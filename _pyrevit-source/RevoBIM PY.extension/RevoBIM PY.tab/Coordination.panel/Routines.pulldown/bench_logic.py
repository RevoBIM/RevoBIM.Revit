# -*- coding: utf-8 -*-
"""Logic bench for RevoBIM PY - Isolate Service Type.

    python bench_logic.py
    python bench_logic.py --selftest

The Revit API is stubbed, but the rules under test are the shipped code:
ist_core.isolate is called for real, and what it hands to
IsolateElementsTemporary is what is checked.  --selftest breaks the rules on
purpose and confirms the bench notices.
"""

import os
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)


# ===========================================================================
# a Revit that works
# ===========================================================================

class ElementId(object):
    def __init__(self, value):
        # A built-in parameter in the fake is a string; real Revit takes the
        # enum.  Either way the id has to carry it.
        try:
            self.Value = int(value)
        except (TypeError, ValueError):
            self.Value = value

    def __eq__(self, other):
        return isinstance(other, ElementId) and other.Value == self.Value

    def __hash__(self):
        return hash(self.Value)


class BuiltInCategory(object):
    OST_CableTray = -2008130
    OST_CableTrayFitting = -2008127
    OST_Conduit = -2008132
    OST_ConduitFitting = -2008128
    OST_DuctCurves = -2008000
    OST_FlexDuctCurves = -2008020
    OST_DuctFitting = -2008010
    OST_DuctAccessory = -2008016
    OST_DuctTerminal = -2008013
    OST_MechanicalEquipment = -2001140
    OST_FabricationDuctwork = -2008193
    OST_PipeCurves = -2008044
    OST_FlexPipeCurves = -2008049
    OST_PipeFitting = -2008049
    OST_PipeAccessory = -2008055
    OST_PlumbingFixtures = -2001160
    OST_PlumbingEquipment = -2001370
    OST_Sprinklers = -2008099
    OST_FabricationPipework = -2008203
    OST_PipeInsulations = -2008122
    OST_DuctInsulations = -2008123
    OST_DuctLinings = -2008124
    OST_ElectricalEquipment = -2001040
    OST_SectionBox = -2000709
    OST_Cameras = -2000500
    OST_RvtLinks = -2001352
    OST_Doors = -2000023
    OST_TextNotes = -2000300
    OST_Walls = -2000011


# OST_FlexPipeCurves and OST_PipeFitting must not share a number, or the
# bench cannot tell them apart.
BuiltInCategory.OST_FlexPipeCurves = -2008048


class BuiltInParameter(object):
    RBS_CTC_SERVICE_TYPE = "BIP_CTC_SERVICE_TYPE"
    RBS_DUCT_SYSTEM_TYPE_PARAM = "BIP_DUCT_SYSTEM_TYPE"
    RBS_PIPING_SYSTEM_TYPE_PARAM = "BIP_PIPING_SYSTEM_TYPE"
    ALL_MODEL_FAMILY_NAME = "BIP_FAMILY_NAME"
    ALL_MODEL_TYPE_NAME = "BIP_TYPE_NAME"


class CategoryType(object):
    Model = "Model"
    Annotation = "Annotation"


class RevitLinkInstance(object):
    pass


class View(object):
    pass


class SharedParameterElement(object):
    pass


class FilterRule(object):
    pass


class ElementParameterFilter(object):
    def __init__(self, rules):
        self.rules = list(rules)


class ParameterFilterRuleFactory(object):
    @staticmethod
    def CreateEqualsRule(param_id, value):
        return ("equals", param_id.Value, value)

    @staticmethod
    def CreateHasNoValueParameterRule(param_id):
        return ("novalue", param_id.Value)


class FakeFilter(object):
    def __init__(self, doc, name, cats, element_filter):
        doc.next_id[0] += 1
        self.Id = ElementId(doc.next_id[0])
        self.Name = name
        self.cats = [c.Value for c in cats]
        self.rules = element_filter.rules if element_filter else []


class ParameterFilterElement(object):
    @staticmethod
    def Create(doc, name, cats, element_filter=None):
        made = FakeFilter(doc, name, cats, element_filter)
        doc.filters[made.Id.Value] = made
        doc.created.append(made)
        return made

    @staticmethod
    def ElementFilterIsAcceptableForParameterFilterElement(doc, cats,
                                                          element_filter):
        return not [c for c in cats if c.Value in doc.unfilterable]


class ObjectType(object):
    Element = "Element"


class OperationCanceledException(Exception):
    pass


class StorageType(object):
    String = "String"
    Double = "Double"


class TemporaryViewMode(object):
    TemporaryHideIsolate = "TemporaryHideIsolate"


class NetList(list):
    def Add(self, item):
        self.append(item)

    @property
    def Count(self):
        return len(self)


class List(object):
    def __class_getitem__(cls, item):
        return NetList


class Transaction(object):
    log = []

    def __init__(self, doc, name):
        self.doc = doc
        self.name = name

    def Start(self):
        Transaction.log.append(("start", self.name))

    def Commit(self):
        Transaction.log.append(("commit", self.name))

    def RollBack(self):
        Transaction.log.append(("rollback", self.name))


class ElementMulticategoryFilter(object):
    def __init__(self, categories):
        self.categories = set(int(c) for c in categories)


class FilteredElementCollector(object):
    def __init__(self, doc, view_id=None, link_id=None):
        self.doc = doc
        self.view_id = view_id
        self.filter = None
        self.raw = False
        if link_id is not None:
            if not doc.link_scoped:
                raise TypeError("this Revit has no view-scoped link collector")
            link = doc.link_by_id[link_id.Value]
            self.items = list(link.GetLinkDocument().elements)
        else:
            self.items = list(doc.elements)

    def OfClass(self, cls):
        self.raw = True
        if cls is RevitLinkInstance:
            self.items = [l for l in self.doc.links
                          if self.view_id is None or l.in_view]
        elif cls is ParameterFilterElement:
            self.items = list(self.doc.filters.values())
        elif cls is View:
            self.items = list(self.doc.views)
        elif cls is SharedParameterElement:
            self.items = list(self.doc.shared)
        else:
            self.items = []
        return self

    def WherePasses(self, element_filter):
        self.filter = element_filter
        return self

    def WhereElementIsNotElementType(self):
        return self

    def OfCategoryId(self, category_id):
        self.filter = ElementMulticategoryFilter([category_id.Value])
        return self

    def OfCategory(self, member):
        self.filter = ElementMulticategoryFilter([member])
        return self

    def __iter__(self):
        if self.raw:
            for item in self.items:
                yield item
            return
        for element in self.items:
            if self.view_id is not None and not element.in_view:
                continue
            if self.filter is not None and \
                    element.category_int not in self.filter.categories:
                continue
            yield element


class FakeParam(object):
    def __init__(self, value):
        self.value = value
        self.StorageType = StorageType.String

    def AsString(self):
        return self.value

    def AsValueString(self):
        return self.value


class FakeCategory(object):
    def __init__(self, value, name, kind=None):
        self.Id = ElementId(value)
        self.Name = name
        self.CategoryType = kind or CategoryType.Model


class FakeElement(object):
    counter = [1000]

    def __init__(self, cat_name, params=None, type_params=None,
                 in_view=True, type_id=None, host=None, annotation=False,
                 cat_int=None, label=None):
        FakeElement.counter[0] += 1
        self.Id = ElementId(FakeElement.counter[0])
        self.cat_name = cat_name
        self.category_int = cat_int if cat_int is not None \
            else getattr(BuiltInCategory, cat_name)
        self.Category = FakeCategory(
            self.category_int, label or cat_name,
            CategoryType.Annotation if annotation else CategoryType.Model)
        self.params = params or {}
        self.type_params = type_params or {}
        self.in_view = in_view
        self._type_id = ElementId(type_id if type_id is not None else 7)
        self.HostElementId = host if host is not None else ElementId(-1)
        self.hideable = True

    def CanBeHidden(self, view):
        return self.hideable

    def IsHidden(self, view):
        return self.Id.Value in getattr(view, "hidden_ids", set())

    def GetParameters(self, name):
        if name in self.params:
            return [FakeParam(self.params[name])]
        return []

    def LookupParameter(self, name):
        if name in self.params:
            return FakeParam(self.params[name])
        return None

    # In real Revit a built-in IS the parameter shown under its English name,
    # so a lookup either way has to land on the same value.
    BIP_NAMES = {
        "BIP_PIPING_SYSTEM_TYPE": "System Type",
        "BIP_DUCT_SYSTEM_TYPE": "System Type",
        "BIP_CTC_SERVICE_TYPE": "Service Type",
    }
    BIP_OWNERS = {
        "BIP_PIPING_SYSTEM_TYPE": ("Pipe", "Plumbing", "Sprinkler",
                                   "Mechanical"),
        "BIP_DUCT_SYSTEM_TYPE": ("Duct", "Mechanical"),
        "BIP_CTC_SERVICE_TYPE": ("CableTray", "Conduit"),
    }

    def get_Parameter(self, bip):
        if bip in self.params:
            return FakeParam(self.params[bip])
        name = self.BIP_NAMES.get(bip)
        owners = self.BIP_OWNERS.get(bip, ())
        if name and name in self.params and \
                [o for o in owners if o in self.cat_name]:
            return FakeParam(self.params[name])
        return None

    def GetTypeId(self):
        return self._type_id


class FakeType(object):
    def __init__(self, params, family=None, name=None):
        self.params = params
        self.FamilyName = family or "A Family"
        self.Name = name or "A Type"

    def GetParameters(self, name):
        if name in self.params:
            return [FakeParam(self.params[name])]
        return []

    def LookupParameter(self, name):
        if name in self.params:
            return FakeParam(self.params[name])
        return None

    def get_Parameter(self, bip):
        return None


class FakeView(object):
    counter = [0]

    def __init__(self, usable=True, isolated=False):
        FakeView.counter[0] += 1
        self.Id = ElementId(99)
        self.UniqueId = "view-{0}".format(FakeView.counter[0])
        self.hidden_ids = set()
        self.Name = "Level 00 - Power"
        self.usable = usable
        self.isolated = isolated
        self.given = None
        self.hidden = None
        self.hidden_permanently = False
        self.disabled = 0
        self.filters = []
        self.filter_visible = {}
        self.template_locked = False

    def GetFilters(self):
        return list(self.filters)

    def AddFilter(self, filter_id):
        if self.template_locked:
            raise Exception("The view template controls this view's filters")
        self.filters.append(filter_id)

    def RemoveFilter(self, filter_id):
        self.filters = [f for f in self.filters if f.Value != filter_id.Value]

    def SetFilterVisibility(self, filter_id, visible):
        self.filter_visible[filter_id.Value] = visible

    def CanUseTemporaryVisibilityModes(self):
        return self.usable

    def IsTemporaryHideIsolateActive(self):
        return self.isolated

    def DisableTemporaryViewMode(self, mode):
        self.disabled += 1
        self.isolated = False

    def IsolateElementsTemporary(self, ids):
        self.given = set(i.Value for i in ids)
        self.isolated = True

    def HideElementsTemporary(self, ids):
        self.hidden = set(i.Value for i in ids)
        self.isolated = True

    def HideElements(self, ids):
        self.hidden = set(i.Value for i in ids)
        self.hidden_ids |= self.hidden
        self.hidden_permanently = True

    def UnhideElements(self, ids):
        self.hidden_ids -= set(i.Value for i in ids)


class FakeView3D(FakeView):
    def __init__(self, usable=True, isolated=False, section=True):
        FakeView.__init__(self, usable=usable, isolated=isolated)
        self.IsSectionBoxActive = section


class FakeDoc(object):
    def __init__(self, elements, types=None, view=None, links=None,
                 title="Host", link_scoped=True):
        self.elements = elements
        self.types = types or {}
        self.ActiveView = view or FakeView()
        self.Title = title
        self.links = links or []
        self.link_by_id = dict((l.Id.Value, l) for l in self.links)
        self.link_scoped = link_scoped
        self.by_id = dict((e.Id.Value, e) for e in elements)
        for link in self.links:
            self.by_id[link.Id.Value] = link
        self.filters = {}
        self.created = []
        self.deleted = []
        self.unfilterable = set()
        self.shared = []
        self.views = [self.ActiveView]
        self.next_id = [900000]

    PathName = ""
    IsWorkshared = False

    def GetElement(self, element_id):
        if isinstance(element_id, str):
            for view in self.views:
                if view.UniqueId == element_id:
                    return view
            return None
        value = element_id.Value if hasattr(element_id, "Value") else element_id
        if value in self.types:
            return self.types[value]
        if value in self.filters:
            return self.filters[value]
        return self.by_id.get(value)

    def Delete(self, element_id):
        self.deleted.append(element_id.Value)
        self.filters.pop(element_id.Value, None)


class FakeLink(object):
    def __init__(self, link_doc, in_view=True):
        FakeElement.counter[0] += 1
        self.Id = ElementId(FakeElement.counter[0])
        self.link_doc = link_doc
        self.in_view = in_view

    def GetLinkDocument(self):
        return self.link_doc

    def CanBeHidden(self, view):
        return True

    def IsHidden(self, view):
        return self.Id.Value in getattr(view, "hidden_ids", set())


class FakeRef(object):
    def __init__(self, element):
        self.ElementId = element.Id


class FakeSelection(object):
    def __init__(self, elements, picks=None):
        self.elements = elements
        # None = Escape; a list = what was clicked before Finish
        self.picks = [] if picks is None else picks
        self.pick_calls = 0

    def GetElementIds(self):
        return [e.Id for e in self.elements]

    def PickObjects(self, object_type, prompt):
        self.pick_calls += 1
        if self.picks == "escape":
            raise OperationCanceledException("The user aborted the pick.")
        return [FakeRef(e) for e in self.picks]


class FakeUIDoc(object):
    def __init__(self, doc, selected, picks=None):
        self.Document = doc
        self.Selection = FakeSelection(selected, picks)


def install_stubs():
    clr = types.ModuleType("clr")
    clr.AddReference = lambda name: None
    sys.modules["clr"] = clr

    for name in ("Autodesk", "Autodesk.Revit", "System"):
        sys.modules[name] = types.ModuleType(name)

    db = types.ModuleType("Autodesk.Revit.DB")
    for key, value in [
            ("BuiltInCategory", BuiltInCategory),
            ("BuiltInParameter", BuiltInParameter),
            ("ElementId", ElementId),
            ("ElementMulticategoryFilter", ElementMulticategoryFilter),
            ("FilteredElementCollector", FilteredElementCollector),
            ("StorageType", StorageType),
            ("TemporaryViewMode", TemporaryViewMode),
            ("Transaction", Transaction),
            ("CategoryType", CategoryType),
            ("RevitLinkInstance", RevitLinkInstance),
            ("View", View),
            ("SharedParameterElement", SharedParameterElement),
            ("FilterRule", FilterRule),
            ("ElementParameterFilter", ElementParameterFilter),
            ("ParameterFilterRuleFactory", ParameterFilterRuleFactory),
            ("ParameterFilterElement", ParameterFilterElement)]:
        setattr(db, key, value)
    sys.modules["Autodesk.Revit.DB"] = db

    sys.modules["Autodesk.Revit.UI"] = types.ModuleType("Autodesk.Revit.UI")
    ui_selection = types.ModuleType("Autodesk.Revit.UI.Selection")
    ui_selection.ObjectType = ObjectType
    sys.modules["Autodesk.Revit.UI.Selection"] = ui_selection

    generic = types.ModuleType("System.Collections.Generic")
    generic.List = List
    sys.modules["System.Collections.Generic"] = generic


install_stubs()
import ist_core  # noqa: E402
import ist_browse  # noqa: E402
import ist_memory  # noqa: E402
import ist_templates  # noqa: E402

ist_memory.MEMORY_DIR = tempfile.mkdtemp(prefix="ist_memory_")
ist_templates.TEMPLATES_PATH = os.path.join(
    tempfile.mkdtemp(prefix="ist_templates_"), "hide_templates.json")


# ===========================================================================
# scenarios
# ===========================================================================

class Bench(object):
    def __init__(self):
        self.passed = 0
        self.failed = []

    def check(self, name, condition, detail=""):
        if condition:
            self.passed += 1
        else:
            self.failed.append((name, detail))

    def equal(self, name, got, wanted):
        self.check(name, got == wanted, "got {0!r}, wanted {1!r}".format(
            got, wanted))


def settings(**overrides):
    values = dict(ist_core.DEFAULTS)
    values.update(overrides)
    return values


def tray_model():
    """Two services of cable tray plus a duct run, some out of the view."""
    small = [
        FakeElement("OST_CableTray", {"Service Type": "Small Power"}),
        FakeElement("OST_CableTray", {"Service Type": "Small Power"}),
        FakeElement("OST_CableTrayFitting", {"Service Type": "Small Power"}),
    ]
    lighting = [
        FakeElement("OST_CableTray", {"Service Type": "Lighting"}),
        FakeElement("OST_CableTrayFitting", {"Service Type": "Lighting"}),
    ]
    out_of_view = [
        FakeElement("OST_CableTray", {"Service Type": "Small Power"},
                    in_view=False),
    ]
    ducts = [
        FakeElement("OST_DuctCurves", {"System Type": "Supply Air"}),
        FakeElement("OST_DuctFitting", {"System Type": "Supply Air"}),
        FakeElement("OST_DuctTerminal", {"System Type": "Extract Air"}),
    ]
    return small, lighting, out_of_view, ducts


def run(bench):
    # -- 1. one tray picked, its own service only ---------------------------
    small, lighting, out_of_view, ducts = tray_model()
    elements = small + lighting + out_of_view + ducts
    doc = FakeDoc(elements)
    uidoc = FakeUIDoc(doc, [small[0]])
    report = ist_core.isolate(uidoc, settings())
    bench.equal("one tray isolates its own service",
                doc.ActiveView.given, set(e.Id.Value for e in small))
    bench.check("the other service is left out",
                not [e for e in lighting if e.Id.Value in doc.ActiveView.given])
    bench.check("the fitting comes with the tray",
                small[2].Id.Value in doc.ActiveView.given)
    bench.check("out of view stays out",
                out_of_view[0].Id.Value not in doc.ActiveView.given)
    bench.check("ducts are untouched",
                not [e for e in ducts if e.Id.Value in doc.ActiveView.given])
    bench.equal("the count is reported", report.count, 3)
    bench.check("nothing needed a look", not report.needs_look, report.notes)

    # -- 2. a fitting picked reads the same way -----------------------------
    doc = FakeDoc(elements)
    uidoc = FakeUIDoc(doc, [small[2]])
    ist_core.isolate(uidoc, settings())
    bench.equal("a fitting picked isolates the whole service",
                doc.ActiveView.given, set(e.Id.Value for e in small))

    # -- 3. mixed selection, every rule at once -----------------------------
    doc = FakeDoc(elements)
    uidoc = FakeUIDoc(doc, [small[0], ducts[0]])
    ist_core.isolate(uidoc, settings())
    wanted = set(e.Id.Value for e in small) | \
        set([ducts[0].Id.Value, ducts[1].Id.Value])
    bench.equal("a mixed pick applies both rules", doc.ActiveView.given, wanted)
    bench.check("the extract terminal is left out",
                ducts[2].Id.Value not in doc.ActiveView.given)

    # -- 4. case ------------------------------------------------------------
    odd = FakeElement("OST_CableTray", {"Service Type": "small power"})
    doc = FakeDoc(elements + [odd])
    uidoc = FakeUIDoc(doc, [small[0]])
    ist_core.isolate(uidoc, settings())
    bench.check("case is ignored by default",
                odd.Id.Value in doc.ActiveView.given)

    doc = FakeDoc(elements + [odd])
    uidoc = FakeUIDoc(doc, [small[0]])
    ist_core.isolate(uidoc, settings(match_case="on"))
    bench.check("match_case on splits them",
                odd.Id.Value not in doc.ActiveView.given)

    # -- 5. a blank value ---------------------------------------------------
    blank = FakeElement("OST_CableTray", {})
    doc = FakeDoc(elements + [blank])
    uidoc = FakeUIDoc(doc, [blank])
    report = ist_core.isolate(uidoc, settings())
    bench.check("a blank pick on its own is refused by default, never widened",
                report.refused is not None and doc.ActiveView.given is None)
    bench.check("and the note says it was left out",
                [n for n in report.notes if "left out" in n])

    doc = FakeDoc(elements + [blank])
    uidoc = FakeUIDoc(doc, [blank])
    report = ist_core.isolate(uidoc, settings(blank_value="group"))
    every_tray = set(e.Id.Value for e in small + lighting + [blank])
    bench.equal("blank_value=group still takes the whole group when asked",
                doc.ActiveView.given, every_tray)
    bench.check("and says so", report.needs_look)

    doc = FakeDoc(elements + [blank])
    uidoc = FakeUIDoc(doc, [blank])
    ist_core.isolate(uidoc, settings(blank_value="blank"))
    bench.equal("blank_value=blank matches other blanks only",
                doc.ActiveView.given, set([blank.Id.Value]))

    doc = FakeDoc(elements + [blank])
    uidoc = FakeUIDoc(doc, [blank])
    report = ist_core.isolate(uidoc, settings(blank_value="skip"))
    bench.check("blank_value=skip refuses rather than guessing",
                report.refused is not None, report.refused)

    # -- 6. the parameter is on the type ------------------------------------
    typed = FakeElement("OST_PipeCurves", {}, type_id=55)
    other = FakeElement("OST_PipeFitting", {}, type_id=55)
    stranger = FakeElement("OST_PipeCurves", {}, type_id=56)
    doc = FakeDoc([typed, other, stranger], types={
        55: FakeType({"System Type": "LTHW Flow"}),
        56: FakeType({"System Type": "Chilled Water"}),
    })
    uidoc = FakeUIDoc(doc, [typed])
    ist_core.isolate(uidoc, settings())
    bench.equal("a type parameter is found and cached",
                doc.ActiveView.given,
                set([typed.Id.Value, other.Id.Value]))

    # -- 7. a renamed parameter ---------------------------------------------
    named = [FakeElement("OST_Conduit", {"BGL_Service": "Fire Alarm"}),
             FakeElement("OST_ConduitFitting", {"BGL_Service": "Fire Alarm"}),
             FakeElement("OST_Conduit", {"BGL_Service": "Data"})]
    doc = FakeDoc(named)
    uidoc = FakeUIDoc(doc, [named[0]])
    report = ist_core.isolate(uidoc, settings(param_conduit="BGL_Service"))
    bench.equal("the parameter is settable per discipline",
                doc.ActiveView.given,
                set([named[0].Id.Value, named[1].Id.Value]))

    doc = FakeDoc(named)
    uidoc = FakeUIDoc(doc, [named[0]])
    report = ist_core.isolate(uidoc, settings())
    bench.check("with the default parameter nothing answers, so it refuses "
                "rather than taking every conduit",
                report.refused is not None and doc.ActiveView.given is None)

    # -- 8. mechanical equipment sits in both groups ------------------------
    plant = FakeElement("OST_MechanicalEquipment", {"System Type": "LTHW Flow"})
    pipe = FakeElement("OST_PipeCurves", {"System Type": "LTHW Flow"})
    duct = FakeElement("OST_DuctCurves", {"System Type": "LTHW Flow"})
    doc = FakeDoc([plant, pipe, duct])
    uidoc = FakeUIDoc(doc, [plant])
    ist_core.isolate(uidoc, settings())
    bench.equal("out of the box equipment is a duct category only",
                doc.ActiveView.given,
                set([plant.Id.Value, duct.Id.Value]))

    both = settings(cats_pipe=ist_core.DEFAULTS["cats_pipe"] +
                    ",OST_MechanicalEquipment")
    doc = FakeDoc([plant, pipe, duct])
    uidoc = FakeUIDoc(doc, [plant])
    ist_core.isolate(uidoc, both)
    bench.equal("ticked into both, it pulls both",
                doc.ActiveView.given,
                set([plant.Id.Value, pipe.Id.Value, duct.Id.Value]))

    # -- 9. a category switched off -----------------------------------------
    doc = FakeDoc(elements)
    uidoc = FakeUIDoc(doc, [small[0]])
    ist_core.isolate(uidoc, settings(cats_tray="OST_CableTray"))
    bench.check("un-ticking fittings leaves them out",
                small[2].Id.Value not in doc.ActiveView.given)

    # -- 10. insulation ------------------------------------------------------
    run_pipe = FakeElement("OST_PipeCurves", {"System Type": "LTHW Flow"})
    lagging = FakeElement("OST_PipeInsulations", {}, host=run_pipe.Id)
    stray = FakeElement("OST_PipeInsulations", {}, host=ElementId(4242))
    doc = FakeDoc([run_pipe, lagging, stray])
    uidoc = FakeUIDoc(doc, [run_pipe])
    ist_core.isolate(uidoc, settings())
    bench.check("insulation travels with its host",
                lagging.Id.Value in doc.ActiveView.given)
    bench.check("somebody else's insulation does not",
                stray.Id.Value not in doc.ActiveView.given)

    doc = FakeDoc([run_pipe, lagging, stray])
    uidoc = FakeUIDoc(doc, [run_pipe])
    ist_core.isolate(uidoc, settings(include_insulation="off"))
    bench.check("and it can be switched off",
                lagging.Id.Value not in doc.ActiveView.given)

    # -- 11. the empty-selection toggle -------------------------------------
    view = FakeView(isolated=True)
    doc = FakeDoc(elements, view=view)
    uidoc = FakeUIDoc(doc, [])
    report = ist_core.isolate(uidoc, settings())
    bench.check("nothing selected resets an isolated view", report.reset)
    bench.check("and the view mode was actually disabled", view.disabled == 1)

    view = FakeView(isolated=False)
    doc = FakeDoc(elements, view=view)
    uidoc = FakeUIDoc(doc, [])
    report = ist_core.isolate(uidoc, settings())
    bench.check("nothing selected in a normal view asks for a pick",
                report.refused is not None and report.reset is False)

    view = FakeView(isolated=True)
    doc = FakeDoc(elements, view=view)
    uidoc = FakeUIDoc(doc, [])
    report = ist_core.isolate(uidoc, settings(empty_selection_resets="off"))
    bench.check("the toggle can be switched off", not report.reset)

    # -- 12. an already isolated view is replaced, not nested ---------------
    view = FakeView(isolated=True)
    doc = FakeDoc(elements, view=view)
    uidoc = FakeUIDoc(doc, [small[0]])
    ist_core.isolate(uidoc, settings())
    bench.check("a second run clears the first isolation", view.disabled == 1)

    # -- 13. refusals --------------------------------------------------------
    view = FakeView(usable=False)
    doc = FakeDoc(elements, view=view)
    uidoc = FakeUIDoc(doc, [small[0]])
    report = ist_core.isolate(uidoc, settings())
    bench.check("a view that will not isolate is refused, not attempted",
                report.refused is not None and view.given is None)

    wall = FakeElement("OST_Walls", {})
    doc = FakeDoc(elements + [wall])
    uidoc = FakeUIDoc(doc, [wall])
    report = ist_core.isolate(uidoc, settings(other_scope="ignore"))
    bench.check("with the other-category rule off, an unhandled category is "
                "named and refused",
                report.refused is not None and
                [n for n in report.notes if "Walls" in n])

    # -- 14. the selection is always kept -----------------------------------
    doc = FakeDoc(elements)
    uidoc = FakeUIDoc(doc, [small[0], wall])
    ist_core.isolate(uidoc, settings(other_scope="ignore"))
    bench.check("what was picked stays visible",
                wall.Id.Value in doc.ActiveView.given)

    doc = FakeDoc(elements)
    uidoc = FakeUIDoc(doc, [small[0], wall])
    ist_core.isolate(uidoc, settings(other_scope="ignore",
                                     include_selection="off"))
    bench.check("unless that is switched off",
                wall.Id.Value not in doc.ActiveView.given)

    # -- 14b. a category with no service type -------------------------------
    boards = FakeDoc([], types={
        61: FakeType({}, family="BGL_Distribution Board", name="DB-A"),
        62: FakeType({}, family="BGL_Distribution Board", name="DB-B"),
        63: FakeType({}, family="BGL_Switchboard", name="MSB"),
    })
    picked = FakeElement("OST_ElectricalEquipment", {}, type_id=61)
    same_family = FakeElement("OST_ElectricalEquipment", {}, type_id=62)
    same_type = FakeElement("OST_ElectricalEquipment", {}, type_id=61)
    other_family = FakeElement("OST_ElectricalEquipment", {}, type_id=63)
    hidden = FakeElement("OST_ElectricalEquipment", {}, type_id=61,
                         in_view=False)
    boards_list = [picked, same_family, same_type, other_family, hidden]

    def board_doc():
        doc = FakeDoc(elements + boards_list, types=boards.types)
        return doc

    doc = board_doc()
    uidoc = FakeUIDoc(doc, [small[0], picked])
    report = ist_core.isolate(uidoc, settings())
    bench.equal("a tray plus a board isolates the tray service and the whole "
                "board category",
                doc.ActiveView.given,
                set(e.Id.Value for e in small) |
                set([picked.Id.Value, same_family.Id.Value,
                     same_type.Id.Value, other_family.Id.Value]))
    bench.check("a board outside the view stays outside",
                hidden.Id.Value not in doc.ActiveView.given)
    bench.check("and both halves are reported",
                len([l for l in report.lines if "Cable tray" in l]) == 1 and
                len([l for l in report.lines
                     if "OST_ElectricalEquipment" in l]) == 1)

    doc = board_doc()
    uidoc = FakeUIDoc(doc, [small[0], picked])
    ist_core.isolate(uidoc, settings(other_scope="family"))
    bench.equal("scoped to the family, only that family comes",
                doc.ActiveView.given,
                set(e.Id.Value for e in small) |
                set([picked.Id.Value, same_family.Id.Value,
                     same_type.Id.Value]))

    doc = board_doc()
    uidoc = FakeUIDoc(doc, [small[0], picked])
    ist_core.isolate(uidoc, settings(other_scope="type"))
    bench.equal("scoped to the type, only that type comes",
                doc.ActiveView.given,
                set(e.Id.Value for e in small) |
                set([picked.Id.Value, same_type.Id.Value]))

    doc = board_doc()
    uidoc = FakeUIDoc(doc, [small[0], picked])
    report = ist_core.isolate(uidoc, settings(other_scope="ignore"))
    bench.equal("ignored, only the picked one survives, through the "
                "keep-the-selection rule",
                doc.ActiveView.given,
                set(e.Id.Value for e in small) | set([picked.Id.Value]))
    bench.check("and it says the category was left out", report.needs_look)

    doc = board_doc()
    uidoc = FakeUIDoc(doc, [picked])
    report = ist_core.isolate(uidoc, settings())
    bench.check("a board on its own is enough to run on",
                report.refused is None)
    bench.equal("and takes its category with it",
                doc.ActiveView.given,
                set([picked.Id.Value, same_family.Id.Value,
                     same_type.Id.Value, other_family.Id.Value]))

    doc = board_doc()
    uidoc = FakeUIDoc(doc, [picked, other_family])
    ist_core.isolate(uidoc, settings(other_scope="family"))
    bench.equal("two families picked bring both",
                doc.ActiveView.given,
                set([picked.Id.Value, same_family.Id.Value,
                     same_type.Id.Value, other_family.Id.Value]))

    # An air terminal un-ticked out of the duct group is no longer a service
    # type category, so the same rule takes it.
    terminal = FakeElement("OST_DuctTerminal", {"System Type": "Extract Air"},
                           type_id=61)
    doc = FakeDoc([terminal, ducts[0]], types=boards.types)
    uidoc = FakeUIDoc(doc, [terminal])
    ist_core.isolate(uidoc, settings(
        cats_duct="OST_DuctCurves,OST_DuctFitting"))
    bench.check("an un-ticked category falls to the other-category rule",
                terminal.Id.Value in doc.ActiveView.given)

    # -- 14c. the section box of a 3D view -----------------------------------
    box = FakeElement("OST_SectionBox", {})
    tray = FakeElement("OST_CableTray", {"Service Type": "Small Power"})
    stray = FakeElement("OST_CableTray", {"Service Type": "Lighting"})
    view3d = FakeView3D()
    doc = FakeDoc([tray, stray, box], view=view3d)
    uidoc = FakeUIDoc(doc, [tray])
    ist_core.isolate(uidoc, settings())
    bench.check("the section box comes through without being picked",
                box.Id.Value in doc.ActiveView.given)
    bench.check("and nothing else does",
                stray.Id.Value not in doc.ActiveView.given)

    view3d = FakeView3D()
    doc = FakeDoc([tray, stray, box], view=view3d)
    uidoc = FakeUIDoc(doc, [tray])
    ist_core.isolate(uidoc, settings(include_selection="off"))
    bench.check("even with keep-the-selection off",
                box.Id.Value in doc.ActiveView.given)

    plan = FakeView()
    doc = FakeDoc([tray, stray, box], view=plan)
    uidoc = FakeUIDoc(doc, [tray])
    ist_core.isolate(uidoc, settings())
    bench.check("a plan view is not asked for a section box",
                box.Id.Value not in doc.ActiveView.given)

    # -- 14d. saying nothing about what was left out --------------------------
    blank_tray = FakeElement("OST_CableTray", {})
    doc = FakeDoc(elements + [blank_tray])
    uidoc = FakeUIDoc(doc, [blank_tray])
    loud = ist_core.isolate(uidoc, settings(blank_value="group"))
    bench.check("by default it says what it widened", loud.needs_look)

    doc = FakeDoc(elements + [blank_tray])
    uidoc = FakeUIDoc(doc, [blank_tray])
    quiet = ist_core.isolate(uidoc, settings(blank_value="group",
                                             hide_uncaptured="on"))
    bench.check("switched on, it says nothing",
                not quiet.needs_look and not quiet.notes)
    bench.equal("and isolates exactly the same elements",
                doc.ActiveView.given,
                set(e.Id.Value for e in small + lighting + [blank_tray]))

    doc = FakeDoc(elements)
    uidoc = FakeUIDoc(doc, [])
    silent = ist_core.isolate(uidoc, settings(hide_uncaptured="on"))
    bench.check("a refusal still reports, because nothing happened",
                silent.refused is not None and silent.needs_look)

    # -- 14e. Hide Service Type ----------------------------------------------
    vent = [FakeElement("OST_PipeCurves", {"System Type": "Vent"}),
            FakeElement("OST_PipeFitting", {"System Type": "Vent"}),
            FakeElement("OST_PlumbingFixtures", {"System Type": "Vent"})]
    soil = [FakeElement("OST_PipeCurves", {"System Type": "Soil"}),
            FakeElement("OST_PipeFitting", {"System Type": "Soil"})]
    air = [FakeElement("OST_DuctCurves", {"System Type": "Vent"})]
    drainage = vent + soil + air

    doc = FakeDoc(drainage)
    uidoc = FakeUIDoc(doc, [vent[0]])
    report = ist_core.hide(uidoc, settings())
    bench.equal("hiding a Vent pipe takes the whole Vent pipe service",
                doc.ActiveView.hidden, set(e.Id.Value for e in vent))
    bench.check("the soil run stays visible",
                not [e for e in soil if e.Id.Value in doc.ActiveView.hidden])
    bench.check("a duct on the same words is a different discipline and stays",
                air[0].Id.Value not in doc.ActiveView.hidden)
    bench.check("nothing was isolated", doc.ActiveView.given is None)
    bench.equal("the report says hidden", report.verb, "hidden")
    bench.equal("and counts them", report.count, 3)

    doc = FakeDoc(drainage)
    uidoc = FakeUIDoc(doc, [vent[0]])
    ist_core.hide(uidoc, settings(include_selection="off"))
    bench.check("what was picked is hidden with the rest, whatever the "
                "keep-the-selection setting says",
                vent[0].Id.Value in doc.ActiveView.hidden)

    doc = FakeDoc(drainage)
    uidoc = FakeUIDoc(doc, [vent[0]])
    report = ist_core.hide(uidoc, settings())
    bench.check("remembered by default: Revit's Hide in View, written down",
                doc.ActiveView.hidden_permanently and report.memory)

    doc = FakeDoc(drainage)
    uidoc = FakeUIDoc(doc, [vent[0]])
    report = ist_core.hide(uidoc, settings(hide_mode="temporary"))
    bench.check("temporary is still a setting, and not remembered",
                not doc.ActiveView.hidden_permanently and not report.memory)

    doc = FakeDoc(drainage)
    uidoc = FakeUIDoc(doc, [vent[0]])
    ist_core.hide(uidoc, settings(hide_mode="permanent"))
    bench.check("set to permanent, it is Hide in View",
                doc.ActiveView.hidden_permanently)

    box2 = FakeElement("OST_SectionBox", {})
    view3d_hide = FakeView3D()
    doc = FakeDoc(drainage + [box2], view=view3d_hide)
    uidoc = FakeUIDoc(doc, [vent[0]])
    ist_core.hide(uidoc, settings())
    bench.check("hiding never takes the section box with it",
                box2.Id.Value not in doc.ActiveView.hidden)

    stubborn = FakeElement("OST_PipeCurves", {"System Type": "Vent"})
    stubborn.hideable = False
    doc = FakeDoc(drainage + [stubborn])
    uidoc = FakeUIDoc(doc, [vent[0]])
    report = ist_core.hide(uidoc, settings())
    bench.check("an element that cannot be hidden is dropped, not thrown on",
                stubborn.Id.Value not in doc.ActiveView.hidden)
    bench.check("and it is reported", report.needs_look)

    view = FakeView(isolated=True)
    doc = FakeDoc(drainage, view=view)
    uidoc = FakeUIDoc(doc, [])
    report = ist_core.hide(uidoc, settings())
    bench.check("Hide resets the same way Isolate does", report.reset)

    boards2 = FakeDoc([], types={71: FakeType({}, family="BGL_Board")})
    board = FakeElement("OST_ElectricalEquipment", {}, type_id=71)
    doc = FakeDoc(drainage + [board], types=boards2.types)
    uidoc = FakeUIDoc(doc, [vent[0], board])
    ist_core.hide(uidoc, settings())
    bench.equal("the other-category rule hides too",
                doc.ActiveView.hidden,
                set(e.Id.Value for e in vent) | set([board.Id.Value]))

    # -- 14f. the 1.3.0 "hid all pipes" bug ----------------------------------
    # A pipe with an EMPTY shared "Service Type" in front of its System Type.
    # 1.3.0 read the empty one, called it blank and took every pipe.
    def pipe(system, shared=""):
        return FakeElement("OST_PipeCurves",
                           {"Service Type": shared, "System Type": system})

    vent_a, vent_b = pipe("Vent"), pipe("Vent")
    soil_a = pipe("Soil")
    cws = FakeElement("OST_PipeFitting", {"System Type": "Domestic Cold Water"})
    vent_fix = FakeElement("OST_PlumbingFixtures", {"System Type": "Vent"})
    model = [vent_a, vent_b, soil_a, cws, vent_fix]

    for label, verb in (("hide", ist_core.hide), ("isolate", ist_core.isolate)):
        doc = FakeDoc(model)
        uidoc = FakeUIDoc(doc, [vent_a])
        verb(uidoc, settings(param_pipe="Service Type"))
        got = doc.ActiveView.hidden if label == "hide" else doc.ActiveView.given
        bench.equal("{0}: an empty Service Type falls through to System "
                    "Type".format(label), got,
                    set([vent_a.Id.Value, vent_b.Id.Value, vent_fix.Id.Value]))

    doc = FakeDoc(model)
    uidoc = FakeUIDoc(doc, [vent_a])
    ist_core.hide(uidoc, settings())
    bench.equal("out of the box pipes are read by System Type",
                doc.ActiveView.hidden,
                set([vent_a.Id.Value, vent_b.Id.Value, vent_fix.Id.Value]))
    bench.check("Soil and cold water stay",
                soil_a.Id.Value not in doc.ActiveView.hidden and
                cws.Id.Value not in doc.ActiveView.hidden)

    # the built-in answers where the name does not (a non-English Revit)
    bip_only = FakeElement("OST_PipeCurves",
                           {"BIP_PIPING_SYSTEM_TYPE": "Vent"})
    bip_other = FakeElement("OST_PipeCurves",
                            {"BIP_PIPING_SYSTEM_TYPE": "Soil"})
    doc = FakeDoc([bip_only, bip_other, vent_b])
    uidoc = FakeUIDoc(doc, [bip_only])
    ist_core.hide(uidoc, settings())
    bench.equal("the built-in System Type answers where the name does not",
                doc.ActiveView.hidden,
                set([bip_only.Id.Value, vent_b.Id.Value]))

    doc = FakeDoc([bip_only, bip_other, vent_b])
    uidoc = FakeUIDoc(doc, [bip_only])
    report = ist_core.hide(uidoc, settings(fallback_builtin="off"))
    bench.check("with the fallback off, a name-less pick is left out",
                report.refused is not None)

    # -- 14g. several picked, each by its own service -----------------------
    tray_sp = FakeElement("OST_CableTray", {"Service Type": "Small Power"})
    tray_sp2 = FakeElement("OST_CableTrayFitting",
                           {"Service Type": "Small Power"})
    tray_lt = FakeElement("OST_CableTray", {"Service Type": "Lighting"})
    mixed = model + [tray_sp, tray_sp2, tray_lt]
    doc = FakeDoc(mixed)
    uidoc = FakeUIDoc(doc, [tray_sp, vent_a])
    ist_core.hide(uidoc, settings())
    bench.equal("a tray and a pipe picked hide each one's own service",
                doc.ActiveView.hidden,
                set([tray_sp.Id.Value, tray_sp2.Id.Value, vent_a.Id.Value,
                     vent_b.Id.Value, vent_fix.Id.Value]))

    doc = FakeDoc(mixed)
    uidoc = FakeUIDoc(doc, [vent_a, soil_a])
    ist_core.hide(uidoc, settings())
    bench.equal("two pipe services picked hide both and nothing else",
                doc.ActiveView.hidden,
                set([vent_a.Id.Value, vent_b.Id.Value, vent_fix.Id.Value,
                     soil_a.Id.Value]))

    blank_pipe = FakeElement("OST_PipeCurves", {})
    doc = FakeDoc(mixed + [blank_pipe])
    uidoc = FakeUIDoc(doc, [vent_a, blank_pipe])
    report = ist_core.hide(uidoc, settings())
    bench.equal("a blank pipe picked alongside a vent never widens the hide",
                doc.ActiveView.hidden,
                set([vent_a.Id.Value, vent_b.Id.Value, vent_fix.Id.Value,
                     blank_pipe.Id.Value]))
    bench.check("and the blank one is reported", report.needs_look)

    # -- 14h. nothing selected: pick, then Finish ---------------------------
    doc = FakeDoc(mixed)
    uidoc = FakeUIDoc(doc, [], picks=[tray_lt, soil_a])
    ist_core.hide(uidoc, settings())
    bench.check("nothing selected opens the picker",
                uidoc.Selection.pick_calls == 1)
    bench.equal("and works from what was picked",
                doc.ActiveView.hidden,
                set([tray_lt.Id.Value, soil_a.Id.Value]))

    doc = FakeDoc(mixed)
    uidoc = FakeUIDoc(doc, [vent_a], picks=[soil_a])
    ist_core.hide(uidoc, settings())
    bench.check("a selection already made skips the picker",
                uidoc.Selection.pick_calls == 0)

    doc = FakeDoc(mixed)
    uidoc = FakeUIDoc(doc, [], picks="escape")
    report = ist_core.hide(uidoc, settings())
    bench.check("Escape changes nothing and opens no window",
                report.cancelled and not report.needs_look and
                doc.ActiveView.hidden is None)

    view = FakeView(isolated=True)
    doc = FakeDoc(mixed, view=view)
    uidoc = FakeUIDoc(doc, [], picks=[])
    report = ist_core.hide(uidoc, settings())
    bench.check("Finish on nothing resets a view that is hidden",
                report.reset and view.disabled == 1)

    view = FakeView(isolated=True)
    doc = FakeDoc(mixed, view=view)
    uidoc = FakeUIDoc(doc, [], picks=[soil_a])
    report = ist_core.isolate(uidoc, settings(nothing_selected="reset"))
    bench.check("set to reset, nothing selected resets without a picker",
                report.reset and uidoc.Selection.pick_calls == 0)

    # -- 14i. settings written by 1.3.0 are moved on --------------------------
    folder = tempfile.mkdtemp(prefix="ist_mig_")
    original_dir, original_path = ist_core.SETTINGS_DIR, ist_core.SETTINGS_PATH
    ist_core.SETTINGS_DIR = folder
    ist_core.SETTINGS_PATH = os.path.join(folder, "isolate_service_type.txt")
    try:
        handle = open(ist_core.SETTINGS_PATH, "w")
        handle.write("settings_version=1\nparam_pipe=Service Type\n"
                     "param_duct=Service Type\nblank_value=group\n"
                     "param_tray=BGL_Containment\ntheme=light\n")
        handle.close()
        moved = ist_core.load_settings()
        bench.equal("an old pipe parameter becomes System Type",
                    moved["param_pipe"], "System Type")
        bench.equal("and the duct one", moved["param_duct"], "System Type")
        bench.equal("the old whole-group default becomes skip",
                    moved["blank_value"], "skip")
        bench.equal("a tray parameter chosen by hand is kept",
                    moved["param_tray"], "BGL_Containment")
        bench.equal("and so is everything else", moved["theme"], "light")
    finally:
        ist_core.SETTINGS_DIR, ist_core.SETTINGS_PATH = \
            original_dir, original_path

    # -- 16. the category list: this model ------------------------------------
    B = ist_browse
    types_ = {
        81: FakeType({}, family="Basic Wall", name="100 Blockwork"),
        82: FakeType({}, family="Basic Wall", name="215 Blockwork"),
        83: FakeType({}, family="Single Door", name="900 x 2100"),
    }
    h_vent = [FakeElement("OST_PipeCurves", {"System Type": "Vent"}),
              FakeElement("OST_PipeCurves", {"System Type": "Vent"})]
    h_soil = [FakeElement("OST_PipeCurves", {"System Type": "Soil"})]
    h_blank = [FakeElement("OST_PipeCurves", {})]
    h_vfit = [FakeElement("OST_PipeFitting", {"System Type": "Vent"})]
    h_sp = [FakeElement("OST_CableTray", {"Service Type": "Small Power"})]
    h_w100 = [FakeElement("OST_Walls", {}, type_id=81),
              FakeElement("OST_Walls", {}, type_id=81)]
    h_w215 = [FakeElement("OST_Walls", {}, type_id=82)]
    h_door = [FakeElement("OST_Doors", {}, type_id=83)]
    h_note = [FakeElement("OST_TextNotes", {}, annotation=True)]
    h_box = [FakeElement("OST_SectionBox", {})]
    h_lag = [FakeElement("OST_PipeInsulations", {}, host=h_vent[0].Id)]
    h_gone = [FakeElement("OST_PipeCurves", {"System Type": "Vent"},
                          in_view=False)]
    host_elems = (h_vent + h_soil + h_blank + h_vfit + h_sp + h_w100 + h_w215 +
                  h_door + h_note + h_box + h_lag + h_gone)

    def ids(elems):
        return set(e.Id.Value for e in elems)

    doc = FakeDoc(host_elems, types=dict(types_))
    root = B.build_host(doc, doc.ActiveView, settings())
    labels = [c.label for c in root.children]
    bench.check("model categories in the view are listed",
                "OST_PipeCurves" in labels and "OST_Walls" in labels and
                "OST_Doors" in labels)
    bench.check("annotation, the section box and insulation are not",
                "OST_TextNotes" not in labels and
                "OST_SectionBox" not in labels and
                "OST_PipeInsulations" not in labels)
    pipes = [c for c in root.children if c.label == "OST_PipeCurves"][0]
    bench.equal("pipes split by service, blanks last",
                [c.label for c in pipes.children],
                ["Soil", "Vent", B.NO_SERVICE])
    bench.equal("an element outside the view is not counted",
                pipes.count, 4)
    walls = [c for c in root.children if c.label == "OST_Walls"][0]
    bench.equal("anything else splits by family",
                [c.label for c in walls.children], ["Basic Wall"])
    bench.equal("then by type",
                [(c.label, c.count) for c in walls.children[0].children],
                [("100 Blockwork", 2), ("215 Blockwork", 1)])

    doc_ins = FakeDoc(host_elems, types=dict(types_))
    root_ins = B.build_host(doc_ins, doc_ins.ActiveView,
                            settings(include_insulation="off"))
    bench.check("insulation is its own row when it does not travel",
                "OST_PipeInsulations" in [c.label for c in root_ins.children])

    # ticking
    vent_row = pipes.find(("s", "vent"))
    B.set_checked(vent_row, True)
    bench.check("ticking a service part-ticks its category",
                pipes.checked is None and root.checked is None)
    bench.equal("and the cover is just that row",
                B.cover(root), [vent_row])
    bench.equal("its ids are its elements", B.host_ids(B.cover(root)),
                ids(h_vent))
    for child in pipes.children:
        B.set_checked(child, True)
    bench.check("ticking every service ticks the category", pipes.checked)
    bench.equal("and the cover collapses to the category",
                B.cover(root), [pipes])
    B.set_checked(vent_row, False)
    bench.check("a part-ticked category is not True, so a click ticks all",
                pipes.checked is None and (pipes.checked is not True))
    B.set_checked(pipes, False)
    bench.check("un-ticking the category clears every row under it",
                not [n for n in pipes.walk() if n.checked])
    bench.check("and the root goes back to clear", root.checked is False)

    # -- 17. the category list: linked models -----------------------------------
    l_types = {91: FakeType({}, family="Basic Wall", name="100 Blockwork"),
               92: FakeType({}, family="Curtain Wall", name="CW1")}
    l_vent = [FakeElement("OST_PipeCurves", {"System Type": "Vent"})
              for _ in range(3)]
    l_cws = [FakeElement("OST_PipeCurves",
                         {"System Type": "Domestic Cold Water"})]
    l_duct = [FakeElement("OST_DuctCurves", {"System Type": "Supply Air"})]
    l_wall = [FakeElement("OST_Walls", {}, type_id=91) for _ in range(4)]
    l_cw = [FakeElement("OST_Walls", {}, type_id=92)]
    l_custom = [FakeElement("OST_Walls", {}, cat_int=123456,
                            label="BGL Custom")]
    l_out = [FakeElement("OST_PipeCurves", {"System Type": "Vent"},
                         in_view=False)]
    link_doc = FakeDoc(l_vent + l_cws + l_duct + l_wall + l_cw + l_custom +
                       l_out, types=l_types, title="BGL_MECH")
    link_doc_2 = FakeDoc([], title="BGL_MECH")
    unloaded = FakeLink(None)
    link_a = FakeLink(link_doc)
    link_b = FakeLink(link_doc_2)
    hidden_link = FakeLink(FakeDoc([], title="ARCH"), in_view=False)

    # link elements in the view only: the fake link collector reads in_view
    for e in l_out:
        e.in_view = False
    link_doc.elements = [e for e in link_doc.elements if e.in_view]

    def host_with_links(**kw):
        return FakeDoc(host_elems, types=dict(types_),
                       links=[link_a, link_b, unloaded, hidden_link], **kw)

    doc = host_with_links()
    host_root = B.build_host(doc, doc.ActiveView, settings())
    links_root = B.build_links_root(doc, doc.ActiveView)
    bench.equal("loaded links drawn in the view are listed, repeats numbered",
                [c.label for c in links_root.children],
                ["BGL_MECH", "BGL_MECH (2)"])
    first = links_root.children[0]
    bench.check("and not read until opened",
                not first.loaded and not first.children)

    B.load_link(first, doc, doc.ActiveView, settings(), host_root)
    cats = dict((c.label, c) for c in first.children)
    bench.check("a link lists its model categories",
                "OST_PipeCurves" in cats and "OST_Walls" in cats and
                "OST_DuctCurves" in cats)
    bench.check("a project's own category is left out and named",
                "BGL Custom" in first.note and "BGL Custom" not in cats)
    bench.equal("linked pipes split by service",
                [(c.label, c.count) for c in cats["OST_PipeCurves"].children],
                [("Domestic Cold Water", 1), ("Vent", 3)])
    bench.equal("linked ducts split by service",
                [c.label for c in cats["OST_DuctCurves"].children],
                ["Supply Air"])
    bench.equal("linked walls by family, then type",
                [(c.label, [t.label for t in c.children])
                 for c in cats["OST_Walls"].children],
                [("Basic Wall", ["100 Blockwork"]),
                 ("Curtain Wall", ["CW1"])])
    l_vent_row = cats["OST_PipeCurves"].find(("s", "vent"))
    bench.equal("a linked Vent row knows the host has 2 Vent pipes",
                l_vent_row.collateral, 2)
    bench.equal("cold water has none in the host",
                cats["OST_PipeCurves"].find(
                    ("s", "domestic cold water")).collateral, 0)
    bench.equal("the linked Walls category knows the host has 3 walls",
                cats["OST_Walls"].collateral, 3)
    l_100 = cats["OST_Walls"].find(("f", "basic wall")).find(
        ("t", "100 blockwork"))
    bench.equal("and a type row matches by name across the two models",
                l_100.collateral, 2)

    # what Hide will do
    B.set_checked(l_vent_row, True)
    B.set_checked(links_root.children[1], True)
    summary = B.summarise(host_root, links_root)
    bench.equal("one filter row", summary["filters"], [l_vent_row])
    bench.equal("one whole link", summary["whole_links"],
                [links_root.children[1]])
    bench.equal("collateral adds up", summary["collateral"], 2)
    bench.check("and it is not empty", not summary["empty"])

    late = FakeLink(FakeDoc([FakeElement("OST_Walls", {}, type_id=91)],
                            types=l_types, title="LATE"))
    doc_late = FakeDoc(host_elems, types=dict(types_), links=[late])
    late_root = B.build_links_root(doc_late, doc_late.ActiveView)
    B.set_checked(late_root.children[0], True)
    B.load_link(late_root.children[0], doc_late, doc_late.ActiveView,
                settings(), None)
    bench.check("a link ticked before it is opened opens fully ticked",
                all(n.checked for n in late_root.children[0].walk()))

    old_ctor = host_with_links(link_scoped=False)
    old_root = B.build_links_root(old_ctor, old_ctor.ActiveView)
    B.load_link(old_root.children[0], old_ctor, old_ctor.ActiveView,
                settings(), None)
    bench.check("without the view-scoped link collector the row says so",
                "whole link is listed" in old_root.children[0].note)

    # filter names and plans
    bench.equal("a filter is named for exactly what it hides",
                B.filter_name(l_vent_row.rule),
                "RevoBIM Temp Hide - OST_PipeCurves - Vent")
    bench.equal("and stripped of what Revit refuses",
                B.filter_name({"cat": 1, "cat_name": "Walls",
                               "family": "A:B", "type": "[x]"}),
                "RevoBIM Temp Hide - Walls - A_B - _x_")
    bench.equal("a linked pipe service filters on the built-in System Type",
                B.filter_plan(l_vent_row.rule, settings()),
                [("bip", "RBS_PIPING_SYSTEM_TYPE_PARAM", "equals", "Vent")])
    bench.equal("a shared service parameter the host also has is used "
                "instead",
                B.filter_plan(l_vent_row.rule,
                              settings(param_pipe="BGL_Service"),
                              lambda n: n == "BGL_Service"),
                [("shared", "BGL_Service", "equals", "Vent")])
    bench.equal("a blank service filters on has-no-value",
                B.filter_plan({"cat": 1, "cat_name": "P", "group": "pipe",
                               "value": ""}, settings()),
                [("bip", "RBS_PIPING_SYSTEM_TYPE_PARAM", "novalue", "")])
    bench.equal("a type row is family and type",
                [r[1] for r in B.filter_plan(l_100.rule, settings())],
                ["ALL_MODEL_FAMILY_NAME", "ALL_MODEL_TYPE_NAME"])
    bench.equal("a category row has no rules",
                B.filter_plan(cats["OST_Walls"].rule, settings()), [])

    # -- 18. hiding from the list ----------------------------------------------
    doc = host_with_links()
    host_root = B.build_host(doc, doc.ActiveView, settings())
    links_root = B.build_links_root(doc, doc.ActiveView)
    B.load_link(links_root.children[0], doc, doc.ActiveView, settings(),
                host_root)
    lcats = dict((c.label, c) for c in links_root.children[0].children)
    hp = [c for c in host_root.children if c.label == "OST_PipeCurves"][0]
    B.set_checked(hp.find(("s", "vent")), True)
    B.set_checked(lcats["OST_PipeCurves"].find(("s", "vent")), True)
    B.set_checked(lcats["OST_Walls"], True)
    B.set_checked(links_root.children[1], True)
    picked = B.summarise(host_root, links_root)
    uidoc = FakeUIDoc(doc, [])
    report = ist_core.hide_from_list(uidoc, settings(), picked)
    view = doc.ActiveView
    bench.equal("host rows are hidden by id, insulation with them, and the "
                "whole link as its instance",
                view.hidden, ids(h_vent) | ids(h_lag) | set([link_b.Id.Value]))
    bench.equal("each linked row becomes one filter",
                sorted(f.Name for f in doc.created),
                ["RevoBIM Temp Hide - OST_PipeCurves - Vent",
                 "RevoBIM Temp Hide - OST_Walls"])
    bench.check("on the view, switched off",
                len(view.filters) == 2 and
                not [v for v in view.filter_visible.values() if v])
    vent_filter = [f for f in doc.created if f.Name.endswith("Vent")][0]
    bench.equal("the Vent filter is pipes, System Type equals Vent",
                (vent_filter.cats, vent_filter.rules),
                ([BuiltInCategory.OST_PipeCurves],
                 [("equals", "BIP_PIPING_SYSTEM_TYPE", "Vent")]))
    bench.check("the walls filter has no rule", not [
        f for f in doc.created if f.Name.endswith("Walls")][0].rules)
    # 2 host Vent pipes + 1 lagging + 1 link instance, 3 linked Vent + 5 walls
    bench.equal("the report counts host and linked", report.count, 12)
    bench.check("and warns the filters also take 5 host elements",
                [n for n in report.notes if "also hide 5" in n])
    bench.check("with the lines in order", report.lines == [
        "This model: 3 elements hidden in Level 00 - Power. Reset Hide puts "
        "them back.",
        "1 whole link hidden.",
        "Linked models: 2 RevoBIM Temp filters on this view. Reset removes "
        "them."])

    report = ist_core.hide_from_list(uidoc, settings(hide_replaces="off"),
                                     picked)
    bench.equal("stacking a second run reuses the filters it made",
                len(doc.created), 2)
    bench.equal("and does not add them to the view twice",
                len(view.filters), 2)

    # filters that Revit will not take
    doc = host_with_links()
    doc.unfilterable.add(BuiltInCategory.OST_PipeCurves)
    host_root = B.build_host(doc, doc.ActiveView, settings())
    links_root = B.build_links_root(doc, doc.ActiveView)
    B.load_link(links_root.children[0], doc, doc.ActiveView, settings(),
                host_root)
    lcats = dict((c.label, c) for c in links_root.children[0].children)
    B.set_checked(lcats["OST_PipeCurves"].find(("s", "vent")), True)
    report = ist_core.hide_from_list(
        FakeUIDoc(doc, []), settings(hide_uncaptured="on"),
        B.summarise(host_root, links_root))
    bench.check("a row Revit will not filter is reported, even on quiet",
                [n for n in report.notes if n.startswith("Not filtered")])
    bench.check("and nothing was made for it", not doc.created)

    doc = host_with_links()
    doc.ActiveView.template_locked = True
    host_root = B.build_host(doc, doc.ActiveView, settings())
    links_root = B.build_links_root(doc, doc.ActiveView)
    B.load_link(links_root.children[0], doc, doc.ActiveView, settings(),
                host_root)
    B.set_checked(links_root.children[0].children[0], True)
    report = ist_core.hide_from_list(FakeUIDoc(doc, []), settings(),
                                     B.summarise(host_root, links_root))
    bench.check("a view whose template owns its filters says so",
                [n for n in report.notes if "template" in n])

    # reset
    doc = host_with_links()
    host_root = B.build_host(doc, doc.ActiveView, settings())
    links_root = B.build_links_root(doc, doc.ActiveView)
    B.load_link(links_root.children[0], doc, doc.ActiveView, settings(),
                host_root)
    lcats = dict((c.label, c) for c in links_root.children[0].children)
    B.set_checked(lcats["OST_Walls"], True)
    B.set_checked(lcats["OST_DuctCurves"], True)
    ist_core.hide_from_list(FakeUIDoc(doc, []), settings(),
                            B.summarise(host_root, links_root))
    other = FakeView()
    duct_id = [f for f in doc.created if f.Name.endswith("DuctCurves")][0].Id
    other.filters.append(duct_id)
    doc.views.append(other)
    mine = FakeFilter(doc, "Someone else's filter", [], None)
    doc.filters[mine.Id.Value] = mine
    doc.ActiveView.filters.append(mine.Id)
    bench.check("a view with tool filters needs a reset",
                ist_core.needs_reset(doc, doc.ActiveView))
    report = ist_core.hide_from_list(FakeUIDoc(doc, []), settings(),
                                     {"reset": True})
    bench.equal("reset takes only this tool's filters off the view",
                [f.Value for f in doc.ActiveView.filters], [mine.Id.Value])
    bench.check("deletes the ones nothing else uses",
                [f for f in doc.created if f.Name.endswith("Walls")][0]
                .Id.Value in doc.deleted)
    bench.check("keeps the one another view still uses",
                duct_id.Value not in doc.deleted)
    bench.check("and says how many it took off",
                [l for l in report.lines if "2 linked filters taken off" in l])

    view = FakeView()
    doc = FakeDoc(host_elems, view=view)
    report = ist_core.hide_from_list(FakeUIDoc(doc, []), settings(),
                                     B.summarise(B.build_host(doc, view,
                                                              settings()),
                                                 None))
    bench.check("Hide with nothing ticked does nothing and opens no window",
                report.cancelled and view.hidden is None)

    # the Isolate reset also clears tool filters
    doc = FakeDoc(host_elems)
    made = FakeFilter(doc, "RevoBIM Temp Hide - OST_Walls", [], None)
    doc.filters[made.Id.Value] = made
    doc.ActiveView.filters.append(made.Id)
    report = ist_core.isolate(FakeUIDoc(doc, [], picks=[]), settings())
    bench.check("Finish on nothing in Isolate clears tool filters too",
                report.reset and not doc.ActiveView.filters)

    # -- 19. the remembered hide ------------------------------------------------
    M = ist_memory

    def fresh_report():
        return ist_core.Report()

    def mem_doc(title):
        return FakeDoc(host_elems, types=dict(types_),
                       links=[link_a, link_b], title=title)

    doc = mem_doc("MEM-A")
    view = doc.ActiveView
    view.hidden_ids.add(h_vent[1].Id.Value)        # somebody hid this earlier
    report = ist_core.hide(FakeUIDoc(doc, [h_vent[0]]), settings())
    key = M.model_key(doc)
    entry = M.load(key)["views"][view.UniqueId]
    bench.check("Hide writes down what it hid",
                h_vent[0].Id.Value in entry["host"] and report.memory)
    bench.check("but not what was already hidden",
                h_vent[1].Id.Value not in entry["host"])
    bench.equal("and names the view", entry["name"], view.Name)

    # a new hide replaces the last one: the old is put back, the new recorded
    ist_core.hide(FakeUIDoc(doc, [h_soil[0]]), settings())
    entry = M.load(key)["views"][view.UniqueId]
    bench.equal("a second hide starts a new record",
                set(entry["host"]), ids(h_soil))
    bench.check("and puts the first one back",
                h_vent[0].Id.Value not in view.hidden_ids and
                h_vfit[0].Id.Value not in view.hidden_ids)
    bench.check("without touching somebody else's hide",
                h_vent[1].Id.Value in view.hidden_ids)

    # the bug the order guards against: hiding what is already hidden by the
    # last hide must still record it
    ist_core.hide(FakeUIDoc(doc, [h_soil[0]]), settings())
    bench.equal("re-hiding the same service still records it",
                set(M.load(key)["views"][view.UniqueId]["host"]),
                ids(h_soil))

    M.run_job(doc, "reset", view.UniqueId, settings(), fresh_report())
    bench.check("Reset Hide shows what the tool hid",
                h_soil[0].Id.Value not in view.hidden_ids)
    bench.check("and leaves somebody else's hide alone",
                h_vent[1].Id.Value in view.hidden_ids)
    bench.equal("the record says shown",
                M.load(key)["views"][view.UniqueId]["state"], M.SHOWN)
    bench.check("so the view no longer needs a reset",
                not ist_core.needs_reset(doc, view))

    M.run_job(doc, "redo", view.UniqueId, settings(), fresh_report())
    bench.check("Hide again hides the same elements",
                h_soil[0].Id.Value in view.hidden_ids and
                h_vent[0].Id.Value not in view.hidden_ids)
    bench.equal("the record says hidden",
                M.load(key)["views"][view.UniqueId]["state"], M.HIDDEN)
    bench.check("and the view needs a reset again",
                ist_core.needs_reset(doc, view))

    # stacking is still there as a setting
    doc = mem_doc("MEM-STACK")
    view = doc.ActiveView
    key = M.model_key(doc)
    stack = settings(hide_replaces="off")
    ist_core.hide(FakeUIDoc(doc, [h_vent[0]]), stack)
    ist_core.hide(FakeUIDoc(doc, [h_soil[0]]), stack)
    bench.equal("with replace off, a second hide adds to the first, and the "
                "memory is on disk",
                set(M.load(key)["views"][view.UniqueId]["host"]),
                ids(h_vent + h_soil + h_vfit + h_lag))

    other = mem_doc("MEM-B")
    bench.check("each model has its own memory",
                M.memory_path(M.model_key(other)) != M.memory_path(key) and
                not M.load(M.model_key(other))["views"])

    # the list: links and filters are remembered too
    doc = mem_doc("MEM-LIST")
    view = doc.ActiveView
    host_root = B.build_host(doc, view, settings())
    links_root = B.build_links_root(doc, view)
    B.load_link(links_root.children[0], doc, view, settings(), host_root)
    lcats = dict((c.label, c) for c in links_root.children[0].children)
    B.set_checked(lcats["OST_PipeCurves"].find(("s", "vent")), True)
    B.set_checked(links_root.children[1], True)
    ist_core.hide_from_list(FakeUIDoc(doc, []), settings(),
                            B.summarise(host_root, links_root))
    key = M.model_key(doc)
    entry = M.load(key)["views"][view.UniqueId]
    vent_name = "RevoBIM Temp Hide - OST_PipeCurves - Vent"
    bench.equal("a whole link is remembered as a link",
                entry["links"], [link_b.Id.Value])
    bench.equal("a linked row is remembered as its filter and rules",
                (list(entry["filters"].keys()),
                 entry["filters"][vent_name]["plan"]),
                ([vent_name],
                 [["bip", "RBS_PIPING_SYSTEM_TYPE_PARAM", "equals", "Vent"]]))

    M.run_job(doc, "reset", view.UniqueId, settings(), fresh_report())
    bench.check("Reset shows the link and takes the filter off",
                link_b.Id.Value not in view.hidden_ids and not view.filters)
    bench.check("leaving no orphan filter in the project",
                vent_name not in [f.Name for f in doc.filters.values()])

    report = fresh_report()
    M.run_job(doc, "redo", view.UniqueId, settings(), report)
    remade = [f for f in doc.filters.values() if f.Name == vent_name]
    bench.check("Hide again remakes the filter from its rules",
                remade and remade[0].rules ==
                [("equals", "BIP_PIPING_SYSTEM_TYPE", "Vent")] and
                remade[0].cats == [BuiltInCategory.OST_PipeCurves])
    bench.check("puts it on the view switched off, and hides the link",
                [f.Value for f in view.filters] == [remade[0].Id.Value] and
                view.filter_visible[remade[0].Id.Value] is False and
                link_b.Id.Value in view.hidden_ids)

    # the tool's other resets put the memory back too
    report = ist_core.hide_from_list(FakeUIDoc(doc, []), settings(),
                                     {"reset": True})
    bench.check("the list's Reset view puts the remembered hide back",
                report.reset and link_b.Id.Value not in view.hidden_ids and
                not view.filters)
    bench.equal("and the file agrees",
                M.load(key)["views"][view.UniqueId]["state"], M.SHOWN)

    # forget, reset all, a deleted view
    M.run_job(doc, "redo", view.UniqueId, settings(), fresh_report())
    second = FakeView()
    doc.views.append(second)
    second.hidden_ids.add(h_door[0].Id.Value)
    M.remember(doc, second, host=[h_door[0].Id.Value])
    M.run_job(doc, "reset_all", None, settings(), fresh_report())
    bench.check("Reset all puts back every remembered view",
                link_b.Id.Value not in view.hidden_ids and
                h_door[0].Id.Value not in second.hidden_ids)

    M.run_job(doc, "redo", view.UniqueId, settings(), fresh_report())
    report = fresh_report()
    M.run_job(doc, "forget", view.UniqueId, settings(), report)
    bench.check("Forget resets a hidden view first",
                link_b.Id.Value not in view.hidden_ids)
    bench.check("then drops it from memory",
                view.UniqueId not in M.load(key)["views"])
    bench.equal("the most recent view moves to the next one",
                M.load(key)["last"], second.UniqueId)

    doc.views.remove(second)
    report = fresh_report()
    M.run_job(doc, "reset", second.UniqueId, settings(), report)
    bench.check("a view deleted since is forgotten and said",
                second.UniqueId not in M.load(key)["views"] and
                [n for n in report.notes if "no longer in the model" in n])

    # temporary mode keeps the old reset by prefix
    doc = mem_doc("MEM-TEMP")
    view = doc.ActiveView
    host_root = B.build_host(doc, view, settings())
    links_root = B.build_links_root(doc, view)
    B.load_link(links_root.children[0], doc, view, settings(), host_root)
    B.set_checked(links_root.children[0].children[0], True)
    report = ist_core.hide_from_list(FakeUIDoc(doc, []),
                                     settings(hide_mode="temporary"),
                                     B.summarise(host_root, links_root))
    bench.check("temporary mode writes no memory",
                not report.memory and
                not M.load(M.model_key(doc))["views"])
    report = ist_core.hide_from_list(FakeUIDoc(doc, []), settings(),
                                     {"reset": True})
    bench.check("and its filters still go by name on reset",
                not view.filters and
                [l for l in report.lines if "linked-model filter" in l])

    # every migration newer than the file
    bench.equal("a version 1 file gets version 2 and 3's resets",
                ist_core.migration_keys("1"),
                ["param_duct", "param_pipe", "blank_value", "hide_mode"])
    bench.equal("a version 2 file gets version 3's only",
                ist_core.migration_keys("2"), ["hide_mode"])
    bench.equal("a current file gets none",
                ist_core.migration_keys(ist_core.SETTINGS_VERSION), [])

    # -- 20. hide selection templates ------------------------------------------
    T = ist_templates
    link_arch = FakeLink(FakeDoc([], title="BGL_ARCH"))
    doc = FakeDoc(host_elems, types=dict(types_),
                  links=[link_a, link_arch], title="TPL-A")
    view = doc.ActiveView
    host_root = B.build_host(doc, view, settings())
    links_root = B.build_links_root(doc, view)
    B.load_link(links_root.children[0], doc, view, settings(), host_root)
    hp = [c for c in host_root.children if c.label == "OST_PipeCurves"][0]
    hw = [c for c in host_root.children if c.label == "OST_Walls"][0]
    lcats = dict((c.label, c) for c in links_root.children[0].children)
    B.set_checked(hp.find(("s", "vent")), True)
    B.set_checked(hw.find(("f", "basic wall")).find(("t", "100 blockwork")),
                  True)
    B.set_checked(lcats["OST_Walls"], True)
    B.set_checked(links_root.children[1], True)
    rows = T.rows_from(host_root, links_root)
    bench.equal("a template names what is ticked, not element ids",
                sorted((r["source"], r["kind"], r.get("value") or
                        r.get("type") or r.get("cat_name") or "")
                       for r in rows),
                sorted([("host", "service", "Vent"),
                        ("host", "type", "100 Blockwork"),
                        ("BGL_MECH", "category", "OST_Walls"),
                        ("BGL_ARCH", "source", "")]))
    bench.check("and keeps no ids at all",
                not [r for r in rows for k in r if k in ("ids", "link_id")])

    bench.check("it saves", T.put("Coordination", rows))
    bench.equal("and lists", T.names(), ["Coordination"])
    T.set_last("Coordination")
    bench.equal("the last one used is remembered", T.last_name(),
                "Coordination")
    T.set_last("No such template")
    bench.check("a name that is not a template is not remembered",
                T.last_name() is None)
    T.set_last("Coordination")

    # a different model, different ids, the same names
    h2_vent = [FakeElement("OST_PipeCurves", {"System Type": "Vent"})]
    h2_wall = [FakeElement("OST_Walls", {}, type_id=81)]
    h2_soil = [FakeElement("OST_PipeCurves", {"System Type": "Soil"})]
    link_c = FakeLink(link_doc)
    link_d = FakeLink(link_doc)
    doc2 = FakeDoc(h2_vent + h2_wall + h2_soil, types=dict(types_),
                   links=[link_c, link_d], title="TPL-B")
    view2 = doc2.ActiveView
    root2 = B.build_host(doc2, view2, settings())
    links2 = B.build_links_root(doc2, view2)
    loaded = []

    def loader(node):
        loaded.append(node.label)
        B.load_link(node, doc2, view2, settings(), root2)

    ticked, missing = T.apply_rows(root2, links2, rows, settings(), loader)
    s2 = B.summarise(root2, links2)
    bench.equal("applied to another model, it ticks the same names",
                s2["host_ids"], ids(h2_vent + h2_wall))
    bench.check("leaving the rest alone",
                h2_soil[0].Id.Value not in s2["host_ids"])
    bench.equal("a link it reaches into is read for it, every instance of it",
                sorted(loaded), ["BGL_MECH", "BGL_MECH (2)"])
    bench.equal("both instances get the walls filter row",
                len([n for n in s2["filters"]
                     if n.rule.get("cat_name") == "OST_Walls"]), 2)
    bench.equal("a whole-link row for a link not in this view is missing",
                [(m["source"], m["kind"]) for m in missing],
                [("BGL_ARCH", "source")])

    # applying again starts from clean
    B.set_checked(root2.find(BuiltInCategory.OST_PipeCurves), True)
    T.apply_rows(root2, links2, rows, settings(), loader)
    bench.check("applying a template clears hand ticks first",
                h2_soil[0].Id.Value not in
                B.summarise(root2, links2)["host_ids"])

    # one click: hide the last template with no window
    summary, missing, error = T.plan_from_template(doc2, view2, settings(),
                                                   "Coordination")
    bench.check("plan_from_template needs no window",
                error is None and summary["template"] == "Coordination")
    report = ist_core.hide_from_list(FakeUIDoc(doc2, []), settings(), summary)
    entry = M.load(M.model_key(doc2))["views"][view2.UniqueId]
    bench.equal("the remembered hide knows its template",
                entry["template"], "Coordination")
    bench.check("and hid this model's own elements for it",
                ids(h2_vent + h2_wall) <= view2.hidden_ids)
    _, _, error = T.plan_from_template(doc2, view2, settings(), "Nope")
    bench.check("an unknown template is refused, not guessed",
                error and "Nope" in error)

    bench.equal("a row reads back in words",
                T.describe_row({"source": "host", "kind": "service",
                                "cat_name": "Pipes", "value": "Vent"}),
                "this model > Pipes > Vent")

    T.remove("Coordination")
    bench.check("deleting the last template forgets it as last",
                T.names() == [] and T.last_name() is None)

    # -- 15. settings round trip --------------------------------------------
    folder = tempfile.mkdtemp(prefix="ist_bench_")
    original_dir, original_path = ist_core.SETTINGS_DIR, ist_core.SETTINGS_PATH
    ist_core.SETTINGS_DIR = folder
    ist_core.SETTINGS_PATH = os.path.join(folder, "isolate_service_type.txt")
    try:
        bench.check("a missing file falls back to the defaults",
                    ist_core.load_settings() == ist_core.DEFAULTS)
        saved = settings(param_pipe="BGL_Service", match_case="on")
        bench.check("it writes", ist_core.save_settings(saved))
        back = ist_core.load_settings()
        bench.equal("and reads back", back["param_pipe"], "BGL_Service")
        bench.equal("every key survives", back["match_case"], "on")

        handle = open(ist_core.SETTINGS_PATH, "a")
        handle.write("something_from_a_later_version=42\n")
        handle.write("this line has no equals sign\n")
        handle.close()
        back = ist_core.load_settings()
        bench.check("an unknown key is ignored rather than breaking the load",
                    "something_from_a_later_version" not in back)
        bench.equal("and the rest still reads", back["param_pipe"],
                    "BGL_Service")
    finally:
        ist_core.SETTINGS_DIR, ist_core.SETTINGS_PATH = \
            original_dir, original_path

    # -- 16. settings helpers ------------------------------------------------
    bench.equal("cats_of drops anything not offered for that group",
                ist_core.cats_of(settings(cats_tray="OST_CableTray,OST_Sprinklers"),
                                 "tray"),
                ["OST_CableTray"])
    bench.equal("param_of falls back to the discipline's default",
                ist_core.param_of(settings(param_duct="  "), "duct"),
                "System Type")
    bench.equal("which for tray is Service Type",
                ist_core.param_of(settings(param_tray=""), "tray"),
                "Service Type")
    bench.equal("normalise trims and folds case",
                ist_core.normalise("  Small Power ", False), "small power")
    bench.equal("and leaves case alone when asked",
                ist_core.normalise("  Small Power ", True), "Small Power")
    bench.equal("groups_for_category can answer twice",
                ist_core.groups_for_category(
                    "OST_MechanicalEquipment",
                    {"duct": ["OST_MechanicalEquipment"],
                     "pipe": ["OST_MechanicalEquipment"],
                     "tray": [], "conduit": []}),
                ["duct", "pipe"])

    # -- 17. every default category exists on this release -------------------
    known = ist_core.category_ids()
    for group in ist_core.GROUP_KEYS:
        for cat_name in ist_core.DEFAULT_CATS[group]:
            bench.check(
                "{0} is a real category".format(cat_name),
                getattr(BuiltInCategory, cat_name, None) is not None)
    bench.check("category_ids covers the defaults", len(known) >= 17)


def main():
    bench = Bench()
    run(bench)
    for name, detail in bench.failed:
        sys.stdout.write("FAIL  {0}  {1}\n".format(name, detail))
    total = bench.passed + len(bench.failed)
    sys.stdout.write("bench_logic: {0} of {1} checks pass\n".format(
        bench.passed, total))
    return 1 if bench.failed else 0


def selftest():
    """Break the rules on purpose and confirm the bench notices."""
    results = []

    def try_break(label, patch, restore):
        patch()
        try:
            bench = Bench()
            try:
                run(bench)
            except Exception:
                bench.failed.append((label, "raised"))
            results.append((label, bool(bench.failed)))
        finally:
            restore()

    original = ist_core.DEFAULTS["blank_value"]

    def patch_blank():
        ist_core.DEFAULTS["blank_value"] = "group"

    def restore_blank():
        ist_core.DEFAULTS["blank_value"] = original

    try_break("the blank rule default", patch_blank, restore_blank)

    original_cats = ist_core.DEFAULT_CATS["tray"]
    saved_choices = ist_core.GROUP_CHOICES["tray"]

    def patch_cats():
        ist_core.DEFAULTS["cats_tray"] = "OST_CableTray"

    def restore_cats():
        ist_core.DEFAULTS["cats_tray"] = ",".join(original_cats)
        ist_core.GROUP_CHOICES["tray"] = saved_choices

    try_break("fittings travelling with the tray", patch_cats, restore_cats)

    original_insulation = ist_core.DEFAULTS["include_insulation"]

    def patch_insulation():
        ist_core.DEFAULTS["include_insulation"] = "off"

    def restore_insulation():
        ist_core.DEFAULTS["include_insulation"] = original_insulation

    try_break("insulation travelling with its host", patch_insulation,
              restore_insulation)

    original_reset = ist_core.DEFAULTS["empty_selection_resets"]

    def patch_reset():
        ist_core.DEFAULTS["empty_selection_resets"] = "off"

    def restore_reset():
        ist_core.DEFAULTS["empty_selection_resets"] = original_reset

    try_break("the empty selection toggle", patch_reset, restore_reset)

    original_other = ist_core.DEFAULTS["other_scope"]

    def patch_other():
        ist_core.DEFAULTS["other_scope"] = "family"

    def restore_other():
        ist_core.DEFAULTS["other_scope"] = original_other

    try_break("the other-category scope default", patch_other, restore_other)

    original_quiet = ist_core.DEFAULTS["hide_uncaptured"]

    def patch_quiet():
        ist_core.DEFAULTS["hide_uncaptured"] = "on"

    def restore_quiet():
        ist_core.DEFAULTS["hide_uncaptured"] = original_quiet

    try_break("reporting what was left out", patch_quiet, restore_quiet)

    original_mode = ist_core.DEFAULTS["hide_mode"]

    def patch_mode():
        ist_core.DEFAULTS["hide_mode"] = "permanent"

    def restore_mode():
        ist_core.DEFAULTS["hide_mode"] = original_mode

    try_break("Hide being temporary by default", patch_mode, restore_mode)

    original_pipe = ist_core.DEFAULTS["param_pipe"]

    def patch_pipe():
        ist_core.DEFAULTS["param_pipe"] = "Service Type"
        ist_core.DEFAULTS["fallback_builtin"] = "off"

    def restore_pipe():
        ist_core.DEFAULTS["param_pipe"] = original_pipe
        ist_core.DEFAULTS["fallback_builtin"] = "on"

    try_break("pipes read by System Type", patch_pipe, restore_pipe)

    original_nothing = ist_core.DEFAULTS["nothing_selected"]

    def patch_nothing():
        ist_core.DEFAULTS["nothing_selected"] = "reset"

    def restore_nothing():
        ist_core.DEFAULTS["nothing_selected"] = original_nothing

    try_break("pick when nothing is selected", patch_nothing, restore_nothing)

    real_lookup = ist_browse.host_lookup

    def patch_lookup():
        ist_browse.host_lookup = lambda *args, **kwargs: 0

    def restore_lookup():
        ist_browse.host_lookup = real_lookup

    try_break("counting what a link filter also hides here", patch_lookup,
              restore_lookup)

    real_prefix = ist_core.TEMP_FILTER_PREFIX

    def patch_prefix():
        ist_core.TEMP_FILTER_PREFIX = ""

    def restore_prefix():
        ist_core.TEMP_FILTER_PREFIX = real_prefix

    try_break("reset touching only this tool's filters", patch_prefix,
              restore_prefix)

    real_fresh = ist_core._not_yet_hidden

    def patch_fresh():
        ist_core._not_yet_hidden = lambda doc, view, ids: set(ids)

    def restore_fresh():
        ist_core._not_yet_hidden = real_fresh

    try_break("Reset Hide leaving other people's hides alone", patch_fresh,
              restore_fresh)

    real_keys = ist_core.migration_keys

    def patch_keys():
        ist_core.migration_keys = lambda stored: list(
            ist_core.MIGRATIONS.get(ist_core.SETTINGS_VERSION, []))

    def restore_keys():
        ist_core.migration_keys = real_keys

    try_break("every migration newer than the file", patch_keys, restore_keys)

    real_replace = ist_core._begin_replace

    def patch_replace():
        ist_core._begin_replace = lambda *args: None

    def restore_replace():
        ist_core._begin_replace = real_replace

    try_break("a new hide putting the last one back", patch_replace,
              restore_replace)

    real_title = ist_templates.link_title

    def patch_title():
        ist_templates.link_title = lambda node: node.label

    def restore_title():
        ist_templates.link_title = real_title

    try_break("a template reaching every instance of a link", patch_title,
              restore_title)

    bad = 0
    for label, noticed in results:
        if noticed:
            sys.stdout.write("  noticed  {0}\n".format(label))
        else:
            bad += 1
            sys.stdout.write("  MISSED   {0}\n".format(label))
    sys.stdout.write("{0} of {1} deliberate breakages noticed\n".format(
        len(results) - bad, len(results)))
    return 1 if bad else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    sys.exit(main())
