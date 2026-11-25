using System;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Threading;
using Autodesk.Revit.UI;
using RevoBIM.Tools.AddinManager;

using Button = System.Windows.Controls.Button;

namespace RevoBIM.UI.AddinManager
{
    /// <summary>
    /// The floating window, used whenever Revit will not hand back the dockable pane. It still docks: the dock buttons snap
    /// it to the left or right edge of Revit's drawing area, full height, and it follows Revit when that is moved or
    /// resized; dragging the header lifts it off again. One window per session: a second press of the ribbon button brings
    /// the open one back. Port of rba_window.py (without the shrink-to-taskbar drawer).
    /// </summary>
    internal sealed class AmWindow
    {
        private const int SnapMs = 500;
        private const double LiftPx = 6;

        private static AmWindow current;

        private readonly AmPane pane;
        private readonly Window window;
        private readonly string status;
        private bool full;
        private double[] fullBounds;
        private string side;
        private bool dragging;
        private Point? press;
        private DispatcherTimer snapTimer;
        private bool areaWarned;

        private AmWindow(AmPane pane, string status)
        {
            this.pane = pane;
            this.status = status;
            window = AmXaml.Load<Window>("RbaWindow.xaml", pane.ThemeName);
        }

        /// <summary>Opens the window, or brings back the one already open.</summary>
        public static bool Show(out string message)
        {
            message = "";
            if (current != null)
            {
                try
                {
                    current.window.Activate();
                    return true;
                }
                catch (Exception)
                {
                    current = null;
                }
            }
            try
            {
                var pane = new AmPane("window");
                pane.FirstReadDone = true;
                pane.Rescan();
                current = new AmWindow(pane, AmDock.Status());
                current.Open();
                return true;
            }
            catch (Exception err)
            {
                AmCore.LogException("window/show", err);
                current = null;
                message = "The Addin Manager window would not open - see " + AmCore.DebugPath();
                return false;
            }
        }

        private void Open()
        {
            AmTheme.Apply(window, pane.ThemeName);
            pane.ThemeListeners.Add(name => AmTheme.Apply(window, name));
            ((ContentControl)window.FindName("Host")).Content = pane.Control;

            pane.Find<UIElement>("WindowControls").Visibility = Visibility.Visible;
            pane.Find<UIElement>("ShrinkBtn").Visibility = Visibility.Collapsed;   // no drawer in the C# window
            var header = pane.Find<Border>("Header");
            header.Tag = "round";
            header.CornerRadius = new CornerRadius(6, 6, 0, 0);
            if (!string.IsNullOrEmpty(status))
            {
                pane.SetStatus(status);
                AmCore.Log("floating: " + status);
            }
            pane.HostWindow = window;

            Wire();
            Place();
            AmUi.Own(window, null);
            window.Show();
            if (side != null) Snap();
            AmCore.Log("floating window opened, dock=" + (side ?? "free"));
        }

        private void Place()
        {
            var settings = pane.Settings;
            window.Width = Math.Max(window.MinWidth, AmCore.AsInt(settings, "win_w", 380));
            window.Height = Math.Max(window.MinHeight, AmCore.AsInt(settings, "win_h", 900));
            string wanted = AmCore.Get(settings, "dock").Trim().ToLowerInvariant();
            side = wanted == "left" || wanted == "right" ? wanted : null;
            double left, top;
            bool onScreen = false;
            if (double.TryParse(AmCore.Get(settings, "win_left"), out left) && double.TryParse(AmCore.Get(settings, "win_top"), out top))
            {
                onScreen = SystemParameters.VirtualScreenLeft - 50 <= left && left <= SystemParameters.VirtualScreenLeft + SystemParameters.VirtualScreenWidth - 100
                           && SystemParameters.VirtualScreenTop - 10 <= top && top <= SystemParameters.VirtualScreenTop + SystemParameters.VirtualScreenHeight - 60;
                if (onScreen)
                {
                    window.WindowStartupLocation = WindowStartupLocation.Manual;
                    window.Left = left;
                    window.Top = top;
                }
            }
            if (!onScreen) window.WindowStartupLocation = WindowStartupLocation.CenterScreen;
            PaintDockButtons();
        }

        private void Wire()
        {
            var header = pane.Find<Border>("Header");
            header.MouseLeftButtonDown += OnHeaderDown;
            header.MouseMove += OnHeaderMove;
            header.MouseLeftButtonUp += (s, a) => { press = null; Release(s as UIElement); };
            pane.Find<Button>("CloseBtn").Click += (s, a) => { try { window.Close(); } catch (Exception) { } };
            pane.Find<Button>("FullBtn").Click += (s, a) => ToggleFull();
            pane.Find<Button>("DockLeftBtn").Click += (s, a) => SetSide(side == "left" ? null : "left", true);
            pane.Find<Button>("DockRightBtn").Click += (s, a) => SetSide(side == "right" ? null : "right", true);
            window.KeyDown += (s, a) =>
            {
                if (a.Key == Key.F11) { ToggleFull(); a.Handled = true; }
            };
            window.Closing += (s, a) => OnClosing();
            window.Closed += (s, a) => OnClosed();

            Grip("GripL", Cursors.SizeWE, -1, 0);
            Grip("GripR", Cursors.SizeWE, 1, 0);
            Grip("GripT", Cursors.SizeNS, 0, -1);
            Grip("GripB", Cursors.SizeNS, 0, 1);
            Grip("GripTL", Cursors.SizeNWSE, -1, -1);
            Grip("GripTR", Cursors.SizeNESW, 1, -1);
            Grip("GripBL", Cursors.SizeNESW, -1, 1);
            Grip("GripBR", Cursors.SizeNWSE, 1, 1);

            snapTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(SnapMs) };
            snapTimer.Tick += (s, a) =>
            {
                if (side != null && !dragging && !full)
                {
                    try { Snap(); } catch (Exception err) { AmCore.LogException("dock/tick", err); }
                }
            };
            snapTimer.Start();
        }

        // ------------------------------------------------------------------ header

        private void OnHeaderDown(object sender, MouseButtonEventArgs args)
        {
            if (args.ClickCount == 2)
            {
                ToggleFull();
                return;
            }
            if (side != null)
            {
                // docked: a click is only a click; the window lifts off when the mouse moves with the button held
                try
                {
                    press = args.GetPosition(window);
                    ((UIElement)sender).CaptureMouse();
                }
                catch (Exception)
                {
                    press = null;
                }
                return;
            }
            if (full) LeaveFull();
            Drag();
        }

        private void OnHeaderMove(object sender, MouseEventArgs args)
        {
            if (press == null) return;
            try
            {
                if (args.LeftButton != MouseButtonState.Pressed)
                {
                    press = null;
                    return;
                }
                Point here = args.GetPosition(window);
                if (Math.Abs(here.X - press.Value.X) < LiftPx && Math.Abs(here.Y - press.Value.Y) < LiftPx) return;
            }
            catch (Exception)
            {
                press = null;
                return;
            }
            press = null;
            Release(sender as UIElement);
            SetSide(null, false);   // lifted off: same size, free, still under the cursor
            Drag();
        }

        private static void Release(UIElement element)
        {
            try { if (element != null) element.ReleaseMouseCapture(); } catch (Exception) { }
        }

        private void Drag()
        {
            dragging = true;
            try { window.DragMove(); } catch (Exception) { }
            dragging = false;
        }

        // ------------------------------------------------------------------ full screen, resize

        /// <summary>Full screen by bounds, not WindowState.Maximized (which covers the taskbar and lands on the primary monitor).</summary>
        private void ToggleFull()
        {
            if (full)
            {
                LeaveFull();
                return;
            }
            double[] area = AmUi.WorkArea(window);
            if (area == null) return;
            fullBounds = new[] { window.Left, window.Top, window.Width, window.Height };
            window.Left = area[0]; window.Top = area[1]; window.Width = area[2]; window.Height = area[3];
            full = true;
        }

        private void LeaveFull()
        {
            if (!full) return;
            if (fullBounds != null)
            {
                window.Left = fullBounds[0]; window.Top = fullBounds[1]; window.Width = fullBounds[2]; window.Height = fullBounds[3];
            }
            full = false;
            fullBounds = null;
        }

        private void Grip(string name, Cursor cursor, int dx, int dy)
        {
            var thumb = window.FindName(name) as Thumb;
            if (thumb == null) return;
            thumb.Cursor = cursor;
            thumb.DragDelta += (s, args) =>
            {
                full = false;
                fullBounds = null;
                try
                {
                    if (dx < 0)
                    {
                        double width = window.Width - args.HorizontalChange;
                        if (width >= window.MinWidth) { window.Left += args.HorizontalChange; window.Width = width; }
                    }
                    else if (dx > 0)
                    {
                        double width = window.Width + args.HorizontalChange;
                        if (width >= window.MinWidth) window.Width = width;
                    }
                    if (side != null)
                    {
                        Snap();   // docked, only the width is the user's to change
                        return;
                    }
                    if (dy < 0)
                    {
                        double height = window.Height - args.VerticalChange;
                        if (height >= window.MinHeight) { window.Top += args.VerticalChange; window.Height = height; }
                    }
                    else if (dy > 0)
                    {
                        double height = window.Height + args.VerticalChange;
                        if (height >= window.MinHeight) window.Height = height;
                    }
                }
                catch (Exception)
                {
                }
            };
        }

        // ------------------------------------------------------------------ docking

        private void SetSide(string wanted, bool restore)
        {
            LeaveFull();
            if (wanted != null && side == null) RememberFree();
            string previous = side;
            side = wanted;
            if (wanted != null) Snap();
            else if (previous != null && restore)
            {
                try
                {
                    window.Height = Math.Max(window.MinHeight, AmCore.AsInt(pane.Settings, "win_h", 900));
                    window.Left = double.Parse(AmCore.Get(pane.Settings, "win_left"));
                    window.Top = double.Parse(AmCore.Get(pane.Settings, "win_top"));
                }
                catch (Exception)
                {
                }
            }
            pane.Settings["dock"] = wanted ?? "floating";
            pane.SaveSettings();
            PaintDockButtons();
            AmCore.Log("dock: " + (wanted ?? "free"));
        }

        private void PaintDockButtons()
        {
            foreach (var pair in new[] { Tuple.Create("DockLeftBtn", "left"), Tuple.Create("DockRightBtn", "right") })
            {
                try
                {
                    var button = pane.Find<Button>(pair.Item1);
                    button.Tag = side == pair.Item2 ? "on" : null;
                    button.ToolTip = side == pair.Item2 ? "Float the window again" : "Dock to the " + pair.Item2 + " of Revit's view";
                }
                catch (Exception)
                {
                }
            }
        }

        /// <summary>Revit's drawing area in WPF units, else its whole window, else the window's own screen.</summary>
        private double[] RevitArea()
        {
            UIApplication app = AmRibbon.UiApp;
            double sx, sy;
            AmUi.DipScale(window, out sx, out sy);
            if (app != null)
            {
                try
                {
                    Autodesk.Revit.DB.Rectangle rect = app.DrawingAreaExtents;
                    double width = rect.Right - rect.Left, height = rect.Bottom - rect.Top;
                    if (width > 100 && height > 100) return new[] { rect.Left / sx, rect.Top / sy, width / sx, height / sy };
                }
                catch (Exception err)
                {
                    if (!areaWarned) { areaWarned = true; AmCore.LogException("dock/DrawingAreaExtents", err); }
                }
            }
            return AmUi.WorkArea(window);
        }

        private void Snap()
        {
            if (side == null) return;
            double[] target = RevitArea();
            if (target == null) return;
            double[] rect = AmCore.DockRect(target, window.Width, side, window.MinWidth);
            double[] now = { window.Left, window.Top, window.Width, window.Height };
            if (AmCore.RectDiffers(now, rect))
            {
                window.Left = rect[0]; window.Top = rect[1]; window.Width = rect[2]; window.Height = rect[3];
            }
        }

        // ------------------------------------------------------------------ closing

        private void RememberFree()
        {
            pane.Settings["win_left"] = ((int)window.Left).ToString();
            pane.Settings["win_top"] = ((int)window.Top).ToString();
            pane.Settings["win_w"] = ((int)window.Width).ToString();
            pane.Settings["win_h"] = ((int)window.Height).ToString();
        }

        private void OnClosing()
        {
            try
            {
                if (full) LeaveFull();
                if (side != null) pane.Settings["win_w"] = ((int)window.Width).ToString();
                else RememberFree();
                pane.SaveSettings();
            }
            catch (Exception err) { AmCore.LogException("window/closing", err); }
        }

        private void OnClosed()
        {
            try { snapTimer.Stop(); } catch (Exception) { }
            try { pane.Stop(); } catch (Exception) { }
            if (ReferenceEquals(current, this)) current = null;
            AmCore.Log("floating window closed");
        }
    }
}
