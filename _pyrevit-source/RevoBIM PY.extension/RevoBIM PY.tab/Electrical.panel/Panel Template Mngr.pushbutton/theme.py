# -*- coding: utf-8 -*-
"""RevoBIM PY - shared dark / light palette for Panel Template Mngr.

Every brush key defined here must also be referenced by name in Theme.xaml, and
Theme.xaml may only be referenced from layout files with DynamicResource, never
StaticResource.  theme.apply() writes the chosen palette's brushes straight onto
window.Resources, which sits in front of a merged dictionary in WPF's lookup
order - so the palette can be swapped on an open window with no reload and no
loss of state.

Runs on IronPython 2.7 and IronPython 3: no f-strings, no print statements.
"""

import pstm_clr                                                  # noqa: F401

from System.Windows.Media import SolidColorBrush, ColorConverter  # noqa: E402


DARK = {
    'name': 'dark',

    # Surfaces
    'WindowBg': '#232326',
    'CardBg': '#2B2B2E',
    'FieldBg': '#1C1C1F',
    'BarBg': '#1C1C1F',
    'PopupBg': '#2B2B2E',
    'ChipBg': '#33333A',

    # Edges
    'EdgeBrush': '#3E3E42',
    'WindowEdge': '#4A4A50',
    'GridLine': '#37373C',

    # Text
    'TextBrush': '#E4E4E4',
    'MutedBrush': '#9A9A9E',
    'DisabledBrush': '#68686E',

    # Accents
    'BlueBrush': '#4FA3E3',
    'OrangeBrush': '#E8912D',
    'OrangeHoverBrush': '#F5A648',
    'GreenBrush': '#3FA75A',
    'GreenHoverBrush': '#4EC06D',
    'RedBrush': '#D9534F',
    'RedHoverBrush': '#E7706C',

    # Interaction
    'SelectionBrush': '#2B5473',
    'HoverBrush': '#34343A',
    'RowAltBrush': '#26262A',
    'ScrollThumb': '#4A4A50',
    'ScrollThumbHover': '#5E5E66',

    # Row / cell states
    'ChangedBg': '#4A3418',      # a change waiting for Apply
    'ChangedEdge': '#E8912D',
    'ReviewBg': '#4A2422',       # Auto Assign could not find a template
    'ReviewEdge': '#D9534F',
    'MatchedBg': '#1F3A28',      # Auto Assign found a clean match
    'MatchedEdge': '#3FA75A',
    'UnusedBg': '#2F2F34',       # template not used anywhere in the project
}


LIGHT = {
    'name': 'light',

    'WindowBg': '#F1F1F4',
    'CardBg': '#FFFFFF',
    'FieldBg': '#FFFFFF',
    'BarBg': '#E3E3E8',
    'PopupBg': '#FFFFFF',
    'ChipBg': '#D8D8DE',

    'EdgeBrush': '#C6C6CC',
    'WindowEdge': '#B0B0B8',
    'GridLine': '#DCDCE2',

    'TextBrush': '#1F1F22',
    'MutedBrush': '#5F5F68',
    'DisabledBrush': '#9A9AA2',

    # The dark palette's accents are picked to sit on near-black and wash out on
    # white, so the light palette darkens them rather than reusing them.
    'BlueBrush': '#1B72BE',
    'OrangeBrush': '#B96A12',
    'OrangeHoverBrush': '#D07C1D',
    'GreenBrush': '#2E8546',
    'GreenHoverBrush': '#379B53',
    'RedBrush': '#B33A36',
    'RedHoverBrush': '#C7514D',

    'SelectionBrush': '#BCD9F2',
    'HoverBrush': '#E8E8EE',
    'RowAltBrush': '#F7F7FA',
    'ScrollThumb': '#BFBFC6',
    'ScrollThumbHover': '#A2A2AA',

    'ChangedBg': '#FCEBD2',
    'ChangedEdge': '#B96A12',
    'ReviewBg': '#F8D9D8',
    'ReviewEdge': '#B33A36',
    'MatchedBg': '#D9EEDF',
    'MatchedEdge': '#2E8546',
    'UnusedBg': '#EAEAEF',
}


PALETTES = {'dark': DARK, 'light': LIGHT}

# Every key that is a colour (i.e. everything except 'name').  Theme.xaml has to
# declare a brush for each of these, and import_check.py checks that it does.
BRUSH_KEYS = sorted([k for k in DARK.keys() if k != 'name'])


def palette(name):
    """Return the named palette, falling back to dark."""
    return PALETTES.get(str(name).lower(), DARK)


def brush(hex_value):
    """SolidColorBrush from a #RRGGBB string, frozen so it can cross threads."""
    b = SolidColorBrush(ColorConverter.ConvertFromString(hex_value))
    try:
        b.Freeze()
    except Exception:
        pass
    return b


def hex_of(name, key):
    """Raw hex string for a key in the named palette."""
    return palette(name).get(key, DARK.get(key, '#FF00FF'))


def apply(window, name):
    """Write the named palette's brushes onto the window's own resources.

    Anything decorative is allowed to fail quietly - cosmetics must never take
    a tool down.
    """
    pal = palette(name)
    for key in BRUSH_KEYS:
        try:
            window.Resources[key] = brush(pal[key])
        except Exception:
            pass
    return pal['name']


def other(name):
    """The palette that is not the one named."""
    if str(name).lower() == 'light':
        return 'dark'
    return 'light'
