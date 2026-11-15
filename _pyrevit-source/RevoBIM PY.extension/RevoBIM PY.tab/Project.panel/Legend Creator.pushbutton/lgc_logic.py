# -*- coding: utf-8 -*-

"""Legend Creator - pure logic.

Constants, the legend kinds, the palettes, and every calculation that needs
neither Revit nor WPF: scaling, labels, colours, parking maths aside (that is
the drawer's), template choice, the phase filter, theme splicing. Imports
nothing of this tool's, so the bench imports it directly under CPython.
"""

import re


# ---------------------------------------------------------------------------
# The house legend standard
# ---------------------------------------------------------------------------
VIEW_PREFIX = 'WIP_'


COMBINED_NAME = 'WIP_COMBINED'


# The spacings below are quoted AT THE REFERENCE SCALE. Legend components are
# drawn at model size, so they grow and shrink with the view scale while text
# height does not - text is a paper measurement. Holding the model distances
# fixed would therefore crowd the text at 1:200 and strand it at 1:20. The
# distances are scaled with the view instead, which keeps the spacing constant
# on paper. See scaled_mm().
REFERENCE_SCALE = 100         # the scale the figures below are quoted at


DEFAULT_SCALE = 100           # 1:100


ROW_SPACING_MM = 900.0        # vertical gap between components


TEXT_OFFSET_MM = 1000.0       # gap between component and its text


DEFAULT_COLUMN_SPACING_MM = 3000.0


SCALE_CHOICES = [1, 2, 5, 10, 20, 25, 50, 100, 200, 500, 1000]


# --- System Colour Legend -------------------------------------------------
# The swatch figures are quoted at 1:200, which is where the house standard
# defines them, so this tab has its own reference scale.
SYSTEM_REFERENCE_SCALE = 200


SYSTEM_DEFAULT_SCALE = 200


SWATCH_W_MM = 2500.0          # filled region width


SWATCH_H_MM = 700.0           # filled region height


SYS_ROW_PITCH_MM = 1600.0     # centre to centre, swatch to swatch


SYS_TEXT_GAP_MM = 700.0       # right edge of swatch to start of text


SYS_HEADING_GAP_MM = 1400.0   # heading baseline up from the first swatch


# Each kind is a self-contained recipe. Adding another legend kind is a new
# entry here plus nothing else, which is why the fields are all data.
# Each kind is a self-contained recipe. 'source' decides where the entries
# and their colours come from, 'style' how the swatch is drawn.
# Pipe system classifications, grouped for the legend. Matched on keywords
# rather than enum members, whose names vary by release.
PIPE_GROUPS = [
    ('Domestic', ['domestic']),
    ('Hydronic', ['hydronic']),
    ('Sanitary & Vent', ['sanitary', 'vent']),
    ('Fire Protection', ['fire']),
]


PIPE_GROUP_OTHER = 'Other'


DEFAULT_LINE_WEIGHT = 3


MIN_LINE_WEIGHT = 1


MAX_LINE_WEIGHT = 16          # Revit's own range


CENTRELINE_NAME = 'LEG_Centreline'


# Revit line patterns are defined in paper millimetres, so these are the same
# on the sheet at every view scale and must not be scaled with the swatch.
CENTRELINE_PATTERN_NAME = 'LEG_Centreline 5-2-2-2'


CENTRELINE_SEGMENTS = [('dash', 5.0), ('space', 2.0),
                       ('dash', 2.0), ('space', 2.0)]


CENTRELINE_RGB = (128, 128, 128)


CENTRELINE_OVERHANG = 0.4     # of the swatch height, each end


SYSTEM_KINDS = [
    {
        'key': 'containment',
        'label': 'Containment Legend',
        'ready': True,
        'source': 'filters',
        'style': 'fill',
        'template': '04_Documentation_Floorplan_Containment',
        'categories': ['OST_CableTray', 'OST_CableTrayFitting',
                       'OST_CableTrayRun'],
        'name_token': 'containment',
        'region_prefix': 'LEG_CONT_',
        'heading': 'CONTAINMENT LEGEND',
        'view_name': 'WIP_Containment Legend',
        'swatch_h': 700.0,
    },
    {
        'key': 'ductwork',
        'label': 'Ductwork Legend',
        'ready': True,
        'source': 'duct_systems',
        'style': 'outline',
        'template': '',
        'categories': ['OST_DuctCurves', 'OST_FlexDuctCurves',
                       'OST_DuctFitting', 'OST_DuctAccessory',
                       'OST_DuctTerminal'],
        'name_token': '',
        'region_prefix': 'LEG_DUCT_',
        'heading': 'DUCTWORK LEGEND',
        'view_name': 'WIP_Ductwork Legend',
        'swatch_h': 700.0,
    },
    {
        'key': 'pipework',
        'label': 'Pipework Legend',
        'ready': True,
        'source': 'pipe_systems',
        'style': 'outline',
        'centreline': True,
        'grouped': True,
        'group_suffix': 'PIPEWORK LEGEND',
        'template': '',
        'categories': ['OST_PipeCurves', 'OST_FlexPipeCurves',
                       'OST_PipeFitting', 'OST_PipeAccessory'],
        'name_token': '',
        'region_prefix': 'LEG_PIPE_',
        'heading': 'PIPEWORK LEGEND',
        'view_name': 'WIP_Pipework Legend',
        # 75mm at 1:50, which is 300mm at the 1:200 reference - a pipe run
        # reads as a thin band, not the block a tray does
        'swatch_h': 300.0,
    },
]


# Defaults for everything else the window can change
DEFAULT_PHASE = 'New Construction'


DEFAULT_NAME_PARAM = 'Description'


DEFAULT_CASE = 'asis'


CASE_ASIS = 'asis'


CASE_UPPER = 'upper'


CASE_CAMEL = 'camel'


# Pseudo-parameters offered alongside the real ones
NAME_TYPE_NAME = '<Type Name>'


NAME_FAMILY_TYPE = '<Family : Type>'


# Categories that cannot be drawn as a legend component. Pointing a legend
# component at one of these can take Revit down rather than raise an error,
# so they are never offered.
BLOCKED_CATEGORIES = [
    'OST_RvtLinks', 'OST_IOSModelGroups', 'OST_Mass', 'OST_MassForm',
    'OST_Parts', 'OST_Topography', 'OST_Toposolid', 'OST_BuildingPad',
    'OST_RasterImages', 'OST_Rebar', 'OST_AreaRein', 'OST_PathRein',
    'OST_FabricAreas', 'OST_FabricReinforcement', 'OST_StructConnections',
    'OST_PipingSystem', 'OST_DuctSystem', 'OST_ElectricalCircuit',
    'OST_SwitchSystem', 'OST_Rooms', 'OST_MEPSpaces', 'OST_Areas',
    'OST_HVAC_Zones', 'OST_Coordination_Model', 'OST_PointClouds',
]


# The only things clear_legend is ever allowed to delete.
CLEARABLE_CATEGORIES = [
    'OST_LegendComponents', 'OST_TextNotes', 'OST_DetailComponents',
    'OST_Lines', 'OST_FilledRegion', 'OST_MaskingRegion',
    'OST_GenericAnnotation', 'OST_Dimensions',
]


# ---------------------------------------------------------------------------
# Palettes
# ---------------------------------------------------------------------------
# Both palettes must carry every key: a missing one leaves the previous
# palette's brush in place and produces an unreadable control on the swap.
# The bench check enforces that they match.
PALETTES = {
    # Revit's own dark theme, sampled from its Project Browser: panel
    # #3C4454, field #2D3441, title bar #212932, text #F0F0F8. Muted is
    # Revit's icon grey lifted from #A8AEB5 just enough to clear 4.5:1 on
    # the panel. The brand accents are the house ones, unchanged.
    'dark': {
        'Base': '#3C4454', 'Card': '#353D4B', 'Field': '#2D3441',
        'Bar': '#212932', 'Line': '#4B5566', 'Edge': '#586376',
        'Ink': '#F0F0F8', 'Muted': '#AEB4BB', 'Blue': '#4FA3E3',
        'BlueHover': '#8FBEFC', 'Orange': '#E8912D', 'Green': '#3FA75A',
        'GreenHover': '#4EC06D', 'OnGreen': '#0E2214', 'Red': '#D9534F',
        'Sel': '#2B5473', 'RowEvenBrush': '#353D4B', 'RowOddBrush': '#2D3441',
        'RowHover': '#2B5473', 'PillBrush': '#4B5566', 'CtrlBorder': '#66728A',
        'CtrlFill': '#465061', 'TickGlyph': '#1B1F24', 'Thumb': '#66728A',
    },
    # Not the dark palette inverted. The accents are darkened because the
    # dark ones are chosen to sit on near-black and wash out on white.
    'light': {
        'Base': '#F1F1F4', 'Card': '#FFFFFF', 'Field': '#FFFFFF',
        'Bar': '#E4E4EA', 'Line': '#D2D2DA', 'Edge': '#B4B4BE',
        'Ink': '#1F1F23', 'Muted': '#5C5C66',
        'Blue': '#1B72BE', 'BlueHover': '#155C99',
        'Orange': '#B96A12', 'Green': '#2E8546', 'GreenHover': '#37A056',
        'OnGreen': '#FFFFFF', 'Red': '#C1443F', 'Sel': '#CBE0F2',
        'RowEvenBrush': '#FFFFFF', 'RowOddBrush': '#F5F5F8',
        'RowHover': '#CBE0F2', 'PillBrush': '#E4E4EA', 'CtrlBorder': '#9A9AA4',
        'CtrlFill': '#EDEDF1', 'TickGlyph': '#FFFFFF', 'Thumb': '#B0B0BA',
    },
}


THEME_AUTO = 'auto'


THEME_ORDER = [THEME_AUTO, 'dark', 'light']


def parse_kv_list(text, fallback):
    """'a=1;b=2' to {'a': 1.0, 'b': 2.0}. A damaged entry falls back."""
    values = dict(fallback)
    for chunk in u'{0}'.format(text or '').split(';'):
        chunk = chunk.strip()
        if not chunk or '=' not in chunk:
            continue
        key, value = chunk.split('=', 1)
        try:
            number = float(value.strip())
        except Exception:
            continue
        if number > 0:
            values[key.strip()] = number
    return values


def format_kv_list(values):
    return ';'.join('{0}={1}'.format(key, format_mm(values[key]))
                    for key in sorted(values.keys()))


MM_PER_FOOT = 304.8


def to_internal(millimetres):
    """Millimetres to Revit internal units (decimal feet).

    Plain arithmetic rather than UnitUtils: the units API changed shape in
    2021 and DisplayUnitType was removed in 2022, whereas a foot has been
    304.8mm in every release and will be in the next.
    """
    return float(millimetres) / MM_PER_FOOT


_WORD = re.compile(r"[A-Za-z][A-Za-z']*")


def to_camel_case(text):
    """Capitalise each word. Tokens holding digits are left alone, so codes
    and sizes such as FD30 or 900x2100 survive untouched."""
    words = []
    for token in text.split(' '):
        if not token or any(ch.isdigit() for ch in token):
            words.append(token)
            continue
        words.append(_WORD.sub(
            lambda m: m.group(0)[0].upper() + m.group(0)[1:].lower(), token))
    return ' '.join(words)


def apply_case(text, mode):
    if not text:
        return text
    if mode == CASE_UPPER:
        return text.upper()
    if mode == CASE_CAMEL:
        return to_camel_case(text)
    return text


def format_mm(value):
    """Trim a float to something a millimetre box should show."""
    rounded = round(float(value), 1)
    if abs(rounded - int(rounded)) < 0.05:
        return str(int(rounded))
    return '{0:.1f}'.format(rounded)


def scaled_mm(base_mm, scale, reference=None):
    """A distance quoted at a reference scale, restated for another scale.

    900mm at 1:100 is 9mm on paper. At 1:50 that same 9mm on paper is 450mm
    in the view, so the model distance halves as the scale gets finer. The
    two tabs quote their figures at different scales, hence the argument.
    """
    reference = REFERENCE_SCALE if reference is None else reference
    try:
        return float(base_mm) * (float(scale) / float(reference))
    except Exception:
        return float(base_mm)


def unscaled_mm(value_mm, scale, reference=None):
    """The inverse - a distance typed at some scale, back to the reference."""
    reference = REFERENCE_SCALE if reference is None else reference
    try:
        return float(value_mm) * (float(reference) / float(scale))
    except Exception:
        return float(value_mm)


def channel(value):
    """A Revit colour channel as a plain Python int, 0-255.

    Revit hands back a .NET Byte. Left as one it takes the .NET formatter
    rather than Python's, and '{0:02X}' is then read as a custom format
    string - digit placeholder, then a literal '2X' - which produced the
    'invalid literal for int() with base 16' crash in 2.1.0. Coerce early.
    """
    try:
        number = int(value)
    except Exception:
        return 0
    return max(0, min(255, number))


def rgb_hex(rgb):
    """(r, g, b) to '#RRGGBB'. Python ints only, no .NET formatting."""
    if not rgb:
        return '#9A9A9E'
    red, green, blue = (channel(c) for c in rgb)
    return '#%02X%02X%02X' % (red, green, blue)


def unique_view_name(base, taken):
    """WIP_Doors, then WIP_Doors_2, WIP_Doors_3 ..."""
    if base not in taken:
        taken.add(base)
        return base
    index = 2
    while True:
        candidate = '{0}_{1}'.format(base, index)
        if candidate not in taken:
            taken.add(candidate)
            return candidate
        index += 1


def tidy_label(text, token):
    """Turn a filter or rule string into the label that goes on the legend."""
    label = re.sub(r'[_]+', ' ', u'{0}'.format(text)).strip()
    if token:
        # Drop the grouping word and any separator left stranded by it.
        label = re.sub(r'(?i)\b' + re.escape(token) + r'\b', ' ', label)
    label = re.sub(r'^[\s\-:>|]+', '', label)
    label = re.sub(r'[\s\-:>|]+$', '', label)
    return re.sub(r'\s{2,}', ' ', label).strip()


def decode_colour_int(number):
    """Revit packs a colour into an integer as R + G*256 + B*65536."""
    try:
        number = int(number)
    except Exception:
        return None
    if number < 0:
        return None
    return (number % 256, (number // 256) % 256, (number // 65536) % 256)


def group_order(name):
    for index, (group, _keywords) in enumerate(PIPE_GROUPS):
        if group == name:
            return index
    return len(PIPE_GROUPS)          # Other last


def grouped_entries(entries, kind):
    """[(header, [entry, ...])] in the order the legend should read."""
    if not kind.get('grouped'):
        return [(kind['heading'], entries)]

    order = []
    buckets = {}
    for entry in entries:
        group = getattr(entry, 'group', PIPE_GROUP_OTHER)
        if group not in buckets:
            buckets[group] = []
            order.append(group)
        buckets[group].append(entry)

    order.sort(key=group_order)
    suffix = kind.get('group_suffix', kind['heading'])
    return [('{0} {1}'.format(group, suffix).upper(), buckets[group])
            for group in order]


def choose_template(names, counts, saved, default, uses_filters):
    """Which template to preselect, and why: (index or -1, reason).

    Used last time, then the kind's own default, then the template holding
    the most matching filters, and only then the first in the list - with a
    reason that says so, never silently.
    """
    if saved and saved in names:
        return names.index(saved), u'used last time'
    if default and default in names:
        return names.index(default), u'the default for this kind'
    if uses_filters and counts and max(counts) > 0:
        best = max(counts)
        return counts.index(best), \
            u'holds the most matching filters ({0})'.format(best)
    if names:
        return 0, u'nothing in this model matches - first in list'
    return -1, u'this model has no view templates'


def usable_phase(value):
    """A phase id value worth filtering on, or None. Real ids are positive;
    0 is what eid_value gives back for nothing at all."""
    if value is None or value <= 0:
        return None
    return value


def phase_verdict(want_phase, on_phase):
    """'keep', 'no phase' or 'other phase' for one element.

    An element with no phase is never kept by a phase filter. Before 2.11 it
    was compared as 0, so an unreadable wanted phase (also 0) kept exactly
    the elements that had no phase and dropped the rest.
    """
    if want_phase is None:
        return 'keep'
    if on_phase is None:
        return 'no phase'
    return 'keep' if on_phase == want_phase else 'other phase'


# ---------------------------------------------------------------------------
# System Colour Legend - drawing it
# ---------------------------------------------------------------------------
def clamp_weight(value):
    """Revit takes 1 to 16. Anything else is coerced rather than refused."""
    try:
        weight = int(round(float(value)))
    except Exception:
        return DEFAULT_LINE_WEIGHT
    return max(MIN_LINE_WEIGHT, min(MAX_LINE_WEIGHT, weight))


INVALID_NAME_CHARS = re.compile(r'[\\:{}\[\]|;<>?`~]')


def safe_style_name(name):
    """Revit refuses these characters in an element name."""
    return INVALID_NAME_CHARS.sub('-', name).strip() or 'Unnamed'


def classify_pipe(text):
    """The legend group for a pipe system's classification text.

    Keywords rather than enum members, which are named inconsistently across
    releases - DomesticColdWater, FireProtectWet, FireProtectPreaction.
    """
    text = (text or u'').lower()
    for group, keywords in PIPE_GROUPS:
        if any(keyword in text for keyword in keywords):
            return group
    return PIPE_GROUP_OTHER


def join_label(abbreviation, description, fallback):
    """Abbreviation - Description, either half alone, or the fallback."""
    parts = [p.strip() for p in (abbreviation or u'', description or u'')
             if p and p.strip()]
    return u' - '.join(parts) if parts else fallback


def pick_theme(mode, revit_value):
    """The palette to use: a pinned mode as it is, otherwise Revit's own,
    otherwise dark."""
    if mode in ('dark', 'light'):
        return mode
    return revit_value or 'dark'


def read_theme_text(value):
    """'dark', 'light' or None from however a UITheme value prints.

    Read as text rather than compared against the enum, whose member names
    have not been stable across releases.
    """
    text = u'{0}'.format(value).lower()
    if 'dark' in text:
        return 'dark'
    if 'light' in text:
        return 'light'
    return None


def next_theme_mode(mode):
    """The chip's cycle: Auto -> Dark -> Light -> Auto."""
    position = THEME_ORDER.index(mode) if mode in THEME_ORDER else 0
    return THEME_ORDER[(position + 1) % len(THEME_ORDER)]


# ---------------------------------------------------------------------------
# The shared theme
# ---------------------------------------------------------------------------
THEME_MARKER = '<!-- lgc:theme -->'
_DICTIONARY = re.compile(r'<ResourceDictionary\b[^>]*>')


def splice_theme(layout, theme):
    """A layout with Theme.xaml's resources put in place of its marker.

    Spliced as text before WPF parses the layout, rather than merged in
    afterwards, so keyed styles stay StaticResource - a dictionary merged
    after parsing is invisible to StaticResource and the window fails to
    load. One theme file, three windows, no copies.
    """
    opened = _DICTIONARY.search(theme)
    closed = theme.rfind('</ResourceDictionary>')
    if opened is None or closed < opened.end():
        raise ValueError('Theme.xaml is not a ResourceDictionary')
    if layout.count(THEME_MARKER) != 1:
        raise ValueError('a layout must hold the theme marker exactly once')
    return layout.replace(THEME_MARKER, theme[opened.end():closed].strip())
