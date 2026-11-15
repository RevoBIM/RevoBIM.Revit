# -*- coding: utf-8 -*-
"""Duct Accessory Resize - everything that reads or writes the model.

Every function here is called from inside the ExternalEvent handler, so it
has a valid API context. BuiltInCategory and BuiltInParameter members are
looked up when called, never at import.
"""

import dar_clr  # noqa: F401 - assemblies first, always

import traceback

from System.Collections.Generic import List
from Autodesk.Revit.DB import (FilteredElementCollector, BuiltInCategory,
                               BuiltInParameter, StorageType, Transaction,
                               TransactionGroup, TransactionStatus,
                               IFailuresPreprocessor, FailureProcessingResult,
                               FailureSeverity, WorksharingUtils, ElementId,
                               Reference, CheckoutStatus)
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException

import dar_core as core

DUCT_BIP = {
    u"w": "RBS_CURVE_WIDTH_PARAM",
    u"h": "RBS_CURVE_HEIGHT_PARAM",
    u"d": "RBS_CURVE_DIAMETER_PARAM",
}
ALL_DIMS = (u"w", u"h", u"d")
KIND_CATEGORY = {core.KIND_ACC: "OST_DuctAccessory",
                 core.KIND_TERM: "OST_DuctTerminal"}


# ============================================================
# lookups
# ============================================================

def bic(name):
    return getattr(BuiltInCategory, name)


def bip(name):
    return getattr(BuiltInParameter, name)


def is_cat(element, name):
    try:
        cat = element.Category
    except Exception:
        return False
    if cat is None:
        return False
    target = bic(name)
    try:
        if cat.BuiltInCategory == target:
            return True
    except Exception:
        pass
    try:
        return core.eid_value(cat.Id) == int(target)
    except Exception:
        return False


def is_duct(element):
    return is_cat(element, "OST_DuctCurves")


def is_accessory(element):
    return is_cat(element, "OST_DuctAccessory")


def is_terminal(element):
    return is_cat(element, "OST_DuctTerminal")


def family_kind(element):
    """core.KIND_ACC / core.KIND_TERM, or None for anything else."""
    if is_accessory(element):
        return core.KIND_ACC
    if is_terminal(element):
        return core.KIND_TERM
    return None


def allowed(element):
    try:
        return is_duct(element) or family_kind(element) is not None
    except Exception:
        return False


def safe_name(element):
    """Element.Name raises AttributeError in IronPython on some classes."""
    if element is None:
        return u""
    try:
        return core.to_text(element.Name)
    except Exception:
        pass
    for name in ("SYMBOL_NAME_PARAM", "ALL_MODEL_TYPE_NAME"):
        try:
            p = element.get_Parameter(bip(name))
            if p is not None and p.HasValue:
                return core.to_text(p.AsString())
        except Exception:
            pass
    return u""


def type_of(doc, element):
    try:
        return doc.GetElement(element.GetTypeId())
    except Exception:
        return None


def family_and_type(doc, element):
    element_type = type_of(doc, element)
    family = u""
    try:
        family = core.to_text(element_type.FamilyName)
    except Exception:
        pass
    return family, safe_name(element_type)


def is_double(param):
    try:
        return param.StorageType == StorageType.Double
    except Exception:
        return False


def read_mm(param):
    if param is None or not is_double(param):
        return None
    try:
        if not param.HasValue:
            return None
        return core.ft_to_mm(param.AsDouble())
    except Exception:
        return None


def lookup(element, name):
    """Every route to a named length parameter. LookupParameter and
    GetParameters do not always hand back the same object, and a family can
    carry two parameters of one name, so a writable one is preferred."""
    if element is None or not name:
        return None
    found = []
    try:
        for p in element.GetParameters(name):
            found.append(p)
    except Exception:
        pass
    try:
        p = element.LookupParameter(name)
        if p is not None:
            found.append(p)
    except Exception:
        pass
    doubles = [p for p in found if is_double(p)]
    if not doubles:
        return None
    for p in doubles:
        try:
            if not p.IsReadOnly:
                return p
        except Exception:
            pass
    return doubles[0]


def acc_param(doc, element, name):
    """(parameter, 'instance' or 'type') - instance first."""
    p = lookup(element, name)
    if p is not None:
        return p, u"instance"
    p = lookup(type_of(doc, element), name)
    if p is not None:
        return p, u"type"
    return None, None


def duct_shape(doc, element):
    try:
        shape = core.to_text(type_of(doc, element).Shape).lower()
        if u"rect" in shape:
            return core.SHAPE_RECT
        if u"round" in shape:
            return core.SHAPE_ROUND
        if u"oval" in shape:
            return u"oval"
    except Exception:
        pass
    diameter = read_mm(element.get_Parameter(bip(DUCT_BIP[u"d"])))
    if diameter:
        return core.SHAPE_ROUND
    width = read_mm(element.get_Parameter(bip(DUCT_BIP[u"w"])))
    if width:
        return core.SHAPE_RECT
    return None


# ============================================================
# connectors
# ============================================================

def connectors(element):
    """A duct carries its ConnectorManager directly, a family instance
    through MEPModel - reading only one of them silently finds nothing on
    the other."""
    if element is None:
        return []
    for route in ("ConnectorManager", "MEPModel"):
        try:
            manager = getattr(element, route)
            if route == "MEPModel":
                manager = manager.ConnectorManager
            if manager is None:
                continue
            return list(manager.Connectors)
        except Exception:
            continue
    return []


def xyz(point):
    return (point.X, point.Y, point.Z)


def physical_links(element):
    """(own connector, other connector, other element) for every physical
    connection - logical (system) connections are left out."""
    out = []
    own_id = core.eid_value(element.Id)
    for connector in connectors(element):
        try:
            if not connector.IsConnected:
                continue
            refs = list(connector.AllRefs)
        except Exception:
            continue
        for other in refs:
            try:
                owner = other.Owner
                if owner is None or core.eid_value(owner.Id) == own_id:
                    continue
                if u"logical" in core.to_text(other.ConnectorType).lower():
                    continue
            except Exception:
                continue
            out.append((connector, other, owner))
    return out


def connection_summary(element):
    parts = []
    for own, other, owner in physical_links(element):
        kind = family_kind(owner) or (
            u"duct" if is_duct(owner) else u"fitting/other")
        parts.append(u"{0} {1}".format(kind, core.eid_value(owner.Id)))
    return u", ".join(parts) or u"nothing"


def detach_accessories(doc, elements, log):
    """Disconnect every connection between these elements and a duct
    accessory or air terminal - either end being the family. Revit
    otherwise tries to push a duct's new size through the connector into
    the family, and one that cannot follow is answered with 'connected in
    a network and can no longer keep the connectivity'. Returns what was
    disconnected."""
    pairs, seen = [], set()
    for element in elements:
        element_is_family = family_kind(element) is not None
        for own, other, owner in physical_links(element):
            if not (element_is_family or family_kind(owner) is not None):
                continue
            key = core.pair_key(core.eid_value(element.Id), xyz(own.Origin),
                                core.eid_value(owner.Id), xyz(other.Origin))
            if key in seen:
                continue
            seen.add(key)
            pairs.append({u"a": element.Id, u"pa": xyz(own.Origin),
                          u"b": owner.Id, u"pb": xyz(other.Origin)})
            own.DisconnectFrom(other)
    if pairs:
        log.add(u"  detached {0} accessory connections", len(pairs))
    return pairs


def connector_near(element, point):
    found = connectors(element)
    index = core.nearest([xyz(c.Origin) for c in found], point)
    return None if index is None else found[index]


def reattach(doc, pairs, log):
    """Reconnect what detach_accessories took apart, finding each end again
    by position, and prove every one is connected. Anything that will not
    reconnect raises, so the transaction rolls back rather than leaving a
    broken system."""
    failed = []
    for pair in pairs:
        a = connector_near(doc.GetElement(pair[u"a"]), pair[u"pa"])
        b = connector_near(doc.GetElement(pair[u"b"]), pair[u"pb"])
        label = u"{0} to {1}".format(core.eid_value(pair[u"a"]),
                                     core.eid_value(pair[u"b"]))
        if a is None or b is None:
            failed.append(label + u" (connector moved)")
            continue
        try:
            if not a.IsConnectedTo(b):
                a.ConnectTo(b)
        except Exception as error:
            failed.append(u"{0} ({1})".format(label, core.to_text(error)))
            continue
        try:
            if not a.IsConnectedTo(b):
                failed.append(label + u" (did not hold)")
        except Exception:
            pass
    if pairs:
        log.add(u"  reconnected {0} of {1}", len(pairs) - len(failed),
                len(pairs))
    if failed:
        raise Exception(u"could not reconnect " + u"; ".join(failed))


# ============================================================
# reading
# ============================================================

def describe(doc, element, settings):
    """One row, as a plain dict the rules in dar_core understand."""
    family, type_name = family_and_type(doc, element)
    row = {
        u"eid": element.Id,
        u"id": core.eid_value(element.Id),
        u"type_id": core.eid_value(element.GetTypeId()),
        u"kind": None,
        u"category": u"",
        u"family": family,
        u"type": type_name,
        u"el_shape": None,
        u"current": {},
        u"sources": {},
        u"param_names": {},
        u"read_problems": [],
    }
    if is_duct(element):
        row[u"kind"] = u"duct"
        row[u"category"] = u"Duct"
        row[u"el_shape"] = duct_shape(doc, element)
        for dim in ALL_DIMS:
            param = None
            try:
                param = element.get_Parameter(bip(DUCT_BIP[dim]))
            except Exception:
                pass
            value = read_mm(param)
            if value:
                row[u"current"][dim] = value
            if param is not None:
                try:
                    row[u"sources"][dim] = (u"instance", not param.IsReadOnly)
                except Exception:
                    row[u"sources"][dim] = (u"instance", True)
    elif family_kind(element) is not None:
        kind = family_kind(element)
        row[u"kind"] = kind
        row[u"category"] = core.KIND_LABEL[kind]
        names = core.settings_names(settings, kind)
        for dim in ALL_DIMS:
            name = names.get(dim, u"")
            row[u"param_names"][dim] = name
            if not name:
                continue
            param, where = acc_param(doc, element, name)
            if param is None:
                continue
            try:
                writable = not param.IsReadOnly
            except Exception:
                writable = False
            row[u"sources"][dim] = (where, writable)
            value = read_mm(param)
            if value is not None:
                row[u"current"][dim] = value
    return row


def read_rows(doc, ids, settings, log):
    rows, skipped = [], 0
    for eid in ids:
        element = doc.GetElement(eid)
        if element is None or not allowed(element):
            skipped += 1
            continue
        try:
            row = describe(doc, element, settings)
        except Exception:
            skipped += 1
            log.add(u"could not read {0}: {1}", core.eid_value(eid),
                    traceback.format_exc())
            continue
        rows.append(row)
        log.add(u"{0} {1} | {2} : {3} | shape {4} | current {5} | sources {6}"
                u" | params {7} | connected to {8}",
                row[u"kind"], row[u"id"], row[u"family"], row[u"type"],
                row[u"el_shape"], row[u"current"], row[u"sources"],
                row[u"param_names"], connection_summary(element))
    order = {core.KIND_ACC: 0, core.KIND_TERM: 1, u"duct": 2}
    rows.sort(key=lambda r: (order.get(r[u"kind"], 3), r[u"family"],
                             r[u"type"], r[u"id"]))
    return rows, skipped


def collect_params(doc, kind):
    """Every length parameter carried by the duct accessories, or the air
    terminals, actually in the project - instance and type. One instance
    per type is enough."""
    names, seen = set(), set()
    collector = (FilteredElementCollector(doc)
                 .OfCategory(bic(KIND_CATEGORY[kind]))
                 .WhereElementIsNotElementType())
    for element in collector:
        type_id = core.eid_value(element.GetTypeId())
        if type_id in seen:
            continue
        seen.add(type_id)
        for owner in (element, type_of(doc, element)):
            if owner is None:
                continue
            try:
                params = list(owner.Parameters)
            except Exception:
                continue
            for p in params:
                if not is_double(p):
                    continue
                try:
                    spec = p.Definition.GetDataType().TypeId
                except Exception:
                    spec = u""
                if not core.is_size_spec(spec):
                    continue
                try:
                    names.add(core.to_text(p.Definition.Name))
                except Exception:
                    pass
    return sorted(names, key=lambda n: n.lower()), len(seen)


def canvas_is_dark(uiapp):
    """True / False from Revit's canvas, None when it cannot be read.
    UITheme.Dark is 0, so the read is tested with 'is not None', never for
    truth. UIThemeManager only exists from 2024, hence getattr."""
    manager = None
    try:
        import Autodesk.Revit.UI as revit_ui
        manager = getattr(revit_ui, "UIThemeManager", None)
    except Exception:
        manager = None
    if manager is not None:
        try:
            theme = getattr(manager, "CurrentCanvasTheme", None)
            if theme is not None:
                return u"dark" in core.to_text(theme).lower()
        except Exception:
            pass
    try:
        colour = uiapp.Application.BackgroundColor
        return core.colour_is_dark(colour.Red, colour.Green, colour.Blue)
    except Exception:
        pass
    if manager is not None:
        try:
            theme = getattr(manager, "CurrentTheme", None)
            if theme is not None:
                return u"dark" in core.to_text(theme).lower()
        except Exception:
            pass
    return None


def environment(uiapp):
    lines = []
    try:
        app = uiapp.Application
        lines.append(u"Revit {0} build {1}".format(app.VersionNumber,
                                                   app.VersionBuild))
    except Exception:
        lines.append(u"Revit version unreadable")
    try:
        doc = uiapp.ActiveUIDocument.Document
        lines.append(u"model: {0} | workshared: {1}".format(doc.Title,
                                                            doc.IsWorkshared))
    except Exception:
        pass
    return lines


# ============================================================
# selection
# ============================================================

class DuctAndAccessoryFilter(ISelectionFilter):
    def AllowElement(self, element):
        return allowed(element)

    def AllowReference(self, reference, point):
        return False


def selected_ids(uiapp):
    uidoc = uiapp.ActiveUIDocument
    doc = uidoc.Document
    keep, dropped = [], 0
    for eid in uidoc.Selection.GetElementIds():
        if allowed(doc.GetElement(eid)):
            keep.append(eid)
        else:
            dropped += 1
    return keep, dropped


def pick_elements(uiapp):
    """PickObjects, with whatever ducts and accessories are already
    selected pre-loaded into the pick. None when cancelled."""
    uidoc = uiapp.ActiveUIDocument
    doc = uidoc.Document
    pre = List[Reference]()
    for eid in selected_ids(uiapp)[0]:
        try:
            pre.Add(Reference(doc.GetElement(eid)))
        except Exception:
            pass
    prompt = (u"RevoBIM Duct Accessory Resize - select ducts, duct "
              u"accessories and air terminals, then Finish")
    try:
        refs = uidoc.Selection.PickObjects(ObjectType.Element,
                                           DuctAndAccessoryFilter(),
                                           prompt, pre)
    except OperationCanceledException:
        return None
    ids = [r.ElementId for r in refs]
    try:
        uidoc.Selection.SetElementIds(List[ElementId](ids))
    except Exception:
        pass
    return ids


def show_element(uiapp, element_id):
    uidoc = uiapp.ActiveUIDocument
    uidoc.Selection.SetElementIds(List[ElementId]([element_id]))
    try:
        uidoc.ShowElements(element_id)
    except Exception:
        pass


# ============================================================
# writing
# ============================================================

class Swallower(IFailuresPreprocessor):
    """Deletes warnings, records errors and rolls back on them, so Revit
    never raises a dialog in the middle of a run."""

    def __init__(self):
        self.errors = []
        self.warnings = 0

    def PreprocessFailures(self, accessor):
        has_error = False
        try:
            messages = list(accessor.GetFailureMessages())
        except Exception:
            messages = []
        for message in messages:
            try:
                severity = message.GetSeverity()
            except Exception:
                severity = None
            try:
                text = core.to_text(message.GetDescriptionText())
            except Exception:
                text = u"(no description)"
            if severity == FailureSeverity.Warning:
                try:
                    accessor.DeleteWarning(message)
                    self.warnings += 1
                    continue
                except Exception:
                    pass
            has_error = True
            if text not in self.errors:
                self.errors.append(text)
        if has_error:
            return FailureProcessingResult.ProceedWithRollBack
        return FailureProcessingResult.Continue


def start_transaction(doc, name):
    transaction = Transaction(doc, name)
    transaction.Start()
    swallower = Swallower()
    try:
        options = transaction.GetFailureHandlingOptions()
        options.SetFailuresPreprocessor(swallower)
        options.SetClearAfterRollback(True)
        try:
            options.SetForcedModalHandling(False)
        except Exception:
            pass
        transaction.SetFailureHandlingOptions(options)
    except Exception:
        pass
    return transaction, swallower


def set_mm(param, mm):
    if param is None:
        raise Exception(u"parameter missing")
    if param.IsReadOnly:
        raise Exception(u"parameter '{0}' is read-only".format(
            core.to_text(param.Definition.Name)))
    if param.Set(core.mm_to_ft(mm)) is False:
        raise Exception(u"Revit would not take {0}mm".format(core.fmt_mm(mm)))


def switch_type(doc, element, shape, target, dims, names, cache, log):
    """The type an instance moves to when its size lives on the type: one
    already named for the size, else the same type in another size, else a
    duplicate of its own type. Never edits a type other instances use."""
    current_type = type_of(doc, element)
    if current_type is None:
        raise Exception(u"the element has no type")
    key = (core.eid_value(current_type.Id),
           tuple(round(float(target[d]), 1) for d in core.DIMS[shape]))
    if key in cache:
        return cache[key]

    def fits(candidate):
        for dim in dims:
            if not core.same_mm(read_mm(lookup(candidate, names[dim])),
                                target[dim]):
                return False
        return True

    base = safe_name(current_type)
    wanted = core.type_name_for(shape, base, target)
    stem = core.strip_size(shape, base).lower()
    siblings = []
    try:
        for sid in current_type.Family.GetFamilySymbolIds():
            sibling = doc.GetElement(sid)
            if sibling is not None:
                siblings.append(sibling)
    except Exception:
        pass
    chosen = None
    for sibling in siblings:
        if safe_name(sibling).lower() == wanted.lower() and fits(sibling):
            chosen = sibling
            break
    if chosen is None:
        own = core.eid_value(current_type.Id)
        for sibling in siblings:
            if core.eid_value(sibling.Id) == own:
                continue
            same_stem = core.strip_size(shape, safe_name(sibling)).lower()
            if same_stem == stem and fits(sibling):
                chosen = sibling
                break
    if chosen is not None:
        log.add(u"  type {0} -> existing type '{1}'", base, safe_name(chosen))
        cache[key] = chosen.Id
        return chosen.Id
    new_name = core.unique_name(wanted, [safe_name(s) for s in siblings])
    new_type = current_type.Duplicate(new_name)
    for dim in dims:
        set_mm(lookup(new_type, names[dim]), target[dim])
    log.add(u"  type {0} -> duplicated as '{1}'", base, new_name)
    cache[key] = new_type.Id
    return new_type.Id


def write_row(doc, row, shape, target, by_kind, type_mode, cache, log):
    """by_kind is {family kind: {dim: parameter name}} - a duct accessory
    and an air terminal rarely name their sizes the same way."""
    names = by_kind.get(row[u"kind"], {})
    element = doc.GetElement(row[u"eid"])
    if element is None:
        raise Exception(u"element {0} no longer exists".format(row[u"id"]))
    current = row.get(u"current") or {}
    changed = [d for d in core.DIMS[shape]
               if not core.same_mm(current.get(d), target.get(d))]
    log.add(u"write {0} {1}: {2} -> {3}", row[u"kind"], row[u"id"],
            core.fmt_size(shape, current), core.fmt_size(shape, target))
    if row[u"kind"] == u"duct":
        for dim in changed:
            set_mm(element.get_Parameter(bip(DUCT_BIP[dim])), target[dim])
        return
    sources = row.get(u"sources") or {}
    type_dims = [d for d in changed if sources.get(d, (None,))[0] == u"type"]
    inst_dims = [d for d in changed
                 if sources.get(d, (None,))[0] == u"instance"]
    if type_dims:
        if type_mode == u"edit":
            element_type = type_of(doc, element)
            for dim in type_dims:
                set_mm(lookup(element_type, names[dim]), target[dim])
        else:
            new_type_id = switch_type(doc, element, shape, target, type_dims,
                                      names, cache, log)
            if core.eid_value(new_type_id) != core.eid_value(
                    element.GetTypeId()):
                element.ChangeTypeId(new_type_id)
    for dim in inst_dims:
        set_mm(lookup(element, names[dim]), target[dim])


def owner_of(doc, element_id):
    try:
        owner = WorksharingUtils.GetWorksharingTooltipInfo(doc, element_id).Owner
        if owner:
            return core.to_text(owner)
    except Exception:
        pass
    try:
        element = doc.GetElement(element_id)
        workset = doc.GetWorksetTable().GetWorkset(element.WorksetId)
        if workset.Owner:
            return u"workset \"{0}\" owned by {1}".format(
                core.to_text(workset.Name), core.to_text(workset.Owner))
    except Exception:
        pass
    return u"another user"


def borrow(doc, ids, log):
    """Borrow before writing: an unborrowed element writes nothing and says
    nothing, because Revit asks in a dialog. Returns {id: reason} for what
    could not be borrowed. Owners are only asked about for those."""
    locked = {}
    if not ids:
        return locked
    try:
        if not doc.IsWorkshared:
            return locked
    except Exception:
        return locked
    try:
        held = WorksharingUtils.CheckoutElements(doc, List[ElementId](ids))
        held_set = set(core.eid_value(i) for i in held)
    except Exception:
        log.add(u"CheckoutElements failed: {0}", traceback.format_exc())
        held_set = None
    for eid in ids:
        value = core.eid_value(eid)
        if held_set is not None and value in held_set:
            continue
        if held_set is None:
            try:
                status = WorksharingUtils.GetCheckoutStatus(doc, eid)
                if status != CheckoutStatus.OwnedByOtherUser:
                    continue
            except Exception:
                continue
        locked[value] = u"LOCKED - held by {0}".format(owner_of(doc, eid))
    if locked:
        log.add(u"could not borrow: {0}", locked)
    return locked


def apply_resize(uiapp, rows, shape, new, settings, log):
    """Resize every orange row. Everything is tried in one transaction
    first, halving on refusal; the whole run is one undo step; sizes are
    read back only after the group has closed, because a commit
    regenerates and Revit can put a size back."""
    doc = uiapp.ActiveUIDocument.Document
    include_ducts = core.flag(settings, u"include_ducts")
    include_acc = core.flag(settings, u"include_accessories")
    include_term = core.flag(settings, u"include_terminals")
    type_mode = core.to_text(settings.get(u"type_mode", u"switch"))
    names = dict((kind, core.settings_names(settings, kind))
                 for kind in core.FAMILY_KINDS)
    result = {u"asked": 0, u"changed": [], u"refused": {}, u"warnings": 0}
    clashes = core.all_clashes(settings, shape)
    if clashes:
        message = u"  ".join(clashes[k] for k in sorted(clashes))
        log.add(u"stopped before writing: {0}", message)
        result[u"stopped"] = message
        return result

    plan = [r for r in rows if core.row_status(
        r, shape, new, include_ducts, include_acc,
        include_term)[0] == u"orange"]
    result[u"asked"] = len(plan)
    log.section(u"resize {0}, {1} elements".format(core.shape_word(shape),
                                                  len(plan)))
    log.add(u"new sizes typed: {0} | type mode: {1} | names: {2}", new,
            type_mode, names)
    if not plan:
        return result

    by_id = dict((r[u"id"], r) for r in plan)
    targets = dict((r[u"id"], core.target_sizes(shape, r[u"current"], new))
                   for r in plan)

    to_borrow, seen = [], set()
    for row in plan:
        if row[u"id"] not in seen:
            seen.add(row[u"id"])
            to_borrow.append(row[u"eid"])
        if type_mode == u"edit" and row[u"kind"] in core.FAMILY_KINDS:
            element = doc.GetElement(row[u"eid"])
            type_id = element.GetTypeId() if element is not None else None
            if type_id is not None and core.eid_value(type_id) not in seen:
                seen.add(core.eid_value(type_id))
                to_borrow.append(type_id)
    locked = borrow(doc, to_borrow, log)

    todo = []
    for row in plan:
        reason = locked.get(row[u"id"])
        if reason is None and type_mode == u"edit":
            reason = locked.get(row[u"type_id"])
            if reason:
                reason = u"type " + reason
        if reason:
            result[u"refused"][row[u"id"]] = reason
        else:
            todo.append(row[u"id"])

    def attempt(chunk):
        transaction, swallower = start_transaction(
            doc, u"RevoBIM Duct Accessory Resize ({0})".format(len(chunk)))
        cache = {}
        try:
            elements = [doc.GetElement(by_id[rid][u"eid"]) for rid in chunk]
            pairs = detach_accessories(
                doc, [e for e in elements if e is not None], log)
            for rid in chunk:
                write_row(doc, by_id[rid], shape, targets[rid], names,
                          type_mode, cache, log)
            doc.Regenerate()
            reattach(doc, pairs, log)
        except Exception as error:
            try:
                transaction.RollBack()
            except Exception:
                pass
            log.add(u"  write failed: {0}", traceback.format_exc())
            return False, core.to_text(error)
        try:
            status = transaction.Commit()
        except Exception as error:
            try:
                if transaction.HasStarted() and not transaction.HasEnded():
                    transaction.RollBack()
            except Exception:
                pass
            return False, core.to_text(error)
        result[u"warnings"] += swallower.warnings
        if swallower.errors:
            log.add(u"  Revit errors: {0}", swallower.errors)
        if status == TransactionStatus.Committed:
            return True, u""
        return False, (u"; ".join(swallower.errors) or
                       u"Revit rolled it back ({0})".format(status))

    group = TransactionGroup(doc, u"RevoBIM Duct Accessory Resize")
    group.Start()
    try:
        accepted, refused = core.run_batches(todo, attempt, log)
    except Exception:
        try:
            group.RollBack()
        except Exception:
            pass
        raise
    if accepted:
        group.Assimilate()
    else:
        group.RollBack()
    result[u"refused"].update(refused)

    log.section(u"read back")
    for rid in accepted:
        element = doc.GetElement(by_id[rid][u"eid"])
        if element is None:
            result[u"refused"][rid] = u"element gone after the resize"
            continue
        fresh = describe(doc, element, settings)
        if core.sizes_match(shape, fresh[u"current"], targets[rid]):
            result[u"changed"].append(rid)
            log.add(u"{0} now {1} - ok", rid,
                    core.fmt_size(shape, fresh[u"current"]))
        else:
            reason = u"Revit took it but it reads back as {0}".format(
                core.fmt_size(shape, fresh[u"current"]))
            result[u"refused"][rid] = reason
            log.add(u"{0} {1}", rid, reason)
    log.add(u"changed {0} of {1}, refused {2}, warnings deleted {3}",
            len(result[u"changed"]), len(plan), len(result[u"refused"]),
            result[u"warnings"])
    return result
