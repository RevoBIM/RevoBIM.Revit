using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using RevoBIM.Tools.FilterManager;
using ComboBox = System.Windows.Controls.ComboBox;
using TextBox = System.Windows.Controls.TextBox;
using Panel = System.Windows.Controls.Panel;
using Visibility = System.Windows.Visibility;

using Grid = System.Windows.Controls.Grid;

namespace RevoBIM.UI.FilterManager
{
    // =======================================================================
    //  TAB 1 - FILTER MANAGER
    // =======================================================================
    public partial class FmWindow
    {
        private void ReloadFilters(ElementId selectId = null)
        {
            allFilters = FmFilters.GetAllFilters(Doc);
            if (ReadFilterUsage)
            {
                FmCore.Crumb("model: counting filter use across every view");
                usage = FmFilters.FilterUsage(Doc);
                FmCore.Crumb("model: filter use counted");
            }
            else usage = new Dictionary<long, int>();
            FillFilterList(selectId);
            try { FillAllFilters(); }
            catch (Exception) { }
        }

        private int UsageOf(ElementId id)
        {
            int n;
            return usage.TryGetValue(FmCore.EidValue(id), out n) ? n : 0;
        }

        private void FillFilterList(ElementId selectId = null)
        {
            string search = txtFmSearch.Text;
            bool unusedOnly = chkUnusedOnly.IsChecked == true;
            lstFilters.Items.Clear();
            filterRows = new List<FmFilterRow>();
            inlineRow = null;

            int shown = 0, unused = 0;
            foreach (ParameterFilterElement f in allFilters)
            {
                string nm;
                try { nm = f.Name; }
                catch (Exception) { continue; }
                int used = ReadFilterUsage ? UsageOf(f.Id) : 0;
                if (ReadFilterUsage && used == 0) unused++;
                if (!FmCore.RowVisible(nm, used, search, unusedOnly)) continue;

                string label = ReadFilterUsage ? nm + "   (" + used + " view" + (used == 1 ? "" : "s") + ")" : nm;
                ListBoxItem item = FilterRow(f, nm, label);
                lstFilters.Items.Add(item);
                shown++;
                if (selectId != null && FmCore.EidValue(f.Id) == FmCore.EidValue(selectId)) item.IsSelected = true;
            }

            if (!ReadFilterUsage)
            {
                chkUnusedOnly.IsEnabled = false;
                chkUnusedOnly.Content = "Only filters no view uses  (counting is off)";
                txtFmCount.Text = shown + " of " + allFilters.Count + " filters";
            }
            else if (unusedOnly) txtFmCount.Text = shown + " of " + unused + " unused filters";
            else txtFmCount.Text = shown + " of " + allFilters.Count + " filters   -   " + unused + " unused";
        }

        public void OnUnusedOnly(object sender, RoutedEventArgs args)
        {
            FillFilterList(current != null ? current.Id : null);
            RefreshFooter();
        }

        /// <summary>A list row that can turn into a text box for renaming in place.</summary>
        private ListBoxItem FilterRow(ParameterFilterElement pfe, string name, string label)
        {
            var item = new ListBoxItem { Tag = pfe, Padding = new Thickness(0) };
            var grid = new Grid { Margin = new Thickness(6, 3, 6, 3) };

            var block = new TextBlock { Text = label, TextTrimming = FmUi.Trim() };
            grid.Children.Add(block);

            var box = new TextBox { Text = name, Height = 24 };
            FmUi.SetVisible(box, false);
            grid.Children.Add(box);

            var row = new FmFilterRow { Item = item, Pfe = pfe, Name = name, Label = block, Box = box };

            box.KeyDown += FmUi.SafeKey((s, a) =>
            {
                if (a.Key == Key.Enter)
                {
                    CommitInlineRename(row);
                    a.Handled = true;
                }
                else if (a.Key == Key.Escape)
                {
                    CancelInlineRename(row);
                    a.Handled = true;
                }
            }, "inline rename key");
            box.LostKeyboardFocus += (s, a) => FmUi.Guard("inline rename", () => CommitInlineRename(row));

            item.Content = grid;
            filterRows.Add(row);
            return item;
        }

        // -- renaming in place ----------------------------------------------------
        private void BeginInlineRename(FmFilterRow row)
        {
            if (inlineRow != null && !ReferenceEquals(inlineRow, row)) CancelInlineRename(inlineRow);
            inlineRow = row;
            row.Box.Text = row.Name;
            FmUi.SetVisible(row.Label, false);
            FmUi.SetVisible(row.Box, true);
            try
            {
                row.Box.Focus();
                row.Box.SelectAll();
            }
            catch (Exception) { }
        }

        private void CancelInlineRename(FmFilterRow row)
        {
            FmUi.SetVisible(row.Box, false);
            FmUi.SetVisible(row.Label, true);
            if (ReferenceEquals(inlineRow, row)) inlineRow = null;
        }

        private void CommitInlineRename(FmFilterRow row)
        {
            if (!ReferenceEquals(inlineRow, row)) return;
            string wanted = row.Box.Text.Trim();
            CancelInlineRename(row);

            if (wanted.Length == 0 || wanted == row.Name) return;
            foreach (ParameterFilterElement f in allFilters)
            {
                try
                {
                    if (FmCore.EidValue(f.Id) != FmCore.EidValue(row.Pfe.Id) &&
                        string.Equals(f.Name, wanted, StringComparison.OrdinalIgnoreCase))
                    {
                        FmMessage.Alert("Another filter is already called '" + wanted + "'.");
                        return;
                    }
                }
                catch (Exception) { }
            }
            RenameBatch(new List<KeyValuePair<ElementId, string>> { new KeyValuePair<ElementId, string>(row.Pfe.Id, wanted) },
                        "Renamed '" + row.Name + "'");
        }

        /// <summary>Double clicking a filter renames it where it sits.</summary>
        public void OnFilterDblclick(object sender, RoutedEventArgs args)
        {
            var item = lstFilters.SelectedItem as ListBoxItem;
            if (item == null) return;
            foreach (FmFilterRow row in filterRows)
            {
                if (ReferenceEquals(row.Item, item))
                {
                    BeginInlineRename(row);
                    try { if (args != null) args.Handled = true; }
                    catch (Exception) { }
                    return;
                }
            }
        }

        // -- the right click menu -------------------------------------------------
        public void OnCtxDuplicate(object sender, RoutedEventArgs args) { OnDuplicateFilter(sender, args); }
        public void OnCtxRename(object sender, RoutedEventArgs args) { OnFilterDblclick(sender, args); }
        public void OnCtxBatch(object sender, RoutedEventArgs args) { OnRenameBatch(sender, args); }
        public void OnCtxDelete(object sender, RoutedEventArgs args) { OnDeleteFilter(sender, args); }

        public void OnFmSearch(object sender, RoutedEventArgs args) { searches["filters"].Poke(); }

        private void RunFmSearch() { FillFilterList(current != null ? current.Id : null); }

        private List<ParameterFilterElement> SelectedFiltersInList()
        {
            var picked = new List<ParameterFilterElement>();
            try
            {
                foreach (object o in lstFilters.SelectedItems)
                {
                    var item = o as ListBoxItem;
                    var pfe = item == null ? null : item.Tag as ParameterFilterElement;
                    if (pfe != null) picked.Add(pfe);
                }
            }
            catch (Exception) { }
            return picked;
        }

        public void OnFilterChanged(object sender, SelectionChangedEventArgs args)
        {
            ListBoxItem item = null;
            try
            {
                if (args.AddedItems != null && args.AddedItems.Count > 0) item = args.AddedItems[args.AddedItems.Count - 1] as ListBoxItem;
            }
            catch (Exception) { item = null; }
            if (item == null) item = lstFilters.SelectedItem as ListBoxItem;
            if (item != null) LoadFilter((ParameterFilterElement)item.Tag);
            RefreshFooter();
        }

        private void LoadFilter(ParameterFilterElement pfe)
        {
            loading = true;
            try
            {
                current = pfe;
                txtFilterName.Text = pfe.Name;

                var picked = new HashSet<long>(FmFilters.FilterCategoryIds(pfe).Select(c => FmCore.EidValue(c)));
                catState = new Dictionary<string, bool>();
                foreach (var c in allCategories) catState[c.Item2] = picked.Contains(FmCore.EidValue(c.Item1));
                FillCategories();

                RebuildParameterContext();

                var read = FmFilters.ReadFilter(Doc, pfe);
                cboMatch.SelectedIndex = read.Item1 == "OR" ? 1 : 0;

                pnlRules.Children.Clear();
                ruleRows = new List<FmRuleRow>();
                var notes = new List<string>();
                foreach (FmRule r in read.Item2)
                {
                    FmRuleRow row = AddRuleRow(r);
                    if (row != null && !string.IsNullOrEmpty(row.Note)) notes.Add(row.Note);
                }
                txtRuleNote.Text = notes.Count > 0 ? string.Join("  ", notes) : "";
            }
            finally { loading = false; }
            RefreshFooter();
        }

        /// <summary>Sample elements and the shared parameter list for the ticked cats.</summary>
        private void RebuildParameterContext()
        {
            List<ElementId> catIds = TickedCategoryIds();
            paramList = FmFilters.CommonParameters(Doc, catIds);
            probe = FmFilters.ProbeFor(Doc, catIds);
        }

        // -- categories -----------------------------------------------------------
        private void FillCategories()
        {
            string search = txtCatSearch.Text;
            bool usedOnly = chkCatUsedOnly.IsChecked == true;
            lstCategories.Items.Clear();
            foreach (var c in allCategories)
            {
                bool on;
                catState.TryGetValue(c.Item2, out on);
                if (usedOnly && !on) continue;
                if (!FmCore.RowVisible(c.Item2, 0, search, false)) continue;
                CheckBox cb = FmUi.NewCheckBox(c.Item2, c.Item1, on);
                cb.Checked += FmUi.Safe(OnCatTicked, "on_cat_ticked");
                cb.Unchecked += FmUi.Safe(OnCatTicked, "on_cat_ticked");
                lstCategories.Items.Add(cb);
            }
        }

        private void HarvestCategories()
        {
            foreach (CheckBox item in lstCategories.Items.OfType<CheckBox>())
                catState[(string)item.Content] = item.IsChecked == true;
        }

        private List<ElementId> TickedCategoryIds()
        {
            return allCategories.Where(c => { bool on; return catState.TryGetValue(c.Item2, out on) && on; }).Select(c => c.Item1).ToList();
        }

        private int TickedCategoryCount() { return catState.Values.Count(v => v); }

        public void OnCatSearch(object sender, RoutedEventArgs args) { HarvestCategories(); FillCategories(); }
        public void OnCatScope(object sender, RoutedEventArgs args) { HarvestCategories(); FillCategories(); }

        public void OnCatTicked(object sender, RoutedEventArgs args)
        {
            if (loading) return;
            HarvestCategories();
            RebuildParameterContext();
            RefreshParameterCombos();
            RefreshFooter();
        }

        public void OnCatsAll(object sender, RoutedEventArgs args)
        {
            foreach (CheckBox item in lstCategories.Items.OfType<CheckBox>()) item.IsChecked = true;
            OnCatTicked(null, null);
        }

        public void OnCatsNone(object sender, RoutedEventArgs args)
        {
            foreach (CheckBox item in lstCategories.Items.OfType<CheckBox>()) item.IsChecked = false;
            OnCatTicked(null, null);
        }

        public void OnNameTyped(object sender, RoutedEventArgs args) { if (!loading) RefreshFooter(); }
        public void OnMatchChanged(object sender, RoutedEventArgs args) { if (!loading) RefreshFooter(); }

        // -- rules ----------------------------------------------------------------
        /// <summary>One editable rule row: parameter, operator, value, remove.</summary>
        private FmRuleRow AddRuleRow(FmRule rule = null)
        {
            var row = new FmRuleRow();
            var grid = new Grid { Margin = new Thickness(0, 0, 0, 5) };
            grid.ColumnDefinitions.Add(FmUi.Col(2.2));
            grid.ColumnDefinitions.Add(FmUi.Col(1.8));
            grid.ColumnDefinitions.Add(FmUi.Col(2.0));
            grid.ColumnDefinitions.Add(FmUi.Col(pixels: 34));

            var names = paramList.Select(p => p.Item2).ToList();
            var tags = paramList.Select(p => (object)p.Item1).ToList();
            string note = "";
            int idx = names.Count > 0 ? 0 : -1;

            if (rule != null)
            {
                long want = FmCore.EidValue(rule.ParamId);
                idx = -1;
                for (int i = 0; i < tags.Count; i++)
                {
                    if (FmCore.EidValue((ElementId)tags[i]) == want) { idx = i; break; }
                }
                if (idx < 0)
                {
                    // the rule points at a parameter these categories do not share - keep it visible rather than dropping it silently
                    string extra = FmFilters.ParameterName(Doc, rule.ParamId);
                    names.Insert(0, extra + "   (not shared by these categories)");
                    tags.Insert(0, rule.ParamId);
                    idx = 0;
                    note = "A rule uses a parameter these categories do not share.";
                }
            }

            ComboBox cboParam = FmUi.NewCombo(names, idx, tags: tags);
            cboParam.Margin = new Thickness(0, 0, 6, 0);
            Grid.SetColumn(cboParam, 0);
            grid.Children.Add(cboParam);

            ComboBox cboOp = FmUi.NewCombo(new string[0], -1);
            cboOp.Margin = new Thickness(0, 0, 6, 0);
            Grid.SetColumn(cboOp, 1);
            grid.Children.Add(cboOp);

            var hostControl = new ContentControl { Margin = new Thickness(0, 0, 6, 0) };
            Grid.SetColumn(hostControl, 2);
            grid.Children.Add(hostControl);

            Button kill = FmUi.NewButton("X", "RowKill", width: 28, height: 26);
            kill.HorizontalAlignment = HorizontalAlignment.Right;
            Grid.SetColumn(kill, 3);
            grid.Children.Add(kill);

            row.Grid = grid;
            row.Param = cboParam;
            row.Op = cboOp;
            row.Host = hostControl;
            row.Editor = null;
            row.Storage = "String";
            row.Spec = null;
            row.YesNo = false;
            row.Note = note;
            row.Busy = false;

            cboParam.SelectionChanged += FmUi.SafeSelection((s, a) => { if (!row.Busy) RebuildOperators(row, null, true); }, "rule parameter");
            cboOp.SelectionChanged += FmUi.SafeSelection((s, a) => { if (!row.Busy) RebuildValueEditor(row); }, "rule operator");
            kill.Click += FmUi.Safe((s, a) => RemoveRuleRow(row), "remove rule");

            pnlRules.Children.Add(grid);
            ruleRows.Add(row);

            RebuildOperators(row, rule == null ? null : rule.Op);
            if (rule != null) SeedValue(row, rule);
            return row;
        }

        private void RebuildOperators(FmRuleRow row, string wantedOp = null, bool keepOp = false)
        {
            var pid = FmUi.ComboTag(row.Param) as ElementId;
            string storage = "String";
            ForgeTypeId spec = null;
            bool yesno = false;
            if (pid != null && probe != null)
            {
                var found = probe.Find(pid);
                storage = found.Item1;
                spec = found.Item2;
                yesno = found.Item3;
            }
            row.Storage = storage;
            row.Spec = spec;
            row.YesNo = yesno;

            string previous = keepOp ? FmUi.ComboText(row.Op) : null;

            row.Busy = true;
            try
            {
                string[] keys = FmFilters.OpsForStorage(storage, yesno);
                var labels = keys.Select(k => FmFilters.OpLabel[k]).ToList();
                row.Op.Items.Clear();
                for (int i = 0; i < keys.Length; i++) row.Op.Items.Add(FmUi.ComboItem(labels[i], keys[i]));

                int target = 0;
                if (!string.IsNullOrEmpty(wantedOp) && Array.IndexOf(keys, wantedOp) >= 0) target = Array.IndexOf(keys, wantedOp);
                else if (!string.IsNullOrEmpty(previous) && labels.Contains(previous)) target = labels.IndexOf(previous);
                row.Op.SelectedIndex = target;
            }
            finally { row.Busy = false; }

            RebuildValueEditor(row);
        }

        private void RebuildValueEditor(FmRuleRow row)
        {
            string op = FmUi.ComboTag(row.Op) as string ?? "equals";
            string storage = row.Storage;

            if (!FmFilters.NeedsValue(op))
            {
                row.Host.Content = null;
                row.Editor = null;
                return;
            }

            object keep = "";
            try
            {
                if (row.Editor != null)
                {
                    keep = ReadEditor(row);
                    if (keep is ElementId) keep = "";
                }
            }
            catch (Exception) { keep = ""; }

            FrameworkElement editor;
            if (storage == "Integer" && row.YesNo)
                editor = FmUi.NewCombo(new[] { "Yes", "No" }, 0, tags: new List<object> { "1", "0" });
            else if (storage == "ElementId")
            {
                var values = new List<Tuple<ElementId, string>>();
                if (probe != null) values = probe.IdValues(FmUi.ComboTag(row.Param) as ElementId);
                if (values.Count > 0)
                    editor = FmUi.NewCombo(values.Select(v => v.Item2).ToList(), 0, tags: values.Select(v => (object)v.Item1).ToList());
                else editor = FmUi.NewTextBox("", "element id");
            }
            else
            {
                string hint = "";
                if (storage == "Double") hint = FmFilters.UnitLabel(Doc, row.Spec);
                editor = FmUi.NewTextBox(keep == null ? "" : keep.ToString(), hint);
            }

            row.Host.Content = editor;
            row.Editor = editor;
        }

        private object ReadEditor(FmRuleRow row)
        {
            FrameworkElement ed = row.Editor;
            if (ed == null) return "";
            var combo = ed as ComboBox;
            if (combo != null)
            {
                object tag = FmUi.ComboTag(combo);
                return tag ?? FmUi.ComboText(combo);
            }
            var box = ed as TextBox;
            return box != null ? box.Text : "";
        }

        private void SeedValue(FmRuleRow row, FmRule rule)
        {
            if (!FmFilters.NeedsValue(rule.Op)) return;
            string storage = row.Storage;
            object value = rule.Value;
            FrameworkElement ed = row.Editor;
            if (ed == null) return;

            try
            {
                var combo = ed as ComboBox;
                if (combo != null)
                {
                    if (storage == "Integer" && row.YesNo)
                    {
                        string s = value == null ? "" : value.ToString();
                        FmUi.SelectByTag(combo, s == "1" || s == "True" ? "1" : "0");
                    }
                    else if (storage == "ElementId")
                    {
                        var wanted = value as ElementId;
                        bool hit = wanted != null && FmUi.SelectByTag(combo, wanted,
                            (a, b) => a is ElementId && b is ElementId && FmCore.EidValue((ElementId)a) == FmCore.EidValue((ElementId)b));
                        if (!hit && wanted != null)
                        {
                            string nm = FmFilters.ElementName(Doc, wanted, FmCore.EidValue(wanted).ToString());
                            combo.Items.Insert(0, FmUi.ComboItem(nm, wanted));
                            combo.SelectedIndex = 0;
                        }
                    }
                    return;
                }
            }
            catch (Exception) { }

            try
            {
                var box = (TextBox)ed;
                if (storage == "Double")
                {
                    double shown = FmFilters.ToDisplay(Doc, Convert.ToDouble(value), row.Spec);
                    box.Text = Math.Round(shown, 6).ToString(System.Globalization.CultureInfo.InvariantCulture);
                }
                else box.Text = value == null ? "" : Convert.ToString(value, System.Globalization.CultureInfo.InvariantCulture);
            }
            catch (Exception) { }
        }

        /// <summary>Categories changed, so the shared parameter list changed too.</summary>
        private void RefreshParameterCombos()
        {
            foreach (FmRuleRow row in ruleRows)
            {
                var keep = FmUi.ComboTag(row.Param) as ElementId;
                row.Busy = true;
                try
                {
                    row.Param.Items.Clear();
                    foreach (var p in paramList) row.Param.Items.Add(FmUi.ComboItem(p.Item2, p.Item1));
                    bool hit = false;
                    if (keep != null)
                        hit = FmUi.SelectByTag(row.Param, keep,
                            (a, b) => a is ElementId && b is ElementId && FmCore.EidValue((ElementId)a) == FmCore.EidValue((ElementId)b));
                    if (!hit && row.Param.Items.Count > 0) row.Param.SelectedIndex = 0;
                }
                finally { row.Busy = false; }
                RebuildOperators(row, null, true);
            }
        }

        public void OnAddRule(object sender, RoutedEventArgs args)
        {
            if (current == null)
            {
                FmMessage.Alert("Pick a filter first, or press Create Filter.");
                return;
            }
            if (paramList.Count == 0)
            {
                FmMessage.Alert("These categories share no filterable parameters.\n\nTick fewer categories and try again.");
                return;
            }
            AddRuleRow(null);
            RefreshFooter();
        }

        private void RemoveRuleRow(FmRuleRow row)
        {
            try { pnlRules.Children.Remove(row.Grid); }
            catch (Exception) { }
            ruleRows.Remove(row);
            RefreshFooter();
        }

        // -- apply ----------------------------------------------------------------
        /// <summary>The FilterRules, and the problems found building them.</summary>
        private Tuple<List<FilterRule>, List<string>> CollectRules()
        {
            var rules = new List<FilterRule>();
            var problems = new List<string>();
            for (int i = 0; i < ruleRows.Count; i++)
            {
                FmRuleRow row = ruleRows[i];
                var pid = FmUi.ComboTag(row.Param) as ElementId;
                var op = FmUi.ComboTag(row.Op) as string;
                if (pid == null || op == null)
                {
                    problems.Add("Rule " + (i + 1) + ": no parameter or operator picked.");
                    continue;
                }
                object raw = ReadEditor(row);
                if (FmFilters.NeedsValue(op))
                {
                    bool blank = raw == null || (!(raw is ElementId) && raw.ToString().Trim().Length == 0);
                    if (blank)
                    {
                        problems.Add("Rule " + (i + 1) + " (" + FmFilters.ParameterName(Doc, pid) + "): no value entered.");
                        continue;
                    }
                }
                try { rules.Add(FmFilters.BuildRule(Doc, pid, op, raw, row.Storage, row.Spec, row.YesNo)); }
                catch (Exception ex)
                {
                    problems.Add("Rule " + (i + 1) + " (" + FmFilters.ParameterName(Doc, pid) + "): " + ex.Message);
                }
            }
            return Tuple.Create(rules, problems);
        }

        private void ApplyChanges()
        {
            if (current == null) return;

            HarvestCategories();
            string name = txtFilterName.Text.Trim();
            List<ElementId> cats = TickedCategoryIds();

            if (name.Length == 0)
            {
                FmMessage.Alert("The filter needs a name.");
                return;
            }
            if (cats.Count == 0)
            {
                FmMessage.Alert("A filter must apply to at least one category.");
                return;
            }
            foreach (ParameterFilterElement f in allFilters)
            {
                try
                {
                    if (FmCore.EidValue(f.Id) != FmCore.EidValue(current.Id) &&
                        string.Equals(f.Name, name, StringComparison.OrdinalIgnoreCase))
                    {
                        FmMessage.Alert("Another filter is already called '" + name + "'.");
                        return;
                    }
                }
                catch (Exception) { }
            }

            var collected = CollectRules();
            List<FilterRule> rules = collected.Item1;
            if (collected.Item2.Count > 0)
            {
                FmMessage.Alert("Nothing was written. Fix these first:\n\n" + string.Join("\n", collected.Item2));
                return;
            }
            txtStatus.Text = "Writing '" + name + "'...";

            string match = MatchKeys[Math.Max(0, cboMatch.SelectedIndex)];
            string oldName = current.Name;
            ElementId fid = current.Id;

            var lines = new List<string>
            {
                "Filter        : " + name,
            };
            if (oldName != name) lines.Add("Renamed from  : " + oldName);
            lines.Add("Categories    : " + cats.Count);
            lines.Add("Match         : " + (match == "AND" ? "ALL rules (AND)" : "ANY rule (OR)"));
            lines.Add("Rules written : " + rules.Count);
            lines.Add("");
            for (int i = 0; i < ruleRows.Count; i++)
            {
                FmRuleRow row = ruleRows[i];
                var pid = FmUi.ComboTag(row.Param) as ElementId;
                var op = FmUi.ComboTag(row.Op) as string;
                object val = ReadEditor(row);
                var valId = val as ElementId;
                if (valId != null) val = FmFilters.ElementName(Doc, valId, FmCore.EidValue(valId).ToString());
                lines.Add("  " + (i + 1) + ". " + FmFilters.ParameterName(Doc, pid) + "   " + (op != null && FmFilters.OpLabel.ContainsKey(op) ? FmFilters.OpLabel[op] : op) + "   " + val);
            }

            ParameterFilterElement target = current;

            RunInRevit(uiapp =>
            {
                List<string> notes;
                using (var t = new Transaction(Doc, "RevoBIM - Edit Filter"))
                {
                    t.Start();
                    try
                    {
                        notes = FmFilters.ApplyFilter(Doc, target, name, cats, rules, match);
                        t.Commit();
                    }
                    catch (Exception ex)
                    {
                        try { t.RollBack(); }
                        catch (Exception) { }
                        FmMessage.Alert("Nothing was changed:\n\n" + ex);
                        return;
                    }
                }
                AfterApply(notes, lines, name, cats, rules, fid);
            });
        }

        private void AfterApply(List<string> notes, List<string> lines, string name, List<ElementId> cats, List<FilterRule> rules, ElementId fid)
        {
            FmFilters.ClearCaches();
            foreach (string n in notes) lines.Add("NOTE: " + n);

            int used = UsageOf(fid);
            string logPath = WriteLog("FilterManager", lines, "Edited filter '" + name + "'");

            ReloadFilters(fid);
            ReloadTemplates(host != null ? host.Id : null);
            foreach (ListBoxItem item in lstFilters.Items.OfType<ListBoxItem>())
            {
                try
                {
                    var pfe = (ParameterFilterElement)item.Tag;
                    if (FmCore.EidValue(pfe.Id) == FmCore.EidValue(fid))
                    {
                        current = pfe;
                        break;
                    }
                }
                catch (Exception) { }
            }
            RefreshFooter();

            var done = new FmDoneWindow(
                "Wow you just saved loads of time.",
                "Filter Manager",
                rules.Count + " rule(s) and " + cats.Count + " categor(ies) written to '" + name + "'. It is used by " + used + " view(s) or template(s).",
                "WHAT CHANGED", lines, logPath);
            done.Owner = Win;
            done.ShowDialog();
        }

        // -- duplicate ------------------------------------------------------------
        public void OnDuplicateFilter(object sender, RoutedEventArgs args)
        {
            if (current == null)
            {
                txtStatus.Text = "Pick a filter to duplicate.";
                return;
            }

            ParameterFilterElement source = current;
            var taken = new List<string>();
            foreach (ParameterFilterElement f in allFilters)
            {
                try { taken.Add(f.Name); }
                catch (Exception) { }
            }
            string newName = FmNames.DuplicateName(source.Name, taken);
            string oldName = source.Name;

            RunInRevit(uiapp =>
            {
                ParameterFilterElement copy;
                using (var t = new Transaction(Doc, "RevoBIM - Duplicate Filter"))
                {
                    t.Start();
                    try
                    {
                        copy = FmFilters.DuplicateFilter(Doc, source, newName);
                        t.Commit();
                    }
                    catch (Exception ex)
                    {
                        try { t.RollBack(); }
                        catch (Exception) { }
                        FmMessage.Alert("The filter was not duplicated:\n\n" + ex);
                        return;
                    }
                }
                AfterDuplicate(copy, oldName, newName);
            });
        }

        /// <summary>Land on the copy with its settings open, ready to be changed.</summary>
        private void AfterDuplicate(ParameterFilterElement copy, string oldName, string newName)
        {
            ReloadFilters(copy.Id);
            foreach (ListBoxItem item in lstFilters.Items.OfType<ListBoxItem>())
            {
                try
                {
                    var pfe = (ParameterFilterElement)item.Tag;
                    if (FmCore.EidValue(pfe.Id) == FmCore.EidValue(copy.Id))
                    {
                        lstFilters.SelectedItems.Clear();
                        item.IsSelected = true;
                        lstFilters.ScrollIntoView(item);
                        LoadFilter(pfe);
                        break;
                    }
                }
                catch (Exception) { }
            }
            try
            {
                txtFilterName.Focus();
                txtFilterName.SelectAll();
            }
            catch (Exception) { }
            RefreshFooter();
            txtStatus.Text = "Duplicated '" + oldName + "' as '" + newName + "' - its categories and rules are open on the right.";
        }

        // -- batch rename ---------------------------------------------------------
        public void OnRenameBatch(object sender, RoutedEventArgs args)
        {
            List<ParameterFilterElement> picked = SelectedFiltersInList();
            if (picked.Count == 0)
            {
                txtStatus.Text = "Select the filters you want to rename.";
                return;
            }

            var existing = new List<string>();
            foreach (ParameterFilterElement f in allFilters)
            {
                try { existing.Add(f.Name); }
                catch (Exception) { }
            }

            var rows = picked.Select(p => new KeyValuePair<object, string>(p.Id, p.Name)).ToList();
            var dlg = new FmRenameWindow(rows, existing);
            dlg.Owner = Win;
            dlg.ShowDialog();
            if (dlg.Result == null || dlg.Result.Count == 0) return;
            RenameBatch(dlg.Result.Select(r => new KeyValuePair<ElementId, string>((ElementId)r.Key, r.Value)).ToList(),
                        "Renamed " + dlg.Result.Count + " filter(s)");
        }

        /// <summary>
        /// Write the new names, in two passes through a parked name: a batch that swaps two names round, or
        /// shuffles a set along by one, clashes with itself in a single pass.
        /// </summary>
        private void RenameBatch(List<KeyValuePair<ElementId, string>> pairs, string subject)
        {
            var taken = new List<string>();
            foreach (ParameterFilterElement f in allFilters)
            {
                try { taken.Add(f.Name); }
                catch (Exception) { }
            }
            List<string> parked = FmNames.ParkingNames(pairs.Count, taken);
            var records = new List<Tuple<string, string, string>>();   // old, new, problem ("" when fine)

            RunInRevit(uiapp =>
            {
                using (var t = new Transaction(Doc, "RevoBIM - Rename Filters"))
                {
                    t.Start();
                    try
                    {
                        var elements = new List<Tuple<Element, string, string>>();
                        for (int index = 0; index < pairs.Count; index++)
                        {
                            Element element = Doc.GetElement(pairs[index].Key);
                            if (element == null)
                            {
                                records.Add(Tuple.Create("(gone)", pairs[index].Value, "no longer in the model"));
                                continue;
                            }
                            string old = element.Name;
                            if (!FmFilters.SetElementName(element, parked[index]))
                            {
                                records.Add(Tuple.Create(old, pairs[index].Value, "Revit would not take a temporary name"));
                                continue;
                            }
                            elements.Add(Tuple.Create(element, old, pairs[index].Value));
                        }

                        foreach (var e in elements)
                        {
                            if (FmFilters.SetElementName(e.Item1, e.Item3)) records.Add(Tuple.Create(e.Item2, e.Item3, ""));
                            else records.Add(Tuple.Create(e.Item2, e.Item3, "Revit would not take the new name"));
                        }
                        t.Commit();
                    }
                    catch (Exception ex)
                    {
                        try { t.RollBack(); }
                        catch (Exception) { }
                        FmMessage.Alert("Nothing was renamed:\n\n" + ex);
                        return;
                    }
                }
                AfterRename(records, subject);
            });
        }

        private void AfterRename(List<Tuple<string, string, string>> records, string subject)
        {
            var done = records.Where(r => r.Item3.Length == 0).ToList();
            var failed = records.Where(r => r.Item3.Length > 0).ToList();

            ElementId keep = current != null ? current.Id : null;
            ReloadFilters(keep);
            ReloadTemplates(host != null ? host.Id : null);
            if (keep != null)
            {
                foreach (ParameterFilterElement f in allFilters)
                {
                    if (FmCore.EidValue(f.Id) == FmCore.EidValue(keep))
                    {
                        current = f;
                        txtFilterName.Text = f.Name;
                        break;
                    }
                }
            }
            RefreshFooter();

            if (failed.Count > 0)
            {
                var lines = records.Select(r => r.Item1 + "  ->  " + r.Item2 + (r.Item3.Length > 0 ? "   " + r.Item3 : "")).ToList();
                string logPath = WriteLog("FilterManager", lines, subject);
                var window = new FmDoneWindow("Renamed, with " + failed.Count + " refused.", "Filter Manager",
                                              done.Count + " renamed, " + failed.Count + " left alone", "WHAT CHANGED", lines, logPath);
                window.Owner = Win;
                window.ShowDialog();
            }
            else txtStatus.Text = subject + ".";
        }

        // -- create / delete ------------------------------------------------------
        public void OnCreateFilter(object sender, RoutedEventArgs args)
        {
            string suggested = FmFilters.UniqueFilterName(Doc, "RevoBIM Filter");
            var dlg = new FmCreateWindow(Doc, allCategories, suggested);
            dlg.Owner = Win;
            dlg.ShowDialog();
            if (dlg.Result == null) return;

            string name = dlg.Result.Item1;
            List<ElementId> cats = dlg.Result.Item2;

            RunInRevit(uiapp =>
            {
                ParameterFilterElement newFilter;
                using (var t = new Transaction(Doc, "RevoBIM - Create Filter"))
                {
                    t.Start();
                    try
                    {
                        newFilter = FmFilters.CreateFilter(Doc, name, cats);
                        t.Commit();
                    }
                    catch (Exception ex)
                    {
                        try { t.RollBack(); }
                        catch (Exception) { }
                        FmMessage.Alert("The filter was not created:\n\n" + ex);
                        return;
                    }
                }
                AfterCreate(newFilter, name);
            });
        }

        private void AfterCreate(ParameterFilterElement newFilter, string name)
        {
            FmFilters.ClearCaches();
            ReloadFilters(newFilter.Id);
            ReloadTemplates(host != null ? host.Id : null);
            foreach (ListBoxItem item in lstFilters.Items.OfType<ListBoxItem>())
            {
                try
                {
                    if (FmCore.EidValue(((ParameterFilterElement)item.Tag).Id) == FmCore.EidValue(newFilter.Id))
                    {
                        item.IsSelected = true;
                        break;
                    }
                }
                catch (Exception) { }
            }
            txtStatus.Text = "Created '" + name + "'. Add its rules on the right, then press Apply Changes.";
        }

        public void OnDeleteFilter(object sender, RoutedEventArgs args)
        {
            if (current == null) return;
            List<ParameterFilterElement> picked = SelectedFiltersInList();
            if (picked.Count < 2) picked = new List<ParameterFilterElement> { current };

            var names = new List<string>();
            int usedTotal = 0;
            foreach (ParameterFilterElement element in picked)
            {
                try
                {
                    names.Add(element.Name);
                    usedTotal += UsageOf(element.Id);
                }
                catch (Exception) { }
            }
            string name = string.Join(", ", names.Take(6)) + (names.Count > 6 ? " ..." : "");

            string msg = picked.Count == 1
                ? "Delete the filter '" + name + "'?"
                : "Delete these " + picked.Count + " filters?\n\n" + name;
            if (usedTotal > 0)
                msg += "\n\nThey are used " + usedTotal + " time(s) across views and templates and will be removed from all of them.";
            msg += "\n\nOnly Revit's own undo can bring them back.";

            if (!FmMessage.Confirm(msg)) return;

            List<ParameterFilterElement> targets = picked;

            RunInRevit(uiapp =>
            {
                using (var t = new Transaction(Doc, "RevoBIM - Delete Filter"))
                {
                    t.Start();
                    try
                    {
                        foreach (ParameterFilterElement element in targets) FmFilters.DeleteFilter(Doc, element);
                        t.Commit();
                    }
                    catch (Exception ex)
                    {
                        try { t.RollBack(); }
                        catch (Exception) { }
                        FmMessage.Alert("The filter was not deleted:\n\n" + ex);
                        return;
                    }
                }
                AfterDelete(name);
            });
        }

        private void AfterDelete(string name)
        {
            FmFilters.ClearCaches();
            current = null;
            pnlRules.Children.Clear();
            ruleRows = new List<FmRuleRow>();
            txtFilterName.Text = "";
            txtRuleNote.Text = "";
            ReloadFilters();
            ReloadTemplates(host != null ? host.Id : null);
            txtStatus.Text = "Deleted '" + name + "'.";
            RefreshFooter();
        }
    }
}
