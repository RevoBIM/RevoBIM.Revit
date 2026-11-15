# -*- coding: utf-8 -*-
"""RevoBIM PY - Wires shared window plumbing.

XAML loading with the theme merged in, the RevoBIM header (theme chip, shrink
to taskbar, close), and icons loaded from bytes rather than a System.Uri
(which moved assemblies between Revit 2024 and 2025 and throws ImportError at
module load on the later releases).

Every window goes through load_window and dress_header, and nothing else in
the tool paints a colour by value: code-built elements take theirs through
paint(), a resource reference, so a theme swap repaints them with the rest.
"""

import os

import clr

for _asm in ('PresentationCore', 'PresentationFramework', 'WindowsBase', 'mscorlib',
             'System.Xml', 'System.Xaml', 'System', 'RevitAPIUI'):
    try:
        clr.AddReference(_asm)
    except Exception:
        pass

from System.IO import StringReader, MemoryStream, File
from System.Xml import XmlReader
from System.Windows.Markup import XamlReader
from System.Windows.Media import SolidColorBrush, Color
from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption
from System.Windows.Controls import (
    Grid, ColumnDefinition, TextBlock, Border,
)
from System.Windows import Thickness, GridLength, GridUnitType, TextWrapping

import wires_theme as theme
from wires_drawer import WindowDrawer

HERE = os.path.dirname(os.path.abspath(__file__))
THEME_FILE = 'Theme.xaml'

# The palette in force, and every themed window still open - a chip press in
# one window repaints them all.
CURRENT = {'mode': theme.FOLLOW, 'name': theme.DARK}
_OPEN = []


def brush(hex_value):
    """A SolidColorBrush from #RRGGBB, without touching ColorConverter."""
    try:
        text = hex_value.lstrip('#')
        red = int(text[0:2], 16)
        green = int(text[2:4], 16)
        blue = int(text[4:6], 16)
        made = SolidColorBrush(Color.FromRgb(red, green, blue))
        try:
            made.Freeze()
        except Exception:
            pass
        return made
    except Exception:
        return SolidColorBrush(Color.FromRgb(154, 154, 158))


def paint(element, dependency_property, key):
    """Have a code-built element follow a palette key, live.

    A brush assigned by value is invisible to a theme swap; a resource
    reference re-resolves with everything else. The property is the static
    one on the class (Border.BackgroundProperty), never an instance's.
    """
    try:
        element.SetResourceReference(dependency_property, key)
        return
    except Exception:
        pass
    try:
        element.SetValue(dependency_property,
                         brush(theme.hex_of(CURRENT['name'], key)))
    except Exception:
        pass


# --- the theme ----------------------------------------------------------------
def revit_canvas_dark():
    """True / False from Revit's canvas theme, None where it cannot be read.

    UIThemeManager is Revit 2024+, reached by name so older releases fall
    through rather than fail at import. The canvas is read first - it is what
    the windows sit over - then the UI theme.
    """
    try:
        import Autodesk.Revit.UI as revit_ui
        manager = getattr(revit_ui, 'UIThemeManager', None)
    except Exception:
        manager = None
    if manager is None:
        return None
    for name in ('CurrentCanvasTheme', 'CurrentTheme'):
        try:
            found = theme.is_dark_value(getattr(manager, name))
        except Exception:
            found = None
        if found is not None:
            return found
    return None


def _stored_mode():
    try:
        import wires_core as core
        return theme.normalise(core.load_settings().get('theme', theme.FOLLOW))
    except Exception:
        return theme.FOLLOW


def _store_mode(mode):
    try:
        import wires_core as core
        settings = core.load_settings()
        settings['theme'] = mode
        return core.save_settings(settings)
    except Exception:
        return False


def _theme_dictionary():
    path = os.path.join(HERE, THEME_FILE)
    return XamlReader.Load(XmlReader.Create(StringReader(_read(path))))


def apply_theme(window, name):
    """Write the palette onto window.Resources, which WPF looks in before the
    merged Theme.xaml - so every DynamicResource re-resolves in place."""
    palette = theme.PALETTES.get(name) or theme.PALETTES[theme.DARK]
    for key in palette:
        try:
            window.Resources[key] = brush(palette[key])
        except Exception:
            continue
    _dress_chip(window)


def refresh_theme(mode=None):
    """Re-read the setting and Revit's canvas, and repaint every open window."""
    if mode is None:
        mode = _stored_mode()
    CURRENT['mode'] = theme.normalise(mode)
    CURRENT['name'] = theme.resolve(CURRENT['mode'], revit_canvas_dark())
    for window in list(_OPEN):
        apply_theme(window, CURRENT['name'])
    return CURRENT['name']


def _attach_theme(window):
    try:
        window.Resources.MergedDictionaries.Add(_theme_dictionary())
    except Exception:
        pass
    _OPEN.append(window)

    def _closed(sender, args):
        try:
            _OPEN.remove(window)
        except Exception:
            pass
    try:
        window.Closed += _closed
    except Exception:
        pass
    refresh_theme()


def _dress_chip(window):
    try:
        text = window.FindName('ThemeText')
        if text is not None:
            text.Text = theme.chip_text(CURRENT['mode'], CURRENT['name'])
        chip = window.FindName('ThemeChip')
        if chip is not None:
            chip.ToolTip = theme.chip_tip(CURRENT['mode'], CURRENT['name'])
    except Exception:
        pass


def _on_theme_chip(sender, args):
    """Auto, Dark, Light, Auto. Saved straight away, every window repainted."""
    mode = theme.next_mode(CURRENT['mode'])
    _store_mode(mode)
    refresh_theme(mode)


# --- loading ----------------------------------------------------------------
def _read(path):
    handle = open(path, 'r')
    try:
        text = handle.read()
    finally:
        handle.close()
    if text[:1] == u'﻿':
        text = text[1:]
    return text


def load_window(xaml_file_name):
    """Parse a layout file beside this module into a themed Window.

    The theme is merged after the parse, which is why layouts may only use
    DynamicResource.
    """
    path = os.path.join(HERE, xaml_file_name)
    window = XamlReader.Load(XmlReader.Create(StringReader(_read(path))))
    _attach_theme(window)
    return window


def load_bitmap(path):
    """A BitmapImage from bytes. Never from a Uri."""
    try:
        if not os.path.isfile(path):
            return None
        image = BitmapImage()
        image.BeginInit()
        image.StreamSource = MemoryStream(File.ReadAllBytes(path))
        image.CacheOption = BitmapCacheOption.OnLoad
        image.EndInit()
        try:
            image.Freeze()
        except Exception:
            pass
        return image
    except Exception:
        return None


def dress_header(window, version, icon_file_name='icon.png'):
    """Icon, version, theme chip, shrink to taskbar, drag and close - what
    every RevoBIM window's header does. Returns the window's drawer.

    Everything here is decorative or convenience, so every step swallows its
    own failure - cosmetics must never be able to take a tool down.
    """
    try:
        label = window.FindName('VersionText')
        if label is not None:
            label.Text = 'v{0}'.format(version)
    except Exception:
        pass

    try:
        image = window.FindName('HeaderIcon')
        if image is not None:
            bitmap = load_bitmap(os.path.join(HERE, icon_file_name))
            if bitmap is not None:
                image.Source = bitmap
    except Exception:
        pass

    try:
        chip = window.FindName('ThemeChip')
        if chip is not None:
            chip.Click += _on_theme_chip
    except Exception:
        pass
    _dress_chip(window)

    drawer = None
    try:
        drawer = WindowDrawer(window, window.FindName('HeaderBar'),
                              window.FindName('Chrome'),
                              window.FindName('ShrinkButton'))
    except Exception:
        drawer = None

    try:
        bar = window.FindName('HeaderBar')
        if bar is not None:
            def _pressed(sender, args):
                if drawer is not None:
                    drawer.header_pressed(args)
                    return
                try:
                    window.DragMove()
                except Exception:
                    pass
            bar.MouseLeftButtonDown += _pressed
    except Exception:
        pass

    try:
        button = window.FindName('CloseButton')
        if button is not None:
            def _close(sender, args):
                try:
                    window.Close()
                except Exception:
                    pass
            button.Click += _close
    except Exception:
        pass
    return drawer


def owned_by_revit(window):
    """Sit the window in front of Revit rather than behind it."""
    try:
        clr.AddReference('System.Windows.Forms')
        from System.Diagnostics import Process
        from System.Windows.Interop import WindowInteropHelper
        helper = WindowInteropHelper(window)
        helper.Owner = Process.GetCurrentProcess().MainWindowHandle
    except Exception:
        pass


# --- a report row -----------------------------------------------------------
TICK_FOR = {
    'ok': 'Green',
    'info': 'Muted',
    'note': 'Orange',
    'skip': 'Red',
}


def report_row(kind, text):
    """One line of the results list, built in code.

    Built rather than bound: WPF cannot reliably see attributes on a Python
    object, and a DataTemplate binding that silently resolves to nothing is a
    blank list with no error to read.
    """
    grid = Grid()
    first = ColumnDefinition()
    first.Width = GridLength.Auto
    second = ColumnDefinition()
    second.Width = GridLength(1, GridUnitType.Star)
    grid.ColumnDefinitions.Add(first)
    grid.ColumnDefinitions.Add(second)
    grid.Margin = Thickness(0, 3, 0, 3)

    tick = Border()
    tick.Width = 4
    tick.CornerRadius = corner(2)
    tick.Margin = Thickness(0, 1, 9, 1)
    paint(tick, Border.BackgroundProperty, TICK_FOR.get(kind, 'Muted'))
    Grid.SetColumn(tick, 0)
    grid.Children.Add(tick)

    label = TextBlock()
    label.Text = text
    label.FontSize = 12
    label.TextWrapping = TextWrapping.Wrap
    paint(label, TextBlock.ForegroundProperty,
          'Muted' if kind in ('skip', 'info') else 'Fg')
    Grid.SetColumn(label, 1)
    grid.Children.Add(label)
    return grid


def park_bottom_right(window, margin=40):
    """Sit the window out of the way of the drawing it is asking about."""
    try:
        from System.Windows import SystemParameters
        area = SystemParameters.WorkArea
        window.Left = area.Left + area.Width - window.Width - margin
        window.Top = area.Top + area.Height - 260 - margin
    except Exception:
        pass


def corner(radius):
    from System.Windows import CornerRadius
    return CornerRadius(radius)


def visible():
    from System.Windows import Visibility
    return Visibility.Visible


def hidden():
    from System.Windows import Visibility
    return Visibility.Collapsed


def hint(text):
    """The muted note that sits under a setting."""
    block = TextBlock()
    block.Text = text
    block.FontSize = 11
    paint(block, TextBlock.ForegroundProperty, 'Muted')
    block.TextWrapping = TextWrapping.Wrap
    block.Margin = Thickness(0, 2, 0, 6)
    return block
