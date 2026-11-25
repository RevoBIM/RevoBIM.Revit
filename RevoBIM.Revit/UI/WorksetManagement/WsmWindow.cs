using System;
using System.Collections.Generic;
using System.Data;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using RevoBIM.Helpers;
using RevoBIM.Tools.WorksetManagement;
using Grid = System.Windows.Controls.Grid;
using Panel = System.Windows.Controls.Panel;
using Visibility = System.Windows.Visibility;
using TextBox = System.Windows.Controls.TextBox;
using Image = System.Windows.Controls.Image;
using Binding = System.Windows.Data.Binding;
using ContextMenu = System.Windows.Controls.ContextMenu;

namespace RevoBIM.UI.WorksetManagement
{
    /// <summary>
    /// The Workset Management window: modeless and owned by Revit, so Revit can be panned while it is open; every read and
    /// write goes through the ExternalEvent runner. Manage Worksets: the table is a DataTable bound through its DefaultView,
    /// filtered on a hidden 'vis' column and sorted on a hidden 'gkey' column, so a row being edited never moves or
    /// disappears under the cursor. F5 re-takes the sort and the filters. Everything staged lives on WsRow objects; the table
    /// is a view of them. Workset Assigner: WsmAssign.cs. Scope Boxes: WsmScope.cs. Port of wsm_window.py.
    /// </summary>
    public class WsmWindow
    {
        private const string ExpandGlyph = "â–¸", CollapseGlyph = "â–¾";
        private const double DetailItemWidth = 250.0;
        private const double RenameDrawerWidth = 338;

        /// <summary>The one open window, so a second press of the ribbon button brings it back.</summary>
        public static WsmWindow Open;

        public readonly UIApplication UiApp;
        public readonly Document Doc;
        public readonly string Title;
        public readonly bool Direct;
        public Dictionary<string, string> Settings;
        public string ThemeSetting;
        public List<WorksetRecord> Records = new List<WorksetRecord>();
        public WsmCore.ModelScan Scan = new WsmCore.ModelScan();
        public Dictionary<int, string> Colours = new Dictionary<int, string>();
        public List<string> Isolated = new List<string>();
        public string ViewName = "";
        public string Tab = "manage";
        public readonly Window Window;
        public readonly WsmGridTable Table;
        public readonly WsmRunner Runner = new WsmRunner();
        public WsmAssignTab Assign;
        public WsmScopeTab Scope;
        public readonly string RevitVersion = "?";

        private readonly HashSet<string> _expanded = new HashSet<string>();
        private readonly WsmUi.Chrome _chrome;
        private readonly WsmUi.SideDrawer _renameDrawer;
        private readonly WsmRenamePanel _rename;
        private readonly TextBlock _expHeader;
        private readonly DataGridColumn _expColumn;
        private int _newCounter;
        private string _canvas;
        private bool _closingOk, _closed;
        private readonly System.Windows.Threading.DispatcherTimer _watchdog;

        public T W<T>(string name) where T : class { return Window.FindName(name) as T; }
        public FrameworkElement W(string name) { return Window.FindName(name) as FrameworkElement; }
        public void Safe(string where, Action action) { WsmUi.Try(() => Window, where, action); }
        public string ThemeName() { return WsmUi.Current; }
        public void Status(string text) { W<TextBlock>("StatusText").Text = WsmCore.Txt(text); }

        private IEnumerable<WsmCore.WsRow> WsRows { get { return Table.Rows.Cast<WsmCore.WsRow>(); } }

        public WsmWindow(UIApplication uiapp, Document document, bool direct = false)
        {
            UiApp = uiapp; Doc = document; Title = WsmCore.Txt(document.Title); Direct = direct;
            Settings = WsmCore.LoadSettings();
            ThemeSetting = WsmCore.NormaliseTheme(Settings["theme"]);
            try { RevitVersion = uiapp.Application.VersionNumber + " (" + uiapp.Application.VersionBuild + ")"; } catch (Exception) { }

            Window = WsmUi.LoadWindow("WorksetManagement.xaml");
            Runner.Setup(uiapp, Window.Dispatcher, direct);
            _watchdog = WsmUi.Repeat(2000, (s, a) =>
            {
                var dropped = Runner.Watchdog();
                if (dropped.Count > 0) Status("Revit did not pick up the request (" + string.Join(", ", dropped) + ") - finish what you are doing in Revit, then try again.");
            });

            Window.Width = Math.Max(Window.MinWidth, Math.Min(WsmCore.AsInt(Settings["width"], 1260), 2600));
            Window.Height = Math.Max(Window.MinHeight, Math.Min(WsmCore.AsInt(Settings["height"], 820), 1600));
            _chrome = new WsmUi.Chrome(Window, W<FrameworkElement>("HeaderBar"), W<Panel>("GripLayer"), W<Button>("FullScreenButton"),
                new object[] { W<object>("ThemeButton"), W<object>("CloseButton"), W<object>("LogoBlock"), W<object>("DebugButton") }, W<Button>("ShrinkButton"));
            var icon = WsmUi.LoadIcon();
            if (icon != null) W<System.Windows.Controls.Image>("HeaderIcon").Source = icon;
            W<TextBlock>("VersionText").Text = "v" + WsmCore.Version;
            W<CheckBox>("AutoEditableCheck").IsChecked = WsmCore.AsBool(Settings["auto_editable"], true);
            ApplyTheme();
            EggHook.Attach(Window, ThemeName, W<UIElement>("LogoBlock"));

            // the table: expander and swatch columns first, then the spec's own
            DataGrid grid = W<DataGrid>("WsGrid");
            Table = new WsmGridTable(() => Window, Status, grid, MakeSpec(), OnTableRefreshed);
            var head = new Border { Background = WsmUi.Brush("#00000000"), Cursor = Cursors.Hand, ToolTip = "Expand or collapse the categories on every workset" };
            _expHeader = WsmUi.TextBlock(ExpandGlyph, 13, "BlueBrush", true);
            _expHeader.HorizontalAlignment = HorizontalAlignment.Center;
            _expHeader.VerticalAlignment = VerticalAlignment.Top;
            _expHeader.Margin = new Thickness(0, 2, 0, 0);
            head.Child = _expHeader;
            head.MouseLeftButtonUp += (s, a) => Safe("Expand", () => OnExpandAll(a));
            _expColumn = new DataGridTextColumn
            {
                Binding = new System.Windows.Data.Binding("exp"), Width = new DataGridLength(30), MinWidth = 30, CanUserResize = false, IsReadOnly = true,
                CanUserSort = false, ElementStyle = (Style)Window.FindResource("WsExpText"), Header = head,
            };
            grid.Columns.Add(_expColumn);
            grid.Columns.Add(new DataGridTemplateColumn
            {
                CellTemplate = (DataTemplate)Window.FindResource("WsSwatchTemplate"), Width = new DataGridLength(24), MinWidth = 24, CanUserResize = false,
                IsReadOnly = true, CanUserSort = false,
            });
            Table.Spec.Extra = row => new Dictionary<string, string>
            {
                { "exp", ExpanderGlyph((WsmCore.WsRow)row) }, { "colour", string.IsNullOrEmpty(((WsmCore.WsRow)row).Colour) ? WsmCore.NoColour : ((WsmCore.WsRow)row).Colour },
            };
            Table.BuildColumns();
            Table.Edited = () => _rename.Update();

            _renameDrawer = new WsmUi.SideDrawer(W<FrameworkElement>("RenameDrawer"), RenameDrawerWidth, W<TextBlock>("RenameTabGlyph"));
            _rename = new WsmRenamePanel(W, Status, "", Table, "workset", "worksets", count =>
                Status(count + " rename" + (count == 1 ? "" : "s") + " staged in red - press Apply workset changes to write them."));
            Wire();
            Scope = new WsmScopeTab(this);
            Assign = new WsmAssignTab(this);

            // the command is still running here, so the first read is direct
            WsmCore.ModelScan scan;
            List<WorksetRecord> records = WsmRevit.ReadModel(Doc, Settings, out scan);
            ApplyRead(records, scan, false);
            ShowTab(Settings["tab"]);
            _rename.Update();
            Update3dButtons();
        }

        private static WsmTableSpec MakeSpec()
        {
            return new WsmTableSpec
            {
                Columns = new List<WsmColumn>
                {
                    new WsmColumn("name", 1.0, 200, "WsNameText", "Filter names", true),
                    new WsmColumn("count", 86, 70, "WsCountText", "e.g. >0"),
                    new WsmColumn("cats", 250, 140, "WsCatsText", "e.g. cable tray"),
                    new WsmColumn("editable", 84, 70, "WsEditableText", "Yes / No"),
                    new WsmColumn("visible", 118, 90, "WsVisibleText", "Yes / No"),
                    new WsmColumn("owner", 104, 80, "WsPlainText", "Filter"),
                    new WsmColumn("change", 230, 140, "WsChangeText", "Filter"),
                },
                Titles = WsmCore.ColumnTitles,
                Numeric = WsmCore.NumericColumns,
                Ticks = WsmCore.TickColumns,
                ExtraColumns = new[] { "exp", "colour" },
                Value = (r, column) =>
                {
                    var row = (WsmCore.WsRow)r;
                    switch (column)
                    {
                        case "name": return row.Name;
                        case "count": return row.IsNew ? "" : row.Count.ToString();
                        case "cats": return WsmCore.CategorySummary(row.Categories);
                        case "editable": return row.IsNew ? "" : (row.Editable ? "Yes" : "No");
                        case "visible": return WsmCore.RowValue(row, "visible");
                        case "owner": return row.IsNew ? "" : row.Owner;
                    }
                    return "";
                },
                Passes = (row, f, by, exclude) => WsmCore.RowPasses((WsmCore.WsRow)row, f, by, exclude),
                TickChoices = (rows, column, f, by) => WsmCore.TickChoices(rows.Cast<WsmCore.WsRow>(), column, f, by),
                Sort = (rows, stack) => WsmCore.SortRows(rows.Cast<WsmCore.WsRow>(), stack).Cast<WsmCore.StagedRow>().ToList(),
                Change = (row, by) => WsmCore.ChangeText((WsmCore.WsRow)row, by),
                Validate = rows => WsmCore.Validate(rows.Cast<WsmCore.WsRow>().ToList()),
            };
        }

        // ---------------------------------------------------------- set up

        private void Wire()
        {
            W<Button>("CloseButton").Click += (s, a) => Window.Close();
            W<Button>("ThemeButton").Click += (s, a) => Safe("Theme", OnTheme);
            W<Button>("DebugButton").Click += (s, a) => Safe("Debug report", OnDebugReport);
            W<Button>("TabManage").Click += (s, a) => Safe("Tabs", () => ShowTab("manage"));
            W<Button>("TabAssign").Click += (s, a) => Safe("Tabs", () => ShowTab("assign"));
            W<Button>("TabScope").Click += (s, a) => Safe("Tabs", () => ShowTab("scope"));
            W<Button>("ExportButton").Click += (s, a) => Safe("Export", OnExport);
            W<Button>("ImportButton").Click += (s, a) => Safe("Import", OnImport);
            W<Button>("NewButton").Click += (s, a) => Safe("New workset", OnNew);
            W<Button>("EditableButton").Click += (s, a) => Safe("Make editable", OnMakeEditable);
            W<Button>("DeleteButton").Click += (s, a) => Safe("Delete", OnDelete);
            W<Button>("RevertButton").Click += (s, a) => Safe("Revert", OnRevertSelected);
            W<Button>("RevertAllButton").Click += (s, a) => Safe("Revert all", OnRevertAll);
            W<Button>("ClearFiltersButton").Click += (s, a) => Safe("Clear filters", Table.ClearFilters);
            W<Button>("RefreshButton").Click += (s, a) => Safe("Refresh", OnRefresh);
            W<Button>("ApplyWorksetsButton").Click += (s, a) => Safe("Apply workset changes", OnApplyWorksets);
            W<Button>("MergeButton").Click += (s, a) => Safe("Merge", OnMerge);
            W<Button>("Show3DButton").Click += (s, a) => Safe("Show in 3D", OnShow3d);
            W<Button>("IsolateButton").Click += (s, a) => Safe("Isolate", OnIsolate);
            W<Button>("UnisolateButton").Click += (s, a) => Safe("Un-isolate", OnUnisolate);
            W<CheckBox>("AutoEditableCheck").Click += (s, a) => Safe("Settings", SaveSettings);
            DataGrid grid = Table.Grid;
            grid.LoadingRow += (s, a) =>
            {
                try
                {
                    var view = a.Row.Item as DataRowView;
                    a.Row.DetailsVisibility = view != null && _expanded.Contains(WsmCore.Txt(view["key"])) ? Visibility.Visible : Visibility.Collapsed;
                }
                catch (Exception) { }
            };
            grid.RowDetailsVisibilityChanged += OnDetailsChanged;
            grid.LoadingRowDetails += OnDetailsChanged;
            grid.PreviewMouseLeftButtonDown += (s, a) => OnGridMouseDown(a);
            grid.SelectionChanged += (s, a) => Update3dButtons();
            grid.PreviewMouseRightButtonDown += (s, a) => Safe("Selecting the row under the pointer", () => OnGridRightDown(a));
            grid.MouseRightButtonUp += (s, a) => Safe("The workset menu", () => OnGridMenu(a));
            W<UIElement>("RenameTab").MouseLeftButtonUp += (s, a) => _renameDrawer.Toggle();
            Window.PreviewKeyDown += (s, a) => OnKey(a);
            Window.Activated += (s, a) =>
            {
                if (ThemeSetting == "follow") { try { ApplyTheme(); } catch (Exception) { } }
            };
            Window.Closing += OnClosing;
            Window.Closed += OnClosed;
        }

        // ---------------------------------------------------------- theme and tabs

        public void ApplyTheme()
        {
            if (ThemeSetting == "follow") _canvas = WsmRevit.CanvasTheme(Doc);
            string name = WsmCore.ResolveTheme(ThemeSetting, _canvas);
            if (name != WsmUi.Current || !Window.Resources.Contains("WindowBrush")) WsmUi.ApplyPalette(Window, name);
            W<TextBlock>("ThemeLabel").Text = WsmCore.ThemeLabel(ThemeSetting);
            string tip;
            if (ThemeSetting == "follow") tip = "Auto: following Revit's canvas (" + name + "). Click for Dark.";
            else if (ThemeSetting == "dark") tip = "Dark. Click for Light.";
            else tip = "Light. Click for Auto (follow Revit's canvas).";
            W<Button>("ThemeButton").ToolTip = tip;
            if (Assign != null && Assign.Manager != null && Assign.Manager.Alive()) Assign.Manager.Retheme();
        }

        public void OnTheme()
        {
            ThemeSetting = WsmCore.NextTheme(ThemeSetting);
            ApplyTheme();
            SaveSettings();
        }

        private static readonly string[][] Tabs =
        {
            new[] { "manage", "TabManage", "ManagePanel", "ManageFooter" },
            new[] { "scope", "TabScope", "ScopePanel", "ScopeFooter" },
            new[] { "assign", "TabAssign", "AssignPanel", "AssignFooter" },
        };

        public void ShowTab(string name)
        {
            Table.CommitEdits();
            if (Scope != null) Scope.Table.CommitEdits();
            Tab = name == "manage" || name == "scope" || name == "assign" ? name : "manage";
            foreach (string[] t in Tabs)
            {
                bool on = t[0] == Tab;
                W(t[2]).Visibility = on ? Visibility.Visible : Visibility.Collapsed;
                W(t[3]).Visibility = on ? Visibility.Visible : Visibility.Collapsed;
                WsmUi.Style(W(t[1]), on ? "WsTabActive" : "WsTab");
            }
            if (Tab == "manage") UpdateManageStatus(null);
            else if (Tab == "assign") { if (Assign != null) Assign.UpdateStatus(); }
            else if (Scope != null) { Scope.UpdateStatus(); Scope.EnsureLoaded(); }
        }

        // ---------------------------------------------------------- reading

        public void RequestRead(bool keep = true, Action then = null)
        {
            RunJob("read", uiapp =>
            {
                WsmCore.ModelScan scan;
                List<WorksetRecord> records = WsmRevit.ReadModel(Doc, Settings, out scan);
                return Tuple.Create(records, scan);
            }, result =>
            {
                var r = (Tuple<List<WorksetRecord>, WsmCore.ModelScan>)result;
                ApplyRead(r.Item1, r.Item2, keep);
                if (then != null) then();
            }, "Reading the model...");
        }

        /// <summary>
        /// Take a read into the window. With keep, staged changes and assigner ticks survive: renames and deletes by
        /// workset id, new worksets unless one of that name now exists.
        /// </summary>
        public void ApplyRead(List<WorksetRecord> records, WsmCore.ModelScan scan, bool keep = true)
        {
            Table.CommitEdits();
            var oldRows = keep ? WsRows.ToList() : new List<WsmCore.WsRow>();
            Records = records; Scan = scan;
            Colours = WsmCore.WorksetColours(records.Select(r => r.Iid));
            var fresh = new List<WsmCore.WsRow>();
            foreach (WorksetRecord record in Records)
            {
                string colour;
                var made = new WsmCore.WsRow("ws:" + record.Iid, record.Name, record.Count, record.Editable, record.Owner, false, record.Iid, record.Active)
                {
                    Categories = new List<KeyValuePair<string, int>>(record.Categories), Visible = record.Visible,
                    Colour = Colours.TryGetValue(record.Iid, out colour) ? colour : WsmCore.NoColour,
                };
                fresh.Add(made);
            }
            if (oldRows.Count > 0)
            {
                var byIid = fresh.ToDictionary(r => r.Iid);
                var names = new HashSet<string>(fresh.Select(r => r.Orig.Trim().ToLowerInvariant()));
                foreach (WsmCore.WsRow old in oldRows)
                {
                    if (old.IsNew)
                    {
                        if (!names.Contains(old.Name.Trim().ToLowerInvariant())) fresh.Add(old);
                        continue;
                    }
                    WsmCore.WsRow row;
                    if (!byIid.TryGetValue(old.Iid, out row)) continue;
                    if (old.Renamed() && old.Name != row.Orig) row.Name = old.Name;
                    if (old.DeleteTo != null) { row.DeleteTo = old.DeleteTo; row.Merge = old.Merge; }
                }
                var keys = new HashSet<string>(fresh.Select(r => r.Key));
                foreach (WsmCore.WsRow row in fresh)
                    if (row.DeleteTo != null && !keys.Contains(row.DeleteTo)) { row.DeleteTo = null; row.Merge = false; }
            }
            PopulateTable(fresh);
            if (Assign != null) Assign.Refresh();
            if (Scan.Error.Length > 0) Status(Scan.Error);
        }

        private void PopulateTable(IEnumerable<WsmCore.WsRow> rows)
        {
            Table.SetRows(rows.Cast<WsmCore.StagedRow>());
        }

        // ---------------------------------------------------------- the table

        private string ExpanderGlyph(WsmCore.WsRow row)
        {
            if (row.Categories.Count == 0) return "";
            return _expanded.Contains(row.Key) ? CollapseGlyph : ExpandGlyph;
        }

        private void OnTableRefreshed()
        {
            // the spec writes exp and colour through Extra
            var plan = WsmCore.BuildPlan(WsRows);
            int count = plan.Count;
            W<TextBlock>("ApplyWorksetsLabel").Text = count > 0 ? "Apply workset changes (" + count + ")" : "Apply workset changes";
            W<Button>("ApplyWorksetsButton").IsEnabled = count > 0 || Table.Problems > 0;
            W<Button>("RevertAllButton").IsEnabled = Table.Rows.Any(r => r.Staged());
            UpdateManageStatus(Table.Problems);
            if (_rename != null) _rename.Update();
        }

        private void UpdateManageStatus(int? problems)
        {
            if (Tab != "manage") return;
            int p = problems ?? Table.Rows.Count(r => r.Problem.Length > 0);
            int shown = Table.ShownKeys().Count;
            int staged = Table.Rows.Count(r => r.Staged());
            var parts = new List<string> { WsRows.Count(r => !r.IsNew) + " worksets" };
            if (shown != Table.Rows.Count) parts.Add(shown + " shown");
            if (staged > 0) parts.Add(staged + " change" + (staged == 1 ? "" : "s") + " staged in red - nothing is written until Apply");
            if (p > 0) parts.Add(p + " need a look");
            Status(string.Join("   Â·   ", parts));
        }

        public void OnRefresh() { RequestRead(true, () => Status("Read the model again - staged changes and ticks kept.")); }

        // ---------------------------------------------------------- category breakdown

        private DataGridRow RowContainer(string key)
        {
            foreach (object item in Table.Grid.Items)
            {
                var view = item as DataRowView;
                if (view != null && WsmCore.Txt(view["key"]) == key) return Table.Grid.ItemContainerGenerator.ContainerFromItem(item) as DataGridRow;
            }
            return null;
        }

        private void SetExpanded(IEnumerable<string> keys, bool openThem)
        {
            var list = keys.ToList();
            Table.Guard++;
            try
            {
                foreach (string key in list)
                {
                    WsmCore.StagedRow staged;
                    if (!Table.ByKey.TryGetValue(key, out staged)) continue;
                    var row = (WsmCore.WsRow)staged;
                    if (row.Categories.Count == 0) continue;
                    if (openThem) _expanded.Add(key); else _expanded.Remove(key);
                    DataRow record;
                    if (Table.DRows.TryGetValue(key, out record)) record["exp"] = ExpanderGlyph(row);
                }
            }
            finally { Table.Guard--; }
            foreach (string key in list)
            {
                DataGridRow container = RowContainer(key);
                if (container != null) container.DetailsVisibility = _expanded.Contains(key) ? Visibility.Visible : Visibility.Collapsed;
            }
            _expHeader.Text = _expanded.Count > 0 ? CollapseGlyph : ExpandGlyph;
        }

        /// <summary>A click on the expander cell opens or closes that row's breakdown.</summary>
        private void OnGridMouseDown(MouseButtonEventArgs args)
        {
            try
            {
                var cell = WsmUi.Ancestor<DataGridCell>(args.OriginalSource, Table.Grid);
                if (cell == null || !ReferenceEquals(cell.Column, _expColumn)) return;
                string key = WsmCore.Txt(((DataRowView)cell.DataContext)["key"]);
                SetExpanded(new[] { key }, !_expanded.Contains(key));
                args.Handled = true;
            }
            catch (Exception err) { Status("Could not open the categories: " + err.Message); }
        }

        private void OnExpandAll(MouseButtonEventArgs args)
        {
            Table.CommitEdits();
            List<string> keys = Table.ShownKeys();
            bool openThem = !keys.Any(_expanded.Contains);
            SetExpanded(keys, openThem);
            args.Handled = true;
        }

        private void OnDetailsChanged(object sender, DataGridRowDetailsEventArgs args)
        {
            try
            {
                if (args.Row.DetailsVisibility != Visibility.Visible || args.DetailsElement == null) return;
                string key = WsmCore.Txt(((DataRowView)args.Row.Item)["key"]);
                WsmCore.StagedRow row;
                Table.ByKey.TryGetValue(key, out row);
                FillDetails(args.DetailsElement as Border, row as WsmCore.WsRow);
            }
            catch (Exception err) { Status("Could not show the categories: " + err.Message); }
        }

        /// <summary>Every category on the workset with its count and a bar against the biggest, laid out in as many columns as the width allows.</summary>
        private void FillDetails(Border host, WsmCore.WsRow row)
        {
            if (host == null) return;
            var outer = new StackPanel();
            if (row == null || row.Categories.Count == 0)
            {
                outer.Children.Add(WsmUi.TextBlock("No elements on this workset.", 11, "MutedBrush"));
                host.Child = outer;
                return;
            }
            int total = row.Categories.Sum(c => c.Value);
            TextBlock heading = WsmUi.TextBlock(row.Categories.Count + " categor" + (row.Categories.Count == 1 ? "y" : "ies") + "  Â·  " + total + " elements", 11, "MutedBrush", true);
            heading.Margin = new Thickness(0, 0, 0, 6);
            outer.Children.Add(heading);
            double biggest = row.Categories[0].Value == 0 ? 1.0 : row.Categories[0].Value;
            var wrap = new WrapPanel { Orientation = Orientation.Horizontal };
            foreach (var category in row.Categories)
            {
                var item = new Grid { Width = DetailItemWidth, Margin = new Thickness(0, 0, 18, 6) };
                item.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
                item.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
                item.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
                item.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
                TextBlock label = WsmUi.TextBlock(category.Key, 12, "TextBrush");
                label.ToolTip = category.Key;
                item.Children.Add(label);
                TextBlock number = WsmUi.TextBlock(category.Value.ToString(), 12, "OrangeTextBrush", true);
                number.Margin = new Thickness(8, 0, 0, 0);
                Grid.SetColumn(number, 1);
                item.Children.Add(number);
                var track = new Border { Height = 3, CornerRadius = new CornerRadius(1.5), Margin = new Thickness(0, 3, 0, 0) };
                WsmUi.Res(track, Border.BackgroundProperty, "EdgeBrush");
                Grid.SetRow(track, 1); Grid.SetColumnSpan(track, 2);
                item.Children.Add(track);
                var fill = new Border
                {
                    Height = 3, CornerRadius = new CornerRadius(1.5), HorizontalAlignment = HorizontalAlignment.Left,
                    Width = Math.Max(2.0, DetailItemWidth * category.Value / biggest), Margin = new Thickness(0, 3, 0, 0),
                };
                WsmUi.Res(fill, Border.BackgroundProperty, "OrangeBrush");
                Grid.SetRow(fill, 1); Grid.SetColumnSpan(fill, 2);
                item.Children.Add(fill);
                wrap.Children.Add(item);
            }
            outer.Children.Add(wrap);
            host.Child = outer;
        }

        // ---------------------------------------------------------- right-click

        /// <summary>A right-click on a row outside the selection selects that row, as Explorer does; inside the selection it keeps the selection.</summary>
        private void OnGridRightDown(MouseButtonEventArgs args)
        {
            DataGridRow row = WsmUi.Ancestor<DataGridRow>(args.OriginalSource);
            if (row == null || row.IsSelected) return;
            Table.Grid.SelectedItems.Clear();
            row.IsSelected = true;
        }

        private void OnGridMenu(MouseButtonEventArgs args)
        {
            if (WsmUi.Ancestor<DataGridRow>(args.OriginalSource) == null) return;
            args.Handled = true;
            Table.CommitEdits();
            List<string> keys = Table.SelectedKeys();
            if (keys.Count == 0) return;
            var rows = keys.Select(k => (WsmCore.WsRow)Table.ByKey[k]).ToList();
            var real = rows.Where(r => !r.IsNew).ToList();
            int count = keys.Count;
            string noun = count == 1 ? "workset" : count + " worksets";
            bool anyStaged = rows.Any(r => r.Staged());
            int opened = keys.Count(_expanded.Contains);
            var items = new List<WsmUi.MenuEntry>
            {
                new WsmUi.MenuEntry("Rename " + noun + "...", (s, a) => OpenRename()),
                new WsmUi.MenuEntry("Rename in place (F2)", (s, a) => EditRow(keys[0]), count == 1),
                new WsmUi.MenuEntry("Delete " + noun + "...", (s, a) => OnDelete()),
                new WsmUi.MenuEntry("Merge " + noun + "...", (s, a) => OnMerge(), real.Count >= 2),
                new WsmUi.MenuEntry("Revert " + noun, (s, a) => OnRevertSelected(), anyStaged),
                WsmUi.MenuEntry.Rule(),
                new WsmUi.MenuEntry("Make editable", (s, a) => OnMakeEditable(), real.Count > 0),
                new WsmUi.MenuEntry("Show in 3D", (s, a) => OnShow3d()),
                new WsmUi.MenuEntry("Isolate in 3D", (s, a) => OnIsolate(), real.Count > 0),
                WsmUi.MenuEntry.Rule(),
                new WsmUi.MenuEntry(opened == count ? "Hide categories" : "Show categories", (s, a) => SetExpanded(keys, opened != count)),
                new WsmUi.MenuEntry(count == 1 ? "Copy name" : "Copy names", (s, a) => WsmUi.CopyText(string.Join("\n", rows.Select(r => r.Name)))),
            };
            ContextMenu menu = WsmUi.ThemedMenu(Window, items);
            menu.PlacementTarget = Table.Grid;
            menu.IsOpen = true;
        }

        private void OpenRename()
        {
            _renameDrawer.Open();
            _rename.Update();
            try { W<TextBox>("FindBox").Focus(); } catch (Exception) { }
        }

        // ---------------------------------------------------------- new, delete, revert

        private void OnNew()
        {
            Table.CommitEdits();
            var names = new HashSet<string>(WsRows.Select(r => r.EffectiveName().Trim().ToLowerInvariant()));
            int number = 1;
            while (names.Contains("new workset " + number)) number++;
            _newCounter++;
            var row = new WsmCore.WsRow("new:" + _newCounter, "New Workset " + number, 0, true, "", true);
            var rows = WsRows.ToList();
            rows.Add(row);
            PopulateTable(rows);
            WsmUi.Later(Window, () => EditRow(row.Key));
        }

        public void EditRow(string key)
        {
            foreach (object item in Table.Grid.Items)
            {
                var view = item as DataRowView;
                if (view == null || WsmCore.Txt(view["key"]) != key) continue;
                Table.Grid.SelectedItem = item;
                Table.Grid.ScrollIntoView(item);
                Table.Grid.CurrentCell = new DataGridCellInfo(item, Table.NameColumn);
                Table.Grid.Focus();
                Table.Grid.BeginEdit();
                return;
            }
        }

        public void OnDelete()
        {
            Table.CommitEdits();
            List<string> keys = Table.SelectedKeys();
            if (keys.Count == 0) { Status("Select the worksets to delete first - Ctrl or Shift click for several."); return; }
            var deleting = keys.Select(k => (WsmCore.WsRow)Table.ByKey[k]).ToList();
            var existing = deleting.Where(r => !r.IsNew).ToList();
            if (existing.Count == 0)
            {
                PopulateTable(WsRows.Where(r => !keys.Contains(r.Key)));
                Status("Removed " + keys.Count + " new workset(s) that had not been applied.");
                return;
            }
            var targets = WsmCore.DeleteTargets(WsRows, keys);
            if (targets.Count == 0)
            {
                WsmUi.Message(Window, "Delete worksets", new[] { "At least one workset has to stay, and it has to be one that is not being deleted - its elements need somewhere to go." }, 520, 260);
                return;
            }
            string target = WsmUi.DeleteDialog(Window, existing, targets);
            if (string.IsNullOrEmpty(target)) return;
            string problem;
            List<WsmCore.WsRow> kept = WsmCore.StageDeletes(WsRows.ToList(), keys, target, out problem);
            if (problem.Length > 0) { Status(problem); return; }
            PopulateTable(kept);
            Status(existing.Count + " workset(s) staged for deletion in red - their elements go to " + Table.ByKey[target].EffectiveName() + " when you press Apply.");
        }

        private void OnRevertSelected()
        {
            Table.CommitEdits();
            List<string> keys = Table.SelectedKeys();
            if (keys.Count == 0) { Status("Select the rows to revert - or use Revert all."); return; }
            PopulateTable(WsmCore.Revert(WsRows, new HashSet<string>(keys)));
        }

        private void OnRevertAll()
        {
            Table.CommitEdits();
            PopulateTable(WsmCore.Revert(WsRows));
            Status("Every staged change reverted.");
        }

        // ---------------------------------------------------------- make editable

        public bool AutoEditable() { return W<CheckBox>("AutoEditableCheck").IsChecked == true; }

        private void OnMakeEditable()
        {
            Table.CommitEdits();
            var rows = Table.SelectedKeys().Select(k => (WsmCore.WsRow)Table.ByKey[k]).Where(r => !r.IsNew).ToList();
            if (rows.Count == 0) { Status("Select the worksets to make editable."); return; }
            var iids = rows.Select(r => r.Iid).ToList();
            RunJob("make editable", uiapp =>
            {
                WsmCore.Log log = NewLog();
                var refused = new List<Tuple<string, string>>();
                HashSet<int> made = WsmRevit.MakeEditable(Doc, iids, log, refused);
                log.Write("Make editable");
                WsmCore.ModelScan scan;
                List<WorksetRecord> records = WsmRevit.ReadModel(Doc, Settings, out scan);
                return new object[] { made, refused, records, scan };
            }, payload =>
            {
                var p = (object[])payload;
                ApplyRead((List<WorksetRecord>)p[2], (WsmCore.ModelScan)p[3], true);
                var refused = (List<Tuple<string, string>>)p[1];
                if (refused.Count > 0)
                {
                    var lines = new List<string> { "Not made editable:" };
                    lines.AddRange(refused.Select(r => "   " + r.Item1 + "  -  " + r.Item2));
                    WsmUi.Message(Window, "Make editable", lines, 560, 340);
                }
                Status(((HashSet<int>)p[0]).Count + " workset(s) checked out to you.");
            }, "Checking worksets out...");
        }

        // ---------------------------------------------------------- excel

        private string ExportDir()
        {
            string folder; Settings.TryGetValue("last_export_dir", out folder);
            return !string.IsNullOrEmpty(folder) && Directory.Exists(folder) ? folder : null;
        }

        private void OnExport()
        {
            Table.CommitEdits();
            var dialog = new Microsoft.Win32.SaveFileDialog
            {
                Title = "Save the workset spreadsheet", Filter = "Excel workbook (*.xlsx)|*.xlsx", DefaultExt = ".xlsx",
                FileName = WsmCore.ProjectKey(Title) + " - Worksets.xlsx",
            };
            string folder = ExportDir();
            if (folder != null) dialog.InitialDirectory = folder;
            if (dialog.ShowDialog(Window) != true) return;
            string path = dialog.FileName;
            var sheet = WsmXlsx.WorksetSheetRows(WsRows, WsmCore.AsInt(Settings["new_rows"], 10));
            string problem;
            if (!WsmXlsx.WriteWorkbook(path, sheet, WsmXlsx.Widths, "Worksets", out problem)) { Status("Could not write the spreadsheet: " + problem); return; }
            Settings["last_export_dir"] = Path.GetDirectoryName(path);
            SaveSettings();
            try { Process.Start("explorer.exe", "/select,\"" + path + "\""); } catch (Exception) { }
            Status("Written to " + path + " - rename in the orange cells, add in the green ones, then Import Excel.");
        }

        private void OnImport()
        {
            Table.CommitEdits();
            var dialog = new Microsoft.Win32.OpenFileDialog { Title = "Open the edited workset spreadsheet", Filter = "Excel workbook (*.xlsx)|*.xlsx" };
            string folder = ExportDir();
            if (folder != null) dialog.InitialDirectory = folder;
            if (dialog.ShowDialog(Window) != true) return;
            string problem;
            var sheet = WsmXlsx.ReadSheet(dialog.FileName, out problem);
            if (problem.Length > 0) { Status(problem); return; }
            WsmCore.ImportResult changes = WsmCore.ImportChanges(WsmXlsx.SheetTriples(sheet), WsRows.ToList());
            foreach (var pair in changes.Renames)
            {
                WsmCore.StagedRow row;
                if (Table.ByKey.TryGetValue(pair.Key, out row) && row.DeleteTo == null) row.Name = pair.Value;
            }
            var rows = WsRows.ToList();
            foreach (string name in changes.Creates)
            {
                _newCounter++;
                rows.Add(new WsmCore.WsRow("new:" + _newCounter, name, 0, true, "", true));
            }
            PopulateTable(rows);
            if (changes.Skipped.Count > 0)
            {
                var lines = new List<string> { "Left alone:" };
                lines.AddRange(changes.Skipped.Select(s => "   " + s.Item1 + "  -  " + s.Item2));
                WsmUi.Message(Window, "Import Excel", lines);
            }
            Status("Imported " + changes.Renames.Count + " rename(s) and " + changes.Creates.Count + " new workset(s) - staged in red; press Apply workset changes to write them.");
        }

        // ---------------------------------------------------------- apply

        private void OnApplyWorksets()
        {
            Table.CommitEdits();
            Table.RefreshStates();
            int problems = Table.Problems;
            if (problems > 0)
            {
                var lines = new List<string> { problems + " row(s) need a look first - they are marked âš  in the Change column:", "" };
                lines.AddRange(Table.Rows.Where(r => r.Problem.Length > 0).Select(r => "   " + (r.Name.Length > 0 ? r.Name : r.Orig) + "  -  " + r.Problem));
                WsmUi.Message(Window, "Apply workset changes", lines, 600, 360);
                return;
            }
            WsmCore.Plan plan = WsmCore.BuildPlan(WsRows);
            if (plan.Count == 0) { Status("Nothing staged."); return; }
            string text = "This writes the changes below to the model as one undo step.";
            if (plan.Deletes.Count > 0) text += " Elements on a deleted workset are moved to the workset named, never deleted.";
            if (AutoEditable()) text += " Worksets that need it are checked out to you first.";
            if (!WsmUi.Confirm(Window, "Apply workset changes", text, WsmCore.PlanLines(plan), "Apply " + plan.Count + " change" + (plan.Count == 1 ? "" : "s"))) return;
            bool auto = AutoEditable();
            RunJob("apply worksets", uiapp =>
            {
                WsmCore.Log log = NewLog();
                ManageResult result = WsmRevit.ApplyManage(Doc, plan, auto, log);
                log.Write("Apply workset changes");
                WsmCore.ModelScan scan;
                List<WorksetRecord> records = WsmRevit.ReadModel(Doc, Settings, out scan);
                return new object[] { result, records, scan };
            }, payload =>
            {
                var p = (object[])payload;
                ApplyRead((List<WorksetRecord>)p[1], (WsmCore.ModelScan)p[2], true);
                ReportManage((ManageResult)p[0]);
            }, "Writing the workset changes...");
        }

        private void ReportManage(ManageResult result)
        {
            var lines = new List<string>();
            lines.AddRange(result.Created.Select(n => "Created   " + n));
            lines.AddRange(result.Renamed.Select(p => "Renamed   " + p.Item1 + "  ->  " + p.Item2));
            lines.AddRange(result.Deleted.Select(p => "Deleted   " + p.Item1 + "  (" + p.Item3 + " elements moved to " + p.Item2 + ")"));
            lines.AddRange(result.Merged.Select(p => "Merged    " + p.Item1 + "  into  " + p.Item2 + "  (" + p.Item3 + " elements)"));
            if (result.CheckedOut > 0)
            {
                lines.Add("");
                lines.Add(result.CheckedOut + " workset(s) were checked out to you first.");
            }
            bool trouble = result.Refused.Count > 0 || result.Error.Length > 0;
            if (trouble)
            {
                lines.Add("");
                lines.Add("Not done - still staged in the table:");
                lines.AddRange(result.Refused.Select(p => "   " + p.Item1 + "  -  " + p.Item2));
                if (result.Error.Length > 0) lines.Add("   " + result.Error);
            }
            int done = result.Created.Count + result.Renamed.Count + result.Deleted.Count + result.Merged.Count;
            string show; Settings.TryGetValue("show_results", out show);
            if (show == "always" || (show != "never" && trouble))
                WsmUi.Message(Window, "Workset changes", lines.Count > 0 ? lines : new List<string> { "Nothing changed." });
            Status(done + " change(s) written" + (result.Refused.Count > 0 ? ", " + result.Refused.Count + " refused - still in red" : "") + ".");
        }

        // ---------------------------------------------------------- keys, close, settings

        private void OnKey(KeyEventArgs args)
        {
            try
            {
                if (WsmUi.TextBoxHasFocus()) return;
                bool control = (Keyboard.Modifiers & ModifierKeys.Control) == ModifierKeys.Control;
                if (args.Key == Key.F5)
                {
                    if (Tab == "scope") Scope.Table.RefreshView();
                    else { Table.CommitEdits(); Table.RefreshView(); }
                    args.Handled = true;
                }
                else if (Tab == "scope" && args.Key == Key.Delete) { Scope.OnDelete(); args.Handled = true; }
                else if (Tab == "manage" && args.Key == Key.Delete) { OnDelete(); args.Handled = true; }
                else if (Tab == "manage" && control && args.Key == Key.N) { OnNew(); args.Handled = true; }
            }
            catch (Exception err) { Status(err.Message); }
        }

        public void SaveSettings()
        {
            Settings["theme"] = ThemeSetting;
            Settings["tab"] = Tab;
            Settings["auto_editable"] = AutoEditable() ? "true" : "false";
            if (!_chrome.Full)
            {
                Settings["width"] = ((int)Window.Width).ToString();
                Settings["height"] = ((int)Window.Height).ToString();
            }
            WsmCore.SaveSettings(Settings);
        }

        private void OnClosing(object sender, System.ComponentModel.CancelEventArgs args)
        {
            try
            {
                Table.CommitEdits();
                if (!_closingOk)
                {
                    int staged = WsmCore.BuildPlan(WsRows).Count + (Scope != null ? Scope.StagedCount() : 0) + Table.Rows.Count(r => r.Problem.Length > 0);
                    if (staged > 0 && !WsmUi.Confirm(Window, "Close", staged + " staged change(s) have not been applied. Close without applying them?",
                                                     null, "Close", "Keep working", "WsRedButton", 480, 220))
                    {
                        args.Cancel = true;
                        return;
                    }
                }
                _closingOk = true;
                if (Assign != null) Assign.Closing();      // the assigner keeps itself - nothing to ask
                SaveSettings();
                if (Isolated.Count > 0)
                {
                    // leave the view as it was found: everything showing
                    RunJob("un-isolate", uiapp => WsmRevit.Unisolate(uiapp, Doc, NewLog()), r => { }, "");
                }
            }
            catch (Exception) { }
        }

        private void OnClosed(object sender, EventArgs args)
        {
            _closed = true;
            try { _watchdog.Stop(); } catch (Exception) { }
            if (ReferenceEquals(Open, this)) Open = null;
        }

        // ---------------------------------------------------------- debug report

        /// <summary>Everything worth sending when something goes wrong - no model call, so it works even when Revit is busy.</summary>
        public List<string> DebugLines()
        {
            var lines = new List<string>
            {
                "RevoBIM - Workset Management debug report",
                "tool v" + WsmCore.Version + "   Revit " + RevitVersion + "   " + Environment.Version,
                WsmCore.BuildInfo(),
                "made " + DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + "   project " + Title + "   tab " + Tab + "   theme " + ThemeSetting + " (" + WsmUi.Current + ")",
                "modeless " + !Direct + "   runner busy " + Runner.Busy() + "   parked " + _chrome.Parked,
                "worksets " + Records.Count + "   model elements " + Scan.Total + "   categories " + Scan.Entries.Count + (Scan.Error.Length > 0 ? "   scan error: " + Scan.Error : ""),
            };
            lines.AddRange(WsmCore.ReportSection("worksets (id | name | elements | editable | owner)", Records.Select(r => r.Iid + " | " + r.Name + " | " + r.Count + " | " + r.Editable + " | " + r.Owner)));
            lines.AddRange(WsmCore.ReportSection("model categories (key | name | elements)", Scan.Entries.Select(e => e.Key + " | " + e.Label + " | " + e.Count)));
            if (Assign != null)
            {
                lines.AddRange(WsmCore.ReportSection("assigner state", WsmRules.RoutineLines(Assign.State, new Dictionary<string, WsmRules.Template>())));
                var library = new List<string>();
                foreach (string name in WsmCore.SortedNatural(Assign.Library.Keys))
                {
                    WsmRules.Template template = Assign.Library[name];
                    var problems = WsmRules.TemplateProblems(template);
                    library.Add(name + (problems.Count > 0 ? "   NOT READY: " + string.Join("; ", problems) : ""));
                    library.AddRange(WsmRules.TemplateLines(template).Select(l => "   " + l));
                }
                lines.AddRange(WsmCore.ReportSection("routine templates", library));
                if (Assign.Manager != null && Assign.Manager.Alive())
                    lines.AddRange(WsmCore.ReportSection("routine template manager", Assign.Manager.DebugLines()));
            }
            lines.AddRange(WsmCore.ReportSection("settings", WsmCore.TailLines(WsmCore.SettingsPath, 0)));
            lines.AddRange(WsmCore.ReportSection("runner log (last 60)", Runner.Log.Skip(Math.Max(0, Runner.Log.Count - 60))));
            lines.AddRange(WsmCore.ReportSection("errors (last 300 lines)", WsmCore.TailLines(WsmCore.ErrorPath, 300)));
            lines.AddRange(WsmCore.ReportSection("last apply log", WsmCore.TailLines(WsmCore.DebugPath, 200)));
            lines.AddRange(WsmCore.ReportSection("start-up error", WsmCore.TailLines(WsmCore.LoadErrorPath, 60)));
            return lines;
        }

        public void OnDebugReport()
        {
            var lines = DebugLines();
            if (!WsmCore.WriteLines(WsmCore.ReportPath, lines))
            {
                WsmUi.Message(Window, "Debug report", new[] { "Could not write " + WsmCore.ReportPath });
                return;
            }
            bool copied = WsmUi.CopyText(string.Join("\n", lines));
            try { Process.Start("explorer.exe", "/select,\"" + WsmCore.ReportPath + "\""); } catch (Exception) { }
            Status("Debug report saved to " + WsmCore.ReportPath + (copied ? " and copied to the clipboard" : "") + " - send it to Claude.");
        }

        // ---------------------------------------------------------- the runner

        public WsmCore.Log NewLog() { return new WsmCore.Log(WsmCore.AsBool(Settings["debug"], true)); }

        /// <summary>Hand work to Revit. work(uiapp) runs in API context; done(result) runs back here. Never waits - see WsmRunner.</summary>
        public bool RunJob(string label, Func<UIApplication, object> work, Action<object> done, string busyText)
        {
            if (Runner.Queued(label)) { Status("Still waiting for Revit to finish the last request."); return false; }
            Func<UIApplication, object> guarded = uiapp =>
            {
                bool valid;
                try { valid = Doc.IsValidObject; } catch (Exception) { valid = false; }
                if (!valid) throw new WsmToolStop(Title + " has been closed - close this window and run the tool again.");
                return work(uiapp);
            };
            Action<object, Exception> finished = (result, error) =>
            {
                if (_closed) return;
                Status("");
                if (error != null) { ReportError(label, error, null); return; }
                try { done(result); }
                catch (Exception err) { ReportError(label, err, err.ToString()); }      // the traceback of the callback itself
            };
            string why;
            if (!Runner.Submit(label, guarded, finished, out why)) { Status(why); return false; }
            if (Runner.Busy()) Status(busyText);
            return true;
        }

        private void ReportError(string label, Exception error, string detail)
        {
            if (error is WsmToolStop)
            {
                Status(error.Message);
                WsmUi.Message(Window, WsmCore.ToolName, new[] { error.Message }, 520, 240);
                return;
            }
            Status(label + " failed: " + error.Message);
            WsmUi.Report(Window, char.ToUpperInvariant(label[0]) + label.Substring(1), new Exception(detail ?? error.ToString()));
        }

        // ---------------------------------------------------------- 3D view

        private void Update3dButtons()
        {
            var selected = Table.SelectedKeys().Where(k => !Table.ByKey[k].IsNew).ToList();
            W<Button>("IsolateButton").IsEnabled = selected.Count > 0;
            W<TextBlock>("IsolateLabel").Text = selected.Count > 0 ? "Isolate selected (" + selected.Count + ")" : "Isolate selected";
            W<Button>("UnisolateButton").IsEnabled = Isolated.Count > 0;
            W<Button>("MergeButton").IsEnabled = Table.SelectedKeys().Count >= 2;
            var hint = W<TextBlock>("ViewHint");
            if (Isolated.Count > 0)
            {
                string names = string.Join(", ", Isolated.Take(3));
                if (Isolated.Count > 3) names += " +" + (Isolated.Count - 3);
                hint.Text = "Isolated: " + names;
            }
            else if (ViewName.Length > 0) hint.Text = "Colours match the '" + ViewName + "' view - pan in Revit with this window open.";
            else hint.Text = "Show in 3D colours every element by workset, matching the swatches.";
        }

        private void OnShow3d()
        {
            Table.CommitEdits();
            var colours = new Dictionary<int, string>(Colours);
            bool direct = Direct;
            RunJob("show in 3D", uiapp =>
            {
                WsmCore.Log log = NewLog();
                ViewShowResult result = WsmRevit.ShowIn3d(uiapp, Doc, colours, direct, log);
                log.Write("Show in 3D");
                return result;
            }, payload =>
            {
                var result = (ViewShowResult)payload;
                Isolated = new List<string>();
                ViewName = result.Name;
                Update3dButtons();
                int total = result.Counts.Values.Sum();
                Status((result.Made ? "Made" : "Refreshed") + " the '" + result.Name + "' view: " + total + " elements coloured over " + result.Counts.Values.Count(c => c > 0) + " worksets.");
                QueueZoom(result.ViewId);
            }, "Colouring the 3D view by workset...");
        }

        /// <summary>The view change was only requested; zoom once it has happened.</summary>
        private void QueueZoom(ElementId viewId)
        {
            RunJob("zoom", uiapp =>
            {
                UIDocument uidoc = WsmRevit.ActiveUidoc(uiapp, Doc);
                if (uidoc == null) return false;
                foreach (UIView uiView in uidoc.GetOpenUIViews())
                {
                    try { if (uiView.ViewId.Equals(viewId)) { uiView.ZoomToFit(); return true; } } catch (Exception) { }
                }
                return false;
            }, r => { }, "");
        }

        private void OnIsolate()
        {
            Table.CommitEdits();
            var rows = Table.SelectedKeys().Select(k => (WsmCore.WsRow)Table.ByKey[k]).Where(r => !r.IsNew).ToList();
            if (rows.Count == 0) { Status("Select the worksets to isolate."); return; }
            var iids = rows.Select(r => r.Iid).ToList();
            var names = rows.Select(r => r.Orig).ToList();
            bool direct = Direct;
            RunJob("isolate", uiapp =>
            {
                WsmCore.Log log = NewLog();
                IsolateResult result = WsmRevit.IsolateWorksets(uiapp, Doc, iids, direct, log);
                log.Write("Isolate selected");
                return result;
            }, payload =>
            {
                var result = (IsolateResult)payload;
                Isolated = names;
                Update3dButtons();
                Status("Isolated " + result.Count + " elements on " + names.Count + " workset(s) - Un-isolate to see everything again.");
            }, "Isolating...");
        }

        private void OnUnisolate()
        {
            RunJob("un-isolate", uiapp => WsmRevit.Unisolate(uiapp, Doc, NewLog()), r =>
            {
                Isolated = new List<string>();
                Update3dButtons();
                Status("Every workset showing again.");
            }, "Un-isolating...");
        }

        // ---------------------------------------------------------- merge

        private void OnMerge()
        {
            Table.CommitEdits();
            List<string> keys = Table.SelectedKeys();
            if (keys.Count < 2) { Status("Select two or more worksets to merge - Ctrl or Shift click."); return; }
            var rows = keys.Select(k => (WsmCore.WsRow)Table.ByKey[k]).ToList();
            string master = WsmUi.MergeDialog(Window, rows);
            if (string.IsNullOrEmpty(master)) return;
            string problem;
            List<WsmCore.WsRow> kept = WsmCore.StageMerge(WsRows.ToList(), keys, master, out problem);
            if (problem.Length > 0) { Status(problem); return; }
            PopulateTable(kept);
            int moving = WsRows.Where(r => r.Merge && r.DeleteTo == master).Sum(r => r.Count);
            Status("Merge into " + Table.ByKey[master].EffectiveName() + " staged in red - " + moving + " elements move onto it and the others go when you press Apply.");
        }

        // ---------------------------------------------------------- lifetime

        public void ShowWindow()
        {
            Open = this;
            WsmUi.Own(Window, UiApp.MainWindowHandle);
            Window.Show();
        }
    }
}




