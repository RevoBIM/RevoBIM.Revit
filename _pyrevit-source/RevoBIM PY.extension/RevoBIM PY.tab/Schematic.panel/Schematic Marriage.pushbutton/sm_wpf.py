# -*- coding: utf-8 -*-
"""Schematic Marriage - shared WPF plumbing.

Theme (palette, canvas following, the header chip), window chrome (drag,
full screen, resize grips, close), table columns bound through converters,
themed context menus and the themed prompt. No Revit document access here.
"""
import sm_clr  # noqa: F401  (must stay first - references the assemblies)

import os
import traceback

from System import Action, TimeSpan, EventHandler
from System.Collections.Generic import List
from System.IO import File, FileStream, FileMode, FileAccess, MemoryStream
from System.Windows import (
    Thickness, Visibility, VerticalAlignment, TextTrimming, FontWeights,
    DataTemplate, FrameworkElementFactory, RoutedEventHandler, DependencyProperty,
    PresentationSource, SystemParameters, TextWrapping, Clipboard, Size, FrameworkElement,
    Point, CornerRadius, SizeToContent, WindowStartupLocation, Style, Setter, DataTrigger,
    DynamicResourceExtension,
)
from System.Windows.Controls import (
    TextBlock, TextBox, Button, StackPanel, ContextMenu, MenuItem,
    DataGridTemplateColumn, DataGridLength, DataGridLengthUnitType, ListBoxItem,
    Orientation, ScrollViewer, ScrollBarVisibility, ToolTipService, ToolTipEventHandler, DataGridRow,
)
from System.Windows.Controls.Primitives import PlacementMode
from System.Windows.Data import Binding, IValueConverter, RelativeSource, RelativeSourceMode
from System.Windows.Input import Key, Keyboard, ModifierKeys
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Markup import XamlReader
from System.Windows.Media import SolidColorBrush, ColorConverter, VisualTreeHelper, FontFamily, CompositionTarget
from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption
from System.Windows.Threading import Dispatcher, DispatcherPriority, DispatcherTimer

import sm_store as store
from sm_store import to_text
from sm_version import __version__

HERE = os.path.dirname(os.path.abspath(__file__))


# ==========================================================================
# palette
# ==========================================================================

PALETTES = {
    'dark': {   # Revit's own dark UI - house values, see the theme reference
        'BgBrush': '#353C4A', 'CardBrush': '#3C4454', 'FieldBrush': '#2D3441',
        'BarBrush': '#222933', 'HeadBrush': '#323C48', 'EdgeBrush': '#515C6B',
        'FrameBrush': '#515C6B', 'TextBrush': '#EEF0F4', 'MutedBrush': '#A4AAB1',
        'BlueBrush': '#5AAEEB', 'OrangeBrush': '#E8912D', 'GreenBrush': '#3FA75A',
        'GreenHoverBrush': '#4EC06D', 'RedBrush': '#D9534F', 'SelBrush': '#3A7392',
        'HoverBrush': '#444E5E', 'RowAltBrush': '#404858', 'OnAccentBrush': '#FFFFFF',
        'HoverOverlayBrush': '#1EFFFFFF', 'DisabledBrush': '#4A5263', 'ScrollBrush': '#5A6475',
        'OrangeSoftBrush': '#4E4538', 'BlueSoftBrush': '#34495E',
    },
    'light': {
        'BgBrush': '#F3F3F5', 'CardBrush': '#FFFFFF', 'FieldBrush': '#FAFAFB',
        'BarBrush': '#E7E7EB', 'HeadBrush': '#EDEDF1', 'EdgeBrush': '#CDCDD3', 'FrameBrush': '#B8B8C0',
        'TextBrush': '#1F1F23', 'MutedBrush': '#6B6B73', 'BlueBrush': '#1B72BE',
        'OrangeBrush': '#B96A12', 'GreenBrush': '#2E8546', 'GreenHoverBrush': '#379C53',
        'RedBrush': '#C0392B', 'SelBrush': '#CFE3F6', 'HoverBrush': '#ECEFF3',
        'RowAltBrush': '#F6F7F9', 'OnAccentBrush': '#FFFFFF', 'HoverOverlayBrush': '#14000000',
        'DisabledBrush': '#D0D0D6', 'ScrollBrush': '#C4C4CC', 'OrangeSoftBrush': '#F8E9D6',
        'BlueSoftBrush': '#DCEAF7',
    },
}


def brush(hex_text):
    b = SolidColorBrush(ColorConverter.ConvertFromString(hex_text))
    try:
        b.Freeze()
    except Exception:
        pass
    return b


def apply_palette(resources, mode):
    palette = PALETTES.get(mode) or PALETTES['dark']
    for key in palette:
        resources[key] = brush(palette[key])


def canvas_theme():
    """'dark' / 'light' from Revit's canvas, or None when it cannot be read.
    UIThemeManager only exists from Revit 2024, so it is reached by getattr.
    UITheme.Dark is 0 - test the read with `is not None`, never truthiness."""
    try:
        import Autodesk.Revit.UI as rui
        mgr = getattr(rui, 'UIThemeManager', None)
        if mgr is None:
            return None
        for prop in ('CurrentCanvasTheme', 'CurrentTheme'):
            try:
                value = getattr(mgr, prop)
            except Exception:
                continue
            if value is None:
                continue
            name = to_text(value).lower()
            if 'dark' in name:
                return 'dark'
            if 'light' in name:
                return 'light'
    except Exception:
        pass
    return None


def resolve_theme(setting):
    if setting == 'dark' or setting == 'light':
        return setting
    return canvas_theme() or 'dark'


# ==========================================================================
# loading
# ==========================================================================

def load_xaml(name):
    path = os.path.join(HERE, name)
    fs = FileStream(path, FileMode.Open, FileAccess.Read)
    try:
        return XamlReader.Load(fs)
    finally:
        fs.Close()


def load_bitmap(path):
    """From bytes, never from a Uri (System.Uri moved in Revit 2025)."""
    try:
        if not os.path.exists(path):
            return None
        bmp = BitmapImage()
        bmp.BeginInit()
        bmp.StreamSource = MemoryStream(File.ReadAllBytes(path))
        bmp.CacheOption = BitmapCacheOption.OnLoad
        bmp.EndInit()
        bmp.Freeze()
        return bmp
    except Exception:
        return None


def do_events():
    """Let WPF repaint. Only ever called BETWEEN transactions."""
    try:
        Dispatcher.CurrentDispatcher.Invoke(Action(lambda: None), DispatcherPriority.Background)
    except Exception:
        pass


class Debounce(object):
    def __init__(self, ms, fn, on_error=None):
        self.fn = fn
        self.on_error = on_error
        self.timer = DispatcherTimer()
        self.timer.Interval = TimeSpan.FromMilliseconds(ms)
        self.timer.Tick += self._tick

    def poke(self):
        self.timer.Stop()
        self.timer.Start()

    def stop(self):
        try:
            self.timer.Stop()
        except Exception:
            pass

    def _tick(self, sender, args):
        self.timer.Stop()
        try:
            self.fn()
        except Exception:
            if self.on_error is not None:
                self.on_error(traceback.format_exc())


class Tween(object):
    """A short animation driven by CompositionTarget.Rendering - WPF's own
    once-per-frame callback, in step with the screen - rather than a
    DispatcherTimer, which drifts against the refresh and stutters.
    step(e) gets e from 0 to 1 (ease-out cubic unless ease is False), then
    done() runs. The clock starts on the first rendered frame, so the time
    spent building the animation never shows up as a jump."""

    MAX_FRAME_MS = 34.0      # a frame that took longer than this only advances this much

    def __init__(self, ms, step, done=None, first_frame=None):
        self.ms = float(ms)
        self.step = step
        self.done = done
        self.first_frame = first_frame
        self.ease = True
        self.t0 = None
        self.elapsed = 0.0
        self.last = None
        self.running = False
        # one delegate object, so -= removes exactly what += added
        self._handler = EventHandler(self._tick)

    def start(self):
        self.t0 = None
        self.elapsed = 0.0
        self.last = None
        if not self.running:
            self.running = True
            CompositionTarget.Rendering += self._handler

    def stop(self):
        if self.running:
            self.running = False
            try:
                CompositionTarget.Rendering -= self._handler
            except Exception:
                pass

    @staticmethod
    def _frame_ms(args):
        """The frame's own presentation time (RenderingEventArgs), which is
        exact and identical for everything drawn in that frame - unlike a
        wall clock read in Python, whose resolution can be ~15ms on Windows
        and is what made the motion uneven."""
        try:
            return float(args.RenderingTime.TotalMilliseconds)
        except Exception:
            from System.Diagnostics import Stopwatch
            return Stopwatch.GetTimestamp() * 1000.0 / Stopwatch.Frequency

    def _tick(self, sender, args):
        if not self.running:
            return
        now = self._frame_ms(args)
        if self.last is not None and now <= self.last:
            return                    # Rendering can fire twice for one frame
        if self.t0 is None:
            self.t0 = now
            if self.first_frame is not None:
                try:
                    self.first_frame()
                except Exception:
                    pass
        else:
            # never let one slow frame (Revit busy) turn into a visible jump
            self.elapsed += min(now - self.last, self.MAX_FRAME_MS)
        self.last = now
        t = min(1.0, self.elapsed / self.ms)
        e = 1.0 - (1.0 - t) ** 3 if self.ease else t
        try:
            self.step(e)
        except Exception:
            t = 1.0
        if t >= 1.0:
            self.stop()
            if self.done is not None:
                try:
                    self.done()
                except Exception:
                    pass


def _smooth(p):
    """Ease in and out (smootherstep) - no visible start or stop."""
    p = max(0.0, min(1.0, p))
    return p * p * p * (p * (p * 6.0 - 15.0) + 10.0)


def genie(win, tx, ty, done, owner=None, ms=600.0, strips=56, reverse=False):
    """Mac-style "minimise to the dock": snapshot the window, cut it into
    horizontal strips, and pour them into the point (tx, ty) - the bottom
    strips narrow and move first, the top ones follow, so it funnels down
    like the genie effect. reverse=True plays it backwards: the window pours
    OUT of (tx, ty) - the Mac "restore from the dock".

    Smoothness: every strip is laid out ONCE at full size and only its
    MatrixTransform changes per frame (render-only, no layout pass); frames
    come from CompositionTarget.Rendering; easing is smootherstep with the
    narrowing led along a curve, so the edge of the funnel is curved rather
    than stepped. Any failure just calls done()."""
    try:
        from System.Windows import Window, WindowStyle, Int32Rect
        from System.Windows.Controls import Canvas, Image
        from System.Windows.Media import PixelFormats, Stretch, MatrixTransform, Matrix, RenderOptions, \
            BitmapScalingMode
        from System.Windows.Media.Imaging import RenderTargetBitmap, CroppedBitmap

        W, H = float(win.ActualWidth), float(win.ActualHeight)
        L, T = float(win.Left), float(win.Top)
        sx, sy = 1.0, 1.0
        src = PresentationSource.FromVisual(win)
        if src is not None:
            m = src.CompositionTarget.TransformToDevice
            sx, sy = m.M11, m.M22
        pw, ph = int(round(W * sx)), int(round(H * sy))
        rtb = RenderTargetBitmap(pw, ph, 96.0 * sx, 96.0 * sy, PixelFormats.Pbgra32)
        rtb.Render(win.Content)
        rtb.Freeze()

        ox = min(L, tx - 30.0)
        oy = min(T, ty - 30.0)
        ow = max(L + W, tx + 30.0) - ox
        oh = max(T + H, ty + 30.0) - oy
        over = Window()
        over.WindowStyle = getattr(WindowStyle, 'None')
        over.AllowsTransparency = True
        over.Background = SolidColorBrush(ColorConverter.ConvertFromString('#00000000'))
        over.ShowInTaskbar = False
        over.ShowActivated = False
        over.UseLayoutRounding = False
        over.SnapsToDevicePixels = False
        over.Left, over.Top, over.Width, over.Height = ox, oy, ow, oh
        if owner is not None:
            over.Owner = owner
        canvas = Canvas()
        over.Content = canvas

        n = max(8, int(strips))
        sh = H / n
        parts = []
        for i in range(n):
            y_px = int(round(i * sh * sy))
            h_px = max(1, min(ph - y_px, int(round((i + 1) * sh * sy)) - y_px))
            img = Image()
            img.Source = CroppedBitmap(rtb, Int32Rect(0, y_px, pw, h_px))
            img.Stretch = Stretch.Fill
            img.Width = W                     # laid out once at full size ...
            img.Height = sh + 0.8             # ... with a hair of overlap to hide seams
            RenderOptions.SetBitmapScalingMode(img, BitmapScalingMode.Linear)
            mt = MatrixTransform()
            img.RenderTransform = mt          # ... and only this changes per frame
            canvas.Children.Add(img)
            parts.append((mt, T + i * sh - oy))
        cx0 = L + W / 2.0 - ox
        txl, tyl = tx - ox, ty - oy
        end_w = 22.0
        min_hs = min(1.0, 1.4 / max(sh, 1.0))  # a strip never thinner than ~1.4px (no shimmer)
        lag = 0.45                            # top strip starts this much later than the bottom one

        def place(t):
            for i, (mt, y0) in enumerate(parts):
                delay = lag * (1.0 - float(i + 1) / n)
                p = max(0.0, min(1.0, (t - delay) / (1.0 - lag)))
                pe = _smooth(p)
                pw_ = _smooth(min(1.0, p * 1.6))      # narrowing leads the fall
                width = W + (end_w - W) * pw_
                cx = cx0 + (txl - cx0) * pw_
                y = y0 + (tyl - y0) * pe
                hs = max(min_hs, 1.0 - 0.92 * pe)
                mt.Matrix = Matrix(width / W, 0.0, 0.0, hs, cx - width / 2.0, y)
            # long, soft fade so the last few frames - where everything is
            # tiny and piling into one point - are already nearly invisible
            canvas.Opacity = 1.0 if t < 0.62 else max(0.0, 1.0 - _smooth((t - 0.62) / 0.38))

        place(1.0 if reverse else 0.0)
        over.Show()

        def first():
            # hide the real window only once the overlay has painted a frame,
            # so there is never a blink between the two
            if not reverse:
                win.Opacity = 0.0

        def step(e):
            place(1.0 - e if reverse else e)

        def close_overlay():
            try:
                over.Close()
            except Exception:
                pass

        def finish():
            if reverse:
                # real window in first, overlay away only after that frame
                # has been drawn - no frame where neither or both show
                win.Opacity = 1.0
                Dispatcher.CurrentDispatcher.BeginInvoke(DispatcherPriority.Background, Action(close_overlay))
            else:
                close_overlay()
            done()

        tw = Tween(ms, step, finish, first_frame=first)
        tw.ease = False                       # strips carry their own easing
        tw.start()
        win.Tag = tw                          # keep it alive until it ends
    except Exception:
        try:
            win.Opacity = 1.0
        except Exception:
            pass
        done()


def screen_area_of(win):
    """(left, top, right, bottom) of the work area of the screen the window is
    on, in WPF units. top is negative on a monitor above the primary."""
    try:
        from System.Windows.Forms import Screen
        area = Screen.FromHandle(WindowInteropHelper(win).Handle).WorkingArea
        sx, sy = 1.0, 1.0
        src = PresentationSource.FromVisual(win)
        if src is not None:
            m = src.CompositionTarget.TransformToDevice
            sx, sy = m.M11, m.M22
        return area.Left / sx, area.Top / sy, area.Right / sx, area.Bottom / sy
    except Exception:
        wa = SystemParameters.WorkArea
        return wa.Left, wa.Top, wa.Right, wa.Bottom


class Drawer(object):
    """Shrink to taskbar (house standard, see the theme reference). The window
    drops like a drawer closing: its bar travels down to the bottom of the
    screen's work area, just above the taskbar, and the body slides down out
    of sight beneath it, leaving only the bar floating so Revit can be worked
    in. The button becomes a green up arrow; it, a double-click on the bar,
    Escape, Enter, F11 or Ctrl+Shift+H pull the window back up - upwards from
    wherever the bar has been dragged.

    Smooth the same way as genie(): a snapshot on a transparent overlay moved
    by transforms only, frames from CompositionTarget.Rendering, and the real
    window resized once, at the end. No WPF animation is used, so nothing is
    left holding Top or Height afterwards.

    companion: the owner window's Drawer. Shrinking a modal dialog takes its
    owner down too (the dialog parks above it), and the owner comes back when
    the dialog reopens or closes."""

    MS = 380.0

    def __init__(self, win, header, button, glyph_down, glyph_up, before=None, companion=None):
        self.win = win
        self.header = header
        self.button = button
        self.down = glyph_down
        self.up = glyph_up
        self.before = before          # e.g. leave full screen first
        self.companion = companion
        self.took_companion = False
        self.collapsed = False
        self.busy = False
        self.saved = None
        self.hidden = []
        self._radius = None
        self._tween = None
        button.Click += self._on_click

    # ---- public -----------------------------------------------------------
    def _on_click(self, sender, args):
        self.toggle()

    def toggle(self):
        if self.busy:
            return
        if self.collapsed:
            self.expand()
        else:
            self.collapse()

    def handle_key(self, args):
        """Ctrl+Shift+H toggles; while parked Escape / Enter / F11 reopen.
        -> True when the key was used."""
        mods = Keyboard.Modifiers
        both = ModifierKeys.Control | ModifierKeys.Shift
        if args.Key == Key.H and (mods & both) == both:
            self.toggle()
            return True
        if self.collapsed and args.Key in (Key.Escape, Key.Enter, Key.Return, Key.F11):
            self.toggle()
            return True
        return False

    def bar_height(self):
        try:
            return self._header_bottom()
        except Exception:
            return 48.0

    def release_companion(self):
        """Bring the owner back up (without activating it over this window)."""
        if self.took_companion and self.companion is not None:
            self.took_companion = False
            if self.companion.collapsed and not self.companion.busy:
                self.companion.expand()

    # ---- helpers ------------------------------------------------------------
    def _body(self):
        """Everything in the window that is not the header or its ancestors -
        the resize grips included, so the parked bar has no hidden handles."""
        chain = []
        el = self.header
        while el is not None and not el.Equals(self.win):
            chain.append(el)
            try:
                el = VisualTreeHelper.GetParent(el)
            except Exception:
                el = None
        out = []
        for el in chain[1:]:
            children = getattr(el, 'Children', None)
            if children is None:
                continue
            for c in children:
                if not any(c.Equals(x) for x in chain):
                    out.append(c)
        return out

    def _header_bottom(self):
        p = self.header.TranslatePoint(Point(0, 0), self.win)
        return float(p.Y) + float(self.header.ActualHeight) + 1.0     # + the frame's bottom edge

    def _snapshot(self):
        w = self.win
        W, H = float(w.ActualWidth), float(w.ActualHeight)
        sx, sy = 1.0, 1.0
        src = PresentationSource.FromVisual(w)
        if src is not None:
            m = src.CompositionTarget.TransformToDevice
            sx, sy = m.M11, m.M22
        from System.Windows.Media import PixelFormats
        from System.Windows.Media.Imaging import RenderTargetBitmap
        rtb = RenderTargetBitmap(int(round(W * sx)), int(round(H * sy)), 96.0 * sx, 96.0 * sy,
                                 PixelFormats.Pbgra32)
        rtb.Render(w.Content)
        rtb.Freeze()
        return rtb, W, H, sy

    def _overlay(self, L, o_top, W, o_h, rtb, hb, sy, win_y):
        """Transparent window over the drawer's track. Two images on
        TranslateTransforms: the body, then the bar drawn over it. win_y is
        where the window's top sits inside the overlay."""
        from System.Windows import Window, WindowStyle, Int32Rect
        from System.Windows.Controls import Canvas, Image
        from System.Windows.Media import Stretch, TranslateTransform
        from System.Windows.Media.Imaging import CroppedBitmap
        over = Window()
        over.WindowStyle = getattr(WindowStyle, 'None')
        over.AllowsTransparency = True
        over.Background = SolidColorBrush(ColorConverter.ConvertFromString('#00000000'))
        over.ShowInTaskbar = False
        over.ShowActivated = False
        over.Left, over.Top, over.Width, over.Height = L, o_top, W, o_h
        try:
            over.Owner = self.win.Owner
        except Exception:
            pass
        canvas = Canvas()
        canvas.ClipToBounds = True          # the body slides away under the bottom edge
        over.Content = canvas
        hb_px = int(round(hb * sy))
        moves = []
        for y_px, h_px, y in ((hb_px, rtb.PixelHeight - hb_px, win_y + hb), (0, hb_px, win_y)):
            if h_px <= 0:
                continue
            img = Image()
            img.Source = CroppedBitmap(rtb, Int32Rect(0, y_px, rtb.PixelWidth, h_px))
            img.Stretch = Stretch.Fill
            img.Width = W
            img.Height = h_px / sy
            Canvas.SetTop(img, y)
            tt = TranslateTransform()
            img.RenderTransform = tt
            canvas.Children.Add(img)
            moves.append(tt)
        return over, moves

    def _run(self, over, moves, drop, closing, done):
        """closing: the bar travels drop px down. opening: it starts drop px
        down and travels back up to 0."""
        def place(p):
            y = drop * _smooth(p)
            for tt in moves:
                tt.Y = y

        place(0.0 if closing else 1.0)
        over.Show()

        def first():
            if closing:
                self.win.Opacity = 0.0

        def step(e):
            place(e if closing else 1.0 - e)

        def close_overlay():
            try:
                over.Close()
            except Exception:
                pass

        def finish():
            self._tween = None
            try:
                done()
            finally:
                self.win.Opacity = 1.0
                Dispatcher.CurrentDispatcher.BeginInvoke(DispatcherPriority.Background, Action(close_overlay))
                self.busy = False

        self._tween = Tween(self.MS, step, finish, first_frame=first)
        self._tween.ease = False
        self._tween.start()

    def _show_glyph(self):
        self.down.Visibility = Visibility.Collapsed if self.collapsed else Visibility.Visible
        self.up.Visibility = Visibility.Visible if self.collapsed else Visibility.Collapsed
        self.button.ToolTip = (u'Open the window again (Ctrl+Shift+H, Esc, or double-click the bar)'
                               if self.collapsed else
                               u'Shrink to the taskbar - park the window as just this bar so Revit can be seen '
                               u'(Ctrl+Shift+H)')

    # ---- collapse / expand ---------------------------------------------------
    def collapse(self):
        w = self.win
        if self.before is not None:
            try:
                self.before()
            except Exception:
                pass
        offset = 0.0
        comp = self.companion
        if comp is not None and not comp.collapsed and not comp.busy:
            offset = comp.bar_height() + store.PARK_GAP
            self.took_companion = True
            comp.collapse()                 # the owner goes down underneath
        elif comp is not None and comp.collapsed:
            offset = comp.bar_height() + store.PARK_GAP
        self.busy = True
        try:
            w.UpdateLayout()
            L, T = float(w.Left), float(w.Top)
            rtb, W, H, sy = self._snapshot()
            hb = self._header_bottom()
            _l, _t, _r, area_bottom = screen_area_of(w)
            bar_top, o_top, o_h, drop = store.park_rect(T, H, hb, area_bottom, offset)
            over, moves = self._overlay(L, o_top, W, o_h, rtb, hb, sy, T - o_top)
        except Exception:
            self.busy = False
            return
        stc = None
        try:
            stc = w.SizeToContent
        except Exception:
            pass
        self.saved = {'H': H, 'minh': w.MinHeight, 'stc': stc, 'hb': hb, 'bar_top': bar_top}

        def done():
            self._set_collapsed(True)

        self._run(over, moves, drop, True, done)

    def _set_collapsed(self, on):
        w = self.win
        if on:
            sv = self.saved
            self.hidden = []
            for el in self._body():
                self.hidden.append((el, el.Visibility))
                el.Visibility = Visibility.Collapsed
            try:
                self._radius = self.header.CornerRadius
                self.header.CornerRadius = CornerRadius(6)
            except Exception:
                self._radius = None
            try:
                w.SizeToContent = getattr(SizeToContent, 'Manual')
            except Exception:
                pass
            w.MinHeight = 0                 # MinHeight would veto the bar height
            w.Height = sv['hb']
            w.Top = sv['bar_top']
            self.collapsed = True
        else:
            for el, vis in self.hidden:
                try:
                    el.Visibility = vis
                except Exception:
                    pass
            self.hidden = []
            if self._radius is not None:
                try:
                    self.header.CornerRadius = self._radius
                except Exception:
                    pass
            self.collapsed = False
        self._show_glyph()

    def expand(self):
        w = self.win
        sv = self.saved or {}
        self.busy = True
        full_h = float(sv.get('H', w.ActualHeight))
        hb = float(sv.get('hb', w.ActualHeight))
        bar_top = float(w.Top)
        _l, area_top, _r, _b = screen_area_of(w)
        top, drop = store.reopen_rect(bar_top, hb, full_h, area_top)
        w.Opacity = 0.0
        self._set_collapsed(False)
        w.Top = top
        w.Height = full_h
        w.MinHeight = sv.get('minh', w.MinHeight)
        try:
            if sv.get('stc') is not None:
                w.SizeToContent = sv['stc']
        except Exception:
            pass
        try:
            w.UpdateLayout()
            rtb, W, H2, sy = self._snapshot()
            hb2 = self._header_bottom()
            over, moves = self._overlay(float(w.Left), top, W, H2, rtb, hb2, sy, 0.0)
        except Exception:
            w.Opacity = 1.0
            self.busy = False
            self.release_companion()
            return
        self._run(over, moves, drop, False, lambda: None)
        self.release_companion()


# ==========================================================================
# converters and table columns
# ==========================================================================

class FuncConverter(IValueConverter):
    """Bind the row object itself ('.') and let Python decide the value."""

    def __init__(self, fn):
        self.fn = fn

    def Convert(self, value, target_type, parameter, culture):
        try:
            out = self.fn(value, parameter)
        except Exception:
            out = None
        if out is None:
            return DependencyProperty.UnsetValue
        return out

    def ConvertBack(self, value, target_type, parameter, culture):
        return None


def _bind(conv, key):
    b = Binding('.')
    b.Converter = conv
    b.ConverterParameter = key
    return b


def header_with_filter(title, brush_key, on_changed, filters=True):
    """A live header element: name above a keyword filter box."""
    panel = StackPanel()
    label = TextBlock()
    label.Text = title
    if brush_key:
        label.SetResourceReference(TextBlock.ForegroundProperty, brush_key)
    panel.Children.Add(label)
    box = None
    if filters:
        box = TextBox()
        box.Tag = u'filter'
        box.FontWeight = FontWeights.Normal
        box.FontSize = 11
        box.MinHeight = 22
        box.Padding = Thickness(4, 1, 4, 1)
        box.Margin = Thickness(0, 4, 0, 0)
        if on_changed is not None:
            box.TextChanged += on_changed
        panel.Children.Add(box)
    return panel, box


def selected_aware_style(ancestor_type, base_value):
    """A TextBlock style whose foreground is base_value (a Binding or a
    DynamicResourceExtension) but turns white while the row / item it sits in
    is selected - coloured and muted text is under 2.5:1 on Revit's selection
    blue. The colour goes in a Setter, not set locally, so the trigger can win."""
    import clr
    st = Style(clr.GetClrType(TextBlock))
    st.Setters.Add(Setter(TextBlock.ForegroundProperty, base_value))
    b = Binding('IsSelected')
    b.RelativeSource = RelativeSource(RelativeSourceMode.FindAncestor, clr.GetClrType(ancestor_type), 1)
    dt = DataTrigger()
    dt.Binding = b
    dt.Value = True
    dt.Setters.Add(Setter(TextBlock.ForegroundProperty, DynamicResourceExtension('OnAccentBrush')))
    st.Triggers.Add(dt)
    return st


def _only_when_trimmed(sender, args):
    """Show the cell's tooltip only when its text does not fit."""
    try:
        tb = sender
        tb.Measure(Size(float('inf'), float('inf')))
        if tb.DesiredSize.Width <= tb.ActualWidth + 0.5:
            args.Handled = True
    except Exception:
        pass


def tip_block(text):
    """Tooltip content that wraps instead of running off the screen."""
    t = TextBlock()
    t.Text = to_text(text)
    t.TextWrapping = TextWrapping.Wrap
    t.MaxWidth = 560
    return t


def text_column(header, key, text_conv, star=1.0, min_width=60, brush_conv=None, bold=False,
                tip_conv=None):
    col = DataGridTemplateColumn()
    col.Header = header
    col.SortMemberPath = key
    col.Width = DataGridLength(star, DataGridLengthUnitType.Star)
    col.MinWidth = min_width
    f = FrameworkElementFactory(TextBlock)
    f.SetBinding(TextBlock.TextProperty, _bind(text_conv, key))
    if brush_conv is not None:
        f.SetValue(TextBlock.StyleProperty, selected_aware_style(DataGridRow, _bind(brush_conv, key)))
    f.SetValue(TextBlock.MarginProperty, Thickness(8, 0, 6, 0))
    f.SetValue(TextBlock.VerticalAlignmentProperty, VerticalAlignment.Center)
    f.SetValue(TextBlock.TextTrimmingProperty, TextTrimming.CharacterEllipsis)
    if bold:
        f.SetValue(TextBlock.FontWeightProperty, FontWeights.SemiBold)
    if tip_conv is not None:
        # full description underneath the cell, only when the cell is cut short
        f.SetBinding(TextBlock.ToolTipProperty, _bind(tip_conv, key))
        f.SetValue(ToolTipService.PlacementProperty, PlacementMode.Bottom)
        f.SetValue(ToolTipService.InitialShowDelayProperty, 350)
        f.SetValue(ToolTipService.ShowDurationProperty, 30000)
        f.AddHandler(FrameworkElement.ToolTipOpeningEvent, ToolTipEventHandler(_only_when_trimmed))
    dt = DataTemplate()
    dt.VisualTree = f
    col.CellTemplate = dt
    return col


def button_column(header, key, text_conv, on_click, star=1.0, min_width=120, brush_conv=None,
                  bg_conv=None, border_conv=None):
    col = DataGridTemplateColumn()
    col.Header = header
    col.SortMemberPath = key
    col.Width = DataGridLength(star, DataGridLengthUnitType.Star)
    col.MinWidth = min_width
    f = FrameworkElementFactory(Button)
    f.SetResourceReference(Button.StyleProperty, 'CellBtn')
    f.SetBinding(Button.ContentProperty, _bind(text_conv, key))
    if brush_conv is not None:
        f.SetBinding(Button.ForegroundProperty, _bind(brush_conv, key))
    if bg_conv is not None:
        f.SetBinding(Button.BackgroundProperty, _bind(bg_conv, key))
    if border_conv is not None:
        f.SetBinding(Button.BorderBrushProperty, _bind(border_conv, key))
    f.AddHandler(Button.ClickEvent, RoutedEventHandler(on_click))
    dt = DataTemplate()
    dt.VisualTree = f
    col.CellTemplate = dt
    return col


def sort_direction(descending):
    """ListSortDirection without importing it: it lives in System.dll on
    Revit 2024 (.NET 4.8) and in System.ComponentModel.Primitives on 2025+
    (.NET 8), so it is read off DataGridColumn.SortDirection by reflection."""
    import clr
    from System import Enum
    prop = clr.GetClrType(DataGridTemplateColumn).GetProperty('SortDirection')
    enum_type = prop.PropertyType.GetGenericArguments()[0]
    return Enum.Parse(enum_type, 'Descending' if descending else 'Ascending')


def items(rows):
    out = List[object]()
    for r in rows:
        out.Add(r)
    return out


def list_item(text, note, tag, muted=False):
    item = ListBoxItem()
    panel = StackPanel()
    panel.Orientation = Orientation.Horizontal
    t = TextBlock()
    t.Text = text
    if muted:
        t.Style = selected_aware_style(ListBoxItem, DynamicResourceExtension('MutedBrush'))
    panel.Children.Add(t)
    if note:
        n = TextBlock()
        n.Text = u'   ' + note
        n.FontSize = 11
        n.Style = selected_aware_style(ListBoxItem, DynamicResourceExtension('MutedBrush'))
        panel.Children.Add(n)
    item.Content = panel
    item.Tag = tag
    return item


# ==========================================================================
# one-box search picker (type to narrow, drop-down underneath)
# ==========================================================================

class SearchPick(object):
    """A TextBox that shows the chosen item and, as you type, a drop-down of
    the entries narrowed to every word typed. Down / Up move, Enter or a click
    picks, Escape or leaving the box puts the current choice back.

    The list and its items are not focusable, so clicking one never takes
    focus from the box (focus leaving is what reverts it) - the pick is made
    from the click itself rather than from ListBox selection."""

    LIMIT = 400

    def __init__(self, box, popup, lst, on_pick):
        self.box = box
        self.popup = popup
        self.lst = lst
        self.on_pick = on_pick
        self.entries = []
        self.current = (u'', u'')
        self.shown = []
        self._quiet = False
        self._skip_focus = False
        box.TextChanged += self._on_text
        box.PreviewKeyDown += self._on_key
        box.GotKeyboardFocus += self._on_focus
        box.PreviewMouseLeftButtonUp += self._on_box_click
        box.LostKeyboardFocus += self._on_lost
        lst.PreviewMouseLeftButtonUp += self._on_list_click

    # ---- state ------------------------------------------------------------
    def set_entries(self, entries):
        """entries: [(id, name, count)]"""
        self.entries = list(entries)
        if self.popup.IsOpen:
            self._fill(self._typed())

    def set_current(self, cid, name):
        self.current = (to_text(cid), to_text(name))
        self._set_text(self.current[1])

    def _set_text(self, text):
        self._quiet = True
        try:
            self.box.Text = text
        finally:
            self._quiet = False

    def _typed(self):
        text = to_text(self.box.Text)
        return u'' if text == self.current[1] else text

    # ---- list -------------------------------------------------------------
    def _fill(self, text):
        self.lst.Items.Clear()
        self.shown = [e for e in self.entries
                      if store.matches_keywords(e[1] + u' ' + (e[3] if len(e) > 3 else u''), text)]
        for e in self.shown[:self.LIMIT]:
            cid, name, count = e[0], e[1], e[2]
            group = e[3] if len(e) > 3 else u''
            note = u'  \u00b7  '.join([x for x in (group, u'{0} elements'.format(count) if count else u'') if x])
            item = list_item(name, note, cid)
            item.Focusable = False
            self.lst.Items.Add(item)
        if not self.shown:
            item = list_item(u'Nothing matches "{0}"'.format(text), u'', None, muted=True)
            item.Focusable = False
            self.lst.Items.Add(item)
            return
        index = 0
        if not text:
            for i, e in enumerate(self.shown[:self.LIMIT]):
                if e[0] == self.current[0]:
                    index = i
        self.lst.SelectedIndex = index
        try:
            self.lst.ScrollIntoView(self.lst.Items[index])
        except Exception:
            pass

    def open(self, text=u''):
        self._fill(text)
        self.popup.IsOpen = True

    def close(self):
        self.popup.IsOpen = False

    # ---- events -----------------------------------------------------------
    def _on_text(self, sender, args):
        if self._quiet or not self.box.IsKeyboardFocused:
            return
        self.open(self._typed())

    def _on_focus(self, sender, args):
        if self._skip_focus:          # focus coming back after a pick's own prompt
            self._skip_focus = False
            return
        self.open(self._typed())
        try:
            self.box.SelectAll()
        except Exception:
            pass

    def _on_box_click(self, sender, args):
        if not self.popup.IsOpen and self.box.IsEnabled:
            self.open(self._typed())

    def _on_key(self, sender, args):
        k = args.Key
        if k in (Key.Down, Key.Up):
            if not self.popup.IsOpen:
                self.open(self._typed())
            n = len(self.shown[:self.LIMIT])
            if n:
                i = self.lst.SelectedIndex + (1 if k == Key.Down else -1)
                self.lst.SelectedIndex = max(0, min(n - 1, i))
                try:
                    self.lst.ScrollIntoView(self.lst.SelectedItem)
                except Exception:
                    pass
            args.Handled = True
        elif k == Key.Enter:
            item = self.lst.SelectedItem if self.popup.IsOpen else None
            if item is not None and item.Tag is not None:
                self.commit(item.Tag)
            args.Handled = True
        elif k == Key.Escape:
            self.revert()
            args.Handled = True

    def _on_list_click(self, sender, args):
        dep = args.OriginalSource
        while dep is not None and not isinstance(dep, ListBoxItem):
            try:
                dep = VisualTreeHelper.GetParent(dep)
            except Exception:
                dep = None
        if dep is not None and dep.Tag is not None:
            self.commit(dep.Tag)
            args.Handled = True

    def _on_lost(self, sender, args):
        self.revert()

    def revert(self):
        self.close()
        self._set_text(self.current[1])

    def commit(self, cid):
        entry = None
        for e in self.entries:
            if e[0] == cid:
                entry = e
        self.close()
        if entry is None:
            self.revert()
            return
        old = self.current
        self.set_current(entry[0], entry[1])
        if entry[0] != old[0]:
            self._skip_focus = True
            if self.on_pick(entry) is False:
                self.set_current(old[0], old[1])


# ==========================================================================
# window base: chrome + theme
# ==========================================================================

class ThemedWindow(object):
    XAML = None
    GRIPS = ('ThW', 'ThE', 'ThN', 'ThS', 'ThNW', 'ThNE', 'ThSW', 'ThSE')

    def __init__(self, state):
        self.state = state
        self.win = load_xaml(self.XAML)
        self.theme_dict = load_xaml('Theme.xaml')
        self.menu_dict = None
        self.win.Resources.MergedDictionaries.Add(self.theme_dict)
        self._full = None
        self._closing = False
        self.mode = resolve_theme(state.settings.get('theme', 'follow'))
        apply_palette(self.win.Resources, self.mode)
        self._wire_chrome()

    # ---- names ------------------------------------------------------------
    def n(self, name):
        el = self.win.FindName(name)
        if el is None:
            raise KeyError('XAML element not found: ' + name)
        return el

    # ---- chrome -----------------------------------------------------------
    def _wire_chrome(self):
        try:
            self.n('TxtVersion').Text = u'v' + __version__
        except Exception:
            pass
        try:
            icon = load_bitmap(os.path.join(HERE, 'icon.png'))
            if icon is not None:
                self.n('HeaderIcon').Source = icon
        except Exception:
            pass
        self.n('HeaderBar').MouseLeftButtonDown += self._on_header_down
        self.n('BtnClose').Click += self._on_close_click
        self.n('BtnFull').Click += self._on_full_click
        self.drawer = Drawer(self.win, self.n('HeaderBar'), self.n('BtnDrawer'), self.n('DrawerDown'),
                             self.n('DrawerUp'), before=self._leave_full)
        self.n('BtnTheme').Click += self._on_theme_click
        self.win.KeyDown += self._on_chrome_key
        self.win.Activated += self._on_activated
        for name in self.GRIPS:
            self.n(name).DragDelta += self._grip_handler(name[2:])
        self._show_theme_label()

    def _leave_full(self):
        if self._full is not None:
            self.toggle_full()

    def _on_header_down(self, sender, args):
        try:
            if args.ClickCount == 2:
                if self.drawer.collapsed:
                    self.drawer.toggle()      # double-click the floating bar pulls it back up
                else:
                    self.toggle_full()
                return
            runner = getattr(self.state, 'runner', None)
            if runner is not None and runner.busy:
                return                    # DragMove is a modal loop - never mid-job
            if self._full is not None:
                self._full = None
            self.win.DragMove()
        except Exception:
            pass

    def set_busy(self, on):
        """While a job runs the body and the other header controls go deaf,
        but the shrink button stays live - it only moves the window."""
        for el in self.drawer._body():
            try:
                el.IsHitTestVisible = not on
            except Exception:
                pass
        for name in ('BtnClose', 'BtnFull', 'BtnTheme'):
            try:
                self.n(name).IsHitTestVisible = not on
            except Exception:
                pass

    def _on_close_click(self, sender, args):
        self.close()

    def _on_full_click(self, sender, args):
        self.toggle_full()

    def _on_chrome_key(self, sender, args):
        if self.drawer.handle_key(args):
            args.Handled = True
            return
        if args.Key == Key.F11:
            self.toggle_full()
            args.Handled = True

    def _grip_handler(self, edge):
        def handler(sender, args):
            try:
                w = self.win
                self._full = None
                dx = args.HorizontalChange
                dy = args.VerticalChange
                if 'E' in edge:
                    w.Width = max(w.MinWidth, w.Width + dx)
                if 'S' in edge:
                    w.Height = max(w.MinHeight, w.Height + dy)
                if 'W' in edge:
                    nw = max(w.MinWidth, w.Width - dx)
                    w.Left = w.Left + (w.Width - nw)
                    w.Width = nw
                if 'N' in edge:
                    nh = max(w.MinHeight, w.Height - dy)
                    w.Top = w.Top + (w.Height - nh)
                    w.Height = nh
            except Exception:
                pass
        return handler

    def screen_area(self):
        """(left, top, right, bottom) of the screen the window is on, in WPF units."""
        return screen_area_of(self.win)

    def toggle_full(self):
        if getattr(self, 'drawer', None) is not None and (self.drawer.collapsed or self.drawer.busy):
            if self.drawer.collapsed:
                self.drawer.toggle()
            return
        w = self.win
        if self._full is not None:
            left, top, width, height = self._full
            self._full = None
            w.Left, w.Top, w.Width, w.Height = left, top, width, height
            return
        self._full = (w.Left, w.Top, w.Width, w.Height)
        try:
            from System.Windows.Forms import Screen
            area = Screen.FromHandle(WindowInteropHelper(w).Handle).WorkingArea
            sx, sy = 1.0, 1.0
            src = PresentationSource.FromVisual(w)
            if src is not None:
                m = src.CompositionTarget.TransformToDevice
                sx, sy = m.M11, m.M22
            w.Left = area.Left / sx
            w.Top = area.Top / sy
            w.Width = area.Width / sx
            w.Height = area.Height / sy
        except Exception:
            wa = SystemParameters.WorkArea
            w.Left, w.Top, w.Width, w.Height = wa.Left, wa.Top, wa.Width, wa.Height

    # ---- theme ------------------------------------------------------------
    def _on_theme_click(self, sender, args):
        self.state.cycle_theme()

    def _on_activated(self, sender, args):
        # following the canvas: pick up a change made in Revit while open
        if self.state.settings.get('theme') == 'follow':
            mode = resolve_theme('follow')
            if mode != self.mode:
                self.state.apply_theme_everywhere()

    def apply_theme(self):
        self.mode = resolve_theme(self.state.settings.get('theme', 'follow'))
        apply_palette(self.win.Resources, self.mode)
        self._show_theme_label()
        self.after_theme()

    def after_theme(self):
        pass

    def _show_theme_label(self):
        try:
            self.n('TxtTheme').Text = store.theme_label(self.state.settings.get('theme', 'follow'), self.mode)
        except Exception:
            pass

    # ---- menus ------------------------------------------------------------
    def menu(self):
        if self.menu_dict is None:
            self.menu_dict = load_xaml('Theme.xaml')
        m = ContextMenu()
        m.Resources.MergedDictionaries.Add(self.menu_dict)
        apply_palette(m.Resources, self.mode)
        try:
            import clr
            m.Style = self.menu_dict[clr.GetClrType(ContextMenu)]
        except Exception:
            pass
        return m

    @staticmethod
    def menu_add(menu, text, handler=None, enabled=True, brush_key=None, bold=False):
        item = MenuItem()
        label = TextBlock()
        label.Text = text
        if brush_key:
            label.SetResourceReference(TextBlock.ForegroundProperty, brush_key)
        if bold:
            label.FontWeight = FontWeights.SemiBold
        item.Header = label
        item.IsEnabled = enabled
        if handler is not None:
            item.Click += handler
        menu.Items.Add(item)
        return item

    # ---- close ------------------------------------------------------------
    def close(self):
        try:
            self.win.Close()
        except Exception:
            pass


# ==========================================================================
# themed prompt
# ==========================================================================

def prompt(owner, title, message, ok=u'OK', cancel=u'Cancel', danger=False,
           choices=None, selected=0, input_text=None, show_cancel=True, copy_text=None, alt=None):
    """Modal themed dialog. -> {'ok': bool, 'index': int|None, 'text': str|None}.
    choices: list of strings shown in a list to pick one from.
    input_text: show a text box pre-filled with this."""
    result = {'ok': False, 'alt': False, 'index': None, 'text': None}
    try:
        win = load_xaml('SMPrompt.xaml')
        win.Resources.MergedDictionaries.Add(load_xaml('Theme.xaml'))
        mode = owner.mode if owner is not None else resolve_theme('follow')
        apply_palette(win.Resources, mode)
        win.FindName('TxtTitle').Text = title
        win.FindName('TxtVersion').Text = u'v' + __version__
        win.FindName('TxtMessage').Text = message
        win.FindName('TxtOk').Text = ok
        win.FindName('TxtCancel').Text = cancel
        btn_ok = win.FindName('BtnOk')
        btn_cancel = win.FindName('BtnCancel')
        if danger:
            btn_ok.SetResourceReference(Button.StyleProperty, 'RedBtn')
        if not show_cancel:
            btn_cancel.Visibility = Visibility.Collapsed
        lst = win.FindName('LstChoices')
        box = win.FindName('TxtInput')
        if choices:
            lst.Visibility = Visibility.Visible
            for c in choices:
                item = ListBoxItem()
                t = TextBlock()
                t.Text = to_text(c)
                t.TextWrapping = TextWrapping.Wrap
                item.Content = t
                lst.Items.Add(item)
            if selected is not None and 0 <= selected < len(choices):
                lst.SelectedIndex = selected
        if input_text is not None:
            box.Visibility = Visibility.Visible
            box.Text = to_text(input_text)
        if copy_text is not None:
            # debug report: read-only, scrollable, monospaced, with a Copy button
            win.Width = 760
            box.Visibility = Visibility.Visible
            box.Text = to_text(copy_text)
            box.IsReadOnly = True
            box.AcceptsReturn = True
            box.Height = 360
            box.VerticalContentAlignment = VerticalAlignment.Top
            box.FontFamily = FontFamily('Consolas')
            box.FontSize = 11
            box.SetValue(ScrollViewer.VerticalScrollBarVisibilityProperty, ScrollBarVisibility.Auto)
            box.SetValue(ScrollViewer.HorizontalScrollBarVisibilityProperty, ScrollBarVisibility.Auto)
            copy_btn = win.FindName('BtnCopy')
            copy_btn.Visibility = Visibility.Visible

            def do_copy(s, a):
                try:
                    Clipboard.SetText(to_text(copy_text))
                    win.FindName('TxtCopy').Text = u'Copied - paste it to Claude'
                except Exception as ex:
                    win.FindName('TxtCopy').Text = u'Copy failed: ' + to_text(ex)
            copy_btn.Click += do_copy

        def finish(ok_pressed):
            result['ok'] = ok_pressed
            if ok_pressed and choices:
                result['index'] = lst.SelectedIndex if lst.SelectedIndex >= 0 else None
            if ok_pressed and input_text is not None:
                result['text'] = to_text(box.Text)
            win.Close()

        btn_ok.Click += lambda s, a: finish(True)
        if alt:
            win.FindName('TxtAlt').Text = alt
            btn_alt = win.FindName('BtnAlt')
            btn_alt.Visibility = Visibility.Visible

            def on_alt(s, a):
                result['alt'] = True
                finish(False)
            btn_alt.Click += on_alt
        btn_cancel.Click += lambda s, a: finish(False)

        def on_key(s, a):
            if win.Tag is not None and win.Tag.handle_key(a):
                a.Handled = True
                return
            if a.Key == Key.Escape:
                finish(False)
            elif a.Key == Key.Enter:
                finish(True)
        if copy_text is None:
            win.KeyDown += on_key
        else:
            def on_report_key(s, a):
                if win.Tag is not None and win.Tag.handle_key(a):
                    a.Handled = True
                elif a.Key == Key.Escape:
                    finish(False)
            win.KeyDown += on_report_key

        def drag(s, a):
            try:
                win.DragMove()
            except Exception:
                pass
        win.FindName('HeaderBar').MouseLeftButtonDown += drag
        owner_drawer = getattr(owner, 'drawer', None) if owner is not None else None
        drawer = Drawer(win, win.FindName('HeaderBar'), win.FindName('BtnDrawer'),
                        win.FindName('DrawerDown'), win.FindName('DrawerUp'), companion=owner_drawer)
        win.Tag = drawer                      # keep it alive with the dialog
        win.Closed += lambda s, a: drawer.release_companion()
        if owner_drawer is not None and owner_drawer.collapsed:
            # centred on a parked 50px bar it would open half off the screen
            win.WindowStartupLocation = getattr(WindowStartupLocation, 'CenterScreen')
        if owner is not None:
            try:
                win.Owner = owner.win
            except Exception:
                pass
        if input_text is not None:
            win.Loaded += lambda s, a: (box.Focus(), box.SelectAll())
        win.ShowDialog()
    except Exception:
        result['error'] = traceback.format_exc()
    return result


def info(owner, title, message, lines=None):
    return prompt(owner, title, message, ok=u'OK', choices=lines, selected=None, show_cancel=False)
