# -*- coding: utf-8 -*-
u"""Project Browser Pro - row icons as WPF path markup.

Drawn as geometry, not images or a symbol font, so they cannot come out as
empty boxes on a machine without the font and they recolour with the theme.
Every path sits on a 12 x 12 grid and is drawn with Stretch="None", so the
literal coordinates are what appears.

Pure data - the bench parses every string to prove it is well formed.
"""

CHEV_RIGHT = u'M3.5,1.5 L7.5,5 L3.5,8.5'
CHEV_DOWN = u'M1.5,3.5 L5,7.5 L8.5,3.5'

ICONS = {
    u'plan': u'F0 M1,1 L11,1 L11,11 L1,11 Z M2.4,2.4 L2.4,9.6 L9.6,9.6 L9.6,2.4 Z '
             u'M5.4,2.4 L6.6,2.4 L6.6,7 L5.4,7 Z',
    u'ceiling': u'F0 M1,1 L11,1 L11,11 L1,11 Z M2.4,2.4 L2.4,9.6 L9.6,9.6 L9.6,2.4 Z '
                u'M2.4,5.4 L9.6,5.4 L9.6,6.6 L2.4,6.6 Z',
    u'area': u'F0 M1,1 L11,1 L11,11 L1,11 Z M2.4,2.4 L2.4,9.6 L9.6,9.6 L9.6,2.4 Z '
             u'M2.4,8.2 L8.2,2.4 L9.6,2.4 L9.6,3.8 L3.8,9.6 L2.4,9.6 Z',
    u'structural': u'M1,1 L11,1 L11,3 L7,3 L7,9 L11,9 L11,11 L1,11 L1,9 L5,9 L5,3 L1,3 Z',
    u'threed': u'F0 M6,0.8 L11.2,3.4 L11.2,8.6 L6,11.2 L0.8,8.6 L0.8,3.4 Z '
               u'M6,2.3 L9.4,4 L6,5.7 L2.6,4 Z',
    u'section': u'M0.5,5.2 L6.6,5.2 L6.6,6.8 L0.5,6.8 Z '
                u'M6.6,6 A2.4,2.4 0 1 0 11.4,6 A2.4,2.4 0 1 0 6.6,6 Z',
    u'elevation': u'M6,0.5 L9.2,4.2 L2.8,4.2 Z '
                  u'M3,8 A3,3 0 1 0 9,8 A3,3 0 1 0 3,8 Z',
    u'detail': u'F0 M1,6 A5,5 0 1 0 11,6 A5,5 0 1 0 1,6 Z '
               u'M2.6,6 A3.4,3.4 0 1 0 9.4,6 A3.4,3.4 0 1 0 2.6,6 Z',
    u'drafting': u'M8.5,0.8 L11.2,3.5 L4,10.7 L0.8,11.2 L1.3,8 Z',
    u'legend': u'M1,1.5 L3.5,1.5 L3.5,4 L1,4 Z M5,2.2 L11,2.2 L11,3.4 L5,3.4 Z '
               u'M1,5 L3.5,5 L3.5,7.5 L1,7.5 Z M5,5.7 L11,5.7 L11,6.9 L5,6.9 Z '
               u'M1,8.5 L3.5,8.5 L3.5,11 L1,11 Z M5,9.2 L11,9.2 L11,10.4 L5,10.4 Z',
    u'camera': u'M1,3 L8,3 L8,9 L1,9 Z M8,5.2 L11,3.2 L11,8.8 L8,6.8 Z',
    u'view': u'F0 M0.8,6 C2.5,2.6 9.5,2.6 11.2,6 C9.5,9.4 2.5,9.4 0.8,6 Z '
             u'M4.2,6 A1.8,1.8 0 1 0 7.8,6 A1.8,1.8 0 1 0 4.2,6 Z',
    u'dependent': u'M2,1 L3.5,1 L3.5,7 L8.5,7 L8.5,5.2 L11.5,8 L8.5,10.8 L8.5,9 L2,9 Z',
    u'sheet': u'F0 M2,0.5 L8,0.5 L10.5,3 L10.5,11.5 L2,11.5 Z '
              u'M3.2,8.4 L9.3,8.4 L9.3,10.3 L3.2,10.3 Z',
    u'schedule': u'F0 M1,1 L11,1 L11,11 L1,11 Z M2.2,4 L5.4,4 L5.4,5.8 L2.2,5.8 Z '
                 u'M6.6,4 L9.8,4 L9.8,5.8 L6.6,5.8 Z M2.2,7 L5.4,7 L5.4,9.8 L2.2,9.8 Z '
                 u'M6.6,7 L9.8,7 L9.8,9.8 L6.6,9.8 Z',
    u'panel': u'F0 M2,0.5 L10,0.5 L10,11.5 L2,11.5 Z M3.2,2 L8.8,2 L8.8,3.5 L3.2,3.5 Z '
              u'M3.2,4.6 L5.5,4.6 L5.5,5.6 L3.2,5.6 Z M6.5,4.6 L8.8,4.6 L8.8,5.6 L6.5,5.6 Z '
              u'M3.2,6.6 L5.5,6.6 L5.5,7.6 L3.2,7.6 Z M6.5,6.6 L8.8,6.6 L8.8,7.6 L6.5,7.6 Z '
              u'M3.2,8.6 L5.5,8.6 L5.5,9.6 L3.2,9.6 Z M6.5,8.6 L8.8,8.6 L8.8,9.6 L6.5,9.6 Z',
    u'family': u'M1,1 L5.4,1 L5.4,5.4 L1,5.4 Z M6.6,1 L11,1 L11,5.4 L6.6,5.4 Z '
               u'M1,6.6 L5.4,6.6 L5.4,11 L1,11 Z M6.6,6.6 L11,6.6 L11,11 L6.6,11 Z',
    u'type': u'M6,1.5 L10.5,6 L6,10.5 L1.5,6 Z',
    u'star': u'M6,0.8 L7.4,4.5 L11.3,4.7 L8.2,7.1 L9.3,10.9 L6,8.8 L2.7,10.9 L3.8,7.1 '
             u'L0.7,4.7 L4.6,4.5 Z',
    u'all': u'M6,0.6 L11.4,3.3 L6,6 L0.6,3.3 Z M1.6,5.2 L6,7.4 L10.4,5.2 L11.4,5.7 L6,8.4 L0.6,5.7 Z '
            u'M1.6,7.6 L6,9.8 L10.4,7.6 L11.4,8.1 L6,10.8 L0.6,8.1 Z',
}

# Tab icons: bigger and simpler than the row icons, on a 24 x 24 grid and
# shown at 22px, one colour per type. Built to read without a label.
TAB_GLYPHS = {
    # three stacked layers
    u'all': u'M12,2 L22,7 L12,12 L2,7 Z '
            u'M4,10.6 L12,14.6 L20,10.6 L22,11.6 L12,16.6 L2,11.6 Z '
            u'M4,15.2 L12,19.2 L20,15.2 L22,16.2 L12,21.2 L2,16.2 Z',
    # a five point star
    u'favourites': u'M12,1.6 L14.8,9 L22.7,9.3 L16.5,14.3 L18.6,21.9 L12,17.5 '
                   u'L5.4,21.9 L7.5,14.3 L1.3,9.3 L9.2,9 Z',
    # a legend: three swatches, each with its line of text
    u'legends': u'M2,3 L7,3 L7,8 L2,8 Z M9.5,4.6 L22,4.6 L22,6.6 L9.5,6.6 Z '
                u'M2,10 L7,10 L7,15 L2,15 Z M9.5,11.6 L22,11.6 L22,13.6 L9.5,13.6 Z '
                u'M2,17 L7,17 L7,22 L2,22 Z M9.5,18.6 L22,18.6 L22,20.6 L9.5,20.6 Z',
    # a pin
    u'pin': u'M8,2 L16,2 L16,4 L14.5,4 L14.5,10 L18,13.5 L18,15 L13,15 L12,23 L11,15 '
            u'L6,15 L6,13.5 L9.5,10 L9.5,4 L8,4 Z',
    # an eye: outline, open iris ring, solid pupil
    u'views': u'F0 M1,12 C4,5.2 20,5.2 23,12 C20,18.8 4,18.8 1,12 Z '
              u'M7.2,12 A4.8,4.8 0 1 0 16.8,12 A4.8,4.8 0 1 0 7.2,12 Z '
              u'M9.8,12 A2.2,2.2 0 1 0 14.2,12 A2.2,2.2 0 1 0 9.8,12 Z',
    # a drawing sheet: folded corner, open drawing area, title block
    u'sheets': u'F0 M4,1 L15,1 L20,6 L20,23 L4,23 Z '
               u'M6.2,3.2 L14,3.2 L14,7.8 L17.8,7.8 L17.8,20.8 L6.2,20.8 Z '
               u'M8,16.6 L16,16.6 L16,19 L8,19 Z',
    # a table: solid heading row, four open cells
    u'schedules': u'F0 M2,3 L22,3 L22,21 L2,21 Z '
                  u'M4,9.5 L11,9.5 L11,13.6 L4,13.6 Z M13,9.5 L20,9.5 L20,13.6 L13,13.6 Z '
                  u'M4,15.2 L11,15.2 L11,19 L4,19 Z M13,15.2 L20,15.2 L20,19 L13,19 Z',
    # a distribution board with a lightning bolt
    u'panels': u'F0 M4,1.5 L20,1.5 L20,22.5 L4,22.5 Z '
               u'M6,3.5 L18,3.5 L18,20.5 L6,20.5 Z '
               u'M13.6,5 L8,13.2 L11.6,13.2 L10.2,19 L16,10.4 L12.4,10.4 Z',
    # a component cube, faces split by a hairline
    u'families': u'M12,2 L21,6.5 L12,11 L3,6.5 Z '
                 u'M2,8.3 L11,12.8 L11,22.5 L2,18 Z '
                 u'M13,12.8 L22,8.3 L22,18 L13,22.5 Z',
}


def tab_glyph(tab):
    return TAB_GLYPHS.get(tab, TAB_GLYPHS[u'all'])


# Which colour family each kind is drawn in.
KIND_FAMILY = {
    u'sheet': u'sheet',
    u'schedule': u'schedule',
    u'panel': u'panel',
    u'family': u'family',
    u'type': u'family',
    u'star': u'fav',
    u'legend': u'legend',
}

# Root heading icon per tab, used on the All tab.
TAB_ICON = {
    u'all': u'all',
    u'views': u'plan',
    u'sheets': u'sheet',
    u'panels': u'panel',
    u'schedules': u'schedule',
    u'families': u'family',
    u'favourites': u'star',
    u'legends': u'legend',
}


def icon_for(kind):
    return ICONS.get(kind, ICONS[u'view'])


def family_for(kind):
    return KIND_FAMILY.get(kind, u'view')


# ============================================================
# view icons: a plain frame with the view's symbol small inside
# ============================================================
# From 1.3.0 a view, legend or drafting view is drawn as Revit draws them:
# a plain rectangle in the text colour (white on dark, black on light), with
# a small symbol in the middle saying what it is - its discipline when its
# view template names one, otherwise its view type. No colour.
FRAME = u'M0.5,1 L11.5,1 L11.5,11 L0.5,11 Z M1.7,2.2 L1.7,9.8 L10.3,9.8 L10.3,2.2 Z'
# The inside of the frame, filled blue behind the symbol when the view is
# placed on a sheet; NO_INNER is drawn (transparent) when it is not.
INNER = u'M1.7,2.2 L10.3,2.2 L10.3,9.8 L1.7,9.8 Z'
NO_INNER = u'M0,0'
SYMBOL_SCALE = 0.6
SYMBOL_ORIGIN = (2.4, 2.4)
VIEW_KINDS = set([u'plan', u'ceiling', u'area', u'structural', u'threed', u'section',
                  u'elevation', u'detail', u'drafting', u'legend', u'camera', u'view',
                  u'dependent'])
_FRAMED = {}
_ARGS = {u'M': 2, u'L': 2, u'C': 6, u'A': 7, u'Z': 0}


def _tokens(data):
    import re
    return re.findall(u'[MLCAZmlcaz]|-?[0-9]*\\.?[0-9]+', data.replace(u',', u' '))


def _num(value):
    text = u'{0:.2f}'.format(float(value)).rstrip(u'0').rstrip(u'.')
    return text if text not in (u'', u'-0') else u'0'


def scaled(data, scale, origin):
    u"""A path's own coordinates scaled and moved: x' = ox + s*x. Arcs keep
    their rotation and flags; their radii scale. Commands are M L C A Z
    (absolute), which is all these icons use."""
    tokens = _tokens(data)
    out = []
    i = 0
    command = None
    while i < len(tokens):
        token = tokens[i]
        if token.isalpha():
            command = token.upper()
            out.append(command)
            i += 1
            continue
        count = _ARGS[command]
        values = [float(t) for t in tokens[i:i + count]]
        i += count
        if command == u'A':
            rx, ry, rot, large, sweep, x, y = values
            out.append(u'{0},{1} {2} {3} {4} {5},{6}'.format(
                _num(rx * scale), _num(ry * scale), _num(rot), int(large), int(sweep),
                _num(origin[0] + x * scale), _num(origin[1] + y * scale)))
        else:
            pairs = []
            for j in range(0, count, 2):
                pairs.append(u'{0},{1}'.format(_num(origin[0] + values[j] * scale),
                                               _num(origin[1] + values[j + 1] * scale)))
            out.append(u' '.join(pairs))
    return u' '.join(out)


def framed(symbol):
    u"""The frame with this 12-grid symbol small in its middle, as one even-odd
    path. Cached: a model has thousands of views and a few dozen symbols."""
    symbol = symbol or ICONS[u'view']
    if symbol not in _FRAMED:
        inner = symbol[2:].strip() if symbol.startswith(u'F0') else symbol
        _FRAMED[symbol] = u'F0 ' + FRAME + u' ' + scaled(inner, SYMBOL_SCALE, SYMBOL_ORIGIN)
    return _FRAMED[symbol]


def is_view_kind(kind):
    return kind in VIEW_KINDS
