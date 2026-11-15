# -*- coding: utf-8 -*-
"""The dark and light palettes, and applying one to a live window.

Both palettes carry exactly the same keys; the bench check enforces that. The
light palette is not the dark one inverted - the accents are darkened, because
the dark palette's accents are chosen to sit on near-black and wash out on
white.

``apply`` writes the brushes straight onto ``window.Resources``, which sits in
front of a merged dictionary in WPF's lookup order. That is what lets the
palette be swapped on an open window with no reload and no loss of state.
"""

import ps_refs  # noqa: F401  - must be first, see its docstring

from System.Windows.Media import Color, ColorConverter, SolidColorBrush


# Revit's own dark theme (1.50.0), measured from Revit's dark Project
# Browser: title bar #222933, body #3C4454, search field #2D3441, hover
# #444E5E, selection Revit's active blue #3A7392 - the same family as
# Project Browser Pro's. Blue is a step brighter than the house blue so it
# still reads on the lighter body.
DARK = {
    'WindowBg':        '#3C4454',
    'CardBg':          '#353D4B',
    'FieldBg':         '#2D3441',
    'BarBg':           '#222933',
    'HeaderBg':        '#323C48',
    'TabActiveBg':     '#353D4B',
    'TabInactiveBg':   '#2B313C',
    'EdgeBrush':       '#4A5464',
    'WindowEdgeBrush': '#515C6B',
    'GridLineBrush':   '#46505F',
    'HoverBrush':      '#444E5E',
    'TextBrush':       '#EEF0F4',
    'MutedBrush':      '#A4AAB1',
    'DisabledBrush':   '#6E7684',
    'BlueBrush':       '#5AAEEB',
    'OrangeBrush':     '#E8912D',
    'GreenBrush':      '#3FA75A',
    'GreenHoverBrush': '#4EC06D',
    # Text sitting on a solid orange fill: near-black on the bright dark-mode
    # orange, white on the deeper light-mode one.
    'OnOrangeBrush':   '#1E1E20',
    # A faint wash of green behind the Export to Excel button.
    'GreenWashBrush':  '#3D5855',
    # A faint wash of orange down a revision column picked on the register.
    'PickWashBrush':   '#5E534C',
    'RedBrush':        '#D9534F',
    'SelectionBrush':  '#3A7392',
    'RowAltBrush':     '#394151',
    'ChipBg':          '#323C48',
    # One colour per sort level, so which column is first and which is
    # third is readable without counting the badges.
    'SortL1':          '#E8912D',
    'SortL2':          '#4FA3E3',
    'SortL3':          '#3FA75A',
    'SortL4':          '#A98BE8',
    'SortL5':          '#46BFBF',
    'SortL6':          '#D9B23C',
    # One colour per export format, so a glance at the Format tab says
    # which formats are ticked without reading the labels.
    'DoneRowBrush':   '#3D5D56',
    'FailedRowBrush': '#634853',
    'FmtPdf':         '#D0443A',
    'FmtDwg':         '#2C6FC4',
    'FmtDwf':         '#6E7684',
    'FmtNwc':         '#1F9C9C',
    'FmtIfc':         '#5A6BD6',
    'FmtDwgInk':      '#F2B417',
    'FmtNwcInk':      '#6FD8D8',
    'FmtIfcInk':      '#C3CBF5',
}

LIGHT = {
    'WindowBg':        '#F2F2F4',
    'CardBg':          '#FFFFFF',
    'FieldBg':         '#FFFFFF',
    'BarBg':           '#E4E4E8',
    'HeaderBg':        '#EAEAEE',
    'TabActiveBg':     '#FFFFFF',
    'TabInactiveBg':   '#DEDEE4',
    'EdgeBrush':       '#C8C8CE',
    'WindowEdgeBrush': '#B4B4BC',
    'GridLineBrush':   '#DCDCE2',
    'HoverBrush':      '#E8E8EC',
    'TextBrush':       '#1E1E20',
    'MutedBrush':      '#6A6A70',
    'DisabledBrush':   '#A8A8AE',
    'BlueBrush':       '#1B72BE',
    'OrangeBrush':     '#B96A12',
    'GreenBrush':      '#2E8546',
    'GreenHoverBrush': '#3A9C56',
    'OnOrangeBrush':   '#FFFFFF',
    'GreenWashBrush':  '#E3F2E7',
    'PickWashBrush':   '#FBEAD6',
    'RedBrush':        '#B5342F',
    'SelectionBrush':  '#CADEF0',
    'RowAltBrush':     '#F7F7F9',
    'ChipBg':          '#DCDCE2',
    'SortL1':          '#B96A12',
    'SortL2':          '#1B72BE',
    'SortL3':          '#2E8546',
    'SortL4':          '#6E4CC4',
    'SortL5':          '#1E8C8C',
    'SortL6':          '#96760F',
    'DoneRowBrush':   '#DCEFE0',
    'FailedRowBrush': '#F6DDDE',
    'FmtPdf':         '#B8322A',
    'FmtDwg':         '#1B5FB4',
    'FmtDwf':         '#8A8A90',
    'FmtNwc':         '#14807F',
    'FmtIfc':         '#4353BE',
    'FmtDwgInk':      '#E5A80C',
    'FmtNwcInk':      '#5FC6C6',
    'FmtIfcInk':      '#B6BFF0',
}

PALETTES = {'dark': DARK, 'light': LIGHT}

# The sort level colours in order, for code that needs the nth one.
SORT_LEVEL_KEYS = ['SortL1', 'SortL2', 'SortL3', 'SortL4', 'SortL5', 'SortL6']


def sort_level_key(level):
    """The palette key for sort level 0, 1, 2... wrapping past the sixth."""
    try:
        return SORT_LEVEL_KEYS[int(level) % len(SORT_LEVEL_KEYS)]
    except Exception:
        return SORT_LEVEL_KEYS[0]

# ==========================================================================
# a colour per group
#
# The six sort level colours are a fixed list because there are only ever
# six sort levels. Groups are not like that: a column of disciplines has
# as many groups as it has values, and every one of them wants to be
# told apart from its neighbours. So they are generated rather than
# listed - evenly spaced hues at a fixed saturation and lightness, tuned
# per theme so the text on top stays readable.
#
# Starting at the house orange means the first group looks like the rest
# of the window, and the eye only meets the wider spread once there is a
# reason for it.
# ==========================================================================

GROUP_HUES = 12
GROUP_START_HUE = 28.0

# saturation, lightness for a cell, lightness for a heading band.
#
# The heading is the *quieter* of the two, not the louder one. Its text
# is blue, and blue on a saturated green or teal band cannot be read -
# so the band is a dark tint of the hue in dark mode and a pale one in
# light mode, which keeps the group identifiable while leaving the text
# somewhere to sit. The full strength colour still appears, on the cells
# of the sorted column, which is where the eye is doing the matching.
GROUP_TONE = {
    # Cells a step lighter from 1.50.0, so a chip stands off Revit's
    # lighter dark body (#3C4454) rather than sinking into it.
    'dark':  (0.42, 0.36, 0.17),
    'light': (0.72, 0.78, 0.945),
}


def _hue_to_channel(p, q, t):
    if t < 0:
        t += 1.0
    if t > 1:
        t -= 1.0
    if t < 1.0 / 6.0:
        return p + (q - p) * 6.0 * t
    if t < 0.5:
        return q
    if t < 2.0 / 3.0:
        return p + (q - p) * (2.0 / 3.0 - t) * 6.0
    return p


def hsl(hue, saturation, lightness):
    """An HSL triple as a #RRGGBB string. Hue in degrees.

    Hand rolled rather than taken from colorsys so this module keeps
    working whatever a given IronPython build ships in its standard
    library.
    """
    h = (float(hue) % 360.0) / 360.0
    s = max(0.0, min(1.0, float(saturation)))
    l = max(0.0, min(1.0, float(lightness)))
    if s == 0:
        red = green = blue = l
    else:
        q = l * (1.0 + s) if l < 0.5 else l + s - l * s
        p = 2.0 * l - q
        red = _hue_to_channel(p, q, h + 1.0 / 3.0)
        green = _hue_to_channel(p, q, h)
        blue = _hue_to_channel(p, q, h - 1.0 / 3.0)
    return '#{0:02X}{1:02X}{2:02X}'.format(
        int(round(red * 255)), int(round(green * 255)),
        int(round(blue * 255)))


def group_colour(index, theme_name, heading=False):
    """The nth group's colour, as a hex string.

    Cycles after GROUP_HUES, which is as many distinct hues as can be
    told apart at this saturation. Two groups that far apart in a sorted
    list are never adjacent, so a repeat is not a collision worth
    solving.
    """
    saturation, cell, head = GROUP_TONE.get(str(theme_name).lower(),
                                            GROUP_TONE['dark'])
    hue = GROUP_START_HUE + (int(index) % GROUP_HUES) * (360.0 / GROUP_HUES)
    return hsl(hue, saturation, head if heading else cell)


_brush_cache = {}


def palette(name):
    """The palette dictionary for 'dark' or 'light'; dark for anything else."""
    return PALETTES.get(str(name).strip().lower(), DARK)


def brush(hex_text):
    """A frozen SolidColorBrush for a hex string, cached and shared."""
    key = str(hex_text)
    found = _brush_cache.get(key)
    if found is not None:
        return found
    made = SolidColorBrush(ColorConverter.ConvertFromString(key))
    try:
        made.Freeze()
    except Exception:
        pass
    _brush_cache[key] = made
    return made


def tinted(hex_text, alpha):
    """The same colour at a fraction of its strength.

    Used for the rows under a group heading: full strength on the heading
    so it reads as a divider, a wash on its members so the eye can follow
    a group down the page without the colour fighting the text.
    """
    try:
        base = ColorConverter.ConvertFromString(u'{0}'.format(hex_text))
        faded = Color.FromArgb(int(max(0, min(255, alpha))),
                               base.R, base.G, base.B)
        made = SolidColorBrush(faded)
        try:
            made.Freeze()
        except Exception:
            pass
        return made
    except Exception:
        return brush(hex_text)


def colour(theme_name, key):
    """The hex string for a palette key, falling back to the dark palette."""
    pal = palette(theme_name)
    return pal.get(key, DARK.get(key, '#FF00FF'))


def apply(window, theme_name):
    """Write every brush of the named palette onto the window's own resources.

    Local resources sit in front of the merged Theme.xaml in WPF's lookup
    order, so every DynamicResource in the layout re-resolves to these and the
    open window repaints without being rebuilt.
    """
    pal = palette(theme_name)
    for key in sorted(pal.keys()):
        try:
            window.Resources[key] = brush(pal[key])
        except Exception:
            pass
    apply_system_colours(window, pal)
    return pal


def apply_system_colours(window, pal):
    """Put the palette behind Windows' own selection brushes too.

    Anything that falls back to a default control template paints its
    selection with SystemColors, and on Windows 10 and 11 the inactive
    one is near white - so a selected row in a grid that has lost focus,
    which is what happens the moment a heading is clicked, comes out as a
    white bar across a dark window.

    Keyed by the SystemColors key objects rather than by name, so these
    cannot go through the palette loop above. Each one is written on its
    own: the inactive pair only exists from .NET 4.5, and a release
    without it should lose that key rather than the three around it.
    """
    try:
        from System.Windows import SystemColors
    except Exception:
        return
    wanted = [
        ('HighlightBrushKey', 'SelectionBrush'),
        ('HighlightTextBrushKey', 'TextBrush'),
        ('InactiveSelectionHighlightBrushKey', 'SelectionBrush'),
        ('InactiveSelectionHighlightTextBrushKey', 'TextBrush'),
        ('ControlBrushKey', 'CardBg'),
        ('WindowBrushKey', 'WindowBg'),
    ]
    for name, palette_key in wanted:
        try:
            key = getattr(SystemColors, name, None)
            if key is None:
                continue
            window.Resources[key] = brush(pal[palette_key])
        except Exception:
            continue


def detect_revit_theme(default='dark'):
    """Whatever light/dark mode Revit's own canvas is set to right now.

    ``UIThemeManager`` arrived in Revit 2024 and is the only honest source for
    this - the alternative is reading the registry, which lags the live
    setting. Anything unexpected falls back to the caller's default rather
    than throwing, because this is only ever a starting guess.
    """
    try:
        from Autodesk.Revit.UI import UIThemeManager, UITheme
        current = UIThemeManager.CurrentTheme
        if current == UITheme.Light:
            return 'light'
        if current == UITheme.Dark:
            return 'dark'
    except Exception:
        pass
    return default


MODES = ('follow', 'dark', 'light')


def mode(setting_value):
    """The saved setting as one of the three modes.

    Anything unrecognised - including a blank first run and the palette
    names older versions wrote here by mistake - comes back as 'follow',
    which is the house standard: match whatever Revit's canvas is set to.
    """
    text = str(setting_value or '').strip().lower()
    return text if text in MODES else 'follow'


def resolve(setting_value, default='dark'):
    """Turn a saved theme setting into an actual palette name.

    'follow' means take Revit's current canvas theme, which is what the
    project standard asks for; 'dark' and 'light' pin it.
    """
    text = str(setting_value or '').strip().lower()
    if text in ('dark', 'light'):
        return text
    return detect_revit_theme(default)
