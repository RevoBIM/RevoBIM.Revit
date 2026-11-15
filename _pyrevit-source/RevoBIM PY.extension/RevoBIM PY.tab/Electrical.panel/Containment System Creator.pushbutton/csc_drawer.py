# -*- coding: utf-8 -*-
"""Shrink to taskbar - the drawer every Containment System Creator window has.

Pressing the shrink button slides the window down to the bottom of its screen
like a drawer closing, leaving only its header bar floating 8px clear of the
taskbar so Revit can be seen. The button turns into a green up arrow; press it,
double-click the bar, or press Enter, Esc or F11 and the window slides back up
to where it was. Ctrl+Shift+H does the same both ways.

Built once, here, and handed to every window by ``attach`` - that is what keeps
the gesture identical across the main window and the three dialogs.

The slide eases ``Top`` only, by hand, on a 15ms timer over 0.28s with
``1-(1-p)^3``. The window keeps its full height on the way down, so nothing
re-measures mid-slide, and the height is cut to the bar only once it has
landed. No Storyboard is ever used: an animation holds its end value and
outranks every later plain assignment, which leaves a window that can never be
moved again with nothing raised to say so. Anything else that may have left an
animation on Top or Height is released before each slide regardless.

The other traps the house standard names, each handled here and each proved by
``bench_logic.py``:

* ``MinHeight`` and ``SizeToContent`` both veto a height change - relaxed for
  the trip down, put back when the window is open again.
* The resize grip (``ResizeMode.CanResizeWithGrip``) would sit on the parked
  bar and swallow clicks - parked with the window, restored after.
* The body is pinned at its full height for the slide and unpinned on landing.
* Every sibling of the header is collapsed while parked and put back to what it
  was, not to Visible.
* A frame that throws lands the window at its end state rather than leaving it
  half way.

The parking and reopening arithmetic is plain functions with no WPF in them, so
the bench proves it under CPython - including a second monitor above the
primary one, whose negative work-area top is what sends a bar to the wrong
screen when it is got wrong.

This module imports nothing from .NET at load time. Everything WPF is reached
lazily through ``real_wpf()``, after ``csc_clr`` has referenced the assemblies,
so the bench can import it with a stand-in.
"""

import time


SLIDE_SECONDS = 0.28
TICK_MS = 15
MARGIN = 8           # bar floats this far above the taskbar
GAP = 4              # between stacked bars
DRAG_TOLERANCE = 2   # bar moved further than this counts as dragged
PARKED_CORNER = 5

OPEN = "open"
CLOSING = "closing"
PARKED = "parked"
OPENING = "opening"

REOPEN_KEYS = ("Escape", "Return", "Enter", "F11")

SHRINK_TIP = u"Shrink to the taskbar (Ctrl+Shift+H)"
EXPAND_TIP = u"Bring the window back (Ctrl+Shift+H)"


# ===========================================================================
# pure arithmetic - proved by bench_logic.py
# ===========================================================================

def ease_out(p):
    """Cubic ease out, clamped to 0..1."""
    if p <= 0.0:
        return 0.0
    if p >= 1.0:
        return 1.0
    inv = 1.0 - p
    return 1.0 - inv * inv * inv


def lerp(start, end, t):
    return start + (end - start) * t


def clamp(value, low, high):
    """Clamp, preferring ``low`` when the range is empty."""
    if high < low:
        return low
    if value < low:
        return low
    if value > high:
        return high
    return value


def bar_height(header_height, header_offset):
    """The parked window: the header plus the frame either side of it."""
    return header_height + 2.0 * header_offset


def free_slot(slots):
    """First unused slot index, reusing ones freed by bars that reopened."""
    for index, taken in enumerate(slots):
        if taken is None:
            return index
    return len(slots)


def shrunk_top(area, bar, below_heights, margin=MARGIN, gap=GAP):
    """Where a parked bar's top edge goes.

    ``area`` is the working area (left, top, width, height) of the screen the
    window is on - its top can be negative on a monitor above the primary.
    ``below_heights`` are the bars already parked beneath this one.
    """
    stacked = 0.0
    for height in below_heights:
        stacked += height + gap
    return area[1] + area[3] - margin - bar - stacked


def parked_left(left, width, area):
    """Keep the bar horizontally on the screen it is parking on."""
    return clamp(left, area[0], area[0] + area[2] - width)


def expand_rect(saved_left, saved_top, width, height, bar_now, parked_at,
                area, tolerance=DRAG_TOLERANCE):
    """Where the window opens to.

    Not dragged: exactly where it was before it shrank. Dragged somewhere
    else: from where the bar now sits, kept on that screen, so it opens upward
    when the bar is down at the taskbar rather than jumping back to a place the
    user has already moved on from.
    """
    moved = (abs(bar_now[0] - parked_at[0]) > tolerance or
             abs(bar_now[1] - parked_at[1]) > tolerance)
    if not moved:
        return saved_left, saved_top
    left = clamp(bar_now[0], area[0], area[0] + area[2] - width)
    top = clamp(bar_now[1], area[1], area[1] + area[3] - height)
    return left, top


# ===========================================================================
# WPF access - lazy, so the bench can stand in for it
# ===========================================================================

class _Wpf(object):
    pass


def real_wpf():
    import csc_clr  # noqa: F401  assemblies first
    from System.Windows import (Window, Visibility, VerticalAlignment,
                                SizeToContent, ResizeMode, CornerRadius,
                                Point)
    wpf = _Wpf()
    wpf.visible = Visibility.Visible
    wpf.collapsed = Visibility.Collapsed
    wpf.top = VerticalAlignment.Top
    wpf.manual = SizeToContent.Manual
    wpf.no_resize = ResizeMode.NoResize
    wpf.top_prop = Window.TopProperty
    wpf.height_prop = Window.HeightProperty
    wpf.corner = lambda radius: CornerRadius(radius)
    wpf.point = lambda x, y: Point(x, y)
    return wpf


class DispatcherTicker(object):
    """A DispatcherTimer behind a start / stop interface."""

    def __init__(self, interval_ms, callback):
        import csc_clr  # noqa: F401
        from System import TimeSpan
        from System.Windows.Threading import DispatcherTimer
        self._callback = callback
        self._timer = DispatcherTimer()
        self._timer.Interval = TimeSpan.FromMilliseconds(interval_ms)
        self._timer.Tick += self._on_tick

    def _on_tick(self, sender, args):
        self._callback()

    def start(self):
        self._timer.Start()

    def stop(self):
        self._timer.Stop()


def screen_work_area(window):
    """Working area of the screen the window is on, in WPF units.

    The screen comes from the window's own handle, and its pixel rectangle is
    divided by the window's DPI scale. Falls back to the primary screen.
    """
    import csc_clr  # noqa: F401
    try:
        from System.Windows import PresentationSource
        from System.Windows.Interop import WindowInteropHelper
        from System.Windows.Forms import Screen
        handle = WindowInteropHelper(window).Handle
        rect = Screen.FromHandle(handle).WorkingArea
        scale_x = 1.0
        scale_y = 1.0
        source = PresentationSource.FromVisual(window)
        if source is not None and source.CompositionTarget is not None:
            matrix = source.CompositionTarget.TransformToDevice
            scale_x = matrix.M11 or 1.0
            scale_y = matrix.M22 or 1.0
        return (rect.Left / scale_x, rect.Top / scale_y,
                rect.Width / scale_x, rect.Height / scale_y)
    except Exception:
        from System.Windows import SystemParameters
        area = SystemParameters.WorkArea
        return (area.Left, area.Top, area.Width, area.Height)


# ===========================================================================
# the drawer
# ===========================================================================

_SLOTS = []      # parked bars, bottom slot first; None where a bar reopened


def _take_slot(drawer):
    index = free_slot(_SLOTS)
    if index == len(_SLOTS):
        _SLOTS.append(drawer)
    else:
        _SLOTS[index] = drawer
    return index


def _release_slot(drawer):
    for index, taken in enumerate(_SLOTS):
        if taken is drawer:
            _SLOTS[index] = None
    while _SLOTS and _SLOTS[-1] is None:
        _SLOTS.pop()


def _heights_below(index):
    return [d.bar for d in _SLOTS[:index] if d is not None]


class _Saved(object):
    def __init__(self, window):
        self.left = window.Left
        self.top = window.Top
        self.width = window.ActualWidth
        self.height = window.ActualHeight
        self.min_height = window.MinHeight
        self.size_to_content = window.SizeToContent
        self.resize_mode = window.ResizeMode


class WindowDrawer(object):
    """One per window. ``owner`` is the drawer of the window this one belongs
    to - a dialog takes its owner down with it and brings it back."""

    def __init__(self, window, header, button, shrink_glyph, expand_glyph,
                 wpf=None, ticker=None, clock=None, work_area=None):
        self.window = window
        self.header = header
        self.button = button
        self.shrink_glyph = shrink_glyph
        self.expand_glyph = expand_glyph
        self.owner = None
        self.state = OPEN
        self.bar = 0.0
        self.slot = None
        self.saved = None
        self.parked_at = (0.0, 0.0)
        self._wpf = wpf
        self._ticker_factory = ticker or DispatcherTicker
        self._clock = clock or time.time
        self._work_area = work_area or screen_work_area
        self._ticker = None
        self._hidden = []
        self._corner = None
        self._pin_saved = None
        self._from = 0.0
        self._to = 0.0
        self._done = None
        self._t0 = 0.0
        self.paint()

    # -- state ---------------------------------------------------------------

    @property
    def wpf(self):
        if self._wpf is None:
            self._wpf = real_wpf()
        return self._wpf

    @property
    def parked(self):
        return self.state == PARKED

    @property
    def busy(self):
        return self.state in (CLOSING, OPENING)

    # -- gestures ------------------------------------------------------------

    def toggle(self):
        if self.busy:
            return
        if self.parked:
            self.expand()
        elif self.state == OPEN:
            self.shrink()

    def shrink(self, animate=True):
        if self.state != OPEN:
            return
        if self.owner is not None and self.owner.state == OPEN:
            # a dialog does not leave its owner standing over Revit
            self.owner.shrink(animate=False)

        window = self.window
        wpf = self.wpf
        self._release()
        self.saved = _Saved(window)
        try:
            window.SizeToContent = wpf.manual
        except Exception:
            pass
        try:
            window.MinHeight = 0
        except Exception:
            pass
        try:
            window.ResizeMode = wpf.no_resize
        except Exception:
            pass
        self._pin()

        self.bar = self._measure_bar()
        area = self._area()
        self.slot = _take_slot(self)
        top = shrunk_top(area, self.bar, _heights_below(self.slot))
        left = parked_left(window.Left, self.saved.width, area)
        self.parked_at = (left, top)
        self.state = CLOSING
        try:
            window.Left = left
        except Exception:
            pass
        self._slide(window.Top, top, self._land_parked, animate)

    def expand(self, animate=True):
        if self.state != PARKED:
            return
        if self.owner is not None and self.owner.parked:
            # the owner comes back first, so the dialog opens over it
            self.owner.expand(animate=False)

        window = self.window
        saved = self.saved
        self._release()
        bar_now = (window.Left, window.Top)
        left, top = expand_rect(saved.left, saved.top, saved.width,
                                saved.height, bar_now, self.parked_at,
                                self._area())
        _release_slot(self)
        self.slot = None
        self._show_siblings()
        self._round_header(False)
        try:
            window.Height = saved.height
        except Exception:
            pass
        try:
            window.Left = left
        except Exception:
            pass
        self.state = OPENING
        self._slide(window.Top, top, self._land_open, animate)

    # -- event handlers ------------------------------------------------------

    def on_button(self, sender, args):
        self.toggle()

    def header_down(self, sender, args):
        """Header MouseLeftButtonDown: double-click reopens, otherwise drag."""
        try:
            if args.ClickCount >= 2:
                if self.parked:
                    self.expand()
                    args.Handled = True
                return
        except Exception:
            pass
        if self.busy:
            return
        try:
            self.window.DragMove()
        except Exception:
            pass

    def handle_key(self, name, ctrl, shift):
        """True when the key belongs to the drawer and should go no further."""
        if self.busy:
            return True
        hotkey = ctrl and shift and name == "H"
        if self.parked:
            if hotkey or name in REOPEN_KEYS:
                self.expand()
            # every other key is swallowed: nothing acts on a hidden window
            return True
        if hotkey:
            self.shrink()
            return True
        return False

    def key_action(self, name, ctrl, shift):
        """What a key press does: "drawer" (it was the drawer's), "close"
        (Esc on an open window - what pyRevit's own Esc handler did before the
        drawer took Esc over), or None (let the window have it)."""
        if self.handle_key(name, ctrl, shift):
            return "drawer"
        if name == "Escape":
            return "close"
        return None

    def on_preview_key(self, sender, args):
        try:
            import csc_clr  # noqa: F401
            from System.Windows.Input import Keyboard, ModifierKeys
            mods = Keyboard.Modifiers
            ctrl = (mods & ModifierKeys.Control) == ModifierKeys.Control
            shift = (mods & ModifierKeys.Shift) == ModifierKeys.Shift
            name = str(args.Key)
        except Exception:
            return
        action = self.key_action(name, ctrl, shift)
        if action is None:
            return
        args.Handled = True
        if action == "close":
            try:
                self.window.Close()
            except Exception:
                pass

    def on_closed(self, sender, args):
        self._stop()
        was_away = self.state != OPEN
        _release_slot(self)
        self.slot = None
        self.state = OPEN
        if was_away and self.owner is not None and self.owner.parked:
            # closing a parked dialog brings its owner back
            self.owner.expand(animate=False)

    # -- the slide -----------------------------------------------------------

    def _slide(self, start, end, on_done, animate):
        if not animate or SLIDE_SECONDS <= 0:
            self._finish(end, on_done)
            return
        self._from = start
        self._to = end
        self._done = on_done
        self._t0 = self._clock()
        try:
            self._ticker = self._ticker_factory(TICK_MS, self._tick)
            self._ticker.start()
        except Exception:
            self._ticker = None
            self._finish(end, on_done)

    def _tick(self):
        if self._ticker is None:
            return
        try:
            progress = (self._clock() - self._t0) / SLIDE_SECONDS
            if progress >= 1.0:
                self._stop()
                self._finish(self._to, self._done)
                return
            self.window.Top = lerp(self._from, self._to, ease_out(progress))
        except Exception:
            # a frame that throws lands the window rather than stranding it
            self._stop()
            self._finish(self._to, self._done)

    def _stop(self):
        ticker = self._ticker
        self._ticker = None
        if ticker is not None:
            try:
                ticker.stop()
            except Exception:
                pass

    def _finish(self, end, on_done):
        try:
            self.window.Top = end
        except Exception:
            pass
        if on_done is not None:
            on_done()

    def _land_parked(self):
        window = self.window
        try:
            window.Height = self.bar
        except Exception:
            pass
        self._hide_siblings()
        self._round_header(True)
        self._unpin()
        self.state = PARKED
        self.paint()

    def _land_open(self):
        window = self.window
        saved = self.saved
        try:
            window.MinHeight = saved.min_height
        except Exception:
            pass
        try:
            window.SizeToContent = saved.size_to_content
        except Exception:
            pass
        try:
            window.ResizeMode = saved.resize_mode
        except Exception:
            pass
        self.state = OPEN
        self.paint()
        try:
            window.Activate()
        except Exception:
            pass

    # -- pieces --------------------------------------------------------------

    def _release(self):
        """Drop anything holding Top or Height, each in its own try."""
        wpf = self.wpf
        try:
            self.window.BeginAnimation(wpf.top_prop, None)
        except Exception:
            pass
        try:
            self.window.BeginAnimation(wpf.height_prop, None)
        except Exception:
            pass

    def _measure_bar(self):
        header = self.header
        offset = 2.0
        try:
            offset = header.TranslatePoint(self.wpf.point(0, 0), self.window).Y
        except Exception:
            pass
        try:
            return bar_height(header.ActualHeight, offset)
        except Exception:
            return 48.0

    def _area(self):
        try:
            return self._work_area(self.window)
        except Exception:
            return (0.0, 0.0, 1920.0, 1040.0)

    def _pin(self):
        content = getattr(self.window, "Content", None)
        if content is None:
            return
        try:
            self._pin_saved = (content.Height, content.VerticalAlignment)
            content.Height = content.ActualHeight
            content.VerticalAlignment = self.wpf.top
        except Exception:
            self._pin_saved = None

    def _unpin(self):
        content = getattr(self.window, "Content", None)
        saved = self._pin_saved
        self._pin_saved = None
        if content is None or saved is None:
            return
        try:
            content.Height = saved[0]
        except Exception:
            pass
        try:
            content.VerticalAlignment = saved[1]
        except Exception:
            pass

    def _hide_siblings(self):
        self._hidden = []
        parent = getattr(self.header, "Parent", None)
        children = getattr(parent, "Children", None)
        if children is None:
            return
        for child in list(children):
            if child is self.header:
                continue
            try:
                self._hidden.append((child, child.Visibility))
                child.Visibility = self.wpf.collapsed
            except Exception:
                pass

    def _show_siblings(self):
        hidden = self._hidden
        self._hidden = []
        for child, visibility in hidden:
            try:
                child.Visibility = visibility
            except Exception:
                pass

    def _round_header(self, parked):
        try:
            if parked:
                self._corner = self.header.CornerRadius
                self.header.CornerRadius = self.wpf.corner(PARKED_CORNER)
            elif self._corner is not None:
                self.header.CornerRadius = self._corner
                self._corner = None
        except Exception:
            pass

    def paint(self):
        """Down-arrow-onto-a-bar while open, green up arrow while parked."""
        wpf = self._wpf
        if wpf is None:
            try:
                wpf = self.wpf
            except Exception:
                return
        away = self.state == PARKED
        try:
            self.shrink_glyph.Visibility = wpf.collapsed if away else wpf.visible
            self.expand_glyph.Visibility = wpf.visible if away else wpf.collapsed
        except Exception:
            pass
        try:
            self.button.ToolTip = EXPAND_TIP if away else SHRINK_TIP
        except Exception:
            pass


def attach(window, owner=None):
    """Give a window its drawer and wire the button, keys and close.

    The window's layout must name ``header_bar``, ``shrink_btn``,
    ``shrink_glyph`` and ``expand_glyph``; ``import_check.py`` holds every
    layout in the tool to that.
    """
    drawer = WindowDrawer(window, window.header_bar, window.shrink_btn,
                          window.shrink_glyph, window.expand_glyph)
    drawer.owner = owner
    window.shrink_btn.Click += drawer.on_button
    window.PreviewKeyDown += drawer.on_preview_key
    window.Closed += drawer.on_closed
    return drawer
