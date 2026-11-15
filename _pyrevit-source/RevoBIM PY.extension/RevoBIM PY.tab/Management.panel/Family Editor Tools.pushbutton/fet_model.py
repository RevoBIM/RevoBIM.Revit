# =========================================================================
# Family Editor Tools - reading the family document
#
# Everything here reads.  Nothing here writes.  Every BuiltInCategory and
# BuiltInParameter member is looked up LATE, inside a function, through
# getattr - a member that does not exist on a given release is then a
# skipped feature rather than a module that will not load.
# =========================================================================

import fet_clr  # noqa: F401  - assemblies first, always

from Autodesk.Revit.DB import (BuiltInCategory, BuiltInParameter, Category,
                               DimensionType, ElementId, FilteredElementCollector,
                               FillPatternElement, LinePatternElement, Material,
                               ReferencePlane, TextNoteType, View, ViewType)

import fet_core

GROUP_FALLBACK = u"Data"


def bic(name):
    u"""BuiltInCategory uses singular member names (OST_DuctAccessory)."""
    return getattr(BuiltInCategory, name, None)


def bip(name):
    return getattr(BuiltInParameter, name, None)


def is_family(doc):
    try:
        return bool(doc) and bool(doc.IsFamilyDocument)
    except Exception:
        return False


def family_category_name(doc):
    try:
        return doc.OwnerFamily.FamilyCategory.Name
    except Exception:
        return u""


def family_name(doc):
    try:
        title = doc.Title
        for suffix in (u".rfa", u".RFA"):
            if title.endswith(suffix):
                return title[:-len(suffix)]
        return title
    except Exception:
        return u""


# =========================================================================
# Parameter groups
#
# GroupTypeId (ForgeTypeId) from Revit 2022; BuiltInParameterGroup before
# that and deprecated since.  The list is built from whichever the release
# actually offers, so the dropdown can never offer something AddParameter
# will refuse.
# =========================================================================

class GroupOption(object):
    def __init__(self, key, label, value, is_forge):
        self.key = key
        self.label = label
        self.value = value
        self.is_forge = is_forge

    def __repr__(self):
        return u"<GroupOption {0}>".format(self.key)


_GROUP_CACHE = []


def group_options():
    if _GROUP_CACHE:
        return list(_GROUP_CACHE)
    out = []
    out.extend(_forge_groups())
    if not out:
        out.extend(_legacy_groups())
    out.sort(key=lambda item: fet_core.natural_key(item.label))
    _GROUP_CACHE.extend(out)
    return list(out)


def _forge_groups():
    out = []
    try:
        from Autodesk.Revit.DB import GroupTypeId, LabelUtils
    except Exception:
        return out
    for name in dir(GroupTypeId):
        if name.startswith(u"_"):
            continue
        try:
            value = getattr(GroupTypeId, name)
        except Exception:
            continue
        if value is None or not hasattr(value, u"TypeId"):
            continue
        label = name
        try:
            label = LabelUtils.GetLabelForGroup(value)
        except Exception:
            label = name
        if not label:
            label = name
        out.append(GroupOption(name, label, value, True))
    return out


def _legacy_groups():
    out = []
    try:
        from Autodesk.Revit.DB import BuiltInParameterGroup, LabelUtils
    except Exception:
        return out
    for name in dir(BuiltInParameterGroup):
        if not name.startswith(u"PG_"):
            continue
        try:
            value = getattr(BuiltInParameterGroup, name)
        except Exception:
            continue
        label = name[3:].replace(u"_", u" ").title()
        try:
            label = LabelUtils.GetLabelFor(value) or label
        except Exception:
            pass
        out.append(GroupOption(name, label, value, False))
    return out


_GROUP_BY_KEY = {}
_GROUP_BY_ID = {}


def _group_indexes():
    u"""Built once.  A linear scan over every parameter group, per
    parameter, per row, is most of what made the window feel slow."""
    if not _GROUP_BY_KEY:
        for option in group_options():
            _GROUP_BY_KEY[option.key] = option
            _GROUP_BY_KEY.setdefault(option.label, option)
            _GROUP_BY_KEY.setdefault(option.label.lower(), option)
            if option.is_forge:
                try:
                    _GROUP_BY_ID[(u"f", option.value.TypeId)] = option.key
                except Exception:
                    pass
            else:
                _GROUP_BY_ID[(u"l", u"{0}".format(option.value))] = option.key
    return _GROUP_BY_KEY, _GROUP_BY_ID


def group_by_key(key):
    by_key, by_id = _group_indexes()
    text = fet_core._as_text(key)
    return by_key.get(text) or by_key.get(text.lower())


def default_group_option(preferred):
    option = group_by_key(preferred)
    if option is not None:
        return option
    option = group_by_key(GROUP_FALLBACK)
    if option is not None:
        return option
    options = group_options()
    return options[0] if options else None


# =========================================================================
# Family parameters already in the document
# =========================================================================

class ExistingParam(object):
    u"""One family parameter, read once, with everything the table needs.
    The live FamilyParameter is kept on it so a write does not have to go
    looking for it again by name - a rename would lose it."""

    def __init__(self):
        self.param = None
        self.name = u""
        self.guid = u""
        self.is_instance = False
        self.is_shared = False
        self.group_key = u""
        self.group_label = u""
        self.data_type = u""
        self.formula = u""
        self.can_have_formula = False
        self.is_reporting = False
        self.is_readonly = False
        self.is_builtin = False
        self.value_text = u""

    @property
    def binding(self):
        return u"instance" if self.is_instance else u"type"

    def __repr__(self):
        return u"<ExistingParam {0}>".format(self.name)


def group_key_for(definition):
    u"""The key of the GroupOption this definition sits in, so the table's
    dropdown lands on the right entry rather than on the first one."""
    by_key, by_id = _group_indexes()
    try:
        forge = definition.GetGroupTypeId()
    except Exception:
        forge = None
    if forge is not None:
        try:
            found = by_id.get((u"f", forge.TypeId))
            if found:
                return found
        except Exception:
            pass
    try:
        return by_id.get((u"l", u"{0}".format(definition.ParameterGroup)), u"")
    except Exception:
        return u""


def data_type_label(definition):
    u"""The spec's own label where the release offers one, and the raw
    enum name otherwise - either spelling lands on the same kind."""
    try:
        from Autodesk.Revit.DB import LabelUtils
        spec = definition.GetDataType()
        label = LabelUtils.GetLabelForSpec(spec)
        if label:
            return label
    except Exception:
        pass
    try:
        spec = definition.GetDataType()
        text = u"{0}".format(spec.TypeId)
        if text:
            # autodesk.spec.aec:length-2.0.0 to 'length'
            tail = text.split(u":")[-1].split(u"-")[0]
            if tail:
                return tail
    except Exception:
        pass
    try:
        return u"{0}".format(definition.ParameterType)
    except Exception:
        return u""


def _value_text(family_type, param):
    if family_type is None or param is None:
        return u""
    for method in (u"AsValueString", u"AsString"):
        try:
            value = getattr(family_type, method)(param)
            if value:
                return u"{0}".format(value)
        except Exception:
            continue
    for method in (u"AsInteger", u"AsDouble"):
        try:
            value = getattr(family_type, method)(param)
            if value is not None:
                return u"{0}".format(value)
        except Exception:
            continue
    return u""


def family_parameters(doc):
    out = []
    try:
        manager = doc.FamilyManager
        parameters = list(manager.Parameters)
    except Exception:
        return out
    try:
        current = manager.CurrentType
    except Exception:
        current = None
    for item in parameters:
        record = ExistingParam()
        record.param = item
        try:
            definition = item.Definition
            record.name = definition.Name
        except Exception:
            continue
        if not record.name:
            continue
        for attribute, target in ((u"IsShared", u"is_shared"),
                                  (u"IsInstance", u"is_instance"),
                                  (u"IsReporting", u"is_reporting"),
                                  (u"IsReadOnly", u"is_readonly"),
                                  (u"CanAssignFormula", u"can_have_formula")):
            try:
                setattr(record, target, bool(getattr(item, attribute)))
            except Exception:
                pass
        if record.is_shared:
            try:
                record.guid = u"{0}".format(item.GUID).lower()
            except Exception:
                record.guid = u""
        try:
            record.formula = item.Formula or u""
        except Exception:
            record.formula = u""
        try:
            # A built-in family parameter cannot be renamed, regrouped or
            # made an instance, so the table has to know which they are.
            record.is_builtin = bool(item.Id) and eid_value_of(item) < 0
        except Exception:
            record.is_builtin = False
        record.group_key = group_key_for(definition)
        option = group_by_key(record.group_key) if record.group_key else None
        record.group_label = option.label if option else u""
        record.data_type = data_type_label(definition)
        record.value_text = _value_text(current, item)
        out.append(record)
    out.sort(key=lambda row: fet_core.natural_key(row.name))
    return out


def eid_value_of(family_parameter):
    try:
        return fet_core.eid_value(family_parameter.Id)
    except Exception:
        return 0


def existing_parameters(doc):
    return family_parameters(doc)


def existing_parameter_index(doc):
    u"""Two indexes: by lowercased name and by lowercased GUID.  A shared
    parameter already in the family under a different name still has to be
    caught, and Revit matches shared parameters on GUID."""
    by_name = {}
    by_guid = {}
    for item in family_parameters(doc):
        by_name[item.name.lower()] = item
        if item.guid:
            by_guid[item.guid.lower()] = item
    return by_name, by_guid


# =========================================================================
# Materials, patterns, subcategories, annotation types
# =========================================================================

def _collect(doc, cls):
    try:
        return list(FilteredElementCollector(doc).OfClass(cls).ToElements())
    except Exception:
        return []


def materials(doc):
    out = []
    for item in _collect(doc, Material):
        try:
            out.append((item.Name, item.Id))
        except Exception:
            continue
    out.sort(key=lambda pair: fet_core.natural_key(pair[0]))
    return out


def material_names(doc):
    return [name for name, eid in materials(doc)]


def fill_patterns(doc):
    out = {}
    for item in _collect(doc, FillPatternElement):
        try:
            out[item.Name.lower()] = item.Id
        except Exception:
            continue
    return out


def line_patterns(doc):
    out = {}
    for item in _collect(doc, LinePatternElement):
        try:
            out[item.Name.lower()] = item.Id
        except Exception:
            continue
    # Solid is not a LinePatternElement - it is the invalid id.
    out[u"solid"] = ElementId.InvalidElementId
    return out


def _category(doc, name):
    member = bic(name)
    if member is None:
        return None
    try:
        return doc.Settings.Categories.get_Item(member)
    except Exception:
        return None


def lines_category(doc):
    return _category(doc, u"OST_Lines")


def own_category(doc):
    try:
        return doc.OwnerFamily.FamilyCategory
    except Exception:
        return None


def subcategory_names(category):
    out = []
    if category is None:
        return out
    try:
        for sub in category.SubCategories:
            try:
                out.append(sub.Name)
            except Exception:
                continue
    except Exception:
        return out
    out.sort(key=fet_core.natural_key)
    return out


def line_style_names(doc):
    return subcategory_names(lines_category(doc))


def family_subcategory_names(doc):
    return subcategory_names(own_category(doc))


def text_note_types(doc):
    out = []
    for item in _collect(doc, TextNoteType):
        try:
            out.append((item.Name, item.Id))
        except Exception:
            continue
    out.sort(key=lambda pair: fet_core.natural_key(pair[0]))
    return out


def dimension_types(doc):
    u"""Only the ones a family editor can usefully duplicate: a dimension
    type whose style is not linear or angular (a radial, an arc length)
    comes back too, and is left in the list with its style named."""
    out = []
    for item in _collect(doc, DimensionType):
        try:
            name = item.Name
        except Exception:
            continue
        if not name:
            continue
        style = u""
        try:
            style = u"{0}".format(item.StyleType)
        except Exception:
            style = u""
        out.append((name, item.Id, style))
    out.sort(key=lambda row: fet_core.natural_key(row[0]))
    return out


def arrowhead_names(doc):
    out = []
    member = bic(u"OST_Arrowheads")
    if member is None:
        return out
    try:
        collector = FilteredElementCollector(doc).OfCategory(member)
        collector = collector.WhereElementIsElementType()
        for item in collector.ToElements():
            try:
                out.append((item.Name, item.Id))
            except Exception:
                continue
    except Exception:
        return out
    out.sort(key=lambda pair: fet_core.natural_key(pair[0]))
    return out


# =========================================================================
# Reference planes and the active view
# =========================================================================

def reference_planes(doc):
    out = {}
    for item in _collect(doc, ReferencePlane):
        try:
            name = item.Name
        except Exception:
            continue
        if name:
            out[name] = item
    return out


PLAN_VIEWS = (u"FloorPlan", u"CeilingPlan", u"EngineeringPlan", u"AreaPlan")
ELEVATION_VIEWS = (u"Elevation", u"Section")


def view_kind(view):
    u"""'plan', 'elevation', or '' for anything a plane cannot be drawn in."""
    if view is None:
        return u""
    try:
        name = u"{0}".format(view.ViewType)
    except Exception:
        return u""
    if name in PLAN_VIEWS:
        return u"plan"
    if name in ELEVATION_VIEWS:
        return u"elevation"
    return u""


def active_view(uidoc):
    try:
        return uidoc.ActiveView
    except Exception:
        return None


def view_is_suitable(view, wanted):
    kind = view_kind(view)
    if not kind:
        return False, u"reference planes cannot be drawn in a {0} view".format(
            _view_type_text(view))
    if kind != wanted:
        return False, u"this layout needs a {0} view and the active view is a {1}".format(
            wanted, kind)
    return True, u""


def _view_type_text(view):
    try:
        return u"{0}".format(view.ViewType)
    except Exception:
        return u"3D or schedule"


# =========================================================================
# Other open models, and what can be harvested out of them
# =========================================================================

class OpenModel(object):
    def __init__(self, key, title, doc, is_current):
        self.key = key
        self.title = title
        self.doc = doc
        self.is_current = is_current


def open_documents(uiapp, current):
    u"""Every document open in this Revit session, the current one first.
    A linked model is not a Document you can read this way, so only what is
    genuinely open is offered rather than offered and then failing."""
    out = []
    try:
        documents = list(uiapp.Application.Documents)
    except Exception:
        documents = []
    for doc in documents:
        try:
            if doc.IsLinked:
                continue
        except Exception:
            pass
        try:
            title = doc.Title
        except Exception:
            continue
        same = False
        try:
            same = (current is not None and doc.Equals(current))
        except Exception:
            same = False
        out.append(OpenModel(title, title, doc, same))
    out.sort(key=lambda item: (0 if item.is_current else 1,
                               fet_core.natural_key(item.title)))
    return out


class ScanItem(object):
    u"""One thing found in a scanned model.

    depends carries the element ids the thing cannot arrive without - a
    material's appearance, thermal and structural assets and its fill
    patterns.  Handing them to CopyElements alongside the material is what
    stops it landing in the family as a flat grey colour with no asset
    behind it.
    """

    def __init__(self, kind, name, element_id, detail=u"", extra=None,
                 depends=None, asset_name=u"", asset_id=None):
        self.kind = kind
        self.name = name
        self.element_id = element_id
        self.detail = detail
        self.extra = extra or {}
        self.depends = depends or []
        self.asset_name = asset_name
        self.asset_id = asset_id

    def searchable(self):
        return u" ".join([self.name, self.detail])


def _colour_text(colour):
    try:
        if colour is None or not colour.IsValid:
            return u""
        return u"{0},{1},{2}".format(colour.Red, colour.Green, colour.Blue)
    except Exception:
        return u""


def valid_id(element_id):
    return element_id is not None and fet_core.eid_value(element_id) > 0


# What a material cannot arrive without.  The asset properties are first
# because they are the ones that carry the look of it; the pattern
# properties are spelled differently across 2024 to 2027, so every spelling
# is asked for and the ones that do not exist are skipped.
MATERIAL_ASSET_PROPERTIES = (u"AppearanceAssetId", u"ThermalAssetId",
                             u"StructuralAssetId")

MATERIAL_PATTERN_PROPERTIES = (u"SurfaceForegroundPatternId",
                               u"SurfaceBackgroundPatternId",
                               u"CutForegroundPatternId",
                               u"CutBackgroundPatternId",
                               u"SurfacePatternId", u"CutPatternId")


def material_dependencies(material):
    u"""Every element the material points at, deduplicated."""
    out = []
    seen = set()
    for attribute in MATERIAL_ASSET_PROPERTIES + MATERIAL_PATTERN_PROPERTIES:
        try:
            element_id = getattr(material, attribute)
        except Exception:
            continue
        if not valid_id(element_id):
            continue
        key = fet_core.eid_value(element_id)
        if key in seen:
            continue
        seen.add(key)
        out.append(element_id)
    return out


def appearance_asset(doc, material):
    u"""(name, id) of the material's appearance asset, or ('', None)."""
    try:
        element_id = material.AppearanceAssetId
    except Exception:
        return u"", None
    if not valid_id(element_id):
        return u"", None
    try:
        asset = doc.GetElement(element_id)
        return asset.Name, element_id
    except Exception:
        return u"", element_id


def appearance_assets(doc):
    u"""Every appearance asset in a document, by lowercased name."""
    out = {}
    try:
        from Autodesk.Revit.DB import AppearanceAssetElement
    except Exception:
        return out
    for item in _collect(doc, AppearanceAssetElement):
        try:
            out[item.Name.lower()] = item.Id
        except Exception:
            continue
    return out


def scan_materials(doc):
    out = []
    for item in _collect(doc, Material):
        try:
            name = item.Name
        except Exception:
            continue
        klass = u""
        try:
            klass = item.MaterialClass or u""
        except Exception:
            klass = u""
        colour = _colour_text(getattr(item, u"Color", None))
        asset_name, asset_id = appearance_asset(doc, item)
        detail = u"  ".join([bit for bit in (klass, colour) if bit])
        out.append(ScanItem(u"material", name, item.Id, detail,
                            {u"colour": colour, u"class": klass},
                            material_dependencies(item), asset_name, asset_id))
    out.sort(key=lambda row: fet_core.natural_key(row.name))
    return out


def _scan_subcategories(doc, category, scope, where):
    out = []
    if category is None:
        return out
    try:
        subs = list(category.SubCategories)
    except Exception:
        return out
    patterns = {}
    for item in _collect(doc, LinePatternElement):
        try:
            patterns[fet_core.eid_value(item.Id)] = item.Name
        except Exception:
            continue
    for sub in subs:
        try:
            name = sub.Name
        except Exception:
            continue
        weight = u""
        try:
            value = sub.GetLineWeight(GraphicsStyleType_projection())
            if value:
                weight = u"{0}".format(value)
        except Exception:
            weight = u""
        colour = _colour_text(getattr(sub, u"LineColor", None))
        pattern = u""
        try:
            pattern = patterns.get(
                fet_core.eid_value(sub.GetLinePatternId(
                    GraphicsStyleType_projection())), u"")
        except Exception:
            pattern = u""
        detail = u"  ".join([bit for bit in
                             (where, u"weight " + weight if weight else u"",
                              pattern, colour) if bit])
        out.append(ScanItem(u"linestyle", name, sub.Id, detail,
                            {u"weight": weight or u"1", u"colour": colour,
                             u"pattern": pattern, u"scope": scope}))
    out.sort(key=lambda row: fet_core.natural_key(row.name))
    return out


def GraphicsStyleType_projection():
    from Autodesk.Revit.DB import GraphicsStyleType
    return GraphicsStyleType.Projection


def scan_line_styles(doc):
    out = _scan_subcategories(doc, lines_category(doc), u"lines", u"Lines")
    try:
        own = doc.OwnerFamily.FamilyCategory
    except Exception:
        own = None
    if own is not None:
        out.extend(_scan_subcategories(doc, own, u"subcategory",
                                       u"family subcategory"))
    return out


def _type_size_mm(element, parameter_name):
    member = bip(parameter_name)
    if member is None:
        return u""
    try:
        parameter = element.get_Parameter(member)
        if parameter is None:
            return u""
        return u"{0:g}mm".format(fet_core.ft_to_mm(parameter.AsDouble()))
    except Exception:
        return u""


def scan_text_types(doc):
    out = []
    for name, element_id in text_note_types(doc):
        element = doc.GetElement(element_id)
        detail = _type_size_mm(element, u"TEXT_SIZE")
        out.append(ScanItem(u"text", name, element_id, detail))
    return out


def scan_dimension_types(doc):
    out = []
    for name, element_id, style in dimension_types(doc):
        element = doc.GetElement(element_id)
        detail = u"  ".join([bit for bit in
                             (style, _type_size_mm(element, u"TEXT_SIZE"))
                             if bit])
        out.append(ScanItem(u"dimension", name, element_id, detail))
    return out


SCANNERS = {
    u"material": scan_materials,
    u"linestyle": scan_line_styles,
    u"text": scan_text_types,
    u"dimension": scan_dimension_types,
}


def scan(doc, kind):
    scanner = SCANNERS.get(kind)
    if scanner is None or doc is None:
        return []
    return scanner(doc)


def existing_names(doc, kind):
    u"""What the family already carries, so a scan can say so rather than
    offering something that will come back as 'already there'."""
    if kind == u"material":
        return set([n.lower() for n in material_names(doc)])
    if kind == u"linestyle":
        names = set([n.lower() for n in line_style_names(doc)])
        names.update([n.lower() for n in family_subcategory_names(doc)])
        return names
    if kind == u"text":
        return set([n.lower() for n, eid in text_note_types(doc)])
    if kind == u"dimension":
        return set([n.lower() for n, eid, style in dimension_types(doc)])
    return set()


# =========================================================================
# Parameters a plane layout can drive
# =========================================================================

def length_parameters(doc):
    return length_parameters_from(family_parameters(doc))


def length_parameters_from(rows):
    u"""The family parameters a setting out dimension could be labelled
    with.  A dimension can only drive a length, so anything else is left
    out rather than offered and then refused.

    Takes an already read list: re-reading the whole family every time the
    standard planes page is opened is what made it hang for a second.
    """
    out = []
    for row in rows or []:
        if fet_core.data_kind(row.data_type) != fet_core.KIND_LENGTH:
            continue
        if row.is_reporting or row.formula:
            # A reporting parameter, or one driven by a formula, cannot be
            # driven by a dimension as well.
            continue
        out.append(row)
    return out


# =========================================================================
# Finding the view a layout has to be set out in
# =========================================================================

def views_of_kind(doc, kind):
    out = []
    try:
        collector = FilteredElementCollector(doc).OfClass(View)
    except Exception:
        return out
    for view in collector.ToElements():
        try:
            if view.IsTemplate:
                continue
        except Exception:
            continue
        if view_kind(view) != kind:
            continue
        out.append(view)
    return out


def find_layout_view(doc, kind, names):
    u"""The view Revit's own family templates use, by name, then any view
    of the right kind that also points the right way."""
    candidates = views_of_kind(doc, kind)
    wanted = [fet_core._as_text(n).lower() for n in names]
    for name in wanted:
        for view in candidates:
            try:
                if view.Name.lower() == name:
                    return view
            except Exception:
                continue
    for view in candidates:
        if view_points_the_right_way(view, kind):
            return view
    return None


def view_points_the_right_way(view, kind):
    try:
        direction = view.ViewDirection
    except Exception:
        return True
    if kind == u"plan":
        return abs(direction.Z) > 0.9
    return abs(direction.Y) > 0.9


# =========================================================================
# Is that really the same appearance asset?
#
# CopyPasteOptions can only answer a name clash with UseDestinationTypes,
# so a material copied into a family whose template already carries an
# appearance asset of the same name quietly ends up pointing at the
# FAMILY'S asset - same name, none of the properties.  The copy succeeds,
# nothing throws, and the material renders wrong.
#
# The only way to know is to compare what is actually in the two assets, so
# the rendering asset's whole property tree is flattened to a string and
# the two strings compared.
# =========================================================================

FINGERPRINT_DEPTH = 3

# Properties that identify the asset rather than describe it.  Two copies
# of the same appearance never agree on these - the thumbnail is a temp
# path with the process id in it, UIName follows the element name, and the
# GUIDs are minted per document - so comparing them makes a perfect copy
# read as a failure, and writing them across is pointless or harmful.
VOLATILE_PROPERTIES = set([
    u"thumbnail", u"uiname", u"versionguid", u"exchangeguid", u"assetlibid",
    u"revision", u"common_shared_asset", u"swatch", u"hidden",
])


# Properties that describe the SCHEMA rather than the look: which XML file
# draws the UI, what the asset type is called.  They are read only, so they
# never write across, and comparing them makes a perfectly transferred look
# read as a mismatch.
SCHEMA_PROPERTIES = set([
    u"advanceduidefinition", u"uidefinition", u"implementationgeneric",
    u"implementationmentalray", u"implementationogs",
    u"implementationpreview", u"baseschema", u"schemaversion", u"assettype",
    u"localname", u"localtype", u"version", u"mode", u"keyword",
    u"category", u"patternoffset",
])


def is_volatile(name):
    u"""Never written across, and never compared."""
    return fet_core._as_text(name).strip().lower() in VOLATILE_PROPERTIES


def is_ignored(name):
    u"""Never compared.  A schema property is read only, so a look that
    transferred perfectly would otherwise still read back as different."""
    text = fet_core._as_text(name).strip().lower()
    return text in VOLATILE_PROPERTIES or text in SCHEMA_PROPERTIES


def asset_base_schema(asset):
    u"""'GenericSchema'.  Read from the asset's own BaseSchema property
    first: a library asset's Name is its own name - 'Aluminium - Anodised'
    - not its schema, which is why matching on Name found nothing in a
    library of three thousand."""
    if asset is None:
        return u""
    try:
        prop = asset.FindByName(u"BaseSchema")
        if prop is not None:
            text = u"{0}".format(prop.Value).strip()
            if text:
                return text
    except Exception:
        pass
    return asset_schema(asset)


def asset_properties(asset):
    u"""The AssetProperty children of an Asset, however this release lets
    them be reached."""
    if asset is None:
        return []
    try:
        return [item for item in asset]
    except Exception:
        pass
    try:
        size = asset.Size
    except Exception:
        return []
    out = []
    for index in range(size):
        got = None
        try:
            got = asset[index]
        except Exception:
            try:
                got = asset.Get(index)
            except Exception:
                got = None
        if got is not None:
            out.append(got)
    return out


def _property_text(prop, depth):
    bits = []
    try:
        bits.append(u"{0}".format(prop.Name))
    except Exception:
        pass
    got = False
    try:
        bits.append(u"{0}".format(prop.Value))
        got = True
    except Exception:
        got = False
    if not got:
        for getter in (u"GetValueAsDoubles", u"GetValueAsInts",
                       u"GetValueAsStrings", u"GetValueAsBools"):
            try:
                values = getattr(prop, getter)()
                bits.append(u",".join([u"{0}".format(v) for v in values]))
                got = True
                break
            except Exception:
                continue
    if not got:
        try:
            bits.append(u"{0}".format(prop.Type))
        except Exception:
            pass
    # A texture hangs off its property as a connected asset, and two
    # materials that differ only in their bitmap have identical scalars.
    try:
        if depth < FINGERPRINT_DEPTH and prop.NumberOfConnectedProperties > 0:
            connected = prop.GetSingleConnectedAsset()
            if connected is not None:
                bits.append(u"<" + asset_fingerprint(connected, depth + 1) + u">")
    except Exception:
        pass
    return u"=".join(bits)


def asset_fingerprint(asset, depth=0):
    u"""The property tree only.  The root asset's own name is left out on
    purpose: the same appearance rebuilt under a different element name is
    the same appearance, and including the name would make every rebuild
    read as a failure."""
    if asset is None:
        return u""
    parts = []
    if depth:
        try:
            parts.append(u"{0}".format(asset.Name))
        except Exception:
            parts.append(u"?")
    for prop in asset_properties(asset):
        try:
            if is_ignored(prop.Name):
                continue
        except Exception:
            pass
        parts.append(_property_text(prop, depth))
    return u"|".join(parts)


def element_fingerprint(doc, element_id):
    u"""The fingerprint of the appearance asset an id points at."""
    if not valid_id(element_id) or doc is None:
        return u""
    try:
        element = doc.GetElement(element_id)
    except Exception:
        return u""
    if element is None:
        return u""
    try:
        return asset_fingerprint(element.GetRenderingAsset())
    except Exception:
        return u""


def same_asset(left, right):
    u"""Two empty fingerprints are not evidence of sameness - a release
    that will not give up the rendering asset would otherwise read as
    'these match' and the wrong asset would be left attached."""
    if not left or not right:
        return False
    return left == right


def document_title(doc):
    try:
        title = doc.Title
    except Exception:
        return u"the other model"
    for suffix in (u".rfa", u".rvt", u".RFA", u".RVT"):
        if title.endswith(suffix):
            return title[:-len(suffix)]
    return title


def rendering_asset(element):
    try:
        return element.GetRenderingAsset()
    except Exception:
        return None


def rendering_asset_by_id(doc, element_id):
    if not valid_id(element_id) or doc is None:
        return None
    try:
        return rendering_asset(doc.GetElement(element_id))
    except Exception:
        return None


def asset_schema(asset):
    u"""'Generic', 'Metal', and so on.  Two assets of different schemas
    have no properties in common, so nothing can be written across."""
    if asset is None:
        return u""
    try:
        return u"{0}".format(asset.Name)
    except Exception:
        return u""


def library_assets(app, schema):
    u"""The appearance assets Revit ships, by SCHEMA.  Creating a new asset
    element out of one of these is the route that reliably produces an
    asset of the same shape as the source, which is what makes the
    source's property names mean anything in the family."""
    if not schema:
        return []
    out = []
    try:
        from Autodesk.Revit.DB.Visual import AssetType
        assets = app.GetAssets(AssetType.Appearance)
    except Exception:
        return out
    wanted = fet_core._as_text(schema).strip().lower()
    for asset in assets or []:
        try:
            if asset_base_schema(asset).strip().lower() == wanted:
                out.append(asset)
        except Exception:
            continue
        if len(out) > 3:
            break
    return out


def family_asset_of_schema(doc, schema):
    u"""An appearance asset element ALREADY in the family built on the same
    schema.  A family template carries dozens of them, and duplicating one
    is the route that works when nothing will cross from the other
    document."""
    if not schema:
        return None
    wanted = fet_core._as_text(schema).strip().lower()
    try:
        from Autodesk.Revit.DB import AppearanceAssetElement
    except Exception:
        return None
    for item in _collect(doc, AppearanceAssetElement):
        try:
            found = asset_base_schema(rendering_asset(item))
        except Exception:
            continue
        if found.strip().lower() == wanted:
            return item.Id
    return None


# =========================================================================
# Describing what is actually there, for the diagnostics
# =========================================================================

def describe_property(prop, trace, indent, depth=0):
    name = u"?"
    try:
        name = prop.Name
    except Exception:
        pass
    kind = u""
    try:
        kind = u"{0}".format(prop.Type)
    except Exception:
        kind = u""
    value = u"<no readable value>"
    for getter in (u"GetValueAsDoubles", u"GetValueAsInts",
                   u"GetValueAsBools", u"GetValueAsStrings"):
        try:
            value = u",".join([u"{0}".format(v) for v in getattr(prop, getter)()])
            break
        except Exception:
            continue
    if value == u"<no readable value>":
        try:
            value = u"{0}".format(prop.Value)
        except Exception:
            pass
    connected = 0
    try:
        connected = prop.NumberOfConnectedProperties
    except Exception:
        connected = 0
    trace.note(u"{0} [{1}] = {2}{3}".format(
        name, kind, fet_core.short(value, 160),
        u"   (+{0} connected)".format(connected) if connected else u""),
        indent)
    if connected and depth < FINGERPRINT_DEPTH:
        try:
            child = prop.GetSingleConnectedAsset()
        except Exception:
            child = None
        if child is not None:
            describe_asset(child, trace, indent + 1, depth + 1)


def describe_asset(asset, trace, indent=1, depth=0):
    if asset is None:
        trace.note(u"<no rendering asset>", indent)
        return
    for label, attribute in ((u"schema", u"Name"), (u"title", u"Title"),
                             (u"library", u"LibraryName"),
                             (u"type", u"AssetType")):
        try:
            trace.note(u"{0}: {1}".format(label, getattr(asset, attribute)),
                       indent)
        except Exception:
            trace.note(u"{0}: <not readable>".format(label), indent)
    properties = asset_properties(asset)
    trace.note(u"{0} properties".format(len(properties)), indent)
    for prop in properties:
        describe_property(prop, trace, indent + 1, depth)


def describe_material(doc, material, trace, indent=1):
    if material is None:
        trace.note(u"<not in this document>", indent)
        return
    for label, attribute in ((u"name", u"Name"), (u"class", u"MaterialClass"),
                             (u"category", u"MaterialCategory")):
        try:
            trace.note(u"{0}: {1}".format(label, getattr(material, attribute)),
                       indent)
        except Exception:
            pass
    try:
        trace.note(u"id: {0}".format(fet_core.eid_value(material.Id)), indent)
    except Exception:
        pass
    try:
        trace.note(u"colour: {0}".format(_colour_text(material.Color)), indent)
    except Exception:
        pass
    for attribute in MATERIAL_ASSET_PROPERTIES + MATERIAL_PATTERN_PROPERTIES:
        try:
            element_id = getattr(material, attribute)
        except Exception:
            trace.note(u"{0}: <not on this release>".format(attribute),
                       indent)
            continue
        trace.note(u"{0}: {1}".format(attribute,
                                      fet_core.eid_value(element_id)), indent)
    asset_name, asset_id = appearance_asset(doc, material)
    trace.note(u"appearance asset element: {0}".format(asset_name or u"<none>"),
               indent)
    try:
        element = doc.GetElement(material.AppearanceAssetId)
        trace.note(u"appearance element class: {0}".format(
            type(element).__name__), indent)
    except Exception:
        pass
    describe_asset(rendering_asset_by_id(doc, asset_id), trace, indent + 1)


def describe_environment(doc, source_doc, trace):
    import sys
    trace.pair(u"tool version", fet_core.__version__)
    trace.pair(u"python", sys.version.replace(u"\n", u" "))
    try:
        app = doc.Application
        trace.pair(u"Revit", u"{0}  build {1}  {2}".format(
            app.VersionNumber, app.VersionBuild, app.VersionName))
        trace.pair(u"language", app.Language)
    except Exception:
        trace.pair(u"Revit", u"<not readable>")
    trace.pair(u"family", u"{0}  ({1})".format(
        family_name(doc), family_category_name(doc)))
    trace.pair(u"source model", document_title(source_doc))
    try:
        from Autodesk.Revit.DB.Visual import AssetType
        assets = doc.Application.GetAssets(AssetType.Appearance)
        trace.pair(u"appearance assets in Revit's library", len(assets))
    except Exception:
        trace.pair(u"appearance assets in Revit's library",
                   u"<GetAssets is not available on this release>")
    trace.pair(u"appearance asset elements already in the family",
               len(appearance_assets(doc)))


# =========================================================================
# What can be flexed
# =========================================================================

# The kinds a flex run can drive.  A material or a family type cannot be
# stepped through a range, and a yes/no has only two values - which the
# run handles as 0 and 1 rather than as a range.
FLEXABLE_KINDS = (fet_core.KIND_LENGTH, fet_core.KIND_AREA_VOLUME,
                  fet_core.KIND_ANGLE, fet_core.KIND_NUMBER,
                  fet_core.KIND_INTEGER, fet_core.KIND_FLOW)


def numeric_value(family_type, param):
    u"""The parameter's current value as a plain number, in whatever unit
    Revit holds it - the flex run never converts, it only puts back
    exactly what it read."""
    if family_type is None or param is None:
        return None
    for method in (u"AsDouble", u"AsInteger"):
        try:
            value = getattr(family_type, method)(param)
            if value is not None:
                return value
        except Exception:
            continue
    return None


class FlexParam(object):
    def __init__(self, record, value):
        self.record = record
        self.value = value

    @property
    def name(self):
        return self.record.name

    @property
    def data_type(self):
        return self.record.data_type

    @property
    def is_instance(self):
        return self.record.is_instance


def flexable_parameters(doc):
    u"""The parameters a flex run can drive, with what each currently
    holds.  A parameter driven by a formula, a reporting parameter and a
    read only one are all left out - setting those is refused, and
    offering them would fill the report with noise rather than faults."""
    out = []
    try:
        manager = doc.FamilyManager
        current = manager.CurrentType
    except Exception:
        return out
    for record in family_parameters(doc):
        if record.formula or record.is_reporting or record.is_readonly:
            continue
        if fet_core.data_kind(record.data_type) not in FLEXABLE_KINDS:
            continue
        value = numeric_value(current, record.param)
        if value is None:
            continue
        out.append(FlexParam(record, value))
    return out


def family_types(doc):
    u"""[(name, FamilyType)], the current one first."""
    out = []
    try:
        manager = doc.FamilyManager
        types = list(manager.Types)
        current = manager.CurrentType
    except Exception:
        return out
    current_name = u""
    try:
        current_name = current.Name if current else u""
    except Exception:
        current_name = u""
    for item in types:
        try:
            name = item.Name
        except Exception:
            continue
        out.append((name, item))
    out.sort(key=lambda pair: (0 if pair[0] == current_name else 1,
                               fet_core.natural_key(pair[0])))
    return out
