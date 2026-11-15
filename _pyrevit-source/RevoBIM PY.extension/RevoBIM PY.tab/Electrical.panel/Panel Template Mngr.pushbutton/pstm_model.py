# -*- coding: utf-8 -*-
"""RevoBIM PY - Panel Template Mngr: reading the model.

Everything the two tabs display is read here in one pass: the panel schedule
templates, every Electrical Equipment panel, and the panel schedule view that
ties one to the other.  Read the model in one pass, not per panel - the read
runs again on every refresh.

Runs on IronPython 2.7 and IronPython 3: no f-strings, no print statements.
"""

import pstm_clr                                                  # noqa: F401
import clr

from pstm_core import (eid_value, as_id, element_name, extract_template_number,
                       calc_slots, as_int)

from Autodesk.Revit.DB import (FilteredElementCollector, BuiltInCategory,
                               BuiltInParameter, StorageType, ElementId)

# The Electrical namespace is requested defensively: a name that does not exist
# on a given release is skipped rather than throwing at module load.
PanelScheduleView = None
PanelScheduleTemplate = None
PanelScheduleType = None
PanelConfiguration = None
try:
    from Autodesk.Revit.DB.Electrical import PanelScheduleView as _PSV
    PanelScheduleView = _PSV
except Exception:
    pass
try:
    from Autodesk.Revit.DB.Electrical import PanelScheduleTemplate as _PST
    PanelScheduleTemplate = _PST
except Exception:
    pass
try:
    from Autodesk.Revit.DB.Electrical import PanelScheduleType as _PSTy
    PanelScheduleType = _PSTy
except Exception:
    pass
try:
    from Autodesk.Revit.DB.Electrical import PanelConfiguration as _PC
    PanelConfiguration = _PC
except Exception:
    pass

WorksharingUtils = None
try:
    from Autodesk.Revit.DB import WorksharingUtils as _WU
    WorksharingUtils = _WU
except Exception:
    pass


# ---------------------------------------------------------------------------
# Who has a hold on an element
# ---------------------------------------------------------------------------

class Ownership(object):
    """Whether an element can be written, and who is in the way if not.

    Two separate things lock an element in a workshared model and both have to
    be asked about:

      * somebody has borrowed the element itself - GetCheckoutStatus says
        OwnedByOtherUser;
      * nobody has borrowed it, but its whole workset is owned by somebody -
        Workset.Owner is their name.  The element's own checkout status is
        clean in that case, so checking only the element misses it.

    Revit's own documentation warns that both answers come from a local cache
    of the central model, so they can be out of date - which is why Apply asks
    again at the moment it writes rather than trusting the read the window did
    when it opened.
    """

    def __init__(self, doc):
        self.doc = doc
        self.workshared = False
        self.user = ''
        self._worksets = {}
        try:
            self.workshared = bool(doc.IsWorkshared)
        except Exception:
            self.workshared = False
        try:
            self.user = (doc.Application.Username or '').strip()
        except Exception:
            self.user = ''

    def _is_me(self, who):
        who = (who or '').strip()
        return bool(who) and who.lower() == self.user.lower()

    def owner_of(self, element):
        if WorksharingUtils is None:
            return ''
        try:
            info = WorksharingUtils.GetWorksharingTooltipInfo(self.doc, element.Id)
            return (info.Owner or '').strip()
        except Exception:
            return ''

    def _workset_lock(self, element):
        """The name of whoever owns this element's workset, if not us."""
        try:
            workset_id = element.WorksetId
        except Exception:
            return ''
        # keyed on the id's own text, not IntegerValue: a WorksetId is not an
        # ElementId and does not have to keep that property across releases
        key = None
        try:
            key = str(workset_id)
        except Exception:
            key = None
        if key is not None and key in self._worksets:
            return self._worksets[key]

        answer = ''
        try:
            workset = self.doc.GetWorksetTable().GetWorkset(workset_id)
            owner = (workset.Owner or '').strip()
            if owner and not self._is_me(owner):
                answer = 'workset "{0}" is owned by {1}'.format(
                    workset.Name, owner)
        except Exception:
            answer = ''
        if key is not None:
            self._worksets[key] = answer
        return answer

    def locked(self, element):
        """'' if this element can be written, otherwise why it cannot."""
        if element is None or not self.workshared:
            return ''
        if WorksharingUtils is not None:
            try:
                status = str(WorksharingUtils.GetCheckoutStatus(
                    self.doc, element.Id))
                # the member name rather than the enum object, so a release
                # that spells it differently still matches
                if 'other' in status.lower():
                    who = self.owner_of(element) or 'another user'
                    return 'checked out by {0}'.format(who)
            except Exception:
                pass
        return self._workset_lock(element)

    def locked_any(self, elements):
        """The first reason any of these elements cannot be written."""
        for element in elements:
            reason = self.locked(element)
            if reason:
                return reason
        return ''


PSEUDO_PARAMS = ['Family and Type', 'Family', 'Type Name', 'Panel Name',
                 'Level', 'Workset', 'Element Id']

# What TemplateInfo.schedule_type reports, in the order they are offered.
SCHEDULE_TYPES = ['Branch Panel', 'Switchboard', 'Data Panel']


def normalise_schedule_type(raw):
    """One name per schedule type, whichever route it was read by.

    A template can report its type through IsBranchPanelSchedule, through
    GetPanelScheduleType(), or only through its table data, and the three do not
    spell it the same way.  The filter default is Branch Panel, so a type that
    came back as 'Branch' or blank would hide every template in the project.
    """
    text = str(raw or '').lower()
    if not text:
        return ''
    if 'branch' in text:
        return 'Branch Panel'
    if 'switch' in text:
        return 'Switchboard'
    if 'data' in text:
        return 'Data Panel'
    return pretty_enum(raw)


# ---------------------------------------------------------------------------
# Enum names, read from the API rather than hardcoded
# ---------------------------------------------------------------------------

def enum_names(enum_type):
    if enum_type is None:
        return []
    try:
        import System
        return list(System.Enum.GetNames(clr.GetClrType(enum_type)))
    except Exception:
        return []


def enum_value(enum_type, name):
    if enum_type is None or not name:
        return None
    try:
        return getattr(enum_type, name)
    except Exception:
        return None


def pretty_enum(name):
    """'TwoColumnsCircuitsOnLeft' -> 'Two Columns Circuits On Left'."""
    if not name:
        return ''
    out = []
    for i, ch in enumerate(str(name)):
        if i and ch.isupper() and not str(name)[i - 1].isupper():
            out.append(' ')
        out.append(ch)
    return ''.join(out)


def config_choices():
    """Panel configurations offered in the filter and the duplicator."""
    names = enum_names(PanelConfiguration)
    if not names:
        names = ['OneColumn', 'TwoColumnsCircuitsOnLeft', 'TwoColumnsCircuitsOnRight']
    return names


# ---------------------------------------------------------------------------
# Parameter reading
# ---------------------------------------------------------------------------

def _param_text(param, doc):
    if param is None:
        return ''
    try:
        st = param.StorageType
    except Exception:
        return ''
    try:
        if st == StorageType.String:
            return param.AsString() or ''
        if st == StorageType.ElementId:
            pid = param.AsElementId()
            if eid_value(pid) > 0:
                el = doc.GetElement(pid)
                if el is not None:
                    return element_name(el)
            return ''
        text = param.AsValueString()
        if text:
            return text
        if st == StorageType.Integer:
            return str(param.AsInteger())
        if st == StorageType.Double:
            return str(param.AsDouble())
    except Exception:
        return ''
    return ''


def _lookup(element, name):
    if element is None or not name:
        return None
    try:
        params = element.GetParameters(name)
        if params and len(params) > 0:
            return params[0]
    except Exception:
        pass
    try:
        return element.LookupParameter(name)
    except Exception:
        return None


def read_param(element, doc, name):
    """Instance parameter first, then the type's, then the pseudo columns."""
    if not name:
        return ''
    if name in PSEUDO_PARAMS:
        return _pseudo(element, doc, name)

    stripped = name
    type_only = False
    if name.lower().startswith('type: '):
        stripped = name[6:]
        type_only = True

    if not type_only:
        text = _param_text(_lookup(element, stripped), doc)
        if text:
            return text

    try:
        type_el = doc.GetElement(element.GetTypeId())
    except Exception:
        type_el = None
    return _param_text(_lookup(type_el, stripped), doc)


def _pseudo(element, doc, name):
    try:
        if name == 'Element Id':
            return str(eid_value(element.Id))
        type_el = None
        try:
            type_el = doc.GetElement(element.GetTypeId())
        except Exception:
            type_el = None
        fam = ''
        typ = ''
        if type_el is not None:
            typ = element_name(type_el)
            try:
                fam = type_el.FamilyName or ''
            except Exception:
                fam = ''
        if name == 'Family':
            return fam
        if name == 'Type Name':
            return typ
        if name == 'Family and Type':
            if fam and typ:
                return '{0} : {1}'.format(fam, typ)
            return typ or fam
        if name == 'Panel Name':
            return panel_label(element, doc)
        if name == 'Level':
            try:
                lvl = doc.GetElement(element.LevelId)
                if lvl is not None:
                    return element_name(lvl)
            except Exception:
                pass
            return read_param(element, doc, 'Schedule Level')
        if name == 'Workset':
            try:
                table = doc.GetWorksetTable()
                ws = table.GetWorkset(element.WorksetId)
                return ws.Name if ws is not None else ''
            except Exception:
                return ''
    except Exception:
        return ''
    return ''


def panel_label(element, doc):
    """What the user calls the panel: its Panel Name, else Mark, else Name."""
    for bip in ('RBS_ELEC_PANEL_NAME',):
        try:
            p = element.get_Parameter(getattr(BuiltInParameter, bip))
            text = _param_text(p, doc)
            if text:
                return text
        except Exception:
            pass
    for name in ('Panel Name', 'Mark'):
        text = _param_text(_lookup(element, name), doc)
        if text:
            return text
    return element_name(element) or ('Id {0}'.format(eid_value(element.Id)))


def bound_params(doc, bic=None):
    """Every project or shared parameter bound to the category.

    Reading parameters off sampled elements alone is not enough: a parameter
    bound to Electrical Equipment can be missing from the handful of panels that
    happen to get sampled, and a type parameter never appears on an instance at
    all.  The bindings map is the authority on what the category can carry, so
    it is asked directly and unioned with what the elements report.
    """
    instance_names = set()
    type_names = set()
    if bic is None:
        bic = BuiltInCategory.OST_ElectricalEquipment

    category = None
    try:
        category = doc.Settings.Categories.get_Item(bic)
    except Exception:
        category = None
    if category is None:
        return instance_names, type_names
    category_id = eid_value(category.Id)

    try:
        iterator = doc.ParameterBindings.ForwardIterator()
        iterator.Reset()
        while iterator.MoveNext():
            try:
                definition = iterator.Key
                binding = iterator.Current
                name = definition.Name
            except Exception:
                continue
            if not name:
                continue

            covered = False
            try:
                for cat in binding.Categories:
                    if eid_value(cat.Id) == category_id:
                        covered = True
                        break
            except Exception:
                covered = False
            if not covered:
                continue

            is_type = False
            try:
                is_type = (binding.GetType().Name == 'TypeBinding')
            except Exception:
                is_type = False
            if is_type:
                type_names.add(name)
            else:
                instance_names.add(name)
    except Exception:
        pass
    return instance_names, type_names


def available_params(doc, elements, limit=800):
    """Every parameter name available on the panels, for the pickers.

    The plain name is what gets listed; read_param looks at the instance first
    and falls back to the type, so one entry covers both.  A "Type: x" entry is
    added only where the same name exists on the instance too, as a way to force
    the type's value.
    """
    instance_names, type_names = bound_params(doc)
    seen_types = set()

    for el in elements[:limit]:
        try:
            for p in el.Parameters:
                try:
                    instance_names.add(p.Definition.Name)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            for p in el.GetOrderedParameters():
                try:
                    instance_names.add(p.Definition.Name)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            tid = eid_value(el.GetTypeId())
            if tid and tid not in seen_types:
                seen_types.add(tid)
                type_el = doc.GetElement(el.GetTypeId())
                if type_el is not None:
                    for p in type_el.Parameters:
                        try:
                            type_names.add(p.Definition.Name)
                        except Exception:
                            pass
        except Exception:
            pass

    names = set(instance_names)
    names.update(type_names)
    both = instance_names.intersection(type_names)

    names.difference_update(PSEUDO_PARAMS)
    ordered = list(PSEUDO_PARAMS)
    ordered.extend(sorted(names, key=lambda s: s.lower()))
    ordered.extend(sorted(['Type: ' + n for n in both], key=lambda s: s.lower()))
    return ordered


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

class TemplateInfo(object):

    def __init__(self, element, doc):
        self.element = element
        self.id = element.Id
        self.id_val = eid_value(element.Id)
        self.name = element_name(element)
        self.slots = 0
        self.config = ''
        self.config_pretty = ''
        self.schedule_type = ''
        self.single_phase = False
        self.is_default = False
        self.used_count = 0
        self.used_panels = []
        self.number = None
        self.flags = {}
        self._read()

    def _read(self):
        el = self.element
        # three routes, because which one a template answers to depends on
        # whether it is a PanelScheduleTemplate or a PanelScheduleView
        for attribute, name in (('IsBranchPanelSchedule', 'Branch Panel'),
                                ('IsSwitchboardSchedule', 'Switchboard'),
                                ('IsDataPanelSchedule', 'Data Panel')):
            try:
                if getattr(el, attribute):
                    self.schedule_type = name
                    break
            except Exception:
                pass
        if not self.schedule_type:
            try:
                self.schedule_type = normalise_schedule_type(
                    str(el.GetPanelScheduleType()))
            except Exception:
                self.schedule_type = ''
        try:
            self.is_default = bool(el.IsDefault)
        except Exception:
            self.is_default = False

        data = table_data(el)
        if data is not None:
            if not self.schedule_type:
                try:
                    self.schedule_type = normalise_schedule_type(
                        str(data.ScheduleType))
                except Exception:
                    pass
            self.slots = _safe_int(data, 'NumberOfSlots')
            try:
                self.config = str(data.PanelConfiguration)
                self.config_pretty = pretty_enum(self.config)
            except Exception:
                pass
            for key in ('IsPanelSinglePhase', 'ShowSlotFromDeviceInsteadOfTemplate',
                        'ShowMultipleRowsForMultiphaseCircuits',
                        'ShowCircuitNumberOnOneRowForMultiphaseCircuits',
                        'IsThirdPhaseHidden', 'PhasesAsCurrents'):
                try:
                    self.flags[key] = bool(getattr(data, key))
                except Exception:
                    pass
            self.single_phase = self.flags.get('IsPanelSinglePhase', False)

    def display(self):
        bits = [self.name]
        if self.slots:
            bits.append('({0} slot)'.format(self.slots))
        return ' '.join(bits)


def table_data(element):
    try:
        return element.GetTableData()
    except Exception:
        return None


def _safe_int(obj, attr):
    try:
        return int(getattr(obj, attr))
    except Exception:
        return 0


def collect_templates(doc, settings=None):
    """Every panel schedule template in the project.

    Templates are collected both as PanelScheduleTemplate elements and as
    PanelScheduleView elements flagged as templates, then deduplicated by id,
    because which class a release surfaces them under has not been consistent.
    """
    settings = settings or {}
    rule = settings.get('name_number_rule', 'largest')
    keyword = settings.get('name_number_keyword', 'way')

    found = {}
    if PanelScheduleTemplate is not None:
        try:
            for el in FilteredElementCollector(doc).OfClass(PanelScheduleTemplate):
                found[eid_value(el.Id)] = el
        except Exception:
            pass
    if PanelScheduleView is not None:
        try:
            for el in FilteredElementCollector(doc).OfClass(PanelScheduleView):
                try:
                    if not el.IsPanelScheduleTemplate():
                        continue
                except Exception:
                    continue
                key = eid_value(el.Id)
                if key not in found:
                    found[key] = el
        except Exception:
            pass

    out = []
    for el in found.values():
        try:
            info = TemplateInfo(el, doc)
        except Exception:
            continue
        info.number = extract_template_number(info.name, rule, keyword)
        out.append(info)
    out.sort(key=lambda t: (t.name or '').lower())
    return out


# ---------------------------------------------------------------------------
# Panels and their schedule views
# ---------------------------------------------------------------------------

class PanelRow(object):

    def __init__(self, element, doc):
        self.element = element
        self.doc = doc
        self.id = element.Id
        self.id_val = eid_value(element.Id)
        self.name = panel_label(element, doc)
        self.view_id = None
        self.view = None
        self.view_name = ''
        self.current_id = 0          # template currently on the schedule
        self.current_name = ''
        self.chosen_id = 0           # template pending Apply
        self.chosen_name = ''
        self.status = ''             # '', 'changed', 'review', 'multi'
        self.note = ''
        self.locked = ''             # why it cannot be written, if it cannot
        self.calc_slots = None
        self.ways_text = ''
        self.phases_text = ''
        self._cache = {}

    # -- values -----------------------------------------------------------
    def value(self, param_name):
        if not param_name:
            return ''
        if param_name not in self._cache:
            self._cache[param_name] = read_param(self.element, self.doc, param_name)
        return self._cache[param_name]

    def clear_cache(self):
        self._cache = {}

    # -- pending change ---------------------------------------------------
    @property
    def changed(self):
        return self.chosen_id and self.chosen_id != self.current_id

    def set_choice(self, template_id_val, template_name):
        self.chosen_id = template_id_val or 0
        self.chosen_name = template_name or ''
        if self.changed:
            if self.status not in ('review', 'multi'):
                self.status = 'changed'
        else:
            if self.status in ('changed',):
                self.status = ''

    def reset_choice(self):
        self.chosen_id = self.current_id
        self.chosen_name = self.current_name
        self.status = ''
        self.note = ''

    def display_template(self):
        return self.chosen_name or self.current_name or '<none>'


def collect_panels(doc):
    out = []
    try:
        collector = FilteredElementCollector(doc) \
            .OfCategory(BuiltInCategory.OST_ElectricalEquipment) \
            .WhereElementIsNotElementType()
        for el in collector:
            out.append(el)
    except Exception:
        pass
    return out


def collect_instance_views(doc):
    """panel id value -> the panel schedule view instance sitting on it."""
    views = {}
    if PanelScheduleView is None:
        return views
    try:
        for v in FilteredElementCollector(doc).OfClass(PanelScheduleView):
            try:
                if v.IsPanelScheduleTemplate():
                    continue
            except Exception:
                pass
            try:
                if v.IsTemplate:
                    continue
            except Exception:
                pass
            try:
                panel_id = as_id(v.GetPanel())
            except Exception:
                panel_id = None
            key = eid_value(panel_id)
            if key and key not in views:
                views[key] = v
    except Exception:
        pass
    return views


def view_template_id(view):
    try:
        return eid_value(as_id(view.GetTemplate()))
    except Exception:
        return 0


class ModelData(object):

    def __init__(self):
        self.templates = []
        self.rows = []
        self.param_names = []
        self.by_id = {}
        self.errors = []
        self.ownership = None


def read(doc, settings):
    """One pass over the model.  Everything both tabs need."""
    data = ModelData()
    data.templates = collect_templates(doc, settings)
    for t in data.templates:
        data.by_id[t.id_val] = t

    views = collect_instance_views(doc)
    panels = collect_panels(doc)
    data.param_names = available_params(doc, panels)
    data.ownership = Ownership(doc)

    for el in panels:
        try:
            row = PanelRow(el, doc)
        except Exception:
            continue
        view = views.get(row.id_val)
        # the schedule view is what a template swap writes to, so it is the one
        # that has to be free; the panel matters too for a board with no
        # schedule yet, because making one writes to the panel
        row.locked = data.ownership.locked_any(
            [v for v in (view, el) if v is not None])
        if view is not None:
            row.view = view
            row.view_id = view.Id
            row.view_name = element_name(view)
            row.current_id = view_template_id(view)
            tpl = data.by_id.get(row.current_id)
            row.current_name = tpl.name if tpl is not None else ''
        row.chosen_id = row.current_id
        row.chosen_name = row.current_name
        data.rows.append(row)

        if row.current_id:
            tpl = data.by_id.get(row.current_id)
            if tpl is not None:
                tpl.used_count += 1
                tpl.used_panels.append(row.id_val)

    data.rows.sort(key=lambda r: _natural(r.name))
    return data


def _natural(text):
    """Sort P1, P2, P10 the way a person reads them."""
    import re as _re
    parts = _re.split(r'(\d+)', str(text or '').lower())
    key = []
    for part in parts:
        if part.isdigit():
            key.append((1, int(part), ''))
        elif part:
            key.append((0, 0, part))
    return key


# ---------------------------------------------------------------------------
# Auto Assign
# ---------------------------------------------------------------------------

def _leave_alone(row, summary, why):
    """Auto Assign could not work this row out.

    A row the user has already picked a template for keeps that pick and stays
    orange - marking it red would say "nothing to apply here" while Apply would
    still write it.  A row nobody has touched goes red for review by hand.
    """
    if row.changed:
        row.status = 'changed'
        row.note = why + ' - kept your pick'
        summary['kept'] += 1
    else:
        row.status = 'review'
        row.note = why
        summary['review'] += 1


def auto_assign(data, settings, rows=None, prefer_config=None):
    """Ways x phases, then the first template of that many slots.

    `rows` limits the run to a selection; None does every panel in the project.
    `prefer_config` breaks a tie towards the panel configuration on screen.
    Rows the number cannot be worked out for, or that have no template of that
    size, are marked 'review' so the table can highlight them in red.
    Returns a summary dict.
    """
    ways_param = settings.get('ways_param', '')
    phases_param = settings.get('phases_param', '')
    fallback = settings.get('phases_fallback', '')
    match_type = str(settings.get('match_schedule_type', '1')) == '1'

    # Match on the template's REAL slot count, not the number in its name.
    # The name carries ways (a "24 Ways" template is 72 slots), so matching on
    # the name compared a slot count against a way count and picked wrongly.
    # The name number is only a fallback for a template whose table data will
    # not report a count.
    by_slots = {}
    for tpl in data.templates:
        size = tpl.slots or tpl.number
        if not size:
            continue
        by_slots.setdefault(size, []).append(tpl)

    summary = {'assigned': 0, 'already': 0, 'review': 0, 'multi': 0,
               'kept': 0, 'locked': 0, 'total': 0}

    for row in (data.rows if rows is None else rows):
        summary['total'] += 1
        if row.locked:
            # no point queueing a change Apply would only have to skip
            summary['locked'] += 1
            row.status = 'locked'
            row.note = ''
            continue
        row.note = ''
        row.calc_slots = None
        row.ways_text = read_param(row.element, row.doc, ways_param) if ways_param else ''
        row.phases_text = read_param(row.element, row.doc, phases_param) if phases_param else ''

        phases = None
        from pstm_core import numbers_in
        nums = numbers_in(row.phases_text)
        if nums:
            phases = nums[0]
        elif fallback:
            phases = as_int(fallback, 0) or None

        slots, why = calc_slots(row.ways_text, phases)
        if slots is None:
            _leave_alone(row, summary, why or 'could not calculate')
            continue

        row.calc_slots = slots
        candidates = list(by_slots.get(slots, []))
        if not candidates:
            _leave_alone(row, summary,
                         'no template of {0} slots'.format(slots))
            continue

        # narrow only where narrowing still leaves something to pick
        if match_type and row.current_id:
            current = data.by_id.get(row.current_id)
            if current is not None and current.schedule_type:
                same = [c for c in candidates
                        if c.schedule_type == current.schedule_type]
                if same:
                    candidates = same
        if prefer_config:
            same = [c for c in candidates if c.config == prefer_config]
            if same:
                candidates = same

        # the first one that fits, as asked
        pick = candidates[0]
        row.set_choice(pick.id_val, pick.name)
        spare = len(candidates) - 1
        detail = '{0} slots'.format(slots)
        if spare:
            detail += ' - {0} other{1} would also fit'.format(
                spare, '' if spare == 1 else 's')
        if row.changed:
            row.status = 'changed'
            row.note = detail
            summary['assigned'] += 1
        else:
            row.status = ''
            row.note = detail + ' - already right'
            summary['already'] += 1

    return summary
