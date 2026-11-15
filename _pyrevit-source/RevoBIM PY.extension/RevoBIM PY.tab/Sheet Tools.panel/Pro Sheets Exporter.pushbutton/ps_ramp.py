# -*- coding: utf-8 -*-
"""Heading colours: Project Browser Pro's trade ramps, shared look.

Project Browser Pro colours its main headings by **trade**, each a solid
pill shaded along that trade's ramp: electrical greens, mechanical blues,
plumbing browns, everything else violets - the same ramps on both themes.
Headings of one trade under the same parent are placed dark to light in
list order; the first level sits at the dark end of the ramp, the second
level in the lighter part, so a series reads as belonging to the
discipline above it. Text on a pill is black or white, whichever has the
better WCAG contrast.

The Document Register and the Selection tab's groups use the same tables
here so Pro Sheets and the browser look like one product. Kept in step
with ``pbp_palette.RAMPS`` / ``LADDER`` by hand: they are two tools'
constants, not a contract between them, and a copy is cheaper than making
one tool load the other's palette at start up.

Pure Python - no .NET - so the bench can check every number.
"""

ELECTRICAL = 'electrical'
MECHANICAL = 'mechanical'
PLUMBING = 'plumbing'
OTHER = 'other'

# Darkest to lightest, per trade.
RAMPS = {
    ELECTRICAL: ('#17572B', '#A9DFA6'),
    MECHANICAL: ('#173F78', '#A9D0F4'),
    PLUMBING: ('#4F3220', '#D9B892'),
    OTHER: ('#4B2A6E', '#CDB2EA'),
}

# Where on the ramp each heading level is placed, dark end first.
LADDER = {
    1: (0.0, 0.3),
    2: (0.38, 0.95),
}

# One level of grouping only (the Selection tab): the whole ramp, so
# neighbouring groups still differ.
SINGLE_LEVEL = {1: (0.0, 0.95)}

# The words that name a trade, matched as whole words; first match wins.
# Fire protection is "other" as in Project Browser Pro, and comes before
# fire alarm's electrical; mechanical comes before plumbing so chilled
# water is a blue and hot water a brown.
TRADE_WORDS = [
    (OTHER, ['FIRE PROTECTION', 'SPRINKLER', 'SPRINKLERS', 'SUPPRESSION',
             'DRY RISER', 'WET RISER']),
    (ELECTRICAL, ['FIRE ALARM', 'FIRE ALARMS', 'FIRE DETECTION', 'SECURITY',
                  'CCTV', 'ACCESS CONTROL', 'LIGHTING', 'LIGHTNING',
                  'EMERGENCY LIGHTING', 'DATA', 'COMMS', 'COMMUNICATIONS',
                  'TELECOMS', 'CONTAINMENT', 'POWER', 'SMALL POWER',
                  'ELECTRICAL', 'ELECTRICS', 'ELEC', 'LV', 'HV',
                  'EARTHING', 'CABLE', 'CABLES', 'CABLING']),
    (MECHANICAL, ['MECHANICAL', 'MECH', 'HVAC', 'HEATING', 'COOLING',
                  'CHILLED', 'CONDENSER', 'PIPEWORK', 'PIPES', 'PIPING',
                  'DUCTWORK', 'DUCT', 'DUCTS', 'AIR', 'VENTILATION',
                  'REFRIGERATION', 'REFRIGERANT', 'FAN', 'FANS', 'LTHW',
                  'CHW', 'BMS']),
    (PLUMBING, ['PLUMBING', 'PUBLIC HEALTH', 'PH', 'PHE', 'DRAINAGE',
                'DRAINS', 'SOIL', 'WASTE', 'RAINWATER', 'WATER SERVICES',
                'WATER', 'SANITARY', 'SANITARYWARE']),
]

_SEPARATORS = u'_-/&,.()[]:;+'


def _words(text):
    try:
        text = u'{0}'.format(text or u'')
    except Exception:
        return u' '
    text = text.upper()
    for mark in _SEPARATORS:
        text = text.replace(mark, u' ')
    return u' ' + u' '.join(text.split()) + u' '


def trade_of(text):
    """The trade a heading's name speaks for, or None when it names none."""
    padded = _words(text)
    for trade, words in TRADE_WORDS:
        for word in words:
            if u' ' + word + u' ' in padded:
                return trade
    return None


def _channels(hex_text):
    text = u'{0}'.format(hex_text).lstrip(u'#')
    if len(text) == 8:
        text = text[2:]                        # #AARRGGBB
    return [int(text[i:i + 2], 16) for i in (0, 2, 4)]


def _hex(channels):
    return u'#{0:02X}{1:02X}{2:02X}'.format(
        *[int(round(max(0, min(255, value)))) for value in channels])


def mix(dark, light, amount):
    """``amount`` of the way from dark to light, 0 to 1."""
    amount = max(0.0, min(1.0, float(amount)))
    low = _channels(dark)
    high = _channels(light)
    return _hex([low[i] + (high[i] - low[i]) * amount for i in range(3)])


def shade(trade, amount):
    dark, light = RAMPS.get(trade, RAMPS[OTHER])
    return mix(dark, light, amount)


def _luminance(hex_text):
    total = 0.0
    for weight, value in zip((0.2126, 0.7152, 0.0722), _channels(hex_text)):
        part = value / 255.0
        part = part / 12.92 if part <= 0.03928 else \
            ((part + 0.055) / 1.055) ** 2.4
        total += weight * part
    return total


def contrast(first, second):
    one = _luminance(first) + 0.05
    two = _luminance(second) + 0.05
    return max(one, two) / min(one, two)


def text_on(hex_text):
    """Black or white, whichever reads better on this colour."""
    if contrast(hex_text, u'#000000') >= contrast(hex_text, u'#FFFFFF'):
        return u'#000000'
    return u'#FFFFFF'


def plan(headings, inherit=None, ladder=None):
    """Every heading's colour: {id: hex}.

    ``headings`` is (id, label, level, parent id) in list order. A heading
    whose name names no trade takes its parent's, then ``inherit`` (the
    label of whatever the list sits under - a discipline's own tab), then
    "other". Per level, headings of one trade under the same parent are
    spread dark to light across that level's part of the ramp, in order.
    """
    ladder = ladder or LADDER
    fallback = trade_of(inherit) if inherit else None
    trades = {}
    order = []
    runs = {}
    for hid, label, level, parent in headings:
        trade = trade_of(label) or trades.get(parent) or fallback or OTHER
        trades[hid] = trade
        key = (level, parent, trade)
        if key not in runs:
            runs[key] = []
            order.append(key)
        runs[key].append(hid)
    found = {}
    top = max(ladder) if ladder else 1
    for key in order:
        level, _parent, trade = key
        low, high = ladder.get(level, ladder[top])
        members = runs[key]
        count = len(members)
        for index, hid in enumerate(members):
            amount = low if count == 1 else \
                low + (high - low) * index / float(count - 1)
            found[hid] = shade(trade, amount)
    return found


# ==========================================================================
# heading colour modes (1.52.0): the Document Register's headings can wear
# the trade ramps, plain greys, or colours picked heading by heading
# ==========================================================================

COLOURED = 'colour'
GREY = 'grey'
CUSTOM = 'custom'
HEADING_MODES = [COLOURED, GREY, CUSTOM]
MODE_LABELS = {COLOURED: u'Coloured headers', GREY: u'Grey headers',
               CUSTOM: u'Custom headers'}

# Plain headings: darker for a discipline, lighter for a series - on dark,
# a step either side of Revit's body; on light, two greys under white.
GREYS = {
    'dark': {1: '#2B313C', 2: '#4A5464'},
    'light': {1: '#8E97A3', 2: '#C9CED6'},
}

# The swatches offered for a heading: each ramp's dark, middle and light,
# then the house accents and two greys.
SWATCHES = ['#17572B', '#4E8B5A', '#A9DFA6',
            '#173F78', '#4E76A7', '#A9D0F4',
            '#4F3220', '#83654B', '#D9B892',
            '#4B2A6E', '#7C5E9D', '#CDB2EA',
            '#8B1E1E', '#D9534F', '#E8912D',
            '#D9B23C', '#1F9C9C', '#2B313C']


def heading_mode(text):
    """A stored mode, or Coloured for anything unknown."""
    text = u'{0}'.format(text or u'').strip().lower()
    return text if text in HEADING_MODES else COLOURED


def next_mode(mode):
    """The mode the button moves on to: Coloured, Grey, Custom, round."""
    mode = heading_mode(mode)
    return HEADING_MODES[(HEADING_MODES.index(mode) + 1) %
                         len(HEADING_MODES)]


def grey(level, theme_name):
    shades = GREYS.get(u'{0}'.format(theme_name).lower(), GREYS['dark'])
    return shades.get(1 if int(level or 1) <= 1 else 2)


def mode_colour(mode, ramp, level, theme_name, custom=None):
    """The colour a heading wears in a mode. Custom starts from the greys
    (1.53.0): only the headings given a colour stand out."""
    mode = heading_mode(mode)
    if mode == GREY:
        return grey(level, theme_name)
    if mode == CUSTOM:
        return custom or grey(level, theme_name)
    return ramp


def parse_hex(text):
    """'#RRGGBB' from what was typed ('3fa75a', '#3FA75A'), or None."""
    text = u'{0}'.format(text or u'').strip().lstrip(u'#').upper()
    if len(text) != 6:
        return None
    for char in text:
        if char not in u'0123456789ABCDEF':
            return None
    return u'#' + text
