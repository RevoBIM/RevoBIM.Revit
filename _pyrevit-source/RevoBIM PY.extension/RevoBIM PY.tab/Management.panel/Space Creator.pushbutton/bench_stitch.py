# -*- coding: utf-8 -*-
"""bench_stitch.py - tests stitch_curve_loop's ordering, gap bridging,
collinear merging and loop closing against stub geometry, under plain
CPython with no Revit present.

Run: python bench_stitch.py
"""
import math
import sys
import types


# --- stub geometry -------------------------------------------------------

class XYZ(object):
    def __init__(self, x, y, z):
        self.X, self.Y, self.Z = float(x), float(y), float(z)

    def DistanceTo(self, other):
        return math.sqrt((self.X - other.X) ** 2 +
                         (self.Y - other.Y) ** 2 +
                         (self.Z - other.Z) ** 2)

    def CrossProduct(self, o):
        return XYZ(self.Y * o.Z - self.Z * o.Y,
                   self.Z * o.X - self.X * o.Z,
                   self.X * o.Y - self.Y * o.X)

    def DotProduct(self, o):
        return self.X * o.X + self.Y * o.Y + self.Z * o.Z

    def GetLength(self):
        return math.sqrt(self.X ** 2 + self.Y ** 2 + self.Z ** 2)

    def __repr__(self):
        return "({0:.2f},{1:.2f},{2:.2f})".format(self.X, self.Y, self.Z)


class Line(object):
    def __init__(self, p0, p1):
        self._p0, self._p1 = p0, p1

    @staticmethod
    def CreateBound(p0, p1):
        if p0.DistanceTo(p1) < 1e-9:
            raise ValueError("zero length")
        return Line(p0, p1)

    def GetEndPoint(self, i):
        return self._p0 if i == 0 else self._p1

    @property
    def Length(self):
        return self._p0.DistanceTo(self._p1)

    @property
    def Direction(self):
        d = self.Length
        return XYZ((self._p1.X - self._p0.X) / d,
                   (self._p1.Y - self._p0.Y) / d,
                   (self._p1.Z - self._p0.Z) / d)

    def CreateReversed(self):
        return Line(self._p1, self._p0)

    def __repr__(self):
        return "Line{0}->{1}".format(self._p0, self._p1)


class Arc(object):
    pass


# --- load the real functions from the core module ------------------------

CORE = "../../../lib/revobim/space_creator_core.py"


def load_core_functions():
    """Pulls the stitching functions out of the real module source without
    importing Revit - the module is exec'd with stub names injected."""
    import io
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    src = io.open(os.path.join(here, CORE), encoding="utf-8").read()

    start = src.index("DEFAULT_TOLERANCE = ")
    end = src.index("def _draw_stitched_loops")
    snippet = src[start:end]

    namespace = {"XYZ": XYZ, "Line": Line, "Arc": Arc}
    exec(compile(snippet, "core_snippet", "exec"), namespace)
    return namespace


ns = load_core_functions()
stitch = ns["stitch_curve_loop"]

failures = []


def check(name, condition, detail=""):
    if condition:
        print("PASS  " + name)
    else:
        print("FAIL  " + name + "  " + detail)
        failures.append(name)


def p(x, y):
    return XYZ(x, y, 0)


# --- tests ---------------------------------------------------------------

# 1. A square already in order, each side split in two -> 4 merged sides
square_split = [
    Line(p(0, 0), p(5, 0)), Line(p(5, 0), p(10, 0)),
    Line(p(10, 0), p(10, 5)), Line(p(10, 5), p(10, 10)),
    Line(p(10, 10), p(5, 10)), Line(p(5, 10), p(0, 10)),
    Line(p(0, 10), p(0, 5)), Line(p(0, 5), p(0, 0)),
]
result = stitch(list(square_split))
check("square with split sides merges to 4 curves", len(result) == 4,
      "got " + str(len(result)))

# 2. Result is a closed continuous chain
def is_continuous_closed(curves, tol=0.0026):
    for i in range(len(curves)):
        end = curves[i].GetEndPoint(1)
        start = curves[(i + 1) % len(curves)].GetEndPoint(0)
        if end.DistanceTo(start) > tol:
            return False
    return True

check("stitched square is continuous and closed", is_continuous_closed(result))

# 3. Out of order and with some segments reversed
shuffled = [
    Line(p(10, 10), p(0, 10)),
    Line(p(0, 0), p(10, 0)),
    Line(p(0, 10), p(0, 0)),
    Line(p(10, 0), p(10, 10)),
]
result3 = stitch(list(shuffled))
check("out-of-order/reversed segments reorder into 4", len(result3) == 4,
      "got " + str(len(result3)))
check("reordered square is continuous and closed", is_continuous_closed(result3))

# 4. An open loop (missing side) gets closed
open_loop = [
    Line(p(0, 0), p(10, 0)),
    Line(p(10, 0), p(10, 10)),
    Line(p(10, 10), p(0, 10)),
]
result4 = stitch(list(open_loop))
check("open loop is closed by a bridging line", len(result4) == 4,
      "got " + str(len(result4)))
check("closed open-loop is continuous", is_continuous_closed(result4))

# 5. A gap mid-perimeter is bridged
gapped = [
    Line(p(0, 0), p(10, 0)),
    Line(p(10, 0), p(10, 10)),
    Line(p(9, 10), p(0, 10)),      # 1.0 gap
    Line(p(0, 10), p(0, 0)),
]
result5 = stitch(list(gapped))
check("gap mid-perimeter is bridged", is_continuous_closed(result5))

# 6. Zero-length / tiny segments are dropped
tiny = [
    Line(p(0, 0), p(10, 0)),
    Line(p(10, 0), p(10.0001, 0)),   # below tolerance
    Line(p(10, 0), p(10, 10)),
    Line(p(10, 10), p(0, 10)),
    Line(p(0, 10), p(0, 0)),
]
result6 = stitch(list(tiny))
check("sub-tolerance segments dropped, still 4 sides", len(result6) == 4,
      "got " + str(len(result6)))

# 7. The closing seam merges when first and last are collinear
seam = [
    Line(p(5, 0), p(10, 0)),
    Line(p(10, 0), p(10, 10)),
    Line(p(10, 10), p(0, 10)),
    Line(p(0, 10), p(0, 0)),
    Line(p(0, 0), p(5, 0)),
]
result7 = stitch(list(seam))
check("collinear seam at loop start/end merges to 4", len(result7) == 4,
      "got " + str(len(result7)))

# 8. Empty input is handled
check("empty input returns empty", stitch([]) == [])

# 9. A single curve does not crash
check("single curve survives", len(stitch([Line(p(0, 0), p(1, 0))])) >= 1)


print("")
if failures:
    print(str(len(failures)) + " FAILURE(S): " + ", ".join(failures))
    sys.exit(1)
print("All stitching checks passed.")
