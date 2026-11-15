# -*- coding: utf-8 -*-
"""Schematic Builder - every write to the model.

The window is modeless, so Create hands a job to the ExternalEvent handler
and the build runs here, inside Revit's API context. One TransactionGroup
wraps the run so Revit's undo sees a single step; the view is created in its
own transaction so a failed layout never costs the view's name.
"""
import sb_clr  # noqa: F401

import traceback

import sb_logic
import sb_lv
import sb_model
from sb_logic import (as_text, to_int, to_float, decode_rows, parse_transfer, row_families,
                      pair_text, effective_transfer, ROW_WIDTH)
from sb_core import (eid_value, make_id, mm_to_ft, ft_to_mm, el_name, find_param, param_text,
                     set_param, quiet_transaction, log, write_error)

from Autodesk.Revit.DB import (  # noqa: E402
    Transaction, TransactionGroup, ViewDrafting, XYZ, Line, TextNote, HorizontalTextAlignment,
    ElementTransformUtils, FamilyPlacementType, Element, VerticalTextAlignment,
)
from Autodesk.Revit.UI import IExternalEventHandler  # noqa: E402


class SchematicHandler(IExternalEventHandler):
    """Runs one job (a dict built by the window) inside API context."""

    def __init__(self):
        self.job = None
        self.callback = None

    def Execute(self, uiapp):
        job = self.job
        callback = self.callback
        self.job = None
        if job is None:
            return
        result = None
        try:
            result = run_job(uiapp, job)
        except Exception:
            body = write_error("run_job")
            result = {"ok": False, "summary": u"The build failed - nothing was changed.",
                      "lines": [body.strip().splitlines()[-1]], "detail": body}
        if callback is not None:
            try:
                callback(result)
            except Exception:
                write_error("callback")

    def GetName(self):
        return "RevoBIM Schematic Builder"


# ---------------------------------------------------------------------------
# JOB
# ---------------------------------------------------------------------------

def run_job(uiapp, job):
    uidoc = uiapp.ActiveUIDocument
    if uidoc is None:
        return fail(u"No document is open.")
    doc = uidoc.Document
    if as_text(doc.Title) != as_text(job.get("doc_title")):
        return fail(u"Make '{0}' the active document, then press Create again.".format(
            as_text(job.get("doc_title"))))
    tab = job["tab"]
    if tab in ("ventilation", "lv"):
        return build_schematic(uidoc, doc, job, tab)
    if tab == "married":
        return run_template(uidoc, doc, job)
    return fail(u"The {0} schematic is not built yet.".format(tab))


def fail(message):
    return {"ok": False, "summary": message, "lines": [], "detail": u""}


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def paper_to_ft(paper_mm, scale):
    return mm_to_ft(float(paper_mm) * float(scale))


def ft_to_paper(ft, scale):
    return ft_to_mm(ft) / float(scale)


def place_detail(doc, view, symbol, point, length_ft):
    """Place a detail item, coping with point and line based families."""
    curve_based = False
    try:
        placement = symbol.Family.FamilyPlacementType
        for name in ("CurveBasedDetail", "CurveBased"):
            if placement == getattr(FamilyPlacementType, name):
                curve_based = True
    except Exception:
        pass
    line = Line.CreateBound(point, XYZ(point.X + length_ft, point.Y, 0.0))
    if curve_based:
        return doc.Create.NewFamilyInstance(line, symbol, view)
    try:
        return doc.Create.NewFamilyInstance(point, symbol, view)
    except Exception:
        return doc.Create.NewFamilyInstance(line, symbol, view)


def stretch_across(doc, instance, x0_mm, x1_mm, scale):
    """Set a line based detail item's length, so the Main LV board runs the
    full width of the ways leaving it. Returns False if it is point based."""
    try:
        location = instance.Location
        curve = location.Curve
    except Exception:
        return False
    try:
        y = curve.GetEndPoint(0).Y
        location.Curve = Line.CreateBound(
            XYZ(paper_to_ft(x0_mm, scale), y, 0.0),
            XYZ(paper_to_ft(x1_mm, scale), y, 0.0))
        return True
    except Exception:
        return False


def rename_element(element, name):
    """Try both rename routes; which one works varies with the IronPython engine."""
    try:
        element.Name = name
    except Exception:
        pass
    if el_name(element) == name:
        return True
    try:
        Element.Name.SetValue(element, name)
    except Exception:
        pass
    return el_name(element) == name


def detail_line(doc, view, p0, p1, style):
    curve = doc.Create.NewDetailCurve(view, Line.CreateBound(p0, p1))
    if style is not None:
        try:
            curve.LineStyle = style
        except Exception:
            pass
    return curve


def text_note(doc, view, point, text, type_id):
    """The point is the TOP LEFT corner of the text, so a caller can place a
    label by its corner rather than guessing at its baseline."""
    note = TextNote.Create(doc, view.Id, point, as_text(text), type_id)
    try:
        note.HorizontalAlignment = HorizontalTextAlignment.Left
    except Exception:
        pass
    try:
        note.VerticalAlignment = VerticalTextAlignment.Top
    except Exception:
        pass
    return note


def resolve_source(rec, source, job_row):
    """A transfer source: a {token} or a parameter on the model element."""
    token = source.lower()
    tokens = {
        u"{level}": rec.get("level_name", u""),
        u"{level_abbr}": rec.get("level_abbr", u""),
        u"{room}": rec.get("room_label", u""),
        u"{mark}": rec.get("mark", u""),
        u"{type_mark}": rec.get("type_mark", u""),
        u"{type mark}": rec.get("type_mark", u""),
        u"{equipment}": job_row[0],
        u"{family}": rec.get("family", u""),
        u"{type}": rec.get("type", u""),
    }
    if token in tokens:
        return tokens[token], True
    value = param_text(find_param(rec["element"], source, True))
    return (as_text(value), value is not None)


def set_view_params(view, browser_rows, issues):
    written = 0
    for name, value in browser_rows:
        if not name or not value:
            continue
        param = find_param(view, name, False)
        if param is None:
            issues.append(u"View parameter '{0}' does not exist on drafting views.".format(name))
            continue
        outcome = set_param(param, value)
        if outcome == "ok":
            written += 1
        else:
            issues.append(u"View parameter '{0}' could not be set ({1}).".format(name, outcome))
    return written


# ---------------------------------------------------------------------------
# VENTILATION
# ---------------------------------------------------------------------------

def build_schematic(uidoc, doc, job, tab):
    """The ventilation and LV schematics share everything up to the layout:
    levels, rooms, the equipment records, placing and measuring the detail
    items. LV then filters to panels, reads the circuits, routes the feeders
    and lets the drawing grow wider; ventilation wraps into rows instead."""
    settings = job["settings"]
    model = job["model"]
    scale = max(1, to_int(settings.get("scale"), 1))
    issues = []
    lines = []
    is_lv = tab == "lv"

    equipment_rows = decode_rows(settings.get("equipment_" + tab, u""), ROW_WIDTH)
    equipment_rows = [r for r in equipment_rows if row_families(r) and r[3]]
    browser_rows = [r for r in decode_rows(settings.get("browser_" + tab, u""), 2) if r[0]]

    # ---- levels ----------------------------------------------------------
    all_levels = sb_model.read_levels(doc)
    level_table = sb_logic.level_rows(settings, [l["name"] for l in all_levels])
    include = {}
    abbr_of = {}
    for name, abbr, included in level_table:
        include[name] = included
        abbr_of[name] = abbr
    levels = [l for l in all_levels if include.get(l["name"], True)]
    if not levels:
        return fail(u"No levels are ticked in Settings, so there is nothing to draw.")
    for level in all_levels:
        level["abbr"] = abbr_of.get(level["name"], u"")
    for level in levels:
        level["abbr"] = abbr_of.get(level["name"], u"")
        level["label"] = sb_logic.format_level_label(settings.get("level_label"), level["name"], level["abbr"])
    level_by_id = {}
    for level in levels:
        level_by_id[level["id"]] = level
    all_level_by_id = {}
    for level in all_levels:
        all_level_by_id[level["id"]] = level
    ticked_ids = set(level_by_id.keys())
    known_ids = set(all_level_by_id.keys())

    # ---- styles and types ------------------------------------------------
    line_styles = sb_model.read_line_styles(doc)
    text_types = sb_model.read_text_types(doc)
    level_style = line_styles.get(settings.get("level_line_style"))
    room_style = line_styles.get(settings.get("room_line_style"))
    circuit_style = line_styles.get(settings.get("lv_circuit_line_style")) or level_style
    if is_lv and settings.get("lv_circuit_line_style") and circuit_style is level_style:
        issues.append(u"Circuit line style '{0}' not found - the level line style is used.".format(
            settings.get("lv_circuit_line_style")))
    if settings.get("level_line_style") and level_style is None:
        issues.append(u"Level line style '{0}' not found - default used.".format(settings.get("level_line_style")))
    if settings.get("room_line_style") and room_style is None:
        issues.append(u"Room line style '{0}' not found - default used.".format(settings.get("room_line_style")))
    level_text = text_types.get(settings.get("level_text_type"))
    room_text = text_types.get(settings.get("room_text_type"))
    if level_text is None or room_text is None:
        fallback = None
        for name in sorted(text_types.keys()):
            fallback = text_types[name]
            break
        if fallback is None:
            return fail(u"No text note types exist in this project.")
        if level_text is None:
            issues.append(u"Level text type '{0}' not found - '{1}' used.".format(
                settings.get("level_text_type"), el_name(fallback)))
            level_text = fallback
        if room_text is None:
            issues.append(u"Room text type '{0}' not found - '{1}' used.".format(
                settings.get("room_text_type"), el_name(fallback)))
            room_text = fallback
    level_size = sb_model.text_size_mm(level_text)
    level_wf = sb_model.text_width_factor(level_text)
    room_size = sb_model.text_size_mm(room_text)
    room_wf = sb_model.text_width_factor(room_text)

    vft_id = sb_model.drafting_view_type_id(doc)
    if vft_id is None:
        return fail(u"No drafting view type exists in this project.")

    # ---- equipment records ------------------------------------------------
    links = sb_model.read_links(doc)
    phase = sb_model.last_phase(doc)
    room_param = settings.get("room_name_param", u"Name")
    room_source = u"element" if settings.get("room_source") == u"element" else u"room"
    element_room_param = as_text(settings.get("room_element_param", u"")).strip()
    if room_source == u"element" and not element_room_param:
        return fail(u"Rooms are set to come from a parameter on the element, but no parameter is "
                    u"named in Settings.")
    detail_symbols = {}
    for row in model.get("details", []):
        detail_symbols[(row["family"], row["type"])] = row["type_id"]
    records = []
    seen_elements = set()
    unreadable = []
    skipped_levels = {}
    panels = sb_model.panel_ids(doc) if is_lv and settings.get("lv_panels_only", u"1") != u"0" else None
    no_schedule = 0
    for row in equipment_rows:
        symbol_id = detail_symbols.get((row[3], row[4]))
        if symbol_id is None:
            issues.append(u"{0}: detail item '{1} : {2}' is no longer loaded - skipped.".format(row[0], row[3], row[4]))
            continue
        instances = []
        for family, type_name in row_families(row):
            found = sb_model.collect_instances(doc, family, type_name)
            if not found:
                issues.append(u"{0}: no placed instances of '{1}'.".format(row[0], pair_text(family, type_name)))
            for inst in found:
                key = eid_value(inst.Id)
                if key in seen_elements:
                    continue        # ticking a whole family and one of its types must not draw twice
                if panels is not None and key not in panels:
                    no_schedule += 1
                    continue        # LV: only equipment that has a panel schedule
                seen_elements.add(key)
                instances.append(inst)
        if not instances:
            continue
        for inst in instances:
            try:
                # identified against EVERY level, so an element on an unticked
                # level is recognised as such rather than snapped to a ticked one
                rec = sb_model.instance_record(doc, inst, all_levels, links, phase, room_param,
                                               room_source, element_room_param)
            except Exception:
                unreadable.append(u"Element {0}: {1}".format(
                    eid_value(inst.Id), traceback.format_exc().strip().splitlines()[-1]))
                continue
            for problem in rec.get("problems", []):
                unreadable.append(u"Element {0} ({1}): could not read {2}".format(
                    rec["id"], rec["family"] or u"?", problem))
            rec["equipment"] = row
            rec["symbol_id"] = symbol_id
            bucket = sb_logic.level_bucket(rec["level_id"], ticked_ids, known_ids)
            if bucket == "unticked":
                # a real level the user has switched off: leave the element out
                name = all_level_by_id[rec["level_id"]]["name"]
                skipped_levels[name] = skipped_levels.get(name, 0) + 1
                continue
            if bucket == "unknown":
                rec["level_id"] = levels[0]["id"]
                rec["no_level"] = True
            level = level_by_id[rec["level_id"]]
            rec["level_name"] = level["name"]
            rec["level_abbr"] = level["abbr"]
            records.append(rec)
    if no_schedule:
        issues.append(u"{0} element(s) of the paired families have no panel schedule and are left out "
                      u"(untick 'only equipment that has a panel schedule' in Settings > LV to draw them).".format(no_schedule))
    edges = []
    main_id = None
    circuit_note = u""
    if is_lv:
        edges, notes = sb_model.circuit_edges(doc, records)
        circuit_note = (u"Circuits: {0} in the project, {1} with a supplying panel, {2} of those "
                        u"supplied by a placed board, {3} drawn".format(
                            notes["circuits"], notes["with_base"], notes["base_placed"], notes["edges"]))
        if records and not edges:
            if not notes["circuits"]:
                issues.append(u"No electrical circuits exist in this project at all, so there is "
                              u"nothing to draw between the boards.")
            elif not notes["with_base"]:
                issues.append(u"{0} circuit(s) exist but none has a supplying panel set, so no "
                              u"feeder can be worked out.".format(notes["circuits"]))
            elif not notes["base_placed"]:
                issues.append(u"{0} circuit(s) have a supplying panel, but none of those panels is "
                              u"on this drawing - pair its family in Equipment, and check the "
                              u"'only equipment with a panel schedule' setting.".format(notes["with_base"]))
            else:
                issues.append(u"Circuits were found, but none runs between two boards that are both "
                              u"on the drawing - the loads are equipment that is not placed here.")
        wanted_main = as_text(settings.get("lv_main_panel", u"")).strip()
        if wanted_main:
            for rec in records:
                if sb_model.panel_label(rec["element"]) == wanted_main:
                    main_id = rec["id"]
                    break
            if main_id is None:
                issues.append(u"The Main LV board '{0}' is not on this drawing - it is treated like "
                              u"any other board.".format(wanted_main))
    for name in sorted(skipped_levels.keys()):
        issues.append(u"{0} element(s) are on '{1}', which is unticked in Settings - left out.".format(
            skipped_levels[name], name))
    for line in unreadable[:12]:
        issues.append(line)
    if len(unreadable) > 12:
        issues.append(u"...and {0} more elements with the same kind of problem.".format(len(unreadable) - 12))
    no_level = [r for r in records if r.get("no_level")]
    if no_level:
        issues.append(u"{0} element(s) have no usable level - placed on {1}.".format(
            len(no_level), levels[0]["name"]))
    no_room = len([r for r in records if r["room_key"] is None])
    if no_room and room_source == u"element":
        issues.append(u"{0} element(s) have nothing in '{1}', so they are drawn without a room box.".format(
            no_room, element_room_param))

    # ---- build -------------------------------------------------------------
    frame = sb_logic.sheet_frame(settings.get("sheet_size", u"A1"), to_float(settings.get("margin_mm"), 20.0))
    params = sb_logic.layout_params(settings)
    group = TransactionGroup(doc, "RevoBIM Schematic Builder")
    group.Start()
    view = None
    view_name = u""
    placed = {}
    try:
        # the view
        trans = Transaction(doc, "Create schematic view")
        quiet_transaction(trans)
        trans.Start()
        view = ViewDrafting.Create(doc, vft_id)
        view_name = sb_logic.next_view_name(settings.get("name_" + tab), sb_model.read_view_names(doc))
        rename_element(view, view_name)
        if el_name(view) != view_name:
            issues.append(u"Revit would not accept the view name '{0}' - left as '{1}'.".format(view_name, el_name(view)))
            view_name = el_name(view)
        view.Scale = scale
        set_view_params(view, browser_rows, issues)
        trans.Commit()
        log(u"Created '{0}' at 1:{1}".format(view_name, scale))

        trans = Transaction(doc, "Draw {0} schematic".format(tab))
        quiet_transaction(trans)
        trans.Start()

        # place every detail item at the origin first, so its size can be read
        for rec in records:
            symbol = doc.GetElement(rec["symbol_id"])
            try:
                if not symbol.IsActive:
                    symbol.Activate()
            except Exception:
                pass
            try:
                inst = place_detail(doc, view, symbol, XYZ(0.0, 0.0, 0.0), paper_to_ft(20.0, scale))
                placed[rec["id"]] = inst
            except Exception:
                issues.append(u"{0} {1}: detail item could not be placed ({2}).".format(
                    rec["equipment"][0], rec["mark"] or rec["id"],
                    traceback.format_exc().strip().splitlines()[-1]))
        doc.Regenerate()

        # measure
        layout_records = []
        for rec in records:
            inst = placed.get(rec["id"])
            if inst is None:
                continue
            box = None
            try:
                box = inst.get_BoundingBox(view)
            except Exception:
                box = None
            if box is None:
                w_mm, h_mm = 20.0, 10.0
                offset_x, offset_y = 0.0, 0.0
            else:
                w_mm = max(ft_to_paper(box.Max.X - box.Min.X, scale), 1.0)
                h_mm = max(ft_to_paper(box.Max.Y - box.Min.Y, scale), 1.0)
                offset_x = box.Min.X
                offset_y = box.Min.Y
            rec["w"] = w_mm
            rec["h"] = h_mm
            rec["box_min"] = (offset_x, offset_y)
            layout_records.append({
                "id": rec["id"], "level_key": rec["level_id"], "room_key": rec["room_key"],
                "room_label": rec["room_label"], "sort": rec["mark"] or rec["type_mark"],
                "w": w_mm, "h": h_mm,
            })

        # lay out
        level_keys = []
        for level in levels:
            label = level["label"]
            level_keys.append((level["id"], label,
                               sb_logic.text_width(label, level_size, level_wf),
                               sb_logic.text_height(level_size)))
        groups = sb_logic.build_groups(layout_records, room_size, room_wf)
        if is_lv:
            layout = sb_lv.plan_lv(level_keys, groups, edges, frame,
                                   sb_lv.lv_params(settings, params), main_id)
        else:
            layout = sb_logic.layout_schematic(level_keys, groups, frame, params)
        pads = layout.get("pads", {})

        # move the detail items into place
        rec_by_id = {}
        for rec in records:
            rec_by_id[rec["id"]] = rec
        moved = 0
        for item_id in layout["items"]:
            rec = rec_by_id.get(item_id)
            inst = placed.get(item_id)
            if rec is None or inst is None:
                continue
            x_mm, y_mm = layout["items"][item_id]
            x_mm += pads.get(item_id, 0.0)       # LV: centred in a slot wide enough for its feeders
            target = XYZ(paper_to_ft(x_mm, scale), paper_to_ft(y_mm, scale), 0.0)
            min_x, min_y = rec["box_min"]
            try:
                ElementTransformUtils.MoveElement(doc, inst.Id, XYZ(target.X - min_x, target.Y - min_y, 0.0))
                moved += 1
            except Exception:
                issues.append(u"Element {0}: detail item could not be moved.".format(item_id))

        # level lines and labels
        for x0, y, x1 in layout["lines"]:
            detail_line(doc, view, XYZ(paper_to_ft(x0, scale), paper_to_ft(y, scale), 0.0),
                        XYZ(paper_to_ft(x1, scale), paper_to_ft(y, scale), 0.0), level_style)
        for x, y_top, text in layout["level_labels"]:
            text_note(doc, view, XYZ(paper_to_ft(x, scale), paper_to_ft(y_top, scale), 0.0), text, level_text.Id)

        # room boxes and labels
        for x0, y0, x1, y1 in layout["boxes"]:
            corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
            for index in range(4):
                ax, ay = corners[index]
                bx, by = corners[(index + 1) % 4]
                detail_line(doc, view, XYZ(paper_to_ft(ax, scale), paper_to_ft(ay, scale), 0.0),
                            XYZ(paper_to_ft(bx, scale), paper_to_ft(by, scale), 0.0), room_style)
        for x, y_top, text in layout["labels"]:
            if text:
                text_note(doc, view, XYZ(paper_to_ft(x, scale), paper_to_ft(y_top, scale), 0.0), text, room_text.Id)

        # the married model element's id, so the pair can be found again later
        link_param = as_text(settings.get("link_param", u"")).strip()
        linked = 0
        link_missing = 0
        if link_param:
            for rec in records:
                inst = placed.get(rec["id"])
                if inst is None:
                    continue
                param = find_param(inst, link_param, False)
                if param is None:
                    link_missing += 1
                    continue
                if set_param(param, as_text(rec["id"])) == "ok":
                    linked += 1
            if link_missing:
                issues.append(u"'{0}' is not on {1} of the detail items, so they cannot be found again "
                              u"from the Married Element List - add it to those families as a text "
                              u"instance parameter.".format(link_param, link_missing))
        else:
            issues.append(u"No linked element ID parameter is named in Settings, so the detail items "
                          u"are not married to their model elements.")

        # LV: a board with several circuits leaving it is stretched to span
        # them, through the width parameter named on its equipment row
        stretched = 0
        stretch_failed = {}
        if is_lv:
            widths = layout.get("widths", {})
            for rec in records:
                inst = placed.get(rec["id"])
                param_name = sb_logic.row_stretch_param(rec["equipment"])
                if inst is None or not param_name:
                    continue
                want = widths.get(rec["id"])
                if not want:
                    continue
                over = to_float(settings.get("lv_stretch_over_mm"), 9.0)
                target_mm = want + 2.0 * over        # a little past the last circuit each end
                param = find_param(inst, param_name, False)
                if param is None:
                    stretch_failed[param_name] = stretch_failed.get(param_name, 0) + 1
                    continue
                try:
                    param.Set(paper_to_ft(target_mm, scale))
                    stretched += 1
                except Exception:
                    stretch_failed[param_name] = stretch_failed.get(param_name, 0) + 1
            for name in sorted(stretch_failed.keys()):
                issues.append(u"'{0}' could not be set on {1} detail item(s) - it has to be a length "
                              u"INSTANCE parameter on the detail item family.".format(
                                  name, stretch_failed[name]))

        # LV: the Main LV board spans its outgoing ways, where its family can
        if (is_lv and main_id is not None and placed.get(main_id) is not None
                and settings.get("lv_stretch_main", u"1") != u"0"):
            width = layout.get("widths", {}).get(main_id)
            spot = layout["items"].get(main_id)
            if width and spot:
                if stretch_across(doc, placed[main_id], spot[0], spot[0] + width, scale):
                    lines.append(u"The Main LV board was stretched across its {0:.0f}mm of outgoing "
                                 u"ways.".format(width))
                else:
                    issues.append(u"The Main LV board's detail item is not line based, so it could "
                                  u"not be stretched across its ways - it is drawn at its own size.")

        # LV: the feeders, one orthogonal polyline per circuit
        routes_drawn = 0
        for label, src, dst, points in layout.get("routes", []):
            for (ax, ay), (bx, by) in zip(points, points[1:]):
                if abs(ax - bx) < 1e-9 and abs(ay - by) < 1e-9:
                    continue
                try:
                    detail_line(doc, view, XYZ(paper_to_ft(ax, scale), paper_to_ft(ay, scale), 0.0),
                                XYZ(paper_to_ft(bx, scale), paper_to_ft(by, scale), 0.0), circuit_style)
                except Exception:
                    issues.append(u"Circuit {0}: a segment could not be drawn.".format(label or u"?"))
            routes_drawn += 1

        # parameter transfer - the shared list, or whatever the row overrides it with
        shared_pairs = parse_transfer(settings.get("transfer", u""))
        templates = sb_logic.decode_templates(settings.get("templates", u""))
        pairs_for_row = {}
        for row in equipment_rows:
            pairs_for_row[id(row)] = effective_transfer(row, shared_pairs, templates)
        skipped_rows = [row[0] for row in equipment_rows if not pairs_for_row[id(row)]]
        transferred = 0
        missing_target = {}
        type_target = {}
        missing_source = {}
        for rec in records:
            inst = placed.get(rec["id"])
            if inst is None:
                continue
            for source, target in pairs_for_row.get(id(rec["equipment"]), []):
                value, found = resolve_source(rec, source, rec["equipment"])
                if not found:
                    missing_source[source] = missing_source.get(source, 0) + 1
                    continue
                param = find_param(inst, target, False)
                if param is None:
                    if find_param(inst, target, True) is not None:
                        type_target[target] = type_target.get(target, 0) + 1
                    else:
                        missing_target[target] = missing_target.get(target, 0) + 1
                    continue
                if set_param(param, value) == "ok":
                    transferred += 1
        for target in sorted(missing_target.keys()):
            issues.append(u"Detail items carry no parameter '{0}' - add it to the detail item family as an "
                          u"instance parameter, or take that line out of the transfer list ({1} skipped).".format(
                              target, missing_target[target]))
        for target in sorted(type_target.keys()):
            issues.append(u"'{0}' is a TYPE parameter on the detail item, so writing it would change every "
                          u"item of that type - skipped ({1}). Use an instance parameter instead.".format(
                              target, type_target[target]))
        if skipped_rows:
            issues.append(u"No parameters written for: {0} (set to skip in the Equipment table).".format(
                u", ".join([r or u"(unnamed)" for r in skipped_rows])))
        for source in sorted(missing_source.keys()):
            issues.append(u"Model elements carry no parameter '{0}' on the instance or its type "
                          u"({1} skipped).".format(source, missing_source[source]))

        trans.Commit()
        group.Assimilate()
    except Exception:
        try:
            group.RollBack()
        except Exception:
            pass
        raise

    if not layout["fits"]:
        sheet_h = frame[3] - frame[1]
        issues.append(u"The schematic is {0:.0f}mm tall against {1:.0f}mm of {2} - it is drawn in full and "
                      u"nothing overlaps, but it runs past the sheet. A bigger sheet size in Settings, or a "
                      u"tighter room gap, will bring it back in.".format(
                          layout["height"], sheet_h, settings.get("sheet_size", u"A1")))
    wrapped = []
    for level in levels:
        rows = layout["rows"].get(level["id"], 0)
        if rows > 1:
            wrapped.append(u"{0} ({1} rows)".format(level["name"], rows))


    if settings.get("open_view", u"1") != u"0" and view is not None:
        try:
            uidoc.ActiveView = view
            for uiview in uidoc.GetOpenUIViews():
                if eid_value(uiview.ViewId) == eid_value(view.Id):
                    uiview.ZoomToFit()
        except Exception:
            pass

    lines.append(u"View: {0} (1:{1}, {2})".format(view_name, scale, settings.get("sheet_size", u"A1")))
    lines.append(u"Levels drawn: {0} of {1} in the project".format(len(levels), len(all_levels)))
    lines.append(u"Equipment placed: {0} of {1}".format(len(placed), len(records)))
    lines.append(u"Rooms boxed: {0}   Items with no room: {1}".format(len(layout["boxes"]), no_room))
    if is_lv:
        lines.append(circuit_note)
        if stretched:
            lines.append(u"Boards stretched to span their circuits: {0}".format(stretched))
        lines.append(u"Feeders drawn: {0} of {1} circuit(s) between the placed equipment".format(
            routes_drawn, len(edges)))
        if layout.get("right", 0) > frame[2]:
            lines.append(u"The drawing was widened to {0:.0f}mm to keep the feeders clear of the panels".format(
                layout["right"] - frame[0]))
        clashes = layout.get("clashes", [])
        if clashes:
            issues.append(u"{0} feeder run(s) pass through a panel they do not serve - these are the "
                          u"feeders that go down or sideways, which are routed but not kept clear of yet.".format(
                              len(clashes)))
    lines.append(u"Drawing height: {0:.0f}mm of the {1:.0f}mm available on {2}".format(
        layout["height"], frame[3] - frame[1], settings.get("sheet_size", u"A1")))
    if wrapped:
        lines.append(u"Levels given extra room: {0}".format(u", ".join(wrapped)))
    lines.append(u"Parameter values transferred: {0}".format(transferred))
    if link_param:
        lines.append(u"Married to their model elements via '{0}': {1}".format(link_param, linked))
    if browser_rows:
        lines.append(u"Browser parameters written: {0}".format(len([r for r in browser_rows if r[1]])))
    if issues:
        lines.append(u"")
        lines.append(u"Needs a look:")
        lines.extend([u"  - " + i for i in issues])
    summary = u"{0}: {1} equipment across {2} level(s)".format(view_name, len(placed), len(levels))
    if issues:
        summary += u"  |  {0} item(s) need a look".format(len(issues))
    log(summary)
    return {"ok": True, "summary": summary, "lines": lines, "detail": u"", "issues": len(issues)}


# ---------------------------------------------------------------------------
# MARRIED ELEMENT LIST - run a parameter template
# ---------------------------------------------------------------------------

def run_template(uidoc, doc, job):
    """Push parameter values from each model element onto the detail item
    that carries its id. Each ticked item runs the template assigned to it,
    so one run can apply several templates."""
    settings = job["settings"]
    batches = job.get("batches", [])
    orphans = job.get("orphans", [])
    if not batches:
        return fail(u"Nothing ticked has a template to run.")
    link_param = as_text(settings.get("link_param", u"")).strip()
    if not link_param:
        return fail(u"No linked element ID parameter is named in Settings.")

    context = read_context(doc, settings)
    tally = {"written": 0, "unchanged": 0, "touched": 0}
    issues = []
    lines = []
    missing_model = []
    missing_target = {}
    type_target = {}
    missing_source = {}
    per_template = []
    total_ticked = sum([len(b["detail_ids"]) for b in batches])
    reports = (missing_model, missing_target, type_target, missing_source, issues)

    names = u", ".join([b["template"] for b in batches[:3]])
    trans = Transaction(doc, u"RevoBIM apply template(s) {0}".format(names or u"?"))
    quiet_transaction(trans)
    trans.Start()
    try:
        for batch in batches:
            before = (tally["written"], tally["touched"])
            for detail_id in batch["detail_ids"]:
                apply_to_detail(doc, detail_id, batch["pairs"], link_param, context, tally, reports)
            per_template.append((batch["template"],
                                 tally["touched"] - before[1],
                                 tally["written"] - before[0]))
        trans.Commit()
    except Exception:
        try:
            trans.RollBack()
        except Exception:
            pass
        raise

    for line in missing_model[:12]:
        issues.append(line)
    if len(missing_model) > 12:
        issues.append(u"...and {0} more with no model element.".format(len(missing_model) - 12))
    for target in sorted(missing_target.keys()):
        issues.append(u"Detail items carry no parameter '{0}' ({1} skipped).".format(target, missing_target[target]))
    for target in sorted(type_target.keys()):
        issues.append(u"'{0}' is a TYPE parameter on the detail item - skipped ({1}).".format(target, type_target[target]))
    for source in sorted(missing_source.keys()):
        issues.append(u"Model elements carry no parameter '{0}' ({1} skipped).".format(source, missing_source[source]))

    for name, count, count_written in per_template:
        lines.append(u"Template '{0}': {1} detail item(s), {2} value(s) written".format(name, count, count_written))
    lines.append(u"Detail items run: {0} of {1} ticked".format(tally["touched"], total_ticked))
    lines.append(u"Values written: {0}   already correct: {1}".format(tally["written"], tally["unchanged"]))
    if orphans:
        lines.append(u"Left out with no template assigned: {0}".format(len(orphans)))
    if issues:
        lines.append(u"")
        lines.append(u"Needs a look:")
        lines.extend([u"  - " + i for i in issues])

    if len(per_template) == 1:
        summary = u"{0}: {1} value(s) written onto {2} detail item(s)".format(
            per_template[0][0], tally["written"], tally["touched"])
    else:
        summary = u"{0} templates: {1} value(s) written onto {2} detail item(s)".format(
            len(per_template), tally["written"], tally["touched"])
    if issues:
        summary += u"  |  {0} item(s) need a look".format(len(issues))
    log(summary)
    return {"ok": True, "kind": "template", "summary": summary, "lines": lines, "detail": u"",
            "issues": len(issues)}


def read_context(doc, settings):
    """What every element read in a template run needs: levels, links, phase."""
    all_levels = sb_model.read_levels(doc)
    abbr_of = {}
    for name, abbr, included in sb_logic.level_rows(settings, [l["name"] for l in all_levels]):
        abbr_of[name] = abbr
    level_by_id = {}
    for level in all_levels:
        level_by_id[level["id"]] = level
    return {
        "levels": all_levels,
        "level_by_id": level_by_id,
        "abbr_of": abbr_of,
        "links": sb_model.read_links(doc),
        "phase": sb_model.last_phase(doc),
        "room_param": settings.get("room_name_param", u"Name"),
        "room_source": u"element" if settings.get("room_source") == u"element" else u"room",
        "element_room_param": as_text(settings.get("room_element_param", u"")).strip(),
    }


def apply_to_detail(doc, detail_id, pairs, link_param, context, tally, reports):
    """One detail item: find its model element again and write the pairs."""
    missing_model, missing_target, type_target, missing_source, issues = reports
    detail = doc.GetElement(make_id(detail_id))
    if detail is None:
        missing_model.append(u"detail item {0} no longer exists".format(detail_id))
        return
    link_id = sb_logic.link_id_of(param_text(find_param(detail, link_param, False)))
    model = doc.GetElement(make_id(link_id)) if link_id is not None else None
    if model is None:
        missing_model.append(u"detail item {0}: model element {1} not found".format(
            detail_id, link_id if link_id is not None else u"?"))
        return

    rec = sb_model.instance_record(doc, model, context["levels"], context["links"], context["phase"],
                                   context["room_param"], context["room_source"],
                                   context["element_room_param"])
    level = context["level_by_id"].get(rec["level_id"])
    rec["level_name"] = level["name"] if level else u""
    rec["level_abbr"] = context["abbr_of"].get(rec["level_name"], u"")
    row_stub = [u"", u"", u"", u"", u"", u""]
    tally["touched"] += 1

    for source, target in pairs:
        value, found = resolve_source(rec, source, row_stub)
        if not found:
            missing_source[source] = missing_source.get(source, 0) + 1
            continue
        param = find_param(detail, target, False)
        if param is None:
            if find_param(detail, target, True) is not None:
                type_target[target] = type_target.get(target, 0) + 1
            else:
                missing_target[target] = missing_target.get(target, 0) + 1
            continue
        if as_text(param_text(param)) == as_text(value):
            tally["unchanged"] += 1
            continue
        if set_param(param, value) == "ok":
            tally["written"] += 1
        else:
            issues.append(u"Detail item {0}: '{1}' would not take '{2}'.".format(detail_id, target, value))
