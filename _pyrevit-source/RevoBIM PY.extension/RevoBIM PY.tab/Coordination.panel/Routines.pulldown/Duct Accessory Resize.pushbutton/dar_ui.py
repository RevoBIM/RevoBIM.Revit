# -*- coding: utf-8 -*-
"""Duct Accessory Resize - XAML loading, theming, window chrome, the logo
and the easter egg. Nothing in here reads the model."""

import dar_clr  # noqa: F401 - assemblies first, always

import io
import os

from System.IO import MemoryStream, File
from System.Windows import (Thickness, HorizontalAlignment, VerticalAlignment,
                            SystemParameters, PresentationSource)
from System.Windows.Markup import XamlReader
from System.Windows.Media import SolidColorBrush, ColorConverter
from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption
from System.Windows.Controls.Primitives import Thumb
from System.Windows.Input import Cursors
from System.Windows.Interop import WindowInteropHelper

import dar_core as core

HERE = os.path.dirname(os.path.abspath(__file__))
THEME_FILE = u"Theme.xaml"
LAYOUT_FILE = u"DuctAccessoryResize.xaml"
ICON_FILE = u"icon.png"


# ============================================================
# loading
# ============================================================

def read_text(name):
    with io.open(os.path.join(HERE, name), "r", encoding="utf-8") as handle:
        return handle.read()


def load_window():
    """The layout is parsed first and Theme.xaml merged in after, which is
    why the layout may only use DynamicResource."""
    window = XamlReader.Parse(read_text(LAYOUT_FILE))
    theme = XamlReader.Parse(read_text(THEME_FILE))
    window.Resources.MergedDictionaries.Add(theme)
    return window


def apply_palette(window, name):
    """Brushes written straight onto window.Resources sit in front of the
    merged Theme.xaml, so the palette swaps on an open window."""
    palette = core.PALETTES.get(name) or core.PALETTES[u"dark"]
    for key, hex_value in palette.items():
        try:
            brush = SolidColorBrush(ColorConverter.ConvertFromString(hex_value))
            brush.Freeze()
            window.Resources[key + u"Brush"] = brush
        except Exception:
            pass


def load_icon(image):
    """From bytes, never from a Uri: System.Uri moved assembly in 2025."""
    try:
        data = File.ReadAllBytes(os.path.join(HERE, ICON_FILE))
        bitmap = BitmapImage()
        bitmap.BeginInit()
        bitmap.StreamSource = MemoryStream(data)
        bitmap.CacheOption = BitmapCacheOption.OnLoad
        bitmap.EndInit()
        bitmap.Freeze()
        image.Source = bitmap
        return True
    except Exception:
        return False


# ============================================================
# full screen by bounds
# ============================================================

def dpi_scale(window):
    try:
        source = PresentationSource.FromVisual(window)
        return float(source.CompositionTarget.TransformToDevice.M11) or 1.0
    except Exception:
        return 1.0


def work_area(window):
    """The working area of the screen the window is on, in WPF units -
    SystemParameters.WorkArea is only ever the primary monitor."""
    try:
        from System.Windows.Forms import Screen
        handle = WindowInteropHelper(window).Handle
        area = Screen.FromHandle(handle).WorkingArea
        scale = dpi_scale(window)
        return (area.X / scale, area.Y / scale,
                area.Width / scale, area.Height / scale)
    except Exception:
        area = SystemParameters.WorkArea
        return (area.X, area.Y, area.Width, area.Height)


class FullScreen(object):
    def __init__(self, window):
        self.window = window
        self.saved = None

    @property
    def active(self):
        return self.saved is not None

    def toggle(self):
        if self.saved is None:
            self.enter()
        else:
            self.leave()

    def enter(self):
        w = self.window
        self.saved = (w.Left, w.Top, w.Width, w.Height)
        left, top, width, height = work_area(w)
        w.Left, w.Top, w.Width, w.Height = left, top, width, height

    def leave(self):
        if self.saved is None:
            return
        w = self.window
        w.Left, w.Top, w.Width, w.Height = self.saved
        self.saved = None

    def forget(self):
        """Dragging by the header or an edge counts as leaving."""
        self.saved = None


# ============================================================
# resize grips - a borderless transparent window has no frame to hit
# ============================================================

GRIP = 5.0
GRIPS = (
    # name, h-align, v-align, left, top, right, bottom, cursor
    (u"L", "Left", "Stretch", 1, 0, 0, 0, "SizeWE"),
    (u"R", "Right", "Stretch", 0, 0, 1, 0, "SizeWE"),
    (u"T", "Stretch", "Top", 0, 1, 0, 0, "SizeNS"),
    (u"B", "Stretch", "Bottom", 0, 0, 0, 1, "SizeNS"),
    (u"TL", "Left", "Top", 1, 1, 0, 0, "SizeNWSE"),
    (u"TR", "Right", "Top", 0, 1, 1, 0, "SizeNESW"),
    (u"BL", "Left", "Bottom", 1, 0, 0, 1, "SizeNESW"),
    (u"BR", "Right", "Bottom", 0, 0, 1, 1, "SizeNWSE"),
)


def add_grips(window, layer, full_screen):
    for name, h_align, v_align, sl, st, sr, sb, cursor in GRIPS:
        thumb = Thumb()
        thumb.Opacity = 0.0
        thumb.Cursor = getattr(Cursors, cursor)
        thumb.HorizontalAlignment = getattr(HorizontalAlignment, h_align)
        thumb.VerticalAlignment = getattr(VerticalAlignment, v_align)
        if h_align != "Stretch":
            thumb.Width = GRIP * (2 if v_align != "Stretch" else 1)
        if v_align != "Stretch":
            thumb.Height = GRIP * (2 if h_align != "Stretch" else 1)
        thumb.Margin = Thickness(0)
        thumb.DragDelta += _make_drag(window, sl, st, sr, sb, full_screen)
        layer.Children.Add(thumb)


def _make_drag(window, sl, st, sr, sb, full_screen):
    def on_drag(sender, args):
        try:
            full_screen.forget()
            dx, dy = args.HorizontalChange, args.VerticalChange
            if sl:
                width = window.Width - dx
                if width >= window.MinWidth:
                    window.Left += dx
                    window.Width = width
            if sr:
                window.Width = max(window.MinWidth, window.Width + dx)
            if st:
                height = window.Height - dy
                if height >= window.MinHeight:
                    window.Top += dy
                    window.Height = height
            if sb:
                window.Height = max(window.MinHeight, window.Height + dy)
        except Exception:
            pass
    return on_drag


# ============================================================
# easter egg - three slow clicks on the RevoBIM logo
# ============================================================

def attach_egg(window, logo_host, get_palette, log=None):
    """The egg lives in the extension's shared lib\\revobim\\egg package and
    is not shipped with this tool. attach_to_window is the current call and
    finds the logo itself; attach is the older form; a local click counter
    calling launch is the last resort."""
    try:
        from revobim.egg import egg_hook
    except Exception:
        if log is not None:
            log.add(u"easter egg: revobim.egg not found on sys.path")
        return False

    attach_to_window = getattr(egg_hook, "attach_to_window", None)
    if attach_to_window is not None:
        try:
            attach_to_window(window, theme=get_palette, tool=core.TOOL_NAME)
            return True
        except TypeError:
            try:
                attach_to_window(window, theme=get_palette)
                return True
            except Exception:
                pass
        except Exception:
            pass

    attach = getattr(egg_hook, "attach", None)
    if attach is not None and logo_host is not None:
        try:
            attach(logo_host, host_window=window, theme=get_palette)
            return True
        except Exception:
            pass

    launch = getattr(egg_hook, "launch", None)
    if launch is None or logo_host is None:
        return False
    counter = core.SlowClicks()

    def on_down(sender, args):
        try:
            if counter.click(int(args.Timestamp)):
                launch(window, get_palette, None)
        except Exception:
            pass
    try:
        logo_host.PreviewMouseLeftButtonDown += on_down
        return True
    except Exception:
        return False
