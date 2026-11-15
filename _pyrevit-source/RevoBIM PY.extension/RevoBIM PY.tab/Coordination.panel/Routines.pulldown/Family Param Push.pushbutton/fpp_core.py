# -*- coding: utf-8 -*-
"""Family Param Push rules. No .NET and no Revit in here: everything that
decides a value, a row or a window position is a plain function the bench can
run under CPython."""
import codecs
import os
import re
import time

SETTINGS_VERSION = 1
MIGRATIONS = {}
DEFAULTS = {
    'settings_version': str(SETTINGS_VERSION),
    'theme': 'auto',
    'debug': '1',
    'clear_empty': '0',
    'width': '1360',
    'height': '860',
    'modal': '0',
}
SLIDE_SECONDS = 0.28
TICK_MS = 15
BAR_GAP = 8.0
STACK_GAP = 4.0
BATCH_SIZE = 200
PARAM_SAMPLE_PER_TYPE = 12
PARAM_SAMPLE_MAX = 40
ALL_CATEGORIES = u'All categories'

try:
    text_type = unicode
    string_types = (basestring,)
except NameError:
    text_type = str
    string_types = (str,)


def to_text(value):
    if value is None:
        return u''
    if isinstance(value, text_type):
        return value
    try:
        return text_type(value)
    except Exception:
        try:
            return str(value).decode('utf-8', 'replace')
        except Exception:
            return u''


def natural_key(value):
    parts = re.split(r'(\d+)', to_text(value).lower())
    out = []
    for part in parts:
        if part.isdigit():
            out.append((0, int(part), u''))
        else:
            out.append((1, 0, part))
    return out


def words_of(query):
    return [w for w in to_text(query).lower().split() if w]


def matches(words, haystack):
    low = to_text(haystack).lower()
    for word in words:
        if word not in low:
            return False
    return True


# ===================== settings and log =====================

def appdata_dir():
    base = os.environ.get('APPDATA') or os.path.expanduser('~')
    return os.path.join(base, 'RevoBIM')


def settings_path():
    return os.path.join(appdata_dir(), 'family_param_push.txt')


def log_path():
    return os.path.join(appdata_dir(), 'family_param_push_debug.txt')


def error_path():
    return os.path.join(appdata_dir(), 'family_param_push_last_error.txt')


def backup_dir():
    return os.path.join(appdata_dir(), 'family_param_replace_backups')


def note_path():
    return os.path.join(appdata_dir(), 'family_param_push_opened.txt')


def parse_settings(text):
    out = dict(DEFAULTS)
    for line in to_text(text).splitlines():
        if '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        if key in DEFAULTS:
            out[key] = value.strip()
    try:
        have = int(out.get('settings_version', '0'))
    except ValueError:
        have = 0
    for version in sorted(MIGRATIONS):
        if have < version:
            out.update(MIGRATIONS[version])
    out['settings_version'] = str(SETTINGS_VERSION)
    return out


def load_settings(path=None):
    path = path or settings_path()
    try:
        with codecs.open(path, 'r', 'utf-8') as handle:
            data = handle.read()
    except Exception:
        data = u''
    return parse_settings(data)


def save_settings(settings, path=None):
    path = path or settings_path()
    try:
        folder = os.path.dirname(path)
        if not os.path.isdir(folder):
            os.makedirs(folder)
        lines = [u'{0}={1}'.format(k, to_text(settings.get(k, DEFAULTS[k])))
                 for k in sorted(DEFAULTS)]
        with codecs.open(path, 'w', 'utf-8') as handle:
            handle.write(u'\n'.join(lines))
        return True
    except Exception:
        return False


def log(settings, text):
    if settings is not None and settings.get('debug') != '1':
        return
    try:
        folder = appdata_dir()
        if not os.path.isdir(folder):
            os.makedirs(folder)
        with codecs.open(log_path(), 'a', 'utf-8') as handle:
            handle.write(u'{0}  {1}\n'.format(
                time.strftime('%Y-%m-%d %H:%M:%S'), to_text(text)))
    except Exception:
        pass


def write_text(path, text):
    try:
        folder = os.path.dirname(path)
        if not os.path.isdir(folder):
            os.makedirs(folder)
        with codecs.open(path, 'w', 'utf-8') as handle:
            handle.write(to_text(text))
        return True
    except Exception:
        return False


def read_text(path):
    try:
        with codecs.open(path, 'r', 'utf-8') as handle:
            return handle.read()
    except Exception:
        return u''


def engine_note_is_stale(note, version):
    """A note left by this version means the last window never proved alive.
    A note from any other version says nothing about this one."""
    return to_text(note).strip() == to_text(version)


# ===================== window maths =====================

def ease_out(p):
    p = max(0.0, min(1.0, p))
    return 1.0 - (1.0 - p) ** 3


def lerp(a, b, p):
    return a + (b - a) * p


def parked_top(area_top, area_height, bar, slot=0):
    """area_top can be negative: a monitor above the primary."""
    return area_top + area_height - BAR_GAP - bar - slot * (bar + STACK_GAP)


def reopen_top(bar_top, bar, full_height, area_top, area_height):
    """Open upward from where the bar now sits, kept on that screen."""
    top = bar_top + bar - full_height
    top = min(top, area_top + area_height - full_height)
    return max(top, area_top)


def clamp_left(left, width, area_left, area_width):
    left = min(left, area_left + area_width - width)
    return max(left, area_left)


class EggWatcher(object):
    """Three slow clicks: each gap between 0.25 and 2 seconds."""
    def __init__(self):
        self.count = 0
        self.last = None

    def click(self, now):
        if self.last is None or not (0.25 <= now - self.last <= 2.0):
            self.count = 1
        else:
            self.count += 1
        self.last = now
        if self.count >= 3:
            self.count = 0
            self.last = None
            return True
        return False


class ProgressMeter(object):
    """Throttles reports to at least 1% and about 0.12 s apart."""
    def __init__(self, callback, clock=None):
        self.callback = callback
        self.clock = clock or time.time
        self.last_pct = -1
        self.last_time = -1000000.0

    def report(self, done, total, label=u''):
        if self.callback is None or total <= 0:
            return
        pct = int(done * 100.0 / total)
        now = self.clock()
        if done < total and (pct == self.last_pct
                             or now - self.last_time < 0.12):
            return
        self.last_pct = pct
        self.last_time = now
        try:
            self.callback(pct, label)
        except Exception:
            self.callback = None


# ===================== families and rows =====================

class TypeRec(object):
    def __init__(self, idv, eid, name, count=0):
        self.idv = idv
        self.eid = eid
        self.name = to_text(name)
        self.count = count


class FamilyRec(object):
    def __init__(self, name, category, cat_id=None):
        self.name = to_text(name)
        self.category = to_text(category)
        self.cat_id = cat_id
        self.key = family_key(category, name)
        self.types = []
        self.family_id = None           # loadable families only
        self.editable = False

    def placed(self):
        return sum([t.count for t in self.types])


def family_key(category, name):
    return u'{0}|{1}'.format(to_text(category), to_text(name))


def sort_families(families):
    for fam in families:
        fam.types.sort(key=lambda t: natural_key(t.name))
    return sorted(families, key=lambda f: (natural_key(f.category),
                                           natural_key(f.name)))


def category_options(families):
    counts = {}
    for fam in families:
        counts[fam.category] = counts.get(fam.category, 0) + 1
    names = sorted(counts, key=natural_key)
    return [ALL_CATEGORIES] + names


def row(key, kind, text, cat=u'', count=u'', opened=u'0', picked=u'0',
        note=u''):
    return {'key': key, 'kind': kind, 'text': to_text(text),
            'cat': to_text(cat), 'count': to_text(count), 'open': opened,
            'picked': picked, 'note': to_text(note)}


def family_rows(families, category, query, opened, picks):
    """The left list. A search that hits a type opens its family and shows
    only the types that matched; one that hits the family leaves it as it is."""
    words = words_of(query)
    out = []
    for fam in families:
        if category and category != ALL_CATEGORIES \
                and fam.category != category:
            continue
        head = u'{0} {1}'.format(fam.name, fam.category)
        fam_hit = matches(words, head)
        hits = [t for t in fam.types
                if matches(words, u'{0} {1}'.format(head, t.name))]
        if not fam_hit and not hits:
            continue
        forced = bool(words) and not fam_hit
        show_types = forced or fam.key in opened
        shown = hits if forced else fam.types
        picked_all = all([picks.has_type(t.idv) for t in fam.types]) \
            and bool(fam.types)
        out.append(row(u'f:' + fam.key, u'f', fam.name, fam.category,
                       fam.placed(), u'1' if show_types else u'0',
                       u'1' if picked_all else u'0'))
        if show_types:
            for typ in shown:
                out.append(row(u't:{0}'.format(typ.idv), u't', typ.name,
                               fam.category, typ.count, u'0',
                               u'1' if picks.has_type(typ.idv) else u'0'))
    return out


def picked_rows(picks, opened):
    out = []
    for pick in picks.ordered():
        count = len(pick.mappings)
        note = u'{0} mapping{1}'.format(count, u'' if count == 1 else u's') \
            if count else u'No mapping yet'
        total = len(pick.fam.types)
        label = u'{0} of {1}'.format(len(pick.type_ids), total)
        show = pick.fam.key in opened
        out.append(row(u'f:' + pick.fam.key, u'f', pick.fam.name,
                       pick.fam.category, label, u'1' if show else u'0',
                       u'0', note))
        if show:
            for typ in pick.fam.types:
                if typ.idv in pick.type_ids:
                    out.append(row(u't:{0}'.format(typ.idv), u't', typ.name,
                                   pick.fam.category, typ.count))
    return out


# ===================== parameters and mappings =====================

class ParamRef(object):
    def __init__(self, name, scope, storage, spec=u'', yesno=False, guid=None,
                 bip=None, writable=True, sample=u''):
        self.name = to_text(name)
        self.scope = scope              # 'I' instance, 'T' type
        self.storage = to_text(storage)
        self.spec = to_text(spec)
        self.yesno = yesno
        self.guid = guid
        self.bip = bip
        self.writable = writable
        self.sample = to_text(sample)
        self.locked = False             # formula or reporting: no value to keep
        self.key = u'{0}|{1}|{2}'.format(scope, self.name, guid or u'')

    def kind(self):
        if self.yesno:
            return u'Yes/No'
        return {u'String': u'Text', u'Double': u'Number',
                u'Integer': u'Integer',
                u'ElementId': u'Element'}.get(self.storage, self.storage)

    def scope_label(self):
        return u'Type' if self.scope == 'T' else u'Instance'

    def origin(self):
        if self.guid:
            return u'Shared'
        if self.bip is not None:
            return u'Built-in'
        return u'Project'

    def label(self):
        return u'{0} ({1})'.format(self.name, self.scope_label())


def merge_params(lists, writable_only=False):
    """What several families have in common, by key. One list is just itself."""
    if not lists:
        return []
    first = lists[0]
    common = None
    for items in lists:
        keys = set([p.key for p in items
                    if p.writable or not writable_only])
        common = keys if common is None else (common & keys)
    return sorted([p for p in first if p.key in common],
                  key=lambda p: natural_key(p.name))


def filter_params(params, query):
    words = words_of(query)
    return [p for p in params if matches(
        words, u'{0} {1} {2} {3}'.format(p.name, p.kind(), p.scope_label(),
                                         p.origin()))]


def param_rows(params):
    return [{'key': p.key, 'name': p.name, 'scope': p.scope_label(),
             'kind': p.kind(), 'origin': p.origin(), 'sample': p.sample}
            for p in params]


def conversion(src, tgt):
    """(allowed, words for the table)."""
    if src.storage == tgt.storage:
        if src.storage == u'Double' and src.spec != tgt.spec:
            return True, u'Number, by display value'
        return True, u'Direct'
    if tgt.storage == u'String':
        return True, u'To text'
    if src.storage == u'ElementId' or tgt.storage == u'ElementId':
        return False, u'An element only goes into an element or text'
    if src.storage == u'String':
        return True, u'Text to number'
    return True, u'Number to number'


def flow_note(src, tgt):
    if src.scope == 'I' and tgt.scope == 'T':
        return u'Instance to type: elements must agree'
    if src.scope == 'T' and tgt.scope == 'I':
        return u'Type to every instance'
    return u''


class Mapping(object):
    def __init__(self, src, tgt):
        self.src = src
        self.tgt = tgt
        self.key = u'{0}>{1}'.format(src.key, tgt.key)


class Pick(object):
    def __init__(self, fam):
        self.fam = fam
        self.type_ids = set()
        self.mappings = []
        self.params = None

    def ready(self):
        return bool(self.type_ids) and bool(self.mappings)


class Picks(object):
    """What has been pushed to the right, and the mappings on it."""
    def __init__(self):
        self.items = {}
        self.order = []
        self.type_owner = {}

    def ordered(self):
        return [self.items[k] for k in self.order]

    def has_type(self, idv):
        return idv in self.type_owner

    def add(self, fam, type_ids):
        pick = self.items.get(fam.key)
        if pick is None:
            pick = Pick(fam)
            self.items[fam.key] = pick
            self.order.append(fam.key)
        before = len(pick.type_ids)
        for idv in type_ids:
            pick.type_ids.add(idv)
            self.type_owner[idv] = fam.key
        if len(pick.type_ids) != before:
            pick.params = None
        return pick

    def drop_family(self, fkey):
        pick = self.items.pop(fkey, None)
        if pick is None:
            return
        self.order.remove(fkey)
        for idv in pick.type_ids:
            self.type_owner.pop(idv, None)

    def drop_type(self, idv):
        fkey = self.type_owner.pop(idv, None)
        if fkey is None:
            return
        pick = self.items[fkey]
        pick.type_ids.discard(idv)
        pick.params = None
        if not pick.type_ids:
            self.drop_family(fkey)

    def remove_keys(self, keys):
        for key in keys:
            if key.startswith(u'f:'):
                self.drop_family(key[2:])
        for key in keys:
            if key.startswith(u't:'):
                self.drop_type(int(key[2:]))

    def family_keys_of(self, keys):
        out = []
        for key in keys:
            fkey = key[2:] if key.startswith(u'f:') \
                else self.type_owner.get(int(key[2:]))
            if fkey in self.items and fkey not in out:
                out.append(fkey)
        return out

    def add_mapping(self, fkeys, src, tgt):
        """Returns (added, refusal text). One source per target parameter."""
        if src.key == tgt.key:
            return 0, u'A parameter cannot push to itself.'
        allowed, words = conversion(src, tgt)
        if not allowed:
            return 0, words + u'.'
        added = 0
        clashes = []
        for fkey in fkeys:
            pick = self.items[fkey]
            if [m for m in pick.mappings if m.tgt.key == tgt.key]:
                clashes.append(pick.fam.name)
                continue
            pick.mappings.append(Mapping(src, tgt))
            added += 1
        if clashes:
            return added, u'{0} already feeds from another mapping on: {1}' \
                .format(tgt.name, u', '.join(clashes))
        return added, u''

    def remove_mappings(self, fkeys, keys):
        for fkey in fkeys:
            pick = self.items[fkey]
            pick.mappings = [m for m in pick.mappings if m.key not in keys]

    def mapping_rows(self, fkeys):
        seen = {}
        order = []
        for fkey in fkeys:
            for mapping in self.items[fkey].mappings:
                if mapping.key not in seen:
                    seen[mapping.key] = [mapping, 0]
                    order.append(mapping.key)
                seen[mapping.key][1] += 1
        out = []
        for key in order:
            mapping, count = seen[key]
            note = conversion(mapping.src, mapping.tgt)[1]
            flow = flow_note(mapping.src, mapping.tgt)
            out.append({'key': key, 'source': mapping.src.label(),
                        'target': mapping.tgt.label(),
                        'how': u'{0}. {1}'.format(note, flow) if flow else note,
                        'count': to_text(count)})
        return out

    def ready(self):
        return [p for p in self.ordered() if p.ready()]

    def mapping_count(self):
        return sum([len(p.mappings) for p in self.ready()])

    def unmapped(self):
        return [p.fam.name for p in self.ordered() if not p.mappings]

    def sync(self, families):
        """After a reload: rebind to the fresh records, drop what has gone."""
        lookup = dict([(f.key, f) for f in families])
        for fkey in list(self.order):
            fresh = lookup.get(fkey)
            pick = self.items[fkey]
            if fresh is None:
                self.drop_family(fkey)
                continue
            live = set([t.idv for t in fresh.types])
            for idv in list(pick.type_ids):
                if idv not in live:
                    self.drop_type(idv)
            if fkey in self.items:
                pick.fam = fresh
                pick.params = None


# ===================== saved mapping sets =====================

_BAD_NAME = re.compile(r'[\\/:*?"<>|\t\r\n]')


def sets_dir():
    return os.path.join(appdata_dir(), 'family_param_push_mappings')


def safe_name(name):
    """What a set is called is its file name, so it must be a legal one."""
    return _BAD_NAME.sub(u'_', to_text(name)).strip().strip(u'.').strip()


def set_path(name, folder=None):
    return os.path.join(folder or sets_dir(), safe_name(name) + u'.txt')


def list_sets(folder=None):
    folder = to_text(folder or sets_dir())
    try:
        names = os.listdir(folder)
    except Exception:
        return []
    return sorted([to_text(n)[:-4] for n in names
                   if to_text(n).lower().endswith(u'.txt')], key=natural_key)


def set_text(picks):
    """Names and parameter keys only: an element id means nothing outside
    the model it came from, so a set can travel to another project."""
    lines = [u'version=1']
    for pick in picks.ordered():
        if not pick.mappings:
            continue
        lines.append(u'family=' + pick.fam.key)
        for typ in pick.fam.types:
            if typ.idv in pick.type_ids:
                lines.append(u'type=' + typ.name)
        for mapping in pick.mappings:
            lines.append(u'map={0}\t{1}'.format(mapping.src.key,
                                                mapping.tgt.key))
    return u'\n'.join(lines)


def parse_set(text):
    """A damaged line is skipped, never fatal."""
    entries = []
    current = None
    for line in to_text(text).splitlines():
        if u'=' not in line:
            continue
        key, value = line.split(u'=', 1)
        if key == u'family':
            current = {'fkey': value, 'types': [], 'maps': []}
            entries.append(current)
        elif current is None:
            continue
        elif key == u'type':
            current['types'].append(value)
        elif key == u'map' and value.count(u'\t') == 1:
            current['maps'].append(tuple(value.split(u'\t')))
    return entries


def key_name(key):
    parts = to_text(key).split(u'|')
    return parts[1] if len(parts) > 1 else to_text(key)


def apply_set_picks(picks, families, entries):
    """First half of a load: put the families on the right. Returns
    (loaded [(entry, pick)], lines saying what this model does not have)."""
    lookup = dict([(f.key, f) for f in families])
    loaded, missing = [], []
    for entry in entries:
        fam = lookup.get(entry['fkey'])
        if fam is None:
            missing.append(u'Family not in this model: {0}'
                           .format(entry['fkey'].split(u'|')[-1]))
            continue
        names = dict([(t.name, t.idv) for t in fam.types])
        ids = [names[n] for n in entry['types'] if n in names]
        for name in entry['types']:
            if name not in names:
                missing.append(u'Type not in this model: {0} : {1}'
                               .format(fam.name, name))
        if ids:
            loaded.append((entry, picks.add(fam, ids)))
    return loaded, missing


def bind_set(picks, loaded):
    """Second half, once parameters are read: rebuild the mappings. Returns
    (mappings added, lines saying what could not be)."""
    added, missing = 0, []
    for entry, pick in loaded:
        params = dict([(p.key, p) for p in pick.params or []])
        have = [m.key for m in pick.mappings]
        for src_key, tgt_key in entry['maps']:
            src, tgt = params.get(src_key), params.get(tgt_key)
            if src is None or tgt is None or not tgt.writable:
                missing.append(u'{0}: parameter not available: {1}'.format(
                    pick.fam.name,
                    key_name(tgt_key if src is not None else src_key)))
                continue
            if Mapping(src, tgt).key in have:
                continue
            count, refusal = picks.add_mapping([pick.fam.key], src, tgt)
            added += count
            if refusal:
                missing.append(u'{0}: {1}'.format(pick.fam.name, refusal))
    return added, missing


# ===================== replace with shared parameters =====================

def spec_base(spec):
    """Revit versions its type ids: length-1.0.0 and length-2.0.0 match."""
    return re.sub(r'-\d+\.\d+\.\d+$', u'', to_text(spec))


def spec_label(spec):
    tail = re.split(r'[:.]', spec_base(spec))[-1]
    words = {u'text': u'Text', u'bool': u'Yes/No', u'int': u'Integer',
             u'number': u'Number', u'': u'Other'}
    return words.get(tail, tail[:1].upper() + tail[1:])


class SharedRef(object):
    def __init__(self, name, group, spec, guid):
        self.name = to_text(name)
        self.group = to_text(group)
        self.spec = to_text(spec)
        self.guid = to_text(guid).lower()
        self.key = self.guid


class ReplaceMap(object):
    def __init__(self, src, tgt):
        self.src = src
        self.tgt = tgt
        self.key = u'{0}>{1}'.format(src.key, tgt.key)


class ReplacePick(object):
    def __init__(self, fam):
        self.fam = fam
        self.params = None
        self.maps = []

    @property
    def type_ids(self):
        """A parameter belongs to the family, so a swap covers every type."""
        return set([t.idv for t in self.fam.types])


def replace_problem(pick, src, tgt):
    """Why this swap cannot go ahead, in words, or empty if it can."""
    if spec_base(src.spec) != spec_base(tgt.spec):
        return u'{0} is {1} but {2} is {3}.'.format(
            src.name, spec_label(src.spec), tgt.name, spec_label(tgt.spec))
    if src.guid and src.guid.lower() == tgt.guid:
        return u'{0} is already that shared parameter.'.format(src.name)
    for mapping in pick.maps:
        if mapping.src.key == src.key:
            return u'{0} is already mapped on {1}.'.format(src.name,
                                                          pick.fam.name)
        if mapping.tgt.key == tgt.key:
            return u'{0} is already the target of another mapping on {1}.' \
                .format(tgt.name, pick.fam.name)
    for param in pick.params or []:
        if param.key == src.key:
            continue
        if param.guid and param.guid.lower() == tgt.guid:
            return u'{0} already has {1}.'.format(pick.fam.name, tgt.name)
        if param.name == tgt.name:
            return u'{0} already has a parameter called {1}.'.format(
                pick.fam.name, tgt.name)
    return u''


class ReplacePicks(object):
    def __init__(self):
        self.items = {}
        self.order = []

    def ordered(self):
        return [self.items[k] for k in self.order]

    def add(self, fam):
        if fam.key not in self.items:
            self.items[fam.key] = ReplacePick(fam)
            self.order.append(fam.key)

    def remove(self, fkeys):
        for fkey in fkeys:
            if fkey in self.items:
                del self.items[fkey]
                self.order.remove(fkey)

    def add_mapping(self, fkeys, src, tgt):
        added, refusals = 0, []
        for fkey in fkeys:
            pick = self.items[fkey]
            problem = replace_problem(pick, src, tgt)
            if problem:
                refusals.append(problem)
                continue
            pick.maps.append(ReplaceMap(src, tgt))
            added += 1
        return added, u' '.join(refusals)

    def remove_mappings(self, fkeys, keys):
        for fkey in fkeys:
            pick = self.items[fkey]
            pick.maps = [m for m in pick.maps if m.key not in keys]

    def ready(self):
        return [p for p in self.ordered() if p.maps]

    def mapping_count(self):
        return sum([len(p.maps) for p in self.ordered()])

    def rows(self):
        out = []
        for pick in self.ordered():
            count = len(pick.maps)
            note = u'{0} mapping{1}'.format(count, u'' if count == 1 else u's') \
                if count else u'No mapping yet'
            out.append(row(u'f:' + pick.fam.key, u'n', pick.fam.name,
                           pick.fam.category, pick.fam.placed(), u'0', u'0',
                           note))
        return out

    def mapping_rows(self, fkeys):
        seen = {}
        order = []
        for fkey in fkeys:
            for mapping in self.items[fkey].maps:
                if mapping.key not in seen:
                    seen[mapping.key] = [mapping, 0]
                    order.append(mapping.key)
                seen[mapping.key][1] += 1
        out = []
        for key in order:
            mapping, count = seen[key]
            how = u'Keeps every placed value' if mapping.src.scope == 'I' \
                else u'Keeps every type value'
            if mapping.src.locked:
                how = u'Driven in the family, nothing to keep'
            out.append({'key': key, 'source': mapping.src.label(),
                        'target': mapping.tgt.name, 'how': how,
                        'count': to_text(count)})
        return out

    def sync(self, families):
        lookup = dict([(f.key, f) for f in families])
        for fkey in list(self.order):
            fresh = lookup.get(fkey)
            if fresh is None or not fresh.editable:
                self.remove([fkey])
            else:
                self.items[fkey].fam = fresh
                self.items[fkey].params = None


def editable_rows(families, category, query, picks):
    words = words_of(query)
    out = []
    for fam in families:
        if not fam.editable:
            continue
        if category and category != ALL_CATEGORIES \
                and fam.category != category:
            continue
        if matches(words, u'{0} {1}'.format(fam.name, fam.category)):
            out.append(row(u'f:' + fam.key, u'n', fam.name, fam.category,
                           fam.placed(), u'0',
                           u'1' if fam.key in picks.items else u'0'))
    return out


def source_rows(params, query):
    words = words_of(query)
    out = []
    for param in params:
        if matches(words, u'{0} {1} {2}'.format(
                param.name, spec_label(param.spec), param.scope_label())):
            out.append({'key': param.key, 'name': param.name,
                        'scope': param.scope_label(),
                        'kind': spec_label(param.spec),
                        'origin': param.origin(), 'sample': param.sample})
    return out


def shared_rows(shared, query):
    words = words_of(query)
    out = []
    for ref in shared:
        if matches(words, u'{0} {1} {2}'.format(ref.name, ref.group,
                                                spec_label(ref.spec))):
            out.append({'key': ref.key, 'name': ref.name, 'scope': ref.group,
                        'kind': spec_label(ref.spec), 'origin': u'',
                        'sample': u''})
    return out


def new_replace_report():
    rep = new_report()
    rep.update({'done': [], 'failed': [], 'backups': [], 'swapped': 0})
    return rep


def replace_problem_lines(rep):
    lines = [u'Not replaced: ' + line for line in rep['failed']]
    lines += problem_lines(rep)
    if lines and rep['backups']:
        lines.append(u'Original values saved in: ' + u', '.join(rep['backups']))
    return lines


def replace_status(rep):
    return (u'{0} famil{1} replaced, {2} parameter{3} swapped, {4} value{5} '
            u'restored on {6} element{7}.').format(
        len(rep['done']), u'y' if len(rep['done']) == 1 else u'ies',
        rep['swapped'], u'' if rep['swapped'] == 1 else u's', rep['written'],
        u'' if rep['written'] == 1 else u's', rep['elements'],
        u'' if rep['elements'] == 1 else u's')


# ===================== values =====================

_NUMBER = re.compile(r'^\s*([-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|'
                     r'[-+]?\.\d+)')


class Value(object):
    def __init__(self, storage, raw=None, text=u'', empty=False):
        self.storage = to_text(storage)
        self.raw = raw
        self.text = to_text(text)
        self.empty = empty


def leading_number(text):
    match = _NUMBER.match(to_text(text))
    if match is None:
        return None
    return float(match.group(1).replace(u',', u''))


def plain_number(value):
    if value == int(value):
        return to_text(int(value))
    return to_text(repr(value))


def number_candidates(src):
    """What to hand SetValueString: the display text, then the bare number,
    because a Number parameter may refuse '1000 mm'."""
    if src.storage == u'Integer':
        return [to_text(src.raw)]
    out = []
    text = src.text.strip()
    if text:
        out.append(text)
    number = leading_number(text)
    if number is not None and plain_number(number) not in out:
        out.append(plain_number(number))
    return out


def parse_integer(src):
    if src.storage == u'Double':
        number = leading_number(src.text)
        if number is None or number != int(number):
            return None
        return int(number)
    low = src.text.strip().lower()
    if low in (u'yes', u'true', u'y'):
        return 1
    if low in (u'no', u'false', u'n'):
        return 0
    number = leading_number(low)
    if number is None or number != int(number):
        return None
    return int(number)


def plan_value(src, tgt_storage, same_spec, clear_empty):
    """(mode, value). Mode is set, text, empty or refused."""
    tgt_storage = to_text(tgt_storage)
    if src.empty:
        if clear_empty and tgt_storage == u'String':
            return u'set', u''
        return u'empty', None
    if src.storage == tgt_storage:
        if src.storage == u'Double' and not same_spec:
            return u'text', number_candidates(src)
        return u'set', src.raw
    if tgt_storage == u'String':
        return u'set', src.text
    if src.storage == u'ElementId' or tgt_storage == u'ElementId':
        return u'refused', u'an element only goes into an element or text'
    if tgt_storage == u'Integer':
        number = parse_integer(src)
        if number is None:
            return u'refused', u'"{0}" is not a whole number'.format(src.text)
        return u'set', number
    if tgt_storage == u'Double':
        candidates = number_candidates(src)
        if src.storage == u'String' and leading_number(src.text) is None:
            return u'refused', u'"{0}" is not a number'.format(src.text)
        return u'text', candidates
    return u'refused', u'nothing can be written to this parameter'


def holds(current, mode, value, id_value=None):
    """Does the target already say this? Used before writing and to prove a
    write. Never trust the void call: the read-back is the evidence."""
    if current is None:
        return False
    if mode == u'text':
        for candidate in value:
            if current.text == candidate:
                return True
        have = leading_number(current.text)
        want = leading_number(value[0]) if value else None
        if have is None or want is None:
            return False
        return abs(have - want) <= 1e-6 * max(1.0, abs(want))
    if current.storage == u'String':
        return (current.raw or u'') == (value or u'')
    if current.storage == u'Double':
        if current.raw is None or value is None:
            return False                # an unset number: float(None) is a
        try:                            # SystemError in IronPython
            return abs(float(current.raw) - float(value)) < 1e-9
        except (TypeError, ValueError):
            return False
    if current.storage == u'ElementId':
        if id_value is None:
            return False
        return id_value(current.raw) == id_value(value)
    return current.raw == value


# ===================== plan and report =====================

class Write(object):
    def __init__(self, eid, idv, ref, mode, value, label, already):
        self.eid = eid
        self.idv = idv
        self.ref = ref
        self.mode = mode
        self.value = value
        self.label = label
        self.already = already
        self.refused = False


class Plan(object):
    """Two writes putting different values in one parameter on one element
    (instance values into a shared type parameter): the first stays."""
    def __init__(self):
        self.writes = {}
        self.order = []

    def add(self, write):
        key = (write.idv, write.ref.key)
        have = self.writes.get(key)
        if have is None:
            self.writes[key] = write
            self.order.append(key)
            return u'new'
        if have.mode == write.mode and have.value == write.value:
            return u'same'
        return u'conflict'

    def pending(self):
        return [self.writes[k] for k in self.order
                if not self.writes[k].already]

    def already(self):
        return len([k for k in self.order if self.writes[k].already])


def new_report():
    return {'written': 0, 'elements': 0, 'already': 0, 'empty': 0,
            'no_elements': [], 'no_source': {}, 'no_target': {},
            'read_only': {}, 'refused': [], 'conflicts': [], 'held': []}


def tally(bucket, key):
    bucket[key] = bucket.get(key, 0) + 1


def problem_lines(rep):
    lines = []
    for name, count in sorted(rep['no_source'].items()):
        lines.append(u'Source parameter not on {0} element(s): {1}'
                     .format(count, name))
    for name, count in sorted(rep['no_target'].items()):
        lines.append(u'Target parameter not on {0} element(s): {1}'
                     .format(count, name))
    for name, count in sorted(rep['read_only'].items()):
        lines.append(u'Read only on {0} element(s): {1}'.format(count, name))
    for line in rep['no_elements']:
        lines.append(u'Nothing placed: ' + line)
    for line in rep['held']:
        lines.append(u'Held by someone else: ' + line)
    for line in rep['conflicts']:
        lines.append(u'Conflict: ' + line)
    for line in rep['refused']:
        lines.append(u'Refused: ' + line)
    return lines


def status_line(rep):
    text = u'{0} value{1} written on {2} element{3}, {4} already up to date' \
        .format(rep['written'], u'' if rep['written'] == 1 else u's',
                rep['elements'], u'' if rep['elements'] == 1 else u's',
                rep['already'])
    if rep['empty']:
        text += u', {0} empty source{1} skipped'.format(
            rep['empty'], u'' if rep['empty'] == 1 else u's')
    return text + u'.'
