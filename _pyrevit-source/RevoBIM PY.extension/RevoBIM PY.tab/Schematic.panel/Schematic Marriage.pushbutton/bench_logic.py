# -*- coding: utf-8 -*-
"""Schematic Marriage - logic bench. Plain CPython, no Revit:

    python bench_logic.py              run every case
    python bench_logic.py --selftest   break the logic on purpose, prove the cases notice

Covers sm_store: record round trips, templates, duplicate / merge, which
templates suit a marriage, value conversion, conflicts, the library file
and settings.
"""
from __future__ import print_function

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import sm_store as store  # noqa: E402

CASES = []


def case(fn):
    CASES.append(fn)
    return fn


def tpl(name, src=u'-2008044', tgt=u'-2002000', maps=()):
    t = store.Template()
    t.name = name
    t.src_cat_id, t.src_cat_name = src, u'Pipes'
    t.tgt_cat_id, t.tgt_cat_name = tgt, u'Detail Items'
    for s, d in maps:
        t.mappings.append(store.Mapping(s, d, u'instance', u'String', u'String'))
    return t


def mar(src=u'-2008044', tgt=u'-2002000', tid=u''):
    m = store.Marriage()
    m.src_uid, m.tgt_uid = store.new_id(), store.new_id()
    m.src_cat_id, m.tgt_cat_id = src, tgt
    m.template_id = tid
    return m


# ==========================================================================
# records
# ==========================================================================

@case
def escape_round_trip():
    for text in [u'', u'plain', u'tab\there', u'line\nbreak', u'back\\slash', u'a=b=c',
                 u'\\t literal', u'end\\', u'· unicode ✓', u'\r\n mixed']:
        assert store.unescape(store.escape(text)) == text, repr(text)
        assert u'\n' not in store.escape(text) and u'\t' not in store.escape(text)


@case
def parse_splits_on_first_equals_and_skips_damage():
    pairs = store.parse(u'a=1\nbroken line\n=nokey\nb=x=y\n\nmap=1\nmap=2')
    assert pairs == [(u'a', u'1'), (u'b', u'x=y'), (u'map', u'1'), (u'map', u'2')], pairs


@case
def marriage_round_trip():
    m = mar(tid=u'abc')
    m.src_cat_name, m.tgt_cat_name = u'Pipe Accessories', u'Detail Items'
    back = store.Marriage.from_text(m.to_text())
    for attr in ('id', 'src_uid', 'tgt_uid', 'src_cat_id', 'src_cat_name', 'tgt_cat_id',
                 'tgt_cat_name', 'template_id', 'created'):
        assert getattr(back, attr) == getattr(m, attr), attr


@case
def template_round_trip_keeps_mappings_with_awkward_names():
    t = tpl(u'Valves = tags\tv2', maps=[(u'BGL_Size', u'Size\tLabel'), (u'Mark', u'Tag\\No')])
    t.mappings[1].tgt_scope = u'type'
    t.mappings[1].src_storage, t.mappings[1].tgt_storage = u'Double', u'String'
    t.clear_empty = True
    back = store.Template.from_text(t.to_text())
    assert back.name == t.name and back.clear_empty
    assert [(m.src_name, m.tgt_name, m.tgt_scope, m.src_storage, m.tgt_storage) for m in back.mappings] == \
        [(m.src_name, m.tgt_name, m.tgt_scope, m.src_storage, m.tgt_storage) for m in t.mappings]


@case
def ids_are_unique():
    ids = set(store.new_id() for _ in range(2000))
    assert len(ids) == 2000


# ==========================================================================
# templates
# ==========================================================================

@case
def usage_counts_and_apply():
    a, b = tpl(u'A'), tpl(u'B')
    ms = [mar(tid=a.id), mar(tid=a.id), mar(tid=b.id), mar()]
    store.apply_usage([a, b], ms)
    assert (a.used, b.used) == (2, 1)


@case
def compatible_only_for_matching_categories():
    a = tpl(u'A')
    b = tpl(u'B', tgt=u'-2008055')
    c = tpl(u'C')
    got = store.compatible_templates([c, b, a], [mar()])
    assert [t.name for t in got] == [u'A', u'C'], [t.name for t in got]
    assert store.compatible_templates([a], [mar(), mar(tgt=u'-2008055')]) == []
    assert store.compatible_templates([a], []) == []


@case
def unique_names():
    assert store.unique_name(u'X', []) == u'X'
    assert store.unique_name(u'X', [u'x']) == u'X (2)'
    assert store.unique_name(u'X', [u'X', u'X (2)']) == u'X (3)'


@case
def duplicate_is_a_new_record_with_same_pushes():
    a = tpl(u'Valves', maps=[(u'Mark', u'Tag')])
    a.storage_id = object()
    d = store.duplicate_template(a, [u'Valves'])
    assert d.id != a.id and d.storage_id is None and d.name == u'Valves - Copy'
    assert [(m.src_name, m.tgt_name) for m in d.mappings] == [(u'Mark', u'Tag')]
    d.mappings[0].src_name = u'changed'
    assert a.mappings[0].src_name == u'Mark', 'duplicate shares mapping objects with the original'


@case
def add_mapping_refuses_second_source_for_one_target():
    t = tpl(u'T')
    ok, _ = store.add_mapping(t, store.Mapping(u'Mark', u'Tag', u'instance', u'String', u'String'))
    assert ok
    ok, why = store.add_mapping(t, store.Mapping(u'Comments', u'Tag', u'instance', u'String', u'String'))
    assert not ok and u'already' in why
    ok, _ = store.add_mapping(t, store.Mapping(u'Comments', u'Tag', u'type', u'String', u'String'))
    assert ok, 'the type parameter of the same name is a different target'
    ok, why = store.add_mapping(t, store.Mapping(u'Note', u'Level', u'instance', u'String', u'ElementId'))
    assert not ok


@case
def merge_unions_and_master_wins():
    master = tpl(u'M', maps=[(u'Mark', u'Tag'), (u'Size', u'Label')])
    other = tpl(u'O', maps=[(u'Comments', u'Tag'), (u'System', u'Service')])
    other2 = tpl(u'O2', maps=[(u'Size', u'Label')])
    merged, conflicts = store.merge_templates(master, [other, other2])
    got = [(m.src_name, m.tgt_name) for m in merged.mappings]
    assert got == [(u'Mark', u'Tag'), (u'Size', u'Label'), (u'System', u'Service')], got
    assert conflicts == [(u'Tag', u'Mark', u'Comments')], conflicts
    assert merged.id == master.id and len(master.mappings) == 2, 'merge must not edit the master in place'


@case
def merge_refuses_other_categories():
    try:
        store.merge_templates(tpl(u'M'), [tpl(u'O', tgt=u'-1')])
    except ValueError:
        return
    raise AssertionError('merged templates for different categories')


@case
def delete_plan_lists_users():
    a = tpl(u'A')
    ms = [mar(tid=a.id), mar(), mar(tid=a.id)]
    assert len(store.plan_template_delete(a, ms)) == 2


@case
def pair_exists():
    m = mar()
    assert store.pair_exists([m], m.src_uid, m.tgt_uid) is m
    assert store.pair_exists([m], m.tgt_uid, m.src_uid) is None


# ==========================================================================
# values
# ==========================================================================

def src(storage, text=None, vstring=None, raw=None, has=True, name=u''):
    return {u'storage': storage, u'text': text, u'vstring': vstring, u'raw': raw,
            u'has_value': has, u'name': name}


VALUE_TABLE = [
    # source,                                          target,       clear, expect action, payload
    (src(u'String', text=u'V-101'),                    u'String',    False, u'string', u'V-101'),
    (src(u'String', has=False),                        u'String',    False, u'skip', None),
    (src(u'String', has=False),                        u'String',    True,  u'string', u''),
    (src(u'Integer', raw=0, has=False),                u'Integer',   True,  u'skip', None),
    (src(u'Double', raw=0.328, vstring=u'100 mm'),     u'String',    False, u'string', u'100 mm'),
    (src(u'Double', raw=0.328, vstring=u'100 mm'),     u'Double',    False, u'double', 0.328),
    (src(u'Double', raw=0.328, vstring=u'100 mm'),     u'Integer',   False, u'int', 100),
    (src(u'Double', raw=1.6, vstring=None),            u'Integer',   False, u'int', 2),
    (src(u'Integer', raw=1, vstring=u'Yes'),           u'String',    False, u'string', u'Yes'),
    (src(u'Integer', raw=7, vstring=None),             u'String',    False, u'string', u'7'),
    (src(u'Integer', raw=3),                           u'Integer',   False, u'int', 3),
    (src(u'Integer', raw=3),                           u'Double',    False, u'vstring', u'3'),
    (src(u'String', text=u'250'),                      u'Double',    False, u'vstring', u'250'),
    (src(u'String', text=u' 250 mm '),                 u'Double',    False, u'vstring', u'250 mm'),
    (src(u'String', text=u'DN50'),                     u'Double',    False, u'vstring', u'DN50'),
    (src(u'String', text=u'big'),                      u'Double',    False, u'skip', None),
    (src(u'String', text=u'Yes'),                      u'Integer',   False, u'int', 1),
    (src(u'String', text=u'no'),                       u'Integer',   False, u'int', 0),
    (src(u'String', text=u'12'),                       u'Integer',   False, u'int', 12),
    (src(u'String', text=u'maybe'),                    u'Integer',   False, u'skip', None),
    (src(u'ElementId', raw=345, name=u'Level 01'),     u'String',    False, u'string', u'Level 01'),
    (src(u'ElementId', raw=345),                       u'ElementId', False, u'id', None),
    (src(u'String', text=u'Level 01'),                 u'ElementId', False, u'skip', None),
    (src(u'Double', raw=1.0),                          u'ElementId', False, u'skip', None),
]


@case
def value_table():
    for i, (s, tgt, clear, action, payload) in enumerate(VALUE_TABLE):
        got_action, got_payload, _note = store.plan_value(s, tgt, clear)
        assert got_action == action, 'row {0}: {1} -> {2}: got {3}'.format(i, s, tgt, got_action)
        if payload is not None:
            if isinstance(payload, float):
                assert abs(got_payload - payload) < 1e-9, 'row {0}'.format(i)
            else:
                assert got_payload == payload, 'row {0}: got {1!r}'.format(i, got_payload)


@case
def unchanged_targets_are_recognised():
    assert store.already_equal(u'string', u'A', {u'text': u'A'})
    assert not store.already_equal(u'string', u'A', {u'text': u'B'})
    assert store.already_equal(u'string', u'', {u'text': None})
    assert store.already_equal(u'double', 0.5, {u'raw': 0.5})
    assert store.already_equal(u'int', 1, {u'raw': 1})
    assert store.already_equal(u'vstring', u'250 mm', {u'vstring': u'250 mm'})
    assert not store.already_equal(u'vstring', u'250', {u'vstring': u'250 mm'})
    assert not store.already_equal(u'string', u'A', None)


@case
def conflicts_only_for_different_values():
    writes = [(10, u'Size', u'50', 1), (10, u'Size', u'50', 2), (10, u'Size', u'65', 3),
              (11, u'Size', u'65', 4), (10, u'Mark', u'X', 5)]
    assert store.find_conflicts(writes) == {2: 1}


@case
def storage_compatibility():
    assert store.storage_compatible(u'String', u'String') == (True, u'')
    assert store.storage_compatible(u'Double', u'String')[0]
    assert not store.storage_compatible(u'String', u'ElementId')[0]
    assert not store.storage_compatible(u'ElementId', u'Double')[0]
    assert store.storage_compatible(u'', u'String')[0]


# ==========================================================================
# library file and settings
# ==========================================================================

@case
def library_round_trip():
    a = tpl(u'A', maps=[(u'Mark', u'Tag')])
    b = tpl(u'B\tweird', maps=[(u'x', u'y'), (u'p', u'q')])
    back = store.import_templates(store.export_templates([a, b]))
    assert [(t.id, t.name, len(t.mappings)) for t in back] == [(a.id, a.name, 1), (b.id, b.name, 2)]


@case
def import_plan_updates_renames_and_adds():
    have = [tpl(u'A'), tpl(u'B')]
    same = store.Template.from_text(have[0].to_text())
    clash = tpl(u'b')
    fresh = tpl(u'C')
    plan = store.plan_import([same, clash, fresh], have)
    assert [a for _t, a in plan] == [u'update', u'rename', u'new'], plan
    assert clash.name == u'b (imported)'


@case
def settings_fall_back_key_by_key():
    folder = tempfile.mkdtemp()
    path = os.path.join(folder, 'sm.txt')
    with open(path, 'wb') as fh:
        fh.write(u'theme=light\ngarbage\nunknown=1\nmain_w=900\n'.encode('utf-8'))
    s = store.load_settings(path)
    assert s[u'theme'] == u'light' and s[u'main_w'] == u'900' and u'unknown' not in s
    assert s[u'debug'] == u'0'
    with open(path, 'wb') as fh:
        fh.write(u'theme=purple\n'.encode('utf-8'))
    assert store.load_settings(path)[u'theme'] == u'follow'
    assert store.save_settings({u'theme': u'dark'}, path)
    assert store.load_settings(path)[u'theme'] == u'dark'
    assert store.load_settings(os.path.join(folder, 'missing.txt'))[u'theme'] == u'follow'


@case
def migrations_apply_to_old_files():
    folder = tempfile.mkdtemp()
    path = os.path.join(folder, 'sm.txt')
    with open(path, 'wb') as fh:
        fh.write(u'settings_version=0\n'.encode('utf-8'))
    saved = dict(store.MIGRATIONS)
    try:
        store.MIGRATIONS[1] = {u'debug': u'1'}
        assert store.load_settings(path)[u'debug'] == u'1'
    finally:
        store.MIGRATIONS.clear()
        store.MIGRATIONS.update(saved)


@case
def theme_cycle_and_label():
    assert store.next_theme(u'follow') == u'dark'
    assert store.next_theme(u'dark') == u'light'
    assert store.next_theme(u'light') == u'follow'
    assert store.next_theme(u'nonsense') == u'follow'
    assert store.theme_label(u'follow', u'dark').startswith(u'Auto')
    assert store.theme_label(u'light', u'light') == u'Light'


@case
def plural_wording():
    assert store.plural(1, u'value') == u'1 value'
    assert store.plural(0, u'value') == u'0 values' and store.plural(3, u'marriage') == u'3 marriages'


@case
def natural_sort_and_keywords():
    names = [u'V-10', u'V-9', u'V-100', u'v-2']
    assert sorted(names, key=store.natural_key) == [u'v-2', u'V-9', u'V-10', u'V-100']
    assert store.matches_keywords(u'Pipe Accessories : Gate Valve', u'gate pipe')
    assert not store.matches_keywords(u'Pipe Accessories', u'gate')
    assert store.matches_keywords(u'anything', u'')


# ==========================================================================
# undo / redo and staged template changes
# ==========================================================================

@case
def undo_redo_round_trip():
    u = store.UndoStack()
    assert not u.push(u'same', 1, 1), 'a step that changes nothing was recorded'
    u.push(u'a', 0, 1)
    u.push(u'b', 1, 2)
    assert u.undo() == (u'b', 1) and u.undo() == (u'a', 0) and u.undo() is None
    assert u.redo() == (u'a', 1) and u.redo() == (u'b', 2) and u.redo() is None
    u.undo()
    u.push(u'c', 1, 5)
    assert not u.can_redo(), 'a new step must clear redo'


@case
def undo_merges_typing():
    u = store.UndoStack()
    u.push(u'name', u'A', u'AB', merge=True)
    u.push(u'name', u'AB', u'ABC', merge=True)
    assert len(u.done) == 1 and u.undo() == (u'name', u'A')
    u.push(u'name', u'A', u'AX', merge=True)
    u.push(u'name', u'AX', u'A', merge=True)
    assert not u.done, 'typing back to where it started should leave nothing to undo'


@case
def staged_templates_restore_and_survive_reload():
    a, b = mar(tid=u't1'), mar(tid=u't1')
    a.applied_tid = b.applied_tid = u't1'
    before = store.template_snapshot([a, b])
    a.template_id = u't2'
    assert [m.id for m in store.pending_marriages([a, b])] == [a.id]
    store.restore_templates([a, b], before)
    assert not store.pending_marriages([a, b])
    a.template_id = u't2'
    fresh = store.Marriage.from_text(a.to_text())
    fresh.template_id = u't1'                     # the model still says t1
    assert store.keep_staged([fresh], [a, b]) == 1
    assert fresh.template_id == u't2' and fresh.applied_tid == u't1' and fresh.pending()


# ==========================================================================
# shrink to taskbar arithmetic
# ==========================================================================

@case
def drawer_parks_on_the_bottom_of_the_work_area():
    # 800-high window at y=100, 48px bar, work area bottom at 1040 (taskbar below)
    bar_top, o_top, o_h, drop = store.park_rect(100.0, 800.0, 48.0, 1040.0)
    assert bar_top == 992.0 and drop == 892.0
    assert o_top == 100.0 and o_top + o_h == 1040.0
    # a second bar (a dialog) parks above the first
    bar2, _t, _h, _d = store.park_rect(300.0, 400.0, 42.0, 1040.0, offset=48.0 + store.PARK_GAP)
    assert bar2 + 42.0 == 1040.0 - 54.0


@case
def drawer_window_already_lower_than_the_bar():
    bar_top, o_top, o_h, drop = store.park_rect(900.0, 300.0, 48.0, 1040.0)
    assert drop == 92.0 and o_top == 900.0 and o_top + o_h == 1200.0


@case
def drawer_reopens_upwards_from_the_bar():
    top, drop = store.reopen_rect(992.0, 48.0, 800.0, 0.0)
    assert top == 240.0 and drop == 752.0, (top, drop)
    # dragged up near the top: clamped to the work area, drop shrinks to match
    top, drop = store.reopen_rect(300.0, 48.0, 800.0, 0.0)
    assert top == 0.0 and drop == 300.0
    # monitor ABOVE the primary: negative work-area top is honoured, not 0
    top, drop = store.reopen_rect(-200.0, 48.0, 800.0, -1080.0)
    assert top == -952.0 and drop == 752.0, (top, drop)


# ==========================================================================
# magenta highlight registry (sm_revit) against a fake view
# ==========================================================================

def _load_revit():
    """sm_revit under the stub .NET / Revit API from import_check."""
    import import_check
    finder = import_check._Finder()
    sys.meta_path.insert(0, finder)
    try:
        import sm_revit
    finally:
        sys.meta_path.remove(finder)
    return sm_revit


class _Id(object):
    def __init__(self, v):
        self.Value = v


class _El(object):
    def __init__(self, v):
        self.Id = _Id(v)


class _View(_El):
    def __init__(self, v):
        _El.__init__(self, v)
        self.over = {}

    def GetElementOverrides(self, eid):
        return self.over.get(eid.Value, 'orig-{0}'.format(eid.Value))

    def SetElementOverrides(self, eid, ogs):
        self.over[eid.Value] = ogs


class _Doc(object):
    IsWorkshared = False

    def __init__(self, *things):
        self.things = dict((t.Id.Value, t) for t in things)

    def GetElement(self, eid):
        return self.things.get(eid.Value)


def _fake_revit(commit='Committed'):
    rv = _load_revit()

    class _T(object):
        def __init__(self, doc, name):
            pass

        def GetFailureHandlingOptions(self):
            raise Exception('not needed')

        def Start(self):
            pass

        def Commit(self):
            return commit

        def RollBack(self):
            pass
    rv.Transaction = _T
    rv.magenta_overrides = lambda doc: 'MAGENTA'
    return rv


@case
def highlight_restores_the_original_once_nothing_holds_it():
    rv = _fake_revit()
    view, el = _View(1), _El(2)
    doc = _Doc(view, el)
    reg = {}
    assert rv.highlight(doc, view, [el], reg, u'src')[0] == 1
    assert view.over[2] == 'MAGENTA'
    rv.highlight(doc, view, [el], reg, u'view')          # second holder: prev must stay the original
    assert reg[(1, 2)]['prev'] == 'orig-2', reg
    rv.release(doc, reg, u'src')
    assert view.over[2] == 'MAGENTA', 'released while the view highlight still holds it'
    rv.release(doc, reg, u'view')
    assert view.over[2] == 'orig-2' and not reg


@case
def release_all_and_failed_commit():
    rv = _fake_revit()
    view, a, b = _View(1), _El(2), _El(3)
    doc = _Doc(view, a, b)
    reg = {}
    rv.highlight(doc, view, [a], reg, u'src')
    rv.highlight(doc, view, [b], reg, u'tgt')
    assert rv.release(doc, reg, None) == 2 and not reg
    assert view.over == {2: 'orig-2', 3: 'orig-3'}
    rv2 = _fake_revit(commit='RolledBack')
    reg = {}
    assert rv2.highlight(doc, view, [a], reg, u'src')[0] == 0
    assert not reg, 'a highlight that did not commit stayed in the registry'


# ==========================================================================
# runner + selftest
# ==========================================================================

def run(verbose=True):
    failed = 0
    for fn in CASES:
        try:
            fn()
            if verbose:
                print('{0:55s} ok'.format(fn.__name__))
        except Exception as ex:
            failed += 1
            if verbose:
                print('{0:55s} FAIL  {1}'.format(fn.__name__, ex))
    return failed


def _break(attr, replacement):
    module = store
    if attr.startswith('rv:'):
        module, attr = _load_revit(), attr[3:]
    original = getattr(module, attr)
    setattr(module, attr, replacement)
    return lambda: setattr(module, attr, original)


def _release_ignoring_holders(doc, registry, tag=None):
    n = 0
    for k in [k for k, r in registry.items() if tag is None or tag in r['tags']]:
        rec = registry.pop(k)
        doc.GetElement(rec['view']).SetElementOverrides(rec['el'], rec['prev'])
        n += 1
    return n


BREAKS = [
    ('escape stops escaping tabs', 'escape', lambda t: store.to_text(t).replace(u'\\', u'\\\\')),
    ('parse splits on the last =', 'parse',
     lambda text: [tuple(l.rsplit(u'=', 1)) for l in store.to_text(text).splitlines() if u'=' in l and l[0] != u'=']),
    ('compatibility ignores the target category', 'is_compatible',
     lambda t, s, g: store.to_text(t.src_cat_id) == store.to_text(s)),
    ('merge lets the other template win', 'merge_templates',
     lambda m, o: (o[0].copy(), [])),
    ('text to integer forgets yes/no', 'plan_value',
     (lambda orig: lambda s, t, c=False: (u'skip', None, u'') if (t == u'Integer' and s.get(u'storage') == u'String') else orig(s, t, c))(store.plan_value)),
    ('unchanged check always says equal', 'already_equal', lambda a, p, c: True),
    ('conflicts flag equal values', 'find_conflicts', lambda w: dict((i, 0) for i in range(1, len(w)))),
    ('duplicate keeps the original id', 'duplicate_template', lambda t, names: t.copy(keep_id=True)),
    ('unique_name ignores case', 'unique_name',
     lambda base, existing: base if base not in existing else base + u' (2)'),
    ('next_theme sticks', 'next_theme', lambda s: s),
    ('undo stack keeps redo after a new step', 'UndoStack',
     type('U', (store.UndoStack,), {'push': lambda self, l, b, a, merge=False: (
         self.done.append((l, b, a)) or True) if b != a else False})),
    ('reload drops staged template changes', 'keep_staged',
     lambda fresh, old: [setattr(m, 'applied_tid', m.template_id) for m in fresh] and 0),
    ('reopen clamps to 0 instead of the work-area top', 'reopen_rect',
     lambda bar_top, hh, fh, at: (max(0.0, bar_top + hh - fh), bar_top - max(0.0, bar_top + hh - fh))),
    ('bar parks on the screen bottom, ignoring the offset', 'park_rect',
     (lambda orig: lambda t, h, hh, b, offset=0.0: orig(t, h, hh, b, 0.0))(store.park_rect)),
    ('release restores while another tag holds it', 'rv:release', _release_ignoring_holders),
    ('new_id without counter (the 1.0.0 draft)', 'new_id',
     lambda: u'%05x' % __import__('random').randint(0, 0xFFFFF)),
]


def selftest():
    if run(verbose=False):
        print('the clean logic fails - fix that first')
        return 1
    missed = 0
    for label, attr, replacement in BREAKS:
        undo = _break(attr, replacement)
        try:
            caught = run(verbose=False)
        finally:
            undo()
        print('{0:50s} {1}'.format(label, 'caught by {0} case(s)'.format(caught) if caught else 'MISSED'))
        if not caught:
            missed += 1
    return missed


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        bad = selftest()
        print('\nselftest: {0}'.format('every breakage caught' if not bad else '{0} missed'.format(bad)))
        sys.exit(1 if bad else 0)
    n = run()
    print('\n{0}'.format('all cases pass ({0})'.format(len(CASES)) if not n else '{0} failing'.format(n)))
    sys.exit(1 if n else 0)
