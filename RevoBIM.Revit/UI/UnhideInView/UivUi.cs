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
using System.Windows.Threading;
using Autodesk.Revit.UI;
using RevoBIM.Tools.UnhideInView;

using Panel = System.Windows.Controls.Panel;

namespace RevoBIM.UI.UnhideInView
{
    /// <summary>Window plumbing shared by the house style (port of uiv_ui.py): layout loading, palette, Revit's canvas theme, resize grips, full screen, shrink to taskbar.</summary>
    internal static class UivUi
    {
        private const string LayoutPrefix = "RevoBIM.UI.UnhideInView.Layouts.";
        private const string IconName = "RevoBIM.Resources.UnhideInView.icon.png";

        public static string ReadLayout(string file)
        {
            using (Stream stream = typeof(UivUi).Assembly.GetManifestResourceStream(LayoutPrefix + file))
            {
                if (stream == null) throw new FileNotFoundException("embedded layout " + LayoutPrefix + file + " was not found");
                using (var reader = new StreamReader(stream, System.Text.Encoding.UTF8)) return reader.ReadToEnd();
            }
        }

        /// <summary>Parses the layout and merges Theme.xaml into it; the palette is written on top by ApplyPalette.</summary>
        public static Window LoadWindow(string file)
        {
            var window = XamlReader.Parse(ReadLayout(file)) as Window;
            if (window == null) throw new InvalidCastException(file + " is not a Window");
            var theme = XamlReader.Parse(ReadLayout("Theme.xaml")) as ResourceDictionary;
            if (theme == null) throw new InvalidCastException("Theme.xaml did not parse as a ResourceDictionary");
            window.Resources.MergedDictionaries.Add(theme);
            return window;
        }

        /// <summary>Written onto Window.Resources, in front of the merged Theme.xaml, so every DynamicResource swaps with no reload.</summary>
        public static void ApplyPalette(Window window, string name)
        {
            Dictionary<string, string> palette = UivCore.Palettes.ContainsKey(name) ? UivCore.Palettes[name] : UivCore.Palettes["dark"];
            foreach (KeyValuePair<string, string> entry in palette)
            {
                try
                {
                    var brush = new SolidColorBrush((Color)ColorConverter.ConvertFromString(entry.Value));
                    brush.Freeze();
                    window.Resources[entry.Key] = brush;
                }
                catch (Exception)
                {
                }
            }
        }

        /// <summary>"dark", "light" or null: Revit's canvas first, then the ribbon theme.</summary>
        public static string CanvasTheme()
        {
            try
            {
                return UIThemeManager.CurrentCanvasTheme == UITheme.Dark ? "dark" : "light";
            }
            catch (Exception)
            {
            }
            try
            {
                return UIThemeManager.CurrentTheme == UITheme.Dark ? "dark" : "light";
            }
            catch (Exception)
            {
                return null;
            }
        }

        public static void LoadLogo(Image image)
        {
            try
            {
                using (Stream stream = typeof(UivUi).Assembly.GetManifestResourceStream(IconName))
                {
                    if (stream == null) return;
                    var bitmap = new BitmapImage();
                    bitmap.BeginInit();
                    bitmap.StreamSource = stream;
                    bitmap.CacheOption = BitmapCacheOption.OnLoad;
                    bitmap.EndInit();
                    bitmap.Freeze();
                    image.Source = bitmap;
                }
            }
            catch (Exception)
            {
            }
        }

        /// <summary>An unowned modeless window slips behind Revit and reads as a crash.</summary>
        public static bool OwnToRevit(Window window, UIApplication uiapp)
        {
            try
            {
                new WindowInteropHelper(window).Owner = uiapp.MainWindowHandle;
                return true;
            }
            catch (Exception)
            {
                return false;
            }
        }

        // ---------------------------------------------------------------- resize grips --

        private sealed class Grip
        {
            public string Name; public HorizontalAlignment H; public VerticalAlignment V; public double W, Ht; public Cursor Cursor;
        }

        /// <summary>A borderless AllowsTransparency window has no frame to hit, so eight thumbs sit over its edges.</summary>
        public static void AddResizeGrips(Window window, Panel layer, Action onResized)
        {
            var grips = new[]
            {
                new Grip { Name = "L", H = HorizontalAlignment.Left, V = VerticalAlignment.Stretch, W = 5, Ht = double.NaN, Cursor = Cursors.SizeWE },
                new Grip { Name = "R", H = HorizontalAlignment.Right, V = VerticalAlignment.Stretch, W = 5, Ht = double.NaN, Cursor = Cursors.SizeWE },
                new Grip { Name = "T", H = HorizontalAlignment.Stretch, V = VerticalAlignment.Top, W = double.NaN, Ht = 5, Cursor = Cursors.SizeNS },
                new Grip { Name = "B", H = HorizontalAlignment.Stretch, V = VerticalAlignment.Bottom, W = double.NaN, Ht = 5, Cursor = Cursors.SizeNS },
                new Grip { Name = "TL", H = HorizontalAlignment.Left, V = VerticalAlignment.Top, W = 9, Ht = 9, Cursor = Cursors.SizeNWSE },
                new Grip { Name = "BR", H = HorizontalAlignment.Right, V = VerticalAlignment.Bottom, W = 9, Ht = 9, Cursor = Cursors.SizeNWSE },
                new Grip { Name = "TR", H = HorizontalAlignment.Right, V = VerticalAlignment.Top, W = 9, Ht = 9, Cursor = Cursors.SizeNESW },
                new Grip { Name = "BL", H = HorizontalAlignment.Left, V = VerticalAlignment.Bottom, W = 9, Ht = 9, Cursor = Cursors.SizeNESW },
            };
            foreach (Grip g in grips)
            {
                try
                {
                    var thumb = new Thumb { HorizontalAlignment = g.H, VerticalAlignment = g.V, Cursor = g.Cursor };
                    thumb.SetResourceReference(FrameworkElement.StyleProperty, "RbGrip");
                    if (!double.IsNaN(g.W)) thumb.Width = g.W;
                    if (!double.IsNaN(g.Ht)) thumb.Height = g.Ht;
                    string edges = g.Name;
                    thumb.DragDelta += (s, e) =>
                    {
                        try
                        {
                            double dx = e.HorizontalChange, dy = e.VerticalChange;
                            if (edges.Contains("L"))
                            {
                                double w = Math.Max(window.MinWidth, window.Width - dx);
                                window.Left += window.Width - w;
                                window.Width = w;
                            }
                            if (edges.Contains("R")) window.Width = Math.Max(window.MinWidth, window.Width + dx);
                            if (edges.Contains("T"))
                            {
                                double h = Math.Max(window.MinHeight, window.Height - dy);
                                window.Top += window.Height - h;
                                window.Height = h;
                            }
                            if (edges.Contains("B")) window.Height = Math.Max(window.MinHeight, window.Height + dy);
                            if (onResized != null) onResized();
                        }
                        catch (Exception)
                        {
                        }
                    };
                    layer.Children.Add(thumb);
                }
                catch (Exception)
                {
                }
            }
        }

        // ---------------------------------------------------------------- screen working area --

        /// <summary>(left, top, width, height) of the working area of the screen the window is on, in WPF units. A monitor above the primary one has a negative top.</summary>
        public static double[] WorkArea(Window window)
        {
            try
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
                catch (Exception)
                {
                }
                return new[] { area.Left / sx, area.Top / sy, area.Width / sx, area.Height / sy };
            }
            catch (Exception)
            {
                Rect area = SystemParameters.WorkArea;
                return new[] { 0.0, 0.0, area.Width, area.Height };
            }
        }
    }

    /// <summary>Never WindowState.Maximized: on a borderless transparent window that covers the task bar and lands on the primary monitor.</summary>
    internal sealed class UivFullScreen
    {
        private readonly Window window;
        public double[] Saved;

        public UivFullScreen(Window window) { this.window = window; }

        public bool Active { get { return Saved != null; } }

        public void Toggle()
        {
            if (Active) Leave(); else Enter();
        }

        public void Enter()
        {
            try
            {
                Saved = new[] { window.Left, window.Top, window.Width, window.Height };
                double[] area = UivUi.WorkArea(window);
                window.Left = area[0];
                window.Top = area[1];
                window.Width = area[2];
                window.Height = area[3];
            }
            catch (Exception)
            {
                Saved = null;
            }
        }

        public void Leave()
        {
            if (Saved == null) return;
            double[] s = Saved;
            Saved = null;
            try
            {
                window.Left = s[0];
                window.Top = s[1];
                window.Width = s[2];
                window.Height = s[3];
            }
            catch (Exception)
            {
            }
        }

        /// <summary>Dragging or resizing by hand counts as leaving full screen.</summary>
        public void Forget() { Saved = null; }
    }

    /// <summary>
    /// Slides a borderless window down to the bottom of its screen, leaving only its header bar floating clear of the
    /// taskbar, and back again (port of WindowDrawer). Top and Height are eased together on a 15 ms timer rather than by a
    /// Storyboard: an animation holds its end value over every later assignment and fights the layout pass.
    /// </summary>
    internal sealed class UivDrawer
    {
        private enum State { Open, Shrinking, Parked, Expanding }

        private readonly Window window;
        private readonly Border header;
        private readonly Panel root;
        private readonly Button button;
        private readonly UIElement grips;
        private readonly UivCore.DebugLog log;
        private readonly Action<string> onChange;

        private State state = State.Open;
        private double[] saved;
        private double savedMin;
        private SizeToContent savedSize;
        private CornerRadius savedCorner;
        private double barHeight;
        private double[] parkedAt;
        private List<KeyValuePair<UIElement, Visibility>> parts = new List<KeyValuePair<UIElement, Visibility>>();
        private DispatcherTimer timer;
        private DateTime startedAt;
        private double top0, top1, h0, h1;
        private Action done;

        public UivDrawer(Window window, Border header, Panel root, Button button, UIElement grips, UivCore.DebugLog log, Action<string> onChange)
        {
            this.window = window;
            this.header = header;
            this.root = root;
            this.button = button;
            this.grips = grips;
            this.log = log;
            this.onChange = onChange;
            try
            {
                button.Tag = "";
                button.ToolTip = UivCore.ShrinkTip;
            }
            catch (Exception)
            {
            }
        }

        public bool IsOpen { get { return state == State.Open; } }
        public bool IsParked { get { return state == State.Parked; } }

        /// <summary>The window's real size and place, even while shrunk - closing parked never saves a bar-high window.</summary>
        public double[] TrueBounds()
        {
            if (state != State.Open && saved != null) return saved;
            return new[] { window.Left, window.Top, window.Width, window.Height };
        }

        public bool Toggle()
        {
            if (state == State.Open) return Shrink();
            if (state == State.Parked) return Expand(true);
            return false;          // mid-slide: a second click is ignored
        }

        public bool Shrink()
        {
            if (state != State.Open) return false;
            double[] area;
            try
            {
                area = UivUi.WorkArea(window);
            }
            catch (Exception err)
            {
                log.Add("Shrink: screen area unreadable - " + err.Message);
                return false;
            }
            saved = new[] { window.Left, window.Top, window.Width, window.Height };
            savedMin = window.MinHeight;
            savedSize = window.SizeToContent;
            barHeight = UivCore.BarHeight(header.ActualHeight, FrameOffset());
            double landing = UivCore.ParkedTop(area, barHeight);
            // what is visible now is what comes back - recorded before anything is collapsed
            parts = new List<KeyValuePair<UIElement, Visibility>>();
            foreach (UIElement el in PartsToPark()) parts.Add(new KeyValuePair<UIElement, Visibility>(el, el.Visibility));
            savedCorner = header.CornerRadius;
            // MinHeight and SizeToContent both veto a shrinking Height
            window.MinHeight = 0.0;
            window.SizeToContent = SizeToContent.Manual;
            Pin(root.ActualHeight);
            grips.Visibility = Visibility.Collapsed;
            button.Tag = "shrunk";
            button.ToolTip = UivCore.ExpandTip;
            state = State.Shrinking;
            log.Add("Shrink: " + string.Join(",", saved) + " -> bar " + barHeight.ToString("0") + " high at top " + landing.ToString("0"));
            Slide(window.Top, landing, window.Height, barHeight, LandedParked, true);
            return true;
        }

        public bool Expand(bool animate)
        {
            if (state != State.Parked) return false;
            double[] now = { window.Left, window.Top };
            double[] area;
            try { area = UivUi.WorkArea(window); } catch (Exception) { area = saved; }
            double[] bounds = UivCore.ExpandBounds(saved, parkedAt, now, barHeight, area);
            foreach (KeyValuePair<UIElement, Visibility> p in parts)
            {
                try { p.Key.Visibility = p.Value; } catch (Exception) { }
            }
            try { header.CornerRadius = savedCorner; } catch (Exception) { }
            Pin(bounds[3]);
            window.Left = bounds[0];
            window.Width = bounds[2];
            state = State.Expanding;
            log.Add("Expand to (" + string.Join(", ", bounds) + ")" + (UivCore.BarMoved(parkedAt, now) ? " - bar was moved" : ""));
            Slide(window.Top, bounds[1], window.Height, bounds[3], LandedOpen, animate);
            return true;
        }

        /// <summary>Puts the window back with no animation, whatever it is doing.</summary>
        public void RestoreNow()
        {
            if (state == State.Shrinking || state == State.Expanding) Finish();
            if (state == State.Parked) Expand(false);
        }

        public void Stop()
        {
            try { if (timer != null) timer.Stop(); } catch (Exception) { }
            timer = null;
        }

        /// <summary>Header mouse-down while shrunk: double-click opens the window, a single click drags the bar. True when handled.</summary>
        public bool OnHeaderDown(MouseButtonEventArgs e)
        {
            if (state == State.Open) return false;
            if (state == State.Parked)
            {
                if (e.ClickCount == 2) Expand(true);
                else
                {
                    try { window.DragMove(); } catch (Exception) { }
                }
            }
            return true;
        }

        // ---------------------------------------------------------------- the slide --

        private void Slide(double t0, double t1, double hh0, double hh1, Action landed, bool animate)
        {
            top0 = t0; top1 = t1; h0 = hh0; h1 = hh1; done = landed;
            startedAt = DateTime.UtcNow;
            if (!animate)
            {
                Finish();
                return;
            }
            try
            {
                timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(UivCore.DrawerTickMs) };
                timer.Tick += (s, a) => Tick();
                timer.Start();
            }
            catch (Exception err)
            {
                log.Add("Drawer timer would not start - landing at once: " + err.Message);
                Finish();
            }
        }

        private void Tick()
        {
            if (done == null)
            {
                Stop();
                return;
            }
            try
            {
                double p = (DateTime.UtcNow - startedAt).TotalSeconds / UivCore.DrawerSeconds;
                double e = UivCore.EaseOut(p);
                window.Top = UivCore.Lerp(top0, top1, e);
                window.Height = Math.Max(1.0, UivCore.Lerp(h0, h1, e));
                if (p >= 1.0) Finish();
            }
            catch (Exception err)
            {
                log.Add("Drawer frame failed - landing at the end: " + err.Message);
                Finish();
            }
        }

        private void Finish()
        {
            Stop();
            Action landed = done;
            done = null;
            if (landed == null) return;
            try
            {
                window.Top = top1;
                window.Height = h1;
            }
            catch (Exception err)
            {
                log.Add("Drawer could not set the final bounds: " + err.Message);
            }
            landed();
        }

        private void LandedParked()
        {
            foreach (KeyValuePair<UIElement, Visibility> p in parts)
            {
                try { p.Key.Visibility = Visibility.Collapsed; } catch (Exception) { }
            }
            try { header.CornerRadius = new CornerRadius(6.0); } catch (Exception) { }
            Unpin();
            parkedAt = new[] { window.Left, window.Top };
            state = State.Parked;
            Changed();
        }

        private void LandedOpen()
        {
            Unpin();
            try
            {
                window.MinHeight = savedMin;
                window.SizeToContent = savedSize;
            }
            catch (Exception)
            {
            }
            button.Tag = "";
            button.ToolTip = UivCore.ShrinkTip;
            state = State.Open;
            try { window.Activate(); } catch (Exception) { }
            Changed();
        }

        private void Changed()
        {
            if (onChange == null) return;
            try { onChange(state.ToString()); } catch (Exception) { }
        }

        // ---------------------------------------------------------------- layout --

        /// <summary>Holds the layout at full size for the slide and lets the window clip it: re-measuring every frame reads as a squashed window, not a drawer.</summary>
        private void Pin(double height)
        {
            try
            {
                root.Height = height;
                root.VerticalAlignment = VerticalAlignment.Top;
            }
            catch (Exception)
            {
            }
        }

        private void Unpin()
        {
            try
            {
                root.Height = double.NaN;
                root.VerticalAlignment = VerticalAlignment.Stretch;
            }
            catch (Exception)
            {
            }
        }

        /// <summary>How far the header sits inside the window - the outer border.</summary>
        private double FrameOffset()
        {
            try { return header.TranslatePoint(new Point(0, 0), window).Y; } catch (Exception) { return 1.0; }
        }

        /// <summary>Everything except the header and the frames holding it: at every level from the header up, every sibling.</summary>
        private List<UIElement> PartsToPark()
        {
            var output = new List<UIElement>();
            DependencyObject el = header;
            int guard = 0;
            while (el != null && !ReferenceEquals(el, window) && guard++ < 30)
            {
                DependencyObject parent = LogicalTreeHelper.GetParent(el);
                if (parent == null) break;
                var panel = parent as Panel;
                if (panel != null)
                {
                    foreach (UIElement k in panel.Children) if (!ReferenceEquals(k, el)) output.Add(k);
                }
                else
                {
                    // a DockPanel/Border parent: siblings are the other children of a DockPanel
                    foreach (object child in LogicalTreeHelper.GetChildren(parent))
                    {
                        var ui = child as UIElement;
                        if (ui != null && !ReferenceEquals(ui, el)) output.Add(ui);
                    }
                }
                el = parent;
            }
            return output;
        }
    }
}
