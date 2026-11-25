using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using RevoBIM.Tools.WorksetManagement;

namespace RevoBIM.UI.WorksetManagement
{
    /// <summary>
    /// The Scope Boxes tab: every scope box in a table - Used, how many views and how many levels and grids use it, and which -
    /// with batch rename and multi-delete staged in red and written by Apply scope box changes. Every read and write goes
    /// through the main window's ExternalEvent runner. Port of wsm_scope.py.
    /// </summary>
    public class WsmScopeTab
    {
        private readonly WsmWindow _main;
        public readonly WsmGridTable Table;
        private readonly WsmRenamePanel _rename;
        private readonly WsmUi.SideDrawer _renameDrawer;
        public bool Loaded;
        public List<ScopeRecord> Records = new List<ScopeRecord>();

        private static WsmTableSpec MakeSpec()
        {
            return new WsmTableSpec
            {
                Columns = new List<WsmColumn>
                {
                    new WsmColumn("name", 2.4, 180, "WsNameText", "Filter names", true),
                    new WsmColumn("used", 0.6, 70, "WsEditableText", "Yes / No", true),
                    new WsmColumn("views", 0.6, 70, "WsCountText", "e.g. >0", true),
                    new WsmColumn("datums", 0.8, 96, "WsCountText", "e.g. =0", true),
                    new WsmColumn("usedby", 2.6, 200, "WsUsedByText", "e.g. level 02", true),
                    new WsmColumn("change", 2.0, 160, "WsChangeText", "Filter", true),
                },
                Titles = WsmCore.ScopeTitles,
                Numeric = WsmCore.ScopeNumeric,
                Ticks = WsmCore.ScopeTick,
                Value = (row, column) => WsmCore.ScopeValue((WsmCore.ScopeRow)row, column),
                Passes = (row, f, by, exclude) => WsmCore.ScopePasses((WsmCore.ScopeRow)row, f, exclude),
                TickChoices = (rows, column, f, by) => WsmCore.ScopeTickChoices(rows.Cast<WsmCore.ScopeRow>(), column, f),
                Sort = (rows, stack) => WsmCore.ScopeSort(rows.Cast<WsmCore.ScopeRow>(), stack).Cast<WsmCore.StagedRow>().ToList(),
                Change = (row, by) => WsmCore.ScopeChangeText((WsmCore.ScopeRow)row),
                Validate = rows => WsmCore.ScopeValidate(rows.Cast<WsmCore.ScopeRow>().ToList()),
                Tips = new Dictionary<string, Func<WsmCore.StagedRow, string>> { { "usedby", row => WsmCore.ScopeUsedFull((WsmCore.ScopeRow)row) } },
            };
        }

        public WsmScopeTab(WsmWindow main)
        {
            _main = main;
            Table = new WsmGridTable(() => main.Window, main.Status, main.W<DataGrid>("ScopeGrid"), MakeSpec(), Refreshed);
            Table.BuildColumns();
            _rename = new WsmRenamePanel(main.W<FrameworkElement>, main.Status, "Sc", Table, "scope box", "scope boxes", Staged);
            _renameDrawer = new WsmUi.SideDrawer(main.W<FrameworkElement>("ScRenameDrawer"), 338, main.W<TextBlock>("ScRenameTabGlyph"));
            main.W<UIElement>("ScRenameTab").MouseLeftButtonUp += (s, a) => _renameDrawer.Toggle();
            DataGrid grid = main.W<DataGrid>("ScopeGrid");
            grid.PreviewMouseRightButtonDown += (s, a) => _main.Safe("Selecting the row under the pointer", () => OnGridRightDown(a));
            grid.MouseRightButtonUp += (s, a) => _main.Safe("The scope box menu", () => OnGridMenu(a));
            main.W<Button>("ScDeleteButton").Click += (s, a) => _main.Safe("Delete scope boxes", OnDelete);
            main.W<Button>("ScRevertButton").Click += (s, a) => _main.Safe("Revert", OnRevertSelected);
            main.W<Button>("ScRevertAllButton").Click += (s, a) => _main.Safe("Revert all", OnRevertAll);
            main.W<Button>("ScClearFiltersButton").Click += (s, a) => Table.ClearFilters();
            main.W<Button>("ScRefreshButton").Click += (s, a) => _main.Safe("Refresh", OnRefresh);
            main.W<Button>("ScApplyButton").Click += (s, a) => _main.Safe("Apply scope box changes", OnApply);
            _rename.Update();
        }

        // ---------------------------------------------------------- right-click

        private void OnGridRightDown(System.Windows.Input.MouseButtonEventArgs args)
        {
            DataGridRow row = WsmUi.Ancestor<DataGridRow>(args.OriginalSource);
            if (row == null || row.IsSelected) return;
            Table.Grid.SelectedItems.Clear();
            row.IsSelected = true;
        }

        private void OnGridMenu(System.Windows.Input.MouseButtonEventArgs args)
        {
            if (WsmUi.Ancestor<DataGridRow>(args.OriginalSource) == null) return;
            args.Handled = true;
            Table.CommitEdits();
            List<string> keys = Table.SelectedKeys();
            if (keys.Count == 0) return;
            int count = keys.Count;
            string noun = count == 1 ? "scope box" : count + " scope boxes";
            var names = keys.Select(k => Table.ByKey[k].Name).ToList();
            ContextMenu menu = WsmUi.ThemedMenu(_main.Window, new[]
            {
                new WsmUi.MenuEntry("Rename " + noun + "...", (s, a) => { _renameDrawer.Open(); _rename.Update(); }),
                new WsmUi.MenuEntry("Delete " + noun, (s, a) => OnDelete()),
                new WsmUi.MenuEntry("Revert " + noun, (s, a) => OnRevertSelected()),
                WsmUi.MenuEntry.Rule(),
                new WsmUi.MenuEntry(count == 1 ? "Copy name" : "Copy names", (s, a) => WsmUi.CopyText(string.Join("\n", names))),
            });
            menu.PlacementTarget = Table.Grid;
            menu.IsOpen = true;
        }

        // ---------------------------------------------------------- reading

        public void EnsureLoaded() { if (!Loaded) RequestRead(null); }

        public void RequestRead(Action then)
        {
            var document = _main.Doc;
            _main.RunJob("read scope boxes", uiapp => WsmRevit.ReadScopeBoxes(document), records =>
            {
                ApplyRead((List<ScopeRecord>)records);
                if (then != null) then();
            }, "Reading scope boxes...");
        }

        /// <summary>Take a read in, keeping what is staged: renames and deletes by element id, for scope boxes still in the model.</summary>
        public void ApplyRead(List<ScopeRecord> records)
        {
            var old = new Dictionary<long, WsmCore.ScopeRow>();
            foreach (WsmCore.StagedRow r in Table.Rows) { var s = (WsmCore.ScopeRow)r; old[s.Eid] = s; }
            var rows = new List<WsmCore.StagedRow>();
            foreach (ScopeRecord record in records)
            {
                var row = new WsmCore.ScopeRow(record.Eid, record.Name, record.Views, record.Datums, record.Workset);
                WsmCore.ScopeRow before;
                if (old.TryGetValue(record.Eid, out before))
                {
                    if (before.Renamed() && before.Name != row.Orig) row.Name = before.Name;
                    if (before.DeleteTo != null) row.DeleteTo = before.DeleteTo;
                }
                rows.Add(row);
            }
            Records = records;
            Loaded = true;
            Table.SetRows(rows);
            _rename.Update();
        }

        // ---------------------------------------------------------- state

        private WsmCore.ScopePlan Plan() { return WsmCore.BuildScopePlan(Table.Rows.Cast<WsmCore.ScopeRow>()); }

        public int StagedCount() { return Plan().Count + Table.Problems; }

        private void Refreshed()
        {
            int count = Plan().Count;
            _main.W<TextBlock>("ScApplyLabel").Text = count > 0 ? "Apply scope box changes (" + count + ")" : "Apply scope box changes";
            _main.W<Button>("ScApplyButton").IsEnabled = count > 0 || Table.Problems > 0;
            _main.W<Button>("ScRevertAllButton").IsEnabled = Table.Rows.Any(r => r.Staged());
            UpdateStatus();
        }

        public void UpdateStatus()
        {
            if (_main.Tab != "scope") return;
            var rows = Table.Rows.Cast<WsmCore.ScopeRow>().ToList();
            if (!Loaded) { _main.Status("Reading scope boxes..."); return; }
            if (rows.Count == 0) { _main.Status("This model has no scope boxes."); return; }
            int unused = rows.Count(r => !r.Used());
            int shown = Table.ShownKeys().Count;
            int staged = rows.Count(r => r.Staged());
            var parts = new List<string> { rows.Count + " scope boxes", unused + " not used" };
            if (shown != rows.Count) parts.Add(shown + " shown");
            if (staged > 0) parts.Add(staged + " change" + (staged == 1 ? "" : "s") + " staged in red");
            if (Table.Problems > 0) parts.Add(Table.Problems + " need a look");
            _main.Status(string.Join("   Â·   ", parts));
        }

        private void Staged(int count)
        {
            _main.Status(count + " rename" + (count == 1 ? "" : "s") + " staged in red - press Apply scope box changes to write them.");
        }

        // ---------------------------------------------------------- actions

        public void OnDelete()
        {
            Table.CommitEdits();
            List<string> keys = Table.SelectedKeys();
            if (keys.Count == 0) { _main.Status("Select the scope boxes to delete - Ctrl or Shift click for several."); return; }
            WsmCore.ScopeStageDelete(Table.Rows.Cast<WsmCore.ScopeRow>(), keys);
            Table.RefreshStates();
            int used = keys.Count(k => ((WsmCore.ScopeRow)Table.ByKey[k]).Used());
            string note = used > 0 ? " " + used + " of them are in use - those views and datums lose their scope box." : "";
            _main.Status(keys.Count + " scope box(es) staged for deletion in red." + note);
        }

        private void OnRevertSelected()
        {
            Table.CommitEdits();
            List<string> keys = Table.SelectedKeys();
            if (keys.Count == 0) { _main.Status("Select the rows to revert - or use Revert all."); return; }
            Table.SetRows(WsmCore.Revert(Table.Rows, new HashSet<string>(keys)));
        }

        private void OnRevertAll()
        {
            Table.CommitEdits();
            Table.SetRows(WsmCore.Revert(Table.Rows));
            _main.Status("Every staged scope box change reverted.");
        }

        private void OnRefresh()
        {
            RequestRead(() => _main.Status("Read the scope boxes again - staged changes kept."));
        }

        private void OnApply()
        {
            Table.CommitEdits();
            Table.RefreshStates();
            if (Table.Problems > 0)
            {
                var lines = new List<string> { Table.Problems + " row(s) need a look first - marked âš  in the Change column:", "" };
                lines.AddRange(Table.Rows.Where(r => r.Problem.Length > 0).Select(r => "   " + (r.Name.Length > 0 ? r.Name : r.Orig) + "  -  " + r.Problem));
                WsmUi.Message(_main.Window, "Apply scope box changes", lines, 600, 360);
                return;
            }
            WsmCore.ScopePlan plan = Plan();
            int count = plan.Count;
            if (count == 0) { _main.Status("Nothing staged."); return; }
            string text = "This writes the changes below to the model as one undo step.";
            int inUse = plan.Deletes.Count(i => i.Views > 0 || i.Datums > 0);
            if (inUse > 0) text += " " + inUse + " of the scope boxes being deleted are in use: those views, levels and grids go back to no scope box.";
            if (_main.AutoEditable()) text += " Anything that needs it is borrowed first.";
            if (!WsmUi.Confirm(_main.Window, "Apply scope box changes", text, WsmCore.ScopePlanLines(plan),
                               "Apply " + count + " change" + (count == 1 ? "" : "s"), "Cancel", plan.Deletes.Count > 0 ? "WsRedButton" : "WsGreenButton")) return;
            var document = _main.Doc;
            bool auto = _main.AutoEditable();
            _main.RunJob("apply scope boxes", uiapp =>
            {
                WsmCore.Log log = _main.NewLog();
                ScopeResult result = WsmRevit.ApplyScope(document, plan, auto, log);
                log.Write("Apply scope box changes");
                return Tuple.Create(result, WsmRevit.ReadScopeBoxes(document));
            }, payload =>
            {
                var p = (Tuple<ScopeResult, List<ScopeRecord>>)payload;
                ApplyRead(p.Item2);
                Report(p.Item1);
            }, "Writing the scope box changes...");
        }

        private void Report(ScopeResult result)
        {
            var lines = result.Deleted.Select(n => "Deleted   " + n).ToList();
            lines.AddRange(result.Renamed.Select(p => "Renamed   " + p.Item1 + "  ->  " + p.Item2));
            if (result.Refused.Count > 0 || result.Error.Length > 0)
            {
                lines.Add("");
                lines.Add("Not done - still staged in the table:");
                lines.AddRange(result.Refused.Select(p => "   " + p.Item1 + "  -  " + p.Item2));
                if (result.Error.Length > 0) lines.Add("   " + result.Error);
            }
            string show; _main.Settings.TryGetValue("show_results", out show);
            bool trouble = result.Refused.Count > 0 || result.Error.Length > 0;
            if (show == "always" || (show != "never" && trouble))
                WsmUi.Message(_main.Window, "Scope box changes", lines.Count > 0 ? lines : new List<string> { "Nothing changed." });
            int done = result.Deleted.Count + result.Renamed.Count;
            _main.Status(done + " scope box change(s) written" + (result.Refused.Count > 0 ? ", " + result.Refused.Count + " refused - still in red" : "") + ".");
        }
    }
}

