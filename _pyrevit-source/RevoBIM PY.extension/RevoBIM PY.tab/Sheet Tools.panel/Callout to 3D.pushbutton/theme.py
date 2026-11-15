# -*- coding: utf-8 -*-
"""Callout to 3D - the dark and light palettes.

The palette is written straight onto ``window.Resources``, which sits in front
of a merged dictionary in WPF's lookup order, so it can be swapped on an open
window with no reload and no loss of state.

The light palette is not the dark one inverted: the accents are darkened,
because the dark palette's accents are chosen to sit on near black and wash
out on white.
"""

import c3d_clr  # noqa: F401  assemblies first, always

import c3d_core as core

from System.Windows.Media import SolidColorBrush, ColorConverter   # noqa: E402

DARK = {
    "WindowBrush": "#232326",
    "CardBrush": "#2B2B2E",
    "FieldBrush": "#1C1C1F",
    "BarBrush": "#1C1C1F",
    "EdgeBrush": "#3E3E42",
    "FrameBrush": "#4A4A50",
    "TextBrush": "#E4E4E4",
    "MutedBrush": "#9A9A9E",
    "BlueBrush": "#4FA3E3",
    "OrangeBrush": "#E8912D",
    "GreenBrush": "#3FA75A",
    "GreenHoverBrush": "#4EC06D",
    "RedBrush": "#D9534F",
    "SelectionBrush": "#2B5473",
    "HoverBrush": "#33333A",
    "RowBrush": "#2B2B2E",
    "RowAltBrush": "#27272A",
    "GridLineBrush": "#38383D",
    "TransparentHitBrush": "#01000000",
    "PreviewInkBrush": "#9A9A9E",
    "PreviewFillBrush": "#1C1C1F",
}

LIGHT = {
    "WindowBrush": "#F2F2F3",
    "CardBrush": "#FFFFFF",
    "FieldBrush": "#FFFFFF",
    "BarBrush": "#E4E4E6",
    "EdgeBrush": "#C6C6CA",
    "FrameBrush": "#B4B4BA",
    "TextBrush": "#1F1F22",
    "MutedBrush": "#63636A",
    "BlueBrush": "#1B72BE",
    "OrangeBrush": "#B96A12",
    "GreenBrush": "#2E8546",
    "GreenHoverBrush": "#3AA057",
    "RedBrush": "#B23B38",
    "SelectionBrush": "#BBD8F0",
    "HoverBrush": "#E8EEF4",
    "RowBrush": "#FFFFFF",
    "RowAltBrush": "#F5F5F7",
    "GridLineBrush": "#D8D8DC",
    "TransparentHitBrush": "#01000000",
    "PreviewInkBrush": "#63636A",
    "PreviewFillBrush": "#FFFFFF",
}

PALETTES = {"dark": DARK, "light": LIGHT}

KEYS = sorted(DARK.keys())


def brush(hex_value):
    return SolidColorBrush(ColorConverter.ConvertFromString(hex_value))


def palette(name):
    return PALETTES.get((name or "dark").strip().lower(), DARK)


def apply(window, name):
    """Write every brush onto the window's own resources."""
    values = palette(name)
    for key in KEYS:
        try:
            window.Resources[key] = brush(values[key])
        except Exception:
            pass
    return values


def revit_canvas_theme():
    """Revit's own canvas light/dark setting, so the tool opens matching the
    model behind it.

    ``UIThemeManager.CurrentCanvasTheme`` is the canvas one and
    ``CurrentTheme`` the ribbon one; both arrived in Revit 2024, so a release
    without them falls through to the saved preference.
    """
    for attribute in ("CurrentCanvasTheme", "CurrentTheme"):
        try:
            from Autodesk.Revit.UI import UIThemeManager
            value = getattr(UIThemeManager, attribute, None)
            if value is None:
                continue
            text = u"{0}".format(value).strip().lower()
            if "light" in text:
                return "light"
            if "dark" in text:
                return "dark"
        except Exception:
            continue
    return None


def resolve(settings):
    """auto follows Revit, anything else is what the user picked."""
    wanted = str(settings.get("theme", "auto")).strip().lower()
    if wanted in ("dark", "light"):
        return wanted
    found = revit_canvas_theme()
    if found:
        return found
    core.log("Revit's canvas theme could not be read; falling back to dark")
    return "dark"
