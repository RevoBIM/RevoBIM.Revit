# -*- coding: utf-8 -*-
"""RevoBIM PY - Family Find & Replace : shrink to taskbar.

Every window this tool opens - the main window, the adjust window and the
prompt - gets one Drawer, so the gesture is the same everywhere. The shrink
button in the top right slides the window down to the bottom of its screen
like a drawer closing, leaving only its header bar floating clear of the
taskbar so Revit can be seen and worked in. The button turns into a green up
arrow that opens it again. Ctrl+Shift+H does the same from the keyboard.

House standard: RevoBIM theme reference, "Shrink to taskbar". The arithmetic
is in plain functions at the top so bench_logic.py can prove it, and the
Drawer class is driven by the same bench against a stand-in window - four of
the five things that break a drawer fail silently.

Runs on IronPython 2.7 and IronPython 3, Revit 2024 - 2027.
"""

import time

import clr

clr.AddReference('mscorlib')
clr.AddReference('PresentationCore')
clr.AddReference('PresentationFramework')
clr.AddReference('WindowsBase')
try:
    # Which screen the window is on. Optional: without it the primary screen's
    # working area is used, which is only wrong on a second monitor.
    clr.AddReference('System.Windows.Forms')
except Exception:
    pass

from System import Double, TimeSpan
from System.Windows import (
    CornerRadius,
    Point,
    PresentationSource,
    ResizeMode,
    SizeToContent,
    SystemParameters,
    VerticalAlignment,
    Visibility,
    Window,
)
from System.Windows.Input import Key, Keyboard, ModifierKeys
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Threading import DispatcherTimer

# ---------------------------------------------------------------------------
# constants worth finding at the top of the file
# ---------------------------------------------------------------------------

#: How long the slide takes either way.
SLIDE_SECONDS = 0.28

#: One frame of the slide.
TICK_MS = 15

#: Gap between a parked bar and the bottom of the working area (the taskbar).
PARK_MARGIN = 8.0

#: Gap between two bars parked one above the other.
PARK_GAP = 4.0

#: A bar carried further than this has been moved on purpose.
MOVED_TOL = 2.0

#: The shrink button's Tag while parked - Theme.xaml swaps in the green arrow.
SHRUNK_TAG = 'shrunk'

TIP_SHRINK = 'Shrink to the taskbar so Revit can be seen  (Ctrl+Shift+H)'
TIP_EXPAND = 'Open the window again  (Ctrl+Shift+H, Enter or Esc)'


# ---------------------------------------------------------------------------
# the arithmetic - pure, proved by bench_logic.py
# ---------------------------------------------------------------------------

def ease_out(progress):
    """Cubic ease out: quick away, settling gently. 0..1 in, 0..1 out."""
    if progress <= 0.0:
        return 0.0
    if progress >= 1.0:
        return 1.0
    return 1.0 - (1.0 - progress) ** 3


def lerp(start, end, fraction):
    return start + (end - start) * fraction


def bar_height(header_height, header_offset):
    """The parked bar: the header, plus the window's edge above and below it."""
    return float(header_height) + 2.0 * float(header_offset)


def device_to_dips(left, top, right, bottom, scale_x, scale_y):
    """A screen rectangle in device pixels, in WPF units."""
    sx = scale_x if scale_x else 1.0
    sy = scale_y if scale_y else 1.0
    return (left / sx, top / sy, right / sx, bottom / sy)


def stacked_below(bars, gap=PARK_GAP):
    """Height already taken at the bottom of the screen by parked bars."""
    return sum([float(bar) + gap for bar in bars])


def parked_top(area_bottom, bar, below, margin=PARK_MARGIN):
    """Top of a bar parked clear of the taskbar, above any bars already there."""
    return area_bottom - margin - below - bar


def clamp_left(left, width, area_left, area_right):
    """Keep a window's left edge on its screen."""
    if left + width > area_right:
        left = area_right - width
    if left < area_left:
        left = area_left
    return left


def clamp_top(top, height, area_top, area_bottom):
    """Keep a window on its screen top to bottom, its header above all.

    Clamped to the area's own top, never to zero: on a second monitor set
    above the primary one the working area's top is negative, and clamping to
    zero is what sends the window back to the wrong screen.
    """
    if top + height > area_bottom:
        top = area_bottom - height
    if top < area_top:
        top = area_top
    return top


def was_moved(now_left, now_top, parked_left, parked_top_value,
              tol=MOVED_TOL):
    return (abs(now_left - parked_left) > tol or
            abs(now_top - parked_top_value) > tol)


def reopen_frame(saved, now_left, now_top, parked, bar, area, tol=MOVED_TOL):
    """(left, top) to reopen a parked window to.

    saved   (left, top, width, height) before it shrank
    parked  (left, top) where the bar landed
    area    (left, top, right, bottom) of the screen the bar is on now

    Left where it landed, the window goes back where it came from. Carried
    somewhere else, it opens upward from where the bar now sits - the bar's
    bottom edge stays put - and is kept on that screen, rather than jumping
    back to a place the user has already moved on from.
    """
    left, top, width, height = saved
    if not was_moved(now_left, now_top, parked[0], parked[1], tol):
        return left, top
    bottom = now_top + bar
    top = clamp_top(bottom - height, height, area[1], area[3])
    left = clamp_left(now_left, width, area[0], area[2])
    return left, top


# ---------------------------------------------------------------------------
# the screen
# ---------------------------------------------------------------------------

def dpi_scale(window):
    try:
        source = PresentationSource.FromVisual(window)
        matrix = source.CompositionTarget.TransformToDevice
        return matrix.M11, matrix.M22
    except Exception:
        return 1.0, 1.0


def work_area(window):
    """(left, top, right, bottom) of the working area of the window's screen,
    in WPF units. Falls back to the primary screen."""
    try:
        from System.Windows.Forms import Screen
        handle = WindowInteropHelper(window).Handle
        rect = Screen.FromHandle(handle).WorkingArea
        scale_x, scale_y = dpi_scale(window)
        return device_to_dips(float(rect.Left), float(rect.Top),
                              float(rect.Right), float(rect.Bottom),
                              scale_x, scale_y)
    except Exception:
        pass
    try:
        area = SystemParameters.WorkArea
        return (area.Left, area.Top, area.Right, area.Bottom)
    except Exception:
        return (0.0, 0.0, 1920.0, 1040.0)


def _dispatcher_timer(milliseconds, handler):
    timer = DispatcherTimer()
    timer.Interval = TimeSpan.FromMilliseconds(milliseconds)
    timer.Tick += handler
    return timer


# ---------------------------------------------------------------------------
# which windows are about
# ---------------------------------------------------------------------------

#: Every live drawer, so a dialog can find its owner's.
_DRAWERS = []

#: Drawers parked at the bottom of the screen, lowest first.
_PARKED = []


def _same(a, b):
    if a is None or b is None:
        return False
    if a is b:
        return True
    try:
        return bool(a.Equals(b))
    except Exception:
        return False


def drawer_of(window):
    for drawer in _DRAWERS:
        if _same(drawer.window, window):
            return drawer
    return None


def _owner_window(drawer):
    try:
        return drawer.window.Owner
    except Exception:
        return None


# ---------------------------------------------------------------------------
# the drawer
# ---------------------------------------------------------------------------

class Drawer(object):
    """Shrink one window to its header bar and bring it back.

    window      the WPF Window
    header      its header bar Border - the part left showing
    root        the layout element holding the header and everything else.
                Its other children are hidden while parked, and the resize
                grips are one of them, so the parked bar is not lined with
                invisible drag handles that swallow the click on the arrow.
    button      the shrink button in the header
    can_toggle  optional; returning False holds the window where it is, for
                the length of a run

    clock, make_timer and area_of are there for the logic bench.

    A dialog takes its owner down with it, so the main window does not stay
    standing over Revit; a window takes its open dialogs down with it for the
    same reason. Bringing either back brings both.
    """

    def __init__(self, window, header, root, button, can_toggle=None,
                 clock=None, make_timer=None, area_of=None):
        self.window = window
        self.header = header
        self.root = root
        self.button = button
        self.can_toggle = can_toggle
        self.state = 'open'           # open, closing, shrunk, opening, closed
        self.saved = None             # (left, top, width, height)
        self.parked = None            # (left, top) the bar landed at
        self.bar = 0.0
        self.lifted = None            # the owner's drawer this one took down
        self.carried = []             # dialogs taken down with this window
        self._kept = {}               # what the slide changed, to put back
        self._hidden = []             # (element, its Visibility before)
        self._anim = None
        self._timer = None
        # Held on the instance: a bound method fetched twice is two different
        # delegates, and the one taken off would not be the one put on.
        self._tick_handler = self._tick
        self._clock = clock or time.time
        self._make_timer = make_timer or _dispatcher_timer
        self._area_of = area_of or work_area
        _DRAWERS.append(self)
        try:
            button.Click += self._clicked
        except Exception:
            pass
        try:
            window.PreviewKeyDown += self._key
        except Exception:
            pass
        try:
            window.Closed += self._closed
        except Exception:
            pass
        self._paint(False)

    # -- asked for by the window ------------------------------------------

    @property
    def is_open(self):
        return self.state == 'open'

    def toggle(self):
        if self.state == 'open':
            return self.shrink()
        if self.state == 'shrunk':
            return self.expand()
        return False

    def on_header_down(self, args):
        """Call first from the header's MouseLeftButtonDown.

        True when the drawer has dealt with the click: a double click on a
        parked bar opens it. Anything else is left to the caller, which drags
        the window as usual - the parked bar stays draggable.
        """
        if self.state != 'shrunk':
            return False
        try:
            clicks = args.ClickCount
        except Exception:
            clicks = 1
        if clicks < 2:
            return False
        self.expand()
        try:
            args.Handled = True
        except Exception:
            pass
        return True

    def _allowed(self):
        if self.can_toggle is None:
            return True
        try:
            return bool(self.can_toggle())
        except Exception:
            return True

    def _clicked(self, sender, args):
        if self._allowed():
            self.toggle()

    def _key(self, sender, args):
        try:
            key = args.Key
            mods = int(Keyboard.Modifiers)
        except Exception:
            return
        both = int(ModifierKeys.Control) | int(ModifierKeys.Shift)
        if key == Key.H and (mods & both) == both:
            if self._allowed():
                self.toggle()
            args.Handled = True
            return
        if self.state in ('closing', 'shrunk', 'opening'):
            # Parked, the keys that would answer or close a window open it
            # instead. A window nobody can see must not be answered blind.
            if key in (Key.Escape, Key.Return):
                if self.state == 'shrunk':
                    self.expand()
                args.Handled = True

    # -- down --------------------------------------------------------------

    def shrink(self, animate=True, lift=True):
        if self.state != 'open':
            return False
        window = self.window
        self.state = 'closing'

        if lift:
            owner = self._owner()
            if owner is not None and owner.state == 'open':
                if owner.shrink(animate=False, lift=True):
                    self.lifted = owner

        try:
            left, top = window.Left, window.Top
            width, height = window.ActualWidth, window.ActualHeight
        except Exception:
            self.state = 'open'
            return False
        self.saved = (left, top, width, height)
        self.bar = self._bar_height()
        area = self._area_of(window)
        below = stacked_below([d.bar for d in _PARKED if d is not self])
        target_top = parked_top(area[3], self.bar, below)
        target_left = clamp_left(left, width, area[0], area[2])
        self.parked = (target_left, target_top)
        _PARKED.append(self)

        self._relax()
        self._pin()
        try:
            window.Left = target_left
        except Exception:
            pass
        self._slide(top, height, target_top, self.bar, self._landed, animate)

        # Open dialogs go down with it, stacked above.
        for child in self._children():
            if child.state == 'open' and child.shrink(animate=False,
                                                      lift=False):
                self.carried.append(child)
        return True

    def _landed(self):
        # The body is hidden only now. Hidden at the start, the slide would be
        # a bar sliding rather than a drawer closing.
        self._hidden = []
        for element in self._siblings():
            try:
                self._hidden.append((element, element.Visibility))
                element.Visibility = Visibility.Collapsed
            except Exception:
                continue
        try:
            corner = self.header.CornerRadius
            self._kept['corner'] = corner
            self.header.CornerRadius = CornerRadius(
                max(corner.TopLeft, corner.TopRight))
        except Exception:
            pass
        try:
            self._kept['resize'] = self.window.ResizeMode
            self.window.ResizeMode = ResizeMode.NoResize
        except Exception:
            pass
        self.state = 'shrunk'
        self._paint(True)

    # -- up ----------------------------------------------------------------

    def expand(self, animate=True):
        if self.state != 'shrunk':
            return False
        window = self.window
        self.state = 'opening'
        if self in _PARKED:
            _PARKED.remove(self)

        # The owner comes back first, so it is behind the dialog as it rises.
        owner = self._owner()
        if owner is not None and owner.state == 'shrunk':
            owner.expand(animate=False)
        self.lifted = None

        for element, visibility in self._hidden:
            try:
                element.Visibility = visibility
            except Exception:
                continue
        self._hidden = []
        if 'corner' in self._kept:
            try:
                self.header.CornerRadius = self._kept.pop('corner')
            except Exception:
                pass
        if 'resize' in self._kept:
            try:
                window.ResizeMode = self._kept.pop('resize')
            except Exception:
                pass
        self._paint(False)

        try:
            now_left, now_top = window.Left, window.Top
        except Exception:
            now_left, now_top = self.parked
        area = self._area_of(window)
        left, top = reopen_frame(self.saved, now_left, now_top, self.parked,
                                 self.bar, area)
        try:
            window.Left = left
        except Exception:
            pass
        self._slide(now_top, self.bar, top, self.saved[3], self._opened,
                    animate)

        # Dialogs that went down with this window, or took it down, come back.
        for child in self._children():
            if child.state == 'shrunk' and (child in self.carried or
                                            child.lifted is self):
                child.expand(animate=False)
        self.carried = []
        return True

    def _opened(self):
        self._unpin()
        self._restore()
        self.state = 'open'
        try:
            self.window.Activate()
        except Exception:
            pass

    # -- what the slide has to relax ----------------------------------------

    def _relax(self):
        """MinHeight and SizeToContent both veto a Height change, and a vetoed
        slide leaves the window half shut. Both relaxed for the slide and the
        time parked, and put back once it reopens."""
        window = self.window
        try:
            self._kept['min'] = window.MinHeight
            window.MinHeight = 0.0
        except Exception:
            pass
        try:
            self._kept['size'] = window.SizeToContent
            window.SizeToContent = SizeToContent.Manual
        except Exception:
            pass
        self._release()

    def _restore(self):
        window = self.window
        if 'min' in self._kept:
            try:
                window.MinHeight = self._kept.pop('min')
            except Exception:
                pass
        if 'size' in self._kept:
            try:
                window.SizeToContent = self._kept.pop('size')
            except Exception:
                pass

    def _pin(self):
        """Hold the body at its full height while the window shrinks round it.

        Without this the layout re-measures on every frame and it reads as a
        window being squashed, not a drawer being drawn away.
        """
        root = self.root
        try:
            self._kept['root_height'] = root.Height
            self._kept['root_align'] = root.VerticalAlignment
            root.Height = root.ActualHeight
            root.VerticalAlignment = VerticalAlignment.Top
        except Exception:
            pass

    def _unpin(self):
        root = self.root
        try:
            root.Height = self._kept.pop('root_height', Double.NaN)
        except Exception:
            pass
        try:
            root.VerticalAlignment = self._kept.pop(
                'root_align', VerticalAlignment.Stretch)
        except Exception:
            pass

    def _release(self):
        """Let go of anything animating Top or Height.

        An animation holds its end value and outranks every later plain
        assignment, so a window left holding one can never be moved or sized
        again - and nothing says so. Each property cleared in its own try, so
        a failure on one still clears the other.
        """
        try:
            self.window.BeginAnimation(Window.TopProperty, None)
        except Exception:
            pass
        try:
            self.window.BeginAnimation(Window.HeightProperty, None)
        except Exception:
            pass

    # -- the slide ---------------------------------------------------------

    def _slide(self, top0, height0, top1, height1, done, animate):
        """Ease Top and Height together on a DispatcherTimer.

        A Storyboard on a borderless window's Top and Height fights the
        layout pass, which is why every RevoBIM drawer steps it by hand.
        """
        self._stop()
        self._anim = (top0, height0, top1, height1, self._clock(), done)
        if not animate:
            self._finish()
            return
        try:
            self._timer = self._make_timer(TICK_MS, self._tick_handler)
            self._timer.Start()
        except Exception:
            # No timer, no slide: land straight at the end.
            self._finish()

    def _tick(self, sender, args):
        anim = self._anim
        if anim is None:
            self._stop()
            return
        try:
            top0, height0, top1, height1, start, _done = anim
            progress = (self._clock() - start) / SLIDE_SECONDS
            if progress >= 1.0:
                self._finish()
                return
            eased = ease_out(progress)
            self.window.Top = lerp(top0, top1, eased)
            self.window.Height = max(1.0, lerp(height0, height1, eased))
        except Exception:
            # A frame that throws lands the window at the end, rather than
            # leaving it stopped half way with the timer still running.
            self._finish()

    def _finish(self):
        self._stop()
        anim, self._anim = self._anim, None
        if anim is None:
            return
        _top0, _height0, top1, height1, _start, done = anim
        # Released in a try of its own: this is also the path taken when the
        # slide could not start at all.
        self._release()
        try:
            self.window.Top = top1
        except Exception:
            pass
        try:
            self.window.Height = height1
        except Exception:
            pass
        try:
            done()
        except Exception:
            pass

    def _stop(self):
        timer, self._timer = self._timer, None
        if timer is None:
            return
        try:
            timer.Stop()
        except Exception:
            pass
        try:
            timer.Tick -= self._tick_handler
        except Exception:
            pass

    # -- bits --------------------------------------------------------------

    def _closed(self, sender, args):
        self._stop()
        self._anim = None
        if self in _PARKED:
            _PARKED.remove(self)
        if self in _DRAWERS:
            _DRAWERS.remove(self)
        lifted, self.lifted = self.lifted, None
        self.state = 'closed'
        # Closing a dialog that took its owner down brings the owner back.
        if lifted is not None and lifted.state == 'shrunk':
            lifted.expand()

    def _paint(self, shrunk):
        try:
            self.button.Tag = SHRUNK_TAG if shrunk else ''
        except Exception:
            pass
        try:
            self.button.ToolTip = TIP_EXPAND if shrunk else TIP_SHRINK
        except Exception:
            pass

    def _bar_height(self):
        try:
            offset = self.header.TranslatePoint(Point(0.0, 0.0),
                                                self.window).Y
        except Exception:
            offset = 1.0
        try:
            height = self.header.ActualHeight
        except Exception:
            height = 40.0
        return bar_height(height, offset)

    def _siblings(self):
        found = []
        try:
            for child in self.root.Children:
                if not _same(child, self.header):
                    found.append(child)
        except Exception:
            pass
        return found

    def _owner(self):
        owner = _owner_window(self)
        if owner is None:
            return None
        return drawer_of(owner)

    def _children(self):
        return [d for d in _DRAWERS if d is not self and
                _same(_owner_window(d), self.window)]
