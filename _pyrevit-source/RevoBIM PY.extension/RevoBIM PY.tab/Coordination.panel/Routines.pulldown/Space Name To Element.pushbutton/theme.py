# -*- coding: utf-8 -*-
"""The dark and light palettes.

Every brush the layouts ask for by DynamicResource has a key here, and
snte_ui.apply_theme writes them straight onto window.Resources - which sits in
front of a merged dictionary in WPF's lookup order, so the palette can be
swapped on an open window with no reload and no loss of state.
"""

import snte_clr  # noqa: F401  - must be first

DARK = {
    "WinBg": "#232326",
    "CardBg": "#2B2B2E",
    "FieldBg": "#1C1C1F",
    "BarBg": "#1C1C1F",
    "EdgeBrush": "#3E3E42",
    "EdgeSoft": "#4A4A50",
    "TextBrush": "#E4E4E4",
    "DimBrush": "#9A9A9E",
    "GhostBrush": "#7A7A80",
    "BlueBrush": "#4FA3E3",
    "BlueSoft": "#2B5473",
    "OrangeBrush": "#E8912D",
    "OrangeHover": "#F3A44A",
    "GreenBrush": "#3FA75A",
    "GreenHover": "#4EC06D",
    "RedBrush": "#D9534F",
    "SelBrush": "#2B5473",
    "HoverBg": "#34343A",
    "FgOnAccent": "#1B1B1E",
    "TrackBg": "#1C1C1F",
    "ThumbBg": "#5A5A62",
}

LIGHT = {
    "WinBg": "#F2F2F4",
    "CardBg": "#FFFFFF",
    "FieldBg": "#FFFFFF",
    "BarBg": "#E4E4E9",
    "EdgeBrush": "#C8C8CE",
    "EdgeSoft": "#B4B4BC",
    "TextBrush": "#1E1E20",
    "DimBrush": "#63636A",
    "GhostBrush": "#8A8A92",
    "BlueBrush": "#1B72BE",
    "BlueSoft": "#BBD6EE",
    "OrangeBrush": "#B96A12",
    "OrangeHover": "#D07E22",
    "GreenBrush": "#2E8546",
    "GreenHover": "#3B9C57",
    "RedBrush": "#B23A37",
    "SelBrush": "#BBD6EE",
    "HoverBg": "#E2E2E8",
    "FgOnAccent": "#FFFFFF",
    "TrackBg": "#E8E8EC",
    "ThumbBg": "#B0B0B8",
}

PALETTES = {"dark": DARK, "light": LIGHT}

KEYS = sorted(DARK.keys())


def palette(name):
    return PALETTES.get((name or "dark").lower(), DARK)


def other(name):
    return "light" if (name or "dark").lower() == "dark" else "dark"
