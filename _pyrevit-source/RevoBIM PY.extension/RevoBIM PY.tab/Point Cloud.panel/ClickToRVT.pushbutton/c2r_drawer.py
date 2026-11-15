# -*- coding: utf-8 -*-
"""Click to RVT Element - shrink to taskbar.

Slides a window down to the bottom of its screen like a drawer closing,
leaving only its header bar floating clear of the taskbar; the button turns
into a green up arrow that slides it back. Built once and handed to every
window the tool opens.

Top and Height are eased by hand on a DispatcherTimer - plain assignments
each frame, never a Storyboard - and any animation clock on either property
is released before each slide, so nothing holds an end value that would
outrank a later assignment. The arithmetic is in c2r_core where the bench
can prove it.
"""
import c2r_clr  # noqa: F401

from System import TimeSpan, EventHandler, Double
from System.Windows import Window, VerticalAlignment, Visibility, SizeToContent
from System.Windows.Threading import DispatcherTimer

import c2r_core as core


def dispatcher_timer(ms, tick):
    t = DispatcherTimer()
    t.Interval = TimeSpan.FromMilliseconds(ms)
    t.Tick += EventHandler(tick)
    return t


def work_area(window):
    """(left, top, right, bottom) of the work area of the screen the window
    is on, in WPF units."""
    try:
        from System.Windows.Forms import Screen
        from System.Windows import PresentationSource
        scale_x = 1.0
        scale_y = 1.0
        try:
            src = PresentationSource.FromVisual(window)
            m = src.CompositionTarget.TransformToDevice
            scale_x = m.M11
            scale_y = m.M22
        except Exception:
            pass
        screens = []
        for s in Screen.AllScreens:
            r = s.WorkingArea
            screens.append((r.Left / scale_x, r.Top / scale_y, r.Right / scale_x, r.Bottom / scale_y))
        h = window.ActualHeight if window.ActualHeight > 0 else window.Height
        w = window.ActualWidth if window.ActualWidth > 0 else window.Width
        sc = core.screen_for(window.Left, window.Top, w, h, screens)
        if sc is not None:
            return sc
    except Exception:
        pass
    from System.Windows import SystemParameters
    wa = SystemParameters.WorkArea
    return (wa.Left, wa.Top, wa.Right, wa.Bottom)


class WindowDrawer(object):

    def __init__(self, window, header, root, button, grips=None, area_fn=None, timer_factory=None,
                 on_change=None, on_error=None):
        self.w = window
        self.header = header
        self.root = root
        self.btn = button
        self.grips = grips
        self.area_fn = area_fn or work_area
        self.timer_factory = timer_factory or dispatcher_timer
        self.on_change = on_change
        self.on_error = on_error
        self.parked = False
        self.sliding = False
        self.saved = None
        self.parked_at = None
        self.hidden = []
        self.linked = None      # the owner's drawer, parked beneath this one
        self.slot = 0

    # ------------------------------------------------------------------
    def toggle(self):
        if self.sliding:
            return
        if self.parked:
            self.expand()
        else:
            self.shrink()

    def shrink(self):
        if self.parked or self.sliding:
            return
        if self.linked is not None:
            self.linked.slot = 0
            self.linked.shrink()
            self.slot = 1
        w = self.w
        _l, _t, _r, bottom = self.area_fn(w)
        self._release()
        full = w.ActualHeight if w.ActualHeight > 0 else w.Height
        self.saved = {u'top': w.Top, u'height': full, u'minh': w.MinHeight, u'stc': w.SizeToContent}
        w.MinHeight = 0
        w.SizeToContent = SizeToContent.Manual
        self._pin(True)
        self._grips(False)
        bar = core.bar_height(self.header.ActualHeight)
        target = core.parked_top(bottom, bar, self.slot)
        self.parked_at = target

        def landed():
            self._body(False)
            self.parked = True
            self._tag(u'shrunk')
            self._notify()
        self._slide(w.Top, target, full, bar, landed)

    def expand(self):
        if not self.parked or self.sliding:
            return
        w = self.w
        _l, top, _r, bottom = self.area_fn(w)
        full = self.saved[u'height']
        target = core.expand_top(self.saved[u'top'], self.parked_at, w.Top, full, top, bottom)
        self._body(True)
        cur_h = w.ActualHeight if w.ActualHeight > 0 else w.Height

        def landed():
            self._pin(False)
            try:
                w.MinHeight = self.saved[u'minh']
                w.SizeToContent = self.saved[u'stc']
            except Exception:
                pass
            self._grips(True)
            self.parked = False
            self.slot = 0
            self._tag(u'')
            self._notify()
            if self.linked is not None and self.linked.parked:
                self.linked.expand()
        self._slide(w.Top, target, cur_h, full, landed)

    # ------------------------------------------------------------------
    def _slide(self, top0, top1, h0, h1, done):
        self.sliding = True
        steps = max(1, core.DRAWER_MS // core.DRAWER_TICK_MS)
        state = {u'k': 0, u'timer': None}

        def land():
            if not self.sliding:
                return
            tm = state[u'timer']
            if tm is not None:
                try:
                    tm.Stop()
                except Exception:
                    pass
            self._release()
            try:
                self.w.Top = top1
                self.w.Height = h1
            except Exception as ex:
                self._err(ex)
            self.sliding = False
            try:
                done()
            except Exception as ex:
                self._err(ex)

        def tick(sender, args):
            try:
                state[u'k'] += 1
                p = state[u'k'] / float(steps)
                if p >= 1.0:
                    land()
                    return
                self.w.Top = core.slide_frame(top0, top1, p)
                self.w.Height = core.slide_frame(h0, h1, p)
            except Exception as ex:
                self._err(ex)
                land()
        try:
            state[u'timer'] = self.timer_factory(core.DRAWER_TICK_MS, tick)
            state[u'timer'].Start()
        except Exception as ex:
            self._err(ex)
            land()

    def _release(self):
        try:
            self.w.BeginAnimation(Window.TopProperty, None)
        except Exception:
            pass
        try:
            self.w.BeginAnimation(Window.HeightProperty, None)
        except Exception:
            pass

    def _pin(self, on):
        try:
            if on:
                self.root.Height = self.root.ActualHeight
                self.root.VerticalAlignment = VerticalAlignment.Top
            else:
                self.root.Height = Double.NaN
                self.root.VerticalAlignment = VerticalAlignment.Stretch
        except Exception:
            pass

    def _grips(self, on):
        if self.grips is None:
            return
        try:
            self.grips.Visibility = Visibility.Visible if on else Visibility.Collapsed
        except Exception:
            pass

    def _body(self, show):
        if not show:
            self.hidden = []
            for child in list(self.root.Children):
                if child is self.header:
                    continue
                self.hidden.append((child, child.Visibility))
                child.Visibility = Visibility.Collapsed
        else:
            for child, was in self.hidden:
                try:
                    child.Visibility = was
                except Exception:
                    pass
            self.hidden = []

    def _tag(self, value):
        try:
            self.btn.Tag = value
        except Exception:
            pass

    def _notify(self):
        if self.on_change is not None:
            try:
                self.on_change(self.parked)
            except Exception as ex:
                self._err(ex)

    def _err(self, ex):
        if self.on_error is not None:
            try:
                self.on_error(ex)
            except Exception:
                pass
