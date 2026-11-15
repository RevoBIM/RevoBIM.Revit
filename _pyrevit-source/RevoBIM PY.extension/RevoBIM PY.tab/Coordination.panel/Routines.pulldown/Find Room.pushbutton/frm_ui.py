# -*- coding: utf-8 -*-
"""Find Room - WPF plumbing shared by the window: XAML loading, the palette,
Theme.xaml, the logo, owner, resize grips, full screen by bounds, the easter
egg and the log. Nothing here knows about rooms."""
import frm_clr  # noqa: F401 - assemblies first, always

import os
import datetime

from System.IO import File, MemoryStream
from System.Windows import Thickness, SystemParameters
from System.Windows.Markup import XamlReader
from System.Windows.Media import SolidColorBrush, ColorConverter, Geometry
from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption
from System.Windows.Interop import WindowInteropHelper

import frm_core as core

HERE = os.path.dirname(os.path.abspath(__file__))


# =============================================================================
# Log
# =============================================================================
class Log(object):
    """Ring buffer always; written to %APPDATA%\\RevoBIM\\find_room_debug.txt
    only while Debug is ticked."""

    def __init__(self, enabled=False):
        self.enabled = enabled
        self.lines = []

    def __call__(self, message):
        stamp = datetime.datetime.now().strftime("%H:%M:%S")
        line = u"{0}  {1}".format(stamp, core.to_text(message))
        self.lines.append(line)
        if len(self.lines) > 400:
            self.lines = self.lines[-300:]
        if not self.enabled:
            return
        try:
            folder = core.settings_dir()
            if not os.path.isdir(folder):
                os.makedirs(folder)
            path = core.debug_path()
            if os.path.exists(path) and os.path.getsize(path) > 1024 * 1024:
                os.remove(path)
            with open(path, "a") as handle:
                try:
                    handle.write((line + u"\n").encode("utf-8"))
                except TypeError:
                    handle.write(line + u"\n")
        except Exception:
            pass

    def text(self):
        return u"\n".join(self.lines)


def write_error(text):
    try:
        folder = core.settings_dir()
        if not os.path.isdir(folder):
            os.makedirs(folder)
        with open(core.error_path(), "w") as handle:
            try:
                handle.write(core.to_text(text).encode("utf-8"))
            except TypeError:
                handle.write(core.to_text(text))
    except Exception:
        pass


# =============================================================================
# XAML, theme, palette
# =============================================================================
def load_xaml(name):
    path = os.path.join(HERE, name)
    return XamlReader.Load(MemoryStream(File.ReadAllBytes(path)))


def brush(hex_text):
    b = SolidColorBrush(ColorConverter.ConvertFromString(hex_text))
    try:
        b.Freeze()
    except Exception:
        pass
    return b


def merge_theme(element):
    """Theme.xaml merged AFTER the layout has parsed - hence DynamicResource."""
    element.Resources.MergedDictionaries.Add(load_xaml("Theme.xaml"))


def apply_palette(element, theme):
    """Written straight onto element.Resources, which sits in front of the
    merged Theme.xaml, so the swap is live on an open window."""
    for key, value in core.palette_for(theme).items():
        element.Resources[key] = brush(value)


def load_image(path):
    """From bytes - System.Uri moved assemblies in Revit 2025."""
    try:
        img = BitmapImage()
        img.BeginInit()
        img.CacheOption = BitmapCacheOption.OnLoad
        img.StreamSource = MemoryStream(File.ReadAllBytes(path))
        img.EndInit()
        img.Freeze()
        return img
    except Exception:
        return None


def geometry(data):
    try:
        return Geometry.Parse(data)
    except Exception:
        return None


THEME_ICONS = {
    # Auto: half-filled circle; Dark: moon; Light: sun
    u"follow": u"F0 M7,0 A7,7 0 1 1 7,14 A7,7 0 1 1 7,0 Z "
               u"M7,1.6 A5.4,5.4 0 1 1 7,12.4 A5.4,5.4 0 1 1 7,1.6 Z "
               u"M7,1.6 L7,12.4 A5.4,5.4 0 0 1 7,1.6 Z",
    u"dark": u"M9,0 A7,7 0 1 0 14,9 A5.5,5.5 0 1 1 9,0 Z",
    u"light": u"M7,4 A3,3 0 1 1 7,10 A3,3 0 1 1 7,4 Z M6.3,0 H7.7 V2.4 H6.3 Z "
              u"M6.3,11.6 H7.7 V14 H6.3 Z M0,6.3 H2.4 V7.7 H0 Z M11.6,6.3 H14 V7.7 H11.6 Z",
}


def set_owner(window, handle):
    try:
        if handle:
            WindowInteropHelper(window).Owner = handle
            return True
    except Exception:
        pass
    return False


# =============================================================================
# Resize grips - a borderless AllowsTransparency window gets no hit testing
# on its frame, so it carries eight Thumbs of its own.
# =============================================================================
def attach_grips(window, find, on_moved=None):
    spec = {
        u"GripN": (0, 1, 0, 0), u"GripS": (0, 0, 0, 1),
        u"GripW": (1, 0, 0, 0), u"GripE": (0, 0, 1, 0),
        u"GripNW": (1, 1, 0, 0), u"GripNE": (0, 1, 1, 0),
        u"GripSW": (1, 0, 0, 1), u"GripSE": (0, 0, 1, 1),
    }
    for name, (left, top, right, bottom) in spec.items():
        thumb = find(name)
        if thumb is None:
            continue

        def make(left, top, right, bottom):
            def drag(sender, e):
                try:
                    if on_moved:
                        on_moved()
                    dx, dy = e.HorizontalChange, e.VerticalChange
                    if right:
                        window.Width = max(window.MinWidth, window.Width + dx)
                    if bottom:
                        window.Height = max(window.MinHeight, window.Height + dy)
                    if left:
                        w = max(window.MinWidth, window.Width - dx)
                        window.Left += window.Width - w
                        window.Width = w
                    if top:
                        h = max(window.MinHeight, window.Height - dy)
                        window.Top += window.Height - h
                        window.Height = h
                except Exception:
                    pass
            return drag
        thumb.DragDelta += make(left, top, right, bottom)


class FullScreen(object):
    """Full screen by bounds: the working area of the screen the window is on,
    divided by the DPI scale. Never WindowState.Maximized."""

    def __init__(self, window):
        self.window = window
        self.saved = None

    @property
    def on(self):
        return self.saved is not None

    def toggle(self):
        if self.on:
            self.leave()
        else:
            self.enter()

    def enter(self):
        w = self.window
        self.saved = (w.Left, w.Top, w.Width, w.Height)
        area = None
        try:
            import System.Windows.Forms as WF
            from System.Windows import PresentationSource
            handle = WindowInteropHelper(w).Handle
            scr = WF.Screen.FromHandle(handle).WorkingArea
            sx, sy = 1.0, 1.0
            src = PresentationSource.FromVisual(w)
            if src is not None:
                m = src.CompositionTarget.TransformToDevice
                sx, sy = m.M11, m.M22
            area = (scr.Left / sx, scr.Top / sy, scr.Width / sx, scr.Height / sy)
        except Exception:
            wa = SystemParameters.WorkArea
            area = (wa.Left, wa.Top, wa.Width, wa.Height)
        w.Left, w.Top, w.Width, w.Height = area

    def leave(self):
        if self.saved is None:
            return
        w = self.window
        w.Left, w.Top, w.Width, w.Height = self.saved
        self.saved = None


# =============================================================================
# Easter egg - three slow clicks on the logo only (250 ms floor, 2 s ceiling,
# timestamps de-duplicated), then egg_hook.launch(window, theme, game_key).
# =============================================================================
class EggCounter(object):
    def __init__(self, window, theme_getter):
        self.window = window
        self.theme_getter = theme_getter
        self.count = 0
        self.last = None

    def reset(self):
        self.count = 0
        self.last = None

    def click(self, timestamp):
        if self.last is not None and timestamp == self.last:
            return False
        gap = None if self.last is None else timestamp - self.last
        if gap is not None and (gap < 250 or gap > 2000):
            self.count = 0
        self.count += 1
        self.last = timestamp
        if self.count >= 3:
            self.reset()
            self.launch()
            return True
        return False

    def launch(self):
        try:
            from revobim.egg import egg_hook
            egg_hook.launch(self.window, self.theme_getter(), "pacman")
        except Exception:
            pass


def margin(left, top, right, bottom):
    return Thickness(left, top, right, bottom)
