# -*- coding: utf-8 -*-
"""RevoBIM PY - View Template Manager: dark and light palettes.

Theme.xaml holds every brush with its dark value as the default. apply() writes
the chosen palette onto window.Resources, which WPF looks in *before* a merged
dictionary, so every DynamicResource re-resolves on an open window with no
reload: selection, scroll and staged edits all survive the swap.

The cell converters cannot use DynamicResource - they hand back a Brush at
conversion time - so they call brush(key), which reads the palette in force
now. Anything already drawn by a converter is refreshed by the window after a
swap.

Both palettes must carry exactly the same keys, or a swap leaves a brush behind
at its dark default. import_check.py enforces it.
"""

import vtm_clr  # noqa: F401  - assemblies first, always

from System.Windows.Media import SolidColorBrush, ColorConverter

DARK = "dark"
LIGHT = "light"
FOLLOW = "follow"

# What the header chip steps through, and what it says in each state.
MODES = [FOLLOW, DARK, LIGHT]
MODE_LABELS = {FOLLOW: "Auto", DARK: "Dark", LIGHT: "Light"}

PALETTES = {
    # Sampled from Revit 2024+ dark theme (Project Browser): a blue-slate
    # family, not neutral grey. House accents kept for blue/orange/green.
    DARK: {
        "BrushWindow": "#3C4454",  # Revit browser body
        "BrushCard": "#353D4B",
        "BrushField": "#2D3441",  # Revit search field
        "BrushGrid": "#3C4454",  # Revit browser list
        "BrushBar": "#202830",  # Revit panel title bar
        "BrushBorder": "#2C333F",
        "BrushEdge": "#535D6E",
        "BrushText": "#E0E6ED",
        "BrushMuted": "#939CAA",
        "BrushBlue": "#4FA3E3",
        "BrushOrange": "#E8912D",
        "BrushGreen": "#3FA75A",
        "BrushGreenHov": "#4EC06D",
        "BrushRed": "#EF7B76",
        "BrushSelection": "#3A6288",
        "BrushRowAlt": "#39414F",
        "BrushHover": "#475165",
        "BrushDisabled": "#6B7382",
        "BrushRowHover": "#424B5B",
        "BrushRowHighlight": "#323C48",  # Revit selected row
        "BrushThumb": "#5A6373",
        "BrushScrollTrack": "#323A47",
        "BrushTipBg": "#1B1F24",  # Revit toolbar strip
        "BrushOnAccent": "#FFFFFF",
        "BrushDirty": "#58452A",
        "BrushCopy": "#55502C",
        "BrushHeaderFiltered": "#4E3B22",
        "BrushTransparent": "#00000000",
    },
    LIGHT: {
        "BrushWindow": "#F3F3F5",
        "BrushCard": "#FFFFFF",
        "BrushField": "#FFFFFF",
        "BrushGrid": "#FFFFFF",
        "BrushBar": "#E8E8EC",
        "BrushBorder": "#D0D0D6",
        "BrushEdge": "#B8B8C0",
        "BrushText": "#1E1E22",
        "BrushMuted": "#6A6A72",
        "BrushBlue": "#1B72BE",
        "BrushOrange": "#B96A12",
        "BrushGreen": "#2E8546",
        "BrushGreenHov": "#379A52",
        "BrushRed": "#C0392B",
        "BrushSelection": "#BBD6F0",
        "BrushRowAlt": "#F7F7FA",
        "BrushHover": "#E2E2E8",
        "BrushDisabled": "#A8A8AE",
        "BrushRowHover": "#EEF3F8",
        "BrushRowHighlight": "#DDEAF7",
        "BrushThumb": "#B8B8C0",
        "BrushScrollTrack": "#ECECF0",
        "BrushTipBg": "#FFFFFF",
        "BrushOnAccent": "#FFFFFF",
        "BrushDirty": "#FCE3C2",
        "BrushCopy": "#FFF1B8",
        "BrushHeaderFiltered": "#F7D9B0",
        "BrushTransparent": "#00000000",
    },
}

CURRENT = {"name": DARK}
_CACHE = {}


def normalise(name):
    text = (name or "").strip().lower()
    return LIGHT if text == LIGHT else DARK


def _make(hex_text):
    got = _CACHE.get(hex_text)
    if got is not None:
        return got
    try:
        made = SolidColorBrush(ColorConverter.ConvertFromString(hex_text))
    except Exception:
        made = SolidColorBrush(ColorConverter.ConvertFromString("#808080"))
    made.Freeze()
    _CACHE[hex_text] = made
    return made


def brush(key):
    """The brush for a palette key in the theme in force now."""
    palette = PALETTES[CURRENT["name"]]
    return _make(palette.get(key, PALETTES[DARK].get(key, "#808080")))


def apply(window, name):
    """Write a palette onto an open window. Returns the theme now in force."""
    name = normalise(name)
    CURRENT["name"] = name
    palette = PALETTES[name]
    for key in palette:
        try:
            window.Resources[key] = _make(palette[key])
        except Exception:
            continue
    return name


def normalise_mode(mode):
    text = (mode or "").strip().lower()
    return text if text in MODES else FOLLOW


def next_mode(mode):
    """Auto -> Dark -> Light -> Auto."""
    mode = normalise_mode(mode)
    return MODES[(MODES.index(mode) + 1) % len(MODES)]


def mode_label(mode):
    return MODE_LABELS[normalise_mode(mode)]


def resolve(mode, uiapp=None):
    """The palette a mode stands for right now."""
    mode = normalise_mode(mode)
    if mode == FOLLOW:
        return revit_theme(uiapp)
    return mode


def luminance_theme(red, green, blue):
    """Dark or light from a background colour, for releases before 2024."""
    try:
        value = 0.2126 * float(red) + 0.7152 * float(green) + 0.0722 * float(blue)
    except Exception:
        return None
    return DARK if value < 128.0 else LIGHT


def revit_theme(uiapp=None, fallback=DARK):
    """Revit's canvas theme: UIThemeManager.CurrentCanvasTheme first (2024+),
    then the canvas background colour, then the ribbon theme.

    Read by name with getattr and compared by text. UITheme.Dark is 0, so a
    truthiness test on the value reports dark as a failed read and falls
    through to light; the value is only ever tested `is not None`.
    """
    manager = None
    try:
        import Autodesk.Revit.UI as revit_ui
        manager = getattr(revit_ui, "UIThemeManager", None)
    except Exception:
        manager = None

    def from_manager(attribute):
        if manager is None:
            return None
        try:
            value = getattr(manager, attribute)
        except Exception:
            return None
        if value is None:
            return None
        try:
            text = value.ToString().lower()
        except Exception:
            text = str(value).lower()
        if "dark" in text:
            return DARK
        if "light" in text:
            return LIGHT
        return None

    found = from_manager("CurrentCanvasTheme")
    if found is not None:
        return found

    if uiapp is not None:
        try:
            colour = uiapp.Application.BackgroundColor
            found = luminance_theme(colour.Red, colour.Green, colour.Blue)
            if found is not None:
                return found
        except Exception:
            pass

    found = from_manager("CurrentTheme")
    if found is not None:
        return found
    return fallback
