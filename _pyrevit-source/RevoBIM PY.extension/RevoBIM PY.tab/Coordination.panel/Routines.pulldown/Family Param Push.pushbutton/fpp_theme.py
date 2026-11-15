# -*- coding: utf-8 -*-
"""Revit's own dark palette and the house light palette. Same keys in both."""
import fpp_clr  # noqa: F401  (must stay first)

REVIT_DARK = {
    'WindowBg': '#3C4454', 'TitleBg': '#222933', 'PanelBg': '#343C4A',
    'FieldBg': '#2D3441', 'HeadBg': '#323C48', 'HoverBg': '#444E5E',
    'SelectBg': '#3A7392', 'Edge': '#515C6B', 'Text': '#EEF0F4',
    'Muted': '#B4BAC2', 'Hint': '#8C95A3', 'Blue': '#5AAEEB',
    'Orange': '#E8912D', 'Green': '#3FA75A', 'Red': '#D9534F',
    'OnAccent': '#FFFFFF',
}
LIGHT = {
    'WindowBg': '#F3F4F6', 'TitleBg': '#E4E7EB', 'PanelBg': '#FFFFFF',
    'FieldBg': '#FFFFFF', 'HeadBg': '#E9ECF0', 'HoverBg': '#DDE3EA',
    'SelectBg': '#BBDAF2', 'Edge': '#C3C9D1', 'Text': '#20242A',
    'Muted': '#59616C', 'Hint': '#7B838E', 'Blue': '#1B72BE',
    'Orange': '#B96A12', 'Green': '#2E8546', 'Red': '#C0392B',
    'OnAccent': '#FFFFFF',
}


def resolve(setting, canvas):
    """setting is auto / dark / light; canvas is what Revit reports."""
    if setting == 'dark':
        return 'dark'
    if setting == 'light':
        return 'light'
    return canvas if canvas in ('dark', 'light') else 'dark'


def next_setting(setting):
    return {'auto': 'dark', 'dark': 'light', 'light': 'auto'}.get(setting,
                                                                  'auto')


def chip_label(setting):
    return {'auto': 'Auto', 'dark': 'Dark', 'light': 'Light'}.get(setting,
                                                                  'Auto')


def palette(name):
    return LIGHT if name == 'light' else REVIT_DARK


def revit_canvas():
    """UIThemeManager only exists from Revit 2024. UITheme.Dark is 0, so the
    read is tested with `is not None`, never truthiness."""
    try:
        import Autodesk.Revit.UI as revit_ui
        manager = getattr(revit_ui, 'UIThemeManager', None)
        if manager is None:
            return None
        theme = manager.CurrentCanvasTheme
        if theme is None:
            return None
        return 'dark' if str(theme).endswith('Dark') else 'light'
    except Exception:
        return None
