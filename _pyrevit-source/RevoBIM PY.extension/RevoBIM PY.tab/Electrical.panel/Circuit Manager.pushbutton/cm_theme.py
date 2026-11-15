# -*- coding: utf-8 -*-
"""Circuit Manager - palettes, Theme.xaml loading and canvas following.

Dark is Revit's own dark theme (sampled from Revit's dark project browser,
the standard Project Browser Pro, Filter Manager and Pro Sheets use); light
is the house light palette with darkened accents. Brushes are written onto
window.Resources, which WPF searches before the merged Theme.xaml, so a
palette swap repaints an open window with no reload and no loss of state.
"""
import cm_clr  # noqa: F401
import os

from System.IO import File
from System.Windows.Markup import XamlReader
from System.Windows.Media import SolidColorBrush, ColorConverter, Color

HERE = os.path.dirname(os.path.abspath(__file__))
THEME_PATH = os.path.join(HERE, 'Theme.xaml')

PALETTES = {
    'dark': {
        'TitleBg': '#222933', 'BodyBg': '#3C4454', 'FieldBg': '#2D3441',
        'ToolbarBg': '#1B1F24', 'HeadingBg': '#323C48', 'CardBg': '#343C4A',
        'HoverBg': '#444E5E', 'PressBg': '#323C48', 'SelBg': '#3A7392',
        'RowHlBg': '#36485A', 'Edge': '#515C6B', 'FrameEdge': '#5A6372',
        'Text': '#EEF0F4', 'Muted': '#A4AAB1', 'Hint': '#7B8290',
        'Blue': '#5AAEEB', 'Orange': '#E8912D', 'Green': '#3FA75A',
        'GreenHover': '#4EC06D', 'Red': '#D9534F', 'OnAccent': '#FFFFFF',
        'ButtonBg': '#46505F', 'ButtonHover': '#55606F',
        'StagedBg': '#2F5E3B', 'StagedText': '#D8F5DF',
        'BadBg': '#8E2A27', 'BadText': '#FFE3E1',
        'CopyBg': '#6B5420', 'ReadOnlyBg': '#4A3E45',
    },
    'light': {
        'TitleBg': '#E4E7EB', 'BodyBg': '#F3F4F6', 'FieldBg': '#FFFFFF',
        'ToolbarBg': '#EAECEF', 'HeadingBg': '#E1E5EA', 'CardBg': '#FFFFFF',
        'HoverBg': '#E3E8EE', 'PressBg': '#D2D9E1', 'SelBg': '#BFDCF4',
        'RowHlBg': '#E3EFFA', 'Edge': '#C5CAD1', 'FrameEdge': '#AEB4BC',
        'Text': '#1E2329', 'Muted': '#5F6670', 'Hint': '#8A9099',
        'Blue': '#1B72BE', 'Orange': '#B96A12', 'Green': '#2E8546',
        'GreenHover': '#379A52', 'Red': '#C0392B', 'OnAccent': '#FFFFFF',
        'ButtonBg': '#E1E5EA', 'ButtonHover': '#D2D9E1',
        'StagedBg': '#CDEFD6', 'StagedText': '#14401F',
        'BadBg': '#F5B7B1', 'BadText': '#5C0F09',
        'CopyBg': '#FBE3A6', 'ReadOnlyBg': '#F6E1E1',
    },
}

_CACHE = {}


def brush(hex_text):
    b = _CACHE.get(hex_text)
    if b is None:
        b = SolidColorBrush(ColorConverter.ConvertFromString(hex_text))
        b.Freeze()
        _CACHE[hex_text] = b
    return b


def load_theme_dict():
    """A fresh Theme.xaml dictionary - one per window or popup it dresses."""
    return XamlReader.Parse(File.ReadAllText(THEME_PATH))


def apply_palette(element, resolved):
    pal = PALETTES.get(resolved, PALETTES['dark'])
    res = element.Resources
    for key, value in pal.items():
        res[key] = brush(value)


def dress(element, resolved):
    """Theme dictionary + current palette onto an element whose resources
    are not inherited from a window (a context menu opened by hand)."""
    try:
        element.Resources.MergedDictionaries.Add(load_theme_dict())
    except Exception:
        pass
    apply_palette(element, resolved)


def canvas_is_dark():
    """True / False from Revit's live canvas theme; None where unreadable.

    UIThemeManager only exists from Revit 2024, so it is reached by getattr.
    UITheme.Dark is 0 - test 'is not None', never truthiness.
    """
    try:
        import Autodesk.Revit.UI as rui
    except Exception:
        return None
    mgr = getattr(rui, 'UIThemeManager', None)
    ui_theme = getattr(rui, 'UITheme', None)
    if mgr is None or ui_theme is None:
        return None
    for prop in ('CurrentCanvasTheme', 'CurrentTheme'):
        try:
            value = getattr(mgr, prop)
        except Exception:
            continue
        if value is not None:
            try:
                return value == ui_theme.Dark
            except Exception:
                return None
    return None
