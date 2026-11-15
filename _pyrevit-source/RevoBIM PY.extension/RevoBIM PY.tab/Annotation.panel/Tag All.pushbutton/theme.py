# -*- coding: utf-8 -*-
"""The RevoBIM palettes and the Auto mode that follows Revit's canvas.

Every brush a layout asks for by DynamicResource is written straight onto
window.Resources, which sits in front of the merged Theme.xaml in WPF's
lookup order - so the palette can be swapped on an open window with no
reload and no loss of state.
"""
import tagall_clr  # noqa: F401  (assemblies first)
import tagall_core as core

# Revit's own dark UI, sampled from its Project Browser, and the same values
# the rest of the RevoBIM suite uses for dark (Pro Sheets, Sheet Manager,
# Project Browser Pro): the panel grey, the darker field the search box sits
# in, the title bar, Revit's hover and active-row blue, its near-white text. Revit's panel is lighter than the old
# near-black, so the accents are lifted just enough to stay at 4.5:1 or
# better against it - bench_logic checks every pairing that carries text.
DARK = {
    "WindowBrush": "#3C4454",       # Revit's panel grey: the body of the window
    "CardBrush": "#353D4B",         # a shade under the body, so the cards sit in it
    "FieldBrush": "#2D3441",        # Revit's search box: lists and inputs
    "BarBrush": "#222933",          # Revit's title bar: header and footer
    "EdgeBrush": "#4A5464",         # hairlines and borders
    "ChromeEdgeBrush": "#515C6B",   # Revit's window edge
    "TextBrush": "#EEF0F4",         # Revit's near-white text
    "MutedBrush": "#ACB2B9",        # lifted to 4.5:1 on the body
    "BlueBrush": "#5AAEEB",         # lifted to 4.5:1 on the cards
    "OrangeBrush": "#F2A452",
    "GreenBrush": "#3FA75A",        # a button face behind white text, so not lifted
    "GreenHoverBrush": "#4EC06D",
    "RedBrush": "#F79A96",          # red as text: problems, failures
    "CloseHoverBrush": "#C42B1C",   # red behind the white close cross
    "OnAccentBrush": "#1B1F24",     # a glyph on a light accent fill: the tick, a badge
    "SelectBrush": "#3A7392",       # Revit's active-row blue
    "HoverBrush": "#444E5E",        # Revit's hover grey
    "LinkBrush": "#D4A6FB",
    "HeaderRowBrush": "#323C48",    # Revit's selected-row tone, for table headings
    "DisabledBrush": "#6E7684",
}

LIGHT = {
    "WindowBrush": "#F3F3F5",
    "CardBrush": "#FFFFFF",
    "FieldBrush": "#FFFFFF",
    "BarBrush": "#E6E6EA",
    "EdgeBrush": "#C9C9CF",
    "ChromeEdgeBrush": "#B8B8C0",
    "TextBrush": "#1E1E22",
    "MutedBrush": "#66666C",
    "BlueBrush": "#1B72BE",
    "OrangeBrush": "#B96A12",
    "GreenBrush": "#2E8546",
    "GreenHoverBrush": "#37A055",
    "RedBrush": "#C9302C",
    "CloseHoverBrush": "#C42B1C",
    "OnAccentBrush": "#FFFFFF",
    "SelectBrush": "#CFE3F5",
    "HoverBrush": "#E9E9EE",
    "LinkBrush": "#7A3FB8",
    "HeaderRowBrush": "#ECECF0",
    "DisabledBrush": "#B0B0B6",
}

PALETTES = {core.THEME_DARK: DARK, core.THEME_LIGHT: LIGHT}


def palette(name):
    return PALETTES.get(name, DARK)


def revit_theme():
    """Revit's canvas theme, or None where the release cannot say.

    UIThemeManager arrived in Revit 2024. The canvas theme is a separate
    property from the UI theme and is the one that matters - it is what the
    drawing area looks like - so it is read first and CurrentTheme is the
    fallback. Compared as text because the enum names have moved around.
    """
    try:
        from Autodesk.Revit.UI import UIThemeManager
    except Exception:
        return None
    for attribute in ("CurrentCanvasTheme", "CurrentTheme"):
        try:
            value = getattr(UIThemeManager, attribute)
        except Exception:
            continue
        found = core.theme_from_text(value)
        if found:
            return found
    return None


def resolve(mode):
    return core.resolve_theme(mode, revit_theme())


def brush(hex_text):
    from System.Windows.Media import SolidColorBrush, ColorConverter
    result = SolidColorBrush(ColorConverter.ConvertFromString(hex_text))
    try:
        result.Freeze()
    except Exception:
        pass
    return result


def apply(window, name):
    """Write the named palette onto the window's own resources."""
    chosen = palette(name)
    for key, hex_text in chosen.items():
        try:
            window.Resources[key] = brush(hex_text)
        except Exception:
            pass
    return chosen
