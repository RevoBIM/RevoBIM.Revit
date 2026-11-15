# -*- coding: utf-8 -*-
"""Find in View - the dark and light palettes.

The palette is written straight onto window.Resources, which sits in front of a
merged dictionary in WPF's lookup order, so it can be swapped on an open window
with no reload and no loss of state.

The light palette is not the dark one inverted: the accents are darkened,
because the dark palette's accents are chosen to sit on near black and wash out
on white.
"""

import fiv_clr  # noqa: F401 - must be first, it holds the clr.AddReference calls

from System.Windows.Media import SolidColorBrush, ColorConverter

DARK = {
    'WindowBg':      '#232326',
    'CardBg':        '#2B2B2E',
    'FieldBg':       '#1C1C1F',
    'BarBg':         '#1C1C1F',
    'EdgeBrush':     '#3E3E42',
    'ChromeEdge':    '#4A4A50',
    'TextBrush':     '#E4E4E4',
    'MutedBrush':    '#9A9A9E',
    'BlueBrush':     '#4FA3E3',
    'OrangeBrush':   '#E8912D',
    'GreenBrush':    '#3FA75A',
    'GreenHover':    '#4EC06D',
    'RedBrush':      '#D9534F',
    'SelectionBg':   '#2B5473',
    'HoverBg':       '#34343A',
    'DisabledBg':    '#303035',
    'DisabledText':  '#6E6E74',
}

LIGHT = {
    'WindowBg':      '#F2F2F4',
    'CardBg':        '#FFFFFF',
    'FieldBg':       '#FFFFFF',
    'BarBg':         '#E4E4E8',
    'EdgeBrush':     '#C6C6CC',
    'ChromeEdge':    '#B4B4BA',
    'TextBrush':     '#1F1F22',
    'MutedBrush':    '#63636A',
    'BlueBrush':     '#1B72BE',
    'OrangeBrush':   '#B96A12',
    'GreenBrush':    '#2E8546',
    'GreenHover':    '#3FA75A',
    'RedBrush':      '#B4302C',
    'SelectionBg':   '#BCD8F0',
    'HoverBg':       '#E8E8EC',
    'DisabledBg':    '#DEDEE2',
    'DisabledText':  '#9A9AA0',
}

PALETTES = {'dark': DARK, 'light': LIGHT}


def palette(name):
    return PALETTES.get((name or 'dark').lower(), DARK)


def brush(hex_value):
    return SolidColorBrush(ColorConverter.ConvertFromString(hex_value))


def apply(window, name):
    """Write every palette brush onto the window's own resource dictionary."""
    values = palette(name)
    for key in values:
        try:
            window.Resources[key] = brush(values[key])
        except Exception:
            pass
    return values


def other(name):
    return 'light' if (name or 'dark').lower() == 'dark' else 'dark'
