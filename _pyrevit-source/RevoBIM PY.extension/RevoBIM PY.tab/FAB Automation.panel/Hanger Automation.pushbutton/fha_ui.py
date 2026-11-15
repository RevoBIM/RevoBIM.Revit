# -*- coding: utf-8 -*-
u"""XAML loading, palette, window chrome, icon and easter egg for the window.

WPF objects are .NET objects: IronPython will not let a script hang new
attributes on them (`win._full = ...` raises AttributeError).  Every bit of
Python-side state lives on plain Python objects - Chrome below, FhaWindow in
fha_window - never on the Window, a Thumb or any other control.
"""
import fha_clr  # noqa: F401  (must be first)
import os
import io
import sys
import fha_core as core
from System import AppDomain, Object
from System.IO import MemoryStream, File
from System.Windows import (SystemParameters, HorizontalAlignment, VerticalAlignment,
                            PresentationSource, FrameworkElement, Size)
from System.Windows import Window, Visibility, CornerRadius, SizeToContent, WindowStartupLocation, Thickness
from System.Windows.Input import Keyboard
from System.Windows.Markup import XamlReader
from System.Windows.Media import SolidColorBrush, ColorConverter
from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption
from System.Windows.Input import Cursors
from System.Windows.Controls.Primitives import Thumb
from System.Windows.Controls import Border
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Media import RotateTransform
from System.Windows.Media.Animation import DoubleAnimation, CubicEase, EasingMode
from System import TimeSpan
from System.Windows import Duration, UIElement

HERE = os.path.dirname(os.path.abspath(__file__))
PARK_KEY = u'RevoBIM.HangerAutomation.window.' + core.__version__


def read_text(name):
    with io.open(os.path.join(HERE, name), 'r', encoding='utf-8') as f:
        return f.read()


def load_xaml_window(name):
    u"""Parse a layout, then merge Theme.xaml (layouts only use DynamicResource)."""
    win = XamlReader.Parse(read_text(name))
    theme = XamlReader.Parse(read_text(u'Theme.xaml'))
    win.Resources.MergedDictionaries.Add(theme)
    return win


def load_window():
    return load_xaml_window(u'HangerAutomation.xaml')


def bitmap_from_bytes(data):
    u"""PNG bytes -> BitmapImage, from a stream (never a Uri - it moved assembly in 2025)."""
    bi = BitmapImage()
    bi.BeginInit()
    bi.StreamSource = MemoryStream(data)
    bi.CacheOption = BitmapCacheOption.OnLoad
    bi.EndInit()
    return bi


def set_style(el, key):
    u"""Swap a control's style by key; re-resolves when the palette changes."""
    try:
        el.SetResourceReference(FrameworkElement.StyleProperty, key)
    except Exception:
        pass


# ================================================================ theme
def canvas_is_dark():
    u"""Revit's canvas theme: True / False, None when it cannot be read.

    UIThemeManager only exists from 2024, so it is reached by getattr.  UITheme.Dark
    is 0, so the value is compared by name and never tested for truth.
    """
    try:
        import Autodesk.Revit.UI as RUI
        mgr = getattr(RUI, 'UIThemeManager', None)
        if mgr is None:
            return None
        for prop in ('CurrentCanvasTheme', 'CurrentTheme'):
            val = getattr(mgr, prop, None)
            if val is not None:
                return str(val).lower() == 'dark'
    except Exception:
        pass
    return None


def apply_palette(win, mode):
    u"""Write the resolved palette onto window.Resources; returns 'dark' / 'light'."""
    name = core.resolve_theme(mode, canvas_is_dark())
    conv = ColorConverter()
    for key, hexv in core.PALETTES[name].items():
        win.Resources[key + u'Brush'] = SolidColorBrush(conv.ConvertFromString(hexv))
    return name


# ============================================================ decoration
def set_icon(win, image_name=u'icon.png'):
    u"""Decorative only: never allowed to take the tool down."""
    try:
        data = File.ReadAllBytes(os.path.join(HERE, image_name))
        bi = BitmapImage()
        bi.BeginInit()
        bi.StreamSource = MemoryStream(data)
        bi.CacheOption = BitmapCacheOption.OnLoad
        bi.EndInit()
        win.FindName('Logo').Source = bi
        win.Icon = bi
    except Exception:
        pass


def _ensure_lib():
    u"""pyRevit only puts the extension's lib on sys.path if something does it."""
    d = HERE
    for _i in range(8):
        if d.lower().endswith(u'.extension'):
            lib = os.path.join(d, u'lib')
            if os.path.isdir(lib) and lib not in sys.path:
                sys.path.append(lib)
            return
        parent = os.path.dirname(d)
        if parent == d:
            return
        d = parent


def _argnames(fn):
    import inspect
    try:
        return list(inspect.getargspec(fn).args)
    except Exception:
        pass
    try:
        spec = inspect.getfullargspec(fn)
        return list(spec.args) + list(spec.kwonlyargs)
    except Exception:
        return []


def _kwargs(fn, offered):
    names = _argnames(fn)
    return dict((k, v) for k, v in offered.items() if k in names)


class EggClicks(object):
    u"""Local fallback: three slow clicks (0.25 - 2.0 s apart) on the logo."""
    def __init__(self, launch):
        self.launch = launch
        self.count = 0
        self.last = None

    def on_up(self, sender, e):
        try:
            now = e.Timestamp
            gap = None if self.last is None else (now - self.last) / 1000.0
            self.last = now
            if gap is not None and 0.25 <= gap <= 2.0:
                self.count += 1
            else:
                self.count = 1
            if self.count >= 3:
                self.count = 0
                self.launch()
        except Exception:
            pass


def attach_egg(win, logo, theme=None, tool=u'Hanger Automation'):
    u"""PacMan on a few slow clicks of the corner logo - and nowhere else.

    The shared package's attach is attach(logo, host_window=...): the element
    goes first and the window only as host_window.  1.0.1 passed the window
    first, which armed the whole window, so a few clicks anywhere started the
    game.  Arguments are matched to the real signature by name.
    Returns the route used, for the debug log.
    """
    try:
        _ensure_lib()
        from revobim.egg import egg_hook
    except Exception:
        return u'not installed'
    if logo is None:
        return u'no logo'
    offered = {'host_window': win, 'theme': theme, 'tool': tool}
    attach = getattr(egg_hook, 'attach', None)
    if attach is not None:
        try:
            attach(logo, **_kwargs(attach, offered))
            return u'attach(logo)'
        except Exception:
            pass
    attach_to_window = getattr(egg_hook, 'attach_to_window', None)
    if attach_to_window is not None:
        try:
            attach_to_window(win, **_kwargs(attach_to_window, offered))
            return u'attach_to_window'
        except Exception:
            pass
    launch = getattr(egg_hook, 'launch', None)
    if launch is not None:
        try:
            clicks = EggClicks(lambda: launch(**_kwargs(launch, offered)))
            logo.MouseLeftButtonUp += clicks.on_up
            _EGG_KEEP.append(clicks)
            return u'local clicks -> launch'
        except Exception:
            pass
    return u'no entry point'


_EGG_KEEP = []


def own_window(win, uiapp):
    u"""Own the window to Revit so a modeless window cannot slip behind it."""
    try:
        WindowInteropHelper(win).Owner = uiapp.MainWindowHandle
    except Exception:
        pass


# =========================================================== live window
def parked():
    u"""The open window from an earlier click (any engine), or None."""
    try:
        w = AppDomain.CurrentDomain.GetData(PARK_KEY)
        if w is not None and w.IsVisible:
            return w
    except Exception:
        pass
    return None


def park(win):
    try:
        AppDomain.CurrentDomain.SetData(PARK_KEY, win)
    except Exception:
        pass


# ========================================================== collapsible
SLIDE_MS = 260
MAX_SCREEN = 0.97   # never taller than this share of the screen's working area


def _eased(frm, to, ms):
    a = DoubleAnimation()
    a.From = frm
    a.To = to
    a.Duration = Duration(TimeSpan.FromMilliseconds(ms))
    ease = CubicEase()
    ease.EasingMode = EasingMode.EaseInOut
    a.EasingFunction = ease
    return a


class Collapser(object):
    u"""Tool cards that fold away to their header (icon + name).

    Clicking a header slides its body open or shut: the body's Height runs
    from 0 to the content's measured height (and back) on a 260 ms ease-in-out
    curve while it fades, and the chevron turns.  When an opening finishes,
    the Height animation is cleared and Height set back to Auto, so the card
    can still grow and shrink with its content.  All state is on this Python
    object; each chevron gets its own RotateTransform made here (never a
    named transform in XAML).
    """
    def __init__(self, win, keys, on_change=None, on_resize=None, prefix=u'Fam'):
        self.win = win
        self.prefix = prefix   # HdrFamPlace / BodyFamPlace / ChvFamPlace (Flr on the floor tab)
        self.keys = list(keys)
        self.open = dict((k, True) for k in self.keys)
        self.turn = {}
        self.on_change = on_change
        self.on_resize = on_resize
        for k in self.keys:
            rt = RotateTransform(0.0)
            self.turn[k] = rt
            try:
                self.c('Chv' + self.prefix + k).RenderTransform = rt
            except Exception:
                pass
            hdr = self.c('Hdr' + self.prefix + k)
            hdr.MouseLeftButtonUp += self._clicker(k)
            hdr.MouseEnter += self._hover(k, True)
            hdr.MouseLeave += self._hover(k, False)

    def c(self, name):
        return self.win.FindName(name)

    def _clicker(self, key):
        def click(sender, e):
            self.toggle(key)
        return click

    def _hover(self, key, on):
        def hover(sender, e):
            try:
                hdr = self.c('Hdr' + self.prefix + key)
                if on:
                    hdr.SetResourceReference(Border.BackgroundProperty, 'HoverBgBrush')
                else:
                    hdr.Background = None
            except Exception:
                pass
        return hover

    # ---- state
    def state_text(self):
        return u','.join(k.lower() for k in self.keys if self.open[k])

    def load(self, text):
        want = set(w.strip().lower() for w in (text or u'').split(u',') if w.strip())
        for k in self.keys:
            self.set(k, k.lower() in want, animate=False)

    def all_open(self):
        return all(self.open[k] for k in self.keys)

    # ---- folding
    def toggle(self, key):
        u"""A header click.  Opening one tool folds whichever others are open
        (one tool at a time); Expand all still opens every one."""
        opening = not self.open[key]
        if opening:
            for k in self.keys:
                if k != key and self.open[k]:
                    self.set(k, False, animate=True)
        self.set(key, opening, animate=True)

    def set_all(self, opened):
        for k in self.keys:
            if self.open[k] != opened:
                self.set(k, opened, animate=True)

    def set(self, key, opened, animate=True):
        self.open[key] = opened
        body = self.c('Body' + self.prefix + key)
        rt = self.turn.get(key)
        angle = 0.0 if opened else -90.0
        if not animate:
            try:
                body.BeginAnimation(FrameworkElement.HeightProperty, None)
                body.BeginAnimation(UIElement.OpacityProperty, None)
                body.Height = float('nan') if opened else 0.0
                body.Opacity = 1.0 if opened else 0.0
                if rt is not None:
                    rt.BeginAnimation(RotateTransform.AngleProperty, None)
                    rt.Angle = angle
            except Exception:
                pass
            self._changed()
            return
        try:
            start = float(body.ActualHeight)
            if opened:
                width = float(self.c('Hdr' + self.prefix + key).ActualWidth) or float(body.ActualWidth)
                content = body.Child
                content.Measure(Size(max(width, 50.0), float('inf')))
                end = float(content.DesiredSize.Height)
                fade = _eased(float(body.Opacity), 1.0, SLIDE_MS)
            else:
                end = 0.0
                fade = _eased(float(body.Opacity), 0.0, SLIDE_MS * 0.8)
            slide = _eased(start, end, SLIDE_MS)
            slide.Completed += self._finisher(key, opened)
            if self.on_resize is not None:
                try:
                    self.on_resize(end - start)   # the window follows, on the same curve
                except Exception:
                    pass
            body.BeginAnimation(FrameworkElement.HeightProperty, slide)
            body.BeginAnimation(UIElement.OpacityProperty, fade)
            if rt is not None:
                rt.BeginAnimation(RotateTransform.AngleProperty, _eased(float(rt.Angle), angle, SLIDE_MS))
        except Exception:
            self.set(key, opened, animate=False)
            return
        self._changed()

    def _finisher(self, key, opened):
        def done(sender, e):
            if self.open.get(key) != opened:
                return   # clicked again mid-slide: the newer animation owns it
            try:
                body = self.c('Body' + self.prefix + key)
                body.BeginAnimation(FrameworkElement.HeightProperty, None)
                body.Height = float('nan') if opened else 0.0
                body.BeginAnimation(UIElement.OpacityProperty, None)
                body.Opacity = 1.0 if opened else 0.0
            except Exception:
                pass
        return done

    def _changed(self):
        if self.on_change is not None:
            try:
                self.on_change()
            except Exception:
                pass


def animate_height(win, height, done=None):
    u"""Slide a window to a new height on the fold curve, then hold it there."""
    a = _eased(float(win.ActualHeight), float(height), SLIDE_MS)

    def finish(sender, e):
        try:
            win.BeginAnimation(FrameworkElement.HeightProperty, None)
            win.Height = float(height)
        except Exception:
            pass
        if done is not None:
            done()
    a.Completed += finish
    win.BeginAnimation(FrameworkElement.HeightProperty, a)


# ================================================================ drawer
DRAWER_MS = 320
BAR_GAP = 8.0   # px between a parked bar and the bottom of the working area
SHRINK_TIP = u'Shrink to the taskbar - see Revit (Ctrl+Shift+H)'
EXPAND_TIP = u'Open the window again (Ctrl+Shift+H, Enter or Esc)'


def thickness(l, t, r, b):
    return Thickness(l, t, r, b)


def header_siblings(header):
    u"""Everything laid out beside the title bar in its parent grid (the body)."""
    out = []
    try:
        for ch in header.Parent.Children:
            if not Object.ReferenceEquals(ch, header):
                out.append(ch)
    except Exception:
        pass
    return out


class Drawer(object):
    u"""Shrink a window to its title bar, slid down to the bottom of its screen
    like a drawer closing, so Revit can be seen - and open it again.  One per
    window (the main window and every dialog), per the RevoBIM theme reference.

    shrink(): MinHeight and SizeToContent are relaxed, the body is pinned at
    its height (so it is clipped, not re-laid-out, as the window closes over
    it), the grips park, then Top and Height slide together (CubicEase,
    DRAWER_MS) to fha_core.shrunk_top.  On landing the body collapses and the
    bar gets four round corners.  expand(): the reverse, to
    fha_core.expand_top - back where it was, or up from where the bar was
    dragged.  Both animations are released when they land (BeginAnimation(p,
    None) in its own try) and the final numbers written straight on; if an
    animation cannot start, the same finish runs at once.

    owner: the Drawer of the window a modal dialog belongs to - shrinking the
    dialog parks the owner too (a slot below it), and the owner comes back
    when the dialog opens again or closes.
    body(): the elements to collapse while parked (default: the header's
    siblings).  on_change(shrunk): swap the button's glyphs.
    """
    def __init__(self, win, chrome, header, button=None, shrink_icon=None, expand_icon=None,
                 body=None, show_body=None, on_change=None, owner=None, grips=None):
        self.win, self.chrome, self.header = win, chrome, header
        self.button, self.shrink_icon, self.expand_icon = button, shrink_icon, expand_icon
        self.body = body or (lambda: header_siblings(header))
        self.show_body = show_body
        self.on_change = on_change
        self.owner = owner
        self.grips = grips
        self.shrunk = False
        self.moving = False
        self.saved = None          # (Top, Height, MinHeight, SizeToContent)
        self.bar_top = None        # where the bar landed
        self.hidden = []           # what shrink collapsed (and expand shows again)
        self.parked_owner = False
        self.pending_finish = None
        self._target = None
        self.slot = 0

    # ---- helpers
    def toggle(self):
        if self.moving:
            return
        if self.shrunk:
            self.expand()
        else:
            self.shrink()

    def bar_height(self):
        try:
            h = float(self.header.ActualHeight)
            return (h if h > 0 else 56.0) + 12.0 + 2.0   # the 6 px window margin each side and the 1 px border
        except Exception:
            return 70.0

    def _work_area(self):
        try:
            return self.chrome.work_area()
        except Exception:
            wa = SystemParameters.WorkArea
            return wa.Left, wa.Top, wa.Width, wa.Height

    def _glyphs(self, shrunk):
        try:
            if self.shrink_icon is not None:
                self.shrink_icon.Visibility = Visibility.Collapsed if shrunk else Visibility.Visible
            if self.expand_icon is not None:
                self.expand_icon.Visibility = Visibility.Visible if shrunk else Visibility.Collapsed
            if self.button is not None:
                self.button.ToolTip = EXPAND_TIP if shrunk else SHRINK_TIP
        except Exception:
            pass
        if self.on_change is not None:
            try:
                self.on_change(shrunk)
            except Exception:
                pass

    def _pin(self, height):
        u"""Hold the body at a fixed height for the slide (clipped, not squashed)."""
        try:
            root = self.win.Content
            root.Height = float(height)
            root.VerticalAlignment = VerticalAlignment.Top
        except Exception:
            pass

    def _unpin(self):
        try:
            root = self.win.Content
            root.Height = float('nan')
            root.VerticalAlignment = VerticalAlignment.Stretch
        except Exception:
            pass

    def _slide(self, top, height, done):
        win = self.win
        self.moving = True
        self._target = (top, height)
        state = {'done': False}

        def finish(sender=None, e=None):
            if state['done']:
                return
            state['done'] = True
            try:
                win.BeginAnimation(Window.TopProperty, None)
                win.BeginAnimation(FrameworkElement.HeightProperty, None)
            except Exception:
                pass
            try:
                win.Top = float(top)
                win.Height = float(height)
            except Exception:
                pass
            self.moving = False
            done()
        self.pending_finish = finish   # the bench runs it in place of WPF's clock
        try:
            a_h = _eased(float(win.ActualHeight), float(height), DRAWER_MS)
            a_t = _eased(float(win.Top), float(top), DRAWER_MS)
            a_h.Completed += finish
            win.BeginAnimation(Window.TopProperty, a_t)
            win.BeginAnimation(FrameworkElement.HeightProperty, a_h)
        except Exception:
            finish()   # no animation: land at once

    # ---- shrink
    def shrink(self, slot=0):
        if self.shrunk or self.moving:
            return
        win = self.win
        try:
            if self.chrome is not None and self.chrome.full:
                self.chrome.toggle_full()
        except Exception:
            pass
        if self.owner is not None and not self.owner.shrunk and not self.owner.moving:
            self.owner.shrink(0)          # a modal dialog takes its owner down, parked beneath it
            self.parked_owner = True
            slot = 1
        self.slot = slot
        try:
            self.saved = (float(win.Top), float(win.ActualHeight), float(win.MinHeight), win.SizeToContent)
        except Exception:
            self.saved = (float(win.Top), float(win.ActualHeight), 0.0, None)
        bar = self.bar_height()
        _l, wa_top, _w, wa_h = self._work_area()
        self.bar_top = core.shrunk_top(wa_top, wa_h, bar, slot, BAR_GAP)
        try:
            win.SizeToContent = getattr(SizeToContent, 'Manual')
        except Exception:
            pass
        win.MinHeight = 0.0
        try:
            self._pin(float(win.Content.ActualHeight))
        except Exception:
            pass
        if self.grips is not None:
            try:
                self.grips.Visibility = Visibility.Collapsed
            except Exception:
                pass
        self.shrunk = True
        self._glyphs(True)
        self._slide(self.bar_top, bar, self.shrink_done)

    def shrink_done(self):
        self.hidden = []
        for el in self.body():
            try:
                if str(el.Visibility).endswith('Visible'):
                    el.Visibility = Visibility.Collapsed
                    self.hidden.append(el)
            except Exception:
                pass
        self._unpin()
        try:
            self.header.CornerRadius = CornerRadius(6.0)
        except Exception:
            pass

    # ---- expand
    def expand(self):
        if not self.shrunk or self.moving:
            return
        win = self.win
        top0, h0, min0, stc = self.saved or (float(win.Top), 600.0, 0.0, None)
        _l, wa_top, _w, wa_h = self._work_area()
        top = core.expand_top(top0, self.bar_top, float(win.Top), float(win.ActualHeight), h0, wa_top, wa_h)
        try:
            self.header.CornerRadius = CornerRadius(6.0, 6.0, 0.0, 0.0)
        except Exception:
            pass
        if self.show_body is not None:
            self.show_body()
        else:
            for el in self.hidden:
                try:
                    el.Visibility = Visibility.Visible
                except Exception:
                    pass
        self.hidden = []
        self._pin(max(0.0, h0 - 12.0))
        self.shrunk = False
        self._glyphs(False)
        if self.owner is not None and self.parked_owner and self.owner.shrunk:
            self.owner.expand()       # bring the owner back with it (it is not activated)
        self.parked_owner = False
        self._slide(top, h0, lambda: self.expand_done(min0, stc))

    def expand_done(self, min_height, size_to_content=None):
        self._unpin()
        try:
            self.win.MinHeight = float(min_height)
        except Exception:
            pass
        if size_to_content is not None:
            try:
                self.win.SizeToContent = size_to_content
            except Exception:
                pass
        if self.grips is not None:
            try:
                self.grips.Visibility = Visibility.Visible
            except Exception:
                pass

    def closing(self):
        u"""A dialog is closing: an owner it parked comes back."""
        if self.owner is not None and self.parked_owner and self.owner.shrunk:
            self.owner.expand()
        self.parked_owner = False

    # ---- keys
    def key(self, e):
        u"""Ctrl+Shift+H toggles; while parked Escape, Enter and F11 open it again.
        True if the key was used."""
        try:
            k = str(e.Key)
            mods = str(Keyboard.Modifiers)
        except Exception:
            return False
        if k == 'H' and 'Control' in mods and 'Shift' in mods:
            self.toggle()
            return True
        if self.shrunk and k in ('Escape', 'Return', 'Enter', 'F11'):
            self.expand()
            return True
        return False


def owner_parked(owner):
    try:
        return owner.drawer is not None and owner.drawer.shrunk
    except Exception:
        return False


def place_dialog(dlg_win, owner):
    u"""Own a dialog to the tool window - centred on the screen instead when the
    window is parked (centred on a 50 px bar it would be half off the screen)."""
    try:
        dlg_win.Owner = owner.win
    except Exception:
        pass
    if owner_parked(owner):
        try:
            dlg_win.WindowStartupLocation = getattr(WindowStartupLocation, 'CenterScreen')
        except Exception:
            pass


def dialog_drawer(dlg, owner, header, button, shrink_icon, expand_icon):
    u"""The drawer for a modal dialog: wired to its shrink button, its keys and
    its closing, parking its owner beneath it."""
    d = Drawer(dlg.win, Chrome(dlg.win), header, button, shrink_icon, expand_icon,
               owner=getattr(owner, 'drawer', None))
    button.Click += lambda s, e: d.toggle()

    def keys(sender, e):
        if d.key(e):
            e.Handled = True
    dlg.win.PreviewKeyDown += keys
    dlg.win.Closed += lambda s, e: d.closing()
    return d


# ================================================================ chrome
class Chrome(object):
    u"""Resize grips, dragging and full screen for a borderless window.

    A borderless AllowsTransparency window cannot be resized by WPF, so it
    carries eight Thumb strips.  Full screen is by bounds (the working area of
    the screen the window is on), never WindowState.Maximized.
    """
    GRIP = 5.0

    def __init__(self, win):
        self.win = win
        self.full = False
        self.saved = None

    # ---- grips
    def add_grips(self, layer):
        L, R, S = HorizontalAlignment.Left, HorizontalAlignment.Right, HorizontalAlignment.Stretch
        T, B, V = VerticalAlignment.Top, VerticalAlignment.Bottom, VerticalAlignment.Stretch
        specs = [
            (L, V, Cursors.SizeWE, -1, 0), (R, V, Cursors.SizeWE, 1, 0),
            (S, T, Cursors.SizeNS, 0, -1), (S, B, Cursors.SizeNS, 0, 1),
            (L, T, Cursors.SizeNWSE, -1, -1), (R, T, Cursors.SizeNESW, 1, -1),
            (L, B, Cursors.SizeNESW, -1, 1), (R, B, Cursors.SizeNWSE, 1, 1),
        ]
        for h, v, cur, sx, sy in specs:
            t = Thumb()
            t.Cursor = cur
            t.HorizontalAlignment = h
            t.VerticalAlignment = v
            t.Opacity = 0.0
            corner = h != S and v != V
            t.Width = self.GRIP * 2 if corner else (self.GRIP if h != S else float('nan'))
            t.Height = self.GRIP * 2 if corner else (self.GRIP if v != V else float('nan'))
            t.DragDelta += self._resizer(sx, sy)
            layer.Children.Add(t)

    def _resizer(self, sx, sy):
        def on_drag(sender, e):
            try:
                win = self.win
                self.full = False
                dx, dy = e.HorizontalChange, e.VerticalChange
                if sx:
                    w = win.Width + sx * dx
                    if w >= win.MinWidth:
                        if sx < 0:
                            win.Left = win.Left + dx
                        win.Width = w
                if sy:
                    h = win.Height + sy * dy
                    if h >= win.MinHeight:
                        if sy < 0:
                            win.Top = win.Top + dy
                        win.Height = h
            except Exception:
                pass
        return on_drag

    # ---- dragging by the header
    def header_down(self, e, logo=None):
        try:
            if logo is not None and Object.ReferenceEquals(e.OriginalSource, logo):
                return  # the logo belongs to the easter egg: never drag or full screen
            if e.ClickCount == 2:
                self.toggle_full()
                return
            if self.full:
                self._leave_full_under_mouse(e)
            self.win.DragMove()
        except Exception:
            pass

    # ---- full screen
    def _dpi(self):
        try:
            m = PresentationSource.FromVisual(self.win).CompositionTarget.TransformToDevice
            return m.M11, m.M22
        except Exception:
            return 1.0, 1.0

    def work_area(self):
        u"""(left, top, width, height) of the working area of the window's screen, in WPF units."""
        win = self.win
        sx, sy = self._dpi()
        try:
            from System.Windows.Forms import Screen
            from System.Drawing import Point
            cx = int((win.Left + win.ActualWidth / 2.0) * sx)
            cy = int((win.Top + 20.0) * sy)
            wa = Screen.FromPoint(Point(cx, cy)).WorkingArea
            return wa.X / sx, wa.Y / sy, wa.Width / sx, wa.Height / sy
        except Exception:
            wa = SystemParameters.WorkArea
            return wa.Left, wa.Top, wa.Width, wa.Height

    def fit_to(self, scroller, grow_only=False):
        u"""Size the window so the tab in `scroller` shows every tool without
        scrolling - up to the height of the screen, where it scrolls instead."""
        if self.full or scroller is None:
            return
        try:
            win = self.win
            if float(win.ActualHeight) <= 0:
                return   # not on screen yet: ContentRendered fits it
            win.UpdateLayout()
            content = scroller.Content
            content.Measure(Size(max(float(scroller.ActualWidth), 100.0), float('inf')))
            want = float(content.DesiredSize.Height)
            have = float(scroller.ViewportHeight) or float(scroller.ActualHeight)
            if want <= 0 or abs(want - have) < 1.0 or (grow_only and want <= have):
                return
            _l, wa_top, _w, wa_h = self.work_area()
            h, top = core.fit_height(float(win.ActualHeight or win.Height), have, want,
                                     float(win.MinHeight), float(win.Top), float(wa_top), float(wa_h) * MAX_SCREEN)
            win.Height = h
            win.Top = top
        except Exception:
            pass

    def toggle_full(self):
        try:
            if self.full:
                self.win.Left, self.win.Top, self.win.Width, self.win.Height = self.saved
                self.full = False
                return
            win = self.win
            self.saved = (win.Left, win.Top, win.Width, win.Height)
            sx, sy = self._dpi()
            try:
                from System.Windows.Forms import Screen
                from System.Drawing import Point
                cx = int((win.Left + win.ActualWidth / 2.0) * sx)
                cy = int((win.Top + 20.0) * sy)
                wa = Screen.FromPoint(Point(cx, cy)).WorkingArea
                win.Left, win.Top = wa.X / sx, wa.Y / sy
                win.Width, win.Height = wa.Width / sx, wa.Height / sy
            except Exception:
                wa = SystemParameters.WorkArea
                win.Left, win.Top, win.Width, win.Height = wa.Left, wa.Top, wa.Width, wa.Height
            self.full = True
        except Exception:
            pass

    def _leave_full_under_mouse(self, e):
        win = self.win
        try:
            pos = e.GetPosition(win)
            frac = pos.X / max(win.ActualWidth, 1.0)
            w, h = self.saved[2], self.saved[3]
            win.Width, win.Height = w, h
            win.Left = win.Left + pos.X - frac * w
        except Exception:
            pass
        self.full = False


def fill_workset_combo(combo, names, value):
    u"""Fill a tab's workset combo (fha_core.WS_OPTIONS + the model's worksets)
    and select the saved choice.  Returns the values in item order."""
    labels, index, values = core.workset_items(names, value)
    try:
        combo.Items.Clear()
    except Exception:
        pass
    for lab in labels:
        combo.Items.Add(lab)
    combo.SelectedIndex = index
    if not names:
        combo.ToolTip = u'This model is not workshared (or has no user worksets): nothing to set.'
    return values
