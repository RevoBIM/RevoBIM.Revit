# -*- coding: utf-8 -*-
"""Schematic Builder - everything read out of the model.

``read_project`` takes one pass at open (and on Refresh) and hands the
windows a plain-Python snapshot. The per-instance lookups (level, room,
marks) run inside the ExternalEvent when Create is pressed.
"""
import sb_clr  # noqa: F401

import traceback

from sb_logic import as_text, natural_key, room_key_of, link_id_of
from sb_core import (eid_value, bic, bip, el_name, category_name, find_param,
                     param_text, builtin_text, type_builtin_text, ft_to_mm, make_id)

from Autodesk.Revit.DB import (  # noqa: E402
    FilteredElementCollector, FamilyInstance, FamilySymbol, Level, TextNoteType,
    GraphicsStyleType, View, ViewFamilyType, ViewFamily, RevitLinkInstance,
    StorageType, ElementId, XYZ, LocationPoint, LocationCurve, ElementCategoryFilter,
)
from Autodesk.Revit.DB.Architecture import Room  # noqa: E402,F401
from Autodesk.Revit.DB.Electrical import PanelScheduleView, ElectricalSystem  # noqa: E402


# ---------------------------------------------------------------------------
# LEVELS
# ---------------------------------------------------------------------------

def read_levels(doc):
    """[{'id': int, 'name': text, 'elev': ft}] sorted low to high."""
    levels = []
    try:
        for level in FilteredElementCollector(doc).OfClass(Level).WhereElementIsNotElementType():
            levels.append({"id": eid_value(level.Id), "name": el_name(level),
                           "elev": level.Elevation, "elev_mm": ft_to_mm(level.Elevation)})
    except Exception:
        pass
    levels.sort(key=lambda l: l["elev"])
    return levels


# ---------------------------------------------------------------------------
# LINE STYLES / TEXT TYPES
# ---------------------------------------------------------------------------

def read_line_styles(doc):
    """{name: GraphicsStyle} for every line style (subcategory of Lines)."""
    styles = {}
    try:
        lines_cat = doc.Settings.Categories.get_Item(bic("OST_Lines"))
        for sub in lines_cat.SubCategories:
            style = sub.GetGraphicsStyle(GraphicsStyleType.Projection)
            if style is not None:
                styles[as_text(sub.Name)] = style
    except Exception:
        pass
    return styles


def read_text_types(doc):
    """{name: TextNoteType}."""
    types = {}
    try:
        for tnt in FilteredElementCollector(doc).OfClass(TextNoteType):
            types[el_name(tnt)] = tnt
    except Exception:
        pass
    return types


def text_size_mm(text_type):
    """Text height of a TextNoteType in paper mm (2.5 if unreadable)."""
    try:
        size = text_type.get_Parameter(bip("TEXT_SIZE")).AsDouble()
        return ft_to_mm(size)
    except Exception:
        return 2.5


def text_width_factor(text_type):
    try:
        return text_type.get_Parameter(bip("TEXT_WIDTH_SCALE")).AsDouble() or 1.0
    except Exception:
        return 1.0


# ---------------------------------------------------------------------------
# LINKS AND ROOMS
# ---------------------------------------------------------------------------

def read_links(doc):
    """[(link_doc, title, inverse_transform)] for every loaded link."""
    links = []
    try:
        for link in FilteredElementCollector(doc).OfClass(RevitLinkInstance):
            link_doc = link.GetLinkDocument()
            if link_doc is None:
                continue
            try:
                inverse = link.GetTotalTransform().Inverse
            except Exception:
                inverse = None
            links.append((link_doc, as_text(link_doc.Title), inverse))
    except Exception:
        pass
    return links


def sample_room(doc, links):
    """The first room found, host first then links - used to list room parameters."""
    for source in [doc] + [l[0] for l in links]:
        try:
            for room in FilteredElementCollector(source).OfCategory(bic("OST_Rooms")) \
                    .WhereElementIsNotElementType():
                return room
        except Exception:
            continue
    return None


def read_room_params(doc, links):
    names = set([u"Name", u"Number"])
    room = sample_room(doc, links)
    if room is not None:
        try:
            for param in room.Parameters:
                try:
                    if param.StorageType == StorageType.String:
                        names.add(as_text(param.Definition.Name))
                except Exception:
                    continue
        except Exception:
            pass
    return sorted(names, key=lambda n: n.lower())


def last_phase(doc):
    try:
        phases = doc.Phases
        return phases.get_Item(phases.Size - 1)
    except Exception:
        return None


def room_label(room, param_name):
    if room is None:
        return u""
    text = None
    if param_name:
        text = param_text(find_param(room, param_name, False))
    if not text:
        text = builtin_text(room, "ROOM_NAME")
    if not text:
        text = builtin_text(room, "ROOM_NUMBER")
    return as_text(text).strip()


def find_room(doc, links, point, phase):
    """(room, doc_title) for the point: the host model first, then every link."""
    if point is None:
        return None, u""
    try:
        room = doc.GetRoomAtPoint(point, phase) if phase is not None else doc.GetRoomAtPoint(point)
        if room is not None:
            return room, as_text(doc.Title)
    except Exception:
        pass
    for link_doc, title, inverse in links:
        try:
            local = inverse.OfPoint(point) if inverse is not None else point
            room = link_doc.GetRoomAtPoint(local)
            if room is not None:
                return room, title
        except Exception:
            continue
    return None, u""


# ---------------------------------------------------------------------------
# FAMILIES IN THE PROJECT
# ---------------------------------------------------------------------------

def _symbol_rows(doc, category_id=None, model_only=True):
    """Count placed instances per FamilySymbol.
    Returns {type_int: {'category','family','type','count','type_id'}}."""
    rows = {}
    try:
        collector = FilteredElementCollector(doc).OfClass(FamilyInstance).WhereElementIsNotElementType()
        if category_id is not None:
            collector = collector.WherePasses(ElementCategoryFilter(category_id))
        for inst in collector:
            try:
                symbol = inst.Symbol
                if symbol is None:
                    continue
                if model_only:
                    if inst.ViewSpecific:
                        continue
                    cat = inst.Category
                    if cat is None:
                        continue
                key = eid_value(symbol.Id)
                row = rows.get(key)
                if row is None:
                    row = {"category": category_name(inst), "family": as_text(symbol.FamilyName),
                           "type": el_name(symbol), "count": 0, "type_id": symbol.Id}
                    rows[key] = row
                row["count"] += 1
            except Exception:
                continue
    except Exception:
        pass
    return rows


def read_model_families(doc):
    """Every loadable family type with placed model instances, plus a
    family-level '(all types)' row per family."""
    rows = _symbol_rows(doc, None, True)
    out = []
    by_family = {}
    for key in rows:
        row = rows[key]
        out.append(dict(row))
        fam_key = (row["category"], row["family"])
        entry = by_family.get(fam_key)
        if entry is None:
            entry = {"category": row["category"], "family": row["family"], "type": u"*",
                     "count": 0, "type_id": None}
            by_family[fam_key] = entry
        entry["count"] += row["count"]
    out.extend(by_family.values())
    out.sort(key=lambda r: (r["category"].lower(), r["family"].lower(),
                            0 if r["type"] == u"*" else 1, natural_key(r["type"])))
    return out


def read_detail_items(doc):
    """Every Detail Item family type loaded, with how many are placed."""
    used = _symbol_rows(doc, bic("OST_DetailComponents"), False)
    out = []
    try:
        collector = FilteredElementCollector(doc).OfClass(FamilySymbol) \
            .OfCategory(bic("OST_DetailComponents")).WhereElementIsElementType()
        for symbol in collector:
            key = eid_value(symbol.Id)
            count = used[key]["count"] if key in used else 0
            out.append({"category": category_name(symbol) or u"Detail Items",
                        "family": as_text(symbol.FamilyName), "type": el_name(symbol),
                        "count": count, "type_id": symbol.Id})
    except Exception:
        pass
    out.sort(key=lambda r: (r["family"].lower(), natural_key(r["type"])))
    return out


def collect_instances(doc, family, type_name):
    """Placed model instances of a family (type '*' = every type)."""
    found = []
    try:
        for inst in FilteredElementCollector(doc).OfClass(FamilyInstance).WhereElementIsNotElementType():
            try:
                if inst.ViewSpecific:
                    continue
                symbol = inst.Symbol
                if symbol is None or as_text(symbol.FamilyName) != family:
                    continue
                if type_name != u"*" and el_name(symbol) != type_name:
                    continue
                found.append(inst)
            except Exception:
                continue
    except Exception:
        pass
    return found


def param_names_of(element, kinds=None):
    """Writable-looking parameter names on one element."""
    names = set()
    if element is None:
        return names
    wanted = kinds or (StorageType.String, StorageType.Integer, StorageType.Double,
                       StorageType.ElementId)
    try:
        for param in element.Parameters:
            try:
                if param.StorageType in wanted:
                    names.add(as_text(param.Definition.Name))
            except Exception:
                continue
    except Exception:
        pass
    return names


def binding_param_names(doc, category_ids):
    """Every project or shared parameter bound to any of these categories.

    This is what makes the drop-down show the whole category rather than
    whatever happened to be on the handful of elements that were sampled."""
    names = set()
    wanted = set([int(c) for c in category_ids])
    if not wanted:
        return names
    try:
        iterator = doc.ParameterBindings.ForwardIterator()
        iterator.Reset()
        while iterator.MoveNext():
            try:
                definition = iterator.Key
                binding = iterator.Current
                for category in binding.Categories:
                    if eid_value(category.Id) in wanted:
                        names.add(as_text(definition.Name))
                        break
            except Exception:
                continue
    except Exception:
        pass
    return names


def category_ids_of(elements):
    ids = set()
    for element in elements:
        try:
            ids.add(eid_value(element.Category.Id))
        except Exception:
            continue
    return ids


def params_by_category(doc, sample=True):
    """{category name: sorted parameter names} for every category that has
    parameters bound to it, plus whatever is on one sampled instance of each
    category actually placed in the model.

    This is what the template editor's category dropdown offers, so choosing
    a category narrows the parameter list to that category's own."""
    by_id = {}
    names_by_id = {}
    try:
        iterator = doc.ParameterBindings.ForwardIterator()
        iterator.Reset()
        while iterator.MoveNext():
            try:
                definition = iterator.Key
                binding = iterator.Current
                for category in binding.Categories:
                    key = eid_value(category.Id)
                    by_id[key] = as_text(category.Name)
                    names_by_id.setdefault(key, set()).add(as_text(definition.Name))
            except Exception:
                continue
    except Exception:
        pass
    if sample:
        seen = set()
        try:
            for inst in FilteredElementCollector(doc).OfClass(FamilyInstance) \
                    .WhereElementIsNotElementType():
                try:
                    key = eid_value(inst.Category.Id)
                except Exception:
                    continue
                if key in seen:
                    continue
                seen.add(key)
                by_id[key] = category_name(inst)
                bucket = names_by_id.setdefault(key, set())
                bucket |= param_names_of(inst)
                try:
                    bucket |= param_names_of(doc.GetElement(inst.GetTypeId()))
                except Exception:
                    pass
        except Exception:
            pass
    out = {}
    for key in names_by_id:
        name = by_id.get(key) or u"Category {0}".format(key)
        out.setdefault(name, set())
        out[name] |= names_by_id[key]
    result = {}
    for name in out:
        result[name] = sorted(out[name], key=lambda n: n.lower())
    return result


def dimension_params(doc, family, type_name):
    """The length parameters of a detail item type, for stretching it.

    Instance parameters first (those can be set per item); a type parameter
    is offered too but flagged, since changing it moves every item of the
    type."""
    instance_names = set()
    type_names = set()
    try:
        for symbol in FilteredElementCollector(doc).OfClass(FamilySymbol) \
                .OfCategory(bic("OST_DetailComponents")).WhereElementIsElementType():
            if as_text(symbol.FamilyName) != family or el_name(symbol) != type_name:
                continue
            type_names |= param_names_of(symbol, (StorageType.Double,))
            symbol_id = eid_value(symbol.Id)
            try:
                for inst in FilteredElementCollector(doc).OfClass(FamilyInstance) \
                        .OfCategory(bic("OST_DetailComponents")).WhereElementIsNotElementType():
                    if eid_value(inst.GetTypeId()) == symbol_id:
                        instance_names |= param_names_of(inst, (StorageType.Double,))
                        break
            except Exception:
                pass
            break
    except Exception:
        pass
    return (sorted(instance_names, key=lambda n: n.lower()),
            sorted(type_names, key=lambda n: n.lower()))


def first_instances(doc, pairs, per_pair=1):
    """One pass over the model for the first instance of each (family, type)."""
    wanted = {}
    for family, type_name in pairs:
        wanted[(family, type_name)] = []
    found = []
    if not wanted:
        return found
    try:
        for inst in FilteredElementCollector(doc).OfClass(FamilyInstance).WhereElementIsNotElementType():
            try:
                if inst.ViewSpecific:
                    continue
                symbol = inst.Symbol
                if symbol is None:
                    continue
                family = as_text(symbol.FamilyName)
                type_name = el_name(symbol)
                for key in ((family, type_name), (family, u"*")):
                    if key in wanted and len(wanted[key]) < per_pair:
                        wanted[key].append(inst)
                        found.append(inst)
            except Exception:
                continue
    except Exception:
        pass
    return found


def family_param_names(doc, pairs):
    """(instance names, type names) across the families paired on a row,
    plus everything bound to their categories."""
    instance_names = set()
    type_names = set()
    sampled = first_instances(doc, pairs)
    for inst in sampled:
        instance_names |= param_names_of(inst)
        try:
            type_names |= param_names_of(doc.GetElement(inst.GetTypeId()))
        except Exception:
            pass
    instance_names |= binding_param_names(doc, category_ids_of(sampled))
    return (sorted(instance_names, key=lambda n: n.lower()),
            sorted(type_names, key=lambda n: n.lower()))


def detail_param_names(doc, family, type_name):
    """(instance names, type names, sampled) for a detail item type.

    Instance parameters can only be read off a placed instance, so where none
    is placed yet only the type parameters are known and 'sampled' is False."""
    instance_names = set()
    type_names = set()
    sampled = False
    symbol = None
    try:
        for candidate in FilteredElementCollector(doc).OfClass(FamilySymbol) \
                .OfCategory(bic("OST_DetailComponents")).WhereElementIsElementType():
            if as_text(candidate.FamilyName) == family and el_name(candidate) == type_name:
                symbol = candidate
                break
    except Exception:
        symbol = None
    if symbol is not None:
        type_names |= param_names_of(symbol)
        try:
            symbol_id = eid_value(symbol.Id)
            for inst in FilteredElementCollector(doc).OfClass(FamilyInstance) \
                    .OfCategory(bic("OST_DetailComponents")).WhereElementIsNotElementType():
                if eid_value(inst.GetTypeId()) == symbol_id:
                    instance_names |= param_names_of(inst)
                    sampled = True
                    break
        except Exception:
            pass
    try:
        instance_names |= binding_param_names(doc, [eid_value(ElementId(bic("OST_DetailComponents")))])
    except Exception:
        pass
    return (sorted(instance_names, key=lambda n: n.lower()),
            sorted(type_names, key=lambda n: n.lower()), sampled)


# ---------------------------------------------------------------------------
# PER-INSTANCE DATA
# ---------------------------------------------------------------------------

def last_error():
    """The last line of the exception being handled, for a readable report."""
    try:
        text = traceback.format_exc().strip().splitlines()[-1]
    except Exception:
        return u"unknown"
    for prefix in ("Autodesk.Revit.Exceptions.", "System."):
        text = text.replace(prefix, u"")
    return as_text(text)[:140]


LEVEL_BIPS = ("FAMILY_LEVEL_PARAM", "INSTANCE_REFERENCE_LEVEL_PARAM",
              "INSTANCE_SCHEDULE_ONLY_LEVEL_PARAM", "SCHEDULE_LEVEL_PARAM",
              "FAMILY_BASE_LEVEL_PARAM")


def instance_point(inst):
    try:
        location = inst.Location
        if isinstance(location, LocationPoint):
            return location.Point
        if isinstance(location, LocationCurve):
            return location.Curve.Evaluate(0.5, True)
    except Exception:
        pass
    try:
        box = inst.get_BoundingBox(None)
        if box is not None:
            return XYZ((box.Min.X + box.Max.X) / 2.0, (box.Min.Y + box.Max.Y) / 2.0,
                       (box.Min.Z + box.Max.Z) / 2.0)
    except Exception:
        pass
    return None


def level_of(inst, levels, point):
    """Level id (int) for an instance: LevelId, then the level parameters,
    then the nearest level at or below its location."""
    level_ids = set([l["id"] for l in levels])
    try:
        value = eid_value(inst.LevelId)
        if value in level_ids:
            return value
    except Exception:
        pass
    for name in LEVEL_BIPS:
        try:
            param = inst.get_Parameter(bip(name))
            if param is not None and param.StorageType == StorageType.ElementId:
                value = eid_value(param.AsElementId())
                if value in level_ids:
                    return value
        except Exception:
            continue
    if point is not None and levels:
        best = levels[0]["id"]
        for level in levels:
            if level["elev"] <= point.Z + 0.01:
                best = level["id"]
        return best
    return -1


def instance_record(doc, inst, levels, links, phase, room_param, room_source="room",
                    element_room_param=u""):
    """Read one element for the schematic.

    Every field is read on its own, so one awkward element loses a room name
    or a mark rather than dropping out of the schematic altogether. Whatever
    would not read is named in record["problems"], because "could not be read"
    on its own is not something anyone can act on."""
    record = {
        "element": inst,
        "id": 0,
        "family": u"",
        "type": u"",
        "level_id": -1,
        "room_key": None,
        "room_label": u"",
        "mark": u"",
        "type_mark": u"",
        "problems": [],
    }

    def read(field, label, func, default=None):
        try:
            record[field] = func()
        except Exception:
            if default is not None:
                record[field] = default
            record["problems"].append(label + u" (" + last_error() + u")")

    read("id", u"element id", lambda: eid_value(inst.Id), 0)
    read("family", u"family name", lambda: as_text(inst.Symbol.FamilyName), u"")
    read("type", u"type name", lambda: el_name(inst.Symbol), u"")

    point = None
    try:
        point = instance_point(inst)
    except Exception:
        record["problems"].append(u"location (" + last_error() + u")")
    if point is None and not record["problems"]:
        record["problems"].append(u"no location point or bounding box")

    read("level_id", u"level", lambda: level_of(inst, levels, point), -1)

    if room_source == "element":
        # the room name is read straight off the element, not from a room
        text = None
        try:
            text = param_text(find_param(inst, element_room_param, True))
        except Exception:
            record["problems"].append(u"room parameter '" + as_text(element_room_param) +
                                      u"' (" + last_error() + u")")
        record["room_label"] = as_text(text).strip()
        record["room_key"] = room_key_of(record["room_label"])
    else:
        room = None
        room_doc = u""
        try:
            room, room_doc = find_room(doc, links, point, phase)
        except Exception:
            record["problems"].append(u"room lookup (" + last_error() + u")")
        if room is None:
            try:
                room = inst.Room
                room_doc = as_text(doc.Title)
            except Exception:
                room = None
        if room is not None:
            read("room_key", u"room id", lambda: u"{0}:{1}".format(room_doc, eid_value(room.Id)))
            read("room_label", u"room name", lambda: room_label(room, room_param), u"")

    read("mark", u"Mark", lambda: as_text(builtin_text(inst, "ALL_MODEL_MARK")), u"")
    read("type_mark", u"Type Mark", lambda: as_text(type_builtin_text(inst, "ALL_MODEL_TYPE_MARK")), u"")
    return record


# ---------------------------------------------------------------------------
# ELECTRICAL
# ---------------------------------------------------------------------------

def panel_ids(doc):
    """Ids of every piece of electrical equipment that has a panel schedule."""
    ids = set()
    try:
        for view in FilteredElementCollector(doc).OfClass(PanelScheduleView):
            try:
                if view.IsPanelScheduleTemplate():
                    continue
            except Exception:
                pass
            try:
                panel_id = view.GetPanel()
                if eid_value(panel_id) > 0:
                    ids.add(eid_value(panel_id))
            except Exception:
                continue
    except Exception:
        pass
    return ids


def panel_label(element):
    """What a board is called: Panel Name, else Mark, else the type name."""
    for name in ("RBS_ELEC_PANEL_NAME", "ALL_MODEL_MARK"):
        text = as_text(builtin_text(element, name)).strip()
        if text:
            return text
    try:
        return el_name(element.Symbol)
    except Exception:
        return el_name(element)


def read_panels(doc):
    """Every electrical equipment instance, with whether it has a panel
    schedule - what the Main LV picker offers."""
    scheduled = panel_ids(doc)
    out = []
    try:
        for inst in FilteredElementCollector(doc).OfClass(FamilyInstance) \
                .OfCategory(bic("OST_ElectricalEquipment")).WhereElementIsNotElementType():
            try:
                if inst.ViewSpecific:
                    continue
                key = eid_value(inst.Id)
                out.append({"id": key, "label": panel_label(inst),
                            "family": as_text(inst.Symbol.FamilyName),
                            "scheduled": key in scheduled})
            except Exception:
                continue
    except Exception:
        pass
    out.sort(key=lambda r: natural_key(r["label"]))
    return out


def electrical_systems(element):
    """The circuits an element is connected to, across API versions.

    Kept as a fallback: reading the circuits out of the document is more
    reliable than reaching through MEPModel, whose members have moved."""
    systems = []
    try:
        mep = element.MEPModel
    except Exception:
        return systems
    if mep is None:
        return systems
    for getter in ("GetElectricalSystems", "ElectricalSystems", "GetAssignedElectricalSystems"):
        try:
            found = getattr(mep, getter)
            if callable(found):
                found = found()
            if found is None:
                continue
            for system in found:
                if system is not None:
                    systems.append(system)
        except Exception:
            continue
    return systems


def system_loads(system):
    """The elements a circuit serves."""
    for getter in ("Elements", "GetElements"):
        try:
            found = getattr(system, getter)
            if callable(found):
                found = found()
            if found is not None:
                return [e for e in found if e is not None]
        except Exception:
            continue
    return []


def circuit_number(system):
    label = u""
    try:
        label = as_text(system.CircuitNumber)
    except Exception:
        label = u""
    if not label:
        label = as_text(builtin_text(system, "RBS_ELEC_CIRCUIT_NUMBER"))
    return label


def circuit_edges(doc, records):
    """(supplying id, fed id, circuit number) for every circuit that feeds one
    placed piece of equipment from another placed one.

    Returns (edges, notes) - notes explains what was seen, because "no lines
    were drawn" is otherwise impossible to act on.
    """
    placed = {}
    for rec in records:
        placed[rec["id"]] = rec
    edges = []
    seen = set()
    total = 0
    with_base = 0
    base_placed = 0

    def add(base_id, load_id, label):
        key = (base_id, load_id, label)
        if base_id in placed and load_id in placed and base_id != load_id and key not in seen:
            seen.add(key)
            edges.append(key)
            return True
        return False

    # the reliable route: every circuit in the document
    systems = []
    try:
        systems = list(FilteredElementCollector(doc).OfClass(ElectricalSystem)
                       .WhereElementIsNotElementType())
    except Exception:
        systems = []
    for system in systems:
        total += 1
        try:
            base = system.BaseEquipment
        except Exception:
            base = None
        if base is None:
            continue
        with_base += 1
        base_id = eid_value(base.Id)
        if base_id in placed:
            base_placed += 1
        label = circuit_number(system)
        for load in system_loads(system):
            try:
                add(base_id, eid_value(load.Id), label)
            except Exception:
                continue

    # fallback for a release where the collector comes back empty
    if not systems:
        for rec in records:
            for system in electrical_systems(rec["element"]):
                total += 1
                try:
                    base = system.BaseEquipment
                except Exception:
                    base = None
                if base is None:
                    continue
                with_base += 1
                add(eid_value(base.Id), rec["id"], circuit_number(system))

    notes = {
        "circuits": total,
        "with_base": with_base,
        "base_placed": base_placed,
        "edges": len(edges),
    }
    return edges, notes


# ---------------------------------------------------------------------------
# MARRIED DETAIL ITEMS
# ---------------------------------------------------------------------------

def describe_element(element):
    """'Category - Family : Type' for a model element, or '' for none."""
    if element is None:
        return u""
    family = u""
    type_name = u""
    try:
        symbol = element.Symbol
        family = as_text(symbol.FamilyName)
        type_name = el_name(symbol)
    except Exception:
        try:
            type_name = el_name(element.Document.GetElement(element.GetTypeId()))
        except Exception:
            type_name = el_name(element)
    parts = [p for p in (category_name(element), family, type_name) if p]
    if family and type_name:
        return u"{0} - {1} : {2}".format(category_name(element), family, type_name)
    return u" - ".join(parts)


def read_married(doc, link_param):
    """Every detail item whose link parameter holds a value.

    Returns [{'detail_id', 'detail', 'view_id', 'view', 'link_id', 'link_text',
              'model_id', 'model', 'status'}] sorted by view then detail."""
    out = []
    if not link_param:
        return out
    view_names = {}
    try:
        collector = FilteredElementCollector(doc).OfClass(FamilyInstance) \
            .OfCategory(bic("OST_DetailComponents")).WhereElementIsNotElementType()
        for inst in collector:
            try:
                param = find_param(inst, link_param, False)
                if param is None:
                    continue
                text = as_text(param_text(param)).strip()
                if not text:
                    continue
                link_id = link_id_of(text)
                view_id = eid_value(inst.OwnerViewId)
                if view_id not in view_names:
                    view_names[view_id] = el_name(doc.GetElement(inst.OwnerViewId))
                model = doc.GetElement(make_id(link_id)) if link_id is not None else None
                if link_id is None:
                    status = u"not an element id"
                elif model is None:
                    status = u"element {0} no longer exists".format(link_id)
                else:
                    status = u"ok"
                out.append({
                    "detail_id": eid_value(inst.Id),
                    "detail": u"{0} : {1}".format(as_text(inst.Symbol.FamilyName), el_name(inst.Symbol)),
                    "view_id": view_id,
                    "view": view_names[view_id],
                    "link_id": link_id,
                    "link_text": text,
                    "model_id": eid_value(model.Id) if model is not None else 0,
                    "model": describe_element(model),
                    "status": status,
                })
            except Exception:
                continue
    except Exception:
        pass
    out.sort(key=lambda r: (natural_key(r["view"]), natural_key(r["detail"]), r["detail_id"]))
    return out


def married_param_names(doc, rows, limit=60):
    """(names to read from, names to write to) for the married pairs.

    One element per distinct type is sampled rather than one per row, and the
    whole of each category's bound parameters is added on top - so the
    drop-downs offer everything the category can carry, not only what the
    first few elements happened to have filled in."""
    from_names = set()
    to_names = set()
    model_cats = set()
    detail_cats = set()
    seen_model_types = set()
    seen_detail_types = set()
    sampled = 0
    for row in rows:
        if row["status"] != u"ok":
            continue
        try:
            model = doc.GetElement(make_id(row["model_id"]))
            detail = doc.GetElement(make_id(row["detail_id"]))
        except Exception:
            continue
        if model is None or detail is None:
            continue
        model_cats |= category_ids_of([model])
        detail_cats |= category_ids_of([detail])
        model_type = eid_value(model.GetTypeId())
        detail_type = eid_value(detail.GetTypeId())
        fresh = False
        if model_type not in seen_model_types:
            seen_model_types.add(model_type)
            from_names |= param_names_of(model)
            try:
                from_names |= param_names_of(doc.GetElement(model.GetTypeId()))
            except Exception:
                pass
            fresh = True
        if detail_type not in seen_detail_types:
            seen_detail_types.add(detail_type)
            to_names |= param_names_of(detail)
            fresh = True
        if fresh:
            sampled += 1
            if sampled >= limit:
                break
    from_names |= binding_param_names(doc, model_cats)
    to_names |= binding_param_names(doc, detail_cats)
    return (sorted(from_names, key=lambda n: n.lower()), sorted(to_names, key=lambda n: n.lower()))


# ---------------------------------------------------------------------------
# VIEWS
# ---------------------------------------------------------------------------

def drafting_view_type_id(doc):
    try:
        for vft in FilteredElementCollector(doc).OfClass(ViewFamilyType):
            if vft.ViewFamily == ViewFamily.Drafting:
                return vft.Id
    except Exception:
        pass
    return None


def read_view_names(doc):
    names = []
    try:
        for view in FilteredElementCollector(doc).OfClass(View):
            names.append(el_name(view))
    except Exception:
        pass
    return names


def read_view_params(doc):
    """Project parameters bound to Views, with the values already in use.
    Returns (sorted names, {name: sorted values})."""
    names = set()
    try:
        views_cat = eid_value(ElementId(bic("OST_Views")))
        iterator = doc.ParameterBindings.ForwardIterator()
        iterator.Reset()
        while iterator.MoveNext():
            try:
                definition = iterator.Key
                binding = iterator.Current
                for cat in binding.Categories:
                    if eid_value(cat.Id) == views_cat:
                        names.add(as_text(definition.Name))
                        break
            except Exception:
                continue
    except Exception:
        pass
    values = {}
    for name in names:
        values[name] = set()
    if names:
        try:
            for view in FilteredElementCollector(doc).OfClass(View):
                try:
                    if view.IsTemplate:
                        continue
                except Exception:
                    pass
                for name in names:
                    try:
                        param = view.LookupParameter(name)
                        if param is not None and param.StorageType == StorageType.String:
                            text = as_text(param.AsString()).strip()
                            if text:
                                values[name].add(text)
                    except Exception:
                        continue
        except Exception:
            pass
    sorted_values = {}
    for name in values:
        sorted_values[name] = sorted(values[name], key=lambda v: v.lower())
    return sorted(names, key=lambda n: n.lower()), sorted_values


# ---------------------------------------------------------------------------
# SNAPSHOT
# ---------------------------------------------------------------------------

def read_project(doc):
    links = read_links(doc)
    view_params, view_values = read_view_params(doc)
    return {
        "title": as_text(doc.Title),
        "levels": read_levels(doc),
        "line_styles": read_line_styles(doc),
        "text_types": read_text_types(doc),
        "room_params": read_room_params(doc, links),
        "families": read_model_families(doc),
        "details": read_detail_items(doc),
        "view_params": view_params,
        "view_values": view_values,
        "panels": read_panels(doc),
        "category_params": params_by_category(doc),
    }
