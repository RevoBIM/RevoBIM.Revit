# -*- coding: utf-8 -*-
"""RevoBIM PY - Workset Management : core.

Everything that reads or writes the Revit document, plus settings and saved
routines.  Written for IronPython 2.7 and IronPython 3, Revit 2024 - 2027:
no f-strings, no print statements, no bare ElementId.IntegerValue.
"""

import os
import re

from Autodesk.Revit import DB

__version__ = "1.0.0"

# ---------------------------------------------------------------- constants

APPDATA_DIR = os.path.join(os.getenv("APPDATA") or "", "RevoBIM")
SETTINGS_PATH = os.path.join(APPDATA_DIR, "workset_management.txt")
ROUTINE_DIR = os.path.join(APPDATA_DIR, "workset_routines")

SETTINGS_VERSION = "1"

NEW_ROW_PLACEHOLDER = "<type a new workset name here>"
NEW_ROW_COUNT = 10

DEFAULTS = {
    "settings_version": SETTINGS_VERSION,
    "new_rows": "10",
    "show_results": "needed",          # needed | always | never
    "hide_empty_categories": "true",
    "subgroup_service_type": "true",
    "last_export_dir": "",
}

# keys reset when the meaning of a setting changes
MIGRATIONS = {}

# Categories that get a Service Type sub group under them.
SUBGROUP_BICS = ("OST_CableTray", "OST_CableTrayFitting")

SERVICE_PARAM_NAMES = ("Service Type", "BGL_Service Type", "Service")

NO_SERVICE = "(no service type)"


# ---------------------------------------------------------------- helpers

def eid_value(element_id):
    """ElementId -> int, across 2024 (.IntegerValue) and 2026+ (.Value)."""
    if element_id is None:
        return 0
    try:
        return int(element_id.Value)
    except Exception:
        pass
    try:
        return int(element_id.IntegerValue)
    except Exception:
        return 0


def wsid_value(workset_id):
    """WorksetId -> int.  WorksetId is not an ElementId; try both members."""
    if workset_id is None:
        return -1
    try:
        return int(workset_id.IntegerValue)
    except Exception:
        pass
    try:
        return int(workset_id.Value)
    except Exception:
        return -1


def safe_str(value):
    if value is None:
        return ""
    try:
        return u"{0}".format(value)
    except Exception:
        try:
            return str(value)
        except Exception:
            return ""


def _ensure_dir(path):
    try:
        if path and not os.path.isdir(path):
            os.makedirs(path)
    except Exception:
        pass


def _read_lines(path):
    lines = []
    try:
        try:
            import io
            handle = io.open(path, "r", encoding="utf-8-sig")
        except Exception:
            handle = open(path, "r")
        try:
            for line in handle:
                lines.append(safe_str(line).rstrip("\r\n"))
        finally:
            handle.close()
    except Exception:
        return []
    return lines


def _write_lines(path, lines):
    _ensure_dir(os.path.dirname(path))
    body = u"\n".join([safe_str(x) for x in lines]) + u"\n"
    try:
        import io
        handle = io.open(path, "w", encoding="utf-8")
        try:
            handle.write(body)
        finally:
            handle.close()
        return True
    except Exception:
        pass
    try:
        handle = open(path, "w")
        try:
            handle.write(body.encode("utf-8"))
        finally:
            handle.close()
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- settings

def load_settings():
    """Plain key=value under %APPDATA%\\RevoBIM.  Missing or damaged keys fall
    back to the default one at a time; unknown keys are ignored."""
    values = {}
    for key in DEFAULTS:
        values[key] = DEFAULTS[key]

    for line in _read_lines(SETTINGS_PATH):
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        parts = text.split("=", 1)
        key = parts[0].strip()
        if key in DEFAULTS:
            values[key] = parts[1].strip()

    stored = values.get("settings_version", "")
    if stored != SETTINGS_VERSION:
        for version in MIGRATIONS:
            for key in MIGRATIONS[version]:
                values[key] = DEFAULTS.get(key, "")
        values["settings_version"] = SETTINGS_VERSION
    return values


def save_settings(values):
    lines = ["# RevoBIM PY - Workset Management settings"]
    for key in sorted(DEFAULTS.keys()):
        lines.append("{0} = {1}".format(key, safe_str(values.get(key, DEFAULTS[key]))))
    return _write_lines(SETTINGS_PATH, lines)


def as_bool(value, fallback=False):
    text = safe_str(value).strip().lower()
    if text in ("true", "1", "yes", "on"):
        return True
    if text in ("false", "0", "no", "off"):
        return False
    return fallback


# ---------------------------------------------------------------- worksets

class WorksetInfo(object):
    def __init__(self, workset):
        self.workset = workset
        self.name = safe_str(workset.Name)
        self.ws_id = workset.Id
        self.id_int = wsid_value(workset.Id)
        self.is_open = True
        self.is_editable = True
        try:
            self.is_open = bool(workset.IsOpen)
        except Exception:
            pass
        try:
            self.is_editable = bool(workset.IsEditable)
        except Exception:
            pass
        self.count = 0


def read_worksets(doc):
    """Every user workset in the document, sorted by name."""
    result = []
    if doc is None:
        return result
    try:
        if not doc.IsWorkshared:
            return result
    except Exception:
        return result
    try:
        collector = DB.FilteredWorksetCollector(doc)
        collector = collector.OfKind(DB.WorksetKind.UserWorkset)
        for workset in collector:
            result.append(WorksetInfo(workset))
    except Exception:
        return result
    result.sort(key=lambda item: item.name.lower())
    return result


def workset_name_exists(worksets, name):
    target = safe_str(name).strip().lower()
    for info in worksets:
        if info.name.strip().lower() == target:
            return True
    return False


# ---------------------------------------------------------------- model scan

def _builtin_category_id(name):
    try:
        bic = getattr(DB.BuiltInCategory, name)
    except Exception:
        return None
    try:
        return DB.ElementId(bic)
    except Exception:
        return None


def _subgroup_category_ints():
    values = []
    for name in SUBGROUP_BICS:
        cat_id = _builtin_category_id(name)
        if cat_id is not None:
            values.append(eid_value(cat_id))
    return values


def service_type_of(element, doc, cache=None):
    """Service Type as the model spells it, instance first then type.

    The type level answer is cached by type id - a tray run is thousands of
    elements sharing a handful of types, and the lookup is the slow part of
    the model scan.
    """
    for name in SERVICE_PARAM_NAMES:
        try:
            param = element.LookupParameter(name)
        except Exception:
            param = None
        text = _param_text(param)
        if text:
            return text

    type_id_int = 0
    try:
        type_id_int = eid_value(element.GetTypeId())
    except Exception:
        type_id_int = 0
    if cache is not None and type_id_int in cache:
        return cache[type_id_int]

    type_element = None
    try:
        type_element = doc.GetElement(element.GetTypeId())
    except Exception:
        type_element = None
    if type_element is not None:
        for name in SERVICE_PARAM_NAMES:
            try:
                param = type_element.LookupParameter(name)
            except Exception:
                param = None
            text = _param_text(param)
            if text:
                if cache is not None:
                    cache[type_id_int] = text
                return text

    for bip_name in ("RBS_CTC_SERVICE_TYPE", "RBS_CTC_SERVICE_TYPE_PARAM"):
        try:
            bip = getattr(DB.BuiltInParameter, bip_name)
        except Exception:
            continue
        try:
            text = _param_text(element.get_Parameter(bip))
            if text:
                return text
        except Exception:
            pass
        if type_element is not None:
            try:
                text = _param_text(type_element.get_Parameter(bip))
                if text:
                    if cache is not None:
                        cache[type_id_int] = text
                    return text
            except Exception:
                pass
    if cache is not None:
        cache[type_id_int] = NO_SERVICE
    return NO_SERVICE


def _param_text(param):
    if param is None:
        return ""
    try:
        if param.StorageType == DB.StorageType.String:
            return safe_str(param.AsString()).strip()
    except Exception:
        pass
    try:
        return safe_str(param.AsValueString()).strip()
    except Exception:
        return ""


class CategoryEntry(object):
    """One tickable line in a workset's category picker."""

    def __init__(self, key, label, count, parent_key=None):
        self.key = key
        self.label = label
        self.count = count
        self.parent_key = parent_key
        self.children = []
        self.element_ids = []


class ModelScan(object):
    def __init__(self):
        self.entries = []               # top level CategoryEntry, sorted
        self.by_key = {}                # key -> CategoryEntry
        self.workset_counts = {}        # workset int id -> element count
        self.total = 0
        self.error = ""


def scan_model(doc, hide_empty=True, subgroup_services=True):
    """One pass over the model.  Gives element counts per workset, the
    categories actually in use, and the elements behind each of them.

    ElementId objects are kept from this pass and reused at apply time - they
    are never rebuilt from integers.
    """
    scan = ModelScan()
    if doc is None:
        scan.error = "No document."
        return scan

    subgroup_ints = _subgroup_category_ints() if subgroup_services else []

    cat_names = {}
    cat_elements = {}
    svc_elements = {}
    service_cache = {}

    try:
        collector = DB.FilteredElementCollector(doc)
        collector = collector.WhereElementIsNotElementType()
        elements = list(collector)
    except Exception as err:
        scan.error = "Could not read the model: {0}".format(err)
        return scan

    for element in elements:
        # workset counts cover everything that sits on a workset
        try:
            ws_int = wsid_value(element.WorksetId)
        except Exception:
            ws_int = -1
        if ws_int >= 0:
            scan.workset_counts[ws_int] = scan.workset_counts.get(ws_int, 0) + 1

        # only model, non view specific elements can be reassigned
        try:
            if element.ViewSpecific:
                continue
        except Exception:
            pass
        try:
            category = element.Category
        except Exception:
            category = None
        if category is None:
            continue
        try:
            if category.CategoryType != DB.CategoryType.Model:
                continue
        except Exception:
            continue

        cat_int = eid_value(category.Id)
        if cat_int == 0:
            continue
        if cat_int not in cat_names:
            cat_names[cat_int] = safe_str(category.Name)
            cat_elements[cat_int] = []
        cat_elements[cat_int].append(element.Id)
        scan.total += 1

        if cat_int in subgroup_ints:
            service = service_type_of(element, doc, service_cache)
            if not service:
                service = NO_SERVICE
            svc_key = (cat_int, service)
            if svc_key not in svc_elements:
                svc_elements[svc_key] = []
            svc_elements[svc_key].append(element.Id)

    for cat_int in cat_names:
        ids = cat_elements.get(cat_int, [])
        if hide_empty and not ids:
            continue
        key = "cat:{0}".format(cat_int)
        entry = CategoryEntry(key, cat_names[cat_int], len(ids))
        entry.element_ids = ids
        scan.entries.append(entry)
        scan.by_key[key] = entry

        if cat_int in subgroup_ints:
            services = []
            for svc_key in svc_elements:
                if svc_key[0] == cat_int:
                    services.append(svc_key[1])
            services.sort(key=lambda text: text.lower())
            for service in services:
                child_ids = svc_elements[(cat_int, service)]
                child_key = "svc:{0}:{1}".format(cat_int, service)
                child = CategoryEntry(child_key, service, len(child_ids), key)
                child.element_ids = child_ids
                entry.children.append(child)
                scan.by_key[child_key] = child

    scan.entries.sort(key=lambda item: item.label.lower())
    return scan


# ---------------------------------------------------------------- failures

class WarningSwallower(DB.IFailuresPreprocessor):
    def PreprocessFailures(self, accessor):
        try:
            accessor.DeleteAllWarnings()
        except Exception:
            pass
        return DB.FailureProcessingResult.Continue


def _quiet_transaction(doc, name):
    transaction = DB.Transaction(doc, name)
    try:
        options = transaction.GetFailureHandlingOptions()
        options.SetFailuresPreprocessor(WarningSwallower())
        options.SetClearAfterRollback(True)
        transaction.SetFailureHandlingOptions(options)
    except Exception:
        pass
    return transaction


# ---------------------------------------------------------------- changes

class WorksetChange(object):
    """A pending create or rename read out of the imported spreadsheet."""

    CREATE = "create"
    RENAME = "rename"

    def __init__(self, kind, new_name, old_name="", ws_id=None):
        self.kind = kind
        self.new_name = new_name
        self.old_name = old_name
        self.ws_id = ws_id
        self.note = ""


def apply_workset_changes(doc, changes):
    """Creates and renames, all inside one transaction."""
    done = []
    failed = []
    if not changes:
        return done, failed

    transaction = _quiet_transaction(doc, "RevoBIM - Workset changes")
    try:
        transaction.Start()
    except Exception as err:
        failed.append(("(transaction)", safe_str(err)))
        return done, failed

    try:
        for change in changes:
            try:
                if change.kind == WorksetChange.CREATE:
                    DB.Workset.Create(doc, change.new_name)
                    done.append("Created  {0}".format(change.new_name))
                else:
                    DB.WorksetTable.RenameWorkset(doc, change.ws_id, change.new_name)
                    done.append("Renamed  {0}  to  {1}".format(
                        change.old_name, change.new_name))
            except Exception as err:
                failed.append((change.new_name, safe_str(err)))
        transaction.Commit()
    except Exception as err:
        try:
            transaction.RollBack()
        except Exception:
            pass
        failed.append(("(commit)", safe_str(err)))
        return [], failed
    return done, failed


# ---------------------------------------------------------------- assigning

class AssignResult(object):
    def __init__(self):
        self.moved = 0
        self.already = 0
        self.locked = 0
        self.failed = 0
        self.lines = []
        self.error = ""


def apply_assignments(doc, plan):
    """plan : list of (workset name, WorksetId int, [ElementId, ...]).

    One transaction for the whole run, so a failure leaves nothing behind.
    """
    result = AssignResult()
    if not plan:
        return result

    try:
        partition = DB.BuiltInParameter.ELEM_PARTITION_PARAM
    except Exception:
        result.error = "ELEM_PARTITION_PARAM is not available on this release."
        return result

    transaction = _quiet_transaction(doc, "RevoBIM - Assign worksets")
    try:
        transaction.Start()
    except Exception as err:
        result.error = safe_str(err)
        return result

    try:
        for name, ws_int, element_ids in plan:
            moved = 0
            already = 0
            locked = 0
            failed = 0
            for element_id in element_ids:
                try:
                    element = doc.GetElement(element_id)
                except Exception:
                    element = None
                if element is None:
                    continue
                try:
                    if wsid_value(element.WorksetId) == ws_int:
                        already += 1
                        continue
                except Exception:
                    pass
                try:
                    param = element.get_Parameter(partition)
                except Exception:
                    param = None
                if param is None:
                    failed += 1
                    continue
                try:
                    if param.IsReadOnly:
                        locked += 1
                        continue
                except Exception:
                    pass
                try:
                    param.Set(ws_int)
                    moved += 1
                except Exception:
                    failed += 1

            result.moved += moved
            result.already += already
            result.locked += locked
            result.failed += failed
            if moved or locked or failed:
                result.lines.append(
                    "{0} : {1} moved, {2} already there, {3} not editable, "
                    "{4} refused".format(name, moved, already, locked, failed))
        transaction.Commit()
    except Exception as err:
        try:
            transaction.RollBack()
        except Exception:
            pass
        result.error = safe_str(err)
        result.moved = 0
    return result


# ---------------------------------------------------------------- routines

def _project_key(doc):
    name = ""
    try:
        name = os.path.basename(safe_str(doc.Title))
    except Exception:
        name = ""
    if not name:
        name = "project"
    name = re.sub(r"[^A-Za-z0-9_\-. ]+", "_", name)
    return name.strip() or "project"


def routine_path(doc):
    return os.path.join(ROUTINE_DIR, _project_key(doc) + ".txt")


def _clean_token(text):
    return safe_str(text).replace("|", "/").replace("=", "-").strip()


def load_routines(doc):
    """name -> {workset name : [entry key, ...]}"""
    routines = {}
    for line in _read_lines(routine_path(doc)):
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        left, right = text.split("=", 1)
        parts = left.strip().split("|")
        if len(parts) != 3 or parts[0] != "routine":
            continue
        routine_name = parts[1].strip()
        workset_name = parts[2].strip()
        keys = [k.strip() for k in right.strip().split(";") if k.strip()]
        if routine_name not in routines:
            routines[routine_name] = {}
        routines[routine_name][workset_name] = keys
    return routines


def save_routine(doc, routine_name, mapping):
    """mapping : workset name -> [entry key, ...].  Replaces a routine of the
    same name and leaves the others alone."""
    routine_name = _clean_token(routine_name)
    if not routine_name:
        return False
    routines = load_routines(doc)
    routines[routine_name] = {}
    for workset_name in mapping:
        keys = mapping[workset_name]
        if keys:
            routines[routine_name][_clean_token(workset_name)] = list(keys)

    lines = ["# RevoBIM PY - Workset Management saved routines"]
    for name in sorted(routines.keys()):
        block = routines[name]
        for workset_name in sorted(block.keys()):
            lines.append("routine|{0}|{1} = {2}".format(
                name, workset_name, ";".join(block[workset_name])))
    return _write_lines(routine_path(doc), lines)


def delete_routine(doc, routine_name):
    routines = load_routines(doc)
    if routine_name in routines:
        del routines[routine_name]
    lines = ["# RevoBIM PY - Workset Management saved routines"]
    for name in sorted(routines.keys()):
        block = routines[name]
        for workset_name in sorted(block.keys()):
            lines.append("routine|{0}|{1} = {2}".format(
                name, workset_name, ";".join(block[workset_name])))
    return _write_lines(routine_path(doc), lines)
