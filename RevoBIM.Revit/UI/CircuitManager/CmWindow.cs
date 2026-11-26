using System;
using System.Collections.Generic;
using System.Data;
using System.Globalization;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Data;
using System.Windows.Input;
using System.Windows.Markup;
using System.Windows.Media;
using System.Windows.Shapes;
using System.Windows.Threading;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Electrical;
using Autodesk.Revit.UI;
using RevoBIM.Helpers;
using RevoBIM.Tools.CircuitManager;

using Binding = System.Windows.Data.Binding;
using Button = System.Windows.Controls.Button;
using CheckBox = System.Windows.Controls.CheckBox;
using Clipboard = System.Windows.Clipboard;
using Control = System.Windows.Controls.Control;
using Panel = System.Windows.Controls.Panel;
using Visibility = System.Windows.Visibility;
using ContextMenu = System.Windows.Controls.ContextMenu;
using DataGrid = System.Windows.Controls.DataGrid;
using Orientation = System.Windows.Controls.Orientation;
using Path = System.Windows.Shapes.Path;
using Popup = System.Windows.Controls.Primitives.Popup;
using TextBox = System.Windows.Controls.TextBox;

namespace RevoBIM.UI.CircuitManager
{
    /// <summary>
    /// Circuit Manager main window (cm_main.py). Every electrical circuit in the project in one Excel-style table:
    /// a keyword box and an Excel tick list on every column heading, parameter columns added from anything circuits
    /// carry, Path Mode from a dropdown on a whole selection, Path Offset typed or Ctrl+C / Ctrl+V, nothing written
    /// until Apply. Modeless: Revit stays usable, writes go through an ExternalEvent. Filter and sort decisions are
    /// held in hidden columns so nothing moves under the cursor; F5 catches the view up.
    /// </summary>
    internal sealed class CmWindow : ThemedWindow
    {
        private sealed class StateStyle
        {
            public string Value, Bg, Fg;
            public bool Bold;
        }

        private sealed class HeadInfo
        {
            public Border Border;
            public TextBlock Label;
            public Path Caret;
            public TextBox Box;
            public string Head;
        }

        private sealed class TickPopup
        {
            public Popup Popup;
            public TextBox Search;
            public ListBox List;
            public TextBlock Count;
            public string Key;
            public List<KeyValuePair<string, CheckBox>> Items = new List<KeyValuePair<string, CheckBox>>();
        }

        private static readonly StateStyle[] StateStyles =
        {
            new StateStyle { Value = "staged", Bg = "StagedBg", Fg = "StagedText", Bold = false },
            new StateStyle { Value = "bad", Bg = "BadBg", Fg = "BadText", Bold = true },
            new StateStyle { Value = "copy", Bg = "CopyBg", Fg = null, Bold = false },
            new StateStyle { Value = "ro", Bg = "ReadOnlyBg", Fg = null, Bold = false },
        };

        private const string Caret = "M 0,0 L 8,0 L 4,5 Z";

        private readonly UIApplication uiapp;
        private readonly Document doc;
        private readonly CmRunner runner;
        private readonly CmStage stage = new CmStage();
        private List<CircuitRow> rows = new List<CircuitRow>();
        private Dictionary<long, int> byEid = new Dictionary<long, int>();
        private List<DataRow> dtRows = new List<DataRow>();
        private List<string> cols = new List<string>();
        private readonly Dictionary<string, string> colName = new Dictionary<string, string>();
        private readonly Dictionary<string, string> keyOfName = new Dictionary<string, string>();
        private readonly Dictionary<string, HeadInfo> heads = new Dictionary<string, HeadInfo>();
        private readonly Dictionary<string, string> textFilters = new Dictionary<string, string>();
        private readonly Dictionary<string, HashSet<string>> tickFilters = new Dictionary<string, HashSet<string>>();
        private readonly Dictionary<Tuple<long, string>, string> bad = new Dictionary<Tuple<long, string>, string>();
        private HashSet<Tuple<long, string>> copyMarks = new HashSet<Tuple<long, string>>();
        private HashSet<int> selected = new HashSet<int>();
        private HashSet<int> hlRows = new HashSet<int>();
        private string sortKey;
        private bool sortDesc;
        private bool editing;
        private bool forceClose;
        private bool selPending;
        private DataTable table;
        private DataView view;
        private readonly List<ContextMenu> dressed = new List<ContextMenu>();
        private List<string> paramKeys;
        private readonly DataGrid dg;
        private readonly TextBlock status;
        private readonly DispatcherTimer filterTimer;
        private readonly DispatcherTimer watchdog;
        private readonly TickPopup tick;

        public CmWindow(UIApplication uiapp) : base(CmUi.Config, "CircuitManager.xaml")
        {
            this.uiapp = uiapp;
            doc = uiapp.ActiveUIDocument.Document;
            runner = new CmRunner(CmSettings.Log);
            sortKey = CmSettings.Get("sort_key");
            if (string.IsNullOrEmpty(sortKey)) sortKey = "panel";
            sortDesc = CmSettings.Get("sort_desc") == "1";
            paramKeys = CmLogic.SplitColumns(CmSettings.Get("columns")).Select(n => CmRevit.ParamPrefix + n).ToList();

            dg = Find<DataGrid>("dg");
            status = Find<TextBlock>("status_text");
            filterTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(220) };
            filterTimer.Tick += (s, a) =>
            {
                filterTimer.Stop();
                ApplyView();
            };
            watchdog = new DispatcherTimer { Interval = TimeSpan.FromSeconds(20) };
            watchdog.Tick += OnWatchdog;
            tick = BuildTickPopup();

            Find<Button>("add_col_btn").Click += OnAddColumns;
            Find<Button>("reset_btn").Click += (s, a) => ResetFilters();
            Find<Button>("refresh_btn").Click += (s, a) => Reload();
            Find<Button>("apply_btn").Click += (s, a) => Apply();
            Find<Button>("undo_btn").Click += (s, a) => Undo();
            Find<Button>("clear_btn").Click += (s, a) => ClearStaged();
            var dbg = Find<CheckBox>("debug_chk");
            dbg.IsChecked = CmSettings.Get("debug") == "1";
            dbg.Checked += (s, a) => CmSettings.Set("debug", "1");
            dbg.Unchecked += (s, a) => CmSettings.Set("debug", "0");

            dg.Sorting += OnSorting;
            dg.SelectedCellsChanged += OnSelectionChanged;
            dg.PreviewMouseLeftButtonDown += OnGridMouseDown;
            dg.PreviewKeyDown += OnGridKey;
            dg.BeginningEdit += OnBeginningEdit;
            dg.CellEditEnding += OnCellEditEnding;
            Win.Closing += OnClosing;

            ReadModel();
            BuildTable(null);
        }

        // ================================================================== reading
        private void ReadModel()
        {
            Mouse.OverrideCursor = Cursors.Wait;
            try
            {
                rows = CmRevit.ReadRows(doc, paramKeys);
            }
            finally
            {
                Mouse.OverrideCursor = null;
            }
            byEid = new Dictionary<long, int>();
            for (int i = 0; i < rows.Count; i++) byEid[rows[i].Eid] = i;
            var gone = stage.Edits.Keys.Where(k => !byEid.ContainsKey(k.Item1)).ToList();
            stage.Clear(gone);
            foreach (var k in bad.Keys.ToList())
                if (!byEid.ContainsKey(k.Item1)) bad.Remove(k);
            CmSettings.Log("read " + rows.Count + " circuits, " + paramKeys.Count + " parameter columns");
        }

        private void Reload()
        {
            var keep = new HashSet<long>(selected.Where(i => i < rows.Count).Select(i => rows[i].Eid));
            ReadModel();
            BuildTable(keep);
            SetStatus("Read " + rows.Count + " circuits from the model. Staged changes kept.");
        }

        // ================================================================== columns and table
        private List<KeyValuePair<string, string>> ColumnDefs()
        {
            var output = new List<KeyValuePair<string, string>>();
            foreach (FixedColumn f in CmRevit.Fixed) output.Add(new KeyValuePair<string, string>(f.Key, f.Heading));
            foreach (string key in paramKeys)
                output.Add(new KeyValuePair<string, string>(key, key.Substring(CmRevit.ParamPrefix.Length)));
            return output;
        }

        private string Display(int i, string key)
        {
            CircuitRow row = rows[i];
            string staged = stage.Get(row.Eid, key);
            return staged ?? row.V(key);
        }

        private string CellState(int i, string key)
        {
            CircuitRow row = rows[i];
            var k = Tuple.Create(row.Eid, key);
            if (stage.Has(row.Eid, key)) return "staged";
            if (bad.ContainsKey(k)) return "bad";
            if (copyMarks.Contains(k)) return "copy";
            if (ColEditable(key) && !row.CanEdit(key)) return "ro";
            return "";
        }

        private bool ColEditable(string key)
        {
            return rows.Any(r => r.CanEdit(key));
        }

        private void BuildTable(HashSet<long> reselect)
        {
            List<KeyValuePair<string, string>> defs = ColumnDefs();
            cols = defs.Select(d => d.Key).ToList();
            colName.Clear();
            keyOfName.Clear();
            var dt = new DataTable("circuits");
            foreach (string c in new[] { "ridx", "vis", "gkey", "hl" }) dt.Columns.Add(c, typeof(string));
            for (int i = 0; i < defs.Count; i++)
            {
                string name = "f" + i;
                colName[defs[i].Key] = name;
                keyOfName[name] = defs[i].Key;
                dt.Columns.Add(name, typeof(string));
                dt.Columns.Add(name + "_s", typeof(string));
            }
            dt.BeginLoadData();
            dtRows = new List<DataRow>();
            for (int i = 0; i < rows.Count; i++)
            {
                var values = new List<object> { i.ToString(CultureInfo.InvariantCulture), "1", "", "0" };
                foreach (string key in cols)
                {
                    values.Add(Display(i, key));
                    values.Add(CellState(i, key));
                }
                dtRows.Add(dt.Rows.Add(values.ToArray()));
            }
            dt.EndLoadData();
            table = dt;
            dg.ItemsSource = null;
            dg.Columns.Clear();
            heads.Clear();
            dressed.Clear();
            foreach (var d in defs) dg.Columns.Add(MakeColumn(d.Key, d.Value));
            view = dt.DefaultView;
            ApplyView();
            view.RowFilter = "[vis] = '1'";
            view.Sort = "[gkey] ASC";
            dg.ItemsSource = view;
            selected = new HashSet<int>();
            hlRows = new HashSet<int>();
            if (reselect != null && reselect.Count > 0) Reselect(reselect);
            RefreshCounts();
        }

        private void Reselect(HashSet<long> eids)
        {
            try
            {
                foreach (DataRowView item in view)
                {
                    int i = int.Parse((string)item.Row["ridx"], CultureInfo.InvariantCulture);
                    if (!eids.Contains(rows[i].Eid)) continue;
                    foreach (DataGridColumn col in dg.Columns) dg.SelectedCells.Add(new DataGridCellInfo(item, col));
                }
            }
            catch (Exception)
            {
                CmSettings.Log("reselect failed");
            }
        }

        private DataGridColumn MakeColumn(string key, string head)
        {
            string name = colName[key];
            bool editable = ColEditable(key);
            DataGridColumn col;
            if (key == "pm")
            {
                var tcol = new DataGridTemplateColumn();
                tcol.CellTemplate = (DataTemplate)XamlReader.Parse(
                    "<DataTemplate xmlns=\"http://schemas.microsoft.com/winfx/2006/xaml/presentation\"><DockPanel Background=\"Transparent\">" +
                    "<Path DockPanel.Dock=\"Right\" Data=\"" + Caret + "\" Margin=\"6,0,2,0\" VerticalAlignment=\"Center\" Fill=\"{DynamicResource Muted}\"/>" +
                    "<TextBlock Text=\"{Binding " + name + "}\" VerticalAlignment=\"Center\" TextTrimming=\"CharacterEllipsis\"/></DockPanel></DataTemplate>");
                tcol.SortMemberPath = name;
                tcol.IsReadOnly = true;
                col = tcol;
            }
            else
            {
                var tcol = new DataGridTextColumn();
                // NOT OneWay: DataGridBoundColumn coerces IsReadOnly to true for a OneWay binding, silently. TwoWay + Explicit
                // is editable but never pushes the typed text into the table: CellEditEnding stages it, validated.
                tcol.Binding = new Binding(name) { Mode = BindingMode.TwoWay, UpdateSourceTrigger = UpdateSourceTrigger.Explicit };
                tcol.SortMemberPath = name;
                tcol.IsReadOnly = !editable;
                if (editable) tcol.EditingElementStyle = (Style)Win.FindResource("CmEditBox");
                col = tcol;
            }
            col.CanUserSort = true;
            col.MinWidth = key == "pm" || key == "po" || key == "load" ? 120 : 90;
            col.Width = new DataGridLength(key == "load" || key == "pm" ? 1.4 : 1.0, DataGridLengthUnitType.Star);
            col.CellStyle = CellStyle(name, editable);
            col.Header = MakeHeader(key, head, editable);
            return col;
        }

        private Style CellStyle(string name, bool editable)
        {
            var style = new Style(typeof(DataGridCell), (Style)Win.FindResource("CmCell"));
            if (!editable) style.Setters.Add(new Setter(Control.ForegroundProperty, new DynamicResourceExtension("Muted")));
            foreach (StateStyle ss in StateStyles)
            {
                var trig = new DataTrigger { Binding = new Binding(name + "_s"), Value = ss.Value };
                trig.Setters.Add(new Setter(Control.BackgroundProperty, new DynamicResourceExtension(ss.Bg)));
                if (ss.Fg != null) trig.Setters.Add(new Setter(Control.ForegroundProperty, new DynamicResourceExtension(ss.Fg)));
                if (ss.Bold) trig.Setters.Add(new Setter(Control.FontWeightProperty, FontWeights.Bold));
                style.Triggers.Add(trig);
            }
            return style;
        }

        private object MakeHeader(string key, string head, bool editable)
        {
            var outer = new Border
            {
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(3),
                Padding = new Thickness(2),
                Background = Brushes.Transparent,
            };
            var stack = new StackPanel();
            var top = new DockPanel();
            var caret = new Button { Width = 20, Height = 18, ToolTip = "Pick values to show" };
            caret.SetResourceReference(FrameworkElement.StyleProperty, "ChromeBtn");
            var glyph = new Path { Data = Geometry.Parse(Caret) };
            glyph.SetResourceReference(Shape.FillProperty, "Muted");
            caret.Content = glyph;
            DockPanel.SetDock(caret, Dock.Right);
            caret.Click += (s, a) =>
            {
                try
                {
                    OpenTickList(key, (FrameworkElement)s);
                }
                catch (Exception ex)
                {
                    CmSettings.Log(ex.ToString());
                }
            };
            top.Children.Add(caret);
            var label = new TextBlock
            {
                Text = head,
                FontWeight = FontWeights.SemiBold,
                TextTrimming = TextTrimming.CharacterEllipsis,
                VerticalAlignment = VerticalAlignment.Center,
                ToolTip = head + (editable ? " - editable" : " - read only"),
            };
            label.SetResourceReference(TextBlock.ForegroundProperty, editable ? "Blue" : "Text");
            top.Children.Add(label);
            stack.Children.Add(top);
            string existing;
            textFilters.TryGetValue(key, out existing);
            var box = new TextBox { Tag = "filter...", Height = 22, FontSize = 11, Margin = new Thickness(0, 3, 0, 0), Text = existing ?? "" };
            box.TextChanged += (s, a) =>
            {
                textFilters[key] = ((TextBox)s).Text;
                filterTimer.Stop();
                filterTimer.Start();
            };
            stack.Children.Add(box);
            outer.Child = stack;
            var menu = new ContextMenu();
            AddMenu(menu, "Sort A to Z", () => SortBy(key, false));
            AddMenu(menu, "Sort Z to A", () => SortBy(key, true));
            AddMenu(menu, "Clear this filter", () => ClearFilter(key));
            if (key.StartsWith(CmRevit.ParamPrefix, StringComparison.Ordinal))
            {
                menu.Items.Add(new Separator());
                AddMenu(menu, "Remove this column", () => RemoveColumn(key));
            }
            Dress(menu);
            dressed.Add(menu);
            outer.ContextMenu = menu;
            heads[key] = new HeadInfo { Border = outer, Label = label, Caret = glyph, Box = box, Head = head };
            PaintHead(key);
            return outer;
        }

        private void AddMenu(ContextMenu menu, string text, Action fn)
        {
            var mi = new MenuItem { Header = text };
            mi.Click += Wrap(fn);
            menu.Items.Add(mi);
        }

        private RoutedEventHandler Wrap(Action fn)
        {
            return (s, a) =>
            {
                try
                {
                    fn();
                }
                catch (Exception ex)
                {
                    CmSettings.Log(ex.ToString());
                    SetStatus("That did not work - see the debug log.");
                }
            };
        }

        private void PaintHead(string key)
        {
            HeadInfo h;
            if (!heads.TryGetValue(key, out h)) return;
            bool sortedHere = key == sortKey;
            h.Border.SetResourceReference(Border.BorderBrushProperty, sortedHere ? "Orange" : "HeadingBg");
            string arrow = sortedHere ? (sortDesc ? "  ▼" : "  ▲") : "";
            h.Label.Text = h.Head + arrow;
            h.Caret.SetResourceReference(Shape.FillProperty, CmLogic.IsFiltered(key, textFilters, tickFilters) ? "Orange" : "Muted");
        }

        protected override void OnRepainted()
        {
            foreach (string key in heads.Keys.ToList()) PaintHead(key);
            foreach (ContextMenu menu in dressed.ToList())
            {
                try
                {
                    ApplyPalette(menu, Resolved);
                }
                catch (Exception)
                {
                }
            }
        }

        // ================================================================== filter, sort, F5
        private Dictionary<string, string> RowValues(int i)
        {
            var d = new Dictionary<string, string>();
            foreach (string k in cols) d[k] = Display(i, k);
            return d;
        }

        /// <summary>Takes the filter and sort decisions again (F5).</summary>
        private void ApplyView()
        {
            var values = Enumerable.Range(0, rows.Count).Select(RowValues).ToList();
            for (int i = 0; i < values.Count; i++)
                SetCell(dtRows[i], "vis", CmLogic.RowVisible(values[i], textFilters, tickFilters) ? "1" : "0");
            string key = cols.Contains(sortKey) ? sortKey : "panel";
            List<int> order = CmLogic.SortOrder(values, "num", false);
            if (key != "num")
            {
                // stable: circuit number stays the second level, so a panel reads 1, 2, 3 under its heading
                order = CmLogic.StableSort(order, (x, y) =>
                {
                    int c = CmLogic.NaturalCompare(values[x].ContainsKey(key) ? values[x][key] : "", values[y].ContainsKey(key) ? values[y][key] : "");
                    return sortDesc ? -c : c;
                });
            }
            else if (sortDesc) order.Reverse();
            for (int place = 0; place < order.Count; place++)
                SetCell(dtRows[order[place]], "gkey", place.ToString("D8", CultureInfo.InvariantCulture));
            foreach (string k in heads.Keys.ToList()) PaintHead(k);
            RefreshCounts();
        }

        private static bool SetCell(DataRow dr, string col, string value)
        {
            if ((dr[col] as string ?? "") == value) return false;
            dr[col] = value;
            return true;
        }

        private void ClearFilter(string key)
        {
            textFilters.Remove(key);
            tickFilters.Remove(key);
            HeadInfo h;
            if (heads.TryGetValue(key, out h)) h.Box.Text = "";
            ApplyView();
        }

        private void ResetFilters()
        {
            tickFilters.Clear();
            foreach (HeadInfo h in heads.Values.ToList()) h.Box.Text = "";
            textFilters.Clear();
            ApplyView();
            SetStatus("Filters cleared.");
        }

        private void SortBy(string key, bool desc)
        {
            sortKey = key;
            sortDesc = desc;
            CmSettings.Set("sort_key", key, false);
            CmSettings.Set("sort_desc", desc ? "1" : "0");
            ApplyView();
        }

        private void OnSorting(object sender, DataGridSortingEventArgs args)
        {
            args.Handled = true;
            string key;
            if (!keyOfName.TryGetValue(args.Column.SortMemberPath, out key)) return;
            bool desc = key == sortKey ? !sortDesc : false;
            SortBy(key, desc);
        }

        // ------------------------------------------------------------------ Excel tick list
        private TickPopup BuildTickPopup()
        {
            var pop = new Popup { StaysOpen = false, AllowsTransparency = true, Placement = PlacementMode.Bottom };
            var border = new Border { BorderThickness = new Thickness(1), Padding = new Thickness(8), Width = 280 };
            border.SetResourceReference(Border.BackgroundProperty, "FieldBg");
            border.SetResourceReference(Border.BorderBrushProperty, "Edge");
            var stackPanel = new StackPanel();
            var search = new TextBox { Tag = "Search values...", Height = 26 };
            stackPanel.Children.Add(search);
            var row = new DockPanel { Margin = new Thickness(0, 6, 0, 6) };
            var bAll = new Button { Content = "Select all" };
            var bNone = new Button { Content = "Untick all", Margin = new Thickness(6, 0, 0, 0) };
            var count = new TextBlock { VerticalAlignment = VerticalAlignment.Center, HorizontalAlignment = HorizontalAlignment.Right };
            count.SetResourceReference(TextBlock.ForegroundProperty, "Muted");
            DockPanel.SetDock(bAll, Dock.Left);
            DockPanel.SetDock(bNone, Dock.Left);
            row.Children.Add(bAll);
            row.Children.Add(bNone);
            row.Children.Add(count);
            stackPanel.Children.Add(row);
            var lst = new ListBox { MaxHeight = 300, MinHeight = 80 };
            stackPanel.Children.Add(lst);
            var foot = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right, Margin = new Thickness(0, 8, 0, 0) };
            var cancel = new Button { Content = "Cancel" };
            var ok = new Button { Content = "OK", Margin = new Thickness(6, 0, 0, 0) };
            ok.SetResourceReference(FrameworkElement.StyleProperty, "GreenBtn");
            foot.Children.Add(cancel);
            foot.Children.Add(ok);
            stackPanel.Children.Add(foot);
            border.Child = stackPanel;
            pop.Child = border;
            // in the window's tree so it inherits the theme and palette
            Find<Panel>("root_grid").Children.Add(pop);
            var t = new TickPopup { Popup = pop, Search = search, List = lst, Count = count };
            search.TextChanged += (s, a) => TickSearch(t);
            bAll.Click += (s, a) => TickSet(t, true);
            bNone.Click += (s, a) => TickSet(t, false);
            cancel.Click += (s, a) => TickClose(t, false);
            ok.Click += (s, a) => TickClose(t, true);
            return t;
        }

        private void OpenTickList(string key, FrameworkElement anchor)
        {
            TickPopup t = tick;
            t.Key = key;
            List<string> values = CmLogic.ListValues(Enumerable.Range(0, rows.Count).Select(RowValues), key, textFilters, tickFilters);
            HashSet<string> allowed;
            tickFilters.TryGetValue(key, out allowed);
            t.List.Items.Clear();
            t.Items = new List<KeyValuePair<string, CheckBox>>();
            foreach (string v in values)
            {
                var cb = new CheckBox { Content = v.Length > 0 ? v : "(blank)", IsChecked = allowed == null || allowed.Contains(v) };
                cb.Checked += (s, a) => TickCount(t);
                cb.Unchecked += (s, a) => TickCount(t);
                t.List.Items.Add(cb);
                t.Items.Add(new KeyValuePair<string, CheckBox>(v, cb));
            }
            t.Search.Text = "";
            t.Popup.PlacementTarget = anchor;
            t.Popup.IsOpen = true;
            TickCount(t);
        }

        private static void TickSearch(TickPopup t)
        {
            string term = t.Search.Text;
            foreach (var i in t.Items) i.Value.Visibility = CmLogic.MatchesText(i.Key, term) ? Visibility.Visible : Visibility.Collapsed;
        }

        private static void TickSet(TickPopup t, bool value)
        {
            foreach (var i in t.Items)
                if (i.Value.Visibility == Visibility.Visible) i.Value.IsChecked = value;
        }

        private static void TickCount(TickPopup t)
        {
            int n = t.Items.Count(i => i.Value.IsChecked == true);
            t.Count.Text = n + " / " + t.Items.Count;
        }

        private void TickClose(TickPopup t, bool accept)
        {
            t.Popup.IsOpen = false;
            if (!accept || t.Key == null) return;
            var ticked = new HashSet<string>(t.Items.Where(i => i.Value.IsChecked == true).Select(i => i.Key));
            if (ticked.Count == t.Items.Count) tickFilters.Remove(t.Key);
            else tickFilters[t.Key] = ticked;
            ApplyView();
        }

        // ================================================================== selection
        private void OnSelectionChanged(object sender, SelectedCellsChangedEventArgs args)
        {
            if (selPending) return;
            selPending = true;
            RevoChrome.Later(Win, AfterSelection);
        }

        private void AfterSelection()
        {
            selPending = false;
            var sel = new HashSet<int>();
            try
            {
                foreach (DataGridCellInfo info in dg.SelectedCells)
                {
                    try
                    {
                        sel.Add(int.Parse((string)((DataRowView)info.Item)["ridx"], CultureInfo.InvariantCulture));
                    }
                    catch (Exception)
                    {
                    }
                }
            }
            catch (Exception)
            {
            }
            selected = sel;
            foreach (int i in hlRows.Where(x => !sel.Contains(x))) SetCell(dtRows[i], "hl", "0");
            foreach (int i in sel.Where(x => !hlRows.Contains(x))) SetCell(dtRows[i], "hl", "1");
            hlRows = sel;
            RefreshCounts();
        }

        private static DataGridCell CellUnder(DependencyObject source)
        {
            DependencyObject el = source;
            while (el != null && !(el is DataGridCell))
            {
                try
                {
                    el = el is Visual || el is System.Windows.Media.Media3D.Visual3D ? VisualTreeHelper.GetParent(el) : LogicalTreeHelper.GetParent(el);
                }
                catch (Exception)
                {
                    el = LogicalTreeHelper.GetParent(el);
                }
            }
            return el as DataGridCell;
        }

        /// <summary>Click a Path Mode on a selected circuit: the dropdown, for all of the selection. Handled, so the click does not drop the selection.</summary>
        private void OnGridMouseDown(object sender, MouseButtonEventArgs args)
        {
            try
            {
                if (RevoChrome.CtrlDown() || RevoChrome.ShiftDown() || args.ClickCount > 1) return;
                DataGridCell cell = CellUnder(args.OriginalSource as DependencyObject);
                if (cell == null || cell.Column == null) return;
                string key;
                if (!keyOfName.TryGetValue(cell.Column.SortMemberPath, out key) || key != "pm") return;
                int i = int.Parse((string)((DataRowView)cell.DataContext)["ridx"], CultureInfo.InvariantCulture);
                if (selected.Contains(i) && selected.Count > 1)
                {
                    args.Handled = true;
                    OpenModeMenu(selected.OrderBy(x => x).ToList(), cell);
                }
                else
                {
                    RevoChrome.Later(Win, () => OpenModeMenu(new List<int> { i }, cell));
                }
            }
            catch (Exception ex)
            {
                CmSettings.Log(ex.ToString());
            }
        }

        private void OpenModeMenu(List<int> targets, FrameworkElement anchor)
        {
            targets = targets.Where(i => rows[i].CanEdit("pm")).ToList();
            if (targets.Count == 0)
            {
                SetStatus("Path mode cannot be changed on that circuit.");
                return;
            }
            var menu = new ContextMenu();
            Dress(menu);   // transient: built per click
            var current = new HashSet<string>(targets.Select(i => CmLogic.ParsePathMode(Display(i, "pm")) ?? ""));
            int nCustom = targets.Count(i => rows[i].CustomOk);
            menu.Items.Add(new MenuItem
            {
                Header = "Set path mode on " + targets.Count + " circuit" + (targets.Count == 1 ? "" : "s"),
                IsEnabled = false,
            });
            menu.Items.Add(new Separator());
            foreach (PathModeInfo pm in CmLogic.PathModes)
            {
                string text = pm.Label;
                var mi = new MenuItem();
                if (pm.Name == "Custom")
                {
                    text = pm.Label + "  (" + nCustom + " of " + targets.Count + " have a custom path)";
                    mi.IsEnabled = nCustom > 0;
                }
                mi.Header = text;
                mi.IsChecked = current.Count == 1 && current.Contains(pm.Name);
                string modeName = pm.Name;
                List<int> t = targets.ToList();
                mi.Click += Wrap(() => StageMode(t, modeName));
                menu.Items.Add(mi);
            }
            menu.PlacementTarget = anchor;
            menu.Placement = PlacementMode.Bottom;
            menu.IsOpen = true;
        }

        private void StageMode(List<int> targets, string mode)
        {
            var custom = new Dictionary<int, bool>();
            foreach (int i in targets) custom[i] = rows[i].CustomOk;
            List<int> ok;
            List<KeyValuePair<int, string>> refused;
            CmLogic.ModeTargets(targets, mode, custom, out ok, out refused);
            string label = CmLogic.PathModeLabel(mode);
            int n = StageChanges(ok.Select(i => Tuple.Create(i, "pm", label)).ToList());
            string msg = "Path mode set to " + label + " on " + n + " circuit" + (n == 1 ? "" : "s") + ".";
            if (refused.Count > 0) msg += " " + refused.Count + " skipped: no custom path stored.";
            SetStatus(msg);
        }

        // ================================================================== staging
        /// <summary>changes: (row index, key, text already validated).</summary>
        private int StageChanges(List<Tuple<int, string, string>> changes)
        {
            if (changes.Count == 0) return 0;
            var batch = new List<Tuple<long, string, string>>();
            var originals = new Dictionary<Tuple<long, string>, string>();
            var kinds = new Dictionary<string, string>();
            foreach (var ch in changes)
            {
                CircuitRow row = rows[ch.Item1];
                batch.Add(Tuple.Create(row.Eid, ch.Item2, ch.Item3));
                originals[Tuple.Create(row.Eid, ch.Item2)] = row.V(ch.Item2);
                kinds[ch.Item2] = row.Kind(ch.Item2);
                bad.Remove(Tuple.Create(row.Eid, ch.Item2));
            }
            List<Tuple<long, string>> touched = stage.ApplyBatch(batch, originals, kinds);
            RepaintCells(touched);
            RefreshCounts();
            CmSettings.Log("staged " + touched.Count + " cell(s)");
            return changes.Count;
        }

        private string Validate(int i, string key, string text, out string error)
        {
            error = null;
            CircuitRow row = rows[i];
            if (!row.CanEdit(key))
            {
                error = row.Reason(key, "read only");
                return null;
            }
            string value = CmLogic.NormaliseInput(row.Kind(key), text, out error);
            if (error != null) return null;
            if (key == "pm" && CmLogic.ParsePathMode(value) == "Custom" && !row.CustomOk)
            {
                error = "no custom path stored";
                return null;
            }
            return value;
        }

        private void RepaintCells(IEnumerable<Tuple<long, string>> keys)
        {
            foreach (var k in keys)
            {
                int i;
                string name;
                if (!byEid.TryGetValue(k.Item1, out i) || !colName.TryGetValue(k.Item2, out name)) continue;
                DataRow dr = dtRows[i];
                SetCell(dr, name, Display(i, k.Item2));
                SetCell(dr, name + "_s", CellState(i, k.Item2));
            }
        }

        private void Undo()
        {
            List<Tuple<long, string>> touched = stage.UndoLast();
            if (touched.Count == 0)
            {
                SetStatus("Nothing to undo.");
                return;
            }
            RepaintCells(touched);
            RefreshCounts();
            SetStatus("Undid " + touched.Count + " staged cell" + (touched.Count == 1 ? "" : "s") + ".");
        }

        private void ClearStaged()
        {
            RepaintCells(stage.Clear());
            RefreshCounts();
            SetStatus("Staged changes cleared.");
        }

        // ------------------------------------------------------------------
        private void OnBeginningEdit(object sender, DataGridBeginningEditEventArgs args)
        {
            try
            {
                string key;
                keyOfName.TryGetValue(args.Column.SortMemberPath, out key);
                int i = int.Parse((string)((DataRowView)args.Row.Item)["ridx"], CultureInfo.InvariantCulture);
                if (key == null || !rows[i].CanEdit(key))
                {
                    args.Cancel = true;
                    SetStatus("That cell cannot be edited: " + rows[i].Reason(key ?? "", "read only") + ".");
                    return;
                }
                editing = true;
            }
            catch (Exception)
            {
                editing = false;
                args.Cancel = true;
            }
        }

        private void OnCellEditEnding(object sender, DataGridCellEditEndingEventArgs args)
        {
            editing = false;
            string key, text;
            int i;
            try
            {
                if (args.EditAction != DataGridEditAction.Commit) return;
                keyOfName.TryGetValue(args.Column.SortMemberPath, out key);
                i = int.Parse((string)((DataRowView)args.Row.Item)["ridx"], CultureInfo.InvariantCulture);
                text = ((TextBox)args.EditingElement).Text;
            }
            catch (Exception)
            {
                return;
            }
            RevoChrome.Later(Win, () =>
            {
                string err;
                string value = Validate(i, key, text, out err);
                if (err != null)
                {
                    RepaintCells(new[] { Tuple.Create(rows[i].Eid, key) });
                    SetStatus("Not staged - " + err + ": \"" + text + "\".");
                    return;
                }
                StageChanges(new List<Tuple<int, string, string>> { Tuple.Create(i, key, value) });
            });
        }

        // ================================================================== clipboard
        /// <summary>Visible rows in display order, and the visible columns by display index.</summary>
        private void Positions(out List<int> visibleRows, out Dictionary<int, string> colByDisplay)
        {
            visibleRows = new List<int>();
            foreach (DataRowView item in view) visibleRows.Add(int.Parse((string)item.Row["ridx"], CultureInfo.InvariantCulture));
            colByDisplay = new Dictionary<int, string>();
            foreach (DataGridColumn col in dg.Columns)
            {
                string key;
                if (keyOfName.TryGetValue(col.SortMemberPath, out key) && col.Visibility == Visibility.Visible) colByDisplay[col.DisplayIndex] = key;
            }
        }

        private List<Tuple<int, int>> SelectedCells(out List<int> visibleRows, out Dictionary<int, string> colByDisplay)
        {
            Positions(out visibleRows, out colByDisplay);
            var posOf = new Dictionary<int, int>();
            for (int p = 0; p < visibleRows.Count; p++) posOf[visibleRows[p]] = p;
            var output = new List<Tuple<int, int>>();
            foreach (DataGridCellInfo info in dg.SelectedCells)
            {
                int i, c;
                try
                {
                    i = int.Parse((string)((DataRowView)info.Item)["ridx"], CultureInfo.InvariantCulture);
                    c = info.Column.DisplayIndex;
                }
                catch (Exception)
                {
                    continue;
                }
                int p;
                if (posOf.TryGetValue(i, out p) && colByDisplay.ContainsKey(c)) output.Add(Tuple.Create(p, c));
            }
            return output;
        }

        private void Copy()
        {
            List<int> visibleRows;
            Dictionary<int, string> colByDisplay;
            List<Tuple<int, int>> cells = SelectedCells(out visibleRows, out colByDisplay);
            if (cells.Count == 0)
            {
                SetStatus("Select cells to copy.");
                return;
            }
            var old = copyMarks.ToList();
            copyMarks = new HashSet<Tuple<long, string>>();
            var blockCells = new List<Tuple<int, int, string>>();
            foreach (var pc in cells)
            {
                int i = visibleRows[pc.Item1];
                string key = colByDisplay[pc.Item2];
                blockCells.Add(Tuple.Create(pc.Item1, pc.Item2, Display(i, key)));
                copyMarks.Add(Tuple.Create(rows[i].Eid, key));
            }
            string text = CmLogic.ToClipboard(CmLogic.CopyBlock(blockCells));
            try
            {
                Clipboard.SetText(text);
            }
            catch (Exception)
            {
                SetStatus("The clipboard is busy - try again.");
                return;
            }
            RepaintCells(old.Concat(copyMarks));
            SetStatus("Copied " + cells.Count + " cell" + (cells.Count == 1 ? "" : "s") + ". Select the cells to change and press Ctrl+V.");
        }

        private void Paste()
        {
            string text;
            try
            {
                text = Clipboard.GetText();
            }
            catch (Exception)
            {
                text = "";
            }
            if (string.IsNullOrEmpty(text))
            {
                SetStatus("Nothing on the clipboard.");
                return;
            }
            List<int> visibleRows;
            Dictionary<int, string> colByDisplay;
            List<Tuple<int, int>> cells = SelectedCells(out visibleRows, out colByDisplay);
            if (cells.Count == 0)
            {
                SetStatus("Select the cells to paste into.");
                return;
            }
            List<string[]> clip = CmLogic.ParseClipboard(text);
            List<int> colPositions = colByDisplay.Keys.OrderBy(x => x).ToList();
            List<Tuple<int, int, string>> plan = CmLogic.PastePlan(clip, cells, Enumerable.Range(0, visibleRows.Count).ToList(), colPositions);
            var changes = new List<Tuple<int, string, string>>();
            var skipped = new List<string>();
            foreach (var item in plan)
            {
                int i = visibleRows[item.Item1];
                string key = colByDisplay[item.Item2];
                string err;
                string value = Validate(i, key, item.Item3, out err);
                if (err != null) skipped.Add(err);
                else changes.Add(Tuple.Create(i, key, value));
            }
            RepaintCells(copyMarks.ToList());
            copyMarks = new HashSet<Tuple<long, string>>();
            int n = StageChanges(changes);
            string msg = "Pasted into " + n + " cell" + (n == 1 ? "" : "s") + ".";
            if (skipped.Count > 0)
            {
                List<string> reasons = skipped.Distinct().OrderBy(x => x, StringComparer.Ordinal).Take(3).ToList();
                msg += " " + skipped.Count + " skipped (" + string.Join(", ", reasons) + ").";
            }
            SetStatus(msg);
        }

        private void ClearCopyMarks()
        {
            var old = copyMarks.ToList();
            copyMarks = new HashSet<Tuple<long, string>>();
            RepaintCells(old);
        }

        // ================================================================== keys
        private bool Typing()
        {
            return editing || Keyboard.FocusedElement is TextBox;
        }

        private void OnGridKey(object sender, KeyEventArgs args)
        {
            if (Typing()) return;   // the text box's own Ctrl+C / Ctrl+V
            bool ctrl = RevoChrome.CtrlDown();
            bool handled = true;
            if (ctrl && args.Key == Key.C) Copy();
            else if (ctrl && args.Key == Key.V) Paste();
            else if (ctrl && args.Key == Key.Z) Undo();
            else if (args.Key == Key.Escape && copyMarks.Count > 0) ClearCopyMarks();
            else handled = false;
            if (handled) args.Handled = true;
        }

        protected override void OnKey(KeyEventArgs args, Key key, bool ctrl, bool shift)
        {
            if (key == Key.F5)
            {
                ApplyView();
                args.Handled = true;
            }
            else if (ctrl && key == Key.S)
            {
                Apply();
                args.Handled = true;
            }
        }

        // ================================================================== columns
        private void OnAddColumns(object sender, RoutedEventArgs args)
        {
            List<ParamInfo> parameters;
            try
            {
                parameters = CmRevit.AvailableParameters(CmRevit.CollectCircuits(doc));
            }
            catch (Exception ex)
            {
                CmSettings.Log(ex.ToString());
                SetStatus("Could not list the circuit parameters.");
                return;
            }
            List<string> shown = paramKeys.Select(k => k.Substring(CmRevit.ParamPrefix.Length)).ToList();
            List<string> picked = new CmParamPicker(this, parameters, shown).ShowPicker();
            if (picked == null) return;
            List<string> keep = shown.Where(n => picked.Contains(n)).ToList();
            List<string> added = parameters.Where(p => picked.Contains(p.Name) && !keep.Contains(p.Name)).Select(p => p.Name).ToList();
            List<string> all = keep.Concat(added).ToList();
            paramKeys = all.Select(n => CmRevit.ParamPrefix + n).ToList();
            CmSettings.Set("columns", CmLogic.JoinColumns(all));
            Reload();
        }

        private void RemoveColumn(string key)
        {
            if (!paramKeys.Contains(key)) return;
            paramKeys.Remove(key);
            textFilters.Remove(key);
            tickFilters.Remove(key);
            CmSettings.Set("columns", CmLogic.JoinColumns(paramKeys.Select(k => k.Substring(CmRevit.ParamPrefix.Length))));
            Reload();
        }

        // ================================================================== apply
        private void Apply()
        {
            if (runner.Busy)
            {
                SetStatus("Still writing the last change...");
                CmSettings.Log("apply ignored while busy");
                return;
            }
            Dictionary<long, List<KeyValuePair<string, string>>> changes = stage.ByElement();
            if (changes.Count == 0)
            {
                SetStatus("Nothing staged to apply.");
                return;
            }
            int n = stage.Count;
            var summary = new SortedDictionary<string, int>(StringComparer.Ordinal);
            foreach (var entry in changes)
            {
                foreach (var kv in entry.Value)
                {
                    string k = ColLabel(kv.Key) + "  ->  " + kv.Value;
                    int c;
                    summary.TryGetValue(k, out c);
                    summary[k] = c + 1;
                }
            }
            List<string> lines = summary.Select(e => e.Key + "   (" + e.Value + " circuit" + (e.Value == 1 ? "" : "s") + ")").ToList();
            string body = string.Join("\n", lines.Take(40));
            if (lines.Count > 40) body += "\n... and " + (lines.Count - 40) + " more";
            string choice = CmDialogs.Ask(this,
                "Apply " + n + " change" + (n == 1 ? "" : "s") + " to " + changes.Count + " circuit" + (changes.Count == 1 ? "" : "s") + "?",
                body, new[] { "Cancel" }, new[] { "Apply", "GreenBtn" });
            if (choice != "Apply") return;
            SetBusy(true);
            SetStatus("Writing " + n + " change" + (n == 1 ? "" : "s") + "...");
            List<string> keys = paramKeys.ToList();
            Document targetDoc = doc;

            Func<UIApplication, object> job = app =>
            {
                // the document the window was opened on, not whichever is active
                if (!targetDoc.IsValidObject) throw new InvalidOperationException("The project this window was opened on has been closed.");
                Dictionary<Tuple<long, string>, string> results = CmRevit.ApplyChanges(targetDoc, changes, CmSettings.Log);
                var fresh = new Dictionary<long, CircuitRow>();
                foreach (ElectricalSystem es in CmRevit.CollectCircuits(targetDoc))
                    if (changes.ContainsKey(es.Id.Value)) fresh[es.Id.Value] = CmRevit.ReadRow(es, keys);
                return Tuple.Create(results, fresh);
            };
            Action<object, string> done = (result, error) => RevoChrome.Later(Win, () => AfterApply(result, error));
            if (!runner.Submit(job, done)) SetBusy(false);
        }

        private string ColLabel(string key)
        {
            HeadInfo h;
            return heads.TryGetValue(key, out h) ? h.Head : key;
        }

        private void AfterApply(object result, string error)
        {
            SetBusy(false);
            if (error != null)
            {
                CmSettings.Log(error);
                CmDialogs.Tell(this, "Nothing was written", error);
                return;
            }
            var pair = (Tuple<Dictionary<Tuple<long, string>, string>, Dictionary<long, CircuitRow>>)result;
            foreach (var entry in pair.Item2)
            {
                int i;
                if (byEid.TryGetValue(entry.Key, out i)) rows[i] = entry.Value;
            }
            var ok = new List<Tuple<long, string>>();
            var refused = new List<Tuple<long, string, string>>();
            foreach (var entry in pair.Item1)
            {
                if (entry.Value == null) ok.Add(entry.Key);
                else
                {
                    refused.Add(Tuple.Create(entry.Key.Item1, entry.Key.Item2, entry.Value));
                    bad[entry.Key] = entry.Value;
                }
            }
            stage.Clear(ok.Concat(refused.Select(r => Tuple.Create(r.Item1, r.Item2))));
            RepaintCells(pair.Item1.Keys.ToList());
            RefreshCounts();
            int changed = ok.Select(o => o.Item1).Distinct().Count();
            string msg = "Applied " + ok.Count + " change" + (ok.Count == 1 ? "" : "s") + " on " + changed + " circuit" + (changed == 1 ? "" : "s") + ".";
            if (refused.Count > 0) msg += " " + refused.Count + " refused - shown red.";
            SetStatus(msg);
            CmSettings.Log(msg);
            if (refused.Count > 0)
            {
                var lines = new List<string>();
                foreach (var r in refused.OrderBy(x => x.Item1).ThenBy(x => x.Item2, StringComparer.Ordinal))
                {
                    string name = r.Item1.ToString(CultureInfo.InvariantCulture);
                    int i;
                    if (byEid.TryGetValue(r.Item1, out i)) name = rows[i].V("panel") + " / " + rows[i].V("num");
                    lines.Add(name + "  " + ColLabel(r.Item2) + ": " + r.Item3);
                }
                CmDialogs.Tell(this, "Revit refused " + refused.Count + " change" + (refused.Count == 1 ? "" : "s"), string.Join("\n", lines.Take(60)));
            }
        }

        /// <summary>Body and buttons go deaf; the shrink button stays live.</summary>
        private void SetBusy(bool busy)
        {
            foreach (string name in new[] { "body", "toolbar", "footer" })
            {
                FrameworkElement el = Find(name);
                if (el != null) el.IsHitTestVisible = !busy;
            }
            Drawer.Busy = busy;
            if (busy) watchdog.Start();
            else watchdog.Stop();
        }

        private void OnWatchdog(object sender, EventArgs args)
        {
            watchdog.Stop();
            if (!runner.Busy) return;
            CmSettings.Log("watchdog freed a busy window");
            runner.Free();
            SetBusy(false);
            SetStatus("Revit did not answer - the window is free again. Press Refresh to see what landed.");
        }

        // ================================================================== status
        private void SetStatus(string text)
        {
            try
            {
                status.Text = text;
            }
            catch (Exception)
            {
            }
        }

        private void RefreshCounts()
        {
            try
            {
                int shown = dtRows.Count(dr => (dr["vis"] as string) == "1");
                SetText("apply_text", "Apply (" + stage.Count + ")");
                Find("apply_btn").IsEnabled = stage.Count > 0;
                Find("undo_btn").IsEnabled = stage.CanUndo;
                SetText("sel_text", rows.Count + " circuits  |  " + shown + " shown  |  " + selected.Count + " selected  |  " + stage.Count + " staged");
                bool filtered = cols.Any(k => CmLogic.IsFiltered(k, textFilters, tickFilters));
                SetText("reset_text", "Reset filters" + (filtered ? " *" : ""));
                if (string.IsNullOrEmpty(status.Text) || status.Text.StartsWith("Reading", StringComparison.Ordinal))
                    SetStatus(rows.Count + " circuits read.");
            }
            catch (Exception)
            {
            }
        }

        // ================================================================== life cycle
        private void OnClosing(object sender, System.ComponentModel.CancelEventArgs args)
        {
            if (forceClose || stage.Count == 0) return;
            int n = stage.Count;
            string choice = CmDialogs.Ask(this, n + " staged change" + (n == 1 ? "" : "s") + " not applied",
                                          "Closing now throws them away.",
                                          new[] { "Close without applying" }, new[] { "Keep open", "GreenBtn" });
            if (choice != "Close without applying") args.Cancel = true;
        }

        protected override void OnClosed()
        {
            CmWindow.Current = null;
            CmSettings.Save();
            CmSettings.Log("closed");
        }

        public static CmWindow Current;

        public void Show()
        {
            RevoChrome.OwnToRevit(Win, uiapp);
            Win.Show();
        }
    }
}
