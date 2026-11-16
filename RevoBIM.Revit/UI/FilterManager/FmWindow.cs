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
using RevoBIM.Helpers;
using RevoBIM.Tools.FilterManager;
using ComboBox = System.Windows.Controls.ComboBox;
using TextBox = System.Windows.Controls.TextBox;
using Panel = System.Windows.Controls.Panel;
using Point = System.Windows.Point;
using View = Autodesk.Revit.DB.View;
using Visibility = System.Windows.Visibility;

using Grid = System.Windows.Controls.Grid;

namespace RevoBIM.UI.FilterManager
{
    /// <summary>One filter row in the Filter Manager tab's list: a list item that can turn into a text box for renaming in place.</summary>
    public class FmFilterRow
    {
        public ListBoxItem Item;
        public ParameterFilterElement Pfe;
        public string Name;
        public TextBlock Label;
        public TextBox Box;
    }

    /// <summary>One editable rule row of the Filter Manager tab: parameter, operator, value, remove.</summary>
    public class FmRuleRow
    {
        public Grid Grid;
        public ComboBox Param, Op;
        public ContentControl Host;
        public FrameworkElement Editor;
        public string Storage = "String";
        public ForgeTypeId Spec;
        public bool YesNo;
        public string Note = "";
        public bool Busy;
    }

    /// <summary>
    /// RevoBIM Filter Manager (port of the pyRevit tool, script.py v3.31.0). Three tabs in one window: Filter
    /// Manager (every view filter, its categories and rules), Table (every filter on one grid, with Excel
    /// import and export) and Filter Pusher (push filters and their graphics from a host template or from the
    /// project into any number of view templates and views). Modeless: every write goes through the
    /// ExternalEvent runner.
    ///
    /// The class is split by tab: FmWindow.cs (state, chrome, layout, footer), FmWindow.Controls.cs (the named
    /// controls), FmWindow.Manager.cs, FmWindow.Table*.cs, FmWindow.Pusher*.cs. Python snake_case names become
    /// PascalCase (reload_filters is ReloadFilters); the on_* handlers are wired from the XAML by name.
    /// </summary>
    public partial class FmWindow : FmWindowBase
    {
        // ---- two switches, as in the pyRevit tool
        // False opens the tool as an ordinary modal dialog (no ExternalEvent at all).
        public const bool Modeless = true;
        // False skips counting how many views use each filter: the one thing the tool does at start up that has to touch every view.
        public const bool ReadFilterUsage = true;

        // the columns whose width is remembered between sessions
        public static readonly string[] LayoutColumns = { "colPusherA", "colPusherB", "colPusherC" };

        // the table tab: one block per filter, one row per rule, categories stacked.
        // key, heading, the width it will not go below, its share of the spare space.
        public static readonly TableColumn[] TableColumns =
        {
            new TableColumn("name", "Filter Name", 232, 3.0),
            new TableColumn("uses", "#", 46, 0.0),
            new TableColumn("categories", "Categories", 214, 1.0),
            new TableColumn("match", "Elements must match", 128, 0.0),
            new TableColumn("parameter", "Parameter", 216, 1.0),
            new TableColumn("operator", "Operator", 192, 0.5),
            new TableColumn("value", "Value", 186, 1.5),
            new TableColumn("actions", "", 78, 0.0),
        };

        public class TableColumn
        {
            public string Key, Label;
            public double Width, Share;
            public TableColumn(string key, string label, double width, double share) { Key = key; Label = label; Width = width; Share = share; }
        }

        public static readonly string[] MatchLabels = { "ALL of the rules  (AND)", "ANY of the rules  (OR)" };
        public static readonly string[] MatchKeys = { "AND", "OR" };

        // ---- the session
        public readonly UIApplication UiApp;
        public readonly Document Doc;

        // ---- manager tab state
        private List<ParameterFilterElement> allFilters = new List<ParameterFilterElement>();
        private Dictionary<long, int> usage = new Dictionary<long, int>();
        private ParameterFilterElement current;
        private Dictionary<string, bool> catState = new Dictionary<string, bool>();
        private List<Tuple<ElementId, string>> allCategories;
        private List<FmRuleRow> ruleRows = new List<FmRuleRow>();
        private List<FmFilterRow> filterRows = new List<FmFilterRow>();
        private FmFilterRow inlineRow;
        private ParameterProbe probe;
        private List<Tuple<ElementId, string>> paramList = new List<Tuple<ElementId, string>>();
        private bool loading;

        // ---- pusher tab state
        private List<View> templates = new List<View>();
        private Dictionary<long, int> templateCounts = new Dictionary<long, int>();
        private View host;
        private List<Tuple<ElementId, string>> hostFilters = new List<Tuple<ElementId, string>>();
        private Dictionary<string, bool> pushState = new Dictionary<string, bool>();
        private Dictionary<string, bool> targetState = new Dictionary<string, bool>();

        // ---- pusher "Target Views" sub-tab state
        private int tgtIndex;                                              // 0 = view templates, 1 = views
        private List<FmViewRow> viewRows = new List<FmViewRow>();          // FmFilters.GetFilterableViews rows
        private Dictionary<long, bool> viewState = new Dictionary<long, bool>();   // view id value -> ticked
        private HashSet<string> typesHidden = new HashSet<string>();       // "family|type" unticked in the dropdown
        private bool viewsLoaded;
        private bool bulk;                                                 // set while code ticks many boxes
        private double popClosedAt;
        private bool viewsOnlySelected;
        private bool popWired;

        // ---- "Filters to push" table: which settings go with each filter
        private Dictionary<string, Dictionary<string, bool>> pushGroups = new Dictionary<string, Dictionary<string, bool>>();   // filter name -> {group: ticked}
        private List<FmPushRow> pushRows = new List<FmPushRow>();
        private object pushViewer;
        private string overwriteMode = "all";                              // "all" or "new"

        // ---- pusher "Filters" sub-tab state
        private Dictionary<string, bool> allPushState = new Dictionary<string, bool>();            // project list: filter name -> ticked
        private List<Tuple<ElementId, string>> staged = new List<Tuple<ElementId, string>>();      // the table
        private Dictionary<string, bool> stagedTicked = new Dictionary<string, bool>();            // table: filter name -> row ticked
        private Dictionary<long, FmSpec> specs = new Dictionary<long, FmSpec>();                   // filter id value -> override spec
        private List<object> rowControls = new List<object>();                                     // the table's live WPF controls
        private List<FmChoice> linePatterns;                               // loaded on first use, not at startup
        private List<FmChoice> fillPatterns;

        // ---- tab strip state (plain buttons, not a TabControl)
        private int tabIndex;
        private int srcIndex;
        private Dictionary<string, string> layoutSaved = new Dictionary<string, string>();
        private List<FmBlock> tableBlocks = new List<FmBlock>();
        private List<FmBlock> tableVisible = new List<FmBlock>();
        private string sortKey = "name";
        private bool sortAscending = true;
        private Grid header;
        private double[] widthsNow = new double[0];
        private Dictionary<string, string> columnSearch = new Dictionary<string, string>
        {
            { "name", "" }, { "uses", "" }, { "categories", "" }, { "parameter", "" }, { "operator", "" }, { "value", "" },
        };

        // ---- modeless plumbing
        private FmRunner runner;
        private FmUi.ScreenState screen;
        private Dictionary<string, FmDebounce> searches;

        public FmWindow(UIApplication uiapp)
        {
            UiApp = uiapp;
            Doc = uiapp.ActiveUIDocument.Document;
            FmCore.SetUiApp(uiapp);

            FmCore.Crumb("window: parsing ui.xaml");
            Init("ui.xaml");
            FmCore.Crumb("window: ui.xaml parsed");
            BindControls();
            ApplyIcon(imgIcon);
            txtVersion.Text = FmCore.Version;

            FmCore.Crumb("model: reading filterable categories");
            allCategories = FmFilters.FilterableCategories(Doc);
            FmCore.Crumb("model: " + allCategories.Count + " filterable categories");

            // ---- modeless plumbing
            runner = new FmRunner(!Modeless);
            runner.SetErrorReporter(ReportError);
            runner.OnRefused = ReportRefused;
            FmUi.SetHandlerReporter(ReportHandlerError);
            if (runner.CreateError != null) FmCore.Crumb("events: ExternalEvent.Create failed");
            screen = new FmUi.ScreenState(Win);
            searches = new Dictionary<string, FmDebounce>
            {
                { "filters", new FmDebounce(RunFmSearch) },
                { "table", new FmDebounce(FillTableRows) },
                { "hosts", new FmDebounce(FillHosts) },
                { "targets", new FmDebounce(FillTargets) },
                { "views", new FmDebounce(FillTargetViews) },
                { "push", new FmDebounce(RunPushFilterSearch) },
                { "all", new FmDebounce(RunAllFilterSearch) },
            };

            Win.PreviewKeyDown += FmUi.SafeKey(OnKey, "on_key");
            Win.Closed += FmUi.SafeEvent(OnClosed, "on_closed");
            Win.Loaded += FmUi.Safe(OnLoaded, "on_loaded");
            Win.Activated += FmUi.SafeEvent(OnWindowActivated, "on_window_activated");
            // the heading over "Filters to push" tracks the list's scrollbar
            lstPushFilters.SizeChanged += FmUi.SafeSize((s, a) => SyncPushHeader(), "sync_push_header");

            // the logo easter egg: three slow clicks on the logo open the RevoBIM Arcade
            EggHook.Attach(Win, () => FmTheme.Name, pnlLogo);

            foreach (string lbl in MatchLabels) cboMatch.Items.Add(FmUi.ComboItem(lbl));
            cboMatch.SelectedIndex = 0;

            FmCore.Crumb("model: reading filters");
            ReloadFilters();
            FmCore.Crumb("model: " + allFilters.Count + " filters");
            FmCore.Crumb("model: reading view templates");
            ReloadTemplates();
            FmCore.Crumb("model: " + templates.Count + " view templates");
            BuildPropsPanel();
            ApplyLayout();
            FmCore.Crumb("window: built");

            RefreshFooter();
        }

        // -- chrome ---------------------------------------------------------------
        /// <summary>The logo easter egg is armed by EggHook (see the constructor); the layout still names this handler.</summary>
        public void OnLogo(object sender, MouseButtonEventArgs args) { }

        /// <summary>Drag the window, or double click to toggle full screen. Dragging while full screen breaks out first.</summary>
        public new void OnDrag(object sender, MouseButtonEventArgs args)
        {
            if (FmDrawer.OnHeaderDown(Drawer, Win, args)) return;
            try
            {
                if (args.ClickCount == 2)
                {
                    screen.ToggleFull();
                    return;
                }
            }
            catch (Exception) { }
            try { if (screen.Full) screen.BreakOut(args); }
            catch (Exception) { }
            try { Win.DragMove(); }
            catch (Exception) { }
        }

        /// <summary>Double click the very top edge to fill the screen vertically.</summary>
        public void OnTopEdge(object sender, MouseButtonEventArgs args)
        {
            if (Drawer.Shrunk || Drawer.Moving) return;
            try
            {
                if (args.ClickCount == 2)
                {
                    screen.ToggleVertical();
                    args.Handled = true;
                }
            }
            catch (Exception) { }
        }

        /// <summary>Auto, Dark, Light. Auto follows Revit's canvas theme.</summary>
        public void OnTheme(object sender, RoutedEventArgs args)
        {
            FmTheme.SetMode(FmTheme.NextMode(FmTheme.Mode), FmUi.RevitTheme());
            RepaintTheme();
            SaveLayout();
        }

        /// <summary>In Auto, pick up a theme change made in Revit while open.</summary>
        private void OnWindowActivated(object sender, EventArgs args)
        {
            if (FmTheme.Mode != "auto") return;
            string before = FmTheme.Name;
            FmTheme.SetMode("auto", FmUi.RevitTheme());
            if (FmTheme.Name != before) RepaintTheme();
        }

        private void RepaintTheme()
        {
            FmUi.ApplyPalette(Win);
            string label;
            txtTheme.Text = FmTheme.ModeLabels.TryGetValue(FmTheme.Mode, out label) ? label : "Auto";
            try
            {
                btnTheme.ToolTip = "Theme: " + txtTheme.Text + "  (" + FmTheme.Name + " palette)\n" +
                                   "Click to cycle Auto, Dark, Light. Auto follows Revit's canvas theme.";
            }
            catch (Exception) { }
            try
            {
                pnlThemeChip.Background = FmUi.PBrush(FmTheme.Mode == "auto" ? "Green" : (FmTheme.Name == "light" ? "Blue" : "Orange"));
            }
            catch (Exception) { }
            // Anything built in code holds the brushes it was built with, so it keeps the old palette until it is
            // built again. The XAML follows on its own, through DynamicResource.
            BuildPropsPanel();
            if (current != null) FillCategories();
            RepaintTable();
        }

        /// <summary>Redraw the Filter Manager Table in the palette now in force.</summary>
        private void RepaintTable()
        {
            foreach (FmBlock block in tableBlocks)
            {
                if (!block.Hydrated) continue;
                try
                {
                    block.Host.BorderBrush = FmUi.PBrush("EdgeFaint");
                    PaintBlock(block);
                }
                catch (Exception) { }
            }
            if (tableBlocks.Count > 0)
            {
                try
                {
                    RebuildHeader();
                    FillTableRows();
                }
                catch (Exception) { }
            }
        }

        public void OnFullscreen(object sender, RoutedEventArgs args)
        {
            if (Drawer.Shrunk || Drawer.Moving)
            {
                Drawer.Expand();
                return;
            }
            screen.ToggleFull();
        }

        /// <summary>Keyboard shortcuts. No blanket try/except: this is guarded, and swallowing everything is how shortcuts end up calling methods that do not exist.</summary>
        private void OnKey(object sender, KeyEventArgs args)
        {
            bool control = Keyboard.Modifiers == ModifierKeys.Control;
            if (args.Key == Key.F11)
            {
                OnFullscreen(null, null);
                args.Handled = true;
            }
            else if (args.Key == Key.F5)
            {
                OnRefresh(null, null);
                args.Handled = true;
            }
            else if (args.Key == Key.D && control && ManagerTab())
            {
                OnDuplicateFilter(null, null);
                args.Handled = true;
            }
            else if (args.Key == Key.F2 && ManagerTab())
            {
                OnFilterDblclick(null, null);
                args.Handled = true;
            }
            else if (args.Key == Key.Escape && screen.Full)
            {
                screen.ExitFull();
                args.Handled = true;
            }
        }

        /// <summary>The handle exists by now, so the screen it is on can be asked.</summary>
        private void OnLoaded(object sender, RoutedEventArgs args) { screen.FitToScreen(); }

        private void OnClosed(object sender, EventArgs args)
        {
            SaveLayout();
            FmCore.Crumb("window: closed cleanly");
            FmWindowKeeper.Unpark();
        }

        // -- column widths --------------------------------------------------------
        /// <summary>The staging table, its arrows and the padding around them.</summary>
        private double TablePanelWidth() { return TableWidth() + 44 + 8 + 8 + 8 + 2 + 18; }

        private double SavedStar(string key, double fallback)
        {
            string raw;
            double value;
            if (layoutSaved.TryGetValue(key, out raw) &&
                double.TryParse(raw, System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out value) &&
                value > 0 && value <= 1000)
                return value;
            return fallback;
        }

        /// <summary>Crop column one to the longest filter name it is showing.</summary>
        private void FitListColumn()
        {
            double widest = 0.0;
            foreach (var pair in AllFilterPairs()) widest = Math.Max(widest, FmUi.MeasureText(pair.Item2, 12.0));
            if (widest <= 0) return;
            // tick box, padding, border and a scrollbar
            double wanted = widest + 34 + 26 + 20;
            wanted = Math.Max(190.0, Math.Min(wanted, 560.0));
            double pool = colPusherA.ActualWidth + colPusherC.ActualWidth;
            if (pool <= 0)
            {
                colPusherA.Width = FmUi.Pixels(wanted);
                return;
            }
            double spare = Math.Max(colPusherC.MinWidth, pool - wanted);
            SetPair(colPusherA, colPusherC, pool - spare, spare);
        }

        public void OnFitList(object sender, RoutedEventArgs args) { FitListColumn(); }

        /// <summary>Write two columns back as star values (pixels would freeze them: Grid never shrinks an absolute column).</summary>
        private static void SetPair(ColumnDefinition first, ColumnDefinition second, double widthFirst, double widthSecond)
        {
            widthFirst = Math.Max(first.MinWidth, widthFirst);
            widthSecond = Math.Max(second.MinWidth, widthSecond);
            first.Width = FmUi.Star(widthFirst);
            second.Width = FmUi.Star(widthSecond);
        }

        private void WireSplitters()
        {
            pnlSplitA.DragDelta += FmUi.SafeDrag(OnSplitA, "on_split_a");
            pnlSplitB.DragDelta += FmUi.SafeDrag(OnSplitB, "on_split_b");
        }

        private void DragPair(ColumnDefinition first, ColumnDefinition second, double change)
        {
            var w = FmCore.SplitWidths(first.ActualWidth, second.ActualWidth, first.MinWidth, second.MinWidth, change);
            SetPair(first, second, w.Item1, w.Item2);
        }

        /// <summary>Column one against column three on the Filters tab, so the settings in the middle keep their width; against column two on the Templates tab.</summary>
        private void OnSplitA(object sender, DragDeltaEventArgs args)
        {
            ColumnDefinition other = SourceTab() == 1 ? colPusherC : colPusherB;
            DragPair(colPusherA, other, args.HorizontalChange);
        }

        private void OnSplitB(object sender, DragDeltaEventArgs args)
        {
            if (SourceTab() == 1) DragPair(colPusherC, colPusherA, -args.HorizontalChange);
            else DragPair(colPusherB, colPusherC, args.HorizontalChange);
        }

        // -- remembering how the columns were dragged -----------------------------
        /// <summary>Put the columns back where they were left last time (widths are kept as star values).</summary>
        private void ApplyLayout()
        {
            Dictionary<string, string> saved = FmCore.LoadSettings(FmCore.LayoutFile);
            layoutSaved = saved;
            // "theme_mode" replaces the old "theme" key, which every earlier version wrote on close - honouring
            // it would mean Auto never becomes the default for anyone who has used the tool before.
            string themeMode;
            FmTheme.SetMode(saved.TryGetValue("theme_mode", out themeMode) ? themeMode : "auto", FmUi.RevitTheme());
            RepaintTheme();
            WireSplitters();
            SelectSource(srcIndex);
            if (saved.Count == 0) return;
            foreach (string name in LayoutColumns)
            {
                string raw;
                double value;
                if (!saved.TryGetValue(name, out raw) || string.IsNullOrEmpty(raw)) continue;
                if (!double.TryParse(raw, System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out value)) continue;
                if (value <= 0 || value > 1000) continue;
                ColumnDefinition column = ColumnByName(name);
                if (column == null) continue;
                try { column.Width = new GridLength(value, GridUnitType.Star); }
                catch (Exception) { }
            }
        }

        private ColumnDefinition ColumnByName(string name)
        {
            switch (name)
            {
                case "colPusherA": return colPusherA;
                case "colPusherB": return colPusherB;
                case "colPusherC": return colPusherC;
            }
            return null;
        }

        private void SaveLayout()
        {
            var values = new Dictionary<string, string>();
            foreach (string name in LayoutColumns)
            {
                ColumnDefinition column = ColumnByName(name);
                if (column == null) continue;
                try
                {
                    GridLength width = column.Width;
                    if (width.IsStar && width.Value > 0)
                        values[name] = width.Value.ToString("0.0000", System.Globalization.CultureInfo.InvariantCulture);
                }
                catch (Exception) { }
            }
            values["theme_mode"] = FmTheme.Mode;
            FmCore.SaveSettings(FmCore.LayoutFile, values);
        }

        // -- error reporting ------------------------------------------------------
        private void ReportRefused(string status)
        {
            FmMessage.Alert("Revit would not accept the request to write (it answered '" + status + "').\n\n" +
                            "The work was run directly instead - check the model, and if nothing changed please send " +
                            "%APPDATA%\\RevoBIM\\filter_manager_last_run.txt");
        }

        private void ReportHandlerError(string name, string text)
        {
            FmMessage.Alert("RevoBIM Filter Manager " + FmCore.Version + "\n\n'" + name + "' failed:\n\n" + text);
        }

        private void ReportError(string text)
        {
            try { FmMessage.Alert("Revit refused the operation:\n\n" + text); }
            catch (Exception) { }
        }

        public void OnCancel(object sender, RoutedEventArgs args) { Win.Close(); }

        // -- tabs -----------------------------------------------------------------
        private void SelectTab(int index)
        {
            tabIndex = index;
            btnTabManager.Tag = index == 0 ? "on" : "off";
            btnTabTable.Tag = index == 1 ? "on" : "off";
            btnTabPusher.Tag = index == 2 ? "on" : "off";
            FmUi.SetVisible(pnlManagerTab, index == 0);
            FmUi.SetVisible(pnlTableTab, index == 1);
            FmUi.SetVisible(pnlPusherTab, index == 2);
            if (index == 1 && tableBlocks.Count == 0) BuildTableTab();
            RefreshFooter();
        }

        public void OnTabManager(object sender, RoutedEventArgs args) { SelectTab(0); }
        public void OnTabTable(object sender, RoutedEventArgs args) { SelectTab(1); }
        public void OnTabPusher(object sender, RoutedEventArgs args) { SelectTab(2); }

        private bool ManagerTab() { return tabIndex == 0; }
        private bool TableTab() { return tabIndex == 1; }

        /// <summary>
        /// Templates and Filters share the same three columns. On the Templates tab all three are star sized.
        /// On the Filters tab the middle column is pinned to the width of the staging table, so dragging column
        /// one takes its width from the target column on the right rather than squeezing the settings.
        /// </summary>
        private void SelectSource(int index)
        {
            srcIndex = index;
            btnSrcTemplates.Tag = index == 0 ? "on" : "off";
            btnSrcFilters.Tag = index == 1 ? "on" : "off";

            FmUi.SetVisible(pnlColHosts, index == 0);
            FmUi.SetVisible(pnlColHostFilters, index == 0);
            FmUi.SetVisible(pnlColFilterList, index == 1);
            FmUi.SetVisible(pnlColTable, index == 1);

            if (index == 1)
            {
                colPusherB.Width = FmUi.Pixels(TablePanelWidth());
                colPusherB.MinWidth = TablePanelWidth();
                if (!layoutSaved.ContainsKey("colPusherA")) FitListColumn();
            }
            else
            {
                colPusherB.MinWidth = 230;
                colPusherB.Width = FmUi.Star(SavedStar("colPusherB", 2.6));
            }
            RefreshFooter();
        }

        public void OnSrcTemplates(object sender, RoutedEventArgs args) { SelectSource(0); }
        public void OnSrcFilters(object sender, RoutedEventArgs args) { SelectSource(1); }

        /// <summary>0 = Templates, 1 = Filters, inside the pusher tab.</summary>
        private int SourceTab() { return srcIndex; }

        private void RefreshFooter()
        {
            if (TableTab())
            {
                int pending = tableBlocks.Count(b => b.Dirty);
                btnPrimary.Content = pending == 0 ? "APPLY TABLE" : "APPLY TABLE  (" + pending + ")";
                // always clickable: Apply checks the model itself, so pressing it with nothing flagged still
                // writes anything that really differs
                btnPrimary.IsEnabled = tableBlocks.Count > 0;
                FmUi.SetVisible(btnCreate, true);
                FmUi.SetVisible(btnDuplicate, false);
                FmUi.SetVisible(btnDelete, false);
                txtStatus.Text = pending == 0 ? "Edit any cell, then Apply." : pending + " filter(s) edited and waiting for Apply.";
                return;
            }

            if (ManagerTab())
            {
                btnPrimary.Content = "APPLY CHANGES";
                FmUi.SetVisible(btnCreate, true);
                FmUi.SetVisible(btnDelete, true);
                FmUi.SetVisible(btnDuplicate, true);
                int picked = SelectedFiltersInList().Count;
                btnDelete.IsEnabled = current != null;
                btnDuplicate.IsEnabled = current != null;
                btnPrimary.IsEnabled = current != null;
                if (current == null) txtStatus.Text = "Pick a filter on the left, or press Create Filter.";
                else if (picked > 1)
                    txtStatus.Text = picked + " filters selected - right click to rename them together. Editing  " + current.Name;
                else
                    txtStatus.Text = "Editing  " + current.Name + "   -   " + ruleRows.Count + " rule(s), " + TickedCategoryCount() + " categor(ies)";
                return;
            }

            btnPrimary.Content = "PUSH FILTERS";
            FmUi.SetVisible(btnCreate, false);
            FmUi.SetVisible(btnDelete, false);
            btnPrimary.IsEnabled = true;
            int nt = targetState.Values.Count(v => v);
            int nv = TickedViewRows().Count;
            string where = nt + " target template(s)";
            if (nv > 0) where += " + " + nv + " view(s)";
            if (overwriteMode == "new") where += "   (new only)";

            if (SourceTab() == 1)
                txtStatus.Text = staged.Count + " filter(s) in the table, with the graphics set there   >>   " + where;
            else
            {
                int nf = pushState.Values.Count(v => v);
                txtStatus.Text = nf + " filter(s) with the host's own settings   >>   " + where;
            }
        }

        /// <summary>Re-read the model. The window is modeless, so it goes stale.</summary>
        public void OnRefresh(object sender, RoutedEventArgs args)
        {
            ElementId keepFilter = current != null ? current.Id : null;
            ElementId keepHost = host != null ? host.Id : null;
            allCategories = FmFilters.FilterableCategories(Doc);
            linePatterns = null;     // loaded on first use, not at startup
            fillPatterns = null;

            ReloadFilters(keepFilter);
            ReloadTemplates(keepHost);

            var live = new Dictionary<long, Tuple<ElementId, string>>();
            foreach (var pair in AllFilterPairs()) live[FmCore.EidValue(pair.Item1)] = pair;
            staged = staged.Where(s => live.ContainsKey(FmCore.EidValue(s.Item1))).Select(s => live[FmCore.EidValue(s.Item1)]).ToList();
            BuildPropsPanel();
            tableBlocks = new List<FmBlock>();
            header = null;
            if (TableTab()) BuildTableTab();
            RefreshFooter();
            txtStatus.Text = "Refreshed - " + allFilters.Count + " filters, " + templates.Count + " view templates.";
        }

        public void OnPrimary(object sender, RoutedEventArgs args)
        {
            if (ManagerTab()) ApplyChanges();
            else if (TableTab()) ApplyTable();
            else PushFilters();
        }

        // -- the run log ----------------------------------------------------------
        private string WriteLog(string prefix, IEnumerable<string> bodyLines, string subject)
        {
            string path = FmCore.LogPath(prefix);
            var rows = new List<string>
            {
                "RevoBIM - Filter Manager " + FmCore.Version,
                "Run:    " + DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss"),
                "Revit:  " + FmCore.RevitVersion(),
                "Model:  " + Doc.Title,
                "Task:   " + subject,
                new string('=', 96),
            };
            rows.AddRange(bodyLines);
            FmCore.WriteText(path, string.Join("\r\n", rows) + "\r\n");
            return path;
        }

        /// <summary>Put a message in the status line (used by the command after the window opens).</summary>
        public void SetStatus(string text) { txtStatus.Text = text; }

        /// <summary>Run work on Revit's own thread (every write goes through here).</summary>
        private void RunInRevit(Action<UIApplication> work) { runner.Run(work); }
    }
}
