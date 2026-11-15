# -*- coding: utf-8 -*-
"""Schematic Builder - the dark and light palettes.

Dark is **Revit's own dark theme**, sampled from Revit's dark Project
Browser, so the windows sit inside Revit's greys rather than beside them.
The muted grey, blue, orange and red are lifted from the house values: on
Revit's lighter body the house accents fall under 4:1 contrast, and the
bench holds every text colour to that.

Light is the house light palette, its accents darkened rather than
inverted, since accents picked for a dark body wash out on white.

Every key here must have a brush in Theme.xaml (the bench enforces it), and
Theme.xaml's own default brushes carry the dark values, so a window never
flashes the wrong colours before the palette lands.
"""

DARK = {
    "ShellBg": "#3C4454",       # Revit window body
    "PanelBg": "#323C48",       # Revit table headings / chips - cards
    "FieldBg": "#2D3441",       # Revit search boxes and fields
    "BarBg": "#222933",         # Revit title bar
    "EdgeBrush": "#515C6B",     # Revit window edge
    "LineBrush": "#48525F",
    "TextBrush": "#EEF0F4",
    "DimBrush": "#ADB3BA",
    "BlueBrush": "#62B6F0",
    "OrangeBrush": "#F0A048",
    "GreenBrush": "#3FA75A",
    "GreenHover": "#4EC06D",
    "RedBrush": "#FF948C",
    "SelBrush": "#3A7392",      # Revit's active blue
    "HoverBrush": "#444E5E",
    "ButtonBg": "#46505F",
    "ButtonHover": "#515C6B",
    "DisabledText": "#7A8290",
    "PlaceholderBrush": "#8E96A1",
}

LIGHT = {
    "ShellBg": "#F3F3F5",
    "PanelBg": "#FFFFFF",
    "FieldBg": "#FAFAFC",
    "BarBg": "#E6E6EA",
    "EdgeBrush": "#B8B8BE",
    "LineBrush": "#D2D2D8",
    "TextBrush": "#202024",
    "DimBrush": "#6A6A72",
    "BlueBrush": "#1B72BE",
    "OrangeBrush": "#9C560B",
    "GreenBrush": "#2E8546",
    "GreenHover": "#3A9A55",
    "RedBrush": "#C0392B",
    "SelBrush": "#CFE3F5",
    "HoverBrush": "#E9EDF3",
    "ButtonBg": "#E4E6EB",
    "ButtonHover": "#D5D9E1",
    "DisabledText": "#A0A0A8",
    "PlaceholderBrush": "#8A8A92",
}

PALETTES = {"dark": DARK, "light": LIGHT}

# what the theme setting can say; "follow" tracks Revit's canvas
MODES = ("follow", "dark", "light")

# text colours and the backgrounds they are drawn on, held to MIN_CONTRAST by
# import_check.py
TEXT_KEYS = ("TextBrush", "DimBrush", "BlueBrush", "OrangeBrush", "RedBrush")
BODY_KEYS = ("ShellBg", "PanelBg", "FieldBg", "BarBg")
MIN_CONTRAST = 4.0


def palette(name):
    return PALETTES.get(str(name).lower(), DARK)


def resolve(setting, canvas):
    """The palette to use: an explicit dark or light wins; otherwise follow
    Revit's canvas, and dark when the canvas could not be read."""
    setting = str(setting or "").lower()
    if setting in PALETTES:
        return setting
    canvas = str(canvas or "").lower()
    return canvas if canvas in PALETTES else "dark"


def other(name):
    return "light" if str(name).lower() == "dark" else "dark"
