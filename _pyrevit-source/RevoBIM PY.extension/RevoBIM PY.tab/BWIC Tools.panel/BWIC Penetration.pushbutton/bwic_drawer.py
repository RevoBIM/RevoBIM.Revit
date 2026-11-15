# -*- coding: utf-8 -*-
"""Shrink a window to its header bar, like a drawer closing, and back.

One helper for every window the tool opens, so the gesture is identical
between the main window and Settings. Follows the RevoBIM shrink-to-taskbar
standard: Top and Height eased together on a 15 ms DispatcherTimer over
0.28 s, landing 8 px above the bottom of the screen's working area, bars
stacked 4 px apart.

The arithmetic is in plain functions at the top so the bench can prove it in
CPython without WPF. The WPF names are imported in a try, so this module also
imports cleanly outside Revit.
"""

# ---------------------------------------------------------------------------
# pure arithmetic -- proved by import_check.py
# ---------------------------------------------------------------------------

DURATION_S = 0.28
TICK_MS = 15
MARGIN = 8.0        # clear of the taskbar
GAP = 4.0           # between stacked bars
MOVED = 2.0         # a bar dragged further than this has been moved

SHRINK_GLYPH = u'⤓'    # down arrow onto a bar
EXPAND_GLYPH = u'⤒'    # up arrow from a bar


def ease_out(p):
    """Cubic ease out, clamped to 0..1."""
    if p <= 0.0:
        return 0.0
    if p >= 1.0:
        return 1.0
    return 1.0 - (1.0 - p) ** 3


def lerp(a, b, t):
    return a + (b - a) * t


def bar_height(header_height, header_offset):
    """The parked window: its header plus the frame above it, twice over.

    Taking the same inset below the header as above it keeps the header
    centred in the bar rather than sitting on its bottom edge.
    """
    return header_height + 2.0 * header_offset


def free_slot(taken):
    """The lowest stacking slot no other parked bar is using."""
    slot = 0
    used = set(taken)
    while slot in used:
        slot += 1
    return slot


def shrunk_top(area, bar, slot, margin=MARGIN, gap=GAP):
    """Where a parked bar sits: bottom of the working area, stacked by slot.

    `area` is (left, top, width, height) in WPF units. The top is NOT clamped
    to zero: a monitor above the primary has a negative work-area top, and
    clamping to zero is what sends the bar to the wrong screen.
    """
    left, top, width, height = area
    y = top + height - margin - bar - slot * (bar + gap)
    return max(y, top)


def clamp_rect(left, top, width, height, area):
    """Keep a window of this size inside the working area."""
    a_left, a_top, a_width, a_height = area
    left = min(max(left, a_left), a_left + max(0.0, a_width - width))
    top = min(max(top, a_top), a_top + max(0.0, a_height - height))
    return left, top


def expand_target(saved, landed, current, bar, area):
    """Where the window opens back to.

    `saved` is (left, top, width, height) before it shrank, `landed` the
    (left, top) the bar was parked at, `current` where the bar is now.

    A bar left where it landed goes home. A bar the user has dragged opens
    upward from where it now sits -- they have moved on from the old spot --
    and either way the result is kept on the screen.
    """
    s_left, s_top, s_width, s_height = saved
    moved = abs(current[0] - landed[0]) > MOVED \
        or abs(current[1] - landed[1]) > MOVED
    if moved:
        left = current[0]
        top = current[1] + bar - s_height
    else:
        left, top = s_left, s_top
    left, top = clamp_rect(left, top, s_width, s_height, area)
    return left, top, moved


# ---------------------------------------------------------------------------
# WPF
# ---------------------------------------------------------------------------

try:
    import clr
    clr.AddReference('PresentationCore')
    clr.AddReference('PresentationFramework')
    clr.AddReference('WindowsBase')
    try:
        clr.AddReference('System.Windows.Forms')
    except Exception:
        pass
    from System import TimeSpan, Double
    from System.Diagnostics import Stopwatch
    from System.Windows import (Window, Visibility, VerticalAlignment,
                                SizeToContent, PresentationSource, Point)
    from System.Windows.Input import Key, Keyboard, ModifierKeys
    from System.Windows.Interop import WindowInteropHelper
    from System.Windows.Threading import DispatcherTimer
    HAVE_WPF = True
except Exception:
    HAVE_WPF = False


# every parked drawer and the slot it holds, so bars stack instead of
# landing on top of each other
_SLOTS = {}


def work_area(window):
    """The working area of the screen the window is on, in WPF units."""
    scale = 1.0
    try:
        source = PresentationSource.FromVisual(window)
        if source is not None:
            scale = source.CompositionTarget.TransformToDevice.M22 or 1.0
    except Exception:
        pass
    try:
        from System.Windows.Forms import Screen
        handle = WindowInteropHelper(window).Handle
        wa = Screen.FromHandle(handle).WorkingArea
        return (wa.Left / scale, wa.Top / scale,
                wa.Width / scale, wa.Height / scale)
    except Exception:
        return (0.0, 0.0, 1920.0, 1040.0)


class Drawer(object):
    """Shrink a borderless window to its header and bring it back.

    window  -- the WPF window
    header  -- its header element; everything beside it is hidden while parked
    button  -- the shrink button; its Tag becomes 'shrunk' to swap the glyph
    grips   -- the resize-grip overlay, parked with the window
    lift    -- the owner's Drawer, for a dialog: shrinking the dialog parks
               the owner too, so the main window does not stay over Revit
    """

    def __init__(self, window, header, button, grips=None, lift=None):
        self.window = window
        self.header = header
        self.body = header.Parent if header is not None else None
        self.button = button
        self.grips = grips
        self.lift = lift
        self.lifted = False

        self.shrunk = False
        self.busy = False
        # 'parked' from the moment a shrink starts, 'open' from the moment an
        # expand starts -- what the window is about to be, for on_change
        self.heading = 'open'
        self.on_change = None
        self.saved = None
        self.landed = None
        self.bar = 0.0
        self.hidden = []

        self._timer = None
        self._tick_handler = None
        self._clock = None
        self._from = None
        self._to = None
        self._done = None

        try:
            window.Closed += self._on_closed
        except Exception:
            pass

    # -- public ------------------------------------------------------------
    def toggle(self):
        if self.busy:
            return
        if self.shrunk:
            self.expand()
        else:
            self.shrink()

    def true_size(self):
        """The window's real size, not the parked bar's."""
        if self.shrunk and self.saved:
            return self.saved['width'], self.saved['height']
        return self.window.ActualWidth, self.window.ActualHeight

    def shrink(self, animate=True):
        if self.shrunk or self.busy:
            return
        # a dialog parks its owner first and stacks above it
        if self.lift is not None and not self.lift.shrunk:
            try:
                self.lift.shrink(animate=False)
                self.lifted = True
            except Exception:
                self.lifted = False

        w = self.window
        self.saved = {
            'left': w.Left, 'top': w.Top,
            'width': w.ActualWidth, 'height': w.ActualHeight,
            'min_height': w.MinHeight,
            'size_to_content': w.SizeToContent,
            'resize_mode': w.ResizeMode,
        }

        # MinHeight and SizeToContent both veto a Height change, and a vetoed
        # one leaves the window half shut
        w.SizeToContent = SizeToContent.Manual
        w.Height = self.saved['height']
        w.MinHeight = 0

        self._pin_body()
        self._park_grips(True)

        area = work_area(w)
        self.bar = self._measure_bar()
        slot = free_slot([s for d, s in _SLOTS.items() if d is not self])
        _SLOTS[self] = slot
        top = shrunk_top(area, self.bar, slot)
        self.landed = (w.Left, top)

        self.busy = True
        self._heading('parked')
        self._run((w.Top, w.Height), (top, self.bar), self._landed,
                  animate)

    def expand(self, animate=True):
        if not self.shrunk or self.busy:
            return
        w = self.window
        area = work_area(w)
        saved = (self.saved['left'], self.saved['top'],
                 self.saved['width'], self.saved['height'])
        left, top, moved = expand_target(saved, self.landed,
                                         (w.Left, w.Top), self.bar, area)

        # the body comes back BEFORE the slide, still pinned to its old
        # height, so the window opens over it rather than re-measuring it
        self._show_parts()
        self.button.Tag = ''
        self._set_tip('Shrink to the taskbar  (Ctrl+Shift+H)')
        self.shrunk = False
        self._heading('open')
        w.Left = left

        self.busy = True
        self._run((w.Top, w.Height), (top, self.saved['height']),
                  self._reopened, animate)

    def restore_now(self):
        """Put the window back at once, no animation."""
        if self.busy:
            self._finish_now()
        if self.shrunk:
            self.expand(animate=False)

    # -- keyboard and header -----------------------------------------------
    def handle_key(self, args):
        """Ctrl+Shift+H toggles. While parked, Esc, Enter and F11 reopen."""
        try:
            key = args.Key
            mods = Keyboard.Modifiers
            # compare the masked value: truthiness of a flags enum is not
            # reliable in IronPython
            ctrl_shift = ModifierKeys.Control | ModifierKeys.Shift
            if key == Key.H and (mods & ctrl_shift) == ctrl_shift:
                self.toggle()
                args.Handled = True
                return True
            if self.shrunk and key in (Key.Escape, Key.Enter, Key.Return,
                                       Key.F11):
                self.expand()
                args.Handled = True
                return True
        except Exception:
            pass
        return False

    def header_down(self, args):
        """A double click on the parked bar reopens it; a single one drags."""
        try:
            if self.shrunk and args.ClickCount >= 2:
                self.expand()
                args.Handled = True
                return True
        except Exception:
            pass
        return False

    # -- the slide ---------------------------------------------------------
    def _run(self, start, end, done, animate):
        self._from, self._to, self._done = start, end, done
        if not animate:
            self._finish_now()
            return
        try:
            self._clock = Stopwatch.StartNew()
            self._timer = DispatcherTimer()
            self._timer.Interval = TimeSpan.FromMilliseconds(TICK_MS)
            # held on the instance, so it can be taken off again and is not
            # collected mid slide
            self._tick_handler = self._on_tick
            self._timer.Tick += self._tick_handler
            self._timer.Start()
        except Exception:
            self._finish_now()

    def _on_tick(self, sender, args):
        try:
            p = self._clock.Elapsed.TotalSeconds / DURATION_S
            t = ease_out(p)
            self.window.Top = lerp(self._from[0], self._to[0], t)
            self.window.Height = max(1.0, lerp(self._from[1], self._to[1], t))
            if p >= 1.0:
                self._finish_now()
        except Exception:
            # a frame that throws lands the window at its end state
            self._finish_now()

    def _finish_now(self):
        self._stop_timer()
        # an animation holds its end value and outranks every later plain
        # assignment, so anything holding Top or Height is released first --
        # in its own try, because this is also the fallback path
        try:
            self.window.BeginAnimation(Window.TopProperty, None)
            self.window.BeginAnimation(Window.HeightProperty, None)
        except Exception:
            pass
        try:
            if self._to is not None:
                self.window.Top = self._to[0]
                self.window.Height = max(1.0, self._to[1])
        except Exception:
            pass
        done, self._done = self._done, None
        self.busy = False
        if done is not None:
            try:
                done()
            except Exception:
                pass

    def _heading(self, heading):
        self.heading = heading
        if self.on_change is not None:
            try:
                self.on_change(heading)
            except Exception:
                pass

    def _stop_timer(self):
        if self._timer is not None:
            try:
                self._timer.Stop()
                if self._tick_handler is not None:
                    self._timer.Tick -= self._tick_handler
            except Exception:
                pass
        self._timer = None
        self._tick_handler = None

    # -- end states --------------------------------------------------------
    def _landed(self):
        self._hide_parts()
        self.shrunk = True
        self.button.Tag = 'shrunk'
        self._set_tip('Open the window again  (Esc, Enter or double click '
                      'the bar)')

    def _reopened(self):
        w = self.window
        try:
            w.MinHeight = self.saved['min_height']
        except Exception:
            pass
        self._unpin_body()
        self._park_grips(False)
        try:
            w.SizeToContent = self.saved['size_to_content']
        except Exception:
            pass
        _SLOTS.pop(self, None)
        if self.lifted and self.lift is not None:
            self.lifted = False
            try:
                self.lift.restore_now()
            except Exception:
                pass
        try:
            w.Activate()
        except Exception:
            pass

    def _on_closed(self, sender, args):
        self._stop_timer()
        _SLOTS.pop(self, None)
        if self.lifted and self.lift is not None:
            self.lifted = False
            try:
                self.lift.restore_now()
            except Exception:
                pass

    # -- parts -------------------------------------------------------------
    def _measure_bar(self):
        try:
            offset = self.header.TranslatePoint(Point(0, 0), self.window).Y
            return bar_height(self.header.ActualHeight, offset)
        except Exception:
            return 60.0

    def _pin_body(self):
        """Hold the layout at its size so it is drawn away, not squashed."""
        if self.body is None:
            return
        try:
            self.body.Height = self.body.ActualHeight
            self.body.VerticalAlignment = VerticalAlignment.Top
        except Exception:
            pass

    def _unpin_body(self):
        if self.body is None:
            return
        try:
            self.body.Height = Double.NaN
            self.body.VerticalAlignment = VerticalAlignment.Stretch
        except Exception:
            pass

    def _park_grips(self, parked):
        """The grips span every row; left visible they swallow the arrow."""
        if self.grips is None:
            return
        try:
            self.grips.Visibility = Visibility.Collapsed if parked \
                else Visibility.Visible
        except Exception:
            pass

    def _hide_parts(self):
        """Collapse everything beside the header, remembering what was what."""
        self.hidden = []
        if self.body is None:
            return
        try:
            for child in self.body.Children:
                if child is self.header:
                    continue
                self.hidden.append((child, child.Visibility))
                child.Visibility = Visibility.Collapsed
        except Exception:
            pass

    def _show_parts(self):
        """Put each part back as it was -- a hidden panel stays hidden."""
        for child, was in self.hidden:
            try:
                child.Visibility = was
            except Exception:
                pass
        self.hidden = []

    def _set_tip(self, text):
        try:
            self.button.ToolTip = text
        except Exception:
            pass
