using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Interop;
using System.Windows.Threading;
using RevoBIM.Tools.BwicPenetration;

namespace RevoBIM.UI.BwicPenetration
{
    /// <summary>
    /// Shrink a window to its header bar, like a drawer closing, and back (port of bwic_drawer.py). Follows the RevoBIM shrink-to-taskbar
    /// standard: Top and Height eased together on a 15 ms DispatcherTimer over 0.28 s, landing 8 px above the bottom of the screen's working
    /// area, bars stacked 4 px apart. A dialog given a <c>lift</c> parks its owner too.
    /// </summary>
    internal sealed class Drawer
    {
        public const double DurationS = 0.28, TickMs = 15, Margin = 8.0, Gap = 4.0, Moved = 2.0;

        private static readonly Dictionary<Drawer, int> Slots = new Dictionary<Drawer, int>();

        private readonly Window _window;
        private readonly FrameworkElement _header;
        private readonly Panel _body;
        private readonly ButtonBase _button;
        private readonly UIElement _grips;
        private readonly Drawer _lift;
        private bool _lifted;

        public bool Shrunk, Busy;
        /// <summary>"parked" from the moment a shrink starts, "open" from the moment an expand starts.</summary>
        public string Heading = "open";
        public Action<string> OnChange;

        private double _savedLeft, _savedTop, _savedWidth, _savedHeight, _savedMinHeight;
        private SizeToContent _savedSizeToContent;
        private double _landedLeft, _landedTop, _bar;
        private List<Tuple<UIElement, Visibility>> _hidden = new List<Tuple<UIElement, Visibility>>();
        private DispatcherTimer _timer;
        private EventHandler _tick;
        private Stopwatch _clock;
        private double[] _from, _to;
        private Action _done;

        public Drawer(Window window, FrameworkElement header, ButtonBase button, UIElement grips = null, Drawer lift = null)
        {
            _window = window;
            _header = header;
            _body = header != null ? header.Parent as Panel : null;
            _button = button;
            _grips = grips;
            _lift = lift;
            try { window.Closed += OnClosed; } catch (Exception) { }
        }

        // ---------------------------------------------------------------- pure arithmetic

        public static double EaseOut(double p)
        {
            if (p <= 0.0) return 0.0;
            if (p >= 1.0) return 1.0;
            return 1.0 - Math.Pow(1.0 - p, 3);
        }

        public static double Lerp(double a, double b, double t) { return a + (b - a) * t; }

        public static double BarHeight(double headerHeight, double headerOffset) { return headerHeight + 2.0 * headerOffset; }

        public static int FreeSlot(IEnumerable<int> taken)
        {
            int slot = 0;
            var used = new HashSet<int>(taken);
            while (used.Contains(slot)) slot++;
            return slot;
        }

        public static double ShrunkTop(double[] area, double bar, int slot)
        {
            double y = area[1] + area[3] - Margin - bar - slot * (bar + Gap);
            return Math.Max(y, area[1]);
        }

        public static void ClampRect(ref double left, ref double top, double width, double height, double[] area)
        {
            left = Math.Min(Math.Max(left, area[0]), area[0] + Math.Max(0.0, area[2] - width));
            top = Math.Min(Math.Max(top, area[1]), area[1] + Math.Max(0.0, area[3] - height));
        }

        // ---------------------------------------------------------------- public

        public void Toggle()
        {
            if (Busy) return;
            if (Shrunk) Expand(true);
            else Shrink(true);
        }

        public static double[] WorkArea(Window window)
        {
            double scale = BwiUi.DpiScale(window);
            try
            {
                System.Drawing.Rectangle wa = System.Windows.Forms.Screen.FromHandle(new WindowInteropHelper(window).Handle).WorkingArea;
                return new[] { wa.Left / scale, wa.Top / scale, wa.Width / scale, wa.Height / scale };
            }
            catch (Exception) { return new[] { 0.0, 0.0, 1920.0, 1040.0 }; }
        }

        public void Shrink(bool animate = true)
        {
            if (Shrunk || Busy) return;
            if (_lift != null && !_lift.Shrunk)
            {
                try
                {
                    _lift.Shrink(false);
                    _lifted = true;
                }
                catch (Exception) { _lifted = false; }
            }
            Window w = _window;
            _savedLeft = w.Left; _savedTop = w.Top; _savedWidth = w.ActualWidth; _savedHeight = w.ActualHeight;
            _savedMinHeight = w.MinHeight; _savedSizeToContent = w.SizeToContent;

            // MinHeight and SizeToContent both veto a Height change, and a vetoed one leaves the window half shut
            w.SizeToContent = SizeToContent.Manual;
            w.Height = _savedHeight;
            w.MinHeight = 0;
            PinBody();
            ParkGrips(true);

            double[] area = WorkArea(w);
            _bar = MeasureBar();
            int slot = FreeSlot(Slots.Where(kv => kv.Key != this).Select(kv => kv.Value));
            Slots[this] = slot;
            double top = ShrunkTop(area, _bar, slot);
            _landedLeft = w.Left;
            _landedTop = top;

            Busy = true;
            SetHeading("parked");
            Run(new[] { w.Top, w.Height }, new[] { top, _bar }, Landed, animate);
        }

        public void Expand(bool animate = true)
        {
            if (!Shrunk || Busy) return;
            Window w = _window;
            double[] area = WorkArea(w);
            bool moved = Math.Abs(w.Left - _landedLeft) > Moved || Math.Abs(w.Top - _landedTop) > Moved;
            double left, top;
            if (moved)
            {
                left = w.Left;
                top = w.Top + _bar - _savedHeight;
            }
            else
            {
                left = _savedLeft;
                top = _savedTop;
            }
            ClampRect(ref left, ref top, _savedWidth, _savedHeight, area);

            // the body comes back BEFORE the slide, still pinned to its old height, so the window opens over it
            ShowParts();
            _button.Tag = "";
            SetTip("Shrink to the taskbar  (Ctrl+Shift+H)");
            Shrunk = false;
            SetHeading("open");
            w.Left = left;
            Busy = true;
            Run(new[] { w.Top, w.Height }, new[] { top, _savedHeight }, Reopened, animate);
        }

        /// <summary>Put the window back at once, no animation.</summary>
        public void RestoreNow()
        {
            if (Busy) FinishNow();
            if (Shrunk) Expand(false);
        }

        // ---------------------------------------------------------------- keyboard and header

        /// <summary>Ctrl+Shift+H toggles. While parked, Esc, Enter and F11 reopen.</summary>
        public bool HandleKey(KeyEventArgs args)
        {
            try
            {
                ModifierKeys mods = Keyboard.Modifiers;
                ModifierKeys both = ModifierKeys.Control | ModifierKeys.Shift;
                if (args.Key == Key.H && (mods & both) == both)
                {
                    Toggle();
                    args.Handled = true;
                    return true;
                }
                if (Shrunk && (args.Key == Key.Escape || args.Key == Key.Enter || args.Key == Key.F11))
                {
                    Expand(true);
                    args.Handled = true;
                    return true;
                }
            }
            catch (Exception) { }
            return false;
        }

        /// <summary>A double click on the parked bar reopens it; a single one drags.</summary>
        public bool HeaderDown(MouseButtonEventArgs args)
        {
            try
            {
                if (Shrunk && args.ClickCount >= 2)
                {
                    Expand(true);
                    args.Handled = true;
                    return true;
                }
            }
            catch (Exception) { }
            return false;
        }

        // ---------------------------------------------------------------- the slide

        private void Run(double[] start, double[] end, Action done, bool animate)
        {
            _from = start;
            _to = end;
            _done = done;
            if (!animate)
            {
                FinishNow();
                return;
            }
            try
            {
                _clock = Stopwatch.StartNew();
                _timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(TickMs) };
                _tick = OnTick;
                _timer.Tick += _tick;
                _timer.Start();
            }
            catch (Exception) { FinishNow(); }
        }

        private void OnTick(object sender, EventArgs args)
        {
            try
            {
                double p = _clock.Elapsed.TotalSeconds / DurationS;
                double t = EaseOut(p);
                _window.Top = Lerp(_from[0], _to[0], t);
                _window.Height = Math.Max(1.0, Lerp(_from[1], _to[1], t));
                if (p >= 1.0) FinishNow();
            }
            catch (Exception) { FinishNow(); }
        }

        private void FinishNow()
        {
            StopTimer();
            try
            {
                _window.BeginAnimation(Window.TopProperty, null);
                _window.BeginAnimation(Window.HeightProperty, null);
            }
            catch (Exception) { }
            try
            {
                if (_to != null)
                {
                    _window.Top = _to[0];
                    _window.Height = Math.Max(1.0, _to[1]);
                }
            }
            catch (Exception) { }
            Action done = _done;
            _done = null;
            Busy = false;
            if (done != null)
            {
                try { done(); } catch (Exception) { }
            }
        }

        private void SetHeading(string heading)
        {
            Heading = heading;
            if (OnChange != null)
            {
                try { OnChange(heading); } catch (Exception) { }
            }
        }

        private void StopTimer()
        {
            if (_timer != null)
            {
                try
                {
                    _timer.Stop();
                    if (_tick != null) _timer.Tick -= _tick;
                }
                catch (Exception) { }
            }
            _timer = null;
            _tick = null;
        }

        // ---------------------------------------------------------------- end states

        private void Landed()
        {
            HideParts();
            Shrunk = true;
            _button.Tag = "shrunk";
            SetTip("Open the window again  (Esc, Enter or double click the bar)");
        }

        private void Reopened()
        {
            Window w = _window;
            try { w.MinHeight = _savedMinHeight; } catch (Exception) { }
            UnpinBody();
            ParkGrips(false);
            try { w.SizeToContent = _savedSizeToContent; } catch (Exception) { }
            Slots.Remove(this);
            if (_lifted && _lift != null)
            {
                _lifted = false;
                try { _lift.RestoreNow(); } catch (Exception) { }
            }
            try { w.Activate(); } catch (Exception) { }
        }

        private void OnClosed(object sender, EventArgs args)
        {
            StopTimer();
            Slots.Remove(this);
            if (_lifted && _lift != null)
            {
                _lifted = false;
                try { _lift.RestoreNow(); } catch (Exception) { }
            }
        }

        // ---------------------------------------------------------------- parts

        private double MeasureBar()
        {
            try
            {
                double offset = _header.TranslatePoint(new Point(0, 0), _window).Y;
                return BarHeight(_header.ActualHeight, offset);
            }
            catch (Exception) { return 60.0; }
        }

        private void PinBody()
        {
            if (_body == null) return;
            try
            {
                _body.Height = _body.ActualHeight;
                _body.VerticalAlignment = VerticalAlignment.Top;
            }
            catch (Exception) { }
        }

        private void UnpinBody()
        {
            if (_body == null) return;
            try
            {
                _body.Height = double.NaN;
                _body.VerticalAlignment = VerticalAlignment.Stretch;
            }
            catch (Exception) { }
        }

        private void ParkGrips(bool parked)
        {
            if (_grips == null) return;
            try { _grips.Visibility = parked ? Visibility.Collapsed : Visibility.Visible; }
            catch (Exception) { }
        }

        private void HideParts()
        {
            _hidden = new List<Tuple<UIElement, Visibility>>();
            if (_body == null) return;
            try
            {
                foreach (UIElement child in _body.Children)
                {
                    if (ReferenceEquals(child, _header)) continue;
                    _hidden.Add(Tuple.Create(child, child.Visibility));
                    child.Visibility = Visibility.Collapsed;
                }
            }
            catch (Exception) { }
        }

        private void ShowParts()
        {
            foreach (var item in _hidden)
            {
                try { item.Item1.Visibility = item.Item2; } catch (Exception) { }
            }
            _hidden = new List<Tuple<UIElement, Visibility>>();
        }

        private void SetTip(string text)
        {
            try { _button.ToolTip = text; } catch (Exception) { }
        }
    }
}
