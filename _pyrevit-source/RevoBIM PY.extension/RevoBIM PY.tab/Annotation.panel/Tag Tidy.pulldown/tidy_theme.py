# -*- coding: utf-8 -*-
"""The dark and light palettes, and following Revit's canvas.

Dark is Revit's own dark theme (sampled from Revit's dark Project Browser), as
Project Browser Pro, Filter Manager and Pro Sheets Exporter use, with muted
text and blue lifted so they read on the lighter body.  Light is the house
light palette, its accents darkened so they do not wash out on white.

Every brush key in Theme.xaml appears in both palettes; the bench check
enforces that, and that Theme.xaml's baked-in defaults are the dark palette, so
a window never flashes the wrong colours before the palette lands.  apply()
writes the chosen palette straight onto window.Resources, which sits in front
of a merged dictionary in WPF's lookup order, so it can be swapped on an open
window with no reload.
"""

import tidy_clr  # noqa: F401  assemblies first

from System.Windows.Media import SolidColorBrush, ColorConverter

import tidy_core as core

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
    "WindowBackBrush": "#3C4454",   # Revit body
    "CardBrush": "#323C48",         # Revit table headings / chips
    "FieldBrush": "#2D3441",        # Revit search boxes and fields
    "BarBrush": "#222933",          # Revit title bar
    "EdgeBrush": "#515C6B",         # Revit window edge
    "TextBrush": "#EEF0F4",
    "MutedBrush": "#A4AAB1",
    "DisabledBrush": "#7A828E",
    "BlueBrush": "#5AAEEB",
    "OrangeBrush": "#E8912D",
    "GreenBrush": "#3FA75A",
    "GreenHoverBrush": "#4EC06D",
    "RedBrush": "#D9534F",
    "SelectionBrush": "#3A7392",    # Revit's active blue
    "HoverBrush": "#444E5E",
}

# Not the dark palette inverted: the accents are darkened, because accents
# chosen to sit on a dark body wash out on white.
LIGHT = {
    "WindowBackBrush": "#F4F4F6",
    "CardBrush": "#FFFFFF",
    "FieldBrush": "#FFFFFF",
    "BarBrush": "#E8E8EC",
    "EdgeBrush": "#C9C9CF",
    "TextBrush": "#1E1E20",
    "MutedBrush": "#5E5E66",
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


def canvas():
    """Revit's canvas theme, "dark" or "light", or None before Revit 2024.

    UIThemeManager only exists from Revit 2024, so it is reached by getattr on
    the namespace rather than imported at the top.  UITheme.Dark is 0, so the
    read is tested with `is not None`, never for truthiness.
    """
    try:
        import Autodesk.Revit.UI as revit_ui
    except Exception:
        return None
    try:
        manager = getattr(revit_ui, "UIThemeManager", None)
    except Exception:
        manager = None
    if manager is None:
        return None
    for name in ("CurrentCanvasTheme", "CurrentTheme"):
        try:
            raw = getattr(manager, name)
        except Exception:
            continue
        if raw is not None:
            found = core.canvas_name(raw)
            if found is not None:
                return found
    return None


def resolve(setting):
    """The palette a setting paints right now: follow reads the canvas."""
    return core.resolve_theme(setting, canvas() if setting not in ("dark", "light") else None)


def apply(window, name):
    """Write the palette onto the window's own resources."""
    values = palette(name)
    for key in KEYS:
        try:
            window.Resources[key] = brush(values[key])
        except Exception:
            pass
    return values
