using System;
using System.Collections.Generic;
using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Interop;
using System.Windows.Markup;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Shapes;
using System.Windows.Threading;
using Autodesk.Revit.UI;

using Path = System.Windows.Shapes.Path;

namespace RevoBIM.Helpers
{
    /// <summary>
    /// Window chrome shared by the tools whose layouts use the snake_case element names
    /// (header_bar, body, shrink_btn, theme_btn, grip_n ...): Circuit Manager and the Electrical tools after it.
    /// One <see cref="ChromeConfig"/> per tool says where its layouts, icon, settings and palettes are; every
    /// window of the tool then builds on <see cref="ThemedWindow"/>: header, dragging, the eight resize grips,
    /// full screen, the theme chip and the shrink-to-taskbar drawer behave identically across them.
    /// </summary>
    public sealed class ChromeConfig
    {
        /// <summary>Resource prefix of the embedded layouts, e.g. "RevoBIM.UI.CircuitManager.Layouts.".</summary>
        public string LayoutPrefix;
        public string ThemeFile = "Theme.xaml";
        /// <summary>Embedded resource name of the tool's icon.png.</summary>
        public string IconResource;
        public string Version = "0.0.0";
        /// <summary>The stored theme setting: follow, dark or light.</summary>
        public Func<string> ThemeSetting = () => "follow";
        public Action<string> SetThemeSetting = s => { };
        /// <summary>Palette (brush key to hex) for a resolved theme, "dark" or "light".</summary>
        public Func<string, IDictionary<string, string>> Palette;
        public Action<string> Log = s => { };
        /// <summary>Windows of this tool that are open, so a theme change repaints all of them.</summary>
        public readonly List<ThemedWindow> Open = new List<ThemedWindow>();
        /// <summary>The drawers of this tool that are parked, so two parked bars do not land on each other.</summary>
        public readonly List<WindowDrawer> Parked = new List<WindowDrawer>();

        /// <summary>True / false from Revit's live canvas theme; null where unreadable.</summary>
        public static bool? CanvasIsDark()
        {
            try
            {
                return RevitCompat.CanvasTheme() == UITheme.Dark;
            }
            catch (Exception)
            {
                return null;
            }
        }

        public string Resolved()
        {
            return RevoChrome.ResolveTheme(ThemeSetting(), CanvasIsDark());
        }

        public void RepaintAll()
        {
            string resolved = Resolved();
            foreach (ThemedWindow w in new List<ThemedWindow>(Open))
            {
                try
                {
                    w.Paint(resolved);
                }
                catch (Exception)
                {
                }
            }
        }
    }

    /// <summary>The pure rules of the chrome: theme cycle, drawer arithmetic, text helpers.</summary>
    public static class RevoChrome
    {
        public static readonly string[] ThemeCycle = { "follow", "dark", "light" };
        public const double BarGap = 8.0;
        public const double StackGap = 4.0;

        public static string NextTheme(string setting)
        {
            int i = Array.IndexOf(ThemeCycle, setting);
            if (i < 0) i = 0;
            return ThemeCycle[(i + 1) % ThemeCycle.Length];
        }

        /// <summary>follow + canvas dark gives dark; canvas unknown gives dark, the house default.</summary>
        public static string ResolveTheme(string setting, bool? canvasDark)
        {
            if (setting == "dark") return "dark";
            if (setting == "light") return "light";
            if (canvasDark == null) return "dark";
            return canvasDark.Value ? "dark" : "light";
        }

        public static string ThemeChipText(string setting)
        {
            if (setting == "dark") return "Dark";
            if (setting == "light") return "Light";
            return "Auto";
        }

        public static double EaseOutCubic(double t)
        {
            t = Math.Max(0.0, Math.Min(1.0, t));
            return 1.0 - Math.Pow(1.0 - t, 3);
        }

        public static double ParkTop(double workTop, double workBottom, double barHeight, int slot)
        {
            double top = workBottom - BarGap - barHeight - slot * (barHeight + StackGap);
            return Math.Max(workTop, top);
        }

        public static double ReopenTop(double savedTop, double parkedTop, double barTop, double fullHeight, double workTop, double workBottom)
        {
            double top;
            if (Math.Abs(barTop - parkedTop) < 1.0) top = savedTop;
            else
            {
                top = barTop;
                if (top + fullHeight > workBottom) top = workBottom - fullHeight;
            }
            if (top < workTop) top = workTop;
            return top;
        }

        public static int FreeSlot(ICollection<int> used)
        {
            int s = 0;
            while (used.Contains(s)) s++;
            return s;
        }

        /// <summary>Every word typed has to appear in the value, any order.</summary>
        public static bool MatchesText(string value, string term)
        {
            string[] words = (term ?? "").ToLowerInvariant().Split(new[] { ' ', '\t', '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries);
            if (words.Length == 0) return true;
            string hay = (value ?? "").ToLowerInvariant();
            foreach (string w in words)
                if (hay.IndexOf(w, StringComparison.Ordinal) < 0) return false;
            return true;
        }

        public static bool CtrlDown()
        {
            return (Keyboard.Modifiers & ModifierKeys.Control) == ModifierKeys.Control;
        }

        public static bool ShiftDown()
        {
            return (Keyboard.Modifiers & ModifierKeys.Shift) == ModifierKeys.Shift;
        }

        /// <summary>Own a modeless window to Revit or it slips behind Revit.</summary>
        public static void OwnToRevit(Window window, UIApplication uiapp)
        {
            try
            {
                new WindowInteropHelper(window).Owner = uiapp.MainWindowHandle;
            }
            catch (Exception)
            {
            }
        }

        /// <summary>Run after the current event has finished (dispatcher, background priority).</summary>
        public static void Later(Window window, Action fn)
        {
            try
            {
                window.Dispatcher.BeginInvoke(DispatcherPriority.Background, fn);
            }
            catch (Exception)
            {
                fn();
            }
        }

        /// <summary>(top, bottom) and (left, right) of the work area of the window's own screen, in WPF units.</summary>
        public static void WorkArea(Window window, out double left, out double top, out double right, out double bottom)
        {
            try
            {
                var helper = new WindowInteropHelper(window);
                System.Drawing.Rectangle area = System.Windows.Forms.Screen.FromHandle(helper.Handle).WorkingArea;
                double sx = 1.0, sy = 1.0;
                PresentationSource src = PresentationSource.FromVisual(window);
                if (src != null && src.CompositionTarget != null)
                {
                    Matrix m = src.CompositionTarget.TransformToDevice;
                    if (m.M11 != 0) sx = m.M11;
                    if (m.M22 != 0) sy = m.M22;
                }
                left = area.Left / sx;
                right = area.Right / sx;
                top = area.Top / sy;
                bottom = area.Bottom / sy;
            }
            catch (Exception)
            {
                Rect wa = SystemParameters.WorkArea;
                left = wa.Left;
                right = wa.Right;
                top = wa.Top;
                bottom = wa.Bottom;
            }
        }
    }

    /// <summary>
    /// Shrink to taskbar: slides the window to the bottom of its screen like a drawer closing, leaving only its
    /// header bar. Top is eased by hand on a 15 ms timer (never a Storyboard), the body is pinned for the trip,
    /// MinHeight and SizeToContent are relaxed and put back, the grips park with the window, a frame that throws
    /// lands the window at its end state. Port of cm_drawer.py.
    /// </summary>
    public sealed class WindowDrawer
    {
        private const double SlideMs = 280.0;
        private const int TickMs = 15;

        private readonly ChromeConfig config;
        private readonly Window window;
        private readonly FrameworkElement header;
        private readonly FrameworkElement body;
        private readonly Button button;
        private readonly UIElement shrinkGlyph;
        private readonly UIElement expandGlyph;
        private readonly UIElement grips;
        private readonly List<UIElement> siblings = new List<UIElement>();
        private readonly List<WindowDrawer> children = new List<WindowDrawer>();
        private readonly List<KeyValuePair<UIElement, Visibility>> savedVisibility = new List<KeyValuePair<UIElement, Visibility>>();
        private Visibility? savedGrips;
        private CornerRadius? savedCorners;
        private DispatcherTimer timer;
        private double savedLeft, savedTop, savedHeight, savedMinHeight;
        private SizeToContent savedStc;
        private ResizeMode savedResize;
        private int slot = -1;
        private double parkedTop;

        public bool Parked;
        public bool Sliding;
        public bool Busy;
        public WindowDrawer Owner;

        /// <summary>The snake_case layouts: header_bar, body, shrink_btn, shrink_glyph, expand_glyph, grips, root_grid.</summary>
        public WindowDrawer(ChromeConfig config, Window window, Func<string, FrameworkElement> find)
            : this(config, window, find("header_bar"), find("body"), find("shrink_btn") as Button, find("shrink_glyph"), find("expand_glyph"), find("grips"),
                   ChildrenOf(find("root_grid") as Panel, find("header_bar"), find("grips")))
        {
        }

        public WindowDrawer(ChromeConfig config, Window window, FrameworkElement header, FrameworkElement body, Button button,
                            UIElement shrinkGlyph, UIElement expandGlyph, UIElement grips, IEnumerable<UIElement> siblings)
        {
            this.config = config;
            this.window = window;
            this.header = header;
            this.body = body;
            this.button = button;
            this.shrinkGlyph = shrinkGlyph;
            this.expandGlyph = expandGlyph;
            this.grips = grips;
            if (siblings != null) this.siblings.AddRange(siblings);
            if (button != null) button.Click += (s, a) => Toggle();
            window.Closed += (s, a) => Released();
            SetGlyphs(false);
        }

        /// <summary>Every child of a panel except the header and the grips: what is collapsed while the window is parked.</summary>
        public static List<UIElement> ChildrenOf(Panel root, UIElement header, UIElement grips)
        {
            var list = new List<UIElement>();
            if (root == null) return list;
            foreach (UIElement child in root.Children)
                if (!ReferenceEquals(child, header) && !ReferenceEquals(child, grips)) list.Add(child);
            return list;
        }

        public void SetOwner(WindowDrawer owner)
        {
            Owner = owner;
            if (owner != null) owner.children.Add(this);
        }

        public void Toggle()
        {
            if (Sliding) return;
            if (Parked) Expand();
            else Shrink();
        }

        private void SetGlyphs(bool parked)
        {
            try
            {
                if (shrinkGlyph != null) shrinkGlyph.Visibility = parked ? Visibility.Collapsed : Visibility.Visible;
                if (expandGlyph != null) expandGlyph.Visibility = parked ? Visibility.Visible : Visibility.Collapsed;
                if (button != null)
                {
                    button.Tag = parked ? "shrunk" : "";
                    button.ToolTip = parked ? "Bring the window back (Ctrl+Shift+H)" : "Shrink to taskbar (Ctrl+Shift+H)";
                }
            }
            catch (Exception)
            {
            }
        }

        private static void Release(Window w)
        {
            try
            {
                w.BeginAnimation(Window.TopProperty, null);
            }
            catch (Exception)
            {
            }
            try
            {
                w.BeginAnimation(Window.HeightProperty, null);
            }
            catch (Exception)
            {
            }
        }

        private double BarHeight()
        {
            try
            {
                return header.ActualHeight + 4.0;
            }
            catch (Exception)
            {
                return 50.0;
            }
        }

        public void Shrink(bool instant = false)
        {
            if (Parked || Sliding) return;
            Window w = window;
            Release(w);
            if (Owner != null && !Owner.Parked) Owner.Shrink(true);
            savedLeft = w.Left;
            savedTop = w.Top;
            savedHeight = w.Height;
            savedMinHeight = w.MinHeight;
            savedStc = w.SizeToContent;
            savedResize = w.ResizeMode;
            try
            {
                if (double.IsNaN(savedHeight)) savedHeight = w.ActualHeight;
            }
            catch (Exception)
            {
            }
            try
            {
                w.MinHeight = 0;
                w.SizeToContent = SizeToContent.Manual;
                w.ResizeMode = ResizeMode.NoResize;   // a resize grip would sit on the parked bar and swallow clicks
                w.Height = savedHeight;
            }
            catch (Exception)
            {
            }
            try
            {
                body.Height = body.ActualHeight;
                body.VerticalAlignment = VerticalAlignment.Top;
            }
            catch (Exception)
            {
            }
            var used = new List<int>();
            foreach (WindowDrawer d in config.Parked) used.Add(d.slot);
            slot = RevoChrome.FreeSlot(used);
            config.Parked.Add(this);
            double bar = BarHeight();
            double l, t, r, b;
            RevoChrome.WorkArea(w, out l, out t, out r, out b);
            parkedTop = RevoChrome.ParkTop(t, b, bar, slot);
            SetGlyphs(true);
            Parked = true;
            if (instant) LandParked(bar);
            else Slide(w.Top, parkedTop, () => LandParked(bar));
        }

        private void LandParked(double bar)
        {
            Release(window);
            savedVisibility.Clear();
            foreach (UIElement el in siblings)
            {
                try
                {
                    savedVisibility.Add(new KeyValuePair<UIElement, Visibility>(el, el.Visibility));
                    el.Visibility = Visibility.Collapsed;
                }
                catch (Exception)
                {
                }
            }
            if (grips != null)
            {
                try
                {
                    savedGrips = grips.Visibility;
                    grips.Visibility = Visibility.Collapsed;
                }
                catch (Exception)
                {
                }
            }
            // the bar stands alone, so its top corners are not the only rounded ones
            var headerBorder = header as Border;
            if (headerBorder != null)
            {
                try
                {
                    savedCorners = headerBorder.CornerRadius;
                    headerBorder.CornerRadius = new CornerRadius(5);
                }
                catch (Exception)
                {
                }
            }
            try
            {
                window.Top = parkedTop;
                window.Height = bar;
            }
            catch (Exception)
            {
            }
        }

        public void Expand(bool instant = false)
        {
            if (!Parked || Sliding) return;
            Window w = window;
            Release(w);
            double l, t, r, b;
            RevoChrome.WorkArea(w, out l, out t, out r, out b);
            double target = RevoChrome.ReopenTop(savedTop, parkedTop, w.Top, savedHeight, t, b);
            double start = w.Top;
            try
            {
                w.Height = savedHeight;
            }
            catch (Exception)
            {
            }
            foreach (var entry in savedVisibility)
            {
                try
                {
                    entry.Key.Visibility = entry.Value;
                }
                catch (Exception)
                {
                }
            }
            savedVisibility.Clear();
            if (grips != null && savedGrips != null)
            {
                try
                {
                    grips.Visibility = savedGrips.Value;
                }
                catch (Exception)
                {
                }
            }
            var headerCorners = header as Border;
            if (headerCorners != null && savedCorners != null)
            {
                try
                {
                    headerCorners.CornerRadius = savedCorners.Value;
                }
                catch (Exception)
                {
                }
            }
            SetGlyphs(false);
            Parked = false;
            config.Parked.Remove(this);
            slot = -1;
            if (instant) LandOpen(target);
            else Slide(start, target, () => LandOpen(target));
            if (Owner != null && Owner.Parked) Owner.Expand(true);
        }

        private void LandOpen(double target)
        {
            Release(window);
            try
            {
                window.Top = target;
                window.MinHeight = savedMinHeight;
                window.SizeToContent = savedStc;
                window.ResizeMode = savedResize;
            }
            catch (Exception)
            {
            }
            try
            {
                body.Height = double.NaN;
                body.VerticalAlignment = VerticalAlignment.Stretch;
            }
            catch (Exception)
            {
            }
        }

        /// <summary>Window closing: free the slot, bring a parked owner back.</summary>
        private void Released()
        {
            config.Parked.Remove(this);
            slot = -1;
            try
            {
                if (timer != null) timer.Stop();
            }
            catch (Exception)
            {
            }
            if (Owner != null)
            {
                Owner.children.Remove(this);
                if (Owner.Parked) Owner.Expand(true);
            }
        }

        private void Slide(double start, double end, Action land)
        {
            Sliding = true;
            int t0 = Environment.TickCount;
            Action finish = () =>
            {
                try
                {
                    if (timer != null) timer.Stop();
                }
                catch (Exception)
                {
                }
                Sliding = false;
                try
                {
                    land();
                }
                catch (Exception)
                {
                }
            };
            try
            {
                timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(TickMs) };
                timer.Tick += (s, a) =>
                {
                    try
                    {
                        double t = (Environment.TickCount - t0) / SlideMs;
                        if (t >= 1.0)
                        {
                            finish();
                            return;
                        }
                        window.Top = start + (end - start) * RevoChrome.EaseOutCubic(t);
                    }
                    catch (Exception)
                    {
                        finish();
                    }
                };
                timer.Start();
            }
            catch (Exception)
            {
                finish();
            }
        }

        /// <summary>True when the key is consumed.</summary>
        public bool OnKey(Key key, bool ctrl, bool shift)
        {
            if (ctrl && shift && key == Key.H)
            {
                Toggle();
                return true;
            }
            if (Sliding) return true;
            if (Parked)
            {
                if (key == Key.Escape || key == Key.Return || key == Key.Enter || key == Key.F11) Expand();
                return true;
            }
            return false;
        }

        /// <summary>True when the drawer took the double click (parked: reopen, not maximise).</summary>
        public bool OnHeaderDoubleClick()
        {
            if (Parked)
            {
                if (!Sliding) Expand();
                return true;
            }
            return false;
        }

        public bool CanDrag()
        {
            return !Sliding && !Busy;
        }
    }

    /// <summary>
    /// A RevoBIM window built from a layout: layout + Theme.xaml + palette + chrome + drawer.
    /// Port of ThemedWindow in cm_chrome.py.
    /// </summary>
    public class ThemedWindow
    {
        private static readonly Dictionary<string, string> Glyphs = new Dictionary<string, string>
        {
            { "follow", "M 7,0 A 7,7 0 1 1 7,14 A 7,7 0 1 1 7,0 Z M 7,2 L 7,12 A 5,5 0 0 1 7,2 Z" },
            { "dark", "M 9,0 A 7,7 0 1 0 14,9 A 5.5,5.5 0 1 1 9,0 Z" },
            { "light", "M 7,3.5 A 3.5,3.5 0 1 1 7,10.5 A 3.5,3.5 0 1 1 7,3.5 Z M 6.3,0 L 7.7,0 L 7.7,2 L 6.3,2 Z M 6.3,12 L 7.7,12 L 7.7,14 L 6.3,14 Z M 0,6.3 L 2,6.3 L 2,7.7 L 0,7.7 Z M 12,6.3 L 14,6.3 L 14,7.7 L 12,7.7 Z" },
        };

        protected readonly ChromeConfig Config;
        public readonly Window Win;
        public readonly ThemedWindow OwnerWindow;
        public readonly WindowDrawer Drawer;
        public string Resolved;
        public bool FullScreen;
        private double[] savedBounds;

        public ThemedWindow(ChromeConfig config, string layoutFile, ThemedWindow owner = null)
        {
            Config = config;
            Win = (Window)XamlReader.Parse(ReadResource(config.LayoutPrefix + layoutFile));
            OwnerWindow = owner;
            Win.Resources.MergedDictionaries.Add((ResourceDictionary)XamlReader.Parse(ReadResource(config.LayoutPrefix + config.ThemeFile)));
            Resolved = config.Resolved();
            ApplyPalette(Win, Resolved);
            Drawer = new WindowDrawer(config, Win, Find);
            if (owner != null)
            {
                try
                {
                    Win.Owner = owner.Win;
                    Drawer.SetOwner(owner.Drawer);
                    Win.WindowStartupLocation = owner.Drawer.Parked ? WindowStartupLocation.CenterScreen : WindowStartupLocation.CenterOwner;
                }
                catch (Exception)
                {
                }
            }
            WireChrome();
            config.Open.Add(this);
            Win.Closed += (s, a) =>
            {
                config.Open.Remove(this);
                OnClosed();
            };
        }

        public static string ReadResource(string name)
        {
            using (Stream stream = typeof(ThemedWindow).Assembly.GetManifestResourceStream(name))
            {
                if (stream == null) throw new FileNotFoundException("embedded layout " + name + " was not found");
                using (var reader = new StreamReader(stream, System.Text.Encoding.UTF8)) return reader.ReadToEnd();
            }
        }

        public FrameworkElement Find(string name)
        {
            try
            {
                return Win.FindName(name) as FrameworkElement;
            }
            catch (Exception)
            {
                return null;
            }
        }

        public T Find<T>(string name) where T : class
        {
            return Find(name) as T;
        }

        /// <summary>Writes every palette brush onto the element's own resources, in front of the merged theme.</summary>
        public void ApplyPalette(FrameworkElement element, string resolved)
        {
            IDictionary<string, string> pal = Config.Palette(resolved);
            foreach (KeyValuePair<string, string> entry in pal)
            {
                try
                {
                    var brush = new SolidColorBrush((Color)ColorConverter.ConvertFromString(entry.Value));
                    brush.Freeze();
                    element.Resources[entry.Key] = brush;
                }
                catch (Exception)
                {
                }
            }
        }

        /// <summary>Theme dictionary and the current palette onto an element that is not in a window's tree (a context menu).</summary>
        public void Dress(FrameworkElement element)
        {
            try
            {
                element.Resources.MergedDictionaries.Add((ResourceDictionary)XamlReader.Parse(ReadResource(Config.LayoutPrefix + Config.ThemeFile)));
            }
            catch (Exception)
            {
            }
            ApplyPalette(element, Resolved);
        }

        public static void LoadIcon(Image image, string resource)
        {
            if (image == null) return;
            try
            {
                using (Stream stream = typeof(ThemedWindow).Assembly.GetManifestResourceStream(resource))
                {
                    if (stream == null) return;
                    var bmp = new BitmapImage();
                    bmp.BeginInit();
                    bmp.StreamSource = stream;
                    bmp.CacheOption = BitmapCacheOption.OnLoad;
                    bmp.EndInit();
                    bmp.Freeze();
                    image.Source = bmp;
                }
            }
            catch (Exception)
            {
            }
        }

        private void WireChrome()
        {
            Image icon = Find<Image>("icon_img");
            LoadIcon(icon, Config.IconResource);
            // Three slow clicks on the logo open the RevoBIM Arcade.
            EggHook.Attach(Win, () => Resolved, icon);
            SetText("version_text", "v" + Config.Version);
            Button close = Find<Button>("close_btn");
            if (close != null) close.Click += (s, a) => Win.Close();
            Button theme = Find<Button>("theme_btn");
            if (theme != null) theme.Click += OnTheme;
            FrameworkElement header = Find("header_bar");
            if (header != null) header.MouseLeftButtonDown += OnHeaderDown;
            Win.PreviewKeyDown += OnKeyBase;
            Win.Activated += OnActivated;
            Button max = Find<Button>("max_btn");
            if (max != null) max.Click += (s, a) => ToggleFullScreen();
            WireGrips();
            ShowThemeChip();
        }

        public void SetText(string name, string text)
        {
            var tb = Find(name) as TextBlock;
            if (tb != null) tb.Text = text;
        }

        private void ShowThemeChip()
        {
            string setting = Config.ThemeSetting();
            try
            {
                SetText("theme_text", RevoChrome.ThemeChipText(setting));
                var glyph = Find("theme_glyph") as Path;
                if (glyph != null)
                {
                    string data;
                    if (!Glyphs.TryGetValue(setting, out data)) data = Glyphs["follow"];
                    glyph.Data = Geometry.Parse(data);
                }
            }
            catch (Exception)
            {
            }
        }

        public void Paint(string resolved)
        {
            Resolved = resolved;
            ApplyPalette(Win, resolved);
            ShowThemeChip();
            OnRepainted();
        }

        /// <summary>Windows with code-built, locally set brushes repaint them here.</summary>
        protected virtual void OnRepainted()
        {
        }

        private void OnTheme(object sender, RoutedEventArgs args)
        {
            Config.SetThemeSetting(RevoChrome.NextTheme(Config.ThemeSetting()));
            Config.Log("theme -> " + Config.ThemeSetting());
            Config.RepaintAll();
        }

        private void OnActivated(object sender, EventArgs args)
        {
            if (Config.ThemeSetting() != "follow") return;
            try
            {
                if (Config.Resolved() != Resolved) Config.RepaintAll();
            }
            catch (Exception)
            {
            }
        }

        private void OnHeaderDown(object sender, MouseButtonEventArgs args)
        {
            try
            {
                if (args.ClickCount == 2)
                {
                    if (!Drawer.OnHeaderDoubleClick() && Find("max_btn") != null) ToggleFullScreen();
                    args.Handled = true;
                    return;
                }
                if (Drawer.CanDrag())
                {
                    if (FullScreen) FullScreen = false;
                    Win.DragMove();
                }
            }
            catch (Exception)
            {
            }
        }

        private void OnKeyBase(object sender, KeyEventArgs args)
        {
            try
            {
                bool ctrl = RevoChrome.CtrlDown(), shift = RevoChrome.ShiftDown();
                Key key = args.Key == Key.System ? args.SystemKey : args.Key;
                if (Drawer.OnKey(key, ctrl, shift))
                {
                    args.Handled = true;
                    return;
                }
                if (key == Key.F11 && Find("max_btn") != null)
                {
                    ToggleFullScreen();
                    args.Handled = true;
                    return;
                }
                OnKey(args, key, ctrl, shift);
            }
            catch (Exception)
            {
                Config.Log("key handler failed");
            }
        }

        protected virtual void OnKey(KeyEventArgs args, Key key, bool ctrl, bool shift)
        {
        }

        public void ToggleFullScreen()
        {
            Window w = Win;
            if (Drawer.Parked)
            {
                Drawer.Expand();
                return;
            }
            if (!FullScreen)
            {
                savedBounds = new[] { w.Left, w.Top, w.Width, w.Height };
                double l, t, r, b;
                RevoChrome.WorkArea(w, out l, out t, out r, out b);
                w.Left = l;
                w.Top = t;
                w.Width = r - l;
                w.Height = b - t;
                FullScreen = true;
            }
            else
            {
                if (savedBounds != null)
                {
                    w.Left = savedBounds[0];
                    w.Top = savedBounds[1];
                    w.Width = savedBounds[2];
                    w.Height = savedBounds[3];
                }
                FullScreen = false;
            }
        }

        private void WireGrips()
        {
            foreach (string name in new[] { "grip_n", "grip_s", "grip_w", "grip_e", "grip_nw", "grip_ne", "grip_sw", "grip_se" })
            {
                var thumb = Find(name) as Thumb;
                if (thumb == null) continue;
                string suffix = name.Substring(5);
                thumb.DragDelta += (s, a) => Grip(suffix, a);
            }
        }

        private void Grip(string suffix, DragDeltaEventArgs args)
        {
            try
            {
                Window w = Win;
                if (Drawer.Parked || Drawer.Sliding) return;
                FullScreen = false;
                double dx = args.HorizontalChange, dy = args.VerticalChange;
                if (suffix.Contains("e")) w.Width = Math.Max(w.MinWidth, w.Width + dx);
                if (suffix.Contains("s")) w.Height = Math.Max(w.MinHeight, w.Height + dy);
                if (suffix.Contains("w"))
                {
                    double nw = Math.Max(w.MinWidth, w.Width - dx);
                    w.Left = w.Left + (w.Width - nw);
                    w.Width = nw;
                }
                if (suffix.Contains("n"))
                {
                    double nh = Math.Max(w.MinHeight, w.Height - dy);
                    w.Top = w.Top + (w.Height - nh);
                    w.Height = nh;
                }
            }
            catch (Exception)
            {
            }
        }

        protected virtual void OnClosed()
        {
        }
    }
}
