# -*- coding: utf-8 -*-

"""Legend Creator - palettes and loading windows.

Follows Revit's canvas theme, paints a palette onto an open window, and loads
a layout with the shared Theme.xaml spliced into it.
"""

import io
import os

from pyrevit import forms

import lgc_clr  # noqa: F401 - references first, before any System import
from System.Windows.Media import Color, SolidColorBrush

from lgc_logic import PALETTES, pick_theme, read_theme_text, splice_theme
from lgc_core import SETTINGS_DIR, err_text, log, swallowed


def revit_theme():
    """Revit's own canvas theme as 'dark' or 'light', or None if unknown.

    UIThemeManager arrived in Revit 2024, and the canvas theme is a separate
    property from the UI theme, so both are tried and the canvas - what the
    drawing area actually looks like - wins. Every route is guarded: a
    release that does not expose it must fall back, not throw.
    """
    try:
        import Autodesk.Revit.UI as revit_ui
    except Exception:
        swallowed()
        return None
    # getattr, not a direct import: UIThemeManager does not exist before
    # Revit 2024, and a missing name must fall back rather than throw.
    UIThemeManager = getattr(revit_ui, 'UIThemeManager', None)
    if UIThemeManager is None:
        return None

    for attribute in ('CurrentCanvasTheme', 'CurrentTheme'):
        try:
            value = getattr(UIThemeManager, attribute)
        except Exception:
            swallowed()
            continue
        log(u'theme: UIThemeManager.{0} = {1}'.format(attribute, value))
        found = read_theme_text(value)
        if found:
            return found
    return None


def resolve_theme(mode):
    """Turn a saved mode into the palette actually used."""
    return pick_theme(mode, None if mode in ('dark', 'light')
                      else revit_theme())


def apply_palette(window, name):
    """Write a palette straight onto window.Resources.

    Every colour in the layouts is a DynamicResource, and window.Resources
    sits in front of anything merged, so replacing the brushes repaints an
    open window with no reload and no loss of state.
    """
    palette = PALETTES.get(name, PALETTES['dark'])
    for key, hex_value in palette.items():
        try:
            window.Resources[key] = brush(hex_value)
        except Exception:
            swallowed()
    return palette


def brush(hex_string):
    """A WPF brush from '#RRGGBB'. Never raises - a swatch is cosmetic, and
    a bad colour must not take the window down with it."""
    try:
        text = (hex_string or '').lstrip('#')
        if len(text) != 6:
            raise ValueError('expected six hex digits')
        return SolidColorBrush(Color.FromRgb(int(text[0:2], 16),
                                             int(text[2:4], 16),
                                             int(text[4:6], 16)))
    except Exception:
        return SolidColorBrush(Color.FromRgb(154, 154, 158))


def layout_text(xaml_path):
    """A layout file with Theme.xaml, beside it, spliced in."""
    folder = os.path.dirname(os.path.abspath(xaml_path))
    layout = io.open(xaml_path, encoding='utf-8').read()
    theme = io.open(os.path.join(folder, 'Theme.xaml'), encoding='utf-8').read()
    return splice_theme(layout, theme)


def load_window(window, xaml_path):
    """forms.WPFWindow.__init__, with the shared theme spliced in.

    handle_esc is off: pyRevit's own Escape handler closes the window and
    runs before the drawer's, so in 2.12 Escape on a parked bar closed the
    window instead of reopening it. Each window handles Escape itself.
    """
    text = layout_text(xaml_path)
    try:
        forms.WPFWindow.__init__(window, text, literal_string=True,
                                 handle_esc=False)
        return
    except TypeError as err:
        if 'argument' not in err_text(err):
            raise
        swallowed()             # a pyRevit without those keywords
    folder = os.path.join(SETTINGS_DIR, 'legend_creator_ui')
    if not os.path.isdir(folder):
        os.makedirs(folder)
    path = os.path.join(folder, os.path.basename(xaml_path))
    handle = io.open(path, 'w', encoding='utf-8')
    try:
        handle.write(text)
    finally:
        handle.close()
    log(u'loaded {0} from a merged copy - this pyRevit takes no '
        u'literal_string'.format(os.path.basename(xaml_path)))
    forms.WPFWindow.__init__(window, path)
