# -*- coding: utf-8 -*-
"""Palettes for the easter egg, and working out which one to use.

The palettes are the house ones from the RevoBIM theme reference, with a small
set of extra game colours on the end. The light palette is not the dark one
inverted: the accents are darkened, because the dark accents are chosen to sit
on near-black and wash out on white.
"""

# No egg_clr here, and no System.* anywhere in this file. It is a pair of colour
# dictionaries and one late, guarded look at Revit's own theme - all of which is
# plain Python. Keeping it that way is what lets the desktop build share it.

DARK = {
    "bg": "#232326",
    "card": "#2B2B2E",
    "field": "#1C1C1F",
    "bar": "#1C1C1F",
    "edge": "#3E3E42",
    "chrome": "#4A4A50",
    "text": "#E4E4E4",
    "muted": "#9A9A9E",
    "blue": "#4FA3E3",
    "orange": "#E8912D",
    "green": "#3FA75A",
    "red": "#D9534F",
    "sel": "#2B5473",
    # game
    "maze": "#4FA3E3",
    "maze_fill": "#1B2A38",
    "pellet": "#9A9A9E",
    "power": "#E8912D",
    "hero": "#F5C518",
    "ghost_1": "#D9534F",
    "ghost_2": "#E88BC0",
    "ghost_3": "#4FD8E3",
    "ghost_4": "#E8912D",
    "scared": "#2B5473",
    "scared_end": "#E4E4E4",
    "eyes": "#FFFFFF",
    "pupil": "#232326",
    "veil": "#E0232326",
}

LIGHT = {
    "bg": "#F2F2F4",
    "card": "#FFFFFF",
    "field": "#FFFFFF",
    "bar": "#E8E8EC",
    "edge": "#C9C9D0",
    "chrome": "#B8B8C0",
    "text": "#1E1E20",
    "muted": "#63636A",
    "blue": "#1B72BE",
    "orange": "#B96A12",
    "green": "#2E8546",
    "red": "#B23B38",
    "sel": "#CFE2F3",
    # game
    "maze": "#1B72BE",
    "maze_fill": "#DCE9F5",
    "pellet": "#63636A",
    "power": "#B96A12",
    "hero": "#D9A400",
    "ghost_1": "#B23B38",
    "ghost_2": "#C4589A",
    "ghost_3": "#1B9AA8",
    "ghost_4": "#B96A12",
    "scared": "#CFE2F3",
    "scared_end": "#1E1E20",
    "eyes": "#FFFFFF",
    "pupil": "#1E1E20",
    "veil": "#EAF2F2F4",
}

PALETTES = {"dark": DARK, "light": LIGHT}


def _normalise(value):
    if value is None:
        return None
    try:
        text = str(value).strip().lower()
    except Exception:
        return None
    if text in ("dark", "darkmode", "0"):
        return "dark"
    if text in ("light", "lightmode", "1"):
        return "light"
    return None


def revit_theme():
    """Revit's own UI theme, where the release exposes it.

    UIThemeManager arrived in 2024 and lives in Autodesk.Revit.UI. It is looked
    up late, inside this function, so a release that does not carry it skips the
    check rather than throwing at module load. RevitAPIUI is never referenced
    here - if it is not already loaded into the engine this simply fails and we
    fall through to the saved setting.
    """
    try:
        import Autodesk.Revit.UI as revit_ui
        manager = getattr(revit_ui, "UIThemeManager", None)
        if manager is None:
            return None
        current = getattr(manager, "CurrentTheme", None)
        if current is None:
            return None
        return _normalise(str(current))
    except Exception:
        return None


def resolve(preferred=None, saved=None):
    """Decide which palette to use.

    Order: an egg setting of 'dark' or 'light' - somebody has said what they
    want and it should not be argued with - then what the host tool says it is
    showing, then Revit's own UI theme, then dark. The setting ships as 'auto',
    so out of the box the egg simply comes up in whatever the tool that launched
    it is already showing.

    `preferred` may be a string or a callable returning one. A tool whose theme
    can be switched while its window is open passes a lambda, so the egg picks
    up the palette in use at the moment it opens rather than the one that was in
    use when the hook was attached.
    """
    name = _normalise(saved)
    if name:
        return name

    value = preferred
    if callable(value):
        try:
            value = value()
        except Exception:
            value = None
    name = _normalise(value)
    if name:
        return name

    name = revit_theme()
    if name:
        return name

    return "dark"


def palette(name):
    return PALETTES.get(name, DARK)
