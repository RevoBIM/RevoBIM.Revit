# -*- coding: utf-8 -*-
# ==========================================================
# RevoBIM System Offset - dark and light palettes
#
# The light palette is not the dark one inverted. The dark
# accents are chosen to sit on near black and wash out on
# white, so they are darkened rather than reused.
# ==========================================================

import so_clr  # noqa: F401  assembly references first

from System.Windows.Media import Color, ColorConverter, SolidColorBrush


DARK = {
    'WindowBg':      '#232326',
    'CardBg':        '#2B2B2E',
    'FieldBg':       '#1C1C1F',
    'BarBg':         '#1C1C1F',
    'EdgeBrush':     '#3E3E42',
    'BodyText':      '#E4E4E4',
    'MutedText':     '#9A9A9E',
    'Blue':          '#4FA3E3',
    'Orange':        '#E8912D',
    'Green':         '#3FA75A',
    'GreenHover':    '#4EC06D',
    'Red':           '#D9534F',
    'Selection':     '#2B5473',
    'HoverBg':       '#34343A',
    'DisabledText':  '#66666B',
}

LIGHT = {
    'WindowBg':      '#F2F2F4',
    'CardBg':        '#FFFFFF',
    'FieldBg':       '#FFFFFF',
    'BarBg':         '#E4E4E8',
    'EdgeBrush':     '#C4C4CA',
    'BodyText':      '#1E1E20',
    'MutedText':     '#5E5E66',
    'Blue':          '#1B72BE',
    'Orange':        '#B96A12',
    'Green':         '#2E8546',
    'GreenHover':    '#3AA059',
    'Red':           '#B5322E',
    'Selection':     '#BBD8F0',
    'HoverBg':       '#E8E8EC',
    'DisabledText':  '#A0A0A8',
}

PALETTES = {'dark': DARK, 'light': LIGHT}

# Every key both palettes must carry. The bench check proves
# neither palette is missing one.
KEYS = tuple(sorted(DARK.keys()))


def brush(hex_text):
    """A frozen SolidColorBrush from a #RRGGBB string."""
    color = ColorConverter.ConvertFromString(hex_text)
    if not isinstance(color, Color):
        color = Color.FromRgb(0, 0, 0)
    result = SolidColorBrush(color)
    result.Freeze()
    return result


def revit_theme():
    """Which theme Revit's own canvas is using right now.

    UIThemeManager arrived in 2024 and the canvas specific
    property is not on every release, so both are tried and
    a failure falls back to dark rather than throwing.
    """
    try:
        from Autodesk.Revit.UI import UIThemeManager, UITheme
    except Exception:
        return 'dark'

    for attr in ('CurrentCanvasTheme', 'CurrentTheme'):
        try:
            value = getattr(UIThemeManager, attr)
        except Exception:
            continue
        try:
            if value == UITheme.Light:
                return 'light'
            if value == UITheme.Dark:
                return 'dark'
        except Exception:
            # Some releases hand back a plain int
            try:
                return 'light' if int(value) == 1 else 'dark'
            except Exception:
                continue
    return 'dark'


def resolve(setting):
    """Turn the saved setting into a real palette name.

    'revit' follows Revit's canvas, which is the default.
    """
    text = (setting or 'revit').strip().lower()
    if text in ('dark', 'light'):
        return text
    return revit_theme()


def apply(window, name):
    """Write a palette's brushes straight onto window.Resources.

    window.Resources sits in front of a merged dictionary in
    WPF's lookup order, so the palette can be swapped on an
    open window with no reload and no loss of state.
    """
    palette = PALETTES.get(name, DARK)
    for key in KEYS:
        try:
            window.Resources[key] = brush(palette[key])
        except Exception:
            pass
    return name


def next_theme(current):
    """The chip in the header cycles Follow Revit, Dark, Light."""
    order = ('revit', 'dark', 'light')
    try:
        return order[(order.index(current) + 1) % len(order)]
    except ValueError:
        return 'dark'


def chip_label(setting):
    return {'revit': u'Auto', 'dark': u'Dark', 'light': u'Light'}.get(setting, u'Auto')
