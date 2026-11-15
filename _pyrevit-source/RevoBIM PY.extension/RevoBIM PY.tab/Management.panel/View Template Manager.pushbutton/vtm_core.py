# -*- coding: utf-8 -*-
"""RevoBIM PY - View Template Manager: model reading, staged edits, writing.

Nothing in here touches WPF. The window drives it.

Runs on Revit 2024-2027 and on IronPython 2.7 and 3: no f-strings, no print
statements, no bare ElementId.IntegerValue.
"""

__version__ = "1.3.1"

import re

import vtm_clr  # noqa: F401  - assemblies first, always

from Autodesk.Revit import DB

from System import Convert, Enum
from System.Collections.Generic import List

# --------------------------------------------------------------------------
# version-safe helpers
# --------------------------------------------------------------------------


def eid_value(element_id):
    """ElementId as an int. .Value (2024+) first, .IntegerValue (<=2025) after."""
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


def bip_int(name):
    """Int of a BuiltInParameter by name, or None where the release lacks it."""
    try:
        member = getattr(DB.BuiltInParameter, name)
    except Exception:
        return None
    try:
        return Convert.ToInt32(member)
    except Exception:
        return None


def elem_name(element):
    if element is None:
        return ""
    try:
        return element.Name
    except Exception:
        pass
    try:
        return DB.Element.Name.GetValue(element)
    except Exception:
        return ""


def set_elem_name(element, new_name):
    """Rename an element. Which route works varies with the engine, and neither
    reliably raises, so the name is read back to confirm."""
    try:
        element.Name = new_name
    except Exception:
        try:
            DB.Element.Name.SetValue(element, new_name)
        except Exception:
            pass
    return elem_name(element) == new_name


def pretty(text):
    """CamelCase enum name to spaced words."""
    if not text:
        return ""
    out = []
    previous = ""
    for ch in text:
        if ch.isupper() and previous and not previous.isupper():
            out.append(" ")
        out.append(ch)
        previous = ch
    return "".join(out)


# --------------------------------------------------------------------------
# cell kinds
# --------------------------------------------------------------------------

KIND_TEXT = "text"
KIND_INT = "int"
KIND_DOUBLE = "double"
KIND_YESNO = "yesno"
KIND_CHOICE = "choice"
KIND_ELEMENT = "element"
KIND_READONLY = "readonly"
KIND_FLAGONLY = "flagonly"     # in the template's parameter list but holds no value

KEY_NAME = "__name__"
KEY_TYPE = "__type__"
KEY_USED = "__used__"
KEY_DEFAULT = "__default__"
FIXED_KEYS = [KEY_NAME, KEY_TYPE, KEY_USED, KEY_DEFAULT]

MODE_VALUES = "values"
MODE_CONTROLLED = "controlled"

# BuiltInParameter name -> .NET enum type name, for the dropdown cells.
# Read off the running Revit so the numbers are always that release's own.
CHOICE_ENUMS = [
    ("VIEW_DETAIL_LEVEL", "ViewDetailLevel"),
    ("VIEW_DISCIPLINE", "ViewDiscipline"),
    ("MODEL_GRAPHICS_STYLE", "DisplayStyle"),
    ("VIEW_PARTS_VISIBILITY", "PartsVisibility"),
]

# BuiltInParameter name -> DB class, so an ElementId cell has a dropdown even
# when every template in the model currently holds None.
ELEMENT_CLASSES = [
    ("VIEW_PHASE_FILTER", "PhaseFilter"),
    ("VIEW_PHASE", "Phase"),
]

# Columns shown the first time the window opens, in this order.
CORE_BIP_NAMES = [
    "VIEW_SCALE",
    "VIEW_DETAIL_LEVEL",
    "VIEW_DISCIPLINE",
    "MODEL_GRAPHICS_STYLE",
    "VIEW_PARTS_VISIBILITY",
    "VIEWER_CROP_REGION",
    "VIEWER_CROP_REGION_VISIBLE",
    "VIEWER_ANNOTATION_CROP_ACTIVE",
    "VIEW_PHASE_FILTER",
    "VIEW_PHASE",
]


def _choice_map():
    """{bip int: [(int value, label), ...]} for the enum-backed parameters."""
    out = {}
    for bip_name, enum_name in CHOICE_ENUMS:
        key = bip_int(bip_name)
        if key is None:
            continue
        try:
            enum_type = getattr(DB, enum_name)
        except Exception:
            continue
        options = []
        try:
            for value in Enum.GetValues(enum_type):
                try:
                    number = Convert.ToInt32(value)
                except Exception:
                    continue
                label = pretty(str(value))
                if label.lower() in ("undefined", "invalid"):
                    continue
                options.append((number, label))
        except Exception:
            options = []
        if options:
            out[key] = options
    return out


def _element_class_map():
    out = {}
    for bip_name, class_name in ELEMENT_CLASSES:
        key = bip_int(bip_name)
        if key is None:
            continue
        try:
            out[key] = getattr(DB, class_name)
        except Exception:
            pass
    return out


# --------------------------------------------------------------------------
# columns
# --------------------------------------------------------------------------


class ColumnDef(object):
    def __init__(self, key, label):
        self.key = key
        self.label = label
        self.group = ""
        self.kind = KIND_READONLY
        self.options = []          # [(value, label)] for choice / yesno / element
        self.seen = 0              # templates carrying this parameter
        self.controllable = 0      # templates listing it as controllable
        self.width = 150
        self.core = False

    def option_label(self, value):
        for option_value, label in self.options:
            if option_value == value:
                return label
        return None


class Cell(object):
    """One parameter on one template, as read."""

    def __init__(self):
        self.kind = KIND_READONLY
        self.text = ""             # what the grid shows
        self.value = None          # raw: str / int / float / ElementId int
        self.editable = False
        self.note = ""


# --------------------------------------------------------------------------
# rows
# --------------------------------------------------------------------------


class TemplateRow(object):
    def __init__(self, view):
        self.view = view
        self.id = view.Id
        self.id_value = eid_value(view.Id)
        self.name = elem_name(view)
        self.view_type = ""
        self.used_views = 0
        self.used_defaults = 0
        self.used_names = []
        self.cells = {}            # key -> Cell
        self.controllable = set()  # keys the template can control
        self.controlled = set()    # keys it does control
        self.edits = {}            # key -> staged value (raw)
        self.edit_text = {}        # key -> staged display text
        self.flag_edits = {}       # key -> staged True/False
        self.marked = False        # staged for deletion

    @property
    def total_used(self):
        return self.used_views + self.used_defaults

    @property
    def unused(self):
        return self.total_used == 0

    @property
    def dirty(self):
        return bool(self.edits) or bool(self.flag_edits) or self.marked

    def display(self, key, mode):
        if key == KEY_NAME:
            if KEY_NAME in self.edit_text:
                return self.edit_text[KEY_NAME]
            return self.name
        if key == KEY_TYPE:
            return self.view_type
        if key == KEY_USED:
            return str(self.used_views)
        if key == KEY_DEFAULT:
            return str(self.used_defaults)
        if mode == MODE_CONTROLLED:
            if key not in self.controllable:
                return ""
            state = self.flag_edits.get(key)
            if state is None:
                state = key in self.controlled
            if state:
                return u"\u2713"
            return u"\u2013"
        if key in self.edit_text:
            return self.edit_text[key]
        cell = self.cells.get(key)
        if cell is None:
            return u"\u2014"
        return cell.text

    def is_dirty_cell(self, key, mode):
        if mode == MODE_CONTROLLED:
            return key in self.flag_edits
        if key == KEY_NAME:
            return KEY_NAME in self.edits
        return key in self.edits

    def clear_edits(self):
        self.edits = {}
        self.edit_text = {}
        self.flag_edits = {}
        self.marked = False


# --------------------------------------------------------------------------
# the read
# --------------------------------------------------------------------------


class Model(object):
    def __init__(self):
        self.rows = []
        self.columns = {}          # key -> ColumnDef
        self.order = []            # column keys, display order
        self.view_types = []
        self.warnings = []


def _param_key(param):
    try:
        return eid_value(param.Id)
    except Exception:
        pass
    try:
        return eid_value(param.Definition.Id)
    except Exception:
        return None


def _param_group(param):
    try:
        group_id = param.Definition.GetGroupTypeId()
        return DB.LabelUtils.GetLabelForGroup(group_id)
    except Exception:
        pass
    try:
        return DB.LabelUtils.GetLabelFor(param.Definition.ParameterGroup)
    except Exception:
        return ""


def _is_yesno(param):
    try:
        if param.Definition.GetDataType() == DB.SpecTypeId.Boolean.YesNo:
            return True
    except Exception:
        pass
    try:
        return str(param.Definition.ParameterType) == "YesNo"
    except Exception:
        return False


def _bip_label(key):
    try:
        member = Enum.ToObject(DB.BuiltInParameter, key)
        if Enum.IsDefined(DB.BuiltInParameter, member):
            label = DB.LabelUtils.GetLabelFor(member)
            if label:
                return label
            return pretty(str(member))
    except Exception:
        pass
    return "Parameter {0}".format(key)


def read_model(doc):
    """Everything the window needs, in one pass over the document."""
    model = Model()
    choices = _choice_map()
    element_classes = _element_class_map()

    views = list(DB.FilteredElementCollector(doc).OfClass(DB.View).ToElements())

    templates = []
    usage = {}
    usage_names = {}
    for view in views:
        try:
            if view.IsTemplate:
                templates.append(view)
                continue
        except Exception:
            continue
        try:
            template_id = view.ViewTemplateId
        except Exception:
            continue
        key = eid_value(template_id)
        if key > 0:
            usage[key] = usage.get(key, 0) + 1
            names = usage_names.setdefault(key, [])
            if len(names) < 40:
                names.append(elem_name(view))

    defaults = {}
    try:
        for vft in DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType).ToElements():
            try:
                key = eid_value(vft.DefaultTemplateId)
            except Exception:
                continue
            if key > 0:
                defaults[key] = defaults.get(key, 0) + 1
    except Exception:
        model.warnings.append("Default templates on view types could not be read.")

    element_cache = {}
    element_seen_classes = {}

    for view in templates:
        row = TemplateRow(view)
        row.used_views = usage.get(row.id_value, 0)
        row.used_defaults = defaults.get(row.id_value, 0)
        row.used_names = usage_names.get(row.id_value, [])
        try:
            row.view_type = pretty(str(view.ViewType))
        except Exception:
            row.view_type = ""

        # which parameters this template can and does control
        try:
            controllable = view.GetTemplateParameterIds()
        except Exception:
            controllable = []
        try:
            non_controlled = view.GetNonControlledTemplateParameterIds()
        except Exception:
            non_controlled = []
        non_controlled_keys = set()
        for pid in non_controlled:
            non_controlled_keys.add(eid_value(pid))
        for pid in controllable:
            key = eid_value(pid)
            row.controllable.add(key)
            if key not in non_controlled_keys:
                row.controlled.add(key)
            column = model.columns.get(key)
            if column is None:
                column = ColumnDef(key, _bip_label(key))
                column.kind = KIND_FLAGONLY
                model.columns[key] = column
            column.controllable += 1

        # the parameters themselves
        for param in view.Parameters:
            key = _param_key(param)
            if key is None:
                continue
            try:
                label = param.Definition.Name
            except Exception:
                label = _bip_label(key)
            column = model.columns.get(key)
            if column is None:
                column = ColumnDef(key, label)
                model.columns[key] = column
            elif column.kind == KIND_FLAGONLY:
                column.label = label
            column.seen += 1
            if not column.group:
                column.group = _param_group(param)

            cell = Cell()
            storage = None
            try:
                storage = param.StorageType
            except Exception:
                pass
            read_only = True
            try:
                read_only = param.IsReadOnly
            except Exception:
                pass

            if storage == DB.StorageType.String:
                cell.kind = KIND_TEXT
                try:
                    cell.value = param.AsString()
                except Exception:
                    cell.value = None
                cell.text = cell.value or ""
            elif storage == DB.StorageType.Integer:
                try:
                    cell.value = param.AsInteger()
                except Exception:
                    cell.value = None
                if key in choices:
                    cell.kind = KIND_CHOICE
                    column.options = choices[key]
                    label_for = column.option_label(cell.value)
                    cell.text = label_for or _value_string(param, cell.value)
                elif _is_yesno(param):
                    cell.kind = KIND_YESNO
                    column.options = [(1, "Yes"), (0, "No")]
                    cell.text = "Yes" if cell.value else "No"
                else:
                    cell.kind = KIND_INT
                    cell.text = _value_string(param, cell.value)
            elif storage == DB.StorageType.Double:
                cell.kind = KIND_DOUBLE
                try:
                    cell.value = param.AsDouble()
                except Exception:
                    cell.value = None
                cell.text = _value_string(param, cell.value)
            elif storage == DB.StorageType.ElementId:
                cell.kind = KIND_ELEMENT
                try:
                    target = param.AsElementId()
                except Exception:
                    target = None
                cell.value = eid_value(target)
                if cell.value > 0:
                    element = doc.GetElement(target)
                    cell.text = elem_name(element) or str(cell.value)
                    try:
                        element_seen_classes.setdefault(key, set()).add(element.GetType())
                    except Exception:
                        pass
                else:
                    cell.text = "(None)"
            else:
                cell.kind = KIND_READONLY
                cell.text = ""

            if read_only:
                cell.editable = False
                if column.kind in (KIND_FLAGONLY, KIND_READONLY):
                    column.kind = KIND_READONLY
            else:
                cell.editable = cell.kind != KIND_READONLY
                if cell.editable:
                    column.kind = cell.kind

            row.cells[key] = cell

        model.rows.append(row)

    # dropdowns for the ElementId columns
    for key, column in model.columns.items():
        if column.kind != KIND_ELEMENT:
            continue
        classes = element_seen_classes.get(key, set())
        seeded = element_classes.get(key)
        if seeded is not None:
            classes = set(classes)
            classes.add(seeded)
        options = [(0, "(None)")]
        for cls in classes:
            cached = element_cache.get(cls)
            if cached is None:
                cached = []
                try:
                    for element in DB.FilteredElementCollector(doc).OfClass(cls).ToElements():
                        cached.append((eid_value(element.Id), elem_name(element)))
                except Exception:
                    cached = []
                element_cache[cls] = cached
            options.extend(cached)
        seen_values = set()
        unique = []
        for value, label in options:
            if value in seen_values:
                continue
            seen_values.add(value)
            unique.append((value, label))
        column.options = unique
        if len(unique) < 2:
            column.kind = KIND_READONLY

    # ordering: the core parameters first, then everything else by name
    core_keys = []
    for name in CORE_BIP_NAMES:
        key = bip_int(name)
        if key is not None and key in model.columns:
            core_keys.append(key)
            model.columns[key].core = True
    rest = []
    for key in model.columns:
        if key not in core_keys:
            rest.append(key)
    rest.sort(key=lambda k: (model.columns[k].label or "").lower())
    model.order = list(FIXED_KEYS) + core_keys + rest

    for key in FIXED_KEYS:
        column = ColumnDef(key, {
            KEY_NAME: "Template Name",
            KEY_TYPE: "View Type",
            KEY_USED: "Used",
            KEY_DEFAULT: "Default",
        }[key])
        column.core = True
        column.kind = KIND_TEXT if key == KEY_NAME else KIND_READONLY
        column.width = {KEY_NAME: 260, KEY_TYPE: 130, KEY_USED: 58, KEY_DEFAULT: 62}[key]
        column.group = "Identity"
        model.columns[key] = column

    types = set()
    for row in model.rows:
        if row.view_type:
            types.add(row.view_type)
    model.view_types = sorted(types)
    model.rows.sort(key=lambda r: (r.view_type.lower(), r.name.lower()))
    return model


def _value_string(param, fallback):
    try:
        text = param.AsValueString()
        if text:
            return text
    except Exception:
        pass
    if fallback is None:
        return ""
    return str(fallback)


# --------------------------------------------------------------------------
# staging an edit - one rule for typing, dropdowns and paste
# --------------------------------------------------------------------------

STAGED = "staged"      # an edit is now held
SAME = "same"          # the text matches the model; any held edit cleared
SKIPPED = "skipped"    # refused, with a reason

TICK = u"✓"
DASH = u"–"

_TRUE_WORDS = set([u"1", u"yes", u"y", u"true", u"on", u"include", u"included",
                   u"x", TICK, u"✔"])
_FALSE_WORDS = set([u"0", u"no", u"n", u"false", u"off", u"exclude", u"excluded",
                    u"", DASH, u"-", u"—"])

_SCALE = re.compile(u"^\\s*1\\s*:\\s*([0-9][0-9,]*)\\s*$")


def parse_bool(text):
    """True, False, or None when the text means neither."""
    word = (u"%s" % (text if text is not None else u"")).strip().lower()
    if word in _TRUE_WORDS:
        return True
    if word in _FALSE_WORDS:
        return False
    return None


def parse_int(text):
    """A whole number from what a user types or what a cell shows.
    '1 : 100' is a scale and means 100. None when it is not a number."""
    word = (u"%s" % (text if text is not None else u"")).strip()
    if not word:
        return None
    match = _SCALE.match(word)
    if match:
        word = match.group(1)
    word = word.replace(u",", u"")
    try:
        return int(round(float(word)))
    except Exception:
        return None


def match_option(options, text):
    """(value, label) of the option the text names, case-insensitively, or
    None. '(None)' and a blank both mean the none option where there is one."""
    word = (u"%s" % (text if text is not None else u"")).strip().lower()
    for value, label in options:
        if (label or u"").strip().lower() == word:
            return value, label
    if word in (u"", u"none", u"(none)"):
        for value, label in options:
            if value == 0:
                return value, label
    return None


def _clear(row, key):
    row.edits.pop(key, None)
    row.edit_text.pop(key, None)


def stage_text(row, column, key, text, mode):
    """Stage `text` into one cell of one template.

    Returns (STAGED | SAME | SKIPPED, reason). Nothing touches Revit - it only
    moves the row's held edits - so it is the one place the rules live, for a
    typed value, a dropdown pick and a paste alike.
    """
    if text is None:
        text = u""
    text = (u"%s" % text).strip()

    if mode == MODE_CONTROLLED:
        if key in FIXED_KEYS:
            return SKIPPED, u"not a template setting"
        if key not in row.controllable:
            return SKIPPED, u"this template does not offer that setting"
        state = parse_bool(text)
        if state is None:
            return SKIPPED, u"'{0}' is not a tick or a dash".format(text)
        if state == (key in row.controlled):
            row.flag_edits.pop(key, None)
            return SAME, u""
        row.flag_edits[key] = state
        return STAGED, u""

    if key == KEY_NAME:
        if not text:
            return SKIPPED, u"a template needs a name"
        if text == row.name:
            _clear(row, key)
            return SAME, u""
        row.edits[key] = text
        row.edit_text[key] = text
        return STAGED, u""

    if key in FIXED_KEYS:
        return SKIPPED, u"read only"

    cell = row.cells.get(key)
    if cell is None:
        return SKIPPED, u"not a parameter of this template"
    if not cell.editable:
        return SKIPPED, u"read only"

    kind = column.kind if column is not None else cell.kind
    options = column.options if column is not None else []

    if kind == KIND_TEXT:
        if text == (cell.value or u""):
            _clear(row, key)
            return SAME, u""
        row.edits[key] = text
        row.edit_text[key] = text
        return STAGED, u""

    if kind == KIND_INT:
        number = parse_int(text)
        if number is None:
            return SKIPPED, u"'{0}' is not a whole number".format(text)
        if number == cell.value:
            _clear(row, key)
            return SAME, u""
        row.edits[key] = number
        shown = _SCALE.match(cell.text or u"")
        row.edit_text[key] = u"1 : {0}".format(number) if shown else u"%s" % number
        return STAGED, u""

    if kind == KIND_DOUBLE:
        if not text:
            return SKIPPED, u"a number is needed"
        if text == (cell.text or u""):
            _clear(row, key)
            return SAME, u""
        row.edits[key] = text
        row.edit_text[key] = text
        return STAGED, u""

    if kind == KIND_YESNO:
        state = parse_bool(text)
        if state is None:
            return SKIPPED, u"'{0}' is not yes or no".format(text)
        value = 1 if state else 0
        if value == (1 if cell.value else 0):
            _clear(row, key)
            return SAME, u""
        row.edits[key] = value
        row.edit_text[key] = u"Yes" if state else u"No"
        return STAGED, u""

    if kind in (KIND_CHOICE, KIND_ELEMENT):
        found = match_option(options, text)
        if found is None:
            return SKIPPED, u"'{0}' is not one of the choices".format(text)
        value, label = found
        if value == cell.value:
            _clear(row, key)
            return SAME, u""
        row.edits[key] = value
        row.edit_text[key] = label
        return STAGED, u""

    return SKIPPED, u"cannot be edited from here"


# --------------------------------------------------------------------------
# clipboard - plain functions over (row position, column position)
# --------------------------------------------------------------------------


def copy_text(cells, value_at):
    """Tab-separated text for a set of (row, col) positions, the shape Excel
    pastes. The block is the selected rows by the union of selected columns;
    a gap in a ragged selection is left empty."""
    if not cells:
        return u""
    rows = sorted(set([r for r, c in cells]))
    cols = sorted(set([c for r, c in cells]))
    chosen = set(cells)
    lines = []
    for r in rows:
        parts = []
        for c in cols:
            if (r, c) in chosen:
                value = value_at(r, c)
                value = u"%s" % (value if value is not None else u"")
                parts.append(value.replace(u"\t", u" ").replace(u"\r", u" ")
                             .replace(u"\n", u" "))
            else:
                parts.append(u"")
        lines.append(u"\t".join(parts))
    return u"\r\n".join(lines)


def parse_clipboard(text):
    """Clipboard text into a list of rows of cells. One trailing line break is
    what Excel adds, not an empty row."""
    if text is None:
        return []
    text = (u"%s" % text).replace(u"\r\n", u"\n").replace(u"\r", u"\n")
    if text.endswith(u"\n"):
        text = text[:-1]
    if text == u"":
        return [[u""]]
    return [line.split(u"\t") for line in text.split(u"\n")]


def paste_plan(block, selected, row_count, col_count):
    """Where each pasted value lands: a list of (row, col, text).

    - one value: into every selected cell
    - a block over a full rectangle it divides into evenly: tiled across it,
      the way Excel repeats a copied row down a taller selection
    - any other block: once, from the top-left of the selection
    Nothing lands outside the grid.
    """
    if not block or not selected:
        return []
    height = len(block)
    width = max([len(line) for line in block])
    if width == 0:
        return []

    if height == 1 and width == 1:
        value = block[0][0]
        return [(r, c, value) for r, c in sorted(selected)
                if 0 <= r < row_count and 0 <= c < col_count]

    rows = [r for r, c in selected]
    cols = [c for r, c in selected]
    top, left = min(rows), min(cols)
    sel_h = max(rows) - top + 1
    sel_w = max(cols) - left + 1
    full = len(set(selected)) == sel_h * sel_w

    out = []
    if full and sel_h % height == 0 and sel_w % width == 0 and \
            (sel_h > height or sel_w > width):
        for r in range(top, top + sel_h):
            line = block[(r - top) % height]
            for c in range(left, left + sel_w):
                j = (c - left) % width
                if j < len(line) and r < row_count and c < col_count:
                    out.append((r, c, line[j]))
        return out

    for i, line in enumerate(block):
        for j, value in enumerate(line):
            r, c = top + i, left + j
            if r < row_count and c < col_count:
                out.append((r, c, value))
    return out


# --------------------------------------------------------------------------
# writing
# --------------------------------------------------------------------------


class WarningSwallower(DB.IFailuresPreprocessor):
    def PreprocessFailures(self, accessor):
        try:
            accessor.DeleteAllWarnings()
        except Exception:
            pass
        return DB.FailureProcessingResult.Continue


def _params_by_key(view):
    out = {}
    for param in view.Parameters:
        key = _param_key(param)
        if key is not None:
            out[key] = param
    return out


def apply_edits(doc, model):
    """Write every staged edit in one transaction. Returns (changed, problems)."""
    problems = []
    changed = 0

    rows = [r for r in model.rows if r.edits or r.flag_edits]
    if not rows:
        return 0, problems

    # a rename clashing with an existing view name is refused before the write
    existing = {}
    for row in model.rows:
        existing[row.name.lower()] = row.id_value

    transaction = DB.Transaction(doc, "RevoBIM: edit view templates")
    transaction.Start()
    try:
        options = transaction.GetFailureHandlingOptions()
        options.SetFailuresPreprocessor(WarningSwallower())
        options.SetClearAfterRollback(True)
        transaction.SetFailureHandlingOptions(options)
    except Exception:
        pass

    try:
        for row in rows:
            params = _params_by_key(row.view)

            # 1. the name
            if KEY_NAME in row.edits:
                new_name = row.edits[KEY_NAME]
                clash = existing.get(new_name.lower())
                if clash is not None and clash != row.id_value:
                    problems.append("{0}: another view is already called '{1}'.".format(
                        row.name, new_name))
                elif set_elem_name(row.view, new_name):
                    existing.pop(row.name.lower(), None)
                    existing[new_name.lower()] = row.id_value
                    row.name = new_name
                    changed += 1
                else:
                    problems.append("{0}: Revit would not take the name '{1}'.".format(
                        row.name, new_name))

            # 2. parameter values
            for key, value in row.edits.items():
                if key == KEY_NAME:
                    continue
                column = model.columns.get(key)
                param = params.get(key)
                if param is None:
                    problems.append("{0}: '{1}' is not on this template.".format(
                        row.name, column.label if column else key))
                    continue
                ok, message = _write_param(param, column, value)
                if ok:
                    changed += 1
                    if key in row.controllable and key not in row.controlled \
                            and key not in row.flag_edits:
                        problems.append(
                            "{0}: '{1}' was written, but the template does not "
                            "control it, so no view will pick it up.".format(
                                row.name, column.label if column else key))
                else:
                    problems.append("{0}: '{1}' - {2}".format(
                        row.name, column.label if column else key, message))

            # 3. the controlled / not-controlled flags
            if row.flag_edits:
                wanted_off = set()
                for key in row.controllable:
                    state = row.flag_edits.get(key)
                    if state is None:
                        state = key in row.controlled
                    if not state:
                        wanted_off.add(key)
                ids = List[DB.ElementId]()
                lookup = {}
                try:
                    for pid in row.view.GetTemplateParameterIds():
                        lookup[eid_value(pid)] = pid
                except Exception:
                    lookup = {}
                for key in wanted_off:
                    pid = lookup.get(key)
                    if pid is not None:
                        ids.Add(pid)
                try:
                    row.view.SetNonControlledTemplateParameterIds(ids)
                    changed += len(row.flag_edits)
                    row.controlled = set(row.controllable) - wanted_off
                except Exception as err:
                    problems.append("{0}: the include tick boxes would not save - {1}".format(
                        row.name, err))

        transaction.Commit()
    except Exception as err:
        try:
            transaction.RollBack()
        except Exception:
            pass
        problems.append("Nothing was written - {0}".format(err))
        return 0, problems

    for row in rows:
        row.clear_edits()
    return changed, problems


def _write_param(param, column, value):
    try:
        if param.IsReadOnly:
            return False, "read only on this template."
    except Exception:
        pass
    kind = column.kind if column else KIND_TEXT
    try:
        if kind == KIND_TEXT:
            param.Set(value if value is not None else "")
            return True, ""
        if kind in (KIND_YESNO, KIND_CHOICE, KIND_INT):
            param.Set(int(value))
            return True, ""
        if kind == KIND_DOUBLE:
            if param.SetValueString(str(value)):
                return True, ""
            return False, "'{0}' is not a value Revit accepts here.".format(value)
        if kind == KIND_ELEMENT:
            param.Set(DB.ElementId(int(value)) if int(value) > 0
                      else DB.ElementId.InvalidElementId)
            return True, ""
    except Exception as err:
        return False, str(err)
    return False, "this parameter cannot be edited from here."


def delete_templates(doc, rows):
    """Delete the given rows. Returns (deleted count, problems)."""
    problems = []
    deleted = 0
    if not rows:
        return 0, problems

    transaction = DB.Transaction(doc, "RevoBIM: delete view templates")
    transaction.Start()
    try:
        options = transaction.GetFailureHandlingOptions()
        options.SetFailuresPreprocessor(WarningSwallower())
        transaction.SetFailureHandlingOptions(options)
    except Exception:
        pass
    try:
        for row in rows:
            try:
                doc.Delete(row.id)
                deleted += 1
            except Exception as err:
                problems.append("{0} could not be deleted - {1}".format(row.name, err))
        transaction.Commit()
    except Exception as err:
        try:
            transaction.RollBack()
        except Exception:
            pass
        return 0, ["Nothing was deleted - {0}".format(err)]
    return deleted, problems
