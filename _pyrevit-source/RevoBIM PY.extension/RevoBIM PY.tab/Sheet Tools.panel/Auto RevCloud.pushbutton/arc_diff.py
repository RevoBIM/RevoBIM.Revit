# -*- coding: utf-8 -*-
u"""Auto RevCloud - reading elements out of the host view and the link.

Everything here talks to Revit; the rules it feeds live in arc_compare.py.
"""
import arc_clr  # noqa: F401

import arc_core
import arc_compare
import arc_model

from Autodesk.Revit.DB import (FilteredElementCollector, ElementId,
                               RevitLinkInstance, BuiltInCategory, XYZ,
                               BuiltInParameter, CategoryType, Outline,
                               BoundingBoxIntersectsFilter, StorageType)


# ==========================================================================
# the links in the project
# ==========================================================================

def link_instances(doc):
    u"""[{id, name, loaded, doc_title}] for every Revit link placed in the
    project. Unloaded links are listed but marked, rather than being left out
    and then failing when one is picked."""
    rows = []
    try:
        collector = FilteredElementCollector(doc).OfClass(RevitLinkInstance)
    except Exception:
        return rows
    counts = {}
    for instance in collector:
        try:
            link_doc = instance.GetLinkDocument()
        except Exception:
            link_doc = None
        name = arc_model.element_name(instance)
        try:
            type_element = doc.GetElement(instance.GetTypeId())
            if type_element is not None:
                name = arc_model.element_name(type_element) or name
        except Exception:
            pass
        counts[name] = counts.get(name, 0) + 1
        label = name if counts[name] == 1 else u"{0} ({1})".format(name, counts[name])
        title = u""
        if link_doc is not None:
            try:
                title = arc_core.unicode_str(link_doc.Title)
            except Exception:
                title = u""
        rows.append({
            u"id": arc_model.eid_value(instance.Id),
            u"name": label,
            u"loaded": link_doc is not None,
            u"doc_title": title,
        })
    rows.sort(key=lambda r: arc_core.natural_key(r[u"name"]))
    return rows


def numbering_sequences(doc):
    u"""The revision numbering sequences in the project, as [(id, name)].

    Revit 2022 replaced `Revision.NumberType` with a numbering sequence
    element, and both still exist on the releases this tool runs on. Where the
    class is not there, an empty list is returned and the caller falls back to
    the old enum - which is why this reports rather than raises.
    """
    out = []
    try:
        from Autodesk.Revit.DB import RevisionNumberingSequence
    except Exception:
        return out
    try:
        collector = FilteredElementCollector(doc).OfClass(RevisionNumberingSequence)
    except Exception:
        return out
    for sequence in collector:
        try:
            out.append((arc_model.eid_value(sequence.Id),
                        arc_model.element_name(sequence)))
        except Exception:
            continue
    out.sort(key=lambda row: arc_core.natural_key(row[1]))
    return out


def apply_revision_fields(revision, details, doc=None):
    u"""Write the dialog's fields onto a revision, reporting what would not
    take.

    Each field is set on its own and READ BACK. Revit does not reliably raise
    when a write does not take, and a revision quietly missing its issued-to
    is worse than one that says so.
    """
    notes = []

    # Un-issue FIRST where it is being turned off. An issued revision is
    # read-only, so every field after it would be refused; turning it off
    # last would be the same mistake in reverse. Issued is therefore handled
    # at whichever end of this function makes the rest of it work.
    if details.get(u"issued") is False:
        try:
            if revision.Issued:
                revision.Issued = False
        except Exception as exc:
            notes.append(u"could not un-issue it: {0}".format(
                arc_core.unicode_str(exc)[:70]))

    def put(name, value, check=True):
        if value is None:
            return
        try:
            setattr(revision, name, value)
        except Exception as exc:
            notes.append(u"{0}: {1}".format(name, arc_core.unicode_str(exc)[:70]))
            return
        if not check:
            return
        try:
            if arc_core.unicode_str(getattr(revision, name)) != arc_core.unicode_str(value):
                notes.append(u"{0} did not take".format(name))
        except Exception:
            pass

    put(u"Description", details.get(u"description"))
    put(u"RevisionDate", details.get(u"date"))
    put(u"IssuedBy", details.get(u"issued_by"))
    put(u"IssuedTo", details.get(u"issued_to"))

    show = details.get(u"visibility")
    if show:
        try:
            from Autodesk.Revit.DB import RevisionVisibility
            value = getattr(RevisionVisibility, show, None)
            if value is not None:
                revision.Visibility = value
            else:
                notes.append(u"this release has no '{0}' visibility".format(show))
        except Exception as exc:
            notes.append(u"Show: {0}".format(arc_core.unicode_str(exc)[:70]))

    sequence_id = details.get(u"sequence_id")
    if sequence_id:
        try:
            revision.RevisionNumberingSequenceId = arc_model.make_id(sequence_id)
        except Exception as exc:
            notes.append(u"numbering sequence: {0}".format(
                arc_core.unicode_str(exc)[:70]))
    else:
        number_type = details.get(u"number_type")
        if number_type:
            try:
                from Autodesk.Revit.DB import RevisionNumberType
                value = getattr(RevisionNumberType, number_type, None)
                if value is not None:
                    revision.NumberType = value
            except Exception:
                notes.append(u"numbering could not be set on this release")

    # ...and issue LAST where it is being turned on, for the same reason.
    if details.get(u"issued"):
        try:
            revision.Issued = True
        except Exception as exc:
            notes.append(u"Issued: {0}".format(arc_core.unicode_str(exc)[:70]))
    return notes


def link_state(doc, link):
    u"""Why a link cannot be read, or None when it can.

    Worth checking rather than discovering: a link whose workset is CLOSED is
    not in memory at all, and reading elements out of a document in that state
    is not something to attempt. A workset merely set "not visible in all
    views" is a different thing entirely and is fine - the link side is read
    straight out of the linked document, not through a view, so nothing about
    host visibility applies to it.
    """
    try:
        if link.GetLinkDocument() is None:
            return (u"that link is not loaded, so there is nothing to compare "
                    u"against - load it in Manage Links and try again")
    except Exception:
        return u"that link could not be opened"
    try:
        table = doc.GetWorksetTable()
        workset = table.GetWorkset(link.WorksetId)
        if workset is not None and not workset.IsOpen:
            return (u"the link sits on workset '{0}', which is closed in this "
                    u"session. Open it and try again.".format(
                        arc_core.unicode_str(workset.Name)))
    except Exception:
        pass
    return None


def link_by_id(doc, link_id):
    element = doc.GetElement(arc_model.make_id(link_id))
    if element is None:
        raise RuntimeError(u"that link is no longer in the project")
    return element


# ==========================================================================
# categories
# ==========================================================================

def all_model_categories(doc):
    u"""Every model category the document has, straight off the category table.

    Read from `doc.Settings.Categories` rather than by counting elements.
    Counting meant walking every element in the project to build a list -
    slow on a real model, and slow inside a modeless window is the worst place
    for it. It also hid categories that are perfectly valid to compare and
    simply have nothing in them yet.

    Model categories only: annotation is never compared. Sorted by name.
    """
    rows = []
    seen = set()
    try:
        categories = doc.Settings.Categories
    except Exception:
        return rows
    for category in categories:
        try:
            if category.CategoryType != CategoryType.Model:
                continue
            name = arc_core.unicode_str(category.Name)
        except Exception:
            continue
        key = name.strip().lower()
        if not name or key in seen:
            continue
        seen.add(key)
        rows.append({u"name": name})
    rows.sort(key=lambda r: arc_core.natural_key(r[u"name"]))
    return rows


def resolve_categories(doc, names):
    u"""The BuiltInCategory for each named category, as [(name, bic)], plus
    the names that could not be resolved.

    `Category.BuiltInCategory` is the only route. It exists on every release
    this tool runs on, and the alternative - reading the category's id as an
    integer and casting it to the enum - can manufacture a value that is not
    a member at all. A value like that going into a native element filter is
    the shape of a hard crash rather than an exception, and the reading phase
    is where Revit went down. OST_INVALID is refused for the same reason.
    """
    wanted = {}
    for name in names:
        wanted[arc_core.unicode_str(name).strip().lower()] = name
    out = []
    seen = set()
    try:
        categories = doc.Settings.Categories
    except Exception:
        return out, list(names)
    for category in categories:
        try:
            key = arc_core.unicode_str(category.Name).strip().lower()
        except Exception:
            continue
        if key not in wanted or key in seen:
            continue
        try:
            bic = category.BuiltInCategory
        except Exception:
            continue
        if bic is None or _is_invalid(bic):
            continue
        seen.add(key)
        out.append((wanted[key], bic))
    resolved = set(n for n, _b in out)
    missing = [n for n in names if n not in resolved]
    return out, missing


def _is_invalid(bic):
    try:
        return arc_core.unicode_str(bic).upper().endswith(u"INVALID")
    except Exception:
        return False


def _collect(doc, bic, outline=None):
    u"""Every instance of one category, or None when Revit refuses it.

    **Never scoped to a view.** `FilteredElementCollector(doc, view.Id)`
    applies view visibility, and to do that Revit has to generate the
    view-specific graphics of everything in the view. On a real drainage plan
    that was eleven thousand elements' worth of geometry built purely to
    answer "which of these are visible", and the journal from the crash ends
    inside exactly that - `updateGReps 11026 elements`, with memory falling.

    Scoped with a bounding box quick filter instead. A quick filter reads the
    element record and nothing else: no geometry, no view graphics, no
    regeneration. Visibility is then decided per element with the cheap tests
    in `_visible_in`.

    One collector per category on purpose: a single multi-category filter
    fails as a whole on the first category Revit will not accept, so failing
    per category keeps the rest of the comparison alive.
    """
    try:
        collector = FilteredElementCollector(doc).OfCategory(bic)
        collector = collector.WhereElementIsNotElementType()
        if outline is not None:
            collector = collector.WherePasses(BoundingBoxIntersectsFilter(outline))
        return list(collector)
    except Exception:
        return None


def view_outline(view, pad_ft=2.0):
    u"""The view's crop as a world-coordinate Outline, or None.

    None means the view has no crop and everything is in scope, which is
    correct if slower.
    """
    try:
        if not view.CropBoxActive:
            return None
        box = view.CropBox
        transform = box.Transform
    except Exception:
        return None
    try:
        corners = []
        for x in (box.Min.X, box.Max.X):
            for y in (box.Min.Y, box.Max.Y):
                for z in (box.Min.Z, box.Max.Z):
                    corners.append(transform.OfPoint(XYZ(x, y, z)))
        lo = XYZ(min(c.X for c in corners) - pad_ft,
                 min(c.Y for c in corners) - pad_ft,
                 min(c.Z for c in corners) - pad_ft)
        hi = XYZ(max(c.X for c in corners) + pad_ft,
                 max(c.Y for c in corners) + pad_ft,
                 max(c.Z for c in corners) + pad_ft)
        return Outline(lo, hi)
    except Exception:
        return None


def outline_into(outline, transform):
    u"""A host-space Outline expressed in a link's own coordinates."""
    if outline is None or transform is None:
        return None
    try:
        inverse = transform.Inverse
        lo, hi = outline.MinimumPoint, outline.MaximumPoint
        corners = []
        for x in (lo.X, hi.X):
            for y in (lo.Y, hi.Y):
                for z in (lo.Z, hi.Z):
                    corners.append(inverse.OfPoint(XYZ(x, y, z)))
        return Outline(
            XYZ(min(c.X for c in corners), min(c.Y for c in corners),
                min(c.Z for c in corners)),
            XYZ(max(c.X for c in corners), max(c.Y for c in corners),
                max(c.Z for c in corners)))
    except Exception:
        return None


def _visible_in(element, view, hidden_categories):
    u"""Is this element actually drawn in the view?

    Cheap tests only - the element's own hidden flag and its category's
    visibility - because the expensive one is what crashed. An element hidden
    by a view filter or by a phase setting is not caught here and will be
    compared; over-comparing is the right way to be wrong, since the worst it
    produces is a cloud round something the drawing does not show, and the
    alternative is regenerating the whole view to find out.
    """
    try:
        category = element.Category
        if category is not None and arc_model.eid_value(category.Id) in hidden_categories:
            return False
    except Exception:
        pass
    try:
        return not element.IsHidden(view)
    except Exception:
        return True


def hidden_category_names(doc, view, names):
    u"""Of the names asked for, those the view does not draw.

    Used to drop them from BOTH sides. The link is read out of the linked
    document with no view involved, so a category switched off in the host
    view was being read there and nowhere in the host - every element of it
    in the link then looked like a deletion and got clouded. The comparison
    has to ask the same question of both models or it invents changes.
    """
    resolved, _missing = resolve_categories(doc, names)
    hidden_ids = _hidden_categories(doc, view, resolved)
    if not hidden_ids:
        return []
    out = []
    for name, bic in resolved:
        try:
            category = doc.Settings.Categories.get_Item(bic)
            if category is not None and arc_model.eid_value(category.Id) in hidden_ids:
                out.append(name)
        except Exception:
            continue
    return out


def still_in_host(doc, changes):
    u"""Drop 'removed' changes for elements that are still in the model.

    A removal means the element is gone, not that this view does not draw it.
    An element hidden in the view - by the hide command, or by sitting outside
    the crop after being moved - is missing from the host side and present in
    the link, which looks identical to a deletion from here. Asking the host
    document whether it still holds that element is the difference, and it is
    one cheap lookup per removal rather than per element.

    Returns (kept, dropped_count).
    """
    kept = []
    dropped = 0
    for change in changes:
        if change.get(u"kind") != u"removed":
            kept.append(change)
            continue
        found = None
        try:
            found = doc.GetElement(change[u"key"])
        except Exception:
            found = None
        if found is None:
            kept.append(change)
        else:
            dropped += 1
    return kept, dropped


def _hidden_categories(doc, view, resolved):
    out = set()
    for _name, bic in resolved:
        try:
            category = doc.Settings.Categories.get_Item(bic)
            if category is None:
                continue
            if view.GetCategoryHidden(category.Id):
                out.add(arc_model.eid_value(category.Id))
        except Exception:
            continue
    return out


# ==========================================================================
# reading elements
# ==========================================================================

def _bbox_of(element, view=None):
    try:
        box = element.get_BoundingBox(view)
    except Exception:
        box = None
    if box is None:
        try:
            box = element.get_BoundingBox(None)
        except Exception:
            box = None
    return box


def _type_name(doc, element):
    try:
        type_id = element.GetTypeId()
    except Exception:
        return u""
    if arc_model.eid_value(type_id) <= 0:
        return u""
    try:
        return arc_model.element_name(doc.GetElement(type_id))
    except Exception:
        return u""


def _location(element, transform):
    u"""(ends, rotation) for an element, both cheap to read.

    `Location` is a property of the element record - no geometry is built and
    no view is touched - so this costs nothing next to the bounding box that
    is already being read.

    It catches what a bounding box cannot: a fitting ROTATED in place, a pipe
    RE-ROUTED inside the same envelope, an element flipped. All of those leave
    the box identical and were being reported as unchanged.
    """
    ends = None
    rotation = None
    try:
        location = element.Location
    except Exception:
        return None, None
    if location is None:
        return None, None
    try:
        curve = location.Curve
    except Exception:
        curve = None
    if curve is not None:
        try:
            a = curve.GetEndPoint(0)
            b = curve.GetEndPoint(1)
            if transform is not None:
                a = transform.OfPoint(a)
                b = transform.OfPoint(b)
            ends = ((a.X, a.Y, a.Z), (b.X, b.Y, b.Z))
        except Exception:
            ends = None
    else:
        try:
            point = location.Point
            if transform is not None:
                point = transform.OfPoint(point)
            ends = ((point.X, point.Y, point.Z), (point.X, point.Y, point.Z))
        except Exception:
            ends = None
        try:
            rotation = float(location.Rotation)
        except Exception:
            rotation = None
    return ends, rotation


def _basis(element, transform):
    u"""The element's own placement axes, as two unit vectors, or None.

    `FamilyInstance.GetTransform()` is read off the element record - no
    geometry, no view - and it says which way the family is actually facing in
    three dimensions. `Location.Rotation` only knows about turning around Z,
    so it misses a fitting rolled about the run it sits on, and it does not
    exist at all for an element placed on a curve.

    The flip flags come with it: a mirrored family occupies exactly the same
    bounding box, at exactly the same angle, and is a real change on a
    drawing.
    """
    try:
        placement = element.GetTransform()
    except Exception:
        return None
    try:
        x = placement.BasisX
        z = placement.BasisZ
        if transform is not None:
            x = transform.OfVector(x)
            z = transform.OfVector(z)
        basis = ((x.X, x.Y, x.Z), (z.X, z.Y, z.Z))
    except Exception:
        return None
    flips = 0
    try:
        if element.HandFlipped:
            flips += 1
        if element.FacingFlipped:
            flips += 2
    except Exception:
        pass
    return (basis, flips)


def _params(element, names):
    u"""The named parameters as text, for the ones the element carries.

    A cheap value read, no geometry. Catches a change that moves nothing and
    resizes nothing - a system reassigned, a reference level changed, an
    offset edited on a symmetric fitting.
    """
    out = {}
    if not names:
        return out
    for name in names:
        try:
            param = element.LookupParameter(name)
        except Exception:
            param = None
        if param is None:
            continue
        try:
            if param.StorageType == StorageType.String:
                value = param.AsString()
            elif param.StorageType == StorageType.Double:
                value = u"{0:.4f}".format(param.AsDouble())
            elif param.StorageType == StorageType.Integer:
                value = u"{0}".format(param.AsInteger())
            elif param.StorageType == StorageType.ElementId:
                value = u"{0}".format(arc_model.eid_value(param.AsElementId()))
            else:
                value = param.AsValueString()
            out[name] = arc_core.unicode_str(value or u"")
        except Exception:
            continue
    return out


def _category_name(element):
    try:
        category = element.Category
        if category is None:
            return u""
        return arc_core.unicode_str(category.Name)
    except Exception:
        return u""


# A category that returns more than this is not a comparison anybody wants to
# read, and grinding through it is how a modeless window stops responding.
MAX_ELEMENTS = 200000


def _safe_item(doc, element, transform=None, param_names=None):
    u"""_item, with the whole read guarded.

    One element that will not give up its geometry must not take the run with
    it. Nested links, imported CAD and elements on a workset that is closed in
    the document being read are the usual offenders, and none of them is worth
    losing a comparison over.
    """
    try:
        return _item(doc, element, transform, param_names)
    except Exception:
        return None


def _item(doc, element, transform=None, param_names=None):
    u"""One element reduced to what the comparison needs, or None.

    The MODEL bounding box, on both sides. The view has already decided which
    elements are present; asking for the view-specific box as well hands back
    one clipped to the crop, and an element crossing the crop edge then reads
    as resized against its full box in the link. Same box, same rules, both
    sides.
    """
    box = _bbox_of(element, None)
    if box is None:
        return None
    lo, hi = box.Min, box.Max
    centre = XYZ((lo.X + hi.X) / 2.0, (lo.Y + hi.Y) / 2.0, (lo.Z + hi.Z) / 2.0)
    size = (abs(hi.X - lo.X), abs(hi.Y - lo.Y), abs(hi.Z - lo.Z))
    if transform is not None:
        try:
            centre = transform.OfPoint(centre)
        except Exception:
            pass
        # The size is left in the link's own axes on purpose: a link is placed
        # by a translation and usually a rotation about Z, and a bounding box
        # cannot be rotated without growing. Comparing sizes rather than
        # boxes means the axes only have to agree, not the placement.
    try:
        key = arc_core.unicode_str(element.UniqueId)
    except Exception:
        return None
    ends, rotation = _location(element, transform)
    basis = _basis(element, transform)
    # The one property that changes on ANY edit to the element - geometry
    # reshaped inside the same box, a parameter not on the list, a host
    # reassigned. One read, no geometry. Whether it survives a Save As is the
    # question the run reports on, not something assumed either way.
    try:
        version = arc_core.unicode_str(element.VersionGuid)
    except Exception:
        version = u""
    return {
        u"key": key,
        u"version": version,
        u"ends": ends,
        u"rot": rotation,
        u"basis": basis[0] if basis else None,
        u"flips": basis[1] if basis else None,
        u"params": _params(element, param_names),
        # The second key. A UniqueId survives a Save As; an ElementId survives
        # some routes a UniqueId does not. Carrying both costs nothing and the
        # matching tries them in that order.
        u"eid": arc_model.eid_value(element.Id),
        u"category": _category_name(element),
        u"type": _type_name(doc, element),
        u"centre": (centre.X, centre.Y, centre.Z),
        u"size": size,
    }


def host_items(doc, view, names, log=None, param_names=None):
    u"""Everything of the listed categories that this view draws.

    Scoped by the view's crop with a quick filter, then narrowed by the cheap
    visibility tests. Never by a view-scoped collector - see `_collect`.

    Returns (items, matched_names, missing_names, refused_names).
    """
    resolved, missing = resolve_categories(doc, names)
    outline = view_outline(view)
    hidden = _hidden_categories(doc, view, resolved)
    items = []
    refused = []
    for name, bic in resolved:
        found = _collect(doc, bic, outline)
        if found is None:
            refused.append(name)
            if log:
                log(u"  {0}: REFUSED by Revit".format(name))
            continue
        if log:
            # Logged after the collector and before the reads, so the last
            # line says which of the two Revit was in when it went down.
            log(u"  {0}: {1} element(s), reading".format(name, len(found)))
        kept = 0
        for element in found:
            if not _visible_in(element, view, hidden):
                continue
            entry = _safe_item(doc, element, None, param_names)
            if entry is None:
                continue
            items.append(entry)
            kept += 1
            if len(items) > MAX_ELEMENTS:
                refused.append(u"{0} (over {1} elements)".format(name, MAX_ELEMENTS))
                break
        if log:
            log(u"  {0}: {1} kept".format(name, kept))
    return items, [n for n, _b in resolved], missing, refused


def link_items(link_doc, transform, names, outline=None, log=None,
               param_names=None):
    u"""Everything of the listed categories in the link, in host coordinates.

    `outline` is the host view's crop; it is turned into the link's own
    coordinates so the same quick filter can do the scoping there, rather than
    reading a whole previous version of the model and throwing most of it
    away.

    Returns (items, matched_names, missing_names, refused_names).
    """
    resolved, missing = resolve_categories(link_doc, names)
    local = outline_into(outline, transform)
    items = []
    refused = []
    for name, bic in resolved:
        found = _collect(link_doc, bic, local)
        if found is None:
            refused.append(name)
            if log:
                log(u"  {0}: REFUSED by the link".format(name))
            continue
        if log:
            log(u"  {0}: {1} element(s) in the link, reading".format(
                name, len(found)))
        for element in found:
            entry = _safe_item(link_doc, element, transform, param_names)
            if entry is None:
                continue
            items.append(entry)
            if len(items) > MAX_ELEMENTS:
                refused.append(u"{0} (over {1} elements)".format(name, MAX_ELEMENTS))
                break
    return items, [n for n, _b in resolved], missing, refused




def view_frame(view):
    u"""(origin, right, up) for the view, as plain tuples in feet."""
    try:
        origin = view.Origin
        right = view.RightDirection
        up = view.UpDirection
        return ((origin.X, origin.Y, origin.Z),
                (right.X, right.Y, right.Z),
                (up.X, up.Y, up.Z))
    except Exception:
        return ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0))


def frame_to_model(u_value, v_value, origin, right, up):
    u"""Back from view coordinates to a model point."""
    return XYZ(origin[0] + right[0] * u_value + up[0] * v_value,
               origin[1] + right[1] * u_value + up[1] * v_value,
               origin[2] + right[2] * u_value + up[2] * v_value)


def set_comment(element, text):
    u"""Write the description onto the cloud's Comments parameter.

    Read back afterwards: Revit does not reliably raise when a write does not
    take, which this extension has been caught by more than once.
    """
    if not text:
        return True
    try:
        bip = getattr(BuiltInParameter, u"ALL_MODEL_INSTANCE_COMMENTS")
        param = element.get_Parameter(bip)
    except Exception:
        param = None
    if param is None:
        try:
            for candidate in element.GetParameters(u"Comments"):
                if not candidate.IsReadOnly:
                    param = candidate
                    break
        except Exception:
            param = None
    if param is None or param.IsReadOnly:
        return False
    try:
        param.Set(text)
    except Exception:
        return False
    try:
        return arc_core.unicode_str(param.AsString() or u"") == text
    except Exception:
        return True
