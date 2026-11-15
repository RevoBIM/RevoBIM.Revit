# -*- coding: utf-8 -*-
"""Prove the step prompt's timing and the family profiles, outside Revit.

Run by import_check.py; returns (label, passed) pairs. Not loaded by the tool.
"""
import importlib
import os
import shutil
import sys
import tempfile


def run(here):
    sys.path.insert(0, here)
    try:
        bp = importlib.import_module('bwic_prompt')
        fm = importlib.import_module('bwic_families')
    finally:
        sys.path.pop(0)
    checks = []

    def ok(label, cond):
        checks.append((label, bool(cond)))

    # -- the step prompt ---------------------------------------------------
    def shown(result):
        if result is None:
            return None
        return result[0] if result[0] == 'hide' else result[1]['title']

    s = bp.PromptState()
    ok('a step shows', shown(s.step({'number': 1, 'total': 2,
                                     'title': 'Select'})) == 'Select')
    ok('the next step replaces it',
       shown(s.step({'number': 2, 'total': 2, 'title': 'Wall'})) == 'Wall')
    r = s.flash('placed', {'title': 'BWIC placed'})
    ok('placed shows at once', shown(r) == 'BWIC placed')
    ok('placed lasts two seconds', r[1]['seconds'] == 2.0)
    ok('placed is green', r[1]['accent'] == 'green')
    ok('the next step waits for the flash',
       s.step({'number': 1, 'total': 2, 'title': 'Select'}) is None)
    ok('and shows when it ends', shown(s.flash_over()) == 'Select')
    ok('done hides the prompt', shown(s.done()) == 'hide')
    ok('done twice is harmless', s.done() is None)

    s = bp.PromptState()
    s.flash('placed', {'title': 'BWIC placed'})
    ok('done during the flash lets it finish', s.done() is None)
    ok('then the prompt closes', shown(s.flash_over()) == 'hide')

    s = bp.PromptState()
    s.flash('placed', {'title': 'BWIC placed'})
    s.done()
    s.step({'number': 1, 'total': 2, 'title': 'Select'})
    ok('a new run after done still gets its step',
       shown(s.flash_over()) == 'Select')

    s = bp.PromptState()
    r = s.flash('problem', {'title': 'Not placed'})
    ok('a problem is orange and lasts longer',
       r[1]['accent'] == 'orange' and r[1]['seconds'] > 2.0)
    ok('a timer firing late does nothing',
       s.flash_over() is not None and s.flash_over() is None)

    s = bp.PromptState()
    r = s.flash('note', {'detail': 'Pick a family first.'})
    ok('a note shows and times out', r[0] == 'show' and r[1]['seconds'] > 0)
    ok('a note has no hint', bp.hint_text(r[1]) == '')
    ok('a note closes when its time is up', s.flash_over() == ('hide', None))

    look = bp.step_look({'number': 2, 'total': 3, 'ends': 'finish'})
    ok('the eyebrow counts the steps', look['eyebrow'] == 'STEP 2 OF 3')
    ok('a selection step says Finish', 'Finish' in bp.hint_text(look))
    ok('a click step says single click', 'Single click' in bp.hint_text(
        bp.step_look({'ends': 'click'})))
    ok('every step says Esc', 'Esc' in bp.hint_text(look))
    ok('dots show progress', bp.dots(look).count(u'●') == 2)
    ok('a flash has no hint', bp.hint_text(r[1]) == '')

    # -- family profiles -------------------------------------------------------
    bgl = ['BGL_Height', 'BGL_Length', 'BGL_Width']
    today = {'wall_family': 'BWIC', 'wall_length_param': 'BGL_Length',
             'wall_width_param': 'BGL_Width',
             'wall_height_param': 'BGL_Height', 'slab_family': 'Rect',
             'slab_width_param': 'BGL_Width', 'slab_length_param': 'BGL_Height',
             'slab_circ_family': 'Circ', 'slab_circular_param': 'BGL_Diameter'}
    p = fm.seed_profile('wall', today, bgl)
    ok('a working family keeps its mapping',
       (p['roles']['through'], p['roles']['across'], p['roles']['height'])
       == ('BGL_Length', 'BGL_Width', 'BGL_Height'))
    ok('it starts rectangular', p['shape'] == fm.RECT)
    other = fm.seed_profile('wall', today, ['Sleeve Depth', 'Opening Width',
                                            'Opening Height'])
    ok('a new family is guessed by name',
       other['roles']['through'] == 'Sleeve Depth'
       and other['roles']['across'] == 'Opening Width')
    plan = fm.seed_profile('slab_rect', {}, ['BGL_Width', 'BGL_Height'])
    ok('plan width and depth never share a parameter',
       plan['roles']['plan_x'] != plan['roles']['plan_y'])
    both = fm.seed_profile('slab_rect', {}, ['Opening Width Depth'])
    ok('a guess never puts one parameter in two sizes',
       both['roles']['plan_x'] == 'Opening Width Depth'
       and both['roles']['plan_y'] == '')
    sleeve = fm.seed_profile('slab_circ', {}, ['Sleeve Radius'])
    ok('a radius parameter is recognised', sleeve['radius'] is True)
    ok('half a diameter is the radius', fm.round_value(200.0, True) == 100.0)
    ok('a pipe hole is its outside diameter plus the gap each side',
       fm.round_hole_mm(114.3, 0, 0, 50, 10) == 220.0)
    ok('a group hole encloses the corners of its cross-section',
       fm.round_hole_mm(None, 300, 400, 50, 10) == 600.0)
    ok('exact sizes are not rounded up a step',
       fm.round_hole_mm(100.0, 0, 0, 50, 10) == 200.0)
    ok('a diameter is left alone', fm.round_value(200.0, False) == 200.0)

    ok('a good profile has no problems', fm.problems('wall', p, bgl) == [])
    gap = {'shape': fm.RECT, 'roles': {'through': 'BGL_Length',
                                       'across': '', 'height': 'BGL_Height'}}
    ok('a missing required size is a problem',
       any('no parameter' in x for x in fm.problems('wall', gap, bgl)))
    twice = {'shape': fm.RECT, 'roles': {'through': 'BGL_Length',
                                         'across': 'BGL_Width',
                                         'height': 'BGL_Width'}}
    ok('one parameter for two sizes is a problem',
       any('both use' in x for x in fm.problems('wall', twice, bgl)))
    ok('position roles are optional',
       fm.problems('slab_rect', plan, ['BGL_Width', 'BGL_Height']) == [])

    ok('no profile changes nothing', fm.overlay(today, 'wall', {}) == today)
    ok('another family\'s profile changes nothing',
       fm.overlay(today, 'wall', {'Other': p}) == today)
    today['wall_circ_family'] = 'Sleeve'
    round_wall = {'Sleeve': {'shape': fm.CIRC, 'radius': True,
                             'roles': {'through': 'L', 'diameter': 'R'}}}
    o = fm.overlay(today, 'wall_circ', round_wall)
    ok('a round wall family writes its own keys',
       o['wall_circ_diameter_param'] == 'R'
       and o['wall_circ_length_param'] == 'L')
    ok('and says it is sized by radius', o['wall_circ_radius'] == 'yes')
    ok('the rectangular wall family is left alone',
       o['wall_length_param'] == 'BGL_Length'
       and o['wall_width_param'] == 'BGL_Width')
    ok('the rectangular wall slot is rectangular only',
       fm.SLOT_SHAPES['wall'] == (fm.RECT,))
    ok('a profile saved round on the rectangular slot is read as '
       'rectangular', fm.overlay(
           today, 'wall', {'BWIC': {'shape': fm.CIRC, 'roles': {
               'across': 'X'}}})['wall_width_param'] == 'BGL_Width')
    ok('the settings passed in are not changed',
       'wall_circ_diameter_param' not in today
       and 'wall_circ_radius' not in today)
    c = fm.overlay(today, 'slab_circ', {'Circ': {'shape': fm.CIRC,
                                                 'roles': {'diameter': 'D'}}})
    ok('the circular slot uses its own family',
       c['slab_circular_param'] == 'D' and c['slab_width_param'] == 'BGL_Width')

    folder = tempfile.mkdtemp()
    try:
        path = os.path.join(folder, 'new folder', 'profiles.json')
        ok('a missing file loads empty', fm.load(path) == {})
        fm.save(path, {'BWIC': p})
        ok('profiles survive a save', fm.load(path) == {'BWIC': p})
        ok('no temporary file is left', not os.path.exists(path + '.tmp'))
        with open(path, 'w') as handle:
            handle.write('{not json')
        ok('a damaged file loads empty rather than failing', fm.load(path) == {})
    finally:
        shutil.rmtree(folder, ignore_errors=True)

    # -- split (X+ / X-) families ------------------------------------------
    wlg = ['WLG_X_Minus', 'WLG_X_Plus', 'WLG_Y_Minus', 'WLG_Y_Plus',
           'WLG_Z_Minus', 'WLG_Z_Plus']
    pair = fm.encode_split('WLG_X_Minus', 'WLG_X_Plus')
    ok('a pair survives the trip through settings',
       fm.decode_split(pair) == ('WLG_X_Minus', 'WLG_X_Plus'))
    ok('an ordinary name is not a pair', fm.decode_split('BGL_Width') is None)
    halves = fm.split_parts(pair)
    ok('each side takes half the size', [h[1] for h in halves] == [0.5, 0.5])
    ok('so the two add up to the overall size', sum(h[1] for h in halves) == 1)
    ok('an ordinary name takes the whole size',
       fm.split_parts('BGL_Width') == [('BGL_Width', 1.0)])
    guessed = fm.guess_split('wall', wlg)
    ok('pairs are found by name',
       guessed['x'] == {'minus': 'WLG_X_Minus', 'plus': 'WLG_X_Plus'}
       and guessed['z'] == {'minus': 'WLG_Z_Minus', 'plus': 'WLG_Z_Plus'})
    ok('an axis letter inside a word is not an axis',
       fm.guess_split('wall', ['Max_Plus', 'Box_Minus'])['x']
       == {'minus': '', 'plus': ''})
    seeded = fm.seed_profile('wall', {}, wlg)
    ok('a family of pairs starts as X+ / X-', seeded['drive'] == fm.SPLIT)
    ok('a standard family starts as standard',
       fm.seed_profile('wall', today, bgl)['drive'] == fm.STANDARD)
    o = fm.overlay({'wall_family': 'WLG'}, 'wall', {'WLG': seeded})
    ok('X drives the width', o['wall_width_param']
       == fm.encode_split('WLG_X_Minus', 'WLG_X_Plus'))
    ok('Y drives the length', o['wall_length_param']
       == fm.encode_split('WLG_Y_Minus', 'WLG_Y_Plus'))
    ok('Z drives the height', o['wall_height_param']
       == fm.encode_split('WLG_Z_Minus', 'WLG_Z_Plus'))
    so = fm.overlay({'slab_family': 'WLG'}, 'slab_rect',
                    {'WLG': fm.seed_profile('slab_rect', {}, wlg)})
    ok('on a slab X and Y are the plan sizes and Z the height',
       so['slab_width_param'].endswith('WLG_X_Plus')
       and so['slab_length_param'].endswith('WLG_Y_Plus')
       and so['slab_height_param'].endswith('WLG_Z_Plus'))
    ok('a good split profile has no problems',
       fm.problems('wall', seeded, wlg) == [])
    half = dict(seeded, split={'x': {'minus': 'WLG_X_Minus', 'plus': ''},
                               'z': seeded['split']['z']})
    ok('half a pair is a problem',
       any('both a Minus and a Plus' in x for x in fm.problems('wall', half)))
    same = dict(seeded, split={'x': {'minus': 'A', 'plus': 'A'},
                               'z': seeded['split']['z']})
    ok('one parameter for both sides is reported once',
       len([x for x in fm.problems('wall', same) if '"A"' in x]) == 1)
    ok('a missing required axis is a problem',
       any('Z = Height has no' in x for x in fm.problems(
           'wall', dict(seeded, split={'x': seeded['split']['x']}))))
    ok('a split profile left on standard uses its standard names',
       fm.overlay({'wall_family': 'W'}, 'wall', {'W': dict(
           seeded, drive=fm.STANDARD, roles={'across': 'BGL_Width'})})
       ['wall_width_param'] == 'BGL_Width')
    ok('round slots split only their thickness through, as Y',
       [a for a, _, _ in fm.SPLIT_AXES['wall_circ']] == ['y']
       and fm.SPLIT_AXES['wall_circ'][0][2] == 'through'
       and fm.SPLIT_AXES['slab_circ'][0][2] == 'vertical')
    ok('the strip says Y+ / Y- on a round family',
       fm.SPLIT_LABEL['wall_circ'] == 'Y+ / Y-'
       and fm.SPLIT_LABEL['wall'] == 'X+ / X-')
    sleeve = ['Sleeve_Diameter', 'WLG_Y_Minus', 'WLG_Y_Plus']
    rs = fm.seed_profile('wall_circ', {}, sleeve)
    ok('a round family with a Y pair starts as Y+ / Y-',
       rs['drive'] == fm.SPLIT)
    ok('and keeps its diameter', rs['roles']['diameter'] == 'Sleeve_Diameter')
    ro = fm.overlay({'wall_circ_family': 'S'}, 'wall_circ', {'S': rs})
    ok('the Y pair drives the thickness through the wall',
       ro['wall_circ_length_param']
       == fm.encode_split('WLG_Y_Minus', 'WLG_Y_Plus'))
    ok('while the diameter stays a single parameter',
       ro['wall_circ_diameter_param'] == 'Sleeve_Diameter')
    so = fm.overlay({'slab_circ_family': 'S'}, 'slab_circ',
                    {'S': fm.seed_profile('slab_circ', {}, sleeve)})
    ok('on a round slab family it drives the height through the floor',
       so['slab_height_param'].endswith('WLG_Y_Plus'))
    ok('a round family in Y+ / Y- still needs its diameter',
       any('Diameter' in x for x in fm.problems('wall_circ', dict(
           rs, roles=dict(rs['roles'], diameter='')), sleeve)))
    ok('Y+ / Y- with no pair says so',
       any('No Minus / Plus pair' in x for x in fm.problems('wall_circ', dict(
           rs, split={'y': {'minus': '', 'plus': ''}}), sleeve)))
    ok('a plain sleeve stays standard', fm.seed_profile(
        'wall_circ', {}, ['Sleeve_Diameter', 'Sleeve_Length'])['drive']
       == fm.STANDARD)
    ok('the round card names its diameter and its pair',
       fm.summary('wall_circ', rs) == 'Round, Y+ / Y-: Diameter '
       'Sleeve_Diameter, Y WLG_Y_Minus + WLG_Y_Plus')

    # -- resize: the picked BWIC's own family decides -------------------------
    chosen = {'wall_family': 'BGL_Rect', 'wall_circ_family': 'BGL_Round',
              'wall_width_param': 'BGL_Width',
              'wall_length_param': 'BGL_Length',
              'wall_height_param': 'BGL_Height'}
    ok('a family chosen on a tab is that slot',
       fm.slot_for_family('BGL_Round', 'wall', chosen) == 'wall_circ'
       and fm.slot_for_family('BGL_Rect', 'wall', chosen) == 'wall')
    ok('a saved round profile makes another family round',
       fm.slot_for_family('Other', 'wall', chosen,
                          {'shape': fm.CIRC}) == 'wall_circ')
    ok('a family with a diameter and no width reads as round',
       fm.slot_for_family('Other', 'slab', {}, None,
                          ['Dia', 'Sleeve Diameter']) == 'slab_circ')
    ok('a family with widths reads as rectangular',
       fm.slot_for_family('Other', 'slab', {}, None,
                          ['Width', 'Depth', 'Diameter']) == 'slab_rect')
    ok('X+ / X- pairs read as rectangular',
       fm.slot_for_family('Other', 'wall', {}, None, wlg) == 'wall')
    slot, values, saved = fm.settings_for_family(
        'WLG', 'wall', chosen, {'WLG': seeded}, wlg)
    ok('a saved X+ / X- profile is used for the resize',
       saved and slot == 'wall' and values['wall_width_param']
       == fm.encode_split('WLG_X_Minus', 'WLG_X_Plus'))
    custom = {'shape': fm.RECT, 'drive': fm.STANDARD,
              'roles': {'across': 'Opening_Breadth', 'height': 'Opening_Rise',
                        'through': 'Opening_Deep'}}
    slot, values, saved = fm.settings_for_family(
        'Custom', 'wall', chosen, {'Custom': custom},
        ['Opening_Breadth', 'Opening_Rise', 'Opening_Deep'])
    ok('saved settings win over anything a guess could find',
       saved and values['wall_width_param'] == 'Opening_Breadth'
       and values['wall_height_param'] == 'Opening_Rise')
    slot, values, saved = fm.settings_for_family(
        'BGL_Rect', 'wall', chosen, {}, ['BGL_Length', 'BGL_Width',
                                         'BGL_Height'])
    ok('the default family with nothing saved keeps today\'s names',
       not saved and values['wall_width_param'] == 'BGL_Width'
       and values['wall_length_param'] == 'BGL_Length')
    slot, values, saved = fm.settings_for_family(
        'Sleeve', 'wall', chosen, {}, ['Sleeve Diameter', 'Sleeve Length'])
    ok('an unset round family is sized by its own parameters',
       slot == 'wall_circ'
       and values['wall_circ_diameter_param'] == 'Sleeve Diameter')
    ok('resizing never changes the settings passed in',
       chosen.get('wall_circ_diameter_param') is None)
    ok('the card says it is split',
       fm.summary('wall', seeded).startswith('X+ / X-'))
    ok('a pair reads as Minus + Plus', fm.show_name(pair)
       == 'WLG_X_Minus + WLG_X_Plus')

    # -- the family's own workset --
    ok('a family with no workset follows Settings',
       fm.workset_choice(fm.family_workset('X', {}), 'M-BWIC') == 'M-BWIC')
    ok('a family\'s workset wins over Settings',
       fm.workset_choice(fm.family_workset(
           'X', {'X': {'workset': 'E-BWIC'}}), 'M-BWIC') == 'E-BWIC')
    ok('a family set to the active workset ignores Settings',
       fm.workset_choice(fm.ACTIVE_WORKSET, 'M-BWIC') is None)
    ok('nothing chosen anywhere means the active workset',
       fm.workset_choice(fm.FOLLOW_SETTINGS, None) is None)
    ok('the card names the family\'s workset',
       fm.summary('wall', {'shape': fm.RECT, 'roles': {},
                           'workset': 'E-BWIC'}).endswith('Workset: E-BWIC'))
    ok('the card says nothing of a workset that follows Settings',
       'Workset' not in fm.summary('wall', {'shape': fm.RECT, 'roles': {}}))
    over = fm.overlay({'wall_family': 'X'}, 'wall',
                      {'X': {'shape': fm.RECT, 'roles': {},
                             'workset': fm.ACTIVE_WORKSET}})
    ok('the workset reaches Global Placement through the settings',
       over.get('family_workset') == fm.ACTIVE_WORKSET)
    ok('a family with nothing saved leaves the workset alone',
       'family_workset' not in fm.overlay({'wall_family': 'X'}, 'wall', {}))

    # -- Family settings first; set-up families green and first --
    saved = {'Box': {'shape': fm.RECT}, 'Alpha': {'shape': fm.RECT}}
    ok('a family with saved settings is set up', fm.is_set('Box', saved))
    ok('a family without is not', not fm.is_set('Sleeve', saved))
    ok('no family chosen is not set up', not fm.is_set('', saved))
    ok('set-up families come first, in order, the rest as they were',
       fm.set_first(['Zed', 'Box', 'Mid', 'Alpha'], saved)
       == ['Alpha', 'Box', 'Zed', 'Mid'])
    ok('clearance starts at 50 mm', fm.clearance_for('Unset', {}) == 50.0)
    ok('a blanked clearance box is flagged',
       fm.clearance_problem('') is not None)
    ok('a profile saved before clearance existed uses 50 mm, no problem',
       fm.clearance_problem(None) is None
       and fm.clearance_for('Old', {'Old': {'shape': fm.RECT}}) == 50.0)
    from bwic_prompt import PromptState
    blocked = PromptState().flash('blocked', {'title': 'x'})[1]
    ok('a refused run shows orange, long enough to read',
       blocked['accent'] == 'orange' and blocked['seconds'] >= 5)

    # -- a clearance per family --
    own = {'Big': {'clearance_mm': '75'}, 'Blank': {'clearance_mm': ''},
           'Bad': {'clearance_mm': 'fifty'}, 'Zero': {'clearance_mm': '0'}}
    ok('a family with its own clearance uses it',
       fm.clearance_for('Big', own, 50.0) == 75.0)
    ok('a blank clearance follows the tab',
       fm.clearance_for('Blank', own, 50.0) == 50.0)
    ok('a family with no settings follows the tab',
       fm.clearance_for('Other', own, 40.0) == 40.0)
    ok('a clearance that is not a number follows the tab',
       fm.clearance_for('Bad', own, 50.0) == 50.0)
    ok('a clearance of 0 is kept, not taken as blank',
       fm.clearance_for('Zero', own, 50.0) == 0.0)
    ok('a negative clearance is refused', fm.clearance_value('-5') is None)
    ok('Family settings says when a clearance is not a number',
       any('Clearance' in p for p in fm.problems(
           'wall', {'shape': fm.RECT, 'roles': {'across': 'W', 'height': 'H',
                                                 'through': 'L'},
                    'clearance_mm': 'fifty'})))
    ok('the card names the family\'s clearance',
       'Clearance 75 mm' in fm.summary('wall', {'shape': fm.RECT, 'roles': {},
                                               'clearance_mm': '75'}))
    ok('Global Placement is given the family\'s clearance',
       fm.overlay({'wall_family': 'Big'}, 'wall',
                  {'Big': {'shape': fm.RECT, 'roles': {},
                           'clearance_mm': '75'}})['family_clearance'] == '75')

    # -- the Options Bar's Finish button, and nothing like it --
    from bwic_prompt import is_finish_label
    ok('"Finish" is the Finish button', is_finish_label('Finish'))
    ok('"&Finish" (an access key) is the Finish button',
       is_finish_label('&Finish'))
    ok('"Finish Edit Mode" is not', not is_finish_label('Finish Edit Mode'))
    ok('"Finished" is not', not is_finish_label('Finished'))
    ok('a blank is not', not is_finish_label('') and
       not is_finish_label(None))

    # -- Finish Selection only when a step is waiting on it --
    from bwic_prompt import finish_armed
    ok('Finish lights up at a step that ends with Finish',
       finish_armed('step', {'ends': 'finish'}, False))
    ok('Finish stays dim at a single-click step',
       not finish_armed('step', {'ends': 'click'}, True))
    ok('placing a BWIC disarms Finish',
       not finish_armed('placed', {}, True))
    ok('a problem disarms Finish', not finish_armed('problem', {}, True))
    ok('the end of the run disarms Finish', not finish_armed('done', {}, True))
    ok('a note leaves Finish as it was',
       finish_armed('note', {}, True) and not finish_armed('note', {}, False))

    # -- rectangular lists show rectangular families, circular circular --
    ok('a Diameter parameter makes a family circular',
       fm.family_shape(['BGL_Length', 'BGL_Diameter']) == fm.CIRC)
    ok('a Radius parameter makes a family circular',
       fm.family_shape(['Sleeve Radius']) == fm.CIRC)
    ok('width, height and length only is rectangular',
       fm.family_shape(['BGL_Width', 'BGL_Height', 'BGL_Length']) == fm.RECT)
    ok('X+ / X- pairs are rectangular',
       fm.family_shape(['WLG_X_Minus', 'WLG_X_Plus']) == fm.RECT)
    ok('an unplaced family named circular counts as circular',
       fm.family_shape([], 'BGL_BWIC_Circular', placed=False) == fm.CIRC)
    ok('a placed family is judged by its parameters, not its name',
       fm.family_shape(['BGL_Width'], 'Round_Edge_Box', placed=True)
       == fm.RECT)
    listed = [('Box',), ('Sleeve',), ('Mystery',)]
    shapes = {'Box': fm.RECT, 'Sleeve': fm.CIRC}
    ok('the rectangular wall list leaves the circular family out',
       [e[0] for e in fm.families_for_slot('wall', listed, shapes)]
       == ['Box', 'Mystery'])
    ok('the circular slab list leaves the rectangular family out',
       [e[0] for e in fm.families_for_slot('slab_circ', listed, shapes)]
       == ['Sleeve', 'Mystery'])

    # -- only the part of a run inside the wall sizes the opening --
    span = fm.wall_span(-1000.0, 500.0, 50.0)
    ok('a run crossing the wall counts only its length inside it',
       abs(span[0] - 950.0 / 1500) < 1e-9 and abs(span[1] - 1050.0 / 1500)
       < 1e-9)
    ok('a run crossing the other way gives the same stretch',
       fm.wall_span(500.0, -1000.0, 50.0) == (450.0 / 1500, 550.0 / 1500))
    ok('a run parallel to the wall counts whole', fm.wall_span(20.0, 20.0,
                                                               50.0) is None)
    ok('a run stopping short of the wall counts its nearest end',
       fm.wall_span(-900.0, -300.0, 50.0) == (1.0, 1.0))
    ok('a run ending inside the wall counts up to its end',
       fm.wall_span(-600.0, 0.0, 50.0) == (550.0 / 600, 1.0))
    # a 110 pipe falling 1:40 over 1.5 m, wall 100 thick: whole run measures
    # 110 + 37.5 high, inside the wall 110 + 2.5
    fall = 1500.0 / 40
    t_in, t_out = fm.wall_span(-750.0, 750.0, 50.0)
    ok('a drainage fall outside the wall does not grow the height',
       abs(110 + fall * (t_out - t_in) - 112.5) < 1e-9)

    # -- a workset per sub tab --
    both = {'X': {'drive': fm.SPLIT, 'roles': {},
                  'worksets': {fm.STANDARD: 'M-BWIC', fm.SPLIT: 'E-BWIC'}}}
    ok('a family set to X+ / X- uses that sub tab\'s workset',
       fm.family_workset('X', both) == 'E-BWIC')
    both['X']['drive'] = fm.STANDARD
    ok('a family set to Standard uses Standard\'s workset',
       fm.family_workset('X', both) == 'M-BWIC')
    ok('a sub tab with no workset follows Settings',
       fm.profile_worksets({'worksets': {fm.STANDARD: 'M-BWIC'}})[fm.SPLIT]
       == fm.FOLLOW_SETTINGS)
    ok('a 2.15.0 family workset carries to both sub tabs',
       fm.profile_worksets({'workset': 'E-BWIC'})
       == {fm.STANDARD: 'E-BWIC', fm.SPLIT: 'E-BWIC'})
    ok('the card names the workset of the sub tab in use',
       fm.summary('wall_circ', {'shape': fm.CIRC, 'roles': {},
                                'drive': fm.SPLIT,
                                'worksets': {fm.SPLIT: 'P-BWIC'}})
       .endswith('Workset: P-BWIC'))
    ok('Global Placement is given the sub tab\'s workset',
       fm.overlay({'wall_family': 'X'}, 'wall', both)['family_workset']
       == 'M-BWIC')

    ok('every slot has roles and shapes',
       all(fm.ROLES.get(slot) and fm.SLOT_SHAPES.get(slot)
           for slot, _, _, _ in fm.SLOTS))
    ok('every shape a slot offers has a required size',
       all(any(r[6] for r in fm.roles_for(slot, shape))
           for slot, _, _, _ in fm.SLOTS for shape in fm.SLOT_SHAPES[slot]))
    return checks


if __name__ == '__main__':
    for label, passed in run(os.path.dirname(os.path.abspath(__file__))):
        sys.stdout.write('{}  {}\n'.format('ok  ' if passed else 'FAIL', label))
