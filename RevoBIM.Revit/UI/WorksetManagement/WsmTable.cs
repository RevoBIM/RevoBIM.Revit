using System;
using System.Collections.Generic;
using System.Data;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Data;
using System.Windows.Input;
using RevoBIM.Tools.WorksetManagement;

namespace RevoBIM.UI.WorksetManagement
{
    /// <summary>What a table shows: columns plus plain functions from WsmCore, so the rules stay separate from the grid.</summary>
    public class WsmColumn
    {
        public string Key, CellStyle, Placeholder;
        public double Width;       // star weight for the name column, pixels for the rest
        public double Minimum;
        public bool Star;
        public WsmColumn(string key, double width, double minimum, string cellStyle, string placeholder, bool star = false)
        {
            Key = key; Width = width; Minimum = minimum; CellStyle = cellStyle; Placeholder = placeholder; Star = star;
        }
    }

    public class WsmTableSpec
    {
        public List<WsmColumn> Columns;
        public Dictionary<string, string> Titles;
        public string[] Numeric, Ticks;
        public Func<WsmCore.StagedRow, string, string> Value;
        public Func<WsmCore.StagedRow, WsmCore.Filters, Dictionary<string, WsmCore.StagedRow>, string, bool> Passes;
        public Func<IEnumerable<WsmCore.StagedRow>, string, WsmCore.Filters, Dictionary<string, WsmCore.StagedRow>, List<string>> TickChoices;
        public Func<IEnumerable<WsmCore.StagedRow>, List<KeyValuePair<string, bool>>, List<WsmCore.StagedRow>> Sort;
        public Func<WsmCore.StagedRow, Dictionary<string, WsmCore.StagedRow>, string> Change;
        public Func<IList<WsmCore.StagedRow>, int> Validate;
        public Dictionary<string, Func<WsmCore.StagedRow, string>> Tips = new Dictionary<string, Func<WsmCore.StagedRow, string>>();
        /// <summary>Extra hidden columns the owner fills (the workset table's expander and swatch).</summary>
        public string[] ExtraColumns = new string[0];
        public Func<WsmCore.StagedRow, Dictionary<string, string>> Extra;
    }

    /// <summary>
    /// The staged table: a DataGrid over a DataTable, filtered on a hidden 'vis' column and sorted on a hidden 'gkey'
    /// column (so nothing moves while it is edited; F5 re-takes both), every heading with a filter box and - where
    /// the values are worth picking from - an Excel-style tick list, natural multi-level sorting, and inline renaming.
    /// Rows only need key, name, orig, delete_to and state(); the staged state lives on them, never in the grid.
    /// Port of wsm_table.GridTable.
    /// </summary>
    public class WsmGridTable
    {
        private static readonly string[] SortKeys = { "OrangeTextBrush", "BlueTextBrush", "GreenTextBrush" };
        private const string Clear = "#00000000";

        private readonly Func<Window> _window;
        public readonly DataGrid Grid;
        public readonly WsmTableSpec Spec;
        private readonly Action<string> _status;
        public Action OnRefreshed;
        public List<WsmCore.StagedRow> Rows = new List<WsmCore.StagedRow>();
        public Dictionary<string, WsmCore.StagedRow> ByKey = new Dictionary<string, WsmCore.StagedRow>();
        public Dictionary<string, DataRow> DRows = new Dictionary<string, DataRow>();
        public WsmCore.Filters Filters = new WsmCore.Filters();
        public List<KeyValuePair<string, bool>> SortStack = new List<KeyValuePair<string, bool>> { new KeyValuePair<string, bool>("name", false) };
        public readonly Dictionary<string, HeaderParts> Headers = new Dictionary<string, HeaderParts>();
        public int Guard;
        public int Problems;
        public DataGridTextColumn NameColumn;
        public readonly DataTable Table;
        private readonly System.Windows.Threading.DispatcherTimer _filterTimer;

        public class HeaderParts
        {
            public Border Outer; public TextBlock Badge; public ToggleButton Caret; public Popup Popup; public TextBox Box;
        }

        public WsmGridTable(Func<Window> window, Action<string> status, DataGrid grid, WsmTableSpec spec, Action onRefreshed = null)
        {
            _window = window; _status = status; Grid = grid; Spec = spec; OnRefreshed = onRefreshed;
            _filterTimer = WsmUi.Debounce(220, RefreshView);
            var names = new List<string> { "key", "state", "vis", "gkey" };
            names.AddRange(spec.Columns.Select(c => c.Key));
            names.AddRange(spec.ExtraColumns);
            names.AddRange(spec.Tips.Keys.Select(k => "tip_" + k));
            Table = new DataTable("rows");
            foreach (string name in names.Distinct()) Table.Columns.Add(name);
            Grid.ItemsSource = Table.DefaultView;
            Table.DefaultView.RowFilter = "vis = '1'";
            Table.DefaultView.Sort = "gkey ASC";
            Grid.BeginningEdit += OnBeginningEdit;
            Table.RowChanged += OnRowChanged;
        }

        /// <summary>Add the columns after any the caller has already put in (the expander and swatch).</summary>
        public void BuildColumns()
        {
            foreach (WsmColumn column in Spec.Columns)
            {
                var made = new DataGridTextColumn
                {
                    Binding = new Binding(column.Key),
                    Width = column.Star ? new DataGridLength(column.Width, DataGridLengthUnitType.Star) : new DataGridLength(column.Width),
                    MinWidth = column.Minimum,
                    IsReadOnly = column.Key != "name",
                    CanUserSort = false,
                    ElementStyle = (Style)_window().FindResource(column.CellStyle),
                };
                if (column.Key == "name")
                {
                    made.EditingElementStyle = (Style)_window().FindResource("WsNameEdit");
                    NameColumn = made;
                }
                made.Header = MakeHeader(column.Key, column.Placeholder);
                Grid.Columns.Add(made);
            }
        }

        private Border MakeHeader(string column, string placeholder)
        {
            var outer = new Border { BorderThickness = new Thickness(0, 0, 0, 2), BorderBrush = WsmUi.Brush(Clear), Padding = new Thickness(2, 0, 2, 3) };
            var layout = new Grid();
            layout.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            layout.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            outer.Child = layout;

            var top = new Grid();
            top.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            top.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            top.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            layout.Children.Add(top);

            var hit = new Border { Background = WsmUi.Brush(Clear), Cursor = Cursors.Hand, ToolTip = "Click to sort. Shift+click adds a second sort level." };
            TextBlock title = WsmUi.TextBlock(Spec.Titles[column], 12, "TextBrush", true);
            if (Spec.Numeric.Contains(column)) WsmUi.Res(title, TextBlock.ForegroundProperty, "OrangeTextBrush");
            hit.Child = title;
            hit.MouseLeftButtonUp += (s, a) =>
            {
                try
                {
                    CommitEdits();
                    bool shift = (Keyboard.Modifiers & ModifierKeys.Shift) == ModifierKeys.Shift;
                    SortStack = WsmCore.PushSort(SortStack, column, shift);
                    RefreshView();
                    a.Handled = true;
                }
                catch (Exception err) { _status("Sort failed: " + err.Message); }
            };
            top.Children.Add(hit);

            TextBlock badge = WsmUi.TextBlock("", 10, "OrangeTextBrush", true);
            badge.Margin = new Thickness(4, 0, 2, 0);
            System.Windows.Controls.Grid.SetColumn(badge, 1);
            top.Children.Add(badge);

            ToggleButton caret = null;
            Popup popup = null;
            if (Spec.Ticks.Contains(column))
            {
                caret = new ToggleButton { ToolTip = "Pick values to show", Margin = new Thickness(2, 0, 0, 0) };
                WsmUi.Style(caret, "WsCaret");
                System.Windows.Controls.Grid.SetColumn(caret, 2);
                top.Children.Add(caret);
                popup = new Popup { PlacementTarget = caret, Placement = PlacementMode.Bottom, StaysOpen = false, AllowsTransparency = true };
                layout.Children.Add(popup);
                ToggleButton c = caret;
                caret.Checked += (s, a) =>
                {
                    try { OpenTicks(column); }
                    catch (Exception err) { _status("Could not open the list: " + err.Message); }
                };
                popup.Closed += (s, a) => c.IsChecked = false;
            }

            var box = new TextBox { Tag = placeholder, Height = 24, FontSize = 11, Margin = new Thickness(0, 4, 0, 0) };
            WsmUi.Style(box, "WsTextBox");
            box.TextChanged += (s, a) =>
            {
                Filters.Text[column] = WsmCore.Txt(box.Text);
                WsmUi.Kick(_filterTimer);
            };
            System.Windows.Controls.Grid.SetRow(box, 1);
            layout.Children.Add(box);

            Headers[column] = new HeaderParts { Outer = outer, Badge = badge, Caret = caret, Popup = popup, Box = box };
            return outer;
        }

        // ---------------------------------------------------------- rows

        /// <summary>A fresh set of rows: rebuild the table, keep sort and filters.</summary>
        public void SetRows(IEnumerable<WsmCore.StagedRow> rows)
        {
            CommitEdits();
            Rows = rows.ToList();
            Guard++;
            try
            {
                Table.Rows.Clear();
                DRows = new Dictionary<string, DataRow>();
                foreach (WsmCore.StagedRow row in Rows)
                {
                    DataRow record = Table.NewRow();
                    record["key"] = row.Key;
                    record["vis"] = "1";
                    record["gkey"] = "0";
                    Table.Rows.Add(record);
                    DRows[row.Key] = record;
                }
            }
            finally { Guard--; }
            RefreshStates();
            RefreshView();
        }

        /// <summary>Validate, then write every row's text and state into the table.</summary>
        public void RefreshStates()
        {
            Problems = Spec.Validate(Rows);
            ByKey = Rows.ToDictionary(r => r.Key);
            Guard++;
            try
            {
                foreach (WsmCore.StagedRow row in Rows)
                {
                    DataRow record;
                    if (!DRows.TryGetValue(row.Key, out record)) continue;
                    var values = new Dictionary<string, string> { { "state", row.State() }, { "change", Spec.Change(row, ByKey) } };
                    foreach (WsmColumn column in Spec.Columns)
                        if (column.Key != "change") values[column.Key] = WsmCore.Txt(Spec.Value(row, column.Key));
                    foreach (var tip in Spec.Tips) values["tip_" + tip.Key] = tip.Value(row);
                    if (Spec.Extra != null) foreach (var pair in Spec.Extra(row)) values[pair.Key] = pair.Value;
                    foreach (var pair in values)
                        if (WsmCore.Txt(record[pair.Key]) != pair.Value) record[pair.Key] = pair.Value;
                }
            }
            finally { Guard--; }
            if (OnRefreshed != null) OnRefreshed();
        }

        /// <summary>Take the sort and the filters again - on a sort click, a filter change or F5, never mid-edit.</summary>
        public void RefreshView()
        {
            CommitEdits();
            List<WsmCore.StagedRow> ordered = Spec.Sort(Rows, SortStack);
            Guard++;
            try
            {
                for (int place = 0; place < ordered.Count; place++)
                {
                    WsmCore.StagedRow row = ordered[place];
                    DataRow record;
                    if (!DRows.TryGetValue(row.Key, out record)) continue;
                    string vis = Spec.Passes(row, Filters, ByKey, null) ? "1" : "0";
                    string gkey = place.ToString("D6");
                    if (WsmCore.Txt(record["vis"]) != vis) record["vis"] = vis;
                    if (WsmCore.Txt(record["gkey"]) != gkey) record["gkey"] = gkey;
                }
            }
            finally { Guard--; }
            UpdateHeaderMarks();
            if (OnRefreshed != null) OnRefreshed();
        }

        private void UpdateHeaderMarks()
        {
            var levels = new Dictionary<string, int>();
            for (int i = 0; i < SortStack.Count; i++) levels[SortStack[i].Key] = i;
            foreach (var pair in Headers)
            {
                HeaderParts parts = pair.Value;
                int index;
                if (levels.TryGetValue(pair.Key, out index))
                {
                    bool descending = SortStack[index].Value;
                    WsmUi.Res(parts.Outer, Border.BorderBrushProperty, SortKeys[index % 3]);
                    WsmUi.Res(parts.Badge, TextBlock.ForegroundProperty, SortKeys[index % 3]);
                    string arrow = descending ? "▼" : "▲";
                    parts.Badge.Text = SortStack.Count > 1 ? (index + 1) + arrow : arrow;
                }
                else
                {
                    parts.Outer.BorderBrush = WsmUi.Brush(Clear);
                    parts.Badge.Text = "";
                }
                if (parts.Caret != null)
                {
                    HashSet<string> t;
                    parts.Caret.Tag = Filters.Ticks.TryGetValue(pair.Key, out t) && t != null ? "on" : "off";
                }
            }
        }

        public List<string> ShownKeys()
        {
            return Rows.Where(r => DRows.ContainsKey(r.Key) && WsmCore.Txt(DRows[r.Key]["vis"]) == "1").Select(r => r.Key).ToList();
        }

        public List<string> SelectedKeys()
        {
            var keys = new List<string>();
            foreach (object item in Grid.SelectedItems)
            {
                var view = item as DataRowView;
                if (view == null) continue;
                keys.Add(WsmCore.Txt(view["key"]));
            }
            return keys.Where(ByKey.ContainsKey).ToList();
        }

        public void CommitEdits()
        {
            try { Grid.CommitEdit(DataGridEditingUnit.Row, true); } catch (Exception) { }
        }

        public void ClearFilters()
        {
            Filters = new WsmCore.Filters();
            foreach (HeaderParts parts in Headers.Values) parts.Box.Text = "";
            RefreshView();
        }

        // ---------------------------------------------------------- the tick lists

        private void OpenTicks(string column)
        {
            HeaderParts parts = Headers[column];
            List<string> choices = Spec.TickChoices(Rows, column, Filters, ByKey);
            HashSet<string> allowed;
            Filters.Ticks.TryGetValue(column, out allowed);
            var shell = new Border { BorderThickness = new Thickness(1), Padding = new Thickness(8), MinWidth = 200 };
            WsmUi.Res(shell, Border.BackgroundProperty, "FieldBrush");
            WsmUi.Res(shell, Border.BorderBrushProperty, "ChromeBrush");
            var stack = new StackPanel();
            shell.Child = new ScrollViewer { VerticalScrollBarVisibility = ScrollBarVisibility.Auto, MaxHeight = 320, Content = stack };
            var boxes = new List<CheckBox>();
            bool busy = false;

            var everything = new CheckBox { Content = WsmUi.TextBlock("(Select all)", 12, "MutedBrush"), IsChecked = allowed == null };
            WsmUi.Style(everything, "WsCheck");
            stack.Children.Add(everything);

            RoutedEventHandler changed = (sender, args) =>
            {
                if (busy) return;
                busy = true;
                try
                {
                    if (ReferenceEquals(sender, everything))
                        foreach (CheckBox b in boxes) b.IsChecked = everything.IsChecked == true;
                    var ticked = new HashSet<string>(boxes.Where(b => b.IsChecked == true).Select(b => WsmCore.Txt(b.Tag)));
                    everything.IsChecked = ticked.Count == boxes.Count;
                    Filters.Ticks[column] = ticked.Count == boxes.Count ? null : ticked;
                    RefreshView();
                }
                finally { busy = false; }
            };
            everything.Click += changed;
            foreach (string value in choices)
            {
                var box = new CheckBox { Content = WsmUi.TextBlock(value, 12, "TextBrush"), Tag = value, IsChecked = allowed == null || allowed.Contains(value) };
                WsmUi.Style(box, "WsCheck");
                box.Click += changed;
                boxes.Add(box);
                stack.Children.Add(box);
            }
            parts.Popup.Child = shell;
            parts.Popup.IsOpen = true;
        }

        // ---------------------------------------------------------- handlers

        private void OnBeginningEdit(object sender, DataGridBeginningEditEventArgs args)
        {
            try
            {
                var view = args.Row.Item as DataRowView;
                WsmCore.StagedRow row;
                if (view == null || !ByKey.TryGetValue(WsmCore.Txt(view["key"]), out row) || !ReferenceEquals(args.Column, NameColumn) || row.DeleteTo != null)
                    args.Cancel = true;
            }
            catch (Exception) { args.Cancel = true; }
        }

        private void OnRowChanged(object sender, DataRowChangeEventArgs args)
        {
            if (Guard > 0) return;
            WsmUi.Later(_window(), AfterEdit);
        }

        /// <summary>Raised after a name was typed into the table and staged on its row.</summary>
        public Action Edited;

        /// <summary>A name typed into the table: stage it on the row. Blank puts the original back.</summary>
        private void AfterEdit()
        {
            try
            {
                bool changed = false;
                foreach (WsmCore.StagedRow row in Rows)
                {
                    DataRow record;
                    if (!DRows.TryGetValue(row.Key, out record)) continue;
                    string typed = WsmCore.Txt(record["name"]).Trim();
                    if (typed.Length == 0 && !row.IsNew) typed = row.Orig;
                    if (typed != row.Name) { row.Name = typed; changed = true; }
                }
                RefreshStates();
                if (changed && Edited != null) Edited();
            }
            catch (Exception err) { _status("Edit failed: " + err.Message); }
        }
    }

    /// <summary>The bulk-rename card. Its controls are the Manage tab's names with a prefix: FindBox, CaseUpper and so on.</summary>
    public class WsmRenamePanel
    {
        private static readonly string[] Boxes = { "FindBox", "ReplaceBox", "PrefixBox", "SuffixBox", "RemoveFirstBox", "RemoveLastBox" };
        private static readonly KeyValuePair<string, string>[] Cases =
        {
            new KeyValuePair<string, string>("CaseKeep", "keep"), new KeyValuePair<string, string>("CaseUpper", "upper"),
            new KeyValuePair<string, string>("CaseLower", "lower"), new KeyValuePair<string, string>("CaseTitle", "title"),
        };

        private readonly Func<string, FrameworkElement> _find;
        private readonly string _prefix, _noun, _plural;
        private readonly WsmGridTable _table;
        private readonly Action<int> _onStaged;
        private readonly Action<string> _status;
        public string CaseMode = "keep";
        private readonly System.Windows.Threading.DispatcherTimer _timer;

        public WsmRenamePanel(Func<string, FrameworkElement> find, Action<string> status, string prefix, WsmGridTable table, string noun, string plural, Action<int> onStaged)
        {
            _find = find; _status = status; _prefix = prefix; _table = table; _noun = noun; _plural = plural; _onStaged = onStaged;
            _timer = WsmUi.Debounce(120, Update);
            foreach (string name in Boxes) ((TextBox)F(name)).TextChanged += (s, a) => WsmUi.Kick(_timer);
            ((CheckBox)F("MatchCaseCheck")).Click += (s, a) => WsmUi.Kick(_timer);
            ((CheckBox)F("TidyCheck")).Click += (s, a) => WsmUi.Kick(_timer);
            foreach (var pair in Cases)
            {
                string mode = pair.Value;
                ((Button)F(pair.Key)).Click += (s, a) => SetCase(mode);
            }
            ((Button)F("RenameResetButton")).Click += (s, a) => Reset();
            ((Button)F("RenameStageButton")).Click += (s, a) => Stage();
            _table.Grid.SelectionChanged += (s, a) => WsmUi.Kick(_timer);
        }

        private FrameworkElement F(string name) { return _find(_prefix + name); }

        public WsmCore.RenameOps Ops()
        {
            return new WsmCore.RenameOps
            {
                Find = WsmCore.Txt(((TextBox)F("FindBox")).Text), Replace = WsmCore.Txt(((TextBox)F("ReplaceBox")).Text),
                MatchCase = ((CheckBox)F("MatchCaseCheck")).IsChecked == true,
                Prefix = WsmCore.Txt(((TextBox)F("PrefixBox")).Text), Suffix = WsmCore.Txt(((TextBox)F("SuffixBox")).Text),
                RemoveFirst = WsmCore.AsInt(((TextBox)F("RemoveFirstBox")).Text, 0), RemoveLast = WsmCore.AsInt(((TextBox)F("RemoveLastBox")).Text, 0),
                Case = CaseMode, Tidy = ((CheckBox)F("TidyCheck")).IsChecked == true,
            };
        }

        public List<string> Scope(out string text)
        {
            List<string> selected = _table.SelectedKeys();
            if (selected.Count > 0)
            {
                text = "Applies to the " + selected.Count + " selected " + (selected.Count == 1 ? _noun : _plural) + ".";
                return selected;
            }
            List<string> shown = _table.ShownKeys();
            text = "Nothing selected - applies to all " + shown.Count + " " + _plural + " shown. Select rows to narrow it.";
            return shown;
        }

        private void SetCase(string mode)
        {
            CaseMode = mode;
            foreach (var pair in Cases) WsmUi.Style(F(pair.Key), pair.Value == mode ? "WsSegmentOn" : "WsSegment");
            Update();
        }

        public void Update()
        {
            try
            {
                string scopeText;
                List<string> keys = Scope(out scopeText);
                ((TextBlock)F("RenameScopeText")).Text = scopeText;
                WsmCore.RenameOps ops = Ops();
                var host = (Panel)F("RenamePreviewHost");
                host.Children.Clear();
                bool empty = WsmCore.OpsEmpty(ops);
                var plan = empty ? new List<Tuple<string, string, string>>() : WsmCore.BulkRenamePlan(_table.Rows, keys, ops);
                if (empty) host.Children.Add(WsmUi.TextBlock("Type above - the new names appear here.", 11, "MutedBrush", false, true));
                else if (plan.Count == 0) host.Children.Add(WsmUi.TextBlock("No names change.", 11, "MutedBrush"));
                foreach (var item in plan.Take(12))
                {
                    var line = new StackPanel { Margin = new Thickness(0, 1, 0, 1) };
                    line.Children.Add(WsmUi.TextBlock(item.Item2, 11, "MutedBrush"));
                    line.Children.Add(WsmUi.TextBlock("→ " + item.Item3, 12, "RedBrush", true));
                    host.Children.Add(line);
                }
                if (plan.Count > 12) host.Children.Add(WsmUi.TextBlock("... and " + (plan.Count - 12) + " more", 11, "MutedBrush"));
                ((TextBlock)F("RenameStageLabel")).Text = plan.Count > 0 ? "Stage rename (" + plan.Count + ")" : "Stage rename";
                F("RenameStageButton").IsEnabled = plan.Count > 0;
            }
            catch (Exception err) { _status("Preview failed: " + err.Message); }
        }

        public void Reset()
        {
            foreach (string name in Boxes) ((TextBox)F(name)).Text = "";
            ((CheckBox)F("MatchCaseCheck")).IsChecked = false;
            ((CheckBox)F("TidyCheck")).IsChecked = false;
            SetCase("keep");
        }

        public void Stage()
        {
            _table.CommitEdits();
            string scopeText;
            List<string> keys = Scope(out scopeText);
            var plan = WsmCore.BulkRenamePlan(_table.Rows, keys, Ops());
            if (plan.Count == 0) return;
            foreach (var item in plan) _table.ByKey[item.Item1].Name = item.Item3;
            _table.RefreshStates();
            Reset();
            _onStaged(plan.Count);
        }
    }
}
