# -*- coding: utf-8 -*-
"""RevoBIM palettes and Revit canvas theme detection.

The palette is written straight onto window.Resources, which WPF looks in
before the merged Theme.xaml, so switching dark/light on an open window needs
no reload.
"""
import eim_clr  # noqa: F401  (assembly references first)
from System.Windows.Media import SolidColorBrush, ColorConverter

PALETTES = {
    u'dark': {
        'Bg': '#232326', 'Card': '#2B2B2E', 'Field': '#1C1C1F', 'Bar': '#1C1C1F',
        'Edge': '#3E3E42', 'Frame': '#4A4A50', 'Hover': '#333338',
        'Text': '#E4E4E4', 'Muted': '#9A9A9E', 'OnAccent': '#FFFFFF',
        'Blue': '#4FA3E3', 'Orange': '#E8912D', 'Green': '#3FA75A',
        'GreenHover': '#4EC06D', 'Red': '#D9534F', 'Sel': '#2B5473',
    },
    u'light': {
        'Bg': '#F3F3F5', 'Card': '#FFFFFF', 'Field': '#FAFAFB', 'Bar': '#E6E6EA',
        'Edge': '#C9C9CF', 'Frame': '#B5B5BC', 'Hover': '#ECECF0',
        'Text': '#1E1E21', 'Muted': '#66666C', 'OnAccent': '#FFFFFF',
        'Blue': '#1B72BE', 'Orange': '#B96A12', 'Green': '#2E8546',
        'GreenHover': '#379B53', 'Red': '#C0392B', 'Sel': '#CFE3F5',
    },
}


def canvas_is_dark():
    """True / False from Revit's live canvas theme, None when it cannot be read.

    UIThemeManager exists from Revit 2024, so it is reached by getattr rather
    than a top-level import. UITheme.Dark is 0, so the read is tested with
    'is not None' - a truthiness test reports Dark as a failed read."""
    try:
        import Autodesk.Revit.UI as rui
        mgr = getattr(rui, 'UIThemeManager', None)
        ui_theme = getattr(rui, 'UITheme', None)
        if mgr is None or ui_theme is None:
            return None
        dark = getattr(ui_theme, 'Dark')
        for prop in ('CurrentCanvasTheme', 'CurrentTheme'):
            try:
                value = getattr(mgr, prop)
            except Exception:
                value = None
            if value is not None:
                return value == dark
    except Exception:
        pass
    return None


def brush(hex_value):
    b = SolidColorBrush(ColorConverter.ConvertFromString(hex_value))
    b.Freeze()
    return b


def apply_palette(window, name):
    palette = PALETTES.get(name) or PALETTES[u'dark']
    for key in palette:
        try:
            window.Resources[key] = brush(palette[key])
        except Exception:
            pass
