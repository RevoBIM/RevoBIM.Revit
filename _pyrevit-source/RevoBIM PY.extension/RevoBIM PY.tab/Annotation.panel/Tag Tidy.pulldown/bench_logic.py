# -*- coding: utf-8 -*-
"""Bench test of the Tag Tidy logic, under plain CPython.

tidy_core carries no Revit or .NET import, so what is tested here is the real
shipped code: the layout engine (unchanged from Sam BIM Tag Stack 1.1.0, all
fifteen scenarios), the settings, following Revit's canvas theme, and the
shrink-to-taskbar drawer driven through a fake window and a fake timer.  Run
from the Tag Tidy.pulldown folder:

    python bench_logic.py
    python bench_logic.py --selftest

Every layout fixture is in paper millimetres, in the view's own frame.
--selftest breaks tidy_core on purpose, in a copy, and confirms the bench
fails for each breakage.
"""

import math
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))

# ============================================================================
# selftest: break the logic in a copy and make sure the bench notices
# ============================================================================

BREAKAGES = [
    ("a canvas read of 0 (UITheme.Dark) taken as a failed read",
     lambda t: t.replace("    if raw is None:\n        return None\n    text = str(raw)",
                         "    if not raw:\n        return None\n    text = str(raw)", 1)),
    ("Auto ignoring the canvas",
     lambda t: t.replace('    return canvas if canvas in ("dark", "light") else "dark"',
                         '    return "dark"', 1)),
    ("the parked bar ignoring the screen's own top",
     lambda t: t.replace("    top = work[1] + work[3] - bar_height - margin",
                         "    top = work[3] - bar_height - margin", 1)),
    ("a drawer tick with no fallback",
     lambda t: t.replace("        except Exception:\n            self._stop_timer()\n"
                         "            self._land()\n",
                         "        except Exception:\n            raise\n", 1)),
    ("a drawer that never stops sliding",
     lambda t: t.replace("        self.shrunk = self._target_shrunk\n        self.sliding = False\n",
                         "        self.shrunk = self._target_shrunk\n", 1)),
    ("a moved bar reopening where it used to be",
     lambda t: t.replace("        top = bar_top + bar_height - height\n",
                         "        top = saved[1]\n", 1)),
    ("groups never split when they reach too far",
     lambda t: t.replace("if pick is None and len(group) > 1 and outcome_reach(outcome) > "
                         "p.reach + 1e-6:", "if False:", 1)),
    ("a lone clear tag never kept",
     lambda t: t.replace("    if not p.keep_single or not tag.has_leader",
                         "    if True or not tag.has_leader", 1)),
]


def _selftest():
    write = sys.stdout.write
    base = subprocess.run([sys.executable, "-I", os.path.join(HERE, "bench_logic.py")],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if base.returncode != 0:
        write(base.stdout.decode("utf-8", "replace"))
        write("The bench does not pass on the shipped code, so the selftest is meaningless.\n")
        return 1
    caught = 0
    for label, break_it in BREAKAGES:
        temp = tempfile.mkdtemp(prefix="tidy_bench_self_")
        try:
            for name in ("tidy_core.py", "bench_logic.py"):
                shutil.copy(os.path.join(HERE, name), os.path.join(temp, name))
            target = os.path.join(temp, "tidy_core.py")
            handle = open(target, "r")
            text = handle.read()
            handle.close()
            broken = break_it(text)
            if broken == text:
                write("SKIP    {0}: the breakage did not change tidy_core.py\n".format(label))
                continue
            handle = open(target, "w")
            handle.write(broken)
            handle.close()
            result = subprocess.run([sys.executable, "-I", os.path.join(temp, "bench_logic.py")],
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=temp)
            if result.returncode != 0:
                caught += 1
                write("caught  {0}\n".format(label))
            else:
                write("MISSED  {0}\n".format(label))
        finally:
            shutil.rmtree(temp, ignore_errors=True)
    write("\n{0} of {1} breakages caught.\n".format(caught, len(BREAKAGES)))
    return 0 if caught == len(BREAKAGES) else 1


if __name__ == "__main__" and "--selftest" in sys.argv:
    sys.exit(_selftest())

sys.path.insert(0, HERE)

import tidy_core as core  # noqa: E402

RESULTS = []
SECTION = [""]


def section(name):
    SECTION[0] = name


def check(label, got, wanted):
    ok = got == wanted
    RESULTS.append((ok, SECTION[0], label, got, wanted))
    return ok


def close(label, got, wanted, tolerance=1e-6):
    ok = got is not None and abs(got - wanted) <= tolerance
    RESULTS.append((ok, SECTION[0], label, got, wanted))
    return ok


def truth(label, value):
    return check(label, bool(value), True)


def params(**overrides):
    values = dict(budget=30.0)
    values.update(overrides)
    return core.Params(**values)


ONE_LINE = (0.0, -1.5, 20.0, 1.5)     # head at the left middle of a 20 x 3 tag
THREE_LINE = (0.0, -7.0, 20.0, 1.5)   # head on the top line of a 20 x 8.5 tag


def tag(key, anchor, rel=ONE_LINE, head=(100.0, 100.0), own=None, anchors=None):
    return core.TagInput(key, "Tag {0}".format(key), head, rel,
                         anchors or [anchor], own=own or ["el{0}".format(key)])


def hard(result):
    return [c for c in result.clashes if c.hard]


def inner_edges(result):
    return sorted(set(round(pl.starts[0][0], 6) for pl in result.placements))


def ordered(result):
    return sorted(result.placements, key=lambda pl: -pl.box[3])


def gaps_between(result):
    rows = ordered(result)
    return [rows[i].box[1] - rows[i + 1].box[3] for i in range(len(rows) - 1)]


# ============================================================================
# geometry primitives
# ============================================================================

section("geometry")

truth("crossing segments intersect", core.segments_intersect((0, 0), (2, 2), (0, 2), (2, 0)))
check("parallel segments do not", core.segments_intersect((0, 0), (2, 0), (0, 1), (2, 1)), False)
truth("collinear overlapping segments do",
      core.segments_intersect((0, 0), (2, 0), (1, 0), (3, 0)))
check("collinear separate segments do not",
      core.segments_intersect((0, 0), (1, 0), (2, 0), (3, 0)), False)
truth("segments touching end to end do", core.segments_intersect((0, 0), (1, 0), (1, 0), (1, 1)))
truth("a T junction does", core.segments_intersect((0, 0), (2, 0), (1, 0), (1, 1)))
check("a T that stops short does not",
      core.segments_intersect((0, 0), (2, 0), (1, 0.1), (1, 1)), False)
truth("a zero-length segment on another intersects it",
      core.segments_intersect((1, 0), (1, 0), (0, 0), (2, 0)))
check("a zero-length segment off it does not",
      core.segments_intersect((1, 1), (1, 1), (0, 0), (2, 0)), False)
check("two separate zero-length segments do not",
      core.segments_intersect((0, 0), (0, 0), (1, 1), (1, 1)), False)

close("point to segment, square on", core.point_segment_distance((1, 1), (0, 0), (2, 0)), 1.0)
close("point to segment, past the end", core.point_segment_distance((3, 0), (0, 0), (2, 0)), 1.0)
close("point to a zero-length segment", core.point_segment_distance((3, 4), (0, 0), (0, 0)), 5.0)
close("parallel segments are their gap apart",
      core.segment_distance((0, 0), (2, 0), (0, 3), (2, 3)), 3.0)
close("crossing segments are 0 apart",
      core.segment_distance((0, 0), (2, 2), (0, 2), (2, 0)), 0.0)

box = (0.0, 0.0, 10.0, 10.0)
truth("a segment through a box hits it", core.segment_box_intersects((-5, 5), (15, 5), box))
truth("a segment wholly inside hits it", core.segment_box_intersects((2, 2), (3, 3), box))
truth("a segment touching an edge hits it", core.segment_box_intersects((-5, 10), (15, 10), box))
check("a segment beside it misses", core.segment_box_intersects((-5, 11), (15, 11), box), False)
check("a diagonal past the corner misses",
      core.segment_box_intersects((9, 12), (12, 9), box), False)
truth("a zero-length segment inside hits it", core.segment_box_intersects((5, 5), (5, 5), box))
check("a zero-length segment outside misses",
      core.segment_box_intersects((15, 5), (15, 5), box), False)
close("segment to box distance", core.segment_box_distance((12, 0), (12, 10), box), 2.0)
close("diagonal to corner distance",
      core.segment_box_distance((11, 12), (12, 11), box), math.sqrt(0.5 ** 2 * 2) + math.sqrt(2.0),
      1e-6)

truth("overlapping boxes overlap", core.box_overlap((0, 0, 2, 2), (1, 1, 3, 3)))
check("boxes that only touch do not", core.box_overlap((0, 0, 2, 2), (2, 0, 4, 2)), False)
check("separate boxes do not", core.box_overlap((0, 0, 1, 1), (2, 2, 3, 3)), False)
truth("a box inside another is inside", core.box_inside((1, 1, 2, 2), (0, 0, 3, 3)))
check("one poking out is not", core.box_inside((1, 1, 4, 2), (0, 0, 3, 3)), False)

check("trimming more than a segment leaves nothing", core.trim_end((0, 0), (1, 0), 2.0), None)
close("trimming takes it off the far end", core.trim_end((0, 0), (10, 0), 2.0)[1][0], 8.0)

pipe = core.Obstacle("seg", ((0, 0), (10, 0)), False, "pipe", radius=1.0)
truth("a thick segment touches a box within its radius", pipe.touches_box((4, 0.5, 6, 3)))
check("and not one beyond it", pipe.touches_box((4, 1.5, 6, 3)), False)
truth("a thick segment touches a leader within its radius", pipe.touches_segment((5, 0.9), (5, 5)))
disc = core.Obstacle("seg", ((5, 5), (5, 5)), False, "riser", radius=2.0)
truth("a pipe seen end on is a disc", disc.touches_segment((0, 6), (10, 6)))
check("and is missed outside its radius", disc.touches_segment((0, 8), (10, 8)), False)

grid = core.Grid(10.0)
items = [core.Obstacle("box", (i * 30.0, 0, i * 30.0 + 5, 5), True, "b{0}".format(i))
         for i in range(10)]
for item in items:
    grid.add(item)
found = grid.query((58.0, 0.0, 66.0, 4.0))
check("the grid finds only what is near", [o.label for o in found], ["b2"])
huge = core.Obstacle("box", (-1e6, -1e6, 1e6, 1e6), True, "huge")
grid.add(huge)
truth("and an enormous item is always found", "huge" in [o.label for o in grid.query((0, 0, 1, 1))])

# ============================================================================
# the frame
# ============================================================================

section("frame")

frame = core.Frame((10.0, 20.0, 3.0), (1, 0, 0), (0, 1, 0), 50)
u, v = frame.to_paper((10.0 + 1.0, 20.0, 3.0))
close("one foot at 1:50 is 6.096mm on paper", u, 304.8 / 50.0)
back = frame.to_model(u, v, frame.depth_of((11.0, 20.0, 3.0)))
close("and converts back", back[0], 11.0)
close("keeping its depth", back[2], 3.0)

# ============================================================================
# scenario 1: six parallel pipes
# ============================================================================

section("1 six parallel pipes")

PIPES_V = [30.0, 24.0, 18.0, 12.0, 6.0, 0.0]
# targets within the 30mm reach of each other, so they share one column; a
# spread wider than that is scenario 15's business
PIPE_ANCHOR_U = [-14.0, -4.0, -11.0, 0.0, -7.0, -2.0]
pipes_obs = [core.Obstacle("seg", ((-60.0, v), (5.0, v)), False, "Pipe {0}".format(i),
                           key="el{0}".format(i), radius=0.6, group="model")
             for i, v in enumerate(PIPES_V)]
pipe_tags = [tag(i, (PIPE_ANCHOR_U[i], PIPES_V[i]), head=(40.0 - 9 * i, 70.0 + 13 * i))
             for i in range(6)]
r1 = core.solve(pipe_tags, pipes_obs, None, params())
check("all six are placed", len(r1.placements), 6)
check("in one column", len(inner_edges(r1)), 1)
check("that column is to the right, clear of the pipes",
      all(pl.side == 1 for pl in r1.placements), True)
check("no hard clashes", len(hard(r1)), 0)
gaps = gaps_between(r1)
truth("gaps between tags are all the same", max(gaps) - min(gaps) < 1e-6)
close("and equal to the setting", gaps[0], 2.0)
order = [pl.key for pl in ordered(r1)]
check("the order down the column matches the pipes", order, [0, 1, 2, 3, 4, 5])

# ============================================================================
# scenario 2: five risers side by side
# ============================================================================

section("2 five risers")

RISER_U = [0.0, 8.0, 16.0, 24.0, 32.0]
riser_obs = [core.Obstacle("seg", ((u, 0.0), (u, 0.0)), False, "Riser {0}".format(i),
                           key="el{0}".format(i), radius=1.5, group="model")
             for i, u in enumerate(RISER_U)]
riser_tags = [tag(i, (RISER_U[i], 0.0)) for i in range(5)]
r2 = core.solve(riser_tags, riser_obs, None, params(side="right"))
check("one column", len(inner_edges(r2)), 1)
leader_clashes = [c for c in r2.clashes if c.part == "leader"]
check("zero leader clashes: the legs nest", len(leader_clashes), 0)
check("zero hard clashes", len(hard(r2)), 0)
nearest = r2.by_key()[4]
close("the riser nearest the column gets a dead straight leader, level with it",
      nearest.starts[0][1], 0.0, 1e-9)
far = r2.by_key()[0]
truth("the farthest riser's tag sits furthest from the row",
      abs(far.starts[0][1]) == max(abs(pl.starts[0][1]) for pl in r2.placements))

# ============================================================================
# scenario 3: a leg crosses a duct
# ============================================================================

section("3 a leg crosses a duct")

stack_tags = [tag(i, (0.0, -3.0 * i), rel=THREE_LINE) for i in range(3)]
base3 = core.solve(stack_tags, [], None, params(side="right"))
leg = [s for s in base3.by_key()[0].segments() if s[2] == "leg"][0]
mid = ((leg[0][0] + leg[1][0]) / 2.0, (leg[0][1] + leg[1][1]) / 2.0)
duct = core.Obstacle("seg", ((mid[0] - 2.0, mid[1] + 2.0), (mid[0] + 2.0, mid[1] - 2.0)), False,
                     "Duct 900", key="duct", radius=0.8, group="model")
base_clashes = core.find_clashes(base3.placements, core.Context([duct], None, params()))
check("in the plain layout the top leg crosses the duct",
      [c.label for c in base_clashes], ["Duct 900"])
r3 = core.solve(stack_tags, [duct], None, params(side="right"))
check("after repair there are zero clashes", len(r3.clashes), 0)
check("still one column", len(inner_edges(r3)), 1)
truth("the top tag moved to get clear",
      core.dist(r3.by_key()[0].head, base3.by_key()[0].head) > 1.0)

# ============================================================================
# scenario 4: the column lands on a text note
# ============================================================================

section("4 a text note in the way")

base4 = core.solve(pipe_tags, pipes_obs, None, params(side="right"))
column_box = core.box_of_points([(pl.box[0], pl.box[1]) for pl in base4.placements] +
                                [(pl.box[2], pl.box[3]) for pl in base4.placements])
half = (column_box[1] + column_box[3]) / 2.0
note = core.Obstacle("box", (column_box[0] + 1.0, half, column_box[2] + 5.0,
                             column_box[3]), True, "Text Note 77", key="note")
before = core.find_clashes(base4.placements, core.Context(pipes_obs + [note], None, params()))
truth("in the plain layout the top half of the column sits on the note",
      len([c for c in before if c.label == "Text Note 77" and c.part == "tag"]) >= 3)
r4 = core.solve(pipe_tags, pipes_obs + [note], None, params(side="right"))
check("no hard clashes once it has moved", len(hard(r4)), 0)
truth("the column moved clear of the note",
      all(not core.box_overlap(pl.box, note.geom) for pl in r4.placements))
check("and is still one column", len(inner_edges(r4)), 1)

# a note that fills the whole corridor beside the pipes: no 45 degree leader
# can reach that side at all, so on auto the column has to change side
wall_note = core.Obstacle("box", (column_box[0] + 1.0, column_box[1], column_box[2] + 5.0,
                                  column_box[3]), True, "Text Note 78", key="note2")
r4b = core.solve(pipe_tags, pipes_obs + [wall_note], None, params())
check("a note filling the corridor sends the column to the other side",
      sorted(set(pl.side for pl in r4b.placements)), [-1])
check("with no hard clashes there", len(hard(r4b)), 0)
r4c = core.solve(pipe_tags, pipes_obs + [wall_note], None, params(side="right"))
truth("forced to the blocked side, it keeps a best layout and names the note",
      any(c.label == "Text Note 78" for c in hard(r4c)))

# ============================================================================
# scenario 5: boxed in
# ============================================================================

section("5 boxed in")

wall = core.Obstacle("box", (-500.0, -500.0, 500.0, 500.0), True, "Text Note 1", key="big")
try:
    r5 = core.solve(pipe_tags, [wall], None, params(budget=1.0))
    raised = None
except Exception as error:  # noqa: BLE001
    r5 = None
    raised = error
check("no exception", raised, None)
check("every tag still gets a best position", len(r5.placements) if r5 else 0, 6)
truth("and the clash is reported, by name", r5 and any(c.label == "Text Note 1" for c in r5.clashes))
check("still one tidy column", len(inner_edges(r5)) if r5 else 0, 1)

ticks = [0.0]


def frozen_clock():
    ticks[0] += 10.0
    return ticks[0]


r5b = core.solve(pipe_tags, pipes_obs, None, params(budget=1.0), clock=frozen_clock)
check("a time budget that has already run out still gives a full layout",
      len(r5b.placements), 6)
check("and says it ran out", r5b.ran_out, True)

# ============================================================================
# scenario 6: mixed heights
# ============================================================================

section("6 mixed heights")

mixed = [tag(i, (0.0, -4.0 * i), rel=(THREE_LINE if i % 2 else ONE_LINE)) for i in range(6)]
r6 = core.solve(mixed, [], None, params())
gaps = gaps_between(r6)
truth("every gap is the same whatever the tag height", max(gaps) - min(gaps) < 1e-6)
close("and is the 2mm setting", gaps[0], 2.0)
heights = [round(pl.box[3] - pl.box[1], 6) for pl in ordered(r6)]
check("tags of both heights are in it", sorted(set(heights)), [3.0, 8.5])

# ============================================================================
# scenario 7: two views
# ============================================================================

section("7 two views")

view_a = [tag("a{0}".format(i), (0.0, -6.0 * i)) for i in range(3)]
view_b = [tag("b{0}".format(i), (500.0, 200.0 - 6.0 * i)) for i in range(4)]
alone = core.solve(view_a, [], None, params())
core.solve(view_b, [note], None, params())
again = core.solve(view_a, [], None, params())
check("each view's layout depends only on its own tags and obstacles",
      [pl.head for pl in alone.placements], [pl.head for pl in again.placements])
check("view A is one column", len(inner_edges(alone)), 1)
check("view B is laid out on its own, one column",
      len(inner_edges(core.solve(view_b, [], None, params()))), 1)

# ============================================================================
# scenario 8: a rotated view
# ============================================================================

section("8 view rotated 30 degrees")

angle = math.radians(30.0)
right = (math.cos(angle), math.sin(angle), 0.0)
up = (-math.sin(angle), math.cos(angle), 0.0)
rotated = core.Frame((5.0, -2.0, 0.0), right, up, 50)
square = core.Frame((0.0, 0.0, 0.0), (1, 0, 0), (0, 1, 0), 50)


def model_of(frame, uv):
    return frame.to_model(uv[0], uv[1], 0.0)


def via(frame):
    tags_in = []
    for t in pipe_tags:
        anchor = frame.to_paper(model_of(frame, t.anchors[0]))
        head = frame.to_paper(model_of(frame, t.head))
        tags_in.append(core.TagInput(t.key, t.label, head, t.rel, [anchor], own=t.own))
    obs = []
    for ob in pipes_obs:
        p0 = frame.to_paper(model_of(frame, ob.geom[0]))
        p1 = frame.to_paper(model_of(frame, ob.geom[1]))
        obs.append(core.Obstacle("seg", (p0, p1), False, ob.label, key=ob.key, radius=ob.radius,
                                 group="model"))
    return core.solve(tags_in, obs, None, params())


ra = via(rotated)
rb = via(square)
diff = max(core.dist(a.head, b.head) for a, b in zip(ordered(ra), ordered(rb)))
close("identical layout in view coordinates", diff, 0.0, 1e-6)
moved_model = rotated.to_model(ordered(ra)[0].head[0], ordered(ra)[0].head[1], 0.0)
truth("and it lands rotated in the model", abs(moved_model[1] - model_of(square, ordered(rb)[0].head)[1]) > 1e-3)

# ============================================================================
# scenario 9: tags it cannot or should not move
# ============================================================================

section("9 pinned, borrowed, grouped")

cfg = dict(core.DEFAULTS)
verdict = core.eligibility({"pinned": True, "has_leader": True}, cfg)
check("a pinned tag is unpinned and re-pinned by default", (verdict["ok"], verdict["unpin"]),
      (True, True))
verdict = core.eligibility({"pinned": True}, dict(cfg, pinned="skip"))
check("or skipped when set to", verdict["ok"], False)
truth("with a reason", "pinned" in verdict["reason"])
verdict = core.eligibility({"owned_by_other": True}, cfg)
check("a borrowed tag is skipped", verdict["ok"], False)
truth("and it says who to ask", "relinquish" in verdict["reason"])
verdict = core.eligibility({"in_group": True}, cfg)
check("a grouped tag is skipped", verdict["ok"], False)
truth("and it says why", "group" in verdict["reason"])
verdict = core.eligibility({"updated_in_central": True}, cfg)
check("a tag changed in central is skipped", verdict["ok"], False)
verdict = core.eligibility({"view_ok": False}, cfg)
check("a tag in a 3D or drafting view is refused", verdict["ok"], False)
verdict = core.eligibility({"spatial": True}, cfg)
check("room tags are off by default", verdict["ok"], False)
verdict = core.eligibility({"spatial": True}, dict(cfg, include_spatial_tags="1"))
check("and on when asked", verdict["ok"], True)

# ============================================================================
# scenario 10: a two-leader tag
# ============================================================================

section("10 a two-leader tag")

twin = tag("twin", None, anchors=[(0.0, 0.0), (0.0, -20.0)])
others = [tag(i, (6.0, -4.0 * i - 4.0)) for i in range(2)]
r10 = core.solve([twin] + others, [], None, params(side="right"))
twin_pl = r10.by_key()["twin"]
check("it gets a leg for each target", len([s for s in twin_pl.segments() if s[2] == "leg"]), 2)
close("it is ordered by the centre of its targets", twin.centre[1], -10.0)
second_leg = [s for s in twin_pl.segments() if s[2] == "leg" and s[3] == 1][0]
m = ((second_leg[0][0] + second_leg[1][0]) / 2.0, (second_leg[0][1] + second_leg[1][1]) / 2.0)
blocker = core.Obstacle("box", (m[0] - 0.5, m[1] - 0.5, m[0] + 0.5, m[1] + 0.5), True,
                        "Text Note 5", key="t5")
found = core.find_clashes(r10.placements, core.Context([blocker], None, params()))
truth("a clash on its second leg alone is caught",
      any(c.key == "twin" and c.label == "Text Note 5" for c in found))

# ============================================================================
# scenario 11: a tag with no leader
# ============================================================================

section("11 a tag with no leader")

verdict = core.eligibility({"has_leader": False}, cfg)
check("the leader is switched on by default", (verdict["ok"], verdict["switch_on"]), (True, True))
verdict = core.eligibility({"has_leader": False}, dict(cfg, no_leader="skip"))
check("or the tag is skipped when set to", verdict["ok"], False)

# ============================================================================
# scenario 12: a column longer than the crop
# ============================================================================

section("12 longer than the crop")

tall = [tag(i, (0.0, -2.0 * i), rel=THREE_LINE) for i in range(8)]
crop = (-70.0, -40.0, 70.0, 30.0)
r12 = core.solve(tall, [], crop, params())
check("it splits into two columns", r12.columns, 2)
check("and nothing is left outside the crop",
      [c for c in r12.clashes if c.label == core.CROP_LABEL], [])
check("one column each side", sorted(set(pl.side for pl in r12.placements)), [-1, 1])
r12b = core.solve(tall, [], crop, params(second_column=False))
check("with second columns off it stays one column", r12b.columns, 1)
truth("and reports the crop", any(c.label == core.CROP_LABEL for c in r12b.clashes))

# ============================================================================
# scenario 13: run twice
# ============================================================================

section("13 run twice")

second = [core.TagInput(pl.key, pl.tag.label, pl.head, pl.tag.rel, pl.tag.anchors, pl.tag.own)
          for pl in r1.placements]
r13 = core.solve(second, pipes_obs, None, params())
moved = max(pl.moved() for pl in r13.placements)
close("nothing moves the second time", moved, 0.0, 1e-9)
r13b = core.solve(pipe_tags, pipes_obs, None, params())
check("and the same input always gives the same answer",
      [pl.head for pl in r13b.placements], [pl.head for pl in r1.placements])

# ============================================================================
# scenario 14: the 45 degree leg
# ============================================================================

section("14 a fixed 45 degree leg")

worst = 0.0
shortest = 1e9
for result in (r1, r2, r3, r6):
    for pl in result.placements:
        for index, anchor in enumerate(pl.anchors):
            elbow = pl.elbows[index]
            start = pl.starts[index]
            drop = abs(elbow[1] - anchor[1])
            if drop > 0.5:
                worst = max(worst, abs(abs(elbow[0] - anchor[0]) - drop))
            shortest = min(shortest, abs(start[0] - elbow[0]))
close("every elbow lands exactly where 45 degrees puts it", worst, 0.0, 1e-9)
truth("no shoulder is shorter than the 3mm minimum", shortest >= 3.0 - 1e-9)

p60 = params(angle="60")
r60 = core.solve(pipe_tags, pipes_obs, None, p60)
worst = 0.0
for pl in r60.placements:
    for index, anchor in enumerate(pl.anchors):
        elbow = pl.elbows[index]
        drop = abs(elbow[1] - anchor[1])
        if drop > 0.5:
            worst = max(worst, abs(drop / abs(elbow[0] - anchor[0]) - math.tan(math.radians(60))))
close("a 60 degree setting gives 60 degree legs", worst, 0.0, 1e-9)

r90 = core.solve(pipe_tags, pipes_obs, None, params(angle="90"))
truth("a 90 degree setting gives vertical legs",
      all(abs(pl.elbows[0][0] - pl.anchors[0][0]) < 1e-9 for pl in r90.placements
          if abs(pl.elbows[0][1] - pl.anchors[0][1]) > 0.5))

rflat = core.solve([tag("flat", (0.0, 0.0))], [], None, params(side="right"))
pl = rflat.placements[0]
close("a single tag level with its target gets a straight leader", pl.elbows[0][1], 0.0, 1e-9)

# ============================================================================
# scenario 15: targets too far apart across the view to share a column
# ============================================================================

section("15 too far apart to line up")

# Two small openings one above the other on the left, a large opening about
# 48mm to the right whose tag already sits just beside it.  All three tags
# start lined up far to the right, so the two left leaders are long.
TWO_LINE = (0.0, -4.5, 25.0, 1.5)
small_top = core.TagInput("top", "125x125 top", (55.0, -6.0), TWO_LINE, [(0.0, 0.0)],
                          own=["o1"], current_elbows=[(8.0, -7.5)])
small_low = core.TagInput("low", "125x125 low", (55.0, -20.0), TWO_LINE, [(0.0, -28.0)],
                          own=["o2"], current_elbows=[(8.0, -21.5)])
large = core.TagInput("large", "1195x499", (55.0, -32.0), TWO_LINE, [(48.0, -29.0)],
                      own=["o3"], current_elbows=[None])
openings = [core.Obstacle("box", (-1.0, -1.0, 1.0, 1.0), False, "Opening 1", key="o1",
                          group="model"),
            core.Obstacle("box", (-1.0, -29.0, 1.0, -27.0), False, "Opening 2", key="o2",
                          group="model"),
            core.Obstacle("box", (28.0, -31.0, 48.0, -27.0), False, "Opening 3", key="o3",
                          group="model")]
r15 = core.solve([small_top, small_low, large], openings, None, params())
placed = r15.by_key()
check("the two small openings' tags share one alignment line",
      round(placed["top"].starts[0][0], 6) == round(placed["low"].starts[0][0], 6), True)
truth("right beside their openings, within the 30mm reach",
      max(placed["top"].reach(), placed["low"].reach()) <= 30.0)
truth("so their leaders are short now",
      max(placed["top"].leader_length(), placed["low"].leader_length()) < 30.0)
check("the large opening's tag is left exactly where it was", placed["large"].kept, True)
close("and has not moved at all", placed["large"].moved(), 0.0, 1e-12)
check("no hard clashes", len(hard(r15)), 0)
check("one column was made, and one tag kept", (r15.columns, r15.kept), (1, 1))

r15b = core.solve([small_top, small_low, large], openings, None, params(keep_single=False))
truth("with keeping switched off the lone tag is tidied on its own instead",
      not r15b.by_key()["large"].kept and r15b.by_key()["large"].moved() > 0.0)

r15c = core.solve([small_top, small_low, large], openings, None, params(reach=1000.0))
truth("with an unlimited reach all three line up again, as before",
      len(set(round(pl.starts[0][0], 6) for pl in r15c.placements)) == 1)

far_tag = core.TagInput("far", "far", (300.0, 300.0), TWO_LINE, [(0.0, 0.0)],
                        own=["f"], current_elbows=[(200.0, 300.0)])
r15d = core.solve([far_tag], [], None, params())
truth("a lone tag far from its target is not kept, it is brought in",
      not r15d.placements[0].kept and r15d.placements[0].reach() <= 30.0)

no_leader = core.TagInput("bare", "bare", (5.0, 0.0), TWO_LINE, [(0.0, 0.0)],
                          own=["b"], current_elbows=None, has_leader=False)
check("a lone tag with no leader yet is laid out, not kept",
      core.solve([no_leader], [], None, params()).placements[0].kept, False)

# targets each close to the next but spread wide overall: chained together
# they would make one long column, so it has to split again after solving
chain = [tag("c{0}".format(i), (18.0 * i, -4.0 * i)) for i in range(6)]
r15e = core.solve(chain, [], None, params())
truth("a wide chain of targets splits until every tag is within reach",
      max(pl.reach() for pl in r15e.placements) <= 30.0)
truth("into more than one alignment line", r15e.columns >= 2)
check("still with no hard clashes", len(hard(r15e)), 0)

# ============================================================================
# settings
# ============================================================================

section("settings")

folder = tempfile.mkdtemp(prefix="stack_bench_")
try:
    path = os.path.join(folder, "tag_tidy.txt")
    check("a missing file gives the defaults", core.load_settings(path), dict(core.DEFAULTS))
    written = dict(core.DEFAULTS, gap_mm="3", leg_angle="60", side="left", theme="light")
    core.save_settings(written, path)
    back = core.load_settings(path)
    check("values round trip", (back["gap_mm"], back["leg_angle"], back["side"], back["theme"]),
          ("3", "60", "left", "light"))
    handle = open(path, "w")
    handle.write("leg_angle=72\ngap_mm=-4\nside=up\nmax_shift_mm=25\nmystery=1\n")
    handle.close()
    back = core.load_settings(path)
    check("a choice outside the list is refused", back["leg_angle"], "45")
    check("a number outside its range is refused", back["gap_mm"], "2")
    check("a side outside the list is refused", back["side"], "auto")
    check("good lines next to bad ones still load", back["max_shift_mm"], "25")
    check("unknown keys are ignored", "mystery" in back, False)
    p = core.Params.from_cfg(back)
    close("params read the numbers", p.max_shift, 25.0)
    check("the theme defaults to following Revit", core.DEFAULTS["theme"], "follow")
    handle = open(path, "w")
    handle.write("theme=purple\ndebug=1\n")
    handle.close()
    check("a theme outside the list falls back to follow", core.load_settings(path)["theme"],
          "follow")
    check("the debug report is on by default", core.as_bool(core.DEFAULTS, "debug"), True)
    report = os.path.join(folder, "tag_tidy_debug.txt")
    core.write_debug(dict(core.DEFAULTS), ["line one", "line two"], report)
    handle = open(report, "r")
    body = handle.read()
    handle.close()
    truth("the debug report names the version and keeps every line",
          ("v" + core.__version__) in body and "line two" in body)
    os.remove(report)
    check("and writes nothing when switched off",
          (core.write_debug(dict(core.DEFAULTS, debug="0"), ["x"], report),
           os.path.exists(report)), (None, False))
finally:
    shutil.rmtree(folder, ignore_errors=True)

# ============================================================================
# theme: following Revit's canvas
# ============================================================================

section("theme")

check("UITheme.Dark is 0, and 0 reads as dark, not as a failed read",
      core.canvas_name(0), "dark")
check("1 reads as light", core.canvas_name(1), "light")
check("the enum's own name reads", (core.canvas_name("Dark"), core.canvas_name("UITheme.Light")),
      ("dark", "light"))
check("nothing read is unknown", core.canvas_name(None), None)
check("a value it does not know is unknown", core.canvas_name(7), None)
check("Auto paints the canvas", (core.resolve_theme("follow", "light"),
                                 core.resolve_theme("follow", "dark")), ("light", "dark"))
check("Auto with no canvas to read (before Revit 2024) is dark",
      core.resolve_theme("follow", None), "dark")
check("a fixed choice beats the canvas", (core.resolve_theme("dark", "light"),
                                          core.resolve_theme("light", "dark")), ("dark", "light"))
check("the chip goes Auto, Dark, Light, Auto",
      [core.next_theme(s) for s in ("follow", "dark", "light")], ["dark", "light", "follow"])
check("and its labels", [core.THEME_LABELS[s] for s in core.THEME_CYCLE], ["Auto", "Dark", "Light"])

# ============================================================================
# the drawer: parking arithmetic
# ============================================================================

section("drawer arithmetic")

PRIMARY = (0.0, 0.0, 1920.0, 1040.0)
ABOVE = (0.0, -1080.0, 1920.0, 1040.0)     # a second monitor above the primary
top, height = core.park_bounds(PRIMARY, 50.0)
check("the bar parks just above the taskbar", (top, height), (1040.0 - 50.0 - 8.0, 50.0))
top, _ = core.park_bounds(ABOVE, 50.0)
truth("on a monitor above the primary it parks on that monitor, not the primary",
      ABOVE[1] <= top <= ABOVE[1] + ABOVE[3] - 50.0)
close("at the bottom of that monitor", top, -1080.0 + 1040.0 - 58.0)
check("a bar taller than the screen still starts on it", core.park_bounds((0, 100, 800, 30), 50.0)[0],
      100)

saved = (200.0, 120.0, 860.0, 580.0)
parked = core.park_bounds(PRIMARY, 50.0)[0]
check("an unmoved bar reopens exactly where the window was",
      core.reopen_bounds(saved, parked, 50.0, PRIMARY, parked), (120.0, 580.0))
check("a bar carried up the screen opens upward from where it sits",
      core.reopen_bounds(saved, 700.0, 50.0, PRIMARY, parked), (700.0 + 50.0 - 580.0, 580.0))
check("but never above the top of the screen",
      core.reopen_bounds(saved, 100.0, 50.0, PRIMARY, parked), (0.0, 580.0))
check("on the monitor above, never above its top either",
      core.reopen_bounds(saved, -1050.0, 50.0, ABOVE, -98.0), (-1080.0, 580.0))
check("a window taller than the screen opens at the screen's height",
      core.reopen_bounds((0, 0, 800, 2000.0), parked, 50.0, PRIMARY, parked), (0.0, 1040.0))
check("easing starts and lands exactly", (core.ease(0.0), core.ease(1.0), core.ease(0.5)),
      (0.0, 1.0, 0.5))
check("the last frame of a slide is its target",
      core.slide_frame((120.0, 580.0), (982.0, 50.0), core.DRAWER_STEPS), (982.0, 50.0))

# ============================================================================
# the drawer, driven through a fake window and a fake timer
# ============================================================================
#
# The fake timer never runs a tick from inside start(), as a real
# DispatcherTimer never does.  An exception that escapes a tick is caught the
# way the dispatcher would catch it and recorded, and the bench fails on any.

section("drawer")


class FakeTimer(object):

    def __init__(self, world, tick):
        self.world = world
        self.tick = tick
        self.running = False

    def start(self):
        if self.world.timers_fail:
            raise RuntimeError("no timer on this machine")
        self.running = True
        self.world.timers.append(self)

    def stop(self):
        self.running = False


class FakeHost(object):

    def __init__(self, work=PRIMARY, bounds=(200.0, 120.0, 860.0, 580.0), bar=50.0):
        self.left, self.top, self.width, self.height = bounds
        self.work = work
        self.bar = bar
        self.timers = []
        self.escaped = []
        self.timers_fail = False
        self.raise_on_frame = None
        self.frames = 0
        self.calls = []

    def bounds(self):
        return (self.left, self.top, self.width, self.height)

    def set_bounds(self, top, height):
        self.frames += 1
        if self.raise_on_frame is not None and self.frames == self.raise_on_frame:
            self.raise_on_frame = None
            raise RuntimeError("a frame went wrong")
        self.top, self.height = top, height

    def work_area(self):
        return self.work

    def bar_height(self):
        return self.bar

    def before_slide(self, shrinking):
        self.calls.append(("before", shrinking))

    def after_slide(self, shrunk):
        self.calls.append(("after", shrunk))

    def make_timer(self, interval_ms, tick):
        return FakeTimer(self, tick)

    def run_timers(self, limit=500):
        """The dispatcher: tick every running timer until none is left."""
        for _ in range(limit):
            live = [timer for timer in self.timers if timer.running]
            if not live:
                return
            for timer in live:
                try:
                    timer.tick()
                except Exception as error:  # noqa: BLE001
                    self.escaped.append(error)
                    timer.running = False


host = FakeHost()
drawer = core.DrawerCore(host)
drawer.toggle()
check("pressing shrink starts a slide", drawer.sliding, True)
check("nothing has moved inside start()", (host.top, host.height), (120.0, 580.0))
check("a second press mid-slide is ignored", drawer.toggle(), False)
host.run_timers()
check("no exception escaped a tick", host.escaped, [])
check("it lands parked", (drawer.shrunk, drawer.sliding), (True, False))
check("as a bar just above the taskbar", (host.top, host.height), (982.0, 50.0))
truth("over several frames, like a drawer", host.frames >= core.DRAWER_STEPS)
check("the window is told before and after", host.calls, [("before", True), ("after", True)])
drawer.toggle()
host.run_timers()
check("pressing the green arrow opens it where it was",
      (drawer.shrunk, drawer.sliding, host.top, host.height), (False, False, 120.0, 580.0))
check("and the window is told it is open", host.calls[-1], ("after", False))

host = FakeHost()
drawer = core.DrawerCore(host)
drawer.shrink()
host.run_timers()
host.top = 600.0            # the parked bar dragged up the screen
drawer.expand()
host.run_timers()
check("a bar dragged elsewhere opens upward from where it now sits",
      (host.top, host.height), (600.0 + 50.0 - 580.0, 580.0))

host = FakeHost()
host.raise_on_frame = 4
drawer = core.DrawerCore(host)
drawer.shrink()
host.run_timers()
check("a frame that raises does not escape the tick", host.escaped, [])
check("and the window still lands parked, free to open again",
      (drawer.shrunk, drawer.sliding, host.top, host.height), (True, False, 982.0, 50.0))
drawer.toggle()
host.run_timers()
check("which it does", (drawer.shrunk, host.top, host.height), (False, 120.0, 580.0))

host = FakeHost()
host.timers_fail = True
drawer = core.DrawerCore(host)
drawer.shrink()
check("with no timer it lands at once rather than not at all",
      (drawer.shrunk, drawer.sliding, host.top, host.height), (True, False, 982.0, 50.0))

host = FakeHost(work=ABOVE, bounds=(200.0, -900.0, 860.0, 580.0))
drawer = core.DrawerCore(host)
drawer.shrink()
host.run_timers()
truth("on the monitor above the primary it parks on that monitor",
      ABOVE[1] <= host.top <= ABOVE[1] + ABOVE[3] - 50.0)
drawer.expand()
host.run_timers()
check("and opens back where it was there", (host.top, host.height), (-900.0, 580.0))

# ============================================================================
# report
# ============================================================================

failed = [row for row in RESULTS if not row[0]]
current = None
for ok, where, label, got, wanted in RESULTS:
    if where != current:
        current = where
        sys.stdout.write("\n{0}\n".format(where))
    sys.stdout.write("  {0}  {1}\n".format("ok  " if ok else "FAIL", label))
    if not ok:
        sys.stdout.write("        got {0!r}\n        wanted {1!r}\n".format(got, wanted))
sys.stdout.write("\n{0} of {1} checks pass.\n".format(len(RESULTS) - len(failed), len(RESULTS)))
sys.exit(1 if failed else 0)
