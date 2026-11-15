# -*- coding: utf-8 -*-
"""Unhide in View - window plumbing shared by the house style.

XAML loading, the palette, following Revit's canvas theme, the icon,
owner handle, resize grips, full screen by bounds and the easter egg.
Anything decorative is wrapped so cosmetics can never take the tool down.
"""
import uiv_clr  # noqa: F401  - assembly references first, always

import time
import traceback

from System import Byte, TimeSpan
from System.IO import File, MemoryStream
from System.Windows import (
    HorizontalAlignment, VerticalAlignment, FrameworkElement, PresentationSource,
    UIElement, Visibility, CornerRadius, Point, SizeToContent,
)
from System.Windows.Controls.Primitives import Thumb, DragDeltaEventHandler
from System.Windows.Input import Cursors, MouseButtonEventHandler
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Markup import XamlReader
from System.Windows.Media import SolidColorBrush, Color
from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption
from System.Windows.Threading import DispatcherTimer
from System.Windows.Forms import Screen

import uiv_core as core


# =====================================================================
# XAML
# =====================================================================

def load_xaml(path):
    """XamlReader.Parse on the file text. A layout that will not parse raises
    here with the line and column, and the loader reports it by stage."""
    return XamlReader.Parse(File.ReadAllText(path))


def load_window(layout_path, theme_path):
    window = load_xaml(layout_path)
    theme = load_xaml(theme_path)
    window.Resources.MergedDictionaries.Add(theme)
    return window


def find(window, names):
    out = {}
    missing = []
    for n in names:
        el = window.FindName(n)
        if el is None:
            missing.append(n)
        out[n] = el
    if missing:
        raise LookupError('Layout is missing: ' + ', '.join(missing))
    return out


# =====================================================================
# Palette and theme
# =====================================================================

def brush(hex_text):
    r, g, b = core.hex_to_rgb(hex_text)
    br = SolidColorBrush(Color.FromRgb(Byte(r), Byte(g), Byte(b)))
    br.Freeze()
    return br


def apply_palette(window, name):
    """Written onto Window.Resources, in front of the merged Theme.xaml, so
    every DynamicResource on the open window swaps with no reload."""
    pal = core.PALETTES.get(name) or core.PALETTES['dark']
    for key, hx in pal.items():
        try:
            window.Resources[key] = brush(hx)
        except Exception:
            pass


def canvas_theme(uiapp):
    """Revit's canvas: UIThemeManager.CurrentCanvasTheme (2024+, reached by
    getattr so older releases do not fail at import), then the canvas
    background colour, then the UI theme. UITheme.Dark is 0, so every read
    is tested 'is not None', never for truth."""
    try:
        import Autodesk.Revit.UI as rui
        mgr = getattr(rui, 'UIThemeManager', None)
        if mgr is not None:
            value = getattr(mgr, 'CurrentCanvasTheme', None)
            if value is not None:
                t = core.theme_from_enum_text(value.ToString())
                if t is not None:
                    return t
    except Exception:
        pass
    try:
        c = uiapp.Application.BackgroundColor
        if c is not None:
            t = core.theme_from_background(c.Red, c.Green, c.Blue)
            if t is not None:
                return t
    except Exception:
        pass
    try:
        import Autodesk.Revit.UI as rui
        mgr = getattr(rui, 'UIThemeManager', None)
        if mgr is not None:
            value = getattr(mgr, 'CurrentTheme', None)
            if value is not None:
                return core.theme_from_enum_text(value.ToString())
    except Exception:
        pass
    return None


# =====================================================================
# Images and ownership
# =====================================================================

def load_bitmap(path):
    """From bytes, never UriSource: System.Uri moved assembly in Revit 2025."""
    try:
        data = File.ReadAllBytes(path)
        bmp = BitmapImage()
        bmp.BeginInit()
        bmp.CacheOption = BitmapCacheOption.OnLoad
        bmp.StreamSource = MemoryStream(data)
        bmp.EndInit()
        bmp.Freeze()
        return bmp
    except Exception:
        return None


def own_to_revit(window, uiapp):
    """An unowned modeless window slips behind Revit and reads as a crash."""
    try:
        WindowInteropHelper(window).Owner = uiapp.MainWindowHandle
        return True
    except Exception:
        return False


# =====================================================================
# Resize grips - a borderless AllowsTransparency window has no frame to hit
# =====================================================================

_GRIPS = [
    # name, h-align, v-align, width, height, cursor, edges
    ('L', 'Left', 'Stretch', 5, None, 'SizeWE', 'L'),
    ('R', 'Right', 'Stretch', 5, None, 'SizeWE', 'R'),
    ('T', 'Stretch', 'Top', None, 5, 'SizeNS', 'T'),
    ('B', 'Stretch', 'Bottom', None, 5, 'SizeNS', 'B'),
    ('TL', 'Left', 'Top', 9, 9, 'SizeNWSE', 'TL'),
    ('BR', 'Right', 'Bottom', 9, 9, 'SizeNWSE', 'BR'),
    ('TR', 'Right', 'Top', 9, 9, 'SizeNESW', 'TR'),
    ('BL', 'Left', 'Bottom', 9, 9, 'SizeNESW', 'BL'),
]


def add_resize_grips(window, layer, on_resized=None):
    for name, ha, va, w, h, cur, edges in _GRIPS:
        try:
            th = Thumb()
            th.SetResourceReference(FrameworkElement.StyleProperty, 'RbGrip')
            th.HorizontalAlignment = getattr(HorizontalAlignment, ha)
            th.VerticalAlignment = getattr(VerticalAlignment, va)
            if w is not None:
                th.Width = w
            if h is not None:
                th.Height = h
            th.Cursor = getattr(Cursors, cur)
            th.DragDelta += _make_drag(window, edges, on_resized)
            layer.Children.Add(th)
        except Exception:
            pass


def _make_drag(window, edges, on_resized):
    def handler(sender, e):
        try:
            dx = e.HorizontalChange
            dy = e.VerticalChange
            if 'L' in edges:
                new_w = max(window.MinWidth, window.Width - dx)
                window.Left += window.Width - new_w
                window.Width = new_w
            if 'R' in edges:
                window.Width = max(window.MinWidth, window.Width + dx)
            if 'T' in edges:
                new_h = max(window.MinHeight, window.Height - dy)
                window.Top += window.Height - new_h
                window.Height = new_h
            if 'B' in edges:
                window.Height = max(window.MinHeight, window.Height + dy)
            if on_resized is not None:
                on_resized()
        except Exception:
            pass
    return DragDeltaEventHandler(handler)


# =====================================================================
# Screen working area, in WPF units
# =====================================================================

def work_area(window):
    """(left, top, width, height) of the working area of the screen the
    window is on - not the primary monitor - divided by the DPI scale.
    A monitor above the primary one has a negative top."""
    hwnd = WindowInteropHelper(window).Handle
    area = Screen.FromHandle(hwnd).WorkingArea
    sx = 1.0
    sy = 1.0
    try:
        src = PresentationSource.FromVisual(window)
        m = src.CompositionTarget.TransformToDevice
        sx = m.M11 or 1.0
        sy = m.M22 or 1.0
    except Exception:
        pass
    return (area.Left / sx, area.Top / sy, area.Width / sx, area.Height / sy)


# =====================================================================
# Full screen by bounds
# =====================================================================

class FullScreen(object):
    """Never WindowState.Maximized: on a borderless transparent window that
    covers the task bar and lands on the primary monitor."""

    def __init__(self, window):
        self.window = window
        self.saved = None

    def active(self):
        return self.saved is not None

    def toggle(self):
        if self.active():
            self.leave()
        else:
            self.enter()

    def enter(self):
        w = self.window
        try:
            self.saved = (w.Left, w.Top, w.Width, w.Height)
            left, top, width, height = work_area(w)
            w.Left = left
            w.Top = top
            w.Width = width
            w.Height = height
        except Exception:
            self.saved = None

    def leave(self):
        if self.saved is None:
            return
        w = self.window
        left, top, width, height = self.saved
        self.saved = None
        try:
            w.Left = left
            w.Top = top
            w.Width = width
            w.Height = height
        except Exception:
            pass

    def forget(self):
        """Dragging or resizing by hand counts as leaving full screen."""
        self.saved = None


# =====================================================================
# Shrink to taskbar - a drawer sliding the window down to its header bar
# =====================================================================

def _dispatcher_timer(ms, fn):
    """A DispatcherTimer calling fn each tick. The handler is returned with
    it so the caller can hold it - an IronPython delegate nothing holds can
    be collected while the timer still runs."""
    t = DispatcherTimer()
    t.Interval = TimeSpan.FromMilliseconds(ms)

    def tick(sender, e):
        fn()
    t.Tick += tick
    return t, tick


class WindowDrawer(object):
    """Slides a borderless window down to the bottom of its screen, leaving
    only its header bar floating clear of the taskbar, and back again.

      window  the Window
      header  the header Border - the bar that stays
      root    the window's root layout element, pinned during the slide
      button  the shrink button; Tag 'shrunk' turns it into the green arrow
      grips   the resize-grip overlay, parked with the window

    Top and Height are eased together on a 15 ms timer (ease-out cubic,
    0.28 s) rather than by a Storyboard: an animation holds its end value
    over every later assignment, and on a borderless window it fights the
    layout pass. Every frame is a plain assignment, so nothing is left
    holding the window when the slide ends. A frame that throws lands the
    window at the end state.

    Everything WPF-specific that varies between Revit and the bench comes
    in as an argument: the timer, the clock and the screen lookup.
    """

    def __init__(self, window, header, root, button, grips, log=None,
                 make_timer=None, clock=None, area_of=None, on_change=None):
        self.window = window
        self.header = header
        self.root = root
        self.button = button
        self.grips = grips
        self.log = log
        self.make_timer = make_timer or _dispatcher_timer
        self.clock = clock or time.time
        self.area_of = area_of or work_area
        self.on_change = on_change
        self.state = 'open'           # open | shrinking | parked | expanding
        self.saved = None             # (left, top, width, height) when shrunk
        self.saved_min = 0.0
        self.saved_stc = None
        self.saved_corner = None
        self.bar_h = 0.0
        self.landing_top = 0.0
        self.parked_at = None         # (left, top) of the bar when it landed
        self.parts = []               # [(element, Visibility before)]
        self.timer = None
        self.tick_ref = None
        self.anim = None
        try:
            self.button.Tag = u''
            self.button.ToolTip = core.SHRINK_TIP
        except Exception:
            pass

    # ---- state -----------------------------------------------------------
    def is_open(self):
        return self.state == 'open'

    def is_parked(self):
        return self.state == 'parked'

    def busy(self):
        return self.state in ('shrinking', 'expanding')

    def true_bounds(self):
        """The window's real size and place, even while shrunk - so closing
        a parked window never saves a 42-pixel-high window."""
        if self.state != 'open' and self.saved is not None:
            return self.saved
        w = self.window
        return (w.Left, w.Top, w.Width, w.Height)

    def _say(self, text):
        if self.log is not None:
            try:
                self.log.add(text)
            except Exception:
                pass

    # ---- the gesture -------------------------------------------------------
    def toggle(self):
        if self.state == 'open':
            return self.shrink()
        if self.state == 'parked':
            return self.expand()
        return False                  # mid-slide: a second click is ignored

    def shrink(self):
        if self.state != 'open':
            return False
        w = self.window
        try:
            area = self.area_of(w)
        except Exception:
            self._say(u'Shrink: screen area unreadable - ' + traceback.format_exc())
            return False
        self.saved = (w.Left, w.Top, w.Width, w.Height)
        self.saved_min = w.MinHeight
        self.saved_stc = w.SizeToContent
        self.bar_h = core.bar_height(self.header.ActualHeight, self._frame_offset())
        self.landing_top = core.parked_top(area, self.bar_h)
        # what is visible now is what comes back - recorded before anything
        # is collapsed, the grips included
        self.parts = [(el, el.Visibility) for el in self._parts_to_park()]
        self.saved_corner = self.header.CornerRadius
        # MinHeight and SizeToContent both veto a shrinking Height
        w.MinHeight = 0.0
        w.SizeToContent = SizeToContent.Manual
        self._pin(self.root.ActualHeight)
        self.grips.Visibility = Visibility.Collapsed
        self.button.Tag = u'shrunk'
        self.button.ToolTip = core.EXPAND_TIP
        self.state = 'shrinking'
        self._say(u'Shrink: {0} -> bar {1:.0f} high at top {2:.0f}'.format(
            self.saved, self.bar_h, self.landing_top))
        self._slide(w.Top, self.landing_top, w.Height, self.bar_h, self._landed_parked)
        return True

    def expand(self, animate=True):
        if self.state != 'parked':
            return False
        w = self.window
        now = (w.Left, w.Top)
        try:
            area = self.area_of(w)
        except Exception:
            area = (self.saved[0], self.saved[1], self.saved[2], self.saved[3])
        left, top, width, height = core.expand_bounds(
            self.saved, self.parked_at, now, self.bar_h, area)
        moved = core.bar_moved(self.parked_at, now)
        for el, vis in self.parts:
            try:
                el.Visibility = vis
            except Exception:
                pass
        try:
            self.header.CornerRadius = self.saved_corner
        except Exception:
            pass
        self._pin(height)
        w.Left = left
        w.Width = width
        self.state = 'expanding'
        self._say(u'Expand to ({0:.0f}, {1:.0f}, {2:.0f}, {3:.0f}){4}'.format(
            left, top, width, height, u' - bar was moved' if moved else u''))
        self._slide(w.Top, top, w.Height, height, self._landed_open, animate)
        return True

    def restore_now(self):
        """Put the window back with no animation, whatever it is doing."""
        if self.state in ('shrinking', 'expanding'):
            self._finish()
        if self.state == 'parked':
            self.expand(animate=False)

    def stop(self):
        try:
            if self.timer is not None:
                self.timer.Stop()
        except Exception:
            pass
        self.timer = None

    def on_header_down(self, e):
        """Header mouse-down while shrunk: a double-click opens the window,
        a single click drags the bar. True when handled here."""
        if self.state == 'open':
            return False
        if self.state == 'parked':
            if e.ClickCount == 2:
                self.expand()
            else:
                try:
                    self.window.DragMove()
                except Exception:
                    pass
        return True

    # ---- the slide ------------------------------------------------------------
    def _slide(self, top0, top1, h0, h1, done, animate=True):
        self.anim = (self.clock(), top0, top1, h0, h1, done)
        if not animate:
            self._finish()
            return
        try:
            timer, tick = self.make_timer(core.DRAWER_TICK_MS, self._tick)
            self.timer = timer
            self.tick_ref = tick
            timer.Start()
        except Exception:
            self._say(u'Drawer timer would not start - landing at once: ' + traceback.format_exc())
            self._finish()

    def _tick(self):
        anim = self.anim
        if anim is None:
            self.stop()
            return
        t0, top0, top1, h0, h1, done = anim
        try:
            p = (self.clock() - t0) / core.DRAWER_SECONDS
            e = core.ease_out(p)
            self.window.Top = core.lerp(top0, top1, e)
            self.window.Height = max(1.0, core.lerp(h0, h1, e))
            if p >= 1.0:
                self._finish()
        except Exception:
            self._say(u'Drawer frame failed - landing at the end: ' + traceback.format_exc())
            self._finish()

    def _finish(self):
        self.stop()
        anim = self.anim
        self.anim = None
        if anim is None:
            return
        t0, top0, top1, h0, h1, done = anim
        try:
            self.window.Top = top1
            self.window.Height = h1
        except Exception:
            self._say(u'Drawer could not set the final bounds: ' + traceback.format_exc())
        done()

    def _landed_parked(self):
        for el, vis in self.parts:
            try:
                el.Visibility = Visibility.Collapsed
            except Exception:
                pass
        try:
            self.header.CornerRadius = CornerRadius(6.0)
        except Exception:
            pass
        self._unpin()
        self.parked_at = (self.window.Left, self.window.Top)
        self.state = 'parked'
        self._changed()

    def _landed_open(self):
        w = self.window
        self._unpin()
        try:
            w.MinHeight = self.saved_min
            if self.saved_stc is not None:
                w.SizeToContent = self.saved_stc
        except Exception:
            pass
        self.button.Tag = u''
        self.button.ToolTip = core.SHRINK_TIP
        self.state = 'open'
        try:
            w.Activate()
        except Exception:
            pass
        self._changed()

    def _changed(self):
        if self.on_change is not None:
            try:
                self.on_change(self.state)
            except Exception:
                pass

    # ---- layout --------------------------------------------------------------
    def _pin(self, height):
        """Hold the layout at full size for the slide and let the window
        clip it: re-measuring every frame reads as a window being squashed,
        not a drawer being drawn away, and churns the virtualised grids."""
        try:
            self.root.Height = height
            self.root.VerticalAlignment = VerticalAlignment.Top
        except Exception:
            pass

    def _unpin(self):
        try:
            self.root.Height = float('nan')
            self.root.VerticalAlignment = VerticalAlignment.Stretch
        except Exception:
            pass

    def _frame_offset(self):
        """How far the header sits inside the window - the outer border."""
        try:
            return self.header.TranslatePoint(Point(0, 0), self.window).Y
        except Exception:
            return 1.0

    def _parts_to_park(self):
        """Everything except the header and the frames holding it: from the
        header up to the window, every sibling at each level - the body,
        the footer, the confirm overlay and the grips."""
        out = []
        el = self.header
        guard = 0
        while el is not None and el is not self.window and guard < 30:
            guard += 1
            parent = getattr(el, 'Parent', None)
            if parent is None:
                break
            kids = getattr(parent, 'Children', None)
            if kids is not None:
                for k in kids:
                    if k is not el:
                        out.append(k)
            el = parent
        return out


# =====================================================================
# Easter egg - three slow clicks on the RevoBIM logo
# =====================================================================

def attach_egg(window, logo, theme_name, log):
    """revobim.egg.egg_hook.attach_to_window, then attach, then a local
    slow-click counter calling launch. Never allowed to raise."""
    hook = None
    try:
        from revobim.egg import egg_hook as hook
    except Exception:
        hook = None
    if hook is not None:
        for fname in ('attach_to_window', 'attach'):
            fn = getattr(hook, fname, None)
            if fn is None:
                continue
            for args in ((window, logo), (window,)):
                try:
                    fn(*args)
                    log.add(u'Easter egg attached via egg_hook.' + fname)
                    return fname
                except TypeError:
                    continue
                except Exception:
                    break
    counter = core.SlowClicks()

    def on_click(sender, e):
        try:
            if counter.add(e.Timestamp / 1000.0):
                launch = getattr(hook, 'launch', None) if hook is not None else None
                if launch is not None:
                    launch(window, theme_name(), None)
        except Exception:
            pass
    try:
        logo.AddHandler(UIElement.MouseLeftButtonDownEvent,
                        MouseButtonEventHandler(on_click), True)
        log.add(u'Easter egg attached via local slow-click counter')
        return 'local'
    except Exception:
        log.add(u'Easter egg not attached: ' + traceback.format_exc())
        return None
