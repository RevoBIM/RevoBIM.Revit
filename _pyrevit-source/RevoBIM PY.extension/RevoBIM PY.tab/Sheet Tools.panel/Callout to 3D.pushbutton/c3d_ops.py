# -*- coding: utf-8 -*-
"""Callout to 3D - every write to the model.

The window is modeless, so nothing in here is called from a button directly:
the window fills in a plan, raises the ExternalEvent, and Revit calls back on
its own thread with a live Document.

One TransactionGroup covers the run so Revit's undo sees one step, but each
callout group takes its own transaction inside it - a group Revit refuses is
rolled back and named, and the rest of the run carries on.
"""

import c3d_clr  # noqa: F401  assemblies first, always

import traceback

import c3d_core as core
import c3d_geom as geom
import c3d_model as model

from Autodesk.Revit.DB import (                      # noqa: E402
    Transaction, TransactionGroup, TransactionStatus, XYZ,
    View3D, ViewSection, ViewSheet, Viewport, IFailuresPreprocessor,
    FailureProcessingResult, ViewDuplicateOption,
)
from Autodesk.Revit.UI import IExternalEventHandler   # noqa: E402


# ---------------------------------------------------------------------------
# noise suppression
# ---------------------------------------------------------------------------


class WarningSwallower(IFailuresPreprocessor):
    """Deletes warnings so a run cannot stop on a dialog."""

    def __init__(self):
        self.deleted = 0

    def PreprocessFailures(self, accessor):
        try:
            for failure in accessor.GetFailureMessages():
                accessor.DeleteWarning(failure)
                self.deleted += 1
        except Exception:
            pass
        return FailureProcessingResult.Continue


_dialog_hooked = [False]
_dialog_active = [False]
_dialog_seen = []


def _on_dialog(sender, args):
    if not _dialog_active[0]:
        return
    try:
        _dialog_seen.append(u"{0}".format(args.DialogId))
    except Exception:
        pass
    try:
        args.OverrideResult(1)
    except Exception:
        pass


def hook_dialogs(uiapp):
    """Hooked once and switched with a flag - unsubscribing an IronPython
    bound method from a .NET event is not reliable."""
    if _dialog_hooked[0]:
        return
    try:
        uiapp.DialogBoxShowing += _on_dialog
        _dialog_hooked[0] = True
    except Exception as err:
        core.log("dialog hook failed: {0}".format(err))


def dialogs(active):
    _dialog_active[0] = bool(active)
    if active:
        del _dialog_seen[:]


def suppressed_dialogs():
    return list(_dialog_seen)


# ---------------------------------------------------------------------------
# the plan
# ---------------------------------------------------------------------------


def callout_template_name(doc, row):
    """The view template on the callout - the discipline the sheet is named
    after.  Falls back to the view it was cut in, then to nothing."""
    for candidate in (row.get("view"), None):
        if candidate is None:
            continue
        try:
            tid = candidate.ViewTemplateId
            if tid is not None and core.eid_value(tid) > 0:
                return model._name_of(doc.GetElement(tid))
        except Exception:
            pass
    parent_name = row.get("parent_name") or ""
    return parent_name


def sane_band(band, most_mm=30000.0, least_mm=100.0):
    """A view range Revit hands back can be inside out or kilometres tall when
    a plane is set oddly.  Using it anyway makes a section box nothing will
    ever show through, so it is checked before it is trusted."""
    try:
        low, high = float(band[0]), float(band[1])
    except Exception:
        return False
    span = high - low
    return least_mm <= span <= most_mm


def band_for(row, settings):
    """The bottom and top of everything made for one callout, in millimetres.

    The 3D section box and every section share it.  Two separate rules for the
    same question is two chances to disagree.
    """
    level = row.get("level_mm", 0.0)
    rule = settings.get("3d_top_rule", "view_range")
    if str(settings.get("sec_top_rule", "match_3d")) != "match_3d":
        rule = settings.get("sec_top_rule", rule)

    below = core.get_float(settings, "3d_bottom_offset_mm", 50.0)
    top_offset = core.get_float(settings, "3d_top_offset_mm", -200.0)
    if str(rule).strip().lower() == "view_range":
        # the callout's own view range, which is literally what the plan
        # shows - with the box's own offsets on it, so the top can stop
        # short of the slab over it here as well as on the level rule
        found = row.get("range_mm")
        if found and sane_band(found):
            return _offset_band(float(found[0]), float(found[1]), below, top_offset)
        rule = "next_level"          # unlimited, unreadable or absurd

    base = level - core.get_float(settings, "3d_bottom_offset_mm", 50.0)
    top = geom.top_z_mm(rule, level, row.get("next_level_mm"),
                        core.get_float(settings, "3d_top_fixed_mm", 4000.0),
                        core.get_float(settings, "3d_top_offset_mm", -300.0))
    return base, top


def section_band(row, settings, band=None):
    """The band the sections cut over: the 3D's band, opened up by the two
    section offsets - below the bottom level and above the top one - so a
    section can show the slab, the ceiling void or the floor above without
    the 3D box growing with it.  Never less than 100mm tall."""
    base, top = band or band_for(row, settings)
    below = core.get_float(settings, "sec_below_mm", 0.0)
    above = core.get_float(settings, "sec_above_mm", 0.0)
    low, high = float(base) - below, float(top) + above
    if high - low < 100.0:
        middle = (float(base) + float(top)) / 2.0
        low, high = middle - 50.0, middle + 50.0
    return low, high


def _offset_band(base, top, below, top_offset):
    """A band moved by the 3D box's offsets: the bottom `below` under its
    bottom, the top `top_offset` from its top (negative is down).  Offsets
    that would turn it inside out are dropped rather than trusted."""
    low, high = float(base) - float(below), float(top) + float(top_offset)
    if high - low < 100.0:
        return float(base), float(top)
    return low, high


def build_plan(doc, rows, settings):
    """Exactly what the run will create, worked out before anything is
    written, so Apply can list it and the preview can show it."""
    taken_views, taken_sheets, taken_numbers = model.existing_names(doc)
    detail_counts = {}
    groups = []
    group_rule = str(settings.get("sheet_group_rule", "per_callout")).lower()

    ordered = {}
    for row in rows:
        key = row["level_name"] if group_rule == "per_level" else row.get("group") or row["name"]
        ordered.setdefault(key, []).append(row)

    kind_3d = settings.get("kind_token_3d") or "3D"
    kind_section = settings.get("kind_token_section") or "Section"
    view_pattern = settings.get("view_name_pattern") or core.DEFAULTS["view_name_pattern"]
    abbrev_source = str(settings.get("abbrev_source", "callout")).lower()

    for key in sorted(ordered.keys(), key=lambda text: u"{0}".format(text).lower()):
        members = ordered[key]
        first = members[0]
        level_name = core.level_token(first["level_name"], settings)

        template_name = callout_template_name(doc, first)
        if abbrev_source != "callout" or not template_name:
            template_name = settings.get("3d_template") or template_name
        abbrev = core.abbreviate_template(template_name, settings)

        entry = {
            "key": key,
            "rows": members,
            "level_name": level_name,
            "abbrev": abbrev,
            "template_name": template_name,
            "size": first.get("size") or settings.get("sheet_size_default", "A1"),
            "views": [],
            "renames": [],
            "notes": [],
        }

        for row in members:
            tokens = {"level": level_name, "abbrev": abbrev,
                      "callout": row["name"], "kind": kind_3d}
            name3d = core.unique_name(view_pattern, tokens, taken_views)
            entry["views"].append({"kind": "3d", "row": row, "name": name3d})

            # the sections are cut over the same band as the 3D box, so the
            # two agree by construction - opened up only by the section
            # offsets below and above, which are asked for by name
            row["band"] = band_for(row, settings)
            base, top = section_band(row, settings, row["band"])
            row["section_band"] = (base, top)

            frames = geom.section_frames(
                geom.extents_mm(row.get("frame"), 0.0) or (0, 0, 0, 0),
                row.get("x_count", 0), row.get("y_count", 0),
                base, top,
                core.get_float(settings, "sec_side_margin_mm", 250.0),
                bool(row.get("flip_x", core.get_bool(settings, "sec_flip_x"))),
                bool(row.get("flip_y", core.get_bool(settings, "sec_flip_y"))),
                row.get("flips") or {}, row.get("cuts") or {})
            for spec in frames:
                axis = spec.get("axis", "X")
                tokens_section = dict(tokens)
                # the axis goes in the name, so a section can be told from its
                # neighbour in the project browser without opening it
                tokens_section["kind"] = u"{0} {1}".format(kind_section, spec["label"])
                tokens_section["axis"] = axis
                name = core.unique_name(view_pattern, tokens_section, taken_views)
                entry["views"].append({"kind": "section", "row": row,
                                       "name": name, "spec": spec})

            if core.get_bool(settings, "rename_callouts", True):
                new_name, changed = core.callout_new_name(
                    row["name"], level_name, settings, taken_views)
                if changed:
                    entry["renames"].append((row, new_name))

        tokens = {"level": level_name, "abbrev": abbrev,
                  "callout": first["name"]}
        entry["sheet_number"] = core.sheet_number_for(
            settings.get("sheet_number_pattern") or core.DEFAULTS["sheet_number_pattern"],
            tokens, taken_numbers, core.get_int(settings, "sheet_number_start", 1))
        entry["sheet_name"] = core.sheet_name_for(
            settings.get("sheet_name_pattern") or core.DEFAULTS["sheet_name_pattern"],
            tokens, detail_counts)
        if entry["sheet_name"].strip().lower() in taken_sheets:
            entry["notes"].append(u"a sheet is already called {0}".format(entry["sheet_name"]))
        taken_sheets.add(entry["sheet_name"].strip().lower())

        groups.append(entry)

    return groups


def plan_lines(groups):
    """The 'here is what Apply will do' list."""
    lines = []
    for entry in groups:
        lines.append(u"Sheet  {0}  -  {1}   ({2})".format(
            entry["sheet_number"], entry["sheet_name"], entry["size"]))

        # the numbers the box and the sections will actually be built from.
        # "it shows nothing" is unanswerable without them, and they cost one
        # line each to print before anything is written
        for row in entry["rows"]:
            frame = row.get("frame")
            base, top = row.get("band") or band_for(row, {})
            if frame:
                centre = frame.get("centre", (0.0, 0.0))
                lines.append(
                    u"    {0}".format(row.get("name", "")))
                lines.append(
                    u"        level        {0} at {1:.0f}mm".format(
                        row.get("level_name") or "NONE FOUND", row.get("level_mm", 0.0)))
                lines.append(
                    u"        callout      {0:.0f} x {1:.0f}mm, centred at "
                    u"{2:.0f}, {3:.0f}{4}   (read from the {5})".format(
                        frame["half_x"] * 2.0, frame["half_y"] * 2.0,
                        centre[0], centre[1],
                        ", rotated" if frame.get("rotated") else "",
                        frame.get("source", "crop box")))
                cut = row.get("section_band") or (base, top)
                if (round(cut[0]), round(cut[1])) == (round(base), round(top)):
                    lines.append(
                        u"        box and cuts {0:.0f}mm to {1:.0f}mm{2}".format(
                            base, top,
                            "   (the callout's view range)" if row.get("range_mm") else ""))
                else:
                    lines.append(
                        u"        3D box       {0:.0f}mm to {1:.0f}mm{2}".format(
                            base, top,
                            "   (the callout's view range)" if row.get("range_mm") else ""))
                    lines.append(
                        u"        sections     {0:.0f}mm to {1:.0f}mm   ({2:.0f} below, "
                        u"{3:.0f} above)".format(cut[0], cut[1], base - cut[0], cut[1] - top))
            else:
                lines.append(u"    {0}   NO CROP BOX - nothing can be built from it"
                             .format(row.get("name", "")))

        for row, new_name in entry["renames"]:
            lines.append(u"    rename callout   {0}  ->  {1}".format(row["name"], new_name))
        for item in entry["views"]:
            if item["kind"] == "3d":
                lines.append(u"    new 3D           {0}".format(item["name"]))
            else:
                lines.append(u"    new section      {0}   ({1} axis, depth {2:.0f}mm)".format(
                    item["name"], item["spec"]["axis"], item["row"].get("depth_mm", 500)))
        for note in entry["notes"]:
            lines.append(u"    note             {0}".format(note))
    return lines


# ---------------------------------------------------------------------------
# the writes
# ---------------------------------------------------------------------------


def _set_template(view, template_id, results, what):
    if template_id is None or core.eid_value(template_id) <= 0:
        return False
    try:
        view.ViewTemplateId = template_id
        try:
            landed = core.eid_value(view.ViewTemplateId) == core.eid_value(template_id)
        except Exception:
            landed = True
        if not landed:
            results.warn(u"{0}: the view template would not take".format(what))
        return landed
    except Exception as err:
        results.warn(u"{0}: view template refused - {1}".format(what, err))
        return False


def _set_scale(view, scale, results, what):
    """Set a view's scale and prove it landed.

    A scale write is one of the quiet ones: a view template that controls the
    scale swallows it without raising, so the 3D would come out at whatever
    Revit felt like while the sections sat at 1:50.  It is read back, and a
    scale that would not take says so and names the template holding it.
    """
    try:
        wanted = int(scale or 0)
    except Exception:
        wanted = 0
    if wanted <= 0:
        return
    try:
        view.Scale = wanted
    except Exception as err:
        results.warn(u"{0}: the scale would not go to 1:{1} - {2}".format(what, wanted, err))
        return
    try:
        landed = int(view.Scale)
    except Exception:
        return
    if landed == wanted:
        return
    holder = ""
    try:
        template = view.Document.GetElement(view.ViewTemplateId)
        if template is not None:
            holder = u", which its template '{0}' is holding".format(
                model._name_of(template))
    except Exception:
        holder = ""
    results.warn(u"{0}: asked for 1:{1} and it came back 1:{2}{3}".format(
        what, wanted, landed, holder))


def scale_where_free(doc, ctx, view, key, fallback, name):
    """Give a view the scale asked for under `key`, unless its template holds
    the scale - then the template wins and says so, once per run per kind.
    With nothing asked for, `fallback` (0 for leave it) is used as before."""
    results = ctx["results"]
    own = core.parse_scale(ctx["settings"].get(key, ""))
    if own and model.template_controls_scale(doc, view):
        said = ctx.setdefault("scale_held", set())
        if key not in said:
            said.add(key)
            kind = dict(core.SCALE_KEYS).get(key, "view")
            template = doc.GetElement(view.ViewTemplateId)
            results.note(u"the {0} views kept their template's scale rather than {1} - "
                         u"'{2}' holds the scale".format(kind, core.scale_text(own),
                                                         model._name_of(template)))
        return False
    wanted = own or fallback
    if wanted:
        _set_scale(view, wanted, results, name)
    return bool(own)


def _rule_scale(settings, row):
    """The scale every new view takes when it has none of its own."""
    if str(settings.get("view_scale_rule", "match_callout")).lower() == "fixed":
        return core.get_int(settings, "view_scale_fixed", 50)
    return row.get("scale", 0)


def make_3d(doc, ctx, row, name):
    settings = ctx["settings"]
    results = ctx["results"]
    frame = row.get("frame")
    if not frame:
        results.fail(u"{0}: the callout has no crop box to read".format(row["name"]))
        return None

    vft = ctx.get("vft_3d")
    if vft is None:
        results.fail(u"no 3D view family type in the project")
        return None

    view = View3D.CreateIsometric(doc, vft.Id)
    try:
        view.Name = core.clean_name(name)
    except Exception:
        try:
            from Autodesk.Revit.DB import Element
            Element.Name.SetValue(view, core.clean_name(name))
        except Exception as err:
            results.warn(u"{0}: could not be named - {1}".format(name, err))

    _set_template(view, ctx.get("template_3d"), results, name)

    base, top = row.get("band") or band_for(row, settings)

    # THE CROP PLANE IS THE CHECK.  A plan's crop sits at its cut plane, which
    # is inside its view range by definition, so a band that does not contain
    # it is not measured against the same datum as the model - which is what
    # reading the wrong level elevation did, 88 metres out and every view
    # empty.
    crop_z = (frame or {}).get("z")
    if crop_z is not None and not (base - 1.0 <= crop_z <= top + 1.0):
        results.fail(
            u"{0}: the band is {1:.0f}mm to {2:.0f}mm but the callout's own crop "
            u"plane is at {3:.0f}mm, so they are not measured from the same datum. "
            u"Nothing was built for it - see the debug panel"
            .format(name, base, top, crop_z))
        return None

    if top <= base + 1.0:
        results.fail(u"{0}: the box would be {1:.0f}mm to {2:.0f}mm, which is "
                     u"inside out - check the callout's view range"
                     .format(name, base, top))
        return None
    if not row.get("level_name"):
        results.warn(u"{0}: no level was found for the callout, so the box is "
                     u"measured from datum".format(name))
    extents = geom.extents_mm(frame, core.get_float(settings, "3d_xy_margin_mm", 0.0))
    box = geom.section_box(frame, extents, base, top)

    try:
        view.IsSectionBoxActive = True
        view.SetSectionBox(box)
    except Exception as err:
        results.fail(u"{0}: the section box would not set - {1}".format(name, err))

    try:
        read = view.GetSectionBox()
        if read is None:
            results.warn(u"{0}: the section box read back empty".format(name))
        else:
            origin_z = 0.0
            try:
                origin_z = float(read.Transform.Origin.Z)
            except Exception:
                origin_z = 0.0
            results.note(u"{0}: box centred at {1:.0f}, {2:.0f}, {3:.0f}mm to "
                         u"{4:.0f}mm, from the {5}".format(
                             name, frame.get("centre", (0, 0))[0],
                             frame.get("centre", (0, 0))[1], base, top,
                             frame.get("source", "crop box")))
            got = core.ft_to_mm(read.Min.Z + origin_z)
            if abs(got - base) > 25.0:
                results.warn(u"{0}: the box bottom read back {1:.0f}mm, wanted {2:.0f}mm"
                             .format(name, got, base))
            try:
                middle = read.Transform.OfPoint(XYZ(
                    (read.Min.X + read.Max.X) / 2.0,
                    (read.Min.Y + read.Max.Y) / 2.0, 0.0))
                wanted = frame.get("centre", (0.0, 0.0))
                off = max(abs(core.ft_to_mm(middle.X) - wanted[0]),
                          abs(core.ft_to_mm(middle.Y) - wanted[1]))
                if off > 50.0:
                    results.warn(
                        u"{0}: the box centre read back {1:.0f}mm off the callout"
                        .format(name, off))
            except Exception:
                pass
    except Exception:
        pass

    # aim the camera at the middle of the box, not at the project origin -
    # SetOrientation moves the target as well as the direction, so an eye left
    # at the origin points the view at the base point and it comes up empty
    geom.orient_3d(view, settings.get("3d_orientation", "se_iso"),
                   geom.box_centre(box),
                   pitch_degrees=core.get_float(settings, "3d_pitch_degrees",
                                                geom.ISOMETRIC_PITCH))

    # THE CROP IS PULLED IN ROUND THE BOX BEFORE THE VIEW GOES ANYWHERE.
    # An uncropped 3D is as big as whatever Revit decides is visible, which is
    # why it landed on the sheet at the wrong size; cropped tight to the
    # section box it takes exactly the room the callout needs.
    if core.get_bool(settings, "3d_crop_tight", True):
        doc.Regenerate()
        try:
            view.CropBoxActive = True
        except Exception as err:
            results.warn(u"{0}: the crop would not switch on - {1}".format(name, err))
        size = geom.tighten_3d_crop(
            view, box, core.get_float(settings, "3d_crop_margin_mm", 150.0))
        if size is None:
            results.warn(u"{0}: the crop region could not be pulled in round the "
                         u"section box".format(name))
        else:
            core.log(u"{0}: cropped to {1:.0f} x {2:.0f}mm".format(name, size[0], size[1]))
    try:
        view.CropBoxActive = core.get_bool(settings, "3d_crop_active", True)
        view.CropBoxVisible = core.get_bool(settings, "3d_crop_visible", True)
    except Exception as err:
        results.warn(u"{0}: the crop settings would not take - {1}".format(name, err))

    if not core.get_bool(settings, "3d_section_box_visible", True):
        try:
            from Autodesk.Revit.DB import BuiltInCategory
            view.SetCategoryHidden(
                doc.Settings.Categories.get_Item(
                    BuiltInCategory.OST_SectionBox).Id, True)
        except Exception:
            pass

    # its own scale when one is asked for and the template leaves it free;
    # else the same as the other views on the sheet
    scale_where_free(doc, ctx, view, "3d_scale", _rule_scale(settings, row), name)

    return view


def make_section(doc, ctx, row, name, spec):
    settings = ctx["settings"]
    results = ctx["results"]
    frame = row.get("frame")
    vft = ctx.get("vft_section")
    if vft is None:
        results.fail(u"no section view family type in the project")
        return None

    depth = row.get("depth_mm", core.get_float(settings, "sec_depth_mm", 500.0))
    box, look = geom.section_creation_box(frame, spec, depth, ctx.get("section_sign", -1.0))
    try:
        view = ViewSection.CreateSection(doc, vft.Id, box)
    except Exception as err:
        results.fail(u"{0}: Revit refused the section - {1}".format(name, err))
        return None

    # prove the direction once per run, and turn the whole run round if the
    # release disagrees with the convention
    if not ctx.get("section_checked"):
        ctx["section_checked"] = True
        if geom.view_looks_the_wrong_way(view, look):
            ctx["section_sign"] = -ctx.get("section_sign", -1.0)
            try:
                doc.Delete(view.Id)
            except Exception:
                pass
            box, look = geom.section_creation_box(frame, spec, depth, ctx["section_sign"])
            try:
                view = ViewSection.CreateSection(doc, vft.Id, box)
                results.note(u"sections turned round to face the way they were asked to")
            except Exception as err:
                results.fail(u"{0}: Revit refused the section - {1}".format(name, err))
                return None

    try:
        view.Name = core.clean_name(name)
    except Exception:
        try:
            from Autodesk.Revit.DB import Element
            Element.Name.SetValue(view, core.clean_name(name))
        except Exception as err:
            results.warn(u"{0}: could not be named - {1}".format(name, err))

    _set_template(view, ctx.get("template_section"), results, name)

    # the label under the viewport, so the sheet reads "Section X1" rather
    # than repeating the whole view name
    label = spec.get("label")
    if label and core.get_bool(settings, "sec_title_on_sheet", True):
        pattern = settings.get("sec_title_pattern", "Section {label}")
        try:
            from Autodesk.Revit.DB import BuiltInParameter
            param = view.get_Parameter(BuiltInParameter.VIEW_DESCRIPTION)
            if param is not None and not param.IsReadOnly:
                param.Set(core.expand(pattern, {"label": label,
                                                "axis": spec.get("axis", ""),
                                                "callout": row.get("name", "")}))
        except Exception as err:
            results.warn(u"{0}: the title on sheet would not set - {1}".format(name, err))

    if core.get_bool(settings, "sec_far_clip_active", True):
        if not geom.set_far_clip(view, depth):
            results.warn(u"{0}: the far clip would not set to {1:.0f}mm".format(name, depth))

    # the section scale only goes where the template leaves the scale alone
    scale_where_free(doc, ctx, view, "sec_scale", _rule_scale(settings, row), name)

    return view


def rename_callout(doc, ctx, row, new_name):
    results = ctx["results"]
    view = row["view"]
    old = row["name"]
    ok = False
    try:
        view.Name = core.clean_name(new_name)
        ok = True
    except Exception:
        try:
            from Autodesk.Revit.DB import Element
            Element.Name.SetValue(view, core.clean_name(new_name))
            ok = True
        except Exception as err:
            results.warn(u"{0}: rename refused - {1}".format(old, err))
    if ok:
        try:
            landed = model._name_of(view).strip().lower() == core.clean_name(new_name).strip().lower()
        except Exception:
            landed = True
        if not landed:
            results.warn(u"{0}: the rename did not take".format(old))
            return False
        row["name"] = core.clean_name(new_name)
        results.note(u"callout renamed  {0}  ->  {1}".format(old, row["name"]))
    return ok


def make_sheet(doc, ctx, entry):
    results = ctx["results"]
    block = model.title_block_for_size(doc, entry["size"], ctx.get("titleblocks", {}))
    if block is None:
        results.fail(u"no title block family is loaded, so no sheet could be made")
        return None
    try:
        if not block["type"].IsActive:
            block["type"].Activate()
            doc.Regenerate()
    except Exception:
        pass
    try:
        sheet = ViewSheet.Create(doc, block["id"])
    except Exception as err:
        results.fail(u"the sheet would not be created - {0}".format(err))
        return None
    try:
        sheet.SheetNumber = entry["sheet_number"]
    except Exception as err:
        results.warn(u"sheet number {0} refused - {1}".format(entry["sheet_number"], err))
    try:
        sheet.Name = entry["sheet_name"]
    except Exception as err:
        results.warn(u"sheet name refused - {0}".format(err))
    return sheet


def _view_kind(view):
    """Which sort of view it is, in the message - "the 3D would not go on" is a
    different problem from "a section would not go on"."""
    try:
        return u"{0}".format(view.ViewType)
    except Exception:
        return "view"


def create_viewport(doc, ctx, sheet, view, vp_type, where_mm):
    """Put one view on the sheet at a rough spot, with its viewport type.

    No regenerate on the way in: the views were committed by the making
    transaction, which is the thing Viewport.Create actually needs.  Only a
    refusal earns a regenerate and one more try.  `CanAddViewToSheet` is asked
    for the report, never as a gate - it answers about the state Revit is in
    right now, and acting on a no turns a timing problem into a missing view.
    """
    results = ctx["results"]
    if view is None:
        return None
    try:
        allowed = bool(Viewport.CanAddViewToSheet(doc, sheet.Id, view.Id))
    except Exception:
        allowed = True

    point = XYZ(core.mm_to_ft(where_mm[0]), core.mm_to_ft(where_mm[1]), 0.0)
    viewport, trouble = None, []
    for attempt in (1, 2):
        try:
            if attempt == 2:
                doc.Regenerate()
            viewport = Viewport.Create(doc, sheet.Id, view.Id, point)
        except Exception as err:
            trouble.append(u"{0}".format(err))
            viewport = None
        if viewport is not None:
            break

    if viewport is None:
        facts = [u"CanAddViewToSheet={0}".format(allowed)]
        for label, getter in (("id", lambda: core.eid_value(view.Id)),
                              ("type", lambda: view.ViewType),
                              ("template", lambda: core.eid_value(view.ViewTemplateId)),
                              ("canBePrinted", lambda: view.CanBePrinted),
                              ("scale", lambda: view.Scale)):
            try:
                facts.append(u"{0}={1}".format(label, getter()))
            except Exception:
                facts.append(u"{0}=?".format(label))
        line = u", ".join(facts)
        results.warn(u"{0} ({1}): Revit refused the viewport - {2}   [{3}]".format(
            model._name_of(view), _view_kind(view),
            u" / ".join(trouble) or "it returned nothing and raised nothing", line))
        core.log(u"viewport refused: {0}".format(line))
        return None
    if not allowed:
        results.note(u"{0}: Revit said the view could not go on a sheet, but it "
                     u"took it".format(model._name_of(view)))
    if vp_type is not None:
        try:
            viewport.ChangeTypeId(vp_type.Id)
        except Exception as err:
            results.warn(u"{0}: viewport type refused - {1}".format(model._name_of(view), err))
    return viewport


def measure_viewport(viewport, pad_mm):
    """A placed viewport's footprint, title and all.  Needs a regenerate first,
    done once for the whole sheet by the caller rather than once per view."""
    try:
        box = viewport.GetBoxOutline()
        centre = viewport.GetBoxCenter()
    except Exception:
        return None
    label = None
    try:
        label = viewport.GetLabelOutline()
    except Exception:
        label = None

    def pair(outline):
        if outline is None:
            return None
        return ((core.ft_to_mm(outline.MinimumPoint.X), core.ft_to_mm(outline.MinimumPoint.Y)),
                (core.ft_to_mm(outline.MaximumPoint.X), core.ft_to_mm(outline.MaximumPoint.Y)))

    return geom.footprint_mm(pair(box), pair(label),
                             (core.ft_to_mm(centre.X), core.ft_to_mm(centre.Y)), pad_mm)


def move_viewport(viewport, cell, results, what, offset):
    """Put a viewport's whole footprint in a cell, by moving its box centre
    the measured offset away from the cell's middle."""
    centre = geom.cell_centre(cell)
    try:
        viewport.SetBoxCenter(XYZ(core.mm_to_ft(centre[0] - offset[0]),
                                  core.mm_to_ft(centre[1] - offset[1]), 0.0))
        return True
    except Exception as err:
        results.warn(u"{0}: would not move into place - {1}".format(what, err))
        return False


def _place_group(doc, ctx, entry, made, needs_review=None):
    """Everything that goes onto the sheet, in its own transaction.

    Three passes: drop every viewport, regenerate ONCE, measure them all, then
    lay out and move.  The plan sits top left and the 3D top right, the X
    sections go down the left column and the Y sections down the right - a
    column cannot put two viewports side by side however their widths read.
    """
    settings = ctx["settings"]
    results = ctx["results"]
    needs_review = needs_review if needs_review is not None else []

    # looked up again by id: a handle captured before a commit is not one to
    # trust afterwards
    sheet = doc.GetElement(entry.get("sheet_id")) if entry.get("sheet_id") else None
    if sheet is None:
        results.fail(u"{0}: the sheet could not be found again after it was made"
                     .format(entry["sheet_number"]))
        return

    def view_of(item):
        try:
            found = doc.GetElement(item.get("view_id"))
        except Exception:
            found = None
        return found if found is not None else item.get("view")

    # ---- the callout, which may already be on a sheet ------------------
    first_row = entry["rows"][0]
    callout_view = first_row["view"]
    if first_row.get("sheet") is not None:
        if str(settings.get("callout_on_sheet", "report")).lower() == "duplicate":
            try:
                callout_view = doc.GetElement(
                    callout_view.Duplicate(ViewDuplicateOption.WithDetailing))
                results.note(u"{0} was already on a sheet, so a duplicate was placed"
                             .format(first_row["name"]))
            except Exception as err:
                results.warn(u"{0}: could not be duplicated - {1}".format(first_row["name"], err))
                callout_view = None
        else:
            results.warn(u"{0} is already on sheet {1}, so it was left there"
                         .format(first_row["name"], first_row.get("sheet_number", "")))
            callout_view = None

    # the callout's own scale is left alone unless one was asked for - it is
    # an existing view, drawn by somebody, and changing it changes its sheet
    if callout_view is not None:
        scale_where_free(doc, ctx, callout_view, "callout_scale", 0, first_row["name"])

    # ---- pass 1: drop -----------------------------------------------------
    wanted = []
    if callout_view is not None:
        wanted.append({"kind": "callout", "view": callout_view, "vp": ctx.get("vp_callout")})
    three_d = [item for item in made if item["kind"] == "3d"]
    if three_d:
        wanted.append({"kind": "3d", "view": view_of(three_d[0]), "vp": ctx.get("vp_3d")})
    else:
        results.warn(u"{0}: no 3D view was made, so nothing was placed in its "
                     u"cell - see the failures above".format(entry["sheet_number"]))
    for item in made:
        if item["kind"] == "section":
            wanted.append({"kind": "section", "view": view_of(item),
                           "axis": (item.get("spec") or {}).get("axis", "X"),
                           "vp": ctx.get("vp_section")})

    placed_items, missed = [], []
    for slot, item in enumerate(wanted):
        item["name"] = model._name_of(item["view"])
        # each on a spot of its own: a pile of viewports on one point is
        # asking Revit to refuse one of them
        item["viewport"] = create_viewport(doc, ctx, sheet, item["view"], item["vp"],
                                           (slot * 10.0, 0.0))
        if item["viewport"] is None:
            if item["kind"] == "section":
                missed.append(item["name"])
            continue
        placed_items.append(item)
    if missed:
        results.warn(u"{0}: {1} section(s) would not go on the sheet at all - {2}"
                     .format(entry["sheet_number"], len(missed), u", ".join(missed)))

    # ---- pass 2: one regenerate, then measure everything -----------------
    try:
        doc.Regenerate()
    except Exception:
        pass
    # the titles go up under their views first, so what is measured is the
    # footprint the sheet will really have
    gap = settings.get("title_gap_mm", "2")
    if u"{0}".format(gap).strip() != "":
        moved_titles = [item for item in placed_items
                        if tidy_label(item["viewport"], core.get_float(settings, "title_gap_mm", 2.0),
                                      results, item["name"])]
        if moved_titles:
            try:
                doc.Regenerate()
            except Exception:
                pass
    pad = core.get_float(settings, "layout_pad_mm", 4.0)
    for item in placed_items:
        item["foot"] = measure_viewport(item["viewport"], pad)
        if item["foot"] is None:
            results.warn(u"{0}: its size could not be read, so it was left where it "
                         u"landed".format(item["name"]))
    sized = [item for item in placed_items if item.get("foot")]

    # ---- pass 3: lay out and move ------------------------------------------
    def size(item):
        return (item["foot"]["width"], item["foot"]["height"])

    callout = next((item for item in sized if item["kind"] == "callout"), None)
    three = next((item for item in sized if item["kind"] == "3d"), None)
    x_run = [item for item in sized if item["kind"] == "section" and item["axis"] != "Y"]
    y_run = [item for item in sized if item["kind"] == "section" and item["axis"] == "Y"]

    # the paper is where the title block is, which is not necessarily 0,0
    origin_x, origin_y, width, height = model.sheet_frame_mm(doc, sheet)
    core.log(u"{0}: the title block runs from {1:.0f}, {2:.0f} and is {3:.0f} x {4:.0f}mm"
             .format(entry["sheet_number"], origin_x, origin_y, width, height))
    left = core.get_float(settings, "sheet_margin_left_mm", 15.0)
    right = core.get_float(settings, "sheet_margin_right_mm", 120.0)
    top = core.get_float(settings, "sheet_margin_top_mm", 15.0)
    bottom = core.get_float(settings, "sheet_margin_bottom_mm", 15.0)
    preset, dragged = core.resolve_layout(settings, geom.preset_keys())
    dragged = geom.shift_moves(dragged, (origin_x, origin_y))
    layout = geom.layout_for(
        preset,
        (origin_x + left, origin_y + bottom, width - left - right, height - top - bottom),
        size(callout) if callout else None, size(three) if three else None,
        [size(item) for item in x_run], [size(item) for item in y_run],
        core.get_float(settings, "sheet_gap_mm", 12.0),
        core.get_float(settings, "section_gap_mm", 6.0),
        core.get_float(settings, "section_min_gap_mm", 2.0))
    # a custom setout: what was dragged in the preview goes where it was
    # left, each viewport at its own measured size
    if dragged:
        layout = geom.recheck_fit(geom.apply_moves(layout, dragged),
                                  (origin_x + left, origin_y + bottom,
                                   width - left - right, height - top - bottom))
        results.note(u"{0}: laid out to the custom setout".format(entry["sheet_number"]))

    moves = [(callout, layout["callout"]), (three, layout["3d"])]
    moves += list(zip(x_run, layout["x"])) + list(zip(y_run, layout["y"]))
    placed = 0
    for item, cell in moves:
        if item is None or cell is None:
            continue
        foot = item["foot"]
        if move_viewport(item["viewport"], cell, results, item["name"],
                         (foot["offset_x"], foot["offset_y"])):
            placed += 1

    if layout["too_wide"]:
        results.warn(u"{0}: the two columns together are wider than the sheet, so "
                     u"the right hand one runs past the title strip"
                     .format(entry["sheet_number"]))
    if layout["overflow"]:
        # asked for: extra sections go below the sheet rather than being
        # dropped or shrunk, and the sheet is flagged for a look by hand
        needs_review.append(entry["sheet_number"])
        results.warn(u"{0}: MANUAL REVIEW - there are more sections than the sheet "
                     u"has room for, so the last of them sit below its bottom edge"
                     .format(entry["sheet_number"]))
    push_sheet_name(doc, ctx, sheet)
    results.sheets.append((sheet.SheetNumber, model._name_of(sheet), placed))
    try:
        results.sheet_ids.append(sheet.Id)
    except Exception:
        pass


def crop_grids(doc, ctx, made):
    """Cut every grid in each new section down to the top and bottom of the
    section's crop, so the grid lines stop at the edge of the view rather
    than running off past it.

    The ends go view specific (2D) in that section only - the grids
    themselves and every other view are left alone - and each end keeps its
    own side, so a bubble stays at the end it was on.
    """
    settings = ctx["settings"]
    results = ctx["results"]
    if not core.get_bool(settings, "sec_crop_grids", True):
        return 0
    sections = [item for item in (made or []) if item.get("kind") == "section"]
    if not sections:
        return 0
    from Autodesk.Revit.DB import Grid, DatumEnds, DatumExtentType, Line, FilteredElementCollector
    inset = core.mm_to_ft(core.get_float(settings, "sec_grid_inset_mm", 0.0))
    done, failed = 0, 0
    for item in sections:
        view = doc.GetElement(item.get("view_id")) if item.get("view_id") else None
        if view is None:
            continue
        try:
            crop = view.CropBox
            low = crop.Transform.OfPoint(XYZ(0.0, crop.Min.Y, 0.0)).Z + inset
            high = crop.Transform.OfPoint(XYZ(0.0, crop.Max.Y, 0.0)).Z - inset
        except Exception:
            continue
        if high - low < core.mm_to_ft(100.0):
            continue
        try:
            grids = list(FilteredElementCollector(doc, view.Id).OfClass(Grid))
        except Exception:
            grids = []
        for grid in grids:
            try:
                for end in (DatumEnds.End0, DatumEnds.End1):
                    grid.SetDatumExtentType(end, view, DatumExtentType.ViewSpecific)
                curves = grid.GetCurvesInView(DatumExtentType.ViewSpecific, view)
                if not curves:
                    continue
                curve = curves[0]
                start, finish = curve.GetEndPoint(0), curve.GetEndPoint(1)
                if abs(start.Z - finish.Z) < 1e-6:
                    continue                    # not a vertical line in this view
                new_start, new_end = geom.grid_ends((start.X, start.Y, start.Z),
                                                    (finish.X, finish.Y, finish.Z), low, high)
                grid.SetCurveInView(DatumExtentType.ViewSpecific, view, Line.CreateBound(
                    XYZ(*new_start), XYZ(*new_end)))
                done += 1
            except Exception as err:
                failed += 1
                core.log(u"grid {0} could not be cropped in {1}: {2}".format(
                    model._name_of(grid), item.get("name", ""), err))
    if done:
        results.note(u"{0} grid end(s) cut down to the section crop".format(done))
    if failed:
        results.warn(u"{0} grid(s) could not be cut down in the sections - a pinned or "
                     u"scope boxed grid will not take a 2D extent".format(failed))
    return done


def tidy_label(viewport, gap_mm, results=None, what=u""):
    """Move a viewport's title up to `gap_mm` under the base of the view, its
    left edge level with the view's.  Needs a regenerate before, so the
    outlines are real, and another after, so the measurement sees it."""
    try:
        box = viewport.GetBoxOutline()
        label = viewport.GetLabelOutline()
        offset = viewport.LabelOffset
    except Exception:
        return False                     # before 2022, or no title on this type
    if box is None or label is None:
        return False
    try:
        if label.MaximumPoint.X - label.MinimumPoint.X <= 1e-6:
            return False                 # a viewport type with no title shown
        dx, dy = geom.label_shift(
            ((box.MinimumPoint.X, box.MinimumPoint.Y), (box.MaximumPoint.X, box.MaximumPoint.Y)),
            ((label.MinimumPoint.X, label.MinimumPoint.Y),
             (label.MaximumPoint.X, label.MaximumPoint.Y)),
            core.mm_to_ft(gap_mm))
        viewport.LabelOffset = XYZ(offset.X + dx, offset.Y + dy, 0.0)
        return True
    except Exception as err:
        if results is not None:
            results.warn(u"{0}: its title would not move - {1}".format(what, err))
        return False


def tag_rooms(doc, ctx, made):
    """Tag every room each new section cuts that is not tagged there yet,
    with the project's default room tag (or the one picked).

    Done in the placing transaction, after the sections are committed: a
    section made in the same transaction has no crop box worth reading yet.
    A room is cut when its bounding box overlaps the section's crop box, and
    its tag goes at the middle of that overlap, 1200mm up from its floor and
    on the view plane - so it is inside the crop, on the room, and visible.
    """
    settings = ctx["settings"]
    results = ctx["results"]
    if not core.get_bool(settings, "sec_tag_rooms", True):
        return 0
    sections = [item for item in (made or []) if item.get("kind") == "section"]
    if not sections:
        return 0
    if "room_tag_type" not in ctx:
        ctx["room_tag_type"] = model.room_tag_type_id(doc, settings.get("sec_room_tag_type", ""))
        ctx["rooms"] = model.placed_rooms(doc)
    tag_type = ctx["room_tag_type"]
    if tag_type is None:
        if not ctx.get("room_tag_said"):
            ctx["room_tag_said"] = True
            results.warn(u"no room tag family is loaded, so the rooms in the sections "
                         u"were not tagged")
        return 0
    from Autodesk.Revit.DB import LinkElementId, UV

    lift = core.mm_to_ft(core.get_float(settings, "sec_room_tag_lift_mm", 1200.0))
    inset = core.mm_to_ft(150.0)
    count, failed = 0, 0
    for item in sections:
        view = doc.GetElement(item.get("view_id")) if item.get("view_id") else None
        if view is None:
            continue
        try:
            crop = view.CropBox
            inverse = crop.Transform.Inverse
        except Exception:
            continue
        done = model.tagged_room_keys(doc, view)
        for room in ctx["rooms"]:
            key = core.eid_value(room.Id)
            if key in done:
                continue
            try:
                box = room.get_BoundingBox(None)
            except Exception:
                box = None
            if box is None:
                continue
            corners = []
            for corner in geom.box_corners((box.Min.X, box.Min.Y, box.Min.Z),
                                           (box.Max.X, box.Max.Y, box.Max.Z)):
                local = inverse.OfPoint(XYZ(corner[0], corner[1], corner[2]))
                corners.append((local.X, local.Y, local.Z))
            spot = geom.room_tag_spot(corners, (crop.Min.X, crop.Min.Y, crop.Min.Z),
                                      (crop.Max.X, crop.Max.Y, crop.Max.Z), lift, inset)
            if spot is None:
                continue                      # this section does not cut it
            head = crop.Transform.OfPoint(XYZ(spot[0], spot[1], 0.0))
            try:
                tag = doc.Create.NewRoomTag(LinkElementId(room.Id), UV(head.X, head.Y), view.Id)
            except Exception as err:
                core.log(u"room {0} could not be tagged in {1}: {2}".format(
                    key, item.get("name", ""), err))
                tag = None
            if tag is None:
                failed += 1
                continue
            try:
                if core.eid_value(tag.GetTypeId()) != core.eid_value(tag_type):
                    tag.ChangeTypeId(tag_type)
            except Exception:
                pass
            # where NewRoomTag put it is read off a UV that means little in a
            # section, so the head is moved to the spot worked out above
            try:
                tag.TagHeadPosition = head
            except Exception:
                try:
                    tag.Location.Point = head
                except Exception:
                    pass
            done.add(key)
            count += 1
    if count:
        results.note(u"{0} room(s) tagged in the new sections".format(count))
    if failed:
        results.warn(u"{0} room(s) cut by a section could not be tagged - Revit only tags "
                     u"rooms a section shows, so check the template shows Rooms".format(failed))
    return count


def push_sheet_name(doc, ctx, sheet):
    """The sheet name push: split the name on the separator and write the
    pieces into the sheet parameters, then read every one of them back."""
    settings = ctx["settings"]
    results = ctx["results"]
    if not core.get_bool(settings, "push_enabled", True):
        return
    params = core.get_list(settings, "push_params")
    if not params:
        return
    pairs, spare = core.split_for_push(
        model._name_of(sheet), settings.get("push_separator", "_"), params)
    overwrite = core.get_bool(settings, "push_overwrite", True)
    prove = core.get_bool(settings, "push_prove", True)

    for name, value in pairs:
        target = None
        try:
            candidates = sheet.GetParameters(name)
        except Exception:
            candidates = []
        if not candidates:
            try:
                found = sheet.LookupParameter(name)
                candidates = [found] if found is not None else []
            except Exception:
                candidates = []
        for candidate in candidates:
            try:
                if candidate is not None and not candidate.IsReadOnly:
                    target = candidate
                    break
            except Exception:
                continue
        if target is None:
            results.warn(u"{0}: the sheet has no writable parameter called {1}"
                         .format(sheet.SheetNumber, name))
            continue
        try:
            current = target.AsString() or ""
        except Exception:
            current = ""
        if current and not overwrite:
            continue
        try:
            target.Set(value)
        except Exception as err:
            results.warn(u"{0}: {1} would not take '{2}' - {3}"
                         .format(sheet.SheetNumber, name, value, err))
            continue
        if prove:
            try:
                read = sheet.LookupParameter(name)
                back = (read.AsString() if read is not None else "") or ""
            except Exception:
                back = ""
            if back != value:
                results.warn(u"{0}: {1} read back as '{2}' rather than '{3}'"
                             .format(sheet.SheetNumber, name, back, value))
    if spare:
        results.note(u"{0}: {1} spare name piece(s) with no parameter to go in"
                     .format(sheet.SheetNumber, len(spare)))


# ---------------------------------------------------------------------------
# results
# ---------------------------------------------------------------------------


class Results(object):
    def __init__(self):
        self.failures = []
        self.warnings = []
        self.notes = []
        self.sheets = []
        self.sheet_ids = []          # so the run can offer to open them
        self.review = []             # sheets that need looking at by hand
        self.learned_sign = None     # section direction, for the window to keep
        self.views = 0

    def fail(self, text):
        self.failures.append(text)
        core.log(u"FAIL  {0}".format(text))

    def warn(self, text):
        self.warnings.append(text)
        core.log(u"WARN  {0}".format(text))

    def note(self, text):
        self.notes.append(text)
        core.log(u"      {0}".format(text))

    @property
    def needs_a_look(self):
        return bool(self.failures or self.warnings)

    def lines(self):
        out = []
        if self.sheets:
            out.append(u"Sheets created")
            for number, name, count in self.sheets:
                out.append(u"    {0}   {1}   ({2} views placed){3}".format(
                    number, name, count,
                    "   *** NEEDS A MANUAL REVIEW ***"
                    if number in (self.review or []) else ""))
            out.append(u"")
        if self.review:
            out.append(u"These sheets have sections below their bottom edge and "
                       u"need a look by hand:")
            for number in self.review:
                out.append(u"    {0}".format(number))
            out.append(u"")
        out.append(u"{0} views created on {1} sheet(s)".format(self.views, len(self.sheets)))
        if self.failures:
            out.append(u"")
            out.append(u"Not done")
            for line in self.failures:
                out.append(u"    {0}".format(line))
        if self.warnings:
            out.append(u"")
            out.append(u"Worth a look")
            for line in self.warnings:
                out.append(u"    {0}".format(line))
        if self.notes:
            out.append(u"")
            out.append(u"Notes")
            for line in self.notes:
                out.append(u"    {0}".format(line))
        seen = suppressed_dialogs()
        if seen:
            out.append(u"")
            out.append(u"Revit dialogs answered during the run: {0}".format(u", ".join(seen)))
        return out


# ---------------------------------------------------------------------------
# the run
# ---------------------------------------------------------------------------


def run(doc, groups, settings, progress=None):
    """Create everything the plan describes.

    `progress` is called as (done, total, message) **between** transactions and
    never inside one.  Letting Revit's message loop run between Start and
    Commit so a bar can move is a way to commit nothing at all, so the finest
    the bar can honestly go is one step per sheet.
    """
    results = Results()

    total = len(groups)

    def say(done, message):
        if progress is None:
            return
        try:
            progress(done, total, message)
        except Exception:
            core.log("progress report failed")
    ctx = {
        "settings": settings,
        "results": results,
        # the direction convention that worked last time.  It used to start
        # at -1 every run, and on this model the first section came out
        # backwards every time - built, read back, deleted and built again.
        # Remembering the answer makes that a one-off.
        "section_sign": 1.0 if core.get_float(settings, "sec_sign", -1.0) > 0 else -1.0,
        "section_checked": False,
        "titleblocks": core.get_map(settings, "sheet_titleblocks"),
    }

    ctx["vft_3d"] = model.pick_view_family_type(
        doc, "ThreeDimensional", settings.get("3d_view_family_type", ""))
    ctx["vft_section"] = model.pick_view_family_type(
        doc, "Section", settings.get("sec_view_family_type", ""))

    template_3d = model.template_by_name(doc, settings.get("3d_template", ""), "3d")
    ctx["template_3d"] = template_3d.Id if template_3d is not None else \
        model.default_template_id(doc, "ThreeDimensional", ctx["vft_3d"])
    template_section = model.template_by_name(doc, settings.get("sec_template", ""), "section")
    ctx["template_section"] = template_section.Id if template_section is not None else \
        model.default_template_id(doc, "Section", ctx["vft_section"])

    ctx["vp_callout"] = model.viewport_type_by_name(doc, settings.get("vp_type_callout", ""))
    ctx["vp_3d"] = model.viewport_type_by_name(doc, settings.get("vp_type_3d", ""))
    ctx["vp_section"] = model.viewport_type_by_name(doc, settings.get("vp_type_section", ""))

    swallower = WarningSwallower()
    dialogs(True)

    group_transaction = TransactionGroup(doc, "RevoBIM Callout to 3D")
    try:
        group_transaction.Start()
    except Exception as err:
        results.fail(u"could not start the transaction group - {0}".format(err))
        dialogs(False)
        return results

    try:
        for index, entry in enumerate(groups):
            say(index, u"sheet {0} of {1} - {2}".format(
                index + 1, total, entry["sheet_number"]))
            transaction = Transaction(doc, u"Callout to 3D - {0}".format(entry["sheet_number"]))
            try:
                transaction.Start()
                options = transaction.GetFailureHandlingOptions()
                options.SetFailuresPreprocessor(swallower)
                options.SetClearAfterRollback(True)
                transaction.SetFailureHandlingOptions(options)
            except Exception as err:
                results.fail(u"{0}: transaction refused - {1}".format(entry["sheet_number"], err))
                continue

            made = None
            try:
                made = _make_group(doc, ctx, entry)
                status = transaction.Commit()
                if status != TransactionStatus.Committed:
                    results.fail(u"{0}: Revit did not commit ({1})"
                                 .format(entry["sheet_number"], status))
                    made = None
            except Exception as err:
                core.log(traceback.format_exc())
                try:
                    transaction.RollBack()
                except Exception:
                    pass
                results.fail(u"{0}: rolled back - {1}".format(entry["sheet_number"], err))
                made = None

            # THE VIEWPORTS GO IN A SECOND TRANSACTION.
            #
            # A view created earlier in the same transaction is not one Revit
            # will hand to Viewport.Create: it returns null, without raising
            # and without a reason, and the view is quietly missing from the
            # sheet.  A regenerate is not enough - it took a commit.  The two
            # transactions sit inside the same TransactionGroup, so undo still
            # sees one step.
            if made is not None:
                placing = Transaction(
                    doc, u"Callout to 3D - place {0}".format(entry["sheet_number"]))
                try:
                    placing.Start()
                    options = placing.GetFailureHandlingOptions()
                    options.SetFailuresPreprocessor(swallower)
                    options.SetClearAfterRollback(True)
                    placing.SetFailureHandlingOptions(options)
                    tag_rooms(doc, ctx, made)
                    crop_grids(doc, ctx, made)
                    _place_group(doc, ctx, entry, made, results.review)
                    status = placing.Commit()
                    if status != TransactionStatus.Committed:
                        results.fail(u"{0}: the viewports did not commit ({1})"
                                     .format(entry["sheet_number"], status))
                except Exception as err:
                    core.log(traceback.format_exc())
                    try:
                        placing.RollBack()
                    except Exception:
                        pass
                    results.fail(u"{0}: the viewports rolled back - {1}"
                                 .format(entry["sheet_number"], err))

            say(index + 1, u"{0} of {1} done".format(index + 1, total))
        group_transaction.Assimilate()
    except Exception as err:
        core.log(traceback.format_exc())
        try:
            group_transaction.RollBack()
        except Exception:
            pass
        results.fail(u"the run stopped - {0}".format(err))
    finally:
        dialogs(False)

    if swallower.deleted:
        results.note(u"{0} Revit warning(s) cleared during the run".format(swallower.deleted))
    results.learned_sign = ctx.get("section_sign")
    return results


def _make_group(doc, ctx, entry):
    """Everything that is created: the renames, the views and the sheet.

    Returns the views that were actually made, for the placing pass to put on
    the sheet once this has been committed.
    """
    results = ctx["results"]

    for row, new_name in entry["renames"]:
        rename_callout(doc, ctx, row, new_name)

    made = []
    for item in entry["views"]:
        if item["kind"] == "3d":
            view = make_3d(doc, ctx, item["row"], item["name"])
        else:
            view = make_section(doc, ctx, item["row"], item["name"], item["spec"])
        item["view"] = view
        if view is not None:
            # the id, not the handle: what crosses the commit between making
            # and placing has to be something that can be looked up again
            item["view_id"] = view.Id
            made.append(item)
            results.views += 1
    doc.Regenerate()

    sheet = make_sheet(doc, ctx, entry)
    if sheet is None:
        return None
    entry["sheet"] = sheet
    entry["sheet_id"] = sheet.Id
    return made








# ---------------------------------------------------------------------------
# the external event
# ---------------------------------------------------------------------------


class RunHandler(IExternalEventHandler):
    """A modeless window cannot start a transaction, so every write leaves
    through here."""

    def __init__(self):
        self.groups = []
        self.settings = {}
        self.on_done = None
        self.on_progress = None
        self.job = "run"

    def Execute(self, uiapp):
        try:
            doc = uiapp.ActiveUIDocument.Document
            hook_dialogs(uiapp)
            results = run(doc, self.groups, self.settings, self.on_progress)
        except Exception as err:
            core.log(traceback.format_exc())
            results = Results()
            results.fail(u"{0}".format(err))
        try:
            if self.on_done:
                self.on_done(results)
        except Exception:
            core.log(traceback.format_exc())

    def GetName(self):
        return "RevoBIM Callout to 3D"


class OpenViewHandler(IExternalEventHandler):
    """Opening a view is a UI action, so it goes out the same way.

    One view uses `RequestViewChange`, which is what Revit itself does.  For
    several, `RequestViewChange` is no good: it is documented as taking effect
    once the API context returns, so calling it in a loop opens the last one
    only.  Setting `ActiveView` takes effect immediately, so each sheet in turn
    really is opened and the last one is left in front.
    """

    def __init__(self):
        self.view_id = None
        self.view_ids = []

    def Execute(self, uiapp):
        try:
            uidoc = uiapp.ActiveUIDocument
            if uidoc is None:
                return
            doc = uidoc.Document

            wanted = list(self.view_ids or [])
            if not wanted and self.view_id is not None:
                wanted = [self.view_id]
            self.view_ids = []
            self.view_id = None
            if not wanted:
                return

            if len(wanted) == 1:
                view = doc.GetElement(wanted[0])
                if view is not None:
                    uidoc.RequestViewChange(view)
                return

            opened = 0
            last = None
            for view_id in wanted:
                view = doc.GetElement(view_id)
                if view is None:
                    continue
                try:
                    uidoc.ActiveView = view
                    opened += 1
                    last = view
                except Exception as err:
                    core.log(u"could not open {0}: {1}".format(
                        model._name_of(view), err))
            if opened == 0 and wanted:
                view = doc.GetElement(wanted[-1])
                if view is not None:
                    uidoc.RequestViewChange(view)
            elif last is not None:
                core.log(u"opened {0} of {1} sheet(s)".format(opened, len(wanted)))
        except Exception:
            core.log(traceback.format_exc())

    def GetName(self):
        return "RevoBIM Callout to 3D - open view"
