# -*- coding: utf-8 -*-
"""RevoBIM PY - Filter Manager : shrink a window to its title bar.

The shrink button (top right, before full screen and close) slides the
window down like a drawer until only its header bar is left, floating just
above the taskbar, so the model can be seen. The button turns into a green
up arrow; that, or a double click on the bar, slides it back.

The same pattern as Pro Sheets' Chrome and Hanger Automation's Drawer:

- Top and Height are eased together on a 15 ms DispatcherTimer for 0.28 s
  (ease-out cubic). A Storyboard on a window's Top/Height fights the layout
  pass, so the frames are driven by hand.
- The body is collapsed only once the bar has landed, and shown again
  before the slide back, so the content never jumps.
- Several bars stack upwards from the bottom of the screen rather than
  landing on top of each other.
- A dialog shrinks its owners first, otherwise the main window would stay
  over Revit. Expanding the dialog, or closing it, brings them back.
  A modal dialog still holds Revit while it is open - shrinking it shows
  the model, it cannot free it.
- While shrunk the bar still drags; resizing and full screen are refused.

The maths at the top is plain Python so the bench can test it.
"""

import fm_clr  # noqa  - must be first

DURATION = 0.28      # seconds, either way
TICK_MS = 15
MARGIN = 8           # gap between the lowest bar and the taskbar
GAP = 4              # gap between stacked bars

_DRAWERS = []        # every live drawer, so bars can stack


# ---------------------------------------------------------------------------
#  Pure maths
# ---------------------------------------------------------------------------
def ease_out(p):
    """Fast start, gentle landing. 0 -> 0, 1 -> 1, never overshoots."""
    p = max(0.0, min(1.0, float(p)))
    return 1.0 - (1.0 - p) ** 3


def lerp(a, b, t):
    return a + (b - a) * t


def shrunk_top(area_top, area_height, bar, below, margin=MARGIN, gap=GAP):
    """Where a bar lands: the bottom of the working area, above any bars
    already shrunk there. `below` is the heights of those bars."""
    used = 0.0
    for h in below or []:
        used += float(h) + gap
    top = area_top + area_height - margin - used - bar
    return max(area_top, top)


def frame(start, end, elapsed, duration=DURATION):
    """(top, height, finished) for a moment in the slide."""
    if duration <= 0:
        return end[0], end[1], True
    p = min(1.0, max(0.0, elapsed / float(duration)))
    t = ease_out(p)
    return (lerp(start[0], end[0], t), lerp(start[1], end[1], t), p >= 1.0)


# ---------------------------------------------------------------------------
#  The drawer
# ---------------------------------------------------------------------------
def drawer_of(window):
    for d in _DRAWERS:
        try:
            if d.window is window or d.window.Equals(window):
                return d
        except Exception:
            continue
    return None


class Drawer(object):
    """Shrink and expand one window. Needs, in the window's layout:
    `pnlHeader` (the header bar, a direct child of the root panel),
    `btnShrink`, and inside it `pthShrink` and `pthExpand`."""

    def __init__(self, window, clock=None, timer_factory=None):
        self.window = window
        self.shrunk = False
        self.moving = False
        self.saved = None
        self.hidden = []
        self.lifted = []         # owners this window shrank on its way down
        self.bar = 0.0
        self._clock = clock
        self._timer_factory = timer_factory
        self._timer = None
        self._tick = None        # the handler is held, or IronPython's
        self._job = None         # delegate is collected mid-slide
        _DRAWERS.append(self)
        try:
            window.Closed += self._on_closed
        except Exception:
            pass

    # -- lookups ------------------------------------------------------------
    def part(self, name):
        try:
            return self.window.FindName(name)
        except Exception:
            return None

    def now(self):
        if self._clock is not None:
            return self._clock()
        import time
        return time.time()

    def bar_height(self):
        header = self.part("pnlHeader")
        w = self.window
        border = 0.0
        try:
            border = w.BorderThickness.Top + w.BorderThickness.Bottom
        except Exception:
            pass
        try:
            return float(header.ActualHeight) + border
        except Exception:
            return 44.0

    def others_below(self):
        """Heights of the bars already sitting at the bottom of the screen."""
        heights = []
        for d in _DRAWERS:
            if d is self or not (d.shrunk or d.moving and d._job == "down"):
                continue
            heights.append(d.bar)
        return heights

    # -- public -------------------------------------------------------------
    def toggle(self):
        if self.shrunk:
            self.expand()
        else:
            self.shrink()

    def shrink(self):
        if self.shrunk or self.moving:
            return
        w = self.window

        # owners first, so the main window does not stay over Revit
        self.lifted = []
        owner = self._owner(w)
        while owner is not None:
            od = drawer_of(owner)
            if od is not None and not od.shrunk and not od.moving:
                od.shrink_now()
                self.lifted.append(od)
            owner = self._owner(owner)

        self.saved = self._snapshot()
        self.bar = self.bar_height()
        try:
            from System.Windows import SizeToContent
            w.SizeToContent = SizeToContent.Manual
        except Exception:
            pass
        w.MinHeight = 0

        left, top, width, height = self._area()
        end_top = shrunk_top(top, height, self.bar, self.others_below())
        self._slide((w.Top, w.Height), (end_top, self.bar), "down")

    def expand(self):
        if not self.shrunk or self.moving:
            return
        w = self.window
        self._show_parts()
        self._set_glyph(False)
        saved = self.saved or (w.Left, w.Top, w.Width, 600.0, 0.0, None, None)
        # if the bar was dragged, grow up out of where it is now, kept on
        # the screen; otherwise go back where it came from
        left, a_top, a_w, a_h = self._area()
        target_top = saved[1]
        if abs(w.Top - self._landed_top) > 2 or abs(w.Left - saved[0]) > 2:
            target_top = max(a_top, min(w.Top + self.bar - saved[3],
                                        a_top + a_h - saved[3]))
        else:
            w.Left = saved[0]
        self.shrunk = False
        self._slide((w.Top, w.Height), (target_top, saved[3]), "up")

    def shrink_now(self):
        """No animation - used for an owner going down with its dialog."""
        if self.shrunk or self.moving:
            return
        w = self.window
        self.saved = self._snapshot()
        self.bar = self.bar_height()
        try:
            from System.Windows import SizeToContent
            w.SizeToContent = SizeToContent.Manual
        except Exception:
            pass
        w.MinHeight = 0
        _l, top, _w, height = self._area()
        w.Top = shrunk_top(top, height, self.bar, self.others_below())
        w.Height = self.bar
        self._landed()

    def restore_now(self):
        """No animation - the window put straight back."""
        if not self.shrunk:
            return
        self._stop()
        self._show_parts()
        self._set_glyph(False)
        self.shrunk = False
        self._restore_saved(True)

    # -- the slide ----------------------------------------------------------
    def _slide(self, start, end, job):
        self._stop()
        self.moving = True
        self._job = job
        self._start = start
        self._end = end
        self._t0 = self.now()

        def tick(sender, args):
            try:
                self._step()
            except Exception:
                self._finish()

        self._tick = tick
        self._timer = self._make_timer(tick)
        if self._timer is None:
            self._finish()

    def _step(self):
        top, height, done = frame(self._start, self._end,
                                  self.now() - self._t0)
        w = self.window
        w.Top = top
        w.Height = max(1.0, height)
        if done:
            self._finish()

    def _finish(self):
        self._stop()
        w = self.window
        try:
            w.Top, w.Height = self._end[0], max(1.0, self._end[1])
        except Exception:
            pass
        job = self._job
        self.moving = False
        self._job = None
        if job == "down":
            self._landed()
        else:
            self._restore_saved(False)
            for od in reversed(self.lifted):
                od.restore_now()
            self.lifted = []
            try:
                w.Activate()
            except Exception:
                pass

    def _make_timer(self, tick):
        if self._timer_factory is not None:
            return self._timer_factory(TICK_MS, tick)
        try:
            from System.Windows.Threading import DispatcherTimer
            from System import TimeSpan
            timer = DispatcherTimer()
            timer.Interval = TimeSpan.FromMilliseconds(TICK_MS)
            timer.Tick += tick
            timer.Start()
            return timer
        except Exception:
            return None

    def _stop(self):
        if self._timer is not None:
            try:
                self._timer.Stop()
            except Exception:
                pass
        self._timer = None

    # -- states -------------------------------------------------------------
    def _landed(self):
        self._hide_parts()
        self._set_glyph(True)
        self._landed_top = self.window.Top
        try:
            from System.Windows import ResizeMode
            self.window.ResizeMode = ResizeMode.NoResize
        except Exception:
            pass
        self.shrunk = True

    _landed_top = 0.0

    def _snapshot(self):
        w = self.window
        return (w.Left, w.Top, w.Width, w.ActualHeight or w.Height,
                w.MinHeight, self._get(w, "SizeToContent"),
                self._get(w, "ResizeMode"))

    def _restore_saved(self, move):
        if not self.saved:
            return
        w = self.window
        left, top, width, height, min_h, size_to, resize = self.saved
        if move:
            w.Left, w.Top = left, top
            w.Height = height
        try:
            w.MinHeight = min_h
        except Exception:
            pass
        if resize is not None:
            try:
                w.ResizeMode = resize
            except Exception:
                pass
        if size_to is not None:
            try:
                w.SizeToContent = size_to
            except Exception:
                pass
        self.saved = None

    def _get(self, w, name):
        try:
            return getattr(w, name)
        except Exception:
            return None

    # -- the body -----------------------------------------------------------
    def _hide_parts(self):
        from System.Windows import Visibility
        header = self.part("pnlHeader")
        self.hidden = []
        if header is None:
            return
        try:
            parent = header.Parent
            for child in parent.Children:
                if child is header or child.Equals(header):
                    continue
                if child.Visibility == Visibility.Visible:
                    child.Visibility = Visibility.Collapsed
                    self.hidden.append(child)
        except Exception:
            pass

    def _show_parts(self):
        from System.Windows import Visibility
        for child in self.hidden:
            try:
                child.Visibility = Visibility.Visible
            except Exception:
                continue
        self.hidden = []

    def _set_glyph(self, shrunk):
        from System.Windows import Visibility
        down = self.part("pthShrink")
        up = self.part("pthExpand")
        button = self.part("btnShrink")
        try:
            down.Visibility = Visibility.Collapsed if shrunk else Visibility.Visible
            up.Visibility = Visibility.Visible if shrunk else Visibility.Collapsed
        except Exception:
            pass
        try:
            button.ToolTip = ("Expand the window again (or double click the bar)"
                              if shrunk else
                              "Shrink to the taskbar - slide the window down to "
                              "its title bar so the model can be seen")
        except Exception:
            pass

    # -- surroundings -------------------------------------------------------
    def _area(self):
        try:
            import fm_ui
            return fm_ui.working_area(self.window)
        except Exception:
            return (0.0, 0.0, 1280.0, 800.0)

    def _owner(self, window):
        try:
            return window.Owner
        except Exception:
            return None

    def _on_closed(self, sender, args):
        self._stop()
        for od in reversed(self.lifted):
            try:
                od.restore_now()
            except Exception:
                continue
        self.lifted = []
        try:
            _DRAWERS.remove(self)
        except ValueError:
            pass


def on_header_down(drawer, window, args):
    """For a header's MouseLeftButtonDown while shrunk: a double click
    expands, anything else drags the bar. True when it handled the press."""
    if drawer is None or not (drawer.shrunk or drawer.moving):
        return False
    try:
        if args.ClickCount == 2:
            drawer.expand()
            return True
    except Exception:
        pass
    try:
        window.DragMove()
    except Exception:
        pass
    return True
