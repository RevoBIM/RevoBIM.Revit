# -*- coding: utf-8 -*-
"""Schematic Marriage - pure logic.

No Revit and no WPF in here, so every rule can be run under plain CPython by
bench_logic.py: record serialisation, templates, duplicate / merge, which
templates suit a marriage, and how a source value becomes a target value.
"""
import os
import random
import re
import time

try:
    _TEXT = unicode          # IronPython 2.7
except NameError:            # IronPython 3 / CPython bench
    _TEXT = str


# ==========================================================================
# text helpers
# ==========================================================================

def to_text(value):
    if value is None:
        return u''
    if isinstance(value, _TEXT):
        return value
    try:
        return _TEXT(value)
    except Exception:
        try:
            return value.decode('utf-8', 'replace')
        except Exception:
            return u''


def escape(text):
    """One record value on one line: backslash, tab, CR and LF escaped."""
    out = []
    for ch in to_text(text):
        if ch == u'\\':
            out.append(u'\\\\')
        elif ch == u'\t':
            out.append(u'\\t')
        elif ch == u'\n':
            out.append(u'\\n')
        elif ch == u'\r':
            out.append(u'\\r')
        else:
            out.append(ch)
    return u''.join(out)


def unescape(text):
    out = []
    text = to_text(text)
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == u'\\' and i + 1 < n:
            nxt = text[i + 1]
            if nxt == u't':
                out.append(u'\t')
            elif nxt == u'n':
                out.append(u'\n')
            elif nxt == u'r':
                out.append(u'\r')
            else:
                out.append(nxt)
            i += 2
            continue
        out.append(ch)
        i += 1
    return u''.join(out)


def serialize(pairs):
    """[(key, value)] -> 'key=value' lines. Keys may repeat (mappings)."""
    lines = []
    for key, value in pairs:
        lines.append(to_text(key) + u'=' + escape(value))
    return u'\n'.join(lines)


def parse(text):
    """'key=value' lines -> [(key, value)], split on the FIRST '=' only.
    Blank and damaged lines are skipped rather than breaking the load."""
    pairs = []
    for raw in to_text(text).splitlines():
        line = raw.strip(u'\r')
        if not line.strip() or u'=' not in line:
            continue
        key, value = line.split(u'=', 1)
        key = key.strip()
        if not key:
            continue
        pairs.append((key, unescape(value)))
    return pairs


def first(pairs, key, default=u''):
    for k, v in pairs:
        if k == key:
            return v
    return default


_COUNTER = [0]


def new_id():
    """Unique id for a record (not a Revit id): time, a per-session counter
    and 32 random bits, so two people adding at the same moment on a
    workshared model cannot collide, nor can a burst created in one run."""
    _COUNTER[0] = (_COUNTER[0] + 1) & 0xFFFF
    stamp = int(time.time() * 1000) & 0xFFFFFFFFFFF
    return u'%011x%04x%08x' % (stamp, _COUNTER[0], random.getrandbits(32))


def now_text():
    return to_text(time.strftime('%Y-%m-%d %H:%M'))


_NUM = re.compile(r'(\d+)')


def natural_key(text):
    parts = _NUM.split(to_text(text).lower())
    key = []
    for p in parts:
        if p.isdigit():
            key.append((0, int(p), u''))
        else:
            key.append((1, 0, p))
    return key


def plural(n, word):
    return u'{0} {1}{2}'.format(n, word, u'' if n == 1 else u's')


def matches_keywords(text, keywords):
    """Every word in keywords appears in text, case-insensitive."""
    hay = to_text(text).lower()
    for word in to_text(keywords).lower().split():
        if word not in hay:
            return False
    return True


# ==========================================================================
# records
# ==========================================================================

KIND_MARRIAGE = u'marriage'
KIND_TEMPLATE = u'template'


class Marriage(object):
    """One source element married to one target element.

    Keyed by UniqueId, not ElementId: a UniqueId is stable for the life of the
    element in this model, which is all a marriage needs. The ElementId is
    shown in the table but never stored as the key."""

    def __init__(self):
        self.id = new_id()
        self.src_uid = u''
        self.tgt_uid = u''
        self.src_cat_id = u''
        self.src_cat_name = u''
        self.tgt_cat_id = u''
        self.tgt_cat_name = u''
        self.template_id = u''
        self.created = now_text()
        # runtime only - never stored
        self.applied_tid = u''      # template id as it is in the model; differs = staged
        self.storage_id = None
        self.src_label = u''
        self.tgt_label = u''
        self.src_eid = u''
        self.tgt_eid = u''
        self.src_view = u''
        self.tgt_view = u''
        self.src_missing = False
        self.tgt_missing = False
        self.status = u''
        self.status_kind = u''      # '', 'ok', 'warn', 'bad'

    def to_pairs(self):
        return [
            (u'id', self.id), (u'src', self.src_uid), (u'tgt', self.tgt_uid),
            (u'src_cat', self.src_cat_id), (u'src_cat_name', self.src_cat_name),
            (u'tgt_cat', self.tgt_cat_id), (u'tgt_cat_name', self.tgt_cat_name),
            (u'template', self.template_id), (u'created', self.created),
        ]

    def to_text(self):
        return serialize(self.to_pairs())

    @staticmethod
    def from_text(text):
        p = parse(text)
        m = Marriage()
        m.id = first(p, u'id') or new_id()
        m.src_uid = first(p, u'src')
        m.tgt_uid = first(p, u'tgt')
        m.src_cat_id = first(p, u'src_cat')
        m.src_cat_name = first(p, u'src_cat_name')
        m.tgt_cat_id = first(p, u'tgt_cat')
        m.tgt_cat_name = first(p, u'tgt_cat_name')
        m.template_id = first(p, u'template')
        m.applied_tid = m.template_id
        m.created = first(p, u'created')
        return m

    def pending(self):
        """A template change staged in the window but not yet written to the model."""
        return self.template_id != self.applied_tid

    def value(self, key):
        """Cell text for the marriage table."""
        if key == u'src_cat':
            return self.src_cat_name
        if key == u'src':
            return self.src_label
        if key == u'src_id':
            return self.src_eid
        if key == u'tgt_cat':
            return self.tgt_cat_name
        if key == u'tgt':
            return self.tgt_label
        if key == u'tgt_id':
            return self.tgt_eid
        if key == u'status':
            return self.status
        return u''


class Mapping(object):
    """Push one source parameter into one target parameter."""

    def __init__(self, src_name=u'', tgt_name=u'', tgt_scope=u'instance',
                 src_storage=u'', tgt_storage=u''):
        self.src_name = to_text(src_name)
        self.tgt_name = to_text(tgt_name)
        self.tgt_scope = to_text(tgt_scope) or u'instance'
        self.src_storage = to_text(src_storage)
        self.tgt_storage = to_text(tgt_storage)

    def key(self):
        return (self.tgt_name, self.tgt_scope)

    def to_field(self):
        return u'\t'.join([escape(self.src_name), escape(self.tgt_name),
                           self.tgt_scope, self.src_storage, self.tgt_storage])

    @staticmethod
    def from_field(text):
        parts = to_text(text).split(u'\t')
        while len(parts) < 5:
            parts.append(u'')
        return Mapping(unescape(parts[0]), unescape(parts[1]), parts[2] or u'instance',
                       parts[3], parts[4])

    def copy(self):
        return Mapping(self.src_name, self.tgt_name, self.tgt_scope,
                       self.src_storage, self.tgt_storage)

    def value(self, key):
        if key == u'src':
            return self.src_name
        if key == u'arrow':
            return u'\u2192'
        if key == u'tgt':
            return self.tgt_name
        if key == u'kind':
            note = storage_label(self.src_storage) + u' > ' + storage_label(self.tgt_storage)
            if self.tgt_scope == u'type':
                return u'type param  ' + note
            return note
        return u''


class Template(object):
    """A named set of parameter pushes for one source category -> target category."""

    def __init__(self):
        self.id = new_id()
        self.name = u''
        self.src_cat_id = u''
        self.src_cat_name = u''
        self.tgt_cat_id = u''
        self.tgt_cat_name = u''
        self.mappings = []
        self.clear_empty = False
        self.modified = now_text()
        self.storage_id = None      # runtime only
        self.used = 0               # runtime only

    def to_pairs(self):
        pairs = [
            (u'id', self.id), (u'name', self.name),
            (u'src_cat', self.src_cat_id), (u'src_cat_name', self.src_cat_name),
            (u'tgt_cat', self.tgt_cat_id), (u'tgt_cat_name', self.tgt_cat_name),
            (u'clear_empty', u'1' if self.clear_empty else u'0'),
            (u'modified', self.modified),
        ]
        for m in self.mappings:
            pairs.append((u'map', m.to_field()))
        return pairs

    def to_text(self):
        return serialize(self.to_pairs())

    @staticmethod
    def from_pairs(p):
        t = Template()
        t.id = first(p, u'id') or new_id()
        t.name = first(p, u'name')
        t.src_cat_id = first(p, u'src_cat')
        t.src_cat_name = first(p, u'src_cat_name')
        t.tgt_cat_id = first(p, u'tgt_cat')
        t.tgt_cat_name = first(p, u'tgt_cat_name')
        t.clear_empty = first(p, u'clear_empty') == u'1'
        t.modified = first(p, u'modified')
        t.mappings = [Mapping.from_field(v) for k, v in p if k == u'map']
        return t

    @staticmethod
    def from_text(text):
        return Template.from_pairs(parse(text))

    def copy(self, keep_id=True):
        t = Template.from_text(self.to_text())
        if not keep_id:
            t.id = new_id()
        t.storage_id = self.storage_id if keep_id else None
        t.used = self.used if keep_id else 0
        return t

    def categories_label(self):
        return self.src_cat_name + u'  >  ' + self.tgt_cat_name

    def value(self, key):
        if key == u'name':
            return self.name
        if key == u'src_cat':
            return self.src_cat_name
        if key == u'tgt_cat':
            return self.tgt_cat_name
        if key == u'params':
            return to_text(len(self.mappings))
        if key == u'used':
            return to_text(self.used)
        return u''


def record_kind_and_object(kind, text):
    if kind == KIND_MARRIAGE:
        return Marriage.from_text(text)
    if kind == KIND_TEMPLATE:
        return Template.from_text(text)
    return None


# ==========================================================================
# rules over the collections
# ==========================================================================

def usage_counts(marriages):
    counts = {}
    for m in marriages:
        if m.template_id:
            counts[m.template_id] = counts.get(m.template_id, 0) + 1
    return counts


def apply_usage(templates, marriages):
    counts = usage_counts(marriages)
    for t in templates:
        t.used = counts.get(t.id, 0)


def is_compatible(template, src_cat_id, tgt_cat_id):
    return (to_text(template.src_cat_id) == to_text(src_cat_id) and
            to_text(template.tgt_cat_id) == to_text(tgt_cat_id))


def compatible_templates(templates, marriages):
    """Templates that suit EVERY marriage given (all must share categories)."""
    if not marriages:
        return []
    pairs = set((to_text(m.src_cat_id), to_text(m.tgt_cat_id)) for m in marriages)
    if len(pairs) != 1:
        return []
    src, tgt = list(pairs)[0]
    out = [t for t in templates if is_compatible(t, src, tgt)]
    out.sort(key=lambda t: natural_key(t.name))
    return out


def pair_exists(marriages, src_uid, tgt_uid):
    for m in marriages:
        if m.src_uid == src_uid and m.tgt_uid == tgt_uid:
            return m
    return None


def unique_name(base, existing):
    names = set(to_text(n).lower() for n in existing)
    base = to_text(base).strip() or u'Template'
    if base.lower() not in names:
        return base
    n = 2
    while True:
        cand = u'{0} ({1})'.format(base, n)
        if cand.lower() not in names:
            return cand
        n += 1


def duplicate_template(template, existing_names):
    t = template.copy(keep_id=False)
    t.name = unique_name(template.name + u' - Copy', existing_names)
    t.modified = now_text()
    return t


def add_mapping(template, mapping):
    """One source per target parameter. Returns (ok, reason)."""
    if not mapping.src_name or not mapping.tgt_name:
        return False, u'Pick a source and a target parameter first.'
    for m in template.mappings:
        if m.key() == mapping.key():
            return False, u'"{0}" is already being written by "{1}".'.format(m.tgt_name, m.src_name)
    ok, note = storage_compatible(mapping.src_storage, mapping.tgt_storage)
    if not ok:
        return False, note
    template.mappings.append(mapping)
    return True, note


def merge_templates(master, others):
    """Union of pushes into a copy of master. Master wins where both write the
    same target parameter. Raises ValueError on mismatched categories.
    Returns (merged_template, conflicts[(target, kept_source, dropped_source)])."""
    merged = master.copy(keep_id=True)
    conflicts = []
    for o in others:
        if not is_compatible(o, master.src_cat_id, master.tgt_cat_id):
            raise ValueError(u'"{0}" is {1}, not {2}. Only templates for the same '
                             u'categories can be merged.'.format(
                                 o.name, o.categories_label(), master.categories_label()))
        for m in o.mappings:
            clash = None
            for k in merged.mappings:
                if k.key() == m.key():
                    clash = k
                    break
            if clash is None:
                merged.mappings.append(m.copy())
            elif clash.src_name != m.src_name:
                conflicts.append((m.tgt_name, clash.src_name, m.src_name))
    merged.modified = now_text()
    return merged, conflicts


def plan_template_delete(template, marriages):
    """Marriages that would be left without a template."""
    return [m for m in marriages if m.template_id == template.id]


# ==========================================================================
# undo / redo
# ==========================================================================

class UndoStack(object):
    """Snapshots, not commands: each step is (label, before, after) and the
    caller restores whichever side it is handed. A step that changes nothing is
    not recorded. merge=True folds a run of steps with the same label (typing
    a name) into one, and drops it if the run ends where it started."""

    def __init__(self, limit=200):
        self.limit = limit
        self.done = []
        self.undone = []

    def push(self, label, before, after, merge=False):
        if before == after:
            return False
        if merge and self.done and self.done[-1][0] == label:
            _l, first_before, _a = self.done[-1]
            if first_before == after:
                self.done.pop()
            else:
                self.done[-1] = (label, first_before, after)
        else:
            self.done.append((label, before, after))
            if len(self.done) > self.limit:
                self.done = self.done[-self.limit:]
        self.undone = []
        return True

    def undo(self):
        """-> (label, state to restore) or None."""
        if not self.done:
            return None
        step = self.done.pop()
        self.undone.append(step)
        return step[0], step[1]

    def redo(self):
        if not self.undone:
            return None
        step = self.undone.pop()
        self.done.append(step)
        return step[0], step[2]

    def can_undo(self):
        return bool(self.done)

    def can_redo(self):
        return bool(self.undone)

    def next_undo_label(self):
        return self.done[-1][0] if self.done else u''

    def next_redo_label(self):
        return self.undone[-1][0] if self.undone else u''

    def clear(self):
        self.done = []
        self.undone = []


def template_snapshot(marriages):
    return dict((m.id, m.template_id) for m in marriages)


def restore_templates(marriages, snapshot):
    """Put template ids back from a snapshot; marriages since removed are skipped."""
    n = 0
    for m in marriages:
        if m.id in snapshot and m.template_id != snapshot[m.id]:
            m.template_id = snapshot[m.id]
            n += 1
    return n


def pending_marriages(marriages):
    return [m for m in marriages if m.pending()]


def keep_staged(fresh, old):
    """After re-reading the model, carry staged (unapplied) template changes
    over onto the fresh records, so a reload never throws them away."""
    staged = dict((m.id, m.template_id) for m in old if m.pending())
    for m in fresh:
        m.applied_tid = m.template_id
        if m.id in staged:
            m.template_id = staged[m.id]
    return len([m for m in fresh if m.id in staged])


# ==========================================================================
# values: how a source parameter becomes a target parameter
# ==========================================================================

S_STRING = u'String'
S_DOUBLE = u'Double'
S_INT = u'Integer'
S_ID = u'ElementId'

_YES = (u'yes', u'y', u'true', u'1', u'on', u'x')
_NO = (u'no', u'n', u'false', u'0', u'off', u'')


def storage_label(storage):
    return {S_STRING: u'Text', S_DOUBLE: u'Number', S_INT: u'Integer',
            S_ID: u'Element'}.get(to_text(storage), to_text(storage) or u'?')


def storage_compatible(src, tgt):
    """(ok, note) - whether a push from src storage to tgt storage can work."""
    src = to_text(src)
    tgt = to_text(tgt)
    if not src or not tgt:
        return True, u''
    if tgt == S_ID and src != S_ID:
        return False, u'Only an element reference can be pushed into an element reference.'
    if src == tgt:
        return True, u''
    if tgt == S_STRING:
        return True, u''
    if src == S_ID:
        return False, u'An element reference can only go into text or another element reference.'
    if src == S_STRING:
        return True, u'Text is converted when pushed. A value that is not a number is reported, not written.'
    return True, u'Converted through the displayed value, in project units.'


_NUMBER = re.compile(r'[-+]?\d+(?:[.,]\d+)?')


def number_in(text):
    m = _NUMBER.search(to_text(text))
    if not m:
        return None
    try:
        return float(m.group(0).replace(u',', u'.'))
    except Exception:
        return None


def plan_value(src, tgt_storage, clear_empty=False):
    """Decide the write. src is a dict with:
        storage, has_value, text (AsString), vstring (AsValueString),
        raw (AsDouble / AsInteger), name (for an element reference)
    Returns (action, payload, note) where action is one of
        'string', 'double', 'int', 'vstring', 'id', 'skip'."""
    s = to_text(src.get(u'storage'))
    t = to_text(tgt_storage)
    if not src.get(u'has_value'):
        if clear_empty and t == S_STRING:
            return u'string', u'', u'cleared (source empty)'
        return u'skip', None, u'source has no value'
    ok, note = storage_compatible(s, t)
    if not ok:
        return u'skip', None, note

    text = src.get(u'text')
    vstring = src.get(u'vstring')
    raw = src.get(u'raw')

    if t == S_STRING:
        if s == S_STRING:
            return u'string', to_text(text), u''
        if s == S_ID:
            return u'string', to_text(src.get(u'name') or vstring or u''), u''
        if vstring not in (None, u''):
            return u'string', to_text(vstring), u''
        return u'string', to_text(raw), u''

    if t == S_ID:
        return u'id', None, u''

    if t == S_DOUBLE:
        if s == S_DOUBLE:
            return u'double', float(raw), u''
        if s == S_INT:
            return u'vstring', to_text(int(raw)), u''
        # text: Revit parses it in project units
        if number_in(text) is None:
            return u'skip', None, u'"{0}" is not a number'.format(to_text(text))
        return u'vstring', to_text(text).strip(), u''

    if t == S_INT:
        if s == S_INT:
            return u'int', int(raw), u''
        if s == S_DOUBLE:
            num = number_in(vstring) if vstring else None
            if num is None:
                num = float(raw)
            return u'int', int(round(num)), u''
        word = to_text(text).strip().lower()
        if word in _YES and word:
            return u'int', 1, u''
        if word in _NO:
            return u'int', 0, u''
        num = number_in(text)
        if num is None:
            return u'skip', None, u'"{0}" is not a whole number or yes / no'.format(to_text(text))
        return u'int', int(round(num)), u''

    return u'skip', None, u'unsupported parameter type'


def already_equal(action, payload, current):
    """current is a dict like src (read from the TARGET). True when the write
    would change nothing - those targets are never borrowed."""
    if not current:
        return False
    if action == u'string':
        return to_text(current.get(u'text')) == to_text(payload)
    if action == u'double':
        try:
            return abs(float(current.get(u'raw')) - float(payload)) < 1e-9
        except Exception:
            return False
    if action == u'int':
        try:
            return int(current.get(u'raw')) == int(payload)
        except Exception:
            return False
    if action == u'vstring':
        return to_text(current.get(u'vstring')).strip() == to_text(payload).strip()
    return False


def find_conflicts(writes):
    """writes: list of (owner_key, param_name, value_text, marriage_no).
    Returns {index: earlier_marriage_no} for writes that would put a DIFFERENT
    value where an earlier write already put one (a type parameter shared by
    two targets, or one target fed by two sources)."""
    seen = {}
    clashes = {}
    for i, (owner, pname, value, no) in enumerate(writes):
        key = (owner, pname)
        if key in seen:
            first_value, first_no = seen[key]
            if first_value != value:
                clashes[i] = first_no
            continue
        seen[key] = (value, no)
    return clashes


# ==========================================================================
# template library file (share across projects / ACC)
# ==========================================================================

LIBRARY_HEADER = u'# RevoBIM Schematic Marriage - Parameter Push Templates'


def export_templates(templates):
    blocks = [LIBRARY_HEADER]
    for t in templates:
        blocks.append(u'[template]')
        blocks.append(t.to_text())
    return u'\n'.join(blocks) + u'\n'


def import_templates(text):
    out = []
    current = None
    for raw in to_text(text).splitlines():
        line = raw.strip(u'\r')
        if line.strip() == u'[template]':
            if current is not None:
                out.append(current)
            current = []
            continue
        if current is None or line.startswith(u'#'):
            continue
        current.append(line)
    if current is not None:
        out.append(current)
    templates = []
    for lines in out:
        t = Template.from_text(u'\n'.join(lines))
        if t.name:
            templates.append(t)
    return templates


def plan_import(incoming, existing):
    """-> list of (template, action) where action is 'new', 'update' or 'rename'.
    Same id updates in place; a different id with a clashing name is renamed."""
    by_id = dict((t.id, t) for t in existing)
    names = [t.name for t in existing]
    plan = []
    for t in incoming:
        if t.id in by_id:
            plan.append((t, u'update'))
            continue
        if t.name.lower() in set(n.lower() for n in names):
            t.name = unique_name(t.name + u' (imported)', names)
            plan.append((t, u'rename'))
        else:
            plan.append((t, u'new'))
        names.append(t.name)
    return plan


# ==========================================================================
# shrink to taskbar - the drawer's arithmetic (pure, so the bench proves it)
# ==========================================================================

PARK_GAP = 6.0


def park_rect(win_top, win_h, header_h, area_bottom, offset=0.0):
    """Where a window's bar parks: its bottom sits on the bottom of the
    screen's work area (just above the taskbar), raised by offset when
    another bar is already parked there.
    -> (bar_top, overlay_top, overlay_h, drop) where the overlay is the strip
    the drawer animates in and drop is how far the bar travels (+ = down)."""
    bar_top = area_bottom - offset - header_h
    overlay_top = min(win_top, bar_top)
    overlay_bottom = max(win_top + win_h, bar_top + header_h)
    return bar_top, overlay_top, overlay_bottom - overlay_top, bar_top - win_top


def reopen_rect(bar_top, header_h, full_h, area_top):
    """Reopen upwards from wherever the bar now sits (it may have been
    dragged): the window's bottom lands on the bar's bottom, never above the
    top of the work area - which is negative on a monitor above the primary.
    -> (window_top, drop) where drop is how far the bar travels up."""
    top = max(area_top, bar_top + header_h - full_h)
    return top, bar_top - top


# ==========================================================================
# settings - plain key=value under %APPDATA%\RevoBIM\
# ==========================================================================

SETTINGS_VERSION = 1
DEFAULTS = {
    u'settings_version': to_text(SETTINGS_VERSION),
    u'theme': u'follow',          # follow / dark / light
    u'debug': u'0',
    u'main_w': u'1220', u'main_h': u'780',
    u'tpl_w': u'1220', u'tpl_h': u'800',
    u'tpl_list_w': u'600', u'tpl_edit_w': u'720', u'tpl_pinned': u'0',
    u'library_folder': u'',
}
# version -> {key: value} added when an older file is loaded
MIGRATIONS = {}


def settings_dir():
    base = os.environ.get('APPDATA') or os.path.expanduser('~')
    return os.path.join(base, 'RevoBIM')


def settings_path():
    return os.path.join(settings_dir(), 'schematic_marriage.txt')


def debug_path():
    return os.path.join(settings_dir(), 'schematic_marriage_debug.txt')


def load_settings(path=None):
    path = path or settings_path()
    values = dict(DEFAULTS)
    try:
        if os.path.exists(path):
            with open(path, 'rb') as fh:
                raw = fh.read()
            try:
                text = raw.decode('utf-8')
            except Exception:
                text = to_text(raw)
            for key, value in parse(text):
                if key in DEFAULTS:
                    values[key] = value
    except Exception:
        return dict(DEFAULTS)
    try:
        version = int(values.get(u'settings_version') or 0)
    except Exception:
        version = 0
    for v in sorted(MIGRATIONS):
        if version < v:
            for key, value in MIGRATIONS[v].items():
                values[key] = value
    values[u'settings_version'] = to_text(SETTINGS_VERSION)
    if values.get(u'theme') not in (u'follow', u'dark', u'light'):
        values[u'theme'] = u'follow'
    return values


def save_settings(values, path=None):
    path = path or settings_path()
    try:
        folder = os.path.dirname(path)
        if not os.path.isdir(folder):
            os.makedirs(folder)
        keys = sorted(DEFAULTS)
        text = serialize([(k, values.get(k, DEFAULTS[k])) for k in keys])
        data = text.encode('utf-8')
        with open(path, 'wb') as fh:
            fh.write(data)
        return True
    except Exception:
        return False


def next_theme(setting):
    order = [u'follow', u'dark', u'light']
    try:
        return order[(order.index(setting) + 1) % 3]
    except ValueError:
        return u'follow'


def theme_label(setting, resolved):
    if setting == u'follow':
        return u'Auto \u00b7 ' + (u'Dark' if resolved == u'dark' else u'Light')
    return u'Dark' if setting == u'dark' else u'Light'
