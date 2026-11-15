# -*- coding: utf-8 -*-
"""Dark and light palettes, and Revit canvas-theme detection.

The light palette is not the dark one inverted: the accents are darkened because
the dark palette's accents are chosen to sit on near-black and wash out on white.
Every key here must have a brush in Theme.xaml (the bench check enforces it).
"""
import sdp_clr

from System.Windows.Media import Color, SolidColorBrush

KEYS = [
    'WindowBrush', 'CardBrush', 'FieldBrush', 'BarBrush', 'EdgeBrush',
    'FrameEdgeBrush', 'TextBrush', 'MutedBrush', 'BlueBrush', 'BlueHoverBrush',
    'OrangeBrush', 'OrangeHoverBrush', 'GreenBrush', 'GreenHoverBrush',
    'RedBrush', 'SelectBrush', 'HoverBrush', 'DisabledBrush', 'OnAccentBrush',
    'ThumbBrush',
]

DARK = {
    'WindowBrush': '#232326', 'CardBrush': '#2B2B2E', 'FieldBrush': '#1C1C1F',
    'BarBrush': '#1C1C1F', 'EdgeBrush': '#3E3E42', 'FrameEdgeBrush': '#4A4A50',
    'TextBrush': '#E4E4E4', 'MutedBrush': '#9A9A9E', 'BlueBrush': '#4FA3E3',
    'BlueHoverBrush': '#6DB8EE', 'OrangeBrush': '#E8912D',
    'OrangeHoverBrush': '#F0A552', 'GreenBrush': '#3FA75A',
    'GreenHoverBrush': '#4EC06D', 'RedBrush': '#D9534F', 'SelectBrush': '#2B5473',
    'HoverBrush': '#38383C', 'DisabledBrush': '#3A3A3E', 'OnAccentBrush': '#FFFFFF',
    'ThumbBrush': '#5A5A60',
}

LIGHT = {
    'WindowBrush': '#F3F3F5', 'CardBrush': '#FFFFFF', 'FieldBrush': '#FAFAFB',
    'BarBrush': '#E6E6EA', 'EdgeBrush': '#C9C9D0', 'FrameEdgeBrush': '#B5B5BD',
    'TextBrush': '#1F1F23', 'MutedBrush': '#6A6A72', 'BlueBrush': '#1B72BE',
    'BlueHoverBrush': '#2A86D4', 'OrangeBrush': '#B96A12',
    'OrangeHoverBrush': '#D07F22', 'GreenBrush': '#2E8546',
    'GreenHoverBrush': '#3A9D57', 'RedBrush': '#C0392B', 'SelectBrush': '#CFE3F5',
    'HoverBrush': '#E9E9EE', 'DisabledBrush': '#D4D4D9', 'OnAccentBrush': '#FFFFFF',
    'ThumbBrush': '#B0B0B8',
}


def revit_theme_name():
    """'dark', 'light', or None when Revit's theme cannot be read.

    The canvas theme is preferred (what the user sees in the drawing area), then
    the UI theme. UIThemeManager only exists from Revit 2024, so it is reached by
    getattr rather than a top-level import. UITheme.Dark is 0, so every test here
    is 'is not None', never truthiness.
    """
    try:
        import Autodesk.Revit.UI as revit_ui
        manager = getattr(revit_ui, 'UIThemeManager', None)
        if manager is None:
            return None
        for prop in ('CurrentCanvasTheme', 'CurrentTheme'):
            try:
                value = getattr(manager, prop)
            except Exception:
                continue
            if value is not None:
                text = ('%s' % (value,)).lower()
                if 'dark' in text:
                    return 'dark'
                if 'light' in text:
                    return 'light'
    except Exception:
        pass
    return None


def _color(hex_text):
    h = hex_text.lstrip('#')
    return Color.FromRgb(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def apply(window, name):
    """Write the palette straight onto window.Resources. That sits in front of the
    merged Theme.xaml in WPF's lookup order, so it swaps live with no reload."""
    palette = DARK if name == 'dark' else LIGHT
    for key in KEYS:
        brush = SolidColorBrush(_color(palette[key]))
        try:
            brush.Freeze()
        except Exception:
            pass
        window.Resources[key] = brush
