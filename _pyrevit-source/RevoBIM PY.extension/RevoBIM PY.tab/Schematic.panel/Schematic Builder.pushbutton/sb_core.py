# -*- coding: utf-8 -*-
"""Schematic Builder - Revit-bound helpers shared by the other modules."""
import sb_clr  # noqa: F401  (assembly references, must be first)

import os
import datetime
import traceback

from sb_logic import as_text, TOOL_NAME, __version__, SETTINGS_DIR  # noqa: F401

from Autodesk.Revit.DB import (  # noqa: E402
    ElementId, UnitUtils, UnitTypeId, Element, StorageType, BuiltInParameter,
    BuiltInCategory, IFailuresPreprocessor, FailureSeverity, FailureProcessingResult,
)

LOG_FILE = os.path.join(SETTINGS_DIR, "schematic_builder.log")
ERROR_FILE = os.path.join(SETTINGS_DIR, "sb_last_error.txt")


# ---------------------------------------------------------------------------
# IDS AND UNITS
# ---------------------------------------------------------------------------

def eid_value(element_id):
    """ElementId -> int, preferring .Value (2024+) over .IntegerValue (gone in 2026)."""
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


def make_id(value):
    try:
        return ElementId(long(value))  # noqa: F821  (IronPython 2.7: Int64 overload)
    except Exception:
        return ElementId(int(value))


def bic(name):
    """BuiltInCategory looked up at call time, never at import."""
    try:
        return getattr(BuiltInCategory, name)
    except Exception:
        return None


def bip(name):
    try:
        return getattr(BuiltInParameter, name)
    except Exception:
        return None


def mm_to_ft(mm):
    return UnitUtils.ConvertToInternalUnits(float(mm), UnitTypeId.Millimeters)


def ft_to_mm(ft):
    return UnitUtils.ConvertFromInternalUnits(float(ft), UnitTypeId.Millimeters)


def el_name(element):
    if element is None:
        return u""
    try:
        return as_text(Element.Name.GetValue(element))
    except Exception:
        try:
            return as_text(element.Name)
        except Exception:
            return u""


def category_name(element):
    try:
        return as_text(element.Category.Name)
    except Exception:
        return u""


# ---------------------------------------------------------------------------
# PARAMETERS
# ---------------------------------------------------------------------------

def find_param(element, name, include_type=True):
    """Instance parameter by name, then the type's. GetParameters first, since
    LookupParameter can hand back the wrong one when names collide."""
    if element is None or not name:
        return None
    try:
        for param in element.GetParameters(name):
            return param
    except Exception:
        pass
    try:
        param = element.LookupParameter(name)
        if param is not None:
            return param
    except Exception:
        pass
    if include_type:
        try:
            type_id = element.GetTypeId()
            if eid_value(type_id) > 0:
                el_type = element.Document.GetElement(type_id)
                return find_param(el_type, name, False)
        except Exception:
            pass
    return None


def param_text(param):
    if param is None:
        return None
    try:
        if param.StorageType == StorageType.String:
            return as_text(param.AsString())
        if param.StorageType == StorageType.ElementId:
            target = param.Element.Document.GetElement(param.AsElementId())
            return el_name(target) if target is not None else u""
        value = param.AsValueString()
        if value is None:
            return as_text(param.AsString())
        return as_text(value)
    except Exception:
        return None


def builtin_text(element, bip_name):
    try:
        param = element.get_Parameter(bip(bip_name))
    except Exception:
        param = None
    return param_text(param)


def type_builtin_text(element, bip_name):
    try:
        el_type = element.Document.GetElement(element.GetTypeId())
        return builtin_text(el_type, bip_name)
    except Exception:
        return None


def set_param(param, value):
    """Write and read back; returns 'ok', 'read_only', 'bad_type' or 'failed'."""
    if param is None:
        return "failed"
    try:
        if param.IsReadOnly:
            return "read_only"
    except Exception:
        pass
    text = as_text(value)
    try:
        if param.StorageType == StorageType.String:
            param.Set(text)
            return "ok" if as_text(param.AsString()) == text else "failed"
        if param.StorageType == StorageType.Integer:
            param.Set(int(float(text)))
            return "ok"
        if param.StorageType == StorageType.Double:
            param.SetValueString(text)
            return "ok"
    except Exception:
        return "failed"
    return "bad_type"


# ---------------------------------------------------------------------------
# WARNINGS
# ---------------------------------------------------------------------------

class WarningSwallower(IFailuresPreprocessor):
    def PreprocessFailures(self, accessor):
        try:
            for failure in accessor.GetFailureMessages():
                if failure.GetSeverity() == FailureSeverity.Warning:
                    accessor.DeleteWarning(failure)
        except Exception:
            pass
        return FailureProcessingResult.Continue


def quiet_transaction(transaction):
    try:
        options = transaction.GetFailureHandlingOptions()
        options.SetFailuresPreprocessor(WarningSwallower())
        options.SetClearAfterRollback(True)
        transaction.SetFailureHandlingOptions(options)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# LOGGING
# ---------------------------------------------------------------------------

def _ensure_dir():
    try:
        if not os.path.isdir(SETTINGS_DIR):
            os.makedirs(SETTINGS_DIR)
    except Exception:
        pass


def log(message):
    _ensure_dir()
    try:
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        handle = open(LOG_FILE, "ab")
        handle.write((u"[{0}] {1}\n".format(stamp, as_text(message))).encode("utf-8"))
        handle.close()
    except Exception:
        pass


def write_error(stage, detail=None):
    """Write the traceback of the current exception; returns the text."""
    text = as_text(detail) if detail else as_text(traceback.format_exc())
    _ensure_dir()
    body = u"{0} v{1}\nstage: {2}\n{3}\n{4}".format(
        TOOL_NAME, __version__, stage, datetime.datetime.now().isoformat(), text)
    try:
        handle = open(ERROR_FILE, "wb")
        handle.write(body.encode("utf-8"))
        handle.close()
    except Exception:
        pass
    log(u"ERROR in {0}: {1}".format(stage, text.strip().splitlines()[-1] if text.strip() else u"?"))
    return body
