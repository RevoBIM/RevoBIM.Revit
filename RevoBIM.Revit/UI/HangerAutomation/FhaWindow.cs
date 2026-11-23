using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Threading;
using RevoBIM.Tools.HangerAutomation;
using ExternalEvent = Autodesk.Revit.UI.ExternalEvent;
using UIApplication = Autodesk.Revit.UI.UIApplication;

namespace RevoBIM.UI.HangerAutomation
{
    /// <summary>
    /// The modeless Hanger Automation window and its ExternalEvent runner (FhaHandler). Port of fha_window.py.
    ///
    /// Four tabs: FAB Hangers (FhaRevit), Family Hangers and Family Floor Support (both FamTab / HfamRevit, the
    /// floor one in mode "floor") and Service Type (SvcTab). All share one ExternalEvent. StartJob runs a tool
    /// and reports in the results box; StartQuiet runs a read (family list, preview, parameter names) and hands
    /// the answer to a callback without touching the results or the debug file.
    /// </summary>
    public sealed class FhaWindow : IFhaHost, IFamOwner, ISvcOwner
    {
        // tab key -> (tab button, panel)
        private static readonly string[][] Tabs =
        {
            new[] { "fab", "TabFab", "FabPanel" }, new[] { "fam", "TabFam", "FamPanel" },
            new[] { "floor", "TabFloor", "FloorPanel" }, new[] { "svc", "TabSvc", "SvcPanel" },
        };

        private const int WatchdogSeconds = 20;
        private static readonly string[] JobButtons = { "BtnRehost", "BtnExtend", "BtnPlace", "BtnRodCatsFab", "BtnInspectLock" };
        private static readonly string[][] Checks =
        {
            new[] { "ChkReplace", "rehost_replace" }, new[] { "ChkExtendAfter", "extend_after" },
            new[] { "ChkFloors", "ext_floors" }, new[] { "ChkFraming", "ext_framing" },
            new[] { "ChkRoofs", "ext_roofs" }, new[] { "ChkDims", "dims" },
            new[] { "ChkSkipExisting", "skip_existing" }, new[] { "ChkExtendPlace", "extend_place" },
            new[] { "ChkDebug", "debug" },
        };

        // the Python _STATE
        private static FhaWindow current;
        private static ExternalEvent evt;
        private static FhaHandler handler;
        private static bool viewHooked;

        private static string[] TabRow(string key)
        {
            foreach (string[] t in Tabs)
                if (t[0] == key) return t;
            return null;
        }

        // ================================================================ view hook
        /// <summary>
        /// Revit's ViewActivated (hooked once per session): light the dimension placer only in a floor plan.
        /// </summary>
        private static void ViewActivated(object sender, Autodesk.Revit.UI.Events.ViewActivatedEventArgs args)
        {
            try
            {
                FhaWindow w = current;
                if (w != null)
                {
                    bool ok = HfamRevit.IsFloorPlan(args.CurrentActiveView);
                    foreach (FamTab t in w.FamTabs()) t.SetViewOk(ok);
                }
            }
            catch (Exception)
            {
            }
        }

        public static void HookViews(UIApplication uiapp)
        {
            if (viewHooked) return;
            try
            {
                uiapp.ViewActivated += ViewActivated;
                viewHooked = true;
            }
            catch (Exception)
            {
            }
        }

        // ================================================================ state
        public readonly UIApplication UiApp;
        public Window Win { get; private set; }
        public FhaChrome Chrome { get; private set; }
        public FhaDrawer Drawer { get; private set; }
        public FhaSettings Settings { get; private set; }
        public string Mode { get; private set; }
        public bool Busy { get; private set; }
        public string LastDebug { get; set; } = "";
        private DispatcherTimer timer;
        public string ThemeName { get; private set; }
        public string EggRoute = "";
        private Action<object, string> quietCb;

        private sealed class Pending
        {
            public FhaJob Job;
            public Action<FhaSettings> Extra;
        }

        private Pending pending;
        private double? foldContent;
        public string Tab { get; set; } = "fab";
        public List<string> Worksets { get; private set; }
        public List<string> DimTypeNames { get; private set; }

        /// <summary>How long each stage of the last window open took - first lines of every debug file and of Copy debug.</summary>
        public static string OpenTiming = "";
        private List<string> wsValues = new List<string>();
        public DimViewsUI DimUi { get; private set; }
        public FamTab Fam;
        public FamTab Flr;
        public SvcTab Svc;
        private int nButtons;
        private bool built;
        // the Finish Selection card (FhaFinish): what it shows, and the window height given to it
        private FinishRequest finishReq;
        private double finishGrew;        // px the window grew for the card (0 when it did not)
        private double finishShift;       // px the window was lifted to make room for it
        private double finishTop;         // where the window stood after that
        private readonly Action<FinishRequest> finishListener;

        Autodesk.Revit.UI.UIApplication IFamOwner.UiApp { get { return UiApp; } }

        public FhaWindow(UIApplication uiapp)
        {
            UiApp = uiapp;
            var lap = new OpenLaps();
            Win = FhaUi.LoadWindow();
            lap.Mark("layout");
            Chrome = new FhaChrome(Win);
            Drawer = null;
            Settings = new FhaSettings(FhaCore.LoadSettings());
            string theme;
            Mode = Settings.TryGetValue("theme", out theme) && theme != null ? theme : "auto";
            if (Array.IndexOf(FhaCore.ThemeModes, Mode) < 0) Mode = "auto";
            Busy = false;
            ThemeName = "dark";
            Autodesk.Revit.DB.Document doc = null;
            try
            {
                doc = uiapp.ActiveUIDocument.Document;
            }
            catch (Exception)
            {
            }
            lap.Mark("settings");
            Worksets = doc != null ? FhaRevit.UserWorksets(doc).Select(w => w.Key).ToList() : new List<string>();
            lap.Mark("worksets");
            DimTypeNames = new List<string>();
            try
            {
                if (doc != null) DimTypeNames = FhaRevit.LinearDimensionTypes(doc).Select(d => d.Key).ToList();
            }
            catch (Exception)
            {
            }
            lap.Mark("dimension types");
            DimUi = new DimViewsUI(this);   // prompts and the Dimension views picker, for the jobs
            Fam = new FamTab(this, doc);
            Flr = new FamTab(this, doc, "floor", Fam.Items);
            Svc = new SvcTab(this);   // Hanger Service Type Assigner
            lap.Mark("family types");
            FillLists();
            lap.Mark("fabrication buttons");
            LoadControls();
            foreach (FamTab t in FamTabs()) t.Load(Settings);
            Svc.Load(Settings);
            lap.Mark("controls");
            Drawer = new FhaDrawer(Win, Chrome, (FrameworkElement)C("HeaderBar"), (FrameworkElement)C("ShrinkBtn"),
                                   (UIElement)C("ShrinkIcon"), (UIElement)C("ExpandIcon"), body: BodyParts, showBody: ShowBody,
                                   grips: (UIElement)C("GripLayer"));
            Drawer.Landed = SyncFinish;   // a card that came or went while the window was parked is settled once it has landed
            finishListener = OnFinishRequest;
            Wire();
            foreach (FamTab tab in FamTabs())
                tab.Wire();   // OpenDoc stays set until the window is on screen (ContentRendered): previews wait till then
            Svc.Wire();
            // open on the tab that was open last time - except the Service Type Assigner, which reads the model: that opens on Family Hangers
            string startTab = Sget(Settings, "active_tab", "fab");
            ShowTab(startTab == "svc" ? "fam" : startTab);
            FhaUi.SetIcon(Win);
            Chrome.AddGrips((Panel)C("GripLayer"));
            FhaUi.OwnWindow(Win, uiapp);
            EggRoute = FhaUi.AttachEgg(Win, (FrameworkElement)C("Logo"), () => ThemeName);
            ((TextBlock)C("VerTxt")).Text = "v" + FhaCore.Version;
            Theme();
            lap.Mark("wiring and theme");
            OpenTiming = lap.Text();
            built = true;   // from here on a tab change is saved
        }

        /// <summary>Stopwatch laps for the window open: "layout 310 ms, settings 4 ms, ... (total 820 ms)".</summary>
        private sealed class OpenLaps
        {
            private readonly System.Diagnostics.Stopwatch sw = System.Diagnostics.Stopwatch.StartNew();
            private long last;
            private readonly List<string> parts = new List<string>();

            public void Mark(string what)
            {
                long now = sw.ElapsedMilliseconds;
                parts.Add(what + " " + (now - last) + " ms");
                last = now;
            }

            public string Text()
            {
                return string.Join(", ", parts) + " (total " + sw.ElapsedMilliseconds + " ms)";
            }
        }

        private static string Sget(IDictionary<string, string> s, string key, string dflt)
        {
            string v;
            return s != null && s.TryGetValue(key, out v) && v != null ? v : dflt;
        }

        public object C(string name)
        {
            return Win.FindName(name);
        }

        // ISvcOwner wants the element typed; IFamOwner wants an object.
        System.Windows.FrameworkElement ISvcOwner.C(string name)
        {
            return Win.FindName(name) as System.Windows.FrameworkElement;
        }

        private T C<T>(string name) where T : class
        {
            return (T)Win.FindName(name);
        }

        // ---- population
        private void FillLists()
        {
            var labels = new List<string>();
            var dims = DimTypeNames ?? new List<string>();
            try
            {
                Autodesk.Revit.DB.Document doc = UiApp.ActiveUIDocument.Document;
                labels = FhaRevit.HangerButtonLabels(doc);
            }
            catch (Exception)
            {
            }
            var cb = C<ComboBox>("CmbButton");
            cb.Items.Add("(automatic - matches the duct size)");
            foreach (string n in labels) cb.Items.Add(n);
            var cd = C<ComboBox>("CmbDimType");
            cd.Items.Add("(default dimension type)");
            foreach (string n in dims) cd.Items.Add(n);
            var cs = C<ComboBox>("CmbScope");
            cs.Items.Add("Selected run only");
            cs.Items.Add("Whole connected system");
            nButtons = labels.Count;
        }

        private void LoadControls()
        {
            FhaSettings s = Settings;
            foreach (string[] c in Checks) C<ToggleButton>(c[0]).IsChecked = FhaCore.AsBool(s, c[1]);
            C<TextBox>("TxtRadius").Text = Sget(s, "search_radius", "1500");
            C<TextBox>("TxtSpacing").Text = Sget(s, "spacing", "2000");
            Select(C<ComboBox>("CmbButton"), Sget(s, "button", ""));
            Select(C<ComboBox>("CmbDimType"), Sget(s, "dim_type", ""));
            C<ComboBox>("CmbScope").SelectedIndex = Sget(s, "scope", "run") == "system" ? 1 : 0;
            wsValues = FhaUi.FillWorksetCombo(C<ComboBox>("CmbWorkset"), Worksets, Sget(s, "workset", ""));
            if (nButtons == 0) C<TextBlock>("StatusTxt").Text = "No hanger buttons found in the loaded fabrication services";
        }

        private static void Select(ComboBox combo, string value)
        {
            for (int i = 0; i < combo.Items.Count; i++)
            {
                if (value.Length > 0 && (combo.Items[i] as string) == value)
                {
                    combo.SelectedIndex = i;
                    return;
                }
            }
            combo.SelectedIndex = 0;
        }

        private FhaSettings Gather()
        {
            var s = new FhaSettings(Settings);
            foreach (string[] c in Checks) s[c[1]] = C<ToggleButton>(c[0]).IsChecked == true ? "1" : "0";
            s["search_radius"] = FhaCore.NumText(FhaCore.ParseMm(C<TextBox>("TxtRadius").Text, 1500.0));
            s["spacing"] = FhaCore.NumText(Math.Max(100.0, FhaCore.ParseMm(C<TextBox>("TxtSpacing").Text, 2000.0)));
            var cb = C<ComboBox>("CmbButton");
            s["button"] = cb.SelectedIndex <= 0 ? "" : Convert.ToString(cb.SelectedItem);
            var cd = C<ComboBox>("CmbDimType");
            s["dim_type"] = cd.SelectedIndex <= 0 ? "" : Convert.ToString(cd.SelectedItem);
            s["scope"] = C<ComboBox>("CmbScope").SelectedIndex == 1 ? "system" : "run";
            if (wsValues.Count > 0) s["workset"] = FhaCore.WorksetValue(wsValues, C<ComboBox>("CmbWorkset").SelectedIndex);
            s["theme"] = Mode;
            s["active_tab"] = Tab;
            foreach (FamTab t in FamTabs()) t.Gather(s);
            if (Svc != null) Svc.Gather(s);
            return s;
        }

        /// <summary>The family tabs (Family Hangers, Family Floor Support).</summary>
        public List<FamTab> FamTabs()
        {
            var o = new List<FamTab>();
            if (Fam != null) o.Add(Fam);
            if (Flr != null) o.Add(Flr);
            return o;
        }

        /// <summary>One tab saved a family's settings: the other re-reads the file.</summary>
        public void FamilySettingsSaved(FamTab by)
        {
            foreach (FamTab t in FamTabs())
                if (!ReferenceEquals(t, by)) t.ReloadFamilies();
        }

        /// <summary>Python _save: gather every control, keep it, write the settings file.</summary>
        public void Save()
        {
            try
            {
                Settings = Gather();
                FhaCore.SaveSettings(Settings);
            }
            catch (Exception)
            {
            }
        }

        // ---- theme
        private void Theme()
        {
            string name = FhaUi.ApplyPalette(Win, Mode);
            ThemeName = name;
            string label = Mode == "auto" ? "Auto (" + name + ")" : Mode == "dark" ? "Dark" : "Light";
            ((ContentControl)C("ThemeBtn")).Content = label;
        }

        private void CycleTheme(object sender, RoutedEventArgs e)
        {
            try
            {
                Mode = FhaCore.NextMode(Mode);
                Theme();
                Save();
            }
            catch (Exception)
            {
            }
        }

        // ---- wiring (every handler guards itself: WPF swallows exceptions)
        private void Wire()
        {
            ((UIElement)C("HeaderBar")).MouseLeftButtonDown += HeaderDown;
            ((ButtonBase)C("ThemeBtn")).Click += CycleTheme;
            ((ButtonBase)C("FullBtn")).Click += FullClick;
            ((ButtonBase)C("ShrinkBtn")).Click += ShrinkClick;
            ((ButtonBase)C("CloseBtn")).Click += CloseClick;
            ((ButtonBase)C("BtnClose")).Click += CloseClick;
            ((ButtonBase)C("BtnCopyDebug")).Click += CopyDebug;
            ((ButtonBase)C("BtnInspectLock")).Click += InspectLockClick;
            ((ButtonBase)C("BtnRehost")).Click += RehostClick;
            ((ButtonBase)C("BtnExtend")).Click += ExtendClick;
            ((ButtonBase)C("BtnPlace")).Click += PlaceClick;
            ((ButtonBase)C("BtnRodCatsFab")).Click += RodCatsClick;
            ((ButtonBase)C("BtnFinish")).Click += FinishClick;
            FhaFinish.Listener = finishListener;
            ((ButtonBase)C("TabFab")).Click += TabFabClick;
            ((ButtonBase)C("TabFam")).Click += TabFamClick;
            ((ButtonBase)C("TabFloor")).Click += TabFloorClick;
            ((ButtonBase)C("TabSvc")).Click += TabSvcClick;
            Win.KeyDown += Key;
            Win.ContentRendered += ContentRendered;
            Win.Closed += Closed;
        }

        // ---- tabs
        private void ShowTab(string name)
        {
            Tab = TabRow(name) != null ? name : "fab";
            ApplyTab();
            Fit(false);
            if (Tab == "svc" && Svc != null) Svc.Shown();   // reads the hangers the first time
            if (built) Save();   // the open tab is remembered for next time
        }

        private void ApplyTab()
        {
            foreach (string[] t in Tabs)
            {
                bool on = t[0] == Tab;
                ((UIElement)C(t[2])).Visibility = on ? Visibility.Visible : Visibility.Collapsed;
                FhaUi.SetStyle((FrameworkElement)C(t[1]), on ? "TabActive" : "Tab");
            }
        }

        // ---- shrink to the taskbar (drawer)
        /// <summary>Everything below the title bar, collapsed while shrunk.</summary>
        private IEnumerable<UIElement> BodyParts()
        {
            var names = new List<string> { "TabsBar", "LogBox", "FinishCard", "FooterBar" };
            names.AddRange(Tabs.Select(t => t[2]));
            return names.Select(n => (UIElement)C(n)).ToList();
        }

        private void ShowBody()
        {
            foreach (string n in new[] { "TabsBar", "LogBox", "FooterBar" }) ((UIElement)C(n)).Visibility = Visibility.Visible;
            ApplyTab();
            // the Finish Selection card: back only if the window's saved height already holds it (SyncFinish does the rest once landed)
            if (finishReq != null && finishGrew > 0.0) ((UIElement)C("FinishCard")).Visibility = Visibility.Visible;
        }

        // ---- the Finish Selection card
        /// <summary>FhaFinish.Listener: the card is wanted (request) or gone (null). Guarded by the window's Dispatcher.</summary>
        private void OnFinishRequest(FinishRequest req)
        {
            try
            {
                Dispatcher d = Win.Dispatcher;
                if (!d.CheckAccess())
                {
                    d.Invoke(new Action(() => ApplyFinish(req)));
                    return;
                }
                ApplyFinish(req);
            }
            catch (Exception)
            {
            }
        }

        private void ApplyFinish(FinishRequest req)
        {
            finishReq = req;
            if (req != null)
            {
                C<TextBlock>("FinishEyebrow").Text = req.Eyebrow ?? "";
                C<TextBlock>("FinishTitle").Text = req.Title ?? "";
                C<TextBlock>("FinishDetail").Text = req.Detail ?? "";
                C<TextBlock>("FinishHint").Text = req.Hint ?? "";
            }
            ((UIElement)C("BtnFinish")).IsEnabled = req != null;   // not tied to SetBusy: the pick is part of the running job
            SyncFinish();
        }

        /// <summary>
        /// Bring the card and the window height in line with whether a pick is waiting. Shown only while the window is
        /// open and still (not parked, not sliding); the window grows by the card and shrinks back by the same amount.
        /// A card that came or went while the window was parked changes the height it will return to instead.
        /// </summary>
        private void SyncFinish()
        {
            try
            {
                var card = (FrameworkElement)C("FinishCard");
                FhaDrawer dr = Drawer;
                bool shrunk = dr != null && dr.Shrunk;
                bool moving = dr != null && dr.Moving;
                if (finishReq == null)
                {
                    card.Visibility = Visibility.Collapsed;
                    if (finishGrew != 0.0)
                    {
                        if (shrunk)
                        {
                            dr.AdjustSavedHeight(-finishGrew);
                            finishGrew = 0.0;
                            finishShift = 0.0;
                        }
                        else if (!moving)
                        {
                            ShrinkForFinish();
                        }
                    }
                    return;
                }
                if (shrunk || moving) return;   // parked: no card; it is shown when the window has landed
                if (card.Visibility != Visibility.Visible)
                {
                    card.Visibility = Visibility.Visible;
                    if (finishGrew == 0.0) GrowForFinish(card);
                }
            }
            catch (Exception)
            {
            }
        }

        private void GrowForFinish(FrameworkElement card)
        {
            Window win = Win;
            if (Chrome.Full || win.ActualHeight <= 0) return;
            double w = ((FrameworkElement)C("LogBox")).ActualWidth;   // the card has the log box's margins
            card.Measure(new Size(w + card.Margin.Left + card.Margin.Right, double.PositiveInfinity));
            double want = card.DesiredSize.Height;   // includes its margin
            Rect wa = Chrome.WorkArea();
            double h, top;
            FhaCore.FitHeight(win.ActualHeight, 0.0, want, win.MinHeight, win.Top, wa.Top, wa.Height * FhaUi.MaxScreen, out h, out top);
            double grew = h - win.ActualHeight;
            if (grew <= 0.5) return;   // no room: the tab scrolls instead
            finishGrew = grew;
            finishShift = win.Top - top;
            finishTop = top;
            if (Math.Abs(top - win.Top) > 0.5) win.Top = top;
            win.Height = h;
        }

        private void ShrinkForFinish()
        {
            double grew = finishGrew, shift = finishShift;
            finishGrew = 0.0;
            finishShift = 0.0;
            if (grew <= 0.0) return;
            Window win = Win;
            if (Chrome.Full)
            {
                Chrome.AdjustSavedHeight(-grew);
                return;
            }
            if (win.ActualHeight <= 0) return;
            double h = Math.Max(win.MinHeight, win.ActualHeight - grew);
            double top = win.Top;
            if (shift > 0.5 && Math.Abs(win.Top - finishTop) < 1.0)   // lifted to make room and not moved since: put it back where it was
            {
                Rect wa = Chrome.WorkArea();
                top = Math.Max(wa.Top, Math.Min(win.Top + shift, wa.Top + wa.Height - h));
            }
            win.Height = h;
            if (Math.Abs(top - win.Top) > 0.5) win.Top = top;
        }

        /// <summary>Finish Selection: once per pick, then it waits for the pick to end (the card goes with it).</summary>
        private void FinishClick(object sender, RoutedEventArgs e)
        {
            var btn = (UIElement)C("BtnFinish");
            try
            {
                if (!FhaFinish.Armed || FhaFinish.Pressed) return;
                btn.IsEnabled = false;
                if (!FhaFinish.Press() && FhaFinish.Armed && !FhaFinish.Pressed) btn.IsEnabled = true;   // it could not be started: try again
            }
            catch (Exception)
            {
                try
                {
                    if (FhaFinish.Armed && !FhaFinish.Pressed) btn.IsEnabled = true;
                }
                catch (Exception)
                {
                }
            }
        }

        private void ShrinkClick(object sender, RoutedEventArgs e)
        {
            Drawer.Toggle();
        }

        /// <summary>
        /// A tool is opening or folding by <paramref name="delta"/>: slide the window with it so its bottom stays at
        /// the lowest tool - never taller than the screen allows (the tab scrolls then), never shorter than the minimum.
        /// </summary>
        public void ResizeForFold(double delta)
        {
            try
            {
                Window win = Win;
                string[] row = TabRow(Tab) ?? TabRow("fam");
                var sc = (ScrollViewer)C(row[2]);
                if (Chrome.Full || win.ActualHeight <= 0 || Drawer.Shrunk || Drawer.Moving) return;
                double now = foldContent != null ? foldContent.Value : ((FrameworkElement)sc.Content).ActualHeight;
                foldContent = now + delta;
                double have = sc.ViewportHeight != 0.0 ? sc.ViewportHeight : sc.ActualHeight;
                Rect wa = Chrome.WorkArea();
                double h, top;
                FhaCore.FitHeight(win.ActualHeight, have, foldContent.Value, win.MinHeight, win.Top, wa.Top,
                                  wa.Height * FhaUi.MaxScreen, out h, out top);
                if (Math.Abs(top - win.Top) > 0.5) win.Top = top;
                FhaUi.AnimateHeight(win, h, FoldResized);
            }
            catch (Exception)
            {
                foldContent = null;
            }
        }

        private void FoldResized()
        {
            foldContent = null;
        }

        /// <summary>Grow or shrink the window to show every tool on the open tab.</summary>
        public void Fit(bool growOnly)
        {
            if (Drawer != null && (Drawer.Shrunk || Drawer.Moving)) return;
            string[] row = TabRow(Tab) ?? TabRow("fab");
            Chrome.FitTo((ScrollViewer)C(row[2]), growOnly);
        }

        private void ContentRendered(object sender, EventArgs e)
        {
            Fit(false);
            // the window is on screen: now read the chosen families' previews (they were left out of the open to make it quicker)
            try
            {
                foreach (FamTab t in FamTabs()) t.OpenDoc = null;
                if (!Busy) (Tab == "floor" ? Flr : Fam).RetryPreview();
            }
            catch (Exception)
            {
            }
        }

        private void TabFabClick(object sender, RoutedEventArgs e)
        {
            ShowTab("fab");
        }

        private void TabFamClick(object sender, RoutedEventArgs e)
        {
            ShowTab("fam");
        }

        private void TabFloorClick(object sender, RoutedEventArgs e)
        {
            ShowTab("floor");
        }

        private void TabSvcClick(object sender, RoutedEventArgs e)
        {
            ShowTab("svc");
        }

        public void Status(string text)
        {
            try
            {
                C<TextBlock>("StatusTxt").Text = text;
            }
            catch (Exception)
            {
            }
        }

        private void HeaderDown(object sender, MouseButtonEventArgs e)
        {
            if (Drawer.Shrunk)
            {
                try
                {
                    if (e.ClickCount == 2)
                    {
                        Drawer.Expand();   // double-click the floating bar opens it again
                        return;
                    }
                }
                catch (Exception)
                {
                }
                if (Busy) return;   // no DragMove (a modal loop) while a job holds Revit's API context
            }
            Chrome.HeaderDown(e, C("Logo"));
        }

        private void FullClick(object sender, RoutedEventArgs e)
        {
            if (Drawer.Shrunk)
            {
                Drawer.Expand();
                return;
            }
            Chrome.ToggleFull();
        }

        private void CloseClick(object sender, RoutedEventArgs e)
        {
            Close();
        }

        /// <summary>Inspect lock (diagnostic): always runs with the debug file on, so Copy debug holds everything.</summary>
        private void InspectLockClick(object sender, RoutedEventArgs e)
        {
            try
            {
                StartJob((u, s, l) => HfamRevit.JobInspectLock(u, s, l), s => { s.Prompts = DimUi; s["debug"] = "1"; });
            }
            catch (Exception)
            {
            }
        }

        private void RehostClick(object sender, RoutedEventArgs e)
        {
            Start("rehost");
        }

        private void ExtendClick(object sender, RoutedEventArgs e)
        {
            Start("extend");
        }

        private void PlaceClick(object sender, RoutedEventArgs e)
        {
            Start("place");
        }

        /// <summary>The "Rod targets..." window: which categories rods can run up to besides floors, framing and roofs.</summary>
        private void RodCatsClick(object sender, RoutedEventArgs e)
        {
            RodCatsDialog.Run(this);
        }

        private void Key(object sender, KeyEventArgs e)
        {
            try
            {
                if (Drawer.Key(e))   // Ctrl+Shift+H; Esc / Enter / F11 open a parked window
                {
                    e.Handled = true;
                    return;
                }
                string k = e.Key.ToString();
                if (k == "F11")
                {
                    Chrome.ToggleFull();
                }
                else if (k == "F5" && Tab == "svc" && !Busy)
                {
                    Svc.Scan();   // read the hangers again
                    e.Handled = true;
                }
                // Escape never closes the tool: it is pressed to leave Revit picks
            }
            catch (Exception)
            {
            }
        }

        public void Close()
        {
            Save();
            try
            {
                Win.Close();
            }
            catch (Exception)
            {
            }
        }

        private void Closed(object sender, EventArgs e)
        {
            Save();   // however the window closed (the Close buttons, Alt+F4, Revit shutting down): keep the settings and the open tab
            current = null;
            StopTimer();
            // the Finish Selection card: no stale armed state, and nobody listening for this window
            finishReq = null;
            finishGrew = 0.0;
            if (ReferenceEquals(FhaFinish.Listener, finishListener)) FhaFinish.Listener = null;
        }

        private void CopyDebug(object sender, RoutedEventArgs e)
        {
            try
            {
                var keys = Gather().ToList();
                keys.Sort((a, b) => string.CompareOrdinal(a.Key, b.Key));
                string text = "Hanger Automation " + FhaCore.Version + "\nwindow open: " + OpenTiming + "\n\n" +
                              (LastDebug.Length > 0 ? LastDebug : "(nothing run yet)") + "\n\nSettings:\n" +
                              string.Join("\n", keys.Select(kv => kv.Key + "=" + kv.Value)) + "\n\nFamily tabs:\n" +
                              string.Join("\n\n", FamTabs().Select(t => t.DebugText()));
                Clipboard.SetText(text);
                C<TextBlock>("StatusTxt").Text = "Debug copied to the clipboard";
            }
            catch (Exception)
            {
            }
        }

        // ---- running a job
        private void SetBusy(bool busy, string status)
        {
            Busy = busy;
            foreach (string n in JobButtons) ((UIElement)C(n)).IsEnabled = !busy;
            foreach (FamTab t in FamTabs()) t.SetBusy(busy);
            if (Svc != null) Svc.SetBusy(busy);
            C<TextBlock>("StatusTxt").Text = status;
        }

        private void Start(string kind)
        {
            FhaJob job;
            if (kind == "rehost") job = (u, s, l) => FhaRevit.JobRehost(u, s, l);
            else if (kind == "extend") job = (u, s, l) => FhaRevit.JobExtend(u, s, l);
            else job = (u, s, l) => FhaRevit.JobPlace(u, s, l);
            StartJob(job, JobExtra);
        }

        public void JobExtra(FhaSettings s)
        {
            s.Prompts = DimUi;
        }

        private bool Queue(FhaJob job, FhaSettings settings, bool quiet, string status)
        {
            FhaHandler h = handler;
            h.Owner = this;
            h.Settings = settings;
            h.Job = job;
            h.Quiet = quiet;
            h.Started = false;
            SetBusy(true, status);
            string answer = evt.Raise().ToString();
            if (answer == "Accepted" || answer == "Pending")
            {
                StartTimer();
                return true;
            }
            h.Job = null;
            quietCb = null;
            SetBusy(false, "Revit refused the request (" + answer + ") - try again");
            return false;
        }

        /// <summary>A tool: picks, writes, results box, debug file.</summary>
        public bool StartJob(FhaJob job, Action<FhaSettings> extra = null)
        {
            try
            {
                if (Busy)
                {
                    if (quietCb != null)
                    {
                        pending = new Pending { Job = job, Extra = extra };   // a quick read is in flight: run straight after it
                        Status("Starting as soon as Revit has finished reading...");
                        return true;
                    }
                    Status("Still working on the last request...");
                    return false;
                }
                Save();
                var settings = new FhaSettings(Settings);
                if (extra != null) extra(settings);
                quietCb = null;
                return Queue(job, settings, false, "Working... pick in the model if asked (Esc cancels the pick)");
            }
            catch (Exception ex)
            {
                SetBusy(false, "Could not start - see Copy debug");
                LastDebug = ex.ToString();
                return false;
            }
        }

        /// <summary>A read: the answer goes to callback(result, error). False if busy.</summary>
        public bool StartQuiet(FhaJob job, Action<object, string> callback, string status = "Reading...")
        {
            try
            {
                if (Busy) return false;
                quietCb = callback;
                return Queue(job, new FhaSettings(Settings), true, status);
            }
            catch (Exception)
            {
                quietCb = null;
                SetBusy(false, "Ready");
                return false;
            }
        }

        private void StartTimer()
        {
            StopTimer();
            try
            {
                timer = new DispatcherTimer();
                timer.Interval = TimeSpan.FromSeconds(WatchdogSeconds);
                timer.Tick += Watchdog;
                timer.Start();
            }
            catch (Exception)
            {
                timer = null;
            }
        }

        private void StopTimer()
        {
            try
            {
                if (timer != null) timer.Stop();
            }
            catch (Exception)
            {
            }
            timer = null;
        }

        /// <summary>Frees the window if Revit never started the job (it was busy).</summary>
        private void Watchdog(object sender, EventArgs e)
        {
            StopTimer();
            FhaHandler h = handler;
            if (Busy && h != null && !h.Started)
            {
                h.Job = null;
                quietCb = null;
                pending = null;
                SetBusy(false, "Revit was busy and did not run it - click again");
            }
        }

        /// <summary>The handler's answer, on the window's dispatcher.</summary>
        public void Finished(object res, string err)
        {
            StopTimer();
            if (FhaFinish.Armed) FhaFinish.Disarm("job ended");   // belt and braces: the card never outlives its job
            if (quietCb != null)
            {
                Action<object, string> cb = quietCb;
                quietCb = null;
                SetBusy(false, "Ready");
                try
                {
                    cb(res, err);
                }
                catch (Exception ex)
                {
                    LastDebug = ex.ToString();
                }
                if (pending != null && !Busy)
                {
                    Pending p = pending;
                    pending = null;
                    StartJob(p.Job, p.Extra);
                }
                foreach (FamTab t in FamTabs())   // a tab whose preview read could not start gets its turn now
                {
                    if (!Busy) t.RetryPreview();
                }
                if (!Busy) Svc.RetryScan();
                return;
            }
            FhaHandler h = handler;
            if (h != null && h.Log != null) LastDebug = h.Log.Text();
            var lines = new List<string>();
            string status;
            JobResult jr = res as JobResult;
            if (!string.IsNullOrEmpty(err))
            {
                lines.Add("Something went wrong - press Copy debug and send it over.");
                lines.Add(err);
                status = "Failed - see the results box";
            }
            else if (jr != null)
            {
                lines.Add(jr.Title + ": " + jr.Done + " done, " + jr.Skipped + " skipped, " + jr.Failed + " failed");
                lines.AddRange(jr.Lines);
                status = jr.Title + ": " + jr.Done + " done";
            }
            else
            {
                status = "Ready";
            }
            try
            {
                C<TextBox>("LogBox").Text = string.Join("\n", lines);
                SetBusy(false, status);
                Win.Activate();
            }
            catch (Exception)
            {
            }
            try
            {
                Svc.AfterJob();   // the service type tab reads again after it wrote Comments
            }
            catch (Exception)
            {
            }
        }

        // ================================================================= entry
        /// <summary>Open the window, or bring the open one forward.</summary>
        public static FhaWindow Show(UIApplication uiapp)
        {
            Window w = FhaUi.Parked();
            if (w != null)
            {
                try
                {
                    w.Activate();
                    return null;
                }
                catch (Exception)
                {
                }
            }
            if (handler == null)
            {
                handler = new FhaHandler();
                evt = ExternalEvent.Create(handler);
            }
            var fw = new FhaWindow(uiapp);
            current = fw;
            HookViews(uiapp);
            FhaUi.Park(fw.Win);
            fw.Win.Show();
            return fw;
        }
    }
}
