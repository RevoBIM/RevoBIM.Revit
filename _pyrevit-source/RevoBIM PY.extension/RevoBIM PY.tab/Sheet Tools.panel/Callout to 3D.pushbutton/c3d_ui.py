# -*- coding: utf-8 -*-
"""Callout to 3D - XAML loading, theming, window chrome and the easter egg."""

import c3d_clr  # noqa: F401  assemblies first, always

import os
import sys
import datetime

import c3d_core as core
import theme as theme_module

from System.IO import FileStream, FileMode, FileAccess, MemoryStream, File   # noqa: E402
from System.Windows.Markup import XamlReader                                 # noqa: E402
from System.Windows.Controls import Image, TextBox, Button                    # noqa: E402
from System.Windows.Controls.Primitives import Thumb                          # noqa: E402
from System.Windows.Input import Cursors, Key, Keyboard, ModifierKeys       # noqa: E402
from System.Windows.Threading import DispatcherTimer                         # noqa: E402
from System import TimeSpan, Double                                          # noqa: E402
from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption       # noqa: E402
from System.Windows import (                                                  # noqa: E402
    PresentationSource, SystemParameters, Thickness, TextWrapping, Clipboard,
    Visibility, VerticalAlignment, CornerRadius, SizeToContent,
    WindowStartupLocation, Size,
)
from System.Windows.Media import FontFamily, RotateTransform                  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def path_to(name):
    return os.path.join(HERE, name)


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------


def _load_xaml(path):
    stream = FileStream(path, FileMode.Open, FileAccess.Read)
    try:
        return XamlReader.Load(stream)
    finally:
        stream.Close()


def theme_dictionary():
    return _load_xaml(path_to("Theme.xaml"))


def load_window(file_name):
    """Parse a layout, then merge Theme.xaml into it.

    The dictionary is merged AFTER the layout is parsed, which is why every
    layout may only use DynamicResource - a StaticResource fails at load and
    shows as a blank white pyRevit window.
    """
    window = _load_xaml(path_to(file_name))
    try:
        window.Resources.MergedDictionaries.Add(theme_dictionary())
    except Exception as err:
        core.log("theme merge failed: {0}".format(err))
    return window


def apply_theme(window, name):
    return theme_module.apply(window, name)


def image_source(path):
    """From bytes, never from System.Uri - Uri moved assemblies in 2025."""
    try:
        if not os.path.isfile(path):
            return None
        image = BitmapImage()
        image.BeginInit()
        image.StreamSource = MemoryStream(File.ReadAllBytes(path))
        image.CacheOption = BitmapCacheOption.OnLoad
        image.EndInit()
        return image
    except Exception:
        return None


def set_image(control, file_name):
    """Decorative, so a failure can never take the tool down."""
    try:
        source = image_source(path_to(file_name))
        if source is not None and isinstance(control, Image):
            control.Source = source
    except Exception:
        pass


# ---------------------------------------------------------------------------
# chrome
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# the stacked groups - each one slides open and shut under its header
# ---------------------------------------------------------------------------


class Fold(object):
    """One group of the main window: a header that slides its body open and
    shut, and a chevron that turns with it.

    Eased by hand on a timer, for the same reason as the drawer: an animated
    Height is held by the animation for good, and a group whose height is held
    can never follow its contents again.  Once open, the body goes back to an
    automatic height, so a table that grows is not cut off by the height the
    slide happened to end on.
    """

    def __init__(self, key, header, body, chevron, opened=True, on_change=None):
        self.key = key
        self.header = header
        self.body = body
        self.chevron = chevron
        self.opened = bool(opened)
        self.on_change = on_change
        self.sliding = False
        self.timer = None
        self.errors = []
        try:
            body.ClipToBounds = True
        except Exception:
            pass
        if not self.opened:
            body.Visibility = Visibility.Collapsed
        self._turn(1.0 if self.opened else 0.0)
        if header is not None:
            header.Click += self._on_click

    def _on_click(self, sender, args):
        self.toggle()

    def toggle(self):
        if self.sliding:
            return
        if self.opened:
            self.shut()
        else:
            self.open()

    def open(self, instant=False):
        if self.opened or self.sliding:
            return
        body = self.body
        body.Visibility = Visibility.Visible
        body.Height = Double.NaN
        if instant:
            self.opened = True
            self._turn(1.0)
            self._said()
            return
        try:
            width = float(self.header.ActualWidth) or float(body.ActualWidth)
            body.Measure(Size(max(1.0, width), Double.PositiveInfinity))
            target = float(body.DesiredSize.Height)
        except Exception:
            target = 0.0
        self.opened = True
        self._said()
        if target <= 1.0:
            return                          # nothing to slide - just show it
        body.Height = 0.0
        self._slide(0.0, target, 0.0, 1.0, self._landed_open)

    def shut(self):
        if not self.opened or self.sliding:
            return
        start = float(self.body.ActualHeight or 0.0)
        self.opened = False
        self._said()
        if start <= 1.0:
            self._landed_shut()
            return
        self.body.Height = start
        self._slide(start, 0.0, 1.0, 0.0, self._landed_shut)

    def _landed_open(self):
        self.body.Height = Double.NaN
        self._turn(1.0)

    def _landed_shut(self):
        self.body.Visibility = Visibility.Collapsed
        self.body.Height = Double.NaN
        self._turn(0.0)

    def _said(self):
        if self.on_change is not None:
            try:
                self.on_change(self.key, self.opened)
            except Exception as err:
                core.log(u"group {0} change threw: {1}".format(self.key, err))

    def _turn(self, amount):
        """The chevron points down when open and right when shut."""
        if self.chevron is None:
            return
        try:
            self.chevron.RenderTransform = RotateTransform(-90.0 + 90.0 * float(amount))
        except Exception:
            pass

    def _slide(self, height_from, height_to, turn_from, turn_to, landed):
        self.sliding = True
        state = {"start": datetime.datetime.now()}

        def land():
            if self.timer is not None:
                try:
                    self.timer.Stop()
                except Exception:
                    pass
            self.sliding = False
            try:
                landed()
            except Exception as err:
                core.log(u"group could not land: {0}".format(err))

        def tick(sender, args):
            try:
                spent = (datetime.datetime.now() - state["start"]).total_seconds() * 1000.0
                p = spent / core.FOLD_LENGTH_MS
                self.body.Height = max(0.0, core.fold_height(height_from, height_to, p))
                self._turn(core.fold_height(turn_from, turn_to, p))
                if p >= 1.0:
                    land()
            except Exception as err:
                self.errors.append(u"{0}".format(err))
                land()

        try:
            self.timer = DispatcherTimer()
            self.timer.Interval = TimeSpan.FromMilliseconds(core.DRAWER_STEP_MS)
            self.timer.Tick += tick
            self.timer.Start()
        except Exception:
            land()


class HeightGrip(object):
    """A strip under a panel that drags the panel taller or shorter.

    The groups are stacked in a scrolling column, so the table and the
    previews need a height of their own - and the one that suits a laptop does
    not suit a portrait screen.  `on_done(height)` is told the new height when
    the mouse is let go, for remembering.
    """

    def __init__(self, handle, target, low, high, on_done=None):
        self.handle = handle
        self.target = target
        self.low = float(low)
        self.high = float(high)
        self.on_done = on_done
        self.start = None
        try:
            handle.Cursor = Cursors.SizeNS
        except Exception:
            pass
        handle.MouseLeftButtonDown += self._down
        handle.MouseMove += self._move
        handle.MouseLeftButtonUp += self._up

    def _down(self, sender, args):
        try:
            screen = self.handle.PointToScreen(args.GetPosition(self.handle))
            self.start = (screen.Y, float(self.target.ActualHeight))
            self.handle.CaptureMouse()
            args.Handled = True
        except Exception:
            self.start = None

    def _move(self, sender, args):
        if self.start is None:
            return
        try:
            screen = self.handle.PointToScreen(args.GetPosition(self.handle))
            self.target.Height = core.clamp_height(
                self.start[1] + (screen.Y - self.start[0]), self.low, self.high)
        except Exception:
            pass

    def _up(self, sender, args):
        if self.start is None:
            return
        self.start = None
        try:
            self.handle.ReleaseMouseCapture()
        except Exception:
            pass
        if self.on_done is not None:
            try:
                self.on_done(float(self.target.Height))
            except Exception as err:
                core.log(u"height grip could not be kept: {0}".format(err))


# ---------------------------------------------------------------------------
# the drawer - shrink to taskbar
# ---------------------------------------------------------------------------

_DRAWERS = []                # every live drawer, so bars stack and owners are found


def drawer_of(window):
    for drawer in _DRAWERS:
        if drawer.window is window:
            return drawer
    return None


class Drawer(object):
    """Slides a window down to the bottom of the screen leaving its header
    floating, and back again.  One of these per window, owned by Chrome, so
    the gesture is identical on every window the tool opens.

    Eased by hand on a timer rather than animated: an animation holds its end
    value and outranks every later assignment, so a window whose Top and
    Height were animated and never released can never be moved or resized
    again - with nothing raised to say so.  Easing by hand leaves nothing to
    release.
    """

    def __init__(self, window, header, button, grips=None, area=None):
        self.window = window
        self.header = header
        self.button = button
        self.grips = grips
        self.area = area or (lambda: None)
        self.busy = lambda: False
        self.shrunk = False
        self.sliding = False
        self.saved = None
        self.parked = None
        self.hidden = []
        self.timer = None
        self.took_owner = None
        self.errors = []              # anything a tick threw, for the bench
        if button is not None:
            button.Click += self._on_click
            button.Content = u""      # the glyph is the ContentTemplate
        _DRAWERS.append(self)
        try:
            window.Closed += self._on_closed
        except Exception:
            pass

    # -- public ------------------------------------------------------------
    def toggle(self):
        if self.sliding:
            return
        if self.shrunk:
            self.expand()
        else:
            self.shrink()

    def shrink(self):
        if self.shrunk or self.sliding:
            return
        window = self.window
        area = self.area() or (0.0, 0.0, 1920.0, 1040.0)
        self.saved = {"left": window.Left, "top": window.Top, "width": window.Width,
                      "height": window.Height, "min_height": window.MinHeight,
                      "size_to_content": window.SizeToContent}
        # MinHeight and SizeToContent each veto a Height change, and a vetoed
        # slide leaves the window half shut for the session
        window.MinHeight = 0
        try:
            window.SizeToContent = getattr(SizeToContent, "Manual")
        except Exception:
            pass
        bar = core.bar_height(self.header.ActualHeight, 1.0)
        below = len([d for d in _DRAWERS if d is not self and d.shrunk])
        self.parked = core.parked_top(area, bar, below)
        self._pin()
        self._show_grips(False)

        owner = drawer_of(getattr(window, "Owner", None))
        if owner is not None and not owner.shrunk:
            # a modal dialog shrinking alone would leave its owner sat over
            # Revit, and shrinking it would have shown nothing
            owner.shrink()
            self.took_owner = owner
        self._slide(window.Top, self.parked, window.Height, bar, self._landed_shrunk)

    def expand(self, activate=True):
        if not self.shrunk or self.sliding:
            return
        window = self.window
        saved = self.saved or {}
        self._show_parts(True)
        height = saved.get("height", window.Height)
        area = self.area() or (0.0, 0.0, 1920.0, 1040.0)
        top = core.reopen_top(saved.get("top", window.Top), height, self.parked,
                              window.Top, window.Height, area)
        self._pin(height - 2.0)
        self.shrunk = False
        self._mark(False)
        self._slide(window.Top, top, window.Height, height,
                    lambda: self._landed_open(activate))

    def settle(self):
        """Put the window back at once - for closing while parked, so whatever
        remembers the window's size remembers the real one."""
        if self.timer is not None:
            try:
                self.timer.Stop()
            except Exception:
                pass
        self.sliding = False
        if self.shrunk and self.saved:
            self._show_parts(True)
            try:
                self.window.Top = self.saved["top"]
                self.window.Height = self.saved["height"]
            except Exception:
                pass
            self._restore_limits()
            self.shrunk = False
            self._mark(False)
        self._unpin()
        self._show_grips(True)
        self._release_owner(False)

    # -- the slide ---------------------------------------------------------
    def _slide(self, top_from, top_to, height_from, height_to, landed):
        window = self.window
        self.sliding = True
        state = {"start": datetime.datetime.now()}

        def land():
            if self.timer is not None:
                try:
                    self.timer.Stop()
                except Exception:
                    pass
            try:
                window.Top = top_to
                window.Height = height_to
            except Exception as err:
                core.log(u"drawer could not land: {0}".format(err))
            self.sliding = False          # before landed(), so a throw cannot jam it
            try:
                landed()
            except Exception as err:
                core.log(u"drawer landing step threw: {0}".format(err))

        def tick(sender, args):
            # a real DispatcherTimer never calls this from inside Start(), so an
            # escape here goes to the dispatcher and leaves sliding true for
            # good - every tick catches its own and lands
            try:
                spent = (datetime.datetime.now() - state["start"]).total_seconds() * 1000.0
                p = spent / core.DRAWER_LENGTH_MS
                e = core.ease_out(p)
                window.Top = top_from + (top_to - top_from) * e
                window.Height = max(1.0, height_from + (height_to - height_from) * e)
                if p >= 1.0:
                    land()
            except Exception as err:
                self.errors.append(u"{0}".format(err))
                land()

        try:
            self.timer = DispatcherTimer()
            self.timer.Interval = TimeSpan.FromMilliseconds(core.DRAWER_STEP_MS)
            self.timer.Tick += tick
            self.timer.Start()
        except Exception:
            land()                        # no timer - jump straight there

    def _landed_shrunk(self):
        self._show_parts(False)
        self._unpin()
        self.shrunk = True
        self._mark(True)

    def _landed_open(self, activate):
        self._unpin()
        self._restore_limits()
        self._show_grips(True)
        self._release_owner(activate)
        if activate:
            try:
                self.window.Activate()
            except Exception:
                pass

    # -- the parts ---------------------------------------------------------
    def _body(self):
        try:
            return self.header.Parent
        except Exception:
            return None

    def _pin(self, height=None):
        """Hold the body at its height for the length of the slide and let the
        window clip it - otherwise the table re-measures every frame and it
        reads as a window being squashed, not a drawer being drawn away."""
        body = self._body()
        if body is None:
            return
        try:
            body.Height = height if height is not None else body.ActualHeight
            body.VerticalAlignment = VerticalAlignment.Top
        except Exception:
            pass

    def _unpin(self):
        body = self._body()
        if body is None:
            return
        try:
            body.Height = Double.NaN
            body.VerticalAlignment = VerticalAlignment.Stretch
        except Exception:
            pass

    def _show_parts(self, show):
        """Everything beside the header goes while parked, and comes back as
        it was - a part that was already hidden stays hidden."""
        body = self._body()
        if body is None:
            return
        if not show:
            self.hidden = []
            for child in list(body.Children):
                if child is self.header:
                    continue
                self.hidden.append((child, child.Visibility))
                child.Visibility = Visibility.Collapsed
            try:
                self.header.CornerRadius = CornerRadius(6)
            except Exception:
                pass
            return
        for child, was in self.hidden:
            try:
                child.Visibility = was
            except Exception:
                pass
        self.hidden = []
        try:
            self.header.CornerRadius = CornerRadius(6, 6, 0, 0)
        except Exception:
            pass

    def _show_grips(self, show):
        """The grip overlay spans the whole window, so left up while parked it
        lines the bar with invisible drag handles and swallows the click on
        the arrow that brings the window back."""
        if self.grips is not None:
            try:
                self.grips.Visibility = Visibility.Visible if show else Visibility.Collapsed
            except Exception:
                pass

    def _restore_limits(self):
        saved = self.saved or {}
        try:
            self.window.MinHeight = saved.get("min_height", self.window.MinHeight)
            if saved.get("size_to_content") is not None:
                self.window.SizeToContent = saved["size_to_content"]
        except Exception:
            pass

    def _mark(self, shrunk):
        if self.button is None:
            return
        try:
            self.button.Tag = "shrunk" if shrunk else None
            self.button.ToolTip = ("Bring the window back (Ctrl+Shift+H)" if shrunk
                                   else "Shrink to the taskbar (Ctrl+Shift+H)")
        except Exception:
            pass

    def _release_owner(self, activate):
        owner = self.took_owner
        self.took_owner = None
        if owner is not None and owner.shrunk:
            owner.expand(activate=False)

    # -- events ------------------------------------------------------------
    def _on_click(self, sender, args):
        self.toggle()

    def _on_closed(self, sender, args):
        self._release_owner(False)
        try:
            _DRAWERS.remove(self)
        except ValueError:
            pass


class Chrome(object):
    """Drag, full screen and the eight resize grips a borderless
    AllowsTransparency window has to carry for itself."""

    def __init__(self, window, header, grip_grid=None, shrink_button=None):
        self.window = window
        self.header = header
        self.saved = None
        self.full = False
        if header is not None:
            header.MouseLeftButtonDown += self._on_header_down
        window.PreviewKeyDown += self._on_key
        if grip_grid is not None:
            self._add_grips(grip_grid)
        self.drawer = Drawer(window, header, shrink_button, grip_grid, self._working_area)
        try:
            # closing while parked settles first, so a remembered size is real
            window.Closing += self._on_closing
        except Exception:
            pass

    def _on_closing(self, sender, args):
        if self.drawer.shrunk or self.drawer.sliding:
            self.drawer.settle()

    # dragging -------------------------------------------------------------
    def _on_header_down(self, sender, args):
        drawer = self.drawer
        try:
            if args.ClickCount == 2:
                # parked, a double click brings it back rather than filling
                # the screen with a window nobody can see
                if drawer.shrunk:
                    drawer.expand()
                else:
                    self.toggle_full_screen()
                return
        except Exception:
            pass
        if drawer.sliding:
            return
        if drawer.shrunk and drawer.busy():
            return                        # DragMove is a modal loop; not mid-job
        try:
            if self.full:
                self.toggle_full_screen()
            self.window.DragMove()
        except Exception:
            pass

    def _on_key(self, sender, args):
        drawer = self.drawer
        try:
            shift_ctrl = (Keyboard.Modifiers & (ModifierKeys.Control | ModifierKeys.Shift)) \
                == (ModifierKeys.Control | ModifierKeys.Shift)
            if args.Key == Key.H and shift_ctrl:
                drawer.toggle()
                args.Handled = True
                return
            if drawer.shrunk and args.Key in (Key.Escape, Key.Enter, Key.Return, Key.F11):
                # parked, these bring it back rather than answering a prompt
                # nobody can see
                drawer.expand()
                args.Handled = True
                return
        except Exception:
            pass
        try:
            if args.Key == Key.F11:
                self.toggle_full_screen()
                args.Handled = True
            elif args.Key == Key.Escape and self.full:
                self.toggle_full_screen()
                args.Handled = True
        except Exception:
            pass

    # full screen ----------------------------------------------------------
    def _working_area(self):
        """The working area of whichever screen the window is on, in device
        independent units."""
        left, top, width, height = None, None, None, None
        try:
            from System.Windows.Forms import Screen
            handle_point = None
            try:
                from System.Drawing import Point
                handle_point = Point(int(self.window.Left) + 10, int(self.window.Top) + 10)
            except Exception:
                handle_point = None
            screen = Screen.FromPoint(handle_point) if handle_point else Screen.PrimaryScreen
            area = screen.WorkingArea
            left, top, width, height = area.Left, area.Top, area.Width, area.Height
        except Exception:
            try:
                left = SystemParameters.WorkArea.Left
                top = SystemParameters.WorkArea.Top
                width = SystemParameters.WorkArea.Width
                height = SystemParameters.WorkArea.Height
                return (left, top, width, height)
            except Exception:
                return None

        scale_x, scale_y = 1.0, 1.0
        try:
            source = PresentationSource.FromVisual(self.window)
            matrix = source.CompositionTarget.TransformToDevice
            scale_x = matrix.M11 or 1.0
            scale_y = matrix.M22 or 1.0
        except Exception:
            pass
        return (left / scale_x, top / scale_y, width / scale_x, height / scale_y)

    def toggle_full_screen(self):
        if self.drawer.shrunk or self.drawer.sliding:
            return False
        window = self.window
        if self.full:
            if self.saved:
                window.Left, window.Top, window.Width, window.Height = self.saved
            self.full = False
            return False
        area = self._working_area()
        if not area:
            return False
        self.saved = (window.Left, window.Top, window.Width, window.Height)
        window.Left, window.Top, window.Width, window.Height = area
        self.full = True
        return True

    # resize grips ---------------------------------------------------------
    def _add_grips(self, grid):
        from System.Windows import HorizontalAlignment, VerticalAlignment, Thickness
        from System.Windows.Media import Brushes
        specs = [
            ("left", HorizontalAlignment.Left, VerticalAlignment.Stretch, 5, 0, Cursors.SizeWE),
            ("right", HorizontalAlignment.Right, VerticalAlignment.Stretch, 5, 0, Cursors.SizeWE),
            ("top", HorizontalAlignment.Stretch, VerticalAlignment.Top, 0, 5, Cursors.SizeNS),
            ("bottom", HorizontalAlignment.Stretch, VerticalAlignment.Bottom, 0, 5, Cursors.SizeNS),
            ("topleft", HorizontalAlignment.Left, VerticalAlignment.Top, 8, 8, Cursors.SizeNWSE),
            ("topright", HorizontalAlignment.Right, VerticalAlignment.Top, 8, 8, Cursors.SizeNESW),
            ("bottomleft", HorizontalAlignment.Left, VerticalAlignment.Bottom, 8, 8, Cursors.SizeNESW),
            ("bottomright", HorizontalAlignment.Right, VerticalAlignment.Bottom, 8, 8, Cursors.SizeNWSE),
        ]
        for name, h_align, v_align, width, height, cursor in specs:
            thumb = Thumb()
            thumb.Tag = name
            thumb.HorizontalAlignment = h_align
            thumb.VerticalAlignment = v_align
            if width:
                thumb.Width = width
            if height:
                thumb.Height = height
            thumb.Cursor = cursor
            thumb.Opacity = 0.0
            thumb.Background = Brushes.Transparent
            thumb.Margin = Thickness(0)
            thumb.DragDelta += self._on_drag
            if name in ("top", "bottom"):
                thumb.MouseDoubleClick += self._on_edge_double
            try:
                grid.Children.Add(thumb)
            except Exception:
                pass

    def _on_edge_double(self, sender, args):
        """Double click the top or bottom edge to stretch the window to the
        full height of the screen it is on - and again to put it back, as
        Windows does for a framed window."""
        if self.drawer.shrunk or self.drawer.sliding or self.full:
            return
        area = self._working_area()
        if not area:
            return
        try:
            top, height, self.tall = core.tall_toggle(
                area, self.window.Top, self.window.Height, getattr(self, "tall", None))
            self.window.Top = top
            self.window.Height = max(float(self.window.MinHeight or 0), height)
            args.Handled = True
        except Exception as err:
            core.log(u"edge double click failed: {0}".format(err))

    def _on_drag(self, sender, args):
        self.tall = None                  # a drag after stretching keeps the new size
        window = self.window
        try:
            name = u"{0}".format(sender.Tag)
            dx, dy = args.HorizontalChange, args.VerticalChange
            if "left" in name:
                width = window.Width - dx
                if width >= window.MinWidth:
                    window.Left += dx
                    window.Width = width
            if "right" in name:
                width = window.Width + dx
                if width >= window.MinWidth:
                    window.Width = width
            if "top" in name:
                height = window.Height - dy
                if height >= window.MinHeight:
                    window.Top += dy
                    window.Height = height
            if "bottom" in name:
                height = window.Height + dy
                if height >= window.MinHeight:
                    window.Height = height
        except Exception:
            pass


# ---------------------------------------------------------------------------
# the easter egg
# ---------------------------------------------------------------------------


class EggWatcher(object):
    """Three slow clicks on the RevoBIM logo.

    'Slow' is the point: a run of clicks closer together than the minimum gap
    is a double click and resets the count, so the egg cannot be opened by
    accident while working.
    """

    MIN_GAP = 0.25
    MAX_GAP = 2.0

    def __init__(self, element, window=None):
        self.window = window
        self.clicks = []
        try:
            element.MouseLeftButtonUp += self._on_click
            element.Cursor = Cursors.Hand
        except Exception:
            pass

    def _on_click(self, sender, args):
        now = datetime.datetime.now()
        if self.clicks:
            gap = (now - self.clicks[-1]).total_seconds()
            if gap < self.MIN_GAP or gap > self.MAX_GAP:
                self.clicks = []
        self.clicks.append(now)
        if len(self.clicks) >= 3:
            self.clicks = []
            launch_egg(self.window)


def egg_folder():
    """Where lib\\revobim\\egg is, walked up from this file.

    The tool lives at
    <extension>\\RevoBIM PY.tab\\<panel>\\<button>\\c3d_ui.py
    and the egg at <extension>\\lib\\revobim\\egg, so the extension root is
    three folders up.  It is found rather than assumed, because a folder that
    is not on sys.path is the most likely reason an import of it fails.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    root = here
    for _step in range(5):
        root = os.path.dirname(root)
        candidate = os.path.join(root, "lib", "revobim", "egg")
        if os.path.isdir(candidate):
            return candidate, os.path.join(root, "lib")
    return None, None


def egg_report():
    """What is in the egg folder and what can be imported from it.

    Read only, and every step is written down: "the game did not start" is
    unanswerable without knowing whether the folder was found, whether it was
    on sys.path, which modules loaded and what each one offers.
    """
    lines = []
    folder, lib = egg_folder()
    lines.append(u"egg folder       {0}".format(folder or "NOT FOUND"))
    if folder is None:
        lines.append(u"looked up from   {0}".format(
            os.path.dirname(os.path.abspath(__file__))))
        return lines

    # the report imports things, so it has to do what the launcher does first
    # or it reports failures the launcher would not have had
    was_on_path = lib in sys.path
    if lib and not was_on_path:
        sys.path.insert(0, lib)
    lines.append(u"lib on sys.path  {0}{1}".format(
        was_on_path, "" if was_on_path else "   (added just now)"))
    try:
        contents = sorted(os.listdir(folder))
    except Exception as err:
        lines.append(u"could not be listed - {0}".format(err))
        return lines
    lines.append(u"it contains      {0}".format(u", ".join(contents) or "nothing"))

    for package in (os.path.join(lib, "revobim", "__init__.py"),
                    os.path.join(folder, "__init__.py")):
        lines.append(u"{0:16} {1}".format(
            os.path.basename(os.path.dirname(package)) + " package",
            "yes" if os.path.isfile(package) else "NO __init__.py - it is not "
                                                  "a package, so it cannot be imported"))

    for name in [item[:-3] for item in contents if item.endswith(".py")]:
        module_name = "revobim.egg.{0}".format(name)
        try:
            module = __import__(module_name, globals(), locals(), ["*"])
        except Exception as err:
            lines.append(u"  {0:28} would not import - {1}".format(name, err))
            continue
        callables = []
        for attribute in dir(module):
            if attribute.startswith("_"):
                continue
            try:
                if callable(getattr(module, attribute)):
                    callables.append(attribute)
            except Exception:
                continue
        lines.append(u"  {0:28} {1}".format(name, u", ".join(callables[:14]) or "nothing callable"))
    return lines


LAST_EGG_ROUTE = []


def _show_if_window(made):
    """If a call handed back a window rather than opening one, open it."""
    if made is None:
        return False
    for method in ("Show", "ShowDialog", "show"):
        function = getattr(made, method, None)
        if function is None or not callable(function):
            continue
        try:
            function()
            return True
        except Exception as err:
            core.log("the egg handed back a window that would not open: {0}".format(err))
            return False
    return False


def launch_egg(owner=None, game=None):
    """Open the shared easter egg in lib\\revobim\\egg.

    The egg's public surface is `egg_hook.attach()`, which wires a logo rather
    than opening anything, so there is no single call to make - and the entry
    point has been spelled several ways across versions.  Rather than guess
    three names and give up silently, the folder is found on disk, its `lib`
    put on sys.path if it is not there, every module in it imported, and every
    plausibly named callable tried with every plausible argument shape.

    Everything tried is written to the log, so a game that does not start says
    why instead of doing nothing.
    """
    tried = []
    folder, lib = egg_folder()
    if lib and lib not in sys.path:
        sys.path.insert(0, lib)
        tried.append(u"put {0} on sys.path".format(lib))

    module_names = ["revobim.egg.launcher", "revobim.egg", "revobim.easter_egg",
                    "revobim.egg.egg_hook", "revobim.egg.games"]
    if game:
        module_names.insert(0, "revobim.egg.{0}".format(game))
    if folder and os.path.isdir(folder):
        try:
            for item in sorted(os.listdir(folder)):
                if not item.endswith(".py") or item == "__init__.py":
                    continue
                name = "revobim.egg.{0}".format(item[:-3])
                if name not in module_names:
                    module_names.append(name)
        except Exception:
            pass

    entries = ["launch", "show", "open_egg", "run", "main", "start", "play"]
    if game:
        entries = [game, "launch_" + game, "open_" + game, "play_" + game,
                   "show_" + game, game.capitalize()] + entries

    for module_name in module_names:
        try:
            module = __import__(module_name, globals(), locals(), ["*"])
        except Exception as err:
            tried.append(u"{0}: would not import - {1}".format(module_name, err))
            continue

        # anything else in the module that names the game or looks like a
        # window class, since plenty of eggs are a class rather than a function
        candidates = list(entries)
        try:
            for attribute in dir(module):
                if attribute.startswith("_") or attribute in candidates:
                    continue
                lowered = attribute.lower()
                looks_right = (game and game in lowered) or \
                    lowered.endswith("window") or lowered.endswith("game")
                if looks_right and callable(getattr(module, attribute, None)):
                    candidates.append(attribute)
        except Exception:
            pass

        for entry in candidates:
            function = getattr(module, entry, None)
            if function is None or not callable(function):
                continue
            # WHICH ARGUMENT GOES FIRST DEPENDS ON THE NAME.
            #
            # A function already named for the game - pacman.show, or
            # launch_pacman - does not want the game's name passed to it; the
            # first argument it takes is the owner window.  Handing it "pacman"
            # as the owner succeeds and then the game has a string where its
            # window should be.  Only a generically named entry gets told which
            # game to open.
            named = game and (game in module_name.lower() or game in entry.lower())
            if not game or named:
                shapes = [(owner,), ()]
            else:
                shapes = [(owner, game), (game, owner), (game,), (owner,), ()]
            for arguments in shapes:
                try:
                    made = function(*arguments)
                    # a class or a factory hands a window back rather than
                    # putting it up, so it is shown here - otherwise the call
                    # succeeds and nothing appears, which looks identical to
                    # nothing having happened at all
                    shown = _show_if_window(made)
                    core.log(u"easter egg opened through {0}.{1} with {2} "
                             u"argument(s){3}".format(
                                 module_name, entry, len(arguments),
                                 ", and its window was shown" if shown else ""))
                    LAST_EGG_ROUTE.append(u"{0}.{1}".format(module_name, entry))
                    return True
                except TypeError as err:
                    # the wrong number of arguments, so try the next shape -
                    # but a TypeError from inside the game is not that, and
                    # would otherwise look identical
                    tried.append(u"{0}.{1}{2}: {3}".format(
                        module_name, entry, arguments and "(...)" or "()", err))
                    continue
                except Exception as err:
                    tried.append(u"{0}.{1} threw - {2}".format(module_name, entry, err))
                    break

    core.log(u"the easter egg would not start. Tried:\n  {0}".format(
        u"\n  ".join(tried) or "nothing - no module in the egg folder loaded"))
    for line in egg_report():
        core.log(u"  {0}".format(line))
    return False


# ---------------------------------------------------------------------------
# prompts
# ---------------------------------------------------------------------------


def prompt(title, lines, palette_name, confirm=False, owner=None, height=460,
           yes=None, no=None, copyable=False):
    """Themed message and confirm window.  Anything thrown here falls back to
    Revit's own dialog rather than returning a silent no - a silent False in a
    confirm step is indistinguishable from a broken button."""
    try:
        window = load_window("CalloutTo3DPrompt.xaml")
        apply_theme(window, palette_name)
        find = window.FindName
        find("PromptTitle").Text = title
        body = u"\n".join(lines)
        find("PromptBody").Text = body
        if copyable:
            # a report is only useful if it can be got out of the window, so
            # the text becomes selectable and a Copy button appears beside Close
            _make_copyable(window, body)
        find("VersionText").Text = u"v{0}".format(core.__version__)
        set_image(find("LogoImage"), "icon.png")
        EggWatcher(find("LogoZone"), window)
        Chrome(window, find("HeaderBar"), find("GripGrid"), find("ShrinkButton"))
        window.Height = height

        state = {"ok": False}

        def on_ok(sender, args):
            state["ok"] = True
            window.DialogResult = True
            window.Close()

        def on_cancel(sender, args):
            window.DialogResult = False
            window.Close()

        find("OkButton").Click += on_ok
        find("CancelButton").Click += on_cancel
        find("CloseButton").Click += on_cancel
        find("CancelButton").Visibility = _visible(confirm)
        find("OkButton").Content = yes or ("Go ahead" if confirm else "Close")
        if no:
            find("CancelButton").Content = no
        set_owner(window, owner)
        window.ShowDialog()
        return state["ok"] if confirm else True
    except Exception as err:
        core.log("themed prompt failed, falling back to Revit: {0}".format(err))
        return _revit_prompt(title, lines, confirm)


def _visible(flag):
    from System.Windows import Visibility
    return Visibility.Visible if flag else getattr(Visibility, "Collapsed")


def _revit_prompt(title, lines, confirm):
    try:
        from Autodesk.Revit.UI import TaskDialog, TaskDialogCommonButtons, TaskDialogResult
        dialog = TaskDialog(title)
        dialog.MainInstruction = title
        dialog.MainContent = u"\n".join(lines[:40])
        if confirm:
            dialog.CommonButtons = TaskDialogCommonButtons.Yes | TaskDialogCommonButtons.No
            return dialog.Show() == TaskDialogResult.Yes
        dialog.CommonButtons = TaskDialogCommonButtons.Close
        dialog.Show()
        return True
    except Exception:
        return not confirm


# ---------------------------------------------------------------------------
# small helpers used by both windows
# ---------------------------------------------------------------------------


def _make_copyable(window, text):
    """Swap the prompt's read-only text block for a selectable box, and put a
    Copy button in the footer."""
    try:
        block = window.FindName("PromptBody")
        box = TextBox()
        box.Text = text
        box.IsReadOnly = True
        box.AcceptsReturn = True
        box.TextWrapping = TextWrapping.NoWrap
        box.BorderThickness = Thickness(0)
        box.Background = None
        try:
            box.FontFamily = FontFamily("Consolas")
        except Exception:
            pass
        box.FontSize = 11.5
        try:
            box.Style = window.TryFindResource("ThemedTextBox")
        except Exception:
            pass
        parent = block.Parent
        if parent is not None and hasattr(parent, "Children"):
            index = parent.Children.IndexOf(block)
            parent.Children.RemoveAt(index)
            parent.Children.Insert(index, box)
        elif parent is not None and hasattr(parent, "Content"):
            parent.Content = box
    except Exception as err:
        core.log("the report could not be made selectable: {0}".format(err))

    try:
        footer = window.FindName("OkButton").Parent
        button = Button()
        button.Content = "Copy it all"
        button.Margin = Thickness(0, 0, 10, 0)
        try:
            button.Style = window.TryFindResource("GhostButton")
        except Exception:
            pass

        def on_copy(sender, args):
            try:
                Clipboard.SetText(text)
                sender.Content = "copied"
            except Exception as err:
                sender.Content = "the clipboard refused it"
                core.log("clipboard refused the report: {0}".format(err))

        button.Click += on_copy
        footer.Children.Insert(0, button)
    except Exception as err:
        core.log("the copy button could not be added: {0}".format(err))


def set_owner(window, owner):
    """Give a dialog its owner - and if that owner is parked as a bar at the
    bottom of the screen, centre the dialog on the screen instead.  Centred on
    a 50px bar most of it would be off the screen, and that is exactly when a
    dialog turns up unasked: a run's summary arriving while the tool is shrunk.
    """
    if owner is None:
        return
    try:
        window.Owner = owner
    except Exception:
        return
    parked = drawer_of(owner)
    try:
        if parked is not None and (parked.shrunk or parked.sliding):
            window.WindowStartupLocation = getattr(WindowStartupLocation, "CenterScreen")
        else:
            window.WindowStartupLocation = getattr(WindowStartupLocation, "CenterOwner")
    except Exception:
        pass


def own_to_revit(window, uiapp=None):
    """An unowned modeless window slips behind Revit and reads as a crash."""
    try:
        from System.Windows.Interop import WindowInteropHelper
        import System.Diagnostics as diagnostics
        handle = None
        if uiapp is not None:
            try:
                handle = uiapp.MainWindowHandle
            except Exception:
                handle = None
        if handle is None:
            handle = diagnostics.Process.GetCurrentProcess().MainWindowHandle
        helper = WindowInteropHelper(window)
        helper.Owner = handle
        return True
    except Exception as err:
        core.log("window ownership failed: {0}".format(err))
        return False


_WATCHED = {}                 # combo hash -> its blank label


def is_default(value, blank_label):
    """Whether a combo is sitting on its 'use the default' entry."""
    text = u"{0}".format(value or "").strip()
    return (not text) or text == u"{0}".format(blank_label or "").strip()


def mark_default(combo, blank_label):
    """Red outline while a combo is on its default entry; green outline and
    green bold text once something specific is picked - so a default left
    where a choice was meant can be seen from across the room."""
    from System.Windows import FontWeights
    default = is_default(combo.SelectedItem, blank_label)
    try:
        combo.BorderBrush = combo.TryFindResource("RedBrush" if default else "GreenBrush")
        combo.BorderThickness = Thickness(1.6)
        if default:
            combo.ClearValue(combo.ForegroundProperty)
            combo.FontWeight = FontWeights.Normal
        else:
            combo.Foreground = combo.TryFindResource("GreenBrush")
            combo.FontWeight = FontWeights.Bold
    except Exception as err:
        core.log(u"default marking failed: {0}".format(err))


def watch_default(combo, blank_label):
    """Keep a combo marked as its selection changes.  Hooked once per combo,
    however many times it is refilled."""
    key = combo.GetHashCode()
    first = key not in _WATCHED
    _WATCHED[key] = blank_label
    if first:
        def handler(sender, args):
            mark_default(sender, _WATCHED.get(sender.GetHashCode(), blank_label))
        combo.SelectionChanged += handler
    mark_default(combo, blank_label)


def fill_combo(combo, values, selected=None, blank_label=None):
    """Rebuild a combo box's items without touching its selection handler.
    A combo with a blank 'default' entry is marked red or green."""
    if blank_label is not None:
        try:
            _fill(combo, values, selected, blank_label)
        finally:
            try:
                watch_default(combo, blank_label)
            except Exception:
                pass
        return
    _fill(combo, values, selected, blank_label)


def _fill(combo, values, selected=None, blank_label=None):
    try:
        combo.Items.Clear()
        items = list(values)
        if blank_label is not None:
            items.insert(0, blank_label)
        for value in items:
            combo.Items.Add(value)
        if selected is not None:
            for index, value in enumerate(items):
                if u"{0}".format(value).strip().lower() == u"{0}".format(selected).strip().lower():
                    combo.SelectedIndex = index
                    return
        if combo.Items.Count:
            combo.SelectedIndex = 0
    except Exception:
        pass


def combo_value(combo, blank_label=None):
    try:
        value = combo.SelectedItem
        if value is None:
            return ""
        text = u"{0}".format(value)
        if blank_label is not None and text == blank_label:
            return ""
        return text
    except Exception:
        return ""
