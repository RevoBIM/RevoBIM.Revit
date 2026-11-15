# -*- coding: utf-8 -*-
"""Tag Aligner: every read of the model, and the small per-tag writes the
run module strings together.

Measuring a tag: its view bounding box covers the leader as well as the text,
so measured with the leader on, the 'left edge' can be the far end of the
leader. Leaders are switched off inside a SubTransaction, the document is
regenerated, the boxes are read, and the SubTransaction is rolled back so
every leader comes back exactly as it was (the Tag All / Tag Leader Elbow
method). The box is projected onto the view's RightDirection and
UpDirection, never world X and Y, so rotated plans and sections work too.
"""
import ta_clr  # noqa: F401  must stay first

from System.Collections.Generic import List
from Autodesk.Revit.DB import (
    BuiltInParameter,
    ElementId,
    ElementTransformUtils,
    FilteredElementCollector,
    IndependentTag,
    SpatialElementTag,
    SubTransaction,
    TextElement,
    TextElementType,
    WorksharingUtils,
    XYZ,
)
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType

import ta_core as core

NO_DRAWING_PLANE = (
    u"Schedule", u"DrawingSheet", u"ProjectBrowser", u"SystemBrowser",
    u"Internal", u"Undefined", u"Report", u"PanelSchedule",
    u"ColumnSchedule", u"CostReport", u"LoadsReport", u"PresureLossReport",
    u"Walkthrough", u"Rendering",
)


# ==========================================================================
# Revit 2024 to 2027 helpers
# ==========================================================================

def eid_value(element_id):
    """ElementId.IntegerValue is gone in 2026; prefer Value, fall back."""
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


def bip(name):
    """BuiltInParameter member looked up at call time, never at load."""
    return getattr(BuiltInParameter, name, None)


def is_tag(element):
    return isinstance(element, IndependentTag) or \
        isinstance(element, SpatialElementTag)


def tag_label(doc, tag):
    """'Family : Type (id 123)' for reports; never lets a name read throw."""
    ident = u"id {0}".format(eid_value(tag.Id))
    try:
        sym = doc.GetElement(tag.GetTypeId())
        fam = getattr(sym, "FamilyName", None)
        typ = None
        try:
            typ = sym.Name
        except Exception:
            typ = None
        if fam and typ:
            return u"{0} : {1} ({2})".format(fam, typ, ident)
        if fam:
            return u"{0} ({1})".format(fam, ident)
    except Exception:
        pass
    return u"Tag ({0})".format(ident)


class TagFilter(ISelectionFilter):
    def AllowElement(self, element):
        try:
            return is_tag(element)
        except Exception:
            return False

    def AllowReference(self, reference, position):
        return False


# ==========================================================================
# View
# ==========================================================================

def view_axes(view):
    """(right, up) unit vectors of the view, or None for a view tags cannot
    live in."""
    if view is None:
        return None
    try:
        vtype = u"{0}".format(view.ViewType).split(u".")[-1]
        if vtype in NO_DRAWING_PLANE:
            return None
    except Exception:
        pass
    try:
        right = view.RightDirection.Normalize()
        up = view.UpDirection.Normalize()
        return right, up
    except Exception:
        return None


def view_scale(view):
    try:
        s = int(view.Scale)
        return s if s > 0 else 1
    except Exception:
        return 1


# ==========================================================================
# Selection
# ==========================================================================

def selected_tags(uidoc, view):
    """(tags in this view in selection order, selected count, elsewhere)."""
    doc = uidoc.Document
    view_key = eid_value(view.Id)
    tags = []
    count = 0
    elsewhere = 0
    try:
        ids = list(uidoc.Selection.GetElementIds())
    except Exception:
        ids = []
    for eid in ids:
        count += 1
        element = doc.GetElement(eid)
        if element is None or not is_tag(element):
            continue
        if eid_value(element.OwnerViewId) != view_key:
            elsewhere += 1
            continue
        tags.append(element)
    return tags, count, elsewhere


def pick_tags(uidoc, view):
    """PickObjects; the caller catches OperationCanceledException."""
    doc = uidoc.Document
    refs = uidoc.Selection.PickObjects(
        ObjectType.Element, TagFilter(),
        u"Select the tags, then click Finish")
    view_key = eid_value(view.Id)
    out = []
    for r in refs:
        element = doc.GetElement(r)
        if element is not None and is_tag(element) and \
                eid_value(element.OwnerViewId) == view_key:
            out.append(element)
    return out


def pick_reference(uidoc):
    """One click: the tag the others align to."""
    r = uidoc.Selection.PickObject(
        ObjectType.Element, TagFilter(),
        u"Click the tag to align the others to")
    return uidoc.Document.GetElement(r)


def set_selection(uidoc, tags):
    try:
        ids = List[ElementId]()
        for t in tags:
            ids.Add(t.Id)
        uidoc.Selection.SetElementIds(ids)
    except Exception:
        pass


# ==========================================================================
# Workshared ownership
# ==========================================================================

def checkout(doc, tags):
    """Set of id values this user can edit. Called OUTSIDE a transaction.
    CheckoutElements returns what the user now holds; the rest belong to
    someone else."""
    keys = set(eid_value(t.Id) for t in tags)
    try:
        if not doc.IsWorkshared:
            return keys
    except Exception:
        return keys
    try:
        ids = List[ElementId]()
        for t in tags:
            ids.Add(t.Id)
        got = WorksharingUtils.CheckoutElements(doc, ids)
        return set(eid_value(i) for i in got)
    except Exception:
        return keys


# ==========================================================================
# Text height, read from the tag families
# ==========================================================================

def _param_double(element, param_name):
    pid = bip(param_name)
    if element is None or pid is None:
        return None
    try:
        p = element.get_Parameter(pid)
        if p is None or not p.HasValue:
            return None
        v = p.AsDouble()
        return v if v > 0 else None
    except Exception:
        return None


def family_text_size(doc, family):
    """Largest label/text size in a tag family, in PAPER feet, or None.

    Opens the family with EditFamily, which cannot happen inside a
    transaction, so the run calls this before it starts one."""
    if family is None:
        return None
    try:
        if not family.IsEditable:
            return None
    except Exception:
        pass
    fdoc = None
    already_open = _open_family_doc(doc, family)
    try:
        fdoc = already_open if already_open is not None else \
            doc.EditFamily(family)
        sizes = []
        collector = FilteredElementCollector(fdoc).WhereElementIsNotElementType()
        for element in collector.ToElements():
            if isinstance(element, TextElement):
                v = _param_double(fdoc.GetElement(element.GetTypeId()),
                                  "TEXT_SIZE")
                if v:
                    sizes.append(v)
        if not sizes:
            for ttype in FilteredElementCollector(fdoc).OfClass(
                    TextElementType).ToElements():
                v = _param_double(ttype, "TEXT_SIZE")
                if v:
                    sizes.append(v)
        return max(sizes) if sizes else None
    except Exception:
        return None
    finally:
        # Never close a family the user already has open in the editor.
        if fdoc is not None and already_open is None:
            try:
                fdoc.Close(False)
            except Exception:
                pass


def _open_family_doc(doc, family):
    """The family's document if the user already has it open, else None."""
    try:
        name = family.Name
    except Exception:
        return None
    try:
        for other in doc.Application.Documents:
            try:
                if other.IsFamilyDocument and \
                        other.OwnerFamily.Name == name and \
                        other.Title.lower().replace(u".rfa", u"") == name.lower():
                    return other
            except Exception:
                continue
    except Exception:
        return None
    return None


def text_height(doc, tags, settings, log):
    """(paper feet, where it came from). Largest text across the families."""
    fixed = settings[u"text_height_mm"] / core.MM_PER_FOOT
    if settings[u"text_height_source"] != u"auto":
        return fixed, u"the fixed setting"
    seen = {}
    for t in tags:
        try:
            sym = doc.GetElement(t.GetTypeId())
            family = sym.Family
            key = eid_value(family.Id)
        except Exception:
            continue
        if key in seen:
            continue
        seen[key] = family_text_size(doc, family)
        log.add(u"text size family {0}: {1}".format(
            key, u"none found" if seen[key] is None else u"{0:.2f} mm".format(
                seen[key] * core.MM_PER_FOOT)))
    found = [v for v in seen.values() if v]
    if not found:
        return fixed, u"the fixed setting (no text found in the tag families)"
    return max(found), u"the tag families"


# ==========================================================================
# Measuring (inside an open transaction)
# ==========================================================================

def project_box(bb, right, up, key):
    try:
        transform = bb.Transform
    except Exception:
        transform = None
    us = []
    vs = []
    for x in (bb.Min.X, bb.Max.X):
        for y in (bb.Min.Y, bb.Max.Y):
            for z in (bb.Min.Z, bb.Max.Z):
                p = XYZ(x, y, z)
                if transform is not None:
                    try:
                        p = transform.OfPoint(p)
                    except Exception:
                        pass
                us.append(p.DotProduct(right))
                vs.append(p.DotProduct(up))
    return core.Box(key, min(us), max(us), min(vs), max(vs))


def measure_boxes(doc, view, tags, right, up):
    """{key: Box} with every leader switched off, then put back."""
    boxes = {}
    sub = SubTransaction(doc)
    sub.Start()
    try:
        for t in tags:
            try:
                if t.HasLeader:
                    t.HasLeader = False
            except Exception:
                pass
        doc.Regenerate()
        for t in tags:
            try:
                bb = t.get_BoundingBox(view)
            except Exception:
                bb = None
            if bb is None:
                continue
            key = eid_value(t.Id)
            boxes[key] = project_box(bb, right, up, key)
    finally:
        try:
            sub.RollBack()
        except Exception:
            pass
    return boxes


# ==========================================================================
# Leader elbows and moving a tag
# ==========================================================================

def _has_leader(tag):
    try:
        return bool(tag.HasLeader)
    except Exception:
        return False


def read_elbows(tag):
    """[(reference or None, point)]. Revit 2022+ IndependentTag keeps one
    elbow per tagged reference; room and space tags keep the older single
    LeaderElbow."""
    out = []
    if not _has_leader(tag):
        return out
    get_refs = getattr(tag, "GetTaggedReferences", None)
    if get_refs is not None and hasattr(tag, "GetLeaderElbow"):
        try:
            for ref in get_refs():
                try:
                    if tag.HasLeaderElbow(ref):
                        out.append((ref, tag.GetLeaderElbow(ref)))
                except Exception:
                    pass
            return out
        except Exception:
            out = []
    try:
        if getattr(tag, "HasElbow", False):
            out.append((None, tag.LeaderElbow))
    except Exception:
        pass
    return out


def write_elbow(tag, ref, point):
    if ref is not None:
        tag.SetLeaderElbow(ref, point)
    else:
        tag.LeaderElbow = point


def move_tag(doc, tag, vector, move_elbows):
    """Move a tag's head by vector; returns [(ref, expected elbow)].

    With a leader: head first, THEN the elbows, from points read before the
    head moved. Assigning the head leaves the elbow where it was, so the
    elbow has to be carried explicitly or the leader goes diagonal.
    Without a leader the whole tag is simply moved."""
    if not _has_leader(tag):
        ElementTransformUtils.MoveElement(doc, tag.Id, vector)
        return []
    elbows = read_elbows(tag) if move_elbows else []
    tag.TagHeadPosition = tag.TagHeadPosition.Add(vector)
    expected = []
    for ref, point in elbows:
        target = point.Add(vector)
        write_elbow(tag, ref, target)
        expected.append((ref, target))
    return expected
