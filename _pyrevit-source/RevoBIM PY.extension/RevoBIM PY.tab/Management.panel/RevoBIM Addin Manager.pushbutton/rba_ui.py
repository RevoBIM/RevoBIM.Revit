# -*- coding: utf-8 -*-
u"""RevoBIM Addins - XAML loading, theming, icons, and the easter egg.

Theme.xaml is merged in AFTER XamlReader has parsed the layout, so a layout
file may only ever use DynamicResource.  A StaticResource fails at parse time
and the tool dies before any of it runs.
"""

import rba_clr  # noqa: F401

import os

from System.IO import File, FileStream, FileMode, FileAccess, MemoryStream
from System.Windows.Markup import XamlReader
from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption, BitmapCreateOptions

from rba_core import to_text, tool_folder, log, log_exception

_ICON_CACHE = {}


def xaml_path(name):
    return os.path.join(tool_folder(), name)


def load_xaml(name):
    u"""Parse a layout and merge Theme.xaml into it."""
    stream = FileStream(xaml_path(name), FileMode.Open, FileAccess.Read)
    try:
        element = XamlReader.Load(stream)
    finally:
        stream.Close()
    merge_theme(element)
    return element


def merge_theme(element):
    theme_file = xaml_path(u"Theme.xaml")
    if not os.path.isfile(theme_file):
        return
    stream = FileStream(theme_file, FileMode.Open, FileAccess.Read)
    try:
        dictionary = XamlReader.Load(stream)
    finally:
        stream.Close()
    try:
        element.Resources.MergedDictionaries.Add(dictionary)
    except Exception:
        log_exception(u"merge_theme")


def load_image(path, size):
    u"""BitmapImage from bytes.

    Never through BitmapImage.UriSource: System.Uri moved assemblies in Revit
    2025 and "from System import Uri" throws ImportError at module load there,
    killing the script before any of it runs.
    """
    if not path or not os.path.isfile(path):
        return None
    key = u"{0}|{1}".format(path, size)
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]
    try:
        stream = MemoryStream(File.ReadAllBytes(path))
        image = BitmapImage()
        image.BeginInit()
        image.StreamSource = stream
        image.CacheOption = BitmapCacheOption.OnLoad
        image.CreateOptions = BitmapCreateOptions.IgnoreColorProfile
        try:
            image.DecodePixelWidth = int(size) * 2
        except Exception:
            pass
        image.EndInit()
        try:
            image.Freeze()
        except Exception:
            pass
        _ICON_CACHE[key] = image
        return image
    except Exception:
        log_exception(u"load_image/{0}".format(path))
        return None


def clear_icon_cache():
    _ICON_CACHE.clear()


def initial_glyph(text, size, background, foreground):
    u"""A drawn stand-in for a button with no icon.

    Drawn from a Border and a TextBlock rather than set in a symbol font, so it
    cannot come out as an empty box on a machine without that font.
    """
    from System.Windows import (Thickness, CornerRadius, FontWeights,
                                HorizontalAlignment, VerticalAlignment)
    from System.Windows.Controls import Border, TextBlock
    from System.Windows.Media import FontFamily

    letter = to_text(text).strip()
    if letter:
        letter = letter[:1].upper()
    else:
        letter = u"?"
    border = Border()
    border.Width = size
    border.Height = size
    border.CornerRadius = CornerRadius(3)
    border.Background = background
    border.BorderThickness = Thickness(0)
    label = TextBlock()
    label.Text = letter
    label.Foreground = foreground
    label.FontFamily = FontFamily(u"Segoe UI")
    label.FontSize = max(9, int(size * 0.5))
    label.FontWeight = FontWeights.SemiBold
    label.HorizontalAlignment = HorizontalAlignment.Center
    label.VerticalAlignment = VerticalAlignment.Center
    border.Child = label
    return border


# ----------------------------------------------------------------------
# easter egg - three slow clicks on the RevoBIM logo
# ----------------------------------------------------------------------

CLICK_FLOOR_MS = 250     # faster than this is a double click, not a slow one
CLICK_CEILING_MS = 2000  # slower than this has stopped being a sequence


class SlowClickWatcher(object):
    u"""Counts three deliberate clicks on one element.

    WPF's own ClickCount only ever reports 1 or 2, so the sequence is timed
    from args.Timestamp, and a repeated timestamp is discarded: the same
    physical click arrives more than once when a parent has already handled the
    tunnelling event and the handler was added with handledEventsToo.
    """

    def __init__(self, on_trigger):
        self.on_trigger = on_trigger
        self.count = 0
        self.last = None

    def clicked(self, timestamp):
        if self.last is not None and timestamp == self.last:
            return False
        gap = None if self.last is None else (timestamp - self.last)
        self.last = timestamp
        if gap is None or gap > CLICK_CEILING_MS or gap < CLICK_FLOOR_MS:
            self.count = 1
            return False
        self.count += 1
        if self.count >= 3:
            self.count = 0
            self.last = None
            try:
                self.on_trigger()
            except Exception:
                log_exception(u"easter_egg/trigger")
            return True
        return False


def attach_easter_egg(element, host_getter, theme_getter):
    u"""Wire three slow clicks on the RevoBIM logo to the arcade.

    Anything decorative belongs in a try/except that swallows failures, so the
    egg can never take the tool down.
    """
    def fire():
        try:
            from revobim.egg import egg_hook
        except Exception:
            log(u"easter_egg: revobim.egg not installed, nothing to launch")
            return
        host = None
        theme = u"dark"
        try:
            host = host_getter()
        except Exception:
            host = None
        try:
            theme = theme_getter()
        except Exception:
            theme = u"dark"
        for args in ((host, theme, None), (host, theme), (host,), ()):
            try:
                egg_hook.launch(*args)
                return
            except TypeError:
                continue
            except Exception:
                log_exception(u"easter_egg/launch")
                return

    watcher = SlowClickWatcher(fire)

    def on_down(sender, args):
        try:
            watcher.clicked(args.Timestamp)
        except Exception:
            pass

    try:
        from System.Windows.Input import MouseButtonEventHandler, Mouse
        element.AddHandler(Mouse.PreviewMouseDownEvent,
                           MouseButtonEventHandler(on_down), True)
    except Exception:
        try:
            element.MouseLeftButtonDown += on_down
        except Exception:
            log_exception(u"easter_egg/attach")
    return watcher


# ----------------------------------------------------------------------
# screens, DPI and ownership - one copy, used by every window
# ----------------------------------------------------------------------

def dip_scale(window):
    u"""(x, y) device pixels per WPF unit for the screen the window is on."""
    try:
        from System.Windows import PresentationSource
        source = PresentationSource.FromVisual(window)
        transform = source.CompositionTarget.TransformToDevice
        scale_x, scale_y = transform.M11, transform.M22
        if scale_x and scale_y:
            return scale_x, scale_y
    except Exception:
        pass
    return 1.0, 1.0


def work_area(window):
    u"""The working area of the screen the window is on, in WPF units.

    A monitor above or left of the primary has a negative top or left; that is
    returned as it is, which is what parks a bar on the right screen.
    """
    try:
        from System.Windows.Forms import Screen
        from System.Windows.Interop import WindowInteropHelper
        screen = Screen.FromHandle(WindowInteropHelper(window).Handle)
        area = screen.WorkingArea
        scale_x, scale_y = dip_scale(window)
        return (area.Left / scale_x, area.Top / scale_y,
                area.Width / scale_x, area.Height / scale_y)
    except Exception:
        log_exception(u"work_area")
        return None


def revit_handle():
    try:
        from System import IntPtr
        from System.Diagnostics import Process
        handle = Process.GetCurrentProcess().MainWindowHandle
        if handle != IntPtr.Zero:
            return handle
    except Exception:
        pass
    return None


def own(window, owner=None):
    u"""Own a window to another RevoBIM window, else to Revit's main window.

    An unowned window slips behind Revit the moment Revit is clicked, which
    reads exactly like the tool having crashed.
    """
    if owner is not None:
        try:
            window.Owner = owner
            return
        except Exception:
            log_exception(u"own/window")
    try:
        from System.Windows.Interop import WindowInteropHelper
        handle = revit_handle()
        if handle is not None:
            WindowInteropHelper(window).Owner = handle
    except Exception:
        log_exception(u"own/revit")


def no_drag(element):
    u"""Clicking this element never drags its window.

    The easter egg counts on the tunnelling preview event, so marking the
    bubbling one handled here stops the header's DragMove without costing the
    egg a click.
    """
    def on_down(sender, args):
        args.Handled = True
    try:
        element.MouseLeftButtonDown += on_down
    except Exception:
        pass
