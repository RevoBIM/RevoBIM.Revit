# -*- coding: utf-8 -*-
"""Global Placement tab of BWIC Penetration -- view wide BWIC placement.

Merged in from the standalone BWIC Global Placement tool (v0.9.0). The
window lives in script.py; this module is the engine, reached through
configure() and run_global_placement().

Instead of picking services and a wall one pair at a time, this tool sweeps the
active view and places every penetration it can justify:

    1. Pick the architectural / structural link in the window (or select an
       instance of it in the model before opening the tool).
    2. Press Run. Every wall in that link carrying a value in
       POP_PERF_FireRatingTarget is treated as fire rated and therefore as
       needing penetrations.
    3. For each of those walls, the pipes and cable trays visible in the active
       view that actually pass through it are collected, grouped, and given a
       BWIC each.

Grouping
    Cable trays within GROUP_GAP_MM of each other share one BWIC. Pipes within
    GROUP_GAP_MM of each other share one BWIC. Pipes and trays never share --
    they are grouped separately, so a tray 50mm from a pipe still gets its own
    opening. Grouping is transitive: A near B and B near C makes one group.

Sizing, levels, worksets and Comments follow the same rules as Place BWIC
Horizontal:

    * BGL_Length = wall thickness.
    * BGL_Width  = extent of the group along the wall + clearance each side,
                   rounded up to the nearest 5mm.
    * BGL_Height = vertical extent of the group + clearance each side,
                   rounded up to the nearest 5mm.
    * Elevation  = midway between the bottom of the lowest service and the top
                   of the highest.
    * Level      = nearest level beneath the BWIC, code written to BHE_Level.
    * Comments   = family and type of the services in the group.

Nothing is pinned, and any group that already sits inside an existing
BGL_BWIC_Penetration_Horizontal_Rectangular-Dynamic is left alone.
"""

# The engine's own version, separate from the tool's. It came across from the
# standalone BWIC Global Placement at 0.9.0.
ENGINE_VERSION = '0.9.0'

import datetime
import math
import os.path as op
import re

from pyrevit import forms, script, HOST_APP

try:
    from pyrevit import DB, UI
except ImportError:
    from Autodesk.Revit import DB, UI

from System.Collections.Generic import List

# the old ElementId integer property was removed in Revit 2026; this helper
# reads .Value first and falls back, so 2024 to 2027 all work
from bwic_core import eid_value
# one size writer for the whole tool: it is the one that knows a split
# family's X Minus / X Plus pair takes half the size on each side
from bwic_core import set_length_param, has_length_param
from Autodesk.Revit.DB.Structure import StructuralType


# ---------------------------------------------------------------------------
# SETTINGS
# ---------------------------------------------------------------------------

FAMILY_NAME = 'BGL_BWIC_Penetration_Horizontal_Rectangular-Dynamic'

# the family type used depends on what the wall is. A wall that is both
# blockwork and fire rated takes the blockwork type.
TYPE_FIRE = 'BWIC - Fire Rated Wall'
TYPE_BLOCKWORK = 'BWIC - Blockwork'

# a wall is blockwork when its type name or family name contains this
BLOCKWORK_KEYWORD = 'BLK'

# on blockwork, pipes and cable trays are allowed to share one opening. On
# fire rated walls they stay in separate openings.
BLOCKWORK_SHARES_HOLE = True

# the link dropdown lands on the first link whose name contains this
LINK_NAME_HINT = '-01000'

P_LENGTH = 'BGL_Length'          # front/back -> through the wall
P_WIDTH = 'BGL_Width'            # left/right -> along the wall
P_HEIGHT = 'BGL_Height'          # vertical

DEFAULT_CLEARANCE_MM = 50.0      # added to EACH side

# a wall is fire rated -- and so needs penetrations -- when this parameter in
# the LINKED model carries any value. Checked on the instance first, then on
# the wall type.
FIRE_PARAM = 'POP_PERF_FireRatingTarget'

# categories this tool will enclose, and the grouping distance for each.
# Elements of different categories are never grouped together.
CAT_PIPES = 'OST_PipeCurves'
CAT_TRAYS = 'OST_CableTray'

TARGET_CATEGORIES = [CAT_PIPES, CAT_TRAYS]

DEFAULT_GAP_PIPES_MM = 200.0     # pipes closer than this share one BWIC
DEFAULT_GAP_TRAYS_MM = 200.0     # cable trays closer than this share one BWIC

# A service crossing at an angle cuts a longer footprint through the wall than
# its own width -- a 100mm pipe at 45 degrees leaves a 141mm gash. With this
# on, the opening is sized on the service's own section instead, as though it
# ran square through, and centred on the middle of the crossing.
WIDTH_FROM_SECTION = True

# how far outside the visible services a wall may sit and still be looked at.
# Only a speed filter -- it is measured off the services themselves, so it can
# never exclude a wall that one of them actually passes through.
SERVICE_REACH_MM = 1000.0

# how far the measured crossing may sit from the wall centre line before the
# group is rejected. Anything genuinely inside the wall is within half its
# thickness, so this only catches geometry that was never really at the wall.
OFF_WALL_TOLERANCE_MM = 50.0

# how square-on an element has to run to count as passing THROUGH the wall
# rather than clipping past it. 0.17 is roughly 10 degrees off the wall face.
MIN_CROSSING_DOT = 0.17

# skip a group when a BWIC that was ALREADY in the model overlaps it. BWICs
# placed during this run are not skipped -- they are flagged as clashes below.
SKIP_EXISTING = True

# two BWICs placed in the same run that overlap in 3D are marked for review:
# a red rectangle in detail lines around each one, all gathered into a group
MARK_CLASHES = True
CLASH_LINE_STYLE = 'BWIC Clash Error'    # line subcategory, created red if new
CLASH_GROUP_NAME = 'BWIC Clash Error'    # the date and time is appended

# groups that could not be placed are marked the same way, in amber, so they
# can be found and done by hand
MARK_FAILURES = True
FAILED_LINE_STYLE = 'BWIC Failed'
FAILED_GROUP_NAME = 'BWIC Failed'        # the same date and time is appended
CLASH_MARGIN_MM = 75.0                   # rectangle drawn this far outside
CLASH_TOLERANCE_MM = 1.0                 # ignore BWICs that merely touch

# a second BWIC of the same size within this distance of one already placed is
# treated as the same penetration and skipped. This is what stops Revit
# raising "there are identical instances in the same place".
DUPLICATE_TOLERANCE_MM = 10.0

# swallow Revit's warning dialogs during the run and report them at the end
# instead. Errors are still handled by Revit -- only warnings are dismissed.
SUPPRESS_WARNINGS = True

# the BWIC is centred on the full vertical extent of the group
ELEVATION_MODE = 'extents_centre'

LEVEL_PARAM_NAME = 'BHE_Level'
LEVEL_PARAM_KEYWORD = 'Level'

# where the family origin sits in its own box: 'centre' | 'bottom' | 'top'
ORIGIN_VERTICAL = 'centre'

# careful with this one on a global run -- if BGL_* are TYPE parameters this
# creates a family type per unique size, which on a whole view can be hundreds
DUPLICATE_TYPE_IF_TYPE_PARAMS = True

# BGL_Width and BGL_Height are rounded UP to a multiple of this, in mm
ROUND_UP_MM = 5.0

# the BWIC is placed on the first workset whose name contains this word
WORKSET_KEYWORD = 'BWIC'
# the workset chosen in Settings, by name. Empty falls back to the keyword.
WORKSET_NAME = ''
# the workset set in the wall family's own Family settings: a name, '<active>'
# or empty to follow WORKSET_NAME. Same values as bwic_families.
FAMILY_WORKSET = ''
# the wall family's own clearance from Family settings, in mm; empty follows
# this tab's clearance
FAMILY_CLEARANCE = ''
ACTIVE_WORKSET = '<active>'

QTY_DELIMITER = '_'              # between entries in the Comments string

logger = script.get_logger()


# ---------------------------------------------------------------------------
# units
# ---------------------------------------------------------------------------
def mm_to_ft(value_mm):
    try:
        from Autodesk.Revit.DB import UnitUtils, UnitTypeId
        return UnitUtils.ConvertToInternalUnits(value_mm, UnitTypeId.Millimeters)
    except ImportError:
        from Autodesk.Revit.DB import UnitUtils, DisplayUnitType
        return UnitUtils.ConvertToInternalUnits(
            value_mm, DisplayUnitType.DUT_MILLIMETERS)


def ft_to_mm(value_ft):
    try:
        from Autodesk.Revit.DB import UnitUtils, UnitTypeId
        return UnitUtils.ConvertFromInternalUnits(value_ft, UnitTypeId.Millimeters)
    except ImportError:
        from Autodesk.Revit.DB import UnitUtils, DisplayUnitType
        return UnitUtils.ConvertFromInternalUnits(
            value_ft, DisplayUnitType.DUT_MILLIMETERS)


def round_up_ft(value_ft, step_mm=None):
    """Round a length UP to the next whole step, working in millimetres."""
    step = ROUND_UP_MM if step_mm is None else step_mm
    if not step or step <= 0:
        return value_ft
    value_mm = ft_to_mm(value_ft)
    steps = math.ceil(value_mm / step - 1e-9)
    return mm_to_ft(steps * step)


# ---------------------------------------------------------------------------
# geometry helpers
# ---------------------------------------------------------------------------
def bbox_corners(element):
    bb = element.get_BoundingBox(None)
    if bb is None:
        return []
    tf = bb.Transform
    mn, mx = bb.Min, bb.Max
    pts = []
    for x in (mn.X, mx.X):
        for y in (mn.Y, mx.Y):
            for z in (mn.Z, mx.Z):
                pts.append(tf.OfPoint(DB.XYZ(x, y, z)))
    return pts


def element_centre_z(element):
    try:
        loc = element.Location
        if isinstance(loc, DB.LocationCurve):
            crv = loc.Curve
            return (crv.GetEndPoint(0).Z + crv.GetEndPoint(1).Z) / 2.0
        if isinstance(loc, DB.LocationPoint):
            return loc.Point.Z
    except Exception:
        pass
    bb = element.get_BoundingBox(None)
    if bb is None:
        return 0.0
    return (bb.Transform.OfPoint(bb.Min).Z + bb.Transform.OfPoint(bb.Max).Z) / 2.0


def get_wall_thickness(wall):
    try:
        width = wall.Width
        if width and width > 1e-9:
            return width
    except Exception:
        pass
    try:
        wtype = wall.Document.GetElement(wall.GetTypeId())
        param = wtype.get_Parameter(DB.BuiltInParameter.WALL_ATTR_WIDTH_PARAM)
        if param and param.AsDouble() > 1e-9:
            return param.AsDouble()
    except Exception:
        pass
    return None


class WallFrame(object):
    """The wall centre line, addressed by distance along it.

    Everything the tool needs to position a BWIC comes from here. The point is
    that a station is a distance ALONG THE WALL, not a coordinate in space:
    ask for a station and you get a point on the wall, clamped to its ends,
    straight or curved. The previous approach projected onto the wall's
    direction vector instead, which is only the same thing for a straight wall
    and let openings slide off the end into open space.
    """

    def __init__(self, curve):
        self.curve = curve
        self.start = curve.GetEndParameter(0)
        self.end = curve.GetEndParameter(1)
        self.span = self.end - self.start
        self.length = curve.Length
        self.base_z = curve.GetEndPoint(0).Z

    def _parameter(self, station):
        if self.length < 1e-9:
            return self.start
        ratio = station / self.length
        ratio = min(max(ratio, 0.0), 1.0)          # never past the ends
        return self.start + ratio * self.span

    def station(self, point):
        """(distance along the wall, distance from the centre line) or None.

        Curve.Project only ever returns a point on the bounded curve, so the
        station that comes back is on the wall by construction.
        """
        flat = DB.XYZ(point.X, point.Y, self.base_z)
        try:
            result = self.curve.Project(flat)
        except Exception:
            return None
        if result is None:
            return None
        if abs(self.span) < 1e-12:
            station = 0.0
        else:
            station = (result.Parameter - self.start) / self.span * self.length
        on_curve = result.XYZPoint
        offset = math.sqrt((flat.X - on_curve.X) ** 2
                           + (flat.Y - on_curve.Y) ** 2)
        return station, offset

    def point_at(self, station):
        return self.curve.Evaluate(self._parameter(station), False)

    def frame_at(self, station):
        """(point on the centre line, along-wall vector, wall normal)."""
        parameter = self._parameter(station)
        point = self.curve.Evaluate(parameter, False)
        try:
            direction = self.curve.ComputeDerivatives(parameter, False).BasisX
        except Exception:
            direction = self.curve.GetEndPoint(1) - self.curve.GetEndPoint(0)
        along = DB.XYZ(direction.X, direction.Y, 0).Normalize()
        normal = along.CrossProduct(DB.XYZ.BasisZ).Normalize()
        return point, along, normal


# ---------------------------------------------------------------------------
# family helpers
# ---------------------------------------------------------------------------
def family_symbols(doc):
    """Every type of the BWIC family, keyed by type name."""
    symbols = {}
    for sym in DB.FilteredElementCollector(doc).OfClass(DB.FamilySymbol):
        try:
            family = sym.Family
            if family is not None and family.Name == FAMILY_NAME:
                symbols[DB.Element.Name.GetValue(sym)] = sym
        except Exception:
            continue
    return symbols


def find_family_symbol(doc):
    symbols = []
    for sym in DB.FilteredElementCollector(doc).OfClass(DB.FamilySymbol):
        fam = sym.Family
        if fam is not None and fam.Name == FAMILY_NAME:
            symbols.append(sym)
    if not symbols:
        for sym in DB.FilteredElementCollector(doc).OfClass(DB.FamilySymbol):
            if DB.Element.Name.GetValue(sym) == FAMILY_NAME:
                symbols.append(sym)
    if not symbols:
        return None
    return symbols[0]


def unique_type_name(base_symbol, length_ft, width_ft, height_ft):
    return '{}_L{:.0f}_W{:.0f}_H{:.0f}'.format(
        DB.Element.Name.GetValue(base_symbol),
        round(ft_to_mm(length_ft)),
        round(ft_to_mm(width_ft)),
        round(ft_to_mm(height_ft)))


def find_symbol_by_name(doc, family, type_name):
    for sid in family.GetFamilySymbolIds():
        sym = doc.GetElement(sid)
        if DB.Element.Name.GetValue(sym) == type_name:
            return sym
    return None


# ---------------------------------------------------------------------------
# levels
# ---------------------------------------------------------------------------
def sorted_levels(doc):
    return sorted(DB.FilteredElementCollector(doc).OfClass(DB.Level).ToElements(),
                  key=lambda l: l.Elevation)


def level_below(levels, elevation):
    """Nearest level at or below the given elevation."""
    if not levels:
        return None
    chosen = levels[0]
    for lvl in levels:
        if lvl.Elevation <= elevation + 1e-6:
            chosen = lvl
    return chosen


def level_code(level, levels):
    """Two digit code for a level.

    Numbered names give up their own digits -- L00 is 00, Level 03 is 03.
    Names with no number in them fall back to the level's position in the
    model counting up from the lowest, so on L00/L01/L02/L03/L04/LRF the roof
    comes out as 05.
    """
    digits = re.findall(r'\d+', level.Name)
    if digits:
        return '{:02d}'.format(int(digits[0]) % 100)
    ids = [l.Id for l in levels]
    try:
        index = ids.index(level.Id)
    except ValueError:
        index = 0
    return '{:02d}'.format(index % 100)


def set_level_code(element, param_name, code):
    """Write the code into the chosen parameter, matching its storage type."""
    param = element.LookupParameter(param_name)
    if param is None:
        return False, 'parameter "{}" not on the family'.format(param_name)
    if param.IsReadOnly:
        return False, '"{}" is read only'.format(param_name)
    try:
        if param.StorageType == DB.StorageType.String:
            param.Set(code)
        elif param.StorageType == DB.StorageType.Integer:
            param.Set(int(code))
        elif param.StorageType == DB.StorageType.Double:
            param.Set(float(code))
        else:
            return False, '"{}" cannot hold the level code'.format(param_name)
    except Exception as err:
        return False, '"{}" not set: {}'.format(param_name, err)
    return True, None


def collect_parameter_names(doc, symbol):
    """Writable text/number parameters the BWIC family can carry."""
    names = set()

    def harvest(element):
        for param in element.Parameters:
            try:
                if param.IsReadOnly:
                    continue
                if param.StorageType not in (DB.StorageType.String,
                                             DB.StorageType.Integer,
                                             DB.StorageType.Double):
                    continue
                names.add(param.Definition.Name)
            except Exception:
                continue

    # an existing instance is the most honest source of instance parameters
    for inst in DB.FilteredElementCollector(doc) \
            .OfClass(DB.FamilyInstance).WhereElementIsNotElementType():
        try:
            if inst.Symbol is not None \
                    and inst.Symbol.Family.Name == FAMILY_NAME:
                harvest(inst)
                break
        except Exception:
            continue

    if symbol is not None:
        harvest(symbol)
        # project and shared parameters bound to the family's category
        try:
            category = symbol.Category
            iterator = doc.ParameterBindings.ForwardIterator()
            iterator.Reset()
            while iterator.MoveNext():
                binding = iterator.Current
                if isinstance(binding, DB.InstanceBinding) \
                        and binding.Categories.Contains(category):
                    names.add(iterator.Key.Name)
        except Exception:
            logger.debug('could not read the parameter bindings')

    names.add(LEVEL_PARAM_NAME)
    return sorted(names, key=lambda n: n.lower())


def default_level_param(names):
    """BHE_Level if it is there, otherwise the first name containing Level."""
    for name in names:
        if name == LEVEL_PARAM_NAME:
            return name
    for name in names:
        if LEVEL_PARAM_KEYWORD.lower() in name.lower():
            return name
    return None


# ---------------------------------------------------------------------------
# worksets
# ---------------------------------------------------------------------------
def find_bwic_workset(doc):
    """The family's own workset; else the one named in Settings; else the
    first containing the keyword. A family's workset is never swapped for a
    keyword match -- it was chosen by name."""
    if not doc.IsWorkshared:
        return None
    worksets = list(DB.FilteredWorksetCollector(doc)
                    .OfKind(DB.WorksetKind.UserWorkset))
    if FAMILY_WORKSET and FAMILY_WORKSET != ACTIVE_WORKSET:
        for w in worksets:
            if w.Name == FAMILY_WORKSET:
                return w
        return None
    if WORKSET_NAME:
        for w in worksets:
            if w.Name == WORKSET_NAME:
                return w
    matches = [w for w in worksets
               if WORKSET_KEYWORD.upper() in w.Name.upper()]
    if not matches:
        return None
    return sorted(matches, key=lambda w: w.Name)[0]


def assign_workset(element, workset):
    param = element.get_Parameter(DB.BuiltInParameter.ELEM_PARTITION_PARAM)
    if param is None or param.IsReadOnly:
        return False
    param.Set(eid_value(workset.Id))
    return True


# ---------------------------------------------------------------------------
# Comments logging
# ---------------------------------------------------------------------------
def describe_element(doc, element):
    """'Family: Type' for a loadable family, 'Category: Type' otherwise."""
    try:
        if isinstance(element, DB.FamilyInstance) and element.Symbol is not None:
            fam_name = element.Symbol.Family.Name
            type_name = DB.Element.Name.GetValue(element.Symbol)
        else:
            etype = doc.GetElement(element.GetTypeId())
            type_name = DB.Element.Name.GetValue(etype) if etype else '<no type>'
            if element.Category is not None:
                fam_name = element.Category.Name
            else:
                fam_name = element.GetType().Name
        return '{}: {}'.format(fam_name, type_name)
    except Exception:
        return None


def build_comment(doc, elements):
    """Summarise the selected services: 'Pipe Types: Standard x3_Duct: Rect x2'"""
    order = []
    counts = {}
    for el in elements:
        key = describe_element(doc, el)
        if not key:
            continue
        if key not in counts:
            counts[key] = 0
            order.append(key)
        counts[key] += 1
    parts = []
    for key in order:
        qty = counts[key]
        parts.append('{} x{}'.format(key, qty) if qty > 1 else key)
    return QTY_DELIMITER.join(parts)


# ---------------------------------------------------------------------------
# links
# ---------------------------------------------------------------------------
def loaded_links(doc):
    """Every loaded RevitLinkInstance, as (instance, display name)."""
    found = []
    for inst in DB.FilteredElementCollector(doc) \
            .OfClass(DB.RevitLinkInstance).WhereElementIsNotElementType():
        try:
            if inst.GetLinkDocument() is None:
                continue
            found.append((inst, DB.Element.Name.GetValue(inst)))
        except Exception:
            continue
    return sorted(found, key=lambda pair: pair[1].lower())


def preselected_link(uidoc):
    """The link instance selected in the model when the window opened."""
    try:
        doc = uidoc.Document
        for eid in uidoc.Selection.GetElementIds():
            el = doc.GetElement(eid)
            if isinstance(el, DB.RevitLinkInstance) \
                    and el.GetLinkDocument() is not None:
                return el
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# fire rating
# ---------------------------------------------------------------------------
def parameter_value(holder, name):
    """Readable value of a parameter, or None when it is empty."""
    if holder is None:
        return None
    try:
        param = holder.LookupParameter(name)
    except Exception:
        return None
    if param is None or not param.HasValue:
        return None
    try:
        if param.StorageType == DB.StorageType.String:
            text = param.AsString()
            return text.strip() if text and text.strip() else None
        if param.StorageType == DB.StorageType.Integer:
            value = param.AsInteger()
            return str(value) if value else None
        if param.StorageType == DB.StorageType.Double:
            value = param.AsDouble()
            if abs(value) < 1e-9:
                return None
            return param.AsValueString() or str(value)
        if param.StorageType == DB.StorageType.ElementId:
            eid = param.AsElementId()
            if eid is None or eid_value(eid) <= 0:
                return None
            target = holder.Document.GetElement(eid)
            return DB.Element.Name.GetValue(target) if target else str(eid)
    except Exception:
        return None
    return None


def fire_rating(wall):
    """The wall's fire rating target, instance first then type, else None."""
    value = parameter_value(wall, FIRE_PARAM)
    if value:
        return value
    try:
        wtype = wall.Document.GetElement(wall.GetTypeId())
    except Exception:
        wtype = None
    return parameter_value(wtype, FIRE_PARAM)


def wall_type_name(wall):
    try:
        wtype = wall.Document.GetElement(wall.GetTypeId())
        return DB.Element.Name.GetValue(wtype) or ''
    except Exception:
        return ''


def wall_family_name(wall):
    try:
        wtype = wall.Document.GetElement(wall.GetTypeId())
        return wtype.FamilyName or ''
    except Exception:
        return ''


def is_blockwork(wall):
    """Blockwork is read off the wall's type name or its family name."""
    keyword = BLOCKWORK_KEYWORD.upper()
    return (keyword in wall_type_name(wall).upper()
            or keyword in wall_family_name(wall).upper())


def walls_to_penetrate(link_doc):
    """Walls needing BWICs, as (wall, kind, description).

    Two reasons a wall qualifies: a value in FIRE_PARAM, or BLK in its type
    name. A wall that is both is treated as blockwork, because that is the
    type you asked for and it is the more permissive of the two on grouping.
    """
    walls = []
    for wall in DB.FilteredElementCollector(link_doc) \
            .OfClass(DB.Wall).WhereElementIsNotElementType():
        try:
            if not isinstance(wall.Location, DB.LocationCurve):
                continue
        except Exception:
            continue

        try:
            rating = fire_rating(wall)
            blockwork = is_blockwork(wall)
        except Exception:
            continue

        if blockwork:
            walls.append((wall, 'blockwork', wall_type_name(wall)))
        elif rating:
            walls.append((wall, 'fire', rating))
    return walls


# ---------------------------------------------------------------------------
# boxes and solids
# ---------------------------------------------------------------------------
def world_box(element, transform=None):
    """Axis aligned (min, max) of an element in host coordinates."""
    bb = element.get_BoundingBox(None)
    if bb is None:
        return None
    pts = []
    tf = bb.Transform
    for x in (bb.Min.X, bb.Max.X):
        for y in (bb.Min.Y, bb.Max.Y):
            for z in (bb.Min.Z, bb.Max.Z):
                pt = tf.OfPoint(DB.XYZ(x, y, z))
                if transform is not None:
                    pt = transform.OfPoint(pt)
                pts.append(pt)
    return (DB.XYZ(min(p.X for p in pts), min(p.Y for p in pts),
                   min(p.Z for p in pts)),
            DB.XYZ(max(p.X for p in pts), max(p.Y for p in pts),
                   max(p.Z for p in pts)))


def boxes_overlap(a, b, tol=1e-6):
    """True when two (min, max) boxes share volume on all three axes."""
    if a is None or b is None:
        return False
    return (a[0].X < b[1].X - tol and b[0].X < a[1].X - tol
            and a[0].Y < b[1].Y - tol and b[0].Y < a[1].Y - tol
            and a[0].Z < b[1].Z - tol and b[0].Z < a[1].Z - tol)


def outline_from_box(box, pad=0.0):
    return DB.Outline(DB.XYZ(box[0].X - pad, box[0].Y - pad, box[0].Z - pad),
                      DB.XYZ(box[1].X + pad, box[1].Y + pad, box[1].Z + pad))


def wall_solid(wall, transform):
    """One solid for the wall, in host coordinates."""
    options = DB.Options()
    options.DetailLevel = DB.ViewDetailLevel.Medium
    options.ComputeReferences = False
    options.IncludeNonVisibleObjects = False

    solids = []

    def walk(geometry):
        for item in geometry:
            if isinstance(item, DB.Solid):
                try:
                    if item.Volume > 1e-9:
                        solids.append(item)
                except Exception:
                    continue
            elif isinstance(item, DB.GeometryInstance):
                walk(item.GetInstanceGeometry())

    try:
        walk(wall.get_Geometry(options))
    except Exception:
        return None
    if not solids:
        return None

    solid = solids[0]
    for other in solids[1:]:
        try:
            solid = DB.BooleanOperationsUtils.ExecuteBooleanOperation(
                solid, other, DB.BooleanOperationsType.Union)
        except Exception:
            if other.Volume > solid.Volume:
                solid = other

    # always copy, even at the origin -- the intersects filter wants a solid
    # that does not belong to the linked document
    try:
        solid = DB.SolidUtils.CreateTransformed(
            solid, transform if transform is not None else DB.Transform.Identity)
    except Exception:
        return None
    return solid


def services_in_view(doc, view):
    """Every pipe and cable tray visible in the view.

    This is what makes the run per floor. A plan only shows the services on
    its own storey -- its view range decides that, and Revit does the work --
    so scoping to what the view shows is scoping to the floor, without the
    tool having to work out where the floor is. Nothing else needs to know
    about levels, view ranges or crop boxes.
    """
    categories = List[DB.BuiltInCategory]()
    for name in TARGET_CATEGORIES:
        categories.Add(bic(name))
    try:
        return list(DB.FilteredElementCollector(doc, view.Id)
                    .WhereElementIsNotElementType()
                    .WherePasses(DB.ElementMulticategoryFilter(categories)))
    except Exception as err:
        logger.debug('could not collect the services in view: {}'.format(err))
        return []


def combined_box(elements, pad_ft=0.0):
    """One box round everything given, in host coordinates, or None."""
    boxes = [world_box(element) for element in elements]
    boxes = [box for box in boxes if box is not None]
    if not boxes:
        return None
    return (DB.XYZ(min(b[0].X for b in boxes) - pad_ft,
                   min(b[0].Y for b in boxes) - pad_ft,
                   min(b[0].Z for b in boxes) - pad_ft),
            DB.XYZ(max(b[1].X for b in boxes) + pad_ft,
                   max(b[1].Y for b in boxes) + pad_ft,
                   max(b[1].Z for b in boxes) + pad_ft))


def boxes_touch(a, b):
    """True when two boxes meet or overlap. Touching counts."""
    if a is None or b is None:
        return True
    return not (a[1].X < b[0].X or b[1].X < a[0].X
                or a[1].Y < b[0].Y or b[1].Y < a[0].Y
                or a[1].Z < b[0].Z or b[1].Z < a[0].Z)


def view_outline(view):
    """Crop box or section box of the view, in host coordinates, or None."""
    flat = not isinstance(view, DB.View3D)
    try:
        if isinstance(view, DB.View3D) and view.IsSectionBoxActive:
            box = view.GetSectionBox()
            flat = False
        elif view.CropBoxActive:
            box = view.CropBox
        else:
            return None
        tf = box.Transform
        pts = []
        for x in (box.Min.X, box.Max.X):
            for y in (box.Min.Y, box.Max.Y):
                for z in (box.Min.Z, box.Max.Z):
                    pts.append(tf.OfPoint(DB.XYZ(x, y, z)))
        # only a 3D section box is trusted vertically -- a plan crop carries
        # the view range, which would throw away perfectly good walls
        z_min = -1.0e6 if flat else min(p.Z for p in pts)
        z_max = 1.0e6 if flat else max(p.Z for p in pts)
        return DB.Outline(
            DB.XYZ(min(p.X for p in pts), min(p.Y for p in pts), z_min),
            DB.XYZ(max(p.X for p in pts), max(p.Y for p in pts), z_max))
    except Exception:
        return None


def outline_hits(outline, box, pad=0.0):
    if outline is None or box is None:
        return True
    return not (box[1].X < outline.MinimumPoint.X - pad
                or box[0].X > outline.MaximumPoint.X + pad
                or box[1].Y < outline.MinimumPoint.Y - pad
                or box[0].Y > outline.MaximumPoint.Y + pad
                or box[1].Z < outline.MinimumPoint.Z - pad
                or box[0].Z > outline.MaximumPoint.Z + pad)


# ---------------------------------------------------------------------------
# finding the services that pass through a wall
# ---------------------------------------------------------------------------
def bic(name):
    return getattr(DB.BuiltInCategory, name)


def bic_id(name):
    return eid_value(DB.ElementId(bic(name)))


def category_id(element):
    try:
        return eid_value(element.Category.Id)
    except Exception:
        return None


def element_direction(element):
    """Unit direction of a linear element, or None."""
    try:
        loc = element.Location
        if isinstance(loc, DB.LocationCurve):
            crv = loc.Curve
            vec = crv.GetEndPoint(1) - crv.GetEndPoint(0)
            if vec.GetLength() > 1e-9:
                return vec.Normalize()
    except Exception:
        pass
    return None


def crosses_wall(element, frame):
    """True when the element runs through the wall rather than along it.

    The normal is taken where the element meets the wall, not at the wall's
    midpoint, so a curved wall is judged fairly along its whole length.
    """
    direction = element_direction(element)
    if direction is None:
        return True                      # not linear -- trust the solid test

    box = world_box(element)
    if box is None:
        return True
    station = frame.station(box_centre(box))
    if station is None:
        return True
    _, _, normal = frame.frame_at(station[0])
    return abs(direction.DotProduct(normal)) >= MIN_CROSSING_DOT


def services_through_wall(doc, view, solid, wall_box, frame):
    """Pipes and cable trays in the view that pass through the wall solid."""
    categories = List[DB.BuiltInCategory]()
    for name in TARGET_CATEGORIES:
        categories.Add(bic(name))

    try:
        collector = DB.FilteredElementCollector(doc, view.Id) \
            .WhereElementIsNotElementType() \
            .WherePasses(DB.ElementMulticategoryFilter(categories)) \
            .WherePasses(DB.BoundingBoxIntersectsFilter(
                outline_from_box(wall_box, mm_to_ft(10.0)))) \
            .WherePasses(DB.ElementIntersectsSolidFilter(solid))
        found = list(collector)
    except Exception as err:
        logger.debug('collector failed on a wall: {}'.format(err))
        return []

    return [el for el in found if crosses_wall(el, frame)]


# ---------------------------------------------------------------------------
# the bit of a service that is actually inside the wall
# ---------------------------------------------------------------------------
def element_solids(element):
    """Solids of an element in host coordinates."""
    options = DB.Options()
    options.DetailLevel = DB.ViewDetailLevel.Medium
    options.ComputeReferences = False
    options.IncludeNonVisibleObjects = False

    solids = []

    def walk(geometry):
        for item in geometry:
            if isinstance(item, DB.Solid):
                try:
                    if item.Volume > 1e-9:
                        solids.append(item)
                except Exception:
                    continue
            elif isinstance(item, DB.GeometryInstance):
                walk(item.GetInstanceGeometry())

    try:
        walk(element.get_Geometry(options))
    except Exception:
        return []
    return solids


def solid_corners(solid):
    try:
        bb = solid.GetBoundingBox()
    except Exception:
        return []
    tf = bb.Transform
    pts = []
    for x in (bb.Min.X, bb.Max.X):
        for y in (bb.Min.Y, bb.Max.Y):
            for z in (bb.Min.Z, bb.Max.Z):
                pts.append(tf.OfPoint(DB.XYZ(x, y, z)))
    return pts


def cross_section_half(element, direction):
    """Half width / half height of a linear element, per world axis."""
    bb = element.get_BoundingBox(None)
    if bb is None:
        return (mm_to_ft(50.0),) * 3
    tf = bb.Transform
    lo, hi = tf.OfPoint(bb.Min), tf.OfPoint(bb.Max)
    spans = [abs(hi.X - lo.X), abs(hi.Y - lo.Y), abs(hi.Z - lo.Z)]
    # the axis the element runs along contributes its length, not its size
    axis = 0
    if direction is not None:
        weights = [abs(direction.X), abs(direction.Y), abs(direction.Z)]
        axis = weights.index(max(weights))
    halves = [span / 2.0 for span in spans]
    halves[axis] = min(halves)
    return halves


def segment_corners(element, solid):
    """Corners of the element where its centre line passes into the solid."""
    curve = None
    try:
        loc = element.Location
        if isinstance(loc, DB.LocationCurve):
            curve = loc.Curve
    except Exception:
        curve = None
    if curve is None:
        return []

    try:
        result = solid.IntersectWithCurve(
            curve, DB.SolidCurveIntersectionOptions())
    except Exception:
        return []
    if result is None or result.SegmentCount == 0:
        return []

    direction = element_direction(element)
    hx, hy, hz = cross_section_half(element, direction)

    corners = []
    for index in range(result.SegmentCount):
        segment = result.GetCurveSegment(index)
        for end in (segment.GetEndPoint(0), segment.GetEndPoint(1)):
            for sx in (-hx, hx):
                for sy in (-hy, hy):
                    for sz in (-hz, hz):
                        corners.append(
                            DB.XYZ(end.X + sx, end.Y + sy, end.Z + sz))
    return corners


def crossing_corners(element, solid):
    """The element's footprint inside the wall.

    A pipe crossing at an angle has a bounding box the length of the whole
    pipe, so measuring the raw box would size the opening off the run rather
    than the penetration. This clips the element to the wall solid instead --
    boolean intersection first, centre line intersection as the fallback,
    and only then the whole element.
    """
    corners = []
    for piece in element_solids(element):
        try:
            cut = DB.BooleanOperationsUtils.ExecuteBooleanOperation(
                piece, solid, DB.BooleanOperationsType.Intersect)
        except Exception:
            continue
        if cut is None:
            continue
        try:
            if cut.Volume < 1e-9:
                continue
        except Exception:
            continue
        corners.extend(solid_corners(cut))
    if corners:
        return corners

    corners = segment_corners(element, solid)
    if corners:
        return corners

    # deliberately no fall back to the whole element. Its box is as long as
    # the run, so its centre sits somewhere out in the middle of the service
    # rather than at the wall -- which is how BWICs ended up floating in space
    # with no wall anywhere near them.
    logger.debug('could not measure element {} at the wall'.format(
        eid_value(element.Id)))
    return []


def corners_box(corners):
    if not corners:
        return None
    return (DB.XYZ(min(p.X for p in corners), min(p.Y for p in corners),
                   min(p.Z for p in corners)),
            DB.XYZ(max(p.X for p in corners), max(p.Y for p in corners),
                   max(p.Z for p in corners)))


# ---------------------------------------------------------------------------
# grouping
# ---------------------------------------------------------------------------
def bip(name):
    """A BuiltInParameter by name, or None if this Revit does not have it."""
    return getattr(DB.BuiltInParameter, name, None)


def builtin_length(element, names):
    """First of these built-in parameters carrying a length, in feet."""
    for name in names:
        parameter_id = bip(name)
        if parameter_id is None:
            continue
        try:
            parameter = element.get_Parameter(parameter_id)
        except Exception:
            continue
        if parameter is None or not parameter.HasValue:
            continue
        try:
            value = parameter.AsDouble()
        except Exception:
            continue
        if value > 1e-9:
            return value
    return None


def section_width(element):
    """How wide the service is across its own axis, or None.

    This is the width the opening would need if the service ran square
    through the wall -- an outside diameter for a pipe, the tray width for a
    cable tray. It is deliberately NOT measured off the crossing footprint,
    which stretches with the angle of the run.
    """
    category = category_id(element)

    if category == bic_id(CAT_PIPES):
        width = builtin_length(element, ['RBS_PIPE_OUTER_DIAMETER',
                                         'RBS_PIPE_OUTER_DIAM_PARAM',
                                         'RBS_PIPE_DIAMETER_PARAM'])
        if width:
            return width
        try:
            if element.Diameter > 1e-9:
                return element.Diameter
        except Exception:
            pass

    elif category == bic_id(CAT_TRAYS):
        width = builtin_length(element, ['RBS_CABLETRAY_WIDTH_PARAM',
                                         'RBS_CURVE_WIDTH_PARAM'])
        if width:
            return width
        try:
            if element.Width > 1e-9:
                return element.Width
        except Exception:
            pass

    return None


def wall_extents(corners, frame, width=None):
    """(u_min, u_max, z_min, z_max) along the wall, or None.

    u is distance along the wall, so grouping distances stay honest on a
    curved wall instead of collapsing onto a single direction.

    Given a width, the along-wall extent becomes that width centred on the
    middle of the crossing rather than the full footprint the crossing cuts.
    That is what keeps a skewed service from earning an opening longer than
    the service is wide.
    """
    if not corners:
        return None
    stations = []
    for point in corners:
        station = frame.station(point)
        if station is None:
            return None
        stations.append(station[0])

    u_min, u_max = min(stations), max(stations)
    if width is not None and width > 1e-9:
        centre = (u_min + u_max) / 2.0
        u_min, u_max = centre - width / 2.0, centre + width / 2.0

    z_values = [p.Z for p in corners]
    return (u_min, u_max, min(z_values), max(z_values))


def union_extents(spans):
    """The combined (u_min, u_max, z_min, z_max) of a group's members."""
    spans = [s for s in spans if s is not None]
    if not spans:
        return None
    return (min(s[0] for s in spans), max(s[1] for s in spans),
            min(s[2] for s in spans), max(s[3] for s in spans))


def gap_between(a, b):
    """Clear distance between two extents in the wall plane, 0 if they touch."""
    du = max(0.0, a[0] - b[1], b[0] - a[1])
    dz = max(0.0, a[2] - b[3], b[2] - a[3])
    return math.sqrt(du * du + dz * dz)


def cluster_by_gap(entries, gap_ft):
    """Union-find over (element, extents) pairs. Grouping is transitive."""
    count = len(entries)
    parent = list(range(count))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    for i in range(count):
        for j in range(i + 1, count):
            if gap_between(entries[i][1], entries[j][1]) <= gap_ft + 1e-9:
                union(i, j)

    groups = {}
    for i in range(count):
        groups.setdefault(find(i), []).append(entries[i][0])
    return list(groups.values())


# ---------------------------------------------------------------------------
# what is already there
# ---------------------------------------------------------------------------
def existing_bwic_boxes(doc):
    """Boxes of every BWIC instance already in the model."""
    boxes = []
    for inst in DB.FilteredElementCollector(doc) \
            .OfClass(DB.FamilyInstance).WhereElementIsNotElementType():
        try:
            if inst.Symbol is None or inst.Symbol.Family is None:
                continue
            if inst.Symbol.Family.Name != FAMILY_NAME:
                continue
        except Exception:
            continue
        box = world_box(inst)
        if box is not None:
            boxes.append(box)
    return boxes


def group_box(corners):
    """Combined box of a group's crossing corners, in host coordinates."""
    return corners_box(corners)


# ---------------------------------------------------------------------------
# the placement itself
# ---------------------------------------------------------------------------
def place_one(doc, services, wall, transform, clearance_ft, symbol,
              options, workset, corners=None, span=None):
    """Places and sizes one BWIC around a group of services.

    Unchanged from Place BWIC Horizontal apart from two things: it never pins,
    and it will work from the corners and span handed to it rather than the
    raw bounding boxes of the services, so the opening is sized on the
    crossing rather than on the whole run. Returns (instance, notes list).
    """
    notes = []

    thickness = get_wall_thickness(wall)
    if thickness is None:
        return None, ['could not read a thickness from that wall']

    wall_curve = wall.Location.Curve.CreateTransformed(transform)
    frame = WallFrame(wall_curve)

    if not corners:
        corners = []
        for el in services:
            corners.extend(bbox_corners(el))
    if not corners:
        return None, ['the selected elements have no geometry to measure']

    # where the group meets the wall, measured along the wall itself
    stations = []
    offsets = []
    for point in corners:
        station = frame.station(point)
        if station is None:
            return None, ['could not relate this group to the wall']
        stations.append(station[0])
        offsets.append(station[1])

    # the corners come from the intersection of the services with the wall
    # solid, so they sit inside the wall -- within half its thickness of the
    # centre line. Anything further out was never really at the wall, and
    # placing on it is how BWICs ended up in open space.
    drift = max(offsets)
    if drift > (thickness / 2.0) + mm_to_ft(OFF_WALL_TOLERANCE_MM):
        return None, ['the crossing measures {:.0f} mm off the wall centre '
                      'line'.format(ft_to_mm(drift))]

    # the span worked out during grouping already carries the skew correction,
    # so use it rather than re-measuring the raw footprint here
    if span is not None:
        u_min, u_max, z_min, z_max = span
    else:
        u_min, u_max = min(stations), max(stations)
        z_values = [p.Z for p in corners]
        z_min, z_max = min(z_values), max(z_values)

    u_mid = (u_min + u_max) / 2.0

    width = round_up_ft((u_max - u_min) + 2 * clearance_ft)
    height = round_up_ft((z_max - z_min) + 2 * clearance_ft)
    length = thickness

    # the middle of the crossing, ON the wall. point_at clamps to the wall's
    # ends, so there is no arithmetic that can walk the BWIC off it.
    plan_pt, along, normal = frame.frame_at(u_mid)

    # midway between the bottom of the lowest service and the top of the
    # highest, so the opening encompasses the whole selection centrally
    if ELEVATION_MODE == 'highest_service':
        target_z = max(element_centre_z(el) for el in services)
    else:
        target_z = (z_min + z_max) / 2.0

    if ORIGIN_VERTICAL == 'bottom':
        origin_z = target_z - height / 2.0
    elif ORIGIN_VERTICAL == 'top':
        origin_z = target_z + height / 2.0
    else:
        origin_z = target_z

    target_point = DB.XYZ(plan_pt.X, plan_pt.Y, origin_z)

    levels = sorted_levels(doc)
    if not levels:
        return None, ['this project has no levels']
    level = level_below(levels, origin_z)

    if not symbol.IsActive:
        symbol.Activate()
        doc.Regenerate()

    # if BGL_* live on the type, work on a dedicated type per size
    place_symbol = symbol
    if [n for n in (P_LENGTH, P_WIDTH, P_HEIGHT)
            if has_length_param(symbol, n)] \
            and DUPLICATE_TYPE_IF_TYPE_PARAMS:
        new_name = unique_type_name(symbol, length, width, height)
        existing = find_symbol_by_name(doc, symbol.Family, new_name)
        place_symbol = existing if existing is not None \
            else symbol.Duplicate(new_name)
        if not place_symbol.IsActive:
            place_symbol.Activate()
        doc.Regenerate()
        notes.append('sized on type "{}"'.format(new_name))

    for pname, pvalue in ((P_LENGTH, length), (P_WIDTH, width), (P_HEIGHT, height)):
        if has_length_param(place_symbol, pname):
            ok, msg = set_length_param(place_symbol, pname, pvalue)
            if not ok:
                notes.append(msg)
    doc.Regenerate()

    try:
        instance = doc.Create.NewFamilyInstance(
            target_point, place_symbol, level, StructuralType.NonStructural)
    except Exception:
        instance = doc.Create.NewFamilyInstance(
            target_point, place_symbol, StructuralType.NonStructural)
    doc.Regenerate()

    for pname, pvalue in ((P_LENGTH, length), (P_WIDTH, width), (P_HEIGHT, height)):
        if has_length_param(instance, pname):
            ok, msg = set_length_param(instance, pname, pvalue)
            if not ok:
                notes.append(msg)
        elif not has_length_param(place_symbol, pname):
            notes.append('{} not found on the family'.format(pname))
    doc.Regenerate()

    # align the Front/Back reference plane to the wall centre line
    try:
        facing = instance.FacingOrientation
        facing = DB.XYZ(facing.X, facing.Y, 0)
        if facing.GetLength() > 1e-9:
            angle = facing.Normalize().AngleOnPlaneTo(normal, DB.XYZ.BasisZ)
            if abs(angle) > 1e-9:
                axis = DB.Line.CreateBound(target_point,
                                           target_point + DB.XYZ.BasisZ)
                DB.ElementTransformUtils.RotateElement(doc, instance.Id, axis, angle)
    except Exception as err:
        notes.append('rotation skipped: {}'.format(err))
    doc.Regenerate()

    loc = instance.Location
    if isinstance(loc, DB.LocationPoint):
        delta = target_point - loc.Point
        if delta.GetLength() > 1e-9:
            DB.ElementTransformUtils.MoveElement(doc, instance.Id, delta)
    doc.Regenerate()

    # workset -- before pinning, and before anything reads the instance back
    if options.get('use_workset'):
        if workset is None:
            notes.append('workset "{}" not found'.format(
                FAMILY_WORKSET or WORKSET_NAME or WORKSET_KEYWORD))
        elif assign_workset(instance, workset):
            notes.append('workset "{}"'.format(workset.Name))
        else:
            notes.append('could not set the workset')

    # level code, e.g. L00 -> 00, LRF -> 05
    level_param = options.get('level_param')
    if level_param:
        code = level_code(level, levels)
        ok, msg = set_level_code(instance, level_param, code)
        if ok:
            notes.append('{} = {} ({})'.format(level_param, code, level.Name))
        else:
            notes.append(msg)
    else:
        notes.append('level {}'.format(level.Name))

    if options.get('log_comments'):
        try:
            comment = build_comment(doc, services)
            if comment:
                cparam = instance.get_Parameter(
                    DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
                if cparam is not None and not cparam.IsReadOnly:
                    cparam.Set(comment)
                    notes.append('comments: {}'.format(comment))
                else:
                    notes.append('Comments parameter is not writable')
            else:
                notes.append('nothing to log to Comments')
        except Exception as err:
            notes.append('comments log failed: {}'.format(err))

    notes.append('L {:.0f} / W {:.0f} / H {:.0f} mm at {:.0f} mm'.format(
        ft_to_mm(length), ft_to_mm(width), ft_to_mm(height), ft_to_mm(target_z)))
    return instance, notes


# ---------------------------------------------------------------------------
# keeping Revit quiet
# ---------------------------------------------------------------------------
class WarningSwallower(DB.IFailuresPreprocessor):
    """Dismisses warning dialogs and keeps a tally of what it dismissed.

    A run touching a whole view can raise the same warning hundreds of times.
    Left alone each one is a modal dialog in the middle of the sweep, so they
    are dismissed here and reported once at the end instead. Errors are left
    for Revit to deal with -- they mean the placement genuinely failed.
    """

    def __init__(self):
        self.counts = {}
        self.order = []
        self.errors = 0

    def _record(self, text):
        if text not in self.counts:
            self.counts[text] = 0
            self.order.append(text)
        self.counts[text] += 1

    def PreprocessFailures(self, accessor):
        try:
            messages = list(accessor.GetFailureMessages())
        except Exception:
            return DB.FailureProcessingResult.Continue

        for failure in messages:
            try:
                text = failure.GetDescriptionText()
            except Exception:
                text = 'unnamed Revit message'
            if not text:
                text = 'unnamed Revit message'
            try:
                severity = failure.GetSeverity()
            except Exception:
                severity = DB.FailureSeverity.Warning

            if severity == DB.FailureSeverity.Warning:
                self._record(text)
                try:
                    accessor.DeleteWarning(failure)
                except Exception:
                    pass
            else:
                self.errors += 1
                self._record('{} (error)'.format(text))

        return DB.FailureProcessingResult.Continue

    def summary(self):
        """['message x12', ...], busiest first."""
        return ['{} x{}'.format(text, self.counts[text])
                if self.counts[text] > 1 else text
                for text in sorted(self.order,
                                   key=lambda t: -self.counts[t])]


def quiet_transaction(doc, name, swallower):
    """A started transaction that will not stop to ask about warnings."""
    trans = DB.Transaction(doc, name)
    trans.Start()
    if swallower is not None:
        try:
            options = trans.GetFailureHandlingOptions()
            options = options.SetFailuresPreprocessor(swallower)
            options = options.SetClearAfterRollback(True)
            trans.SetFailureHandlingOptions(options)
        except Exception as err:
            logger.debug('could not attach the failure handler: {}'.format(err))
    return trans


# ---------------------------------------------------------------------------
# not placing the same BWIC twice
# ---------------------------------------------------------------------------
def box_centre(box):
    return DB.XYZ((box[0].X + box[1].X) / 2.0,
                  (box[0].Y + box[1].Y) / 2.0,
                  (box[0].Z + box[1].Z) / 2.0)


def box_size(box):
    return (abs(box[1].X - box[0].X),
            abs(box[1].Y - box[0].Y),
            abs(box[1].Z - box[0].Z))


def already_placed_here(box, records, tolerance_ft):
    """True when a BWIC of the same size already sits at this spot.

    A service crossing two walls that occupy the same space -- a stacked wall,
    a wall duplicated in the link, a wall and its fire lining -- produces the
    same opening twice. Revit calls those identical instances and warns about
    double counting in schedules, so the second one is dropped here.
    """
    if box is None:
        return False
    centre, size = box_centre(box), box_size(box)
    for record in records:
        other = record.get('box')
        if other is None:
            continue
        if centre.DistanceTo(box_centre(other)) > tolerance_ft:
            continue
        if all(abs(a - b) <= tolerance_ft
               for a, b in zip(size, box_size(other))):
            return True
    return False


# ---------------------------------------------------------------------------
# clashes between the BWICs this run places
# ---------------------------------------------------------------------------
def find_clashes(records, tolerance_ft):
    """Indices of records whose boxes overlap another in all three axes.

    A pipe group and a tray group can sit close enough on the same wall that
    their openings overlap. Neither is wrong on its own, and merging them
    would break the grouping rules, so both are placed and both are flagged.
    """
    clashing = set()
    pairs = []
    for i in range(len(records)):
        for j in range(i + 1, len(records)):
            if boxes_overlap(records[i]['box'], records[j]['box'],
                             tolerance_ft):
                clashing.add(i)
                clashing.add(j)
                pairs.append((i, j))
    return sorted(clashing), pairs


def view_takes_detail_lines(view):
    """Detail lines are view specific and 3D views will not take them."""
    if view is None or view.IsTemplate:
        return False
    return view.ViewType in (DB.ViewType.FloorPlan, DB.ViewType.CeilingPlan,
                             DB.ViewType.EngineeringPlan, DB.ViewType.AreaPlan,
                             DB.ViewType.Section, DB.ViewType.Elevation,
                             DB.ViewType.Detail, DB.ViewType.DraftingView)


def marker_line_style(doc, name, rgb):
    """A line style for the marks, created in the given colour if new."""
    categories = doc.Settings.Categories
    try:
        lines = categories.get_Item(DB.BuiltInCategory.OST_Lines)
    except Exception:
        return None

    subcategory = None
    for sub in lines.SubCategories:
        if sub.Name == name:
            subcategory = sub
            break

    if subcategory is None:
        try:
            subcategory = categories.NewSubcategory(lines, name)
            subcategory.LineColor = DB.Color(rgb[0], rgb[1], rgb[2])
            try:
                subcategory.SetLineWeight(
                    5, DB.GraphicsStyleType.Projection)
            except Exception:
                pass
        except Exception as err:
            logger.debug('could not create the line style: {}'.format(err))
            return None

    try:
        return subcategory.GetGraphicsStyle(DB.GraphicsStyleType.Projection)
    except Exception:
        return None


def view_plane_rectangle(view, box, margin_ft):
    """Rectangle in the plane of the view around a 3D box."""
    origin = view.Origin
    right = view.RightDirection
    up = view.UpDirection

    corners = []
    for x in (box[0].X, box[1].X):
        for y in (box[0].Y, box[1].Y):
            for z in (box[0].Z, box[1].Z):
                corners.append(DB.XYZ(x, y, z))

    a_values = [(p - origin).DotProduct(right) for p in corners]
    b_values = [(p - origin).DotProduct(up) for p in corners]
    a_min, a_max = min(a_values) - margin_ft, max(a_values) + margin_ft
    b_min, b_max = min(b_values) - margin_ft, max(b_values) + margin_ft

    def point(a, b):
        return origin + right.Multiply(a) + up.Multiply(b)

    pts = [point(a_min, b_min), point(a_max, b_min),
           point(a_max, b_max), point(a_min, b_max)]

    lines = []
    for index in range(4):
        start, end = pts[index], pts[(index + 1) % 4]
        if start.DistanceTo(end) > 1e-6:
            lines.append(DB.Line.CreateBound(start, end))
    return lines


def mark_boxes(doc, view, boxes, margin_ft, style):
    """Draw a rectangle around each box in the view. Returns the line ids."""
    created = []
    for box in boxes:
        for line in view_plane_rectangle(view, box, margin_ft):
            try:
                curve = doc.Create.NewDetailCurve(view, line)
            except Exception as err:
                logger.debug('detail line refused: {}'.format(err))
                continue
            if style is not None:
                try:
                    curve.LineStyle = style
                except Exception:
                    pass
            created.append(curve.Id)
    return created


def group_marks(doc, line_ids, name):
    """Gather the marks into one named group. Returns the name, or None."""
    if not line_ids:
        return None
    ids = List[DB.ElementId]()
    for eid in line_ids:
        ids.Add(eid)
    try:
        group = doc.Create.NewGroup(ids)
    except Exception as err:
        logger.debug('could not group the marks: {}'.format(err))
        return None

    try:
        group.GroupType.Name = name
    except Exception:
        try:
            group.GroupType.Name = '{} {}'.format(name, eid_value(group.Id))
            name = group.GroupType.Name
        except Exception:
            logger.debug('the group kept its default name')
            return None
    return name


# ---------------------------------------------------------------------------
# the global sweep
# ---------------------------------------------------------------------------
def run_global_placement(uiapp, settings, report):
    """Walk every wall in the link that needs BWICs and place them.

    Returns a summary dict for the results window, or None when the run could
    not start.
    """
    uidoc = uiapp.ActiveUIDocument
    if uidoc is None:
        report('No active Revit document.')
        return

    doc = uidoc.Document
    view = doc.ActiveView
    log = []

    def note(line):
        log.append(line)
        logger.debug(line)

    if view is None or view.IsTemplate \
            or isinstance(view, (DB.ViewSheet, DB.ViewSchedule)):
        report('Open a model view -- this tool works on the active view.')
        return

    symbols = family_symbols(doc)
    default_symbol = find_family_symbol(doc)
    if not symbols or default_symbol is None:
        report('The family "{}" is not loaded in this project.'.format(
            FAMILY_NAME))
        return

    symbol_for = {}
    for kind, type_name in (('fire', TYPE_FIRE), ('blockwork', TYPE_BLOCKWORK)):
        chosen = symbols.get(type_name)
        if chosen is None:
            chosen = default_symbol
            note('Type "{}" is not in the family -- {} walls fall back to '
                 '"{}".'.format(type_name, kind,
                                DB.Element.Name.GetValue(default_symbol)))
        symbol_for[kind] = chosen

    link = doc.GetElement(settings['link_id']) \
        if settings.get('link_id') else None
    if not isinstance(link, DB.RevitLinkInstance):
        report('Choose the link to read the walls from.')
        return
    link_doc = link.GetLinkDocument()
    if link_doc is None:
        report('That link is not loaded.')
        return
    transform = link.GetTotalTransform()

    clearance_mm = settings.get('clearance_mm') or 50.0
    if FAMILY_CLEARANCE:
        try:
            clearance_mm = float(FAMILY_CLEARANCE)
            note('Clearance {:g} mm from the family\'s Family settings.'
                 .format(clearance_mm))
        except ValueError:
            pass
    clearance_ft = mm_to_ft(clearance_mm)
    gaps = {bic_id(CAT_PIPES): mm_to_ft(settings['gap_pipes_mm']),
            bic_id(CAT_TRAYS): mm_to_ft(settings['gap_trays_mm'])}

    options = {'log_comments': settings.get('log_comments', True),
               'use_workset': settings.get('use_workset', True),
               'level_param': settings.get('level_param'),
               'pin': False}

    if FAMILY_WORKSET == ACTIVE_WORKSET:
        # the family's Family settings say: leave it on the active workset
        options['use_workset'] = False
    workset = find_bwic_workset(doc) if options['use_workset'] else None
    if options['use_workset'] and workset is None:
        if doc.IsWorkshared and FAMILY_WORKSET:
            note('Workset "{}" from the family\'s Family settings is not in '
                 'this model -- BWICs land on the active workset.'.format(
                     FAMILY_WORKSET))
        elif doc.IsWorkshared:
            note('No workset containing "{}" -- BWICs land on the active '
                 'workset.'.format(WORKSET_KEYWORD))
        else:
            note('This model is not workshared -- skipping the workset step.')

    walls = walls_to_penetrate(link_doc)
    if not walls:
        report('No walls in "{}" are fire rated ({}) or blockwork ({} in the '
               'type name).'.format(DB.Element.Name.GetValue(link),
                                    FIRE_PARAM, BLOCKWORK_KEYWORD))
        return

    crop = view_outline(view)

    # the services on show in this view are the run's scope, and therefore
    # its floor. No services, nothing to do -- say so rather than grinding
    # through every wall in the link for nothing.
    visible_services = services_in_view(doc, view)
    if not visible_services:
        report('No pipes or cable trays are visible in "{}". Open the plan '
               'for the floor you want to do and run it again.'.format(
                   view.Name))
        return
    reach = combined_box(visible_services, mm_to_ft(SERVICE_REACH_MM))

    # BWICs already in the model before this run -- these are the ones that
    # mean "already resolved". Anything placed during the run goes into
    # placed_records instead, and is clash checked rather than skipped.
    prior = existing_bwic_boxes(doc) if SKIP_EXISTING else []
    placed_records = []

    fire_count = len([w for w in walls if w[1] == 'fire'])
    block_count = len(walls) - fire_count
    note('{} wall{} to look at in "{}" -- {} fire rated, {} blockwork.'.format(
        len(walls), '' if len(walls) == 1 else 's',
        DB.Element.Name.GetValue(link), fire_count, block_count))
    note('{} pipe / cable tray element{} visible in "{}" -- that is the '
         'floor this run covers.'.format(
             len(visible_services), '' if len(visible_services) == 1 else 's',
             view.Name))
    if crop is not None:
        note('Limited to the active view\'s crop / section box.')

    swallower = WarningSwallower() if SUPPRESS_WARNINGS else None
    duplicate_tol = mm_to_ft(DUPLICATE_TOLERANCE_MM)

    out_of_reach = 0
    walls_hit = 0
    groups_found = 0
    placed = 0
    skipped_existing = 0
    duplicates = 0
    unmeasured = 0
    failures = []
    clashing = []
    pairs = []
    review_ids = []
    group_name = None
    failed_group_name = None

    group_holder = DB.TransactionGroup(doc, 'BWIC Global Placement')
    group_holder.Start()
    try:
        for wall, kind, description in walls:
            wall_box = world_box(wall, transform)
            if wall_box is None or not outline_hits(crop, wall_box):
                continue
            # nowhere near anything visible in this view, so nothing on this
            # floor can pass through it
            if not boxes_touch(wall_box, reach):
                out_of_reach += 1
                continue

            solid = wall_solid(wall, transform)
            if solid is None:
                failures.append({'text': 'wall {} ({}): no solid geometry'
                                         .format(eid_value(wall.Id), kind),
                                 'box': None})
                continue

            symbol = symbol_for[kind]

            wall_curve = wall.Location.Curve.CreateTransformed(transform)
            frame = WallFrame(wall_curve)

            services = services_through_wall(doc, view, solid, wall_box, frame)
            if not services:
                continue
            walls_hit += 1

            # measure each service where it actually crosses the wall
            by_category = {}
            crossings = {}
            member_extents = {}
            for el in services:
                key = category_id(el)
                if key not in gaps:
                    continue
                corners = crossing_corners(el, solid)
                width = section_width(el) if WIDTH_FROM_SECTION else None
                extents = wall_extents(corners, frame, width)
                if extents is None:
                    unmeasured += 1
                    continue
                crossings[eid_value(el.Id)] = corners
                member_extents[eid_value(el.Id)] = extents
                by_category.setdefault(key, []).append((el, extents))

            # on blockwork the categories share an opening, so they go into
            # one bucket at the wider of the two grouping distances. On fire
            # rated walls each category is clustered on its own.
            if kind == 'blockwork' and BLOCKWORK_SHARES_HOLE:
                shared = []
                for entries in by_category.values():
                    shared.extend(entries)
                buckets = [(shared, max(gaps.values()))] if shared else []
            else:
                buckets = [(entries, gaps[key])
                           for key, entries in by_category.items()]

            for entries, gap in buckets:
                for group in cluster_by_gap(entries, gap):
                    groups_found += 1

                    corners = []
                    spans = []
                    for el in group:
                        corners.extend(crossings.get(eid_value(el.Id), []))
                        member = member_extents.get(eid_value(el.Id))
                        if member is not None:
                            spans.append(member)
                    span = union_extents(spans)
                    box = group_box(corners)

                    if SKIP_EXISTING and box is not None \
                            and any(boxes_overlap(box, other)
                                    for other in prior):
                        skipped_existing += 1
                        continue

                    # the same opening arrived twice -- one wall is enough.
                    # Stacked walls, linings and walls doubled up in the link
                    # all produce it, and Revit calls those identical
                    # instances.
                    if already_placed_here(box, placed_records, duplicate_tol) \
                            or already_placed_here(
                                box, [{'box': b} for b in prior],
                                duplicate_tol):
                        duplicates += 1
                        continue

                    trans = quiet_transaction(
                        doc, 'Place BWIC penetration', swallower)
                    try:
                        instance, notes = place_one(
                            doc, group, wall, transform, clearance_ft,
                            symbol, options, workset, corners, span)
                        if instance is None:
                            trans.RollBack()
                            failures.append({
                                'text': 'wall {} ({}): {}'.format(
                                    eid_value(wall.Id), kind,
                                    '; '.join(notes)),
                                'box': box})
                        else:
                            new_box = world_box(instance) or box
                            # last line of defence: whatever the maths did,
                            # the BWIC has to end up on the wall it was
                            # placed for. If it is not touching, it is wrong
                            # and it does not get committed.
                            if new_box is not None and not boxes_overlap(
                                    new_box, wall_box, -mm_to_ft(1.0)):
                                trans.RollBack()
                                failures.append({
                                    'text': 'wall {} ({}): the BWIC landed '
                                            'off the wall and was not kept'
                                            .format(eid_value(wall.Id),
                                                    kind),
                                    'box': box})
                            else:
                                trans.Commit()
                                placed += 1
                                if new_box is not None:
                                    placed_records.append(
                                        {'id': instance.Id, 'box': new_box})
                    except Exception as err:
                        if trans.HasStarted():
                            trans.RollBack()
                        failures.append({
                            'text': 'wall {} ({}): {}'.format(
                                eid_value(wall.Id), kind, err),
                            'box': box})
                        logger.error(err)

        # --- mark what needs a human: overlaps, and anything that failed --
        clashing, pairs = find_clashes(placed_records,
                                       mm_to_ft(CLASH_TOLERANCE_MM))
        review_ids = [placed_records[i]['id'] for i in clashing
                      if placed_records[i]['id'] is not None]

        failed_boxes = [f['box'] for f in failures if f.get('box') is not None]
        clash_boxes = [placed_records[i]['box'] for i in clashing]

        want_marks = ((clash_boxes and MARK_CLASHES)
                      or (failed_boxes and MARK_FAILURES))

        if want_marks and not view_takes_detail_lines(view):
            note('Nothing could be marked -- this view will not take detail '
                 'lines. Run in a plan or section for the red boxes.')
        elif want_marks:
            stamp = datetime.datetime.now().strftime('%Y-%m-%d %H-%M')
            jobs = []
            if clash_boxes and MARK_CLASHES:
                jobs.append(('clash', clash_boxes, CLASH_LINE_STYLE,
                             (255, 0, 0),
                             '{} {}'.format(CLASH_GROUP_NAME, stamp)))
            if failed_boxes and MARK_FAILURES:
                jobs.append(('failed', failed_boxes, FAILED_LINE_STYLE,
                             (255, 150, 0),
                             '{} {}'.format(FAILED_GROUP_NAME, stamp)))

            for label, boxes, style_name, rgb, name in jobs:
                marks = quiet_transaction(
                    doc, 'Mark BWIC {}'.format(label), swallower)
                try:
                    style = marker_line_style(doc, style_name, rgb)
                    line_ids = mark_boxes(doc, view, boxes,
                                          mm_to_ft(CLASH_MARGIN_MM), style)
                    marks.Commit()
                except Exception as err:
                    if marks.HasStarted():
                        marks.RollBack()
                    line_ids = []
                    note('Could not draw the {} marks: {}'.format(label, err))
                    logger.error(err)

                if not line_ids:
                    continue

                grouping = quiet_transaction(
                    doc, 'Group BWIC {} marks'.format(label), swallower)
                try:
                    made = group_marks(doc, line_ids, name)
                    grouping.Commit()
                except Exception as err:
                    if grouping.HasStarted():
                        grouping.RollBack()
                    made = None
                    note('Could not group the {} marks: {}'.format(label, err))
                    logger.error(err)

                if label == 'clash':
                    group_name = made
                else:
                    failed_group_name = made

        group_holder.Assimilate()
    except Exception as err:
        if group_holder.HasStarted():
            group_holder.RollBack()
        report('Run stopped: {}'.format(err))
        logger.error(err)
        return

    # ---- summary ----------------------------------------------------------
    if out_of_reach:
        note('{} wall{} sat away from anything visible here and {} not '
             'looked at.'.format(out_of_reach, '' if out_of_reach == 1 else 's',
                                 'was' if out_of_reach == 1 else 'were'))
    note('{} wall{} with services passing through, {} group{} found.'.format(
        walls_hit, '' if walls_hit == 1 else 's',
        groups_found, '' if groups_found == 1 else 's'))
    if skipped_existing:
        note('{} group{} already had a BWIC and {} left alone.'.format(
            skipped_existing, '' if skipped_existing == 1 else 's',
            'was' if skipped_existing == 1 else 'were'))
    if duplicates:
        note('{} opening{} came up twice -- the repeat was dropped.'.format(
            duplicates, '' if duplicates == 1 else 's'))
    if unmeasured:
        note('{} service{} could not be measured at the wall and {} left out.'
             .format(unmeasured, '' if unmeasured == 1 else 's',
                     'was' if unmeasured == 1 else 'were'))
    if failures:
        note('{} placement{} failed -- see the pyRevit output for detail.'
             .format(len(failures), '' if len(failures) == 1 else 's'))
        for entry in failures[:20]:
            logger.warning(entry['text'])

    if clashing:
        note('{} of the BWICs placed overlap{} another in 3D -- '
             'marked To Review.'.format(
                 len(clashing), 's' if len(clashing) == 1 else ''))
    if group_name:
        note('Overlap marks grouped as "{}".'.format(group_name))
    if failed_group_name:
        note('Failure marks grouped as "{}".'.format(failed_group_name))

    note('{} BWIC placed.'.format(placed))

    warnings = swallower.summary() if swallower is not None else []
    if warnings:
        note('Revit messages dismissed during the run:')
        for line in warnings[:8]:
            note('  - {}'.format(line))
        if len(warnings) > 8:
            note('  - and {} more, see the pyRevit output.'.format(
                len(warnings) - 8))
        for line in warnings:
            logger.info(line)

    report('\n'.join(log))

    return {'placed': placed,
            'review': len(clashing),
            'clash_pairs': len(pairs),
            'review_ids': review_ids,
            'skipped': skipped_existing,
            'duplicates': duplicates,
            'unmeasured': unmeasured,
            'failed_group_name': failed_group_name,
            'warnings': warnings,
            'failed': len(failures),
            'groups': groups_found,
            'walls': walls_hit,
            'group_name': group_name,
            'log': log}


# ---------------------------------------------------------------------------
# one Settings for the whole tool
# ---------------------------------------------------------------------------
def configure(settings):
    """Take the family, types, sizes and workset from the tool's Settings.

    The Wall tab and this tab place the same family into the same walls, so
    they read the same Settings -- otherwise changing the family name in
    Settings would quietly leave Global Placement on the old one.
    """
    global FAMILY_NAME, TYPE_FIRE, TYPE_BLOCKWORK, P_LENGTH, P_WIDTH, \
        P_HEIGHT, ROUND_UP_MM, WORKSET_NAME, FAMILY_WORKSET, FAMILY_CLEARANCE
    get = settings.get
    if get('wall_family'):
        FAMILY_NAME = get('wall_family')
    if get('wall_type_firerated'):
        TYPE_FIRE = get('wall_type_firerated')
    if get('wall_type_blockwork'):
        TYPE_BLOCKWORK = get('wall_type_blockwork')
    if get('wall_length_param'):
        P_LENGTH = get('wall_length_param')
    if get('wall_width_param'):
        P_WIDTH = get('wall_width_param')
    if get('wall_height_param'):
        P_HEIGHT = get('wall_height_param')
    try:
        if get('round_up'):
            ROUND_UP_MM = float(get('round_up'))
    except ValueError:
        pass
    WORKSET_NAME = get('workset') or ''
    FAMILY_WORKSET = get('family_workset') or ''
    FAMILY_CLEARANCE = get('family_clearance') or ''
