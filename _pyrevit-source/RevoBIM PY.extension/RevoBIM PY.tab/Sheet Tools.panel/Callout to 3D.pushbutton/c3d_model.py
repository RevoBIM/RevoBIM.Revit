# -*- coding: utf-8 -*-
"""Callout to 3D - everything read out of the model.

Read in one pass and cache: the callout table is rebuilt on every refresh and
a per-view collector at 400 sheets is the difference between instant and
unusable.
"""

import c3d_clr  # noqa: F401  assemblies first, always

import time

import c3d_core as core
import c3d_geom as geom

from Autodesk.Revit.DB import (                      # noqa: E402
    FilteredElementCollector, View, ViewPlan, ViewSection, ViewSheet,
    Viewport, ElementType, FamilySymbol, Level, ViewFamilyType, ViewFamily,
    ElementId, BuiltInParameter, StorageType, ElementTypeGroup,
)


def _bic(name):
    """BuiltInCategory members are looked up late, inside a function, never at
    module load - one less thing that can die before the tool runs."""
    from Autodesk.Revit.DB import BuiltInCategory
    return getattr(BuiltInCategory, name)


def _name_of(element):
    if element is None:
        return ""
    for route in ("Name",):
        try:
            value = getattr(element, route)
            if value:
                return u"{0}".format(value)
        except Exception:
            pass
    try:
        param = element.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
        if param is not None:
            return param.AsString() or ""
    except Exception:
        pass
    return ""


# ---------------------------------------------------------------------------
# levels
# ---------------------------------------------------------------------------


def levels(doc, source="Elevation"):
    found = []
    try:
        for level in FilteredElementCollector(doc).OfClass(Level).WhereElementIsNotElementType():
            z = geom.level_model_z(level, source)
            if z is None:
                continue
            found.append({"level": level, "id": level.Id, "name": _name_of(level),
                          "z_ft": z, "z_mm": core.ft_to_mm(z)})
    except Exception as err:
        core.log("level read failed: {0}".format(err))
    found.sort(key=lambda item: item["z_mm"])
    return found


def next_level_above(level_list, z_mm, tolerance=1.0):
    for item in level_list:
        if item["z_mm"] > float(z_mm) + tolerance:
            return item
    return None


def nearest_level(level_list, z_mm):
    best = None
    for item in level_list:
        gap = abs(item["z_mm"] - float(z_mm))
        if best is None or gap < best[0]:
            best = (gap, item)
    return best[1] if best else None


# ---------------------------------------------------------------------------
# callouts
# ---------------------------------------------------------------------------


def is_callout_kind(view):
    """Only a plan or a detail view can be a callout - a section or an
    elevation has a marker as well, and is neither."""
    try:
        if view is None or view.IsTemplate:
            return False
    except Exception:
        return False
    if isinstance(view, ViewPlan):
        return True
    try:
        return u"{0}".format(view.ViewType) == "Detail"
    except Exception:
        return False


def _callout_of_viewer(doc, viewer, by_name):
    """The callout view a Viewer marker stands for, or None when it is the
    marker of a section, an elevation or anything else.

    Matched by the name the marker carries - its own, or its View Name - and
    by the element Revit keeps next to it, which is the view itself."""
    names = []
    try:
        own = _name_of(viewer)
        if own:
            names.append(own.strip().lower())
    except Exception:
        pass
    try:
        param = viewer.get_Parameter(BuiltInParameter.VIEW_NAME)
        text = (param.AsString() or "").strip().lower() if param is not None else ""
        if text and text not in names:
            names.append(text)
    except Exception:
        pass
    for name in names:
        view = by_name.get(name)
        if is_callout_kind(view):
            return view
    for step in (1, -1):
        try:
            near = doc.GetElement(ElementId(core.eid_value(viewer.Id) + step))
        except Exception:
            near = None
        if isinstance(near, View) and is_callout_kind(near) and \
                _name_of(near).strip().lower() in names:
            return near
    return None


def _view_from_marker(doc, marker, by_name):
    """A callout marker does not hand its view over directly, so it is asked
    three ways: an ElementId parameter pointing at a view, the View Name
    parameter, then the marker's own name."""
    try:
        for param in marker.Parameters:
            try:
                if param.StorageType != StorageType.ElementId:
                    continue
                target = doc.GetElement(param.AsElementId())
                if isinstance(target, View):
                    return target
            except Exception:
                continue
    except Exception:
        pass
    for builtin in ("VIEW_NAME", "VIEWER_VIEW_NAME", "VIEWPORT_VIEW_NAME"):
        try:
            enum = getattr(BuiltInParameter, builtin, None)
            if enum is None:
                continue
            param = marker.get_Parameter(enum)
            if param is None:
                continue
            text = (param.AsString() or "").strip().lower()
            if text and text in by_name:
                return by_name[text]
        except Exception:
            continue
    try:
        text = _name_of(marker).strip().lower()
        if text and text in by_name:
            return by_name[text]
    except Exception:
        pass
    return None


def view_type_name(doc, view, cache=None):
    """The name of a view's own ViewFamilyType, cached by type id - the same
    handful of types answer for every view in the project."""
    try:
        type_id = view.GetTypeId()
    except Exception:
        return ""
    key = core.eid_value(type_id)
    if cache is not None and key in cache:
        return cache[key]
    name = ""
    try:
        element = doc.GetElement(type_id)
        if element is not None:
            name = _name_of(element)
    except Exception:
        name = ""
    if cache is not None:
        cache[key] = name
    return name


def view_type_tally(doc):
    """Every view family type name actually in use, with how many views carry
    it - what to read out when nothing matched, so the token can be set from
    the model rather than guessed."""
    cache = {}
    tally = {}
    try:
        for view in FilteredElementCollector(doc).OfClass(View):
            try:
                if view.IsTemplate:
                    continue
            except Exception:
                continue
            name = view_type_name(doc, view, cache)
            if not name:
                continue
            tally[name] = tally.get(name, 0) + 1
    except Exception as err:
        core.log("view type tally failed: {0}".format(err))
    return sorted(tally.items(), key=lambda pair: (-pair[1], pair[0].lower()))


def _tokens(settings, key, fallback):
    raw = (settings or {}).get(key, fallback)
    return [piece.strip().lower() for piece in u"{0}".format(raw or "").split(",")
            if piece.strip()]


SCAN_CLASSES = {
    "plans": ("ViewPlan",),
    "plans_sections": ("ViewPlan", "ViewSection"),
    "every": ("View",),
}


def scan_views(doc, settings=None):
    """The views worth looking at, collected once.

    A callout of a plan is a `ViewPlan` and a detail callout is a
    `ViewSection`, so asking only those two classes is not a shortcut - it is
    the right question, and `OfClass` does the filtering in native code rather
    than a property read per view. Asking every view in the project what
    callouts it carries, one call at a time, is what made the tool slow to
    open on a real model.

    The list is built once and handed to every route, so a project is walked
    once rather than three times.
    """
    settings = settings or {}
    mode = str(settings.get("scan_scope", "plans")).strip().lower()
    names = SCAN_CLASSES.get(mode, SCAN_CLASSES["plans"])
    views = []
    seen = set()
    for name in names:
        cls = {"ViewPlan": ViewPlan, "ViewSection": ViewSection, "View": View}.get(name)
        if cls is None:
            continue
        try:
            for view in FilteredElementCollector(doc).OfClass(cls):
                try:
                    if view.IsTemplate:
                        continue
                except Exception:
                    continue
                key = core.eid_value(view.Id)
                if key in seen:
                    continue
                seen.add(key)
                views.append(view)
        except Exception as err:
            core.log("scan of {0} failed: {1}".format(name, err))
    return views


def find_callout_views(doc, settings=None, include_cropped=False, views=None):
    """Every callout view in the project, with the view it was cut in.

    There is no single API call that answers this, so three routes are tried
    and their answers merged; which one found a view is reported, because on
    a model where none of them fire the tool has to say so rather than show
    an empty table.
    """
    settings = settings or {}
    if views is None:
        views = scan_views(doc, settings)
    found = {}
    routes = {"viewer": 0, "reference": 0, "marker": 0, "type": 0, "cropped": 0, "ms": {}}
    type_cache = {}

    def clock():
        try:
            return time.time()
        except Exception:
            return 0.0

    # the name map is only wanted by the marker route, and building it means
    # reading a name off every view, so it is built on demand rather than
    # every time the tool opens
    name_map = {"table": None}

    def by_name_table():
        if name_map["table"] is None:
            name_map["table"] = dict(
                [(_name_of(view).strip().lower(), view) for view in views])
        return name_map["table"]

    # ROUTE ORDER IS A SPEED DECISION.
    #
    # The marker route is a quick filter over one category and costs one pass
    # over the callouts themselves - tens of elements, not thousands.  The type
    # route is one cached type read per view.  Asking every view what callouts
    # it carries is an API call per view, and on a real model that is the whole
    # of the wait to open the tool.  So the two cheap routes run first, and the
    # expensive one only runs when they have come back with nothing - it cannot
    # find a callout they both missed unless the naming is unusual.

    # route 0 - the view markers.  A callout is drawn in its parent view as a
    # Viewer element carrying the callout view's name; a section or an
    # elevation has one too, but its view is a section, so a PLAN (or a detail
    # view) that has a marker somewhere is a callout and nothing else is.  On
    # this kind of model it is the one route that answers on its own: the
    # OST_Callouts category is empty and GetReferenceCallouts says nothing.
    if core.get_bool(settings, "route_viewer", True):
        started = clock()
        routes.setdefault("viewer", 0)
        try:
            viewers = FilteredElementCollector(doc)\
                .OfCategory(_bic("OST_Viewers")).WhereElementIsNotElementType()
            table = by_name_table()
            for viewer in viewers:
                child = _callout_of_viewer(doc, viewer, table)
                if child is None:
                    continue
                key = core.eid_value(child.Id)
                if key in found:
                    continue
                parent = None
                try:
                    parent = doc.GetElement(viewer.OwnerViewId)
                except Exception:
                    parent = None
                found[key] = {"view": child, "parent": parent, "route": "viewer"}
                routes["viewer"] += 1
        except Exception as err:
            core.log("callout viewer route failed: {0}".format(err))
        routes["ms"]["viewer"] = (clock() - started) * 1000.0

    # route 2 - the callout marker elements themselves
    if core.get_bool(settings, "route_marker", True):
        started = clock()
        try:
            markers = FilteredElementCollector(doc)\
                .OfCategory(_bic("OST_Callouts")).WhereElementIsNotElementType()
            for marker in markers:
                child = _view_from_marker(doc, marker, by_name_table())
                if child is None:
                    continue
                key = core.eid_value(child.Id)
                if key in found:
                    continue
                parent = None
                try:
                    parent = doc.GetElement(marker.OwnerViewId)
                except Exception:
                    parent = None
                found[key] = {"view": child, "parent": parent, "route": "marker"}
                routes["marker"] += 1
        except Exception as err:
            core.log("callout marker route failed: {0}".format(err))
        routes["ms"]["marker"] = (clock() - started) * 1000.0

    # route 3 - the view's own family type name.  A model whose callouts are
    # cut with a named view family type ("BGL_Callout", "Detail Callout") is
    # answered by the name alone, which is the only route that works when the
    # reference and marker calls come back empty.
    tokens = _tokens(settings, "type_contains", "Callout")
    if tokens and core.get_bool(settings, "route_type", True):
        started = clock()
        try:
            for view in views:
                try:
                    if isinstance(view, ViewSheet):
                        continue
                except Exception:
                    continue
                name = view_type_name(doc, view, type_cache).lower()
                if not name:
                    continue
                if not [token for token in tokens if token in name]:
                    continue
                key = core.eid_value(view.Id)
                if key in found:
                    continue
                found[key] = {"view": view, "parent": None, "route": "type"}
                routes["type"] += 1
        except Exception as err:
            core.log("callout type route failed: {0}".format(err))
        routes["ms"]["type"] = (clock() - started) * 1000.0

    # route 1 - ask every view what callouts it carries.  The slow one, so it
    # is skipped when the cheap routes have already answered, unless it has
    # been asked for outright.
    wanted = core.get_bool(settings, "route_reference", True)
    if wanted and found and not core.get_bool(settings, "route_reference_always", False):
        routes["ms"]["reference"] = -1.0        # skipped, and said so
        wanted = False
    if wanted:
        started = clock()
        try:
            for view in views:
                try:
                    ids = view.GetReferenceCallouts()
                except Exception:
                    continue
                for cid in (ids or []):
                    try:
                        element = doc.GetElement(cid)
                    except Exception:
                        continue
                    child = (element if isinstance(element, View)
                             else _view_from_marker(doc, element, by_name_table()))
                    if child is None or child.Id == view.Id:
                        continue
                    key = core.eid_value(child.Id)
                    if key not in found:
                        found[key] = {"view": child, "parent": view, "route": "reference"}
                        routes["reference"] += 1
        except Exception as err:
            core.log("callout reference route failed: {0}".format(err))
        routes["ms"]["reference"] = (clock() - started) * 1000.0

    # route 4 - last resort, and only when it is asked for.  Routes 1 and 2
    # are callout-only by construction; this one is not, so it never runs on
    # its own - an empty table is the honest answer to a model whose callouts
    # cannot be read, and a table full of every cropped view is not.
    if include_cropped:
        try:
            for view in views:
                try:
                    if not isinstance(view, (ViewPlan, ViewSection)):
                        continue
                    if not view.CropBoxActive:
                        continue
                except Exception:
                    continue
                key = core.eid_value(view.Id)
                if key in found:
                    continue
                found[key] = {"view": view, "parent": None, "route": "cropped",
                              "unconfirmed": True}
                routes["cropped"] += 1
        except Exception as err:
            core.log("callout cropped route failed: {0}".format(err))

    core.log(u"callout scan: {0} view(s) looked at, {1}".format(
        len(views),
        u", ".join([u"{0} {1:.0f}ms".format(key, value)
                    for key, value in sorted(routes["ms"].items()) if value >= 0])))
    return list(found.values()), routes


def sheets_by_view(doc):
    table = {}
    try:
        for viewport in FilteredElementCollector(doc).OfClass(Viewport):
            try:
                sheet = doc.GetElement(viewport.SheetId)
                table[core.eid_value(viewport.ViewId)] = sheet
            except Exception:
                continue
    except Exception:
        pass
    return table


def elevation_source(doc, candidates, frames=None):
    """Which level property is the model's internal Z: 'Elevation' or
    'ProjectElevation'.

    It is worked out from the model rather than assumed, because it is not the
    same on every job and getting it wrong is not a small error.  A plan view's
    crop plane sits at its view range cut plane, and the crop region's Z is a
    model coordinate with nothing between it and the truth - so

        the level's internal Z  =  the crop plane's Z  -  the cut plane offset

    and whichever property that lands on is the internal one.  Several callouts
    are asked and the answer they mostly agree on wins, so one odd view cannot
    decide it.

    On a job whose elevation base is the survey point, `Elevation` comes back as
    the shared elevation - 88 metres out on the model this was found on, which
    put every section and every 3D box that far above the building.
    """
    votes = {"Elevation": 0, "ProjectElevation": 0}
    evidence = []
    for item in candidates[:8]:
        view = item.get("view") if isinstance(item, dict) else item
        try:
            level = view.GenLevel
        except Exception:
            level = None
        if level is None:
            continue
        frame = geom.crop_frame(view, frames)
        offset = geom.cut_plane_offset_mm(view)
        if not frame or offset is None:
            continue
        wanted = frame.get("z", 0.0) - offset
        best, gap = None, None
        for name in ("Elevation", "ProjectElevation"):
            try:
                value = core.ft_to_mm(float(getattr(level, name)))
            except Exception:
                continue
            distance = abs(value - wanted)
            if gap is None or distance < gap:
                best, gap = name, distance
        if best is None or gap is None or gap > 500.0:
            continue                      # neither fits, so it says nothing
        votes[best] += 1
        evidence.append((_name_of(view), wanted, best, gap))

    chosen = "Elevation"
    if votes["ProjectElevation"] > votes["Elevation"]:
        chosen = "ProjectElevation"
    if evidence:
        core.log(u"level elevations read from {0} ({1} vote(s) for Elevation, "
                 u"{2} for ProjectElevation); first: {3} wants {4:.1f}mm and "
                 u"{5} is {6:.1f}mm away".format(
                     chosen, votes["Elevation"], votes["ProjectElevation"],
                     evidence[0][0], evidence[0][1], evidence[0][2], evidence[0][3]))
    else:
        core.log("no callout could say which level elevation is the internal "
                 "one, so Elevation is used")
    return chosen, votes, evidence


def callout_rows(doc, settings, include_cropped=False, progress=None):
    """One row per callout, with everything the table and the run need.

    `progress` is called as (done, total, message) as the read goes along.  It
    is only a read, so there is no transaction to keep the message loop out
    of, and the scan is the slow part of opening the tool.
    """
    def say(done, total, message):
        if progress is None:
            return
        try:
            progress(done, total, message)
        except Exception:
            pass

    say(1, 5, "reading the sheets")
    on_sheet = sheets_by_view(doc)
    say(2, 5, "looking through the views")
    views = scan_views(doc, settings)
    say(3, 5, u"looking for callouts in {0} view(s)".format(len(views)))
    raw, routes = find_callout_views(doc, settings, include_cropped, views)
    say(4, 5, u"reading {0} callout(s)".format(len(raw)))

    # which level property is the internal one has to be settled before any
    # elevation is read, because everything else is measured from it
    frames = {}                       # one crop read per callout per refresh
    source, votes, evidence = elevation_source(doc, raw, frames)
    routes["elevation_source"] = source
    routes["elevation_votes"] = votes
    level_list = levels(doc, source)
    rows = []

    lost = 0
    for item in raw:
        try:
            view = item["view"]
            parent = item["parent"]
            frame = geom.crop_frame(view, frames)
            level = None
            try:
                level = view.GenLevel
            except Exception:
                level = None
            if level is None and parent is not None:
                try:
                    level = parent.GenLevel
                except Exception:
                    level = None
            if level is None and frame is not None:
                near = nearest_level(level_list, frame.get("z", 0.0))
                level = near["level"] if near else None

            level_name = _name_of(level) if level is not None else ""
            level_z = geom.level_model_z(level, source) if level is not None else None
            level_mm = core.ft_to_mm(level_z) if level_z is not None else 0.0
            above = next_level_above(level_list, level_mm) if level is not None else None

            try:
                scale = view.Scale
            except Exception:
                scale = 0

            size_mm = (0.0, 0.0)
            if frame:
                size_mm = (frame["half_x"] * 2.0, frame["half_y"] * 2.0)

            sheet = on_sheet.get(core.eid_value(view.Id))
            rows.append({
                "view": view,
                "id": view.Id,
                "key": core.eid_value(view.Id),
                "name": _name_of(view),
                "parent_name": _name_of(parent) if parent is not None else "",
                "level": level,
                "level_name": level_name,
                "level_mm": level_mm,
                "next_level_mm": above["z_mm"] if above else None,
                "scale": scale,
                "frame": frame,
                "size_mm": size_mm,
                "sheet": sheet,
                "sheet_text": (_name_of(sheet) if sheet is not None else ""),
                "sheet_number": (sheet.SheetNumber if sheet is not None else ""),
                "route": item["route"],
                "checked": False,
                "x_count": core.get_int(settings, "sec_x_count", 1),
                "y_count": core.get_int(settings, "sec_y_count", 1),
                "depth_mm": core.get_float(settings, "sec_depth_mm", 500.0),
                "group": _name_of(view),
                "size": settings.get("sheet_size_default", "A1"),
                "flip_x": core.get_bool(settings, "sec_flip_x"),
                "flips": {},          # per section overrides, keyed X1, Y2 ...
                "range_mm": geom.view_range_mm(doc, view, source),
                "flip_y": core.get_bool(settings, "sec_flip_y"),
                "is_callout": not item.get("unconfirmed"),
                "status": ("a plan, not a callout" if item.get("unconfirmed") else ""),
                "note": "",
            })

        except Exception as err:
            # one row that will not build must not cost the whole table - that
            # is what a missing key in the callout frame did in 1.5.0, and the
            # table came up empty with nothing said
            lost += 1
            core.log(u"row skipped: {0}".format(err))

    say(5, 5, u"{0} callout(s)".format(len(rows)))
    if lost:
        routes["lost"] = lost
        core.log(u"{0} callout(s) could not be read into a row".format(lost))

    rows.sort(key=lambda row: (row["level_mm"], row["name"].lower()))
    return rows, routes


# ---------------------------------------------------------------------------
# view templates, families and types
# ---------------------------------------------------------------------------

_TEMPLATE_KINDS = {
    "3d": ("ThreeD", "ThreeDimensional"),
    # a template made for a detail view or an elevation applies perfectly well
    # to a section, and plenty of house templates are filed under one of those,
    # so all three count as "a section template"
    "section": ("Section", "Detail", "Elevation"),
}


def matches_kind(view_type, kind):
    """Whether a view type name belongs to one of the tool's kinds."""
    if not kind:
        return True
    wanted = _TEMPLATE_KINDS.get(kind, ())
    text = u"{0}".format(view_type or "").lower()
    return bool([w for w in wanted if w.lower() in text])


def default_template_name(doc, family_type_name, kind):
    """The name of the view template a view family type applies by default, so
    picking a type can offer its own template rather than leaving the box on
    whatever was there before."""
    if not family_type_name:
        return ""
    for item in view_family_types(doc, "ThreeDimensional" if kind == "3d" else "Section"):
        if item["name"].strip().lower() != family_type_name.strip().lower():
            continue
        try:
            template_id = item["type"].DefaultTemplateId
        except Exception:
            return ""
        if template_id is None or core.eid_value(template_id) <= 0:
            return ""
        template = doc.GetElement(template_id)
        return _name_of(template) if template is not None else ""
    return ""


def view_templates(doc, kind=None, cache=None):
    """Every view template, optionally only those of one view type.

    A cache dict can be handed in so a caller wanting two kinds walks the
    project once rather than twice - which is what the settings window does.
    """
    if cache is not None:
        if "all" not in cache:
            cache["all"] = view_templates(doc, None)
        return [item for item in cache["all"] if matches_kind(item["type"], kind)]
    out = []
    try:
        for view in FilteredElementCollector(doc).OfClass(View):
            try:
                if not view.IsTemplate:
                    continue
            except Exception:
                continue
            try:
                view_type = u"{0}".format(view.ViewType)
            except Exception:
                view_type = ""
            if not matches_kind(view_type, kind):
                continue
            out.append({"view": view, "id": view.Id, "name": _name_of(view),
                        "type": view_type})
    except Exception as err:
        core.log("template read failed: {0}".format(err))
    out.sort(key=lambda item: item["name"].lower())
    return out


def room_tag_types(doc):
    """Every room tag type loaded, as 'Family : Type'."""
    out = []
    try:
        collector = FilteredElementCollector(doc).OfCategory(_bic("OST_RoomTags"))\
            .WhereElementIsElementType()
        for symbol in collector:
            family = u""
            try:
                family = symbol.FamilyName or u""
            except Exception:
                pass
            name = u"{0} : {1}".format(family, _name_of(symbol)) if family else _name_of(symbol)
            out.append({"type": symbol, "id": symbol.Id, "name": name})
    except Exception as err:
        core.log(u"room tag types could not be read: {0}".format(err))
    out.sort(key=lambda item: item["name"].lower())
    return out


def room_tag_type_id(doc, wanted=""):
    """The room tag to use: the one named, else the project's default room
    tag, else the first one loaded - or None when there is none at all."""
    options = room_tag_types(doc)
    if wanted:
        for option in options:
            if option["name"].strip().lower() == wanted.strip().lower():
                return option["id"]
    try:
        from Autodesk.Revit.DB import ElementId
        found = doc.GetDefaultFamilyTypeId(ElementId(_bic("OST_RoomTags")))
        if found is not None and core.eid_value(found) > 0:
            return found
    except Exception:
        pass
    return options[0]["id"] if options else None


def placed_rooms(doc):
    """Every room that is placed and bounded - an unplaced or redundant room
    has no area and nothing a tag could sit in."""
    out = []
    try:
        collector = FilteredElementCollector(doc).OfCategory(_bic("OST_Rooms"))\
            .WhereElementIsNotElementType()
        for room in collector:
            try:
                if room.Location is None or float(room.Area) <= 0.0:
                    continue
            except Exception:
                continue
            out.append(room)
    except Exception as err:
        core.log(u"rooms could not be read: {0}".format(err))
    return out


def tagged_room_keys(doc, view):
    """The rooms that already carry a tag in this view."""
    keys = set()
    try:
        collector = FilteredElementCollector(doc, view.Id).OfCategory(_bic("OST_RoomTags"))\
            .WhereElementIsNotElementType()
        for tag in collector:
            try:
                room = tag.Room
                if room is not None:
                    keys.add(core.eid_value(room.Id))
                    continue
            except Exception:
                pass
            try:
                keys.add(core.eid_value(tag.TaggedLocalRoomId))
            except Exception:
                pass
    except Exception as err:
        core.log(u"room tags in {0} could not be read: {1}".format(_name_of(view), err))
    return keys


def view_family_types(doc, family_name):
    """family_name is 'ThreeDimensional' or 'Section'."""
    out = []
    try:
        family = getattr(ViewFamily, family_name, None)
        for vft in FilteredElementCollector(doc).OfClass(ViewFamilyType):
            try:
                if family is not None and vft.ViewFamily != family:
                    continue
            except Exception:
                continue
            out.append({"type": vft, "id": vft.Id, "name": _name_of(vft)})
    except Exception as err:
        core.log("view family type read failed: {0}".format(err))
    out.sort(key=lambda item: item["name"].lower())
    return out


def pick_view_family_type(doc, family_name, wanted_name=""):
    options = view_family_types(doc, family_name)
    if not options:
        return None
    if wanted_name:
        for option in options:
            if option["name"].strip().lower() == wanted_name.strip().lower():
                return option["type"]
    return options[0]["type"]


def default_template_id(doc, family_name, vft=None):
    """The template a new view of this family gets by default: the view family
    type's own DefaultTemplateId, which is what Revit itself applies."""
    try:
        target = vft or pick_view_family_type(doc, family_name)
        if target is None:
            return ElementId.InvalidElementId
        tid = target.DefaultTemplateId
        if tid is not None and core.eid_value(tid) > 0:
            return tid
    except Exception:
        pass
    return ElementId.InvalidElementId


def template_by_name(doc, name, kind=None):
    if not name:
        return None
    for item in view_templates(doc, kind):
        if item["name"].strip().lower() == name.strip().lower():
            return item["view"]
    return None


def viewport_types(doc):
    """Every viewport type in the project.

    Three routes merged, because the obvious one comes back empty on plenty of
    models: a viewport type's Category is not reliably OST_Viewports, and a
    type nothing has been placed with may not be reachable by category at all.
    """
    out = {}

    def add(element):
        try:
            key = core.eid_value(element.Id)
        except Exception:
            return
        if key in out:
            return
        out[key] = {"type": element, "id": element.Id, "name": _name_of(element)}

    # route 1 - by category
    try:
        collector = FilteredElementCollector(doc)\
            .OfCategory(_bic("OST_Viewports")).WhereElementIsElementType()
        for element in collector:
            add(element)
    except Exception as err:
        core.log("viewport type route 1 failed: {0}".format(err))

    # route 2 - every ElementType whose family name is Viewport
    try:
        for element in FilteredElementCollector(doc).OfClass(ElementType):
            try:
                family = element.FamilyName
            except Exception:
                continue
            if family and str(family).strip().lower() in ("viewport", "viewports"):
                add(element)
    except Exception as err:
        core.log("viewport type route 2 failed: {0}".format(err))

    # route 3 - the types of the viewports actually placed, plus the project
    # default, so a model with exactly one in use still offers it
    try:
        for viewport in FilteredElementCollector(doc).OfClass(Viewport):
            try:
                element = doc.GetElement(viewport.GetTypeId())
            except Exception:
                element = None
            if element is not None:
                add(element)
    except Exception as err:
        core.log("viewport type route 3 failed: {0}".format(err))
    try:
        default = doc.GetDefaultElementTypeId(
            getattr(ElementTypeGroup, "ViewportType"))
        element = doc.GetElement(default) if default is not None else None
        if element is not None:
            add(element)
    except Exception:
        pass

    values = list(out.values())
    values.sort(key=lambda item: item["name"].lower())
    return values


def viewport_type_by_name(doc, name):
    if not name:
        return None
    for item in viewport_types(doc):
        if item["name"].strip().lower() == name.strip().lower():
            return item["type"]
    return None


def selection_targets(uidoc):
    """What was selected in Revit when the tool opened, as the views it
    points at: {"keys": view ids, "names": lower case names, "count": n}.

    - a view picked in the project browser is the view itself;
    - a callout marker picked in a plan is a Viewer element, not the view -
      it carries the view's name, so it is matched by name;
    - a viewport is the view it shows;
    - a sheet is every view placed on it.
    """
    out = {"keys": set(), "names": set(), "count": 0}
    try:
        doc = uidoc.Document
        ids = list(uidoc.Selection.GetElementIds())
    except Exception:
        return out
    out["count"] = len(ids)

    def add_view(view):
        if view is None:
            return
        try:
            out["keys"].add(core.eid_value(view.Id))
        except Exception:
            pass
        name = _name_of(view)
        if name:
            out["names"].add(name.strip().lower())

    for element_id in ids:
        try:
            element = doc.GetElement(element_id)
        except Exception:
            element = None
        if element is None:
            continue
        if isinstance(element, ViewSheet):
            try:
                for placed in element.GetAllPlacedViews():
                    add_view(doc.GetElement(placed))
            except Exception:
                pass
            continue
        if isinstance(element, View):
            add_view(element)
            continue
        try:
            view_id = element.ViewId            # a viewport
            if view_id is not None and core.eid_value(view_id) > 0:
                add_view(doc.GetElement(view_id))
                continue
        except Exception:
            pass
        # anything else - a callout marker picked in a view above all - is
        # matched by the name it carries.  The marker is a Viewer element
        # rather than the view, and asking for that category by id is not
        # something every build answers, so no category test is relied on;
        # a name that is not a callout simply matches nothing.
        for name in _names_on(element):
            out["names"].add(name.strip().lower())
        # and the view itself where Revit keeps it next to its marker
        for step in (1, -1):
            try:
                from Autodesk.Revit.DB import ElementId as _ElementId
                near = doc.GetElement(_ElementId(core.eid_value(element.Id) + step))
            except Exception:
                near = None
            if isinstance(near, View) and _name_of(near).strip().lower() in out["names"]:
                add_view(near)
    return out


def _names_on(element):
    """The names a selected element answers to: its own, and the view name
    a marker carries as a parameter."""
    names = []
    own = _name_of(element)
    if own:
        names.append(own)
    try:
        param = element.get_Parameter(BuiltInParameter.VIEW_NAME)
        if param is not None:
            text = param.AsString()
            if text and text not in names:
                names.append(text)
    except Exception:
        pass
    return names


def template_controls_scale(doc, view):
    """Whether the view's template holds its scale - True when there is a
    template and View Scale is not one of the parameters it leaves alone."""
    try:
        template_id = view.ViewTemplateId
        if template_id is None or core.eid_value(template_id) <= 0:
            return False
        template = doc.GetElement(template_id)
        if template is None:
            return False
        from Autodesk.Revit.DB import BuiltInParameter, ElementId
        scale_id = core.eid_value(ElementId(BuiltInParameter.VIEW_SCALE_PULLDOWN_METRIC))
        scale_ids = set([scale_id, core.eid_value(ElementId(BuiltInParameter.VIEW_SCALE))])
        left_alone = set([core.eid_value(item) for item in
                          template.GetNonControlledTemplateParameterIds()])
        return not bool(scale_ids & left_alone)
    except Exception as err:
        core.log(u"could not tell whether the template holds the scale: {0}".format(err))
        return False


def title_block_size_mm(doc, block):
    """A title block's paper size, read off one already placed - the type
    alone does not carry it.  None when it has never been placed."""
    if not block:
        return None
    try:
        from Autodesk.Revit.DB import BuiltInParameter
        wanted = core.eid_value(block["id"])
        collector = FilteredElementCollector(doc).OfCategory(_bic("OST_TitleBlocks"))\
            .WhereElementIsNotElementType()
        for instance in collector:
            try:
                if core.eid_value(instance.GetTypeId()) != wanted:
                    continue
                width = instance.get_Parameter(BuiltInParameter.SHEET_WIDTH).AsDouble()
                height = instance.get_Parameter(BuiltInParameter.SHEET_HEIGHT).AsDouble()
                if width > 0 and height > 0:
                    return (core.ft_to_mm(width), core.ft_to_mm(height))
            except Exception:
                continue
    except Exception as err:
        core.log(u"title block size could not be read: {0}".format(err))
    return None


def title_blocks(doc):
    """Every title block type in the project, as family and type.

    Two routes, for the same reason as the viewport types: asking by category
    alone comes back empty on some models, and an empty dropdown reads as a
    setting that cannot be set.
    """
    out = {}

    def add(element):
        try:
            key = core.eid_value(element.Id)
        except Exception:
            return
        if key in out:
            return
        family = ""
        try:
            family = u"{0}".format(element.FamilyName or "")
        except Exception:
            family = ""
        type_name = _name_of(element)
        label = u"{0}: {1}".format(family, type_name) if family else type_name
        out[key] = {"type": element, "id": element.Id, "name": label,
                    "family": family, "type_name": type_name}

    try:
        collector = FilteredElementCollector(doc)\
            .OfCategory(_bic("OST_TitleBlocks")).WhereElementIsElementType()
        for element in collector:
            add(element)
    except Exception as err:
        core.log("title block route 1 failed: {0}".format(err))

    try:
        for element in FilteredElementCollector(doc).OfClass(FamilySymbol):
            try:
                category = element.Category
                if category is None:
                    continue
                if core.eid_value(category.Id) != _bic_value(doc, "OST_TitleBlocks"):
                    continue
            except Exception:
                continue
            add(element)
    except Exception as err:
        core.log("title block route 2 failed: {0}".format(err))

    values = list(out.values())
    values.sort(key=lambda item: item["name"].lower())
    return values


def _bic_value(doc, name):
    """The category id of a built in category, as a plain number, so a
    symbol's own Category can be compared against it."""
    try:
        category = doc.Settings.Categories.get_Item(_bic(name))
        return core.eid_value(category.Id)
    except Exception:
        return None


def title_block_for_size(doc, size, mapping):
    """The title block type for a paper size: the one named in settings, else
    the first whose family or type name carries the size token."""
    blocks = title_blocks(doc)
    wanted = (mapping or {}).get(size, "")
    if wanted:
        wanted = wanted.strip()
        # "Family: Type", or a family on its own ending in a colon, or a bare
        # type name saved before the two dropdowns existed
        family, type_name = "", wanted
        if ":" in wanted:
            family, type_name = [piece.strip() for piece in wanted.split(":", 1)]
        for block in blocks:
            if family and block["family"].strip().lower() != family.lower():
                continue
            if type_name and block["type_name"].strip().lower() != type_name.lower():
                continue
            return block
        for block in blocks:
            if block["name"].strip().lower() == wanted.lower():
                return block
        core.log(u"no title block matches '{0}' for {1}".format(wanted, size))
    token = (size or "").strip().lower()
    if token:
        # THE TYPE NAME FIRST, and only then the family.
        #
        # A family called "BGL_TitleBlocks_A0-A1-A2" carries every size in its
        # own name, so matching the family name hands back its first type for
        # every size asked for - A1 came out as BGL_A0.  The type name is what
        # actually says which sheet this is.
        for block in blocks:
            if token in block["type_name"].strip().lower().replace(" ", ""):
                return block
        for block in blocks:
            if token in block["family"].strip().lower().replace(" ", ""):
                core.log(u"no title block type is named for {0}; falling back to "
                         u"'{1}' because its family name mentions the size"
                         .format(size, block["name"]))
                return block
    if blocks:
        core.log(u"nothing matches the paper size {0}, so '{1}' was used - set the "
                 u"title block for each size in Settings".format(size, blocks[0]["name"]))
    return blocks[0] if blocks else None


def sheet_frame_mm(doc, sheet):
    """Where the title block actually is on the sheet: (left, bottom, width,
    height) in sheet mm.

    THE TITLE BLOCK'S ORIGIN IS NOT ITS BOTTOM LEFT CORNER.  Revit puts the
    family's own origin at the sheet's 0,0, and plenty of title blocks are
    drawn from their bottom right corner (or their centre) - this project's
    BGL ones among them.  Laying the views out from 0,0 put the whole layout
    up and to the left of the paper.  So the frame is read off the title
    block placed on this sheet - its box in the sheet's own coordinates -
    then off the sheet's outline, and only then assumed.
    """
    try:
        collector = FilteredElementCollector(doc, sheet.Id).OfCategory(_bic("OST_TitleBlocks"))\
            .WhereElementIsNotElementType()
        best = None
        for block in collector:
            box = block.get_BoundingBox(sheet)
            if box is None:
                continue
            frame = (core.ft_to_mm(box.Min.X), core.ft_to_mm(box.Min.Y),
                     core.ft_to_mm(box.Max.X - box.Min.X), core.ft_to_mm(box.Max.Y - box.Min.Y))
            if frame[2] > 1 and frame[3] > 1 and (best is None or
                                                  frame[2] * frame[3] > best[2] * best[3]):
                best = frame
        if best is not None:
            return best
    except Exception as err:
        core.log(u"the title block's box could not be read: {0}".format(err))
    try:
        outline = sheet.Outline
        width = core.ft_to_mm(outline.Max.U - outline.Min.U)
        height = core.ft_to_mm(outline.Max.V - outline.Min.V)
        if width > 1 and height > 1:
            return (core.ft_to_mm(outline.Min.U), core.ft_to_mm(outline.Min.V), width, height)
    except Exception:
        pass
    return (0.0, 0.0, 841.0, 594.0)


def sheet_size_mm(doc, sheet):
    """The sheet's own paper size, read off its outline rather than guessed
    from the title block's name."""
    try:
        outline = sheet.Outline
        width = core.ft_to_mm(outline.Max.U - outline.Min.U)
        height = core.ft_to_mm(outline.Max.V - outline.Min.V)
        if width > 1 and height > 1:
            return (width, height)
    except Exception:
        pass
    return (841.0, 594.0)


PAPER_SIZES = {
    "A0": (1189.0, 841.0),
    "A1": (841.0, 594.0),
    "A2": (594.0, 420.0),
    "A3": (420.0, 297.0),
    "A4": (297.0, 210.0),
}


def sheet_parameters(doc):
    """Writable text parameter names available on sheets, for the name push.

    The project's own bindings for the Sheets category are read first, then
    the parameters the sheets actually carry are unioned in - a project
    parameter shows in the bindings, a shared parameter delivered with the
    title block often only shows on the elements.  Reading one sheet and
    stopping is what made this list come back nearly empty.
    """
    names = set()

    # the bindings for the Sheets category
    try:
        iterator = doc.ParameterBindings.ForwardIterator()
        iterator.Reset()
        while iterator.MoveNext():
            try:
                definition = iterator.Key
                binding = iterator.Current
            except Exception:
                continue
            try:
                categories = binding.Categories
            except Exception:
                continue
            for category in categories:
                try:
                    if str(category.Name).strip().lower() in ("sheets", "sheet"):
                        names.add(definition.Name)
                except Exception:
                    continue
    except Exception as err:
        core.log("sheet parameter bindings read failed: {0}".format(err))

    # and what the sheets themselves carry
    try:
        looked = 0
        for sheet in FilteredElementCollector(doc).OfClass(ViewSheet):
            looked += 1
            try:
                for param in sheet.Parameters:
                    try:
                        if param.IsReadOnly:
                            continue
                        if param.StorageType != StorageType.String:
                            continue
                        names.add(param.Definition.Name)
                    except Exception:
                        continue
            except Exception:
                continue
            if looked >= 25:
                break
    except Exception as err:
        core.log("sheet parameter read failed: {0}".format(err))

    return sorted(names, key=lambda text: text.lower())


def existing_names(doc):
    """Every view and sheet name and number already taken, lower cased."""
    views = set()
    sheets = set()
    numbers = set()
    try:
        for view in FilteredElementCollector(doc).OfClass(View):
            views.add(_name_of(view).strip().lower())
    except Exception:
        pass
    try:
        for sheet in FilteredElementCollector(doc).OfClass(ViewSheet):
            sheets.add(_name_of(sheet).strip().lower())
            try:
                numbers.add((sheet.SheetNumber or "").strip().lower())
            except Exception:
                pass
    except Exception:
        pass
    return views, sheets, numbers


