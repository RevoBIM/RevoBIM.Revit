# -*- coding: utf-8 -*-
"""Bench test of the Tag Leader Elbow rules, under plain CPython.

tle_core carries no Revit or .NET import, so the rules under test here are the
real shipped code rather than a copy of it.  Run from this folder:

    python bench_logic.py
"""

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tle_core  # noqa: E402

RESULTS = []


def check(label, got, wanted):
    ok = got == wanted
    RESULTS.append((ok, label, got, wanted))
    return ok


def close(label, got, wanted, tolerance=1e-9):
    ok = abs(got - wanted) <= tolerance
    RESULTS.append((ok, label, got, wanted))
    return ok


def cfg(**overrides):
    values = dict(tle_core.DEFAULTS)
    values.update(dict((key, str(value)) for key, value in overrides.items()))
    return values


# ============================================================================
# a fake XYZ, so the elbow point itself can be proved without Revit
# ============================================================================

class XYZ(object):

    def __init__(self, x, y, z=0.0):
        self.X, self.Y, self.Z = float(x), float(y), float(z)

    def __add__(self, other):
        return XYZ(self.X + other.X, self.Y + other.Y, self.Z + other.Z)

    def __sub__(self, other):
        return XYZ(self.X - other.X, self.Y - other.Y, self.Z - other.Z)

    def Multiply(self, factor):
        return XYZ(self.X * factor, self.Y * factor, self.Z * factor)

    def DotProduct(self, other):
        return self.X * other.X + self.Y * other.Y + self.Z * other.Z


def elbow_point(head, leader_end, right, settings, scale, width=0.0):
    """The same four lines tle_ops runs, on the fake vectors."""
    along = (leader_end - head).DotProduct(right)
    sign, reason = tle_core.decide(True, along, False, settings)
    if sign == 0:
        return None, reason
    length = tle_core.elbow_length_ft(settings, scale)
    offset = tle_core.leg_offset_ft(width, length, sign, settings)
    return head + right.Multiply(offset * sign), None


# ============================================================================
# units and length
# ============================================================================

close("a foot is 304.8mm", tle_core.ft_to_mm(1.0), 304.8, 1e-9)
close("150mm round trips", tle_core.ft_to_mm(tle_core.mm_to_ft(150.0)), 150.0, 1e-9)

close("150mm at 1:50 stays 150mm", tle_core.elbow_length_mm(cfg(), 50), 150.0)
close("150mm at 1:100 becomes 300mm", tle_core.elbow_length_mm(cfg(), 100), 300.0)
close("150mm at 1:20 becomes 60mm", tle_core.elbow_length_mm(cfg(), 20), 60.0)
close("150mm at 1:200 becomes 600mm", tle_core.elbow_length_mm(cfg(), 200), 600.0)
close("scaling off holds 150mm at 1:100",
      tle_core.elbow_length_mm(cfg(scale_with_view=0), 100), 150.0)
close("a different nominal length scales the same way",
      tle_core.elbow_length_mm(cfg(elbow_mm=200), 100), 400.0)
close("a nonsense view scale falls back to the quoted one",
      tle_core.elbow_length_mm(cfg(), 0), 150.0)
close("a damaged length setting falls back to the default",
      tle_core.elbow_length_mm(cfg(elbow_mm="rubbish"), 50), 150.0)

# ============================================================================
# which side the elbow goes
# ============================================================================

check("a leader running right elbows right", tle_core.choose_sign(2.0, cfg())[0], 1)
check("a leader running left elbows left", tle_core.choose_sign(-2.0, cfg())[0], -1)
check("reverse flips a right hand leader",
      tle_core.choose_sign(2.0, cfg(direction="reverse"))[0], -1)
check("reverse flips a left hand leader",
      tle_core.choose_sign(-2.0, cfg(direction="reverse"))[0], 1)

check("a leader straight up or down elbows left by default",
      tle_core.choose_sign(0.0, cfg())[0], -1)
sign, reason = tle_core.choose_sign(0.0, cfg(ambiguous="skip"))
check("skip is still available for it", sign, 0)
check("and it says why", bool(reason), True)
check("forced right gives a right elbow", tle_core.choose_sign(0.0, cfg(ambiguous="right"))[0], 1)
check("reverse does not flip the straight up default, which is absolute",
      tle_core.choose_sign(0.0, cfg(direction="reverse"))[0], -1)
check("half a millimetre is inside the tolerance, so the default applies",
      tle_core.choose_sign(tle_core.mm_to_ft(0.5), cfg())[0], -1)
check("two millimetres is outside it",
      tle_core.choose_sign(tle_core.mm_to_ft(2.0), cfg())[0], 1)

# ============================================================================
# the whole decision
# ============================================================================

check("a tag with no leader is skipped", tle_core.decide(False, 2.0, False, cfg())[0], 0)
check("and the reason names the leader",
      "leader" in tle_core.decide(False, 2.0, False, cfg())[1], True)
check("an existing elbow is replaced by default",
      tle_core.decide(True, 2.0, True, cfg())[0], 1)
check("an existing elbow is left alone when asked",
      tle_core.decide(True, 2.0, True, cfg(existing_elbow="keep"))[0], 0)
check("a leader end that could not be located is skipped",
      tle_core.decide(True, None, False, cfg())[0], 0)

# ============================================================================
# where the leg starts
# ============================================================================

WIDTH = tle_core.mm_to_ft(420.0)   # a 420mm wide tag
LEG = tle_core.mm_to_ft(150.0)


def offset_mm(sign, **overrides):
    return tle_core.ft_to_mm(tle_core.leg_offset_ft(WIDTH, LEG, sign, cfg(**overrides)))


# left justified: the head is at the left hand end of the text
close("left justified, running left, the leg starts at the head",
      offset_mm(-1), 150.0, 1e-9)
close("left justified, running right, it starts past the end of the text",
      offset_mm(1), 570.0, 1e-9)

# right justified is the mirror of it
close("right justified, running right, the leg starts at the head",
      offset_mm(1, justification="right"), 150.0, 1e-9)
close("right justified, running left, it starts past the end of the text",
      offset_mm(-1, justification="right"), 570.0, 1e-9)

# centred clears half the width either way
close("centred, running left, half the text is cleared",
      offset_mm(-1, justification="centre"), 360.0, 1e-9)
close("centred, running right, the same",
      offset_mm(1, justification="centre"), 360.0, 1e-9)

close("from the head, it is just the leg whichever way and however justified",
      offset_mm(1, start_from="head"), 150.0, 1e-9)
close("and the same going the other way",
      offset_mm(-1, start_from="head", justification="centre"), 150.0, 1e-9)
close("a tag with no measurable text still gets its leg",
      tle_core.ft_to_mm(tle_core.leg_offset_ft(0.0, LEG, 1, cfg())), 150.0, 1e-9)

# ============================================================================
# the tag's own measured extent
# ============================================================================

def ft(mm):
    return tle_core.mm_to_ft(mm)


# a three line tag, head on the top line: the box runs 400mm up from the head
# and 100mm down, and 420mm to the right of it
BOX = (ft(-400.0), ft(100.0), ft(0.0), ft(420.0))

close("the elbow drops onto the exact middle of the measured box",
      tle_core.ft_to_mm(tle_core.centre_from_box_ft(BOX)), -150.0, 1e-9)
close("running right, all the tag on that side is cleared",
      tle_core.ft_to_mm(tle_core.ahead_from_box_ft(BOX, 1, cfg())), 420.0, 1e-9)
close("running left, there is none of it in the way",
      tle_core.ft_to_mm(tle_core.ahead_from_box_ft(BOX, -1, cfg())), 0.0, 1e-9)

CENTRED = (ft(-150.0), ft(150.0), ft(-210.0), ft(210.0))
close("a centred tag needs no drop at all",
      tle_core.ft_to_mm(tle_core.centre_from_box_ft(CENTRED)), 0.0, 1e-9)
close("and clears half its width either way",
      tle_core.ft_to_mm(tle_core.ahead_from_box_ft(CENTRED, -1, cfg())), 210.0, 1e-9)

check("no box means no measured answer, so the text rules take over",
      tle_core.centre_from_box_ft(None), None)
check("and the same for the width", tle_core.ahead_from_box_ft(None, 1, cfg()), None)
close("a box that does not reach the leg's side never gives a negative",
      tle_core.ahead_from_box_ft((ft(-10.0), ft(10.0), ft(-420.0), ft(-10.0)), 1, cfg()),
      0.0, 1e-12)

# ============================================================================
# keeping the run into the tag horizontal, from the text (the fallback)
# ============================================================================

PITCH = tle_core.mm_to_ft(200.0)


def shift_mm(lines, **overrides):
    return tle_core.ft_to_mm(tle_core.vertical_shift_ft(PITCH, lines, cfg(**overrides)))


close("a one line tag needs no drop at all", shift_mm(1), 0.0)
close("a two line tag drops half a line", shift_mm(2), -100.0, 1e-9)
close("a three line tag drops a whole line onto the middle one",
      shift_mm(3), -200.0, 1e-9)
close("a four line tag drops a line and a half", shift_mm(4), -300.0, 1e-9)
close("a head already on the middle is left alone",
      shift_mm(3, head_vertical="middle"), 0.0)
close("a head on the bottom line rises instead",
      shift_mm(3, head_vertical="bottom"), 200.0, 1e-9)
close("no measurable line pitch means no drop",
      tle_core.ft_to_mm(tle_core.vertical_shift_ft(0.0, 3, cfg())), 0.0)
check("a nonsense line count is treated as one line",
      tle_core.vertical_shift_ft(PITCH, None, cfg()), 0.0)

close("a one line estimate is the character count times the em times the glyph width",
      tle_core.estimate_text_width_mm("ABCD", 2.5, 1.0, 0.5), 5.0, 1e-9)
close("the widest line wins on a multi line tag",
      tle_core.estimate_text_width_mm("AB\nABCDEF", 2.5, 1.0, 0.5), 7.5, 1e-9)
close("the width factor scales it",
      tle_core.estimate_text_width_mm("ABCD", 2.5, 0.8, 0.5), 4.0, 1e-9)
close("empty text measures nothing",
      tle_core.estimate_text_width_mm("", 2.5, 1.0, 0.5), 0.0)

# ============================================================================
# the elbow point itself
# ============================================================================

RIGHT = XYZ(1, 0, 0)
HEAD = XYZ(10.0, 5.0, 0.0)

point, _ = elbow_point(HEAD, XYZ(2.0, 3.0, 0.0), RIGHT, cfg(), 50)
close("a leader to the left puts the elbow 150mm left of the head",
      tle_core.ft_to_mm(point.X - HEAD.X), -150.0, 1e-6)
close("and does not move it along the string", point.Y - HEAD.Y, 0.0)
close("and does not move it in Z", point.Z - HEAD.Z, 0.0)

point, _ = elbow_point(HEAD, XYZ(18.0, 9.0, 0.0), RIGHT, cfg(), 50)
close("a leader to the right puts the elbow 150mm right of the head",
      tle_core.ft_to_mm(point.X - HEAD.X), 150.0, 1e-6)

point, _ = elbow_point(HEAD, XYZ(2.0, 3.0, 0.0), RIGHT, cfg(), 100)
close("the same leader at 1:100 gets a 300mm leg",
      tle_core.ft_to_mm(point.X - HEAD.X), -300.0, 1e-6)

# a rotated view: right is the view's own horizontal, not the world X axis
ROTATED = XYZ(0.0, 1.0, 0.0)
point, _ = elbow_point(HEAD, XYZ(10.0, 20.0, 0.0), ROTATED, cfg(), 50)
close("a rotated view elbows along the view's own horizontal",
      tle_core.ft_to_mm(point.Y - HEAD.Y), 150.0, 1e-6)
close("and leaves the other axis alone", point.X - HEAD.X, 0.0)

point, _ = elbow_point(HEAD, XYZ(10.0, 20.0, 0.0), RIGHT, cfg(), 50)
close("a leader straight up the view elbows left",
      tle_core.ft_to_mm(point.X - HEAD.X), -150.0, 1e-6)

point, reason = elbow_point(HEAD, XYZ(10.0, 20.0, 0.0), RIGHT, cfg(ambiguous="skip"), 50)
check("unless it is set to skip instead", point, None)

WIDE = tle_core.mm_to_ft(420.0)

point, _ = elbow_point(HEAD, XYZ(2.0, 3.0, 0.0), RIGHT, cfg(), 50, width=WIDE)
close("a left justified tag running left puts the elbow 150mm from the head",
      tle_core.ft_to_mm(point.X - HEAD.X), -150.0, 1e-6)

point, _ = elbow_point(HEAD, XYZ(18.0, 3.0, 0.0), RIGHT, cfg(), 50, width=WIDE)
close("the same tag running right clears all 420mm of it first",
      tle_core.ft_to_mm(point.X - HEAD.X), 570.0, 1e-6)

point, _ = elbow_point(HEAD, XYZ(18.0, 3.0, 0.0), RIGHT, cfg(), 100, width=WIDE)
close("at 1:100 the text is cleared and the leg doubles",
      tle_core.ft_to_mm(point.X - HEAD.X), 720.0, 1e-6)

point, _ = elbow_point(HEAD, XYZ(2.0, 3.0, 0.0), RIGHT, cfg(justification="centre"),
                       50, width=WIDE)
close("a centred tag running left clears half of it",
      tle_core.ft_to_mm(point.X - HEAD.X), -360.0, 1e-6)

# ============================================================================
# settings round trip
# ============================================================================

folder = tempfile.mkdtemp(prefix="tle_bench_")
try:
    path = os.path.join(folder, "tag_leader_elbow.txt")

    check("a missing file gives the defaults", tle_core.load_settings(path),
          dict(tle_core.DEFAULTS))

    written = cfg(elbow_mm=200, base_scale=100, ambiguous="right", theme="light")
    tle_core.save_settings(written, path)
    back = tle_core.load_settings(path)
    check("the length round trips", back["elbow_mm"], "200")
    check("the quoted scale round trips", back["base_scale"], "100")
    check("the ambiguous rule round trips", back["ambiguous"], "right")
    check("justification defaults to left justified", back["justification"], "left")
    check("the head is taken to be on the top line by default",
          back["head_vertical"], "top")
    check("the tag is measured rather than its text by default",
          back["tag_extent"], "measured")
    check("the theme round trips", back["theme"], "light")

    handle = open(path, "a")
    handle.write("some_key_from_a_later_version=7\n")
    handle.close()
    back = tle_core.load_settings(path)
    check("a key the tool does not know is ignored", "some_key_from_a_later_version" in back,
          False)
    check("and the rest still loads", back["elbow_mm"], "200")

    handle = open(path, "w")
    handle.write("this file is not key equals value at all\nelbow_mm=175\n")
    handle.close()
    back = tle_core.load_settings(path)
    check("a damaged file falls back key by key", back["base_scale"], "50")
    check("and keeps the lines that did parse", back["elbow_mm"], "175")

    handle = open(path, "w")
    handle.write("ambiguous=sideways\n")
    handle.close()
    check("a value outside the choices is refused",
          tle_core.load_settings(path)["ambiguous"], "left")

    handle = open(path, "w")
    handle.write("settings_version=1\nambiguous=skip\nelbow_mm=175\n")
    handle.close()
    back = tle_core.load_settings(path)
    check("a version 1 file has its ambiguous rule reset to the new default",
          back["ambiguous"], "left")
    check("and keeps everything the migration does not name", back["elbow_mm"], "175")
finally:
    shutil.rmtree(folder, ignore_errors=True)

# ============================================================================
# report
# ============================================================================

failed = [row for row in RESULTS if not row[0]]
for ok, label, got, wanted in RESULTS:
    if not ok:
        sys.stdout.write("FAIL  {0}\n      got {1!r}, wanted {2!r}\n".format(
            label, got, wanted))
sys.stdout.write("\n{0} of {1} checks pass.\n".format(
    len(RESULTS) - len(failed), len(RESULTS)))
sys.exit(1 if failed else 0)
