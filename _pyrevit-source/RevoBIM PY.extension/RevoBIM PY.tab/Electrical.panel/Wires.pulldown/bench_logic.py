# -*- coding: utf-8 -*-
"""RevoBIM PY - Wires: logic bench.

The rules themselves, run under plain CPython against the same stub API that
import_check.py builds. Ships beside the tool because an earlier set of these
tests lived in a scratch folder and was lost with it.

    python bench_logic.py

Exit code 0 means every check passed.
"""

from __future__ import print_function

import ast
import io
import math
import os
import sys
import importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

_spec = importlib.util.spec_from_file_location(
    'import_check', os.path.join(HERE, 'import_check.py'))
_check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_check)
_check.install_stub_api()

import wires_core as core       # noqa: E402
import circuit_core as cc       # noqa: E402
import results_window           # noqa: E402

PASSED = []
_SOURCE = {}


def source_of(file_name):
    if file_name not in _SOURCE:
        _SOURCE[file_name] = io.open(os.path.join(HERE, file_name),
                                     encoding='utf-8').read()
    return _SOURCE[file_name]


def function_source(file_name, name):
    """One function's own source, by its real boundaries.

    Slicing from `def foo(` to the end of the file was how an earlier version
    of these checks worked, and it silently swallowed every function written
    after it - so a rule about what `foo` may call started failing because of
    something `bar` does.
    """
    text = source_of(file_name)
    lines = text.splitlines(True)
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            end = getattr(node, 'end_lineno', None)
            if end is None:
                end = len(lines)
            return ''.join(lines[node.lineno - 1:end])
    raise AssertionError('{0} has no function {1}'.format(file_name, name))


def check(label, condition, detail=''):
    if not condition:
        raise AssertionError('{0} {1}'.format(label, detail))
    PASSED.append(label)


class P(object):
    def __init__(self, x, y, z=0.0):
        self.X = float(x)
        self.Y = float(y)
        self.Z = float(z)


core.XYZ = P
MM = core.MM


def mp(x, y):
    return P(x * MM, y * MM)


def mm(value):
    return core.to_mm(value)


class View(object):
    Scale = 50
    IsTemplate = False


# ---------------------------------------------------------------------------
# the arc
# ---------------------------------------------------------------------------
def arc_tests():
    a, b = mp(0, 0), mp(4000, 0)
    depth = core.mm(600)

    points = core.arc_through(a.X, a.Y, b.X, b.Y, depth, 'left', 1, 0.0)
    check('one vertex gives start, middle, end', len(points) == 3)
    check('the middle sits mid-span', abs(mm(points[1].X) - 2000) < 1e-6)
    check('at exactly the depth asked for', abs(mm(points[1].Y) - 600) < 1e-6)

    half, d = 2000.0, 600.0
    radius = (half * half + d * d) / (2 * d)
    centre = (2000.0, d - radius)
    for count in (1, 2, 3, 5, 8):
        points = core.arc_through(a.X, a.Y, b.X, b.Y, depth, 'left', count, 0.0)
        radii = [math.hypot(mm(p.X) - centre[0], mm(p.Y) - centre[1])
                 for p in points]
        steps = [math.hypot(mm(points[i + 1].X) - mm(points[i].X),
                            mm(points[i + 1].Y) - mm(points[i].Y))
                 for i in range(len(points) - 1)]
        check('{0} vertices all on one circle'.format(count),
              max(radii) - min(radii) < 1e-6)
        check('{0} vertices evenly splayed along it'.format(count),
              max(steps) - min(steps) < 1e-6)
        check('{0} vertices do not deepen the arc'.format(count),
              max(mm(p.Y) for p in points) <= 600 + 1e-6)

    right = core.arc_through(a.X, a.Y, b.X, b.Y, depth, 'right', 1, 0.0)
    check('right mirrors left', abs(mm(right[1].Y) + 600) < 1e-6)

    for span in (800, 4000, 12000):
        got = core.sagitta(View(), 'span', 18, core.mm(span))
        check('depth is 18% of a {0}mm span'.format(span),
              abs(100 * mm(got) / span - 18) < 1e-6)
    check('paper depth scales with the view',
          abs(mm(core.sagitta(View(), 'paper', 3, core.mm(4000))) - 150) < 1e-6)
    check('depth clamped under the half-chord',
          mm(core.sagitta(View(), 'span', 400, core.mm(1000))) <= 490 + 1e-6)

    trimmed = core.segment_points(mp(0, 0), mp(4000, 0), 0.0, core.mm(500),
                                  'left', core.mm(300), core.mm(300), 1)
    check('trim applied at both ends',
          abs(mm(trimmed[0].X) - 300) < 1e-6 and abs(mm(trimmed[2].X) - 3700) < 1e-6)


# ---------------------------------------------------------------------------
# vertex floor and arc / chamfer
# ---------------------------------------------------------------------------
def vertex_and_wiring_tests():
    check('0 is raised to the floor of 1', core.clamp_vertices(0) == 1)
    check('a negative count is raised to 1', core.clamp_vertices(-5) == 1)
    check('1 stays 1', core.clamp_vertices(1) == 1)
    check('4 stays 4', core.clamp_vertices(4) == 4)
    check('99 is held at 8', core.clamp_vertices(99) == 8)
    check('rubbish falls back to 1', core.clamp_vertices('lots') == 1)
    check('the setting defaults to 1', core.DEFAULTS['mid_vertices'] == '1')

    check('arc is the default wiring', core.DEFAULTS['wiring_type'] == 'arc')
    check('chamfer resolves to WiringType.Chamfer',
          'Chamfer' in str(core.wiring_kind('chamfer')))
    check('arc resolves to WiringType.Arc',
          'Arc' in str(core.wiring_kind('arc')))
    check('anything unrecognised is an arc',
          'Arc' in str(core.wiring_kind('wiggly')))

    # with the floor in place, no wire can come out with no middle vertex
    for count in (0, 1, 3):
        points = core.segment_points(mp(0, 0), mp(3000, 0), 0.0, core.mm(400),
                                     'left', 0.0, 0.0,
                                     core.clamp_vertices(count))
        check('vertex count {0} still yields a bend'.format(count),
              len(points) >= 3)

    # the length mode shares out, but never below the floor
    spans = [core.mm(600), core.mm(2000), core.mm(9000)]
    spacing = core.vertex_spacing(spans, 1)
    shared = [max(core.MIN_VERTICES, core.vertices_for(s, spacing))
              for s in spans]
    check('length mode never drops a wire below 1', min(shared) >= 1,
          str(shared))
    check('length mode still gives the long span more', shared[2] > shared[0])


# ---------------------------------------------------------------------------
# chamfer
# ---------------------------------------------------------------------------
def chamfer_tests():
    a, b = mp(0, 0), mp(6000, 0)
    offset = core.mm(600)
    points = core.segment_points(a, b, 0.0, offset, 'left', 0.0, 0.0, 1,
                                 'chamfer', 45.0)
    check('chamfer is angle, straight, angle', len(points) == 4, str(len(points)))
    xs = [mm(p.X) for p in points]
    ys = [mm(p.Y) for p in points]
    check('it starts and finishes on the fittings',
          abs(xs[0]) < 1e-6 and abs(xs[3] - 6000) < 1e-6)
    check('both ends of the straight are at full offset',
          abs(ys[1] - 600) < 1e-6 and abs(ys[2] - 600) < 1e-6, str(ys))
    check('the middle really is straight', abs(ys[1] - ys[2]) < 1e-6)
    check('at 45 degrees the crank insets by the offset',
          abs(xs[1] - 600) < 1e-6 and abs(xs[2] - 5400) < 1e-6, str(xs))

    shallow = core.segment_points(a, b, 0.0, offset, 'left', 0.0, 0.0, 1,
                                  'chamfer', 30.0)
    check('a shallower angle insets further',
          mm(shallow[1].X) > 600, mm(shallow[1].X))
    steep = core.segment_points(a, b, 0.0, offset, 'left', 0.0, 0.0, 1,
                                'chamfer', 75.0)
    check('a steeper angle insets less', mm(steep[1].X) < 600, mm(steep[1].X))

    extra = core.segment_points(a, b, 0.0, offset, 'left', 0.0, 0.0, 4,
                                'chamfer', 45.0)
    check('extra vertices go along the straight', len(extra) == 6, str(len(extra)))
    middles = [mm(p.Y) for p in extra[1:-1]]
    check('and stay on it', max(middles) - min(middles) < 1e-6, str(middles))

    short = core.segment_points(mp(0, 0), mp(500, 0), 0.0, core.mm(900),
                                'left', 0.0, 0.0, 1, 'chamfer', 20.0)
    check('a short span still comes out in order',
          mm(short[0].X) <= mm(short[1].X) <= mm(short[-1].X), str([mm(p.X) for p in short]))

    right = core.segment_points(a, b, 0.0, offset, 'left', 0.0, 0.0, 1,
                                'chamfer', 45.0)
    left_y = mm(right[1].Y)
    other = core.segment_points(a, b, 0.0, offset, 'right', 0.0, 0.0, 1,
                                'chamfer', 45.0)
    check('side flips the crank', abs(mm(other[1].Y) + left_y) < 1e-6)

    arc = core.segment_points(a, b, 0.0, offset, 'left', 0.0, 0.0, 1, 'arc')
    check('arc mode is unaffected', len(arc) == 3)


# ---------------------------------------------------------------------------
# routing
# ---------------------------------------------------------------------------
def routing_tests():
    grid = [(x, y) for y in (0, 3000, 6000) for x in (0, 2000, 4000, 6000)]
    items = [('E%d' % i, mp(x, y)) for i, (x, y) in enumerate(grid)]
    options = cc.route_alternatives(items, None, True)
    best = cc._path_length([items[i][1] for i in options[0]])
    check('a 4x3 grid finds the serpentine', abs(mm(best) - 24000) < 1)
    for order in options:
        check('every route visits every light once',
              sorted(order) == list(range(len(items))))
    for order in cc.route_alternatives(items, 0, True):
        check('the run ends at the switch light', order[-1] == 0)

    room_a = [(0, 0), (2000, 0), (4000, 0), (0, 2000), (2000, 2000)]
    room_b = [(9000, 0), (11000, 0), (9000, 2000)]
    items = [('E%d' % i, mp(x, y)) for i, (x, y) in enumerate(room_a + room_b)]
    keys = ['a'] * len(room_a) + ['b'] * len(room_b)
    order, crossings, _options = cc.grouped_route(items, keys, 0, True)
    check('two legs give exactly one bridging span', len(crossings) == 1)
    check('the bridge really crosses legs',
          keys[order[crossings[0]]] != keys[order[crossings[0] + 1]])

    # clashes rank above length
    square = [('L0', mp(0, 0)), ('L1', mp(4000, 0)), ('L2', mp(4000, 4000)),
              ('L3', mp(0, 4000))]
    centre = [(50, 2000 * MM, 2000 * MM, 600 * MM)]

    def cost(order):
        length = 0.0
        clashes = 0
        for i in range(len(order) - 1):
            a = square[order[i]][1]
            b = square[order[i + 1]][1]
            length += core.plan_distance(a, b)
            clashes += cc.span_clashes(a, b, core.mm(300), 'left', centre)
        return (clashes, length)

    check('cutting the middle scores worse than the edge',
          cost([1, 3, 0, 2])[0] > cost([0, 1, 2, 3])[0])
    check('a clash-free route sorts first',
          sorted([[1, 3, 0, 2], [0, 1, 2, 3]], key=cost)[0] == [0, 1, 2, 3])


# ---------------------------------------------------------------------------
# wire types
# ---------------------------------------------------------------------------
def wire_type_tests():
    light, emerg, live = 'Lighting', 'Emergency', 'PermLive'
    order = [0, 1, 2, 3]
    crossings = set([1])
    none_marked = {0: False, 1: False, 2: False, 3: False}
    one_marked = {0: True, 1: False, 2: False, 3: False}

    picks = [cc._segment_type(i, order, crossings, none_marked, light, live,
                              emerg, False) for i in range(3)]
    check('plain circuit uses permanent live on the crossing',
          picks == [light, live, light], str(picks))

    picks = [cc._segment_type(i, order, crossings, one_marked, light, live,
                              emerg, True) for i in range(3)]
    check('an emergency circuit is emergency throughout',
          picks == [emerg, emerg, emerg], str(picks))
    check('and never permanent live', live not in picks)


# ---------------------------------------------------------------------------
# the Shuffle prompt drives a Session it is handed
# ---------------------------------------------------------------------------
def session_tests():
    source = io.open(os.path.join(HERE, 'shuffle_window.py'),
                     encoding='utf-8').read()
    called = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Attribute) and \
                isinstance(node.value, ast.Name) and node.value.id == 'session':
            called.add(node.attr)

    members = set()
    tree = ast.parse(io.open(os.path.join(HERE, 'circuit_core.py'),
                             encoding='utf-8').read())
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == 'Session':
            for item in node.body:
                if isinstance(item, ast.FunctionDef):
                    members.add(item.name)
            for inner in ast.walk(node):
                if isinstance(inner, ast.Assign):
                    for target in inner.targets:
                        if isinstance(target, ast.Attribute) and \
                                isinstance(target.value, ast.Name) and \
                                target.value.id == 'self':
                            members.add(target.attr)
    missing = sorted(name for name in called if name not in members)
    check('every Session member the prompt calls exists', not missing,
          str(missing))
    for name in ('set_wiring', 'wiring', 'set_vertices', 'vertices',
                 'set_avoid', 'avoiding', 'set_sag', 'sag'):
        check('Session.{0} exists'.format(name), name in members)

    # stepping and wiring without Revit
    class Fake(object):
        def __init__(self):
            self.variant = 0
            self.settings = dict(core.DEFAULTS)
            self.vertex_override = None
            self.wiring_override = None
            self.placed_with = []

        def place(self, variant, clear_first=False):
            self.placed_with.append((self.vertex_override, self.wiring_override))
            return 1

    for name in ('set_vertices', 'vertices', 'set_wiring', 'wiring'):
        setattr(Fake, name, getattr(cc.Session, name))

    fake = Fake()
    check('starts as arc', fake.wiring() == 'arc')
    fake.set_wiring('chamfer')
    check('switches to chamfer', fake.wiring() == 'chamfer')
    fake.set_wiring('arc')
    check('and back to arc', fake.wiring() == 'arc')
    fake.set_vertices(0)
    check('the stepper cannot go below 1', fake.vertices() == 1)
    fake.set_vertices(12)
    check('or above 8', fake.vertices() == 8)


# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------
def span_note_tests():
    class Result(object):
        def __init__(self):
            self.info = []
            self.notes = []

    result = Result()
    cc._emit_span_notes(result, 'DB1/1', {
        'trim was refused, so the wire ends sit on the connectors': 17,
        'refused - Revit returned no wire': 2,
    })
    check('a routine outcome is said once, as information',
          len(result.info) == 1 and '17 span(s)' in result.info[0],
          str(result.info))
    check('a real refusal is said once, as a note',
          len(result.notes) == 1 and '2 span(s)' in result.notes[0],
          str(result.notes))

    result = Result()
    cc._emit_span_notes(result, 'DB1/1', {'refused - no connector': 1})
    check('a single occurrence drops the count',
          'span(s)' not in result.notes[0], result.notes[0])

    result = Result()
    cc._emit_span_notes(result, 'DB1/1', {})
    check('nothing to say means nothing said',
          not result.info and not result.notes)


def modeless_tests():
    """The pieces the floating prompt depends on, without a Revit to run in."""
    source = io.open(os.path.join(HERE, 'shuffle_window.py'),
                     encoding='utf-8').read()
    check('the prompt keeps modeless windows referenced', '_LIVE' in source)
    check('closing with the X cancels', 'session.finish(False)' in source)
    check('keep and cancel both go through finish',
          'session.finish(keep)' in source)
    check('it falls back to modal without a bridge',
          'window.ShowDialog()' in source)

    for name in ('EventBridge', 'WireEventHandler'):
        check('wire_events exposes {0}'.format(name),
              name in io.open(os.path.join(HERE, 'wire_events.py'),
                              encoding='utf-8').read())

    # a floating prompt means the command returns before the run is settled
    report = core.Report('Auto Wire')
    check('a report starts undeferred', report.deferred is False)
    report.deferred = True
    for script in ('Auto Wire.pushbutton/script.py',
                   'Re-Route Wires.pushbutton/script.py'):
        text = io.open(os.path.join(HERE, script), encoding='utf-8').read()
        check('{0} sets the persistent engine'.format(script),
              '__persistentengine__ = True' in text)
        check('{0} defers its results window'.format(script),
              'not report.deferred' in text)

    # the session picks its path from the setting and never opens a group
    # on the modeless one
    check('modeless is the default',
          core.DEFAULTS['modeless_shuffle'] == 'yes')
    tree = ast.parse(io.open(os.path.join(HERE, 'circuit_core.py'),
                             encoding='utf-8').read())
    members = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == 'Session':
            for item in node.body:
                if isinstance(item, ast.FunctionDef):
                    members.add(item.name)
    for name in ('start', 'keep', 'cancel', 'finish'):
        check('Session.{0} exists'.format(name), name in members)
    for name in ('snapshot_wire', 'restore_wire', 'snapshot_tag',
                 'restore_tag'):
        check('{0} exists for the modeless cancel'.format(name),
              hasattr(cc, name))


def modeless_wiring_tests():
    """The floating path, read off the source rather than run.

    These exist because v3.0.0 shipped with `_LIVE` used and never defined: a
    silent str.replace miss left one line of a batch unapplied while the lines
    either side of it went in. Spot-checking the markers of an edit is cheap
    and catches a half-applied one.
    """
    source = io.open(os.path.join(HERE, 'shuffle_window.py'),
                     encoding='utf-8').read()
    tree = ast.parse(source)

    module_level = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    module_level.add(target.id)
    check('_LIVE is defined at module level', '_LIVE' in module_level)

    for marker in ('from wire_events import EventBridge',
                   'window.Show()', 'window.ShowDialog()',
                   "state['bridge']", 'def _close_with',
                   'session.finish(keep)', 'session.finish(False)',
                   '_redraw(move)'):
        check('the floating path has {0!r}'.format(marker[:34]),
              marker in source)

    check('the docstring describes both paths',
          'Modeless' in source and 'Modal' in source)

    # show() must return None on the floating path and a bool on the modal
    # one. Only show's OWN returns count - walking into the nested handlers
    # would let any bare `return` in one of them satisfy this.
    def own_returns(function):
        found = []

        def walk(node):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.Lambda)):
                    continue
                if isinstance(child, ast.Return):
                    found.append(child)
                walk(child)

        walk(function)
        return found

    returns = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == 'show':
            returns = own_returns(node)
    check('show has several returns of its own', len(returns) >= 3,
          str(len(returns)))
    nones = [r for r in returns
             if isinstance(r.value, ast.Constant) and r.value.value is None]
    check('one of them returns None, for the floating path', nones,
          str(len(nones)))
    check('and others return the kept flag',
          [r for r in returns if isinstance(r.value, ast.Subscript)],
          'none return state[...]')

    # and _finish must treat that None as "the prompt owns it now"
    circuits = io.open(os.path.join(HERE, 'circuit_core.py'),
                       encoding='utf-8').read()
    check('_finish defers on None', 'if kept is None:' in circuits)
    check('and marks the report deferred', 'report.deferred = True' in circuits)


def debug_tests():
    class App(object):
        pass

    report = core.Report('Auto Wire')
    report.info('Wire type: Lighting.')
    report.note('DB1/1: 5 span(s) still cross a fitting.')
    text = core.debug_report(App(), dict(core.DEFAULTS), report)
    check('the debug report names the version', core.__version__ in text)
    check('it lists the settings', 'arc_sag_percent' in text)
    check('it carries the informational lines too',
          'Wire type: Lighting.' in text)
    check('and the notes', 'still cross a fitting' in text)
    check('it survives a document it cannot read',
          'could not be read' in text)

    changed = dict(core.DEFAULTS)
    changed['mid_vertices'] = '4'
    check('a changed setting is flagged',
          '<- changed' in core.debug_report(App(), changed, report))
    check('an unchanged one is not',
          core.debug_report(App(), dict(core.DEFAULTS),
                            report).count('<- changed') == 0)
    check('the debug button is on by default',
          core.DEFAULTS['debug_report'] == 'yes')


def apply_type_tests():
    """Apply Wire Types must reach the same answer Auto Wire draws with."""

    class Id(object):
        def __init__(self, value):
            self.Value = value

    class Element(object):
        def __init__(self, eid, leg):
            self.Id = Id(eid)
            self.leg = leg

    class Connector(object):
        def __init__(self, owner):
            self.Owner = owner

    class Wire(object):
        def __init__(self, ends):
            self.Id = Id(99)
            self.ends = ends

    # stand in for the connector walk
    original_ends = cc.wire_endpoints
    try:
        cc.wire_endpoints = lambda doc, wire: wire.ends
        cc.leg_key = lambda element, doc, settings, cache=None: element.leg

        settings = dict(core.DEFAULTS)
        base, emerg, live = 'Lighting', 'Emergency', 'PermLive'
        types = (base, emerg, live)

        same_leg = Wire([Element(1, 'Office|SW1'), Element(2, 'Office|SW1')])
        other_leg = Wire([Element(1, 'Office|SW1'), Element(3, 'Corridor|SW2')])
        home_run = Wire([Element(1, 'Office|SW1')])

        got, _why = cc.wanted_wire_type(None, settings, same_leg, False, True,
                                        types, {})
        check('a wire inside one leg takes the lighting type', got == base, got)

        got, why = cc.wanted_wire_type(None, settings, other_leg, False, True,
                                       types, {})
        check('a wire bridging two legs takes permanent live', got == live, got)
        check('and says why', 'bridges' in why, why)

        got, _why = cc.wanted_wire_type(None, settings, home_run, False, True,
                                        types, {})
        check('a home run takes the base type', got == base, got)

        for wire in (same_leg, other_leg, home_run):
            got, why = cc.wanted_wire_type(None, settings, wire, True, True,
                                           types, {})
            check('an emergency circuit retypes everything to emergency',
                  got == emerg, got)
        check('even the span that bridges legs',
              cc.wanted_wire_type(None, settings, other_leg, True, True,
                                  types, {})[0] == emerg)

        # power circuits never get the lighting-only types
        got, _why = cc.wanted_wire_type(None, settings, other_leg, False, False,
                                        ('Power', emerg, live), {})
        check('a power circuit takes the power type', got == 'Power', got)

        # with no permanent live type loaded nothing changes hands
        got, _why = cc.wanted_wire_type(None, settings, other_leg, False, True,
                                        (base, emerg, None), {})
        check('no permanent live type set means the base type', got == base)

        # the two tools must agree: _segment_type and wanted_wire_type are the
        # same three questions in the same order
        order = [0, 1]
        for emergency_circuit in (False, True):
            drawn = cc._segment_type(0, order, set([0]), {0: emergency_circuit,
                                                        1: emergency_circuit},
                                     base, live, emerg, emergency_circuit)
            retyped, _why = cc.wanted_wire_type(None, settings, other_leg,
                                                emergency_circuit, True,
                                                types, {})
            check('drawn and retyped agree on a bridging span '
                  '(emergency={0})'.format(emergency_circuit),
                  drawn == retyped, '{0} vs {1}'.format(drawn, retyped))
    finally:
        cc.wire_endpoints = original_ends

    # a tool that draws nothing must not say it drew anything
    retyped = core.Report('Apply Wire Types')
    retyped.retyped = 3
    check('the summary says retyped, not drawn',
          'retyped' in retyped.summary() and 'drawn' not in retyped.summary(),
          retyped.summary())
    drawn = core.Report('Auto Wire')
    drawn.drawn = 24
    check('and a drawing run still says drawn', 'drawn' in drawn.summary(),
          drawn.summary())
    check('a run that changed nothing says so',
          core.Report('Apply Wire Types').summary() == 'Nothing to do.')

    run = function_source('circuit_core.py', 'run_apply_types')
    check('the loose-wire note is skipped when circuits were selected',
          'if loose and not chosen:' in run)
    check('the total line is skipped for a single circuit',
          'len(work) > 1' in run)
    check('it reports a retype count, not a drawn count',
          'report.retyped = total' in run and 'report.drawn' not in run)

    # the command exists and is wired up
    source = io.open(os.path.join(HERE, 'Apply Wire Types.pushbutton',
                                  'script.py'), encoding='utf-8').read()
    check('the button calls run_apply_types',
          'circuit_core.run_apply_types' in source)
    check('and passes a confirm callback', 'confirm' in source)
    check('run_apply_types exists', hasattr(cc, 'run_apply_types'))
    for name in ('wires_by_circuit', 'selected_circuits',
                 'apply_types_to_circuit', 'circuit_reads_emergency'):
        check('{0} exists'.format(name), hasattr(cc, name))

    chunk = function_source('circuit_core.py', 'run_apply_types')
    for forbidden in ('Wire.Create', 'doc.Delete', 'place_tag', 'SetVertex',
                      'place_segment', 'NewDetailCurve'):
        check('Apply Wire Types never calls {0}'.format(forbidden),
              forbidden not in chunk, forbidden)
    applied = function_source('circuit_core.py', 'apply_types_to_circuit')
    for forbidden in ('Wire.Create', 'doc.Delete', 'SetVertex', 'place_tag'):
        check('and nor does apply_types_to_circuit ({0})'.format(forbidden),
              forbidden not in applied, forbidden)
    check('it only ever changes the type', 'ChangeTypeId' in applied)
    # the read-back has to come AFTER the change - looking for the string
    # anywhere in the function is satisfied by the "already right" test that
    # precedes it, and a deliberate break slipped past on exactly that
    change_at = applied.index('ChangeTypeId')
    after = applied[change_at:]
    check('and reads the change back afterwards',
          'same_id(wire.GetTypeId()' in after, after[:80])
    check('counting a change only once it has taken',
          after.index('same_id(wire.GetTypeId()') < after.index('changed += 1'),
          'changed is counted before the read-back')


def align_tests():
    """Where a wire should meet its fitting, and what the tool may touch."""

    class Box(object):
        def __init__(self, half):
            self.Min = P(-half * MM, -half * MM, 0)
            self.Max = P(half * MM, half * MM, 0)

    class Fitting(object):
        def __init__(self, half):
            self._box = Box(half)

        def get_BoundingBox(self, view):
            return self._box

    settings = dict(core.DEFAULTS)
    view = View()
    fitting = Fitting(150)          # a 300mm square symbol
    centre = mp(2000, 0)
    arriving_from = mp(0, 0)        # the wire comes in from the left

    # the default is the symbol edge, which is where Revit itself puts a
    # re-docked wire. The connector node is the fitting's CENTRE, and aiming
    # at it ran the wires through their symbols.
    check('the default is edge', core.DEFAULTS['align_target'] == 'edge')
    on_centre = core.arrival_point(view, settings, fitting, centre,
                                   arriving_from, 0.0, 'centre')
    check('centre mode sits on the connector',
          abs(mm(on_centre.X) - 2000) < 1e-6, mm(on_centre.X))
    check('and keeps the wire\'s own elevation', abs(on_centre.Z) < 1e-9)
    check('the default is not the centre',
          abs(mm(core.arrival_point(view, settings, fitting, centre,
                                    arriving_from, 0.0).X) - 2000) > 1,
          'the default still lands on the connector')

    got = core.arrival_point(view, settings, fitting, centre, arriving_from,
                             0.0, 'trim')
    check('trim mode stops short of the symbol', mm(got.X) < 2000, mm(got.X))
    check('on the line it arrives along', abs(mm(got.Y)) < 1e-6)

    # --- the collapse: a fitting whose bounding box is nothing like its
    # symbol must not drag the wire end back to a stub
    huge = Fitting(4000)            # an 8m box on a 2m span
    trim, capped = core.trim_distance(view, settings, huge, (1.0, 0.0),
                                      core.mm(2000))
    check('an oversized box is capped', capped, 'the cap never bit')
    check('and the trim stays at the paper ceiling',
          abs(mm(trim) - 300) < 1e-6, mm(trim))
    collapsed = core.arrival_point(view, settings, huge, centre,
                                   arriving_from, 0.0, 'trim')
    # without the cap this was 2000 - 0.9 * 2000 = 200, a collapsed stub
    check('so the end stays near its fitting, not back at the next vertex',
          mm(collapsed.X) >= 1700 - 1e-6, mm(collapsed.X))

    # the paper ceiling and the span ceiling, each biting in turn
    trim, capped = core.trim_distance(view, settings, huge, (1.0, 0.0),
                                      core.mm(10000))
    check('on a long span the paper ceiling is what bites',
          abs(mm(trim) - 6 * 50) < 1e-6, mm(trim))
    trim, capped = core.trim_distance(view, settings, huge, (1.0, 0.0),
                                      core.mm(300))
    check('on a short span a third of it is what bites',
          abs(mm(trim) - 100) < 1e-6, mm(trim))   # 300 / 3
    check('a sane symbol is not capped at all',
          not core.trim_distance(view, settings, fitting, (1.0, 0.0),
                                 core.mm(4000))[1])

    # arriving from above instead, the step-back follows the new direction
    from_above = core.arrival_point(view, settings, fitting, centre,
                                    mp(2000, 3000), 0.0, 'trim')
    check('the step-back follows the arrival direction',
          abs(mm(from_above.X) - 2000) < 1e-6 and mm(from_above.Y) > 0,
          '{0},{1}'.format(mm(from_above.X), mm(from_above.Y)))

    # it must never step back past the vertex it came from
    close = core.arrival_point(view, settings, Fitting(5000), mp(100, 0),
                               mp(0, 0), 0.0, 'trim')
    check('a trim bigger than the span is clamped',
          0 <= mm(close.X) <= 100, mm(close.X))

    check('it survives a fitting with no bounding box',
          core.arrival_point(view, settings, object(), centre, arriving_from,
                             0.0, 'trim') is not None)
    check('and refuses an impossible one',
          core.arrival_point(view, settings, fitting, None, arriving_from)
          is None)

    # what the aligner may and may not do. It is allowed to re-seat a
    # connection and, as a last resort, rebuild a wire - but never to retype,
    # retag or delete anything, and never to touch a different element
    chunk = function_source('circuit_core.py', 'align_one_wire')
    for forbidden in ('ChangeTypeId', 'place_tag', 'doc.Delete',
                      'Wire.Create'):
        check('align_one_wire never calls {0}'.format(forbidden),
              forbidden not in chunk, forbidden)
    # presence first: an ordering check that indexes a missing string raises
    # instead of failing, and a bench that crashes says less than one that
    # names what is wrong
    for route in ('_try_redock', '_try_move', '_try_nudge', '_try_jiggle',
                  '_try_rebuild'):
        check('align_one_wire can use {0}'.format(route), route in chunk,
              'route is not called at all')

    # The default must not compute a destination. Three releases did, and got
    # it wrong three different ways - stub, symbol centre, 400mm short.
    auto = chunk.split("method in ('auto', 'redock')")[-1]
    auto = auto.split('# the aimed methods')[0]
    for forbidden in ('wire_end_targets', 'arrival_point', 'align_target',
                      'tolerance'):
        check('the auto path never uses {0}'.format(forbidden),
              forbidden not in auto, 'auto is computing a destination again')
    check('auto re-docks every joined end', 'wire_joined_ends(' in auto)
    check('and nothing else', '_try_move' not in auto and
          '_try_nudge' not in auto and '_try_rebuild' not in auto)

    joined = function_source('circuit_core.py', 'wire_joined_ends')
    for forbidden in ('arrival_point', 'align_target', 'trim_distance'):
        check('wire_joined_ends computes no destination either',
              forbidden not in joined, forbidden)

    check('the re-dock tries more than one shove',
          len(cc.REDOCK_SHOVES) >= 2)
    check('starting small, as the hand does',
          list(cc.REDOCK_SHOVES) == sorted(cc.REDOCK_SHOVES) and
          cc.REDOCK_SHOVES[0] <= 500, cc.REDOCK_SHOVES)
    check('and resolves the end again on every shove',
          function_source('circuit_core.py', '_try_redock').count(
              '_end_state(') >= 2)

    # the re-dock reproduces the hand: disconnect, drag clear, drop on the
    # node, reconnect - and then accepts whatever Revit decided
    redock = function_source('circuit_core.py', '_try_redock')
    for step in ('DisconnectFrom', 'SetVertex', 'ConnectTo'):
        check('the re-dock does {0}'.format(step), step in redock)
    check('it drags clear before dropping back',
          redock.index('away') < redock.index('node.X'))
    check('it reconnects last',
          redock.index('DisconnectFrom') < redock.index('ConnectTo'))
    check('it judges by getting nearer, not by hitting a target',
          'now < was' in redock, 'it is still testing against a target')
    check('and rolls back when it does not',
          redock.count('sub.RollBack()') >= 3)

    # the edge target: where Revit puts a re-docked wire, not the centre
    check('the default target is the symbol edge',
          core.DEFAULTS['align_target'] == 'edge')
    edge = core.arrival_point(view, settings, fitting, centre, arriving_from,
                              0.0, 'edge')
    check('edge stops short of the centre', mm(edge.X) < 2000, mm(edge.X))
    check('by about the symbol radius', abs(mm(edge.X) - 1850) < 1,
          mm(edge.X))
    check('symbol_radius takes the smaller half of the box',
          abs(mm(core.symbol_radius(Fitting(150), view)) - 150) < 1e-6)

    # the nudge is the route built from what Revit actually said: it refuses a
    # vertex landing within tolerance of one it holds, so the end is walked in
    nudge = function_source('circuit_core.py', '_try_nudge')
    check('the nudge shoves the vertex and puts it back',
          nudge.count('wire.SetVertex(index, here)') == 1 and
          'wire.SetVertex(index, away)' in nudge)
    check('then walks in from the node', 'NUDGE_STEPS' in nudge)
    check('the steps start at the node itself', cc.NUDGE_STEPS[0] == 0)
    check('and increase', list(cc.NUDGE_STEPS) == sorted(cc.NUDGE_STEPS))
    check('the last step is still invisible on a sheet',
          cc.NUDGE_STEPS[-1] <= 50, cc.NUDGE_STEPS[-1])
    # the comparison, not the variable: a check for the name alone passed on a
    # build where the test had been replaced by "if True"
    check('it only accepts a landing close to the node',
          'gap <= close_enough' in nudge, 'the gap is not being tested')
    check('and the shove is judged the same way',
          'core.plan_distance(landed, target) <= close_enough' in nudge)
    check('close enough defaults to half a millimetre on a 1:50 sheet',
          core.DEFAULTS['align_max_gap_mm'] == '25')
    check('every step runs in its own sub-transaction',
          nudge.count('sub.Start()') >= 2 and
          nudge.count('sub.RollBack()') >= 3)
    check('the rebuild is the last resort only',
          "method in ('auto+rebuild', 'rebuild')" in chunk)
    # a rebuild changes element ids, so it must not happen just because the
    # default was left alone: 29 new wires for no visible change is worse
    # than doing nothing
    check('and never on the plain default',
          core.DEFAULTS['align_method'] == 'auto' and
          "'auto'" not in chunk.split('if refused')[-1],
          'auto still rebuilds')

    # the geometry dump, for when a wire will not do what it is told
    dump = function_source('circuit_core.py', 'log_wire_geometry')
    for wanted in ('wire_vertices', 'opposite_connector', 'element_point',
                   'get_BoundingBox', 'electrical_connectors'):
        check('the geometry dump reports {0}'.format(wanted), wanted in dump)
    check('it is off unless asked for',
          core.DEFAULTS['debug_geometry'] == 'no')
    caller2 = function_source('circuit_core.py', 'align_one_wire')
    check('and is gated on the setting',
          "_settings_bool(settings, 'debug_geometry')" in caller2)

    for name, must in (('_try_move', 'SetVertex'),
                       ('_try_nudge', 'SetVertex'),
                       ('_try_jiggle', 'DisconnectFrom'),
                       ('_try_rebuild', 'rebuild_wire')):
        route = function_source('circuit_core.py', name)
        check('{0} does what it says'.format(name), must in route)
        check('{0} runs in its own sub-transaction'.format(name),
              'SubTransaction' in route and 'RollBack' in route)
        if name != '_try_rebuild':
            check('{0} reads the result back'.format(name),
                  'plan_distance(landed, target)' in route)

    # Connector references do not survive a sub-transaction, committed OR
    # rolled back. Holding them is what made every second end and every
    # rebuild fail with "the referenced object is not valid", while reading
    # like Revit refusing the work.
    for name in ('_try_move', '_try_nudge', '_try_jiggle'):
        route = function_source('circuit_core.py', name)
        check('{0} resolves the end afresh'.format(name),
              '_end_state(' in route, 'it is using a held reference')
    rebuild = function_source('circuit_core.py', '_try_rebuild')
    check('_try_rebuild resolves its ends afresh',
          'wire_end_targets(' in rebuild, 'it is using held references')
    caller = function_source('circuit_core.py', 'align_one_wire')
    check('align_one_wire hands routes an index, not a connector',
          'connector' not in caller.split('for index, target in todo:')[-1],
          'a connector is still being passed down')

    # a rebuilt wire is a new element, so anything hosted on it has to follow
    check('a rebuild carries the tags over', 'snapshot_tag(' in rebuild and
          'restore_tag(' in rebuild, 'tags would be lost with the old wire')
    restore = function_source('circuit_core.py', 'restore_tag')
    check('restore_tag can be re-pointed at a new host', 'host=None' in restore)

    jiggle = function_source('circuit_core.py', '_try_jiggle')
    check('the re-seat reconnects what it disconnected',
          jiggle.index('DisconnectFrom') < jiggle.index('ConnectTo'))
    check('and rolls back rather than leaving a wire hanging',
          jiggle.count('sub.RollBack()') >= 3, jiggle.count('sub.RollBack()'))

    # the trace is the thing that explains a failure next time
    traced = core.Report('Align Wire Ends')
    traced.log('wire 123: 1 end(s) to move, by auto')
    check('a report carries a trace', traced.trace)
    check('the trace never opens the window',
          not traced.needs_a_look())
    text = core.debug_report(object(), dict(core.DEFAULTS), traced)
    check('but the debug report carries it', '-- trace --' in text and
          'wire 123' in text)

    check('align_method defaults to trying everything',
          core.DEFAULTS['align_method'] == 'auto')

    for name in ('place_segment', 'place_home_run', 'place_switch_line'):
        chunk = function_source('circuit_core.py', name)
        check('{0} trims through the one capped rule'.format(name),
              'plan_half_extent' not in chunk, 'still trims by raw extent')
        check('{0} calls trim_distance'.format(name),
              'trim_distance' in chunk)

    run = function_source('circuit_core.py', 'run_align_ends')
    check('nothing selected asks first', 'confirm(' in run)
    check('selected wires are honoured', 'picked_wires' in run)
    check('selected circuits are honoured', 'picked_circuits' in run)
    check('it reports an aligned count', 'report.aligned = moved' in run)

    aligned = core.Report('Align Wire Ends')
    aligned.aligned = 7
    check('the summary says aligned',
          'aligned' in aligned.summary() and 'drawn' not in aligned.summary(),
          aligned.summary())

    # _retrim no longer gives up when Revit changed the vertex count
    retrim = function_source('circuit_core.py', '_retrim')
    check('_retrim handles a count mismatch by aligning the ends',
          'len(current) - 1' in retrim, 'still bails on a mismatch')
    check('and only a refusal from Revit counts as one',
          'refused = True' in retrim)


def report_tests():
    settings = dict(core.DEFAULTS)
    clean = core.Report('Auto Wire')
    clean.info('Wire type: Lighting.')
    clean.info('DB1/1: switch found.')
    clean.ok('3 circuit(s) drawn.')
    check('a clean run opens no window',
          not results_window.should_show(clean, settings))
    check('unless asked to always',
          results_window.should_show(clean, dict(settings, show_results='always')))
    worth = core.Report('Auto Wire')
    worth.note('DB1/2: 3 of 8 read as emergency.')
    check('a note opens it', results_window.should_show(worth, settings))


class _Enum(object):
    """Stands in for a Revit enum member: a name and an integer value."""

    def __init__(self, name, value):
        self.name = name
        self.value = value

    def __str__(self):
        return self.name

    def __int__(self):
        return self.value

    def __bool__(self):
        return bool(self.value)

    __nonzero__ = __bool__


def theme_tests():
    import wires_theme as theme
    # UITheme.Dark is 0: falsy. Reading it by truthiness is the classic bug.
    dark_zero = _Enum('Dark', 0)
    light_one = _Enum('Light', 1)
    check('dark reads as dark even though its value is 0',
          theme.is_dark_value(dark_zero) is True)
    check('light reads as light', theme.is_dark_value(light_one) is False)
    check('nothing to read is unknown, not light',
          theme.is_dark_value(None) is None)
    check('a value with neither name is unknown',
          theme.is_dark_value(_Enum('HighContrast', 2)) is None)

    check('follow on a dark canvas is dark',
          theme.resolve('follow', True) == 'dark')
    check('follow on a light canvas is light',
          theme.resolve('follow', False) == 'light')
    check('follow with no canvas to read lands on dark',
          theme.resolve('follow', None) == 'dark')
    check('dark is dark whatever Revit says',
          theme.resolve('dark', False) == 'dark')
    check('light is light whatever Revit says',
          theme.resolve('light', True) == 'light')
    check('a damaged stored value follows',
          theme.normalise('purple') == 'follow' and
          theme.normalise(None) == 'follow' and
          theme.normalise(' Dark ') == 'dark')

    seen = ['follow']
    for _ in range(3):
        seen.append(theme.next_mode(seen[-1]))
    check('the chip cycles Auto, Dark, Light and back',
          seen == ['follow', 'dark', 'light', 'follow'], str(seen))
    check('the chip says what it is showing while following',
          theme.chip_text('follow', 'light') == u'Auto \u00b7 Light')
    check('and just the mode otherwise',
          theme.chip_text('dark', 'dark') == 'Dark')

    dark = theme.PALETTES['dark']
    light = theme.PALETTES['light']
    check('both palettes carry the same keys',
          set(dark.keys()) == set(light.keys()),
          str(set(dark.keys()) ^ set(light.keys())))
    check('the light accents are darkened, not inverted',
          light['Blue'] == '#1B72BE' and light['Orange'] == '#B96A12' and
          light['Green'] == '#2E8546')
    check('the dark palette is the house palette',
          dark['Shell'] == '#232326' and dark['Blue'] == '#4FA3E3' and
          dark['Green'] == '#3FA75A')

    def luminance(hex_value):
        red, green, blue = [int(hex_value[i:i + 2], 16) / 255.0
                            for i in (1, 3, 5)]

        def channel(c):
            return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
        return (0.2126 * channel(red) + 0.7152 * channel(green) +
                0.0722 * channel(blue))

    def contrast(a, b):
        la, lb = luminance(a), luminance(b)
        return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)

    for name in ('dark', 'light'):
        palette = theme.PALETTES[name]
        check('{0}: body text reads on the window'.format(name),
              contrast(palette['Fg'], palette['Shell']) >= 7.0)
        check('{0}: muted text still reads on a field'.format(name),
              contrast(palette['Muted'], palette['Field']) >= 4.5,
              '{0:.2f}'.format(contrast(palette['Muted'], palette['Field'])))
        check('{0}: the tick reads on the blue it sits on'.format(name),
              contrast(palette['OnBlue'], palette['Blue']) >= 4.0,
              '{0:.2f}'.format(contrast(palette['OnBlue'], palette['Blue'])))
        check('{0}: the reopen arrow stands off the bar'.format(name),
              contrast(palette['Green'], palette['Bar']) >= 3.0,
              '{0:.2f}'.format(contrast(palette['Green'], palette['Bar'])))
    check('hex_of falls back to dark for an unknown palette',
          theme.hex_of('neon', 'Shell') == '#232326')


def drawer_tests():
    import wires_drawer as drawer
    # a 1080p primary with a 40px taskbar: work area 0..1040
    check('parks the bar just above the taskbar',
          drawer.park_top(0, 1040, 50) == 1040 - 50 - drawer.MARGIN)
    # a second monitor ABOVE the primary: its work area starts at -1080
    above = drawer.park_top(-1080, 1040, 50)
    check('parks on the upper monitor, not the primary',
          -1080 < above < 0, str(above))
    check('and at the bottom of that monitor',
          above == -1080 + 1040 - 50 - drawer.MARGIN)
    # a monitor to the left with an offset top
    check('an offset monitor keeps its own offset',
          drawer.park_top(200, 900, 40, margin=10) == 200 + 900 - 40 - 10)

    parked = drawer.park_top(0, 1040, 50)
    check('left where it was parked, it goes back where it came from',
          drawer.reopen_top(120, parked, parked, 50, 600, 0, 1040) == 120)
    check('a nudge inside the tolerance still counts as unmoved',
          drawer.reopen_top(120, parked, parked + 1.5, 50, 600, 0, 1040)
          == 120)
    # carried up to y=700: open upward, so the window's bottom is the bar's
    moved = drawer.reopen_top(120, parked, 700, 50, 600, 0, 1040)
    check('carried elsewhere, it opens upward from where the bar sits',
          moved == 700 + 50 - 600, str(moved))
    # carried to the very top: opening upward would leave the screen
    check('opening upward never leaves the top of the screen',
          drawer.reopen_top(120, parked, 10, 50, 600, 0, 1040) == 0)
    check('a window taller than the screen is pinned to its top',
          drawer.reopen_top(120, parked, 500, 50, 1400, 0, 1040) == 0)
    # the upper monitor: parked there, carried, reopened - all negative
    upper_parked = drawer.park_top(-1080, 1040, 50)
    check('reopens on the upper monitor where it came from',
          drawer.reopen_top(-900, upper_parked, upper_parked, 50, 600,
                            -1080, 1040) == -900)
    carried = drawer.reopen_top(-900, upper_parked, -400, 50, 600,
                                -1080, 1040)
    check('carried on the upper monitor, opens upward there',
          carried == -400 + 50 - 600, str(carried))
    check('and never lands on the monitor below it',
          drawer.reopen_top(-900, upper_parked, -60, 50, 600, -1080, 1040)
          + 600 <= -1080 + 1040)
    check('clamp keeps a window on the work area',
          drawer.clamp_top(2000, 300, 0, 1040) == 740 and
          drawer.clamp_top(-50, 300, 0, 1040) == 0)

    land = function_source('wires_drawer.py', '_land')
    check('the slide releases both animations when it lands',
          'BeginAnimation(Window.TopProperty, None)' in land and
          'BeginAnimation(Window.HeightProperty, None)' in land)
    keys = function_source('wires_drawer.py', '_on_key')
    check('Ctrl+Shift+H toggles the drawer',
          'Key.H' in keys and 'ModifierKeys.Control' in keys and
          'ModifierKeys.Shift' in keys and 'self.toggle()' in keys)
    check('Escape, Enter and F11 reopen while parked',
          'self.parked and key in' in keys and 'Key.Escape' in keys and
          'Key.Return' in keys and 'Key.F11' in keys)
    pressed = function_source('wires_drawer.py', 'header_pressed')
    check('a double-click on the parked bar reopens it',
          'ClickCount >= 2' in pressed and 'self.expand()' in pressed)
    check('and the parked bar can still be dragged',
          pressed.rstrip().endswith('pass') and 'DragMove()' in pressed)
    glyph = function_source('wires_drawer.py', '_glyph')
    check('parking swaps the shrink glyph for the green up arrow',
          "FindName('ExpandGlyph')" in glyph and
          'Visibility.Visible if parked' in glyph)


def main():
    for group in (arc_tests, vertex_and_wiring_tests, chamfer_tests,
                  routing_tests, wire_type_tests, session_tests,
                  span_note_tests, modeless_tests, modeless_wiring_tests,
                  debug_tests, apply_type_tests, align_tests,
                  report_tests, theme_tests, drawer_tests):
        group()
    sys.stdout.write('WIRES LOGIC BENCH - {0} checks passed.\n'.format(
        len(PASSED)))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except AssertionError as error:
        sys.stdout.write('WIRES LOGIC BENCH - FAILED: {0}\n'.format(error))
        sys.stdout.write('  ({0} passed before it)\n'.format(len(PASSED)))
        sys.exit(1)
