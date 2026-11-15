# -*- coding: utf-8 -*-
"""Shrink to taskbar - the RevoBIM drawer, one per window.

Pressing the shrink button slides the window down to the bottom of its
screen like a drawer closing, leaving only its header bar floating clear of
the taskbar so Revit can be seen. The button turns into a green up arrow;
press it, double-click the bar, or press Enter / Esc / F11 and the window
slides back. Ctrl+Shift+H works both ways.

Nothing from .NET is imported at module load: WPF is reached through an
environment object (real_env() for Revit, a fake one on the bench), so the
whole gesture can be driven under CPython.

House rules this follows (RevoBIM theme reference, Shrink to taskbar):
- the slide eases Top by hand on a 15ms timer - no Storyboard, ever - and
  BeginAnimation(prop, None) releases Top and Height before every slide
- MinHeight / SizeToContent are relaxed for the trip and put back
- the body is pinned at its height for the slide
- resize grips are parked with the window
- a frame that throws lands the window at its end state
"""
import cm_logic

SLIDE_MS = 280.0
TICK_MS = 15

_SLOTS = {}          # slot -> drawer, shared by every window of the tool


class _RealEnv(object):
    """WPF and screen access for the drawer, imported on first use."""

    def __init__(self):
        import cm_clr  # noqa: F401  - references before any System import
        from System import TimeSpan, Double
        from System.Windows import Visibility, VerticalAlignment, \
            SizeToContent, Window
        from System.Windows.Threading import DispatcherTimer
        self.TimeSpan = TimeSpan
        self.NaN = Double.NaN
        self.Visibility = Visibility
        self.VerticalAlignment = VerticalAlignment
        self.SizeToContent = SizeToContent
        self.Window = Window
        self.DispatcherTimer = DispatcherTimer

    def make_timer(self, ms, tick):
        timer = self.DispatcherTimer()
        timer.Interval = self.TimeSpan.FromMilliseconds(ms)
        timer.Tick += tick
        return timer

    def release(self, window):
        """An animation holds its end value and outranks every later plain
        assignment - release both, each in its own try."""
        try:
            window.BeginAnimation(self.Window.TopProperty, None)
        except Exception:
            pass
        try:
            window.BeginAnimation(self.Window.HeightProperty, None)
        except Exception:
            pass

    def work_area(self, window):
        """(top, bottom) of the work area of the window's own screen, DIPs."""
        try:
            from System.Windows.Interop import WindowInteropHelper
            from System.Windows.Forms import Screen
            from System.Windows import PresentationSource
            hwnd = WindowInteropHelper(window).Handle
            area = Screen.FromHandle(hwnd).WorkingArea
            scale = 1.0
            src = PresentationSource.FromVisual(window)
            if src is not None and src.CompositionTarget is not None:
                scale = src.CompositionTarget.TransformToDevice.M22 or 1.0
            return area.Top / scale, area.Bottom / scale
        except Exception:
            from System.Windows import SystemParameters
            wa = SystemParameters.WorkArea
            return wa.Top, wa.Bottom

    def bar_height(self, header):
        try:
            return header.ActualHeight + 4.0
        except Exception:
            return 50.0

    def now_ms(self):
        from System import Environment
        return float(Environment.TickCount)


_ENV = [None]


def real_env():
    if _ENV[0] is None:
        _ENV[0] = _RealEnv()
    return _ENV[0]


class WindowDrawer(object):

    def __init__(self, window, header, body, button, shrink_glyph,
                 expand_glyph, grips=None, env=None, siblings=None):
        self.window = window
        self.header = header
        self.body = body
        self.button = button
        self.shrink_glyph = shrink_glyph
        self.expand_glyph = expand_glyph
        self.grips = grips
        self.env = env or real_env()
        self.siblings = siblings or []
        self.parked = False
        self.sliding = False
        self.busy = False
        self.slot = None
        self.owner = None
        self.children = []
        self.saved = {}
        self.parked_top = 0.0
        self.timer = None
        self.errors = []
        self._anim = None

    # ------------------------------------------------------------------
    def set_owner(self, owner_drawer):
        self.owner = owner_drawer
        if owner_drawer is not None:
            owner_drawer.children.append(self)

    def toggle(self, *args):
        if self.sliding:
            return
        if self.parked:
            self.expand()
        else:
            self.shrink()

    # ------------------------------------------------------------------
    def _set_glyphs(self, parked):
        env = self.env
        try:
            self.shrink_glyph.Visibility = env.Visibility.Collapsed \
                if parked else env.Visibility.Visible
            self.expand_glyph.Visibility = env.Visibility.Visible \
                if parked else env.Visibility.Collapsed
            self.button.Tag = 'shrunk' if parked else ''
            self.button.ToolTip = u'Bring the window back (Ctrl+Shift+H)' \
                if parked else u'Shrink to taskbar (Ctrl+Shift+H)'
        except Exception:
            pass

    def _hide_siblings(self):
        env = self.env
        self.saved['vis'] = []
        for el in self.siblings:
            try:
                self.saved['vis'].append((el, el.Visibility))
                el.Visibility = env.Visibility.Collapsed
            except Exception:
                pass
        if self.grips is not None:
            try:
                self.saved['grips'] = self.grips.Visibility
                self.grips.Visibility = env.Visibility.Collapsed
            except Exception:
                pass

    def _show_siblings(self):
        for el, vis in self.saved.get('vis', []):
            try:
                el.Visibility = vis
            except Exception:
                pass
        if self.grips is not None and 'grips' in self.saved:
            try:
                self.grips.Visibility = self.saved['grips']
            except Exception:
                pass

    def _pin_body(self):
        env = self.env
        try:
            self.body.Height = self.body.ActualHeight
            self.body.VerticalAlignment = env.VerticalAlignment.Top
        except Exception:
            pass

    def _unpin_body(self):
        env = self.env
        try:
            self.body.Height = env.NaN
            self.body.VerticalAlignment = env.VerticalAlignment.Stretch
        except Exception:
            pass

    # ------------------------------------------------------------------
    def shrink(self, instant=False):
        if self.parked or self.sliding:
            return
        w = self.window
        env = self.env
        env.release(w)
        # a dialog going down takes its owner down first, instantly
        if self.owner is not None and not self.owner.parked:
            self.owner.shrink(instant=True)
        self.saved = {
            'left': w.Left, 'top': w.Top, 'height': w.Height,
            'min_height': w.MinHeight, 'stc': w.SizeToContent,
        }
        try:
            if w.Height != w.Height:          # NaN - sized to content
                self.saved['height'] = w.ActualHeight
        except Exception:
            pass
        try:
            w.MinHeight = 0
            w.SizeToContent = env.SizeToContent.Manual
            w.Height = self.saved['height']
        except Exception:
            pass
        self._pin_body()
        used = set(k for k in _SLOTS.keys())
        self.slot = cm_logic.free_slot(used)
        _SLOTS[self.slot] = self
        bar_h = env.bar_height(self.header)
        top, bottom = env.work_area(w)
        self.parked_top = cm_logic.park_top(top, bottom, bar_h, self.slot)
        self._set_glyphs(True)
        self.parked = True
        if instant:
            self._land_parked(bar_h)
        else:
            self._slide(w.Top, self.parked_top,
                        lambda: self._land_parked(bar_h))

    def _land_parked(self, bar_h):
        w = self.window
        self.env.release(w)
        self._hide_siblings()          # full height on the way down; cut on landing
        try:
            w.Top = self.parked_top
        except Exception:
            pass
        try:
            w.Height = bar_h
        except Exception:
            pass

    def expand(self, instant=False):
        if not self.parked or self.sliding:
            return
        w = self.window
        env = self.env
        env.release(w)
        full_h = self.saved.get('height', 600.0)
        top, bottom = env.work_area(w)
        target = cm_logic.reopen_top(self.saved.get('top', top),
                                     self.parked_top, w.Top, full_h,
                                     top, bottom)
        start = w.Top
        try:
            w.Height = full_h
        except Exception:
            pass
        self._show_siblings()
        self._set_glyphs(False)
        self.parked = False
        if self.slot is not None and _SLOTS.get(self.slot) is self:
            del _SLOTS[self.slot]
        self.slot = None
        if instant:
            self._land_open(target)
        else:
            self._slide(start, target, lambda: self._land_open(target))
        if self.owner is not None and self.owner.parked:
            self.owner.expand(instant=True)

    def _land_open(self, target):
        w = self.window
        self.env.release(w)
        try:
            w.Top = target
        except Exception:
            pass
        try:
            w.MinHeight = self.saved.get('min_height', 0)
        except Exception:
            pass
        self._unpin_body()

    def released(self):
        """Window closing: free the slot, bring a parked owner back."""
        if self.slot is not None and _SLOTS.get(self.slot) is self:
            del _SLOTS[self.slot]
        self.slot = None
        try:
            if self.timer is not None:
                self.timer.Stop()
        except Exception:
            pass
        if self.owner is not None:
            try:
                self.owner.children.remove(self)
            except Exception:
                pass
            if self.owner.parked:
                self.owner.expand(instant=True)

    # ------------------------------------------------------------------
    def _slide(self, start, end, land):
        """Ease Top from start to end, then land. Any failure lands."""
        env = self.env
        self.sliding = True
        state = {'t0': None}
        try:
            state['t0'] = env.now_ms()      # the first frame already moves
        except Exception:
            pass

        def finish():
            try:
                if self.timer is not None:
                    self.timer.Stop()
            except Exception:
                pass
            self.sliding = False
            try:
                land()
            except Exception as ex:
                self.errors.append(ex)

        def tick(sender, args):
            try:
                now = env.now_ms()
                if state['t0'] is None:
                    state['t0'] = now
                t = (now - state['t0']) / SLIDE_MS
                if t >= 1.0:
                    finish()
                    return
                k = cm_logic.ease_out_cubic(t)
                self.window.Top = start + (end - start) * k
            except Exception as ex:
                self.errors.append(ex)
                finish()

        try:
            self.timer = env.make_timer(TICK_MS, tick)
            self.timer.Start()
        except Exception as ex:
            self.errors.append(ex)
            finish()

    # ------------------------------------------------------------------
    def on_key(self, key_name, ctrl, shift):
        """Returns True when the key is consumed."""
        if ctrl and shift and key_name == 'H':
            self.toggle()
            return True
        if self.sliding:
            return True
        if self.parked:
            if key_name in ('Escape', 'Return', 'Enter', 'F11'):
                self.expand()
            return True              # nothing acts on a window nobody sees
        return False

    def on_header_double_click(self):
        """True when the drawer took it (parked: reopen, not maximise)."""
        if self.parked:
            if not self.sliding:
                self.expand()
            return True
        return False

    def can_drag(self):
        return not self.sliding and not self.busy


def attach(window, find, env=None):
    """Make a drawer for a window built from a RevoBIM layout and wire it.

    find(name) returns a named element. Every layout draws header_bar,
    body, shrink_btn, shrink_glyph and expand_glyph; grips is optional.
    The siblings collapsed while parked are body + footer + toolbar - every
    child of the root grid apart from the header.
    """
    header = find('header_bar')
    body = find('body')
    btn = find('shrink_btn')
    sg = find('shrink_glyph')
    eg = find('expand_glyph')
    grips = find('grips')
    siblings = []
    try:
        root = find('root_grid')
        for child in root.Children:
            if child is not header and child is not grips:
                siblings.append(child)
    except Exception:
        pass
    drawer = WindowDrawer(window, header, body, btn, sg, eg, grips=grips,
                          env=env, siblings=siblings)
    btn.Click += lambda s, a: drawer.toggle()
    try:
        window.Closed += lambda s, a: drawer.released()
    except Exception:
        pass
    drawer._set_glyphs(False)
    return drawer
