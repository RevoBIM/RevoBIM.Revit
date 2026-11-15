# -*- coding: utf-8 -*-
"""Every read of the model. Nothing in here writes.

Results come back as plain Python records (TypeNode, RoomRecord, Source) so
the window and the planner never hold a Revit element longer than one read.
BuiltInCategory and BuiltInParameter members are looked up by name inside
functions, never at import - one less thing that can die before the tool
runs on a release that lacks one of them.
"""
import tagall_clr  # noqa: F401  (assemblies first)
import tagall_core as core
from tagall_core import eid_value, to_text

from Autodesk.Revit.DB import (FilteredElementCollector, ElementId, BuiltInCategory,
                               CategoryType, FamilySymbol, RevitLinkInstance, ViewType,
                               View, ViewPlan, IndependentTag, Reference, XYZ,
                               PlanViewPlane)


# ====================== records ======================

class Source(object):
    """The host model or one loaded link instance."""

    def __init__(self, key, name, doc, instance=None, transform=None):
        self.key = key
        self.name = name
        self.doc = doc
        self.instance = instance
        self.transform = transform
        self.is_link = instance is not None

    @property
    def link_value(self):
        return eid_value(self.instance.Id) if self.instance is not None else 0


class TypeNode(object):
    """One family type of one source, with the elements of it in scope."""

    def __init__(self, source, category, family, type_name, type_id):
        self.source = source
        self.category = category
        self.family = family
        self.type_name = type_name
        self.type_id = type_id
        self.element_ids = []

    @property
    def key(self):
        return (self.source.key, eid_value(self.type_id))

    @property
    def count(self):
        return len(self.element_ids)

    @property
    def display(self):
        return core.type_display(self.family, self.type_name)


class RoomRecord(object):
    def __init__(self, source, room_id, label, point, min_z, max_z, level_name):
        self.source = source
        self.room_id = room_id
        self.label = label
        self.point = point
        self.min_z = min_z
        self.max_z = max_z
        self.level_name = level_name

    @property
    def key(self):
        return core.element_key(self.source.link_value, eid_value(self.room_id))


class SheetRecord(object):
    """One sheet: every view placed on it, and which of those the list it
    sits in can tag.

    `view_ids` are the taggable ones - what a run from this sheet works in.
    `placed` is every placed view as (key, name, family and type), which is
    what expanding the sheet shows, the untaggable ones greyed.
    """

    def __init__(self, sheet, number, name, view_ids, placed=None):
        self.sheet = sheet
        self.element = sheet
        self.sheet_id = sheet.Id
        self.number = number
        self.name = name
        self.view_ids = view_ids
        self.placed = placed or []
        self.groups = {}

    def group_value(self, parameter_name):
        if not parameter_name:
            return u""
        if parameter_name not in self.groups:
            self.groups[parameter_name] = parameter_text(self.sheet, parameter_name)
        return self.groups[parameter_name]

    def cells(self, group_1, group_2):
        return {"number": self.number, "name": self.name,
                "g1": self.group_value(group_1), "g2": self.group_value(group_2),
                "views": u"{0}".format(len(self.view_ids))}

    @property
    def key(self):
        return eid_value(self.sheet_id)

    @property
    def display(self):
        count = len(self.view_ids)
        return u"{0}   {1}   [{2} view{3}]".format(
            self.number, self.name, count, u"" if count == 1 else u"s")


class ViewRecord(object):
    def __init__(self, view):
        self.view = view
        self.view_id = view.Id
        self.name = safe_name(view)
        self.kind = to_text(view.ViewType)
        try:
            self.is_plan = isinstance(view, ViewPlan)
        except Exception:
            self.is_plan = False
        self.family_type = view_family_type(view) or self.kind
        self.element = view
        self.groups = {}          # parameter name -> text, filled on demand

    def group_value(self, parameter_name):
        if not parameter_name:
            return u""
        if parameter_name not in self.groups:
            self.groups[parameter_name] = parameter_text(self.view, parameter_name)
        return self.groups[parameter_name]

    def cells(self, group_1, group_2):
        return {"name": self.name, "type": self.family_type,
                "g1": self.group_value(group_1), "g2": self.group_value(group_2)}

    @property
    def key(self):
        return eid_value(self.view_id)

    @property
    def display(self):
        return u"{0}   [{1}]".format(self.name, self.kind)


# ====================== helpers ======================

def safe_name(element):
    """Element.Name raises AttributeError in IronPython for some classes -
    guard it and fall back to the parameter."""
    try:
        text = element.Name
        if text:
            return to_text(text)
    except Exception:
        pass
    try:
        from Autodesk.Revit.DB import Element
        return to_text(Element.Name.GetValue(element))
    except Exception:
        pass
    try:
        param = element.get_Parameter(builtin_parameter("ALL_MODEL_TYPE_NAME"))
        if param is not None:
            return to_text(param.AsString())
    except Exception:
        pass
    return u""


def builtin_category(name):
    return getattr(BuiltInCategory, name)


def builtin_parameter(name):
    from Autodesk.Revit.DB import BuiltInParameter
    return getattr(BuiltInParameter, name)


def xyz_tuple(point):
    return (point.X, point.Y, point.Z)


def to_xyz(tup):
    return XYZ(tup[0], tup[1], tup[2])


def transform_point(transform, tup):
    if transform is None:
        return tup
    try:
        return xyz_tuple(transform.OfPoint(to_xyz(tup)))
    except Exception:
        return tup


def bbox_corners(bbox):
    """The eight corners of a BoundingBoxXYZ in world coordinates, through
    the box's own transform."""
    out = []
    try:
        lo, hi = bbox.Min, bbox.Max
        transform = bbox.Transform
        for x in (lo.X, hi.X):
            for y in (lo.Y, hi.Y):
                for z in (lo.Z, hi.Z):
                    point = XYZ(x, y, z)
                    try:
                        point = transform.OfPoint(point)
                    except Exception:
                        pass
                    out.append(xyz_tuple(point))
    except Exception:
        return []
    return out


def element_bounds(element, transform=None):
    """World box of an element, transformed into the host where the element
    lives in a link."""
    try:
        bbox = element.get_BoundingBox(None)
    except Exception:
        bbox = None
    if bbox is None:
        return None, None
    corners = bbox_corners(bbox)
    if transform is not None:
        corners = [transform_point(transform, c) for c in corners]
    return core.corners_bounds(corners)


def element_point(element, transform=None):
    """The point a tag is measured from: the location point, the middle of a
    location curve, else the centre of the bounding box."""
    point = None
    try:
        location = element.Location
        if location is not None:
            if hasattr(location, "Point"):
                point = xyz_tuple(location.Point)
            elif hasattr(location, "Curve"):
                curve = location.Curve
                point = xyz_tuple(curve.Evaluate(0.5, True))
    except Exception:
        point = None
    if point is None:
        lo, hi = element_bounds(element)
        if lo is None:
            return None
        point = ((lo[0] + hi[0]) / 2.0, (lo[1] + hi[1]) / 2.0, (lo[2] + hi[2]) / 2.0)
    return transform_point(transform, point)


def level_project_elevation(level):
    """ProjectElevation, not Elevation - Elevation is in survey coordinates
    on a survey-point-based project and sits ~80m out."""
    try:
        return float(level.ProjectElevation)
    except Exception:
        try:
            return float(level.Elevation)
        except Exception:
            return None


# ====================== sources ======================

def list_sources(doc):
    """Host first, then every loaded link instance by its type name; the same
    link placed twice is numbered. Unloaded links are left out rather than
    offered and then failing."""
    sources = [Source(core.HOST_KEY, u"<Current model>", doc)]
    instances = []
    try:
        for instance in FilteredElementCollector(doc).OfClass(RevitLinkInstance):
            try:
                link_doc = instance.GetLinkDocument()
            except Exception:
                link_doc = None
            if link_doc is None:
                continue
            name = u""
            try:
                link_type = doc.GetElement(instance.GetTypeId())
                name = safe_name(link_type)
            except Exception:
                name = u""
            if not name:
                name = safe_name(instance) or u"Link"
            name = name.replace(u".rvt", u"")
            try:
                transform = instance.GetTotalTransform()
            except Exception:
                transform = None
            instances.append((name, instance, link_doc, transform))
    except Exception:
        pass
    instances.sort(key=lambda item: core.natural_key(item[0]))
    names = core.unique_names([item[0] for item in instances])
    for name, item in zip(names, instances):
        sources.append(Source(u"link:{0}".format(eid_value(item[1].Id)), name,
                              item[2], item[1], item[3]))
    return sources


def source_by_key(sources, key):
    for source in sources:
        if source.key == key:
            return source
    return None


# ====================== view bounds ======================

def plane_z(view, view_range, plane):
    try:
        level_id = view_range.GetLevelId(plane)
        if level_id is None or eid_value(level_id) <= 0:
            return None
        level = view.Document.GetElement(level_id)
        base = level_project_elevation(level)
        if base is None:
            return None
        return base + float(view_range.GetOffset(plane))
    except Exception:
        return None


def view_bounds(view):
    """World box of what a view can show, and its cut plane elevation.

    Plan views: Z from the view range, XY from the crop when it is active.
    Other views: the crop box (with its far clip) when active, else the
    section box of a 3D view. None means unbounded on that side.
    """
    lo = hi = None
    cut_z = None
    is_plan = False
    try:
        is_plan = isinstance(view, ViewPlan)
    except Exception:
        pass
    try:
        if view.CropBoxActive:
            lo, hi = core.corners_bounds(bbox_corners(view.CropBox))
    except Exception:
        lo = hi = None
    if is_plan:
        zs = []
        try:
            view_range = view.GetViewRange()
            for name in ("TopClipPlane", "CutPlane", "BottomClipPlane", "ViewDepthPlane"):
                plane = getattr(PlanViewPlane, name)
                z = plane_z(view, view_range, plane)
                if z is not None:
                    zs.append(z)
                    if name == "CutPlane":
                        cut_z = z
        except Exception:
            zs = []
        if zs:
            min_z, max_z = min(zs), max(zs)
            if lo is None:
                lo = (-1e9, -1e9, min_z)
                hi = (1e9, 1e9, max_z)
            else:
                lo = (lo[0], lo[1], min_z)
                hi = (hi[0], hi[1], max_z)
        if cut_z is None:
            try:
                level = view.GenLevel
                base = level_project_elevation(level)
                if base is not None:
                    cut_z = base + core.mm_to_ft(1200)
            except Exception:
                cut_z = None
    elif lo is None:
        try:
            if view.IsSectionBoxActive:
                lo, hi = core.corners_bounds(bbox_corners(view.GetSectionBox()))
        except Exception:
            pass
    return lo, hi, cut_z


def view_scale(view):
    """The view's scale (100 for 1:100), or 1 where it has none."""
    try:
        return max(1, int(view.Scale))
    except Exception:
        return 1


def tagged_reference(tag):
    """The reference a tag is attached to - the one its leader elbow is set
    against. GetTaggedReferences arrived in 2022; GetTaggedReference was
    removed later, so both are tried."""
    try:
        refs = tag.GetTaggedReferences()
        for ref in refs:
            return ref
    except Exception:
        pass
    try:
        return tag.GetTaggedReference()
    except Exception:
        return None


def view_directions(view):
    try:
        return xyz_tuple(view.RightDirection), xyz_tuple(view.UpDirection)
    except Exception:
        return (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)


# ====================== the tree ======================

EXCLUDED_CATEGORIES = set([
    u"Rooms", u"Spaces", u"Areas", u"Lines", u"Grids", u"Levels", u"Reference Planes",
    u"Views", u"Cameras", u"Elevations", u"Sections", u"Callouts", u"Sheets",
    u"Scope Boxes", u"Project Base Point", u"Survey Point", u"Internal Origin",
    u"RVT Links", u"Model Groups", u"Detail Groups", u"Curtain Wall Grids",
    u"HVAC Zones", u"Duct Systems", u"Piping Systems", u"Electrical Circuits",
    u"Raster Images", u"Point Clouds", u"Coordination Model", u"Legend Components",
    u"Matchline", u"Analytical Nodes", u"Boundary Conditions", u"Structural Load Cases",
    u"Center Line", u"Wire Insulation", u"Duct Insulations", u"Pipe Insulations",
    u"Duct Linings", u"Sketch", u"Masking Region", u"Filled region", u"Imports in Families",
])


def taggable_element(element):
    """Model elements only: skip annotation, view-specific things, elements
    with no category and the categories a tag cannot go on."""
    try:
        if element.ViewSpecific:
            return None
    except Exception:
        pass
    try:
        category = element.Category
    except Exception:
        return None
    if category is None:
        return None
    try:
        if category.CategoryType != CategoryType.Model:
            return None
    except Exception:
        return None
    name = to_text(category.Name)
    if name in EXCLUDED_CATEGORIES:
        return None
    return name


def scope_elements(source, view, bounds):
    """The elements of a source that are in scope: the view's own elements
    for the host in a view, everything for a project read, and for a link in
    a view everything whose box overlaps what the view can show."""
    doc = source.doc
    if view is not None and not source.is_link:
        try:
            collector = FilteredElementCollector(doc, view.Id).WhereElementIsNotElementType()
            return list(collector), False
        except Exception:
            return [], False
    collector = FilteredElementCollector(doc).WhereElementIsNotElementType()
    return list(collector), (view is not None and source.is_link)


def collect_type_nodes(source, view=None):
    """category -> family -> type -> TypeNode, with element ids in scope."""
    nodes = {}
    type_cache = {}
    lo = hi = None
    if view is not None:
        lo, hi, _cut = view_bounds(view)
    elements, test_bounds = scope_elements(source, view, (lo, hi))
    for element in elements:
        category = taggable_element(element)
        if not category:
            continue
        try:
            type_id = element.GetTypeId()
        except Exception:
            continue
        if type_id is None or eid_value(type_id) <= 0:
            continue
        if test_bounds and lo is not None:
            e_lo, e_hi = element_bounds(element, source.transform)
            if e_lo is None or not core.bounds_overlap(e_lo, e_hi, lo, hi):
                continue
        type_value = eid_value(type_id)
        info = type_cache.get(type_value)
        if info is None:
            element_type = source.doc.GetElement(type_id)
            family = u""
            type_name = safe_name(element_type) if element_type is not None else u""
            try:
                family = to_text(element_type.FamilyName)
            except Exception:
                family = u""
            if not family:
                family = category
            info = (family, type_name or u"(type)")
            type_cache[type_value] = info
        node = nodes.get(type_value)
        if node is None:
            node = TypeNode(source, category, info[0], info[1], type_id)
            nodes[type_value] = node
        node.element_ids.append(element.Id)
    return list(nodes.values())


def collect_type_nodes_many(source, views):
    """Type nodes for one source across several views.

    The host is read per view, through each view's own collector. A link
    has no view collector of its own, so every element of it is tested
    against what each view can show - and its bounding boxes are worked
    out once here rather than once per view, which on a big architectural
    link and twenty ticked views is the difference between a read and a
    pause.
    """
    if not views:
        return []
    if not source.is_link:
        return merge_nodes([collect_type_nodes(source, view) for view in views])
    view_boxes = [view_bounds(view)[:2] for view in views]
    nodes = {}
    type_cache = {}
    for element in FilteredElementCollector(source.doc).WhereElementIsNotElementType():
        category = taggable_element(element)
        if not category:
            continue
        try:
            type_id = element.GetTypeId()
        except Exception:
            continue
        if type_id is None or eid_value(type_id) <= 0:
            continue
        e_lo, e_hi = element_bounds(element, source.transform)
        if e_lo is None:
            continue
        shown = False
        for lo, hi in view_boxes:
            if lo is None or core.bounds_overlap(e_lo, e_hi, lo, hi):
                shown = True
                break
        if not shown:
            continue
        type_value = eid_value(type_id)
        info = type_cache.get(type_value)
        if info is None:
            element_type = source.doc.GetElement(type_id)
            try:
                family = to_text(element_type.FamilyName) or category
            except Exception:
                family = category
            info = (family, safe_name(element_type) or u"(type)")
            type_cache[type_value] = info
        node = nodes.get(type_value)
        if node is None:
            node = TypeNode(source, category, info[0], info[1], type_id)
            nodes[type_value] = node
        node.element_ids.append(element.Id)
    return list(nodes.values())


def nodes_for_elements(source, element_ids):
    """TypeNodes for a set of host element ids - the Revit selection."""
    nodes = {}
    for element_id in element_ids:
        try:
            element = source.doc.GetElement(element_id)
        except Exception:
            continue
        if element is None:
            continue
        category = taggable_element(element)
        if not category:
            continue
        try:
            type_id = element.GetTypeId()
        except Exception:
            continue
        if type_id is None or eid_value(type_id) <= 0:
            continue
        type_value = eid_value(type_id)
        node = nodes.get(type_value)
        if node is None:
            element_type = source.doc.GetElement(type_id)
            try:
                family = to_text(element_type.FamilyName) or category
            except Exception:
                family = category
            node = TypeNode(source, category, family, safe_name(element_type) or u"(type)", type_id)
            nodes[type_value] = node
        node.element_ids.append(element.Id)
    return list(nodes.values())


def host_elements_by_type(doc, view, wanted_type_values):
    """type id value -> [elements] for the host elements a view shows, read
    with one collector per view rather than one per row."""
    found = {}
    if not wanted_type_values:
        return found
    try:
        collector = FilteredElementCollector(doc, view.Id).WhereElementIsNotElementType()
    except Exception:
        return found
    for element in collector:
        try:
            type_value = eid_value(element.GetTypeId())
        except Exception:
            continue
        if type_value in wanted_type_values:
            found.setdefault(type_value, []).append(element)
    return found


def elements_of_node_in_view(node, view, bounds, host_lookup):
    """The elements of one type node that a given view can show. Host nodes
    come from the per-view lookup; link nodes are tested by their box
    against what the view can show."""
    source = node.source
    type_value = eid_value(node.type_id)
    if not source.is_link:
        return list(host_lookup.get(type_value, []))
    lo, hi = bounds
    found = []
    for element_id in node.element_ids:
        element = source.doc.GetElement(element_id)
        if element is None:
            continue
        if lo is not None:
            e_lo, e_hi = element_bounds(element, source.transform)
            if e_lo is None or not core.bounds_overlap(e_lo, e_hi, lo, hi):
                continue
        found.append(element)
    return found


# ====================== tag families ======================

def list_tag_symbols(doc):
    """Every tag family type in the project, by tag category name."""
    by_category = {}
    try:
        for symbol in FilteredElementCollector(doc).OfClass(FamilySymbol):
            try:
                category = symbol.Category
                if category is None or category.CategoryType != CategoryType.Annotation:
                    continue
                cat_name = to_text(category.Name)
                if not (cat_name.endswith(u" Tags") or cat_name.endswith(u" Tag")):
                    continue
                family_name = to_text(symbol.FamilyName)
                display = core.type_display(family_name, safe_name(symbol))
                by_category.setdefault(cat_name, []).append((display, symbol.Id))
            except Exception:
                continue
    except Exception:
        pass
    for cat_name in by_category:
        by_category[cat_name].sort(key=lambda item: core.natural_key(item[0]))
    return by_category


def tags_for_category(tag_symbols, category_name):
    """(display, type id, is_multi) for the tags that suit a model category:
    the category's own tags first, multi-category tags after."""
    specific = []
    multi = []
    for tag_category, items in tag_symbols.items():
        if not core.tag_category_matches(category_name, tag_category):
            continue
        target = multi if tag_category in core.UNIVERSAL_TAG_CATEGORIES else specific
        for display, type_id in items:
            target.append((display, type_id, tag_category in core.UNIVERSAL_TAG_CATEGORIES))
    specific.sort(key=lambda item: core.natural_key(item[0]))
    multi.sort(key=lambda item: core.natural_key(item[0]))
    return specific + multi


def list_room_tag_types(doc):
    out = []
    try:
        collector = FilteredElementCollector(doc).OfCategory(builtin_category("OST_RoomTags")).WhereElementIsElementType()
        for symbol in collector:
            try:
                family = to_text(symbol.FamilyName)
            except Exception:
                family = u""
            out.append((core.type_display(family, safe_name(symbol)), symbol.Id))
    except Exception:
        pass
    out.sort(key=lambda item: core.natural_key(item[0]))
    return out


# ====================== views ======================

FAMILY_VIEW_TYPES = ("FloorPlan", "CeilingPlan", "Elevation", "Section", "Detail",
                     "ThreeD", "EngineeringPlan", "AreaPlan", "Walkthrough")
ROOM_VIEW_TYPES = ("FloorPlan", "CeilingPlan", "AreaPlan", "EngineeringPlan")


def list_sheets(doc, records, include_empty=False):
    """Every sheet in drawing-number order, with the views placed on it.

    With `include_empty` off, a sheet carrying nothing in `records` is left
    out rather than offered and then doing nothing, and the caller is told
    how many that was. With it on - Family Tags, which lists every sheet in
    the project - such a sheet is listed with a view count of 0.
    """
    wanted = {}
    for record in records:
        wanted[eid_value(record.view_id)] = record
    out = []
    skipped = 0
    try:
        from Autodesk.Revit.DB import ViewSheet
        collector = FilteredElementCollector(doc).OfClass(ViewSheet)
    except Exception:
        return out, skipped
    for sheet in collector:
        try:
            if sheet.IsTemplate:
                continue
        except Exception:
            pass
        taggable = []
        placed = []
        for value in placed_view_keys(sheet):
            record = wanted.get(value)
            if record is not None:
                taggable.append(value)
                placed.append((value, record.name, record.family_type, True))
                continue
            try:
                view = doc.GetElement(ElementId(value))
            except Exception:
                view = None
            if view is not None:
                placed.append((value, safe_name(view), view_family_type(view) or to_text(view.ViewType), False))
        if not taggable and not include_empty:
            skipped += 1
            continue
        number = u""
        try:
            number = to_text(sheet.SheetNumber)
        except Exception:
            pass
        out.append(SheetRecord(sheet, number or u"?", safe_name(sheet), taggable, placed))
    out.sort(key=lambda record: core.natural_key(record.number))
    return out, skipped


def view_family_type(view):
    """'Floor Plan : MEP Floor Plan' - the view's family and type, the way
    Revit's own Properties palette reads it."""
    try:
        view_type = view.Document.GetElement(view.GetTypeId())
    except Exception:
        view_type = None
    if view_type is None:
        return u""
    family = u""
    try:
        family = to_text(view_type.FamilyName)
    except Exception:
        family = u""
    return core.type_display(family, safe_name(view_type))


def parameter_text(element, name):
    """A parameter's value as the Properties palette shows it, or blank."""
    try:
        parameter = element.LookupParameter(name)
    except Exception:
        parameter = None
    if parameter is None:
        return u""
    try:
        if not parameter.HasValue:
            return u""
    except Exception:
        pass
    for reader in ("AsString", "AsValueString"):
        try:
            value = getattr(parameter, reader)()
            if value:
                return to_text(value)
        except Exception:
            continue
    try:
        value = parameter.AsElementId()
        if value is not None and eid_value(value) > 0:
            return safe_name(element.Document.GetElement(value))
    except Exception:
        pass
    return u""


# group parameters tried in order when nothing has been chosen yet - the
# office's own browser parameters first, then Revit's
GROUP_DEFAULTS = (u"BGL_View Discipline", u"BGL_View Type", u"BGL_View Series",
                  u"View Group", u"Sub-Discipline", u"Discipline", u"Associated Level")


def view_parameter_names(records, sample=80):
    """The parameter names the views carry, for the two group dropdowns.

    Read off a sample rather than every view - a project's views share a
    handful of parameter sets, and reading every parameter of four hundred
    views to fill a dropdown is a pause nobody asked for.
    """
    names = set()
    for record in records[:sample]:
        try:
            for parameter in record.element.Parameters:
                try:
                    name = to_text(parameter.Definition.Name)
                except Exception:
                    continue
                if name:
                    names.add(name)
        except Exception:
            continue
    return sorted(names, key=core.natural_key)


# the Sheet Manager's own grouping parameters first, then Revit's
SHEET_GROUP_DEFAULTS = (u"BGL_Sheet Discipline", u"BGL_Sheet Series", u"BGL_Sheet Stage",
                        u"BGL Sheet Stage", u"BGL_WIP_Tag", u"Sheet Issue Date", u"Designed By")


def default_groups(names, defaults=GROUP_DEFAULTS):
    found = [name for name in defaults if name in names]
    first = found[0] if found else u""
    second = found[1] if len(found) > 1 else u""
    return first, second


def opening_context(uidoc):
    """What the tool opened on: the active view, whether it is a sheet and
    what is placed on it, and the views picked before opening.

    A pick can be a view or a sheet in the Project Browser, or a viewport on
    the open sheet. Picking a viewport selects the Viewport element, not its
    view - reading only View and ViewSheet out of the selection, as 1.1.0
    did, silently ignored viewports picked on a sheet. A sheet picked in the
    Project Browser counts as the views placed on it.
    """
    out = {"active_key": 0, "active_is_sheet": False, "sheet_views": [],
           "selected_views": set(), "selected_sheets": set()}
    try:
        from Autodesk.Revit.DB import ViewSheet
    except Exception:
        return out
    try:
        from Autodesk.Revit.DB import Viewport
    except Exception:
        Viewport = None
    doc = uidoc.Document
    active = active_view(uidoc)
    if active is not None:
        out["active_key"] = eid_value(active.Id)
        if isinstance(active, ViewSheet):
            out["active_is_sheet"] = True
            out["sheet_views"] = placed_view_keys(active)
    try:
        picked = list(uidoc.Selection.GetElementIds())
    except Exception:
        picked = []
    for element_id in picked:
        try:
            element = doc.GetElement(element_id)
        except Exception:
            element = None
        if element is None:
            continue
        if Viewport is not None and isinstance(element, Viewport):
            try:
                out["selected_views"].add(eid_value(element.ViewId))
            except Exception:
                pass
        elif isinstance(element, ViewSheet):
            out["selected_sheets"].add(eid_value(element.Id))
            out["selected_views"].update(placed_view_keys(element))
        elif isinstance(element, View):
            out["selected_views"].add(eid_value(element.Id))
    return out


def placed_view_keys(sheet):
    """The views placed on a sheet, in viewport order."""
    out = []
    try:
        for view_id in sheet.GetAllPlacedViews():
            value = eid_value(view_id)
            if value not in out:
                out.append(value)
    except Exception:
        pass
    return out


def is_sheet(view):
    try:
        from Autodesk.Revit.DB import ViewSheet
        return isinstance(view, ViewSheet)
    except Exception:
        return False


def merge_nodes(node_lists):
    """Type nodes read from several views, merged into one per type with each
    element counted once however many views show it."""
    merged = {}
    seen = {}
    for nodes in node_lists:
        for node in nodes:
            existing = merged.get(node.key)
            if existing is None:
                existing = TypeNode(node.source, node.category, node.family,
                                    node.type_name, node.type_id)
                merged[node.key] = existing
                seen[node.key] = set()
            for element_id in node.element_ids:
                value = eid_value(element_id)
                if value in seen[node.key]:
                    continue
                seen[node.key].add(value)
                existing.element_ids.append(element_id)
    return list(merged.values())


def list_views(doc, allowed):
    out = []
    allowed_values = set()
    for name in allowed:
        try:
            allowed_values.add(getattr(ViewType, name))
        except Exception:
            continue
    try:
        for view in FilteredElementCollector(doc).OfClass(View):
            try:
                if view.IsTemplate:
                    continue
                if view.ViewType not in allowed_values:
                    continue
            except Exception:
                continue
            out.append(ViewRecord(view))
    except Exception:
        pass
    out.sort(key=lambda record: core.natural_key(record.name))
    return out


# ====================== existing tags ======================

def link_element_key(link_element_id):
    try:
        link_value = eid_value(link_element_id.LinkInstanceId)
    except Exception:
        link_value = 0
    if link_value > 0:
        try:
            return core.element_key(link_value, eid_value(link_element_id.LinkedElementId))
        except Exception:
            return None
    try:
        return core.element_key(0, eid_value(link_element_id.HostElementId))
    except Exception:
        return None


def tag_targets(tag):
    """The keys of everything an IndependentTag tags. 2022+ tags can tag
    several elements; older ones expose a single LinkElementId."""
    keys = []
    try:
        for link_id in tag.GetTaggedElementIds():
            key = link_element_key(link_id)
            if key:
                keys.append(key)
        return keys
    except Exception:
        pass
    try:
        key = link_element_key(tag.TaggedElementId)
        if key:
            keys.append(key)
    except Exception:
        pass
    return keys


def existing_tags(doc, view):
    """element key -> [tag ids] for every IndependentTag in the view."""
    tagged = {}
    try:
        for tag in FilteredElementCollector(doc, view.Id).OfClass(IndependentTag):
            for key in tag_targets(tag):
                tagged.setdefault(key, []).append(tag.Id)
    except Exception:
        pass
    return tagged


def element_reference(element, source):
    ref = Reference(element)
    if source.is_link:
        ref = ref.CreateLinkReference(source.instance)
    return ref


def element_key_of(element, source):
    return core.element_key(source.link_value, eid_value(element.Id))


def annotation_corners(tag, view):
    """The corners of a placed tag's box in the view, or None.

    Only meaningful with the tag's leader switched off - see
    tagall_ops.measure_tag_boxes. With a leader on, this box covers the
    leader as well as the text, so its edge is the far end of the leader
    rather than the side of the tag.
    """
    try:
        bbox = tag.get_BoundingBox(view)
    except Exception:
        bbox = None
    if bbox is None:
        return None
    corners = bbox_corners(bbox)
    return corners or None


def set_leader(tag, on):
    try:
        tag.HasLeader = bool(on)
        return True
    except Exception:
        return False


def head_position(tag):
    """Where Revit actually put the tag head, which is not always where it
    was asked to."""
    try:
        return xyz_tuple(tag.TagHeadPosition)
    except Exception:
        return None


def leader_elbow(tag, reference):
    try:
        return xyz_tuple(tag.GetLeaderElbow(reference))
    except Exception:
        pass
    try:
        return xyz_tuple(tag.LeaderElbow)
    except Exception:
        return None


# ====================== rooms ======================

def collect_rooms(source):
    """Every placed room in a source, with its point and Z range in host
    coordinates."""
    out = []
    try:
        collector = FilteredElementCollector(source.doc).OfCategory(builtin_category("OST_Rooms")).WhereElementIsNotElementType()
    except Exception:
        return out
    for room in collector:
        try:
            if room.Area <= 0:
                continue
            location = room.Location
            if location is None:
                continue
            point = transform_point(source.transform, xyz_tuple(location.Point))
        except Exception:
            continue
        lo, hi = element_bounds(room, source.transform)
        if lo is None:
            min_z = max_z = point[2]
        else:
            min_z, max_z = lo[2], hi[2]
        level_name = u""
        try:
            level_name = safe_name(room.Level)
        except Exception:
            pass
        number = u""
        name = u""
        try:
            number = to_text(room.get_Parameter(builtin_parameter("ROOM_NUMBER")).AsString())
        except Exception:
            pass
        try:
            name = to_text(room.get_Parameter(builtin_parameter("ROOM_NAME")).AsString())
        except Exception:
            pass
        label = (number + u" " + name).strip() or u"Room {0}".format(eid_value(room.Id))
        out.append(RoomRecord(source, room.Id, label, point, min_z, max_z, level_name))
    return out


def existing_room_tags(doc, view):
    """(room key -> [tag ids], [orphaned tag ids]) for a view. A tag is
    unassigned - shows ? - when Revit says it is orphaned or it has no room."""
    keyed = {}
    orphaned = []
    try:
        collector = FilteredElementCollector(doc, view.Id).OfCategory(builtin_category("OST_RoomTags")).WhereElementIsNotElementType()
    except Exception:
        return keyed, orphaned
    for tag in collector:
        is_orphan = False
        try:
            is_orphan = bool(tag.IsOrphaned)
        except Exception:
            pass
        if not is_orphan:
            try:
                is_orphan = tag.Room is None
            except Exception:
                pass
        if is_orphan:
            orphaned.append(tag.Id)
            continue
        key = None
        try:
            key = link_element_key(tag.TaggedRoomId)
        except Exception:
            key = None
        if key is None:
            try:
                key = core.element_key(0, eid_value(tag.Room.Id))
            except Exception:
                key = None
        if key is not None:
            keyed.setdefault(key, []).append(tag.Id)
    return keyed, orphaned


def view_level_name(view):
    try:
        return safe_name(view.GenLevel)
    except Exception:
        return u""


def selected_ids(uidoc):
    try:
        return list(uidoc.Selection.GetElementIds())
    except Exception:
        return []


def active_view(uidoc):
    try:
        return uidoc.ActiveGraphicalView or uidoc.ActiveView
    except Exception:
        try:
            return uidoc.ActiveView
        except Exception:
            return None


def invalid_id():
    return ElementId.InvalidElementId
