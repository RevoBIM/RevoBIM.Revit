# -*- coding: utf-8 -*-
"""Elevation Push -- RevoBIM PY

Pushes a source parameter into a target parameter on every element
matching any of the category + family-name rules below.

    Source parameter:     Elevation from Level
    Target parameter:     BGL_Elevation from Level

    Duct Accessories     | family name contains  Fire
    Duct Fittings        | family name contains  QFR
    Cable Tray Fittings  | family name contains  QFR
    Pipe Fittings        | family name contains  QFR

Edit the CONFIGURATION block to change the parameters, or add
another line to FILTER_RULES for another category.

Results are reported in a themed window, not the pyRevit output
window. SHOW_RESULTS decides when it appears.
"""

import os
import sys
import traceback

from pyrevit import revit, DB, script

__title__ = "Elevation Push"
__version__ = "1.3.0"

# ============================================================
# CONFIGURATION
# ============================================================

# Parameter to copy data FROM
SOURCE_PARAM_NAME = "Elevation from Level"

# Parameter to copy data TO
TARGET_PARAM_NAME = "BGL_Elevation from Level"

# Each rule = a category + a required substring in the family name
# (case sensitive). An element is included if it matches ANY rule.
FILTER_RULES = [
    {"category": DB.BuiltInCategory.OST_DuctAccessory,
     "label": "Duct Accessories", "family_contains": "Fire"},
    {"category": DB.BuiltInCategory.OST_DuctFitting,
     "label": "Duct Fittings", "family_contains": "QFR"},
    {"category": DB.BuiltInCategory.OST_CableTrayFitting,
     "label": "Cable Tray Fittings", "family_contains": "QFR"},
    {"category": DB.BuiltInCategory.OST_PipeFitting,
     "label": "Pipe Fittings", "family_contains": "QFR"},
]

# "always", "auto" (only when something needs a look), or "never"
SHOW_RESULTS = "always"

# ============================================================

HERE = os.path.dirname(__file__)
if HERE not in sys.path:
    sys.path.append(HERE)

doc = revit.doc


# ============================================================
# Revit 2024 - 2027 helpers
# ============================================================

def eid_value(element_id):
    """ElementId.IntegerValue was removed in Revit 2026 in favour of
    .Value (Int64). Prefer .Value and fall back."""
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


def get_family_name(element):
    """Return the Family name for a family instance, or None."""
    try:
        return element.Symbol.Family.Name
    except AttributeError:
        return None


def find_param(element, param_name):
    """Look up a parameter by name on the instance first, then fall
    back to the element's type, since some parameters live there."""
    param = element.LookupParameter(param_name)
    if param is not None:
        return param
    try:
        el_type = doc.GetElement(element.GetTypeId())
        if el_type is not None:
            return el_type.LookupParameter(param_name)
    except AttributeError:
        pass
    return None


def list_available_param_names(element):
    """All instance + type parameter names, for when a lookup fails."""
    names = set()
    for p in element.Parameters:
        names.add(p.Definition.Name)
    try:
        el_type = doc.GetElement(element.GetTypeId())
        if el_type is not None:
            for p in el_type.Parameters:
                names.add(p.Definition.Name)
    except AttributeError:
        pass
    return sorted(names)


def get_param_value(param):
    """Read a parameter's value based on its storage type."""
    if param is None:
        return None
    storage_type = param.StorageType
    if storage_type == DB.StorageType.String:
        return param.AsString()
    elif storage_type == DB.StorageType.Integer:
        return param.AsInteger()
    elif storage_type == DB.StorageType.Double:
        return param.AsDouble()
    elif storage_type == DB.StorageType.ElementId:
        return param.AsElementId()
    return None


def set_param_value(param, value):
    """Write a value into a parameter based on its storage type."""
    if param is None or param.IsReadOnly:
        return False
    storage_type = param.StorageType
    try:
        if storage_type == DB.StorageType.String:
            param.Set(value if value is not None else "")
        elif storage_type == DB.StorageType.Integer:
            param.Set(int(value) if value is not None else 0)
        elif storage_type == DB.StorageType.Double:
            param.Set(float(value) if value is not None else 0.0)
        elif storage_type == DB.StorageType.ElementId:
            param.Set(value)
        return True
    except Exception:
        return False


# ============================================================
# Collect
# ============================================================

matched = []
seen_ids = set()
rule_rows = []

for rule in FILTER_RULES:
    family_contains = rule["family_contains"]

    collector = DB.FilteredElementCollector(doc) \
        .OfCategory(rule["category"]) \
        .WhereElementIsNotElementType() \
        .ToElements()

    count = 0
    for el in collector:
        fam_name = get_family_name(el)
        if fam_name and family_contains in fam_name:
            count += 1
            key = eid_value(el.Id)
            if key not in seen_ids:
                seen_ids.add(key)
                matched.append(el)

    rule_rows.append((rule["label"], family_contains, count))


# ============================================================
# Push
# ============================================================

updated_count = 0
skipped = []
debug_names = None

if matched:
    with revit.Transaction("Elevation Push"):
        for el in matched:
            source_param = find_param(el, SOURCE_PARAM_NAME)
            target_param = find_param(el, TARGET_PARAM_NAME)

            if source_param is None or target_param is None:
                missing = []
                if source_param is None:
                    missing.append("source '{}'".format(SOURCE_PARAM_NAME))
                if target_param is None:
                    missing.append("target '{}'".format(TARGET_PARAM_NAME))
                skipped.append(
                    (eid_value(el.Id), "Missing " + " and ".join(missing)))
                if debug_names is None:
                    debug_names = (eid_value(el.Id),
                                   list_available_param_names(el))
                continue

            value = get_param_value(source_param)
            if set_param_value(target_param, value):
                updated_count += 1
            else:
                skipped.append(
                    (eid_value(el.Id),
                     "Target would not take the value "
                     "(read only or type mismatch)"))


# ============================================================
# Report
# ============================================================

def plain_report():
    """Fallback if the themed window will not load, so a run is never
    silent about what it did."""
    out = script.get_output()
    out.print_md("### Elevation Push")
    out.print_md("`{}` to `{}`".format(SOURCE_PARAM_NAME, TARGET_PARAM_NAME))
    for label, contains, count in rule_rows:
        out.print_md("- {} | contains \"{}\" | {}".format(
            label, contains, count))
    out.print_md("Matched {}, updated {}, skipped {}".format(
        len(matched), updated_count, len(skipped)))
    for eid, reason in skipped:
        out.print_md("- {}: {}".format(eid, reason))
    if debug_names is not None:
        eid, names = debug_names
        out.print_md("Parameters on element {}: {}".format(
            eid, ", ".join(names)))


def wants_window():
    if SHOW_RESULTS == "never":
        return False
    if SHOW_RESULTS == "always":
        return True
    return bool(skipped) or not matched


def revit_main_window():
    """Owning the window to Revit stops it slipping behind Revit.

    HOST_APP is pyRevit's own handle on the running Revit, so this
    needs no System.* import in a module that has referenced no
    assemblies, and no reliance on the injected __revit__ builtin."""
    try:
        from pyrevit import HOST_APP
        return HOST_APP.proc_window
    except Exception:
        return None


if wants_window():
    try:
        import elevation_push_results as report

        report.show_report(
            __version__, SOURCE_PARAM_NAME, TARGET_PARAM_NAME,
            rule_rows, len(matched), updated_count, skipped,
            debug_names, revit_main_window())
    except Exception:
        plain_report()
        script.get_output().print_md(
            "The themed results window could not be shown:\n\n```\n{}\n```"
            .format(traceback.format_exc()))
