# -*- coding: utf-8 -*-
"""Number Sequencer - WPF plumbing shared by the windows.

XAML loading, the theme dictionary and palette, Revit canvas detection,
icon loading from bytes, borderless chrome (drag, full screen, resize grips)
and the easter egg on the RevoBIM logo.
"""

import nsq_clr  # noqa: F401  (must stay the first import)

import os
import time
import traceback

from System.IO import File, MemoryStream
from System import TimeSpan, EventHandler, Action
from System.Windows import (PresentationSource, Visibility, Thickness, LogicalTreeHelper, DependencyObject,
                            VerticalAlignment, SystemParameters, Duration, Size, Point, FrameworkElement,
                            GridLength, GridUnitType, Window, WindowStyle, Int32Rect,
                            CornerRadius)
from System.Windows.Controls import (StackPanel, TextBlock, Viewbox, Control, ContentControl, Orientation,
                                     Canvas, Image, Border)
from System.Windows.Data import Binding, RelativeSource, RelativeSourceMode
from System.Windows.Shapes import Path, Shape
from System.Windows.Markup import XamlReader
from System.Windows.Media import (SolidColorBrush, Color, ColorConverter, Geometry, PenLineCap, PenLineJoin,
                                  RotateTransform, MatrixTransform, Matrix, CompositionTarget, PixelFormats,
                                  Brushes, Stretch)
from System.Windows.Media.Animation import DoubleAnimation, CubicEase, EasingMode
from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption, RenderTargetBitmap, CroppedBitmap
from System.Windows.Threading import DispatcherPriority
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Input import Key
from System.Windows.Forms import Screen

import nsq_core as core

HERE = os.path.dirname(os.path.abspath(__file__))


def here(name):
    return os.path.join(HERE, name)


# ============================================================
# Loading
# ============================================================

def load_xaml(name):
    return XamlReader.Parse(File.ReadAllText(here(name)))


def merge_theme(win):
    win.Resources.MergedDictionaries.Add(load_xaml(u"Theme.xaml"))


def brush(hex_text, alpha=None):
    c = ColorConverter.ConvertFromString(hex_text)
    if alpha is not None:
        c = Color.FromArgb(int(alpha), c.R, c.G, c.B)
    b = SolidColorBrush(c)
    try:
        b.Freeze()
    except Exception:
        pass
    return b


def apply_palette(win, mode):
    """Written straight onto window.Resources, which sits in front of the
    merged Theme.xaml, so an open window re-themes with no reload."""
    for key, value in core.palette_for(mode).items():
        win.Resources[key] = brush(value)


def load_icon(name=u"icon.png"):
    try:
        path = here(name)
        if not os.path.isfile(path):
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


def fit_to_screen(win, margin=40):
    """Never open bigger than the screen's work area (a laptop is narrower
    than the window's preferred width)."""
    try:
        area = SystemParameters.WorkArea
        win.Width = max(min(win.Width, area.Width - margin), min(win.MinWidth, area.Width - margin))
        win.Height = max(min(win.Height, area.Height - margin), min(win.MinHeight, area.Height - margin))
    except Exception:
        pass


def own_to_revit(win, uiapp):
    try:
        WindowInteropHelper(win).Owner = uiapp.MainWindowHandle
        return True
    except Exception:
        return False


# ============================================================
# Revit's canvas theme
# ============================================================

def canvas_is_dark(uiapp):
    """True / False, or None when nothing could be read.
    UITheme.Dark is 0 - test 'is not None', never truthiness."""
    mgr = None
    try:
        import Autodesk.Revit.UI as RUI
        mgr = getattr(RUI, u"UIThemeManager", None)
    except Exception:
        mgr = None
    if mgr is not None:
        try:
            t = mgr.CurrentCanvasTheme
            if t is not None:
                return u"{0}".format(t) == u"Dark"
        except Exception:
            pass
    try:
        c = uiapp.Application.BackgroundColor
        dark = core.luminance_is_dark(c.Red, c.Green, c.Blue)
        if dark is not None:
            return dark
    except Exception:
        pass
    if mgr is not None:
        try:
            t = mgr.CurrentTheme
            if t is not None:
                return u"{0}".format(t) == u"Dark"
        except Exception:
            pass
    return None


# ============================================================
# Chrome: drag, full screen by bounds, eight resize grips
# ============================================================

GRIPS = {u"GripL": u"l", u"GripR": u"r", u"GripT": u"t", u"GripB": u"b",
         u"GripTL": u"tl", u"GripTR": u"tr", u"GripBL": u"bl", u"GripBR": u"br"}


class Chrome(object):
    """Drag by the header, full screen by bounds, eight grips. Also: a
    double-click on the top or bottom edge stretches the window to the
    monitor's full height (again: back); the shrink button slides the window
    down to the bottom of the screen as just its header bar, and its green up
    arrow brings it back. on_close replaces the plain close (an animation)."""

    def __init__(self, win, header, full_btn, close_btn, logo=None, min_btn=None, on_close=None):
        self.win = win
        self.logo = logo
        self.header = header
        self.min_btn = min_btn
        self.on_close = on_close
        self.full = False
        self.saved = None
        self.tall = None        # (Top, Height) before a double-click on an edge
        self.shrunk = False
        self.before = None      # (Top, Height, MinHeight) before shrinking
        self.moving = False
        self.hidden = []
        self.corner = None
        header.MouseLeftButtonDown += self._on_header
        full_btn.Click += self._on_full
        close_btn.Click += self._on_close
        win.PreviewKeyDown += self._on_key
        for name, sides in GRIPS.items():
            g = win.FindName(name)
            if g is not None:
                g.DragDelta += self._grip(sides)
        for name in (u"GripT", u"GripB"):
            g = win.FindName(name)
            if g is not None:
                g.PreviewMouseLeftButtonDown += self._on_edge_down
        if min_btn is not None:
            min_btn.Click += self._on_min
            self._paint_min()

    # ---------------------------------------------------- full height
    def _on_edge_down(self, sender, e):
        try:
            if e.ClickCount != 2 or self.shrunk:
                return
            e.Handled = True
            self.toggle_tall()
        except Exception:
            pass

    def toggle_tall(self):
        w = self.win
        area = work_area(w)
        if area is None:
            return
        top, bottom = area[1], area[3]
        if self.tall is not None and abs(w.Top - top) < 1.5 and abs(w.Height - (bottom - top)) < 1.5:
            w.Top, w.Height = self.tall
            self.tall = None
            return
        self.tall = (w.Top, w.Height)
        w.Top = top
        w.Height = bottom - top

    # ---------------------------------------------------- shrink to a bar
    def _on_min(self, sender, e):
        try:
            if self.shrunk:
                self.expand()
            else:
                self.shrink()
        except Exception:
            self.moving = False

    def _paint_min(self):
        btn = self.min_btn
        if btn is None:
            return
        p = Path()
        p.StrokeThickness = 1.8
        p.StrokeStartLineCap = getattr(PenLineCap, u"Round")
        p.StrokeEndLineCap = getattr(PenLineCap, u"Round")
        p.StrokeLineJoin = getattr(PenLineJoin, u"Round")
        if self.shrunk:
            p.Data = Geometry.Parse(u"M6,12 L6,1.5 M1.5,6 L6,1.5 L10.5,6")
            p.SetResourceReference(Shape.StrokeProperty, u"Green")
            btn.ToolTip = u"Bring the window back"
        else:
            p.Data = Geometry.Parse(u"M6,0 L6,7.5 M2.5,4.5 L6,8 L9.5,4.5 M0.5,11.5 L11.5,11.5")
            p.SetResourceReference(Shape.StrokeProperty, u"Muted")
            btn.ToolTip = u"Shrink to a bar at the bottom of the screen, so Revit can be seen"
        btn.Content = p

    def _parts(self):
        """Everything in the window's frame but the header bar."""
        out = []
        try:
            for child in self.header.Parent.Children:
                if child is not self.header:
                    out.append(child)
        except Exception:
            pass
        return out

    def shrink(self):
        if self.shrunk or self.moving:
            return
        w = self.win
        if self.full:
            self.leave_full()
        area = work_area(w)
        bar = self.header.ActualHeight + 2.0
        to = (area[3] if area is not None else w.Top + w.Height) - bar - 6.0
        start = w.Top
        self.before = (w.Top, w.Height, w.MinHeight)
        self.moving = True

        def step(e):
            w.Top = start + (to - start) * e

        def landed():
            # only the header bar is left, floating at the bottom
            self.hidden = [el for el in self._parts() if u"{0}".format(el.Visibility) == u"Visible"]
            for el in self.hidden:
                show(el, False)
            try:
                self.corner = self.header.CornerRadius
                self.header.CornerRadius = CornerRadius(6)
            except Exception:
                self.corner = None
            w.MinHeight = 0
            w.Height = bar
            w.Top = to
            self.shrunk = True
            self.moving = False
            self._paint_min()

        Tween(SHRINK_MS, step, landed)

    def expand(self):
        if not self.shrunk or self.moving:
            return
        w = self.win
        top, height, min_h = self.before
        for el in self.hidden:
            show(el, True)
        self.hidden = []
        if self.corner is not None:
            try:
                self.header.CornerRadius = self.corner
            except Exception:
                pass
        w.Height = height
        start = w.Top
        self.moving = True

        def step(e):
            w.Top = start + (top - start) * e

        def landed():
            w.Top = top
            w.MinHeight = min_h
            self.shrunk = False
            self.moving = False
            self._paint_min()

        Tween(SHRINK_MS, step, landed)

    def _on_header(self, sender, e):
        try:
            src = e.OriginalSource
            if self.logo is not None and src is self.logo:
                return
            if e.ClickCount == 2:
                if self.shrunk:
                    self.expand()
                else:
                    self.toggle_full()
                return
            if self.full:
                self.leave_full()
            self.win.DragMove()
        except Exception:
            pass

    def _on_full(self, sender, e):
        self.toggle_full()

    def _on_close(self, sender, e):
        try:
            if self.on_close is not None:
                self.on_close()
            else:
                self.win.Close()
        except Exception:
            try:
                self.win.Close()
            except Exception:
                pass

    def _on_key(self, sender, e):
        try:
            if e.Key == getattr(Key, u"F11"):
                self.toggle_full()
                e.Handled = True
            elif e.Key == getattr(Key, u"Escape") and self.full:
                self.leave_full()
                e.Handled = True
        except Exception:
            pass

    def toggle_full(self):
        if self.shrunk:
            self.expand()
            return
        if self.full:
            self.leave_full()
        else:
            self.enter_full()

    def enter_full(self):
        try:
            w = self.win
            self.saved = (w.Left, w.Top, w.Width, w.Height)
            area = Screen.FromHandle(WindowInteropHelper(w).Handle).WorkingArea
            sx = 1.0
            sy = 1.0
            src = PresentationSource.FromVisual(w)
            if src is not None:
                m = src.CompositionTarget.TransformToDevice
                sx = m.M11 or 1.0
                sy = m.M22 or 1.0
            w.Left = area.Left / sx
            w.Top = area.Top / sy
            w.Width = area.Width / sx
            w.Height = area.Height / sy
            self.full = True
        except Exception:
            self.full = False

    def leave_full(self):
        if not self.full:
            return
        self.full = False
        try:
            if self.saved:
                w = self.win
                w.Left, w.Top, w.Width, w.Height = self.saved
        except Exception:
            pass

    def _grip(self, sides):
        def handler(sender, e):
            try:
                if self.shrunk:
                    return
                self.full = False
                w = self.win
                dx = e.HorizontalChange
                dy = e.VerticalChange
                if u"l" in sides:
                    nw = max(w.MinWidth, w.Width - dx)
                    w.Left = w.Left + (w.Width - nw)
                    w.Width = nw
                if u"r" in sides:
                    w.Width = max(w.MinWidth, w.Width + dx)
                if u"t" in sides:
                    nh = max(w.MinHeight, w.Height - dy)
                    w.Top = w.Top + (w.Height - nh)
                    w.Height = nh
                if u"b" in sides:
                    w.Height = max(w.MinHeight, w.Height + dy)
            except Exception:
                pass
        return handler


# ============================================================
# Easter egg - three slow clicks on the RevoBIM logo
# ============================================================

def wire_egg(win, logo, theme_getter, log):
    egg_hook = None
    try:
        from revobim.egg import egg_hook as _eh
        egg_hook = _eh
    except Exception:
        egg_hook = None
    if egg_hook is not None:
        for fn_name in (u"attach_to_window", u"attach"):
            fn = getattr(egg_hook, fn_name, None)
            if fn is None:
                continue
            try:
                fn(win)
                log.add(u"egg: egg_hook.{0}".format(fn_name))
                return fn_name
            except Exception:
                log.add(u"egg: {0} failed".format(fn_name))
    if logo is None:
        return None
    counter = core.SlowClicks()

    def on_click(sender, e):
        try:
            e.Handled = True
            if not counter.click(e.Timestamp / 1000.0):
                return
            if egg_hook is None:
                return
            launch = getattr(egg_hook, u"launch", None)
            if launch is None:
                return
            for args in ((win, theme_getter(), None), (win, theme_getter()), (win,)):
                try:
                    launch(*args)
                    return
                except TypeError:
                    continue
        except Exception:
            log.add(u"egg launch failed: " + traceback.format_exc())

    logo.MouseLeftButtonUp += on_click
    log.add(u"egg: local slow-click counter")
    return u"local"


def show(elem, visible):
    try:
        elem.Visibility = getattr(Visibility, u"Visible") if visible else getattr(Visibility, u"Collapsed")
    except Exception:
        pass


# ============================================================
# Icons - stroked paths on a 16 x 16 grid, drawn in the button's own
# foreground so hover, disabled and the light theme all follow
# ============================================================

ICONS = {
    u"seq": u"M2,3 L3,3 M6,3 L14,3 M2,8 L3,8 M6,8 L14,8 M2,13 L3,13 M6,13 L14,13",
    u"selector": u"M2,2 L14,2 L14,14 L2,14 Z M2,6 L14,6 M2,10 L14,10 M6,2 L6,14",
    u"duct": u"M1,5 L15,5 L15,11 L1,11 Z M5,5 L5,11 M11,5 L11,11",
    u"pipe": u"M1,6 L15,6 M1,10 L15,10 M4,4.5 L4,11.5 M12,4.5 L12,11.5",
    u"add": u"M8,3 L8,13 M3,8 L13,8",
    u"pick": u"M3,2 L3,13 L6,10 L8,14 L10,13 L8,9 L12,9 Z",
    u"up": u"M3,10 L8,5 L13,10",
    u"down": u"M3,6 L8,11 L13,6",
    u"top": u"M3,3 L13,3 M3,12 L8,7 L13,12",
    u"bottom": u"M3,13 L13,13 M3,4 L8,9 L13,4",
    u"remove": u"M4,4 L12,12 M12,4 L4,12",
    u"clear": u"M3,4 L13,4 M6,4 L6,2 L10,2 L10,4 M4,4 L5,14 L11,14 L12,4",
    u"start": u"M4,14 L4,2 L12,4.5 L4,7",
    u"auto": u"M8,1 L8,5 M8,11 L8,15 M1,8 L5,8 M11,8 L15,8 M3,3 L5.5,5.5 M10.5,10.5 L13,13",
    u"show": u"M1,8 Q8,1 15,8 Q8,15 1,8 Z M6,8 A2,2 0 1 0 10,8 A2,2 0 1 0 6,8",
    u"refresh": u"M13,8 A5,5 0 1 1 11.5,4.5 M11.5,1.5 L11.5,4.5 L8.5,4.5",
    u"isolate": u"M2,5 L2,2 L5,2 M11,2 L14,2 L14,5 M14,11 L14,14 L11,14 M5,14 L2,14 L2,11 M6,6 L10,6 L10,10 L6,10 Z",
    u"unisolate": u"M2,5 L2,2 L5,2 M11,2 L14,2 L14,5 M14,11 L14,14 L11,14 M5,14 L2,14 L2,11 M6,6 L10,10 M10,6 L6,10",
    u"colour": u"M8,2 Q13,8 13,10 A5,5 0 0 1 3,10 Q3,8 8,2 Z",
    u"uncolour": u"M8,2 Q13,8 13,10 A5,5 0 0 1 3,10 Q3,8 8,2 Z M2,14 L14,2",
    u"order": u"M4,2 L4,14 M1,11 L4,14 L7,11 M10,3 L15,3 M10,7 L14,7 M10,11 L13,11",
    u"tick": u"M2,2 L14,2 L14,14 L2,14 Z M4.5,8 L7,10.5 L11.5,5.5",
    u"untick": u"M2,2 L14,2 L14,14 L2,14 Z",
    u"hide": u"M1,8 Q8,1 15,8 Q8,15 1,8 Z M6,8 A2,2 0 1 0 10,8 A2,2 0 1 0 6,8 M2,14 L14,2",
    u"restore": u"M2,7 L5,4 M2,7 L5,10 M2,7 L10,7 Q14,7 14,10.5 Q14,14 10,14 L6,14",
    u"expand": u"M4,3 L8,7 L12,3 M4,9 L8,13 L12,9",
    u"collapse": u"M4,7 L8,3 L12,7 M4,13 L8,9 L12,13",
    u"copy": u"M5,5 L14,5 L14,14 L5,14 Z M2,11 L2,2 L11,2",
    u"run": u"M4,2 L13,8 L4,14 Z",
    u"apply": u"M2,8 L6,12 L14,4",
    u"filter": u"M2,3 L14,3 L9.5,8.5 L9.5,13.5 L6.5,12 L6.5,8.5 Z",
    u"cube": u"M8,1.5 L14,5 L14,11 L8,14.5 L2,11 L2,5 Z M2,5 L8,8.5 L14,5 M8,8.5 L8,14.5",
    u"group": u"M1.5,2.5 L7,2.5 L7,7 L1.5,7 Z M9,9 L14.5,9 L14.5,13.5 L9,13.5 Z M7,4.75 L11.75,4.75 L11.75,9",
    u"ungroup": u"M1.5,2.5 L7,2.5 L7,7 L1.5,7 Z M9,9 L14.5,9 L14.5,13.5 L9,13.5 Z M10,2.5 L14,6.5 M14,2.5 L10,6.5",
    u"regroup": u"M1.5,2.5 L7,2.5 L7,7 L1.5,7 Z M1.5,9 L7,9 L7,13.5 L1.5,13.5 Z M11.5,2.5 L11.5,13 M9,10.5 L11.5,13 L14,10.5",
    u"tag": u"M2,2 L8,2 L14.5,8.5 L8.5,14.5 L2,8 Z M5.25,5.25 L5.3,5.3",
    u"sheet": u"M3,1.5 L10,1.5 L13,4.5 L13,14.5 L3,14.5 Z M10,1.5 L10,4.5 L13,4.5 M5.5,8 L10.5,8 M5.5,11 L10.5,11",
}


def icon(key, size=14):
    """A Viewbox holding the 16 x 16 path, stroked in the nearest control's
    Foreground."""
    data = ICONS.get(key)
    if data is None:
        return None
    p = Path()
    p.Data = Geometry.Parse(data)
    p.Width = 16
    p.Height = 16
    p.StrokeThickness = 1.6
    p.StrokeStartLineCap = getattr(PenLineCap, u"Round")
    p.StrokeEndLineCap = getattr(PenLineCap, u"Round")
    p.StrokeLineJoin = getattr(PenLineJoin, u"Round")
    b = Binding(u"Foreground")
    b.RelativeSource = RelativeSource(getattr(RelativeSourceMode, u"FindAncestor"), Control, 1)
    p.SetBinding(Shape.StrokeProperty, b)
    vb = Viewbox()
    vb.Width = size
    vb.Height = size
    vb.Child = p
    return vb


def step_badge(step):
    """A small red square with a white sub-step number (2.1, 2.2 ...)."""
    b = Border()
    b.SetResourceReference(FrameworkElement.StyleProperty, u"SubStepBadge")
    tb = TextBlock()
    tb.Text = step
    tb.SetResourceReference(FrameworkElement.StyleProperty, u"SubStepText")
    b.Child = tb
    return b


def set_button(btn, key, text, step=None):
    """Icon plus label as the button's content (a sub-step badge first when
    step is given). Set the label through this, never through Content, or the
    icon is lost."""
    sp = StackPanel()
    sp.Orientation = getattr(Orientation, u"Horizontal")
    if step:
        sp.Children.Add(step_badge(step))
    ic = icon(key)
    if ic is not None:
        sp.Children.Add(ic)
    if text:
        tb = TextBlock()
        tb.Text = text
        tb.VerticalAlignment = getattr(VerticalAlignment, u"Center")
        if ic is not None:
            tb.Margin = Thickness(6, 0, 0, 0)
        sp.Children.Add(tb)
    btn.Content = sp


def prompt_number(owner, mode, title, message, default, lo, hi):
    """A small themed modal prompt for a whole number from lo to hi.
    Enter confirms, Escape cancels. Returns the number, or None."""
    dlg = load_xaml(u"NumberSequencerPrompt.xaml")
    merge_theme(dlg)
    apply_palette(dlg, mode)
    try:
        iconize(dlg)
    except Exception:
        pass
    try:
        dlg.Owner = owner
    except Exception:
        pass
    f = dlg.FindName
    f(u"PVersion").Text = u"v" + core.__version__
    f(u"PTitle").Text = title
    f(u"PMessage").Text = message
    box = f(u"PValue")
    box.Text = u"" if default is None else u"{0}".format(default)
    result = [None]

    def ok(sender, e):
        try:
            v = core.parse_position(box.Text, lo, hi)
            if v is None:
                f(u"PError").Text = u"Type a whole number from {0} to {1}".format(lo, hi)
                return
            result[0] = v
            dlg.DialogResult = True
        except Exception:
            dlg.Close()

    def cancel(sender, e):
        try:
            dlg.DialogResult = False
        except Exception:
            dlg.Close()

    def keys(sender, e):
        if e.Key == getattr(Key, u"Enter"):
            ok(sender, e)
            e.Handled = True
        elif e.Key == getattr(Key, u"Escape"):
            cancel(sender, e)
            e.Handled = True

    def drag(sender, e):
        try:
            dlg.DragMove()
        except Exception:
            pass

    def loaded(sender, e):
        try:
            box.Focus()
            box.SelectAll()
        except Exception:
            pass

    f(u"POk").Click += ok
    f(u"PCancel").Click += cancel
    f(u"PHeader").MouseLeftButtonDown += drag
    dlg.PreviewKeyDown += keys
    dlg.Loaded += loaded
    dlg.ShowDialog()
    return result[0]


def ask_yes_no(owner, mode, title, message, yes=u"Yes", no=u"No"):
    """A small themed modal question. Enter = yes, Escape = no. True / False."""
    dlg = load_xaml(u"NumberSequencerPrompt.xaml")
    merge_theme(dlg)
    apply_palette(dlg, mode)
    try:
        dlg.Owner = owner
    except Exception:
        pass
    f = dlg.FindName
    dlg.Title = u"RevoBIM Number Sequencer - " + title
    f(u"PVersion").Text = u"v" + core.__version__
    f(u"PTitle").Text = title
    f(u"PMessage").Text = message
    show(f(u"PValue"), False)
    show(f(u"PError"), False)
    set_button(f(u"POk"), u"apply", yes)
    set_button(f(u"PCancel"), u"clear", no)
    result = [False]

    def ok(sender, e):
        result[0] = True
        try:
            dlg.DialogResult = True
        except Exception:
            dlg.Close()

    def cancel(sender, e):
        try:
            dlg.DialogResult = False
        except Exception:
            dlg.Close()

    def keys(sender, e):
        if e.Key == getattr(Key, u"Enter"):
            ok(sender, e)
            e.Handled = True
        elif e.Key == getattr(Key, u"Escape"):
            cancel(sender, e)
            e.Handled = True

    def drag(sender, e):
        try:
            dlg.DragMove()
        except Exception:
            pass

    f(u"POk").Click += ok
    f(u"PCancel").Click += cancel
    dlg.PreviewKeyDown += keys
    f(u"PHeader").MouseLeftButtonDown += drag
    dlg.ShowDialog()
    return result[0]


def set_icon_data(path, key):
    try:
        path.Data = Geometry.Parse(ICONS[key])
    except Exception:
        pass


def iconize(root):
    """Every button or tab whose Tag reads 'i:<icon>' gets that icon in
    front of its text. Cosmetic: never allowed to fail the window."""
    done = 0
    stack = [root]
    while stack:
        node = stack.pop()
        try:
            tag = getattr(node, u"Tag", None)
            if isinstance(node, ContentControl) and tag is not None:
                t = u"{0}".format(tag)
                if t.startswith(u"i:"):
                    content = node.Content
                    text = content if hasattr(content, u"startswith") else u""
                    set_button(node, t[2:], text)
                    done += 1
                    continue
        except Exception:
            pass
        try:
            for child in LogicalTreeHelper.GetChildren(node):
                if isinstance(child, DependencyObject):
                    stack.append(child)
        except Exception:
            pass
    return done


# ============================================================
# Animation: sections that fold away, the tag drawer
# ============================================================

ANIM_MS = 220
NAN = float(u"nan")


_RUNNING = {}   # (element, property) -> the animation now running on it


def animate(el, prop, to, frm=None, ms=ANIM_MS, done=None):
    """Ease el's property to a value; when it lands the value is set for real
    and the animation let go (a held animation would freeze the property).
    An animation replaced before it lands does nothing when it ends."""
    dur = Duration(TimeSpan.FromMilliseconds(ms))
    anim = DoubleAnimation(float(frm), float(to), dur) if frm is not None else DoubleAnimation(float(to), dur)
    ease = CubicEase()
    ease.EasingMode = getattr(EasingMode, u"EaseOut")
    anim.EasingFunction = ease
    key = (id(el), prop)
    _RUNNING[key] = anim

    def finished(sender, e):
        if _RUNNING.get(key) is not anim:
            return
        _RUNNING.pop(key, None)
        try:
            el.SetValue(prop, float(to))
            el.BeginAnimation(prop, None)
        except Exception:
            pass
        if done is not None:
            done()
    anim.Completed += finished
    el.BeginAnimation(prop, anim)


def chevron(button):
    """A chevron for a fold button; returns its RotateTransform (0 = open)."""
    p = Path()
    p.Data = Geometry.Parse(u"M0,0 L4,4 L8,0")
    p.StrokeThickness = 1.6
    p.StrokeStartLineCap = getattr(PenLineCap, u"Round")
    p.StrokeEndLineCap = getattr(PenLineCap, u"Round")
    b = Binding(u"Foreground")
    b.RelativeSource = RelativeSource(getattr(RelativeSourceMode, u"FindAncestor"), Control, 1)
    p.SetBinding(Shape.StrokeProperty, b)
    p.RenderTransformOrigin = Point(0.5, 0.5)
    turn = RotateTransform()
    p.RenderTransform = turn
    button.Content = p
    return turn


class Section(object):
    """A section whose chevron button slides its body shut (height to 0) and
    open again. row: a star-sized RowDefinition holding the section - Auto
    while shut, so the card shrinks to its heading. resize(delta) is told how
    much height the section gave up (negative) or takes back, so the window
    can shrink and grow with it."""

    def __init__(self, key, button, body, row=None, changed=None, shut=False, resize=None):
        self.key = key
        self.btn = button
        self.body = body
        self.row = row
        self.changed = changed
        self.resize = resize
        self.open = True
        self.last = 0.0
        self.token = 0
        self.turn = chevron(button)
        button.Click += self._on_click
        if shut:
            self.set(False, animated=False)

    def _on_click(self, sender, e):
        try:
            self.set(not self.open)
        except Exception:
            pass

    def _natural(self):
        """The height the body wants (a stretching section: the height it had)."""
        if self.row is not None and self.last > 0:
            return self.last
        w = self.body.ActualWidth
        if w <= 0:
            parent = getattr(self.body, u"Parent", None)
            w = getattr(parent, u"ActualWidth", 0) or 600
        self.body.Measure(Size(w, float(u"inf")))
        h = self.body.DesiredSize.Height
        return min(h, 400.0) if self.row is not None else h

    def _tell(self, h):
        """The body's height and its margins come and go together."""
        if self.resize is None or h == 0:
            return
        m = self.body.Margin
        extra = m.Top + m.Bottom
        try:
            self.resize(h + extra if h > 0 else h - extra)
        except Exception:
            pass

    def set(self, open_, animated=True):
        if open_ == self.open:
            return
        self.open = open_
        self.token += 1
        token = self.token
        body = self.body
        angle = 0.0 if open_ else -90.0
        if animated:
            animate(self.turn, RotateTransform.AngleProperty, angle)
        else:
            self.turn.Angle = angle
        if open_:
            if self.row is not None:
                self.row.Height = GridLength(1, getattr(GridUnitType, u"Star"))
            body.Height = NAN
            show(body, True)
            target = self._natural()
            self._tell(target)
            if animated and target > 0:
                body.Height = 0.0

                def opened():
                    if token == self.token:
                        body.Height = NAN
                animate(body, FrameworkElement.HeightProperty, target, frm=0.0, done=opened)
        else:
            h = body.ActualHeight
            if h > 0:
                self.last = h
            self._tell(-h)

            def shut():
                if token != self.token:
                    return
                show(body, False)
                body.Height = NAN
                if self.row is not None:
                    self.row.Height = GridLength.Auto
            if animated and h > 0:
                animate(body, FrameworkElement.HeightProperty, 0.0, frm=h, done=shut)
            else:
                shut()
        if self.changed is not None:
            try:
                self.changed(self.key, open_)
            except Exception:
                pass


# ============================================================
# Frame-driven animation: the genie open / close, shrink to a bar
# (the RevoBIM animation rules: frames from CompositionTarget.Rendering,
# time from the frame, never lay out per frame, smootherstep)
# ============================================================

SHRINK_MS = 300
GENIE_MS = 520
GENIE_STRIPS = 36
GENIE_LAG = 0.42      # how far the strips nearest the point lead the others
GENIE_NARROW = 1.7    # narrowing leads the fall
GENIE_FADE = 0.62     # fade from here to the end
GENIE_MIN_STRIP = 1.4


def smootherstep(p):
    p = max(0.0, min(1.0, p))
    return p * p * p * (p * (p * 6.0 - 15.0) + 10.0)


class Tween(object):
    """step(p) once per rendered frame for ms milliseconds (p eased with
    smootherstep unless ease=False), then done(). The clock starts on the
    first painted frame (first_frame runs there), is read from the frame's
    RenderingTime (not Python's clock, which ticks in ~15 ms steps), skips
    duplicate frames and clamps a slow frame to 34 ms so a Revit hiccup never
    jumps. One stored EventHandler, so -= removes exactly what += added."""

    def __init__(self, ms, step, done=None, ease=True, first_frame=None):
        self.ms = float(ms)
        self.step = step
        self.done = done
        self.ease = ease
        self.first_frame = first_frame
        self.start = None
        self.last = None
        self.elapsed = 0.0
        self.handler = EventHandler(self._frame)
        CompositionTarget.Rendering += self.handler

    def _now(self, e):
        try:
            return e.RenderingTime.TotalMilliseconds
        except Exception:
            return time.time() * 1000.0

    def _frame(self, sender, e):
        try:
            t = self._now(e)
            if self.last is not None and t == self.last:
                return
            if self.start is None:
                self.start = t
                self.last = t
                if self.first_frame is not None:
                    self.first_frame()
                self.step(0.0)
                return
            self.elapsed += min(34.0, max(0.0, t - self.last))
            self.last = t
            p = min(1.0, self.elapsed / self.ms)
            self.step(smootherstep(p) if self.ease else p)
            if p >= 1.0:
                self.finish()
        except Exception:
            self.finish()

    def finish(self):
        if self.handler is None:
            return
        try:
            CompositionTarget.Rendering -= self.handler
        except Exception:
            pass
        self.handler = None
        if self.done is not None:
            try:
                self.done()
            except Exception:
                pass


def dpi_scale(win):
    try:
        src = PresentationSource.FromVisual(win)
        if src is not None:
            m = src.CompositionTarget.TransformToDevice
            return (m.M11 or 1.0), (m.M22 or 1.0)
    except Exception:
        pass
    return 1.0, 1.0


def work_area(win):
    """(left, top, right, bottom) of the working area of the monitor the
    window is on, in WPF units."""
    try:
        a = Screen.FromHandle(WindowInteropHelper(win).Handle).WorkingArea
        sx, sy = dpi_scale(win)
        return a.Left / sx, a.Top / sy, a.Right / sx, a.Bottom / sy
    except Exception:
        try:
            a = SystemParameters.WorkArea
            return a.Left, a.Top, a.Right, a.Bottom
        except Exception:
            return None


def screen_point(el, win):
    """The centre of an element on the screen, in WPF units."""
    try:
        pt = el.PointToScreen(Point(el.ActualWidth / 2.0, el.ActualHeight / 2.0))
        sx, sy = dpi_scale(win)
        return pt.X / sx, pt.Y / sy
    except Exception:
        return None


def genie(win, target, done, reverse=False):
    """The Mac minimise: the window pours into a point (target, screen WPF
    units) - or, reverse=True, out of it. A snapshot of the window is cut
    into horizontal strips on a see-through overlay; each strip is placed by
    a render-only MatrixTransform per frame (no layout), the strips nearest
    the point move first, narrowing leads the fall, and it fades from 62%.
    The real window hides on the first painted frame (closing) or shows at
    the end (opening; the caller shows it at Opacity 0 first). Any failure
    just shows the window as it should end up and calls done()."""
    def plain():
        try:
            win.Opacity = 1.0
        except Exception:
            pass
        if done is not None:
            done()

    try:
        content = win.Content
        W = float(content.ActualWidth)
        H = float(content.ActualHeight)
        if target is None or W < 20 or H < 20:
            plain()
            return
        sx, sy = dpi_scale(win)
        pw = int(round(W * sx))
        ph = int(round(H * sy))
        rtb = RenderTargetBitmap(pw, ph, 96.0 * sx, 96.0 * sy, PixelFormats.Pbgra32)
        rtb.Render(content)
        wl = float(win.Left)
        wt = float(win.Top)
        tx, ty = target
        ol = min(wl, tx) - 4.0
        ot = min(wt, ty) - 4.0
        ov = Window()
        ov.WindowStyle = getattr(WindowStyle, u"None")
        ov.AllowsTransparency = True
        ov.Background = Brushes.Transparent
        ov.ShowInTaskbar = False
        ov.ShowActivated = False
        ov.Left = ol
        ov.Top = ot
        ov.Width = max(wl + W, tx) + 4.0 - ol
        ov.Height = max(wt + H, ty) + 4.0 - ot
        try:
            ov.Owner = win.Owner
        except Exception:
            pass
        canvas = Canvas()
        ov.Content = canvas
        n = GENIE_STRIPS
        strips = []
        for i in range(n):
            y0 = int(round(i * ph / float(n)))
            y1 = int(round((i + 1) * ph / float(n)))
            if y1 <= y0:
                continue
            img = Image()
            img.Source = CroppedBitmap(rtb, Int32Rect(0, y0, pw, y1 - y0))
            img.Stretch = getattr(Stretch, u"Fill")
            h0 = (y1 - y0) / sy
            img.Width = W
            img.Height = h0
            mt = MatrixTransform()
            img.RenderTransform = mt
            canvas.Children.Add(img)
            strips.append((mt, wl - ol, wt - ot + y0 / sy, h0, i))
        cx = tx - ol
        cy = ty - ot
        below = cy >= (wt - ot) + H / 2.0
        last = float(max(1, n - 1))

        def place(t):
            for mt, x0, y0, h0, i in strips:
                # the strips nearest the point go first
                q = (n - 1 - i) / last if below else i / last
                p = max(0.0, min(1.0, (t - GENIE_LAG * q) / (1.0 - GENIE_LAG)))
                e = smootherstep(p)
                en = smootherstep(min(1.0, p * GENIE_NARROW))
                w = W + (2.0 - W) * en
                centre = x0 + W / 2.0 + (cx - (x0 + W / 2.0)) * en
                h = max(GENIE_MIN_STRIP, h0 + (GENIE_MIN_STRIP - h0) * e)
                y = y0 + (cy - y0) * e
                mt.Matrix = Matrix(w / W, 0.0, 0.0, h / h0, centre - w / 2.0, y)
            canvas.Opacity = 1.0 if t < GENIE_FADE else max(0.0, 1.0 - (t - GENIE_FADE) / (1.0 - GENIE_FADE))

        def hide_real():
            if not reverse:
                win.Opacity = 0.0

        def finished():
            if reverse:
                win.Opacity = 1.0

                def remove():
                    try:
                        ov.Close()
                    except Exception:
                        pass
                # after the real window's frame is drawn
                win.Dispatcher.BeginInvoke(getattr(DispatcherPriority, u"Background"), Action(remove))
            else:
                try:
                    ov.Close()
                except Exception:
                    pass
            if done is not None:
                done()

        place(1.0 if reverse else 0.0)
        ov.Show()
        Tween(GENIE_MS, (lambda p: place(1.0 - p)) if reverse else place, finished,
              ease=False, first_frame=hide_real)
    except Exception:
        plain()
