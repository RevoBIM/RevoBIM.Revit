# -*- coding: utf-8 -*-
u"""RevoBIM Addin Manager - shrink to taskbar, for every window the tool opens.

The house gesture (RevoBIM theme reference): the shrink button top right slides
the window down to the bottom of its screen like a drawer closing, leaving only
its header bar floating clear of the taskbar so the model can be seen and
worked in. The button turns into a green up arrow that slides it back. The
arrow, a double click on the bar, Escape, Enter or F11 reopen it; Ctrl+Shift+H
works both ways. The bar drags, and if it has been carried somewhere else the
window opens upward from where it now sits.

The five things that make or break a drawer, four of them silently, and where
each is handled here:

1. **No animation is left holding the window.** A WPF animation keeps its end
   value and outranks every later assignment, freezing the window for good.
   The slide is eased by hand on a 15 ms timer - plain assignments every
   frame - so there is nothing to release. A frame that throws lands the
   window at its end state rather than leaving it half way.
2. **MinHeight and SizeToContent each veto a Height change**, and a vetoed one
   leaves the window half shut. Both are relaxed for the slide and put back
   when it reopens. The shortcut prompt sizes to its content, so this matters.
3. **The body is pinned for the slide** at its full height, top aligned, and
   the window clips it - so nothing re-measures on every frame.
4. **The resize grips park as the slide starts.** Left up, they line the bar
   with invisible handles and swallow the click on the arrow.
5. **Keys are redirected while parked**: Escape and Enter reopen rather than
   cancelling a dialog nobody can see; F11 reopens rather than filling the
   screen with a bar; a double click reopens rather than going full screen.

Everything WPF goes through a platform object. `WpfPlatform` below is the real
one; the logic bench hands in a stand-in window, timer and clock and drives
whole slides, which is how all five are proved rather than hoped for.
"""

import rba_clr  # noqa: F401

import rba_core
import rba_ui

from rba_core import log, log_exception

# Every live drawer in this engine, so parked bars can stack rather than land
# on top of one another.
DRAWERS = []

CTRL_SHIFT_KEY = u"H"
REOPEN_KEYS = (u"Escape", u"Return", u"Enter", u"F11")


class Drawer(object):

    def __init__(self, window, header, root, glyphs, platform,
                 grips=None, owner=None, name=u"window", shortcut=True):
        u"""glyphs is (button, shrink_glyph, expand_glyph).

        shortcut=False leaves Ctrl+Shift+H to the window while it is open - the
        keyboard shortcut prompt has to be able to capture it as a shortcut.
        Parked, the drawer takes every key either way.
        """
        self.window = window
        self.header = header
        self.root = root
        self.glyphs = glyphs
        self.platform = platform
        self.grips = grips
        self.owner = owner
        self.name = name
        self.shortcut = shortcut

        self.shrunk = False
        self.sliding = False
        self.slot = None
        self.bar = 0.0
        self.saved = None            # (left, top, width, height)
        self.saved_min_height = 0.0
        self.saved_size_to_content = None
        self.landed = None           # (left, top) of the bar when it parked
        self.hidden = []             # [(element, previous visibility)]
        self.grips_token = None
        self.lifted_owner = False
        self._timer = None

        DRAWERS.append(self)
        platform.set_glyph(glyphs, False)

    # ------------------------------------------------------------ queries

    def busy(self):
        return self.sliding

    def true_bounds(self):
        u"""The window's real size, for whoever saves it on close.

        Closing a parked window must not save a 40 pixel window.
        """
        if self.saved is not None and (self.shrunk or self.sliding):
            return self.saved
        window = self.window
        return (window.Left, window.Top, window.Width,
                self.platform.actual_height(window))

    @staticmethod
    def parked_bars(exclude=None):
        out = []
        for drawer in DRAWERS:
            if drawer is exclude or drawer.slot is None:
                continue
            out.append((drawer.slot, drawer.bar))
        return out

    # ------------------------------------------------------------ gestures

    def toggle(self):
        if self.shrunk:
            self.expand()
        else:
            self.shrink()

    def on_key(self, key, ctrl, shift):
        u"""Returns True when the key was the drawer's to handle."""
        if ctrl and shift and key == CTRL_SHIFT_KEY and (self.shortcut or self.shrunk):
            if not self.sliding:
                self.toggle()
            return True
        if self.shrunk:
            if key in REOPEN_KEYS:
                self.expand()
            # Every other key is swallowed: nothing inside a parked bar should
            # be typed into.
            return True
        return False

    def on_header_double_click(self):
        if self.shrunk:
            self.expand()
            return True
        return False

    # ------------------------------------------------------------ shrink

    def shrink(self, instant=False):
        if self.shrunk or self.sliding:
            return
        owner = self.owner
        if owner is not None and not owner.shrunk and not owner.sliding:
            # A dialog takes its owner down first, so the main window is not
            # left standing over Revit, and parks its own bar above it.
            owner.shrink(instant=True)
            self.lifted_owner = True

        window = self.window
        platform = self.platform
        height = platform.actual_height(window)
        self.saved = (window.Left, window.Top, window.Width, height)
        self.saved_min_height = window.MinHeight
        self.saved_size_to_content = platform.size_to_content(window)

        # Trap 2: relax the two vetoes, then make the height explicit - a
        # window sized to its content has no Height of its own to keep.
        platform.relax(window)
        window.Height = height

        # Trap 4: the grips go as the slide starts.
        if self.grips is not None:
            self.grips_token = platform.hide(self.grips)

        # Trap 3: pin the body.
        platform.pin(self.root)

        self.bar = platform.bar_height(window, self.header)
        area = platform.work_area(window)
        parked = Drawer.parked_bars(exclude=self)
        self.slot = rba_core.free_slot([slot for slot, _bar in parked])
        target = rba_core.stacked_top(area, self.bar,
                                      rba_core.below_height(parked, self.slot))
        log(u"drawer: {0} parking in slot {1}".format(self.name, self.slot))
        self._slide(window.Top, target, self._landed_parked, instant)

    def _landed_parked(self):
        window = self.window
        platform = self.platform
        window.Height = self.bar
        skip = [self.grips] if self.grips is not None else []
        self.hidden = []
        for element in platform.siblings(self.header, window, skip):
            self.hidden.append((element, platform.hide(element)))
        platform.unpin(self.root)
        platform.round_header(self.header, True)
        self.landed = (window.Left, window.Top)
        self.shrunk = True
        platform.set_glyph(self.glyphs, True)

    # ------------------------------------------------------------ expand

    def expand(self, instant=False):
        if not self.shrunk or self.sliding:
            return
        window = self.window
        platform = self.platform
        area = platform.work_area(window)
        left, top, height = rba_core.expand_rect(
            self.saved, self.landed, (window.Left, window.Top), self.bar, area)

        # Everything back the way it was found - a closed section stays
        # closed - then the full height at once below the bar, so the slide up
        # moves the window without re-measuring it.
        for element, token in self.hidden:
            platform.show(element, token)
        self.hidden = []
        platform.round_header(self.header, False)
        window.Left = left
        window.Height = height
        self.shrunk = False
        self.slot = None
        platform.set_glyph(self.glyphs, False)
        self._slide(window.Top, top, self._landed_open, instant)

    def _landed_open(self):
        window = self.window
        platform = self.platform
        platform.restore(window, self.saved_min_height, self.saved_size_to_content)
        if self.grips is not None:
            platform.show(self.grips, self.grips_token)
        self.grips_token = None
        platform.activate(window)
        if self.lifted_owner and self.owner is not None:
            self.lifted_owner = False
            self.owner.expand()

    # ------------------------------------------------------------ the slide

    def _slide(self, start, end, done, instant):
        u"""Ease Top from start to end by hand, then call done exactly once."""
        window = self.window
        platform = self.platform
        state = {u"finished": False}

        def finish():
            if state[u"finished"]:
                return
            state[u"finished"] = True
            if self._timer is not None:
                try:
                    self._timer.stop()
                except Exception:
                    pass
                self._timer = None
            try:
                window.Top = end
            except Exception:
                log_exception(u"drawer/land")
            self.sliding = False
            try:
                done()
            except Exception:
                log_exception(u"drawer/done")

        if instant:
            self.sliding = True
            finish()
            return

        self.sliding = True
        began = platform.now()
        duration = rba_core.DRAWER_MS / 1000.0

        def tick():
            try:
                progress = (platform.now() - began) / duration
                window.Top = rba_core.tween(start, end, progress)
                if progress >= 1.0:
                    finish()
            except Exception:
                # A frame that throws lands the window rather than leaving it
                # half way down the screen.
                log_exception(u"drawer/tick")
                finish()

        try:
            self._timer = platform.timer(rba_core.DRAWER_TICK_MS, tick)
            self._timer.start()
        except Exception:
            log_exception(u"drawer/timer")
            finish()

    # ------------------------------------------------------------ closing

    def forget(self):
        u"""The window has closed: free its slot, and bring back its owner."""
        if self._timer is not None:
            try:
                self._timer.stop()
            except Exception:
                pass
            self._timer = None
        self.slot = None
        self.sliding = False
        try:
            DRAWERS.remove(self)
        except ValueError:
            pass
        if self.lifted_owner and self.owner is not None:
            self.lifted_owner = False
            if self.owner.shrunk:
                self.owner.expand()


# ----------------------------------------------------------------------
# the real platform
# ----------------------------------------------------------------------

class WpfPlatform(object):
    u"""Every WPF call the drawer makes, in one place."""

    def __init__(self):
        from System.Diagnostics import Stopwatch
        self._stopwatch = Stopwatch.StartNew()

    def now(self):
        # A Stopwatch, not time.time(): IronPython's clock can move in 15 ms
        # steps on Windows, which is the whole length of one frame.
        return self._stopwatch.Elapsed.TotalSeconds

    def timer(self, interval_ms, tick):
        return _Timer(interval_ms, tick)

    def actual_height(self, window):
        height = window.ActualHeight
        if not height or height != height:      # NaN on a window not yet laid out
            height = window.Height
        return float(height)

    def size_to_content(self, window):
        return window.SizeToContent

    def relax(self, window):
        from System.Windows import SizeToContent
        window.MinHeight = 0
        window.SizeToContent = SizeToContent.Manual

    def restore(self, window, min_height, size_to_content):
        try:
            window.MinHeight = min_height
        except Exception:
            pass
        try:
            if size_to_content is not None:
                window.SizeToContent = size_to_content
        except Exception:
            pass

    def bar_height(self, window, header):
        u"""The header plus the frame either side of it."""
        from System.Windows import Point
        offset = 0.0
        try:
            offset = header.TranslatePoint(Point(0, 0), window).Y
        except Exception:
            pass
        return float(header.ActualHeight) + 2.0 * max(0.0, offset)

    def work_area(self, window):
        area = rba_ui.work_area(window)
        if area is None:
            from System.Windows import SystemParameters
            area_rect = SystemParameters.WorkArea
            area = (area_rect.Left, area_rect.Top, area_rect.Width, area_rect.Height)
        return area

    def siblings(self, header, window, skip):
        u"""Every element beside the header, on the way up to the window."""
        from System import Object
        from System.Windows import LogicalTreeHelper
        out = []
        node = header
        guard = 0
        while node is not None and not Object.ReferenceEquals(node, window) and guard < 40:
            guard += 1
            parent = LogicalTreeHelper.GetParent(node)
            if parent is None:
                break
            children = getattr(parent, u"Children", None)
            if children is not None:
                for child in children:
                    if Object.ReferenceEquals(child, node):
                        continue
                    if any(Object.ReferenceEquals(child, other) for other in skip):
                        continue
                    out.append(child)
            node = parent
        return out

    def hide(self, element):
        from System.Windows import Visibility
        token = element.Visibility
        element.Visibility = Visibility.Collapsed
        return token

    def show(self, element, token):
        element.Visibility = token

    def pin(self, root):
        from System.Windows import VerticalAlignment
        try:
            height = root.ActualHeight
            if height and height == height:
                root.Height = height
            root.VerticalAlignment = VerticalAlignment.Top
        except Exception:
            log_exception(u"drawer/pin")

    def unpin(self, root):
        from System import Double
        from System.Windows import VerticalAlignment
        try:
            root.Height = Double.NaN
            root.VerticalAlignment = VerticalAlignment.Stretch
        except Exception:
            log_exception(u"drawer/unpin")

    def round_header(self, header, parked):
        u"""A parked bar is rounded all round; an open header only at the top."""
        from System.Windows import CornerRadius
        try:
            if getattr(header, u"Tag", None) != u"round":
                return
            header.CornerRadius = CornerRadius(6) if parked else CornerRadius(6, 6, 0, 0)
        except Exception:
            pass

    def set_glyph(self, glyphs, shrunk):
        from System.Windows import Visibility
        button, shrink_glyph, expand_glyph = glyphs
        try:
            shrink_glyph.Visibility = Visibility.Collapsed if shrunk else Visibility.Visible
            expand_glyph.Visibility = Visibility.Visible if shrunk else Visibility.Collapsed
            button.ToolTip = (u"Bring the window back (Ctrl+Shift+H)" if shrunk
                              else u"Shrink to the taskbar so Revit can be seen (Ctrl+Shift+H)")
        except Exception:
            log_exception(u"drawer/glyph")

    def activate(self, window):
        # A window under a modal dialog is disabled. Activating it as it
        # lands would take focus from the dialog that brought it back, and
        # Escape, Enter and typing would stop reaching the dialog.
        try:
            if not window.IsEnabled:
                return
            window.Activate()
        except Exception:
            pass


class _Timer(object):

    def __init__(self, interval_ms, tick):
        from System import TimeSpan
        from System.Windows.Threading import DispatcherTimer
        self._timer = DispatcherTimer()
        self._timer.Interval = TimeSpan.FromMilliseconds(interval_ms)
        self._tick = tick
        self._timer.Tick += self._on_tick

    def _on_tick(self, sender, args):
        self._tick()

    def start(self):
        self._timer.Start()

    def stop(self):
        self._timer.Stop()


# ----------------------------------------------------------------------
# wiring a window
# ----------------------------------------------------------------------

def attach(window, header, glyphs, grips=None, owner=None, name=u"window",
           shortcut=True):
    u"""Give a window its drawer and wire every gesture to it.

    Returns the Drawer. The window's root (its Content) is what gets pinned;
    the header is what parks; glyphs is (button, shrink glyph, expand glyph).
    """
    from System.Windows.Input import Keyboard, ModifierKeys

    drawer = Drawer(window, header, window.Content, glyphs, WpfPlatform(),
                    grips=grips, owner=owner, name=name, shortcut=shortcut)

    def on_click(sender, args):
        try:
            if not drawer.sliding:
                drawer.toggle()
        except Exception:
            log_exception(u"drawer/click")

    def on_key(sender, args):
        try:
            modifiers = Keyboard.Modifiers
            ctrl = bool(modifiers & ModifierKeys.Control)
            shift = bool(modifiers & ModifierKeys.Shift)
            if drawer.on_key(rba_core.to_text(args.Key), ctrl, shift):
                args.Handled = True
        except Exception:
            log_exception(u"drawer/key")

    def on_closed(sender, args):
        drawer.forget()

    glyphs[0].Click += on_click
    window.PreviewKeyDown += on_key
    window.Closed += on_closed
    return drawer
