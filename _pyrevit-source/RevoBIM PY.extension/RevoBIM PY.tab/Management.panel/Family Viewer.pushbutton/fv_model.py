# -*- coding: utf-8 -*-
"""Family Viewer - the read of the model.

One pass over the types and one pass over the instances, never a collector per
family.  A collector per family is fine on a demo model and unusable at forty
thousand elements, and it runs again on every refresh.
"""

import fv_clr  # noqa: F401  - must be first, references the assemblies

import re

from Autodesk.Revit.DB import (
    BuiltInParameter,
    Element,
    ElementId,
    ElementType,
    FamilyInstance,
    FamilySymbol,
    FilteredElementCollector,
    StorageType,
)

import fv_core
from fv_core import eid_value, natural_key, agree, VARIES, TEXT_TYPES

FAMILY_ROW = 'family'
TYPE_ROW = 'type'
# the third level: one line per placed element under its type
INSTANCE_ROW = 'instance'
# a heading that gathers the instances under a type by one parameter's value.
# It holds no element, takes no edit and is never selected or exported.
GROUP_ROW = 'group'

KEY_NAME = '__name__'
KEY_CATEGORY = '__category__'
KEY_COUNT = '__count__'



# ---------------------------------------------------------------------------
# rows
# ---------------------------------------------------------------------------

class Row(object):
    """One line in the list: a family heading, or a type under it."""

    __slots__ = ('kind', 'family_name', 'family_id', 'type_name', 'type_id',
                 'category', 'category_id', 'is_system', 'count', 'values',
                 'children', 'parent', 'open', 'preview_id', 'note',
                 'element_id', 'mark', 'instances', 'loaded', 'group_key')

    def __init__(self, kind):
        self.kind = kind
        self.family_name = ''
        self.family_id = 0
        self.type_name = ''
        self.type_id = 0
        self.category = ''
        self.category_id = 0
        self.is_system = False
        self.count = 0
        self.values = {}
        self.children = []
        self.parent = None
        self.open = True
        self.preview_id = 0
        self.note = ''
        # instance rows
        self.element_id = 0
        self.mark = ''
        # type rows: the instances under them, and whether they have been read
        self.instances = []
        self.loaded = False
        # group heading rows
        self.group_key = ''

    @property
    def label(self):
        if self.kind == FAMILY_ROW:
            return self.family_name
        if self.kind == GROUP_ROW:
            return self.group_key or '(blank)'
        if self.kind == INSTANCE_ROW:
            # an instance has no name of its own - element.Name on a family
            # instance gives back the TYPE name, which would repeat the line
            # above it forty times.  Its mark is what identifies it, and its
            # id is what is left when there is no mark.
            return self.mark or ('Element ' + str(self.element_id))
        return self.type_name

    def cell(self, key):
        if key == KEY_NAME:
            return self.label
        if key == KEY_CATEGORY:
            return self.category
        if key == KEY_COUNT:
            if self.kind == INSTANCE_ROW:
                # one element is one element; a "1" on every line is noise
                return ''
            return str(self.count)
        return self.values.get(key, '')

    def search_text(self):
        parts = [self.family_name, self.type_name, self.category, str(self.count)]
        for value in self.values.values():
            parts.append(value)
        return ' '.join([part for part in parts if part])


# ---------------------------------------------------------------------------
# categories and phases
# ---------------------------------------------------------------------------

def category_of(element):
    try:
        return element.Category
    except Exception:
        return None


def category_name(element):
    cat = category_of(element)
    if cat is None:
        return ''
    try:
        return cat.Name or ''
    except Exception:
        return ''


def category_id(element):
    cat = category_of(element)
    if cat is None:
        return 0
    try:
        return eid_value(cat.Id)
    except Exception:
        return 0


def is_annotation(cat):
    """CategoryType.Annotation without importing the enum by name, so a release
    that moved it cannot take the module down at load."""
    try:
        return str(cat.CategoryType) == 'Annotation'
    except Exception:
        return False


def list_categories(doc, include_system=True, include_annotation=False):
    """Every category that actually has a type in this project, with how many
    types it has.  Nothing is offered that does not exist."""
    found = {}
    collector = FilteredElementCollector(doc).WhereElementIsElementType()
    for element in collector:
        if not isinstance(element, ElementType):
            continue
        loadable = isinstance(element, FamilySymbol)
        if not loadable and not include_system:
            continue
        cat = category_of(element)
        if cat is None:
            continue
        try:
            name = cat.Name
        except Exception:
            continue
        if not name:
            continue
        if is_annotation(cat) and not include_annotation:
            continue
        key = eid_value(cat.Id)
        entry = found.get(key)
        if entry is None:
            found[key] = {'name': name, 'id': key, 'types': 1,
                          'annotation': is_annotation(cat)}
        else:
            entry['types'] += 1
    values = list(found.values())
    values.sort(key=lambda item: natural_key(item['name']))
    return values


WORKSET_KEY = 'Workset'


def categories_in_view(doc, view):
    """The category ids that actually have something in this view.

    Read off the elements rather than off the view's category settings: a
    category can be switched on in a view and have nothing in it, and ticking
    it would then be a lie.
    """
    found = set()
    if view is None:
        return found
    try:
        collector = FilteredElementCollector(doc, view.Id)
        collector = collector.WhereElementIsNotElementType()
    except Exception:
        return found
    for element in collector:
        try:
            cat = element.Category
        except Exception:
            continue
        if cat is None:
            continue
        try:
            found.add(eid_value(cat.Id))
        except Exception:
            continue
    return found


def list_worksets(doc):
    """Every user workset in the project, for the Workset cell's dropdown."""
    found = []
    try:
        if not doc.IsWorkshared:
            return found
    except Exception:
        return found
    try:
        from Autodesk.Revit.DB import (FilteredWorksetCollector, WorksetKind)
        collector = FilteredWorksetCollector(doc).OfKind(WorksetKind.UserWorkset)
        for workset in collector:
            try:
                found.append({'id': workset_number(workset),
                              'name': workset.Name})
            except Exception:
                continue
    except Exception:
        fv_core.log('could not list worksets:\n' + fv_core.format_exc())
    found.sort(key=lambda entry: natural_key(entry['name']))
    return found


def workset_number(workset):
    """A WorksetId is not an ElementId, so eid_value does not apply to it - it
    carries its own integer, and the name of that member has not moved the way
    ElementId's has."""
    try:
        return int(workset.Id.IntegerValue)      # noqa - WorksetId, not ElementId
    except Exception:
        pass
    try:
        return int(workset.Id)
    except Exception:
        return 0


def workset_of(element, doc):
    """The name of the workset an element is on, or blank."""
    if element is None:
        return ''
    try:
        param = element.get_Parameter(BuiltInParameter.ELEM_PARTITION_PARAM)
        if param is not None:
            text = _text_or_blank(param.AsValueString())
            if text:
                return text
    except Exception:
        pass
    try:
        table = doc.GetWorksetTable()
        workset = table.GetWorkset(element.WorksetId)
        return _text_or_blank(workset.Name)
    except Exception:
        return ''


def workset_ids(doc):
    """Workset name -> id, built once per run rather than once per element."""
    found = {}
    for entry in list_worksets(doc):
        found[entry['name']] = entry['id']
    return found


def set_workset(element, name, doc, by_name=None):
    """Put an element on a workset by name, and read it back.

    Pass `by_name` from workset_ids() when moving more than one element: listing
    the worksets is a collector of its own, and doing it for every element of
    every type in a run was the slowest part of a workset Apply.
    """
    if element is None:
        return False, 'the element could not be found'
    wanted = (name or '').strip()
    if not wanted:
        return False, 'pick a workset'
    if by_name is None:
        by_name = workset_ids(doc)
    target = by_name.get(wanted)
    if target is None:
        return False, 'there is no workset called "' + wanted + '"'
    try:
        param = element.get_Parameter(BuiltInParameter.ELEM_PARTITION_PARAM)
    except Exception:
        param = None
    if param is None:
        return False, 'this element does not sit on a workset'
    try:
        if param.IsReadOnly:
            return False, 'its workset is read-only here'
    except Exception:
        pass
    try:
        param.Set(target)
    except Exception:
        return False, 'Revit would not move it'
    if workset_of(element, doc) == wanted:
        return True, ''
    return False, 'it read back on "' + workset_of(element, doc) + '"'


def list_phases(doc):
    """Phases in sequence order, as they read in Revit."""
    phases = []
    try:
        collection = doc.Phases
    except Exception:
        return phases
    index = 0
    try:
        for phase in collection:
            name = ''
            try:
                name = phase.Name
            except Exception:
                name = ''
            phases.append({'name': name, 'id': eid_value(phase.Id),
                           'sequence': index})
            index += 1
    except Exception:
        pass
    return phases


def _phase_sequence_map(doc):
    order = {}
    for index, phase in enumerate(list_phases(doc)):
        order[phase['id']] = index
    return order


def _phase_of(element, builtin):
    try:
        param = element.get_Parameter(builtin)
    except Exception:
        return None
    if param is None:
        return None
    try:
        value = eid_value(param.AsElementId())
    except Exception:
        return None
    if value <= 0:
        return None
    return value


def phase_keeps(element, wanted_id, mode, order):
    """True where the element belongs in the chosen phase.

    'created' is the element's own Phase Created.  'existing' is everything
    standing in that phase: created at or before it, and not demolished before
    the end of it.  An element with no phase parameter at all is left out when
    a phase is chosen, and the status line reports how many.
    """
    if not wanted_id:
        return True
    created = _phase_of(element, BuiltInParameter.PHASE_CREATED)
    if created is None:
        return False
    if mode != 'existing':
        return created == wanted_id
    wanted_seq = order.get(wanted_id, -1)
    created_seq = order.get(created, -1)
    if created_seq < 0 or wanted_seq < 0:
        return created == wanted_id
    if created_seq > wanted_seq:
        return False
    demolished = _phase_of(element, BuiltInParameter.PHASE_DEMOLISHED)
    if demolished is None:
        return True
    demolished_seq = order.get(demolished, -1)
    if demolished_seq < 0:
        return True
    return demolished_seq > wanted_seq


# ---------------------------------------------------------------------------
# parameter reading
# ---------------------------------------------------------------------------

def _as_text(param, doc):
    if param is None:
        return None
    try:
        if not param.HasValue:
            return ''
    except Exception:
        pass
    try:
        storage = param.StorageType
    except Exception:
        storage = None
    try:
        if storage == StorageType.ElementId:
            target = param.AsElementId()
            if target is None or eid_value(target) <= 0:
                return ''
            element = doc.GetElement(target)
            if element is None:
                return str(eid_value(target))
            try:
                return element.Name
            except Exception:
                return str(eid_value(target))
        text = param.AsValueString()
        if text:
            return text
        if storage == StorageType.String:
            return param.AsString() or ''
        if storage == StorageType.Integer:
            return str(param.AsInteger())
        if storage == StorageType.Double:
            return str(round(param.AsDouble(), 6))
    except Exception:
        return None
    return ''


def read_param(element, name, doc):
    """Every route to a parameter is tried: GetParameters and LookupParameter do
    not always hand back the same object, and a family can carry two parameters
    of the same name."""
    if element is None:
        return None
    try:
        found = element.GetParameters(name)
    except Exception:
        found = None
    if found:
        for param in found:
            text = _as_text(param, doc)
            if text:
                return text
        return _as_text(found[0], doc)
    try:
        param = element.LookupParameter(name)
    except Exception:
        param = None
    if param is not None:
        return _as_text(param, doc)
    return None


def _text_or_blank(value):
    """A name is only a name if it came back as text.

    IronPython does not reliably hand back a string for `element.Name`: on some
    engines, and on some element classes that hide the property, it comes back
    as the bound property object instead, and str() of that is a repr.  Reading
    a repr as a name is what put "(unnamed)" on every row - it never raised, so
    the try/except round it never fired.
    """
    if value is None:
        return ''
    try:
        if not isinstance(value, TEXT_TYPES):
            return ''
    except Exception:
        return ''
    text = value.strip()
    if not text:
        return ''
    if text.startswith('<') and text.endswith('>'):
        return ''
    return text


def type_name_of(element):
    """The type's own name, by every route in turn.

    `element.Name` first, then the built-in name parameters - a family symbol
    carries SYMBOL_NAME_PARAM, a system type ALL_MODEL_TYPE_NAME - then
    `Element.Name` reached through the class, which is the route that works
    where the instance property does not.
    """
    if element is None:
        return ''
    try:
        name = _text_or_blank(element.Name)
        if name:
            return name
    except Exception:
        pass
    for builtin in ('SYMBOL_NAME_PARAM', 'ALL_MODEL_TYPE_NAME',
                    'ELEM_TYPE_PARAM'):
        try:
            param = element.get_Parameter(getattr(BuiltInParameter, builtin))
        except Exception:
            param = None
        if param is None:
            continue
        try:
            name = _text_or_blank(param.AsString())
        except Exception:
            name = ''
        if name:
            return name
    try:
        name = _text_or_blank(Element.Name.GetValue(element))
        if name:
            return name
    except Exception:
        pass
    return ''


def family_name_of(element):
    """The family the type belongs to.

    `ElementType.FamilyName` is the reliable one and it answers for a system
    type as well as a loadable one, so it goes first; `element.Family.Name` is
    tried after it, and the built-in family name parameter after that.
    """
    if element is None:
        return ''
    try:
        name = _text_or_blank(element.FamilyName)
        if name:
            return name
    except Exception:
        pass
    try:
        family = element.Family
    except Exception:
        family = None
    if family is not None:
        name = type_name_of(family)
        if name:
            return name
    for builtin in ('SYMBOL_FAMILY_NAME_PARAM', 'ALL_MODEL_FAMILY_NAME'):
        try:
            param = element.get_Parameter(getattr(BuiltInParameter, builtin))
        except Exception:
            param = None
        if param is None:
            continue
        try:
            name = _text_or_blank(param.AsString())
        except Exception:
            name = ''
        if name:
            return name
    return ''


def _builtin_name(element_type, name, doc):
    """The handful of names that are really properties rather than parameters."""
    if name == 'Type Name':
        return type_name_of(element_type)
    if name == 'Family Name':
        return family_name_of(element_type)
    if name == WORKSET_KEY:
        # a type carries no workset - its instances do - so reading it off a
        # type returns nothing and the instance pass fills it in.  Where the
        # instances disagree, agree() turns that into "(varies)", which is what
        # the cell's dropdown is for.
        return workset_of(element_type, doc) or None
    return None


def _binding_covers(binding, wanted):
    """True where a project parameter's binding reaches one of these
    categories.  A binding with no readable category list is taken as covering
    everything, so a parameter is never hidden by a failure to read it."""
    try:
        categories = binding.Categories
    except Exception:
        return True
    if categories is None:
        return True
    try:
        for category in categories:
            try:
                if eid_value(category.Id) in wanted:
                    return True
            except Exception:
                continue
    except Exception:
        return True
    return False


def parameter_names(doc, type_elements, sample_instances, category_ids=None):
    """The parameter list offered in a column picker.

    Scoped to the categories on show.  A project parameter is only offered
    where its binding actually covers one of those categories, and the two
    name properties are only offered because every element has them - the rest
    of the list is read off the elements themselves, which are already narrowed
    to the chosen categories.  Offering every project parameter in the model
    made the list long enough to be useless on a job of any size.
    """
    names = set()
    names.add('Type Name')
    names.add('Family Name')
    try:
        if doc.IsWorkshared:
            names.add(WORKSET_KEY)
    except Exception:
        pass

    wanted = None
    if category_ids:
        wanted = set([int(value) for value in category_ids])

    try:
        iterator = doc.ParameterBindings.ForwardIterator()
        iterator.Reset()
        while iterator.MoveNext():
            try:
                definition = iterator.Key
                if definition is None or not definition.Name:
                    continue
                if wanted is not None and not _binding_covers(
                        iterator.Current, wanted):
                    continue
                names.add(definition.Name)
            except Exception:
                continue
    except Exception:
        pass

    for element in list(type_elements)[:2000]:
        try:
            for param in element.Parameters:
                try:
                    if param.Definition is not None and param.Definition.Name:
                        names.add(param.Definition.Name)
                except Exception:
                    continue
        except Exception:
            continue

    for element in list(sample_instances)[:2000]:
        try:
            for param in element.Parameters:
                try:
                    if param.Definition is not None and param.Definition.Name:
                        names.add(param.Definition.Name)
                except Exception:
                    continue
        except Exception:
            continue

    ordered = sorted(names, key=natural_key)
    return ordered


# ---------------------------------------------------------------------------
# the read
# ---------------------------------------------------------------------------

class ReadResult(object):
    def __init__(self):
        self.families = []        # Row objects, kind == FAMILY_ROW
        self.type_ids = {}        # type id -> Row
        self.param_names = []
        self.categories = []
        self.phases = []
        self.notes = []
        self.instance_total = 0
        self.no_phase = 0
        self.types_found = 0
        self.type_level = set()
        self.instances_seen = 0
        self.no_type_match = 0
        self.in_scope_seen = 0
        self.in_scope_no_match = 0
        self.by_category = {}
        self.nested_out = 0
        self.phased_out = 0
        self.truncated = False


# the three scopes, by name.  One word decides both halves of what a scope
# means - where the elements are counted, and whether a type with none of them
# is listed - so the two can never be set to disagree with each other.
SCOPE_PROJECT = 'project'
SCOPE_VIEW = 'view'
SCOPE_ALL = 'all'


def scope_rules(scope):
    """(count in the active view only, keep types with nothing placed).

        project   every family placed anywhere in the project
        view      every family placed in the active view
        all       every family in the project, placed or not

    Written out once, here, because every previous version of this worked it
    out in two places that could disagree.
    """
    if scope == SCOPE_VIEW:
        return True, False
    if scope == SCOPE_ALL:
        return False, True
    return False, False


def read(doc, view=None, scope=SCOPE_PROJECT, wanted_category_ids=None,
         columns=None, include_system=False, include_annotation=False,
         ignore_nested=True, phase_id=None, phase_mode='existing',
         progress=None):
    """Read the whole list in two passes."""
    columns = list(columns or [])
    view_only, include_unused = scope_rules(scope)
    if not view_only:
        # a view was handed in but this scope does not count by view: ignoring
        # it here means the caller cannot accidentally scope the count to a
        # view while asking for the whole project
        view = None
    if view_only and view is None:
        # asked for the active view and there is not one
        result = ReadResult()
        result.categories = list_categories(doc, include_system,
                                            include_annotation)
        result.phases = list_phases(doc)
        result.notes.append(
            'There is no active view to read, so nothing could be counted.')
        return result
    result = ReadResult()
    result.categories = list_categories(doc, include_system, include_annotation)
    result.phases = list_phases(doc)
    order = _phase_sequence_map(doc)

    wanted = None
    if wanted_category_ids:
        wanted = set([int(value) for value in wanted_category_ids])

    # ---- pass 1: the types -------------------------------------------------
    if progress:
        progress(0.0, 'Reading types')

    families = {}
    type_rows = {}
    type_elements = []

    collector = FilteredElementCollector(doc).WhereElementIsElementType()
    for element in collector:
        if not isinstance(element, ElementType):
            continue
        loadable = isinstance(element, FamilySymbol)
        if not loadable and not include_system:
            continue
        cat = category_of(element)
        if cat is None:
            continue
        try:
            cat_name = cat.Name
        except Exception:
            continue
        if not cat_name:
            continue
        if is_annotation(cat) and not include_annotation:
            continue
        cat_key = eid_value(cat.Id)
        if wanted is not None and cat_key not in wanted:
            continue

        fam_name = family_name_of(element)
        fam_id = 0
        if loadable:
            try:
                family = element.Family
            except Exception:
                family = None
            if family is not None:
                fam_id = eid_value(family.Id)
        if not fam_name:
            # a system type with no family name of its own belongs under its
            # category; a loadable one with none is worth saying so about
            fam_name = cat_name if not loadable else '(no family name)'

        group_key = (cat_key, fam_name, fam_id, not loadable)
        parent = families.get(group_key)
        if parent is None:
            parent = Row(FAMILY_ROW)
            parent.family_name = fam_name
            parent.family_id = fam_id
            parent.category = cat_name
            parent.category_id = cat_key
            parent.is_system = not loadable
            families[group_key] = parent

        row = Row(TYPE_ROW)
        row.family_name = fam_name
        row.family_id = fam_id
        row.category = cat_name
        row.category_id = cat_key
        row.is_system = not loadable
        row.type_id = eid_value(element.Id)
        row.type_name = type_name_of(element)
        if not row.type_name:
            # every route refused - the family name is a better answer than
            # "(unnamed)", which tells nobody anything
            row.type_name = fam_name or ('type ' + str(row.type_id))
            row.note = 'Revit would not give up a name for this type.'
        row.parent = parent
        parent.children.append(row)
        type_rows[row.type_id] = row
        type_elements.append(element)

        # type level parameter values.  Which names answered here is what
        # tells the batch window - and anything else that writes - that the
        # parameter lives on the TYPE rather than on each instance.
        for name in columns:
            value = _builtin_name(element, name, doc)
            if value is None:
                value = read_param(element, name, doc)
            if value is not None:
                row.values[name] = value
                if name != WORKSET_KEY:
                    result.type_level.add(name)

    result.type_ids = type_rows

    # ---- pass 2: the instances --------------------------------------------
    if progress:
        progress(0.35, 'Counting elements')

    # NO CATEGORY FILTER ON THIS COLLECTOR.
    #
    # It used to carry an ElementMulticategoryFilter built from the category
    # ids, purely for speed.  It is the only step in the count that can match
    # NOTHING without raising - and when it does, every type comes back with a
    # count of zero, which showed up as "Entire project" and "Active view"
    # listing nothing at all while "All families" looked fine, because that one
    # keeps types whose count is zero.
    #
    # The filter was never doing the filtering anyway: a type that is not in
    # type_rows is skipped below, and that dictionary was already built from
    # exactly the categories asked for.  So the filter bought a little speed and
    # cost the whole feature, and it is gone.
    if view is not None:
        instances = FilteredElementCollector(doc, view.Id)
    else:
        instances = FilteredElementCollector(doc)
    instances = instances.WhereElementIsNotElementType()

    pending = {}          # (type id, name) -> list of seen values
    counted = 0
    no_phase = 0
    # a sample of the instances that actually survived the filters, so the
    # parameter picker offers instance parameters as well as type ones
    param_sample = []

    # counters kept so an empty list can say WHERE it went empty, rather than
    # blaming a filter that was never set
    looked_at = 0
    no_type_match = 0
    nested_out = 0
    phased_out = 0
    # Counted separately, and this distinction is the whole point of them: an
    # element of a category nobody ticked is SUPPOSED to miss.  Counting those
    # as mismatches is what made the tool accuse itself of a bug every time a
    # view held nothing of the ticked category - which is most views.
    in_scope_seen = 0
    in_scope_no_match = 0
    by_category = {}

    for element in instances:
        looked_at += 1
        cat_id = category_id(element)
        in_scope = (wanted is None or cat_id in wanted)
        if in_scope:
            in_scope_seen += 1
            name = category_name(element) or '(no category)'
            by_category[name] = by_category.get(name, 0) + 1
        try:
            type_id = eid_value(element.GetTypeId())
        except Exception:
            no_type_match += 1
            if in_scope:
                in_scope_no_match += 1
            continue
        row = type_rows.get(type_id)
        if row is None:
            no_type_match += 1
            if in_scope:
                in_scope_no_match += 1
            continue
        if ignore_nested and isinstance(element, FamilyInstance):
            try:
                if element.SuperComponent is not None:
                    nested_out += 1
                    continue
            except Exception:
                pass
        if phase_id:
            if not phase_keeps(element, phase_id, phase_mode, order):
                created = _phase_of(element, BuiltInParameter.PHASE_CREATED)
                if created is None:
                    no_phase += 1
                phased_out += 1
                continue
        row.count += 1
        counted += 1
        if len(param_sample) < 600:
            param_sample.append(element)

        # a parameter the type does not carry is an instance parameter; read it
        # here rather than in a second pass over the same elements
        for name in columns:
            if name in row.values:
                continue
            key = (type_id, name)
            seen = pending.get(key)
            if seen is None:
                seen = []
                pending[key] = seen
            if len(seen) > 1:
                continue
            value = _builtin_name(element, name, doc)
            if value is None:
                value = read_param(element, name, doc)
            if value is None:
                continue
            if value not in seen:
                seen.append(value)

    result.instance_total = counted
    result.no_phase = no_phase
    result.types_found = len(type_rows)
    result.instances_seen = looked_at
    result.no_type_match = no_type_match
    result.nested_out = nested_out
    result.phased_out = phased_out
    result.in_scope_seen = in_scope_seen
    result.in_scope_no_match = in_scope_no_match
    result.by_category = by_category

    if type_rows and not counted:
        # Types were read and nothing counted against any of them.  Which of
        # the four ways that can happen it was decides what to say, because
        # "nothing matches" on its own sent the last two rounds of this
        # looking at the column filters, which were not the problem.
        where = 'the active view' if view is not None else 'this project'
        if not looked_at:
            result.notes.append(
                'Revit returned no elements at all for ' + where + '. ' +
                str(len(type_rows)) + ' types were read.')
        elif not in_scope_seen:
            # the ordinary case, and the one that used to be reported as a bug:
            # the view simply has nothing of the categories that are ticked
            result.notes.append(
                'None of the ' + str(looked_at) + ' elements in ' + where +
                ' are in the categories you have ticked. Nothing of those '
                'categories is placed there.')
        elif in_scope_no_match >= in_scope_seen:
            # THIS is the one worth reporting: elements of the right category
            # are there, and their types are not among the ones read
            result.notes.append(
                'All ' + str(in_scope_seen) + ' elements of those categories '
                'in ' + where + ' belong to types that were not read. That is '
                'a bug - please send a debug report.')
        elif phased_out:
            result.notes.append(
                str(phased_out) + ' elements were left out by the phase '
                'filter and nothing was left. Set the phase to every phase.')
        elif nested_out:
            result.notes.append(
                str(nested_out) + ' elements are nested inside another family '
                'and nothing was left. Turn off "ignore nested" in Settings.')
        else:
            result.notes.append(
                'No placed elements were found in ' + where + ' for any of '
                'the ' + str(len(type_rows)) + ' types read.')

    for (type_id, name), seen in pending.items():
        row = type_rows.get(type_id)
        if row is None:
            continue
        if len(seen) == 1:
            row.values[name] = seen[0]
        elif len(seen) > 1:
            row.values[name] = VARIES

    # ---- roll up -----------------------------------------------------------
    if progress:
        progress(0.8, 'Grouping')

    parents = []
    for parent in families.values():
        kept = parent.children
        if not include_unused:
            kept = [child for child in kept if child.count > 0]
        if not kept:
            continue
        parent.children = sorted(kept, key=lambda item: natural_key(item.type_name))
        parent.count = sum([child.count for child in parent.children])
        parent.preview_id = parent.children[0].type_id
        for name in columns:
            parent.values[name] = agree(
                [child.values.get(name) for child in parent.children])
        parents.append(parent)

    parents.sort(key=lambda item: (natural_key(item.category),
                                   natural_key(item.family_name)))
    result.families = parents

    # the picker offers what THESE categories carry, not every parameter in
    # the model - scoped by the categories actually read
    shown_ids = set([parent.category_id for parent in parents])
    result.param_names = parameter_names(doc, type_elements, param_sample,
                                         shown_ids)

    if progress:
        progress(1.0, 'Done')
    return result


def flatten(families, families_open=True):
    """The families in order, with their types under them and - where a type
    is open - its instances under those, honouring each row's own open state.

    A group heading is a row like any other here: the grouping is worked out
    before this and handed in as the type's children, so nothing downstream has
    to know whether it is looking at a grouped list or a flat one.
    """
    rows = []
    for parent in families:
        rows.append(parent)
        if not parent.open:
            continue
        for child in parent.children:
            rows.append(child)
            if child.kind != TYPE_ROW or not child.open:
                continue
            for under in child.instances:
                rows.append(under)
                if under.kind != GROUP_ROW or not under.open:
                    continue
                for leaf in under.children:
                    rows.append(leaf)
    return rows


def sort_instances(instances, key, direction=1):
    """The elements under a type, in the order of one column.

    With no column - or sorted by the name column - they go in their own
    natural order, which for an element is its mark and then its id.
    """
    rows = list(instances)
    if not key or key == KEY_NAME:
        rows.sort(key=lambda one: natural_key(one.label))
    else:
        rows.sort(key=lambda one: (natural_key(one.cell(key) or ''),
                                   natural_key(one.label)))
    if direction < 0:
        rows.reverse()
    return rows


def group_instances(instances, key):
    """Instances gathered under a heading per distinct value of one column.

    Returns the list to sit under the type: heading rows, each carrying its own
    instances.  A blank value gets its own heading rather than being dropped,
    because "which ones have nothing set" is usually the question being asked.
    """
    if not key:
        return list(instances)
    order = []
    buckets = {}
    for row in instances:
        value = (row.cell(key) or '').strip()
        if value not in buckets:
            buckets[value] = []
            order.append(value)
        buckets[value].append(row)

    made = []
    for value in sorted(order, key=natural_key):
        heading = Row(GROUP_ROW)
        heading.group_key = value or '(blank)'
        heading.family_name = instances[0].family_name if instances else ''
        heading.type_name = instances[0].type_name if instances else ''
        heading.category = instances[0].category if instances else ''
        heading.count = len(buckets[value])
        heading.children = buckets[value]
        heading.open = True
        for row in buckets[value]:
            row.parent = heading
        made.append(heading)
    return made


def read_instances(doc, type_ids, columns=None, view=None, ignore_nested=True,
                   phase_id=None, phase_mode='existing', cap=20000):
    """One row per placed element, for the types asked for.

    Read on demand rather than in the main pass: a real model has hundreds of
    types and tens of thousands of elements, and reading every instance up
    front to show a level most people never open would make every refresh slow
    for everybody.
    """
    columns = list(columns or [])
    wanted = set([int(value) for value in (type_ids or [])])
    found = {}
    for value in wanted:
        found[value] = []
    if not wanted:
        return found, 0

    order = _phase_sequence_map(doc)
    if view is not None:
        collector = FilteredElementCollector(doc, view.Id)
    else:
        collector = FilteredElementCollector(doc)
    collector = collector.WhereElementIsNotElementType()

    seen = 0
    for element in collector:
        try:
            type_id = eid_value(element.GetTypeId())
        except Exception:
            continue
        if type_id not in wanted:
            continue
        if ignore_nested and isinstance(element, FamilyInstance):
            try:
                if element.SuperComponent is not None:
                    continue
            except Exception:
                pass
        if phase_id and not phase_keeps(element, phase_id, phase_mode, order):
            continue
        if seen >= cap:
            break
        seen += 1

        row = Row(INSTANCE_ROW)
        row.element_id = eid_value(element.Id)
        row.type_id = type_id
        row.mark = _text_or_blank(read_param(element, 'Mark', doc))
        row.category = category_name(element)
        row.category_id = category_id(element)
        for name in columns:
            value = read_param(element, name, doc)
            if value is None and name == WORKSET_KEY:
                value = workset_of(element, doc)
            if value is not None:
                row.values[name] = value
        found[type_id].append(row)

    for type_id in found:
        found[type_id].sort(key=lambda one: natural_key(one.label))
    return found, seen


# ---------------------------------------------------------------------------
# writing.  Nothing here starts a transaction - the caller owns that - and
# every write is READ BACK, because Revit does not reliably raise when a write
# does not take.  A void API call is not evidence.
# ---------------------------------------------------------------------------

def rename_element(element, wanted):
    """Rename, by whichever route this IronPython engine will take.

    Neither route reliably raises on failure and which one works varies with
    the engine, so the only way to know is to read the name back.
    """
    if element is None:
        return False, 'the element could not be found'
    wanted = (wanted or '').strip()
    if not wanted:
        return False, 'a name cannot be blank'
    try:
        element.Name = wanted
    except Exception:
        pass
    if type_name_of(element) == wanted:
        return True, ''
    try:
        Element.Name.SetValue(element, wanted)
    except Exception:
        pass
    if type_name_of(element) == wanted:
        return True, ''
    return False, 'Revit would not take the name (it is usually already used)'


def _writable(param):
    if param is None:
        return False
    try:
        if param.IsReadOnly:
            return False
    except Exception:
        pass
    return True


def _all_params(element, name):
    """Every route to a parameter, because GetParameters and LookupParameter do
    not always hand back the same object and a family can carry two parameters
    of the same name."""
    found = []
    try:
        for param in element.GetParameters(name):
            found.append(param)
    except Exception:
        pass
    try:
        one = element.LookupParameter(name)
        if one is not None:
            found.append(one)
    except Exception:
        pass
    return found


def set_param(element, name, text, doc):
    """Set a parameter from typed text, and read it back.

    Returns (written, message).  A parameter the element does not carry, or
    carries read-only, is reported rather than silently skipped.
    """
    if element is None:
        return False, 'the element could not be found'
    params = [param for param in _all_params(element, name) if _writable(param)]
    if not params:
        if _all_params(element, name):
            return False, 'that parameter is read-only here'
        return False, 'this element does not carry that parameter'

    wanted = '' if text is None else str(text)
    problem = ''
    for param in params:
        try:
            storage = param.StorageType
        except Exception:
            storage = None
        try:
            if storage == StorageType.String:
                param.Set(wanted)
            elif storage == StorageType.Integer:
                param.Set(_as_int(wanted))
            elif storage == StorageType.Double:
                if not param.SetValueString(wanted):
                    param.Set(float(wanted))
            elif storage == StorageType.ElementId:
                param.Set(ElementId(_as_int(wanted)))
            else:
                param.Set(wanted)
        except Exception:
            try:
                if not param.SetValueString(wanted):
                    problem = 'Revit would not take that value'
            except Exception:
                problem = 'Revit would not take that value'

    back = read_param(element, name, doc)
    if _same_value(back, wanted):
        return True, ''
    return False, problem or ('it read back as "' + str(back or '') + '"')


def _as_int(text):
    cleaned = str(text).strip().lower()
    if cleaned in ('yes', 'true', 'on'):
        return 1
    if cleaned in ('no', 'false', 'off', ''):
        return 0
    return int(float(cleaned))


def _same_value(got, wanted):
    """Revit rounds and reformats, so an exact string match is too strict for a
    number: 2400 typed into a length comes back as "2400.0" or "2400 mm"."""
    left = (got or '').strip()
    right = (wanted or '').strip()
    if left == right:
        return True
    if not right and not left:
        return True
    try:
        return abs(float(_first_number(left)) - float(_first_number(right))) < 1e-6
    except Exception:
        return False


def _first_number(text):
    match = re.search(r'-?\d+(\.\d+)?', text or '')
    if match is None:
        raise ValueError('no number')
    return match.group(0)


class InstanceIndex(object):
    """Every instance of a set of types, found in ONE pass of the model.

    A parameter that lives on the instance rather than the type has to be
    written to every instance of it.  The first version looked those up per
    type with a fresh collector over the whole model each time, so staging one
    instance parameter across fifty types walked a large model fifty times
    inside the Apply transaction.  This walks it once, for every type the run
    could need, and only when the first lookup asks.
    """

    def __init__(self, doc, type_ids):
        self.doc = doc
        self.wanted = set([int(value) for value in type_ids])
        self.found = None

    def of(self, type_id):
        if self.found is None:
            self._build()
        return self.found.get(int(type_id), [])

    def _build(self):
        self.found = {}
        for value in self.wanted:
            self.found[value] = []
        if not self.wanted:
            return
        try:
            collector = FilteredElementCollector(self.doc)
            collector = collector.WhereElementIsNotElementType()
        except Exception:
            return
        for element in collector:
            try:
                type_id = eid_value(element.GetTypeId())
            except Exception:
                continue
            if type_id in self.wanted:
                self.found[type_id].append(element)


# ---------------------------------------------------------------------------
# instance ids, for the two Select buttons
# ---------------------------------------------------------------------------

def instance_ids(doc, type_ids, view=None, ignore_nested=True,
                 phase_id=None, phase_mode='created'):
    """Every instance of the given types, under the same rules the list used,
    so what is selected agrees with the Count column."""
    wanted = set([int(value) for value in type_ids])
    if not wanted:
        return []
    order = _phase_sequence_map(doc)
    if view is not None:
        collector = FilteredElementCollector(doc, view.Id)
    else:
        collector = FilteredElementCollector(doc)
    collector = collector.WhereElementIsNotElementType()

    found = []
    for element in collector:
        try:
            type_id = eid_value(element.GetTypeId())
        except Exception:
            continue
        if type_id not in wanted:
            continue
        if ignore_nested and isinstance(element, FamilyInstance):
            try:
                if element.SuperComponent is not None:
                    continue
            except Exception:
                pass
        if phase_id and not phase_keeps(element, phase_id, phase_mode, order):
            continue
        found.append(element.Id)
    return found
