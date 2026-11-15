# -*- coding: utf-8 -*-
"""
space_creator_core.py
Shared logic for the RevoBIM PY Space Creator tools:
  - Place Automatic Spaces
  - Space From Room Manual

Written for IronPython 2.7 / IronPython 3 (pyRevit engine varies by release)
and for Revit 2024 - 2027 (.NET Framework 4.8 through .NET 8).

Rules followed (see RevoBIM PY theme reference):
  - no f-strings, no bare .IntegerValue, no System.Uri
  - settings persisted as plain key=value text under %APPDATA%\\RevoBIM\\
  - everything a run creates sits in one transaction
"""

import os
import io

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

from Autodesk.Revit.DB import (
    FilteredElementCollector,
    FilteredWorksetCollector,
    WorksetKind,
    WorksetId,
    BuiltInCategory,
    BuiltInParameter,
    Category,
    Element,
    IFailuresPreprocessor,
    FailureProcessingResult,
    Transaction,
    TransactionGroup,
    SpatialElementBoundaryOptions,
    CurveArray,
    Line,
    Arc,
    UV,
    XYZ,
    Level,
)

try:
    from Autodesk.Revit.DB.Architecture import Room
except Exception:
    Room = None

try:
    from Autodesk.Revit.DB import Floor
except Exception:
    Floor = None


__version__ = "1.0.0"

APPDATA_DIR = os.path.join(os.environ.get("APPDATA", ""), "RevoBIM")
SETTINGS_PATH = os.path.join(APPDATA_DIR, "space_creator.txt")

DEFAULT_SETTINGS = {
    "scope": "current_view",          # current_view | all_project
    "room_source": "both",            # host | links | both
    "create_separation_lines": "1",
    "clear_existing": "0",
    "push_to_ceiling": "0",
    "inherit_room_name": "1",
    "workset_name": "",
    "boundary_mode": "lines",         # lines | native  (manual tool)
}


# ---------------------------------------------------------------------------
# Cross-version helpers
# ---------------------------------------------------------------------------

def level_elevation(level):
    """A level's elevation **in the same coordinates as geometry**.

    `Level.Elevation` is reported relative to whatever the level's
    'Elevation Base' parameter is set to. Where that is the Survey Point -
    normal on a coordinated project - it returns survey elevations, while
    every point returned by the geometry API is in internal project
    coordinates. On the model this was found on the two differ by 83
    metres, so comparing a room's point Z against `Level.Elevation` picked
    the basement for a room on level 4, put the separation lines there,
    and every space came out unenclosed.

    `ProjectElevation` is the internal one and is what must be compared
    against a point's Z."""
    if level is None:
        return None
    try:
        return level.ProjectElevation
    except Exception:
        pass
    try:
        return level.Elevation
    except Exception:
        return None


def eid_value(element_id):
    """Version-safe read of an ElementId's integer value.
    ElementId.IntegerValue was removed in Revit 2026 in favour of .Value.
    """
    if element_id is None:
        return 0
    try:
        return element_id.Value
    except Exception:
        pass
    try:
        return element_id.IntegerValue
    except Exception:
        return 0


def workset_id_value(workset_id):
    """WorksetId is a different type to ElementId and has kept .IntegerValue
    across every Revit release used here, but this is routed through a
    helper for symmetry and in case a future Revit release changes it too."""
    if workset_id is None:
        return -1
    try:
        return workset_id.IntegerValue
    except Exception:
        try:
            return workset_id.Value
        except Exception:
            return -1


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def load_settings():
    settings = dict(DEFAULT_SETTINGS)
    if not os.path.isfile(SETTINGS_PATH):
        return settings
    try:
        f = io.open(SETTINGS_PATH, "r", encoding="utf-8")
    except Exception:
        try:
            f = open(SETTINGS_PATH, "r")
        except Exception:
            return settings
    try:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if key in DEFAULT_SETTINGS:
                settings[key] = value.strip()
    except Exception:
        pass
    finally:
        try:
            f.close()
        except Exception:
            pass
    return settings


def save_settings(settings):
    try:
        if not os.path.isdir(APPDATA_DIR):
            os.makedirs(APPDATA_DIR)
    except Exception:
        pass
    lines = []
    for key in DEFAULT_SETTINGS:
        value = settings.get(key, DEFAULT_SETTINGS[key])
        lines.append(key + "=" + str(value))
    text = "\n".join(lines)
    try:
        f = io.open(SETTINGS_PATH, "w", encoding="utf-8")
        f.write(_to_unicode(text))
        f.close()
    except Exception:
        try:
            f = open(SETTINGS_PATH, "w")
            f.write(text)
            f.close()
        except Exception:
            pass


def _is_ipy2():
    try:
        unicode
        return True
    except NameError:
        return False


def _to_unicode(text):
    if _is_ipy2():
        try:
            return unicode(text)
        except Exception:
            return text
    return text


# ---------------------------------------------------------------------------
# Worksets
# ---------------------------------------------------------------------------

def get_user_worksets(doc):
    """Returns a list of (name, WorksetId) for user worksets, sorted by
    name (case-insensitive), or an empty list on a non-workshared model."""
    result = []
    try:
        if not doc.IsWorkshared:
            return result
    except Exception:
        return result
    try:
        collector = FilteredWorksetCollector(doc).OfKind(WorksetKind.UserWorkset)
        for ws in collector:
            result.append((ws.Name, ws.Id))
    except Exception:
        pass
    result.sort(key=lambda pair: (pair[0] or "").lower())
    return result


def set_element_workset(doc, element, workset_id):
    if workset_id is None:
        return False
    try:
        param = element.get_Parameter(BuiltInParameter.ELEM_PARTITION_PARAM)
        if param is not None and not param.IsReadOnly:
            param.Set(workset_id_value(workset_id))
            return True
    except Exception:
        pass
    return False


# ---------------------------------------------------------------------------
# Temporary room visibility
#
# A linked room can only be clicked if Rooms and Room Reference are visible
# in the host view - linked elements follow the host view's category
# settings unless the link is set to custom. These turn them on for the
# duration of a pick and put the view back exactly as it was afterwards.
# ---------------------------------------------------------------------------

def _room_visibility_categories():
    """Looked up late via getattr rather than at module level, so a member
    missing on a given release is skipped rather than killing the import.

    Interior Fill matters as much as Reference: with only Reference on, a
    room can only be clicked on its crosshair lines, not anywhere inside
    its area. RvtLinks is included because a hidden link hides everything
    in it regardless of the room settings."""
    names = ["OST_Rooms", "OST_RoomReference", "OST_RoomInteriorFill", "OST_RvtLinks"]
    result = []
    for name in names:
        member = getattr(BuiltInCategory, name, None)
        if member is not None:
            result.append((name, member))
    return result


def force_links_by_host_view(doc, view):
    """Sets every loaded link's display settings in this view to By Host
    View, so the host's now-visible Rooms category actually reaches the
    linked rooms.

    This is the part that host category visibility alone cannot do: a link
    set to 'By Linked View' or 'Custom' ignores the host's categories
    entirely, so turning Rooms on in the host view has no effect on it and
    the rooms stay unclickable. Must be called inside a transaction.
    Returns (restore_list, error_or_None)."""
    restore = []
    try:
        from Autodesk.Revit.DB import (RevitLinkGraphicsSettings,
                                       RevitLinkInstance, LinkVisibility)
    except Exception as ex:
        return restore, "link display settings unavailable: " + str(ex)

    error = None
    try:
        links = FilteredElementCollector(doc, view.Id).OfClass(RevitLinkInstance)
    except Exception as ex:
        return restore, "could not list links: " + str(ex)

    for link in links:
        try:
            current = view.GetLinkOverrides(link.Id)
        except Exception:
            continue

        try:
            if current is not None and \
                    current.LinkVisibilityType == LinkVisibility.ByHostView:
                continue
        except Exception:
            pass

        try:
            wanted = RevitLinkGraphicsSettings()
            wanted.LinkVisibilityType = LinkVisibility.ByHostView
            view.SetLinkOverrides(link.Id, wanted)
            restore.append((link.Id, current))
        except Exception as ex:
            if error is None:
                error = str(ex)

    return restore, error


def restore_link_overrides(view, restore):
    """Puts back whatever force_links_by_host_view() changed. Must be
    called inside a transaction."""
    for link_id, settings in restore:
        try:
            view.SetLinkOverrides(link_id, settings)
        except Exception:
            continue


def show_room_categories(doc, view):
    """Makes Rooms and Room Reference visible in view. Must be called inside
    a transaction. Returns (restore_list, error_or_None) where restore_list
    is what to hand back to restore_category_visibility()."""
    restore = []

    try:
        if view.ViewTemplateId is not None and eid_value(view.ViewTemplateId) > 0:
            # A template may lock V/G; SetCategoryHidden then throws. Try
            # anyway and report, rather than refusing up front - most
            # templates do not control the room categories.
            pass
    except Exception:
        pass

    error = None
    for name, bic in _room_visibility_categories():
        try:
            category = Category.GetCategory(doc, bic)
        except Exception:
            category = None
        if category is None:
            continue
        try:
            was_hidden = view.GetCategoryHidden(category.Id)
        except Exception:
            continue
        if not was_hidden:
            continue
        try:
            view.SetCategoryHidden(category.Id, False)
            restore.append((category.Id, True))
        except Exception as ex:
            if error is None:
                error = name + ": " + str(ex)
    return restore, error


def restore_category_visibility(view, restore):
    """Puts back whatever show_room_categories() turned on. Must be called
    inside a transaction."""
    for category_id, was_hidden in restore:
        try:
            view.SetCategoryHidden(category_id, was_hidden)
        except Exception:
            continue


# ---------------------------------------------------------------------------
# Room collection
# ---------------------------------------------------------------------------

def get_rooms(doc, scope, active_view):
    """scope is 'current_view' or 'all_project'."""
    rooms = []
    try:
        if scope == "current_view" and active_view is not None:
            collector = FilteredElementCollector(doc, active_view.Id)
        else:
            collector = FilteredElementCollector(doc)
        collector = collector.OfCategory(BuiltInCategory.OST_Rooms).WhereElementIsNotElementType()
        for el in collector:
            try:
                if Room is not None and not isinstance(el, Room):
                    continue
                if el.Area > 0:
                    rooms.append(el)
            except Exception:
                continue
    except Exception:
        pass
    return rooms


def get_existing_spaces_and_lines(doc, scope, active_view):
    spaces = []
    lines = []
    try:
        if scope == "current_view" and active_view is not None:
            base_collector_1 = FilteredElementCollector(doc, active_view.Id)
            base_collector_2 = FilteredElementCollector(doc, active_view.Id)
        else:
            base_collector_1 = FilteredElementCollector(doc)
            base_collector_2 = FilteredElementCollector(doc)

        for el in base_collector_1.OfCategory(BuiltInCategory.OST_MEPSpaces).WhereElementIsNotElementType():
            spaces.append(el)
        for el in base_collector_2.OfCategory(BuiltInCategory.OST_MEPSpaceSeparationLines).WhereElementIsNotElementType():
            lines.append(el)
    except Exception:
        pass
    return spaces, lines


# ---------------------------------------------------------------------------
# Space separation lines
#
# Room boundaries come back from GetBoundarySegments as many short segments -
# split at every wall junction, door and embedded column. Drawing them one
# for one leaves a perimeter made of dozens of stubs. These helpers stitch a
# loop into a single continuous closed perimeter first: ordered end to end,
# consecutive collinear lines merged into one, gaps bridged, and the loop
# closed back to its start.
# ---------------------------------------------------------------------------

DEFAULT_TOLERANCE = 0.0026          # ~1/32", Revit's short curve tolerance
COLLINEAR_TOLERANCE = 1.0e-6


def _short_curve_tolerance(doc):
    try:
        value = doc.Application.ShortCurveTolerance
        if value and value > 0:
            return value
    except Exception:
        pass
    return DEFAULT_TOLERANCE


def _pts_equal(a, b, tol):
    try:
        return a.DistanceTo(b) <= tol
    except Exception:
        return False


def _flatten_curve(curve, z_value):
    """Returns the curve with both ends (and, for an arc, its mid point)
    moved onto the z_value plane. NewSpaceBoundaryLines rejects a curve that
    is not on its sketch plane, and a linked room's boundary curves rarely
    sit at exactly the elevation the plane gets built at."""
    try:
        p0 = curve.GetEndPoint(0)
        p1 = curve.GetEndPoint(1)
        flat0 = XYZ(p0.X, p0.Y, z_value)
        flat1 = XYZ(p1.X, p1.Y, z_value)

        if isinstance(curve, Line):
            return Line.CreateBound(flat0, flat1)

        mid = curve.Evaluate(0.5, True)
        flat_mid = XYZ(mid.X, mid.Y, z_value)
        return Arc.Create(flat0, flat_mid, flat1)
    except Exception:
        return None


def _try_merge(curve_a, curve_b, tol):
    """Merges two consecutive collinear, same-direction Lines into one.
    Returns None if they cannot be merged (an arc, a corner, a reversal)."""
    if not (isinstance(curve_a, Line) and isinstance(curve_b, Line)):
        return None
    if not _pts_equal(curve_a.GetEndPoint(1), curve_b.GetEndPoint(0), tol):
        return None
    try:
        dir_a = curve_a.Direction
        dir_b = curve_b.Direction
        if dir_a.CrossProduct(dir_b).GetLength() > COLLINEAR_TOLERANCE:
            return None
        if dir_a.DotProduct(dir_b) < 0:
            return None
        return Line.CreateBound(curve_a.GetEndPoint(0), curve_b.GetEndPoint(1))
    except Exception:
        return None


def _merge_collinear(chain, tol, closed):
    if not chain:
        return chain
    merged = [chain[0]]
    for curve in chain[1:]:
        combined = _try_merge(merged[-1], curve, tol)
        if combined is not None:
            merged[-1] = combined
        else:
            merged.append(curve)
    # The seam where the loop closes is a join like any other - if the last
    # and first runs are collinear they belong to one side of the room.
    if closed and len(merged) > 1:
        combined = _try_merge(merged[-1], merged[0], tol)
        if combined is not None:
            merged[0] = combined
            merged.pop()
    return merged


def stitch_curve_loop(curves, tol=DEFAULT_TOLERANCE, close_loop=True):
    """Orders curves end to end, bridges any gaps, closes the loop and
    merges collinear runs, so the result is one continuous perimeter."""
    remaining = []
    for curve in curves:
        if curve is None:
            continue
        try:
            if curve.Length <= tol:
                continue
        except Exception:
            pass
        remaining.append(curve)

    if not remaining:
        return []

    chain = [remaining.pop(0)]

    while remaining:
        end_point = chain[-1].GetEndPoint(1)

        matched_index = None
        matched_curve = None
        for index, curve in enumerate(remaining):
            if _pts_equal(end_point, curve.GetEndPoint(0), tol):
                matched_index, matched_curve = index, curve
                break
            if _pts_equal(end_point, curve.GetEndPoint(1), tol):
                try:
                    matched_index, matched_curve = index, curve.CreateReversed()
                except Exception:
                    continue
                break

        if matched_curve is None:
            # Nothing joins on: take the nearest remaining end and bridge
            # the gap, rather than abandoning the rest of the perimeter.
            best_index = None
            best_curve = None
            best_distance = None
            for index, curve in enumerate(remaining):
                for reversed_flag in (False, True):
                    try:
                        candidate = curve.CreateReversed() if reversed_flag else curve
                        distance = end_point.DistanceTo(candidate.GetEndPoint(0))
                    except Exception:
                        continue
                    if best_distance is None or distance < best_distance:
                        best_distance = distance
                        best_index = index
                        best_curve = candidate
            if best_curve is None:
                break
            if best_distance is not None and best_distance > tol:
                try:
                    chain.append(Line.CreateBound(end_point, best_curve.GetEndPoint(0)))
                except Exception:
                    pass
            chain.append(best_curve)
            remaining.pop(best_index)
        else:
            chain.append(matched_curve)
            remaining.pop(matched_index)

    if close_loop and len(chain) > 1:
        start_point = chain[0].GetEndPoint(0)
        end_point = chain[-1].GetEndPoint(1)
        try:
            if start_point.DistanceTo(end_point) > tol:
                chain.append(Line.CreateBound(end_point, start_point))
        except Exception:
            pass

    return _merge_collinear(chain, tol, close_loop)


def _draw_stitched_loops(doc, loops_of_curves, elevation, view, level=None,
                         plane_cache=None):
    """Shared back end: builds one sketch plane, then draws each already
    stitched loop as a single continuous run of space separation lines.
    Returns (loops_drawn, first_error_or_None).

    When a level is given, the sketch plane is built **from that level**
    and the curves are flattened to the level's own elevation rather than
    to whatever Z was passed in.

    This matters more than it looks. A separation line only bounds a space
    that shares its level. Drawing the lines at a linked room's location
    point Z - which carries the link's transform and the room's base
    offset - puts them a little off the host level the space is created
    on, and Revit then reports every space as 'not in a properly enclosed
    region' even though the perimeter is visibly right there."""
    try:
        from Autodesk.Revit.DB import SketchPlane, Plane
    except Exception as ex:
        return 0, "SketchPlane/Plane unavailable: " + str(ex)

    if level is not None:
        resolved = level_elevation(level)
        if resolved is not None:
            elevation = resolved

    # One sketch plane per level, not one per room. SketchPlane.Create
    # makes a real element each time, so a batch of several hundred rooms
    # was creating several hundred identical planes - the largest single
    # cost in a run, and all of it avoidable.
    if plane_cache is None:
        plane_cache = {}
    if level is not None:
        cache_key = ("level", eid_value(level.Id))
    else:
        cache_key = ("elev", int(round(elevation * 1000.0)))

    sketch_plane = plane_cache.get(cache_key)

    if sketch_plane is None:
        if level is not None:
            try:
                sketch_plane = SketchPlane.Create(doc, level.Id)
            except Exception:
                sketch_plane = None
        if sketch_plane is None:
            try:
                plane = Plane.CreateByNormalAndOrigin(XYZ.BasisZ,
                                                      XYZ(0, 0, elevation))
                sketch_plane = SketchPlane.Create(doc, plane)
            except Exception as ex:
                return 0, "could not create sketch plane: " + str(ex)
        plane_cache[cache_key] = sketch_plane

    tol = _short_curve_tolerance(doc)

    drawn = 0
    first_error = None
    for curves in loops_of_curves:
        flattened = []
        for curve in curves:
            flat = _flatten_curve(curve, elevation)
            if flat is not None:
                flattened.append(flat)

        stitched = stitch_curve_loop(flattened, tol, True)
        if not stitched:
            continue

        curve_array = CurveArray()
        for curve in stitched:
            try:
                curve_array.Append(curve)
            except Exception:
                continue
        if curve_array.Size == 0:
            continue

        try:
            doc.Create.NewSpaceBoundaryLines(sketch_plane, curve_array, view)
            drawn += 1
        except Exception as ex:
            if first_error is None:
                first_error = str(ex)
            continue

    return drawn, first_error


def create_separation_lines_for_room(doc, room, view, plane_cache=None):
    """Draws one continuous closed run of space separation lines around
    each of the room's boundary loops. Returns (loops_drawn, error)."""
    options = SpatialElementBoundaryOptions()
    try:
        loops = room.GetBoundarySegments(options)
    except Exception as ex:
        return 0, "could not read room boundary: " + str(ex)
    if not loops:
        return 0, "room has no boundary segments"

    elevation = 0.0
    level = None
    try:
        level = room.Level
    except Exception:
        level = None
    if level is not None:
        elevation = level_elevation(level) or 0.0

    loops_of_curves = []
    for loop in loops:
        curves = []
        for segment in loop:
            try:
                curves.append(segment.GetCurve())
            except Exception:
                continue
        if curves:
            loops_of_curves.append(curves)

    return _draw_stitched_loops(doc, loops_of_curves, elevation, view, level,
                                plane_cache)


def create_separation_lines_for_curve_loops(doc, curve_loops, elevation, view,
                                            level=None, plane_cache=None):
    """Same as above but for explicit curve loops already transformed into
    host coordinates - used by the manual linked-room tool.

    Pass the host level the space will be created on: the lines must share
    that level to bound it.
    Returns (loops_drawn, error)."""
    return _draw_stitched_loops(doc, curve_loops, elevation, view, level,
                                plane_cache)


def get_all_spaces(doc):
    """Every placed space in the document. Deliberately project-wide even
    when placing into one view: a room already given a space elsewhere must
    not be given a second one."""
    spaces = []
    try:
        collector = FilteredElementCollector(doc) \
            .OfCategory(BuiltInCategory.OST_MEPSpaces).WhereElementIsNotElementType()
        for el in collector:
            try:
                if el.Area > 0:
                    spaces.append(el)
            except Exception:
                spaces.append(el)
    except Exception:
        pass
    return spaces


LEVEL_BUCKET = 1.0          # ft, bucket width for matching spaces to levels


def _space_points_by_level(spaces):
    """Buckets space location points by rounded level elevation, so a room
    only has to be tested against the spaces near its own level rather than
    against every space in the project."""
    buckets = {}
    for space in spaces:
        try:
            point = space.Location.Point
        except Exception:
            continue
        elevation = None
        try:
            elevation = level_elevation(space.Level)
            if elevation is None:
                elevation = point.Z
        except Exception:
            elevation = point.Z
        key = int(round(elevation / LEVEL_BUCKET))
        buckets.setdefault(key, []).append(point)
    return buckets


def rooms_without_spaces(doc, rooms, spaces=None):
    """Splits rooms into (unplaced, already_placed).

    A room counts as already having a space when a space's location point
    falls inside it. The room's bounding box is checked first because it is
    cheap, and the plan-boundary walk only runs on what survives that - on
    a real model this is the difference between instant and unusable, since
    the naive form is every room against every space.

    Containment is tested in 2D against the room's plan boundary, not with
    IsPointInRoom: that tests the room's 3D volume, which depends on its
    base offset, upper limit and limit offset, and a room with any of those
    set can reject a space that is plainly inside it - which would show up
    as duplicate spaces on the next run."""
    if spaces is None:
        spaces = get_all_spaces(doc)

    buckets = _space_points_by_level(spaces)
    loop_cache = {}

    unplaced = []
    placed = []

    for room in rooms:
        elevation = level_elevation(room.Level) or 0.0

        key = int(round(elevation / LEVEL_BUCKET))
        candidates = []
        for offset in (-1, 0, 1):
            candidates.extend(buckets.get(key + offset, []))

        if not candidates:
            unplaced.append(room)
            continue

        bbox = None
        try:
            bbox = room.get_BoundingBox(None)
        except Exception:
            bbox = None

        has_space = False
        for point in candidates:
            if bbox is not None:
                if not (bbox.Min.X <= point.X <= bbox.Max.X and
                        bbox.Min.Y <= point.Y <= bbox.Max.Y):
                    continue
            try:
                if room_contains_point_xy(room, point.X, point.Y, loop_cache):
                    has_space = True
                    break
            except Exception:
                continue

        if has_space:
            placed.append(room)
        else:
            unplaced.append(room)

    return unplaced, placed


def describe_space(space, room):
    """A (level, number, name) tuple for the results list."""
    level_name = ""
    try:
        level_name = room.Level.Name
    except Exception:
        pass
    if not level_name:
        try:
            level_name = space.Level.Name
        except Exception:
            level_name = ""

    number = get_room_number(space)
    name = get_element_name(space)

    return (level_name, number, name)


def get_loaded_link_instances(doc):
    """Every RevitLinkInstance whose document is actually loaded, as
    (link_instance, link_document) pairs. Unloaded links are left out
    rather than offered and then failing."""
    result = []
    try:
        from Autodesk.Revit.DB import RevitLinkInstance
    except Exception:
        return result
    try:
        for link in FilteredElementCollector(doc).OfClass(RevitLinkInstance):
            try:
                link_doc = link.GetLinkDocument()
            except Exception:
                continue
            if link_doc is not None:
                result.append((link, link_doc))
    except Exception:
        pass
    return result


def collect_link_rooms(link_doc):
    """Every placed room in a link document."""
    rooms = []
    try:
        collector = FilteredElementCollector(link_doc) \
            .OfCategory(BuiltInCategory.OST_Rooms).WhereElementIsNotElementType()
        for el in collector:
            try:
                if Room is not None and not isinstance(el, Room):
                    continue
                if el.Area > 0:
                    rooms.append(el)
            except Exception:
                continue
    except Exception:
        pass
    return rooms


def _room_loops_xy(room, loop_cache=None):
    """The room's boundary loops flattened to a list of (x, y) polygons in
    the room's own document coordinates.

    Curves are tessellated so an arc wall is followed properly rather than
    being treated as a straight chord."""
    if loop_cache is not None:
        key = id(room)
        if key in loop_cache:
            return loop_cache[key]

    loops = []
    try:
        options = SpatialElementBoundaryOptions()
        for loop in room.GetBoundarySegments(options):
            points = []
            for segment in loop:
                try:
                    curve = segment.GetCurve()
                except Exception:
                    continue
                try:
                    for point in curve.Tessellate():
                        points.append((point.X, point.Y))
                except Exception:
                    try:
                        p0 = curve.GetEndPoint(0)
                        p1 = curve.GetEndPoint(1)
                        points.append((p0.X, p0.Y))
                        points.append((p1.X, p1.Y))
                    except Exception:
                        continue
            if len(points) >= 3:
                loops.append(points)
    except Exception:
        loops = []

    if loop_cache is not None:
        loop_cache[id(room)] = loops
    return loops


def point_in_loops_xy(x, y, loops):
    """Even-odd point in polygon across every loop at once.

    Even-odd is what makes a room with a hole in it - a core, a shaft -
    come out right without having to work out which loop is the outer one:
    a point inside the hole crosses two boundaries and lands back outside."""
    inside = False
    for points in loops:
        count = len(points)
        j = count - 1
        for i in range(count):
            xi, yi = points[i]
            xj, yj = points[j]
            if (yi > y) != (yj > y):
                try:
                    x_cross = (xj - xi) * (y - yi) / (yj - yi) + xi
                except ZeroDivisionError:
                    j = i
                    continue
                if x < x_cross:
                    inside = not inside
            j = i
    return inside


def room_contains_point_xy(room, x, y, loop_cache=None):
    """True when (x, y), in the room's own document coordinates, is inside
    the room's plan boundary.

    This is deliberately two dimensional. IsPointInRoom tests the room's
    3D volume, which depends on its base offset, its upper limit and its
    limit offset - all of which can put a perfectly sensible picked point
    outside the room and reject every candidate, which is exactly how
    picking came to select nothing at all."""
    loops = _room_loops_xy(room, loop_cache)
    if not loops:
        return False
    return point_in_loops_xy(x, y, loops)


def find_linked_room_at_point(links, host_point, room_cache, loop_cache=None):
    """Finds the linked room containing host_point.

    Clicking a linked room directly is not something Revit reliably allows
    - a room in a link is generally not selectable however visible it is -
    so the room is resolved from a picked point instead.

    The point is transformed into each link's own coordinates and tested
    against the room's plan boundary in 2D, so the room's vertical extent
    and the Z the point happened to be picked at are both irrelevant.

    room_cache is keyed by link instance id and loop_cache by room, both
    filled on first use so repeated clicks do not re-read the model.
    Returns (link_instance, room) or (None, None)."""
    if loop_cache is None:
        loop_cache = {}

    for link, link_doc in links:
        try:
            inverse = link.GetTotalTransform().Inverse
            local_point = inverse.OfPoint(host_point)
        except Exception:
            continue

        key = eid_value(link.Id)
        if key not in room_cache:
            room_cache[key] = collect_link_rooms(link_doc)

        for room in room_cache[key]:
            # Cheap rejection first - the plan boundary walk is the
            # expensive part and most rooms are nowhere near the click.
            try:
                bbox = room.get_BoundingBox(None)
                if bbox is not None:
                    if not (bbox.Min.X <= local_point.X <= bbox.Max.X and
                            bbox.Min.Y <= local_point.Y <= bbox.Max.Y):
                        continue
            except Exception:
                pass

            try:
                if room_contains_point_xy(room, local_point.X, local_point.Y,
                                          loop_cache):
                    return link, room
            except Exception:
                continue

    return None, None


def list_all_linked_rooms(doc):
    """Every room available to place a space from - this model's own rooms
    first, then every room in every loaded link - as a list of dicts,
    sorted by source, then level elevation, then room number.

    This backs the 'From List' route, which does not depend on picking
    working at all - visibility, phasing and view type can each stop a
    click from resolving, and none of them affect reading the model."""
    result = []

    for room in get_rooms(doc, "all_project", None):
        try:
            level_name = room.Level.Name
        except Exception:
            level_name = ""
        elevation = level_elevation(room.Level) or 0.0
        number = get_room_number(room)
        name = get_element_name(room)
        result.append({
            "link": None,
            "link_title": "This model",
            "room": room,
            "room_id": room.Id,
            "level": level_name,
            "elevation": elevation,
            "number": number,
            "name": name,
        })

    for link, link_doc in get_loaded_link_instances(doc):
        try:
            title = link_doc.Title
        except Exception:
            title = "link"
        for room in collect_link_rooms(link_doc):
            try:
                level_name = room.Level.Name
            except Exception:
                level_name = ""
            elevation = level_elevation(room.Level) or 0.0
            number = get_room_number(room)
            name = get_element_name(room)
            result.append({
                "link": link,
                "link_title": title,
                "room": room,
                "room_id": room.Id,
                "level": level_name,
                "elevation": elevation,
                "number": number,
                "name": name,
            })

    result.sort(key=lambda r: ((r["link_title"] or "").lower(),
                               r["elevation"],
                               _natural_key(r["number"]),
                               (r["name"] or "").lower()))
    return result


def _natural_key(text):
    """Sorts 'R10' after 'R9' rather than before it."""
    parts = []
    digits = ""
    for char in (text or ""):
        if char.isdigit():
            digits += char
        else:
            if digits:
                parts.append((1, int(digits), ""))
                digits = ""
            parts.append((0, 0, char.lower()))
    if digits:
        parts.append((1, int(digits), ""))
    return parts


def _view_level_elevation(view):
    """The elevation of the level a plan view is associated with, or None."""
    try:
        level = view.GenLevel
        if level is not None:
            return level_elevation(level)
    except Exception:
        pass
    return None


def get_linked_room_records(doc, scope, active_view):
    """Every room in every loaded link, as records carrying the host-space
    location point alongside the room and its link.

    This exists because in an MEP model the rooms usually are not in the
    model at all - they are in the architectural link - so an automatic
    run that only collects host rooms finds nothing to do.

    With scope 'current_view' the records are narrowed to the level the
    view is associated with, which is the closest sensible reading of
    'this view' for an element that lives in another document."""
    records = []
    for link, link_doc in get_loaded_link_instances(doc):
        try:
            transform = link.GetTotalTransform()
        except Exception:
            continue
        try:
            title = link_doc.Title
        except Exception:
            title = "link"

        for room in collect_link_rooms(link_doc):
            try:
                host_point = transform.OfPoint(room.Location.Point)
            except Exception:
                continue
            try:
                level_name = room.Level.Name
            except Exception:
                level_name = ""
            records.append({
                "link": link,
                "link_title": title,
                "room": room,
                "transform": transform,
                "host_point": host_point,
                "level": level_name,
            })

    if scope == "current_view":
        elevation = _view_level_elevation(active_view)
        if elevation is not None:
            records = [r for r in records
                       if abs(r["host_point"].Z - elevation) <= LEVEL_BUCKET]

    return records


def linked_records_without_spaces(doc, records, spaces=None):
    """The linked-room equivalent of rooms_without_spaces.

    Space points are in host coordinates and the room's boundary is in the
    link's, so each candidate point is pushed back through the link's
    inverse transform before the plan test rather than the other way
    round - transforming one point is cheaper than transforming a whole
    boundary."""
    if spaces is None:
        spaces = get_all_spaces(doc)

    buckets = _space_points_by_level(spaces)
    loop_cache = {}

    unplaced = []
    placed = []

    for record in records:
        host_elevation = record["host_point"].Z
        key = int(round(host_elevation / LEVEL_BUCKET))
        candidates = []
        for offset in (-1, 0, 1):
            candidates.extend(buckets.get(key + offset, []))

        if not candidates:
            unplaced.append(record)
            continue

        try:
            inverse = record["transform"].Inverse
        except Exception:
            unplaced.append(record)
            continue

        has_space = False
        for point in candidates:
            try:
                local_point = inverse.OfPoint(point)
                if room_contains_point_xy(record["room"], local_point.X,
                                          local_point.Y, loop_cache):
                    has_space = True
                    break
            except Exception:
                continue

        if has_space:
            placed.append(record)
        else:
            unplaced.append(record)

    return unplaced, placed


def get_element_name(element):
    """Reads an element's name without going through `element.Name`.

    `Element.Name` is not reliably readable through IronPython - on some
    Revit and engine combinations it raises `AttributeError: Name`, which
    is exactly what stopped every picked room from reaching the list:
    `.Area` worked, 408 rooms were found, and every single one was
    discarded on `room.Name`.

    The built-in parameter is asked first because it is the value Revit
    itself shows, then the property descriptor route, then the plain
    attribute, then a lookup by name."""
    try:
        param = element.get_Parameter(BuiltInParameter.ROOM_NAME)
        if param is not None:
            value = param.AsString()
            if value:
                return value
    except Exception:
        pass
    try:
        value = Element.Name.GetValue(element)
        if value:
            return value
    except Exception:
        pass
    try:
        value = element.Name
        if value:
            return value
    except Exception:
        pass
    try:
        param = element.LookupParameter("Name")
        if param is not None:
            return param.AsString() or ""
    except Exception:
        pass
    return ""


def get_room_number(element):
    """The same treatment for the room or space number."""
    try:
        param = element.get_Parameter(BuiltInParameter.ROOM_NUMBER)
        if param is not None:
            value = param.AsString()
            if value:
                return value
    except Exception:
        pass
    try:
        value = element.Number
        if value:
            return value
    except Exception:
        pass
    try:
        param = element.LookupParameter("Number")
        if param is not None:
            return param.AsString() or ""
    except Exception:
        pass
    return ""


def set_element_name(element, value):
    """Writes a name back, by parameter first for the same reason."""
    if not value:
        return False
    try:
        param = element.get_Parameter(BuiltInParameter.ROOM_NAME)
        if param is not None and not param.IsReadOnly:
            param.Set(value)
            return True
    except Exception:
        pass
    try:
        element.Name = value
        return True
    except Exception:
        pass
    try:
        Element.Name.SetValue(element, value)
        return True
    except Exception:
        pass
    return False


PICK_LOG_PATH = os.path.join(APPDATA_DIR, "space_creator_pick.log")

# Anything registered here receives every log line as well as the file, so
# the window can show the same record the log file gets.
_LOG_SINKS = []


def add_log_sink(callback):
    if callback not in _LOG_SINKS:
        _LOG_SINKS.append(callback)


def clear_log_sinks():
    del _LOG_SINKS[:]


def log_pick(message):
    """Appends a line to the pick log and to any registered sink. Every
    step of a selection session is logged, because a session that quietly
    does nothing is otherwise impossible to explain after the fact."""
    try:
        if not os.path.isdir(APPDATA_DIR):
            os.makedirs(APPDATA_DIR)
    except Exception:
        pass
    try:
        import datetime
        stamp = datetime.datetime.now().strftime("%H:%M:%S")
    except Exception:
        stamp = ""
    text = stamp + "  " + str(message)
    try:
        handle = io.open(PICK_LOG_PATH, "a", encoding="utf-8")
        handle.write(_to_unicode(text + "\n"))
        handle.close()
    except Exception:
        pass
    for sink in list(_LOG_SINKS):
        try:
            sink(text)
        except Exception:
            continue


def _safe(call, default=""):
    try:
        value = call()
        return value if value is not None else default
    except Exception as ex:
        return "<error: " + str(ex) + ">"


def diagnose_rooms(doc, active_view, source_key="all"):
    """A plain-language account of what the tool can and cannot see.

    Written because three separate attempts at picking rooms failed for
    three different reasons, none of which were visible from inside Revit.
    Anything that can stop a room being found is reported here rather than
    guessed at."""
    lines = []

    lines.append("ACTIVE VIEW")
    lines.append("  Name: " + str(_safe(lambda: active_view.Name)))
    lines.append("  Type: " + str(_safe(lambda: str(active_view.ViewType))))
    lines.append("  Template applied: " +
                 str(_safe(lambda: eid_value(active_view.ViewTemplateId) > 0)))
    lines.append("  Detail level: " + str(_safe(lambda: str(active_view.DetailLevel))))
    try:
        level = active_view.GenLevel
        lines.append("  Associated level: " +
                     (level.Name if level is not None else "none (not a plan view)"))
    except Exception:
        lines.append("  Associated level: none (not a plan view)")
    lines.append("")

    lines.append("ROOMS IN THIS MODEL")
    host_rooms = get_rooms(doc, "all_project", None)
    lines.append("  Placed rooms found: " + str(len(host_rooms)))
    lines.append("")

    lines.append("REVIT LINKS")
    try:
        from Autodesk.Revit.DB import RevitLinkInstance
        all_links = list(FilteredElementCollector(doc).OfClass(RevitLinkInstance))
    except Exception as ex:
        all_links = []
        lines.append("  Could not list links: " + str(ex))

    lines.append("  Link instances in the model: " + str(len(all_links)))

    loaded = get_loaded_link_instances(doc)
    lines.append("  Of those, with a loaded document: " + str(len(loaded)))
    if len(all_links) and not loaded:
        lines.append("  >> Every link is unloaded. Rooms cannot be read from an")
        lines.append("     unloaded link - reload it in Manage > Manage Links.")
    lines.append("")

    total_link_rooms = 0
    for link, link_doc in loaded:
        title = _safe(lambda: link_doc.Title, "link")
        lines.append("  LINK: " + str(title))
        lines.append("    Link instance id: " + str(eid_value(link.Id)))

        try:
            raw = list(FilteredElementCollector(link_doc)
                       .OfCategory(BuiltInCategory.OST_Rooms)
                       .WhereElementIsNotElementType())
        except Exception as ex:
            raw = []
            lines.append("    Could not collect rooms: " + str(ex))

        placed = collect_link_rooms(link_doc)
        total_link_rooms += len(placed)

        lines.append("    Room elements of any kind: " + str(len(raw)))
        lines.append("    Placed rooms (area greater than zero): " + str(len(placed)))

        if raw and not placed:
            lines.append("    >> Rooms exist but none are placed or enclosed.")
            lines.append("       An unplaced or unenclosed room has no area and")
            lines.append("       cannot have a space made from it.")

        for room in placed[:3]:
            name = get_element_name(room) or "(unnamed)"
            try:
                point = link.GetTotalTransform().OfPoint(room.Location.Point)
                where = ("host X " + str(int(point.X * 304.8)) +
                         "mm, Y " + str(int(point.Y * 304.8)) +
                         "mm, Z " + str(int(point.Z * 304.8)) + "mm")
            except Exception as ex:
                where = "no location (" + str(ex) + ")"
            lines.append("      e.g. " + str(name) + " at " + where)
        lines.append("")

    lines.append("SELECTED SOURCE")
    sources = filter_sources(get_room_sources(doc), source_key)
    if not sources:
        lines.append("  The chosen source no longer exists - reopen the tool.")
    for source in sources:
        lines.append("  " + str(source["label"]))
    lines.append("")

    lines.append("SUMMARY")
    lines.append("  Rooms available to this model: " + str(len(host_rooms)))
    lines.append("  Rooms available across loaded links: " + str(total_link_rooms))
    if len(host_rooms) + total_link_rooms == 0:
        lines.append("  >> Nothing can be selected because no placed rooms were")
        lines.append("     found anywhere. This is a model question, not a view")
        lines.append("     question - visibility settings cannot affect it.")
    else:
        lines.append("  Rooms were found, so From List will work even if")
        lines.append("  selecting in the view does not.")
    lines.append("")
    lines.append("Log file: " + PICK_LOG_PATH)

    return lines


def space_visibility_warning(doc, view):
    """Whether Spaces and Space Separation lines are actually visible in
    this view.

    A space that is created but hidden is indistinguishable from a space
    that was never created, and a coordination view very often has the
    Spaces category turned off. Returns a warning string, or ''."""
    hidden = []
    names = [("Spaces", "OST_MEPSpaces"),
             ("Space separation lines", "OST_MEPSpaceSeparationLines")]
    for label, member_name in names:
        member = getattr(BuiltInCategory, member_name, None)
        if member is None:
            continue
        try:
            category = Category.GetCategory(doc, member)
            if category is None:
                continue
            if view.GetCategoryHidden(category.Id):
                hidden.append(label)
        except Exception:
            continue

    if not hidden:
        return ""
    return (" / ".join(hidden) +
            " are HIDDEN in this view - anything created will not be "
            "visible here until the category is turned on in "
            "Visibility/Graphics.")


class WarningSwallower(IFailuresPreprocessor):
    """Deletes warnings raised during a run.

    'Space is not in a properly enclosed region' is a warning, not an
    error - Revit still creates the space. Left unhandled it stops the run
    with a dialog per space, which on a batch is unusable. The run reports
    which spaces came out unenclosed instead, which is the same
    information without four hundred dialogs."""

    def PreprocessFailures(self, accessor):
        try:
            accessor.DeleteAllWarnings()
        except Exception:
            pass
        return FailureProcessingResult.Continue


def apply_warning_suppression(transaction):
    """Attaches the warning swallower to a started transaction."""
    try:
        options = transaction.GetFailureHandlingOptions()
        options.SetFailuresPreprocessor(WarningSwallower())
        options.SetClearAfterRollback(True)
        transaction.SetFailureHandlingOptions(options)
        return True
    except Exception:
        return False


def space_is_enclosed(space):
    """A space with no area is one Revit could not bound. Only meaningful
    after a regeneration."""
    try:
        return space.Area > 0
    except Exception:
        return False


def find_separation_lines_in_loops(doc, loops_xy, elevation, tolerance=2.0):
    """Space separation line ids whose midpoint falls inside the given
    plan boundary at roughly the given elevation.

    Used to clear the perimeter around a room before redrawing it, or to
    undo a run. The midpoint is tested rather than the endpoints because a
    line shared between two rooms sits exactly on the boundary, and its
    ends coincide with neighbouring loops."""
    found = []
    if not loops_xy:
        return found
    try:
        collector = FilteredElementCollector(doc) \
            .OfCategory(BuiltInCategory.OST_MEPSpaceSeparationLines) \
            .WhereElementIsNotElementType()
    except Exception:
        return found

    for element in collector:
        try:
            curve = element.GeometryCurve
            if curve is None:
                continue
            midpoint = curve.Evaluate(0.5, True)
        except Exception:
            continue
        if elevation is not None:
            try:
                if abs(midpoint.Z - elevation) > tolerance:
                    continue
            except Exception:
                pass
        try:
            if point_in_loops_xy(midpoint.X, midpoint.Y, loops_xy):
                found.append(element.Id)
        except Exception:
            continue
    return found


def delete_separation_lines_for_records(doc, records):
    """Deletes the space separation lines lying inside each record's room.
    Records carry room, link/transform and the level. Returns
    (deleted_count, error_or_None). Must be called inside a transaction."""
    ids = []
    seen = set()
    for record in records:
        room = record.get("room")
        link = record.get("link")
        level = record.get("level")
        elevation = level_elevation(level)

        loops_xy = []
        try:
            if link is None:
                for points in _room_loops_xy(room):
                    loops_xy.append(points)
            else:
                transform = record.get("transform")
                for curves in linked_room_curve_loops(room, transform):
                    points = []
                    for curve in curves:
                        try:
                            for point in curve.Tessellate():
                                points.append((point.X, point.Y))
                        except Exception:
                            continue
                    if len(points) >= 3:
                        loops_xy.append(points)
        except Exception:
            continue

        for line_id in find_separation_lines_in_loops(doc, loops_xy, elevation):
            key = eid_value(line_id)
            if key not in seen:
                seen.add(key)
                ids.append(line_id)

    deleted = 0
    error = None
    for line_id in ids:
        try:
            doc.Delete(line_id)
            deleted += 1
        except Exception as ex:
            if error is None:
                error = str(ex)
    return deleted, error


MM_PER_FOOT = 304.8


def mm(feet):
    try:
        return int(round(feet * MM_PER_FOOT))
    except Exception:
        return 0


def feet(millimetres):
    return float(millimetres) / MM_PER_FOOT


def _space_param(space, bip, fallback_name):
    param = None
    try:
        param = space.get_Parameter(bip)
    except Exception:
        param = None
    if param is None:
        try:
            param = space.LookupParameter(fallback_name)
        except Exception:
            param = None
    return param


def space_row(doc, space):
    """Everything the management grid shows for one space, in one dict.
    Distances are in millimetres, elevations in feet (internal)."""
    row = {
        "id": space.Id,
        "id_value": eid_value(space.Id),
        "number": get_room_number(space),
        "name": get_element_name(space),
        "level": "",
        "level_elev": 0.0,
        "upper_level": "",
        "upper_level_id": None,
        "upper_level_elev": None,
        "base_offset": 0,
        "limit_offset": 0,
        "height": 0,
        "area": 0.0,
        "point": None,
        "bbox": None,
        "pending_base": None,
        "pending_limit": None,
        "pending_upper_id": None,
        "pending_upper": "",
        "status": "",
        "flag": "",
    }

    try:
        level = space.Level
        row["level"] = get_element_name(level)
        row["level_elev"] = level_elevation(level) or 0.0
    except Exception:
        pass

    param = _space_param(space, BuiltInParameter.ROOM_UPPER_LEVEL, "Upper Limit")
    if param is not None:
        try:
            upper_id = param.AsElementId()
            upper = doc.GetElement(upper_id)
            if upper is not None:
                row["upper_level"] = get_element_name(upper)
                row["upper_level_id"] = upper_id
                row["upper_level_elev"] = level_elevation(upper)
        except Exception:
            pass

    param = _space_param(space, BuiltInParameter.ROOM_LOWER_OFFSET, "Base Offset")
    if param is not None:
        try:
            row["base_offset"] = mm(param.AsDouble())
        except Exception:
            pass

    param = _space_param(space, BuiltInParameter.ROOM_UPPER_OFFSET, "Limit Offset")
    if param is not None:
        try:
            row["limit_offset"] = mm(param.AsDouble())
        except Exception:
            pass

    param = _space_param(space, BuiltInParameter.ROOM_HEIGHT, "Unbounded Height")
    if param is not None:
        try:
            row["height"] = mm(param.AsDouble())
        except Exception:
            pass

    try:
        row["area"] = round(space.Area * 0.09290304, 1)
    except Exception:
        pass

    try:
        row["point"] = space.Location.Point
    except Exception:
        pass
    try:
        row["bbox"] = space.get_BoundingBox(None)
    except Exception:
        pass

    return row


def all_space_rows(doc):
    rows = []
    try:
        collector = FilteredElementCollector(doc) \
            .OfCategory(BuiltInCategory.OST_MEPSpaces).WhereElementIsNotElementType()
        for space in collector:
            try:
                rows.append(space_row(doc, space))
            except Exception:
                continue
    except Exception:
        pass
    rows.sort(key=lambda r: (r["level_elev"], _natural_key(r["number"]),
                             (r["name"] or "").lower()))
    return rows


def space_base_elevation(row):
    return row["level_elev"] + feet(row["base_offset"])


def space_top_elevation(row):
    upper = row["upper_level_elev"]
    if upper is None:
        upper = row["level_elev"]
    return upper + feet(row["limit_offset"])


def collect_floor_boxes(doc):
    """Every floor's bounding box, once, so pushing many spaces does not
    re-collect the floors for each."""
    boxes = []
    if Floor is None:
        return boxes
    try:
        for floor in FilteredElementCollector(doc).OfClass(Floor):
            try:
                bbox = floor.get_BoundingBox(None)
                if bbox is not None:
                    boxes.append(bbox)
            except Exception:
                continue
    except Exception:
        pass
    return boxes


def _xy_inside(bbox, point):
    return (bbox.Min.X <= point.X <= bbox.Max.X and
            bbox.Min.Y <= point.Y <= bbox.Max.Y)


MIN_PUSH_GAIN = 0.05            # ft; below this a push is a no-op
SPACE_ABOVE_GAP = 0.0           # ft; how far below a space above to stop


def compute_push_target(row, floor_boxes, all_rows):
    """Works out how far up a space can go. Returns (new_limit_offset_mm,
    new_top_elev, reason_or_None). The reason, when present, is why it
    was NOT possible - the caller flags the row with it.

    The target is the lowest of:
    - the underside of the nearest floor above the space's base point;
    - the base of the nearest space stacked above it, so no space is
      pushed up into another.
    """
    point = row["point"]
    if point is None:
        return None, None, "no location point"

    base = space_base_elevation(row)
    current_top = space_top_elevation(row)

    floor_underside = None
    for bbox in floor_boxes:
        if not _xy_inside(bbox, point):
            continue
        underside = bbox.Min.Z
        if underside <= base + 0.5:
            continue                      # the floor it stands on, or below
        if floor_underside is None or underside < floor_underside:
            floor_underside = underside

    if floor_underside is None:
        return None, None, "no floor found above"

    space_above = None
    for other in all_rows:
        if other["id_value"] == row["id_value"]:
            continue
        other_base = space_base_elevation(other)
        if other_base <= base + 0.5:
            continue
        other_box = other["bbox"]
        if other_box is None or not _xy_inside(other_box, point):
            continue
        if space_above is None or other_base < space_above:
            space_above = other_base

    target = floor_underside
    reason = None
    if space_above is not None and space_above < target:
        target = space_above - SPACE_ABOVE_GAP

    if target <= base + 0.5:
        return None, None, "nothing above to extend to"

    if abs(target - current_top) < MIN_PUSH_GAIN:
        return None, None, "already at that height"

    # Express it as a limit offset from the space's own level, so the
    # upper limit is the level the space is on and the offset carries the
    # height. That is the form that survives a level rename or reorder.
    new_limit = mm(target - row["level_elev"])
    return new_limit, target, reason


def apply_space_edit(doc, row, level_by_name):
    """Writes a row's pending values onto its space and reads them back.
    Returns (ok, message). Must be called inside a transaction."""
    space = doc.GetElement(row["id"])
    if space is None:
        return False, "space no longer exists"

    changes = []

    if row["pending_upper_id"] is not None:
        param = _space_param(space, BuiltInParameter.ROOM_UPPER_LEVEL, "Upper Limit")
        if param is None or param.IsReadOnly:
            return False, "Upper Limit is not writable"
        try:
            param.Set(row["pending_upper_id"])
            changes.append("upper limit -> " + str(row["pending_upper"]))
        except Exception as ex:
            return False, "Upper Limit refused: " + str(ex)

    if row["pending_base"] is not None:
        param = _space_param(space, BuiltInParameter.ROOM_LOWER_OFFSET, "Base Offset")
        if param is None or param.IsReadOnly:
            return False, "Base Offset is not writable"
        try:
            param.Set(feet(row["pending_base"]))
            changes.append("base " + str(row["base_offset"]) + " -> " +
                           str(row["pending_base"]) + "mm")
        except Exception as ex:
            return False, "Base Offset refused: " + str(ex)

    if row["pending_limit"] is not None:
        param = _space_param(space, BuiltInParameter.ROOM_UPPER_OFFSET, "Limit Offset")
        if param is None or param.IsReadOnly:
            return False, "Limit Offset is not writable"
        try:
            param.Set(feet(row["pending_limit"]))
            changes.append("limit " + str(row["limit_offset"]) + " -> " +
                           str(row["pending_limit"]) + "mm")
        except Exception as ex:
            return False, "Limit Offset refused: " + str(ex)

    return True, "; ".join(changes) if changes else "no change"


def verify_space_edit(doc, row):
    """Reads the space back after the commit and compares against what was
    asked. A void Set() is not evidence. Returns (ok, message)."""
    space = doc.GetElement(row["id"])
    if space is None:
        return False, "space gone after write"
    fresh = space_row(doc, space)
    problems = []
    if row["pending_base"] is not None and \
            abs(fresh["base_offset"] - row["pending_base"]) > 1:
        problems.append("base read back " + str(fresh["base_offset"]))
    if row["pending_limit"] is not None and \
            abs(fresh["limit_offset"] - row["pending_limit"]) > 1:
        problems.append("limit read back " + str(fresh["limit_offset"]))
    if row["pending_upper_id"] is not None and \
            eid_value(fresh["upper_level_id"]) != eid_value(row["pending_upper_id"]):
        problems.append("upper limit read back " + str(fresh["upper_level"]))
    if problems:
        return False, "; ".join(problems)
    return True, "verified"


def get_room_sources(doc):
    """The places rooms can be read from: this model, then every loaded
    link. Returned as dicts so the UI can show a label and hand the choice
    straight back.

    key is 'host' for this document or the link instance's id value."""
    sources = [{
        "key": "host",
        "label": "This model",
        "link": None,
        "link_doc": doc,
    }]
    for link, link_doc in get_loaded_link_instances(doc):
        try:
            title = link_doc.Title
        except Exception:
            title = "link"
        sources.append({
            "key": eid_value(link.Id),
            "label": title,
            "link": link,
            "link_doc": link_doc,
        })
    return sources


def filter_sources(sources, key):
    """key is 'all', 'host', or a link instance id value."""
    if key == "all":
        return list(sources)
    return [s for s in sources if s["key"] == key]


def _room_host_point(room, link):
    """A room's location point in host coordinates."""
    try:
        point = room.Location.Point
    except Exception:
        return None
    if link is None:
        return point
    try:
        return link.GetTotalTransform().OfPoint(point)
    except Exception:
        return None


BOX_CLICK_TOLERANCE = 0.02      # ft; below this a drag is really a click


LEVEL_BAND = 4.0        # ft; fallback band when a view range cannot be read
BAND_PADDING = 1.0      # ft; slack added to a view range for base offsets


def view_level_elevation(view):
    """The elevation of the level a plan view is associated with, or None
    for a view that has no level (a 3D view, a section)."""
    try:
        level = view.GenLevel
        if level is not None:
            return level_elevation(level)
    except Exception:
        pass
    return None


def view_elevation_band(view):
    """The band of elevations a plan view actually shows, read from its
    **view range**, as (low, high). Either end may be None, meaning
    unbounded.

    The view's own level is not good enough. A coordination plan is
    routinely set to a level high above the rooms it displays - a roof
    level view at 109.8m showing rooms four storeys down - and filtering
    to the level elevation throws away everything on screen. The view
    range is what decides what the view draws, so it is what decides what
    can be selected in it."""
    try:
        from Autodesk.Revit.DB import ViewPlan, PlanViewPlane
    except Exception:
        return None, None
    try:
        if not isinstance(view, ViewPlan):
            return None, None
    except Exception:
        return None, None

    try:
        view_range = view.GetViewRange()
        view_doc = view.Document
    except Exception:
        return None, None

    def plane_elevation(plane):
        try:
            level_id = view_range.GetLevelId(plane)
            offset = view_range.GetOffset(plane)
            level = view_doc.GetElement(level_id)
            if level is None:
                return None
            base = level_elevation(level)
            return None if base is None else base + offset
        except Exception:
            return None

    top = plane_elevation(getattr(PlanViewPlane, "TopClipPlane", None))
    bottom = plane_elevation(getattr(PlanViewPlane, "BottomClipPlane", None))
    depth = plane_elevation(getattr(PlanViewPlane, "ViewDepthPlane", None))

    lows = [value for value in (bottom, depth) if value is not None]
    low = min(lows) if lows else None

    if low is not None:
        low = low - BAND_PADDING
    if top is not None:
        top = top + BAND_PADDING
    return low, top


def band_for_view(view):
    """The elevation band to select within: the view range if it can be
    read, else the view's level plus or minus LEVEL_BAND, else unbounded."""
    low, high = view_elevation_band(view)
    if low is not None or high is not None:
        return low, high
    elevation = view_level_elevation(view)
    if elevation is None:
        return None, None
    return elevation - LEVEL_BAND, elevation + LEVEL_BAND


def band_for_elevation(elevation):
    if elevation is None:
        return None, None
    return elevation - LEVEL_BAND, elevation + LEVEL_BAND


def describe_band(band):
    low, high = band
    if low is None and high is None:
        return "every level"
    def mm(value):
        return "unbounded" if value is None else str(int(value * 304.8)) + "mm"
    return mm(low) + " to " + mm(high)


def _room_elevation(room, link):
    """A room's elevation in host coordinates."""
    point = _room_host_point(room, link)
    if point is not None:
        return point.Z
    try:
        elevation = level_elevation(room.Level)
    except Exception:
        return None
    if elevation is None:
        return None
    if link is None:
        return elevation
    try:
        return link.GetTotalTransform().OfPoint(XYZ(0, 0, elevation)).Z
    except Exception:
        return elevation


def _in_band(room, link, band):
    """Whether a room sits inside the elevation band being selected in.

    Without this the plan test matches every floor at once, because rooms
    stack vertically and the test is deliberately two dimensional: two
    clicks a few millimetres apart returned a room on level 00 and a room
    on level 04."""
    if band is None:
        return True
    low, high = band
    if low is None and high is None:
        return True
    elevation = _room_elevation(room, link)
    if elevation is None:
        return True
    if low is not None and elevation < low:
        return False
    if high is not None and elevation > high:
        return False
    return True


def get_source_levels(sources):
    """Every level across the chosen sources as (label, host_elevation),
    sorted by elevation, so a level can be picked by hand when the view
    range is not the filter wanted."""
    try:
        from Autodesk.Revit.DB import Level as LevelClass
    except Exception:
        return []

    seen = {}
    for source in sources:
        link = source["link"]
        try:
            levels = FilteredElementCollector(source["link_doc"]).OfClass(LevelClass)
        except Exception:
            continue
        for level in levels:
            elevation = level_elevation(level)
            if elevation is None:
                continue
            if link is not None:
                try:
                    elevation = link.GetTotalTransform().OfPoint(
                        XYZ(0, 0, elevation)).Z
                except Exception:
                    pass
            name = get_element_name(level) or "Level"
            key = int(round(elevation * 1000.0))
            if key not in seen:
                seen[key] = (name, elevation)

    result = list(seen.values())
    result.sort(key=lambda pair: pair[1])
    return result


def rooms_in_box(sources, min_point, max_point, room_cache=None,
                 loop_cache=None, band=None):
    """Every room selected by a plan rectangle, across the given sources.
    Returns a list of (link_or_None, room).

    Two things count as selected:

    - a room whose **location point** falls inside the rectangle, which is
      the normal case for a box thrown around several rooms;
    - the room **containing the centre** of the rectangle, which catches a
      small box dragged *inside* one large room. Without this, dragging a
      box within a single room selects nothing, because the room's
      location point is outside the little rectangle.

    When a band is given, only rooms within that elevation range are
    eligible.

    Selecting by rectangle sidesteps pickability entirely: a room is not a
    pickable element in Revit, but a rectangle is a pair of coordinates
    and the rooms it covers can be worked out directly."""
    if room_cache is None:
        room_cache = {}
    if loop_cache is None:
        loop_cache = {}

    low_x = min(min_point.X, max_point.X)
    high_x = max(min_point.X, max_point.X)
    low_y = min(min_point.Y, max_point.Y)
    high_y = max(min_point.Y, max_point.Y)

    found = []
    seen = set()

    for source in sources:
        key = source["key"]
        if key not in room_cache:
            if source["link"] is None:
                room_cache[key] = get_rooms(source["link_doc"], "all_project", None)
            else:
                room_cache[key] = collect_link_rooms(source["link_doc"])

        for room in room_cache[key]:
            if not _in_band(room, source["link"], band):
                continue
            point = _room_host_point(room, source["link"])
            if point is None:
                continue
            if low_x <= point.X <= high_x and low_y <= point.Y <= high_y:
                marker = (key, eid_value(room.Id))
                if marker not in seen:
                    seen.add(marker)
                    found.append((source["link"], room))

    centre = XYZ((low_x + high_x) / 2.0, (low_y + high_y) / 2.0, 0.0)
    link, room = find_room_in_sources(sources, centre, room_cache, loop_cache,
                                      band)
    if room is not None:
        source_key = "host"
        if link is not None:
            source_key = eid_value(link.Id)
        marker = (source_key, eid_value(room.Id))
        if marker not in seen:
            found.append((link, room))

    return found


def is_click_not_box(min_point, max_point):
    return (abs(max_point.X - min_point.X) < BOX_CLICK_TOLERANCE and
            abs(max_point.Y - min_point.Y) < BOX_CLICK_TOLERANCE)


def find_room_in_sources(sources, host_point, room_cache=None,
                         loop_cache=None, band=None):
    """Point-in-room across the given sources, for a click rather than a
    drag. Returns (link_or_None, room_or_None).

    Where more than one room still contains the point - rooms stack, and
    the boundary test is two dimensional - the **highest** one inside the
    band wins, which is the storey a plan view is showing. Returning the
    first match found is what put a level 04 room in the list from a click
    on a level 00 plan."""
    if room_cache is None:
        room_cache = {}
    if loop_cache is None:
        loop_cache = {}

    best = (None, None)
    best_gap = None

    for source in sources:
        key = source["key"]
        if key not in room_cache:
            if source["link"] is None:
                room_cache[key] = get_rooms(source["link_doc"], "all_project", None)
            else:
                room_cache[key] = collect_link_rooms(source["link_doc"])

        link = source["link"]
        local_point = host_point
        if link is not None:
            try:
                local_point = link.GetTotalTransform().Inverse.OfPoint(host_point)
            except Exception:
                continue

        for room in room_cache[key]:
            if not _in_band(room, link, band):
                continue
            try:
                bbox = room.get_BoundingBox(None)
                if bbox is not None:
                    if not (bbox.Min.X <= local_point.X <= bbox.Max.X and
                            bbox.Min.Y <= local_point.Y <= bbox.Max.Y):
                        continue
            except Exception:
                pass
            try:
                if not room_contains_point_xy(room, local_point.X,
                                              local_point.Y, loop_cache):
                    continue
            except Exception:
                continue

            # Where several rooms still contain the point, the highest
            # one wins: a plan view shows the storey you are standing on,
            # not the ones beneath it.
            elevation = _room_elevation(room, link)
            if elevation is None:
                return link, room
            if best_gap is None or elevation > best_gap:
                best_gap = elevation
                best = (link, room)

    return best


def count_rooms_in_sources(sources, room_cache=None):
    """How many rooms the chosen sources hold.

    Fills room_cache as it goes: the count used to collect every room and
    throw the result away, so the first box or click then collected them
    all over again."""
    total = 0
    for source in sources:
        key = source["key"]
        if room_cache is not None and key in room_cache:
            total += len(room_cache[key])
            continue
        if source["link"] is None:
            rooms = get_rooms(source["link_doc"], "all_project", None)
        else:
            rooms = collect_link_rooms(source["link_doc"])
        if room_cache is not None:
            room_cache[key] = rooms
        total += len(rooms)
    return total


def find_room_at_point(doc, links, host_point, host_rooms, room_cache,
                       loop_cache=None):
    """Finds the room containing host_point, looking in **this model first
    and then in the links**.

    The manual picker originally searched links only, on the assumption
    that the rooms always live in the architectural link. That is usually
    true and it is not always true - a model with copy/monitored or
    natively modelled rooms would never resolve a click, however visible
    and correct everything else was.

    Returns (link_instance_or_None, room_or_None). A None link means the
    room is in this document.
    """
    if loop_cache is None:
        loop_cache = {}

    # --- this model ---------------------------------------------------
    for room in (host_rooms or []):
        try:
            bbox = room.get_BoundingBox(None)
            if bbox is not None:
                if not (bbox.Min.X <= host_point.X <= bbox.Max.X and
                        bbox.Min.Y <= host_point.Y <= bbox.Max.Y):
                    continue
        except Exception:
            pass
        try:
            if room_contains_point_xy(room, host_point.X, host_point.Y,
                                      loop_cache):
                return None, room
        except Exception:
            continue

    # --- the links ----------------------------------------------------
    link, room = find_linked_room_at_point(links, host_point, room_cache,
                                           loop_cache)
    return link, room


def diagnose_point_miss(links, host_point, host_rooms, room_cache):
    """Explains why a click matched nothing.

    A miss can mean no rooms were found at all, or that rooms were found
    but the click was nowhere near them, or that it was right next to one -
    which points at a coordinate problem rather than a user aiming
    problem. Saying which removes the guesswork."""
    host_count = len(host_rooms or [])
    link_count = 0
    nearest_name = None
    nearest_distance = None

    def consider(room, x, y, label):
        try:
            point = room.Location.Point
        except Exception:
            return None, None
        distance = (((point.X - x) ** 2) + ((point.Y - y) ** 2)) ** 0.5
        name = get_element_name(room) or "(unnamed)"
        return name + label, distance

    for room in (host_rooms or []):
        name, distance = consider(room, host_point.X, host_point.Y, "")
        if distance is not None and (nearest_distance is None or
                                     distance < nearest_distance):
            nearest_distance = distance
            nearest_name = name

    for link, link_doc in links:
        key = eid_value(link.Id)
        if key not in room_cache:
            room_cache[key] = collect_link_rooms(link_doc)
        rooms = room_cache[key]
        link_count += len(rooms)
        try:
            inverse = link.GetTotalTransform().Inverse
            local_point = inverse.OfPoint(host_point)
        except Exception:
            continue
        for room in rooms:
            name, distance = consider(room, local_point.X, local_point.Y,
                                      " (in link)")
            if distance is not None and (nearest_distance is None or
                                         distance < nearest_distance):
                nearest_distance = distance
                nearest_name = name

    total = host_count + link_count
    if total == 0:
        return ("No rooms were found at all - " + str(len(links)) +
                " loaded link(s), 0 rooms in this model.")

    parts = [str(total) + " room(s) known (" + str(host_count) +
             " here, " + str(link_count) + " in links)"]
    if nearest_name is not None and nearest_distance is not None:
        parts.append("nearest is " + nearest_name + " about " +
                     str(int(nearest_distance * 304.8)) + "mm away")
    return "; ".join(parts) + "."


def linked_room_curve_loops(room, transform):
    """Room boundary loops pulled out of a linked room and transformed into
    host coordinates. Returns a list of lists of Curve."""
    options = SpatialElementBoundaryOptions()
    try:
        loops = room.GetBoundarySegments(options)
    except Exception:
        return []
    if not loops:
        return []

    curve_loops = []
    for loop in loops:
        curves = []
        for segment in loop:
            try:
                curves.append(segment.GetCurve().CreateTransformed(transform))
            except Exception:
                continue
        if curves:
            curve_loops.append(curves)
    return curve_loops


def _room_location_point(room):
    try:
        loc = room.Location
        return loc.Point
    except Exception:
        return None


def _get_last_phase(doc):
    """The document's last (most recent) phase - used as a fallback for
    Space creation where a Level-based placement is refused."""
    try:
        phases = doc.Phases
        count = phases.Size
        if count > 0:
            return phases.get_Item(count - 1)
    except Exception:
        pass
    return None


def create_space_at_point(doc, level, point_xyz, phase=None):
    """Creates a Space at point_xyz. Tries the Level overload first, then
    falls back to the Phase overload (the document's last phase, unless one
    is supplied) if that is refused - some Revit releases and some project
    phasing setups reject one or the other. Returns (space_or_None,
    error_message_or_None) - callers should surface the message rather than
    swallow it, since a silently-returned None reads as "nothing happened"
    with no way to tell why."""
    if point_xyz is None:
        return None, "no location point"

    uv = UV(point_xyz.X, point_xyz.Y)
    errors = []

    if level is not None:
        try:
            space = doc.Create.NewSpace(level, uv)
            if space is not None:
                return space, None
        except Exception as ex:
            errors.append("level: " + str(ex))

    use_phase = phase if phase is not None else _get_last_phase(doc)
    if use_phase is not None:
        try:
            space = doc.Create.NewSpace(use_phase, uv)
            if space is not None:
                return space, None
        except Exception as ex:
            errors.append("phase: " + str(ex))
    else:
        errors.append("no document phase available")

    return None, "; ".join(errors) if errors else "NewSpace returned nothing"


def create_space_for_room(doc, room):
    """Creates a Space at the room's location point, on the room's level.
    Returns (space_or_None, error_message_or_None)."""
    point = _room_location_point(room)
    level = None
    try:
        level = room.Level
    except Exception:
        pass
    return create_space_at_point(doc, level, point)


def inherit_name_from_room(space, room):
    """Both sides go through the safe helpers - reading a room's name and
    writing a space's name are equally unreliable as plain attributes."""
    name = get_element_name(room)
    if not name:
        return False
    return set_element_name(space, name)


# ---------------------------------------------------------------------------
# Push space to underside of floor above
# ---------------------------------------------------------------------------

def _sorted_levels(doc):
    levels = list(FilteredElementCollector(doc).OfClass(Level))
    levels.sort(key=lambda l: level_elevation(l) or 0.0)
    return levels


def _level_above(doc, level):
    levels = _sorted_levels(doc)
    for lvl in levels:
        if (level_elevation(lvl) or 0.0) > (level_elevation(level) or 0.0) + 0.01 \
                and eid_value(lvl.Id) != eid_value(level.Id):
            return lvl
    return None


def _floor_underside_near_point(doc, upper_level, point_xyz):
    """Best-effort search for the floor on / near upper_level whose plan
    footprint contains point_xyz, returning its lowest elevation (bottom of
    the floor solid). Uses a bounding-box test against the point, which is
    an approximation for non-rectangular floors but never over-states the
    underside height by more than the floor's own bounding box."""
    if Floor is None or upper_level is None:
        return None
    best = None
    try:
        collector = FilteredElementCollector(doc, upper_level.Id).OfClass(Floor)
    except Exception:
        collector = FilteredElementCollector(doc).OfClass(Floor)
    for floor in collector:
        try:
            bbox = floor.get_BoundingBox(None)
            if bbox is None:
                continue
            if not (bbox.Min.X <= point_xyz.X <= bbox.Max.X and
                    bbox.Min.Y <= point_xyz.Y <= bbox.Max.Y):
                continue
            underside = bbox.Min.Z
            if best is None or underside < best:
                best = underside
        except Exception:
            continue
    return best


def push_space_to_ceiling_underside_at(doc, space, level, point):
    """Sets the space's Upper Limit / Limit Offset so it extends to the
    underside of the floor above. Takes an explicit host level and host
    point rather than a room, so it works for a linked room too - a linked
    room's own Level belongs to the link document, not to the levels being
    searched here. Returns (success, message)."""
    if level is None:
        return False, "no level"
    if point is None:
        return False, "no location point"

    upper_level = _level_above(doc, level)
    if upper_level is None:
        return False, "no level above"

    underside = _floor_underside_near_point(doc, upper_level, point)
    if underside is None:
        return False, "no floor found above"

    upper_limit_param = space.get_Parameter(BuiltInParameter.ROOM_UPPER_LEVEL)
    offset_param = space.get_Parameter(BuiltInParameter.ROOM_UPPER_OFFSET)
    if upper_limit_param is None:
        upper_limit_param = space.LookupParameter("Upper Limit")
    if offset_param is None:
        offset_param = space.LookupParameter("Limit Offset")

    if upper_limit_param is None or offset_param is None:
        return False, "upper limit parameters not found"

    try:
        upper_limit_param.Set(upper_level.Id)
        offset = underside - (level_elevation(upper_level) or 0.0)
        offset_param.Set(offset)
        return True, "set to underside of floor on " + upper_level.Name
    except Exception as ex:
        return False, "failed: " + str(ex)


def push_space_to_ceiling_underside(doc, space, room):
    """Wrapper for a room in this document."""
    try:
        level = room.Level
    except Exception:
        return False, "no level"
    try:
        point = room.Location.Point
    except Exception:
        return False, "no location point"
    return push_space_to_ceiling_underside_at(doc, space, level, point)
