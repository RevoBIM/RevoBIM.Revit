# -*- coding: utf-8 -*-
"""The dark and light palettes, and which one Revit's canvas is using.

The palette is written straight onto window.Resources, which sits in front of
the merged Theme.xaml in WPF's lookup order, so a switch on an open window
needs no reload. The light palette is not the dark one inverted: the accents
are darkened because the dark accents wash out on white.
"""
import mcu_clr  # noqa: F401 - must come before any System.* import
import mcu_core as core

from System.Windows.Media import SolidColorBrush, ColorConverter

# Dark follows Revit's own dark theme (2024 and later), which is Autodesk's
# slate blue-grey rather than a neutral grey: the frame and title bars are the
# darkest, panels sit lighter than the window behind them, and fields drop
# back below the panel they sit in. The RevoBIM accents stay as they are on
# every tool. Swap the surface values here, and the defaults at the top of
# Theme.xaml, to retune the whole tool.

DARK = {
    u"BgBrush": u"#2D3440",
    u"CardBrush": u"#3B4453",
    u"FieldBrush": u"#262D38",
    u"BarBrush": u"#222933",
    u"EdgeBrush": u"#4F596C",
    u"WindowEdgeBrush": u"#5B667B",
    u"TextBrush": u"#F2F4F7",
    u"MutedBrush": u"#B2BAC6",
    u"BlueBrush": u"#4FA3E3",
    u"OrangeBrush": u"#E8912D",
    u"GreenBrush": u"#3FA75A",
    u"GreenHoverBrush": u"#4EC06D",
    u"RedBrush": u"#EE7A75",
    u"SelectBrush": u"#2E5A80",
    u"HoverBrush": u"#4A5468",
    u"OnAccentBrush": u"#FFFFFF",
    u"LockedBrush": u"#333A47",
    u"BlueSoftBrush": u"#2A4A66",
    u"GreenSoftBrush": u"#2B4636",
    u"OrangeSoftBrush": u"#4D3D2A",
}

LIGHT = {
    u"BgBrush": u"#F3F3F5",
    u"CardBrush": u"#FFFFFF",
    u"FieldBrush": u"#FAFAFB",
    u"BarBrush": u"#E6E6EA",
    u"EdgeBrush": u"#CDCDD3",
    u"WindowEdgeBrush": u"#B5B5BC",
    u"TextBrush": u"#1E1E22",
    u"MutedBrush": u"#6A6A72",
    u"BlueBrush": u"#1B72BE",
    u"OrangeBrush": u"#B96A12",
    u"GreenBrush": u"#2E8546",
    u"GreenHoverBrush": u"#36A055",
    u"RedBrush": u"#C23B37",
    u"SelectBrush": u"#CFE3F5",
    u"HoverBrush": u"#ECECF0",
    u"OnAccentBrush": u"#FFFFFF",
    u"LockedBrush": u"#EDEDF0",
    u"BlueSoftBrush": u"#E3EEF8",
    u"GreenSoftBrush": u"#E2F1E6",
    u"OrangeSoftBrush": u"#F7ECDF",
}

PALETTES = {core.THEME_DARK: DARK, core.THEME_LIGHT: LIGHT}


def palette(resolved):
    return PALETTES.get(resolved, DARK)


def make_brush(hex_text):
    brush = SolidColorBrush(ColorConverter.ConvertFromString(hex_text))
    try:
        brush.Freeze()
    except Exception:
        pass
    return brush


def apply(window, resolved):
    for key, value in palette(resolved).items():
        try:
            window.Resources[key] = make_brush(value)
        except Exception:
            core.log(u"theme: could not set " + key)


def _theme_is_dark(theme_value):
    text = core.to_text(theme_value).lower()
    if u"dark" in text:
        return True
    if u"light" in text:
        return False
    return None


def canvas_is_dark(uiapp):
    """True / False from Revit's own settings, None when nothing answers.

    Tried in order: the canvas theme (UIThemeManager.CurrentCanvasTheme),
    the canvas background colour, then the UI theme. Every route is looked up
    late with getattr, so a release that lacks one simply falls through."""
    manager = None
    try:
        import Autodesk.Revit.UI as revit_ui
        manager = getattr(revit_ui, u"UIThemeManager", None)
    except Exception:
        manager = None

    if manager is not None:
        try:
            answer = _theme_is_dark(getattr(manager, u"CurrentCanvasTheme"))
            if answer is not None:
                return answer
        except Exception:
            pass

    try:
        colour = uiapp.Application.BackgroundColor
        return core.colour_is_dark(colour.Red, colour.Green, colour.Blue)
    except Exception:
        pass

    if manager is not None:
        try:
            answer = _theme_is_dark(getattr(manager, u"CurrentTheme"))
            if answer is not None:
                return answer
        except Exception:
            pass
    return None
