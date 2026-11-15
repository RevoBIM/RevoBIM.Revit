# -*- coding: utf-8 -*-
"""Shrink to taskbar. The slide is eased by hand on a timer: an animation holds
its end value and outranks every later assignment, so nothing here ever calls
BeginAnimation. Timer, clock and the screen lookup are arguments so the bench
can drive a whole slide against a stand-in window."""
import time
from fpp_core import (SLIDE_SECONDS, TICK_MS, clamp_left, ease_out, lerp,
                      parked_top, reopen_top)

COLLAPSED = 'Collapsed'
VISIBLE = 'Visible'


class Drawer(object):
    def __init__(self, window, header, root, button, shrink_glyph, expand_glyph,
                 ui, grips=None, siblings=None, work_area=None, timer=None,
                 clock=None):
        self.win = window
        self.header = header
        self.root = root
        self.button = button
        self.shrink_glyph = shrink_glyph
        self.expand_glyph = expand_glyph
        self.ui = ui                    # visibility, sizing and timer values
        self.grips = grips
        self.siblings = siblings or []
        self.work_area = work_area
        self.make_timer = timer or ui.make_timer
        self.clock = clock or time.time
        self.parked = False
        self.sliding = False
        self.owner = None               # drawer of the window beneath
        self.slot = 0
        self.saved = None
        self.hidden = []
        self.timer = None
        self.bar = 0.0
        self.landed_top = 0.0
        self.path = None
        self.started = 0.0
        self.took_owner = False

    # ----- state -----
    def toggle(self):
        if self.sliding:
            return
        if self.parked:
            self.expand()
        else:
            self.shrink()

    def shrink(self, instant=False):
        if self.parked or self.sliding:
            return
        if self.owner is not None:
            self.took_owner = not self.owner.parked
            self.owner.shrink(True)
            self.slot = self.owner.slot + 1
        win = self.win
        self.saved = {'left': win.Left, 'top': win.Top, 'height': win.Height,
                      'width': win.Width, 'min_height': win.MinHeight,
                      'size': win.SizeToContent,
                      'root_height': self.root.ActualHeight}
        win.SizeToContent = self.ui.size_manual()
        win.MinHeight = 0
        self.root.Height = self.root.ActualHeight or win.Height
        self.root.VerticalAlignment = self.ui.align_top()
        if self.grips is not None:
            self.grips.Visibility = self.ui.visibility(COLLAPSED)
        self.bar = self.ui.bar_height(self.header, win)
        area = self.work_area(win)
        self.landed_top = parked_top(area[1], area[3], self.bar, self.slot)
        self.start_slide(win.Top, self.landed_top, win.Height, self.bar,
                         win.Top, self.landed_park, instant)

    def expand(self, instant=False, activate=True):
        if not self.parked or self.sliding:
            return
        win = self.win
        saved = self.saved
        area = self.work_area(win)
        moved = abs(win.Top - self.landed_top) > 2.0
        if moved:
            top = reopen_top(win.Top, self.bar, saved['height'], area[1],
                             area[3])
            left = clamp_left(win.Left, saved['width'], area[0], area[2])
        else:
            top, left = saved['top'], saved['left']
        self.restore_siblings()
        self.root.Height = saved['root_height'] or saved['height']
        self.parked = False
        self.show_glyph()
        win.Left = left
        self.start_slide(win.Top, top, self.bar, saved['height'], win.Top,
                         self.landed_open, instant)
        self.release_owner()
        if activate:
            try:
                win.Activate()
            except Exception:
                pass

    # ----- slide -----
    def start_slide(self, from_top, to_top, from_h, to_h, _unused, land,
                    instant):
        self.path = (from_top, to_top, from_h, to_h, land)
        self.sliding = True
        if instant:
            self.finish()
            return
        self.started = self.clock()
        try:
            self.timer = self.make_timer(TICK_MS, self.on_tick)
            self.timer.Start()
        except Exception:
            self.finish()

    def on_tick(self, sender=None, args=None):
        try:
            elapsed = self.clock() - self.started
            progress = elapsed / SLIDE_SECONDS
            if progress >= 1.0:
                self.finish()
                return
            eased = ease_out(progress)
            self.win.Top = lerp(self.path[0], self.path[1], eased)
            self.win.Height = lerp(self.path[2], self.path[3], eased)
        except Exception:
            self.finish()

    def finish(self):
        if self.timer is not None:
            try:
                self.timer.Stop()
            except Exception:
                pass
            self.timer = None
        path = self.path
        self.sliding = False
        try:
            self.win.Height = path[3]
            self.win.Top = path[1]
        except Exception:
            pass
        path[4]()

    def landed_park(self):
        self.parked = True
        self.hidden = []
        for item in self.siblings:
            self.hidden.append((item, item.Visibility))
            item.Visibility = self.ui.visibility(COLLAPSED)
        self.root.Height = self.bar
        self.show_glyph()

    def landed_open(self):
        win = self.win
        saved = self.saved
        self.root.Height = self.ui.nan()
        self.root.VerticalAlignment = self.ui.align_stretch()
        win.MinHeight = saved['min_height']
        win.SizeToContent = saved['size']
        if self.grips is not None:
            self.grips.Visibility = self.ui.visibility(VISIBLE)
        self.slot = 0

    def restore_siblings(self):
        for item, state in self.hidden:
            item.Visibility = state
        self.hidden = []

    def show_glyph(self):
        self.shrink_glyph.Visibility = self.ui.visibility(
            COLLAPSED if self.parked else VISIBLE)
        self.expand_glyph.Visibility = self.ui.visibility(
            VISIBLE if self.parked else COLLAPSED)

    def release_owner(self):
        """Only what this drawer took down comes back: a window the user had
        already parked stays parked when its dialog closes."""
        if self.owner is not None and self.took_owner:
            self.took_owner = False
            self.owner.expand(True, False)

    def settle(self):
        """Closing while parked: put the real size back first, so what is
        remembered is the window and not the bar."""
        if self.sliding:
            self.finish()
        if self.parked:
            self.expand(True, False)
            if self.sliding:
                self.finish()
