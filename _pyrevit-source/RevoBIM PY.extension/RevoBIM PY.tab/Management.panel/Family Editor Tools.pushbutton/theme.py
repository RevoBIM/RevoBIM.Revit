# =========================================================================
# Family Editor Tools - palettes
#
# Both palettes carry exactly the same keys, and every key has a brush in
# Theme.xaml.  The bench check proves all three of those.
#
# The light palette is NOT the dark one inverted: the accents are darkened,
# because the dark palette's accents are chosen to sit on near black and
# wash out on white.
# =========================================================================

import fet_clr  # noqa: F401  - assemblies first, always

from System.Windows.Media import Brush, BrushConverter, Color, SolidColorBrush

DARK = {
    u"WindowBg": u"#232326",
    u"CardBg": u"#2B2B2E",
    u"FieldBg": u"#1C1C1F",
    u"BarBg": u"#1C1C1F",
    u"PreviewBg": u"#191A1D",
    u"EdgeBrush": u"#3E3E42",
    u"GridLineBrush": u"#34343A",
    u"TextBrush": u"#E4E4E4",
    u"MutedBrush": u"#9A9A9E",
    u"DisabledBrush": u"#6A6A70",
    u"BlueBrush": u"#4FA3E3",
    u"OrangeBrush": u"#E8912D",
    u"GreenBrush": u"#3FA75A",
    u"GreenHoverBrush": u"#4EC06D",
    u"RedBrush": u"#D9534F",
    u"SelectBrush": u"#2B5473",
    u"HoverBrush": u"#34343A",
    u"TabActiveBg": u"#2B2B2E",
    u"ScrollThumbBrush": u"#4A4A50",
    u"ScrollThumbHoverBrush": u"#5E5E66",
    u"CloseHoverBrush": u"#D9534F",

    # Data type colours. The same key is used for a staged shared
    # parameter and for the family parameter it would replace.
    u"DataLength": u"#4FA3E3",
    u"DataAreaVolume": u"#46B8B0",
    u"DataAngle": u"#A98BE0",
    u"DataNumber": u"#3FA75A",
    u"DataInteger": u"#72C489",
    u"DataText": u"#E8912D",
    u"DataYesNo": u"#D6C03F",
    u"DataMaterial": u"#C9714E",
    u"DataFamilyType": u"#8F9BB3",
    u"DataUrlImage": u"#7E9BD4",
    u"DataFlow": u"#E0728F",
    u"DataOther": u"#9A9A9E",
    # A pending swap, and a family parameter the picked new one could
    # replace.
    u"SwapBrush": u"#A98BE0",
    u"SwapRowBg": u"#2E2842",
    u"MatchRowBg": u"#22323F",
}

LIGHT = {
    u"WindowBg": u"#F2F2F4",
    u"CardBg": u"#FFFFFF",
    u"FieldBg": u"#FFFFFF",
    u"BarBg": u"#E4E4E8",
    u"PreviewBg": u"#FAFAFB",
    u"EdgeBrush": u"#C6C6CC",
    u"GridLineBrush": u"#DCDCE2",
    u"TextBrush": u"#1F1F22",
    u"MutedBrush": u"#5E5E66",
    u"DisabledBrush": u"#A0A0A8",
    u"BlueBrush": u"#1B72BE",
    u"OrangeBrush": u"#B96A12",
    u"GreenBrush": u"#2E8546",
    u"GreenHoverBrush": u"#3B9E58",
    u"RedBrush": u"#B4322E",
    u"SelectBrush": u"#BBD8F0",
    u"HoverBrush": u"#E0E0E6",
    u"TabActiveBg": u"#FFFFFF",
    u"ScrollThumbBrush": u"#B4B4BC",
    u"ScrollThumbHoverBrush": u"#96969E",
    u"CloseHoverBrush": u"#B4322E",

    # Data type colours. The same key is used for a staged shared
    # parameter and for the family parameter it would replace.
    u"DataLength": u"#1B72BE",
    u"DataAreaVolume": u"#18827B",
    u"DataAngle": u"#6B4CB0",
    u"DataNumber": u"#2E8546",
    u"DataInteger": u"#3F8F55",
    u"DataText": u"#B96A12",
    u"DataYesNo": u"#8E7C11",
    u"DataMaterial": u"#9B4A29",
    u"DataFamilyType": u"#5A6479",
    u"DataUrlImage": u"#4667A6",
    u"DataFlow": u"#B23F5E",
    u"DataOther": u"#5E5E66",
    # A pending swap, and a family parameter the picked new one could
    # replace.
    u"SwapBrush": u"#6B4CB0",
    u"SwapRowBg": u"#EAE3F8",
    u"MatchRowBg": u"#DCEBF7",
}

PALETTES = {u"dark": DARK, u"light": LIGHT}

_CACHE = {}


def palette(name):
    return PALETTES.get(name, DARK)


def keys():
    return sorted(DARK.keys())


def make_brush(hex_text):
    cached = _CACHE.get(hex_text)
    if cached is not None:
        return cached
    brush = None
    try:
        brush = BrushConverter().ConvertFromString(hex_text)
    except Exception:
        brush = None
    if brush is None:
        try:
            text = hex_text.lstrip(u"#")
            colour = Color.FromRgb(int(text[0:2], 16),
                                   int(text[2:4], 16),
                                   int(text[4:6], 16))
            brush = SolidColorBrush(colour)
        except Exception:
            brush = None
    if brush is not None:
        try:
            brush.Freeze()
        except Exception:
            pass
        _CACHE[hex_text] = brush
    return brush


def apply(window, name):
    u"""Write the palette straight onto window.Resources.  That sits in
    FRONT of a merged dictionary in WPF's lookup order, so the palette can
    be swapped on an open window with no reload and no loss of state."""
    values = palette(name)
    for key in values:
        brush = make_brush(values[key])
        if brush is not None:
            window.Resources[key] = brush
    return name


def revit_theme():
    u"""'dark', 'light', or None when Revit will not say.

    UIThemeManager exists from Revit 2024; the enum spelling has moved
    about, so the answer is read as text rather than compared to a member.
    """
    try:
        from Autodesk.Revit.UI import UIThemeManager
    except Exception:
        return None
    try:
        current = getattr(UIThemeManager, u"CurrentTheme", None)
        if current is None:
            return None
        text = u"{0}".format(current).lower()
        if u"light" in text:
            return u"light"
        if u"dark" in text:
            return u"dark"
    except Exception:
        return None
    return None


def resolve(setting, remembered=u"dark"):
    u"""'follow' asks Revit and falls back to what was last used, so a
    release that will not answer never leaves the window unthemed."""
    if setting == u"dark" or setting == u"light":
        return setting
    found = revit_theme()
    if found:
        return found
    return remembered if remembered in PALETTES else u"dark"


def other(name):
    return u"light" if name == u"dark" else u"dark"
