# -*- coding: utf-8 -*-
"""XAML loading, theming, window chrome, resize grips, full screen, prompts."""

import snte_clr  # noqa: F401  - must be first

import os

from System.IO import File, MemoryStream, StringReader
from System.Windows import Visibility, WindowState, SizeToContent
from System.Windows.Markup import XamlReader
from System.Windows.Media import SolidColorBrush, ColorConverter
from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption
from System.Windows.Interop import WindowInteropHelper
from System.Xml import XmlReader

import theme as theme_module

HERE = os.path.dirname(os.path.abspath(__file__))

_THEME_DICT = None


def path_of(filename):
    return os.path.join(HERE, filename)


def _read_text(filename):
    handle = open(path_of(filename), "r")
    try:
        return handle.read()
    finally:
        handle.close()


def theme_dictionary():
    """Theme.xaml, parsed once."""
    global _THEME_DICT
    if _THEME_DICT is None:
        text = _read_text("Theme.xaml")
        _THEME_DICT = XamlReader.Load(XmlReader.Create(StringReader(text)))
    return _THEME_DICT


def load_window(filename):
    """Parse a layout and merge Theme.xaml into it afterwards.

    The layouts may therefore only use DynamicResource - a StaticResource
    would be resolved while XamlReader parses, before the dictionary exists,
    and fail at load.
    """
    text = _read_text(filename)
    window = XamlReader.Load(XmlReader.Create(StringReader(text)))
    # deliberately not wrapped in try/except: a Theme.xaml that will not load
    # leaves every control on its Windows default, which looks like a broken
    # dark mode rather than a failure. It has to be loud.
    window.Resources.MergedDictionaries.Add(theme_dictionary())
    return window


def apply_theme(window, name):
    """Write the palette straight onto window.Resources, which sits in front
    of a merged dictionary in WPF's lookup order - so the palette can be
    swapped on an open window with no reload and no loss of state."""
    palette = theme_module.palette(name)
    converter = ColorConverter()
    for key in palette:
        try:
            colour = converter.ConvertFromString(palette[key])
            window.Resources[key] = SolidColorBrush(colour)
        except Exception:
            continue
    return name


def load_icon(image_element, filename):
    """From bytes through a MemoryStream - System.Uri moved assemblies in
    Revit 2025 and BitmapImage.UriSource is not safe across 2024 - 2027."""
    try:
        full = path_of(filename)
        if not os.path.exists(full):
            return False
        data = File.ReadAllBytes(full)
        stream = MemoryStream(data)
        bitmap = BitmapImage()
        bitmap.BeginInit()
        bitmap.CacheOption = BitmapCacheOption.OnLoad
        bitmap.StreamSource = stream
        bitmap.EndInit()
        try:
            bitmap.Freeze()
        except Exception:
            pass
        image_element.Source = bitmap
        return True
    except Exception:
        return False


def own_to_revit(window, uiapp):
    """An unowned modeless window slips behind Revit and reads as a crash."""
    try:
        helper = WindowInteropHelper(window)
        helper.Owner = uiapp.MainWindowHandle
        return True
    except Exception:
        try:
            from System.Diagnostics import Process
            helper = WindowInteropHelper(window)
            helper.Owner = Process.GetCurrentProcess().MainWindowHandle
            return True
        except Exception:
            return False


# ---------------------------------------------------------------------------
#  Dragging, resizing and full screen
# ---------------------------------------------------------------------------
def drag_window(window):
    try:
        window.DragMove()
    except Exception:
        pass


GRIP_NAMES = ["grip_l", "grip_r", "grip_t", "grip_b",
              "grip_tl", "grip_tr", "grip_bl", "grip_br"]


def hook_grips(window, on_resize_start=None):
    """Eight Thumb strips standing in for the resize frame WPF cannot give a
    borderless AllowsTransparency window."""

    def make(name):
        def handler(sender, args):
            if on_resize_start is not None:
                try:
                    on_resize_start()
                except Exception:
                    pass
            dx = args.HorizontalChange
            dy = args.VerticalChange
            left = window.Left
            top = window.Top
            width = window.Width
            height = window.Height
            min_w = window.MinWidth or 200
            min_h = window.MinHeight or 200

            if "l" in name.split("_")[1]:
                new_w = width - dx
                if new_w >= min_w:
                    window.Left = left + dx
                    window.Width = new_w
            if "r" in name.split("_")[1]:
                new_w = width + dx
                if new_w >= min_w:
                    window.Width = new_w
            if "t" in name.split("_")[1]:
                new_h = height - dy
                if new_h >= min_h:
                    window.Top = top + dy
                    window.Height = new_h
            if "b" in name.split("_")[1]:
                new_h = height + dy
                if new_h >= min_h:
                    window.Height = new_h
        return handler

    for name in GRIP_NAMES:
        grip = window.FindName(name)
        if grip is None:
            continue
        grip.DragDelta += make(name)


class FullScreen(object):
    """Full screen by bounds, not WindowState.Maximized - maximising a
    borderless AllowsTransparency window the normal way covers the task bar
    and lands on the wrong monitor."""

    def __init__(self, window):
        self.window = window
        self.on = False
        self._saved = None

    def toggle(self):
        if self.on:
            self.restore()
        else:
            self.enter()
        return self.on

    def enter(self):
        window = self.window
        if self.on:
            return
        self._saved = (window.Left, window.Top, window.Width, window.Height,
                       window.SizeToContent)
        try:
            from System.Windows.Forms import Screen
            from System.Drawing import Rectangle
            helper = WindowInteropHelper(window)
            screen = Screen.FromHandle(helper.Handle)
            area = screen.WorkingArea
            scale_x, scale_y = self._dpi()
            window.SizeToContent = SizeToContent.Manual
            window.Left = area.Left / scale_x
            window.Top = area.Top / scale_y
            window.Width = area.Width / scale_x
            window.Height = area.Height / scale_y
            self.on = True
        except Exception:
            try:
                window.WindowState = WindowState.Maximized
                self.on = True
            except Exception:
                pass

    def restore(self):
        if not self.on or self._saved is None:
            return
        window = self.window
        try:
            window.WindowState = WindowState.Normal
        except Exception:
            pass
        left, top, width, height, stc = self._saved
        try:
            window.Left = left
            window.Top = top
            window.Width = width
            window.Height = height
            window.SizeToContent = stc
        except Exception:
            pass
        self.on = False

    def _dpi(self):
        try:
            from System.Windows import PresentationSource
            source = PresentationSource.FromVisual(self.window)
            if source is not None:
                matrix = source.CompositionTarget.TransformToDevice
                return (matrix.M11 or 1.0), (matrix.M22 or 1.0)
        except Exception:
            pass
        return 1.0, 1.0


# ---------------------------------------------------------------------------
#  Themed message window
# ---------------------------------------------------------------------------
class MessageWindow(object):
    def __init__(self, title, body, theme_name="dark", owner=None,
                 confirm=False, yes_text="OK", no_text="Cancel"):
        self.result = False
        self.window = load_window("SnteMessage.xaml")
        apply_theme(self.window, theme_name)

        self.window.FindName("sub_txt").Text = title
        self.window.FindName("body_txt").Text = body

        yes_btn = self.window.FindName("yes_btn")
        no_btn = self.window.FindName("no_btn")
        yes_btn.Content = yes_text
        no_btn.Content = no_text
        if not confirm:
            no_btn.Visibility = Visibility.Collapsed

        yes_btn.Click += self._yes
        no_btn.Click += self._no

        close_btn = self.window.FindName("msg_close")
        if close_btn is not None:
            close_btn.Click += self._no

        header = self.window.FindName("msg_header")
        if header is not None:
            header.MouseLeftButtonDown += self._drag

        if owner is not None:
            try:
                self.window.Owner = owner
            except Exception:
                pass

    def _drag(self, sender, args):
        drag_window(self.window)

    def _yes(self, sender, args):
        self.result = True
        self.window.Close()

    def _no(self, sender, args):
        self.result = False
        self.window.Close()

    def show(self):
        self.window.ShowDialog()
        return self.result


def alert(title, body, theme_name="dark", owner=None):
    return MessageWindow(title, body, theme_name, owner).show()


def confirm(title, body, theme_name="dark", owner=None,
            yes_text="Yes", no_text="Cancel"):
    return MessageWindow(title, body, theme_name, owner, True,
                         yes_text, no_text).show()
