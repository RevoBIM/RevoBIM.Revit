# -*- coding: utf-8 -*-
"""RevoBIM PY - Filter Manager : the dark and light palettes.

Every colour in the tool is a key in here. The layouts reference them with
DynamicResource so the palette can be swapped on an open window with no
reload and no loss of state, and code-built elements read them through
`get()`.

The light palette is not the dark one inverted: the accents are darkened
because the dark palette's accents are chosen to sit on near-black and wash
out on white.

Pure Python - no Revit, no WPF - so the bench can test it.
"""

DARK = {
    # Revit's own dark theme (2024+), sampled from its Project Browser:
    # slate blue-greys rather than neutral greys. Title bar #222931, toolbar
    # #1B1F24, panel #3C4454, search field #2D3441, selected row #323C48,
    # tree lines #5A6372, text #EBF5FF, muted #9DA4B2, placeholder #7B8290.
    # Muted text and red are lifted a shade from Revit's so they still read
    # at 4.5:1 / 3:1 on the lighter #3C4454 panel.
    "WindowBg":      "#FF323A47",
    "Head":          "#FF222931",
    "Panel":         "#FF3C4454",
    "PanelAlt":      "#FF363E4C",
    "HeaderRow":     "#FF323C48",
    "Field":         "#FF2D3441",
    "FieldDeep":     "#FF262C37",

    "Edge":          "#FF4A5364",
    "EdgeWindow":    "#FF1B1F24",
    "EdgeSoft":      "#FF434C5B",
    "EdgeFaint":     "#FF3A4352",
    "EdgeStrong":    "#FF5A6372",
    "BoxEdge":       "#FF6A7384",
    "EdgeHover":     "#FF7B8290",

    "Txt":           "#FFE6EEF7",
    "Label":         "#FFBAC0C8",
    "Dim":           "#FFACB4C2",
    "TabIdle":       "#FFACB2B9",
    "TabActiveTxt":  "#FFFFFFFF",
    "Disabled":      "#FF6E7584",
    "Glyph":         "#FFACB2B9",
    "OnAccent":      "#FFF2F2F2",
    "OnOrange":      "#FF1B1F24",

    "Blue":          "#FF3D9BE9",
    "Orange":        "#FFE8862D",
    "OrangeEdge":    "#FFC96F1E",
    "OrangeHover":   "#FFF39A45",
    "Green":         "#FF3FA75A",
    "GreenHover":    "#FF4EC06D",
    "GreenEdge":     "#FF2E8546",
    "Red":           "#FFF07A75",
    "RedDeep":       "#FFB03A36",
    "RedEdge":       "#FF8E2C29",
    "CloseHover":    "#FFC0392B",

    "Btn":           "#FF2D3441",
    "BtnHover":      "#FF39424F",
    "BtnPress":      "#FF222931",
    "GlyphHover":    "#FF2D3441",

    "Sel":           "#FF4B5669",
    "Hover":         "#FF39414F",
    "Thumb":         "#FF5A6372",
    "ThumbHover":    "#FF7B8290",

    "ChangedBg":     "#FF4A3A20",
    "ChangedEdge":   "#FFE8862D",

    "ArrowBg":       "#FF1B1F24",
    "ArrowHover":    "#FF12151A",
    "ArrowPress":    "#FF2D3441",
}

LIGHT = {
    "WindowBg":      "#FFF4F4F6",
    "Head":          "#FFE7E7EC",
    "Panel":         "#FFFFFFFF",
    "PanelAlt":      "#FFF1F1F5",
    "HeaderRow":     "#FFEBEBF0",
    "Field":         "#FFFFFFFF",
    "FieldDeep":     "#FFFAFAFC",

    "Edge":          "#FFC6C6CE",
    "EdgeWindow":    "#FFB4B4BE",
    "EdgeSoft":      "#FFCFCFD6",
    "EdgeFaint":     "#FFDCDCE2",
    "EdgeStrong":    "#FFAEAEB8",
    "BoxEdge":       "#FFA6A6B0",
    "EdgeHover":     "#FF96969E",

    "Txt":           "#FF1E1E22",
    "Label":         "#FF5A5A62",
    "Dim":           "#FF5E5E66",
    "TabIdle":       "#FF6A6A72",
    "TabActiveTxt":  "#FF16161A",
    "Disabled":      "#FFA2A2AA",
    "Glyph":         "#FF3A3A40",
    "OnAccent":      "#FFFFFFFF",
    "OnOrange":      "#FF1E1E1E",

    "Blue":          "#FF1B72BE",
    "Orange":        "#FFB96A12",
    "OrangeEdge":    "#FF95560E",
    "OrangeHover":   "#FFD07C1C",
    "Green":         "#FF2E8546",
    "GreenHover":    "#FF3FA75A",
    "GreenEdge":     "#FF24693A",
    "Red":           "#FFC0392B",
    "RedDeep":       "#FFB03A36",
    "RedEdge":       "#FF8E2C29",
    "CloseHover":    "#FFC0392B",

    "Btn":           "#FFE4E4EA",
    "BtnHover":      "#FFD6D6DE",
    "BtnPress":      "#FFC6C6D0",
    "GlyphHover":    "#FFDCDCE4",

    "Sel":           "#FFCBDCEC",
    "Hover":         "#FFE3EAF2",
    "Thumb":         "#FFB6B6C0",
    "ThumbHover":    "#FF90909A",

    "ChangedBg":     "#FFFFF0D2",
    "ChangedEdge":   "#FFB96A12",

    "ArrowBg":       "#FF1E1E24",
    "ArrowHover":    "#FF000000",
    "ArrowPress":    "#FF34343A",
}

PALETTES = {"dark": DARK, "light": LIGHT}
KEYS = sorted(DARK.keys())

_CURRENT = ["dark"]


def name():
    return _CURRENT[0]


def set_palette(palette_name):
    _CURRENT[0] = "light" if str(palette_name).lower() == "light" else "dark"
    return _CURRENT[0]


def toggle():
    return set_palette("dark" if name() == "light" else "light")


# ---------------------------------------------------------------------------
#  Mode: what the user picked. "auto" follows Revit's canvas theme, so the
#  palette is a consequence of the mode rather than the setting itself.
# ---------------------------------------------------------------------------
MODES = ("auto", "dark", "light")
MODE_LABELS = {"auto": "Auto", "dark": "Dark", "light": "Light"}
_MODE = ["auto"]


def mode():
    return _MODE[0]


def parse_mode(value):
    """A saved value back to a mode. Anything unknown is auto."""
    text = str(value or "").strip().lower()
    if text in ("follow", "auto", "revit", "system"):
        return "auto"
    return text if text in MODES else "auto"


def set_mode(value, detected=None):
    """Set the mode and the palette it implies. `detected` is what Revit
    is showing ("dark"/"light"/None) and only matters in auto."""
    _MODE[0] = parse_mode(value)
    return set_palette(resolve(_MODE[0], detected))


def resolve(mode_value, detected=None):
    """The palette a mode means. Auto with nothing detected is dark, the
    same as Revit's own default."""
    m = parse_mode(mode_value)
    if m == "auto":
        return "light" if str(detected or "").lower() == "light" else "dark"
    return m


def next_mode(mode_value):
    """Auto -> Dark -> Light -> Auto, the order the header chip cycles."""
    m = parse_mode(mode_value)
    return MODES[(MODES.index(m) + 1) % len(MODES)]


def current():
    return PALETTES[_CURRENT[0]]


def get(key, fallback="#FF808080"):
    return current().get(key, DARK.get(key, fallback))
