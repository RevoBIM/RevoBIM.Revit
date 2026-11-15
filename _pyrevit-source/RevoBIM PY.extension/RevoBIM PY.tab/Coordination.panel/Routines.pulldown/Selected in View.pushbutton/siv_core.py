# -*- coding: utf-8 -*-
"""Selected in View - version, settings, palettes and every rule.

No .NET imports here: the bench runs this module under plain CPython.
"""
import os
import io

__version__ = '1.1.0'
TOOL_NAME = u'Selected in View'

# =====================================================================
# Settings  (plain key=value under %APPDATA%\RevoBIM\)
# =====================================================================
SETTINGS_VERSION = 1
SETTINGS_FILE = 'selected_in_view.txt'
DEBUG_FILE = 'selected_in_view_debug.txt'
ERROR_FILE = 'selected_in_view_error.txt'

DEFAULTS = {
    'settings_version': str(SETTINGS_VERSION),
    'theme': 'auto',
    'debug': '1',
    'left': '',
    'top': '',
    'width': '',
    'height': '',
}

# version the file was written at -> function upgrading the dict one step
MIGRATIONS = {}

VALID = {
    'theme': ('auto', 'dark', 'light'),
    'debug': ('0', '1'),
}


def appdata_dir():
    base = os.environ.get('APPDATA') or os.path.expanduser('~')
    return os.path.join(base, 'RevoBIM')


def settings_path():
    return os.path.join(appdata_dir(), SETTINGS_FILE)


def debug_path():
    return os.path.join(appdata_dir(), DEBUG_FILE)


def error_path():
    return os.path.join(appdata_dir(), ERROR_FILE)


def parse_settings(text):
    """Defaults key by key; unknown keys ignored; split on the first '=' only."""
    values = dict(DEFAULTS)
    found = {}
    for raw in (text or u'').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, val = line.split('=', 1)
        key = key.strip()
        val = val.strip()
        if key in DEFAULTS:
            found[key] = val
    try:
        ver = int(found.get('settings_version', '0') or '0')
    except Exception:
        ver = 0
    while ver < SETTINGS_VERSION:
        step = MIGRATIONS.get(ver)
        if step is not None:
            try:
                step(found)
            except Exception:
                pass
        ver += 1
    for key, val in found.items():
        if key == 'settings_version':
            continue
        allowed = VALID.get(key)
        if allowed is not None and val not in allowed:
            continue
        values[key] = val
    values['settings_version'] = str(SETTINGS_VERSION)
    return values


def format_settings(values):
    lines = []
    for key in sorted(DEFAULTS.keys()):
        lines.append(u'{0}={1}'.format(key, values.get(key, DEFAULTS[key])))
    return u'\n'.join(lines) + u'\n'


def load_settings(path=None):
    path = path or settings_path()
    text = u''
    try:
        if os.path.exists(path):
            with io.open(path, 'r', encoding='utf-8') as fh:
                text = fh.read()
    except Exception:
        text = u''
    return parse_settings(text)


def save_settings(values, path=None):
    path = path or settings_path()
    try:
        folder = os.path.dirname(path)
        if not os.path.isdir(folder):
            os.makedirs(folder)
        body = format_settings(values)
        with io.open(path, 'w', encoding='utf-8') as fh:
            fh.write(body)
        return True
    except Exception:
        return False


def to_float(text, default=None):
    try:
        return float(text)
    except Exception:
        return default


# =====================================================================
# Theme
# =====================================================================
THEME_CYCLE = ['auto', 'dark', 'light']
THEME_LABELS = {'auto': u'Auto', 'dark': u'Dark', 'light': u'Light'}


def next_theme(current):
    try:
        i = THEME_CYCLE.index(current)
    except ValueError:
        return 'auto'
    return THEME_CYCLE[(i + 1) % len(THEME_CYCLE)]


def resolve_theme(setting, canvas):
    """setting auto/dark/light + Revit canvas dark/light/None -> dark/light."""
    if setting in ('dark', 'light'):
        return setting
    if canvas in ('dark', 'light'):
        return canvas
    return 'dark'


def theme_tooltip(setting, mode):
    if setting == 'auto':
        return u'Theme: Auto - following the Revit canvas ({0}). Click for Dark.'.format(mode)
    if setting == 'dark':
        return u'Theme: Dark. Click for Light.'
    return u'Theme: Light. Click for Auto.'


PALETTES = {
    'dark': {
        'WindowBg': '#232326', 'CardBg': '#2B2B2E', 'FieldBg': '#1C1C1F',
        'BarBg': '#1C1C1F', 'Edge': '#3E3E42', 'FrameEdge': '#4A4A50',
        'Text': '#E4E4E4', 'Muted': '#9A9A9E', 'Blue': '#4FA3E3',
        'Orange': '#E8912D', 'Green': '#3FA75A', 'GreenHover': '#4EC06D',
        'Red': '#D9534F', 'RedHover': '#E8615D', 'Sel': '#2B5473',
        'RowHover': '#303035', 'ChipBg': '#2B2B2E', 'OnText': '#FFFFFF',
        'ScrollThumb': '#4A4A50', 'CheckBg': '#1C1C1F',
        'CatPlumb': '#4FA3E3', 'CatMech': '#55C27A', 'CatElec': '#E8912D',
        'CatStruct': '#E06A66', 'CatArch': '#C9A26B', 'CatGeneric': '#A889D8',
        'CatDatum': '#3FB7B0', 'CatAnno': '#B4B4BA', 'CatOther': '#D6C760',
    },
    'light': {
        'WindowBg': '#F3F3F5', 'CardBg': '#FFFFFF', 'FieldBg': '#FFFFFF',
        'BarBg': '#E6E6EA', 'Edge': '#C9C9CF', 'FrameEdge': '#B5B5BC',
        'Text': '#1E1E20', 'Muted': '#66666C', 'Blue': '#1B72BE',
        'Orange': '#B96A12', 'Green': '#2E8546', 'GreenHover': '#36994F',
        'Red': '#C0392B', 'RedHover': '#D24A3B', 'Sel': '#CFE3F5',
        'RowHover': '#EAEAEF', 'ChipBg': '#FFFFFF', 'OnText': '#FFFFFF',
        'ScrollThumb': '#B5B5BC', 'CheckBg': '#FFFFFF',
        'CatPlumb': '#1B72BE', 'CatMech': '#2E8546', 'CatElec': '#B96A12',
        'CatStruct': '#B83E3A', 'CatArch': '#8C6A35', 'CatGeneric': '#6E4FB0',
        'CatDatum': '#1F8079', 'CatAnno': '#5E5E66', 'CatOther': '#8A7A12',
    },
}

# =====================================================================
# Category colours  (first rule whose keyword appears in the name wins)
# =====================================================================
COLOUR_RULES = [
    ('CatElec', ['cable tray', 'conduit', 'electrical', 'lighting',
                 'communication', 'data device', 'fire alarm', 'security',
                 'nurse call', 'telephone', 'wire', 'switch system',
                 'panel schedule', 'audio visual']),
    ('CatPlumb', ['pipe', 'piping', 'plumbing', 'sprinkler']),
    ('CatMech', ['duct', 'air terminal', 'mechanical', 'hvac']),
    ('CatStruct', ['structural', 'foundation', 'rebar', 'framing', 'truss',
                   'bearing']),
    ('CatDatum', ['grid', 'level', 'reference plane', 'scope box',
                  'section box', 'viewer', 'elevation', 'callout', 'section',
                  'reference line', 'matchline']),
    ('CatArch', ['wall', 'floor', 'ceiling', 'door', 'window', 'roof',
                 'stair', 'railing', 'room', 'furniture', 'casework',
                 'curtain', 'column', 'ramp', 'topograph', 'toposolid',
                 'site', 'parking', 'planting', 'entourage', 'area',
                 'shaft', 'opening']),
    ('CatGeneric', ['generic model', 'specialty equipment', 'space',
                    'fabrication', 'mass', 'group', 'zone']),
    ('CatAnno', ['text', 'dimension', 'detail', 'line', 'revision',
                 'annotation', 'filled region', 'masking', 'spot',
                 'keynote', 'symbol', 'legend', 'insulation', 'tag']),
]


def tag_base_name(name):
    """'Pipe Tags' -> 'Pipe'; 'Multi-Category Tags' -> 'Multi-Category'."""
    n = (name or u'').strip()
    low = n.lower()
    for suffix in (u' tags', u' tag'):
        if low.endswith(suffix):
            return n[:len(n) - len(suffix)].strip()
    return n


def colour_key(name, is_tag=False):
    base = tag_base_name(name) if is_tag else (name or u'')
    low = base.lower()
    for key, words in COLOUR_RULES:
        for w in words:
            if w in low:
                return key
    return 'CatAnno' if is_tag else 'CatOther'


# =====================================================================
# The category list
# =====================================================================
SECTIONS = [('tags', u'Tags'), ('model', u'Model'), ('annotation', u'Annotation')]
SECTION_TICK = {'model': 'Blue', 'annotation': 'Orange', 'tags': 'Green'}


def tag_row_key(family):
    """Tags are listed by tag family, not by tag category."""
    return u'tag:' + (family or u'(no family)')


def build_list(records):
    """records: (cat_key, cat_name, ctype, is_tag, type_key, type_name, family).

    ctype is 'model' or 'annotation'. Every tag goes under one Tags heading,
    one row per tag FAMILY (key tag_row_key(family)) holding its types as
    children keyed (row_key, type_key). Rows sort by section then name.
    """
    rows = {}
    for rec in records:
        cat_key, cat_name, ctype, is_tag, type_key, type_name, family = rec
        if cat_key is None:
            continue
        if is_tag:
            key = tag_row_key(family)
            name = family or u'(no family)'
            section = 'tags'
        else:
            key = cat_key
            name = cat_name or u'(unnamed)'
            section = ctype if ctype in ('model', 'annotation') else 'model'
        row = rows.get(key)
        if row is None:
            row = {
                'key': key, 'name': name, 'section': section,
                'colour': colour_key(cat_name, is_tag), 'count': 0,
                'types': {}, 'categories': [],
            }
            rows[key] = row
        row['count'] += 1
        if is_tag:
            if cat_name and cat_name not in row['categories']:
                row['categories'].append(cat_name)
            tkey = (key, type_key)
            child = row['types'].get(tkey)
            if child is None:
                child = {'key': tkey, 'name': type_name or u'(no type)', 'count': 0}
                row['types'][tkey] = child
            child['count'] += 1
    order = dict((s, i) for i, (s, _t) in enumerate(SECTIONS))
    out = []
    for row in rows.values():
        kids = list(row['types'].values())
        kids.sort(key=lambda c: c['name'].lower())
        row['types'] = kids
        row['categories'].sort()
        out.append(row)
    out.sort(key=lambda r: (order.get(r['section'], 9), r['name'].lower()))
    return out


def rows_in(rows, section):
    return [r for r in rows if r['section'] == section]


class FilterState(object):
    """What the next selection keeps. Stored as what is OFF, so anything
    new defaults to on."""

    def __init__(self):
        self.off_cats = set()
        self.off_tags = set()
        self.links_on = True
        self.pinned_on = True
        self.tag_types = {}
        self.known_cats = set()

    def learn(self, rows):
        for r in rows:
            self.known_cats.add(r['key'])
            if r['section'] == 'tags':
                known = self.tag_types.setdefault(r['key'], set())
                for c in r['types']:
                    known.add(c['key'][1])

    def restricting(self):
        return bool(self.off_cats or self.off_tags or not self.links_on
                    or not self.pinned_on)

    def row_on(self, row):
        if row['section'] == 'tags':
            return parent_state(row, self.off_tags)
        return row['key'] not in self.off_cats

    def set_row(self, row, on):
        if row['section'] == 'tags':
            for c in row['types']:
                if on:
                    self.off_tags.discard(c['key'])
                else:
                    self.off_tags.add(c['key'])
            if on:
                self.off_cats.discard(row['key'])
            else:
                self.off_cats.add(row['key'])
        elif on:
            self.off_cats.discard(row['key'])
        else:
            self.off_cats.add(row['key'])

    def set_child(self, row, child_key, on):
        if on:
            self.off_tags.discard(child_key)
        else:
            self.off_tags.add(child_key)
        # the category flag follows its children: off only when all are off
        if parent_state(row, self.off_tags) is False:
            self.off_cats.add(row['key'])
        else:
            self.off_cats.discard(row['key'])

    def set_all(self, rows, on):
        for r in rows:
            self.set_row(r, on)


def parent_state(row, off_tags):
    """True all children on, False all off, None mixed."""
    kids = row.get('types') or []
    if not kids:
        return True
    off = 0
    for c in kids:
        if c['key'] in off_tags:
            off += 1
    if off == 0:
        return True
    if off == len(kids):
        return False
    return None


def section_state(rows, state):
    vals = [state.row_on(r) for r in rows]
    if not vals:
        return True
    if all(v is True for v in vals):
        return True
    if all(v is False for v in vals):
        return False
    return None


def decide(info, state):
    """info: cat, row, is_tag, type, linked, pinned. Returns (keep, reason).

    'row' is the list row the element belongs to - its category, or for a
    tag its tag family row."""
    if info.get('linked'):
        if not state.links_on:
            return False, 'linked'
        return True, ''
    if info.get('pinned') and not state.pinned_on:
        return False, 'pinned'
    row = info.get('row', info.get('cat'))
    if row is None:
        return True, ''
    if info.get('is_tag'):
        known = state.tag_types.get(row)
        t = info.get('type')
        if known:
            if t in known:
                if (row, t) in state.off_tags:
                    return False, 'tag type'
                return True, ''
            # a type of this family the list has not seen follows its family
            for k in known:
                if (row, k) not in state.off_tags:
                    return True, ''
            return False, 'tag family'
        # a family the list has not seen: off only when every tag is off
        if state.tag_types and all_tags_off(state):
            return False, 'tags'
        return True, ''
    if row in state.off_cats:
        return False, 'category'
    return True, ''


def all_tags_off(state):
    for row, types in state.tag_types.items():
        for t in types:
            if (row, t) not in state.off_tags:
                return False
    return True


def drop_summary(kept, dropped):
    """dropped: list of label strings. 'Kept 5, dropped 3 (2 Walls, 1 pinned)'."""
    if not dropped:
        return u'Kept {0}.'.format(kept)
    counts = {}
    for label in dropped:
        counts[label] = counts.get(label, 0) + 1
    parts = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))
    shown = [u'{0} {1}'.format(n, label) for label, n in parts[:3]]
    if len(parts) > 3:
        shown.append(u'+{0} more'.format(len(parts) - 3))
    return u'Kept {0}, dropped {1} ({2}).'.format(kept, len(dropped), u', '.join(shown))


def picking_summary(rows, state):
    total = len(rows)
    on = 0
    for r in rows:
        v = state.row_on(r)
        if v is True or v is None:
            on += 1
    return on, total


def matches(query, text):
    """Every word of the query must appear in the text."""
    words = [w for w in (query or u'').lower().split() if w]
    if not words:
        return True
    low = (text or u'').lower()
    for w in words:
        if w not in low:
            return False
    return True


# =====================================================================
# Easter egg slow clicks (250ms floor, 2s ceiling, three clicks)
# =====================================================================
class SlowClicks(object):
    def __init__(self, need=3, floor_ms=250, ceiling_ms=2000):
        self.need = need
        self.floor_ms = floor_ms
        self.ceiling_ms = ceiling_ms
        self.times = []

    def click(self, ms):
        if self.times:
            gap = ms - self.times[-1]
            if gap < self.floor_ms:
                return False
            if gap > self.ceiling_ms:
                self.times = []
        self.times.append(ms)
        if len(self.times) >= self.need:
            self.times = []
            return True
        return False


# =====================================================================
# Debug log
# =====================================================================
class DebugLog(object):
    def __init__(self, path, enabled=True, keep=3000):
        self.path = path
        self.enabled = enabled
        self.keep = keep
        self.lines = []

    def add(self, text):
        line = u'{0}'.format(text)
        self.lines.append(line)
        if len(self.lines) > self.keep:
            self.lines = self.lines[-self.keep:]
        if not self.enabled:
            return
        try:
            folder = os.path.dirname(self.path)
            if not os.path.isdir(folder):
                os.makedirs(folder)
            with io.open(self.path, 'a', encoding='utf-8') as fh:
                fh.write(line + u'\n')
        except Exception:
            pass

    def text(self):
        return u'\n'.join(self.lines)
