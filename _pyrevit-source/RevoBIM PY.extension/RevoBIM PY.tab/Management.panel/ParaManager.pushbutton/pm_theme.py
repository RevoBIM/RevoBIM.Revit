# -*- coding: utf-8 -*-
"""Palettes and Revit's canvas theme."""
import pm_clr
from System.Windows.Media import BrushConverter, SolidColorBrush

DARK = {
    'WindowBg': '#3C4454', 'TitleBg': '#222933', 'FieldBg': '#2D3441', 'StripBg': '#1B1F24',
    'HeadBg': '#323C48', 'HoverBg': '#444E5E', 'SelBg': '#3A7392', 'Edge': '#515C6B',
    'Text': '#EEF0F4', 'Muted': '#A4AAB1', 'Blue': '#5AAEEB', 'Orange': '#E8912D',
    'Green': '#3FA75A', 'GreenHover': '#4EC06D', 'Red': '#D9534F', 'DisabledBg': '#59616F',
    'DisabledText': '#A4AAB1', 'NewRow': '#6E3B42', 'ModRow': '#5C4B30', 'DelRow': '#4A2B30',
    'OnAccent': '#FFFFFF',
}
LIGHT = {
    'WindowBg': '#F1F1F2', 'TitleBg': '#E3E3E5', 'FieldBg': '#FFFFFF', 'StripBg': '#D9D9DC',
    'HeadBg': '#E9E9EB', 'HoverBg': '#DADDE2', 'SelBg': '#BBD8EE', 'Edge': '#B4B4B9',
    'Text': '#232326', 'Muted': '#66666B', 'Blue': '#1B72BE', 'Orange': '#B96A12',
    'Green': '#2E8546', 'GreenHover': '#37A055', 'Red': '#C23B37', 'DisabledBg': '#B3B3B7',
    'DisabledText': '#55555A', 'NewRow': '#FFD2D2', 'ModRow': '#FBE6C8', 'DelRow': '#E9C4C4',
    'OnAccent': '#FFFFFF',
}


def canvas_is_dark():
    """UITheme.Dark is 0, so every read is tested with 'is not None'."""
    try:
        import Autodesk.Revit.UI as rui
        manager = getattr(rui, 'UIThemeManager', None)
        if manager is None:
            return False
        theme = getattr(manager, 'CurrentCanvasTheme', None)
        if theme is None:
            theme = getattr(manager, 'CurrentTheme', None)
        if theme is None:
            return False
        return theme == getattr(rui, 'UITheme').Dark
    except Exception:
        return False


def brushes(name):
    palette = DARK if name == 'dark' else LIGHT
    convert = BrushConverter()
    out = {}
    for key in palette:
        brush = convert.ConvertFromString(palette[key])
        brush.Freeze()
        out[key] = brush
    return out
