# -*- coding: utf-8 -*-
"""bench_rooms.py - tests the room geometry logic under plain CPython with
no Revit present:

  - point_in_loops_xy / room_contains_point_xy : 2D plan containment
  - find_linked_room_at_point                  : resolving a click to a
                                                 linked room
  - rooms_without_spaces                       : which rooms already have
                                                 a space

The thing all three share, and the reason they are tested together: none
of them may depend on Z. Testing a room's 3D volume with IsPointInRoom
brings in its base offset, upper limit and limit offset, and any of those
can reject a point that is plainly inside the room in plan - which showed
up as picking selecting nothing at all, and would show up again as
duplicate spaces on a second automatic run.

Run: python bench_rooms.py
"""
import io
import os
import sys


# --- stubs ---------------------------------------------------------------

class XYZ(object):
    def __init__(self, x, y, z):
        self.X, self.Y, self.Z = float(x), float(y), float(z)


class Transform(object):
    """Pure translation, enough to prove the coordinate handling."""

    def __init__(self, dx=0.0, dy=0.0, dz=0.0):
        self.dx, self.dy, self.dz = dx, dy, dz

    def OfPoint(self, p):
        return XYZ(p.X + self.dx, p.Y + self.dy, p.Z + self.dz)

    @property
    def Inverse(self):
        return Transform(-self.dx, -self.dy, -self.dz)


class Level(object):
    def __init__(self, elevation, name="Level"):
        self.Elevation = elevation
        self.Name = name


class BBox(object):
    def __init__(self, x0, y0, x1, y1):
        self.Min = XYZ(x0, y0, -10)
        self.Max = XYZ(x1, y1, 10)


class LocationPoint(object):
    def __init__(self, point):
        self.Point = point


class ElementId(object):
    def __init__(self, value):
        self.Value = value


class Curve(object):
    def __init__(self, p0, p1):
        self.p0, self.p1 = p0, p1

    def Tessellate(self):
        return [XYZ(self.p0[0], self.p0[1], 0), XYZ(self.p1[0], self.p1[1], 0)]

    def GetEndPoint(self, i):
        pt = self.p0 if i == 0 else self.p1
        return XYZ(pt[0], pt[1], 0)


class Segment(object):
    def __init__(self, curve):
        self._curve = curve

    def GetCurve(self):
        return self._curve


class Room(object):
    """Defined by explicit XY boundary loops, the way a real room is.

    Critically it does NOT implement IsPointInRoom - if the code under
    test ever goes back to using it, these tests fail with an
    AttributeError rather than silently passing."""

    def __init__(self, name, loops, level_elev=0.0, number=""):
        self.Name = name
        self.Number = number
        self._loops = loops
        self.Level = Level(level_elev, "L" + str(level_elev))
        self.Id = ElementId(abs(hash(name)) % 100000)
        xs = [p[0] for loop in loops for p in loop]
        ys = [p[1] for loop in loops for p in loop]
        self._bbox = BBox(min(xs), min(ys), max(xs), max(ys))
        # A real Room has a location point; rooms_in_box selects on it.
        self.Location = LocationPoint(
            XYZ((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0,
                level_elev))
        self.Area = 1.0

    def get_BoundingBox(self, view):
        return self._bbox

    def GetBoundarySegments(self, options):
        result = []
        for loop in self._loops:
            segments = []
            for i in range(len(loop)):
                segments.append(Segment(Curve(loop[i], loop[(i + 1) % len(loop)])))
            result.append(segments)
        return result


class NoBoundaryRoom(Room):
    def GetBoundarySegments(self, options):
        raise Exception("boundary unavailable")


class Space(object):
    def __init__(self, x, y, level_elev):
        self.Location = LocationPoint(XYZ(x, y, level_elev))
        self.Level = Level(level_elev)
        self.Area = 10.0


class LinkInstance(object):
    def __init__(self, value, transform):
        self.Id = ElementId(value)
        self._t = transform

    def GetTotalTransform(self):
        return self._t


def rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


# --- load the real functions ---------------------------------------------

def load_core():
    here = os.path.dirname(os.path.abspath(__file__))
    src = io.open(os.path.join(here, "../../../lib/revobim/space_creator_core.py"),
                  encoding="utf-8").read()
    start = src.index("def get_all_spaces")
    end = src.index("def linked_room_curve_loops")
    # level_elevation sits above the slice but everything in it depends on
    # the real function, so it is loaded rather than stubbed.
    helper_start = src.index("def level_elevation")
    helper_end = src.index("def eid_value")
    ns = {
        # The slice now includes the logging helpers, which reach for os,
        # io and the settings path at import time.
        "os": os,
        "io": io,
        "APPDATA_DIR": "/tmp/revobim_bench",
        # get_element_name reaches for these; the stub rooms answer
        # get_Parameter with the same string keys.
        "BuiltInParameter": type("BIP", (), {"ROOM_NAME": "ROOM_NAME",
                                             "ROOM_NUMBER": "ROOM_NUMBER"}),
        "Element": type("El", (), {"Name": None}),
        # The slice now covers the failure-handling helpers too.
        "IFailuresPreprocessor": object,
        "FailureProcessingResult": type("FPR", (), {"Continue": 0}),
        "Category": None,
        "_to_unicode": lambda text: text,
        "XYZ": XYZ,
        "Room": Room,
        "SpatialElementBoundaryOptions": lambda: None,
        "FilteredElementCollector": None,
        "BuiltInCategory": None,
        "eid_value": lambda eid: eid.Value if eid is not None else 0,
    }
    exec(compile(src[helper_start:helper_end], "core_helper", "exec"), ns)
    exec(compile(src[start:end], "core_snippet", "exec"), ns)
    return ns


ns = load_core()
room_contains_point_xy = ns["room_contains_point_xy"]
find_linked_room_at_point = ns["find_linked_room_at_point"]
rooms_without_spaces = ns["rooms_without_spaces"]

failures = []


def check(name, condition, detail=""):
    if condition:
        print("PASS  " + name)
    else:
        print("FAIL  " + name + "  " + detail)
        failures.append(name)


def names(rooms):
    return sorted(r.Name for r in rooms)


# =========================================================================
print("-- 2D containment")

square = Room("Square", [rect(0, 0, 10, 10)])
check("point inside a square", room_contains_point_xy(square, 5, 5, {}))
check("point outside a square", not room_contains_point_xy(square, 15, 5, {}))

# L-shape: the 20x20 square minus the top-right quadrant
l_shape = Room("LShaped", [[(0, 0), (20, 0), (20, 10), (10, 10),
                            (10, 20), (0, 20)]])
check("point in the solid arm of an L", room_contains_point_xy(l_shape, 5, 15, {}))
check("point in the notch of an L is outside",
      not room_contains_point_xy(l_shape, 15, 15, {}))

# Donut: outer square with an inner hole, two loops - even-odd handles it
donut = Room("Donut", [rect(0, 0, 20, 20), rect(8, 8, 12, 12)])
check("point in the ring of a donut room", room_contains_point_xy(donut, 2, 2, {}))
check("point in the hole of a donut room is outside",
      not room_contains_point_xy(donut, 10, 10, {}))

# Z is irrelevant - proved by there being no Z anywhere in the API used
check("a room with no readable boundary is not claimed",
      not room_contains_point_xy(NoBoundaryRoom("Bad", [rect(0, 0, 10, 10)]),
                                 5, 5, {}))


# =========================================================================
print("")
print("-- resolving a click to a linked room")

link_transform = Transform(100.0, 0.0, 12.0)      # link is offset and a floor up
link = LinkInstance(1, link_transform)

kitchen = Room("Kitchen", [rect(0, 0, 10, 10)], 0.0, "01")
office = Room("Office", [rect(10, 0, 20, 10)], 0.0, "02")
links = [(link, "linkdoc")]


def find(host_x, host_y, host_z):
    cache = {}
    ns["collect_link_rooms"] = lambda link_doc: [kitchen, office]
    return find_linked_room_at_point(links, XYZ(host_x, host_y, host_z), cache, {})


lnk, room = find(105.0, 5.0, 999.0)
check("resolves the kitchen whatever Z was picked",
      room is kitchen, "got " + str(room and room.Name))

lnk, room = find(115.0, 5.0, -400.0)
check("resolves the office through the link transform, negative Z",
      room is office, "got " + str(room and room.Name))

lnk, room = find(5.0, 5.0, 0.0)
check("an untransformed point matches nothing",
      room is None, "got " + str(room and room.Name))

lnk, room = find(500.0, 500.0, 0.0)
check("a far-away click matches nothing", room is None)

lnk, room = find(105.0, 5.0, 0.0)
check("returns the owning link instance", lnk is link)


# =========================================================================
print("")
print("-- which rooms already have a space")

k = Room("Kitchen", [rect(0, 0, 10, 10)], 0.0)
o = Room("Office", [rect(10, 0, 20, 10)], 0.0)
s = Room("Store", [rect(20, 0, 30, 10)], 0.0)

unplaced, placed = rooms_without_spaces(None, [k, o, s], [])
check("no spaces means every room unplaced",
      names(unplaced) == ["Kitchen", "Office", "Store"] and placed == [])

unplaced, placed = rooms_without_spaces(None, [k, o, s], [Space(5, 5, 0.0)])
check("a space inside a room marks that room placed",
      names(placed) == ["Kitchen"] and names(unplaced) == ["Office", "Store"],
      "placed=" + str(names(placed)))

unplaced, placed = rooms_without_spaces(None, [k, o, s], [Space(50, 50, 0.0)])
check("a space outside every room marks nothing", placed == [])

upper = Room("UpperKitchen", [rect(0, 0, 10, 10)], 12.0)
unplaced, placed = rooms_without_spaces(None, [k, upper], [Space(5, 5, 12.0)])
check("a space on the level above does not place the room below",
      names(placed) == ["UpperKitchen"] and names(unplaced) == ["Kitchen"],
      "placed=" + str(names(placed)))

unplaced, placed = rooms_without_spaces(
    None, [k, o, s], [Space(5, 5, 0.0), Space(25, 5, 0.0)])
check("mixed set resolves each room independently",
      names(placed) == ["Kitchen", "Store"] and names(unplaced) == ["Office"])

# The bounding-box prefilter must not be load-bearing: an L-shaped room
# whose notch is inside its own bounding box must not be claimed.
l_room = Room("LShaped", [[(0, 0), (20, 0), (20, 10), (10, 10),
                           (10, 20), (0, 20)]], 0.0)
unplaced, placed = rooms_without_spaces(None, [l_room], [Space(15, 15, 0.0)])
check("a space in an L-shaped room's notch does NOT place it",
      placed == [], "placed=" + str(names(placed)))

unplaced, placed = rooms_without_spaces(None, [l_room], [Space(5, 15, 0.0)])
check("a space in an L-shaped room's arm does place it",
      names(placed) == ["LShaped"])

unplaced, placed = rooms_without_spaces(None, [], [Space(5, 5, 0.0)])
check("empty room list returns empty", unplaced == [] and placed == [])


# =========================================================================
print("")
print("-- resolving a click across this model and the links")

find_room_at_point = ns["find_room_at_point"]
host_room = Room("HostRoom", [rect(0, 0, 10, 10)], 0.0, "H1")


def find_any(host_x, host_y, host_rooms):
    cache = {}
    ns["collect_link_rooms"] = lambda link_doc: [kitchen, office]
    return find_room_at_point(None, links, XYZ(host_x, host_y, 0.0),
                              host_rooms, cache, {})


# The case that used to be unreachable: the picker searched links only, so
# a natively modelled room could never be clicked however visible it was.
lnk, room = find_any(5.0, 5.0, [host_room])
check("a room in this model resolves, with no link",
      room is host_room and lnk is None,
      "got " + str(room and room.Name) + " link=" + str(lnk))

lnk, room = find_any(105.0, 5.0, [host_room])
check("a linked room still resolves alongside host rooms",
      room is kitchen and lnk is link, "got " + str(room and room.Name))

lnk, room = find_any(105.0, 5.0, [])
check("links are searched when this model has no rooms", room is kitchen)

lnk, room = find_any(900.0, 900.0, [host_room])
check("a click near nothing matches nothing", room is None)


# =========================================================================
print("")
print("-- selecting rooms by rectangle")

rooms_in_box = ns["rooms_in_box"]
is_click_not_box = ns["is_click_not_box"]

# Sources: this model holds one room, the link holds the kitchen/office.
host_only = [{"key": "host", "label": "This model", "link": None,
              "link_doc": None}]
link_only = [{"key": 1, "label": "Arch", "link": link, "link_doc": "d"}]
both_sources = host_only + link_only

# The host room sits at 0..10; kitchen/office are at 100..120 in host
# coordinates because of the link's 100ft offset.
ns["get_rooms"] = lambda d, scope, view: [host_room]
ns["collect_link_rooms"] = lambda link_doc: [kitchen, office]

hits = rooms_in_box(both_sources, XYZ(-5, -5, 0), XYZ(50, 50, 0), {})
check("a box over this model picks up its room only",
      [r.Name for _l, r in hits] == ["HostRoom"],
      str([r.Name for _l, r in hits]))

hits = rooms_in_box(both_sources, XYZ(95, -5, 0), XYZ(125, 50, 0), {})
check("a box over the link picks up both linked rooms",
      sorted(r.Name for _l, r in hits) == ["Kitchen", "Office"],
      str([r.Name for _l, r in hits]))

hits = rooms_in_box(both_sources, XYZ(-5, -5, 0), XYZ(125, 50, 0), {})
check("a box over everything picks up all three",
      len(hits) == 3, str(len(hits)))

hits = rooms_in_box(link_only, XYZ(-5, -5, 0), XYZ(50, 50, 0), {})
check("a box over this model finds nothing when only the link is chosen",
      hits == [], str([r.Name for _l, r in hits]))

hits = rooms_in_box(both_sources, XYZ(300, 300, 0), XYZ(400, 400, 0), {})
check("a box over empty space finds nothing", hits == [])

# The rectangle is normalised, so dragging right-to-left works the same.
hits = rooms_in_box(both_sources, XYZ(125, 50, 0), XYZ(95, -5, 0), {})
check("a box dragged backwards selects the same rooms",
      sorted(r.Name for _l, r in hits) == ["Kitchen", "Office"])

check("a tiny drag counts as a click",
      is_click_not_box(XYZ(10, 10, 0), XYZ(10.001, 10.001, 0)))
check("a real drag does not count as a click",
      not is_click_not_box(XYZ(10, 10, 0), XYZ(30, 30, 0)))


# =========================================================================
print("")
print("-- reading names off elements that refuse .Name")

get_element_name = ns["get_element_name"]
get_room_number = ns["get_room_number"]


class Param(object):
    def __init__(self, value, read_only=False):
        self._value = value
        self.IsReadOnly = read_only

    def AsString(self):
        return self._value


class HostileRoom(object):
    """Reproduces the field failure exactly: .Area works, .Name raises
    AttributeError. 408 rooms were found and every one was discarded on
    room.Name, which is what this guards against coming back."""

    Area = 100.0

    def __init__(self, name, number):
        self._name = name
        self._number = number

    @property
    def Name(self):
        raise AttributeError("Name")

    @property
    def Number(self):
        raise AttributeError("Number")

    def get_Parameter(self, bip):
        if bip == "ROOM_NAME":
            return Param(self._name)
        if bip == "ROOM_NUMBER":
            return Param(self._number)
        return None

    def LookupParameter(self, name):
        return None


class PlainRoom(object):
    """A room where the plain attribute works fine."""

    def __init__(self, name, number):
        self.Name = name
        self.Number = number

    def get_Parameter(self, bip):
        return None

    def LookupParameter(self, name):
        return None


hostile = HostileRoom("Plant Room", "R-204")
check("name is read from the parameter when .Name raises",
      get_element_name(hostile) == "Plant Room",
      repr(get_element_name(hostile)))
check("number is read from the parameter when .Number raises",
      get_room_number(hostile) == "R-204",
      repr(get_room_number(hostile)))

plain = PlainRoom("Office", "101")
check("the plain attribute is still used when it works",
      get_element_name(plain) == "Office", repr(get_element_name(plain)))
check("the plain number is still used when it works",
      get_room_number(plain) == "101", repr(get_room_number(plain)))


class SilentRoom(object):
    def get_Parameter(self, bip):
        return None

    def LookupParameter(self, name):
        return None


check("an element with no name anywhere returns empty, not an exception",
      get_element_name(SilentRoom()) == "")


# =========================================================================
print("")
print("-- only rooms on the view's level")

find_in_sources = ns["find_room_in_sources"]
rooms_in_box_lv = ns["rooms_in_box"]

# Two rooms stacked directly on top of each other, as in a real building:
# identical plan boundary, different levels. This is the field failure -
# two clicks a few millimetres apart returned a level 00 room and a level
# 04 room, because the plan test is deliberately two dimensional.
ground = Room("Club Shop", [rect(0, 0, 10, 10)], 0.0, "L00-009")
fourth = Room("Hospitality Lounge", [rect(0, 0, 10, 10)], 48.0, "L04-001")

stacked = [{"key": "host", "label": "This model", "link": None,
            "link_doc": None}]
ns["get_rooms"] = lambda d, scope, view: [fourth, ground]   # 4th listed first


band_for_elevation = ns["band_for_elevation"]


def find_in_band(band):
    return find_in_sources(stacked, XYZ(5, 5, 0), {}, {}, band)


lnk, room = find_in_band(band_for_elevation(0.0))
check("a band on the ground floor gets the ground floor room",
      room is ground, "got " + str(room and room.Name))

lnk, room = find_in_band(band_for_elevation(48.0))
check("a band on level 4 gets the level 4 room",
      room is fourth, "got " + str(room and room.Name))

# No band at all - a 3D view. The highest room wins, which is what a plan
# view shows: the storey you are on, not the ones beneath it.
lnk, room = find_in_band(None)
check("with no band the highest stacked room wins",
      room is fourth, "got " + str(room and room.Name))

lnk, room = find_in_band(band_for_elevation(500.0))
check("a band nowhere near either room matches nothing",
      room is None, "got " + str(room and room.Name))

# A wide band - a coordination plan whose view range reaches down several
# storeys. Both rooms qualify, and the higher one wins the click. This is
# the field case: a roof level view showing rooms far below it.
lnk, room = find_in_band((-10.0, 200.0))
check("a deep view range keeps both rooms and takes the higher",
      room is fourth, "got " + str(room and room.Name))

ns["get_rooms"] = lambda d, scope, view: [fourth, ground]
hits = rooms_in_box_lv(stacked, XYZ(-1, -1, 0), XYZ(11, 11, 0), {}, {},
                       band_for_elevation(0.0))
check("a box on the ground floor returns only the ground floor room",
      [r.Name for _l, r in hits] == ["Club Shop"],
      str([r.Name for _l, r in hits]))

ns["get_rooms"] = lambda d, scope, view: [fourth, ground]
hits = rooms_in_box_lv(stacked, XYZ(-1, -1, 0), XYZ(11, 11, 0), {}, {},
                       band_for_elevation(48.0))
check("a box on level 4 returns only the level 4 room",
      [r.Name for _l, r in hits] == ["Hospitality Lounge"],
      str([r.Name for _l, r in hits]))


# =========================================================================
print("")
print("-- survey elevations versus project elevations")

level_elevation = ns["level_elevation"]


class SurveyLevel(object):
    """A level whose Elevation Base is the Survey Point.

    `Elevation` reads 83m higher than the internal coordinates every
    geometry point is in. This is the real model's configuration, and
    comparing a room's point Z against `Elevation` chose the basement for
    a level 4 room, drew the separation lines there, and left every space
    unenclosed."""

    def __init__(self, name, project_elevation, survey_offset=272.0):
        self.Name = name
        self.ProjectElevation = project_elevation
        self.Elevation = project_elevation + survey_offset


class PlainLevel(object):
    """A level with no survey offset - Elevation only."""

    def __init__(self, name, elevation):
        self.Name = name
        self.Elevation = elevation


survey = SurveyLevel("L04", 56.5)
check("the project elevation is preferred over the survey one",
      level_elevation(survey) == 56.5, str(level_elevation(survey)))

plain = PlainLevel("L00", 12.0)
check("a level with no ProjectElevation falls back to Elevation",
      level_elevation(plain) == 12.0, str(level_elevation(plain)))

check("a missing level returns None", level_elevation(None) is None)

# The banding must work off project elevations, or a room sitting at its
# real Z is judged against a level 83m away.
# The room's geometry sits at its PROJECT elevation, which is the whole
# point: its own level reports 272ft higher.
survey_room = Room("SurveyRoom", [rect(0, 0, 10, 10)], 56.5)
survey_room.Level = SurveyLevel("L04", 56.5)
survey_sources = [{"key": "host", "label": "This model", "link": None,
                   "link_doc": None}]
ns["get_rooms"] = lambda d, scope, view: [survey_room]

lnk, room = find_in_sources(survey_sources, XYZ(5, 5, 0), {}, {},
                            band_for_elevation(56.5))
check("a band built from project elevations finds the room",
      room is survey_room, "got " + str(room and room.Name))

ns["get_rooms"] = lambda d, scope, view: [survey_room]
lnk, room = find_in_sources(survey_sources, XYZ(5, 5, 0), {}, {},
                            band_for_elevation(56.5 + 272.0))
check("a band built from survey elevations does NOT find it",
      room is None, "got " + str(room and room.Name))


print("")
if failures:
    print(str(len(failures)) + " FAILURE(S): " + ", ".join(failures))
    sys.exit(1)
print("All room geometry checks passed.")
