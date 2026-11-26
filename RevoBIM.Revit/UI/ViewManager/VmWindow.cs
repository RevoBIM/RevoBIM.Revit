using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Interop;
using System.Windows.Media;
using System.Windows.Threading;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using RevoBIM.Helpers;
using RevoBIM.Tools.ViewManager;
using ComboBox = System.Windows.Controls.ComboBox;
using Panel = System.Windows.Controls.Panel;
using TextBox = System.Windows.Controls.TextBox;
using Visibility = System.Windows.Visibility;

namespace RevoBIM.UI.ViewManager
{
    /// <summary>
    /// View Manager - the main window (port of ViewManagerWindow, version 1.13.1). Modeless: every write runs in an
    /// ExternalEvent and nothing waits on it. This half holds the lists, ticks and shift-click runs, the tabs and the
    /// plumbing; the creating half is in VmWindow.Run.cs.
    /// </summary>
    internal sealed partial class VmWindow
    {
        public const int TabRange = 2, TabViews = 3;     // the View Range and View Manager tabs
        public const int TabRefs = 4;           // index of the View Reference Manager tab

        public static VmWindow Current;
        public static VmRunner Runner;

        public readonly UIApplication UiApp;
        public readonly UIDocument UiDoc;
        public readonly Document Doc;

        public Window Window;
        public VmChrome Chrome;
        public VmThemed Themed;
        public VmRefsTab Refs;
        public VmViewsTab ViewsTab;
        public VmRangeTab RangeTab;
        public string RefsError;

        private List<View> hostViews = new List<View>();
        private List<Element> scopeBoxes = new List<Element>();
        private List<View> templates = new List<View>();
        private List<Level> levels = new List<Level>();
        private Dictionary<long, Element> elements = new Dictionary<long, Element>();

        private readonly Dictionary<long, bool> viewState = new Dictionary<long, bool>();
        private readonly Dictionary<long, bool> boxState = new Dictionary<long, bool>();
        private readonly Dictionary<long, bool> tplState = new Dictionary<long, bool>();
        private readonly Dictionary<long, bool> lvlState = new Dictionary<long, bool>();
        private long? cvBoxKey;

        public List<string> Log = new List<string>();
        private string reportText = "";
        public bool Busy;
        private bool fastMode = true;
        private bool askBeforeCreating = true;
        private Action<UIApplication> pendingJob;
        private readonly Dictionary<string, List<RowRec>> rowSets = new Dictionary<string, List<RowRec>>();
        private readonly Dictionary<string, int?> anchors = new Dictionary<string, int?>();
        private readonly Dictionary<string, HashSet<int>> highlights = new Dictionary<string, HashSet<int>>();
        private bool suppressToggle;
        private HashSet<long> isolateKeys = new HashSet<long>();
        private Dictionary<long, string[]> viewMeta = new Dictionary<long, string[]>();
        private Dictionary<long, string[]> tplMeta = new Dictionary<long, string[]>();
        private List<VmRevit.FilterOption> viewFilterOptions = new List<VmRevit.FilterOption>();
        private List<VmRevit.FilterOption> tplFilterOptions = new List<VmRevit.FilterOption>();
        private bool loadingFilters;

        private sealed class RowRec
        {
            public long Key;
            public Border Border;
            public CheckBox Check;
        }

        // named controls
        private Border header;
        private TextBlock versionLabel, status, viewsHead, boxesHead, tplHead, lvlHead, cvboxHead, isolateText;
        private TabControl tabs;
        public Button BtnRfApply, BtnRfRevert;
        private Button btnApply, btnCreate, btnReport;
        private CheckBox chkDebug, chkRoomTags, askRemember;
        private FrameworkElement progTrack, progFill, askOverlay, isolateChip;
        private ComboBox viewFilter, tplFilter;
        private TextBox viewSearch, boxSearch, tplSearch, lvlSearch, cvboxSearch;
        private StackPanel viewList, boxList, tplList, lvlList, cvboxList;

        private T C<T>(string name) where T : class
        {
            return Window.FindName(name) as T;
        }

        public VmWindow(UIApplication uiapp)
        {
            UiApp = uiapp;
            UiDoc = uiapp.ActiveUIDocument;
            Doc = UiDoc.Document;
            VmUi.RevitApp = uiapp.Application;
            VmCore.ProjectKeyProvider = () => VmRevit.ProjectName(Doc);

            Window = VmUi.LoadLayout("ViewManager.xaml");

            header = C<Border>("Header");
            versionLabel = C<TextBlock>("VersionLabel");
            tabs = C<TabControl>("Tabs");
            status = C<TextBlock>("Status");
            btnApply = C<Button>("BtnApply");
            btnCreate = C<Button>("BtnCreate");
            btnReport = C<Button>("BtnReport");
            BtnRfApply = C<Button>("BtnRfApply");
            BtnRfRevert = C<Button>("BtnRfRevert");
            chkDebug = C<CheckBox>("ChkDebug");
            chkRoomTags = C<CheckBox>("ChkRoomTags");
            askRemember = C<CheckBox>("AskRemember");
            progTrack = C<FrameworkElement>("ProgTrack");
            progFill = C<FrameworkElement>("ProgFill");
            askOverlay = C<FrameworkElement>("AskOverlay");
            isolateChip = C<FrameworkElement>("IsolateChip");
            isolateText = C<TextBlock>("IsolateText");
            viewFilter = C<ComboBox>("ViewFilter");
            tplFilter = C<ComboBox>("TplFilter");
            viewSearch = C<TextBox>("ViewSearch");
            boxSearch = C<TextBox>("BoxSearch");
            tplSearch = C<TextBox>("TplSearch");
            lvlSearch = C<TextBox>("LvlSearch");
            cvboxSearch = C<TextBox>("CvBoxSearch");
            viewList = C<StackPanel>("ViewList");
            boxList = C<StackPanel>("BoxList");
            tplList = C<StackPanel>("TplList");
            lvlList = C<StackPanel>("LvlList");
            cvboxList = C<StackPanel>("CvBoxList");
            viewsHead = C<TextBlock>("ViewsHead");
            boxesHead = C<TextBlock>("BoxesHead");
            tplHead = C<TextBlock>("TplHead");
            lvlHead = C<TextBlock>("LvlHead");
            cvboxHead = C<TextBlock>("CvBoxHead");

            versionLabel.Text = "v" + VmCore.Version;

            header.MouseLeftButtonDown += (s, e) => VmUi.DragMove(Window);
            Chrome = new VmChrome(Window, header, C<Button>("BtnShrink"));
            Themed = new VmThemed(Window, OnThemeChanged);
            C<Button>("BtnClose").Click += (s, e) => Guard("close", () => Window.Close());
            C<Button>("BtnCancel").Click += (s, e) => Guard("close", () => Window.Close());
            btnApply.Click += (s, e) => Guard("dependents", OnApplyDependents);
            btnCreate.Click += (s, e) => Guard("create", OnCreateViews);
            btnReport.Click += (s, e) => Guard("report", () => new VmDebugWindow(Window, reportText.Length > 0 ? reportText : BuildReport()).Show());
            BtnRfApply.Click += (s, e) => Guard("apply", () => { if (Refs != null) Refs.Apply(); });
            BtnRfRevert.Click += (s, e) => Guard("revert", () => { if (Refs != null) Refs.Revert(); });
            C<Button>("BtnRefresh").Click += (s, e) => Guard("refresh", OnRefresh);
            C<Button>("BtnSettings").Click += (s, e) => Guard("settings", () =>
                new VmSettingsWindow(this, Window, templates, levels, scopeBoxes, OnAbbreviationsChanged, 1).Show());
            C<Button>("BtnShowAll").Click += (s, e) => Guard("show all", () =>
            {
                isolateKeys = new HashSet<long>();
                BuildViews(viewSearch.Text);
                Refresh();
            });
            viewFilter.SelectionChanged += (s, e) => Guard("view filter", () =>
            {
                if (loadingFilters) return;
                BuildViews(viewSearch.Text);
                Refresh();
            });
            tplFilter.SelectionChanged += (s, e) => Guard("template filter", () =>
            {
                if (loadingFilters) return;
                BuildTemplates(tplSearch.Text);
                Refresh();
            });
            C<Button>("AskFast").Click += (s, e) => Guard("ask", () => { fastMode = true; RememberAnswer(); StartPending(); });
            C<Button>("AskNormal").Click += (s, e) => Guard("ask", () => { fastMode = false; RememberAnswer(); StartPending(); });
            C<Button>("AskCancel").Click += (s, e) => Guard("ask", () =>
            {
                pendingJob = null;
                askOverlay.Visibility = Visibility.Collapsed;
                SetStatus("Cancelled - nothing was created.");
            });
            tabs.SelectionChanged += (s, e) => Guard("tab", () => OnTabChanged(s, e));
            Window.KeyDown += (s, e) => Guard("key", () => { if (e.Key == Key.F5 && !Busy) OnRefresh(); });
            Window.Closed += (s, e) =>
            {
                if (ReferenceEquals(Current, this)) Current = null;
            };

            viewSearch.TextChanged += (s, e) => Guard("search", () => BuildViews(viewSearch.Text));
            boxSearch.TextChanged += (s, e) => Guard("search", () => BuildBoxes(boxSearch.Text));
            tplSearch.TextChanged += (s, e) => Guard("search", () => BuildTemplates(tplSearch.Text));
            lvlSearch.TextChanged += (s, e) => Guard("search", () => BuildLevels(lvlSearch.Text));
            cvboxSearch.TextChanged += (s, e) => Guard("search", () => BuildCvBoxes(cvboxSearch.Text));
            C<Button>("BtnViewsAll").Click += (s, e) => Guard("all", () => Bulk("views", viewState, true));
            C<Button>("BtnViewsNone").Click += (s, e) => Guard("none", () => Bulk("views", viewState, false));
            C<Button>("BtnBoxesAll").Click += (s, e) => Guard("all", () => Bulk("boxes", boxState, true));
            C<Button>("BtnBoxesNone").Click += (s, e) => Guard("none", () => Bulk("boxes", boxState, false));
            C<Button>("BtnTplAll").Click += (s, e) => Guard("all", () => Bulk("templates", tplState, true));
            C<Button>("BtnTplNone").Click += (s, e) => Guard("none", () => Bulk("templates", tplState, false));
            C<Button>("BtnLvlAll").Click += (s, e) => Guard("all", () => Bulk("levels", lvlState, true));
            C<Button>("BtnLvlNone").Click += (s, e) => Guard("none", () => Bulk("levels", lvlState, false));
            C<Button>("BtnCvBoxNone").Click += (s, e) => Guard("clear", () =>
            {
                cvBoxKey = null;
                foreach (object child in cvboxList.Children)
                {
                    var rb = child as RadioButton;
                    if (rb != null) rb.IsChecked = false;
                }
                Refresh();
            });

            try
            {
                chkRoomTags.IsChecked = VmCore.SettingOn("room_tags_on");
            }
            catch (Exception) { }
            chkRoomTags.Checked += (s, e) => { try { Refresh(); } catch (Exception) { } };
            chkRoomTags.Unchecked += (s, e) => { try { Refresh(); } catch (Exception) { } };
            ReadModel();

            try
            {
                Refs = new VmRefsTab(this);
            }
            catch (Exception ex)
            {
                RefsError = VmCore.Describe(ex);
                Log.Add("View Reference Manager failed to start: " + RefsError);
                Log.Add(ex.ToString());
            }

            try { RangeTab = new VmRangeTab(this); }
            catch (Exception ex)
            {
                Log.Add("View Range tab failed to start: " + VmCore.Describe(ex));
                Log.Add(ex.ToString());
            }
            try { ViewsTab = new VmViewsTab(this); }
            catch (Exception ex)
            {
                Log.Add("View Manager tab failed to start: " + VmCore.Describe(ex));
                Log.Add(ex.ToString());
            }

            // Views picked in the Project Browser isolate the host list and arrive ticked, on the tab that uses them.
            List<long> preselected = ReadPreselection();
            if (preselected.Count > 0)
            {
                isolateKeys = new HashSet<long>(preselected);
                foreach (long key in preselected) viewState[key] = true;
                try { tabs.SelectedIndex = 1; } catch (Exception) { }
            }

            RebuildAll();
            OnTabChanged(tabs, null);
            if (RefsError != null)
            {
                SetStatus("The View Reference Manager tab could not start - see the debug report.", true);
                OfferReport();
            }
            if (preselected.Count > 0)
                SetStatus(preselected.Count + " view(s) selected in Revit are isolated and ticked.");

            // the logo easter egg: three slow clicks on the RevoBIM wordmark open the Arcade
            try { EggHook.Attach(Window, () => VmCore.ThemeName, C<UIElement>("BrandText")); } catch (Exception) { }
        }

        // ---------------------------------------------------------------- guards --

        /// <summary>Never let a handler exception reach Revit's UI thread.</summary>
        public void Guard(string name, Action action)
        {
            try
            {
                action();
            }
            catch (Exception ex)
            {
                try
                {
                    SetStatus("Error: " + VmCore.Describe(ex), true);
                    Log.Add("HANDLER FAILED in " + name);
                    Log.Add(ex.ToString());
                    OfferReport();
                }
                catch (Exception) { }
            }
        }

        // ---------------------------------------------------------------- model --

        public void ReadModel()
        {
            hostViews = VmRevit.CollectHostViews(Doc);
            scopeBoxes = VmRevit.CollectScopeBoxes(Doc);
            templates = VmRevit.CollectViewTemplates(Doc);
            levels = VmRevit.CollectLevels(Doc);
            elements = new Dictionary<long, Element>();
            foreach (Element e in hostViews.Cast<Element>().Concat(scopeBoxes).Concat(templates).Concat(levels)) elements[VmRevit.Key(e)] = e;

            // family and type are read once here rather than on every keystroke
            viewMeta = VmRevit.BuildMeta(Doc, hostViews);
            tplMeta = VmRevit.BuildMeta(Doc, templates);
            // a pick that no longer exists is dropped rather than carried forward
            foreach (Dictionary<long, bool> state in new[] { viewState, boxState, tplState, lvlState })
                foreach (long key in state.Keys.ToList())
                    if (!elements.ContainsKey(key)) state.Remove(key);
            if (cvBoxKey != null && !elements.ContainsKey(cvBoxKey.Value)) cvBoxKey = null;
            if (isolateKeys.Count > 0) isolateKeys = new HashSet<long>(isolateKeys.Where(k => elements.ContainsKey(k)));
        }

        private void RebuildAll()
        {
            BuildViews(viewSearch.Text);
            BuildBoxes(boxSearch.Text);
            BuildTemplates(tplSearch.Text);
            BuildLevels(lvlSearch.Text);
            BuildCvBoxes(cvboxSearch.Text);
            Refresh();
        }

        /// <summary>Re-resolve an element at write time: modeless means it may be gone.</summary>
        public Element Live(long key)
        {
            Element element = Doc.GetElement(RevitCompat.Id(key));
            try
            {
                if (element == null || !element.IsValidObject) return null;
            }
            catch (Exception) { }
            return element;
        }

        // ---------------------------------------------------------------- shared helpers --

        public Brush BrushOf(string key) { return (Brush)Window.Resources[key]; }

        public void SetStatus(string text, bool error = false)
        {
            status.Text = text;
            status.Foreground = BrushOf(error ? "Orange" : "Muted");
        }

        private bool DebugOn()
        {
            try { return chkDebug.IsChecked == true; } catch (Exception) { return false; }
        }

        private int CurrentTab()
        {
            try { return tabs.SelectedIndex; } catch (Exception) { return 0; }
        }

        private UIElement RowContent(string label, string sub, string subBrush)
        {
            if (string.IsNullOrEmpty(sub)) return new TextBlock { Text = label };
            var sp = new StackPanel { Orientation = Orientation.Horizontal };
            sp.Children.Add(new TextBlock { Text = label });
            sp.Children.Add(new TextBlock { Text = "   " + sub, Foreground = BrushOf(subBrush) });
            return sp;
        }

        // ---------------------------------------------------------------- rows, and selecting a run of them --

        private void ResetRows(string name)
        {
            rowSets[name] = new List<RowRec>();
            anchors[name] = null;
            highlights[name] = new HashSet<int>();
        }

        /// <summary>One row: a CheckBox inside a Border that carries the highlight (the tick box's own Background is the box itself).</summary>
        private void AddRow(Panel panel, string name, long key, string label, Dictionary<long, bool> state, string sub = null, string subBrush = "Muted")
        {
            bool on;
            var chk = new CheckBox { Tag = key, IsChecked = state.TryGetValue(key, out on) && on, Content = RowContent(label, sub, subBrush) };
            var border = new Border { Background = Brushes.Transparent, Child = chk };       // or it is not hit testable
            int index = rowSets[name].Count;
            rowSets[name].Add(new RowRec { Key = key, Border = border, Check = chk });
            border.PreviewMouseLeftButtonDown += (s, e) => OnRowMouseDown(name, index, e);
            RoutedEventHandler toggled = (s, e) => OnRowToggle(name, index, state);
            chk.Checked += toggled;
            chk.Unchecked += toggled;
            panel.Children.Add(border);
        }

        private void OnRowMouseDown(string name, int index, MouseButtonEventArgs args)
        {
            List<RowRec> rows;
            if (!rowSets.TryGetValue(name, out rows) || index >= rows.Count) return;
            HashSet<int> highlight = highlights[name];
            int? anchor = anchors[name];
            bool shift = false, control = false;
            try
            {
                shift = (Keyboard.Modifiers & ModifierKeys.Shift) != 0;
                control = (Keyboard.Modifiers & ModifierKeys.Control) != 0;
            }
            catch (Exception) { }

            if (shift && anchor != null)
            {
                int low = Math.Min(anchor.Value, index), high = Math.Max(anchor.Value, index);
                highlight.Clear();
                for (int i = low; i <= high; i++) highlight.Add(i);
                PaintHighlight(name);
                args.Handled = true;             // extend the run, do not tick it
                return;
            }
            if (control)
            {
                if (!highlight.Remove(index)) highlight.Add(index);
                anchors[name] = index;
                PaintHighlight(name);
                args.Handled = true;
                return;
            }
            // A plain click on a row outside the run starts again from here; inside it, the run is kept so the tick carries.
            if (!highlight.Contains(index)) highlight.Clear();
            anchors[name] = index;
            PaintHighlight(name);
        }

        private void PaintHighlight(string name)
        {
            List<RowRec> rows;
            if (!rowSets.TryGetValue(name, out rows)) return;
            HashSet<int> highlight = highlights[name];
            Brush selected = BrushOf("Selection");
            for (int i = 0; i < rows.Count; i++)
            {
                try { rows[i].Border.Background = highlight.Contains(i) ? selected : Brushes.Transparent; } catch (Exception) { }
            }
        }

        private void OnRowToggle(string name, int index, Dictionary<long, bool> state)
        {
            if (suppressToggle) return;
            List<RowRec> rows;
            if (!rowSets.TryGetValue(name, out rows) || index >= rows.Count) return;
            HashSet<int> highlight = highlights[name];
            bool value = rows[index].Check.IsChecked == true;
            state[rows[index].Key] = value;
            if (highlight.Contains(index) && highlight.Count > 1)
            {
                suppressToggle = true;
                try
                {
                    foreach (int other in highlight.ToList())
                    {
                        if (other >= rows.Count || other == index) continue;
                        RowRec record = rows[other];
                        if ((record.Check.IsChecked == true) != value) record.Check.IsChecked = value;
                        state[record.Key] = value;
                    }
                }
                finally
                {
                    suppressToggle = false;
                }
            }
            Refresh();
        }

        private TextBlock EmptyRow(string text)
        {
            return new TextBlock { Text = "  " + text, Foreground = BrushOf("Muted") };
        }

        /// <summary>All / None over whatever the list is currently showing.</summary>
        private void Bulk(string name, Dictionary<long, bool> state, bool value)
        {
            suppressToggle = true;
            try
            {
                List<RowRec> rows;
                if (rowSets.TryGetValue(name, out rows))
                    foreach (RowRec record in rows)
                    {
                        state[record.Key] = value;
                        record.Check.IsChecked = value;
                    }
            }
            finally
            {
                suppressToggle = false;
            }
            Refresh();
        }

        // ---------------------------------------------------------------- list building --

        private TextBlock GroupHeader(string text)
        {
            return new TextBlock
            {
                Text = text.ToUpperInvariant(),
                Foreground = BrushOf("Muted"),
                FontSize = 10,
                FontWeight = FontWeights.SemiBold,
                Margin = new Thickness(10, 9, 8, 3),
            };
        }

        private static string OptionsSignature(List<VmRevit.FilterOption> options)
        {
            return string.Join("\u0001", options.Select(o => (o.Family ?? "\u0002") + "\u0003" + (o.Type ?? "\u0002") + "\u0003" + o.Label));
        }

        /// <summary>Refill a dropdown without its own SelectionChanged firing back.</summary>
        private void FillFilter(ComboBox combo, List<VmRevit.FilterOption> options, string[] keep)
        {
            loadingFilters = true;
            try
            {
                combo.Items.Clear();
                foreach (VmRevit.FilterOption o in options) combo.Items.Add(o.Label);
                int index = 0;
                if (keep != null)
                {
                    for (int i = 0; i < options.Count; i++)
                        if (options[i].Family == keep[0] && options[i].Type == keep[1]) { index = i; break; }
                }
                combo.SelectedIndex = combo.Items.Count > 0 ? index : -1;
            }
            finally
            {
                loadingFilters = false;
            }
        }

        private static string[] CurrentFilter(ComboBox combo, List<VmRevit.FilterOption> options)
        {
            int index;
            try { index = combo.SelectedIndex; } catch (Exception) { return new string[] { null, null }; }
            if (index < 0 || index >= options.Count) return new string[] { null, null };
            return new[] { options[index].Family, options[index].Type };
        }

        private static bool PassesFilter(string[] pair, string[] wanted)
        {
            if (wanted[0] == null) return true;
            if (pair[0] != wanted[0]) return false;
            return wanted[1] == null || pair[1] == wanted[1];
        }

        private sealed class Match
        {
            public string Family, Type, Name;
            public long Key;
        }

        private static int CompareMatches(Match a, Match b)
        {
            int c = string.CompareOrdinal(a.Family.ToLowerInvariant(), b.Family.ToLowerInvariant());
            if (c != 0) return c;
            c = string.CompareOrdinal(a.Type.ToLowerInvariant(), b.Type.ToLowerInvariant());
            if (c != 0) return c;
            return string.CompareOrdinal(a.Name.ToLowerInvariant(), b.Name.ToLowerInvariant());
        }

        private static List<Match> Sorted(List<Match> matches)
        {
            return matches.Select((m, i) => new { m, i }).OrderBy(t => t.m, Comparer<Match>.Create(CompareMatches)).ThenBy(t => t.i).Select(t => t.m).ToList();
        }

        private static string[] MetaOf(Dictionary<long, string[]> meta, long key)
        {
            string[] pair;
            return meta.TryGetValue(key, out pair) ? pair : new[] { "Other", "(no type)" };
        }

        private void BuildViews(string keyword)
        {
            viewList.Children.Clear();
            ResetRows("views");

            List<VmRevit.FilterOption> options = VmRevit.BuildFilterOptions(viewMeta);
            if (OptionsSignature(options) != OptionsSignature(viewFilterOptions))
            {
                string[] keep = CurrentFilter(viewFilter, viewFilterOptions);
                viewFilterOptions = options;
                FillFilter(viewFilter, options, keep);
            }
            string[] wanted = CurrentFilter(viewFilter, viewFilterOptions);

            string kw = (keyword ?? "").ToLowerInvariant().Trim();
            var matches = new List<Match>();
            foreach (View v in hostViews)
            {
                long key = VmRevit.Key(v);
                if (isolateKeys.Count > 0 && !isolateKeys.Contains(key)) continue;
                string[] pair = MetaOf(viewMeta, key);
                if (!PassesFilter(pair, wanted)) continue;
                if (kw.Length > 0 && !v.Name.ToLowerInvariant().Contains(kw) && !pair[0].ToLowerInvariant().Contains(kw) && !pair[1].ToLowerInvariant().Contains(kw)) continue;
                matches.Add(new Match { Family = pair[0], Type = pair[1], Name = v.Name, Key = key });
            }
            matches = Sorted(matches);

            string[] group = null;
            foreach (Match m in matches)
            {
                if (group == null || group[0] != m.Family || group[1] != m.Type)
                {
                    group = new[] { m.Family, m.Type };
                    viewList.Children.Add(GroupHeader(m.Family + "   -   " + m.Type));
                }
                AddRow(viewList, "views", m.Key, m.Name, viewState);
            }
            if (matches.Count == 0) viewList.Children.Add(EmptyRow("No matching views."));
            PaintIsolateChip();
        }

        private void BuildBoxes(string keyword)
        {
            boxList.Children.Clear();
            ResetRows("boxes");
            string kw = (keyword ?? "").ToLowerInvariant().Trim();
            int shown = 0;
            foreach (Element b in scopeBoxes)
            {
                if (kw.Length > 0 && !b.Name.ToLowerInvariant().Contains(kw)) continue;
                string source;
                string abbr = VmCore.BoxAbbrDetail(b.Name, out source);
                if (source == "override") AddRow(boxList, "boxes", VmRevit.Key(b), b.Name, boxState, "-> " + abbr, "Orange");
                else AddRow(boxList, "boxes", VmRevit.Key(b), b.Name, boxState);
                shown++;
            }
            if (shown == 0) boxList.Children.Add(EmptyRow("No matching scope boxes."));
        }

        private void BuildTemplates(string keyword)
        {
            tplList.Children.Clear();
            ResetRows("templates");

            List<VmRevit.FilterOption> options = VmRevit.BuildFilterOptions(tplMeta);
            if (OptionsSignature(options) != OptionsSignature(tplFilterOptions))
            {
                bool firstFill = tplFilterOptions.Count == 0;
                string[] keep = CurrentFilter(tplFilter, tplFilterOptions);
                // Create Views makes plans, so open on the plan templates
                if (firstFill) keep = new[] { VmCore.DefaultTemplateFamily, null };
                tplFilterOptions = options;
                FillFilter(tplFilter, options, keep);
            }
            string[] wanted = CurrentFilter(tplFilter, tplFilterOptions);

            string kw = (keyword ?? "").ToLowerInvariant().Trim();
            var matches = new List<Match>();
            foreach (View t in templates)
            {
                long key = VmRevit.Key(t);
                string[] pair = MetaOf(tplMeta, key);
                if (!PassesFilter(pair, wanted)) continue;
                if (kw.Length > 0 && !t.Name.ToLowerInvariant().Contains(kw) && !pair[0].ToLowerInvariant().Contains(kw) && !pair[1].ToLowerInvariant().Contains(kw)) continue;
                matches.Add(new Match { Family = pair[0], Type = pair[1], Name = t.Name, Key = key });
            }
            matches = Sorted(matches);

            string[] group = null;
            foreach (Match m in matches)
            {
                if (group == null || group[0] != m.Family || group[1] != m.Type)
                {
                    group = new[] { m.Family, m.Type };
                    tplList.Children.Add(GroupHeader(m.Family + "   -   " + m.Type));
                }
                bool matched;
                string abbr = VmCore.AbbreviateTemplate(m.Name, out matched);
                var t = (View)elements[m.Key];
                string tag, colour;
                if (VmRevit.PlanFamilyFor(t.ViewType.ToString()) == null)
                {
                    tag = "-> not a plan template";
                    colour = "Muted";
                }
                else if (matched)
                {
                    tag = "-> " + abbr;
                    colour = "Orange";
                }
                else
                {
                    tag = "-> " + abbr + "  (no keyword)";
                    colour = "Muted";
                }
                AddRow(tplList, "templates", m.Key, m.Name, tplState, tag, colour);
            }
            if (matches.Count == 0) tplList.Children.Add(EmptyRow("No matching templates."));
        }

        private void BuildLevels(string keyword)
        {
            lvlList.Children.Clear();
            ResetRows("levels");
            string kw = (keyword ?? "").ToLowerInvariant().Trim();
            int shown = 0;
            foreach (Level lv in levels)
            {
                if (kw.Length > 0 && !lv.Name.ToLowerInvariant().Contains(kw)) continue;
                AddRow(lvlList, "levels", VmRevit.Key(lv), lv.Name, lvlState, "-> " + VmCore.AbbreviateLevel(lv.Name), "Orange");
                shown++;
            }
            if (shown == 0) lvlList.Children.Add(EmptyRow("No matching levels."));
        }

        private void BuildCvBoxes(string keyword)
        {
            cvboxList.Children.Clear();
            string kw = (keyword ?? "").ToLowerInvariant().Trim();
            int shown = 0;
            foreach (Element b in scopeBoxes)
            {
                if (kw.Length > 0 && !b.Name.ToLowerInvariant().Contains(kw)) continue;
                long key = VmRevit.Key(b);
                var rb = new RadioButton { GroupName = "CreateViewsScopeBox", Tag = key, Content = b.Name, IsChecked = cvBoxKey == key };
                rb.Checked += (s, e) =>
                {
                    try
                    {
                        cvBoxKey = (long)((RadioButton)s).Tag;
                        Refresh();
                    }
                    catch (Exception) { }
                };
                cvboxList.Children.Add(rb);
                shown++;
            }
            if (shown == 0) cvboxList.Children.Add(EmptyRow("No matching scope boxes."));
        }

        // ---------------------------------------------------------------- the pre-selection isolate --

        /// <summary>Views picked in the Project Browser before the tool was opened.</summary>
        private List<long> ReadPreselection()
        {
            var hostKeys = new HashSet<long>(hostViews.Select(VmRevit.Key));
            ICollection<ElementId> ids;
            try { ids = UiDoc.Selection.GetElementIds(); } catch (Exception) { return new List<long>(); }
            var found = new List<long>();
            foreach (ElementId id in ids)
            {
                long key = id.Value;
                if (hostKeys.Contains(key) && !found.Contains(key)) found.Add(key);
            }
            if (found.Count > 0) return found;

            // Nothing picked was a view itself, so fall back to the views the picked elements live on - someone who picked a
            // viewport meant its sheet, and someone who picked an annotation meant its view.
            foreach (ElementId id in ids)
            {
                try
                {
                    Element element = Doc.GetElement(id);
                    long key = element.OwnerViewId.Value;
                    if (hostKeys.Contains(key) && !found.Contains(key)) found.Add(key);
                }
                catch (Exception) { }
            }
            return found;
        }

        private void PaintIsolateChip()
        {
            try
            {
                if (isolateKeys.Count > 0)
                {
                    isolateText.Text = "Isolated to " + isolateKeys.Count + " view(s) selected in Revit";
                    isolateChip.Visibility = Visibility.Visible;
                }
                else isolateChip.Visibility = Visibility.Collapsed;
            }
            catch (Exception) { }
        }

        private static List<long> Selected(Dictionary<long, bool> state)
        {
            return state.Where(kv => kv.Value).Select(kv => kv.Key).ToList();
        }

        public void Refresh()
        {
            int nv = Selected(viewState).Count, nb = Selected(boxState).Count, nt = Selected(tplState).Count, nl = Selected(lvlState).Count;

            viewsHead.Text = "HOST VIEWS  (" + nv + " of " + hostViews.Count + " selected)";
            boxesHead.Text = "SCOPE BOXES  (" + nb + " of " + scopeBoxes.Count + " selected)";
            tplHead.Text = "VIEW TEMPLATES  (" + nt + " of " + templates.Count + " selected)";
            lvlHead.Text = "LEVELS  (" + nl + " of " + levels.Count + " selected)";
            cvboxHead.Text = cvBoxKey == null ? "SCOPE BOX  (pick one)" : "SCOPE BOX  (1 picked)";

            bool ready = nt > 0 && nl > 0 && cvBoxKey != null;
            btnCreate.IsEnabled = ready && !Busy;
            btnApply.IsEnabled = !Busy;
            if (Busy) return;

            int tab = CurrentTab();
            if (tab == 0)
            {
                if (ready)
                {
                    string tags = "";
                    try { if (chkRoomTags.IsChecked == true) tags = ", with room tags"; } catch (Exception) { }
                    SetStatus((nt * nl) + " view(s) will be created" + tags + ", e.g. " + SampleName());
                }
                else
                {
                    var missing = new List<string>();
                    if (nt == 0) missing.Add("a view template");
                    if (nl == 0) missing.Add("a level");
                    if (cvBoxKey == null) missing.Add("one scope box");
                    SetStatus("Select " + string.Join(", ", missing) + ".");
                }
            }
            else if (tab == 1)
            {
                if (nv > 0 && nb > 0) SetStatus((nv * nb) + " dependent view(s) will be created.");
                else SetStatus("Select at least one view and one scope box.");
            }
            else if (tab == TabRefs)
            {
                if (Refs != null) Refs.UpdateState();
            }
            else if (tab == TabRange)
            {
                if (RangeTab != null) RangeTab.UpdateState();
            }
            else if (tab == TabViews)
            {
                if (ViewsTab != null) ViewsTab.UpdateState();
            }
        }

        private string SampleName()
        {
            List<long> tplKeys = Selected(tplState), lvlKeys = Selected(lvlState);
            if (tplKeys.Count == 0 || lvlKeys.Count == 0) return "";
            Element tpl, lvl;
            if (!elements.TryGetValue(tplKeys[0], out tpl) || !elements.TryGetValue(lvlKeys[0], out lvl)) return "";
            return VmCore.AbbreviateTemplate(tpl.Name) + VmCore.CreateSeparator + VmCore.AbbreviateLevel(lvl.Name);
        }

        // ---------------------------------------------------------------- handlers --

        /// <summary>Rows built in code hold their brushes, so rebuild them.</summary>
        private void OnThemeChanged()
        {
            try { RebuildAll(); } catch (Exception) { }
        }

        /// <summary>Relabel every list without disturbing the ticks.</summary>
        private void OnAbbreviationsChanged()
        {
            try { RebuildAll(); } catch (Exception) { }
        }

        private void OnRefresh()
        {
            if (Busy) return;
            if (CurrentTab() == TabRefs && Refs != null)
            {
                Refs.Reload();
                return;
            }
            if (CurrentTab() == TabRange && RangeTab != null)
            {
                RangeTab.Reload();
                return;
            }
            if (CurrentTab() == TabViews && ViewsTab != null)
            {
                ViewsTab.Reload();
                return;
            }
            ReadModel();
            RebuildAll();
        }

        private void OnTabChanged(object sender, SelectionChangedEventArgs args)
        {
            if (!ReferenceEquals(sender, tabs)) return;
            // SelectionChanged bubbles up from every list and grid inside a tab, so only the tab control's own change counts.
            if (args != null && !ReferenceEquals(args.OriginalSource, tabs)) return;
            int index = CurrentTab();
            bool first = index == 0, second = index == 1, refs = index == TabRefs;
            btnCreate.Visibility = first ? Visibility.Visible : Visibility.Collapsed;
            btnApply.Visibility = second ? Visibility.Visible : Visibility.Collapsed;
            BtnRfApply.Visibility = refs ? Visibility.Visible : Visibility.Collapsed;
            BtnRfRevert.Visibility = refs ? Visibility.Visible : Visibility.Collapsed;
            try { chkRoomTags.Visibility = first ? Visibility.Visible : Visibility.Collapsed; } catch (Exception) { }
            if (refs && Refs != null) Refs.Activate();
            if (index == TabRange && RangeTab != null) RangeTab.Activate();
            if (index == TabViews && ViewsTab != null) ViewsTab.Activate();
            Refresh();
        }

        /// <summary>After one grid wrote to the model, the others read it again the next time they are shown.</summary>
        public void InvalidateGridTabs(object except)
        {
            if (Refs != null && !ReferenceEquals(Refs, except)) Refs.Invalidate();
            if (RangeTab != null && !ReferenceEquals(RangeTab, except)) RangeTab.Invalidate();
            if (ViewsTab != null && !ReferenceEquals(ViewsTab, except)) ViewsTab.Invalidate();
        }

        // ---------------------------------------------------------------- debug --

        public void LogEnvironment(string job)
        {
            Log = new List<string>();
            Log.Add(VmCore.BuildInfo());
            Log.Add("Job: " + job);
            Log.Add("Revit: " + VmRevit.RevitVersion(UiApp.Application));
            Log.Add(".NET: " + Environment.Version + " (" + System.Runtime.InteropServices.RuntimeInformation.FrameworkDescription + ")");
            try { Log.Add("Document: " + Doc.Title + " (workshared=" + Doc.IsWorkshared + ")"); } catch (Exception) { }
            Log.Add("Counts: host views=" + hostViews.Count + ", scope boxes=" + scopeBoxes.Count + ", templates=" + templates.Count + ", levels=" + levels.Count);
            Log.Add("");
        }

        private string BuildReport()
        {
            var lines = new List<string>
            {
                "I'm using the RevoBIM View Manager tool and hit a problem. Here is the debug report - please work out what went wrong.",
                "",
                "```",
            };
            lines.AddRange(Log);
            lines.Add("```");
            reportText = string.Join("\n", lines);
            return reportText;
        }

        public void OfferReport()
        {
            try { btnReport.Visibility = Visibility.Visible; } catch (Exception) { }
        }

        public void Finish(string message, bool error = false, bool forceReport = false)
        {
            Busy = false;
            try
            {
                Window.IsHitTestVisible = true;
                progFill.Width = 0;
            }
            catch (Exception) { }
            SetStatus(message, error);
            Refresh();
            SetStatus(message, error);
            if (DebugOn() || forceReport)
            {
                BuildReport();
                OfferReport();
                if (DebugOn()) new VmDebugWindow(Window, reportText).Show();
            }
        }

        // ---------------------------------------------------------------- the ask-first overlay --

        private void AskThen(Action<UIApplication> job)
        {
            pendingJob = job;
            if (!askBeforeCreating)
            {
                StartPending();
                return;
            }
            try { askOverlay.Visibility = Visibility.Visible; }
            catch (Exception) { StartPending(); }
        }

        private void StartPending()
        {
            Action<UIApplication> job = pendingJob;
            pendingJob = null;
            try { askOverlay.Visibility = Visibility.Collapsed; } catch (Exception) { }
            if (job != null) Queue(job);
        }

        private void RememberAnswer()
        {
            try { if (askRemember.IsChecked == true) askBeforeCreating = false; } catch (Exception) { }
        }

        /// <summary>Hand work to the external event and return at once. Never wait for it: Revit raises the event on this very thread.</summary>
        public void Queue(Action<UIApplication> job)
        {
            Busy = true;
            btnApply.IsEnabled = false;
            btnCreate.IsEnabled = false;
            BtnRfApply.IsEnabled = false;
            BtnRfRevert.IsEnabled = false;
            SetStatus("Working...");
            // Pumping the dispatcher to paint progress also pumps mouse and key input, so the window is made untouchable until done.
            try { Window.IsHitTestVisible = false; } catch (Exception) { }
            Runner.Raise(job);
        }

        public void BackOnUi(Action fn)
        {
            try { Window.Dispatcher.Invoke(fn); }
            catch (Exception)
            {
                try { fn(); } catch (Exception) { }
            }
        }

        // ---------------------------------------------------------------- show --

        public void Show()
        {
            // Owned to Revit's main window, or a modeless window slips behind Revit and reads as a crash.
            try { new WindowInteropHelper(Window).Owner = UiApp.MainWindowHandle; } catch (Exception) { }
            Window.Show();
        }

        public void Activate()
        {
            try
            {
                if (Chrome.Mode == VmChrome.State.Shrunk)
                {
                    Chrome.Expand();
                    return;
                }
            }
            catch (Exception) { }
            try { if (Window.WindowState == WindowState.Minimized) Window.WindowState = WindowState.Normal; } catch (Exception) { }
            try { Window.Activate(); } catch (Exception) { }
        }

        /// <summary>Opens the window, or brings the open one forward.</summary>
        public static void Open(UIApplication uiapp)
        {
            if (Current != null)
            {
                Current.Activate();
                return;
            }
            VmCore.LoadSettings();
            VmUi.RevitApp = uiapp.Application;
            VmUi.ResolveTheme();
            VmCore.ProjectKeyProvider = () => VmRevit.ProjectName(uiapp.ActiveUIDocument.Document);
            VmCore.LoadOverrides();
            VmRevit.HookDialogs(uiapp);
            if (Runner == null) Runner = new VmRunner();

            Current = new VmWindow(uiapp);
            if (Current.scopeBoxes.Count == 0) Current.SetStatus("No scope boxes found in this project.", true);
            Current.Show();
        }
    }
}

