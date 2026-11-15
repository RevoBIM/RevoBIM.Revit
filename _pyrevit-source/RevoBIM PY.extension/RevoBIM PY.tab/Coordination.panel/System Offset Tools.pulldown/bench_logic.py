# -*- coding: utf-8 -*-
"""RevoBIM System Offset - the rules, under plain CPython.

    python bench_logic.py

so_core carries every decision the tool makes about how far
the offset goes, which way, whether it fits and what the
refusal says. None of it touches WPF or the Revit API, so
all of it can be run against a table of cases here rather
than by clicking through Revit.

That separation is the reason this file can exist. Anything
that cannot be tested this way is where the bugs survive.
"""

from __future__ import print_function

import os
import sys
import math
import types
import shutil
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# so_core reaches for clr through so_clr and nothing else.
if 'clr' not in sys.modules:
    stub = types.ModuleType('clr')
    stub.AddReference = lambda *args, **kwargs: None
    sys.modules['clr'] = stub

import so_core  # noqa: E402


PASSED = []
FAILED = []


def check(name, got, want):
    if got == want:
        PASSED.append(name)
    else:
        FAILED.append('{0}\n      wanted {1!r}\n      got    {2!r}'
                      .format(name, want, got))


def close(name, got, want, tolerance=1e-6):
    try:
        ok = abs(float(got) - float(want)) <= tolerance
    except Exception:
        ok = False
    if ok:
        PASSED.append(name)
    else:
        FAILED.append('{0}\n      wanted {1!r}\n      got    {2!r}'
                      .format(name, want, got))


def truthy(name, got):
    check(name, bool(got), True)


def falsy(name, got):
    check(name, bool(got), False)


# =========================================================
# The bend arithmetic
# =========================================================

def test_run_back():
    close('45 degrees eats its own offset in run', so_core.run_back_mm(100, 45), 100.0)
    close('90 degrees eats no run at all', so_core.run_back_mm(100, 90), 0.0)
    close('30 degrees eats more run than the offset',
          so_core.run_back_mm(100, 30), 173.20508, 1e-4)
    close('60 degrees eats less', so_core.run_back_mm(100, 60), 57.735027, 1e-4)
    close('a zero offset eats nothing', so_core.run_back_mm(0, 45), 0.0)


def test_break_needs_one_bend_not_two():
    """A break turns out and stops, so it pays for one turn
    where a jog pays for two - and has twice the room."""
    close('a jog at 45 pays twice the offset in run',
          so_core.minimum_span_mm(100, 45, bends=2), 210.0)
    close('a break pays once',
          so_core.minimum_span_mm(100, 45, bends=1), 110.0)

    close('so a break fits twice the offset in the same span',
          so_core.max_offset_mm(410, 45, bends=1), 400.0, 1e-4)
    close('where a jog fits half that',
          so_core.max_offset_mm(410, 45, bends=2), 200.0, 1e-4)

    plan = so_core.plan_offset(300, 45, 410, bends=1)
    truthy('a 300mm break over 410mm fits', plan['ok'])
    check('and reports one bend', plan['bends'], 1)
    close('leaving the rest as the stepped piece', plan['middle_mm'], 110.0)

    falsy('the same 300mm as a jog does not fit',
          so_core.plan_offset(300, 45, 410, bends=2)['ok'])

    # The prompt and the routine have to agree in BOTH modes,
    # or the prompt offers a number the routine then refuses.
    for bends in (1, 2):
        for angle in (22.5, 30.0, 45.0, 60.0):
            largest = so_core.max_offset_mm(400, angle, bends)
            truthy('largest at {0} with {1} bend(s) fits'.format(angle, bends),
                   so_core.plan_offset(largest, angle, 400, bends=bends)['ok'])
            falsy('a hair more at {0} with {1} bend(s) does not'
                  .format(angle, bends),
                  so_core.plan_offset(largest + 1.0, angle, 400,
                                      bends=bends)['ok'])


def test_minimum_span():
    close('a 45 degree 100mm offset needs 2x100 plus the short piece',
          so_core.minimum_span_mm(100, 45), 210.0)
    close('a square offset only needs the short piece',
          so_core.minimum_span_mm(100, 90), 10.0)
    close('the short piece is settable',
          so_core.minimum_span_mm(100, 90, 50.0), 50.0)


def test_snap_angle():
    check('45 stays 45', so_core.snap_angle(45), 45.0)
    check('43 snaps to the nearest five', so_core.snap_angle(43), 45.0)
    check('47 snaps down', so_core.snap_angle(47), 45.0)
    check('nothing goes past 90', so_core.snap_angle(140), 90.0)
    check('nothing goes below the smallest offered',
          so_core.snap_angle(1), 22.5)
    check('rubbish falls back to 45', so_core.snap_angle('elbow'), 45.0)


def test_round_to():
    check('305 rounds up to 5', so_core.round_to(303, 5), 305.0)
    check('an exact multiple is left alone', so_core.round_to(300, 5), 300.0)
    check('a zero step rounds nothing', so_core.round_to(303.4, 0), 303.4)
    check('rounding up never rounds down', so_core.round_to(301, 25), 325.0)


# =========================================================
# Does the offset fit
# =========================================================

def test_plan_offset():
    plan = so_core.plan_offset(100, 45, 400)
    truthy('a roomy 45 degree offset is fine', plan['ok'])
    close('the run back is the offset at 45', plan['run_back_mm'], 100.0)
    close('the middle length is what is left', plan['middle_mm'], 200.0)
    falsy('45 degrees is not square', plan['square'])

    plan = so_core.plan_offset(100, 90, 400)
    truthy('a square offset is fine too', plan['ok'])
    close('a square offset keeps the whole middle', plan['middle_mm'], 400.0)
    truthy('90 degrees is square', plan['square'])

    plan = so_core.plan_offset(100, 45, 150)
    falsy('too tight is refused', plan['ok'])
    truthy('the refusal names the shortfall', '60mm further apart' in plan['reason'])
    close('the refusal carries the number needed', plan['needed_mm'], 210.0)

    plan = so_core.plan_offset(0, 45, 400)
    falsy('a zero offset is refused', plan['ok'])

    plan = so_core.plan_offset(100, 45, 210)
    truthy('exactly enough room is enough', plan['ok'])
    close('and leaves the shortest allowed piece', plan['middle_mm'], 10.0)


# =========================================================
# How far the offset goes
# =========================================================

def base_settings(**overrides):
    values = dict(so_core.DEFAULTS)
    values.update(overrides)
    return values


def test_default_distance():
    values = base_settings(width_factor=u'1.0')
    check('one width of a 100mm service',
          so_core.offset_distance_mm(values, 100.0), 100.0)
    check('an odd width rounds up onto the 5mm grid',
          so_core.offset_distance_mm(values, 63.0), 65.0)
    check('a tiny service still clears the floor',
          so_core.offset_distance_mm(values, 1.0), so_core.MIN_OFFSET_MM)
    check('a service with no size at all clears the floor',
          so_core.offset_distance_mm(values, 0.0), so_core.MIN_OFFSET_MM)

    values = base_settings(width_factor=u'2.0')
    check('the multiplier is honoured',
          so_core.offset_distance_mm(values, 150.0), 300.0)

    values = base_settings(width_factor=u'wide')
    check('a damaged multiplier falls back to one',
          so_core.offset_distance_mm(values, 100.0), 100.0)


def test_max_offset():
    close('at 45 degrees half the spare run is the limit',
          so_core.max_offset_mm(410, 45), 200.0, 1e-4)
    check('a square offset has no limit',
          so_core.max_offset_mm(410, 90), None)
    check('no room at all means no offset',
          so_core.max_offset_mm(5, 45), 0.0)
    close('a shallower angle allows more',
          so_core.max_offset_mm(410, 60), 346.410161, 1e-4)

    # The limit and the fit test have to agree, or the prompt
    # offers a number the routine then refuses.
    for angle in (22.5, 30.0, 45.0, 60.0):
        largest = so_core.max_offset_mm(400, angle)
        truthy('the largest offset at {0} actually fits'.format(angle),
               so_core.plan_offset(largest, angle, 400)['ok'])
        falsy('a hair more than the largest at {0} does not'.format(angle),
              so_core.plan_offset(largest + 1.0, angle, 400)['ok'])


# =========================================================
# Settings
# =========================================================

def with_temp_settings(function):
    folder = tempfile.mkdtemp(prefix='revobim_so_bench_')
    original = so_core.settings_dir
    so_core.settings_dir = lambda: folder
    try:
        return function(folder)
    finally:
        so_core.settings_dir = original
        shutil.rmtree(folder, ignore_errors=True)


def test_settings_round_trip():
    def body(folder):
        values = base_settings(angle=u'90', width_factor=u'2.5',
                               theme=u'light')
        truthy('the settings write', so_core.save_settings(values))
        back = so_core.load_settings()
        check('the angle survives', back['angle'], u'90')
        check('the multiplier survives', back['width_factor'], u'2.5')
        check('the theme survives', back['theme'], u'light')
        check('the version is stamped', back['settings_version'],
              so_core.to_text(so_core.SETTINGS_VERSION))
    with_temp_settings(body)


def test_settings_missing_file():
    def body(folder):
        back = so_core.load_settings()
        check('a missing file gives the defaults', back['angle'],
              so_core.DEFAULTS['angle'])
    with_temp_settings(body)


def test_settings_damaged_file():
    def body(folder):
        path = os.path.join(folder, 'system_offset.txt')
        handle = open(path, 'wb')
        try:
            handle.write((u'settings_version={0}\n'
                          u'angle=90\n'
                          u'this line has no equals sign\n'
                          u'# a comment\n'
                          u'nonsense_key=1\n'
                          .format(so_core.SETTINGS_VERSION)).encode('utf-8'))
        finally:
            handle.close()
        back = so_core.load_settings()
        check('a good key still loads', back['angle'], u'90')
        check('a junk line is ignored', 'nonsense_key' in back, False)
        check('the rest take their defaults', back['width_factor'],
              so_core.DEFAULTS['width_factor'])
    with_temp_settings(body)


def test_settings_migration():
    def body(folder):
        path = os.path.join(folder, 'system_offset.txt')
        handle = open(path, 'wb')
        try:
            # A file from before the direction rule changed
            handle.write((u'settings_version=4\n'
                          u'width_factor=3.0\n'
                          u'angle=90\n'
                          u'theme=light\n').encode('utf-8'))
        finally:
            handle.close()
        back = so_core.load_settings()
        check('the old 3x multiplier is reset to the new 1x',
              back['width_factor'], so_core.DEFAULTS['width_factor'])
        check('a key that migration does not list survives',
              back['angle'], u'90')
        check('and so does the theme', back['theme'], u'light')
    with_temp_settings(body)


def test_settings_migration_from_v3():
    def body(folder):
        path = os.path.join(folder, 'system_offset.txt')
        handle = open(path, 'wb')
        try:
            handle.write((u'settings_version=3\n'
                          u'width_factor=2.0\n'
                          u'angle=90\n'
                          u'theme=light\n').encode('utf-8'))
        finally:
            handle.close()
        back = so_core.load_settings()
        check('a file old enough for both migrations resets the multiplier',
              back['width_factor'], so_core.DEFAULTS['width_factor'])
        check('and the angle, which v4 listed',
              back['angle'], so_core.DEFAULTS['angle'])
        check('the theme is listed by neither and survives',
              back['theme'], u'light')
    with_temp_settings(body)


def test_settings_value_with_equals():
    def body(folder):
        path = os.path.join(folder, 'system_offset.txt')
        handle = open(path, 'wb')
        try:
            handle.write((u'settings_version={0}\n'
                          u'angle=45=45\n'
                          .format(so_core.SETTINGS_VERSION)).encode('utf-8'))
        finally:
            handle.close()
        back = so_core.load_settings()
        check('the loader splits on the first equals only',
              back['angle'], u'45=45')
    with_temp_settings(body)


# =========================================================
# Odds and ends
# =========================================================

def test_settings_are_small():
    check('the offset tools still have only two settings, plus the theme, '
          'the version and Clash Offset own two',
          sorted(so_core.DEFAULTS.keys()),
          ['angle', 'clash_clearance', 'clash_lead', 'settings_version',
           'theme', 'width_factor'])
    check('the multiplier defaults to one', so_core.DEFAULTS['width_factor'],
          u'1.0')
    check('the angle defaults to 45', so_core.DEFAULTS['angle'], u'45')


def test_a_clean_run_says_nothing():
    """The regression this exists to stop: the tool popping a
    report after every single offset."""

    def record(ok=True, notes=None, problems=None):
        return {'ok': ok, 'notes': notes or [], 'problems': problems or []}

    falsy('a clean offset says nothing',
          so_core.needs_reporting([record()]))

    # Every successful offset produces these. Treating them as
    # things needing a look is exactly what went wrong.
    falsy('notes alone are not a reason to open a window',
          so_core.needs_reporting([record(notes=[
              u'Broken by BreakCurve.',
              u'Copied BGL_Service Type.',
              u'The run is cut at the second click.'])]))

    falsy('a whole run of clean offsets stays silent',
          so_core.needs_reporting([record() for _ in range(6)]))

    truthy('a refusal opens it',
           so_core.needs_reporting([record(ok=False)]))
    truthy('a real problem opens it',
           so_core.needs_reporting([record(problems=[u'2 of 4 bends took a fitting.'])]))
    truthy('one bad one among many good ones opens it',
           so_core.needs_reporting([record(), record(), record(ok=False)]))
    falsy('nothing at all says nothing', so_core.needs_reporting([]))

    shown = so_core.worth_showing([record(), record(ok=False), record(),
                                   record(problems=[u'x'])])
    check('and only the ones that earned it are shown', len(shown), 2)
    check('the clean ones are left out',
          [r['ok'] for r in shown], [False, True])


class Vec(object):
    """A plain vector with the three methods plan_corner uses.

    plan_corner is duck typed, so the corner rule can be run
    against real numbers here instead of against Revit.
    """

    def __init__(self, x, y, z=0.0):
        self.x, self.y, self.z = float(x), float(y), float(z)

    def __sub__(self, other):
        return Vec(self.x - other.x, self.y - other.y, self.z - other.z)

    def __add__(self, other):
        return Vec(self.x + other.x, self.y + other.y, self.z + other.z)

    def __eq__(self, other):
        return (abs(self.x - other.x) < 1e-9 and abs(self.y - other.y) < 1e-9
                and abs(self.z - other.z) < 1e-9)

    def DotProduct(self, other):
        return self.x * other.x + self.y * other.y + self.z * other.z

    def Multiply(self, scale):
        return Vec(self.x * scale, self.y * scale, self.z * scale)

    def GetLength(self):
        return (self.x ** 2 + self.y ** 2 + self.z ** 2) ** 0.5

    def Normalize(self):
        length = self.GetLength()
        return Vec(self.x / length, self.y / length, self.z / length)

    def Negate(self):
        return Vec(-self.x, -self.y, -self.z)

    def CrossProduct(self, other):
        return Vec(self.y * other.z - self.z * other.y,
                   self.z * other.x - self.x * other.z,
                   self.x * other.y - self.y * other.x)

    def __repr__(self):
        return 'Vec({0:.3f}, {1:.3f}, {2:.3f})'.format(self.x, self.y, self.z)


def ft(mm):
    return so_core.mm_to_ft(mm)


def test_the_corner_is_square():
    origin = Vec(0, 0)
    east = Vec(1, 0)

    # 2000mm along, 1000mm off to the north
    step = so_core.plan_corner(origin, east, Vec(ft(2000), ft(1000)))
    truthy('a normal click routes', step['ok'])
    falsy('and is not straight on', step['straight'])
    close('the corner sits at the click projected onto the axis',
          so_core.ft_to_mm(step['corner'].x), 2000.0, 1e-6)
    close('square to it, so the corner is on the axis',
          so_core.ft_to_mm(step['corner'].y), 0.0, 1e-6)
    close('the new leg is the sideways distance', step['leg_mm'], 1000.0, 1e-6)

    # The turn has to be exactly 90 degrees, not nearly
    close('the new direction is square to the old',
          step['direction'].DotProduct(east), 0.0, 1e-9)
    close('and is a unit vector', step['direction'].GetLength(), 1.0, 1e-9)


def test_a_corner_behind_the_end_is_allowed():
    """It shortens the current length rather than being refused
    - that is the real constraint, not "click forwards"."""
    origin = Vec(0, 0)
    east = Vec(1, 0)

    step = so_core.plan_corner(origin, east, Vec(ft(400), ft(900)))
    truthy('a corner part way back along the length is fine', step['ok'])
    close('and keeps that much of it', step['kept_mm'], 400.0, 1e-6)

    step = so_core.plan_corner(origin, east, Vec(ft(-500), ft(900)))
    falsy('but one behind its start is not', step['ok'])
    truthy('and the refusal says why', 'further along' in step['reason'])

    step = so_core.plan_corner(origin, east, Vec(ft(4), ft(900)))
    falsy('nor one with nothing left to bend from', step['ok'])


def test_straight_on_needs_no_bend():
    origin = Vec(0, 0)
    east = Vec(1, 0)

    step = so_core.plan_corner(origin, east, Vec(ft(3000), ft(1)))
    truthy('a click straight ahead routes', step['ok'])
    truthy('as a straight carry on', step['straight'])
    check('with no new leg', step['leg_mm'], 0.0)
    check('and the same direction', step['direction'], east)

    # Between "straight on" and "a leg worth bending into"
    step = so_core.plan_corner(origin, east, Vec(ft(3000), ft(8)))
    falsy('a click a few mm off the axis is refused, not fudged',
          step['ok'])
    truthy('and says to click further out',
           'further out' in step['reason'])


def test_the_corner_rule_works_off_axis():
    """Nothing in it assumes the run is east-west or horizontal."""
    origin = Vec(ft(1000), ft(2000), ft(3000))
    north = Vec(0, 1, 0)

    step = so_core.plan_corner(origin, north,
                               Vec(ft(1000) + ft(700), ft(2000) + ft(1500),
                                   ft(3000)))
    truthy('a run heading north routes just the same', step['ok'])
    close('keeping the along part', step['kept_mm'], 1500.0, 1e-6)
    close('and turning off by the rest', step['leg_mm'], 700.0, 1e-6)
    close('still exactly square', step['direction'].DotProduct(north),
          0.0, 1e-9)


def spacing_mm(line_start, line_end, point):
    """How far a point sits off a line, square to it."""
    along = (line_end - line_start).Normalize()
    return so_core.ft_to_mm(
        so_core.cross(point - line_start, along).GetLength())


def test_a_bank_keeps_its_spacing_round_a_corner():
    """The trap this exists to stop.

    Two pipes side by side running east, translated 300mm
    north, are 300mm apart on the leg that runs east and
    EXACTLY ON TOP OF EACH OTHER on the leg that turns north.
    """
    up = Vec(0, 0, 1)
    east, north = Vec(1, 0, 0), Vec(0, 1, 0)
    start = Vec(0, 0, 0)
    corner = Vec(ft(2000), 0, 0)
    target = Vec(ft(2000), ft(1500), 0)

    # What translating it would do, for the record
    moved_corner = corner + Vec(0, ft(300), 0)
    moved_target = target + Vec(0, ft(300), 0)
    close('translating keeps the first leg apart',
          spacing_mm(start, corner, moved_corner), 300.0, 1e-6)
    close('and puts the second leg straight on top of itself',
          spacing_mm(corner, target, moved_target), 0.0, 1e-6)

    # What the tool actually does
    strand_corner, strand_target = so_core.strand_route(
        corner, target, east, north, up, ft(300), 0.0)
    close('the offset route keeps the first leg apart',
          spacing_mm(start, corner, strand_corner), 300.0, 1e-6)
    close('and the second leg too',
          spacing_mm(corner, target, strand_target), 300.0, 1e-6)

    # The inner strand has to turn earlier for that to work
    truthy('so the strand turns before the leader does',
           strand_corner.x < corner.x - 1e-9)
    close('by exactly the spacing at a square corner',
          so_core.ft_to_mm(corner.x - strand_corner.x), 300.0, 1e-6)


def test_a_stacked_bank_just_shifts():
    """Spacing straight through the routing plane needs none of
    the offsetting - it is a plain shift."""
    up = Vec(0, 0, 1)
    east, north = Vec(1, 0, 0), Vec(0, 1, 0)
    corner = Vec(ft(2000), 0, 0)
    target = Vec(ft(2000), ft(1500), 0)

    strand_corner, strand_target = so_core.strand_route(
        corner, target, east, north, up, 0.0, ft(-450))
    close('the corner drops by the stack spacing',
          so_core.ft_to_mm(corner.z - strand_corner.z), 450.0, 1e-6)
    close('and stays over the leader in plan',
          so_core.ft_to_mm(abs(strand_corner.x - corner.x)), 0.0, 1e-6)
    close('the end drops with it',
          so_core.ft_to_mm(target.z - strand_target.z), 450.0, 1e-6)


def test_the_bank_holds_at_other_angles():
    up = Vec(0, 0, 1)
    east = Vec(1, 0, 0)
    for angle in (45.0, 30.0, 22.5, 60.0):
        radians = math.radians(angle)
        out = Vec(math.cos(radians), math.sin(radians), 0)
        corner = Vec(ft(3000), 0, 0)
        target = corner + out.Multiply(ft(2000))
        strand_corner, strand_target = so_core.strand_route(
            corner, target, east, out, up, ft(300), 0.0)
        close('a {0} degree corner keeps the first leg apart'.format(angle),
              spacing_mm(Vec(0, 0, 0), corner, strand_corner), 300.0, 1e-6)
        close('and the second'.format(angle),
              spacing_mm(corner, target, strand_target), 300.0, 1e-6)


def test_parallel_check():
    east = Vec(1, 0, 0)
    truthy('one run is parallel with itself',
           so_core.axes_parallel([east])[0])
    truthy('two identical runs are parallel',
           so_core.axes_parallel([east, Vec(1, 0, 0)])[0])
    truthy('and so are two pointing at each other',
           so_core.axes_parallel([east, Vec(-1, 0, 0)])[0])

    near = Vec(math.cos(math.radians(0.2)), math.sin(math.radians(0.2)), 0)
    truthy('a fifth of a degree out is still parallel',
           so_core.axes_parallel([east, near])[0])

    off = Vec(math.cos(math.radians(3.0)), math.sin(math.radians(3.0)), 0)
    ok, worst = so_core.axes_parallel([east, off])
    falsy('three degrees out is not', ok)
    close('and the angle is reported so it can be said out loud',
          worst, 3.0, 1e-6)

    ok, worst = so_core.axes_parallel([east, Vec(1, 0, 0), off])
    falsy('one odd one out of three fails the whole set', ok)


def test_a_shallow_bend_starts_before_the_click():
    """At 90 the corner sits square under the click. At anything
    less it has to start earlier, or the leg cannot arrive."""
    origin, east = Vec(0, 0), Vec(1, 0)
    target = Vec(ft(2000), ft(500))

    square = so_core.plan_corner(origin, east, target, 90.0)
    close('a square corner sits under the click',
          so_core.ft_to_mm(square['corner'].x), 2000.0, 1e-6)

    for angle, back in ((45.0, 500.0), (30.0, 866.02540), (22.5, 1207.10678)):
        step = so_core.plan_corner(origin, east, target, angle)
        truthy('a {0} degree bend fits here'.format(angle), step['ok'])
        close('and starts {0:.0f}mm early'.format(back),
              2000.0 - so_core.ft_to_mm(step['corner'].x), back, 1e-4)
        close('arriving exactly at the click'.format(angle),
              so_core.ft_to_mm((step['target'] - target).GetLength()),
              0.0, 1e-9)
        # and the turn really is the angle asked for
        turn = math.degrees(math.acos(max(-1.0, min(1.0,
               step['direction'].DotProduct(east)))))
        close('turning exactly {0} degrees'.format(angle), turn, angle, 1e-9)

    tight = so_core.plan_corner(origin, east, Vec(ft(600), ft(500)), 22.5)
    falsy('a shallow bend with no room to start is refused', tight['ok'])
    truthy('and the refusal says how much it needed',
           'before the click' in tight['reason'])


def test_an_offset_bank_keeps_its_spacing_on_the_diagonals():
    """Same-station bends pull the diagonals closer together
    than the straight legs by cos(angle). Staggering them is
    what holds the bank square."""
    up = Vec(0, 0, 1)
    east = Vec(1, 0, 0)
    spacing = ft(300)

    for angle in (45.0, 30.0, 22.5):
        radians = math.radians(angle)
        drop = ft(300)
        back = drop / math.tan(radians)

        cut_a = Vec(ft(1000), 0, 0)
        inner_a = Vec(ft(1000) + back, drop, 0)
        inner_b = Vec(ft(6000) - back, drop, 0)
        cut_b = Vec(ft(6000), 0, 0)
        first = (inner_a - cut_a).Normalize()
        second = (cut_b - inner_b).Normalize()
        legs = [east, first, east, second, east]

        points = so_core.bank_corners([cut_a, inner_a, inner_b, cut_b], legs,
                                      up, spacing, 0.0)

        close('{0} deg: the lead leg keeps its spacing'.format(angle),
              spacing_mm(Vec(0, 0, 0), cut_a, points[0]), 300.0, 1e-6)
        close('{0} deg: and so does the first diagonal'.format(angle),
              spacing_mm(cut_a, inner_a, points[1]), 300.0, 1e-6)
        close('{0} deg: and the offset middle'.format(angle),
              spacing_mm(inner_a, inner_b, points[2]), 300.0, 1e-6)
        close('{0} deg: and the second diagonal'.format(angle),
              spacing_mm(inner_b, cut_b, points[3]), 300.0, 1e-6)

        # Which it does by turning at a different station
        stagger = so_core.ft_to_mm(points[0].x - cut_a.x)
        close('{0} deg: staggered by spacing x tan(half the turn)'.format(angle),
              abs(stagger), 300.0 * math.tan(radians / 2.0), 1e-4)

        # And the same-station version really is worse
        naive = cut_a + Vec(0, spacing, 0)
        close('{0} deg: same-station loses cos(angle) of it'.format(angle),
              spacing_mm(cut_a, inner_a, naive),
              300.0 * math.cos(radians), 1e-6)


def test_a_bank_square_to_the_offset_just_shifts():
    """Runs spread out of the plane the offset turns in need no
    staggering at all - that is a plain shift."""
    up = Vec(0, 0, 1)
    east = Vec(1, 0, 0)
    cut_a = Vec(ft(1000), 0, 0)
    inner_a = Vec(ft(1300), ft(300), 0)
    legs = [east, (inner_a - cut_a).Normalize(), east]

    points = so_core.bank_corners([cut_a, inner_a], legs, up, 0.0, ft(-450))
    close('the corner drops by the spacing',
          so_core.ft_to_mm(cut_a.z - points[0].z), 450.0, 1e-6)
    close('and does not move along the run',
          so_core.ft_to_mm(abs(points[0].x - cut_a.x)), 0.0, 1e-6)


def test_bank_split():
    up = Vec(0, 0, 1)
    east = Vec(1, 0, 0)
    north = Vec(0, 1, 0)

    # 300 to the side, 450 above, and 2000 along - the along
    # part means nothing between parallel runs and is dropped.
    offset = Vec(ft(2000), ft(300), ft(450))
    lateral, through = so_core.bank_split(offset, east, north, up)
    close('the sideways part is kept', so_core.ft_to_mm(lateral), 300.0, 1e-6)
    close('the through-plane part is kept',
          so_core.ft_to_mm(through), 450.0, 1e-6)


def test_left_and_right_do_not_depend_on_how_the_run_was_drawn():
    """The bug: right was taken from the element's own axis, so
    the same duct drawn the other way round swapped left and
    right - and the guard meant to fix it compared the side
    vector against the view's right, which is exactly zero for
    a run lying across the view."""
    up = Vec(0, 0, 1)
    screen_right, screen_up = Vec(1, 0, 0), Vec(0, 1, 0)

    east, west = Vec(1, 0, 0), Vec(-1, 0, 0)
    right_of_east = so_core.side_of_travel(east, up, screen_right, screen_up)
    right_of_west = so_core.side_of_travel(west, up, screen_right, screen_up)
    check('a run drawn east and the same run drawn west agree',
          right_of_east, right_of_west)
    close('and walking east in a plan, right is south',
          right_of_east.y, -1.0, 1e-9)

    # A run lying across the view is where the old guard did
    # nothing at all, because the dot product was zero.
    north, south = Vec(0, 1, 0), Vec(0, -1, 0)
    right_of_north = so_core.side_of_travel(north, up, screen_right, screen_up)
    right_of_south = so_core.side_of_travel(south, up, screen_right, screen_up)
    check('a run up the view agrees with the same run down it',
          right_of_north, right_of_south)
    close('and walking up the view, right is east',
          right_of_north.x, 1.0, 1e-9)

    # Left is always the other one, and both are square to the run
    for axis in (east, west, north, south, Vec(1, 1, 0).Normalize()):
        side = so_core.side_of_travel(axis, up, screen_right, screen_up)
        close('right is square to the run', side.DotProduct(axis), 0.0, 1e-9)
        close('and level', side.z, 0.0, 1e-9)

    falsy('a vertical run has no side to it',
          so_core.side_of_travel(Vec(0, 0, 1), up, screen_right, screen_up)
          is not None)


def test_travel_direction():
    screen_right, screen_up = Vec(1, 0, 0), Vec(0, 1, 0)
    check('a run reading left to right is already forwards',
          so_core.travel_direction(Vec(1, 0, 0), screen_right, screen_up),
          Vec(1, 0, 0))
    check('one reading right to left is turned round',
          so_core.travel_direction(Vec(-1, 0, 0), screen_right, screen_up),
          Vec(1, 0, 0))
    check('one straight up the view falls back to bottom to top',
          so_core.travel_direction(Vec(0, -1, 0), screen_right, screen_up),
          Vec(0, 1, 0))


def test_which_half_is_which_is_measured():
    """The bug: BreakCurve returns "the new element" without
    saying which side of the cut it is, and it was taken for
    the far half. Where it was not, the original run stayed at
    full length with the offset pieces laid over the top."""
    east = Vec(1, 0, 0)
    origin = Vec(0, 0, 0)

    near_mid = Vec(ft(500), 0, 0)
    far_mid = Vec(ft(2500), 0, 0)

    check('handed near then far, the order is kept',
          so_core.halves_in_order(near_mid, far_mid, origin, east), (0, 1))
    check('handed far then near, the order is turned round',
          so_core.halves_in_order(far_mid, near_mid, origin, east), (1, 0))

    # And it has to hold when the run points the other way
    west = Vec(-1, 0, 0)
    check('a run drawn the other way still sorts correctly',
          so_core.halves_in_order(near_mid, far_mid, origin, west), (1, 0))

    # Off axis, and not from the origin
    north = Vec(0, 1, 0)
    base = Vec(ft(1000), ft(1000), ft(3000))
    check('and off axis, measured from wherever the run starts',
          so_core.halves_in_order(base + Vec(0, ft(4000), 0),
                                  base + Vec(0, ft(200), 0), base, north),
          (1, 0))


def plan_gradient(start, end, up=None):
    """Rise over PLAN run between two points."""
    up = up or Vec(0, 0, 1)
    span = end - start
    rise = span.DotProduct(up)
    flat = span - up.Multiply(rise)
    return rise / flat.GetLength()


def test_gradient_is_rise_over_plan_run():
    up = Vec(0, 0, 1)
    # 1:60 heading east
    axis = Vec(60, 0, -1).Normalize()
    close('a 1 in 60 fall reads as 1 in 60',
          abs(1.0 / so_core.gradient(axis, up)), 60.0, 1e-9)
    check('and is written the way engineers write it',
          so_core.describe_gradient(so_core.gradient(axis, up)), u'1:60')

    close('rise over PLAN run, not over the slope length',
          so_core.gradient(Vec(1, 0, 1).Normalize(), up), 1.0, 1e-9)

    check('a level run is level',
          so_core.describe_gradient(so_core.gradient(Vec(1, 0, 0), up)),
          u'level')
    falsy('and does not count as sloped',
          so_core.is_sloped(so_core.gradient(Vec(1, 0, 0), up)))
    check('a vertical run has no gradient',
          so_core.gradient(Vec(0, 0, 1), up), None)


def test_with_fall_puts_a_plan_point_on_the_gradient():
    up = Vec(0, 0, 1)
    grade = -1.0 / 60.0
    start = Vec(0, 0, ft(3000))

    # 6000mm along in plan at 1:60 is 100mm of fall
    landed = so_core.with_fall(start, Vec(ft(6000), 0, ft(9999)), up, grade)
    close('the plan position is kept', so_core.ft_to_mm(landed.x), 6000.0, 1e-6)
    close('and the level comes from the gradient, not the click',
          so_core.ft_to_mm(start.z - landed.z), 100.0, 1e-6)
    close('so the piece is exactly on grade',
          abs(1.0 / plan_gradient(start, landed)), 60.0, 1e-9)

    # Round a corner, still on grade
    corner = so_core.with_fall(start, Vec(ft(2000), 0, 0), up, grade)
    onward = so_core.with_fall(corner, Vec(ft(2000), ft(1500), 0), up, grade)
    close('and so is the next one after a turn',
          abs(1.0 / plan_gradient(corner, onward)), 60.0, 1e-9)
    close('the fall accumulating along the way',
          so_core.ft_to_mm(start.z - onward.z), (2000.0 + 1500.0) / 60.0, 1e-6)


def test_a_jog_cannot_hold_the_fall_and_rejoin():
    """The constraint behind the whole design decision: a jog is
    longer in plan than the straight it replaces, and at a fixed
    gradient extra length is extra fall."""
    grade = 1.0 / 60.0

    close('a 300mm 45 degree jog at 1:60 would arrive 4mm low',
          so_core.jog_fall_shortfall(300.0, 45.0, grade), 4.14, 0.01)
    close('a square jog costs more',
          so_core.jog_fall_shortfall(300.0, 90.0, grade), 10.0, 1e-6)
    close('and a shallower bend costs less',
          so_core.jog_fall_shortfall(300.0, 22.5, grade), 1.99, 0.01)

    close('twice the offset, twice the shortfall',
          so_core.jog_fall_shortfall(600.0, 45.0, grade),
          2.0 * so_core.jog_fall_shortfall(300.0, 45.0, grade), 1e-9)

    check('a level run has none of this to worry about',
          so_core.jog_fall_shortfall(300.0, 45.0, 0.0), 0.0)


def test_a_break_holds_the_fall_on_every_piece():
    """A break does not rejoin, so it can."""
    up = Vec(0, 0, 1)
    grade = -1.0 / 60.0
    axis = Vec(1, 0, 0)

    cut_a = Vec(ft(1000), 0, ft(3000))
    # where the bend and the far end would land before the fall
    inner_a = Vec(ft(1300), ft(300), ft(3000))
    end_b = Vec(ft(4000), ft(300), ft(3000))

    bend = so_core.with_fall(cut_a, inner_a, up, grade)
    stepped = so_core.with_fall(bend, end_b, up, grade)

    close('the bend leg is on grade',
          abs(1.0 / plan_gradient(cut_a, bend)), 60.0, 1e-9)
    close('and the stepped run is on grade',
          abs(1.0 / plan_gradient(bend, stepped)), 60.0, 1e-9)
    # End to end is STEEPER than 1:60 in plan, and that is
    # right: the route turns, so its path is longer than the
    # straight line between its ends, and the fall follows the
    # path. Measuring a turning route corner to corner is how
    # you talk yourself into thinking a correct route is wrong.
    path_mm = (so_core.ft_to_mm((bend - cut_a).GetLength())
               + so_core.ft_to_mm((stepped - bend).GetLength()))
    close('the total fall follows the path, not the straight line',
          so_core.ft_to_mm(cut_a.z - stepped.z), path_mm / 60.0, 0.01)
    truthy('so end to end reads steeper than the gradient',
           abs(1.0 / plan_gradient(cut_a, stepped)) < 60.0)


def test_a_set_length_changes_what_the_click_means():
    """Blank: the piece runs to the click. Set: the click only
    puts the corner and says which way to turn."""
    origin, east = Vec(0, 0), Vec(1, 0)
    click = Vec(ft(2000), ft(500))

    loose = so_core.plan_corner(origin, east, click, 90.0)
    close('with no length, the piece ends at the click',
          so_core.ft_to_mm((loose['target'] - click).GetLength()), 0.0, 1e-9)

    fixed = so_core.plan_corner(origin, east, click, 90.0, leg_mm=1200.0)
    close('with a length, the corner still goes under the click',
          so_core.ft_to_mm(fixed['corner'].x), 2000.0, 1e-6)
    close('and the piece is the length asked for',
          so_core.ft_to_mm((fixed['target'] - fixed['corner']).GetLength()),
          1200.0, 1e-6)
    close('turning square', fixed['direction'].DotProduct(east), 0.0, 1e-9)
    close('towards the side clicked', fixed['target'].y, ft(1200), 1e-9)

    # The other side
    other = so_core.plan_corner(origin, east, Vec(ft(2000), ft(-500)), 90.0,
                                leg_mm=1200.0)
    close('and the other way when clicked the other way',
          other['target'].y, ft(-1200), 1e-9)


def test_a_set_length_at_a_shallower_angle():
    origin, east = Vec(0, 0), Vec(1, 0)
    step = so_core.plan_corner(origin, east, Vec(ft(3000), ft(800)), 45.0,
                               leg_mm=1000.0)
    truthy('a 45 degree leg of a set length routes', step['ok'])
    close('the leg is the length asked for',
          so_core.ft_to_mm((step['target'] - step['corner']).GetLength()),
          1000.0, 1e-6)
    turn = math.degrees(math.acos(max(-1.0, min(1.0,
           step['direction'].DotProduct(east)))))
    close('and the turn is the angle asked for', turn, 45.0, 1e-9)
    # A set length does not have to start early - the corner is
    # where the click is, not where the leg has to arrive.
    close('the corner sits under the click',
          so_core.ft_to_mm(step['corner'].x), 3000.0, 1e-6)


def test_a_set_length_straight_on():
    origin, east = Vec(0, 0), Vec(1, 0)
    step = so_core.plan_corner(origin, east, Vec(ft(2000), ft(1)), 90.0,
                               leg_mm=700.0)
    truthy('a click straight ahead with a length routes', step['ok'])
    truthy('with no bend', step['straight'])
    close('and simply carries on that far past the corner',
          so_core.ft_to_mm(step['target'].x), 2700.0, 1e-6)


def test_a_set_length_still_needs_run_to_cut():
    origin, east = Vec(0, 0), Vec(1, 0)
    step = so_core.plan_corner(origin, east, Vec(ft(4), ft(900)), 90.0,
                               leg_mm=1000.0)
    falsy('a corner with nothing behind it is still refused', step['ok'])


def test_a_rise_gains_its_height_at_its_angle():
    up = Vec(0, 0, 1)
    east = Vec(1, 0, 0)
    start = Vec(0, 0, ft(3000))

    top, direction = so_core.rise_step(start, east, up, 500.0, 45.0, True)
    close('it gains the height asked for',
          so_core.ft_to_mm(top.z - start.z), 500.0, 1e-6)
    close('over the same again in plan at 45 degrees',
          so_core.ft_to_mm(top.x - start.x), 500.0, 1e-6)
    turn = math.degrees(math.acos(max(-1.0, min(1.0,
           direction.DotProduct(east)))))
    close('rising at 45 degrees', turn, 45.0, 1e-9)

    top, _d = so_core.rise_step(start, east, up, 500.0, 45.0, False)
    close('down loses it instead',
          so_core.ft_to_mm(start.z - top.z), 500.0, 1e-6)
    close('and still runs forwards in plan',
          so_core.ft_to_mm(top.x - start.x), 500.0, 1e-6)

    # 90 degrees is a plain riser, which is the old behaviour
    top, direction = so_core.rise_step(start, east, up, 500.0, 90.0, True)
    close('a 90 degree rise takes no run at all',
          so_core.ft_to_mm(top.x - start.x), 0.0, 1e-9)
    close('and is straight up', direction.DotProduct(up), 1.0, 1e-9)

    # Shallower angles eat more run
    for angle, run in ((30.0, 866.0254), (22.5, 1207.1068), (60.0, 288.6751)):
        close('{0} degrees needs {1:.0f}mm of run'.format(angle, run),
              so_core.rise_plan_run_mm(500.0, angle), run, 1e-3)
        top, _d = so_core.rise_step(start, east, up, 500.0, angle, True)
        close('and the piece agrees with it',
              so_core.ft_to_mm(top.x - start.x), run, 1e-3)


def test_a_stacked_bank_keeps_its_height_through_a_rise():
    """Every run gains the same height over the same plan run,
    so services above one another stay as far apart as they
    were. That is what was asked for - note it leaves them
    closer together square to a sloping leg, by cos(angle)."""
    up = Vec(0, 0, 1)
    east = Vec(1, 0, 0)

    lower = Vec(0, 0, ft(3000))
    upper = Vec(0, 0, ft(3300))
    close('they start 300mm apart',
          so_core.ft_to_mm(upper.z - lower.z), 300.0, 1e-9)

    lower_top, _a = so_core.rise_step(lower, east, up, 500.0, 45.0, True)
    upper_top, _b = so_core.rise_step(upper, east, up, 500.0, 45.0, True)

    close('and they are still 300mm apart at the top',
          so_core.ft_to_mm(upper_top.z - lower_top.z), 300.0, 1e-9)
    close('having turned at the same place along the run',
          so_core.ft_to_mm(upper_top.x - lower_top.x), 0.0, 1e-9)

    # The trade, written down: square to the sloping legs they
    # are closer than they are vertically.
    across = spacing_mm(lower, lower_top, upper)
    close('square to a 45 degree leg that reads as 212mm',
          across, 300.0 * math.cos(math.radians(45.0)), 1e-6)


def test_a_level_change_fits_the_room_it_is_given():
    """The height is the point of the move and is never given
    up. The run on shortens first, then the angle steepens."""
    height, angle, lead = 1000.0, 45.0, 3000.0

    plenty = so_core.fit_level_change(4010.0, height, angle, lead)
    truthy('with room to spare it uses the numbers as asked', plenty['ok'])
    close('the run on is untouched', plenty['lead_mm'], 3000.0, 1e-6)
    close('and the angle', plenty['angle_deg'], 45.0, 1e-9)
    check('with nothing to report', plenty['changed'], [])

    tight = so_core.fit_level_change(3000.0, height, angle, lead)
    truthy('less room still works', tight['ok'])
    close('the angle is held', tight['angle_deg'], 45.0, 1e-9)
    close('and the run on gives way', tight['lead_mm'], 1990.0, 1e-6)
    truthy('and it says so', 'ran on' in u' '.join(tight['changed']))

    steep = so_core.fit_level_change(600.0, height, angle, lead)
    truthy('too little for 45 degrees still works', steep['ok'])
    truthy('by steepening', steep['angle_deg'] > 45.0)
    truthy('and saying so', 'steepened' in u' '.join(steep['changed']))

    # Whatever it does, the pieces have to add up to the room
    for total in (4010.0, 3000.0, 1200.0, 600.0, 120.0):
        fit = so_core.fit_level_change(total, height, angle, lead)
        truthy('{0:.0f}mm of room fits'.format(total), fit['ok'])
        close('{0:.0f}mm: the pieces add up'.format(total),
              fit['lead_mm'] + fit['rise_run_mm'] + fit['landing_mm'],
              total, 1e-6)
        truthy('{0:.0f}mm: the landing is usable'.format(total),
               fit['landing_mm'] >= so_core.MIN_LEG_MM - 1e-9)
        truthy('{0:.0f}mm: the angle stays sane'.format(total),
               0.0 < fit['angle_deg'] <= 90.0)
        # the height is never traded away
        close('{0:.0f}mm: the rise still gains the height'.format(total),
              so_core.rise_plan_run_mm(height, fit['angle_deg']),
              fit['rise_run_mm'], 1e-6)

    nothing = so_core.fit_level_change(15.0, height, angle, lead)
    falsy('only genuinely no room is refused', nothing['ok'])
    truthy('and it says how far along the click was',
           'along the run' in nothing['reason'])


def test_the_whole_level_change_lands_where_it_should():
    up = Vec(0, 0, 1)
    east = Vec(1, 0, 0)
    start = Vec(0, 0, ft(3000))
    lead, height, angle = 500.0, 500.0, 45.0

    # 1 - run on
    after_lead = start + east.Multiply(ft(lead))
    close('the turn starts 500mm past the end',
          so_core.ft_to_mm(after_lead.x - start.x), 500.0, 1e-9)
    close('at the level it was', so_core.ft_to_mm(after_lead.z - start.z),
          0.0, 1e-9)

    # 2 - rise
    top, direction = so_core.rise_step(after_lead, east, up, height, angle,
                                       True)
    close('it gains the offset', so_core.ft_to_mm(top.z - start.z),
          500.0, 1e-6)
    close('reaching 1000mm along in plan',
          so_core.ft_to_mm(top.x - start.x), 1000.0, 1e-6)

    # 3 - straight on to a click 3000mm along
    click_x = ft(3000)
    landing = top + east.Multiply(click_x - (top.x - start.x) - start.x)
    close('and lands at the click', so_core.ft_to_mm(landing.x - start.x),
          3000.0, 1e-6)
    close('still at the new level',
          so_core.ft_to_mm(landing.z - top.z), 0.0, 1e-9)
    close('which is the offset above where it began',
          so_core.ft_to_mm(landing.z - start.z), 500.0, 1e-6)


def test_a_service_is_measured_the_way_it_moves():
    """A 600 x 300 duct is 300 out to the side and 150 up. Using
    the larger dimension both ways over-clears the narrow way by
    150mm, which is safe but moves services further than they
    need to go."""
    centre = Vec(0, 0, 0)
    east, north, up = Vec(1, 0, 0), Vec(0, 1, 0), Vec(0, 0, 1)

    # a 600 wide by 300 deep duct, running north
    body = [Vec(ft(x), ft(y), ft(z))
            for x in (-300, 300) for y in (-1000, 1000) for z in (-150, 150)]

    close('300 out to the side', so_core.half_extent(body, centre, east),
          300.0, 1e-6)
    close('but only 150 up', so_core.half_extent(body, centre, up),
          150.0, 1e-6)

    # insulation is separate geometry, and has to count
    lagged = body + [Vec(ft(x), ft(y), ft(z))
                     for x in (-325, 325) for y in (-1000, 1000)
                     for z in (-175, 175)]
    close('25mm of lagging widens it', so_core.half_extent(lagged, centre, east),
          325.0, 1e-6)
    close('and deepens it', so_core.half_extent(lagged, centre, up),
          175.0, 1e-6)

    # a round pipe is the same every way
    import math as _math
    pipe = [Vec(ft(150 * _math.cos(t / 8.0 * _math.pi)), 0,
                ft(150 * _math.sin(t / 8.0 * _math.pi))) for t in range(16)]
    close('a round pipe reads the same sideways',
          so_core.half_extent(pipe, centre, east), 150.0, 1e-6)
    close('as it does upwards',
          so_core.half_extent(pipe, centre, up), 150.0, 1e-6)

    check('nothing to measure is no answer',
          so_core.half_extent([], centre, east), None)


def test_the_offset_clears_by_size_plus_clearance():
    """The distance is the obstruction's reach, plus the
    service's own half size that way, plus the clearance."""
    centre = Vec(0, 0, 0)
    up = Vec(0, 0, 1)

    # a column reaching 400mm to one side of the run
    column = [Vec(ft(x), ft(y), ft(z))
              for x in (-400, 400) for y in (-400, 400) for z in (-3000, 3000)]
    reach = so_core.span_along(column, centre, Vec(1, 0, 0))
    close('the column reaches 400mm that way', reach[1], 400.0, 1e-6)

    duct = [Vec(ft(x), ft(y), ft(z))
            for x in (-300, 300) for y in (-1000, 1000) for z in (-150, 150)]
    sideways = reach[1] + so_core.half_extent(duct, centre, Vec(1, 0, 0)) + 50.0
    upward = (so_core.span_along(column, centre, up)[1]
              + so_core.half_extent(duct, centre, up) + 50.0)

    close('going sideways needs 750mm', sideways, 750.0, 1e-6)
    close('going up needs 3200mm', upward, 3200.0, 1e-6)
    check('so a column is gone round, not over',
          so_core.choose_escape({u'left': sideways, u'right': sideways,
                                 u'up': upward, u'down': upward},
                                u'column')['direction'], u'left')


def test_which_way_round_a_clash():
    """The shape says what SHOULD be preferred; the numbers say
    whether that preference is affordable."""
    round_it = {u'left': 420.0, u'right': 480.0,
                u'up': 3100.0, u'down': 2800.0}
    chosen = so_core.choose_escape(round_it, u'column')
    check('a column is gone round', chosen['direction'], u'left')
    truthy('as the preferred way', chosen['preferred'])

    # Same column, but going round has become absurd
    costly = {u'left': 4200.0, u'right': 4600.0,
              u'up': 900.0, u'down': 310.0}
    chosen = so_core.choose_escape(costly, u'column')
    check('unless going round costs far more', chosen['direction'], u'down')

    beam = {u'left': 5200.0, u'right': 5600.0,
            u'up': 2400.0, u'down': 340.0}
    check('a beam is gone under',
          so_core.choose_escape(beam, u'beam')['direction'], u'down')

    # A near tie goes to the preference, not to a few mm
    close_call = {u'left': 420.0, u'right': 400.0,
                  u'up': 5000.0, u'down': 5000.0}
    check('a near tie goes to the preferred side',
          so_core.choose_escape(close_call, u'column')['direction'], u'left')

    # Directions that do not exist are not offered
    vertical_run = {u'left': 300.0, u'right': 320.0,
                    u'up': None, u'down': None}
    check('a way that is not available is never chosen',
          so_core.choose_escape(vertical_run, u'beam')['direction'], u'left')

    check('nothing available is no answer at all',
          so_core.choose_escape({u'up': None}, u'beam'), None)


def test_the_cuts_clear_the_obstruction():
    """The middle of a jog starts a bend's worth in from the
    cut, so the cuts have to sit back by that too or the
    sloping legs clip the very thing being avoided."""
    # 600mm wide obstruction, 400mm offset at 45 degrees,
    # 100mm of clearance along the run
    cut_a, cut_b = so_core.clash_cuts(-300.0, 300.0, 400.0, 45.0, 100.0)
    back = so_core.run_back_mm(400.0, 45.0)
    close('the first cut sits back by the clearance and the bend',
          cut_a, -300.0 - 100.0 - back, 1e-6)
    close('and the second the other way',
          cut_b, 300.0 + 100.0 + back, 1e-6)

    # The offset middle must start clear of the obstruction
    close('so the middle starts at the clearance, not inside it',
          cut_a + back, -400.0, 1e-6)
    close('and ends at the clearance the other side',
          cut_b - back, 400.0, 1e-6)

    # A square jog eats no run, so the cuts are just the clearance
    cut_a, cut_b = so_core.clash_cuts(-300.0, 300.0, 400.0, 90.0, 100.0)
    close('a square jog cuts at the clearance', cut_a, -400.0, 1e-6)
    close('either side', cut_b, 400.0, 1e-6)


def test_units():
    close('a foot is 304.8mm', so_core.ft_to_mm(1.0), 304.8)
    close('and back again', so_core.mm_to_ft(304.8), 1.0)


def test_as_bool():
    for text in (u'1', u'true', u'TRUE', u'yes', u'on'):
        truthy('"{0}" is true'.format(text), so_core.as_bool(text))
    for text in (u'0', u'false', u'no', u'off', u'', None):
        falsy('"{0}" is false'.format(text), so_core.as_bool(text))


def test_as_float():
    check('a number parses', so_core.as_float(u'2.5'), 2.5)
    check('rubbish falls back', so_core.as_float(u'wide', 7.0), 7.0)
    check('and so does nothing at all', so_core.as_float(None, 3.0), 3.0)


def test_eid_value():
    class NewStyle(object):
        Value = 1234

    class OldStyle(object):
        @property
        def Value(self):
            raise AttributeError('gone in 2026')
        IntegerValue = 5678

    check('2026 style reads .Value', so_core.eid_value(NewStyle()), 1234)
    check('2024 style falls back to .IntegerValue',
          so_core.eid_value(OldStyle()), 5678)
    check('nothing at all is zero', so_core.eid_value(None), 0)


TESTS = (
    test_run_back, test_break_needs_one_bend_not_two, test_minimum_span, test_snap_angle, test_round_to,
    test_plan_offset,
    test_default_distance, test_max_offset,
    test_settings_round_trip, test_settings_missing_file,
    test_settings_damaged_file, test_settings_migration,
    test_settings_migration_from_v3,
    test_settings_value_with_equals,
    test_settings_are_small, test_a_clean_run_says_nothing,
    test_a_service_is_measured_the_way_it_moves,
    test_the_offset_clears_by_size_plus_clearance,
    test_which_way_round_a_clash, test_the_cuts_clear_the_obstruction,
    test_the_corner_is_square, test_a_corner_behind_the_end_is_allowed,
    test_straight_on_needs_no_bend, test_the_corner_rule_works_off_axis,
    test_a_bank_keeps_its_spacing_round_a_corner,
    test_a_stacked_bank_just_shifts, test_the_bank_holds_at_other_angles,
    test_parallel_check, test_a_shallow_bend_starts_before_the_click,
    test_left_and_right_do_not_depend_on_how_the_run_was_drawn,
    test_which_half_is_which_is_measured,
    test_gradient_is_rise_over_plan_run,
    test_with_fall_puts_a_plan_point_on_the_gradient,
    test_a_jog_cannot_hold_the_fall_and_rejoin,
    test_a_break_holds_the_fall_on_every_piece,
    test_a_set_length_changes_what_the_click_means,
    test_a_set_length_at_a_shallower_angle,
    test_a_set_length_straight_on,
    test_a_set_length_still_needs_run_to_cut,
    test_a_rise_gains_its_height_at_its_angle,
    test_a_stacked_bank_keeps_its_height_through_a_rise,
    test_a_level_change_fits_the_room_it_is_given,
    test_the_whole_level_change_lands_where_it_should,
    test_travel_direction,
    test_an_offset_bank_keeps_its_spacing_on_the_diagonals,
    test_a_bank_square_to_the_offset_just_shifts, test_bank_split,
    test_units, test_as_bool, test_as_float, test_eid_value,
)


def main():
    sys.stdout.write('RevoBIM System Offset - logic bench\n\n')
    for test in TESTS:
        test()
    for line in FAILED:
        sys.stdout.write('FAIL  {0}\n'.format(line))
    sys.stdout.write('\n{0} checks pass, {1} fail.\n'
                     .format(len(PASSED), len(FAILED)))
    return 1 if FAILED else 0


if __name__ == '__main__':
    sys.exit(main())
