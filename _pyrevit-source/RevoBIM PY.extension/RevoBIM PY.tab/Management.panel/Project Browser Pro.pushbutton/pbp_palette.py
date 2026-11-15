# -*- coding: utf-8 -*-
u"""Project Browser Pro - the house palettes and group colours as plain data.

Pure Python so the bench can check both palettes carry the same keys and
that every key Theme.xaml asks for exists. pbp_theme turns these into brushes.

The light palette is not the dark one inverted: the accents are darkened
because the dark palette's accents are chosen to sit on near-black and wash
out on white.
"""
from pbp_compat import to_text

# Dark is Revit's own dark theme (2024+), measured from the Properties
# palette: navy title / section bands, slate body and rows, a darker bottom
# bar, slate-grey separators and edges, Revit's active blue. The RevoBIM
# accents (blue, orange, green and the type colours) stay on top of it.
DARK = {
    u'BgBrush': u'#3B4453',          # Revit panel body
    u'CardBrush': u'#2E3440',        # menus, tooltips, progress strip
    u'FieldBrush': u'#3B4453',       # list rows and inputs, as Properties
    u'BarBrush': u'#222933',         # title bar and section bands
    u'BottomBrush': u'#2E3440',      # Revit's bottom bar (footer)
    u'EdgeBrush': u'#444E5E',        # row separators
    u'ChromeEdgeBrush': u'#515C6B',  # pane edges and splitters
    u'TextBrush': u'#F0F0F0',
    u'MutedBrush': u'#9AA0A6',       # Revit's read-only text
    u'BlueBrush': u'#4FA3E3',
    u'OrangeBrush': u'#E8912D',
    u'GreenBrush': u'#3FA75A',
    u'GreenHoverBrush': u'#4EC06D',
    u'RedBrush': u'#D9534F',
    u'SelectBrush': u'#3A7392',      # Revit's active / selected blue
    u'SelectEdgeBrush': u'#4F8DB3',
    u'HoverBrush': u'#444E5E',
    u'ChipBrush': u'#2E3440',
    u'DisabledBrush': u'#465060',
    u'DisabledTextBrush': u'#737578',
    u'OnAccentBrush': u'#FFFFFF',
    u'ScrollThumbBrush': u'#68768A',
    u'ScrollThumbHoverBrush': u'#7C8A9E',
    u'TreeLineBrush': u'#444E5E',
    u'ShadowBrush': u'#66000000',
    u'PanelBrush': u'#A78BEA',
    u'FamilyBrush': u'#3BB3A5',
    u'AllBrush': u'#E06C9F',
    u'FavBrush': u'#F2C94C',
    u'LegendBrush': u'#E57B5C',
    u'OrangeWashBrush': u'#33E8912D',
    u'PillShadowColor': u'#000000',
    u'RowShadowColor': u'#70000000',   # the shadow under each top row
    u'SearchBrush': u'#2B323E',        # Revit's darker search box
    u'SubTabBrush': u'#2B323E',        # the sub tab strip, the search box's grey
    u'SubTabOnBrush': u'#566173',      # the chosen sub tab
    u'OnSheetBrush': u'#2F7FCF',       # the inside of a placed view's icon
}

# Light is Revit's own light UI: neutral, very light greys for the bars and
# the frame (no blue tint), white for the list.
LIGHT = {
    u'BgBrush': u'#F5F5F5',
    u'CardBrush': u'#FFFFFF',
    u'FieldBrush': u'#FFFFFF',
    u'BarBrush': u'#F0F0F0',
    u'BottomBrush': u'#F0F0F0',
    u'EdgeBrush': u'#E1E1E1',
    u'ChromeEdgeBrush': u'#D4D4D4',
    u'TextBrush': u'#1E1E22',
    u'MutedBrush': u'#6A6A72',
    u'BlueBrush': u'#1B72BE',
    u'OrangeBrush': u'#B96A12',
    u'GreenBrush': u'#2E8546',
    u'GreenHoverBrush': u'#379A53',
    u'RedBrush': u'#C0392B',
    u'SelectBrush': u'#CCE4F7',
    u'SelectEdgeBrush': u'#1B72BE',
    u'HoverBrush': u'#E5ECF4',
    u'ChipBrush': u'#EDEDED',
    u'DisabledBrush': u'#E6E6E6',
    u'DisabledTextBrush': u'#A0A0A6',
    u'OnAccentBrush': u'#FFFFFF',
    u'ScrollThumbBrush': u'#BFC3CA',
    u'ScrollThumbHoverBrush': u'#A5AAB3',
    u'TreeLineBrush': u'#DADAE0',
    u'ShadowBrush': u'#33000000',
    u'PanelBrush': u'#6C4CC4',
    u'FamilyBrush': u'#1E8075',
    u'AllBrush': u'#B03A70',
    u'FavBrush': u'#B8860B',
    u'LegendBrush': u'#B2472A',
    u'OrangeWashBrush': u'#22B96A12',
    u'PillShadowColor': u'#5A6070',
    u'RowShadowColor': u'#1F000000',
    u'SearchBrush': u'#E8E8E8',
    u'SubTabBrush': u'#E8E8E8',
    u'SubTabOnBrush': u'#CFCFCF',
    u'OnSheetBrush': u'#A9D0F4',
}

# Icon colours per kind of row, (dark, light).
KIND_COLOURS = {
    u'view': (u'#4FA3E3', u'#1B72BE'),
    u'sheet': (u'#E8912D', u'#B96A12'),
    u'schedule': (u'#3FA75A', u'#2E8546'),
    u'panel': (u'#A78BEA', u'#6C4CC4'),
    u'family': (u'#3BB3A5', u'#1E8075'),
    u'fav': (u'#F2C94C', u'#B8860B'),
    u'legend': (u'#E57B5C', u'#B2472A'),
    u'group': (u'#9A9A9E', u'#6A6A72'),
}

# Group heading colours for the colour button. Chosen to read on both
# palettes once tinted; dark first, light second.
GROUP_COLOURS = [
    (u'#4FA3E3', u'#1B72BE'),
    (u'#E8912D', u'#B96A12'),
    (u'#3FA75A', u'#2E8546'),
    (u'#A78BEA', u'#6C4CC4'),
    (u'#3BB3A5', u'#1E8075'),
    (u'#E06C9F', u'#B03A70'),
    (u'#D9B84A', u'#9A7A12'),
    (u'#6FB7FF', u'#2F6FB5'),
    (u'#E57B5C', u'#B2472A'),
    (u'#8FC45A', u'#4E8A1E'),
]

# The names the Set colour window shows for each slot (favourites store the
# slot - c0 to c9 - not the colour, so a favourite follows dark and light).
COLOUR_NAMES = [u'Blue', u'Orange', u'Green', u'Purple', u'Teal', u'Pink',
                u'Gold', u'Sky', u'Coral', u'Lime']

TRANSPARENT = u'#00000000'

# Heading pills: how strong the fill and the edge are, by heading level
# (1 = View Group, 2 = View Purpose) and theme. Level 1 is the stronger.
PILL_ALPHA = {
    (1, u'dark'): (0x66, 0xC0),
    (2, u'dark'): (0x40, 0x90),
    (1, u'light'): (0x40, 0xB0),
    (2, u'light'): (0x26, 0x80),
}


def palette(name):
    return LIGHT if name == u'light' else DARK


def stable_index(text, size):
    u"""A colour slot that is the same on every run and every engine.

    Python's own hash() is salted per process on CPython 3, so it cannot be
    used for anything a user is meant to recognise from one day to the next.
    """
    total = 7
    for ch in to_text(text):
        total = (total * 31 + ord(ch)) % 1000003
    return total % size if size else 0


def group_colour(label, theme_name):
    pair = GROUP_COLOURS[stable_index(label, len(GROUP_COLOURS))]
    return pair[1] if theme_name == u'light' else pair[0]


def kind_colour(kind_family, theme_name):
    pair = KIND_COLOURS.get(kind_family, KIND_COLOURS[u'group'])
    return pair[1] if theme_name == u'light' else pair[0]


# Heading gradients, dark end first. Every electrical heading is a shade of
# green, mechanical (ductwork, heating, pipework) blue, plumbing (drainage,
# water services) brown, and everything else violet - a hue none of the
# other three is near. The same ramps on both themes: a heading is a solid
# pill with its text picked for contrast, so it reads on either.
RAMPS = {
    u'electrical': (u'#17572B', u'#A9DFA6'),
    u'mechanical': (u'#173F78', u'#A9D0F4'),
    u'plumbing': (u'#4F3220', u'#D9B892'),
    u'other': (u'#4B2A6E', u'#CDB2EA'),
}
DARK_TEXT = u'#1E1E22'
LIGHT_TEXT = u'#FFFFFF'


def _rgb(hex_colour):
    text = to_text(hex_colour).lstrip(u'#')
    if len(text) == 8:
        text = text[2:]
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


def _hex(rgb):
    return u'#{0:02X}{1:02X}{2:02X}'.format(*[max(0, min(255, int(round(v)))) for v in rgb])


def shade(family, t):
    u"""A colour along a family's ramp: t 0 is the dark end, 1 the light."""
    dark, light = RAMPS.get(family, RAMPS[u'other'])
    t = max(0.0, min(1.0, float(t)))
    a, b = _rgb(dark), _rgb(light)
    return _hex([a[i] + (b[i] - a[i]) * t for i in range(3)])


def luminance(hex_colour):
    u"""Relative luminance 0 (black) to 1 (white), WCAG weights."""
    def channel(value):
        value = value / 255.0
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4
    r, g, b = [channel(v) for v in _rgb(hex_colour)]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def text_on(hex_colour):
    u"""Black or white text, whichever has more contrast on this colour."""
    lum = luminance(hex_colour)
    on_white = 1.05 / (lum + 0.05)
    on_black = (lum + 0.05) / 0.05
    return LIGHT_TEXT if on_white >= on_black else DARK_TEXT


def heading_pill(family, t):
    u"""(fill, edge, text) for a solid heading pill at t along its ramp."""
    fill = shade(family, t)
    edge = shade(family, max(0.0, t - 0.18))
    return fill, edge, text_on(fill)


def own_pill(colour):
    u"""(fill, edge, text) for a heading the user coloured themselves."""
    r, g, b = _rgb(colour)
    edge = _hex([v * 0.72 for v in (r, g, b)])
    fill = _hex((r, g, b))
    return fill, edge, text_on(fill)


# The colours offered in Browser Organisation for a group of its own: each
# trade's ramp at its dark, middle and light, then the ten group colours.
# A highlight: a row marked for now (right click > Highlight), until it is
# turned off. A marker yellow on both themes. (fill, edge) by theme.
HIGHLIGHT = {u'dark': (u'#8A7420', u'#C9A93A'), u'light': (u'#FFF0A0', u'#E8CF52')}


def highlight(theme_name):
    return HIGHLIGHT[u'light' if theme_name == u'light' else u'dark']


GREYS = [u'#1F1F1F', u'#383838', u'#525252', u'#6B6B6B', u'#858585', u'#A0A0A0',
         u'#BABABA', u'#D4D4D4', u'#EBEBEB']


def choice_colours(custom=None):
    u"""Each trade's ramp at its dark, middle and light; the ten group
    colours; nine greys, black to near white; then the user's own."""
    out = []
    for family in (u'electrical', u'mechanical', u'plumbing', u'other'):
        for t in (0.0, 0.5, 1.0):
            out.append(shade(family, t))
    for dark, light in GROUP_COLOURS:
        out.append(dark)
    out.extend(GREYS)
    for colour in custom or []:
        if colour not in out:
            out.append(colour)
    return out


# With the colour button off the main headings keep their bars, in grey -
# barely there on the light theme. (fill, edge) by rank: 1 main, 2 below.
GREY_PILLS = {
    (1, u'dark'): (u'#535D6C', u'#636E7E'),
    (2, u'dark'): (u'#48515F', u'#58626F'),
    (1, u'light'): (u'#EBECEE', u'#DDDFE2'),
    (2, u'light'): (u'#F2F3F4', u'#E4E6E8'),
}


def grey_pill(rank, theme_name):
    return GREY_PILLS[(1 if rank <= 1 else 2, u'light' if theme_name == u'light' else u'dark')]


def ladder(count, first, last):
    u"""count positions from first to last, dark to light; one sits midway."""
    if count <= 0:
        return []
    if count == 1:
        return [(first + last) / 2.0]
    step = (last - first) / float(count - 1)
    return [first + step * i for i in range(count)]


def slot_colour(slot, theme_name):
    u"""A favourite's colour slot ('c0'..'c9') as '#RRGGBB', or None."""
    text = to_text(slot)
    if len(text) < 2 or not text[1:].isdigit():
        return None
    index = int(text[1:])
    if not 0 <= index < len(GROUP_COLOURS):
        return None
    pair = GROUP_COLOURS[index]
    return pair[1] if theme_name == u'light' else pair[0]


def pill(colour, level, theme_name):
    u"""(fill, edge) for a heading pill of this colour at this level."""
    level = 1 if level <= 1 else 2
    fill_alpha, edge_alpha = PILL_ALPHA[(level, u'light' if theme_name == u'light' else u'dark')]
    return tint(colour, fill_alpha), tint(colour, edge_alpha)


def tint(hex_colour, alpha):
    u"""'#RRGGBB' plus an alpha 0-255 as '#AARRGGBB' for a binding to convert."""
    text = to_text(hex_colour).lstrip(u'#')
    if len(text) == 8:
        text = text[2:]
    if len(text) != 6:
        return TRANSPARENT
    alpha = max(0, min(255, int(alpha)))
    return u'#{0:02X}{1}'.format(alpha, text.upper())
