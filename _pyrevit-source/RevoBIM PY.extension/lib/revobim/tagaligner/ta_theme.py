# -*- coding: utf-8 -*-
"""Tag Aligner: the dark and light palettes, and Auto following Revit's canvas.

Same palette as every RevoBIM PY tool (see the theme reference). The light
palette darkens the accents rather than inverting the dark one, because the
dark accents are chosen to sit on near black and wash out on white.
"""
import ta_clr  # noqa: F401  must stay first

MODES = (u"follow", u"dark", u"light")
LABELS = {u"follow": u"Auto", u"dark": u"Dark", u"light": u"Light"}

PALETTES = {
    u"dark": {
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
        u"Green": u"#3FA75A",
        u"GreenHover": u"#4EC06D",
        u"Red": u"#D9534F",
        u"Sel": u"#2B5473",
        u"Hover": u"#35353A",
        u"Chip": u"#2B2B2E",
        u"OnAccent": u"#FFFFFF",
    },
    u"light": {
        u"Bg": u"#F3F3F5",
        u"Card": u"#FFFFFF",
        u"Field": u"#FFFFFF",
        u"Bar": u"#E4E4E9",
        u"Edge": u"#C9C9CF",
        u"WinEdge": u"#AEAEB6",
        u"Text": u"#1E1E22",
        u"Muted": u"#66666E",
        u"Blue": u"#1B72BE",
        u"Orange": u"#B96A12",
        u"Green": u"#2E8546",
        u"GreenHover": u"#379A53",
        u"Red": u"#C0392B",
        u"Sel": u"#CFE3F5",
        u"Hover": u"#E6E6EC",
        u"Chip": u"#FFFFFF",
        u"OnAccent": u"#FFFFFF",
    },
}


def canvas_is_dark():
    """True / False from Revit's canvas theme, None when it cannot be read.

    UITheme.Dark is 0, so a truthiness test reads Dark as a failed read and
    falls through to Light. Test 'is not None' and compare by name.
    UIThemeManager only exists from Revit 2024, so it is reached by getattr.
    """
    try:
        import Autodesk.Revit.UI as revit_ui
    except Exception:
        return None
    manager = getattr(revit_ui, "UIThemeManager", None)
    if manager is None:
        return None
    for prop in ("CurrentCanvasTheme", "CurrentTheme"):
        try:
            theme = getattr(manager, prop)
        except Exception:
            theme = None
        if theme is not None:
            return u"{0}".format(theme).split(u".")[-1] == u"Dark"
    return None


def resolve(mode):
    """The palette name a mode shows right now."""
    if mode == u"dark" or mode == u"light":
        return mode
    dark = canvas_is_dark()
    if dark is None:
        return u"dark"
    return u"dark" if dark else u"light"


def next_mode(mode):
    try:
        i = MODES.index(mode)
    except ValueError:
        i = -1
    return MODES[(i + 1) % len(MODES)]


def tooltip(mode):
    shown = resolve(mode)
    if mode == u"follow":
        return (u"Theme: Auto, following Revit's canvas (now {0}).\n"
                u"Click for Dark, then Light, then back to Auto.").format(shown)
    return (u"Theme: {0}.\nClick to switch. Auto follows Revit's canvas."
            ).format(LABELS[mode])


def hex_to_rgb(text):
    text = text.lstrip(u"#")
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)
