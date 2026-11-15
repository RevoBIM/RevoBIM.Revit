# -*- coding: utf-8 -*-
"""RevoBIM Match Offset - everything that touches the Revit model.

Measuring is deliberately separate from writing, and both report what route
they took, because a void API call is not evidence: every write is read back
through a fresh measurement before it is called a success.

Two things here run far more often than the rest and are written for it.
ISelectionFilter.AllowElement runs on every element the cursor crosses, so it
does one attribute read against a frozenset and nothing else. And every
BuiltInCategory and BuiltInParameter member is resolved once, on first use,
rather than on every lookup - late enough that a name a release does not have
cannot kill the tool at import, but only once.
"""

import mo_clr  # noqa: F401

from Autodesk.Revit.DB import (
    BuiltInCategory, BuiltInParameter, CheckoutStatus, ElementId,
    ElementTransformUtils, FilteredElementCollector, GeometryInstance, Level,
    LocationCurve, LocationPoint, Options, PlanarFace, Solid,
    ViewDetailLevel, WorksharingUtils, XYZ,
)
from Autodesk.Revit.UI.Selection import ISelectionFilter

from mo_core import (
    CATEGORY_DEFS, EPS, FROM_BEARING, FROM_BOX, FROM_INSERTION, FROM_PARAMETERS,
    FROM_SOLID, FROM_TOP, MM_PER_FT,
    TOL_FT, anchor_value, bearing_from_members, best_bearing, eid_value,
    format_mm, ft_to_mm, host_offset_direction, is_fabrication, is_framing,
    is_hanger,
    is_point_based,
    is_upright, rod_length_after, slope_degrees, to_text,
)

try:
    from System.Collections.Generic import List
except Exception:
    List = None

# Height of a round or rectangular MEP curve, by whichever parameter the
# category actually carries.
ROUND_SIZE_PARAMS = (
    u"RBS_PIPE_OUTER_DIAMETER",
    u"RBS_CURVE_DIAMETER_PARAM",
    u"RBS_CONDUIT_OUTER_DIAM_PARAM",
    u"RBS_CONDUIT_DIAMETER_PARAM",
)
BOX_SIZE_PARAMS = (
    u"RBS_CURVE_HEIGHT_PARAM",
    u"RBS_CABLETRAY_HEIGHT_PARAM",
)
INSULATION_PARAMS = (
    u"RBS_REFERENCE_INSULATION_THICKNESS",
)
OFFSET_PARAMS = (
    u"RBS_OFFSET_PARAM",
)
# A family's height above its own level. Written as itself rather than by
# moving the family, so the number that ends up in the properties palette is
# the one worked out against the family's own level - whatever level the
# element it was matched to happens to be on.
LEVEL_OFFSET_PARAMS = (
    u"INSTANCE_ELEVATION_PARAM",
)
# A face or work plane hosted family's distance off its host. It runs along
# the host's normal, so on a ceiling it runs downward.
HOST_OFFSET_PARAMS = (
    u"INSTANCE_FREE_HOST_OFFSET_PARAM",
)
# Fabrication parts carry their own top and bottom of part - the numbers the
# shop and the installer work to, and what the properties palette shows.
FAB_BOTTOM_PARAMS = (
    u"FABRICATION_BOTTOM_OF_PART",
    u"FABRICATION_PART_BOTTOM_ELEVATION",
)
FAB_TOP_PARAMS = (
    u"FABRICATION_TOP_OF_PART",
    u"FABRICATION_PART_TOP_ELEVATION",
)
FAB_BOTTOM_NAMES = (u"Bottom of Part", u"Bottom Elevation")
FAB_TOP_NAMES = (u"Top of Part", u"Top Elevation")

LEVEL_PARAMS = (
    u"FABRICATION_LEVEL_PARAM",
    u"RBS_START_LEVEL_PARAM",
    u"FAMILY_LEVEL_PARAM",
    u"SCHEDULE_LEVEL_PARAM",
    u"INSTANCE_SCHEDULE_ONLY_LEVEL_PARAM",
    u"LEVEL_PARAM",
)

_CATEGORY_IDS = None
_POINT_IDS = None
_FAB_IDS = None
_HANGER_IDS = None

# 50mm: close enough that a parameter and the solids are describing the same
# face, far enough that a level offset mistaken for a project elevation is
# never mistaken for agreement.
AGREE_FT = 50.0 / 304.8
_BIP_CACHE = {}
_BIP_SETS = {}
_LEVELS = [None, []]      # the document the list was read from, and the list


def reset_caches():
    """Forget anything cached against a document.

    Called at the start of every run: the category map and the resolved
    enum members are true for the session, but the level elevations belong
    to one document and a second project opened in the same session must not
    inherit them.
    """
    _LEVELS[0] = None
    del _LEVELS[1][:]


# ======================================================================
# late enum lookup, resolved once
# ======================================================================

def builtin_category(name):
    try:
        return getattr(BuiltInCategory, name)
    except Exception:
        return None


def builtin_parameter(name):
    """The BuiltInParameter member, resolved on first use and kept.

    Late by name rather than at import, because a member a release does not
    have would otherwise kill the module before any of the tool ran. Kept,
    because param_by_builtin is called five or six times per element.
    """
    if name in _BIP_CACHE:
        return _BIP_CACHE[name]
    try:
        member = getattr(BuiltInParameter, name)
    except Exception:
        member = None
    _BIP_CACHE[name] = member
    return member


def builtin_parameters(names):
    """A tuple of names resolved once, with the ones this release lacks
    dropped, so the per element loop is over real members only."""
    cached = _BIP_SETS.get(names)
    if cached is not None:
        return cached
    members = tuple([m for m in [builtin_parameter(n) for n in names]
                     if m is not None])
    _BIP_SETS[names] = members
    return members


def category_id_map():
    """settings key -> the category's id as an int, built once per session."""
    global _CATEGORY_IDS
    if _CATEGORY_IDS is not None:
        return _CATEGORY_IDS
    mapping = {}
    for key, _label, bic_name, _group, _on in CATEGORY_DEFS:
        bic = builtin_category(bic_name)
        if bic is None:
            continue
        try:
            mapping[key] = eid_value(ElementId(bic))
        except Exception:
            continue
    _CATEGORY_IDS = mapping
    return mapping


def category_key_map():
    """The same map the other way round, for naming a picked element."""
    reverse = {}
    for key, value in category_id_map().items():
        reverse[value] = key
    return reverse


def point_based_ids():
    """The ids of the categories measured at their insertion point.

    A set of ints built once, for the same reason the selection filter's is:
    this is asked per element, and the answer never changes in a session.
    """
    global _POINT_IDS
    if _POINT_IDS is not None:
        return _POINT_IDS
    mapping = category_id_map()
    _POINT_IDS = frozenset([value for key, value in mapping.items()
                            if is_point_based(key)])
    return _POINT_IDS


def fabrication_ids():
    global _FAB_IDS
    if _FAB_IDS is not None:
        return _FAB_IDS
    mapping = category_id_map()
    _FAB_IDS = frozenset([v for k, v in mapping.items() if is_fabrication(k)])
    return _FAB_IDS


def hanger_ids():
    global _HANGER_IDS
    if _HANGER_IDS is not None:
        return _HANGER_IDS
    mapping = category_id_map()
    _HANGER_IDS = frozenset([v for k, v in mapping.items() if is_hanger(k)])
    return _HANGER_IDS


def is_a_fabrication_part(element):
    try:
        return eid_value(element.Category.Id) in fabrication_ids()
    except Exception:
        return False


_FRAMING_IDS = [None]


def framing_ids():
    if _FRAMING_IDS[0] is not None:
        return _FRAMING_IDS[0]
    mapping = category_id_map()
    _FRAMING_IDS[0] = frozenset([v for k, v in mapping.items()
                                 if is_framing(k)])
    return _FRAMING_IDS[0]


def is_ancillary_framing(element):
    try:
        return eid_value(element.Category.Id) in framing_ids()
    except Exception:
        return False


def is_a_support(element):
    """A hanger or a piece of support steel: something a service sits on."""
    return is_a_hanger(element) or is_ancillary_framing(element)


def is_a_hanger(element):
    try:
        return eid_value(element.Category.Id) in hanger_ids()
    except Exception:
        return False


# ======================================================================
# real geometry, rather than the bounding box
# ======================================================================

def geometry_options():
    options = Options()
    try:
        options.DetailLevel = ViewDetailLevel.Fine
        options.ComputeReferences = False
        options.IncludeNonVisibleObjects = False
    except Exception:
        pass
    return options


def solids_of(element, depth=0):
    """Every real solid in an element, following instance geometry.

    The bounding box takes in connectors, symbolic lines, insulation and
    anything else Revit calls geometry; the solids are the thing itself. An
    air terminal's box reaches out to its neck and its flange, which is why
    "bottom" off a box matched nothing anybody could see.
    """
    found = []
    if depth > 3:
        return found
    try:
        source = element.get_Geometry(geometry_options()) \
            if depth == 0 else element
    except Exception:
        return found
    if source is None:
        return found
    try:
        for item in source:
            if isinstance(item, Solid):
                try:
                    if item.Volume > EPS:
                        found.append(item)
                except Exception:
                    continue
            elif isinstance(item, GeometryInstance):
                try:
                    found.extend(solids_of(item.GetInstanceGeometry(),
                                           depth + 1))
                except Exception:
                    continue
    except Exception:
        return found
    return found


def solid_extent(element):
    """The lowest and highest point of an element's real solids."""
    low = None
    high = None
    for solid in solids_of(element):
        try:
            box = solid.GetBoundingBox()
        except Exception:
            box = None
        if box is None:
            continue
        try:
            transform = solid.GetBoundingBox().Transform
        except Exception:
            transform = None
        for corner in box_corners(box, transform):
            if low is None or corner < low:
                low = corner
            if high is None or corner > high:
                high = corner
    if low is None or high is None:
        return None
    return (low, high)


def box_corners(box, transform):
    """The eight corners of a solid's own box, in project coordinates.

    A solid's bounding box comes back in the solid's own frame with a
    transform beside it; taking Min.Z and Max.Z straight off it is right
    only when that transform happens to be the identity, which is exactly
    the sort of thing that is true in the test model and false on site.
    """
    out = []
    try:
        low, high = box.Min, box.Max
    except Exception:
        return out
    for x in (low.X, high.X):
        for y in (low.Y, high.Y):
            for z in (low.Z, high.Z):
                point = XYZ(x, y, z)
                if transform is not None:
                    try:
                        point = transform.OfPoint(point)
                    except Exception:
                        pass
                try:
                    out.append(float(point.Z))
                except Exception:
                    continue
    return out


def flat_faces(solid):
    """One solid's flat faces, as (upness, area, height)."""
    out = []
    try:
        faces = solid.Faces
    except Exception:
        return out
    for face in faces:
        if not isinstance(face, PlanarFace):
            continue
        try:
            normal = face.FaceNormal
            out.append((float(normal.Z), float(face.Area),
                        float(face.Origin.Z)))
        except Exception:
            continue
    return out


def upward_faces(element):
    """Every flat face of an element pointing up, as (upness, area, height)."""
    out = []
    for solid in solids_of(element):
        out.extend(flat_faces(solid))
    return out


def solid_frame(solid):
    """One solid's extents in project feet: low, high, plan span, plan area.

    Read through the solid's own transform, like everything else here: Min
    and Max are in the solid's frame and taking them straight is right only
    when that frame happens to be the identity.
    """
    try:
        box = solid.GetBoundingBox()
    except Exception:
        return None
    if box is None:
        return None
    try:
        transform = box.Transform
    except Exception:
        transform = None
    try:
        low, high = box.Min, box.Max
    except Exception:
        return None
    xs = []
    ys = []
    zs = []
    for x in (low.X, high.X):
        for y in (low.Y, high.Y):
            for z in (low.Z, high.Z):
                point = XYZ(x, y, z)
                if transform is not None:
                    try:
                        point = transform.OfPoint(point)
                    except Exception:
                        pass
                try:
                    xs.append(float(point.X))
                    ys.append(float(point.Y))
                    zs.append(float(point.Z))
                except Exception:
                    continue
    if not zs:
        return None
    across = max(xs) - min(xs)
    along = max(ys) - min(ys)
    return (min(zs), max(zs), max(across, along), across * along)


def hanger_members(element):
    """A hanger, one piece at a time: (low, high, span, area, faces).

    A hanger is not one shape, it is a few: rods, a bearer, sometimes an
    anchor and a backing plate. Taken as one lump there is no telling the
    top of a rod from the top of the bearer; taken a piece at a time there
    is, and that is the whole of the problem.
    """
    out = []
    for solid in solids_of(element):
        frame = solid_frame(solid)
        if frame is None:
            continue
        out.append((frame[0], frame[1], frame[2], frame[3],
                    flat_faces(solid)))
    return out


def bearing_top(element):
    """Where a hanger actually holds its services up, and how it was found.

    The top of a hanger's geometry is the top of its rods, up at the soffit,
    and nothing sits there. What services sit on is the top face of its
    bearer: found by telling the bearer from the rods where the geometry
    comes in pieces, and by the largest upward face where it does not.
    """
    height = bearing_from_members(hanger_members(element))
    if height is not None:
        return height, u"the top of its bearer"
    height = best_bearing(upward_faces(element))
    if height is not None:
        return height, u"its biggest upward face"
    return None, u""


def hanger_lines(element, limit=48):
    """The hanger's own geometry, written out for the debug report.

    Every rule for finding a bearer is a guess about how somebody drew a
    hanger. This is the evidence: one line per piece and one per upward
    face, so a hanger that measures wrong can be read rather than guessed
    at.
    """
    lines = []
    members = hanger_members(element)
    if not members:
        lines.append(u"no solids to look at")
        return lines
    for index, member in enumerate(members):
        low, high, span, area, faces = member
        lines.append(
            u"piece {0}: {1} to {2} mm, {3} mm across, footprint {4} mm2, "
            u"{5}".format(index + 1, format_mm(ft_to_mm(low)),
                          format_mm(ft_to_mm(high)),
                          format_mm(ft_to_mm(span)),
                          format_mm(area * MM_PER_FT * MM_PER_FT),
                          u"a rod" if is_upright(low, high, span)
                          else u"a bearer"))
        ups = [f for f in faces if f[0] >= 0.9]
        ups.sort(key=lambda f: -f[2])
        for face in ups:
            if len(lines) >= limit:
                lines.append(u"... and more")
                return lines
            lines.append(u"    up face {0} mm2 at {1} mm".format(
                format_mm(face[1] * MM_PER_FT * MM_PER_FT),
                format_mm(ft_to_mm(face[2]))))
    return lines


# ======================================================================
# fabrication parts
# ======================================================================

def named_parameter(element, names):
    for name in names:
        try:
            parameter = element.LookupParameter(name)
        except Exception:
            continue
        if parameter is None:
            continue
        try:
            return parameter.AsDouble()
        except Exception:
            continue
    return None


def fab_value(element, builtins, names):
    value = param_number(element, builtins, None)
    if value is None:
        value = named_parameter(element, names)
    return value


def agreeing(candidates, extent, tolerance=AGREE_FT):
    """Pick the reading of a parameter that the solids agree with.

    Top of Part and Bottom of Part are measured from the part's level, not
    from the project base - but not on every release and not for every
    service template, and a level offset mistaken for a project elevation is
    out by the height of the level and still looks like a number. So both
    readings are compared against what the solids actually say, and the one
    that agrees wins. Neither agreeing means the solids are the answer.
    """
    if extent is None:
        return None, u"no solids to check against"
    best = None
    for label, value in candidates:
        if value is None:
            continue
        gap = min(abs(value - extent[0]), abs(value - extent[1]))
        if best is None or gap < best[0]:
            best = (gap, label, value)
    if best is None:
        return None, u"no parameter to read"
    if best[0] > tolerance:
        return None, u"the parameters disagree with the solids by {0:.0f}mm" \
                     u"".format(best[0] * 304.8)
    return best[2], best[1]


def fab_extent(doc, element):
    """Bottom and top of a fabrication part, from its own parameters.

    Returns (bottom, top, how) with how naming which reading was used, so a
    run that fell back says so rather than looking the same as one that did
    not.
    """
    extent = solid_extent(element)
    bottom_raw = fab_value(element, FAB_BOTTOM_PARAMS, FAB_BOTTOM_NAMES)
    top_raw = fab_value(element, FAB_TOP_PARAMS, FAB_TOP_NAMES)
    if bottom_raw is None and top_raw is None:
        return None, None, u"no top or bottom of part parameter"

    level = level_elevation(doc, element)
    bottom, how_bottom = agreeing(
        [(u"from its level", None if bottom_raw is None else level + bottom_raw),
         (u"as a project elevation", bottom_raw)], extent)
    top, how_top = agreeing(
        [(u"from its level", None if top_raw is None else level + top_raw),
         (u"as a project elevation", top_raw)], extent)
    if bottom is None or top is None:
        return None, None, how_bottom if bottom is None else how_top
    if top < bottom:
        bottom, top = top, bottom
    return bottom, top, how_bottom


def measured_at_a_point(element):
    try:
        return eid_value(element.Category.Id) in point_based_ids()
    except Exception:
        return False


def insertion_point(element):
    """A family's own insertion point, which is what its level offset is.

    Read off the element rather than out of a parameter, because which
    parameter holds it depends on how the family is hosted - Elevation from
    Level, Offset from Host, Default Elevation - and the point itself is the
    same thing whichever of them the family happens to carry.
    """
    try:
        location = element.Location
        if isinstance(location, LocationPoint):
            return geom_point_z(location)
    except Exception:
        pass
    return None


def geom_point_z(location):
    try:
        return float(location.Point.Z)
    except Exception:
        return None


class OffsetFilter(ISelectionFilter):
    """Only the categories the settings allow, and nothing in a link.

    The hot path in the whole tool. A frozenset of ints and one attribute
    chain: no name lookups, no set building, no formatting.
    """

    def __init__(self, category_keys):
        mapping = category_id_map()
        allowed = []
        for key in category_keys:
            if key in mapping:
                allowed.append(mapping[key])
        self.allowed = frozenset(allowed)

    def AllowElement(self, element):
        try:
            category = element.Category
            if category is None:
                return False
            return eid_value(category.Id) in self.allowed
        except Exception:
            return False

    def AllowReference(self, reference, point):
        return False


# ======================================================================
# parameters
# ======================================================================

def param_by_builtin(element, names):
    for member in builtin_parameters(names):
        try:
            parameter = element.get_Parameter(member)
        except Exception:
            continue
        if parameter is not None:
            return parameter
    return None


def param_number(element, names, fallback=0.0):
    parameter = param_by_builtin(element, names)
    if parameter is None:
        return fallback
    try:
        return parameter.AsDouble()
    except Exception:
        return fallback


def element_name(element):
    """Element.Name raises AttributeError under IronPython; guard it."""
    try:
        return to_text(element.Name)
    except Exception:
        pass
    try:
        return to_text(element.Category.Name)
    except Exception:
        return u"element"


def describe(element):
    try:
        category = to_text(element.Category.Name)
    except Exception:
        category = u"Element"
    return u"{0} {1}".format(category, eid_value(element.Id))


# ======================================================================
# levels
# ======================================================================

def level_elevations(doc):
    """Every level's project elevation, read once per document per run.

    ProjectElevation, never Elevation: on a survey-point-based project the
    latter reports shared coordinates and comes back tens of metres out.
    """
    if _LEVELS[0] is doc and _LEVELS[1]:
        return _LEVELS[1]
    values = []
    try:
        for level in FilteredElementCollector(doc).OfClass(Level).ToElements():
            try:
                values.append(float(level.ProjectElevation))
            except Exception:
                continue
    except Exception:
        values = []
    values.sort()
    _LEVELS[0] = doc
    del _LEVELS[1][:]
    _LEVELS[1].extend(values)
    return _LEVELS[1]


def level_elevation(doc, element):
    """Project elevation of the element's own reference level, in feet."""
    parameter = param_by_builtin(element, LEVEL_PARAMS)
    if parameter is not None:
        try:
            level = doc.GetElement(parameter.AsElementId())
            if level is not None:
                return float(level.ProjectElevation)
        except Exception:
            pass
    try:
        level = doc.GetElement(element.LevelId)
        if level is not None:
            return float(level.ProjectElevation)
    except Exception:
        pass
    return nearest_level_below(doc, element)


def nearest_level_below(doc, element):
    """Where an element names no level, the level at or below it stands in,
    so the "round to the level offset" datum still means something."""
    try:
        box = element.get_BoundingBox(None)
        z = float(box.Min.Z) if box is not None else 0.0
    except Exception:
        z = 0.0
    values = level_elevations(doc)
    if not values:
        return 0.0
    best = None
    for elevation in values:
        if elevation <= z + EPS:
            best = elevation
        else:
            break
    return values[0] if best is None else best


# ======================================================================
# measuring
# ======================================================================

class Measurement(object):
    __slots__ = ('ok', 'reason', 'bottom', 'middle', 'top', 'slope', 'route',
                 'has_offset_param')

    def __init__(self):
        self.ok = False
        self.reason = u""
        self.bottom = 0.0
        self.middle = 0.0
        self.top = 0.0
        self.slope = 0.0
        self.route = u""
        self.has_offset_param = False

    def value(self, anchor):
        return anchor_value(self.bottom, self.middle, self.top, anchor)


def bounding_box(element):
    try:
        return element.get_BoundingBox(None)
    except Exception:
        return None


def mep_curve_of(element):
    """The centreline of an MEP curve, or None.

    One fetch of Location and one of ConnectorManager, rather than the two
    of each that asking "is this an MEP curve" and then "give me its curve"
    separately would cost.
    """
    try:
        location = element.Location
    except Exception:
        return None
    if not isinstance(location, LocationCurve):
        return None
    try:
        if element.ConnectorManager is None:
            return None
    except Exception:
        return None
    try:
        return location.Curve
    except Exception:
        return None


def half_height(element, include_insulation):
    """Half the element's own vertical extent, from its size parameters.

    Size parameters rather than the bounding box, because the box takes in
    insulation, lining and anything the family draws beyond the duct; the
    parameters are the bare service, which is what a setting-out offset
    means. Insulation is added back when the setting asks for it.
    """
    height = param_number(element, BOX_SIZE_PARAMS, 0.0)
    if height <= EPS:
        height = param_number(element, ROUND_SIZE_PARAMS, 0.0)
    if height <= EPS:
        return None
    half = height / 2.0
    if include_insulation:
        half += param_number(element, INSULATION_PARAMS, 0.0)
    return half


def measure(doc, element, settings_measure=u"size", include_insulation=False,
            slope_tol_deg=0.5, at_point=None, point_measure=FROM_SOLID,
            fab_measure=FROM_PARAMETERS, hanger_top=FROM_BEARING,
            framing_measure=FROM_TOP):
    """Bottom, middle and top of an element in project feet.

    For a piece of equipment, a fixture, a device or a terminal, all three
    are its **insertion point** - because what one of those sits at is its
    own level offset, and a family's level offset is one number, not three.
    Aligning an air terminal to a piece of mechanical equipment by the
    extents of what their families happen to draw lines up a flange with a
    plant base, which is not what anybody meant.
    """
    result = Measurement()

    # Support steel first, before anything that reads a centreline: strut
    # is drawn along a line, and a line is exactly what made it measure at
    # its middle and land half its depth proud of the duct it was put under.
    if is_ancillary_framing(element):
        return measure_framing(element, framing_measure, result)

    curve = mep_curve_of(element)

    if curve is not None:
        try:
            start = curve.GetEndPoint(0)
            end = curve.GetEndPoint(1)
        except Exception:
            result.reason = u"no usable centreline"
            return result
        start_z = float(start.Z)
        end_z = float(end.Z)
        rise = end_z - start_z
        run = ((float(end.X) - float(start.X)) ** 2 +
               (float(end.Y) - float(start.Y)) ** 2) ** 0.5
        result.slope = slope_degrees(rise, run)

        if at_point is not None and abs(rise) > EPS:
            centre = elevation_at(curve, at_point)
        else:
            centre = (start_z + end_z) / 2.0

        half = None
        if settings_measure != u"box":
            half = half_height(element, include_insulation)
        if half is None:
            half = half_from_box(bounding_box(element), centre)
            result.route = u"bounding box"
        else:
            result.route = u"size parameters"
        result.bottom = centre - half
        result.middle = centre
        result.top = centre + half
        result.has_offset_param = \
            param_by_builtin(element, OFFSET_PARAMS) is not None
        result.ok = True
        return result

    # A hanger is one height: the top face it holds its services on. Match a
    # duct's bottom onto a hanger and the bearer lands under the duct, which
    # is the whole reason anybody aligns a hanger to anything.
    if is_a_hanger(element) and hanger_top != FROM_BOX:
        height, how = bearing_top(element) \
            if hanger_top == FROM_BEARING else (None, u"")
        if height is None:
            extent = solid_extent(element)
            if extent is not None:
                height = extent[1]
                result.route = u"top of its solids"
        else:
            result.route = how or u"its bearing face"
        if height is not None:
            result.bottom = height
            result.middle = height
            result.top = height
            result.ok = True
            return result

    # Hangers are fabrication parts too, but their own setting governs them
    # from end to end: falling through to the fabrication route would make
    # "measure a hanger from its box" quietly mean "from its solids".
    if is_a_fabrication_part(element) and not is_a_hanger(element) \
            and fab_measure != FROM_BOX:
        if fab_measure == FROM_PARAMETERS:
            bottom, top, how = fab_extent(doc, element)
            if bottom is not None:
                result.bottom = bottom
                result.top = top
                result.middle = (bottom + top) / 2.0
                result.route = u"top and bottom of part, {0}".format(how)
                result.ok = True
                return result
            result.reason = how
        extent = solid_extent(element)
        if extent is not None:
            result.bottom, result.top = extent
            result.middle = (extent[0] + extent[1]) / 2.0
            result.route = u"its solids"
            result.reason = u""
            result.ok = True
            return result

    if point_measure != FROM_BOX and measured_at_a_point(element):
        height = insertion_point(element)
        if point_measure == FROM_INSERTION and height is not None:
            result.bottom = height
            result.middle = height
            result.top = height
            result.route = u"its offset from level"
            result.slope = 0.0
            result.ok = True
            return result
        if point_measure == FROM_SOLID:
            extent = solid_extent(element)
            if extent is not None:
                result.bottom, result.top = extent
                # Middle stays the family's own offset from level: that is
                # the number in the properties palette, it is the one thing
                # every family agrees on, and it is what the three buttons
                # are for - real bottom face, real top face, and the datum
                # the family was placed at.
                result.middle = height if height is not None \
                    else (extent[0] + extent[1]) / 2.0
                result.route = u"its solid faces" if height is None else \
                    u"its solid faces, middle from its offset from level"
                result.slope = 0.0
                result.ok = True
                return result
        if height is not None:
            result.bottom = height
            result.middle = height
            result.top = height
            result.route = u"its offset from level"
            result.slope = 0.0
            result.ok = True
            return result

    box = bounding_box(element)
    if box is None:
        result.reason = u"no geometry to measure"
        return result
    result.bottom = float(box.Min.Z)
    result.top = float(box.Max.Z)
    result.middle = (result.bottom + result.top) / 2.0
    result.route = u"bounding box"
    result.slope = 0.0
    result.ok = True
    return result


def measure_framing(element, framing_measure, result):
    """MEP ancillary framing: strut, channel, trapeze bars.

    Like a hanger it is one height - the face the service sits on, its top -
    so Match Offset Bottom from a duct puts the strut flush under the duct.
    Where the family has drops or rods drawn in it, the top of its bearer
    is found the same way a hanger's is; a plain length of strut is its own
    bearer, and its top is the top of its solids.
    """
    result.slope = 0.0
    if framing_measure != FROM_BOX:
        extent = solid_extent(element)
        if extent is not None:
            if framing_measure == FROM_SOLID:
                result.bottom, result.top = extent
                result.middle = (extent[0] + extent[1]) / 2.0
                result.route = u"its solids"
            else:
                height = bearing_from_members(hanger_members(element))
                if height is None:
                    height = extent[1]
                    result.route = u"the top face it supports on"
                else:
                    result.route = u"the top of its bearer"
                result.bottom = height
                result.middle = height
                result.top = height
            result.ok = True
            return result
    box = bounding_box(element)
    if box is None:
        result.reason = u"no geometry to measure"
        return result
    low = float(box.Min.Z)
    high = float(box.Max.Z)
    if framing_measure == FROM_BOX:
        result.bottom, result.middle, result.top = low, (low + high) / 2.0, \
            high
        result.route = u"bounding box"
    else:
        result.bottom = result.middle = result.top = high
        result.route = u"the top of its bounding box"
    result.ok = True
    return result


def half_from_box(box, centre_z):
    if box is None:
        return 0.0
    try:
        up = float(box.Max.Z) - float(centre_z)
        down = float(centre_z) - float(box.Min.Z)
        return max(abs(up), abs(down))
    except Exception:
        return 0.0


def elevation_at(curve, point):
    """Centreline Z of a sloping run directly under the picked point."""
    try:
        result = curve.Project(point)
        if result is not None:
            return float(result.XYZPoint.Z)
    except Exception:
        pass
    try:
        return float(curve.GetEndPoint(0).Z)
    except Exception:
        return 0.0


# ======================================================================
# writing
# ======================================================================

def connected_count(element):
    """How many of an element's connectors are joined to something.

    A fitting is a FamilyInstance and keeps its manager on MEPModel rather
    than on the element, so asking only for ConnectorManager reports every
    fitting as unconnected - which is how "connected fittings are left for
    their pipes to move" quietly stopped applying to fittings.
    """
    manager = None
    try:
        manager = element.ConnectorManager
    except Exception:
        manager = None
    if manager is None:
        try:
            model = element.MEPModel
            if model is not None:
                manager = model.ConnectorManager
        except Exception:
            manager = None
    if manager is None:
        return 0
    count = 0
    try:
        for connector in manager.Connectors:
            try:
                if connector.IsConnected:
                    count += 1
            except Exception:
                continue
    except Exception:
        return 0
    return count


def in_group(element):
    try:
        return eid_value(element.GroupId) > 0
    except Exception:
        return False


def is_pinned(element):
    try:
        return bool(element.Pinned)
    except Exception:
        return False


def is_workshared(doc):
    try:
        return bool(doc.IsWorkshared)
    except Exception:
        return False


def username(doc):
    try:
        return to_text(doc.Application.Username).lower()
    except Exception:
        return u""


def owned_by_other(doc, element, me=None):
    """Who has this element, if anybody. Two locks, and both are asked.

    An element nobody has borrowed can still sit on a workset somebody else
    owns, and its own checkout status is perfectly clean in that case. On a
    model that is not workshared neither question means anything, so neither
    is asked - that is two API calls per element saved on every single
    project file.
    """
    try:
        status = WorksharingUtils.GetCheckoutStatus(doc, element.Id)
        if status == CheckoutStatus.OwnedByOtherUser:
            try:
                info = WorksharingUtils.GetWorksharingTooltipInfo(
                    doc, element.Id)
                return to_text(info.Owner) or u"another user"
            except Exception:
                return u"another user"
    except Exception:
        pass
    try:
        workset = doc.GetWorksetTable().GetWorkset(element.WorksetId)
        owner = to_text(workset.Owner)
        if owner and owner.lower() != (me if me is not None else username(doc)):
            return owner
    except Exception:
        pass
    return u""


def writable(element, names):
    parameter = param_by_builtin(element, names)
    if parameter is None:
        return None
    try:
        if parameter.IsReadOnly:
            return None
    except Exception:
        return None
    return parameter


def vertical_marker(element):
    """Something on the element that moves when it moves: its insertion
    point, or the bottom of its box."""
    height = insertion_point(element)
    if height is not None:
        return height
    box = bounding_box(element)
    if box is None:
        return None
    try:
        return float(box.Min.Z)
    except Exception:
        return None


def regenerate(doc):
    if doc is None:
        return
    try:
        doc.Regenerate()
    except Exception:
        pass


def shift_off_host(doc, element, parameter, delta_ft):
    """Move a hosted family through its offset from host.

    Which way that parameter runs depends on which way the host faces, and
    nothing on the element says so directly. So: write it one way, look at
    where the family went, and turn it round if it went the other. Returns
    the route, or u"" where the parameter moved nothing either way and the
    caller should try something else.
    """
    try:
        current = parameter.AsDouble()
    except Exception:
        return u""
    before = vertical_marker(element)
    try:
        parameter.Set(current + delta_ft)
    except Exception:
        return u""
    regenerate(doc)
    after = vertical_marker(element)
    if before is None or after is None:
        return u"offset from host"
    direction = host_offset_direction(delta_ft, after - before)
    if direction > 0:
        return u"offset from host"
    try:
        if direction < 0:
            parameter.Set(current - delta_ft)
            regenerate(doc)
            return u"offset from host, which runs down off its host"
        parameter.Set(current)
        regenerate(doc)
    except Exception:
        pass
    return u""


def level_of(doc, element):
    """The element's own level: (name, project elevation in feet).

    The same search as level_elevation, keeping the name so a match across
    two levels can say which level each end was worked out against.
    """
    level = None
    parameter = param_by_builtin(element, LEVEL_PARAMS)
    if parameter is not None:
        try:
            level = doc.GetElement(parameter.AsElementId())
        except Exception:
            level = None
    if level is None:
        try:
            level = doc.GetElement(element.LevelId)
        except Exception:
            level = None
    if level is not None:
        try:
            return to_text(level.Name), float(level.ProjectElevation)
        except Exception:
            pass
    return u"", None


def shift(doc, element, delta_ft):
    """Move an element up or down by delta_ft. Returns the route taken.

    The offset parameter first, because it is relative to the element's own
    level and so needs no level elevation to be known and keeps the element's
    connections intact. Where there is no such parameter - a fitting, a piece
    of equipment - the element is moved, which is the same thing done a
    different way.
    """
    if abs(float(delta_ft)) <= TOL_FT:
        return u"already there"
    parameter = param_by_builtin(element, OFFSET_PARAMS)
    if parameter is not None and not parameter.IsReadOnly:
        try:
            current = parameter.AsDouble()
            parameter.Set(current + float(delta_ft))
            return u"offset parameter"
        except Exception:
            pass

    # A family on a level: its elevation from that level, worked out
    # against its own level. Everything here is in project elevations, so
    # the delta is the same number whichever level the datum came off.
    parameter = writable(element, LEVEL_OFFSET_PARAMS)
    if parameter is not None:
        try:
            current = parameter.AsDouble()
            parameter.Set(current + float(delta_ft))
            return u"elevation from level"
        except Exception:
            pass

    # A family on a face or a work plane: Revit will not move it off its
    # host, so the move has to go through its offset from host - which runs
    # along the host's normal and so runs downward under a ceiling.
    parameter = writable(element, HOST_OFFSET_PARAMS)
    if parameter is not None:
        route = shift_off_host(doc, element, parameter, float(delta_ft))
        if route:
            return route

    try:
        ElementTransformUtils.MoveElement(doc, element.Id,
                                          XYZ(0.0, 0.0, float(delta_ft)))
        return u"moved"
    except Exception as err:
        raise Exception(u"Revit refused the move: {0}".format(to_text(err)))


def keep_rod_tops(element, delta_ft):
    """After a hanger moves, hold its rod tops where they were.

    A hanger hangs from the soffit. Move the body and the rods have to
    change length to suit, or the tops come away from the structure and the
    hanger is left floating on nothing - which looks correct in plan and in
    a section until somebody looks at the rods.

    Rods Revit is hosting it re-solves itself; rods set to manual are ours
    to re-cut, which is the same call the Fab Hangar Automation tool makes.
    """
    if abs(float(delta_ft)) <= TOL_FT:
        return u""
    try:
        info = element.GetRodInfo()
    except Exception:
        return u""
    if info is None:
        return u""
    try:
        if info.CanRodsBeHosted:
            return u"its rods are hosted, so Revit re-solved them"
    except Exception:
        pass
    try:
        count = int(info.RodCount)
    except Exception:
        return u""
    recut = 0
    refused = 0
    for index in range(count):
        try:
            length = info.GetRodLength(index)
        except Exception:
            continue
        wanted = rod_length_after(length, delta_ft)
        if wanted is None:
            refused += 1
            continue
        try:
            info.SetRodLength(index, wanted)
            recut += 1
        except Exception:
            refused += 1
    if refused and not recut:
        return u"its rods would have no length left and were not re-cut"
    if refused:
        return u"{0} rod(s) re-cut, {1} would have no length left".format(
            recut, refused)
    if recut:
        return u"{0} rod(s) re-cut to keep their tops at the soffit".format(
            recut)
    return u""


def checkout(doc, element_ids):
    """Borrow before writing, in one call for however many elements.

    On a workshared model a write to an element nobody has borrowed writes
    nothing and says nothing, because Revit asks in a dialog and a run that
    suppresses dialogs answers it. On a model that is not workshared there
    is nothing to borrow and the call is skipped.
    """
    if List is None or not is_workshared(doc):
        return False
    try:
        collection = List[ElementId]()
        for element_id in element_ids:
            collection.Add(element_id)
        WorksharingUtils.CheckoutElements(doc, collection)
        return True
    except Exception:
        return False
