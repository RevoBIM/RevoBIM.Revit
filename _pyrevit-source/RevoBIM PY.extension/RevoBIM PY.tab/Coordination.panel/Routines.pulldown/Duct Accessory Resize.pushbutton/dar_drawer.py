# -*- coding: utf-8 -*-
"""Shrink to taskbar - the drawer every window of this tool carries.

Pressing the control slides the window down like a drawer closing, leaving
only its own header bar floating clear of the taskbar so Revit can be worked
in; the control becomes a green up arrow that opens it again.

Built once and handed to each window class, so the gesture is identical
whatever built the window's chrome. The arithmetic lives in dar_core where
the bench can prove it; this module is only the WPF around it.
"""

import dar_clr  # noqa: F401 - assemblies first, always

from System import Double, TimeSpan
from System.Windows import Visibility, VerticalAlignment, SizeToContent
from System.Windows.Threading import DispatcherTimer

import dar_core as core
import dar_ui as ui

SHRUNK = u"shrunk"
TIP_SHRINK = u"Shrink to the taskbar so Revit can be seen  (Ctrl+Shift+H)"
TIP_RESTORE = u"Open the window again  (Ctrl+Shift+H)"

# slots in use across every window of this tool, so two parked bars stack
# rather than sitting on top of each other
_TAKEN = set()


class Drawer(object):
    """window     the Window itself
    header        the header Border - what stays visible when parked
    body          the root layout element, pinned for the length of a slide
    button        the shrink control, whose Tag drives its glyph
    grips         the resize grip overlay, parked with the window
    """

    def __init__(self, window, header, body, button, grips=None, log=None):
        self.window = window
        self.header = header
        self.body = body
        self.button = button
        self.grips = grips
        self.log = log
        self.parked = False
        self.sliding = False
        self.timer = None
        self.slot = None
        self.full_height = None
        self.saved = {}
        self._paint()

    # ---------------------------------------------------------- helpers

    def _say(self, text, *args):
        if self.log is not None:
            self.log.add(text, *args)

    def _paint(self):
        try:
            self.button.Tag = SHRUNK if self.parked else None
            self.button.ToolTip = TIP_RESTORE if self.parked else TIP_SHRINK
        except Exception:
            pass

    def _stop_timer(self):
        try:
            if self.timer is not None:
                self.timer.Stop()
        except Exception:
            pass
        self.timer = None

    def _show_grips(self, visible):
        if self.grips is None:
            return
        try:
            self.grips.Visibility = (Visibility.Visible if visible
                                     else Visibility.Collapsed)
        except Exception:
            pass

    def _pin_body(self):
        """Pin the body to its measured height and let the shrinking window
        clip it. Without this the grid re-measures on every frame and the
        table realises and drops rows twenty times a second, which reads as
        a window being squashed rather than a drawer being drawn away."""
        try:
            height = float(self.body.ActualHeight)
            if height > 0:
                self.body.Height = height
            self.body.VerticalAlignment = VerticalAlignment.Top
        except Exception:
            pass

    def _unpin_body(self):
        try:
            self.body.Height = Double.NaN
            self.body.VerticalAlignment = VerticalAlignment.Stretch
        except Exception:
            pass

    def _relax(self):
        """MinHeight and SizeToContent each veto a Height change, and a
        vetoed slide leaves the window half shut for the rest of the
        session."""
        try:
            self.saved = {
                u"min": float(self.window.MinHeight),
                u"size_to": self.window.SizeToContent,
                u"resize": self.window.ResizeMode,
            }
            self.window.MinHeight = 0.0
            self.window.SizeToContent = SizeToContent.Manual
        except Exception:
            self.saved = {}

    def _put_back(self):
        try:
            if u"min" in self.saved:
                self.window.MinHeight = self.saved[u"min"]
            if u"size_to" in self.saved:
                self.window.SizeToContent = self.saved[u"size_to"]
            if u"resize" in self.saved:
                self.window.ResizeMode = self.saved[u"resize"]
        except Exception:
            pass
        self.saved = {}

    def _screen(self):
        try:
            return ui.work_area(self.window)
        except Exception:
            return (0.0, 0.0, 1920.0, 1040.0)

    def _measured_height(self):
        """A window sized to its content has Height = NaN until something
        sets it, and a slide starting from NaN lands nowhere."""
        for value in (self.window.Height, self.window.ActualHeight):
            try:
                value = float(value)
            except Exception:
                continue
            if value > 0 and value == value:  # NaN != NaN
                return value
        return float(core.DRAWER_BAR_FLOOR)

    # ---------------------------------------------------------- the slide

    def _slide(self, top_to, height_to, done):
        top_from = float(self.window.Top)
        height_from = self._measured_height()
        steps = core.slide_steps()
        state = {u"step": 0}

        def land():
            try:
                self.window.Top = float(top_to)
                self.window.Height = float(height_to)
            except Exception:
                pass
            self.sliding = False
            try:
                done()
            except Exception:
                self._say(u"drawer: finishing the slide failed")

        def on_tick(sender, args):
            # A tick that throws reaches the dispatcher, NOT the try around
            # Start() - so without this the drawer is left sliding for ever
            # and the button never works again.
            try:
                state[u"step"] += 1
                progress = float(state[u"step"]) / steps
                if progress >= 1.0:
                    self._stop_timer()
                    land()
                    return
                self.window.Top = core.tween(top_from, top_to, progress)
                self.window.Height = core.tween(height_from, height_to,
                                                progress)
            except Exception:
                self._stop_timer()
                land()

        self.sliding = True
        try:
            self.timer = DispatcherTimer()
            self.timer.Interval = TimeSpan.FromMilliseconds(
                core.DRAWER_TICK_MS)
            self.timer.Tick += on_tick
            self.timer.Start()
        except Exception:
            self.timer = None
            land()

    # ---------------------------------------------------------- the gesture

    def toggle(self):
        if self.parked:
            self.restore()
        else:
            self.shrink()

    def shrink(self):
        if self.sliding or self.parked:
            return False
        self.full_height = self._measured_height()
        left, top, width, height = self._screen()
        bar = core.bar_height(self.header.ActualHeight)
        self.slot = core.take_slot(_TAKEN)
        _TAKEN.add(self.slot)
        target = core.bar_top(top, height, bar, self.slot)
        self._say(u"drawer: parking at {0} (bar {1}, slot {2})", target, bar,
                  self.slot)
        self._relax()
        self._pin_body()
        self._show_grips(False)

        def done():
            self.parked = True
            self._paint()
        self._slide(target, bar, done)
        return True

    def restore(self):
        if self.sliding or not self.parked:
            return False
        left, top, width, height = self._screen()
        full = self.full_height or self._measured_height()
        target = core.restore_top(float(self.window.Top),
                                  self._measured_height(), full, top, height)
        self._say(u"drawer: opening to {0} (height {1})", target, full)

        def done():
            # Both ways out of the drawer come through here - the slide and
            # the fallback when no timer could start. Unpinning on only one
            # of them still leaves a window nobody can resize.
            self._unpin_body()
            self._put_back()
            self._show_grips(True)
            if self.slot is not None:
                _TAKEN.discard(self.slot)
                self.slot = None
            self.parked = False
            self._paint()
        self._slide(target, full, done)
        return True

    def settle(self):
        """Put the window back with no slide - for closing while parked, so
        nothing is left pinned or clamped."""
        if not self.parked:
            return False
        self._stop_timer()
        self.sliding = False
        left, top, width, height = self._screen()
        full = self.full_height or self._measured_height()
        try:
            self.window.Top = core.restore_top(float(self.window.Top),
                                               self._measured_height(), full,
                                               top, height)
            self.window.Height = full
        except Exception:
            pass
        self._unpin_body()
        self._put_back()
        self._show_grips(True)
        if self.slot is not None:
            _TAKEN.discard(self.slot)
            self.slot = None
        self.parked = False
        self._paint()
        return True
