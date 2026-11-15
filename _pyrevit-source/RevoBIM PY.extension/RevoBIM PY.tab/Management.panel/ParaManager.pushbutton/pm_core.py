# -*- coding: utf-8 -*-
"""Pure rules for ParaManager. No WPF and no Revit in here, so the bench can run it."""
import codecs
import os
import re

KIND_SHARED = u'Shared Parameter'
KIND_PROJECT = u'Project Parameter'
KIND_ALL = u'All'
INSTANCE = u'Instance'
TYPE = u'Type'

ILLEGAL_NAME = u'\\:{}[]|;<>?`~'

SETTINGS_VERSION = 1
MIGRATIONS = {}
DEFAULTS = {
    'settings_version': str(SETTINGS_VERSION),
    'theme': 'follow',
    'debug': '1',
    'open_note': '',
    'width': '1290',
    'height': '640',
    'last_sp_folder': '',
}


def to_text(value):
    if value is None:
        return u''
    try:
        return value if isinstance(value, type(u'')) else u'{0}'.format(value)
    except Exception:
        return u''


def data_root():
    return os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'RevoBIM')


def settings_path(root=None):
    return os.path.join(root or data_root(), 'para_manager.txt')


def groups_path(root=None):
    return os.path.join(root or data_root(), 'para_manager_category_groups.txt')


def debug_path(root=None):
    return os.path.join(root or data_root(), 'para_manager_debug.txt')


def _read(path):
    with codecs.open(path, 'r', 'utf-8') as src:
        return src.read()


def _write(path, text):
    folder = os.path.dirname(path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)
    with codecs.open(path, 'w', 'utf-8') as out:
        out.write(text)


def load_settings(path):
    out = dict(DEFAULTS)
    try:
        lines = _read(path).splitlines()
    except Exception:
        return out
    stored = {}
    for line in lines:
        if '=' in line:
            key, value = line.split('=', 1)
            stored[key.strip()] = value
    for key in out:
        if key in stored:
            out[key] = stored[key]
    try:
        found = int(stored.get('settings_version', '0'))
    except Exception:
        found = 0
    for version in sorted(MIGRATIONS):
        if found < version:
            for key, value in MIGRATIONS[version].items():
                out[key] = value
    out['settings_version'] = str(SETTINGS_VERSION)
    return out


def save_settings(path, settings):
    _write(path, u'\n'.join(u'{0}={1}'.format(k, settings[k]) for k in sorted(settings)) + u'\n')


def log(message, settings=None, path=None):
    if settings is not None and settings.get('debug') != '1':
        return
    try:
        with codecs.open(path or debug_path(), 'a', 'utf-8') as out:
            out.write(to_text(message) + u'\n')
    except Exception:
        pass


# ---- saved category groups: one group a line, name then categories, tab separated

def load_category_groups(path):
    groups = {}
    try:
        lines = _read(path).splitlines()
    except Exception:
        return groups
    for line in lines:
        parts = line.split(u'\t')
        if parts[0].strip():
            groups[parts[0].strip()] = [p for p in parts[1:] if p]
    return groups


def save_category_groups(path, groups):
    lines = []
    for name in sorted(groups):
        lines.append(u'\t'.join([name] + sorted(groups[name])))
    _write(path, u'\n'.join(lines) + u'\n')


# ---- categories

_DISCIPLINE_RULES = (
    (u'Infrastructure', (u'abutment', u'approach slab', u'bearing', u'bridge', u'pier',
                         u'expansion joint', u'vibration')),
    (u'Mechanical', (u'air ', u'duct', u'hvac', u'mechanical', u'mep ancillary',
                     u'mep fabrication hanger', u'zone')),
    (u'Piping', (u'pipe', u'piping', u'plumbing', u'sprinkler')),
    (u'Electrical', (u'cable tray', u'conduit', u'communication', u'data device',
                     u'electrical', u'fire alarm', u'lighting', u'nurse call',
                     u'security', u'switch system', u'telephone', u'wire', u'panel schedule')),
    (u'Structure', (u'analytical link', u'analytical node', u'analytical opening',
                    u'analytical panel', u'analytical surface', u'analytical pipe',
                    u'structural', u'rebar', u'foundation', u'fabric', u'reinforcement')),
    (u'General', (u'alignment', u'analytical member', u'detail item', u'generic',
                  u'grid', u'level', u'line', u'mass', u'project info', u'rvt link',
                  u'scope box', u'sheet', u'view', u'title block', u'tag', u'site',
                  u'revision', u'schedule')),
)


def category_discipline(label):
    """Revit does not expose the discipline column of its own dialogs, so it comes from the name."""
    text = to_text(label).lower() + u' '
    for discipline, words in _DISCIPLINE_RULES:
        for word in words:
            if word in text:
                return discipline
    return u'Architecture'


def join_categories(cats):
    return u', '.join(sorted(cats, key=lambda c: c.lower()))


def apply_category_choice(current, ticked, cleared):
    """ticked are added, cleared are removed, anything else stays as it was on that parameter."""
    return (set(current) - set(cleared)) | set(ticked)


def shared_state(all_sets):
    """For the parameters being edited: (in every one, in only some)."""
    sets = [set(s) for s in all_sets]
    if not sets:
        return set(), set()
    every = set(sets[0])
    some = set(sets[0])
    for item in sets[1:]:
        every &= item
        some |= item
    return every, some - every


# ---- parameter records

class Rec(object):
    """One parameter row. source: '' in the model, 'typed' new by hand, 'file' from a shared file."""

    def __init__(self, rid, name, kind, disc, ptype, group, scope, cats,
                 guid=u'', source=u'', sp_path=u'', handle=None):
        self.rid = rid
        self.name = name
        self.kind = kind
        self.disc = disc
        self.ptype = ptype
        self.group = group
        self.scope = scope
        self.cats = set(cats)
        self.guid = guid
        self.source = source
        self.sp_path = sp_path
        self.handle = handle
        self.tick = False
        self.deleted = False
        self.orig = (group, scope, set(cats))

    @property
    def is_new(self):
        return self.source != u''

    @property
    def free(self):
        return self.source == u'typed'

    def state(self):
        if self.deleted:
            return 'del'
        if self.is_new:
            return 'new'
        return 'mod' if self.changed() else 'ok'

    def changed(self):
        return (self.group, self.scope, self.cats) != self.orig

    def needs_rebind(self):
        return self.scope != self.orig[1] or self.cats != self.orig[2]

    def group_changed(self):
        return self.group != self.orig[0]


def build_plan(recs):
    plan = {'delete': [], 'create': [], 'modify': []}
    for rec in recs:
        state = rec.state()
        if state == 'del':
            plan['delete'].append(rec)
        elif state == 'new':
            plan['create'].append(rec)
        elif state == 'mod':
            plan['modify'].append(rec)
    return plan


def validate_plan(recs):
    errors = []
    names = {}
    for rec in recs:
        if not rec.deleted:
            key = to_text(rec.name).strip().lower()
            names[key] = names.get(key, 0) + 1
    for rec in recs:
        state = rec.state()
        if state in ('ok', 'del'):
            continue
        label = rec.name or u'(no name)'
        if state == 'new':
            bad = name_problem(rec.name)
            if bad:
                errors.append(u'{0}: {1}'.format(label, bad))
            elif names.get(rec.name.strip().lower(), 0) > 1:
                errors.append(u'{0}: that name is already in the list'.format(label))
            if not rec.ptype:
                errors.append(u'{0}: pick a type of parameter'.format(label))
        if not rec.cats:
            errors.append(u'{0}: needs at least one category'.format(label))
    return errors


def name_problem(name):
    text = to_text(name)
    if not text.strip():
        return u'the name is empty'
    for ch in ILLEGAL_NAME:
        if ch in text:
            return u'the name cannot contain {0}'.format(ch)
    return u''


def plan_lines(plan):
    lines = []
    if plan['create']:
        lines.append(u'Create {0} parameter(s)'.format(len(plan['create'])))
    if plan['modify']:
        lines.append(u'Change {0} parameter(s)'.format(len(plan['modify'])))
    moved = [r for r in plan['modify'] if r.scope != r.orig[1]]
    if moved:
        lines.append(u'{0} switch between Instance and Type: values on elements '
                     u'can be lost'.format(len(moved)))
    if plan['delete']:
        lines.append(u'DELETE {0} parameter(s): their values go from every '
                     u'element'.format(len(plan['delete'])))
    return lines


def status_line(recs):
    create = modify = existing = 0
    for rec in recs:
        state = rec.state()
        if state == 'new':
            create += 1
        elif state in ('mod', 'del'):
            modify += 1
        if not rec.is_new:
            existing += 1
    return u'Total number of parameters {0} | create {1} | modify {2} | existing {3}'.format(
        len(recs), create, modify, existing)


def next_free_name(taken, stem=u'Parameter'):
    used = set(to_text(t).lower() for t in taken)
    number = 1
    while True:
        name = u'{0} {1:03d}'.format(stem, number)
        if name.lower() not in used:
            return name
        number += 1


def rec_visible(rec, kind, search, show_existing):
    if not show_existing and not rec.is_new:
        return False
    if kind != KIND_ALL and rec.kind != kind:
        return False
    return words_match(search, [rec.name, rec.kind, rec.ptype, rec.group, rec.scope,
                                join_categories(rec.cats)])


def words_match(search, fields):
    text = u' '.join(to_text(f) for f in fields).lower()
    for word in to_text(search).lower().split():
        if word not in text:
            return False
    return True


def natural_key(value):
    out = []
    for piece in re.split(r'(\d+)', to_text(value).lower()):
        out.append((0, int(piece), u'') if piece.isdigit() else (1, 0, piece))
    return out


def sort_ranks(items, value_of, descending, is_new):
    """{item index: rank}. New rows stay at the bottom whichever way the rest are sorted."""
    order = list(range(len(items)))
    order.sort(key=lambda i: natural_key(value_of(items[i])), reverse=descending)
    order.sort(key=lambda i: 1 if is_new(items[i]) else 0)
    return dict((index, rank) for rank, index in enumerate(order))


def rename_preview(name, find, replace, prefix, suffix):
    out = to_text(name)
    if find:
        out = out.replace(find, replace)
    return to_text(prefix) + out + to_text(suffix)


# ---- Excel round trip

EXPORT_HEADINGS = [u'Parameter Name', u'Parameter Kind', u'Discipline', u'Type of Parameter',
                   u'Group Under', u'Instance/Type', u'Categories']
CAT_SEPARATOR = u'; '


def export_rows(recs):
    rows = [list(EXPORT_HEADINGS)]
    for rec in recs:
        if not rec.deleted:
            rows.append([rec.name, rec.kind, rec.disc, rec.ptype, rec.group, rec.scope,
                         CAT_SEPARATOR.join(sorted(rec.cats))])
    return rows


def plan_import(rows, recs, groups, categories):
    """Stage group, instance/type and categories by name. Returns (changes, notes)."""
    notes = []
    changes = []
    if not rows or [to_text(c).strip() for c in rows[0][:7]] != EXPORT_HEADINGS:
        return changes, [u'The first row does not match the ParaManager export headings.']
    by_name = dict((r.name, r) for r in recs if not r.deleted)
    known_groups = set(groups)
    known_cats = set(categories)
    for row in rows[1:]:
        cells = [to_text(c).strip() for c in (list(row) + [u''] * 7)[:7]]
        if not cells[0]:
            continue
        rec = by_name.get(cells[0])
        if rec is None:
            notes.append(u'{0}: not in this project, skipped'.format(cells[0]))
            continue
        group = cells[4]
        if group not in known_groups:
            notes.append(u'{0}: group "{1}" not recognised, left as it was'.format(cells[0], group))
            group = rec.group
        scope = cells[5]
        if scope not in (INSTANCE, TYPE):
            notes.append(u'{0}: "{1}" is not Instance or Type, left as it was'.format(cells[0], scope))
            scope = rec.scope
        cats = set(c.strip() for c in cells[6].split(u';') if c.strip())
        unknown = sorted(cats - known_cats)
        if unknown:
            notes.append(u'{0}: categories not recognised, ignored: {1}'.format(
                cells[0], u', '.join(unknown)))
            cats -= set(unknown)
        if not cats:
            notes.append(u'{0}: no usable categories, left as they were'.format(cells[0]))
            cats = set(rec.cats)
        if group != rec.group or scope != rec.scope or cats != rec.cats:
            changes.append((rec, group, scope, cats))
    return changes, notes


# ---- window maths

DRAWER_SECONDS = 0.28
DRAWER_TICK_MS = 15
BAR_GAP = 8.0
BAR_STACK = 4.0


def ease_out(progress):
    p = max(0.0, min(1.0, progress))
    return 1.0 - (1.0 - p) ** 3


def parked_top(work_bottom, bar_height, slot=0):
    return work_bottom - BAR_GAP - (bar_height + BAR_STACK) * slot - bar_height


def reopen_top(saved_top, bar_top, parked_at, full_height, work_top, work_bottom):
    """Back where it was, or upward from the bar if the bar has been carried elsewhere."""
    if abs(bar_top - parked_at) <= 2.0:
        return saved_top
    top = bar_top - full_height
    return max(work_top, min(top, work_bottom - full_height))


def resolve_theme(setting, canvas_dark):
    if setting == 'dark':
        return 'dark'
    if setting == 'light':
        return 'light'
    return 'dark' if canvas_dark else 'light'


def next_theme(setting):
    return {'follow': 'dark', 'dark': 'light'}.get(setting, 'follow')


def theme_label(setting):
    return {'follow': u'Auto', 'dark': u'Dark', 'light': u'Light'}.get(setting, u'Auto')


def compose_layout(layout, header, title):
    return layout.replace('@@HEADER@@', header).replace('@@TITLE@@', title)
