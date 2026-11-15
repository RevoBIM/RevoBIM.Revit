# -*- coding: utf-8 -*-
"""Place BWIC - the model side.

Everything that reads or writes the Revit model lives here: geometry, level
and workset handling, the wall rules, the slab rules and the settings file.
There is no WPF in this module, so the rules can be read and reasoned about
without the window in the way.
"""

__version__ = '2.19.0'

import io
import math
import os
import os.path as op
import re

from pyrevit import script, HOST_APP

import bwic_families as families

try:
    from pyrevit import DB, UI
except ImportError:
    from Autodesk.Revit import DB, UI

from System.Collections.Generic import List
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter
from Autodesk.Revit.Exceptions import OperationCanceledException
from Autodesk.Revit.DB.Structure import StructuralType


# ---------------------------------------------------------------------------
# SETTINGS
# ---------------------------------------------------------------------------

FAMILY_NAME = 'BGL_BWIC_Penetration_Horizontal_Rectangular-Dynamic'

P_LENGTH = 'BGL_Length'          # front/back -> through the wall
P_WIDTH = 'BGL_Width'            # left/right -> along the wall
P_HEIGHT = 'BGL_Height'          # vertical
# what the three go back to when a family's settings leave one blank. Without
# these a blank kept whatever the last run used -- an X+ / X- pair, say, on a
# family since set back to Standard.
DEFAULT_P_LENGTH, DEFAULT_P_WIDTH, DEFAULT_P_HEIGHT = P_LENGTH, P_WIDTH, P_HEIGHT
# a round wall family: one size parameter, holding a diameter or a radius.
# Set only for the length of a circular run, by run_placement_loop.
WALL_SHAPE = families.RECT
P_DIAMETER = ''
WALL_RADIUS = False
# the wall family type used when no wall rule (blockwork, fire) applies
WALL_TYPE = ''
# how a circular run sizes its hole: gap and round-up in mm, and whether
# insulation counts. None outside a circular run.
ROUND_WALL = None

DEFAULT_CLEARANCE_MM = 50.0      # added to EACH side

# the BWIC is centred on the full vertical extent of the selection, so it
# encompasses everything from the bottom of the lowest service to the top of
# the highest one
# 'extents_centre'  -> origin at the middle of that extent
# 'highest_service' -> origin on the centre line of the highest service
ELEVATION_MODE = 'extents_centre'

# Which family type to use for which wall, tested in order -- the FIRST match
# wins, so a wall that is both blockwork and fire rated comes out fire rated.
# Reorder the list if your standard says otherwise.
#   keywords        -> matched against the linked wall's Type Name, as whole
#                      words, case insensitive
#   fire_rating     -> also matches when the wall type carries a fire rating
#   symbol          -> family type to place; falls back to the default type
#                      with a note in the status box if it is not loaded
WALL_RULES = [
    {'label': 'fire rated wall',
     'keywords': ['FR', 'FIRE'],
     'fire_rating': True,
     'symbol': 'BWIC - Fire Rated Wall'},
    {'label': 'blockwork wall',
     'keywords': ['BLK'],
     'fire_rating': False,
     'symbol': 'BWIC - Blockwork'},
]

# Level name -> code. The numbered rule is tried first, so "Level 03" gives
# "03"; then these keyword rules; then any number in the name; then the level's
# position counting up from the lowest.
LEVEL_CODE_RULES = [
    ('ROOF', 'RF'),
    ('RF', 'RF'),
]

# preferred parameter for the level code, and the fallback keyword used to
# find one when it does not exist on the family
LEVEL_PARAM_NAME = 'BHE_Level'
LEVEL_PARAM_KEYWORD = 'Level'

# where the family origin sits in its own box: 'centre' | 'bottom' | 'top'
ORIGIN_VERTICAL = 'centre'

DUPLICATE_TYPE_IF_TYPE_PARAMS = True

# Categories offered when picking services. Fittings and accessories are in
# here as well as the straight runs, so a bend or a coupler sitting in the
# wall line can be included in the opening. Names that do not exist on a
# given Revit release are skipped.
SERVICE_CATEGORY_NAMES = [
    'OST_PipeCurves', 'OST_FlexPipeCurves', 'OST_PipeFitting',
    'OST_PipeAccessory', 'OST_PipeInsulations',
    'OST_DuctCurves', 'OST_FlexDuctCurves', 'OST_DuctFitting',
    'OST_DuctAccessory', 'OST_DuctInsulations', 'OST_DuctTerminal',
    'OST_Conduit', 'OST_ConduitFitting', 'OST_ConduitRun',
    'OST_CableTray', 'OST_CableTrayFitting', 'OST_CableTrayRun',
    'OST_Sprinklers', 'OST_MechanicalEquipment', 'OST_ElectricalEquipment',
    'OST_ElectricalFixtures', 'OST_PlumbingFixtures', 'OST_GenericModel',
]

# BGL_Width and BGL_Height are rounded UP to a multiple of this, in mm
ROUND_UP_MM = 5.0

# the BWIC is placed on the first workset whose name contains this word
WORKSET_KEYWORD = 'BWIC'

QTY_DELIMITER = '_'              # between entries in the Comments string

# keep the run silent: no pyRevit output console, no Revit warning dialogs.
# Everything still lands in the status box at the bottom of the window.
SUPPRESS_MESSAGES = True

SETTINGS_PATH = op.join(
    op.expandvars(r'%APPDATA%'), 'RevoBIM PY', 'place_bwic_settings.txt')
# how each family sizes itself, by family name -- see bwic_families.py
PROFILES_PATH = op.join(
    op.expandvars(r'%APPDATA%'), 'RevoBIM PY', 'place_bwic_families.json')


def load_profiles():
    return families.load(PROFILES_PATH)


def family_settings(settings, slot):
    """Settings with the slot's chosen family profile written over them."""
    return families.overlay(settings, slot, load_profiles())

logger = script.get_logger()

# ---------------------------------------------------------------------------
# debug log -- off unless the tick box is on. Everything the run decides is
# written here so a session can be sent on rather than described.
# ---------------------------------------------------------------------------
DEBUG_PATH = op.join(op.expandvars(r'%APPDATA%'), 'RevoBIM PY',
                     'place_bwic_debug.log')
DEBUG = False


def set_debug(on):
    global DEBUG
    DEBUG = bool(on)


def debug(message):
    """Append a timestamped line to the debug log, if debugging is on."""
    if not DEBUG:
        return
    try:
        import datetime
        folder = op.dirname(DEBUG_PATH)
        if not op.isdir(folder):
            os.makedirs(folder)
        stamp = datetime.datetime.now().strftime('%H:%M:%S')
        handle = io.open(DEBUG_PATH, 'a', encoding='utf-8')
        try:
            handle.write(u'{} {}\n'.format(stamp, message))
        finally:
            handle.close()
    except Exception:
        pass


def start_debug(doc, heading, settings=None, options=None):
    """Open a run in the log with everything needed to read it cold."""
    if not DEBUG:
        return
    try:
        import datetime
        folder = op.dirname(DEBUG_PATH)
        if not op.isdir(folder):
            os.makedirs(folder)
        handle = io.open(DEBUG_PATH, 'a', encoding='utf-8')
        try:
            handle.write(u'\n{}\n'.format('=' * 70))
            handle.write(u'{}  {}\n'.format(
                datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), heading))
            handle.write(u'tool version {}\n'.format(__version__))
            # a stale copy of the tool left in another folder is easy to run
            # by accident and impossible to spot from the log otherwise
            try:
                handle.write(u'running from {}\n'.format(
                    op.dirname(op.abspath(__file__))))
            except Exception:
                pass
            try:
                app = doc.Application
                handle.write(u'Revit {} build {}\n'.format(
                    app.VersionNumber, app.VersionBuild))
            except Exception:
                pass
            try:
                handle.write(u'document {} (workshared: {})\n'.format(
                    doc.Title, doc.IsWorkshared))
            except Exception:
                pass
            if settings:
                handle.write(u'settings:\n')
                for key in sorted(settings.keys()):
                    handle.write(u'   {} = {}\n'.format(key, settings[key]))
            if options:
                handle.write(u'options:\n')
                for key in sorted(options.keys()):
                    handle.write(u'   {} = {}\n'.format(key, options[key]))
            handle.write(u'{}\n'.format('-' * 70))
        finally:
            handle.close()
    except Exception:
        pass


def clear_debug():
    try:
        if op.isfile(DEBUG_PATH):
            os.remove(DEBUG_PATH)
    except Exception:
        pass


def read_settings():
    """Plain key=value file -- no JSON, which varies with the engine.

    A missing or damaged file falls back to the defaults key by key, and keys
    from an older version are ignored rather than breaking the load.
    """
    values = dict(SLAB_DEFAULTS)
    try:
        if not op.isfile(SETTINGS_PATH):
            return values
        handle = io.open(SETTINGS_PATH, 'r', encoding='utf-8')
        try:
            for line in handle:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, _, value = line.partition('=')
                values[key.strip()] = value.strip()
        finally:
            handle.close()
    except Exception:
        logger.debug('could not read the settings file')
    return values


def apply_settings(values):
    """Push saved settings onto the module level names the rules read.

    Kept in one place so the settings window never has to know which module
    global belongs to which field.
    """
    global FAMILY_NAME, P_LENGTH, P_WIDTH, P_HEIGHT
    global DEFAULT_CLEARANCE_MM, ROUND_UP_MM, WALL_RULES
    global WALL_TYPE

    # the wall family's own profile decides its parameter names
    try:
        values = family_settings(values, 'wall')
    except Exception:
        pass
    WALL_TYPE = values.get('wall_type') or ''

    if values.get('wall_family'):
        FAMILY_NAME = values['wall_family']
    # every time, from the settings or the defaults -- never left as they
    # were, which kept the last run's names
    P_LENGTH = values.get('wall_length_param') or DEFAULT_P_LENGTH
    P_WIDTH = values.get('wall_width_param') or DEFAULT_P_WIDTH
    P_HEIGHT = values.get('wall_height_param') or DEFAULT_P_HEIGHT

    for key, name in (('clearance', 'DEFAULT_CLEARANCE_MM'),
                      ('round_up', 'ROUND_UP_MM')):
        raw = values.get(key)
        if not raw:
            continue
        try:
            number = float(raw)
        except ValueError:
            continue
        if number <= 0 and name == 'ROUND_UP_MM':
            continue
        globals()[name] = number

    fire = values.get('wall_type_firerated')
    block = values.get('wall_type_blockwork')
    if fire or block:
        rules = []
        for rule in WALL_RULES:
            rule = dict(rule)
            if rule['label'].startswith('fire') and fire:
                rule['symbol'] = fire
            elif rule['label'].startswith('block') and block:
                rule['symbol'] = block
            rules.append(rule)
        WALL_RULES = rules


def write_settings(values):
    try:
        folder = op.dirname(SETTINGS_PATH)
        if not op.isdir(folder):
            os.makedirs(folder)
        handle = io.open(SETTINGS_PATH, 'w', encoding='utf-8')
        try:
            for key in sorted(values.keys()):
                handle.write(u'{}={}\n'.format(key, values[key]))
        finally:
            handle.close()
    except Exception:
        logger.debug('could not write the settings file')

if SUPPRESS_MESSAGES:
    try:
        logger.set_quiet_mode()
    except Exception:
        pass


def close_output_window():
    """Shut the pyRevit console if anything managed to open it."""
    if not SUPPRESS_MESSAGES:
        return
    try:
        out = script.get_output()
        if out is None or out.window is None:
            return
        if getattr(out.window, 'IsVisible', False):
            out.close()
    except Exception:
        pass


class WarningSwallower(DB.IFailuresPreprocessor):
    """Clears Revit's own warning dialogs during placement."""

    def PreprocessFailures(self, accessor):
        try:
            for failure in accessor.GetFailureMessages():
                if failure.GetSeverity() == DB.FailureSeverity.Warning:
                    accessor.DeleteWarning(failure)
        except Exception:
            pass
        return DB.FailureProcessingResult.Continue


def quieten(transaction):
    """Attach the warning swallower to a transaction."""
    if not SUPPRESS_MESSAGES:
        return
    try:
        options = transaction.GetFailureHandlingOptions()
        options.SetFailuresPreprocessor(WarningSwallower())
        options.SetClearAfterRollback(True)
        transaction.SetFailureHandlingOptions(options)
    except Exception:
        logger.debug('could not attach the failure preprocessor')


# ---------------------------------------------------------------------------
# units
# ---------------------------------------------------------------------------
def eid_value(element_id):
    """ElementId as a number.

    .IntegerValue was deprecated in 2024 and removed in 2026, so .Value is
    tried first and the old name kept as a fallback for 2024/2025.
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
# selection filters
# ---------------------------------------------------------------------------
class WallPickFilter(ISelectionFilter):
    """Walls only, in a link or in the host model."""

    def __init__(self, host_doc):
        self.host_doc = host_doc

    def AllowElement(self, element):
        return isinstance(element, (DB.Wall, DB.RevitLinkInstance))

    def AllowReference(self, reference, position):
        try:
            element = self.host_doc.GetElement(reference.ElementId)
            if isinstance(element, DB.RevitLinkInstance):
                link_doc = element.GetLinkDocument()
                if link_doc is None:
                    return False
                return isinstance(
                    link_doc.GetElement(reference.LinkedElementId), DB.Wall)
            return isinstance(element, DB.Wall)
        except Exception:
            return False


def service_category_ids():
    """The BuiltInCategory ids a service can belong to, this release."""
    ids = []
    for name in SERVICE_CATEGORY_NAMES:
        try:
            ids.append(int(getattr(DB.BuiltInCategory, name)))
        except (AttributeError, ValueError):
            continue
    return set(ids)


SERVICE_CATEGORY_IDS = None


def is_service(element):
    """True for pipes, ducts, trays, conduit and their fittings."""
    global SERVICE_CATEGORY_IDS
    if SERVICE_CATEGORY_IDS is None:
        SERVICE_CATEGORY_IDS = service_category_ids()
    try:
        category = element.Category
        if category is None:
            return False
        if eid_value(category.Id) not in SERVICE_CATEGORY_IDS:
            return False
        return element.get_BoundingBox(None) is not None
    except Exception:
        return False


def is_bwic(element, names=None):
    """True for an instance of a BWIC family.

    The wall tool looks for its own family; the slab tool passes the names of
    whichever rectangular and circular families it is set to use, so a slab
    opening is pickable for a resize even though it is a different family.
    """
    try:
        if not isinstance(element, DB.FamilyInstance) \
                or element.Symbol is None:
            return False
        family = element.Symbol.Family.Name
        if names:
            return family in [n for n in names if n]
        return family == FAMILY_NAME
    except Exception:
        return False


class BWICPickFilter(ISelectionFilter):
    """Existing BWIC instances only."""

    def __init__(self, names=None):
        self.names = names

    def AllowElement(self, element):
        return is_bwic(element, self.names)

    def AllowReference(self, reference, position):
        return False


class ServicePickFilter(ISelectionFilter):
    """Services -- runs, fittings and accessories.

    With include_linked set, services inside loaded links are pickable in the
    SAME selection as host ones, so there is one Finish rather than two. Revit
    hands back a reference whose ElementId is the link instance and whose
    LinkedElementId names the element inside it, which resolve_picked() below
    untangles.
    """

    def __init__(self, host_doc=None, include_linked=False):
        self.host_doc = host_doc
        self.include_linked = include_linked

    def AllowElement(self, element):
        if is_service(element):
            return True
        return bool(self.include_linked
                    and isinstance(element, DB.RevitLinkInstance))

    def AllowReference(self, reference, position):
        if not self.include_linked or self.host_doc is None:
            return False
        try:
            element = self.host_doc.GetElement(reference.ElementId)
            if not isinstance(element, DB.RevitLinkInstance):
                return True
            link_doc = element.GetLinkDocument()
            if link_doc is None:
                return False
            return is_service(link_doc.GetElement(reference.LinkedElementId))
        except Exception:
            return False


def resolve_picked(doc, reference):
    """Turn a picked reference into a Service, host or linked."""
    element = doc.GetElement(reference.ElementId)
    if isinstance(element, DB.RevitLinkInstance):
        link_doc = element.GetLinkDocument()
        if link_doc is None:
            return None
        try:
            linked = link_doc.GetElement(reference.LinkedElementId)
        except Exception:
            return None
        if linked is None or not is_service(linked):
            return None
        return Service(linked, element.GetTotalTransform(), linked=True)
    if element is None or not is_service(element):
        return None
    return Service(element)


# ---------------------------------------------------------------------------
# services -- an element plus the transform that puts it in host coordinates
# ---------------------------------------------------------------------------
class Service(object):
    def __init__(self, element, transform=None, linked=False):
        self.element = element
        self.transform = transform or DB.Transform.Identity
        self.linked = linked

    @property
    def doc(self):
        return self.element.Document


# ---------------------------------------------------------------------------
# geometry helpers
# ---------------------------------------------------------------------------
def param_double(element, names, bips):
    """First non-zero value from a list of parameter names or built-ins."""
    for bip_name in bips:
        try:
            bip = getattr(DB.BuiltInParameter, bip_name)
        except AttributeError:
            continue
        try:
            param = element.get_Parameter(bip)
            if param is not None and param.StorageType == DB.StorageType.Double:
                value = param.AsDouble()
                if value > 1e-9:
                    return value
        except Exception:
            continue
    for name in names:
        try:
            param = element.LookupParameter(name)
            if param is not None and param.StorageType == DB.StorageType.Double:
                value = param.AsDouble()
                if value > 1e-9:
                    return value
        except Exception:
            continue
    return 0.0


def cross_section(element):
    """Outer half width and half height of a service, insulation included.

    Returns (half_width, half_height) or None when the element is not a
    straight run with a readable cross section -- fittings, accessories and
    equipment fall back to their bounding box.
    """
    diameter = param_double(
        element, ['Diameter', 'Overall Size', 'Outside Diameter'],
        ['RBS_PIPE_OUTER_DIAMETER', 'RBS_CURVE_DIAMETER_PARAM',
         'RBS_PIPE_DIAMETER_PARAM', 'RBS_CONDUIT_OUTER_DIAM_PARAM',
         'RBS_CONDUIT_DIAMETER_PARAM'])

    width = param_double(element, ['Width'], ['RBS_CURVE_WIDTH_PARAM',
                                              'RBS_CABLETRAY_WIDTH_PARAM'])
    height = param_double(element, ['Height'], ['RBS_CURVE_HEIGHT_PARAM',
                                                'RBS_CABLETRAY_HEIGHT_PARAM'])

    if width > 1e-9 and height > 1e-9:
        half_w, half_h = width / 2.0, height / 2.0
    elif diameter > 1e-9:
        half_w = half_h = diameter / 2.0
    else:
        return None

    insulation = param_double(
        element, ['Insulation Thickness'],
        ['RBS_REFERENCE_INSULATION_THICKNESS',
         'RBS_INSULATION_THICKNESS_FOR_DUCT',
         'RBS_PIPE_INSULATION_THICKNESS'])
    if insulation > 1e-9:
        half_w += insulation
        half_h += insulation

    return half_w, half_h


def run_frame(direction):
    """Local axes for a run: along, horizontal perpendicular, and 'up'."""
    along = direction.Normalize()
    horizontal = DB.XYZ(along.X, along.Y, 0)
    if horizontal.GetLength() < 1e-6:
        # a vertical run -- any horizontal pair will do
        side = DB.XYZ.BasisX
        up = DB.XYZ.BasisY
    else:
        side = along.CrossProduct(DB.XYZ.BasisZ)
        if side.GetLength() < 1e-9:
            side = DB.XYZ.BasisX
        side = side.Normalize()
        up = side.CrossProduct(along).Normalize()
    return along, side, up


def service_points(service, wall_plane=None):
    """Points describing the outer envelope of a service, in host coordinates.

    Straight runs are measured from their real edges -- the duct or tray face,
    the outside of the pipe, insulation included -- so a run at an angle is not
    inflated the way its bounding box would be. Everything else falls back to
    the bounding box.

    wall_plane, (point on the centre line, normal, half thickness) in host
    coordinates, measures a straight run only where it is inside the wall --
    otherwise a drainage pipe's fall over its whole length is added to the
    height, and a pipe crossing at an angle to the width.
    """
    element = service.element
    transform = service.transform

    try:
        location = element.Location
        section = cross_section(element)
        if isinstance(location, DB.LocationCurve) and section is not None:
            half_w, half_h = section
            curve = location.Curve
            start, end = curve.GetEndPoint(0), curve.GetEndPoint(1)
            direction = end - start
            if direction.GetLength() > 1e-9:
                _, side, up = run_frame(direction)
                bases = (start, end)
                if wall_plane is not None:
                    origin, normal, half = wall_plane
                    span = families.wall_span(
                        (transform.OfPoint(start) - origin).DotProduct(normal),
                        (transform.OfPoint(end) - origin).DotProduct(normal),
                        half)
                    if span is not None:
                        bases = tuple(start + direction * t for t in span)
                points = []
                for base in bases:
                    for sw in (-half_w, half_w):
                        for sh in (-half_h, half_h):
                            points.append(base + side * sw + up * sh)
                return [transform.OfPoint(p) for p in points]
    except Exception:
        logger.debug('cross section unavailable, falling back to geometry')

    # fittings, accessories and equipment: measure the real solids
    points = solid_points(element, transform)
    if points:
        return points

    return bbox_corners(element, transform)


def walk_geometry(geometry, into_instances=True):
    """Yield every solid in a geometry element, stepping into instances."""
    if geometry is None:
        return
    for item in geometry:
        try:
            if isinstance(item, DB.Solid):
                if item.Volume > 1e-9:
                    yield item
            elif into_instances and isinstance(item, DB.GeometryInstance):
                for solid in walk_geometry(item.GetInstanceGeometry(), False):
                    yield solid
            elif isinstance(item, DB.GeometryElement):
                for solid in walk_geometry(item, into_instances):
                    yield solid
        except Exception:
            continue


def solid_points(element, transform=None):
    """Corner points of an element's real solids, in host coordinates.

    Used for fittings and accessories, which have no single cross section. A
    conduit bend or a duct elbow sits at an angle by definition, so its
    bounding box overstates the extent it actually needs -- the edge points
    give the true envelope.
    """
    points = []
    try:
        options = DB.Options()
        options.DetailLevel = DB.ViewDetailLevel.Fine
        options.IncludeNonVisibleObjects = False
        geometry = element.get_Geometry(options)
        for solid in walk_geometry(geometry):
            for edge in solid.Edges:
                try:
                    points.extend(edge.Tessellate())
                except Exception:
                    continue
    except Exception:
        logger.debug('solid geometry unavailable')
        return []

    if not points:
        return []
    if transform is not None:
        points = [transform.OfPoint(p) for p in points]
    return points


def bbox_corners(element, transform=None):
    bb = element.get_BoundingBox(None)
    if bb is None:
        return []
    local = bb.Transform
    mn, mx = bb.Min, bb.Max
    points = []
    for x in (mn.X, mx.X):
        for y in (mn.Y, mx.Y):
            for z in (mn.Z, mx.Z):
                points.append(local.OfPoint(DB.XYZ(x, y, z)))
    if transform is not None:
        points = [transform.OfPoint(p) for p in points]
    return points


def element_centre_z(service):
    element, transform = service.element, service.transform
    try:
        location = element.Location
        if isinstance(location, DB.LocationCurve):
            curve = location.Curve
            mid = (curve.GetEndPoint(0) + curve.GetEndPoint(1)) / 2.0
            return transform.OfPoint(mid).Z
        if isinstance(location, DB.LocationPoint):
            return transform.OfPoint(location.Point).Z
    except Exception:
        pass
    points = solid_points(element, transform) or bbox_corners(element, transform)
    if not points:
        return 0.0
    return (min(p.Z for p in points) + max(p.Z for p in points)) / 2.0


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


def wall_frame_at(wall_curve, point):
    """(point on the wall centre line, along-wall vector, wall normal)."""
    result = wall_curve.Project(point)
    if result is None:
        base = wall_curve.GetEndPoint(0)
        direction = wall_curve.GetEndPoint(1) - base
    else:
        base = result.XYZPoint
        direction = wall_curve.ComputeDerivatives(result.Parameter, False).BasisX
    direction = DB.XYZ(direction.X, direction.Y, 0).Normalize()
    normal = direction.CrossProduct(DB.XYZ.BasisZ).Normalize()
    return base, direction, normal


# ---------------------------------------------------------------------------
# family helpers
# ---------------------------------------------------------------------------
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
    # the type chosen on the Wall tab, when there is one
    for sym in symbols:
        if WALL_TYPE and DB.Element.Name.GetValue(sym) == WALL_TYPE:
            return sym
    return symbols[0]


def set_length_param(holder, name, value_ft):
    """Write a size. A split pair (X Minus + X Plus) takes half on each side.

    Every part is checked before any is written, so a pair is never left
    half sized.
    """
    parts = families.split_parts(name)
    params = []
    for part, share in parts:
        param = holder.LookupParameter(part)
        if param is None:
            return False, '{} not found'.format(part)
        if param.IsReadOnly:
            return False, '{} is read only'.format(part)
        if param.StorageType != DB.StorageType.Double:
            return False, '{} is not a length parameter'.format(part)
        params.append((param, share))
    for param, share in params:
        param.Set(value_ft * share)
    if len(params) > 1:
        debug('split {} -> {:.1f} mm each side ({:.1f} overall)'.format(
            families.show_name(name), ft_to_mm(value_ft / 2.0),
            ft_to_mm(value_ft)))
    return True, None


def has_length_param(holder, name):
    """True when the holder carries the parameter -- or, for a split pair,
    both sides of it."""
    if not name or holder is None:
        return False
    try:
        return all(holder.LookupParameter(part) is not None
                   for part, _ in families.split_parts(name))
    except Exception:
        return False


def wall_size_writes(length, width, height):
    """(parameter, value) pairs a wall BWIC is sized with, by its shape.

    A rectangular family takes the three sizes. A round one takes the larger
    of width and height as its diameter -- or half of it, when its parameter
    is a radius -- and the thickness through the wall as before.
    """
    if WALL_SHAPE == families.CIRC and P_DIAMETER:
        writes = [(P_DIAMETER,
                   families.round_value(max(width, height), WALL_RADIUS))]
        if P_LENGTH:
            writes.insert(0, (P_LENGTH, length))
        return writes
    return [(P_LENGTH, length), (P_WIDTH, width), (P_HEIGHT, height)]


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
# wall classification
# ---------------------------------------------------------------------------
def wall_type_name(wall):
    """The linked wall's Type Name."""
    try:
        wtype = wall.Document.GetElement(wall.GetTypeId())
        if wtype is not None:
            return DB.Element.Name.GetValue(wtype) or ''
    except Exception:
        pass
    try:
        param = wall.get_Parameter(DB.BuiltInParameter.ELEM_TYPE_PARAM)
        if param is not None:
            return param.AsValueString() or ''
    except Exception:
        pass
    return ''


def wall_is_fire_rated(wall):
    """True when the wall type carries a meaningful Fire Rating value."""
    try:
        wtype = wall.Document.GetElement(wall.GetTypeId())
        param = wtype.get_Parameter(DB.BuiltInParameter.FIRE_RATING)
        if param is None:
            return False
        value = (param.AsString() or '').strip()
        return bool(value) and value.upper() not in ('0', 'NONE', 'N/A', '-')
    except Exception:
        return False


def has_keyword(text, keyword):
    """Whole word match, so BLK does not fire on BLOCKING and FR not on FRAME."""
    pattern = r'(?<![A-Z0-9])' + re.escape(keyword.upper()) + r'(?![A-Z0-9])'
    return re.search(pattern, (text or '').upper()) is not None


def classify_wall(wall):
    """Return the first matching rule, or None for an ordinary wall."""
    type_name = wall_type_name(wall)
    for rule in WALL_RULES:
        if any(has_keyword(type_name, kw) for kw in rule.get('keywords', [])):
            return rule
        if rule.get('fire_rating') and wall_is_fire_rated(wall):
            return rule
    return None


def choose_symbol(doc, wall, default_symbol, cache):
    """Pick the family type that suits this wall.

    Returns (symbol, description). Falls back to the default type, saying so,
    when the rule's type is not loaded in the project.
    """
    rule = classify_wall(wall)
    type_name = wall_type_name(wall)
    if rule is None:
        return default_symbol, 'wall "{}"'.format(type_name)

    wanted = rule['symbol']
    if wanted not in cache:
        cache[wanted] = find_symbol_by_name(doc, default_symbol.Family, wanted)
    symbol = cache[wanted]

    if symbol is None:
        return default_symbol, '{} "{}" - type "{}" not loaded, used the ' \
                               'default type'.format(rule['label'], type_name,
                                                     wanted)
    return symbol, '{} "{}" - type "{}"'.format(rule['label'], type_name, wanted)


# ---------------------------------------------------------------------------
# levels
# ---------------------------------------------------------------------------
def sorted_levels(doc):
    return sorted(DB.FilteredElementCollector(doc).OfClass(DB.Level).ToElements(),
                  key=lambda l: level_z(l))


def view_level(view):
    """The level a plan view is associated with, or None for anything else.

    Floor, ceiling, structural and area plans all carry a generating level;
    3D views, sections and elevations do not.
    """
    if view is None:
        return None
    try:
        if not isinstance(view, DB.ViewPlan):
            return None
        level = view.GenLevel
        return level if isinstance(level, DB.Level) else None
    except Exception:
        return None


def level_below(levels, elevation):
    """Nearest level at or below the given elevation.

    Where nothing sits below -- which happens when the host and the link do
    not share a datum -- the NEAREST level is returned instead of the lowest
    one. Falling back to the lowest silently is how an opening ends up tens of
    metres from the floor it belongs to.
    """
    if not levels:
        return None
    below = [lvl for lvl in levels if level_z(lvl) <= elevation + 1e-6]
    if below:
        return below[-1]
    return min(levels, key=lambda lvl: abs(level_z(lvl) - elevation))


# Which shape suits which service. Pipes and conduit are round; trays and
# ducts are set out as rectangles even where the duct itself is round, because
# that is how the opening is formed on site.
ROUND_CATEGORY_NAMES = [
    'OST_PipeCurves', 'OST_FlexPipeCurves', 'OST_PipeFitting',
    'OST_PipeAccessory', 'OST_PipeInsulations',
    'OST_Conduit', 'OST_ConduitFitting', 'OST_ConduitRun',
    'OST_Sprinklers',
]
RECT_CATEGORY_NAMES = [
    'OST_DuctCurves', 'OST_FlexDuctCurves', 'OST_DuctFitting',
    'OST_DuctAccessory', 'OST_DuctInsulations', 'OST_DuctTerminal',
    'OST_CableTray', 'OST_CableTrayFitting', 'OST_CableTrayRun',
]

_SHAPE_IDS = None


def shape_category_ids():
    global _SHAPE_IDS
    if _SHAPE_IDS is None:
        table = {}
        for shape, names in (('round', ROUND_CATEGORY_NAMES),
                             ('rect', RECT_CATEGORY_NAMES)):
            for name in names:
                try:
                    table[int(getattr(DB.BuiltInCategory, name))] = shape
                except (AttributeError, ValueError):
                    continue
        _SHAPE_IDS = table
    return _SHAPE_IDS


def service_shape(service):
    """'round' for a pipe, 'rect' for a tray or duct, 'round' by default."""
    try:
        category = service.element.Category
        if category is not None:
            return shape_category_ids().get(eid_value(category.Id), 'round')
    except Exception:
        pass
    return 'round'


CIRCULAR_WORD = 'circular'
RECTANGULAR_WORDS = ('rectangular', 'rectangle')


def family_shape(family_name):
    """'circular', 'rectangular', or None when the name does not say.

    The family name is the strongest signal available and it is nearly always
    explicit, so it decides the method on its own. Only a name carrying
    neither word leaves the choice to the tick box.
    """
    name = (family_name or '').lower()
    if CIRCULAR_WORD in name:
        return 'circular'
    for word in RECTANGULAR_WORDS:
        if word in name:
            return 'rectangular'
    return None


def wants_circular(family_name, forced=False):
    """True when the circular rule applies to this family."""
    shape = family_shape(family_name)
    if shape is not None:
        return shape == 'circular'
    return bool(forced)


# Outside diameter, tried hardest first. A pipe carries several diameters and
# they are not interchangeable: Diameter is the NOMINAL size, which on steel
# and cast iron is smaller than the pipe actually is. A hole set out from the
# nominal size is undersized on exactly the services where it matters.
OD_SOURCES = [
    ('RBS_PIPE_OUTER_DIAMETER', 'Outside Diameter', True),
    (None, 'Outside Diameter', True),
    (None, 'Outer Diameter', True),
    ('RBS_CONDUIT_OUTER_DIAM_PARAM', 'Outside Diameter', True),
    ('RBS_CURVE_DIAMETER_PARAM', 'Diameter', False),
    ('RBS_PIPE_DIAMETER_PARAM', 'Diameter', False),
    ('RBS_CONDUIT_DIAMETER_PARAM', 'Diameter', False),
    (None, 'Overall Size', False),
]


def outside_diameter(element):
    """(diameter, where it came from, is it a true outside diameter).

    Returns (None, reason, False) when the element carries no diameter at all.
    """
    for bip_name, param_name, is_outer in OD_SOURCES:
        value = 0.0
        if bip_name:
            try:
                bip = getattr(DB.BuiltInParameter, bip_name)
                param = element.get_Parameter(bip)
                if param is not None \
                        and param.StorageType == DB.StorageType.Double:
                    value = param.AsDouble()
            except (AttributeError, Exception):
                value = 0.0
        else:
            try:
                param = element.LookupParameter(param_name)
                if param is not None \
                        and param.StorageType == DB.StorageType.Double:
                    value = param.AsDouble()
            except Exception:
                value = 0.0
        if value > 1e-9:
            return value, (bip_name or param_name), is_outer
    return None, 'no diameter parameter', False


def insulation_thickness(element):
    return param_double(
        element, ['Insulation Thickness'],
        ['RBS_REFERENCE_INSULATION_THICKNESS',
         'RBS_INSULATION_THICKNESS_FOR_DUCT',
         'RBS_PIPE_INSULATION_THICKNESS'])


def service_diameter(service):
    """Outer diameter of a round service, insulation included.

    Returns None for anything that is not round, so a rectangular duct in a
    circular selection is reported rather than given a nonsense diameter.
    """
    element = service.element
    section = cross_section(element)
    if section is None:
        return None
    half_w, half_h = section
    # cross_section returns equal halves for a round service
    if abs(half_w - half_h) > mm_to_ft(0.5):
        return None
    return half_w * 2.0


def circular_size(service, gap_ft, round_mm, include_insulation=True):
    """(hole diameter, note) for one service.

    The hole is set out from the service's OUTSIDE diameter -- the real
    outside of the pipe, not its nominal size -- with the gap added on every
    side, then rounded up.
    """
    element = service.element
    diameter, source, is_outer = outside_diameter(element)

    if diameter is None:
        # no diameter at all: a fitting, or something rectangular. The widest
        # plan dimension is the honest answer, and it is flagged as such.
        points = service_points(service)
        if not points:
            return None, 'no geometry to measure'
        span = max(max(p.X for p in points) - min(p.X for p in points),
                   max(p.Y for p in points) - min(p.Y for p in points))
        hole = round_up_ft(span + 2 * gap_ft, round_mm)
        debug('   {}: no diameter, widest plan dimension {:.1f} mm '
              '-> hole {:.0f} mm'.format(describe_element(element),
                                         ft_to_mm(span), ft_to_mm(hole)))
        return hole, 'no diameter parameter, sized on its widest plan dimension'

    note = None
    if not is_outer:
        note = ('"{}" is the nominal size, not the outside diameter - the '
                'hole may be tight'.format(source))

    outer = diameter
    insulation = insulation_thickness(element) if include_insulation else 0.0
    if insulation > 1e-9:
        outer += 2 * insulation

    hole = round_up_ft(outer + 2 * gap_ft, round_mm)

    debug('   {}: {} = {:.1f} mm{} + gap {:.0f} x2 -> hole {:.0f} mm'.format(
        describe_element(element), source, ft_to_mm(diameter),
        ' + insulation {:.0f} x2'.format(ft_to_mm(insulation))
        if insulation > 1e-9 else '',
        ft_to_mm(gap_ft), ft_to_mm(hole)))

    return hole, note


def plan_bounds(service):
    """(xmin, xmax, ymin, ymax) of a service in plan, host coordinates."""
    points = service_points(service)
    if not points:
        return None
    return (min(p.X for p in points), max(p.X for p in points),
            min(p.Y for p in points), max(p.Y for p in points))


def convex_hull(points):
    """Andrew's monotone chain, on (x, y) tuples."""
    points = sorted(set(points))
    if len(points) < 3:
        return points

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    def half(sequence):
        out = []
        for point in sequence:
            while len(out) >= 2 and cross(out[-2], out[-1], point) <= 0:
                out.pop()
            out.append(point)
        return out

    return half(points)[:-1] + half(points[::-1])[:-1]


def min_area_rect(points):
    """The tightest rectangle around some plan points, at any angle.

    Returns (angle, width across, depth along, centre x, centre y).

    An axis aligned box around a service running at an angle is far larger
    than the service: a 600 x 100 tray at 30 degrees needs a 570 x 387 box,
    against 600 x 100 turned to suit. The smallest such rectangle sits on one
    of the hull's edges, so only those angles are tried.
    """
    if not points:
        return 0.0, 0.0, 0.0, 0.0, 0.0

    hull = convex_hull(points)
    if len(hull) < 3:
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        return (0.0, max(xs) - min(xs), max(ys) - min(ys),
                (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0)

    best = None
    for index in range(len(hull)):
        x0, y0 = hull[index]
        x1, y1 = hull[(index + 1) % len(hull)]
        if abs(x1 - x0) < 1e-12 and abs(y1 - y0) < 1e-12:
            continue
        angle = math.atan2(y1 - y0, x1 - x0)
        cos_a, sin_a = math.cos(-angle), math.sin(-angle)
        us = [p[0] * cos_a - p[1] * sin_a for p in hull]
        vs = [p[0] * sin_a + p[1] * cos_a for p in hull]
        width = max(us) - min(us)
        depth = max(vs) - min(vs)
        area = width * depth
        if best is None or area < best[0] - 1e-12:
            mid_u = (min(us) + max(us)) / 2.0
            mid_v = (min(vs) + max(vs)) / 2.0
            centre_x = mid_u * math.cos(angle) - mid_v * math.sin(angle)
            centre_y = mid_u * math.sin(angle) + mid_v * math.cos(angle)
            best = (area, angle, width, depth, centre_x, centre_y)

    if best is None:
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        return (0.0, max(xs) - min(xs), max(ys) - min(ys),
                (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0)

    return best[1], best[2], best[3], best[4], best[5]


def box_gap(a, b):
    """Clear distance between two plan boxes, zero where they overlap."""
    dx = max(0.0, max(a[0] - b[1], b[0] - a[1]))
    dy = max(0.0, max(a[2] - b[3], b[2] - a[3]))
    return math.sqrt(dx * dx + dy * dy)


def boxes_within(a, b, gap):
    """True when two plan boxes are within gap of each other."""
    return box_gap(a, b) <= gap


def service_angle(service):
    """How a service is turned in plan, in degrees, 0 to 180.

    Taken from the tightest rectangle around its own footprint, so it is the
    direction the service actually runs rather than anything read from a
    parameter.
    """
    points = service_points(service)
    if not points:
        return None
    angle, span_u, span_v, _, _ = min_area_rect([(p.X, p.Y) for p in points])
    if span_u < span_v:
        # report the long axis, so a tray and the same tray drawn the other
        # way round are recognised as the same orientation
        angle += math.pi / 2.0
    return math.degrees(angle) % 180.0


def angles_align(a, b, tolerance):
    """True when two plan angles point the same way, within tolerance.

    Orientation repeats every 180 degrees, so 179 and 1 are two degrees
    apart, not 178.
    """
    if a is None or b is None:
        return True
    difference = abs(a - b) % 180.0
    return min(difference, 180.0 - difference) <= tolerance


def cluster_services(services, gap_ft, angle_tol=None):
    """Group services that sit within gap of each other in plan.

    Services running side by side belong in one opening rather than a row of
    small ones. Grouping is transitive -- A near B and B near C puts all three
    together -- so a run of services is not split by the order they were
    picked.
    """
    boxes = []
    keep = []
    for service in services:
        box = plan_bounds(service)
        if box is None:
            continue
        boxes.append(box)
        keep.append(service)

    if not keep:
        return []

    parent = list(range(len(keep)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    angles = [service_angle(sv) for sv in keep] if angle_tol is not None \
        else [None] * len(keep)

    for i in range(len(keep)):
        for j in range(i + 1, len(keep)):
            if not boxes_within(boxes[i], boxes[j], gap_ft):
                continue
            # close is not enough: two trays crossing at right angles would
            # need an opening several times the size of either, so they are
            # left to their own
            if angle_tol is not None \
                    and not angles_align(angles[i], angles[j], angle_tol):
                debug('   {} and {} are close but {:.0f} and {:.0f} deg '
                      'apart, so they keep separate openings'.format(
                          describe_element(keep[i].element),
                          describe_element(keep[j].element),
                          angles[i] or 0, angles[j] or 0))
                continue
            union(i, j)

    groups = {}
    for index, service in enumerate(keep):
        groups.setdefault(find(index), []).append(service)

    ordered = sorted(groups.values(),
                     key=lambda g: (min(plan_bounds(s)[0] for s in g),
                                    min(plan_bounds(s)[2] for s in g)))
    debug('{} service(s) grouped into {} opening(s) at {:.0f} mm'.format(
        len(keep), len(ordered), ft_to_mm(gap_ft)))
    return ordered


# Which elevation property is in the same coordinate space as the model's
# geometry is decided by measurement, once per run, and cached here.
LEVEL_Z_PROP = None


def level_z(level):
    """A level's elevation in the SAME space as element geometry.

    Revit exposes two: Elevation and ProjectElevation. Which one matches the
    internal coordinates that Location points and bounding boxes are given in
    depends on the project's base point, so it is chosen by measurement in
    calibrate_levels() rather than assumed. Reading the wrong one puts every
    level tens of metres from the geometry, which is what made openings pick
    the basement and then need an 88 metre correction.
    """
    for prop in ((LEVEL_Z_PROP,) if LEVEL_Z_PROP else
                 ('Elevation', 'ProjectElevation')):
        try:
            value = getattr(level, prop)
            if value is not None:
                return value
        except Exception:
            continue
    return 0.0


def calibrate_levels(levels, reference_z):
    """Pick the elevation property that actually matches the geometry.

    reference_z is a point known to be in internal coordinates -- the click on
    the floor. Whichever property puts a level closest to it is the one in the
    same space.
    """
    global LEVEL_Z_PROP
    LEVEL_Z_PROP = None
    if not levels or reference_z is None:
        return

    best = None
    for prop in ('Elevation', 'ProjectElevation'):
        values = []
        for level in levels:
            try:
                value = getattr(level, prop)
                if value is not None:
                    values.append(value)
            except Exception:
                continue
        if not values:
            continue
        gap = min(abs(value - reference_z) for value in values)
        debug('level property "{}": nearest is {:.0f} mm from the floor'
              .format(prop, ft_to_mm(gap)))
        if best is None or gap < best[1]:
            best = (prop, gap)

    if best is not None:
        LEVEL_Z_PROP = best[0]
        debug('using "{}" for level elevations'.format(LEVEL_Z_PROP))


def build_jobs(services, group_gap_ft, pipe_gap_ft, method='auto',
               angle_tol=15.0):
    """Decide what gets its own opening and what shares one.

    The rules, in order:
      * trays and ducts are rectangular; anything within group_gap of another
        shares one rectangular opening sized to encompass them all
      * a pipe within pipe_gap of one of those groups joins it, because a hole
        beside a tray opening is not worth forming separately
      * every other pipe gets its own circular opening

    Returns [(shape, [services])].
    """
    if method == 'circular':
        return [('round', [sv]) for sv in services]

    rect = [sv for sv in services if service_shape(sv) == 'rect']
    round_ = [sv for sv in services if service_shape(sv) != 'rect']

    if method == 'rectangular':
        rect, round_ = services, []

    groups = [list(g) for g in cluster_services(rect, group_gap_ft, angle_tol)] \
        if rect else []

    # a pipe close to a rectangular group is absorbed into it
    loose = []
    for service in round_:
        box = plan_bounds(service)
        if box is None:
            continue
        joined = None
        best = None
        for index, group in enumerate(groups):
            for member in group:
                other = plan_bounds(member)
                if other is None:
                    continue
                gap = box_gap(box, other)
                if gap <= pipe_gap_ft and (best is None or gap < best):
                    best, joined = gap, index
        if joined is None:
            loose.append(service)
        else:
            groups[joined].append(service)
            debug('   {} joins a rectangular opening ({:.0f} mm from it)'
                  .format(describe_element(service.element), ft_to_mm(best)))

    jobs = [('rect', group) for group in groups]
    jobs.extend(('round', [service]) for service in loose)

    debug('{} rectangular opening(s), {} circular'.format(
        len(groups), len(loose)))
    return jobs


def slab_job_settings(settings, shape, symbol, profiles):
    """Settings for one slab opening, with its own family's profile."""
    slot = 'slab_circ' if shape == 'round' else 'slab_rect'
    values = dict(settings)
    name = family_name_of(symbol)
    if name:
        values[families.slot_family_key(slot)] = name
    return families.overlay(values, slot, profiles)


def nearest_level(levels, elevation):
    """The level closest to an elevation, above or below."""
    if not levels:
        return None
    return min(levels, key=lambda lvl: abs(level_z(lvl) - elevation))


def level_param_ids():
    """The built in parameters that can hold a family instance's level.

    Which ones exist varies with the Revit release, so each is fetched on its
    own and a missing name is simply skipped.
    """
    wanted = ['FAMILY_LEVEL_PARAM',
              'INSTANCE_SCHEDULE_ONLY_LEVEL_PARAM',
              'INSTANCE_REFERENCE_LEVEL_PARAM',
              'SCHEDULE_LEVEL_PARAM',
              'FAMILY_BASE_LEVEL_PARAM']
    found = []
    for name in wanted:
        try:
            found.append(getattr(DB.BuiltInParameter, name))
        except AttributeError:
            continue
    return found


def get_instance_level(doc, instance):
    """The level the instance is actually associated with, or None."""
    for bip in level_param_ids():
        try:
            param = instance.get_Parameter(bip)
            if param is None or param.StorageType != DB.StorageType.ElementId:
                continue
            level = doc.GetElement(param.AsElementId())
            if isinstance(level, DB.Level):
                return level
        except Exception:
            continue
    return None


def set_instance_level(doc, instance, level):
    """Point the instance at a level.

    Every writable level parameter is set, not just the first one that takes
    it -- otherwise Schedule Level can quietly accept the new level while the
    real Level parameter stays on whatever Revit created it against, which is
    exactly how an instance ends up reading as the lowest level.
    """
    changed = False
    for bip in level_param_ids():
        try:
            param = instance.get_Parameter(bip)
            if param is None or param.IsReadOnly:
                continue
            if param.StorageType != DB.StorageType.ElementId:
                continue
            param.Set(level.Id)
            changed = True
        except Exception:
            continue
    return changed


def level_code(level, levels):
    """Two character code for a level.

    "Level 00" gives 00, "Level 03" gives 03, anything containing Roof gives
    RF. Failing both, any number in the name is used, and a name with no number
    at all falls back to the level's position counting up from the lowest.
    """
    name = (level.Name or '').upper()

    numbered = re.search(r'LEVEL\s*[-_]?\s*(\d+)', name)
    if numbered:
        return '{:02d}'.format(int(numbered.group(1)) % 100)

    for keyword, code in LEVEL_CODE_RULES:
        if keyword.upper() in name:
            return code

    digits = re.findall(r'\d+', name)
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
# worksets and pinning
# ---------------------------------------------------------------------------
def list_worksets(doc):
    """Every user workset in the model, by name."""
    if not doc.IsWorkshared:
        return []
    try:
        worksets = list(DB.FilteredWorksetCollector(doc)
                        .OfKind(DB.WorksetKind.UserWorkset))
    except Exception:
        return []
    return sorted(worksets, key=lambda w: w.Name.lower())


def find_workset_by_name(doc, name):
    for workset in list_worksets(doc):
        if workset.Name == name:
            return workset
    return None


def assign_workset(element, workset):
    param = element.get_Parameter(DB.BuiltInParameter.ELEM_PARTITION_PARAM)
    if param is None or param.IsReadOnly:
        return False
    param.Set(int(eid_value(workset.Id)))
    return True


def family_clearance_mm(family, default_mm=families.DEFAULT_CLEARANCE_MM,
                        profiles=None):
    """The clearance each side for a family: its own, set in Family
    settings, or the tab's when it has none."""
    if profiles is None:
        profiles = load_profiles()
    value = families.clearance_for(family, profiles, default_mm)
    debug('clearance for {}: {:g} mm ({})'.format(
        family, value, 'family settings' if value != default_mm or
        families.family_clearance(family, profiles) is not None
        else 'the tab'))
    return value


def place_on_workset(doc, instance, options, workset, notes,
                     profiles=None):
    """Put a placed or resized BWIC on its workset.

    The workset set in the family's own Family settings wins; a family with
    none follows the one chosen in Settings (options['workset_name'], already
    looked up as `workset`). Either can say "active workset", which leaves
    the instance where Revit put it.
    """
    if not doc.IsWorkshared:
        return
    try:
        family = family_name_of(instance.Symbol)
    except Exception:
        family = ''
    if profiles is None:
        profiles = load_profiles()
    choice = families.family_workset(family, profiles)
    settings_name = options.get('workset_name')
    name = families.workset_choice(choice, settings_name)
    debug('workset for {}: family says "{}", Settings "{}" -> {}'.format(
        family, choice, settings_name or '', name or 'active'))
    if not name:
        return
    if workset is None or workset.Name != name:
        workset = find_workset_by_name(doc, name)
    if workset is None:
        notes.append('workset "{}" not found'.format(name))
    elif assign_workset(instance, workset):
        notes.append('workset "{}"'.format(workset.Name))
    else:
        notes.append('could not set the workset')


def pin_element(element):
    try:
        if not element.Pinned:
            element.Pinned = True
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Comments logging
# ---------------------------------------------------------------------------
def describe_element(element):
    """'Family: Type' for a loadable family, 'Category: Type' otherwise."""
    doc = element.Document
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


def build_comment(services):
    """Summarise the selected services: 'Pipe Types: Standard x3_Duct: Rect x2'

    Linked services are counted alongside host ones, so the comment describes
    everything the opening was sized around.
    """
    order = []
    counts = {}
    for service in services:
        key = describe_element(service.element)
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


def spread(points, along):
    """How far a set of points reaches along a horizontal direction."""
    values = [p.X * along.X + p.Y * along.Y for p in points]
    return max(values) - min(values)


def spread_z(points):
    values = [p.Z for p in points]
    return max(values) - min(values)


# ---------------------------------------------------------------------------
# the placement itself
# ---------------------------------------------------------------------------
def compute_bwic(doc, services, wall, transform, clearance_ft,
                 preferred_level=None):
    """Work out the size and position an opening needs. No model changes.

    Shared by placing a new BWIC and resizing an existing one, so both follow
    exactly the same rules.
    """
    thickness = get_wall_thickness(wall)
    if thickness is None:
        return None, 'could not read a thickness from that wall'

    wall_curve = wall.Location.Curve.CreateTransformed(transform)

    corners = []
    for service in services:
        corners.extend(service_points(service))
    if not corners:
        return None, 'the selected elements have no geometry to measure'

    centroid = DB.XYZ(sum(p.X for p in corners) / len(corners),
                      sum(p.Y for p in corners) / len(corners),
                      sum(p.Z for p in corners) / len(corners))

    base_pt, along, normal = wall_frame_at(wall_curve, centroid)

    # measure again, counting straight runs only inside the wall: a pipe's
    # fall or angle beyond the wall must not grow the opening
    plane = (DB.XYZ(base_pt.X, base_pt.Y, 0),
             DB.XYZ(normal.X, normal.Y, 0).Normalize(), thickness / 2.0)
    inside = []
    for service in services:
        inside.extend(service_points(service, plane))
    if inside:
        debug('services measured inside the wall: {:.1f} x {:.1f} mm '
              '(whole runs {:.1f} x {:.1f} mm)'.format(
                  ft_to_mm(spread(inside, along)), ft_to_mm(spread_z(inside)),
                  ft_to_mm(spread(corners, along)), ft_to_mm(spread_z(corners))))
        corners = inside

    u_values = [p.X * along.X + p.Y * along.Y for p in corners]
    u_min, u_max = min(u_values), max(u_values)
    u_mid = (u_min + u_max) / 2.0

    z_values = [p.Z for p in corners]
    z_min, z_max = min(z_values), max(z_values)

    width = round_up_ft((u_max - u_min) + 2 * clearance_ft)
    height = round_up_ft((z_max - z_min) + 2 * clearance_ft)
    length = thickness

    if ROUND_WALL is not None:
        # one pipe: its real outside diameter. Anything else: the circle that
        # encloses the cross-section, so no corner is cut off
        outer_mm = None
        if len(services) == 1:
            dia, source, _ = outside_diameter(services[0].element)
            if dia is not None:
                if ROUND_WALL.get('insulation', True):
                    dia += 2 * insulation_thickness(services[0].element)
                outer_mm = ft_to_mm(dia)
                debug('round hole from {} {:.1f} mm'.format(source, outer_mm))
        hole_mm = families.round_hole_mm(
            outer_mm, ft_to_mm(u_max - u_min), ft_to_mm(z_max - z_min),
            ROUND_WALL.get('gap_mm', 50.0), ROUND_WALL.get('round_mm', 10.0))
        debug('round hole {:.0f} mm ({})'.format(
            hole_mm, 'outside diameter' if outer_mm else
            'circle around {:.0f} x {:.0f} mm'.format(
                ft_to_mm(u_max - u_min), ft_to_mm(z_max - z_min))))
        width = height = mm_to_ft(hole_mm)

    # slide along the wall to the middle of the selection, then re-project so
    # the instance stays on the centre line (matters on curved walls)
    for _ in range(2):
        base_u = base_pt.X * along.X + base_pt.Y * along.Y
        plan_pt = base_pt + along * (u_mid - base_u)
        base_pt, along, normal = wall_frame_at(wall_curve, plan_pt)
    base_u = base_pt.X * along.X + base_pt.Y * along.Y
    plan_pt = base_pt + along * (u_mid - base_u)

    # midway between the bottom of the lowest service and the top of the
    # highest, so the opening encompasses the whole selection centrally
    if ELEVATION_MODE == 'highest_service':
        target_z = max(element_centre_z(sv) for sv in services)
    else:
        target_z = (z_min + z_max) / 2.0

    if ORIGIN_VERTICAL == 'bottom':
        origin_z = target_z - height / 2.0
    elif ORIGIN_VERTICAL == 'top':
        origin_z = target_z + height / 2.0
    else:
        origin_z = target_z

    levels = sorted_levels(doc)
    if not levels:
        return None, 'this project has no levels'

    # a plan view names the level outright; anything else (3D, section) falls
    # back to the nearest level at or below the BWIC
    level = preferred_level or level_below(levels, origin_z)

    return {
        'length': length,
        'width': width,
        'height': height,
        'point': DB.XYZ(plan_pt.X, plan_pt.Y, origin_z),
        'normal': normal,
        'target_z': target_z,
        'level': level,
        'levels': levels,
        'preferred_level': preferred_level,
    }, None


def sized_symbol(doc, symbol, geom, notes):
    """The family type to use, with the type level sizes written if needed."""
    if not symbol.IsActive:
        symbol.Activate()
        doc.Regenerate()

    length, width, height = geom['length'], geom['width'], geom['height']

    place_symbol = symbol
    writes = wall_size_writes(length, width, height)
    if [n for n, _ in writes
            if n and has_length_param(symbol, n)] \
            and DUPLICATE_TYPE_IF_TYPE_PARAMS:
        new_name = unique_type_name(symbol, length, width, height)
        existing = find_symbol_by_name(doc, symbol.Family, new_name)
        place_symbol = existing if existing is not None \
            else symbol.Duplicate(new_name)
        if not place_symbol.IsActive:
            place_symbol.Activate()
        doc.Regenerate()
        notes.append('sized on type "{}"'.format(new_name))

    for pname, pvalue in writes:
        if has_length_param(place_symbol, pname):
            ok, msg = set_length_param(place_symbol, pname, pvalue)
            if not ok:
                notes.append(msg)
    doc.Regenerate()
    return place_symbol


def apply_to_instance(doc, instance, geom, place_symbol, services, options,
                      workset, notes):
    """Size, orient, position and stamp an instance. Shared by both routines."""
    target_point = geom['point']
    normal = geom['normal']
    levels = geom['levels']

    for pname, pvalue in wall_size_writes(geom['length'], geom['width'],
                                          geom['height']):
        if not pname:
            continue
        if has_length_param(instance, pname):
            ok, msg = set_length_param(instance, pname, pvalue)
            if not ok:
                notes.append(msg)
        elif not has_length_param(place_symbol, pname):
            notes.append('{} not found on the family'.format(
                families.show_name(pname)))
    doc.Regenerate()

    # align the Front/Back reference plane to the wall centre line
    try:
        facing = instance.FacingOrientation
        facing = DB.XYZ(facing.X, facing.Y, 0)
        if facing.GetLength() > 1e-9:
            angle = facing.Normalize().AngleOnPlaneTo(normal, DB.XYZ.BasisZ)
            if abs(angle) > 1e-9:
                origin = instance.Location.Point \
                    if isinstance(instance.Location, DB.LocationPoint) \
                    else target_point
                axis = DB.Line.CreateBound(origin, origin + DB.XYZ.BasisZ)
                DB.ElementTransformUtils.RotateElement(doc, instance.Id, axis,
                                                       angle)
    except Exception as err:
        notes.append('rotation skipped: {}'.format(err))
    doc.Regenerate()

    # X, Y and Z in one move
    loc = instance.Location
    if isinstance(loc, DB.LocationPoint):
        delta = target_point - loc.Point
        if delta.GetLength() > 1e-9:
            DB.ElementTransformUtils.MoveElement(doc, instance.Id, delta)
    doc.Regenerate()

    # level -- the one it sits on, or the nearest one beneath it. Checked
    # against the final position rather than the placement point.
    wanted_level = geom['preferred_level'] \
        or level_below(levels, target_point.Z)
    actual_level = get_instance_level(doc, instance)

    if wanted_level is not None and \
            (actual_level is None or actual_level.Id != wanted_level.Id):
        if set_instance_level(doc, instance, wanted_level):
            doc.Regenerate()
            # changing the level re-bases the offset, so put it back
            loc = instance.Location
            if isinstance(loc, DB.LocationPoint):
                delta = target_point - loc.Point
                if delta.GetLength() > 1e-9:
                    DB.ElementTransformUtils.MoveElement(doc, instance.Id, delta)
            doc.Regenerate()
            actual_level = get_instance_level(doc, instance) or wanted_level
        else:
            notes.append('could not move it onto level {}'.format(
                wanted_level.Name))

    level = actual_level or wanted_level or geom['level']

    # workset -- before pinning, and before anything reads the instance back.
    # The family's own Family settings can name one; else Settings decides.
    place_on_workset(doc, instance, options, workset, notes)

    # level code from the level the instance ended up on, e.g. L00 -> 00
    level_param = options.get('level_param')
    if level_param and level is not None:
        code = level_code(level, levels)
        ok, msg = set_level_code(instance, level_param, code)
        if ok:
            notes.append('{} = {} ({})'.format(level_param, code, level.Name))
        else:
            notes.append(msg)
    elif level is not None:
        notes.append('level {}'.format(level.Name))

    if level is not None and options.get('level_source'):
        notes.append('level from the {}'.format(options['level_source']))

    if options.get('log_comments'):
        try:
            comment = build_comment(services)
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

    # pinning last, so nothing else has to fight a pinned element
    if options.get('pin'):
        pinned_services = len([sv.element for sv in services
                               if not sv.linked and pin_element(sv.element)])
        pinned_bwic = pin_element(instance)
        notes.append('pinned {} service{} and {}the BWIC'.format(
            pinned_services,
            '' if pinned_services == 1 else 's',
            '' if pinned_bwic else 'not '))

    notes.append('L {:.0f} / W {:.0f} / H {:.0f} mm at {:.0f} mm'.format(
        ft_to_mm(geom['length']), ft_to_mm(geom['width']),
        ft_to_mm(geom['height']), ft_to_mm(geom['target_z'])))


def place_one(doc, services, wall, transform, clearance_ft, symbol,
              options, workset, preferred_level=None):
    """Places and sizes one BWIC. Returns (instance, notes list)."""
    notes = []

    geom, error = compute_bwic(doc, services, wall, transform, clearance_ft,
                               preferred_level)
    if geom is None:
        return None, [error]

    place_symbol = sized_symbol(doc, symbol, geom, notes)

    instance = None
    try:
        instance = doc.Create.NewFamilyInstance(
            geom['point'], place_symbol, geom['level'],
            StructuralType.NonStructural)
    except Exception as err:
        logger.debug('level overload refused: {}'.format(err))
    if instance is None:
        # this overload puts the instance on the lowest level, so the level is
        # forced back on below
        instance = doc.Create.NewFamilyInstance(
            geom['point'], place_symbol, StructuralType.NonStructural)
        notes.append('placed without a level, level set afterwards')
    doc.Regenerate()

    apply_to_instance(doc, instance, geom, place_symbol, services, options,
                      workset, notes)
    return instance, notes


def instance_length_names(instance):
    """Every length-like parameter name on a placed BWIC and its type."""
    names = set()
    for holder in (instance, getattr(instance, 'Symbol', None)):
        if holder is None:
            continue
        try:
            for param in holder.Parameters:
                if param.StorageType == DB.StorageType.Double:
                    names.add(param.Definition.Name)
        except Exception:
            continue
    return sorted(names)


def resize_family_names(context):
    """Families a resize will accept: only those whose Family settings have
    been saved -- a BWIC is never resized by guesswork."""
    return [n for n in load_profiles().keys() if n]


def resize_settings(instance, context):
    """(slot, settings) for resizing this BWIC: its own family's settings."""
    family = family_name_of(instance.Symbol)
    slot, values, saved = families.settings_for_family(
        family, context, read_settings(), load_profiles(),
        instance_length_names(instance))
    debug('resizing "{}" as {} with its {} family settings'.format(
        family, slot, 'saved' if saved else 'guessed'))
    return slot, values


def use_wall_family(instance, options):
    """Point the wall sizing at a picked BWIC's own family, for one resize.

    Returns what it replaced, for restore_wall_family().
    """
    global FAMILY_NAME, P_LENGTH, P_WIDTH, P_HEIGHT, WALL_SHAPE, \
        P_DIAMETER, WALL_RADIUS, ROUND_WALL
    saved = (FAMILY_NAME, P_LENGTH, P_WIDTH, P_HEIGHT, WALL_SHAPE,
             P_DIAMETER, WALL_RADIUS, ROUND_WALL)
    slot, values = resize_settings(instance, 'wall')
    FAMILY_NAME = family_name_of(instance.Symbol) or FAMILY_NAME
    if slot == 'wall_circ':
        P_LENGTH = values.get('wall_circ_length_param') or ''
        P_DIAMETER = values.get('wall_circ_diameter_param') or 'BGL_Diameter'
        WALL_RADIUS = values.get('wall_circ_radius') == 'yes'
        WALL_SHAPE = families.CIRC
        spec = options.get('round_wall') or options.get('round_spec') \
            or {'gap_mm': 50.0, 'round_mm': 10.0, 'insulation': True}
        # the picked family's own clearance, else the Circular tab's gap
        ROUND_WALL = dict(spec)
        ROUND_WALL['gap_mm'] = family_clearance_mm(
            FAMILY_NAME, spec.get('gap_mm', 50.0))
    else:
        P_LENGTH = values.get('wall_length_param') or DEFAULT_P_LENGTH
        P_WIDTH = values.get('wall_width_param') or DEFAULT_P_WIDTH
        P_HEIGHT = values.get('wall_height_param') or DEFAULT_P_HEIGHT
        WALL_SHAPE = families.RECT
        P_DIAMETER = ''
        ROUND_WALL = None
    return saved


def restore_wall_family(saved):
    global FAMILY_NAME, P_LENGTH, P_WIDTH, P_HEIGHT, WALL_SHAPE, \
        P_DIAMETER, WALL_RADIUS, ROUND_WALL
    (FAMILY_NAME, P_LENGTH, P_WIDTH, P_HEIGHT, WALL_SHAPE, P_DIAMETER,
     WALL_RADIUS, ROUND_WALL) = saved


def resize_one(doc, instance, services, wall, transform, clearance_ft,
               options, workset, preferred_level=None):
    """Resize and reposition an existing BWIC. Returns (instance, notes)."""
    notes = []

    geom, error = compute_bwic(doc, services, wall, transform, clearance_ft,
                               preferred_level)
    if geom is None:
        return None, [error]

    was_pinned = False
    try:
        was_pinned = instance.Pinned
        if was_pinned:
            instance.Pinned = False
            notes.append('unpinned to move it')
    except Exception:
        pass

    # the wall may have changed kind since it was placed, so the type is
    # re-evaluated rather than assumed
    base_symbol = instance.Symbol
    try:
        family = base_symbol.Family
        default_symbol = None
        for sid in family.GetFamilySymbolIds():
            candidate = doc.GetElement(sid)
            if candidate is not None:
                default_symbol = candidate
                break
        wanted, wall_note = choose_symbol(doc, wall, default_symbol or
                                          base_symbol, {})
        notes.append(wall_note)
        base_symbol = wanted
    except Exception:
        logger.debug('kept the existing type')

    place_symbol = sized_symbol(doc, base_symbol, geom, notes)

    if place_symbol.Id != instance.Symbol.Id:
        try:
            instance.Symbol = place_symbol
            doc.Regenerate()
        except Exception as err:
            notes.append('could not change the type: {}'.format(err))

    apply_to_instance(doc, instance, geom, place_symbol, services, options,
                      workset, notes)

    if was_pinned and not options.get('pin'):
        pin_element(instance)
        notes.append('re-pinned')
    return instance, notes


# ---------------------------------------------------------------------------
# step prompts -- what the user is asked to pick next
# ---------------------------------------------------------------------------
# The core only announces where a run has got to; the window decides how to
# show it. Kept free of WPF so the wording can be proved on the bench.
FLOWS = {
    'wall_place': ['services', 'wall'],
    'wall_resize': ['bwic', 'services', 'wall'],
    'slab_place': ['services', 'floor'],
    'slab_resize': ['opening', 'services', 'floor'],
}

STEP_TEXT = {
    'bwic': ('Pick the BWIC to resize',
             'Click the existing BWIC you want re-fitted to new services.'),
    'opening': ('Pick the slab opening to resize',
                'Click the existing slab opening you want re-fitted.'),
    'services': ('Select the services',
                 'Pick the pipes, ducts, cable trays or conduit passing '
                 'through, then click Finish on the Options Bar, top left, '
                 'or press Return.'),
    'wall': ('Click the wall',
             'Click the wall the services pass through. Walls in linked '
             'models work too.'),
    'floor': ('Click the floor',
              'Click the floor the services pass through. Floors in linked '
              'models work too.'),
}

# what each step needs before it is answered: Finish, or a single click
STEP_ENDS = {'services': 'finish', 'bwic': 'click', 'opening': 'click',
             'wall': 'click', 'floor': 'click'}

_GUIDE = [None]


def step_info(flow, key, linked=False):
    """(number, total, title, detail, ends) for one step of one flow."""
    steps = FLOWS[flow]
    title, detail = STEP_TEXT[key]
    if key == 'services' and linked:
        detail = detail.replace('passing through,',
                                'passing through, linked ones included,')
    return (steps.index(key) + 1, len(steps), title, detail,
            STEP_ENDS[key])


def step_dict(flow, key, linked=False):
    """A step for the prompt. Never raises: it is worked out before guide()
    is called, outside its protection, and a prompt must not stop a run."""
    try:
        number, total, title, detail, ends = step_info(flow, key, linked)
    except Exception as err:
        debug('unknown step {} / {}: {}'.format(flow, key, err))
        number, total, title, detail, ends = 1, 1, key, '', 'click'
    return {'flow': flow, 'key': key, 'number': number, 'total': total,
            'title': title, 'detail': detail, 'ends': ends}


def set_guide(callback):
    """Who to tell where a run has got to. None stops telling anyone."""
    _GUIDE[0] = callback


def guide(event, **details):
    """Tell the window where the run has got to. Never stops the run."""
    callback = _GUIDE[0]
    if callback is None:
        return
    try:
        callback(event, details)
    except Exception as err:
        debug('step prompt failed: {}'.format(err))


def press_finish():
    """Finish the selection Revit is waiting on, as its Finish button would.

    There is no API call for the Options Bar's Finish button, and a Return
    sent from the tool window's click arrived while the tool window still
    had the keyboard, so Revit never saw it (2.17.0). So the button itself is
    pressed:

      1. as a Windows button among Revit's child windows (BM_CLICK),
      2. else through UI Automation (Invoke),
      3. else Return is posted straight to the active view's window.

    It runs on its own thread, after the click handler has returned: Revit's
    window answers UI Automation and SendMessage on the UI thread, which the
    click handler would otherwise still be holding. Only ever called while a
    step that ends with Finish is waiting -- Return with nothing waiting
    repeats Revit's last command.
    """
    try:
        hwnd = int(str(HOST_APP.uiapp.MainWindowHandle))
    except Exception as err:
        debug('Finish Selection: no Revit window handle ({})'.format(err))
        return False
    # the click gave the tool window the keyboard: hand it back to Revit so
    # the next pick, the wall, answers straight away
    focus_revit()
    try:
        from System.Threading import Thread, ThreadStart
        worker = Thread(ThreadStart(lambda: _press_finish(hwnd)))
        worker.IsBackground = True
        worker.Start()
        return True
    except Exception as err:
        debug('Finish Selection could not start: {}'.format(err))
        return False


def _press_finish(hwnd):
    # an exception escaping a .NET thread ends Revit: nothing may get out
    try:
        if _finish_by_button(hwnd):
            return
        if _finish_by_automation(hwnd):
            return
        _finish_by_return(hwnd)
    except BaseException as err:
        try:
            debug('Finish Selection failed: {}'.format(err))
        except BaseException:
            pass
    except:
        pass


def _child_windows(hwnd):
    """(handle, class, text, visible, enabled) for every child window."""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    found = []
    proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def visit(child, _):
        try:
            cls = ctypes.create_unicode_buffer(128)
            user32.GetClassNameW(child, cls, 128)
            length = user32.GetWindowTextLengthW(child)
            text = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(child, text, length + 1)
            found.append((child, cls.value, text.value,
                          bool(user32.IsWindowVisible(child)),
                          bool(user32.IsWindowEnabled(child))))
        except Exception:
            pass
        return True

    callback = proc(visit)
    user32.EnumChildWindows(hwnd, callback, 0)
    return found


def _finish_by_button(hwnd):
    import ctypes
    user32 = ctypes.windll.user32
    windows = _child_windows(hwnd)
    for child, cls, text, visible, enabled in windows:
        if visible and enabled and steps_finish_label(text):
            debug('Finish Selection: pressing the Options Bar button '
                  '"{}" ({})'.format(text, cls))
            BM_CLICK = 0x00F5
            user32.SendMessageW(child, BM_CLICK, 0, 0)
            return True
    debug('Finish Selection: no Finish window among {} child windows; '
          'candidates: {}'.format(len(windows), ', '.join(
              '"{}" {}'.format(t, c) for _, c, t, v, _ in windows
              if t and v and len(t) < 30)[:600] or 'none'))
    return False


def _finish_by_automation(hwnd):
    import clr
    clr.AddReference('UIAutomationClient')
    clr.AddReference('UIAutomationTypes')
    from System import IntPtr
    from System.Windows.Automation import (AutomationElement, ControlType,
                                           InvokePattern, PropertyCondition,
                                           TreeScope)
    root = AutomationElement.FromHandle(IntPtr(hwnd))
    buttons = root.FindAll(TreeScope.Descendants, PropertyCondition(
        AutomationElement.ControlTypeProperty, ControlType.Button))
    names = []
    for index in range(buttons.Count):
        element = buttons[index]
        try:
            name = element.Current.Name
            names.append(name)
            if not steps_finish_label(name) or not element.Current.IsEnabled \
                    or element.Current.IsOffscreen:
                continue
            pattern = element.GetCurrentPattern(InvokePattern.Pattern)
            debug('Finish Selection: invoking "{}" through UI Automation'
                  .format(name))
            pattern.Invoke()
            return True
        except Exception:
            continue
    debug('Finish Selection: UI Automation found no Finish button among {} '
          'buttons'.format(len(names)))
    return False


def _finish_by_return(hwnd):
    """Post Return to the active view, not the main frame."""
    import ctypes
    user32 = ctypes.windll.user32
    WM_MDIGETACTIVE = 0x0229
    WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101
    target = 0
    for child, cls, _, _, _ in _child_windows(hwnd):
        if cls == 'MDIClient':
            target = user32.SendMessageW(child, WM_MDIGETACTIVE, 0, 0)
            break
    if target:
        # the view itself is the active frame's first child
        inner = user32.GetWindow(target, 5)   # GW_CHILD
        target = inner or target
    target = target or hwnd
    debug('Finish Selection: posting Return to window {}'.format(target))
    user32.PostMessageW(target, WM_KEYDOWN, VK_RETURN, 0x001C0001)
    user32.PostMessageW(target, WM_KEYUP, VK_RETURN, 0xC01C0001)
    return True


def steps_finish_label(text):
    import bwic_prompt
    return bwic_prompt.is_finish_label(text)


VK_RETURN = 0x0D
KEYEVENTF_KEYUP = 0x0002


def focus_revit():
    """Put Revit in the foreground with the keyboard actually attached to it.

    A bare SetForegroundWindow is refused by Windows when the calling thread
    does not own the foreground window, which leaves Revit painted on top but
    the keystrokes still going to the tool window -- that is what stops Return
    finishing a selection. Attaching the input queues first makes the call
    stick, and the attachment is undone straight away.
    """
    try:
        import ctypes
        user32 = ctypes.windll.user32
        hwnd = int(str(HOST_APP.uiapp.MainWindowHandle))

        foreground = user32.GetForegroundWindow()
        if foreground == hwnd:
            return

        this_thread = user32.GetWindowThreadProcessId(foreground, None)
        revit_thread = user32.GetWindowThreadProcessId(hwnd, None)

        attached = False
        if this_thread and revit_thread and this_thread != revit_thread:
            attached = bool(user32.AttachThreadInput(this_thread,
                                                     revit_thread, True))
        try:
            user32.SetForegroundWindow(hwnd)
            user32.SetFocus(hwnd)
        finally:
            if attached:
                user32.AttachThreadInput(this_thread, revit_thread, False)
    except Exception:
        logger.debug('could not set focus to the Revit window')


# ---------------------------------------------------------------------------
# the loop that runs while the window stays open
# ---------------------------------------------------------------------------
def run_placement_loop(uiapp, clearance_mm, options, report, mode='place'):
    """Place or resize wall BWICs, rectangular or round.

    A round run swaps in the circular family and its parameter names for its
    own length only, and always puts the rectangular ones back -- whatever the
    run ends with -- so the next rectangular run is not left sizing a circle.
    """
    global FAMILY_NAME, P_LENGTH, WALL_SHAPE, P_DIAMETER, WALL_RADIUS, \
        WALL_TYPE, ROUND_WALL
    round_wall = options.get('round_wall')
    if not round_wall:
        return _wall_loop(uiapp, clearance_mm, options, report, mode)

    saved = (FAMILY_NAME, P_LENGTH, WALL_SHAPE, P_DIAMETER, WALL_RADIUS,
             WALL_TYPE, ROUND_WALL)
    try:
        FAMILY_NAME = round_wall.get('family') or FAMILY_NAME
        P_LENGTH = round_wall.get('through') or ''
        P_DIAMETER = round_wall.get('diameter') or 'BGL_Diameter'
        WALL_RADIUS = bool(round_wall.get('radius'))
        WALL_TYPE = round_wall.get('type') or ''
        WALL_SHAPE = families.CIRC
        # the round family's own clearance, else the Circular tab's gap
        ROUND_WALL = dict(round_wall)
        ROUND_WALL['gap_mm'] = family_clearance_mm(
            FAMILY_NAME, round_wall.get('gap_mm', 50.0))
        return _wall_loop(uiapp, clearance_mm, options, report, mode)
    finally:
        (FAMILY_NAME, P_LENGTH, WALL_SHAPE, P_DIAMETER, WALL_RADIUS,
         WALL_TYPE, ROUND_WALL) = saved


def _wall_loop(uiapp, clearance_mm, options, report, mode='place'):
    """The pick-and-go loop. mode is 'place' for new BWICs, 'resize' to
    re-fit an existing one to a fresh selection of services."""
    uidoc = uiapp.ActiveUIDocument
    if uidoc is None:
        report('No active Revit document.')
        return

    doc = uidoc.Document
    # the tab's clearance, unless the family has its own
    tab_clearance_mm = clearance_mm
    clearance_mm = family_clearance_mm(FAMILY_NAME, tab_clearance_mm)
    clearance_ft = mm_to_ft(clearance_mm)

    start_debug(doc, 'WALL RUN ({})'.format(mode), None, options)
    debug('family "{}" clearance {} mm'.format(FAMILY_NAME, clearance_mm))
    debug('size parameters: width {}, height {}, through {}{}'.format(
        families.show_name(P_WIDTH), families.show_name(P_HEIGHT),
        families.show_name(P_LENGTH) or '-',
        ', diameter {}'.format(P_DIAMETER) if WALL_SHAPE == families.CIRC
        else ''))

    default_symbol = find_family_symbol(doc)
    if default_symbol is None:
        debug('family "{}" is not loaded'.format(FAMILY_NAME))
        report('The family "{}" is not loaded in this project.'.format(FAMILY_NAME))
        return
    symbol_cache = {}

    workset = None
    wanted_workset = options.get('workset_name')
    if wanted_workset:
        workset = find_workset_by_name(doc, wanted_workset)
        if workset is None:
            report('Workset "{}" is not in this model - the BWIC will land on '
                   'the active workset.'.format(wanted_workset))

    wall_filter = WallPickFilter(doc)
    include_linked = bool(options.get('include_linked'))
    service_filter = ServicePickFilter(doc, include_linked)
    resizing = (mode == 'resize')
    accepted = resize_family_names('wall') if resizing \
        else None
    bwic_filter = BWICPickFilter(accepted)
    placed = 0
    flow = 'wall_resize' if resizing else 'wall_place'

    while True:
        target = None

        # --- the existing BWIC, when resizing ------------------------------
        if resizing:
            preselected = [doc.GetElement(eid)
                           for eid in uidoc.Selection.GetElementIds()]
            preselected = [el for el in preselected
                           if is_bwic(el, accepted)]
            if len(preselected) == 1:
                target = preselected[0]
            else:
                try:
                    guide('step', **step_dict(flow, 'bwic'))
                    focus_revit()
                    ref = uidoc.Selection.PickObject(
                        ObjectType.Element, bwic_filter,
                        'Pick the BWIC to resize  '
                        '(Esc returns to the RevoBIM window)')
                    target = doc.GetElement(ref.ElementId)
                except OperationCanceledException:
                    break
                except Exception as err:
                    report('BWIC pick failed: {}'.format(err))
                    break
            uidoc.Selection.SetElementIds(List[DB.ElementId]())

        # --- the services, host and linked together ------------------------
        services = []
        if not resizing:
            for eid in uidoc.Selection.GetElementIds():
                el = doc.GetElement(eid)
                try:
                    if el is not None and el.get_BoundingBox(None) is not None:
                        services.append(Service(el))
                except Exception:
                    continue

        if not services:
            try:
                guide('step', **step_dict(flow, 'services', include_linked))
                focus_revit()
                refs = uidoc.Selection.PickObjects(
                    ObjectType.Element, service_filter,
                    'Select the services{}, then press Return or Finish  '
                    '(Esc returns to the RevoBIM window)'.format(
                        ', links included' if include_linked else ''))
            except OperationCanceledException:
                break
            except Exception as err:
                report('Selection failed: {}'.format(err))
                break
            for ref in refs:
                service = resolve_picked(doc, ref)
                if service is not None:
                    services.append(service)

        if not services:
            break

        linked_count = len([sv for sv in services if sv.linked])

        # --- the wall -----------------------------------------------------
        try:
            focus_revit()
            guide('step', **step_dict(flow, 'wall'))
            ref = uidoc.Selection.PickObject(
                ObjectType.LinkedElement, wall_filter,
                'Pick the wall to align the BWIC to  '
                '(Esc returns to the RevoBIM window)')
        except OperationCanceledException:
            uidoc.Selection.SetElementIds(List[DB.ElementId]())
            break
        except Exception as err:
            report('Wall pick failed: {}'.format(err))
            break

        # GlobalPoint is in host coordinates whatever the link placement
        pick_z = None
        try:
            if ref.GlobalPoint is not None:
                pick_z = ref.GlobalPoint.Z
                debug('click point Z {:.1f} mm (host coordinates)'.format(
                    ft_to_mm(pick_z)))
        except Exception:
            debug('the pick gave no global point, falling back to the '
                  'bounding box')

        # decide which level property matches the geometry, using the click
        if pick_z is not None:
            # the wall loop has no level list of its own yet
            levels = sorted_levels(doc)
            calibrate_levels(levels, pick_z)
            levels = sorted_levels(doc)
            debug('levels now: lowest "{}" at {:.0f} mm, highest "{}" at '
                  '{:.0f} mm'.format(
                      levels[0].Name, ft_to_mm(level_z(levels[0])),
                      levels[-1].Name, ft_to_mm(level_z(levels[-1]))))

        picked = doc.GetElement(ref.ElementId)
        transform = DB.Transform.Identity
        if isinstance(picked, DB.RevitLinkInstance):
            link_doc = picked.GetLinkDocument()
            if link_doc is None:
                report('That link is not loaded.')
                continue
            wall = link_doc.GetElement(ref.LinkedElementId)
            transform = picked.GetTotalTransform()
        else:
            wall = picked

        if not isinstance(wall, DB.Wall):
            debug('the pick was not a wall')
            report('That is not a wall - try again.')
            continue

        debug('wall "{}" in {}'.format(
            wall_type_name(wall),
            'link "{}"'.format(picked.Name)
            if isinstance(picked, DB.RevitLinkInstance) else 'the host model'))
        debug('{} service(s) selected'.format(len(services)))
        for sv in services:
            try:
                debug('   {} id {}{}'.format(
                    describe_element(sv.element), eid_value(sv.element.Id),
                    ' (linked)' if sv.linked else ''))
            except Exception:
                pass

        # --- place or resize ----------------------------------------------
        trans = DB.Transaction(
            doc, 'Resize BWIC penetration' if resizing
            else 'Place BWIC penetration')
        trans.Start()
        quieten(trans)
        try:
            plan_level = view_level(uidoc.ActiveView)
            options['level_source'] = 'active plan view' if plan_level \
                else 'nearest level below'
            if resizing:
                notes = []
                # the picked BWIC's own family settings decide how it is
                # sized -- not whichever family the tab has chosen
                swapped = use_wall_family(target, options)
                try:
                    # the picked BWIC's family's own clearance
                    instance, more = resize_one(
                        doc, target, services, wall, transform,
                        mm_to_ft(family_clearance_mm(FAMILY_NAME,
                                                     tab_clearance_mm)),
                        options, workset, plan_level)
                finally:
                    restore_wall_family(swapped)
            else:
                symbol, wall_note = choose_symbol(doc, wall, default_symbol,
                                                  symbol_cache)
                notes = [wall_note]
                instance, more = place_one(doc, services, wall, transform,
                                           clearance_ft, symbol, options,
                                           workset, plan_level)
            notes.extend(more)
            if instance is None:
                trans.RollBack()
                debug('SKIPPED: {}'.format('; '.join(notes)))
                report('Skipped: {}'.format('; '.join(notes)))
                guide('problem', title='BWIC not placed',
                      detail='; '.join(n for n in notes if n)[:160])
            else:
                trans.Commit()
                placed += 1
                debug('placed id {} : {}'.format(
                    eid_value(instance.Id), '; '.join(notes)))
                if linked_count:
                    notes.insert(1, '{} linked service{} included'.format(
                        linked_count, '' if linked_count == 1 else 's'))
                report('BWIC {} {} - {}'.format(
                    placed, 'resized' if resizing else 'placed',
                    '; '.join(notes)))
                guide('placed',
                      title='BWIC resized' if resizing else 'BWIC placed',
                      detail='{} this run. Carry on with the next one, or '
                             'press Esc to stop.'.format(placed))
        except Exception as err:
            # the traceback goes to the DEBUG LOG, not just the status box.
            # Without this a failure here left the log ending at the wall
            # pick, which says nothing about what actually went wrong.
            if trans.HasStarted():
                trans.RollBack()
            import traceback
            debug('EXCEPTION during {}\n{}'.format(
                'resize' if resizing else 'placement',
                traceback.format_exc()))
            report('{} failed: {}'.format(
                'Resize' if resizing else 'Placement', err))
            guide('problem', title='BWIC not placed', detail=str(err)[:160])
            logger.error(err)

        uidoc.Selection.SetElementIds(List[DB.ElementId]())

    guide('done')
    report('Finished - {} BWIC {} this run.'.format(
        placed, 'resized' if resizing else 'placed'))




# ===========================================================================
# SLAB PENETRATIONS
# ===========================================================================
# The slab tool is deliberately separate from the wall tool: it has its own
# family, its own parameter names, its own clearance and its own offsets, all
# held under "slab_" keys in the same settings file. Nothing here touches the
# wall settings.

SLAB_DEFAULTS = {
    'slab_family': '',
    'slab_type': '',
    'slab_family_kind': 'all',          # 'all', 'hosted' or 'regular'
    'slab_clearance': '50',
    'slab_length_param': 'BGL_Height',
    'slab_width_param': 'BGL_Width',
    'slab_datum': 'soffit',             # 'soffit', 'top' or 'level'
    'slab_base_extra': '50',            # added to the slab depth
    'slab_top_extra': '100',            # above the base
    'slab_base_level_param': '',        # blank -> the built in Base Level
    'slab_top_level_param': '',         # blank -> the built in Top Level
    'slab_base_offset_param': '',
    'slab_top_offset_param': '',
    'debug': 'no',
}

# built in parameters tried when the settings name nothing
BASE_LEVEL_BIPS = ['FAMILY_BASE_LEVEL_PARAM', 'FAMILY_LEVEL_PARAM',
                   'SCHEDULE_BASE_LEVEL_PARAM', 'INSTANCE_SCHEDULE_ONLY_LEVEL_PARAM']
TOP_LEVEL_BIPS = ['FAMILY_TOP_LEVEL_PARAM', 'SCHEDULE_TOP_LEVEL_PARAM']
BASE_OFFSET_BIPS = ['FAMILY_BASE_LEVEL_OFFSET_PARAM',
                    'INSTANCE_FREE_HOST_OFFSET_PARAM',
                    'SCHEDULE_BASE_LEVEL_OFFSET_PARAM']
TOP_OFFSET_BIPS = ['FAMILY_TOP_LEVEL_OFFSET_PARAM',
                   'SCHEDULE_TOP_LEVEL_OFFSET_PARAM']


def slab_defaults():
    return dict(SLAB_DEFAULTS)


# ---------------------------------------------------------------------------
# picking the slab
# ---------------------------------------------------------------------------
def is_slab(element):
    """Floors and structural foundation slabs."""
    try:
        if isinstance(element, DB.Floor):
            return True
        category = element.Category
        if category is None:
            return False
        for name in ('OST_Floors', 'OST_StructuralFoundation'):
            try:
                if eid_value(category.Id) == int(getattr(DB.BuiltInCategory, name)):
                    return True
            except (AttributeError, ValueError):
                continue
    except Exception:
        pass
    return False


class SlabPickFilter(ISelectionFilter):
    """Floors, in a link or in the host model."""

    def __init__(self, host_doc):
        self.host_doc = host_doc

    def AllowElement(self, element):
        return is_slab(element) or isinstance(element, DB.RevitLinkInstance)

    def AllowReference(self, reference, position):
        try:
            element = self.host_doc.GetElement(reference.ElementId)
            if isinstance(element, DB.RevitLinkInstance):
                link_doc = element.GetLinkDocument()
                if link_doc is None:
                    return False
                return is_slab(link_doc.GetElement(reference.LinkedElementId))
            return is_slab(element)
        except Exception:
            return False


def slab_depth(slab):
    """Overall thickness of a floor, in internal units."""
    for bip_name in ('FLOOR_ATTR_THICKNESS_PARAM', 'STRUCTURAL_FLOOR_CORE_THICKNESS'):
        try:
            bip = getattr(DB.BuiltInParameter, bip_name)
        except AttributeError:
            continue
        try:
            stype = slab.Document.GetElement(slab.GetTypeId())
            for holder in (stype, slab):
                if holder is None:
                    continue
                param = holder.get_Parameter(bip)
                if param is not None and param.StorageType == DB.StorageType.Double:
                    value = param.AsDouble()
                    if value > 1e-9:
                        return value
        except Exception:
            continue
    # compound structure is the reliable route where the parameter is absent
    try:
        stype = slab.Document.GetElement(slab.GetTypeId())
        structure = stype.GetCompoundStructure()
        if structure is not None:
            width = structure.GetWidth()
            if width > 1e-9:
                return width
    except Exception:
        pass
    # last resort: the bounding box height
    try:
        bb = slab.get_BoundingBox(None)
        if bb is not None:
            return abs(bb.Max.Z - bb.Min.Z)
    except Exception:
        pass
    return None


def slab_faces(slab, transform):
    """(top, bottom) elevation of the slab, in host coordinates."""
    try:
        bb = slab.get_BoundingBox(None)
        if bb is None:
            return None, None
        zs = []
        for point in (bb.Min, bb.Max):
            zs.append(transform.OfPoint(bb.Transform.OfPoint(point)).Z)
        return max(zs), min(zs)
    except Exception:
        return None, None


def slab_top_elevation(slab, transform):
    """Elevation of the top face of the slab, in host coordinates."""
    return slab_faces(slab, transform)[0]


def slab_level(doc, slab, transform, levels):
    """The host model level matching the slab's own level.

    A linked floor's level belongs to the link, so it cannot be assigned to a
    host element. The nearest host level to the slab's top face is used
    instead, which is the same level in any coordinated pair of models.
    """
    top = slab_top_elevation(slab, transform)
    if top is None:
        return None, None
    return level_below(levels, top + 1e-6), top


# ---------------------------------------------------------------------------
# families available to the slab tool
# ---------------------------------------------------------------------------
def family_kind(symbol):
    """('hosted'|'regular', a readable label) for a family symbol.

    Revit calls a wall/floor/ceiling hosted family OneLevelBasedHosted. A
    family that is simply placed at a point on a level -- which is what most
    penetration families are, including ones that cut the slab through "Cut
    with Voids When Loaded" -- is OneLevelBased, and is NOT hosted. Filtering
    on hosting alone therefore hides exactly the families this tool wants.
    """
    placement = ''
    try:
        placement = str(symbol.Family.FamilyPlacementType)
    except Exception:
        pass

    hosting = ''
    try:
        param = symbol.Family.get_Parameter(
            DB.BuiltInParameter.FAMILY_HOSTING_BEHAVIOR)
        if param is not None:
            hosting = {0: '', 1: 'wall', 2: 'floor', 3: 'ceiling',
                       4: 'roof', 5: 'face'}.get(param.AsInteger(), '')
    except Exception:
        pass

    if 'Hosted' in placement or hosting:
        label = '{} hosted'.format(hosting or 'host').strip()
        return 'hosted', label
    if 'WorkPlane' in placement:
        return 'regular', 'work plane based'
    if 'TwoLevels' in placement:
        return 'regular', 'two levels'
    if 'CurveBased' in placement or 'Curve' in placement:
        return 'regular', 'line based'
    return 'regular', 'non-hosted'


def is_floor_based(symbol):
    """Kept for compatibility -- true only for a genuinely hosted family."""
    return family_kind(symbol)[0] == 'hosted'


def generic_model_families(doc, kind_filter=None):
    """Generic model families, with the placement kind of each.

    kind_filter is None for everything, or 'hosted' / 'regular'. Returns
    [(family name, [type names], kind, label)] sorted by name.
    """
    found = {}
    try:
        bic = DB.BuiltInCategory.OST_GenericModel
        collector = DB.FilteredElementCollector(doc) \
            .OfClass(DB.FamilySymbol).OfCategory(bic)
    except Exception:
        collector = DB.FilteredElementCollector(doc).OfClass(DB.FamilySymbol)

    for symbol in collector:
        try:
            family = symbol.Family
            if family is None:
                continue
            kind, label = family_kind(symbol)
            if kind_filter and kind != kind_filter:
                continue
            entry = found.setdefault(family.Name, [[], kind, label])
            entry[0].append(DB.Element.Name.GetValue(symbol))
        except Exception:
            continue

    debug('generic model families found: {} (filter {})'.format(
        len(found), kind_filter or 'all'))
    for name in sorted(found.keys()):
        debug('   {} [{}] {} type(s)'.format(
            name, found[name][2], len(found[name][0])))

    return [(name, sorted(found[name][0]), found[name][1], found[name][2])
            for name in sorted(found.keys(), key=lambda n: n.lower())]


def family_shapes(doc):
    """{family name: RECT or CIRC} for the generic model families.

    Read from each family's length parameters -- a Diameter or Radius makes it
    round. One placed instance per family is read for its instance
    parameters; the types give the rest.
    """
    lengths = {}
    placed = set()

    def harvest(name, element):
        try:
            for param in element.Parameters:
                try:
                    if param.StorageType == DB.StorageType.Double:
                        lengths.setdefault(name, set()).add(
                            param.Definition.Name)
                except Exception:
                    continue
        except Exception:
            pass

    bic = DB.BuiltInCategory.OST_GenericModel
    try:
        for instance in DB.FilteredElementCollector(doc) \
                .OfClass(DB.FamilyInstance).OfCategory(bic) \
                .WhereElementIsNotElementType():
            try:
                name = instance.Symbol.Family.Name
            except Exception:
                continue
            if name in placed:
                continue
            placed.add(name)
            harvest(name, instance)
    except Exception:
        logger.debug('could not read the placed generic models')
    try:
        for symbol in DB.FilteredElementCollector(doc) \
                .OfClass(DB.FamilySymbol).OfCategory(bic):
            try:
                name = symbol.Family.Name
            except Exception:
                continue
            lengths.setdefault(name, set())
            harvest(name, symbol)
    except Exception:
        logger.debug('could not read the generic model types')

    shapes = {}
    for name, names in lengths.items():
        shapes[name] = families.family_shape(names, name, name in placed)
    debug('family shapes: {}'.format(', '.join(
        '{} {}'.format(n, 'round' if s == families.CIRC else 'rect')
        for n, s in sorted(shapes.items()))))
    return shapes


def family_parameter_names(doc, family_name, lengths_only=True):
    """Writable length parameters a family carries.

    Instance parameters only exist on a placed instance, so an existing one is
    used when the model has any. Where the family has never been placed the
    list falls back to the type parameters, which is why the settings window
    keeps whatever name is already saved even if it cannot see it.
    """
    names = set()

    def harvest(element, want_length_only=None):
        if want_length_only is None:
            want_length_only = lengths_only
        if element is None:
            return
        try:
            for param in element.Parameters:
                try:
                    if param.IsReadOnly:
                        continue
                    if want_length_only and \
                            param.StorageType != DB.StorageType.Double:
                        continue
                    names.add(param.Definition.Name)
                except Exception:
                    continue
        except Exception:
            pass

    for instance in DB.FilteredElementCollector(doc) \
            .OfClass(DB.FamilyInstance).WhereElementIsNotElementType():
        try:
            if instance.Symbol is not None \
                    and instance.Symbol.Family.Name == family_name:
                harvest(instance)
                break
        except Exception:
            continue

    for symbol in DB.FilteredElementCollector(doc).OfClass(DB.FamilySymbol):
        try:
            if symbol.Family is not None \
                    and symbol.Family.Name == family_name:
                harvest(symbol)
                break
        except Exception:
            continue

    return sorted(names, key=lambda n: n.lower())


def family_is_placed(doc, family_name):
    """True once the family has an instance in the model.

    Revit only shows a family's instance parameters on an instance, so a
    family that has never been placed lists its type parameters alone.
    """
    for instance in DB.FilteredElementCollector(doc) \
            .OfClass(DB.FamilyInstance).WhereElementIsNotElementType():
        try:
            if instance.Symbol is not None \
                    and instance.Symbol.Family.Name == family_name:
                return True
        except Exception:
            continue
    return False


def family_preview(doc, family_name, type_name=None, pixels=192):
    """The family type's own preview image, as a System.Drawing.Bitmap.

    None when the family is not loaded or saved no preview -- a family saved
    without one hands back a blank image, which is treated as none so the
    card can say so instead of showing an empty white square.
    """
    symbol = find_slab_symbol(doc, family_name, type_name)
    if symbol is None:
        return None
    try:
        import clr
        clr.AddReference('System.Drawing')
        from System.Drawing import Size
        bitmap = symbol.GetPreviewImage(Size(pixels, pixels))
    except Exception as err:
        debug('no preview for "{}": {}'.format(family_name, err))
        return None
    if bitmap is None:
        return None
    try:
        first = bitmap.GetPixel(0, 0)
        step = max(1, pixels // 12)
        for x in range(0, bitmap.Width, step):
            for y in range(0, bitmap.Height, step):
                if bitmap.GetPixel(x, y) != first:
                    return bitmap
        bitmap.Dispose()
        return None
    except Exception:
        return bitmap


def find_slab_symbol(doc, family_name, type_name):
    """The chosen slab family type, or the family's first type."""
    if not family_name:
        return None
    fallback = None
    for symbol in DB.FilteredElementCollector(doc).OfClass(DB.FamilySymbol):
        try:
            if symbol.Family is None or symbol.Family.Name != family_name:
                continue
            if fallback is None:
                fallback = symbol
            if type_name and DB.Element.Name.GetValue(symbol) == type_name:
                return symbol
        except Exception:
            continue
    return fallback


# ---------------------------------------------------------------------------
# writing the level and offset parameters
# ---------------------------------------------------------------------------
def list_parameters(element, label):
    """Write every parameter on an element to the debug log.

    A missing parameter name is the commonest cause of a placement that looks
    like it did nothing, and guessing at the spelling from the outside is
    hopeless -- so the real list goes in the log.
    """
    if not DEBUG:
        return
    debug('parameters on {}:'.format(label))
    for holder, kind in ((element, 'instance'),
                         (element.Document.GetElement(element.GetTypeId()),
                          'type')):
        if holder is None:
            continue
        names = []
        try:
            for param in holder.Parameters:
                try:
                    names.append('{}{}'.format(
                        param.Definition.Name,
                        '' if not param.IsReadOnly else ' (read only)'))
                except Exception:
                    continue
        except Exception:
            continue
        for name in sorted(names):
            debug('   [{}] {}'.format(kind, name))


def set_by_name_or_bip(element, name, bip_names, value, is_level=False):
    """Set a parameter by configured name first, then by built in."""
    holders = []
    if name:
        param = element.LookupParameter(name)
        if param is not None:
            holders.append(param)
    for bip_name in bip_names:
        try:
            bip = getattr(DB.BuiltInParameter, bip_name)
        except AttributeError:
            continue
        try:
            param = element.get_Parameter(bip)
            if param is not None:
                holders.append(param)
        except Exception:
            continue

    for param in holders:
        try:
            if param.IsReadOnly:
                continue
            if is_level:
                if param.StorageType != DB.StorageType.ElementId:
                    continue
                param.Set(value.Id)
            else:
                if param.StorageType != DB.StorageType.Double:
                    continue
                param.Set(value)
            return True
        except Exception:
            continue
    return False


# a vertical penetration is drawn in plan, so its two plan dimensions are not
# always called Length and Width -- BGL_Height is the second plan dimension on
# the vertical family. The configured name is tried first, then these.
SIZE_FALLBACKS = ['BGL_Length', 'BGL_Height', 'BGL_Width', 'BGL_Depth',
                  'Length', 'Width', 'Height', 'Depth']


def resolve_size_param(instance, symbol, wanted, taken):
    """The parameter that actually holds a size, and where it lives.

    Returns (name, holder) or (None, None). Falls back to the other BGL size
    names rather than silently writing nothing, because a family whose plan
    dimensions are called Width and Height is not a misconfiguration -- it is
    just a different family.
    """
    if families.decode_split(wanted) is not None:
        for holder in (instance, symbol):
            if holder is not None and wanted not in taken \
                    and has_length_param(holder, wanted):
                return wanted, holder
        # a split family has no BGL names to fall back on
        return None, None
    candidates = [wanted] + [n for n in SIZE_FALLBACKS if n != wanted]
    for name in candidates:
        if not name or name in taken:
            continue
        for holder in (instance, symbol):
            if holder is None:
                continue
            try:
                param = holder.LookupParameter(name)
            except Exception:
                continue
            if param is None or param.IsReadOnly:
                continue
            if param.StorageType != DB.StorageType.Double:
                continue
            return name, holder
    return None, None


def compute_slab_bwic(doc, services, slab, transform, clearance_ft,
                      base_extra_ft, top_extra_ft, levels, datum='soffit',
                      pick_z=None, rule='two_level', round_up_mm=None,
                      height_extra_ft=0.0, top_height_extra_ft=0.0,
                      view_level_hint=None, override_plan=None):
    """Size and position for a slab penetration. No model changes."""
    corners = []
    for service in services:
        corners.extend(service_points(service))
    if not corners:
        return None, 'the selected elements have no geometry to measure'

    depth = slab_depth(slab)
    if depth is None:
        return None, 'could not read a thickness from that floor'
    debug('floor depth {:.1f} mm'.format(ft_to_mm(depth)))

    # the opening is set out in plan: X across, Y along
    x_min, x_max = min(p.X for p in corners), max(p.X for p in corners)
    y_min, y_max = min(p.Y for p in corners), max(p.Y for p in corners)

    angle = 0.0
    if override_plan is not None:
        width = length = override_plan
        centre_x = (x_min + x_max) / 2.0
        centre_y = (y_min + y_max) / 2.0
    else:
        # the services decide which way the opening faces, so it hugs a tray
        # running at an angle instead of boxing it in squarely
        angle, span_u, span_v, centre_x, centre_y = min_area_rect(
            [(p.X, p.Y) for p in corners])
        width = round_up_ft(span_u + 2 * clearance_ft, round_up_mm)
        length = round_up_ft(span_v + 2 * clearance_ft, round_up_mm)
        debug('plan fit: {:.0f} x {:.0f} mm turned {:.1f} deg -> opening '
              '{:.0f} x {:.0f} mm'.format(
                  ft_to_mm(span_u), ft_to_mm(span_v),
                  math.degrees(angle) % 180.0,
                  ft_to_mm(width), ft_to_mm(length)))
        square = round_up_ft((x_max - x_min) + 2 * clearance_ft, round_up_mm)
        square_v = round_up_ft((y_max - y_min) + 2 * clearance_ft, round_up_mm)
        if square * square_v > width * length * 1.05:
            debug('   (square to the model it would have been {:.0f} x '
                  '{:.0f} mm)'.format(ft_to_mm(square), ft_to_mm(square_v)))



    top_z, bottom_z = slab_faces(slab, transform)

    # The click point is the honest datum. Reference.GlobalPoint is in HOST
    # coordinates whatever the link's placement, while a linked element's
    # bounding box has to be pushed through the link transform by hand -- and
    # where that transform does not carry the link's full position, the box
    # comes back short by exactly the link offset. Trust the click.
    if pick_z is not None:
        if top_z is not None and abs(top_z - pick_z) > mm_to_ft(1.0):
            debug('NOTE the floor bounding box says {:.1f} mm but the click '
                  'is at {:.1f} mm - a difference of {:.0f} mm. The click '
                  'wins.'.format(ft_to_mm(top_z), ft_to_mm(pick_z),
                                 ft_to_mm(abs(top_z - pick_z))))
        top_z = pick_z
        bottom_z = pick_z - depth

    if top_z is None:
        return None, 'could not work out where that floor sits'

    # the services are in the host model, so their elevation is beyond doubt
    service_z = [p.Z for p in corners]
    debug('services span Z {:.1f} to {:.1f} mm'.format(
        ft_to_mm(min(service_z)), ft_to_mm(max(service_z))))
    if max(service_z) < bottom_z - mm_to_ft(2000) \
            or min(service_z) > top_z + mm_to_ft(2000):
        debug('WARNING the floor at {:.0f} mm is nowhere near the services - '
              'the opening would be placed away from them'.format(
                  ft_to_mm(top_z)))

    # The NEAREST level, above or below. A slab opening belongs to the slab it
    # is in, and the level that slab sits closest to is the one that reads
    # correctly on a schedule -- taking the level below hands the opening to
    # the storey underneath whenever the slab sits just under a level, and
    # falling back to the lowest level in the project is how these ended up in
    # the basement.
    level = nearest_level(levels, top_z)
    if level is None:
        return None, 'could not work out a level for that floor'
    debug('nearest level to {:.1f} mm is "{}" at {:.1f} mm ({:.0f} mm away)'
          .format(ft_to_mm(top_z), level.Name, ft_to_mm(level_z(level)),
                  ft_to_mm(abs(level_z(level) - top_z))))

    debug('floor top {:.1f} mm, soffit {:.1f} mm'.format(
        ft_to_mm(top_z), ft_to_mm(bottom_z)))
    debug('nearest level at or below: "{}" at {:.1f} mm'.format(
        level.Name, ft_to_mm(level_z(level))))
    debug('plan extent {:.0f} x {:.0f} mm -> L {:.0f} W {:.0f}'.format(
        ft_to_mm(y_max - y_min), ft_to_mm(x_max - x_min),
        ft_to_mm(length), ft_to_mm(width)))

    gap = ft_to_mm(abs(level_z(level) - top_z))
    if gap > 5000:
        debug('NOTE the nearest level "{}" is {:.0f} mm from the floor. The '
              'opening is set out from the floor itself, so it still lands '
              'correctly.'.format(level.Name, gap))

    # ---- the position is taken from the SLAB, never from the level -------
    # Deriving it from the level put openings tens of metres away wherever the
    # host and the link do not share a datum. The offsets written are worked
    # back from the world position, so the numbers in the properties palette
    # stay honest whatever the level is.
    if datum == 'top':
        base_world = top_z + base_extra_ft
    elif datum == 'level':
        base_world = level_z(level) + depth + base_extra_ft
    else:                                   # 'soffit', the default
        base_world = bottom_z - base_extra_ft

    top_world = base_world + top_extra_ft

    base_offset = base_world - level_z(level)
    top_offset = top_world - level_z(level)

    debug('datum "{}" -> base {:.1f} mm, top {:.1f} mm (world)'.format(
        datum, ft_to_mm(base_world), ft_to_mm(top_world)))
    debug('offsets from "{}": base {:.1f} mm, top {:.1f} mm'.format(
        level.Name, ft_to_mm(base_offset), ft_to_mm(top_offset)))

    # a single level family sits on the nearest level and carries its own
    # height, so it needs the level closest to the floor rather than the one
    # below it, and a height that matches the floor thickness
    if rule == 'single_level':
        # the nearest level, up or down, same as the two level rule
        level = nearest_level(levels, top_z) or level
        opening_height = depth + height_extra_ft
        base_world = bottom_z - (base_extra_ft if datum == 'soffit' else 0.0)
        top_world = base_world + opening_height
        top_height = (top_z + top_height_extra_ft) - level_z(level)
        debug('single level rule: level "{}" at {:.1f} mm, height {:.1f} mm '
              '(floor {:.1f} + {:.1f})'.format(
                  level.Name, ft_to_mm(level_z(level)),
                  ft_to_mm(opening_height), ft_to_mm(depth),
                  ft_to_mm(height_extra_ft)))
    else:
        opening_height = top_world - base_world
        top_height = top_world - level_z(level)

    return {
        'rule': rule,
        'height': opening_height,
        'top_height': top_height,
        'level_offset': base_world - level_z(level),
        'length': length,
        'width': width,
        'point': DB.XYZ(centre_x, centre_y, base_world),
        'angle': angle,
        'level': level,
        'levels': levels,
        'preferred_level': level,
        'depth': depth,
        'base_offset': base_offset,
        'top_offset': top_offset,
        'base_world': base_world,
        'top_world': top_world,
        'target_z': base_world,
        'slab_top': top_z,
        'slab_bottom': bottom_z,
    }, None


def swap_plan_sizes(doc, instance, place_symbol, geom, settings, notes):
    """Make the opening's footprint match the one that was asked for.

    Which of the family's two plan parameters runs along model X depends on
    how the family was drawn, so writing width to one and depth to the other
    is a coin toss. The footprint is measured and the pair swapped if it came
    out the wrong way round.
    """
    bb = instance.get_BoundingBox(None)
    if bb is None:
        return

    got_x = bb.Max.X - bb.Min.X
    got_y = bb.Max.Y - bb.Min.Y
    want_x, want_y = geom['width'], geom['length']
    tol = mm_to_ft(1.0)

    if abs(got_x - want_x) <= tol and abs(got_y - want_y) <= tol:
        return
    # only swap when swapping is actually the answer
    if not (abs(got_x - want_y) <= tol and abs(got_y - want_x) <= tol):
        debug('footprint is {:.0f} x {:.0f} mm, asked for {:.0f} x {:.0f} - '
              'the family may not size from these parameters'.format(
                  ft_to_mm(got_x), ft_to_mm(got_y),
                  ft_to_mm(want_x), ft_to_mm(want_y)))
        return

    length_param = settings.get('slab_length_param') or 'BGL_Height'
    width_param = settings.get('slab_width_param') or 'BGL_Width'
    taken = []
    for wanted, value in ((width_param, geom['length']),
                          (length_param, geom['width'])):
        name, holder = resolve_size_param(instance, place_symbol, wanted, taken)
        if name is None:
            return
        taken.append(name)
        set_length_param(holder, name, value)
    doc.Regenerate()
    notes.append('plan sizes swapped to match the family')
    debug('footprint was {:.0f} x {:.0f} mm, swapped to give {:.0f} x '
          '{:.0f}'.format(ft_to_mm(got_x), ft_to_mm(got_y),
                          ft_to_mm(want_x), ft_to_mm(want_y)))


def turn_to_angle(doc, instance, angle, notes):
    """Turn the opening to match the services it is set out around."""
    if abs(angle) < 1e-6:
        return
    try:
        loc = instance.Location
        origin = loc.Point if isinstance(loc, DB.LocationPoint) else None
        if origin is None:
            bb = instance.get_BoundingBox(None)
            if bb is None:
                return
            origin = DB.XYZ((bb.Min.X + bb.Max.X) / 2.0,
                            (bb.Min.Y + bb.Max.Y) / 2.0, bb.Min.Z)
        axis = DB.Line.CreateBound(origin, origin + DB.XYZ.BasisZ)
        DB.ElementTransformUtils.RotateElement(doc, instance.Id, axis, angle)
        doc.Regenerate()
        notes.append('turned {:.1f} deg to suit'.format(
            math.degrees(angle) % 180.0))
    except Exception as err:
        notes.append('could not turn it: {}'.format(err))


def apply_slab_to_instance(doc, instance, place_symbol, services, geom,
                           settings, options, workset, notes):
    """Size, level, turn and centre a slab opening.

    Shared by placing a new opening and resizing an existing one, so both
    follow exactly the same rules -- a resize that drifted from placement
    would be worse than no resize at all.
    """
    length_param = settings.get('slab_length_param') or 'BGL_Height'
    width_param = settings.get('slab_width_param') or 'BGL_Width'
    level = geom['level']
    point = geom['point']

    # a circular opening carries one diameter; a rectangular one carries the
    # two plan dimensions
    if geom.get('circular'):
        dia_param = settings.get('slab_circular_param') or 'BGL_Diameter'
        name, holder = resolve_size_param(instance, place_symbol,
                                          dia_param, [])
        if name is None:
            notes.append('SIZE NOT SET - "{}" is not on the family'.format(
                dia_param))
            list_parameters(instance, 'the placed opening')
        else:
            radius = settings.get('slab_circular_radius') == 'yes'
            value = families.round_value(geom['width'], radius)
            ok, msg = set_length_param(holder, name, value)
            if ok:
                notes.append('{} = {:.0f} mm'.format(name, ft_to_mm(value)))
                debug('set {} = {:.1f} mm ({})'.format(
                    name, ft_to_mm(value),
                    'radius' if radius else 'diameter'))
            else:
                notes.append(msg)
    else:
        missing = []
        taken = []
        for wanted, pvalue, slot in ((length_param, geom['length'], 'length'),
                                     (width_param, geom['width'], 'width')):
            name, holder = resolve_size_param(instance, place_symbol,
                                              wanted, taken)
            if name is None:
                missing.append(wanted)
                continue
            taken.append(name)
            ok, msg = set_length_param(holder, name, pvalue)
            if not ok:
                notes.append(msg)
                continue
            debug('set {} = {:.1f} mm ({} slot)'.format(
                name, ft_to_mm(pvalue), slot))
            if name != wanted:
                notes.append('used "{}" for the {} - "{}" is not on this '
                             'family'.format(name, slot, wanted))
        if missing:
            notes.append('SIZE NOT SET - no parameter found for {}'.format(
                ' and '.join(missing)))
            list_parameters(instance, 'the placed opening')
    doc.Regenerate()

    # ---- single level, non face based --------------------------------
    if geom.get('rule') == 'single_level':
        height_param = settings.get('slab_height_param')
        top_param = settings.get('slab_top_height_param')
        offset_param = settings.get('slab_level_offset_param')

        if not set_by_name_or_bip(instance, None, BASE_LEVEL_BIPS, level,
                                  is_level=True):
            debug('level parameter not writable; the instance keeps the '
                  'level it was created on')

        if height_param:
            ok, msg = set_length_param(instance, height_param, geom['height'])
            if ok:
                notes.append('{} = {:.0f} mm (floor {:.0f})'.format(
                    height_param, ft_to_mm(geom['height']),
                    ft_to_mm(geom['depth'])))
            else:
                notes.append(msg)
                list_parameters(instance, 'the placed opening')
        else:
            notes.append('no vertical height parameter set in Settings')

        if top_param:
            ok, msg = set_length_param(instance, top_param,
                                       geom['top_height'])
            notes.append('{} = {:.0f} mm'.format(
                top_param, ft_to_mm(geom['top_height'])) if ok else msg)

        if offset_param:
            ok, msg = set_length_param(instance, offset_param,
                                       geom['level_offset'])
            if not ok:
                debug(msg)
        doc.Regenerate()

        # a non hosted family can simply be moved, which beats guessing which
        # parameter drives its elevation
        wanted = geom.get('base_world')
        for attempt in range(2):
            bb = instance.get_BoundingBox(None)
            if bb is None or wanted is None:
                break
            drift = wanted - bb.Min.Z
            debug('geometry base at {:.1f} mm, wanted {:.1f} mm, drift '
                  '{:.1f} mm'.format(ft_to_mm(bb.Min.Z), ft_to_mm(wanted),
                                     ft_to_mm(drift)))
            if abs(drift) <= mm_to_ft(1.0):
                break
            DB.ElementTransformUtils.MoveElement(
                doc, instance.Id, DB.XYZ(0, 0, drift))
            doc.Regenerate()
            notes.append('moved {:.0f} mm to sit on the floor'.format(
                ft_to_mm(drift)))

    # ---- two levels based --------------------------------------------
    elif set_by_name_or_bip(instance, settings.get('slab_base_level_param'),
                            BASE_LEVEL_BIPS, level, is_level=True):
        notes.append('base level {}'.format(level.Name))
    elif geom.get('rule') != 'single_level':
        notes.append('could not set the base level')

    if geom.get('rule') != 'single_level' and \
            not set_by_name_or_bip(instance,
                                   settings.get('slab_top_level_param'),
                                   TOP_LEVEL_BIPS, level, is_level=True):
        logger.debug('no top level parameter on this family')

    top_span = geom['top_offset'] - geom['base_offset']

    if geom.get('rule') == 'single_level':
        pass
    elif set_by_name_or_bip(instance, settings.get('slab_base_offset_param'),
                            BASE_OFFSET_BIPS, geom['base_offset']):
        notes.append('base offset {:.0f} mm (slab {:.0f} + {:.0f})'.format(
            ft_to_mm(geom['base_offset']), ft_to_mm(geom['depth']),
            ft_to_mm(geom['base_offset'] - geom['depth'])))
    else:
        notes.append('could not set the base offset')

    if geom.get('rule') != 'single_level' and \
            set_by_name_or_bip(instance,
                               settings.get('slab_top_offset_param'),
                               TOP_OFFSET_BIPS, geom['top_offset']):
        notes.append('top offset {:.0f} mm'.format(ft_to_mm(geom['top_offset'])))
    doc.Regenerate()

    # Measure, do not reason. On a two levels based family the creation point's
    # Z is ignored and the geometry is driven by Base Offset -- and how that
    # offset relates to the family's own origin varies by family. So read where
    # the solid actually landed and correct the offset by the difference.
    wanted_base = geom.get('base_world')
    if wanted_base is not None and geom.get('rule') != 'single_level':
        for attempt in range(2):
            bb = instance.get_BoundingBox(None)
            if bb is None:
                break
            drift = wanted_base - bb.Min.Z
            debug('geometry base at {:.1f} mm, wanted {:.1f} mm, drift '
                  '{:.1f} mm'.format(ft_to_mm(bb.Min.Z),
                                     ft_to_mm(wanted_base), ft_to_mm(drift)))
            if abs(drift) <= mm_to_ft(1.0):
                break
            corrected = geom['base_offset'] + drift
            if not set_by_name_or_bip(instance,
                                      settings.get('slab_base_offset_param'),
                                      BASE_OFFSET_BIPS, corrected):
                notes.append('could not correct the base offset')
                break
            geom['base_offset'] = corrected
            set_by_name_or_bip(instance, settings.get('slab_top_offset_param'),
                               TOP_OFFSET_BIPS, corrected + top_span)
            doc.Regenerate()
            notes.append('base offset corrected by {:.0f} mm'.format(
                ft_to_mm(drift)))

    # ---- centre the opening on the services, in plan ---------------------
    # Moving the instance's ORIGIN to the target assumes the origin sits at
    # the middle of the family's own geometry. It often does not -- this is
    # the same trap as the 380mm vertical offset -- and the opening then ends
    # up beside the services instead of around them. So the GEOMETRY is
    # measured and the box centred on the services.
    if not geom.get('circular'):
        # square to the model first, so the footprint can be checked against
        # the sizes that were asked for, and only then turned
        swap_plan_sizes(doc, instance, place_symbol, geom, settings, notes)
        turn_to_angle(doc, instance, geom.get('angle') or 0.0, notes)

    for attempt in range(3):
        bb = instance.get_BoundingBox(None)
        if bb is None:
            break
        centre_x = (bb.Min.X + bb.Max.X) / 2.0
        centre_y = (bb.Min.Y + bb.Max.Y) / 2.0
        dx = point.X - centre_x
        dy = point.Y - centre_y
        if max(abs(dx), abs(dy)) <= mm_to_ft(0.5):
            break
        debug('centring: geometry centre {:.1f}, {:.1f} -> wanted {:.1f}, '
              '{:.1f} (moving {:.1f}, {:.1f} mm)'.format(
                  ft_to_mm(centre_x), ft_to_mm(centre_y),
                  ft_to_mm(point.X), ft_to_mm(point.Y),
                  ft_to_mm(dx), ft_to_mm(dy)))
        DB.ElementTransformUtils.MoveElement(doc, instance.Id,
                                             DB.XYZ(dx, dy, 0))
        doc.Regenerate()
    doc.Regenerate()

    # the family's own workset, else the one chosen in Settings
    place_on_workset(doc, instance, options, workset, notes)

    # level code, the same rule the wall tool uses
    level_param = settings.get('slab_level_code_param') \
        or options.get('level_param') or LEVEL_PARAM_NAME
    if level_param:
        code = level_code(level, geom['levels'])
        ok, msg = set_level_code(instance, level_param, code)
        notes.append('{} = {} ({})'.format(level_param, code, level.Name)
                     if ok else msg)
        if not ok:
            list_parameters(instance, 'the placed opening')

    if options.get('log_comments'):
        try:
            comment = build_comment(services)
            if comment:
                cparam = instance.get_Parameter(
                    DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
                if cparam is not None and not cparam.IsReadOnly:
                    cparam.Set(comment)
                    notes.append('comments: {}'.format(comment))
        except Exception as err:
            notes.append('comments log failed: {}'.format(err))

    if options.get('pin'):
        pinned = len([sv for sv in services
                      if not sv.linked and pin_element(sv.element)])
        pin_element(instance)
        notes.append('pinned {} service{} and the opening'.format(
            pinned, '' if pinned == 1 else 's'))

    # prove the position rather than assume it -- a void API call is not
    # evidence, and this is exactly where the 80 metre error hid
    try:
        loc = instance.Location
        if isinstance(loc, DB.LocationPoint):
            actual = loc.Point
            debug('instance origin now {:.1f}, {:.1f}, {:.1f} mm'.format(
                ft_to_mm(actual.X), ft_to_mm(actual.Y), ft_to_mm(actual.Z)))
        # Check the GEOMETRY against where it was wanted, not the origin.
        # A family's origin sits wherever its author put it -- 380mm above the
        # base on this one -- so comparing the origin reported a drift on every
        # correctly placed opening.
        bb = instance.get_BoundingBox(None)
        if bb is not None:
            debug('instance extent Z {:.1f} to {:.1f} mm (slab {:.1f} to '
                  '{:.1f})'.format(
                      ft_to_mm(bb.Min.Z), ft_to_mm(bb.Max.Z),
                      ft_to_mm(geom.get('slab_bottom') or 0),
                      ft_to_mm(geom.get('slab_top') or 0)))
            wanted = geom.get('base_world')
            if wanted is not None:
                drift = abs(bb.Min.Z - wanted)
                if drift > mm_to_ft(1.0):
                    notes.append('WARNING it settled {:.0f} mm off'.format(
                        ft_to_mm(drift)))
            # the opening has to actually pass through the slab
            top, bottom = geom.get('slab_top'), geom.get('slab_bottom')
            if top is not None and bottom is not None:
                if bb.Max.Z < bottom - 1e-6 or bb.Min.Z > top + 1e-6:
                    notes.append('WARNING it does not reach the floor')
    except Exception:
        pass

    # ---- does it actually enclose the services? --------------------------
    # Checked in the OPENING'S own frame, not against an axis aligned box: a
    # turned opening has a bounding box larger than itself, so comparing boxes
    # would pass services that actually fall outside it. A placement that
    # reports success while sitting beside the services is worse than one that
    # fails outright.
    try:
        corners = []
        for service in services:
            corners.extend(service_points(service))
        bb = instance.get_BoundingBox(None)
        if corners and bb is not None:
            mid_x = (bb.Min.X + bb.Max.X) / 2.0
            mid_y = (bb.Min.Y + bb.Max.Y) / 2.0
            angle = geom.get('angle') or 0.0
            cos_a, sin_a = math.cos(-angle), math.sin(-angle)
            round_hole = bool(geom.get('circular'))
            half_u = geom['width'] / 2.0
            half_v = half_u if round_hole else geom['length'] / 2.0

            worst = None
            for corner in corners:
                dx = corner.X - mid_x
                dy = corner.Y - mid_y
                u = dx * cos_a - dy * sin_a
                v = dx * sin_a + dy * cos_a
                if round_hole:
                    over = math.sqrt(u * u + v * v) - half_u
                else:
                    over = max(abs(u) - half_u, abs(v) - half_v)
                worst = over if worst is None else max(worst, over)

            if worst is not None and worst > mm_to_ft(0.5):
                notes.append('WARNING the opening misses the services by up '
                             'to {:.0f} mm'.format(ft_to_mm(worst)))
                debug('enclosure FAILED by {:.1f} mm; opening {:.0f} x {:.0f} '
                      'mm at {:.1f} deg, centre {:.0f}, {:.0f}'.format(
                          ft_to_mm(worst), ft_to_mm(geom['width']),
                          ft_to_mm(geom['length']),
                          math.degrees(angle) % 180.0,
                          ft_to_mm(mid_x), ft_to_mm(mid_y)))
            elif worst is not None:
                debug('encloses the services with {:.0f} mm to spare'.format(
                    ft_to_mm(-worst)))
    except Exception:
        pass

    notes.append('L {:.0f} / W {:.0f} mm at {:.0f} mm'.format(
        ft_to_mm(geom['length']), ft_to_mm(geom['width']),
        ft_to_mm(geom.get('base_world') or 0)))
    return instance, notes


def family_name_of(symbol):
    """A symbol's family name, or '' when Revit will not give one."""
    try:
        return symbol.Family.Name
    except Exception:
        return ''


def slab_sized_symbol(doc, symbol, geom, settings, notes):
    """The type to place, duplicated and sized when the size lives on type."""
    if not symbol.IsActive:
        symbol.Activate()
        doc.Regenerate()

    length_param = settings.get('slab_length_param') or 'BGL_Height'
    width_param = settings.get('slab_width_param') or 'BGL_Width'

    type_sized = [n for n in (length_param, width_param)
                  if has_length_param(symbol, n)]
    if not (type_sized and DUPLICATE_TYPE_IF_TYPE_PARAMS):
        return symbol

    new_name = '{}_L{:.0f}_W{:.0f}'.format(
        DB.Element.Name.GetValue(symbol),
        round(ft_to_mm(geom['length'])), round(ft_to_mm(geom['width'])))
    existing = find_symbol_by_name(doc, symbol.Family, new_name)
    place_symbol = existing if existing is not None \
        else symbol.Duplicate(new_name)
    if not place_symbol.IsActive:
        place_symbol.Activate()
    doc.Regenerate()
    for pname, pvalue in ((length_param, geom['length']),
                          (width_param, geom['width'])):
        if has_length_param(place_symbol, pname):
            ok, msg = set_length_param(place_symbol, pname, pvalue)
            if not ok:
                notes.append(msg)
    doc.Regenerate()
    notes.append('sized on type "{}"'.format(new_name))
    return place_symbol


def resize_slab_one(doc, instance, services, slab, transform, symbol, geom,
                    settings, options, workset):
    """Re-fit an existing slab opening to a fresh selection of services.

    Everything after the type swap is the same code the placement runs, so a
    resized opening and a newly placed one cannot drift apart.
    """
    notes = []

    was_pinned = False
    try:
        was_pinned = instance.Pinned
        if was_pinned:
            instance.Pinned = False
            notes.append('unpinned to move it')
    except Exception:
        pass

    place_symbol = slab_sized_symbol(doc, symbol, geom, settings, notes)

    # the services may have changed shape since it was placed -- a tray added
    # to a group of pipes turns a round hole into a rectangular one
    if place_symbol.Id != instance.Symbol.Id:
        was = family_name_of(instance.Symbol)
        try:
            instance.Symbol = place_symbol
            doc.Regenerate()
            now = family_name_of(place_symbol)
            if was != now:
                notes.append('changed family from "{}" to "{}"'.format(
                    was, now))
        except Exception as err:
            notes.append('could not change the type, so the existing one was '
                         'kept: {}'.format(err))

    instance, more = apply_slab_to_instance(
        doc, instance, instance.Symbol, services, geom, settings, options,
        workset, notes)

    if was_pinned and not options.get('pin'):
        pin_element(instance)
        notes.append('re-pinned')
    return instance, more


def place_slab_one(doc, services, slab, transform, symbol, geom, settings,
                   options, workset):
    """Place and size one slab penetration. Returns (instance, notes)."""
    notes = []

    if not symbol.IsActive:
        symbol.Activate()
        doc.Regenerate()

    place_symbol = slab_sized_symbol(doc, symbol, geom, settings, notes)

    level = geom['level']
    point = geom['point']

    instance = None
    host_slab = slab if slab.Document.Equals(doc) else None

    # a floor based family can only be hosted on a floor in this model; a
    # linked floor cannot host anything, so it falls back to a free instance
    if settings.get('slab_family_kind', 'floor') == 'floor' and host_slab is not None:
        try:
            instance = doc.Create.NewFamilyInstance(
                point, place_symbol, host_slab, level,
                StructuralType.NonStructural)
        except Exception as err:
            logger.debug('hosted placement refused: {}'.format(err))

    if instance is None:
        try:
            instance = doc.Create.NewFamilyInstance(
                point, place_symbol, level, StructuralType.NonStructural)
        except Exception:
            instance = doc.Create.NewFamilyInstance(
                point, place_symbol, StructuralType.NonStructural)
        if settings.get('slab_family_kind', 'floor') == 'floor':
            if host_slab is None:
                notes.append('the floor is in a link, so the family is placed '
                             'unhosted at the right level')
            else:
                notes.append('could not host on the floor, placed unhosted')
    doc.Regenerate()

    return apply_slab_to_instance(doc, instance, place_symbol, services,
                                  geom, settings, options, workset, notes)


def run_slab_loop(uiapp, settings, options, report, mode='place'):
    """Place slab openings, or re-fit an existing one to a new selection.

    Resizing picks the opening first, then the services, then the floor, and
    runs the same geometry the placement does.
    """
    uidoc = uiapp.ActiveUIDocument
    if uidoc is None:
        report('No active Revit document.')
        return

    doc = uidoc.Document
    resizing = (mode == 'resize')
    start_debug(doc, 'SLAB RUN ({})'.format(mode), settings, options)

    method = settings.get('slab_method') or 'auto'

    rect_name = settings.get('slab_family')
    circ_name = settings.get('slab_circ_family') or rect_name
    rect_symbol = find_slab_symbol(doc, rect_name, settings.get('slab_type'))
    circ_symbol = find_slab_symbol(doc, circ_name,
                                   settings.get('slab_circ_type')
                                   or settings.get('slab_type'))

    # a family whose name says circular is circular whatever it was picked as
    if rect_symbol is not None and circ_symbol is None \
            and wants_circular(rect_name):
        circ_symbol, rect_symbol = rect_symbol, None

    if rect_symbol is None and circ_symbol is None:
        debug('neither family is loaded: rectangular "{}", circular "{}"'
              .format(rect_name, circ_name))
        debug('generic models present:')
        for name, types, kind, label in generic_model_families(doc):
            debug('   {} [{}]'.format(name, label))
        report('Choose a slab penetration family in Settings first.')
        return

    if rect_symbol is not None:
        debug('rectangular family "{}" type "{}"'.format(
            rect_name, DB.Element.Name.GetValue(rect_symbol)))
    if circ_symbol is not None:
        debug('circular family "{}" type "{}"'.format(
            circ_name, DB.Element.Name.GetValue(circ_symbol)))
    debug('method "{}"'.format(method))

    datum = settings.get('slab_datum') or 'soffit'
    rule = settings.get('slab_rule') or 'two_level'
    debug('rule "{}", datum mode "{}"'.format(rule, datum))

    try:
        # each family's own, from Family settings; 50 until set
        clearance_ft = mm_to_ft(families.DEFAULT_CLEARANCE_MM)
        base_extra_ft = mm_to_ft(float(settings.get('slab_base_extra') or 50))
        top_extra_ft = mm_to_ft(float(settings.get('slab_top_extra') or 100))
        round_up_mm = float(settings.get('slab_round_up') or ROUND_UP_MM)
        height_extra_ft = mm_to_ft(float(settings.get('slab_height_extra') or 0))
        top_height_extra_ft = mm_to_ft(
            float(settings.get('slab_top_height_extra') or 0))
        circ_gap_ft = mm_to_ft(families.DEFAULT_CLEARANCE_MM)
        circ_round_mm = float(settings.get('slab_circular_round') or 10)
        group_gap_ft = mm_to_ft(float(settings.get('slab_group_gap') or 100))
        circ_insulation = settings.get('slab_circular_insulation') != 'no'
        pipe_gap_ft = mm_to_ft(float(settings.get('slab_pipe_tray_gap') or 150))
        angle_tol = float(settings.get('slab_group_angle') or 15)
    except ValueError:
        report('The slab round up and height figures must be numbers, in mm.')
        return

    debug('round: OUTSIDE diameter{} + {:.0f} mm gap each side, rounded up '
          'to {:.0f} mm'.format(
              ' (insulation included)' if circ_insulation else '',
              ft_to_mm(circ_gap_ft), circ_round_mm))
    debug('rect: the services plus {:.0f} mm each side, rounded up to {:.0f} '
          'mm; trays and ducts within {:.0f} mm share one; a pipe within '
          '{:.0f} mm of one joins it'.format(
              ft_to_mm(clearance_ft), round_up_mm,
              ft_to_mm(group_gap_ft), ft_to_mm(pipe_gap_ft)))
    debug('     trays only share an opening when they point within {:.0f} '
          'deg of each other'.format(angle_tol))

    workset = None
    if options.get('workset_name'):
        workset = find_workset_by_name(doc, options['workset_name'])

    levels = sorted_levels(doc)
    if not levels:
        report('This project has no levels.')
        return
    debug('{} level(s), lowest "{}" at {:.0f} mm, highest "{}" at {:.0f} mm'
          .format(len(levels), levels[0].Name, ft_to_mm(level_z(levels[0])),
                  levels[-1].Name, ft_to_mm(level_z(levels[-1]))))

    include_linked = bool(options.get('include_linked'))
    service_filter = ServicePickFilter(doc, include_linked)
    slab_filter = SlabPickFilter(doc)
    accepted = resize_family_names('slab') \
        if resizing else [rect_name, circ_name]
    bwic_filter = BWICPickFilter(accepted)
    resize_values = None
    placed = 0
    flow = 'slab_resize' if resizing else 'slab_place'

    while True:
        # --- the opening to re-fit, when resizing -------------------------
        target = None
        if resizing:
            chosen = [doc.GetElement(eid)
                      for eid in uidoc.Selection.GetElementIds()]
            chosen = [el for el in chosen if is_bwic(el, accepted)]
            if len(chosen) == 1:
                target = chosen[0]
                debug('resizing the pre-selected opening id {}'.format(
                    eid_value(target.Id)))
            else:
                try:
                    guide('step', **step_dict(flow, 'opening'))
                    focus_revit()
                    ref = uidoc.Selection.PickObject(
                        ObjectType.Element, bwic_filter,
                        'Pick the slab opening to resize  '
                        '(Esc returns to the RevoBIM window)')
                    target = doc.GetElement(ref.ElementId)
                    debug('resizing opening id {}'.format(
                        eid_value(target.Id)))
                except OperationCanceledException:
                    break
                except Exception as err:
                    report('Opening pick failed: {}'.format(err))
                    break
            uidoc.Selection.SetElementIds(List[DB.ElementId]())

        # --- the services, host and linked in ONE selection ---------------
        services = []
        for eid in uidoc.Selection.GetElementIds():
            el = doc.GetElement(eid)
            try:
                if el is not None and el.get_BoundingBox(None) is not None:
                    services.append(Service(el))
            except Exception:
                continue

        if not services:
            try:
                guide('step', **step_dict(flow, 'services', include_linked))
                focus_revit()
                refs = uidoc.Selection.PickObjects(
                    ObjectType.Element, service_filter,
                    'Select the services{}, then press Return or Finish  '
                    '(Esc returns to the RevoBIM window)'.format(
                        ', links included' if include_linked else ''))
            except OperationCanceledException:
                break
            except Exception as err:
                report('Selection failed: {}'.format(err))
                break
            for ref in refs:
                service = resolve_picked(doc, ref)
                if service is not None:
                    services.append(service)

        if not services:
            break

        # --- the slab -----------------------------------------------------
        try:
            focus_revit()
            guide('step', **step_dict(flow, 'floor'))
            ref = uidoc.Selection.PickObject(
                ObjectType.LinkedElement, slab_filter,
                'Click the floor the services pass through  '
                '(Esc returns to the RevoBIM window)')
        except OperationCanceledException:
            uidoc.Selection.SetElementIds(List[DB.ElementId]())
            break
        except Exception as err:
            report('Floor pick failed: {}'.format(err))
            break

        # GlobalPoint is in host coordinates whatever the link placement
        pick_z = None
        try:
            if ref.GlobalPoint is not None:
                pick_z = ref.GlobalPoint.Z
                debug('click point Z {:.1f} mm (host coordinates)'.format(
                    ft_to_mm(pick_z)))
        except Exception:
            debug('the pick gave no global point, falling back to the '
                  'bounding box')

        # decide which level property matches the geometry, using the click
        if pick_z is not None:
            calibrate_levels(levels, pick_z)
            levels = sorted_levels(doc)
            debug('levels now: lowest "{}" at {:.0f} mm, highest "{}" at '
                  '{:.0f} mm'.format(
                      levels[0].Name, ft_to_mm(level_z(levels[0])),
                      levels[-1].Name, ft_to_mm(level_z(levels[-1]))))

        picked = doc.GetElement(ref.ElementId)
        transform = DB.Transform.Identity
        if isinstance(picked, DB.RevitLinkInstance):
            link_doc = picked.GetLinkDocument()
            if link_doc is None:
                report('That link is not loaded.')
                continue
            slab = link_doc.GetElement(ref.LinkedElementId)
            transform = picked.GetTotalTransform()
            debug('floor picked in link "{}"'.format(picked.Name))
            try:
                origin = transform.Origin
                debug('link transform origin {:.1f}, {:.1f}, {:.1f} mm'.format(
                    ft_to_mm(origin.X), ft_to_mm(origin.Y), ft_to_mm(origin.Z)))
            except Exception:
                pass
        else:
            slab = picked
            debug('floor picked in the host model')

        debug('{} service(s) selected'.format(len(services)))
        for sv in services:
            try:
                debug('   {} id {} {}'.format(
                    describe_element(sv.element), eid_value(sv.element.Id),
                    '(linked)' if sv.linked else ''))
            except Exception:
                pass

        if not is_slab(slab):
            report('That is not a floor - try again.')
            continue

        # --- place --------------------------------------------------------
        if resizing:
            # everything selected belongs to the ONE opening being re-fitted,
            # so the grouping rules are not applied -- the user has already
            # said what belongs together by picking it
            # and the opening keeps its own family: its Family settings say
            # how it sizes, and whether it is round
            slot, resize_values = resize_settings(target, 'slab')
            shape = 'round' if slot == 'slab_circ' else 'rect'
            jobs = [(shape, services)]
            debug('resizing to a {} opening around {} service(s)'.format(
                'circular' if shape == 'round' else 'rectangular',
                len(services)))
        else:
            jobs = build_jobs(services, group_gap_ft, pipe_gap_ft, method,
                              angle_tol)
        if not jobs:
            report('Nothing to place from that selection.')
            continue

        plan_level = view_level(uidoc.ActiveView)
        debug('{} job(s) to place'.format(len(jobs)))

        # ONE TRANSACTION PER OPENING, inside a group.
        # A single transaction for the whole batch is a way to lose the whole
        # batch: one service Revit refuses rolls back every opening placed
        # alongside it. The group keeps undo to one step.
        group = DB.TransactionGroup(
            doc, 'Resize slab penetration' if resizing
            else 'Place slab penetrations')
        group.Start()
        made = 0
        failed = 0
        seen = []
        # read once per selection; each job then takes its own family's
        profiles = load_profiles()

        for index, (shape, job) in enumerate(jobs):
            symbol = circ_symbol if shape == 'round' else rect_symbol
            if symbol is None:
                other = 'circular' if shape == 'round' else 'rectangular'
                debug('job {}: no {} family set, skipped'.format(
                    index + 1, other))
                failed += 1
                continue

            trans = DB.Transaction(
                doc, 'Resize slab penetration' if resizing
                else 'Place slab penetration')
            # the job's family's own clearance, else the tab's
            job_family = family_name_of(symbol)
            job_clearance_ft = mm_to_ft(family_clearance_mm(
                job_family, ft_to_mm(clearance_ft), profiles))
            job_gap_ft = mm_to_ft(family_clearance_mm(
                job_family, ft_to_mm(circ_gap_ft), profiles))
            try:
                override = None
                if shape == 'round':
                    override, note = circular_size(job[0], job_gap_ft,
                                                   circ_round_mm,
                                                   circ_insulation)
                    if override is None:
                        debug('job {}: skipped - {}'.format(index + 1, note))
                        failed += 1
                        continue
                    if note:
                        debug('job {}: {}'.format(index + 1, note))

                geom, error = compute_slab_bwic(
                    doc, job, slab, transform, job_clearance_ft, base_extra_ft,
                    top_extra_ft, levels, datum, pick_z, rule, round_up_mm,
                    height_extra_ft, top_height_extra_ft, plan_level, override)
                if geom is None:
                    debug('job {}: compute failed - {}'.format(index + 1,
                                                               error))
                    failed += 1
                    continue

                key = (round(ft_to_mm(geom['point'].X), 1),
                       round(ft_to_mm(geom['point'].Y), 1),
                       round(ft_to_mm(geom['width']), 1), shape)
                if key in seen and not resizing:
                    debug('job {}: duplicate of one already placed at '
                          '{:.0f}, {:.0f} - skipped'.format(
                              index + 1, key[0], key[1]))
                    continue
                seen.append(key)

                geom['circular'] = (shape == 'round')
                # the parameter names come from the profile of the family
                # this opening actually uses, so a rectangular and a round
                # family built differently can share one run
                if resizing and resize_values is not None:
                    symbol = target.Symbol
                    job_settings = dict(settings)
                    job_settings.update(resize_values)
                else:
                    job_settings = slab_job_settings(settings, shape, symbol,
                                                     profiles)
                trans.Start()
                quieten(trans)
                if resizing:
                    instance, notes = resize_slab_one(
                        doc, target, job, slab, transform, symbol, geom,
                        job_settings, options, workset)
                else:
                    instance, notes = place_slab_one(
                        doc, job, slab, transform, symbol, geom, job_settings,
                        options, workset)
                if instance is None:
                    trans.RollBack()
                    debug('job {}: nothing placed - {}'.format(
                        index + 1, '; '.join(notes)))
                    failed += 1
                    continue

                trans.Commit()
                made += 1
                debug('job {} ({}, {} service(s)): placed id {} : {}'.format(
                    index + 1, shape, len(job), eid_value(instance.Id),
                    '; '.join(notes)))
                report('{} - {}'.format(
                    'Resized' if resizing
                    else '{} of {} placed'.format(made, len(jobs)),
                    '; '.join(notes)))

            except Exception as err:
                if trans.HasStarted():
                    trans.RollBack()
                import traceback
                failed += 1
                debug('job {}: EXCEPTION\n{}'.format(
                    index + 1, traceback.format_exc()))
                logger.error(err)

        if made:
            group.Assimilate()
            placed += made
            report('{} opening{} {}{}.'.format(
                made, '' if made == 1 else 's',
                'resized' if resizing else 'placed',
                ', {} skipped'.format(failed) if failed else ''))
            guide('placed',
                  title='BWIC resized' if resizing else (
                      'BWIC placed' if made == 1
                      else '{} BWICs placed'.format(made)),
                  detail='{}Carry on with the next one, or press Esc to '
                         'stop.'.format('{} skipped. '.format(failed)
                                        if failed else ''))
        else:
            group.RollBack()
            report('Nothing {} - see the debug log.'.format(
                'resized' if resizing else 'placed'))
            guide('problem', title='Nothing placed',
                  detail='Nothing could be placed from that selection. '
                         'The status line says why.')

        uidoc.Selection.SetElementIds(List[DB.ElementId]())

    guide('done')
    report('Finished - {} slab opening{} {} this run.'.format(
        placed, '' if placed == 1 else 's',
        'resized' if resizing else 'placed'))
