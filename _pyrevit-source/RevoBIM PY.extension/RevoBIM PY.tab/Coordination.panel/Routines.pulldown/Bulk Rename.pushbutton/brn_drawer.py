# -*- coding: utf-8 -*-
"""Shrink to taskbar. Top is eased by hand on a timer, so no animation is left
holding the window, and the window is cut to the bar only once it has landed."""
import time

import brn_core as core

_slots = []


class Drawer(object):
    def __init__(self, window, header, root, shrink_glyph, expand_glyph, grips,
                 work_area, make_timer, collapsed, frame=2.0, clock=None):
        self.window = window
        self.header = header
        self.root = root
        self.shrink_glyph = shrink_glyph
        self.expand_glyph = expand_glyph
        self.grips = grips
        self.work_area = work_area
        self.make_timer = make_timer
        self.collapsed = collapsed      # (visible, collapsed) enum values
        self.frame = frame
        self.clock = clock or time.time
        self.owner = None
        self.parked = False
        self.sliding = False
        self.slot = None
        self.saved = None
        self.relaxed = None
        self.hidden = []
        self.timer = None
        self.parked_at = (0.0, 0.0)

    # ---------- geometry ----------
    def bar_height(self):
        return self.header.ActualHeight + 2 * self.frame

    def _stack_below(self):
        return sum([d.bar_height() + core.STACK_GAP
                    for d in _slots[:self.slot] if d is not None])

    def toggle(self):
        if self.sliding:
            return
        if self.parked:
            self.expand()
        else:
            self.shrink()

    # ---------- going down ----------
    def shrink(self, animate=True):
        if self.parked or self.sliding:
            return
        if self.owner is not None:
            self.owner.shrink(False)
        window = self.window
        self.saved = (window.Left, window.Top, window.ActualWidth,
                      window.ActualHeight)
        self.relaxed = (window.MinHeight, window.SizeToContent)
        window.SizeToContent = self.manual()
        window.Height = self.saved[3]
        window.MinHeight = 0
        self.root.Height = self.saved[3]
        self.root.VerticalAlignment = self.top_align()
        self.grips.Visibility = self.collapsed[1]
        self.slot = core.free_slot(_slots)
        if self.slot == len(_slots):
            _slots.append(self)
        else:
            _slots[self.slot] = self
        left, top, width, height = self.work_area()
        target = core.parked_top(top, height, self.bar_height(),
                                 self._stack_below())
        self._slide(window.Top, target, self._landed, animate)

    def _landed(self):
        window = self.window
        self.parked = True
        parent = self.header.Parent
        self.hidden = []
        for child in parent.Children:
            if child != self.header:
                self.hidden.append((child, child.Visibility))
                child.Visibility = self.collapsed[1]
        window.Height = self.bar_height()
        self.root.Height = self.nan()
        self.root.VerticalAlignment = self.stretch()
        self.parked_at = (window.Left, window.Top)
        self.shrink_glyph.Visibility = self.collapsed[1]
        self.expand_glyph.Visibility = self.collapsed[0]

    # ---------- coming back ----------
    def expand(self, animate=True):
        if not self.parked or self.sliding:
            return
        window = self.window
        target = core.expand_rect(self.saved, window.Left, window.Top,
                                  self.parked_at[0], self.parked_at[1],
                                  self.work_area())
        for child, visibility in self.hidden:
            child.Visibility = visibility
        self.hidden = []
        window.Height = self.saved[3]
        window.Left = target[0]
        self.parked = False
        self.shrink_glyph.Visibility = self.collapsed[0]
        self.expand_glyph.Visibility = self.collapsed[1]
        _slots[self.slot] = None
        self.slot = None
        self._slide(window.Top, target[1], self._opened, animate)

    def _opened(self):
        self.window.MinHeight = self.relaxed[0]
        self.window.SizeToContent = self.relaxed[1]
        self.grips.Visibility = self.collapsed[0]
        if self.owner is not None:
            self.owner.expand(False)

    def settle(self):
        """Closing while parked: free the slot and bring the owner back."""
        if self.slot is not None:
            _slots[self.slot] = None
            self.slot = None
        if self.owner is not None:
            self.owner.expand(False)

    # ---------- the slide ----------
    def _slide(self, start, end, done, animate):
        if not animate:
            self.window.Top = end
            done()
            return
        self.sliding = True
        began = self.clock()
        state = {'finished': False}

        def finish():
            if state['finished']:
                return
            state['finished'] = True
            try:
                self.timer.Stop()
            except Exception:
                pass
            self.sliding = False
            self.window.Top = end
            done()

        def tick(sender, args):
            try:
                progress = (self.clock() - began) / core.SLIDE_SECONDS
                if progress >= 1:
                    finish()
                else:
                    self.window.Top = start + (end - start) * core.ease(progress)
            except Exception:
                finish()

        try:
            self.timer = self.make_timer(tick)
            self.timer.Start()
        except Exception:
            finish()

    # ---------- values WPF supplies; the chrome overrides these ----------
    def manual(self):
        return 0

    def top_align(self):
        return 'Top'

    def stretch(self):
        return 'Stretch'

    def nan(self):
        return float('nan')
