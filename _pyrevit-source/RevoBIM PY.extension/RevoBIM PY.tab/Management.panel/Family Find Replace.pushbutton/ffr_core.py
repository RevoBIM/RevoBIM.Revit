# -*- coding: utf-8 -*-
"""RevoBIM PY - Family Find & Replace : Revit-side core.

Everything that touches the document lives here.  No WPF, no pyRevit.
Runs on IronPython 2.7 and IronPython 3, Revit 2024 - 2027.
"""

import math
import os
import time

import clr

clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')

from Autodesk.Revit.DB import (
    BuiltInCategory,
    BuiltInParameter,
    CategoryType,
    Element,
    ElementId,
    ElementSet,
    ElementTransformUtils,
    FailureProcessingResult,
    FamilyInstance,
    FamilyInstanceFilter,
    FamilySymbol,
    FilteredElementCollector,
    Group,
    IFailuresPreprocessor,
    ImportInstance,
    IndependentTag,
    Level,
    Line,
    LocationCurve,
    LocationPoint,
    Options,
    Plane,
    Reference,
    SketchPlane,
    StorageType,
    SubTransaction,
    Transaction,
    TransactionGroup,
    UnitTypeId,
    UnitUtils,
    XYZ,
)
from Autodesk.Revit.DB.Electrical import ElectricalSystem, Wire
from Autodesk.Revit.DB.Structure import StructuralType
from Autodesk.Revit.UI.Selection import ISelectionFilter

clr.AddReference('mscorlib')
from System.Collections.Generic import List

# ---------------------------------------------------------------------------
# constants worth finding at the top of the file
# ---------------------------------------------------------------------------

#: parameters never offered for retention - the placement or the type drives them
EXCLUDED_PARAM_TOKENS = (
    'family and type', 'family', 'type id', 'type name',
    'level', 'host', 'reference level', 'schedule level',
    'elevation from level', 'offset from host', 'host id',
    'design option', 'edited by', 'phase created by',
    'image', 'moves with nearby elements',
)

#: Nothing is ticked by default.  Retention is a deliberate choice per run:
#: silently carrying a value across is the sort of thing that is only noticed
#: three drawings later, so the tool asks rather than guesses.
DEFAULT_RETAIN_TOKENS = ()

#: voltage comparison tolerance, in Revit internal units
VOLTAGE_TOL = 1.0e-6

#: Elements per transaction.  Small enough that a refused batch loses little
#: and progress moves visibly, large enough that commit overhead stays modest.
CHUNK_SIZE = 25

#: how far a placed instance may sit from the requested point before it is nudged
POINT_TOL_FT = 1.0e-6

#: guard against a runaway selection
MAX_ELEMENTS = 5000

#: how many elements are scanned for circuits while the window is being driven
CIRCUIT_SCAN_CAP = 500

MM_PER_FT = 304.8


# ---------------------------------------------------------------------------
# version-safe helpers
# ---------------------------------------------------------------------------

def eid_value(element_id):
    """ElementId.IntegerValue was dropped in Revit 2026 in favour of .Value."""
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


def mm_to_ft(value):
    return float(value) / MM_PER_FT


def ft_to_mm(value):
    return float(value) * MM_PER_FT


def volts(raw):
    """Internal electrical potential to volts, for display only."""
    try:
        return UnitUtils.ConvertFromInternalUnits(raw, UnitTypeId.Volt)
    except Exception:
        return raw


def fmt(template, *args):
    try:
        return template.format(*args)
    except Exception:
        return template


def elem_name(elem):
    try:
        return Element.Name.GetValue(elem)
    except Exception:
        pass
    try:
        return elem.Name
    except Exception:
        return ''


def signed_plan_angle(from_dir, to_dir):
    """Angle about +Z that turns from_dir onto to_dir."""
    dot = from_dir.X * to_dir.X + from_dir.Y * to_dir.Y
    cross = from_dir.X * to_dir.Y - from_dir.Y * to_dir.X
    return math.atan2(cross, dot)


# ---------------------------------------------------------------------------
# warning suppression
# ---------------------------------------------------------------------------

class WarningSwallower(IFailuresPreprocessor):
    """Deletes warnings raised during a run so nothing stops on a dialog."""

    def PreprocessFailures(self, accessor):
        try:
            for failure in accessor.GetFailureMessages():
                accessor.DeleteWarning(failure)
        except Exception:
            pass
        return FailureProcessingResult.Continue


class FamilyInstancePickFilter(ISelectionFilter):
    """Pick filter for manual selection - family instances only."""

    def __init__(self, category_id=None):
        self._category_id = category_id

    def AllowElement(self, element):
        try:
            if not isinstance(element, FamilyInstance):
                return False
            if self._category_id is None:
                return True
            return eid_value(element.Category.Id) == eid_value(self._category_id)
        except Exception:
            return False

    def AllowReference(self, reference, point):
        return False


# ---------------------------------------------------------------------------
# the model index : category -> family -> type
# ---------------------------------------------------------------------------

class TypeRecord(object):
    def __init__(self, symbol_id, type_name, family_name, category_name,
                 placement, count):
        self.symbol_id = symbol_id
        self.type_name = type_name
        self.family_name = family_name
        self.category_name = category_name
        self.placement = placement
        self.count = count
        self.is_import = False

    @property
    def label(self):
        # An import has no family/type split - the block name is the whole of
        # what it is called, and "LIGHT-01 : Import symbol" reads as noise.
        if self.is_import:
            return self.family_name
        return fmt('{0} : {1}', self.family_name, self.type_name)


def placement_name(symbol):
    try:
        return str(symbol.Family.FamilyPlacementType)
    except Exception:
        return 'Unknown'


def build_index(doc):
    """Every loadable family type in the project, keyed category > family."""
    index = {}
    counts = instance_counts(doc)
    collector = FilteredElementCollector(doc).OfClass(FamilySymbol)
    for symbol in collector:
        try:
            category = symbol.Category
            if category is None:
                continue
            if category.CategoryType != CategoryType.Model:
                continue
            family = symbol.Family
            if family is None:
                continue
            cat_name = category.Name
            fam_name = elem_name(family)
            typ_name = elem_name(symbol)
            sid = eid_value(symbol.Id)
            record = TypeRecord(
                symbol.Id, typ_name, fam_name, cat_name,
                placement_name(symbol), counts.get(sid, 0))
            index.setdefault(cat_name, {}).setdefault(fam_name, []).append(record)
        except Exception:
            continue
    for families in index.values():
        for records in families.values():
            records.sort(key=lambda r: r.type_name.lower())
    return index


def instance_counts(doc):
    """One pass over the model rather than a collector per type."""
    counts = {}
    collector = FilteredElementCollector(doc).OfClass(FamilyInstance)
    collector = collector.WhereElementIsNotElementType()
    for inst in collector:
        try:
            key = eid_value(inst.GetTypeId())
        except Exception:
            continue
        counts[key] = counts.get(key, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# finding the instances to replace
# ---------------------------------------------------------------------------

SCOPE_MODEL = 'model'
SCOPE_VIEW = 'view'
SCOPE_SELECTION = 'selection'


def collect_instances(doc, uidoc, symbol_id, scope):
    if symbol_id is None:
        return []
    try:
        if scope == SCOPE_SELECTION:
            ids = uidoc.Selection.GetElementIds()
            found = []
            for eid in ids:
                elem = doc.GetElement(eid)
                if isinstance(elem, FamilyInstance) and \
                        eid_value(elem.GetTypeId()) == eid_value(symbol_id):
                    found.append(elem)
            return found
        if scope == SCOPE_VIEW and uidoc.ActiveView is not None:
            collector = FilteredElementCollector(doc, uidoc.ActiveView.Id)
        else:
            collector = FilteredElementCollector(doc)
        collector = collector.WherePasses(FamilyInstanceFilter(doc, symbol_id))
        return list(collector)
    except Exception:
        return []


# ---------------------------------------------------------------------------
# parameters
# ---------------------------------------------------------------------------

class ParamInfo(object):
    def __init__(self, name, storage, is_shared, guid, sample, definition):
        self.name = name
        self.storage = storage
        self.is_shared = is_shared
        self.guid = guid
        self.sample = sample
        self.definition = definition


def _excluded(name):
    low = name.lower()
    for token in EXCLUDED_PARAM_TOKENS:
        if low == token or low.startswith(token):
            return True
    return False


def _sample_text(param):
    try:
        if param.StorageType == StorageType.String:
            return param.AsString() or ''
        text = param.AsValueString()
        if text:
            return text
        if param.StorageType == StorageType.Integer:
            return str(param.AsInteger())
        if param.StorageType == StorageType.Double:
            return str(round(param.AsDouble(), 4))
        if param.StorageType == StorageType.ElementId:
            target = param.Element.Document.GetElement(param.AsElementId())
            return elem_name(target) if target is not None else ''
    except Exception:
        pass
    return ''


def read_param_infos(instance):
    """Writable instance parameters on a placed element, keyed by name."""
    infos = {}
    try:
        params = instance.Parameters
    except Exception:
        return infos
    for param in params:
        try:
            if param.IsReadOnly:
                continue
            definition = param.Definition
            if definition is None:
                continue
            name = definition.Name
            if not name or _excluded(name):
                continue
            guid = ''
            try:
                if param.IsShared:
                    guid = str(param.GUID)
            except Exception:
                guid = ''
            infos[name] = ParamInfo(
                name, param.StorageType, bool(guid), guid,
                _sample_text(param), definition)
        except Exception:
            continue
    return infos


class ParamRow(object):
    """One line in the retain list."""

    def __init__(self, name, storage, is_shared, sample, on_target, note):
        self.name = name
        self.storage = storage
        self.is_shared = is_shared
        self.sample = sample
        self.on_target = on_target
        self.note = note
        self.checked = False


def build_param_rows(source_infos, target_infos):
    """One row per writable instance parameter on the original.

    target_infos is None until a replacement family has been read, and in that
    state every row is offered rather than greyed out - the ticks are kept and
    re-tested the moment the replacement is chosen.
    """
    unknown = target_infos is None
    if unknown:
        target_infos = {}
    rows = []
    for name in sorted(source_infos.keys(), key=lambda n: n.lower()):
        src = source_infos[name]
        tgt = target_infos.get(name)
        note = ''
        on_target = unknown or tgt is not None
        if unknown:
            note = 'replacement family not chosen yet'
        elif not on_target:
            note = 'not on the replacement family'
        elif tgt.storage != src.storage:
            on_target = False
            note = fmt('type mismatch - {0} vs {1}',
                       str(src.storage), str(tgt.storage))
        row = ParamRow(name, str(src.storage), src.is_shared,
                       src.sample, on_target, note)
        # Off unless the caller ticks it.  DEFAULT_RETAIN_TOKENS is empty by
        # design; put names back into it to have some pre-ticked again.
        if on_target and DEFAULT_RETAIN_TOKENS:
            low = name.lower()
            row.checked = any(low.startswith(token)
                              for token in DEFAULT_RETAIN_TOKENS)
        rows.append(row)
    return rows


def find_target_param(element, name, guid):
    param = None
    if guid:
        try:
            from System import Guid
            param = element.get_Parameter(Guid(guid))
        except Exception:
            param = None
    if param is None:
        try:
            params = element.GetParameters(name)
            if params and params.Count > 0:
                for candidate in params:
                    if not candidate.IsReadOnly:
                        param = candidate
                        break
                if param is None:
                    param = params[0]
        except Exception:
            param = None
    if param is None:
        try:
            param = element.LookupParameter(name)
        except Exception:
            param = None
    return param


def copy_parameter(source, target, name):
    """Copy one instance parameter by name. Returns (ok, message)."""
    try:
        src_params = source.GetParameters(name)
    except Exception:
        src_params = None
    src = None
    if src_params:
        for candidate in src_params:
            src = candidate
            break
    if src is None:
        try:
            src = source.LookupParameter(name)
        except Exception:
            src = None
    if src is None:
        return False, fmt('{0}: not found on the original', name)

    guid = ''
    try:
        if src.IsShared:
            guid = str(src.GUID)
    except Exception:
        guid = ''

    dst = find_target_param(target, name, guid)
    if dst is None:
        return False, fmt('{0}: not on the replacement', name)
    if dst.IsReadOnly:
        return False, fmt('{0}: read only on the replacement', name)
    if dst.StorageType != src.StorageType:
        return False, fmt('{0}: storage type differs', name)

    try:
        storage = src.StorageType
        if storage == StorageType.String:
            dst.Set(src.AsString() or '')
        elif storage == StorageType.Integer:
            dst.Set(src.AsInteger())
        elif storage == StorageType.Double:
            dst.Set(src.AsDouble())
        elif storage == StorageType.ElementId:
            dst.Set(src.AsElementId())
        else:
            return False, fmt('{0}: unsupported storage type', name)
        return True, ''
    except Exception as err:
        return False, fmt('{0}: {1}', name, err)


def carry_workset(source, target):
    """Put the replacement on the workset the original sat on.

    House style puts new elements on the workset of the first element picked,
    but a swap is per element: each replacement belongs where its own original
    was, or a run across several worksets quietly consolidates them onto one.
    Silent no-op on a model that is not workshared.
    """
    try:
        src = source.get_Parameter(BuiltInParameter.ELEM_PARTITION_PARAM)
        dst = target.get_Parameter(BuiltInParameter.ELEM_PARTITION_PARAM)
    except Exception:
        return True, ''
    if src is None or dst is None:
        return True, ''
    if dst.IsReadOnly:
        return False, 'workset is read only on the replacement'
    try:
        wanted = src.AsInteger()
        if dst.AsInteger() != wanted:
            dst.Set(wanted)
        return True, ''
    except Exception as err:
        return False, fmt('workset: {0}', err)


def carry_phasing(source, target):
    """Copy Phase Created and Phase Demolished onto the replacement.

    A new instance takes the phase of the view it was created in, which is not
    necessarily the phase the original was on.  Circuits are phase-aware, so a
    replacement left on the wrong phase is refused by AddToCircuit for a reason
    that reads as nothing to do with phasing.  Carried always, like the
    workset, rather than offered as a tickable parameter.
    """
    problems = []
    for bip in (BuiltInParameter.PHASE_CREATED,
                BuiltInParameter.PHASE_DEMOLISHED):
        try:
            src = source.get_Parameter(bip)
            dst = target.get_Parameter(bip)
        except Exception:
            continue
        if src is None or dst is None or dst.IsReadOnly:
            continue
        if src.StorageType != StorageType.ElementId:
            continue
        try:
            wanted = src.AsElementId()
            if eid_value(dst.AsElementId()) != eid_value(wanted):
                dst.Set(wanted)
        except Exception as err:
            problems.append(fmt('phasing: {0}', err))
    return (not problems), '; '.join(problems)


# ---------------------------------------------------------------------------
# electrical
# ---------------------------------------------------------------------------

ELEC_NONE = 'none'
ELEC_RETAIN = 'retain'
ELEC_REVIEW = 'review'
ELEC_UNCIRCUITABLE = 'uncircuitable'


class ElecProfile(object):
    def __init__(self):
        self.has_connector = False
        self.system_types = []
        self.poles = None
        self.voltage = None
        self.load_classification = ''
        self.circuits = 0


def _connector_list(instance):
    connectors = []
    try:
        model = instance.MEPModel
        if model is None:
            return connectors
        manager = model.ConnectorManager
        if manager is None:
            return connectors
        for connector in manager.Connectors:
            connectors.append(connector)
    except Exception:
        pass
    return connectors


def electrical_systems(instance):
    """Circuits the element sits on, as ElectricalSystem elements.

    Four routes, because which one answers varies with the release and with
    what the element is.  The last is a document-wide scan that asks each
    circuit for its own members - slower, but it does not depend on MEPModel
    handing back anything at all, and it is the one that catches the cases the
    others quietly miss.
    """
    found = []
    seen = {}

    def keep(item, doc):
        if item is None:
            return
        try:
            system = doc.GetElement(item) if isinstance(item, ElementId) else item
        except Exception:
            system = item
        if system is None:
            return
        key = eid_value(system.Id)
        if key in seen:
            return
        seen[key] = True
        found.append(system)

    try:
        doc = instance.Document
    except Exception:
        return found

    model = None
    try:
        model = instance.MEPModel
    except Exception:
        model = None

    if model is not None:
        for route in ('GetElectricalSystems', 'GetAssignedElectricalSystems'):
            getter = getattr(model, route, None)
            if getter is None:
                continue
            try:
                raw = getter()
            except Exception:
                continue
            if raw is None:
                continue
            try:
                for item in raw:
                    keep(item, doc)
            except Exception:
                continue
        if not found:
            try:
                for item in model.ElectricalSystems:
                    keep(item, doc)
            except Exception:
                pass

    if found:
        return found

    # Nothing came back.  Ask every circuit in the document whether it holds
    # this element.  Cached per document, because the run calls this once per
    # element and a bare collector each time is unusable at any real count.
    target = eid_value(instance.Id)
    for system in _circuit_index(doc).get(target, []):
        keep(system, doc)
    return found


_CIRCUIT_INDEX = {}


def reset_run_caches():
    """Drop everything cached for the length of one run.

    The circuit member map and the sketch planes created for work plane based
    replacements. Both are keyed on document state, so carrying either across a
    model edit would be wrong.
    """
    _CIRCUIT_INDEX.clear()
    _SKETCH_CACHE.clear()
    _TAG_INDEX.clear()



def _circuit_index(doc):
    """element id -> the circuits holding it, built once per run."""
    key = eid_value(doc.ProjectInformation.Id) if doc is not None else 0
    cached = _CIRCUIT_INDEX.get(key)
    if cached is not None:
        return cached
    index = {}
    try:
        collector = FilteredElementCollector(doc).OfClass(ElectricalSystem)
        for system in collector:
            for member_id in circuit_members(system):
                index.setdefault(member_id, []).append(system)
    except Exception:
        pass
    _CIRCUIT_INDEX[key] = index
    return index


def circuit_members(system):
    """The element ids on a circuit, whichever way the release reports them."""
    ids = []
    for route in ('GetCircuitElements', 'Elements'):
        try:
            raw = getattr(system, route, None)
            if raw is None:
                continue
            if route == 'GetCircuitElements':
                raw = raw()
            for item in raw:
                if isinstance(item, ElementId):
                    ids.append(eid_value(item))
                else:
                    ids.append(eid_value(item.Id))
            if ids:
                return ids
        except Exception:
            continue
    return ids


def on_circuit(system, element_id):
    return eid_value(element_id) in circuit_members(system)


def electrical_profile(instance):
    profile = ElecProfile()
    for connector in _connector_list(instance):
        try:
            if str(connector.Domain) != 'DomainElectrical':
                continue
        except Exception:
            continue
        profile.has_connector = True
        try:
            system_type = str(connector.ElectricalSystemType)
            if system_type not in profile.system_types:
                profile.system_types.append(system_type)
        except Exception:
            pass
        for attr in ('NumberOfPoles', 'PolesNumber'):
            try:
                value = getattr(connector, attr)
                if value:
                    profile.poles = int(value)
                    break
            except Exception:
                continue
        try:
            voltage = connector.Voltage
            if voltage:
                profile.voltage = float(voltage)
        except Exception:
            pass

    if profile.poles is None:
        profile.poles = _param_int(instance, BuiltInParameter.RBS_ELEC_NUMBER_OF_POLES)
    if profile.voltage is None:
        profile.voltage = _param_double(instance, BuiltInParameter.RBS_ELEC_VOLTAGE)

    profile.circuits = len(electrical_systems(instance))
    return profile


def _param_int(element, bip):
    for source in (element, element.Document.GetElement(element.GetTypeId())):
        try:
            param = source.get_Parameter(bip)
            if param is not None and param.HasValue:
                return int(param.AsInteger())
        except Exception:
            continue
    return None


def _param_double(element, bip):
    for source in (element, element.Document.GetElement(element.GetTypeId())):
        try:
            param = source.get_Parameter(bip)
            if param is not None and param.HasValue:
                return float(param.AsDouble())
        except Exception:
            continue
    return None


def compare_electrical(source, target, circuited_count):
    """Returns (state, headline, detail lines)."""
    lines = []
    if circuited_count <= 0:
        return (ELEC_NONE, 'No circuits on the originals',
                ['Nothing to carry across - the replacement is a plain swap.'])

    if not target.has_connector:
        return (ELEC_UNCIRCUITABLE, 'Replacement cannot be circuited',
                ['The replacement family has no electrical connector, so the '
                 'circuits on the originals cannot be carried across.',
                 'Running the replace will drop them.'])

    mismatch = False

    if source.system_types and target.system_types:
        shared = [s for s in source.system_types if s in target.system_types]
        if not shared:
            mismatch = True
            lines.append(fmt('System type: {0} on the original, {1} on the '
                             'replacement.',
                             ', '.join(source.system_types),
                             ', '.join(target.system_types)))

    if source.poles is not None and target.poles is not None:
        if int(source.poles) != int(target.poles):
            mismatch = True
            lines.append(fmt('Poles: {0} on the original, {1} on the '
                             'replacement.', source.poles, target.poles))

    if source.voltage is not None and target.voltage is not None:
        if abs(float(source.voltage) - float(target.voltage)) > VOLTAGE_TOL:
            mismatch = True
            lines.append(fmt('Voltage: {0}V on the original, {1}V on the '
                             'replacement.',
                             round(volts(source.voltage), 1),
                             round(volts(target.voltage), 1)))

    if mismatch:
        lines.append('Revit will refuse the circuit, or accept it and put the '
                     'panel schedule out. Check the two families before you run.')
        return (ELEC_REVIEW, 'Review electrical data', lines)

    detail = [fmt('{0} circuit(s) found on the originals.', circuited_count)]
    if target.system_types:
        detail.append(fmt('Connector: {0}.', ', '.join(target.system_types)))
    if target.poles is not None:
        detail.append(fmt('Poles: {0}.', target.poles))
    if target.voltage is not None:
        detail.append(fmt('Voltage: {0}V.', round(volts(target.voltage), 1)))
    detail.append('Each replacement joins its circuit before the original is '
                  'deleted, so the circuit is never emptied.')
    return (ELEC_RETAIN, 'Retain circuits', detail)


def _add_routes(system, element):
    """Every signature AddToCircuit has carried, newest first.

    The ElementSet form is the one that was missing in 1.0.x: several releases
    expose only that, so a List[ElementId] threw, the exception was swallowed,
    and the circuit was reported as refused when the call had simply been made
    the wrong way round.
    """
    def as_id_list():
        ids = List[ElementId]()
        ids.Add(element.Id)
        system.AddToCircuit(ids)

    def as_element_set():
        group = ElementSet()
        group.Insert(element)
        system.AddToCircuit(group)

    def as_element():
        system.AddToCircuit(element)

    def as_id():
        system.AddToCircuit(element.Id)

    return (('element id list', as_id_list),
            ('element set', as_element_set),
            ('element', as_element),
            ('element id', as_id))


def transfer_circuits(doc, systems, new_element):
    """Put the replacement onto every circuit the original sat on.

    Returns (joined, problems).  Every add is verified by reading the circuit's
    own member list back afterwards - a call that does not throw has still not
    necessarily done anything, and a circuit silently dropped is the one
    failure of this tool that costs real work to find later.
    """
    joined = 0
    problems = []
    for system in systems:
        label = circuit_label(system)
        if on_circuit(system, new_element.Id):
            joined += 1
            continue

        errors = []
        done = False
        for route_name, route in _add_routes(system, new_element):
            try:
                route()
            except Exception as err:
                errors.append(fmt('{0}: {1}', route_name, err))
                continue
            # Verify rather than trust.  Regenerate first, or the member list
            # can still read as it did before the add.
            try:
                doc.Regenerate()
            except Exception:
                pass
            if on_circuit(system, new_element.Id):
                done = True
                break
            errors.append(fmt('{0}: accepted but the circuit did not take it',
                              route_name))

        if done:
            joined += 1
        else:
            # Prefer "accepted but did not take" over a signature complaint
            # from whichever route happened to be tried last - the first says
            # something about the model, the second only about the API.
            detail = ''
            for text in errors:
                if 'did not take' in text:
                    detail = text
                    break
            if not detail:
                detail = errors[-1] if errors else 'no route was accepted'
            problems.append(fmt('{0} would not take the replacement ({1})',
                                label, detail))
    return joined, problems


def circuit_label(system):
    """Panel and circuit number, which is how the circuit reads on a schedule."""
    panel = ''
    number = ''
    try:
        panel = system.PanelName or ''
    except Exception:
        panel = ''
    try:
        number = system.CircuitNumber or ''
    except Exception:
        number = ''
    if panel and number:
        return fmt('circuit {0}-{1}', panel, number)
    if panel:
        return fmt('circuit on {0}', panel)
    if number:
        return fmt('circuit {0}', number)
    return fmt('circuit {0}', eid_value(system.Id))


# ---------------------------------------------------------------------------
# groups
# ---------------------------------------------------------------------------

class GroupWork(object):
    """One group type that holds the family being replaced."""

    def __init__(self, type_id, type_name):
        self.type_id = type_id
        self.type_name = type_name
        self.group_ids = []      # every placed instance of that type
        self.targets = 0         # how many of the family sit in one instance


def survey_groups(doc, instances, source_types):
    """Split the selection into loose elements and the group types involved.

    Every instance of an affected group type is listed, not only the ones the
    scope picked up.  A group type is a single definition shared by all its
    instances: changing what is inside it changes every one of them, project
    wide, whatever the scope says.  Pretending otherwise would be the tool
    lying about what it is about to do.
    """
    loose = []
    work = {}
    for element in instances:
        group_id = None
        try:
            group_id = element.GroupId
        except Exception:
            group_id = None
        if group_id is None or eid_value(group_id) <= 0:
            loose.append(element)
            continue
        group = doc.GetElement(group_id)
        if group is None:
            loose.append(element)
            continue
        try:
            group_type = group.GroupType
            type_id = eid_value(group_type.Id)
        except Exception:
            loose.append(element)
            continue
        item = work.get(type_id)
        if item is None:
            item = GroupWork(group_type.Id, elem_name(group_type))
            item.group_ids = _instances_of_group_type(doc, group_type)
            work[type_id] = item
        item.targets += 1

    # How many of the family sit across *all* instances of each type, not only
    # the ones the scope picked up - that is the number the confirmation should
    # be quoting, because that is the work.
    wanted = _as_type_id_set(source_types)
    if wanted:
        for item in work.values():
            total = 0
            for group_id in item.group_ids:
                group = doc.GetElement(group_id)
                if group is None:
                    continue
                total += len(group_member_targets(doc, group, wanted))
            if total:
                item.targets = total
    return loose, list(work.values())


def _as_type_id_set(source_types):
    """Accept a set, a list, a single id or a single ElementId."""
    if source_types is None:
        return set()
    if isinstance(source_types, (set, frozenset, list, tuple)):
        return set([eid_value(item) if not isinstance(item, int) else item
                    for item in source_types])
    if isinstance(source_types, int):
        return set([source_types])
    return set([eid_value(source_types)])


def _instances_of_group_type(doc, group_type):
    ids = []
    try:
        for group in group_type.Groups:
            ids.append(group.Id)
    except Exception:
        pass
    if ids:
        return ids
    # Older releases without GroupType.Groups: scan for them.
    wanted = eid_value(group_type.Id)
    try:
        collector = FilteredElementCollector(doc).OfClass(Group)
        for group in collector:
            try:
                if eid_value(group.GroupType.Id) == wanted:
                    ids.append(group.Id)
            except Exception:
                continue
    except Exception:
        pass
    return ids


def count_group_instances(work_items):
    total = 0
    for item in work_items:
        total += len(item.group_ids)
    return total


def group_member_targets(doc, group, source_type_ids):
    """The ids inside a group that are of the family being replaced."""
    found = []
    try:
        member_ids = group.GetMemberIds()
    except Exception:
        return found
    for member_id in member_ids:
        element = doc.GetElement(member_id)
        if element is None or not isinstance(element, FamilyInstance):
            continue
        try:
            if eid_value(element.GetTypeId()) in source_type_ids:
                found.append(member_id)
        except Exception:
            continue
    return found


def _swap_members(doc, member_ids, symbol, source_type_ids, retain_names,
                  z_offset_ft, match_orientation, extra_radians, report,
                  level_below_point, retain_circuits, retain_tags,
                  retain_wires, problems):
    """Run the ordinary swap over one ungrouped set. Returns the final ids."""
    final = []
    swapped = 0
    for member_id in member_ids:
        element = doc.GetElement(member_id)
        if element is None:
            continue
        if isinstance(element, Group):
            # A nested group would need the whole routine again, one level
            # down. Left alone and reported rather than half handled.
            problems.append('a nested group was left alone - the family '
                            'inside it was not replaced')
            final.append(member_id)
            continue
        is_target = False
        try:
            is_target = (isinstance(element, FamilyInstance) and
                         eid_value(element.GetTypeId()) in source_type_ids)
        except Exception:
            is_target = False
        if not is_target:
            final.append(member_id)
            continue

        before = len(report.new_ids)
        ok, message = _replace_one(
            doc, element, symbol, retain_names, z_offset_ft,
            match_orientation, extra_radians, report,
            level_below_point, retain_circuits, retain_tags, retain_wires,
            True)
        if ok and len(report.new_ids) > before:
            final.append(report.new_ids[-1])
            swapped += 1
        else:
            problems.append(message or
                            'an element in the group would not replace')
            final.append(member_id)
    return final, swapped


def _witness_point(doc, group, type_ids):
    """Where one member of a given type sits, used to prove nothing shifted."""
    for member_id in group_member_targets(doc, group, type_ids):
        element = doc.GetElement(member_id)
        point = instance_point(element)
        if point is not None:
            return point
    return None


def replace_in_group_type(doc, item, symbol, source_type_ids, retain_names,
                          z_offset_ft, match_orientation, extra_radians,
                          report, level_below_point, retain_circuits,
                          retain_tags, retain_wires):
    """Swap the family inside every instance of one group type.

    There is no edit-group-in-place in the API, so one instance is taken apart,
    changed, and put back as a new type, and the other instances are moved onto
    that type. That is the fast route: the swap itself runs once for the type
    rather than once per instance, which on a type placed forty times is forty
    times less work.

    The risk in it is that regrouping computes a fresh group origin, and moving
    an instance to a type whose origin sits somewhere else can shift its
    contents. So the first reassignment is checked against a witness point
    taken before it, and if anything moved the caller is told to take the slow
    route instead.
    """
    problems = []
    if not item.group_ids:
        return 0, problems, 0, False

    detail_groups = 0
    for group_id in item.group_ids:
        group = doc.GetElement(group_id)
        if group is None:
            continue
        try:
            attached = group.GetAvailableAttachedDetailGroupTypeIds()
            if attached is not None and len(attached):
                detail_groups += 1
        except Exception:
            pass

    first = doc.GetElement(item.group_ids[0])
    if first is None:
        return 0, ['the group instance has gone'], detail_groups, False

    # Witnesses for every other instance, taken while they are still intact.
    witnesses = {}
    for group_id in item.group_ids[1:]:
        group = doc.GetElement(group_id)
        if group is None:
            continue
        point = _witness_point(doc, group, source_type_ids)
        if point is not None:
            witnesses[eid_value(group_id)] = point

    pinned = _unpin_group(first)
    try:
        members = list(first.UngroupMembers())
    except Exception as err:
        return 0, [fmt('the group would not ungroup: {0}', err)], \
            detail_groups, False
    doc.Regenerate()

    final, swapped = _swap_members(
        doc, members, symbol, source_type_ids, retain_names, z_offset_ft,
        match_orientation, extra_radians, report, level_below_point,
        retain_circuits, retain_tags, retain_wires, problems)

    if not swapped:
        return 0, problems, detail_groups, False

    doc.Regenerate()

    ids = List[ElementId]()
    for element_id in final:
        if doc.GetElement(element_id) is not None:
            ids.Add(element_id)
    if not ids.Count:
        return 0, problems + ['the group had nothing left to re-form'], \
            detail_groups, False
    try:
        rebuilt = doc.Create.NewGroup(ids)
    except Exception as err:
        return 0, problems + [fmt('the group would not re-form: {0}', err)], \
            detail_groups, False
    doc.Regenerate()

    if pinned:
        _repin_group(rebuilt)

    try:
        new_type = rebuilt.GroupType
    except Exception:
        new_type = None
    if new_type is None:
        return swapped, problems + ['the re-formed group has no type'], \
            detail_groups, False

    # Move every other instance onto the new type, checking the first one.
    checked = False
    for group_id in item.group_ids[1:]:
        group = doc.GetElement(group_id)
        if group is None:
            continue
        was_pinned = _unpin_group(group)
        try:
            group.GroupType = new_type
        except Exception as err:
            problems.append(fmt('an instance kept its own type: {0}', err))
            if was_pinned:
                _repin_group(group)
            continue
        doc.Regenerate()
        if was_pinned:
            _repin_group(group)

        if checked:
            continue
        checked = True
        wanted = witnesses.get(eid_value(group_id))
        if wanted is None:
            continue
        landed = _witness_point(doc, group, set([eid_value(symbol.Id)]))
        if landed is None:
            # Cannot prove it, so do not claim it.
            problems.append('an instance could not be checked for movement '
                            'after being moved to the new type')
            return swapped, problems, detail_groups, True
        if landed.DistanceTo(wanted) > POINT_TOL_FT * 100.0:
            # It shifted. The caller rolls this back and takes the slow route,
            # which rebuilds every instance in place and cannot shift anything.
            return swapped, problems, detail_groups, True

    _retire_old_group_type(doc, item, new_type, problems)
    return swapped, problems, detail_groups, False


def replace_in_group_type_slow(doc, item, symbol, source_type_ids,
                               retain_names, z_offset_ft, match_orientation,
                               extra_radians, report, level_below_point,
                               retain_circuits, retain_tags, retain_wires):
    """The careful route: rebuild every instance in place, then unify.

    Slower - the swap runs once per instance rather than once per type - but
    every instance's members are regrouped exactly where they already were, so
    identical inputs give identical origins and nothing can move. Used only
    when the fast route has been caught shifting something.
    """
    problems = []
    pinned = {}
    sets = []
    detail_groups = 0

    for group_id in item.group_ids:
        group = doc.GetElement(group_id)
        if group is None:
            continue
        try:
            attached = group.GetAvailableAttachedDetailGroupTypeIds()
            if attached is not None and len(attached):
                detail_groups += 1
        except Exception:
            pass
        if _unpin_group(group):
            pinned[eid_value(group_id)] = True
        try:
            sets.append(list(group.UngroupMembers()))
        except Exception as err:
            problems.append(fmt('group {0} would not ungroup: {1}',
                                eid_value(group_id), err))
    if not sets:
        return 0, problems, detail_groups

    doc.Regenerate()

    swapped = 0
    rebuilt = []
    for members in sets:
        final, count = _swap_members(
            doc, members, symbol, source_type_ids, retain_names, z_offset_ft,
            match_orientation, extra_radians, report, level_below_point,
            retain_circuits, retain_tags, retain_wires, problems)
        swapped += count
        rebuilt.append(final)

    doc.Regenerate()

    made = []
    for final in rebuilt:
        ids = List[ElementId]()
        for element_id in final:
            if doc.GetElement(element_id) is not None:
                ids.Add(element_id)
        if not ids.Count:
            continue
        try:
            made.append(doc.Create.NewGroup(ids))
        except Exception as err:
            problems.append(fmt('a group would not re-form: {0}', err))
    if not made:
        return swapped, problems, detail_groups

    doc.Regenerate()
    keeper = made[0]
    try:
        new_type = keeper.GroupType
    except Exception:
        new_type = None
    if new_type is not None:
        for group in made[1:]:
            try:
                group.GroupType = new_type
            except Exception as err:
                problems.append(fmt('a re-formed group kept its own type: {0}',
                                    err))
        _retire_old_group_type(doc, item, new_type, problems)
    for group in made:
        if pinned:
            _repin_group(group)
    return swapped, problems, detail_groups


def _unpin_group(group):
    try:
        if group.Pinned:
            group.Pinned = False
            return True
    except Exception:
        pass
    return False


def _repin_group(group):
    try:
        group.Pinned = True
    except Exception:
        pass


def _retire_old_group_type(doc, item, new_type, problems):
    """Delete the emptied original type and take its name back."""
    try:
        old_type = doc.GetElement(item.type_id)
        if old_type is not None:
            doc.Delete(old_type.Id)
            doc.Regenerate()
    except Exception:
        pass
    if not set_element_name(new_type, item.type_name):
        problems.append(fmt(
            'the re-formed group type could not be renamed back to "{0}" and '
            'is called "{1}"', item.type_name, elem_name(new_type)))


def set_element_name(element, name):
    """Rename, then read it back - neither route reliably raises on failure."""
    for attempt in (0, 1):
        try:
            if attempt == 0:
                element.Name = name
            else:
                Element.Name.SetValue(element, name)
        except Exception:
            continue
        if elem_name(element) == name:
            return True
    return elem_name(element) == name


# ---------------------------------------------------------------------------
# tags
# ---------------------------------------------------------------------------

_TAG_INDEX = {}


def _tag_index(doc):
    """tagged element id -> the tags pointing at it, built once per run.

    One collector for the whole document rather than one per element: a run
    over a few hundred fittings would otherwise walk every tag in the model a
    few hundred times.
    """
    key = eid_value(doc.ProjectInformation.Id) if doc is not None else 0
    cached = _TAG_INDEX.get(key)
    if cached is not None:
        return cached
    index = {}
    try:
        collector = FilteredElementCollector(doc).OfClass(IndependentTag)
        for tag in collector:
            for tagged in _tagged_ids(tag):
                index.setdefault(tagged, []).append(tag)
    except Exception:
        pass
    _TAG_INDEX[key] = index
    return index


def _tagged_ids(tag):
    """Which elements a tag points at, across the multi-reference API change."""
    ids = []
    getter = getattr(tag, 'GetTaggedLocalElementIds', None)
    if getter is not None:
        try:
            for item in getter():
                ids.append(eid_value(item))
            return ids
        except Exception:
            ids = []
    # Pre-2022 single-reference form.
    try:
        ids.append(eid_value(tag.TaggedLocalElementId))
    except Exception:
        pass
    return ids


def tags_on(doc, instance):
    return list(_tag_index(doc).get(eid_value(instance.Id), []))


def transfer_tags(doc, tags, old_element, new_element):
    """Point the originals' tags at the replacement.

    Re-pointing is preferred over recreating because it keeps the tag's head
    position, its leader and any elbow the user dragged. Recreating is the
    fallback, and it only keeps the head position.

    Done before the original is deleted: Revit removes a tag whose only
    referenced element has gone, so a tag moved afterwards is a tag that no
    longer exists.
    """
    moved = 0
    problems = []
    if not tags:
        return moved, problems

    try:
        new_ref = Reference(new_element)
    except Exception as err:
        return moved, [fmt('the replacement gave no reference to tag ({0})',
                           err)]

    old_id = eid_value(old_element.Id)

    for tag in tags:
        if _repoint_tag(doc, tag, new_ref, old_id):
            moved += 1
            continue
        if _recreate_tag(doc, tag, new_element, new_ref):
            moved += 1
            continue
        problems.append(fmt('tag {0} could not be moved to the replacement',
                            eid_value(tag.Id)))
    return moved, problems


def _repoint_tag(doc, tag, new_ref, old_id):
    """Add the replacement to the tag, then drop the original."""
    add = getattr(tag, 'AddReferences', None)
    remove = getattr(tag, 'RemoveReferences', None)
    if add is None or remove is None:
        return False
    try:
        refs = List[Reference]()
        refs.Add(new_ref)
        add(refs)
    except Exception:
        return False
    try:
        doc.Regenerate()
    except Exception:
        pass
    # Drop the reference to the original so the tag does not read as tagging
    # two things, one of which is about to disappear.
    try:
        stale = List[Reference]()
        for ref in tag.GetTaggedReferences():
            if eid_value(ref.ElementId) == old_id:
                stale.Add(ref)
        if stale.Count:
            remove(stale)
    except Exception:
        pass
    return eid_value(new_ref.ElementId) in _tagged_ids(tag)


def _recreate_tag(doc, tag, new_element, new_ref):
    """Make an equivalent tag on the replacement and delete the old one."""
    try:
        view_id = tag.OwnerViewId
        head = tag.TagHeadPosition
        leader = bool(tag.HasLeader)
        type_id = tag.GetTypeId()
    except Exception:
        return False
    try:
        orientation = tag.TagOrientation
    except Exception:
        orientation = None
    made = None
    try:
        if orientation is not None:
            made = IndependentTag.Create(doc, type_id, view_id, new_ref,
                                         leader, orientation, head)
        else:
            made = IndependentTag.Create(doc, type_id, view_id, new_ref,
                                         leader, head)
    except Exception:
        made = None
    if made is None:
        return False
    try:
        doc.Delete(tag.Id)
    except Exception:
        pass
    return True


# ---------------------------------------------------------------------------
# wires
# ---------------------------------------------------------------------------

class WireLink(object):
    """One end of one wire, and where it met the original."""

    def __init__(self, wire_id, wire_connector_origin, system_type):
        self.wire_id = wire_id
        self.origin = wire_connector_origin
        self.system_type = system_type


def wire_links(doc, instance):
    """Every wire end physically connected to this element.

    Circuits and wires are separate things: putting the replacement on the
    circuit says nothing about the Wire elements drawn on the plan, which stay
    pointing at the original and dangle once it is deleted.
    """
    links = []
    seen = {}
    for connector in _connector_list(instance):
        try:
            if str(connector.Domain) != 'DomainElectrical':
                continue
        except Exception:
            continue
        try:
            system_type = str(connector.ElectricalSystemType)
        except Exception:
            system_type = ''
        try:
            refs = connector.AllRefs
        except Exception:
            continue
        for other in refs:
            try:
                owner = other.Owner
            except Exception:
                continue
            if owner is None or not isinstance(owner, Wire):
                continue
            key = (eid_value(owner.Id), _origin_key(other))
            if key in seen:
                continue
            seen[key] = True
            try:
                origin = other.Origin
            except Exception:
                origin = None
            links.append(WireLink(owner.Id, origin, system_type))
    return links


def _origin_key(connector):
    try:
        origin = connector.Origin
        return (int(round(origin.X * 1000)), int(round(origin.Y * 1000)),
                int(round(origin.Z * 1000)))
    except Exception:
        return (0, 0, 0)


def transfer_wires(doc, links, old_element, new_element):
    """Move each wire end off the original and onto the replacement.

    Reconnected before the original is deleted, and the wire's own end vertex
    is dragged onto the replacement's connector so the wire is drawn to where
    the new device actually is rather than left reaching for where the old one
    was.
    """
    moved = 0
    problems = []
    if not links:
        return moved, problems

    targets = []
    for connector in _connector_list(new_element):
        try:
            if str(connector.Domain) == 'DomainElectrical':
                targets.append(connector)
        except Exception:
            continue
    if not targets:
        return moved, [fmt('{0} wire end(s) could not move - the replacement '
                           'has no electrical connector', len(links))]

    old_connectors = [c for c in _connector_list(old_element)]

    for link in links:
        wire = doc.GetElement(link.wire_id)
        if wire is None:
            continue
        target = _pick_wire_target(targets, link)
        if target is None:
            problems.append(fmt('wire {0}: no matching connector on the '
                                'replacement', eid_value(link.wire_id)))
            continue
        wire_connector = _wire_connector_at(wire, link.origin)
        if wire_connector is None:
            problems.append(fmt('wire {0}: its end could not be found again',
                                eid_value(link.wire_id)))
            continue
        if _relink_wire(doc, wire, wire_connector, old_connectors, target):
            moved += 1
        else:
            problems.append(fmt('wire {0} would not reconnect',
                                eid_value(link.wire_id)))
    return moved, problems


def _pick_wire_target(targets, link):
    """Prefer a connector of the same system type, else the first one."""
    for connector in targets:
        try:
            if str(connector.ElectricalSystemType) == link.system_type:
                return connector
        except Exception:
            continue
    return targets[0] if targets else None


def _wire_connector_at(wire, origin):
    """The wire's connector nearest where it met the original."""
    best = None
    best_gap = None
    try:
        manager = wire.ConnectorManager
        connectors = list(manager.Connectors)
    except Exception:
        return None
    for connector in connectors:
        if origin is None:
            return connector
        try:
            gap = connector.Origin.DistanceTo(origin)
        except Exception:
            continue
        if best_gap is None or gap < best_gap:
            best = connector
            best_gap = gap
    return best


def _relink_wire(doc, wire, wire_connector, old_connectors, target):
    # Free the end first: a connector already joined to something will not
    # take a second connection.
    for old in old_connectors:
        try:
            if wire_connector.IsConnectedTo(old):
                wire_connector.DisconnectFrom(old)
        except Exception:
            continue
    try:
        wire_connector.ConnectTo(target)
    except Exception:
        return False
    _drag_wire_end(wire, wire_connector, target)
    return True


def _drag_wire_end(wire, wire_connector, target):
    """Move the wire's end vertex onto the replacement's connector."""
    try:
        count = wire.NumberOfVertices
        if count < 2:
            return
        origin = wire_connector.Origin
        first = wire.GetVertex(0)
        last = wire.GetVertex(count - 1)
        index = 0 if first.DistanceTo(origin) <= last.DistanceTo(origin) \
            else count - 1
        wire.SetVertex(index, target.Origin)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# placement
# ---------------------------------------------------------------------------

REF_FACING = 'facing'
REF_HAND = 'hand'
REF_BASIS_X = 'basisx'


def _plan_vector(instance, kind):
    vector = None
    try:
        if kind == REF_FACING:
            vector = instance.FacingOrientation
        elif kind == REF_HAND:
            vector = instance.HandOrientation
        else:
            vector = instance.GetTransform().BasisX
    except Exception:
        return None
    if vector is None:
        return None
    flat = XYZ(vector.X, vector.Y, 0.0)
    try:
        if flat.GetLength() < 1.0e-7:
            return None
        return flat.Normalize()
    except Exception:
        return None


def reference_kind(instance):
    """Which axis to read the plan rotation off.

    A wall-hosted device faces out of the wall, so its facing direction is the
    one worth keeping.  A ceiling-hosted fitting faces straight down and has no
    plan facing at all, so its hand direction stands in.
    """
    for kind in (REF_FACING, REF_HAND, REF_BASIS_X):
        if _plan_vector(instance, kind) is not None:
            return kind
    return REF_BASIS_X


def instance_point(instance):
    location = instance.Location
    if isinstance(location, LocationPoint):
        return location.Point
    if isinstance(location, LocationCurve):
        return None
    return None


def resolve_level(doc, instance, point, prefer_below=True):
    """Which level the replacement should be associated with.

    A face-based family hosted to a face often carries no usable level at all,
    and where it does the level frequently belongs to the *host* rather than to
    the element - a light hosted to Level 1's ceiling reports Level 2, because
    that is the level the ceiling was drawn on.  Associating the replacement
    with the nearest level at or below the insertion point is the rule that
    gets both cases right, and it is what prefer_below asks for.

    With prefer_below off the original's own level association is kept where it
    has one, which suits a family deliberately dimensioned down from the level
    above on a negative offset.
    """
    if prefer_below:
        below = level_below(doc, point)
        if below is not None:
            return below

    try:
        level_id = instance.LevelId
        if level_id is not None and eid_value(level_id) > 0:
            level = doc.GetElement(level_id)
            if isinstance(level, Level):
                return level
    except Exception:
        pass
    for bip in (BuiltInParameter.FAMILY_LEVEL_PARAM,
                BuiltInParameter.SCHEDULE_LEVEL_PARAM,
                BuiltInParameter.INSTANCE_REFERENCE_LEVEL_PARAM):
        try:
            param = instance.get_Parameter(bip)
            if param is not None and param.HasValue:
                level = doc.GetElement(param.AsElementId())
                if isinstance(level, Level):
                    return level
        except Exception:
            continue
    try:
        host = instance.Host
        if host is not None:
            level = doc.GetElement(host.LevelId)
            if isinstance(level, Level):
                return level
    except Exception:
        pass
    return level_below(doc, point) or nearest_level(doc, point)


# A level within this of the insertion point counts as being at it rather than
# above it, so an element sitting exactly on its own level is not pushed down
# to the one beneath by floating point noise.  1mm in feet.
LEVEL_TOL_FT = 1.0 / MM_PER_FT


def level_below(doc, point):
    """The highest level at or below the point.

    Falls back to the lowest level in the model where the point sits below all
    of them - a basement slab modelled below its own level still has to be
    associated with something.
    """
    if point is None:
        return None
    z = point.Z
    best = None
    best_elev = None
    lowest = None
    lowest_elev = None
    for level in FilteredElementCollector(doc).OfClass(Level):
        try:
            elev = level.ProjectElevation
        except Exception:
            continue
        if lowest_elev is None or elev < lowest_elev:
            lowest = level
            lowest_elev = elev
        if elev > z + LEVEL_TOL_FT:
            continue
        if best_elev is None or elev > best_elev:
            best = level
            best_elev = elev
    if best is not None:
        return best
    return lowest


def nearest_level(doc, point):
    best = None
    best_gap = None
    z = point.Z if point is not None else 0.0
    for level in FilteredElementCollector(doc).OfClass(Level):
        try:
            gap = abs(level.ProjectElevation - z)
        except Exception:
            continue
        if best_gap is None or gap < best_gap:
            best = level
            best_gap = gap
    return best


def force_level(doc, element, level):
    """Write the level onto every writable level parameter the family has.

    Passing a level to NewFamilyInstance does not always take, and a family
    can carry both Level and Schedule Level - setting only the first writable
    one it offers leaves the other pointing somewhere else, which shows up
    later in schedules rather than in the view.
    """
    if level is None or element is None:
        return None
    wanted = level.Id
    written = []
    for bip in (BuiltInParameter.FAMILY_LEVEL_PARAM,
                BuiltInParameter.SCHEDULE_LEVEL_PARAM,
                BuiltInParameter.INSTANCE_REFERENCE_LEVEL_PARAM,
                BuiltInParameter.INSTANCE_SCHEDULE_ONLY_LEVEL_PARAM):
        try:
            param = element.get_Parameter(bip)
        except Exception:
            continue
        if param is None or param.IsReadOnly:
            continue
        if param.StorageType != StorageType.ElementId:
            continue
        try:
            if eid_value(param.AsElementId()) != eid_value(wanted):
                param.Set(wanted)
            written.append(bip)
        except Exception:
            continue
    return elem_name(level) if written else None


#: Placement types that genuinely want a host element. Everything else must
#: never be handed one - passing the original's ceiling to a level based family
#: is what produces Revit's "Can't use this type of host".
HOSTED_PLACEMENTS = ('OneLevelBasedHosted',)

#: Placement types that want a work plane or a face rather than a host element.
WORKPLANE_PLACEMENTS = ('WorkPlaneBased',)

_SKETCH_CACHE = {}


def _sketch_plane(doc, point):
    """A horizontal work plane at the point, one per elevation per run.

    Work plane based families need a plane to sit on. Cached by elevation so a
    run over three hundred fittings leaves three or four sketch planes behind
    rather than three hundred.
    """
    key = int(round(point.Z * MM_PER_FT))
    cached = _SKETCH_CACHE.get(key)
    if cached is not None:
        try:
            if doc.GetElement(cached.Id) is not None:
                return cached
        except Exception:
            pass
    try:
        plane = Plane.CreateByNormalAndOrigin(XYZ.BasisZ,
                                              XYZ(point.X, point.Y, point.Z))
    except Exception:
        try:
            plane = Plane.CreateByNormalAndOrigin(XYZ.BasisZ, point)
        except Exception:
            return None
    try:
        sketch = SketchPlane.Create(doc, plane)
    except Exception:
        return None
    _SKETCH_CACHE[key] = sketch
    return sketch


def host_face_reference(doc, host, point):
    """The face of the original's host nearest the insertion point.

    Only wanted when the *replacement* is face or work plane based. Returns
    (reference, direction) or (None, None).
    """
    if host is None:
        return None, None
    try:
        options = Options()
        options.ComputeReferences = True
        options.IncludeNonVisibleObjects = True
        geometry = host.get_Geometry(options)
    except Exception:
        return None, None
    if geometry is None:
        return None, None

    best = None
    best_gap = None

    def walk(items):
        result = []
        for item in items:
            try:
                nested = item.GetInstanceGeometry()
            except Exception:
                nested = None
            if nested is not None:
                result.extend(walk(nested))
                continue
            result.append(item)
        return result

    for item in walk(geometry):
        faces = getattr(item, 'Faces', None)
        if faces is None:
            continue
        for face in faces:
            try:
                if face.Reference is None:
                    continue
                projected = face.Project(point)
                gap = projected.Distance if projected is not None else None
            except Exception:
                continue
            if gap is None:
                continue
            if best_gap is None or gap < best_gap:
                best = face
                best_gap = gap
    if best is None:
        return None, None
    try:
        normal = best.ComputeNormal(best.Project(point).UVPoint)
    except Exception:
        normal = XYZ.BasisZ
    # A direction lying in the face, which is what the overload wants.
    direction = XYZ(-normal.Y, normal.X, 0.0)
    try:
        if direction.GetLength() < 1.0e-7:
            direction = XYZ.BasisX
        else:
            direction = direction.Normalize()
    except Exception:
        direction = XYZ.BasisX
    return best.Reference, direction


def _attempt_place(doc, make):
    """One placement route, isolated.

    A route can return an element and only then have Revit post an error at
    regeneration. Without a sub-transaction around each attempt that failure
    lands on the whole run instead of just this route, and the cascade never
    gets to try the next one. Regenerating inside the attempt is what forces
    the error to surface here where it can be rolled back.
    """
    sub = SubTransaction(doc)
    try:
        sub.Start()
    except Exception as err:
        return None, str(err)
    try:
        created = make()
        if created is None:
            sub.RollBack()
            return None, 'the call returned nothing'
        doc.Regenerate()
        sub.Commit()
        return created, ''
    except Exception as err:
        try:
            sub.RollBack()
        except Exception:
            pass
        return None, str(err)


def create_replacement(doc, symbol, point, level, host, placement):
    """Place the replacement, choosing routes by the target's placement type.

    The rule that matters: a host element is only ever offered to a family whose
    placement type actually takes one. Handing the original's ceiling to a level
    based or work plane based family is exactly what Revit refuses with "Can't
    use this type of host", and it is the reason a face based to non-face based
    swap used to fail.
    """
    creator = doc.Create
    attempts = []
    wants_host = placement in HOSTED_PLACEMENTS
    wants_plane = placement in WORKPLANE_PLACEMENTS

    if wants_host and host is not None:
        if level is not None:
            attempts.append(('host and level', lambda: creator.NewFamilyInstance(
                point, symbol, host, level, StructuralType.NonStructural)))
        attempts.append(('host', lambda: creator.NewFamilyInstance(
            point, symbol, host, StructuralType.NonStructural)))

    if wants_plane:
        # The work plane route first, then the original's own face, which keeps
        # a face based replacement on the surface the original sat on.
        sketch = _sketch_plane(doc, point)
        if sketch is not None:
            attempts.append(('work plane', lambda: creator.NewFamilyInstance(
                point, symbol, sketch, StructuralType.NonStructural)))

    if wants_host or wants_plane:
        reference, direction = host_face_reference(doc, host, point)
        if reference is not None:
            attempts.append(('host face', lambda: creator.NewFamilyInstance(
                reference, point, direction, symbol)))

    # Un-hosted routes. These are the ones a level based replacement wants, and
    # no host is passed to any of them.
    if level is not None:
        attempts.append(('level', lambda: creator.NewFamilyInstance(
            point, symbol, level, StructuralType.NonStructural)))
    attempts.append(('point', lambda: creator.NewFamilyInstance(
        point, symbol, StructuralType.NonStructural)))

    # Last resort for a family that reports a placement type we did not expect:
    # give it a work plane rather than a host, because a wrong work plane can be
    # moved and a wrong host cannot.
    if not wants_plane and not wants_host:
        sketch = _sketch_plane(doc, point)
        if sketch is not None:
            attempts.append(('work plane', lambda: creator.NewFamilyInstance(
                point, symbol, sketch, StructuralType.NonStructural)))

    errors = []
    for label, attempt in attempts:
        created, message = _attempt_place(doc, attempt)
        if created is not None:
            return created, label, errors
        errors.append(fmt('{0}: {1}', label, message))
    return None, '', errors


def place_at(doc, new_element, point, z_offset_ft):
    """Nudge the placed element onto the exact point, plus any Z offset."""
    target = XYZ(point.X, point.Y, point.Z + z_offset_ft)
    try:
        actual = instance_point(new_element)
        if actual is None:
            return False
        delta = XYZ(target.X - actual.X, target.Y - actual.Y, target.Z - actual.Z)
        if delta.GetLength() > POINT_TOL_FT:
            ElementTransformUtils.MoveElement(doc, new_element.Id, delta)
        return True
    except Exception:
        return False


def match_rotation(doc, source, new_element, kind, extra_radians):
    """Turn the replacement so it reads the same way round as the original.

    The angle is measured between the two elements on the same axis, so it is
    right whatever the replacement family's own default orientation is.
    """
    point = instance_point(new_element)
    if point is None:
        return 0.0
    source_dir = _plan_vector(source, kind)
    new_dir = _plan_vector(new_element, kind)
    angle = 0.0
    if source_dir is not None and new_dir is not None:
        angle = signed_plan_angle(new_dir, source_dir)
    angle += extra_radians
    if abs(angle) < 1.0e-9:
        return 0.0
    axis = Line.CreateBound(point, XYZ(point.X, point.Y, point.Z + 1.0))
    ElementTransformUtils.RotateElement(doc, new_element.Id, axis, angle)
    return angle


# ---------------------------------------------------------------------------
# probing an unplaced replacement family
# ---------------------------------------------------------------------------

class Probe(object):
    def __init__(self):
        self.ok = False
        self.param_infos = {}
        self.elec = ElecProfile()
        self.placement = 'Unknown'
        self.note = ''


def probe_symbol(doc, symbol_id, view=None):
    """Read the replacement family's instance parameters and connectors.

    An already placed instance is read for free.  Where the family is not
    placed anywhere yet, one is put down inside a transaction that is then
    rolled back, so the model is left exactly as it was.
    """
    probe = Probe()
    symbol = doc.GetElement(symbol_id)
    if not isinstance(symbol, FamilySymbol):
        probe.note = 'The replacement type could not be read.'
        return probe
    probe.placement = placement_name(symbol)

    existing = None
    try:
        collector = FilteredElementCollector(doc)
        collector = collector.WherePasses(FamilyInstanceFilter(doc, symbol_id))
        for inst in collector:
            existing = inst
            break
    except Exception:
        existing = None

    if existing is not None:
        probe.param_infos = read_param_infos(existing)
        probe.elec = electrical_profile(existing)
        probe.ok = True
        probe.note = 'Read from a placed instance.'
        return probe

    transaction = Transaction(doc, 'RevoBIM probe replacement family')
    try:
        transaction.Start()
        if not symbol.IsActive:
            symbol.Activate()
            doc.Regenerate()
        if probe.placement == 'ViewBased' and view is not None:
            # A detail item is placed in a view, not on a level. The level
            # routes all refuse it, so it gets the one route it does take.
            created, message = _attempt_place(
                doc, lambda: doc.Create.NewFamilyInstance(
                    XYZ.Zero, symbol, view))
            errors = [message] if message else []
        else:
            level = nearest_level(doc, XYZ.Zero)
            created, _route, errors = create_replacement(
                doc, symbol, XYZ.Zero, level, None, probe.placement)
        if created is None:
            probe.note = ('The replacement family could not be test-placed, so '
                          'its parameters are unknown until it is used. '
                          'Place one in the model and reselect it.')
            if errors:
                probe.note = probe.note + ' (' + errors[-1] + ')'
        else:
            doc.Regenerate()
            probe.param_infos = read_param_infos(created)
            probe.elec = electrical_profile(created)
            probe.ok = True
            probe.note = 'Read from a temporary instance, rolled back.'
    except Exception as err:
        probe.note = fmt('The replacement family could not be read: {0}', err)
    finally:
        try:
            transaction.RollBack()
        except Exception:
            pass
    return probe


# ---------------------------------------------------------------------------
# drafting views : import symbols -> detail items
# ---------------------------------------------------------------------------

#: The category a drafting-view replacement comes from. Looked up at call
#: time, never at module load.
DETAIL_ITEM_BIC = 'OST_DetailComponents'

#: What the type list shows for an import, which has no family/type split.
IMPORT_TYPE_LABEL = u'Import symbol'

#: Points gathered from one import's linework before the extents are taken.
#: A block can be tessellated arcs and hatching; the extents settle long
#: before this, and it keeps a pathological block from stalling the run.
IMPORT_POINT_CAP = 20000


def is_drafting_view(view):
    try:
        return view is not None and str(view.ViewType) == 'DraftingView'
    except Exception:
        return False


def _bic(name):
    try:
        return getattr(BuiltInCategory, name)
    except Exception:
        return None


def category_is(element, bic_name):
    """True when the element is in the named built-in category."""
    bic = _bic(bic_name)
    if bic is None or element is None:
        return False
    try:
        category = element.Category
        return category is not None and eid_value(category.Id) == int(bic)
    except Exception:
        return False


class ImportPickFilter(ISelectionFilter):
    """Pick filter for the Find side in a drafting view - imports only."""

    def AllowElement(self, element):
        try:
            return isinstance(element, ImportInstance)
        except Exception:
            return False

    def AllowReference(self, reference, point):
        return False


class DetailItemPickFilter(ISelectionFilter):
    """Pick filter for the Replace side in a drafting view - detail items."""

    def AllowElement(self, element):
        try:
            return (isinstance(element, FamilyInstance) and
                    category_is(element, DETAIL_ITEM_BIC))
        except Exception:
            return False

    def AllowReference(self, reference, point):
        return False


def owner_view(doc, element):
    """The view an element is drawn in, or None for a model element."""
    try:
        view_id = element.OwnerViewId
        if view_id is None or eid_value(view_id) <= 0:
            return None
        view = doc.GetElement(view_id)
        if view is None or getattr(view, 'ViewDirection', None) is None:
            return None
        return view
    except Exception:
        return None


def import_name(element, doc=None):
    """The block name an import symbol goes by.

    The type's name first - after a partial explode that is the AutoCAD block
    name - then the instance's own name.
    """
    if doc is None:
        try:
            doc = element.Document
        except Exception:
            doc = None
    names = []
    if doc is not None:
        try:
            names.append(elem_name(doc.GetElement(element.GetTypeId())))
        except Exception:
            pass
    names.append(elem_name(element))
    for name in names:
        if name:
            return name
    return u'Unnamed import'


def import_category(element):
    try:
        category = element.Category
        if category is not None and category.Name:
            return category.Name
    except Exception:
        pass
    return u'Imports'


def import_record(doc, element, count=0):
    """The list record for an import - shared by the index and the picker, so
    a picked import always finds its own row in the lists."""
    record = TypeRecord(element.GetTypeId(), IMPORT_TYPE_LABEL,
                        import_name(element, doc), import_category(element),
                        'Import', count)
    record.is_import = True
    return record


def build_import_index(doc):
    """Every import that sits in a view, keyed category > block name.

    View-specific imports only. A detail item belongs to a view, so an import
    placed as a model element has nowhere for its replacement to go - it is
    left out of the list rather than offered and then refused.
    """
    index = {}
    seen = {}
    try:
        collector = FilteredElementCollector(doc).OfClass(ImportInstance)
        collector = collector.WhereElementIsNotElementType()
    except Exception:
        return index
    for element in collector:
        try:
            if owner_view(doc, element) is None:
                continue
            key = eid_value(element.GetTypeId())
        except Exception:
            continue
        record = seen.get(key)
        if record is None:
            record = import_record(doc, element)
            seen[key] = record
            index.setdefault(record.category_name, {}).setdefault(
                record.family_name, []).append(record)
        record.count += 1
    return index


def build_detail_index(doc):
    """Every detail item type in the project, keyed category > family."""
    index = {}
    bic = _bic(DETAIL_ITEM_BIC)
    counts = instance_counts(doc)
    try:
        collector = FilteredElementCollector(doc).OfClass(FamilySymbol)
        if bic is not None:
            collector = collector.OfCategory(bic)
    except Exception:
        return index
    for symbol in collector:
        try:
            if not category_is(symbol, DETAIL_ITEM_BIC):
                continue
            family = symbol.Family
            if family is None:
                continue
            cat_name = symbol.Category.Name
            fam_name = elem_name(family)
            record = TypeRecord(
                symbol.Id, elem_name(symbol), fam_name, cat_name,
                placement_name(symbol), counts.get(eid_value(symbol.Id), 0))
            index.setdefault(cat_name, {}).setdefault(fam_name, []).append(
                record)
        except Exception:
            continue
    for families in index.values():
        for records in families.values():
            records.sort(key=lambda r: r.type_name.lower())
    return index


def collect_imports(doc, uidoc, type_id, scope):
    """Every import of the given type inside the chosen scope."""
    if type_id is None:
        return []
    wanted = eid_value(type_id)

    def matches(element):
        try:
            return (isinstance(element, ImportInstance) and
                    eid_value(element.GetTypeId()) == wanted)
        except Exception:
            return False

    try:
        if scope == SCOPE_SELECTION:
            found = []
            for element_id in uidoc.Selection.GetElementIds():
                element = doc.GetElement(element_id)
                if matches(element):
                    found.append(element)
            return found
        if scope == SCOPE_VIEW and uidoc.ActiveView is not None:
            collector = FilteredElementCollector(doc, uidoc.ActiveView.Id)
        else:
            collector = FilteredElementCollector(doc)
        collector = collector.OfClass(ImportInstance)
        return [element for element in collector if matches(element)]
    except Exception:
        return []


def _view_axes(view):
    """(right, up, normal) of the view the element is drawn in."""
    try:
        right = view.RightDirection
        up = view.UpDirection
        normal = view.ViewDirection
        if right is not None and up is not None and normal is not None:
            return right, up, normal
    except Exception:
        pass
    return XYZ.BasisX, XYZ.BasisY, XYZ.BasisZ


def _instance_transform(element):
    for name in ('GetTransform', 'GetTotalTransform'):
        getter = getattr(element, name, None)
        if getter is None:
            continue
        try:
            transform = getter()
            if transform is not None:
                return transform
        except Exception:
            continue
    return None


def _collect_points(items, out, depth=0):
    """Every drawn point in a piece of geometry, nested blocks included."""
    if depth > 8 or len(out) >= IMPORT_POINT_CAP:
        return
    try:
        iterator = iter(items)
    except Exception:
        return
    for item in iterator:
        if len(out) >= IMPORT_POINT_CAP:
            return
        getter = getattr(item, 'GetInstanceGeometry', None)
        if getter is not None:
            try:
                nested = getter()
            except Exception:
                nested = None
            if nested is not None:
                _collect_points(nested, out, depth + 1)
            continue
        tessellate = getattr(item, 'Tessellate', None)
        if tessellate is not None:
            try:
                for point in tessellate():
                    out.append(point)
            except Exception:
                pass
            continue
        coordinates = getattr(item, 'GetCoordinates', None)
        if coordinates is not None:
            try:
                for point in coordinates():
                    out.append(point)
            except Exception:
                pass
            continue
        edges = getattr(item, 'Edges', None)
        if edges is not None:
            try:
                for edge in edges:
                    for point in edge.Tessellate():
                        out.append(point)
            except Exception:
                pass
            continue
        vertices = getattr(item, 'Vertices', None)
        if vertices is not None:
            try:
                for point in vertices:
                    out.append(point)
            except Exception:
                pass
            continue
        coord = getattr(item, 'Coord', None)
        if coord is not None:
            out.append(coord)


def _extents_centre(points, to_local=None, to_world=None):
    """Centre of the extents, measured in a local frame when one is given.

    Measured in the element's own axes, a rotated block's centre is the centre
    of the block as drawn. Measured in world axes, it is the centre of the box
    around the rotated block - which for anything not symmetric about its own
    middle is somewhere else.
    """
    lo = None
    hi = None
    for point in points:
        try:
            q = to_local.OfPoint(point) if to_local is not None else point
            values = (q.X, q.Y, q.Z)
        except Exception:
            continue
        if lo is None:
            lo = list(values)
            hi = list(values)
            continue
        for axis in range(3):
            if values[axis] < lo[axis]:
                lo[axis] = values[axis]
            if values[axis] > hi[axis]:
                hi[axis] = values[axis]
    if lo is None:
        return None
    middle = XYZ((lo[0] + hi[0]) * 0.5, (lo[1] + hi[1]) * 0.5,
                 (lo[2] + hi[2]) * 0.5)
    if to_world is not None:
        try:
            return to_world.OfPoint(middle)
        except Exception:
            return None
    return middle


def own_frame_centre(element, view):
    """(centre, how it was found) for an import or a detail item.

    Tried in order of how true an answer each gives: the drawn linework in the
    element's own axes, the drawn linework in world axes, the view bounding
    box, and finally the insertion point - which for an AutoCAD block is
    wherever its base point was set, and very often not the middle at all.
    """
    transform = _instance_transform(element)
    points = []
    try:
        options = Options()
        if view is not None:
            try:
                options.View = view
            except Exception:
                pass
        geometry = element.get_Geometry(options)
        if geometry is not None:
            _collect_points(geometry, points)
    except Exception:
        points = []

    if points and transform is not None:
        try:
            centre = _extents_centre(points, transform.Inverse, transform)
            if centre is not None:
                return centre, 'own extents'
        except Exception:
            pass
    if points:
        centre = _extents_centre(points)
        if centre is not None:
            return centre, 'drawn extents'
    try:
        box = element.get_BoundingBox(view)
        if box is not None:
            return box_centre(box), 'bounding box'
    except Exception:
        pass
    if transform is not None:
        try:
            return transform.Origin, 'insertion point'
        except Exception:
            pass
    try:
        point = instance_point(element)
        if point is not None:
            return point, 'insertion point'
    except Exception:
        pass
    return None, ''


#: How far off a detail item may land before the verify pass moves it again.
CENTRE_TOL_FT = 0.5 / MM_PER_FT


def box_centre(box):
    """Middle of a bounding box, in model coordinates.

    A BoundingBoxXYZ carries its own Transform; Min and Max are in that box's
    frame, not the model's. Usually it is the identity, which is exactly why
    ignoring it looks fine until it isn't.
    """
    middle = box.Min.Add(box.Max).Multiply(0.5)
    transform = getattr(box, 'Transform', None)
    if transform is not None:
        try:
            return transform.OfPoint(middle)
        except Exception:
            pass
    return middle


def rotate_in_plane(vector, angle, right, up):
    """Turn a vector by angle about the view normal, in the view's terms."""
    x = vector.DotProduct(right)
    y = vector.DotProduct(up)
    depth = vector.Subtract(right.Multiply(x)).Subtract(up.Multiply(y))
    c = math.cos(angle)
    s = math.sin(angle)
    return right.Multiply(x * c - y * s).Add(
        up.Multiply(x * s + y * c)).Add(depth)


def reflect_across(vector, plane_normal):
    """Mirror a vector across a plane through the origin."""
    return vector.Subtract(
        plane_normal.Multiply(2.0 * vector.DotProduct(plane_normal)))


def centre_from_unrotated(square_centre, pivot, angle, right, up):
    """Where a centre measured with the element turned square really is.

    The element was turned back by -angle about pivot to be measured, so the
    centre found then is turned forward by +angle about the same pivot.
    """
    return pivot.Add(rotate_in_plane(square_centre.Subtract(pivot), angle,
                                     right, up))


def placed_offset(offset, angle, mirror_normal, right, up):
    """Where a detail item's middle sits from its insertion point once turned.

    offset is read with the item square to the view. Turning comes first and
    mirroring second, because that is the order place_detail_item does them
    in - mirroring first and turning after puts a lop-sided item somewhere else.
    """
    moved = rotate_in_plane(offset, angle, right, up)
    if mirror_normal is not None:
        moved = reflect_across(moved, mirror_normal)
    return moved


def element_pivot(element):
    """The point an element turns about - its insertion point."""
    transform = _instance_transform(element)
    if transform is not None:
        try:
            return transform.Origin
        except Exception:
            pass
    try:
        return instance_point(element)
    except Exception:
        return None


def _square_box_centre(doc, element, view, pivot, angle, normal):
    """Bounding box middle with the element turned square, then turned back.

    Turned in a sub-transaction that is always rolled back, so the model is
    never left changed. Needs a transaction to be open; returns None when the
    document is read only.
    """
    if abs(angle) < 1.0e-9:
        try:
            box = element.get_BoundingBox(view)
            return box_centre(box) if box is not None else None
        except Exception:
            return None
    try:
        if not doc.IsModifiable:
            return None
    except Exception:
        return None
    sub = SubTransaction(doc)
    try:
        sub.Start()
    except Exception:
        return None
    found = None
    try:
        try:
            if element.Pinned:
                element.Pinned = False
        except Exception:
            pass
        axis = Line.CreateBound(pivot, pivot.Add(normal))
        ElementTransformUtils.RotateElement(doc, element.Id, axis, -angle)
        doc.Regenerate()
        box = element.get_BoundingBox(view)
        if box is not None:
            found = box_centre(box)
    except Exception:
        found = None
    finally:
        try:
            sub.RollBack()
        except Exception:
            pass
    return found


def measure_centre(doc, element, view, transform=None):
    """(centre, route) - the middle of an element as drawn, in its own axes.

    First choice is Revit's own bounding box taken with the element turned
    square to the view: square, the box *is* the element's extents in its own
    axes, so its middle is the true middle at any final angle. That needs
    nothing from the geometry API and is the box Revit draws when you select
    the element. Falling back, the drawn linework measured in the element's own
    axes, then the box as it stands, then the insertion point.
    """
    right, up, normal = _view_axes(view)
    if transform is None:
        transform = _instance_transform(element)
    angle = 0.0
    pivot = None
    if transform is not None:
        try:
            angle = plane_angle(transform.BasisX, right, up)
            pivot = transform.Origin
        except Exception:
            angle = 0.0
    if pivot is None:
        pivot = element_pivot(element)
    if pivot is not None:
        square = _square_box_centre(doc, element, view, pivot, angle, normal)
        if square is not None:
            return centre_from_unrotated(square, pivot, angle, right, up), \
                'square box'
    return own_frame_centre(element, view)


# ---------------------------------------------------------------------------
# debug log
# ---------------------------------------------------------------------------

DEBUG_FILE = 'FamilyFindReplace_debug.txt'

#: Past this the log starts again rather than growing for ever.
DEBUG_MAX_BYTES = 2 * 1024 * 1024


def debug_path():
    try:
        root = os.environ.get('APPDATA') or ''
        if not root:
            return None
        folder = os.path.join(root, 'RevoBIM')
        if not os.path.isdir(folder):
            os.makedirs(folder)
        return os.path.join(folder, DEBUG_FILE)
    except Exception:
        return None


def write_debug(lines):
    """Append a run's lines to the debug log. Never raises."""
    if not lines:
        return
    path = debug_path()
    if path is None:
        return
    try:
        mode = 'a'
        if os.path.isfile(path) and os.path.getsize(path) > DEBUG_MAX_BYTES:
            mode = 'w'
        handle = open(path, mode)
        try:
            handle.write(u'\n'.join(lines).encode('utf-8')
                         if str is bytes else u'\n'.join(lines))
            handle.write('\n')
        finally:
            handle.close()
    except Exception:
        pass


def mm_text(point):
    if point is None:
        return u'none'
    try:
        return fmt(u'({0:.1f}, {1:.1f})', ft_to_mm(point.X), ft_to_mm(point.Y))
    except Exception:
        return u'?'


class ImportFrame(object):
    """Where an import sits and which way round, in its view's terms."""

    def __init__(self):
        self.centre = None        # where the detail item is lined up to
        self.route = ''           # how that point was found
        self.origin = None        # the block's insertion (base) point
        self.origin_route = ''    # which transform it came from
        self.transform = None     # the block's placement transform
        self.candidates = []      # every (route, transform) tried, for the log
        self.angle = 0.0          # radians, from the view's right, about its normal
        self.mirrored = False
        self.x_dir = None         # the import's own X, flattened into the view


def plane_angle(basis_x, right, up):
    """Angle of a direction in the view plane, measured from the view's right."""
    try:
        x = basis_x.DotProduct(right)
        y = basis_x.DotProduct(up)
    except Exception:
        return 0.0
    if abs(x) < 1.0e-12 and abs(y) < 1.0e-12:
        return 0.0
    return math.atan2(y, x)


def is_mirrored_in_plane(basis_x, basis_y, right, up):
    """True when the element's axes run the other way round to the view's.

    Judged in the view plane rather than from the transform's determinant, so
    an import that is merely flipped through the sheet - which looks the same
    on paper - does not read as mirrored.
    """
    try:
        ax = basis_x.DotProduct(right)
        ay = basis_x.DotProduct(up)
        bx = basis_y.DotProduct(right)
        by = basis_y.DotProduct(up)
    except Exception:
        return False
    return (ax * by - ay * bx) < 0.0


def _is_instance(item):
    return getattr(item, 'GetSymbolGeometry', None) is not None


def block_transform(element, view, max_depth=6):
    """(transform, depth) - the placement the block's linework is drawn by.

    An import symbol's geometry is a GeometryInstance whose Transform is the
    block's insertion: its origin is the AutoCAD base point, its axes the
    block's rotation. That is the transform the drawing actually uses, so it is
    read first. Where the import wraps the block in an outer instance holding
    nothing else, the wrapper is stepped through and the two transforms
    combined - stopping at the first level that holds anything besides one
    block, so a block made of other blocks keeps its own insertion.

    Returns (None, 0) when the import is not exactly one block - a whole DWG
    left unexploded has no single insertion point.
    """
    try:
        options = Options()
        if view is not None:
            try:
                options.View = view
            except Exception:
                pass
        geometry = element.get_Geometry(options)
    except Exception:
        return None, 0
    if geometry is None:
        return None, 0
    try:
        items = list(geometry)
    except Exception:
        return None, 0
    blocks = [item for item in items if _is_instance(item)]
    if len(blocks) != 1:
        return None, 0
    current = blocks[0]
    try:
        transform = current.Transform
    except Exception:
        return None, 0
    depth = 0
    while depth < max_depth:
        try:
            inner = list(current.GetSymbolGeometry())
        except Exception:
            break
        if len(inner) != 1 or not _is_instance(inner[0]):
            break
        try:
            transform = transform.Multiply(inner[0].Transform)
        except Exception:
            break
        current = inner[0]
        depth += 1
    return transform, depth


def insertion_candidates(element, view):
    """Every route to the import's placement, best first. None where a route
    gives nothing. All of them are written to the debug log, so if the first is
    ever the wrong one the log shows which of the others was right."""
    found = []
    transform, depth = block_transform(element, view)
    found.append((u'block insertion' if not depth
                  else fmt(u'block insertion, {0} level(s) in', depth),
                  transform))
    for name, label in (('GetTotalTransform', u'total transform'),
                        ('GetTransform', u'instance transform')):
        getter = getattr(element, name, None)
        value = None
        if getter is not None:
            try:
                value = getter()
            except Exception:
                value = None
        found.append((label, value))
    return found


def frame_from_transform(transform, right, up):
    """(origin, angle, mirrored) of a placement, in the view's terms."""
    origin = transform.Origin
    angle = plane_angle(transform.BasisX, right, up)
    mirrored = is_mirrored_in_plane(transform.BasisX, transform.BasisY,
                                    right, up)
    return origin, angle, mirrored


def angle_gap(target, got):
    """target - got, wrapped to (-pi, pi], so 359 degrees reads as -1."""
    gap = math.fmod(target - got, 2.0 * math.pi)
    if gap <= -math.pi:
        gap += 2.0 * math.pi
    elif gap > math.pi:
        gap -= 2.0 * math.pi
    return gap


def read_import_frame(doc, element, view, by_centre=False):
    """Where an import symbol sits and which way round.

    Insertion point and rotation come from the block's own placement transform
    - the first route in insertion_candidates that answers. By default the
    detail item is lined up insertion point to insertion point, which is what a
    family-for-family swap does. With by_centre, it is lined up middle to
    middle instead, using the same transform for the angle.
    """
    frame = ImportFrame()
    right, up, _normal = _view_axes(view)
    frame.candidates = insertion_candidates(element, view)
    for route, transform in frame.candidates:
        if transform is None:
            continue
        try:
            origin, angle, mirrored = frame_from_transform(transform, right, up)
        except Exception:
            continue
        frame.transform = transform
        frame.origin = origin
        frame.origin_route = route
        frame.angle = angle
        frame.mirrored = mirrored
        break
    frame.x_dir = right.Multiply(math.cos(frame.angle)).Add(
        up.Multiply(math.sin(frame.angle)))
    if by_centre:
        frame.centre, frame.route = measure_centre(doc, element, view,
                                                   frame.transform)
    else:
        frame.centre = frame.origin
        frame.route = u'insertion point' if frame.origin is not None else u''
    return frame


def mirror_plane_normal(view_normal, x_dir):
    """Normal of the plane to mirror across so the import's own X is kept.

    The plane holds the import's X axis and the view normal, so mirroring
    across it keeps X and flips the other in-plane axis - exactly what a block
    mirrored in AutoCAD did. Using X itself as the normal would mirror across
    the wrong axis and leave the symbol pointing backwards.
    """
    return view_normal.CrossProduct(x_dir).Normalize()


def flatten_to_plane(vector, normal):
    """The part of a vector lying in the view's plane."""
    return vector.Subtract(normal.Multiply(vector.DotProduct(normal)))


#: How far a placed detail item may turn from the block before it is put right.
ANGLE_TOL = math.radians(0.01)


def place_detail_item(doc, symbol, view, frame, extra_radians,
                      match_rotation, match_mirror, report, problems,
                      debug=None, by_centre=False):
    """Insertion point to insertion point by default; middle to middle when
    asked."""
    if by_centre:
        return _place_by_centre(doc, symbol, view, frame, extra_radians,
                                match_rotation, match_mirror, report,
                                problems, debug)
    return _place_by_insertion(doc, symbol, view, frame, extra_radians,
                               match_rotation, match_mirror, report, problems,
                               debug)


def _place_by_insertion(doc, symbol, view, frame, extra_radians,
                        match_rotation, match_mirror, report, problems,
                        debug=None):
    """Put a detail item's insertion point on the block's, at its rotation.

    The same rule a family-for-family swap follows: the new family's origin
    goes where the old one's was, turned the same way. The block's insertion
    point is the AutoCAD base point, read from the placement its linework is
    drawn by; the detail item family is expected to have its origin where the
    block's base point is.

    Then checked: the item's own placement is read back, and if its origin is
    more than half a millimetre from the block's, or its X more than a
    hundredth of a degree from the block's, it is moved or turned by exactly
    what is left.
    """
    origin = frame.origin
    created, message = _attempt_place(
        doc, lambda: doc.Create.NewFamilyInstance(origin, symbol, view))
    if created is None:
        return None, message

    right, up, normal = _view_axes(view)
    angle = extra_radians
    if match_rotation:
        angle = angle + frame.angle
    if abs(angle) > 1.0e-9:
        try:
            axis = Line.CreateBound(origin, origin.Add(normal))
            ElementTransformUtils.RotateElement(doc, created.Id, axis, angle)
            if match_rotation and abs(frame.angle) > 1.0e-9:
                report.rotated += 1
        except Exception as err:
            problems.append(fmt('the detail item would not rotate ({0})', err))

    mirrored = False
    if match_mirror and frame.mirrored:
        try:
            placed_x = right.Multiply(math.cos(angle)).Add(
                up.Multiply(math.sin(angle)))
            across = mirror_plane_normal(normal, placed_x)
            plane = Plane.CreateByNormalAndOrigin(across, origin)
            ids = List[ElementId]()
            ids.Add(created.Id)
            ElementTransformUtils.MirrorElements(doc, ids, plane, False)
            report.mirrored += 1
            mirrored = True
        except Exception as err:
            report.mirror_failed += 1
            problems.append(fmt('the import is mirrored and the detail item '
                                'would not mirror to match ({0})', err))
    try:
        doc.Regenerate()
    except Exception:
        pass

    # Check against the item's own placement, and put right what is left.
    gap_text = u'none'
    turn_text = u'not checked'
    placed = _instance_transform(created)
    if placed is None:
        report.centre_unverified += 1
        problems.append('the detail item\'s placement could not be read '
                        'back, so it was not checked')
    else:
        try:
            gap = flatten_to_plane(origin.Subtract(placed.Origin), normal)
            if gap.GetLength() > CENTRE_TOL_FT:
                ElementTransformUtils.MoveElement(doc, created.Id, gap)
                report.centre_corrected += 1
            if not mirrored:
                # A mirrored item's X can be stored either way round, so only
                # an unmirrored one is turned by what its X says.
                turn = angle_gap(angle, plane_angle(placed.BasisX, right, up))
                turn_text = fmt(u'{0:.3f} deg', math.degrees(turn))
                if abs(turn) > ANGLE_TOL:
                    axis = Line.CreateBound(origin, origin.Add(normal))
                    ElementTransformUtils.RotateElement(doc, created.Id, axis,
                                                        turn)
                    report.rotation_corrected += 1
            doc.Regenerate()
            placed = _instance_transform(created)
            left = flatten_to_plane(origin.Subtract(placed.Origin), normal)
            gap_text = fmt(u'{0:.2f}mm', ft_to_mm(left.GetLength()))
            if left.GetLength() > CENTRE_TOL_FT:
                report.centre_unverified += 1
                problems.append(fmt('the detail item\'s insertion point is '
                                    'still {0:.1f}mm from the symbol\'s',
                                    ft_to_mm(left.GetLength())))
        except Exception as err:
            report.centre_unverified += 1
            problems.append(fmt('the detail item could not be checked ({0})',
                                err))

    if debug is not None:
        debug.append(fmt(
            u'  detail {0}: placed at {1}, turned {2:.2f} deg, mirrored {3}; '
            u'insertion point off by {4}; turn off by {5}',
            eid_value(created.Id), mm_text(origin), math.degrees(angle),
            mirrored, gap_text, turn_text))
    return created, ''


def _place_by_centre(doc, symbol, view, frame, extra_radians,
                     match_rotation, match_mirror, report, problems,
                     debug=None):
    """Put a detail item's middle on an import's middle, turned and handed to
    match.

    1. Place it on the import's centre, still square to the view, and read
       where its own middle sits from its insertion point. Square, Revit's
       bounding box is exactly the item's own extents, so this offset is true
       whatever shape or size the detail item is.
    2. Turn it, and mirror it if the block was mirrored, about its insertion
       point.
    3. Work out where its middle now is - the offset turned and mirrored the
       same way - and move it so that middle sits on the import's.
    4. Measure it again. If it is still more than half a millimetre off, move
       it by what is left, once. If it still will not land, say so.

    Before 1.6.1 this was one read of the turned item's geometry and one move,
    unchecked. When that read did not come back as expected the move did
    nothing, and any detail item whose origin was not its middle stayed off.
    """
    centre = frame.centre
    created, message = _attempt_place(
        doc, lambda: doc.Create.NewFamilyInstance(centre, symbol, view))
    if created is None:
        return None, message
    try:
        doc.Regenerate()
    except Exception:
        pass

    right, up, normal = _view_axes(view)

    # 1. the item's own middle, relative to its insertion point, while square
    insert = element_pivot(created) or centre
    square = None
    route = ''
    try:
        box = created.get_BoundingBox(view)
        if box is not None:
            square = box_centre(box)
            route = 'square box'
    except Exception:
        square = None
    if square is None:
        square, route = own_frame_centre(created, view)
    offset = flatten_to_plane(square.Subtract(insert), normal) \
        if square is not None else None

    # 2. turn and mirror about the insertion point
    angle = extra_radians
    if match_rotation:
        angle = angle + frame.angle
    # The detail item's own X once turned - the line a mirror has to keep.
    placed_x = right.Multiply(math.cos(angle)).Add(up.Multiply(math.sin(angle)))
    if abs(angle) > 1.0e-9:
        try:
            axis = Line.CreateBound(insert, insert.Add(normal))
            ElementTransformUtils.RotateElement(doc, created.Id, axis, angle)
            if match_rotation and abs(frame.angle) > 1.0e-9:
                report.rotated += 1
        except Exception as err:
            angle = 0.0
            problems.append(fmt('the detail item would not rotate ({0})', err))

    across = None
    if match_mirror and frame.mirrored:
        try:
            # Mirror across the line the item's own X runs along: that keeps
            # X and flips the other axis, which is exactly what a block
            # mirrored in AutoCAD did.
            across = mirror_plane_normal(normal, placed_x)
            plane = Plane.CreateByNormalAndOrigin(across, insert)
            ids = List[ElementId]()
            ids.Add(created.Id)
            ElementTransformUtils.MirrorElements(doc, ids, plane, False)
            report.mirrored += 1
        except Exception as err:
            across = None
            report.mirror_failed += 1
            problems.append(fmt('the import is mirrored and the detail item '
                                'would not mirror to match ({0})', err))

    # 3. move its middle onto the import's middle - worked out, not read back
    first_move = None
    if offset is not None:
        expected = insert.Add(placed_offset(offset, angle, across, right, up))
        first_move = flatten_to_plane(centre.Subtract(expected), normal)
        if first_move.GetLength() > POINT_TOL_FT * 10.0:
            try:
                ElementTransformUtils.MoveElement(doc, created.Id, first_move)
                report.centre_shifted += 1
            except Exception as err:
                problems.append(fmt('the detail item could not be centred '
                                    '({0})', err))
    try:
        doc.Regenerate()
    except Exception:
        pass

    # 4. verify, and correct once
    landed, check_route = measure_centre(doc, created, view)
    residual = None
    if landed is not None:
        residual = flatten_to_plane(centre.Subtract(landed), normal)
        if residual.GetLength() > CENTRE_TOL_FT:
            try:
                ElementTransformUtils.MoveElement(doc, created.Id, residual)
                doc.Regenerate()
                report.centre_corrected += 1
            except Exception:
                pass
            landed, check_route = measure_centre(doc, created, view)
            residual = flatten_to_plane(centre.Subtract(landed), normal) \
                if landed is not None else None
    if residual is None:
        report.centre_unverified += 1
        problems.append('the detail item\'s centre could not be measured '
                        'afterwards, so it may not sit on the symbol\'s centre')
    elif residual.GetLength() > CENTRE_TOL_FT:
        report.centre_unverified += 1
        problems.append(fmt('the detail item\'s centre is still {0:.1f}mm from '
                            'the symbol\'s centre', ft_to_mm(
                                residual.GetLength())))

    if debug is not None:
        debug.append(fmt(
            u'  detail {0}: offset {1} via {2}; angle {3:.2f}; mirrored {4}; '
            u'moved {5}; check via {6}, off by {7}',
            eid_value(created.Id), mm_text(offset), route or u'none',
            math.degrees(angle), bool(across is not None), mm_text(first_move),
            check_route or u'none',
            u'none' if residual is None
            else fmt(u'{0:.2f}mm', ft_to_mm(residual.GetLength()))))
    return created, ''


def _replace_import_one(doc, source, symbol, retain_names, extra_radians,
                        match_rotation, match_mirror, report, retain_tags,
                        by_centre=False):
    """Swap one import symbol for a detail item in the same view."""
    source_id = eid_value(source.Id)

    try:
        if source.GroupId is not None and eid_value(source.GroupId) > 0:
            return False, fmt(
                'Import {0} is inside a detail group and was left alone - '
                'groups are not handled in drafting views.', source_id)
    except Exception:
        pass

    view = owner_view(doc, source)
    if view is None:
        return False, fmt(
            'Import {0} is not drawn in a view, so there is nowhere to put a '
            'detail item. It was left alone.', source_id)

    frame = read_import_frame(doc, source, view, by_centre)
    if frame.centre is None:
        return False, fmt('Import {0}: its {1} could not be found, so it was '
                          'left alone.', source_id,
                          'centre' if by_centre else 'insertion point')

    tags = tags_on(doc, source) if retain_tags else []
    try:
        was_pinned = bool(source.Pinned)
    except Exception:
        was_pinned = False

    report.debug.append(fmt(
        u'Import {0} "{1}" in "{2}": lined up by {3} at {4}; insertion from '
        u'{5}; angle {6:.2f}; mirrored {7}', source_id,
        import_name(source, doc), elem_name(view), frame.route or u'none',
        mm_text(frame.centre), frame.origin_route or u'none',
        math.degrees(frame.angle), frame.mirrored))
    right, up, _normal = _view_axes(view)
    for route, transform in frame.candidates:
        if transform is None:
            report.debug.append(fmt(u'    {0}: none', route))
            continue
        try:
            origin, angle, mirrored = frame_from_transform(transform, right, up)
            report.debug.append(fmt(u'    {0}: origin {1}, angle {2:.2f}, '
                                    u'mirrored {3}', route, mm_text(origin),
                                    math.degrees(angle), mirrored))
        except Exception:
            report.debug.append(fmt(u'    {0}: unreadable', route))
    problems = []
    created, message = place_detail_item(
        doc, symbol, view, frame, extra_radians, match_rotation,
        match_mirror, report, problems, report.debug, by_centre)
    if created is None:
        return False, fmt('Import {0}: the detail item would not place in '
                          '"{1}" ({2}).', source_id, elem_name(view),
                          message or 'no reason given')

    route = frame.route if by_centre else frame.origin_route
    report.centre_routes[route] = report.centre_routes.get(route, 0) + 1
    report.views[eid_value(view.Id)] = elem_name(view)

    for name in retain_names:
        ok, text = copy_parameter(source, created, name)
        if not ok and text:
            problems.append(text)

    if tags:
        moved, tag_problems = transfer_tags(doc, tags, source, created)
        report.tags_kept += moved
        problems.extend(tag_problems)

    try:
        if was_pinned:
            source.Pinned = False
    except Exception:
        pass

    doc.Delete(source.Id)

    if was_pinned:
        try:
            created.Pinned = True
            report.pinned += 1
        except Exception:
            problems.append('the import was pinned and the detail item would '
                            'not take the pin')

    report.replaced += 1
    report.new_ids.append(created.Id)
    if problems:
        report.add('warn', fmt('Import {0}: {1}', source_id,
                               '; '.join(problems)))
    return True, ''


# ---------------------------------------------------------------------------
# the run
# ---------------------------------------------------------------------------

class Report(object):
    def __init__(self):
        self.replaced = 0
        self.circuits_kept = 0
        self.circuits_dropped = 0
        self.pinned = 0
        self.tags_kept = 0
        self.wires_kept = 0
        self.groups_done = 0
        self.groups_failed = 0
        self.group_instances = 0
        self.routes = {}
        self.levels_set = {}
        # drafting views
        self.rotated = 0
        self.mirrored = 0
        self.mirror_failed = 0
        self.centre_shifted = 0
        self.centre_corrected = 0
        self.centre_unverified = 0
        self.rotation_corrected = 0
        self.by_centre = False
        self.centre_routes = {}
        self.debug = []
        self.views = {}
        self.new_ids = []
        self.lines = []          # (kind, text) - kind in ok / warn / fail
        self.reference_kind = REF_FACING

    def add(self, kind, text):
        self.lines.append((kind, text))


def _set_failure_handling(transaction):
    try:
        options = transaction.GetFailureHandlingOptions()
        options.SetFailuresPreprocessor(WarningSwallower())
        options.SetClearAfterRollback(True)
        transaction.SetFailureHandlingOptions(options)
    except Exception:
        pass


def _tick(progress, done, total, label):
    """Report progress, if anyone is listening.

    Only ever called with **no transaction open**.  The caller repaints the
    window from here, and letting Revit's message loop run between a
    transaction's Start and Commit can leave the write with nothing committed.
    That is the whole reason this run is chunked rather than one transaction.
    """
    if progress is None:
        return
    try:
        progress(done, total, label)
    except Exception:
        pass


def replace_all(doc, uidoc, instances, symbol_id, retain_names,
                z_offset_mm, match_orientation, extra_degrees,
                level_below_point=True, retain_circuits=True,
                retain_tags=True, retain_wires=True,
                replace_in_groups=False, progress=None,
                drafting=False, match_mirror=True, by_centre=False):
    """Swap every instance for the replacement type. One transaction group.

    With drafting set, the instances are import symbols and each is replaced
    by a detail item centred on it and turned to match - see
    _replace_import_one. Circuits, wires, levels and groups do not apply there.
    """
    if drafting:
        replace_in_groups = False
    report = Report()
    report.by_centre = bool(by_centre)
    reset_run_caches()
    symbol = doc.GetElement(symbol_id)
    if not isinstance(symbol, FamilySymbol):
        report.add('fail', 'The replacement type is no longer in the model.')
        return report

    if len(instances) > MAX_ELEMENTS:
        report.add('fail', fmt(
            'The selection reaches {0} elements, past the {1} limit. Narrow '
            'the scope and run it again.', len(instances), MAX_ELEMENTS))
        return report

    z_offset_ft = mm_to_ft(z_offset_mm)
    extra_radians = math.radians(float(extra_degrees or 0.0))

    # The types being replaced *from*.  Matching group members against the
    # replacement type instead of these is what made 1.4.0 report "nothing
    # inside it would replace" on a group that plainly held the family: it was
    # looking for elements that had already been swapped.
    source_type_ids = set()
    for element in instances:
        try:
            source_type_ids.add(eid_value(element.GetTypeId()))
        except Exception:
            continue

    # Element ids, not element handles: the run now spans several transactions
    # and a handle captured before the first one is not something to lean on
    # after the third.  Everything is re-fetched by id at the point of use.
    loose_ids = [element.Id for element in instances]
    group_work = []

    group = TransactionGroup(doc, 'RevoBIM Family Find & Replace')
    group.Start()
    try:
        if replace_in_groups:
            survey = Transaction(doc, 'Read groups')
            survey.Start()
            try:
                loose, group_work = survey_groups(doc, instances,
                                                  source_type_ids)
                loose_ids = [element.Id for element in loose]
                report.group_instances = count_group_instances(group_work)
            finally:
                survey.RollBack()

        total = len(loose_ids) + len(group_work)
        done = 0
        _tick(progress, done, total, 'Starting')

        activate = Transaction(doc, 'Activate type')
        activate.Start()
        _set_failure_handling(activate)
        try:
            if not symbol.IsActive:
                symbol.Activate()
                doc.Regenerate()
            activate.Commit()
        except Exception:
            try:
                activate.RollBack()
            except Exception:
                pass

        # Loose elements, in chunks.  One transaction for the whole batch is a
        # way to lose the whole batch, and it also leaves nowhere safe to
        # report progress from - the dispatcher must never be pumped between a
        # transaction's Start and Commit.  Progress is reported between chunks,
        # with nothing open.
        for begin in range(0, len(loose_ids), CHUNK_SIZE):
            chunk = loose_ids[begin:begin + CHUNK_SIZE]
            transaction = Transaction(doc, 'Replace families')
            transaction.Start()
            _set_failure_handling(transaction)
            try:
                for element_id in chunk:
                    source = doc.GetElement(element_id)
                    if source is None:
                        continue
                    sub = SubTransaction(doc)
                    try:
                        sub.Start()
                        if drafting:
                            ok, message = _replace_import_one(
                                doc, source, symbol, retain_names,
                                extra_radians, match_orientation,
                                match_mirror, report, retain_tags,
                                by_centre)
                        else:
                            ok, message = _replace_one(
                                doc, source, symbol, retain_names,
                                z_offset_ft, match_orientation, extra_radians,
                                report, level_below_point, retain_circuits,
                                retain_tags, retain_wires)
                        if ok:
                            sub.Commit()
                        else:
                            sub.RollBack()
                            report.add('fail', message)
                    except Exception as err:
                        try:
                            sub.RollBack()
                        except Exception:
                            pass
                        report.add('fail', fmt('Element {0}: {1}',
                                               eid_value(element_id), err))
                transaction.Commit()
            except Exception as err:
                try:
                    if transaction.HasStarted():
                        transaction.RollBack()
                except Exception:
                    pass
                report.add('fail', fmt('A batch of {0} was rolled back: {1}',
                                       len(chunk), err))
            done += len(chunk)
            _tick(progress, done, total,
                  fmt('{0} of {1} elements', min(done, len(loose_ids)),
                      len(loose_ids)))

        # One transaction per group type.  Taking a group apart and putting it
        # back is one move, so a type that fails rolls back whole - and the gap
        # between two of them is again somewhere safe to repaint.
        for item in group_work:
            transaction = Transaction(doc, 'Replace families in group')
            transaction.Start()
            _set_failure_handling(transaction)
            try:
                attempt = SubTransaction(doc)
                attempt.Start()
                swapped, problems, detail_groups, shifted = \
                    replace_in_group_type(
                        doc, item, symbol, source_type_ids, retain_names,
                        z_offset_ft, match_orientation, extra_radians, report,
                        level_below_point, retain_circuits, retain_tags,
                        retain_wires)
                if shifted:
                    # The fast route moved something. Undo all of it and
                    # rebuild every instance in place instead.
                    attempt.RollBack()
                    report.add('warn', fmt(
                        'Group "{0}": moving the other instances onto the new '
                        'type shifted them, so every instance was rebuilt in '
                        'place instead. Slower, but nothing moved.',
                        item.type_name))
                    swapped, problems, detail_groups = \
                        replace_in_group_type_slow(
                            doc, item, symbol, source_type_ids, retain_names,
                            z_offset_ft, match_orientation, extra_radians,
                            report, level_below_point, retain_circuits,
                            retain_tags, retain_wires)
                else:
                    attempt.Commit()

                if swapped:
                    transaction.Commit()
                    report.groups_done += len(item.group_ids)
                    if detail_groups:
                        report.add('warn', fmt(
                            'Group "{0}": {1} instance(s) had attached detail '
                            'groups, which do not survive being re-formed.',
                            item.type_name, detail_groups))
                    for problem in problems:
                        report.add('warn', fmt('Group "{0}": {1}',
                                               item.type_name, problem))
                else:
                    transaction.RollBack()
                    report.groups_failed += len(item.group_ids)
                    detail = problems[0] if problems else \
                        'nothing inside it matched the family being replaced'
                    report.add('fail', fmt(
                        'Group "{0}" was left alone - {1}',
                        item.type_name, detail))
            except Exception as err:
                try:
                    if transaction.HasStarted():
                        transaction.RollBack()
                except Exception:
                    pass
                report.groups_failed += len(item.group_ids)
                report.add('fail', fmt('Group "{0}" was left alone: {1}',
                                       item.type_name, err))
            done += 1
            _tick(progress, done, total,
                  fmt('group "{0}"', item.type_name))

        group.Assimilate()
        _tick(progress, total, total, 'Finished')
    except Exception as err:
        try:
            group.RollBack()
        except Exception:
            pass
        report.add('fail', fmt('The run was rolled back: {0}', err))
    if report.debug:
        write_debug([fmt(u'=== {0} - {1} import symbol(s) to {2} ===',
                         time.strftime('%Y-%m-%d %H:%M:%S'), len(instances),
                         elem_name(symbol))] + report.debug +
                    [fmt(u'  lined up by {0}; replaced {1}, moved after '
                         u'checking {2}, turned after checking {3}, '
                         u'unverified {4}',
                         u'centre' if report.by_centre else u'insertion point',
                         report.replaced, report.centre_corrected,
                         report.rotation_corrected,
                         report.centre_unverified)])
    return report


def _replace_one(doc, source, symbol, retain_names, z_offset_ft,
                 match_orientation, extra_radians, report,
                 level_below_point=True, retain_circuits=True,
                 retain_tags=True, retain_wires=True, allow_grouped=False):
    source_id = eid_value(source.Id)

    # Still guarded even on the group path: by the time this is reached from
    # replace_in_group_type the member has been ungrouped, so a live GroupId
    # here means the ungroup did not take and writing on regardless would edit
    # an element Revit still considers part of a group definition.
    try:
        if source.GroupId is not None and eid_value(source.GroupId) > 0:
            if allow_grouped:
                return False, fmt(
                    'Element {0} is still inside a group after it was '
                    'ungrouped, so it was left alone.', source_id)
            return False, fmt(
                'Element {0} is inside a group and was left alone - tick '
                '"Replace inside groups" to have them handled.', source_id)
    except Exception:
        pass

    point = instance_point(source)
    if point is None:
        return False, fmt('Element {0} is line based rather than point based '
                          'and was left alone.', source_id)

    kind = reference_kind(source) if match_orientation else REF_BASIS_X
    report.reference_kind = kind
    level = resolve_level(doc, source, point, level_below_point)
    host = None
    try:
        host = source.Host
    except Exception:
        host = None
    # Captured before anything is placed, and acted on before the original is
    # deleted - Revit removes a tag whose element has gone and leaves a wire
    # end dangling, so afterwards is too late for both.
    tags = tags_on(doc, source) if retain_tags else []
    wires = wire_links(doc, source) if retain_wires else []
    circuits = electrical_systems(source) if retain_circuits else []
    dropped = 0
    if not retain_circuits:
        # Asked for explicitly, so the circuits go when the originals do.
        # Counted rather than ignored, because it is the one setting here that
        # loses something that cannot be got back with an undo.
        dropped = len(electrical_systems(source))
    param_names = list(retain_names)
    try:
        was_pinned = bool(source.Pinned)
    except Exception:
        was_pinned = False

    created, route, errors = create_replacement(
        doc, symbol, point, level, host, placement_name(symbol))
    if created is None:
        # Every route, not just the last: which ones were even tried says what
        # placement type the family reported, and that is usually the answer.
        detail = '; '.join(errors) if errors \
            else 'no placement route was accepted'
        return False, fmt('Element {0}: the replacement would not place. {1}',
                          source_id, detail)
    report.routes[route] = report.routes.get(route, 0) + 1

    doc.Regenerate()
    # Setting a level parameter moves the element, so the level is forced on
    # first and the point corrected afterwards - not the other way round.
    level_note = force_level(doc, created, level)
    if level_note:
        report.levels_set[level_note] = report.levels_set.get(level_note, 0) + 1
    doc.Regenerate()
    place_at(doc, created, point, z_offset_ft)
    if match_orientation or abs(extra_radians) > 1.0e-9:
        match_rotation(doc, source, created, kind, extra_radians)
    doc.Regenerate()

    failed_params = []
    ok, message = carry_workset(source, created)
    if not ok and message:
        failed_params.append(message)
    # Phasing goes on before the circuit is touched, not after: a replacement
    # left on the view's phase rather than the original's is refused by
    # AddToCircuit.
    ok, message = carry_phasing(source, created)
    if not ok and message:
        failed_params.append(message)
    for name in param_names:
        ok, message = copy_parameter(source, created, name)
        if not ok and message:
            failed_params.append(message)

    if circuits:
        doc.Regenerate()
        joined, problems = transfer_circuits(doc, circuits, created)
        if joined < len(circuits):
            # The original still holds the circuit. Deleting it now would take
            # the circuit with it, so the element is refused instead and left
            # exactly as it was for the user to look at.
            return False, fmt(
                'Element {0} was left alone - {1} of {2} circuit(s) would not '
                'take the replacement, and deleting the original would have '
                'destroyed them. {3}',
                source_id, len(circuits) - joined, len(circuits),
                '; '.join(problems))
        report.circuits_kept += joined

    if wires:
        moved, problems = transfer_wires(doc, wires, source, created)
        report.wires_kept += moved
        for problem in problems:
            report.add('warn', fmt('Element {0}: {1}', source_id, problem))

    if tags:
        moved, problems = transfer_tags(doc, tags, source, created)
        report.tags_kept += moved
        for problem in problems:
            report.add('warn', fmt('Element {0}: {1}', source_id, problem))

    try:
        if was_pinned:
            source.Pinned = False
    except Exception:
        pass

    doc.Delete(source.Id)

    # The pin goes on inside the run rather than being left to the adjust
    # window, which the user may never open. adjust_elements releases it and
    # puts it back, so a pinned replacement can still be rotated afterwards.
    if was_pinned:
        try:
            created.Pinned = True
            report.pinned += 1
        except Exception:
            report.add('warn', fmt('Element {0}: the original was pinned and '
                                   'the replacement would not take the pin.',
                                   source_id))

    report.replaced += 1
    report.circuits_dropped += dropped
    report.new_ids.append(created.Id)
    if failed_params:
        report.add('warn', fmt('Element {0}: {1}',
                               source_id, '; '.join(failed_params)))
    return True, ''


# ---------------------------------------------------------------------------
# the post-run adjust
# ---------------------------------------------------------------------------

def adjust_elements(doc, element_ids, delta_degrees, delta_z_mm,
                    about_centre=False):
    """Rotate each replacement about its own insertion point and shift it in Z.

    Called with the difference from what is already applied, so the numbers in
    the window read as absolutes.

    With about_centre set - detail items from a drafting view - each one turns
    about its own drawn centre and its view's normal instead, and there is no
    Z: the run put each centre exactly on its import's centre, and turning
    about an insertion point that is not the middle would walk it off again.
    """
    angle = math.radians(float(delta_degrees or 0.0))
    dz = 0.0 if about_centre else mm_to_ft(delta_z_mm or 0.0)
    if abs(angle) < 1.0e-9 and abs(dz) < POINT_TOL_FT:
        return 0, []

    moved = 0
    problems = []
    transaction = Transaction(doc, 'RevoBIM adjust replacements')
    try:
        transaction.Start()
        options = transaction.GetFailureHandlingOptions()
        options.SetFailuresPreprocessor(WarningSwallower())
        transaction.SetFailureHandlingOptions(options)
        for element_id in element_ids:
            element = doc.GetElement(element_id)
            if element is None:
                continue
            # A pinned element refuses both transforms, so the pin comes off
            # for the move and goes straight back on.
            was_pinned = False
            try:
                was_pinned = bool(element.Pinned)
                if was_pinned:
                    element.Pinned = False
            except Exception:
                was_pinned = False
            try:
                if abs(angle) > 1.0e-9:
                    if about_centre:
                        view = owner_view(doc, element)
                        point, _route = measure_centre(doc, element, view)
                        _r, _u, normal = _view_axes(view)
                    else:
                        point = instance_point(element)
                        normal = XYZ.BasisZ
                    if point is not None:
                        axis = Line.CreateBound(point, point.Add(normal))
                        ElementTransformUtils.RotateElement(
                            doc, element_id, axis, angle)
                if abs(dz) > POINT_TOL_FT:
                    ElementTransformUtils.MoveElement(
                        doc, element_id, XYZ(0.0, 0.0, dz))
                moved += 1
            except Exception as err:
                problems.append(fmt('Element {0}: {1}',
                                    eid_value(element_id), err))
            finally:
                if was_pinned:
                    try:
                        element.Pinned = True
                    except Exception:
                        pass
        transaction.Commit()
    except Exception as err:
        try:
            if transaction.HasStarted():
                transaction.RollBack()
        except Exception:
            pass
        problems.append(str(err))
    return moved, problems


def select_elements(uidoc, element_ids):
    try:
        ids = List[ElementId]()
        for element_id in element_ids:
            ids.Add(element_id)
        uidoc.Selection.SetElementIds(ids)
        return True
    except Exception:
        return False
