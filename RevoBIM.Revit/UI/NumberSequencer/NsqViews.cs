using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Media;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using RevoBIM.Tools.NumberSequencer;
using Button = System.Windows.Controls.Button;
using CheckBox = System.Windows.Controls.CheckBox;
using ComboBox = System.Windows.Controls.ComboBox;
using Grid = System.Windows.Controls.Grid;
using TextBox = System.Windows.Controls.TextBox;
using Thumb = System.Windows.Controls.Primitives.Thumb;
using Control = System.Windows.Controls.Control;
using Border = System.Windows.Controls.Border;
using Panel = System.Windows.Controls.Panel;
using StackPanel = System.Windows.Controls.StackPanel;
using ComboBoxItem = System.Windows.Controls.ComboBoxItem;

namespace RevoBIM.UI.NumberSequencer
{
    /// <summary>
    /// The Tag in views list (port of nsq_views.py): every floor plan, section and 3D view in the project (no
    /// templates) with a Type column and two group columns whose values come from view parameters chosen in the
    /// column headings. Each column filters on what is typed under its heading and sorts when its heading is
    /// clicked. Ticked views get tags on the numbered elements they show; with nothing ticked the active view is
    /// tagged. Sheets: selecting a sheet narrows the list to its views and ticks them.
    /// </summary>
    public class TagViewsPanel
    {
        private const string Sep = "||";

        private class Col { public string Key, Head; public double Width; public bool Star; public double Min; }
        private static readonly Col[] Columns =
        {
            new Col { Key = "tick", Head = "", Width = 26, Star = false, Min = 0 },
            new Col { Key = "name", Head = "View", Width = 3, Star = true, Min = 90 },
            new Col { Key = "kind", Head = "Type", Width = 1.3, Star = true, Min = 62 },
            new Col { Key = "g1", Head = "View Group 1", Width = 2, Star = true, Min = 70 },
            new Col { Key = "g2", Head = "View Group 2", Width = 2, Star = true, Min = 70 },
        };

        private readonly SequencerWindow _w;
        public List<ViewRowData> Rows = new List<ViewRowData>();
        private List<string> _params = new List<string>();
        private HashSet<long> _only;
        private string _onlyLabel = "";
        private string _sortCol = "name";
        private bool _sortDesc;
        private readonly Dictionary<string, string> _filters = new Dictionary<string, string> { { "name", "" }, { "kind", "" }, { "g1", "" }, { "g2", "" } };
        private readonly Dictionary<string, HashSet<string>> _excluded = new Dictionary<string, HashSet<string>>
        {
            { "name", new HashSet<string>() }, { "kind", new HashSet<string>() }, { "g1", new HashSet<string>() }, { "g2", new HashSet<string>() },
        };
        private readonly Dictionary<string, CheckBox> _kindBoxes = new Dictionary<string, CheckBox>();
        private readonly Dictionary<string, Button> _funnels = new Dictionary<string, Button>();
        private readonly Dictionary<string, Popup> _popups = new Dictionary<string, Popup>();
        private readonly List<TextBox> _filterBoxes = new List<TextBox>();
        private HashSet<string> _ticked;
        private readonly string[] _saved;
        private string[] _groups = { "", "" };
        public string DocKeyValue;
        private List<ComboBox> _combos = new List<ComboBox>();
        private readonly Dictionary<string, KeyValuePair<TextBlock, string>> _sortLabels = new Dictionary<string, KeyValuePair<TextBlock, string>>();
        private bool _filling;
        public List<SheetData> Sheets = new List<SheetData>();
        private HashSet<string> _sheetSel = new HashSet<string>();
        private string _sheetAnchor;
        private readonly List<Tuple<SheetData, Border, CheckBox>> _sheetRows = new List<Tuple<SheetData, Border, CheckBox>>();
        private Tuple<HashSet<string>, string, HashSet<string>, HashSet<long>, string> _sheetUndo;
        private double? _sheetNumW;
        private double _sheetViewsW = 74.0;
        private readonly List<Grid> _sheetGrids = new List<Grid>();

        public TagViewsPanel(SequencerWindow w)
        {
            _w = w;
            _excluded["kind"] = new HashSet<string>(SplitSet(w.Settings["view_kinds_off"]));
            _ticked = new HashSet<string>(SplitSet(w.Settings["tag_views"]));
            _saved = new[] { w.Settings["view_g1"] ?? "", w.Settings["view_g2"] ?? "" };
            BuildHead();
            _w.Ctl<Button>("TagViewFindBtn").Click += (s, e) => _w.Try("find views", () => OnFind());
            _w.Ctl<Button>("TagViewAllBtn").Click += (s, e) => _w.Try("all views", () => OnAll());
            _w.Ctl<Button>("TagViewTickBtn").Click += (s, e) => _w.Try("tick shown", () => OnTickShown());
            _w.Ctl<Button>("TagViewUntickBtn").Click += (s, e) => _w.Try("untick all", () => OnUntickAll());
            _w.Ctl<Button>("TagViewClearFiltersBtn").Click += (s, e) => _w.Try("clear filters", () => OnClearFilters());
            _w.Ctl<TextBox>("TagSheetSearch").TextChanged += (s, e) => _w.Try("sheet search", () => BuildSheets());
            var tab = _w.Ctl<RadioButton>(_w.Settings["tag_tab"] == "views" ? "TagTabViews" : "TagTabSheets");
            tab.IsChecked = true;
            ShowTagTab();
            _w.Ctl<RadioButton>("TagTabSheets").Checked += (s, e) => _w.Try("tag tab", () => OnTagTab());
            _w.Ctl<RadioButton>("TagTabViews").Checked += (s, e) => _w.Try("tag tab", () => OnTagTab());
            _w.Ctl<Button>("TagSheetClearBtn").Click += (s, e) => _w.Try("clear sheets", () => OnSheetClear());
            foreach (var pair in new[] { Tuple.Create("TagKindPlan", "Floor plan"), Tuple.Create("TagKindSection", "Section"), Tuple.Create("TagKind3D", "3D") })
            {
                var box = _w.Ctl<CheckBox>(pair.Item1);
                string kind = pair.Item2;
                _kindBoxes[kind] = box;
                box.Click += (s, e) => _w.Try("kind", () => KindClick(kind, box));
            }
            SyncKinds();
        }

        private static IEnumerable<string> SplitSet(string text)
        {
            return (text ?? "").Split(new[] { Sep }, StringSplitOptions.None).Where(x => x.Length > 0);
        }

        private HashSet<string> OnlyStrings() { return _only == null ? null : new HashSet<string>(_only.Select(x => x.ToString())); }

        // ---------------------------------------------------- reading

        private class ReadResult
        {
            public List<ViewRowData> Rows; public List<string> Params; public string[] Groups; public string DocKey; public List<SheetData> Sheets;
        }

        private Func<UIApplication, object> ReadJob()
        {
            string[] groups = (string[])_saved.Clone();
            return uiapp =>
            {
                Document doc = uiapp.ActiveUIDocument.Document;
                List<View> plans = NsqRevit.TagViews(doc);
                List<string> names = NsqRevit.ViewParamNames(plans);
                string g1 = NsqCore.DefaultGroupParam(names, groups[0], 0);
                string g2 = NsqCore.DefaultGroupParam(names, groups[1], 1);
                List<string> paramNames;
                List<ViewRowData> rows = NsqRevit.ViewTable(doc, g1, g2, out paramNames);
                List<SheetData> sheets = NsqRevit.SheetTable(doc, rows.Select(r => long.Parse(r.Id)));
                return new ReadResult { Rows = rows, Params = paramNames, Groups = new[] { g1, g2 }, DocKey = NsqRevit.DocKey(doc), Sheets = sheets };
            };
        }

        /// <summary>At launch, inside the command.</summary>
        public void LoadNow(UIApplication uiapp)
        {
            try { Loaded(ReadJob()(uiapp), null); }
            catch (Exception ex) { _w.Log.Add("views read failed: " + ex); }
        }

        public void Refresh() { _w.Runner.Queue("read views", ReadJob(), Loaded); }

        private void Loaded(object resObj, string err)
        {
            var res = resObj as ReadResult;
            if (err != null || res == null) { _w.Status("Could not read the views - see debug"); return; }
            Rows = res.Rows;
            _params = res.Params;
            _groups = res.Groups;
            DocKeyValue = res.DocKey;
            _w.Log.Add("views: " + Rows.Count + " plans / sections / 3D, groups '" + _groups[0] + "' / '" + _groups[1] + "'");
            Sheets = res.Sheets ?? new List<SheetData>();
            _sheetNumW = null;
            var here = new HashSet<string>(Sheets.Select(sh => sh.Uid));
            _sheetSel = new HashSet<string>(_sheetSel.Where(here.Contains));
            FillCombos();
            if (_sheetSel.Count > 0) _only = NsqCore.SheetViews(Sheets, _sheetSel);
            Build();
            BuildSheets();
        }

        // ---------------------------------------------------- heading

        private void ColumnsFor(Grid grid)
        {
            foreach (Col c in Columns)
            {
                var cd = new ColumnDefinition();
                if (c.Star) { cd.Width = new GridLength(c.Width, GridUnitType.Star); cd.MinWidth = c.Min; }
                else cd.Width = new GridLength(c.Width);
                grid.ColumnDefinitions.Add(cd);
            }
        }

        private TextBlock SortLabel(string col, string text)
        {
            var tb = new TextBlock
            {
                Text = text, FontSize = 11, Margin = new Thickness(4, 0, 4, 0), Cursor = Cursors.Hand,
                VerticalAlignment = VerticalAlignment.Center, ToolTip = "Click to sort",
            };
            tb.SetResourceReference(TextBlock.ForegroundProperty, "Muted");
            tb.MouseLeftButtonUp += (s, e) => _w.Try("sort", () =>
            {
                _sortDesc = _sortCol == col ? !_sortDesc : false;
                _sortCol = col;
                PaintSort();
                Build();
            });
            _sortLabels[col] = new KeyValuePair<TextBlock, string>(tb, text);
            return tb;
        }

        private static Grid Cell(params Tuple<UIElement, bool>[] parts)
        {
            var cell = new Grid();
            for (int i = 0; i < parts.Length; i++)
            {
                cell.ColumnDefinitions.Add(new ColumnDefinition { Width = parts[i].Item2 ? new GridLength(1, GridUnitType.Star) : GridLength.Auto });
                if (parts[i].Item1 != null) { Grid.SetColumn(parts[i].Item1, i); cell.Children.Add(parts[i].Item1); }
            }
            return cell;
        }

        private static Tuple<UIElement, bool> P(UIElement el, bool star) { return Tuple.Create(el, star); }

        private void BuildHead()
        {
            var outer = new StackPanel();
            var top = new Grid();
            ColumnsFor(top);
            Grid cell = Cell(P(SortLabel("name", "View"), false), P(null, true), P(Funnel("name"), false));
            Grid.SetColumn(cell, 1); top.Children.Add(cell);
            cell = Cell(P(SortLabel("kind", "Type"), false), P(null, true), P(Funnel("kind"), false));
            Grid.SetColumn(cell, 2); top.Children.Add(cell);
            _combos = new List<ComboBox>();
            int n = 0;
            foreach (string col in new[] { "g1", "g2" })
            {
                int nn = n;
                var combo = new ComboBox
                {
                    Height = 24, FontSize = 11, Margin = new Thickness(0, 0, 2, 0),
                    ToolTip = "View Group " + (n + 1) + ": the view parameter shown in this column",
                };
                combo.SelectionChanged += (s, e) => _w.Try("group", () => GroupChanged(nn));
                cell = Cell(P(SortLabel(col, "Sort"), false), P(combo, true), P(Funnel(col), false));
                Grid.SetColumn(cell, 3 + n);
                top.Children.Add(cell);
                _combos.Add(combo);
                n++;
            }
            foreach (string col in new[] { "name", "kind", "g1", "g2" }) top.Children.Add(_popups[col]);   // in the heading's tree, so they find the theme
            outer.Children.Add(top);
            var filt = new Grid { Margin = new Thickness(0, 4, 0, 0) };
            ColumnsFor(filt);
            _filterBoxes.Clear();
            int[] idx = { 1, 2, 3, 4 };
            string[] cols = { "name", "kind", "g1", "g2" };
            for (int k = 0; k < 4; k++)
            {
                string col = cols[k];
                var box = new TextBox { Tag = "Filter", Height = 24, FontSize = 11, Padding = new Thickness(4, 2, 4, 2), Margin = new Thickness(0, 0, 4, 0) };
                box.TextChanged += (s, e) => _w.Try("filter", () => { _filters[col] = box.Text ?? ""; Build(); });
                Grid.SetColumn(box, idx[k]);
                filt.Children.Add(box);
                _filterBoxes.Add(box);
            }
            outer.Children.Add(filt);
            _w.Ctl<Border>("TagViewHead").Child = outer;
            PaintSort();
            PaintFunnels();
        }

        // ---------------------------------------------------- Excel-style value lists

        private Button Funnel(string col)
        {
            var btn = new Button { Width = 22, Height = 22, Content = NsqUi.Icon("filter", 12), ToolTip = "Pick the values to show in this column" };
            btn.SetResourceReference(FrameworkElement.StyleProperty, "ChromeButton");
            btn.Click += (s, e) => _w.Try("values", () => OpenValues(col));
            var pop = new Popup { PlacementTarget = btn, Placement = PlacementMode.Bottom, StaysOpen = false, AllowsTransparency = true };
            _funnels[col] = btn;
            _popups[col] = pop;
            return btn;
        }

        private void PaintFunnels()
        {
            foreach (var kv in _funnels)
            {
                if (_excluded[kv.Key].Count > 0)
                {
                    kv.Value.SetResourceReference(Control.ForegroundProperty, "Orange");
                    kv.Value.ToolTip = _excluded[kv.Key].Count + " value(s) hidden - click to change";
                }
                else
                {
                    kv.Value.ClearValue(Control.ForegroundProperty);
                    kv.Value.ToolTip = "Pick the values to show in this column";
                }
            }
        }

        private void OpenValues(string col)
        {
            Popup pop = _popups[col];
            var card = new Border
            {
                BorderThickness = new Thickness(1), CornerRadius = new CornerRadius(4), Padding = new Thickness(8),
                MinWidth = 230, Margin = new Thickness(0, 2, 0, 0),
            };
            card.SetResourceReference(Border.BackgroundProperty, "Card");
            card.SetResourceReference(Border.BorderBrushProperty, "Blue");
            var sp = new StackPanel();
            var search = new TextBox { Tag = "Search values", Height = 26, FontSize = 11, Margin = new Thickness(0, 0, 0, 6) };
            sp.Children.Add(search);
            var bar = new WrapPanel { Margin = new Thickness(0, 0, 0, 6) };
            var allBtn = new Button(); allBtn.SetResourceReference(FrameworkElement.StyleProperty, "ChipButton");
            NsqUi.SetButton(allBtn, "tick", "Select all");
            var noneBtn = new Button(); noneBtn.SetResourceReference(FrameworkElement.StyleProperty, "ChipButton");
            NsqUi.SetButton(noneBtn, "untick", "Clear all");
            bar.Children.Add(allBtn); bar.Children.Add(noneBtn);
            sp.Children.Add(bar);
            var host = new StackPanel();
            var sv = new ScrollViewer { MaxHeight = 280, VerticalScrollBarVisibility = ScrollBarVisibility.Auto, Content = host };
            sp.Children.Add(sv);
            var note = new TextBlock { FontSize = 11, Margin = new Thickness(0, 6, 0, 0), Text = "Everything ticked = no filter" };
            note.SetResourceReference(TextBlock.ForegroundProperty, "Muted");
            sp.Children.Add(note);
            card.Child = sp;
            var shown = new List<string>();

            Action<string> fill = null;
            fill = text =>
            {
                host.Children.Clear();
                shown.Clear();
                var values = NsqCore.ColumnValues(Rows, col, _filters, _excluded, OnlyStrings());
                foreach (var kv in values)
                {
                    string val = kv.Key;
                    string label = val.Length > 0 ? val : "(blank)";
                    if (!NsqCore.Matches(label, text)) continue;
                    shown.Add(val);
                    var cb = new CheckBox { Content = label + "  (" + kv.Value + ")", IsChecked = !_excluded[col].Contains(val), Margin = new Thickness(0, 2, 0, 2) };
                    cb.Click += (s, e) => _w.Try("tick value", () =>
                    {
                        if (cb.IsChecked == true) _excluded[col].Remove(val); else _excluded[col].Add(val);
                        ValuesChanged();
                    });
                    host.Children.Add(cb);
                }
                if (shown.Count == 0)
                {
                    var tb = new TextBlock { Text = "No values" };
                    tb.SetResourceReference(TextBlock.ForegroundProperty, "Muted");
                    host.Children.Add(tb);
                }
            };
            Func<bool, RoutedEventHandler> setAll = on => (s, e) => _w.Try("set all", () =>
            {
                _excluded[col] = NsqCore.TickValues(_excluded[col], shown.ToList(), on);
                ValuesChanged();
                fill(search.Text ?? "");
            });
            search.TextChanged += (s, e) => _w.Try("search values", () => fill(search.Text ?? ""));
            allBtn.Click += setAll(true);
            noneBtn.Click += setAll(false);
            fill("");
            pop.Child = card;
            pop.IsOpen = true;
            try { search.Focus(); } catch (Exception) { }
        }

        private void ValuesChanged()
        {
            PaintFunnels();
            SyncKinds();
            Build();
        }

        // ---------------------------------------------------- view types

        private void SyncKinds()
        {
            foreach (var kv in _kindBoxes) kv.Value.IsChecked = !_excluded["kind"].Contains(kv.Key);
            _w.Settings["view_kinds_off"] = string.Join(Sep, _excluded["kind"].OrderBy(x => x, StringComparer.Ordinal));
        }

        private void KindClick(string kind, CheckBox box)
        {
            if (box.IsChecked == true) _excluded["kind"].Remove(kind); else _excluded["kind"].Add(kind);
            _w.Save();
            ValuesChanged();
        }

        private void OnClearFilters()
        {
            foreach (string c in _excluded.Keys.ToList()) _excluded[c] = new HashSet<string>();
            foreach (TextBox b in _filterBoxes) b.Text = "";
            ValuesChanged();
        }

        private void FillCombos()
        {
            _filling = true;
            try
            {
                for (int n = 0; n < _combos.Count; n++)
                {
                    ComboBox combo = _combos[n];
                    combo.Items.Clear();
                    var none = new ComboBoxItem { Content = "(none)", Tag = "" };
                    combo.Items.Add(none);
                    ComboBoxItem pick = none;
                    foreach (string name in _params)
                    {
                        var item = new ComboBoxItem { Content = name, Tag = name };
                        combo.Items.Add(item);
                        if (name == _groups[n]) pick = item;
                    }
                    combo.SelectedItem = pick;
                }
            }
            finally { _filling = false; }
        }

        private void GroupChanged(int n)
        {
            if (_filling) return;
            var item = _combos[n].SelectedItem as ComboBoxItem;
            string value = item != null && item.Tag != null ? item.Tag.ToString() : "";
            if (value == _groups[n]) return;
            _saved[n] = value.Length > 0 ? value : NsqCore.NoneMark;
            _w.Settings["view_g" + (n + 1)] = _saved[n];
            _w.Save();
            Refresh();
        }

        private void PaintSort()
        {
            foreach (var kv in _sortLabels)
            {
                TextBlock tb = kv.Value.Key;
                if (kv.Key == _sortCol)
                {
                    tb.Text = kv.Value.Value + (_sortDesc ? " v" : " ^");
                    tb.SetResourceReference(TextBlock.ForegroundProperty, "Orange");
                }
                else
                {
                    tb.Text = kv.Value.Value;
                    tb.SetResourceReference(TextBlock.ForegroundProperty, "Muted");
                }
            }
        }

        // ---------------------------------------------------- rows

        public List<ViewRowData> Shown()
        {
            return NsqCore.ViewRows(Rows, _filters, _sortCol, _sortDesc, OnlyStrings(), _excluded);
        }

        public void Build()
        {
            var host = _w.Ctl<StackPanel>("TagViewRows");
            host.Children.Clear();
            List<ViewRowData> rows = Shown();
            if (Rows.Count == 0)
            {
                var tb = new TextBlock { Text = "No floor plans, sections or 3D views in the project", Margin = new Thickness(6) };
                tb.SetResourceReference(TextBlock.ForegroundProperty, "Muted");
                host.Children.Add(tb);
            }
            foreach (ViewRowData r in rows)
            {
                var grid = new Grid { Margin = new Thickness(0, 1, 0, 1), Background = NsqUi.Brush("#00000000"), Cursor = Cursors.Hand };
                ColumnsFor(grid);
                var cb = new CheckBox { IsChecked = _ticked.Contains(r.Uid), HorizontalAlignment = HorizontalAlignment.Center };
                ViewRowData row = r;
                cb.Click += (s, e) => _w.Try("tick view", () => Tick(row, cb));
                Grid.SetColumn(cb, 0);
                grid.Children.Add(cb);
                int[] idx = { 1, 2, 3, 4 };
                string[] keys = { "name", "kind", "g1", "g2" };
                for (int k = 0; k < 4; k++)
                {
                    string key = keys[k];
                    string text = key == "kind" ? (r.Get("kind_text").Length > 0 ? r.Get("kind_text") : r.Get(key)) : r.Get(key);
                    var tb = new TextBlock
                    {
                        Text = text,
                        ToolTip = r.Get(key) + (key == "name" && r.Get("level").Length > 0 ? "  (" + r.Get("level") + ")" : ""),
                        Margin = new Thickness(4, 2, 6, 2),
                        TextTrimming = TextTrimming.CharacterEllipsis,
                        VerticalAlignment = VerticalAlignment.Center,
                    };
                    tb.SetResourceReference(TextBlock.ForegroundProperty, key == "name" ? "Text" : "Muted");
                    Grid.SetColumn(tb, idx[k]);
                    grid.Children.Add(tb);
                }
                grid.MouseLeftButtonUp += (s, e) => _w.Try("row click", () => RowClick(row, cb, e));
                host.Children.Add(grid);
            }
            Count(rows.Count);
        }

        private void Count(int shown)
        {
            int ticked = TickedCount();
            string text = ticked + " ticked  |  " + shown + " of " + Rows.Count + " views";
            if (_only != null) text += "  |  " + _onlyLabel;
            int hidden = _excluded.Values.Sum(v => v.Count);
            if (hidden > 0 || _filters.Values.Any(t => t.Trim().Length > 0)) text += "  |  filtered";
            _w.Ctl<TextBlock>("TagViewCount").Text = text;
            PaintSheets();
            PaintTabs();
            _w.RefreshTagNote(_w.PlanOnly());
        }

        private void Tick(ViewRowData r, CheckBox cb)
        {
            if (cb.IsChecked == true) _ticked.Add(r.Uid); else _ticked.Remove(r.Uid);
            SaveTicks();
            Count(Shown().Count);
        }

        private void RowClick(ViewRowData r, CheckBox cb, MouseButtonEventArgs e)
        {
            if (e.ClickCount == 2)
            {
                // the first click of the double-click toggled the tick: put it back
                cb.IsChecked = !(cb.IsChecked == true);
                Tick(r, cb);
                OpenView(r);
                return;
            }
            if (e.OriginalSource is CheckBox) return;
            cb.IsChecked = !(cb.IsChecked == true);
            Tick(r, cb);
        }

        private void OpenView(ViewRowData r)
        {
            _w.Runner.Queue("open view", uiapp =>
            {
                Element view = uiapp.ActiveUIDocument.Document.GetElement(r.Eid);
                if (view is View) uiapp.ActiveUIDocument.RequestViewChange((View)view);
                return true;
            }, (res, err) => _w.Status(err != null ? "Could not open " + r.Name + " - see debug" : "Opened " + r.Name));
        }

        private void SaveTicks()
        {
            _w.Settings["tag_views"] = string.Join(Sep, _ticked.OrderBy(x => x, StringComparer.Ordinal));
            _w.Save();
        }

        /// <summary>ElementIds of the ticked views, for the tag step.</summary>
        public List<ElementId> TickedIds() { return Rows.Where(r => _ticked.Contains(r.Uid)).Select(r => r.Eid).ToList(); }

        public int TickedCount() { return Rows.Count(r => _ticked.Contains(r.Uid)); }

        // ---------------------------------------------------- buttons

        private void OnTickShown()
        {
            foreach (ViewRowData r in Shown()) _ticked.Add(r.Uid);
            SaveTicks();
            Build();
        }

        private void OnUntickAll()
        {
            var here = new HashSet<string>(Rows.Select(r => r.Uid));
            _ticked = new HashSet<string>(_ticked.Where(u => !here.Contains(u)));   // other projects keep theirs
            SaveTicks();
            Build();
        }

        private void OnAll()
        {
            _only = null;
            _onlyLabel = "";
            _sheetSel = new HashSet<string>();
            Refresh();
        }

        /// <summary>Narrow the list to the views that show the selected system(s).</summary>
        private void OnFind()
        {
            string label;
            List<ElementId> keys = _w.FindKeys(out label);
            if (keys.Count == 0) { _w.Status("Select a system first"); return; }
            var viewIds = Rows.Select(r => r.Eid).ToList();
            _w.QueueBusy("find views", uiapp => NsqRevit.ViewsShowing(uiapp.ActiveUIDocument.Document, viewIds, keys), (resObj, err) =>
            {
                var found = resObj as HashSet<long>;
                if (err != null || found == null) { _w.Status("Could not search the views - see debug"); return; }
                _only = found;
                _onlyLabel = "showing " + label;
                _sheetSel = new HashSet<string>();   // the newest narrowing wins
                Build();
                BuildSheets();
                _w.Status(found.Count + " view(s) show " + label);
            }, "Looking for the views that show " + label);
        }

        // ---------------------------------------------------- the Sheets | Views tabs

        private bool ShowTagTab()
        {
            bool views = _w.Ctl<RadioButton>("TagTabViews").IsChecked == true;
            NsqUi.Show(_w.Ctl<UIElement>("TagViewsPanel"), views);
            NsqUi.Show(_w.Ctl<UIElement>("TagSheetsPanel"), !views);
            return views;
        }

        private void OnTagTab()
        {
            bool views = ShowTagTab();
            _w.Settings["tag_tab"] = views ? "views" : "sheets";
            _w.Save();
        }

        private void PaintTabs()
        {
            try
            {
                int n = TickedCount();
                NsqUi.SetButton(_w.Ctl<ContentControl>("TagTabViews"), "show", n > 0 ? "Views (" + n + " ticked)" : "Views");
                int k = _sheetSel.Count;
                NsqUi.SetButton(_w.Ctl<ContentControl>("TagTabSheets"), "sheet", k > 0 ? "Sheets (" + k + " selected)" : "Sheets");
            }
            catch (Exception) { }
        }

        /// <summary>Id values of the ticked views of this project.</summary>
        public HashSet<long> TickedIdsHere()
        {
            return new HashSet<long>(Rows.Where(r => _ticked.Contains(r.Uid)).Select(r => long.Parse(r.Id)));
        }

        // ---------------------------------------------------- sheet columns

        private double FitNumber(IEnumerable<SheetData> sheets)
        {
            double widest = 40.0;
            var tb = new TextBlock { FontWeight = FontWeights.SemiBold };
            foreach (SheetData sh in sheets)
            {
                tb.Text = sh.Number ?? "";
                tb.Measure(new Size(double.PositiveInfinity, double.PositiveInfinity));
                widest = Math.Max(widest, tb.DesiredSize.Width);
            }
            return widest + 14.0;
        }

        private void SheetColumns(Grid grid)
        {
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(26) });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(_sheetNumW ?? 96.0) });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star), MinWidth = 60 });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(_sheetViewsW) });
            _sheetGrids.Add(grid);
        }

        private void ResizeSheetColumns()
        {
            foreach (Grid g in _sheetGrids)
            {
                try
                {
                    g.ColumnDefinitions[1].Width = new GridLength(_sheetNumW ?? 96.0);
                    g.ColumnDefinitions[3].Width = new GridLength(_sheetViewsW);
                }
                catch (Exception) { }
            }
        }

        private Thumb Edge(bool num)
        {
            var th = new Thumb { Width = 7, Cursor = Cursors.SizeWE, ToolTip = "Drag to size the column" };
            th.SetResourceReference(FrameworkElement.StyleProperty, "Grip");
            th.DragDelta += (s, e) => _w.Try("size column", () =>
            {
                if (num) _sheetNumW = Math.Max(36.0, (_sheetNumW ?? 96.0) + e.HorizontalChange);
                else _sheetViewsW = Math.Max(44.0, _sheetViewsW - e.HorizontalChange);
                ResizeSheetColumns();
            });
            return th;
        }

        private void BuildSheetHead()
        {
            var grid = new Grid();
            SheetColumns(grid);
            string[] heads = { "Number", "Name", "Views" };
            for (int i = 0; i < 3; i++)
            {
                var tb = new TextBlock
                {
                    Text = heads[i], FontSize = 11, FontWeight = FontWeights.SemiBold, Margin = new Thickness(4, 0, 6, 0),
                    VerticalAlignment = VerticalAlignment.Center,
                };
                tb.SetResourceReference(TextBlock.ForegroundProperty, "Muted");
                Grid.SetColumn(tb, i + 1);
                grid.Children.Add(tb);
            }
            Thumb num = Edge(true);
            num.HorizontalAlignment = HorizontalAlignment.Right;
            Grid.SetColumn(num, 1);
            grid.Children.Add(num);
            Thumb views = Edge(false);
            views.HorizontalAlignment = HorizontalAlignment.Left;
            Grid.SetColumn(views, 3);
            grid.Children.Add(views);
            _w.Ctl<Border>("TagSheetHead").Child = grid;
        }

        public void BuildSheets()
        {
            var host = _w.Ctl<StackPanel>("TagSheetRows");
            host.Children.Clear();
            _sheetRows.Clear();
            _sheetGrids.Clear();
            if (_sheetNumW == null && Sheets.Count > 0) _sheetNumW = FitNumber(Sheets);
            if (_sheetNumW == null) _sheetNumW = 96.0;
            BuildSheetHead();
            List<SheetData> shown = NsqCore.SheetRows(Sheets, _w.Ctl<TextBox>("TagSheetSearch").Text);
            if (shown.Count == 0)
            {
                var tb = new TextBlock { Text = Sheets.Count > 0 ? "No sheets match" : "No sheets in the project", Margin = new Thickness(6) };
                tb.SetResourceReference(TextBlock.ForegroundProperty, "Muted");
                host.Children.Add(tb);
                return;
            }
            for (int idx = 0; idx < shown.Count; idx++)
            {
                SheetData sh = shown[idx];
                int myIdx = idx;
                var grid = new Grid();
                SheetColumns(grid);
                var row = new Border
                {
                    CornerRadius = new CornerRadius(3), Padding = new Thickness(0, 1, 0, 1), Margin = new Thickness(0, 0, 0, 1),
                    Cursor = Cursors.Hand, Child = grid,
                };
                var cb = new CheckBox
                {
                    HorizontalAlignment = HorizontalAlignment.Center, VerticalAlignment = VerticalAlignment.Center,
                    ToolTip = "Tick or untick every listed view on this sheet",
                };
                cb.Click += (s, e) => _w.Try("sheet tick", () => SheetTick(sh));
                Grid.SetColumn(cb, 0);
                grid.Children.Add(cb);
                int listed = sh.Views.Count;
                var cols = new[]
                {
                    Tuple.Create(1, sh.Number, "Text"), Tuple.Create(2, sh.Name, "Text"),
                    Tuple.Create(3, listed + " view" + (listed == 1 ? "" : "s"), "Muted"),
                };
                foreach (var c in cols)
                {
                    var tb = new TextBlock
                    {
                        Text = c.Item2, Margin = new Thickness(4, 2, 6, 2), TextTrimming = TextTrimming.CharacterEllipsis,
                        VerticalAlignment = VerticalAlignment.Center,
                    };
                    tb.SetResourceReference(TextBlock.ForegroundProperty, c.Item3);
                    if (c.Item1 == 1) tb.FontWeight = FontWeights.SemiBold;
                    Grid.SetColumn(tb, c.Item1);
                    grid.Children.Add(tb);
                }
                row.ToolTip = sh.Number + " - " + sh.Name + ": " + listed + " of its " + sh.Placed + " views can take tags here.  Click: find and tick them.  " +
                              "Ctrl / Shift + click: several sheets.  Double-click: open the sheet.";
                row.MouseLeftButtonUp += (s, e) => _w.Try("sheet click", () => SheetClick(myIdx, sh, e));
                host.Children.Add(row);
                _sheetRows.Add(Tuple.Create(sh, row, cb));
            }
            PaintSheets();
        }

        private void PaintSheets()
        {
            PaintTabs();
            HashSet<long> ticked = TickedIdsHere();
            foreach (var t in _sheetRows)
            {
                if (_sheetSel.Contains(t.Item1.Uid)) t.Item2.SetResourceReference(Border.BackgroundProperty, "Sel");
                else t.Item2.Background = NsqUi.Brush("#00000000");
                t.Item3.IsChecked = NsqCore.SheetState(t.Item1, ticked);
                t.Item3.IsEnabled = t.Item1.Views.Count > 0;
            }
        }

        private void SheetClick(int idx, SheetData sh, MouseButtonEventArgs e)
        {
            if (e.OriginalSource is CheckBox) return;
            if (e.ClickCount == 2)
            {
                // the first click of the double-click selected and ticked: put it back
                if (_sheetUndo != null)
                {
                    _sheetSel = _sheetUndo.Item1; _sheetAnchor = _sheetUndo.Item2; _ticked = _sheetUndo.Item3; _only = _sheetUndo.Item4; _onlyLabel = _sheetUndo.Item5;
                    _sheetUndo = null;
                    SaveTicks();
                    Build();
                }
                OpenSheet(sh);
                return;
            }
            _sheetUndo = Tuple.Create(new HashSet<string>(_sheetSel), _sheetAnchor, new HashSet<string>(_ticked), _only, _onlyLabel);
            ModifierKeys m = Keyboard.Modifiers;
            bool ctrl = (m & ModifierKeys.Control) == ModifierKeys.Control;
            bool shift = (m & ModifierKeys.Shift) == ModifierKeys.Shift;
            List<SheetData> shownSheets = _sheetRows.Select(r => r.Item1).ToList();
            var now = new HashSet<int>();
            for (int i = 0; i < shownSheets.Count; i++) if (_sheetSel.Contains(shownSheets[i].Uid)) now.Add(i);
            int? anchor = null;
            for (int i = 0; i < shownSheets.Count; i++) if (shownSheets[i].Uid == _sheetAnchor) anchor = i;
            HashSet<int> nw;
            if (ctrl && now.Contains(idx) && now.Count == 1) { nw = new HashSet<int>(); anchor = null; }
            else { int? na; nw = NsqCore.ClickSelection(now, anchor, idx, ctrl, shift, out na); anchor = na; }
            var shownUids = new HashSet<string>(shownSheets.Select(x => x.Uid));
            var hidden = new HashSet<string>(_sheetSel.Where(u => !shownUids.Contains(u)));   // selections hidden by the search stay selected
            hidden.UnionWith(nw.Select(i => shownSheets[i].Uid));
            _sheetSel = hidden;
            _sheetAnchor = anchor != null ? shownSheets[anchor.Value].Uid : null;
            ApplySheets();
        }

        /// <summary>The views on the selected sheets: the list narrows to them and they are ticked for tagging.</summary>
        private void ApplySheets()
        {
            if (_sheetSel.Count == 0)
            {
                _only = null;
                _onlyLabel = "";
                Build();
                PaintSheets();
                _w.Status("No sheet selected - every view shown");
                return;
            }
            HashSet<long> ids = NsqCore.SheetViews(Sheets, _sheetSel);
            int added = 0;
            foreach (ViewRowData r in Rows)
                if (ids.Contains(long.Parse(r.Id)) && !_ticked.Contains(r.Uid)) { _ticked.Add(r.Uid); added++; }
            var chosen = Sheets.Where(sh => _sheetSel.Contains(sh.Uid)).ToList();
            string label = chosen.Count == 1 ? chosen[0].Number : chosen.Count + " sheets";
            _only = ids;
            _onlyLabel = "on " + label;
            SaveTicks();
            Build();
            PaintSheets();
            _w.Status(ids.Count + " view(s) on " + label + " to tag" + (added > 0 ? " - " + added + " newly ticked" : ", all ticked already"));
        }

        private void SheetTick(SheetData sh)
        {
            HashSet<long> ticked = TickedIdsHere();
            bool on = NsqCore.SheetState(sh, ticked) != true;   // partly or not ticked -> tick all
            var set = new HashSet<long>(sh.Views);
            var uids = new HashSet<string>(Rows.Where(r => set.Contains(long.Parse(r.Id))).Select(r => r.Uid));
            if (on) _ticked.UnionWith(uids); else _ticked.ExceptWith(uids);
            SaveTicks();
            Build();
            _w.Status(sh.Number + ": " + uids.Count + " view(s) " + (on ? "ticked" : "unticked"));
        }

        private void OpenSheet(SheetData sh)
        {
            _w.Runner.Queue("open sheet", uiapp =>
            {
                View view = uiapp.ActiveUIDocument.Document.GetElement((ElementId)sh.Eid) as View;
                if (view != null) uiapp.ActiveUIDocument.RequestViewChange(view);
                return true;
            }, (res, err) => _w.Status(err != null ? "Could not open " + sh.Number + " - see debug" : "Opened sheet " + sh.Number));
        }

        private void OnSheetClear()
        {
            _sheetSel = new HashSet<string>();
            _sheetAnchor = null;
            _w.Ctl<TextBox>("TagSheetSearch").Text = "";
            ApplySheets();
        }
    }
}
