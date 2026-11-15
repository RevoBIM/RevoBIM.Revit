# -*- coding: utf-8 -*-
"""Selected in View - logic checks under plain CPython against the stub API.

    python bench_logic.py             run every check
    python bench_logic.py --selftest  put known bugs back and prove the checks catch them
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import bench_stubs  # noqa: E402
bench_stubs.install()

import siv_core as core  # noqa: E402
import siv_revit as rv  # noqa: E402
from bench_stubs import (  # noqa: E402
    FakeCategory, FakeElement, FakeTag, FakeLink, FakeCloud, FakeImport,
    FakeType, FakeView, FakeDoc, FakeId,
)

CHECKS = []


def check(fn):
    CHECKS.append(fn)
    return fn


def eq(got, want, what):
    if got != want:
        raise AssertionError('{0}: got {1!r}, want {2!r}'.format(what, got, want))


# =====================================================================
# A small model: pipes, ducts, walls, lines (subcategory), pipe tags of
# two types, a pinned duct, a Revit link, a point cloud, a linked and an
# imported DWG, a camera that must never be listed.
# =====================================================================
PIPES = FakeCategory(-2008044, 'Pipes')
DUCTS = FakeCategory(-2008000, 'Ducts')
WALLS = FakeCategory(-2000011, 'Walls')
LINES = FakeCategory(-2000051, 'Lines', 'Model')
THIN = FakeCategory(-9001, '<Thin Lines>', 'Model', parent=LINES)
PTAGS = FakeCategory(-2008045, 'Pipe Tags', 'Annotation')
DTAGS = FakeCategory(-2008001, 'Duct Tags', 'Annotation')
TEXT = FakeCategory(-2000300, 'Text Notes', 'Annotation')
CAMS = FakeCategory(-2000500, 'Cameras')
LINKS = FakeCategory(-2001352, 'RVT Links')
DWG_LINK = FakeCategory(-5001, 'site.dwg', 'Model')
DWG_IMP = FakeCategory(-5002, 'detail.dwg', 'Model')
INTERNAL = FakeCategory(-5003, 'Internal thing', 'Internal')


def model():
    doc = FakeDoc()
    view = FakeView(100, 'Level 01 - Mech')
    doc.add(FakeType(500, 'BGL_Pipe Tag', 'Size'))
    doc.add(FakeType(501, 'BGL_Pipe Tag', 'Service'))
    doc.add(FakeType(510, 'BGL_MEP Tag', 'Size'))
    doc.add(FakeType(511, 'BGL_MEP Tag', 'System'))
    els = {
        'pipe1': doc.add(FakeElement(1, PIPES), view),
        'pipe2': doc.add(FakeElement(2, PIPES), view),
        'duct_pinned': doc.add(FakeElement(3, DUCTS, pinned=True), view),
        'wall': doc.add(FakeElement(4, WALLS), view),
        'line': doc.add(FakeElement(5, THIN), view),
        'tag_size': doc.add(FakeTag(6, PTAGS, type_id=500), view),
        'tag_size2': doc.add(FakeTag(7, PTAGS, type_id=500), view),
        'tag_service': doc.add(FakeTag(8, PTAGS, type_id=501), view),
        'text': doc.add(FakeElement(9, TEXT), view),
        'mep_on_pipe': doc.add(FakeTag(20, PTAGS, type_id=510), view),
        'mep_on_duct': doc.add(FakeTag(21, DTAGS, type_id=511), view),
        'camera': doc.add(FakeElement(10, CAMS), view),
        'link': doc.add(FakeLink(11, LINKS, pinned=True), view),
        'cloud': doc.add(FakeCloud(12, FakeCategory(-2010001, 'Point Clouds')), view),
        'dwg_linked': doc.add(FakeImport(13, DWG_LINK, True), view),
        'dwg_imported': doc.add(FakeImport(14, DWG_IMP, False), view),
        'internal': doc.add(FakeElement(15, INTERNAL), view),
        'nocat': doc.add(FakeElement(16, None), view),
    }
    return doc, view, els


def read_rows():
    doc, view, els = model()
    records, stats = rv.read_view(doc, view)
    rows = core.build_list(records)
    st = core.FilterState()
    st.learn(rows)
    return doc, view, els, rows, stats, st


def row_named(rows, name):
    for r in rows:
        if r['name'] == name:
            return r
    raise AssertionError('no row {0}; have {1}'.format(name, [r['name'] for r in rows]))


def ids(els, *names):
    return [els[n].Id for n in names]


# =====================================================================
# Reading the view
# =====================================================================
@check
def read_view_lists_the_right_categories():
    _d, _v, _e, rows, stats, _s = read_rows()
    names = sorted(r['name'] for r in rows)
    eq(names, sorted(['Pipes', 'Ducts', 'Walls', 'Lines', 'BGL_Pipe Tag', 'BGL_MEP Tag',
                      'Text Notes', 'detail.dwg']), 'listed rows (tags by family)')
    eq(stats['links'], 3, 'links counted (Revit link, point cloud, linked DWG)')
    eq(stats['pinned'], 1, 'pinned counted (link excluded)')


@check
def subcategory_reports_parent():
    _d, _v, _e, rows, _st, _s = read_rows()
    eq(row_named(rows, 'Lines')['count'], 1, 'line style folded into Lines')


@check
def sections_and_order():
    _d, _v, _e, rows, _st, _s = read_rows()
    eq([r['section'] for r in rows],
       ['tags'] * 2 + ['model'] * 5 + ['annotation'], 'Tags heading first')
    eq([r['name'] for r in core.rows_in(rows, 'tags')],
       ['BGL_MEP Tag', 'BGL_Pipe Tag'], 'tag families sorted by name')
    eq([r['name'] for r in core.rows_in(rows, 'model')],
       ['detail.dwg', 'Ducts', 'Lines', 'Pipes', 'Walls'], 'model rows sorted by name')


@check
def tags_split_into_types():
    _d, _v, _e, rows, _st, _s = read_rows()
    tags = row_named(rows, 'BGL_Pipe Tag')
    eq([(c['name'], c['count']) for c in tags['types']],
       [('Service', 1), ('Size', 2)], 'types under their family')
    eq(tags['count'], 3, 'tag total')
    eq(tags['colour'], 'CatPlumb', 'pipe tags take the pipe colour')
    eq(tags['categories'], ['Pipe Tags'], 'category kept for the tooltip')


@check
def one_family_across_categories_is_one_row():
    _d, _v, _e, rows, _st, _s = read_rows()
    mep = row_named(rows, 'BGL_MEP Tag')
    eq(mep['categories'], ['Duct Tags', 'Pipe Tags'], 'both categories under one family')
    eq([c['name'] for c in mep['types']], ['Size', 'System'], 'types')
    eq(len([r for r in rows if r['name'] in ('Pipe Tags', 'Duct Tags')]), 0,
       'no rows per tag category')


# =====================================================================
# Colours
# =====================================================================
@check
def colour_rules():
    cases = [
        ('Pipes', False, 'CatPlumb'), ('Pipe Fittings', False, 'CatPlumb'),
        ('Sprinklers', False, 'CatPlumb'), ('Ducts', False, 'CatMech'),
        ('Air Terminals', False, 'CatMech'), ('Flex Ducts', False, 'CatMech'),
        ('Cable Trays', False, 'CatElec'), ('Cable Tray Fittings', False, 'CatElec'),
        ('Conduits', False, 'CatElec'), ('Lighting Fixtures', False, 'CatElec'),
        ('Structural Columns', False, 'CatStruct'), ('Columns', False, 'CatArch'),
        ('Walls', False, 'CatArch'), ('Doors', False, 'CatArch'),
        ('Grids', False, 'CatDatum'), ('Levels', False, 'CatDatum'),
        ('Section Boxes', False, 'CatDatum'), ('Generic Models', False, 'CatGeneric'),
        ('Model Groups', False, 'CatGeneric'), ('Text Notes', False, 'CatAnno'),
        ('Dimensions', False, 'CatAnno'), ('Detail Items', False, 'CatAnno'),
        ('Duct Tags', True, 'CatMech'), ('Cable Tray Tags', True, 'CatElec'),
        ('Room Tags', True, 'CatArch'), ('Multi-Category Tags', True, 'CatAnno'),
        ('Something Odd', False, 'CatOther'),
    ]
    for name, tag, want in cases:
        eq(core.colour_key(name, tag), want, 'colour of ' + name)


# =====================================================================
# The filter decision
# =====================================================================
def plan(doc, st, els, *names):
    keep, dropped, unknown = rv.plan_selection(doc, ids(els, *names), st)
    return [k.Value for k in keep], sorted(dropped), unknown


@check
def default_keeps_everything():
    doc, _v, els, _rows, _st, st = read_rows()
    eq(st.restricting(), False, 'nothing off by default')
    keep, dropped, _u = plan(doc, st, els, 'pipe1', 'wall', 'link', 'duct_pinned', 'tag_size')
    eq(keep, [1, 4, 11, 3, 6], 'all kept')
    eq(dropped, [], 'nothing dropped')


@check
def unticked_category_is_dropped():
    doc, _v, els, rows, _st, st = read_rows()
    st.set_row(row_named(rows, 'Walls'), False)
    keep, dropped, _u = plan(doc, st, els, 'pipe1', 'wall', 'pipe2')
    eq(keep, [1, 2], 'walls dropped')
    eq(dropped, ['Walls'], 'drop labelled by category')


@check
def links_button():
    doc, _v, els, _rows, _st, st = read_rows()
    st.links_on = False
    keep, dropped, _u = plan(doc, st, els, 'pipe1', 'link', 'cloud', 'dwg_linked', 'dwg_imported')
    eq(keep, [1, 14], 'links, point clouds and linked DWG dropped; imported DWG kept')
    eq(dropped, ['linked', 'linked', 'linked'], 'labels')


@check
def pinned_button():
    doc, _v, els, _rows, _st, st = read_rows()
    st.pinned_on = False
    keep, dropped, _u = plan(doc, st, els, 'pipe1', 'duct_pinned', 'link')
    eq(keep, [1, 11], 'pinned duct dropped; a pinned link follows the links button')
    eq(dropped, ['pinned'], 'labels')


@check
def tag_types_filter_independently():
    doc, _v, els, rows, _st, st = read_rows()
    tags = row_named(rows, 'BGL_Pipe Tag')
    st.set_child(tags, (tags['key'], 500), False)
    eq(core.parent_state(tags, st.off_tags), None, 'parent part-ticked')
    keep, dropped, _u = plan(doc, st, els, 'tag_size', 'tag_service', 'tag_size2')
    eq(keep, [8], 'only Service tags kept')
    eq(dropped, ['BGL_Pipe Tag', 'BGL_Pipe Tag'], 'labels by family')
    eq(tags['key'] in st.off_cats, False, 'category flag stays on while any child is on')


@check
def parent_tick_sets_all_children():
    doc, _v, els, rows, _st, st = read_rows()
    tags = row_named(rows, 'BGL_Pipe Tag')
    st.set_row(tags, False)
    eq(core.parent_state(tags, st.off_tags), False, 'all off')
    keep, _d, _u = plan(doc, st, els, 'tag_size', 'tag_service')
    eq(keep, [], 'every tag dropped')
    st.set_row(tags, True)
    eq(core.parent_state(tags, st.off_tags), True, 'all back on')
    keep, _d, _u = plan(doc, st, els, 'tag_size', 'tag_service')
    eq(keep, [6, 8], 'every tag kept')


@check
def unknown_tag_type_follows_parent():
    doc, view, els, rows, _st, st = read_rows()
    tags = row_named(rows, 'BGL_Pipe Tag')
    doc.add(FakeType(502, 'BGL_Pipe Tag', 'New'))
    new_tag = doc.add(FakeTag(40, PTAGS, type_id=502), view)
    st.set_child(tags, (tags['key'], 500), False)
    keep, _d, _u = rv.plan_selection(doc, [new_tag.Id], st)
    eq(len(keep), 1, 'new type kept while some types are on')
    st.set_row(tags, False)
    keep, _d, _u = rv.plan_selection(doc, [new_tag.Id], st)
    eq(len(keep), 0, 'new type dropped when every type is off')


@check
def unknown_tag_family_follows_the_tags_heading():
    doc, view, els, rows, _st, st = read_rows()
    doc.add(FakeType(520, 'BGL_New Family', 'A'))
    stranger = doc.add(FakeTag(42, PTAGS, type_id=520), view)
    st.set_row(row_named(rows, 'BGL_Pipe Tag'), False)
    keep, _d, unknown = rv.plan_selection(doc, [stranger.Id], st)
    eq((len(keep), unknown), (1, True), 'new family kept while any tag family is on, refresh flagged')
    st.set_all(core.rows_in(rows, 'tags'), False)
    keep, _d, _u = rv.plan_selection(doc, [stranger.Id], st)
    eq(len(keep), 0, 'new family dropped when every tag is off')


@check
def unknown_category_kept_and_flagged():
    doc, view, els, _rows, _st, st = read_rows()
    st.off_cats.add(WALLS.Id.Value)
    tray = doc.add(FakeElement(41, FakeCategory(-2008130, 'Cable Trays')), view)
    keep, dropped, unknown = rv.plan_selection(doc, [tray.Id], st)
    eq((len(keep), dropped, unknown), (1, [], True), 'new category kept, refresh flagged')


@check
def missing_and_uncategorised_elements_kept():
    doc, _v, els, _rows, _st, st = read_rows()
    st.set_all(_rows, False)
    keep, _d, _u = rv.plan_selection(doc, [FakeId(9999), els['nocat'].Id], st)
    eq(len(keep), 2, 'unknown ids and no-category elements are never stripped')


@check
def none_then_all():
    _d, _v, _e, rows, _s, st = read_rows()
    st.set_all(rows, False)
    eq(core.picking_summary(rows, st), (0, len(rows)), 'none')
    eq(core.section_state(core.rows_in(rows, 'tags'), st), False, 'tag section off')
    st.set_all(rows, True)
    eq(core.picking_summary(rows, st), (len(rows), len(rows)), 'all')
    eq(st.restricting(), False, 'all on restricts nothing')


@check
def section_state_mixed():
    _d, _v, _e, rows, _s, st = read_rows()
    st.set_row(row_named(rows, 'Walls'), False)
    eq(core.section_state(core.rows_in(rows, 'model'), st), None, 'model section part-ticked')
    eq(core.section_state(core.rows_in(rows, 'annotation'), st), True, 'annotation untouched')


@check
def ticks_carry_across_views():
    doc, view, els, rows, _s, st = read_rows()
    st.set_row(row_named(rows, 'Walls'), False)
    view2 = FakeView(200, 'Level 02 - Mech')
    doc.add(FakeElement(50, WALLS), view2)
    doc.add(FakeElement(51, FakeCategory(-2008130, 'Cable Trays')), view2)
    records, _stats = rv.read_view(doc, view2)
    rows2 = core.build_list(records)
    st.learn(rows2)
    eq(st.row_on(row_named(rows2, 'Walls')), False, 'walls still off in the next view')
    eq(st.row_on(row_named(rows2, 'Cable Trays')), True, 'new category defaults on')


@check
def drop_summary_text():
    eq(core.drop_summary(5, []), u'Kept 5.', 'nothing dropped')
    eq(core.drop_summary(5, ['Walls', 'pinned', 'Walls']),
       u'Kept 5, dropped 3 (2 Walls, 1 pinned).', 'summary')
    many = ['A', 'B', 'C', 'D', 'E']
    eq(core.drop_summary(0, many), u'Kept 0, dropped 5 (1 A, 1 B, 1 C, +2 more).', 'capped')


@check
def search_is_every_word():
    eq(core.matches(u'pipe tag', u'Pipe Tags'), True, 'both words')
    eq(core.matches(u'tag pipe', u'Pipe Tags'), True, 'any order')
    eq(core.matches(u'pipe duct', u'Pipe Tags'), False, 'every word must match')
    eq(core.matches(u'  ', u'Walls'), True, 'blank matches all')


# =====================================================================
# Settings, theme, egg
# =====================================================================
@check
def settings_round_trip():
    path = os.path.join(tempfile.mkdtemp(), 'siv.txt')
    vals = core.load_settings(path)
    eq(vals['theme'], 'auto', 'default theme')
    eq(vals['debug'], '1', 'debug on by default')
    vals['theme'] = 'light'
    vals['left'] = '120'
    core.save_settings(vals, path)
    eq(core.load_settings(path)['theme'], 'light', 'theme saved')
    eq(core.load_settings(path)['left'], '120', 'bounds saved')


@check
def settings_damaged_falls_back_per_key():
    vals = core.parse_settings(u'theme=purple\ndebug=0\nnonsense\nunknown=1\nleft=a=b\n')
    eq(vals['theme'], 'auto', 'invalid theme -> default')
    eq(vals['debug'], '0', 'valid key kept')
    eq(vals['left'], 'a=b', 'split on the first = only')
    eq('unknown' in vals, False, 'unknown keys ignored')


@check
def settings_migrations_run():
    saved_ver = core.SETTINGS_VERSION
    saved_mig = dict(core.MIGRATIONS)
    try:
        core.SETTINGS_VERSION = 2
        core.MIGRATIONS[1] = lambda d: d.__setitem__('theme', 'dark')
        vals = core.parse_settings(u'settings_version=1\ntheme=auto\n')
        eq(vals['theme'], 'dark', 'migration applied')
        eq(vals['settings_version'], '2', 'stamped with the new version')
    finally:
        core.SETTINGS_VERSION = saved_ver
        core.MIGRATIONS.clear()
        core.MIGRATIONS.update(saved_mig)


@check
def theme_resolution():
    eq(core.resolve_theme('auto', 'light'), 'light', 'auto follows a light canvas')
    eq(core.resolve_theme('auto', 'dark'), 'dark', 'auto follows a dark canvas')
    eq(core.resolve_theme('auto', None), 'dark', 'auto with no reading')
    eq(core.resolve_theme('light', 'dark'), 'light', 'forced light')
    eq([core.next_theme(t) for t in core.THEME_CYCLE], ['dark', 'light', 'auto'], 'cycle')


@check
def canvas_theme_dark_is_zero():
    import Autodesk.Revit.UI as ui_ns

    class Dark(object):
        def __str__(self):
            return 'Dark'

        def __bool__(self):
            return False
        __nonzero__ = __bool__

    class Mgr(object):
        CurrentCanvasTheme = Dark()
    ui_ns.UIThemeManager = Mgr
    try:
        eq(rv.canvas_theme(None), 'dark', 'UITheme.Dark (falsy) still reads as dark')
    finally:
        del ui_ns.UIThemeManager


@check
def canvas_theme_falls_back_to_background():
    class Col(object):
        Red = Green = Blue = 250

    class App(object):
        BackgroundColor = Col()

    class UIApp(object):
        Application = App()
    eq(rv.canvas_theme(UIApp()), 'light', 'white background reads light (pre-2024)')


@check
def slow_clicks():
    c = core.SlowClicks()
    eq([c.click(t) for t in (0, 500, 1000)], [False, False, True], 'three slow clicks')
    c = core.SlowClicks()
    eq([c.click(t) for t in (0, 100, 200)], [False, False, False], 'fast clicks ignored')
    c = core.SlowClicks()
    eq([c.click(t) for t in (0, 3000, 3500, 4000)], [False, False, False, True], 'gap resets')


@check
def eid_value_prefers_value():
    class Old(object):
        IntegerValue = 7

    eq(rv.eid_value(FakeId(5)), 5, '.Value')
    eq(rv.eid_value(Old()), 7, 'falls back to IntegerValue')
    eq(rv.eid_value(None), 0, 'None')


# =====================================================================
# Runner
# =====================================================================
def run_checks():
    failures = []
    for fn in CHECKS:
        try:
            fn()
        except Exception as ex:
            failures.append('{0}: {1}'.format(fn.__name__, ex))
    return failures


def _patch(mod, name, value):
    def apply():
        old = getattr(mod, name)
        setattr(mod, name, value)
        return lambda: setattr(mod, name, old)
    return apply


def _broken_decide(info, state):
    if info.get('linked'):
        return state.links_on, 'linked'
    cat = info.get('cat')
    if cat is not None and cat in state.off_cats:
        return False, 'category'
    return True, ''  # pinned and tag types ignored


def _broken_top_category(e):
    try:
        return e.Category
    except Exception:
        return None


def _broken_is_linked(e):
    return isinstance(e, bench_stubs.RevitLinkInstance)


def _broken_matches(q, t):
    words = (q or u'').lower().split()
    return not words or any(w in (t or u'').lower() for w in words)


def _broken_parse(text):
    vals = dict(core.DEFAULTS)
    for line in (text or u'').splitlines():
        if '=' in line:
            parts = line.split('=')
            vals[parts[0].strip()] = parts[1].strip()
    return vals


def _broken_resolve(setting, canvas):
    return setting if setting in ('dark', 'light') else 'dark'


def _broken_set_child(self, row, child_key, on):
    if on:
        self.off_tags.discard(child_key)
    else:
        self.off_tags.add(child_key)
    self.off_cats.add(row['key'])


def _broken_canvas(uiapp):
    try:
        import Autodesk.Revit.UI as ui_ns
        t = ui_ns.UIThemeManager.CurrentCanvasTheme
        if t:
            return 'dark' if 'dark' in str(t).lower() else 'light'
    except Exception:
        pass
    return 'light'


def _broken_build_list(records):
    """v1.0.0 behaviour: tags grouped by tag category, not family."""
    regrouped = []
    for r in records:
        cat_key, cat_name, ctype, is_tag, tkey, tname, fam = r
        regrouped.append((cat_key, cat_name, ctype, False, tkey, tname, fam) if is_tag else r)
    return _REAL_BUILD(regrouped)


_REAL_BUILD = core.build_list


BREAKAGES = [
    ('tags grouped by category instead of family', _patch(core, 'build_list', _broken_build_list)),
    ('Tags heading not first', _patch(core, 'SECTIONS', [('model', u'Model'), ('annotation', u'Annotation'), ('tags', u'Tags')])),
    ('decide ignores pinned and tag types', _patch(core, 'decide', _broken_decide)),
    ('subcategories not folded to parent', _patch(rv, 'top_category', _broken_top_category)),
    ('point clouds / linked DWG not treated as links', _patch(rv, 'is_linked', _broken_is_linked)),
    ('search matches any word', _patch(core, 'matches', _broken_matches)),
    ('settings split on every =', _patch(core, 'parse_settings', _broken_parse)),
    ('auto theme ignores the canvas', _patch(core, 'resolve_theme', _broken_resolve)),
    ('one tag type off turns the category off', _patch(core.FilterState, 'set_child', _broken_set_child)),
    ('canvas Dark tested by truthiness', _patch(rv, 'canvas_theme', _broken_canvas)),
    ('colour rules in the wrong order', _patch(core, 'COLOUR_RULES', list(reversed(core.COLOUR_RULES)))),
    ('excluded categories not excluded', _patch(rv, '_EXCLUDED_NAMES', ())),
    ('slow clicks count fast clicks', _patch(core.SlowClicks, 'click',
                                             lambda self, ms: (self.times.append(ms) or len(self.times) >= 3))),
]


def selftest():
    clean = run_checks()
    if clean:
        sys.stdout.write('Checks fail on the real code:\n  ' + '\n  '.join(clean) + '\n')
        return 1
    missed = []
    for label, patch in BREAKAGES:
        undo = patch()
        try:
            out = run_checks()
        finally:
            undo()
        if not out:
            missed.append(label)
    sys.stdout.write('selftest: {0}/{1} breakages caught\n'.format(len(BREAKAGES) - len(missed), len(BREAKAGES)))
    if missed:
        sys.stdout.write('MISSED: ' + '; '.join(missed) + '\n')
        return 1
    return 0


def main():
    if '--selftest' in sys.argv:
        return selftest()
    failures = run_checks()
    if failures:
        sys.stdout.write('FAIL\n  ' + '\n  '.join(failures) + '\n')
        return 1
    sys.stdout.write('bench_logic: {0} checks passed\n'.format(len(CHECKS)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
