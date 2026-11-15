# -*- coding: utf-8 -*-
"""Bulk Rename rules. No Revit and no WPF in here, so the bench can prove them."""
import os
import re

from brn_version import __version__

TOOL_NAME = u'Bulk Rename'
SETTINGS_NAME = 'bulk_rename.txt'
DEBUG_NAME = 'bulk_rename_debug.txt'
ERROR_NAME = 'bulk_rename_last_error.txt'
SETTINGS_VERSION = 1
MIGRATIONS = {}
DEFAULTS = {
    'theme': 'auto', 'debug': '1',
    'sheet_param_1': 'BGL_Sheet Title 1',
    'sheet_param_2': 'BGL_Sheet Title 2',
    'sheet_param_3': 'BGL_Sheet Title 3',
    'sheet_delimiter': '_',
}
PARAM_KEYS = ('sheet_param_1', 'sheet_param_2', 'sheet_param_3')

FIELD_NAME = 'name'
FIELD_NUMBER = 'number'
FIELDS = (FIELD_NAME, FIELD_NUMBER)

SAME = 'same'
CHANGE = 'change'
CLASH = 'clash'
BAD = 'bad'

ILLEGAL = u'\\:{}[]|;<>?`~'
PARK_PREFIX = u'zz-rbrn-parked-'

# drawer
SLIDE_SECONDS = 0.28
TICK_MS = 15
BAR_GAP = 8.0
STACK_GAP = 4.0


# ==================== text ====================

def to_text(value):
    if value is None:
        return u''
    try:
        return u'' + value
    except Exception:
        return u'{0}'.format(value)


class Rules(object):
    def __init__(self, find=u'', replace=u'', case=False, prefix=u'',
                 suffix=u''):
        self.find = find
        self.replace = replace
        self.case = case
        self.prefix = prefix
        self.suffix = suffix

    def empty(self):
        return not (self.find or self.prefix or self.suffix)


def _merge(segments):
    out = []
    for text, changed in segments:
        if not text:
            continue
        if out and out[-1][1] == changed:
            out[-1] = (out[-1][0] + text, changed)
        else:
            out.append((text, changed))
    return out


def apply_rules(text, rules):
    """Returns (new text, [(piece, changed)]). Find, then prefix, then suffix."""
    text = to_text(text)
    middle = []
    if rules.find:
        flags = re.UNICODE
        if not rules.case:
            flags |= re.IGNORECASE
        pos = 0
        for match in re.finditer(re.escape(rules.find), text, flags):
            middle.append((text[pos:match.start()], False))
            middle.append((rules.replace, True))
            pos = match.end()
        middle.append((text[pos:], False))
    else:
        middle.append((text, False))
    segments = _merge([(rules.prefix, True)] + middle + [(rules.suffix, True)])
    return u''.join([s[0] for s in segments]), segments


def bad_reason(old, new):
    """Why Revit would refuse this text. A character the name already has is
    not held against it, so a prefix on an old name still works."""
    if not new.strip():
        return u'Would leave it empty'
    for ch in ILLEGAL:
        if ch in new and ch not in old:
            return u'Revit does not allow {0} in a name'.format(ch)
    return None


# ==================== rows ====================

class Row(object):
    """One selected item. eid is a real ElementId in Revit; key is its integer."""

    def __init__(self, eid, key, kind, name, number=None, name_scope=None,
                 number_scope=None):
        self.eid = eid
        self.key = key
        self.kind = kind
        self.values = {FIELD_NAME: name}
        self.scopes = {FIELD_NAME: name_scope, FIELD_NUMBER: number_scope}
        if number is not None:
            self.values[FIELD_NUMBER] = number

    def has(self, field):
        return field in self.values


class Item(object):
    """What one field of one row would become."""

    def __init__(self, row, field, rules):
        self.row = row
        self.field = field
        self.old = row.values[field]
        self.scope = row.scopes.get(field)
        self.new, self.segments = apply_rules(self.old, rules)
        self.reason = None
        self.state = SAME
        if self.new != self.old:
            self.reason = bad_reason(self.old, self.new)
            self.state = BAD if self.reason else CHANGE

    def final(self):
        return self.new if self.state == CHANGE else self.old


def natural_key(text):
    parts = re.split(u'([0-9]+)', to_text(text).lower())
    out = []
    for i in range(len(parts)):
        if i % 2:
            out.append((0, int(parts[i]), u''))
        else:
            out.append((1, 0, parts[i]))
    return out


def sort_rows(rows):
    def key(row):
        if row.has(FIELD_NUMBER):
            return (0, natural_key(row.values[FIELD_NUMBER]))
        return (1, natural_key(row.kind), natural_key(row.values[FIELD_NAME]))
    return sorted(rows, key=key)


def evaluate(rows, rules_by_field, taken):
    """taken: {scope: set of names held by elements outside the batch}.
    A name kept by one clash can become the next one's clash, so this repeats
    until nothing moves."""
    items = []
    for field in FIELDS:
        for row in rows:
            if row.has(field):
                items.append(Item(row, field, rules_by_field[field]))
    moved = True
    while moved:
        moved = False
        landing = {}
        for item in items:
            if item.scope is not None:
                landing.setdefault((item.scope, item.final()), []).append(item)
        for item in items:
            if item.state != CHANGE or item.scope is None:
                continue
            if item.new in taken.get(item.scope, ()):
                item.state = CLASH
                item.reason = u'Already used by an item not selected'
                moved = True
            elif len(landing[(item.scope, item.new)]) > 1:
                item.state = CLASH
                item.reason = u'Another selected item would get the same name'
                moved = True
    return items


def changes(items):
    return [i for i in items if i.state == CHANGE]


def needs_parking(items):
    """Changes landing on a name another change is leaving. Those go through a
    parked name so a swap does not clash with itself."""
    going = {}
    for item in changes(items):
        going[(item.scope, item.old)] = item
    out = []
    for item in changes(items):
        other = going.get((item.scope, item.new))
        if other is not None and other is not item and item.scope is not None:
            out.append(other)
    return out


def counts(items):
    out = {SAME: 0, CHANGE: 0, CLASH: 0, BAD: 0}
    for item in items:
        out[item.state] += 1
    return out


def status_line(items):
    tally = counts(items)
    stopped = tally[CLASH] + tally[BAD]
    if not tally[CHANGE] and not stopped:
        return u'Type in a tool to preview the change.'
    text = u'{0} will change'.format(tally[CHANGE])
    if stopped:
        text += u', {0} left alone'.format(stopped)
    return text


def plural(count, word):
    if count == 1:
        return u'1 {0}'.format(word)
    return u'{0} {1}s'.format(count, word)


# ==================== settings ====================

def data_dir():
    root = os.environ.get('APPDATA') or os.path.expanduser('~')
    return os.path.join(root, 'RevoBIM')


def parse_settings(text):
    out = dict(DEFAULTS)
    found = 0
    for line in text.splitlines():
        if '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        if key == 'settings_version':
            try:
                found = int(value)
            except ValueError:
                found = 0
        elif key == 'sheet_delimiter':
            out[key] = value        # a space is a real delimiter
        elif key in DEFAULTS:
            out[key] = value.strip()
    for version in sorted(MIGRATIONS):
        if version > found:
            for key, value in MIGRATIONS[version].items():
                out[key] = value
    if out['theme'] not in ('auto', 'dark', 'light'):
        out['theme'] = DEFAULTS['theme']
    return out


def format_settings(settings):
    lines = ['settings_version={0}'.format(SETTINGS_VERSION)]
    for key in sorted(DEFAULTS):
        lines.append('{0}={1}'.format(key, settings.get(key, DEFAULTS[key])))
    return '\n'.join(lines) + '\n'


def load_settings(path=None):
    path = path or os.path.join(data_dir(), SETTINGS_NAME)
    try:
        with open(path, 'r') as handle:
            text = handle.read()
    except Exception:
        text = ''
    return parse_settings(text)


def save_settings(settings, path=None):
    path = path or os.path.join(data_dir(), SETTINGS_NAME)
    try:
        folder = os.path.dirname(path)
        if not os.path.isdir(folder):
            os.makedirs(folder)
        text = format_settings(settings)
        with open(path, 'w') as handle:
            handle.write(text)
    except Exception:
        pass


class Log(object):
    def __init__(self, enabled=True, path=None):
        self.enabled = enabled
        self.path = path or os.path.join(data_dir(), DEBUG_NAME)

    def __call__(self, text):
        if not self.enabled:
            return
        try:
            folder = os.path.dirname(self.path)
            if not os.path.isdir(folder):
                os.makedirs(folder)
            with open(self.path, 'a') as handle:
                handle.write(to_text(text).encode('ascii', 'replace').decode('ascii') + '\n')
        except Exception:
            pass


# ==================== theme choice ====================

def next_theme(mode):
    order = ['auto', 'dark', 'light']
    return order[(order.index(mode) + 1) % 3] if mode in order else 'auto'


def resolve_theme(mode, canvas):
    if mode in ('dark', 'light'):
        return mode
    return canvas if canvas in ('dark', 'light') else 'dark'


def canvas_from_rgb(red, green, blue):
    light = 0.299 * red + 0.587 * green + 0.114 * blue
    return 'dark' if light < 128 else 'light'


# ==================== window maths ====================

def ease(progress):
    progress = max(0.0, min(1.0, progress))
    return 1.0 - (1.0 - progress) ** 3


def free_slot(slots):
    for index in range(len(slots)):
        if slots[index] is None:
            return index
    return len(slots)


def parked_top(work_top, work_height, bar_height, below):
    """below = height of the bars already stacked under this one."""
    return work_top + work_height - bar_height - BAR_GAP - below


def expand_rect(saved, bar_left, bar_top, parked_left, parked_at, work):
    """Back where it was, or upward from where the bar was carried to."""
    left, top, width, height = saved
    if abs(bar_left - parked_left) <= 2 and abs(bar_top - parked_at) <= 2:
        return (left, top)
    work_left, work_top, work_width, work_height = work
    new_top = bar_top - height + 40
    new_top = max(work_top, min(new_top, work_top + work_height - height))
    new_left = max(work_left, min(bar_left, work_left + work_width - width))
    return (new_left, new_top)


def resize(rect, edge, dx, dy, min_width, min_height):
    """rect (left, top, width, height) dragged by a grip; edge holds L T R B."""
    left, top, width, height = rect
    if 'R' in edge:
        width = max(min_width, width + dx)
    if 'B' in edge:
        height = max(min_height, height + dy)
    if 'L' in edge:
        new = max(min_width, width - dx)
        left += width - new
        width = new
    if 'T' in edge:
        new = max(min_height, height - dy)
        top += height - new
        height = new
    return (left, top, width, height)


def split_sheet_name(name, delimiter, count=3):
    """Always count values. Anything past the last slot stays in it, so no part
    of the name is lost; a short name blanks the rest so no old value is left."""
    name = to_text(name)
    parts = name.split(delimiter) if delimiter else [name]
    if len(parts) > count:
        parts = parts[:count - 1] + [delimiter.join(parts[count - 1:])]
    parts = [p.strip() for p in parts]
    return parts + [u''] * (count - len(parts))


def sheet_writes(name, settings):
    """[(parameter, value)] for the slots that have a parameter set."""
    values = split_sheet_name(name, to_text(settings.get('sheet_delimiter', '')))
    out = []
    for key, value in zip(PARAM_KEYS, values):
        param = to_text(settings.get(key, '')).strip()
        if param:
            out.append((param, value))
    return out


def list_width(pairs, gap=14.0, chrome=34.0):
    """Width the list needs for [(main text width, side text width)]. chrome is
    the row padding, frame and scroll bar."""
    widest = 0.0
    for main, side in pairs:
        widest = max(widest, main + (side + gap if side else 0.0))
    return widest + chrome


def widened(left, width, extra, work_left, work_width):
    """(left, width) grown by extra. Never narrower, never wider than the
    screen, and moved left when the right edge would run off it."""
    if extra <= 0:
        return (left, width)
    new_width = min(width + extra, work_width)
    right_limit = work_left + work_width
    new_left = max(work_left, min(left, right_limit - new_width))
    return (new_left, new_width)


class SlowClicks(object):
    """Three clicks, each gap 0.25 to 2 seconds. Same timestamp counts once."""

    def __init__(self, need=3, low=250, high=2000):
        self.need, self.low, self.high = need, low, high
        self.count = 0
        self.last = None

    def click(self, stamp):
        if self.last == stamp:
            return False
        if self.last is None or not self.low <= stamp - self.last <= self.high:
            self.count = 1
        else:
            self.count += 1
        self.last = stamp
        if self.count >= self.need:
            self.count = 0
            self.last = None
            return True
        return False
