using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Threading;

namespace RevoBIM.UI.ProSheets
{
    public static partial class PsUi
    {
        /// <summary>Every live window's Chrome (Python _CHROMES).</summary>
        internal static readonly List<Chrome> Chromes = new List<Chrome>();

        /// <summary>The Chromes shrunk to a bar, bottom first (Python _SHRUNK).</summary>
        internal static readonly List<Chrome> Shrunk = new List<Chrome>();

        /// <summary>The Chrome looking after a Pro Sheets window, or null.</summary>
        public static Chrome ChromeOf(Window window)
        {
            if (window == null) return null;
            foreach (Chrome chrome in Chromes)
            {
                if (ReferenceEquals(chrome.Window, window)) return chrome;
            }
            return null;
        }

        /// <summary>
        /// Drag, close, full screen, shrink and the resize grips for one window.
        ///
        /// A borderless AllowsTransparency window cannot be resized by WPF - there
        /// is nothing hit testable in its transparent frame. The window carries
        /// eight thumbs of its own instead, in an overlay Grid with no Background
        /// so everything underneath stays clickable.
        /// </summary>
        public class Chrome
        {
            /// <summary>Grip name -> (move left, move top, change width, change height).</summary>
            public static readonly Dictionary<string, (bool Left, bool Top, bool Width, bool Height)> Grips =
                new Dictionary<string, (bool Left, bool Top, bool Width, bool Height)>(StringComparer.Ordinal)
                {
                    ["GripNW"] = (true, true, true, true),
                    ["GripN"] = (false, true, false, true),
                    ["GripNE"] = (false, true, true, true),
                    ["GripW"] = (true, false, true, false),
                    ["GripE"] = (false, false, true, false),
                    ["GripSW"] = (true, false, true, true),
                    ["GripS"] = (false, false, false, true),
                    ["GripSE"] = (false, false, true, true),
                };

            /// <summary>
            /// The edges whose double-click stretches the window top to bottom of
            /// its screen, as Windows does for its own windows. Corners still resize.
            /// </summary>
            public static readonly string[] TallEdges = { "GripN", "GripS" };

            // The window slides down to the bottom of its screen like a drawer
            // closing, until only its title bar floats there, so Revit can be seen
            // without closing anything. Every Pro Sheets window with a
            // ShrinkButton in its header gets it from here.
            public const double DrawerSeconds = 0.28;
            public const int DrawerTickMs = 15;
            public const double BarMargin = 8;
            public const double BarGap = 4;

            public Window Window;
            public Action OnClose;
            public bool FullScreen;
            public (double Left, double Top, double Width, double Height)? SavedBounds;

            /// <summary>Where the window was before a double-click stretched it top to bottom; null while not stretched.</summary>
            public (double Top, double Height)? TallSaved;

            // Shrunk to its title bar at the bottom of the screen (1.49.0): the
            // bounds and MinHeight to come back to, the owner shrunk along with
            // it, and the drawer animation in flight.
            public bool Shrunk;
            public (double Left, double Top, double Width, double Height, double MinHeight)? ShrinkSaved;
            public Chrome LiftedOwner;
            internal DispatcherTimer Drawer;
            internal List<UIElement> HiddenParts = new List<UIElement>();
            internal CornerRadius? HeaderCorner;

            /// <summary>
            /// Says a job is running (the main window's export): the shrunk bar is
            /// not dragged then - DragMove is a modal message loop, and Revit's API
            /// context is no place to start one.
            /// </summary>
            public Func<bool> Busy;

            public Chrome(Window window, Action onClose = null)
            {
                Window = window;
                OnClose = onClose;
                FullScreen = false;
                SavedBounds = null;
                TallSaved = null;
                Shrunk = false;
                ShrinkSaved = null;
                LiftedOwner = null;
                Drawer = null;
                HiddenParts = new List<UIElement>();
                HeaderCorner = null;
                Busy = null;
                Wire();
                Chromes.Add(this);
                try
                {
                    window.Closed += Forget;
                }
                catch (Exception)
                {
                }
                try
                {
                    window.SourceInitialized += PlaceStart;
                }
                catch (Exception)
                {
                }
                try
                {
                    window.PreviewKeyDown += PreviewKey;
                }
                catch (Exception)
                {
                }
            }

            // ---------------------------------------------------------------- wiring
            internal void Wire()
            {
                Window window = Window;

                if (Find(window, "HeaderBar") is UIElement header)
                {
                    try
                    {
                        header.MouseLeftButtonDown += HeaderDown;
                    }
                    catch (Exception)
                    {
                    }
                }

                if (Find(window, "CloseButton") is ButtonBase closeButton)
                {
                    try
                    {
                        closeButton.Click += CloseClicked;
                    }
                    catch (Exception)
                    {
                    }
                }

                if (Find(window, "FullScreenButton") is ButtonBase fullButton)
                {
                    try
                    {
                        fullButton.Click += FullClicked;
                    }
                    catch (Exception)
                    {
                    }
                }

                if (Find(window, "ShrinkButton") is ButtonBase shrinkButton)
                {
                    try
                    {
                        shrinkButton.Click += ShrinkClicked;
                    }
                    catch (Exception)
                    {
                    }
                }

                try
                {
                    window.KeyDown += KeyDown;
                }
                catch (Exception)
                {
                }

                foreach (string name in Grips.Keys)
                {
                    if (!(Find(window, name) is Thumb thumb)) continue;
                    try
                    {
                        thumb.DragDelta += MakeGrip(name);
                    }
                    catch (Exception)
                    {
                        continue;
                    }
                    if (TallEdges.Contains(name))
                    {
                        // Preview: seen before the thumb takes the press for a drag.
                        try
                        {
                            thumb.PreviewMouseLeftButtonDown += EdgeDown;
                        }
                        catch (Exception)
                        {
                        }
                    }
                }
            }

            internal DragDeltaEventHandler MakeGrip(string name)
            {
                var grip = Grips[name];
                return (sender, args) => Resize(args, grip.Left, grip.Top, grip.Width, grip.Height);
            }

            // ------------------------------------------------------------- behaviour

            /// <summary>A double-click on the top or bottom edge: the full height of the screen, and back again on the next.</summary>
            internal void EdgeDown(object sender, MouseButtonEventArgs args)
            {
                try
                {
                    if (args.ClickCount != 2) return;
                    args.Handled = true;
                }
                catch (Exception)
                {
                    return;
                }
                ToggleTall();
            }

            /// <summary>
            /// Stretch the window to its screen's full working height, keeping its
            /// width and left edge - or, already stretched, put it back. True when
            /// it is now stretched, false when put back, null when nothing could be
            /// done (full screen already fills it).
            /// </summary>
            public bool? ToggleTall()
            {
                if (FullScreen || Shrunk) return null;
                var area = WorkingArea(Window);
                if (area == null) return null;
                try
                {
                    var result = FullHeight(area.Value, Window.Top, Window.Height, TallSaved);
                    TallSaved = result.Saved;
                    Window.Top = result.Top;
                    Window.Height = result.Height;
                }
                catch (Exception)
                {
                    return null;
                }
                return TallSaved != null;
            }

            internal void HeaderDown(object sender, MouseButtonEventArgs args)
            {
                try
                {
                    if (args.ClickCount == 2)
                    {
                        // A shrunk bar's double-click brings the window back; it
                        // does not go full screen from the bottom of the screen.
                        if (Shrunk)
                        {
                            Expand();
                            return;
                        }
                        ToggleFullScreen();
                        return;
                    }
                    if (Shrunk)
                    {
                        // The bar can be dragged along the bottom of the screen -
                        // but not while a job runs.
                        if (Busy != null && Busy()) return;
                        Window.DragMove();
                        return;
                    }
                    if (FullScreen)
                    {
                        // Dragging a full screen window is asking to leave it.
                        SetFullScreen(false);
                    }
                    Window.DragMove();
                }
                catch (Exception)
                {
                }
            }

            internal void CloseClicked(object sender, RoutedEventArgs args)
            {
                if (OnClose != null)
                {
                    try
                    {
                        OnClose();
                        return;
                    }
                    catch (Exception)
                    {
                    }
                }
                try
                {
                    Window.Close();
                }
                catch (Exception)
                {
                }
            }

            internal void FullClicked(object sender, RoutedEventArgs args)
            {
                ToggleFullScreen();
            }

            internal void KeyDown(object sender, KeyEventArgs args)
            {
                try
                {
                    if (args.Key == Key.F11)
                    {
                        ToggleFullScreen();
                        args.Handled = true;
                        return;
                    }
                    if (args.Key == Key.Escape && FullScreen)
                    {
                        SetFullScreen(false);
                        args.Handled = true;
                    }
                }
                catch (Exception)
                {
                }
            }

            internal void Resize(DragDeltaEventArgs args, bool moveLeft, bool moveTop, bool changeWidth, bool changeHeight)
            {
                Window window = Window;
                if (Shrunk || Drawer != null) return;
                try
                {
                    double dx = args.HorizontalChange;
                    double dy = args.VerticalChange;
                    double minWidth = window.MinWidth != 0 ? window.MinWidth : 200;
                    double minHeight = window.MinHeight != 0 ? window.MinHeight : 150;

                    if (changeWidth)
                    {
                        if (moveLeft)
                        {
                            double newWidth = window.Width - dx;
                            if (newWidth >= minWidth)
                            {
                                window.Left = window.Left + dx;
                                window.Width = newWidth;
                            }
                        }
                        else
                        {
                            double newWidth = window.Width + dx;
                            if (newWidth >= minWidth) window.Width = newWidth;
                        }
                    }
                    if (changeHeight)
                    {
                        if (moveTop)
                        {
                            double newHeight = window.Height - dy;
                            if (newHeight >= minHeight)
                            {
                                window.Top = window.Top + dy;
                                window.Height = newHeight;
                            }
                        }
                        else
                        {
                            double newHeight = window.Height + dy;
                            if (newHeight >= minHeight) window.Height = newHeight;
                        }
                    }
                    if (FullScreen)
                    {
                        FullScreen = false;
                        SayFullScreen();
                    }
                }
                catch (Exception)
                {
                }
            }

            // ------------------------------------------------------------ full screen
            public void ToggleFullScreen()
            {
                if (Shrunk) return;
                SetFullScreen(!FullScreen);
            }

            // ------------------------------------------------------- shrink drawer
            internal void ShrinkClicked(object sender, RoutedEventArgs args)
            {
                ToggleShrink();
            }

            /// <summary>
            /// Ctrl+Shift+H shrinks or brings back. While shrunk, Escape, Enter and
            /// F11 bring the window back - Escape must not reach a dialog's Cancel,
            /// nor F11 fill the screen with a window nobody can see.
            /// </summary>
            internal void PreviewKey(object sender, KeyEventArgs args)
            {
                Key key;
                bool control, shift;
                try
                {
                    key = args.Key;
                    ModifierKeys modifiers = Keyboard.Modifiers;
                    control = (modifiers & ModifierKeys.Control) == ModifierKeys.Control;
                    shift = (modifiers & ModifierKeys.Shift) == ModifierKeys.Shift;
                }
                catch (Exception)
                {
                    return;
                }
                try
                {
                    if (key == Key.H && control && shift)
                    {
                        ToggleShrink();
                        args.Handled = true;
                        return;
                    }
                    // Key.Enter and Key.Return are the same value in WPF.
                    if (Shrunk && (key == Key.Escape || key == Key.Enter || key == Key.F11))
                    {
                        Expand();
                        args.Handled = true;
                    }
                }
                catch (Exception)
                {
                }
            }

            /// <summary>
            /// A dialog opening over a shrunk owner is centred on its screen.
            /// Centred on the owner it would sit on a 42-pixel bar at the bottom,
            /// most of it off the screen - and that is when a prompt turns up
            /// unasked, while the tool is put away.
            /// </summary>
            internal void PlaceStart(object sender = null, EventArgs args = null)
            {
                Window ownerWindow = null;
                try
                {
                    ownerWindow = Window.Owner;
                }
                catch (Exception)
                {
                }
                Chrome owner = ChromeOf(ownerWindow);
                if (owner == null || !owner.Shrunk) return;
                var area = WorkingArea(owner.Window);
                if (area == null) return;
                try
                {
                    var place = Centred(area.Value, Window.Width, Window.Height);
                    Window.WindowStartupLocation = WindowStartupLocation.Manual;
                    Window.Left = place.Left;
                    Window.Top = place.Top;
                }
                catch (Exception)
                {
                }
            }

            /// <summary>
            /// Hold the body at a fixed height for the slide and let the window
            /// clip it, so a virtualising grid is not re-measured on every frame -
            /// a drawer drawn away, not a window squashed.
            /// </summary>
            internal void Pin(double height)
            {
                if (!(Window.Content is FrameworkElement content)) return;
                try
                {
                    content.Height = height;
                    content.VerticalAlignment = VerticalAlignment.Top;
                }
                catch (Exception)
                {
                }
            }

            internal void Unpin()
            {
                if (!(Window.Content is FrameworkElement content)) return;
                try
                {
                    content.Height = double.NaN;
                    content.VerticalAlignment = VerticalAlignment.Stretch;
                }
                catch (Exception)
                {
                }
            }

            public void ToggleShrink()
            {
                if (Shrunk) Expand();
                else Shrink();
            }

            /// <summary>(width, height) of the window as the user left it: the size to remember, never the shrunk bar's.</summary>
            public (double Width, double Height) TrueSize()
            {
                if (ShrinkSaved != null) return (ShrinkSaved.Value.Width, ShrinkSaved.Value.Height);
                return (Window.Width, Window.Height);
            }

            /// <summary>The window's height with only its title bar showing.</summary>
            public double BarHeight()
            {
                if (!(Find(Window, "HeaderBar") is FrameworkElement header)) return 44.0;
                try
                {
                    double offset = header.TranslatePoint(new Point(0, 0), Window).Y;
                    return header.ActualHeight + 2 * Math.Max(0.0, offset);
                }
                catch (Exception)
                {
                    try
                    {
                        return header.ActualHeight + 2.0;
                    }
                    catch (Exception)
                    {
                        return 44.0;
                    }
                }
            }

            /// <summary>Slide down to the bottom of the screen, title bar only.</summary>
            public bool Shrink()
            {
                if (Shrunk || Drawer != null) return false;
                Window window = Window;
                // A dialog over a Pro Sheets window would still leave that window
                // covering Revit, so the owner goes down with it, first.
                Window ownerWindow = null;
                try
                {
                    ownerWindow = window.Owner;
                }
                catch (Exception)
                {
                }
                Chrome owner = ChromeOf(ownerWindow);
                if (owner != null && !owner.Shrunk)
                {
                    if (owner.Shrink()) LiftedOwner = owner;
                }
                var area = WorkingArea(window);
                if (area == null) return false;
                double top, bar;
                try
                {
                    ShrinkSaved = (window.Left, window.Top, window.Width, window.Height, window.MinHeight);
                    bar = BarHeight();
                    var below = PsUi.Shrunk.Select(other => other.BarHeight()).ToList();
                    top = ShrunkTop(area.Value, bar, below, BarMargin, BarGap);
                    window.MinHeight = 0;
                }
                catch (Exception)
                {
                    ShrinkSaved = null;
                    return false;
                }
                Shrunk = true;
                PsUi.Shrunk.Add(this);
                PaintShrink();
                Pin(window.Height);
                Animate(window.Top, window.Height, top, bar, ShrunkDone);
                return true;
            }

            /// <summary>Slide back up to where the window was.</summary>
            public bool Expand()
            {
                if (!Shrunk || Drawer != null) return false;
                var saved = ShrinkSaved;
                ShowParts();
                Shrunk = false;
                PsUi.Shrunk.Remove(this);
                PaintShrink();
                if (saved == null) return true;

                void Done()
                {
                    Unpin();
                    try
                    {
                        Window.MinHeight = saved.Value.MinHeight;
                    }
                    catch (Exception)
                    {
                    }
                    ShrinkSaved = null;
                    Chrome lifted = LiftedOwner;
                    LiftedOwner = null;
                    if (lifted != null) lifted.Expand();
                    try
                    {
                        Window.Activate();
                    }
                    catch (Exception)
                    {
                    }
                }

                try
                {
                    Window.Left = saved.Value.Left;
                }
                catch (Exception)
                {
                }
                Pin(saved.Value.Height);
                Animate(Window.Top, Window.Height, saved.Value.Top, saved.Value.Height, Done);
                return true;
            }

            /// <summary>Put the window back at once, no animation - before it closes.</summary>
            public void RestoreNow()
            {
                StopDrawer();
                var saved = ShrinkSaved;
                if (saved == null) return;
                ShowParts();
                Unpin();
                try
                {
                    Window.Left = saved.Value.Left;
                    Window.Top = saved.Value.Top;
                    Window.Width = saved.Value.Width;
                    Window.Height = saved.Value.Height;
                    Window.MinHeight = saved.Value.MinHeight;
                }
                catch (Exception)
                {
                }
                Shrunk = false;
                ShrinkSaved = null;
                PsUi.Shrunk.Remove(this);
                PaintShrink();
            }

            internal void ShrunkDone()
            {
                HideParts();
                Unpin();
            }

            /// <summary>
            /// Everything but the title bar collapsed, its corners rounded, so the
            /// bar floats as a bar rather than a window cut off below it.
            /// </summary>
            internal void HideParts()
            {
                if (!(Find(Window, "HeaderBar") is FrameworkElement header)) return;
                HiddenParts = new List<UIElement>();
                try
                {
                    foreach (UIElement child in ((Panel)header.Parent).Children)
                    {
                        if (ReferenceEquals(child, header) || child.Visibility != Visibility.Visible) continue;
                        child.Visibility = Visibility.Collapsed;
                        HiddenParts.Add(child);
                    }
                }
                catch (Exception)
                {
                }
                // The resize grips too: a bar is moved, not resized.
                foreach (string name in Grips.Keys)
                {
                    if (!(Find(Window, name) is UIElement thumb)) continue;
                    try
                    {
                        if (thumb.Visibility == Visibility.Visible)
                        {
                            thumb.Visibility = Visibility.Collapsed;
                            HiddenParts.Add(thumb);
                        }
                    }
                    catch (Exception)
                    {
                    }
                }
                try
                {
                    var border = (Border)header;
                    HeaderCorner = border.CornerRadius;
                    double radius = border.CornerRadius.TopLeft != 0 ? border.CornerRadius.TopLeft : 5;
                    border.CornerRadius = new CornerRadius(radius);
                }
                catch (Exception)
                {
                    HeaderCorner = null;
                }
            }

            internal void ShowParts()
            {
                foreach (UIElement child in HiddenParts)
                {
                    try
                    {
                        child.Visibility = Visibility.Visible;
                    }
                    catch (Exception)
                    {
                    }
                }
                HiddenParts = new List<UIElement>();
                CornerRadius? corner = HeaderCorner;
                if (Find(Window, "HeaderBar") is Border header && corner != null)
                {
                    try
                    {
                        header.CornerRadius = corner.Value;
                    }
                    catch (Exception)
                    {
                    }
                }
                HeaderCorner = null;
            }

            /// <summary>
            /// The button's Tag drives its glyph: the shrink arrow, or the green up
            /// arrow once shrunk (ShrinkButton style in Theme.xaml).
            /// </summary>
            internal void PaintShrink()
            {
                if (!(Find(Window, "ShrinkButton") is FrameworkElement button)) return;
                try
                {
                    button.Tag = Shrunk ? "shrunk" : "";
                    button.ToolTip = Shrunk ? "Expand the window" : "Shrink to the bottom of the screen";
                }
                catch (Exception)
                {
                }
            }

            /// <summary>
            /// Top and Height eased from where they are to the end, on a
            /// DispatcherTimer - a Storyboard on a borderless window's Top and
            /// Height fights the layout pass and judders.
            /// </summary>
            internal void Animate(double top, double height, double endTop, double endHeight, Action done = null)
            {
                StopDrawer();
                Stopwatch clock = Stopwatch.StartNew();
                Window window = Window;

                void Tick(object sender, EventArgs args)
                {
                    double progress = clock.Elapsed.TotalSeconds / DrawerSeconds;
                    double eased = EaseOut(progress);
                    try
                    {
                        window.Top = top + (endTop - top) * eased;
                        window.Height = Math.Max(1.0, height + (endHeight - height) * eased);
                    }
                    catch (Exception)
                    {
                        progress = 1.0;
                    }
                    if (progress >= 1.0)
                    {
                        StopDrawer();
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
                    }
                }

                try
                {
                    var timer = new DispatcherTimer();
                    timer.Interval = TimeSpan.FromMilliseconds(DrawerTickMs);
                    timer.Tick += Tick;
                    Drawer = timer;
                    timer.Start();
                }
                catch (Exception)
                {
                    // No timer: jump straight there.
                    Drawer = null;
                    try
                    {
                        window.Top = endTop;
                        window.Height = endHeight;
                    }
                    catch (Exception)
                    {
                    }
                    done?.Invoke();
                }
            }

            internal void StopDrawer()
            {
                DispatcherTimer timer = Drawer;
                Drawer = null;
                if (timer != null)
                {
                    try
                    {
                        timer.Stop();
                    }
                    catch (Exception)
                    {
                    }
                }
            }

            /// <summary>
            /// Closed: out of the lists, and an owner it took down brought back - a
            /// dialog closed from its bar must not strand the main window.
            /// </summary>
            internal void Forget(object sender = null, EventArgs args = null)
            {
                StopDrawer();
                PsUi.Shrunk.Remove(this);
                Chromes.Remove(this);
                Chrome owner = LiftedOwner;
                LiftedOwner = null;
                if (owner != null) owner.Expand();
            }

            /// <summary>
            /// Full screen by bounds, never WindowState.Maximized. Maximising a
            /// borderless AllowsTransparency window the normal way covers the task
            /// bar and lands on the primary monitor rather than the one the window
            /// is on.
            /// </summary>
            public void SetFullScreen(bool wanted)
            {
                Window window = Window;
                try
                {
                    if (wanted && !FullScreen)
                    {
                        SavedBounds = (window.Left, window.Top, window.Width, window.Height);
                        var bounds = WorkingArea(window);
                        if (bounds == null) return;
                        window.Left = bounds.Value.Left;
                        window.Top = bounds.Value.Top;
                        window.Width = bounds.Value.Width;
                        window.Height = bounds.Value.Height;
                        FullScreen = true;
                    }
                    else if (!wanted && FullScreen)
                    {
                        if (SavedBounds != null)
                        {
                            window.Left = SavedBounds.Value.Left;
                            window.Top = SavedBounds.Value.Top;
                            window.Width = SavedBounds.Value.Width;
                            window.Height = SavedBounds.Value.Height;
                        }
                        FullScreen = false;
                    }
                }
                catch (Exception)
                {
                }
                SayFullScreen();
            }

            internal void SayFullScreen()
            {
                if (!(Find(Window, "FullScreenButton") is FrameworkElement button)) return;
                try
                {
                    button.ToolTip = FullScreen ? "Leave full screen (F11)" : "Full screen (F11)";
                }
                catch (Exception)
                {
                }
            }
        }
    }
}
