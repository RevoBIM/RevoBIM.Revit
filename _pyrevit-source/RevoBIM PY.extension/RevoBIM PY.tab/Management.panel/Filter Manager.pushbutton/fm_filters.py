# -*- coding: utf-8 -*-
"""RevoBIM PY - Filter Manager : Revit filter reading and writing.

Everything that touches ParameterFilterElement lives here so the window
code stays about the window.

Revit 2021 - 2027.  No f-strings, no System.Uri, no bare .IntegerValue.
"""

import fm_clr  # noqa  - must be first, it holds every clr.AddReference

import re

from Autodesk.Revit.DB import (
    ElementId,
    BuiltInCategory,
    Category,
    FilteredElementCollector,
    ParameterFilterElement,
    ParameterFilterUtilities,
    ParameterFilterRuleFactory,
    ElementParameterFilter,
    LogicalAndFilter,
    LogicalOrFilter,
    ElementMulticategoryFilter,
    LabelUtils,
    UnitUtils,
    StorageType,
    View,
)

from System.Collections.Generic import List

from fm_core import eid_value, revit_version


DOUBLE_EPSILON = 0.000001

# Anything here costs a scan of the model to work out and does not change
# until the model does, so it is worked out once and kept. clear_caches() is
# called whenever the tool re-reads the document.
_CACHE = {"categories": None, "parameters": {}, "probes": {}, "lookups": {}}


def clear_caches():
    _CACHE["categories"] = None
    _CACHE["parameters"] = {}
    _CACHE["probes"] = {}
    _CACHE["lookups"] = {}


def category_signature(category_ids):
    """A key for a set of categories, so two filters on the same categories
    share one answer instead of working it out twice."""
    try:
        return tuple(sorted(eid_value(c) for c in (category_ids or [])))
    except Exception:
        return tuple()

# operator key -> (label, factory method name, needs a value)
OPERATORS = [
    ("equals",        "equals",                       "CreateEqualsRule",         True),
    ("not_equals",    "does not equal",               "CreateNotEqualsRule",      True),
    ("greater",       "is greater than",              "CreateGreaterRule",        True),
    ("greater_equal", "is greater than or equal to",  "CreateGreaterOrEqualRule", True),
    ("less",          "is less than",                 "CreateLessRule",           True),
    ("less_equal",    "is less than or equal to",     "CreateLessOrEqualRule",    True),
    ("contains",      "contains",                     "CreateContainsRule",       True),
    ("not_contains",  "does not contain",             "CreateNotContainsRule",    True),
    ("begins",        "begins with",                  "CreateBeginsWithRule",     True),
    ("not_begins",    "does not begin with",          "CreateNotBeginsWithRule",  True),
    ("ends",          "ends with",                    "CreateEndsWithRule",       True),
    ("not_ends",      "does not end with",            "CreateNotEndsWithRule",    True),
    ("has_value",     "has a value",                  "CreateHasValueParameterRule",   False),
    ("has_no_value",  "has no value",                 "CreateHasNoValueParameterRule", False),
]

OP_LABEL = {}
OP_FACTORY = {}
OP_NEEDS_VALUE = {}
for _k, _lbl, _fac, _needs in OPERATORS:
    OP_LABEL[_k] = _lbl
    OP_FACTORY[_k] = _fac
    OP_NEEDS_VALUE[_k] = _needs

LABEL_TO_OP = {}
for _k in OP_LABEL:
    LABEL_TO_OP[OP_LABEL[_k]] = _k

STRING_OPS = ["equals", "not_equals", "contains", "not_contains",
              "begins", "not_begins", "ends", "not_ends",
              "greater", "greater_equal", "less", "less_equal",
              "has_value", "has_no_value"]

NUMERIC_OPS = ["equals", "not_equals", "greater", "greater_equal",
               "less", "less_equal", "has_value", "has_no_value"]

# Revit offers the text operators on an element id parameter as well, because
# it matches against the name of the element the parameter points at - which
# is why "System Type contains" is a perfectly ordinary filter rule.
ID_TEXT_OPS = ["contains", "not_contains", "begins", "not_begins",
               "ends", "not_ends"]

ID_OPS = ["equals", "not_equals"] + ID_TEXT_OPS + \
    ["has_value", "has_no_value"]

YESNO_OPS = ["equals", "not_equals", "has_value", "has_no_value"]


def ops_for_storage(storage, is_yesno=False):
    if is_yesno:
        return YESNO_OPS
    if storage == "String":
        return STRING_OPS
    if storage == "ElementId":
        return ID_OPS
    return NUMERIC_OPS


# ---------------------------------------------------------------------------
#  Filters in the project
# ---------------------------------------------------------------------------
def get_all_filters(doc):
    """Every ParameterFilterElement, sorted by name."""
    out = []
    try:
        for f in FilteredElementCollector(doc)\
                .OfClass(ParameterFilterElement).ToElements():
            out.append(f)
    except Exception:
        pass
    try:
        out.sort(key=lambda x: x.Name.lower())
    except Exception:
        pass
    return out


def filter_usage(doc):
    """{filter id value: number of views/templates using it}."""
    used = {}
    try:
        for v in FilteredElementCollector(doc).OfClass(View):
            try:
                if not supports_filters(v):
                    continue
                for fid in v.GetFilters():
                    k = eid_value(fid)
                    used[k] = used.get(k, 0) + 1
            except Exception:
                continue
    except Exception:
        pass
    return used


def filter_category_ids(pfe):
    try:
        return [c for c in pfe.GetCategories()]
    except Exception:
        return []


# ---------------------------------------------------------------------------
#  Categories
# ---------------------------------------------------------------------------
def category_map(doc):
    """{id value: name} read once out of the document's own category table.

    Category.GetCategory is avoided here: it is the least predictable call
    in the startup path, and one bad category id in a loop over every
    filterable category is not worth the risk when doc.Settings.Categories
    already holds the same names.
    """
    if _CACHE["categories"] is not None:
        return _CACHE["categories"]

    out = {}
    try:
        for cat in doc.Settings.Categories:
            try:
                out[eid_value(cat.Id)] = cat.Name
            except Exception:
                continue
    except Exception:
        pass
    _CACHE["categories"] = out
    return out


def filterable_categories(doc):
    """[(ElementId, name)] of every category a filter may be built on."""
    out = []
    known = category_map(doc)
    try:
        ids = ParameterFilterUtilities.GetAllFilterableCategories()
    except Exception:
        return out

    for cid in ids:
        name = known.get(eid_value(cid))
        if not name:
            name = builtin_category_name(cid)
        if name:
            out.append((cid, name))
    try:
        out.sort(key=lambda x: x[1].lower())
    except Exception:
        pass
    return out


def builtin_category_name(cid):
    try:
        return LabelUtils.GetLabelFor(BuiltInCategory(eid_value(cid)))
    except Exception:
        return None


def category_name(doc, cid):
    name = category_map(doc).get(eid_value(cid))
    return name if name else builtin_category_name(cid)


# ---------------------------------------------------------------------------
#  Parameters
# ---------------------------------------------------------------------------
def common_parameters(doc, category_ids):
    """[(ElementId, name)] filterable on every one of these categories."""
    out = []
    if not category_ids:
        return out

    signature = category_signature(category_ids)
    if signature in _CACHE["parameters"]:
        return _CACHE["parameters"][signature]
    try:
        ids = List[ElementId]()
        for c in category_ids:
            ids.Add(c)
        for pid in ParameterFilterUtilities.GetFilterableParametersInCommon(doc, ids):
            nm = parameter_name(doc, pid)
            if nm:
                out.append((pid, nm))
    except Exception:
        pass
    try:
        out.sort(key=lambda x: x[1].lower())
    except Exception:
        pass
    _CACHE["parameters"][signature] = out
    return out


def probe_for(doc, category_ids):
    """A ParameterProbe per set of categories, not per filter.

    Sampling elements is the most expensive thing the tool does, and a
    project's filters use the same handful of category sets over and over,
    so the answer is worked out once and shared.
    """
    signature = category_signature(category_ids)
    if signature not in _CACHE["probes"]:
        _CACHE["probes"][signature] = ParameterProbe(doc, category_ids)
    return _CACHE["probes"][signature]


def parameter_lookup(doc, category_ids):
    """{lower name: (ElementId, scope)} for anything a rule could point at.

    Three widening circles:
      common   every one of the filter's categories has it - what Revit's
               own dialog offers
      partial  at least one category has it, but not all of them
      project  a parameter of that name exists in the project

    Anything past "common" is still worth accepting on the way in from a
    sheet - the parameter exists, the user has asked for it, and Revit is
    the one that decides whether it will take it.
    """
    signature = category_signature(category_ids)
    if signature in _CACHE["lookups"]:
        return _CACHE["lookups"][signature]

    out = {}

    for pid, name in common_parameters(doc, category_ids):
        out[name.lower()] = (pid, "common")

    for cid in category_ids or []:
        try:
            for pid, name in common_parameters(doc, [cid]):
                if name.lower() not in out:
                    out[name.lower()] = (pid, "partial")
        except Exception:
            continue

    try:
        from Autodesk.Revit.DB import ParameterElement
        for element in FilteredElementCollector(doc)\
                .OfClass(ParameterElement).ToElements():
            try:
                name = element.Name
            except Exception:
                continue
            if name and name.lower() not in out:
                out[name.lower()] = (element.Id, "project")
    except Exception:
        pass

    _CACHE["lookups"][signature] = out
    return out


def parameter_name(doc, pid):
    val = eid_value(pid)
    if val < 0:
        # built-in parameter
        try:
            from Autodesk.Revit.DB import BuiltInParameter
            return LabelUtils.GetLabelFor(BuiltInParameter(val))
        except Exception:
            pass
    try:
        el = doc.GetElement(pid)
        if el is not None:
            return el.Name
    except Exception:
        pass
    return "Parameter {0}".format(val)


class ParameterProbe(object):
    """Works out a parameter's storage type and unit spec from real elements.

    Built-in parameters have no ParameterElement to interrogate, so the only
    reliable route is to find an element that actually carries the parameter
    and read it there. Sample elements are collected once per category set
    and the answer cached per parameter.
    """

    def __init__(self, doc, category_ids, sample_size=250):
        self.doc = doc
        self.cache = {}
        self.samples = []
        self._collect(category_ids, sample_size)

    def _collect(self, category_ids, sample_size):
        if not category_ids:
            return
        try:
            ids = List[ElementId]()
            for c in category_ids:
                ids.Add(c)
            mcf = ElementMulticategoryFilter(ids)

            # iterated rather than ToElements(): only the first few hundred
            # are wanted, and ToElements builds the whole list first
            for collector in (
                    FilteredElementCollector(self.doc).WherePasses(mcf)
                    .WhereElementIsNotElementType(),
                    FilteredElementCollector(self.doc).WherePasses(mcf)
                    .WhereElementIsElementType()):
                count = 0
                for e in collector:
                    self.samples.append(e)
                    count += 1
                    if count >= sample_size:
                        break
        except Exception:
            pass

    def find(self, pid):
        """(storage, spec_or_None, is_yesno) for a parameter id."""
        key = eid_value(pid)
        if key in self.cache:
            return self.cache[key]

        storage, spec, yesno = "String", None, False
        found = False
        for el in self.samples:
            p = _param_on(el, key)
            if p is None:
                continue
            try:
                st = p.StorageType
                if st == StorageType.String:
                    storage = "String"
                elif st == StorageType.Integer:
                    storage = "Integer"
                elif st == StorageType.Double:
                    storage = "Double"
                elif st == StorageType.ElementId:
                    storage = "ElementId"
                else:
                    continue
                found = True
            except Exception:
                continue

            try:
                spec = p.Definition.GetDataType()
            except Exception:
                spec = None

            if storage == "Integer":
                try:
                    from Autodesk.Revit.DB import SpecTypeId
                    if spec is not None and spec == SpecTypeId.Boolean.YesNo:
                        yesno = True
                except Exception:
                    pass
            break

        result = (storage, spec if found else None, yesno)
        self.cache[key] = result
        return result

    def id_values(self, pid, limit=400):
        """[(ElementId, name)] of the values elements actually hold."""
        seen = {}
        key = eid_value(pid)
        for el in self.samples:
            p = _param_on(el, key)
            if p is None:
                continue
            try:
                if p.StorageType != StorageType.ElementId:
                    continue
                v = p.AsElementId()
                if v is None or eid_value(v) <= 0:
                    continue
                k = eid_value(v)
                if k in seen:
                    continue
                seen[k] = (v, element_name(self.doc, v, str(k)))
            except Exception:
                continue
            if len(seen) >= limit:
                break
        out = list(seen.values())
        try:
            out.sort(key=lambda x: x[1].lower())
        except Exception:
            pass
        return out


def _param_on(element, pid_value):
    try:
        for p in element.Parameters:
            if eid_value(p.Id) == pid_value:
                return p
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
#  Units - filter values for Double parameters are stored in internal units
# ---------------------------------------------------------------------------
def unit_id_for(doc, spec):
    if spec is None:
        return None
    try:
        if not UnitUtils.IsMeasurableSpec(spec):
            return None
    except Exception:
        pass
    try:
        return doc.GetUnits().GetFormatOptions(spec).GetUnitTypeId()
    except Exception:
        return None


def unit_label(doc, spec):
    uid = unit_id_for(doc, spec)
    if uid is None:
        return ""
    try:
        return LabelUtils.GetLabelForUnit(uid)
    except Exception:
        return ""


def to_display(doc, value, spec):
    uid = unit_id_for(doc, spec)
    if uid is None:
        return value
    try:
        return UnitUtils.ConvertFromInternalUnits(value, uid)
    except Exception:
        return value


def to_internal(doc, value, spec):
    uid = unit_id_for(doc, spec)
    if uid is None:
        return value
    try:
        return UnitUtils.ConvertToInternalUnits(value, uid)
    except Exception:
        return value


# ---------------------------------------------------------------------------
#  Reading rules off a filter
# ---------------------------------------------------------------------------
def read_filter(doc, pfe):
    """(match_mode, [rule dict]) where match_mode is 'AND' or 'OR'.

    A rule dict: {param_id, op, value, storage, spec, raw_ok}
    """
    ef = None
    try:
        ef = pfe.GetElementFilter()
    except Exception:
        ef = None

    match = "AND"
    collected = []

    if ef is not None:
        try:
            if isinstance(ef, LogicalOrFilter):
                match = "OR"
        except Exception:
            pass
        _walk_filter(ef, collected)
    else:
        # Revit 2018 and earlier route, kept as a fallback
        try:
            for r in pfe.GetRules():
                collected.append(r)
        except Exception:
            pass

    rules = []
    for r in collected:
        info = decode_rule(doc, r)
        if info is not None:
            rules.append(info)
    return match, rules


def _walk_filter(ef, out):
    try:
        if isinstance(ef, ElementParameterFilter):
            for r in ef.GetRules():
                out.append(r)
            return
    except Exception:
        pass
    try:
        if isinstance(ef, LogicalAndFilter) or isinstance(ef, LogicalOrFilter):
            for sub in ef.GetFilters():
                _walk_filter(sub, out)
            return
    except Exception:
        pass


_EVAL_MAP = [
    ("GreaterOrEqual", "greater_equal"),
    ("LessOrEqual", "less_equal"),
    ("BeginsWith", "begins"),
    ("EndsWith", "ends"),
    ("Contains", "contains"),
    ("Greater", "greater"),
    ("Less", "less"),
    ("Equals", "equals"),
]

_NEGATE = {
    "equals": "not_equals",
    "contains": "not_contains",
    "begins": "not_begins",
    "ends": "not_ends",
    "greater": "less_equal",
    "greater_equal": "less",
    "less": "greater_equal",
    "less_equal": "greater",
}


def decode_rule(doc, rule):
    """Turn a FilterRule into a plain dict the window can edit."""
    inverted = False
    inner = rule
    try:
        name = type(rule).__name__
        if "InverseRule" in name:
            inverted = True
            inner = rule.GetInnerRule()
    except Exception:
        pass

    cls = ""
    try:
        cls = type(inner).__name__
    except Exception:
        pass

    pid = None
    try:
        pid = inner.GetRuleParameter()
    except Exception:
        pid = None
    if pid is None:
        return None

    # has value / has no value
    if "HasNoValue" in cls:
        return _rule_dict(pid, "has_value" if inverted else "has_no_value", "", "String", None)
    if "HasValue" in cls:
        return _rule_dict(pid, "has_no_value" if inverted else "has_value", "", "String", None)

    op = "equals"
    try:
        ev = type(inner.GetEvaluator()).__name__
        for token, key in _EVAL_MAP:
            if token in ev:
                op = key
                break
    except Exception:
        pass

    if inverted:
        op = _NEGATE.get(op, op)

    value = ""
    storage = "String"
    spec = None

    try:
        if "StringRule" in cls:
            storage = "String"
            value = _string_value(inner)
        elif "DoubleRule" in cls:
            storage = "Double"
            value = inner.RuleValue
        elif "IntegerRule" in cls:
            storage = "Integer"
            value = inner.RuleValue
        elif "ElementIdRule" in cls:
            storage = "ElementId"
            value = inner.RuleValue
        elif "GlobalParameterAssociation" in cls:
            storage = "String"
            value = ""
        else:
            storage = "String"
            value = _string_value(inner)
    except Exception:
        pass

    return _rule_dict(pid, op, value, storage, spec)


def _string_value(rule):
    for attr in ("RuleString", "RuleValue"):
        try:
            v = getattr(rule, attr)
            if v is not None:
                return v
        except Exception:
            continue
    return ""


def _rule_dict(pid, op, value, storage, spec):
    return {
        "param_id": pid,
        "op": op,
        "value": value,
        "storage": storage,
        "spec": spec,
    }


# ---------------------------------------------------------------------------
#  Building rules
# ---------------------------------------------------------------------------
def build_rule(doc, pid, op, raw_value, storage, spec, yesno=False):
    """A FilterRule, or raises with a readable message."""
    factory = OP_FACTORY.get(op)
    if factory is None:
        raise ValueError("Unknown operator '{0}'".format(op))

    method = getattr(ParameterFilterRuleFactory, factory, None)
    if method is None:
        raise ValueError("This Revit release has no {0}".format(factory))

    if not OP_NEEDS_VALUE.get(op, True):
        return method(pid)

    if storage == "String":
        text = raw_value if raw_value is not None else ""
        try:
            return method(pid, text)
        except Exception:
            # Revit 2021 string overloads take a caseSensitive flag
            return method(pid, text, True)

    if storage == "Integer":
        if yesno:
            text = str(raw_value).strip().lower()
            num = 1 if text in ("1", "yes", "true", "y") else 0
        else:
            num = int(round(float(str(raw_value).strip())))
        return method(pid, num)

    if storage == "Double":
        display = float(str(raw_value).strip())
        internal = to_internal(doc, display, spec)
        try:
            return method(pid, internal, DOUBLE_EPSILON)
        except Exception:
            return method(pid, internal)

    if storage == "ElementId":
        if op in ID_TEXT_OPS:
            # a text match against the element's name
            text = u"" if raw_value is None else u"{0}".format(raw_value)
            try:
                return method(pid, text)
            except Exception:
                return method(pid, text, True)

        if isinstance(raw_value, ElementId):
            return method(pid, raw_value)
        try:
            return method(pid, ElementId(int(str(raw_value).strip())))
        except Exception:
            pass
        # equals against a name Revit will not take: say so rather than
        # writing the wrong rule
        raise ValueError(
            "'{0}' is an element, so equals needs one of its values, not "
            "free text. Use contains for a text match.".format(raw_value))

    raise ValueError("Unsupported storage type '{0}'".format(storage))


def build_element_filter(rules, match_mode):
    """An ElementFilter from FilterRule objects."""
    if not rules:
        return None

    from Autodesk.Revit.DB import ElementFilter, FilterRule

    if match_mode == "OR":
        subs = List[ElementFilter]()
        for r in rules:
            subs.Add(ElementParameterFilter(r))
        return LogicalOrFilter(subs)

    lst = List[FilterRule]()
    for r in rules:
        lst.Add(r)
    return ElementParameterFilter(lst)


# ---------------------------------------------------------------------------
#  Writing
# ---------------------------------------------------------------------------
def apply_filter(doc, pfe, name, category_ids, rules, match_mode):
    """Write name, categories and rules onto an existing filter.

    Must be called inside a transaction. Returns a list of note strings.
    """
    notes = []

    if name:
        try:
            if pfe.Name != name:
                pfe.Name = name
        except Exception as ex:
            notes.append("Name not changed: {0}".format(ex))

    if category_ids:
        try:
            ids = List[ElementId]()
            for c in category_ids:
                ids.Add(c)
            pfe.SetCategories(ids)
        except Exception as ex:
            notes.append("Categories not changed: {0}".format(ex))

    ef = build_element_filter(rules, match_mode)
    try:
        if ef is None:
            pfe.SetElementFilter(_empty_filter())
            notes.append("No rules - the filter now matches every element "
                         "of its categories.")
        else:
            pfe.SetElementFilter(ef)
    except Exception as ex:
        notes.append("Rules not written: {0}".format(ex))

    return notes


def _empty_filter():
    from Autodesk.Revit.DB import FilterRule, ElementParameterFilter
    return ElementParameterFilter(List[FilterRule]())


def create_filter(doc, name, category_ids, rules=None, match_mode="AND"):
    """A new ParameterFilterElement. Must be inside a transaction."""
    ids = List[ElementId]()
    for c in category_ids:
        ids.Add(c)

    ef = build_element_filter(rules or [], match_mode)
    if ef is not None:
        try:
            return ParameterFilterElement.Create(doc, name, ids, ef)
        except Exception:
            pass
    return ParameterFilterElement.Create(doc, name, ids)


def _looks_like_id(target):
    """An ElementId, or anything shaped like one.

    Checked by shape rather than by type: a stub, or an id class from a
    different loaded copy of the API, is still an id, and treating one as an
    element gives a name of "(unnamed)" with no clue why.
    """
    if isinstance(target, ElementId):
        return True
    if hasattr(target, "Name"):
        return False
    return hasattr(target, "Value") or hasattr(target, "IntegerValue")


def element_name(doc, target, fallback=None):
    """A display name for an element or an element id, whatever it is.

    Element.Name is not implemented for every class in the Revit API, and
    where it is not it raises rather than returning nothing. Anything that
    puts a user's model data on screen has to survive that.
    """
    element = target
    try:
        if _looks_like_id(target):
            if eid_value(target) <= 0:
                return fallback if fallback is not None else ""
            element = doc.GetElement(target)
    except Exception:
        element = None

    if element is None:
        return fallback if fallback is not None else ""

    try:
        name = element.Name
        if name:
            return name
    except Exception:
        pass

    for route in ("FamilyName", "Title"):
        try:
            value = getattr(element, route)
            if value:
                return value
        except Exception:
            continue

    try:
        from Autodesk.Revit.DB import Element
        value = Element.Name.GetValue(element)
        if value:
            return value
    except Exception:
        pass

    if fallback is not None:
        return fallback
    try:
        return "id {0}".format(eid_value(element.Id))
    except Exception:
        return "(unnamed)"


def duplicate_filter(doc, source, new_name):
    """A copy of a filter under a new name. Must be inside a transaction.

    ParameterFilterElement has no Duplicate, so the copy is created from the
    source's own categories and element filter.
    """
    ids = List[ElementId]()
    for cid in source.GetCategories():
        ids.Add(cid)

    element_filter = None
    try:
        element_filter = source.GetElementFilter()
    except Exception:
        element_filter = None

    if element_filter is not None:
        try:
            return ParameterFilterElement.Create(doc, new_name, ids,
                                                 element_filter)
        except Exception:
            pass
    return ParameterFilterElement.Create(doc, new_name, ids)


def rename_filter(doc, pfe, new_name):
    """Rename, then read it back.

    Which route works varies with the IronPython version and neither
    reliably raises on failure, so the only way to know is to look.
    """
    from Autodesk.Revit.DB import Element
    try:
        pfe.Name = new_name
    except Exception:
        pass
    try:
        if pfe.Name == new_name:
            return True
    except Exception:
        pass
    try:
        Element.Name.SetValue(pfe, new_name)
    except Exception:
        pass
    try:
        return pfe.Name == new_name
    except Exception:
        return False


def delete_filter(doc, pfe):
    doc.Delete(pfe.Id)


def unique_filter_name(doc, base):
    taken = set()
    for f in get_all_filters(doc):
        try:
            taken.add(f.Name.lower())
        except Exception:
            pass
    if base.lower() not in taken:
        return base
    n = 2
    while True:
        candidate = "{0} {1}".format(base, n)
        if candidate.lower() not in taken:
            return candidate
        n += 1


# ---------------------------------------------------------------------------
#  Filter Pusher support
# ---------------------------------------------------------------------------
def supports_filters(view):
    try:
        return view.AreGraphicsOverridesAllowed()
    except Exception:
        return False


def get_view_templates(doc):
    templates = []
    for v in FilteredElementCollector(doc).OfClass(View):
        try:
            if v.IsTemplate and supports_filters(v):
                templates.append(v)
        except Exception:
            continue
    try:
        templates.sort(key=lambda x: x.Name.lower())
    except Exception:
        pass
    return templates


# ---------------------------------------------------------------------------
#  Target views - every ordinary (non-template) view that can carry filters
# ---------------------------------------------------------------------------
# ViewType names as Revit's own browser words them. Anything not listed is
# split out of its CamelCase name, so a new view type still gets a label.
VIEW_KIND_LABELS = {
    "FloorPlan": "Floor Plan",
    "CeilingPlan": "Ceiling Plan",
    "EngineeringPlan": "Structural Plan",
    "AreaPlan": "Area Plan",
    "ThreeD": "3D View",
    "Section": "Section",
    "Elevation": "Elevation",
    "Detail": "Detail View",
    "DraftingView": "Drafting View",
    "Legend": "Legend",
    "Walkthrough": "Walkthrough",
    "Rendering": "Rendering",
}

# never push targets, even where AreGraphicsOverridesAllowed says yes
NOT_TARGET_KINDS = ("DrawingSheet", "Schedule", "PanelSchedule",
                    "ColumnSchedule", "ProjectBrowser", "SystemBrowser",
                    "Internal", "Undefined", "Report", "CostReport",
                    "LoadsReport", "PresureLossReport", "SystemsAnalysisReport")


def view_kind(view):
    """'Floor Plan', '3D View', 'Section' ... for a view's ViewType."""
    try:
        raw = str(view.ViewType)
    except Exception:
        return "Other"
    raw = raw.split(".")[-1]
    if raw in VIEW_KIND_LABELS:
        return VIEW_KIND_LABELS[raw]
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", raw) or "Other"


def _filters_param_value():
    from Autodesk.Revit.DB import BuiltInParameter
    return eid_value(ElementId(BuiltInParameter.VIS_GRAPHICS_FILTERS))


def template_controls_filters(template, filters_param=None):
    """True when this template drives V/G Filters on the views it is applied to."""
    if template is None:
        return False
    try:
        target = filters_param if filters_param is not None \
            else _filters_param_value()
        for e in template.GetNonControlledTemplateParameterIds():
            if eid_value(e) == target:
                return False
        return True
    except Exception:
        return False


def view_filter_lock(doc, view, cache=None, filters_param=None):
    """(template name, locked) for an ordinary view.

    A view whose template controls V/G Filters refuses AddFilter - the
    filters have to go onto the template instead. Templates themselves are
    never locked.
    """
    try:
        if view.IsTemplate:
            return "", False
        tid = view.ViewTemplateId
    except Exception:
        return "", False
    tval = eid_value(tid) if tid is not None else -1
    if tval <= 0:
        return "", False
    if cache is not None and tval in cache:
        return cache[tval]
    template = doc.GetElement(tid)
    result = (element_name(doc, template, "(template)"),
              template_controls_filters(template, filters_param))
    if cache is not None:
        cache[tval] = result
    return result


def target_label(view):
    """How a push target is written in the prompt and the log."""
    try:
        if view.IsTemplate:
            return view.Name
        return "{0}  ({1})".format(view.Name, view_kind(view))
    except Exception:
        return "(view)"


def type_name_of(doc, type_id):
    """The name of a type, e.g. 'Mechanical Plan' for a ViewFamilyType.

    element_name is no good here: ElementType.Name raises under some
    IronPython builds, and its next fallback, FamilyName, is the family -
    'Floor Plan' - which made every type read as its family in v3.26.0.
    """
    element = doc.GetElement(type_id)
    if element is None:
        return ""
    try:
        from Autodesk.Revit.DB import Element
        value = Element.Name.GetValue(element)
        if value:
            return value
    except Exception:
        pass
    try:
        from Autodesk.Revit.DB import BuiltInParameter
        for bip in ("ALL_MODEL_TYPE_NAME", "SYMBOL_NAME_PARAM"):
            try:
                param = element.get_Parameter(getattr(BuiltInParameter, bip))
                value = param.AsString() if param is not None else None
                if value:
                    return value
            except Exception:
                continue
    except Exception:
        pass
    try:
        value = element.Name
        if value:
            return value
    except Exception:
        pass
    return ""


def get_filterable_views(doc):
    """Every ordinary view that can take filters, as plain row dicts.

    Each row: id, idv, name, kind (Floor Plan, Section...), type (the view
    family type, e.g. 'Mechanical Plan'), template (name or ''), locked
    (True when that template controls filters, so the view cannot be
    written to directly).
    """
    rows = []
    type_names = {}
    locks = {}
    try:
        filters_param = _filters_param_value()
    except Exception:
        filters_param = None
    for v in FilteredElementCollector(doc).OfClass(View):
        try:
            if v.IsTemplate:
                continue
            if str(v.ViewType).split(".")[-1] in NOT_TARGET_KINDS:
                continue
            if not supports_filters(v):
                continue
            kind = view_kind(v)
            type_name = ""
            try:
                type_id = v.GetTypeId()
                tval = eid_value(type_id)
                if tval > 0:
                    if tval not in type_names:
                        type_names[tval] = type_name_of(doc, type_id)
                    type_name = type_names[tval]
            except Exception:
                type_name = ""
            template, locked = view_filter_lock(doc, v, locks, filters_param)
            rows.append({
                "id": v.Id,
                "idv": eid_value(v.Id),
                "name": element_name(doc, v, "(view)"),
                "kind": kind,
                "type": type_name or kind,
                "template": template,
                "locked": bool(locked),
            })
        except Exception:
            continue
    rows.sort(key=lambda r: (r["kind"].lower(), r["name"].lower()))
    return rows


def template_filter_counts(doc, templates):
    """{template id value: how many filters it carries}.

    Worked out once for the whole list, because doing it per row meant a
    GetFilters call for every template on every keystroke in the search box.
    """
    counts = {}
    for view in templates or []:
        try:
            counts[eid_value(view.Id)] = len(view.GetFilters())
        except Exception:
            counts[eid_value(view.Id)] = 0
    return counts


def get_template_filters(doc, view):
    result = []
    try:
        for fid in view.GetFilters():
            fel = doc.GetElement(fid)
            if fel is not None:
                try:
                    result.append((fid, fel.Name))
                except Exception:
                    continue
    except Exception:
        pass
    try:
        result.sort(key=lambda x: x[1].lower())
    except Exception:
        pass
    return result


# ---------------------------------------------------------------------------
#  Renaming and duplicating
# ---------------------------------------------------------------------------
PARK_PREFIX = "__RevoBIM_parked_"


def set_element_name(element, name):
    """Rename an element and prove it took.

    Which route works varies with the IronPython version and neither
    reliably raises on failure, so the name is read back afterwards.
    """
    try:
        element.Name = name
    except Exception:
        pass
    try:
        if element.Name == name:
            return True
    except Exception:
        pass
    try:
        from Autodesk.Revit.DB import Element
        Element.Name.SetValue(element, name)
    except Exception:
        pass
    try:
        return element.Name == name
    except Exception:
        return False


def suffixed_name(doc, base, existing=None):
    """'Thing' -> 'Thing (1)', then (2), then (3)."""
    taken = set()
    if existing is None:
        existing = [f.Name for f in get_all_filters(doc)]
    for name in existing:
        try:
            taken.add(name.lower())
        except Exception:
            continue

    stem = base
    match = re.match(r"^(.*?)\s*\((\d+)\)\s*$", base)
    if match:
        stem = match.group(1)

    index = 1
    while True:
        candidate = "{0} ({1})".format(stem, index)
        if candidate.lower() not in taken:
            return candidate
        index += 1


def duplicate_filter(doc, pfe, new_name):
    """A copy carrying the same categories and the same rules.

    Must be called inside a transaction.
    """
    ids = List[ElementId]()
    for cid in filter_category_ids(pfe):
        ids.Add(cid)

    element_filter = None
    try:
        element_filter = pfe.GetElementFilter()
    except Exception:
        element_filter = None

    if element_filter is not None:
        try:
            return ParameterFilterElement.Create(doc, new_name, ids,
                                                 element_filter)
        except Exception:
            pass

    copy = ParameterFilterElement.Create(doc, new_name, ids)
    if element_filter is not None:
        try:
            copy.SetElementFilter(element_filter)
        except Exception:
            pass
    return copy


def rename_preview(names, find="", replace="", prefix="", suffix="",
                   match_case=False, other_names=None):
    """[(old, new, problem)] for a batch rename, worked out before anything
    is written.

    Pure string work, so it can be tested on the bench without Revit.
    """
    other = set()
    for name in (other_names or []):
        try:
            other.add(name.lower())
        except Exception:
            continue

    rows = []
    seen = {}
    for old in names:
        new = old
        if find:
            if match_case:
                new = new.replace(find, replace)
            else:
                new = re.sub(re.escape(find), lambda _m: replace, new,
                             flags=re.IGNORECASE)
        new = "{0}{1}{2}".format(prefix, new, suffix)

        problem = ""
        if not new.strip():
            problem = "would leave no name"
        elif new.lower() in other:
            problem = "clashes with another filter in the project"
        elif new.lower() in seen and seen[new.lower()] != old:
            problem = "two filters would end up with this name"

        if not problem:
            seen[new.lower()] = old
        rows.append((old, new, problem))
    return rows


def apply_renames(doc, pairs):
    """Rename in two passes through a parked name.

    Swapping two names round, or shuffling a set along by one, fails on a
    clash with itself if each is written straight to its final name.
    Must be called inside a transaction.
    """
    done = []
    failed = []

    for index, (element, _new) in enumerate(pairs):
        if not set_element_name(element, "{0}{1}".format(PARK_PREFIX, index)):
            failed.append((element, "could not be parked"))

    for element, new_name in pairs:
        if set_element_name(element, new_name):
            done.append(new_name)
        else:
            failed.append((element, "would not take the name '{0}'".format(
                new_name)))
    return done, failed
