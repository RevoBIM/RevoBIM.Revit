# -*- coding: utf-8 -*-
"""The dark and light palettes.

Every brush key in Theme.xaml appears in both palettes; the bench check
enforces that.  theme.apply writes the chosen palette straight onto
window.Resources, which sits in front of a merged dictionary in WPF's lookup
order, so the palette can be swapped on an open window with no reload.
"""

import tle_clr  # noqa: F401  assemblies first

from System.Windows.Media import SolidColorBrush, ColorConverter

KEYS = (
    "WindowBackBrush",
    "CardBrush",
    "FieldBrush",
    "BarBrush",
    "EdgeBrush",
    "TextBrush",
    "MutedBrush",
    "DisabledBrush",
    "BlueBrush",
    "OrangeBrush",
    "GreenBrush",
    "GreenHoverBrush",
    "RedBrush",
    "SelectionBrush",
    "HoverBrush",
)

DARK = {
    "WindowBackBrush": "#232326",
    "CardBrush": "#2B2B2E",
    "FieldBrush": "#1C1C1F",
    "BarBrush": "#1C1C1F",
    "EdgeBrush": "#3E3E42",
    "TextBrush": "#E4E4E4",
    "MutedBrush": "#9A9A9E",
    "DisabledBrush": "#6A6A70",
    "BlueBrush": "#4FA3E3",
    "OrangeBrush": "#E8912D",
    "GreenBrush": "#3FA75A",
    "GreenHoverBrush": "#4EC06D",
    "RedBrush": "#D9534F",
    "SelectionBrush": "#2B5473",
    "HoverBrush": "#34343A",
}

# Not the dark palette inverted: the accents are darkened, because the dark
# palette's accents are chosen to sit on near black and wash out on white.
LIGHT = {
    "WindowBackBrush": "#F4F4F6",
    "CardBrush": "#FFFFFF",
    "FieldBrush": "#FFFFFF",
    "BarBrush": "#E8E8EC",
    "EdgeBrush": "#C9C9CF",
    "TextBrush": "#1E1E20",
    "MutedBrush": "#65656C",
    "DisabledBrush": "#A0A0A6",
    "BlueBrush": "#1B72BE",
    "OrangeBrush": "#B96A12",
    "GreenBrush": "#2E8546",
    "GreenHoverBrush": "#3FA75A",
    "RedBrush": "#C0392B",
    "SelectionBrush": "#CFE2F3",
    "HoverBrush": "#E4E4E8",
}

PALETTES = {"dark": DARK, "light": LIGHT}


def brush(hex_value):
    return SolidColorBrush(ColorConverter.ConvertFromString(hex_value))


def palette(name):
    return PALETTES.get(str(name).lower(), DARK)


def apply(window, name):
    """Write the palette onto the window's own resources."""
    values = palette(name)
    for key in KEYS:
        try:
            window.Resources[key] = brush(values[key])
        except Exception:
            pass
    return values


def other(name):
    return "light" if str(name).lower() == "dark" else "dark"
