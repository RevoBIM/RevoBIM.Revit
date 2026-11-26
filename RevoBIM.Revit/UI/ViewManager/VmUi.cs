using System;
using System.Collections.Generic;
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
using System.Windows.Threading;
using Autodesk.Revit.UI;
using RevoBIM.Helpers;
using RevoBIM.Tools.ViewManager;

namespace RevoBIM.UI.ViewManager
{
    /// <summary>Window plumbing shared by every View Manager window: layout loading with the shared resources dropped in, palettes, Revit's canvas theme.</summary>
    internal static class VmUi
    {
        private const string LayoutPrefix = "RevoBIM.UI.ViewManager.Layouts.";
        private const string SharedToken = "<!--SHARED_RESOURCES-->";

        public static Autodesk.Revit.ApplicationServices.Application RevitApp;

        public static string ReadLayout(string file)
        {
            using (Stream stream = typeof(VmUi).Assembly.GetManifestResourceStream(LayoutPrefix + file))
            {
                if (stream == null) throw new FileNotFoundException("embedded layout " + LayoutPrefix + file + " was not found");
                using (var reader = new StreamReader(stream, Encoding.UTF8)) return reader.ReadToEnd();
            }
        }

        /// <summary>Parses a window's XAML with the shared resources dropped in.</summary>
        public static Window LoadWindow(string xaml)
        {
            string full = xaml.Replace(SharedToken, ReadLayout("Shared.xaml"));
            var window = XamlReader.Parse(full) as Window;
            if (window == null) throw new InvalidCastException("the layout is not a Window");
            return window;
        }

        public static Window LoadLayout(string file) { return LoadWindow(ReadLayout(file)); }

        public static T Find<T>(FrameworkElement root, string name) where T : class
        {
            return root.FindName(name) as T;
        }

        public static SolidColorBrush MakeBrush(string hex)
        {
            var brush = new SolidColorBrush((Color)ColorConverter.ConvertFromString(hex));
            try { brush.Freeze(); } catch (Exception) { }
            return brush;
        }

        public static Brush Res(FrameworkElement window, string key)
        {
            return window.Resources[key] as Brush;
        }

        public static bool SameObject(object a, object b)
        {
            if (a == null || b == null) return false;
            return ReferenceEquals(a, b) || a.Equals(b);
        }

        /// <summary>What Revit is drawing in: canvas first, then the canvas background by luminance, then the ribbon theme.</summary>
        public static string RevitTheme(out string readAs)
        {
            try
            {
                string text = RevitCompat.CanvasTheme().ToString().ToLowerInvariant();
                if (text.Contains("dark")) { readAs = "canvas theme: dark"; return "dark"; }
                if (text.Contains("light")) { readAs = "canvas theme: light"; return "light"; }
            }
            catch (Exception) { }
            try
            {
                Autodesk.Revit.DB.Color colour = RevitApp == null ? null : RevitApp.BackgroundColor;
                if (colour != null && colour.IsValid)
                {
                    double lum = (0.2126 * colour.Red + 0.7152 * colour.Green + 0.0722 * colour.Blue) / 255.0;
                    if (lum < 0.5) { readAs = "canvas background is dark"; return "dark"; }
                    readAs = "canvas background is light";
                    return "light";
                }
            }
            catch (Exception) { }
            try
            {
                string text = UIThemeManager.CurrentTheme.ToString().ToLowerInvariant();
                if (text.Contains("dark")) { readAs = "Revit theme: dark"; return "dark"; }
                if (text.Contains("light")) { readAs = "Revit theme: light"; return "light"; }
            }
            catch (Exception) { }
            readAs = "nothing to read - dark";
            return "dark";
        }

        public static string ResolveTheme()
        {
            string mode = VmCore.ThemeMode;
            if (mode == "dark" || mode == "light")
            {
                VmCore.ThemeName = mode;
                VmCore.ThemeReadAs = "set by hand";
            }
            else
            {
                string readAs;
                VmCore.ThemeName = RevitTheme(out readAs);
                VmCore.ThemeReadAs = readAs;
            }
            return VmCore.ThemeName;
        }

        /// <summary>Writes the palette onto window.Resources; every colour in the layouts is a DynamicResource, so an open window repaints in place.</summary>
        public static void ApplyPalette(Window window, string name = null)
        {
            Dictionary<string, string> palette;
            if (!VmCore.Palettes.TryGetValue(name ?? VmCore.ThemeName, out palette)) palette = VmCore.Dark;
            foreach (KeyValuePair<string, string> kv in palette)
            {
                try { window.Resources[kv.Key] = MakeBrush(kv.Value); } catch (Exception) { }
            }
        }

        public static void PaintChip(Window window)
        {
            try
            {
                var label = window.FindName("ThemeChipText") as TextBlock;
                if (label != null)
                {
                    string text;
                    label.Text = VmCore.ThemeLabels.TryGetValue(VmCore.ThemeMode, out text) ? text : "Auto";
                }
                var chip = window.FindName("ThemeChip") as FrameworkElement;
                if (chip != null)
                {
                    string mode = VmCore.ThemeMode;
                    if (mode == "follow") chip.ToolTip = "Auto - following Revit (" + VmCore.ThemeReadAs + "). Click for Dark.";
                    else if (mode == "dark") chip.ToolTip = "Dark. Click for Light.";
                    else chip.ToolTip = "Light. Click for Auto.";
                }
            }
            catch (Exception) { }
        }

        public static void RepaintAll()
        {
            ResolveTheme();
            foreach (VmThemed t in VmThemed.All.ToList())
            {
                try { t.Repaint(); } catch (Exception) { }
            }
        }

        public static void DragMove(Window window)
        {
            try { window.DragMove(); } catch (Exception) { }
        }
    }

    /// <summary>Hooks a window up to the shared theme: chip, palette, auto re-check.</summary>
    internal sealed class VmThemed
    {
        public static readonly List<VmThemed> All = new List<VmThemed>();

        public readonly Window Window;
        private readonly Action onRepaint;

        public VmThemed(Window window, Action onRepaint = null)
        {
            Window = window;
            this.onRepaint = onRepaint;
            All.Add(this);
            VmUi.ApplyPalette(window);
            VmUi.PaintChip(window);
            try
            {
                var chip = window.FindName("ThemeChip") as ButtonBase;
                if (chip != null) chip.Click += OnChip;
            }
            catch (Exception) { }
            window.Activated += OnActivated;
            window.Closed += (s, e) => All.Remove(this);
        }

        private void OnChip(object sender, RoutedEventArgs args)
        {
            try
            {
                int index = Array.IndexOf(VmCore.ThemeModes, VmCore.ThemeMode);
                if (index < 0) index = 0;
                VmCore.ThemeMode = VmCore.ThemeModes[(index + 1) % VmCore.ThemeModes.Length];
                VmCore.Settings["theme_mode"] = VmCore.ThemeMode;
                string note;
                VmCore.SaveSettings(out note);
                VmUi.RepaintAll();
            }
            catch (Exception) { }
        }

        /// <summary>Auto re-reads Revit whenever a window comes to the front, so changing Revit's theme is picked up without reopening the tool.</summary>
        private void OnActivated(object sender, EventArgs args)
        {
            if (VmCore.ThemeMode != "follow") return;
            string before = VmCore.ThemeName;
            VmUi.ResolveTheme();
            if (VmCore.ThemeName != before) VmUi.RepaintAll();
            else foreach (VmThemed t in All.ToList()) VmUi.PaintChip(t.Window);
        }

        public void Repaint()
        {
            VmUi.ApplyPalette(Window);
            VmUi.PaintChip(Window);
            if (onRepaint != null)
            {
                try { onRepaint(); } catch (Exception) { }
            }
        }
    }

    /// <summary>
    /// Shrinks a window to its header bar at the bottom of the screen, and back (port of Chrome, the same mechanics as the
    /// Pro Sheets chrome). The header's siblings are collapsed once it lands; the shrink button turns into a green up arrow
    /// (its Tag becomes "shrunk"); that arrow, or a double click on the bar, slides it back.
    /// </summary>
    internal sealed class VmChrome
    {
        public enum State { Open, Shrinking, Shrunk, Expanding }

        private const double SlideMs = 280.0, FrameMs = 15, Margin = 8, Gap = 4, FallbackBar = 40;
        private static readonly List<VmChrome> Chromes = new List<VmChrome>();
        private static readonly System.Diagnostics.Stopwatch Clock = System.Diagnostics.Stopwatch.StartNew();

        public readonly Window Window;
        private readonly Border header;
        private readonly ButtonBase button;
        public State Mode = State.Open;
        private int? slot;
        private double savedLeft, savedTop, savedHeight, savedMinHeight;
        private ResizeMode savedResize;
        private bool hasSaved;
        private List<KeyValuePair<UIElement, Visibility>> hidden = new List<KeyValuePair<UIElement, Visibility>>();
        private bool liftedOwner;
        private readonly List<VmChrome> liftedChildren = new List<VmChrome>();
        private DispatcherTimer timer;
        private EventHandler tick;

        public VmChrome(Window window, Border header, ButtonBase button)
        {
            Window = window;
            this.header = header;
            this.button = button;
            Chromes.Add(this);
            button.Click += OnButton;
            header.PreviewMouseLeftButtonDown += OnHeaderDown;
            window.Closed += OnClosed;
        }

        public static double Ease(double p)
        {
            if (p <= 0.0) return 0.0;
            if (p >= 1.0) return 1.0;
            return 1.0 - Math.Pow(1.0 - p, 3);
        }

        public static double ShrunkTop(double areaBottom, double bar, int slot)
        {
            return areaBottom - Margin - bar - slot * (bar + Gap);
        }

        private static VmChrome ChromeOf(Window window)
        {
            foreach (VmChrome c in Chromes) if (VmUi.SameObject(c.Window, window)) return c;
            return null;
        }

        private VmChrome Owner()
        {
            try { return ChromeOf(Window.Owner); } catch (Exception) { return null; }
        }

        private List<VmChrome> Children()
        {
            return Chromes.Where(c => c != this && c.Owner() == this).ToList();
        }

        public bool Busy { get { return Mode == State.Shrinking || Mode == State.Expanding; } }

        private double Now() { return Clock.ElapsedMilliseconds; }

        private void StartTimer(Action step)
        {
            StopTimer();
            var t = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(FrameMs) };
            tick = (s, a) => step();
            t.Tick += tick;
            timer = t;
            t.Start();
        }

        private void StopTimer()
        {
            DispatcherTimer t = timer;
            timer = null;
            if (t == null) return;
            try { t.Stop(); } catch (Exception) { }
            try { if (tick != null) t.Tick -= tick; } catch (Exception) { }
            tick = null;
        }

        private double BarHeight()
        {
            try
            {
                double height = header.ActualHeight;
                double offset = header.TranslatePoint(new Point(0, 0), Window).Y;
                double bar = height + 2.0 * Math.Max(offset, 0.0);
                if (bar >= 10.0) return bar;
            }
            catch (Exception) { }
            return FallbackBar;
        }

        private double WorkAreaBottom()
        {
            try
            {
                double[] area = WorkArea(Window);
                return area[1] + area[3];
            }
            catch (Exception) { }
            try { return SystemParameters.WorkArea.Bottom; } catch (Exception) { return 1000.0; }
        }

        /// <summary>(left, top, width, height) of the working area of the screen the window is on, in WPF units.</summary>
        public static double[] WorkArea(Window window)
        {
            System.Drawing.Rectangle area = System.Windows.Forms.Screen.FromHandle(new WindowInteropHelper(window).Handle).WorkingArea;
            double sx = 1.0, sy = 1.0;
            try
            {
                PresentationSource source = PresentationSource.FromVisual(window);
                Matrix m = source.CompositionTarget.TransformToDevice;
                if (m.M11 != 0) sx = m.M11;
                if (m.M22 != 0) sy = m.M22;
            }
            catch (Exception) { }
            return new[] { area.Left / sx, area.Top / sy, area.Width / sx, area.Height / sy };
        }

        private void HideParts()
        {
            hidden = new List<KeyValuePair<UIElement, Visibility>>();
            var parent = header.Parent as Panel;
            if (parent == null) return;
            foreach (UIElement child in parent.Children)
            {
                if (ReferenceEquals(child, header)) continue;
                try
                {
                    hidden.Add(new KeyValuePair<UIElement, Visibility>(child, child.Visibility));
                    child.Visibility = Visibility.Collapsed;
                }
                catch (Exception) { }
            }
        }

        private void ShowParts()
        {
            foreach (KeyValuePair<UIElement, Visibility> p in hidden)
            {
                try { p.Key.Visibility = p.Value; } catch (Exception) { }
            }
            hidden = new List<KeyValuePair<UIElement, Visibility>>();
        }

        private void SetButton(string tag)
        {
            try { button.Tag = tag; } catch (Exception) { }
        }

        private int FreeSlot()
        {
            var taken = new HashSet<int>(Chromes.Where(c => c != this && c.slot != null && (c.Mode == State.Shrinking || c.Mode == State.Shrunk)).Select(c => c.slot.Value));
            int s = 0;
            while (taken.Contains(s)) s++;
            return s;
        }

        private void Animate(double top0, double top1, double h0, double h1, Action done)
        {
            double start = Now();
            Action land = () =>
            {
                StopTimer();
                try
                {
                    Window.Height = Math.Max(h1, 1.0);
                    Window.Top = top1;
                }
                catch (Exception) { }
                done();
            };
            StartTimer(() =>
            {
                try
                {
                    double p = (Now() - start) / SlideMs;
                    double e = Ease(p);
                    Window.Height = Math.Max(h0 + (h1 - h0) * e, 1.0);
                    Window.Top = top0 + (top1 - top0) * e;
                    if (p >= 1.0) land();
                }
                catch (Exception)
                {
                    land();      // never leave a window half way
                }
            });
        }

        private double CurrentHeight()
        {
            double h = Window.Height;
            if (!double.IsNaN(h) && h > 0) return h;
            try { return Window.ActualHeight; } catch (Exception) { return 600.0; }
        }

        public bool Shrink()
        {
            if (Mode != State.Open) return false;
            VmChrome owner = Owner();
            if (owner != null && owner.Mode == State.Open)
            {
                if (owner.Shrink()) liftedOwner = true;
            }
            savedLeft = Window.Left;
            savedTop = Window.Top;
            savedHeight = CurrentHeight();
            savedMinHeight = Window.MinHeight;
            savedResize = Window.ResizeMode;
            hasSaved = true;
            double bar = BarHeight();
            slot = FreeSlot();
            double target = ShrunkTop(WorkAreaBottom(), bar, slot.Value);
            Window.MinHeight = 0;
            try { Window.ResizeMode = ResizeMode.NoResize; } catch (Exception) { }
            Mode = State.Shrinking;
            Animate(Window.Top, target, savedHeight, bar, OnShrunk);
            foreach (VmChrome child in Children())
            {
                if (child.Mode == State.Open && child.Shrink()) liftedChildren.Add(child);
            }
            return true;
        }

        private void OnShrunk()
        {
            HideParts();
            Mode = State.Shrunk;
            SetButton("shrunk");
        }

        public bool Expand()
        {
            if (Mode != State.Shrunk) return false;
            ShowParts();
            SetButton("");
            try { if (hasSaved) Window.Left = savedLeft; } catch (Exception) { }
            Mode = State.Expanding;
            slot = null;
            Animate(Window.Top, hasSaved ? savedTop : Window.Top, CurrentHeight(), hasSaved ? savedHeight : 600.0, OnExpanded);
            VmChrome owner = Owner();
            if (owner != null && owner.Mode == State.Shrunk) owner.Expand();
            foreach (VmChrome child in liftedChildren.ToList())
                if (child.Mode == State.Shrunk) child.Expand();
            liftedChildren.Clear();
            liftedOwner = false;
            return true;
        }

        private void OnExpanded()
        {
            try { if (hasSaved) Window.MinHeight = savedMinHeight; } catch (Exception) { }
            try { if (hasSaved) Window.ResizeMode = savedResize; } catch (Exception) { }
            hasSaved = false;
            Mode = State.Open;
            try { Window.Activate(); } catch (Exception) { }
        }

        /// <summary>Back to full size with no slide - for a window about to be used.</summary>
        public void RestoreNow()
        {
            if (Mode == State.Open) return;
            StopTimer();
            ShowParts();
            SetButton("");
            try
            {
                if (hasSaved)
                {
                    Window.Left = savedLeft;
                    Window.Top = savedTop;
                    Window.Height = savedHeight;
                    Window.MinHeight = savedMinHeight;
                    Window.ResizeMode = savedResize;
                }
            }
            catch (Exception) { }
            hasSaved = false;
            slot = null;
            Mode = State.Open;
        }

        private void OnButton(object sender, RoutedEventArgs args)
        {
            try
            {
                if (Mode == State.Open) Shrink();
                else if (Mode == State.Shrunk) Expand();
            }
            catch (Exception)
            {
                try { RestoreNow(); } catch (Exception) { }
            }
        }

        private static bool InsideButton(DependencyObject element, DependencyObject stop)
        {
            DependencyObject node = element;
            for (int guard = 0; guard < 48; guard++)
            {
                if (node == null || ReferenceEquals(node, stop)) return false;
                if (node is ButtonBase) return true;
                DependencyObject parent = null;
                try { parent = node is Visual || node is System.Windows.Media.Media3D.Visual3D ? VisualTreeHelper.GetParent(node) : null; } catch (Exception) { }
                if (parent == null)
                {
                    try { parent = LogicalTreeHelper.GetParent(node); } catch (Exception) { }
                }
                node = parent;
            }
            return false;
        }

        private void OnHeaderDown(object sender, MouseButtonEventArgs args)
        {
            try
            {
                if (InsideButton(args.OriginalSource as DependencyObject, header)) return;
                if (Busy)
                {
                    args.Handled = true;          // no drag mid-slide
                    return;
                }
                if (Mode == State.Shrunk && args.ClickCount == 2)
                {
                    args.Handled = true;
                    Expand();
                }
            }
            catch (Exception) { }
        }

        private void OnClosed(object sender, EventArgs args)
        {
            StopTimer();
            VmChrome owner = Owner();
            Chromes.Remove(this);
            if (liftedOwner && owner != null && owner.Mode == State.Shrunk)
            {
                try { owner.Expand(); } catch (Exception) { }
            }
        }
    }
}
