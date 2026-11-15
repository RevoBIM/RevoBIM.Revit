# -*- coding: utf-8 -*-
"""Fire Damper Wall Type Push - shared core.

Geometry, host matching, parameter reading/writing and settings.
No WPF in here: this module is the part that can be reasoned about and
bench-checked without a window.

Runs on IronPython 2.7 and IronPython 3, Revit 2024 - 2027.
"""

import fdwt_clr  # noqa: F401  - assembly references MUST be first

import io
import os
import re

from Autodesk.Revit.DB import (
    BooleanOperationsType,
    BooleanOperationsUtils,
    BoundingBoxIntersectsFilter,
    BuiltInCategory,
    BuiltInParameter,
    CurveLoop,
    ElementId,
    ElementIntersectsSolidFilter,
    ElementMulticategoryFilter,
    FilteredElementCollector,
    GeometryCreationUtilities,
    GeometryInstance,
    Line,
    Options,
    Outline,
    RevitLinkInstance,
    Solid,
    SolidUtils,
    StorageType,
    Transform,
    ViewDetailLevel,
    WorksharingUtils,
    XYZ,
)
from System.Collections.Generic import List

__version__ = "1.2.0"

TOOL_NAME = "Fire Damper Wall Type Push"

# The synthetic entry that means "the host type's own name" rather than a
# project parameter that happens to be called this.
TYPE_NAME_KEY = "Family type name"

CURRENT_MODEL_KEY = "<Current model>"

# ============================================================================
# small helpers
# ============================================================================

STR_TYPES = (str,)
try:
    STR_TYPES = (str, unicode)  # noqa: F821  - IronPython 2.7 only
except NameError:
    pass


def eid_value(element_id):
    """ElementId as a number, on every Revit release.

    .IntegerValue was deprecated in 2024 and removed in 2026; .Value (Int64)
    replaced it.  Never touch either directly.
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


def is_text(value):
    return isinstance(value, STR_TYPES)


def safe_name(element):
    """Element.Name without letting a refused read take the tool down."""
    if element is None:
        return ""
    try:
        return element.Name or ""
    except Exception:
        return ""


# ============================================================================
# settings - plain key=value under %APPDATA%\RevoBIM\
# ============================================================================

SETTINGS_DIRNAME = "RevoBIM"
SETTINGS_FILENAME = "fire_damper_wall_type_push.txt"

DEFAULTS = {
    "theme": "dark",
    "link": CURRENT_MODEL_KEY,
    "src_type_param": TYPE_NAME_KEY,
    "src_fire_param": "POP_PERF_FireRatingTarget",
    "tgt_type_param": "",
    "tgt_fire_param": "BGL_Wall Fire Rating",
    "scope": "project",          # project | view
    "overwrite": "1",
    "only_rated": "0",
    "hosts": "walls,floors",
    "excluded_families": "",     # families UNticked, delimited by |
}


def settings_dir():
    base = os.getenv("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, SETTINGS_DIRNAME)


def settings_path():
    return os.path.join(settings_dir(), SETTINGS_FILENAME)


def load_settings():
    """Defaults, overlaid key by key with whatever the file can give us.

    A missing or damaged file falls back to the defaults key by key, and keys
    from an older version are ignored rather than breaking the load.
    """
    values = {}
    values.update(DEFAULTS)
    path = settings_path()
    try:
        if not os.path.isfile(path):
            return values
        handle = io.open(path, "r", encoding="utf-8")
        try:
            lines = handle.readlines()
        finally:
            handle.close()
    except Exception:
        return values

    for line in lines:
        try:
            raw = line.strip()
            if not raw or raw.startswith("#") or "=" not in raw:
                continue
            key, value = raw.split("=", 1)
            key = key.strip()
            if key in DEFAULTS:
                values[key] = value.strip()
        except Exception:
            continue
    return values


def save_settings(values):
    try:
        folder = settings_dir()
        if not os.path.isdir(folder):
            os.makedirs(folder)
        handle = io.open(settings_path(), "w", encoding="utf-8")
        try:
            handle.write(u"# RevoBIM - {0} {1}\n".format(TOOL_NAME, __version__))
            for key in sorted(DEFAULTS.keys()):
                handle.write(u"{0}={1}\n".format(key, values.get(key, DEFAULTS[key])))
        finally:
            handle.close()
        return True
    except Exception:
        return False


def log_path():
    return os.path.join(settings_dir(), "fire_damper_wall_type_push.log")


def log_line(text):
    """Best effort diagnostic log beside the settings file."""
    try:
        folder = settings_dir()
        if not os.path.isdir(folder):
            os.makedirs(folder)
        handle = io.open(log_path(), "a", encoding="utf-8")
        try:
            handle.write(u"{0}\n".format(text))
        finally:
            handle.close()
    except Exception:
        pass


# ============================================================================
# parameters
# ============================================================================

def param_by_name(element, name):
    if element is None or not name:
        return None
    try:
        found = element.GetParameters(name)
        if found is not None and found.Count > 0:
            return found[0]
    except Exception:
        pass
    try:
        return element.LookupParameter(name)
    except Exception:
        return None


def param_to_string(param):
    """Whatever the parameter holds, as text, or None when it holds nothing."""
    if param is None:
        return None
    try:
        if not param.HasValue:
            return None
    except Exception:
        pass
    try:
        storage = param.StorageType
    except Exception:
        return None

    try:
        if storage == StorageType.String:
            return param.AsString()
        if storage == StorageType.Integer:
            shown = param.AsValueString()
            if shown:
                return shown
            return str(param.AsInteger())
        if storage == StorageType.Double:
            shown = param.AsValueString()
            if shown:
                return shown
            return str(param.AsDouble())
        if storage == StorageType.ElementId:
            shown = param.AsValueString()
            if shown:
                return shown
            return None
    except Exception:
        return None
    return None


def set_param_string(param, value):
    """Write text into a parameter. Returns (ok, message)."""
    if param is None:
        return False, "parameter not found"
    try:
        if param.IsReadOnly:
            return False, "parameter is read only"
    except Exception:
        pass

    text = value if value is not None else ""
    try:
        storage = param.StorageType
    except Exception:
        return False, "parameter has no storage type"

    try:
        if storage == StorageType.String:
            param.Set(text)
            return True, ""
        if storage in (StorageType.Integer, StorageType.Double):
            try:
                if param.SetValueString(text):
                    return True, ""
            except Exception:
                pass
            number = first_number(text)
            if number is None:
                return False, "target parameter is numeric, value is not"
            if storage == StorageType.Integer:
                param.Set(int(round(number)))
            else:
                param.Set(number)
            return True, ""
    except Exception as err:
        return False, str(err)
    return False, "unsupported parameter type"


def param_candidates(element, name):
    """Every route to a parameter of this name, best first.

    GetParameters and LookupParameter do not always return the same object,
    and a family can carry two parameters with the same name (one shared, one
    project).  Trying each in turn is what makes the write stick.
    """
    found = []
    if element is None or not name:
        return found
    try:
        for param in element.GetParameters(name):
            found.append(param)
    except Exception:
        pass
    try:
        param = element.LookupParameter(name)
        if param is not None:
            found.append(param)
    except Exception:
        pass
    return found


def values_match(left, right):
    """Did the value land? Revit hands numbers back in its own formatting."""
    left = (left or "").strip()
    right = (right or "").strip()
    if left == right:
        return True
    if left.lower() == right.lower():
        return True
    first = first_number(left)
    second = first_number(right)
    if first is not None and second is not None:
        if abs(first - second) < 1.0e-6:
            return True
    return False


def write_value(element, name, value, log=False):
    """Write text into a parameter and PROVE it landed.

    Revit does not reliably raise when a write does not take - the same trap
    as renaming an element - so the value is always read back through a fresh
    lookup, and every route is tried before giving up.

    Returns (ok, message).
    """
    if not name:
        return False, "no target parameter chosen"

    candidates = param_candidates(element, name)
    if not candidates:
        return False, "parameter '{0}' is not on this element".format(name)

    problems = []
    for index, param in enumerate(candidates):
        try:
            if param.IsReadOnly:
                problems.append("read only")
                continue
        except Exception:
            pass

        ok, message = set_param_string(param, value)
        if not ok:
            problems.append(message)
            continue

        # read it back through a fresh lookup, not through the object we
        # just wrote to
        landed = None
        for check in param_candidates(element, name):
            landed = param_to_string(check)
            if values_match(landed, value):
                break
        if values_match(landed, value):
            if log:
                log_line(
                    u"  wrote {0} = {1}".format(name, value)
                )
            return True, ""
        problems.append(
            "wrote '{0}' but it reads back '{1}'".format(value, landed or "")
        )

    message = "; ".join([p for p in problems if p]) or "the write did not take"
    if log:
        log_line(u"  FAILED {0} = {1} :: {2}".format(name, value, message))
    return False, message


NUMBER_RE = re.compile(r"[-+]?\d*\.?\d+")


def first_number(text):
    if not is_text(text):
        return None
    found = NUMBER_RE.search(text)
    if not found:
        return None
    try:
        return float(found.group(0))
    except Exception:
        return None


def host_type_name(host, host_doc, source_param_name):
    """The value the host offers for bit of data 1.

    TYPE_NAME_KEY resolves in this order: a real parameter of that name on the
    type, then on the instance, then the built in Type Name, then the host
    type's own Element.Name.  Any other name is a straight parameter lookup on
    type then instance.  Works the same for a wall type or a floor type.
    """
    host_type = None
    try:
        host_type = host_doc.GetElement(host.GetTypeId())
    except Exception:
        host_type = None

    if source_param_name and source_param_name != TYPE_NAME_KEY:
        value = param_to_string(param_by_name(host_type, source_param_name))
        if value:
            return value
        return param_to_string(param_by_name(host, source_param_name))

    for holder in (host_type, host):
        value = param_to_string(param_by_name(holder, TYPE_NAME_KEY))
        if value:
            return value
    try:
        value = param_to_string(host_type.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM))
        if value:
            return value
    except Exception:
        pass
    return safe_name(host_type)


def host_fire_rating(host, host_doc, source_param_name):
    """The value the host offers for bit of data 2. Type first, then instance."""
    host_type = None
    try:
        host_type = host_doc.GetElement(host.GetTypeId())
    except Exception:
        host_type = None
    for holder in (host_type, host):
        value = param_to_string(param_by_name(holder, source_param_name))
        if value:
            return value
    return None


def writable_instance_param_names(elements, limit=40):
    """Names of instance parameters we could write text into.

    Read from a sample of real elements, so the dropdown only ever offers
    parameters that actually exist on the accessories in this project.
    """
    names = set()
    count = 0
    for element in elements:
        if count >= limit:
            break
        count += 1
        try:
            params = element.Parameters
        except Exception:
            continue
        for param in params:
            try:
                if param.IsReadOnly:
                    continue
                if param.StorageType not in (
                    StorageType.String,
                    StorageType.Integer,
                    StorageType.Double,
                ):
                    continue
                definition = param.Definition
                if definition is None:
                    continue
                names.add(definition.Name)
            except Exception:
                continue
    return sorted(names, key=lambda text: text.lower())


def readable_param_names(elements, host_doc, limit=40):
    """Names of parameters a host (type or instance) can offer us."""
    names = set()
    count = 0
    for element in elements:
        if count >= limit:
            break
        count += 1
        holders = [element]
        try:
            holders.append(host_doc.GetElement(element.GetTypeId()))
        except Exception:
            pass
        for holder in holders:
            if holder is None:
                continue
            try:
                params = holder.Parameters
            except Exception:
                continue
            for param in params:
                try:
                    definition = param.Definition
                    if definition is None:
                        continue
                    names.add(definition.Name)
                except Exception:
                    continue
    return sorted(names, key=lambda text: text.lower())


# ============================================================================
# geometry
# ============================================================================

def geometry_options():
    options = Options()
    try:
        options.DetailLevel = ViewDetailLevel.Fine
    except Exception:
        pass
    try:
        options.ComputeReferences = False
        options.IncludeNonVisibleObjects = False
    except Exception:
        pass
    return options


def element_solids(element, options=None):
    """Every real solid on an element, instance geometry unwrapped."""
    if options is None:
        options = geometry_options()
    solids = []
    try:
        geometry = element.get_Geometry(options)
    except Exception:
        return solids
    if geometry is None:
        return solids
    _walk_geometry(geometry, solids)
    return solids


def _walk_geometry(geometry, solids, depth=0):
    if depth > 6:
        return
    try:
        items = list(geometry)
    except Exception:
        return
    for item in items:
        try:
            if isinstance(item, Solid):
                if item.Volume > 1.0e-9 and item.Faces.Size > 0:
                    solids.append(item)
            elif isinstance(item, GeometryInstance):
                _walk_geometry(item.GetInstanceGeometry(), solids, depth + 1)
        except Exception:
            continue


def box_solid(bbox):
    """A solid the size of a bounding box - the fallback when an element
    hands us no usable geometry (empty family, coarse view, hidden)."""
    if bbox is None:
        return None
    try:
        low = bbox.Min
        high = bbox.Max
        height = high.Z - low.Z
        if height < 1.0e-6:
            height = 1.0e-3
        corners = [
            XYZ(low.X, low.Y, low.Z),
            XYZ(high.X, low.Y, low.Z),
            XYZ(high.X, high.Y, low.Z),
            XYZ(low.X, high.Y, low.Z),
        ]
        loop = CurveLoop()
        for index in range(4):
            start = corners[index]
            end = corners[(index + 1) % 4]
            if start.DistanceTo(end) < 1.0e-6:
                return None
            loop.Append(Line.CreateBound(start, end))
        loops = List[CurveLoop]()
        loops.Add(loop)
        return GeometryCreationUtilities.CreateExtrusionGeometry(
            loops, XYZ.BasisZ, height
        )
    except Exception:
        return None


def transform_solid(solid, transform):
    if solid is None:
        return None
    if transform is None:
        return solid
    try:
        if transform.IsIdentity:
            return solid
    except Exception:
        pass
    try:
        return SolidUtils.CreateTransformed(solid, transform)
    except Exception:
        return None


def transformed_outline(bbox, transform):
    """An axis aligned Outline covering a bounding box after a transform."""
    if bbox is None:
        return None
    try:
        low = bbox.Min
        high = bbox.Max
        points = []
        for x in (low.X, high.X):
            for y in (low.Y, high.Y):
                for z in (low.Z, high.Z):
                    point = XYZ(x, y, z)
                    if transform is not None:
                        point = transform.OfPoint(point)
                    points.append(point)
        min_x = min([p.X for p in points])
        min_y = min([p.Y for p in points])
        min_z = min([p.Z for p in points])
        max_x = max([p.X for p in points])
        max_y = max([p.Y for p in points])
        max_z = max([p.Z for p in points])
        pad = 0.01  # ~3mm, so a damper sitting exactly on a host face counts
        return Outline(
            XYZ(min_x - pad, min_y - pad, min_z - pad),
            XYZ(max_x + pad, max_y + pad, max_z + pad),
        )
    except Exception:
        return None


def intersection_volume(solid_a, solid_b):
    try:
        result = BooleanOperationsUtils.ExecuteBooleanOperation(
            solid_a, solid_b, BooleanOperationsType.Intersect
        )
        if result is None:
            return 0.0
        return result.Volume
    except Exception:
        return -1.0  # "could not tell" - treated as a weak hit, not a miss


# ============================================================================
# collecting
# ============================================================================

def link_instances(doc):
    """Every placed Revit link, as (label, RevitLinkInstance)."""
    found = []
    try:
        collector = (
            FilteredElementCollector(doc)
            .OfClass(RevitLinkInstance)
            .WhereElementIsNotElementType()
        )
        for link in collector:
            try:
                link_doc = link.GetLinkDocument()
            except Exception:
                link_doc = None
            if link_doc is None:
                continue  # unloaded
            label = safe_name(doc.GetElement(link.GetTypeId())) or safe_name(link)
            if not label:
                label = link_doc.Title
            found.append((label, link))
    except Exception:
        pass
    found.sort(key=lambda pair: pair[0].lower())

    # Same link placed twice would give two identical labels - number them.
    seen = {}
    labelled = []
    for label, link in found:
        count = seen.get(label, 0) + 1
        seen[label] = count
        if count > 1:
            label = "{0} ({1})".format(label, count)
        labelled.append((label, link))
    return labelled


def duct_accessories(doc, view=None):
    try:
        if view is not None:
            collector = FilteredElementCollector(doc, view.Id)
        else:
            collector = FilteredElementCollector(doc)
        return list(
            collector.OfCategory(BuiltInCategory.OST_DuctAccessory)
            .WhereElementIsNotElementType()
            .ToElements()
        )
    except Exception:
        return []


def family_of(element, doc):
    """Family name of a family instance, for the include/exclude list."""
    try:
        symbol = doc.GetElement(element.GetTypeId())
        if symbol is None:
            return "(no type)"
        try:
            family = symbol.Family
            if family is not None:
                return safe_name(family) or "(no family)"
        except Exception:
            pass
        return safe_name(symbol) or "(no family)"
    except Exception:
        return "(no family)"


def type_of(element, doc):
    try:
        return safe_name(doc.GetElement(element.GetTypeId()))
    except Exception:
        return ""


HOST_WALLS = "walls"
HOST_FLOORS = "floors"
HOST_KEYS = (HOST_WALLS, HOST_FLOORS)
HOST_LABELS = {HOST_WALLS: "Wall", HOST_FLOORS: "Floor"}


def builtin_category(key):
    """OST_Walls / OST_Floors, looked up late.

    Deliberately not a module level dict: touching BuiltInCategory members at
    import time is one more thing that can die before the tool runs.
    """
    try:
        if key == HOST_WALLS:
            return BuiltInCategory.OST_Walls
        if key == HOST_FLOORS:
            return BuiltInCategory.OST_Floors
    except Exception:
        pass
    return None


def host_categories(keys):
    """Clean a list of host keys, defaulting to walls when it comes back empty."""
    wanted = [key for key in (keys or []) if key in HOST_KEYS]
    return wanted or [HOST_WALLS]


def host_collector(host_doc, keys=None):
    """Every wall and/or floor in a document."""
    wanted = host_categories(keys)
    collector = FilteredElementCollector(host_doc).WhereElementIsNotElementType()
    if len(wanted) == 1:
        category = builtin_category(wanted[0])
        if category is not None:
            return collector.OfCategory(category)
        return collector
    categories = List[BuiltInCategory]()
    for key in wanted:
        category = builtin_category(key)
        if category is not None:
            categories.Add(category)
    return collector.WherePasses(ElementMulticategoryFilter(categories))


def host_kind(element):
    """"Wall" or "Floor", as Revit names the category in this language."""
    try:
        category = element.Category
        if category is not None:
            return safe_name(category) or ""
    except Exception:
        pass
    return ""


def host_ids_in_reach(host_doc, outline, keys=None):
    """Cheap first pass: hosts whose bounding box meets the outline."""
    ids = []
    if outline is None:
        return ids
    try:
        collector = host_collector(host_doc, keys).WherePasses(
            BoundingBoxIntersectsFilter(outline)
        )
        for host in collector:
            ids.append(host.Id)
    except Exception:
        pass
    return ids


# ============================================================================
# the match
# ============================================================================

STATUS_CHANGE = "change"        # orange - waiting to be applied
STATUS_SAME = "same"            # green  - already correct
STATUS_REVIEW = "review"        # red    - needs looking at by hand
STATUS_DONE = "done"            # green  - written this run
STATUS_FAILED = "failed"        # red    - the write was refused


class MatchRow(object):
    """One duct accessory and what we intend to do to it."""

    def __init__(self, element, doc):
        self.element = element
        self.id = eid_value(element.Id)
        self.family = family_of(element, doc)
        self.type_name = type_of(element, doc)
        self.mark = param_to_string(param_by_name(element, "Mark")) or ""
        self.level = ""
        try:
            level = doc.GetElement(element.LevelId)
            self.level = safe_name(level)
        except Exception:
            self.level = ""
        self.host_label = ""
        self.host_kind = ""
        self.host_id = 0
        self.host_count = 0
        self.new_type_value = None
        self.new_fire_value = None
        self.old_type_value = None
        self.old_fire_value = None
        self.status = STATUS_REVIEW
        self.note = ""

    @property
    def label(self):
        if self.type_name:
            return "{0} : {1}".format(self.family, self.type_name)
        return self.family


def find_hosts_for(
    accessory, host_doc, link_transform, options, host_cache=None, keys=None
):
    """Every wall or floor this accessory passes through, best hit first.

    Returns a list of (host, overlap_volume).  Volume is -1 where the boolean
    could not be computed, which we treat as a weak but real hit.
    """
    hits = []
    inverse = None
    if link_transform is not None:
        try:
            inverse = link_transform.Inverse
        except Exception:
            inverse = None

    try:
        bbox = accessory.get_BoundingBox(None)
    except Exception:
        bbox = None

    outline = transformed_outline(bbox, inverse)
    if outline is None:
        return hits

    candidate_ids = host_ids_in_reach(host_doc, outline, keys)
    if not candidate_ids:
        return hits

    solids = element_solids(accessory, options)
    if not solids:
        fallback = box_solid(bbox)
        if fallback is not None:
            solids = [fallback]
    if not solids:
        return hits

    link_solids = []
    for solid in solids:
        moved = transform_solid(solid, inverse)
        if moved is not None:
            link_solids.append(moved)
    if not link_solids:
        return hits

    for host_id in candidate_ids:
        host = host_doc.GetElement(host_id)
        if host is None:
            continue

        # A host is usually hit by several accessories: pulling its geometry
        # once and keeping it is the difference between seconds and minutes.
        key = eid_value(host_id)
        host_solids = None
        if host_cache is not None:
            host_solids = host_cache.get(key)
        if host_solids is None:
            host_solids = element_solids(host, options)
            if not host_solids:
                try:
                    fallback = box_solid(host.get_BoundingBox(None))
                except Exception:
                    fallback = None
                host_solids = [fallback] if fallback is not None else []
            if host_cache is not None:
                host_cache[key] = host_solids
        if not host_solids:
            continue

        best = 0.0
        unknown = False
        for one in link_solids:
            for other in host_solids:
                volume = intersection_volume(one, other)
                if volume < 0:
                    unknown = True
                elif volume > best:
                    best = volume
        if best > 1.0e-9:
            hits.append((host, best))
        elif unknown:
            hits.append((host, -1.0))

    hits.sort(key=lambda pair: pair[1], reverse=True)
    return hits


def build_rows(
    doc,
    accessories,
    host_doc,
    link_transform,
    src_type_param,
    src_fire_param,
    tgt_type_param,
    tgt_fire_param,
    only_rated=False,
    progress=None,
    keys=None,
):
    """Work out, for every accessory, which wall or floor it passes through
    and what would be written.  Reads only - nothing is written until Apply."""
    options = geometry_options()
    host_cache = {}
    rows = []
    total = len(accessories)
    for index, accessory in enumerate(accessories):
        if progress is not None:
            progress(index, total)

        row = MatchRow(accessory, doc)
        try:
            hits = find_hosts_for(
                accessory, host_doc, link_transform, options, host_cache, keys
            )
        except Exception as err:
            row.status = STATUS_REVIEW
            row.note = "geometry failed: {0}".format(err)
            rows.append(row)
            continue

        if not hits:
            row.status = STATUS_REVIEW
            row.note = "nothing intersecting"
            rows.append(row)
            continue

        host = hits[0][0]
        row.host_count = len(hits)
        row.host_id = eid_value(host.Id)
        row.host_kind = host_kind(host)
        row.host_label = safe_name(host_doc.GetElement(host.GetTypeId()))

        row.new_type_value = host_type_name(host, host_doc, src_type_param)
        row.new_fire_value = host_fire_rating(host, host_doc, src_fire_param)

        if only_rated and not row.new_fire_value:
            row.status = STATUS_REVIEW
            row.note = "no fire rating on the {0}".format(
                (row.host_kind or "host").lower()
            )
            rows.append(row)
            continue

        type_param = param_by_name(accessory, tgt_type_param)
        fire_param = param_by_name(accessory, tgt_fire_param)
        row.old_type_value = param_to_string(type_param)
        row.old_fire_value = param_to_string(fire_param)

        missing = []
        if tgt_type_param and type_param is None:
            missing.append(tgt_type_param)
        if tgt_fire_param and fire_param is None:
            missing.append(tgt_fire_param)
        if missing:
            row.status = STATUS_REVIEW
            row.note = "no parameter: " + ", ".join(missing)
            rows.append(row)
            continue

        notes = []
        if row.host_count > 1:
            notes.append("{0} hosts hit, deepest used".format(row.host_count))
        if not row.new_fire_value:
            notes.append(
                "no fire rating on the {0}".format((row.host_kind or "host").lower())
            )

        same_type = (row.old_type_value or "") == (row.new_type_value or "")
        same_fire = (row.old_fire_value or "") == (row.new_fire_value or "")
        if same_type and same_fire:
            row.status = STATUS_SAME
        else:
            row.status = STATUS_CHANGE
        row.note = ", ".join(notes)
        rows.append(row)

    if progress is not None:
        progress(total, total)
    return rows


def checkout(doc, elements):
    """Borrow the elements before writing, on a workshared model.

    On a cloud workshared model a write to an element you have not borrowed
    does not throw - Revit puts up a dialog, and a run that is suppressing
    dialogs answers it and carries on having written nothing. Borrowing up
    front, outside the transaction, is the only way to know.

    Returns (owned ids or None when the question does not apply, message).
    """
    try:
        if not doc.IsWorkshared:
            return None, ""
    except Exception:
        return None, ""

    try:
        ids = List[ElementId]()
        for element in elements:
            ids.Add(element.Id)
        got = WorksharingUtils.CheckoutElements(doc, ids)
        owned = set()
        for element_id in got:
            owned.add(eid_value(element_id))
        return owned, ""
    except Exception as err:
        log_line(u"checkout failed: {0}".format(err))
        return None, str(err)


def apply_row(row, tgt_type_param, tgt_fire_param, overwrite=True, log=False):
    """Write one row and confirm it landed. Caller owns the transaction."""
    problems = []
    wrote = False
    skipped = []

    if log:
        log_line(u"row {0} - {1}".format(row.id, row.label))

    pairs = (
        (tgt_type_param, row.new_type_value, row.old_type_value),
        (tgt_fire_param, row.new_fire_value, row.old_fire_value),
    )
    for name, new_value, old_value in pairs:
        if not name:
            continue
        if new_value is None or new_value == "":
            skipped.append("nothing to write to {0}".format(name))
            continue
        if not overwrite and old_value:
            skipped.append("{0} already has a value".format(name))
            continue
        if values_match(old_value, new_value):
            continue

        ok, message = write_value(row.element, name, new_value, log=log)
        if ok:
            wrote = True
        else:
            problems.append("{0}: {1}".format(name, message))

    if problems:
        row.status = STATUS_FAILED
        row.note = "; ".join(problems)
        return False
    if wrote:
        row.status = STATUS_DONE
        row.old_type_value = row.new_type_value
        row.old_fire_value = row.new_fire_value
        row.note = ""
    else:
        row.status = STATUS_SAME
        row.note = "; ".join(skipped)
    return True


def accessory_multicategory_filter():
    """Kept for callers that want the filter rather than the collector."""
    categories = List[BuiltInCategory]()
    categories.Add(BuiltInCategory.OST_DuctAccessory)
    return ElementMulticategoryFilter(categories)


def identity_transform():
    return Transform.Identity


def element_id_from(value):
    try:
        return ElementId(value)
    except Exception:
        return ElementId.InvalidElementId
