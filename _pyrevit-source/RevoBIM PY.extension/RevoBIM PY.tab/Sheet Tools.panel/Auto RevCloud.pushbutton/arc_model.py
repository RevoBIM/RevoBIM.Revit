# -*- coding: utf-8 -*-
"""Auto RevCloud - everything that reads the model.  No writes live here."""
import arc_clr  # noqa: F401
import arc_core

from System import Int64
from Autodesk.Revit.DB import (FilteredElementCollector, ViewSheet, Revision,
                               BuiltInCategory, XYZ, ElementId, View,
                               Viewport)


# ==========================================================================
# ids
# ==========================================================================

def eid_value(element_id):
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


def make_id(value):
    """An ElementId from an integer, or straight back if it already is one.

    ElementId(Int64) exists from 2024 and is the only constructor left once
    the int one goes; the int form is kept as a fallback. Passing an ElementId
    back unchanged makes this safe to call on anything, which is the point of
    having it - a caller should never have to know which it is holding.
    """
    if isinstance(value, ElementId):
        return value
    try:
        return ElementId(Int64(value))
    except Exception:
        return ElementId(int(value))


def views_on_sheet(doc, sheet_id):
    """The views placed on a sheet, as rows for the window.

    A sheet is a container - the elements live in the views on it, and the
    comparison reads a view. Legends and schedules are left out: they hold no
    model elements to compare and will not take a revision cloud anyway.
    """
    rows = []
    sheet = sheet_by_id(doc, sheet_id)
    if sheet is None:
        return rows
    try:
        ids = sheet.GetAllViewports()
    except Exception:
        return rows
    for vp_id in ids:
        try:
            viewport = doc.GetElement(vp_id)
            view = doc.GetElement(viewport.ViewId)
        except Exception:
            continue
        if view is None:
            continue
        try:
            kind = arc_core.unicode_str(view.ViewType)
        except Exception:
            kind = u""
        if kind in (u"Legend", u"Schedule", u"ColumnSchedule", u"PanelSchedule"):
            continue
        rows.append({
            u"kind": u"view",
            u"id": eid_value(view.Id),
            u"number": arc_core.unicode_str(sheet.SheetNumber),
            u"name": element_name(view),
            u"label": u"{0} - {1}".format(arc_core.unicode_str(sheet.SheetNumber),
                                          element_name(view)),
        })
    return rows


def all_views(doc):
    """Every view that could carry a revision cloud, for the picker."""
    rows = []
    try:
        collector = FilteredElementCollector(doc).OfClass(View)
    except Exception:
        return rows
    for view in collector:
        try:
            if view.IsTemplate:
                continue
            kind = arc_core.unicode_str(view.ViewType)
        except Exception:
            continue
        if kind in (u"Legend", u"Schedule", u"ColumnSchedule", u"PanelSchedule",
                    u"DrawingSheet", u"Internal", u"ProjectBrowser",
                    u"SystemBrowser", u"Undefined"):
            continue
        name = element_name(view)
        rows.append({
            u"kind": u"view",
            u"id": eid_value(view.Id),
            u"number": kind,
            u"name": name,
            u"label": name,
        })
    rows.sort(key=lambda r: arc_core.natural_key(r[u"name"]))
    return rows


# Views that hold no model elements, or will not take a revision cloud, or
# both. A sheet is a container and is expanded into the views on it.
NO_COMPARE_KINDS = (u"DrawingSheet", u"Schedule", u"ColumnSchedule",
                    u"PanelSchedule", u"Legend", u"ThreeD", u"Walkthrough",
                    u"Rendering", u"Internal", u"ProjectBrowser",
                    u"SystemBrowser", u"Undefined", u"Report", u"CostReport",
                    u"LoadsReport", u"PresureLossReport")


def view_kind(view):
    try:
        return arc_core.unicode_str(view.ViewType)
    except Exception:
        return u""


def expand_sheets(doc, rows):
    """Replace every sheet row with the views placed on it, in place order.

    A sheet is a container - the elements live in the views on it and a cloud
    drawn on the sheet sits in paper space where it cannot follow the
    viewport. Done at Compare time so nobody has to remember the button.
    """
    out = []
    seen = set()
    for row in rows:
        if row.get(u"kind") != u"sheet":
            if row[u"id"] not in seen:
                seen.add(row[u"id"])
                out.append(row)
            continue
        for view in views_on_sheet(doc, row[u"id"]):
            if view[u"id"] in seen:
                continue
            seen.add(view[u"id"])
            # a category list set on the sheet carries down to its views
            if row.get(u"categories"):
                view = dict(view)
                view[u"categories"] = row[u"categories"]
            out.append(view)
    return out


def sheets_of_views(doc, view_ids):
    """The sheets carrying these views, as [(sheet_id, number)].

    A cloud is drawn in a view, but the thing anybody wants to look at
    afterwards is the sheet it prints on. Read from the viewports rather than
    from the view, because `View.GetSheetNumber` does not exist on every
    release and a viewport always knows both ends.
    """
    wanted = set(view_ids)
    out = []
    seen = set()
    try:
        collector = FilteredElementCollector(doc).OfClass(Viewport)
    except Exception:
        return out
    for viewport in collector:
        try:
            if eid_value(viewport.ViewId) not in wanted:
                continue
            sheet_id = eid_value(viewport.SheetId)
        except Exception:
            continue
        if sheet_id in seen or sheet_id <= 0:
            continue
        sheet = sheet_by_id(doc, sheet_id)
        if sheet is None:
            continue
        seen.add(sheet_id)
        out.append((sheet_id, arc_core.unicode_str(sheet.SheetNumber)))
    out.sort(key=lambda row: arc_core.natural_key(row[1]))
    return out


def view_scale(view):
    """The view's scale denominator, 1 where it has none."""
    try:
        value = int(view.Scale)
        return value if value > 0 else 1
    except Exception:
        return 1


def element_name(element):
    """Element.Name raises AttributeError on some elements under IronPython."""
    try:
        return arc_core.unicode_str(element.Name)
    except Exception:
        return u""


# ==========================================================================
# sheets
# ==========================================================================

def sheets(doc):
    """[{id, number, name}] for every real (non placeholder) sheet, in
    natural drawing-number order."""
    rows = []
    for sheet in FilteredElementCollector(doc).OfClass(ViewSheet):
        try:
            if sheet.IsPlaceholder:
                continue
        except Exception:
            pass
        rows.append({
            u"kind": u"sheet",
            u"id": eid_value(sheet.Id),
            u"number": arc_core.unicode_str(sheet.SheetNumber),
            u"name": element_name(sheet),
            u"label": u"{0} - {1}".format(arc_core.unicode_str(sheet.SheetNumber),
                                          element_name(sheet)),
        })
    rows.sort(key=lambda r: arc_core.natural_key(r[u"number"]))
    return rows


def sheet_by_id(doc, id_value):
    element = doc.GetElement(make_id(id_value))
    if element is None or not isinstance(element, ViewSheet):
        return None
    return element




# ==========================================================================
# revisions
# ==========================================================================

def _visibility_name(revision):
    """The revision's Show setting by name, for prefilling the editor."""
    try:
        return arc_core.unicode_str(revision.Visibility)
    except Exception:
        return u""


def _sequence_id(revision):
    try:
        return eid_value(revision.RevisionNumberingSequenceId)
    except Exception:
        return 0


def revisions(doc):
    """[{id, seq, date, description, issued_by, issued_to, issued}] sorted by
    sequence number."""
    rows = []
    try:
        ids = Revision.GetAllRevisionIds(doc)
    except Exception:
        ids = [r.Id for r in FilteredElementCollector(doc).OfClass(Revision)]
    for rid in ids:
        rev = doc.GetElement(rid)
        if rev is None:
            continue
        rows.append({
            u"id": eid_value(rev.Id),
            u"seq": _safe_int(getattr(rev, u"SequenceNumber", 0)),
            u"date": arc_core.unicode_str(getattr(rev, u"RevisionDate", u"")),
            u"description": arc_core.unicode_str(getattr(rev, u"Description", u"")),
            u"issued_by": arc_core.unicode_str(getattr(rev, u"IssuedBy", u"")),
            u"visibility": _visibility_name(rev),
            u"sequence_id": _sequence_id(rev),
            u"issued_to": arc_core.unicode_str(getattr(rev, u"IssuedTo", u"")),
            u"issued": bool(getattr(rev, u"Issued", False)),
        })
    rows.sort(key=lambda r: r[u"seq"])
    return rows


def _safe_int(value):
    try:
        return int(value)
    except Exception:
        return 0


# ==========================================================================
# viewports on a sheet
# ==========================================================================


def _maps_2023(view, viewport):
    entries = []
    try:
        to_sheet = viewport.GetProjectionToSheetTransform()
        for twb in view.GetModelToProjectionTransforms():
            to_projection = twb.GetModelToProjectionTransform()
            composite = to_sheet.Multiply(to_projection)
            bbox = _loop_bbox(twb.GetBoundary(), composite)
            if bbox is None:
                continue
            entries.append({u"view": view, u"viewport": viewport,
                            u"transform": composite, u"bbox": bbox})
    except Exception:
        return []
    return entries


def _maps_2021(view, viewport):
    entries = []
    try:
        for twb in viewport.GetModelToProjectionTransforms():
            transform = twb.GetModelToProjectionTransform()
            bbox = _loop_bbox(twb.GetBoundary(), transform)
            if bbox is None:
                continue
            entries.append({u"view": view, u"viewport": viewport,
                            u"transform": transform, u"bbox": bbox})
    except Exception:
        return []
    return entries


def _loop_bbox(loop, transform=None):
    """Bounding box of a curve loop, pushed through `transform` first when
    one is given (the 2023 boundary is in model space)."""
    minx = miny = maxx = maxy = None
    for curve in loop:
        try:
            points = curve.Tessellate()
        except Exception:
            points = [curve.GetEndPoint(0), curve.GetEndPoint(1)]
        for p in points:
            if transform is not None:
                try:
                    p = transform.OfPoint(p)
                except Exception:
                    return None
            if minx is None or p.X < minx:
                minx = p.X
            if maxx is None or p.X > maxx:
                maxx = p.X
            if miny is None or p.Y < miny:
                miny = p.Y
            if maxy is None or p.Y > maxy:
                maxy = p.Y
    if minx is None:
        return None
    return (minx, miny, maxx, maxy)



# ==========================================================================
# Revit canvas theme (2024+)
# ==========================================================================

def revit_canvas_theme():
    """'dark' or 'light' from Revit's own canvas setting (2024+), then the
    UI theme, or None when the release has neither.  Compared by name:
    CurrentCanvasTheme is a CanvasTheme and CurrentTheme a UITheme, and
    comparing either against the other enum is always False."""
    try:
        from Autodesk.Revit.UI import UIThemeManager
    except Exception:
        return None
    for member in (u"CurrentCanvasTheme", u"CurrentTheme"):
        try:
            current = getattr(UIThemeManager, member)
        except Exception:
            continue
        name = arc_core.unicode_str(current).lower()
        if u"dark" in name:
            return u"dark"
        if u"light" in name:
            return u"light"
    return None


def resolve_theme(setting):
    """Settings 'auto' follows Revit's canvas; otherwise the setting wins."""
    if setting in (u"dark", u"light"):
        return setting
    return revit_canvas_theme() or u"dark"
