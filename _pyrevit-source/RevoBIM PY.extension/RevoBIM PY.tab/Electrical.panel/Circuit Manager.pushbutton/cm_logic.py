# -*- coding: utf-8 -*-
"""Circuit Manager - pure rules.

No WPF, no Revit, no .NET in here: everything that decides a value lives in
plain functions that bench_logic.py proves under CPython.
Runs on IronPython 2.7 and IronPython 3 alike.
"""
import re

MM_PER_FOOT = 304.8
MAX_OFFSET_FT = 30000.0          # Revit refuses |PathOffset| above this

# ======================================================================
# Path mode
# ======================================================================
# (API enum member name, label shown in the table) - order is menu order
PATH_MODES = [
    ('FarthestDevice', u'Farthest Device'),
    ('AllDevices', u'All Devices'),
    ('Custom', u'Custom'),
]


def _squash(text):
    return re.sub(r'[\s_\-]+', '', to_text(text)).lower()


def path_mode_label(api_name):
    """'FarthestDevice' -> 'Farthest Device'. Unknown names pass through."""
    key = _squash(api_name)
    for name, label in PATH_MODES:
        if _squash(name) == key:
            return label
    return to_text(api_name)


def parse_path_mode(text):
    """Label, API name or a sensible abbreviation -> API member name, or None."""
    key = _squash(text)
    if not key:
        return None
    for name, label in PATH_MODES:
        if key == _squash(name) or key == _squash(label):
            return name
    aliases = {'farthest': 'FarthestDevice', 'far': 'FarthestDevice',
               'fd': 'FarthestDevice', 'all': 'AllDevices',
               'ad': 'AllDevices', 'alldevice': 'AllDevices',
               'cus': 'Custom', 'c': 'Custom'}
    return aliases.get(key)


def mode_targets(rows, mode, custom_ok):
    """Split rows into (can take this mode, refused with reason).

    rows: list of row keys; custom_ok: {row key: has a custom path stored}.
    Revit refuses Custom on a circuit that has no customised path.
    """
    ok, refused = [], []
    for r in rows:
        if mode == 'Custom' and not custom_ok.get(r, False):
            refused.append((r, u'no custom path stored - edit the path in '
                               u'Revit first'))
        else:
            ok.append(r)
    return ok, refused


# ======================================================================
# Lengths
# ======================================================================
def to_text(value):
    if value is None:
        return u''
    try:
        return u'{0}'.format(value)
    except Exception:
        try:
            return unicode(value)  # noqa: F821  (IronPython 2.7)
        except Exception:
            return u''


def format_mm(mm):
    """2750 -> '2750.0' - matches what Revit's Edit Path bar shows."""
    if mm is None:
        return u''
    return u'{0:.1f}'.format(float(mm))


def feet_to_mm_text(feet):
    if feet is None:
        return u''
    return format_mm(float(feet) * MM_PER_FOOT)


_NUM = re.compile(r'^[+-]?(\d+(\.\d*)?|\.\d+)$')


def parse_mm(text):
    """'2750', '2,750.0 mm', ' 2750mm ' -> 2750.0. Returns None if not a length.

    Metres are accepted with an explicit unit ('2.75 m'). Anything else, or a
    value Revit would refuse, is None so it can never be staged.
    """
    t = to_text(text).strip().lower().replace(',', '').replace(' ', '')
    if not t:
        return None
    scale = 1.0
    if t.endswith('mm'):
        t = t[:-2]
    elif t.endswith('m'):
        t, scale = t[:-1], 1000.0
    if not _NUM.match(t):
        return None
    mm = float(t) * scale
    if abs(mm / MM_PER_FOOT) > MAX_OFFSET_FT:
        return None
    return mm


def mm_to_feet(mm):
    return float(mm) / MM_PER_FOOT


def same_mm(a_text, b_text, tol=0.05):
    a, b = parse_mm(a_text), parse_mm(b_text)
    if a is None or b is None:
        return to_text(a_text).strip() == to_text(b_text).strip()
    return abs(a - b) <= tol


# ======================================================================
# Values typed or pasted into a column
# ======================================================================
YES = ('yes', 'y', 'true', '1', 'on', 'x')
NO = ('no', 'n', 'false', '0', 'off', '')


def normalise_input(kind, text):
    """Validate text for a column kind. Returns (value_text, error or None).

    kind: 'pm' path mode, 'po' offset in mm, 'int', 'yesno', 'double',
    'string'. 'double' is left for Revit's own unit parser to judge.
    """
    t = to_text(text).strip()
    if kind == 'pm':
        name = parse_path_mode(t)
        if name is None:
            return None, u'not a path mode'
        return path_mode_label(name), None
    if kind == 'po':
        mm = parse_mm(t)
        if mm is None:
            return None, u'not a length in mm'
        return format_mm(mm), None
    if kind == 'yesno':
        low = t.lower()
        if low in YES:
            return u'Yes', None
        if low in NO:
            return u'No', None
        return None, u'not yes / no'
    if kind == 'int':
        if re.match(r'^[+-]?\d+$', t):
            return to_text(int(t)), None
        return None, u'not a whole number'
    if kind == 'double':
        if not t:
            return None, u'blank'
        return t, None
    return to_text(text), None


def same_value(kind, a, b):
    if kind == 'po':
        return same_mm(a, b)
    if kind == 'pm':
        return parse_path_mode(a) == parse_path_mode(b)
    return to_text(a).strip() == to_text(b).strip()


# ======================================================================
# Clipboard
# ======================================================================
def parse_clipboard(text):
    """Excel's tab separated block -> list of rows of cells.

    A single trailing newline (Excel always adds one) is not a blank row.
    """
    t = to_text(text).replace('\r\n', '\n').replace('\r', '\n')
    if t.endswith('\n'):
        t = t[:-1]
    if t == u'':
        return [[u'']]
    return [line.split('\t') for line in t.split('\n')]


def to_clipboard(block):
    """list of rows of cells -> tab separated text with Excel's newline."""
    return u'\r\n'.join(u'\t'.join(to_text(c) for c in row)
                        for row in block) + u'\r\n'


def copy_block(cells):
    """cells: [(row position, column position, text)] -> rectangular block.

    Gaps inside the rectangle (a ragged Ctrl-selection) copy as blanks.
    """
    if not cells:
        return []
    rows = sorted(set(c[0] for c in cells))
    cols = sorted(set(c[1] for c in cells))
    look = dict(((r, c), v) for r, c, v in cells)
    return [[look.get((r, c), u'') for c in cols] for r in rows]


def paste_plan(clip, selected, row_positions, col_positions):
    """Where each pasted value goes: [(row position, column position, text)].

    clip: parse_clipboard output.
    selected: [(row position, column position)] the selected cells.
    row_positions / col_positions: the visible data rows and columns in
    display order, so a block walks what is on screen and never lands in a
    filtered-out row.

    One value copied -> it fills every selected cell (the Excel way to set
    many offsets at once). A block -> laid out from the top-left selected cell.
    """
    if not selected or not clip:
        return []
    if len(clip) == 1 and len(clip[0]) == 1:
        value = clip[0][0]
        return [(r, c, value) for r, c in sorted(set(selected))]
    top = min(r for r, c in selected)
    left = min(c for r, c in selected)
    if top not in row_positions or left not in col_positions:
        return []
    r0 = row_positions.index(top)
    c0 = col_positions.index(left)
    out = []
    for i, line in enumerate(clip):
        if r0 + i >= len(row_positions):
            break
        for j, value in enumerate(line):
            if c0 + j >= len(col_positions):
                break
            out.append((row_positions[r0 + i], col_positions[c0 + j], value))
    return out


# ======================================================================
# Filtering and sorting
# ======================================================================
def matches_text(value, term):
    """Keyword filter: every space separated word must appear, any order."""
    words = to_text(term).lower().split()
    if not words:
        return True
    hay = to_text(value).lower()
    for w in words:
        if w not in hay:
            return False
    return True


def row_visible(values, text_filters, tick_filters, exclude=None):
    """values: {key: text}. tick filter None = everything ticked."""
    for key, term in text_filters.items():
        if key == exclude:
            continue
        if not matches_text(values.get(key, u''), term):
            return False
    for key, allowed in tick_filters.items():
        if key == exclude or allowed is None:
            continue
        if to_text(values.get(key, u'')) not in allowed:
            return False
    return True


def list_values(rows_values, key, text_filters, tick_filters):
    """Values for a column's tick list: what the OTHER filters allow.

    Its own filter is excluded so values it hides can be ticked back on.
    """
    seen = set()
    for values in rows_values:
        if row_visible(values, text_filters, tick_filters, exclude=key):
            seen.add(to_text(values.get(key, u'')))
    return sorted(seen, key=natural_key)


def is_filtered(key, text_filters, tick_filters):
    return bool(to_text(text_filters.get(key, u'')).strip()) or \
        tick_filters.get(key) is not None


_CHUNK = re.compile(r'(\d+(?:\.\d+)?)')


def natural_key(value):
    """P-9 < P-10 < P-100; numbers compare as numbers, text case-blind."""
    out = []
    for part in _CHUNK.split(to_text(value).lower()):
        if not part:
            continue
        if _CHUNK.match(part):
            out.append((0, float(part), u''))
        else:
            out.append((1, 0.0, part))
    return out


def sort_order(rows_values, key, descending):
    """Indices of rows_values in display order (stable, natural)."""
    idx = list(range(len(rows_values)))
    idx.sort(key=lambda i: natural_key(rows_values[i].get(key, u'')),
             reverse=bool(descending))
    return idx


# ======================================================================
# Staged edits
# ======================================================================
class Stage(object):
    """Edits keyed by (element id, column key) - never by cell position.

    Survives sorting, filtering and column rebuilds. Undo is per batch:
    a paste into forty cells is one Ctrl+Z.
    """

    def __init__(self):
        self.edits = {}
        self.undo = []

    def count(self):
        return len(self.edits)

    def get(self, eid, key):
        return self.edits.get((eid, key))

    def has(self, eid, key):
        return (eid, key) in self.edits

    def apply_batch(self, changes, originals, kinds):
        """changes: [(eid, key, value)]. A value equal to the model's original
        unstages that cell. Returns the cells whose staged state moved."""
        before = []
        touched = []
        for eid, key, value in changes:
            k = (eid, key)
            before.append((k, self.edits.get(k)))
            orig = originals.get(k, u'')
            if same_value(kinds.get(key, 'string'), value, orig):
                if k in self.edits:
                    del self.edits[k]
            else:
                self.edits[k] = value
            touched.append(k)
        if touched:
            self.undo.append(before)
        return touched

    def undo_last(self):
        if not self.undo:
            return []
        batch = self.undo.pop()
        touched = []
        for k, old in reversed(batch):
            if old is None:
                self.edits.pop(k, None)
            else:
                self.edits[k] = old
            touched.append(k)
        return touched

    def clear(self, keys=None):
        if keys is None:
            touched = list(self.edits.keys())
            self.edits = {}
        else:
            touched = [k for k in keys if k in self.edits]
            for k in touched:
                del self.edits[k]
        self.undo = []
        return touched

    def by_element(self):
        """{eid: [(key, value)]} with path mode first, then offset, then the
        rest - a mode change can reset the offset, so the offset goes after."""
        rank = {'pm': 0, 'po': 1}
        out = {}
        for (eid, key), value in self.edits.items():
            out.setdefault(eid, []).append((key, value))
        for eid in out:
            out[eid].sort(key=lambda kv: (rank.get(kv[0], 2), kv[0]))
        return out


# ======================================================================
# Theme
# ======================================================================
THEME_CYCLE = ['follow', 'dark', 'light']


def next_theme(setting):
    s = setting if setting in THEME_CYCLE else 'follow'
    return THEME_CYCLE[(THEME_CYCLE.index(s) + 1) % len(THEME_CYCLE)]


def resolve_theme(setting, canvas_dark):
    """follow + canvas dark -> dark. canvas_dark None (pre-2024, unreadable)
    -> dark, the house default."""
    if setting == 'dark':
        return 'dark'
    if setting == 'light':
        return 'light'
    if canvas_dark is None:
        return 'dark'
    return 'dark' if canvas_dark else 'light'


def theme_chip_text(setting):
    return {'follow': u'Auto', 'dark': u'Dark', 'light': u'Light'}.get(
        setting, u'Auto')


# ======================================================================
# Settings - plain key=value, first '=' only, versioned
# ======================================================================
SETTINGS_VERSION = 1
DEFAULTS = {
    'settings_version': str(SETTINGS_VERSION),
    'theme': 'follow',
    'columns': '',
    'sort_key': 'panel',
    'sort_desc': '0',
    'debug': '1',
    'open_note': '',
}
MIGRATIONS = {
    # 0 -> 1: first release; nothing to carry
    0: {},
}


def parse_settings(text):
    out = dict(DEFAULTS)
    for line in to_text(text).splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        out[k.strip()] = v.strip()
    try:
        ver = int(out.get('settings_version', '0') or 0)
    except Exception:
        ver = 0
    while ver < SETTINGS_VERSION:
        for k, v in MIGRATIONS.get(ver, {}).items():
            out[k] = v
        ver += 1
    out['settings_version'] = str(SETTINGS_VERSION)
    return out


def dump_settings(settings):
    keys = sorted(settings.keys())
    return u'\n'.join(u'{0}={1}'.format(k, to_text(settings[k]).replace(
        '\n', ' ')) for k in keys) + u'\n'


def split_columns(text):
    return [c for c in to_text(text).split('|') if c.strip()]


def join_columns(keys):
    return u'|'.join(keys)


# ======================================================================
# Drawer arithmetic (shrink to taskbar)
# ======================================================================
BAR_GAP = 8.0          # bar floats this far above the taskbar
STACK_GAP = 4.0        # stacked bars


def ease_out_cubic(t):
    t = max(0.0, min(1.0, float(t)))
    return 1.0 - (1.0 - t) ** 3


def park_top(work_top, work_bottom, bar_h, slot):
    """Top of a parked bar in a work area (DIPs). Slot 0 is lowest.
    work_top can be negative (a monitor above the primary)."""
    top = work_bottom - BAR_GAP - bar_h - slot * (bar_h + STACK_GAP)
    return max(work_top, top)


def reopen_top(saved_top, parked_top, bar_top, full_h, work_top, work_bottom):
    """Where the window opens to.

    Bar where it was parked -> back to exactly where it came from.
    Bar dragged elsewhere -> open upward from where the bar now sits, kept
    on that screen.
    """
    if abs(bar_top - parked_top) < 1.0:
        top = saved_top
    else:
        top = bar_top + 0.0
        if top + full_h > work_bottom:
            top = work_bottom - full_h
    if top < work_top:
        top = work_top
    return top


def free_slot(used):
    s = 0
    while s in used:
        s += 1
    return s
