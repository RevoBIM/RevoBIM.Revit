# -*- coding: utf-8 -*-
u"""RevoBIM PY - Isolate Service Type : shared core.

Version, settings, the category groups, the service-type read and the isolate
routine itself.  Both buttons in the pulldown import this module.
"""

import ist_clr  # noqa: F401  - assemblies first, always

import os
import codecs

from Autodesk.Revit.DB import (
    BuiltInCategory,
    ElementId,
    ElementMulticategoryFilter,
    FilteredElementCollector,
    StorageType,
    TemporaryViewMode,
    Transaction,
)
from System.Collections.Generic import List as NetList

__version__ = u"1.7.0"

TOOL_NAME = u"Isolate Service Type"
RIBBON_NAME = u"RevoBIM Isolate Service Type"
HIDE_RIBBON_NAME = u"RevoBIM Hide Service Type"
RESET_RIBBON_NAME = u"RevoBIM Reset Hide"

# Every view filter this tool makes starts with this, and the reset removes
# exactly these and nothing else.
TEMP_FILTER_PREFIX = u"RevoBIM Temp Hide"

SETTINGS_DIR = os.path.join(os.getenv(u"APPDATA") or u"", u"RevoBIM")
SETTINGS_PATH = os.path.join(SETTINGS_DIR, u"isolate_service_type.txt")

SETTINGS_VERSION = u"3"

# Keys reset when the file was written by an older version.  Nothing to reset
# yet; the dict exists so the next change has somewhere to go.
MIGRATIONS = {
    # 1.4.0: pipes and ducts carry the service in System Type, not Service
    # Type, and a blank value no longer widens to the whole group.  Reset the
    # keys whose old defaults caused "hid all pipes".
    u"2": [u"param_duct", u"param_pipe", u"blank_value"],
    # 1.6.0: Hide remembers what it hid and the floating Reset Hide window
    # puts it back.  Settings files carry hide_mode=temporary from the old
    # default, which would keep the new behaviour from ever running.
    u"3": [u"hide_mode"],
}


# ===========================================================================
# categories and groups
# ===========================================================================

# BuiltInCategory members are looked up late, inside a function, never at
# module load - one less thing that can die before the tool runs.

CATEGORY_LABELS = [
    (u"OST_CableTray", u"Cable Trays"),
    (u"OST_CableTrayFitting", u"Cable Tray Fittings"),
    (u"OST_Conduit", u"Conduits"),
    (u"OST_ConduitFitting", u"Conduit Fittings"),
    (u"OST_DuctCurves", u"Ducts"),
    (u"OST_FlexDuctCurves", u"Flex Ducts"),
    (u"OST_DuctFitting", u"Duct Fittings"),
    (u"OST_DuctAccessory", u"Duct Accessories"),
    (u"OST_DuctTerminal", u"Air Terminals"),
    (u"OST_MechanicalEquipment", u"Mechanical Equipment"),
    (u"OST_FabricationDuctwork", u"Fabrication Ductwork"),
    (u"OST_PipeCurves", u"Pipes"),
    (u"OST_FlexPipeCurves", u"Flex Pipes"),
    (u"OST_PipeFitting", u"Pipe Fittings"),
    (u"OST_PipeAccessory", u"Pipe Accessories"),
    (u"OST_PlumbingFixtures", u"Plumbing Fixtures"),
    (u"OST_PlumbingEquipment", u"Plumbing Equipment"),
    (u"OST_Sprinklers", u"Sprinklers"),
    (u"OST_FabricationPipework", u"Fabrication Pipework"),
]

LABEL_OF = dict(CATEGORY_LABELS)

GROUPS = [
    (u"tray", u"Cable tray"),
    (u"conduit", u"Conduit"),
    (u"duct", u"Duct"),
    (u"pipe", u"Pipe"),
]

GROUP_KEYS = [g[0] for g in GROUPS]
GROUP_LABEL = dict(GROUPS)

# What each group is allowed to hold, in the order it is offered in Settings.
GROUP_CHOICES = {
    u"tray": [u"OST_CableTray", u"OST_CableTrayFitting"],
    u"conduit": [u"OST_Conduit", u"OST_ConduitFitting"],
    u"duct": [
        u"OST_DuctCurves", u"OST_FlexDuctCurves", u"OST_DuctFitting",
        u"OST_DuctAccessory", u"OST_DuctTerminal", u"OST_MechanicalEquipment",
        u"OST_FabricationDuctwork",
    ],
    u"pipe": [
        u"OST_PipeCurves", u"OST_FlexPipeCurves", u"OST_PipeFitting",
        u"OST_PipeAccessory", u"OST_PlumbingFixtures", u"OST_PlumbingEquipment",
        u"OST_Sprinklers", u"OST_MechanicalEquipment",
        u"OST_FabricationPipework",
    ],
}

# What is ticked out of the box.
DEFAULT_CATS = {
    u"tray": [u"OST_CableTray", u"OST_CableTrayFitting"],
    u"conduit": [u"OST_Conduit", u"OST_ConduitFitting"],
    u"duct": [
        u"OST_DuctCurves", u"OST_FlexDuctCurves", u"OST_DuctFitting",
        u"OST_DuctAccessory", u"OST_DuctTerminal", u"OST_MechanicalEquipment",
    ],
    u"pipe": [
        u"OST_PipeCurves", u"OST_FlexPipeCurves", u"OST_PipeFitting",
        u"OST_PipeAccessory", u"OST_PlumbingFixtures", u"OST_PlumbingEquipment",
        u"OST_Sprinklers",
    ],
}

INSULATION_CATS = [
    u"OST_PipeInsulations",
    u"OST_DuctInsulations",
    u"OST_DuctLinings",
]

DEFAULT_PARAM = u"Service Type"

# The parameter that names the service, per discipline, out of the box.  Cable
# tray and conduit have a real Service Type; pipes and ducts put the service in
# System Type.
DEFAULT_PARAMS = {
    u"tray": u"Service Type",
    u"conduit": u"Service Type",
    u"duct": u"System Type",
    u"pipe": u"System Type",
}

# Revit's own parameter for the same thing, tried after the configured name
# when that comes back blank.  Built-ins answer in every Revit language, where
# the name "System Type" only answers in English.
SERVICE_BIPS = {
    u"tray": (u"RBS_CTC_SERVICE_TYPE", u"RBS_CABLETRAY_SERVICE_TYPE_PARAM"),
    u"conduit": (u"RBS_CTC_SERVICE_TYPE",),
    u"duct": (u"RBS_DUCT_SYSTEM_TYPE_PARAM",),
    u"pipe": (u"RBS_PIPING_SYSTEM_TYPE_PARAM",),
}


DEFAULTS = {
    u"settings_version": SETTINGS_VERSION,
    u"param_tray": DEFAULT_PARAMS[u"tray"],
    u"param_conduit": DEFAULT_PARAMS[u"conduit"],
    u"param_duct": DEFAULT_PARAMS[u"duct"],
    u"param_pipe": DEFAULT_PARAMS[u"pipe"],
    u"cats_tray": u",".join(DEFAULT_CATS[u"tray"]),
    u"cats_conduit": u",".join(DEFAULT_CATS[u"conduit"]),
    u"cats_duct": u",".join(DEFAULT_CATS[u"duct"]),
    u"cats_pipe": u",".join(DEFAULT_CATS[u"pipe"]),
    u"match_case": u"off",
    u"blank_value": u"skip",       # skip | blank | group
    u"fallback_builtin": u"on",
    u"nothing_selected": u"pick",  # pick | reset
    u"hide_browse": u"on",         # Hide with nothing selected opens the list
    u"hide_replaces": u"on",       # a new hide puts the view's last one back
    u"template_run": u"apply",     # apply | list: what the last template does
    u"reset_left": u"",            # where the Reset Hide window was left
    u"reset_top": u"",
    u"other_scope": u"category",   # category | family | type | ignore
    u"include_insulation": u"on",
    u"hide_uncaptured": u"off",
    u"hide_mode": u"memory",       # memory | temporary | permanent
    u"include_selection": u"on",
    u"empty_selection_resets": u"on",
    u"show_results": u"needed",    # needed | always | never
    u"theme": u"dark",
}


# ===========================================================================
# settings
# ===========================================================================

def _ensure_dir():
    try:
        if SETTINGS_DIR and not os.path.isdir(SETTINGS_DIR):
            os.makedirs(SETTINGS_DIR)
    except Exception:
        pass


def load_settings():
    u"""Plain key=value text.  A missing or damaged file falls back to the
    defaults key by key; keys from an older version are ignored rather than
    breaking the load."""
    values = dict(DEFAULTS)
    try:
        if os.path.isfile(SETTINGS_PATH):
            handle = codecs.open(SETTINGS_PATH, u"r", u"utf-8")
            try:
                lines = handle.read().splitlines()
            finally:
                handle.close()
            for line in lines:
                line = line.strip()
                if not line or line.startswith(u"#") or u"=" not in line:
                    continue
                key, _, raw = line.partition(u"=")
                key = key.strip()
                if key in DEFAULTS:
                    values[key] = raw.strip()
    except Exception:
        return dict(DEFAULTS)

    stored = values.get(u"settings_version", u"")
    if stored != SETTINGS_VERSION:
        for key in migration_keys(stored):
            values[key] = DEFAULTS[key]
        values[u"settings_version"] = SETTINGS_VERSION
    return values


def _version_number(text):
    try:
        return int(u"{0}".format(text).strip())
    except Exception:
        return 0


def migration_keys(stored):
    u"""Every key reset by every migration newer than the file - not just the
    latest one.  A file written by 1.3.0 (version 1) opened by 1.6.0
    (version 3) needs version 2's reset as well as version 3's; taking only
    the latest left pipes on Service Type."""
    have = _version_number(stored)
    keys = []
    for version in sorted(MIGRATIONS.keys(), key=_version_number):
        if _version_number(version) > have:
            for key in MIGRATIONS[version]:
                if key not in keys:
                    keys.append(key)
    return keys


def save_settings(values):
    _ensure_dir()
    merged = dict(DEFAULTS)
    for key in DEFAULTS:
        if key in values and values[key] is not None:
            merged[key] = u"{0}".format(values[key])
    merged[u"settings_version"] = SETTINGS_VERSION
    try:
        handle = codecs.open(SETTINGS_PATH, u"w", u"utf-8")
        try:
            for key in sorted(merged.keys()):
                handle.write(u"{0}={1}\n".format(key, merged[key]))
        finally:
            handle.close()
        return True
    except Exception:
        return False


def is_on(values, key):
    return u"{0}".format(values.get(key, u"")).strip().lower() in (
        u"on", u"true", u"yes", u"1")


def cats_of(values, group):
    raw = values.get(u"cats_" + group, u"") or u""
    allowed = GROUP_CHOICES.get(group, [])
    picked = [c.strip() for c in raw.split(u",") if c.strip()]
    return [c for c in picked if c in allowed]


def param_of(values, group):
    name = (values.get(u"param_" + group, u"") or u"").strip()
    return name or DEFAULT_PARAMS.get(group, DEFAULT_PARAM)


# ===========================================================================
# small helpers
# ===========================================================================

def eid_value(element_id):
    u"""ElementId.IntegerValue was removed in Revit 2026; .Value (Int64) is the
    replacement, deprecated-in-2024 the other way round.  Never touch either
    directly."""
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


def bic(name):
    u"""A BuiltInCategory member by name, or None where the release has no such
    member.  Looked up at call time, never at module load."""
    return getattr(BuiltInCategory, name, None)


def category_ids():
    u"""{integer category id: OST_ name} for every category the tool knows,
    skipping any the running release does not have."""
    out = {}
    for name, _label in CATEGORY_LABELS:
        member = bic(name)
        if member is None:
            continue
        try:
            out[int(member)] = name
        except Exception:
            continue
    return out


def normalise(value, case_sensitive):
    if value is None:
        return u""
    text = u"{0}".format(value).strip()
    if not case_sensitive:
        text = text.lower()
    return text


# ===========================================================================
# reading the service type
# ===========================================================================

class ValueReader(object):
    u"""Reads the service off an element: the configured parameter first, then
    Revit's own built-in for the discipline.  The first non-blank answer wins.

    A parameter that exists but is empty is blank, not an answer - an empty
    shared "Service Type" on a pipe must not hide the System Type behind it.
    That was the 1.3.0 "hid all pipes" bug.

    Each route looks at the instance, then the type, and type answers are
    cached by type id, so the same pipe type hit five thousand times is read
    once.
    """

    def __init__(self, doc, name, group, fallback=True):
        self.doc = doc
        self.name = name
        self.group = group
        self.bips = []
        if fallback:
            self._resolve_bips()
        self._type_cache = {}

    def _resolve_bips(self):
        from Autodesk.Revit.DB import BuiltInParameter
        for bip_name in SERVICE_BIPS.get(self.group, ()):
            member = getattr(BuiltInParameter, bip_name, None)
            if member is not None:
                self.bips.append(member)

    # -- routes ------------------------------------------------------------
    def _named(self, host):
        u"""GetParameters first: LookupParameter collides with Revit's own
        read-only Category parameter, and a family can carry two parameters of
        the same name - so take the first one that has a value."""
        try:
            found = host.GetParameters(self.name)
        except Exception:
            found = None
        if found:
            for prm in found:
                value = self._read(prm)
                if value:
                    return value
            return None
        try:
            return self._read(host.LookupParameter(self.name))
        except Exception:
            return None

    def _builtin(self, host):
        for bip in self.bips:
            try:
                value = self._read(host.get_Parameter(bip))
            except Exception:
                value = None
            if value:
                return value
        return None

    @staticmethod
    def _read(prm):
        u"""Text for a string, the element's name for an ElementId (System
        Type is one), the displayed value for anything else.  Blank comes back
        as None, never as an empty string."""
        if prm is None:
            return None
        try:
            if not prm.HasValue:
                return None
        except Exception:
            pass
        try:
            if prm.StorageType == StorageType.String:
                text = prm.AsString()
            else:
                text = prm.AsValueString()
                if not text:
                    text = prm.AsString()
        except Exception:
            return None
        if text is None:
            return None
        text = u"{0}".format(text).strip()
        return text or None

    def _type_answer(self, element):
        try:
            type_id = element.GetTypeId()
        except Exception:
            return (None, None)
        key = eid_value(type_id)
        if key in self._type_cache:
            return self._type_cache[key]
        named = built = None
        try:
            symbol = self.doc.GetElement(type_id)
        except Exception:
            symbol = None
        if symbol is not None:
            named = self._named(symbol)
            built = self._builtin(symbol)
        self._type_cache[key] = (named, built)
        return (named, built)

    # -- public ------------------------------------------------------------
    def value(self, element):
        value = self._named(element)
        if value:
            return value
        named_type, built_type = self._type_answer(element)
        if named_type:
            return named_type
        value = self._builtin(element)
        if value:
            return value
        return built_type


def family_name_of(doc, element, cache):
    u"""The family an element belongs to.  `ElementType.FamilyName` answers for
    a loadable family and for a system family alike; the type name stands in
    where it does not."""
    try:
        type_id = element.GetTypeId()
    except Exception:
        return u""
    key = eid_value(type_id)
    if key in cache:
        return cache[key]
    name = u""
    try:
        symbol = doc.GetElement(type_id)
    except Exception:
        symbol = None
    if symbol is not None:
        for route in (u"FamilyName", u"Name"):
            try:
                value = getattr(symbol, route, None)
                if value:
                    name = u"{0}".format(value)
                    break
            except Exception:
                continue
    cache[key] = name
    return name


def elements_in_category(doc, view, cat_id, cat_int):
    u"""Everything of one category drawn in the view.

    `OfCategoryId` keeps it to one indexed pass.  Where a release will not take
    it, the whole view is walked once and filtered by category id instead -
    slower, but it still answers."""
    try:
        collector = FilteredElementCollector(doc, view.Id)\
            .OfCategoryId(cat_id).WhereElementIsNotElementType()
        return list(collector)
    except Exception:
        pass
    out = []
    try:
        collector = FilteredElementCollector(doc, view.Id)\
            .WhereElementIsNotElementType()
        for element in collector:
            try:
                category = element.Category
            except Exception:
                continue
            if category is not None and eid_value(category.Id) == cat_int:
                out.append(element)
    except Exception:
        return []
    return out


def parameter_names_for(doc, cat_names, sample=40):
    u"""Parameter names actually available on the given categories, for the
    Settings dropdowns.  Reads a sample of instances and their types rather
    than the whole model, so opening Settings is instant on a big job."""
    names = set()
    for cat_name in cat_names:
        member = bic(cat_name)
        if member is None:
            continue
        try:
            collector = FilteredElementCollector(doc)\
                .OfCategory(member).WhereElementIsNotElementType()
            seen_types = set()
            count = 0
            for element in collector:
                count += 1
                try:
                    for prm in element.Parameters:
                        try:
                            names.add(prm.Definition.Name)
                        except Exception:
                            continue
                except Exception:
                    pass
                try:
                    type_id = element.GetTypeId()
                    key = eid_value(type_id)
                    if key not in seen_types:
                        seen_types.add(key)
                        symbol = doc.GetElement(type_id)
                        if symbol is not None:
                            for prm in symbol.Parameters:
                                try:
                                    names.add(prm.Definition.Name)
                                except Exception:
                                    continue
                except Exception:
                    pass
                if count >= sample:
                    break
        except Exception:
            continue
    names.add(DEFAULT_PARAM)
    for name in DEFAULT_PARAMS.values():
        names.add(name)
    return sorted(names, key=lambda s: s.lower())


# ===========================================================================
# the routine
# ===========================================================================

class Report(object):
    def __init__(self):
        self.lines = []
        self.notes = []
        self.count = 0
        self.verb = u"isolated"
        self.reset = False
        self.refused = None
        self.cancelled = False
        self.memory = False        # a remembered hide: open Reset Hide

    def add(self, text):
        self.lines.append(text)

    def note(self, text):
        u"""Something that needs a look."""
        self.notes.append(text)

    @property
    def needs_look(self):
        if self.cancelled:
            return False
        return bool(self.notes) or self.refused is not None


def groups_for_category(cat_name, active_cats):
    u"""Every group the category is switched on for.  Mechanical Equipment can
    legitimately be in both Duct and Pipe, so this returns a list."""
    return [g for g in GROUP_KEYS if cat_name in active_cats.get(g, [])]


VERB = {u"isolate": u"isolated", u"hide": u"hidden"}


def _element_name(element):
    try:
        return u"{0}".format(element.Name or u"")
    except Exception:
        try:
            from Autodesk.Revit.DB import Element
            return u"{0}".format(Element.Name.GetValue(element) or u"")
        except Exception:
            return u""


def temp_filter_ids(doc, view):
    u"""The RevoBIM Temp Hide filters on this view."""
    out = []
    try:
        applied = list(view.GetFilters())
    except Exception:
        return out
    for filter_id in applied:
        element = doc.GetElement(filter_id)
        if element is not None and \
                _element_name(element).startswith(TEMP_FILTER_PREFIX):
            out.append(filter_id)
    return out


def remove_temp_filters(doc, view):
    u"""Takes this tool's filters off the view, and deletes any no other view
    or template still uses.  Runs inside the caller's transaction."""
    ours = temp_filter_ids(doc, view)
    if not ours:
        return 0
    for filter_id in ours:
        try:
            view.RemoveFilter(filter_id)
        except Exception:
            continue
    still_used = set()
    try:
        from Autodesk.Revit.DB import View as RevitView
        for other in FilteredElementCollector(doc).OfClass(RevitView):
            try:
                for filter_id in other.GetFilters():
                    still_used.add(eid_value(filter_id))
            except Exception:
                continue
    except Exception:
        return len(ours)
    for filter_id in ours:
        if eid_value(filter_id) in still_used:
            continue
        try:
            doc.Delete(filter_id)
        except Exception:
            continue
    return len(ours)


def needs_reset(doc, view):
    try:
        if view.IsTemporaryHideIsolateActive():
            return True
    except Exception:
        pass
    if temp_filter_ids(doc, view):
        return True
    try:
        import ist_memory
        return ist_memory.view_is_hidden(doc, view)
    except Exception:
        return False


def _reset_view(doc, view, report):
    u"""Both tools come back the same way: Temporary Hide/Isolate off, and this
    tool's linked-model filters off the view."""
    trans = Transaction(doc, u"Reset view")
    trans.Start()
    try:
        try:
            active = view.IsTemporaryHideIsolateActive()
        except Exception:
            active = False
        if active:
            view.DisableTemporaryViewMode(
                TemporaryViewMode.TemporaryHideIsolate)
            report.add(u"Temporary Hide/Isolate reset.")
        save_memory = None
        try:
            import ist_memory
            save_memory = ist_memory.reset_view_memory(doc, view, report)
        except Exception as err:
            report.note(u"The remembered hide could not be put back: "
                        u"{0}".format(err))
        removed = remove_temp_filters(doc, view)
        if removed:
            report.add(u"{0} linked-model filter{1} removed.".format(
                removed, u"" if removed == 1 else u"s"))
        trans.Commit()
        if save_memory is not None:
            save_memory()
        report.reset = True
    except Exception as err:
        try:
            trans.RollBack()
        except Exception:
            pass
        report.refused = u"Could not reset the view: {0}".format(err)
    return report


PICK_PROMPT = {
    u"isolate": u"Isolate Service Type: pick services, then Finish "
                u"(Finish with nothing picked resets the view)",
    u"hide": u"Hide Service Type: pick services, then Finish "
             u"(Finish with nothing picked resets the view)",
}


def pick_elements(uidoc, mode):
    u"""Revit's own multi-pick, with Finish and Cancel on the Options Bar.

    Returns the picked ids - an empty list when Finish was pressed on nothing,
    which the caller turns into the reset - or None when Escape cancelled.
    The cancel exception is matched by name rather than imported, so nothing
    from Autodesk.Revit.Exceptions has to load for the tool to start."""
    from Autodesk.Revit.UI.Selection import ObjectType
    try:
        refs = uidoc.Selection.PickObjects(
            ObjectType.Element, PICK_PROMPT.get(mode, PICK_PROMPT[u"isolate"]))
    except Exception as err:
        if u"OperationCanceled" in type(err).__name__ or \
                u"OperationCanceled" in u"{0}".format(err):
            return None
        raise
    out = []
    seen = set()
    for ref in refs or []:
        try:
            element_id = ref.ElementId
        except Exception:
            continue
        key = eid_value(element_id)
        if key in seen:
            continue
        seen.add(key)
        out.append(element_id)
    return out


def resolve(uidoc, values, report, mode):
    u"""Read the selection and work out which elements the run is about.

    Isolate and Hide ask exactly the same question - everything in the view
    sharing the picked service type - and differ only in what they then do with
    the answer, so the matching lives here and the two commands are thin.

    Returns a plan dict, or None where `report` already says why not.
    """
    verb = VERB.get(mode, u"isolated")
    doc = uidoc.Document

    try:
        view = doc.ActiveView
    except Exception:
        view = None
    if view is None:
        report.refused = u"There is no active view."
        return None

    try:
        usable = view.CanUseTemporaryVisibilityModes()
    except Exception:
        usable = False
    if not usable:
        report.refused = (u"This view will not take Temporary Hide/Isolate - "
                          u"a sheet, a schedule or a view template.")
        return None

    try:
        selected_ids = list(uidoc.Selection.GetElementIds())
    except Exception:
        selected_ids = []

    # -- nothing selected: pick, or the reset -------------------------------
    if not selected_ids:
        how = (values.get(u"nothing_selected", u"pick")
               or u"pick").strip().lower()
        if how == u"pick":
            picked = pick_elements(uidoc, mode)
            if picked is None:
                # Escape: the user changed their mind.  No window, no change.
                report.cancelled = True
                return None
            selected_ids = picked

    if not selected_ids:
        active = needs_reset(doc, view)
        if active and is_on(values, u"empty_selection_resets"):
            _reset_view(doc, view, report)
            return None
        report.refused = (u"Nothing is selected. Pick a tray, duct, pipe or "
                          u"conduit and run it again.")
        return None

    case_sensitive = is_on(values, u"match_case")
    blank_rule = (values.get(u"blank_value", u"skip") or u"skip").strip().lower()

    active_cats = {}
    for group in GROUP_KEYS:
        active_cats[group] = cats_of(values, group)

    id_to_cat = category_ids()

    fallback = is_on(values, u"fallback_builtin")
    readers = {}
    for group in GROUP_KEYS:
        readers[group] = ValueReader(doc, param_of(values, group), group,
                                     fallback)

    # -- what was picked ----------------------------------------------------
    other_scope = (values.get(u"other_scope", u"category")
                   or u"category").strip().lower()
    family_cache = {}

    wanted = {}            # group -> set of normalised values
    whole_group = set()    # groups to take wholesale
    blank_groups = set()   # groups where a blank value is itself a match
    others = {}            # category id -> what was picked from it
    seen_values = {}       # group -> {normalised: as typed}

    def note_other(element, category, label):
        entry = others.setdefault(eid_value(category.Id), {
            u"label": label,
            u"cat_id": category.Id,
            u"families": set(),
            u"types": set(),
        })
        entry[u"families"].add(family_name_of(doc, element, family_cache))
        try:
            entry[u"types"].add(eid_value(element.GetTypeId()))
        except Exception:
            pass

    for element_id in selected_ids:
        element = doc.GetElement(element_id)
        if element is None:
            continue
        try:
            category = element.Category
            cat_int = eid_value(category.Id) if category is not None else 0
            cat_label = category.Name if category is not None else u"?"
        except Exception:
            continue
        cat_name = id_to_cat.get(cat_int)
        groups = groups_for_category(cat_name, active_cats) if cat_name else []
        if not groups:
            note_other(element, category, cat_label)
            continue

        placed = False
        for group in groups:
            raw = readers[group].value(element)
            key = normalise(raw, case_sensitive)
            if key:
                wanted.setdefault(group, set()).add(key)
                seen_values.setdefault(group, {})[key] = u"{0}".format(raw).strip()
                placed = True
        if placed:
            continue

        # Blank on every group it belongs to.
        group = groups[0]
        if blank_rule == u"skip":
            report.note(u"{0} has no {1} - left out, nothing else was "
                        u"{2} on its account.".format(
                            LABEL_OF.get(cat_name, cat_name),
                            param_of(values, group), verb))
        elif blank_rule == u"blank":
            blank_groups.add(group)
            wanted.setdefault(group, set())
            report.note(u"{0} has no {1} - matching other blanks.".format(
                LABEL_OF.get(cat_name, cat_name), param_of(values, group)))
        else:
            whole_group.add(group)
            report.note(u"{0} has no {1} - the whole {2} group is {3}.".format(
                LABEL_OF.get(cat_name, cat_name), param_of(values, group),
                GROUP_LABEL[group].lower(), verb))

    if other_scope == u"ignore":
        for entry in others.values():
            report.note(u"{0} does not carry a service type - ignored.".format(
                entry[u"label"]))
        others = {}

    live_groups = sorted(set(list(wanted.keys()) + list(whole_group)))
    if not live_groups and not others:
        report.refused = (u"Nothing in the selection carries a service type "
                          u"this tool can work from.")
        return None

    # -- one collector pass over every category in play ---------------------
    cat_list = NetList[BuiltInCategory]()
    added = set()
    for group in live_groups:
        for cat_name in active_cats.get(group, []):
            member = bic(cat_name)
            if member is not None and cat_name not in added:
                added.add(cat_name)
                cat_list.Add(member)

    chosen = set()
    per_group = {}
    if cat_list.Count:
        collector = FilteredElementCollector(doc, view.Id)\
            .WherePasses(ElementMulticategoryFilter(cat_list))\
            .WhereElementIsNotElementType()
        for element in collector:
            try:
                category = element.Category
                if category is None:
                    continue
                cat_name = id_to_cat.get(eid_value(category.Id))
            except Exception:
                continue
            if cat_name is None:
                continue
            for group in groups_for_category(cat_name, active_cats):
                if group not in live_groups:
                    continue
                if group in whole_group:
                    chosen.add(eid_value(element.Id))
                    per_group[group] = per_group.get(group, 0) + 1
                    break
                key = normalise(readers[group].value(element), case_sensitive)
                if key in wanted.get(group, set()) or (
                        not key and group in blank_groups):
                    chosen.add(eid_value(element.Id))
                    per_group[group] = per_group.get(group, 0) + 1
                    break

    # -- categories that carry no service type ------------------------------
    other_counts = {}
    for cat_int, entry in others.items():
        found = 0
        for element in elements_in_category(doc, view, entry[u"cat_id"], cat_int):
            if other_scope == u"category":
                pass
            elif other_scope == u"type":
                try:
                    if eid_value(element.GetTypeId()) not in entry[u"types"]:
                        continue
                except Exception:
                    continue
            elif other_scope == u"family":
                if family_name_of(doc, element, family_cache) not in \
                        entry[u"families"]:
                    continue
            chosen.add(eid_value(element.Id))
            found += 1
        other_counts[cat_int] = found

    # -- the section box of a 3D view ---------------------------------------
    # Temporary Hide/Isolate takes the section box away with everything else
    # unless it is in the list, and there is no way to pick it beforehand.
    # Hiding is the other way round: the section box must stay out of the list
    # or the box itself goes.
    if mode == u"isolate" and \
            getattr(view, u"IsSectionBoxActive", None) is not None:
        member = bic(u"OST_SectionBox")
        if member is not None:
            try:
                collector = FilteredElementCollector(doc, view.Id)\
                    .OfCategory(member).WhereElementIsNotElementType()
                for element in collector:
                    chosen.add(eid_value(element.Id))
            except Exception:
                report.note(u"The section box could not be read; isolating "
                            u"may switch it off.")

    # -- the selection itself ------------------------------------------------
    # Isolating, this keeps what was picked visible and is a setting.  Hiding,
    # what was picked must go, or the one element the user pointed at is the
    # one left behind.
    if mode == u"hide" or is_on(values, u"include_selection"):
        for element_id in selected_ids:
            chosen.add(eid_value(element_id))

    # -- insulation and lining ----------------------------------------------
    insulation_count = 0
    if is_on(values, u"include_insulation"):
        ins_cats = NetList[BuiltInCategory]()
        for cat_name in INSULATION_CATS:
            member = bic(cat_name)
            if member is not None:
                ins_cats.Add(member)
        if ins_cats.Count:
            try:
                collector = FilteredElementCollector(doc, view.Id)\
                    .WherePasses(ElementMulticategoryFilter(ins_cats))\
                    .WhereElementIsNotElementType()
                extra = 0
                for element in collector:
                    try:
                        host = eid_value(element.HostElementId)
                    except Exception:
                        continue
                    if host in chosen:
                        chosen.add(eid_value(element.Id))
                        extra += 1
                insulation_count = extra
            except Exception:
                report.note(u"Insulation could not be read; it is left out.")

    if is_on(values, u"hide_uncaptured"):
        # What was left out is still left out; it just stops being a reason to
        # open a window.  A refusal is not a note, so it still reports.
        report.notes = []

    if not chosen:
        report.refused = u"Nothing in this view matches the selection."
        return None

    return {
        u"doc": doc,
        u"view": view,
        u"chosen": chosen,
        u"live_groups": live_groups,
        u"per_group": per_group,
        u"whole_group": whole_group,
        u"wanted": wanted,
        u"seen_values": seen_values,
        u"others": others,
        u"other_counts": other_counts,
        u"other_scope": other_scope,
        u"selected_ids": selected_ids,
        u"insulation": insulation_count,
    }


def describe(report, plan, verb, tail):
    u"""The same report for both tools, with the verb swapped."""
    for group in plan[u"live_groups"]:
        label = GROUP_LABEL[group]
        count = plan[u"per_group"].get(group, 0)
        if group in plan[u"whole_group"]:
            report.add(u"{0}: every element in the group ({1})".format(
                label, count))
        else:
            shown = plan[u"seen_values"].get(group, {})
            names = sorted(shown.get(k, k)
                           for k in plan[u"wanted"].get(group, set()))
            if not names:
                names = [u"(blank)"]
            report.add(u"{0}: {1}  -  {2} element{3}".format(
                label, u", ".join(names), count, u"" if count == 1 else u"s"))

    scope_words = {
        u"category": u"the whole category",
        u"family": u"family {0}",
        u"type": u"the picked type",
    }
    for cat_int in sorted(plan[u"others"].keys()):
        entry = plan[u"others"][cat_int]
        word = scope_words.get(plan[u"other_scope"], u"")
        if plan[u"other_scope"] == u"family":
            names = sorted(n for n in entry[u"families"] if n)
            word = word.format(u", ".join(names) or u"?")
        report.add(u"{0}: {1}  -  {2} elements".format(
            entry[u"label"], word, plan[u"other_counts"].get(cat_int, 0)))

    if plan.get(u"insulation"):
        report.add(u"Insulation and lining: {0}".format(plan[u"insulation"]))
    report.add(u"{0} elements {1} {2}".format(report.count, verb, tail))
    return report


def _net_ids(values):
    ids = NetList[ElementId]()
    for value in values:
        ids.Add(ElementId(value))
    return ids


def isolate(uidoc, values, report=None):
    u"""Everything sharing the picked service type stays; the rest goes."""
    report = report or Report()
    report.verb = u"isolated"
    plan = resolve(uidoc, values, report, u"isolate")
    if plan is None:
        return report

    doc, view = plan[u"doc"], plan[u"view"]
    trans = Transaction(doc, u"Isolate service type")
    trans.Start()
    try:
        try:
            if view.IsTemporaryHideIsolateActive():
                view.DisableTemporaryViewMode(
                    TemporaryViewMode.TemporaryHideIsolate)
        except Exception:
            pass
        view.IsolateElementsTemporary(_net_ids(plan[u"chosen"]))
        trans.Commit()
    except Exception as err:
        try:
            trans.RollBack()
        except Exception:
            pass
        report.refused = u"Revit refused the isolation: {0}".format(err)
        return report

    report.count = len(plan[u"chosen"])
    return describe(report, plan, u"isolated", u"in {0}.".format(view.Name))


def hide_mode_of(values):
    mode = (values.get(u"hide_mode", u"memory") or u"memory").strip().lower()
    return mode if mode in (u"memory", u"temporary", u"permanent") \
        else u"memory"


def _permanent(values):
    u"""Revit's Hide in View - which the remembered hide uses too."""
    return hide_mode_of(values) in (u"memory", u"permanent")


def _begin_replace(doc, view, values, mode):
    u"""Inside the hide's transaction, before anything is worked out: put the
    view's remembered hide back, so the new one starts clean.  Must run before
    _not_yet_hidden - otherwise anything in both the old and the new selection
    still reads as hidden, is left out of the new record, and Reset can never
    bring it back.  Returns the old record's saver, or None."""
    if mode != u"memory" or not is_on(values, u"hide_replaces"):
        return None
    try:
        import ist_memory
        return ist_memory.reset_view_memory(doc, view, Report())
    except Exception:
        return None


def _not_yet_hidden(doc, view, ids):
    u"""Only what the tool itself hides goes in the memory, so Reset never
    unhides something somebody hid before."""
    out = set()
    for value in ids:
        element = doc.GetElement(ElementId(value))
        if element is None:
            continue
        try:
            if element.IsHidden(view):
                continue
        except Exception:
            pass
        out.add(value)
    return out


def _hideable(doc, view, ids):
    u"""Revit throws on the whole call if one element in it cannot be hidden,
    so the ones that cannot are dropped here and counted."""
    keep = set()
    stubborn = 0
    for value in ids:
        element = doc.GetElement(ElementId(value))
        if element is None:
            continue
        try:
            if not element.CanBeHidden(view):
                stubborn += 1
                continue
        except Exception:
            pass
        keep.add(value)
    return keep, stubborn


def _hide_now(view, ids, permanent):
    if permanent:
        view.HideElements(_net_ids(ids))
    else:
        view.HideElementsTemporary(_net_ids(ids))


def _hidden_tail(view, permanent, mode=None):
    if mode == u"memory":
        return u"in {0}. Reset Hide puts them back.".format(view.Name)
    if permanent:
        return u"in {0}. Reveal Hidden Elements brings them back.".format(
            view.Name)
    return u"in {0}, temporarily.".format(view.Name)


def hide(uidoc, values, report=None):
    u"""Everything sharing the picked service type goes; the rest stays."""
    report = report or Report()
    report.verb = u"hidden"
    plan = resolve(uidoc, values, report, u"hide")
    if plan is None:
        return report

    doc, view = plan[u"doc"], plan[u"view"]
    permanent = _permanent(values)
    mode = hide_mode_of(values)
    hideable, stubborn = _hideable(doc, view, plan[u"chosen"])
    if not hideable:
        report.refused = u"Nothing that matched can be hidden in this view."
        return report
    fresh = set()
    old_saver = None

    trans = Transaction(doc, u"Hide service type")
    trans.Start()
    try:
        old_saver = _begin_replace(doc, view, values, mode)
        if mode == u"memory":
            fresh = _not_yet_hidden(doc, view, hideable)
        _hide_now(view, hideable, permanent)
        trans.Commit()
    except Exception as err:
        try:
            trans.RollBack()
        except Exception:
            pass
        report.refused = u"Revit refused the hide: {0}".format(err)
        return report

    report.count = len(hideable)
    replace = is_on(values, u"hide_replaces")
    if mode == u"memory" and fresh:
        import ist_memory
        ist_memory.remember(doc, view, host=fresh, replace=replace)
        report.memory = True
    elif old_saver is not None:
        old_saver()
    if stubborn:
        report.note(u"{0} element{1} could not be hidden in this view.".format(
            stubborn, u"" if stubborn == 1 else u"s"))
    return describe(report, plan, u"hidden",
                    _hidden_tail(view, permanent, mode))


# ===========================================================================
# hiding from the category list
# ===========================================================================

def insulation_for(doc, view, ids):
    u"""Insulation and lining in the view whose host is in `ids`."""
    out = set()
    cats = NetList[BuiltInCategory]()
    for cat_name in INSULATION_CATS:
        member = bic(cat_name)
        if member is not None:
            cats.Add(member)
    if not cats.Count or not ids:
        return out
    try:
        collector = FilteredElementCollector(doc, view.Id)\
            .WherePasses(ElementMulticategoryFilter(cats))\
            .WhereElementIsNotElementType()
        for element in collector:
            try:
                if eid_value(element.HostElementId) in ids:
                    out.add(eid_value(element.Id))
            except Exception:
                continue
    except Exception:
        pass
    return out


def shared_parameter_ids(doc):
    u"""{name: ElementId} of the shared parameters this model carries."""
    out = {}
    try:
        from Autodesk.Revit.DB import SharedParameterElement
        for element in FilteredElementCollector(doc)\
                .OfClass(SharedParameterElement):
            name = _element_name(element)
            if name and name not in out:
                out[name] = element.Id
    except Exception:
        pass
    return out


def existing_filters(doc):
    out = {}
    try:
        from Autodesk.Revit.DB import ParameterFilterElement
        for element in FilteredElementCollector(doc)\
                .OfClass(ParameterFilterElement):
            out[_element_name(element)] = element.Id
    except Exception:
        pass
    return out


def _filter_rule(param_id, test, value):
    from Autodesk.Revit.DB import ParameterFilterRuleFactory
    if test == u"novalue":
        return ParameterFilterRuleFactory.CreateHasNoValueParameterRule(param_id)
    try:
        # 2023 onwards: no case-sensitivity argument.
        return ParameterFilterRuleFactory.CreateEqualsRule(param_id, value)
    except Exception:
        return ParameterFilterRuleFactory.CreateEqualsRule(param_id, value, False)


def make_filter(doc, name, cat_int, plan, shared_ids):
    u"""A ParameterFilterElement for one linked row.  Raises with a sentence
    when Revit will not take the rule on that category."""
    from Autodesk.Revit.DB import (
        BuiltInParameter, ElementParameterFilter, FilterRule,
        ParameterFilterElement)
    cats = NetList[ElementId]()
    cats.Add(ElementId(cat_int))
    if not plan:
        return ParameterFilterElement.Create(doc, name, cats).Id
    rules = NetList[FilterRule]()
    for source, param, test, value in plan:
        if source == u"shared":
            param_id = shared_ids.get(param)
        else:
            member = getattr(BuiltInParameter, param, None)
            param_id = ElementId(member) if member is not None else None
        if param_id is None:
            raise Exception(u"{0} is not available here".format(param))
        rules.Add(_filter_rule(param_id, test, value))
    element_filter = ElementParameterFilter(rules)
    try:
        acceptable = ParameterFilterElement\
            .ElementFilterIsAcceptableForParameterFilterElement(
                doc, cats, element_filter)
    except Exception:
        acceptable = True
    if not acceptable:
        raise Exception(u"Revit will not filter this category by that "
                        u"parameter")
    return ParameterFilterElement.Create(doc, name, cats, element_filter).Id


def hide_from_list(uidoc, values, picked, report=None):
    u"""Carry out what was ticked in the category list.

    `picked` is ist_browse.summarise() output, or {"reset": True}.  Host rows
    are hidden by id the same way as everywhere else; a whole link is hidden as
    its link instance; every other linked row becomes a filter.  One
    transaction, so one Ctrl+Z.
    """
    import ist_browse
    report = report or Report()
    report.verb = u"hidden"
    doc = uidoc.Document
    view = doc.ActiveView

    if picked.get(u"reset"):
        return _reset_view(doc, view, report)
    if picked.get(u"empty"):
        report.cancelled = True
        return report

    permanent = _permanent(values)
    mode = hide_mode_of(values)
    ids = set(picked.get(u"host_ids") or ())
    if ids and is_on(values, u"include_insulation"):
        ids |= insulation_for(doc, view, ids)
    link_ids = set()
    for node in picked.get(u"whole_links") or ():
        if node.link_id is not None:
            link_ids.add(eid_value(node.link_id))
    ids |= link_ids
    hideable, stubborn = _hideable(doc, view, ids)
    fresh = set()
    old_saver = None
    specs = {}

    shared_ids = None
    known = None
    made = 0
    linked_count = 0
    failed = []
    trans = Transaction(doc, u"Hide from list")
    trans.Start()
    try:
        old_saver = _begin_replace(doc, view, values, mode)
        if mode == u"memory":
            fresh = _not_yet_hidden(doc, view, hideable)
        if hideable:
            _hide_now(view, hideable, permanent)
        rows = picked.get(u"filters") or ()
        if rows:
            shared_ids = shared_parameter_ids(doc)
            known = existing_filters(doc)
            for node in rows:
                rule = node.rule or {}
                name = ist_browse.filter_name(rule)
                plan = ist_browse.filter_plan(
                    rule, values, lambda n: n in shared_ids)
                try:
                    filter_id = known.get(name)
                    if filter_id is None:
                        filter_id = make_filter(doc, name, rule[u"cat"], plan,
                                                shared_ids)
                        known[name] = filter_id
                    applied = set(eid_value(f) for f in view.GetFilters())
                    if eid_value(filter_id) not in applied:
                        view.AddFilter(filter_id)
                    view.SetFilterVisibility(filter_id, False)
                    made += 1
                    linked_count += node.count
                    if mode == u"memory":
                        import ist_memory
                        specs[name] = ist_memory.filter_spec(
                            rule, plan, name[len(TEMP_FILTER_PREFIX) + 3:])
                except Exception as err:
                    failed.append(u"{0}: {1}".format(
                        name[len(TEMP_FILTER_PREFIX) + 3:], err))
        trans.Commit()
    except Exception as err:
        try:
            trans.RollBack()
        except Exception:
            pass
        report.refused = u"Revit refused the hide: {0}".format(err)
        return report

    report.count = len(hideable) + linked_count
    if mode == u"memory" and (fresh or specs):
        import ist_memory
        ist_memory.remember(doc, view, host=fresh - link_ids,
                            links=fresh & link_ids, filters=specs,
                            replace=is_on(values, u"hide_replaces"),
                            template=picked.get(u"template"))
        report.memory = True
    elif old_saver is not None:
        old_saver()
    links = len(picked.get(u"whole_links") or ())
    host_count = len(hideable) - links
    if host_count:
        report.add(u"This model: {0} element{1} hidden {2}".format(
            host_count, u"" if host_count == 1 else u"s",
            _hidden_tail(view, permanent, mode)))
    if links:
        report.add(u"{0} whole link{1} hidden.".format(
            links, u"" if links == 1 else u"s"))
    if made:
        report.add(u"Linked models: {0} RevoBIM Temp filter{1} on this view. "
                   u"Reset removes them.".format(made,
                                                 u"" if made == 1 else u"s"))
    if stubborn:
        report.note(u"{0} element{1} could not be hidden in this view.".format(
            stubborn, u"" if stubborn == 1 else u"s"))
    if is_on(values, u"hide_uncaptured"):
        report.notes = []
    # Never silenced: a row that did not hide, and host elements hidden that
    # nobody ticked, are both things the user would otherwise not know.
    for line in failed:
        report.note(u"Not filtered - {0}".format(line))
    if made and picked.get(u"collateral"):
        report.note(u"Those filters also hide {0} element{1} of this "
                    u"model.".format(picked[u"collateral"],
                                     u"" if picked[u"collateral"] == 1
                                     else u"s"))
    return report
