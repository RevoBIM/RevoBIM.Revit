# -*- coding: utf-8 -*-
"""Dark and light palettes, and Auto, which follows Revit's canvas.

The palette is written straight onto window.Resources, which sits in front of
Theme.xaml's merged dictionary in WPF's lookup order, so a switch lands on an
open window with no reload and no loss of state.
"""
import msm_clr  # noqa: F401  - assemblies first

from System.Windows.Media import SolidColorBrush, ColorConverter

MODES = (u"auto", u"dark", u"light")

DARK = {
    u"Bg": u"#232326",
    u"Card": u"#2B2B2E",
    u"Field": u"#1C1C1F",
    u"Bar": u"#1C1C1F",
    u"Edge": u"#3E3E42",
    u"WinEdge": u"#4A4A50",
    u"Text": u"#E4E4E4",
    u"Muted": u"#9A9A9E",
    u"Blue": u"#4FA3E3",
    u"Orange": u"#E8912D",
    u"OrangeHover": u"#F2A24A",
    u"Green": u"#3FA75A",
    u"GreenHover": u"#4EC06D",
    u"BlueHover": u"#6BB6EC",
    u"Red": u"#D9534F",
    u"RedWash": u"#3A2426",
    u"OrangeWash": u"#3B2F1E",
    u"Type0": u"#4FA3E3",
    u"Type1": u"#E8912D",
    u"Type2": u"#3FA75A",
    u"Type3": u"#C678DD",
    u"Type4": u"#E5C07B",
    u"Type5": u"#56B6C2",
    u"Type6": u"#FF79C6",
    u"Type7": u"#98C379",
    u"Type8": u"#B08968",
    u"Type9": u"#C8CDD3",
    u"Select": u"#2B5473",
    u"Hover": u"#333338",
    u"RowAlt": u"#202023",
    u"OnAccent": u"#FFFFFF",
    u"GroupHead": u"#28282C",
}

LIGHT = {
    u"Bg": u"#F3F3F5",
    u"Card": u"#FFFFFF",
    u"Field": u"#FFFFFF",
    u"Bar": u"#E6E6EA",
    u"Edge": u"#C9C9CF",
    u"WinEdge": u"#B5B5BC",
    u"Text": u"#1E1E22",
    u"Muted": u"#65656C",
    u"Blue": u"#1B72BE",
    u"Orange": u"#B96A12",
    u"OrangeHover": u"#CC7A1E",
    u"Green": u"#2E8546",
    u"GreenHover": u"#379A53",
    u"BlueHover": u"#2A85D1",
    u"Red": u"#C0392B",
    u"RedWash": u"#FBE4E2",
    u"OrangeWash": u"#FCEBD5",
    u"Type0": u"#1B72BE",
    u"Type1": u"#B96A12",
    u"Type2": u"#2E8546",
    u"Type3": u"#8E44AD",
    u"Type4": u"#9A7B12",
    u"Type5": u"#1F8A96",
    u"Type6": u"#B0306E",
    u"Type7": u"#5E8C1F",
    u"Type8": u"#7A5230",
    u"Type9": u"#5A6270",
    u"Select": u"#CFE3F5",
    u"Hover": u"#ECECF0",
    u"RowAlt": u"#F7F7F9",
    u"OnAccent": u"#FFFFFF",
    u"GroupHead": u"#EDEDF1",
}


def canvas_theme():
    """'dark' or 'light' from Revit's canvas, or None where it cannot be read.

    UIThemeManager only exists from Revit 2024, so it is reached by getattr on
    the namespace rather than imported. UITheme.Dark is 0, so the read is
    tested with 'is not None' - a truthiness test reports Dark as a failure.
    """
    try:
        import Autodesk.Revit.UI as revit_ui
        manager = getattr(revit_ui, u"UIThemeManager", None)
        if manager is None:
            return None
        current = getattr(manager, u"CurrentCanvasTheme", None)
        if current is None:
            return None
        text = u"{0}".format(current).lower()
        if u"dark" in text:
            return u"dark"
        if u"light" in text:
            return u"light"
        return None
    except Exception:
        return None


def resolve(mode):
    mode = (mode or u"auto").lower()
    if mode in (u"dark", u"light"):
        return mode
    found = canvas_theme()
    return found if found is not None else u"dark"


def palette(resolved):
    return LIGHT if resolved == u"light" else DARK


def next_mode(mode):
    mode = (mode or u"auto").lower()
    if mode not in MODES:
        return u"auto"
    return MODES[(MODES.index(mode) + 1) % len(MODES)]


def label(mode):
    mode = (mode or u"auto").lower()
    if mode == u"auto":
        return u"Auto \u00b7 {0}".format(resolve(mode).capitalize())
    return mode.capitalize()


def brush(hex_text):
    color = ColorConverter.ConvertFromString(hex_text)
    result = SolidColorBrush(color)
    try:
        result.Freeze()
    except Exception:
        pass
    return result


def apply(window, mode):
    resolved = resolve(mode)
    colours = palette(resolved)
    for key in colours:
        try:
            window.Resources[key] = brush(colours[key])
        except Exception:
            pass
    return resolved
