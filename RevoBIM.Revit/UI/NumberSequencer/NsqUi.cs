using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Data;
using System.Windows.Input;
using System.Windows.Interop;
using System.Windows.Markup;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows.Media.Imaging;
using System.Windows.Shapes;
using Path = System.Windows.Shapes.Path;
using TextBox = System.Windows.Controls.TextBox;
using Button = System.Windows.Controls.Button;
using Autodesk.Revit.UI;
using RevoBIM.Tools.NumberSequencer;
using WinForms = System.Windows.Forms;

namespace RevoBIM.UI.NumberSequencer
{
    /// <summary>Frame-driven tween (port of nsq_ui.Tween): step(p) once per rendered frame, then done().</summary>
    public class Tween
    {
        private readonly double _ms;
        private readonly Action<double> _step;
        private readonly Action _done;
        private readonly bool _ease;
        private readonly Action _firstFrame;
        private double? _start, _last;
        private double _elapsed;
        private EventHandler _handler;

        public Tween(double ms, Action<double> step, Action done = null, bool ease = true, Action firstFrame = null)
        {
            _ms = ms; _step = step; _done = done; _ease = ease; _firstFrame = firstFrame;
            _handler = Frame;
            CompositionTarget.Rendering += _handler;
        }

        private void Frame(object sender, EventArgs e)
        {
            try
            {
                var re = e as RenderingEventArgs;
                double t = re != null ? re.RenderingTime.TotalMilliseconds : Environment.TickCount;
                if (_last != null && t == _last.Value) return;
                if (_start == null)
                {
                    _start = t; _last = t;
                    if (_firstFrame != null) _firstFrame();
                    _step(0.0);
                    return;
                }
                _elapsed += Math.Min(34.0, Math.Max(0.0, t - _last.Value));
                _last = t;
                double p = Math.Min(1.0, _elapsed / _ms);
                _step(_ease ? NsqUi.SmootherStep(p) : p);
                if (p >= 1.0) Finish();
            }
            catch (Exception) { Finish(); }
        }

        public void Finish()
        {
            if (_handler == null) return;
            try { CompositionTarget.Rendering -= _handler; } catch (Exception) { }
            _handler = null;
            if (_done != null) { try { _done(); } catch (Exception) { } }
        }
    }

    /// <summary>WPF plumbing shared by the Number Sequencer windows (port of nsq_ui.py).</summary>
    public static class NsqUi
    {
        private const string LayoutPrefix = "RevoBIM.UI.NumberSequencer.Layouts.";
        private const string IconName = "RevoBIM.Resources.NumberSequencer.icon.png";
        public const int AnimMs = 220;
        public const int ShrinkMs = 300;

        // ============================================================ Loading

        public static object LoadXaml(string name)
        {
            using (Stream s = typeof(NsqUi).Assembly.GetManifestResourceStream(LayoutPrefix + name))
            {
                if (s == null) throw new FileNotFoundException("Missing layout " + name);
                return XamlReader.Load(s);
            }
        }

        public static T LoadWindow<T>(string name) where T : class
        {
            return (T)LoadXaml(name);
        }

        public static void MergeTheme(FrameworkElement win)
        {
            win.Resources.MergedDictionaries.Add((ResourceDictionary)LoadXaml("Theme.xaml"));
        }

        public static SolidColorBrush Brush(string hex, int? alpha = null)
        {
            Color c = (Color)ColorConverter.ConvertFromString(hex);
            if (alpha != null) c = Color.FromArgb((byte)alpha.Value, c.R, c.G, c.B);
            var b = new SolidColorBrush(c);
            try { b.Freeze(); } catch (Exception) { }
            return b;
        }

        /// <summary>Written straight onto window.Resources, which sits in front of the merged Theme.xaml.</summary>
        public static void ApplyPalette(FrameworkElement win, string mode)
        {
            foreach (var kv in NsqCore.PaletteFor(mode)) win.Resources[kv.Key] = Brush(kv.Value);
        }

        public static ImageSource LoadIcon()
        {
            try
            {
                using (Stream s = typeof(NsqUi).Assembly.GetManifestResourceStream(IconName))
                {
                    if (s == null) return null;
                    var bmp = new BitmapImage();
                    bmp.BeginInit();
                    bmp.StreamSource = s;
                    bmp.CacheOption = BitmapCacheOption.OnLoad;
                    bmp.EndInit();
                    bmp.Freeze();
                    return bmp;
                }
            }
            catch (Exception) { return null; }
        }

        public static void FitToScreen(Window win, double margin = 40)
        {
            try
            {
                Rect area = SystemParameters.WorkArea;
                win.Width = Math.Max(Math.Min(win.Width, area.Width - margin), Math.Min(win.MinWidth, area.Width - margin));
                win.Height = Math.Max(Math.Min(win.Height, area.Height - margin), Math.Min(win.MinHeight, area.Height - margin));
            }
            catch (Exception) { }
        }

        public static bool OwnToRevit(Window win, UIApplication uiapp)
        {
            try { new WindowInteropHelper(win).Owner = uiapp.MainWindowHandle; return true; } catch (Exception) { return false; }
        }

        // ============================================================ Revit's canvas theme

        /// <summary>True / false, or null when nothing could be read.</summary>
        public static bool? CanvasIsDark(UIApplication uiapp)
        {
            Type mgr = typeof(UIThemeManager);
            try
            {
                PropertyInfo pi = mgr.GetProperty("CurrentCanvasTheme", BindingFlags.Public | BindingFlags.Static);
                if (pi != null)
                {
                    object t = pi.GetValue(null, null);
                    if (t != null) return t.ToString() == "Dark";
                }
            }
            catch (Exception) { }
            try
            {
                var c = uiapp.Application.BackgroundColor;
                return NsqCore.LuminanceIsDark(c.Red, c.Green, c.Blue);
            }
            catch (Exception) { }
            try { return UIThemeManager.CurrentTheme.ToString() == "Dark"; } catch (Exception) { }
            return null;
        }

        // ============================================================ Small helpers

        public static void Show(UIElement el, bool visible)
        {
            try { el.Visibility = visible ? Visibility.Visible : Visibility.Collapsed; } catch (Exception) { }
        }

        public static double SmootherStep(double p)
        {
            p = Math.Max(0.0, Math.Min(1.0, p));
            return p * p * p * (p * (p * 6.0 - 15.0) + 10.0);
        }

        public static void DpiScale(Visual win, out double sx, out double sy)
        {
            sx = 1.0; sy = 1.0;
            try
            {
                PresentationSource src = PresentationSource.FromVisual(win);
                if (src != null)
                {
                    Matrix m = src.CompositionTarget.TransformToDevice;
                    sx = m.M11 == 0 ? 1.0 : m.M11;
                    sy = m.M22 == 0 ? 1.0 : m.M22;
                }
            }
            catch (Exception) { }
        }

        /// <summary>(left, top, right, bottom) of the working area of the monitor the window is on, in WPF units.</summary>
        public static double[] WorkArea(Window win)
        {
            try
            {
                var a = WinForms.Screen.FromHandle(new WindowInteropHelper(win).Handle).WorkingArea;
                double sx, sy;
                DpiScale(win, out sx, out sy);
                return new[] { a.Left / sx, a.Top / sy, a.Right / sx, a.Bottom / sy };
            }
            catch (Exception)
            {
                try { Rect a = SystemParameters.WorkArea; return new[] { a.Left, a.Top, a.Right, a.Bottom }; } catch (Exception) { return null; }
            }
        }

        // ============================================================ Icons

        public static readonly Dictionary<string, string> Icons = new Dictionary<string, string>
        {
            { "seq", "M2,3 L3,3 M6,3 L14,3 M2,8 L3,8 M6,8 L14,8 M2,13 L3,13 M6,13 L14,13" },
            { "selector", "M2,2 L14,2 L14,14 L2,14 Z M2,6 L14,6 M2,10 L14,10 M6,2 L6,14" },
            { "duct", "M1,5 L15,5 L15,11 L1,11 Z M5,5 L5,11 M11,5 L11,11" },
            { "pipe", "M1,6 L15,6 M1,10 L15,10 M4,4.5 L4,11.5 M12,4.5 L12,11.5" },
            { "add", "M8,3 L8,13 M3,8 L13,8" },
            { "pick", "M3,2 L3,13 L6,10 L8,14 L10,13 L8,9 L12,9 Z" },
            { "up", "M3,10 L8,5 L13,10" },
            { "down", "M3,6 L8,11 L13,6" },
            { "top", "M3,3 L13,3 M3,12 L8,7 L13,12" },
            { "bottom", "M3,13 L13,13 M3,4 L8,9 L13,4" },
            { "remove", "M4,4 L12,12 M12,4 L4,12" },
            { "clear", "M3,4 L13,4 M6,4 L6,2 L10,2 L10,4 M4,4 L5,14 L11,14 L12,4" },
            { "start", "M4,14 L4,2 L12,4.5 L4,7" },
            { "auto", "M8,1 L8,5 M8,11 L8,15 M1,8 L5,8 M11,8 L15,8 M3,3 L5.5,5.5 M10.5,10.5 L13,13" },
            { "show", "M1,8 Q8,1 15,8 Q8,15 1,8 Z M6,8 A2,2 0 1 0 10,8 A2,2 0 1 0 6,8" },
            { "refresh", "M13,8 A5,5 0 1 1 11.5,4.5 M11.5,1.5 L11.5,4.5 L8.5,4.5" },
            { "isolate", "M2,5 L2,2 L5,2 M11,2 L14,2 L14,5 M14,11 L14,14 L11,14 M5,14 L2,14 L2,11 M6,6 L10,6 L10,10 L6,10 Z" },
            { "unisolate", "M2,5 L2,2 L5,2 M11,2 L14,2 L14,5 M14,11 L14,14 L11,14 M5,14 L2,14 L2,11 M6,6 L10,10 M10,6 L6,10" },
            { "colour", "M8,2 Q13,8 13,10 A5,5 0 0 1 3,10 Q3,8 8,2 Z" },
            { "uncolour", "M8,2 Q13,8 13,10 A5,5 0 0 1 3,10 Q3,8 8,2 Z M2,14 L14,2" },
            { "order", "M4,2 L4,14 M1,11 L4,14 L7,11 M10,3 L15,3 M10,7 L14,7 M10,11 L13,11" },
            { "tick", "M2,2 L14,2 L14,14 L2,14 Z M4.5,8 L7,10.5 L11.5,5.5" },
            { "untick", "M2,2 L14,2 L14,14 L2,14 Z" },
            { "hide", "M1,8 Q8,1 15,8 Q8,15 1,8 Z M6,8 A2,2 0 1 0 10,8 A2,2 0 1 0 6,8 M2,14 L14,2" },
            { "restore", "M2,7 L5,4 M2,7 L5,10 M2,7 L10,7 Q14,7 14,10.5 Q14,14 10,14 L6,14" },
            { "expand", "M4,3 L8,7 L12,3 M4,9 L8,13 L12,9" },
            { "collapse", "M4,7 L8,3 L12,7 M4,13 L8,9 L12,13" },
            { "copy", "M5,5 L14,5 L14,14 L5,14 Z M2,11 L2,2 L11,2" },
            { "run", "M4,2 L13,8 L4,14 Z" },
            { "apply", "M2,8 L6,12 L14,4" },
            { "filter", "M2,3 L14,3 L9.5,8.5 L9.5,13.5 L6.5,12 L6.5,8.5 Z" },
            { "cube", "M8,1.5 L14,5 L14,11 L8,14.5 L2,11 L2,5 Z M2,5 L8,8.5 L14,5 M8,8.5 L8,14.5" },
            { "group", "M1.5,2.5 L7,2.5 L7,7 L1.5,7 Z M9,9 L14.5,9 L14.5,13.5 L9,13.5 Z M7,4.75 L11.75,4.75 L11.75,9" },
            { "ungroup", "M1.5,2.5 L7,2.5 L7,7 L1.5,7 Z M9,9 L14.5,9 L14.5,13.5 L9,13.5 Z M10,2.5 L14,6.5 M14,2.5 L10,6.5" },
            { "regroup", "M1.5,2.5 L7,2.5 L7,7 L1.5,7 Z M1.5,9 L7,9 L7,13.5 L1.5,13.5 Z M11.5,2.5 L11.5,13 M9,10.5 L11.5,13 L14,10.5" },
            { "tag", "M2,2 L8,2 L14.5,8.5 L8.5,14.5 L2,8 Z M5.25,5.25 L5.3,5.3" },
            { "sheet", "M3,1.5 L10,1.5 L13,4.5 L13,14.5 L3,14.5 Z M10,1.5 L10,4.5 L13,4.5 M5.5,8 L10.5,8 M5.5,11 L10.5,11" },
        };

        private static Path MakeStrokePath(string data)
        {
            var p = new Path
            {
                Data = Geometry.Parse(data),
                StrokeThickness = 1.6,
                StrokeStartLineCap = PenLineCap.Round,
                StrokeEndLineCap = PenLineCap.Round,
                StrokeLineJoin = PenLineJoin.Round,
            };
            var b = new Binding("Foreground") { RelativeSource = new RelativeSource(RelativeSourceMode.FindAncestor, typeof(Control), 1) };
            p.SetBinding(Shape.StrokeProperty, b);
            return p;
        }

        /// <summary>A Viewbox holding the 16 x 16 path, stroked in the nearest control's Foreground.</summary>
        public static UIElement Icon(string key, double size = 14)
        {
            string data;
            if (!Icons.TryGetValue(key, out data)) return null;
            Path p = MakeStrokePath(data);
            p.Width = 16;
            p.Height = 16;
            return new Viewbox { Width = size, Height = size, Child = p };
        }

        public static UIElement StepBadge(string step)
        {
            var b = new Border();
            b.SetResourceReference(FrameworkElement.StyleProperty, "SubStepBadge");
            var tb = new TextBlock { Text = step };
            tb.SetResourceReference(FrameworkElement.StyleProperty, "SubStepText");
            b.Child = tb;
            return b;
        }

        /// <summary>Icon plus label as the button's content. Set the label through this, never through Content.</summary>
        public static void SetButton(ContentControl btn, string key, string text, string step = null)
        {
            var sp = new StackPanel { Orientation = Orientation.Horizontal };
            if (!string.IsNullOrEmpty(step)) sp.Children.Add(StepBadge(step));
            UIElement ic = Icon(key);
            if (ic != null) sp.Children.Add(ic);
            if (!string.IsNullOrEmpty(text))
            {
                var tb = new TextBlock { Text = text, VerticalAlignment = VerticalAlignment.Center };
                if (ic != null) tb.Margin = new Thickness(6, 0, 0, 0);
                sp.Children.Add(tb);
            }
            btn.Content = sp;
        }

        public static void SetIconData(Path path, string key)
        {
            try { path.Data = Geometry.Parse(Icons[key]); } catch (Exception) { }
        }

        /// <summary>Every button or tab whose Tag reads 'i:icon' gets that icon in front of its text. Never allowed to fail the window.</summary>
        public static int Iconize(DependencyObject root)
        {
            int done = 0;
            var stack = new Stack<DependencyObject>();
            stack.Push(root);
            while (stack.Count > 0)
            {
                DependencyObject node = stack.Pop();
                try
                {
                    var fe = node as FrameworkElement;
                    var cc = node as ContentControl;
                    if (cc != null && fe != null && fe.Tag != null)
                    {
                        string t = fe.Tag.ToString();
                        if (t.StartsWith("i:"))
                        {
                            string text = cc.Content as string ?? "";
                            SetButton(cc, t.Substring(2), text);
                            done++;
                            continue;
                        }
                    }
                }
                catch (Exception) { }
                try
                {
                    foreach (object child in LogicalTreeHelper.GetChildren(node))
                    {
                        var d = child as DependencyObject;
                        if (d != null) stack.Push(d);
                    }
                }
                catch (Exception) { }
            }
            return done;
        }

        // ============================================================ Animation

        private static readonly Dictionary<string, DoubleAnimation> RunningAnim = new Dictionary<string, DoubleAnimation>();

        /// <summary>Ease el's property to a value; when it lands the value is set for real and the animation let go.</summary>
        public static void Animate(DependencyObject el, DependencyProperty prop, double to, double? from = null, int ms = AnimMs, Action done = null)
        {
            var dur = new Duration(TimeSpan.FromMilliseconds(ms));
            DoubleAnimation anim = from != null ? new DoubleAnimation(from.Value, to, dur) : new DoubleAnimation(to, dur);
            anim.EasingFunction = new CubicEase { EasingMode = EasingMode.EaseOut };
            string key = System.Runtime.CompilerServices.RuntimeHelpers.GetHashCode(el) + ":" + prop.Name;
            RunningAnim[key] = anim;
            anim.Completed += (s, e) =>
            {
                DoubleAnimation cur;
                if (!RunningAnim.TryGetValue(key, out cur) || !ReferenceEquals(cur, anim)) return;
                RunningAnim.Remove(key);
                try
                {
                    el.SetValue(prop, to);
                    ((IAnimatable)el).BeginAnimation(prop, null);
                }
                catch (Exception) { }
                if (done != null) done();
            };
            ((IAnimatable)el).BeginAnimation(prop, anim);
        }

        /// <summary>A chevron for a fold button; returns its RotateTransform (0 = open).</summary>
        public static RotateTransform Chevron(ContentControl button)
        {
            Path p = MakeStrokePath("M0,0 L4,4 L8,0");
            p.RenderTransformOrigin = new Point(0.5, 0.5);
            var turn = new RotateTransform();
            p.RenderTransform = turn;
            button.Content = p;
            return turn;
        }

        // ============================================================ Prompts

        public static int? PromptNumber(Window owner, string mode, string title, string message, int? defaultValue, int lo, int hi)
        {
            var dlg = (Window)LoadXaml("NumberSequencerPrompt.xaml");
            MergeTheme(dlg);
            ApplyPalette(dlg, mode);
            try { Iconize(dlg); } catch (Exception) { }
            try { dlg.Owner = owner; } catch (Exception) { }
            Func<string, object> f = dlg.FindName;
            ((TextBlock)f("PVersion")).Text = "v" + NsqCore.Version;
            ((TextBlock)f("PTitle")).Text = title;
            ((TextBlock)f("PMessage")).Text = message;
            var box = (TextBox)f("PValue");
            box.Text = defaultValue == null ? "" : defaultValue.ToString();
            int? result = null;

            Action ok = () =>
            {
                try
                {
                    int? v = NsqCore.ParsePosition(box.Text, lo, hi);
                    if (v == null) { ((TextBlock)f("PError")).Text = "Type a whole number from " + lo + " to " + hi; return; }
                    result = v;
                    dlg.DialogResult = true;
                }
                catch (Exception) { dlg.Close(); }
            };
            Action cancel = () => { try { dlg.DialogResult = false; } catch (Exception) { dlg.Close(); } };
            ((Button)f("POk")).Click += (s, e) => ok();
            ((Button)f("PCancel")).Click += (s, e) => cancel();
            ((UIElement)f("PHeader")).MouseLeftButtonDown += (s, e) => { try { dlg.DragMove(); } catch (Exception) { } };
            dlg.PreviewKeyDown += (s, e) =>
            {
                if (e.Key == Key.Enter) { ok(); e.Handled = true; }
                else if (e.Key == Key.Escape) { cancel(); e.Handled = true; }
            };
            dlg.Loaded += (s, e) => { try { box.Focus(); box.SelectAll(); } catch (Exception) { } };
            dlg.ShowDialog();
            return result;
        }

        public static bool AskYesNo(Window owner, string mode, string title, string message, string yes = "Yes", string no = "No")
        {
            var dlg = (Window)LoadXaml("NumberSequencerPrompt.xaml");
            MergeTheme(dlg);
            ApplyPalette(dlg, mode);
            try { dlg.Owner = owner; } catch (Exception) { }
            Func<string, object> f = dlg.FindName;
            dlg.Title = "RevoBIM Number Sequencer - " + title;
            ((TextBlock)f("PVersion")).Text = "v" + NsqCore.Version;
            ((TextBlock)f("PTitle")).Text = title;
            ((TextBlock)f("PMessage")).Text = message;
            Show((UIElement)f("PValue"), false);
            Show((UIElement)f("PError"), false);
            SetButton((ContentControl)f("POk"), "apply", yes);
            SetButton((ContentControl)f("PCancel"), "clear", no);
            bool result = false;
            Action ok = () => { result = true; try { dlg.DialogResult = true; } catch (Exception) { dlg.Close(); } };
            Action cancel = () => { try { dlg.DialogResult = false; } catch (Exception) { dlg.Close(); } };
            ((Button)f("POk")).Click += (s, e) => ok();
            ((Button)f("PCancel")).Click += (s, e) => cancel();
            dlg.PreviewKeyDown += (s, e) =>
            {
                if (e.Key == Key.Enter) { ok(); e.Handled = true; }
                else if (e.Key == Key.Escape) { cancel(); e.Handled = true; }
            };
            ((UIElement)f("PHeader")).MouseLeftButtonDown += (s, e) => { try { dlg.DragMove(); } catch (Exception) { } };
            dlg.ShowDialog();
            return result;
        }
    }

    /// <summary>Drag by the header, full screen by bounds, eight grips, edge double-click full height, shrink to a bar (port of nsq_ui.Chrome).</summary>
    public class Chrome
    {
        private static readonly Dictionary<string, string> Grips = new Dictionary<string, string>
        {
            { "GripL", "l" }, { "GripR", "r" }, { "GripT", "t" }, { "GripB", "b" },
            { "GripTL", "tl" }, { "GripTR", "tr" }, { "GripBL", "bl" }, { "GripBR", "br" },
        };

        private readonly Window _win;
        private readonly FrameworkElement _logo;
        private readonly Border _header;
        private readonly Button _minBtn;
        private readonly Action _onClose;
        public bool Full;
        private double[] _saved;
        private double[] _tall;       // (Top, Height)
        public bool Shrunk;
        public double[] Before;       // (Top, Height, MinHeight)
        private bool _moving;
        private List<UIElement> _hidden = new List<UIElement>();
        private CornerRadius? _corner;

        public Chrome(Window win, Border header, Button fullBtn, Button closeBtn, FrameworkElement logo = null, Button minBtn = null, Action onClose = null)
        {
            _win = win; _logo = logo; _header = header; _minBtn = minBtn; _onClose = onClose;
            header.MouseLeftButtonDown += OnHeader;
            fullBtn.Click += (s, e) => ToggleFull();
            closeBtn.Click += OnClose;
            win.PreviewKeyDown += OnKey;
            foreach (var kv in Grips)
            {
                var g = win.FindName(kv.Key) as System.Windows.Controls.Primitives.Thumb;
                if (g != null) g.DragDelta += MakeGrip(kv.Value);
            }
            foreach (string name in new[] { "GripT", "GripB" })
            {
                var g = win.FindName(name) as UIElement;
                if (g != null) g.PreviewMouseLeftButtonDown += OnEdgeDown;
            }
            if (minBtn != null)
            {
                minBtn.Click += (s, e) =>
                {
                    try { if (Shrunk) Expand(); else Shrink(); } catch (Exception) { _moving = false; }
                };
                PaintMin();
            }
        }

        public void ClearTall() { _tall = null; }

        private void OnEdgeDown(object sender, MouseButtonEventArgs e)
        {
            try
            {
                if (e.ClickCount != 2 || Shrunk) return;
                e.Handled = true;
                ToggleTall();
            }
            catch (Exception) { }
        }

        public void ToggleTall()
        {
            Window w = _win;
            double[] area = NsqUi.WorkArea(w);
            if (area == null) return;
            double top = area[1], bottom = area[3];
            if (_tall != null && Math.Abs(w.Top - top) < 1.5 && Math.Abs(w.Height - (bottom - top)) < 1.5)
            {
                w.Top = _tall[0]; w.Height = _tall[1];
                _tall = null;
                return;
            }
            _tall = new[] { w.Top, w.Height };
            w.Top = top;
            w.Height = bottom - top;
        }

        private void PaintMin()
        {
            if (_minBtn == null) return;
            var p = new Path
            {
                StrokeThickness = 1.8,
                StrokeStartLineCap = PenLineCap.Round,
                StrokeEndLineCap = PenLineCap.Round,
                StrokeLineJoin = PenLineJoin.Round,
            };
            if (Shrunk)
            {
                p.Data = Geometry.Parse("M6,12 L6,1.5 M1.5,6 L6,1.5 L10.5,6");
                p.SetResourceReference(Shape.StrokeProperty, "Green");
                _minBtn.ToolTip = "Bring the window back";
            }
            else
            {
                p.Data = Geometry.Parse("M6,0 L6,7.5 M2.5,4.5 L6,8 L9.5,4.5 M0.5,11.5 L11.5,11.5");
                p.SetResourceReference(Shape.StrokeProperty, "Muted");
                _minBtn.ToolTip = "Shrink to a bar at the bottom of the screen, so Revit can be seen";
            }
            _minBtn.Content = p;
        }

        private List<UIElement> Parts()
        {
            var o = new List<UIElement>();
            try
            {
                var panel = _header.Parent as Panel;
                if (panel != null) foreach (UIElement child in panel.Children) if (!ReferenceEquals(child, _header)) o.Add(child);
            }
            catch (Exception) { }
            return o;
        }

        public void Shrink()
        {
            if (Shrunk || _moving) return;
            Window w = _win;
            if (Full) LeaveFull();
            double[] area = NsqUi.WorkArea(w);
            double bar = _header.ActualHeight + 2.0;
            double to = (area != null ? area[3] : w.Top + w.Height) - bar - 6.0;
            double start = w.Top;
            Before = new[] { w.Top, w.Height, w.MinHeight };
            _moving = true;
            new Tween(NsqUi.ShrinkMs, e => w.Top = start + (to - start) * e, () =>
            {
                _hidden = Parts().Where(el => el.Visibility == Visibility.Visible).ToList();
                foreach (UIElement el in _hidden) NsqUi.Show(el, false);
                try { _corner = _header.CornerRadius; _header.CornerRadius = new CornerRadius(6); } catch (Exception) { _corner = null; }
                w.MinHeight = 0;
                w.Height = bar;
                w.Top = to;
                Shrunk = true;
                _moving = false;
                PaintMin();
            });
        }

        public void Expand()
        {
            if (!Shrunk || _moving) return;
            Window w = _win;
            double top = Before[0], height = Before[1], minH = Before[2];
            foreach (UIElement el in _hidden) NsqUi.Show(el, true);
            _hidden = new List<UIElement>();
            if (_corner != null) { try { _header.CornerRadius = _corner.Value; } catch (Exception) { } }
            w.Height = height;
            double start = w.Top;
            _moving = true;
            new Tween(NsqUi.ShrinkMs, e => w.Top = start + (top - start) * e, () =>
            {
                w.Top = top;
                w.MinHeight = minH;
                Shrunk = false;
                _moving = false;
                PaintMin();
            });
        }

        private void OnHeader(object sender, MouseButtonEventArgs e)
        {
            try
            {
                object src = e.OriginalSource;
                if (_logo != null && ReferenceEquals(src, _logo)) return;
                if (e.ClickCount == 2)
                {
                    if (Shrunk) Expand(); else ToggleFull();
                    return;
                }
                if (Full) LeaveFull();
                _win.DragMove();
            }
            catch (Exception) { }
        }

        private void OnClose(object sender, RoutedEventArgs e)
        {
            try
            {
                if (_onClose != null) _onClose(); else _win.Close();
            }
            catch (Exception)
            {
                try { _win.Close(); } catch (Exception) { }
            }
        }

        private void OnKey(object sender, KeyEventArgs e)
        {
            try
            {
                if (e.Key == Key.F11) { ToggleFull(); e.Handled = true; }
                else if (e.Key == Key.Escape && Full) { LeaveFull(); e.Handled = true; }
            }
            catch (Exception) { }
        }

        public void ToggleFull()
        {
            if (Shrunk) { Expand(); return; }
            if (Full) LeaveFull(); else EnterFull();
        }

        public void EnterFull()
        {
            try
            {
                Window w = _win;
                _saved = new[] { w.Left, w.Top, w.Width, w.Height };
                var area = WinForms.Screen.FromHandle(new WindowInteropHelper(w).Handle).WorkingArea;
                double sx, sy;
                NsqUi.DpiScale(w, out sx, out sy);
                w.Left = area.Left / sx;
                w.Top = area.Top / sy;
                w.Width = area.Width / sx;
                w.Height = area.Height / sy;
                Full = true;
            }
            catch (Exception) { Full = false; }
        }

        public void LeaveFull()
        {
            if (!Full) return;
            Full = false;
            try
            {
                if (_saved != null)
                {
                    _win.Left = _saved[0]; _win.Top = _saved[1]; _win.Width = _saved[2]; _win.Height = _saved[3];
                }
            }
            catch (Exception) { }
        }

        private System.Windows.Controls.Primitives.DragDeltaEventHandler MakeGrip(string sides)
        {
            return (sender, e) =>
            {
                try
                {
                    if (Shrunk) return;
                    Full = false;
                    Window w = _win;
                    double dx = e.HorizontalChange, dy = e.VerticalChange;
                    if (sides.Contains("l"))
                    {
                        double nw = Math.Max(w.MinWidth, w.Width - dx);
                        w.Left = w.Left + (w.Width - nw);
                        w.Width = nw;
                    }
                    if (sides.Contains("r")) w.Width = Math.Max(w.MinWidth, w.Width + dx);
                    if (sides.Contains("t"))
                    {
                        double nh = Math.Max(w.MinHeight, w.Height - dy);
                        w.Top = w.Top + (w.Height - nh);
                        w.Height = nh;
                    }
                    if (sides.Contains("b")) w.Height = Math.Max(w.MinHeight, w.Height + dy);
                }
                catch (Exception) { }
            };
        }
    }

    /// <summary>A section whose chevron button slides its body shut (height to 0) and open again (port of nsq_ui.Section).</summary>
    public class Section
    {
        public string Key;
        public bool Open = true;
        private readonly Button _btn;
        private readonly FrameworkElement _body;
        private readonly RowDefinition _row;
        private readonly Action<string, bool> _changed;
        private readonly Action<double> _resize;
        private double _last;
        private int _token;
        private readonly RotateTransform _turn;

        public Section(string key, Button button, FrameworkElement body, RowDefinition row, Action<string, bool> changed, bool shut, Action<double> resize)
        {
            Key = key; _btn = button; _body = body; _row = row; _changed = changed; _resize = resize;
            _turn = NsqUi.Chevron(button);
            button.Click += (s, e) => { try { Set(!Open); } catch (Exception) { } };
            if (shut) Set(false, false);
        }

        private double Natural()
        {
            if (_row != null && _last > 0) return _last;
            double w = _body.ActualWidth;
            if (w <= 0)
            {
                var parent = _body.Parent as FrameworkElement;
                w = parent != null && parent.ActualWidth > 0 ? parent.ActualWidth : 600;
            }
            _body.Measure(new Size(w, double.PositiveInfinity));
            double h = _body.DesiredSize.Height;
            return _row != null ? Math.Min(h, 400.0) : h;
        }

        private void Tell(double h)
        {
            if (_resize == null || h == 0) return;
            Thickness m = _body.Margin;
            double extra = m.Top + m.Bottom;
            try { _resize(h > 0 ? h + extra : h - extra); } catch (Exception) { }
        }

        public void Set(bool open, bool animated = true)
        {
            if (open == Open) return;
            Open = open;
            _token++;
            int token = _token;
            FrameworkElement body = _body;
            double angle = open ? 0.0 : -90.0;
            if (animated) NsqUi.Animate(_turn, RotateTransform.AngleProperty, angle);
            else _turn.Angle = angle;
            if (open)
            {
                if (_row != null) _row.Height = new GridLength(1, GridUnitType.Star);
                body.Height = double.NaN;
                NsqUi.Show(body, true);
                double target = Natural();
                Tell(target);
                if (animated && target > 0)
                {
                    body.Height = 0.0;
                    NsqUi.Animate(body, FrameworkElement.HeightProperty, target, 0.0, NsqUi.AnimMs, () => { if (token == _token) body.Height = double.NaN; });
                }
            }
            else
            {
                double h = body.ActualHeight;
                if (h > 0) _last = h;
                Tell(-h);
                Action shut = () =>
                {
                    if (token != _token) return;
                    NsqUi.Show(body, false);
                    body.Height = double.NaN;
                    if (_row != null) _row.Height = GridLength.Auto;
                };
                if (animated && h > 0) NsqUi.Animate(body, FrameworkElement.HeightProperty, 0.0, h, NsqUi.AnimMs, shut);
                else shut();
            }
            if (_changed != null) { try { _changed(Key, open); } catch (Exception) { } }
        }
    }
}



