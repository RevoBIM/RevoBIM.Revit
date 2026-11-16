using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using Autodesk.Revit.DB;
using RevoBIM.Tools.FilterManager;
using ComboBox = System.Windows.Controls.ComboBox;
using TextBox = System.Windows.Controls.TextBox;
using Panel = System.Windows.Controls.Panel;
using Visibility = System.Windows.Visibility;

using Grid = System.Windows.Controls.Grid;

namespace RevoBIM.UI.FilterManager
{
    // =======================================================================
    //  TAB 2 - FILTER MANAGER TABLE: writing the table back   (script.py 3906-4157)
    // =======================================================================
    public partial class FmWindow
    {
        /// <summary>One filter ready to be written: what Apply Table collected for it.</summary>
        private class TablePayload
        {
            public FmBlock Block;
            public string Name;
            public List<ElementId> Cats;
            public List<FilterRule> Rules;
            public string Match;
        }

        /// <summary>
        /// Does this block hold anything the model does not? Apply works off this rather than trusting the
        /// dirty flag alone. A flag can be missed - a handler that failed quietly, an edit path nobody thought
        /// of - and then Apply writes nothing and says nothing. Comparing against the model cannot be missed.
        /// </summary>
        private bool BlockDiffers(FmBlock block)
        {
            var element = Doc.GetElement(block.Pfe.Id) as ParameterFilterElement;
            if (element == null) return false;
            try
            {
                if (element.Name != block.Name) return true;
            }
            catch (Exception) { }

            try
            {
                var was = element.GetCategories().Select(c => FmCore.EidValue(c)).OrderBy(v => v).ToList();
                var now = block.Cats.Select(c => FmCore.EidValue(c)).OrderBy(v => v).ToList();
                if (!was.SequenceEqual(now)) return true;
            }
            catch (Exception) { }

            string match;
            List<FmRule> rules;
            try
            {
                var read = FmFilters.ReadFilter(Doc, element);
                match = read.Item1;
                rules = read.Item2;
            }
            catch (Exception) { return false; }

            if (block.Probe != null)
            {
                foreach (FmRule rule in rules) TableEnrich(block, rule);
            }
            foreach (FmRule rule in rules) NormaliseRule(rule);
            if (match != block.Match) return true;
            if (rules.Count != block.Rules.Count) return true;
            for (int i = 0; i < rules.Count; i++)
            {
                FmRule was = rules[i];
                FmRule now = block.Rules[i];
                if (FmCore.EidValue(was.ParamId) != FmCore.EidValue(now.ParamId)) return true;
                if (was.Op != now.Op) return true;
                if (!SameValue(was, now)) return true;
            }
            return false;
        }

        private void ApplyTable()
        {
            FmCore.Crumb("apply table: started");
            var dirty = new List<FmBlock>();
            foreach (FmBlock block in tableBlocks)
            {
                // a block nobody has opened cannot have been edited
                if (!block.Hydrated && !block.Dirty) continue;
                if (block.Dirty || BlockDiffers(block))
                {
                    block.Dirty = true;
                    dirty.Add(block);
                }
            }

            FmCore.Crumb("apply table: " + dirty.Count + " filter(s) differ");
            if (dirty.Count == 0)
            {
                FmMessage.Alert("Nothing in the table differs from the model, so there is nothing to write.");
                txtStatus.Text = "Nothing in the table differs from the model.";
                return;
            }

            var names = new Dictionary<long, string>();
            foreach (ParameterFilterElement f in allFilters)
            {
                try { names[FmCore.EidValue(f.Id)] = f.Name; }
                catch (Exception) { continue; }
            }
            foreach (FmBlock block in dirty) names[FmCore.EidValue(block.Pfe.Id)] = block.Name;

            var problems = new List<string>();
            var payload = new List<TablePayload>();
            foreach (FmBlock block in dirty)
            {
                string name = (block.Name ?? "").Trim();
                if (name.Length == 0)
                {
                    problems.Add("A filter has been left with no name.");
                    continue;
                }
                bool clash = false;
                foreach (var pair in names)
                {
                    if (pair.Key != FmCore.EidValue(block.Pfe.Id) &&
                        pair.Value.ToLowerInvariant() == name.ToLowerInvariant())
                    {
                        problems.Add("Two filters would both be called '" + name + "'.");
                        clash = true;
                        break;
                    }
                }
                if (clash) continue;
                if (block.Cats.Count == 0)
                {
                    problems.Add("'" + name + "' has no categories.");
                    continue;
                }

                var rules = new List<FilterRule>();
                bool failed = false;
                for (int index = 0; index < block.Rules.Count; index++)
                {
                    FmRule rule = block.Rules[index];
                    if (rule.ParamId == null || rule.Op == null)
                    {
                        problems.Add("'" + name + "' rule " + (index + 1) + ": no parameter or operator.");
                        failed = true;
                        break;
                    }
                    object raw = rule.Value;
                    if (FmFilters.NeedsValue(rule.Op))
                    {
                        bool blank = raw == null || (!(raw is ElementId) && raw.ToString().Trim().Length == 0);
                        if (blank)
                        {
                            problems.Add("'" + name + "' rule " + (index + 1) + ": no value.");
                            failed = true;
                            break;
                        }
                    }
                    try
                    {
                        rules.Add(FmFilters.BuildRule(Doc, rule.ParamId, rule.Op, raw, rule.Storage ?? "String", rule.Spec, rule.YesNo));
                    }
                    catch (Exception ex)
                    {
                        problems.Add("'" + name + "' rule " + (index + 1) + ": " + ex.Message);
                        failed = true;
                        break;
                    }
                }
                if (!failed)
                    payload.Add(new TablePayload { Block = block, Name = name, Cats = new List<ElementId>(block.Cats), Rules = rules, Match = block.Match });
            }

            if (problems.Count > 0)
            {
                FmMessage.Alert("Nothing was written. Fix these first:\n\n" + string.Join("\n", problems));
                return;
            }
            if (payload.Count == 0)
            {
                // never leave silently: a button that appears to do nothing is
                // indistinguishable from a broken one
                FmMessage.Alert(dirty.Count + " filter(s) are marked as edited but none of them produced anything to write.\n\n" +
                                "This should not happen - please send the log.");
                return;
            }

            FmCore.Crumb("apply table: " + payload.Count + " filter(s) ready to write");
            txtStatus.Text = "Writing " + payload.Count + " filter(s)...";

            var lines = new List<string>();
            var records = new List<Tuple<string, string>>();

            string status = runner.Run(uiapp =>
            {
                using (var t = new Transaction(Doc, "RevoBIM - Edit Filters"))
                {
                    t.Start();
                    TransactionStatus commit;
                    try
                    {
                        foreach (TablePayload item in payload)
                        {
                            var element = Doc.GetElement(item.Block.Pfe.Id) as ParameterFilterElement;
                            if (element == null)
                            {
                                records.Add(Tuple.Create(item.Name, "no longer in the model"));
                                continue;
                            }
                            string oldName = FmFilters.ElementName(Doc, item.Block.Pfe.Id, item.Name);
                            List<string> notes = FmFilters.ApplyFilter(Doc, element, item.Name, item.Cats, item.Rules, item.Match);
                            lines.Add(item.Name + (oldName == item.Name ? "" : "   (was '" + oldName + "')") + "   " +
                                      item.Cats.Count + " categor(ies), " + item.Rules.Count + " rule(s), " +
                                      (item.Match == "AND" ? "ALL rules" : "ANY rule"));
                            foreach (string note in notes) lines.Add("    NOTE: " + note);
                        }

                        commit = t.Commit();
                    }
                    catch (Exception ex)
                    {
                        try { t.RollBack(); }
                        catch (Exception) { }
                        FmMessage.Alert("Nothing was changed:\n\n" + ex);
                        return;
                    }

                    if (commit != TransactionStatus.Committed)
                    {
                        FmMessage.Alert("Revit did not commit the changes (status " + commit + "). Nothing was written.");
                        return;
                    }
                }

                // a void API call is not evidence: read every filter back
                foreach (TablePayload item in payload)
                {
                    var element = Doc.GetElement(item.Block.Pfe.Id) as ParameterFilterElement;
                    if (element == null)
                    {
                        records.Add(Tuple.Create(item.Name, "gone from the model after the write"));
                        continue;
                    }
                    try
                    {
                        if (element.Name != item.Name) records.Add(Tuple.Create(item.Name, "still called '" + element.Name + "'"));
                    }
                    catch (Exception) { }
                    try
                    {
                        int written = element.GetCategories().Count;
                        if (written != item.Cats.Count)
                            records.Add(Tuple.Create(item.Name, written + " categor(ies) written, " + item.Cats.Count + " asked for"));
                    }
                    catch (Exception) { }
                }

                AfterTableApply(lines, records, payload.Count);
            });
            tableLastRequest = status;
            FmCore.Crumb("apply table: Revit answered '" + status + "'");
        }

        private void AfterTableApply(List<string> lines, List<Tuple<string, string>> records, int count)
        {
            FmFilters.ClearCaches();
            if (records.Count > 0)
            {
                lines.Add("");
                lines.Add("DID NOT TAKE");
                foreach (var record in records) lines.Add("  " + record.Item1 + ": " + record.Item2);
            }
            string logPath = WriteLog("FilterManager", lines, "Edited " + count + " filter(s) in the table");
            ReloadFilters(current != null ? current.Id : null);
            tableBlocks = new List<FmBlock>();
            header = null;
            chkTblChanged.IsChecked = false;
            BuildTableTab();
            RefreshFooter();

            string headline = records.Count > 0 ? "Written, but " + records.Count + " did not take." : "Wow you just saved loads of time.";
            txtStatus.Text = count + " filter(s) written.";

            var window = new FmDoneWindow(headline, "Filter Manager Table",
                                          count + " filter(s) written" + (records.Count > 0 ? " - " + records.Count + " need a look" : "") + ".",
                                          "WHAT CHANGED", lines, logPath);
            try { window.Owner = Win; }
            catch (Exception) { }
            window.ShowDialog();
        }
    }
}
