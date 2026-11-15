# -*- coding: utf-8 -*-
"""3D Align - the dark and light palettes, and which one Revit is showing.

The palette is written onto window.Resources, which WPF looks in before the
merged Theme.xaml, so it can be swapped on an open window with no reload.
"""
import a3d_clr  # noqa: F401  - assemblies first, always

DARK = {
    'BgWindow': '#232326', 'BgCard': '#2B2B2E', 'BgField': '#1C1C1F',
    'BgBar': '#1C1C1F', 'Edge': '#3E3E42', 'EdgeWindow': '#4A4A50',
    'Text': '#E4E4E4', 'TextMuted': '#9A9A9E', 'Blue': '#4FA3E3',
    'Orange': '#E8912D', 'Green': '#3FA75A', 'GreenHover': '#4EC06D',
    'Red': '#D9534F', 'Selection': '#2B5473', 'Hover': '#38383D',
    'OnAccent': '#FFFFFF', 'RowOk': '#1F3326', 'RowWarn': '#3A2C1A',
    'RowBad': '#3A2020', 'RowQuiet': '#29292D',
}

LIGHT = {
    'BgWindow': '#F3F3F5', 'BgCard': '#FFFFFF', 'BgField': '#FAFAFB',
    'BgBar': '#E4E4E8', 'Edge': '#C8C8CE', 'EdgeWindow': '#A9A9B0',
    'Text': '#1E1E22', 'TextMuted': '#5F5F67', 'Blue': '#1B72BE',
    'Orange': '#B96A12', 'Green': '#2E8546', 'GreenHover': '#379B53',
    'Red': '#C0392B', 'Selection': '#CFE3F5', 'Hover': '#E2E2E8',
    'OnAccent': '#FFFFFF', 'RowOk': '#E3F2E7', 'RowWarn': '#FBEEDC',
    'RowBad': '#F8E0DE', 'RowQuiet': '#ECECF0',
}

PALETTES = {'dark': DARK, 'light': LIGHT}


def palette(mode):
    return PALETTES.get(mode, DARK)


def revit_theme(ui_module=None):
    """'dark' or 'light' as Revit is drawing its canvas, or None if it cannot
    say (Revit before 2024 has no UIThemeManager).

    UITheme.Dark is 0, so the value is tested with `is not None` and read by
    name - a truthiness test reports Dark as a failed read.
    """
    if ui_module is None:
        try:
            import Autodesk.Revit.UI as ui_module
        except Exception:
            return None
    manager = getattr(ui_module, 'UIThemeManager', None)
    if manager is None:
        return None
    for attribute in ('CurrentCanvasTheme', 'CurrentTheme'):
        try:
            value = getattr(manager, attribute)
        except Exception:
            continue
        if value is not None:
            name = u'{0}'.format(value).lower()
            if 'light' in name:
                return 'light'
            if 'dark' in name:
                return 'dark'
    return None


def resolve(mode, ui_module=None):
    """The palette to draw: a pinned choice, else Revit's canvas, else dark."""
    if mode in PALETTES:
        return mode
    return revit_theme(ui_module) or 'dark'


def chip_label(mode, resolved):
    if mode in PALETTES:
        return u'Dark' if resolved == 'dark' else u'Light'
    return u'Auto'


def chip_tooltip(mode, resolved):
    if mode in PALETTES:
        return u'{0} theme, pinned. Click to change.'.format(chip_label(mode, resolved))
    return (u'Following Revit\'s canvas - {0} at the moment. '
            u'Click to pin dark, then light, then back to following.').format(resolved)
