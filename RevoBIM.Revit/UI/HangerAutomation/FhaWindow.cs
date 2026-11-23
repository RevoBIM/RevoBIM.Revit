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
    public sealed partial class FhaWindow : IFhaHost, IFamOwner, ISvcOwner
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
