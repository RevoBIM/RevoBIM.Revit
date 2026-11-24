using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Interop;
using System.Windows.Media;
using System.Windows.Threading;

using Button = System.Windows.Controls.Button;
using Panel = System.Windows.Controls.Panel;

namespace RevoBIM.UI.FamilyFindReplace
{
    /// <summary>
    /// Shrink to taskbar, for every window the tool opens (main, adjust, prompt). The shrink button slides the
    /// window down to the bottom of its screen like a drawer closing, leaving only its header bar clear of the
    /// taskbar; the button turns into a green up arrow that opens it again. Ctrl+Shift+H does the same from the
    /// keyboard. A dialog takes its owner down with it, and a window takes its open dialogs down with it; bringing
    /// either back brings both. Port of ffr_drawer.py.
    /// </summary>
    internal sealed class FfrDrawer
    {
        private const double SlideSeconds = 0.28;
        private const int TickMs = 15;
        private const double ParkMargin = 8.0;
        private const double ParkGap = 4.0;
        private const double MovedTol = 2.0;
        private const string ShrunkTag = "shrunk";
        private const string TipShrink = "Shrink to the taskbar so Revit can be seen  (Ctrl+Shift+H)";
        private const string TipExpand = "Open the window again  (Ctrl+Shift+H, Enter or Esc)";

        private enum DrawerState { Open, Closing, Shrunk, Opening, Closed }

        /// <summary>Every live drawer, so a dialog can find its owner's.</summary>
        private static readonly List<FfrDrawer> All = new List<FfrDrawer>();

        /// <summary>Drawers parked at the bottom of the screen, lowest first.</summary>
        private static readonly List<FfrDrawer> Parked = new List<FfrDrawer>();

        private readonly Window window;
        private readonly Border header;
        private readonly Panel root;
        private readonly Button button;
        private readonly Func<bool> canToggle;

        private DrawerState state = DrawerState.Open;
        private double[] saved;               // left, top, width, height
        private double parkedLeft, parkedTop;
        private double bar;
        private FfrDrawer lifted;             // the owner's drawer this one took down
        private List<FfrDrawer> carried = new List<FfrDrawer>();
        private readonly Dictionary<string, object> kept = new Dictionary<string, object>();
        private List<KeyValuePair<UIElement, Visibility>> hidden = new List<KeyValuePair<UIElement, Visibility>>();
        private DispatcherTimer timer;
        private double[] anim;                // top0, height0, top1, height1
        private Action animDone;
        private readonly Stopwatch clock = new Stopwatch();

        public FfrDrawer(Window window, Border header, Panel root, Button button, Func<bool> canToggle = null)
        {
            this.window = window;
            this.header = header;
            this.root = root;
            this.button = button;
            this.canToggle = canToggle;
            All.Add(this);
            try
            {
                button.Click += (s, a) => { if (Allowed()) Toggle(); };
            }
            catch (Exception)
            {
            }
            window.PreviewKeyDown += OnKey;
            window.Closed += OnClosed;
            Paint(false);
        }

        public bool IsOpen { get { return state == DrawerState.Open; } }
        public bool IsShrunk { get { return state == DrawerState.Shrunk; } }

        public bool Toggle()
        {
            if (state == DrawerState.Open) return Shrink(true, true);
            if (state == DrawerState.Shrunk) return Expand(true);
            return false;
        }

        /// <summary>
        /// Call first from the header's MouseLeftButtonDown. True when the drawer has dealt with the click: a
        /// double click on a parked bar opens it. Anything else is left to the caller, which drags the window.
        /// </summary>
        public bool OnHeaderDown(MouseButtonEventArgs args)
        {
            if (state != DrawerState.Shrunk) return false;
            if (args.ClickCount < 2) return false;
            Expand(true);
            args.Handled = true;
            return true;
        }

        private bool Allowed()
        {
            if (canToggle == null) return true;
            try
            {
                return canToggle();
            }
            catch (Exception)
            {
                return true;
            }
        }

        private void OnKey(object sender, KeyEventArgs args)
        {
            ModifierKeys mods = Keyboard.Modifiers;
            const ModifierKeys both = ModifierKeys.Control | ModifierKeys.Shift;
            if (args.Key == Key.H && (mods & both) == both)
            {
                if (Allowed()) Toggle();
                args.Handled = true;
                return;
            }
            if (state == DrawerState.Closing || state == DrawerState.Shrunk || state == DrawerState.Opening)
            {
                // parked, the keys that would answer or close a window open it instead: a window nobody can see must not be answered blind
                if (args.Key == Key.Escape || args.Key == Key.Return)
                {
                    if (state == DrawerState.Shrunk) Expand(true);
                    args.Handled = true;
                }
            }
        }

        // ---- the arithmetic ---------------------------------------------------------------------------

        private static double EaseOut(double progress)
        {
            if (progress <= 0.0) return 0.0;
            if (progress >= 1.0) return 1.0;
            return 1.0 - Math.Pow(1.0 - progress, 3);
        }

        private static double Lerp(double start, double end, double fraction) { return start + (end - start) * fraction; }

        private static double ClampLeft(double left, double width, double areaLeft, double areaRight)
        {
            if (left + width > areaRight) left = areaRight - width;
            if (left < areaLeft) left = areaLeft;
            return left;
        }

        /// <summary>Clamped to the area's own top, never to zero: on a second monitor above the primary one the working area's top is negative.</summary>
        private static double ClampTop(double top, double height, double areaTop, double areaBottom)
        {
            if (top + height > areaBottom) top = areaBottom - height;
            if (top < areaTop) top = areaTop;
            return top;
        }

        /// <summary>
        /// (left, top) to reopen a parked window to. Left where it landed, it goes back where it came from.
        /// Carried somewhere else, it opens upward from where the bar now sits and is kept on that screen.
        /// </summary>
        private void ReopenFrame(double nowLeft, double nowTop, double[] area, out double left, out double top)
        {
            left = saved[0];
            top = saved[1];
            bool moved = Math.Abs(nowLeft - parkedLeft) > MovedTol || Math.Abs(nowTop - parkedTop) > MovedTol;
            if (!moved) return;
            double bottom = nowTop + bar;
            top = ClampTop(bottom - saved[3], saved[3], area[1], area[3]);
            left = ClampLeft(nowLeft, saved[2], area[0], area[2]);
        }

        /// <summary>(left, top, right, bottom) of the working area of the window's screen, in WPF units.</summary>
        private double[] WorkArea()
        {
            try
            {
                IntPtr handle = new WindowInteropHelper(window).Handle;
                System.Drawing.Rectangle rect = System.Windows.Forms.Screen.FromHandle(handle).WorkingArea;
                double sx = 1.0, sy = 1.0;
                PresentationSource source = PresentationSource.FromVisual(window);
                if (source != null && source.CompositionTarget != null)
                {
                    Matrix m = source.CompositionTarget.TransformToDevice;
                    if (m.M11 != 0) sx = m.M11;
                    if (m.M22 != 0) sy = m.M22;
                }
                return new[] { rect.Left / sx, rect.Top / sy, rect.Right / sx, rect.Bottom / sy };
            }
            catch (Exception)
            {
            }
            try
            {
                Rect area = SystemParameters.WorkArea;
                return new[] { area.Left, area.Top, area.Right, area.Bottom };
            }
            catch (Exception)
            {
                return new[] { 0.0, 0.0, 1920.0, 1040.0 };
            }
        }

        // ---- down -------------------------------------------------------------------------------------

        public bool Shrink(bool animate, bool lift)
        {
            if (state != DrawerState.Open) return false;
            state = DrawerState.Closing;

            if (lift)
            {
                FfrDrawer owner = OwnerDrawer();
                if (owner != null && owner.state == DrawerState.Open && owner.Shrink(false, true)) lifted = owner;
            }

            double left, top, width, height;
            try
            {
                left = window.Left;
                top = window.Top;
                width = window.ActualWidth;
                height = window.ActualHeight;
            }
            catch (Exception)
            {
                state = DrawerState.Open;
                return false;
            }
            saved = new[] { left, top, width, height };
            bar = BarHeight();
            double[] area = WorkArea();
            double below = Parked.Where(d => d != this).Sum(d => d.bar + ParkGap);
            double targetTop = area[3] - ParkMargin - below - bar;
            double targetLeft = ClampLeft(left, width, area[0], area[2]);
            parkedLeft = targetLeft;
            parkedTop = targetTop;
            Parked.Add(this);

            Relax();
            Pin();
            try
            {
                window.Left = targetLeft;
            }
            catch (Exception)
            {
            }
            Slide(top, height, targetTop, bar, Landed, animate);

            // open dialogs go down with it, stacked above
            foreach (FfrDrawer child in Children())
            {
                if (child.state == DrawerState.Open && child.Shrink(false, false)) carried.Add(child);
            }
            return true;
        }

        private void Landed()
        {
            // the body is hidden only now: hidden at the start, the slide would be a bar sliding rather than a drawer closing
            hidden = new List<KeyValuePair<UIElement, Visibility>>();
            foreach (UIElement element in Siblings())
            {
                try
                {
                    hidden.Add(new KeyValuePair<UIElement, Visibility>(element, element.Visibility));
                    element.Visibility = Visibility.Collapsed;
                }
                catch (Exception)
                {
                }
            }
            try
            {
                CornerRadius corner = header.CornerRadius;
                kept["corner"] = corner;
                header.CornerRadius = new CornerRadius(Math.Max(corner.TopLeft, corner.TopRight));
            }
            catch (Exception)
            {
            }
            try
            {
                kept["resize"] = window.ResizeMode;
                window.ResizeMode = ResizeMode.NoResize;
            }
            catch (Exception)
            {
            }
            state = DrawerState.Shrunk;
            Paint(true);
        }

        // ---- up ---------------------------------------------------------------------------------------

        public bool Expand(bool animate)
        {
            if (state != DrawerState.Shrunk) return false;
            state = DrawerState.Opening;
            Parked.Remove(this);

            // the owner comes back first, so it is behind the dialog as it rises
            FfrDrawer owner = OwnerDrawer();
            if (owner != null && owner.state == DrawerState.Shrunk) owner.Expand(false);
            lifted = null;

            foreach (KeyValuePair<UIElement, Visibility> entry in hidden)
            {
                try
                {
                    entry.Key.Visibility = entry.Value;
                }
                catch (Exception)
                {
                }
            }
            hidden = new List<KeyValuePair<UIElement, Visibility>>();
            if (kept.ContainsKey("corner"))
            {
                try
                {
                    header.CornerRadius = (CornerRadius)kept["corner"];
                }
                catch (Exception)
                {
                }
                kept.Remove("corner");
            }
            if (kept.ContainsKey("resize"))
            {
                try
                {
                    window.ResizeMode = (ResizeMode)kept["resize"];
                }
                catch (Exception)
                {
                }
                kept.Remove("resize");
            }
            Paint(false);

            double nowLeft = parkedLeft, nowTop = parkedTop;
            try
            {
                nowLeft = window.Left;
                nowTop = window.Top;
            }
            catch (Exception)
            {
            }
            double left, top;
            ReopenFrame(nowLeft, nowTop, WorkArea(), out left, out top);
            try
            {
                window.Left = left;
            }
            catch (Exception)
            {
            }
            Slide(nowTop, bar, top, saved[3], Opened, animate);

            // dialogs that went down with this window, or took it down, come back
            foreach (FfrDrawer child in Children())
            {
                if (child.state == DrawerState.Shrunk && (carried.Contains(child) || child.lifted == this)) child.Expand(false);
            }
            carried = new List<FfrDrawer>();
            return true;
        }

        private void Opened()
        {
            Unpin();
            Restore();
            state = DrawerState.Open;
            try
            {
                window.Activate();
            }
            catch (Exception)
            {
            }
        }

        // ---- what the slide has to relax --------------------------------------------------------------

        /// <summary>MinHeight and SizeToContent both veto a Height change, and a vetoed slide leaves the window half shut.</summary>
        private void Relax()
        {
            try
            {
                kept["min"] = window.MinHeight;
                window.MinHeight = 0.0;
            }
            catch (Exception)
            {
            }
            try
            {
                kept["size"] = window.SizeToContent;
                window.SizeToContent = SizeToContent.Manual;
            }
            catch (Exception)
            {
            }
            Release();
        }

        private void Restore()
        {
            if (kept.ContainsKey("min"))
            {
                try
                {
                    window.MinHeight = (double)kept["min"];
                }
                catch (Exception)
                {
                }
                kept.Remove("min");
            }
            if (kept.ContainsKey("size"))
            {
                try
                {
                    window.SizeToContent = (SizeToContent)kept["size"];
                }
                catch (Exception)
                {
                }
                kept.Remove("size");
            }
        }

        /// <summary>Hold the body at its full height while the window shrinks round it, or it reads as a window being squashed.</summary>
        private void Pin()
        {
            try
            {
                kept["root_height"] = root.Height;
                kept["root_align"] = root.VerticalAlignment;
                root.Height = root.ActualHeight;
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
                root.Height = kept.ContainsKey("root_height") ? (double)kept["root_height"] : double.NaN;
            }
            catch (Exception)
            {
            }
            try
            {
                root.VerticalAlignment = kept.ContainsKey("root_align") ? (VerticalAlignment)kept["root_align"] : VerticalAlignment.Stretch;
            }
            catch (Exception)
            {
            }
            kept.Remove("root_height");
            kept.Remove("root_align");
        }

        /// <summary>Let go of anything animating Top or Height: an animation outranks every later plain assignment.</summary>
        private void Release()
        {
            try
            {
                window.BeginAnimation(Window.TopProperty, null);
            }
            catch (Exception)
            {
            }
            try
            {
                window.BeginAnimation(Window.HeightProperty, null);
            }
            catch (Exception)
            {
            }
        }

        // ---- the slide --------------------------------------------------------------------------------

        /// <summary>Ease Top and Height together on a DispatcherTimer (a Storyboard on a borderless window fights the layout pass).</summary>
        private void Slide(double top0, double height0, double top1, double height1, Action done, bool animate)
        {
            StopTimer();
            anim = new[] { top0, height0, top1, height1 };
            animDone = done;
            clock.Restart();
            if (!animate)
            {
                Finish();
                return;
            }
            try
            {
                timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(TickMs) };
                timer.Tick += OnTick;
                timer.Start();
            }
            catch (Exception)
            {
                Finish();
            }
        }

        private void OnTick(object sender, EventArgs args)
        {
            if (anim == null)
            {
                StopTimer();
                return;
            }
            try
            {
                double progress = clock.Elapsed.TotalSeconds / SlideSeconds;
                if (progress >= 1.0)
                {
                    Finish();
                    return;
                }
                double eased = EaseOut(progress);
                window.Top = Lerp(anim[0], anim[2], eased);
                window.Height = Math.Max(1.0, Lerp(anim[1], anim[3], eased));
            }
            catch (Exception)
            {
                // a frame that throws lands the window at the end, rather than leaving it half way with the timer running
                Finish();
            }
        }

        private void Finish()
        {
            StopTimer();
            double[] last = anim;
            Action done = animDone;
            anim = null;
            animDone = null;
            if (last == null) return;
            Release();
            try
            {
                window.Top = last[2];
            }
            catch (Exception)
            {
            }
            try
            {
                window.Height = last[3];
            }
            catch (Exception)
            {
            }
            try
            {
                if (done != null) done();
            }
            catch (Exception)
            {
            }
        }

        private void StopTimer()
        {
            DispatcherTimer local = timer;
            timer = null;
            if (local == null) return;
            try
            {
                local.Stop();
                local.Tick -= OnTick;
            }
            catch (Exception)
            {
            }
        }

        // ---- bits -------------------------------------------------------------------------------------

        private void OnClosed(object sender, EventArgs args)
        {
            StopTimer();
            anim = null;
            Parked.Remove(this);
            All.Remove(this);
            FfrDrawer lift = lifted;
            lifted = null;
            state = DrawerState.Closed;
            // closing a dialog that took its owner down brings the owner back
            if (lift != null && lift.state == DrawerState.Shrunk) lift.Expand(true);
        }

        private void Paint(bool shrunk)
        {
            try
            {
                button.Tag = shrunk ? ShrunkTag : "";
            }
            catch (Exception)
            {
            }
            try
            {
                button.ToolTip = shrunk ? TipExpand : TipShrink;
            }
            catch (Exception)
            {
            }
        }

        /// <summary>The parked bar: the header, plus the window's edge above and below it.</summary>
        private double BarHeight()
        {
            double offset = 1.0, height = 40.0;
            try
            {
                offset = header.TranslatePoint(new Point(0.0, 0.0), window).Y;
            }
            catch (Exception)
            {
            }
            try
            {
                height = header.ActualHeight;
            }
            catch (Exception)
            {
            }
            return height + 2.0 * offset;
        }

        private List<UIElement> Siblings()
        {
            var found = new List<UIElement>();
            try
            {
                foreach (UIElement child in root.Children)
                    if (!ReferenceEquals(child, header)) found.Add(child);
            }
            catch (Exception)
            {
            }
            return found;
        }

        private FfrDrawer OwnerDrawer()
        {
            Window owner;
            try
            {
                owner = window.Owner;
            }
            catch (Exception)
            {
                return null;
            }
            return owner == null ? null : All.FirstOrDefault(d => ReferenceEquals(d.window, owner));
        }

        private List<FfrDrawer> Children()
        {
            return All.Where(d => d != this && ReferenceEquals(OwnerOf(d), window)).ToList();
        }

        private static Window OwnerOf(FfrDrawer drawer)
        {
            try
            {
                return drawer.window.Owner;
            }
            catch (Exception)
            {
                return null;
            }
        }
    }
}
