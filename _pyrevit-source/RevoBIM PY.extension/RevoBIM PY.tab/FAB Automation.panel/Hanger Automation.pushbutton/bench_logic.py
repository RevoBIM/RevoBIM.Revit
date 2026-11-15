# -*- coding: utf-8 -*-
"""Pure-logic bench for Hanger Automation.  Run under plain CPython:
    python bench_logic.py            run the cases
    python bench_logic.py --selftest break the logic on purpose, confirm it is caught
"""
import os
import sys
import copy

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fha_core as core
import hfam_core as fc
import hcirc_core as cc
import math

MM = core.MM
CFG = core.plan_config(dict(core.DEFAULTS))


def mm(v):
    return v / MM


def stations(length_mm, s, e, cfg=None):
    return [round(x * MM) for x in core.plan_stations(mm(length_mm), s, e, cfg or CFG)]


def straight(pid, a, b, to0, to1, c0=0, c1=0):
    return pid, {'kind': 'straight', 'len': mm(b - a), 'horizontal': True,
                 'conns': [{'to': to0, 'to_conn': c0, 'role': None},
                           {'to': to1, 'to_conn': c1, 'role': None}]}


def cases():
    out = []

    def check(name, got, want):
        out.append((name, got == want, got, want))

    # --- spacing rules
    check('6000 bend-bend', stations(6000, 'bend', 'bend'), [300, 2300, 4300, 5700])
    s = stations(5000, 'bend', 'bend')
    check('5000 starts 300 ends 4700', (s[0], s[-1]), (300, 4700))
    check('5000 never over spacing', max(b - a for a, b in zip(s, s[1:])) <= 2000, True)
    s = stations(1200, 'bend', 'bend')
    check('short run 2 hangers', s, [300, 900])
    check('tiny run none', stations(150, 'bend', 'bend'), [])
    check('takeoff stub none', stations(500, 'tap', 'bend'), [])
    s = stations(3000, 'tap', 'bend')
    check('takeoff start keeps clear', s[0] >= 400, True)
    s = stations(4000, 'bend', 'open')
    check('open end no forced hanger', s[-1] <= 3900, True)
    # --- dedupe / existing
    check('dedupe', core.dedupe([1.0, 1.1, 3.0], 0.5), [1.0, 3.0])
    check('drop_near', core.drop_near([1.0, 5.0], [1.1], 0.3), [5.0])
    # --- spans
    p = {}
    for pid, rec in [straight(1, 0, 3000, 10, 2, 0, 0), straight(2, 3000, 6000, 1, 11, 1, 0)]:
        p[pid] = rec
    p[1]['conns'][0] = {'to': 10, 'to_conn': 0, 'role': None}
    p[10] = {'kind': 'bend', 'len': 0, 'horizontal': True, 'conns': [{'to': 1, 'to_conn': 0, 'role': None}, {'to': None, 'to_conn': None, 'role': None}]}
    p[11] = {'kind': 'bend', 'len': 0, 'horizontal': True, 'conns': [{'to': 2, 'to_conn': 1, 'role': None}, {'to': None, 'to_conn': None, 'role': None}]}
    p[1]['conns'][1] = {'to': 2, 'to_conn': 0, 'role': None}
    p[2]['conns'][0] = {'to': 1, 'to_conn': 1, 'role': None}
    p[2]['conns'][1] = {'to': 11, 'to_conn': 0, 'role': None}
    sp = core.build_spans(p)
    check('two straights one span', len(sp), 1)
    check('span ends are bends', (sp[0]['start_end']['type'], sp[0]['end_end']['type']), ('bend', 'bend'))
    check('span length', round(core.span_length(sp[0]) * MM), 6000)
    loc = core.locate(sp[0]['chain'], mm(3000), 0.1)
    check('locate not on joint', 0.1 <= loc['dist'], True)
    # --- tee branch end is typed as takeoff
    q = {1: {'kind': 'straight', 'len': mm(3000), 'horizontal': True,
             'conns': [{'to': 5, 'to_conn': 0, 'role': None}, {'to': None, 'to_conn': None, 'role': None}]},
         5: {'kind': 'tee', 'len': 0, 'horizontal': True,
             'conns': [{'to': 1, 'to_conn': 0, 'role': 'branch'}, {'to': None, 'to_conn': None, 'role': 'main'}, {'to': None, 'to_conn': None, 'role': 'main'}]}}
    sq = core.build_spans(q)
    check('tee branch typed', sq[0]['start_end']['type'] in ('tee_branch', 'open'), True)
    # --- nearest host
    hosts = [{'id': 1, 'a': (0, 0, 0), 'b': (10, 0, 0), 'horizontal': True},
             {'id': 2, 'a': (0, 3, 0), 'b': (10, 3, 0), 'horizontal': True}]
    n = core.nearest_host((5, 1, 0), hosts, 5, 0.1)
    check('nearest host', n['host']['id'], 1)
    check('host none out of range', core.nearest_host((5, 20, 0), hosts, 5, 0.1), None)
    n = core.nearest_host((-4, 0, 0), hosts, 5, 0.1)
    check('dist clamped off the end', n['dist'], 0.1)
    # --- dimensions
    p0, p1, nrm = core.dim_line((0, 0, 0), (10, 0, 0), 800)
    check('dim line parallel', abs(p0[1] - p1[1]) < 1e-9, True)
    check('dim line below run', p0[1] < 0, True)
    check('dim overshoot', p0[0] < 0 and p1[0] > 10, True)
    check('collapse refs', len(core.collapse_refs([(0, 'a'), (0.001, 'b'), (1, 'c')], 0.01)), 2)
    # --- rods
    check('rod target', round(core.rod_target_length(2.0, 10.0, 12.0, 0.5), 6), 3.5)
    check('rod ok at soffit', core.rod_ok(12.0, 12.0, 0.2, 0.02), True)
    check('rod short', core.rod_ok(10.0, 12.0, 0.2, 0.02), False)
    # --- settings round trip
    d = core.parse_settings(u'spacing=1800\nbogus\n=x\ntheme=dark\n')
    check('settings parse', (d.get(u'spacing'), d.get(u'theme')), (u'1800', u'dark'))
    check('parse_mm', (core.parse_mm(u'2500', 1.0), core.parse_mm(u'x', 7.0)), (2500.0, 7.0))
    # --- theme
    check('resolve auto dark', core.resolve_theme(u'auto', True), u'dark')
    check('resolve auto light', core.resolve_theme(u'auto', False), u'light')
    check('resolve forced', core.resolve_theme(u'light', True), u'light')
    check('palettes same keys', sorted(core.PALETTES[u'dark']) == sorted(core.PALETTES[u'light']), True)
    check('next_mode cycles', core.next_mode(core.next_mode(core.next_mode(u'auto'))), u'auto')
    # --- takeoffs on the run
    L = mm(6000)
    st = core.plan_stations(L, 'bend', 'bend', CFG)
    moved = [round(x * MM) for x in core.avoid_blocks(st, [mm(4300)], mm(400), L, mm(100))]
    check('tap moves hanger clear', moved, [300, 2300, 3900, 5700])
    check('no taps no change', core.avoid_blocks(st, [], mm(400), L, mm(100)), st)
    moved = [round(x * MM) for x in core.avoid_blocks([mm(1000)], [mm(700), mm(1300)], mm(400), mm(1500), mm(100))]
    check('between two taps: moves to the free side', moved, [300])
    boxed = core.avoid_blocks([mm(750)], [mm(400), mm(1100)], mm(400), mm(1500), mm(100))
    check('boxed in by two taps: dropped', boxed, [])
    segs = core.span_segments([{'id': 1, 'kind': 'straight', 'len': mm(3000)},
                               {'id': 2, 'kind': 'straight', 'len': mm(3000)}],
                              {1: ((0, 0, 0), (mm(3000), 0, 0)), 2: ((mm(3000), 0, 0), (mm(6000), 0, 0))})
    check('station of a tap', round(core.station_of_point(segs, (mm(4300), 0.6, 0.3), 2.5) * MM), 4300)
    check('point off the run', core.station_of_point(segs, (mm(4300), 9.0, 0), 2.5), None)
    # --- hanger conditions
    conds = [(0, 0.0, 1.0, False), (1, 1.0, 2.0, False), (2, 0.0, -1.0, False), (3, 0, 0, True)]
    check('condition: tightest covering', core.pick_condition(conds, 1.3), 1)
    check('condition: open-ended upper', core.pick_condition(conds[2:], 5.0), 2)
    check('condition: unrestricted fallback', core.pick_condition([(0, 0.0, 1.0, False), (3, 0, 0, True)], 5.0), 3)
    check('condition: none fits', core.pick_condition([(0, 0.0, 1.0, False)], 5.0), None)
    # --- matching an existing hanger to a button
    check('name tokens drop sizes', core.name_tokens(u'Clevis 300', u'CLEVIS-450'), set([u'clevis']))
    old = {'name': u'Clevis 200', 'product': u'Clevis hanger', 'item_id': 2}
    clevis = {'name': u'Clevis 450', 'product': u'Clevis hanger', 'item_id': 2}
    trapeze = {'name': u'Trapeze 450', 'product': u'Trapeze hanger', 'item_id': 1}
    check('same kind outscores other kind', core.signature_score(old, clevis) > core.signature_score(old, trapeze), True)
    check('names alone still match', core.signature_score({'name': u'Clevis 200'}, {'name': u'clevis 600'}) > 0, True)
    check('nothing in common scores 0', core.signature_score({'name': u'Clevis'}, {'name': u'Trapeze'}), 0.0)
    check('rehost replaces by default', core.as_bool(core.DEFAULTS, u'rehost_replace'), True)
    # --- Family Hangers: pure rules
    fams = {u'BGL Hanger': {u'left': u'W L', u'right': u'W R', u'rod': u'Rod', u'axis': u'Y', u'clearance': u'10', u'soffit': u'structure', u'swap': u'1', u'first_bar': u'FB', u'height': u'SH', u'height_clear': u'15',
                          u'style': u'circ', u'dia': u'D', u'circ_height': u'CH', u'circ_axis': u'Y'}}
    check('family settings round trip', fc.parse_families(fc.dump_families(fams)), fams)
    check('family settings ignore unknown keys', fc.parse_families(u'[A]\nleft=x\nbogus=1\n'), {u'A': {u'left': u'x'}})
    cfg = fc.fam_config({}, u'New', [u'BGL_DIM_Width Left', u'BGL_DIM_Width Right', u'BGL_DIM_Drop Rod Length'])
    check('defaults: rod parameter', cfg[u'rod'], u'BGL_DIM_Drop Rod Length')
    check('guess width pair', (cfg[u'left'], cfg[u'right']), (u'BGL_DIM_Width Left', u'BGL_DIM_Width Right'))
    check('guess _L / _R pair', fc.guess_width_params([u'Width_L', u'Width_R']), (u'Width_L', u'Width_R'))
    check('chosen params beat guesses', fc.fam_config(fams, u'BGL Hanger', [u'X Left', u'X Right'])[u'left'], u'W L')
    items = [{'family': u'BGL Unistrut', 'type': u'41x41', 'cat': u'OST_MEPAncillaryFraming'},
             {'family': u'Generic Box', 'type': u'A', 'cat': u'OST_GenericModel'},
             {'family': u'BGL Damper', 'type': u'FD', 'cat': u'OST_DuctAccessory'}]
    check('filter by category', [i['family'] for i in fc.filter_types(items, u'OST_GenericModel', u'')], [u'Generic Box'])
    check('search every word, any order', [i['family'] for i in fc.filter_types(items, u'all', u'41 bgl')], [u'BGL Unistrut'])
    check('DW/144 rectangular up to 1500', fc.dw144_spacing_mm(1500, 400, False), 3000.0)
    check('DW/144 rectangular over 1500', fc.dw144_spacing_mm(1600, 400, False), 2500.0)
    check('DW/144 by longer side', fc.dw144_spacing_mm(400, 1600, False), 2500.0)
    check('your maximum still wins when smaller', fc.span_spacing_mm(2000, True, 600, 300, False), 2000.0)
    check('DW/144 off uses your maximum', fc.span_spacing_mm(4000, False, 1600, 400, False), 4000.0)
    check('half width plus clearance', round(fc.half_width(600 / MM, 10) * MM, 6), 310.0)
    check('rod to the soffit', round(fc.rod_length(1.0, 4.5), 9), 3.5)
    check('no rod when nothing above', fc.rod_length(5.0, None), None)
    check('level above is the next one up', fc.level_above([0.0, 10.0, 20.0], 9.5), 10.0)
    check('level above skips the level it sits on', fc.level_above([0.0, 10.0, 20.0], 10.0), 20.0)
    check('rotate 90 to square up', round(math.degrees(fc.rotation_to((1, 0), (0, 1)))), 90)
    check('never spin a symmetric hanger round', round(math.degrees(fc.rotation_to((1, 0), (-1, 0.0001)))), 0)
    check('width along X faces across the duct', fc.family_x_dir(u'X', (1, 0, 0), (0, 1, 0)), (0, 1, 0))
    check('width along Y faces along the duct', fc.family_x_dir(u'Y', (1, 0, 0), (0, 1, 0)), (1, 0, 0))
    q = fc.on_centreline((0, 0, 10), (10, 0, 10), (3, 2, 11), 0.1)
    check('onto the centreline where clicked', tuple(round(v, 9) for v in q), (3.0, 0.0, 10.0))
    st = [round(x * MM) for x in core.plan_stations(mm(4000), 'bend', 'accessory', CFG)]
    check('damper end gets a hanger before it', st[-1], 3700)
    # --- 1.2.0: re-align, insulation, dimension groups
    check('re-align keeps the place along the run', fc.on_line((0, 0, 10), (10, 0, 10), (14, 3, 9)), (14.0, 0.0, 10.0))
    segs = [('a', (0, 0, 0), (10, 0, 0)), ('b', (10, 0, 0), (20, 0, 0))]
    check('segment under the hanger', fc.pick_segment((14, 0.5, 0), segs, 0.5), 'b')
    check('hanger off every segment', fc.pick_segment((30, 0, 0), segs, 0.5), None)
    ins = fc.apply_insulation({'width': 2.0, 'depth': 1.0, 'ins': 0.1}, True)
    check('insulation outside widens both ways', (round(ins['width'], 9), round(ins['depth'], 9)), (2.2, 1.2))
    check('insulation inside leaves the duct size', fc.apply_insulation({'width': 2.0, 'depth': 1.0, 'ins': 0.1}, False)['width'], 2.0)
    g = fc.group_runs([('h1', (0, 0, 0), (0, 1, 0)), ('h2', (0, 5, 0), (0, -1, 0)), ('h3', (0.2, 9, 0), (0, 1, 0)),
                       ('x', (30, 0, 0), (1, 0, 0))], 1.0)
    check('one run line, either facing, sorted', g, [((0.0, 1.0, 0.0), ['h1', 'h2', 'h3'])])
    g = fc.group_runs([('a', (0, 0, 0), (1, 0, 0)), ('b', (5, 0, 0), (1, 0, 0)), ('c', (0, 10, 0), (1, 0, 0)), ('d', (5, 10, 0), (1, 0, 0))], 1.0)
    check('parallel runs dimension separately', len(g), 2)
    check('centre reference across a run along Y', fc.reference_type_across((1, 0), (0, 1), (0, 1, 0)), 'CenterFrontBack')
    check('centre reference across a run along X', fc.reference_type_across((1, 0), (0, 1), (1, 0, 0)), 'CenterLeftRight')
    p0, p1, n = core.dim_line((0, 0, 0), (0, 10, 0), 800.0, 0.0)
    check('dimension 800 mm off to the side of a vertical run', round(p0[0] * MM), 800)
    check('window grows to show every tool', core.fit_height(760, 500, 640, 560, 100, 0, 1040), (900, 100))
    check('never taller than the screen, scrolls instead', core.fit_height(760, 500, 1400, 560, 100, 0, 1040), (1040, 0))
    check('moved up when it would run off the bottom', core.fit_height(760, 500, 640, 560, 300, 0, 1040), (900, 140))
    check('shrinks to the content, not below the minimum', core.fit_height(900, 700, 300, 560, 0, 0, 1040), (560, 0))
    # --- 1.4.0: grouped services
    tray = ('tray', (0, 0, 10), (20, 0, 10), 300 / MM, 100 / MM)
    pipe = ('pipe', (0, 260 / MM, 10 + 30 / MM), (20, 260 / MM, 10 + 30 / MM), 100 / MM, 100 / MM)
    b = fc.bundle((5, 0, 10), [tray, pipe])
    check('group: both in, 460 wide', (b['keys'], round(b['width'] * MM, 6)), (['tray', 'pipe'], 460.0))
    check('group: at the lowest invert', round((b['bottom'] - 10) * MM, 6), -50.0)
    check('group: centred on the mean of the centres', round(b['point'][1] * MM, 6), 130.0)
    check('group: reaches each outer edge', (round(b['ext_neg'] * MM, 6), round(b['ext_pos'] * MM, 6)), (280.0, 180.0))
    gap_far = ('far', (0, 720 / MM, 10), (20, 720 / MM, 10), 100 / MM, 100 / MM)
    check('group: 500 mm gap or more stays separate', fc.bundle((5, 0, 10), [tray, gap_far])['keys'], ['tray'])
    high = ('high', (0, 260 / MM, 10 + 81 / MM), (20, 260 / MM, 10 + 81 / MM), 100 / MM, 100 / MM)
    check('group: more than 50 mm higher stays separate', fc.bundle((5, 0, 10), [tray, high])['keys'], ['tray'])
    skew = ('skew', (0, 0.9, 10), (20, 3.0, 10), 100 / MM, 100 / MM)
    check('group: not parallel stays separate', fc.bundle((5, 0, 10), [tray, skew])['keys'], ['tray'])
    short = ('short', (8, 260 / MM, 10), (20, 260 / MM, 10), 100 / MM, 100 / MM)
    check('group: not alongside here stays separate', fc.bundle((5, 0, 10), [tray, short])['keys'], ['tray'])
    chain = [tray, ('p1', (0, 260 / MM, 10), (20, 260 / MM, 10), 100 / MM, 100 / MM),
             ('p2', (0, 420 / MM, 10), (20, 420 / MM, 10), 100 / MM, 100 / MM)]
    check('group: chains neighbour to neighbour', fc.bundle((5, 0, 10), chain)['keys'], ['tray', 'p1', 'p2'])
    check('group of one is the service itself', round(fc.bundle((5, 0, 10), [tray])['width'] * MM, 6), 300.0)
    # --- 1.5.0: rules, sides
    check('rules default: 50 mm height, 500 mm gap, 2 deg, mean centre',
          (round(fc.group_rules(core.DEFAULTS)[0] * MM), round(fc.group_rules(core.DEFAULTS)[1] * MM),
           fc.group_rules(core.DEFAULTS)[2], fc.group_rules(core.DEFAULTS)[3]), (50, 500, 2.0, u'mean'))
    single = {'width': 0.6}
    check('single service: half each side plus clearance', fc.side_values(single, (1, 0), 0.1), (0.4, 0.4))
    grp = {'width': 1.0, 'ext_neg': 0.7, 'ext_pos': 0.3, 'across': (0.0, 1.0, 0.0)}
    check('group: family axis along across - right reaches the positive edge', fc.side_values(grp, (0, 1), 0.0), (0.7, 0.3))
    check('group: family axis reversed - sides follow it', fc.side_values(grp, (0, -1), 0.0), (0.3, 0.7))
    check('group: swap', fc.side_values(grp, (0, 1), 0.0, True), (0.3, 0.7))
    b = fc.bundle((5, 0, 10), [tray, pipe], centre=u'edges')
    check('edges centre option', round(b['point'][1] * MM, 6), 80.0)
    # --- 1.5.1: measured sides
    check('reach either side from the box corners', fc.reaches([(0, -1.5), (0, 2.5)], (0, 0), (0, 1, 0)), (2.5, 1.5))
    check('mirrored when the long side is on the short side', fc.sides_mirrored(1.5, 2.5, 2.5, 1.5), True)
    check('not mirrored when it matches', fc.sides_mirrored(2.5, 1.5, 2.5, 1.5), False)
    # --- 1.5.2: strict stations, lone services, units
    leg = [(0.0, (mm(300), mm(300), 0), (mm(300), mm(2000), 0), 2)]
    check('hanger round a bend is not on the next leg', core.station_on_run(leg, (0, 0, 0), 2.5), None)
    check('hanger on the leg is', round(core.station_on_run(leg, (mm(300), mm(900), 0), 2.5) * MM), 600)
    lone = fc.bundle((5, 0, 10), [tray])
    own = {'a': (0, 0, 10), 'b': (20, 0, 10), 'width': 300 / MM, 'depth': 100 / MM, 'round': True}
    check('lone service keeps its own section', fc.bundle_section(lone, own)['round'] and
          fc.bundle_section(lone, own)['depth'] == own['depth'], True)
    check('lone service hung from its centreline', round(fc.bundle_point(lone, own, (5, 0.2, 10))[2], 9), 10.0)
    box = [(x, y, z) for x in (0, mm(1200)) for y in (0, mm(800)) for z in (mm(2500), mm(3000))]
    u = fc.unit_section((1, 0), (0, 1), box)
    check('unit: spans across the longer side, bottom face, centred',
          (round(u['width'] * MM), round((u['a'][2] - u['depth'] / 2.0) * MM), round(u['a'][1] * MM)), (800, 2500, 400))
    u2 = fc.unit_section((1, 0), (0, 1), box, run_hint=(0, 1))
    check('unit: runs along its connectors when it has them', round(u2['width'] * MM), 1200)
    check('in-line connectors give the run', fc.inline_direction([((0, 0, 0), (0, 1, 0)), ((0, 1, 0), (0, -1, 0))]), (0, 1))
    # --- 1.6.0: floor supports
    sec1 = {'depth': mm(300)}
    check('floor: first bar at the invert, height the depth plus clearance',
          [round(v * MM) for v in fc.floor_values(mm(2898), mm(0), sec1, mm(20))], [2898, 320])
    check('floor: a group uses its full span', round(fc.floor_values(mm(2998), 0.0, {'depth': 0.0, 'span_height': mm(150)}, 0.0)[1] * MM), 150)
    check('floor: params guessed', (fc.guess_first_bar_param([u'HBarLastOffset', u'First Bar Offset']),
                                    fc.guess_support_height_param([u'Frame Width', u'BIM_Hanger_Support_Height'])),
          (u'First Bar Offset', u'BIM_Hanger_Support_Height'))
    check('floor: control names', [fc.flr_name(n) for n in (u'FamPanel', u'LstFamilies', u'ChkFamLockPlace', u'HdrFamAuto')],
          [u'FloorPanel', u'LstFlrFamilies', u'ChkFlrLockPlace', u'HdrFlrAuto'])
    check('floor: own settings, shared rules, no rods', (core.floor_key(u'fam_lock_place'), core.floor_key(u'fam_group_gap'),
          u'flr_rod_place' in core.DEFAULTS, core.DEFAULTS.get(u'flr_lock_place')), (u'flr_lock_place', u'fam_group_gap', False, u'1'))
    # --- 1.7.0: worksets
    labels, idx, vals = core.workset_items([u'Mech'], u'Gone')
    check('workset combo: three choices, the model, a lost name kept', (len(labels), idx, labels[-1]), (5, 4, u'Gone (not in this model)'))
    check('workset combo value', core.workset_value(vals, 3), u'Mech')
    t = core.workset_target
    check('workset target: leave as is', (t(u'', 5, 9, None, True), t(u'', 5, 9, None, False)), (5, None))
    check('workset target: service / active / named', (t(core.WS_SERVICE, 5, 9, None, False), t(core.WS_ACTIVE, 5, 9, None, True),
                                                       t(u'X', 5, 9, 3, False)), (5, 9, 3))
    check('workset target: named but missing', (t(u'X', 5, 9, None, True), t(u'X', 5, 9, None, False)), (5, None))
    # --- 1.10.0: drawer arithmetic, search, dimension views, palette
    check('drawer: parked 8 px above the taskbar', core.shrunk_top(0.0, 1040.0, 70.0), 962.0)
    check('drawer: a dialog parks above its window', core.shrunk_top(0.0, 1040.0, 70.0, 1), 884.0)
    check('drawer: a monitor above the primary (negative top)', core.shrunk_top(-1080.0, 1040.0, 70.0), -118.0)
    check('drawer: reopens where it was', core.expand_top(200.0, 962.0, 962.0, 70.0, 700.0, 0.0, 1040.0), 200.0)
    check('drawer: dragged bar opens upward from it', core.expand_top(200.0, 962.0, 800.0, 70.0, 700.0, 0.0, 1040.0), 170.0)
    check('drawer: kept on the screen', core.expand_top(200.0, 962.0, 100.0, 70.0, 700.0, 0.0, 1040.0), 0.0)
    check('drawer: on the upper monitor', core.expand_top(-900.0, -118.0, -118.0, 70.0, 700.0, -1080.0, 1040.0), -900.0)
    check('search: every word, any order, any case', (core.match_words(u'Level 1 - Mech Ductwork', u'mech lev'),
          core.match_words(u'Level 1 - Mech', u'mech pipe')), (True, False))
    check('natural order', sorted([u'M-A10', u'M-A9', u'M-A100'], key=core.natural_key), [u'M-A9', u'M-A10', u'M-A100'])
    vrows = [{'key': 1, 'name': u'L1 Mech', 'type': u'FloorPlan', 'scale': 50},
             {'key': 2, 'name': u'Section A', 'type': u'Section', 'scale': 20},
             {'key': 3, 'name': u'L1 RCP', 'type': u'CeilingPlan', 'scale': 50}]
    check('views: plans only', [r['key'] for r in core.filter_view_rows(vrows, u'', u'plan')], [1, 3])
    check('views: floor plans (the default filter)', ([r['key'] for r in core.filter_view_rows(vrows, u'', u'floor')],
          core.VIEW_KINDS[0][0]), ([1], u'floor'))
    check('views: sections only, searched', [r['key'] for r in core.filter_view_rows(vrows, u'sect', u'section')], [2])
    check('views: search covers the type', [r['key'] for r in core.filter_view_rows(vrows, u'ceiling')], [3])
    srows = [{'key': 10, 'number': u'M-101', 'name': u'L1 Ductwork', 'views': [1, 2]},
             {'key': 11, 'number': u'M-102', 'name': u'L2', 'views': [2, 3]}]
    check('sheets: searched by number', [r['key'] for r in core.filter_sheet_rows(srows, u'102')], [11])
    check('chosen: ticked views plus every view on a ticked sheet, each once',
          core.chosen_views([3], [10, 11], srows), [3, 1, 2])
    p0, p1 = core.dim_line_in_view((0, 5, 10), (10, 5, 10), 800.0, (0, 0, 1), (0, -1, 0), (0, 0, 0))
    check('section dimension line: below the run, in the view plane, past both ends',
          (round(p0[2] * MM), round(p0[1], 9), round(p0[0] * MM), round(p1[0] * MM)), (3048 - 800, 0.0, -300, 3348))
    pal = core.PALETTES[u'dark']
    low = []
    for fg in (u'Text', u'Muted', u'Blue', u'Orange'):
        for bg in (u'WinBg', u'Card', u'Field', u'Bar'):
            if core.contrast(pal[fg], pal[bg]) < 4.5:
                low.append((fg, bg, round(core.contrast(pal[fg], pal[bg]), 2)))
    for fg, bg in ((u'Text', u'Sel'), (u'OnAccent', u'Green'), (u'OnAccent', u'Blue')):
        if core.contrast(pal[fg], pal[bg]) < 4.5:
            low.append((fg, bg, round(core.contrast(pal[fg], pal[bg]), 2)))
    check('dark palette: every text pairing 4.5:1 or better', low, [])
    check('dark palette: Revit greys (theme reference)', (pal[u'WinBg'], pal[u'Field'], pal[u'Card'], pal[u'Sel']),
          (u'#3C4454', u'#2D3441', u'#323C48', u'#3A7392'))
    check('comments: one service', core.service_comment([u'Pipe Types : Copper']), u'Pipe Types : Copper')
    check('comments: several, in order, repeats counted', core.service_comment(
        [u'Cable Tray : Ladder', u'Pipe Types : Copper', u'Cable Tray : Ladder', u'', None]), u'2xCable Tray : Ladder, Pipe Types : Copper')
    check('comments: nothing to say', core.service_comment([]), u'')
    check('set-up families: the green reads on the list in both themes (4.5:1)',
          [round(core.contrast(core.PALETTES[m][u'SetText'], core.PALETTES[m][u'Field']), 1) >= 4.5 for m in (u'dark', u'light')],
          [True, True])
    # --- 1.13.0: Circular System Based supports (hcirc_core - a path of its own)
    check('circular: support height = base up to the service centre (the ring centre)',
          round(cc.support_height(mm(3048), mm(400)) * MM, 2), 2648.0)
    check('circular: ring check is the ring centre less the service centre',
          round(cc.ring_off(mm(3098), mm(3048)) * MM, 2), 50.0)
    check('circular hanger: its offset puts it on the service centreline (not the invert)',
          round(cc.hanger_offset(mm(3048), mm(4000)) * MM, 2), -952.0)
    check('circular: orientation', (cc.circ_x_dir(u'X', (1, 0, 0), (0, 1, 0)), cc.circ_x_dir(u'Y', (1, 0, 0), (0, 1, 0))),
          ((1, 0, 0), (0, 1, 0)))
    check('circular: width axis for the dimension placer', (cc.width_axis(u'X'), cc.width_axis(u'Y')), (u'Y', u'X'))
    check('circular: diameter parameter guessed', fc.guess_diameter_param([u'Width', u'BIM_DIM_Diameter']), u'BIM_DIM_Diameter')
    check('circular: the saved style decides, on either tab (1.14.0: circular hangers)', (cc.is_circ({u'style': u'circ', u'mode': u'floor'}),
          cc.is_circ({u'style': u'circ', u'mode': u'hang'}), cc.is_circ({u'style': u'rect', u'mode': u'floor'})), (True, True, False))
    q = (mm(1000), 0.0, mm(3000))
    cands = [(mm(57.15), (0.0, mm(3), mm(2950)), (1, 0, 0), u'round face'),       # the ring, axis along the pipe
             (mm(62.15), (0.0, mm(3), mm(2950)), (1, 0, 0), u'round face'),       # its outside
             (mm(57.15), (mm(1000), 0.0, mm(500)), (0, 0, 1), u'arc'),            # a round base plate (axis up)
             (mm(10), (mm(1000), 0.0, mm(2900)), (0, 1, 0), u'arc'),              # a bolt
             (mm(57.15), (0.0, mm(900), mm(3000)), (1, 0, 0), u'arc')]            # another pipe's ring, far away
    ring = cc.pick_ring(cands, mm(57.15), q, (1, 0, 0))
    check('circular: the ring is picked out of the family geometry',
          ring and (round(ring['z'] * MM, 1), round(ring['r'] * MM, 2), round(ring['off'] * MM, 1), ring['along']),
          (2950.0, 57.15, 3.0, 1.0))
    across = cc.pick_ring([(mm(57.15), (mm(1000), mm(-200), mm(3000)), (0, 1, 0), u'arc')], mm(57.15), q, (1, 0, 0))
    check('circular: a ring facing across the pipe is told apart', across and round(across['along'], 3), 0.0)
    check('circular: nothing ring-like - no ring', cc.pick_ring(cands[2:4], mm(57.15), q, (1, 0, 0)), None)
    check('a family is set up once saved', (fc.configured({u'A': {}}, u'A'), fc.configured({}, u'A')), (True, False))
    check('connectors on one face give no run', fc.inline_direction([((0, 0, 0), (1, 0, 0)), ((0, 1, 0), (1, 0, 0))]), None)
    check('settings carry extend_place', core.load_settings('/nonexistent/x.txt').get(u'extend_place'), u'1')
    return [c for c in out if c is not None]


def run(quiet=False):
    bad = 0
    res = cases()
    for name, ok, got, want in res:
        if not ok:
            bad += 1
            print('FAIL %s: got %r want %r' % (name, got, want))
    if not quiet:
        print('%d checks, %d failed' % (len(res), bad))
    return bad


def selftest():
    breaks = [
        ('end_off ignored', lambda: core.DEFAULTS.__setitem__(u'end_off', u'900')),
        ('spacing shrunk', lambda: core.DEFAULTS.__setitem__(u'spacing', u'900')),
        ('takeoff_max zero', lambda: core.DEFAULTS.__setitem__(u'takeoff_max', u'0')),
    ]
    fails = 0
    for name, brk in breaks:
        saved = dict(core.DEFAULTS)
        global CFG
        old = CFG
        brk()
        CFG = core.plan_config(dict(core.DEFAULTS))
        caught = run(quiet=True) > 0
        core.DEFAULTS.clear()
        core.DEFAULTS.update(saved)
        CFG = old
        print('%-22s %s' % (name, 'caught' if caught else 'MISSED'))
        if not caught:
            fails += 1
    # function swaps: each returns the original so it can be put back
    def swap(name, fn):
        old = getattr(core, name)
        setattr(core, name, fn(old))
        return lambda: setattr(core, name, old)
    def cswap(name, fn):
        old = getattr(cc, name)
        setattr(cc, name, fn(old))
        return lambda: setattr(cc, name, old)
    pal = core.PALETTES[u'dark']
    patches = [
        ('drawer slot ignored', lambda: swap('shrunk_top', lambda f: (lambda a, b, c, slot=0, gap=8.0: f(a, b, c, 0, gap)))),
        ('drawer forgets where', lambda: swap('expand_top', lambda f: (lambda s0, l, h, b, fh, t, wh: f(0.0, l, h, b, fh, t, wh)))),
        ('search any word', lambda: swap('match_words', lambda f: (lambda t, q: any(w in (t or u'').lower()
                                                                                     for w in (q or u'').lower().split()) or not q))),
        ('sheet views doubled', lambda: swap('chosen_views', lambda f: (lambda v, sk, sh: list(v) + [x for k in sk for r in sh
                                                                                                 if r['key'] == k for x in r['views']]))),
        ('ring height plus half', lambda: cswap('support_height', lambda f: (lambda z, s: z - s + 0.2))),
        ('ring check sign', lambda: cswap('ring_off', lambda f: (lambda rz, zc: zc - rz))),
        ('ring axis ignored', lambda: cswap('pick_ring', lambda f: (lambda c, w, q, a: f([(r, ce, (1, 0, 0), k) for r, ce, _a, k in c], w, q, a)))),
        ('faint muted text', lambda: (pal.__setitem__(u'Muted', u'#7B8290'), lambda: pal.__setitem__(u'Muted', u'#ABB3BF'))[1]),
    ]
    for name, brk in patches:
        undo = brk()
        try:
            caught = run(quiet=True) > 0
        finally:
            undo()
        print('%-22s %s' % (name, 'caught' if caught else 'MISSED'))
        if not caught:
            fails += 1
    return fails


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(1 if selftest() else 0)
    sys.exit(1 if run() else 0)
