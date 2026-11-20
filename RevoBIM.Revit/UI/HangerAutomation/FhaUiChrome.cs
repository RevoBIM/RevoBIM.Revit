using System;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using RevoBIM.Tools.HangerAutomation;

namespace RevoBIM.UI.HangerAutomation
{
    /// <summary>
    /// Resize grips, dragging and full screen for a borderless window. Port of fha_ui.Chrome.
    ///
    /// A borderless AllowsTransparency window cannot be resized by WPF, so it carries eight Thumb strips. Full screen
    /// is by bounds (the working area of the screen the window is on), never WindowState.Maximized.
    /// </summary>
    public sealed class FhaChrome
    {
        public const double Grip = 5.0;

        private struct Bounds
        {
            public double Left, Top, Width, Height;
        }

        public readonly Window Win;
        /// <summary>True while the window is full screen (Python <c>chrome.full</c>).</summary>
        public bool Full;
        private Bounds? saved;

        public FhaChrome(Window win)
        {
            Win = win;
            Full = false;
        }

        // ---- grips
        /// <summary>Adds the eight Thumb strips to <paramref name="layer"/> (the XAML's GripLayer grid).</summary>
        public void AddGrips(Panel layer)
        {
            HorizontalAlignment L = HorizontalAlignment.Left, R = HorizontalAlignment.Right, S = HorizontalAlignment.Stretch;
            VerticalAlignment T = VerticalAlignment.Top, B = VerticalAlignment.Bottom, V = VerticalAlignment.Stretch;
            var specs = new[]
            {
                new GripSpec(L, V, Cursors.SizeWE, -1, 0), new GripSpec(R, V, Cursors.SizeWE, 1, 0),
                new GripSpec(S, T, Cursors.SizeNS, 0, -1), new GripSpec(S, B, Cursors.SizeNS, 0, 1),
                new GripSpec(L, T, Cursors.SizeNWSE, -1, -1), new GripSpec(R, T, Cursors.SizeNESW, 1, -1),
                new GripSpec(L, B, Cursors.SizeNESW, -1, 1), new GripSpec(R, B, Cursors.SizeNWSE, 1, 1),
            };
            foreach (GripSpec sp in specs)
            {
                var t = new Thumb();
                t.Cursor = sp.Cursor;
                t.HorizontalAlignment = sp.H;
                t.VerticalAlignment = sp.V;
                t.Opacity = 0.0;
                bool corner = sp.H != S && sp.V != V;
                t.Width = corner ? Grip * 2 : (sp.H != S ? Grip : double.NaN);
                t.Height = corner ? Grip * 2 : (sp.V != V ? Grip : double.NaN);
                t.DragDelta += Resizer(sp.Sx, sp.Sy);
                layer.Children.Add(t);
            }
        }

        private sealed class GripSpec
        {
            public readonly HorizontalAlignment H;
            public readonly VerticalAlignment V;
            public readonly Cursor Cursor;
            public readonly int Sx, Sy;

            public GripSpec(HorizontalAlignment h, VerticalAlignment v, Cursor cursor, int sx, int sy)
            {
                H = h; V = v; Cursor = cursor; Sx = sx; Sy = sy;
            }
        }

        private DragDeltaEventHandler Resizer(int sx, int sy)
        {
            return (sender, e) =>
            {
                try
                {
                    Window win = Win;
                    Full = false;
                    double dx = e.HorizontalChange, dy = e.VerticalChange;
                    if (sx != 0)
                    {
                        double w = win.Width + sx * dx;
                        if (w >= win.MinWidth)
                        {
                            if (sx < 0) win.Left = win.Left + dx;
                            win.Width = w;
                        }
                    }
                    if (sy != 0)
                    {
                        double h = win.Height + sy * dy;
                        if (h >= win.MinHeight)
                        {
                            if (sy < 0) win.Top = win.Top + dy;
                            win.Height = h;
                        }
                    }
                }
                catch (Exception)
                {
                }
            };
        }

        // ---- dragging by the header
        /// <summary>Header MouseLeftButtonDown: double-click = full screen, otherwise drag. <paramref name="logo"/> is skipped.</summary>
        public void HeaderDown(MouseButtonEventArgs e, object logo = null)
        {
            try
            {
                if (logo != null && ReferenceEquals(e.OriginalSource, logo)) return;   // the logo belongs to the easter egg: never drag or full screen
                if (e.ClickCount == 2)
                {
                    ToggleFull();
                    return;
                }
                if (Full) LeaveFullUnderMouse(e);
                Win.DragMove();
            }
            catch (Exception)
            {
            }
        }

        // ---- full screen
        private void Dpi(out double sx, out double sy)
        {
            try
            {
                var m = PresentationSource.FromVisual(Win).CompositionTarget.TransformToDevice;
                sx = m.M11;
                sy = m.M22;
            }
            catch (Exception)
            {
                sx = 1.0;
                sy = 1.0;
            }
        }

        /// <summary>The working area of the screen the window is on, in WPF units (Python returned (left, top, width, height)).</summary>
        public Rect WorkArea()
        {
            Window win = Win;
            double sx, sy;
            Dpi(out sx, out sy);
            try
            {
                int cx = (int)((win.Left + win.ActualWidth / 2.0) * sx);
                int cy = (int)((win.Top + 20.0) * sy);
                System.Drawing.Rectangle wa = System.Windows.Forms.Screen.FromPoint(new System.Drawing.Point(cx, cy)).WorkingArea;
                return new Rect(wa.X / sx, wa.Y / sy, wa.Width / sx, wa.Height / sy);
            }
            catch (Exception)
            {
                return SystemParameters.WorkArea;
            }
        }

        /// <summary>
        /// Size the window so the tab in <paramref name="scroller"/> shows every tool without scrolling - up to the
        /// height of the screen, where it scrolls instead.
        /// </summary>
        public void FitTo(ScrollViewer scroller, bool growOnly = false)
        {
            if (Full || scroller == null) return;
            try
            {
                Window win = Win;
                if (win.ActualHeight <= 0) return;   // not on screen yet: ContentRendered fits it
                win.UpdateLayout();
                var content = (UIElement)scroller.Content;
                content.Measure(new Size(Math.Max(scroller.ActualWidth, 100.0), double.PositiveInfinity));
                double want = content.DesiredSize.Height;
                double have = scroller.ViewportHeight != 0.0 ? scroller.ViewportHeight : scroller.ActualHeight;
                if (want <= 0 || Math.Abs(want - have) < 1.0 || (growOnly && want <= have)) return;
                Rect wa = WorkArea();
                double h, top;
                FhaCore.FitHeight(win.ActualHeight != 0.0 ? win.ActualHeight : win.Height, have, want,
                                  win.MinHeight, win.Top, wa.Top, wa.Height * FhaUi.MaxScreen, out h, out top);
                win.Height = h;
                win.Top = top;
            }
            catch (Exception)
            {
            }
        }

        /// <summary>
        /// The window changed height while full screen (the Finish Selection card came or went): the size it returns
        /// to when full screen is left changes with it.
        /// </summary>
        public void AdjustSavedHeight(double delta)
        {
            try
            {
                if (saved == null) return;
                Bounds b = saved.Value;
                b.Height = Math.Max(Win.MinHeight, b.Height + delta);
                saved = b;
            }
            catch (Exception)
            {
            }
        }

        public void ToggleFull()
        {
            try
            {
                if (Full)
                {
                    Bounds b = saved.Value;
                    Win.Left = b.Left;
                    Win.Top = b.Top;
                    Win.Width = b.Width;
                    Win.Height = b.Height;
                    Full = false;
                    return;
                }
                Window win = Win;
                saved = new Bounds { Left = win.Left, Top = win.Top, Width = win.Width, Height = win.Height };
                double sx, sy;
                Dpi(out sx, out sy);
                try
                {
                    int cx = (int)((win.Left + win.ActualWidth / 2.0) * sx);
                    int cy = (int)((win.Top + 20.0) * sy);
                    System.Drawing.Rectangle wa = System.Windows.Forms.Screen.FromPoint(new System.Drawing.Point(cx, cy)).WorkingArea;
                    win.Left = wa.X / sx;
                    win.Top = wa.Y / sy;
                    win.Width = wa.Width / sx;
                    win.Height = wa.Height / sy;
                }
                catch (Exception)
                {
                    Rect wa = SystemParameters.WorkArea;
                    win.Left = wa.Left;
                    win.Top = wa.Top;
                    win.Width = wa.Width;
                    win.Height = wa.Height;
                }
                Full = true;
            }
            catch (Exception)
            {
            }
        }

        private void LeaveFullUnderMouse(MouseButtonEventArgs e)
        {
            Window win = Win;
            try
            {
                Point pos = e.GetPosition(win);
                double frac = pos.X / Math.Max(win.ActualWidth, 1.0);
                double w = saved.Value.Width, h = saved.Value.Height;
                win.Width = w;
                win.Height = h;
                win.Left = win.Left + pos.X - frac * w;
            }
            catch (Exception)
            {
            }
            Full = false;
        }
    }
}
