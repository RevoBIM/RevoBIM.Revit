// Port of efr_core.py's WindowDrawer (lines 2286-2515).
using System;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Animation;
using RevoBIM.Tools.ExcelForRevit;
using static RevoBIM.Tools.ExcelForRevit.Efr;
using static RevoBIM.UI.ExcelForRevit.EfrUi;

namespace RevoBIM.UI.ExcelForRevit
{
    /// <summary>
    /// Shrinks a window down to its header bar and parks it at the bottom. Driven by
    /// one button, which doubles as the state: a down arrow while the window is open,
    /// a green up arrow while it is away. Both the main window and every ThemedDialog
    /// hand one of these their own chrome, so the gesture is identical wherever it
    /// appears.
    /// </summary>
    public class WindowDrawer
    {
        public Window Window;                       // the Window being shrunk
        public FrameworkElement Header;             // the Border that stays on screen
        public FrameworkElement Root;               // the body holder, pinned during the slide
        public Button Button;                       // the arrow, repainted on every change
        public Action<bool> StateHook;              // host callback (receives Shrunk), so it can park its grips
        public bool Shrunk;
        public bool Busy;
        public (double Left, double Top, double Width, double Height)? Saved;   // before shrinking
        public (double Left, double Top)? Docked;   // where the bar was parked, to spot a drag
        public double SavedMinH;

        public WindowDrawer(Window window, FrameworkElement header, FrameworkElement root, Button button, Action<bool> stateHook = null)
        {
            Window = window;
            Header = header;
            Root = root;
            Button = button;
            StateHook = stateHook;
            Shrunk = false;
            Busy = false;
            Saved = null;
            Docked = null;
            SavedMinH = 0.0;
            PaintButton();
        }

        // -- measurement --------------------------------------------------------

        /// <summary>How tall the parked window is: the header plus the shell border.</summary>
        public double BarHeight()
        {
            double h;
            try
            {
                h = Header.ActualHeight;
            }
            catch (Exception)
            {
                h = 0.0;
            }
            if (h < 24.0)
                h = 46.0;                           // not laid out yet; a fair guess
            var shell = Window.Content as Border;
            if (shell != null)
                h += shell.BorderThickness.Top + shell.BorderThickness.Bottom;
            else
                h += 2.0;
            return h;
        }

        // -- the body -----------------------------------------------------------

        /// <summary>
        /// Freeze the body at its present size for the length of the slide. Without this
        /// the grid re-measures on every animation frame (a virtualising panel realising
        /// and dropping rows twenty times a second) and the window looks squashed rather
        /// than drawn away. Pinned, the body keeps its height and the shrinking window
        /// simply clips it.
        /// </summary>
        public void Pin()
        {
            try
            {
                Root.Height = Root.ActualHeight;
                Root.VerticalAlignment = VerticalAlignment.Top;
            }
            catch (Exception)
            {
            }
            try
            {
                var content = Window.Content as UIElement;
                if (content != null)
                    content.ClipToBounds = true;
            }
            catch (Exception)
            {
            }
        }

        public void Unpin()
        {
            try
            {
                Root.Height = double.NaN;
                Root.VerticalAlignment = VerticalAlignment.Stretch;
            }
            catch (Exception)
            {
            }
        }

        // -- the arrow ----------------------------------------------------------

        public void PaintButton()
        {
            if (Button == null)
                return;
            try
            {
                if (Shrunk)
                {
                    Button.Content = DRAWER_UP;
                    Button.Foreground = Brush(C_GREEN_HI);
                    Button.ToolTip = DRAWER_TIP_UP;
                }
                else
                {
                    Button.Content = DRAWER_DOWN;
                    Button.Foreground = Brush(C_TEXT);
                    Button.ToolTip = DRAWER_TIP_DOWN;
                }
            }
            catch (Exception)
            {
            }
        }

        public void Notify()
        {
            if (StateHook == null)
                return;
            try
            {
                StateHook(Shrunk);
            }
            catch (Exception)
            {
            }
        }

        // -- the slide ----------------------------------------------------------

        /// <summary>
        /// Animate Top and Height together, then hand the properties back. An animation
        /// holds its end value and outranks any later plain assignment, so each one is
        /// cleared the moment it finishes and the final number written straight onto
        /// the window; otherwise every resize and move from then on would be silently
        /// ignored.
        /// </summary>
        public void Slide(double top, double height, Action done = null)
        {
            Window w = Window;
            Busy = true;
            bool finished = false;

            EventHandler finish = (sender, args) =>
            {
                if (finished)
                    return;
                finished = true;
                Busy = false;
                try
                {
                    w.BeginAnimation(Window.TopProperty, null);
                    w.BeginAnimation(Window.HeightProperty, null);
                }
                catch (Exception)
                {
                }
                // a separate try, because the release above is also the path taken when
                // the animation could not start at all, and the window still has to end
                // up where it was asked to go
                try
                {
                    w.Top = top;
                    w.Height = height;
                }
                catch (Exception)
                {
                }
                if (done != null)
                {
                    try
                    {
                        done();
                    }
                    catch (Exception)
                    {
                    }
                }
            };

            try
            {
                var ease = new CubicEase();
                ease.EasingMode = EasingMode.EaseInOut;
                var span = new Duration(TimeSpan.FromMilliseconds(DRAWER_MS));

                var high = new DoubleAnimation();
                high.To = height;
                high.Duration = span;
                high.EasingFunction = ease;
                high.FillBehavior = FillBehavior.HoldEnd;
                high.Completed += finish;

                var down = new DoubleAnimation();
                down.To = top;
                down.Duration = span;
                down.EasingFunction = ease;
                down.FillBehavior = FillBehavior.HoldEnd;

                w.BeginAnimation(Window.TopProperty, down);
                w.BeginAnimation(Window.HeightProperty, high);
            }
            catch (Exception)
            {
                finish(null, null);                 // no animation beats no drawer
            }
        }

        // -- the two directions -------------------------------------------------

        public void Shrink()
        {
            if (Shrunk || Busy)
                return;
            Window w = Window;
            try
            {
                Saved = (w.Left, w.Top, w.ActualWidth, w.ActualHeight);
                SavedMinH = w.MinHeight;
            }
            catch (Exception)
            {
                return;
            }
            double bar = BarHeight();
            var area = ScreenWorkArea(w);
            double target = DrawerParkTop(area.Top, area.Height, bar);
            try
            {
                // SizeToContent and MinHeight both veto a Height animation, and a vetoed
                // one leaves the window half shut. Both come off before the body is
                // pinned, so the pin cannot trigger a re-measure that SizeToContent
                // would then act on.
                w.SizeToContent = SizeToContent.Manual;
                w.MinHeight = 0;
            }
            catch (Exception)
            {
            }
            Pin();
            Shrunk = true;
            PaintButton();
            Notify();
            Slide(target, bar, Parked);
        }

        public void Parked()
        {
            try
            {
                Docked = (Window.Left, Window.Top);
            }
            catch (Exception)
            {
                Docked = null;
            }
        }

        public void Expand()
        {
            if (!Shrunk || Busy)
                return;
            Window w = Window;
            double left, top, width, height;
            if (Saved == null)
            {
                left = w.Left;
                top = w.Top;
                width = w.ActualWidth;
                height = 480.0;
            }
            else
            {
                left = Saved.Value.Left;
                top = Saved.Value.Top;
                width = Saved.Value.Width;
                height = Saved.Value.Height;
            }
            bool moved;
            try
            {
                moved = DrawerMoved(w.Left, w.Top, Docked);
            }
            catch (Exception)
            {
                moved = false;
            }
            var area = ScreenWorkArea(w);
            double target;
            try
            {
                target = DrawerOpenTop(w.Top, w.ActualHeight, height, area.Top, top, moved);
            }
            catch (Exception)
            {
                target = top;
            }
            if (!moved)
            {
                try
                {
                    w.Left = left;
                }
                catch (Exception)
                {
                }
            }
            Shrunk = false;
            PaintButton();
            Notify();
            Slide(target, height, Opened);
        }

        public void Opened()
        {
            try
            {
                Window.MinHeight = SavedMinH;
            }
            catch (Exception)
            {
            }
            Unpin();
            Docked = null;
        }

        /// <summary>Click handler for the arrow button; also callable as Toggle().</summary>
        public void Toggle(object sender = null, EventArgs args = null)
        {
            if (Busy)
                return;
            if (Shrunk)
                Expand();
            else
                Shrink();
        }
    }
}
