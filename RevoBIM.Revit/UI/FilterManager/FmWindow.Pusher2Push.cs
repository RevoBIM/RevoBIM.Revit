using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using RevoBIM.Tools.FilterManager;
using ComboBox = System.Windows.Controls.ComboBox;
using TextBox = System.Windows.Controls.TextBox;
using Panel = System.Windows.Controls.Panel;
using View = Autodesk.Revit.DB.View;
using Visibility = System.Windows.Visibility;

using Grid = System.Windows.Controls.Grid;

namespace RevoBIM.UI.FilterManager
{
    // =======================================================================
    //  FILTER PUSHER: the push itself (python script.py 5328-5677)
    // =======================================================================
    public partial class FmWindow
    {
        /// <summary>One line of the push record: filter, target, what happened (ADDED, OVERWRITTEN, KEPT, SKIPPED, FAILED) and a note.</summary>
        private class PushRecord
        {
            public string Filter, Target, Action, Note;
            public PushRecord(string filter, string target, string action, string note)
            {
                Filter = filter; Target = target; Action = action; Note = note;
            }
        }

        private class PushCounters
        {
            public int Added, Updated, Failed, Skipped, Kept;
        }

        private void PushFilters()
        {
            HarvestTargets();
            HarvestViews();
            var targets = new List<View>();
            foreach (View t in templates)
            {
                bool ticked;
                if (targetState.TryGetValue(t.Name, out ticked) && ticked) targets.Add(t);
            }
            foreach (FmViewRow row in TickedViewRows())
            {
                var view = Doc.GetElement(row.Id) as View;
                if (view != null) targets.Add(view);
            }

            if (targets.Count == 0)
            {
                FmMessage.Alert("Tick at least one target view template or view.");
                return;
            }

            if (SourceTab() == 1) PushFromProject(targets);
            else PushFromHost(targets);
        }

        // -- push from a host template, carrying its own settings ---------------
        private void PushFromHost(List<View> targets)
        {
            HarvestPush();

            if (host == null)
            {
                FmMessage.Alert("Pick a host view template first.");
                return;
            }

            var filters = new List<Tuple<ElementId, string>>();
            foreach (var pair in hostFilters)
            {
                bool ticked;
                if (pushState.TryGetValue(pair.Item2, out ticked) && ticked) filters.Add(pair);
            }
            long hostVal = FmCore.EidValue(host.Id);
            targets = targets.Where(t => FmCore.EidValue(t.Id) != hostVal).ToList();

            if (filters.Count == 0)
            {
                FmMessage.Alert("Tick at least one filter to push.");
                return;
            }
            if (targets.Count == 0)
            {
                FmMessage.Alert("The host template is the only target ticked.");
                return;
            }

            View hostView = host;
            bool control = chkControl.IsChecked == true;

            Func<ElementId, Tuple<OverrideGraphicSettings, bool, bool>> settingsFor = fid =>
                Tuple.Create(hostView.GetFilterOverrides(fid), hostView.GetFilterVisibility(fid), EnabledOn(hostView, fid));

            var groups = new Dictionary<string, Dictionary<string, bool>>();
            foreach (var pair in filters) groups[pair.Item2] = new Dictionary<string, bool>(PushGroupsFor(pair.Item2));

            Func<ElementId, string, Dictionary<string, bool>> groupsFor = (fid, fname) =>
            {
                Dictionary<string, bool> g;
                return groups.TryGetValue(fname, out g) ? g : null;
            };

            RunPush(filters, targets, settingsFor, control,
                    "Pushed from '" + hostView.Name + "'", "the host template's own settings", null, groupsFor);
        }

        // -- push any filter in the project, with graphics set here -------------
        private void PushFromProject(List<View> targets)
        {
            HarvestTable();

            var filters = new List<Tuple<ElementId, string>>(staged);
            if (filters.Count == 0)
            {
                FmMessage.Alert("Nothing is in the table yet.\n\nTick filters on the left and press the green arrow to bring them in.");
                return;
            }

            var chosen = new Dictionary<long, FmSpec>();
            foreach (var pair in filters) chosen[FmCore.EidValue(pair.Item1)] = SpecFor(pair.Item1);

            Func<ElementId, Tuple<OverrideGraphicSettings, bool, bool>> settingsFor = fid =>
            {
                FmSpec spec;
                if (!chosen.TryGetValue(FmCore.EidValue(fid), out spec) || spec == null) spec = FmOverrides.NewSpec();
                return Tuple.Create(FmOverrides.BuildOverrides(spec), SpecSet(spec["visible"]), SpecSet(spec["enabled"]));
            };

            RunPush(filters, targets, settingsFor, chkControl.IsChecked == true,
                    "Pushed from the project filter table", "the graphics set in the table", chosen, null);
        }

        private static bool EnabledOn(View view, ElementId fid)
        {
            try { return view.GetIsFilterEnabled(fid); }
            catch (Exception) { return true; }
        }

        // -- the write ----------------------------------------------------------
        /// <summary>
        /// Push, then read the model back to see whether it actually took. Element handles captured when the
        /// window opened go stale, especially with a modeless window the user has been working around, so the
        /// target views are re-fetched by id inside the transaction.
        /// </summary>
        private void RunPush(List<Tuple<ElementId, string>> filters, List<View> targets,
                             Func<ElementId, Tuple<OverrideGraphicSettings, bool, bool>> settingsFor, bool control,
                             string subject, string sourceNote, Dictionary<long, FmSpec> chosen,
                             Func<ElementId, string, Dictionary<string, bool>> groupsFor)
        {
            var targetIds = targets.Select(t => t.Id).ToList();
            var filterIds = filters.Select(f => Tuple.Create(f.Item1, f.Item2)).ToList();

            var records = new List<PushRecord>();
            var counters = new PushCounters();
            var skippedIds = new HashSet<long>();
            var lockCache = new Dictionary<long, Tuple<string, bool>>();
            bool newOnly = overwriteMode == "new";

            RunInRevit(uiapp =>
            {
                TransactionStatus status;
                using (var t = new Transaction(Doc, "RevoBIM - Push Filters"))
                {
                    t.Start();
                    try
                    {
                        foreach (ElementId tid in targetIds)
                        {
                            var tv = Doc.GetElement(tid) as View;
                            if (tv == null)
                            {
                                foreach (var f in filterIds)
                                {
                                    counters.Failed++;
                                    records.Add(new PushRecord(f.Item2, "(view gone)", "FAILED", "no longer in the model"));
                                }
                                continue;
                            }

                            string name = FmFilters.TargetLabel(tv);
                            Tuple<string, bool> lockInfo = FmFilters.ViewFilterLock(Doc, tv, lockCache);
                            if (lockInfo.Item2)
                            {
                                // the view refuses AddFilter while its template controls V/G Filters - say so rather than fail
                                skippedIds.Add(FmCore.EidValue(tid));
                                foreach (var f in filterIds)
                                {
                                    counters.Skipped++;
                                    records.Add(new PushRecord(f.Item2, name, "SKIPPED", "filters set by template '" + lockInfo.Item1 + "'"));
                                }
                                continue;
                            }
                            var existing = new HashSet<long>();
                            try
                            {
                                foreach (ElementId e in tv.GetFilters()) existing.Add(FmCore.EidValue(e));
                            }
                            catch (Exception) { }

                            foreach (var f in filterIds)
                            {
                                ElementId fid = f.Item1;
                                string fname = f.Item2;
                                try
                                {
                                    bool hadIt = existing.Contains(FmCore.EidValue(fid));
                                    if (hadIt && newOnly)
                                    {
                                        counters.Kept++;
                                        records.Add(new PushRecord(fname, name, "KEPT", "already there - New Only"));
                                        continue;
                                    }
                                    string action;
                                    if (hadIt) action = "OVERWRITTEN";
                                    else
                                    {
                                        tv.AddFilter(fid);
                                        action = "ADDED";
                                    }

                                    Tuple<OverrideGraphicSettings, bool, bool> settings = settingsFor(fid);
                                    OverrideGraphicSettings overrides = settings.Item1;
                                    bool visible = settings.Item2, enabled = settings.Item3;
                                    Dictionary<string, bool> groups = groupsFor != null ? groupsFor(fid, fname) : null;
                                    if (!FmOverrides.GroupsAllOn(groups))
                                    {
                                        OverrideGraphicSettings baseSettings = hadIt ? tv.GetFilterOverrides(fid) : null;
                                        overrides = FmOverrides.MergeOverrides(overrides, baseSettings, groups);
                                    }
                                    tv.SetFilterOverrides(fid, overrides);
                                    if (GroupTicked(groups, "visible")) tv.SetFilterVisibility(fid, visible);
                                    if (GroupTicked(groups, "enabled"))
                                    {
                                        try { tv.SetIsFilterEnabled(fid, enabled); }
                                        catch (Exception) { }
                                    }

                                    if (action == "ADDED") counters.Added++;
                                    else counters.Updated++;
                                    records.Add(new PushRecord(fname, name, action, ""));
                                }
                                catch (Exception ex)
                                {
                                    counters.Failed++;
                                    records.Add(new PushRecord(fname, name, "FAILED", ex.Message));
                                }
                            }

                            if (control && tv.IsTemplate) EnsureFiltersControlled(tv);
                        }

                        status = t.Commit();
                    }
                    catch (Exception ex)
                    {
                        try { t.RollBack(); }
                        catch (Exception) { }
                        FmMessage.Alert("Push failed and nothing was changed:\n\n" + ex);
                        return;
                    }
                }

                if (status != TransactionStatus.Committed)
                {
                    FmMessage.Alert("Revit did not commit the push (status " + status + "). Nothing was changed.");
                    return;
                }

                // a void API call is not evidence - check the model
                var missing = VerifyPush(targetIds, filterIds, skippedIds);
                AfterPush(records, counters, filterIds, targetIds, subject, sourceNote, chosen, missing);
            });
        }

        /// <summary>groups is None or groups.get(key, True).</summary>
        private static bool GroupTicked(Dictionary<string, bool> groups, string key)
        {
            bool on;
            return groups == null || !groups.TryGetValue(key, out on) || on;
        }

        /// <summary>[(filter name, target name)] that are not on the target.</summary>
        private List<Tuple<string, string>> VerifyPush(List<ElementId> targetIds, List<Tuple<ElementId, string>> filterIds,
                                                       HashSet<long> skip = null)
        {
            var missing = new List<Tuple<string, string>>();
            foreach (ElementId tid in targetIds)
            {
                if (skip != null && skip.Contains(FmCore.EidValue(tid))) continue;
                var tv = Doc.GetElement(tid) as View;
                if (tv == null) continue;
                HashSet<long> present;
                try
                {
                    present = new HashSet<long>();
                    foreach (ElementId f in tv.GetFilters()) present.Add(FmCore.EidValue(f));
                }
                catch (Exception) { continue; }
                string targetName = FmFilters.TargetLabel(tv);
                foreach (var f in filterIds)
                {
                    if (!present.Contains(FmCore.EidValue(f.Item1))) missing.Add(Tuple.Create(f.Item2, targetName));
                }
            }
            return missing;
        }

        private void AfterPush(List<PushRecord> records, PushCounters counters, List<Tuple<ElementId, string>> filters,
                               List<ElementId> targetIds, string subject, string sourceNote, Dictionary<long, FmSpec> chosen,
                               List<Tuple<string, string>> missing)
        {
            int added = counters.Added;
            int updated = counters.Updated;
            int failed = counters.Failed;
            int skipped = counters.Skipped;
            int kept = counters.Kept;

            var byTemplate = new Dictionary<string, List<PushRecord>>();
            var order = new List<string>();
            foreach (PushRecord r in records)
            {
                if (!byTemplate.ContainsKey(r.Target))
                {
                    byTemplate[r.Target] = new List<PushRecord>();
                    order.Add(r.Target);
                }
                byTemplate[r.Target].Add(r);
            }

            var body = new List<string>();
            body.Add("Source: " + sourceNote);
            body.Add("Targets: " + targetIds.Count + "   Filters added: " + added + "   Overwritten: " + updated +
                     "   Kept: " + kept + "   Failed: " + failed + "   Skipped: " + skipped);
            body.Add("Mode: " + OverwriteLabel(overwriteMode));
            if (chosen == null || chosen.Count == 0)
            {
                body.Add("");
                body.Add("SETTINGS PUSHED");
                foreach (var f in filters)
                {
                    Dictionary<string, bool> g;
                    pushGroups.TryGetValue(f.Item2, out g);
                    body.Add("  " + f.Item2 + ": " + FmOverrides.DescribeGroups(g));
                }
            }
            if (chosen != null && chosen.Count > 0)
            {
                body.Add("");
                body.Add("GRAPHICS ASSIGNED");
                foreach (var f in filters)
                {
                    FmSpec spec;
                    if (chosen.TryGetValue(FmCore.EidValue(f.Item1), out spec) && spec != null)
                        body.Add("  " + f.Item2 + ": " + FmOverrides.Describe(spec));
                }
            }
            body.Add("");
            body.Add("WHAT WENT WHERE");
            foreach (string tname in order)
            {
                body.Add("");
                body.Add("  " + tname);
                foreach (PushRecord r in byTemplate[tname])
                    body.Add("      " + r.Filter + "  [" + r.Action + "]" + (r.Note.Length > 0 ? "  " + r.Note : ""));
            }
            if (missing.Count > 0)
            {
                body.Add("");
                body.Add("NOT ON THE TARGET AFTERWARDS");
                foreach (var m in missing) body.Add("  " + m.Item1 + "  ->  " + m.Item2);
            }

            string logPath = WriteLog("FilterPusher", body, subject);

            var lines = new List<string>();
            foreach (string tname in order)
            {
                lines.Add(tname);
                foreach (PushRecord r in byTemplate[tname])
                    lines.Add("     " + r.Filter + "   [" + r.Action + "]" + (r.Note.Length > 0 ? "  -  " + r.Note : ""));
                lines.Add("");
            }
            if (missing.Count > 0)
            {
                lines.Add("NOT ON THE TARGET AFTERWARDS:");
                foreach (var m in missing) lines.Add("     " + m.Item1 + "  ->  " + m.Item2);
            }

            ReloadTemplates(host != null ? host.Id : null);
            RefreshFooter();

            string headline;
            if (missing.Count > 0) headline = "Pushed, but " + missing.Count + " did not stick.";
            else if (failed > 0) headline = "Pushed, with " + failed + " failure(s).";
            else if ((skipped > 0 || kept > 0) && !(added > 0 || updated > 0))
                headline = kept > 0 && skipped == 0
                    ? "Nothing changed - every filter was already there."
                    : "Nothing pushed - every view takes its filters from a template.";
            else headline = "Wow you just saved loads of time.";

            string stats = filters.Count + " filter(s) pushed to " + targetIds.Count + " target(s)   -   " +
                           added + " added, " + updated + " overwritten, " + failed + " failed";
            if (kept > 0) stats += ", " + kept + " kept (already there)";
            if (skipped > 0) stats += ", " + skipped + " skipped (template-controlled)";

            var window = new FmDoneWindow(headline, "Filter Pusher", stats, "WHAT WENT WHERE", lines, logPath);
            window.Owner = Win;
            window.ShowDialog();
        }

        /// <summary>Take V/G Filters out of the template's non-controlled list.</summary>
        private void EnsureFiltersControlled(View tv)
        {
            try
            {
                var pid = new ElementId(BuiltInParameter.VIS_GRAPHICS_FILTERS);
                long target = FmCore.EidValue(pid);
                var keep = new List<ElementId>();
                bool hit = false;
                foreach (ElementId e in tv.GetNonControlledTemplateParameterIds())
                {
                    if (FmCore.EidValue(e) == target) hit = true;
                    else keep.Add(e);
                }
                if (hit) tv.SetNonControlledTemplateParameterIds(keep);
            }
            catch (Exception) { }
        }
    }
}

