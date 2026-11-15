# -*- coding: utf-8 -*-
"""Unhide in View - logic bench. Plain CPython 3, no Revit.

    python bench_logic.py             run every check
    python bench_logic.py --selftest  break the code on purpose, one
                                      breakage at a time, and prove a check
                                      catches each one

The rules in uiv_core are tested against tables of cases. The Revit side
(uiv_revit) runs end to end against a fake document that behaves the way
the live model does where it matters: a refused element raises, a silent
one does nothing, a view held by someone else will not check out, and a
template decides a controlled view's categories.
"""
import os
import sys
import types
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import bench_stubs  # noqa: E402

MODULES = ['uiv_clr', 'uiv_core', 'uiv_revit', 'uiv_ui']


def load(mutation=None):
    """Load the tool modules fresh from source, optionally with one textual
    breakage applied. Returns a namespace with core, rv, ui."""
    bench_stubs.install()
    for name in MODULES + ['uiv_window']:
        sys.modules.pop(name, None)
    out = types.SimpleNamespace()
    for name in MODULES:
        path = os.path.join(HERE, name + '.py')
        with open(path, encoding='utf-8') as f:
            src = f.read()
        if mutation is not None and mutation[0] == name:
            old, new = mutation[1], mutation[2]
            if old not in src:
                raise RuntimeError('breakage does not apply to {0}: {1!r}'.format(name, old[:60]))
            src = src.replace(old, new, 1)
        mod = types.ModuleType(name)
        mod.__file__ = path
        sys.modules[name] = mod
        exec(compile(src, path, 'exec'), mod.__dict__)
    out.core = sys.modules['uiv_core']
    out.rv = sys.modules['uiv_revit']
    out.ui = sys.modules['uiv_ui']
    return out


# =====================================================================
# Fake Revit
# =====================================================================

class FId(object):
    def __init__(self, v):
        self.Value = v

    def __eq__(self, o):
        return isinstance(o, FId) and o.Value == self.Value

    def __hash__(self):
        return hash(self.Value)

    def __repr__(self):
        return 'FId(%s)' % self.Value


NONE_ID = FId(-1)


class FCat(object):
    def __init__(self, k, name, ct='Model', subs=()):
        self.Id = FId(k)
        self.Name = name
        self.CategoryType = ct
        self.SubCategories = list(subs)


class FElem(object):
    def __init__(self, k, cat=None, hidden_in=(), owner=None, name=u'Thing'):
        self.Id = FId(k)
        self.Category = cat
        self.hidden = set(hidden_in)
        self.OwnerViewId = FId(owner) if owner else NONE_ID
        self.LevelId = NONE_ID
        self.Name = name

    def IsHidden(self, view):
        return view.Id.Value in self.hidden

    def GetTypeId(self):
        return NONE_ID


class FView(object):
    def __init__(self, k, name, doc, template=None):
        self.Id = FId(k)
        self.Name = name
        self.doc = doc
        self.cat_hidden = set()
        self.ViewTemplateId = FId(template) if template else NONE_ID
        self.refuse = set()
        self.silent = set()
        self.noncontrolled = []
        self.ViewType = 'FloorPlan'
        self.IsTemplate = False
        doc.add(self)

    def UnhideElements(self, ids):
        ids = list(ids)
        for i in ids:
            if i.Value in self.refuse:
                raise Exception('cannot unhide %d' % i.Value)
        for i in ids:
            if i.Value in self.silent:
                continue
            e = self.doc.GetElement(i)
            e.hidden.discard(self.Id.Value)

    def CanCategoryBeHidden(self, cid):
        return True

    def GetCategoryHidden(self, cid):
        return cid.Value in self.cat_hidden

    def SetCategoryHidden(self, cid, hidden):
        if hidden:
            self.cat_hidden.add(cid.Value)
        else:
            self.cat_hidden.discard(cid.Value)

    def GetNonControlledTemplateParameterIds(self):
        return list(self.noncontrolled)


class FDoc(object):
    def __init__(self):
        self.elems = {}
        self.IsWorkshared = False
        self.held = set()

    def add(self, e):
        self.elems[e.Id.Value] = e
        return e

    def GetElement(self, i):
        if i is None:
            return None
        return self.elems.get(i.Value)


class _Opts(object):
    def SetFailuresPreprocessor(self, p):
        pass

    def SetClearAfterRollback(self, v):
        pass


class FTransaction(object):
    def __init__(self, doc, name):
        pass

    def GetFailureHandlingOptions(self):
        return _Opts()

    def SetFailureHandlingOptions(self, o):
        pass

    def Start(self):
        return 'Started'

    def Commit(self):
        return 'Committed'

    def RollBack(self):
        return 'RolledBack'


class FGroup(FTransaction):
    def Assimilate(self):
        return 'Committed'


class FWorksharing(object):
    @staticmethod
    def CheckoutElements(doc, ids):
        return [i for i in ids if i.Value not in doc.held]

    @staticmethod
    def GetWorksharingTooltipInfo(doc, i):
        return types.SimpleNamespace(Owner=u'Bob')


class FBip(object):
    VIS_GRAPHICS_MODEL = 'VGM'
    VIS_GRAPHICS_ANNOTATION = 'VGA'


BIP_IDS = {'VGM': -1001, 'VGA': -1002}


class FUiApp(object):
    def __init__(self):
        self.DialogBoxShowing = _Event()


class _Event(object):
    def __iadd__(self, other):
        return self


class _Log(object):
    def __init__(self):
        self.lines = []

    def add(self, t):
        self.lines.append(t)


def fake_revit(M):
    M.rv.Transaction = FTransaction
    M.rv.TransactionGroup = FGroup
    M.rv.WorksharingUtils = FWorksharing
    M.rv.BuiltInParameter = FBip
    M.rv.ElementId = lambda p: FId(BIP_IDS[p])


# =====================================================================
# Checks
# =====================================================================

CHECKS = []


def check(fn):
    CHECKS.append(fn)
    return fn


def eq(a, b, what):
    if a != b:
        raise AssertionError('{0}: expected {1!r}, got {2!r}'.format(what, b, a))


def ok(cond, what):
    if not cond:
        raise AssertionError(what)


# ---- text and views ---------------------------------------------------------

@check
def natural_order(M):
    names = ['P-100', 'P-9', 'p-10', 'Level 2', 'Level 10', 'Level 1']
    got = sorted(names, key=M.core.natural_key)
    eq(got, ['Level 1', 'Level 2', 'Level 10', 'P-9', 'p-10', 'P-100'], 'natural sort')


@check
def keyword_search(M):
    km = M.core.keyword_match
    ok(km(u'Level 01 - Mechanical Floor Plan', u'mech 01'), 'two terms any order')
    ok(not km(u'Level 01 - Mechanical', u'mech 02'), 'a missing term fails')
    ok(km(u'anything', u'   '), 'blank query matches')
    ok(km(u'ABC', u'abc'), 'case-insensitive')


@check
def views_listed(M):
    c = M.core
    ok(c.view_is_listed('FloorPlan', False), 'floor plan listed')
    ok(c.view_is_listed('DrawingSheet', False), 'sheets listed')
    ok(not c.view_is_listed('FloorPlan', True), 'templates left out')
    for vt in ('Schedule', 'PanelSchedule', 'ProjectBrowser', 'SystemBrowser', 'Internal'):
        ok(not c.view_is_listed(vt, False), vt + ' left out')
    eq(c.view_type_label('ThreeD'), u'3D', '3D label')
    eq(c.view_type_label('SomethingNewIn2027'), u'Something New In2027', 'camel fallback')
    eq(c.view_display_name(u'GA', u'M-001'), u'M-001 - GA', 'sheet name')


@check
def views_filter(M):
    vis = M.core.view_row_visible
    ok(vis(u'L01', u'Floor Plan', None, u'', False), 'unscanned shown with toggle off')
    ok(not vis(u'L01', u'Floor Plan', None, u'', True), 'unscanned hidden with toggle on')
    ok(not vis(u'L01', u'Floor Plan', 0, u'', True), 'zero hidden with toggle on')
    ok(vis(u'L01', u'Floor Plan', 3, u'floor', True), 'search over type')
    ok(not vis(u'L01', u'Floor Plan', 3, u'section', True), 'search excludes')
    eq(M.core.count_text(None), u'\u2026', 'unscanned shows an ellipsis')


@check
def column_filters(M):
    m = M.core.row_matches_columns
    row = {'category': u'Pipes', 'ftype': u'Copper : 15mm', 'level': u'L01'}
    ok(m(row, {'category': u'pip', 'level': u'01'}), 'both columns match')
    ok(not m(row, {'category': u'duct'}), 'one column fails')
    ok(m(row, {}), 'no filters')


# ---- scanner ------------------------------------------------------------------

def _scan_world():
    # view keys 1..3; items are (key, set of hidden view keys)
    model = [(k, set()) for k in range(1000)]
    model[5] = (5, {1})
    model[700] = (700, {1, 3})
    model[999] = (999, {2})
    owned = {1: [(5000, {1})], 2: [], 3: [(6000, set())]}

    def segments(vk):
        return [model, owned.get(vk, [])]

    def is_hidden(item, vk):
        return vk in item[1]

    def id_of(item):
        return item[0]
    return segments, is_hidden, id_of


class Clock(object):
    def __init__(self, step=0.001):
        self.t = 0.0
        self.step = step

    def __call__(self):
        self.t += self.step
        return self.t


@check
def scanner_finds(M):
    seg, hid, idf = _scan_world()
    s = M.core.Scanner([1, 2, 3], seg, hid, idf, Clock(0.0))
    s.step(1.0)
    ok(s.finished(), 'finished in one big slice')
    eq(sorted(s.results[1]), [5, 700, 5000], 'view 1 incl. its own annotation')
    eq(s.results[2], [999], 'view 2')
    eq(s.results[3], [700], 'view 3')
    eq(s.count(1), 3, 'count')
    eq(s.progress(), (3, 3), 'progress')


@check
def scanner_slices_resume(M):
    """Tiny budget: many slices, same answer, nothing counted twice."""
    seg, hid, idf = _scan_world()
    s = M.core.Scanner([1, 2, 3], seg, hid, idf, Clock(0.01))
    slices = 0
    while not s.finished():
        s.step(0.005)
        slices += 1
        if slices > 500:
            raise AssertionError('scan never finished - progress inside a view is lost')
    ok(slices > 3, 'the budget actually sliced the work ({0} slices)'.format(slices))
    eq(sorted(s.results[1]), [5, 700, 5000], 'view 1 after slicing')
    eq(s.checked, 3 * 1000 + 1 + 0 + 1, 'every candidate checked exactly once')


@check
def scanner_bump_and_errors(M):
    seg, hid, idf = _scan_world()
    s = M.core.Scanner([1, 2, 3], seg, hid, idf, Clock(0.0))
    s.bump([3, 3, 99])
    eq(s.order, [3, 1, 2], 'bumped view first, unknown ignored, no duplicates')
    finished = s.step(1.0)
    eq(finished, [3, 1, 2], 'scanned in the bumped order')

    def bad_segments(vk):
        if vk == 2:
            raise RuntimeError('unreadable')
        return seg(vk)

    def bad_hidden(item, vk):
        if item[0] == 700:
            raise RuntimeError('deleted')
        return hid(item, vk)
    s2 = M.core.Scanner([1, 2], bad_segments, bad_hidden, idf, Clock(0.0))
    s2.step(1.0)
    ok(s2.finished(), 'errors never stall the queue')
    eq(s2.results[2], [], 'unreadable view finishes empty')
    eq(s2.errors, 2, 'both errors counted')


@check
def scanner_remove_found(M):
    seg, hid, idf = _scan_world()
    s = M.core.Scanner([1], seg, hid, idf, Clock(0.0))
    s.step(1.0)
    s.remove_found(1, [700])
    eq(sorted(s.results[1]), [5, 5000], 'unhidden id dropped')


# ---- staging and plan -----------------------------------------------------------

@check
def staging_rules(M):
    st = M.core.Staging()
    st.set_element(1, 10, True)
    st.set_element(1, 11, True)
    st.set_element(2, 20, True)
    eq(st.element_total(), 3, 'total')
    eq(st.element_views(), 2, 'views')
    st.prune_view(1, set([11]))
    eq(st.elements[1], set([11]), 'prune keeps only still-hidden ticks')
    st.prune_view(2, set())
    ok(2 not in st.elements, 'empty bucket removed')
    st.set_category(5, True)
    st.set_category(6, True)
    st.prune_categories(set([5]))
    eq(st.categories, set([5]), 'categories pruned to offered')
    ok(st.anything(), 'anything')
    st.clear()
    ok(not st.anything(), 'cleared')


@check
def targets(M):
    eq(M.core.target_views([3, 4], 1), [3, 4], 'ticked views win')
    eq(M.core.target_views([], 1), [1], 'focus when none ticked')
    eq(M.core.target_views([], None), [], 'nothing')


@check
def category_summary(M):
    state = {
        1: {7: (True, None), 8: (True, u'MEP Plan')},
        2: {7: (True, None)},
        3: {},
    }
    rows = M.core.summarise_categories([1, 2, 3], state, {7: u'Pipes', 8: u'Ducts'})
    eq([r['name'] for r in rows], [u'Ducts', u'Pipes'], 'sorted by name')
    pipes = rows[1]
    eq(pipes['hidden_in'], 2, 'hidden in two of three')
    eq(pipes['hidden_text'], u'2 / 3', 'hidden text')
    eq(rows[0]['note'], u'Template: MEP Plan', 'template named')


@check
def plan_elements(M):
    st = M.core.Staging()
    st.set_element(1, 10, True)
    st.set_element(1, 11, True)
    plan = M.core.build_plan(st, {1: set([10])}, [], {}, False, lambda vk: None)
    eq(plan['elements'], [(1, [10])], 'only still-hidden elements')
    eq(plan['skipped'][0][3], u'no longer hidden', 'the other is said')


@check
def plan_templates(M):
    st = M.core.Staging()
    st.set_category(7, True)
    state = {1: {7: (True, u'T')}, 2: {7: (True, u'T')}, 3: {7: (True, None)}}
    tmpl = {1: 50, 2: 50, 3: None}
    plan = M.core.build_plan(st, {}, [1, 2, 3], state, False, tmpl.get)
    eq(plan['categories'], [(3, False, [7])], 'template-controlled views skipped')
    eq(len(plan['skipped']), 2, 'and both are said')
    plan = M.core.build_plan(st, {}, [1, 2, 3], state, True, tmpl.get)
    eq(plan['categories'], [(50, True, [7]), (3, False, [7])],
       'one template action shared by two views')
    eq(M.core.plan_counts(plan), (0, 0, 2, 2), 'counts')


@check
def labels(M):
    c = M.core
    eq(c.unhide_label(0, 0), u'Unhide', 'nothing')
    eq(c.unhide_label(1, 0), u'Unhide 1 element', 'one element')
    eq(c.unhide_label(4, 2), u'Unhide 4 elements + 2 categories', 'both')
    eq(c.views_button_label(0, 0), u'Unhide all in ticked views', 'no views')
    eq(c.views_button_label(2, 9), u'Unhide all in 2 views (9)', 'views')
    text = c.summarise_result({'elements_ok': 3, 'element_views': 1, 'categories_ok': 1,
                               'category_owners': 2, 'refused': [1], 'skipped': []})
    eq(text, u'Unhid 3 elements in 1 view. 1 category unhidden in 2 views. '
             u'1 refused - see the red rows.', 'result')


# ---- theme, clicks, settings ------------------------------------------------------

@check
def theme_rules(M):
    c = M.core
    eq(c.next_theme('follow'), 'dark', 'Auto -> Dark')
    eq(c.next_theme('dark'), 'light', 'Dark -> Light')
    eq(c.next_theme('light'), 'follow', 'Light -> Auto')
    eq(c.normalise_theme('auto'), 'follow', 'old spelling')
    eq(c.resolve_theme('follow', 'light'), 'light', 'follows the canvas')
    eq(c.resolve_theme('follow', None), 'dark', 'unreadable canvas -> dark')
    eq(c.resolve_theme('light', 'dark'), 'light', 'a fixed choice wins')
    eq(c.theme_from_enum_text('Dark'), 'dark', 'enum by name')
    eq(c.theme_from_background(250, 250, 250), 'light', 'white canvas')
    eq(c.theme_from_background(30, 30, 30), 'dark', 'black canvas')


class _FalsyDark(object):
    """UITheme.Dark is 0: falsy, but a real answer."""

    def __bool__(self):
        return False

    def ToString(self):
        return 'Dark'


@check
def canvas_dark_is_zero(M):
    rui = sys.modules['Autodesk.Revit.UI']
    saved = getattr(rui, 'UIThemeManager', None)
    rui.UIThemeManager = types.SimpleNamespace(CurrentCanvasTheme=_FalsyDark(),
                                               CurrentTheme=_FalsyDark())
    try:
        app = types.SimpleNamespace(Application=types.SimpleNamespace(
            BackgroundColor=types.SimpleNamespace(Red=255, Green=255, Blue=255)))
        eq(M.ui.canvas_theme(app), 'dark', 'a Dark canvas (enum 0) is read as dark')
    finally:
        rui.UIThemeManager = saved


@check
def palettes(M):
    p = M.core.PALETTES
    eq(sorted(p['dark'].keys()), sorted(p['light'].keys()), 'both palettes carry the same keys')
    for name in p:
        for k, v in p[name].items():
            M.core.hex_to_rgb(v)
    ok(p['light']['Blue'] != p['dark']['Blue'], 'light accents are darkened, not shared')


@check
def slow_clicks(M):
    sc = M.core.SlowClicks()
    ok(not sc.add(1.0), 'first')
    ok(not sc.add(1.6), 'second')
    ok(not sc.add(1.6), 'the same click reported twice is one click')
    ok(sc.add(2.2), 'third fires')
    sc = M.core.SlowClicks()
    sc.add(1.0)
    sc.add(1.1)
    ok(not sc.add(1.2), 'too fast never fires')


@check
def settings_round_trip(M):
    c = M.core
    s = c.parse_settings(u'theme=auto\nwidth=1500\nnope=1\nsplit=a=b\nsettings_version=1\n')
    eq(s['theme'], 'follow', 'auto is read as follow')
    eq(s['width'], '1500', 'value kept')
    ok('nope' not in s, 'unknown keys ignored')
    eq(s['split'], 'a=b', 'split on the first = only')
    eq(c.as_float(s['split'], 0.56, 0.2, 0.8), 0.56, 'damaged value falls back')
    again = c.parse_settings(c.format_settings(s))
    eq(again, s, 'round trip')
    s2 = c.parse_settings(u'')
    eq(s2['debug'], '1', 'debug on by default')
    eq(s2['theme'], 'follow', 'follows the canvas by default')


@check
def settings_migrations(M):
    c = M.core
    saved = (dict(c.MIGRATIONS), c.SETTINGS_VERSION)
    c.MIGRATIONS.clear()
    c.MIGRATIONS[2] = {'scan_budget_ms': ('120', '80')}
    c.SETTINGS_VERSION = 2
    try:
        old = c.parse_settings(u'settings_version=1\nscan_budget_ms=120\n')
        eq(old['scan_budget_ms'], '80', 'an old file gets the new default')
        eq(old['settings_version'], '2', 'and is stamped with the new version')
        mine = c.parse_settings(u'settings_version=1\nscan_budget_ms=200\n')
        eq(mine['scan_budget_ms'], '200', 'a value the user set is kept')
        new = c.parse_settings(u'settings_version=2\nscan_budget_ms=120\n')
        eq(new['scan_budget_ms'], '120', 'a current file is left alone')
    finally:
        c.MIGRATIONS.clear()
        c.MIGRATIONS.update(saved[0])
        c.SETTINGS_VERSION = saved[1]


# ---- the Revit side, end to end on a fake model -------------------------------------

def _model(M):
    fake_revit(M)
    doc = FDoc()
    pipes = FCat(1, u'Pipes')
    v10 = FView(10, u'L01', doc)
    v20 = FView(20, u'L02', doc)
    tmpl = FView(50, u'MEP Plan', doc)
    v30 = FView(30, u'L03', doc, template=50)
    for k in (100, 101, 102, 103):
        doc.add(FElem(k, pipes, hidden_in=[10]))
    doc.add(FElem(200, pipes, hidden_in=[20]))
    v10.refuse.add(101)
    v10.silent.add(103)
    v10.cat_hidden.add(5)
    tmpl.cat_hidden.add(6)
    return doc, {10: v10, 20: v20, 30: v30, 50: tmpl}


def _run(M, doc, views, plan):
    log = _Log()
    res = M.rv.run_unhide(
        doc, plan,
        view_of=lambda vk: views.get(vk),
        owner_of=lambda k, is_t: views.get(k),
        eid_of=lambda vk, ek: FId(ek),
        cat_id_of=lambda ck: FId(ck),
        uiapp=FUiApp(), log=log)
    return res, log


@check
def unhide_elements_end_to_end(M):
    doc, views = _model(M)
    plan = {'elements': [(10, [100, 101, 102, 103, 999])], 'categories': [], 'skipped': []}
    res, log = _run(M, doc, views, plan)
    eq(sorted(e for _v, e in res['ok_elements']), [100, 102], 'the rest go through a refusal')
    why = dict((r[2], r[3]) for r in res['refused'])
    ok(why.get(101, u'').startswith(u'Refused'), 'refused element says Revit refused it')
    eq(why.get(103), u'Still hidden after the run', 'a silent write is caught on read back')
    eq(why.get(999), u'No longer in the model', 'deleted element')
    ok(not doc.elems[100].IsHidden(views[10]), 'really unhidden')
    eq(res['elements_ok'], 2, 'count is what reads back')


@check
def unhide_held_view(M):
    doc, views = _model(M)
    doc.IsWorkshared = True
    doc.held.add(20)
    plan = {'elements': [(10, [100]), (20, [200])], 'categories': [], 'skipped': []}
    res, log = _run(M, doc, views, plan)
    eq([e for _v, e in res['ok_elements']], [100], 'borrowed view done')
    why = dict((r[2], r[3]) for r in res['refused'])
    eq(why.get(200), u'Held by Bob', 'a view held by someone else is named')
    ok(doc.elems[200].IsHidden(views[20]), 'and left alone')


@check
def unhide_categories_end_to_end(M):
    doc, views = _model(M)
    plan = {'elements': [], 'categories': [(10, False, [5]), (50, True, [6])], 'skipped': []}
    res, log = _run(M, doc, views, plan)
    eq(sorted((o, c) for o, _t, c in res['ok_categories']), [(10, 5), (50, 6)], 'view and template')
    ok(not views[10].GetCategoryHidden(FId(5)), 'view category shown')
    ok(not views[50].GetCategoryHidden(FId(6)), 'template category shown')


@check
def category_state_reads_template(M):
    doc, views = _model(M)
    pipes = FCat(1, u'Pipes')
    centre = FCat(2, u'Centre line')
    ducts = FCat(3, u'Ducts')
    tags = FCat(4, u'Tags', 'Annotation')
    cats = [(1, pipes, u'Pipes', 'Model', None), (2, centre, u'Pipes : Centre line', 'Model', 1),
            (3, ducts, u'Ducts', 'Model', None), (4, tags, u'Tags', 'Annotation', None)]
    v10 = views[10]
    v10.cat_hidden = set([1, 2, 3])
    st = M.rv.read_category_state(doc, v10, cats, _Log())
    eq(sorted(st.keys()), [1, 3], 'subcategory left out when its parent is hidden')
    v30 = views[30]
    tmpl = views[50]
    tmpl.noncontrolled = [FId(-1002)]   # template controls model V/G, not annotation
    tmpl.cat_hidden = set([3])
    v30.cat_hidden = set([1, 4])
    st = M.rv.read_category_state(doc, v30, cats, _Log())
    eq(sorted(st.keys()), [3, 4], 'model categories from the template, annotation from the view')
    eq(st[3], (True, u'MEP Plan'), 'template named')
    eq(st[4], (True, None), 'view-owned category not marked')


@check
def element_rows(M):
    doc, views = _model(M)
    v10 = views[10]
    v10.cat_hidden.add(1)
    row = M.rv.element_row(doc, FId(100), v10, {})
    eq(row['category'], u'Pipes', 'category')
    eq(row['warn'], u'1', 'category hidden here too is flagged')
    gone = M.rv.element_row(doc, FId(4242), v10, {})
    eq(gone['bad'], u'1', 'deleted element is red')


@check
def scanner_through_revit(M):
    doc, views = _model(M)
    note = FElem(900, FCat(9, u'Text Notes', 'Annotation'), hidden_in=[20], owner=20)
    doc.add(note)
    model = [doc.elems[k] for k in (100, 101, 102, 103, 200)]
    M.rv.model_candidates = lambda d, ids: model
    M.rv.owned_candidates = lambda d, vid, ids: [note] if vid.Value == 20 else []
    vlist = [{'key': 10, 'view': views[10]}, {'key': 20, 'view': views[20]}]
    s = M.rv.make_scanner(doc, vlist, [], _Log())
    s.step(5.0)
    eq(sorted(i.Value for i in s.results[10]), [100, 101, 102, 103], 'view 10')
    eq(sorted(i.Value for i in s.results[20]), [200, 900], 'view 20 incl. its own note')


# ---- shrink to taskbar --------------------------------------------------------

class _NS(object):
    def __init__(self, **k):
        self.__dict__.update(k)


NAN = float('nan')


def _is_nan(v):
    return isinstance(v, float) and v != v


class FakeEl(object):
    def __init__(self, name, parent=None, vis='Visible'):
        self.name = name
        self.Visibility = vis
        self.Parent = parent
        self.Children = None
        self.Height = NAN
        self.VerticalAlignment = 'Stretch'
        self.ActualHeight = 0.0

    def __repr__(self):
        return '<%s>' % self.name


class FakeWin(object):
    """Records every Top/Height it is given; clamps Height at MinHeight the
    way WPF does, so a MinHeight left in place vetoes the shrink."""

    def __init__(self):
        self._top = 100.0
        self._height = 800.0
        self.Left = 100.0
        self.Width = 1300.0
        self.MinHeight = 560.0
        self.SizeToContent = 'Height'
        self.tops = []
        self.heights = []
        self.activated = 0

    @property
    def Top(self):
        return self._top

    @Top.setter
    def Top(self, v):
        self._top = v
        self.tops.append(v)

    @property
    def Height(self):
        return self._height

    @Height.setter
    def Height(self, v):
        if v < self.MinHeight:
            v = self.MinHeight          # WPF clamps: MinHeight vetoes a shrink
        self._height = v
        self.heights.append(v)

    def Activate(self):
        self.activated += 1

    def DragMove(self):
        pass


class InstantTimer(object):
    """Runs its ticks at once, until stopped (or 500 ticks)."""

    def __init__(self, fn):
        self.fn = fn
        self.running = False
        self.ticks = 0

    def Start(self):
        self.running = True
        while self.running and self.ticks < 500:
            self.ticks += 1
            self.fn()

    def Stop(self):
        self.running = False


class ManualTimer(object):
    def __init__(self, fn):
        self.fn = fn
        self.running = False

    def Start(self):
        self.running = True

    def Stop(self):
        self.running = False

    def tick(self):
        if self.running:
            self.fn()


def _drawer_world(M, area=(0.0, 0.0, 1920.0, 1040.0), manual=False):
    M.ui.Visibility = _NS(Visible='Visible', Collapsed='Collapsed')
    M.ui.VerticalAlignment = _NS(Top='Top', Stretch='Stretch')
    M.ui.SizeToContent = _NS(Manual='Manual')
    M.ui.CornerRadius = lambda v: ('CR', v)
    M.ui.Point = lambda x, y: (x, y)
    win = FakeWin()
    root = FakeEl('RootGrid', parent=win)
    root.ActualHeight = 800.0
    frame = FakeEl('Frame', parent=root)
    overlay = FakeEl('ConfirmOverlay', parent=root, vis='Collapsed')
    grips = FakeEl('GripLayer', parent=root)
    root.Children = [frame, overlay, grips]
    dock = FakeEl('Dock', parent=frame)
    header = FakeEl('HeaderBar', parent=dock)
    header.ActualHeight = 40.0
    header.CornerRadius = 'orig'
    header.TranslatePoint = lambda pt, w: _NS(Y=1.0)
    footer = FakeEl('FooterBar', parent=dock)
    body = FakeEl('BodyGrid', parent=dock)
    dock.Children = [header, footer, body]
    button = _NS(Tag=None, ToolTip=None)
    clock = Clock(0.02)
    timers = []

    def make_timer(ms, fn):
        t = ManualTimer(fn) if manual else InstantTimer(fn)
        timers.append(t)
        return t, fn
    box = {'area': area}
    d = M.ui.WindowDrawer(win, header, root, button, grips, log=_Log(),
                          make_timer=make_timer, clock=clock,
                          area_of=lambda w: box['area'])
    return _NS(d=d, win=win, root=root, header=header, footer=footer, body=body,
               overlay=overlay, grips=grips, button=button, timers=timers, box=box)


@check
def drawer_math(M):
    c = M.core
    eq(c.ease_out(0), 0.0, 'ease starts at 0')
    eq(c.ease_out(1), 1.0, 'ease ends at 1')
    eq(c.ease_out(2), 1.0, 'ease clamps past the end')
    eq(round(c.ease_out(0.5), 4), 0.875, 'ease-out cubic: fast away, gentle landing')
    vals = [c.ease_out(i / 20.0) for i in range(21)]
    ok(all(b >= a for a, b in zip(vals, vals[1:])), 'ease never goes backwards')
    eq(c.bar_height(40, 1), 42.0, 'bar = header + frame both sides')
    eq(c.parked_top((0, 0, 1920, 1040), 42), 990.0, '8 above the taskbar')
    eq(c.parked_top((0, -1080, 1920, 1040), 42), -90.0, 'monitor above the primary one')
    eq(c.parked_top((1920, 30, 1920, 1010), 42), 990.0, 'taskbar at the top of a second screen')
    saved = (100, 100, 1300, 800)
    eq(c.expand_bounds(saved, (100, 990), (101, 990), 42, (0, 0, 1920, 1040)), saved,
       'a bar nudged a pixel goes straight back')
    eq(c.expand_bounds(saved, (100, 990), (300, 950), 42, (0, 0, 1920, 1040)),
       (300, 192, 1300, 800), 'a moved bar opens upward from where it sits')
    eq(c.expand_bounds(saved, (100, 990), (1500, 200), 42, (0, 0, 1920, 1040)),
       (620, 0, 1300, 800), 'kept on the screen')
    eq(c.expand_bounds((0, 0, 1300, 1200), (0, 990), (0, 500), 42, (0, 0, 1920, 1040)),
       (0, 0, 1300, 1040), 'never taller than the screen it opens on')


@check
def drawer_shrink_and_expand(M):
    w = _drawer_world(M)
    ok(w.d.toggle(), 'shrink starts')
    eq(w.d.state, 'parked', 'parked after the slide')
    eq(w.win.Top, 990.0, 'bar lands 8 above the taskbar')
    eq(w.win.Height, 42.0, 'only the header bar is left')
    ok(len(w.win.tops) > 5, 'it slides - not a jump ({0} frames)'.format(len(w.win.tops)))
    ok(all(b >= a for a, b in zip(w.win.tops, w.win.tops[1:])), 'the drawer only ever moves down')
    eq(w.win.MinHeight, 0.0, 'MinHeight relaxed so it can shrink')
    eq(w.win.SizeToContent, 'Manual', 'SizeToContent relaxed')
    for el in (w.footer, w.body, w.overlay, w.grips):
        eq(el.Visibility, 'Collapsed', el.name + ' parked with the window')
    eq(w.header.Visibility, 'Visible', 'header stays')
    eq(w.header.CornerRadius, ('CR', 6.0), 'bar rounded all round')
    eq(w.button.Tag, u'shrunk', 'button becomes the green up arrow')
    ok(_is_nan(w.root.Height) and w.root.VerticalAlignment == 'Stretch', 'layout unpinned on landing')
    ok(not w.timers[-1].running, 'timer stopped')
    eq(w.d.true_bounds(), (100.0, 100.0, 1300.0, 800.0), 'real size remembered while parked')

    ok(w.d.toggle(), 'expand starts')
    eq(w.d.state, 'open', 'open again')
    eq((w.win.Left, w.win.Top, w.win.Width, w.win.Height), (100.0, 100.0, 1300.0, 800.0),
       'back exactly where it was')
    ok(all(b <= a for a, b in zip(w.win.tops[-5:], w.win.tops[-4:])), 'the drawer opens upward')
    eq(w.win.MinHeight, 560.0, 'MinHeight put back')
    eq(w.win.SizeToContent, 'Height', 'SizeToContent put back')
    for el in (w.footer, w.body, w.grips):
        eq(el.Visibility, 'Visible', el.name + ' shown again')
    eq(w.overlay.Visibility, 'Collapsed', 'a closed prompt stays closed')
    eq(w.header.CornerRadius, 'orig', 'header corners put back')
    eq(w.button.Tag, u'', 'button back to shrink')
    ok(w.win.activated >= 1, 'window brought forward')
    ok(_is_nan(w.root.Height), 'layout unpinned after opening')


@check
def drawer_pins_layout_mid_slide(M):
    w = _drawer_world(M, manual=True)
    w.d.shrink()
    eq(w.root.Height, 800.0, 'layout pinned at full height for the slide')
    eq(w.root.VerticalAlignment, 'Top', 'pinned to the top, clipped by the window')
    eq(w.grips.Visibility, 'Collapsed', 'grips parked as the slide starts')
    eq(w.button.Tag, u'shrunk', 'arrow shows straight away')
    for _ in range(4):
        w.timers[-1].tick()
    ok(100.0 < w.win.Top < 990.0, 'mid slide')
    eq(w.root.Height, 800.0, 'still pinned mid slide')
    eq(w.footer.Visibility, 'Visible', 'body still drawn while it slides')
    ok(not w.d.toggle(), 'a second press mid slide is ignored')
    ok(not w.d.shrink(), 'and cannot restart it')
    eq(w.d.saved, (100.0, 100.0, 1300.0, 800.0), 'saved size not overwritten mid slide')
    w.d.restore_now()
    eq(w.d.state, 'open', 'restore_now from mid slide')
    eq((w.win.Top, w.win.Height, w.win.MinHeight), (100.0, 800.0, 560.0), 'restored at once')


@check
def drawer_moved_bar(M):
    w = _drawer_world(M)
    w.d.shrink()
    w.win.Left = 400.0
    w.win._top = 600.0                 # dragged up the screen
    w.d.expand()
    eq((w.win.Left, w.win.Top, w.win.Height), (400.0, 0.0, 800.0),
       'opens upward from the moved bar, kept on the screen')


@check
def drawer_second_monitor_above(M):
    w = _drawer_world(M, area=(0.0, -1080.0, 1920.0, 1040.0))
    w.win._top = -900.0
    w.d.shrink()
    eq(w.win.Top, -90.0, 'parks on the screen above, not the primary')
    w.d.expand()
    eq(w.win.Top, -900.0, 'and comes back there')


class _BrokenClock(object):
    """Reads once (the slide's start), then throws on every frame."""

    def __init__(self):
        self.reads = 0

    def __call__(self):
        self.reads += 1
        if self.reads > 1:
            raise RuntimeError('frame failed')
        return 0.0


@check
def drawer_bad_frame_lands(M):
    w = _drawer_world(M)
    w.d.clock = _BrokenClock()        # every frame throws
    w.d.shrink()
    eq(w.d.state, 'parked', 'a frame that throws lands the window at the end')
    eq((w.win.Top, w.win.Height), (990.0, 42.0), 'at the end state')
    ok(not w.timers[-1].running, 'and the timer is stopped')


@check
def drawer_header_clicks(M):
    w = _drawer_world(M)
    ok(not w.d.on_header_down(_NS(ClickCount=2)), 'open: header clicks are the window\'s own')
    w.d.shrink()
    ok(w.d.on_header_down(_NS(ClickCount=1)), 'parked: a click drags the bar')
    eq(w.d.state, 'parked', 'dragging does not open it')
    ok(w.d.on_header_down(_NS(ClickCount=2)), 'parked: double-click handled')
    eq(w.d.state, 'open', 'double-click opens it')


# =====================================================================
# Runner and selftest
# =====================================================================

def run_all(M, quiet=False):
    failed = []
    for fn in CHECKS:
        try:
            fn(M)
            if not quiet:
                print('PASS  ' + fn.__name__)
        except Exception as ex:
            failed.append((fn.__name__, ex))
            if not quiet:
                print('FAIL  {0}: {1}'.format(fn.__name__, ex))
                if not isinstance(ex, AssertionError):
                    traceback.print_exc()
    return failed


BREAKAGES = [
    ('uiv_core', 'st[2] = idx', 'st[2] = 0', 'scan progress inside a view lost'),
    ('uiv_core', 'if not change_templates:', 'if False:', 'templates changed without the tick'),
    ('uiv_core', "    if canvas in ('dark', 'light'):\n        return canvas",
     "    if False:\n        return canvas", 'Auto stops following the canvas'),
    ('uiv_core', 'if values.get(key) == old:', 'if False:', 'migration skipped'),
    ('uiv_core', "r['hidden_in'] += 1", "r['hidden_in'] = 1", 'category count wrong'),
    ('uiv_core', 'if only_hidden and not count:', 'if False:', 'toggle shows every view'),
    ('uiv_core', 'keep = set(k for k in bucket if k in still_hidden)', 'keep = set(bucket)',
     'ticks on unhidden elements survive'),
    ('uiv_core', 'if self.stamps and t == self.stamps[-1]:', 'if False:',
     'one click counted twice'),
    ('uiv_revit', 'still = elem is None or bool(elem.IsHidden(view))', 'still = False',
     'no read back'),
    ('uiv_revit', '    for i in ids:\n        k = eid_value(i)\n        t1, q1',
     '    for i in []:\n        k = eid_value(i)\n        t1, q1',
     'no one-at-a-time fallback after a refusal'),
    ('uiv_revit', "        refused[k] = (u'Held by ' + owner) if owner else u'Could not be borrowed'",
     "        continue", 'held views written anyway'),
    ('uiv_revit', 'src = t if (controlled and t is not None) else view', 'src = view',
     'template-controlled categories read from the view'),
    ('uiv_revit', "        elif parent in hidden_parents:\n            continue",
     "        elif False:\n            continue", 'subcategories of hidden parents listed'),
    ('uiv_core', '    return 1.0 - (1.0 - p) ** 3', '    return p', 'drawer slides linearly'),
    ('uiv_core', '    return top + height - margin - bar_h', '    return height - margin - bar_h',
     'bar parks on the wrong screen when one sits above the primary'),
    ('uiv_core', '    if not bar_moved(parked, now):', '    if True:', 'a moved bar jumps back home'),
    ('uiv_ui', '            w.MinHeight = self.saved_min', '            w.MinHeight = 0.0',
     'MinHeight never put back'),
    ('uiv_ui', '        self.grips.Visibility = Visibility.Collapsed\n', '',
     'grips left over the bar during the slide'),
    ('uiv_ui', '        self._pin(self.root.ActualHeight)\n', '', 'layout squashed every frame'),
    ('uiv_ui', '        self._unpin()\n        self.parked_at', '        self.parked_at',
     'layout left pinned after landing'),
    ('uiv_ui', '        self.parts = [(el, el.Visibility) for el in self._parts_to_park()]',
     '        self.parts = [(el, Visibility.Visible) for el in self._parts_to_park()]',
     'a closed prompt comes back open'),
    ('uiv_ui', "        if self.state != 'open' and self.saved is not None:", '        if False:',
     'closing parked saves the bar size'),
    ('uiv_ui', "        if self.state != 'open':\n            return False\n        w = self.window\n        try:\n            area",
     "        w = self.window\n        try:\n            area", 'a second press mid slide restarts it'),
    ('uiv_ui', "            self._say(u'Drawer frame failed - landing at the end: ' + traceback.format_exc())\n            self._finish()",
     "            pass", 'a frame that throws strands the window'),
    ('uiv_ui', "        self.button.Tag = u'shrunk'", "        self.button.Tag = u''", 'no green arrow'),
    ('uiv_ui', "            if e.ClickCount == 2:\n                self.expand()", "            if False:\n                self.expand()",
     'double-click on the bar does nothing'),
    ('uiv_ui', "            value = getattr(mgr, 'CurrentCanvasTheme', None)\n            if value is not None:",
     "            value = getattr(mgr, 'CurrentCanvasTheme', None)\n            if value:",
     'UITheme.Dark (0) read as a failure'),
]


def selftest():
    print('Clean run first:')
    clean = run_all(load(), quiet=True)
    if clean:
        print('  the clean code fails - fix that first: ' + ', '.join(n for n, _ in clean))
        return 1
    print('  all {0} checks pass'.format(len(CHECKS)))
    missed = 0
    for mod, old, new, what in BREAKAGES:
        try:
            M = load((mod, old, new))
        except Exception as ex:
            print('BAD   breakage did not apply ({0}): {1}'.format(what, ex))
            missed += 1
            continue
        failed = run_all(M, quiet=True)
        if failed:
            print('CAUGHT  {0:55s} by {1}'.format(what, failed[0][0]))
        else:
            print('MISSED  ' + what)
            missed += 1
    load()
    print('{0} breakages, {1} missed'.format(len(BREAKAGES), missed))
    return 1 if missed else 0


def main(argv):
    if '--selftest' in argv:
        return selftest()
    failed = run_all(load())
    print('{0} checks, {1} failed'.format(len(CHECKS), len(failed)))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
