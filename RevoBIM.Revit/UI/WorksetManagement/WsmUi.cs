using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Interop;
using System.Windows.Markup;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Threading;
using System.Xml;
using RevoBIM.Tools.WorksetManagement;

namespace RevoBIM.UI.WorksetManagement
{
    /// <summary>
    /// Window furniture shared by every Workset Management window: XAML loading, the palette swap, the chrome
    /// (drag, eight resize grips, full screen by bounds, F11), the shrink-to-taskbar drawer, the small themed
    /// dialogs (message, confirm, text prompt, pick one, delete and merge). Port of wsm_ui.py.
    /// </summary>
    public static class WsmUi
    {
        private const string LayoutPrefix = "RevoBIM.UI.WorksetManagement.Layouts.";

        /// <summary>The palette in use, so dialogs open in the main window's colours.</summary>
        public static string Current = "dark";

        private static readonly Dictionary<string, SolidColorBrush> BrushCache = new Dictionary<string, SolidColorBrush>();

        // ================================================================ loading

        public static string ReadLayout(string fileName)
        {
            using (Stream stream = typeof(WsmUi).Assembly.GetManifestResourceStream(LayoutPrefix + fileName))
            {
                if (stream == null) throw new FileNotFoundException("embedded layout " + LayoutPrefix + fileName + " was not found");
                using (var reader = new StreamReader(stream, Encoding.UTF8)) return reader.ReadToEnd();
            }
        }

        public static object ParseXaml(string fileName)
        {
            using (var reader = XmlReader.Create(new StringReader(ReadLayout(fileName)))) return XamlReader.Load(reader);
        }

        /// <summary>A fresh copy per window - one parsed dictionary shared between several windows' MergedDictionaries is not something to depend on.</summary>
        public static ResourceDictionary ThemeDictionary() { return (ResourceDictionary)ParseXaml("Theme.xaml"); }

        public static SolidColorBrush Brush(string hex)
        {
            SolidColorBrush cached;
            if (BrushCache.TryGetValue(hex, out cached)) return cached;
            var made = new SolidColorBrush((System.Windows.Media.Color)ColorConverter.ConvertFromString(hex));
            try { made.Freeze(); } catch (Exception) { }
            BrushCache[hex] = made;
            return made;
        }

        /// <summary>Write the palette onto the element's own resources, in front of the merged Theme.xaml, so every DynamicResource re-resolves on the spot.</summary>
        public static string ApplyPalette(FrameworkElement element, string name)
        {
            if (!WsmCore.Palettes.ContainsKey(name)) name = "dark";
            foreach (var pair in WsmCore.Palettes[name])
            {
                try { element.Resources[pair.Key] = Brush(pair.Value); } catch (Exception) { }
            }
            Current = name;
            return name;
        }

        public static void ApplyPalette(ContextMenu menu, string name)
        {
            if (!WsmCore.Palettes.ContainsKey(name)) name = "dark";
            foreach (var pair in WsmCore.Palettes[name])
            {
                try { menu.Resources[pair.Key] = Brush(pair.Value); } catch (Exception) { }
            }
        }

        public static T Prepare<T>(T window) where T : FrameworkElement
        {
            window.Resources.MergedDictionaries.Add(ThemeDictionary());
            ApplyPalette(window, Current);
            return window;
        }

        public static Window LoadWindow(string fileName)
        {
            var window = ParseXaml(fileName) as Window;
            if (window == null) throw new InvalidCastException(fileName + " is not a Window");
            return Prepare(window);
        }

        public static void Res(FrameworkElement element, DependencyProperty prop, string key) { element.SetResourceReference(prop, key); }

        public static void Style(FrameworkElement element, string key) { element.SetResourceReference(FrameworkElement.StyleProperty, key); }

        /// <summary>The tool's icon, from the embedded resource, as a frozen image.</summary>
        public static BitmapImage LoadIcon()
        {
            try
            {
                using (Stream stream = typeof(WsmUi).Assembly.GetManifestResourceStream("RevoBIM.Resources.WorksetManagement.icon.png"))
                {
                    if (stream == null) return null;
                    var image = new BitmapImage();
                    image.BeginInit();
                    image.StreamSource = stream;
                    image.CacheOption = BitmapCacheOption.OnLoad;
                    image.EndInit();
                    image.Freeze();
                    return image;
                }
            }
            catch (Exception) { return null; }
        }

        /// <summary>Run func after the current event has finished.</summary>
        public static void Later(Window window, Action func, DispatcherPriority priority = DispatcherPriority.Background)
        {
            try { window.Dispatcher.BeginInvoke(priority, func); }
            catch (Exception) { func(); }
        }

        public static DispatcherTimer Debounce(int milliseconds, Action func)
        {
            var timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(milliseconds) };
            timer.Tick += (s, a) => { timer.Stop(); func(); };
            return timer;
        }

        public static DispatcherTimer Repeat(int milliseconds, EventHandler handler)
        {
            var timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(milliseconds) };
            timer.Tick += handler;
            timer.Start();
            return timer;
        }

        /// <summary>Owned by Revit's main window, so a modeless window floats in front of Revit instead of slipping behind it. Before Show().</summary>
        public static void Own(Window window, IntPtr revitHandle)
        {
            try { new WindowInteropHelper(window).Owner = revitHandle; } catch (Exception) { }
        }

        public static void Kick(DispatcherTimer timer) { timer.Stop(); timer.Start(); }

        public static TextBlock TextBlock(string text, double size = 12, string key = "TextBrush", bool bold = false, bool wrap = false)
        {
            var block = new TextBlock { Text = WsmCore.Txt(text), FontSize = size, VerticalAlignment = VerticalAlignment.Center };
            Res(block, System.Windows.Controls.TextBlock.ForegroundProperty, key);
            if (bold) block.FontWeight = FontWeights.SemiBold;
            if (wrap) block.TextWrapping = TextWrapping.Wrap; else block.TextTrimming = TextTrimming.CharacterEllipsis;
            return block;
        }

        private static DependencyObject ParentOf(DependencyObject node)
        {
            DependencyObject parent = null;
            try { if (node is Visual || node is System.Windows.Media.Media3D.Visual3D) parent = VisualTreeHelper.GetParent(node); } catch (Exception) { }
            if (parent == null) { try { parent = LogicalTreeHelper.GetParent(node); } catch (Exception) { } }
            return parent;
        }

        /// <summary>True when source sits inside any of targets, walking up to stop.</summary>
        public static bool IsWithin(object source, IEnumerable<object> targets, object stop)
        {
            var node = source as DependencyObject;
            var list = targets.ToList();
            for (int i = 0; i < 60; i++)
            {
                if (node == null || ReferenceEquals(node, stop)) return false;
                if (list.Any(t => ReferenceEquals(t, node))) return true;
                node = ParentOf(node);
            }
            return false;
        }

        /// <summary>The nearest element of type T at or above source, or null.</summary>
        public static T Ancestor<T>(object source, object stop = null) where T : class
        {
            var node = source as DependencyObject;
            for (int i = 0; i < 60; i++)
            {
                if (node == null || ReferenceEquals(node, stop)) return null;
                var hit = node as T;
                if (hit != null) return hit;
                node = ParentOf(node);
            }
            return null;
        }

        public static bool TextBoxHasFocus()
        {
            try { return Keyboard.FocusedElement is TextBox; } catch (Exception) { return false; }
        }

        public static bool CopyText(string text)
        {
            try { Clipboard.SetText(WsmCore.Txt(text)); return true; } catch (Exception) { return false; }
        }

        // ================================================================ errors

        private static DateTime _errorShown = DateTime.MinValue;
        private const double ErrorQuietSeconds = 4.0;

        /// <summary>Log the failure with its traceback, then say so - at most once every few seconds, so a failing timer cannot bury the user in dialogs.</summary>
        public static void Report(Window owner, string where, Exception error)
        {
            string detail = error == null ? "" : error.ToString();
            WsmCore.LogError(where, detail);
            if ((DateTime.Now - _errorShown).TotalSeconds < ErrorQuietSeconds) return;
            _errorShown = DateTime.Now;
            try
            {
                CopyText("Workset Management v" + WsmCore.Version + " - " + where + "\n" + detail);
                Message(owner, "Something went wrong", new[]
                {
                    where + " failed.", "", "The details are copied to the clipboard and saved in", "   " + WsmCore.ErrorPath,
                    "Paste them to Claude, or press the bug button top right for a full debug report.", "", detail,
                }, 760, 480);
            }
            catch (Exception) { }
        }

        /// <summary>Run an event handler's work: an exception is logged and reported in a themed dialog instead of escaping into WPF.</summary>
        public static void Try(Func<Window> owner, string where, Action action)
        {
            try { action(); }
            catch (Exception err)
            {
                Window w = null;
                try { w = owner == null ? null : owner(); } catch (Exception) { }
                Report(w, where, err);
            }
        }

        // ================================================================ chrome

        /// <summary>
        /// Drag by the header, eight resize grips, full screen by bounds. A borderless AllowsTransparency window has
        /// nothing hit-testable in its frame, so WPF never resizes it - hence the grips. Full screen replaces the bounds
        /// with the working area of the screen the window is on.
        /// </summary>
        public class Chrome
        {
            private const int Grip = 5;
            private readonly Window _window;
            private readonly FrameworkElement _header;
            private readonly List<object> _skip;
            public bool Full;
            private double[] _saved;
            public readonly WindowDrawer Drawer;

            public Chrome(Window window, FrameworkElement header, Panel gripLayer, Button fullButton, IEnumerable<object> skip, Button shrinkButton = null)
            {
                _window = window; _header = header; _skip = skip.ToList();
                if (shrinkButton != null)
                {
                    _skip.Add(shrinkButton);
                    Drawer = new WindowDrawer(window, header, shrinkButton, gripLayer);
                }
                header.MouseLeftButtonDown += OnHeaderDown;
                window.PreviewKeyDown += OnKey;
                if (fullButton != null) { fullButton.Click += (s, a) => Toggle(); _skip.Add(fullButton); }
                if (gripLayer != null) AddGrips(gripLayer);
            }

            public bool Parked { get { return Drawer != null && Drawer.Parked; } }

            private void AddGrips(Panel layer)
            {
                int g = Grip;
                var specs = new[]
                {
                    new { Side = "left", H = HorizontalAlignment.Left, V = VerticalAlignment.Stretch, W = (double?)g, Ht = (double?)null, C = Cursors.SizeWE },
                    new { Side = "right", H = HorizontalAlignment.Right, V = VerticalAlignment.Stretch, W = (double?)g, Ht = (double?)null, C = Cursors.SizeWE },
                    new { Side = "top", H = HorizontalAlignment.Stretch, V = VerticalAlignment.Top, W = (double?)null, Ht = (double?)g, C = Cursors.SizeNS },
                    new { Side = "bottom", H = HorizontalAlignment.Stretch, V = VerticalAlignment.Bottom, W = (double?)null, Ht = (double?)g, C = Cursors.SizeNS },
                    new { Side = "topleft", H = HorizontalAlignment.Left, V = VerticalAlignment.Top, W = (double?)(g * 2), Ht = (double?)(g * 2), C = Cursors.SizeNWSE },
                    new { Side = "topright", H = HorizontalAlignment.Right, V = VerticalAlignment.Top, W = (double?)(g * 2), Ht = (double?)(g * 2), C = Cursors.SizeNESW },
                    new { Side = "bottomleft", H = HorizontalAlignment.Left, V = VerticalAlignment.Bottom, W = (double?)(g * 2), Ht = (double?)(g * 2), C = Cursors.SizeNESW },
                    new { Side = "bottomright", H = HorizontalAlignment.Right, V = VerticalAlignment.Bottom, W = (double?)(g * 2), Ht = (double?)(g * 2), C = Cursors.SizeNWSE },
                };
                foreach (var spec in specs)
                {
                    var thumb = new Thumb { HorizontalAlignment = spec.H, VerticalAlignment = spec.V, Cursor = spec.C };
                    WsmUi.Style(thumb, "WsGrip");
                    if (spec.W.HasValue) thumb.Width = spec.W.Value;
                    if (spec.Ht.HasValue) thumb.Height = spec.Ht.Value;
                    string side = spec.Side;
                    thumb.DragDelta += (s, a) => { try { Resize(side, a.HorizontalChange, a.VerticalChange); } catch (Exception) { } };
                    layer.Children.Add(thumb);
                }
            }

            private void Resize(string side, double dx, double dy)
            {
                if (Parked) return;
                if (Full) { Full = false; _saved = null; }
                if (side.Contains("left")) { double w = Math.Max(_window.MinWidth, _window.Width - dx); _window.Left += _window.Width - w; _window.Width = w; }
                if (side.Contains("right")) _window.Width = Math.Max(_window.MinWidth, _window.Width + dx);
                if (side.Contains("top")) { double h = Math.Max(_window.MinHeight, _window.Height - dy); _window.Top += _window.Height - h; _window.Height = h; }
                if (side.Contains("bottom")) _window.Height = Math.Max(_window.MinHeight, _window.Height + dy);
            }

            private void OnHeaderDown(object sender, MouseButtonEventArgs args)
            {
                try
                {
                    if (IsWithin(args.OriginalSource, _skip, _header)) return;
                    if (args.ClickCount == 2)
                    {
                        if (Parked) Drawer.Open(); else Toggle();
                        return;
                    }
                    if (Full) LeaveFull();
                    _window.DragMove();
                }
                catch (Exception) { }
            }

            private void OnKey(object sender, KeyEventArgs args)
            {
                try
                {
                    if (Parked) return;
                    if (args.Key == Key.F11) { Toggle(); args.Handled = true; }
                    else if (args.Key == Key.Escape && Full) { LeaveFull(); args.Handled = true; }
                }
                catch (Exception) { }
            }

            public void Toggle()
            {
                if (Parked) { Drawer.Open(); return; }
                if (Full) LeaveFull(); else EnterFull();
            }

            private void EnterFull()
            {
                double[] area;
                try { area = WorkArea(_window); } catch (Exception) { return; }
                _saved = new[] { _window.Left, _window.Top, _window.Width, _window.Height };
                _window.Left = area[0]; _window.Top = area[1]; _window.Width = area[2]; _window.Height = area[3];
                Full = true;
            }

            private void LeaveFull()
            {
                if (_saved != null) { _window.Left = _saved[0]; _window.Top = _saved[1]; _window.Width = _saved[2]; _window.Height = _saved[3]; }
                _saved = null; Full = false;
            }
        }

        /// <summary>The working area of the screen the window is on, in WPF units - the window's own screen, not the primary, divided by the DPI scale.</summary>
        public static double[] WorkArea(Window window)
        {
            IntPtr handle = new WindowInteropHelper(window).Handle;
            System.Drawing.Rectangle area = System.Windows.Forms.Screen.FromHandle(handle).WorkingArea;
            double sx = 1.0, sy = 1.0;
            try
            {
                Matrix m = PresentationSource.FromVisual(window).CompositionTarget.TransformToDevice;
                sx = m.M11 == 0 ? 1.0 : m.M11; sy = m.M22 == 0 ? 1.0 : m.M22;
            }
            catch (Exception) { }
            return new[] { area.Left / sx, area.Top / sy, area.Width / sx, area.Height / sy };
        }

        public static DispatcherTimer MakeTimer(int milliseconds) { return new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(milliseconds) }; }

        // Every drawer the tool has made, so parked bars can share out slots and a dialog can find its owner's drawer.
        public static readonly List<WindowDrawer> Drawers = new List<WindowDrawer>();

        public static WindowDrawer DrawerOf(Window window)
        {
            return window == null ? null : Drawers.FirstOrDefault(d => ReferenceEquals(d.Window, window));
        }

        /// <summary>Open a parked owner at once before a dialog is shown over it, or the dialog would centre on a 50px bar.</summary>
        public static void BringBack(Window owner)
        {
            WindowDrawer drawer = DrawerOf(owner);
            if (drawer != null && (drawer.Parked || drawer.Sliding))
            {
                drawer.Stop();
                if (drawer.Parked) drawer.Open(false, true);
            }
        }

        /// <summary>
        /// Shrink to taskbar. The window slides down like a drawer closing until only its header floats above the
        /// taskbar. No Storyboard and no BeginAnimation: an animation holds its end value and outranks every later
        /// assignment. Top is eased by hand on a 15ms timer; Height is set once, on landing and on opening.
        /// </summary>
        public class WindowDrawer
        {
            public readonly Window Window;
            private readonly FrameworkElement _header;
            private readonly Button _button;
            private readonly Panel _grips;
            private readonly Stopwatch _clock = Stopwatch.StartNew();
            public bool Parked, Sliding;
            public int? Slot;
            private double[] _saved, _parkedAt;
            private List<KeyValuePair<UIElement, Visibility>> _hidden = new List<KeyValuePair<UIElement, Visibility>>();
            private double _restoreMinHeight;
            private SizeToContent? _restoreSize;
            private DispatcherTimer _timer;
            private WindowDrawer _tookOwner;
            public readonly List<string> Errors = new List<string>();

            public WindowDrawer(Window window, FrameworkElement header, Button button, Panel grips = null)
            {
                Window = window; _header = header; _button = button; _grips = grips;
                if (button != null) { button.Click += (s, a) => Toggle(); SetButton(false); }
                window.PreviewKeyDown += OnKey;
                window.Closed += (s, a) => { Stop(); Drawers.Remove(this); GiveOwnerBack(); };
                Drawers.Add(this);
            }

            public void Toggle()
            {
                if (Sliding) return;
                if (Parked) Open(); else Shrink();
            }

            private void OnKey(object sender, KeyEventArgs args)
            {
                try
                {
                    ModifierKeys modifiers = Keyboard.Modifiers;
                    ModifierKeys controlShift = ModifierKeys.Control | ModifierKeys.Shift;
                    if (args.Key == Key.H && (modifiers & controlShift) == controlShift) { Toggle(); args.Handled = true; return; }
                    if (!Parked) return;
                    if (args.Key == Key.Escape || args.Key == Key.Enter || args.Key == Key.F11) { Open(); args.Handled = true; }
                    else if ((modifiers & ModifierKeys.Alt) != ModifierKeys.Alt) args.Handled = true;
                }
                catch (Exception err) { Errors.Add(err.Message); }
            }

            private void SetButton(bool shrunk)
            {
                if (_button == null) return;
                try
                {
                    _button.Tag = shrunk ? "shrunk" : "";
                    _button.ToolTip = shrunk ? "Bring the window back (Ctrl+Shift+H)" : "Shrink to the taskbar so Revit can be seen (Ctrl+Shift+H)";
                }
                catch (Exception) { }
            }

            private double BarHeight()
            {
                double h = 0;
                try { h = _header.ActualHeight; } catch (Exception) { }
                return (h > 0 ? h : 46.0) + 2.0;
            }

            private FrameworkElement Root { get { return Window.Content as FrameworkElement; } }

            private List<UIElement> Siblings()
            {
                DependencyObject parent = LogicalTreeHelper.GetParent(_header) ?? VisualTreeHelper.GetParent(_header);
                var panel = parent as Panel;
                return panel == null ? new List<UIElement>() : panel.Children.Cast<UIElement>().Where(c => !ReferenceEquals(c, _header)).ToList();
            }

            private void Pin(double height)
            {
                try { Root.Height = height; Root.VerticalAlignment = VerticalAlignment.Top; } catch (Exception) { }
            }

            private void Unpin()
            {
                try { Root.Height = double.NaN; Root.VerticalAlignment = VerticalAlignment.Stretch; } catch (Exception) { }
            }

            public void Stop()
            {
                DispatcherTimer timer = _timer;
                _timer = null;
                if (timer != null) { try { timer.Stop(); } catch (Exception) { } }
            }

            private void Slide(double start, double end, Action landed, bool instant)
            {
                Sliding = true;
                if (instant) { Land(end, landed); return; }
                double began = _clock.Elapsed.TotalMilliseconds;
                try
                {
                    DispatcherTimer timer = MakeTimer(WsmCore.DrawerTickMs);
                    timer.Tick += (s, a) =>
                    {
                        try
                        {
                            double progress = (_clock.Elapsed.TotalMilliseconds - began) / WsmCore.DrawerMs;
                            Window.Top = WsmCore.Lerp(start, end, WsmCore.EaseOut(progress));
                            if (progress >= 1.0) Land(end, landed);
                        }
                        catch (Exception err) { Errors.Add(err.Message); Land(end, landed); }
                    };
                    _timer = timer;
                    timer.Start();
                }
                catch (Exception err) { Errors.Add(err.Message); Land(end, landed); }
            }

            private void Land(double end, Action landed)
            {
                Stop();
                try { Window.Top = end; } catch (Exception) { }
                try { landed(); } catch (Exception err) { Errors.Add(err.Message); }
                Sliding = false;
            }

            public void Shrink(bool instant = false)
            {
                if (Parked || Sliding) return;
                Window owner = null;
                try { owner = Window.Owner; } catch (Exception) { }
                WindowDrawer ownerDrawer = DrawerOf(owner);
                if (ownerDrawer != null && !ownerDrawer.Parked && !ownerDrawer.Sliding)
                {
                    ownerDrawer.Shrink(true);            // a dialog takes its owner down first
                    _tookOwner = ownerDrawer;
                }
                _saved = new[] { Window.Left, Window.Top, Window.ActualWidth, Window.ActualHeight };
                _restoreMinHeight = Window.MinHeight;
                try { _restoreSize = Window.SizeToContent; Window.SizeToContent = SizeToContent.Manual; } catch (Exception) { }
                Window.MinHeight = 0;
                Pin(Window.ActualHeight);
                if (_grips != null) { try { _grips.Visibility = Visibility.Collapsed; } catch (Exception) { } }
                double[] screen = WorkArea(Window);
                Slot = WsmCore.FreeSlot(Drawers.Where(d => !ReferenceEquals(d, this) && d.Slot.HasValue && (d.Parked || d.Sliding)).Select(d => d.Slot.Value));
                double bar = BarHeight();
                double target = WsmCore.ParkedTop(screen[1], screen[3], bar, Slot.Value);
                Parked = true;
                SetButton(true);
                Slide(Window.Top, target, () =>
                {
                    Window.Height = bar;
                    _hidden = new List<KeyValuePair<UIElement, Visibility>>();
                    foreach (UIElement child in Siblings())
                    {
                        _hidden.Add(new KeyValuePair<UIElement, Visibility>(child, child.Visibility));
                        child.Visibility = Visibility.Collapsed;
                    }
                    Unpin();
                    _parkedAt = new[] { Window.Left, Window.Top };
                }, instant);
            }

            public void Open(bool activate = true, bool instant = false)
            {
                if (!Parked || Sliding) return;
                double[] saved = _saved ?? new[] { Window.Left, Window.Top, Window.Width, 600.0 };
                foreach (var pair in _hidden) { try { pair.Key.Visibility = pair.Value; } catch (Exception) { } }
                _hidden = new List<KeyValuePair<UIElement, Visibility>>();
                double[] work;
                try { work = WorkArea(Window); } catch (Exception) { work = new[] { saved[0], saved[1], saved[2], saved[3] }; }
                double left, top;
                WsmCore.OpenedPosition(saved, Window.Left, Window.Top, BarHeight(), _parkedAt, work, out left, out top);
                Window.Height = saved[3];
                Pin(saved[3]);
                Window.Left = left;
                Parked = false;
                SetButton(false);
                Slide(Window.Top, top, () =>
                {
                    Unpin();
                    try { Window.MinHeight = _restoreMinHeight; } catch (Exception) { }
                    if (_restoreSize.HasValue) { try { Window.SizeToContent = _restoreSize.Value; } catch (Exception) { } }
                    if (_grips != null) { try { _grips.Visibility = Visibility.Visible; } catch (Exception) { } }
                    Slot = null; _parkedAt = null;
                    if (activate) { try { Window.Activate(); } catch (Exception) { } }
                    GiveOwnerBack();
                }, instant);
            }

            private void GiveOwnerBack()
            {
                WindowDrawer owner = _tookOwner;
                _tookOwner = null;
                if (owner != null && owner.Parked) owner.Open(false, true);
            }
        }

        // ================================================================ small widgets

        /// <summary>Opens and closes one element downward like a drawer. Height is eased by hand on a timer, never animated.</summary>
        public class HeightDrawer
        {
            public readonly FrameworkElement Element;
            protected readonly Stopwatch Clock = Stopwatch.StartNew();
            protected DispatcherTimer Timer;
            public bool IsOpen;
            protected double Ms = 220.0;
            private readonly Func<double> _widthOf;
            public readonly List<string> Errors = new List<string>();

            public HeightDrawer(FrameworkElement element, Func<double> widthOf = null) { Element = element; _widthOf = widthOf; }

            public void Stop()
            {
                DispatcherTimer timer = Timer; Timer = null;
                if (timer != null) { try { timer.Stop(); } catch (Exception) { } }
            }

            private double NaturalHeight()
            {
                Element.Height = double.NaN;
                Element.Visibility = Visibility.Visible;
                try
                {
                    double width = (_widthOf != null ? _widthOf() : 0.0);
                    if (width <= 0) width = Element.ActualWidth;
                    if (width <= 0) width = 600.0;
                    Element.Measure(new Size(width, double.PositiveInfinity));
                    double height = Element.DesiredSize.Height - (Element.Margin.Top + Element.Margin.Bottom);
                    return Math.Max(0.0, height);
                }
                catch (Exception) { return 200.0; }
            }

            public virtual void Open()
            {
                if (IsOpen) return;
                IsOpen = true;
                double target = NaturalHeight();
                Element.Height = 0.0;
                Run(0.0, target, () => Element.Height = double.NaN);
            }

            public virtual void Close()
            {
                if (!IsOpen) return;
                IsOpen = false;
                double start = 0.0;
                try { start = Element.ActualHeight; } catch (Exception) { }
                Run(start, 0.0, () => { Element.Visibility = Visibility.Collapsed; Element.Height = double.NaN; });
            }

            public void Toggle() { if (IsOpen) Close(); else Open(); }

            private void Run(double start, double end, Action landed)
            {
                Stop();
                double began = Clock.Elapsed.TotalMilliseconds;
                Action finish = () =>
                {
                    Stop();
                    try { landed(); } catch (Exception err) { Errors.Add(err.Message); }
                };
                try
                {
                    DispatcherTimer timer = MakeTimer(WsmCore.DrawerTickMs);
                    timer.Tick += (s, a) =>
                    {
                        try
                        {
                            double progress = (Clock.Elapsed.TotalMilliseconds - began) / Ms;
                            Element.Height = Math.Max(0.0, WsmCore.Lerp(start, end, WsmCore.EaseOut(progress)));
                            if (progress >= 1.0) finish();
                        }
                        catch (Exception err) { Errors.Add(err.Message); finish(); }
                    };
                    Timer = timer;
                    timer.Start();
                }
                catch (Exception err) { Errors.Add(err.Message); finish(); }
            }

            protected void RunWidth(double start, double end, Action landed)
            {
                Stop();
                double began = Clock.Elapsed.TotalMilliseconds;
                Action finish = () =>
                {
                    Stop();
                    try { Element.Width = end; landed(); } catch (Exception err) { Errors.Add(err.Message); }
                };
                try
                {
                    DispatcherTimer timer = MakeTimer(WsmCore.DrawerTickMs);
                    timer.Tick += (s, a) =>
                    {
                        try
                        {
                            double progress = (Clock.Elapsed.TotalMilliseconds - began) / Ms;
                            Element.Width = Math.Max(0.0, WsmCore.Lerp(start, end, WsmCore.EaseOut(progress)));
                            if (progress >= 1.0) finish();
                        }
                        catch (Exception err) { Errors.Add(err.Message); finish(); }
                    };
                    Timer = timer;
                    timer.Start();
                }
                catch (Exception err) { Errors.Add(err.Message); finish(); }
            }
        }

        /// <summary>Slides a side panel open sideways - the rename panels. The panel inside has a fixed width, so nothing reflows while the drawer moves.</summary>
        public class SideDrawer : HeightDrawer
        {
            private readonly double _width;
            private readonly TextBlock _glyph;
            private readonly Action<bool> _onChange;

            public SideDrawer(FrameworkElement element, double width, TextBlock glyph = null, Action<bool> onChange = null) : base(element)
            {
                _width = width; _glyph = glyph; _onChange = onChange; Ms = 240.0;
            }

            private void Glyph()
            {
                if (_glyph != null) { try { _glyph.Text = IsOpen ? "›" : "‹"; } catch (Exception) { } }
                if (_onChange != null) { try { _onChange(IsOpen); } catch (Exception) { } }
            }

            public override void Open() { Open(false); }

            public void Open(bool instant)
            {
                if (IsOpen) return;
                IsOpen = true;
                Element.Visibility = Visibility.Visible;
                Glyph();
                if (instant) { Stop(); Element.Width = _width; return; }
                double start = double.IsNaN(Element.Width) ? 0.0 : Element.Width;
                RunWidth(start, _width, () => { });
            }

            public override void Close() { Close(false); }

            public void Close(bool instant)
            {
                if (!IsOpen) return;
                IsOpen = false;
                Glyph();
                Action landed = () => Element.Visibility = Visibility.Collapsed;
                if (instant) { Stop(); Element.Width = 0.0; landed(); return; }
                double start = _width;
                try { start = Element.ActualWidth; } catch (Exception) { }
                RunWidth(start, 0.0, landed);
            }
        }

        public class MenuEntry
        {
            public string Label; public RoutedEventHandler Handler; public bool Enabled = true;
            public MenuEntry(string label, RoutedEventHandler handler, bool enabled = true) { Label = label; Handler = handler; Enabled = enabled; }
            public static MenuEntry Rule() { return new MenuEntry(null, null, false); }
        }

        /// <summary>A right-click menu in the window's palette. A ContextMenu opens in its own popup, outside the window's tree, so styles come from the window.</summary>
        public static ContextMenu ThemedMenu(FrameworkElement ownerWindow, IEnumerable<MenuEntry> items)
        {
            var menu = new ContextMenu();
            ApplyPalette(menu, Current);
            Action<FrameworkElement, string> styled = (element, key) =>
            {
                try { element.Style = (Style)ownerWindow.FindResource(key); } catch (Exception) { }
            };
            styled(menu, "WsMenu");
            foreach (MenuEntry entry in items)
            {
                if (entry.Label == null)
                {
                    var line = new Border { Height = 1, Margin = new Thickness(6, 3, 6, 3) };
                    Res(line, Border.BackgroundProperty, "EdgeBrush");
                    menu.Items.Add(line);
                    continue;
                }
                var item = new MenuItem { Header = entry.Label, IsEnabled = entry.Enabled };
                styled(item, "WsMenuItem");
                if (entry.Handler != null) item.Click += entry.Handler;
                menu.Items.Add(item);
            }
            return menu;
        }

        public class Choice
        {
            public object Value; public string Label, Detail;
            public Choice(object value, string label, string detail = "") { Value = value; Label = label; Detail = detail; }
        }

        /// <summary>A themed drop-down: a toggle showing the choice, a popup with an optional search box and the list. Stands in for a ComboBox.</summary>
        public class PickButton
        {
            public List<Choice> Choices;
            public object Value;
            private readonly Action<object> _onChange;
            private readonly bool _search;
            private readonly string _placeholder;
            private readonly double _minPopup;
            public readonly Grid Holder = new Grid();
            private readonly TextBlock _label;
            private readonly ToggleButton _toggle;
            private readonly Popup _popup;

            public PickButton(IEnumerable<Choice> choices, object value = null, Action<object> onChange = null, bool search = false,
                              string placeholder = "Choose...", double? width = null, double minPopup = 260)
            {
                Choices = choices.ToList(); Value = value; _onChange = onChange; _search = search; _placeholder = placeholder; _minPopup = minPopup;
                _toggle = new ToggleButton();
                WsmUi.Style(_toggle, "WsDropToggle");
                if (width.HasValue) _toggle.Width = width.Value;
                _label = TextBlock("", 12, "TextBrush");
                _toggle.Content = _label;
                _toggle.Checked += OnOpen;
                Holder.Children.Add(_toggle);
                _popup = new Popup { PlacementTarget = _toggle, Placement = PlacementMode.Bottom, StaysOpen = false, AllowsTransparency = true };
                _popup.Closed += (s, a) => _toggle.IsChecked = false;
                Holder.Children.Add(_popup);
                Refresh();
            }

            public FrameworkElement Element { get { return Holder; } }

            private string LabelOf(object value)
            {
                foreach (Choice c in Choices) if (Equals(c.Value, value)) return c.Label;
                return null;
            }

            public void Refresh()
            {
                string label = LabelOf(Value);
                bool empty = Value == null || WsmCore.Txt(Value).Length == 0;
                if (label == null)
                {
                    _label.Text = empty ? _placeholder : WsmCore.Txt(Value);
                    Res(_label, System.Windows.Controls.TextBlock.ForegroundProperty, empty ? "MutedBrush" : "TextBrush");
                }
                else
                {
                    _label.Text = label;
                    Res(_label, System.Windows.Controls.TextBlock.ForegroundProperty, "TextBrush");
                }
                _toggle.ToolTip = _label.Text;
            }

            public void SetChoices(IEnumerable<Choice> choices, object value = null)
            {
                Choices = choices.ToList();
                if (value != null) Value = value;
                Refresh();
            }

            private void OnOpen(object sender, RoutedEventArgs args)
            {
                try
                {
                    var shell = new Border { BorderThickness = new Thickness(1), Padding = new Thickness(6), MinWidth = Math.Max(_minPopup, _toggle.ActualWidth) };
                    Res(shell, Border.BackgroundProperty, "FieldBrush");
                    Res(shell, Border.BorderBrushProperty, "ChromeBrush");
                    var stack = new StackPanel();
                    TextBox box = null;
                    if (_search || Choices.Count > 12)
                    {
                        box = new TextBox { Tag = "Search", Height = 30, Margin = new Thickness(0, 0, 0, 6) };
                        WsmUi.Style(box, "WsTextBox");
                        stack.Children.Add(box);
                    }
                    var listing = new ListBox { MaxHeight = 320, BorderThickness = new Thickness(0) };
                    WsmUi.Style(listing, "WsListBox");
                    stack.Children.Add(listing);
                    shell.Child = stack;

                    Action<string> fill = needle =>
                    {
                        listing.Items.Clear();
                        foreach (Choice c in Choices)
                        {
                            if (!WsmCore.TextMatch(c.Label, needle)) continue;
                            var item = new ListBoxItem { Tag = c.Value };
                            WsmUi.Style(item, "WsListItem");
                            var line = new StackPanel { Orientation = Orientation.Horizontal };
                            line.Children.Add(TextBlock(c.Label, 12, "TextBrush", Equals(c.Value, Value)));
                            if (!string.IsNullOrEmpty(c.Detail)) line.Children.Add(TextBlock("   " + c.Detail, 11, "MutedBrush"));
                            item.Content = line;
                            listing.Items.Add(item);
                        }
                    };
                    fill("");
                    if (box != null) { TextBox b = box; b.TextChanged += (s, a) => fill(b.Text); }
                    listing.SelectionChanged += (s, a) =>
                    {
                        var item = listing.SelectedItem as ListBoxItem;
                        if (item == null) return;
                        Value = item.Tag;
                        _popup.IsOpen = false;
                        Refresh();
                        if (_onChange != null)
                        {
                            try { _onChange(Value); }
                            catch (Exception err) { Report(Window.GetWindow(Holder), "Choosing '" + _label.Text + "'", err); }
                        }
                    };
                    _popup.Child = shell;
                    _popup.IsOpen = true;
                    if (box != null) box.Focus();
                }
                catch (Exception err)
                {
                    _toggle.IsChecked = false;
                    Report(Window.GetWindow(Holder), "Opening a drop-down", err);
                }
            }
        }

        public static Border Swatch(string colour, double size = 13)
        {
            var block = new Border
            {
                Width = size, Height = size, CornerRadius = new CornerRadius(3), Margin = new Thickness(0, 0, 8, 0), BorderThickness = new Thickness(1),
                Background = Brush(WsmCore.Txt(colour).StartsWith("#") ? colour : "#00000000"),
            };
            Res(block, Border.BorderBrushProperty, "EdgeBrush");
            return block;
        }

        // ================================================================ dialogs

        /// <summary>A themed, borderless child window: header with logo, title and version; a body; a footer of buttons on the right.</summary>
        public class Dialog
        {
            public readonly Window Window;
            public object Result;
            public readonly StackPanel Body, Footer;
            private readonly WindowDrawer _drawer;

            public Dialog(Window owner, string title, double width, double height)
            {
                var window = new Window
                {
                    WindowStyle = WindowStyle.None, AllowsTransparency = true, Background = Brush("#00000000"), ResizeMode = ResizeMode.NoResize,
                    ShowInTaskbar = false, Width = width, Height = height, Title = title,
                };
                if (owner != null)
                {
                    BringBack(owner);
                    try { window.Owner = owner; window.WindowStartupLocation = WindowStartupLocation.CenterOwner; }
                    catch (Exception) { window.WindowStartupLocation = WindowStartupLocation.CenterScreen; }
                }
                else window.WindowStartupLocation = WindowStartupLocation.CenterScreen;
                Prepare(window);
                Window = window;

                var frame = new Border { BorderThickness = new Thickness(1), CornerRadius = new CornerRadius(6) };
                Res(frame, Border.BackgroundProperty, "WindowBrush");
                Res(frame, Border.BorderBrushProperty, "ChromeBrush");
                window.Content = frame;

                var layout = new Grid();
                layout.RowDefinitions.Add(new RowDefinition { Height = new GridLength(46) });
                layout.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
                layout.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
                frame.Child = layout;

                var header = new Border { CornerRadius = new CornerRadius(5, 5, 0, 0), Padding = new Thickness(14, 0, 6, 0) };
                Res(header, Border.BackgroundProperty, "BarBrush");
                layout.Children.Add(header);
                var bar = new Grid();
                bar.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
                bar.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
                bar.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
                bar.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
                bar.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
                header.Child = bar;

                var brand = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center, Background = Brush("#00000000") };
                TextBlock logo = TextBlock("RevoBIM", 16, "BlueBrush", true);
                logo.FontWeight = FontWeights.Bold;
                brand.Children.Add(logo);
                brand.Children.Add(TextBlock("   " + title, 13, "OrangeTextBrush"));
                bar.Children.Add(brand);

                TextBlock version = TextBlock("v" + WsmCore.Version, 11, "MutedBrush");
                version.Margin = new Thickness(0, 0, 10, 0);
                Grid.SetColumn(version, 2);
                bar.Children.Add(version);

                var shrink = new Button();
                WsmUi.Style(shrink, "WsShrinkButton");
                Grid.SetColumn(shrink, 3);
                bar.Children.Add(shrink);

                var close = new Button { Content = "✕" };
                WsmUi.Style(close, "WsCloseButton");
                close.Click += (s, a) => { Result = null; window.Close(); };
                Grid.SetColumn(close, 4);
                bar.Children.Add(close);

                _drawer = new WindowDrawer(window, header, shrink);
                header.MouseLeftButtonDown += (s, a) =>
                {
                    try
                    {
                        if (IsWithin(a.OriginalSource, new object[] { close, brand, shrink }, header)) return;
                        if (a.ClickCount == 2 && _drawer.Parked) { _drawer.Open(); return; }
                        window.DragMove();
                    }
                    catch (Exception) { }
                };

                Body = new StackPanel { Margin = new Thickness(16, 12, 16, 6) };
                var scroller = new ScrollViewer { VerticalScrollBarVisibility = ScrollBarVisibility.Auto, HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled, Content = Body };
                Grid.SetRow(scroller, 1);
                layout.Children.Add(scroller);

                var footer = new Border { CornerRadius = new CornerRadius(0, 0, 5, 5), Padding = new Thickness(14, 0, 14, 0), Height = 50 };
                Res(footer, Border.BackgroundProperty, "BarBrush");
                Grid.SetRow(footer, 2);
                layout.Children.Add(footer);
                Footer = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right, VerticalAlignment = VerticalAlignment.Center };
                footer.Child = Footer;

                window.PreviewKeyDown += (s, a) =>
                {
                    try
                    {
                        if (_drawer.Parked) return;           // Escape reopens a parked dialog, never closes it
                        if (a.Key == Key.Escape && !TextBoxHasFocus()) { Result = null; window.Close(); a.Handled = true; }
                    }
                    catch (Exception) { }
                };
            }

            public Button Button(string text, string key = "WsButton", RoutedEventHandler handler = null, double width = 96)
            {
                var made = new Button { Content = text, MinWidth = width, Margin = new Thickness(8, 0, 0, 0) };
                WsmUi.Style(made, key);
                if (handler != null) made.Click += handler;
                Footer.Children.Add(made);
                return made;
            }

            public T Add<T>(T element) where T : UIElement { Body.Children.Add(element); return element; }

            public TextBlock Text(string text, string key = "TextBrush", double size = 12, bool bold = false, Thickness? margin = null)
            {
                TextBlock block = TextBlock(text, size, key, bold, true);
                block.Margin = margin ?? new Thickness(0, 0, 0, 8);
                return Add(block);
            }

            public void CloseWith(object value) { Result = value; Window.Close(); }

            public object Show() { Window.ShowDialog(); return Result; }
        }

        private static TextBox ReadOnlyBox(string text, double height, bool wrap)
        {
            var box = new TextBox
            {
                Text = text, IsReadOnly = true, AcceptsReturn = true, TextWrapping = wrap ? TextWrapping.Wrap : TextWrapping.NoWrap,
                VerticalContentAlignment = VerticalAlignment.Top, VerticalScrollBarVisibility = ScrollBarVisibility.Auto, Height = height,
            };
            WsmUi.Style(box, "WsTextBox");
            return box;
        }

        /// <summary>Results go here, never to a console.</summary>
        public static void Message(Window owner, string title, IEnumerable<string> lines, double width = 640, double height = 460)
        {
            var dialog = new Dialog(owner, title, width, height);
            TextBox box = ReadOnlyBox(string.Join("\n", lines.Select(WsmCore.Txt)), height - 130, true);
            box.FontFamily = new FontFamily("Consolas");
            dialog.Add(box);
            dialog.Button("Close", "WsButton", (s, a) => dialog.CloseWith(true));
            dialog.Show();
        }

        public static bool Confirm(Window owner, string title, string text, IEnumerable<string> lines = null, string yes = "Apply", string no = "Cancel",
                                   string yesKey = "WsGreenButton", double width = 600, double height = 420)
        {
            var dialog = new Dialog(owner, title, width, height);
            dialog.Text(text);
            if (lines != null)
            {
                var list = lines.ToList();
                if (list.Count > 0)
                {
                    TextBox box = ReadOnlyBox(string.Join("\n", list.Select(WsmCore.Txt)), height - 170, false);
                    box.HorizontalScrollBarVisibility = ScrollBarVisibility.Auto;
                    dialog.Add(box);
                }
            }
            dialog.Button(no, "WsButton", (s, a) => dialog.CloseWith(false));
            dialog.Button(yes, yesKey, (s, a) => dialog.CloseWith(true), 120);
            return dialog.Show() is bool && (bool)dialog.Result;
        }

        public static string PromptText(Window owner, string title, string label, string defaultText = "", string accept = "Save")
        {
            var dialog = new Dialog(owner, title, 460, 210);
            dialog.Text(label);
            var box = new TextBox { Text = WsmCore.Txt(defaultText), Height = 30, FontSize = 13 };
            WsmUi.Style(box, "WsTextBox");
            dialog.Add(box);
            Action done = () => { string v = box.Text.Trim(); if (v.Length > 0) dialog.CloseWith(v); };
            box.KeyDown += (s, a) => { if (a.Key == Key.Enter) done(); };
            dialog.Button("Cancel", "WsButton", (s, a) => dialog.CloseWith(null));
            dialog.Button(accept, "WsGreenButton", (s, a) => done());
            dialog.Window.Loaded += (s, a) => { box.Focus(); box.SelectAll(); };      // typing replaces the suggested name
            return dialog.Show() as string;
        }

        public static ListBox ThemedList(double height = 240)
        {
            var listing = new ListBox { Height = height };
            WsmUi.Style(listing, "WsListBox");
            listing.ItemContainerStyle = listing.TryFindResource("WsListItem") as Style;
            return listing;
        }

        public static ListBoxItem ListItem(ListBox listing, string label, object tag, string detail = "")
        {
            var item = new ListBoxItem { Tag = tag };
            WsmUi.Style(item, "WsListItem");
            var line = new StackPanel { Orientation = Orientation.Horizontal };
            line.Children.Add(TextBlock(label, 12, "TextBrush"));
            if (detail.Length > 0) line.Children.Add(TextBlock("   " + detail, 11, "OrangeTextBrush"));
            item.Content = line;
            listing.Items.Add(item);
            return item;
        }

        /// <summary>Pick one of options. onDelete(name) -> bool removes one from the list.</summary>
        public static string PromptChoice(Window owner, string title, string label, IEnumerable<string> options, string accept = "Load", Func<string, bool> onDelete = null)
        {
            var dialog = new Dialog(owner, title, 480, 420);
            dialog.Text(label);
            ListBox listing = ThemedList(250);
            foreach (string option in options) ListItem(listing, option, option);
            dialog.Add(listing);
            RoutedEventHandler done = (s, a) =>
            {
                var item = listing.SelectedItem as ListBoxItem;
                if (item != null) dialog.CloseWith(WsmCore.Txt(item.Tag));
            };
            listing.MouseDoubleClick += (s, a) => done(s, null);
            if (onDelete != null)
                dialog.Button("Delete", "WsRedButton", (s, a) =>
                {
                    var item = listing.SelectedItem as ListBoxItem;
                    if (item != null && onDelete(WsmCore.Txt(item.Tag))) listing.Items.Remove(item);
                });
            dialog.Button("Cancel", "WsButton", (s, a) => dialog.CloseWith(null));
            dialog.Button(accept, "WsGreenButton", done);
            return dialog.Show() as string;
        }

        public class WorksetChoice
        {
            public int Iid; public string Name; public int Count; public string Colour;
        }

        /// <summary>-> the iid picked, or null.</summary>
        public static int? ChooseWorkset(Window owner, string title, string text, IList<WorksetChoice> worksets, string accept = "Choose", string acceptKey = "WsGreenButton")
        {
            var dialog = new Dialog(owner, title, 520, 540);
            dialog.Text(text);
            var search = new TextBox { Tag = "Filter worksets", Height = 30, Margin = new Thickness(0, 0, 0, 6) };
            WsmUi.Style(search, "WsTextBox");
            dialog.Add(search);
            ListBox choices = ThemedList(300);
            dialog.Add(choices);
            Action<string> fill = needle =>
            {
                choices.Items.Clear();
                foreach (WorksetChoice w in worksets)
                {
                    if (!WsmCore.TextMatch(w.Name, needle)) continue;
                    var item = new ListBoxItem { Tag = w.Iid };
                    WsmUi.Style(item, "WsListItem");
                    var line = new StackPanel { Orientation = Orientation.Horizontal };
                    line.Children.Add(Swatch(w.Colour));
                    line.Children.Add(TextBlock(w.Name, 12, "TextBrush", true));
                    line.Children.Add(TextBlock("   " + w.Count + " elements", 11, "OrangeTextBrush"));
                    item.Content = line;
                    choices.Items.Add(item);
                }
                if (choices.Items.Count == 1) choices.SelectedIndex = 0;
            };
            fill("");
            search.TextChanged += (s, a) => fill(search.Text);
            RoutedEventHandler done = (s, a) =>
            {
                var item = choices.SelectedItem as ListBoxItem;
                if (item != null) dialog.CloseWith(item.Tag);
            };
            choices.MouseDoubleClick += (s, a) => done(s, null);
            dialog.Button("Cancel", "WsButton", (s, a) => dialog.CloseWith(null));
            dialog.Button(accept, acceptKey, done, 150);
            dialog.Window.Loaded += (s, a) => search.Focus();
            object result = dialog.Show();
            return result is int ? (int?)(int)result : null;
        }

        /// <summary>-> the key of the workset taking the elements, or null. Nothing is deleted here - it is staged.</summary>
        public static string DeleteDialog(Window owner, IList<WsmCore.WsRow> deleting, IList<WsmCore.WsRow> targets)
        {
            int total = deleting.Sum(r => r.Count);
            var dialog = new Dialog(owner, "Delete worksets", 560, 560);
            dialog.Text(deleting.Count + " workset" + (deleting.Count == 1 ? "" : "s") + " will be deleted when you press Apply. Nothing is deleted from the model until then.");
            var listing = new StackPanel { Margin = new Thickness(4, 0, 0, 10) };
            foreach (WsmCore.WsRow row in deleting.Take(14))
            {
                var line = new StackPanel { Orientation = Orientation.Horizontal };
                line.Children.Add(TextBlock(row.Orig.Length > 0 ? row.Orig : row.Name, 12, "RedBrush", true));
                line.Children.Add(TextBlock("   " + row.Count + " elements", 11, "OrangeTextBrush"));
                listing.Children.Add(line);
            }
            if (deleting.Count > 14) listing.Children.Add(TextBlock("... and " + (deleting.Count - 14) + " more", 11, "MutedBrush"));
            dialog.Add(listing);
            if (total > 0) dialog.Text("Move all " + total + " of their elements onto:", "TextBrush", 12, true);
            else dialog.Text("They are empty. Revit still asks where elements would go, so pick a workset - nothing will move.", "MutedBrush", 11);

            var search = new TextBox { Tag = "Filter worksets", Height = 30, Margin = new Thickness(0, 0, 0, 6) };
            WsmUi.Style(search, "WsTextBox");
            dialog.Add(search);
            ListBox choices = ThemedList(220);
            dialog.Add(choices);
            Action<string> fill = needle =>
            {
                choices.Items.Clear();
                foreach (WsmCore.WsRow row in targets)
                    if (WsmCore.TextMatch(row.EffectiveName(), needle))
                        ListItem(choices, row.EffectiveName(), row.Key, row.IsNew ? "new" : row.Count + " elements");
                if (choices.Items.Count == 1) choices.SelectedIndex = 0;
            };
            fill("");
            search.TextChanged += (s, a) => fill(search.Text);
            RoutedEventHandler done = (s, a) =>
            {
                var item = choices.SelectedItem as ListBoxItem;
                if (item != null) dialog.CloseWith(WsmCore.Txt(item.Tag));
            };
            choices.MouseDoubleClick += (s, a) => done(s, null);
            dialog.Button("Cancel", "WsButton", (s, a) => dialog.CloseWith(null));
            dialog.Button("Stage delete", "WsRedButton", done, 120);
            return dialog.Show() as string;
        }

        /// <summary>-> the key of the master, or null. Nothing is merged here - it is staged.</summary>
        public static string MergeDialog(Window owner, IList<WsmCore.WsRow> rows)
        {
            var dialog = new Dialog(owner, "Merge worksets", 540, 520);
            dialog.Text("Which workset is the master? The others move all of their elements onto it and are then deleted, when you press Apply. Any rename staged on the master is kept.");
            dialog.Text(rows.Count + " worksets, " + rows.Sum(r => r.Count) + " elements between them.", "MutedBrush", 11);
            ListBox choices = ThemedList(300);
            var ordered = rows.OrderByDescending(r => r.Count).ThenBy(r => r.EffectiveName(), WsmCore.Natural).ToList();
            foreach (WsmCore.WsRow row in ordered)
            {
                var item = new ListBoxItem { Tag = row.Key };
                WsmUi.Style(item, "WsListItem");
                var line = new StackPanel { Orientation = Orientation.Horizontal };
                line.Children.Add(Swatch(row.Colour));
                line.Children.Add(TextBlock(row.EffectiveName(), 12, "TextBrush", true));
                line.Children.Add(TextBlock(row.IsNew ? "   new" : "   " + row.Count + " elements", 11, "OrangeTextBrush"));
                item.Content = line;
                choices.Items.Add(item);
            }
            choices.SelectedIndex = 0;
            dialog.Add(choices);
            RoutedEventHandler done = (s, a) =>
            {
                var item = choices.SelectedItem as ListBoxItem;
                if (item != null) dialog.CloseWith(WsmCore.Txt(item.Tag));
            };
            choices.MouseDoubleClick += (s, a) => done(s, null);
            dialog.Button("Cancel", "WsButton", (s, a) => dialog.CloseWith(null));
            dialog.Button("Stage merge", "WsOrangeButton", done, 120);
            return dialog.Show() as string;
        }
    }
}
