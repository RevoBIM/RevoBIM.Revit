using System;
using System.Diagnostics;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Threading;

namespace RevoBIM.Arcade.Services
{
    /// <summary>The drawer arithmetic, free of WPF state so the selftest can check it.</summary>
    public static class DrawerMath
    {
        public const double DurationMs = 220;
        public const double TickMs = 15;
        public const double TaskbarGap = 8;

        public static double Tween(double start, double end, double progress)
        {
            if (progress <= 0) return start;
            if (progress >= 1) return end;
            double e = 1 - Math.Pow(1 - progress, 3);   // ease out
            return start + (end - start) * e;
        }

        /// <summary>Top of a parked bar: its bottom edge 8 px clear of the taskbar.</summary>
        public static double ParkedTop(Rect workArea, double bar) => workArea.Bottom - bar - TaskbarGap;

        /// <summary>
        /// Where the window opens to. A bar left where it parked returns to its saved place; a bar
        /// that was dragged elsewhere opens upward from where it now sits.
        /// </summary>
        public static (double Left, double Top, double Height) ExpandRect(
            Rect saved, Point landed, Point current, double bar, Rect area)
        {
            double height = Math.Min(saved.Height, area.Height);
            if (Math.Abs(current.X - landed.X) < 1 && Math.Abs(current.Y - landed.Y) < 1)
                return (saved.Left, saved.Top, height);
            double left = ScreenHelper.Clamp(current.X, area.Left, area.Right - saved.Width);
            double top = ScreenHelper.Clamp(current.Y + bar - height, area.Top, area.Bottom - height);
            return (left, top, height);
        }
    }

    /// <summary>
    /// Shrink to the taskbar, ported from the Addin Manager / Callout to 3D drawer. The window
    /// slides down like a drawer closing until only its header bar floats 8 px above the
    /// taskbar; the button turns into a green up arrow that slides it back.
    /// The five traps and where they are handled:
    ///  1 no WPF animation holds the window: the slide is eased by hand on a 15 ms timer;
    ///  2 MinHeight and SizeToContent veto Height: both relaxed for the slide, restored after;
    ///  3 the body is pinned at its full height during the slide so nothing re-measures;
    ///  4 resize is switched off while parked so the edges do not swallow the arrow click;
    ///  5 Escape, Enter and F11 reopen a parked bar, other keys are swallowed.
    /// </summary>
    public sealed class DrawerController
    {
        readonly Window _window;
        readonly FrameworkElement _header;
        readonly FrameworkElement _root;
        readonly Button _button;
        readonly UIElement _shrinkGlyph, _expandGlyph;
        readonly UIElement[] _hideWhenParked;

        readonly Stopwatch _clock = new Stopwatch();
        DispatcherTimer? _timer;

        Rect _saved;
        Point _landed;
        double _bar;
        double _savedMinHeight;
        ResizeMode _savedResize;
        Visibility[] _savedVisibility = Array.Empty<Visibility>();

        public bool Shrunk { get; private set; }
        public bool Sliding { get; private set; }

        public DrawerController(Window window, FrameworkElement header, FrameworkElement root, Button button,
            UIElement shrinkGlyph, UIElement expandGlyph, params UIElement[] hideWhenParked)
        {
            _window = window; _header = header; _root = root; _button = button;
            _shrinkGlyph = shrinkGlyph; _expandGlyph = expandGlyph; _hideWhenParked = hideWhenParked;
            SetGlyph(false);
            _button.Click += (s, e) => { if (!Sliding) Toggle(); };
            _window.Closed += (s, e) => { _timer?.Stop(); _timer = null; };
        }

        public void Toggle() { if (Shrunk) Expand(); else Shrink(); }

        /// <summary>True when the key was the drawer's.</summary>
        public bool OnKey(Key key, bool ctrl, bool shift)
        {
            if (ctrl && shift && key == Key.H) { if (!Sliding) Toggle(); return true; }
            if (Shrunk)
            {
                if (key == Key.Escape || key == Key.Enter || key == Key.F11) Expand();
                return true;   // nothing inside a parked bar is typed into
            }
            return false;
        }

        public bool OnHeaderDoubleClick()
        {
            if (!Shrunk) return false;
            Expand();
            return true;
        }

        public void Shrink(bool instant = false)
        {
            if (Shrunk || Sliding) return;
            double height = _window.ActualHeight > 0 ? _window.ActualHeight : _window.Height;
            _saved = new Rect(_window.Left, _window.Top, _window.Width, height);
            _savedMinHeight = _window.MinHeight;
            _savedResize = _window.ResizeMode;

            _window.MinHeight = 0;                       // trap 2
            _window.SizeToContent = SizeToContent.Manual;
            _window.Height = height;
            _window.ResizeMode = ResizeMode.NoResize;    // trap 4

            _root.Height = _root.ActualHeight;           // trap 3
            _root.VerticalAlignment = VerticalAlignment.Top;

            _bar = _header.ActualHeight + 2;
            var target = DrawerMath.ParkedTop(ScreenHelper.WorkAreaOf(_window), _bar);
            Slide(_window.Top, target, LandedParked, instant);
        }

        void LandedParked()
        {
            _window.Height = _bar;
            _savedVisibility = new Visibility[_hideWhenParked.Length];
            for (int i = 0; i < _hideWhenParked.Length; i++)
            {
                _savedVisibility[i] = _hideWhenParked[i].Visibility;
                _hideWhenParked[i].Visibility = Visibility.Collapsed;
            }
            _root.ClearValue(FrameworkElement.HeightProperty);
            _root.VerticalAlignment = VerticalAlignment.Stretch;
            _landed = new Point(_window.Left, _window.Top);
            Shrunk = true;
            SetGlyph(true);
        }

        public void Expand(bool instant = false)
        {
            if (!Shrunk || Sliding) return;
            var area = ScreenHelper.WorkAreaOf(_window);
            var (left, top, height) = DrawerMath.ExpandRect(
                _saved, _landed, new Point(_window.Left, _window.Top), _bar, area);

            for (int i = 0; i < _hideWhenParked.Length; i++)
                _hideWhenParked[i].Visibility = _savedVisibility[i];
            _window.Left = left;
            _window.Height = height;
            Shrunk = false;
            SetGlyph(false);
            Slide(_window.Top, top, LandedOpen, instant);
        }

        void LandedOpen()
        {
            _window.MinHeight = _savedMinHeight;
            _window.ResizeMode = _savedResize;
            _window.Activate();
        }

        void Slide(double start, double end, Action done, bool instant)
        {
            Sliding = true;
            bool finished = false;

            void Finish()
            {
                if (finished) return;
                finished = true;
                _timer?.Stop(); _timer = null;
                try { _window.Top = end; } catch { }
                Sliding = false;
                try { done(); } catch { }
            }

            if (instant) { Finish(); return; }

            _clock.Restart();
            try
            {
                _timer = new DispatcherTimer(DispatcherPriority.Render) { Interval = TimeSpan.FromMilliseconds(DrawerMath.TickMs) };
                _timer.Tick += (s, e) =>
                {
                    try
                    {
                        double p = _clock.Elapsed.TotalMilliseconds / DrawerMath.DurationMs;
                        _window.Top = DrawerMath.Tween(start, end, p);
                        if (p >= 1) Finish();
                    }
                    catch { Finish(); }   // a frame that throws lands the window rather than stranding it
                };
                _timer.Start();
            }
            catch { Finish(); }
        }

        void SetGlyph(bool shrunk)
        {
            _shrinkGlyph.Visibility = shrunk ? Visibility.Collapsed : Visibility.Visible;
            _expandGlyph.Visibility = shrunk ? Visibility.Visible : Visibility.Collapsed;
            _button.ToolTip = shrunk ? "Bring the window back (Ctrl+Shift+H)" : "Shrink to the taskbar (Ctrl+Shift+H)";
        }
    }
}
