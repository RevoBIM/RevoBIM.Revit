# -*- coding: utf-8 -*-
"""RevoBIM Match Offset - the dark and light palettes.

The light palette is not the dark one inverted: the accents are darkened,
because the dark palette's blue, orange and green are chosen to sit on
near-black and wash out on white.
"""

import mo_clr  # noqa: F401

from mo_core import to_text

AUTO = u"auto"
DARK = u"dark"
LIGHT = u"light"
CYCLE = (AUTO, DARK, LIGHT)

CHIP_LABEL = {AUTO: u"Auto", DARK: u"Dark", LIGHT: u"Light"}

DARK_PALETTE = {
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
    u"SelectBrush": u"#2B5473",
    u"HoverBrush": u"#33333A",
    u"DisabledBrush": u"#55555C",
}

LIGHT_PALETTE = {
    u"WindowBrush": u"#F2F2F4",
    u"CardBrush": u"#FFFFFF",
    u"FieldBrush": u"#FFFFFF",
    u"BarBrush": u"#E6E6EA",
    u"EdgeBrush": u"#C6C6CC",
    u"TextBrush": u"#1E1E20",
    u"MutedBrush": u"#63636A",
    u"BlueBrush": u"#1B72BE",
    u"OrangeBrush": u"#B96A12",
    u"GreenBrush": u"#2E8546",
    u"GreenHoverBrush": u"#3A9E56",
    u"RedBrush": u"#B23430",
    u"SelectBrush": u"#BFD8EE",
    u"HoverBrush": u"#E4E4EA",
    u"DisabledBrush": u"#A8A8B0",
}

PALETTES = {DARK: DARK_PALETTE, LIGHT: LIGHT_PALETTE}


def next_in_cycle(current):
    """The chip cycles Auto, then Dark, then Light, then back to Auto."""
    mode = to_text(current).strip().lower()
    if mode not in CYCLE:
        return DARK
    return CYCLE[(CYCLE.index(mode) + 1) % len(CYCLE)]


def revit_theme():
    """Whichever way Revit's own canvas is set, dark or light.

    UIThemeManager arrived in Revit 2024, which is the oldest release this
    extension supports, so the import is inside a try/except only because a
    future release moving it must not take the tool down with it.
    """
    try:
        from Autodesk.Revit.UI import UIThemeManager
    except Exception:
        return DARK
    for attribute in ('CurrentCanvasTheme', 'CurrentTheme'):
        try:
            value = to_text(getattr(UIThemeManager, attribute)).lower()
        except Exception:
            continue
        if u"dark" in value:
            return DARK
        if u"light" in value:
            return LIGHT
    return DARK


def resolve(mode):
    """The palette name a setting of auto, dark or light actually means."""
    chosen = to_text(mode).strip().lower()
    if chosen == LIGHT:
        return LIGHT
    if chosen == DARK:
        return DARK
    return revit_theme()


def palette(mode):
    return PALETTES.get(resolve(mode), DARK_PALETTE)


def apply(window, mode):
    """Write the palette straight onto window.Resources.

    That sits in front of a merged dictionary in WPF's lookup order, so the
    palette can be swapped on an open window with no reload and no loss of
    state - which is what makes the chip instant.
    """
    from System.Windows.Media import SolidColorBrush, ColorConverter
    chosen = palette(mode)
    for key, hex_value in chosen.items():
        try:
            colour = ColorConverter.ConvertFromString(hex_value)
            window.Resources[key] = SolidColorBrush(colour)
        except Exception:
            continue
    return resolve(mode)


def keys_match():
    """Both palettes carry the same keys. The bench check proves it."""
    return set(DARK_PALETTE.keys()) == set(LIGHT_PALETTE.keys())
