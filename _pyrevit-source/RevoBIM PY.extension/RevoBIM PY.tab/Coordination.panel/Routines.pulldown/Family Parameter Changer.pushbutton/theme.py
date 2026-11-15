# -*- coding: utf-8 -*-
"""RevoBIM PY - Family Parameter Changer - dark and light palettes.

Applied by writing straight onto window.Resources, which sits in front of
the merged Theme.xaml dictionary in WPF's lookup order - so the palette
can be swapped on an open window with no reload and no loss of state.

The light palette is not the dark one inverted: the accents are darkened
(#4FA3E3 -> #1B72BE, #E8912D -> #B96A12, #3FA75A -> #2E8546) because the
dark palette's accents are chosen to sit on near-black and wash out on
white.

Every key here must have a matching brush in Theme.xaml and vice versa -
import_check.py enforces both directions.
"""
import fpc_clr  # noqa - assemblies referenced before anything below

PALETTES = {
    'dark': {
        'WindowBg': '#232326',
        'CardBg': '#2B2B2E',
        'FieldBg': '#1C1C1F',
        'BarBg': '#1C1C1F',
        'EdgeBrush': '#3E3E42',
        'TextBrush': '#E4E4E4',
        'MutedTextBrush': '#9A9A9E',
        'BlueBrush': '#4FA3E3',
        'OrangeBrush': '#E8912D',
        'GreenBrush': '#3FA75A',
        'GreenHoverBrush': '#4EC06D',
        'RedBrush': '#D9534F',
        'SelectionBrush': '#2B5473',
        'WindowEdgeBrush': '#4A4A50',
        'ScrollThumbBrush': '#4A4A50',
        'ScrollThumbHoverBrush': '#5E5E66',
    },
    'light': {
        'WindowBg': '#F2F2F4',
        'CardBg': '#FFFFFF',
        'FieldBg': '#FFFFFF',
        'BarBg': '#E7E7EA',
        'EdgeBrush': '#C9C9CE',
        'TextBrush': '#232326',
        'MutedTextBrush': '#6B6B70',
        'BlueBrush': '#1B72BE',
        'OrangeBrush': '#B96A12',
        'GreenBrush': '#2E8546',
        'GreenHoverBrush': '#37995A',
        'RedBrush': '#B3413D',
        'SelectionBrush': '#CBE0F0',
        'WindowEdgeBrush': '#B7B7BC',
        'ScrollThumbBrush': '#BFBFC5',
        'ScrollThumbHoverBrush': '#A2A2A9',
    },
}


def apply(window, theme_name):
    """Writes the named palette's brushes onto window.Resources so the
    swap takes effect immediately, with no reload and no loss of state."""
    from System.Windows.Media import SolidColorBrush, ColorConverter

    palette = PALETTES.get(theme_name, PALETTES['dark'])
    for key in palette:
        try:
            color = ColorConverter.ConvertFromString(palette[key])
            brush = SolidColorBrush(color)
            brush.Freeze()
            window.Resources[key] = brush
        except Exception:
            continue
    return palette


def other(theme_name):
    """The palette name the toggle should switch to."""
    return 'light' if theme_name == 'dark' else 'dark'
