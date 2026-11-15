# -*- coding: utf-8 -*-
u"""RevoBIM Addins - the dark and light palettes, and following Revit.

Auto is the default: the palette follows Revit's own canvas theme, read from
Autodesk.Revit.UI.UIThemeManager.  Two things about that read matter.

* UIThemeManager only exists from Revit 2024, and only on RevitAPIUI.  It is
  therefore reached by getattr on the namespace rather than by a top level
  "from Autodesk.Revit.UI import UIThemeManager", which would throw ImportError
  at module load on an older host - the blank white pyRevit window.
* UITheme.Dark is 0.  Testing the read with "or" instead of "is not None"
  treats Dark as a failed read and silently falls through to Light.  pyRevit's
  own loader carried a version of that bug for several releases.
"""

import rba_clr  # noqa: F401

from rba_core import to_text, log

# Revit's own dark UI, sampled from its Project Browser: slate blue rather than
# near black, so a docked panel sits beside Revit's browsers as one surface.
# The accents stay the house blue, orange and green.
DARK = {
    u"BgWindow": u"#3B4453",      # panel body
    u"BgCard": u"#333B49",        # group headings, cards
    u"BgField": u"#2C3440",       # search box, lists, inputs
    u"BgBar": u"#222933",         # header and footer bars (Revit's title bar)
    u"BgHover": u"#414B5A",
    u"BrdEdge": u"#515C6B",
    u"BrdWindow": u"#515C6B",     # a floating window's outer edge
    u"FgText": u"#F5F5F5",
    u"FgMuted": u"#9DA5B0",
    u"AccBlue": u"#4FA3E3",
    u"AccOrange": u"#E8912D",
    u"AccGreen": u"#3FA75A",
    u"AccGreenHover": u"#4EC06D",
    u"AccRed": u"#D9534F",
    u"AccStar": u"#F5C542",       # the favourites star
    u"ShadowColor": u"#000000",   # a Color, not a brush - see apply()
    u"SelHighlight": u"#2D5B80",
}

# Not the dark palette inverted: the accents are darkened, because the dark
# accents are chosen to sit on dark slate and wash out on white.
LIGHT = {
    u"BgWindow": u"#F2F2F4",
    u"BgCard": u"#FFFFFF",
    u"BgField": u"#FFFFFF",
    u"BgBar": u"#E8E8EC",
    u"BgHover": u"#E3E9F0",
    u"BrdEdge": u"#C7C7CC",
    u"BrdWindow": u"#B4B4BC",
    u"FgText": u"#1F1F22",
    u"FgMuted": u"#6A6A70",
    u"AccBlue": u"#1B72BE",
    u"AccOrange": u"#B96A12",
    u"AccGreen": u"#2E8546",
    u"AccGreenHover": u"#3C9B57",
    u"AccRed": u"#B5403C",
    u"AccStar": u"#D49B00",
    u"ShadowColor": u"#5A6070",
    u"SelHighlight": u"#CBDDEE",
}

PALETTES = {u"dark": DARK, u"light": LIGHT}
MODES = (u"auto", u"dark", u"light")


def revit_theme():
    u"""'dark', 'light', or None when Revit will not say."""
    try:
        from Autodesk.Revit import UI as revit_ui
    except Exception:
        return None
    manager = getattr(revit_ui, u"UIThemeManager", None)
    if manager is None:
        return None
    value = None
    for attribute in (u"CurrentCanvasTheme", u"CurrentTheme"):
        candidate = getattr(manager, attribute, None)
        if candidate is not None:          # Dark is 0 - never test truthiness
            value = candidate
            break
    if value is None:
        return None
    name = to_text(value).strip().lower()
    if u"dark" in name:
        return u"dark"
    if u"light" in name:
        return u"light"
    try:
        return u"dark" if int(value) == 0 else u"light"
    except Exception:
        return None


def resolve(mode):
    mode = to_text(mode).strip().lower()
    if mode not in MODES:
        mode = u"auto"
    if mode == u"auto":
        detected = revit_theme()
        if detected is None:
            log(u"theme: Revit would not report a theme, falling back to dark")
            return u"dark"
        return detected
    return mode


def next_mode(mode):
    mode = to_text(mode).strip().lower()
    if mode not in MODES:
        return u"dark"
    return MODES[(MODES.index(mode) + 1) % len(MODES)]


def palette(name):
    return PALETTES.get(to_text(name).strip().lower(), DARK)


def brush(hex_value):
    from System.Windows.Media import BrushConverter
    return BrushConverter().ConvertFromString(hex_value)


def apply(element, name):
    u"""Write the palette straight onto the element's own Resources.

    A local resource dictionary sits in front of a merged one in WPF's lookup
    order, so the palette can be swapped on a pane that is already open with no
    reload and no loss of state.
    """
    values = palette(name)
    resources = element.Resources
    for key in values:
        try:
            if key.endswith(u"Color"):
                # A DropShadowEffect wants a Color, not a brush.
                from System.Windows.Media import ColorConverter
                resources[key] = ColorConverter.ConvertFromString(values[key])
            else:
                resources[key] = brush(values[key])
        except Exception:
            pass
    return values
