# -*- coding: utf-8 -*-

"""Legend Creator - shrink to the taskbar.

The house drawer: slides a window down to the bottom of its screen, leaving
its header bar floating, and back. WPF is only touched inside functions, so
the bench drives the real class against a stand-in window.
"""

import time

from lgc_core import log, swallowed


# ---------------------------------------------------------------------------
# Shrink to the taskbar - the drawer every window in this tool carries
# ---------------------------------------------------------------------------
# House pattern, as in Pro Sheets, Filter Manager and View Manager: Top and
# Height eased together on a short DispatcherTimer rather than a Storyboard,
# which on a borderless window fights the layout pass and holds its end
# value over every later assignment.
DRAWER_SECONDS = 0.28


DRAWER_TICK_MS = 15


DRAWER_MARGIN = 8.0        # px between a parked bar and the taskbar


DRAWER_GAP = 4.0           # px between bars parked one above another


SHRUNK = 'shrunk'          # the button's Tag while parked - the style swaps


                           # its glyph for the green up arrow on this value
SHRINK_TIP = u'Shrink to the taskbar (Ctrl+Shift+H)'


EXPAND_TIP = u'Open the window again (Ctrl+Shift+H, Enter or double-click)'


_PARKED = []               # drawers whose windows are parked, oldest first


def ease_out(progress):
    """Ease-out cubic, clamped to 0..1: quick away, gentle landing."""
    if progress <= 0.0:
        return 0.0
    if progress >= 1.0:
        return 1.0
    return 1.0 - (1.0 - progress) ** 3


def free_slot(taken):
    """The lowest slot no parked bar is using. Counting the parked bars was
    not enough: reopen the bottom one while the one above stays parked, shrink
    it again, and a count of one sent it into the slot already occupied."""
    slot = 0
    while slot in taken:
        slot += 1
    return slot


def parked_top(area_top, area_height, bar, slot=0, margin=DRAWER_MARGIN,
               gap=DRAWER_GAP):
    """Top edge of a parked bar: the bottom of the working area less the
    margin, stacked above any bars already parked there.

    Measured from the area's own top, so a monitor above the primary one -
    whose working area has a negative top - parks the bar on itself, not on
    the primary screen.
    """
    return area_top + area_height - margin - bar - slot * (bar + gap)


def reopen_rect(saved_left, saved_top, saved_height, bar_left, bar_top, bar,
                moved, area_top, area_height):
    """(left, top, height) to open a parked window back to.

    Left where it was, it goes straight back where it came from. Carried
    somewhere else, it opens upward from where the bar now sits - its bottom
    edge stays put - at the bar's left, kept inside the working area, rather
    than jumping back to a place the user has already moved on from.
    """
    if not moved:
        return saved_left, saved_top, saved_height
    height = min(saved_height, area_height)
    top = bar_top + bar - height
    top = max(area_top, min(top, area_top + area_height - height))
    return bar_left, top, height


class _DrawerUI(object):
    """The handful of WPF values the drawer needs, looked up once."""


_DRAWER_UI = {}


def _drawer_ui():
    if 'ui' in _DRAWER_UI:
        return _DRAWER_UI['ui']
    from System.Windows import (CornerRadius, SizeToContent,
                                VerticalAlignment, Visibility)
    from System.Windows.Input import Key, Keyboard, ModifierKeys
    ui = _DrawerUI()
    ui.collapsed = Visibility.Collapsed
    ui.top = VerticalAlignment.Top
    ui.manual = SizeToContent.Manual
    ui.nan = float('nan')
    ui.corner = lambda radius: CornerRadius(radius)
    ui.key_h = Key.H
    ui.key_enter = Key.Return
    ui.key_escape = Key.Escape
    both = ModifierKeys.Control | ModifierKeys.Shift
    ui.ctrl_shift = lambda: (Keyboard.Modifiers & both) == both
    _DRAWER_UI['ui'] = ui
    return ui


def _wpf_timer(milliseconds, callback):
    from System import TimeSpan
    from System.Windows.Threading import DispatcherTimer
    timer = DispatcherTimer()
    timer.Interval = TimeSpan.FromMilliseconds(milliseconds)
    timer.Tick += callback
    return timer


def screen_work_area(window):
    """(left, top, width, height) of the working area of the screen the
    window is on, in WPF units - the taskbar left out, DPI allowed for.
    Falls back to the primary screen if the window's own cannot be read."""
    try:
        from System.Windows import PresentationSource
        from System.Windows.Forms import Screen
        from System.Windows.Interop import WindowInteropHelper
        handle = WindowInteropHelper(window).Handle
        area = Screen.FromHandle(handle).WorkingArea
        scale = PresentationSource.FromVisual(window)\
            .CompositionTarget.TransformFromDevice
        return (area.Left * scale.M11, area.Top * scale.M22,
                area.Width * scale.M11, area.Height * scale.M22)
    except Exception:
        swallowed()
    from System.Windows import SystemParameters
    area = SystemParameters.WorkArea
    return (area.Left, area.Top, area.Width, area.Height)


class WindowDrawer(object):
    """Slides a window down to the bottom of its screen like a drawer
    closing, leaving only its header bar floating clear of the taskbar, and
    back again. One per window; the window binds its own button to toggle()
    and starts drag_window with header_down().

    The clock, timer, work area and WPF values can be handed in, so the
    bench can drive this exact class against a stand-in window.
    """

    def __init__(self, window, header, button, clock=None,
                 timer_factory=None, area=None, ui=None):
        self.window = window
        self.header = header
        self.button = button
        self.root = window.Content
        self.ui = ui or _drawer_ui()
        self._clock = clock or time.time
        self._make_timer = timer_factory or _wpf_timer
        self._area = area or screen_work_area
        self.parked = False
        self.sliding = False
        self.saved = None
        self.parked_at = None
        self.slot = None
        self.hidden = []
        self._timer = None
        self._done = None
        self._label()
        try:
            window.PreviewKeyDown += self._on_key
        except Exception:
            swallowed()
        try:
            window.Closed += self._on_closed
        except Exception:
            swallowed()

    # -- the gestures --------------------------------------------------------
    def toggle(self):
        if self.sliding:
            return
        if self.parked:
            self.expand()
        else:
            self.shrink()

    def header_down(self, args):
        """True when a header click belonged to the drawer: a double click on
        a parked bar opens it. A single click is left to drag the bar."""
        if self.parked and getattr(args, 'ClickCount', 1) >= 2:
            self.expand()
            return True
        return False

    def intercept(self):
        """For a window's default and cancel buttons: while parked, Enter or
        Escape reopens the window instead of reaching a button nobody can
        see. Returns True when it took the key."""
        if self.parked:
            self.expand()
            return True
        return self.sliding

    # -- shrinking -----------------------------------------------------------
    def shrink(self):
        if self.parked or self.sliding:
            return
        window, root = self.window, self.root
        height = window.ActualHeight if window.ActualHeight > 0 \
            else window.Height
        edge = root.BorderThickness
        bar = self.header.ActualHeight + edge.Top + edge.Bottom
        area = self._area(window)
        slot = free_slot(set(d.slot for d in _PARKED if d is not self))
        self.slot = slot
        target = parked_top(area[1], area[3], bar, slot)

        self.saved = {
            'left': window.Left, 'top': window.Top, 'height': height,
            'min_height': window.MinHeight,
            'size_to_content': window.SizeToContent,
            'root_height': root.Height,
            'root_align': root.VerticalAlignment,
            'root_full': root.ActualHeight,
            'corner': self.header.CornerRadius, 'bar': bar,
        }
        # MinHeight and SizeToContent both veto a shrinking Height, and a
        # vetoed slide leaves the window half shut.
        window.SizeToContent = self.ui.manual
        window.MinHeight = 0
        # Pin the body at its full height so it is drawn away under the
        # header, not squashed and re-laid-out on every frame.
        root.Height = self.saved['root_full']
        root.VerticalAlignment = self.ui.top
        self.parked_at = (window.Left, target)
        log(u'drawer: shrinking {0:.0f}px high to a {1:.0f}px bar at '
            u'top {2:.0f} (slot {3})'.format(height, bar, target, slot))
        self._slide(window.Top, height, target, bar, self._landed)

    def _landed(self):
        # Only now, with the bar down, is the body put away: everything
        # beside the header goes, the resize grips with it, so the bar is not
        # lined with invisible handles that swallow the click on the arrow.
        self.hidden = []
        for child in list(self.header.Parent.Children):
            if child is self.header:
                continue
            self.hidden.append((child, child.Visibility))
            child.Visibility = self.ui.collapsed
        self.root.Height = self.ui.nan
        self.header.CornerRadius = self.ui.corner(5)
        self.parked = True
        if self not in _PARKED:
            _PARKED.append(self)
        self._label()

    # -- opening -------------------------------------------------------------
    def expand(self):
        if not self.parked or self.sliding:
            return
        window, saved = self.window, self.saved
        moved = abs(window.Left - self.parked_at[0]) > 1.0 or \
            abs(window.Top - self.parked_at[1]) > 1.0
        area = self._area(window)
        left, top, height = reopen_rect(
            saved['left'], saved['top'], saved['height'], window.Left,
            window.Top, saved['bar'], moved, area[1], area[3])

        # Body back before the slide, previous visibility and all - a panel
        # that was already hidden stays hidden.
        for child, visibility in self.hidden:
            child.Visibility = visibility
        self.hidden = []
        self.header.CornerRadius = saved['corner']
        self.root.Height = saved['root_full']
        self.root.VerticalAlignment = self.ui.top
        self.parked = False
        if self in _PARKED:
            _PARKED.remove(self)
        self._label()

        window.Left = left
        log(u'drawer: opening to top {0:.0f}, {1:.0f}px high{2}'.format(
            top, height, u' (bar was moved)' if moved else u''))
        self._slide(window.Top, saved['bar'], top, height, self._opened)

    def _opened(self):
        window, saved = self.window, self.saved
        self.root.Height = saved['root_height']
        self.root.VerticalAlignment = saved['root_align']
        window.MinHeight = saved['min_height']
        window.SizeToContent = saved['size_to_content']
        self.saved = None
        try:
            window.Activate()
        except Exception:
            swallowed()

    # -- the slide -----------------------------------------------------------
    def _slide(self, top0, height0, top1, height1, done):
        self.sliding = True
        self._from = (top0, height0)
        self._to = (top1, height1)
        self._done = done
        self._t0 = self._clock()
        try:
            self._timer = self._make_timer(DRAWER_TICK_MS, self._tick)
            self._timer.Start()
        except Exception:
            swallowed()
            self._finish()          # no timer: land at the end state now

    def _tick(self, sender=None, args=None):
        if not self.sliding:
            return
        try:
            progress = ease_out((self._clock() - self._t0) / DRAWER_SECONDS)
            self.window.Top = self._from[0] + \
                (self._to[0] - self._from[0]) * progress
            self.window.Height = self._from[1] + \
                (self._to[1] - self._from[1]) * progress
            if progress >= 1.0:
                self._finish()
        except Exception:
            swallowed()
            self._finish()          # a frame that throws lands at the end

    def _finish(self):
        """Stop the timer and write the end state straight onto the window.

        The timer stop and the final assignment are guarded separately: this
        is also the fallback when the slide could not start at all, and one
        failing must not stop the other.
        """
        timer, self._timer = self._timer, None
        if timer is not None:
            try:
                timer.Stop()
            except Exception:
                swallowed()
        try:
            self.window.Top = self._to[0]
            self.window.Height = self._to[1]
        except Exception:
            swallowed()
        self.sliding = False
        done, self._done = self._done, None
        if done is not None:
            try:
                done()
            except Exception:
                swallowed()

    # -- housekeeping --------------------------------------------------------
    def _label(self):
        try:
            self.button.Tag = SHRUNK if self.parked else None
            self.button.ToolTip = EXPAND_TIP if self.parked else SHRINK_TIP
        except Exception:
            swallowed()

    def _on_key(self, sender, args):
        try:
            key = args.Key
            if key == self.ui.key_h and self.ui.ctrl_shift():
                self.toggle()
                args.Handled = True
            elif self.parked and key in (self.ui.key_enter,
                                         self.ui.key_escape):
                self.expand()
                args.Handled = True
        except Exception:
            swallowed()

    def _on_closed(self, sender, args):
        timer, self._timer = self._timer, None
        if timer is not None:
            try:
                timer.Stop()
            except Exception:
                swallowed()
        if self in _PARKED:
            _PARKED.remove(self)


class NullDrawer(object):
    """Stands in when a window's drawer cannot be built, so the window still
    opens - a shrink button is a convenience and must never cost the tool."""
    parked = False
    sliding = False

    def toggle(self):
        pass

    def header_down(self, args):
        return False

    def intercept(self):
        return False


def make_drawer(window):
    """A drawer for a window, or a NullDrawer and a hidden button if the
    drawer cannot be built on this machine."""
    try:
        return WindowDrawer(window, window.header_bar, window.shrink_btn)
    except Exception:
        swallowed()
        try:
            from System.Windows import Visibility
            window.shrink_btn.Visibility = Visibility.Collapsed
        except Exception:
            swallowed()
        return NullDrawer()
