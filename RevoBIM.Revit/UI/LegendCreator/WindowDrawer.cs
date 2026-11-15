using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Interop;
using System.Windows.Threading;
using static RevoBIM.Tools.LegendCreator.LgcCore;
using static RevoBIM.Tools.LegendCreator.LgcLogic;

namespace RevoBIM.UI.LegendCreator
{
    /// <summary>
    /// The house drawer: slides a window down to the bottom of its screen,
    /// leaving its header bar floating clear of the taskbar, and back. Top and
    /// Height are eased together on a short DispatcherTimer rather than a
    /// Storyboard, which on a borderless window fights the layout pass.
    /// Port of lgc_drawer.py.
    /// </summary>
    public sealed class WindowDrawer
    {
        public const double DrawerSeconds = 0.28;
        public const int DrawerTickMs = 15;
        public const double DrawerMargin = 8.0; // px between a parked bar and the taskbar
        public const double DrawerGap = 4.0;    // px between bars parked one above another
        public const string Shrunk = "shrunk";  // the button's Tag while parked - the style swaps its glyph
        public const string ShrinkTip = "Shrink to the taskbar (Ctrl+Shift+H)";
        public const string ExpandTip = "Open the window again (Ctrl+Shift+H, Enter or double-click)";

        private static readonly List<WindowDrawer> Parked = new List<WindowDrawer>();

        private readonly Window window;
        private readonly Border header;
        private readonly Button button;
        private readonly Border root;
        private readonly bool enabled;

        public bool IsParked { get; private set; }
        public bool Sliding { get; private set; }

        private int? slot;
        private (double Left, double Top) parkedAt;
        private SavedState saved;
        private List<(UIElement Child, Visibility Was)> hidden = new List<(UIElement, Visibility)>();
        private DispatcherTimer timer;
        private Action done;
        private (double Top, double Height) from, to;
        private DateTime t0;

        private sealed class SavedState
        {
            public double Left, Top, Height, MinHeight, RootHeight, RootFull, Bar;
            public SizeToContent SizeToContent;
            public VerticalAlignment RootAlign;
            public CornerRadius Corner;
        }

        /// <summary>A drawer for a window, or an inert one (button hidden) if it cannot be built.</summary>
        public WindowDrawer(Window window, Border header, Button button)
        {
            this.window = window;
            this.header = header;
            this.button = button;
            try
            {
                root = (Border)window.Content;
                Label();
                window.PreviewKeyDown += OnKey;
                window.Closed += OnClosed;
                enabled = true;
            }
            catch (Exception err)
            {
                Swallowed(err);
                try
                {
                    button.Visibility = Visibility.Collapsed;
                }
                catch (Exception inner)
                {
                    Swallowed(inner);
                }
            }
        }

        // -- pure maths --------------------------------------------------------
        /// <summary>Ease-out cubic, clamped to 0..1: quick away, gentle landing.</summary>
        public static double EaseOut(double progress)
        {
            if (progress <= 0.0) return 0.0;
            if (progress >= 1.0) return 1.0;
            return 1.0 - Math.Pow(1.0 - progress, 3);
        }

        /// <summary>The lowest slot no parked bar is using.</summary>
        public static int FreeSlot(ICollection<int> taken)
        {
            int s = 0;
            while (taken.Contains(s)) s++;
            return s;
        }

        /// <summary>Top edge of a parked bar, stacked above any bars already parked there.</summary>
        public static double ParkedTop(double areaTop, double areaHeight, double bar, int slot)
        {
            return areaTop + areaHeight - DrawerMargin - bar - slot * (bar + DrawerGap);
        }

        /// <summary>(left, top, height) to open a parked window back to.</summary>
        public static (double Left, double Top, double Height) ReopenRect(
            double savedLeft, double savedTop, double savedHeight, double barLeft, double barTop, double bar,
            bool moved, double areaTop, double areaHeight)
        {
            if (!moved) return (savedLeft, savedTop, savedHeight);
            double height = Math.Min(savedHeight, areaHeight);
            double top = barTop + bar - height;
            top = Math.Max(areaTop, Math.Min(top, areaTop + areaHeight - height));
            return (barLeft, top, height);
        }

        /// <summary>The working area of the window's own screen, in WPF units.</summary>
        private static Rect ScreenWorkArea(Window window)
        {
            try
            {
                IntPtr handle = new WindowInteropHelper(window).Handle;
                var area = System.Windows.Forms.Screen.FromHandle(handle).WorkingArea;
                var scale = PresentationSource.FromVisual(window).CompositionTarget.TransformFromDevice;
                return new Rect(area.Left * scale.M11, area.Top * scale.M22,
                                area.Width * scale.M11, area.Height * scale.M22);
            }
            catch (Exception err)
            {
                Swallowed(err);
            }
            return SystemParameters.WorkArea;
        }

        // -- the gestures ------------------------------------------------------
        public void Toggle()
        {
            if (!enabled || Sliding) return;
            if (IsParked) Expand();
            else Shrink();
        }

        /// <summary>True when a header click belonged to the drawer: a double click on a parked bar opens it.</summary>
        public bool HeaderDown(MouseButtonEventArgs args)
        {
            if (IsParked && args.ClickCount >= 2)
            {
                Expand();
                return true;
            }
            return false;
        }

        /// <summary>For default and cancel buttons: while parked, Enter or Escape reopens the window.</summary>
        public bool Intercept()
        {
            if (IsParked)
            {
                Expand();
                return true;
            }
            return Sliding;
        }

        // -- shrinking ---------------------------------------------------------
        private void Shrink()
        {
            if (IsParked || Sliding) return;
            double height = window.ActualHeight > 0 ? window.ActualHeight : window.Height;
            Thickness edge = root.BorderThickness;
            double bar = header.ActualHeight + edge.Top + edge.Bottom;
            Rect area = ScreenWorkArea(window);
            int s = FreeSlot(Parked.Where(d => d != this && d.slot.HasValue).Select(d => d.slot.Value).ToList());
            slot = s;
            double target = ParkedTop(area.Top, area.Height, bar, s);

            saved = new SavedState
            {
                Left = window.Left, Top = window.Top, Height = height,
                MinHeight = window.MinHeight, SizeToContent = window.SizeToContent,
                RootHeight = root.Height, RootAlign = root.VerticalAlignment,
                RootFull = root.ActualHeight, Corner = header.CornerRadius, Bar = bar,
            };
            // MinHeight and SizeToContent both veto a shrinking Height.
            window.SizeToContent = SizeToContent.Manual;
            window.MinHeight = 0;
            // Pin the body at its full height so it is drawn away under the header.
            root.Height = saved.RootFull;
            root.VerticalAlignment = VerticalAlignment.Top;
            parkedAt = (window.Left, target);
            Log(string.Format(Inv, "drawer: shrinking {0:F0}px high to a {1:F0}px bar at top {2:F0} (slot {3})",
                              height, bar, target, s));
            Slide(window.Top, height, target, bar, Landed);
        }

        private void Landed()
        {
            // Only now is the body put away - resize grips with it.
            hidden = new List<(UIElement, Visibility)>();
            if (header.Parent is Panel panel)
            {
                foreach (UIElement child in panel.Children.Cast<UIElement>().ToList())
                {
                    if (ReferenceEquals(child, header)) continue;
                    hidden.Add((child, child.Visibility));
                    child.Visibility = Visibility.Collapsed;
                }
            }
            root.Height = double.NaN;
            header.CornerRadius = new CornerRadius(5);
            IsParked = true;
            if (!Parked.Contains(this)) Parked.Add(this);
            Label();
        }

        // -- opening -----------------------------------------------------------
        private void Expand()
        {
            if (!IsParked || Sliding) return;
            bool moved = Math.Abs(window.Left - parkedAt.Left) > 1.0 || Math.Abs(window.Top - parkedAt.Top) > 1.0;
            Rect area = ScreenWorkArea(window);
            var (left, top, height) = ReopenRect(saved.Left, saved.Top, saved.Height, window.Left, window.Top,
                                                 saved.Bar, moved, area.Top, area.Height);

            // Body back before the slide, previous visibility and all.
            foreach (var (child, was) in hidden) child.Visibility = was;
            hidden = new List<(UIElement, Visibility)>();
            header.CornerRadius = saved.Corner;
            root.Height = saved.RootFull;
            root.VerticalAlignment = VerticalAlignment.Top;
            IsParked = false;
            Parked.Remove(this);
            Label();

            window.Left = left;
            Log(string.Format(Inv, "drawer: opening to top {0:F0}, {1:F0}px high{2}",
                              top, height, moved ? " (bar was moved)" : ""));
            Slide(window.Top, saved.Bar, top, height, Opened);
        }

        private void Opened()
        {
            root.Height = saved.RootHeight;
            root.VerticalAlignment = saved.RootAlign;
            window.MinHeight = saved.MinHeight;
            window.SizeToContent = saved.SizeToContent;
            saved = null;
            try
            {
                window.Activate();
            }
            catch (Exception err)
            {
                Swallowed(err);
            }
        }

        // -- the slide ---------------------------------------------------------
        private void Slide(double top0, double height0, double top1, double height1, Action whenDone)
        {
            Sliding = true;
            from = (top0, height0);
            to = (top1, height1);
            done = whenDone;
            t0 = DateTime.UtcNow;
            try
            {
                timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(DrawerTickMs) };
                timer.Tick += Tick;
                timer.Start();
            }
            catch (Exception err)
            {
                Swallowed(err);
                Finish(); // no timer: land at the end state now
            }
        }

        private void Tick(object sender, EventArgs args)
        {
            if (!Sliding) return;
            try
            {
                double progress = EaseOut((DateTime.UtcNow - t0).TotalSeconds / DrawerSeconds);
                window.Top = from.Top + (to.Top - from.Top) * progress;
                window.Height = from.Height + (to.Height - from.Height) * progress;
                if (progress >= 1.0) Finish();
            }
            catch (Exception err)
            {
                Swallowed(err);
                Finish(); // a frame that throws lands at the end
            }
        }

        /// <summary>Stop the timer and write the end state straight onto the window.</summary>
        private void Finish()
        {
            DispatcherTimer running = timer;
            timer = null;
            if (running != null)
            {
                try
                {
                    running.Stop();
                }
                catch (Exception err)
                {
                    Swallowed(err);
                }
            }
            try
            {
                window.Top = to.Top;
                window.Height = to.Height;
            }
            catch (Exception err)
            {
                Swallowed(err);
            }
            Sliding = false;
            Action next = done;
            done = null;
            try
            {
                next?.Invoke();
            }
            catch (Exception err)
            {
                Swallowed(err);
            }
        }

        // -- housekeeping ------------------------------------------------------
        private void Label()
        {
            try
            {
                button.Tag = IsParked ? Shrunk : null;
                button.ToolTip = IsParked ? ExpandTip : ShrinkTip;
            }
            catch (Exception err)
            {
                Swallowed(err);
            }
        }

        private void OnKey(object sender, KeyEventArgs args)
        {
            try
            {
                bool ctrlShift = (Keyboard.Modifiers & (ModifierKeys.Control | ModifierKeys.Shift))
                                 == (ModifierKeys.Control | ModifierKeys.Shift);
                if (args.Key == Key.H && ctrlShift)
                {
                    Toggle();
                    args.Handled = true;
                }
                else if (IsParked && (args.Key == Key.Return || args.Key == Key.Escape))
                {
                    Expand();
                    args.Handled = true;
                }
            }
            catch (Exception err)
            {
                Swallowed(err);
            }
        }

        private void OnClosed(object sender, EventArgs args)
        {
            DispatcherTimer running = timer;
            timer = null;
            try
            {
                running?.Stop();
            }
            catch (Exception err)
            {
                Swallowed(err);
            }
            Parked.Remove(this);
        }
    }
}
