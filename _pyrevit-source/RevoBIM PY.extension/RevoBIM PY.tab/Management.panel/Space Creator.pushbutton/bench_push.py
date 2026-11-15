# -*- coding: utf-8 -*-
"""bench_push.py - tests compute_push_target under plain CPython.

What it has to get right:
  - a space reaches the underside of the nearest floor above
  - it stops at the base of a space stacked above it, never running into it
  - the floor the space stands on is not mistaken for the one above
  - a space with no floor above is flagged, not guessed
  - a space already at the target is reported as no-op, not re-pushed

Run: python bench_push.py
"""
import io
import os
import sys


class XYZ(object):
    def __init__(self, x, y, z):
        self.X, self.Y, self.Z = float(x), float(y), float(z)


class BBox(object):
    def __init__(self, x0, y0, z0, x1, y1, z1):
        self.Min = XYZ(x0, y0, z0)
        self.Max = XYZ(x1, y1, z1)


def load_core():
    here = os.path.dirname(os.path.abspath(__file__))
    src = io.open(os.path.join(here, "../../../lib/revobim/space_creator_core.py"),
                  encoding="utf-8").read()
    start = src.index("MM_PER_FOOT = 304.8")
    end = src.index("def apply_space_edit")
    ns = {"XYZ": XYZ, "Floor": None, "FilteredElementCollector": None,
          "BuiltInParameter": None, "eid_value": lambda e: e,
          "get_room_number": lambda s: "", "get_element_name": lambda s: "",
          "level_elevation": lambda l: None, "_natural_key": lambda t: t}
    exec(compile(src[start:end], "core_snippet", "exec"), ns)
    return ns


ns = load_core()
compute = ns["compute_push_target"]
mm = ns["mm"]
failures = []


def check(name, condition, detail=""):
    print(("PASS  " if condition else "FAIL  ") + name +
          ("" if condition else "  " + detail))
    if not condition:
        failures.append(name)


def row(id_value, x, y, level_elev, base_mm=0, limit_mm=2500, upper_elev=None):
    return {"id_value": id_value, "point": XYZ(x, y, level_elev),
            "bbox": BBox(x - 5, y - 5, level_elev, x + 5, y + 5, level_elev + 8),
            "level_elev": level_elev, "base_offset": base_mm,
            "limit_offset": limit_mm, "upper_level_elev": upper_elev}


# Building: ground 0ft, first floor slab underside at 11ft (slab 11..12),
# second at 23ft. Space A on ground, space B on first floor at 12ft.
floors = [BBox(-50, -50, 11.0, 50, 50, 12.0),      # first floor slab
          BBox(-50, -50, 23.0, 50, 50, 24.0),      # second floor slab
          BBox(-50, -50, -1.0, 50, 50, 0.0)]       # ground slab (below)

ground = row("A", 0, 0, 0.0, limit_mm=2500)        # top currently 2.5m
first = row("B", 0, 0, 12.0, limit_mm=2500)

# 1 - ground space reaches the first floor slab underside (11ft)
new_limit, target, reason = compute(ground, floors, [ground, first])
check("pushes to the underside of the floor above",
      reason is None and abs(target - 11.0) < 1e-6,
      "target=" + str(target) + " reason=" + str(reason))
check("expresses it as a limit offset from its own level",
      new_limit == mm(11.0), str(new_limit))

# 2 - the ground slab (below) is not mistaken for the floor above
check("ignores the slab it stands on", target > 0.0)

# 3 - a space directly above stops the push at its base
low_first = row("C", 0, 0, 9.0, limit_mm=2500)     # a space starting at 9ft
new_limit, target, reason = compute(ground, floors, [ground, low_first])
check("stops at the base of a space stacked above",
      reason is None and abs(target - 9.0) < 1e-6,
      "target=" + str(target) + " reason=" + str(reason))

# 4 - a space above that is not over this point does not interfere
elsewhere = row("D", 100, 100, 9.0)
new_limit, target, reason = compute(ground, floors, [ground, elsewhere])
check("a space above but elsewhere in plan is ignored",
      abs(target - 11.0) < 1e-6, "target=" + str(target))

# 5 - no floor above at all is flagged
roof_space = row("E", 0, 0, 24.0)
new_limit, target, reason = compute(roof_space, floors, [roof_space])
check("no floor above is flagged, not guessed",
      reason == "no floor found above", str(reason))

# 6 - already at the target is a no-op
at_target = row("F", 0, 0, 0.0, limit_mm=mm(11.0))
new_limit, target, reason = compute(at_target, floors, [at_target])
check("a space already at the floor is reported as already there",
      reason == "already at that height", str(reason))

# 7 - a base offset raises the base; the floor it must clear is judged
#     from the raised base
raised = row("G", 0, 0, 0.0, base_mm=mm(11.5), limit_mm=mm(12.0))
new_limit, target, reason = compute(raised, floors, [raised])
check("a raised base skips the slab it now sits inside",
      reason is None and abs(target - 23.0) < 1e-6,
      "target=" + str(target) + " reason=" + str(reason))

# 8 - no location point is flagged
no_point = row("H", 0, 0, 0.0)
no_point["point"] = None
_n, _t, reason = compute(no_point, floors, [no_point])
check("no location point is flagged", reason == "no location point")


print("")
if failures:
    print(str(len(failures)) + " FAILURE(S): " + ", ".join(failures))
    sys.exit(1)
print("All push-up checks passed.")
