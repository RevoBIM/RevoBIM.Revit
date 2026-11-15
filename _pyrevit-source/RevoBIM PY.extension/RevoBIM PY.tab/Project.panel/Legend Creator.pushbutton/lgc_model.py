# -*- coding: utf-8 -*-

"""Legend Creator - reading the model.

Element helpers, the family scan, phases, text types, seed legends, view
template filters and the duct and pipe systems in use. Nothing here writes.
"""

from pyrevit import DB

from lgc_logic import (BLOCKED_CATEGORIES, DEFAULT_NAME_PARAM,
                       NAME_FAMILY_TYPE, NAME_TYPE_NAME, channel,
                       classify_pipe, decode_colour_int, group_order,
                       join_label, phase_verdict, rgb_hex, tidy_label,
                       usable_phase)
from lgc_core import eid_value, err_text, log, swallowed

# The active document, bound by lgc_app.bind_document() at the start of every
# run - never captured at import, which pyRevit may cache across runs and
# models.
doc = None


def element_name(element):
    try:
        return DB.Element.Name.GetValue(element)
    except Exception:
        try:
            return element.Name
        except Exception:
            swallowed()
            return ''


def family_name(element_type):
    try:
        return element_type.FamilyName or ''
    except Exception:
        swallowed()
        return ''


def family_type_label(element_type):
    return ' : '.join([p for p in (family_name(element_type),
                                   element_name(element_type)) if p])


def param_text(element_type, param_name):
    """Read the nominated parameter off a type, with sensible fallbacks."""
    if param_name == NAME_TYPE_NAME:
        return element_name(element_type)
    if param_name == NAME_FAMILY_TYPE:
        return family_type_label(element_type)

    try:
        param = element_type.LookupParameter(param_name)
    except Exception:
        swallowed()
        param = None

    if param is None and param_name == DEFAULT_NAME_PARAM:
        try:
            param = element_type.get_Parameter(
                DB.BuiltInParameter.ALL_MODEL_DESCRIPTION)
        except Exception:
            swallowed()
            param = None

    if param is not None and param.HasValue:
        try:
            if param.StorageType == DB.StorageType.String:
                value = param.AsString()
            else:
                value = param.AsValueString()
        except Exception:
            swallowed()
            value = None
        if value and value.strip():
            return value.strip()

    return family_type_label(element_type)


def category_id_set(names):
    ids = set()
    for name in names:
        builtin = getattr(DB.BuiltInCategory, name, None)
        if builtin is None:
            continue          # category absent on this Revit version
        try:
            ids.add(int(builtin))
        except Exception:
            swallowed()
    return ids


# ---------------------------------------------------------------------------
# Model interrogation
# ---------------------------------------------------------------------------
class CategoryInfo(object):
    """A model category plus the type ids of that category actually placed."""

    def __init__(self, category, type_ids):
        self.category = category
        self.name = category.Name
        self.type_ids = type_ids

    @property
    def count(self):
        return len(self.type_ids)


def project_phases():
    """(name, ElementId) for every phase, in project order."""
    phases = []
    try:
        for phase in doc.Phases:
            phases.append((element_name(phase), phase.Id))
    except Exception:
        swallowed()
    return phases


def element_phase_id(element):
    try:
        param = element.get_Parameter(DB.BuiltInParameter.PHASE_CREATED)
    except Exception:
        swallowed()
        return None
    if param is None or not param.HasValue:
        return None
    try:
        return param.AsElementId()
    except Exception:
        swallowed()
        return None


def collect_used_types(phase_id=None):
    """CategoryInfo objects for every usable model category in use.

    phase_id None means every phase. Otherwise only elements whose Phase
    Created matches are counted - an element with no phase parameter at all
    is left out, since it cannot belong to the phase asked for.
    """
    buckets = {}
    seen = set()
    blocked = category_id_set(BLOCKED_CATEGORIES)
    raw_phase = eid_value(phase_id) if phase_id is not None else None
    want_phase = usable_phase(raw_phase)
    if phase_id is not None and want_phase is None:
        # A real phase id is positive. Anything else means the id could not
        # be read, and filtering on it would keep exactly the elements that
        # have no phase at all - the opposite of what was asked.
        log(u'phase id unreadable ({0!r}, type {1}) - listing every phase '
            u'instead'.format(phase_id, type(phase_id).__name__))
    counts = {'scanned': 0, 'no phase': 0, 'other phase': 0}

    collector = DB.FilteredElementCollector(doc)\
                  .WhereElementIsNotElementType()\
                  .WhereElementIsViewIndependent()

    for element in collector:
        counts['scanned'] += 1
        if want_phase is not None:
            on_phase = element_phase_id(element)
            verdict = phase_verdict(
                want_phase, eid_value(on_phase) if on_phase is not None
                else None)
            if verdict != 'keep':
                counts[verdict] += 1
                continue

        try:
            type_id = element.GetTypeId()
        except Exception:
            swallowed()
            continue
        if type_id is None or type_id == DB.ElementId.InvalidElementId:
            continue

        key = eid_value(type_id)
        if key in seen:
            continue
        seen.add(key)

        element_type = doc.GetElement(type_id)
        if element_type is None:
            continue

        category = element_type.Category
        if category is None or category.CategoryType != DB.CategoryType.Model:
            continue

        cat_key = eid_value(category.Id)
        if cat_key >= 0:            # subcategory or non built-in
            continue
        if cat_key in blocked:      # cannot be a legend component
            continue

        bucket = buckets.setdefault(cat_key, {'cat': category, 'ids': []})
        bucket['ids'].append(type_id)

    infos = []
    for bucket in buckets.values():
        ids = sorted(bucket['ids'],
                     key=lambda i: (family_name(doc.GetElement(i)).lower(),
                                    element_name(doc.GetElement(i)).lower()))
        infos.append(CategoryInfo(bucket['cat'], ids))

    log(u'family scan (phase id {0}): {1} element(s) read, {2} with no '
        u'phase, {3} on another phase -> {4} type(s) in {5} categor(ies)'
        .format(want_phase if want_phase is not None else u'all',
                counts['scanned'], counts['no phase'], counts['other phase'],
                sum(i.count for i in infos), len(infos)))
    return sorted(infos, key=lambda i: i.name.lower())


def string_parameter_names(infos, limit=400):
    """Parameter names worth offering as the description source.

    Sampled across the collected types rather than read from every one, since
    a large model can hold thousands and the list only needs the names.
    """
    names = set()
    sampled = 0
    for info in infos:
        for type_id in info.type_ids:
            if sampled >= limit:
                break
            element_type = doc.GetElement(type_id)
            if element_type is None:
                continue
            sampled += 1
            try:
                params = element_type.Parameters
            except Exception:
                swallowed()
                continue
            for param in params:
                try:
                    if param.StorageType != DB.StorageType.String:
                        continue
                    definition = param.Definition
                    if definition is None:
                        continue
                    names.add(definition.Name)
                except Exception:
                    swallowed()
                    continue
    return sorted(names, key=lambda n: n.lower())


def text_note_types():
    """(name, ElementId) for every text note type, sorted."""
    types = []
    for text_type in DB.FilteredElementCollector(doc)\
                       .OfClass(DB.TextNoteType):
        types.append((element_name(text_type), text_type.Id))
    return sorted(types, key=lambda t: t[0].lower())


def default_text_type_id():
    try:
        type_id = doc.GetDefaultElementTypeId(DB.ElementTypeGroup.TextNoteType)
        if type_id and type_id != DB.ElementId.InvalidElementId:
            return type_id
    except Exception:
        swallowed()
    return DB.FilteredElementCollector(doc)\
             .OfClass(DB.TextNoteType).FirstElementId()


def find_seed_legend_view():
    """Any legend view. The system tab draws filled regions and text, which
    need no legend component, so it has the lighter requirement."""
    for view in DB.FilteredElementCollector(doc).OfClass(DB.View):
        try:
            if view.ViewType == DB.ViewType.Legend and not view.IsTemplate:
                return view
        except Exception:
            swallowed()
            continue
    return None


def find_seed_legend():
    """A legend view and a legend component inside it, to clone from."""
    components = DB.FilteredElementCollector(doc)\
                   .OfCategory(DB.BuiltInCategory.OST_LegendComponents)\
                   .WhereElementIsNotElementType()\
                   .ToElements()
    for component in components:
        view = doc.GetElement(component.OwnerViewId)
        if view is not None and view.ViewType == DB.ViewType.Legend:
            return view, component
    return None, None


def taken_view_names():
    return set(element_name(v) for v in
               DB.FilteredElementCollector(doc).OfClass(DB.View))


# ---------------------------------------------------------------------------
# System Colour Legend - reading filters out of a view template
# ---------------------------------------------------------------------------
class LegendEntry(object):
    """One legend row: where it came from, its label and its colour."""

    def __init__(self, source_id, source_name, label, colour, pattern_id):
        self.source_id = source_id
        self.source_name = source_name
        self.label = label
        self.colour = colour            # (r, g, b) or None
        self.pattern_id = pattern_id    # ElementId or None
        self.key = label                # what a line style is named after
        self.group = ''                 # classification, where one applies

    def hex_colour(self):
        return rgb_hex(self.colour)


def view_templates():
    """(name, View) for every view template, sorted by name."""
    found = []
    for view in DB.FilteredElementCollector(doc).OfClass(DB.View):
        try:
            if view.IsTemplate:
                found.append((element_name(view), view))
        except Exception:
            swallowed()
            continue
    return sorted(found, key=lambda t: t[0].lower())


def filter_category_ids(filter_element):
    ids = set()
    try:
        for cat_id in filter_element.GetCategories():
            ids.add(eid_value(cat_id))
    except Exception:
        swallowed()
    return ids


def rule_values(filter_element):
    """The string values a filter's rules test for.

    Revit moved this API about: GetRules was deprecated for GetElementFilter,
    and the rule classes differ by release, so every route is tried and the
    first that yields something wins.
    """
    values = []

    def take(rule):
        for attr in ('RuleString', 'RuleValue'):
            try:
                value = getattr(rule, attr)
            except Exception:
                swallowed()
                continue
            if value is None:
                continue
            text = u'{0}'.format(value).strip()
            if text and text not in values:
                values.append(text)
                return

    def walk(element_filter, depth=0):
        if element_filter is None or depth > 6:
            return
        try:
            for rule in element_filter.GetRules():
                take(rule)
        except Exception:
            swallowed()
        try:
            for child in element_filter.GetFilters():
                walk(child, depth + 1)
        except Exception:
            swallowed()

    try:
        walk(filter_element.GetElementFilter())
    except Exception:
        swallowed()

    if not values:
        try:
            for rule in filter_element.GetRules():
                take(rule)
        except Exception:
            swallowed()

    return values


def override_colour(overrides):
    """The colour a filter paints with, preferring the surface fill."""
    names = ['SurfaceForegroundPatternColor', 'ProjectionFillColor',
             'CutForegroundPatternColor', 'SurfaceBackgroundPatternColor',
             'ProjectionLineColor', 'CutLineColor']
    for name in names:
        try:
            colour = getattr(overrides, name)
        except Exception:
            swallowed()
            continue
        try:
            if colour is not None and colour.IsValid:
                # Plain ints from here on - see channel().
                return (channel(colour.Red), channel(colour.Green),
                        channel(colour.Blue))
        except Exception:
            swallowed()
            continue
    return None


def override_pattern(overrides):
    names = ['SurfaceForegroundPatternId', 'ProjectionFillPatternId',
             'CutForegroundPatternId', 'SurfaceBackgroundPatternId']
    for name in names:
        try:
            pattern_id = getattr(overrides, name)
        except Exception:
            swallowed()
            continue
        if pattern_id is not None and \
                pattern_id != DB.ElementId.InvalidElementId and \
                eid_value(pattern_id) > 0:
            return pattern_id
    return None


def used_duct_system_type_ids():
    """Type ids of the duct systems actually used in the model.

    Two routes, unioned. MechanicalSystem elements are the direct answer but
    only exist where Revit has formed a system; ducts and terminals also name
    their system type on a parameter, which covers the rest.
    """
    ids = {}                 # value -> the ElementId Revit gave us

    mechanical = getattr(DB, 'Mechanical', None)
    system_class = getattr(mechanical, 'MechanicalSystem', None) \
        if mechanical else None
    if system_class is not None:
        try:
            for system in DB.FilteredElementCollector(doc)\
                            .OfClass(system_class):
                type_id = system.GetTypeId()
                if type_id and type_id != DB.ElementId.InvalidElementId:
                    ids[eid_value(type_id)] = type_id
        except Exception:
            swallowed()

    log(u'duct systems: {0} type(s) from formed systems'.format(len(ids)))
    param = getattr(DB.BuiltInParameter, 'RBS_DUCT_SYSTEM_TYPE_PARAM', None)
    if param is not None:
        for name in ('OST_DuctCurves', 'OST_FlexDuctCurves', 'OST_DuctFitting',
                     'OST_DuctAccessory', 'OST_DuctTerminal'):
            builtin = getattr(DB.BuiltInCategory, name, None)
            if builtin is None:
                continue
            try:
                collector = DB.FilteredElementCollector(doc)\
                              .OfCategory(builtin)\
                              .WhereElementIsNotElementType()
            except Exception:
                swallowed()
                continue
            for element in collector:
                try:
                    value = element.get_Parameter(param)
                except Exception:
                    swallowed()
                    continue
                if value is None or not value.HasValue:
                    continue
                try:
                    type_id = value.AsElementId()
                except Exception:
                    swallowed()
                    continue
                if type_id and type_id != DB.ElementId.InvalidElementId:
                    ids[eid_value(type_id)] = type_id
    log(u'duct systems: {0} type(s) in use after the parameter scan'.format(len(ids)))
    return ids


def system_colour(system_type):
    """The line colour from a system type's Graphic Overrides.

    MEPSystemType exposes it as LineColor on the releases that have it; where
    it does not, the same value is readable off the parameter, stored as a
    packed integer. Both are tried before giving up.
    """
    for attribute in ('LineColor', 'Color'):
        try:
            colour = getattr(system_type, attribute)
        except Exception:
            swallowed()
            continue
        try:
            if colour is not None and colour.IsValid:
                return (channel(colour.Red), channel(colour.Green),
                        channel(colour.Blue))
        except Exception:
            swallowed()
            continue

    try:
        params = system_type.Parameters
    except Exception:
        swallowed()
        return None
    for param in params:
        try:
            definition = param.Definition
            if definition is None:
                continue
            name = definition.Name.lower()
            if 'colour' not in name and 'color' not in name:
                continue
            if param.StorageType != DB.StorageType.Integer:
                continue
            decoded = decode_colour_int(param.AsInteger())
            if decoded:
                return decoded
        except Exception:
            swallowed()
            continue
    return None


def system_key(system_type):
    """The short name a line style is built from.

    The abbreviation where there is one - LEG_PIPE_SVP reads far better than
    the full label - falling back to the type name.
    """
    builtin = getattr(DB.BuiltInParameter, 'RBS_SYSTEM_ABBREVIATION_PARAM',
                      None)
    if builtin is not None:
        try:
            param = system_type.get_Parameter(builtin)
            if param is not None and param.HasValue:
                value = param.AsString()
                if value and value.strip():
                    return value.strip()
        except Exception:
            swallowed()
    return element_name(system_type)


def system_label(system_type):
    """Abbreviation, then ' - ', then Description. IA - INTAKE AIR."""
    def read(builtin_name, fallback_names):
        builtin = getattr(DB.BuiltInParameter, builtin_name, None)
        if builtin is not None:
            try:
                param = system_type.get_Parameter(builtin)
                if param is not None and param.HasValue:
                    value = param.AsString()
                    if value and value.strip():
                        return value.strip()
            except Exception:
                swallowed()
        for name in fallback_names:
            try:
                param = system_type.LookupParameter(name)
            except Exception:
                swallowed()
                continue
            if param is not None and param.HasValue:
                try:
                    value = param.AsString()
                except Exception:
                    swallowed()
                    continue
                if value and value.strip():
                    return value.strip()
        return ''

    abbreviation = read('RBS_SYSTEM_ABBREVIATION_PARAM', ['Abbreviation'])
    description = read('ALL_MODEL_DESCRIPTION', ['Description'])

    return join_label(abbreviation, description, element_name(system_type))


def read_duct_systems(kind):
    """Entries for every duct system type in use, with its override colour."""
    entries = []
    notes = []

    used = used_duct_system_type_ids()
    if not used:
        return entries, ['no ducts in this model name a duct system type']

    for type_id in used.values():
        system_type = doc.GetElement(type_id)
        if system_type is None:
            continue
        name = element_name(system_type)
        colour = system_colour(system_type)
        if colour is None:
            notes.append('{0} has no graphic override colour - shown grey'
                         .format(name))
        entry = LegendEntry(system_type.Id, name, system_label(system_type),
                            colour, None)
        entry.key = system_key(system_type)
        log(u'   duct type {0}: label "{1}", colour {2}'.format(
            name, entry.label, entry.colour))
        entries.append(entry)

    entries.sort(key=lambda e: e.label.lower())
    return entries, notes


def used_pipe_system_type_ids():
    """Type ids of the pipe systems actually used, by the same two routes
    as ducts: formed systems, plus the type parameter on the pipes."""
    ids = {}                 # value -> the ElementId Revit gave us

    plumbing = getattr(DB, 'Plumbing', None)
    system_class = getattr(plumbing, 'PipingSystem', None) if plumbing else None
    if system_class is not None:
        try:
            for system in DB.FilteredElementCollector(doc)\
                            .OfClass(system_class):
                type_id = system.GetTypeId()
                if type_id and type_id != DB.ElementId.InvalidElementId:
                    ids[eid_value(type_id)] = type_id
        except Exception:
            swallowed()

    log(u'pipe systems: {0} type(s) from formed systems'.format(len(ids)))
    param = getattr(DB.BuiltInParameter, 'RBS_PIPING_SYSTEM_TYPE_PARAM', None)
    if param is not None:
        for name in ('OST_PipeCurves', 'OST_FlexPipeCurves', 'OST_PipeFitting',
                     'OST_PipeAccessory'):
            builtin = getattr(DB.BuiltInCategory, name, None)
            if builtin is None:
                continue
            try:
                collector = DB.FilteredElementCollector(doc)\
                              .OfCategory(builtin)\
                              .WhereElementIsNotElementType()
            except Exception:
                swallowed()
                continue
            for element in collector:
                try:
                    value = element.get_Parameter(param)
                except Exception:
                    swallowed()
                    continue
                if value is None or not value.HasValue:
                    continue
                try:
                    type_id = value.AsElementId()
                except Exception:
                    swallowed()
                    continue
                if type_id and type_id != DB.ElementId.InvalidElementId:
                    ids[eid_value(type_id)] = type_id
    log(u'pipe systems: {0} type(s) in use after the parameter scan'.format(len(ids)))
    return ids


def pipe_group_name(system_type):
    """The classification group a pipe system belongs to.

    Read as text and matched on keywords, because the PipeSystemType members
    are not named consistently across releases - DomesticColdWater,
    FireProtectWet and so on - and a keyword survives that.
    """
    text = ''
    try:
        text = u'{0}'.format(system_type.SystemClassification).lower()
    except Exception:
        swallowed()
    if not text:
        param = getattr(DB.BuiltInParameter, 'RBS_SYSTEM_CLASSIFICATION_PARAM',
                        None)
        if param is not None:
            try:
                value = system_type.get_Parameter(param)
                if value is not None and value.HasValue:
                    text = (value.AsString() or
                            value.AsValueString() or '').lower()
            except Exception:
                swallowed()
    if not text:
        text = element_name(system_type).lower()

    group_found = classify_pipe(text)
    log(u'   {0}: classification "{1}" -> {2}'.format(
        element_name(system_type), text, group_found))
    return group_found


def read_pipe_systems(kind):
    """Entries for every pipe system type in use, tagged with their group."""
    entries = []
    notes = []

    used = used_pipe_system_type_ids()
    if not used:
        return entries, ['no pipes in this model name a piping system type']

    for type_id in used.values():
        system_type = doc.GetElement(type_id)
        if system_type is None:
            continue
        name = element_name(system_type)
        colour = system_colour(system_type)
        if colour is None:
            notes.append('{0} has no graphic override colour - shown grey'
                         .format(name))
        entry = LegendEntry(system_type.Id, name, system_label(system_type),
                            colour, None)
        entry.key = system_key(system_type)
        entry.group = pipe_group_name(system_type)
        log(u'   pipe type {0}: label "{1}", colour {2}, group {3}'.format(
            name, entry.label, colour, entry.group))
        entries.append(entry)

    entries.sort(key=lambda e: (group_order(e.group), e.label.lower()))
    return entries, notes


def matching_filter_count(template, kind):
    """How many filters on a template this legend kind would use - the same
    category and name test read_template_filters applies, without reading
    any colours, so every template can be checked when the list is filled."""
    wanted = category_id_set(kind['categories'])
    token = (kind['name_token'] or '').lower()
    count = 0
    try:
        filter_ids = list(template.GetFilters())
    except Exception:
        swallowed()
        return 0
    for filter_id in filter_ids:
        element = doc.GetElement(filter_id)
        if element is None:
            continue
        if wanted and not (filter_category_ids(element) & wanted):
            continue
        if token and token not in element_name(element).lower():
            continue
        count += 1
    return count


def read_template_filters(template, kind):
    """Filters on the template matching the kind's categories and token.

    Returns (entries, notes). A filter with no colour override is still
    returned, flagged in notes, rather than dropped without explanation.
    """
    entries = []
    notes = []
    if template is None:
        return entries, ['view template not found']

    wanted = category_id_set(kind['categories'])
    token = (kind['name_token'] or '').lower()

    try:
        filter_ids = list(template.GetFilters())
    except Exception as err:
        return entries, ['this template exposes no filters: {0}'.format(
            err_text(err))]

    log(u'template "{0}": {1} filter(s); keeping those on {2} named "{3}"'
        .format(element_name(template), len(filter_ids),
                u'/'.join(c.replace('OST_', '') for c in kind['categories']),
                token))
    for filter_id in filter_ids:
        filter_element = doc.GetElement(filter_id)
        if filter_element is None:
            log(u'   filter id {0}: no element'.format(eid_value(filter_id)))
            continue
        name = element_name(filter_element)

        on = filter_category_ids(filter_element)
        if wanted and not (on & wanted):
            log(u'   {0}: skipped - categories {1} not wanted'.format(
                name, sorted(on)))
            continue
        if token and token not in name.lower():
            log(u'   {0}: skipped - name lacks "{1}"'.format(name, token))
            continue

        try:
            overrides = template.GetFilterOverrides(filter_id)
        except Exception:
            swallowed()
            overrides = None

        colour = override_colour(overrides) if overrides else None
        pattern_id = override_pattern(overrides) if overrides else None
        if colour is None:
            notes.append('{0} has no colour override - shown grey'.format(name))

        values = rule_values(filter_element)
        label = tidy_label(values[0], token) if values else ''
        if not label:
            label = tidy_label(name, token) or name

        log(u'   {0}: kept - label "{1}", colour {2}, pattern {3}, rule '
            u'values {4}'.format(name, label, colour,
                                 eid_value(pattern_id) if pattern_id
                                 else None, values))
        entries.append(LegendEntry(filter_id, name, label, colour,
                                   pattern_id))

    entries.sort(key=lambda e: e.label.lower())
    return entries, notes
