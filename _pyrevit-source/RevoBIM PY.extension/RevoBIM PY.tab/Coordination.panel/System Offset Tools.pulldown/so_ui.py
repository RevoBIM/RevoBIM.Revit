# -*- coding: utf-8 -*-
# ==========================================================
# RevoBIM System Offset - XAML loading, theming and chrome
# ==========================================================

import so_clr  # noqa: F401  assembly references first

import os

from System.IO import StringReader, MemoryStream, File
from System.Xml import XmlReader
from System.Windows.Markup import XamlReader
from System.Windows import (
    ResourceDictionary, WindowState, SizeToContent, PresentationSource,
)
from System.Windows.Input import Cursors, Key
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption

import theme as theme_module
import so_core


HERE = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------
# Every closure goes through here.
#
# A WPF event handler that throws is swallowed silently, so
# a dead button looks like a broken tool with nothing to
# find. Anything the user pressed reports instead.
# ---------------------------------------------------------

def ui_safe(function):
    def wrapped(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Exception as error:
            try:
                report_error(u'{0} failed'.format(getattr(function, '__name__', 'handler')),
                             error)
            except Exception:
                pass
    try:
        wrapped.__name__ = function.__name__
    except Exception:
        pass
    return wrapped


def report_error(where, error):
    import traceback
    text = u'{0}\n\n{1}'.format(so_core.to_text(where), traceback.format_exc())
    try:
        folder = so_core.settings_dir()
        if not os.path.isdir(folder):
            os.makedirs(folder)
        handle = open(os.path.join(folder, 'system_offset_last_error.txt'), 'wb')
        try:
            handle.write(text.encode('utf-8'))
        finally:
            handle.close()
    except Exception:
        pass
    try:
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show(u'RevoBIM System Offset', text[:2000])
    except Exception:
        pass


# ---------------------------------------------------------
# Loading a layout
#
# XamlReader.Load over a StringReader, so there is no file
# path and no code behind. Theme.xaml is merged in AFTER the
# layout has parsed, which is exactly why a layout may only
# use DynamicResource.
# ---------------------------------------------------------

_TEXT_CACHE = {}
_ICON_CACHE = {}


def read_text(path):
    """Read a file once and keep it.

    The prompt is built again for every offset, and re-reading
    and re-parsing a 30KB Theme.xaml each time is work nobody
    asked for. The files do not change while Revit is running.
    """
    cached = _TEXT_CACHE.get(path)
    if cached is not None:
        return cached
    handle = open(path, 'rb')
    try:
        text = handle.read().decode('utf-8-sig', 'replace')
    finally:
        handle.close()
    _TEXT_CACHE[path] = text
    return text


def _parse(text):
    return XamlReader.Load(XmlReader.Create(StringReader(text)))


def load_window(name, theme_setting='revit'):
    """Parse a layout and merge the theme into it.

    Theme.xaml is merged AFTER the layout has been parsed,
    which is exactly why a layout may only use DynamicResource.

    The dictionary is parsed fresh per window rather than
    cached: a ResourceDictionary shared between two live
    windows is a source of very quiet bugs, and only the file
    read is worth saving.
    """
    window = _parse(read_text(os.path.join(HERE, name)))

    dictionary = _parse(read_text(os.path.join(HERE, 'Theme.xaml')))
    if isinstance(dictionary, ResourceDictionary):
        window.Resources.MergedDictionaries.Add(dictionary)

    applied = theme_module.resolve(theme_setting)
    theme_module.apply(window, applied)
    return window, applied


def set_version(window):
    try:
        block = window.FindName('VersionText')
        if block is not None:
            block.Text = u'v{0}'.format(so_core.__version__)
    except Exception:
        pass


def load_icon(window, filename='icon.png'):
    """The logo, from bytes and cached, never through System.Uri.

    Uri moved assemblies in Revit 2025 and importing it throws
    at module load. The bitmap is frozen, so one instance is
    safe to hand to every window the tool opens.

    Anything decorative is swallowed - cosmetics can never take
    the tool down.
    """
    try:
        image = window.FindName('LogoImage')
        if image is None:
            return None

        bitmap = _ICON_CACHE.get(filename)
        if bitmap is None:
            path = os.path.join(HERE, filename)
            if not os.path.isfile(path):
                return None
            bitmap = BitmapImage()
            bitmap.BeginInit()
            bitmap.StreamSource = MemoryStream(File.ReadAllBytes(path))
            bitmap.CacheOption = BitmapCacheOption.OnLoad
            bitmap.EndInit()
            try:
                bitmap.Freeze()
            except Exception:
                pass
            _ICON_CACHE[filename] = bitmap

        image.Source = bitmap
        return image
    except Exception:
        return None


# ---------------------------------------------------------
# The easter egg
#
# Three slow clicks on the RevoBIM logo. The whole public
# surface is these three lines; everything else lives in
# lib\revobim\egg\. Arming it here is one of its anchors, so
# a hand wired tool brings the feature back on its own even
# if a delivery has clobbered startup.py.
# ---------------------------------------------------------

def attach_egg(window):
    try:
        from revobim.egg import egg_hook
        egg_hook.attach(window, window.FindName('LogoImage'))
        return True
    except Exception:
        return False


# ---------------------------------------------------------
# Window chrome
#
# A borderless AllowsTransparency window cannot be resized by
# WPF - there is nothing hit testable in the transparent
# frame - so it carries its own grips.
# ---------------------------------------------------------

GRIP_CURSORS = {
    'GripN': 'SizeNS', 'GripS': 'SizeNS',
    'GripW': 'SizeWE', 'GripE': 'SizeWE',
    'GripNW': 'SizeNWSE', 'GripSE': 'SizeNWSE',
    'GripNE': 'SizeNESW', 'GripSW': 'SizeNESW',
}


class Chrome(object):
    """Drag, resize grips and full screen for one window."""

    def __init__(self, window):
        self.window = window
        self.saved = None
        self._wire_header()
        self._wire_grips()
        self._wire_keys()

    # -- header ------------------------------------------------
    def _wire_header(self):
        bar = self.window.FindName('HeaderBar')
        if bar is None:
            return

        @ui_safe
        def on_press(sender, args):
            if args.ClickCount == 2:
                self.toggle_full_screen()
                return
            if self.saved is not None:
                self.toggle_full_screen()
            try:
                self.window.DragMove()
            except Exception:
                pass

        bar.MouseLeftButtonDown += on_press

        for name, handler in (('CloseButton', self.close),
                              ('FullScreenButton', self.toggle_full_screen)):
            button = self.window.FindName(name)
            if button is None:
                continue
            button.Click += ui_safe(lambda s, a, fn=handler: fn())

    # -- grips -------------------------------------------------
    def _wire_grips(self):
        for name, cursor_name in GRIP_CURSORS.items():
            grip = self.window.FindName(name)
            if grip is None:
                continue
            try:
                grip.Cursor = getattr(Cursors, cursor_name)
            except Exception:
                pass
            grip.DragDelta += ui_safe(
                lambda s, a, key=name: self._resize(key, a))

    def _resize(self, key, args):
        window = self.window
        dx, dy = args.HorizontalChange, args.VerticalChange

        if key in ('GripW', 'GripNW', 'GripSW'):
            new_width = window.Width - dx
            if new_width >= window.MinWidth:
                window.Left += dx
                window.Width = new_width
        if key in ('GripE', 'GripNE', 'GripSE'):
            new_width = window.Width + dx
            if new_width >= window.MinWidth:
                window.Width = new_width
        if key in ('GripN', 'GripNW', 'GripNE'):
            new_height = window.Height - dy
            if new_height >= window.MinHeight:
                window.Top += dy
                window.Height = new_height
        if key in ('GripS', 'GripSW', 'GripSE'):
            new_height = window.Height + dy
            if new_height >= window.MinHeight:
                window.Height = new_height

    # -- keys --------------------------------------------------
    def _wire_keys(self):
        @ui_safe
        def on_key(sender, args):
            if args.Key == Key.F11:
                self.toggle_full_screen()
            elif args.Key == Key.Escape:
                if self.saved is not None:
                    self.toggle_full_screen()
                else:
                    self.close()

        self.window.KeyDown += on_key

    # -- full screen -------------------------------------------
    def toggle_full_screen(self):
        window = self.window
        if self.saved is not None:
            left, top, width, height = self.saved
            window.Left, window.Top = left, top
            window.Width, window.Height = width, height
            self.saved = None
            return

        self.saved = (window.Left, window.Top, window.Width, window.Height)
        try:
            window.SizeToContent = SizeToContent.Manual
        except Exception:
            pass
        bounds = self._working_area()
        if bounds is None:
            try:
                window.WindowState = WindowState.Maximized
            except Exception:
                pass
            return
        left, top, width, height = bounds
        window.Left, window.Top = left, top
        window.Width, window.Height = width, height

    def _working_area(self):
        """The working area of the screen the window is on.

        SystemParameters.WorkArea is the primary monitor, not
        the one the window is on, and a borderless
        AllowsTransparency window maximised the normal way
        covers the task bar. Divide by the DPI scale or it
        overshoots on a scaled display.
        """
        try:
            import clr
            clr.AddReference('System.Windows.Forms')
            from System.Windows.Forms import Screen
            handle = WindowInteropHelper(self.window).Handle
            screen = Screen.FromHandle(handle)
            area = screen.WorkingArea

            scale_x, scale_y = 1.0, 1.0
            try:
                source = PresentationSource.FromVisual(self.window)
                matrix = source.CompositionTarget.TransformToDevice
                scale_x, scale_y = matrix.M11, matrix.M22
            except Exception:
                pass
            if not scale_x:
                scale_x = 1.0
            if not scale_y:
                scale_y = 1.0

            return (area.Left / scale_x, area.Top / scale_y,
                    area.Width / scale_x, area.Height / scale_y)
        except Exception:
            return None

    def close(self):
        try:
            self.window.Close()
        except Exception:
            pass


# ---------------------------------------------------------
# The theme chip
# ---------------------------------------------------------

def wire_theme_chip(window, setting, on_change=None):
    """Cycles Auto, Dark, Light and reports the new setting."""
    chip = window.FindName('ThemeChip')
    state = {'setting': setting}

    def paint():
        try:
            chip.Content = theme_module.chip_label(state['setting'])
        except Exception:
            pass

    if chip is None:
        return state

    @ui_safe
    def on_click(sender, args):
        state['setting'] = theme_module.next_theme(state['setting'])
        theme_module.apply(window, theme_module.resolve(state['setting']))
        paint()
        if on_change is not None:
            on_change(state['setting'])

    chip.Click += on_click
    paint()
    return state
