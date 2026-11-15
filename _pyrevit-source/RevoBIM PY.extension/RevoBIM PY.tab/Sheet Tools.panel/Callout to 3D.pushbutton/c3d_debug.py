# -*- coding: utf-8 -*-
"""Callout to 3D - the debug report.

Everything the tool can read about a callout and everything it works out from
it, as plain text that can be selected and pasted somewhere useful.  Nothing in
here changes the model or the settings; it only reads and formats.

The point of it is that "the sections are in the wrong place" and "the 3D will
not go on a sheet" are both unanswerable from the outside.  The numbers are
answerable.
"""

import c3d_clr  # noqa: F401  assemblies first, always

import os
import traceback

import c3d_core as core
import c3d_geom as geom
import c3d_model as model
import c3d_ops as ops
import c3d_ui as ui

from Autodesk.Revit.DB import (                          # noqa: E402
    FilteredElementCollector, Viewport,
)

FT = 304.8


def _mm(value):
    try:
        return core.ft_to_mm(float(value))
    except Exception:
        return 0.0


def _point(prefix, point, feet=True):
    try:
        if feet:
            return u"{0}{1:.1f}, {2:.1f}, {3:.1f} mm".format(
                prefix, _mm(point.X), _mm(point.Y), _mm(point.Z))
        return u"{0}{1:.3f}, {2:.3f}, {3:.3f}".format(prefix, point.X, point.Y, point.Z)
    except Exception:
        return u"{0}unreadable".format(prefix)


def _safe(function, default=u"unreadable"):
    try:
        value = function()
        return default if value is None else value
    except Exception:
        return default


# ---------------------------------------------------------------------------
# the document itself
# ---------------------------------------------------------------------------


def document_block(doc):
    lines = ["=== THE DOCUMENT ==="]
    lines.append(u"title            {0}".format(_safe(lambda: doc.Title)))
    lines.append(u"workshared       {0}".format(_safe(lambda: doc.IsWorkshared)))
    lines.append(u"revit build      {0}".format(
        _safe(lambda: doc.Application.VersionBuild)))
    lines.append(u"revit version    {0}".format(
        _safe(lambda: doc.Application.VersionNumber)))

    # a survey point a long way from the model origin is the usual reason two
    # sets of coordinates disagree, so it is worth having in writing
    for label, kind in (("project base point", "ProjectBasePoint"),
                        ("survey point", "SurveyPoint")):
        try:
            from Autodesk.Revit.DB import BuiltInCategory
            category = getattr(BuiltInCategory, "OST_ProjectBasePoint"
                               if kind == "ProjectBasePoint" else "OST_SharedBasePoint")
            found = list(FilteredElementCollector(doc).OfCategory(category)
                         .WhereElementIsNotElementType())
            if not found:
                lines.append(u"{0:16} none found".format(label))
                continue
            point = found[0]
            position = _safe(lambda: point.Position)
            lines.append(u"{0:16} {1}".format(label, _point("", position)))
        except Exception as err:
            lines.append(u"{0:16} could not be read - {1}".format(label, err))

    try:
        location = doc.ActiveProjectLocation
        transform = location.GetTotalTransform()
        lines.append(u"project location {0}".format(_safe(lambda: location.Name)))
        lines.append(u"  its origin     {0}".format(_point("", transform.Origin)))
        lines.append(u"  its basis X    {0}".format(_point("", transform.BasisX, False)))
    except Exception as err:
        lines.append(u"project location could not be read - {0}".format(err))

    return lines


# ---------------------------------------------------------------------------
# one callout
# ---------------------------------------------------------------------------


def callout_block(doc, row, settings):
    view = row.get("view")
    lines = ["", u"=== CALLOUT: {0} ===".format(row.get("name", ""))]

    lines.append(u"id               {0}".format(core.eid_value(row.get("id"))))
    lines.append(u"class            {0}".format(_safe(lambda: view.GetType().Name)))
    lines.append(u"view type        {0}".format(_safe(lambda: view.ViewType)))
    lines.append(u"view family type {0}".format(model.view_type_name(doc, view)))
    lines.append(u"found by route   {0}".format(row.get("route", "?")))
    lines.append(u"scale            1:{0}".format(_safe(lambda: view.Scale)))
    lines.append(u"crop active      {0}".format(_safe(lambda: view.CropBoxActive)))
    lines.append(u"crop visible     {0}".format(_safe(lambda: view.CropBoxVisible)))
    lines.append(u"template on it   {0}".format(
        _safe(lambda: model._name_of(doc.GetElement(view.ViewTemplateId)), "none")))

    # ---- the level ------------------------------------------------------
    lines.append("")
    lines.append("--- level ---")
    level = _safe(lambda: view.GenLevel, None)
    if level is None:
        lines.append(u"GenLevel         NONE - the level was guessed from the crop")
    else:
        lines.append(u"GenLevel         {0}".format(model._name_of(level)))
        lines.append(u"  Elevation      {0:.1f} mm".format(_mm(_safe(lambda: level.Elevation, 0.0))))
        lines.append(u"  ProjectElev.   {0:.1f} mm".format(
            _mm(_safe(lambda: level.ProjectElevation, 0.0))))
    # which property is the internal one, and the sum that decides it
    offset = geom.cut_plane_offset_mm(view)
    frame_now = geom.crop_frame(view)
    if level is not None and offset is not None and frame_now:
        wanted = frame_now.get("z", 0.0) - offset
        lines.append(u"crop plane Z     {0:.1f} mm".format(frame_now.get("z", 0.0)))
        lines.append(u"cut plane offset {0:.1f} mm".format(offset))
        lines.append(u"so the level is  {0:.1f} mm internally".format(wanted))
        for name in ("Elevation", "ProjectElevation"):
            try:
                value = _mm(getattr(level, name))
                lines.append(u"  {0:14} {1:.1f} mm   {2:.1f} mm away{3}".format(
                    name, value, abs(value - wanted),
                    "   <-- this one" if abs(value - wanted) < 1.0 else ""))
            except Exception:
                lines.append(u"  {0:14} unreadable".format(name))
    lines.append(u"row level name   {0}".format(row.get("level_name") or "NONE"))
    lines.append(u"row level mm     {0:.1f}".format(row.get("level_mm", 0.0)))
    lines.append(u"next level mm    {0}".format(
        u"{0:.1f}".format(row["next_level_mm"]) if row.get("next_level_mm") is not None
        else "none above"))

    # ---- the crop region, both ways -------------------------------------
    lines.append("")
    lines.append("--- where the callout is, read both ways ---")

    curves = geom._frame_from_crop_shape(view)
    if curves is None:
        lines.append(u"crop region      GetCropShape gave nothing back")
    else:
        lines.append(u"crop region      centre {0:.1f}, {1:.1f} mm   size {2:.1f} x {3:.1f} mm"
                     .format(curves["centre"][0], curves["centre"][1],
                             curves["half_x"] * 2.0, curves["half_y"] * 2.0))
        lines.append(u"  its axis X     {0:.4f}, {1:.4f}   rotated {2}".format(
            curves["axis_x"][0], curves["axis_x"][1], curves["rotated"]))
        lines.append(u"  its elevation  {0:.1f} mm".format(curves["z"]))

    box_frame = geom._frame_from_crop_box(view)
    if box_frame is None:
        lines.append(u"crop box         CropBox gave nothing back")
    else:
        lines.append(u"crop box         centre {0:.1f}, {1:.1f} mm   size {2:.1f} x {3:.1f} mm"
                     .format(box_frame["centre"][0], box_frame["centre"][1],
                             box_frame["half_x"] * 2.0, box_frame["half_y"] * 2.0))

    # the raw numbers, so the arithmetic can be checked by hand
    try:
        raw = view.CropBox
        lines.append(u"  raw Min        {0}".format(_point("", raw.Min)))
        lines.append(u"  raw Max        {0}".format(_point("", raw.Max)))
        transform = raw.Transform
        lines.append(u"  raw Transform  origin {0}".format(_point("", transform.Origin)))
        lines.append(u"                 basisX {0}".format(_point("", transform.BasisX, False)))
        lines.append(u"                 basisY {0}".format(_point("", transform.BasisY, False)))
        lines.append(u"                 basisZ {0}".format(_point("", transform.BasisZ, False)))
        lines.append(u"  Transform x Min {0}".format(_point("", transform.OfPoint(raw.Min))))
        lines.append(u"  Transform x Max {0}".format(_point("", transform.OfPoint(raw.Max))))
    except Exception as err:
        lines.append(u"  raw CropBox    could not be read - {0}".format(err))

    if curves is not None and box_frame is not None:
        gap = max(abs(curves["centre"][0] - box_frame["centre"][0]),
                  abs(curves["centre"][1] - box_frame["centre"][1]))
        lines.append(u"  THE TWO DISAGREE BY {0:.1f} mm".format(gap))

    frame = row.get("frame")
    if frame:
        lines.append(u"USED             the {0}: centre {1:.1f}, {2:.1f} mm, "
                     u"size {3:.1f} x {4:.1f} mm".format(
                         frame.get("source", "?"), frame["centre"][0], frame["centre"][1],
                         frame["half_x"] * 2.0, frame["half_y"] * 2.0))
    else:
        lines.append(u"USED             NO FRAME AT ALL - nothing can be built")

    # ---- the view range -------------------------------------------------
    lines.append("")
    lines.append("--- view range ---")
    try:
        from Autodesk.Revit.DB import PlanViewPlane
        view_range = view.GetViewRange()
        for name in ("TopClipPlane", "CutPlane", "BottomClipPlane", "ViewDepthPlane"):
            enum = getattr(PlanViewPlane, name, None)
            if enum is None:
                lines.append(u"{0:16} not in this release".format(name))
                continue
            level_id = view_range.GetLevelId(enum)
            offset = view_range.GetOffset(enum)
            if level_id is None or core.eid_value(level_id) <= 0:
                lines.append(u"{0:16} unlimited (offset {1:.1f} mm)".format(name, _mm(offset)))
                continue
            plane_level = doc.GetElement(level_id)
            base = geom.level_model_z(plane_level)
            lines.append(u"{0:16} {1} + {2:.1f} mm  =  {3:.1f} mm".format(
                name, model._name_of(plane_level), _mm(offset),
                _mm(base) + _mm(offset) if base is not None else 0.0))
    except Exception as err:
        lines.append(u"could not be read - {0}".format(err))
    lines.append(u"row range_mm     {0}".format(row.get("range_mm")))

    # ---- what will be built ---------------------------------------------
    lines.append("")
    lines.append("--- what would be built ---")
    base, top = ops.band_for(row, settings)
    lines.append(u"band             {0:.1f} mm to {1:.1f} mm   (height {2:.1f} mm)"
                 .format(base, top, top - base))
    lines.append(u"band is sane     {0}".format(ops.sane_band((base, top))))
    if frame:
        crop_z = frame.get("z")
        inside = crop_z is not None and base - 1.0 <= crop_z <= top + 1.0
        lines.append(u"crop plane in it {0}{1}".format(
            inside, "" if inside else
            "   <-- THE BAND AND THE MODEL ARE NOT ON THE SAME DATUM"))

    if frame:
        extents = geom.extents_mm(frame, core.get_float(settings, "3d_xy_margin_mm", 0.0))
        lines.append(u"3D box extents   {0:.1f}, {1:.1f} to {2:.1f}, {3:.1f} mm "
                     u"(offsets from the centre)".format(*extents))
        try:
            box = geom.section_box(frame, extents, base, top)
            lines.append(u"3D box Min       {0}".format(_point("", box.Min)))
            lines.append(u"3D box Max       {0}".format(_point("", box.Max)))
            lines.append(u"3D box transform origin {0}".format(
                _point("", box.Transform.Origin)))
            lines.append(u"3D box quarter turn {0}".format(
                geom._quarter_turn(frame.get("axis_x", (1.0, 0.0)))))
            lines.append(u"3D box is axis aligned {0}".format(
                geom._quarter_turn(frame.get("axis_x", (1.0, 0.0))) is not None))
            middle = geom.box_centre(box)
            lines.append(u"3D box centre    {0}".format(_point("", middle)))
            forward = geom.orientation_vector(
                settings.get("3d_orientation", "se_iso"),
                core.get_float(settings, "3d_pitch_degrees", geom.ISOMETRIC_PITCH))
            eye = geom.eye_point_mm(
                (_mm(middle.X), _mm(middle.Y), _mm(middle.Z)),
                forward or (1.0, -1.0, 1.0))
            lines.append(u"camera stands at {0:.1f}, {1:.1f}, {2:.1f} mm".format(*eye))
        except Exception as err:
            lines.append(u"3D box           could not be built - {0}".format(err))
            lines.append(traceback.format_exc())

        specs = geom.section_frames(
            geom.extents_mm(frame, 0.0),
            row.get("x_count", 0), row.get("y_count", 0), base, top,
            core.get_float(settings, "sec_side_margin_mm", 250.0),
            bool(row.get("flip_x")), bool(row.get("flip_y")), row.get("flips") or {},
            row.get("cuts") or {})
        lines.append(u"sections         {0}".format(len(specs)))
        for spec in specs:
            try:
                point = geom._to_model(frame, spec["origin"])
                lines.append(
                    u"  {0:4} origin {1:.1f}, {2:.1f}, {3:.1f} mm   looks {4}   "
                    u"{5:.0f} wide x {6:.0f} tall".format(
                        spec["label"], _mm(point.X), _mm(point.Y), _mm(point.Z),
                        spec["look"], spec["width"], spec["height"]))
            except Exception as err:
                lines.append(u"  {0} could not be placed - {1}".format(spec["label"], err))

    return lines


# ---------------------------------------------------------------------------
# why a view will or will not go on a sheet
# ---------------------------------------------------------------------------


def sheet_block(doc, settings):
    lines = ["", "=== SHEETS AND VIEWPORTS ==="]

    blocks = model.title_blocks(doc)
    lines.append(u"title block types {0}".format(len(blocks)))
    for block in blocks[:8]:
        lines.append(u"  {0}".format(block["name"]))
    mapping = core.get_map(settings, "sheet_titleblocks")
    lines.append(u"mapped in settings {0}".format(mapping or "nothing"))
    size = settings.get("sheet_size_default", "A1")
    chosen = model.title_block_for_size(doc, size, mapping)
    lines.append(u"{0} would use     {1}".format(
        size, chosen["name"] if chosen else "NOTHING - a sheet cannot be made"))

    types = model.viewport_types(doc)
    lines.append(u"viewport types    {0}".format(len(types)))
    for item in types[:8]:
        lines.append(u"  {0}".format(item["name"]))
    for key, label in (("vp_type_callout", "callout"), ("vp_type_3d", "3D"),
                       ("vp_type_section", "section")):
        lines.append(u"  set for the {0:8} {1}".format(
            label, settings.get(key) or "(Revit's default)"))

    # the question that matters: will Revit take a 3D view on a sheet at all,
    # in this document, right now
    lines.append("")
    lines.append("--- can a 3D view go on a sheet here ---")
    try:
        from Autodesk.Revit.DB import View3D, ViewSheet
        sheets = list(FilteredElementCollector(doc).OfClass(ViewSheet))
        threes = [view for view in FilteredElementCollector(doc).OfClass(View3D)
                  if not view.IsTemplate]
        lines.append(u"sheets in project {0}".format(len(sheets)))
        lines.append(u"3D views          {0}".format(len(threes)))
        if sheets and threes:
            sheet = sheets[0]
            lines.append(u"asking about      {0} onto {1}".format(
                model._name_of(threes[0]), sheet.SheetNumber))
            for view in threes[:5]:
                try:
                    answer = Viewport.CanAddViewToSheet(doc, sheet.Id, view.Id)
                except Exception as err:
                    answer = u"threw - {0}".format(err)
                on_sheet = ""
                try:
                    placed = [vp for vp in FilteredElementCollector(doc)
                              .OfClass(Viewport)
                              if core.eid_value(vp.ViewId) == core.eid_value(view.Id)]
                    if placed:
                        on_sheet = "  (already on a sheet)"
                except Exception:
                    pass
                lines.append(u"  {0:40} {1}{2}".format(
                    model._name_of(view)[:40], answer, on_sheet))
    except Exception as err:
        lines.append(u"could not be asked - {0}".format(err))

    return lines


# ---------------------------------------------------------------------------
# the log
# ---------------------------------------------------------------------------


def log_block(tail=80):
    lines = ["", u"=== THE LAST {0} LOG LINES ===".format(tail)]
    try:
        path = core.log_path()
        if not os.path.isfile(path):
            lines.append(u"no log at {0} yet".format(path))
            return lines
        handle = open(path, "rb")
        try:
            content = handle.read().decode("utf-8", "replace")
        finally:
            handle.close()
        for line in content.splitlines()[-tail:]:
            lines.append(line)
    except Exception as err:
        lines.append(u"the log could not be read - {0}".format(err))
    return lines


# ---------------------------------------------------------------------------


def report(doc, rows, settings, routes=None):
    """The whole thing, as one block of text."""
    lines = [u"RevoBIM Callout to 3D - debug report",
             u"version {0}".format(core.__version__),
             u"all distances in model millimetres unless it says otherwise",
             ""]
    try:
        lines += document_block(doc)
    except Exception:
        lines.append("the document block threw:")
        lines.append(traceback.format_exc())

    if routes:
        lines.append("")
        lines.append(u"=== HOW THE CALLOUTS WERE FOUND ===")
        if routes.get("elevation_source"):
            lines.append(u"level elevations read from {0}  {1}".format(
                routes["elevation_source"], routes.get("elevation_votes") or ""))
        for key in ("reference", "marker", "type", "cropped", "lost"):
            if key in routes:
                lines.append(u"{0:12} {1}".format(key, routes[key]))
        for key, value in sorted((routes.get("ms") or {}).items()):
            lines.append(u"{0:12} {1:.0f} ms{2}".format(
                key, value, "  (skipped)" if value < 0 else ""))

    for row in rows[:5]:
        try:
            lines += callout_block(doc, row, settings)
        except Exception:
            lines.append(u"the block for {0} threw:".format(row.get("name", "")))
            lines.append(traceback.format_exc())
    if len(rows) > 5:
        lines.append("")
        lines.append(u"({0} more callout(s) not listed - tick fewer to see them)"
                     .format(len(rows) - 5))

    try:
        lines += sheet_block(doc, settings)
    except Exception:
        lines.append("the sheet block threw:")
        lines.append(traceback.format_exc())

    lines.append("")
    lines.append("=== THE EASTER EGG ===")
    lines.append(u"last route taken {0}".format(
        (ui.LAST_EGG_ROUTE or ["nothing has opened it this session"])[-1]))
    try:
        lines += ui.egg_report()
    except Exception:
        lines.append("the egg report threw:")
        lines.append(traceback.format_exc())

    lines += log_block()
    return u"\n".join(lines)
