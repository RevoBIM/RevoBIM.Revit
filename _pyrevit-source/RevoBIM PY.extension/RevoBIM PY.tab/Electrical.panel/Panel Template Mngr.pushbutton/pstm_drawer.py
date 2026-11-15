# -*- coding: utf-8 -*-
"""RevoBIM PY - Panel Template Mngr: shrink any window down to its header bar.

Pressing the shrink button slides the window to the bottom of the screen like a
drawer closing, leaving only its header floating clear of the taskbar so Revit
can be seen and worked in.  The button turns into a green up arrow that opens it
again.  It is the answer to "I need to see the model" that does not involve
closing a window holding changes that have not been applied.

Built once, here, and handed to every window the tool opens - the main window
and every dialog - so the gesture is identical everywhere.

The parking and reopening arithmetic is in plain functions at the top so the
bench can prove it, including a second monitor ABOVE the primary one, where a
negative work-area top is what sends a bar to the wrong screen.

Four things make or break this, and all four fail silently:

  * An animation holds its end value and outranks every later plain
    assignment.  The slide is driven by a DispatcherTimer with plain
    assignments, not BeginAnimation, but the end of every slide still releases
    both properties - in a try of its own, separate from the final assignment -
    so nothing added later can leave a window that never resizes again.
  * MinHeight and SizeToContent both veto a Height animation and leave the
    window half shut.  Both are relaxed before the slide and put back after.
  * The body is pinned at its full height for the length of the slide and the
    shrinking window clips it.  Left free, the grid re-measures every frame and
    the DataGrid realises and drops rows twenty times a second - a window being
    squashed rather than a drawer being drawn away.
  * The resize grips are parked with the body.  Left visible they line the bar
    with invisible drag handles and swallow the click on the arrow.

Runs on IronPython 2.7 and IronPython 3: no f-strings, no print statements.
"""

import time

import pstm_clr                                                  # noqa: F401

from System import TimeSpan, Double                              # noqa: E402
from System.Windows import (Visibility, ResizeMode, SizeToContent,  # noqa: E402
                            VerticalAlignment, CornerRadius, Point, Window,
                            WindowStartupLocation)
from System.Windows.Threading import DispatcherTimer             # noqa: E402
from System.Windows.Input import Key, Keyboard, ModifierKeys     # noqa: E402


SLIDE_SECONDS = 0.28        # the same curve and length as every RevoBIM drawer
TICK_MS = 15
MARGIN = 8                  # gap between the lowest bar and the taskbar
GAP = 4                     # gap between stacked bars
SHRUNK_TAG = 'shrunk'       # the ShrinkButton style swaps to the green arrow on it

SHRINK_TIP = 'Shrink to the taskbar so Revit can be seen - Ctrl+Shift+H'
EXPAND_TIP = 'Bring the window back - Ctrl+Shift+H, or double click the bar'


# ---------------------------------------------------------------------------
# The arithmetic.  Pure, so the bench can prove it without a screen.
# Rectangles are (left, top, width, height) in device independent pixels.
# ---------------------------------------------------------------------------

def ease_out(progress):
    """1 - (1 - p)^3, clamped: fast away, gentle landing."""
    p = max(0.0, min(1.0, float(progress)))
    return 1.0 - (1.0 - p) ** 3


def lerp(start, end, t):
    return start + (end - start) * t


def stack_below(bars_beneath, gap=GAP):
    """How much of the bottom of the screen the bars already parked take up."""
    return sum([float(bar) + gap for bar in bars_beneath])


def shrunk_top(area_top, area_height, bar, below=0.0, margin=MARGIN):
    """Where a bar of height `bar` comes to rest.

    The bottom of the work area - which is already above the taskbar - less
    the margin, less whatever is parked beneath it.  The area's own top is used
    rather than assumed to be zero, because on a monitor above the primary one
    it is negative, and treating it as zero lands the bar on the wrong screen.
    """
    return float(area_top) + float(area_height) - margin - float(below) - float(bar)


def lowest_free(taken):
    """The lowest slot nobody is parked in, so freed slots are reused."""
    slot = 0
    taken = set(taken)
    while slot in taken:
        slot += 1
    return slot


def was_moved(landed, now, tolerance=2.0):
    """Whether the parked bar has been dragged since it landed."""
    if landed is None or now is None:
        return False
    return (abs(float(now[0]) - float(landed[0])) > tolerance or
            abs(float(now[1]) - float(landed[1])) > tolerance)


def reopen_rect(saved, bar_left, bar_top, bar_height, moved, area):
    """Where the window opens back up to.

    A bar nobody has touched goes back exactly where it came from.  A bar that
    has been carried somewhere else opens UPWARD from where it now sits - its
    bottom edge stays at the bar's bottom edge - rather than jumping back to a
    position the user has already moved on from.  Either way it is kept on the
    screen it is on.
    """
    left, top, width, height = [float(v) for v in saved]
    if not moved:
        return (left, top, width, height)
    a_left, a_top, a_width, a_height = [float(v) for v in area]
    new_left = float(bar_left)
    new_top = float(bar_top) + float(bar_height) - height
    if new_top + height > a_top + a_height:
        new_top = a_top + a_height - height
    if new_top < a_top:
        new_top = a_top
    if new_left + width > a_left + a_width:
        new_left = a_left + a_width - width
    if new_left < a_left:
        new_left = a_left
    return (new_left, new_top, width, height)


# ---------------------------------------------------------------------------
# Every live drawer, for slots and for finding a dialog's owner
# ---------------------------------------------------------------------------

_LIVE = []


def _same(a, b):
    if a is None or b is None:
        return False
    if a is b:
        return True
    try:
        from System import Object
        return Object.ReferenceEquals(a, b) is True
    except Exception:
        return False


def drawer_of(window):
    for drawer in _LIVE:
        if _same(drawer.window, window):
            return drawer
    return None


def adopt(dialog, owner):
    """Give a dialog its owner, and put it where it can be seen.

    A dialog centred on an owner that is parked at the bottom of the screen is
    centred on a fifty pixel bar - mostly off the screen.  That is exactly when
    a dialog turns up unasked: somebody shrinks the tool to watch Revit while
    Apply runs, and the summary arrives.  So while the owner is parked the
    dialog opens in the middle of the screen being worked on instead.
    """
    if owner is None:
        return
    try:
        dialog.Owner = owner
    except Exception:
        return
    parent = drawer_of(owner)
    if parent is not None and parent.parked:
        try:
            dialog.WindowStartupLocation = WindowStartupLocation.CenterScreen
        except Exception:
            pass


def screen_area(window):
    """The work area of the screen the window is on, in DIPs.

    The work area already excludes the taskbar.  Divided by the DPI scale,
    because Screen reports device pixels and the window is positioned in DIPs.
    """
    try:
        from System.Windows.Interop import WindowInteropHelper
        from System.Windows.Forms import Screen
        from System.Windows import PresentationSource
        area = Screen.FromHandle(WindowInteropHelper(window).Handle).WorkingArea
        sx, sy = 1.0, 1.0
        try:
            matrix = PresentationSource.FromVisual(window) \
                .CompositionTarget.TransformToDevice
            sx, sy = (matrix.M11 or 1.0), (matrix.M22 or 1.0)
        except Exception:
            pass
        return (area.Left / sx, area.Top / sy, area.Width / sx, area.Height / sy)
    except Exception:
        pass
    try:
        from System.Windows import SystemParameters
        work = SystemParameters.WorkArea
        return (work.Left, work.Top, work.Width, work.Height)
    except Exception:
        return (0.0, 0.0, 1920.0, 1040.0)


def _dispatcher_timer(interval_ms, on_tick):
    timer = DispatcherTimer()
    timer.Interval = TimeSpan.FromMilliseconds(interval_ms)
    timer.Tick += on_tick
    return timer


# ---------------------------------------------------------------------------
# The drawer
# ---------------------------------------------------------------------------

class Drawer(object):
    """Shrink a borderless window to its header bar and bring it back.

    Finds `HeaderBar` and `ShrinkButton` by name if they are not handed in, so
    every window in the tool is wired the same way and the bench can check that
    none was missed.  The timer, the clock and the screen are injectable so the
    whole slide can be driven on the bench against a stand-in window.
    """

    def __init__(self, window, header=None, button=None, on_change=None,
                 timer_factory=None, clock=None, area_of=None):
        self.window = window
        self.header = header if header is not None else window.FindName('HeaderBar')
        self.button = button if button is not None else window.FindName('ShrinkButton')
        self.on_change = on_change
        self._timer_factory = timer_factory or _dispatcher_timer
        self._clock = clock or time.time
        self._area_of = area_of or screen_area

        self.shrunk = False
        self.sliding = False
        self.slot = None
        self.bar = 0.0
        self.saved = None               # (left, top, width, height) before shrinking
        self.landed = None              # (left, top) where the bar came to rest
        self.lifted = None              # the owner's drawer this one shrank
        self._kept = {}                 # MinHeight, ResizeMode, SizeToContent, corners
        self._hidden = []               # [(element, its visibility before)]
        self._timer = None
        self._start = None
        self._end = None
        self._t0 = 0.0
        self._done = None
        self._activate = True

        # held on the instance: a delegate nobody holds can be collected, and
        # then the event simply stops firing with nothing said
        self._button_handler = self._on_button
        self._key_handler = self._on_key
        self._closed_handler = self._on_closed
        self._tick_handler = self._tick

        try:
            self.button.Click += self._button_handler
            self.button.ToolTip = SHRINK_TIP
        except Exception:
            pass
        try:
            self.window.PreviewKeyDown += self._key_handler
        except Exception:
            pass
        try:
            self.window.Closed += self._closed_handler
        except Exception:
            pass
        _LIVE.append(self)

    # -- state --------------------------------------------------------------
    @property
    def parked(self):
        """Shrunk, or on the way down or up - nothing else should move it."""
        return bool(self.shrunk or self.sliding)

    def true_size(self):
        """(width, height) as the user left it, even while it is a bar.

        Anything that remembers a window's size has to ask this rather than
        the window, or closing it while shrunk saves a fifty pixel window.
        """
        if self.parked and self.saved is not None:
            return (self.saved[2], self.saved[3])
        try:
            return (self.window.ActualWidth, self.window.ActualHeight)
        except Exception:
            return (0.0, 0.0)

    # -- the gesture --------------------------------------------------------
    def toggle(self):
        if self.sliding:
            return
        if self.shrunk:
            self.expand()
        else:
            self.shrink()

    def shrink(self, animate=True):
        if self.parked:
            return
        w = self.window

        # a dialog takes its owner down with it, or the owner just sits over
        # Revit and shrinking the dialog has shown nothing
        owner = None
        try:
            owner = drawer_of(w.Owner)
        except Exception:
            owner = None
        if owner is not None and not owner.parked:
            owner.shrink(animate=False)
            self.lifted = owner

        full_height = _num(w.ActualHeight, _num(w.Height, 400.0))
        full_width = _num(w.ActualWidth, _num(w.Width, 600.0))
        self.saved = (w.Left, w.Top, full_width, full_height)
        self._kept = {'min_height': _get(w, 'MinHeight'),
                      'resize': _get(w, 'ResizeMode'),
                      'size_to': _get(w, 'SizeToContent'),
                      'corners': _get(self.header, 'CornerRadius')}

        # SizeToContent and MinHeight both veto a Height that is shrinking
        _set(w, 'SizeToContent', SizeToContent.Manual)
        _set(w, 'Height', full_height)
        _set(w, 'MinHeight', 0.0)
        self._pin(full_height)

        self.bar = self._bar_height()
        self.slot = lowest_free([d.slot for d in _LIVE
                                 if d is not self and d.slot is not None])
        below = stack_below([d.bar for d in _LIVE
                             if d is not self and d.slot is not None
                             and d.slot < self.slot])
        area = self._area_of(w)
        top = shrunk_top(area[1], area[3], self.bar, below)
        self._slide((w.Top, full_height), (top, self.bar), animate,
                    self._landed_shrunk)

    def expand(self, animate=True, activate=True):
        if not self.shrunk or self.sliding:
            return
        w = self.window

        # the owner comes back first, so it is behind this one as it rises
        if self.lifted is not None:
            lifted, self.lifted = self.lifted, None
            try:
                lifted.expand(animate=False, activate=False)
            except Exception:
                pass

        now = (_num(w.Left, 0.0), _num(w.Top, 0.0))
        rect = reopen_rect(self.saved, now[0], now[1], self.bar,
                           was_moved(self.landed, now), self._area_of(w))

        # the body goes back BEFORE the slide, pinned at its full height, so the
        # window reveals it as it rises rather than re-laying it out every frame
        self._pin(rect[3])
        _set(self.header, 'CornerRadius', self._kept.get('corners'))
        self._show_body()
        _set(w, 'Left', rect[0])

        self.shrunk = False
        self.slot = None
        self._activate = activate
        try:
            if self.button is not None:
                self.button.Tag = None
                self.button.ToolTip = SHRINK_TIP
        except Exception:
            pass
        self._slide((w.Top, self.bar), (rect[1], rect[3]), animate,
                    self._landed_open)

    def restore_now(self):
        """Back to full size with no slide - for closing, or for an owner."""
        if self.sliding:
            self._finish_slide()
        if self.shrunk:
            self.expand(animate=False, activate=False)

    # -- landing ------------------------------------------------------------
    def _landed_shrunk(self):
        w = self.window
        self._hide_body()
        try:
            radius = self._kept.get('corners')
            _set(self.header, 'CornerRadius', CornerRadius(radius.TopLeft))
        except Exception:
            pass
        # the window is now exactly the bar, so the root can fit it again and
        # draw its whole rounded outline around the header
        self._unpin()
        _set(w, 'ResizeMode', ResizeMode.NoResize)
        self.shrunk = True
        self.landed = (_num(w.Left, 0.0), _num(w.Top, 0.0))
        try:
            if self.button is not None:
                self.button.Tag = SHRUNK_TAG
                self.button.ToolTip = EXPAND_TIP
        except Exception:
            pass
        self._changed()

    def _landed_open(self):
        w = self.window
        _set(w, 'MinHeight', self._kept.get('min_height'))
        _set(w, 'ResizeMode', self._kept.get('resize'))
        _set(w, 'SizeToContent', self._kept.get('size_to'))
        self._unpin()
        if self._activate:
            try:
                w.Activate()
            except Exception:
                pass
        self._activate = True
        self._changed()

    def _changed(self):
        if self.on_change is None:
            return
        try:
            self.on_change(self.shrunk)
        except Exception:
            pass

    # -- the slide ----------------------------------------------------------
    def _slide(self, start, end, animate, done):
        self.sliding = True
        self._start = (float(start[0]), float(start[1]))
        self._end = (float(end[0]), float(end[1]))
        self._done = done
        if not animate:
            self._finish_slide()
            return
        self._t0 = self._clock()
        try:
            self._timer = self._timer_factory(TICK_MS, self._tick_handler)
            self._timer.Start()
        except Exception:
            # could not animate at all: land at the end state
            self._finish_slide()

    def _tick(self, sender=None, args=None):
        if not self.sliding:
            return
        try:
            progress = (self._clock() - self._t0) / SLIDE_SECONDS
            if progress >= 1.0:
                self._finish_slide()
                return
            eased = ease_out(progress)
            self.window.Top = lerp(self._start[0], self._end[0], eased)
            self.window.Height = max(1.0, lerp(self._start[1], self._end[1], eased))
        except Exception:
            # a frame that throws lands the window at the end state rather than
            # leaving it stranded half way
            self._finish_slide()

    def _finish_slide(self):
        timer, self._timer = self._timer, None
        if timer is not None:
            try:
                timer.Stop()
            except Exception:
                pass
        w = self.window
        # release any animation on these two properties BEFORE writing them,
        # each in a try of its own: an animation's held end value outranks every
        # later plain assignment, and this is also the path taken when the
        # animation never started, so the release must not depend on it
        try:
            w.BeginAnimation(Window.TopProperty, None)
        except Exception:
            pass
        try:
            w.BeginAnimation(Window.HeightProperty, None)
        except Exception:
            pass
        if self._end is not None:
            _set(w, 'Top', self._end[0])
            _set(w, 'Height', self._end[1])
        self.sliding = False
        done, self._done = self._done, None
        if done is not None:
            try:
                done()
            except Exception:
                pass

    # -- the body -----------------------------------------------------------
    def _bar_height(self):
        """The header, plus the outer border above and below it."""
        height = _num(_get(self.header, 'ActualHeight'), 40.0)
        offset = 1.0
        try:
            offset = float(self.header.TranslatePoint(Point(0, 0), self.window).Y)
        except Exception:
            offset = 1.0
        return height + 2.0 * max(0.0, offset)

    def _siblings(self):
        out = []
        try:
            for child in self.header.Parent.Children:
                if not _same(child, self.header):
                    out.append(child)
        except Exception:
            pass
        return out

    def _hide_body(self):
        """Collapse everything beside the header - body, footer, grips -
        remembering how each one was, so a hidden panel stays hidden."""
        self._hidden = []
        for child in self._siblings():
            try:
                self._hidden.append((child, child.Visibility))
                child.Visibility = Visibility.Collapsed
            except Exception:
                pass

    def _show_body(self):
        for child, was in self._hidden:
            try:
                child.Visibility = was
            except Exception:
                pass
        self._hidden = []

    def _pin(self, height):
        root = _get(self.window, 'Content')
        _set(root, 'Height', height)
        _set(root, 'VerticalAlignment', VerticalAlignment.Top)

    def _unpin(self):
        root = _get(self.window, 'Content')
        _set(root, 'Height', Double.NaN)
        _set(root, 'VerticalAlignment', VerticalAlignment.Stretch)

    # -- input --------------------------------------------------------------
    def on_header_down(self, args, can_drag=True):
        """Mouse down on the header.  True if the drawer dealt with it.

        While parked a double click brings the window back - rather than going
        full screen with a window nobody can see - and a single click drags the
        bar.  Not parked, it is the window's own business.
        """
        if not self.parked:
            return False
        if self.sliding:
            return True
        try:
            if args.ClickCount == 2:
                self.expand()
                args.Handled = True
                return True
        except Exception:
            pass
        if can_drag:
            try:
                self.window.DragMove()
            except Exception:
                pass
        return True

    def _modifiers(self):
        try:
            return Keyboard.Modifiers
        except Exception:
            return None

    def _ctrl_shift(self):
        mods = self._modifiers()
        if mods is None:
            return False
        try:
            want = ModifierKeys.Control | ModifierKeys.Shift
            return (mods & want) == want
        except Exception:
            return False

    def _on_key(self, sender, args):
        try:
            key = args.Key
        except Exception:
            return
        try:
            if key == Key.H and self._ctrl_shift():
                self.toggle()
                args.Handled = True
                return
            # while parked Escape, Enter and F11 bring the window back rather
            # than reaching a close prompt or filling the screen with a window
            # nobody can see
            if self.shrunk and key in (Key.Escape, Key.Enter, Key.F11):
                self.expand()
                args.Handled = True
        except Exception:
            pass

    def _on_button(self, sender, args):
        self.toggle()

    def _on_closed(self, sender, args):
        timer, self._timer = self._timer, None
        if timer is not None:
            try:
                timer.Stop()
            except Exception:
                pass
        self.sliding = False
        self.shrunk = False
        self.slot = None
        # a dialog closed while parked brings back the owner it took down
        if self.lifted is not None:
            lifted, self.lifted = self.lifted, None
            try:
                lifted.expand(animate=False)
            except Exception:
                pass
        try:
            _LIVE.remove(self)
        except ValueError:
            pass


# ---------------------------------------------------------------------------
# small helpers - every property access can throw on a release that lacks it
# ---------------------------------------------------------------------------

def _num(value, fallback):
    try:
        number = float(value)
    except Exception:
        return fallback
    if number != number:            # NaN, which is what Height is under SizeToContent
        return fallback
    return number


def _get(obj, name):
    if obj is None:
        return None
    try:
        return getattr(obj, name)
    except Exception:
        return None


def _set(obj, name, value):
    if obj is None or value is None:
        return False
    try:
        setattr(obj, name, value)
        return True
    except Exception:
        return False
