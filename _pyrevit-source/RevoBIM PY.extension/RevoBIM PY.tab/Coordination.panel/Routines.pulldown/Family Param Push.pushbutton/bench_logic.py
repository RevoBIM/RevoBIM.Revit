# -*- coding: utf-8 -*-
"""Logic bench: runs the tool's real modules under CPython against the fakes in
bench_stubs. `--selftest` breaks the code on purpose and every breakage must be
caught. A breakage whose anchor text is missing fails the selftest."""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.dont_write_bytecode = True
CHECKS = []


def check(fn):
    CHECKS.append(fn)
    return fn


def same(have, want, note=''):
    assert have == want, '{0} != {1} {2}'.format(have, want, note)


def load():
    import bench_stubs
    bench_stubs.install()
    return bench_stubs


STUBS = load()
os.environ['APPDATA'] = tempfile.mkdtemp()
import fpp_core as core        # noqa: E402
import fpp_revit as rvt        # noqa: E402
import fpp_theme as theme      # noqa: E402
import fpp_drawer              # noqa: E402
import fpp_main                # noqa: E402
import fpp_app                 # noqa: E402
import fpp_dialogs             # noqa: E402
import fpp_family              # noqa: E402

CAT = STUBS.Marker(Name='Duct Accessories', Id=STUBS.Id(7),
                   CategoryType='Model')
CAT2 = STUBS.Marker(Name='Pipe Fittings', Id=STUBS.Id(8), CategoryType='Model')


def model():
    """Damper family: two types, three instances. Valve family: one unplaced."""
    doc = STUBS.Doc()
    P = STUBS.Param
    def type_params(mark, width):
        return [P('Type Mark', 'String', mark, bip=11),
                P('Width', 'Double', width, 'length'),
                P('BGL_Type Copy', 'String', '', guid='g-copy'),
                P('BGL_Width Text', 'String', 'old'),
                P('Locked', 'String', 'x', read_only=True)]
    STUBS.Elem(doc, 100, CAT, type_params('FD1', 1.0), name='300x300',
               family='Damper')
    STUBS.Elem(doc, 101, CAT, type_params('FD2', 2.0), name='600x600',
               family='Damper')
    STUBS.Elem(doc, 200, CAT2, type_params('V', 0.5), name='DN25',
               family='Valve')
    def inst(idv, type_id, mark, length):
        return STUBS.Elem(doc, idv, CAT, [
            P('Mark', 'String', mark, bip=22),
            P('Comments', 'String', ''),
            P('Offset', 'Double', length, 'length'),
            P('Count', 'Integer', 3),
            P('Open', 'Integer', 1, 'bool'),
            P('BGL_Note', 'String', '', guid='g-note'),
            P('BGL_Number', 'Double', 0.0, 'number'),
            P('BGL_Int', 'Integer', 0)], type_id=type_id)
    inst(1, 100, 'A', 1.0)
    inst(2, 100, 'B', 2.0)
    inst(3, 101, '', 3.0)
    F = STUBS.FamParam
    damper = STUBS.Family(doc, 900, 'Damper', [
        F('Width', False, 'Double', 'length-2.0.0', default=9.0),
        F('BGL_Width Text', False, 'String', 'text-1.0.0', default=''),
        F('Comments Local', True, 'String', 'text-1.0.0', default='family'),
        F('Offset', True, 'Double', 'length-2.0.0', default=9.0),
        F('Count', True, 'Integer', 'int-1.0.0', default=7),
        F('Mark', True, 'String', 'text-1.0.0', idv=-5),
        F('Driven', True, 'Double', 'length-2.0.0', formula=True, default=1.0),
        F('Old Shared', True, 'String', 'text-1.0.0', guid='g-old'),
        ])
    valve = STUBS.Family(doc, 901, 'Valve', [
        F('Width', False, 'Double', 'length-2.0.0', default=9.0)])
    for idv, family in ((100, damper), (101, damper), (200, valve)):
        doc.elements[idv].Family = family
        doc.elements[idv].family_id = family.Id.Value
    for idv in (1, 2, 3):
        elem = doc.elements[idv]
        elem.family_id = damper.Id.Value
        elem.params.append(P('Comments Local', 'String',
                             {1: 'Riser A', 2: '', 3: 'Plant'}[idv], doc=doc))
        elem.params.append(P('Driven', 'Double', 2.0, 'length', read_only=True,
                             doc=doc))
    return doc


NEW_TEXT = core.SharedRef('BGL_Comment', 'Data', 'text-1.0.0', 'G-TEXT')
NEW_LENGTH = core.SharedRef('BGL_Width', 'Data', 'length-1.0.0', 'G-LEN')
NEW_OFFSET = core.SharedRef('BGL_Offset', 'Data', 'length-1.0.0', 'G-OFF')
NEW_DRIVEN = core.SharedRef('BGL_Driven', 'Data', 'length-1.0.0', 'G-DRV')


def shared_app():
    defs = [STUBS.ExternalDef(r.name, r.guid, r.spec)
            for r in (NEW_TEXT, NEW_LENGTH, NEW_OFFSET, NEW_DRIVEN)]
    opened = STUBS.Marker(Groups=[STUBS.Marker(Name='Data', Definitions=defs)])
    return STUBS.Marker(SharedParametersFilename='C:\\shared.txt',
                        OpenSharedParameterFile=lambda: opened)


def replace_setup(doc=None):
    doc = doc or model()
    fams = rvt.read_model(doc)
    picks = core.ReplacePicks()
    fam = [f for f in fams if f.name == 'Damper'][0]
    picks.add(fam)
    pick = picks.items[fam.key]
    pick.params = fpp_family.read_family_params(doc, pick)
    return doc, picks, pick


def fref(pick, name):
    return [p for p in pick.params if p.name == name][0]


def picked(doc, type_ids=None):
    families = rvt.read_model(doc)
    picks = core.Picks()
    fam = [f for f in families if f.name == 'Damper'][0]
    picks.add(fam, type_ids or [t.idv for t in fam.types])
    pick = picks.items[fam.key]
    pick.params = rvt.discover_params(doc, pick)
    return families, picks, pick


def ref(pick, name, scope):
    return [p for p in pick.params if p.name == name and p.scope == scope][0]


def param(doc, idv, name):
    return doc.elements[idv].LookupParameter(name)


# ---------- rows ----------
@check
def read_counts_and_sorts():
    fams = rvt.read_model(model())
    same([f.name for f in fams], ['Damper', 'Valve'])
    same([t.count for t in fams[0].types], [2, 1])
    same(fams[0].placed(), 3)


@check
def category_filter_and_options():
    fams = rvt.read_model(model())
    same(core.category_options(fams),
         [core.ALL_CATEGORIES, 'Duct Accessories', 'Pipe Fittings'])
    rows = core.family_rows(fams, 'Pipe Fittings', '', set(), core.Picks())
    same([r['text'] for r in rows], ['Valve'])


@check
def search_refines_within_category():
    fams = rvt.read_model(model())
    rows = core.family_rows(fams, core.ALL_CATEGORIES, 'damper', set(),
                            core.Picks())
    same([r['text'] for r in rows], ['Damper'])
    rows = core.family_rows(fams, 'Pipe Fittings', 'damper', set(),
                            core.Picks())
    same(rows, [])


@check
def type_hit_opens_family_with_only_hits():
    fams = rvt.read_model(model())
    rows = core.family_rows(fams, core.ALL_CATEGORIES, '600', set(),
                            core.Picks())
    same([r['text'] for r in rows], ['Damper', '600x600'])
    same(rows[0]['open'], '1')


@check
def caret_opens_types():
    fams = rvt.read_model(model())
    key = fams[0].key
    rows = core.family_rows(fams, core.ALL_CATEGORIES, '', set([key]),
                            core.Picks())
    same([r['kind'] for r in rows], ['f', 't', 't', 'f'])


@check
def picked_shows_on_left():
    fams, picks, _ = picked(model(), [100])
    rows = core.family_rows(fams, core.ALL_CATEGORIES, '',
                            set([fams[0].key]), picks)
    same([r['picked'] for r in rows], ['0', '1', '0', '0'])
    picks.add(fams[0], [101])
    rows = core.family_rows(fams, core.ALL_CATEGORIES, '', set(), picks)
    same(rows[0]['picked'], '1')


@check
def removing_last_type_drops_family():
    _, picks, pick = picked(model())
    picks.remove_keys(['t:100'])
    same(sorted(pick.type_ids), [101])
    same(pick.params, None, 'types changed, parameters must be read again')
    picks.remove_keys(['t:101'])
    same(picks.ordered(), [])
    same(picks.has_type(100), False)


@check
def reload_keeps_mappings_drops_the_gone():
    doc = model()
    fams, picks, pick = picked(doc)
    picks.add_mapping([pick.fam.key], ref(pick, 'Mark', 'I'),
                      ref(pick, 'Comments', 'I'))
    del doc.elements[101]
    fresh = rvt.read_model(doc)
    picks.sync(fresh)
    same(sorted(pick.type_ids), [100])
    same(len(pick.mappings), 1)


# ---------- parameters ----------
@check
def discovers_instance_and_type_with_identity():
    _, _, pick = picked(model())
    note = ref(pick, 'BGL_Note', 'I')
    same(note.guid, 'g-note')
    same(note.origin(), 'Shared')
    same(ref(pick, 'Mark', 'I').origin(), 'Built-in')
    same(ref(pick, 'Open', 'I').kind(), 'Yes/No')
    same(ref(pick, 'Type Mark', 'T').sample, 'FD1')


@check
def targets_are_writable_only():
    _, _, pick = picked(model())
    names = [p.name for p in core.merge_params([pick.params], True)]
    assert 'Locked' not in names
    assert 'Locked' in [p.name for p in core.merge_params([pick.params])]


@check
def several_families_share_only_common():
    a = core.ParamRef('A', 'I', 'String')
    b = core.ParamRef('B', 'I', 'String')
    b2 = core.ParamRef('B', 'I', 'String')
    same([p.name for p in core.merge_params([[a, b], [b2]])], ['B'])


@check
def mapping_rules():
    _, picks, pick = picked(model())
    key = pick.fam.key
    mark = ref(pick, 'Mark', 'I')
    comments = ref(pick, 'Comments', 'I')
    note = ref(pick, 'BGL_Note', 'I')
    same(picks.add_mapping([key], mark, mark)[0], 0)
    same(picks.add_mapping([key], mark, comments)[0], 1)
    added, text = picks.add_mapping([key], note, comments)
    same(added, 0, 'one source per target')
    assert 'already' in text
    same(picks.add_mapping([key], mark, note)[0], 1, 'multiple mappings')
    same(len(picks.mapping_rows([key])), 2)
    same(picks.mapping_count(), 2)


@check
def element_refuses_numbers():
    src = core.ParamRef('Mat', 'I', 'ElementId')
    tgt = core.ParamRef('N', 'I', 'Double')
    same(core.conversion(src, tgt)[0], False)
    same(core.conversion(src, core.ParamRef('T', 'I', 'String'))[0], True)


# ---------- values ----------
@check
def value_conversions():
    V = core.Value
    same(core.plan_value(V('String', 'x', 'x'), 'String', True, False),
         ('set', 'x'))
    same(core.plan_value(V('Double', 1.0, '304.8 mm'), 'Double', True, False),
         ('set', 1.0))
    same(core.plan_value(V('Double', 1.0, '304.8 mm'), 'String', True, False),
         ('set', '304.8 mm'))
    same(core.plan_value(V('Double', 1.0, '304.8 mm'), 'Double', False, False),
         ('text', ['304.8 mm', '304.8']))
    same(core.plan_value(V('String', 'Yes', 'Yes'), 'Integer', False, False),
         ('set', 1))
    same(core.plan_value(V('String', '12', '12'), 'Double', False, False),
         ('text', ['12']))
    same(core.plan_value(V('String', 'abc', 'abc'), 'Double', False, False)[0],
         'refused')
    same(core.plan_value(V('Double', 1.0, '12.5 mm'), 'Integer', False,
                         False)[0], 'refused')
    same(core.plan_value(V('Double', 1.0, '1,200 mm'), 'Integer', False,
                         False), ('set', 1200))
    same(core.plan_value(V('Integer', 3, '3'), 'Double', False, False),
         ('text', ['3']))


@check
def empty_source_skips_unless_told():
    empty = core.Value('String', '', '', True)
    same(core.plan_value(empty, 'String', True, False)[0], 'empty')
    same(core.plan_value(empty, 'String', True, True), ('set', ''))
    same(core.plan_value(empty, 'Double', True, True)[0], 'empty')


@check
def holds_compares_properly():
    V = core.Value
    assert core.holds(V('String', 'a', 'a'), 'set', 'a')
    assert not core.holds(V('String', 'a', 'a'), 'set', 'b')
    assert core.holds(V('Double', 1.0, ''), 'set', 1.0 + 1e-12)
    assert core.holds(V('Double', 1.0, '304.8 mm'), 'text', ['304.8'])
    assert not core.holds(V('Double', 1.0, '304.8 mm'), 'text', ['305'])
    assert not core.holds(None, 'set', 'a')


# ---------- push ----------
def push(doc, picks, clear=False):
    return rvt.run_push(doc, picks, clear)


@check
def instance_to_instance_each_keeps_its_own():
    doc = model()
    _, picks, pick = picked(doc)
    picks.add_mapping([pick.fam.key], ref(pick, 'Mark', 'I'),
                      ref(pick, 'Comments', 'I'))
    rep = push(doc, picks)
    same(param(doc, 1, 'Comments').value, 'A')
    same(param(doc, 2, 'Comments').value, 'B')
    same(rep['written'], 2)
    same(rep['elements'], 2)
    same(rep['empty'], 1, 'instance 3 has no mark')
    same(core.problem_lines(rep), [])
    same(doc.groups, ['assimilated'], 'one undo step')


@check
def only_picked_types_are_touched():
    doc = model()
    doc.elements[3].LookupParameter('Mark').value = 'C'
    _, picks, pick = picked(doc, [100])
    picks.add_mapping([pick.fam.key], ref(pick, 'Mark', 'I'),
                      ref(pick, 'Comments', 'I'))
    push(doc, picks)
    same(param(doc, 3, 'Comments').value, '')


@check
def type_to_instance():
    doc = model()
    _, picks, pick = picked(doc)
    picks.add_mapping([pick.fam.key], ref(pick, 'Type Mark', 'T'),
                      ref(pick, 'BGL_Note', 'I'))
    push(doc, picks)
    same(param(doc, 2, 'BGL_Note').value, 'FD1')
    same(param(doc, 3, 'BGL_Note').value, 'FD2')


@check
def instances_are_only_of_picked_types():
    doc = model()
    _, _, pick = picked(doc, [100])
    same(sorted(rvt.instances_of(doc, pick)), [100])


@check
def type_to_type_works_unplaced():
    doc = model()
    fams = rvt.read_model(doc)
    picks = core.Picks()
    fam = [f for f in fams if f.name == 'Valve'][0]
    picks.add(fam, [200])
    pick = picks.items[fam.key]
    pick.params = rvt.discover_params(doc, pick)
    picks.add_mapping([fam.key], ref(pick, 'Type Mark', 'T'),
                      ref(pick, 'BGL_Type Copy', 'T'))
    rep = push(doc, picks)
    same(param(doc, 200, 'BGL_Type Copy').value, 'V')
    same(rep['written'], 1)


@check
def instance_into_type_flags_disagreement():
    doc = model()
    _, picks, pick = picked(doc, [100])
    picks.add_mapping([pick.fam.key], ref(pick, 'Mark', 'I'),
                      ref(pick, 'BGL_Type Copy', 'T'))
    rep = push(doc, picks)
    same(param(doc, 100, 'BGL_Type Copy').value, 'A', 'first stays')
    same(len(rep['conflicts']), 1)


@check
def unplaced_type_with_instance_target_is_reported():
    doc = model()
    fams = rvt.read_model(doc)
    picks = core.Picks()
    fam = fams[0]
    picks.add(fam, [100, 101])
    pick = picks.items[fam.key]
    pick.params = rvt.discover_params(doc, pick)
    del doc.elements[3]
    picks.add_mapping([fam.key], ref(pick, 'Type Mark', 'T'),
                      ref(pick, 'BGL_Note', 'I'))
    rep = push(doc, picks)
    same(len(rep['no_elements']), 1)


@check
def length_into_text_uses_display_units():
    doc = model()
    _, picks, pick = picked(doc)
    picks.add_mapping([pick.fam.key], ref(pick, 'Width', 'T'),
                      ref(pick, 'BGL_Width Text', 'T'))
    push(doc, picks)
    same(param(doc, 100, 'BGL_Width Text').value, '304.8 mm')


@check
def length_into_number_strips_units():
    doc = model()
    _, picks, pick = picked(doc)
    picks.add_mapping([pick.fam.key], ref(pick, 'Offset', 'I'),
                      ref(pick, 'BGL_Number', 'I'))
    rep = push(doc, picks)
    same(param(doc, 1, 'BGL_Number').value, 304.8)
    same(rep['refused'], [])


def strict_float(value):
    """IronPython's float(None) is a SystemError, not a TypeError."""
    if value is None:
        raise SystemError('Object reference not set to an instance of an object.')
    return float(value)


@check
def unset_number_target_is_written():
    doc = model()
    _, picks, pick = picked(doc)
    target = param(doc, 1, 'BGL_Number')
    target.value = None
    target.HasValue = False
    param(doc, 2, 'BGL_Number').value = None
    param(doc, 2, 'BGL_Number').HasValue = False
    picks.add_mapping([pick.fam.key], ref(pick, 'Offset', 'I'),
                      ref(pick, 'BGL_Number', 'I'))
    core.float = strict_float
    try:
        rep = push(doc, picks)
        same(core.holds(core.Value('Double', None, '', True), 'set', 1.0),
             False)
    finally:
        del core.float
    same(param(doc, 1, 'BGL_Number').value, 304.8)
    same(rep['refused'], [])


@check
def unset_number_same_spec_goes_straight_in():
    doc = model()
    _, picks, pick = picked(doc)
    param(doc, 100, 'Width').Definition.spec = 'length'
    STUBS_P = STUBS.Param('Copy', 'Double', None, 'length', doc=doc)
    doc.elements[100].params.append(STUBS_P)
    pick.params = rvt.discover_params(doc, pick)
    picks.add_mapping([pick.fam.key], ref(pick, 'Width', 'T'),
                      ref(pick, 'Copy', 'T'))
    picks.remove_keys(['t:101'])
    pick.params = rvt.discover_params(doc, pick)
    core.float = strict_float
    try:
        rep = push(doc, picks)
    finally:
        del core.float
    same(STUBS_P.value, 1.0)
    same(rep['refused'], [])


@check
def number_into_integer():
    doc = model()
    _, picks, pick = picked(doc)
    picks.add_mapping([pick.fam.key], ref(pick, 'Count', 'I'),
                      ref(pick, 'BGL_Int', 'I'))
    push(doc, picks)
    same(param(doc, 1, 'BGL_Int').value, 3)


@check
def rerun_writes_nothing_and_opens_no_undo():
    doc = model()
    _, picks, pick = picked(doc)
    picks.add_mapping([pick.fam.key], ref(pick, 'Mark', 'I'),
                      ref(pick, 'Comments', 'I'))
    push(doc, picks)
    before = doc.writes
    doc.groups = []
    rep = push(doc, picks)
    same(doc.writes, before)
    same(doc.groups, [])
    same(rep['already'], 2)


@check
def refused_write_keeps_the_rest():
    doc = model()
    _, picks, pick = picked(doc)
    picks.add_mapping([pick.fam.key], ref(pick, 'Mark', 'I'),
                      ref(pick, 'Comments', 'I'))
    param(doc, 1, 'Comments').refuse = True
    rep = push(doc, picks)
    same(param(doc, 2, 'Comments').value, 'B')
    same(rep['written'], 1)
    same(len(rep['refused']), 1)


@check
def rolled_back_batch_splits_down_to_the_culprit():
    doc = model()
    doc.elements[3].LookupParameter('Mark').value = 'C'
    _, picks, pick = picked(doc)
    picks.add_mapping([pick.fam.key], ref(pick, 'Mark', 'I'),
                      ref(pick, 'Comments', 'I'))
    doc.fail_ids = set([2])
    rep = push(doc, picks)
    same(param(doc, 1, 'Comments').value, 'A')
    same(param(doc, 2, 'Comments').value, '')
    same(param(doc, 3, 'Comments').value, 'C')
    same(rep['written'], 2)
    same(len(rep['refused']), 1)
    assert doc.transactions > 1


@check
def value_that_does_not_stick_is_not_counted():
    doc = model()
    _, picks, pick = picked(doc)
    picks.add_mapping([pick.fam.key], ref(pick, 'Mark', 'I'),
                      ref(pick, 'Comments', 'I'))
    target = param(doc, 1, 'Comments')
    def lying(value):
        return True
    target.Set = lying
    rep = push(doc, picks)
    same(rep['written'], 1)
    assert 'did not stick' in rep['refused'][0]


@check
def held_elements_are_left_out_and_named():
    doc = model()
    doc.IsWorkshared = True
    doc.held = set([2])
    _, picks, pick = picked(doc)
    picks.add_mapping([pick.fam.key], ref(pick, 'Mark', 'I'),
                      ref(pick, 'Comments', 'I'))
    rep = push(doc, picks)
    same(param(doc, 2, 'Comments').value, '')
    assert 'Sam' in rep['held'][0]
    same(rep['written'], 1)


@check
def read_only_on_element_is_reported():
    doc = model()
    _, picks, pick = picked(doc)
    picks.add_mapping([pick.fam.key], ref(pick, 'Mark', 'I'),
                      ref(pick, 'Comments', 'I'))
    param(doc, 1, 'Comments').IsReadOnly = True
    rep = push(doc, picks)
    same(rep['read_only'], {'Comments': 1})


@check
def clear_empty_blanks_target_text():
    doc = model()
    param(doc, 3, 'Comments').value = 'stale'
    _, picks, pick = picked(doc)
    picks.add_mapping([pick.fam.key], ref(pick, 'Mark', 'I'),
                      ref(pick, 'Comments', 'I'))
    push(doc, picks)
    same(param(doc, 3, 'Comments').value, 'stale', 'off by default')
    push(doc, picks, True)
    same(param(doc, 3, 'Comments').value, '')


@check
def shared_found_by_guid_not_name():
    doc = model()
    _, _, pick = picked(doc)
    src = ref(pick, 'BGL_Note', 'I')
    param(doc, 1, 'BGL_Note').Definition.Name = 'Renamed'
    assert rvt.find_param(doc.elements[1], src) is not None


# ---------- settings, theme, window maths ----------
@check
def settings_round_trip_and_damage():
    out = core.parse_settings(u'theme=dark\nnonsense\nunknown=1\nwidth=9=9')
    same(out['theme'], 'dark')
    same(out['width'], '9=9', 'split on the first = only')
    assert 'unknown' not in out
    same(core.parse_settings(u'')['theme'], 'auto')


@check
def theme_follows_canvas():
    same(theme.resolve('auto', 'light'), 'light')
    same(theme.resolve('auto', None), 'dark')
    same(theme.resolve('light', 'dark'), 'light')
    same(theme.next_setting('light'), 'auto')
    same(sorted(theme.LIGHT), sorted(theme.REVIT_DARK))


@check
def canvas_read_survives_dark_being_zero():
    import Autodesk.Revit.UI as ui
    class Zero(int):
        def __str__(self):
            return 'Dark'
    ui.UIThemeManager = STUBS.Marker(CurrentCanvasTheme=Zero(0))
    try:
        same(theme.revit_canvas(), 'dark')
    finally:
        del ui.UIThemeManager


@check
def parking_maths():
    same(core.parked_top(0, 1000, 50), 942.0)
    same(core.parked_top(-1080, 1040, 50), -98.0, 'monitor above the primary')
    same(core.parked_top(0, 1000, 50, 1), 888.0)
    same(core.reopen_top(942, 50, 800, 0, 1000), 192)
    same(core.reopen_top(40, 50, 800, 0, 1000), 0)
    same(core.clamp_left(1500, 600, 0, 1920), 1320)


@check
def egg_counts_slow_clicks_only():
    egg = core.EggWatcher()
    assert not egg.click(0.0)
    assert not egg.click(0.1), 'double click resets'
    assert not egg.click(0.6)
    assert egg.click(1.0)


@check
def engine_note_is_versioned():
    assert core.engine_note_is_stale('1.0.0', '1.0.0')
    assert not core.engine_note_is_stale('0.9.0', '1.0.0')
    assert not core.engine_note_is_stale('', '1.0.0')


@check
def progress_throttles_and_survives_a_bad_callback():
    seen = []
    clock = [0.0]
    meter = core.ProgressMeter(lambda p, l: seen.append(p), lambda: clock[0])
    meter.report(1, 100)
    meter.report(2, 100)
    clock[0] = 1.0
    meter.report(50, 100)
    same(seen, [1, 50])
    def bad(p, l):
        raise ValueError('x')
    meter = core.ProgressMeter(bad, lambda: 5.0)
    meter.report(1, 2)
    meter.report(2, 2)


# ---------- drawer ----------
class Piece(object):
    def __init__(self):
        self.Visibility = 'Visible'
        self.Height = float('nan')
        self.VerticalAlignment = 'Stretch'
        self.ActualHeight = 760.0


class Win(object):
    def __init__(self):
        self.Left, self.Top, self.Width, self.Height = 100.0, 100.0, 900.0, 800.0
        self.MinHeight = 620.0
        self.SizeToContent = 'Height'

    def Activate(self):
        pass


class Timer(object):
    """Like the real one: Start never runs a tick, and what escapes a tick goes
    to the dispatcher rather than back to the caller."""
    def __init__(self, handler, log):
        self.handler, self.log = handler, log
        self.running = False

    def Start(self):
        self.running = True

    def Stop(self):
        self.running = False

    def tick(self):
        try:
            self.handler()
        except Exception as err:
            self.log.append(err)


class Bits(object):
    def visibility(self, name):
        return name

    def size_manual(self):
        return 'Manual'

    def align_top(self):
        return 'Top'

    def align_stretch(self):
        return 'Stretch'

    def nan(self):
        return 'nan'

    def bar_height(self, header, window):
        return 46.0


def rig(owner=None):
    state = {'now': 0.0, 'timers': [], 'errors': []}
    def make(ms, handler):
        timer = Timer(handler, state['errors'])
        state['timers'].append(timer)
        return timer
    win, root, grips, body = Win(), Piece(), Piece(), Piece()
    shrink, expand = Piece(), Piece()
    expand.Visibility = 'Collapsed'
    drawer = fpp_drawer.Drawer(win, Piece(), root, Piece(), shrink, expand,
                               Bits(), grips, [body],
                               lambda w: (0.0, 0.0, 1920.0, 1040.0),
                               make, lambda: state['now'])
    drawer.owner = owner
    return drawer, state, win, root, grips, body, shrink, expand


def run_slide(drawer, state):
    while drawer.sliding:
        state['now'] += 0.05
        state['timers'][-1].tick()
    same(state['errors'], [])


@check
def drawer_full_cycle():
    drawer, state, win, root, grips, body, shrink, expand = rig()
    drawer.toggle()
    same(root.Height, 760.0, 'pinned')
    same(grips.Visibility, 'Collapsed', 'grips park with the window')
    same(win.MinHeight, 0)
    same(win.SizeToContent, 'Manual')
    run_slide(drawer, state)
    assert drawer.parked
    same(win.Height, 46.0)
    same(win.Top, 986.0)
    same(body.Visibility, 'Collapsed')
    same(expand.Visibility, 'Visible', 'green arrow')
    drawer.toggle()
    same(body.Visibility, 'Visible')
    run_slide(drawer, state)
    assert not drawer.parked
    same((win.Top, win.Height), (100.0, 800.0))
    same(win.MinHeight, 620.0)
    same(win.SizeToContent, 'Height')
    same(root.Height, 'nan')
    same(root.VerticalAlignment, 'Stretch')
    same(grips.Visibility, 'Visible')
    same(shrink.Visibility, 'Visible')


@check
def drawer_opens_from_a_moved_bar():
    drawer, state, win, *_ = rig()
    drawer.toggle()
    run_slide(drawer, state)
    win.Top = 900.0
    drawer.toggle()
    run_slide(drawer, state)
    same(win.Top, 146.0)


@check
def drawer_restores_what_siblings_were():
    drawer, state, win, root, grips, body, *_ = rig()
    body.Visibility = 'Hidden'
    drawer.toggle()
    run_slide(drawer, state)
    drawer.toggle()
    run_slide(drawer, state)
    same(body.Visibility, 'Hidden')


@check
def drawer_throwing_frame_lands():
    drawer, state, win, *_ = rig()
    drawer.toggle()
    class Bad(Win):
        def __setattr__(self, name, value):
            raise ValueError('frame')
    drawer.on_tick_real = None
    good = drawer.win
    drawer.clock = lambda: 1 / 0
    state['timers'][-1].tick()
    same(state['errors'], [], 'a frame must not escape to the dispatcher')
    assert drawer.parked
    same(good.Height, 46.0)


@check
def dialog_takes_owner_down_and_brings_it_back():
    owner, ostate, owin, *_ = rig()
    dialog, state, *_ = rig(owner)
    dialog.toggle()
    assert owner.parked
    same(dialog.slot, 1)
    run_slide(dialog, state)
    dialog.toggle()
    run_slide(dialog, state)
    assert not owner.parked


@check
def dialog_leaves_an_already_parked_owner_parked():
    owner, ostate, *_ = rig()
    owner.shrink(True)
    dialog, state, *_ = rig(owner)
    dialog.toggle()
    run_slide(dialog, state)
    dialog.settle()
    dialog.release_owner()
    assert owner.parked


@check
def settle_gives_back_the_real_size():
    drawer, state, win, *_ = rig()
    drawer.toggle()
    run_slide(drawer, state)
    drawer.settle()
    same(win.Height, 800.0)


# ---------- the window, driven ----------
class FakeRunner(object):
    def __init__(self, uiapp):
        self.uiapp = uiapp
        self.names = []
        self.refuse = False

    def submit(self, name, work, done, dispatcher):
        if self.refuse:
            return False
        self.names.append(name)
        import traceback
        result, error = None, None
        try:
            result = work(self.uiapp)
        except Exception:
            error = traceback.format_exc()
        done(result, error)
        return True


def open_tool(doc=None):
    doc = doc or model()
    uiapp = STUBS.Marker(ActiveUIDocument=STUBS.Marker(Document=doc))
    settings = core.load_settings()
    tool = fpp_main.FamilyParamPush(uiapp, doc, rvt.read_model(doc), settings,
                                    FakeRunner(uiapp))
    return tool, doc


def click_row(table, key):
    for item in table.grid.ItemsSource:
        if item['key'] == key:
            if table.single:
                table.grid.SelectedItem = item
            else:
                table.grid.SelectedItems.Add(item)
            return
    raise AssertionError('no row ' + key)


def key_of(table, name):
    for item in table.grid.ItemsSource:
        if item.get('name') == name:
            return item['key']
    raise AssertionError('no parameter ' + name)


def push_damper(tool):
    fam = tool.families[0]
    click_row(tool.left, u'f:' + fam.key)
    tool.grid_left.SelectionChanged.fire()
    tool.btn_push.Click.fire()
    return fam


def map_params(tool, src, tgt, src_scope=None):
    click_row(tool.source, key_of(tool.source, src))
    click_row(tool.target, key_of(tool.target, tgt))
    tool.grid_target.SelectionChanged.fire()
    tool.btn_add.Click.fire()


@check
def window_opens_with_run_off():
    tool, _ = open_tool()
    same(len(tool.left.grid.ItemsSource), 2)
    same(tool.btn_run.IsEnabled, False)
    same(tool.btn_push.IsEnabled, False)
    same(tool.window.Resources['WindowBgBrush'] is not None, True)
    same(tool.find('txt_version').Text[0], 'v')


@check
def window_category_then_search():
    tool, _ = open_tool()
    tool.combo_category.SelectedItem = 'Pipe Fittings'
    tool.combo_category.SelectionChanged.fire()
    same([r['text'] for r in tool.left.grid.ItemsSource], ['Valve'])
    tool.combo_category.SelectedItem = core.ALL_CATEGORIES
    tool.txt_search.Text = u'600'
    tool.on_search_tick(None, None)
    same([r['text'] for r in tool.left.grid.ItemsSource],
         ['Damper', '600x600'])
    same(tool.txt_count.Text, '1 family')


@check
def window_end_to_end():
    tool, doc = open_tool()
    push_damper(tool)
    same(tool.focus, [tool.families[0].key], 'pushed family is ready to map')
    assert len(tool.source_params) > 3
    map_params(tool, 'Mark', 'Comments')
    map_params(tool, 'Type Mark', 'BGL_Note')
    same(len(tool.maps.grid.ItemsSource), 2)
    same(tool.btn_run.IsEnabled, True)
    same(tool.txt_run.Text, 'Run (2)')
    tool.btn_run.Click.fire()
    same(param(doc, 1, 'Comments').value, 'A')
    same(param(doc, 1, 'BGL_Note').value, 'FD1')
    same(tool.busy, False)
    assert 'written' in tool.txt_status.Text
    same(tool.dirty, False)


@check
def window_param_search_keeps_the_pick():
    tool, _ = open_tool()
    push_damper(tool)
    click_row(tool.source, key_of(tool.source, 'Mark'))
    tool.search_source.Text = u'mark'
    tool.search_source.TextChanged.fire()
    same(tool.source.keys(), [key_of(tool.source, 'Mark')])


@check
def prompt_before_the_window_is_shown():
    tool, _ = open_tool()
    prompt = fpp_dialogs.Prompt(tool, 'Title', 'Message')
    same(prompt.window.WindowStartupLocation, 'CenterScreen')
    tool.window.Show()
    prompt = fpp_dialogs.Prompt(tool, 'Title', 'Message')
    same(prompt.window.Owner, tool.window)
    same(prompt.window.WindowStartupLocation, 'CenterOwner')


@check
def dialog_over_a_parked_window_centres_on_screen():
    tool, _ = open_tool()
    tool.window.Show()
    tool.drawer.parked = True
    prompt = fpp_dialogs.Prompt(tool, 'Title', 'Message')
    same(prompt.window.WindowStartupLocation, 'CenterScreen')


@check
def stale_engine_offers_locked_window():
    doc = model()
    uiapp = STUBS.Marker(ActiveUIDocument=STUBS.Marker(Document=doc),
                         MainWindowHandle=1)
    core.write_text(core.note_path(), fpp_app.__version__)
    original = fpp_dialogs.ask
    fpp_dialogs.ask = lambda *a: True
    try:
        tool = fpp_app.launch(uiapp)
    finally:
        fpp_dialogs.ask = original
        core.save_settings(core.load_settings())
    same(tool.runner.direct, True)
    settings = core.load_settings()
    settings['modal'] = u'0'
    core.save_settings(settings)
    core.write_text(core.note_path(), u'')


# ---------- replace ----------
@check
def only_loadable_families_are_offered():
    doc = model()
    doc.families[901].IsEditable = False
    fams = rvt.read_model(doc)
    rows = core.editable_rows(fams, core.ALL_CATEGORIES, '', core.ReplacePicks())
    same([r['text'] for r in rows], ['Damper'])
    doc.families[901].IsEditable = True
    doc.families[901].IsInPlace = True
    fams = rvt.read_model(doc)
    same(len(core.editable_rows(fams, '', '', core.ReplacePicks())), 1)


@check
def family_params_list_without_built_ins_and_closes():
    doc, _, pick = replace_setup()
    names = [p.name for p in pick.params]
    assert 'Mark' not in names
    assert fref(pick, 'Driven').locked
    same(doc.closed, 1, 'the copy is closed')
    same(doc.loads, 0, 'reading loads nothing')


@check
def spec_versions_do_not_block_a_match():
    same(core.spec_base('autodesk.spec.aec:length-2.0.0'),
         core.spec_base('autodesk.spec.aec:length-1.0.0'))
    same(core.spec_label('autodesk.spec.aec:length-2.0.0'), 'Length')
    same(core.spec_label('autodesk.spec:spec.string-2.0.0'), 'String')


@check
def replace_map_rules():
    doc, picks, pick = replace_setup()
    key = pick.fam.key
    width = fref(pick, 'Width')
    same(picks.add_mapping([key], width, NEW_TEXT)[0], 0, 'length into text')
    assert 'Length' in picks.add_mapping([key], width, NEW_TEXT)[1]
    same(picks.add_mapping([key], width, NEW_LENGTH)[0], 1)
    same(picks.add_mapping([key], width, NEW_OFFSET)[0], 0, 'source mapped')
    same(picks.add_mapping([key], fref(pick, 'Offset'), NEW_LENGTH)[0], 0,
         'target used')
    same(core.replace_problem(pick, fref(pick, 'Old Shared'),
                              core.SharedRef('X', '', 'text-1.0.0', 'g-old')),
         'Old Shared is already that shared parameter.')
    clash = core.SharedRef('Offset', '', 'text-1.0.0', 'g-z')
    assert 'already has a parameter' in core.replace_problem(
        pick, fref(pick, 'Comments Local'), clash)
    owned = core.SharedRef('Z', '', 'text-1.0.0', 'G-OLD')
    assert 'already has' in core.replace_problem(
        pick, fref(pick, 'Comments Local'), owned)


def replace_run(doc, picks):
    return fpp_family.run_replace(doc, shared_app(), picks)


@check
def instance_values_survive_the_reload():
    doc, picks, pick = replace_setup()
    picks.add_mapping([pick.fam.key], fref(pick, 'Comments Local'), NEW_TEXT)
    picks.add_mapping([pick.fam.key], fref(pick, 'Offset'), NEW_OFFSET)
    rep = replace_run(doc, picks)
    same(doc.loads, 1)
    same(doc.closed, 2)
    for idv, want in ((1, 'Riser A'), (2, ''), (3, 'Plant')):
        same(param(doc, idv, 'BGL_Comment').value, want, 'blank stays blank')
        same(param(doc, idv, 'BGL_Comment').GUID, 'g-text')
        same(param(doc, idv, 'Comments Local'), None)
    same([param(doc, i, 'BGL_Offset').value for i in (1, 2, 3)],
         [1.0, 2.0, 3.0])
    same(rep['done'], [pick.fam.key])
    same(rep['swapped'], 2)
    same(rep['refused'], [])
    same(rep['failed'], [])
    same(doc.groups, ['assimilated'], 'one undo step')


@check
def type_values_survive_the_reload():
    doc, picks, pick = replace_setup()
    picks.add_mapping([pick.fam.key], fref(pick, 'Width'), NEW_LENGTH)
    rep = replace_run(doc, picks)
    same(param(doc, 100, 'BGL_Width').value, 1.0)
    same(param(doc, 101, 'BGL_Width').value, 2.0)
    same(rep['elements'], 2)


@check
def values_are_counted_across_families():
    doc = model()
    fams = rvt.read_model(doc)
    picks = core.ReplacePicks()
    for fam in fams:
        picks.add(fam)
        pick = picks.items[fam.key]
        pick.params = fpp_family.read_family_params(doc, pick)
        picks.add_mapping([fam.key], fref(pick, 'Width'), NEW_LENGTH)
    rep = replace_run(doc, picks)
    same(len(rep['done']), 2)
    same(rep['elements'], 3)


@check
def formula_parameter_swaps_and_keeps_nothing():
    doc, picks, pick = replace_setup()
    picks.add_mapping([pick.fam.key], fref(pick, 'Driven'), NEW_DRIVEN)
    rep = replace_run(doc, picks)
    same(rep['done'], [pick.fam.key])
    same(rep['read_only'], {}, 'nothing to report')
    assert 'BGL_Driven' in [p.Definition.Name for p in doc.elements[1].params]


@check
def backup_holds_the_originals_before_any_change():
    doc, picks, pick = replace_setup()
    picks.add_mapping([pick.fam.key], fref(pick, 'Comments Local'), NEW_TEXT)
    doc.formula_error = True
    rep = replace_run(doc, picks)
    text = core.read_text(rep['backups'][0])
    assert 'uid-1\t1\tComments Local\tBGL_Comment\tRiser A' in text


@check
def failed_swap_leaves_the_project_alone():
    doc, picks, pick = replace_setup()
    picks.add_mapping([pick.fam.key], fref(pick, 'Comments Local'), NEW_TEXT)
    doc.formula_error = True
    rep = replace_run(doc, picks)
    same(doc.loads, 0)
    same(param(doc, 1, 'Comments Local').value, 'Riser A')
    same(rep['done'], [])
    assert 'formula error' in rep['failed'][0]
    same(doc.closed, 2, 'the family copy is still closed')


@check
def one_bad_family_does_not_stop_the_next():
    doc = model()
    fams = rvt.read_model(doc)
    picks = core.ReplacePicks()
    for fam in fams:
        picks.add(fam)
        pick = picks.items[fam.key]
        pick.params = fpp_family.read_family_params(doc, pick)
        picks.add_mapping([fam.key], fref(pick, 'Width'), NEW_LENGTH)
    original = doc.EditFamily
    def flaky(family):
        if family.Name == 'Damper':
            raise ValueError('already being edited')
        return original(family)
    doc.EditFamily = flaky
    rep = replace_run(doc, picks)
    same(len(rep['done']), 1)
    assert 'already being edited' in rep['failed'][0]


@check
def held_element_stops_that_family_before_it_is_opened():
    doc, picks, pick = replace_setup()
    doc.IsWorkshared = True
    doc.held = set([2])
    picks.add_mapping([pick.fam.key], fref(pick, 'Comments Local'), NEW_TEXT)
    closed = doc.closed
    rep = replace_run(doc, picks)
    same(doc.loads, 0)
    same(doc.closed, closed, 'never opened')
    assert 'Sam' in rep['failed'][0]
    same(param(doc, 2, 'Comments Local') is not None, True)


@check
def family_itself_is_borrowed():
    doc, picks, pick = replace_setup()
    doc.IsWorkshared = True
    doc.held = set([900])
    picks.add_mapping([pick.fam.key], fref(pick, 'Comments Local'), NEW_TEXT)
    same(replace_run(doc, picks)['done'], [])


@check
def load_refused_in_a_group_retries_without_one():
    doc, picks, pick = replace_setup()
    doc.refuse_load_in_group = True
    picks.add_mapping([pick.fam.key], fref(pick, 'Comments Local'), NEW_TEXT)
    rep = replace_run(doc, picks)
    same(doc.loads, 1)
    same(param(doc, 1, 'BGL_Comment').value, 'Riser A')
    same(rep['failed'], [])


@check
def load_returning_nothing_is_a_failure():
    doc, picks, pick = replace_setup()
    doc.load_returns_none = True
    picks.add_mapping([pick.fam.key], fref(pick, 'Comments Local'), NEW_TEXT)
    rep = replace_run(doc, picks)
    same(rep['done'], [])
    assert 'did not load' in rep['failed'][0]
    same(param(doc, 1, 'Comments Local').value, 'Riser A')


@check
def value_that_will_not_write_points_at_the_backup():
    doc, picks, pick = replace_setup()
    picks.add_mapping([pick.fam.key], fref(pick, 'Comments Local'), NEW_TEXT)
    original = fpp_family.load_family
    def then_block(*args):
        group = original(*args)
        param(doc, 3, 'BGL_Comment').refuse = True
        return group
    fpp_family.load_family = then_block
    try:
        rep = replace_run(doc, picks)
    finally:
        fpp_family.load_family = original
    same(len(rep['refused']), 1)
    same(rep['written'], 2, 'the count is what reads back')
    lines = core.replace_problem_lines(rep)
    assert 'Original values saved in' in lines[-1]


@check
def element_lost_on_reload_is_not_counted():
    doc, picks, pick = replace_setup()
    picks.add_mapping([pick.fam.key], fref(pick, 'Comments Local'), NEW_TEXT)
    original = fpp_family.load_family
    def then_lose(*args):
        group = original(*args)
        del doc.elements[3]
        return group
    fpp_family.load_family = then_lose
    try:
        rep = replace_run(doc, picks)
    finally:
        fpp_family.load_family = original
    same(rep['no_target'], {'BGL_Comment': 1})


def open_replace(doc=None):
    tool, doc = open_tool(doc or model())
    tool.uiapp.Application = shared_app()
    tool.btn_tab_replace.Click.fire()
    return tool, doc, tool.replace


def rpush(tab):
    click_row(tab.left, tab.left.grid.ItemsSource[0]['key'])
    tab.btn_rpush.Click.fire()


def rmap(tab, src, tgt):
    click_row(tab.source, key_of(tab.source, src))
    click_row(tab.target, key_of(tab.target, tgt))
    tab.grid_rtarget.SelectionChanged.fire()
    tab.btn_rmap.Click.fire()


@check
def tabs_swap_panels_and_the_run_button():
    tool, doc, tab = open_replace()
    same(tool.body_replace.Visibility, 'Visible')
    same(tool.body_grid.Visibility, 'Collapsed')
    same(tool.btn_tab_replace.Tag, 'on')
    same(tool.txt_run.Text, 'Replace')
    same(tool.tick_clear.Visibility, 'Collapsed')
    same(tab.txt_rfile.Text, 'C:\\shared.txt')
    same(len(tab.target.grid.ItemsSource), 4)
    tool.btn_tab_push.Click.fire()
    same(tool.body_grid.Visibility, 'Visible')
    same(tool.txt_run.Text, 'Run')
    same(tool.drawer.siblings[2], tool.body_replace, 'parks with the window')


@check
def no_shared_file_says_so():
    tool, doc = open_tool()
    tool.uiapp.Application = STUBS.Marker(SharedParametersFilename='',
                                          OpenSharedParameterFile=lambda: None)
    tool.btn_tab_replace.Click.fire()
    same(tool.replace.txt_rfile.Text, 'No shared parameter file is set')
    assert 'shared parameter' in tool.txt_status.Text


@check
def window_replace_end_to_end():
    tool, doc, tab = open_replace()
    rpush(tab)
    same(tab.focus, [tab.picks.order[0]])
    assert 'Mark' not in [r['name'] for r in tab.source.grid.ItemsSource]
    rmap(tab, 'Comments Local', 'BGL_Comment')
    same(tool.txt_run.Text, 'Replace (1)')
    same(tool.btn_run.IsEnabled, True)
    original = fpp_dialogs.ask
    asked = []
    def yes(*a):
        asked.append(a)
        return True
    fpp_dialogs.ask = yes
    try:
        tool.btn_run.Click.fire()
    finally:
        fpp_dialogs.ask = original
    same(len(asked), 1)
    assert 'Schedules, filters and tags' in asked[0][2]
    same(param(doc, 1, 'BGL_Comment').value, 'Riser A')
    same(tab.picks.ordered(), [], 'done families leave the list')
    same(tool.busy, False)
    assert 'restored' in tool.txt_status.Text
    same(tool.progress_band.Visibility, 'Collapsed')


@check
def window_replace_cancel_changes_nothing():
    tool, doc, tab = open_replace()
    rpush(tab)
    rmap(tab, 'Comments Local', 'BGL_Comment')
    original = fpp_dialogs.ask
    fpp_dialogs.ask = lambda *a: False
    try:
        tool.btn_run.Click.fire()
    finally:
        fpp_dialogs.ask = original
    same(doc.loads, 0)
    same(len(tab.picks.ready()), 1)


@check
def window_replace_refusal_shows_and_stays():
    tool, doc, tab = open_replace()
    rpush(tab)
    rmap(tab, 'Width', 'BGL_Comment')
    assert 'Text' in tool.txt_status.Text
    same(tab.picks.mapping_count(), 0)


@check
def window_failed_family_stays_with_its_mappings():
    tool, doc, tab = open_replace()
    rpush(tab)
    rmap(tab, 'Comments Local', 'BGL_Comment')
    doc.formula_error = True
    seen = []
    original_ask, original_tell = fpp_dialogs.ask, fpp_dialogs.tell
    fpp_dialogs.ask = lambda *a: True
    fpp_dialogs.tell = lambda *a, **k: seen.append(a[2])
    try:
        tool.btn_run.Click.fire()
    finally:
        fpp_dialogs.ask, fpp_dialogs.tell = original_ask, original_tell
    same(tab.picks.mapping_count(), 1)
    assert 'Not replaced' in seen[0]


@check
def window_replace_back_and_close_asks():
    tool, doc, tab = open_replace()
    rpush(tab)
    rmap(tab, 'Comments Local', 'BGL_Comment')
    original = fpp_dialogs.ask
    asked = []
    fpp_dialogs.ask = lambda *a: asked.append(a) or False
    try:
        args = STUBS.NetObj('Args')
        args.Cancel = False
        tool.on_closing(None, args)
    finally:
        fpp_dialogs.ask = original
    same(args.Cancel, True)
    click_row(tab.maps, tab.maps.grid.ItemsSource[0]['key'])
    tab.btn_runmap.Click.fire()
    same(tab.picks.mapping_count(), 0)
    tab.btn_rback.Click.fire()
    same(tab.picks.ordered(), [])


@check
def several_families_show_what_they_share():
    doc = model()
    tool, doc, tab = open_replace(doc)
    tab.grid_rleft.SelectedItems.Add(tab.left.grid.ItemsSource[0])
    tab.grid_rleft.SelectedItems.Add(tab.left.grid.ItemsSource[1])
    tab.btn_rpush.Click.fire()
    same(len(tab.focus), 2)
    same([r['name'] for r in tab.source.grid.ItemsSource], ['Width'])


# ---------- saved sets ----------
def saved_set(tool, name):
    original = fpp_dialogs.ask_text
    fpp_dialogs.ask_text = lambda *a: name
    try:
        tool.btn_save_set.Click.fire()
    finally:
        fpp_dialogs.ask_text = original


def clear_sets():
    shutil.rmtree(core.sets_dir(), True)


@check
def set_names_become_legal_files():
    same(core.safe_name(u' a/b:c? '), u'a_b_c_')
    same(core.safe_name(u'...'), u'')


@check
def set_round_trip_text():
    doc = model()
    _, picks, pick = picked(doc, [101])
    src, tgt = ref(pick, 'BGL_Note', 'I'), ref(pick, 'Comments', 'I')
    picks.add_mapping([pick.fam.key], src, tgt)
    entries = core.parse_set(core.set_text(picks))
    same(entries[0]['fkey'], pick.fam.key)
    same(entries[0]['types'], ['600x600'])
    same(entries[0]['maps'], [(src.key, tgt.key)])
    same(core.parse_set(u'junk\nmap=x\ntype=y'), [], 'damage is not fatal')
    same(core.parse_set(u'family=a\nmap=x')[0]['maps'], [])


@check
def unmapped_family_is_not_saved():
    _, picks, _ = picked(model())
    same(core.parse_set(core.set_text(picks)), [])


@check
def window_save_then_load_in_a_fresh_window():
    clear_sets()
    tool, doc = open_tool()
    same(tool.btn_save_set.IsEnabled, False)
    push_damper(tool)
    map_params(tool, 'Mark', 'Comments')
    map_params(tool, 'Type Mark', 'BGL_Note')
    same(tool.btn_save_set.IsEnabled, True)
    saved_set(tool, u'Dampers')
    same(tool.chosen_set(), u'Dampers')
    same(tool.dirty, False)
    fresh, _ = open_tool(doc)
    same(core.list_sets(), [u'Dampers'])
    same(list(fresh.combo_sets.Items), [u'Dampers'], 'listed on opening')
    same(fresh.chosen_set(), u'')
    same(fresh.btn_load_set.IsEnabled, False)
    fresh.combo_sets.SelectedItem = u'Dampers'
    fresh.combo_sets.SelectionChanged.fire()
    same(fresh.btn_load_set.IsEnabled, True)
    fresh.btn_load_set.Click.fire()
    same(fresh.picks.mapping_count(), 2)
    same(len(fresh.maps.grid.ItemsSource), 2)
    same(fresh.btn_run.IsEnabled, True)
    same(fresh.dirty, False)
    fresh.btn_run.Click.fire()
    same(param(doc, 1, 'Comments').value, 'A')
    fresh.btn_load_set.Click.fire()
    same(fresh.picks.mapping_count(), 2, 'loading twice does not double up')
    clear_sets()


@check
def window_load_reports_what_this_model_lacks():
    clear_sets()
    tool, doc = open_tool()
    push_damper(tool)
    map_params(tool, 'Mark', 'Comments')
    map_params(tool, 'Type Mark', 'BGL_Note')
    saved_set(tool, u'Set')
    other = model()
    del other.elements[101]
    for idv in (1, 2):
        elem = other.elements[idv]
        elem.params = [p for p in elem.params
                       if p.Definition.Name != 'BGL_Note']
    other.elements[3].type_id = 100
    other.elements[3].params = [p for p in other.elements[3].params
                                if p.Definition.Name != 'BGL_Note']
    fresh, _ = open_tool(other)
    fresh.combo_sets.SelectedItem = u'Set'
    seen = []
    original = fpp_dialogs.tell
    fpp_dialogs.tell = lambda *a, **k: seen.append(a[2])
    try:
        fresh.btn_load_set.Click.fire()
    finally:
        fpp_dialogs.tell = original
    assert 'Type not in this model: Damper : 600x600' in seen[0]
    assert 'parameter not available: BGL_Note' in seen[0]
    same(fresh.picks.mapping_count(), 1, 'what can load does')
    clear_sets()


@check
def missing_family_is_reported():
    entries = [{'fkey': u'Cat|Gone', 'types': [u'A'], 'maps': []}]
    loaded, missing = core.apply_set_picks(core.Picks(), [], entries)
    same(loaded, [])
    assert 'Gone' in missing[0]
    fam = rvt.read_model(model())[0]
    picks = core.Picks()
    entries = [{'fkey': fam.key, 'types': [u'Nope'], 'maps': []}]
    loaded, missing = core.apply_set_picks(picks, [fam], entries)
    same(picks.ordered(), [], 'no matching type, no family on the right')
    same(len(missing), 1)


@check
def save_asks_before_replacing_and_delete_removes():
    clear_sets()
    tool, _ = open_tool()
    push_damper(tool)
    map_params(tool, 'Mark', 'Comments')
    saved_set(tool, u'One')
    asked = []
    original = fpp_dialogs.ask
    def no(*a):
        asked.append(a)
        return False
    fpp_dialogs.ask = no
    try:
        map_params(tool, 'Type Mark', 'BGL_Note')
        saved_set(tool, u'One')
        same(len(asked), 1)
        same(len(core.parse_set(core.read_text(core.set_path(u'One')))[0]
                 ['maps']), 1, 'refused replace leaves the file alone')
        tool.btn_delete_set.Click.fire()
        same(core.list_sets(), [u'One'])
        fpp_dialogs.ask = lambda *a: True
        tool.btn_delete_set.Click.fire()
        same(core.list_sets(), [])
        same(tool.chosen_set(), u'')
    finally:
        fpp_dialogs.ask = original
    clear_sets()


@check
def cancelled_name_saves_nothing():
    clear_sets()
    tool, _ = open_tool()
    push_damper(tool)
    map_params(tool, 'Mark', 'Comments')
    saved_set(tool, None)
    same(core.list_sets(), [])


@check
def prompt_with_a_text_box():
    tool, _ = open_tool()
    tool.window.Show()
    prompt = fpp_dialogs.Prompt(tool, 'T', 'M', [('Save', True, 'GreenBtn')],
                                None, u'Name')
    same(prompt.find('txt_input').Visibility, 'Visible')
    same(prompt.input.Text, u'Name')
    plain = fpp_dialogs.Prompt(tool, 'T', 'M')
    same(plain.input, None)


@check
def window_type_row_pushes_only_that_type():
    tool, _ = open_tool()
    fam = tool.families[0]
    tool.opened_left.add(fam.key)
    tool.refresh_left()
    click_row(tool.left, u't:100')
    tool.btn_push.Click.fire()
    same(sorted(tool.picks.items[fam.key].type_ids), [100])
    click_row(tool.left, u't:101')
    tool.grid_left.MouseDoubleClick.fire()
    same(sorted(tool.picks.items[fam.key].type_ids), [100, 101])


@check
def window_caret_toggles():
    tool, _ = open_tool()
    key = u'f:' + tool.families[0].key
    args = STUBS.NetObj('Args')
    args.OriginalSource = STUBS.Marker(Name='', DataContext=None)
    tool.on_left_caret(None, args)           # a column heading is a ButtonBase
    same(len(tool.left.grid.ItemsSource), 2)
    args.OriginalSource = STUBS.Marker(Name='caret', DataContext={'key': key})
    tool.on_left_caret(None, args)
    same(len(tool.left.grid.ItemsSource), 4)
    tool.on_left_caret(None, args)
    same(len(tool.left.grid.ItemsSource), 2)


@check
def window_back_and_unmap():
    tool, _ = open_tool()
    fam = push_damper(tool)
    map_params(tool, 'Mark', 'Comments')
    click_row(tool.maps, tool.maps.grid.ItemsSource[0]['key'])
    tool.grid_maps.SelectionChanged.fire()
    same(tool.btn_unmap.IsEnabled, True)
    tool.btn_unmap.Click.fire()
    same(len(tool.maps.grid.ItemsSource), 0)
    same(tool.btn_run.IsEnabled, False)
    tool.btn_back.Click.fire()
    same(tool.picks.ordered(), [])
    same(tool.focus, [])
    same(len(tool.source.grid.ItemsSource), 0)


@check
def window_two_families_map_together():
    doc = model()
    extra = STUBS.Param('Mark', 'String', 'Z', bip=22)
    other = STUBS.Param('Comments', 'String', '')
    STUBS.Elem(doc, 300, CAT, [STUBS.Param('Type Mark', 'String', 'T')],
               name='A', family='Zed')
    STUBS.Elem(doc, 9, CAT, [extra, other], type_id=300)
    tool, doc = open_tool(doc)
    click_row(tool.left, u'f:' + tool.families[0].key)
    click_row(tool.left, u'f:' + tool.families[1].key)
    tool.btn_push.Click.fire()
    same(len(tool.focus), 2)
    assert 'BGL_Note' not in [p.name for p in tool.source_params]
    map_params(tool, 'Mark', 'Comments')
    same(tool.maps.grid.ItemsSource[0]['count'], '2')
    tool.btn_run.Click.fire()
    same(param(doc, 9, 'Comments').value, 'Z')


@check
def window_refuses_another_document():
    tool, doc = open_tool()
    push_damper(tool)
    map_params(tool, 'Mark', 'Comments')
    tool.uiapp.ActiveUIDocument.Document = STUBS.Doc()
    tool.runner.uiapp = tool.uiapp
    answers = []
    original = fpp_dialogs.tell
    fpp_dialogs.tell = lambda *a, **k: answers.append(a)
    try:
        tool.btn_run.Click.fire()
    finally:
        fpp_dialogs.tell = original
    same(param(doc, 1, 'Comments').value, '')
    same(tool.busy, False)
    same(len(answers), 1)
    assert 'not the one this window read' in answers[0][2]


@check
def window_refused_event_frees_it():
    tool, _ = open_tool()
    push_damper(tool)
    map_params(tool, 'Mark', 'Comments')
    tool.runner.refuse = True
    tool.btn_run.Click.fire()
    same(tool.busy, False)
    same(tool.btn_run.IsEnabled, True)


@check
def window_problems_open_a_report():
    tool, doc = open_tool()
    push_damper(tool)
    map_params(tool, 'Mark', 'Comments')
    param(doc, 1, 'Comments').IsReadOnly = True
    seen = []
    original = fpp_dialogs.tell
    fpp_dialogs.tell = lambda *a, **k: seen.append(a)
    try:
        tool.btn_run.Click.fire()
    finally:
        fpp_dialogs.tell = original
    assert 'Read only' in seen[0][2]


@check
def window_close_asks_only_with_unrun_mappings():
    tool, _ = open_tool()
    tool.window.Close()
    tool, _ = open_tool()
    push_damper(tool)
    map_params(tool, 'Mark', 'Comments')
    original = fpp_dialogs.ask
    asked = []
    def no(*a):
        asked.append(a)
        return False
    fpp_dialogs.ask = no
    try:
        args = STUBS.NetObj('Args')
        args.Cancel = False
        tool.on_closing(None, args)
    finally:
        fpp_dialogs.ask = original
    same(len(asked), 1)
    same(args.Cancel, True)


@check
def window_replace_skips_the_question():
    tool, _ = open_tool()
    push_damper(tool)
    map_params(tool, 'Mark', 'Comments')
    tool.window.Tag = 'replace'
    args = STUBS.NetObj('Args')
    args.Cancel = False
    tool.on_closing(None, args)
    same(args.Cancel, False)


@check
def handler_failure_is_shown_not_swallowed():
    tool, _ = open_tool()
    def boom(s, a):
        raise ValueError('kaboom')
    tool.safe(boom)()
    assert 'kaboom' in tool.txt_status.Text


@check
def proof_waits_for_arming():
    tool, _ = open_tool()
    core.write_text(core.note_path(), '1.0.0')
    tool.btn_reload.Click.fire()
    same(core.read_text(core.note_path()), '1.0.0', 'not armed, no proof')
    tool.armed = True
    tool.on_mouse_move(None, None)
    same(core.read_text(core.note_path()), '')


@check
def prompt_builds_and_answers():
    tool, _ = open_tool()
    prompt = fpp_dialogs.Prompt(tool, 'Title', 'Message',
                                [('Yes', True, 'GreenBtn'),
                                 ('No', False, 'GhostBtn')], 'copy me')
    same(len(prompt.find('button_row').Children), 3)
    same(prompt.drawer.owner, tool.drawer)
    prompt.find('button_row').Children[1].Click.fire()
    same(prompt.answer, True)


# ---------- runner ----------
class Event(object):
    def __init__(self, status):
        self.status = status

    def Raise(self):
        return self.status


def runner_with(status):
    runner = fpp_app.Runner({'debug': '0'})
    runner.event = Event(status)
    return runner


@check
def runner_pending_keeps_jobs():
    runner = runner_with('Pending')
    first = runner.submit('a', None, None, None)
    runner.submit('b', None, None, None)
    assert first
    same(len(runner.queue), 2)


@check
def runner_refusal_drops_only_its_job():
    runner = runner_with('Accepted')
    runner.submit('a', None, None, None)
    runner.event = Event('Denied')
    same(runner.submit('b', None, None, None), False)
    same([j.name for j in runner.queue], ['a'])


@check
def runner_reports_failure_to_the_window():
    runner = runner_with('Accepted')
    seen = []
    def work(uiapp):
        raise ValueError('nope')
    dispatcher = STUBS.FakeDispatcher()
    runner.submit('a', work, lambda r, e: seen.append(e), dispatcher)
    runner.Execute(None)
    assert 'nope' in seen[0]
    same(runner.queue, [])


@check
def runner_direct_runs_at_once():
    runner = fpp_app.Runner({'debug': '0'}, True)
    seen = []
    runner.submit('a', lambda u: 5, lambda r, e: seen.append(r),
                  STUBS.FakeDispatcher())
    same(seen, [5])


@check
def launch_notes_then_arms_then_shows():
    doc = model()
    uiapp = STUBS.Marker(ActiveUIDocument=STUBS.Marker(Document=doc),
                         MainWindowHandle=1)
    core.write_text(core.note_path(), '')
    tool = fpp_app.launch(uiapp)
    same(core.read_text(core.note_path()), fpp_app.__version__)
    same(tool.armed, True)
    assert tool.window._shown
    tool.prove_alive()
    same(core.read_text(core.note_path()), '')


# ---------- run ----------
BREAKAGES = [
    ('fpp_core.py', "forced = bool(words) and not fam_hit", "forced = False"),
    ('fpp_core.py', "if category and category != ALL_CATEGORIES \\\n                and fam.category != category:", "if False:"),
    ('fpp_core.py', "shown = hits if forced else fam.types", "shown = fam.types"),
    ('fpp_core.py', "if p.writable or not writable_only", "if True"),
    ('fpp_core.py', "keys = set([p.key for p in items", "keys = set([p.key for p in lists[0]"),
    ('fpp_core.py', "if [m for m in pick.mappings if m.tgt.key == tgt.key]:", "if False:"),
    ('fpp_core.py', "if src.key == tgt.key:\n            return 0,", "if False:\n            return 0,"),
    ('fpp_core.py', "if src.storage == u'Double' and not same_spec:\n            return u'text', number_candidates(src)", "if False:\n            pass"),
    ('fpp_core.py', "if number is None or number != int(number):\n            return None\n        return int(number)\n    low", "return int(number or 0)\n    low"),
    ('fpp_core.py', "if current.raw is None or value is None:\n            return False ", "if False:\n            return False "),
    ('fpp_core.py', "if clear_empty and tgt_storage == u'String':", "if False:"),
    ('fpp_core.py', "if have.mode == write.mode and have.value == write.value:\n            return u'same'\n        return u'conflict'", "return u'same'"),
    ('fpp_core.py', "return area_top + area_height - BAR_GAP - bar - slot * (bar + STACK_GAP)", "return area_height - BAR_GAP - bar"),
    ('fpp_core.py', "return to_text(note).strip() == to_text(version)", "return bool(to_text(note).strip())"),
    ('fpp_core.py', "key, value = line.split('=', 1)", "key, value = line.split('=')[:2]"),
    ('fpp_core.py', "if self.last is None or not (0.25 <= now - self.last <= 2.0):", "if self.last is None:"),
    ('fpp_core.py', "pick.params = None\n        if not pick.type_ids:", "if not pick.type_ids:"),
    ('fpp_revit.py', "if idv in pick.type_ids:\n            out.setdefault", "if True:\n            out.setdefault"),
    ('fpp_revit.py', "if target_param.IsReadOnly:", "if False:"),
    ('fpp_revit.py', "source = type_elem if src.scope == 'T' else inst", "source = inst"),
    ('fpp_revit.py', "target = type_elem if tgt.scope == 'T' else inst", "target = inst"),
    ('fpp_revit.py', "if not writes:\n        return rep", "if False:\n        return rep"),
    ('fpp_revit.py', "    if not doc.IsWorkshared:\n        return writes\n", ""),
    ('fpp_revit.py', "return [w for w in writes if w.idv not in missing]", "return writes"),
    ('fpp_revit.py', "    middle = len(batch) // 2\n    apply_batch(doc, batch[:middle], rep)\n    apply_batch(doc, batch[middle:], rep)\n", ""),
    ('fpp_revit.py', "    prove(doc, writes, rep)\n", "    rep['written'] = len(writes)\n"),
    ('fpp_revit.py', "if ref.guid:", "if False:"),
    ('fpp_revit.py', "group.Assimilate()", "pass"),
    ('fpp_revit.py', "if param is not None and holds(snapshot(doc, param), write.mode,\n                                       write.value, eid_value):", "if param is not None:"),
    ('fpp_theme.py', "return 'dark' if str(theme).endswith('Dark') else 'light'", "return 'dark' if theme else 'light'"),
    ('fpp_drawer.py', "self.root.Height = self.root.ActualHeight or win.Height", "pass"),
    ('fpp_drawer.py', "win.MinHeight = saved['min_height']", "pass"),
    ('fpp_drawer.py', "self.grips.Visibility = self.ui.visibility(COLLAPSED)", "pass"),
    ('fpp_drawer.py', "        except Exception:\n            self.finish()\n\n    def finish", "        except ZeroDivisionError.__class__:\n            self.finish()\n\n    def finish"),
    ('fpp_drawer.py', "self.took_owner = not self.owner.parked", "self.took_owner = True"),
    ('fpp_drawer.py', "moved = abs(win.Top - self.landed_top) > 2.0", "moved = False"),
    ('fpp_drawer.py', "self.hidden.append((item, item.Visibility))", "self.hidden.append((item, 'Visible'))"),
    ('fpp_main.py', "self.grid_left.UnselectAll()\n        self.refresh_left()\n        self.refresh_right([u'f:' + k for k in wanted])\n        self.after_right()", "self.grid_left.UnselectAll()\n        self.refresh_left()\n        self.refresh_right()\n        self.after_right()"),
    ('fpp_main.py', "if not doc.Equals(self.doc):", "if False:"),
    ('fpp_main.py', "        if not accepted:\n            self.busy = False\n", "        if not accepted:\n"),
    ('fpp_main.py', "if self.window.Tag == 'replace':\n            return\n", "pass\n"),
    ('fpp_main.py', "if (self.dirty and self.picks.mapping_count()) \\\n", "if (False) \\\n"),
    ('fpp_main.py', "self.btn_run.IsEnabled = count > 0 and not self.busy", "self.btn_run.IsEnabled = True"),
    ('fpp_app.py', "self.queue.remove(job)", "self.queue = []"),
    ('fpp_app.py', "if status in ('Accepted', 'Pending'):", "if status == 'Accepted':"),
    ('fpp_app.py', "tool.armed = True", "pass"),
    ('fpp_core.py', "return re.sub(r'-\\d+\\.\\d+\\.\\d+$', u'', to_text(spec))", "return to_text(spec)"),
    ('fpp_core.py', "    if spec_base(src.spec) != spec_base(tgt.spec):\n", "    if False:\n"),
    ('fpp_core.py', "if param.guid and param.guid.lower() == tgt.guid:", "if False:"),
    ('fpp_core.py', "        if param.name == tgt.name:\n", "        if False:\n"),
    ('fpp_core.py', "        if not fam.editable:\n            continue\n", ""),
    ('fpp_core.py', "    lines = [u'Not replaced: ' + line for line in rep['failed']]\n", "    lines = []\n"),
    ('fpp_core.py', "if lines and rep['backups']:", "if False:"),
    ('fpp_revit.py', "and not bool(family.IsInPlace)", ""),
    ('fpp_revit.py', "rep['elements'] += len(changed)", "rep['elements'] = len(changed)"),
    ('fpp_family.py', "    if eid_value(param.Id) < 0:\n        return None\n", ""),
    ('fpp_family.py', "            if mapping.src.locked:\n                continue\n", ""),
    ('fpp_family.py', "if value.empty and value.storage != u'String':", "if value.empty:"),
    ('fpp_family.py', "        famdoc.Close(False)\n    rep['swapped']", "        pass\n    rep['swapped']"),
    ('fpp_family.py', "    try:\n        refs = [family_ref(p) for p in famdoc.FamilyManager.Parameters]\n    finally:\n        famdoc.Close(False)\n", "    refs = [family_ref(p) for p in famdoc.FamilyManager.Parameters]\n"),
    ('fpp_family.py', "        wanted = {eid_value(pick.fam.family_id): pick.fam.family_id}\n", "        wanted = {}\n"),
    ('fpp_family.py', "        for write in writes:\n            wanted[write.idv] = write.eid\n", ""),
    ('fpp_family.py', "        if held:\n", "        if False:\n"),
    ('fpp_family.py', "overwriteParameterValues.Value = True", "overwriteParameterValues.Value = False"),
    ('fpp_family.py', "        group.RollBack()\n        state['group'] = False\n        return load_family(doc, famdoc, state)\n", "        raise\n"),
    ('fpp_family.py', "    if loaded is None:\n", "    if False:\n"),
    ('fpp_family.py', "        if param is None:\n            tally(rep['no_target'], write.ref.name)\n        elif param.IsReadOnly:", "        if param.IsReadOnly:"),
    ('fpp_family.py', "        pending = restore(doc, writes, rep)\n", "        pending = []\n"),
    ('fpp_family.py', "    prove(doc, pending, rep)\n", "    rep['written'] = len(pending)\n"),
    ('fpp_family.py', "            if group is not None:\n            group.Assimilate()", "") if False else
    ('fpp_family.py', "        if group is not None:\n            group.Assimilate()\n", ""),
    ('fpp_family.py', "        except Exception as err:\n            rep['failed'].append(u'{0}: {1}'.format(name, to_text(err)))\n            return\n", "        except Exception as err:\n            rep['failed'].append(u'{0}: {1}'.format(name, to_text(err)))\n"),
    ('fpp_replace.py', "        self.picks.remove(rep['done'])\n", ""),
    ('fpp_replace.py', "        if not fpp_dialogs.ask(tool, u'Replace family parameters?', text,\n                               u'Replace'):\n            return\n", ""),
    ('fpp_main.py', "        if self.active == 'replace':\n            self.replace.on_run()\n            return\n", ""),
    ('fpp_main.py', "                or self.replace.picks.mapping_count():", "                or False:"),
    ('fpp_main.py', "return ['tab_strip', 'body_grid', 'body_replace', 'footer_bar']", "return ['tab_strip', 'body_grid', 'footer_bar']"),
    ('fpp_core.py', "        if not pick.mappings:\n            continue\n        lines.append(u'family='", "        lines.append(u'family='"),
    ('fpp_core.py', "if ids:\n            loaded.append", "if True:\n            loaded.append"),
    ('fpp_core.py', "if Mapping(src, tgt).key in have:\n                continue\n", ""),
    ('fpp_core.py', "if src is None or tgt is None or not tgt.writable:", "if src is None and tgt is None:"),
    ('fpp_core.py', "return _BAD_NAME.sub(u'_', to_text(name)).strip().strip(u'.').strip()", "return to_text(name)"),
    ('fpp_core.py', "elif key == u'map' and value.count(u'\\t') == 1:", "elif key == u'map':"),
    ('fpp_main.py', "if name in fpp_core.list_sets() and not fpp_dialogs.ask(", "if False and not fpp_dialogs.ask("),
    ('fpp_main.py', "        self.dirty = False\n        self.refresh_sets(name)", "        self.refresh_sets(name)"),
    ('fpp_main.py', "        problems = missing + problems\n", ""),
    ('fpp_main.py', "        os.remove(fpp_core.set_path(name))\n", ""),
    ('fpp_main.py', "self.refresh_sets()\n        self.refresh_left()", "self.refresh_left()"),
    ('fpp_chrome.py', "                    if self.single:\n                        self.grid.SelectedItem = item\n                        break\n", ""),
    ('fpp_main.py', "if to_text(getattr(source, 'Name', u'')) != u'caret':", "if False:"),
    ('fpp_chrome.py', "if self.window.IsLoaded:        # Owner refuses an unshown window\n            dialog.Owner", "if True:\n            dialog.Owner"),
    ('fpp_chrome.py', "if self.drawer.parked or not self.window.IsLoaded:", "if not self.window.IsLoaded:"),
    ('fpp_main.py', "self.load_params(True) ", "self.load_params() "),
    ('fpp_chrome.py', "                self.on_error(text)\n", "                pass\n"),
]


def run_all():
    failed = 0
    for fn in CHECKS:
        try:
            fn()
        except Exception as err:
            failed += 1
            print('FAIL {0}: {1!r}'.format(fn.__name__, err))
    print('{0} checks, {1} failed'.format(len(CHECKS), failed))
    return failed


def selftest():
    missed = []
    for file_name, old, new in BREAKAGES:
        folder = tempfile.mkdtemp()
        copy = os.path.join(folder, 'tool')
        shutil.copytree(HERE, copy, ignore=shutil.ignore_patterns('__pycache__'))
        path = os.path.join(copy, file_name)
        with open(path) as handle:
            text = handle.read()
        if old not in text:
            missed.append('ANCHOR MISSING: ' + old[:60])
            continue
        with open(path, 'w') as handle:
            handle.write(text.replace(old, new, 1))
        code = subprocess.call(
            [sys.executable, '-B', os.path.join(copy, 'bench_logic.py')],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        shutil.rmtree(folder)
        if code == 0:
            missed.append('NOT CAUGHT: {0}: {1}'.format(file_name, old[:60]))
    for line in missed:
        print(line)
    print('{0} breakages, {1} missed'.format(len(BREAKAGES), len(missed)))
    return 1 if missed else 0


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(selftest())
    sys.exit(1 if run_all() else 0)
