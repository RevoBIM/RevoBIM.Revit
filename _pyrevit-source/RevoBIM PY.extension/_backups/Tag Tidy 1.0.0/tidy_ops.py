# -*- coding: utf-8 -*-
"""Everything that touches the model: picking the tags, measuring them,
collecting what is in the way, writing the layout and reading it back.

Every decision is made in tidy_core; this module only converts between Revit
and the paper-millimetre frame the engine works in, and moves things.
"""

import tidy_clr  # noqa: F401  assemblies first, always

from Autodesk.Revit.DB import (XYZ, Transaction, TransactionGroup, TransactionStatus,
                               ElementId, IndependentTag, SpatialElementTag,
                               BuiltInCategory, BuiltInParameter, FilteredElementCollector,
                               LocationPoint, LocationCurve, WorksharingUtils, CheckoutStatus,
                               ModelUpdatesStatus, LeaderEndCondition, RevitLinkInstance,
                               Outline, BoundingBoxIntersectsFilter, ElementTransformUtils,
                               CurveElement, Line, IFailuresPreprocessor,
                               FailureProcessingResult, FailureSeverity)
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter

import tidy_core as core

eid_value = core.eid_value


# ============================================================================
# selection
# ============================================================================

class TagFilter(ISelectionFilter):
    """Tags only, so a stray pipe cannot get into the pick."""

    def __init__(self, include_spatial):
        self.include_spatial = include_spatial

    def AllowElement(self, element):
        try:
            if isinstance(element, IndependentTag):
                return True
            if self.include_spatial and isinstance(element, SpatialElementTag):
                return True
        except Exception:
            pass
        return False

    def AllowReference(self, reference, point):
        return False


def gather_tags(uidoc, cfg):
    """Whatever is selected, filtered to tags.  Nothing selected asks for them.
    Returns (tags, how many selected things were not tags, message)."""
    doc = uidoc.Document
    tags = []
    others = 0
    for element_id in uidoc.Selection.GetElementIds():
        element = doc.GetElement(element_id)
        if isinstance(element, IndependentTag) or isinstance(element, SpatialElementTag):
            tags.append(element)
        else:
            others += 1
    if tags:
        return tags, others, None

    if not core.as_bool(cfg, "prompt_when_empty"):
        return [], others, "No tags were selected."

    try:
        picked = uidoc.Selection.PickObjects(
            ObjectType.Element, TagFilter(core.as_bool(cfg, "include_spatial_tags")),
            "Pick the tags to tidy, then Finish")
    except Exception:
        return [], others, None  # Escape: leave without a word
    for reference in picked:
        element = doc.GetElement(reference.ElementId)
        if element is not None:
            tags.append(element)
    return tags, others, None


# ============================================================================
# small conversions
# ============================================================================

def xyz_t(point):
    return (point.X, point.Y, point.Z)


def t_xyz(values):
    return XYZ(values[0], values[1], values[2])


def view_scale(view):
    try:
        scale = view.Scale
        if scale and scale > 0:
            return scale
    except Exception:
        pass
    return 100


BAD_VIEW_TYPES = ("ThreeD", "DraftingView", "Schedule", "ColumnSchedule", "PanelSchedule",
                  "Legend", "Walkthrough", "Rendering", "Report", "CostReport",
                  "LoadsReport", "PresureLossReport", "SystemBrowser", "ProjectBrowser",
                  "Internal", "Undefined", "DrawingSheet", "SystemsAnalysisReport")


def view_ok(view):
    if view is None:
        return False
    try:
        if str(view.ViewType) in BAD_VIEW_TYPES:
            return False
        right = view.RightDirection
        up = view.UpDirection
        return right.GetLength() > 1e-9 and up.GetLength() > 1e-9
    except Exception:
        return False


def frame_for(view):
    return core.Frame(xyz_t(view.Origin), xyz_t(view.RightDirection),
                      xyz_t(view.UpDirection), view_scale(view))


def bic(name):
    """A BuiltInCategory by name, or None on a release that lacks it."""
    return getattr(BuiltInCategory, name, None)


def bic_int(value):
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        pass
    try:
        return int(value.value__)
    except Exception:
        return None


def category_name(element):
    try:
        return element.Category.Name
    except Exception:
        return "Element"


def category_value(element):
    try:
        return eid_value(element.Category.Id)
    except Exception:
        return None


def box_corners(box):
    """The eight corners of a BoundingBoxXYZ, through its own transform."""
    low, high = box.Min, box.Max
    try:
        transform = box.Transform
    except Exception:
        transform = None
    out = []
    for x in (low.X, high.X):
        for y in (low.Y, high.Y):
            for z in (low.Z, high.Z):
                point = XYZ(x, y, z)
                if transform is not None:
                    try:
                        point = transform.OfPoint(point)
                    except Exception:
                        pass
                out.append(point)
    return out


def paper_box(frame, box, transform=None):
    points = []
    for corner in box_corners(box):
        if transform is not None:
            corner = transform.OfPoint(corner)
        points.append(frame.to_paper(xyz_t(corner)))
    return core.box_of_points(points)


# ============================================================================
# one tag, as read out of Revit
# ============================================================================

class Entry(object):

    def __init__(self, tag, view, spatial, verdict):
        self.tag = tag
        self.view = view
        self.key = eid_value(tag.Id)
        self.spatial = spatial
        self.verdict = verdict
        self.frame = frame_for(view)
        self.refs = [None] if spatial else tagged_references(tag)
        self.has_leader = has_leader(tag)
        self.label = label_for(tag)
        self.own = own_keys(tag, spatial)
        # filled by measuring
        self.head = None          # model XYZ
        self.head_uv = None
        self.depth = 0.0
        self.rel = None
        self.rel_estimated = False
        self.ends = []            # model XYZ per reference, or None
        self.anchors_uv = []
        self.converted = False    # attached end switched to free while measuring
        self.was_free = False
        self.elbows_now = []      # paper (u, v) per reference, or None

    def tag_input(self):
        elbows = None
        if self.has_leader and len(self.elbows_now) == len(self.anchors_uv):
            elbows = list(self.elbows_now)
        return core.TagInput(self.key, self.label, self.head_uv, self.rel, self.anchors_uv,
                             own=self.own, current_elbows=elbows,
                             has_leader=self.has_leader)


def tagged_references(tag):
    """Every leader on the tag.  Multi-reference tags arrived in 2022; the
    single-leader route is kept for anything that will not answer."""
    try:
        refs = list(tag.GetTaggedReferences())
        if refs:
            return refs
    except Exception:
        pass
    return [None]


def has_leader(tag):
    try:
        return bool(tag.HasLeader)
    except Exception:
        return True


def label_for(tag):
    text = ""
    try:
        text = tag.TagText or ""
    except Exception:
        text = ""
    text = text.splitlines()[0].strip() if text else ""
    if not text:
        try:
            text = tag.Name
        except Exception:
            text = "Tag"
    if len(text) > 32:
        text = text[:30] + "..."
    return "{0}  [{1}]".format(text, eid_value(tag.Id))


def own_keys(tag, spatial):
    """The obstacle keys a tag may touch: the elements it tags."""
    keys = set()
    if spatial:
        for name in ("Room", "Space", "Area"):
            try:
                element = getattr(tag, name)
                if element is not None:
                    keys.add(eid_value(element.Id))
            except Exception:
                pass
        return keys
    try:
        for element_id in tag.GetTaggedLocalElementIds():
            keys.add(eid_value(element_id))
    except Exception:
        pass
    for reference in tagged_references(tag):
        if reference is None:
            continue
        try:
            linked = reference.LinkedElementId
            if linked is not None and eid_value(linked) > 0:
                keys.add(("link", eid_value(reference.ElementId), eid_value(linked)))
            else:
                keys.add(eid_value(reference.ElementId))
        except Exception:
            pass
    return keys


def head_of(tag, spatial):
    try:
        point = tag.TagHeadPosition
        if point is not None:
            return point
    except Exception:
        pass
    if spatial:
        try:
            location = tag.Location
            if isinstance(location, LocationPoint):
                return location.Point
        except Exception:
            pass
    return None


def workshare_flags(doc, element_id):
    owned = False
    updated = False
    try:
        if not doc.IsWorkshared:
            return False, False
    except Exception:
        return False, False
    try:
        owned = WorksharingUtils.GetCheckoutStatus(doc, element_id) == CheckoutStatus.OwnedByOtherUser
    except Exception:
        owned = False
    try:
        updated = (WorksharingUtils.GetModelUpdatesStatus(doc, element_id) ==
                   ModelUpdatesStatus.UpdatedInCentral)
    except Exception:
        updated = False
    return owned, updated


def in_group(tag):
    try:
        return eid_value(tag.GroupId) > 0
    except Exception:
        return False


class Row(object):

    def __init__(self, kind, label, note):
        self.kind = kind
        self.label = label
        self.note = note

    def as_tuple(self):
        return (self.kind, self.label, self.note)


def prepare(doc, tags, cfg):
    """Sort the selection into tags to move and tags to leave, with reasons."""
    entries = []
    rows = []
    for tag in tags:
        spatial = isinstance(tag, SpatialElementTag)
        try:
            view = doc.GetElement(tag.OwnerViewId)
        except Exception:
            view = None
        owned, updated = workshare_flags(doc, tag.Id)
        pinned = False
        try:
            pinned = bool(tag.Pinned)
        except Exception:
            pinned = False
        info = {
            "view_ok": view_ok(view),
            "has_leader": has_leader(tag),
            "pinned": pinned,
            "owned_by_other": owned,
            "updated_in_central": updated,
            "in_group": in_group(tag),
            "spatial": spatial,
        }
        verdict = core.eligibility(info, cfg)
        if not verdict["ok"]:
            rows.append(Row("skip", label_for(tag), verdict["reason"]))
            continue
        try:
            entries.append(Entry(tag, view, spatial, verdict))
        except Exception as error:
            rows.append(Row("fail", label_for(tag), "could not be read: {0}".format(error)))
    return entries, rows


# ============================================================================
# where a leader lands when Revit will not say
# ============================================================================

def target_points(doc, tag, reference, spatial):
    """Model points of what the tag points at: one point, or the run of a
    curve.  Used for a tag with no leader yet, and as a last resort."""
    try:
        if spatial:
            for name in ("Room", "Space", "Area"):
                element = getattr(tag, name, None)
                if element is not None:
                    location = element.Location
                    if isinstance(location, LocationPoint):
                        return [location.Point]
            return []

        source = doc
        transform = None
        element = None
        if reference is not None:
            linked = None
            try:
                linked = reference.LinkedElementId
            except Exception:
                linked = None
            if linked is not None and eid_value(linked) > 0:
                link = doc.GetElement(reference.ElementId)
                source = link.GetLinkDocument()
                transform = link.GetTotalTransform()
                element = source.GetElement(linked)
            else:
                element = doc.GetElement(reference.ElementId)
        if element is None:
            ids = list(tag.GetTaggedLocalElementIds())
            if ids:
                element = doc.GetElement(ids[0])
        if element is None:
            return []

        points = []
        location = getattr(element, "Location", None)
        if isinstance(location, LocationPoint):
            points = [location.Point]
        elif isinstance(location, LocationCurve):
            points = curve_points(location.Curve)
        if not points:
            box = element.get_BoundingBox(None)
            if box is not None:
                points = [(box.Min + box.Max) / 2.0]
        if transform is not None:
            points = [transform.OfPoint(point) for point in points]
        return points
    except Exception:
        return []


def curve_points(curve):
    try:
        if isinstance(curve, Line):
            return [curve.GetEndPoint(0), curve.GetEndPoint(1)]
    except Exception:
        pass
    try:
        points = list(curve.Tessellate())
        if len(points) > 24:
            step = len(points) / 24.0
            points = [points[int(i * step)] for i in range(24)] + [points[-1]]
        return points
    except Exception:
        pass
    try:
        return [curve.GetEndPoint(0), curve.GetEndPoint(1)]
    except Exception:
        return []


def nearest_on(points_uv, target):
    """The point on a polyline nearest `target`, all in paper."""
    if len(points_uv) == 1:
        return points_uv[0]
    best = None
    best_d = None
    for a, b in zip(points_uv[:-1], points_uv[1:]):
        ab = core.sub(b, a)
        size = core.dot(ab, ab)
        t = 0.0 if size < 1e-12 else max(0.0, min(1.0, core.dot(core.sub(target, a), ab) / size))
        point = (a[0] + ab[0] * t, a[1] + ab[1] * t)
        d = core.dist(point, target)
        if best_d is None or d < best_d:
            best, best_d = point, d
    return best


# ============================================================================
# measuring, inside a transaction that is always rolled back
# ============================================================================

class QuietWarnings(IFailuresPreprocessor):
    """Warnings raised while measuring or writing tags are noise; errors are
    left alone for Revit to handle."""

    def PreprocessFailures(self, accessor):
        try:
            for failure in accessor.GetFailureMessages():
                if failure.GetSeverity() == FailureSeverity.Warning:
                    accessor.DeleteWarning(failure)
        except Exception:
            pass
        return FailureProcessingResult.Continue


def _quiet(transaction):
    try:
        options = transaction.GetFailureHandlingOptions()
        options.SetFailuresPreprocessor(QuietWarnings())
        options.SetClearAfterRollback(True)
        transaction.SetFailureHandlingOptions(options)
    except Exception:
        pass


def measure(doc, entries):
    """Read every entry's head, its outline with its leader switched off, the
    far end of every leader and its current elbows.

    A tag's bounding box includes its leader, which is the thing being moved,
    so the leaders are switched off to read the tag alone.  An attached leader
    end cannot be read through the API, so it is switched to a free end, which
    Revit puts exactly where the attached end was, and read from there.  All
    of it happens in a transaction that is rolled back, which leaves the model
    exactly as it was.
    """
    transaction = Transaction(doc, "RevoBIM Tag Tidy - measuring")
    _quiet(transaction)
    transaction.Start()
    try:
        _measure_inside(doc, entries)
    finally:
        try:
            transaction.RollBack()
        except Exception:
            pass


def _measure_inside(doc, entries):
    for e in entries:
        # read afresh: when verifying, a leader may have just been switched on
        e.has_leader = has_leader(e.tag)
        e.ends = [None] * len(e.refs)
        e.elbows_now = [None] * len(e.refs)
        e.converted = False
        e.was_free = False
        e.head = head_of(e.tag, e.spatial)
        if e.head is not None:
            e.depth = e.frame.depth_of(xyz_t(e.head))
            e.head_uv = e.frame.to_paper(xyz_t(e.head))
        if not e.has_leader:
            continue
        for index, reference in enumerate(e.refs):
            elbow = read_elbow(e.tag, reference, e.spatial)
            if elbow is not None:
                e.elbows_now[index] = e.frame.to_paper(xyz_t(elbow))
        if e.spatial:
            e.was_free = True
            continue
        try:
            attached = e.tag.LeaderEndCondition == LeaderEndCondition.Attached
        except Exception:
            attached = False
        e.was_free = not attached
        if attached:
            try:
                e.tag.LeaderEndCondition = LeaderEndCondition.Free
                e.converted = True
            except Exception:
                e.converted = False
    doc.Regenerate()

    for e in entries:
        if e.has_leader:
            for index, reference in enumerate(e.refs):
                e.ends[index] = read_end(e.tag, reference, e.spatial)
        for index, reference in enumerate(e.refs):
            if e.ends[index] is None:
                points = target_points(doc, e.tag, reference, e.spatial)
                if points and e.head_uv is not None:
                    uv = nearest_on([e.frame.to_paper(xyz_t(p)) for p in points], e.head_uv)
                    e.ends[index] = t_xyz(e.frame.to_model(uv[0], uv[1], e.depth))
        if e.has_leader:
            try:
                e.tag.HasLeader = False
            except Exception:
                pass
    doc.Regenerate()

    for e in entries:
        if e.head is None:
            continue
        e.rel = None
        try:
            box = e.tag.get_BoundingBox(e.view)
            if box is not None:
                b = paper_box(e.frame, box)
                e.rel = (b[0] - e.head_uv[0], b[1] - e.head_uv[1],
                         b[2] - e.head_uv[0], b[3] - e.head_uv[1])
        except Exception:
            e.rel = None
        if e.rel is None or (e.rel[2] - e.rel[0]) < 0.2 or (e.rel[3] - e.rel[1]) < 0.2:
            e.rel = (0.0, -1.5, 15.0, 1.5)
            e.rel_estimated = True
        e.anchors_uv = [e.frame.to_paper(xyz_t(end)) for end in e.ends if end is not None]


def read_end(tag, reference, spatial):
    if not spatial and reference is not None:
        try:
            point = tag.GetLeaderEnd(reference)
            if point is not None:
                return point
        except Exception:
            pass
    try:
        point = tag.LeaderEnd
        if point is not None:
            return point
    except Exception:
        pass
    return None


def read_elbow(tag, reference, spatial):
    if not spatial and reference is not None:
        try:
            if tag.HasLeaderElbow(reference):
                return tag.GetLeaderElbow(reference)
        except Exception:
            pass
    for name in ("LeaderElbow", "LeaderElbowPosition"):
        try:
            point = getattr(tag, name)
            if point is not None:
                return point
        except Exception:
            pass
    return None


# ============================================================================
# what is in the way
# ============================================================================

LINEAR = (
    ("obs_pipes", ("OST_PipeCurves", "OST_FlexPipeCurves", "OST_PipeInsulations")),
    ("obs_ducts", ("OST_DuctCurves", "OST_FlexDuctCurves", "OST_DuctInsulations")),
    ("obs_trays", ("OST_CableTray",)),
    ("obs_conduit", ("OST_Conduit",)),
    ("obs_walls", ("OST_Walls",)),
    ("obs_grids", ("OST_Grids",)),
)

BOXED = (
    ("obs_pipes", ("OST_PipeFitting", "OST_PipeAccessory", "OST_PlumbingFixtures",
                   "OST_Sprinklers")),
    ("obs_ducts", ("OST_DuctFitting", "OST_DuctAccessory", "OST_DuctTerminal")),
    ("obs_trays", ("OST_CableTrayFitting",)),
    ("obs_conduit", ("OST_ConduitFitting",)),
)

OTHER_SKIP = ("OST_Rooms", "OST_MEPSpaces", "OST_Areas", "OST_Floors", "OST_Ceilings",
              "OST_Roofs", "OST_Levels", "OST_VolumeOfInterest", "OST_Cameras",
              "OST_Viewers", "OST_SectionBox", "OST_RvtLinks", "OST_HVAC_Zones",
              "OST_Topography", "OST_Toposolid", "OST_Site", "OST_Mass")

SOFT_ANNOTATION = ("OST_Lines", "OST_FilledRegion", "OST_DetailComponents_Hidden")

WIDTHS = ("RBS_PIPE_OUTER_DIAMETER", "RBS_PIPE_DIAMETER_PARAM", "RBS_CURVE_WIDTH_PARAM",
          "RBS_CURVE_DIAMETER_PARAM", "RBS_CABLETRAY_WIDTH_PARAM",
          "RBS_CONDUIT_OUTER_DIAM_PARAM", "WALL_ATTR_WIDTH_PARAM",
          "RBS_INSULATION_THICKNESS_FOR_DUCT")
HEIGHTS = ("RBS_CURVE_HEIGHT_PARAM", "RBS_CABLETRAY_HEIGHT_PARAM")


def _param_double(element, name):
    bip = getattr(BuiltInParameter, name, None)
    if bip is None:
        return 0.0
    try:
        parameter = element.get_Parameter(bip)
        if parameter is not None:
            return parameter.AsDouble() or 0.0
    except Exception:
        pass
    return 0.0


def thickness_ft(element, plan):
    """How thick a linear element is drawn: its width or diameter, or in a
    section the larger of width and height, since either may face the view."""
    width = 0.0
    for name in WIDTHS:
        width = max(width, _param_double(element, name))
    try:
        width = max(width, float(element.Width))
    except Exception:
        pass
    if not plan:
        for name in HEIGHTS:
            width = max(width, _param_double(element, name))
    return width


def _enabled(cfg, groups):
    out = []
    for key, names in groups:
        if not core.as_bool(cfg, key):
            continue
        for name in names:
            value = bic(name)
            if value is not None:
                out.append(value)
    return out


def _too_big(box, crop, limit):
    width = box[2] - box[0]
    height = box[3] - box[1]
    if crop is not None:
        return width > 0.9 * (crop[2] - crop[0]) and height > 0.9 * (crop[3] - crop[1])
    return width > limit and height > limit


def region_outline(frame, region, transform=None):
    """An Outline in model (or link) coordinates round a paper region, deep
    enough along the view direction to catch everything the view shows."""
    points = []
    for u in (region[0], region[2]):
        for v in (region[1], region[3]):
            for depth in (-5000.0, 5000.0):
                point = t_xyz(frame.to_model(u, v, depth))
                if transform is not None:
                    point = transform.Inverse.OfPoint(point)
                points.append(point)
    low = XYZ(min(p.X for p in points), min(p.Y for p in points), min(p.Z for p in points))
    high = XYZ(max(p.X for p in points), max(p.Y for p in points), max(p.Z for p in points))
    return Outline(low, high)


def collect_obstacles(doc, view, frame, cfg, moving_ids, region, crop):
    """Everything in this view a tag or a leader should keep off, as engine
    obstacles.  The tags being moved are left out; tags that stay put are in."""
    obstacles = []
    plan = abs(frame.depth[2]) > 0.9
    soft_annotation = set(bic_int(bic(name)) for name in SOFT_ANNOTATION)
    outline = None
    try:
        outline = region_outline(frame, region)
    except Exception:
        outline = None

    # annotation: everything this view owns
    if core.as_bool(cfg, "obs_annotation"):
        try:
            owned = FilteredElementCollector(doc, view.Id).OwnedByView(view.Id) \
                .WhereElementIsNotElementType()
        except Exception:
            owned = []
        for element in owned:
            try:
                value = eid_value(element.Id)
                if value in moving_ids or element.Category is None:
                    continue
                label = "{0} {1}".format(category_name(element), value)
                category = category_value(element)
                if isinstance(element, CurveElement):
                    for a, b in _segments(frame, curve_points(element.GeometryCurve)):
                        obstacles.append(core.Obstacle("seg", (a, b), False, label, key=value,
                                                       radius=0.2, group="model"))
                    continue
                box = element.get_BoundingBox(view)
                if box is None:
                    continue
                pb = paper_box(frame, box)
                if _too_big(pb, crop, 400.0) or not core.box_overlap(pb, region):
                    continue
                hard = category not in soft_annotation
                obstacles.append(core.Obstacle("box", pb, hard, label, key=value,
                                               group="annotation" if hard else "model"))
            except Exception:
                continue

    # model: linear elements as thick lines, the rest as boxes
    for value in _enabled(cfg, LINEAR):
        for element in _model_collector(doc, view, value, outline):
            obstacles.extend(_linear(frame, element, plan, crop))
    for value in _enabled(cfg, BOXED):
        for element in _model_collector(doc, view, value, outline):
            obstacles.extend(_boxed(frame, view, element, crop, region))
    if core.as_bool(cfg, "obs_other"):
        obstacles.extend(_everything_else(doc, view, frame, cfg, crop, region, outline))
    if core.as_bool(cfg, "obs_links"):
        obstacles.extend(_linked(doc, view, frame, cfg, plan, crop, region))
    return obstacles


def _model_collector(doc, view, category, outline, source=None):
    """Elements of one category: those visible in the view, or for a link
    document (which knows nothing of this view) those inside the outline."""
    try:
        if source is None:
            collector = FilteredElementCollector(doc, view.Id)
        else:
            collector = FilteredElementCollector(source)
        collector = collector.OfCategory(category).WhereElementIsNotElementType()
        if outline is not None:
            collector = collector.WherePasses(BoundingBoxIntersectsFilter(outline))
        return list(collector)
    except Exception:
        if source is not None:
            return []
        try:
            return list(FilteredElementCollector(doc, view.Id).OfCategory(category)
                        .WhereElementIsNotElementType())
        except Exception:
            return []


def _segments(frame, points, transform=None):
    uv = []
    for point in points:
        if transform is not None:
            point = transform.OfPoint(point)
        uv.append(frame.to_paper(xyz_t(point)))
    if len(uv) == 1:
        return [(uv[0], uv[0])]
    return list(zip(uv[:-1], uv[1:]))


def _linear(frame, element, plan, crop, transform=None, prefix="", key=None):
    try:
        curve = None
        location = getattr(element, "Location", None)
        if isinstance(location, LocationCurve):
            curve = location.Curve
        if curve is None:
            curve = getattr(element, "Curve", None)
        if curve is None:
            return []
        value = key if key is not None else eid_value(element.Id)
        label = "{0}{1} {2}".format(prefix, category_name(element), eid_value(element.Id))
        radius = frame.length_to_paper(thickness_ft(element, plan)) / 2.0
        out = []
        for a, b in _segments(frame, curve_points(curve), transform):
            out.append(core.Obstacle("seg", (a, b), False, label, key=value, radius=radius,
                                     group="model"))
        return out
    except Exception:
        return []


def _boxed(frame, view, element, crop, region, transform=None, prefix="", key=None):
    try:
        box = element.get_BoundingBox(view if transform is None else None)
        if box is None:
            return []
        pb = paper_box(frame, box, transform)
        if _too_big(pb, crop, 2000.0) or not core.box_overlap(pb, region):
            return []
        value = key if key is not None else eid_value(element.Id)
        label = "{0}{1} {2}".format(prefix, category_name(element), eid_value(element.Id))
        return [core.Obstacle("box", pb, False, label, key=value, group="model")]
    except Exception:
        return []


def _everything_else(doc, view, frame, cfg, crop, region, outline):
    taken = set(bic_int(v) for v in _enabled(dict((k, "1") for k, _ in LINEAR + BOXED),
                                             LINEAR + BOXED))
    skip = set(bic_int(bic(name)) for name in OTHER_SKIP)
    out = []
    try:
        collector = FilteredElementCollector(doc, view.Id).WhereElementIsNotElementType()
        if outline is not None:
            collector = collector.WherePasses(BoundingBoxIntersectsFilter(outline))
    except Exception:
        return out
    for element in collector:
        try:
            if element.ViewSpecific or element.Category is None:
                continue
            category = category_value(element)
            if category in taken or category in skip:
                continue
            out.extend(_boxed(frame, view, element, crop, region))
        except Exception:
            continue
    return out


def _linked(doc, view, frame, cfg, plan, crop, region):
    """Linked model elements, read from each link document within the region.
    The link documents know nothing of this view's visibility settings, so a
    linked element hidden in the view still counts here."""
    out = []
    try:
        links = list(FilteredElementCollector(doc, view.Id).OfClass(RevitLinkInstance))
    except Exception:
        return out
    for link in links:
        try:
            source = link.GetLinkDocument()
            if source is None:
                continue
            transform = link.GetTotalTransform()
            outline = region_outline(frame, region, transform)
            link_id = eid_value(link.Id)
            for value in _enabled(cfg, LINEAR):
                for element in _model_collector(doc, view, value, outline, source):
                    key = ("link", link_id, eid_value(element.Id))
                    out.extend(_linear(frame, element, plan, crop, transform, "Linked ", key))
            for value in _enabled(cfg, BOXED):
                for element in _model_collector(doc, view, value, outline, source):
                    key = ("link", link_id, eid_value(element.Id))
                    out.extend(_boxed(frame, view, element, crop, region, transform,
                                      "Linked ", key))
        except Exception:
            continue
    return out


def crop_paper(view, frame):
    """The crop region in paper, or the annotation crop when that is on, or
    None when the view is not cropped."""
    try:
        if not view.CropBoxActive:
            return None
        box = view.CropBox
        transform = box.Transform
        points = []
        for x in (box.Min.X, box.Max.X):
            for y in (box.Min.Y, box.Max.Y):
                points.append(frame.to_paper(xyz_t(transform.OfPoint(XYZ(x, y, box.Min.Z)))))
        crop = core.box_of_points(points)
    except Exception:
        return None
    try:
        parameter = view.get_Parameter(BuiltInParameter.VIEWER_ANNOTATION_CROP_ACTIVE)
        if parameter is not None and parameter.AsInteger() == 1:
            manager = view.GetCropRegionShapeManager()
            # annotation crop offsets are paper distances, in feet
            crop = (crop[0] - core.ft_to_mm(manager.LeftAnnotationCropOffset),
                    crop[1] - core.ft_to_mm(manager.BottomAnnotationCropOffset),
                    crop[2] + core.ft_to_mm(manager.RightAnnotationCropOffset),
                    crop[3] + core.ft_to_mm(manager.TopAnnotationCropOffset))
    except Exception:
        pass
    return crop


# ============================================================================
# writing
# ============================================================================

def set_head(doc, entry, point):
    try:
        entry.tag.TagHeadPosition = point
        return True
    except Exception:
        pass
    try:
        ElementTransformUtils.MoveElement(doc, entry.tag.Id, point - entry.head)
        return True
    except Exception:
        return False


def set_elbow(tag, reference, point, spatial):
    errors = []
    if not spatial and reference is not None:
        try:
            tag.SetLeaderElbow(reference, point)
            return None
        except Exception as error:
            errors.append(str(error))
    for name in ("LeaderElbow", "LeaderElbowPosition"):
        try:
            setattr(tag, name, point)
            return None
        except Exception as error:
            errors.append(str(error))
    return errors[0] if errors else "Revit would not take the elbow"


def put_end_back(tag, reference, point, spatial):
    """A free leader end should not move when its tag does; put it back if a
    release moves it anyway."""
    if point is None:
        return
    now = read_end(tag, reference, spatial)
    if now is not None and now.DistanceTo(point) < core.mm_to_ft(0.05):
        return
    try:
        if not spatial and reference is not None:
            tag.SetLeaderEnd(reference, point)
        else:
            tag.LeaderEnd = point
    except Exception:
        pass


def write(doc, plans, cfg):
    """One transaction for every view.  plans is a list of (entry, placement).
    Returns {entry key: problem text} for anything Revit refused."""
    problems = {}
    transaction = Transaction(doc, "RevoBIM Tag Tidy")
    _quiet(transaction)
    transaction.Start()
    try:
        for entry, placement in plans:
            tag = entry.tag
            if entry.verdict.get("unpin"):
                try:
                    tag.Pinned = False
                except Exception:
                    pass
            if entry.verdict.get("switch_on"):
                try:
                    tag.HasLeader = True
                except Exception as error:
                    problems[entry.key] = "Revit would not switch its leader on: {0}".format(error)
            head = t_xyz(entry.frame.to_model(placement.head[0], placement.head[1], entry.depth))
            if not set_head(doc, entry, head):
                problems[entry.key] = "Revit would not move the tag"
        doc.Regenerate()

        free_mode = cfg.get("leader_end", "keep") == "free"
        for entry, placement in plans:
            tag = entry.tag
            for index, reference in enumerate(entry.refs):
                original = entry.ends[index] if index < len(entry.ends) else None
                if entry.was_free:
                    put_end_back(tag, reference, original, entry.spatial)
                elif free_mode and entry.converted and original is not None:
                    try:
                        tag.LeaderEndCondition = LeaderEndCondition.Free
                        put_end_back(tag, reference, original, entry.spatial)
                    except Exception:
                        pass
            for index, reference in enumerate(entry.refs):
                if index >= len(placement.elbows) or placement.elbows[index] is None:
                    continue
                elbow = placement.elbows[index]
                point = t_xyz(entry.frame.to_model(elbow[0], elbow[1], entry.depth))
                error = set_elbow(tag, reference, point, entry.spatial)
                if error:
                    problems[entry.key] = "Revit refused the elbow: {0}".format(error)
            if entry.verdict.get("unpin"):
                try:
                    tag.Pinned = True
                except Exception:
                    pass
        status = transaction.Commit()
        if status != TransactionStatus.Committed:
            raise RuntimeError("Revit reported {0} rather than a commit".format(status))
    except Exception:
        try:
            transaction.RollBack()
        except Exception:
            pass
        raise
    return problems


# ============================================================================
# the whole run
# ============================================================================

class ViewJob(object):
    """One view's worth: its tags, what is in the way, and the latest layout."""

    def __init__(self, view, entries):
        self.view = view
        self.entries = entries
        self.frame = entries[0].frame
        self.obstacles = []
        self.crop = None
        self.result = None
        self.pick = None
        self.actual = {}
        self.actual_clashes = []


def _region(entries, p):
    points = []
    for e in entries:
        if e.head_uv is not None:
            points.append(e.head_uv)
        points.extend(e.anchors_uv)
    region = core.box_of_points(points) if points else (-100.0, -100.0, 100.0, 100.0)
    widest = max([e.rel[2] - e.rel[0] for e in entries if e.rel] + [20.0])
    tallest = sum([e.rel[3] - e.rel[1] + p.gap for e in entries if e.rel] + [0.0])
    margin = p.max_shift + 2.0 * widest + tallest + 60.0
    return core.box_grow(region, margin)


def run(uidoc, tags, others, cfg, ui):
    doc = uidoc.Document
    p = core.Params.from_cfg(cfg)
    entries, rows = prepare(doc, tags, cfg)
    if not entries:
        ui.show_results(cfg, "Nothing was moved",
                        _detail(0, len(rows), others, 0), [r.as_tuple() for r in rows],
                        "Nothing was written.", can_flip=False, final=True)
        return

    # A point has to be picked before any transaction opens.
    pick_view = None
    pick_uv = None
    if cfg.get("side") == "point":
        active = uidoc.ActiveView
        if any(eid_value(e.view.Id) == eid_value(active.Id) for e in entries):
            try:
                point = uidoc.Selection.PickPoint("Click where the top of the column goes")
                pick_view = eid_value(active.Id)
                pick_uv = frame_for(active).to_paper(xyz_t(point))
            except Exception:
                pick_view = None

    measure(doc, entries)
    unreadable = [e for e in entries if e.head is None or not e.anchors_uv]
    for e in unreadable:
        rows.append(Row("fail", e.label, "its head or its target could not be read"))
    entries = [e for e in entries if e not in unreadable]
    if not entries:
        ui.show_results(cfg, "Nothing was moved", _detail(0, len(rows), others, 0),
                        [r.as_tuple() for r in rows], "Nothing was written.",
                        can_flip=False, final=True)
        return

    jobs = {}
    for e in entries:
        jobs.setdefault(eid_value(e.view.Id), []).append(e)
    job_list = []
    moving = set(e.key for e in entries)
    for view_key in sorted(jobs.keys()):
        job = ViewJob(jobs[view_key][0].view, jobs[view_key])
        job.crop = crop_paper(job.view, job.frame)
        job.obstacles = collect_obstacles(doc, job.view, job.frame, cfg, moving,
                                          _region(job.entries, p), job.crop)
        if pick_view == view_key:
            job.pick = pick_uv
        job_list.append(job)

    flip = None
    while True:
        for job in job_list:
            inputs = [e.tag_input() for e in job.entries]
            job.result = core.solve(inputs, job.obstacles, job.crop, p,
                                    flip=flip.get(eid_value(job.view.Id)) if flip else None,
                                    pick=job.pick)

        group = TransactionGroup(doc, "RevoBIM Tag Tidy")
        group.Start()
        try:
            plans = []
            for job in job_list:
                placed = job.result.by_key()
                for e in job.entries:
                    if e.key in placed and not placed[e.key].kept:
                        plans.append((e, placed[e.key]))
            problems = write(doc, plans, cfg)
            verify(doc, job_list, p)
        except Exception:
            try:
                group.RollBack()
            except Exception:
                pass
            raise

        report_rows = list(rows) + _rows(job_list, problems)
        needs_look = any(r.kind != "done" for r in report_rows)
        summary = _summary(job_list, report_rows)
        detail = _detail(len(plans), len(rows), others, sum(j.result.columns for j in job_list),
                         any(j.result.ran_out for j in job_list))
        preview = cfg.get("preview", "always")
        if preview == "never" or (preview == "needed" and not needs_look):
            group.Assimilate()
            _debug(cfg, job_list, report_rows, summary, detail, "kept without a preview")
            return
        try:
            uidoc.RefreshActiveView()
        except Exception:
            pass
        choice = ui.show_results(cfg, summary, detail, [r.as_tuple() for r in report_rows],
                                 "Keep to accept it as one undo step. Undo, or closing this "
                                 "window, puts every tag back.",
                                 can_flip=any(j.pick is None for j in job_list), final=False)
        _debug(cfg, job_list, report_rows, summary, detail, "preview answered: " + str(choice))
        if choice == "keep":
            group.Assimilate()
            return
        group.RollBack()
        if choice != "flip":
            return
        flip = dict((eid_value(j.view.Id), j.result.sides) for j in job_list)
        # verifying read the tags where the rolled-back layout had put them;
        # read them again where they really are before laying out again
        measure(doc, [e for job in job_list for e in job.entries])


def verify(doc, job_list, p):
    """Read back what Revit actually did and check that, not the plan."""
    all_entries = [e for job in job_list for e in job.entries]
    measure(doc, all_entries)
    for job in job_list:
        job.actual = {}
        placements = []
        for e in job.entries:
            if e.head_uv is None or not e.anchors_uv:
                continue
            tag_input = e.tag_input()
            elbows = [elbow for elbow in e.elbows_now[:len(tag_input.anchors)]]
            placement = core.actual_placement(tag_input, e.head_uv, elbows)
            job.actual[e.key] = placement
            placements.append(placement)
        job.actual_clashes = core.find_clashes(placements, core.Context(job.obstacles, job.crop, p))


def _debug(cfg, job_list, rows, summary, detail, outcome):
    """The run as plain text in %APPDATA%\\RevoBIM\\tag_tidy_debug.txt."""
    try:
        lines = ["summary: " + summary, "detail: " + detail, "outcome: " + outcome]
        for job in job_list:
            result = job.result
            lines.append("view {0} [{1}]: {2} tags, {3} obstacles, {4} columns, {5} kept, "
                         "search ran out: {6}, crop: {7}".format(
                             getattr(job.view, "Name", "?"), eid_value(job.view.Id),
                             len(job.entries), len(job.obstacles), result.columns,
                             result.kept, result.ran_out, job.crop))
        for row in rows:
            lines.append("{0}\t{1}\t{2}".format(row.kind, row.label, row.note))
        lines.append("settings: " + ", ".join(
            "{0}={1}".format(k, cfg.get(k)) for k in sorted(core.DEFAULTS.keys())))
        core.write_debug(cfg, lines)
    except Exception:
        pass


def _rows(job_list, problems):
    out = []
    for job in job_list:
        planned = job.result.by_key()
        for e in job.entries:
            placement = planned.get(e.key)
            if placement is None:
                continue
            if e.key in problems:
                out.append(Row("fail", e.label, problems[e.key]))
                continue
            actual = job.actual.get(e.key)
            clashes = [c for c in job.actual_clashes if c.key == e.key]
            note = core.describe_outcome(placement, clashes)
            if actual is not None:
                drift = core.dist(actual.head, placement.head)
                if drift > 0.5:
                    note += "; Revit put it {0:.1f}mm from where it was sent".format(drift)
            if e.verdict.get("switch_on"):
                note += "; leader switched on"
            if e.rel_estimated:
                note += "; its size could not be read, so it was estimated"
            kind = "clash" if any(c.hard for c in clashes) else "done"
            out.append(Row(kind, e.label, note))
    return out


def _summary(job_list, rows):
    kept = sum(j.result.kept for j in job_list)
    placed = sum(1 for r in rows if r.kind in ("done", "clash")) - kept
    look = sum(1 for r in rows if r.kind != "done")
    columns = sum(j.result.columns for j in job_list)
    return "{0} tag{1} stacked in {2} column{3}{4}{5}".format(
        placed, "" if placed == 1 else "s", columns, "" if columns == 1 else "s",
        ", {0} already fine and left alone".format(kept) if kept else "",
        ", {0} need{1} a look".format(look, "s" if look == 1 else "") if look else ", all clear")


def _detail(placed, skipped, others, columns, ran_out=False):
    parts = []
    if skipped:
        parts.append("{0} tag{1} left where {2}".format(
            skipped, "" if skipped == 1 else "s", "it was" if skipped == 1 else "they were"))
    if others:
        parts.append("{0} selected element{1} {2} not a tag".format(
            others, "" if others == 1 else "s", "was" if others == 1 else "were"))
    if ran_out:
        parts.append("the search hit its time limit, so this is the best it found in time")
    return ("; ".join(parts) + ".") if parts else "Every selected tag was laid out."
