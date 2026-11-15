# -*- coding: utf-8 -*-
"""The dark and light palettes, and reading Revit's own canvas theme.

The light palette is not the dark one inverted: the accents are darkened,
because the dark palette's accents are chosen to sit on near-black and wash out
on white.
"""

import shtm_clr  # noqa: F401  - references the assemblies first

DARK = {
    # Revit's own dark theme, sampled from its Project Browser (RevoBIM theme
    # reference, "Revit's own dark palette"), so the tool sits inside Revit's
    # greys rather than the older house near-black. Accents stay RevoBIM's;
    # muted text and blue are lifted to stay over 4:1 on the lighter body.
    "WindowBg": "#3C4454",
    "CardBg": "#343C4A",
    "FieldBg": "#2D3441",
    "BarBg": "#222933",
    "EdgeBrush": "#4E5665",
    "TextBrush": "#EEF0F4",
    "MutedBrush": "#A4AAB1",
    "BlueBrush": "#5AAEEB",
    "OrangeBrush": "#E8912D",
    "GreenBrush": "#3FA75A",
    "GreenHover": "#4EC06D",
    "RedBrush": "#D9534F",
    "SelectionBrush": "#3A7392",
    "HoverBg": "#444E5E",
    "HeaderBg": "#323C48",
    "RowAltBg": "#333A47",
    "GroupRowBg": "#42495C",
    "GroupL1Bg": "#5B5B3A",
    "GroupL2Bg": "#5B483A",
    "GroupL3Bg": "#2D5274",
    "GroupL4Bg": "#3B624C",
    "GroupL5Bg": "#4B426C",
    "GroupL6Bg": "#2F566C",
    "BandL1Bg": "#3A3E39",
    "BandL2Bg": "#3C3A3B",
    "BandL3Bg": "#2A3D55",
    "BandL4Bg": "#2D433D",
    "BandL5Bg": "#36374E",
    "BandL6Bg": "#2A404E",
    "CreatedBg": "#2A6E48",
    "VioletBrush": "#B08EE6",
    "TealBrush": "#4CC2C0",
    "AmberBrush": "#DDBF55",
    "StagedBg": "#30624E",
    "ImportBg": "#2D5E68",
    "RefusedBg": "#8B3B42",
    "ReadOnlyBg": "#4E3E48",
    "CopiedBg": "#5B5736",
    "DupBg1": "#4B426C",
    "DupBg2": "#2F566C",
    "DupBg3": "#5B5240",
    "DupBg4": "#3B624C",
    "DupBg5": "#5B424C",
    "DupBg6": "#3B426C",
    "DisabledBrush": "#7B8290",
    "GridLineBrush": "#3A4250",
    # found view-name text: small and bold, so a brighter green than the
    # buttons' to stay over 4.5:1 on the cards and lists
    "FoundGreen": "#6CD38A",
    # the set table's number / name / view boxes, in their find's colour
    "TintBlueBg": "#364C63",
    "TintOrangeBg": "#52473D",
    "TintGreenBg": "#314B46",
}

LIGHT = {
    "WindowBg": "#F4F4F6",
    "CardBg": "#FFFFFF",
    "FieldBg": "#FFFFFF",
    "BarBg": "#E7E7EB",
    "EdgeBrush": "#C6C6CC",
    "TextBrush": "#1F1F22",
    "MutedBrush": "#63636A",
    "BlueBrush": "#1B72BE",
    "OrangeBrush": "#B96A12",
    "GreenBrush": "#2E8546",
    "GreenHover": "#37A055",
    "RedBrush": "#B33430",
    "SelectionBrush": "#BBD8F0",
    "HoverBg": "#E2E2E8",
    "HeaderBg": "#EAEAEF",
    "RowAltBg": "#F0F0F3",
    "GroupRowBg": "#DFE4EA",
    "GroupL1Bg": "#F0E6BF",
    "GroupL2Bg": "#F3DEC6",
    "GroupL3Bg": "#CFE2F2",
    "GroupL4Bg": "#D8F0D8",
    "GroupL5Bg": "#E8D8F4",
    "GroupL6Bg": "#D2EAF3",
    "BandL1Bg": "#FAF5E2",
    "BandL2Bg": "#FAEFE3",
    "BandL3Bg": "#E8F1F9",
    "BandL4Bg": "#ECF7EC",
    "BandL5Bg": "#F3ECFA",
    "BandL6Bg": "#E8F4F8",
    "CreatedBg": "#9EDCB0",
    "VioletBrush": "#6E3FB8",
    "TealBrush": "#1C7F7D",
    "AmberBrush": "#9C7C10",
    "StagedBg": "#CFEFD8",
    "ImportBg": "#CBEDED",
    "RefusedBg": "#F2B4B1",
    "ReadOnlyBg": "#F6DCDC",
    "CopiedBg": "#F8ECB8",
    "DupBg1": "#E6D8F6",
    "DupBg2": "#D2EAF3",
    "DupBg3": "#F6E9CF",
    "DupBg4": "#D8F2D8",
    "DupBg5": "#F6D8D8",
    "DupBg6": "#D8D8F6",
    "DisabledBrush": "#A3A3A9",
    "GridLineBrush": "#DADADF",
    "FoundGreen": "#277A3E",
    "TintBlueBg": "#E4EEF7",
    "TintOrangeBg": "#F7EDE3",
    "TintGreenBg": "#E6F0E9",
}

MODES = ["auto", "dark", "light"]
LABELS = {"auto": "Theme: Auto", "dark": "Theme: Dark", "light": "Theme: Light"}


def revit_theme():
    """'dark' or 'light' from Revit itself - the canvas first, since that is
    the drawing area the window sits over, then the ribbon and panels.

    UIThemeManager arrived in the Revit 2024 API, the bottom of this
    extension's range. The value is compared by its name rather than against
    an imported UITheme, because the enum has moved between releases and
    UITheme.Dark is 0, which a plain truth test reads as "nothing".
    """
    try:
        from Autodesk.Revit.UI import UIThemeManager
    except Exception:
        return _windows_theme()
    for name in ("CurrentCanvasTheme", "CurrentTheme"):
        found = theme_name(_read(UIThemeManager, name))
        if found:
            return found
    return _windows_theme()


def _read(owner, name):
    try:
        return getattr(owner, name)
    except Exception:
        return None


def theme_name(value):
    """'dark', 'light' or None from whatever Revit hands back."""
    if value is None:
        return None
    try:
        text = u"{0}".format(value.ToString()).lower()
    except Exception:
        text = u"{0}".format(value).lower()
    if "dark" in text:
        return "dark"
    if "light" in text:
        return "light"
    return None


def _windows_theme():
    try:
        from Microsoft.Win32 import Registry
        key = (u"HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\"
               u"CurrentVersion\\Themes\\Personalize")
        value = Registry.GetValue(key, "AppsUseLightTheme", None)
        if value is not None and int(value) == 1:
            return "light"
    except Exception:
        pass
    return "dark"


def resolve(mode):
    """Turn the saved mode into the palette actually shown."""
    if mode == "light":
        return "light"
    if mode == "dark":
        return "dark"
    return revit_theme()


def palette(mode):
    return LIGHT if resolve(mode) == "light" else DARK


def next_mode(mode):
    try:
        return MODES[(MODES.index(mode) + 1) % len(MODES)]
    except ValueError:
        return "dark"


def label(mode):
    resolved = resolve(mode)
    if mode == "auto":
        return "Theme: Auto ({0})".format(resolved)
    return LABELS.get(mode, "Theme: Dark")


def brush(hex_value):
    from System.Windows.Media import BrushConverter
    return BrushConverter().ConvertFromString(hex_value)


# the palette last applied, for anything that has to pick a brush at
# conversion time rather than through a resource reference
CURRENT = {}


def apply(window, mode):
    """Write the palette straight onto window.Resources.

    window.Resources sits in front of a merged dictionary in WPF's lookup order,
    so the palette can be swapped on an open window with no reload and no loss
    of state.
    """
    global CURRENT
    CURRENT = dict(palette(mode))
    values = palette(mode)
    for key in values:
        try:
            window.Resources[key] = brush(values[key])
        except Exception:
            pass
    return resolve(mode)
