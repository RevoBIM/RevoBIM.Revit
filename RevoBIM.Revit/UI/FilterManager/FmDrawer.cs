using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Threading;

namespace RevoBIM.UI.FilterManager
{
    /// <summary>
    /// Shrink a window to its title bar. The shrink button (top right, before full screen and close) slides the
    /// window down like a drawer until only its header bar is left, floating just above the taskbar, so the model
    /// can be seen. The button turns into a green up arrow; that, or a double click on the bar, slides it back.
    /// Port of fm_drawer.py. Needs, in the window's layout: pnlHeader (a direct child of the root panel),
    /// btnShrink, and inside it pthShrink and pthExpand.
    /// </summary>
    public class FmDrawer
    {
        public const double Duration = 0.28;   // seconds, either way
        public const int TickMs = 15;
        public const double Margin = 8;        // gap between the lowest bar and the taskbar
        public const double Gap = 4;           // gap between stacked bars

        private static readonly List<FmDrawer> Drawers = new List<FmDrawer>();   // every live drawer, so bars can stack

        public static double EaseOut(double p)
        {
            p = Math.Max(0.0, Math.Min(1.0, p));
            return 1.0 - Math.Pow(1.0 - p, 3);
        }

        public static double Lerp(double a, double b, double t) { return a + (b - a) * t; }

        /// <summary>Where a bar lands: the bottom of the working area, above any bars already shrunk there.</summary>
        public static double ShrunkTop(double areaTop, double areaHeight, double bar, IEnumerable<double> below)
        {
            double used = 0.0;
            if (below != null) foreach (double h in below) used += h + Gap;
            double top = areaTop + areaHeight - Margin - used - bar;
            return Math.Max(areaTop, top);
        }

        public static FmDrawer DrawerOf(Window window)
        {
            foreach (FmDrawer d in Drawers)
                if (ReferenceEquals(d.Window, window)) return d;
            return null;
        }

        public readonly Window Window;
        public bool Shrunk;
        public bool Moving;
        private double[] _saved;               // left, top, width, height, minHeight
        private SizeToContent _savedSize;
        private ResizeMode _savedResize;
        private readonly List<UIElement> _hidden = new List<UIElement>();
        private readonly List<FmDrawer> _lifted = new List<FmDrawer>();   // owners this window shrank on its way down
        private double _bar;
        private DispatcherTimer _timer;
        private string _job;
        private double[] _start, _end;
        private Stopwatch _clock;
        private double _landedTop;

        public FmDrawer(Window window)
        {
            Window = window;
            Drawers.Add(this);
            try { window.Closed += OnClosed; }
            catch (Exception) { }
        }

        private T Part<T>(string name) where T : class
        {
            try { return Window.FindName(name) as T; }
            catch (Exception) { return null; }
        }

        private double BarHeight()
        {
            var header = Part<FrameworkElement>("pnlHeader");
            double border = 0.0;
            try { border = Window.BorderThickness.Top + Window.BorderThickness.Bottom; }
            catch (Exception) { }
            try { return header.ActualHeight + border; }
            catch (Exception) { return 44.0; }
        }

        private List<double> OthersBelow()
        {
            var heights = new List<double>();
            foreach (FmDrawer d in Drawers)
            {
                if (ReferenceEquals(d, this) || !(d.Shrunk || (d.Moving && d._job == "down"))) continue;
                heights.Add(d._bar);
            }
            return heights;
        }

        public void Toggle()
        {
            if (Shrunk) Expand(); else Shrink();
        }

        public void Shrink()
        {
            if (Shrunk || Moving) return;
            Window w = Window;

            // owners first, so the main window does not stay over Revit
            _lifted.Clear();
            Window owner = OwnerOf(w);
            while (owner != null)
            {
                FmDrawer od = DrawerOf(owner);
                if (od != null && !od.Shrunk && !od.Moving)
                {
                    od.ShrinkNow();
                    _lifted.Add(od);
                }
                owner = OwnerOf(owner);
            }

            Snapshot();
            _bar = BarHeight();
            try { w.SizeToContent = SizeToContent.Manual; }
            catch (Exception) { }
            w.MinHeight = 0;

            Rect a = Area();
            double endTop = ShrunkTop(a.Top, a.Height, _bar, OthersBelow());
            Slide(new[] { w.Top, w.Height }, new[] { endTop, _bar }, "down");
        }

        public void Expand()
        {
            if (!Shrunk || Moving) return;
            Window w = Window;
            ShowParts();
            SetGlyph(false);
            double[] saved = _saved ?? new[] { w.Left, w.Top, w.Width, 600.0, 0.0 };
            // if the bar was dragged, grow up out of where it is now, kept on the screen; otherwise go back
            Rect a = Area();
            double targetTop = saved[1];
            if (Math.Abs(w.Top - _landedTop) > 2 || Math.Abs(w.Left - saved[0]) > 2)
                targetTop = Math.Max(a.Top, Math.Min(w.Top + _bar - saved[3], a.Top + a.Height - saved[3]));
            else
                w.Left = saved[0];
            Shrunk = false;
            Slide(new[] { w.Top, w.Height }, new[] { targetTop, saved[3] }, "up");
        }

        /// <summary>No animation - used for an owner going down with its dialog.</summary>
        public void ShrinkNow()
        {
            if (Shrunk || Moving) return;
            Window w = Window;
            Snapshot();
            _bar = BarHeight();
            try { w.SizeToContent = SizeToContent.Manual; }
            catch (Exception) { }
            w.MinHeight = 0;
            Rect a = Area();
            w.Top = ShrunkTop(a.Top, a.Height, _bar, OthersBelow());
            w.Height = _bar;
            Landed();
        }

        /// <summary>No animation - the window put straight back.</summary>
        public void RestoreNow()
        {
            if (!Shrunk) return;
            StopTimer();
            ShowParts();
            SetGlyph(false);
            Shrunk = false;
            RestoreSaved(true);
        }

        // -- the slide -------------------------------------------------------------
        private void Slide(double[] start, double[] end, string job)
        {
            StopTimer();
            Moving = true;
            _job = job;
            _start = start;
            _end = end;
            _clock = Stopwatch.StartNew();
            try
            {
                _timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(TickMs) };
                _timer.Tick += (s, a) =>
                {
                    try { Step(); }
                    catch (Exception) { Finish(); }
                };
                _timer.Start();
            }
            catch (Exception)
            {
                _timer = null;
                Finish();
            }
        }

        private void Step()
        {
            double elapsed = _clock.Elapsed.TotalSeconds;
            double p = Duration <= 0 ? 1.0 : Math.Min(1.0, Math.Max(0.0, elapsed / Duration));
            double t = EaseOut(p);
            Window.Top = Lerp(_start[0], _end[0], t);
            Window.Height = Math.Max(1.0, Lerp(_start[1], _end[1], t));
            if (p >= 1.0) Finish();
        }

        private void Finish()
        {
            StopTimer();
            Window w = Window;
            try { w.Top = _end[0]; w.Height = Math.Max(1.0, _end[1]); }
            catch (Exception) { }
            string job = _job;
            Moving = false;
            _job = null;
            if (job == "down") Landed();
            else
            {
                RestoreSaved(false);
                for (int i = _lifted.Count - 1; i >= 0; i--) _lifted[i].RestoreNow();
                _lifted.Clear();
                try { w.Activate(); }
                catch (Exception) { }
            }
        }

        private void StopTimer()
        {
            if (_timer != null)
            {
                try { _timer.Stop(); }
                catch (Exception) { }
            }
            _timer = null;
        }

        // -- states ----------------------------------------------------------------
        private void Landed()
        {
            HideParts();
            SetGlyph(true);
            _landedTop = Window.Top;
            try { Window.ResizeMode = ResizeMode.NoResize; }
            catch (Exception) { }
            Shrunk = true;
        }

        private void Snapshot()
        {
            Window w = Window;
            _saved = new[] { w.Left, w.Top, w.Width, w.ActualHeight > 0 ? w.ActualHeight : w.Height, w.MinHeight };
            _savedSize = w.SizeToContent;
            _savedResize = w.ResizeMode;
        }

        private void RestoreSaved(bool move)
        {
            if (_saved == null) return;
            Window w = Window;
            if (move)
            {
                w.Left = _saved[0];
                w.Top = _saved[1];
                w.Height = _saved[3];
            }
            try { w.MinHeight = _saved[4]; }
            catch (Exception) { }
            try { w.ResizeMode = _savedResize; }
            catch (Exception) { }
            try { w.SizeToContent = _savedSize; }
            catch (Exception) { }
            _saved = null;
        }

        // -- the body --------------------------------------------------------------
        private void HideParts()
        {
            var header = Part<FrameworkElement>("pnlHeader");
            _hidden.Clear();
            if (header == null) return;
            try
            {
                var parent = header.Parent as Panel;
                if (parent == null) return;
                foreach (UIElement child in parent.Children)
                {
                    if (ReferenceEquals(child, header)) continue;
                    if (child.Visibility == Visibility.Visible)
                    {
                        child.Visibility = Visibility.Collapsed;
                        _hidden.Add(child);
                    }
                }
            }
            catch (Exception) { }
        }

        private void ShowParts()
        {
            foreach (UIElement child in _hidden)
            {
                try { child.Visibility = Visibility.Visible; }
                catch (Exception) { }
            }
            _hidden.Clear();
        }

        private void SetGlyph(bool shrunk)
        {
            var down = Part<UIElement>("pthShrink");
            var up = Part<UIElement>("pthExpand");
            var button = Part<FrameworkElement>("btnShrink");
            try
            {
                down.Visibility = shrunk ? Visibility.Collapsed : Visibility.Visible;
                up.Visibility = shrunk ? Visibility.Visible : Visibility.Collapsed;
            }
            catch (Exception) { }
            try
            {
                button.ToolTip = shrunk
                    ? "Expand the window again (or double click the bar)"
                    : "Shrink to the taskbar - slide the window down to its title bar so the model can be seen";
            }
            catch (Exception) { }
        }

        // -- surroundings ----------------------------------------------------------
        private Rect Area()
        {
            try { return FmUi.WorkingArea(Window); }
            catch (Exception) { return new Rect(0, 0, 1280, 800); }
        }

        private static Window OwnerOf(Window window)
        {
            try { return window.Owner; }
            catch (Exception) { return null; }
        }

        private void OnClosed(object sender, EventArgs args)
        {
            StopTimer();
            for (int i = _lifted.Count - 1; i >= 0; i--)
            {
                try { _lifted[i].RestoreNow(); }
                catch (Exception) { }
            }
            _lifted.Clear();
            Drawers.Remove(this);
        }

        /// <summary>
        /// For a header's MouseLeftButtonDown while shrunk: a double click expands, anything else drags the
        /// bar. True when it handled the press.
        /// </summary>
        public static bool OnHeaderDown(FmDrawer drawer, Window window, MouseButtonEventArgs args)
        {
            if (drawer == null || !(drawer.Shrunk || drawer.Moving)) return false;
            try
            {
                if (args.ClickCount == 2)
                {
                    drawer.Expand();
                    return true;
                }
            }
            catch (Exception) { }
            try { window.DragMove(); }
            catch (Exception) { }
            return true;
        }
    }
}
