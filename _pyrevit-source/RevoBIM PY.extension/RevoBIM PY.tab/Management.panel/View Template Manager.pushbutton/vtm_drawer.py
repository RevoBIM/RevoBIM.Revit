# -*- coding: utf-8 -*-
"""RevoBIM PY - View Template Manager: shrink to the taskbar.

Every window the tool opens carries a shrink button top right. Pressing it
slides the window down to the bottom of its screen like a drawer closing,
leaving only its header bar floating there, so Revit can be seen. The button
becomes a green up arrow; pressing it - or double-clicking the bar, or
Escape / Enter / F11, or Ctrl+Shift+H - slides the window back.

The slide is Top and Height eased together on a DispatcherTimer rather than a
Storyboard: an animation holds its end value and outranks every later plain
assignment, which leaves a window that can never be moved or resized again
with nothing raised to say so. A timer only ever writes plain values.

The parking and reopening arithmetic is plain functions at the top of this
file, proved by bench_logic.py - including a second monitor *above* the
primary, where a negative working-area top is what sends a bar to the wrong
screen.
"""

import time

import vtm_clr  # noqa: F401  - assemblies first, always

from System import Double, TimeSpan
from System.Windows import (CornerRadius, Point, PresentationSource,
                            SizeToContent, SystemParameters, Thickness,
                            VerticalAlignment, Visibility)
from System.Windows.Forms import Screen
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Threading import DispatcherTimer

DURATION = 0.28      # seconds for one slide
TICK_MS = 15         # frame interval
MARGIN = 8.0         # gap between a parked bar and the bottom of the screen
GAP = 4.0            # gap between stacked bars
MOVED = 2.0          # a bar dragged further than this opens where it now is
SHRUNK = "shrunk"    # the button's Tag while parked - Theme.xaml swaps the glyph

TIP_SHRINK = "Shrink to the taskbar so Revit can be seen (Ctrl+Shift+H)"
TIP_EXPAND = "Open the window again (Ctrl+Shift+H, Enter or Escape)"

_LIVE = []


# --------------------------------------------------------------------------
# the arithmetic - plain functions
# --------------------------------------------------------------------------


def ease_out(progress):
    """Ease-out cubic: fast away, settling gently. Clamped to 0..1."""
    p = max(0.0, min(1.0, float(progress)))
    return 1.0 - (1.0 - p) ** 3


def lerp(start, end, t):
    return start + (end - start) * t


def clamp(value, low, high):
    """value kept inside low..high; low wins when the range is inverted (a
    window wider than the screen sits at its left edge)."""
    if high < low:
        return low
    return max(low, min(high, value))


def parked_top(area, bar, stacked=(), margin=MARGIN, gap=GAP):
    """Top of a bar parked at the bottom of a working area (left, top, width,
    height), above any bars already parked there. The area's own top is
    included - on a monitor above the primary it is negative."""
    _left, top, _width, height = area
    y = top + height - margin - bar
    for other in stacked:
        y -= other + gap
    return y


def expanded_rect(saved, bar_pos, parked_pos, area, tolerance=MOVED):
    """Where the window opens to, as (left, top, width, height).

    Left where it was parked: exactly where it came from. Dragged somewhere
    else: the header stays where the bar now is and the window opens from
    there, kept on that screen - never a jump back to a place the user has
    already moved on from."""
    s_left, s_top, s_width, s_height = saved
    b_left, b_top = bar_pos
    p_left, p_top = parked_pos
    if abs(b_left - p_left) <= tolerance and abs(b_top - p_top) <= tolerance:
        return (s_left, s_top, s_width, s_height)
    a_left, a_top, a_width, a_height = area
    left = clamp(b_left, a_left, a_left + a_width - s_width)
    top = clamp(b_top, a_top, a_top + a_height - s_height)
    return (left, top, s_width, s_height)


def key_action(key, ctrl, shift, shrunk, sliding):
    """What a key press means to the drawer: 'toggle', 'expand', 'swallow'
    (the body is hidden, so nothing else should act on it), or None."""
    if ctrl and shift and key == "H":
        return "toggle"
    if sliding:
        return "swallow"
    if shrunk:
        if key in ("Escape", "Enter", "Return", "F11"):
            return "expand"
        return "swallow"
    return None


# --------------------------------------------------------------------------
# screens
# --------------------------------------------------------------------------


def dpi_scale(window):
    try:
        source = PresentationSource.FromVisual(window)
        matrix = source.CompositionTarget.TransformToDevice
        return (matrix.M11 or 1.0, matrix.M22 or 1.0)
    except Exception:
        return (1.0, 1.0)


def work_area(window):
    """The working area of the screen the window is on, in WPF units.
    SystemParameters.WorkArea is the *primary* screen - last resort only."""
    try:
        handle = WindowInteropHelper(window).Handle
        bounds = Screen.FromHandle(handle).WorkingArea
        scale_x, scale_y = dpi_scale(window)
        return (bounds.Left / scale_x, bounds.Top / scale_y,
                bounds.Width / scale_x, bounds.Height / scale_y)
    except Exception:
        area = SystemParameters.WorkArea
        return (area.Left, area.Top, area.Width, area.Height)


def drawer_of(window):
    if window is None:
        return None
    for drawer in _LIVE:
        if drawer.window is window:
            return drawer
    return None


# --------------------------------------------------------------------------
# the drawer
# --------------------------------------------------------------------------


class Drawer(object):
    """Shrink and expand one borderless window.

    window   the Window
    header   its header Border; every sibling of it is hidden while parked
    button   the shrink button, wired here
    grips    the resize-grip overlay, parked with the window so it cannot
             line the bar with invisible handles and swallow the arrow's click
    before   called before a shrink - close popups, leave full screen
    timer / clock / area   for the bench; the defaults are the real ones
    """

    def __init__(self, window, header, button, grips=None, before=None,
                 timer=None, clock=None, area=None):
        self.window = window
        self.header = header
        self.button = button
        self.grips = grips
        self.before = before
        self.clock = clock or time.time
        self.area = area or work_area
        self.shrunk = False
        self.sliding = False
        self.saved = None
        self.saved_min = 0.0
        self.saved_size_to = None
        self.saved_root = None
        self.parked = None
        self.bar = 0.0
        self.hidden = []
        self.header_look = None
        self.lifted = []
        self.anim = None
        self.timer = timer if timer is not None else self.make_timer()
        # hooked once and gated by state - unhooking an IronPython bound
        # method from a .NET event is not reliable
        self.timer.Tick += self.on_tick
        if button is not None:
            button.Click += self.on_button
            button.ToolTip = TIP_SHRINK
        try:
            window.Closed += self.on_closed
        except Exception:
            pass
        _LIVE.append(self)

    @staticmethod
    def make_timer():
        timer = DispatcherTimer()
        timer.Interval = TimeSpan.FromMilliseconds(TICK_MS)
        return timer

    # ------------------------------------------------------------ queries

    @property
    def busy(self):
        return self.shrunk or self.sliding

    def true_size(self):
        """The window's real (width, height) while it is parked or sliding, so
        closing it parked never saves a 54-pixel window. None otherwise."""
        if self.busy and self.saved is not None:
            return (self.saved[2], self.saved[3])
        return None

    def bar_height(self):
        """The header plus whatever frames it above, mirrored below."""
        height = self.header.ActualHeight
        try:
            offset = self.header.TranslatePoint(Point(0, 0), self.window).Y
        except Exception:
            offset = 1.0
        return height + 2.0 * max(0.0, offset)

    # ------------------------------------------------------------ input

    def on_button(self, sender, args):
        try:
            self.toggle()
        except Exception:
            self.recover()

    def on_closed(self, sender, args):
        self.forget()

    def header_down(self, args):
        """For the window's header MouseLeftButtonDown. True when the drawer
        dealt with it: while parked a double-click opens the window and a
        single click drags the bar; mid-slide nothing happens."""
        if self.sliding:
            return True
        if not self.shrunk:
            return False
        if args.ClickCount == 2:
            self.expand()
        else:
            try:
                self.window.DragMove()
            except Exception:
                pass
        return True

    def handle_key(self, key, ctrl, shift):
        """For the window's PreviewKeyDown, with the key's name. True when the
        drawer dealt with it."""
        action = key_action(key, ctrl, shift, self.shrunk, self.sliding)
        if action == "toggle":
            self.toggle()
        elif action == "expand":
            self.expand()
        return action is not None

    def toggle(self):
        if self.sliding:
            return
        if self.shrunk:
            self.expand()
        else:
            self.shrink()

    # ------------------------------------------------------------ shrink

    def shrink(self, animate=True):
        if self.busy:
            return
        if self.before is not None:
            try:
                self.before()
            except Exception:
                pass

        # A dialog takes its owner down first, so the owner is not left
        # standing over Revit, and parks its own bar above the owner's.
        owner = drawer_of(getattr(self.window, "Owner", None))
        if owner is not None and not owner.busy:
            owner.shrink(animate=False)
            if owner.shrunk:
                self.lifted.append(owner)

        window = self.window
        self.saved = (window.Left, window.Top, window.ActualWidth, window.ActualHeight)
        self.saved_min = window.MinHeight
        self.saved_size_to = window.SizeToContent
        try:
            self.saved_root = window.Content.ActualHeight
        except Exception:
            self.saved_root = None

        # MinHeight and SizeToContent both veto a smaller Height and would
        # leave the window half shut.
        window.SizeToContent = SizeToContent.Manual
        window.MinHeight = 0
        self.bar = self.bar_height()
        stacked = [d.bar for d in _LIVE if d is not self and d.shrunk]
        top = parked_top(self.area(window), self.bar, stacked)

        self.show_grips(False)
        self.pin(True)
        self.set_button(True)
        self.start((window.Left, window.Top, window.ActualHeight),
                   (window.Left, top, self.bar), self.landed, animate)

    def landed(self):
        self.hide_body(True)
        self.pin(False)          # the root follows the bar, so the shell draws round it
        self.shrunk = True
        self.parked = (self.window.Left, self.window.Top)

    # ------------------------------------------------------------ expand

    def expand(self, animate=True):
        if not self.shrunk or self.sliding:
            return
        lifted, self.lifted = self.lifted, []
        for owner in lifted:
            owner.expand(animate=False)

        window = self.window
        target = expanded_rect(self.saved, (window.Left, window.Top),
                               self.parked or (window.Left, window.Top),
                               self.area(window))
        self.shrunk = False
        self.pin(True)           # full height again before the body shows
        self.hide_body(False)
        self.start((window.Left, window.Top, window.ActualHeight),
                   (target[0], target[1], target[3]), self.opened, animate)

    def opened(self):
        window = self.window
        self.pin(False)
        try:
            window.MinHeight = self.saved_min
        except Exception:
            pass
        try:
            if self.saved_size_to is not None:
                window.SizeToContent = self.saved_size_to
        except Exception:
            pass
        self.show_grips(True)
        self.set_button(False)
        self.saved = None
        self.parked = None
        try:
            window.Activate()
        except Exception:
            pass

    def restore_now(self):
        """Back to full size at once - before a dialog opens over the window."""
        if self.sliding:
            self.finish()
        if self.shrunk:
            self.expand(animate=False)

    def forget(self):
        """The window has closed: stop, let go, and bring back any owner."""
        if self.sliding:
            self.finish()
        lifted, self.lifted = self.lifted, []
        for owner in lifted:
            try:
                owner.expand(animate=False)
            except Exception:
                pass
        if self in _LIVE:
            _LIVE.remove(self)

    # ------------------------------------------------------------ the slide

    def start(self, frm, to, done, animate):
        self.sliding = True
        self.anim = (frm, to, done, self.clock())
        if not animate:
            self.finish()
            return
        try:
            self.timer.Start()
        except Exception:
            self.finish()

    def on_tick(self, sender, args):
        if self.anim is None:
            try:
                self.timer.Stop()
            except Exception:
                pass
            return
        try:
            frm, to, done, began = self.anim
            progress = (self.clock() - began) / DURATION
            self.place(frm, to, ease_out(progress))
            if progress >= 1.0:
                self.finish()
        except Exception:
            self.finish()

    def finish(self):
        """Land wherever the slide was going. The timer is stopped first and
        the state cleared in its own guard, so this is also the way out when
        a frame or the start itself failed."""
        try:
            self.timer.Stop()
        except Exception:
            pass
        anim, self.anim = self.anim, None
        self.sliding = False
        if anim is None:
            return
        frm, to, done, _began = anim
        try:
            self.place(frm, to, 1.0)
        except Exception:
            pass
        try:
            done()
        except Exception:
            self.recover()

    def place(self, frm, to, t):
        window = self.window
        window.Left = lerp(frm[0], to[0], t)
        window.Top = lerp(frm[1], to[1], t)
        window.Height = max(1.0, lerp(frm[2], to[2], t))

    def recover(self):
        """Something threw part way: put everything visible back so the window
        is never left as an unreachable bar."""
        self.anim = None
        self.sliding = False
        self.shrunk = False
        try:
            self.timer.Stop()
        except Exception:
            pass
        try:
            self.hide_body(False)
            self.pin(False)
            self.show_grips(True)
            self.set_button(False)
            self.window.MinHeight = self.saved_min
        except Exception:
            pass

    # ------------------------------------------------------------ parts

    def pin(self, on):
        """Hold the body at its full height while the window slides, and let
        the shrinking window clip it - otherwise the grid re-measures every
        frame and it reads as a window being squashed, not a drawer drawn
        away."""
        root = getattr(self.window, "Content", None)
        if root is None:
            return
        try:
            if on and self.saved_root:
                root.Height = self.saved_root
                root.VerticalAlignment = VerticalAlignment.Top
            else:
                root.Height = Double.NaN
                root.VerticalAlignment = VerticalAlignment.Stretch
        except Exception:
            pass

    def hide_body(self, hide):
        parent = getattr(self.header, "Parent", None)
        if hide:
            self.hidden = []
            if parent is not None:
                for child in list(parent.Children):
                    if child is self.header:
                        continue
                    self.hidden.append((child, child.Visibility))
                    child.Visibility = Visibility.Collapsed
            try:
                self.header_look = (self.header.CornerRadius, self.header.BorderThickness)
                self.header.CornerRadius = CornerRadius(5)
                self.header.BorderThickness = Thickness(0)
            except Exception:
                self.header_look = None
            return
        # a part that was already collapsed stays that way
        for child, was in self.hidden:
            try:
                child.Visibility = was
            except Exception:
                pass
        self.hidden = []
        if self.header_look is not None:
            try:
                self.header.CornerRadius, self.header.BorderThickness = self.header_look
            except Exception:
                pass
            self.header_look = None

    def show_grips(self, show):
        if self.grips is None:
            return
        try:
            self.grips.Visibility = Visibility.Visible if show else Visibility.Collapsed
        except Exception:
            pass

    def set_button(self, shrunk):
        if self.button is None:
            return
        try:
            self.button.Tag = SHRUNK if shrunk else None
            self.button.ToolTip = TIP_EXPAND if shrunk else TIP_SHRINK
        except Exception:
            pass
