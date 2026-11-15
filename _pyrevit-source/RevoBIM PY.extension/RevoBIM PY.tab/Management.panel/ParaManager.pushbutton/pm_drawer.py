# -*- coding: utf-8 -*-
"""Shrink to taskbar. Top and Height are eased by hand on a timer, so nothing is held."""
import pm_clr
import time

from System import Double, TimeSpan
from System.Windows import SizeToContent, VerticalAlignment, Visibility, Window
from System.Windows.Threading import DispatcherTimer

import pm_core as core

PARKED = []


def _timer():
    timer = DispatcherTimer()
    timer.Interval = TimeSpan.FromMilliseconds(core.DRAWER_TICK_MS)
    return timer


class Drawer(object):
    def __init__(self, window, header, root, button, grips, work_area, owner=None,
                 make_timer=_timer, clock=time.time):
        self.window = window
        self.header = header
        self.root = root
        self.button = button
        self.grips = grips
        self.work_area = work_area
        self.owner = owner
        self.make_timer = make_timer
        self.clock = clock
        self.parked = False
        self.sliding = False
        self.hidden = []
        self.saved = None
        self.size_mode = None
        self.min_height = 0.0
        self.timer = None
        self.parked_at = 0.0
        self.held = False

    def toggle(self):
        if self.sliding or self.held:
            return
        if self.parked:
            self.open()
        else:
            self.shrink()

    def _bar_height(self):
        try:
            return self.header.ActualHeight + 2.0
        except Exception:
            return 44.0

    def _release(self):
        try:
            self.window.BeginAnimation(Window.TopProperty, None)
        except Exception:
            pass
        try:
            self.window.BeginAnimation(Window.HeightProperty, None)
        except Exception:
            pass

    def shrink(self, instant=False):
        if self.parked or self.sliding:
            return
        if self.owner is not None:
            self.owner.shrink(True)
        window = self.window
        self._release()
        self.saved = (window.Top, window.ActualHeight)
        self.size_mode = window.SizeToContent
        self.min_height = window.MinHeight
        window.SizeToContent = SizeToContent.Manual
        window.MinHeight = 0.0
        self.grips.Visibility = Visibility.Collapsed
        self.root.Height = self.root.ActualHeight
        self.root.VerticalAlignment = VerticalAlignment.Top
        bar = self._bar_height()
        slot = len(PARKED)
        target = core.parked_top(self.work_area()[3], bar, slot)
        self.parked_at = target
        PARKED.append(self)
        self.parked = True
        self._slide(window.Top, target, window.ActualHeight, bar, self._landed_down, instant)

    def _landed_down(self):
        self.button.Tag = 'shrunk'
        self._set_body(False)

    def open(self):
        if not self.parked or self.sliding:
            return
        window = self.window
        top, height = self.saved
        area = self.work_area()
        target = core.reopen_top(top, window.Top, self.parked_at, height, area[1], area[3])
        if self in PARKED:
            PARKED.remove(self)
        self.parked = False
        self._set_body(True)
        self._slide(window.Top, target, window.ActualHeight, height, self._landed_up, False)
        if self.owner is not None:
            self.owner.open()

    def _landed_up(self):
        self.window.MinHeight = self.min_height
        self.root.Height = Double.NaN
        self.root.VerticalAlignment = VerticalAlignment.Stretch
        self.grips.Visibility = Visibility.Visible
        self.button.Tag = None
        if self.size_mode is not None:
            self.window.SizeToContent = self.size_mode

    def _set_body(self, show):
        """Everything under the header goes, and comes back as it was."""
        try:
            if show:
                for element, state in self.hidden:
                    element.Visibility = state
                self.hidden = []
                return
            parent = self.header.Parent
            for child in parent.Children:
                if child is not self.header and child is not self.grips:
                    self.hidden.append((child, child.Visibility))
                    child.Visibility = Visibility.Collapsed
        except Exception:
            pass

    def _slide(self, top0, top1, height0, height1, landed, instant):
        window = self.window

        def finish():
            self.sliding = False
            if self.timer is not None:
                try:
                    self.timer.Stop()
                except Exception:
                    pass
            window.Top = top1
            window.Height = height1
            landed()

        if instant:
            finish()
            return
        self.sliding = True
        started = self.clock()

        def tick(sender, args):
            try:
                progress = (self.clock() - started) / core.DRAWER_SECONDS
                eased = core.ease_out(progress)
                window.Top = top0 + (top1 - top0) * eased
                window.Height = height0 + (height1 - height0) * eased
                if progress >= 1.0:
                    finish()
            except Exception:
                finish()

        try:
            self.timer = self.make_timer()
            self.timer.Tick += tick
            self.timer.Start()
        except Exception:
            finish()

    def settle(self):
        """Closing while parked: free the slot and bring the owner back."""
        if self in PARKED:
            PARKED.remove(self)
        if self.owner is not None and self.owner.parked:
            self.owner.open()
