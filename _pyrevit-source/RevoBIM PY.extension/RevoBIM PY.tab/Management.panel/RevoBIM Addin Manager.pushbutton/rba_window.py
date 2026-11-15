# -*- coding: utf-8 -*-
u"""RevoBIM Addin Manager - the floating window, snap docked or free.

Used whenever Revit will not hand back the dockable pane: the startup block was
not pasted, Revit was not restarted since, or it ran and found no host it could
use. The footer says which, from the startup log (`rba_dock.docking_status`).

**It still docks.** The dock buttons in the header snap the window to the left
or right edge of Revit's drawing area, full height, and it follows Revit when
Revit is moved or resized. Dragging it by its header lifts it off again. The
side is the same `dock` setting the real pane uses, so whichever route a
session takes it comes up on the same side.

**It shrinks to the taskbar** like every RevoBIM window (`rba_drawer`), and the
pane's own header is the bar that is left floating - there is no title strip of
the window's own.

A modeless window needs all of: `__persistentengine__ = True` in the loader,
the window owned to Revit's main window, and the window parked somewhere it
outlives the command. Here that somewhere is the **AppDomain**, as a `present`
action under a version-stamped key: a second press of the ribbon button - even
from a fresh engine after a pyRevit reload - finds the open window and brings
it back instead of opening a second copy, and an upgrade never talks to a
window left over from the old version.
"""

import rba_clr  # noqa: F401

import os

from System import Action, AppDomain, Object, TimeSpan
from System.Windows import (SystemParameters, WindowStartupLocation, CornerRadius,
                            Visibility)
from System.Windows.Input import Cursors, Key, MouseButtonState
from System.Windows.Threading import DispatcherTimer

import rba_core
import rba_drawer
import rba_launch
import rba_theme
import rba_ui

from rba_core import to_text, log, log_exception

PRESENT_KEY = u"RevoBIM.AddinManager.window.present." + rba_core.__version__
ALIVE_NOTE = u"revobim_addins_modeless.txt"
SNAP_MS = 500
LIFT_PX = 6          # a docked window lifts off once dragged this far


# ----------------------------------------------------------------------
# the dead-engine check
# ----------------------------------------------------------------------

def note_path():
    return os.path.join(rba_core.appdata_root(), ALIVE_NOTE)


def write_alive_note():
    u"""Record that a modeless window was opened.

    Where the engine is not kept alive the window opens and every handler in it
    is dead - on screen, responding to nothing, and nothing inside it can say
    so. The first handler that runs clears this note, so a note still there at
    the next launch means the last window never came alive.
    """
    try:
        rba_core.ensure_root()
        handle = open(note_path(), u"wb")
        try:
            handle.write((u"opened v" + rba_core.__version__).encode(u"utf-8"))
        finally:
            handle.close()
    except Exception:
        pass


def clear_alive_note():
    try:
        if os.path.isfile(note_path()):
            os.remove(note_path())
    except Exception:
        pass


def check_alive_note():
    try:
        if os.path.isfile(note_path()):
            log(u"WARNING: the last modeless window never ran a handler - the "
                u"engine was probably torn down. Check __persistentengine__.")
            clear_alive_note()
            return True
    except Exception:
        pass
    return False


# ----------------------------------------------------------------------
# the entry point
# ----------------------------------------------------------------------

def show(build_pane, status=None):
    u"""Open the window, or bring back the one already open.  (ok, message)."""
    present = None
    try:
        present = AppDomain.CurrentDomain.GetData(PRESENT_KEY)
    except Exception:
        present = None
    if present is not None:
        try:
            present.Invoke()
            return True, u""
        except Exception:
            # The window it belonged to has gone without saying so.
            _clear_present()

    check_alive_note()
    try:
        host = FloatingHost(build_pane(), status)
        host.open()
        return True, u""
    except Exception:
        log_exception(u"window/show")
        _clear_present()
        return False, (u"The RevoBIM Addin Manager window would not open - see "
                       u"%APPDATA%\\RevoBIM\\revobim_addins_debug.txt")


def _clear_present():
    try:
        AppDomain.CurrentDomain.SetData(PRESENT_KEY, None)
    except Exception:
        pass


# ----------------------------------------------------------------------
# the host
# ----------------------------------------------------------------------

class FloatingHost(object):

    def __init__(self, pane, status):
        self.pane = pane
        self.status = status
        self.window = rba_ui.load_xaml(u"RbaWindow.xaml")
        self.full = False
        self.full_bounds = None
        self.side = None
        self.dragging = False
        self.press = None            # where a docked header was pressed
        self.last_snap = None
        self.area_warned = set()
        self.drawer = None
        self.snap_timer = None
        self._present = None

    # ------------------------------------------------------------ build

    def open(self):
        window = self.window
        pane = self.pane
        rba_theme.apply(window, pane.theme_name)
        pane.theme_listeners.append(self._on_theme)

        window.FindName(u"Host").Content = pane.control
        find = pane.find
        find(u"WindowControls").Visibility = Visibility.Visible
        header = find(u"Header")
        header.Tag = u"round"
        header.CornerRadius = CornerRadius(6, 6, 0, 0)

        if self.status is not None:
            code, short, detail = self.status
            pane.set_status(short)
            pane.status_text.ToolTip = detail
            log(u"floating: {0} - {1}".format(code, detail))

        self.drawer = rba_drawer.attach(
            window, header,
            (find(u"ShrinkBtn"), find(u"ShrinkGlyph"), find(u"ExpandGlyph")),
            grips=window.FindName(u"Grips"), name=u"Addin Manager")
        pane.host_window = window
        pane.host_drawer = self.drawer

        self._wire()
        self._place()
        rba_ui.own(window)

        self._present = Action(self.present)
        AppDomain.CurrentDomain.SetData(PRESENT_KEY, self._present)
        write_alive_note()
        window.Show()
        if self.side:
            self.snap()
        log(u"floating window opened, dock={0}".format(self.side or u"free"))

    def _place(self):
        u"""The last free position if it is still on a screen, else centred."""
        window = self.window
        settings = self.pane.settings
        window.Width = max(window.MinWidth, rba_core.as_int(settings, u"win_w", 380))
        window.Height = max(window.MinHeight, rba_core.as_int(settings, u"win_h", 900))
        side = to_text(settings.get(u"dock", u"left")).strip().lower()
        self.side = side if side in rba_core.DOCK_SIDES else None
        left = settings.get(u"win_left", u"")
        top = settings.get(u"win_top", u"")
        try:
            left, top = float(left), float(top)
            on_screen = (SystemParameters.VirtualScreenLeft - 50 <= left
                         <= SystemParameters.VirtualScreenLeft
                         + SystemParameters.VirtualScreenWidth - 100
                         and SystemParameters.VirtualScreenTop - 10 <= top
                         <= SystemParameters.VirtualScreenTop
                         + SystemParameters.VirtualScreenHeight - 60)
        except Exception:
            on_screen = False
        if on_screen:
            window.WindowStartupLocation = WindowStartupLocation.Manual
            window.Left, window.Top = left, top
        else:
            window.WindowStartupLocation = WindowStartupLocation.CenterScreen
        self._paint_dock_buttons()

    def _wire(self):
        window = self.window
        find = self.pane.find

        # The name is the biggest part of the header, so it stays a drag
        # handle. The easter egg counts on the tunnelling preview event,
        # which fires before the drag starts, so it loses nothing.
        find(u"Header").MouseLeftButtonDown += self.on_header_down
        find(u"Header").MouseMove += self.on_header_move
        find(u"Header").MouseLeftButtonUp += self.on_header_up
        find(u"CloseBtn").Click += self.on_close
        find(u"FullBtn").Click += self.on_full
        find(u"DockLeftBtn").Click += self.on_dock_left
        find(u"DockRightBtn").Click += self.on_dock_right
        window.KeyDown += self.on_key
        window.Activated += self.on_alive
        window.Closing += self.on_closing
        window.Closed += self.on_closed

        grips = (
            (u"GripL", Cursors.SizeWE, -1, 0),
            (u"GripR", Cursors.SizeWE, 1, 0),
            (u"GripT", Cursors.SizeNS, 0, -1),
            (u"GripB", Cursors.SizeNS, 0, 1),
            (u"GripTL", Cursors.SizeNWSE, -1, -1),
            (u"GripTR", Cursors.SizeNESW, 1, -1),
            (u"GripBL", Cursors.SizeNESW, -1, 1),
            (u"GripBR", Cursors.SizeNWSE, 1, 1),
        )
        for name, cursor, dx, dy in grips:
            thumb = window.FindName(name)
            if thumb is not None:
                thumb.Cursor = cursor
                thumb.DragDelta += self._dragger(dx, dy)

        self.snap_timer = DispatcherTimer()
        self.snap_timer.Interval = TimeSpan.FromMilliseconds(SNAP_MS)
        self.snap_timer.Tick += self.on_snap_tick
        self.snap_timer.Start()

    # ------------------------------------------------------------ present

    def present(self):
        u"""What a second press of the ribbon button does."""
        if self.drawer is not None and self.drawer.shrunk:
            self.drawer.expand()
        else:
            self.window.Activate()

    def _on_theme(self, name):
        rba_theme.apply(self.window, name)

    def on_alive(self, sender, args):
        clear_alive_note()

    # ------------------------------------------------------------ header

    def on_header_down(self, sender, args):
        clear_alive_note()
        try:
            if args.ClickCount == 2:
                if not self.drawer.on_header_double_click():
                    self.toggle_full()
                return
        except Exception:
            pass
        if self.drawer.sliding:
            return
        if self.side and not self.drawer.shrunk:
            # Docked: a click is only a click. The window lifts off when the
            # mouse actually moves with the button held (on_header_move).
            try:
                self.press = args.GetPosition(self.window)
                # Captured, so a quick flick that leaves the header before
                # the lift-off distance still arrives here.
                sender.CaptureMouse()
            except Exception:
                self.press = None
            return
        if self.full and not self.drawer.shrunk:
            self.leave_full()
        self._drag()

    def on_header_move(self, sender, args):
        if self.press is None:
            return
        try:
            if args.LeftButton != MouseButtonState.Pressed:
                self.press = None
                return
            here = args.GetPosition(self.window)
            if (abs(here.X - self.press.X) < LIFT_PX
                    and abs(here.Y - self.press.Y) < LIFT_PX):
                return
        except Exception:
            self.press = None
            return
        self.press = None
        self._release(sender)
        # Lifted off: same size, free, still under the cursor.
        self.set_side(None, restore=False)
        self._drag()

    def on_header_up(self, sender, args):
        self.press = None
        self._release(sender)

    @staticmethod
    def _release(element):
        try:
            element.ReleaseMouseCapture()
        except Exception:
            pass

    def _drag(self):
        self.dragging = True
        try:
            self.window.DragMove()
        except Exception:
            pass
        self.dragging = False

    def on_key(self, sender, args):
        clear_alive_note()
        try:
            if args.Key == Key.F11:
                self.toggle_full()
                args.Handled = True
        except Exception:
            pass

    def on_close(self, sender, args):
        try:
            self.window.Close()
        except Exception:
            pass

    # ------------------------------------------------------------ full screen

    def on_full(self, sender, args):
        clear_alive_note()
        if self.drawer.shrunk:
            self.drawer.expand()
            return
        self.toggle_full()

    def toggle_full(self):
        u"""Full screen by bounds, not WindowState.Maximized.

        Maximising a borderless AllowsTransparency window the normal way covers
        the task bar and lands on the primary monitor rather than the one the
        window is on.
        """
        if self.drawer.shrunk or self.drawer.sliding:
            return
        if self.full:
            self.leave_full()
            return
        area = rba_ui.work_area(self.window)
        if area is None:
            return
        window = self.window
        self.full_bounds = (window.Left, window.Top, window.Width, window.Height)
        window.Left, window.Top, window.Width, window.Height = area
        self.full = True

    def leave_full(self):
        if not self.full:
            return
        window = self.window
        if self.full_bounds is not None:
            window.Left, window.Top, window.Width, window.Height = self.full_bounds
        self.full = False
        self.full_bounds = None

    # ------------------------------------------------------------ resize

    def _dragger(self, dx, dy):
        window = self.window

        def handler(sender, args):
            if self.drawer.shrunk or self.drawer.sliding:
                return
            # Dragging an edge counts as leaving full screen, at the size it
            # is now rather than snapping back.
            self.full = False
            self.full_bounds = None
            try:
                if dx < 0:
                    width = window.Width - args.HorizontalChange
                    if width >= window.MinWidth:
                        window.Left = window.Left + args.HorizontalChange
                        window.Width = width
                elif dx > 0:
                    width = window.Width + args.HorizontalChange
                    if width >= window.MinWidth:
                        window.Width = width
                if self.side:
                    # Docked, only the width is the user's to change.
                    self.snap()
                    return
                if dy < 0:
                    height = window.Height - args.VerticalChange
                    if height >= window.MinHeight:
                        window.Top = window.Top + args.VerticalChange
                        window.Height = height
                elif dy > 0:
                    height = window.Height + args.VerticalChange
                    if height >= window.MinHeight:
                        window.Height = height
            except Exception:
                pass

        return handler

    # ------------------------------------------------------------ docking

    def on_dock_left(self, sender, args):
        self.set_side(None if self.side == u"left" else u"left")

    def on_dock_right(self, sender, args):
        self.set_side(None if self.side == u"right" else u"right")

    def set_side(self, side, restore=True):
        u"""Dock to a side, or float again.

        Docking remembers the free position first, so pressing the same dock
        button again puts the window back where it floated. Lifting it off by
        dragging keeps it under the cursor instead.
        """
        if self.drawer.shrunk:
            self.drawer.expand(instant=True)
        self.leave_full()
        window = self.window
        if side and not self.side:
            self._remember_free()
        previous = self.side
        self.side = side
        self.last_snap = None
        if side:
            self.snap()
        elif previous and restore:
            settings = self.pane.settings
            try:
                window.Height = max(window.MinHeight,
                                    rba_core.as_int(settings, u"win_h", 900))
                window.Left = float(settings.get(u"win_left", window.Left))
                window.Top = float(settings.get(u"win_top", window.Top))
            except Exception:
                pass
        self.pane.settings[u"dock"] = side or u"floating"
        self.pane.save_settings()
        self._paint_dock_buttons()
        log(u"dock: {0}".format(side or u"free"))

    def _paint_dock_buttons(self):
        find = self.pane.find
        for name, side in ((u"DockLeftBtn", u"left"), (u"DockRightBtn", u"right")):
            try:
                button = find(name)
                button.Tag = u"on" if self.side == side else None
                button.ToolTip = (u"Float the window again" if self.side == side else
                                  u"Dock to the {0} of Revit's view".format(side))
            except Exception:
                pass

    def revit_area(self):
        u"""Revit's drawing area in WPF units, or None.

        DrawingAreaExtents is the region the views sit in, inside Revit's own
        docked browsers, so a snapped window sits beside them rather than over
        the ribbon. Read outside an API context it can throw on some releases;
        then the whole Revit window is tried, then the window's own screen.
        """
        uiapp = rba_launch.get_uiapp()
        scale_x, scale_y = rba_ui.dip_scale(self.window)
        for name in (u"DrawingAreaExtents", u"MainWindowExtents"):
            try:
                rect = getattr(uiapp, name)
                width = rect.Right - rect.Left
                height = rect.Bottom - rect.Top
                if width > 100 and height > 100:
                    return (rect.Left / scale_x, rect.Top / scale_y,
                            width / scale_x, height / scale_y)
            except Exception:
                # Once per property: this runs every half second while docked.
                if name not in self.area_warned:
                    self.area_warned.add(name)
                    log_exception(u"dock/{0}".format(name))
        if u"screen" not in self.area_warned:
            self.area_warned.add(u"screen")
            log(u"dock: Revit would not report its window, using the screen")
        return rba_ui.work_area(self.window)

    def snap(self):
        if not self.side or self.drawer.shrunk or self.drawer.sliding:
            return
        target = self.revit_area()
        if target is None:
            return
        window = self.window
        rect = rba_core.dock_rect(target, window.Width, self.side, window.MinWidth)
        current = (window.Left, window.Top, window.Width, window.Height)
        if rba_core.rect_differs(current, rect):
            window.Left, window.Top, window.Width, window.Height = rect
        self.last_snap = rect

    def on_snap_tick(self, sender, args):
        u"""Follow Revit when it moves or resizes."""
        if self.side and not self.dragging and not self.full:
            try:
                self.snap()
            except Exception:
                log_exception(u"dock/tick")

    # ------------------------------------------------------------ closing

    def _remember_free(self):
        left, top, width, height = self.drawer.true_bounds()
        settings = self.pane.settings
        settings[u"win_left"] = to_text(int(left))
        settings[u"win_top"] = to_text(int(top))
        settings[u"win_w"] = to_text(int(width))
        settings[u"win_h"] = to_text(int(height))

    def on_closing(self, sender, args):
        u"""Save the true size - never a parked bar's, never full screen's."""
        clear_alive_note()
        try:
            if self.full:
                self.leave_full()
            if self.side:
                left, top, width, height = self.drawer.true_bounds()
                self.pane.settings[u"win_w"] = to_text(int(width))
            else:
                self._remember_free()
            self.pane.save_settings()
        except Exception:
            log_exception(u"window/closing")

    def on_closed(self, sender, args):
        try:
            self.snap_timer.Stop()
        except Exception:
            pass
        try:
            self.pane.stop()
        except Exception:
            pass
        try:
            if Object.ReferenceEquals(AppDomain.CurrentDomain.GetData(PRESENT_KEY),
                                      self._present):
                _clear_present()
        except Exception:
            _clear_present()
        log(u"floating window closed")
