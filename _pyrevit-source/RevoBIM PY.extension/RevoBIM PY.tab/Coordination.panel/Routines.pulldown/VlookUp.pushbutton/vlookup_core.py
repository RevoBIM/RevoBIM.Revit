# -*- coding: utf-8 -*-
"""RevoBIM VlookUp - the model side.

Scoping, parameter discovery, the match itself and the write pass, plus the
plain key=value settings and mapping profiles. Nothing in here touches WPF,
so it can be exercised on the bench.

Revit 2024 - 2027. No f-strings, no print statements, no bare .IntegerValue.
"""

import clr
import os
import re

for _asm in ('RevitAPI', 'RevitAPIUI'):
    try:
        clr.AddReference(_asm)
    except Exception:
        pass

from Autodesk.Revit import DB

__version__ = "1.0.1"

APPDATA_DIR = os.path.join(os.getenv('APPDATA') or '', 'RevoBIM')
SETTINGS_FILE = os.path.join(APPDATA_DIR, 'vlookup.txt')
PROFILE_DIR = os.path.join(APPDATA_DIR, 'vlookup_profiles')
SETTINGS_VERSION = 1

TYPE_PREFIX = u'Type: '
NONE_TARGET = u'\u2014 none \u2014'

SCOPE_SELECTION = 'selection'
SCOPE_VIEW = 'view'
SCOPE_MODEL = 'model'
SCOPE_LABELS = [(SCOPE_SELECTION, 'Current selection'),
                (SCOPE_VIEW, 'Active view'),
                (SCOPE_MODEL, 'Whole model')]

DUP_FIRST = 'first'
DUP_LAST = 'last'
DUP_SKIP = 'skip'
DUP_LABELS = [(DUP_FIRST, 'Use the first'),
              (DUP_LAST, 'Use the last'),
              (DUP_SKIP, 'Leave unmatched')]

PSEUDO_ELEMENT_ID = u'* Element ID'
PSEUDO_UNIQUE_ID = u'* Unique ID'
PSEUDO_FAMILY = u'* Family name'
PSEUDO_TYPE = u'* Type name'
PSEUDO_FAMILY_TYPE = u'* Family and type'
PSEUDO_CATEGORY = u'* Category'
PSEUDO_KEYS = [PSEUDO_ELEMENT_ID, PSEUDO_UNIQUE_ID, PSEUDO_FAMILY,
               PSEUDO_TYPE, PSEUDO_FAMILY_TYPE, PSEUDO_CATEGORY]

# how many elements are inspected when building the parameter lists
PARAM_SCAN_LIMIT = 3000

try:
    TEXT_TYPES = (str, unicode)          # noqa: F821  (IronPython 2.7)
except NameError:
    TEXT_TYPES = (str,)


# ------------------------------------------------------------------ basics

def eid_value(element_id):
    """ElementId.IntegerValue was dropped in Revit 2026; .Value replaced it."""
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


def as_text(value):
    if value is None:
        return u''
    if isinstance(value, TEXT_TYPES):
        return value
    try:
        return u'{0}'.format(value)
    except Exception:
        return u''


def element_name(element):
    try:
        name = element.Name
        if name:
            return as_text(name)
    except Exception:
        pass
    return u''


def describe(element):
    cat = u'?'
    try:
        if element.Category is not None:
            cat = as_text(element.Category.Name)
    except Exception:
        pass
    name = element_name(element)
    return u'{0} : {1} [{2}]'.format(cat, name or u'(unnamed)', eid_value(element.Id))


# ------------------------------------------------------------------ scoping

def collect_elements(doc, uidoc, scope):
    """Every model element in the chosen scope, element types excluded."""
    out = []
    if scope == SCOPE_SELECTION:
        try:
            for eid in uidoc.Selection.GetElementIds():
                element = doc.GetElement(eid)
                if element is not None:
                    out.append(element)
        except Exception:
            pass
        return out

    collector = None
    if scope == SCOPE_VIEW:
        view = doc.ActiveView
        if view is None:
            return out
        try:
            collector = DB.FilteredElementCollector(doc, view.Id)
        except Exception:
            collector = None
    if collector is None:
        collector = DB.FilteredElementCollector(doc)
    try:
        collector = collector.WhereElementIsNotElementType()
        for element in collector:
            if element is None:
                continue
            if element.Category is None:
                continue
            out.append(element)
    except Exception:
        pass
    return out


def category_names(elements):
    names = {}
    for element in elements:
        try:
            cat = element.Category
        except Exception:
            cat = None
        if cat is None:
            continue
        name = as_text(cat.Name)
        names[name] = names.get(name, 0) + 1
    return sorted(names.items(), key=lambda item: item[0].lower())


def filter_by_category(elements, wanted):
    if not wanted:
        return list(elements)
    lookup = set(wanted)
    out = []
    for element in elements:
        try:
            cat = element.Category
        except Exception:
            cat = None
        if cat is not None and as_text(cat.Name) in lookup:
            out.append(element)
    return out


# ------------------------------------------------------------------ parameters

def _definition_name(param):
    try:
        definition = param.Definition
        if definition is None:
            return None
        return as_text(definition.Name)
    except Exception:
        return None


def is_yes_no(param):
    try:
        return param.Definition.GetDataType() == DB.SpecTypeId.Boolean.YesNo
    except Exception:
        pass
    try:
        return as_text(param.Definition.ParameterType) == u'YesNo'
    except Exception:
        return False


def discover_parameters(doc, elements):
    """Return (key options, instance targets, type targets).

    Key options are anything readable; targets are anything writable. Scanning
    stops at PARAM_SCAN_LIMIT elements so a whole-model scope stays quick.
    """
    keys = set()
    inst_targets = set()
    type_targets = set()
    seen_types = set()
    scanned = 0

    for element in elements:
        if scanned >= PARAM_SCAN_LIMIT:
            break
        scanned += 1
        try:
            params = element.Parameters
        except Exception:
            params = []
        for param in params:
            name = _definition_name(param)
            if not name:
                continue
            keys.add(name)
            try:
                if not param.IsReadOnly:
                    inst_targets.add(name)
            except Exception:
                pass
        try:
            type_id = element.GetTypeId()
        except Exception:
            type_id = None
        if type_id is None or eid_value(type_id) <= 0:
            continue
        marker = eid_value(type_id)
        if marker in seen_types:
            continue
        seen_types.add(marker)
        symbol = doc.GetElement(type_id)
        if symbol is None:
            continue
        try:
            params = symbol.Parameters
        except Exception:
            params = []
        for param in params:
            name = _definition_name(param)
            if not name:
                continue
            keys.add(name)
            try:
                if not param.IsReadOnly:
                    type_targets.add(name)
            except Exception:
                pass

    key_list = list(PSEUDO_KEYS) + sorted(keys, key=lambda t: t.lower())
    return (key_list,
            sorted(inst_targets, key=lambda t: t.lower()),
            sorted(type_targets, key=lambda t: t.lower()),
            scanned)


def find_parameter(doc, element, name, include_type=True):
    """Instance parameter first, then the element's type."""
    param = None
    try:
        param = element.LookupParameter(name)
    except Exception:
        param = None
    if param is not None:
        return param
    if not include_type:
        return None
    try:
        symbol = doc.GetElement(element.GetTypeId())
    except Exception:
        symbol = None
    if symbol is None:
        return None
    try:
        return symbol.LookupParameter(name)
    except Exception:
        return None


def type_parameter(doc, element, name):
    try:
        symbol = doc.GetElement(element.GetTypeId())
    except Exception:
        symbol = None
    if symbol is None:
        return None, None
    try:
        return symbol, symbol.LookupParameter(name)
    except Exception:
        return symbol, None


def read_parameter_text(doc, param):
    if param is None:
        return None
    try:
        storage = param.StorageType
    except Exception:
        return None
    try:
        if storage == DB.StorageType.String:
            return as_text(param.AsString())
        if storage == DB.StorageType.Integer:
            if is_yes_no(param):
                return u'Yes' if param.AsInteger() else u'No'
            value = param.AsValueString()
            if value:
                return as_text(value)
            return as_text(param.AsInteger())
        if storage == DB.StorageType.Double:
            value = param.AsValueString()
            if value:
                return as_text(value)
            return as_text(param.AsDouble())
        if storage == DB.StorageType.ElementId:
            target = doc.GetElement(param.AsElementId())
            if target is not None:
                return element_name(target)
            return u''
    except Exception:
        return None
    return None


def read_key_text(doc, element, key_name):
    """The value the element is matched on, as text."""
    if key_name == PSEUDO_ELEMENT_ID:
        return as_text(eid_value(element.Id))
    if key_name == PSEUDO_UNIQUE_ID:
        try:
            return as_text(element.UniqueId)
        except Exception:
            return u''
    if key_name == PSEUDO_CATEGORY:
        try:
            return as_text(element.Category.Name) if element.Category else u''
        except Exception:
            return u''
    if key_name in (PSEUDO_FAMILY, PSEUDO_TYPE, PSEUDO_FAMILY_TYPE):
        family = u''
        type_name = u''
        try:
            symbol = doc.GetElement(element.GetTypeId())
        except Exception:
            symbol = None
        if symbol is not None:
            type_name = element_name(symbol)
            try:
                family_param = symbol.get_Parameter(DB.BuiltInParameter.ALL_MODEL_FAMILY_NAME)
                if family_param is not None:
                    family = as_text(family_param.AsString())
            except Exception:
                family = u''
            if not family:
                try:
                    family = as_text(symbol.FamilyName)
                except Exception:
                    family = u''
        if key_name == PSEUDO_FAMILY:
            return family
        if key_name == PSEUDO_TYPE:
            return type_name
        if family and type_name:
            return u'{0} : {1}'.format(family, type_name)
        return type_name or family
    param = find_parameter(doc, element, key_name, True)
    return read_parameter_text(doc, param)


# ------------------------------------------------------------------ matching

def normalise(text, ignore_case=True, trim=True, numeric=True):
    value = as_text(text)
    if trim:
        value = value.strip()
        value = re.sub(r'\s+', u' ', value)
    if numeric:
        probe = value.replace(u',', u'')
        try:
            number = float(probe)
            if abs(number - round(number)) < 1e-9:
                return u'#{0}'.format(int(round(number)))
            return u'#{0:.6f}'.format(number)
        except Exception:
            pass
    if ignore_case:
        value = value.lower()
    return value


class MatchOptions(object):
    def __init__(self):
        self.ignore_case = True
        self.trim = True
        self.numeric = True
        self.duplicates = DUP_FIRST
        self.skip_blanks = True


class Edit(object):
    __slots__ = ('element', 'key', 'row_number', 'writes')

    def __init__(self, element, key, row_number):
        self.element = element
        self.key = key
        self.row_number = row_number
        self.writes = []        # list of (target_string, text)


class MatchPlan(object):
    def __init__(self):
        self.edits = []
        self.no_key = []            # elements whose key parameter is blank/missing
        self.unmatched = []         # (description, key)
        self.duplicate_keys = []    # (key, count)
        self.unused_rows = 0
        self.row_count = 0
        self.matched_rows = 0
        self.scanned = 0
        self.value_count = 0
        self.notes = []

    @property
    def matched(self):
        return len(self.edits)


def build_index(rows, lookup_index, options):
    """key -> row, plus the keys that appeared more than once."""
    index = {}
    counts = {}
    for row in rows:
        if lookup_index >= len(row):
            continue
        raw = row[lookup_index]
        if raw is None or not as_text(raw).strip():
            continue
        key = normalise(raw, options.ignore_case, options.trim, options.numeric)
        counts[key] = counts.get(key, 0) + 1
        if key in index:
            if options.duplicates == DUP_LAST:
                index[key] = row
        else:
            index[key] = row
    duplicates = [(k, v) for k, v in counts.items() if v > 1]
    if options.duplicates == DUP_SKIP:
        for key, _count in duplicates:
            index.pop(key, None)
    duplicates.sort(key=lambda item: -item[1])
    return index, duplicates


def build_plan(doc, elements, key_name, rows, lookup_index, mapping, options):
    """Work out every write without touching the model.

    mapping: list of (column index, target string) - target as stored, i.e.
    "Comments" for an instance parameter or "Type: Comments" for a type one.
    """
    plan = MatchPlan()
    plan.row_count = len(rows)
    index, duplicates = build_index(rows, lookup_index, options)
    plan.duplicate_keys = duplicates[:40]
    used = {}

    for element in elements:
        plan.scanned += 1
        raw = read_key_text(doc, element, key_name)
        if raw is None or not as_text(raw).strip():
            plan.no_key.append(describe(element))
            continue
        key = normalise(raw, options.ignore_case, options.trim, options.numeric)
        row = index.get(key)
        if row is None:
            plan.unmatched.append((describe(element), as_text(raw).strip()))
            continue
        used[key] = True
        edit = Edit(element, as_text(raw).strip(), 0)
        for column_index, target in mapping:
            if column_index >= len(row):
                continue
            text = as_text(row[column_index])
            if options.skip_blanks and not text.strip():
                continue
            edit.writes.append((target, text))
        if edit.writes:
            plan.edits.append(edit)
            plan.value_count += len(edit.writes)
        else:
            plan.notes.append(u'{0} matched "{1}" but every mapped cell was blank.'
                              .format(describe(element), edit.key))
    plan.matched_rows = len(used)
    plan.unused_rows = max(0, len(index) - len(used))
    return plan


# ------------------------------------------------------------------ writing

def split_target(target):
    """'Type: Comments' -> ('Comments', True)."""
    text = as_text(target)
    if text.startswith(TYPE_PREFIX):
        return text[len(TYPE_PREFIX):], True
    return text, False


def join_target(name, is_type):
    if is_type:
        return TYPE_PREFIX + as_text(name)
    return as_text(name)


def _decimal_text(text):
    value = as_text(text).strip()
    if u',' in value and u'.' not in value:
        tail = value.split(u',')[-1]
        if 1 <= len(tail) <= 2 and tail.isdigit():
            value = value.replace(u',', u'.')
        else:
            value = value.replace(u',', u'')
    else:
        value = value.replace(u',', u'')
    return value


def _double_internal(param, text):
    try:
        raw = float(_decimal_text(text))
    except Exception:
        return None
    try:
        return DB.UnitUtils.ConvertToInternalUnits(raw, param.GetUnitTypeId())
    except Exception:
        pass
    return raw


class _IdResolver(object):
    """Lazily built name -> ElementId maps for ElementId parameters."""

    def __init__(self, doc):
        self.doc = doc
        self._maps = {}

    def _map(self, kind):
        if kind in self._maps:
            return self._maps[kind]
        table = {}
        try:
            if kind == 'material':
                collector = DB.FilteredElementCollector(self.doc).OfClass(DB.Material)
            elif kind == 'level':
                collector = DB.FilteredElementCollector(self.doc).OfClass(DB.Level)
            else:
                collector = DB.FilteredElementCollector(self.doc).WhereElementIsElementType()
            for element in collector:
                name = element_name(element)
                if name and name.lower() not in table:
                    table[name.lower()] = element.Id
        except Exception:
            pass
        self._maps[kind] = table
        return table

    def resolve(self, text):
        probe = as_text(text).strip().lower()
        if not probe:
            return None
        for kind in ('material', 'level', 'type'):
            table = self._map(kind)
            if probe in table:
                return table[probe]
        return None


def set_parameter(param, text, resolver):
    """Return (changed, error text or None)."""
    if param is None:
        return False, u'parameter not found'
    try:
        if param.IsReadOnly:
            return False, u'read-only here'
    except Exception:
        pass
    try:
        storage = param.StorageType
    except Exception:
        return False, u'no storage type'

    value = as_text(text)
    try:
        if storage == DB.StorageType.String:
            current = as_text(param.AsString())
            if current == value:
                return False, None
            param.Set(value)
            return True, None

        if storage == DB.StorageType.Integer:
            probe = value.strip().lower()
            if is_yes_no(param):
                if probe in (u'yes', u'y', u'true', u't', u'1', u'x'):
                    target = 1
                elif probe in (u'no', u'n', u'false', u'f', u'0', u''):
                    target = 0
                else:
                    return False, u'"{0}" is not yes/no'.format(value)
            else:
                try:
                    target = int(round(float(_decimal_text(value))))
                except Exception:
                    return False, u'"{0}" is not a whole number'.format(value)
            if param.AsInteger() == target:
                return False, None
            param.Set(target)
            return True, None

        if storage == DB.StorageType.Double:
            target = _double_internal(param, value)
            if target is None:
                try:
                    if param.AsValueString() == value:
                        return False, None
                except Exception:
                    pass
                try:
                    if param.SetValueString(value):
                        return True, None
                except Exception:
                    pass
                return False, u'"{0}" is not a number'.format(value)
            try:
                if abs(param.AsDouble() - target) < 1e-9:
                    return False, None
            except Exception:
                pass
            param.Set(target)
            return True, None

        if storage == DB.StorageType.ElementId:
            if not value.strip():
                if eid_value(param.AsElementId()) == eid_value(DB.ElementId.InvalidElementId):
                    return False, None
                param.Set(DB.ElementId.InvalidElementId)
                return True, None
            found = resolver.resolve(value)
            if found is None:
                return False, u'no element named "{0}"'.format(value)
            if eid_value(param.AsElementId()) == eid_value(found):
                return False, None
            param.Set(found)
            return True, None
    except Exception as err:
        return False, as_text(err)
    return False, u'unsupported parameter type'


class WarningSwallower(DB.IFailuresPreprocessor):
    def PreprocessFailures(self, accessor):
        try:
            accessor.DeleteAllWarnings()
        except Exception:
            pass
        return DB.FailureProcessingResult.Continue


class ApplyResult(object):
    def __init__(self):
        self.elements_changed = 0
        self.values_written = 0
        self.values_unchanged = 0
        self.failures = []          # (description, target, reason)
        self.type_writes = 0
        self.type_names = set()
        self.aborted = None


def apply_plan(doc, plan):
    """One transaction over the whole plan; a failure rolls the lot back."""
    result = ApplyResult()
    resolver = _IdResolver(doc)
    done_types = {}

    transaction = DB.Transaction(doc, 'RevoBIM VlookUp')
    options = transaction.GetFailureHandlingOptions()
    options.SetFailuresPreprocessor(WarningSwallower())
    options.SetClearAfterRollback(True)
    transaction.Start()
    try:
        transaction.SetFailureHandlingOptions(options)
        for edit in plan.edits:
            touched = False
            for target, text in edit.writes:
                name, is_type = split_target(target)
                if is_type:
                    symbol, param = type_parameter(doc, edit.element, name)
                    if symbol is None:
                        result.failures.append((describe(edit.element), target,
                                                u'the element has no type'))
                        continue
                    stamp = u'{0}|{1}'.format(eid_value(symbol.Id), name)
                    if done_types.get(stamp) == text:
                        continue
                    changed, error = set_parameter(param, text, resolver)
                    done_types[stamp] = text
                    if error:
                        result.failures.append((describe(edit.element), target, error))
                    elif changed:
                        result.values_written += 1
                        result.type_writes += 1
                        result.type_names.add(element_name(symbol) or u'(type)')
                        touched = True
                    else:
                        result.values_unchanged += 1
                    continue

                param = find_parameter(doc, edit.element, name, False)
                changed, error = set_parameter(param, text, resolver)
                if error:
                    result.failures.append((describe(edit.element), target, error))
                elif changed:
                    result.values_written += 1
                    touched = True
                else:
                    result.values_unchanged += 1
            if touched:
                result.elements_changed += 1
        transaction.Commit()
    except Exception as err:
        try:
            transaction.RollBack()
        except Exception:
            pass
        result.aborted = as_text(err)
    return result


# ------------------------------------------------------------------ settings

def _ensure_dir(path):
    try:
        if not os.path.isdir(path):
            os.makedirs(path)
    except Exception:
        pass


def _write_lines(path, lines):
    _ensure_dir(os.path.dirname(path))
    try:
        import io
        handle = io.open(path, 'w', encoding='utf-8')
    except Exception:
        handle = open(path, 'w')
    try:
        for line in lines:
            try:
                handle.write(line + u'\n')
            except Exception:
                handle.write(as_text(line).encode('utf-8') + '\n')
    finally:
        handle.close()


def _read_lines(path):
    if not os.path.isfile(path):
        return []
    try:
        import io
        handle = io.open(path, 'r', encoding='utf-8')
    except Exception:
        handle = open(path, 'r')
    try:
        return [line.rstrip(u'\r\n') for line in handle.readlines()]
    except Exception:
        return []
    finally:
        handle.close()


DEFAULTS = {
    'settings_version': str(SETTINGS_VERSION),
    'file': '',
    'sheet': '',
    'header_row': '1',
    'lookup_column': '',
    'scope': SCOPE_SELECTION,
    'categories': '',
    'key_parameter': '',
    'ignore_case': '1',
    'trim': '1',
    'numeric': '1',
    'duplicates': DUP_FIRST,
    'skip_blanks': '1',
    'type_parameters': '0',
}


def load_settings(path=None):
    """key=value, split on the first '=' only, missing keys fall back."""
    values = dict(DEFAULTS)
    values['mapping'] = []
    for line in _read_lines(path or SETTINGS_FILE):
        text = line.strip()
        if not text or text.startswith('#'):
            continue
        if '=' not in text:
            continue
        key, value = text.split('=', 1)
        key = key.strip()
        if key.startswith('map.'):
            values['mapping'].append(value)
        elif key in values:
            values[key] = value
    return values


def save_settings(values, path=None):
    lines = ['# RevoBIM VlookUp settings']
    for key in sorted(DEFAULTS.keys()):
        lines.append(u'{0}={1}'.format(key, as_text(values.get(key, DEFAULTS[key]))))
    index = 0
    for entry in values.get('mapping', []):
        lines.append(u'map.{0}={1}'.format(index, as_text(entry)))
        index += 1
    _write_lines(path or SETTINGS_FILE, lines)


def profile_path(name):
    safe = re.sub(r'[^A-Za-z0-9 _\-\.]', '_', as_text(name)).strip()
    return os.path.join(PROFILE_DIR, safe + '.txt'), safe


def list_profiles():
    out = []
    try:
        if os.path.isdir(PROFILE_DIR):
            for item in os.listdir(PROFILE_DIR):
                if item.lower().endswith('.txt'):
                    out.append(item[:-4])
    except Exception:
        pass
    return sorted(out, key=lambda t: t.lower())


def save_profile(name, values):
    path, safe = profile_path(name)
    if not safe:
        return None
    save_settings(values, path)
    return safe


def load_profile(name):
    path, safe = profile_path(name)
    if not safe or not os.path.isfile(path):
        return None
    return load_settings(path)


def delete_profile(name):
    path, safe = profile_path(name)
    try:
        if safe and os.path.isfile(path):
            os.remove(path)
            return True
    except Exception:
        pass
    return False


def encode_mapping(pairs):
    """[(column caption, target)] -> ['caption||target']."""
    return [u'{0}||{1}'.format(as_text(a), as_text(b)) for a, b in pairs]


def decode_mapping(entries):
    out = []
    for entry in entries:
        text = as_text(entry)
        if u'||' not in text:
            continue
        caption, target = text.split(u'||', 1)
        out.append((caption, target))
    return out
