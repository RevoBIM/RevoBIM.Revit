# -*- coding: utf-8 -*-
"""Version, settings, geometry, parameter discovery and the read of the model."""

import snte_clr  # noqa: F401  - must be first, before any System.* / Autodesk.*

import os
import re

from Autodesk.Revit import DB

__version__ = "2.0.2"

TOOL_NAME = "Space Name To Element"

# ---------------------------------------------------------------------------
#  Constants
# ---------------------------------------------------------------------------
PART_DELIM = " - "      # between space name and space number
SPACE_DELIM = " / "     # between multiple spaces

NO_TYPE = "<no type>"

SETTINGS_DIR = os.path.join(os.getenv("APPDATA") or "", "RevoBIM")
SETTINGS_PATH = os.path.join(SETTINGS_DIR, "space_name_to_element.txt")

DEFAULTS = {
    "settings_version": "2",
    "theme": "dark",
    "parameter": "BGL_Room name",
    "overwrite": "1",
    "clear_empty": "0",
    "auto_bind": "1",
    "chunk_size": "200",
}

# built-in instance text parameters offered alongside the project parameters
BUILTIN_TEXT_PARAMS = [
    "ALL_MODEL_INSTANCE_COMMENTS",
    "ALL_MODEL_MARK",
]

# categories that must never be offered or processed
SKIPPED_BIC_NAMES = [
    "OST_MEPSpaces", "OST_MEPSpaceSeparationLines",
    "OST_Rooms", "OST_RoomSeparationLines",
    "OST_Areas", "OST_AreaSchemeLines",
    "OST_RvtLinks", "OST_Levels", "OST_Grids", "OST_Cameras",
    "OST_ProjectBasePoint", "OST_SharedBasePoint", "OST_IOSModelGroups",
    "OST_SectionBox", "OST_Viewers",
]


def _skipped_ids():
    """BuiltInCategory members looked up late, so a name missing on a given
    release is skipped rather than throwing at import time."""
    out = set()
    for name in SKIPPED_BIC_NAMES:
        try:
            out.add(int(getattr(DB.BuiltInCategory, name)))
        except Exception:
            continue
    return out


# ---------------------------------------------------------------------------
#  Revit 2024 - 2027 helpers
# ---------------------------------------------------------------------------
def eid_value(element_id):
    """ElementId.IntegerValue was removed in Revit 2026 in favour of .Value."""
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


def natural_key(text):
    """Sort 1, 2, 10 rather than 1, 10, 2."""
    parts = re.split(r"(\d+)", text or "")
    return [int(p) if p.isdigit() else p.lower() for p in parts]


# ---------------------------------------------------------------------------
#  Settings - plain key=value text, no JSON dependency
# ---------------------------------------------------------------------------
def load_settings():
    """Defaults, overlaid key by key with whatever parsed out of the file."""
    data = dict(DEFAULTS)
    try:
        if os.path.exists(SETTINGS_PATH):
            handle = open(SETTINGS_PATH, "r")
            try:
                for line in handle:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, value = line.split("=", 1)   # first '=' only
                    key = key.strip()
                    if key in DEFAULTS:               # unknown keys ignored
                        data[key] = value.strip()
            finally:
                handle.close()
    except Exception:
        pass
    return data


def save_settings(data):
    try:
        if not os.path.isdir(SETTINGS_DIR):
            os.makedirs(SETTINGS_DIR)
        handle = open(SETTINGS_PATH, "w")
        try:
            handle.write("# RevoBIM PY - Space Name To Element\n")
            for key in sorted(DEFAULTS.keys()):
                handle.write("{0}={1}\n".format(key, data.get(key, DEFAULTS[key])))
        finally:
            handle.close()
        return True
    except Exception:
        return False


def as_bool(value):
    return str(value).strip().lower() in ("1", "true", "yes", "on")


# ---------------------------------------------------------------------------
#  Spaces
# ---------------------------------------------------------------------------
def space_label(space):
    """'Name - Number' for a space."""
    name = None
    number = None
    try:
        prm = space.get_Parameter(DB.BuiltInParameter.ROOM_NAME)
        if prm:
            name = prm.AsString()
    except Exception:
        pass
    try:
        prm = space.get_Parameter(DB.BuiltInParameter.ROOM_NUMBER)
        if prm:
            number = prm.AsString()
    except Exception:
        pass
    if not name:
        prm = space.LookupParameter("Name")
        name = prm.AsString() if prm else None
    if not number:
        prm = space.LookupParameter("Number")
        number = prm.AsString() if prm else None

    name = (name or "").strip()
    number = (number or "").strip()
    if name and number:
        return name + PART_DELIM + number
    return name or number or ""


def get_placed_spaces(doc):
    spaces = DB.FilteredElementCollector(doc) \
        .OfCategory(DB.BuiltInCategory.OST_MEPSpaces) \
        .WhereElementIsNotElementType().ToElements()
    placed = []
    for space in spaces:
        try:
            if space.Area > 0 and space.Location is not None:
                placed.append(space)
        except Exception:
            continue
    return placed


# ---------------------------------------------------------------------------
#  Geometry
# ---------------------------------------------------------------------------
def geometry_options():
    opts = DB.Options()
    opts.ComputeReferences = False
    opts.IncludeNonVisibleObjects = False
    opts.DetailLevel = DB.ViewDetailLevel.Medium
    return opts


def _harvest_solids(gobj, out):
    if isinstance(gobj, DB.Solid):
        try:
            if gobj.Volume > 1e-6 and gobj.Faces.Size > 0:
                out.append(gobj)
        except Exception:
            pass
    elif isinstance(gobj, DB.GeometryInstance):
        try:
            for sub in gobj.GetInstanceGeometry():
                _harvest_solids(sub, out)
        except Exception:
            pass


def solid_from_bbox(bbox):
    """Fallback volume when a space returns no geometry."""
    if bbox is None:
        return None
    try:
        from System.Collections.Generic import List
        mn = bbox.Min
        mx = bbox.Max
        height = mx.Z - mn.Z
        if height < 1e-6:
            return None
        pts = [DB.XYZ(mn.X, mn.Y, mn.Z), DB.XYZ(mx.X, mn.Y, mn.Z),
               DB.XYZ(mx.X, mx.Y, mn.Z), DB.XYZ(mn.X, mx.Y, mn.Z)]
        curves = List[DB.Curve]()
        for i in range(4):
            curves.Add(DB.Line.CreateBound(pts[i], pts[(i + 1) % 4]))
        loops = List[DB.CurveLoop]()
        loops.Add(DB.CurveLoop.Create(curves))
        return DB.GeometryCreationUtilities.CreateExtrusionGeometry(
            loops, DB.XYZ.BasisZ, height)
    except Exception:
        return None


def get_space_solids(space, opts):
    solids = []
    try:
        geo = space.get_Geometry(opts)
        if geo:
            for gobj in geo:
                _harvest_solids(gobj, solids)
    except Exception:
        pass
    if not solids:
        fallback = solid_from_bbox(space.get_BoundingBox(None))
        if fallback:
            solids.append(fallback)
    return solids


# ---------------------------------------------------------------------------
#  Parameters
# ---------------------------------------------------------------------------
def is_text_definition(definition):
    """True for Text / Multiline Text definitions, on 2024 and on 2025+."""
    try:
        dtype = definition.GetDataType()
        if dtype is not None:
            tid = dtype.TypeId
            for spec in (DB.SpecTypeId.String.Text,
                         DB.SpecTypeId.String.MultilineText):
                if tid == spec.TypeId:
                    return True
            return False
    except Exception:
        pass
    try:
        return definition.ParameterType in (DB.ParameterType.Text,
                                            DB.ParameterType.MultilineText)
    except Exception:
        return False


class ParamOption(object):
    """One selectable target parameter."""

    def __init__(self, name, definition=None, cat_ids=None,
                 shared=False, builtin=False):
        self.name = name
        self.definition = definition
        self.cat_ids = cat_ids or set()
        self.shared = shared
        self.builtin = builtin

    @property
    def kind(self):
        if self.builtin:
            return "built-in instance parameter"
        return "shared instance parameter" if self.shared \
            else "project instance parameter"

    def bound_to(self, cat_id_value):
        return cat_id_value in self.cat_ids


def get_instance_text_params(doc):
    """Every instance bound text parameter in the project, by name.

    Type bindings are deliberately left out: a type parameter would stamp
    every instance of a type with one space.
    """
    found = {}
    bmap = doc.ParameterBindings
    iterator = bmap.ForwardIterator()
    iterator.Reset()
    while iterator.MoveNext():
        try:
            definition = iterator.Key
            binding = iterator.Current
        except Exception:
            continue
        if definition is None or binding is None:
            continue
        if not isinstance(binding, DB.InstanceBinding):
            continue
        if not is_text_definition(definition):
            continue

        cat_ids = set()
        try:
            for cat in binding.Categories:
                cat_ids.add(eid_value(cat.Id))
        except Exception:
            pass

        shared = False
        try:
            pelem = doc.GetElement(definition.Id)
            shared = isinstance(pelem, DB.SharedParameterElement)
        except Exception:
            pass

        name = definition.Name
        existing = found.get(name)
        if existing is None or (shared and not existing.shared):
            found[name] = ParamOption(name, definition, cat_ids, shared, False)

    for bip_name in BUILTIN_TEXT_PARAMS:
        try:
            bip = getattr(DB.BuiltInParameter, bip_name)
            label = DB.LabelUtils.GetLabelFor(bip)
        except Exception:
            continue
        if label and label not in found:
            found[label] = ParamOption(label, None, set(), False, True)

    return sorted(found.values(), key=lambda p: p.name.lower())


def get_target_param(element, param_name):
    """A writeable text parameter of that name on the element, else None.

    GetParameters and LookupParameter do not always hand back the same object
    and a family can carry two parameters of one name, so every route is tried.
    """
    prm = None
    try:
        prm = element.LookupParameter(param_name)
    except Exception:
        prm = None
    if prm is None or prm.IsReadOnly or prm.StorageType != DB.StorageType.String:
        wanted = param_name.strip().lower()
        for candidate in element.Parameters:
            try:
                definition = candidate.Definition
                if definition is None:
                    continue
                if definition.Name.strip().lower() != wanted:
                    continue
                if candidate.IsReadOnly:
                    continue
                if candidate.StorageType != DB.StorageType.String:
                    continue
                return candidate
            except Exception:
                continue
    if prm is None:
        return None
    if prm.IsReadOnly or prm.StorageType != DB.StorageType.String:
        return None
    return prm


# ---------------------------------------------------------------------------
#  The category / family / type tree
# ---------------------------------------------------------------------------
class TypeNode(object):
    def __init__(self, key, name, family):
        self.key = key
        self.name = name
        self.family = family
        self.element_ids = []
        self.checked = False

    @property
    def count(self):
        return len(self.element_ids)

    def state(self):
        return self.checked

    def set_state(self, value):
        self.checked = bool(value)

    def match(self, keyword):
        return keyword in self.name.lower()


class FamilyNode(object):
    def __init__(self, name, category):
        self.name = name
        self.category = category
        self.types = {}

    @property
    def type_list(self):
        return sorted(self.types.values(), key=lambda t: natural_key(t.name))

    @property
    def count(self):
        return sum([t.count for t in self.types.values()])

    def state(self):
        vals = [t.state() for t in self.types.values()]
        if not vals or all(vals):
            return True if vals else False
        if not any(vals):
            return False
        return None

    def set_state(self, value):
        for node in self.types.values():
            node.set_state(value)

    def match(self, keyword):
        if keyword in self.name.lower():
            return True
        for node in self.types.values():
            if node.match(keyword):
                return True
        return False


class CategoryNode(object):
    def __init__(self, cat_id, name):
        self.cat_id = cat_id
        self.cat_id_value = eid_value(cat_id)
        self.name = name
        self.families = {}

    @property
    def family_list(self):
        return sorted(self.families.values(), key=lambda f: natural_key(f.name))

    @property
    def count(self):
        return sum([f.count for f in self.families.values()])

    def state(self):
        vals = [f.state() for f in self.families.values()]
        if not vals:
            return False
        if all([v is True for v in vals]):
            return True
        if all([v is False for v in vals]):
            return False
        return None

    def set_state(self, value):
        for node in self.families.values():
            node.set_state(value)

    def match(self, keyword):
        if keyword in self.name.lower():
            return True
        for node in self.families.values():
            if node.match(keyword):
                return True
        return False


def read_model_tree(doc, progress=None):
    """One pass over every placed instance, building categories -> families ->
    types and collecting the element ids as it goes, so nothing has to be
    collected a second time when the run starts."""
    skipped = _skipped_ids()
    cats = {}
    type_cache = {}

    collector = DB.FilteredElementCollector(doc) \
        .WhereElementIsNotElementType() \
        .WhereElementIsViewIndependent()
    elements = collector.ToElements()
    total = len(elements)

    for index, element in enumerate(elements):
        if progress is not None and (index % 2000 == 0 or index == total - 1):
            progress(index + 1, total)
        try:
            cat = element.Category
        except Exception:
            continue
        if cat is None:
            continue
        try:
            cid = eid_value(cat.Id)
        except Exception:
            continue
        if cid >= 0 or cid in skipped:
            continue

        cnode = cats.get(cid)
        if cnode is None:
            try:
                if cat.CategoryType != DB.CategoryType.Model:
                    continue
                if not cat.AllowsBoundParameters:
                    continue
                cname = cat.Name
            except Exception:
                continue
            cnode = CategoryNode(cat.Id, cname)
            cats[cid] = cnode

        # family and type name, cached per type id
        try:
            tid = element.GetTypeId()
            tkey = eid_value(tid)
        except Exception:
            tid = None
            tkey = 0
        pair = type_cache.get(tkey)
        if pair is None:
            fam_name = NO_TYPE
            type_name = NO_TYPE
            if tkey > 0:
                try:
                    etype = doc.GetElement(tid)
                    if etype is not None:
                        try:
                            fam_name = etype.FamilyName or NO_TYPE
                        except Exception:
                            fam_name = NO_TYPE
                        try:
                            type_name = DB.Element.Name.GetValue(etype) or NO_TYPE
                        except Exception:
                            type_name = NO_TYPE
                except Exception:
                    pass
            pair = (fam_name, type_name)
            type_cache[tkey] = pair
        fam_name, type_name = pair

        fnode = cnode.families.get(fam_name)
        if fnode is None:
            fnode = FamilyNode(fam_name, cnode)
            cnode.families[fam_name] = fnode

        tnode = fnode.types.get(tkey)
        if tnode is None:
            tnode = TypeNode(tkey, type_name, fnode)
            fnode.types[tkey] = tnode
        tnode.element_ids.append(element.Id)

    return sorted(cats.values(), key=lambda c: natural_key(c.name))


def selected_categories(cat_nodes):
    """Category nodes with at least one ticked type."""
    return [c for c in cat_nodes if c.state() is not False]


def selected_element_ids(cat_nodes):
    """Every element id under a ticked type."""
    out = []
    for cnode in cat_nodes:
        for fnode in cnode.families.values():
            for tnode in fnode.types.values():
                if tnode.checked:
                    out.extend(tnode.element_ids)
    return out


def selection_counts(cat_nodes):
    """(categories, types, elements) currently ticked."""
    cats = 0
    types = 0
    elements = 0
    for cnode in cat_nodes:
        hit = False
        for fnode in cnode.families.values():
            for tnode in fnode.types.values():
                if tnode.checked:
                    hit = True
                    types += 1
                    elements += tnode.count
        if hit:
            cats += 1
    return cats, types, elements
