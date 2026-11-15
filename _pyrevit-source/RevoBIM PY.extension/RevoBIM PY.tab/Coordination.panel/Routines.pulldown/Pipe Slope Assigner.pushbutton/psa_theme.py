# -*- coding: utf-8 -*-
"""The dark and light palettes, and which one Revit is showing.

Every colour in the tool is one of these keys. The layouts only ever say
{DynamicResource Key}; apply() writes a SolidColorBrush for each key straight
onto window.Resources, which sits in front of the merged Theme.xaml in WPF's
lookup order, so the palette can be swapped on an open window with no reload.

The light palette is not the dark one inverted: the accents are darkened
because the dark palette's are chosen to sit on near-black and wash out on
white.
"""

import psa_clr  # noqa: F401  (assemblies before any System.* name)

MODES = ('auto', 'dark', 'light')

DARK = {
    'BgWindow': '#232326',
    'BgCard': '#2B2B2E',
    'BgField': '#1C1C1F',
    'BgBar': '#1C1C1F',
    'Hover': '#34343A',
    'Edge': '#3E3E42',
    'WindowEdge': '#4A4A50',
    'Text': '#E4E4E4',
    'TextMuted': '#9A9A9E',
    'TextOnAccent': '#FFFFFF',
    'Blue': '#4FA3E3',
    'Orange': '#E8912D',
    'OrangeWash': '#3A2D1E',
    'Green': '#3FA75A',
    'GreenHover': '#4EC06D',
    'Red': '#D9534F',
    'Select': '#2B5473',
}

LIGHT = {
    'BgWindow': '#F3F3F5',
    'BgCard': '#FFFFFF',
    'BgField': '#FFFFFF',
    'BgBar': '#E4E4E9',
    'Hover': '#E9E9EE',
    'Edge': '#C8C8CE',
    'WindowEdge': '#AEAEB6',
    'Text': '#1E1E22',
    'TextMuted': '#66666E',
    'TextOnAccent': '#FFFFFF',
    'Blue': '#1B72BE',
    'Orange': '#B96A12',
    'OrangeWash': '#FBEBD7',
    'Green': '#2E8546',
    'GreenHover': '#379A53',
    'Red': '#C0392B',
    'Select': '#CFE3F5',
}

PALETTES = {'dark': DARK, 'light': LIGHT}


def canvas_theme():
    """'dark' or 'light' from Revit's own canvas theme, or None.

    UIThemeManager only exists from Revit 2024, so it is reached by getattr on
    the namespace rather than imported at the top. UITheme.Dark is 0, so the
    read is tested with `is not None` and read by name - a truthiness test
    reports Dark as a failed read and falls through to Light.
    """
    try:
        import Autodesk.Revit.UI as revit_ui
        manager = getattr(revit_ui, 'UIThemeManager', None)
        if manager is None:
            return None
        value = None
        for prop in ('CurrentCanvasTheme', 'CurrentTheme'):
            try:
                value = getattr(manager, prop)
            except Exception:
                value = None
            if value is not None:
                break
        if value is None:
            return None
        name = str(value).lower()
        if 'dark' in name:
            return 'dark'
        if 'light' in name:
            return 'light'
    except Exception:
        pass
    return None


def resolve(mode):
    if mode in ('dark', 'light'):
        return mode
    return canvas_theme() or 'dark'


def palette(resolved):
    return dict(PALETTES.get(resolved, DARK))


def next_mode(mode):
    try:
        return MODES[(MODES.index(mode) + 1) % len(MODES)]
    except ValueError:
        return 'auto'


def chip_text(mode):
    resolved = resolve(mode)
    if mode == 'auto':
        return u'Auto \u00b7 {0}'.format(resolved.title())
    return resolved.title()


def apply(window, mode):
    """Write the palette onto the window. Cosmetic, so it can never throw."""
    try:
        from System.Windows.Media import SolidColorBrush, ColorConverter
        pal = palette(resolve(mode))
        for key, hexcode in pal.items():
            try:
                brush = SolidColorBrush(ColorConverter.ConvertFromString(hexcode))
                window.Resources[key] = brush
            except Exception:
                pass
        return True
    except Exception:
        return False
