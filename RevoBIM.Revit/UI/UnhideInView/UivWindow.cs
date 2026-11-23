using System;
using System.Collections.Generic;
using System.Data;
using System.Diagnostics;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Data;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Threading;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using RevoBIM.Helpers;
using RevoBIM.Tools.UnhideInView;

using Binding = System.Windows.Data.Binding;
using CheckBox = System.Windows.Controls.CheckBox;
using Control = System.Windows.Controls.Control;
using ToggleButton = System.Windows.Controls.Primitives.ToggleButton;
using DataGrid = System.Windows.Controls.DataGrid;
using Grid = System.Windows.Controls.Grid;
using Panel = System.Windows.Controls.Panel;
using TextBox = System.Windows.Controls.TextBox;
using Visibility = System.Windows.Visibility;

namespace RevoBIM.UI.UnhideInView
{
    /// <summary>One piece of work for Revit's API thread.</summary>
    internal sealed class UivJob
    {
        public string Name;
        public Func<UIApplication, object> Work;
        public Action<object> Done;
        public Action<string> Fail;
        public bool User;
    }

    /// <summary>
    /// Queue, raise, return. Every read and write goes out through one ExternalEvent; nothing waits for it. A 'Pending' answer
    /// means an earlier request is still waiting - the new job queues behind it and the queue is never cleared.
    /// </summary>
    internal sealed class UivRunner : IExternalEventHandler
    {
        private const double WatchdogSeconds = 20.0;

        private readonly UivCore.DebugLog log;
        private readonly List<UivJob> queue = new List<UivJob>();
        private ExternalEvent externalEvent;
        private DateTime? raisedAt;

        public Dispatcher Dispatcher;

        public UivRunner(UivCore.DebugLog log) { this.log = log; }

        public void CreateEvent() { externalEvent = ExternalEvent.Create(this); }

        public string GetName() { return "RevoBIM Unhide in View"; }

        public bool Submit(UivJob job)
        {
            lock (queue) queue.Add(job);
            if (raisedAt != null)
            {
                log.Add("Queued behind a pending request: " + job.Name);
                return true;
            }
            return Raise(job);
        }

        private bool Raise(UivJob job)
        {
            string status;
            try { status = externalEvent.Raise().ToString(); } catch (Exception err) { status = "Error " + err.Message; }
            if (status == "Accepted" || status == "Pending")
            {
                raisedAt = DateTime.UtcNow;
                return true;
            }
            log.Add("ExternalEvent.Raise() answered " + status);
            if (job != null)
            {
                bool removed;
                lock (queue) removed = queue.Remove(job);
                if (removed) Post(() => job.Fail?.Invoke("Revit did not take the request (" + status + "). Try again."));
            }
            return false;
        }

        public void Execute(UIApplication uiapp)
        {
            raisedAt = null;
            List<UivJob> jobs;
            lock (queue)
            {
                jobs = new List<UivJob>(queue);
                queue.Clear();
            }
            foreach (UivJob job in jobs)
            {
                object payload;
                try
                {
                    payload = job.Work(uiapp);
                }
                catch (Exception err)
                {
                    UivJob j = job;
                    string text = err.ToString();
                    Post(() => j.Fail?.Invoke(text));
                    continue;
                }
                UivJob done = job;
                Post(() => done.Done?.Invoke(payload));
            }
            bool more;
            lock (queue) more = queue.Count > 0;
            if (more) Raise(null);
        }

        /// <summary>True when a request had gone unanswered for too long and was raised again.</summary>
        public bool Watchdog()
        {
            if (raisedAt == null || (DateTime.UtcNow - raisedAt.Value).TotalSeconds < WatchdogSeconds) return false;
            log.Add("Revit has not run the request after " + (DateTime.UtcNow - raisedAt.Value).TotalSeconds.ToString("0") + "s - asking again");
            raisedAt = null;
            bool any;
            lock (queue) any = queue.Count > 0;
            if (any) Raise(null);
            return true;
        }

        private void Post(Action call)
        {
            Action guarded = () =>
            {
                try { call(); } catch (Exception err) { log.Add("Callback failed: " + err); }
            };
            if (Dispatcher != null) Dispatcher.BeginInvoke(guarded);
            else guarded();
        }
    }

    /// <summary>
    /// The Unhide in View window (port of uiv_window.py). Modeless and owned by Revit's main window, so Revit stays usable.
    /// Results come back as callbacks marshalled onto the window's dispatcher.
    /// </summary>
    internal sealed class UivWindow
    {
        private static UivWindow current;

        private static readonly string[] ElemFilterCols = { "id_txt", "category", "ftype", "level", "note" };
        private const int CatViewsPerJob = 20;

        private readonly UIApplication uiapp;
        private readonly UivRunner runner;
        private readonly Dictionary<string, string> settings;
        private readonly UivCore.DebugLog log;
        private readonly Window win;
        private readonly UivFullScreen fullscreen;
        private readonly UivDrawer drawer;

        private bool closed, closeOk, started, loading, suspend, scanInFlight, catJobPending;
        private Document doc;
        private List<UivView> views = new List<UivView>();
        private Dictionary<long, UivView> viewByKey = new Dictionary<long, UivView>();
        private List<UivCategory> cats = new List<UivCategory>();
        private Dictionary<long, string> catNames = new Dictionary<long, string>();
        private Dictionary<long, ElementId> catIds = new Dictionary<long, ElementId>();
        private UivScanner scanner;
        private DateTime scanStarted = DateTime.UtcNow;
        private readonly Dictionary<long, Dictionary<long, ElementId>> hidden = new Dictionary<long, Dictionary<long, ElementId>>();
        private readonly Dictionary<long, Dictionary<long, UivCatState>> catState = new Dictionary<long, Dictionary<long, UivCatState>>();
        private long? focusKey;
        private UivCore.Staging staging = new UivCore.Staging();
        private readonly Dictionary<string, string> elemNotes = new Dictionary<string, string>();
        private readonly Dictionary<long, string> catNotes = new Dictionary<long, string>();
        private readonly Dictionary<string, string> elemFilters = new Dictionary<string, string>();
        private readonly Dictionary<long, DataRow> viewRows = new Dictionary<long, DataRow>();
        private Dictionary<long, DataRow> elemRows = new Dictionary<long, DataRow>();
        private Dictionary<long, DataRow> catRows = new Dictionary<long, DataRow>();
        private int userJobs;
        private DateTime busySince = DateTime.UtcNow;
        private string currentTheme = "dark";
        private Action confirmAction;
        private CheckBox viewAll, elemAll, catAll;
        private DataTable viewTable, elemTable, catTable;
        private readonly DispatcherTimer viewTimer, elemTimer, catTimer, scanTimer, watchTimer;

        // ---------------------------------------------------------------- opening --

        /// <summary>Opens the window, or brings the open one forward.</summary>
        public static void Open(UIApplication uiapp)
        {
            if (current != null && !current.closed)
            {
                try
                {
                    if (current.win.IsVisible)
                    {
                        if (current.win.WindowState == WindowState.Minimized) current.win.WindowState = WindowState.Normal;
                        current.win.Activate();
                        current.log.Add("Opened again while already open - brought forward");
                        return;
                    }
                }
                catch (Exception)
                {
                }
                try { current.closeOk = true; current.win.Close(); } catch (Exception) { }
            }
            Dictionary<string, string> settings = UivCore.LoadSettings();
            var log = new UivCore.DebugLog(UivCore.AsBool(UivCore.Get(settings, "debug")));
            var runner = new UivRunner(log);
            runner.CreateEvent();
            var window = new UivWindow(uiapp, runner, settings, log);
            current = window;
            UivUi.OwnToRevit(window.win, uiapp);
            window.win.Show();
        }

        private UivWindow(UIApplication uiapp, UivRunner runner, Dictionary<string, string> settings, UivCore.DebugLog log)
        {
            this.uiapp = uiapp;
            this.runner = runner;
            this.settings = settings;
            this.log = log;
            log.Add("Unhide in View " + UivCore.Version + " (" + DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + ")");
            log.Add("build: " + UivCore.BuildInfo());
            try { log.Add("revit: " + uiapp.Application.VersionName + " " + uiapp.Application.VersionBuild); } catch (Exception) { }

            win = UivUi.LoadWindow("UnhideInView.xaml");
            runner.Dispatcher = win.Dispatcher;
            fullscreen = new UivFullScreen(win);
            drawer = new UivDrawer(win, C<Border>("HeaderBar"), C<Panel>("RootGrid"), C<Button>("ShrinkBtn"), C<UIElement>("GripLayer"), log, null);

            viewTimer = Timer(220, RefilterViews);
            elemTimer = Timer(220, RefilterElems);
            catTimer = Timer(220, RefilterCats);
            scanTimer = Timer(25, PumpScan);
            watchTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(2) };

            BuildTables();
            ApplySettings();
            Wire();
            ApplyTheme();
            Chrome();
            RefreshButtons();
        }

        private T C<T>(string name) where T : class
        {
            var element = win.FindName(name) as T;
            if (element == null) throw new InvalidOperationException("Layout is missing: " + name);
            return element;
        }

        private DispatcherTimer Timer(int ms, Action fn)
        {
            var t = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(ms) };
            t.Tick += (s, e) =>
            {
                t.Stop();
                Safe(fn);
            };
            return t;
        }

        private static void Restart(DispatcherTimer t)
        {
            t.Stop();
            t.Start();
        }

        /// <summary>A WPF event swallows exceptions silently, so every handler goes through here.</summary>
        private void Safe(Action fn)
        {
            try
            {
                fn();
            }
            catch (Exception err)
            {
                log.Add("Handler error: " + err);
                try { SetStatus("Something went wrong - tick Debug, Copy debug and send it over.", "bad"); } catch (Exception) { }
            }
        }

        private RoutedEventHandler H(Action fn) { return (s, e) => Safe(fn); }

        // ---------------------------------------------------------------- building --

        private DataTable NewTable(params KeyValuePair<string, Type>[] cols)
        {
            var t = new DataTable();
            foreach (var c in cols) t.Columns.Add(c.Key, c.Value);
            t.DefaultView.RowFilter = "vis = '1'";
            return t;
        }

        private static KeyValuePair<string, Type> Col(string name, Type type) { return new KeyValuePair<string, Type>(name, type); }

        private static KeyValuePair<string, Type>[] Common()
        {
            return new[]
            {
                Col("key", typeof(string)), Col("tick", typeof(bool)), Col("note", typeof(string)), Col("warn", typeof(string)),
                Col("bad", typeof(string)), Col("hot", typeof(string)), Col("vis", typeof(string)),
            };
        }

        private void BuildTables()
        {
            viewTable = NewTable(Common().Concat(new[] { Col("name", typeof(string)), Col("nkey", typeof(string)), Col("vtype", typeof(string)),
                Col("cnt", typeof(int)), Col("cnt_txt", typeof(string)) }).ToArray());
            elemTable = NewTable(Common().Concat(new[] { Col("id_txt", typeof(string)), Col("nid", typeof(string)), Col("category", typeof(string)),
                Col("ftype", typeof(string)), Col("level", typeof(string)) }).ToArray());
            catTable = NewTable(Common().Concat(new[] { Col("name", typeof(string)), Col("nkey", typeof(string)), Col("hidden_txt", typeof(string)),
                Col("hidden_n", typeof(int)) }).ToArray());

            DataGrid g = C<DataGrid>("ViewGrid");
            g.Columns.Add(TickCol(OnViewAll, out viewAll));
            g.Columns.Add(TextCol("View", "name", 160, 3.0, "nkey"));
            g.Columns.Add(TextCol("Type", "vtype", 80, 1.0, null));
            g.Columns.Add(StyledCol("Hidden", "cnt_txt", "RbCountText", 64, 0.7, "cnt"));
            g.ItemsSource = viewTable.DefaultView;

            g = C<DataGrid>("ElemGrid");
            g.Columns.Add(TickCol(OnElemAll, out elemAll));
            g.Columns.Add(TextCol(Head("Element ID", "id_txt"), "id_txt", 86, 0.8, "nid"));
            g.Columns.Add(TextCol(Head("Category", "category"), "category", 110, 1.3, null));
            g.Columns.Add(TextCol(Head("Family : Type", "ftype"), "ftype", 150, 2.4, null));
            g.Columns.Add(TextCol(Head("Level", "level"), "level", 80, 1.0, null));
            g.Columns.Add(StyledCol(Head("Note", "note"), "note", "RbNoteText", 110, 1.4, null));
            g.ItemsSource = elemTable.DefaultView;

            g = C<DataGrid>("CatGrid");
            g.Columns.Add(TickCol(OnCatAll, out catAll));
            g.Columns.Add(TextCol("Category", "name", 160, 2.6, "nkey"));
            g.Columns.Add(StyledCol("Hidden in", "hidden_txt", "RbCountText", 70, 0.7, "hidden_n"));
            g.Columns.Add(StyledCol("Note", "note", "RbNoteText", 120, 1.8, null));
            g.ItemsSource = catTable.DefaultView;
        }

        private static void Width(DataGridColumn col, double min, double star)
        {
            col.MinWidth = min;
            col.Width = new DataGridLength(star, DataGridLengthUnitType.Star);
        }

        private DataGridColumn TextCol(object header, string path, double min, double star, string sortPath)
        {
            var col = new DataGridTextColumn { Header = header, Binding = new Binding(path), IsReadOnly = true, SortMemberPath = sortPath ?? path };
            Width(col, min, star);
            Style style = win.TryFindResource("RbCellText") as Style;
            if (style != null) col.ElementStyle = style;
            return col;
        }

        private DataGridColumn StyledCol(object header, string path, string styleKey, double min, double star, string sortPath)
        {
            var f = new FrameworkElementFactory(typeof(TextBlock));
            f.SetBinding(TextBlock.TextProperty, new Binding(path));
            f.SetResourceReference(FrameworkElement.StyleProperty, styleKey);
            var col = new DataGridTemplateColumn
            {
                CellTemplate = new DataTemplate { VisualTree = f },
                Header = header,
                SortMemberPath = sortPath ?? path,
                CanUserSort = true,
            };
            Width(col, min, star);
            return col;
        }

        private DataGridColumn TickCol(Action onAll, out CheckBox header)
        {
            var f = new FrameworkElementFactory(typeof(CheckBox));
            f.SetBinding(ToggleButton.IsCheckedProperty, new Binding("tick") { Mode = BindingMode.TwoWay, UpdateSourceTrigger = UpdateSourceTrigger.PropertyChanged });
            f.SetResourceReference(FrameworkElement.StyleProperty, "RbCheck");
            f.SetValue(FrameworkElement.HorizontalAlignmentProperty, HorizontalAlignment.Center);
            var hdr = new CheckBox { ToolTip = "Tick or untick every row shown" };
            hdr.SetResourceReference(FrameworkElement.StyleProperty, "RbCheck");
            hdr.Click += (s, e) => Safe(onAll);
            header = hdr;
            return new DataGridTemplateColumn
            {
                CellTemplate = new DataTemplate { VisualTree = f },
                Header = hdr,
                Width = new DataGridLength(36),
                CanUserSort = false,
                CanUserResize = false,
            };
        }

        /// <summary>A live heading: the name with a keyword box under it. Typing in the box never sorts - the TextBox takes the mouse.</summary>
        private object Head(string title, string key)
        {
            var sp = new StackPanel();
            var tb = new TextBlock { Text = title };
            tb.SetResourceReference(FrameworkElement.StyleProperty, "RbHeadText");
            var box = new TextBox { Tag = "filter" };
            box.SetResourceReference(FrameworkElement.StyleProperty, "RbHeadSearch");
            box.TextChanged += (s, e) =>
            {
                elemFilters[key] = ((TextBox)s).Text ?? "";
                Restart(elemTimer);
            };
            sp.Children.Add(tb);
            sp.Children.Add(box);
            return sp;
        }

        private void ApplySettings()
        {
            Dictionary<string, string> s = settings;
            win.Width = UivCore.AsDouble(UivCore.Get(s, "width"), 1320, win.MinWidth, 4000);
            win.Height = UivCore.AsDouble(UivCore.Get(s, "height"), 800, win.MinHeight, 3000);
            double split = UivCore.AsDouble(UivCore.Get(s, "split"), 0.56, 0.2, 0.8);
            C<ColumnDefinition>("LeftCol").Width = new GridLength(split, GridUnitType.Star);
            C<ColumnDefinition>("RightCol").Width = new GridLength(1.0 - split, GridUnitType.Star);
            double cs = UivCore.AsDouble(UivCore.Get(s, "cat_split"), 0.34, 0.12, 0.8);
            C<RowDefinition>("ElemRow").Height = new GridLength(1.0 - cs, GridUnitType.Star);
            C<RowDefinition>("CatRow").Height = new GridLength(cs, GridUnitType.Star);
            C<CheckBox>("DebugChk").IsChecked = UivCore.AsBool(UivCore.Get(s, "debug"));
            C<ToggleButton>("OnlyHiddenToggle").IsChecked = UivCore.AsBool(UivCore.Get(s, "only_hidden"));
            C<CheckBox>("ChangeTemplatesChk").IsChecked = UivCore.AsBool(UivCore.Get(s, "change_templates"));
            C<TextBlock>("VersionText").Text = "v" + UivCore.Version;
        }

        private void Wire()
        {
            C<Button>("CloseBtn").Click += H(RequestClose);
            C<Button>("FullScreenBtn").Click += H(OnFullScreen);
            C<Button>("ThemeChip").Click += H(OnThemeChip);
            C<Border>("HeaderBar").MouseLeftButtonDown += (s, e) => Safe(() => OnHeaderDown(e));
            C<Button>("CopyDebugBtn").Click += H(OnCopyDebug);
            C<CheckBox>("DebugChk").Click += H(OnDebug);
            C<Button>("UnhideBtn").Click += H(OnUnhide);
            C<Button>("UnhideViewsBtn").Click += H(OnUnhideViews);
            C<Button>("CurrentViewBtn").Click += H(OnCurrentView);
            C<Button>("RefreshBtn").Click += H(Load);
            C<TextBox>("ViewSearch").TextChanged += (s, e) => Restart(viewTimer);
            C<TextBox>("CatSearch").TextChanged += (s, e) => Restart(catTimer);
            C<ToggleButton>("OnlyHiddenToggle").Click += H(OnOnlyHidden);
            C<CheckBox>("ChangeTemplatesChk").Click += H(OnChangeTemplates);
            C<Button>("ConfirmNoBtn").Click += H(HideConfirm);
            C<Button>("ConfirmYesBtn").Click += H(OnConfirmYes);

            foreach (string name in new[] { "ViewGrid", "ElemGrid", "CatGrid" })
            {
                string which = name == "ViewGrid" ? "view" : name == "ElemGrid" ? "elem" : "cat";
                C<DataGrid>(name).AddHandler(ButtonBase.ClickEvent, new RoutedEventHandler((s, e) => Safe(() => OnGridClick(which, e))));
            }
            C<DataGrid>("ViewGrid").SelectionChanged += (s, e) => Safe(() => OnViewSelected(e));
            C<DataGrid>("ElemGrid").SelectionChanged += (s, e) => Safe(RefreshButtons);
            C<DataGrid>("ViewGrid").MouseDoubleClick += (s, e) => Safe(() => OnViewDouble(e));
            C<DataGrid>("ElemGrid").MouseDoubleClick += (s, e) => Safe(() => OnElemDouble(e));

            win.PreviewKeyDown += (s, e) => Safe(() => OnKey(e));
            win.Activated += (s, e) =>
            {
                try { if (UivCore.NormaliseTheme(UivCore.Get(settings, "theme")) == "follow") ApplyTheme(); } catch (Exception) { }
            };
            win.ContentRendered += (s, e) => Safe(OnRendered);
            win.Closing += (s, e) => OnClosing(e);
            win.Closed += (s, e) => OnClosed();
            watchTimer.Tick += (s, e) => Safe(OnWatchdog);
        }

        private void Chrome()
        {
            try { UivUi.LoadLogo(C<Image>("Logo")); } catch (Exception) { }
            try { UivUi.AddResizeGrips(win, C<Panel>("GripLayer"), fullscreen.Forget); } catch (Exception) { }
            try { EggHook.Attach(win, () => currentTheme, C<Image>("Logo")); } catch (Exception) { }
        }

        // ---------------------------------------------------------------- status, theme, chrome --

        private void SetStatus(string text, string kind = "muted")
        {
            TextBlock st = C<TextBlock>("StatusText");
            st.Text = text ?? "";
            string key = kind == "bad" ? "Red" : kind == "good" ? "Green" : kind == "warn" ? "Orange" : "Muted";
            st.SetResourceReference(TextBlock.ForegroundProperty, key);
        }

        private void ApplyTheme()
        {
            string mode = UivCore.NormaliseTheme(UivCore.Get(settings, "theme"));
            string canvas = mode == "follow" ? UivUi.CanvasTheme() : null;
            currentTheme = UivCore.ResolveTheme(mode, canvas);
            UivUi.ApplyPalette(win, currentTheme);
            string label = UivCore.ThemeLabel(mode);
            C<TextBlock>("ThemeText").Text = label;
            C<Button>("ThemeChip").ToolTip = "Theme: " + label + " (" + currentTheme + "). Click for " + UivCore.ThemeLabel(UivCore.NextTheme(mode)) + ".";
        }

        private void OnThemeChip()
        {
            settings["theme"] = UivCore.NextTheme(UivCore.Get(settings, "theme"));
            UivCore.SaveSettings(settings);
            ApplyTheme();
            log.Add("Theme -> " + settings["theme"] + " (" + currentTheme + ")");
        }

        private void OnFullScreen()
        {
            // while shrunk, full screen means 'give me the window back'
            if (!drawer.IsOpen)
            {
                drawer.Expand(true);
                return;
            }
            fullscreen.Toggle();
        }

        private void OnHeaderDown(MouseButtonEventArgs e)
        {
            DependencyObject src = e.OriginalSource as DependencyObject;
            if (IsWithin(src, C<Image>("Logo")) || Ancestor<ButtonBase>(src) != null) return;
            if (drawer.OnHeaderDown(e)) return;
            if (e.ClickCount == 2)
            {
                fullscreen.Toggle();
                return;
            }
            try
            {
                fullscreen.Forget();
                win.DragMove();
            }
            catch (Exception)
            {
            }
        }

        private static DependencyObject Parent(DependencyObject d)
        {
            if (d == null) return null;
            try
            {
                if (d is Visual || d is System.Windows.Media.Media3D.Visual3D) return VisualTreeHelper.GetParent(d);
                return LogicalTreeHelper.GetParent(d);
            }
            catch (Exception)
            {
                return null;
            }
        }

        private static T Ancestor<T>(DependencyObject element) where T : DependencyObject
        {
            DependencyObject el = element;
            for (int i = 0; i < 60 && el != null; i++)
            {
                var t = el as T;
                if (t != null) return t;
                el = Parent(el);
            }
            return null;
        }

        private static bool IsWithin(DependencyObject element, DependencyObject target)
        {
            DependencyObject el = element;
            for (int i = 0; i < 60 && el != null; i++)
            {
                if (ReferenceEquals(el, target)) return true;
                el = Parent(el);
            }
            return false;
        }

        private string DebugHeader()
        {
            var lines = new List<string> { "RevoBIM Unhide in View v" + UivCore.Version, "build: " + UivCore.BuildInfo() };
            try { lines.Add("Revit " + uiapp.Application.VersionNumber + " " + uiapp.Application.VersionBuild); } catch (Exception) { }
            lines.Add("Theme: " + UivCore.Get(settings, "theme") + " -> " + currentTheme);
            if (scanner != null)
                lines.Add("Scan: " + scanner.Done() + "/" + scanner.Total + " views, " + scanner.Checked + " checks, " + scanner.Errors + " errors");
            lines.Add("Staged: " + staging.ElementTotal() + " elements in " + staging.ElementViews() + " views, " + staging.Categories.Count + " categories");
            lines.Add("Settings: " + string.Join("; ", settings.OrderBy(k => k.Key).Select(k => k.Key + "=" + k.Value)));
            lines.Add(new string('=', 60));
            return string.Join("\r\n", lines);
        }

        private void OnCopyDebug()
        {
            string text = log.Text(DebugHeader());
            bool ok = false;
            for (int i = 0; i < 3 && !ok; i++)
            {
                try { Clipboard.SetDataObject(text, true); ok = true; } catch (Exception) { System.Threading.Thread.Sleep(50); }
            }
            if (ok) SetStatus("Debug copied to the clipboard (" + log.Lines.Count + " lines).", "good");
            else SetStatus("Could not reach the clipboard - the log is in " + UivCore.DebugPath(), "warn");
            log.Flush(DebugHeader());
        }

        private void OnDebug()
        {
            bool on = C<CheckBox>("DebugChk").IsChecked == true;
            log.Enabled = on;
            settings["debug"] = on ? "1" : "0";
            UivCore.SaveSettings(settings);
        }

        // ---------------------------------------------------------------- loading --

        private void OnRendered()
        {
            if (started) return;
            started = true;
            watchTimer.Start();
            Load();
        }

        /// <summary>Every Revit call goes through here. A user job marks the window busy until its callback lands; the watchdog frees it if Revit never answers.</summary>
        private void Submit(string name, Func<UIApplication, object> work, Action<object> done, bool user = true)
        {
            if (user)
            {
                userJobs++;
                busySince = DateTime.UtcNow;
                RefreshButtons();
            }
            Action<object> finish = payload =>
            {
                if (user) userJobs = Math.Max(0, userJobs - 1);
                try { done(payload); }
                finally { if (user) RefreshButtons(); }
            };
            Action<string> fail = text =>
            {
                if (user) userJobs = Math.Max(0, userJobs - 1);
                log.Add("Job \"" + name + "\" failed: " + text);
                SetStatus(name + " did not finish - tick Debug, Copy debug and send it over.", "bad");
                if (name == "Read the model") loading = false;
                if (name == "Scan") scanInFlight = false;
                if (name == "Categories") catJobPending = false;
                RefreshButtons();
            };
            log.Add("Job: " + name);
            runner.Submit(new UivJob { Name = name, Work = work, Done = finish, Fail = fail, User = user });
        }

        private sealed class Loaded
        {
            public Document Doc;
            public List<UivView> Views;
            public List<UivCategory> Cats;
            public UivScanner Scanner;
            public long? Active;
            public string Title;
        }

        private void Load()
        {
            if (loading) return;
            loading = true;
            SetStatus("Reading the model...");
            C<TextBlock>("ScanText").Text = "Reading views and elements...";
            Submit("Read the model", uiapp2 =>
            {
                UIDocument uidoc = uiapp2.ActiveUIDocument;
                if (uidoc == null) throw new InvalidOperationException("No model is open in Revit");
                Document d = uidoc.Document;
                var timer = Stopwatch.StartNew();
                List<UivView> v = UivRevit.ReadViews(d, log);
                List<UivCategory> c = UivRevit.AllCategories(d);
                List<ElementId> ids = UivRevit.CandidateCategoryIds(d);
                UivScanner s = UivRevit.MakeScanner(d, v, ids, log);
                log.Add("Model read in " + timer.Elapsed.TotalSeconds.ToString("0.00") + "s: " + d.Title);
                return new Loaded { Doc = d, Views = v, Cats = c, Scanner = s, Active = UivRevit.ActiveViewKey(uidoc), Title = d.Title };
            }, payload => OnLoaded((Loaded)payload));
        }

        private void OnLoaded(Loaded data)
        {
            loading = false;
            var ticked = new HashSet<long>(TickedViews());
            long? oldFocus = focusKey;
            doc = data.Doc;
            views = data.Views;
            viewByKey = views.ToDictionary(v => v.Key);
            cats = data.Cats;
            catNames = cats.ToDictionary(c => c.Key, c => c.Name, null);
            catIds = cats.ToDictionary(c => c.Key, c => c.Category.Id);
            scanner = data.Scanner;
            hidden.Clear();
            catState.Clear();
            elemNotes.Clear();
            catNotes.Clear();
            scanStarted = DateTime.UtcNow;

            long? focus = data.Active;
            if (focus == null || !viewByKey.ContainsKey(focus.Value))
                focus = oldFocus != null && viewByKey.ContainsKey(oldFocus.Value) ? oldFocus : null;
            if (focus == null && views.Count > 0) focus = views[0].Key;

            FillViews(ticked);
            SetStatus(data.Title + " - " + views.Count + " views. Scanning for hidden elements...");
            SetFocus(focus, true);
            var first = new List<long>();
            if (focus != null) first.Add(focus.Value);
            first.AddRange(ticked.Where(viewByKey.ContainsKey));
            scanner.Bump(first);
            PumpScan();
        }

        // ---------------------------------------------------------------- the scan, a slice at a time --

        private void PumpScan()
        {
            if (closed || scanner == null || scanInFlight) return;
            if (scanner.Finished())
            {
                ShowScanProgress();
                return;
            }
            if (!UivRevit.DocAlive(doc)) return;
            scanInFlight = true;
            double budget = UivCore.AsDouble(UivCore.Get(settings, "scan_budget_ms"), 120, 20, 1000) / 1000.0;
            UivScanner s = scanner;
            Submit("Scan", uiapp2 => new KeyValuePair<UivScanner, List<long>>(s, s.Step(budget)),
                payload => OnScanned((KeyValuePair<UivScanner, List<long>>)payload), false);
        }

        private void OnScanned(KeyValuePair<UivScanner, List<long>> payload)
        {
            scanInFlight = false;
            if (!ReferenceEquals(payload.Key, scanner)) return;     // a Refresh replaced it
            foreach (long vk in payload.Value)
            {
                List<ElementId> ids;
                scanner.Results.TryGetValue(vk, out ids);
                var map = new Dictionary<long, ElementId>();
                foreach (ElementId id in ids ?? new List<ElementId>()) map[UivRevit.Key(id)] = id;
                hidden[vk] = map;
                staging.PruneView(vk, new HashSet<long>(map.Keys));
                UpdateViewCount(vk);
                if (focusKey == vk) RequestElemRows(vk);
            }
            if (payload.Value.Count > 0) RefreshButtons();
            ShowScanProgress();
            if (!scanner.Finished()) Restart(scanTimer);
        }

        private void ShowScanProgress()
        {
            if (scanner == null) return;
            int done = scanner.Done(), total = scanner.Total;
            ProgressBar bar = C<ProgressBar>("ScanBar");
            bar.Value = total > 0 ? 100.0 * done / total : 100.0;
            int withHidden = hidden.Values.Count(d => d.Count > 0);
            if (scanner.Finished())
            {
                bar.SetResourceReference(Control.ForegroundProperty, "Green");
                C<TextBlock>("ScanText").Text = "Scanned " + UivCore.Plural(total, "view") + " - " + withHidden + " with hidden elements (" +
                                                (DateTime.UtcNow - scanStarted).TotalSeconds.ToString("0.0") + "s)";
            }
            else
            {
                bar.SetResourceReference(Control.ForegroundProperty, "Blue");
                C<TextBlock>("ScanText").Text = "Scanning views for hidden elements: " + done + " / " + total + " - " + withHidden + " found so far";
            }
        }

        // ---------------------------------------------------------------- views list --

        private void FillViews(HashSet<long> ticked)
        {
            suspend = true;
            try
            {
                viewTable.Rows.Clear();
                viewRows.Clear();
                foreach (UivView v in views)
                {
                    DataRow r = viewTable.NewRow();
                    r["key"] = v.Key.ToString();
                    r["tick"] = ticked.Contains(v.Key);
                    r["name"] = v.Name;
                    r["nkey"] = UivCore.NaturalKey(v.Name);
                    r["vtype"] = v.Type;
                    r["note"] = v.TemplateName ?? "";
                    r["warn"] = "0";
                    r["bad"] = "0";
                    r["vis"] = "1";
                    SetCountCells(r, null);
                    viewTable.Rows.Add(r);
                    viewRows[v.Key] = r;
                }
            }
            finally
            {
                suspend = false;
            }
            RefilterViews();
        }

        private static void SetCountCells(DataRow row, int? n)
        {
            row["cnt"] = n ?? -1;
            row["cnt_txt"] = UivCore.CountText(n);
            row["hot"] = n.HasValue && n.Value > 0 ? "1" : "0";
        }

        private int? CountFor(long vk)
        {
            Dictionary<long, ElementId> d;
            return hidden.TryGetValue(vk, out d) ? d.Count : (int?)null;
        }

        private void UpdateViewCount(long vk)
        {
            DataRow r;
            if (!viewRows.TryGetValue(vk, out r)) return;
            SetCountCells(r, CountFor(vk));
            ViewVis(vk, r);
        }

        private void ViewVis(long vk, DataRow r)
        {
            UivView v;
            if (!viewByKey.TryGetValue(vk, out v)) return;
            bool ok = UivCore.ViewRowVisible(v.Name, v.Type, CountFor(vk), C<TextBox>("ViewSearch").Text, C<ToggleButton>("OnlyHiddenToggle").IsChecked == true);
            string want = ok ? "1" : "0";
            if ((string)r["vis"] != want) r["vis"] = want;
        }

        private void RefilterViews()
        {
            foreach (KeyValuePair<long, DataRow> pair in viewRows) ViewVis(pair.Key, pair.Value);
            int shown = viewTable.DefaultView.Count, total = viewRows.Count;
            C<TextBlock>("ViewCountText").Text = shown == total ? UivCore.Plural(total, "view") : shown + " of " + total + " views";
            string empty = "";
            bool only = C<ToggleButton>("OnlyHiddenToggle").IsChecked == true;
            if (total > 0 && shown == 0)
            {
                if (only && scanner != null && !scanner.Finished()) empty = "No views with hidden elements found yet - still scanning.";
                else if (only) empty = "No view has elements hidden in it.";
                else empty = "No views match the search.";
            }
            C<TextBlock>("ViewEmptyText").Text = empty;
        }

        private void OnOnlyHidden()
        {
            settings["only_hidden"] = C<ToggleButton>("OnlyHiddenToggle").IsChecked == true ? "1" : "0";
            UivCore.SaveSettings(settings);
            RefilterViews();
        }

        private List<long> TickedViews()
        {
            var output = new List<long>();
            foreach (KeyValuePair<long, DataRow> pair in viewRows)
            {
                try { if (pair.Value["tick"] is bool && (bool)pair.Value["tick"]) output.Add(pair.Key); } catch (Exception) { }
            }
            return output;
        }

        private void OnViewSelected(SelectionChangedEventArgs e)
        {
            if (suspend || e.AddedItems == null || e.AddedItems.Count == 0) return;
            var drv = e.AddedItems[e.AddedItems.Count - 1] as DataRowView;
            if (drv == null) return;
            long vk = long.Parse((string)drv.Row["key"]);
            if (vk != focusKey) SetFocus(vk, false);
        }

        private void OnViewDouble(MouseButtonEventArgs e)
        {
            var row = Ancestor<DataGridRow>(e.OriginalSource as DependencyObject);
            var drv = row == null ? null : row.Item as DataRowView;
            if (drv == null) return;
            UivView v;
            if (!viewByKey.TryGetValue(long.Parse((string)drv.Row["key"]), out v) || !DocOk()) return;
            Document d = doc;
            Submit("Open view", uiapp2 =>
            {
                UIDocument uidoc = uiapp2.ActiveUIDocument;
                if (uidoc == null || !UivRevit.SameDoc(uidoc.Document, d)) return "Open this model in Revit first - the window is reading another one.";
                return UivRevit.ActivateView(uidoc, v.View, log) ? "Opened " + v.Name : "Revit would not open " + v.Name;
            }, msg => SetStatus((string)msg));
        }

        // ---------------------------------------------------------------- focus: which view the left table shows --

        private void SetFocus(long? vk, bool selectRow)
        {
            focusKey = vk;
            UivView v = null;
            if (vk != null) viewByKey.TryGetValue(vk.Value, out v);
            C<TextBlock>("FocusViewText").Text = v != null ? v.Name + "  (" + v.Type + ")" : "";
            elemTable.Rows.Clear();
            elemRows = new Dictionary<long, DataRow>();
            elemAll.IsChecked = false;
            if (selectRow && vk != null) SelectViewRow(vk.Value);
            if (v == null) C<TextBlock>("ElemEmptyText").Text = "No view to show.";
            else if (hidden.ContainsKey(vk.Value)) RequestElemRows(vk.Value);
            else
            {
                C<TextBlock>("ElemEmptyText").Text = "Scanning this view...";
                C<TextBlock>("ElemCountText").Text = "";
                if (scanner != null)
                {
                    scanner.Bump(new[] { vk.Value });
                    PumpScan();
                }
            }
            TargetsChanged();
        }

        private void SelectViewRow(long vk)
        {
            DataRow r;
            if (!viewRows.TryGetValue(vk, out r)) return;
            DataGrid g = C<DataGrid>("ViewGrid");
            suspend = true;
            try
            {
                foreach (DataRowView drv in viewTable.DefaultView)
                {
                    if (ReferenceEquals(drv.Row, r))
                    {
                        g.SelectedItem = drv;
                        g.ScrollIntoView(drv);
                        break;
                    }
                }
            }
            finally
            {
                suspend = false;
            }
        }

        private void OnCurrentView()
        {
            Document d = doc;
            Submit("Current view", uiapp2 =>
            {
                UIDocument uidoc = uiapp2.ActiveUIDocument;
                if (uidoc == null || !UivRevit.SameDoc(uidoc.Document, d)) return (object)null;
                return UivRevit.ActiveViewKey(uidoc);
            }, payload =>
            {
                long? vk = payload as long?;
                if (vk == null)
                {
                    SetStatus("The model open in Revit is not the one this window read - press Refresh.", "warn");
                    return;
                }
                if (!viewByKey.ContainsKey(vk.Value))
                {
                    SetStatus("The open view cannot hide elements (a schedule or browser) - pick one from the list.", "warn");
                    return;
                }
                SetFocus(vk, true);
            });
        }

        // ---------------------------------------------------------------- hidden elements table --

        private void RequestElemRows(long vk)
        {
            Dictionary<long, ElementId> map;
            UivView v;
            if (!hidden.TryGetValue(vk, out map) || !viewByKey.TryGetValue(vk, out v)) return;
            if (map.Count == 0)
            {
                FillElems(vk, new List<UivElementRow>());
                return;
            }
            C<TextBlock>("ElemEmptyText").Text = "Reading " + UivCore.Plural(map.Count, "element") + "...";
            Document d = doc;
            var items = map.OrderBy(p => p.Key).Select(p => p.Value).ToList();
            Submit("Read hidden elements", uiapp2 =>
            {
                var cache = new Dictionary<long, bool>();
                return new KeyValuePair<long, List<UivElementRow>>(vk, items.Select(id => UivRevit.ElementRow(d, id, v.View, cache)).ToList());
            }, payload =>
            {
                var p = (KeyValuePair<long, List<UivElementRow>>)payload;
                FillElems(p.Key, p.Value);
            }, false);
        }

        private void FillElems(long vk, List<UivElementRow> rows)
        {
            if (vk != focusKey) return;
            elemTable.Rows.Clear();
            elemRows = new Dictionary<long, DataRow>();
            foreach (UivElementRow d in rows)
            {
                DataRow r = elemTable.NewRow();
                r["key"] = d.Key.ToString();
                r["tick"] = staging.ElementTicked(vk, d.Key);
                r["id_txt"] = d.IdText;
                r["nid"] = UivCore.NaturalKey(d.IdText);
                r["category"] = d.Category;
                r["ftype"] = d.FamilyType;
                r["level"] = d.Level;
                string note;
                if (elemNotes.TryGetValue(vk + ":" + d.Key, out note))
                {
                    r["note"] = note;
                    r["bad"] = "1";
                    r["warn"] = "0";
                }
                else
                {
                    r["note"] = d.Note;
                    r["bad"] = d.Bad ? "1" : "0";
                    r["warn"] = d.Warn ? "1" : "0";
                }
                r["hot"] = "0";
                r["vis"] = "1";
                elemTable.Rows.Add(r);
                elemRows[d.Key] = r;
            }
            RefilterElems();
        }

        private void RefilterElems()
        {
            var filters = elemFilters.Where(p => p.Value.Length > 0).ToDictionary(p => p.Key, p => p.Value);
            foreach (DataRow r in elemRows.Values)
            {
                var values = ElemFilterCols.ToDictionary(c => c, c => (string)r[c]);
                string want = UivCore.RowMatchesColumns(values, filters) ? "1" : "0";
                if ((string)r["vis"] != want) r["vis"] = want;
            }
            int total = elemRows.Count, shown = elemTable.DefaultView.Count;
            bool known = focusKey != null && hidden.ContainsKey(focusKey.Value);
            if (known)
            {
                string txt = UivCore.Plural(total, "hidden element");
                if (shown != total) txt += ", " + shown + " shown";
                C<TextBlock>("ElemCountText").Text = txt;
            }
            TextBlock empty = C<TextBlock>("ElemEmptyText");
            if (total == 0 && known) empty.Text = "Nothing is hidden in this view by Hide in View > Elements.";
            else if (total > 0 && shown == 0) empty.Text = "No hidden elements match the filters.";
            else empty.Text = "";
            RefreshButtons();
        }

        private void OnElemDouble(MouseButtonEventArgs e)
        {
            var row = Ancestor<DataGridRow>(e.OriginalSource as DependencyObject);
            var drv = row == null ? null : row.Item as DataRowView;
            if (drv == null || focusKey == null) return;
            long vk = focusKey.Value;
            long ek = long.Parse((string)drv.Row["key"]);
            Dictionary<long, ElementId> map;
            ElementId eid = null;
            if (hidden.TryGetValue(vk, out map)) map.TryGetValue(ek, out eid);
            UivView v;
            if (eid == null || !viewByKey.TryGetValue(vk, out v) || !DocOk()) return;
            Document d = doc;
            Submit("Select element", uiapp2 =>
            {
                UIDocument uidoc = uiapp2.ActiveUIDocument;
                if (uidoc == null || !UivRevit.SameDoc(uidoc.Document, d)) return "Open this model in Revit first - the window is reading another one.";
                UivRevit.ActivateView(uidoc, v.View, log);
                return UivRevit.SelectIds(uidoc, new List<ElementId> { eid }, log)
                    ? "Selected element " + ek + " - its properties are in the Properties palette."
                    : "Revit would not select element " + ek + ".";
            }, msg => SetStatus((string)msg));
        }

        // ---------------------------------------------------------------- categories --

        private List<long> Targets() { return UivCore.TargetViews(TickedViews(), focusKey); }

        private void TargetsChanged()
        {
            List<long> targets = Targets();
            List<long> ticked = TickedViews();
            TextBlock text = C<TextBlock>("CatTargetText");
            UivView v = null;
            if (focusKey != null) viewByKey.TryGetValue(focusKey.Value, out v);
            if (ticked.Count > 0) text.Text = "in the " + UivCore.Plural(ticked.Count, "view") + " ticked";
            else text.Text = v != null ? "in " + v.Name : "";
            if (targets.Count == 0)
            {
                catTable.Rows.Clear();
                catRows = new Dictionary<long, DataRow>();
                C<TextBlock>("CatEmptyText").Text = "";
                return;
            }
            RefreshCategories();
        }

        /// <summary>Category state is read a few views per ExternalEvent, so ticking every view in a big project never holds Revit for long.</summary>
        private void RefreshCategories()
        {
            List<long> targets = Targets();
            var missing = targets.Where(vk => !catState.ContainsKey(vk) && viewByKey.ContainsKey(vk)).ToList();
            if (missing.Count == 0)
            {
                FillCats();
                return;
            }
            if (catJobPending) return;
            catJobPending = true;
            int read = targets.Count(catState.ContainsKey);
            C<TextBlock>("CatEmptyText").Text = "Reading categories... " + read + " / " + targets.Count + " views";
            Document d = doc;
            List<UivCategory> categories = cats;
            var batch = missing.Take(CatViewsPerJob).Select(vk => new KeyValuePair<long, View>(vk, viewByKey[vk].View)).ToList();
            Submit("Categories", uiapp2 =>
            {
                var output = new Dictionary<long, Dictionary<long, UivCatState>>();
                foreach (var pair in batch)
                {
                    try
                    {
                        output[pair.Key] = UivRevit.ReadCategoryState(d, pair.Value, categories);
                    }
                    catch (Exception err)
                    {
                        log.Add("Categories of view " + pair.Key + " unreadable: " + err.Message);
                        output[pair.Key] = new Dictionary<long, UivCatState>();
                    }
                }
                return output;
            }, payload =>
            {
                catJobPending = false;
                foreach (var pair in (Dictionary<long, Dictionary<long, UivCatState>>)payload) catState[pair.Key] = pair.Value;
                RefreshCategories();
            }, false);
        }

        private void FillCats()
        {
            List<UivCategoryRow> rows = UivCore.SummariseCategories(Targets(), catState, catNames);
            staging.PruneCategories(new HashSet<long>(rows.Select(r => r.Key)));
            bool changeT = C<CheckBox>("ChangeTemplatesChk").IsChecked == true;
            catTable.Rows.Clear();
            catRows = new Dictionary<long, DataRow>();
            foreach (UivCategoryRow d in rows)
            {
                DataRow r = catTable.NewRow();
                r["key"] = d.Key.ToString();
                r["tick"] = staging.Categories.Contains(d.Key);
                r["name"] = d.Name;
                r["nkey"] = UivCore.NaturalKey(d.Name);
                r["hidden_txt"] = d.HiddenText;
                r["hidden_n"] = d.HiddenIn;
                string refused;
                if (catNotes.TryGetValue(d.Key, out refused))
                {
                    r["note"] = refused;
                    r["bad"] = "1";
                    r["warn"] = "0";
                }
                else
                {
                    string note = d.Note;
                    if (note.Length > 0 && !changeT) note += " - tick \"Also change view templates\" to unhide it there";
                    r["note"] = note;
                    r["bad"] = "0";
                    r["warn"] = d.Templates.Count > 0 ? "1" : "0";
                }
                r["hot"] = "1";
                r["vis"] = "1";
                catTable.Rows.Add(r);
                catRows[d.Key] = r;
            }
            RefilterCats();
        }

        private void RefilterCats()
        {
            string q = C<TextBox>("CatSearch").Text;
            foreach (DataRow r in catRows.Values)
            {
                string want = UivCore.KeywordMatch((string)r["name"], q) ? "1" : "0";
                if ((string)r["vis"] != want) r["vis"] = want;
            }
            int total = catRows.Count, shown = catTable.DefaultView.Count;
            TextBlock empty = C<TextBlock>("CatEmptyText");
            if (total == 0) empty.Text = "No categories are hidden in these views.";
            else if (shown == 0) empty.Text = "No hidden categories match the search.";
            else empty.Text = "";
            RefreshButtons();
        }

        private void OnChangeTemplates()
        {
            settings["change_templates"] = C<CheckBox>("ChangeTemplatesChk").IsChecked == true ? "1" : "0";
            UivCore.SaveSettings(settings);
            FillCats();
        }

        // ---------------------------------------------------------------- ticks --

        private void OnGridClick(string which, RoutedEventArgs e)
        {
            var src = e.OriginalSource as CheckBox;
            if (src == null) return;
            var drv = src.DataContext as DataRowView;
            if (drv == null) return;
            try { drv.EndEdit(); } catch (Exception) { }
            Ticked(which, new List<DataRow> { drv.Row }, src.IsChecked == true);
        }

        private void Ticked(string which, List<DataRow> rows, bool on)
        {
            foreach (DataRow r in rows)
            {
                if (!((r["tick"] is bool) && (bool)r["tick"] == on)) r["tick"] = on;
                long k = long.Parse((string)r["key"]);
                if (which == "elem" && focusKey != null) staging.SetElement(focusKey.Value, k, on);
                else if (which == "cat") staging.SetCategory(k, on);
            }
            if (which == "view")
            {
                foreach (DataRow r in rows)
                {
                    long vk = long.Parse((string)r["key"]);
                    if (on && scanner != null && !hidden.ContainsKey(vk)) scanner.Bump(new[] { vk });
                }
                PumpScan();
                TargetsChanged();
            }
            RefreshButtons();
        }

        private static List<DataRow> ShownRows(DataTable table)
        {
            return table.DefaultView.Cast<DataRowView>().Select(d => d.Row).ToList();
        }

        private void OnViewAll() { Ticked("view", ShownRows(viewTable), viewAll.IsChecked == true); }
        private void OnElemAll() { Ticked("elem", ShownRows(elemTable), elemAll.IsChecked == true); }
        private void OnCatAll() { Ticked("cat", ShownRows(catTable), catAll.IsChecked == true); }

        private bool ToggleSelected(DataGrid grid, string which)
        {
            var rows = grid.SelectedItems.OfType<DataRowView>().Select(d => d.Row).ToList();
            if (rows.Count == 0) return false;
            bool on = !rows.All(r => (r["tick"] is bool) && (bool)r["tick"]);
            Ticked(which, rows, on);
            return true;
        }

        // ---------------------------------------------------------------- buttons --

        private List<long> SelectedElemKeys()
        {
            return C<DataGrid>("ElemGrid").SelectedItems.OfType<DataRowView>().Select(d => long.Parse((string)d.Row["key"])).ToList();
        }

        /// <summary>Ticks if there are any; otherwise the rows selected in the left table - 'select them and click Unhide' works without ticking.</summary>
        private UivCore.Staging EffectiveStaging(out bool fromSelection)
        {
            fromSelection = false;
            if (staging.ElementTotal() > 0 || focusKey == null) return staging;
            List<long> sel = SelectedElemKeys();
            if (sel.Count == 0) return staging;
            var st = new UivCore.Staging { Categories = new HashSet<long>(staging.Categories) };
            foreach (long k in sel) st.SetElement(focusKey.Value, k, true);
            fromSelection = true;
            return st;
        }

        private void RefreshButtons()
        {
            if (viewTable == null) return;
            bool busy = userJobs > 0;
            bool loaded = doc != null;
            bool fromSel;
            UivCore.Staging st = EffectiveStaging(out fromSel);
            int nEl = st.ElementTotal(), nCat = st.Categories.Count;
            string label = UivCore.UnhideLabel(nEl, nCat);
            if (fromSel && nEl > 0) label += " (selected)";
            C<TextBlock>("UnhideText").Text = label;
            C<Button>("UnhideBtn").IsEnabled = loaded && !busy && (nEl > 0 || nCat > 0);

            List<long> ticked = TickedViews();
            int nHidden = 0, waiting = 0;
            foreach (long vk in ticked)
            {
                Dictionary<long, ElementId> d;
                if (hidden.TryGetValue(vk, out d)) nHidden += d.Count;
                else waiting++;
            }
            C<TextBlock>("UnhideViewsText").Text = waiting > 0 ? "Unhide all in ticked views (scanning " + waiting + ")" : UivCore.ViewsButtonLabel(ticked.Count, nHidden);
            C<Button>("UnhideViewsBtn").IsEnabled = loaded && !busy && ticked.Count > 0 && waiting == 0 && nHidden > 0;
            TextBlock tickedText = C<TextBlock>("TickedText");
            if (ticked.Count > 0)
            {
                string extra = staging.ElementTotal() > 0
                    ? " - " + staging.ElementTotal() + " elements ticked in " + UivCore.Plural(staging.ElementViews(), "view") : "";
                tickedText.Text = UivCore.Plural(ticked.Count, "view") + " ticked" + extra;
            }
            else if (staging.ElementTotal() > 0)
                tickedText.Text = staging.ElementTotal() + " elements ticked in " + UivCore.Plural(staging.ElementViews(), "view");
            else
                tickedText.Text = "Tick views to unhide everything in them";
        }

        // ---------------------------------------------------------------- unhide --

        private bool DocOk()
        {
            if (UivRevit.DocAlive(doc)) return true;
            SetStatus("The model this window read has been closed - press Refresh.", "warn");
            return false;
        }

        private void OnUnhide()
        {
            if (!DocOk()) return;
            bool fromSel;
            UivCore.Staging st = EffectiveStaging(out fromSel);
            StartUnhide(st, Targets());
        }

        private void OnUnhideViews()
        {
            if (!DocOk()) return;
            var st = new UivCore.Staging();
            foreach (long vk in TickedViews())
            {
                Dictionary<long, ElementId> d;
                if (!hidden.TryGetValue(vk, out d)) continue;
                foreach (long ek in d.Keys) st.SetElement(vk, ek, true);
            }
            if (st.ElementTotal() == 0)
            {
                SetStatus("Nothing is hidden in the ticked views.");
                return;
            }
            int n = st.ElementTotal(), nv = st.ElementViews();
            Confirm("Unhide everything in the ticked views?",
                    UivCore.Plural(n, "element") + " hidden in " + UivCore.Plural(nv, "view") + " will be shown again. One undo step reverses it.",
                    "Unhide " + UivCore.Plural(n, "element"), () => StartUnhide(st, new List<long>()));
        }

        private void StartUnhide(UivCore.Staging stage, List<long> targets)
        {
            if (stage.Categories.Count > 0 && targets.Any(vk => !catState.ContainsKey(vk)))
            {
                SetStatus("Still reading the categories of the target views - try again in a moment.", "warn");
                RefreshCategories();
                return;
            }
            var hiddenKeys = hidden.ToDictionary(p => p.Key, p => new HashSet<long>(p.Value.Keys));
            bool changeT = C<CheckBox>("ChangeTemplatesChk").IsChecked == true;
            UivPlan plan = UivCore.BuildPlan(stage, hiddenKeys, targets, catState, changeT, vk =>
            {
                UivView v;
                return viewByKey.TryGetValue(vk, out v) ? v.TemplateKey : null;
            });
            int nEl, nEv, nCat, nOwn;
            UivCore.PlanCounts(plan, out nEl, out nEv, out nCat, out nOwn);
            log.Add("Plan: " + nEl + " elements in " + nEv + " views, " + nCat + " categories on " + nOwn + " views/templates, " + plan.Skipped.Count + " skipped");
            foreach (UivSkip s in plan.Skipped) log.Add("  skip " + s.Kind + " " + s.Owner + " " + s.Key + ": " + s.Reason);
            if (nEl == 0 && nCat == 0)
            {
                string reason = plan.Skipped.Count > 0 ? plan.Skipped[0].Reason : "nothing is ticked";
                SetStatus("Nothing to unhide - " + reason + ".", "warn");
                return;
            }
            List<long> templates = plan.Categories.Where(c => c.IsTemplate).Select(c => c.Owner).ToList();
            if (templates.Count > 0)
            {
                var names = new List<string>();
                int users = 0;
                foreach (long okey in templates)
                    foreach (UivView v in views)
                        if (v.TemplateKey == okey)
                        {
                            users++;
                            if (!names.Contains(v.TemplateName)) names.Add(v.TemplateName);
                        }
                Confirm("Change view templates?",
                        "This unhides categories on " + UivCore.Plural(templates.Count, "template") + " (" + string.Join(", ", names) +
                        "), which changes every view using them - " + UivCore.Plural(users, "view") + " in this model.",
                        "Change templates and unhide", () => RunPlan(plan));
                return;
            }
            RunPlan(plan);
        }

        private View TemplateView(long tkey)
        {
            foreach (UivView v in views)
                if (v.TemplateKey == tkey && v.TemplateId != null) return doc.GetElement(v.TemplateId) as View;
            return null;
        }

        private void RunPlan(UivPlan plan)
        {
            Document d = doc;
            var hiddenMap = hidden.ToDictionary(p => p.Key, p => new Dictionary<long, ElementId>(p.Value));
            Dictionary<long, UivView> byKey = viewByKey;
            Dictionary<long, ElementId> ids = catIds;
            Func<long, View> viewOf = vk => { UivView v; return byKey.TryGetValue(vk, out v) ? v.View : null; };
            Func<long, bool, View> ownerOf = (key, isT) => isT ? TemplateView(key) : viewOf(key);
            Func<long, long, ElementId> eidOf = (vk, ek) =>
            {
                Dictionary<long, ElementId> m; ElementId id = null;
                if (hiddenMap.TryGetValue(vk, out m)) m.TryGetValue(ek, out id);
                return id;
            };
            Func<long, ElementId> catIdOf = ck => { ElementId id; return ids.TryGetValue(ck, out id) ? id : null; };

            SetStatus("Unhiding...");
            Submit("Unhide", uiapp2 => UivRevit.RunUnhide(d, plan, viewOf, ownerOf, eidOf, catIdOf, uiapp2, log),
                payload => AfterUnhide(plan, (UivResult)payload));
        }

        private void AfterUnhide(UivPlan plan, UivResult result)
        {
            var touched = new HashSet<long>();
            foreach (KeyValuePair<long, long> ok in result.OkElements)
            {
                Dictionary<long, ElementId> d;
                if (hidden.TryGetValue(ok.Key, out d)) d.Remove(ok.Value);
                staging.SetElement(ok.Key, ok.Value, false);
                elemNotes.Remove(ok.Key + ":" + ok.Value);
                touched.Add(ok.Key);
            }
            foreach (UivSkip r in result.Refused)
            {
                if (r.Kind == "element")
                {
                    elemNotes[r.Owner + ":" + r.Key] = r.Reason;
                    staging.SetElement(r.Owner, r.Key, false);
                    touched.Add(r.Owner);
                }
                else if (r.Kind == "category") catNotes[r.Key] = r.Reason;
            }
            foreach (long vk in touched)
            {
                Dictionary<long, ElementId> d;
                if (scanner != null && hidden.TryGetValue(vk, out d)) scanner.Results[vk] = d.Values.ToList();
                UpdateViewCount(vk);
            }

            // categories: every view whose own settings or template changed reads again
            var changed = new HashSet<string>();
            foreach (UivPlanCategories oc in result.OkCategories)
            {
                foreach (long ck in oc.Categories)
                {
                    staging.SetCategory(ck, false);
                    catNotes.Remove(ck);
                }
                changed.Add((oc.IsTemplate ? "T" : "V") + oc.Owner);
            }
            foreach (UivPlanCategories pc in plan.Categories) changed.Add((pc.IsTemplate ? "T" : "V") + pc.Owner);
            foreach (string id in changed)
            {
                long key = long.Parse(id.Substring(1));
                if (id[0] == 'T')
                {
                    foreach (UivView v in views) if (v.TemplateKey == key) catState.Remove(v.Key);
                }
                else catState.Remove(key);
            }

            foreach (UivSkip s in result.Skipped) log.Add("Skipped " + s.Kind + " " + s.Owner + " " + s.Key + ": " + s.Reason);
            if (focusKey != null && (touched.Contains(focusKey.Value) || hidden.ContainsKey(focusKey.Value))) RequestElemRows(focusKey.Value);
            TargetsChanged();
            RefilterViews();
            string kind = result.Refused.Count > 0 ? "bad" : (result.ElementsOk > 0 || result.CategoriesOk > 0 ? "good" : "warn");
            SetStatus(UivCore.SummariseResult(result), kind);
            log.Flush(DebugHeader());
            try { uiapp.ActiveUIDocument.RefreshActiveView(); } catch (Exception) { }
        }

        // ---------------------------------------------------------------- confirm overlay --

        private void Confirm(string title, string text, string yesLabel, Action action)
        {
            // a prompt on a shrunk window would sit over the bar - open it first
            if (!drawer.IsOpen) drawer.RestoreNow();
            confirmAction = action;
            C<TextBlock>("ConfirmTitle").Text = title;
            C<TextBlock>("ConfirmText").Text = text;
            C<TextBlock>("ConfirmYesText").Text = yesLabel;
            C<UIElement>("ConfirmOverlay").Visibility = Visibility.Visible;
        }

        private void HideConfirm()
        {
            C<UIElement>("ConfirmOverlay").Visibility = Visibility.Collapsed;
            confirmAction = null;
        }

        private void OnConfirmYes()
        {
            Action action = confirmAction;
            HideConfirm();
            if (action != null) action();
        }

        // ---------------------------------------------------------------- keyboard --

        private void OnKey(KeyEventArgs e)
        {
            bool ctrl = (Keyboard.Modifiers & ModifierKeys.Control) == ModifierKeys.Control;
            bool shift = (Keyboard.Modifiers & ModifierKeys.Shift) == ModifierKeys.Shift;
            IInputElement focus = Keyboard.FocusedElement;
            var focusBox = focus as TextBox;
            if (ctrl && shift && e.Key == Key.H)
            {
                drawer.Toggle();
                e.Handled = true;
                return;
            }
            if (!drawer.IsOpen)
            {
                // shrunk: Escape, Enter and F11 bring the window back rather than reaching the close prompt
                if (e.Key == Key.Escape || e.Key == Key.Enter || e.Key == Key.F11)
                {
                    drawer.Expand(true);
                    e.Handled = true;
                }
                return;
            }
            if (e.Key == Key.F5)
            {
                Load();
                e.Handled = true;
            }
            else if (e.Key == Key.F11)
            {
                fullscreen.Toggle();
                e.Handled = true;
            }
            else if (e.Key == Key.Escape)
            {
                if (C<UIElement>("ConfirmOverlay").Visibility == Visibility.Visible) HideConfirm();
                else if (fullscreen.Active) fullscreen.Leave();
                else if (focusBox != null && !string.IsNullOrEmpty(focusBox.Text)) focusBox.Text = "";
                e.Handled = true;
            }
            else if (ctrl && e.Key == Key.F)
            {
                C<TextBox>("ViewSearch").Focus();
                C<TextBox>("ViewSearch").SelectAll();
                e.Handled = true;
            }
            else if (e.Key == Key.Space && focusBox == null)
            {
                foreach (var pair in new[] { Tuple.Create("ElemGrid", "elem"), Tuple.Create("ViewGrid", "view"), Tuple.Create("CatGrid", "cat") })
                {
                    DataGrid g = C<DataGrid>(pair.Item1);
                    if (g.IsKeyboardFocusWithin)
                    {
                        if (ToggleSelected(g, pair.Item2)) e.Handled = true;
                        break;
                    }
                }
            }
        }

        // ---------------------------------------------------------------- watchdog and closing --

        private void OnWatchdog()
        {
            if (runner.Watchdog()) SetStatus("Revit had not answered for 20s - asked again.", "warn");
            if (userJobs > 0 && (DateTime.UtcNow - busySince).TotalSeconds > 25.0)
            {
                log.Add("Window freed after 25s busy (" + userJobs + " jobs outstanding)");
                userJobs = 0;
                SetStatus("Revit did not answer - the window is free again. Try once more.", "warn");
                RefreshButtons();
            }
        }

        private void RequestClose()
        {
            if (staging.Anything())
            {
                Confirm("Close without unhiding?",
                        UivCore.Plural(staging.ElementTotal(), "element") + " and " + UivCore.Plural(staging.Categories.Count, "category", "categories") +
                        " are ticked and have not been unhidden.", "Close anyway", ReallyClose);
                return;
            }
            ReallyClose();
        }

        private void ReallyClose()
        {
            closeOk = true;
            try { win.Close(); } catch (Exception) { }
        }

        private void OnClosing(System.ComponentModel.CancelEventArgs e)
        {
            try
            {
                if (!closeOk && staging.Anything())
                {
                    e.Cancel = true;
                    RequestClose();
                }
            }
            catch (Exception)
            {
            }
        }

        private void OnClosed()
        {
            closed = true;
            foreach (DispatcherTimer t in new[] { viewTimer, elemTimer, catTimer, scanTimer, watchTimer })
            {
                try { t.Stop(); } catch (Exception) { }
            }
            drawer.Stop();
            try
            {
                // the real size - not the parked bar, not the full-screen bounds
                double[] bounds = drawer.TrueBounds();
                if (fullscreen.Saved != null) bounds = fullscreen.Saved;
                settings["width"] = bounds[2].ToString("0");
                settings["height"] = bounds[3].ToString("0");
                double lw = C<ColumnDefinition>("LeftCol").ActualWidth, rw = C<ColumnDefinition>("RightCol").ActualWidth;
                if (lw + rw > 0) settings["split"] = (lw / (lw + rw)).ToString("0.000", System.Globalization.CultureInfo.InvariantCulture);
                double eh = C<RowDefinition>("ElemRow").ActualHeight, ch = C<RowDefinition>("CatRow").ActualHeight;
                if (eh + ch > 0) settings["cat_split"] = (ch / (eh + ch)).ToString("0.000", System.Globalization.CultureInfo.InvariantCulture);
                UivCore.SaveSettings(settings);
            }
            catch (Exception)
            {
            }
            log.Add("Closed");
            log.Flush(DebugHeader());
            if (ReferenceEquals(current, this)) current = null;
        }
    }
}
