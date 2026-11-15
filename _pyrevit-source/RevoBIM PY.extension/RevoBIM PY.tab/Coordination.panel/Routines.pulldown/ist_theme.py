# -*- coding: utf-8 -*-
u"""RevoBIM PY - Isolate Service Type : the dark and light palettes.

Every key here must have a brush of the same name in IstTheme.xaml, and every
brush there must appear here - the bench check proves it both ways.

The light palette is not the dark one inverted: the accents are darkened,
because the dark palette's accents are chosen to sit on near-black and wash
out on white.
"""

import ist_clr  # noqa: F401

from System.Windows.Media import BrushConverter

DARK = {
    u"WindowBrush": u"#232326",
    u"CardBrush": u"#2B2B2E",
    u"FieldBrush": u"#1C1C1F",
    u"BarBrush": u"#1C1C1F",
    u"EdgeBrush": u"#3E3E42",
    u"TextBrush": u"#E4E4E4",
    u"MutedBrush": u"#9A9A9E",
    u"BlueBrush": u"#4FA3E3",
    u"OrangeBrush": u"#E8912D",
    u"GreenBrush": u"#3FA75A",
    u"GreenHoverBrush": u"#4EC06D",
    u"RedBrush": u"#D9534F",
    u"SelectionBrush": u"#2B5473",
    u"HoverBrush": u"#33333A",
    u"ChromeBrush": u"#4A4A50",
}

LIGHT = {
    u"WindowBrush": u"#F2F2F4",
    u"CardBrush": u"#FFFFFF",
    u"FieldBrush": u"#FFFFFF",
    u"BarBrush": u"#E4E4E8",
    u"EdgeBrush": u"#C6C6CC",
    u"TextBrush": u"#1E1E20",
    u"MutedBrush": u"#61616A",
    u"BlueBrush": u"#1B72BE",
    u"OrangeBrush": u"#B96A12",
    u"GreenBrush": u"#2E8546",
    u"GreenHoverBrush": u"#37A055",
    u"RedBrush": u"#B33B37",
    u"SelectionBrush": u"#BDD7EE",
    u"HoverBrush": u"#E8E8EE",
    u"ChromeBrush": u"#B4B4BA",
}

PALETTES = {u"dark": DARK, u"light": LIGHT}


def palette(name):
    return PALETTES.get((name or u"dark").strip().lower(), DARK)


def apply(window, name):
    u"""Write the palette straight onto window.Resources, which sits in front
    of a merged dictionary in WPF's lookup order - so the palette can be
    swapped on an open window with no reload and no loss of state."""
    converter = BrushConverter()
    for key, hex_value in palette(name).items():
        try:
            window.Resources[key] = converter.ConvertFromString(hex_value)
        except Exception:
            continue
