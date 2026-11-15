# -*- coding: utf-8 -*-
"""Space Data Push - everything that touches the Revit model.

Reads: categories, space parameters, a category's writable instance parameters,
a space's values. Writes: mapped values onto one picked element, proved by
reading them back after the commit.
"""
import sdp_clr

import sdp_logic as L
from sdp_logic import Snap, RowResult

from System.Collections.Generic import List
from Autodesk.Revit.DB import (
    BuiltInCategory, BuiltInParameter, Element, ElementId, FailureProcessingResult,
    FailureSeverity, FilteredElementCollector, IFailuresPreprocessor,
    Transaction, WorksharingUtils,
)
from Autodesk.Revit.Exceptions import OperationCanceledException
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType

FALLBACK_SPACE_PARAMS = [u'Number', u'Name', u'Area', u'Volume', u'Level',
                         u'Comments', u'Perimeter']
FALLBACK_TARGET_PARAMS = [u'Comments', u'Mark']
TYPE_SCAN_LIMIT = 400
SPACE_SCAN_LIMIT = 25


# ---------------------------------------------------------------- small helpers

def eid_value(element_id):
    """ElementId.Value from 2024 on, IntegerValue before; never touch either bare."""
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


def elem_name(element):
    """Element.Name raises AttributeError in some IronPython builds."""
    if element is None:
        return u''
    try:
        return L.to_text(element.Name)
    except Exception:
        pass
    try:
        return L.to_text(Element.Name.GetValue(element))
    except Exception:
        return u''


def space_category_value():
    return int(BuiltInCategory.OST_MEPSpaces)


def detail_items_value():
    return int(BuiltInCategory.OST_DetailComponents)


class CatRec(object):
    def __init__(self, name, eid, value):
        self.name = name
        self.eid = eid
        self.value = value


class SpaceHold(object):
    """The space the tool is holding: its values are a snapshot, refreshed just
    before each push so edits made since the pick are not lost."""

    def __init__(self, doc_title, eid, values, caption):
        self.doc_title = doc_title
        self.eid = eid
        self.values = values
        self.caption = caption


# --------------------------------------------------------------------- reading

def read_categories(doc):
    """Top-level model and annotation categories that can carry parameters."""
    out = []
    for cat in doc.Settings.Categories:
        try:
            if cat.Parent is not None:
                continue
            if ('%s' % (cat.CategoryType,)) not in ('Model', 'Annotation'):
                continue
            if not cat.AllowsBoundParameters:
                continue
            name = L.to_text(cat.Name)
            if not name:
                continue
            out.append(CatRec(name, cat.Id, eid_value(cat.Id)))
        except Exception:
            continue
    out.sort(key=lambda c: c.name.lower())
    return out


def _param_name(p):
    try:
        return L.to_text(p.Definition.Name)
    except Exception:
        return u''


def read_space_params(doc):
    """Every parameter name spaces in this project carry, sorted."""
    found = {}
    count = 0
    try:
        collector = (FilteredElementCollector(doc)
                     .OfCategory(BuiltInCategory.OST_MEPSpaces)
                     .WhereElementIsNotElementType())
        for sp in collector:
            for p in sp.Parameters:
                try:
                    if ('%s' % (p.StorageType,)) == 'None':
                        continue
                    name = _param_name(p)
                    if name and name.lower() not in found:
                        found[name.lower()] = name
                except Exception:
                    continue
            count += 1
            if count >= SPACE_SCAN_LIMIT:
                break
    except Exception as ex:
        L.log_debug(u'read_space_params failed: %s' % ex)
    names = sorted(found.values(), key=lambda n: n.lower())
    return names if names else list(FALLBACK_SPACE_PARAMS)


def read_category_params(doc, rec):
    """Writable instance parameters for a category: one element per type is
    enough to see every family's parameters, plus anything bound to the category
    through the project's shared or project parameters."""
    found = {}
    seen_types = set()
    try:
        collector = FilteredElementCollector(doc).OfCategoryId(rec.eid).WhereElementIsNotElementType()
        for el in collector:
            try:
                tid = eid_value(el.GetTypeId())
                if tid in seen_types:
                    continue
                seen_types.add(tid)
                for p in el.Parameters:
                    try:
                        if p.IsReadOnly:
                            continue
                        if ('%s' % (p.StorageType,)) in ('None', 'ElementId'):
                            continue
                        name = _param_name(p)
                        if name and name.lower() not in found:
                            found[name.lower()] = name
                    except Exception:
                        continue
            except Exception:
                continue
            if len(seen_types) >= TYPE_SCAN_LIMIT:
                break
    except Exception as ex:
        L.log_debug(u'read_category_params (elements) failed: %s' % ex)
    try:
        it = doc.ParameterBindings.ForwardIterator()
        while it.MoveNext():
            binding = it.Current
            if 'InstanceBinding' not in binding.GetType().Name:
                continue
            for cat in binding.Categories:
                if eid_value(cat.Id) == rec.value:
                    name = L.to_text(it.Key.Name)
                    if name and name.lower() not in found:
                        found[name.lower()] = name
                    break
    except Exception as ex:
        L.log_debug(u'read_category_params (bindings) failed: %s' % ex)
    names = sorted(found.values(), key=lambda n: n.lower())
    return names if names else list(FALLBACK_TARGET_PARAMS)


def spec_of(p):
    try:
        return L.to_text(p.Definition.GetDataType().TypeId)
    except Exception:
        pass
    try:
        return L.to_text(p.Definition.ParameterType)
    except Exception:
        return u''


def snap_param(p):
    storage = L.to_text(p.StorageType)
    has = bool(p.HasValue)
    text = u''
    raw = None
    try:
        if storage == u'String':
            raw = p.AsString() or u''
            text = raw
        elif storage == u'Double':
            raw = p.AsDouble()
            text = p.AsValueString() or u''
        elif storage == u'Integer':
            raw = p.AsInteger()
            text = p.AsValueString() or u'%s' % (raw,)
        elif storage == u'ElementId':
            raw = p.AsElementId()
            text = p.AsValueString() or u''
    except Exception:
        pass
    return Snap(_param_name(p), storage, has, L.to_text(text), raw, spec_of(p))


def space_caption(doc, sp):
    number = name = level = u''
    try:
        number = sp.get_Parameter(BuiltInParameter.ROOM_NUMBER).AsString() or u''
    except Exception:
        pass
    try:
        name = sp.get_Parameter(BuiltInParameter.ROOM_NAME).AsString() or u''
    except Exception:
        pass
    try:
        level = elem_name(sp.Level)
    except Exception:
        pass
    return L.space_caption(number, name, level)


def hold_space(doc, sp):
    """Snapshot every parameter of a space, keyed by name (first one wins)."""
    values = {}
    for p in sp.Parameters:
        try:
            name = _param_name(p)
            if name and name not in values:
                values[name] = snap_param(p)
        except Exception:
            continue
    return SpaceHold(L.to_text(doc.Title), sp.Id, values, space_caption(doc, sp))


def selected_space(uidoc):
    """The space already selected in Revit, if exactly one is."""
    try:
        ids = list(uidoc.Selection.GetElementIds())
        if len(ids) != 1:
            return None
        el = uidoc.Document.GetElement(ids[0])
        if el is not None and el.Category is not None \
                and eid_value(el.Category.Id) == space_category_value():
            return el
    except Exception:
        pass
    return None


def element_label(el):
    """(category, family : type, id) for the activity log."""
    cat = u''
    try:
        cat = L.to_text(el.Category.Name)
    except Exception:
        pass
    fam = u''
    try:
        sym = el.Symbol
        fam = u'%s : %s' % (L.to_text(sym.FamilyName), elem_name(sym))
    except Exception:
        fam = elem_name(el)
    return (cat, fam, eid_value(el.Id))


# ----------------------------------------------------------------------- picking

class CategoryFilter(ISelectionFilter):
    """Lets only elements of one category be picked."""
    __namespace__ = u'RevoBIM.SpaceDataPush'

    def __init__(self, value):
        self.value = value

    def AllowElement(self, e):
        try:
            return e.Category is not None and eid_value(e.Category.Id) == self.value
        except Exception:
            return False

    def AllowReference(self, reference, position):
        return False


def pick_one(uidoc, selection_filter, prompt):
    """One PickObject. Returns the element, or None when the user pressed Esc."""
    try:
        ref = uidoc.Selection.PickObject(ObjectType.Element, selection_filter, prompt)
    except OperationCanceledException:
        return None
    if ref is None:
        return None
    return uidoc.Document.GetElement(ref.ElementId)


# ---------------------------------------------------------------------- writing

class WarningSwallower(IFailuresPreprocessor):
    """Deletes warnings so a run never stops on a dialog."""
    __namespace__ = u'RevoBIM.SpaceDataPush'

    def PreprocessFailures(self, accessor):
        try:
            for failure in list(accessor.GetFailureMessages()):
                if failure.GetSeverity() == FailureSeverity.Warning:
                    accessor.DeleteWarning(failure)
        except Exception:
            pass
        return FailureProcessingResult.Continue


def find_param(el, name):
    """A writable parameter of that name if there is one. GetParameters and
    LookupParameter do not always hand back the same object, and a family can
    carry two parameters of the same name."""
    first = None
    try:
        for p in el.GetParameters(name):
            if first is None:
                first = p
            if not p.IsReadOnly:
                return p
    except Exception:
        pass
    if first is None:
        try:
            first = el.LookupParameter(name)
        except Exception:
            first = None
    return first


def read_current(p, action):
    try:
        if action == u'string':
            return p.AsString() or u''
        if action == u'int':
            return p.AsInteger()
        if action == u'double':
            return p.AsDouble()
        if action == u'valuestring':
            return bool(p.HasValue)
    except Exception:
        pass
    return None


def write_param(p, action, value):
    try:
        if action == u'string':
            return bool(p.Set(value))
        if action == u'int':
            return bool(p.Set(int(value)))
        if action == u'double':
            return bool(p.Set(float(value)))
        if action == u'valuestring':
            return bool(p.SetValueString(value))
    except Exception:
        return False
    return False


def lock_reason(doc, el):
    """Why this element cannot be written, or None. Two different locks: the
    element itself borrowed by someone else, and its workset owned by someone
    else (the element's own checkout status is clean in that case)."""
    try:
        if not doc.IsWorkshared:
            return None
    except Exception:
        return None
    try:
        ids = List[ElementId]()
        ids.Add(el.Id)
        got = WorksharingUtils.CheckoutElements(doc, ids)
        held = [eid_value(i) for i in got]
        if eid_value(el.Id) in held:
            return None
    except Exception:
        pass
    try:
        status = '%s' % (WorksharingUtils.GetCheckoutStatus(doc, el.Id),)
        if status == 'OwnedByOtherUser':
            owner = u''
            try:
                owner = L.to_text(WorksharingUtils.GetWorksharingTooltipInfo(doc, el.Id).Owner)
            except Exception:
                pass
            return u'checked out by %s' % (owner or u'another user')
    except Exception:
        pass
    try:
        ws = doc.GetWorksetTable().GetWorkset(el.WorksetId)
        owner = L.to_text(ws.Owner)
        if owner and owner != L.to_text(doc.Application.Username):
            return u'workset "%s" is owned by %s' % (L.to_text(ws.Name), owner)
    except Exception:
        pass
    return None


class _Planned(object):
    def __init__(self, src, dst, action, value, shown):
        self.src = src
        self.dst = dst
        self.action = action
        self.value = value
        self.shown = shown
        self.wrote = False


def push_to_element(doc, hold, el, mappings, overwrite, skip_blank):
    """Write each mapped space value onto the element.

    mappings is [(space parameter, element parameter)]. Returns [RowResult].
    One transaction per element. Every write is read back afterwards through a
    fresh element lookup, because Revit does not reliably raise when a write
    does not take.
    """
    results = []
    plans = []
    for src_name, dst_name in mappings:
        snap = hold.values.get(src_name)
        if snap is None:
            results.append(RowResult(src_name, dst_name, u'fail',
                                     u'the space has no parameter "%s"' % src_name))
            continue
        p = find_param(el, dst_name)
        if p is None:
            results.append(RowResult(src_name, dst_name, u'fail',
                                     u'this element has no parameter "%s"' % dst_name))
            continue
        if p.IsReadOnly:
            results.append(RowResult(src_name, dst_name, u'fail',
                                     u'"%s" is read-only on this element' % dst_name))
            continue
        storage = L.to_text(p.StorageType)
        action, value, note = L.plan_value(snap, storage, spec_of(p), skip_blank)
        if action == u'skip':
            results.append(RowResult(src_name, dst_name, u'skip', note))
            continue
        current = snap_param(p)
        if (not overwrite) and not L.target_is_blank(storage, current.has, current.text):
            results.append(RowResult(src_name, dst_name, u'skip',
                                     u'already holds "%s" (overwrite is off)' % current.text))
            continue
        if action in (u'string', u'int', u'double') \
                and L.verify_write(action, value, read_current(p, action)) and current.has:
            results.append(RowResult(src_name, dst_name, u'same',
                                     u'already "%s"' % (snap.text,)))
            continue
        plans.append(_Planned(src_name, dst_name, action, value, snap.text))

    if not plans:
        return results

    reason = lock_reason(doc, el)
    if reason:
        for pl in plans:
            results.append(RowResult(pl.src, pl.dst, u'fail', reason))
        return results

    eid = el.Id
    committed = False
    error = u''
    t = Transaction(doc, u'Space Data Push')
    started = False
    try:
        t.Start()
        started = True
        try:
            options = t.GetFailureHandlingOptions()
            options.SetFailuresPreprocessor(WarningSwallower())
            t.SetFailureHandlingOptions(options)
        except Exception:
            pass
        for pl in plans:
            target = find_param(el, pl.dst)
            pl.wrote = bool(target is not None and write_param(target, pl.action, pl.value))
        committed = ('%s' % (t.Commit(),)) == 'Committed'
    except Exception as ex:
        error = L.to_text(ex)
        if started:
            try:
                t.RollBack()
            except Exception:
                pass

    if not committed:
        for pl in plans:
            results.append(RowResult(pl.src, pl.dst, u'fail',
                                     u'Revit did not commit the change %s' % error))
        return results

    fresh = doc.GetElement(eid)
    for pl in plans:
        back = None
        if fresh is not None:
            target = find_param(fresh, pl.dst)
            if target is not None:
                back = read_current(target, pl.action)
        if pl.wrote and L.verify_write(pl.action, pl.value, back):
            results.append(RowResult(pl.src, pl.dst, u'ok', u'written "%s"' % (pl.shown,)))
        elif not pl.wrote:
            results.append(RowResult(pl.src, pl.dst, u'fail',
                                     u'Revit refused the value "%s"' % (pl.shown,)))
        else:
            results.append(RowResult(pl.src, pl.dst, u'fail',
                                     u'the value did not stick (read back "%s")' % L.to_text(back)))
    return results
