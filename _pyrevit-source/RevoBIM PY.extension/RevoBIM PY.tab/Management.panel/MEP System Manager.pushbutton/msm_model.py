# -*- coding: utf-8 -*-
"""Everything the window shows is read here, in one pass per collector.

BuiltInParameter and BuiltInCategory members are looked up at call time, never
at module load, so a member one release lacks cannot stop the tool loading.
"""
import msm_clr  # noqa: F401  - assemblies first

from Autodesk.Revit.DB import (FilteredElementCollector, BuiltInParameter,
                               BuiltInCategory, StorageType, View3D, Element,
                               ElementId, FamilyInstance, ElementCategoryFilter,
                               InsulationLiningBase, RoutingPreferenceRuleGroupType,
                               MEPCurve, FamilySymbol, FilteredWorksetCollector,
                               WorksetKind)
from Autodesk.Revit.DB.Plumbing import Pipe, PipeType, PipingSystem
from Autodesk.Revit.DB.Mechanical import (Duct, DuctType, DuctShape, DuctSizeSettings,
                                          MechanicalSystem)
from Autodesk.Revit.DB.Electrical import CableTray, Conduit, CableTrayType, ConduitType

import msm_core as core


# ============================================================
# version-safe helpers
# ============================================================

def eid_value(element_id):
    """ElementId.IntegerValue was removed in Revit 2026; .Value is Int64."""
    if element_id is None:
        return 0
    try:
        return int(element_id.Value)
    except Exception:
        pass
    try:
        return int(element_id.IntegerValue)
    except Exception:
        return 0


def make_id(number):
    """ElementId(Int64) from 2024, ElementId(int) before - try both."""
    try:
        from System import Int64
        return ElementId(Int64(number))
    except Exception:
        return ElementId(int(number))


def bip(name):
    return getattr(BuiltInParameter, name, None)


def bic(name):
    return getattr(BuiltInCategory, name, None)


def elem_name(element):
    """Element.Name raises AttributeError in IronPython on some classes."""
    if element is None:
        return u""
    try:
        return element.Name or u""
    except Exception:
        pass
    try:
        return Element.Name.GetValue(element) or u""
    except Exception:
        pass
    for name in (u"SYMBOL_NAME_PARAM", u"ALL_MODEL_TYPE_NAME"):
        try:
            p = element.get_Parameter(bip(name))
            if p is not None and p.AsString():
                return p.AsString()
        except Exception:
            pass
    return u""


def param_text(element, name):
    if element is None or not name:
        return u""
    try:
        p = element.LookupParameter(name)
    except Exception:
        p = None
    if p is None:
        return u""
    try:
        if p.StorageType == StorageType.String:
            return p.AsString() or u""
        text = p.AsValueString()
        if text:
            return text
        if p.StorageType == StorageType.Integer:
            return u"{0}".format(p.AsInteger())
        if p.StorageType == StorageType.Double:
            return u"{0}".format(p.AsDouble())
    except Exception:
        pass
    return u""


def builtin_text(element, name):
    member = bip(name)
    if member is None or element is None:
        return u""
    try:
        p = element.get_Parameter(member)
        if p is None:
            return u""
        if p.StorageType == StorageType.String:
            return p.AsString() or u""
        return p.AsValueString() or u""
    except Exception:
        return u""


# ============================================================
# the read
# ============================================================

class Snapshot(object):
    def __init__(self):
        self.records = []
        self.types = []             # [(name, id int)] - the tab's own types
        self.views_3d = []          # [(name, id int)]
        self.param_names = []       # writable instance params, pipes + fittings
        self.all_param_names = []   # everything on a pipe, for grouping
        self.system_names = {}      # element id -> system name
        self.warnings = []
        self.systems = []           # Workset Assigner: every system of all three
        self.worksets = []          # Workset Assigner: [(name, number)]
        self.workshared = True


# ============================================================
# the three disciplines
# ============================================================

def curve_classes(domain):
    if domain == u"duct":
        return [Duct]
    if domain == u"cont":
        return [CableTray, Conduit]
    return [Pipe]


def type_classes(domain):
    if domain == u"duct":
        return [DuctType]
    if domain == u"cont":
        return [CableTrayType, ConduitType]
    return [PipeType]


KIND_LABEL = {u"tray": u"Cable Tray", u"conduit": u"Conduit"}


def element_kind(element):
    for cls, kind in ((Pipe, u"pipe"), (Duct, u"duct"), (CableTray, u"tray"),
                      (Conduit, u"conduit")):
        try:
            if isinstance(element, cls):
                return kind
        except Exception:
            pass
    return u""


def type_kind(type_element):
    for cls, kind in ((PipeType, u"pipe"), (DuctType, u"duct"), (CableTrayType, u"tray"),
                      (ConduitType, u"conduit")):
        try:
            if isinstance(type_element, cls):
                return kind
        except Exception:
            pass
    return u""


def type_label(type_element):
    """What a type is called in the table. Containment mixes cable tray and
    conduit types, so each says which it is."""
    name = elem_name(type_element)
    kind = type_kind(type_element)
    if kind in KIND_LABEL:
        return u"{0}: {1}".format(KIND_LABEL[kind], name)
    return name


def accepts(type_element, element):
    """A type can only be given to an element of the same kind - a cable tray
    cannot become a conduit type."""
    kind = type_kind(type_element)
    return bool(kind) and kind == element_kind(element)


def collect_curves(doc, domain, view=None):
    out = []
    for cls in curve_classes(domain):
        if view is not None:
            collector = FilteredElementCollector(doc, view.Id)
        else:
            collector = FilteredElementCollector(doc)
        out.extend(list(collector.OfClass(cls).WhereElementIsNotElementType()))
    return out


def service_of(element, settings):
    """Containment's service type: the Service Type parameter, or the custom
    parameter chosen in Settings - read off the instance, then its type."""
    if (settings or {}).get(u"group_by") == u"param":
        name = (settings or {}).get(u"group_param") or u""
        text = param_text(element, name)
        if not text:
            try:
                text = param_text(element.Document.GetElement(element.GetTypeId()), name)
            except Exception:
                text = u""
        return text.strip()
    return builtin_text(element, u"RBS_CTC_SERVICE_TYPE").strip()


# ============================================================
# sizes
# ============================================================

def _double(element, name):
    member = bip(name)
    if member is None:
        return None
    try:
        p = element.get_Parameter(member)
        if p is None or not p.HasValue:
            return None
        value = p.AsDouble()
        return value if value > 0 else None
    except Exception:
        return None


def size_params(element):
    """The built-in parameters that hold an element's size, by kind. A round
    duct has a diameter, a rectangular or oval one a width and a height."""
    kind = element_kind(element)
    if kind == u"pipe":
        return [u"RBS_PIPE_DIAMETER_PARAM"]
    if kind == u"duct":
        if _double(element, u"RBS_CURVE_DIAMETER_PARAM") is not None:
            return [u"RBS_CURVE_DIAMETER_PARAM"]
        return [u"RBS_CURVE_WIDTH_PARAM", u"RBS_CURVE_HEIGHT_PARAM"]
    if kind == u"tray":
        return [u"RBS_CABLETRAY_WIDTH_PARAM", u"RBS_CABLETRAY_HEIGHT_PARAM"]
    if kind == u"conduit":
        return [u"RBS_CONDUIT_DIAMETER_PARAM"]
    return []


def size_state(element):
    """{parameter: feet} - what keep size puts back after a type change."""
    out = {}
    for name in size_params(element):
        value = _double(element, name)
        if value is not None:
            out[name] = value
    return out


def set_size_state(element, state):
    ok = True
    for name, value in (state or {}).items():
        try:
            element.get_Parameter(bip(name)).Set(value)
        except Exception:
            ok = False
    return ok


def size_of(element):
    """(text, number to sort by) - a pipe by its diameter in mm; ducts and
    containment by cross-section area, so round and rectangular sort together."""
    kind = element_kind(element)
    state = size_state(element)
    if not state:
        return u"", None
    mm = dict((k, core.feet_to_mm(v)) for k, v in state.items())
    if kind == u"pipe":
        d = mm.get(u"RBS_PIPE_DIAMETER_PARAM")
        return core.format_size(d), d
    diameter = mm.get(u"RBS_CURVE_DIAMETER_PARAM") or mm.get(u"RBS_CONDUIT_DIAMETER_PARAM")
    if diameter:
        return core.round_size_text(diameter), 3.14159265 * diameter * diameter / 4.0
    width = mm.get(u"RBS_CURVE_WIDTH_PARAM") or mm.get(u"RBS_CABLETRAY_WIDTH_PARAM")
    height = mm.get(u"RBS_CURVE_HEIGHT_PARAM") or mm.get(u"RBS_CABLETRAY_HEIGHT_PARAM")
    if width and height:
        return core.rect_size_text(width, height), width * height
    return u"", None


def size_label(state):
    mm = [core.format_size(core.feet_to_mm(v)) for _k, v in sorted((state or {}).items())]
    return u"x".join(mm) or u"-"


# ============================================================
# the read
# ============================================================

def run_key(element, settings):
    """What a containment run may not cross: tray to conduit, or one service
    to another."""
    return (element_kind(element), service_of(element, settings))


def walk_run(start, settings, curve_ids=None):
    """([tray/conduit ids], [fitting ids]) joined to start through fittings,
    staying on start's kind and service. A fitting belonging to another
    service is kept as the boundary but not walked through, and a tray or
    conduit of another service or kind is never entered - so a VRF tray teed
    into an ICT tray is not one run. curve_ids, when given, limits which
    trays and conduits count (the read's own list)."""
    key = run_key(start, settings)
    first = eid_value(start.Id)
    seen = set([first])
    curves = [first]
    fittings = []
    queue = [start]
    while queue:
        element = queue.pop()
        for owner in neighbours(element):
            oid = eid_value(owner.Id)
            if oid in seen:
                continue
            seen.add(oid)
            if is_fitting_or_accessory(owner):
                fittings.append(oid)
                service = service_of(owner, settings)
                if service and service != key[1]:
                    continue                    # the boundary: kept, not crossed
                queue.append(owner)
            elif is_curve(owner):
                if curve_ids is not None and oid not in curve_ids:
                    continue
                if run_key(owner, settings) != key:
                    continue
                curves.append(oid)
                queue.append(owner)
    return curves, fittings


def run_labels(doc, curves, settings=None):
    """Containment has no systems, so the System No column shows the run a
    tray or conduit belongs to: everything of the same kind and service
    joined to it through fittings. A run is named after its lowest element
    id, which does not change as the run is edited."""
    ids = set([eid_value(c.Id) for c in curves])
    label = {}
    for curve in curves:
        start = eid_value(curve.Id)
        if start in label:
            continue
        members, _fittings = walk_run(curve, settings or {}, ids)
        name = u"Run {0}".format(min(members))
        for number in members:
            label[number] = name
    return label


def read(doc, settings, view=None, domain=u"pipe"):
    snap = Snapshot()
    group_by = settings.get(u"group_by", u"system_type")
    group_param = settings.get(u"group_param", u"")
    system_from = settings.get(u"system_from", u"")

    type_names = {}
    for cls in type_classes(domain):
        for type_element in FilteredElementCollector(doc).OfClass(cls):
            name = type_label(type_element)
            type_names[eid_value(type_element.Id)] = name
            snap.types.append((name, eid_value(type_element.Id)))
    snap.types.sort(key=lambda t: core.natural_key(t[0]))

    system_type_names = {}
    type_bip = u"RBS_DUCT_SYSTEM_TYPE_PARAM" if domain == u"duct" else \
        u"RBS_PIPING_SYSTEM_TYPE_PARAM"
    health = Health(doc, domain, settings)
    curves = collect_curves(doc, domain, view)
    runs = run_labels(doc, curves, settings) if domain == u"cont" and not system_from else {}
    for curve in curves:
        record = {u"id": eid_value(curve.Id), u"kind": element_kind(curve)}

        if domain == u"cont":
            service = service_of(curve, settings)
            record[u"system_type"] = builtin_text(curve, u"RBS_CTC_SERVICE_TYPE").strip()
            record[u"system_id"] = 0
            record[u"has_system"] = bool(service)
            if system_from:
                record[u"system"] = param_text(curve, system_from)
            else:
                record[u"system"] = runs.get(record[u"id"], u"")
        else:
            system = None
            try:
                system = curve.MEPSystem
            except Exception:
                system = None
            record[u"system_id"] = eid_value(system.Id) if system is not None else 0
            if system_from:
                record[u"system"] = param_text(curve, system_from)
            else:
                record[u"system"] = elem_name(system) if system is not None else u""
                if not record[u"system"]:
                    record[u"system"] = builtin_text(curve, u"RBS_SYSTEM_NAME_PARAM")
            type_label_text = u""
            member = bip(type_bip)
            try:
                p = curve.get_Parameter(member) if member is not None else None
                if p is not None:
                    sid = p.AsElementId()
                    key = eid_value(sid)
                    if key > 0:
                        if key not in system_type_names:
                            system_type_names[key] = elem_name(doc.GetElement(sid))
                        type_label_text = system_type_names[key]
            except Exception:
                pass
            record[u"system_type"] = type_label_text
            record[u"classification"] = builtin_text(curve, u"RBS_SYSTEM_CLASSIFICATION_PARAM")

        if group_by == u"param" and group_param:
            text = param_text(curve, group_param)
            if not text:
                try:
                    text = param_text(doc.GetElement(curve.GetTypeId()), group_param)
                except Exception:
                    text = u""
            record[u"group_param"] = text

        record[u"ptype"] = type_names.get(eid_value(curve.GetTypeId()), u"")
        text, number = size_of(curve)
        record[u"size_text"] = text
        record[u"size_num"] = number
        if domain == u"pipe" and number is not None:
            record[u"size_mm"] = number
        try:
            record[u"length_ft"] = curve.Location.Curve.Length
        except Exception:
            record[u"length_ft"] = 0.0
        health.read(curve, record)
        snap.records.append(record)

    snap.views_3d = read_views(doc)

    snap.param_names, snap.all_param_names = parameter_names(doc, curves, domain)
    return snap


def read_views(doc):
    """Every 3D view that is not a template, by name."""
    out = []
    for v in FilteredElementCollector(doc).OfClass(View3D):
        try:
            if v.IsTemplate:
                continue
        except Exception:
            continue
        out.append((elem_name(v), eid_value(v.Id)))
    out.sort(key=lambda t: core.natural_key(t[0]))
    return out


def parameter_names(doc, pipes, domain=u"pipe", sample=150):
    """Writable instance parameters on the tab's elements and their fittings
    (what can be retained), plus every parameter they carry (what can group)."""
    writable = set()
    everything = set()
    storage_none = getattr(StorageType, u"None", None)
    samples = list(pipes[:sample])
    for name in FITTING_CATEGORIES.get(domain, ()):
        try:
            fitting_cat = bic(name)
            if fitting_cat is not None:
                fittings = FilteredElementCollector(doc).OfCategory(fitting_cat) \
                    .WhereElementIsNotElementType().ToElements()
                samples.extend(list(fittings)[:sample])
        except Exception:
            pass
    for element in samples:
        try:
            for p in element.Parameters:
                try:
                    name = p.Definition.Name
                except Exception:
                    continue
                if not name:
                    continue
                everything.add(name)
                try:
                    if not p.IsReadOnly and p.StorageType != storage_none:
                        writable.add(name)
                except Exception:
                    pass
        except Exception:
            pass
    for pipe in pipes[:20]:
        try:
            ptype = doc.GetElement(pipe.GetTypeId())
            for p in ptype.Parameters:
                try:
                    everything.add(p.Definition.Name)
                except Exception:
                    pass
        except Exception:
            pass
    return (sorted(writable, key=core.natural_key),
            sorted(everything, key=core.natural_key))


# ============================================================
# connectivity
# ============================================================

def connectors_of(element):
    """ConnectorManager lives on the element for MEP curves and on MEPModel
    for family instances - reading only one of them truncates a walk."""
    manager = None
    try:
        manager = element.ConnectorManager
    except Exception:
        manager = None
    if manager is None:
        try:
            manager = element.MEPModel.ConnectorManager
        except Exception:
            manager = None
    if manager is None:
        return []
    try:
        return list(manager.Connectors)
    except Exception:
        return []


def neighbours(element):
    """Elements joined to this one through its connectors, one hop."""
    out = []
    own = eid_value(element.Id)
    for connector in connectors_of(element):
        try:
            if not connector.IsConnected:
                continue
            for ref in connector.AllRefs:
                try:
                    owner = ref.Owner
                    oid = eid_value(owner.Id)
                    if oid != own and oid not in [eid_value(o.Id) for o in out]:
                        out.append(owner)
                except Exception:
                    pass
        except Exception:
            pass
    return out


def connected_count(element):
    total = 0
    for connector in connectors_of(element):
        try:
            if connector.IsConnected:
                total += 1
        except Exception:
            pass
    return total


FITTING_CATEGORIES = {
    u"pipe": (u"OST_PipeFitting",),
    u"duct": (u"OST_DuctFitting",),
    u"cont": (u"OST_CableTrayFitting", u"OST_ConduitFitting"),
}
ACCESSORY_CATEGORIES = (u"OST_PipeAccessory", u"OST_DuctAccessory")


def _category_numbers(names):
    out = []
    for name in names:
        member = bic(name)
        if member is not None:
            try:
                out.append(int(member))
            except Exception:
                pass
    return out


def is_curve(element):
    """A pipe, duct, cable tray or conduit - the rows of every tab."""
    try:
        return isinstance(element, MEPCurve)
    except Exception:
        return False


is_pipe = is_curve


def is_fitting(element):
    try:
        if not isinstance(element, FamilyInstance) or element.Category is None:
            return False
        names = []
        for group in FITTING_CATEGORIES.values():
            names.extend(group)
        return eid_value(element.Category.Id) in _category_numbers(names)
    except Exception:
        return False


def is_fitting_or_accessory(element):
    try:
        if not isinstance(element, FamilyInstance) or element.Category is None:
            return False
        names = list(ACCESSORY_CATEGORIES)
        for group in FITTING_CATEGORIES.values():
            names.extend(group)
        return eid_value(element.Category.Id) in _category_numbers(names)
    except Exception:
        return False


def whole_system_ids(doc, pipe_ids, domain=u"pipe", settings=None):
    """Every element on the systems the given elements belong to - the piping
    or duct network, or for containment the whole run."""
    if domain == u"cont":
        return whole_run_ids(doc, pipe_ids, settings)
    out = set(pipe_ids)
    seen_systems = set()
    for number in pipe_ids:
        try:
            pipe = doc.GetElement(make_id(number))
            system = pipe.MEPSystem
            if system is None:
                continue
            sid = eid_value(system.Id)
            if sid in seen_systems:
                continue
            seen_systems.add(sid)
            network = None
            for name in (u"PipingNetwork", u"DuctNetwork", u"Elements"):
                try:
                    network = getattr(system, name)
                    if network is not None:
                        break
                except Exception:
                    network = None
            for element in network or []:
                out.add(eid_value(element.Id))
        except Exception:
            pass
    return sorted(out)


def whole_run_ids(doc, ids, settings=None):
    """Every tray, conduit and fitting on the runs of these - the same walk
    that names the Run column, so a run isolated or resized is exactly the
    run the table shows."""
    out = set()
    for number in ids:
        if number in out:
            continue
        element = doc.GetElement(make_id(number))
        if element is None:
            continue
        if not is_curve(element):
            out.add(number)
            continue
        curves, fittings = walk_run(element, settings or {})
        out.update(curves)
        out.update(fittings)
    return sorted(out)


def with_connected_fittings(doc, pipe_ids):
    out = set(pipe_ids)
    for number in pipe_ids:
        try:
            pipe = doc.GetElement(make_id(number))
            for owner in neighbours(pipe):
                if is_fitting_or_accessory(owner):
                    out.add(eid_value(owner.Id))
        except Exception:
            pass
    return sorted(out)


# ============================================================
# isolating only what is on the picked systems
# ============================================================

def category_number(element):
    try:
        return eid_value(element.Category.Id)
    except Exception:
        return None


def isolate_category_numbers(domain=u"pipe"):
    out = set()
    for name in core.isolate_categories(domain):
        member = bic(name)
        if member is not None:
            try:
                out.add(int(member))
            except Exception:
                pass
    return out


def membership(element, domain, settings):
    """What an element belongs to, for isolating and for the fitting check:
    its system ids, or for containment its service type."""
    if domain == u"cont":
        service = service_of(element, settings)
        return set([service]) if service else set()
    return system_ids_of(element)


def system_ids_of(element):
    """The piping systems an element is on. A pipe answers directly; a
    fitting or accessory answers through each of its connectors, so one
    sitting between two systems reports both."""
    out = set()
    try:
        system = element.MEPSystem
        if system is not None:
            out.add(eid_value(system.Id))
    except Exception:
        pass
    for connector in connectors_of(element):
        try:
            system = connector.MEPSystem
            if system is not None:
                out.add(eid_value(system.Id))
        except Exception:
            pass
    out.discard(0)
    return out


def insulation_ids(doc, numbers):
    """Pipe insulation hosted on the given elements - without it an isolated
    run shows bare pipe."""
    out = set()
    for number in numbers:
        for getter in (u"GetInsulationIds", u"GetLiningIds"):
            try:
                for iid in getattr(InsulationLiningBase, getter)(doc, make_id(number)):
                    out.add(eid_value(iid))
            except Exception:
                pass
    out.discard(0)
    return out


def isolate_ids(doc, pipe_ids, what, domain=u"pipe", settings=None):
    """(kept ids, {category name: count dropped}). The walk finds candidates
    as before; core.keep_for_isolate then drops anything that is not
    pipework on one of the picked pipes' own systems."""
    if what == u"systems":
        found = whole_system_ids(doc, pipe_ids, domain, settings)
    elif what == u"fittings":
        found = with_connected_fittings(doc, pipe_ids)
    else:
        found = list(pipe_ids)
    picked = set(pipe_ids)
    wanted_systems = set()
    for number in pipe_ids:
        try:
            wanted_systems |= membership(doc.GetElement(make_id(number)), domain, settings)
        except Exception:
            pass
    allowed = isolate_category_numbers(domain)
    kept = []
    dropped = {}
    for number in found:
        element = doc.GetElement(make_id(number))
        if element is None:
            continue
        touches = False
        if number not in picked:
            try:
                touches = any([eid_value(n.Id) in picked for n in neighbours(element)])
            except Exception:
                touches = False
        if core.keep_for_isolate(number in picked, category_number(element) in allowed,
                                 membership(element, domain, settings), wanted_systems,
                                 touches):
            kept.append(number)
        else:
            label = u"?"
            try:
                label = element.Category.Name
            except Exception:
                pass
            dropped[label] = dropped.get(label, 0) + 1
    extra = insulation_ids(doc, kept)
    return sorted(set(kept) | extra), dropped


def section_box_id(doc, view):
    """The section box of a 3D view is an element of its own. A temporary
    isolate hides it like anything else unless it is in the list, so it has
    to be found and added. The view owns it, so it is one of the view's
    dependents; a view-bound collector is the fallback."""
    member = bic(u"OST_SectionBox")
    if member is None:
        return None
    try:
        for eid in view.GetDependentElements(ElementCategoryFilter(member)):
            if eid_value(eid) > 0:
                return eid_value(eid)
    except Exception:
        pass
    try:
        collector = FilteredElementCollector(doc, view.Id).OfCategory(member)
        for eid in collector.ToElementIds():
            return eid_value(eid)
    except Exception:
        pass
    return None


# ============================================================
# finding a fitting again after a type change
# ============================================================

def point_of(element):
    try:
        p = element.Location.Point
        return (p.X, p.Y, p.Z)
    except Exception:
        pass
    try:
        box = element.get_BoundingBox(None)
        return ((box.Min.X + box.Max.X) / 2.0, (box.Min.Y + box.Max.Y) / 2.0,
                (box.Min.Z + box.Max.Z) / 2.0)
    except Exception:
        return None


def is_live(element):
    if element is None:
        return False
    try:
        return bool(element.IsValidObject)
    except Exception:
        return True


# ============================================================
# health checks, read with the pipes
# ============================================================

SIZE_TOLERANCE_FT = core.mm_to_feet(0.5)


class Health(object):
    """Per element: open ends, fittings on another system (containment:
    another service), the fittings joined to it, and whether its size is one
    the project offers - a pipe type's routing preference segments, or the
    duct sizes set for its shape. Containment has no size list to check.
    Fitting membership and size lists are cached - the same fitting joins two
    elements and the same type covers hundreds."""

    def __init__(self, doc, domain=u"pipe", settings=None):
        self.doc = doc
        self.domain = domain
        self.settings = settings or {}
        self.fitting_systems = {}
        self.type_sizes = {}
        self.duct_size_lists = {}

    def own_membership(self, curve, record):
        if self.domain == u"cont":
            return membership(curve, self.domain, self.settings)
        own = record.get(u"system_id") or 0
        return set([own]) if own else set()

    def read(self, pipe, record):
        record[u"open_ends"] = self.open_ends(pipe)
        fittings = []
        mismatch = 0
        own = self.own_membership(pipe, record)
        for owner in neighbours(pipe):
            if not is_fitting_or_accessory(owner):
                continue
            oid = eid_value(owner.Id)
            fittings.append(oid)
            if own:
                systems = self.systems_of_fitting(owner, oid)
                if systems and not (own & systems):
                    mismatch += 1
        record[u"fittings"] = fittings
        record[u"mismatch"] = mismatch
        record[u"size_ok"] = self.size_ok(pipe)

    def open_ends(self, pipe):
        """End connectors joined to nothing. A branch tap's curve connector
        is not an end, so it is not counted."""
        count = 0
        for connector in connectors_of(pipe):
            try:
                if u"{0}".format(connector.ConnectorType) != u"End":
                    continue
                if not connector.IsConnected:
                    count += 1
            except Exception:
                pass
        return count

    def systems_of_fitting(self, fitting, oid):
        if oid not in self.fitting_systems:
            self.fitting_systems[oid] = membership(fitting, self.domain, self.settings)
        return self.fitting_systems[oid]

    def duct_sizes(self, shape_name):
        """The duct sizes the project offers for a shape, in feet; None if
        they cannot be read."""
        if shape_name in self.duct_size_lists:
            return self.duct_size_lists[shape_name]
        sizes = None
        try:
            table = DuctSizeSettings.GetDuctSizeSettings(self.doc)
            shape = getattr(DuctShape, shape_name)
            found = [size.NominalDiameter for size in table[shape]]
            if found:
                sizes = found
        except Exception:
            sizes = None
        self.duct_size_lists[shape_name] = sizes
        return sizes

    def duct_size_ok(self, duct):
        state = size_state(duct)
        if not state:
            return None
        if u"RBS_CURVE_DIAMETER_PARAM" in state:
            shape = u"Round"
        else:
            shape = u"Rectangular"
            for connector in connectors_of(duct):
                try:
                    if u"{0}".format(connector.Shape) == u"Oval":
                        shape = u"Oval"
                except Exception:
                    pass
                break
        sizes = self.duct_sizes(shape)
        if not sizes:
            return None
        for value in state.values():
            if not [s for s in sizes if abs(s - value) <= SIZE_TOLERANCE_FT]:
                return False
        return True

    def sizes_for(self, type_id):
        """Every nominal size the pipe type's routing preference segments
        offer, in feet; None when they cannot be read, so nothing is flagged
        on a guess."""
        key = eid_value(type_id)
        if key in self.type_sizes:
            return self.type_sizes[key]
        sizes = None
        try:
            pipe_type = self.doc.GetElement(type_id)
            manager = pipe_type.RoutingPreferenceManager
            group = getattr(RoutingPreferenceRuleGroupType, u"Segments", None)
            found = []
            for index in range(manager.GetNumberOfRules(group)):
                rule = manager.GetRule(group, index)
                segment = self.doc.GetElement(rule.MEPPartId)
                if segment is None:
                    continue
                for size in segment.GetSizes():
                    found.append(size.NominalDiameter)
            if found:
                sizes = found
        except Exception:
            sizes = None
        self.type_sizes[key] = sizes
        return sizes

    def size_ok(self, pipe):
        if self.domain == u"cont":
            return None
        if self.domain == u"duct":
            return self.duct_size_ok(pipe)
        try:
            sizes = self.sizes_for(pipe.GetTypeId())
            if not sizes:
                return None
            diameter = pipe.Diameter
            for size in sizes:
                if abs(size - diameter) <= SIZE_TOLERANCE_FT:
                    return True
            return False
        except Exception:
            return None


# ============================================================
# containment fitting slots
# ============================================================

def fitting_slots(type_element):
    """{parameter name: fitting type id} for a cable tray or conduit type.
    Found, not hardcoded: every ElementId parameter on the type that points
    at a family type in a fitting category is a slot. Non-standard slots and
    releases that rename the built-in ones are both covered."""
    out = {}
    if type_element is None:
        return out
    storage_id = getattr(StorageType, u"ElementId", None)
    wanted = []
    for names in FITTING_CATEGORIES.values():
        wanted.extend(_category_numbers(names))
    try:
        doc = type_element.Document
        parameters = list(type_element.Parameters)
    except Exception:
        return out
    for p in parameters:
        try:
            if p.StorageType != storage_id:
                continue
            number = eid_value(p.AsElementId())
            if number <= 0:
                continue
            target = doc.GetElement(p.AsElementId())
            if not isinstance(target, FamilySymbol):
                continue
            if category_number(target) not in wanted:
                continue
            out[p.Definition.Name] = number
        except Exception:
            pass
    return out


# ============================================================
# the Workset Assigner: every system, and the worksets it sits on
# ============================================================

# what a system's workset is set on: the pipework itself, not the equipment
# or fixtures a system runs through, and not insulation, which follows its host
WORKSET_CATEGORIES = {
    u"pipe": (u"OST_PipeCurves", u"OST_PipeFitting", u"OST_PipeAccessory",
              u"OST_FlexPipeCurves"),
    u"duct": (u"OST_DuctCurves", u"OST_DuctFitting", u"OST_DuctAccessory",
              u"OST_FlexDuctCurves"),
    u"cont": (u"OST_CableTray", u"OST_Conduit", u"OST_CableTrayFitting",
              u"OST_ConduitFitting"),
}


def workset_number(workset_id):
    """WorksetId keeps IntegerValue (only ElementId lost it), but go
    carefully all the same."""
    for name in (u"IntegerValue", u"Value"):
        try:
            return int(getattr(workset_id, name))
        except Exception:
            pass
    return -1


def read_workset_names(doc):
    out = []
    try:
        collector = FilteredWorksetCollector(doc).OfKind(WorksetKind.UserWorkset)
        for workset in collector:
            out.append((workset.Name, workset_number(workset.Id)))
    except Exception:
        pass
    out.sort(key=lambda t: core.natural_key(t[0]))
    return out


def _tally(elements, wanted):
    """([ids], {workset number: count}) for the elements in the wanted
    categories."""
    ids = []
    worksets = {}
    for element in elements:
        try:
            if category_number(element) not in wanted:
                continue
            ids.append(eid_value(element.Id))
            key = workset_number(element.WorksetId)
            worksets[key] = worksets.get(key, 0) + 1
        except Exception:
            pass
    return ids, worksets


def _network_systems(doc, cls, discipline, network_names):
    wanted = set(_category_numbers(WORKSET_CATEGORIES[discipline]))
    out = []
    for system in FilteredElementCollector(doc).OfClass(cls):
        network = None
        for name in network_names:
            try:
                network = getattr(system, name)
                if network is not None:
                    break
            except Exception:
                network = None
        ids, worksets = _tally(list(network or []), wanted)
        if not ids:
            continue
        type_name = u""
        try:
            type_name = elem_name(doc.GetElement(system.GetTypeId()))
        except Exception:
            pass
        out.append({u"key": u"{0}:{1}".format(discipline, eid_value(system.Id)),
                    u"discipline": discipline, u"type": type_name,
                    u"name": elem_name(system), u"ids": ids, u"worksets": worksets})
    return out


def _containment_systems(doc, settings):
    """Containment has no systems: a run of one service stands in for one,
    under its service type - the same runs the Containment tab shows."""
    wanted = set(_category_numbers(WORKSET_CATEGORIES[u"cont"]))
    curves = collect_curves(doc, u"cont")
    ids = set([eid_value(c.Id) for c in curves])
    done = set()
    out = []
    for curve in curves:
        start = eid_value(curve.Id)
        if start in done:
            continue
        members, fittings = walk_run(curve, settings, ids)
        done.update(members)
        service = service_of(curve, settings)
        # a fitting of another service is this run's edge, not part of it
        own = []
        for number in fittings:
            fitting = doc.GetElement(make_id(number))
            other = service_of(fitting, settings) if fitting is not None else u""
            if not other or other == service:
                own.append(fitting)
        elements = [doc.GetElement(make_id(n)) for n in members] + own
        run_ids, worksets = _tally([e for e in elements if e is not None], wanted)
        if run_ids:
            out.append({u"key": u"cont:{0}".format(min(members)), u"discipline": u"cont",
                        u"type": service, u"name": u"Run {0}".format(min(members)),
                        u"ids": run_ids, u"worksets": worksets})
    return out


def read_worksets(doc, cont_settings):
    """A Snapshot for the Workset Assigner: .systems of all three disciplines
    and .worksets [(name, number)]; .workshared False if there are none."""
    snap = Snapshot()
    try:
        snap.workshared = bool(doc.IsWorkshared)
    except Exception:
        snap.workshared = False
    snap.views_3d = read_views(doc)
    snap.systems = []
    snap.worksets = []
    if not snap.workshared:
        return snap
    snap.worksets = read_workset_names(doc)
    snap.systems.extend(_network_systems(doc, PipingSystem, u"pipe", (u"PipingNetwork",)))
    snap.systems.extend(_network_systems(doc, MechanicalSystem, u"duct", (u"DuctNetwork",)))
    snap.systems.extend(_containment_systems(doc, cont_settings))
    return snap


# ============================================================
# Pick System: which tab a picked element belongs to
# ============================================================

DOMAIN_CATEGORIES = {
    u"pipe": (u"OST_PipeCurves", u"OST_PipeFitting", u"OST_PipeAccessory", u"OST_FlexPipeCurves"),
    u"duct": (u"OST_DuctCurves", u"OST_DuctFitting", u"OST_DuctAccessory", u"OST_FlexDuctCurves"),
    u"cont": (u"OST_CableTray", u"OST_Conduit", u"OST_CableTrayFitting", u"OST_ConduitFitting"),
}


def domain_of(element):
    """pipe / duct / cont for anything on a system, else ''."""
    kind = element_kind(element)
    if kind in core.KIND_DOMAIN:
        return core.KIND_DOMAIN[kind]
    number = category_number(element)
    for domain, names in DOMAIN_CATEGORIES.items():
        if number in _category_numbers(names):
            return domain
    return u""


# ============================================================
# Change Pipe Type: sizes offered, and groups
# ============================================================

def type_sizes(doc, type_id):
    """Every nominal size a pipe type's routing preferences offer, in mm,
    smallest first - [] if they cannot be read."""
    try:
        feet = Health(doc).sizes_for(make_id(type_id)) or []
    except Exception:
        feet = []
    return sorted(set([round(core.feet_to_mm(f), 1) for f in feet]))


def group_of(doc, element):
    """(the group an element is in or None, instances of that group's type,
    nested inside another group)."""
    try:
        gid = element.GroupId
        if gid is None or eid_value(gid) <= 0:
            return None, 0, False
        group = doc.GetElement(gid)
        if group is None:
            return None, 0, False
        instances = 1
        try:
            instances = len(list(group.GroupType.Groups))
        except Exception:
            pass
        nested = False
        try:
            nested = eid_value(group.GroupId) > 0
        except Exception:
            nested = False
        return group, instances, nested
    except Exception:
        return None, 0, False


def _xyz(point):
    return (point.X, point.Y, point.Z)


def group_members(group):
    try:
        return [eid_value(i) for i in group.GetMemberIds()]
    except Exception:
        return []


def mid_point(element):
    """The middle of a pipe's centreline, as (x, y, z) in feet."""
    try:
        curve = element.Location.Curve
        return _xyz(curve.Evaluate(0.5, True))
    except Exception:
        return None


def extents(element):
    """((min), (max)) of an element's bounding box in the model, or None."""
    try:
        box = element.get_BoundingBox(None)
        return _xyz(box.Min), _xyz(box.Max)
    except Exception:
        return None
