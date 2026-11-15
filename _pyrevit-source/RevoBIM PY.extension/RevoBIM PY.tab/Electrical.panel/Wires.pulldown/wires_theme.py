# -*- coding: utf-8 -*-
"""RevoBIM PY - Wires: the two palettes and which one is in force.

Pure Python - no clr, no WPF - so the logic bench can prove every rule here.
Painting a window is wires_ui's job; this module only decides the colours.

The setting is stored as follow / dark / light, so following Revit is a state
rather than the absence of one. Follow reads Revit's *canvas* theme, which is
the drawing area the windows sit over, and falls back to the UI theme.
"""

FOLLOW = 'follow'
DARK = 'dark'
LIGHT = 'light'
MODES = (FOLLOW, DARK, LIGHT)

# Both palettes carry exactly the same keys - a key missing from one is a
# brush left behind at its dark default after a swap. The bench checks it, and
# checks every key has a fallback brush in Theme.xaml.
PALETTES = {
    DARK: {
        'Shell': '#232326',
        'Card': '#2B2B2E',
        'Field': '#1C1C1F',
        'Bar': '#1C1C1F',
        'Edge': '#3E3E42',
        'Rim': '#4A4A50',
        'Fg': '#E4E4E4',
        'Muted': '#9A9A9E',
        'Blue': '#4FA3E3',
        'Orange': '#E8912D',
        'Green': '#3FA75A',
        'GreenHi': '#4EC06D',
        'Red': '#D9534F',
        'Sel': '#2B5473',
        'Ghost': '#33333A',
        'Disabled': '#3A3A3E',
        'DisabledFg': '#77777B',
        'OnAccent': '#FFFFFF',
        # what sits on a blue fill - a checkbox tick, the lit segment. Dark
        # navy on the pale dark-mode blue, white on the deeper light-mode one;
        # one colour is weak against one of the two blues.
        'OnBlue': '#0E2233',
    },
    LIGHT: {
        'Shell': '#F3F3F5',
        'Card': '#FFFFFF',
        'Field': '#FAFAFB',
        'Bar': '#E6E6EA',
        'Edge': '#C8C8CE',
        'Rim': '#B4B4BC',
        'Fg': '#1E1E22',
        'Muted': '#6A6A72',
        # the accents are darkened, not inverted - the dark ones are chosen to
        # sit on near-black and wash out on white
        'Blue': '#1B72BE',
        'Orange': '#B96A12',
        'Green': '#2E8546',
        'GreenHi': '#38A055',
        'Red': '#C0392B',
        'Sel': '#CFE3F5',
        'Ghost': '#E1E1E6',
        'Disabled': '#DCDCE0',
        'DisabledFg': '#9A9AA0',
        'OnAccent': '#FFFFFF',
        'OnBlue': '#FFFFFF',
    },
}

# what the chip says for each stored mode
CHIP_TEXT = {FOLLOW: 'Auto', DARK: 'Dark', LIGHT: 'Light'}


def normalise(mode):
    """A stored value read back as one of MODES. Anything else follows."""
    text = str(mode or '').strip().lower()
    if text in MODES:
        return text
    if text in ('auto', 'revit', 'canvas'):
        return FOLLOW
    return FOLLOW


def next_mode(mode):
    """The chip's cycle: Auto, then Dark, then Light, then back to Auto."""
    mode = normalise(mode)
    return MODES[(MODES.index(mode) + 1) % len(MODES)]


def is_dark_value(value):
    """True for a dark Revit theme, False for light, None for not known.

    Compared by name. `UITheme.Dark` is 0, so a truthiness test reads dark as
    'not set' - that is the bug this function exists to rule out - and the
    enum is never imported, because its home has moved before.
    """
    if value is None:
        return None
    try:
        text = str(value).strip().lower()
    except Exception:
        return None
    if 'dark' in text:
        return True
    if 'light' in text:
        return False
    return None


def resolve(mode, canvas_dark):
    """The palette name in force for a stored mode and what Revit says.

    Following with nothing to follow (Revit 2023 and older, or the read
    failing) lands on dark, the house default.
    """
    mode = normalise(mode)
    if mode in (DARK, LIGHT):
        return mode
    if canvas_dark is False:
        return LIGHT
    return DARK


def chip_text(mode, resolved):
    """'Auto - Dark' while following, so the chip says what it is showing."""
    mode = normalise(mode)
    if mode == FOLLOW:
        return '{0} · {1}'.format(CHIP_TEXT[FOLLOW],
                                       CHIP_TEXT.get(resolved, 'Dark'))
    return CHIP_TEXT[mode]


def chip_tip(mode, resolved):
    mode = normalise(mode)
    if mode == FOLLOW:
        return ('Following Revit\'s canvas ({0}). Click for Dark, then '
                'Light, then back to following Revit.'.format(resolved))
    return ('{0} theme, whatever Revit is using. Click to change.'.format(
        CHIP_TEXT[mode]))


def hex_of(name, key):
    """A palette colour by key, for code that has to paint by hand."""
    palette = PALETTES.get(name) or PALETTES[DARK]
    return palette.get(key) or PALETTES[DARK].get(key) or '#9A9A9E'
