// Excel for Revit: the main window, first part (port of efr_core.py lines 4979-5795):
// the constructor, duplicate tools, column headers and their menus, sort marks and the filter debounce.
using System;
using System.Collections.Generic;
using System.Collections.Specialized;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Threading;
using ExternalEvent = Autodesk.Revit.UI.ExternalEvent;
using RevoBIM.Tools.ExcelForRevit;
using WGrid = System.Windows.Controls.Grid;
using UIDocument = Autodesk.Revit.UI.UIDocument;
using Document = Autodesk.Revit.DB.Document;
using FieldInfo = RevoBIM.Tools.ExcelForRevit.FieldInfo;

namespace RevoBIM.UI.ExcelForRevit
{
    public partial class ExcelForRevitWindow
    {
        public ExcelForRevitWindow(UIDocument uidoc, Document doc, ScheduleModel model)
        {
            // not ported: _proved / _shown liveness proof (the engine teardown it guarded against cannot happen here)
            Uidoc = uidoc;
            Doc = doc;
            Model = model;

            // Modeless keeps Revit usable; the write work goes through an ExternalEvent (WorkHandler).
            Modeless = Efr.GetBool(Efr.LoadSettings(), "modeless", true);
            if (Modeless)
            {
                try
                {
                    Handler = new WorkHandler();
                    Event = ExternalEvent.Create(Handler);
                }
                catch (Exception)
                {
                    Handler = null;
                    Event = null;
                    Modeless = false;
                }
            }

            Window = Efr.LoadXamlResource<Window>("ExcelForRevit.xaml");
            Window w = Window;

            // the named lookup every wiring helper takes (Python's local f)
            Func<string, object> f = name => w.FindName(name);

            Dg = (DataGrid)f("DataGridMain");
            GridHost = (WGrid)f("GridHost");
            Handle = (Border)f("FillHandle");
            Preview = (Border)f("FillPreview");
            Status = (TextBlock)f("StatusText");
            Pending = (TextBlock)f("PendingText");
            BtnRevertSel = (Button)f("BtnRevertSelected");
            BtnApply = (Button)f("BtnApply");

            ((TextBlock)f("VersionText")).Text = "v" + Efr.Version;
            ((TextBlock)f("ScheduleTitle")).Text = Efr.ElemName(model.Sched);
            ((TextBlock)f("ScheduleSub")).Text = string.Join("  ", model.Notes);

            try
            {
                ((Image)f("IconImage")).Source = Efr.LoadImageResource(Efr.IconResource);
            }
            catch (Exception) { }

            // toolbar: (button name, icon, label, tooltip, handler)
            ToolDefs = new List<(string Name, string Icon, string Label, string Tip, RoutedEventHandler Handler)>
            {
                ("BtnFillDown", "filldown", "Fill Down", "Fill the top cell of the selection down (Ctrl+D)", new RoutedEventHandler((s, e) => OnFillDown(s, e))),
                ("BtnFormula", "formula", "Formula", "Build values from other columns, e.g. =CONCAT(A,\" - \",B)  (Ctrl+Shift+F)", new RoutedEventHandler((s, e) => OnFormula(s, e))),
                ("BtnSequence", "sequence", "Sequence", "Number the selection, keeping the padding of the start number (Ctrl+Shift+N)", new RoutedEventHandler((s, e) => OnSequence(s, e))),
                ("BtnAffix", "affix", "Prefix", "Wrap text around what the selected cells already hold (Ctrl+Shift+P)", new RoutedEventHandler((s, e) => OnAffix(s, e))),
                ("BtnFindView", "findview", "Find in View", "Select the elements on the picked rows in Revit and show them in a view", new RoutedEventHandler((s, e) => OnFindInView(s, e))),
                ("BtnSetLevel", "setlevel", "Set Level", "Put the selected elements on another level without moving them", new RoutedEventHandler((s, e) => OnSetLevel(s, e))),
                ("BtnHighlight", "highlight", "Highlight", "Colour cells, rows or columns \u2014 the colour follows the data through filters (Ctrl+Shift+H)", new RoutedEventHandler((s, e) => OnHighlight(s, e))),
                ("BtnFind", "find", "Find and Replace", "Find and replace across the schedule (Ctrl+H)", new RoutedEventHandler((s, e) => OnFind(s, e))),
                ("BtnRevertAll", "revert", "Revert All", "Drop every staged edit", new RoutedEventHandler((s, e) => OnRevertAll(s, e))),
                ("BtnGroup", "group", "Group", "Break the table with a coloured heading each time the sorted column changes value", new RoutedEventHandler((s, e) => OnGroupToggle(s, e))),
                ("BtnExpand", "expand", "Collapse All", "Open or close every group at once", new RoutedEventHandler((s, e) => OnExpandAll(s, e))),
                ("BtnReload", "reload", "Reload", "Re-read the schedule from the model", new RoutedEventHandler((s, e) => OnReload(s, e))),
            };
            ToolButtons = new Dictionary<string, Button>();
            foreach (var def in ToolDefs)
            {
                try
                {
                    Button btn = (Button)f(def.Name);
                    EfrUi.BuildToolButton(btn, def.Icon, def.Label, def.Tip);
                    btn.Click += def.Handler;
                    ToolButtons[def.Name] = btn;
                }
                catch (Exception) { }
            }

            var clicks = new List<(string Name, RoutedEventHandler Handler)>
            {
                ("CloseBtn", new RoutedEventHandler((s, e) => OnCloseClick(s, e))),
                ("BtnClose", new RoutedEventHandler((s, e) => OnCloseClick(s, e))),
                ("MaxBtn", new RoutedEventHandler((s, e) => OnMaximise(s, e))),
                ("BtnTheme", new RoutedEventHandler((s, e) => OnTheme(s, e))),
                ("BtnApply", new RoutedEventHandler((s, e) => OnApply(s, e))),
                ("BtnExcel", new RoutedEventHandler((s, e) => OnExcel(s, e))),
                ("BtnRevertSelected", new RoutedEventHandler((s, e) => OnRevertSelected(s, e))),
            };
            foreach (var c in clicks)
            {
                try
                {
                    ((ButtonBase)f(c.Name)).Click += c.Handler;
                }
                catch (Exception) { }
            }

            WireFormulaBar(f);
            WireGrips(f);
            BtnTheme = (Button)f("BtnTheme");
            BtnIsolate = (Button)f("BtnIsolate");
            try
            {
                EfrUi.BuildWideButton(BtnIsolate, "isolate", "Isolate Selected",
                    "Open the default 3D view and temporarily isolate " +
                    "the selected elements, keeping the section box");
                BtnIsolate.Click += (s, e) => OnIsolateSelected(s, e);
            }
            catch (Exception) { }
            BtnExcel = (Button)f("BtnExcel");
            try
            {
                EfrUi.BuildWideButton(BtnExcel, "excel", "Excel",
                    "Export to Excel, or import an edited workbook back");
            }
            catch (Exception) { }
            GroupBar = (Border)f("GroupBar");
            ToolStrip = (StackPanel)f("ToolStrip");
            ToolGrid = (WGrid)f("ToolGrid");
            Button b;
            BtnGroup = ToolButtons.TryGetValue("BtnGroup", out b) ? b : null;
            ShowThemeState();
            BtnExpand = ToolButtons.TryGetValue("BtnExpand", out b) ? b : null;
            LegendHost = (WrapPanel)f("LegendHost");
            BuildLegend();
            try
            {
                ((UIElement)f("HeaderBar")).MouseLeftButtonDown += (s, e) => OnHeaderClick(s, e);
            }
            catch (Exception) { }
            MaxBtn = (Button)f("MaxBtn");
            BuildDrawer(f);

            BuildGrid();

            try
            {
                if (Efr.GetString(Efr.LoadSettings(), "theme") == "light")
                    SetThemeTo("light");
            }
            catch (Exception) { }

            try
            {
                Dg.BeginningEdit += (s, e) => OnBeginEdit(s, e);
                Dg.CellEditEnding += (s, e) => OnCellEditEnding(s, e);
                Dg.SelectedCellsChanged += (s, e) => OnSelectionChanged(s, e);
                Dg.LoadingRow += (s, e) => OnLoadingRow(s, e);
                Dg.UnloadingRow += (s, e) => OnUnloadingRow(s, e);
                Dg.LayoutUpdated += (s, e) => OnLayoutUpdated(s, e);
            }
            catch (Exception) { }
            // each in its own try: these only keep the fill handle exact after a
            // column moves, and neither may take the paint hook above down with it
            try
            {
                Dg.ColumnReordered += (s, e) => OnColumnsChanged(s, e);
            }
            catch (Exception) { }
            try
            {
                ((INotifyCollectionChanged)Dg.Columns).CollectionChanged += (s, e) => OnColumnsChanged(s, e);
            }
            catch (Exception) { }
            try
            {
                Dg.AddHandler(ScrollViewer.ScrollChangedEvent,
                    new ScrollChangedEventHandler((s, e) => OnScroll(s, e)));
            }
            catch (Exception) { }
            try
            {
                Handle.MouseLeftButtonDown += (s, e) => OnHandleDown(s, e);
                Handle.MouseMove += (s, e) => OnHandleMove(s, e);
                Handle.MouseLeftButtonUp += (s, e) => OnHandleUp(s, e);
            }
            catch (Exception) { }

            BuildContextMenu();
            try
            {
                Dg.ContextMenuOpening += (s, e) => OnGridMenuOpening(s, e);
            }
            catch (Exception) { }
            try
            {
                Dg.Sorting += (s, e) => OnSorting(s, e);
                Dg.CurrentCellChanged += (s, e) => OnCurrentCellChanged(s, e);
                Dg.PreviewMouseRightButtonDown += (s, e) => OnRightClick(s, e);
                Dg.PreviewMouseRightButtonUp += (s, e) => OnHeaderRightUp(s, e);
                Dg.PreviewMouseLeftButtonDown += (s, e) => OnGridMouseDown(s, e);
                Dg.MouseMove += (s, e) => OnGridMouseMove(s, e);
                Dg.PreviewMouseLeftButtonUp += (s, e) => OnGridMouseUp(s, e);
                Dg.LostMouseCapture += (s, e) => OnGridMouseUp(s, e as MouseButtonEventArgs);  // the handler ignores args
            }
            catch (Exception) { }

            AttachEgg(f);

            w.SizeChanged += (s, e) => OnSizeChanged(s, e);
            w.ContentRendered += (s, e) => OnFirstRender(s, e);
            w.PreviewKeyDown += (s, e) => OnKey(s, e);
            // not ported: w.PreviewMouseMove += on_any_mouse (liveness proof)
            w.Closing += (s, e) => OnClosing(s, e);
            UpdatePending();
            SetStatus(string.Format("{0} rows loaded. Edit cells, then press APPLY.", model.Rows.Count));
        }

        // -- duplicates ---------------------------------------------------------

        /// <summary>Every value in a column and how many rows carry it.</summary>
        public Dictionary<string, int> ColumnCounts(FieldInfo fi)
        {
            var counts = new Dictionary<string, int>();
            foreach (RowInfo row in Model.Rows)
            {
                string value = Model.CurrentText(row, fi.Index);
                int n;
                counts.TryGetValue(value, out n);
                counts[value] = n + 1;
            }
            return counts;
        }

        /// <summary>
        /// Values that appear on more than one row.
        /// Blanks are left out: an empty cell repeated forty times is not the kind
        /// of duplicate anyone is hunting for, and including them would drown the real ones.
        /// </summary>
        public List<string> DuplicateValues(FieldInfo fi)
        {
            var values = new List<string>();
            foreach (RowInfo row in Model.Rows)
                values.Add(Model.CurrentText(row, fi.Index));
            return Efr.FindDuplicates(values);
        }

        /// <summary>A colour per duplicate set, so which rows clash with which is
        /// readable without comparing values by eye.</summary>
        public int HighlightDuplicates(FieldInfo fi)
        {
            List<string> dups = DuplicateValues(fi);
            // drop any previous marking on this column before re-marking it
            foreach (var key in CellHl.Keys.ToList())
            {
                if (key.FieldIndex == fi.Index)
                    CellHl.Remove(key);
            }
            if (dups.Count == 0)
            {
                RepaintSoon();
                SetStatus(string.Format("No duplicates in {0}.", fi.Name));
                return 0;
            }
            var colourOf = new Dictionary<string, string>();
            for (int n = 0; n < dups.Count; n++)
                colourOf[dups[n]] = Efr.HIGHLIGHT_COLOURS[n % Efr.HIGHLIGHT_COLOURS.Length];
            int rows = 0;
            foreach (RowInfo row in Model.Rows)
            {
                string value = Model.CurrentText(row, fi.Index);
                string colour;
                if (colourOf.TryGetValue(value, out colour))
                {
                    CellHl[(row.Ridx, fi.Index)] = (colour, "both");
                    rows++;
                }
            }
            RepaintSoon();
            string note = "";
            if (dups.Count > Efr.HIGHLIGHT_COLOURS.Length)
                note = string.Format("  Colours repeat after {0} sets.", Efr.HIGHLIGHT_COLOURS.Length);
            SetStatus(string.Format("{0} duplicate value{1} in {2}, across {3} rows.{4}",
                dups.Count, dups.Count == 1 ? "" : "s", fi.Name, rows, note));
            return dups.Count;
        }

        /// <summary>
        /// Show only the rows that clash, using the column's own tick filter.
        /// Only this column is touched: any other column's filter, and the sort
        /// and the grouping, are left exactly as they were.
        /// </summary>
        public bool IsolateDuplicates(FieldInfo fi, bool on)
        {
            if (on)
            {
                List<string> dups = DuplicateValues(fi);
                if (dups.Count == 0)
                {
                    SetStatus(string.Format("No duplicates in {0} to isolate.", fi.Name));
                    return false;
                }
                if (!DupIsolated.Contains(fi.Index))
                {
                    // a tick filter the user had set here comes back afterwards
                    HashSet<string> prior;
                    ColPicks.TryGetValue(fi.Index, out prior);
                    DupSavedPicks[fi.Index] = prior;
                }
                ColPicks[fi.Index] = new HashSet<string>(dups);
                DupIsolated.Add(fi.Index);
            }
            else
            {
                HashSet<string> saved;
                DupSavedPicks.TryGetValue(fi.Index, out saved);
                DupSavedPicks.Remove(fi.Index);
                if (saved == null)
                    ColPicks.Remove(fi.Index);
                else
                    ColPicks[fi.Index] = saved;
                DupIsolated.Remove(fi.Index);
            }
            ApplyFilters();
            int shown = 0;
            try
            {
                shown = Dg.Items.Count;
            }
            catch (Exception) { }
            if (on)
                SetStatus(string.Format("Isolated {0} row{1} with duplicate {2} values.",
                    shown, shown == 1 ? "" : "s", fi.Name));
            else
                SetStatus(string.Format("Stopped isolating duplicates in {0}.", fi.Name));
            return on;
        }

        /// <summary>
        /// The next value not already in use, counting on the rightmost number.
        /// `SD-01` with `SD-02` taken gives `SD-03`; the padding and everything
        /// either side of the number are kept. A value with no number at all gets
        /// one added rather than being left as a clash.
        /// </summary>
        public string NextUnique(HashSet<string> taken, string seed)
        {
            var parts = Efr.SplitNumber(seed);
            if (parts == null)
            {
                string baseText = Efr.ToText(seed).TrimEnd();
                int n = 2;
                while (true)
                {
                    string candidate = baseText.Length > 0
                        ? string.Format("{0} {1}", baseText, n)
                        : Efr.ToText(n);
                    if (!taken.Contains(candidate))
                        return candidate;
                    n++;
                }
            }
            long step = 1;
            for (int i = 0; i < 100000; i++)
            {
                string candidate = Efr.SeriesValue(seed, step, 1);
                if (!taken.Contains(candidate))
                    return candidate;
                step++;
            }
            return seed;
        }

        /// <summary>Give every selected cell a value nothing else in its column uses.</summary>
        public void OnUniqueSequence(object sender = null, EventArgs args = null)
        {
            var cells = SelCells().Where(c => Model.Rows[c.Ridx].Cells[c.Fidx].Editable).ToList();
            if (cells.Count == 0)
            {
                SetStatus("Select one or more editable cells first.");
                return;
            }
            var byField = new Dictionary<int, List<SelCell>>();
            var fieldOrder = new List<int>();
            foreach (SelCell c in cells)
            {
                List<SelCell> list;
                if (!byField.TryGetValue(c.Fidx, out list))
                {
                    list = new List<SelCell>();
                    byField[c.Fidx] = list;
                    fieldOrder.Add(c.Fidx);
                }
                list.Add(c);
            }

            BeginBatch();
            int changed = 0;
            int left = 0;
            foreach (int fidx in fieldOrder)
            {
                List<SelCell> group = byField[fidx];
                FieldInfo fi = Model.Fields[fidx];
                Dictionary<string, int> counts = ColumnCounts(fi);
                var taken = new HashSet<string>(counts.Keys);
                foreach (SelCell cell in group.OrderBy(d => d.Pos))
                {
                    string current = TextAt(cell.Pos, cell.Col) ?? "";
                    int have;
                    counts.TryGetValue(current, out have);
                    if (have < 2)
                    {
                        left++;
                        continue;          // already unique: nothing to solve
                    }
                    string value = NextUnique(taken, current);
                    if (StageCell(cell.Pos, cell.Col, value))
                    {
                        taken.Add(value);
                        counts[value] = 1;
                        int was;
                        counts[current] = counts.TryGetValue(current, out was) ? was - 1 : 0;
                        changed++;
                    }
                }
            }
            EndBatch();

            string msg = string.Format("Renumbered {0} cell{1} to unique values.",
                changed, changed == 1 ? "" : "s");
            if (left > 0)
                msg += string.Format("  {0} {1} already unique.", left, left == 1 ? "was" : "were");
            SetStatus(msg);
        }

        // -- column filters -----------------------------------------------------

        /// <summary>
        /// Heading, a keyword box and a tick-filter caret, built as elements.
        /// The header is set to a live UIElement rather than a string, so there is
        /// no DataTemplate: the same reason the rows are built this way.
        /// </summary>
        public Border ColumnHeader(FieldInfo fi)
        {
            var panel = new StackPanel();
            panel.Orientation = Orientation.Vertical;

            var top = new StackPanel();
            top.Orientation = Orientation.Horizontal;
            top.Margin = new Thickness(0, 0, 0, 4);

            // the formula reference, as a quiet badge rather than part of the name
            var badge = new Border();
            badge.Width = 17;
            badge.Height = 17;
            badge.CornerRadius = new CornerRadius(9);
            badge.BorderBrush = Efr.Brush(Efr.C_ORANGE);
            badge.BorderThickness = new Thickness(1);
            badge.Background = Efr.Brush(Efr.C_TYPE_BG);
            badge.Margin = new Thickness(0, 0, 6, 0);
            badge.VerticalAlignment = VerticalAlignment.Center;
            TextBlock letter = EfrUi.Tb(fi.Letter, Efr.C_ORANGE, 9.5, true);
            letter.HorizontalAlignment = HorizontalAlignment.Center;
            letter.VerticalAlignment = VerticalAlignment.Center;
            badge.Child = letter;
            badge.ToolTip = string.Format("Column {0} \u2014 the name to use in a formula", fi.Letter);
            top.Children.Add(badge);

            TextBlock title = EfrUi.Tb(fi.Name,
                fi.IsType ? Efr.C_TYPE_FG :
                (!fi.Supported ? Efr.C_RO_FG : Efr.C_INST_FG), 12, true);
            title.TextTrimming = TextTrimming.CharacterEllipsis;
            title.VerticalAlignment = VerticalAlignment.Center;
            string tip = fi.IsType ? "Type parameter" : "Instance parameter";
            if (!fi.Supported)
                tip = !string.IsNullOrEmpty(fi.Reason) ? fi.Reason : "Read only";
            title.ToolTip = string.Format("{0} \u2014 column {1}", tip, fi.Letter);
            top.Children.Add(title);
            HeaderBadges[fi.Index] = (badge, letter);
            panel.Children.Add(top);

            var row = new WGrid();
            row.ColumnDefinitions.Add(new ColumnDefinition());
            var cd = new ColumnDefinition();
            cd.Width = new GridLength(20);
            row.ColumnDefinitions.Add(cd);

            var box = new TextBox();
            box.Height = 22;
            box.MinHeight = 22;
            box.Padding = new Thickness(4, 1, 2, 1);
            box.FontWeight = FontWeights.Normal;
            box.FontSize = 11;
            box.Tag = "Filter";
            box.ToolTip = string.Format("Show only rows where {0} contains this", fi.Name);
            try
            {
                string existing;
                box.Text = ColFilters.TryGetValue(fi.Index, out existing) ? existing : "";
            }
            catch (Exception) { }

            box.TextChanged += (sender, args) =>
            {
                string text;
                try
                {
                    text = ((TextBox)sender).Text ?? "";
                }
                catch (Exception)
                {
                    text = "";
                }
                if (text.Trim().Length > 0)
                    ColFilters[fi.Index] = text;
                else
                    ColFilters.Remove(fi.Index);
                DebounceFilter();
            };
            // clicking in the box must not sort the column underneath it
            box.PreviewMouseLeftButtonDown += (s, e) => StopHeaderClick(s, e);
            WGrid.SetColumn(box, 0);
            row.Children.Add(box);

            var caret = new Button();
            caret.Content = "\u25BE";
            caret.Width = 18;
            caret.Height = 22;
            caret.Padding = new Thickness(0);
            caret.ToolTip = "Pick which values to show";
            try
            {
                caret.Style = (Style)Window.Resources["CaretBtn"];
            }
            catch (Exception) { }

            // The header underneath sorts on click, so the caret has to mark the
            // event handled. Doing that in PreviewMouseLeftButtonDown *and* relying
            // on Click cannot work: handling the preview stops the button ever
            // raising Click, which is why the caret did nothing at all. Open the
            // filter from the preview instead, and handle it there.
            // the last test column carries a remove button instead of a filter,
            // since a test column is disposable and only the last can go without
            // shifting the ones after it
            bool lastScratch = fi.Scratch && fi.Index == Model.Fields.Count - 1;
            if (lastScratch)
            {
                caret.Content = "\u2715";
                caret.ToolTip = "Remove this test column";
                caret.PreviewMouseLeftButtonDown += (sender, args) =>
                {
                    args.Handled = true;
                    if (RemoveScratchColumn())
                        SetStatus("Removed the test column.");
                };
            }
            else
            {
                FieldInfo field = fi;
                caret.PreviewMouseLeftButtonDown += (sender, args) =>
                {
                    args.Handled = true;
                    OpenTickFilter(field);
                };
            }
            WGrid.SetColumn(caret, 1);
            row.Children.Add(caret);

            panel.Children.Add(row);
            HeaderBoxes[fi.Index] = box;
            HeaderCarets[fi.Index] = caret;
            HeaderTitles[fi.Index] = title;

            // the outline lives on a Border of our own rather than on the header's
            // template, which hardcodes its brush. The thickness never changes,
            // only the colour, so lighting it cannot nudge the layout.
            var outline = new Border();
            outline.BorderBrush = Efr.Brush(Efr.C_CLEAR);
            outline.BorderThickness = new Thickness(2);
            outline.CornerRadius = new CornerRadius(3);
            outline.Padding = new Thickness(3, 1, 3, 1);
            outline.Child = panel;
            outline.Background = Efr.Brush(Efr.C_CLEAR);   // hit-testable across its width
            HeaderOutlines[fi.Index] = outline;
            return outline;
        }

        /// <summary>
        /// Add the duplicate commands to a menu.
        /// `fieldOf` answers "which column?" when the menu opens, so the same
        /// items serve the heading menu (always its own column) and the cell menu
        /// (whichever column was right-clicked). The isolate item is an ordinary
        /// item whose label flips between isolating and un-isolating, rather than a
        /// checkable one whose state cannot be trusted inside its own Click.
        /// </summary>
        public void DuplicateItems(ContextMenu menu, Func<FieldInfo> fieldOf)
        {
            var highlight = new MenuItem();
            highlight.FontWeight = FontWeights.Bold;
            var isolate = new MenuItem();
            var clear = new MenuItem();

            menu.Opened += (sender, args) =>
            {
                FieldInfo fi = fieldOf();
                bool ok = fi != null;
                foreach (MenuItem item in new[] { highlight, isolate, clear })
                    item.Visibility = ok ? Visibility.Visible : Visibility.Collapsed;
                if (!ok)
                    return;
                List<string> dups = DuplicateValues(fi);
                highlight.Header = string.Format("Highlight duplicates in {0}", fi.Name);
                highlight.IsEnabled = dups.Count > 0;
                if (dups.Count == 0)
                    highlight.Header = string.Format("No duplicates in {0}", fi.Name);
                if (DupIsolated.Contains(fi.Index))
                {
                    isolate.Header = string.Format("Un-isolate duplicates in {0}", fi.Name);
                    isolate.IsEnabled = true;
                }
                else
                {
                    isolate.Header = string.Format("Isolate duplicates in {0}{1}",
                        fi.Name, dups.Count > 0
                            ? string.Format(" ({0} set{1})", dups.Count, dups.Count == 1 ? "" : "s")
                            : "");
                    isolate.IsEnabled = dups.Count > 0;
                }
                clear.Header = string.Format("Clear highlighting in {0}", fi.Name);
                clear.IsEnabled = CellHl.Keys.Any(k => k.FieldIndex == fi.Index);
            };

            highlight.Click += (sender, args) =>
            {
                FieldInfo fi = fieldOf();
                if (fi != null)
                    HighlightDuplicates(fi);
            };
            isolate.Click += (sender, args) =>
            {
                FieldInfo fi = fieldOf();
                if (fi != null)
                    IsolateDuplicates(fi, !DupIsolated.Contains(fi.Index));
            };
            clear.Click += (sender, args) =>
            {
                FieldInfo fi = fieldOf();
                if (fi != null)
                    ClearColumnHighlight(fi);
            };

            menu.Items.Add(highlight);
            menu.Items.Add(isolate);
            menu.Items.Add(clear);
        }

        /// <summary>The right-click menu on a column heading.</summary>
        public ContextMenu HeaderMenu(FieldInfo fi)
        {
            var menu = new ContextMenu();
            DuplicateItems(menu, () => fi);
            menu.Items.Add(new Separator());

            var clearItem = new MenuItem();
            clearItem.Header = "Clear this column filter";
            clearItem.Click += (sender, args) => ClearColumnFilter(fi);
            menu.Items.Add(clearItem);

            var pickItem = new MenuItem();
            pickItem.Header = "Pick values to show...";
            pickItem.Click += (sender, args) => OpenTickFilter(fi);
            menu.Items.Add(pickItem);
            return menu;
        }

        /// <summary>
        /// (heading, field) under the mouse, or (null, null).
        /// The filter box inside a heading does not count: it keeps its own
        /// cut / copy / paste menu.
        /// </summary>
        public (DataGridColumnHeader Header, FieldInfo Field) HeaderUnderPointer()
        {
            DependencyObject hit;
            try
            {
                hit = Dg.InputHitTest(Mouse.GetPosition(Dg)) as DependencyObject;
            }
            catch (Exception)
            {
                return (null, null);
            }
            DataGridColumnHeader header = EfrUi.WalkUp<DataGridColumnHeader>(hit);
            if (header == null)
                return (null, null);
            if (EfrUi.WalkUp<TextBox>(hit) != null)
                return (null, null);
            FieldInfo fi = null;
            if (header.Column != null)
                ColField.TryGetValue(header.Column, out fi);
            return (header, fi);
        }

        public bool OpenHeaderMenu(DataGridColumnHeader header, FieldInfo fi)
        {
            try
            {
                ContextMenu menu = HeaderMenu(fi);
                menu.PlacementTarget = header;
                menu.Placement = PlacementMode.MousePoint;
                menu.IsOpen = true;
                return true;
            }
            catch (Exception)
            {
                return false;
            }
        }

        /// <summary>
        /// Right-click anywhere on a heading opens that column's menu.
        /// Handled on the button *coming up*, which is when Windows opens a
        /// context menu, and marked handled, so nothing else gets the chance to
        /// open the cell menu in its place. This does not depend on the grid
        /// deciding to raise ContextMenuOpening for a heading, or on which part of
        /// the heading happens to be hit-testable.
        /// </summary>
        public void OnHeaderRightUp(object sender, MouseButtonEventArgs args)
        {
            var hp = HeaderUnderPointer();
            if (hp.Header == null)
                return;
            args.Handled = true;
            if (hp.Field == null)
                return;                // the # and Id columns have no menu
            _menuCol = hp.Field;
            OpenHeaderMenu(hp.Header, hp.Field);
        }

        /// <summary>The keyboard route to the same menu (the menu key, Shift+F10), and a
        /// second line of defence if the mouse route were ever bypassed.</summary>
        public void OnGridMenuOpening(object sender, ContextMenuEventArgs args)
        {
            var hp = HeaderUnderPointer();
            if (hp.Header == null)
                return;
            args.Handled = true;
            if (hp.Field != null)
            {
                _menuCol = hp.Field;
                OpenHeaderMenu(hp.Header, hp.Field);
            }
        }

        public void ClearColumnHighlight(FieldInfo fi)
        {
            int n = 0;
            foreach (var key in CellHl.Keys.ToList())
            {
                if (key.FieldIndex == fi.Index)
                {
                    CellHl.Remove(key);
                    n++;
                }
            }
            RepaintSoon();
            SetStatus(string.Format("Cleared {0} highlighted cell{1} in {2}.",
                n, n == 1 ? "" : "s", fi.Name));
        }

        public void ClearColumnFilter(FieldInfo fi)
        {
            ColPicks.Remove(fi.Index);
            ColFilters.Remove(fi.Index);
            TextBox box;
            HeaderBoxes.TryGetValue(fi.Index, out box);
            try
            {
                if (box != null)
                    box.Text = "";
            }
            catch (Exception) { }
            ApplyFilters();
            SetStatus(string.Format("Cleared the filter on {0}.", fi.Name));
        }

        /// <summary>
        /// Outline the column the table is sorted by, and show the direction.
        /// The header template draws no sort arrow of its own, so without this a
        /// sorted table gives no clue which column it is sorted on or which way.
        /// </summary>
        public void MarkSortedColumn()
        {
            foreach (var pair in HeaderOutlines)
            {
                try
                {
                    string colour = SortColour(pair.Key);
                    pair.Value.BorderBrush = Efr.Brush(colour ?? Efr.C_CLEAR);
                }
                catch (Exception) { }
            }
            foreach (var pair in HeaderTitles)
            {
                try
                {
                    FieldInfo fi = Model.Fields[pair.Key];
                    TextBlock title = pair.Value;
                    title.Text = fi.Name + SortArrow(pair.Key);
                    title.Foreground = Efr.Brush(SortColour(pair.Key) ?? (
                        fi.IsType ? Efr.C_TYPE_FG :
                        (!fi.Supported ? Efr.C_RO_FG : Efr.C_INST_FG)));
                }
                catch (Exception) { }
            }
            foreach (var pair in HeaderBadges)
            {
                try
                {
                    Border badge = pair.Value.Badge;
                    TextBlock letter = pair.Value.Letter;
                    badge.BorderBrush = Efr.Brush(Efr.C_ORANGE);
                    badge.Background = Efr.Brush(Efr.C_TYPE_BG);
                    letter.Foreground = Efr.Brush(Efr.C_ORANGE);
                }
                catch (Exception) { }
            }
        }

        /// <summary>Where this column sits in the sort: 0 primary, 1 secondary, else null.</summary>
        public int? SortLevelOf(int index)
        {
            for (int n = 0; n < SortStack.Count; n++)
            {
                try
                {
                    if (SortStack[n].Field.Index == index)
                        return n;
                }
                catch (Exception)
                {
                    continue;
                }
            }
            return null;
        }

        /// <summary>The colour of this column's sort level, or null when it is not sorted on.</summary>
        public string SortColour(int index)
        {
            int? level = SortLevelOf(index);
            if (level == null)
                return null;
            return EfrUi.SortLevelColour(level.Value);
        }

        public string SortArrow(int index)
        {
            int? level = SortLevelOf(index);
            if (level == null)
                return "";
            bool desc = SortStack[level.Value].Desc;
            string arrow = desc ? "\u25BC" : "\u25B2";
            if (SortStack.Count > 1)
                return string.Format("   {0}{1}", level.Value + 1, arrow);
            return "   " + arrow;
        }

        /// <summary>
        /// Give the box the keyboard without letting the header sort.
        /// Only the first click is swallowed. Handling every one would take the
        /// mouse away from the text box as well as from the header, leaving no way
        /// to place the caret or select inside the filter text.
        /// </summary>
        public void StopHeaderClick(object sender, MouseButtonEventArgs args)
        {
            try
            {
                var element = (UIElement)sender;
                if (element.IsKeyboardFocusWithin)
                    return;
                element.Focus();
                args.Handled = true;
            }
            catch (Exception) { }
        }

        /// <summary>Coalesce keystrokes: refiltering on every one is visibly slow.</summary>
        public void DebounceFilter()
        {
            if (_filterTimer == null)
            {
                _filterTimer = new DispatcherTimer();
                _filterTimer.Interval = TimeSpan.FromMilliseconds(220);
                _filterTimer.Tick += (sender, args) =>
                {
                    _filterTimer.Stop();
                    ApplyFilters();
                };
            }
            _filterTimer.Stop();
            _filterTimer.Start();
        }

        public void OpenTickFilter(FieldInfo fi)
        {
            try
            {
                EfrUi.TickFilterDialog(this, fi);
            }
            catch (Exception ex)
            {
                EfrUi.ThemedMessage(string.Format("Filter \u2014 {0}", fi.Name),
                    "That filter could not be opened:\n\n" + ex,
                    owner: Window, accent: Efr.C_RED, width: 680);
            }
        }
    }
}


