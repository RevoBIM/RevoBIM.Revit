# -*- coding: utf-8 -*-
"""Clash Analysis - logic bench. Plain CPython, run from this folder:

    python bench_logic.py              every check against the tool
    python bench_logic.py --selftest   patch the tool on purpose, once per
                                       patch, and prove a check fails

Pure rules come from ca_core; the read-back helpers, the ExternalEvent
runner and the box-mode clash test are loaded against bench_stubs.
"""
from __future__ import print_function

import importlib
import io
import os
import random
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CHECKS = []


def check(fn):
    CHECKS.append(fn)
    return fn


class Ctx(object):
    def __init__(self, root):
        sys.path.insert(0, HERE)
        import bench_stubs
        sys.path.remove(HERE)
        self.stubs = bench_stubs
        bench_stubs.uninstall()
        bench_stubs.install()
        sys.path.insert(0, root)
        try:
            self.core = importlib.import_module('ca_core')
            self.rv = importlib.import_module('ca_revit')
            self.jobs = importlib.import_module('ca_jobs')
            self.ui = importlib.import_module('ca_ui')
        finally:
            sys.path.remove(root)

    def close(self):
        self.stubs.uninstall()


def eq(got, want, what):
    if got != want:
        raise AssertionError('{0}: got {1!r}, want {2!r}'.format(what, got, want))


def near(got, want, what, tol=1e-6):
    if isinstance(want, (tuple, list)):
        for g, w in zip(got, want):
            near(g, w, what, tol)
        return
    if abs(got - want) > tol:
        raise AssertionError('{0}: got {1!r}, want {2!r}'.format(what, got, want))


def true(value, what):
    if not value:
        raise AssertionError(what)


# ======================================================================
# names and comments
# ======================================================================

@check
def group_names(c):
    core = c.core
    eq(core.clash_group_name((2026, 11, 13, 8, 39), u'L02 Tray vs Steel'),
       u'CLASH-2026_11_13_08-39-L02 Tray vs Steel', 'group name')
    eq(core.clash_group_name((2026, 1, 2, 23, 5), u'A:B {c}|d'),
       u'CLASH-2026_01_02_23-05-A-B -c--d', 'forbidden characters')
    eq(core.clash_group_name((2026, 1, 2, 3, 4), u'  '),
       u'CLASH-2026_01_02_03-04-Clash', 'blank name')
    p = core.parse_clash_group_name(u'CLASH-2026_11_13_08-39-L02 Tray vs Steel (2)')
    eq(p['stamp'], (2026, 11, 13, 8, 39), 'parsed stamp')
    eq(p['clash'], u'L02 Tray vs Steel', 'unique suffix dropped')
    eq(p['display_date'], u'13/11/2026 08:39', 'display date')
    eq(core.parse_clash_group_name(u'CLASH-2026_13_01_08-39-x'), None, 'month 13')
    eq(core.parse_clash_group_name(u'Model Group 1'), None, 'other group')
    eq(core.parse_clash_group_name(u'CLASH-2026_11_13_08_39-x'), None, 'wrong separator')
    eq(core.unique_name(u'G', [u'g', u'G (2)']), u'G (3)', 'unique name')
    # 1.3.0: one group per floor, level code after the minutes
    eq(core.clash_group_name((2026, 11, 13, 12, 49), u'Tray vs Steel', u'L02'),
       u'CLASH-2026_11_13_12-49_L02-Tray vs Steel', 'floor group name')
    eq(core.clash_group_name((2026, 11, 13, 12, 49), u'T', u'L 0-2'),
       u'CLASH-2026_11_13_12-49_L02-T', 'level code cannot break the name')
    p = core.parse_clash_group_name(u'CLASH-2026_11_13_12-49_GF-Tray-vs-Steel (2)')
    eq((p['level'], p['clash']), (u'GF', u'Tray-vs-Steel'), 'floor group parsed')
    p = core.parse_clash_group_name(u'CLASH-2026_11_13_12-49-Tray-vs-Steel')
    eq((p['level'], p['clash']), (u'', u'Tray-vs-Steel'), 'pre-1.3 group still parses')
    p = core.parse_clash_group_name(core.clash_group_name((2026, 1, 2, 3, 4), u'X', u'B01'))
    eq((p['stamp'], p['level'], p['clash']), ((2026, 1, 2, 3, 4), u'B01', u'X'),
       'name round trip')


@check
def level_codes(c):
    core = c.core
    for name, code in ((u'L02 - First Floor', u'L02'), (u'Level 2', u'L02'),
                       (u'Level 02', u'L02'), (u'Level -1', u'B01'),
                       (u'Ground Floor', u'GF'), (u'GF - Ground Floor', u'GF'),
                       (u'Lower Ground Floor', u'LG'), (u'Basement 2', u'B2'),
                       (u'B1', u'B1'), (u'3rd Floor', u'L03'),
                       (u'Second Floor', u'L02'), (u'Roof', u'RF'),
                       (u'Mezzanine', u'MZ'), (u'Top of Steel', u'TOS'),
                       (u'Level 00 Ground', u'L00')):
        eq(core.level_abbreviation(name), code, 'abbreviation of ' + name)
    codes = core.level_codes([u'Level 1', u'Level 01', u'Roof', u'Ground'])
    eq(codes[u'Roof'], u'RF', 'unique code kept')
    eq((codes[u'Level 1'], codes[u'Level 01']), (u'Level1', u'Level01'),
       'shared code: each falls back to its full name')
    eq(len(set(v.lower() for v in codes.values())), 4, 'every code different')
    eq(all(u'-' not in v and u' ' not in v for v in codes.values()), True,
       'codes safe in a group name')
    codes = core.level_codes([u'L1', u'L 1'])
    eq(len(set(v.lower() for v in codes.values())), 2, 'clash of full names too')


@check
def already_placed(c):
    core = c.core
    tol = core.mm_to_ft(core.DUPLICATE_MM)
    idx = core.PointIndex([(0.0, 0.0, 0.0), (10.0, 10.0, 3.0)], tol)
    eq(idx.near((0.0, 0.0, 0.0)), True, 'same spot')
    eq(idx.near((tol * 0.9, 0.0, 0.0)), True, 'just inside')
    eq(idx.near((tol * 0.7, tol * 0.7, 0.0)), True, 'inside, across a cell edge')
    eq(idx.near((tol * 1.1, 0.0, 0.0)), False, 'just outside')
    eq(idx.near((tol * 0.8, tol * 0.8, 0.0)), False, 'outside on the diagonal')
    eq(idx.near((-tol * 0.5, -tol * 0.5, -tol * 0.5)), True, 'negative side')
    eq(idx.near((10.0, 10.0, 3.0 + tol * 2)), False, 'a floor above')
    idx.add((5.0, 5.0, 5.0))
    eq(idx.near((5.0, 5.0, 5.0)), True, 'added during the run')
    eq(core.PointIndex([], tol).near((0.0, 0.0, 0.0)), False, 'nothing placed yet')


@check
def comments(c):
    core = c.core
    a = {'category': u'Cable Trays', 'family': u'Cable Tray with Fittings',
         'type': u'BGL_CT_LV Ladder'}
    b = {'category': u'Structural Framing', 'family': u'UB-Universal Beam',
         'type': u'305x165x40UB'}
    eq(core.comment_text(a, b), u'Cable Tray with Fittings : BGL_CT_LV Ladder-vs-'
       u'UB-Universal Beam : 305x165x40UB', 'family : type')
    eq(core.comment_text(a, b, 'family'),
       u'Cable Tray with Fittings-vs-UB-Universal Beam', 'family')
    eq(core.comment_text(a, b, 'category'), u'Cable Trays-vs-Structural Framing',
       'category')
    same = {'category': u'Walls', 'family': u'Basic Wall', 'type': u'Basic Wall'}
    eq(core.describe(same, 'family_type'), u'Basic Wall', 'type equal to family')
    eq(core.split_comment(u'A : x-vs-B : y'), (u'A : x', u'B : y'), 'split')
    rep = core.comment_report([u'A-vs-B', u'C-vs-D', u'A-vs-B', u'', None])
    eq(rep, [(u'(blank)', 2), (u'A-vs-B', 2), (u'C-vs-D', 1)], 'comment report')


# ======================================================================
# geometry
# ======================================================================

def _brute(core, a, b, pad):
    return sorted((i, j) for i, x in enumerate(a) for j, y in enumerate(b)
                  if core.boxes_overlap(x, y, pad))


@check
def pair_finding(c):
    core = c.core
    rnd = random.Random(7)

    def box():
        x, y, z = rnd.uniform(-60, 60), rnd.uniform(-60, 60), rnd.uniform(-10, 30)
        return (x, y, z, x + rnd.uniform(0.1, 6), y + rnd.uniform(0.1, 6),
                z + rnd.uniform(0.1, 2))
    a = [box() for i in range(250)]
    b = [box() for i in range(250)]
    b.append((-500.0, -500.0, -1.0, 500.0, 500.0, 0.5))   # a slab: the big list
    a.append((-0.5, -0.5, -400.0, 0.5, 0.5, 400.0))       # a riser over every cell
    for pad in (0.0, 0.3):
        eq(sorted(core.candidate_pairs(a, b, pad)), _brute(core, a, b, pad),
           'grid matches brute force (pad {0})'.format(pad))
    eq(core.candidate_pairs([], b), [], 'empty side')


@check
def boxes_and_points(c):
    core = c.core
    eq(core.overlap_box((0, 0, 0, 2, 2, 2), (1, 1, 1, 3, 3, 3)), (1, 1, 1, 2, 2, 2),
       'overlap box')
    eq(core.overlap_box((0, 0, 0, 1, 1, 1), (2, 2, 2, 3, 3, 3)), None, 'apart')
    ft = core.mm_to_ft
    thin = (0, 0, 0, 1, 1, ft(3))
    true(core.is_touching(thin, ft(5)), '3 mm overlap is touching at 5 mm')
    true(not core.is_touching((0, 0, 0, 1, 1, ft(20)), ft(5)), '20 mm is a clash')
    true(core.is_touching(None, ft(5)), 'no box is touching')
    rot = core.transform_box((1, 0, 0, 3, 1, 1), lambda p: (-p[1], p[0], p[2]))
    near(rot, (-1, 1, 0, 0, 3, 1), 'box turned 90 degrees')
    near(core.weighted_centroid([((0, 0, 0), 1.0), ((4, 0, 0), 3.0)]), (3, 0, 0),
         'weighted centroid')
    eq(core.weighted_centroid([((1, 1, 1), 0.0)]), None, 'no weight')
    near(core.move_to_centre((5, 5, 5), (4, 6, 5)), (1, -1, 0), 'move to centre')
    near(core.ft_to_mm(core.mm_to_ft(123.0)), 123.0, 'mm round trip')


@check
def levels(c):
    core = c.core
    lv = [('L1', 10.0), ('L0', 0.0), ('L2', 20.0)]
    eq(core.choose_level(lv, -3.0), 'L0', 'below every level')
    eq(core.choose_level(lv, 10.0), 'L1', 'on a level')
    eq(core.choose_level(lv, 19.99), 'L1', 'between levels')
    eq(core.choose_level(lv, 99.0), 'L2', 'above every level')
    eq(core.choose_level([], 1.0), None, 'no levels')
    eq(core.marker_level(None, lv, 15.0), 'L1', 'no view level: closest below')
    eq(core.marker_level('L2', lv, 15.0), 'L2', 'floor plan run: the view level')
    eq(core.marker_level('L0', lv, -5.0), 'L0', 'view level even below it')


@check
def workset_offer(c):
    core = c.core
    sug = core.SUGGESTED_WORKSET
    eq(sug, u'Z_BIM_Clash_Sphere', 'suggested workset name')
    e = core.workset_entries([u'Workset1', u'Shared Levels and Grids'])
    eq(e[0], ('create', sug, core.ws_create_tag(sug)), 'suggestion offered first')
    eq(e[1][0], 'custom', 'Custom workset under it')
    eq([x[1] for x in e[2:]], [u'Workset1', u'Shared Levels and Grids'], 'then the model')
    e = core.workset_entries([u'Workset1', u'z_bim_clash_sphere'])
    eq([x[0] for x in e], ['custom', 'existing', 'existing'],
       'suggestion hidden when the model has it (any case)')
    e = core.workset_entries([u'Workset1'], [u'MEP Clash', u'mep clash', u'Workset1'])
    eq([(x[0], x[1]) for x in e[:3]],
       [('create', sug), ('create', u'MEP Clash'), ('custom', u'Custom workset...')],
       'custom names to create: once each, never one the model has')
    eq(core.parse_ws_tag(core.ws_create_tag(u'A')), ('create', u'A'), 'create tag')
    eq(core.parse_ws_tag(core.WS_CUSTOM), ('custom', u''), 'custom tag')
    eq(core.parse_ws_tag(u'Workset1'), ('existing', u'Workset1'), 'existing tag')
    e = core.workset_entries([u'Workset1'])
    eq(core.default_ws_tag(u'', e), core.ws_create_tag(sug), 'default: suggestion')
    eq(core.default_ws_tag(u'workset1', e), u'Workset1', 'saved choice kept')
    e = core.workset_entries([u'Workset1', sug])
    eq(core.default_ws_tag(u'Gone', e), sug, 'saved gone: the suggested one')
    eq(core.check_workset_name(u'  MEP   Clash ', [u'W'])[0:2], (u'MEP Clash', None), 'tidied')
    eq(core.check_workset_name(u'', [])[1] is not None, True, 'blank refused')
    eq(core.check_workset_name(u'a:b', [])[1] is not None, True, 'forbidden refused')
    eq(core.check_workset_name(u'WORKSET1', [u'Workset1'])[2], u'Workset1',
       'existing name: use it, create nothing')


@check
def schedule_width(c):
    core = c.core
    eq(core.SCHEDULE_NAME, u'BIM_Clash Analysis Schedule', 'schedule name')
    eq(core.comment_column_mm([]), core.SCHEDULE_EMPTY_MM, 'no comments yet')
    eq(core.comment_column_mm([u'', u'   ']), core.SCHEDULE_EMPTY_MM, 'blank comments')
    eq(core.comment_column_mm([u'A-vs-B']), core.SCHEDULE_MIN_MM, 'short: minimum')
    longest = u'Cable Trays : Ladder 300-vs-Structural Framing : UB 305x165x40'
    want = len(longest) * core.SCHEDULE_MM_PER_CHAR + core.SCHEDULE_PAD_MM
    eq(core.comment_column_mm([u'Ducts-vs-Walls', longest, u'x']), want,
       'longest comment decides')
    eq(core.comment_column_mm([u'x' * 500]), core.SCHEDULE_MAX_MM, 'capped')
    eq(core.comment_column_mm([longest]) >= len(longest) * 1.8, True,
       'at least 1.8 mm a character so 2.5 mm text is not cut')


@check
def results(c):
    core = c.core

    def side(uid, fam):
        return {'uid': uid, 'category': u'C', 'family': fam, 'type': u''}
    clashes = [{'a': side('H:1', u'Tray'), 'b': side('L:9', u'Beam')},
               {'a': side('H:2', u'Tray'), 'b': side('L:9', u'Beam')},
               {'a': side('L:9', u'Beam'), 'b': side('H:1', u'Tray')},
               {'a': side('H:3', u'Duct'), 'b': side('L:8', u'Column')}]
    eq(core.pair_key('b', 'a'), core.pair_key('a', 'b'), 'pair key symmetric')
    eq(len(core.dedupe(clashes)), 3, 'same two elements counted once')
    eq(core.summarise(core.dedupe(clashes))[0], (u'Tray', u'Beam', 2), 'most first')


# ======================================================================
# the category / family tree
# ======================================================================

@check
def catalog_tree(c):
    core = c.core
    cat = {u'Cable Trays': {u'Tray A': 10, u'Tray B': 5},
           u'Structural Framing': {u'UB': 7}}
    t = core.CatalogTree(cat, [u'Structural Framing|*', u'Pipes|*'])
    eq(t.cat_state(u'Structural Framing'), True, 'whole category ticked')
    eq(t.cat_state(u'Cable Trays'), False, 'nothing ticked')
    t.toggle_family(u'Cable Trays', u'Tray A')
    eq(t.cat_state(u'Cable Trays'), None, 'part ticked')
    t.toggle_category(u'Cable Trays')
    eq(t.cat_state(u'Cable Trays'), True, 'part -> all')
    t.toggle_category(u'Cable Trays')
    eq(t.cat_state(u'Cable Trays'), False, 'all -> none')
    t.toggle_family(u'Cable Trays', u'Tray B')
    eq(t.chosen_keys(), [u'Cable Trays|Tray B', u'Pipes|*', u'Structural Framing|*'],
       'chosen keys collapse whole categories and keep an unloaded model')
    true(core.key_matches(set(t.chosen_keys()), u'Pipes', u'Anything'), 'cat|* matches')
    true(not core.key_matches(set(t.chosen_keys()), u'Cable Trays', u'Tray A'),
         'unticked family')
    rows = t.rows()
    eq([r['kind'] for r in rows], ['cat', 'cat'], 'categories arrive collapsed')
    t.toggle_collapse(u'Cable Trays')
    eq(len(t.rows()), 4, 'opened category lists its families')
    t.set_catalog(core.merge_catalogs([cat, {u'Ducts': {u'Rect': 3}}]))
    true(u'Cable Trays' not in t.collapsed, 'an opened category stays open')
    true(u'Ducts' in t.collapsed, 'a new category arrives collapsed')
    found = t.rows(u'ub')
    eq([(r['kind'], r['label']) for r in found],
       [('cat', u'Structural Framing'), ('fam', u'UB')], 'search opens matches')
    eq(core.merge_catalogs([{u'A': {u'x': 1}}, {u'A': {u'x': 2, u'y': 1}}]),
       {u'A': {u'x': 3, u'y': 1}}, 'merged counts')


@check
def rename_names(c):
    core = c.core
    have = [u'L02 Tray vs Steel', u'Risers', u'a_b']
    eq(core.check_test_name(u'  Level 02   Tray ', u'Risers', have),
       (u'Level 02 Tray', None), 'tidied and accepted')
    eq(core.check_test_name(u'', u'Risers', have)[1] is not None, True, 'blank refused')
    true(u'already a clash test' in (core.check_test_name(
        u'l02 tray VS steel', u'Risers', have)[1] or u''),
         'another test, different case, refused as a duplicate name')
    true(core.check_test_name(u'a/b', u'Risers', have)[1],
         'a name that saves over another file is refused')
    eq(core.check_test_name(u'RISERS', u'Risers', have), (u'RISERS', None),
       'a change of case on itself is allowed')
    true(core.check_test_name(u'x||y', u'Risers', have)[1], 'list separator refused')
    eq(core.rename_in_order([u'A', u'B', u'C'], u'B', u'Z'), [u'A', u'Z', u'C'],
       'run order keeps its place')
    eq(core.rename_in_order([u'Z', u'B'], u'B', u'Z'), [u'Z'], 'no duplicate entry')


# ======================================================================
# saved tests and settings
# ======================================================================

@check
def saved_tests(c):
    core = c.core
    t = core.new_test(u'L02 Tray vs Steel')
    t['a_models'] = [u'HOST', u'LINK:Structure.rvt']
    t['a_keys'] = [u'Cable Trays|*']
    t['b_keys'] = [u'Structural Framing|UB', u'Structural Columns|*']
    t['touch_mm'] = 12.5
    t['skip_connected'] = False
    t['scope'] = u'view'
    t['last_count'] = 23
    back = core.parse_test(core.dump_test(t))
    for key in core.TEST_DEFAULTS:
        eq(back[key], t[key], 'round trip ' + key)
    damaged = core.parse_test(u'name=X\ntouch_mm=abc\nmode=psychic\nnonsense=1\n')
    eq(damaged['touch_mm'], core.TEST_DEFAULTS['touch_mm'], 'bad number falls back')
    eq(damaged['mode'], u'solid', 'unknown mode falls back')
    eq(damaged['scope'], u'view', 'no scope saved: current view')
    eq(core.parse_test(u'name=X\nscope=galaxy\n')['scope'], u'view',
       'unknown scope falls back')
    eq(core.parse_test(u'name=X\nscope=project\n')['scope'], u'project',
       'whole project kept')
    eq(core.new_test()['scope'], u'view', 'new tests run on the current view')
    eq(core.RUN_SCOPES[0][0], u'view', 'Current view listed first')
    eq(damaged['name'], u'X', 'good values survive')
    eq(core.project_key(u'Model_MEP_drew', u'Autodesk Docs://Proj/Model_MEP.rvt'),
       u'Model_MEP', 'central name wins over the local title')
    eq(core.project_key(u'Job 1.rvt'), u'Job 1', 'title fallback')
    eq(core.safe_filename(u'a/b:c?'), u'a_b_c_', 'safe file name')


@check
def settings(c):
    core = c.core
    s = core.parse_settings(u'theme=purple\ndebug=maybe\nwin_width=900\nzzz=1\n'
                            u'comment_format=family\n')
    eq(s['theme'], u'follow', 'bad theme falls back')
    eq(s['debug'], True, 'bad flag falls back')
    eq(s['win_width'], 900.0, 'good value kept')
    eq(s['comment_format'], u'family', 'comment format kept')
    eq(core.parse_settings(core.dump_settings(s)), s, 'settings round trip')
    saved = dict(core.MIGRATIONS)
    try:
        core.MIGRATIONS[99] = {'debug': False}
        eq(core.parse_settings(u'settings_version=1\ndebug=1\n')['debug'], False,
           'migration applies to an older file')
    finally:
        core.MIGRATIONS.clear()
        core.MIGRATIONS.update(saved)


# ======================================================================
# theme
# ======================================================================

@check
def theme(c):
    core = c.core
    eq(core.resolve_theme(u'follow', 0), u'dark', 'UITheme.Dark is 0, not a failed read')
    eq(core.resolve_theme(u'follow', 1), u'light', 'canvas light')
    eq(core.resolve_theme(u'follow', None), u'dark', 'unreadable canvas')
    eq(core.resolve_theme(u'light', 0), u'light', 'explicit light')
    eq([core.next_theme(x) for x in core.THEMES], [u'dark', u'light', u'follow'],
       'chip cycle')
    eq(core.theme_chip_label(u'follow', u'dark'), u'Auto (Dark)', 'chip label')
    for name, pal in (('dark', core.PALETTE_DARK), ('light', core.PALETTE_LIGHT)):
        for bg in ('WindowBg', 'CardBg', 'FieldBg', 'BarBg', 'HeadBg', 'SelBg', 'HoverBg'):
            true(core.contrast(pal['Text'], pal[bg]) >= 4.5,
                 '{0}: Text on {1} under 4.5:1'.format(name, bg))
        for bg in ('WindowBg', 'CardBg', 'FieldBg', 'BarBg'):
            true(core.contrast(pal['Muted'], pal[bg]) >= 4.5,
                 '{0}: Muted on {1} under 4.5:1'.format(name, bg))
        for bg in ('Green', 'Red'):
            true(core.contrast(pal['OnAccent'], pal[bg]) >= 3.0,
                 '{0}: button text on {1} under 3:1'.format(name, bg))


@check
def filters_and_egg(c):
    core = c.core
    eq(core.sql_like_escape(u"O'Brien [x] 5%"), u"O''Brien [[]x[]] 5[%]", 'escape')
    eq(core.row_filter(u'  '), u'', 'blank filter')
    eq(core.row_filter(u'Tray'), u"[search] LIKE '%tray%'", 'filter text')
    true(core.egg_ready([0, 600, 600, 1500]), 'three slow clicks (repeat ignored)')
    true(not core.egg_ready([0, 100, 700]), 'too quick')
    true(not core.egg_ready([0, 3000, 3500]), 'too slow')


# ======================================================================
# the drawer
# ======================================================================

class FakeTimer(object):
    """A timer that never ticks inside Start(), like a DispatcherTimer.
    Anything a tick lets escape is recorded, the way the dispatcher would
    receive it."""
    escaped = []

    def __init__(self, ms, cb):
        self.cb = cb
        self.running = False

    def Start(self):
        self.running = True

    def Stop(self):
        self.running = False

    def pump(self, limit=100):
        n = 0
        while self.running and n < limit:
            try:
                self.cb()
            except Exception as ex:
                FakeTimer.escaped.append(ex)
                return
            n += 1


class FakeHost(object):
    def __init__(self, wa=(0.0, 0.0, 1920.0, 1040.0), fail_frame=None):
        self.top, self.height = 100.0, 700.0
        self.wa = wa
        self.fail_frame = fail_frame
        self.frames = 0
        self.released = 0
        self.prepared = []
        self.finished_with = []

    def bounds(self):
        return (50.0, self.top, 1000.0, self.height)

    def work_area(self):
        return self.wa

    def header_height(self):
        return 46.0

    def set_bounds(self, top, height):
        self.frames += 1
        if self.fail_frame is not None and self.frames == self.fail_frame:
            raise RuntimeError('frame failed')
        self.top, self.height = top, height

    def prepare(self, parking):
        self.prepared.append(parking)

    def release(self):
        self.released += 1

    def finished(self, parked):
        self.finished_with.append(parked)


def _machine(c, host):
    timers = []

    def factory(ms, cb):
        t = FakeTimer(ms, cb)
        timers.append(t)
        return t
    return c.core.DrawerMachine(host, factory), timers


@check
def drawer_maths(c):
    core = c.core
    eq(core.parked_bounds((0, 0, 1920, 1040), 46), (1040 - 46 - 8, 46), 'parked bar')
    # a second monitor above the primary has a negative top
    eq(core.parked_bounds((0, -1080, 1920, 1040), 46)[0], -1080 + 1040 - 46 - 8.0,
       'monitor above the primary')
    wa = (0, 0, 1920, 1040)
    eq(core.reopen_bounds((100, 700), 986, 986, 46, wa), (100, 700), 'unmoved bar')
    eq(core.reopen_bounds((100, 700), 800, 986, 46, wa), (800 + 46 - 700, 700),
       'moved bar opens upward from where it sits')
    eq(core.reopen_bounds((100, 700), 300, 986, 46, wa), (0, 700), 'kept on screen')
    near(core.ease(1.0), 1.0, 'ease end')
    near(core.frame_bounds((0, 100), (50, 0), 14, 14), (50, 0), 'last frame')


@check
def drawer_cycle(c):
    FakeTimer.escaped = []
    host = FakeHost()
    m, timers = _machine(c, host)
    m.toggle()
    true(m.sliding, 'sliding after toggle')
    true(not m.toggle(), 'a second toggle mid slide is ignored')
    timers[-1].pump()
    true(m.parked and not m.sliding, 'parked')
    eq((host.top, host.height), (1040 - 46 - 8.0, 46.0), 'landed on the bar')
    eq(host.released, 1, 'animations released on landing')
    m.toggle()
    timers[-1].pump()
    true(not m.parked and not m.sliding, 'reopened')
    eq((host.top, host.height), (100.0, 700.0), 'back where it was')
    eq(host.released, 2, 'released again')
    eq(host.finished_with, [True, False], 'finished told both ways')
    eq(FakeTimer.escaped, [], 'nothing escaped a tick')


class SectionHost(object):
    def __init__(self, full=300.0, shown=300.0, fail_frame=None):
        self.full = full
        self.h = shown
        self.angle = None
        self.frames = 0
        self.fail_frame = fail_frame
        self.landed = []
        self.heights = []

    def current(self):
        return self.h

    def open_target(self):
        return self.full

    def begin(self):
        pass

    def apply(self, h, angle):
        self.frames += 1
        if self.fail_frame is not None and self.frames == self.fail_frame:
            raise ValueError('frame broke')
        self.h = h
        self.angle = angle
        self.heights.append(h)

    def land(self, is_open):
        self.landed.append(is_open)
        self.h = self.full if is_open else 0.0
        self.angle = 0.0 if is_open else -90.0


@check
def sections(c):
    core = c.core
    FakeTimer.escaped = []
    timers = []

    def factory(ms, cb):
        t = FakeTimer(ms, cb)
        timers.append(t)
        return t
    host = SectionHost()
    m = core.SectionMachine(host, factory, is_open=True)
    true(m.toggle(), 'collapse starts')
    true(m.sliding and not m.is_open, 'sliding shut')
    true(not m.toggle(), 'a click mid slide is ignored')
    timers[-1].pump()
    true(not m.sliding, 'landed')
    eq(host.landed, [False], 'landed shut')
    eq(host.heights == sorted(host.heights, reverse=True), True, 'height only falls')
    eq(host.heights[0], 300.0, 'starts from the open height')
    eq(len(host.heights), core.DRAWER_FRAMES, 'one slide is DRAWER_FRAMES frames long')
    true(all(0.0 <= h <= 300.0 for h in host.heights), 'never overshoots')
    m.toggle()
    timers[-1].pump()
    eq(host.landed, [False, True], 'opened again')
    eq((host.h, host.angle), (300.0, 0.0), 'fully open, chevron down')
    eq(core.chevron_angle(True, 0.0), core.CHEVRON_SHUT, 'opening starts turned')
    eq(core.chevron_angle(False, 1.0), core.CHEVRON_SHUT, 'shutting ends turned')
    eq(core.chevron_angle(True, 1.0), core.CHEVRON_OPEN, 'opening ends down')
    eq(m.set_open(True), False, 'already open: nothing to do')
    # a frame that fails still lands, and nothing escapes to the dispatcher
    host2 = SectionHost(fail_frame=4)
    m2 = core.SectionMachine(host2, factory, is_open=True)
    m2.toggle()
    timers[-1].pump()
    eq(FakeTimer.escaped, [], 'nothing escaped a tick')
    true(not m2.sliding and host2.landed == [False], 'a failing frame still lands shut')
    # no timer at all: lands straight away
    def broken(ms, cb):
        raise RuntimeError('no timer')
    m3 = core.SectionMachine(SectionHost(), broken, is_open=True)
    m3.toggle()
    true(not m3.sliding and not m3.is_open, 'no timer: lands at once')


@check
def model_categories(c):
    core = c.core
    ok = core.is_model_category
    eq(ok(u'Ducts', True, False, True), True, 'Ducts listed')
    eq(ok(u'Cable Trays', True, False, True), True, 'Cable Trays listed')
    eq(ok(u'<Room Separation>', True, True, True), False, 'line style out')
    eq(ok(u'<Room Separation>', True, False, True), False, '<named> out')
    eq(ok(u'Site plan.dwg', False, False, True), False, 'import category out')
    eq(ok(u'Survey.dwg', True, False, True), False, 'named like a file out')
    eq(ok(u'Survey.DXF 2', True, False, True), False, 'any case, with a suffix')
    eq(ok(u'Walls', True, False, False), False, 'not a model category')
    eq(ok(u'Hidden Lines', True, True, True), False, 'sub-category out')
    eq(ok(u'My Category', False, False, True), False, 'user category out')
    eq(ok(u'', True, False, True), False, 'blank out')
    eq(core.models_list_height() >= 7 * 22, True, 'shows seven models')


@check
def isolate_choice(c):
    core = c.core
    eq(core.isolate_here(7, 7), True, 'plan on the group level: isolate here')
    eq(core.isolate_here(8, 7), False, 'plan on another floor: pick a plan')
    eq(core.isolate_here(None, 7), False, '3D / section / sheet: pick a plan')
    eq(core.isolate_here(None, None), False, 'unknown level: pick a plan')
    eq(core.most_common([3, 5, 5, None, 3, 5]), 5, 'most spheres decide the level')
    eq(core.most_common([3, 5]), 3, 'tie: first seen')
    eq(core.most_common([None]), None, 'no level')
    views = [{'name': u'L02 - Mechanical', 'level': u'Level 02', 'level_key': 2},
             {'name': u'L01 - Mechanical', 'level': u'Level 01', 'level_key': 1},
             {'name': u'L02 - Electrical', 'level': u'Level 02', 'level_key': 2},
             {'name': u'Roof Plan', 'level': u'Roof', 'level_key': 9}]
    got = [v['name'] for v in core.plan_choices(views, u'', 2)]
    eq(got[:2], [u'L02 - Electrical', u'L02 - Mechanical'], 'group level first, by name')
    eq(len(got), 4, 'every plan when not limited')
    got = [v['name'] for v in core.plan_choices(views, u'', 2, True)]
    eq(got, [u'L02 - Electrical', u'L02 - Mechanical'], 'only the group level')
    got = [v['name'] for v in core.plan_choices(views, u'mech level 01', 2)]
    eq(got, [u'L01 - Mechanical'], 'every word, name or level, any case')
    got = [v['name'] for v in core.plan_choices(views, u'roof', 2, True)]
    eq(got, [], 'search inside the level filter')
    got = [v['name'] for v in core.plan_choices(views, u'', None, True)]
    eq(len(got), 4, 'no group level: the filter cannot hide everything')


@check
def review_status(c):
    core = c.core
    store = {}
    eq(core.review_state(store, u'a'), u'not', 'red until reviewed')
    eq(core.after_zoom(u'not'), u'reviewed', 'zoom turns red amber')
    eq(core.after_zoom(u'ok'), u'ok', 'zoom never takes green away')
    eq(core.after_zoom(u'reviewed'), u'reviewed', 'amber stays amber')
    eq(core.set_reviews(store, [u'a', u'b', u'c'], u'ok'), 3, 'several at once')
    eq(core.set_reviews(store, [u'a', u'b'], u'ok'), 0, 'no change counted twice')
    eq(core.set_reviews(store, [u'b'], u'not'), 1, 'back to red')
    eq(u'b' in store, False, 'red is stored as nothing')
    core.set_reviews(store, [u'd'], u'reviewed')
    back = core.parse_reviews(core.dump_reviews(store))
    eq(back, store, 'round trip')
    eq(core.parse_reviews(u'x=ok\ny=bogus\n=ok\nz=not\nnoise\n'), {u'x': u'ok'},
       'damaged lines ignored')
    eq([core.review_number(k) for k in (u'not', u'reviewed', u'ok')], [0, 1, 2],
       'sort and colour order red, amber, green')
    eq([b for k, l, b, n in core.REVIEW_STATES], ['Red', 'Orange', 'Green'], 'blob colours')
    eq(core.review_summary([u'ok', u'ok', u'reviewed', u'not', None]),
       u'2 OK - 1 reviewed - 2 not reviewed', 'summary')
    try:
        core.set_reviews(store, [u'a'], u'purple')
        eq(True, False, 'unknown state refused')
    except ValueError:
        pass


@check
def view_3d(c):
    core = c.core
    names = [u'{3D}', u'{3D - drew}', u'Coord 3D']
    eq(core.default_3d(names, u'drew'), u'{3D - drew}', 'my own default 3D first')
    eq(core.default_3d(names, u'sam'), u'{3D}', 'then {3D}')
    eq(core.default_3d([u'{3D - sam}', u'Coord'], u'drew'), u'{3D - sam}', 'then any {3D}')
    eq(core.default_3d([u'Coord'], u'drew'), u'Coord', 'then the first')
    eq(core.default_3d([], u'drew'), None, 'none')
    box = core.section_box_around([(0, 0, 0, 1, 1, 1), (5, -2, 3, 6, -1, 4)], 0.5)
    eq(box, (-0.5, -2.5, -0.5, 6.5, 1.5, 4.5), 'one box round every sphere, padded')
    eq(core.section_box_around([None], 1.0), None, 'nothing to box')


@check
def drawer_failures(c):
    FakeTimer.escaped = []
    host = FakeHost(fail_frame=3)
    m, timers = _machine(c, host)
    m.park()
    timers[-1].pump()
    eq(FakeTimer.escaped, [], 'a failing frame did not escape to the dispatcher')
    true(m.parked and not m.sliding, 'a failing frame still lands the window')
    eq((host.top, host.height), (1040 - 46 - 8.0, 46.0), 'landed after the failure')
    host2 = FakeHost()

    def broken(ms, cb):
        raise RuntimeError('no timer')
    m2 = c.core.DrawerMachine(host2, broken)
    m2.park()
    true(m2.parked and not m2.sliding, 'no timer: lands at once')


# ======================================================================
# read back, the runner and box-mode detection (against the stub API)
# ======================================================================

class _WsId(object):
    def __init__(self, v):
        self.IntegerValue = v


class _Param(object):
    def __init__(self, el, sticks):
        self.el = el
        self.sticks = sticks
        self.IsReadOnly = False
        self.value = None

    def Set(self, v):
        if self.sticks:
            if isinstance(v, int):
                self.el.WorksetId = _WsId(v)
            self.value = v

    def AsString(self):
        return self.value


class _El(object):
    def __init__(self, sticks):
        self.WorksetId = _WsId(1)
        self.p = _Param(self, sticks)

    def get_Parameter(self, which):
        return self.p

    def LookupParameter(self, name):
        return self.p


@check
def read_back(c):
    jobs = c.jobs
    eq(jobs.set_workset(_El(True), _WsId(7)), True, 'workset that sticks')
    eq(jobs.set_workset(_El(False), _WsId(7)), False, 'workset Revit ignored')
    eq(jobs.set_workset(_El(False), None), True, 'no workset asked for')
    eq(jobs.set_comment(_El(True), u'A-vs-B'), True, 'comment that sticks')
    eq(jobs.set_comment(_El(False), u'A-vs-B'), False, 'comment Revit ignored')


class _Event(object):
    def __init__(self, status):
        self.status = status

    def Raise(self):
        return self.status


@check
def runner_queue(c):
    ui = c.ui
    req = c.stubs  # noqa
    import sys as _s
    ER = _s.modules['Autodesk.Revit.UI'].ExternalEventRequest
    r = ui.Runner()
    r.event = _Event(ER.Accepted)
    true(r.submit(lambda u: 1, lambda res, err: None), 'accepted')
    r.event = _Event(ER.Pending)
    true(r.submit(lambda u: 2, lambda res, err: None), 'pending is queued')
    eq(len(r.jobs), 2, 'both jobs waiting')
    r.event = _Event(ER.Denied)
    true(not r.submit(lambda u: 3, lambda res, err: None), 'denied')
    eq(len(r.jobs), 2, 'a refused job is removed; the waiting ones stay')
    got = []
    r.Execute(None)
    eq(r.jobs, [], 'queue emptied by Execute')
    r.jobs.append((lambda u: 1 / 0, lambda res, err: got.append(err)))
    r.Execute(None)
    true(got and 'ZeroDivisionError' in got[0], 'job errors reach the callback')


@check
def box_mode(c):
    rv = c.rv
    core = c.core
    a = {'box': (0.0, 0.0, 0.0, 2.0, 2.0, 2.0)}
    b = {'box': (1.0, 1.0, 1.0, 3.0, 3.0, 3.0)}
    hit = rv.intersection(None, a, b, core.mm_to_ft(5), 'box')
    near(hit[0], (1.5, 1.5, 1.5), 'clash at the overlap centre')
    true(hit[3], 'box mode is marked approximate')
    flat = {'box': (2.0 - core.mm_to_ft(2), 0.0, 0.0, 4.0, 2.0, 2.0)}
    eq(rv.intersection(None, a, flat, core.mm_to_ft(5), 'box'), None, 'touching')
    far = {'box': (9.0, 9.0, 9.0, 10.0, 10.0, 10.0)}
    eq(rv.intersection(None, a, far, core.mm_to_ft(5), 'box'), None, 'apart')


# ======================================================================
# running
# ======================================================================

def run_checks(root, quiet=False):
    ctx = Ctx(root)
    failed = []
    try:
        for fn in CHECKS:
            try:
                fn(ctx)
                ok = True
                msg = ''
            except Exception as ex:
                ok = False
                msg = '{0}: {1}'.format(type(ex).__name__, ex)
                failed.append(fn.__name__)
            if not quiet:
                print('{0:<22} {1}{2}'.format(fn.__name__, 'ok' if ok else 'FAIL',
                                             '' if ok else '  - ' + msg))
    finally:
        ctx.close()
    return failed


PATCHES = [
    ('ca_core.py', "u'CLASH-{0:04d}_{1:02d}_{2:02d}_{3:02d}-{4:02d}{5}-{6}'",
     "u'CLASH-{0:04d}_{1:02d}_{2:02d}_{3:02d}_{4:02d}{5}-{6}'", 'group_names'),
    ('ca_core.py', "(?:_([^-\\\\s]+))?-(.+)$')", "-(.+)$')", 'group_names'),
    ('ca_core.py', "    out = [ch for ch in to_text(code) if ch.isalnum() or ch == u'.']",
     "    out = list(to_text(code))", 'group_names'),
    ('ca_core.py', "        return (u'B{0:02d}' if m.group(1) else u'L{0:02d}').format(n)",
     "        return u'L{0:02d}'.format(n)", 'level_codes'),
    ('ca_core.py', "        if len(group) > 1:", "        if False:", 'level_codes'),
    ('ca_core.py', "    for word, code in _WORDS:", "    for word, code in []:", 'level_codes'),
    ('ca_core.py', "        for dx in (-1, 0, 1):", "        for dx in (0,):", 'already_placed'),
    ('ca_core.py', "                        if d2 <= t2:", "                        if True:",
     'already_placed'),
    ('ca_core.py', "        return tuple(int(math.floor(v / self.tol)) for v in p[:3])",
     "        return tuple(int(math.floor(v / (self.tol / 3.0))) for v in p[:3])",
     'already_placed'),
    ('ca_core.py', "    clash = re.sub(u' \\\\(\\\\d+\\\\)$', u'', clash)\n", '', 'group_names'),
    ('ca_core.py', "    if typ and typ != fam:", "    if typ:", 'comments'),
    ('ca_core.py', "            pool.extend(big)\n", '', 'pair_finding'),
    ('ca_core.py', "    return min_extent(intersection_box) < touch_ft",
     "    return min_extent(intersection_box) > touch_ft", 'boxes_and_points'),
    ('ca_core.py', "        sx += x * w\n", "        sx += x\n", 'boxes_and_points'),
    ('ca_core.py', "        if elev <= z + 1e-6:", "        if elev < z - 1e-6:", 'levels'),
    ('ca_core.py', "        key = pair_key(c['a']['uid'], c['b']['uid'])",
     "        key = (c['a']['uid'], c['b']['uid'])", 'results'),
    ('ca_core.py', "        self.collapsed |= fresh\n", "        self.collapsed = set(self.catalog.keys())\n",
     'catalog_tree'),
    ('ca_core.py', "            if self.cat_state(cat) is True and self.families(cat):",
     "            if False:", 'catalog_tree'),
    ('ca_core.py', "        except Exception:\n            pass\n    if test['mode']",
     "        except Exception:\n            test[key] = None\n    if test['mode']",
     'saved_tests'),
    ('ca_core.py', "    if out['theme'] not in THEMES:", "    if False:", 'settings'),
    ('ca_core.py', "        if found_version < version:", "        if found_version > version:",
     'settings'),
    ('ca_core.py', "    if canvas is None:\n        return u'dark'\n    return u'dark' if int(canvas) == 0",
     "    if not canvas:\n        return u'dark' if canvas is None else u'light'\n    return u'dark' if int(canvas) == 0",
     'theme'),
    ('ca_core.py', "    'Muted': '#B4BAC2',", "    'Muted': '#7A808A',", 'theme'),
    ('ca_core.py', "            out.append(u\"''\")", "            out.append(u\"'\")", 'filters_and_egg'),
    ('ca_core.py', "        if not uniq or s != uniq[-1]:", "        if True:", 'filters_and_egg'),
    ('ca_core.py', "    return (wt + wh - header_h - gap, header_h)",
     "    return (wh - header_h - gap, header_h)", 'drawer_maths'),
    ('ca_core.py', "        new_top = bar_top + header_h - height", "        new_top = top",
     'drawer_maths'),
    ('ca_core.py', "        if self.sliding:\n            return False",
     "        if False:\n            return False", 'drawer_cycle'),
    ('ca_core.py', "        try:\n            self.host.release()",
     "        try:\n            pass", 'drawer_cycle'),
    ('ca_core.py', "        except Exception as ex:\n            self.errors.append(u'tick: {0}'.format(ex))\n            self._land()\n",
     "        finally:\n            pass\n", 'drawer_failures'),
    ('ca_core.py', "            self.errors.append(u'timer: {0}'.format(ex))\n            self._land()",
     "            self.errors.append(u'timer: {0}'.format(ex))", 'drawer_failures'),
    ('ca_jobs.py', "        return rv.workset_int(element.WorksetId) == target\n    except Exception:\n        return False",
     "        return True\n    except Exception:\n        return False", 'read_back'),
    ('ca_jobs.py', "        return core.to_text(p.AsString()) == text", "        return True",
     'read_back'),
    ('ca_ui.py', "        try:\n            self.jobs.remove(job)\n        except ValueError:\n            pass\n",
     "        del self.jobs[:]\n", 'runner_queue'),
    ('ca_ui.py', "        if status == ExternalEventRequest.Accepted or \\\n                status == ExternalEventRequest.Pending:",
     "        if status == ExternalEventRequest.Accepted:", 'runner_queue'),
    ('ca_core.py', "        if o.lower() == clean.lower():", "        if o == clean:",
     'rename_names'),
    ('ca_core.py', "        if safe_filename(o).lower() == safe_filename(clean).lower():",
     "        if False:", 'rename_names'),
    ('ca_core.py', "        if o.lower() == old_key:\n            continue",
     "        if False:\n            continue", 'rename_names'),
    ('ca_core.py', "    return [new if n == old else n for n in order if n != new or n == old]",
     "    return [new if n == old else n for n in order]", 'rename_names'),
    ('ca_revit.py', "    if mode == 'box':\n        if core.is_touching(overlap, touch_ft):\n            return None\n",
     "    if mode == 'box':\n", 'box_mode'),
    ('ca_core.py', "    if fixed_level is not None:\n        return fixed_level\n", '', 'levels'),
    ('ca_core.py', "    if test['scope'] not in [s[0] for s in RUN_SCOPES]:", "    if False:",
     'saved_tests'),
    ('ca_core.py', "    'scope': u'view',\n", "    'scope': u'project',\n", 'saved_tests'),
    ('ca_core.py', "            if self._i >= self.frames:\n                self._land()\n                return\n            t = float(self._i)",
     "            if self._i >= self.frames * 3:\n                self._land()\n                return\n            t = float(self._i)",
     'sections'),
    ('ca_core.py', "            self.errors.append(u'tick: {0}'.format(ex))\n            self._land()\n\n    def _land(self):\n        try:\n            if self._timer is not None:\n                self._timer.Stop()\n        except Exception:\n            pass\n        self._timer = None\n        self.sliding = False\n        try:\n            self.host.land(self.is_open)",
     "            raise\n\n    def _land(self):\n        try:\n            if self._timer is not None:\n                self._timer.Stop()\n        except Exception:\n            pass\n        self._timer = None\n        self.sliding = False\n        try:\n            self.host.land(self.is_open)",
     'sections'),
    ('ca_core.py', "        if self.sliding or want == self.is_open:", "        if want == self.is_open:",
     'sections'),
    ('ca_core.py', "        return CHEVRON_SHUT + (CHEVRON_OPEN - CHEVRON_SHUT) * t",
     "        return CHEVRON_OPEN + (CHEVRON_SHUT - CHEVRON_OPEN) * t", 'sections'),
    ('ca_core.py', "    if not name or not model_type or not builtin or has_parent:",
     "    if not name or not model_type:", 'model_categories'),
    ('ca_core.py', "    if name.startswith(u'<') or name.endswith(u'>'):", "    if False:",
     'model_categories'),
    ('ca_core.py', "    return (active_level_key is not None and group_level_key is not None and\n            active_level_key == group_level_key)",
     "    return active_level_key == group_level_key", 'isolate_choice'),
    ('ca_core.py', "    return u'reviewed' if state in (None, u'', u'not') else state",
     "    return u'reviewed'", 'review_status'),
    ('ca_core.py', "        if state == u'not':\n            store.pop(uid, None)\n        else:\n            store[uid] = state",
     "        store[uid] = state", 'review_status'),
    ('ca_core.py', "        if review_state(store, uid) == state:\n            continue\n", '',
     'review_status'),
    ('ca_core.py', "        if uid and state in REVIEW_KEYS and state != u'not':",
     "        if uid:", 'review_status'),
    ('ca_core.py', "    wanted = [u'{3D - ' + to_text(user) + u'}', u'{3D}']",
     "    wanted = [u'{3D}', u'{3D - ' + to_text(user) + u'}']", 'view_3d'),
    ('ca_core.py', "    x1 = max(b[3] for b in boxes) + pad", "    x1 = max(b[3] for b in boxes)",
     'view_3d'),
    ('ca_core.py', "        if best is None or counts[k] > counts[best]:",
     "        if best is None or counts[k] >= counts[best]:", 'isolate_choice'),
    ('ca_core.py', "    if on_level_only and level_key is not None and view.get('level_key') != level_key:",
     "    if on_level_only and view.get('level_key') != level_key:", 'isolate_choice'),
    ('ca_core.py', "        if word not in hay:", "        if word not in to_text(view.get('name')).lower():",
     'isolate_choice'),
    ('ca_core.py', "    picked.sort(key=lambda v: (0 if (level_key is not None and",
     "    picked.sort(key=lambda v: (1 if (level_key is not None and", 'isolate_choice'),
    ('ca_core.py', "        if low.endswith(ext) or (ext + u' ') in low:", "        if low.endswith(ext):",
     'model_categories'),
    ('ca_core.py', "        if key in taken or key in offered:", "        if key in offered:",
     'workset_offer'),
    ('ca_core.py', "    for name in [SUGGESTED_WORKSET] + list(pending):", "    for name in list(pending):",
     'workset_offer'),
    ('ca_core.py', "        if to_text(name).lower() == clean.lower():\n            return clean, None, name",
     "        if to_text(name) == clean:\n            return clean, None, name", 'workset_offer'),
    ('ca_core.py', "    out.append(('custom', u'Custom workset...', WS_CUSTOM))\n", '', 'workset_offer'),
    ('ca_core.py', "    wanted = longest * SCHEDULE_MM_PER_CHAR + SCHEDULE_PAD_MM",
     "    wanted = longest * 1.2", 'schedule_width'),
    ('ca_core.py', "    return max(SCHEDULE_MIN_MM, min(SCHEDULE_MAX_MM, wanted))",
     "    return max(SCHEDULE_MIN_MM, wanted)", 'schedule_width'),
    ('ca_core.py', "        longest = max(longest, len(to_text(c).strip()))",
     "        longest = len(to_text(c).strip())", 'schedule_width'),
]


def selftest():
    if run_checks(HERE, quiet=True):
        print('the clean tool fails its own checks')
        return False
    ok = True
    for i, (fname, anchor, replacement, expected) in enumerate(PATCHES):
        tmp = tempfile.mkdtemp(prefix='ca_logic_')
        try:
            for f in os.listdir(HERE):
                p = os.path.join(HERE, f)
                if os.path.isfile(p):
                    shutil.copy(p, tmp)
            path = os.path.join(tmp, fname)
            text = io.open(path, encoding='utf-8').read()
            if anchor not in text:
                print('  [{0:02d}] anchor missing in {1}: FAIL'.format(i, fname))
                ok = False
                continue
            io.open(path, 'w', encoding='utf-8').write(text.replace(anchor, replacement, 1))
            failed = run_checks(tmp, quiet=True)
            caught = expected in failed
            print('  [{0:02d}] {1:<18} {2:<12} {3}'.format(
                i, expected, fname, 'caught' if caught else 'MISSED (got {0})'.format(failed)))
            ok = ok and caught
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    names = set(p[3] for p in PATCHES)
    unproven = [fn.__name__ for fn in CHECKS if fn.__name__ not in names]
    if unproven:
        print('checks with no patch: {0}'.format(unproven))
        ok = False
    return ok


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        good = selftest()
        print('\nSELFTEST {0}: {1} patches, {2} checks'.format(
            'PASSED' if good else 'FAILED', len(PATCHES), len(CHECKS)))
        sys.exit(0 if good else 1)
    bad = run_checks(HERE)
    print('\n{0} of {1} checks passed'.format(len(CHECKS) - len(bad), len(CHECKS)))
    sys.exit(1 if bad else 0)
