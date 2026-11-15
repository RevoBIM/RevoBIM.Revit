# -*- coding: utf-8 -*-
"""The dark and light palettes.

Every brush and control template lives in Theme.xaml.  The palette here is
written straight onto window.Resources, which sits IN FRONT of a merged
dictionary in WPF's lookup order, so the palette can be swapped on an open
window with no reload and no loss of state.

The light palette is not the dark one inverted: the accents are darkened,
because the dark palette's accents are chosen to sit on near black and wash out
on white.
"""

import fv_clr  # noqa: F401  - must be first

# Revit's own dark theme, not the house near-black.  Sampled from Revit's dark
# Project Browser and shared with Project Browser Pro, Filter Manager and Pro
# Sheets Exporter (see "RevoBIM theme reference" in the project), so the tool
# sits inside Revit's greys rather than as a black hole on top of them.
#
# The body is far lighter than the old near-black, which drags the house muted
# grey and blue under a 4:1 contrast - they are lifted to the values the other
# Revit-dark tools use.  The bench checks every one of these against the
# reference and every text colour against every background it sits on.
REVIT_DARK = {
    'BarBg':    '#222933',      # title bar
    'WindowBg': '#3C4454',      # body
    'FieldBg':  '#2D3441',      # search boxes, fields
    'CardBg':   '#323C48',      # table headings, chips, toolbar
    'HoverBg':  '#444E5E',
    'SelBg':    '#3A7392',      # Revit's active blue
    'ChromeEdge': '#515C6B',    # window edge
    'FgBody':   '#EEF0F4',
    'FgMuted':  '#A4AAB1',
    'AccentBlue': '#5AAEEB',
}

DARK = {
    'WindowBg':         REVIT_DARK['WindowBg'],
    'CardBg':           REVIT_DARK['CardBg'],
    'FieldBg':          REVIT_DARK['FieldBg'],
    'BarBg':            REVIT_DARK['BarBg'],
    'PopupBg':          REVIT_DARK['CardBg'],
    'EdgeBrush':        '#48525F',
    'ChromeEdge':       REVIT_DARK['ChromeEdge'],
    'GridLine':         '#46505E',
    'FgBody':           REVIT_DARK['FgBody'],
    'FgMuted':          REVIT_DARK['FgMuted'],
    'FgOnAccent':       '#14181E',
    'AccentBlue':       REVIT_DARK['AccentBlue'],
    'AccentBlueDim':    '#3A7392',
    'AccentOrange':     '#F0A045',
    'AccentOrangeHover': '#F7B565',
    'AccentGreen':      '#5CC97A',
    'AccentGreenHover': '#72D68D',
    'WarnRed':          '#FA928E',
    'SelBg':            REVIT_DARK['SelBg'],
    'HoverBg':          REVIT_DARK['HoverBg'],
    'RowAlt':           '#404859',
    'ScrollThumb':      '#5A6576',
    'ScrollThumbHover': '#6E7A8C',
    'DisabledFg':       '#7F8896',
    'DisabledBg':       '#353D4A',
    'TickBlue':         REVIT_DARK['AccentBlue'],
    'TickOrange':       '#F0A045',
    # the band behind a family row: a step DARKER than the body, as Revit's own
    # browser does for a group, so a bank of types reads as one block
    'FamilyRowBg':      '#323A48',
    # a value staged from a workbook, and the band behind a family holding one
    'AccentTeal':       '#52CCC4',
    'ImportRowBg':      '#27434B',
}

LIGHT = {
    # the band behind a family row, so a bank of types reads as one block
    'FamilyRowBg': '#E8ECF1',
    'AccentTeal':       '#0E7670',
    'ImportRowBg':      '#D3EEEA',
    'WindowBg':         '#F1F1F4',
    'CardBg':           '#FFFFFF',
    'FieldBg':          '#FFFFFF',
    'BarBg':            '#E4E4EA',
    'PopupBg':          '#FFFFFF',
    'EdgeBrush':        '#C7C7CF',
    'ChromeEdge':       '#B4B4BE',
    'GridLine':         '#DEDEE4',
    'FgBody':           '#1E1E22',
    'FgMuted':          '#63636C',
    'FgOnAccent':       '#FFFFFF',
    'AccentBlue':       '#1B72BE',
    'AccentBlueDim':    '#7FAFD6',
    'AccentOrange':     '#B96A12',
    'AccentOrangeHover': '#D07E1F',
    'AccentGreen':      '#2E8546',
    'AccentGreenHover': '#37A05A',
    'WarnRed':          '#B23B37',
    'SelBg':            '#CFE3F5',
    'HoverBg':          '#EAEAF0',
    'RowAlt':           '#F7F7FA',
    'ScrollThumb':      '#B4B4BE',
    'ScrollThumbHover': '#93939E',
    'DisabledFg':       '#A0A0AA',
    'DisabledBg':       '#EDEDF1',
    'TickBlue':         '#1B72BE',
    'TickOrange':       '#B96A12',
}

# every key both palettes must carry; the bench check compares against this
KEYS = sorted(DARK.keys())

PALETTES = {'dark': DARK, 'light': LIGHT}


FOLLOW = 'follow'
SETTINGS = (FOLLOW, 'dark', 'light')


def palette(name):
    return PALETTES.get(str(name).strip().lower(), DARK)


def resolve(setting, canvas):
    """Which palette to show.

    `setting` is what is saved - follow, dark or light - and `canvas` is what
    Revit says its canvas is, or None where it cannot say.  Following is a
    state in its own right rather than the absence of a choice, so a user who
    picked dark keeps dark when Revit is light.
    """
    chosen = str(setting or FOLLOW).strip().lower()
    if chosen in ('dark', 'light'):
        return chosen
    if canvas in ('dark', 'light'):
        return canvas
    return 'dark'


def revit_canvas():
    """'dark' or 'light' from Revit's own canvas theme, or None.

    UIThemeManager only exists from Revit 2024, so it is reached by getattr on
    the namespace rather than imported at module load.  UITheme.Dark is 0, so
    a read is tested with `is not None` - testing it for truth reported every
    dark canvas as a failed read and fell through to light.
    """
    try:
        import Autodesk.Revit.UI as revit_ui
    except Exception:
        return None
    # not getattr(..., None): that only swallows AttributeError, and a name an
    # older Revit does not have can surface as something else
    try:
        manager = revit_ui.UIThemeManager
        kinds = revit_ui.UITheme
    except Exception:
        return None
    if manager is None or kinds is None:
        return None
    for name in ('CurrentCanvasTheme', 'CurrentTheme'):
        try:
            value = getattr(manager, name)
        except Exception:
            continue
        if value is None:
            continue
        try:
            if value == kinds.Dark:
                return 'dark'
            if value == kinds.Light:
                return 'light'
        except Exception:
            continue
    return None


def other(name):
    return 'light' if str(name).strip().lower() == 'dark' else 'dark'


def apply(window, name):
    """Write the palette's brushes straight onto window.Resources."""
    from System.Windows.Media import BrushConverter

    converter = BrushConverter()
    chosen = palette(name)
    for key in sorted(chosen.keys()):
        try:
            window.Resources[key] = converter.ConvertFromString(chosen[key])
        except Exception:
            pass
    return chosen
