# -*- coding: utf-8 -*-
"""RevoBIM PY - Style Manager

Three tabs in one window:

  Filters      - every view filter, its rules, and where it is used
  Line Styles  - every line subcategory, its weight, colour and pattern
  Text Styles  - every text note type and its formatting

Each tab can isolate duplicates by appearance, merge them into a single
style of your choice, rename in place or in bulk, delete with an impact
warning, and round-trip through a DiRoots-style Excel workbook. Nothing is
written to the model until APPLY CHANGES is pressed.

Author  : RevoBIM PY
Version : see VERSION below / CHANGELOG.md
"""

__title__ = "Style Manager"
__author__ = "RevoBIM PY"
__doc__ = "Audit, de-duplicate, merge, rename and delete view filters, line styles and text styles."
__persistentengine__ = True

# ---------------------------------------------------------------------------
#  VERSION CONTROL
# ---------------------------------------------------------------------------
VERSION = "4.7.0"
BUILD_DATE = "2026-11-04"
TOOL_NAME = "Style Manager"
BRAND = "RevoBIM PY"
# ---------------------------------------------------------------------------

from pyrevit import script  # pyRevit import first (engine bootstrap)

import clr
import os
import re
import json
import math
import datetime
import traceback

clr.AddReference('PresentationCore')
clr.AddReference('PresentationFramework')
clr.AddReference('WindowsBase')
clr.AddReference('System')
clr.AddReference('System.Xml')
clr.AddReference('System.Data')
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')

import System
import System.Windows
import System.Windows.Controls as WpfControls
import System.Windows.Controls.Primitives as WpfPrimitives
import System.Windows.Media as WpfMedia

from System import Action, AppDomain, Array, Object, Type, Activator
from System.Collections.Generic import List
from System.Data import DataTable
from System.Windows import Window, Thickness, Visibility, WindowState
from System.Windows.Markup import XamlReader
from System.Windows.Data import Binding
from System.Windows.Threading import DispatcherPriority
from System.Runtime.InteropServices import Marshal
from Microsoft.Win32 import SaveFileDialog, OpenFileDialog

# One name per line: if a Revit / .NET build is missing any of these the traceback
# points at the exact name instead of failing the whole import block.
CornerRadius = System.Windows.CornerRadius
SolidColorBrush = WpfMedia.SolidColorBrush
WpfColor = WpfMedia.Color
VisualTreeHelper = WpfMedia.VisualTreeHelper
ListBoxItem = WpfControls.ListBoxItem
Button = WpfControls.Button
CheckBox = WpfControls.CheckBox
ContextMenu = WpfControls.ContextMenu
MenuItem = WpfControls.MenuItem
Separator = WpfControls.Separator
Orientation = WpfControls.Orientation
StackPanel = WpfControls.StackPanel
TextBlock = WpfControls.TextBlock
Image = WpfControls.Image
TabItem = WpfControls.TabItem
RadioButton = WpfControls.RadioButton
WrapPanel = WpfControls.WrapPanel
ContentControl = WpfControls.ContentControl
Border = WpfControls.Border
DataGridRow = WpfControls.DataGridRow
DataGridCell = WpfControls.DataGridCell
DataGridCellInfo = WpfControls.DataGridCellInfo
DataGridEditAction = WpfControls.DataGridEditAction
DataGridLength = WpfControls.DataGridLength
DataGridTextColumn = WpfControls.DataGridTextColumn
DataGridTemplateColumn = WpfControls.DataGridTemplateColumn
DataGridComboBoxColumn = WpfControls.DataGridComboBoxColumn
ComboBox = WpfControls.ComboBox

try:
    from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption
except Exception:
    BitmapImage = None
    BitmapCacheOption = None

try:
    from System.IO import MemoryStream, File as IOFile
except Exception:
    MemoryStream = None
    IOFile = None

try:
    from System.Windows.Shell import WindowChrome
except Exception:
    WindowChrome = None

try:
    from System.Threading import Thread, ThreadStart, ApartmentState
except Exception:
    Thread = None
    ThreadStart = None
    ApartmentState = None

import Autodesk.Revit.DB as DB
import Autodesk.Revit.UI as UI
from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent

try:
    UIAPP = __revit__          # noqa - injected by pyRevit
except Exception:
    from pyrevit import HOST_APP
    UIAPP = HOST_APP.uiapp

WINDOW_KEY = 'RevoBIM_PY_StyleManager_Window_v3'

# ---------------------------------------------------------------------------
#  PATHS / SETTINGS / LOGGING
# ---------------------------------------------------------------------------
APPDATA_DIR = os.path.join(os.getenv('APPDATA') or '', BRAND)
SETTINGS_FILE = os.path.join(APPDATA_DIR, 'style_manager_settings.json')
LOG_DIR = os.path.join(os.path.expanduser('~'), 'Documents', BRAND, 'Logs')

DEFAULT_SETTINGS = {
    'version': VERSION,
    'last_export_dir': '',
    'last_export_file': '',
    'include_selection_filters': True,
    'write_log_files': True,
    'dup_rules': {},
}


def _ensure_dir(path):
    try:
        if path and not os.path.isdir(path):
            os.makedirs(path)
    except Exception:
        pass


def load_settings():
    data = dict(DEFAULT_SETTINGS)
    try:
        if os.path.isfile(SETTINGS_FILE):
            f = open(SETTINGS_FILE, 'r')
            try:
                loaded = json.load(f)
            finally:
                f.close()
            if isinstance(loaded, dict):
                data.update(loaded)
    except Exception:
        pass
    data['version'] = VERSION
    return data


def save_settings(data):
    try:
        _ensure_dir(APPDATA_DIR)
        f = open(SETTINGS_FILE, 'w')
        try:
            json.dump(data, f, indent=2)
        finally:
            f.close()
    except Exception:
        pass


def write_log(lines, tag='session'):
    """Write a timestamped log file. Returns the path or None."""
    try:
        _ensure_dir(LOG_DIR)
        stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        path = os.path.join(LOG_DIR, 'StyleManager_%s_%s.log' % (tag, stamp))
        f = open(path, 'w')
        try:
            f.write('%s - %s v%s\n' % (BRAND, TOOL_NAME, VERSION))
            f.write('%s\n' % datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
            f.write('-' * 70 + '\n')
            for ln in lines:
                try:
                    f.write(('%s\n' % ln).encode('utf-8') if isinstance(ln, unicode) else '%s\n' % ln)  # noqa
                except Exception:
                    f.write('%s\n' % str(ln))
        finally:
            f.close()
        return path
    except Exception:
        return None


# ---------------------------------------------------------------------------
#  SMALL HELPERS
# ---------------------------------------------------------------------------
def eid_int(eid):
    """ElementId -> int.

    .Value first (Revit 2024+), .IntegerValue only as the fallback for 2021-2023.
    The other way round, every call on Revit 2026/2027 - where IntegerValue no
    longer exists - raised and caught an exception, and this runs for every id of
    every element on every read.
    """
    if eid is None:
        return -1
    try:
        return int(eid.Value)
    except Exception:
        pass
    try:
        return int(eid.IntegerValue)
    except Exception:
        return -1


def to_eid(value):
    try:
        return DB.ElementId(int(value))
    except Exception:
        return DB.ElementId.InvalidElementId


def safe_str(value):
    if value is None:
        return ''
    try:
        return unicode(value)  # noqa
    except Exception:
        try:
            return str(value)
        except Exception:
            return ''


def fmt_num(value):
    try:
        v = float(value)
    except Exception:
        return safe_str(value)
    if abs(v - round(v)) < 1e-9:
        return '%d' % int(round(v))
    txt = '%.6f' % v
    txt = txt.rstrip('0').rstrip('.')
    return txt


_BRUSH_CACHE = {}


def brush_from_hex(hex_str):
    """A frozen brush for a hex colour, made once and shared.

    The table used to build a fresh brush for every row on every refresh - several
    thousand objects each time a cell was edited on a large tab. Frozen brushes
    are immutable, so one per colour is safe to share across every row.
    """
    cached = _BRUSH_CACHE.get(hex_str)
    if cached is not None:
        return cached
    brush = _make_brush(hex_str)
    _BRUSH_CACHE[hex_str] = brush
    return brush


def _make_brush(hex_str):
    hex_str = hex_str.lstrip('#')
    r = int(hex_str[0:2], 16)
    g = int(hex_str[2:4], 16)
    b = int(hex_str[4:6], 16)
    brush = SolidColorBrush(WpfColor.FromRgb(r, g, b))
    try:
        brush.Freeze()
    except Exception:
        pass
    return brush


def blend_hex(fg_hex, bg_hex, factor):
    """Blend fg over bg by factor (0..1) and return a hex string."""
    fg_hex = fg_hex.lstrip('#')
    bg_hex = bg_hex.lstrip('#')
    out = ''
    for i in (0, 2, 4):
        f = int(fg_hex[i:i + 2], 16)
        b = int(bg_hex[i:i + 2], 16)
        v = int(round(b + (f - b) * factor))
        v = max(0, min(255, v))
        out += '%02X' % v
    return '#' + out


def column_width(value):
    """A DataGrid column width that does not depend on which overload the engine
    picks. DataGridLength takes a double, and handing it a Python int has been
    known to miss the overload on some IronPython builds."""
    try:
        return DataGridLength(float(value))
    except Exception:
        try:
            return DataGridLength(System.Double(value))
        except Exception:
            return float(value)


def parse_xaml(name, text):
    """Parse a XAML block and name it in the error if it will not load."""
    try:
        return XamlReader.Parse(text)
    except Exception as ex:
        raise Exception('XAML block "%s" failed to load: %s' % (name, ex))


def apply_window_chrome(window):
    """Remove the light non-client strip WPF leaves at the top of a
    WindowStyle=None window, while keeping resize and maximise behaviour."""
    if WindowChrome is None:
        return
    try:
        chrome = WindowChrome()
        chrome.CaptionHeight = 0.0
        chrome.CornerRadius = CornerRadius(0)
        chrome.GlassFrameThickness = Thickness(0)
        chrome.ResizeBorderThickness = Thickness(6)
        try:
            chrome.UseAeroCaptionButtons = False
        except Exception:
            pass
        WindowChrome.SetWindowChrome(window, chrome)
    except Exception:
        pass


def open_in_explorer(path):
    """Open Windows Explorer with the file selected (or the folder if missing)."""
    try:
        if path and os.path.isfile(path):
            System.Diagnostics.Process.Start('explorer.exe', '/select,"%s"' % path)
            return True
        folder = path if os.path.isdir(path) else os.path.dirname(path)
        if folder and os.path.isdir(folder):
            System.Diagnostics.Process.Start('explorer.exe', '"%s"' % folder)
            return True
    except Exception:
        try:
            os.startfile(os.path.dirname(path))
            return True
        except Exception:
            pass
    return False


def ui_safe(fn):
    """Catch exceptions in WPF handlers so they never reach Revit's UI thread."""
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as ex:
            try:
                args[0].log('ERROR in %s: %s' % (fn.__name__, ex))
                args[0].log(traceback.format_exc())
            except Exception:
                pass
    wrapper.__name__ = fn.__name__
    return wrapper


# ---------------------------------------------------------------------------
#  THEME
# ---------------------------------------------------------------------------
SHELL_BG = '#262A31'
PANEL_BG = '#2F343C'
GRID_BG = '#21252B'
ROW_BG = '#21252B'
ROW_ALT_BG = '#262A31'
ACCENT = '#3D9BE9'
ORANGE = '#F07C10'
BORDER = '#4F4F4F'
TEXT = '#DCDCDC'
TITLEBAR = '#2B2B2B'
CHANGED = '#3FB950'

# Vivid chip colours used to identify duplicate groups
GROUP_COLOURS = [
    '#E06C75', '#61AFEF', '#98C379', '#E5C07B', '#C678DD', '#56B6C2',
    '#D19A66', '#7FB3D5', '#BB8FCE', '#48C9B0', '#F1948A', '#F7DC6F',
    '#A3E4D7', '#F5B041', '#85C1E9', '#D7BDE2', '#A9DFBF', '#F0B27A',
]
GROUP_LABELS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
ALL_CATEGORIES = '(all)'

# The table carries these columns for its own bookkeeping - colours, staging
# state, grouping and sorting. A panel column may not reuse one of these names or
# the DataTable refuses the second one and the whole tab fails to build.
RESERVED_COLUMNS = ('RowBrush', 'ChipBrush', 'Group', 'Changed', 'RowKind',
                    'GroupKey', 'SortKey', 'Hidden')


def group_label(index):
    if index < len(GROUP_LABELS):
        return GROUP_LABELS[index]
    first = index // len(GROUP_LABELS) - 1
    return GROUP_LABELS[first] + GROUP_LABELS[index % len(GROUP_LABELS)]


# ---------------------------------------------------------------------------
#  FILTER RULE READING
# ---------------------------------------------------------------------------
OP_FROM_EVALUATOR = {
    'FilterStringEquals': 'equals',
    'FilterStringContains': 'contains',
    'FilterStringBeginsWith': 'begins with',
    'FilterStringEndsWith': 'ends with',
    'FilterStringGreater': '>',
    'FilterStringGreaterOrEqual': '>=',
    'FilterStringLess': '<',
    'FilterStringLessOrEqual': '<=',
    'FilterNumericEquals': 'equals',
    'FilterNumericGreater': '>',
    'FilterNumericGreaterOrEqual': '>=',
    'FilterNumericLess': '<',
    'FilterNumericLessOrEqual': '<=',
}

NEGATED_OP = {
    'equals': 'not equals',
    'contains': 'does not contain',
    'begins with': 'does not begin with',
    'ends with': 'does not end with',
    '>': '<=',
    '>=': '<',
    '<': '>=',
    '<=': '>',
    'has value': 'has no value',
}

# Longest first so parsing is unambiguous
PARSE_OPS = [
    'does not begin with', 'does not end with', 'does not contain',
    'not equals', 'has no value', 'has value',
    'begins with', 'ends with', 'contains', 'equals',
    '>=', '<=', '!=', '>', '<', '=',
]

OP_ALIASES = {'=': 'equals', '!=': 'not equals'}


class ParamResolver(object):
    """Resolves parameter names, storage types and display units, with caching."""

    def __init__(self, doc):
        self.doc = doc
        self._name_cache = {}
        self._kind_cache = {}

    def name(self, pid):
        key = eid_int(pid)
        if key in self._name_cache:
            return self._name_cache[key]
        label = 'Parameter %d' % key
        try:
            if key < 0:
                bip = System.Enum.ToObject(DB.BuiltInParameter, key)
                label = DB.LabelUtils.GetLabelFor(bip)
            else:
                el = self.doc.GetElement(pid)
                if el is not None:
                    label = el.Name
        except Exception:
            pass
        self._name_cache[key] = label
        return label

    def kind(self, pid, cat_ids):
        """Return (storage_kind, unit_type_id).

        storage_kind is one of 'string', 'double', 'int', 'elementid', None.
        """
        key = eid_int(pid)
        if key in self._kind_cache:
            return self._kind_cache[key]
        kind = None
        unit = None
        spec = None
        try:
            el = self.doc.GetElement(pid)
            if isinstance(el, DB.ParameterElement):
                defn = el.GetDefinition()
                spec = defn.GetDataType()
                kind = self._kind_from_spec(spec)
        except Exception:
            pass
        if kind is None:
            param = self._sample_parameter(pid, cat_ids)
            if param is not None:
                try:
                    st = param.StorageType
                    if st == DB.StorageType.String:
                        kind = 'string'
                    elif st == DB.StorageType.Double:
                        kind = 'double'
                    elif st == DB.StorageType.Integer:
                        kind = 'int'
                    elif st == DB.StorageType.ElementId:
                        kind = 'elementid'
                except Exception:
                    pass
                try:
                    spec = param.Definition.GetDataType()
                except Exception:
                    pass
        if spec is not None:
            try:
                if DB.UnitUtils.IsMeasurableSpec(spec):
                    unit = self.doc.GetUnits().GetFormatOptions(spec).GetUnitTypeId()
            except Exception:
                unit = None
        result = (kind, unit)
        self._kind_cache[key] = result
        return result

    @staticmethod
    def _kind_from_spec(spec):
        try:
            if DB.UnitUtils.IsMeasurableSpec(spec):
                return 'double'
        except Exception:
            pass
        try:
            if spec == DB.SpecTypeId.String.Text or spec == DB.SpecTypeId.String.MultilineText:
                return 'string'
            if spec == DB.SpecTypeId.Boolean.YesNo:
                return 'int'
            if spec == DB.SpecTypeId.Int.Integer:
                return 'int'
            if spec == DB.SpecTypeId.Reference.Material:
                return 'elementid'
        except Exception:
            pass
        return None

    def _sample_parameter(self, pid, cat_ids):
        bip = None
        key = eid_int(pid)
        if key < 0:
            try:
                bip = System.Enum.ToObject(DB.BuiltInParameter, key)
            except Exception:
                bip = None
        for cid in list(cat_ids or []):
            for is_type in (False, True):
                try:
                    col = DB.FilteredElementCollector(self.doc).OfCategoryId(cid)
                    col = col.WhereElementIsElementType() if is_type \
                        else col.WhereElementIsNotElementType()
                    el = col.FirstElement()
                except Exception:
                    el = None
                if el is None:
                    continue
                param = None
                try:
                    param = el.get_Parameter(bip) if bip is not None else el.get_Parameter(pid)
                except Exception:
                    param = None
                if param is None:
                    try:
                        tp = self.doc.GetElement(el.GetTypeId())
                        if tp is not None:
                            param = tp.get_Parameter(bip) if bip is not None \
                                else tp.get_Parameter(pid)
                    except Exception:
                        param = None
                if param is not None:
                    return param
        return None

    def to_display(self, value, unit):
        if unit is None:
            return fmt_num(value)
        try:
            return fmt_num(DB.UnitUtils.ConvertFromInternalUnits(float(value), unit))
        except Exception:
            return fmt_num(value)

    def to_internal(self, value, unit):
        v = float(value)
        if unit is None:
            return v
        try:
            return DB.UnitUtils.ConvertToInternalUnits(v, unit)
        except Exception:
            return v


def extract_element_filter(ef, state, depth=0):
    """Flatten a Revit ElementFilter into a list of FilterRule objects."""
    if ef is None or depth > 6:
        state['complex'] = True
        return
    try:
        if isinstance(ef, DB.ElementParameterFilter):
            try:
                if ef.Inverted:
                    state['complex'] = True
            except Exception:
                pass
            for rule in ef.GetRules():
                state['rules'].append(rule)
            return
        if isinstance(ef, DB.LogicalAndFilter) or isinstance(ef, DB.LogicalOrFilter):
            logic = 'AND' if isinstance(ef, DB.LogicalAndFilter) else 'OR'
            children = list(ef.GetFilters())
            real_children = [c for c in children
                             if not isinstance(c, (DB.ElementMulticategoryFilter,
                                                   DB.ElementCategoryFilter,
                                                   DB.ElementClassFilter))]
            if len(real_children) > 1:
                if state['logic'] is None:
                    state['logic'] = logic
                elif state['logic'] != logic:
                    state['complex'] = True
            for child in real_children:
                extract_element_filter(child, state, depth + 1)
            return
        if isinstance(ef, (DB.ElementMulticategoryFilter,
                           DB.ElementCategoryFilter,
                           DB.ElementClassFilter)):
            return
    except Exception:
        pass
    state['complex'] = True
    state['other'].append(ef.GetType().Name if ef is not None else 'None')


def rule_to_parts(rule, resolver, cat_ids):
    """FilterRule -> (param_name, operator, value_text, ok)."""
    negate = False
    try:
        if isinstance(rule, DB.FilterInverseRule):
            rule = rule.GetInnerRule()
            negate = True
    except Exception:
        pass

    pid = None
    for attr in ('GetRuleParameter',):
        try:
            pid = getattr(rule, attr)()
            break
        except Exception:
            pid = None
    if pid is None:
        return ('?', rule.GetType().Name, '', False)

    pname = resolver.name(pid)
    cls = rule.GetType().Name
    op = None
    value = ''

    try:
        evaluator = rule.GetEvaluator()
        op = OP_FROM_EVALUATOR.get(evaluator.GetType().Name)
    except Exception:
        op = None

    if op is None:
        low = cls.lower()
        if 'hasnovalue' in low:
            op = 'has no value'
        elif 'hasvalue' in low:
            op = 'has value'

    try:
        if isinstance(rule, DB.FilterStringRule):
            value = safe_str(rule.RuleString)
        elif isinstance(rule, DB.FilterDoubleRule):
            _kind, unit = resolver.kind(pid, cat_ids)
            value = resolver.to_display(rule.RuleValue, unit)
        elif isinstance(rule, DB.FilterIntegerRule):
            value = fmt_num(rule.RuleValue)
        elif isinstance(rule, DB.FilterElementIdRule):
            rid = rule.RuleValue
            el = resolver.doc.GetElement(rid)
            nm = ''
            try:
                nm = el.Name if el is not None else ''
            except Exception:
                nm = ''
            value = '%s [%d]' % (nm, eid_int(rid)) if nm else '[%d]' % eid_int(rid)
        else:
            try:
                value = safe_str(rule.RuleString)
            except Exception:
                value = ''
    except Exception:
        value = ''

    if op is None:
        return (pname, cls, value, False)

    if negate:
        op = NEGATED_OP.get(op, 'not ' + op)

    return (pname, op, value, True)


def rule_text(parts):
    pname, op, value, _ok = parts
    if op in ('has value', 'has no value'):
        return u'[%s] %s' % (pname, op)
    if value == '':
        return u'[%s] %s ""' % (pname, op)
    return u'[%s] %s %s' % (pname, op, value)


# ---------------------------------------------------------------------------
#  MODEL READING
# ---------------------------------------------------------------------------
def template_controls_filters(doc, view, cache=None):
    """True when the view's template controls its filters.

    The answer depends only on the template, so pass a dict as cache when asking
    for many views: a model with hundreds of views on a handful of templates then
    reads each template's non-controlled list once instead of once per view.
    """
    try:
        tid = view.ViewTemplateId
        if tid is None or tid == DB.ElementId.InvalidElementId:
            return False
        key = eid_int(tid)
        if cache is not None and key in cache:
            return cache[key]
        tpl = doc.GetElement(tid)
        answer = False
        if tpl is not None:
            non_controlled = set(eid_int(i)
                                 for i in tpl.GetNonControlledTemplateParameterIds())
            answer = eid_int(DB.ElementId(DB.BuiltInParameter.VIS_GRAPHICS_FILTERS)) \
                not in non_controlled
        if cache is not None:
            cache[key] = answer
        return answer
    except Exception:
        return False


def gather_usage(doc):
    usage = {}
    template_cache = {}
    try:
        views = DB.FilteredElementCollector(doc).OfClass(DB.View).ToElements()
    except Exception:
        views = []
    for v in views:
        try:
            if not v.AreGraphicsOverridesAllowed():
                continue
        except Exception:
            continue
        try:
            fids = list(v.GetFilters())
        except Exception:
            continue
        if not fids:
            continue
        try:
            is_tpl = v.IsTemplate
        except Exception:
            is_tpl = False
        inherited = (not is_tpl) and template_controls_filters(doc, v, template_cache)
        try:
            vname = v.Name
        except Exception:
            vname = 'View %d' % eid_int(v.Id)
        for fid in fids:
            key = eid_int(fid)
            rec = usage.get(key)
            if rec is None:
                rec = {'views': [], 'templates': [], 'inherited': []}
                usage[key] = rec
            if is_tpl:
                rec['templates'].append(vname)
            elif inherited:
                rec['inherited'].append(vname)
            else:
                rec['views'].append(vname)
    return usage


def gather_filters(doc, include_selection=True, usage=None):
    """Read every filter in the project into a list of plain dicts.

    Pass a previously built usage map to skip the (expensive) sweep of every
    view in the model - renames and rule edits cannot change filter usage.
    """
    resolver = ParamResolver(doc)
    if usage is None:
        usage = gather_usage(doc)
    rows = []

    pfes = DB.FilteredElementCollector(doc).OfClass(DB.ParameterFilterElement).ToElements()
    for pfe in pfes:
        fid = eid_int(pfe.Id)
        try:
            cat_ids = list(pfe.GetCategories())
        except Exception:
            cat_ids = []
        cat_names = []
        for cid in cat_ids:
            try:
                cat = DB.Category.GetCategory(doc, cid)
                cat_names.append(cat.Name if cat is not None else 'Category %d' % eid_int(cid))
            except Exception:
                cat_names.append('Category %d' % eid_int(cid))
        cat_names.sort()

        state = {'logic': None, 'rules': [], 'complex': False, 'other': []}
        try:
            extract_element_filter(pfe.GetElementFilter(), state)
        except Exception:
            state['complex'] = True

        rule_texts = []
        norm_rules = []
        for rule in state['rules']:
            parts = rule_to_parts(rule, resolver, cat_ids)
            rule_texts.append(rule_text(parts))
            if not parts[3]:
                state['complex'] = True
            norm_rules.append(u'%s|%s|%s' % (parts[0].strip().lower(),
                                             parts[1].strip().lower(),
                                             safe_str(parts[2]).strip().lower()))

        logic = state['logic'] or 'AND'
        rec_usage = usage.get(fid, {'views': [], 'templates': [], 'inherited': []})

        if state['complex']:
            status = 'Complex - read only'
        elif not rule_texts:
            status = 'No rules'
        elif not rec_usage['views'] and not rec_usage['templates']:
            status = 'Unused'
        else:
            status = 'OK'

        signature = None
        if not state['complex'] and rule_texts:
            signature = u'RULES||%s||%s||%s' % (
                u','.join([c.lower() for c in cat_names]),
                logic,
                u';'.join(sorted(norm_rules)))

        rows.append({
            'id': fid,
            'name': safe_str(pfe.Name),
            'kind': 'Rules',
            'cat_names': cat_names,
            'cat_ids': [eid_int(c) for c in cat_ids],
            'logic': logic,
            'rule_texts': rule_texts,
            'complex': state['complex'],
            'signature': signature,
            # exact values the duplicate rules compare - rules sorted so the
            # order they were written in does not matter
            'dup': {
                'Categories': u','.join([c.lower() for c in cat_names]),
                'Logic': logic.lower(),
                'Rules': u';'.join(sorted(norm_rules)),
            },
            'views': rec_usage['views'],
            'templates': rec_usage['templates'],
            'inherited': rec_usage['inherited'],
            'status': status,
        })

    if include_selection:
        try:
            sfes = DB.FilteredElementCollector(doc)\
                .OfClass(DB.SelectionFilterElement).ToElements()
        except Exception:
            sfes = []
        for sfe in sfes:
            fid = eid_int(sfe.Id)
            try:
                count = len(list(sfe.GetElementIds()))
            except Exception:
                count = 0
            rec_usage = usage.get(fid, {'views': [], 'templates': [], 'inherited': []})
            rows.append({
                'id': fid,
                'name': safe_str(sfe.Name),
                'kind': 'Selection',
                'cat_names': [],
                'cat_ids': [],
                'logic': '',
                'rule_texts': [u'(selection filter - %d element(s))' % count],
                'complex': True,
                'signature': None,
                'views': rec_usage['views'],
                'templates': rec_usage['templates'],
                'inherited': rec_usage['inherited'],
                'status': 'Selection - read only',
            })

    rows.sort(key=lambda r: r['name'].lower())
    return rows, usage


class GroupRegistry(object):
    """Keeps a duplicate group's letter and colour attached to its rule signature.

    Without this, groups are numbered by position each time the model is read, so
    merging group B away renames C to B and hands it B's colour - every remaining
    swatch changes meaning under the user. Here a signature keeps its letter and
    colour for as long as it is still a duplicate, and only when a group is fully
    resolved are they released for a future group to reuse.
    """

    def __init__(self):
        self.assigned = {}          # signature -> (label, colour)

    def labels_in_use(self):
        return set(label for label, _colour in self.assigned.values())

    def colours_in_use(self):
        return set(colour for _label, colour in self.assigned.values())

    def next_free(self):
        used_labels = self.labels_in_use()
        used_colours = self.colours_in_use()
        label = None
        for index in range(len(GROUP_LABELS) * 27):
            candidate = group_label(index)
            if candidate not in used_labels:
                label = candidate
                break
        if label is None:
            label = group_label(len(self.assigned))
        colour = None
        for candidate in GROUP_COLOURS:
            if candidate not in used_colours:
                colour = candidate
                break
        if colour is None:
            colour = GROUP_COLOURS[len(self.assigned) % len(GROUP_COLOURS)]
        return label, colour

    def resolve(self, signatures):
        """Assign to any new signature, release any that is no longer a duplicate."""
        wanted = set(signatures)
        released = []
        for sig in list(self.assigned.keys()):
            if sig not in wanted:
                released.append(self.assigned.pop(sig))
        for sig in signatures:
            if sig not in self.assigned:
                self.assigned[sig] = self.next_free()
        return released

    def get(self, signature):
        return self.assigned.get(signature, ('', ''))


def dup_value(row, key):
    """The value a duplicate rule compares for one row.

    Readers may store an exact form in row['dup'] - a raw double rather than the
    rounded string the table shows, so 2.5 mm and 2.54 mm are not reported as the
    same just because the project rounds both to 3 mm. Anything else falls back
    to the displayed value, trimmed and lower-cased.
    """
    exact = row.get('dup')
    if exact and key in exact:
        return safe_str(exact[key])
    return safe_str(row['values'].get(key, '')).strip().lower()


def build_signature(row, keys, scope=u''):
    """One string per row: two rows are duplicates when their strings match."""
    parts = [scope]
    for key in keys:
        parts.append(u'%s=%s' % (key, dup_value(row, key)))
    return u'||'.join(parts)


def choose_keeper(members):
    """The style a duplicate group is merged into: the one with the most elements
    using it. A tie goes to the name that sorts first, so the choice is the same
    every time rather than depending on read order."""
    def key(row):
        uses = row.get('usage')
        try:
            uses = int(uses or 0)
        except Exception:
            uses = 0
        return (-uses, safe_str(row.get('name', '')).lower())
    return sorted(members, key=key)[0]


def compute_duplicates(rows, registry=None):
    """Assign duplicate group letters and colours. Returns list of group dicts.

    Pass the panel's GroupRegistry so a group keeps the same letter and colour
    from one read to the next.
    """
    buckets = {}
    for row in rows:
        row['group'] = ''
        row['chip'] = ''
        sig = row.get('signature')
        if not sig:
            continue
        buckets.setdefault(sig, []).append(row)

    dup_sigs = [(sig, members) for sig, members in buckets.items() if len(members) > 1]
    dup_sigs.sort(key=lambda item: item[1][0]['name'].lower())

    if registry is None:
        registry = GroupRegistry()
    registry.resolve([sig for sig, _members in dup_sigs])

    groups = []
    for sig, members in dup_sigs:
        label, colour = registry.get(sig)
        for member in members:
            member['group'] = label
            member['chip'] = colour
        groups.append({
            'label': label,
            'colour': colour,
            'signature': sig,
            'count': len(members),
            'members': [m['id'] for m in members],
            'names': [m['name'] for m in members],
        })
    groups.sort(key=lambda g: (len(g['label']), g['label']))
    return groups


# ---------------------------------------------------------------------------
#  EXCEL (COM) - DiRoots style round trip, driven by a panel's column spec
# ---------------------------------------------------------------------------
XL_HDR_EDIT = 'F07C10'
XL_HDR_LOCK = '7F7F7F'
XL_BODY_EDIT = 'FBE0C6'
XL_BODY_LOCK = 'E3E3E3'


def _bgr(hex_str):
    hex_str = hex_str.lstrip('#')
    r = int(hex_str[0:2], 16)
    g = int(hex_str[2:4], 16)
    b = int(hex_str[4:6], 16)
    return r + (g * 256) + (b * 65536)


def _get_excel():
    xl_type = Type.GetTypeFromProgID('Excel.Application')
    if xl_type is None:
        raise Exception('Microsoft Excel is not installed or not registered on this machine.')
    return Activator.CreateInstance(xl_type)


def _release(obj):
    try:
        if obj is not None:
            Marshal.ReleaseComObject(obj)
    except Exception:
        pass


def export_to_excel(columns, rows, path, project_name, sheet_name, notes):
    """Write one panel's table to a formatted, filterable workbook.

    columns is the panel column spec: dicts with header / name / edit.
    rows is a list of {'Id': .., 'values': {column name: value}} dicts.
    """
    xl = None
    wb = None
    try:
        xl = _get_excel()
        xl.Visible = False
        xl.DisplayAlerts = False
        wb = xl.Workbooks.Add()
        try:
            ws = wb.Worksheets(1)
        except Exception:
            ws = wb.Worksheets[1]
        ws.Name = sheet_name

        headers = [c['header'] for c in columns]
        n_rows = len(rows)
        n_cols = len(headers)
        arr = Array.CreateInstance(clr.GetClrType(Object), n_rows + 1, n_cols)
        for c in range(n_cols):
            arr[0, c] = headers[c]
        for r in range(n_rows):
            values = rows[r]
            for c in range(n_cols):
                arr[r + 1, c] = values.get(columns[c]['name'], '')

        rng = ws.Range(ws.Cells(1, 1), ws.Cells(n_rows + 1, n_cols))
        rng.Value2 = arr

        try:
            lo = ws.ListObjects.Add(1, rng, Type.Missing, 1)
            lo.Name = 'RevoBIM_%s' % re.sub(r'[^A-Za-z0-9_]', '', sheet_name)
            lo.TableStyle = 'TableStyleLight1'
            lo.ShowTableStyleRowStripes = False
        except Exception:
            try:
                rng.AutoFilter(1)
            except Exception:
                pass

        for c in range(n_cols):
            editable = bool(columns[c].get('edit'))
            hdr = ws.Cells(1, c + 1)
            hdr.Interior.Color = _bgr(XL_HDR_EDIT if editable else XL_HDR_LOCK)
            hdr.Font.Bold = True
            hdr.Font.Color = _bgr('FFFFFF')
            if n_rows:
                body = ws.Range(ws.Cells(2, c + 1), ws.Cells(n_rows + 1, c + 1))
                body.Interior.Color = _bgr(XL_BODY_EDIT if editable else XL_BODY_LOCK)
                body.Font.Color = _bgr('1E1E1E')
                if not editable:
                    body.Locked = True
            try:
                width = columns[c].get('xl_width')
                if width:
                    ws.Columns(c + 1).ColumnWidth = width
                    if columns[c].get('wrap'):
                        ws.Columns(c + 1).WrapText = True
                else:
                    ws.Columns(c + 1).AutoFit()
            except Exception:
                pass

        ws.Rows(1).RowHeight = 22
        try:
            ws.Range(ws.Cells(1, 1), ws.Cells(n_rows + 1, n_cols)).VerticalAlignment = -4160
        except Exception:
            pass

        try:
            ws.Activate()
            xl.ActiveWindow.FreezePanes = False
            xl.ActiveWindow.SplitRow = 1
            xl.ActiveWindow.SplitColumn = 0
            xl.ActiveWindow.FreezePanes = True
        except Exception:
            pass

        try:
            info = wb.Worksheets.Add(Type.Missing, ws)
            info.Name = 'RevoBIM PY'
            meta = [('%s - %s' % (BRAND, TOOL_NAME), ''),
                    ('Version', VERSION),
                    ('Tab', sheet_name),
                    ('Exported', datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
                    ('Project', project_name),
                    ('Rows exported', str(n_rows)),
                    ('', ''),
                    ('How to use', 'Edit the ORANGE cells only, save, then use Import from '
                                   'Excel. Edits are staged in the window - nothing reaches '
                                   'the model until you press APPLY CHANGES.'),
                    ('Grey columns', 'Read only - changes are ignored on import.')]
            for label, text in notes:
                meta.append((label, text))
            for i, (k, v) in enumerate(meta):
                info.Cells(i + 1, 1).Value2 = k
                info.Cells(i + 1, 2).Value2 = v
            info.Cells(1, 1).Font.Bold = True
            info.Cells(1, 1).Font.Size = 14
            info.Cells(1, 1).Font.Color = _bgr('3D9BE9')
            legend_row = len(meta) + 2
            info.Cells(legend_row, 1).Value2 = 'Legend'
            info.Cells(legend_row, 1).Font.Bold = True
            info.Cells(legend_row + 1, 1).Value2 = 'Editable'
            info.Cells(legend_row + 1, 2).Interior.Color = _bgr(XL_BODY_EDIT)
            info.Cells(legend_row + 2, 1).Value2 = 'Read only'
            info.Cells(legend_row + 2, 2).Interior.Color = _bgr(XL_BODY_LOCK)
            info.Columns(1).ColumnWidth = 20
            info.Columns(2).ColumnWidth = 95
            info.Columns(2).WrapText = True
        except Exception:
            pass

        try:
            ws.Activate()
            ws.Cells(2, 2).Select()
        except Exception:
            pass

        if os.path.isfile(path):
            try:
                os.remove(path)
            except Exception:
                pass
        wb.SaveAs(path, 51)
        wb.Close(False)
        xl.Quit()
        return True
    finally:
        _release(wb)
        _release(xl)
        try:
            System.GC.Collect()
            System.GC.WaitForPendingFinalizers()
        except Exception:
            pass


def import_from_excel(path, sheet_name=None):
    """Read a sheet back into a list of dicts keyed by lower-case header."""
    xl = None
    wb = None
    try:
        xl = _get_excel()
        xl.Visible = False
        xl.DisplayAlerts = False
        wb = xl.Workbooks.Open(path, False, True)
        ws = None
        wanted = safe_str(sheet_name).strip().lower()
        for i in range(1, wb.Worksheets.Count + 1):
            try:
                sheet = wb.Worksheets(i)
            except Exception:
                sheet = wb.Worksheets[i]
            name = safe_str(sheet.Name).strip().lower()
            if name == 'revobim py':
                continue
            if not wanted or name == wanted:
                ws = sheet
                break
        if ws is None:
            try:
                ws = wb.Worksheets(1)
            except Exception:
                ws = wb.Worksheets[1]

        used = ws.UsedRange
        n_rows = used.Rows.Count
        n_cols = used.Columns.Count
        values = used.Value2

        def cell(r, c):
            try:
                return values.GetValue(r, c)
            except Exception:
                return None

        headers = {}
        for c in range(1, n_cols + 1):
            h = safe_str(cell(1, c)).strip().lower()
            if h:
                headers[h] = c

        records = []
        for r in range(2, n_rows + 1):
            rec = {}
            empty = True
            for name, c in headers.items():
                text = safe_str(cell(r, c)).strip()
                if text:
                    empty = False
                rec[name] = text
            if not empty:
                rec['_excel_row'] = r
                records.append(rec)

        wb.Close(False)
        xl.Quit()
        return records, safe_str(ws.Name)
    finally:
        _release(wb)
        _release(xl)
        try:
            System.GC.Collect()
            System.GC.WaitForPendingFinalizers()
        except Exception:
            pass


# ---------------------------------------------------------------------------
#  RULE PARSING AND CONSTRUCTION
# ---------------------------------------------------------------------------
def split_list(text):
    if not text:
        return []
    parts = re.split(r'[;\n\r]+|,\s', text)
    return [p.strip().strip(',').strip() for p in parts if p and p.strip().strip(',').strip()]


def parse_rule_line(line):
    """'[Param] operator value' -> (param_name, operator, value) or None."""
    line = safe_str(line).strip()
    if not line:
        return None
    match = re.match(r'^\s*\[(?P<p>[^\]]+)\]\s*(?P<rest>.*)$', line)
    if not match:
        return None
    pname = match.group('p').strip()
    rest = match.group('rest').strip()
    low = rest.lower()
    for op in PARSE_OPS:
        if low.startswith(op):
            value = rest[len(op):].strip()
            if value.startswith('"') and value.endswith('"') and len(value) >= 2:
                value = value[1:-1]
            return (pname, OP_ALIASES.get(op, op), value)
    return None


def build_category_map(doc):
    lookup = {}
    try:
        for cid in DB.ParameterFilterUtilities.GetAllFilterableCategories():
            try:
                cat = DB.Category.GetCategory(doc, cid)
                if cat is not None:
                    lookup[cat.Name.strip().lower()] = cid
            except Exception:
                pass
    except Exception:
        pass
    return lookup


def build_param_map(doc, cat_ids, resolver):
    lookup = {}
    try:
        ids = DB.ParameterFilterUtilities.GetFilterableParametersInCommon(
            doc, List[DB.ElementId](cat_ids))
        for pid in ids:
            lookup[resolver.name(pid).strip().lower()] = pid
    except Exception:
        pass
    return lookup


def make_filter_rule(pid, op, value, kind, unit, doc):
    F = DB.ParameterFilterRuleFactory
    op = op.strip().lower()

    if op == 'has value':
        return F.CreateHasValueParameterRule(pid)
    if op == 'has no value':
        return F.CreateHasNoValueParameterRule(pid)

    if kind is None:
        try:
            float(value)
            kind = 'double'
        except Exception:
            kind = 'string'

    if kind == 'string':
        makers = {
            'equals': F.CreateEqualsRule,
            'not equals': F.CreateNotEqualsRule,
            'contains': F.CreateContainsRule,
            'does not contain': F.CreateNotContainsRule,
            'begins with': F.CreateBeginsWithRule,
            'does not begin with': F.CreateNotBeginsWithRule,
            'ends with': F.CreateEndsWithRule,
            'does not end with': F.CreateNotEndsWithRule,
            '>': F.CreateGreaterRule,
            '>=': F.CreateGreaterOrEqualRule,
            '<': F.CreateLessRule,
            '<=': F.CreateLessOrEqualRule,
        }
        maker = makers.get(op)
        if maker is None:
            raise Exception('operator "%s" is not valid for a text parameter' % op)
        return maker(pid, safe_str(value))

    if kind == 'elementid':
        eid = None
        match = re.search(r'\[(\d+)\]\s*$', value)
        if match:
            eid = DB.ElementId(int(match.group(1)))
        else:
            name = value.strip()
            for el in DB.FilteredElementCollector(doc).WhereElementIsNotElementType():
                try:
                    if el.Name == name:
                        eid = el.Id
                        break
                except Exception:
                    continue
        if eid is None:
            raise Exception('could not resolve element value "%s"' % value)
        makers = {
            'equals': F.CreateEqualsRule,
            'not equals': F.CreateNotEqualsRule,
            '>': F.CreateGreaterRule,
            '>=': F.CreateGreaterOrEqualRule,
            '<': F.CreateLessRule,
            '<=': F.CreateLessOrEqualRule,
        }
        maker = makers.get(op)
        if maker is None:
            raise Exception('operator "%s" is not valid for an element parameter' % op)
        return maker(pid, eid)

    if kind == 'int':
        low = value.strip().lower()
        if low in ('yes', 'true'):
            ival = 1
        elif low in ('no', 'false'):
            ival = 0
        else:
            ival = int(round(float(value)))
        makers = {
            'equals': F.CreateEqualsRule,
            'not equals': F.CreateNotEqualsRule,
            '>': F.CreateGreaterRule,
            '>=': F.CreateGreaterOrEqualRule,
            '<': F.CreateLessRule,
            '<=': F.CreateLessOrEqualRule,
        }
        maker = makers.get(op)
        if maker is None:
            raise Exception('operator "%s" is not valid for an integer parameter' % op)
        return maker(pid, ival)

    # double
    resolver_value = float(value) if unit is None else \
        DB.UnitUtils.ConvertToInternalUnits(float(value), unit)
    eps = 1e-06
    makers = {
        'equals': lambda p, v: F.CreateEqualsRule(p, v, eps),
        'not equals': lambda p, v: F.CreateNotEqualsRule(p, v, eps),
        '>': lambda p, v: F.CreateGreaterRule(p, v, eps),
        '>=': lambda p, v: F.CreateGreaterOrEqualRule(p, v, eps),
        '<': lambda p, v: F.CreateLessRule(p, v, eps),
        '<=': lambda p, v: F.CreateLessOrEqualRule(p, v, eps),
    }
    maker = makers.get(op)
    if maker is None:
        raise Exception('operator "%s" is not valid for a numeric parameter' % op)
    return maker(pid, resolver_value)


def build_element_filter(rules, logic):
    rule_list = List[DB.FilterRule]()
    for r in rules:
        rule_list.Add(r)
    if logic.strip().upper() == 'OR' and len(rules) > 1:
        filters = List[DB.ElementFilter]()
        for r in rules:
            single = List[DB.FilterRule]()
            single.Add(r)
            filters.Add(DB.ElementParameterFilter(single))
        return DB.LogicalOrFilter(filters)
    return DB.ElementParameterFilter(rule_list)


def normalise_rule_lines(lines):
    out = []
    for line in lines:
        text = re.sub(r'\s+', ' ', safe_str(line).strip())
        if text:
            out.append(text.lower())
    out.sort()
    return out


def is_writable(doc, element):
    """Can this element actually be edited right now?"""
    try:
        if element is None:
            return False, 'element no longer exists'
        if doc.IsWorkshared:
            status = DB.WorksharingUtils.GetCheckoutStatus(doc, element.Id)
            if status == DB.CheckoutStatus.OwnedByOtherUser:
                owner = ''
                try:
                    owner = DB.WorksharingUtils.GetWorksharingTooltipInfo(
                        doc, element.Id).Owner
                except Exception:
                    owner = 'another user'
                return False, 'checked out by %s' % (owner or 'another user')
    except Exception:
        pass
    return True, ''


def unique_name_in(base, taken):
    """base, or base (2), base (3)... against a set of lowercase names."""
    base = safe_str(base).strip() or 'Filter'
    name = base
    counter = 2
    while name.lower() in taken:
        name = '%s (%d)' % (base, counter)
        counter += 1
        if counter > 999:
            break
    return name


def diff_excel_records(records, rows):
    """Compare a workbook against the in-memory model snapshot.

    Nothing is written here - this only works out what *would* change.
    Returns (pending, created, log_lines).
    """
    pending = {}
    created = []
    lines = []
    ignored = 0
    matched = 0
    by_id = dict((r['id'], r) for r in rows)

    for rec in records:
        excel_row = rec.get('_excel_row', '?')
        raw_id = rec.get('filter id', '').strip()
        name = rec.get('filter name', '').strip()
        cats_text = rec.get('categories', '').strip()
        logic = (rec.get('logic', '') or '').strip().upper()
        rules_text = rec.get('rules', '')

        if raw_id == '' or raw_id.upper() == 'NEW':
            if not name:
                lines.append('Row %s: ignored - a new filter needs a name' % excel_row)
                continue
            if not cats_text or not safe_str(rules_text).strip():
                lines.append('Row %s: ignored - a new filter needs categories and rules'
                             % excel_row)
                continue
            created.append({'name': name, 'cats': cats_text,
                            'logic': logic or 'AND', 'rules': rules_text,
                            'row': excel_row})
            continue

        try:
            fid = int(float(raw_id))
        except Exception:
            lines.append('Row %s: ignored - unreadable Filter Id "%s"' % (excel_row, raw_id))
            continue

        snapshot = by_id.get(fid)
        if snapshot is None:
            lines.append('Row %s: ignored - filter id %d is not in this model'
                         % (excel_row, fid))
            continue

        change = {}
        if name and name != snapshot['name']:
            change['name'] = name

        read_only_rules = snapshot['kind'] != 'Rules' or snapshot['complex']
        wanted_rules = normalise_rule_lines(
            safe_str(rules_text).replace('\r', '\n').split('\n'))
        current_rules = normalise_rule_lines(snapshot['rule_texts'])
        rules_edited = bool(safe_str(rules_text).strip()) and wanted_rules != current_rules

        if read_only_rules:
            if rules_edited or (cats_text and
                                [c.lower() for c in split_list(cats_text)] !=
                                sorted([c.lower() for c in snapshot['cat_names']])):
                ignored += 1
                lines.append('Row %s: rule and category edits ignored for "%s" - %s'
                             % (excel_row, snapshot['name'],
                                'selection filter' if snapshot['kind'] != 'Rules'
                                else 'nested or inverted condition set'))
        else:
            if cats_text:
                wanted_cats = sorted([c.strip().lower() for c in split_list(cats_text)])
                current_cats = sorted([c.strip().lower() for c in snapshot['cat_names']])
                if wanted_cats != current_cats:
                    change['cats'] = cats_text
            if rules_edited:
                change['rules'] = rules_text
            if logic in ('AND', 'OR') and logic != snapshot['logic']:
                change['logic'] = logic

        if change:
            change['source'] = 'Excel row %s' % excel_row
            pending[fid] = change
        else:
            matched += 1

    lines.insert(0, '%d filter(s) with pending edits, %d new filter(s), %d row(s) already '
                    'matched the model, %d edit(s) ignored as not writable.'
                 % (len(pending), len(created), matched, ignored))
    return pending, created, lines


class WarningSwallower(DB.IFailuresPreprocessor):
    """Keep Revit quiet while a batch of filter edits is committed."""

    def PreprocessFailures(self, accessor):
        try:
            accessor.DeleteAllWarnings()
        except Exception:
            pass
        return DB.FailureProcessingResult.Continue


def resolve_categories(cat_lookup, cats_text):
    """Text -> ([ElementId], [unknown names])."""
    cat_ids = []
    bad = []
    for cname in split_list(cats_text):
        cid = cat_lookup.get(cname.strip().lower())
        if cid is None:
            bad.append(cname)
        else:
            cat_ids.append(cid)
    return cat_ids, bad


def build_rules(doc, resolver, cat_ids, rules_text, param_lookup=None):
    """Text block -> ([FilterRule], error_message)."""
    if param_lookup is None:
        param_lookup = build_param_map(doc, cat_ids, resolver)
    rules = []
    text = safe_str(rules_text).replace('\r', '\n').replace('|', '\n')
    for line in text.split('\n'):
        line = line.strip()
        if not line:
            continue
        parsed = parse_rule_line(line)
        if parsed is None:
            return [], 'cannot read rule "%s"' % line
        pname, op, value = parsed
        pid = param_lookup.get(pname.strip().lower())
        if pid is None:
            return [], 'parameter "%s" is not filterable for these categories' % pname
        p_kind, p_unit = resolver.kind(pid, cat_ids)
        try:
            rules.append(make_filter_rule(pid, op, value, p_kind, p_unit, doc))
        except Exception as ex:
            return [], 'rule "%s" - %s' % (line, ex)
    return rules, ''


def merge_filters(doc, keep_id, drop_ids, transfer_overrides=True, delete_after=True):
    """Repoint every view/template from drop filters onto the keep filter."""
    log_lines = []
    keep_eid = DB.ElementId(keep_id)
    drop_set = set(drop_ids)
    repointed = 0
    view_hits = 0
    skipped_views = []

    keep_el = doc.GetElement(keep_eid)
    keep_name = keep_el.Name if keep_el is not None else str(keep_id)

    tg = DB.TransactionGroup(doc, 'RevoBIM PY - Merge Filters')
    tg.Start()
    try:
        views = DB.FilteredElementCollector(doc).OfClass(DB.View).ToElements()
        for v in views:
            try:
                if not v.AreGraphicsOverridesAllowed():
                    continue
                current = set(eid_int(f) for f in v.GetFilters())
            except Exception:
                continue
            present = current & drop_set
            if not present:
                continue
            try:
                if not v.IsTemplate and template_controls_filters(doc, v):
                    continue
            except Exception:
                pass

            try:
                vname = v.Name
            except Exception:
                vname = 'View %d' % eid_int(v.Id)

            trans = DB.Transaction(doc, 'Merge filters in view')
            trans.Start()
            try:
                has_keep = keep_id in current
                for dropped in present:
                    drop_eid = DB.ElementId(dropped)
                    overrides = None
                    visible = True
                    try:
                        overrides = v.GetFilterOverrides(drop_eid)
                        visible = v.GetFilterVisibility(drop_eid)
                    except Exception:
                        overrides = None
                    if not has_keep:
                        v.AddFilter(keep_eid)
                        has_keep = True
                        if transfer_overrides and overrides is not None:
                            try:
                                v.SetFilterOverrides(keep_eid, overrides)
                                v.SetFilterVisibility(keep_eid, visible)
                            except Exception:
                                pass
                    v.RemoveFilter(drop_eid)
                    repointed += 1
                trans.Commit()
                view_hits += 1
                log_lines.append('  %s%s: %d filter(s) repointed to "%s"'
                                 % ('[Template] ' if v.IsTemplate else '', vname,
                                    len(present), keep_name))
            except Exception as ex:
                try:
                    trans.RollBack()
                except Exception:
                    pass
                skipped_views.append('%s (%s)' % (vname, ex))

        if delete_after:
            trans = DB.Transaction(doc, 'Delete merged filters')
            trans.Start()
            try:
                ids = List[DB.ElementId]()
                names = []
                for dropped in drop_ids:
                    el = doc.GetElement(DB.ElementId(dropped))
                    if el is not None:
                        ids.Add(DB.ElementId(dropped))
                        names.append(el.Name)
                if ids.Count:
                    doc.Delete(ids)
                    log_lines.append('Deleted %d filter(s): %s' % (len(names), ', '.join(names)))
                trans.Commit()
            except Exception as ex:
                try:
                    trans.RollBack()
                except Exception:
                    pass
                log_lines.append('Could not delete merged filters: %s' % ex)
        tg.Assimilate()
    except Exception as ex:
        try:
            tg.RollBack()
        except Exception:
            pass
        log_lines.append('Merge aborted: %s' % ex)
        raise

    for sv in skipped_views:
        log_lines.append('  Skipped %s' % sv)
    log_lines.insert(0, 'Merged into "%s": %d placement(s) across %d view(s)/template(s).'
                     % (keep_name, repointed, view_hits))
    return log_lines


# ---------------------------------------------------------------------------
#  EXTERNAL EVENT HANDLER
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
#  FILTER PANEL - staged writes and deletion
# ---------------------------------------------------------------------------
def write_filter_changes(doc, rows, pending, created):
    """Write staged filter edits. Runs INSIDE a transaction opened by the caller,
    so a whole batch across every tab costs one regeneration."""
    lines = []
    changed = []
    snapshot = dict((r['id'], r) for r in rows)
    resolver = ParamResolver(doc)
    cat_lookup = build_category_map(doc)
    param_cache = {}
    names = set(safe_str(r['name']).lower() for r in rows)

    def params_for(cat_ids):
        key = tuple(sorted(eid_int(c) for c in cat_ids))
        if key not in param_cache:
            param_cache[key] = build_param_map(doc, cat_ids, resolver)
        return param_cache[key]

    for fid in sorted(pending.keys()):
        change = pending[fid]
        row = snapshot.get(fid)
        element = doc.GetElement(DB.ElementId(fid))
        if row is None or element is None:
            lines.append('Skipped id %d - no longer in the model' % fid)
            continue
        writable, why = is_writable(doc, element)
        if not writable:
            lines.append('Skipped "%s" - %s' % (row['name'], why))
            continue

        done = []
        if change.get('name'):
            wanted = safe_str(change['name']).strip()
            old = safe_str(row['name'])
            names.discard(old.lower())
            final = unique_name_in(wanted, names)
            try:
                element.Name = final
                names.add(final.lower())
                note = 'renamed "%s" -> "%s"' % (old, final)
                if final != wanted:
                    note += ' ("%s" was already in use)' % wanted
                done.append(note)
            except Exception as ex:
                names.add(old.lower())
                lines.append('Could not rename "%s" - %s' % (old, ex))

        cat_ids = [DB.ElementId(c) for c in row.get('cat_ids', [])]
        if change.get('cats'):
            parsed, bad = resolve_categories(cat_lookup, change['cats'])
            if bad:
                lines.append('"%s": ignored categories Revit cannot filter on - %s'
                             % (row['name'], ', '.join(bad)))
            if parsed:
                try:
                    cats = List[DB.ElementId]()
                    for cid in parsed:
                        cats.Add(cid)
                    element.SetCategories(cats)
                    cat_ids = parsed
                    done.append('categories updated')
                except Exception as ex:
                    lines.append('"%s": categories not changed - %s' % (row['name'], ex))

        if change.get('rules') or change.get('logic'):
            text = change.get('rules') or u'\n'.join(row['rule_texts'])
            want_logic = change.get('logic') or row['logic'] or 'AND'
            rules, err = build_rules(doc, resolver, cat_ids, text, params_for(cat_ids))
            if err:
                lines.append('"%s": rules not changed - %s' % (row['name'], err))
            elif not rules:
                lines.append('"%s": rules not changed - nothing readable' % row['name'])
            else:
                try:
                    element.SetElementFilter(build_element_filter(rules, want_logic))
                    done.append('%d rule(s) written' % len(rules))
                    if change.get('logic'):
                        done.append('logic %s -> %s' % (row['logic'], want_logic))
                except Exception as ex:
                    lines.append('"%s": rules not changed - %s' % (row['name'], ex))

        if done:
            changed.append(fid)
            lines.append('%s: %s' % (change.get('name') or row['name'], '; '.join(done)))

    for rec in created or []:
        label = rec.get('row', '?')
        parsed, bad = resolve_categories(cat_lookup, rec['cats'])
        if bad:
            lines.append('New filter "%s": ignored categories - %s'
                         % (rec['name'], ', '.join(bad)))
        if not parsed:
            lines.append('New filter "%s" (row %s) skipped - no valid categories'
                         % (rec['name'], label))
            continue
        rules, err = build_rules(doc, resolver, parsed, rec['rules'], params_for(parsed))
        if err or not rules:
            lines.append('New filter "%s" (row %s) skipped - %s'
                         % (rec['name'], label, err or 'no readable rules'))
            continue
        try:
            cats = List[DB.ElementId]()
            for cid in parsed:
                cats.Add(cid)
            final = unique_name_in(rec['name'], names)
            new_pfe = DB.ParameterFilterElement.Create(
                doc, final, cats, build_element_filter(rules, rec.get('logic', 'AND')))
            names.add(final.lower())
            changed.append(eid_int(new_pfe.Id))
            lines.append('Created "%s" (id %d)' % (final, eid_int(new_pfe.Id)))
        except Exception as ex:
            lines.append('New filter "%s" (row %s) failed - %s' % (rec['name'], label, ex))

    return lines, changed


def delete_elements(doc, ids, label, names=None):
    """Delete a set of elements one at a time so one failure does not stop the rest.

    Line styles are subcategories, which are not Elements - doc.GetElement returns
    nothing for them - so the delete is attempted regardless and only the name and
    the checkout test depend on there being an element. Runs inside a transaction
    opened by the caller."""
    lines = []
    deleted = []
    names = names or {}
    for eid in ids:
        element = doc.GetElement(DB.ElementId(eid))
        name = safe_str(names.get(eid, ''))
        if not name:
            try:
                name = safe_str(element.Name) if element is not None else str(eid)
            except Exception:
                name = str(eid)
        if element is not None:
            writable, why = is_writable(doc, element)
            if not writable:
                lines.append('Kept "%s" - %s' % (name, why))
                continue
        try:
            removed = doc.Delete(DB.ElementId(eid))
            count = 0
            try:
                count = len(list(removed))
            except Exception:
                count = 1
            deleted.append(eid)
            lines.append('Deleted "%s"%s' % (name, ' (%d element(s) removed in total)' % count
                                             if count > 1 else ''))
        except Exception as ex:
            lines.append('Could not delete "%s" - %s' % (name, ex))
    return lines, deleted


# ---------------------------------------------------------------------------
#  GROUP-AWARE EDITING
# ---------------------------------------------------------------------------
def group_instance_id(element):
    """The group instance an element sits in, or None."""
    try:
        gid = element.GroupId
    except Exception:
        return None
    if gid is None or gid == DB.ElementId.InvalidElementId or eid_int(gid) <= 0:
        return None
    return eid_int(gid)


def split_by_group(elements):
    """(elements not in a group, {group instance id: [element ids]})"""
    free = []
    grouped = {}
    for element in elements:
        gid = group_instance_id(element)
        if gid is None:
            free.append(element)
        else:
            grouped.setdefault(gid, []).append(eid_int(element.Id))
    return free, grouped


def _group_type_name(doc, type_id):
    try:
        gtype = doc.GetElement(type_id)
        return safe_str(DB.Element.Name.GetValue(gtype))
    except Exception:
        return ''


def _has_attached_detail_groups(doc, type_id):
    try:
        gtype = doc.GetElement(type_id)
        ids = gtype.GetAvailableAttachedDetailGroupTypeIds()
        return len(list(ids)) > 0
    except Exception:
        return False


def edit_inside_group(doc, group_id, target_ids, apply_fn, lines, depth=0):
    """Change elements that live inside a group, keeping the group.

    Revit will not let an element inside a group be modified in place, and it has
    no API for 'edit group' mode. The only route is to ungroup one instance,
    make the change, group the members back up, give the new type the original
    name and repoint every other instance of the old type onto it. The caller
    wraps this in a SubTransaction so a failure leaves the group exactly as it was.

    Returns (new group instance id, new group type id).
    """
    group = doc.GetElement(DB.ElementId(group_id))
    if group is None:
        raise Exception('group %d no longer exists' % group_id)

    type_id = group.GetTypeId()
    original_name = _group_type_name(doc, type_id)

    if _has_attached_detail_groups(doc, type_id):
        raise Exception('"%s" has attached detail groups, which would be detached by '
                        'ungrouping' % original_name)

    others = []
    try:
        for other in DB.FilteredElementCollector(doc).OfClass(DB.Group)\
                .WhereElementIsNotElementType():
            if eid_int(other.GetTypeId()) == eid_int(type_id) and \
                    eid_int(other.Id) != group_id:
                others.append(other)
    except Exception:
        others = []

    was_pinned = False
    try:
        was_pinned = group.Pinned
        if was_pinned:
            group.Pinned = False
    except Exception:
        was_pinned = False

    member_ids = [eid for eid in group.UngroupMembers()]
    doc.Regenerate()

    # Apply the change, recursing into any nested groups.
    nested = {}
    for tid in target_ids:
        element = doc.GetElement(DB.ElementId(tid))
        if element is None:
            continue
        inner = group_instance_id(element)
        if inner is not None and depth < 4:
            nested.setdefault(inner, []).append(tid)
        else:
            apply_fn(element)

    for inner_id, inner_targets in nested.items():
        new_inner, _inner_type = edit_inside_group(doc, inner_id, inner_targets,
                                                   apply_fn, lines, depth + 1)
        member_ids = [i for i in member_ids if eid_int(i) != inner_id]
        member_ids.append(new_inner)

    doc.Regenerate()

    ids = List[DB.ElementId]()
    for eid in member_ids:
        if doc.GetElement(eid) is not None:
            ids.Add(eid)
    new_group = doc.Create.NewGroup(ids)
    new_type_id = new_group.GetTypeId()

    for other in others:
        try:
            other.ChangeTypeId(new_type_id)
        except Exception as ex:
            lines.append('  Could not move another instance of "%s" onto the rebuilt '
                         'group: %s' % (original_name, ex))

    if original_name:
        try:
            doc.Delete(type_id)
        except Exception:
            pass
        try:
            doc.GetElement(new_type_id).Name = original_name
        except Exception:
            try:
                taken = set()
                for gt in DB.FilteredElementCollector(doc).OfClass(DB.GroupType):
                    taken.add(safe_str(DB.Element.Name.GetValue(gt)).lower())
                doc.GetElement(new_type_id).Name = unique_name_in(original_name, taken)
                lines.append('  Group "%s" was rebuilt but the original name was still in '
                             'use, so it was numbered.' % original_name)
            except Exception:
                pass

    try:
        if was_pinned:
            new_group.Pinned = True
    except Exception:
        pass

    return new_group.Id, new_type_id


def apply_to_grouped(doc, grouped, apply_fn, lines, thing='element'):
    """Run apply_fn over grouped elements, one instance per group type.

    Every other instance of the same type is repointed onto the rebuilt group, so
    a change made once shows up in all of them. Returns (changed, skipped).
    """
    changed = 0
    skipped = 0
    handled_types = set()

    for gid in sorted(grouped.keys()):
        target_ids = grouped[gid]
        group = doc.GetElement(DB.ElementId(gid))
        if group is None:
            continue
        type_id = eid_int(group.GetTypeId())
        name = _group_type_name(doc, group.GetTypeId())
        if type_id in handled_types:
            # already rebuilt through another instance of the same group type
            changed += len(target_ids)
            continue

        sub = DB.SubTransaction(doc)
        sub.Start()
        try:
            _new_gid, new_type_id = edit_inside_group(doc, gid, target_ids, apply_fn, lines)
            sub.Commit()
            handled_types.add(type_id)
            handled_types.add(eid_int(new_type_id))
            changed += len(target_ids)
            lines.append('  Group "%s": %d %s(s) changed, group kept together.'
                         % (name, len(target_ids), thing))
        except Exception as ex:
            try:
                sub.RollBack()
            except Exception:
                pass
            skipped += len(target_ids)
            lines.append('  Group "%s" left untouched (%d %s(s) skipped) - %s'
                         % (name, len(target_ids), thing, ex))
    return changed, skipped


# ---------------------------------------------------------------------------
#  LINE STYLES
# ---------------------------------------------------------------------------
LINE_WEIGHTS = 'Line weight is 1-16, or blank to inherit.'


def colour_text(colour):
    try:
        if colour is None or not colour.IsValid:
            return 'By Category'
        return '%d,%d,%d' % (colour.Red, colour.Green, colour.Blue)
    except Exception:
        return ''


def parse_colour(text):
    parts = re.split(r'[,;/ ]+', safe_str(text).strip())
    parts = [p for p in parts if p != '']
    if len(parts) != 3:
        raise Exception('colour must be "R,G,B"')
    values = []
    for part in parts:
        v = int(round(float(part)))
        if v < 0 or v > 255:
            raise Exception('colour channels must be 0-255')
        values.append(v)
    return DB.Color(values[0], values[1], values[2])


def line_pattern_map(doc):
    lookup = {}
    names = {}
    try:
        for lp in DB.FilteredElementCollector(doc).OfClass(DB.LinePatternElement):
            lookup[safe_str(lp.Name).strip().lower()] = lp.Id
            names[eid_int(lp.Id)] = safe_str(lp.Name)
    except Exception:
        pass
    try:
        solid = DB.LinePatternElement.GetSolidPatternId()
        lookup['solid'] = solid
        names[eid_int(solid)] = 'Solid'
    except Exception:
        pass
    return lookup, names


def rename_subcategory(subcat, new_name):
    """Rename a line style.

    Category.Name is read only in the Revit API, so the rename has to go through
    the subcategory's GraphicsStyle element - setting Element.Name on that
    renames the subcategory itself.
    """
    last_error = None
    for style_type in (DB.GraphicsStyleType.Projection, DB.GraphicsStyleType.Cut):
        try:
            gstyle = subcat.GetGraphicsStyle(style_type)
        except Exception as ex:
            last_error = ex
            continue
        if gstyle is None:
            continue
        try:
            gstyle.Name = new_name
            return
        except Exception as ex:
            last_error = ex
    try:
        subcat.Name = new_name
        return
    except Exception as ex:
        last_error = ex
    raise Exception(safe_str(last_error) or 'Revit would not accept the new name')


def gather_line_styles(doc):
    """Every line subcategory with its graphics, plus how many curves use it."""
    rows = []
    _lookup, pattern_names = line_pattern_map(doc)

    usage = {}
    try:
        curves = DB.FilteredElementCollector(doc)\
            .OfClass(DB.CurveElement).WhereElementIsNotElementType().ToElements()
    except Exception:
        curves = []
    for curve in curves:
        try:
            style = curve.LineStyle
        except Exception:
            continue
        if style is None:
            continue
        key = eid_int(style.Id)
        usage[key] = usage.get(key, 0) + 1

    try:
        lines_cat = doc.Settings.Categories.get_Item(DB.BuiltInCategory.OST_Lines)
        subcats = list(lines_cat.SubCategories)
    except Exception:
        subcats = []

    for subcat in subcats:
        try:
            name = safe_str(subcat.Name)
        except Exception:
            continue
        cid = eid_int(subcat.Id)
        gs_id = -1
        try:
            gstyle = subcat.GetGraphicsStyle(DB.GraphicsStyleType.Projection)
            if gstyle is not None:
                gs_id = eid_int(gstyle.Id)
        except Exception:
            pass
        try:
            weight = subcat.GetLineWeight(DB.GraphicsStyleType.Projection)
        except Exception:
            weight = None
        colour = ''
        try:
            colour = colour_text(subcat.LineColor)
        except Exception:
            colour = ''
        pattern = ''
        pattern_id = -1
        try:
            pattern_id = eid_int(subcat.GetLinePatternId(DB.GraphicsStyleType.Projection))
            pattern = pattern_names.get(pattern_id, 'Solid' if pattern_id < 0 else '')
        except Exception:
            pattern = ''

        uses = usage.get(gs_id, 0)
        builtin = cid < 0
        rows.append({
            'id': cid,
            'gs_id': gs_id,
            'name': name,
            'kind': 'Line Style',
            'weight': weight,
            'colour': colour,
            'pattern': pattern,
            'pattern_id': pattern_id,
            'usage': uses,
            'usage_names': [],
            'builtin': builtin,
            'deletable': not builtin,
            'complex': builtin,
            'signature': None if builtin else u'LINE||%s||%s||%s' % (
                safe_str(weight), colour.lower(), safe_str(pattern).lower()),
            'status': 'Built in' if builtin else ('Unused' if not uses else 'OK'),
            'values': {},
        })

    for row in rows:
        row['values'] = {
            'Name': row['name'],
            'Weight': '' if row['weight'] in (None, -1) else str(row['weight']),
            'Colour': row['colour'],
            'Pattern': row['pattern'],
            'Uses': row['usage'],
            'Status': row['status'],
            'ElemId': str(row['id']),
        }
    rows.sort(key=lambda r: r['name'].lower())
    return rows


def write_line_changes(doc, rows, pending):
    """Apply staged line style edits inside the caller's transaction."""
    lines = []
    changed = []
    snapshot = dict((r['id'], r) for r in rows)
    pattern_lookup, _names = line_pattern_map(doc)
    names = set(safe_str(r['name']).lower() for r in rows)

    try:
        lines_cat = doc.Settings.Categories.get_Item(DB.BuiltInCategory.OST_Lines)
        subcats = dict((eid_int(sc.Id), sc) for sc in lines_cat.SubCategories)
    except Exception:
        subcats = {}

    for cid in sorted(pending.keys()):
        change = pending[cid]
        row = snapshot.get(cid)
        subcat = subcats.get(cid)
        if row is None or subcat is None:
            lines.append('Skipped line style id %d - no longer in the model' % cid)
            continue
        if row['builtin']:
            lines.append('Skipped "%s" - built-in line styles cannot be edited' % row['name'])
            continue

        done = []
        if change.get('Name'):
            wanted = safe_str(change['Name']).strip()
            old = safe_str(row['name'])
            names.discard(old.lower())
            final = unique_name_in(wanted, names)
            try:
                rename_subcategory(subcat, final)
                names.add(final.lower())
                note = 'renamed "%s" -> "%s"' % (old, final)
                if final != wanted:
                    note += ' ("%s" was already in use)' % wanted
                done.append(note)
            except Exception as ex:
                names.add(old.lower())
                lines.append('Could not rename "%s" - %s' % (old, ex))

        if change.get('Weight'):
            try:
                weight = int(round(float(change['Weight'])))
                if weight < 1 or weight > 16:
                    raise Exception('line weight must be 1-16')
                subcat.SetLineWeight(weight, DB.GraphicsStyleType.Projection)
                done.append('weight -> %d' % weight)
            except Exception as ex:
                lines.append('"%s": weight not changed - %s' % (row['name'], ex))

        if change.get('Colour'):
            try:
                subcat.LineColor = parse_colour(change['Colour'])
                done.append('colour -> %s' % change['Colour'])
            except Exception as ex:
                lines.append('"%s": colour not changed - %s' % (row['name'], ex))

        if change.get('Pattern'):
            wanted = safe_str(change['Pattern']).strip()
            pid = pattern_lookup.get(wanted.lower())
            if pid is None:
                lines.append('"%s": pattern not changed - "%s" is not a line pattern in this '
                             'project' % (row['name'], wanted))
            else:
                try:
                    subcat.SetLinePatternId(pid, DB.GraphicsStyleType.Projection)
                    done.append('pattern -> %s' % wanted)
                except Exception as ex:
                    lines.append('"%s": pattern not changed - %s' % (row['name'], ex))

        if done:
            changed.append(cid)
            lines.append('%s: %s' % (change.get('Name') or row['name'], '; '.join(done)))

    return lines, changed


def merge_line_styles(doc, rows, keep_id, drop_ids, delete_after=True):
    """Repoint every curve drawn with the dropped styles onto the kept style.

    Curves that sit inside a group are handled by rebuilding the group rather
    than asking the user to ungroup - see edit_inside_group. Caller owns the
    transaction.
    """
    lines = []
    by_id = dict((r['id'], r) for r in rows)
    keep = by_id.get(keep_id)
    if keep is None:
        return ['Merge aborted - the kept style is no longer in the model.'], []

    keep_gs = doc.GetElement(DB.ElementId(keep['gs_id']))
    if keep_gs is None:
        return ['Merge aborted - could not resolve the kept line style.'], []

    drop_gs = {}
    for did in drop_ids:
        row = by_id.get(did)
        if row is not None:
            drop_gs[row['gs_id']] = row

    affected = []
    try:
        curves = DB.FilteredElementCollector(doc)\
            .OfClass(DB.CurveElement).WhereElementIsNotElementType().ToElements()
    except Exception:
        curves = []
    for curve in curves:
        try:
            style = curve.LineStyle
            if style is not None and eid_int(style.Id) in drop_gs:
                affected.append(curve)
        except Exception:
            continue

    def set_style(element):
        element.LineStyle = keep_gs

    free, grouped = split_by_group(affected)

    moved = 0
    failed = 0
    for curve in free:
        try:
            set_style(curve)
            moved += 1
        except Exception as ex:
            failed += 1
            lines.append('  Could not restyle curve %d - %s' % (eid_int(curve.Id), ex))

    if grouped:
        lines.append('%d curve(s) sit inside groups - rebuilding those groups so they '
                     'stay grouped...' % sum(len(v) for v in grouped.values()))
        in_group, skipped = apply_to_grouped(doc, grouped, set_style, lines, 'curve')
        moved += in_group
        failed += skipped

    lines.insert(0, 'Moved %d curve(s) onto "%s"%s.'
                 % (moved, keep['name'],
                    ', %d could not be moved' % failed if failed else ''))

    deleted = []
    if delete_after:
        if failed:
            lines.append('Not deleting the replaced styles: %d curve(s) still use them and '
                         'deleting a line style deletes its curves. Fix the reported items '
                         'and merge again.' % failed)
        else:
            removable = [d for d in drop_ids if by_id.get(d) and by_id[d]['deletable']]
            blocked = [by_id[d]['name'] for d in drop_ids
                       if by_id.get(d) and not by_id[d]['deletable']]
            if blocked:
                lines.append('Kept built-in style(s): %s' % ', '.join(blocked))
            names = dict((d, by_id[d]['name']) for d in removable if by_id.get(d))
            del_lines, deleted = delete_elements(doc, removable, 'Line style', names)
            lines.extend(del_lines)
    return lines, deleted


# ---------------------------------------------------------------------------
#  TEXT STYLES
# ---------------------------------------------------------------------------
def bip(name):
    """BuiltInParameter by name, or None if this Revit version does not have it."""
    try:
        return getattr(DB.BuiltInParameter, name)
    except Exception:
        return None


def _param_value(element, param_id):
    try:
        return element.get_Parameter(param_id)
    except Exception:
        return None


def _yes_no(value):
    return 'Yes' if value else 'No'


# (column, BuiltInParameter, how the value is read and written)
TEXT_FIELDS = [
    ('Font', 'TEXT_FONT', 'string'),
    ('Size', 'TEXT_SIZE', 'valuestring'),
    ('Width', 'TEXT_WIDTH_SCALE', 'double'),
    ('Bold', 'TEXT_STYLE_BOLD', 'bool'),
    ('Italic', 'TEXT_STYLE_ITALIC', 'bool'),
    ('Underline', 'TEXT_STYLE_UNDERLINE', 'bool'),
    ('Colour', 'LINE_COLOR', 'colour'),
    ('LineWeight', 'LINE_PEN', 'int'),
    ('Background', 'TEXT_BACKGROUND', 'background'),
    ('ShowBorder', 'TEXT_BOX_VISIBILITY', 'bool'),
    ('LeaderOffset', 'LEADER_OFFSET_SHEET', 'valuestring'),
    ('TabSize', 'TEXT_TAB_SIZE', 'valuestring'),
    ('Arrowhead', 'LEADER_ARROWHEAD', 'element'),
]

BACKGROUND_CHOICES = ['Opaque', 'Transparent']


def colour_from_int(value):
    try:
        value = int(value)
        return '%d,%d,%d' % (value % 256, (value // 256) % 256, (value // 65536) % 256)
    except Exception:
        return ''


def gather_text_styles(doc):
    """Every text note type with every setting on its type properties.

    Each setting is read twice over: a display form for the table, and an exact
    form in row['dup'] for the duplicate rules, so a rounded size or a localised
    Yes/No can never make two different styles look identical.
    """
    rows = []
    usage = {}
    try:
        notes = DB.FilteredElementCollector(doc)\
            .OfClass(DB.TextNote).WhereElementIsNotElementType().ToElements()
    except Exception:
        notes = []
    for note in notes:
        key = eid_int(note.GetTypeId())
        usage[key] = usage.get(key, 0) + 1

    try:
        types = DB.FilteredElementCollector(doc).OfClass(DB.TextNoteType).ToElements()
    except Exception:
        types = []

    params = [(column, bip(param_name), kind) for column, param_name, kind in TEXT_FIELDS]

    for tt in types:
        tid = eid_int(tt.Id)
        name = element_name(tt)
        values = {'Name': name}
        exact = {}
        for column, which, kind in params:
            param = _param_value(tt, which) if which is not None else None
            display = ''
            raw = ''
            if param is not None:
                try:
                    if kind == 'string':
                        display = safe_str(param.AsString())
                        raw = display.strip().lower()
                    elif kind == 'bool':
                        flag = param.AsInteger()
                        display = _yes_no(flag)
                        raw = '1' if flag else '0'
                    elif kind == 'background':
                        flag = param.AsInteger()
                        # 0 is opaque, 1 is transparent
                        display = 'Transparent' if flag else 'Opaque'
                        raw = '1' if flag else '0'
                    elif kind == 'colour':
                        display = colour_from_int(param.AsInteger())
                        raw = display
                    elif kind == 'int':
                        display = safe_str(param.AsInteger())
                        raw = display
                    elif kind == 'double':
                        display = fmt_num(param.AsDouble())
                        raw = fmt_num(round(param.AsDouble(), 6))
                    elif kind == 'element':
                        target = doc.GetElement(param.AsElementId())
                        display = element_name(target) if target is not None else NO_VALUE
                        raw = display.strip().lower()
                    else:
                        display = safe_str(param.AsValueString())
                        try:
                            raw = fmt_num(round(param.AsDouble(), 9))
                        except Exception:
                            raw = display.strip().lower()
                except Exception:
                    display = ''
                    raw = ''
            values[column] = display
            exact[column] = raw

        uses = usage.get(tid, 0)
        values['Uses'] = uses
        values['Status'] = 'Unused' if not uses else 'OK'
        values['ElemId'] = str(tid)
        rows.append({
            'id': tid,
            'name': name,
            'kind': 'Text Style',
            'usage': uses,
            'usage_names': [],
            'deletable': True,
            'complex': False,
            'builtin': False,
            'signature': u'TEXT',          # eligible; the rules build the real one
            'dup': exact,
            'editable': writable_fields(tt, TEXT_FIELDS),
            'status': values['Status'],
            'values': values,
        })

    rows.sort(key=lambda r: r['name'].lower())
    return rows




def write_text_changes(doc, rows, pending):
    """Apply staged text style edits inside the caller's transaction."""
    lines = []
    changed = []
    snapshot = dict((r['id'], r) for r in rows)
    names = set(safe_str(r['name']).lower() for r in rows)

    for tid in sorted(pending.keys()):
        change = pending[tid]
        row = snapshot.get(tid)
        element = doc.GetElement(DB.ElementId(tid))
        if row is None or element is None:
            lines.append('Skipped text style id %d - no longer in the model' % tid)
            continue
        writable, why = is_writable(doc, element)
        if not writable:
            lines.append('Skipped "%s" - %s' % (row['name'], why))
            continue

        done = []
        if change.get('Name'):
            wanted = safe_str(change['Name']).strip()
            old = safe_str(row['name'])
            names.discard(old.lower())
            final = unique_name_in(wanted, names)
            try:
                element.Name = final
                names.add(final.lower())
                note = 'renamed "%s" -> "%s"' % (old, final)
                if final != wanted:
                    note += ' ("%s" was already in use)' % wanted
                done.append(note)
            except Exception as ex:
                names.add(old.lower())
                lines.append('Could not rename "%s" - %s' % (old, ex))

        for field, param_name, kind in TEXT_FIELDS:
            if not change.get(field):
                continue
            text = safe_str(change[field]).strip()
            which = bip(param_name)
            param = _param_value(element, which) if which is not None else None
            if param is None or param.IsReadOnly:
                lines.append('"%s": %s is read only' % (row['name'], field))
                continue
            try:
                if kind == 'string':
                    param.Set(text)
                elif kind == 'bool':
                    param.Set(1 if text.strip().lower() in ('yes', 'true', '1') else 0)
                elif kind == 'background':
                    param.Set(1 if text.strip().lower().startswith('trans') else 0)
                elif kind == 'double':
                    param.Set(float(text))
                elif kind == 'int':
                    weight = int(round(float(text)))
                    if weight < 1 or weight > 16:
                        raise Exception('line weight must be 1-16')
                    param.Set(weight)
                elif kind == 'colour':
                    colour = parse_colour(text)
                    param.Set(colour.Red + colour.Green * 256 + colour.Blue * 65536)
                elif kind == 'element':
                    if text.lower() in (NO_VALUE, 'none', ''):
                        param.Set(DB.ElementId.InvalidElementId)
                    else:
                        eid = arrowhead_lookup(doc).get(text.lower())
                        if eid is None:
                            raise Exception('"%s" is not an arrowhead in this project'
                                            % text)
                        param.Set(eid)
                else:
                    if not param.SetValueString(text):
                        raise Exception('Revit would not accept "%s"' % text)
                done.append('%s -> %s' % (field.lower(), text))
            except Exception as ex:
                lines.append('"%s": %s not changed - %s' % (row['name'], field, ex))

        if done:
            changed.append(tid)
            lines.append('%s: %s' % (change.get('Name') or row['name'], '; '.join(done)))

    return lines, changed


def merge_text_styles(doc, rows, keep_id, drop_ids, delete_after=True):
    """Repoint every text note onto the kept type. Caller owns the transaction."""
    lines = []
    by_id = dict((r['id'], r) for r in rows)
    keep = by_id.get(keep_id)
    if keep is None:
        return ['Merge aborted - the kept text style is no longer in the model.'], []

    drop_set = set(drop_ids)
    affected = []
    try:
        notes = DB.FilteredElementCollector(doc)\
            .OfClass(DB.TextNote).WhereElementIsNotElementType().ToElements()
    except Exception:
        notes = []
    for note in notes:
        try:
            if eid_int(note.GetTypeId()) in drop_set:
                affected.append(note)
        except Exception:
            continue

    def set_type(element):
        element.ChangeTypeId(DB.ElementId(keep_id))

    free, grouped = split_by_group(affected)
    moved = 0
    failed = 0
    for note in free:
        try:
            set_type(note)
            moved += 1
        except Exception as ex:
            failed += 1
            lines.append('  Could not retype note %d - %s' % (eid_int(note.Id), ex))

    if grouped:
        lines.append('%d text note(s) sit inside groups - rebuilding those groups so they '
                     'stay grouped...' % sum(len(v) for v in grouped.values()))
        in_group, skipped = apply_to_grouped(doc, grouped, set_type, lines, 'note')
        moved += in_group
        failed += skipped

    lines.insert(0, 'Moved %d text note(s) onto "%s"%s.'
                 % (moved, keep['name'],
                    ', %d could not be moved' % failed if failed else ''))
    deleted = []
    if delete_after:
        if failed:
            lines.append('Not deleting the replaced styles: %d note(s) still use them and '
                         'deleting a text style deletes its notes.' % failed)
        else:
            names = dict((r['id'], r['name']) for r in rows if r['id'] in drop_set)
            del_lines, deleted = delete_elements(doc, list(drop_ids), 'Text style', names)
            lines.extend(del_lines)
    return lines, deleted


# ---------------------------------------------------------------------------
#  GENERIC ELEMENT TYPE STYLES (dimensions, text, materials)
# ---------------------------------------------------------------------------
def param_display(element, param_id):
    """Best readable form of a parameter value."""
    param = _param_value(element, param_id)
    if param is None:
        return ''
    try:
        if param.StorageType == DB.StorageType.String:
            return safe_str(param.AsString())
        if param.StorageType == DB.StorageType.Integer:
            text = safe_str(param.AsValueString())
            return text if text else safe_str(param.AsInteger())
        if param.StorageType == DB.StorageType.Double:
            text = safe_str(param.AsValueString())
            return text if text else fmt_num(param.AsDouble())
        if param.StorageType == DB.StorageType.ElementId:
            target = element.Document.GetElement(param.AsElementId())
            return element_name(target) if target is not None else ''
    except Exception:
        return ''
    return ''


def write_param(element, param_id, text, kind):
    """Write one parameter, choosing the right Set overload. Raises on refusal."""
    param = _param_value(element, param_id)
    if param is None:
        raise Exception('this type does not carry that parameter')
    if param.IsReadOnly:
        raise Exception('read only')
    text = safe_str(text).strip()
    if kind == 'string':
        param.Set(text)
        return
    if kind == 'bool':
        param.Set(1 if text.lower() in ('yes', 'true', '1') else 0)
        return
    if kind == 'double':
        param.Set(float(text))
        return
    if kind == 'int':
        param.Set(int(round(float(text))))
        return
    if not param.SetValueString(text):
        raise Exception('Revit would not accept "%s"' % text)


NO_VALUE = '(none)'


def writable_fields(element, fields):
    """Which of these fields the element actually carries as a writable parameter.

    Editability has to be decided from the parameter, not from whether the cell
    printed anything: a leader arrowhead set to none, a blank font override or a
    zero width factor all read as an empty cell while being perfectly writable.
    """
    found = set()
    for column, param_name, _kind in fields:
        which = bip(param_name)
        if which is None:
            continue
        try:
            param = element.get_Parameter(which)
        except Exception:
            param = None
        if param is not None and not param.IsReadOnly:
            found.add(column)
    return found


def element_name(element):
    if element is None:
        return ''
    try:
        return safe_str(DB.Element.Name.GetValue(element))
    except Exception:
        try:
            return safe_str(element.Name)
        except Exception:
            return ''


def gather_type_styles(doc, revit_class, fields, usage_class=None):
    """Read every element type of a class into standard row dicts.

    fields is a list of (column name, BuiltInParameter name, kind).
    """
    usage = {}
    if usage_class is not None:
        try:
            instances = DB.FilteredElementCollector(doc).OfClass(usage_class)\
                .WhereElementIsNotElementType().ToElements()
        except Exception:
            instances = []
        for instance in instances:
            key = eid_int(instance.GetTypeId())
            usage[key] = usage.get(key, 0) + 1

    try:
        types = DB.FilteredElementCollector(doc).OfClass(revit_class)\
            .WhereElementIsElementType().ToElements()
    except Exception:
        try:
            types = DB.FilteredElementCollector(doc).OfClass(revit_class).ToElements()
        except Exception:
            types = []

    rows = []
    for element in types:
        tid = eid_int(element.Id)
        name = element_name(element)
        if not name:
            continue
        values = {'Name': name}
        parts = []
        for column, param_name, _kind in fields:
            which = bip(param_name)
            text = param_display(element, which) if which is not None else ''
            values[column] = text
            parts.append(u'%s=%s' % (column, safe_str(text).strip().lower()))

        uses = usage.get(tid, 0)
        values['Uses'] = uses
        values['Status'] = 'Unused' if not uses else 'OK'
        values['ElemId'] = str(tid)
        rows.append({
            'id': tid,
            'name': name,
            'usage': uses,
            'usage_names': [],
            'deletable': True,
            'complex': False,
            'builtin': False,
            'signature': u'TYPE||' + u'||'.join(parts),
            'status': values['Status'],
            'values': values,
        })

    rows.sort(key=lambda r: r['name'].lower())
    return rows


def write_type_changes(doc, rows, pending, fields):
    """Apply staged edits to element types. Caller owns the transaction."""
    lines = []
    changed = []
    snapshot = dict((r['id'], r) for r in rows)
    field_map = dict((column, (param_name, kind)) for column, param_name, kind in fields)
    names = set(safe_str(r['name']).lower() for r in rows)

    for tid in sorted(pending.keys()):
        change = pending[tid]
        row = snapshot.get(tid)
        element = doc.GetElement(DB.ElementId(tid))
        if row is None or element is None:
            lines.append('Skipped id %d - no longer in the model' % tid)
            continue
        writable, why = is_writable(doc, element)
        if not writable:
            lines.append('Skipped "%s" - %s' % (row['name'], why))
            continue

        done = []
        if change.get('Name'):
            wanted = safe_str(change['Name']).strip()
            old = safe_str(row['name'])
            names.discard(old.lower())
            final = unique_name_in(wanted, names)
            try:
                element.Name = final
                names.add(final.lower())
                note = 'renamed "%s" -> "%s"' % (old, final)
                if final != wanted:
                    note += ' ("%s" was already in use)' % wanted
                done.append(note)
            except Exception as ex:
                names.add(old.lower())
                lines.append('Could not rename "%s" - %s' % (old, ex))

        for column in sorted(change.keys()):
            if column == 'Name' or column not in field_map:
                continue
            param_name, kind = field_map[column]
            which = bip(param_name)
            if which is None:
                lines.append('"%s": %s is not available in this Revit version'
                             % (row['name'], column))
                continue
            try:
                write_param(element, which, change[column], kind)
                done.append('%s -> %s' % (column.lower(), safe_str(change[column]).strip()))
            except Exception as ex:
                lines.append('"%s": %s not changed - %s' % (row['name'], column, ex))

        if done:
            changed.append(tid)
            lines.append('%s: %s' % (change.get('Name') or row['name'], '; '.join(done)))

    return lines, changed


def merge_type_styles(doc, rows, keep_id, drop_ids, usage_class, thing,
                      delete_after=True):
    """Retype every instance of the dropped types onto the kept one, groups and all."""
    lines = []
    by_id = dict((r['id'], r) for r in rows)
    keep = by_id.get(keep_id)
    if keep is None:
        return ['Merge aborted - the kept %s is no longer in the model.' % thing], []

    drop_set = set(drop_ids)
    affected = []
    try:
        instances = DB.FilteredElementCollector(doc).OfClass(usage_class)\
            .WhereElementIsNotElementType().ToElements()
    except Exception:
        instances = []
    for instance in instances:
        try:
            if eid_int(instance.GetTypeId()) in drop_set:
                affected.append(instance)
        except Exception:
            continue

    def set_type(element):
        element.ChangeTypeId(DB.ElementId(keep_id))

    free, grouped = split_by_group(affected)
    moved = 0
    failed = 0
    for instance in free:
        try:
            set_type(instance)
            moved += 1
        except Exception as ex:
            failed += 1
            lines.append('  Could not retype %d - %s' % (eid_int(instance.Id), ex))

    if grouped:
        lines.append('%d %s(s) sit inside groups - rebuilding those groups so they stay '
                     'grouped...' % (sum(len(v) for v in grouped.values()), thing))
        in_group, skipped = apply_to_grouped(doc, grouped, set_type, lines, thing)
        moved += in_group
        failed += skipped

    lines.insert(0, 'Moved %d %s(s) onto "%s"%s.'
                 % (moved, thing, keep['name'],
                    ', %d could not be moved' % failed if failed else ''))
    deleted = []
    if delete_after:
        if failed:
            lines.append('Not deleting the replaced types: %d %s(s) still use them.'
                         % (failed, thing))
        else:
            names = dict((r['id'], r['name']) for r in rows if r['id'] in drop_set)
            del_lines, deleted = delete_elements(doc, list(drop_ids), thing, names)
            lines.extend(del_lines)
    return lines, deleted


# ---------------------------------------------------------------------------
#  OBJECT STYLES
# ---------------------------------------------------------------------------
def is_builtin_subcategory(doc, sub, parent_cat):
    """A subcategory Revit defines itself rather than one the project added.

    There is no API flag for this. What distinguishes them in practice is that
    Revit's own subcategories carry a negative built-in id, while anything a
    project, family or import created gets a positive element id.
    """
    return eid_int(sub.Id) < 0


def gather_object_styles(doc):
    """Every model category and subcategory, as Revit's Object Styles dialog shows.

    Usage is not counted here. Counting which elements reference an object style
    means opening every family of the parent category, which is far too slow to do
    on every refresh - it is done on demand by the Analyze button instead, the same
    way Ideate StyleManager handles it. Until then usage reads as "?" for custom
    subcategories and "-" for built-in ones, whose usage Revit will not report.
    """
    _lookup, pattern_names = line_pattern_map(doc)

    def read(cat, parent_name):
        try:
            name = safe_str(cat.Name)
        except Exception:
            return None
        if not name:
            return None

        def weight(style_type):
            try:
                value = cat.GetLineWeight(style_type)
                return '' if value is None else str(value)
            except Exception:
                return ''

        def pattern(style_type):
            try:
                pid = eid_int(cat.GetLinePatternId(style_type))
                return pattern_names.get(pid, 'Solid' if pid < 0 else '')
            except Exception:
                return ''

        try:
            colour = colour_text(cat.LineColor)
        except Exception:
            colour = ''
        material = ''
        try:
            material = element_name(cat.Material)
        except Exception:
            material = ''

        full_name = ('%s : %s' % (parent_name, name)) if parent_name else name
        return {
            'Name': name,
            'Parent': parent_name,
            'FullName': full_name,
            'ProjWeight': weight(DB.GraphicsStyleType.Projection),
            'CutWeight': weight(DB.GraphicsStyleType.Cut),
            'Colour': colour,
            'ProjPattern': pattern(DB.GraphicsStyleType.Projection),
            'CutPattern': pattern(DB.GraphicsStyleType.Cut),
            'Material': material,
        }

    rows = []
    try:
        categories = list(doc.Settings.Categories)
    except Exception:
        categories = []

    for cat in categories:
        try:
            if cat.CategoryType != DB.CategoryType.Model:
                continue
            if safe_str(cat.Name) == 'Lines':
                continue
            if not cat.IsVisibleInUI:
                continue
        except Exception:
            continue

        parent_name = safe_str(cat.Name)
        entries = [(cat, '', False)]
        try:
            for sub in cat.SubCategories:
                entries.append((sub, parent_name, is_builtin_subcategory(doc, sub, cat)))
        except Exception:
            pass

        for target, parent, builtin_sub in entries:
            values = read(target, parent)
            if values is None:
                continue
            cid = eid_int(target.Id)
            is_category = parent == ''
            builtin = is_category or builtin_sub
            values['Kind'] = ('Category' if is_category
                              else ('Built-in subcategory' if builtin_sub
                                    else 'Subcategory'))
            values['Uses'] = '-' if builtin else '?'
            values['Status'] = 'Not analysed' if not builtin else 'Usage not reported'
            values['ElemId'] = str(cid)
            rows.append({
                'id': cid,
                'name': values['FullName'],
                'parent': parent,
                'is_category': is_category,
                'usage': None,
                'analysed': False,
                'usage_names': [],
                'deletable': not builtin,
                'complex': False,
                'builtin': builtin,
                'signature': None if builtin else u'OBJ||%s||%s||%s||%s||%s||%s' % (
                    parent.lower(), values['ProjWeight'], values['CutWeight'],
                    values['Colour'].lower(), values['ProjPattern'].lower(),
                    values['CutPattern'].lower()),
                'status': values['Status'],
                'values': values,
            })

    rows.sort(key=lambda r: r['name'].lower())
    return rows


def analyze_object_styles(doc, rows, targets, report=None):
    """Count what actually uses each selected object style.

    Opens every family of the relevant parent categories once and counts the
    elements sitting on each target subcategory, then adds anything placed
    directly in the project. Slow by nature, which is why it is a deliberate
    step rather than part of the refresh.
    """
    note = report if report is not None else (lambda d, t, x='': None)
    lines = []
    wanted = [r for r in targets if not r.get('builtin')]
    if not wanted:
        return ['Nothing to analyse - built-in styles do not report their usage.'], {}

    by_parent = {}
    for row in wanted:
        by_parent.setdefault(row['parent'], []).append(row)

    counts = dict((r['id'], 0) for r in wanted)
    where = dict((r['id'], []) for r in wanted)

    # ---- project-level elements -----------------------------------------
    id_lookup = {}
    for row in wanted:
        cat = find_category(doc, row['id'])
        if cat is None:
            continue
        for key in subcategory_ids(cat):
            id_lookup[key] = row['id']

    try:
        for element in DB.FilteredElementCollector(doc).WhereElementIsNotElementType():
            try:
                sub = element.Subcategory
            except Exception:
                continue
            if sub is None:
                continue
            target = id_lookup.get(eid_int(sub.Id))
            if target is not None:
                counts[target] += 1
                if len(where[target]) < 40:
                    where[target].append('project element %d' % eid_int(element.Id))
    except Exception:
        pass

    # ---- families --------------------------------------------------------
    for parent_name, group in by_parent.items():
        families = []
        try:
            for family in DB.FilteredElementCollector(doc).OfClass(DB.Family).ToElements():
                try:
                    fam_cat = family.FamilyCategory
                    if fam_cat is not None and safe_str(fam_cat.Name) == parent_name \
                            and family.IsEditable:
                        families.append(family)
                except Exception:
                    continue
        except Exception:
            families = []

        names = dict((safe_str(r['values']['Name']), r['id']) for r in group)
        note(0, len(families), 'Analysing %d "%s" family(ies)...'
             % (len(families), parent_name))

        for index, family in enumerate(families):
            note(index, len(families), 'Analysing %s (%d of %d)'
                 % (element_name(family), index + 1, len(families)))
            fam_name = element_name(family)
            fam_doc = None
            try:
                fam_doc = doc.EditFamily(family)
                found = count_family_subcategory_use(fam_doc, names)
                for target_id, count in found.items():
                    counts[target_id] += count
                    if count and len(where[target_id]) < 40:
                        where[target_id].append('%s (%d)' % (fam_name, count))
            except Exception as ex:
                lines.append('  Could not open "%s" - %s' % (fam_name, ex))
            finally:
                try:
                    if fam_doc is not None and fam_doc.IsValidObject:
                        fam_doc.Close(False)
                except Exception:
                    pass

    for row in wanted:
        lines.append('%s: %d use(s)' % (row['name'], counts[row['id']]))
    lines.insert(0, 'Analysed %d object style(s).' % len(wanted))
    note(0, 0)
    return lines, dict((k, (counts[k], where[k])) for k in counts)


def count_family_subcategory_use(fam_doc, names, depth=0):
    """Count elements on each named subcategory in a family and its nested families."""
    found = {}
    try:
        parent = fam_doc.OwnerFamily.FamilyCategory
    except Exception:
        return found
    if parent is None:
        return found

    lookup = {}
    for name, target_id in names.items():
        sub = find_subcategory_by_name(parent, name)
        if sub is not None:
            for key in subcategory_ids(sub):
                lookup[key] = target_id
    if lookup:
        try:
            for element in DB.FilteredElementCollector(fam_doc)\
                    .WhereElementIsNotElementType():
                current = element_subcategory_id(element)
                target = lookup.get(current) if current is not None else None
                if target is not None:
                    found[target] = found.get(target, 0) + 1
        except Exception:
            pass

    if depth < 3:
        try:
            nested = list(DB.FilteredElementCollector(fam_doc).OfClass(DB.Family)
                          .ToElements())
        except Exception:
            nested = []
        for family in nested:
            nested_doc = None
            try:
                if not family.IsEditable:
                    continue
                nested_doc = fam_doc.EditFamily(family)
                inner = count_family_subcategory_use(nested_doc, names, depth + 1)
                for key, value in inner.items():
                    found[key] = found.get(key, 0) + value
            except Exception:
                pass
            finally:
                try:
                    if nested_doc is not None and nested_doc.IsValidObject:
                        nested_doc.Close(False)
                except Exception:
                    pass
    return found


def element_subcategory_id(element):
    try:
        sub = element.Subcategory
        if sub is not None:
            return eid_int(sub.Id)
    except Exception:
        pass
    which = bip('FAMILY_ELEM_SUBCATEGORY')
    if which is not None:
        try:
            param = element.get_Parameter(which)
            if param is not None:
                return eid_int(param.AsElementId())
        except Exception:
            pass
    return None


def find_category(doc, cid):
    try:
        for cat in doc.Settings.Categories:
            if eid_int(cat.Id) == cid:
                return cat
            try:
                for sub in cat.SubCategories:
                    if eid_int(sub.Id) == cid:
                        return sub
            except Exception:
                pass
    except Exception:
        pass
    return None


def write_object_style_changes(doc, rows, pending):
    """Apply staged object style edits. Caller owns the transaction."""
    lines = []
    changed = []
    snapshot = dict((r['id'], r) for r in rows)
    pattern_lookup, _names = line_pattern_map(doc)
    material_lookup = {}
    try:
        for mat in DB.FilteredElementCollector(doc).OfClass(DB.Material):
            material_lookup[element_name(mat).strip().lower()] = mat.Id
    except Exception:
        pass

    for cid in sorted(pending.keys()):
        change = pending[cid]
        row = snapshot.get(cid)
        cat = find_category(doc, cid)
        if row is None or cat is None:
            lines.append('Skipped object style id %d - no longer in the model' % cid)
            continue

        done = []
        if change.get('Name'):
            if row['builtin']:
                lines.append('"%s": Revit categories cannot be renamed, only their '
                             'subcategories.' % row['name'])
            else:
                try:
                    rename_subcategory(cat, safe_str(change['Name']).strip())
                    done.append('renamed to "%s"' % safe_str(change['Name']).strip())
                except Exception as ex:
                    lines.append('Could not rename "%s" - %s' % (row['name'], ex))

        for column, style_type in (('ProjWeight', DB.GraphicsStyleType.Projection),
                                   ('CutWeight', DB.GraphicsStyleType.Cut)):
            if not change.get(column):
                continue
            try:
                weight = int(round(float(change[column])))
                if weight < 1 or weight > 16:
                    raise Exception('line weight must be 1-16')
                cat.SetLineWeight(weight, style_type)
                done.append('%s -> %d' % (column, weight))
            except Exception as ex:
                lines.append('"%s": %s not changed - %s' % (row['name'], column, ex))

        if change.get('Colour'):
            try:
                cat.LineColor = parse_colour(change['Colour'])
                done.append('colour -> %s' % change['Colour'])
            except Exception as ex:
                lines.append('"%s": colour not changed - %s' % (row['name'], ex))

        for column, style_type in (('ProjPattern', DB.GraphicsStyleType.Projection),
                                   ('CutPattern', DB.GraphicsStyleType.Cut)):
            if not change.get(column):
                continue
            wanted = safe_str(change[column]).strip()
            pid = pattern_lookup.get(wanted.lower())
            if pid is None:
                lines.append('"%s": %s not changed - "%s" is not a line pattern in this '
                             'project' % (row['name'], column, wanted))
                continue
            try:
                cat.SetLinePatternId(pid, style_type)
                done.append('%s -> %s' % (column, wanted))
            except Exception as ex:
                lines.append('"%s": %s not changed - %s' % (row['name'], column, ex))

        if change.get('Material'):
            wanted = safe_str(change['Material']).strip()
            mid = material_lookup.get(wanted.lower())
            if mid is None:
                lines.append('"%s": material not changed - "%s" is not a material in this '
                             'project' % (row['name'], wanted))
            else:
                try:
                    cat.Material = doc.GetElement(mid)
                    done.append('material -> %s' % wanted)
                except Exception as ex:
                    lines.append('"%s": material not changed - %s' % (row['name'], ex))

        if done:
            changed.append(cid)
            lines.append('%s: %s' % (row['name'], '; '.join(done)))

    return lines, changed


# ---------------------------------------------------------------------------
#  MATERIALS
# ---------------------------------------------------------------------------
def gather_materials(doc):
    """Every material with its graphics and how many elements reference it."""
    fill_names = {}
    try:
        for fp in DB.FilteredElementCollector(doc).OfClass(DB.FillPatternElement):
            fill_names[eid_int(fp.Id)] = element_name(fp)
    except Exception:
        pass

    usage = {}
    try:
        for element in DB.FilteredElementCollector(doc).WhereElementIsNotElementType():
            try:
                for mid in element.GetMaterialIds(False):
                    key = eid_int(mid)
                    usage[key] = usage.get(key, 0) + 1
            except Exception:
                continue
    except Exception:
        pass

    rows = []
    try:
        materials = DB.FilteredElementCollector(doc).OfClass(DB.Material).ToElements()
    except Exception:
        materials = []

    for mat in materials:
        mid = eid_int(mat.Id)
        name = element_name(mat)
        if not name:
            continue

        def safe(fn, default=''):
            try:
                return fn()
            except Exception:
                return default

        colour = safe(lambda: colour_text(mat.Color))
        surface_colour = safe(lambda: colour_text(mat.SurfaceForegroundPatternColor))
        cut_colour = safe(lambda: colour_text(mat.CutForegroundPatternColor))
        surface_pattern = safe(
            lambda: fill_names.get(eid_int(mat.SurfaceForegroundPatternId), ''))
        cut_pattern = safe(lambda: fill_names.get(eid_int(mat.CutForegroundPatternId), ''))
        transparency = safe(lambda: str(mat.Transparency))
        shininess = safe(lambda: str(mat.Shininess))
        smoothness = safe(lambda: str(mat.Smoothness))

        uses = usage.get(mid, 0)
        values = {
            'Name': name,
            'Class': safe(lambda: safe_str(mat.MaterialClass)),
            'Category': safe(lambda: safe_str(mat.MaterialCategory)),
            'Colour': colour,
            'Transparency': transparency,
            'Shininess': shininess,
            'Smoothness': smoothness,
            'SurfacePattern': surface_pattern,
            'SurfaceColour': surface_colour,
            'CutPattern': cut_pattern,
            'CutColour': cut_colour,
            'Uses': uses,
            'Status': 'Unused' if not uses else 'OK',
            'ElemId': str(mid),
        }
        rows.append({
            'id': mid,
            'name': name,
            'usage': uses,
            'usage_names': [],
            'deletable': True,
            'complex': False,
            'builtin': False,
            'signature': u'MAT||%s||%s||%s||%s||%s||%s' % (
                colour.lower(), transparency, surface_pattern.lower(),
                surface_colour.lower(), cut_pattern.lower(), cut_colour.lower()),
            'status': values['Status'],
            'values': values,
        })

    rows.sort(key=lambda r: r['name'].lower())
    return rows


def write_material_changes(doc, rows, pending):
    """Apply staged material edits. Caller owns the transaction."""
    lines = []
    changed = []
    snapshot = dict((r['id'], r) for r in rows)
    names = set(safe_str(r['name']).lower() for r in rows)
    fill_lookup = {}
    try:
        for fp in DB.FilteredElementCollector(doc).OfClass(DB.FillPatternElement):
            fill_lookup[element_name(fp).strip().lower()] = fp.Id
    except Exception:
        pass

    for mid in sorted(pending.keys()):
        change = pending[mid]
        row = snapshot.get(mid)
        mat = doc.GetElement(DB.ElementId(mid))
        if row is None or mat is None:
            lines.append('Skipped material id %d - no longer in the model' % mid)
            continue
        writable, why = is_writable(doc, mat)
        if not writable:
            lines.append('Skipped "%s" - %s' % (row['name'], why))
            continue

        done = []
        if change.get('Name'):
            wanted = safe_str(change['Name']).strip()
            old = safe_str(row['name'])
            names.discard(old.lower())
            final = unique_name_in(wanted, names)
            try:
                mat.Name = final
                names.add(final.lower())
                note = 'renamed "%s" -> "%s"' % (old, final)
                if final != wanted:
                    note += ' ("%s" was already in use)' % wanted
                done.append(note)
            except Exception as ex:
                names.add(old.lower())
                lines.append('Could not rename "%s" - %s' % (old, ex))

        for column, attr in (('Class', 'MaterialClass'), ('Category', 'MaterialCategory')):
            if not change.get(column):
                continue
            try:
                setattr(mat, attr, safe_str(change[column]).strip())
                done.append('%s -> %s' % (column.lower(), change[column]))
            except Exception as ex:
                lines.append('"%s": %s not changed - %s' % (row['name'], column, ex))

        for column, attr in (('Colour', 'Color'),
                             ('SurfaceColour', 'SurfaceForegroundPatternColor'),
                             ('CutColour', 'CutForegroundPatternColor')):
            if not change.get(column):
                continue
            try:
                setattr(mat, attr, parse_colour(change[column]))
                done.append('%s -> %s' % (column, change[column]))
            except Exception as ex:
                lines.append('"%s": %s not changed - %s' % (row['name'], column, ex))

        for column, attr, low, high in (('Transparency', 'Transparency', 0, 100),
                                        ('Shininess', 'Shininess', 0, 128),
                                        ('Smoothness', 'Smoothness', 0, 100)):
            if not change.get(column):
                continue
            try:
                value = int(round(float(change[column])))
                if value < low or value > high:
                    raise Exception('must be %d-%d' % (low, high))
                setattr(mat, attr, value)
                done.append('%s -> %d' % (column.lower(), value))
            except Exception as ex:
                lines.append('"%s": %s not changed - %s' % (row['name'], column, ex))

        for column, attr in (('SurfacePattern', 'SurfaceForegroundPatternId'),
                             ('CutPattern', 'CutForegroundPatternId')):
            if not change.get(column):
                continue
            wanted = safe_str(change[column]).strip()
            pid = fill_lookup.get(wanted.lower())
            if pid is None:
                lines.append('"%s": %s not changed - "%s" is not a fill pattern in this '
                             'project' % (row['name'], column, wanted))
                continue
            try:
                setattr(mat, attr, pid)
                done.append('%s -> %s' % (column, wanted))
            except Exception as ex:
                lines.append('"%s": %s not changed - %s' % (row['name'], column, ex))

        if done:
            changed.append(mid)
            lines.append('%s: %s' % (change.get('Name') or row['name'], '; '.join(done)))

    return lines, changed


def run_in_transaction(doc, name, fn):
    """Open a transaction, run fn, and report rather than raise on failure."""
    trans = DB.Transaction(doc, name)
    trans.Start()
    try:
        opts = trans.GetFailureHandlingOptions()
        opts.SetFailuresPreprocessor(WarningSwallower())
        trans.SetFailureHandlingOptions(opts)
    except Exception:
        pass
    try:
        lines, _deleted = fn()
        trans.Commit()
        return lines
    except Exception as ex:
        try:
            trans.RollBack()
        except Exception:
            pass
        return ['Aborted, nothing was changed: %s' % ex]


def merge_materials(doc, rows, keep_id, drop_ids, delete_after=True):
    """Repoint every material-valued parameter from the dropped materials to the kept one."""
    lines = []
    by_id = dict((r['id'], r) for r in rows)
    keep = by_id.get(keep_id)
    if keep is None:
        return ['Merge aborted - the kept material is no longer in the model.'], []

    drop_set = set(drop_ids)
    keep_eid = DB.ElementId(keep_id)
    moved = 0
    touched = 0
    failed = 0

    try:
        elements = list(DB.FilteredElementCollector(doc).WhereElementIsNotElementType())
        elements.extend(list(DB.FilteredElementCollector(doc).WhereElementIsElementType()))
    except Exception:
        elements = []

    for element in elements:
        try:
            material_ids = set(eid_int(m) for m in element.GetMaterialIds(False))
        except Exception:
            continue
        if not (material_ids & drop_set):
            continue
        hit = False
        try:
            for param in element.Parameters:
                try:
                    if param.StorageType != DB.StorageType.ElementId or param.IsReadOnly:
                        continue
                    if eid_int(param.AsElementId()) not in drop_set:
                        continue
                    param.Set(keep_eid)
                    moved += 1
                    hit = True
                except Exception:
                    continue
        except Exception:
            pass
        if hit:
            touched += 1
        else:
            failed += 1

    lines.append('Repointed %d material parameter(s) across %d element(s) onto "%s".'
                 % (moved, touched, keep['name']))
    if failed:
        lines.append('%d element(s) reference a replaced material through geometry or a '
                     'read-only parameter (compound structure layers, paint) and could not '
                     'be repointed from the API.' % failed)

    deleted = []
    if delete_after:
        if failed:
            lines.append('Not deleting the replaced materials while %d element(s) still '
                         'reference them.' % failed)
        else:
            names = dict((r['id'], r['name']) for r in rows if r['id'] in drop_set)
            del_lines, deleted = delete_elements(doc, list(drop_ids), 'Material', names)
            lines.extend(del_lines)
    return lines, deleted


# ---------------------------------------------------------------------------
#  OBJECT STYLE MERGING
# ---------------------------------------------------------------------------
class FamilyOverwriteOptions(DB.IFamilyLoadOptions):
    """Reload an edited family over the one already in the project."""

    def OnFamilyFound(self, familyInUse, overwriteParameterValues):
        overwriteParameterValues.Value = True
        return True

    def OnSharedFamilyFound(self, sharedFamily, familyInUse, source, overwriteParameterValues):
        source.Value = DB.FamilySource.Family
        overwriteParameterValues.Value = True
        return True


def subcategory_ids(cat):
    """Every id a subcategory can be referenced by: its own, and its graphics styles."""
    ids = set()
    try:
        ids.add(eid_int(cat.Id))
    except Exception:
        pass
    for style_type in (DB.GraphicsStyleType.Projection, DB.GraphicsStyleType.Cut):
        try:
            gstyle = cat.GetGraphicsStyle(style_type)
            if gstyle is not None:
                ids.add(eid_int(gstyle.Id))
        except Exception:
            pass
    return ids


def set_subcategory(element, target_cat):
    """Assign an element to a subcategory.

    target_cat of None means the parent category - Revit shows that as the blank
    entry in the family editor's Subcategory list, and it is where elements land
    when a subcategory is deleted.
    """
    try:
        element.Subcategory = target_cat
        return True
    except Exception:
        pass
    which = bip('FAMILY_ELEM_SUBCATEGORY')
    if which is None:
        return False
    try:
        param = element.get_Parameter(which)
        if param is None or param.IsReadOnly:
            return False
        if target_cat is None:
            param.Set(DB.ElementId.InvalidElementId)
            return True
        try:
            gstyle = target_cat.GetGraphicsStyle(DB.GraphicsStyleType.Projection)
        except Exception:
            gstyle = None
        param.Set(gstyle.Id if gstyle is not None else target_cat.Id)
        return True
    except Exception:
        return False


def find_subcategory_by_name(parent_cat, name):
    try:
        for sub in parent_cat.SubCategories:
            if safe_str(sub.Name) == safe_str(name):
                return sub
    except Exception:
        pass
    return None


def remap_family_subcategories(fam_doc, keep_name, drop_names, depth=0, report=None):
    # report here takes plain text - it appends to the run log rather than the bar
    """Move everything off the dropped subcategories onto the kept one, in this
    family and in every family nested inside it, then delete the spares.

    keep_name of None means the parent category itself - which is what Revit
    falls back to when a subcategory is deleted.

    Nested families have to be handled first and outside the transaction,
    because EditFamily and LoadFamily both refuse to run with one open.

    Returns (moved, changed, error).
    """
    note = report if report is not None else (lambda text: None)
    try:
        parent = fam_doc.OwnerFamily.FamilyCategory
    except Exception:
        return 0, False, 'no family category'
    if parent is None:
        return 0, False, 'no family category'

    moved = 0
    changed = False

    # ---- nested families first -------------------------------------------
    if depth < 3:
        try:
            nested = list(DB.FilteredElementCollector(fam_doc).OfClass(DB.Family)
                          .ToElements())
        except Exception:
            nested = []
        for family in nested:
            nested_doc = None
            try:
                if not family.IsEditable:
                    continue
                fam_name = element_name(family)
                nested_doc = fam_doc.EditFamily(family)
                inner_moved, inner_changed, inner_error = remap_family_subcategories(
                    nested_doc, keep_name, drop_names, depth + 1, report)
                if inner_error:
                    note('    nested "%s": %s' % (fam_name, inner_error))
                elif inner_changed:
                    nested_doc.LoadFamily(fam_doc, FamilyOverwriteOptions())
                    moved += inner_moved
                    changed = True
                    note('    nested "%s": %d element(s) moved' % (fam_name, inner_moved))
            except Exception as ex:
                note('    nested family failed - %s' % ex)
            finally:
                try:
                    if nested_doc is not None and nested_doc.IsValidObject:
                        nested_doc.Close(False)
                except Exception:
                    pass

    present = {}
    for name in drop_names:
        sub = find_subcategory_by_name(parent, name)
        if sub is not None:
            present[name] = sub
    if not present:
        return moved, changed, ''

    trans = DB.Transaction(fam_doc, 'RevoBIM PY - Merge subcategories')
    trans.Start()
    try:
        opts = trans.GetFailureHandlingOptions()
        opts.SetFailuresPreprocessor(WarningSwallower())
        trans.SetFailureHandlingOptions(opts)
    except Exception:
        pass
    try:
        keep_sub = None
        if keep_name:
            keep_sub = find_subcategory_by_name(parent, keep_name)
            if keep_sub is None:
                keep_sub = fam_doc.Settings.Categories.NewSubcategory(parent, keep_name)

        wanted = set()
        for sub in present.values():
            wanted |= subcategory_ids(sub)

        for element in DB.FilteredElementCollector(fam_doc).WhereElementIsNotElementType():
            current = element_subcategory_id(element)
            if current is None or current not in wanted:
                continue
            if set_subcategory(element, keep_sub):
                moved += 1

        for sub in present.values():
            try:
                fam_doc.Delete(sub.Id)
            except Exception:
                pass

        trans.Commit()
        return moved, True, ''
    except Exception as ex:
        try:
            trans.RollBack()
        except Exception:
            pass
        return moved, changed, safe_str(ex)


def merge_object_styles(doc, rows, keep_id, drop_ids, delete_after=True, report=None):
    """Merge subcategories by editing and reloading the families that use them.

    Subcategory assignment lives inside each family, so the merge opens every
    family of the parent category, repoints its geometry (and that of any family
    nested inside it) onto the kept subcategory, deletes the spare subcategory
    there, and loads the family back over itself.

    The kept style may be the parent category itself, which is what Revit falls
    back to when a subcategory is deleted.

    Runs with no transaction open, because EditFamily and LoadFamily require it.
    """
    lines = []
    note = report if report is not None else (lambda d, t, x='': None)
    try:
        if doc.IsModifiable:
            return ['Merge aborted - a Revit transaction is still open. Editing families '
                    'needs the document idle; try again in a moment.'], []
    except Exception:
        pass

    by_id = dict((r['id'], r) for r in rows)
    keep = by_id.get(keep_id)
    if keep is None:
        return ['Merge aborted - the kept object style is no longer in the model.'], []

    drops = [by_id[d] for d in drop_ids if d in by_id]
    drops = [d for d in drops if not d.get('builtin')]
    if not drops:
        return ['Merge aborted - only custom subcategories can be merged away. Revit '
                'categories and its own built-in subcategories cannot be removed.'], []

    keep_is_category = keep.get('is_category', False)
    parent_name = keep['parent'] if not keep_is_category else keep['name']
    for drop in drops:
        if drop['parent'] != parent_name:
            return ['Merge aborted - "%s" is not a subcategory of "%s". Revit can only '
                    'merge subcategories that share a parent category.'
                    % (drop['name'], parent_name)], []

    keep_name = None if keep_is_category else safe_str(keep['values'].get('Name'))
    drop_names = [safe_str(d['values'].get('Name', d['name'])) for d in drops]

    if keep_is_category:
        lines.append('Merging %s into the parent category "%s" - elements revert to the '
                     'category style, which is what Revit does when a subcategory is '
                     'deleted.' % (', '.join('"%s"' % n for n in drop_names), parent_name))
    else:
        lines.append('Merging %s into "%s : %s".'
                     % (', '.join('"%s"' % n for n in drop_names), parent_name, keep_name))

    # ---- 1. elements placed directly in the project ----------------------
    wanted = set()
    for drop in drops:
        cat = find_category(doc, drop['id'])
        if cat is not None:
            wanted |= subcategory_ids(cat)
    keep_cat = None if keep_is_category else find_category(doc, keep_id)

    project_moved = 0
    if wanted:
        trans = DB.Transaction(doc, 'RevoBIM PY - Repoint object style')
        trans.Start()
        try:
            opts = trans.GetFailureHandlingOptions()
            opts.SetFailuresPreprocessor(WarningSwallower())
            trans.SetFailureHandlingOptions(opts)
        except Exception:
            pass
        try:
            for element in DB.FilteredElementCollector(doc).WhereElementIsNotElementType():
                current = element_subcategory_id(element)
                if current is None or current not in wanted:
                    continue
                if set_subcategory(element, keep_cat):
                    project_moved += 1
            trans.Commit()
        except Exception as ex:
            try:
                trans.RollBack()
            except Exception:
                pass
            lines.append('Project-level repoint failed: %s' % ex)
    if project_moved:
        lines.append('Repointed %d element(s) placed directly in the project.'
                     % project_moved)

    # ---- 2. families, and families nested inside them --------------------
    families = []
    try:
        for family in DB.FilteredElementCollector(doc).OfClass(DB.Family).ToElements():
            try:
                fam_cat = family.FamilyCategory
                if fam_cat is None or safe_str(fam_cat.Name) != parent_name:
                    continue
                if not family.IsEditable:
                    lines.append('  "%s" is not editable (in-place or system family) - '
                                 'skipped.' % element_name(family))
                    continue
                families.append(family)
            except Exception:
                continue
    except Exception:
        families = []

    lines.append('Checking %d "%s" family(ies), including any nested inside them...'
                 % (len(families), parent_name))
    note(0, len(families), 'Checking %d family(ies)...' % len(families))

    edited = 0
    moved_total = 0
    failures = 0
    for index, family in enumerate(families):
        fam_name = element_name(family)
        note(index, len(families), 'Opening %s (%d of %d)'
             % (fam_name, index + 1, len(families)))
        fam_doc = None
        try:
            fam_doc = doc.EditFamily(family)
        except Exception as ex:
            lines.append('  Could not open "%s" - %s' % (fam_name, ex))
            failures += 1
            continue
        try:
            moved, changed, error = remap_family_subcategories(
                fam_doc, keep_name, drop_names, 0, lambda text: lines.append(text))
            # remap logs nested progress into lines; the bar is driven above
            if error:
                lines.append('  "%s" left untouched - %s' % (fam_name, error))
                failures += 1
            elif changed:
                fam_doc.LoadFamily(doc, FamilyOverwriteOptions())
                edited += 1
                moved_total += moved
                lines.append('  "%s": %d element(s) moved, family reloaded.'
                             % (fam_name, moved))
                note(index + 1, len(families), 'Reloaded %s' % fam_name)
        except Exception as ex:
            lines.append('  "%s" failed - %s' % (fam_name, ex))
            failures += 1
        finally:
            try:
                if fam_doc is not None and fam_doc.IsValidObject:
                    fam_doc.Close(False)
            except Exception:
                pass

    lines.append('%d family(ies) updated, %d element(s) moved.' % (edited, moved_total))

    note(0, 0)

    # ---- 3. remove the now-unused subcategories --------------------------
    deleted = []
    if delete_after:
        if failures:
            lines.append('Not deleting the merged subcategories: %d family(ies) could not '
                         'be updated and may still use them.' % failures)
        else:
            trans = DB.Transaction(doc, 'RevoBIM PY - Delete merged object styles')
            trans.Start()
            try:
                opts = trans.GetFailureHandlingOptions()
                opts.SetFailuresPreprocessor(WarningSwallower())
                trans.SetFailureHandlingOptions(opts)
            except Exception:
                pass
            try:
                names = dict((d['id'], d['name']) for d in drops)
                del_lines, deleted = delete_elements(
                    doc, [d['id'] for d in drops], 'Object style', names)
                lines.extend(del_lines)
                trans.Commit()
            except Exception as ex:
                try:
                    trans.RollBack()
                except Exception:
                    pass
                lines.append('Could not delete the merged subcategories: %s' % ex)
    return lines, deleted


# ---------------------------------------------------------------------------
#  ADDITIONAL STYLE TYPES
# ---------------------------------------------------------------------------
def make_row(rid, name, values, usage=0, signature=None, deletable=True,
             builtin=False, status=None, extra=None):
    """Build one table row in the shape every panel expects."""
    values = dict(values)
    values['Name'] = name
    values['Uses'] = usage if usage is not None else '?'
    values['Status'] = status or ('Unused' if not usage else 'OK')
    values['ElemId'] = str(rid)
    row = {
        'id': rid,
        'name': name,
        'usage': usage,
        'usage_names': [],
        'deletable': deletable,
        'complex': False,
        'builtin': builtin,
        'signature': signature,
        'status': values['Status'],
        'values': values,
    }
    if extra:
        row.update(extra)
    return row


def collect_types(doc, category, family_name=None):
    """Every element type in a category, optionally of one family name."""
    out = []
    try:
        col = DB.FilteredElementCollector(doc).OfCategory(category)\
            .WhereElementIsElementType().ToElements()
    except Exception:
        return out
    for element in col:
        if family_name is not None:
            try:
                if safe_str(element.FamilyName) != family_name:
                    continue
            except Exception:
                continue
        out.append(element)
    return out


def count_instances(doc, category=None, revit_class=None):
    """Instance count keyed by type id."""
    usage = {}
    try:
        col = DB.FilteredElementCollector(doc)
        col = col.OfCategory(category) if category is not None else col.OfClass(revit_class)
        for element in col.WhereElementIsNotElementType():
            key = eid_int(element.GetTypeId())
            usage[key] = usage.get(key, 0) + 1
    except Exception:
        pass
    return usage


def repoint_element_id_params(doc, drop_set, keep_eid, lines, thing,
                              include_types=True):
    """Set every writable ElementId parameter pointing at a dropped style to the
    kept one. This is the mechanism behind most of the merges - a style is used
    by being referenced from a parameter."""
    moved = 0
    touched = 0
    sources = []
    try:
        sources.append(DB.FilteredElementCollector(doc).WhereElementIsNotElementType())
    except Exception:
        pass
    if include_types:
        try:
            sources.append(DB.FilteredElementCollector(doc).WhereElementIsElementType())
        except Exception:
            pass
    for source in sources:
        try:
            elements = list(source)
        except Exception:
            continue
        for element in elements:
            hit = False
            try:
                params = list(element.Parameters)
            except Exception:
                continue
            for param in params:
                try:
                    if param.StorageType != DB.StorageType.ElementId or param.IsReadOnly:
                        continue
                    if eid_int(param.AsElementId()) not in drop_set:
                        continue
                    param.Set(keep_eid)
                    moved += 1
                    hit = True
                except Exception:
                    continue
            if hit:
                touched += 1
    if moved:
        lines.append('Repointed %d %s reference(s) across %d element(s).'
                     % (moved, thing, touched))
    return moved


def merge_by_repoint(doc, rows, keep_id, drop_ids, thing, delete_after=True,
                     extra=None, include_types=True):
    """Generic merge: repoint every reference, then remove the emptied styles.

    extra(doc, keep_id, drop_set, lines) handles references that are properties
    rather than parameters - a category's line pattern, a material's fill pattern
    or appearance asset, a view's template.
    """
    lines = []
    by_id = dict((r['id'], r) for r in rows)
    keep = by_id.get(keep_id)
    if keep is None:
        return ['Merge aborted - the kept %s is no longer in the model.' % thing], []
    drop_set = set(d for d in drop_ids if d in by_id)
    if not drop_set:
        return ['Merge aborted - nothing to merge.'], []

    keep_eid = DB.ElementId(keep_id)
    trans = DB.Transaction(doc, 'RevoBIM PY - Merge %s' % thing)
    trans.Start()
    try:
        opts = trans.GetFailureHandlingOptions()
        opts.SetFailuresPreprocessor(WarningSwallower())
        trans.SetFailureHandlingOptions(opts)
    except Exception:
        pass
    deleted = []
    try:
        repoint_element_id_params(doc, drop_set, keep_eid, lines, thing, include_types)
        if extra is not None:
            extra(doc, keep_id, drop_set, lines)
        if delete_after:
            names = dict((d, by_id[d]['name']) for d in drop_set)
            del_lines, deleted = delete_elements(doc, list(drop_set), thing, names)
            lines.extend(del_lines)
        trans.Commit()
    except Exception as ex:
        try:
            trans.RollBack()
        except Exception:
            pass
        return ['Merge aborted, nothing was changed: %s' % ex], []
    lines.insert(0, 'Merged %d %s(s) into "%s".' % (len(drop_set), thing, keep['name']))
    return lines, deleted


# ---------------------------------------------------------------------------
#  LINE PATTERNS
# ---------------------------------------------------------------------------
def line_pattern_text(pattern):
    """Readable summary of a line pattern's segments."""
    try:
        parts = []
        for seg in pattern.GetSegments():
            kind = safe_str(seg.Type).replace('LinePatternSegmentType.', '')
            length = seg.Length
            if kind.lower() == 'dot':
                parts.append('dot')
            else:
                parts.append('%s %s' % (kind.lower(), fmt_num(round(length * 304.8, 2))))
        return ', '.join(parts)
    except Exception:
        return ''


def gather_line_patterns(doc):
    """Every line pattern, with how many categories and line styles draw with it."""
    usage = {}
    names = {}
    try:
        for cat in doc.Settings.Categories:
            targets = [cat]
            try:
                targets.extend(list(cat.SubCategories))
            except Exception:
                pass
            for target in targets:
                for style_type in (DB.GraphicsStyleType.Projection,
                                   DB.GraphicsStyleType.Cut):
                    try:
                        pid = eid_int(target.GetLinePatternId(style_type))
                    except Exception:
                        continue
                    if pid > 0:
                        usage[pid] = usage.get(pid, 0) + 1
                        names.setdefault(pid, []).append(safe_str(target.Name))
    except Exception:
        pass

    rows = []
    try:
        patterns = DB.FilteredElementCollector(doc).OfClass(DB.LinePatternElement)\
            .ToElements()
    except Exception:
        patterns = []
    for pattern in patterns:
        pid = eid_int(pattern.Id)
        name = element_name(pattern)
        if not name:
            continue
        segments = line_pattern_text(pattern.GetLinePattern())
        uses = usage.get(pid, 0)
        row = make_row(pid, name, {'Segments': segments}, uses,
                       signature=u'LP||%s' % segments.lower())
        row['usage_names'] = names.get(pid, [])[:40]
        rows.append(row)
    rows.sort(key=lambda r: r['name'].lower())
    return rows


def repoint_category_line_patterns(doc, keep_id, drop_set, lines):
    keep_eid = DB.ElementId(keep_id)
    moved = 0
    try:
        for cat in doc.Settings.Categories:
            targets = [cat]
            try:
                targets.extend(list(cat.SubCategories))
            except Exception:
                pass
            for target in targets:
                for style_type in (DB.GraphicsStyleType.Projection,
                                   DB.GraphicsStyleType.Cut):
                    try:
                        if eid_int(target.GetLinePatternId(style_type)) not in drop_set:
                            continue
                        target.SetLinePatternId(keep_eid, style_type)
                        moved += 1
                    except Exception:
                        continue
    except Exception:
        pass
    if moved:
        lines.append('Repointed %d category / subcategory line pattern(s).' % moved)


# ---------------------------------------------------------------------------
#  FILL PATTERNS AND FILLED REGIONS
# ---------------------------------------------------------------------------
def fill_pattern_definition(fill):
    """(readable summary, exact comparison string, number of grids) for a pattern."""
    try:
        if fill.IsSolidFill:
            return 'Solid fill', 'solid', 0
    except Exception:
        pass
    shown = []
    exact = []
    grids = list(fill.GetFillGrids())
    for grid in grids:
        try:
            angle = math.degrees(grid.Angle)
            offset = grid.Offset * 304.8
            shift = grid.Shift * 304.8
            origin = grid.Origin
            ox = origin.U * 304.8
            oy = origin.V * 304.8
            segments = [seg * 304.8 for seg in grid.GetSegments()]
        except Exception:
            continue
        shown.append(u'%s\u00b0 @ %s' % (fmt_num(round(angle, 2)), fmt_num(round(offset, 2))))
        exact.append(u'%s|%s|%s|%s|%s|%s' % (
            fmt_num(round(angle % 360.0, 4)), fmt_num(round(offset, 4)),
            fmt_num(round(shift, 4)), fmt_num(round(ox, 4)), fmt_num(round(oy, 4)),
            u','.join(fmt_num(round(seg, 4)) for seg in segments)))
    # grid order is not meaningful, so sort before comparing
    return u', '.join(shown), u';'.join(sorted(exact)), len(grids)


def gather_fill_patterns(doc):
    """Every fill pattern, with how many materials and filled region types use it."""
    usage = {}
    where = {}

    def bump(pid, label):
        if pid > 0:
            usage[pid] = usage.get(pid, 0) + 1
            where.setdefault(pid, []).append(label)

    try:
        for mat in DB.FilteredElementCollector(doc).OfClass(DB.Material):
            label = element_name(mat)
            for attr in ('SurfaceForegroundPatternId', 'SurfaceBackgroundPatternId',
                         'CutForegroundPatternId', 'CutBackgroundPatternId'):
                try:
                    bump(eid_int(getattr(mat, attr)), 'material %s' % label)
                except Exception:
                    continue
    except Exception:
        pass
    try:
        for frt in DB.FilteredElementCollector(doc).OfClass(DB.FilledRegionType):
            label = element_name(frt)
            for attr in ('ForegroundPatternId', 'BackgroundPatternId'):
                try:
                    bump(eid_int(getattr(frt, attr)), 'filled region %s' % label)
                except Exception:
                    continue
    except Exception:
        pass

    rows = []
    try:
        patterns = DB.FilteredElementCollector(doc).OfClass(DB.FillPatternElement)\
            .ToElements()
    except Exception:
        patterns = []
    for element in patterns:
        pid = eid_int(element.Id)
        name = element_name(element)
        if not name:
            continue
        target = ''
        kind = ''
        summary = ''
        exact = ''
        grids = 0
        try:
            fill = element.GetFillPattern()
            target = safe_str(fill.Target).replace('FillPatternTarget.', '')
            kind = safe_str(fill.HostOrientation).replace('FillPatternHostOrientation.', '')
            summary, exact, grids = fill_pattern_definition(fill)
        except Exception:
            pass
        uses = usage.get(pid, 0)
        row = make_row(pid, name, {'Target': target, 'Orientation': kind,
                                   'Grids': grids, 'Definition': summary}, uses,
                       signature=u'FP')
        # Matching on target and orientation alone made every drafting hatch with
        # the same orientation a "duplicate" of every other. The grid lines are
        # what make a pattern look the way it does, so they are what is compared.
        row['dup'] = {'Target': target.lower(), 'Orientation': kind.lower(),
                      'Definition': exact}
        row['usage_names'] = where.get(pid, [])[:40]
        rows.append(row)
    rows.sort(key=lambda r: r['name'].lower())
    return rows


def repoint_fill_patterns(doc, keep_id, drop_set, lines):
    keep_eid = DB.ElementId(keep_id)
    moved = 0
    for collector, attrs in (
            (DB.Material, ('SurfaceForegroundPatternId', 'SurfaceBackgroundPatternId',
                           'CutForegroundPatternId', 'CutBackgroundPatternId')),
            (DB.FilledRegionType, ('ForegroundPatternId', 'BackgroundPatternId'))):
        try:
            elements = list(DB.FilteredElementCollector(doc).OfClass(collector))
        except Exception:
            continue
        for element in elements:
            for attr in attrs:
                try:
                    if eid_int(getattr(element, attr)) not in drop_set:
                        continue
                    setattr(element, attr, keep_eid)
                    moved += 1
                except Exception:
                    continue
    if moved:
        lines.append('Repointed %d material / filled region pattern reference(s).' % moved)


def gather_filled_regions(doc):
    """Every filled region type with its patterns, colour and boundary."""
    usage = count_instances(doc, revit_class=DB.FilledRegion)
    pattern_names = {}
    try:
        for fp in DB.FilteredElementCollector(doc).OfClass(DB.FillPatternElement):
            pattern_names[eid_int(fp.Id)] = element_name(fp)
    except Exception:
        pass
    style_names = {}
    try:
        for gs in DB.FilteredElementCollector(doc).OfClass(DB.GraphicsStyle):
            style_names[eid_int(gs.Id)] = element_name(gs)
    except Exception:
        pass

    rows = []
    try:
        types = DB.FilteredElementCollector(doc).OfClass(DB.FilledRegionType).ToElements()
    except Exception:
        types = []
    for frt in types:
        tid = eid_int(frt.Id)
        name = element_name(frt)
        if not name:
            continue

        def safe(fn, default=''):
            try:
                return fn()
            except Exception:
                return default

        fore = safe(lambda: pattern_names.get(eid_int(frt.ForegroundPatternId), ''))
        back = safe(lambda: pattern_names.get(eid_int(frt.BackgroundPatternId), ''))
        fore_colour = safe(lambda: colour_text(frt.ForegroundPatternColor))
        back_colour = safe(lambda: colour_text(frt.BackgroundPatternColor))
        masking = safe(lambda: _yes_no(frt.IsMasking), '')
        weight = safe(lambda: str(frt.LineWeight), '')
        boundary = safe(lambda: style_names.get(
            eid_int(frt.get_Parameter(bip('FILL_REGION_LINE_STYLE')).AsElementId()), ''))

        values = {'Foreground': fore, 'ForeColour': fore_colour, 'Background': back,
                  'BackColour': back_colour, 'Masking': masking, 'Weight': weight,
                  'Boundary': boundary}
        rows.append(make_row(tid, name, values, usage.get(tid, 0),
                             signature=u'FR||%s||%s||%s||%s||%s' % (
                                 fore.lower(), fore_colour.lower(), back.lower(),
                                 back_colour.lower(), masking.lower())))
    rows.sort(key=lambda r: r['name'].lower())
    return rows


# ---------------------------------------------------------------------------
#  MATERIAL APPEARANCE ASSETS
# ---------------------------------------------------------------------------
ASSET_IDENTITY = ('uiname', 'description', 'keyword', 'thumbnail', 'assetlibid',
                  'version', 'category', 'revision', 'localname', 'baseschema')


def _asset_props(asset):
    try:
        size = asset.Size
    except Exception:
        return []
    out = []
    for index in range(size):
        prop = None
        try:
            prop = asset.Get(index)
        except Exception:
            try:
                prop = asset[index]
            except Exception:
                prop = None
        if prop is not None:
            out.append(prop)
    return out


def asset_settings(asset, depth=0):
    """Every rendering property that affects how a material looks, as one string.

    Identity fields - the asset's own name, description, keywords, library ids -
    are left out, so two assets differing only in what they are called compare
    equal. Connected assets (texture maps) are followed one level down so a brick
    bitmap and a tile bitmap do not compare equal either.
    """
    parts = []
    for prop in _asset_props(asset):
        try:
            name = safe_str(prop.Name)
        except Exception:
            continue
        low = name.lower()
        if any(word in low for word in ASSET_IDENTITY):
            continue
        value = ''
        try:
            value = u','.join(fmt_num(round(v, 5)) for v in prop.GetValueAsDoubles())
        except Exception:
            try:
                raw = prop.Value
                try:
                    value = fmt_num(round(float(raw), 5))
                except Exception:
                    value = safe_str(raw)
            except Exception:
                value = ''
        if depth < 1:
            try:
                for connected in prop.GetAllConnectedProperties():
                    inner, _count = asset_settings(connected, depth + 1)
                    value += u'{%s}' % inner
            except Exception:
                pass
        parts.append(u'%s=%s' % (low, value))
    parts.sort()
    return u';'.join(parts), len(parts)


def gather_appearance_assets(doc):
    """Every rendering appearance asset, with the materials that use it."""
    usage = {}
    where = {}
    try:
        for mat in DB.FilteredElementCollector(doc).OfClass(DB.Material):
            try:
                aid = eid_int(mat.AppearanceAssetId)
            except Exception:
                continue
            if aid > 0:
                usage[aid] = usage.get(aid, 0) + 1
                where.setdefault(aid, []).append(element_name(mat))
    except Exception:
        pass

    rows = []
    try:
        assets = DB.FilteredElementCollector(doc).OfClass(DB.AppearanceAssetElement)\
            .ToElements()
    except Exception:
        assets = []
    for asset in assets:
        aid = eid_int(asset.Id)
        name = element_name(asset)
        if not name:
            continue
        schema = ''
        settings = ''
        count = 0
        try:
            rendering = asset.GetRenderingAsset()
            schema = safe_str(rendering.Name)
            settings, count = asset_settings(rendering)
        except Exception:
            schema = ''
        uses = usage.get(aid, 0)
        row = make_row(aid, name, {'Schema': schema, 'Properties': count}, uses,
                       signature=u'AA')
        # Matching on the schema alone made every Generic asset a "duplicate" of
        # every other Generic asset, whatever its colour, texture or finish.
        row['dup'] = {'Schema': schema.strip().lower(), 'Settings': settings}
        row['usage_names'] = where.get(aid, [])[:40]
        rows.append(row)
    rows.sort(key=lambda r: r['name'].lower())
    return rows


def repoint_appearance_assets(doc, keep_id, drop_set, lines):
    keep_eid = DB.ElementId(keep_id)
    moved = 0
    try:
        for mat in DB.FilteredElementCollector(doc).OfClass(DB.Material):
            try:
                if eid_int(mat.AppearanceAssetId) not in drop_set:
                    continue
                mat.AppearanceAssetId = keep_eid
                moved += 1
            except Exception:
                continue
    except Exception:
        pass
    if moved:
        lines.append('Repointed %d material(s) onto the kept appearance asset.' % moved)


# ---------------------------------------------------------------------------
#  VIEW TEMPLATES, VIEWPORTS, SCOPE BOXES
# ---------------------------------------------------------------------------
def gather_view_templates(doc):
    """Every view template, with how many views it drives."""
    usage = {}
    where = {}
    try:
        for view in DB.FilteredElementCollector(doc).OfClass(DB.View):
            try:
                if view.IsTemplate:
                    continue
                tid = eid_int(view.ViewTemplateId)
            except Exception:
                continue
            if tid > 0:
                usage[tid] = usage.get(tid, 0) + 1
                where.setdefault(tid, []).append(safe_str(view.Name))
    except Exception:
        pass

    rows = []
    try:
        views = DB.FilteredElementCollector(doc).OfClass(DB.View).ToElements()
    except Exception:
        views = []
    for view in views:
        try:
            if not view.IsTemplate:
                continue
        except Exception:
            continue
        vid = eid_int(view.Id)
        name = safe_str(view.Name)
        kind = safe_str(view.ViewType)
        controlled = ''
        try:
            total = len(list(view.GetTemplateParameterIds()))
            free = len(list(view.GetNonControlledTemplateParameterIds()))
            controlled = '%d of %d' % (total - free, total)
        except Exception:
            controlled = ''
        uses = usage.get(vid, 0)
        row = make_row(vid, name, {'ViewType': kind, 'Controlled': controlled}, uses,
                       signature=None)
        row['usage_names'] = where.get(vid, [])[:40]
        rows.append(row)
    rows.sort(key=lambda r: r['name'].lower())
    return rows


def repoint_view_templates(doc, keep_id, drop_set, lines):
    keep_eid = DB.ElementId(keep_id)
    moved = 0
    try:
        for view in DB.FilteredElementCollector(doc).OfClass(DB.View):
            try:
                if view.IsTemplate:
                    continue
                if eid_int(view.ViewTemplateId) not in drop_set:
                    continue
                view.ViewTemplateId = keep_eid
                moved += 1
            except Exception:
                continue
    except Exception:
        pass
    if moved:
        lines.append('Moved %d view(s) onto the kept template.' % moved)


def gather_viewports(doc):
    """Every viewport type, with how many placed views use it."""
    usage = count_instances(doc, revit_class=DB.Viewport)
    rows = []
    for element in collect_types(doc, DB.BuiltInCategory.OST_Viewports):
        tid = eid_int(element.Id)
        name = element_name(element)
        if not name:
            continue
        values = {}
        parts = []
        for column, param_name in (('ShowTitle', 'VIEWPORT_ATTR_SHOW_LABEL'),
                                   ('ShowExtension', 'VIEWPORT_ATTR_SHOW_EXTENSION_LINE'),
                                   ('LineWeight', 'VIEWPORT_ATTR_LINE_WEIGHT'),
                                   ('TitleType', 'VIEWPORT_ATTR_LABEL_TAG')):
            which = bip(param_name)
            text = param_display(element, which) if which is not None else ''
            values[column] = text
            parts.append(text.lower())
        rows.append(make_row(tid, name, values, usage.get(tid, 0),
                             signature=u'VP||' + u'||'.join(parts)))
    rows.sort(key=lambda r: r['name'].lower())
    return rows


def gather_scope_boxes(doc):
    """Every scope box, with the views and datums referencing it."""
    usage = {}
    where = {}
    crop_param = bip('VIEWER_VOLUME_OF_INTEREST_CROP')
    datum_param = bip('DATUM_VOLUME_OF_INTEREST')

    def scan(collector, which, label_fn):
        if which is None:
            return
        try:
            for element in collector:
                try:
                    param = element.get_Parameter(which)
                    if param is None:
                        continue
                    sid = eid_int(param.AsElementId())
                except Exception:
                    continue
                if sid > 0:
                    usage[sid] = usage.get(sid, 0) + 1
                    where.setdefault(sid, []).append(label_fn(element))
        except Exception:
            pass

    try:
        scan(DB.FilteredElementCollector(doc).OfClass(DB.View), crop_param,
             lambda v: 'view %s' % safe_str(v.Name))
    except Exception:
        pass
    for cls in (DB.Grid, DB.Level, DB.ReferencePlane):
        try:
            scan(DB.FilteredElementCollector(doc).OfClass(cls), datum_param,
                 lambda e: '%s %s' % (cls.__name__.lower(), element_name(e)))
        except Exception:
            continue

    rows = []
    try:
        boxes = DB.FilteredElementCollector(doc)\
            .OfCategory(DB.BuiltInCategory.OST_VolumeOfInterest)\
            .WhereElementIsNotElementType().ToElements()
    except Exception:
        boxes = []
    for box in boxes:
        sid = eid_int(box.Id)
        name = element_name(box)
        if not name:
            continue
        row = make_row(sid, name, {}, usage.get(sid, 0), signature=None)
        row['usage_names'] = where.get(sid, [])[:40]
        rows.append(row)
    rows.sort(key=lambda r: r['name'].lower())
    return rows


# ---------------------------------------------------------------------------
#  FONTS AND ARROWHEADS
# ---------------------------------------------------------------------------
ARROW_FIELDS = [
    ('Style', 'ARROW_STYLE', 'valuestring'),
    ('Size', 'ARROW_WIDTH', 'valuestring'),
    ('TickSize', 'ARROW_TICK_MARK_PEN', 'int'),
    ('Filled', 'ARROW_TICK_IS_FILLED', 'bool'),
    ('Closed', 'ARROW_CLOSED', 'bool'),
    ('Angle', 'ARROW_TICK_MARK_ANGLE', 'valuestring'),
    ('LineWeight', 'LINE_PEN', 'int'),
]


FONT_HOSTS = [
    (DB.TextNoteType, 'text style', 'TEXT_FONT'),
    (DB.DimensionType, 'dimension style', 'TEXT_FONT'),
]


def gather_fonts(doc):
    """Every font actually referenced by a text or dimension style.

    A font is not a Revit element, so it has no id of its own. Rows are keyed by a
    stable hash of the font name, and merging rewrites the styles that use it.
    """
    tally = {}
    for revit_class, label, param_name in FONT_HOSTS:
        which = bip(param_name)
        if which is None:
            continue
        try:
            types = DB.FilteredElementCollector(doc).OfClass(revit_class).ToElements()
        except Exception:
            continue
        for element in types:
            try:
                param = element.get_Parameter(which)
                font = safe_str(param.AsString()) if param is not None else ''
            except Exception:
                font = ''
            if not font:
                continue
            record = tally.setdefault(font, {'text': 0, 'dim': 0, 'names': []})
            record['text' if label == 'text style' else 'dim'] += 1
            if len(record['names']) < 40:
                record['names'].append('%s %s' % (label, element_name(element)))

    rows = []
    for font, record in tally.items():
        total = record['text'] + record['dim']
        rid = abs(hash(font.lower())) % 900000000 + 1000
        row = make_row(rid, font,
                       {'TextStyles': record['text'], 'DimStyles': record['dim']},
                       total, signature=None, deletable=False,
                       status='In use' if total else 'Unused')
        row['font_name'] = font
        row['usage_names'] = record['names']
        rows.append(row)
    rows.sort(key=lambda r: r['name'].lower())
    return rows


def merge_fonts(doc, rows, keep_id, drop_ids, delete_after=True):
    """Rewrite every text and dimension style off the dropped fonts onto the kept one."""
    lines = []
    by_id = dict((r['id'], r) for r in rows)
    keep = by_id.get(keep_id)
    if keep is None:
        return ['Merge aborted - the kept font is no longer listed.'], []
    keep_font = keep.get('font_name', keep['name'])
    drop_fonts = set(safe_str(by_id[d].get('font_name', by_id[d]['name'])).lower()
                     for d in drop_ids if d in by_id)
    if not drop_fonts:
        return ['Merge aborted - nothing to merge.'], []

    trans = DB.Transaction(doc, 'RevoBIM PY - Merge Fonts')
    trans.Start()
    try:
        opts = trans.GetFailureHandlingOptions()
        opts.SetFailuresPreprocessor(WarningSwallower())
        trans.SetFailureHandlingOptions(opts)
    except Exception:
        pass
    moved = 0
    try:
        for revit_class, label, param_name in FONT_HOSTS:
            which = bip(param_name)
            if which is None:
                continue
            try:
                types = DB.FilteredElementCollector(doc).OfClass(revit_class).ToElements()
            except Exception:
                continue
            for element in types:
                try:
                    param = element.get_Parameter(which)
                    if param is None or param.IsReadOnly:
                        continue
                    if safe_str(param.AsString()).lower() not in drop_fonts:
                        continue
                    param.Set(keep_font)
                    moved += 1
                    lines.append('  %s "%s" -> %s' % (label, element_name(element),
                                                      keep_font))
                except Exception as ex:
                    lines.append('  Could not change "%s" - %s'
                                 % (element_name(element), ex))
        trans.Commit()
    except Exception as ex:
        try:
            trans.RollBack()
        except Exception:
            pass
        return ['Merge aborted, nothing was changed: %s' % ex], []
    lines.insert(0, 'Moved %d style(s) onto "%s". A font is not a Revit element, so '
                    'nothing is deleted - the old font simply stops being referenced.'
                 % (moved, keep_font))
    return lines, []


def gather_arrowheads(doc):
    """Every arrowhead style, with the types that point at it."""
    usage = {}
    where = {}
    try:
        for element in DB.FilteredElementCollector(doc).WhereElementIsElementType():
            try:
                params = list(element.Parameters)
            except Exception:
                continue
            for param in params:
                try:
                    if param.StorageType != DB.StorageType.ElementId:
                        continue
                    name = safe_str(param.Definition.Name).lower()
                    if 'arrowhead' not in name and 'tick mark' not in name:
                        continue
                    aid = eid_int(param.AsElementId())
                except Exception:
                    continue
                if aid > 0:
                    usage[aid] = usage.get(aid, 0) + 1
                    if len(where.setdefault(aid, [])) < 40:
                        where[aid].append(element_name(element))
    except Exception:
        pass

    rows = []
    seen = set()
    try:
        types = DB.FilteredElementCollector(doc).OfClass(DB.ElementType).ToElements()
    except Exception:
        types = []
    for element in types:
        try:
            if safe_str(element.FamilyName) != 'Arrowhead':
                continue
        except Exception:
            continue
        aid = eid_int(element.Id)
        if aid in seen:
            continue
        seen.add(aid)
        name = element_name(element)
        if not name:
            continue
        values = {}
        parts = []
        for column, param_name, _kind in ARROW_FIELDS:
            which = bip(param_name)
            text = param_display(element, which) if which is not None else ''
            values[column] = text
            parts.append(text.lower())
        row = make_row(aid, name, values, usage.get(aid, 0),
                       signature=u'AH||' + u'||'.join(parts))
        row['editable'] = writable_fields(element, ARROW_FIELDS)
        row['usage_names'] = where.get(aid, [])
        rows.append(row)
    rows.sort(key=lambda r: r['name'].lower())
    return rows


# ---------------------------------------------------------------------------
#  PARAMETERS AND GLOBAL PARAMETERS
# ---------------------------------------------------------------------------
def spec_labels(definition):
    """(data type, discipline) as Revit words them, whatever the API version."""
    data_type = ''
    discipline = ''
    spec = None
    try:
        spec = definition.GetDataType()
    except Exception:
        spec = None
    if spec is not None:
        try:
            data_type = safe_str(DB.LabelUtils.GetLabelForSpec(spec))
        except Exception:
            try:
                data_type = safe_str(spec.TypeId).split(':')[0].split('-')[0]
            except Exception:
                data_type = ''
        try:
            discipline = safe_str(DB.LabelUtils.GetLabelForDiscipline(
                DB.UnitUtils.GetDiscipline(spec)))
        except Exception:
            discipline = ''
    if not data_type:
        try:
            data_type = safe_str(definition.ParameterType)
        except Exception:
            data_type = ''
    return data_type, discipline


def group_label_for(definition):
    try:
        return safe_str(DB.LabelUtils.GetLabelForGroup(definition.GetGroupTypeId()))
    except Exception:
        pass
    try:
        return safe_str(DB.LabelUtils.GetLabelFor(definition.ParameterGroup))
    except Exception:
        pass
    try:
        return safe_str(definition.ParameterGroup)
    except Exception:
        return ''


def gather_parameters(doc):
    """Every parameter defined in the project.

    The list is driven from doc.ParameterBindings, not from a ParameterElement
    collector. A non-shared project parameter has no ParameterElement of its own,
    so collecting elements finds only the shared ones - which is why this tab came
    up empty on models whose parameters are all project parameters. The binding
    table is the authoritative list of what the project actually defines, and the
    collectors are then used to pick up anything defined but not bound.
    """
    rows = []
    seen = set()

    def add(pid, name, kind, binding, definition, cats, cat_ids, guid, bound):
        if not name or pid in seen:
            return
        seen.add(pid)
        data_type, discipline = spec_labels(definition)
        values = {
            'Kind': kind,
            'Binding': binding,
            'Discipline': discipline,
            'DataType': data_type,
            'ParamGroup': group_label_for(definition),
            'Categories': ', '.join(cats),
            'CategoryCount': len(cats),
            'Guid': guid,
        }
        row = make_row(pid, name, values, None, signature=None,
                       deletable=True,
                       status='Not analysed' if bound else 'Defined, not bound')
        row['param_name'] = name
        row['cat_ids'] = cat_ids
        row['shared'] = kind == 'Shared'
        row['bound'] = bound
        row['values']['Uses'] = '?' if bound else '0'
        rows.append(row)

    # ---- 1. everything the project actually binds -------------------------
    try:
        iterator = doc.ParameterBindings.ForwardIterator()
        iterator.Reset()
        while iterator.MoveNext():
            definition = iterator.Key
            binding = iterator.Current
            cats = []
            cat_ids = []
            try:
                for cat in binding.Categories:
                    cats.append(safe_str(cat.Name))
                    cat_ids.append(eid_int(cat.Id))
            except Exception:
                pass
            cats.sort()
            try:
                pid = eid_int(definition.Id)
            except Exception:
                pid = -1
            guid = ''
            kind = 'Project'
            try:
                element = doc.GetElement(definition.Id)
                if isinstance(element, DB.SharedParameterElement):
                    kind = 'Shared'
                    guid = safe_str(element.GuidValue)
            except Exception:
                pass
            add(pid, safe_str(definition.Name), kind,
                'Instance' if isinstance(binding, DB.InstanceBinding) else 'Type',
                definition, cats, cat_ids, guid, True)
    except Exception:
        pass

    # ---- 2. anything defined but bound to nothing -------------------------
    for revit_class in (DB.SharedParameterElement, DB.ParameterElement):
        try:
            elements = DB.FilteredElementCollector(doc).OfClass(revit_class).ToElements()
        except Exception:
            continue
        for element in elements:
            try:
                if isinstance(element, DB.GlobalParameter):
                    continue          # global parameters have their own tab
            except Exception:
                pass
            try:
                definition = element.GetDefinition()
            except Exception:
                continue
            if definition is None:
                continue
            shared = isinstance(element, DB.SharedParameterElement)
            guid = ''
            if shared:
                try:
                    guid = safe_str(element.GuidValue)
                except Exception:
                    guid = ''
            add(eid_int(element.Id), safe_str(definition.Name),
                'Shared' if shared else 'Project', '', definition, [], [], guid, False)

    rows.sort(key=lambda r: r['name'].lower())
    return rows


def gather_global_parameters(doc):
    """Every global parameter with its value, formula and dependants."""
    rows = []
    try:
        ids = list(DB.GlobalParametersManager.GetAllGlobalParameters(doc))
    except Exception:
        ids = []
    for gid in ids:
        element = doc.GetElement(gid)
        if element is None:
            continue
        pid = eid_int(gid)
        name = safe_str(element.Name)
        value = ''
        try:
            data = element.GetValue()
            if isinstance(data, DB.DoubleParameterValue):
                value = fmt_num(data.Value)
            elif isinstance(data, DB.IntegerParameterValue):
                value = safe_str(data.Value)
            elif isinstance(data, DB.StringParameterValue):
                value = safe_str(data.Value)
            elif isinstance(data, DB.ElementIdParameterValue):
                value = element_name(doc.GetElement(data.Value))
        except Exception:
            value = ''
        formula = ''
        try:
            formula = safe_str(element.GetFormula())
        except Exception:
            formula = ''
        reporting = ''
        try:
            reporting = _yes_no(element.IsReporting)
        except Exception:
            reporting = ''
        data_type = ''
        try:
            data_type = safe_str(DB.LabelUtils.GetLabelForSpec(element.GetDefinition()
                                                              .GetDataType()))
        except Exception:
            pass
        uses = 0
        labels = []
        try:
            for dep in element.GetDependentGlobalParameters():
                uses += 1
                labels.append(safe_str(doc.GetElement(dep).Name))
        except Exception:
            pass
        try:
            uses += len(list(element.GetLabeledDimensions()))
        except Exception:
            pass
        row = make_row(pid, name, {'DataType': data_type, 'Value': value,
                                   'Formula': formula, 'Reporting': reporting},
                       uses, signature=None)
        row['usage_names'] = labels[:40]
        rows.append(row)
    rows.sort(key=lambda r: r['name'].lower())
    return rows


def write_named_element_changes(doc, rows, pending):
    """Rename elements, and nothing else. The first release of several tabs only
    exposes the name for editing, because the rest of their properties are set
    through Revit dialogs that have no API equivalent."""
    lines = []
    changed = []
    snapshot = dict((r['id'], r) for r in rows)
    names = set(safe_str(r['name']).lower() for r in rows)

    for rid in sorted(pending.keys()):
        change = pending[rid]
        row = snapshot.get(rid)
        element = doc.GetElement(DB.ElementId(rid))
        if row is None or element is None:
            lines.append('Skipped id %d - no longer in the model' % rid)
            continue
        writable, why = is_writable(doc, element)
        if not writable:
            lines.append('Skipped "%s" - %s' % (row['name'], why))
            continue
        if not change.get('Name'):
            continue
        wanted = safe_str(change['Name']).strip()
        old = safe_str(row['name'])
        names.discard(old.lower())
        final = unique_name_in(wanted, names)
        try:
            element.Name = final
            names.add(final.lower())
            note = 'renamed "%s" -> "%s"' % (old, final)
            if final != wanted:
                note += ' ("%s" was already in use)' % wanted
            changed.append(rid)
            lines.append(note)
        except Exception as ex:
            names.add(old.lower())
            lines.append('Could not rename "%s" - %s' % (old, ex))

    return lines, changed


# ---------------------------------------------------------------------------
#  TAG STYLES
# ---------------------------------------------------------------------------
TAG_FIELDS = [
    ('Arrowhead', 'LEADER_ARROWHEAD', 'element'),
    ('Font', 'TEXT_FONT', 'string'),
    ('Size', 'TEXT_SIZE', 'valuestring'),
    ('Width', 'TEXT_WIDTH_SCALE', 'double'),
    ('Bold', 'TEXT_STYLE_BOLD', 'bool'),
    ('Italic', 'TEXT_STYLE_ITALIC', 'bool'),
    ('Underline', 'TEXT_STYLE_UNDERLINE', 'bool'),
    ('Background', 'TEXT_BACKGROUND', 'valuestring'),
    ('ShowBorder', 'LEADER_OFFSET_SHEET', 'valuestring'),
    ('Colour', 'LINE_COLOR', 'colour'),
]

YES_NO_CHOICES = ['Yes', 'No']


def arrowhead_lookup(doc):
    """name -> ElementId for every arrowhead style in the project."""
    lookup = {}
    try:
        for element in DB.FilteredElementCollector(doc).OfClass(DB.ElementType):
            try:
                if safe_str(element.FamilyName) != 'Arrowhead':
                    continue
            except Exception:
                continue
            name = element_name(element)
            if name:
                lookup[name.strip().lower()] = element.Id
    except Exception:
        pass
    return lookup


def is_tag_category(cat):
    try:
        if cat is None:
            return False
        if cat.CategoryType != DB.CategoryType.Annotation:
            return False
        name = safe_str(cat.Name)
        return 'tag' in name.lower() or name.lower().endswith('keynotes')
    except Exception:
        return False


def gather_tag_styles(doc, report=None):
    """Every tag family type in the project, grouped by the category it tags."""
    note = report if report is not None else (lambda d, t, x='': None)
    rows = []
    try:
        symbols = DB.FilteredElementCollector(doc).OfClass(DB.FamilySymbol).ToElements()
    except Exception:
        symbols = []

    tag_symbols = []
    for symbol in symbols:
        try:
            if is_tag_category(symbol.Category):
                tag_symbols.append(symbol)
        except Exception:
            continue

    usage = {}
    try:
        for element in DB.FilteredElementCollector(doc).WhereElementIsNotElementType():
            try:
                if not is_tag_category(element.Category):
                    continue
                key = eid_int(element.GetTypeId())
            except Exception:
                continue
            usage[key] = usage.get(key, 0) + 1
    except Exception:
        pass

    total = len(tag_symbols)
    for index, symbol in enumerate(tag_symbols):
        if total and index % 25 == 0:
            note(index, total, 'Reading tag types...')
        tid = eid_int(symbol.Id)
        type_name = element_name(symbol)
        try:
            family_name = safe_str(symbol.Family.Name)
        except Exception:
            family_name = safe_str(symbol.FamilyName)
        try:
            category = safe_str(symbol.Category.Name)
        except Exception:
            category = ''

        values = {'Category': category, 'FamilyName': family_name,
                  'TypeName': type_name}
        parts = []
        for column, param_name, kind in TAG_FIELDS:
            which = bip(param_name)
            if which is None:
                values[column] = ''
                continue
            if kind == 'colour':
                text = ''
                try:
                    param = symbol.get_Parameter(which)
                    if param is not None:
                        raw = param.AsInteger()
                        text = '%d,%d,%d' % (raw % 256, (raw // 256) % 256,
                                             (raw // 65536) % 256)
                except Exception:
                    text = ''
            else:
                text = param_display(symbol, which)
                if kind == 'element' and not safe_str(text).strip():
                    try:
                        param = symbol.get_Parameter(which)
                        if param is not None:
                            text = NO_VALUE
                    except Exception:
                        pass
            values[column] = text
            parts.append(u'%s=%s' % (column, safe_str(text).lower()))

        uses = usage.get(tid, 0)
        row = make_row(tid, u'%s : %s' % (family_name, type_name), values, uses,
                       signature=u'TAG||%s||%s' % (category.lower(), u'||'.join(parts)))
        row['values']['Name'] = type_name
        row['editable'] = writable_fields(symbol, TAG_FIELDS)
        row['type_name'] = type_name
        row['family_name'] = family_name
        row['category'] = category
        rows.append(row)

    rows.sort(key=lambda r: (r['category'].lower(), r['name'].lower()))
    note(0, 0)
    return rows


def write_tag_changes(doc, rows, pending, report=None):
    """Apply staged tag type edits. Caller owns the transaction."""
    note = report if report is not None else (lambda d, t, x='': None)
    lines = []
    changed = []
    snapshot = dict((r['id'], r) for r in rows)
    arrowheads = arrowhead_lookup(doc)
    field_map = dict((c, (p, k)) for c, p, k in TAG_FIELDS)
    names = set()

    keys = sorted(pending.keys())
    for index, tid in enumerate(keys):
        note(index, len(keys), 'Writing tag types...')
        change = pending[tid]
        row = snapshot.get(tid)
        symbol = doc.GetElement(DB.ElementId(tid))
        if row is None or symbol is None:
            lines.append('Skipped id %d - no longer in the model' % tid)
            continue
        writable, why = is_writable(doc, symbol)
        if not writable:
            lines.append('Skipped "%s" - %s' % (row['name'], why))
            continue

        done = []
        if change.get('Name'):
            wanted = safe_str(change['Name']).strip()
            if not names:
                for other in rows:
                    names.add(safe_str(other['values'].get('Name', '')).lower())
            names.discard(safe_str(row['values'].get('Name', '')).lower())
            final = unique_name_in(wanted, names)
            try:
                symbol.Name = final
                names.add(final.lower())
                done.append('renamed to "%s"' % final)
            except Exception as ex:
                lines.append('Could not rename "%s" - %s' % (row['name'], ex))

        for column in sorted(change.keys()):
            if column == 'Name' or column not in field_map:
                continue
            param_name, kind = field_map[column]
            which = bip(param_name)
            if which is None:
                lines.append('"%s": %s is not available in this Revit version'
                             % (row['name'], column))
                continue
            value = safe_str(change[column]).strip()
            try:
                if kind == 'element':
                    param = symbol.get_Parameter(which)
                    if param is None or param.IsReadOnly:
                        raise Exception('this family does not expose it as a writable '
                                        'type parameter')
                    if value.lower() in (NO_VALUE, 'none', ''):
                        param.Set(DB.ElementId.InvalidElementId)
                    else:
                        eid = arrowheads.get(value.lower())
                        if eid is None:
                            raise Exception('"%s" is not an arrowhead in this project'
                                            % value)
                        param.Set(eid)
                elif kind == 'colour':
                    colour = parse_colour(value)
                    param = symbol.get_Parameter(which)
                    if param is None or param.IsReadOnly:
                        raise Exception('read only')
                    param.Set(colour.Red + colour.Green * 256 + colour.Blue * 65536)
                else:
                    write_param(symbol, which, value, kind)
                done.append('%s -> %s' % (column.lower(), value))
            except Exception as ex:
                lines.append('"%s": %s not changed - %s' % (row['name'], column, ex))

        if done:
            changed.append(tid)
            lines.append('%s: %s' % (row['name'], '; '.join(done)))

    note(0, 0)
    return lines, changed


# ---------------------------------------------------------------------------
#  PROJECT PARAMETER USAGE
# ---------------------------------------------------------------------------
USAGE_CAP = 50


def analyze_parameters(doc, rows, targets, report=None):
    """Work out which project parameters actually hold a value somewhere.

    Two things made this slow and one made it wrong. Slow: every element asked
    for every parameter by name (LookupParameter walks the element's whole
    parameter set, and it picks the wrong one when two parameters share a name),
    and every element of a category was visited even once every parameter bound
    to it was known to be used. Wrong: once 20 examples were recorded the count
    stopped as well, so "Elements With A Value" could never read above 20.

    Now each parameter is looked up by its own definition, counting stops at
    USAGE_CAP with the result shown as "50+", and a category is abandoned the
    moment every parameter bound to it has reached the cap.
    """
    note = report if report is not None else (lambda d, t, x='': None)
    lines = []
    wanted = [r for r in targets if r.get('param_name')]
    if not wanted:
        return ['Nothing to analyse.'], {}

    definitions = {}
    for row in wanted:
        definition = None
        try:
            element = doc.GetElement(DB.ElementId(row['id']))
            if element is not None:
                definition = element.GetDefinition()
        except Exception:
            definition = None
        definitions[row['id']] = definition

    def lookup(element, row):
        definition = definitions.get(row['id'])
        if definition is not None:
            try:
                # An element that does not carry this parameter answers None, and
                # that is the answer - falling back to the name here would find
                # a different parameter that happens to share it.
                return element.get_Parameter(definition)
            except Exception:
                pass
        try:
            return element.LookupParameter(row['param_name'])
        except Exception:
            return None

    def has_value(param):
        try:
            if param is None or not param.HasValue:
                return False
            if param.StorageType == DB.StorageType.String:
                return bool(safe_str(param.AsString()).strip())
            if param.StorageType == DB.StorageType.ElementId:
                return eid_int(param.AsElementId()) > 0
            return True
        except Exception:
            return False

    by_category = {}
    for row in wanted:
        for cat_id in row.get('cat_ids', []):
            by_category.setdefault(cat_id, []).append(row)

    counts = dict((r['id'], 0) for r in wanted)
    where = dict((r['id'], []) for r in wanted)

    cat_ids = sorted(by_category.keys())
    for index, cat_id in enumerate(cat_ids):
        note(index, len(cat_ids), 'Scanning category %d of %d...'
             % (index + 1, len(cat_ids)))
        active = [r for r in by_category[cat_id] if counts[r['id']] < USAGE_CAP]
        for is_type in (False, True):
            if not active:
                break
            try:
                col = DB.FilteredElementCollector(doc).OfCategoryId(DB.ElementId(cat_id))
                col = col.WhereElementIsElementType() if is_type \
                    else col.WhereElementIsNotElementType()
            except Exception:
                continue
            for element in col:
                for row in active:
                    if not has_value(lookup(element, row)):
                        continue
                    counts[row['id']] += 1
                    if len(where[row['id']]) < 20:
                        try:
                            label = safe_str(element.Category.Name)
                        except Exception:
                            label = 'element'
                        where[row['id']].append('%s %d' % (label, eid_int(element.Id)))
                active = [r for r in active if counts[r['id']] < USAGE_CAP]
                if not active:
                    break

    used = len([r for r in wanted if counts[r['id']]])
    lines.append('Analysed %d parameter(s): %d hold values somewhere, %d hold none.'
                 % (len(wanted), used, len(wanted) - used))
    for row in wanted:
        lines.append('  %s: %s element(s) with a value'
                     % (row['name'], usage_text(counts[row['id']])))
    note(0, 0)
    return lines, dict((k, (counts[k], where[k])) for k in counts)


def usage_text(count):
    return '%d+' % USAGE_CAP if count >= USAGE_CAP else str(count)


# ---------------------------------------------------------------------------
#  REVIT DIALOG HAND-OFF
# ---------------------------------------------------------------------------
def select_in_revit_dialog(dialog_names, item_name, timeout=10.0):
    """Best effort: wait for a Revit dialog to appear, then select a named row.

    Runs on a background MTA thread because the Revit UI thread is blocked by
    its own modal dialog while this is happening. Everything is wrapped - if
    UI Automation is unavailable or the dialog is laid out differently, the
    caller simply loses the auto-selection, not the command.
    """
    try:
        clr.AddReference('UIAutomationClient')
        clr.AddReference('UIAutomationTypes')
        from System.Windows.Automation import (AutomationElement, TreeScope,
                                               PropertyCondition, SelectionItemPattern,
                                               ScrollItemPattern, ExpandCollapsePattern)
    except Exception:
        return False

    def worker():
        try:
            deadline = System.DateTime.Now.AddSeconds(timeout)
            root = AutomationElement.RootElement
            dialog = None
            while dialog is None and System.DateTime.Now < deadline:
                for name in dialog_names:
                    try:
                        cond = PropertyCondition(AutomationElement.NameProperty, name)
                        dialog = root.FindFirst(TreeScope.Children, cond)
                    except Exception:
                        dialog = None
                    if dialog is not None:
                        break
                if dialog is None:
                    Thread.Sleep(200)
            if dialog is None:
                return

            target = None
            while target is None and System.DateTime.Now < deadline:
                try:
                    cond = PropertyCondition(AutomationElement.NameProperty, item_name)
                    target = dialog.FindFirst(TreeScope.Descendants, cond)
                except Exception:
                    target = None
                if target is None:
                    Thread.Sleep(200)
            if target is None:
                return

            # Expand any collapsed parent group first (the Filters dialog groups
            # rule-based and selection filters under expandable headings).
            try:
                walker = target
                for _ in range(3):
                    parent = System.Windows.Automation.TreeWalker.ControlViewWalker\
                        .GetParent(walker)
                    if parent is None:
                        break
                    try:
                        pattern = parent.GetCurrentPattern(ExpandCollapsePattern.Pattern)
                        pattern.Expand()
                    except Exception:
                        pass
                    walker = parent
            except Exception:
                pass

            for pattern_type, method in ((ScrollItemPattern.Pattern, 'ScrollIntoView'),
                                         (SelectionItemPattern.Pattern, 'Select')):
                try:
                    pattern = target.GetCurrentPattern(pattern_type)
                    getattr(pattern, method)()
                except Exception:
                    pass
            try:
                target.SetFocus()
            except Exception:
                pass
        except Exception:
            pass

    if Thread is None:
        return False
    thread = Thread(ThreadStart(worker))
    thread.IsBackground = True
    try:
        thread.SetApartmentState(ApartmentState.MTA)
    except Exception:
        pass
    thread.Start()
    return True


# ---------------------------------------------------------------------------
#  EXTERNAL EVENT HANDLER
# ---------------------------------------------------------------------------
class RevoBimHandler(IExternalEventHandler):
    def __init__(self):
        self.queue = []
        self.owner = None

    def enqueue(self, fn):
        self.queue.append(fn)

    def Execute(self, uiapp):
        while self.queue:
            fn = self.queue.pop(0)
            try:
                fn(uiapp)
            except Exception as ex:
                if self.owner is not None:
                    try:
                        self.owner.post('ERROR: %s' % ex)
                        self.owner.post(traceback.format_exc())
                        self.owner.post_busy(False)
                    except Exception:
                        pass

    def GetName(self):
        return '%s - %s' % (BRAND, TOOL_NAME)


try:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
except Exception:
    SCRIPT_DIR = ''


def load_icon(file_name):
    """Load a tab icon from bytes.

    Deliberately not through BitmapImage.UriSource: System.Uri moved assemblies in
    Revit 2025 and importing it throws at module load on 2025+. Reading the file
    into a MemoryStream avoids the type entirely and also releases the file handle,
    so the icons are not locked while Revit is open.
    """
    if BitmapImage is None or MemoryStream is None or not file_name:
        return None
    try:
        path = os.path.join(SCRIPT_DIR, 'icons', file_name)
        if not os.path.isfile(path):
            return None
        stream = MemoryStream(IOFile.ReadAllBytes(path))
        bmp = BitmapImage()
        bmp.BeginInit()
        bmp.StreamSource = stream
        if BitmapCacheOption is not None:
            bmp.CacheOption = BitmapCacheOption.OnLoad
        bmp.EndInit()
        try:
            bmp.Freeze()
        except Exception:
            pass
        return bmp
    except Exception:
        return None


# ---------------------------------------------------------------------------
#  XAML
# ---------------------------------------------------------------------------
SHARED_STYLES = u"""
    <Style x:Key="RevoBtn" TargetType="Button">
      <Setter Property="Background" Value="#2F343C"/>
      <Setter Property="Foreground" Value="#DCDCDC"/>
      <Setter Property="BorderBrush" Value="#4F4F4F"/>
      <Setter Property="BorderThickness" Value="1"/>
      <Setter Property="Padding" Value="12,6"/>
      <Setter Property="Margin" Value="0,0,6,0"/>
      <Setter Property="MinWidth" Value="84"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="SnapsToDevicePixels" Value="True"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="bd" Background="{TemplateBinding Background}"
                    BorderBrush="{TemplateBinding BorderBrush}"
                    BorderThickness="{TemplateBinding BorderThickness}" CornerRadius="2">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"
                                Margin="{TemplateBinding Padding}"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="bd" Property="Background" Value="#3A414B"/>
                <Setter TargetName="bd" Property="BorderBrush" Value="#3D9BE9"/>
              </Trigger>
              <Trigger Property="IsPressed" Value="True">
                <Setter TargetName="bd" Property="Background" Value="#1E5A8A"/>
              </Trigger>
              <Trigger Property="IsEnabled" Value="False">
                <Setter Property="Foreground" Value="#7A7F87"/>
                <Setter TargetName="bd" Property="Background" Value="#292D34"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="AccentBtn" TargetType="Button" BasedOn="{StaticResource RevoBtn}">
      <Setter Property="Background" Value="#1E5A8A"/>
      <Setter Property="BorderBrush" Value="#3D9BE9"/>
      <Setter Property="Foreground" Value="#FFFFFF"/>
    </Style>

    <Style x:Key="IconBtn" TargetType="Button">
      <Setter Property="Background" Value="#2F343C"/>
      <Setter Property="BorderBrush" Value="#4F4F4F"/>
      <Setter Property="BorderThickness" Value="1"/>
      <Setter Property="Width" Value="38"/>
      <Setter Property="Height" Value="34"/>
      <Setter Property="Margin" Value="0,0,6,0"/>
      <Setter Property="Padding" Value="0"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="bd" Background="{TemplateBinding Background}"
                    BorderBrush="{TemplateBinding BorderBrush}"
                    BorderThickness="{TemplateBinding BorderThickness}" CornerRadius="2">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="bd" Property="Background" Value="#3A414B"/>
                <Setter TargetName="bd" Property="BorderBrush" Value="#3D9BE9"/>
              </Trigger>
              <Trigger Property="IsEnabled" Value="False">
                <Setter TargetName="bd" Property="Background" Value="#292D34"/>
                <Setter Property="Opacity" Value="0.45"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="DangerBtn" TargetType="Button" BasedOn="{StaticResource RevoBtn}">
      <Setter Property="Background" Value="#5C2A24"/>
      <Setter Property="BorderBrush" Value="#C0392B"/>
      <Setter Property="Foreground" Value="#F1B0A8"/>
    </Style>

    <Style x:Key="RevoBox" TargetType="TextBox">
      <Setter Property="Background" Value="#21252B"/>
      <Setter Property="Foreground" Value="#DCDCDC"/>
      <Setter Property="BorderBrush" Value="#4F4F4F"/>
      <Setter Property="BorderThickness" Value="1"/>
      <Setter Property="Padding" Value="6,4"/>
      <Setter Property="CaretBrush" Value="#DCDCDC"/>
      <Setter Property="SelectionBrush" Value="#3D9BE9"/>
    </Style>

    <Style x:Key="CellEdit" TargetType="TextBox">
      <Setter Property="Background" Value="#12161A"/>
      <Setter Property="Foreground" Value="#FFFFFF"/>
      <Setter Property="BorderBrush" Value="#3D9BE9"/>
      <Setter Property="BorderThickness" Value="1"/>
      <Setter Property="Padding" Value="4,1"/>
      <Setter Property="CaretBrush" Value="#FFFFFF"/>
      <Setter Property="SelectionBrush" Value="#3D9BE9"/>
      <Setter Property="VerticalContentAlignment" Value="Center"/>
    </Style>

    <Style TargetType="CheckBox">
      <Setter Property="Foreground" Value="#DCDCDC"/>
      <Setter Property="VerticalAlignment" Value="Center"/>
      <Setter Property="Margin" Value="10,0,4,0"/>
    </Style>

    <Style TargetType="ContextMenu">
      <Setter Property="Background" Value="#2F343C"/>
      <Setter Property="Foreground" Value="#DCDCDC"/>
      <Setter Property="BorderBrush" Value="#4F4F4F"/>
      <Setter Property="BorderThickness" Value="1"/>
    </Style>

    <Style TargetType="MenuItem">
      <Setter Property="Background" Value="#2F343C"/>
      <Setter Property="Foreground" Value="#DCDCDC"/>
      <Setter Property="Padding" Value="8,5"/>
      <Style.Triggers>
        <Trigger Property="IsHighlighted" Value="True">
          <Setter Property="Background" Value="#1E5A8A"/>
          <Setter Property="Foreground" Value="#FFFFFF"/>
        </Trigger>
        <Trigger Property="IsEnabled" Value="False">
          <Setter Property="Foreground" Value="#7A7F87"/>
        </Trigger>
      </Style.Triggers>
    </Style>

    <Style TargetType="Separator">
      <Setter Property="Background" Value="#4F4F4F"/>
      <Setter Property="Margin" Value="4,3"/>
    </Style>

    <Style x:Key="ScrollThumb" TargetType="Thumb">
      <Setter Property="IsTabStop" Value="False"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Thumb">
            <Border x:Name="tb" Background="#4A515B" CornerRadius="4" Margin="2"/>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="tb" Property="Background" Value="#5D6672"/>
              </Trigger>
              <Trigger Property="IsDragging" Value="True">
                <Setter TargetName="tb" Property="Background" Value="#3D9BE9"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="ScrollArrow" TargetType="RepeatButton">
      <Setter Property="IsTabStop" Value="False"/>
      <Setter Property="Focusable" Value="False"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="RepeatButton">
            <Border Background="Transparent"/>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style TargetType="ScrollBar">
      <Setter Property="Background" Value="#1C1F24"/>
      <Setter Property="Width" Value="12"/>
      <Setter Property="MinWidth" Value="12"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ScrollBar">
            <Grid Background="#1C1F24">
              <Track x:Name="PART_Track" IsDirectionReversed="True">
                <Track.DecreaseRepeatButton>
                  <RepeatButton Command="ScrollBar.PageUpCommand"
                                Style="{StaticResource ScrollArrow}"/>
                </Track.DecreaseRepeatButton>
                <Track.Thumb>
                  <Thumb Style="{StaticResource ScrollThumb}"/>
                </Track.Thumb>
                <Track.IncreaseRepeatButton>
                  <RepeatButton Command="ScrollBar.PageDownCommand"
                                Style="{StaticResource ScrollArrow}"/>
                </Track.IncreaseRepeatButton>
              </Track>
            </Grid>
            <ControlTemplate.Triggers>
              <Trigger Property="Orientation" Value="Horizontal">
                <Setter Property="Height" Value="12"/>
                <Setter Property="MinHeight" Value="12"/>
                <Setter Property="Width" Value="Auto"/>
                <Setter TargetName="PART_Track" Property="IsDirectionReversed" Value="False"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="ComboToggle" TargetType="ToggleButton">
      <Setter Property="Focusable" Value="False"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ToggleButton">
            <Border x:Name="bd" Background="#21252B" BorderBrush="#4F4F4F"
                    BorderThickness="1" CornerRadius="2">
              <Path x:Name="ar" HorizontalAlignment="Right" VerticalAlignment="Center"
                    Margin="0,0,8,0" Fill="#B6BCC4"
                    Data="M 0 0 L 8 0 L 4 5 Z"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="bd" Property="BorderBrush" Value="#3D9BE9"/>
              </Trigger>
              <Trigger Property="IsChecked" Value="True">
                <Setter TargetName="bd" Property="BorderBrush" Value="#3D9BE9"/>
                <Setter TargetName="ar" Property="Fill" Value="#3D9BE9"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style TargetType="ComboBoxItem">
      <Setter Property="Background" Value="#2F343C"/>
      <Setter Property="Foreground" Value="#DCDCDC"/>
      <Setter Property="Padding" Value="8,5"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ComboBoxItem">
            <Border x:Name="bd" Background="{TemplateBinding Background}"
                    Padding="{TemplateBinding Padding}">
              <ContentPresenter/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsHighlighted" Value="True">
                <Setter TargetName="bd" Property="Background" Value="#1E5A8A"/>
                <Setter Property="Foreground" Value="#FFFFFF"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style TargetType="ComboBox">
      <Setter Property="Foreground" Value="#DCDCDC"/>
      <Setter Property="Background" Value="#21252B"/>
      <Setter Property="BorderBrush" Value="#4F4F4F"/>
      <Setter Property="Height" Value="26"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ComboBox">
            <Grid>
              <ToggleButton x:Name="PART_Toggle" Style="{StaticResource ComboToggle}"
                            Focusable="False" ClickMode="Press"
                            IsChecked="{Binding IsDropDownOpen, Mode=TwoWay,
                                        RelativeSource={RelativeSource TemplatedParent}}"/>
              <ContentPresenter x:Name="PART_Content" IsHitTestVisible="False"
                                Margin="8,0,24,0" VerticalAlignment="Center"
                                Content="{TemplateBinding SelectionBoxItem}"
                                ContentTemplate="{TemplateBinding SelectionBoxItemTemplate}"/>
              <TextBox x:Name="PART_EditableTextBox" Visibility="Hidden"
                       Background="#21252B" Foreground="#DCDCDC" BorderThickness="0"
                       Margin="7,0,24,0" VerticalContentAlignment="Center"
                       IsReadOnly="{TemplateBinding IsReadOnly}"/>
              <Popup x:Name="PART_Popup" AllowsTransparency="True" Focusable="False"
                     IsOpen="{TemplateBinding IsDropDownOpen}" Placement="Bottom"
                     PopupAnimation="Fade">
                <Border Background="#2F343C" BorderBrush="#4F4F4F" BorderThickness="1"
                        MinWidth="{TemplateBinding ActualWidth}" MaxHeight="280"
                        CornerRadius="2">
                  <ScrollViewer>
                    <StackPanel IsItemsHost="True" KeyboardNavigation.DirectionalNavigation="Contained"/>
                  </ScrollViewer>
                </Border>
              </Popup>
            </Grid>
            <ControlTemplate.Triggers>
              <Trigger Property="IsEditable" Value="True">
                <Setter TargetName="PART_EditableTextBox" Property="Visibility"
                        Value="Visible"/>
                <Setter TargetName="PART_Content" Property="Visibility" Value="Hidden"/>
              </Trigger>
              <Trigger Property="IsEnabled" Value="False">
                <Setter Property="Foreground" Value="#7A7F87"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style TargetType="ProgressBar">
      <Setter Property="Background" Value="#1C1F24"/>
      <Setter Property="BorderBrush" Value="#4F4F4F"/>
      <Setter Property="BorderThickness" Value="1"/>
      <Setter Property="Height" Value="14"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ProgressBar">
            <Border Background="{TemplateBinding Background}"
                    BorderBrush="{TemplateBinding BorderBrush}"
                    BorderThickness="{TemplateBinding BorderThickness}" CornerRadius="3">
              <Grid>
                <Rectangle x:Name="PART_Track" Fill="Transparent"/>
                <Rectangle x:Name="PART_Indicator" Fill="#3D9BE9" HorizontalAlignment="Left"
                           RadiusX="2" RadiusY="2" Margin="1"/>
              </Grid>
            </Border>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style TargetType="ScrollViewer">
      <Setter Property="Background" Value="Transparent"/>
    </Style>

    <Style TargetType="Slider">
      <Setter Property="Foreground" Value="#3D9BE9"/>
      <Setter Property="Background" Value="#1C1F24"/>
      <Setter Property="BorderBrush" Value="#4F4F4F"/>
    </Style>

    <Style TargetType="DataGridColumnHeader">
      <Setter Property="Background" Value="#2F343C"/>
      <Setter Property="Foreground" Value="#DCDCDC"/>
      <Setter Property="BorderBrush" Value="#4F4F4F"/>
      <Setter Property="BorderThickness" Value="0,0,1,1"/>
      <Setter Property="Padding" Value="8,7"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
      <Setter Property="HorizontalContentAlignment" Value="Left"/>
    </Style>

    <Style TargetType="DataGridRow">
      <Setter Property="Background" Value="{Binding RowBrush}"/>
      <Setter Property="Foreground" Value="#DCDCDC"/>
      <Setter Property="Height" Value="26"/>
      <Style.Triggers>
        <Trigger Property="IsSelected" Value="True">
          <Setter Property="Background" Value="#1E5A8A"/>
          <Setter Property="Foreground" Value="#FFFFFF"/>
        </Trigger>
        <Trigger Property="IsMouseOver" Value="True">
          <Setter Property="Foreground" Value="#FFFFFF"/>
        </Trigger>
      </Style.Triggers>
    </Style>

    <Style TargetType="DataGridCell">
      <Setter Property="Background" Value="Transparent"/>
      <Setter Property="BorderThickness" Value="0"/>
      <Setter Property="Padding" Value="6,2"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="DataGridCell">
            <Border Background="{TemplateBinding Background}" Padding="{TemplateBinding Padding}">
              <ContentPresenter VerticalAlignment="Center"/>
            </Border>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="NavBtn" TargetType="RadioButton">
      <Setter Property="Foreground" Value="#B6BCC4"/>
      <Setter Property="Margin" Value="0,0,2,3"/>
      <Setter Property="Padding" Value="0"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="SnapsToDevicePixels" Value="True"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="RadioButton">
            <Border x:Name="bd" Background="Transparent" BorderBrush="Transparent"
                    BorderThickness="1" CornerRadius="3" Padding="7,5">
              <ContentPresenter VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="bd" Property="Background" Value="#333944"/>
                <Setter Property="Foreground" Value="#FFFFFF"/>
              </Trigger>
              <Trigger Property="IsChecked" Value="True">
                <Setter TargetName="bd" Property="Background" Value="#2F343C"/>
                <Setter TargetName="bd" Property="BorderBrush" Value="#3D9BE9"/>
                <Setter Property="Foreground" Value="#FFFFFF"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style TargetType="TabItem">
      <Setter Property="Foreground" Value="#9AA1AA"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="TabItem">
            <Border x:Name="bd" Background="#262A31" BorderBrush="#4F4F4F"
                    BorderThickness="1,1,1,0" Margin="0,0,3,0" Padding="16,8"
                    CornerRadius="3,3,0,0">
              <ContentPresenter ContentSource="Header" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsSelected" Value="True">
                <Setter TargetName="bd" Property="Background" Value="#2F343C"/>
                <Setter TargetName="bd" Property="BorderBrush" Value="#3D9BE9"/>
                <Setter Property="Foreground" Value="#FFFFFF"/>
              </Trigger>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="bd" Property="Background" Value="#333944"/>
                <Setter Property="Foreground" Value="#FFFFFF"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
"""

MAIN_XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="RevoBIM PY - Style Manager"
        Height="820" Width="1320" MinHeight="600" MinWidth="1000"
        WindowStartupLocation="CenterScreen" WindowStyle="None"
        ResizeMode="CanResize" Background="#262A31"
        TextOptions.TextFormattingMode="Display"
        FontFamily="Segoe UI" FontSize="12">
  <Window.Resources>
__STYLES__
    <Style x:Key="ChromeBtn" TargetType="Button">
      <Setter Property="Background" Value="Transparent"/>
      <Setter Property="Foreground" Value="#DCDCDC"/>
      <Setter Property="BorderThickness" Value="0"/>
      <Setter Property="Width" Value="34"/>
      <Setter Property="Height" Value="28"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="bd" Background="{TemplateBinding Background}">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="bd" Property="Background" Value="#3A414B"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
    <Style x:Key="CloseBtn" TargetType="Button" BasedOn="{StaticResource ChromeBtn}">
      <Style.Triggers>
        <Trigger Property="IsMouseOver" Value="True">
          <Setter Property="Background" Value="#C0392B"/>
          <Setter Property="Foreground" Value="#FFFFFF"/>
        </Trigger>
      </Style.Triggers>
    </Style>
    <Style x:Key="ApplyBtn" TargetType="Button">
      <Setter Property="Background" Value="#C0392B"/>
      <Setter Property="Foreground" Value="#FFFFFF"/>
      <Setter Property="BorderBrush" Value="#E74C3C"/>
      <Setter Property="BorderThickness" Value="1"/>
      <Setter Property="FontWeight" Value="Bold"/>
      <Setter Property="Margin" Value="8,0,0,0"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="bd" Background="{TemplateBinding Background}"
                    BorderBrush="{TemplateBinding BorderBrush}"
                    BorderThickness="{TemplateBinding BorderThickness}" CornerRadius="3">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"
                                Margin="16,0"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="bd" Property="Background" Value="#E04B39"/>
              </Trigger>
              <Trigger Property="IsPressed" Value="True">
                <Setter TargetName="bd" Property="Background" Value="#8E2B20"/>
              </Trigger>
              <Trigger Property="IsEnabled" Value="False">
                <Setter TargetName="bd" Property="Background" Value="#3A2E2C"/>
                <Setter TargetName="bd" Property="BorderBrush" Value="#4F4F4F"/>
                <Setter Property="Foreground" Value="#8A7A78"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
  </Window.Resources>

  <Border BorderBrush="#4F4F4F" BorderThickness="1">
    <Grid>
      <Grid.RowDefinitions>
        <RowDefinition Height="40"/>
        <RowDefinition Height="*"/>
        <RowDefinition Height="Auto"/>
        <RowDefinition Height="120"/>
        <RowDefinition Height="Auto"/>
        <RowDefinition Height="26"/>
      </Grid.RowDefinitions>

      <Border x:Name="HeaderBar" Grid.Row="0" Background="#2B2B2B">
        <Grid>
          <StackPanel Orientation="Horizontal" VerticalAlignment="Center" Margin="14,0,0,0">
            <TextBlock Text="RevoBIM" Foreground="#3D9BE9" FontSize="15" FontWeight="Bold"/>
            <TextBlock Text=" PY" Foreground="#F07C10" FontSize="15" FontWeight="Bold"/>
            <TextBlock Text="  |  " Foreground="#5A6068" FontSize="15"/>
            <TextBlock Text="Style Manager" Foreground="#DCDCDC" FontSize="15"/>
          </StackPanel>
          <StackPanel Orientation="Horizontal" HorizontalAlignment="Right"
                      VerticalAlignment="Center">
            <TextBlock x:Name="VersionText" Text="v0.0.0" Foreground="#8A9099"
                       VerticalAlignment="Center" Margin="0,0,12,0" FontSize="11"/>
            <Button x:Name="BtnMin" Style="{StaticResource ChromeBtn}" Content="&#8211;"/>
            <Button x:Name="BtnMax" Style="{StaticResource ChromeBtn}" Content="&#9633;"/>
            <Button x:Name="BtnClose" Style="{StaticResource CloseBtn}" Content="&#10005;"/>
          </StackPanel>
        </Grid>
      </Border>

      <Grid Grid.Row="1" Margin="10,8,10,0">
        <Grid.RowDefinitions>
          <RowDefinition Height="Auto"/>
          <RowDefinition Height="*"/>
        </Grid.RowDefinitions>
        <Border Grid.Row="0" Background="#23262C" BorderBrush="#4F4F4F"
                BorderThickness="1" CornerRadius="3,3,0,0" Padding="6,5">
          <WrapPanel x:Name="NavBar" Orientation="Horizontal"/>
        </Border>
        <Border Grid.Row="1" Background="#2F343C" BorderBrush="#4F4F4F"
                BorderThickness="1,0,1,1">
          <ContentControl x:Name="TabHost"/>
        </Border>
      </Grid>

      <Border x:Name="ProgressPanel" Grid.Row="2" Margin="12,8,12,0"
              Visibility="Collapsed">
        <Grid>
          <Grid.ColumnDefinitions>
            <ColumnDefinition Width="*"/>
            <ColumnDefinition Width="Auto"/>
          </Grid.ColumnDefinitions>
          <StackPanel Grid.Column="0">
            <TextBlock x:Name="ProgressText" Text="" Foreground="#B6BCC4" FontSize="11"
                       Margin="0,0,0,4" TextTrimming="CharacterEllipsis"/>
            <ProgressBar x:Name="ProgressBarCtl" Minimum="0" Maximum="100" Value="0"/>
          </StackPanel>
          <TextBlock x:Name="ProgressPercent" Grid.Column="1" Text="0%"
                     Foreground="#3D9BE9" FontWeight="Bold" FontSize="16"
                     VerticalAlignment="Bottom" Margin="12,0,2,0"/>
        </Grid>
      </Border>

      <Border Grid.Row="3" Margin="12,10,12,8" BorderBrush="#4F4F4F" BorderThickness="1">
        <TextBox x:Name="StatusBox" Background="#1C1F24" Foreground="#B6BCC4"
                 BorderThickness="0" IsReadOnly="True" TextWrapping="NoWrap"
                 VerticalScrollBarVisibility="Auto" HorizontalScrollBarVisibility="Auto"
                 FontFamily="Consolas" FontSize="11" Padding="8,6"/>
      </Border>

      <Border Grid.Row="4" Background="#23262C" BorderBrush="#4F4F4F"
              BorderThickness="0,1,0,0" Padding="12,10">
        <Grid>
          <StackPanel VerticalAlignment="Center">
            <TextBlock x:Name="PendingText" Text="No pending changes"
                       Foreground="#8A9099" FontSize="12"/>
            <TextBlock x:Name="PendingHint"
                       Text="Edits on every tab are held in the table until you apply them."
                       Foreground="#6E747C" FontSize="11" Margin="0,2,0,0"/>
          </StackPanel>
          <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
            <Button x:Name="BtnDiscard" Style="{StaticResource RevoBtn}"
                    Content="Discard Changes" Height="44" MinWidth="150" FontSize="13"
                    VerticalAlignment="Center"/>
            <Button x:Name="BtnApply" Style="{StaticResource ApplyBtn}"
                    Content="APPLY CHANGES" Height="44" MinWidth="240" FontSize="15"
                    VerticalAlignment="Center"/>
          </StackPanel>
        </Grid>
      </Border>

      <Border Grid.Row="5" Background="#2B2B2B">
        <Grid>
          <TextBlock x:Name="FooterLeft" Text="" Foreground="#8A9099" Margin="12,0,0,0"
                     VerticalAlignment="Center" FontSize="11"/>
          <TextBlock x:Name="FooterRight" Text="" Foreground="#8A9099" Margin="0,0,12,0"
                     HorizontalAlignment="Right" VerticalAlignment="Center" FontSize="11"/>
        </Grid>
      </Border>
    </Grid>
  </Border>
</Window>
""".replace('__STYLES__', SHARED_STYLES)

PANEL_XAML = u"""
<Grid xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
      xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml" Background="#2F343C">
  <Grid.RowDefinitions>
    <RowDefinition Height="Auto"/>
    <RowDefinition Height="Auto"/>
    <RowDefinition Height="Auto"/>
    <RowDefinition Height="*"/>
    <RowDefinition Height="Auto"/>
  </Grid.RowDefinitions>

  <Border Grid.Row="0" Padding="12,10,12,6">
    <StackPanel Orientation="Horizontal">
      <Button x:Name="BtnRefresh" Style="{DynamicResource RevoBtn}" Content="Refresh"/>
      <Button x:Name="BtnAnalyze" Style="{DynamicResource RevoBtn}" Content="Analyze"
              ToolTip="Count what actually uses the selected styles"/>
      <Button x:Name="BtnDupes" Style="{DynamicResource RevoBtn}" Content="Find Duplicates"/>
      <Button x:Name="BtnDupRules" Style="{DynamicResource RevoBtn}"
              ToolTip="Choose which settings must match for two styles to count as duplicates">
        <StackPanel Orientation="Horizontal">
          <TextBlock Text="Duplicate Rules" VerticalAlignment="Center"/>
          <Path Data="M 0 0 L 8 0 L 4 5 Z" Fill="#B6BCC4" Margin="8,1,0,0"
                VerticalAlignment="Center"/>
        </StackPanel>
      </Button>
      <Button x:Name="BtnMerge" Style="{DynamicResource AccentBtn}" Content="Merge Selected..."/>
      <Button x:Name="BtnDelete" Style="{DynamicResource DangerBtn}" Content="Delete Selected..."/>
      <Border Width="1" Background="#4F4F4F" Margin="6,2,12,2"/>
      <Button x:Name="BtnExcel" Style="{DynamicResource IconBtn}"
              ToolTip="Excel - export this table, or import an edited workbook">
        <Grid Width="30" Height="30">
          <!-- Excel sheet glyph, drawn rather than set in a symbol font -->
          <Border Background="#2E7D4F" CornerRadius="2" Margin="3,2,3,2"/>
          <Border Background="#FFFFFF" Opacity="0.92" CornerRadius="1"
                  Margin="6,7,6,6"/>
          <Grid Margin="6,7,6,6">
            <Grid.RowDefinitions>
              <RowDefinition Height="*"/>
              <RowDefinition Height="*"/>
              <RowDefinition Height="*"/>
            </Grid.RowDefinitions>
            <Grid.ColumnDefinitions>
              <ColumnDefinition Width="*"/>
              <ColumnDefinition Width="*"/>
            </Grid.ColumnDefinitions>
            <Border Grid.Row="0" Grid.ColumnSpan="2" Background="#2E7D4F"/>
            <Border Grid.Row="1" Grid.Column="0" Background="#BFD9C8" Margin="0,1,1,0"/>
            <Border Grid.Row="1" Grid.Column="1" Background="#BFD9C8" Margin="1,1,0,0"/>
            <Border Grid.Row="2" Grid.Column="0" Background="#BFD9C8" Margin="0,1,1,0"/>
            <Border Grid.Row="2" Grid.Column="1" Background="#BFD9C8" Margin="1,1,0,0"/>
          </Grid>
        </Grid>
      </Button>
      <Border Width="1" Background="#4F4F4F" Margin="6,2,12,2"/>
      <Button x:Name="BtnCollapse" Style="{DynamicResource RevoBtn}" Content="Collapse All"
              Visibility="Collapsed"/>
      <Button x:Name="BtnExpand" Style="{DynamicResource RevoBtn}" Content="Expand All"
              Visibility="Collapsed"/>
      <Button x:Name="BtnUnused" Style="{DynamicResource RevoBtn}" Content="Select Unused"/>
      <Button x:Name="BtnRevit" Style="{DynamicResource RevoBtn}" Content="Edit in Revit..."/>
    </StackPanel>
  </Border>

  <Border Grid.Row="1" Padding="12,0,12,10">
    <StackPanel Orientation="Horizontal">
      <TextBlock Text="Search" Foreground="#8A9099" VerticalAlignment="Center"
                 Margin="0,0,8,0"/>
      <TextBox x:Name="SearchBox" Style="{DynamicResource RevoBox}" Width="240"
               VerticalContentAlignment="Center"/>
      <CheckBox x:Name="ChkDupOnly" Content="Duplicates only"/>
      <CheckBox x:Name="ChkUnusedOnly" Content="Unused only"/>
      <CheckBox x:Name="ChkChangedOnly" Content="Changed only"/>
      <TextBlock x:Name="GroupFilterLabel" Text="Category" Foreground="#8A9099"
                 VerticalAlignment="Center" Margin="16,0,8,0" Visibility="Collapsed"/>
      <ComboBox x:Name="GroupFilter" Width="220" Visibility="Collapsed"/>
      <TextBlock x:Name="CountText" Foreground="#6E747C" VerticalAlignment="Center"
                 Margin="16,0,0,0" FontSize="11"/>
    </StackPanel>
  </Border>

  <Border Grid.Row="2" Background="#2B2F36" Margin="12,0,12,8"
          BorderBrush="#4F4F4F" BorderThickness="1" Padding="12,9">
    <StackPanel Orientation="Horizontal">
      <TextBlock Text="Rename selected" Foreground="#F07C10" FontWeight="SemiBold"
                 VerticalAlignment="Center" Margin="0,0,14,0"/>
      <TextBlock Text="Find" Foreground="#8A9099" VerticalAlignment="Center" Margin="0,0,8,0"/>
      <TextBox x:Name="FindBox" Style="{DynamicResource RevoBox}" Width="210"
               VerticalContentAlignment="Center"/>
      <TextBlock Text="Replace with" Foreground="#8A9099" VerticalAlignment="Center"
                 Margin="14,0,8,0"/>
      <TextBox x:Name="ReplaceBox" Style="{DynamicResource RevoBox}" Width="210"
               VerticalContentAlignment="Center"/>
      <Button x:Name="BtnRenameApply" Style="{DynamicResource AccentBtn}" Content="Apply"
              Margin="14,0,0,0"/>
      <TextBlock Foreground="#6E747C" VerticalAlignment="Center" Margin="14,0,0,0"
                 FontSize="11" Text="Staged only - nothing is written until APPLY CHANGES."/>
    </StackPanel>
  </Border>

  <Border Grid.Row="3" Margin="12,0,12,0" BorderBrush="#4F4F4F" BorderThickness="1">
    <DataGrid x:Name="Grid" Background="#21252B" BorderThickness="0"
              AutoGenerateColumns="False" CanUserAddRows="False" CanUserDeleteRows="False"
              IsReadOnly="False" SelectionMode="Extended" SelectionUnit="FullRow"
              HeadersVisibility="Column" GridLinesVisibility="Horizontal"
              HorizontalGridLinesBrush="#343A42" VerticalGridLinesBrush="#343A42"
              RowHeaderWidth="0" EnableRowVirtualization="True"
              ColumnWidth="SizeToHeader" AlternationCount="0"/>
  </Border>

  <Border x:Name="LegendBar" Grid.Row="4" Margin="12,8,12,10">
    <StackPanel>
      <Grid>
        <TextBlock x:Name="LegendTitle" VerticalAlignment="Center"
                   Text="Duplicate groups - click swatches to pick groups, then Merge Groups"
                   Foreground="#8A9099" Margin="0,0,4,0"/>
        <StackPanel x:Name="GroupMergeBar" Orientation="Horizontal"
                    HorizontalAlignment="Right">
          <Button x:Name="BtnAllGroups" Style="{DynamicResource RevoBtn}"
                  Content="Pick All" MinWidth="70" Padding="10,3"/>
          <Button x:Name="BtnNoGroups" Style="{DynamicResource RevoBtn}"
                  Content="Clear" MinWidth="60" Padding="10,3"/>
          <Button x:Name="BtnMergeGroups" Style="{DynamicResource RevoBtn}"
                  Content="Merge Groups" MinWidth="150" Padding="12,3"
                  FontWeight="SemiBold" IsEnabled="False"
                  ToolTip="Merge every picked group into its most-used style"/>
        </StackPanel>
      </Grid>
      <ScrollViewer MaxHeight="54" VerticalScrollBarVisibility="Auto"
                    HorizontalScrollBarVisibility="Disabled">
        <WrapPanel x:Name="LegendPanel" Margin="0,4,0,0"/>
      </ScrollViewer>
    </StackPanel>
  </Border>
</Grid>
"""

CHIP_TEMPLATE = u"""
<DataTemplate xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation">
  <StackPanel Orientation="Horizontal" Margin="4,0,0,0">
    <Rectangle Width="11" Height="11" RadiusX="2" RadiusY="2" Fill="{Binding ChipBrush}"
               VerticalAlignment="Center"/>
    <TextBlock Text="{Binding Group}" Margin="6,0,0,0" VerticalAlignment="Center"
               FontWeight="Bold"/>
  </StackPanel>
</DataTemplate>
"""

PROMPT_XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="RevoBIM PY" SizeToContent="Height" Width="580"
        WindowStartupLocation="CenterOwner" WindowStyle="None" ResizeMode="NoResize"
        Background="#262A31" FontFamily="Segoe UI" FontSize="12"
        TextOptions.TextFormattingMode="Display">
  <Window.Resources>
__STYLES__
  </Window.Resources>
  <Border BorderBrush="#4F4F4F" BorderThickness="1">
    <Grid>
      <Grid.RowDefinitions>
        <RowDefinition Height="36"/>
        <RowDefinition Height="Auto"/>
        <RowDefinition Height="Auto"/>
      </Grid.RowDefinitions>
      <Border x:Name="HeaderBar" Grid.Row="0" Background="#2B2B2B">
        <Grid>
          <StackPanel Orientation="Horizontal" VerticalAlignment="Center" Margin="14,0,0,0">
            <TextBlock Text="RevoBIM" Foreground="#3D9BE9" FontSize="14" FontWeight="Bold"/>
            <TextBlock Text=" PY" Foreground="#F07C10" FontSize="14" FontWeight="Bold"/>
            <TextBlock x:Name="HeadText" Text="  |  " Foreground="#DCDCDC" FontSize="14"/>
          </StackPanel>
          <TextBlock x:Name="VersionText" Text="v0.0.0" Foreground="#8A9099"
                     HorizontalAlignment="Right" VerticalAlignment="Center"
                     Margin="0,0,14,0" FontSize="11"/>
        </Grid>
      </Border>
      <StackPanel Grid.Row="1" Margin="18,16,18,12">
        <TextBlock x:Name="BodyText" Text="" Foreground="#DCDCDC" TextWrapping="Wrap"/>
        <TextBlock x:Name="PathText" Text="" Foreground="#8A9099" TextWrapping="Wrap"
                   Margin="0,10,0,0" FontFamily="Consolas" FontSize="11"/>
      </StackPanel>
      <Border Grid.Row="2" Background="#2B2B2B" Padding="12,10">
        <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
          <Button x:Name="BtnClose" Style="{StaticResource RevoBtn}" Content="Close"/>
          <Button x:Name="BtnOpen" Style="{StaticResource AccentBtn}" Content="OK"/>
        </StackPanel>
      </Border>
    </Grid>
  </Border>
</Window>
""".replace('__STYLES__', SHARED_STYLES)

CONFIRM_XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Confirm delete" Height="520" Width="640" MinHeight="380" MinWidth="520"
        WindowStartupLocation="CenterOwner" WindowStyle="None" ResizeMode="CanResize"
        Background="#262A31" FontFamily="Segoe UI" FontSize="12"
        TextOptions.TextFormattingMode="Display">
  <Window.Resources>
__STYLES__
    <Style x:Key="DeleteBtn" TargetType="Button">
      <Setter Property="Background" Value="#C0392B"/>
      <Setter Property="Foreground" Value="#FFFFFF"/>
      <Setter Property="BorderBrush" Value="#E74C3C"/>
      <Setter Property="BorderThickness" Value="1"/>
      <Setter Property="FontWeight" Value="Bold"/>
      <Setter Property="Margin" Value="8,0,0,0"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="bd" Background="{TemplateBinding Background}"
                    BorderBrush="{TemplateBinding BorderBrush}"
                    BorderThickness="{TemplateBinding BorderThickness}" CornerRadius="3">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"
                                Margin="18,0"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="bd" Property="Background" Value="#E04B39"/>
              </Trigger>
              <Trigger Property="IsPressed" Value="True">
                <Setter TargetName="bd" Property="Background" Value="#8E2B20"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
  </Window.Resources>
  <Border BorderBrush="#C0392B" BorderThickness="1">
    <Grid>
      <Grid.RowDefinitions>
        <RowDefinition Height="38"/>
        <RowDefinition Height="Auto"/>
        <RowDefinition Height="*"/>
        <RowDefinition Height="Auto"/>
      </Grid.RowDefinitions>
      <Border x:Name="HeaderBar" Grid.Row="0" Background="#3A1F1B">
        <Grid>
          <StackPanel Orientation="Horizontal" VerticalAlignment="Center" Margin="14,0,0,0">
            <TextBlock Text="RevoBIM" Foreground="#3D9BE9" FontSize="14" FontWeight="Bold"/>
            <TextBlock Text=" PY" Foreground="#F07C10" FontSize="14" FontWeight="Bold"/>
            <TextBlock x:Name="HeadText" Text="  |  Confirm delete" Foreground="#F1B0A8"
                       FontSize="14"/>
          </StackPanel>
          <TextBlock x:Name="VersionText" Text="v0.0.0" Foreground="#8A9099"
                     HorizontalAlignment="Right" VerticalAlignment="Center"
                     Margin="0,0,14,0" FontSize="11"/>
        </Grid>
      </Border>
      <StackPanel Grid.Row="1" Margin="18,14,18,8">
        <TextBlock x:Name="BodyText" Text="" Foreground="#F1B0A8" TextWrapping="Wrap"
                   FontWeight="SemiBold"/>
        <TextBlock x:Name="SubText" Text="" Foreground="#DCDCDC" TextWrapping="Wrap"
                   Margin="0,8,0,0"/>
      </StackPanel>
      <Border Grid.Row="2" Margin="18,4,18,10" BorderBrush="#4F4F4F" BorderThickness="1">
        <TextBox x:Name="ImpactBox" Background="#1C1F24" Foreground="#B6BCC4"
                 BorderThickness="0" IsReadOnly="True" TextWrapping="NoWrap"
                 VerticalScrollBarVisibility="Auto" HorizontalScrollBarVisibility="Auto"
                 FontFamily="Consolas" FontSize="11" Padding="8,6"/>
      </Border>
      <Border Grid.Row="3" Background="#2B2B2B" Padding="12,10">
        <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
          <Button x:Name="BtnCancel" Style="{StaticResource RevoBtn}" Content="Cancel"
                  Height="40" MinWidth="120"/>
          <Button x:Name="BtnDelete" Style="{StaticResource DeleteBtn}"
                  Content="DELETE" Height="40" MinWidth="200" FontSize="14"/>
        </StackPanel>
      </Border>
    </Grid>
  </Border>
</Window>
""".replace('__STYLES__', SHARED_STYLES)

MERGE_XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Merge" Height="540" Width="660" MinHeight="420" MinWidth="520"
        WindowStartupLocation="CenterOwner" WindowStyle="None" ResizeMode="CanResize"
        Background="#262A31" FontFamily="Segoe UI" FontSize="12"
        TextOptions.TextFormattingMode="Display">
  <Window.Resources>
__STYLES__
  </Window.Resources>
  <Border BorderBrush="#4F4F4F" BorderThickness="1">
    <Grid>
      <Grid.RowDefinitions>
        <RowDefinition Height="38"/>
        <RowDefinition Height="Auto"/>
        <RowDefinition Height="*"/>
        <RowDefinition Height="Auto"/>
        <RowDefinition Height="Auto"/>
      </Grid.RowDefinitions>
      <Border x:Name="HeaderBar" Grid.Row="0" Background="#2B2B2B">
        <Grid>
          <StackPanel Orientation="Horizontal" VerticalAlignment="Center" Margin="14,0,0,0">
            <TextBlock Text="RevoBIM" Foreground="#3D9BE9" FontSize="14" FontWeight="Bold"/>
            <TextBlock Text=" PY" Foreground="#F07C10" FontSize="14" FontWeight="Bold"/>
            <TextBlock x:Name="HeadText" Text="  |  Merge" Foreground="#DCDCDC" FontSize="14"/>
          </StackPanel>
          <TextBlock x:Name="VersionText" Text="v0.0.0" Foreground="#8A9099"
                     HorizontalAlignment="Right" VerticalAlignment="Center"
                     Margin="0,0,14,0" FontSize="11"/>
        </Grid>
      </Border>
      <StackPanel Grid.Row="1" Margin="16,14,16,6">
        <TextBlock x:Name="IntroText" Text="" Foreground="#DCDCDC" TextWrapping="Wrap"/>
        <CheckBox x:Name="ChkSelectionSet" IsChecked="True" Margin="0,8,0,0"
                  Content="Selection set only - untick to choose any other style as the target"/>
        <TextBlock x:Name="WarnText" Text="" Foreground="#F07C10" TextWrapping="Wrap"
                   Margin="0,8,0,0" Visibility="Collapsed"/>
      </StackPanel>
      <Border Grid.Row="2" Margin="16,6,16,6" BorderBrush="#4F4F4F" BorderThickness="1">
        <ListBox x:Name="FilterList" Background="#2B2B2B" Foreground="#DCDCDC"
                 BorderThickness="0" SelectionMode="Single"/>
      </Border>
      <StackPanel Grid.Row="3" Margin="16,0,16,8">
        <CheckBox x:Name="ChkOverrides" IsChecked="True"
                  Content="Carry graphic overrides across where the kept filter is not already present"/>
        <CheckBox x:Name="ChkDelete" IsChecked="True"
                  Content="Delete the replaced styles after merging"/>
      </StackPanel>
      <Border Grid.Row="4" Background="#2B2B2B" Padding="12,10">
        <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
          <Button x:Name="BtnCancel" Style="{StaticResource RevoBtn}" Content="Cancel"/>
          <Button x:Name="BtnMerge" Style="{StaticResource AccentBtn}" Content="Merge"/>
        </StackPanel>
      </Border>
    </Grid>
  </Border>
</Window>
""".replace('__STYLES__', SHARED_STYLES)


# ---------------------------------------------------------------------------
#  DIALOGS
# ---------------------------------------------------------------------------
class PromptDialog(object):
    def __init__(self, owner, heading, body, detail='', primary='OK', secondary='Close',
                 open_path=None):
        self.path = open_path
        self.result = False
        self.window = parse_xaml('PROMPT_XAML', PROMPT_XAML)
        self.window.Owner = owner
        apply_window_chrome(self.window)
        self.window.FindName('VersionText').Text = 'v%s' % VERSION
        self.window.FindName('HeadText').Text = '  |  %s' % heading
        self.window.FindName('BodyText').Text = body
        self.window.FindName('PathText').Text = detail or ''
        self.window.FindName('HeaderBar').MouseLeftButtonDown += self.on_drag
        btn_open = self.window.FindName('BtnOpen')
        btn_close = self.window.FindName('BtnClose')
        btn_open.Content = primary
        if secondary:
            btn_close.Content = secondary
        else:
            btn_close.Visibility = Visibility.Collapsed
        btn_open.Click += self.on_ok
        btn_close.Click += self.on_close

    def on_drag(self, sender, args):
        try:
            self.window.DragMove()
        except Exception:
            pass

    def on_ok(self, sender, args):
        if self.path:
            open_in_explorer(self.path)
        self.result = True
        self.window.DialogResult = True
        self.window.Close()

    def on_close(self, sender, args):
        self.result = False
        self.window.DialogResult = False
        self.window.Close()

    def show(self):
        try:
            self.window.ShowDialog()
        except Exception:
            pass
        return self.result


class ConfirmDeleteDialog(object):
    def __init__(self, owner, heading, warning, detail, impact_lines,
                 confirm_label='DELETE'):
        self.result = False
        self.window = parse_xaml('CONFIRM_XAML', CONFIRM_XAML)
        self.window.Owner = owner
        apply_window_chrome(self.window)
        self.window.FindName('VersionText').Text = 'v%s' % VERSION
        self.window.FindName('HeadText').Text = '  |  %s' % heading
        self.window.FindName('BodyText').Text = warning
        self.window.FindName('SubText').Text = detail
        self.window.FindName('ImpactBox').Text = '\n'.join(impact_lines)
        self.window.FindName('HeaderBar').MouseLeftButtonDown += self.on_drag
        self.window.FindName('BtnDelete').Content = confirm_label
        self.window.FindName('BtnCancel').Click += self.on_cancel
        self.window.FindName('BtnDelete').Click += self.on_delete

    def on_drag(self, sender, args):
        try:
            self.window.DragMove()
        except Exception:
            pass

    def on_cancel(self, sender, args):
        self.result = False
        self.window.DialogResult = False
        self.window.Close()

    def on_delete(self, sender, args):
        self.result = True
        self.window.DialogResult = True
        self.window.Close()

    def show(self):
        try:
            self.window.ShowDialog()
        except Exception:
            pass
        return self.result


class MergeDialog(object):
    """Pick the style to keep.

    Follows Ideate StyleManager's pattern: the list starts as the rows the user
    selected, and unticking "Selection set only" widens it to every style that
    could legitimately be the target - which is how a custom subcategory gets
    merged into a built-in one that was never in the table.
    """

    def __init__(self, owner, rows, thing='filter', show_overrides=True, summary=None,
                 all_targets=None, check_groups=True):
        self.rows = rows
        self.all_targets = all_targets or []
        self.summary = summary
        self.result = None
        self.window = parse_xaml('MERGE_XAML', MERGE_XAML)
        self.window.Owner = owner
        apply_window_chrome(self.window)
        self.window.FindName('VersionText').Text = 'v%s' % VERSION
        self.window.FindName('HeadText').Text = '  |  Merge %ss' % thing
        self.window.FindName('IntroText').Text = (
            'Choose the %s to keep. Everything using the others will be repointed to it, '
            'and the emptied %ss are then removed.' % (thing, thing))
        self.window.FindName('HeaderBar').MouseLeftButtonDown += self.on_drag

        if not show_overrides:
            self.window.FindName('ChkOverrides').Visibility = Visibility.Collapsed

        selection_box = self.window.FindName('ChkSelectionSet')
        if not self.all_targets:
            selection_box.Visibility = Visibility.Collapsed
        else:
            selection_box.Checked += self.on_scope_changed
            selection_box.Unchecked += self.on_scope_changed

        # Only meaningful where the tab looks for duplicates at all; on Fonts or
        # View Templates every merge would otherwise carry the warning.
        groups = set(r.get('group', '') for r in rows)
        if check_groups and (len(groups) > 1 or '' in groups):
            warn = self.window.FindName('WarnText')
            warn.Text = ('Warning: these %ss are not all in the same duplicate group, so '
                         'they do not look identical. Merging will change the appearance '
                         'of everything that used the replaced ones.' % thing)
            warn.Visibility = Visibility.Visible

        self.fill_list(rows)
        self.window.FindName('BtnCancel').Click += self.on_cancel
        self.window.FindName('BtnMerge').Click += self.on_merge

    def fill_list(self, rows):
        listbox = self.window.FindName('FilterList')
        listbox.Items.Clear()
        for row in sorted(rows, key=lambda r: (-(r.get('usage') or 0), r['name'].lower())):
            item = ListBoxItem()
            uses = row.get('usage')
            uses_text = '%d use%s' % (uses, '' if uses == 1 else 's') \
                if uses is not None else 'usage not analysed'
            label = row['name']
            if row.get('builtin'):
                label += '   [built in]'
            item.Content = u'%s      (%s)   id %d\n     %s' % (
                label, uses_text, row['id'],
                (self.summary(row) if self.summary else '')[:170])
            item.Tag = row['id']
            item.Padding = Thickness(8, 6, 8, 6)
            listbox.Items.Add(item)
        if listbox.Items.Count:
            listbox.SelectedIndex = 0

    @ui_safe
    def on_scope_changed(self, sender, args):
        if self.window.FindName('ChkSelectionSet').IsChecked:
            self.fill_list(self.rows)
        else:
            self.fill_list(self.all_targets)

    def on_drag(self, sender, args):
        try:
            self.window.DragMove()
        except Exception:
            pass

    def on_cancel(self, sender, args):
        self.result = None
        self.window.DialogResult = False
        self.window.Close()

    def on_merge(self, sender, args):
        item = self.window.FindName('FilterList').SelectedItem
        if item is None:
            return
        keep_id = int(item.Tag)
        self.result = {
            'keep': keep_id,
            'drop': [r['id'] for r in self.rows if r['id'] != keep_id],
            'overrides': bool(self.window.FindName('ChkOverrides').IsChecked),
            'delete': bool(self.window.FindName('ChkDelete').IsChecked),
        }
        self.window.DialogResult = True
        self.window.Close()

    def show(self):
        self.window.ShowDialog()
        return self.result


# ---------------------------------------------------------------------------
#  PANELS
# ---------------------------------------------------------------------------
class BasePanel(object):
    key = 'base'
    tab_title = 'Panel'
    nav_label = None
    allow_duplicates = True      # False where "same settings" is not a useful idea
    # (key, label, ticked by default) - the settings that must match for two rows
    # to count as duplicates. The user picks from these in the Duplicate Rules
    # menu. A key reads row['dup'][key] when the reader stored an exact form,
    # otherwise the displayed value in that column.
    dup_rules = []
    dup_extra_keys = []          # rule keys with no column of their own
    group_column = None          # column whose value groups and colours the rows
    header_rows = False          # draw a collapsible header per group
    icon_file = ''
    thing = 'style'
    sheet_name = 'Styles'
    columns = []
    excel_notes = []
    revit_dialogs = None          # (PostableCommand names, dialog captions)
    delete_warning = 'These styles will be deleted.'

    def __init__(self, app):
        self.app = app
        self.rows = []
        self.groups = []
        self.pending = {}
        self.pending_new = []
        self.changed_ids = set()
        self.table = None
        self.registry = GroupRegistry()
        self.family_registry = GroupRegistry()
        self.sort_by_group = False
        self.loaded = False
        self.collapsed = set()
        self.click_selection = set()
        self.leading_columns = 0
        self.row_index = {}
        self.picked_groups = set()

        # Built in named stages. When a panel cannot be constructed the message
        # says which stage failed - every tab failing at once used to surface as
        # "No tabs could be built" with no reason attached to it.
        stage = 'parsing the panel layout'
        try:
            self.root = parse_xaml('PANEL_XAML', PANEL_XAML)
            stage = 'finding the table in the layout'
            self.grid = self.find('Grid')
            if self.grid is None:
                raise Exception('the layout has no control named Grid')
            stage = 'building the columns'
            self.build_columns()
            stage = 'wiring the controls'
            self.wire()
        except Exception as ex:
            raise Exception('%s failed while %s: %s'
                            % (self.__class__.__name__, stage, ex))

    # -- plumbing ----------------------------------------------------------
    def find(self, name):
        return self.root.FindName(name)

    def log(self, message):
        self.app.log(message)

    def post(self, message):
        self.app.post(message)

    def post_many(self, lines):
        self.app.post_many(lines)

    def log_many(self, lines):
        self.app.log_many(lines)

    def progress(self, done, total, text=''):
        self.app.post_progress(done, total, text)

    def confirm_long_run(self, what):
        return self.app.confirm_long_run(what)

    def column_by_name(self, name):
        for col in self.columns:
            if col['name'] == name:
                return col
        return None

    def row_by_id(self, rid):
        # A dict, not a scan: selection, staging, Select Unused and bulk rename all
        # look rows up one at a time, and on a 2,600-row tab a scan per lookup made
        # each of those quadratic.
        return self.row_index.get(rid)

    def can_edit(self, row, col):
        if not col.get('edit'):
            return False
        if col['name'] == 'Name':
            return not row.get('builtin')
        return not (row.get('complex') or row.get('builtin'))

    def build_columns(self):
        """Build the grid columns.

        Each is added independently: a column the engine will not take costs that
        one column and is reported, rather than throwing and losing the whole tab.
        """
        # How many columns sit in front of the panel's own, so anything addressing
        # a column by index allows for them. The colour column is only built where
        # grouping means something, so this is not always two.
        self.leading_columns = 0

        if self.allow_duplicates or self.group_column:
            try:
                chip = DataGridTemplateColumn()
                chip.Header = 'Dup' if self.allow_duplicates else 'Grp'
                chip.Width = column_width(58)
                chip.SortMemberPath = 'Group'
                chip.IsReadOnly = True
                chip.CellTemplate = parse_xaml('CHIP_TEMPLATE', CHIP_TEMPLATE)
                self.grid.Columns.Add(chip)
                self.leading_columns += 1
            except Exception as ex:
                self.app.startup_note('%s: colour column skipped - %s'
                                      % (self.__class__.__name__, ex))

        try:
            changed = DataGridTextColumn()
            changed.Header = 'Chg'
            changed.Width = column_width(62)
            changed.IsReadOnly = True
            changed.Binding = Binding('Changed')
            self.grid.Columns.Add(changed)
            self.leading_columns += 1
        except Exception as ex:
            self.app.startup_note('%s: staging column skipped - %s'
                                  % (self.__class__.__name__, ex))

        edit_style = None
        try:
            edit_style = self.app.window.FindResource('CellEdit')
        except Exception:
            edit_style = None

        for col in self.columns:
            try:
                if col.get('choices') and col.get('edit'):
                    # A DataGridComboBoxColumn commits through the same
                    # CellEditEnding path as a text cell, so multi-row apply works
                    # with no extra wiring.
                    column = DataGridComboBoxColumn()
                    column.SelectedItemBinding = Binding(col['name'])
                    try:
                        column.ItemsSource = List[System.String]()
                    except Exception:
                        pass
                else:
                    column = DataGridTextColumn()
                    column.Binding = Binding(col['name'])
                    if col.get('edit') and edit_style is not None:
                        column.EditingElementStyle = edit_style
                column.Header = col['header']
                column.Width = column_width(col.get('width', 100))
                column.IsReadOnly = not col.get('edit')
                self.grid.Columns.Add(column)
            except Exception as ex:
                self.app.startup_note('%s: column "%s" skipped - %s'
                                      % (self.__class__.__name__, col.get('header'), ex))

    def hook(self, name, event, handler):
        """Attach a handler, tolerating a control this layout does not have."""
        try:
            control = self.find(name)
        except Exception:
            return False
        if control is None:
            return False
        try:
            if event == 'Click':
                control.Click += handler
            elif event == 'Checked':
                control.Checked += handler
            elif event == 'Unchecked':
                control.Unchecked += handler
            elif event == 'TextChanged':
                control.TextChanged += handler
            elif event == 'KeyDown':
                control.KeyDown += handler
            elif event == 'SelectionChanged':
                control.SelectionChanged += handler
            else:
                return False
            return True
        except Exception:
            return False

    def wire(self):
        """Attach every handler tolerantly.

        Nothing here is allowed to take a tab down. A control missing from the
        layout costs that one feature and is reported, rather than throwing and
        losing the whole panel - which is how a single bad hookup turned into
        "No tabs could be built" with nothing to go on.
        """
        missing = []
        for name, event, handler in (
                ('BtnRefresh', 'Click', self.on_refresh),
                ('BtnAnalyze', 'Click', self.on_analyze),
                ('BtnDupes', 'Click', self.on_dupes),
                ('BtnDupRules', 'Click', self.on_dup_rules),
                ('BtnAllGroups', 'Click', self.on_pick_all_groups),
                ('BtnNoGroups', 'Click', self.on_clear_groups),
                ('BtnMergeGroups', 'Click', self.on_merge_groups),
                ('BtnMerge', 'Click', self.on_merge),
                ('BtnDelete', 'Click', self.on_delete),
                ('BtnExcel', 'Click', self.on_excel),
                ('BtnUnused', 'Click', self.on_unused),
                ('BtnRevit', 'Click', self.on_edit_in_revit),
                ('BtnRenameApply', 'Click', self.on_mass_rename),
                ('BtnCollapse', 'Click', self.on_collapse_all),
                ('BtnExpand', 'Click', self.on_expand_all),
                ('FindBox', 'KeyDown', self.on_rename_key),
                ('ReplaceBox', 'KeyDown', self.on_rename_key),
                ('SearchBox', 'TextChanged', self.on_filter_changed),
                ('GroupFilter', 'SelectionChanged', self.on_filter_changed),
                ('ChkDupOnly', 'Checked', self.on_filter_changed),
                ('ChkDupOnly', 'Unchecked', self.on_filter_changed),
                ('ChkUnusedOnly', 'Checked', self.on_filter_changed),
                ('ChkUnusedOnly', 'Unchecked', self.on_filter_changed),
                ('ChkChangedOnly', 'Checked', self.on_filter_changed),
                ('ChkChangedOnly', 'Unchecked', self.on_filter_changed)):
            if not self.hook(name, event, handler):
                missing.append('%s.%s' % (name, event))

        try:
            self.grid.BeginningEdit += self.on_beginning_edit
        except Exception:
            missing.append('Grid.BeginningEdit')
        try:
            self.grid.PreparingCellForEdit += self.on_preparing_edit
        except Exception:
            missing.append('Grid.PreparingCellForEdit')
        try:
            self.grid.CellEditEnding += self.on_cell_edit_ending
        except Exception:
            missing.append('Grid.CellEditEnding')
        try:
            self.grid.PreviewMouseRightButtonDown += self.on_right_click
        except Exception:
            missing.append('Grid.PreviewMouseRightButtonDown')
        try:
            self.grid.PreviewMouseLeftButtonDown += self.on_grid_left_click
        except Exception:
            missing.append('Grid.PreviewMouseLeftButtonDown')
        try:
            self.grid.Sorting += self.on_grid_sorting
        except Exception:
            missing.append('Grid.Sorting')
        try:
            self.grid.ContextMenu = self.build_menu()
        except Exception:
            missing.append('Grid.ContextMenu')
        try:
            self.find('BtnExcel').ContextMenu = self.build_excel_menu()
        except Exception:
            missing.append('BtnExcel.ContextMenu')

        if self.revit_dialogs is None:
            try:
                self.find('BtnRevit').Visibility = Visibility.Collapsed
            except Exception:
                pass

        try:
            self.configure_panel()
        except Exception as ex:
            self.app.startup_note('%s: %s' % (self.__class__.__name__, ex))

        if missing:
            self.app.startup_note('%s: could not wire %s'
                                  % (self.__class__.__name__, ', '.join(missing)))

    def build_excel_menu(self):
        menu = ContextMenu()
        export_item = MenuItem()
        export_item.Header = 'Export to Excel...'
        export_item.Click += self.on_export
        menu.Items.Add(export_item)
        import_item = MenuItem()
        import_item.Header = 'Import from Excel...'
        import_item.Click += self.on_import
        menu.Items.Add(import_item)
        return menu

    @ui_safe
    def on_excel(self, sender, args):
        """One button, both directions - drop the menu under it."""
        menu = sender.ContextMenu
        menu.PlacementTarget = sender
        menu.Placement = WpfPrimitives.PlacementMode.Bottom
        menu.IsOpen = True

    def configure_panel(self):
        """Show only the controls this panel actually uses."""
        if not self.allow_duplicates or not self.dup_rules:
            for name in ('BtnDupRules', 'GroupMergeBar'):
                try:
                    self.find(name).Visibility = Visibility.Collapsed
                except Exception:
                    pass
        if not self.allow_duplicates:
            for name in ('BtnDupes', 'ChkDupOnly'):
                try:
                    self.find(name).Visibility = Visibility.Collapsed
                except Exception:
                    pass
            if not self.group_column:
                try:
                    self.find('LegendBar').Visibility = Visibility.Collapsed
                except Exception:
                    pass
            try:
                self.find('LegendTitle').Text = 'Groups (click a swatch to select it)'
            except Exception:
                pass
        if self.group_column:
            for name in ('GroupFilter', 'GroupFilterLabel'):
                self.find(name).Visibility = Visibility.Visible
        if self.header_rows:
            for name in ('BtnCollapse', 'BtnExpand'):
                self.find(name).Visibility = Visibility.Visible

    def ancestor(self, node, wanted):
        """Walk up the visual tree looking for a control of this type."""
        for _ in range(14):
            if node is None:
                return None
            if isinstance(node, wanted):
                return node
            try:
                node = VisualTreeHelper.GetParent(node)
            except Exception:
                return None
        return None

    def build_menu(self):
        menu = ContextMenu()
        self.mnu_rename = MenuItem()
        self.mnu_rename.Header = 'Rename          F2'
        self.mnu_rename.Click += self.on_menu_rename
        menu.Items.Add(self.mnu_rename)
        self.mnu_group = MenuItem()
        self.mnu_group.Header = 'Select duplicate group'
        self.mnu_group.Click += self.on_menu_group
        menu.Items.Add(self.mnu_group)
        menu.Items.Add(Separator())
        self.mnu_merge = MenuItem()
        self.mnu_merge.Header = 'Merge selected...'
        self.mnu_merge.Click += self.on_merge
        menu.Items.Add(self.mnu_merge)
        self.mnu_delete = MenuItem()
        self.mnu_delete.Header = 'Delete selected...'
        self.mnu_delete.Click += self.on_delete
        menu.Items.Add(self.mnu_delete)
        return menu

    # -- table -------------------------------------------------------------
    def display_value(self, row, col):
        change = self.pending.get(row['id'], {})
        if col['name'] in change:
            return safe_str(change[col['name']])
        return safe_str(row['values'].get(col['name'], ''))

    def fill_choices(self):
        """Load each dropdown column's options from whatever the model offers."""
        for index, col in enumerate(self.columns):
            if not (col.get('choices') and col.get('edit')):
                continue
            try:
                column = self.grid.Columns[index + self.leading_columns]
            except Exception:
                continue
            try:
                options = self.choices_for(col['name'])
            except Exception:
                options = []
            try:
                items = List[System.String]()
                for option in options:
                    items.Add(safe_str(option))
                column.ItemsSource = items
            except Exception:
                pass

    def choices_for(self, name):
        """Options for a dropdown column. Panels override this."""
        return []

    def current_selection_ids(self):
        ids = set()
        try:
            for item in self.grid.SelectedItems:
                try:
                    if safe_str(item['RowKind']) == 'header':
                        continue
                    ids.add(safe_str(item['ElemId']))
                except Exception:
                    continue
        except Exception:
            pass
        return ids

    def reselect(self, ids):
        """Put a selection back after the table has been rebuilt, so a staged edit
        does not clear the rows you were working through."""
        if not ids:
            return
        try:
            self.grid.SelectedItems.Clear()
            for item in self.grid.Items:
                try:
                    if safe_str(item['ElemId']) in ids:
                        self.grid.SelectedItems.Add(item)
                except Exception:
                    continue
        except Exception:
            pass

    def refresh_table(self):
        keep = self.current_selection_ids()
        table = DataTable(self.key)
        t_obj = clr.GetClrType(Object)
        t_str = clr.GetClrType(System.String)
        for name, ctype in (('RowBrush', t_obj), ('ChipBrush', t_obj), ('Group', t_str),
                            ('Changed', t_str), ('RowKind', t_str), ('GroupKey', t_str),
                            ('SortKey', t_str), ('Hidden', t_str)):
            table.Columns.Add(name, ctype)
        for col in self.columns:
            if col['name'] in RESERVED_COLUMNS:
                self.app.startup_note(
                    '%s: column "%s" uses the reserved name %s and was skipped'
                    % (self.__class__.__name__, col['header'], col['name']))
                continue
            table.Columns.Add(col['name'],
                              clr.GetClrType(System.Int32) if col.get('type') == 'int'
                              else t_str)

        base_brush = brush_from_hex(ROW_BG)
        changed_brush = brush_from_hex(blend_hex(CHANGED, ROW_BG, 0.30))
        pending_brush = brush_from_hex(blend_hex(ORANGE, ROW_BG, 0.28))

        for row in self.rows:
            chip_hex = row.get('chip', '')
            is_pending = row['id'] in self.pending
            is_changed = row['id'] in self.changed_ids
            if chip_hex:
                row_brush = brush_from_hex(blend_hex(chip_hex, ROW_BG, 0.22))
                chip_brush = brush_from_hex(chip_hex)
            else:
                row_brush = base_brush
                chip_brush = base_brush
            if is_changed:
                row_brush = changed_brush
            if is_pending:
                row_brush = pending_brush

            if row.get('row_colour'):
                row_brush = brush_from_hex(blend_hex(row['row_colour'], ROW_BG, 0.20))
                if is_changed:
                    row_brush = changed_brush
                if is_pending:
                    row_brush = pending_brush
            group_key = safe_str(row.get('group_key', ''))
            dr = table.NewRow()
            dr['RowBrush'] = row_brush
            dr['ChipBrush'] = chip_brush
            dr['Group'] = row.get('group', '')
            dr['Changed'] = 'Pending' if is_pending else ('Yes' if is_changed else '')
            dr['RowKind'] = 'data'
            dr['GroupKey'] = group_key
            dr['SortKey'] = u'%s\x01%s' % (group_key.lower(), row['name'].lower())
            dr['Hidden'] = 'Y' if group_key in self.collapsed else 'N'
            for col in self.columns:
                value = self.display_value(row, col)
                if col.get('type') == 'int':
                    try:
                        dr[col['name']] = int(float(value or 0))
                    except Exception:
                        dr[col['name']] = 0
                else:
                    dr[col['name']] = value
            table.Rows.Add(dr)

        for index, rec in enumerate(self.pending_new):
            dr = table.NewRow()
            dr['RowBrush'] = pending_brush
            dr['ChipBrush'] = brush_from_hex(ORANGE)
            dr['Group'] = ''
            dr['Changed'] = 'Pending'
            for col in self.columns:
                if col.get('type') == 'int':
                    dr[col['name']] = 0
                else:
                    dr[col['name']] = safe_str(rec.get(col['name'], ''))
            dr['Name'] = rec.get('name', '')
            dr['ElemId'] = 'NEW%d' % index
            dr['Status'] = 'New - not created yet'
            table.Rows.Add(dr)

        if self.header_rows and self.group_column:
            first = self.columns[0]['name']
            counts = {}
            for row in self.rows:
                key = safe_str(row.get('group_key', ''))
                counts[key] = counts.get(key, 0) + 1
            for key in sorted(counts.keys(), key=lambda t: t.lower()):
                dr = table.NewRow()
                colour = ''
                for group in self.groups:
                    if group.get('key') == key:
                        colour = group['colour']
                        break
                dr['RowBrush'] = brush_from_hex(blend_hex(colour or ACCENT, GRID_BG, 0.34))
                dr['ChipBrush'] = brush_from_hex(colour or ACCENT)
                dr['Group'] = ''
                dr['Changed'] = ''
                dr['RowKind'] = 'header'
                dr['GroupKey'] = key
                dr['SortKey'] = u'%s\x00' % key.lower()
                dr['Hidden'] = 'N'
                for col in self.columns:
                    if col.get('type') == 'int':
                        dr[col['name']] = 0
                    else:
                        dr[col['name']] = ''
                marker = '+' if key in self.collapsed else '-'
                dr[first] = u'  %s   %s   (%d)' % (marker, key or '(none)', counts[key])
                dr['ElemId'] = u'HDR:%s' % key
                table.Rows.Add(dr)

        self.table = table
        self.grid.ItemsSource = table.DefaultView
        self.fill_choices()
        self.fill_group_filter()
        self.apply_view_filter()
        self.build_legend()
        self.reselect(keep)
        self.app.update_pending_ui()

    def usage_column(self):
        return self.column_by_name('Uses') or self.column_by_name('TotalUses')

    def unused_clause(self):
        """The filter for "unused only", written to suit the column's own type.

        Where usage is counted on every read the column holds a number. Where it
        is worked out by Analyze it holds text, because an unanalysed row reads
        "?" and a built-in one reads "-" - so the comparison has to be quoted or
        the DataView refuses it with "cannot perform '=' on System.String and
        System.Int32".
        """
        col = self.usage_column()
        if col is None:
            return ''
        if col.get('type') == 'int':
            return '[%s] = 0' % col['name']
        return "[%s] = '0'" % col['name']

    def apply_view_filter(self):
        if self.table is None:
            return
        clauses = []
        text = safe_str(self.find('SearchBox').Text).strip()
        if text:
            escaped = text.replace("'", "''").replace('[', '[[]').replace('%', '[%]')
            parts = []
            for col in self.columns:
                if col.get('type') != 'int':
                    parts.append("[%s] LIKE '%%%s%%'" % (col['name'], escaped))
            if parts:
                if self.header_rows:
                    parts.append("[RowKind] = 'header'")
                clauses.append('(%s)' % ' OR '.join(parts))
        if self.find('ChkDupOnly').IsChecked:
            clauses.append("[Group] <> ''")
        if self.find('ChkUnusedOnly').IsChecked:
            clause = self.unused_clause()
            if clause:
                clauses.append(clause)
        if self.find('ChkChangedOnly').IsChecked:
            clauses.append("[Changed] <> ''")
        if self.header_rows:
            clauses.append("[Hidden] = 'N'")
        if self.group_column:
            chosen = safe_str(self.find('GroupFilter').SelectedItem)
            if chosen and chosen != ALL_CATEGORIES:
                escaped = chosen.replace("'", "''")
                clauses.append("[GroupKey] = '%s'" % escaped)
        try:
            self.table.DefaultView.RowFilter = ' AND '.join(clauses)
        except Exception as ex:
            self.log('Search error: %s' % ex)
        self.apply_sort()
        try:
            self.find('CountText').Text = '%d of %d shown' % (
                self.table.DefaultView.Count, self.table.Rows.Count)
        except Exception:
            pass

    @ui_safe
    def on_grid_left_click(self, sender, e):
        """Open a cell for editing without losing the rows already highlighted.

        A plain click on a DataGrid row collapses a multi-row selection to that
        one row, and it does it before the cell ever starts editing. So when the
        click lands on an editable cell inside a selection of several rows, the
        click is handled here instead: the cell is put into edit mode, the
        selection is put back exactly as it was, and the event is marked handled
        so WPF never gets to collapse it. The rows stay highlighted while the
        dropdown is open, which is what makes "select several, change one, they
        all follow" behave the way it looks.
        """
        row = self.ancestor(e.OriginalSource, DataGridRow)
        if row is None:
            return

        # a click on a group header folds that group away
        if self.header_rows:
            try:
                if safe_str(row.Item['RowKind']) == 'header':
                    key = safe_str(row.Item['GroupKey'])
                    if key in self.collapsed:
                        self.collapsed.discard(key)
                    else:
                        self.collapsed.add(key)
                    e.Handled = True
                    self.refresh_table()
                    return
            except Exception:
                pass

        selected = []
        try:
            selected = list(self.grid.SelectedItems)
        except Exception:
            selected = []
        if len(selected) < 2 or not row.IsSelected:
            self.click_selection = set()
            return

        cell = self.ancestor(e.OriginalSource, DataGridCell)
        if cell is None or cell.Column is None or cell.Column.IsReadOnly:
            return

        self.click_selection = set()
        for item in selected:
            try:
                if safe_str(item['RowKind']) == 'header':
                    continue
                self.click_selection.add(int(item['ElemId']))
            except Exception:
                continue

        try:
            self.grid.CurrentCell = DataGridCellInfo(row.Item, cell.Column)
            self.grid.BeginEdit()
        except Exception:
            return

        # BeginEdit can still drop the selection on some builds - put it back
        try:
            if self.grid.SelectedItems.Count != len(selected):
                self.grid.SelectedItems.Clear()
                for item in selected:
                    self.grid.SelectedItems.Add(item)
        except Exception:
            pass
        e.Handled = True

    @ui_safe
    def on_collapse_all(self, sender, args):
        self.collapsed = set(safe_str(r.get('group_key', '')) for r in self.rows)
        self.refresh_table()
        self.log('All %d group(s) collapsed. Click a header to open one.'
                 % len(self.collapsed))

    @ui_safe
    def on_expand_all(self, sender, args):
        self.collapsed = set()
        self.refresh_table()
        self.log('All groups expanded.')

    def fill_group_filter(self):
        if not self.group_column:
            return
        combo = self.find('GroupFilter')
        previous = safe_str(combo.SelectedItem)
        keys = sorted(set(safe_str(r.get('group_key', '')) for r in self.rows),
                      key=lambda t: t.lower())
        combo.Items.Clear()
        combo.Items.Add(ALL_CATEGORIES)
        for key in keys:
            combo.Items.Add(key or '(none)')
        combo.SelectedIndex = 0
        if previous:
            for index in range(combo.Items.Count):
                if safe_str(combo.Items[index]) == previous:
                    combo.SelectedIndex = index
                    break

    @ui_safe
    def on_grid_sorting(self, sender, e):
        """A header click takes over from the automatic grouping."""
        self.sort_by_group = safe_str(e.Column.SortMemberPath) == 'Group' \
            or safe_str(e.Column.Header) == 'Dup'

    def apply_sort(self):
        """Group the duplicates together whenever the list is showing only them.

        Sorted by group letter then name, so the members of each group sit next to
        each other under one colour rather than being scattered alphabetically.
        """
        if self.table is None:
            return
        want_group = bool(self.sort_by_group)
        name_col = self.columns[0]['name']
        if self.header_rows:
            try:
                self.table.DefaultView.Sort = '[SortKey] ASC'
            except Exception:
                pass
            return
        try:
            if want_group:
                self.table.DefaultView.Sort = '[Group] ASC, [%s] ASC' % name_col
            elif safe_str(self.table.DefaultView.Sort).startswith('[Group]'):
                self.table.DefaultView.Sort = '[%s] ASC' % name_col
        except Exception:
            pass

    def build_legend(self):
        panel = self.find('LegendPanel')
        panel.Children.Clear()
        # Group letters and colours are stable, so a picked group stays picked
        # across a refresh; only groups that no longer exist are dropped.
        live = set(group['label'] for group in self.groups)
        self.picked_groups &= live
        for group in self.groups:
            picked = group['label'] in self.picked_groups
            btn = Button()
            btn.Content = '%s%s  x%d' % (u'\u2713 ' if picked else '', group['label'],
                                         group['count'])
            btn.Background = brush_from_hex(group['colour'])
            btn.Foreground = brush_from_hex('#1A1A1A')
            btn.BorderBrush = brush_from_hex('#FFFFFF')
            btn.BorderThickness = Thickness(2) if picked else Thickness(0)
            btn.Opacity = 1.0 if picked or not self.picked_groups else 0.55
            btn.Padding = Thickness(10, 3, 10, 3)
            btn.Margin = Thickness(0, 0, 6, 6)
            btn.FontWeight = System.Windows.FontWeights.Bold
            btn.Cursor = System.Windows.Input.Cursors.Hand
            btn.Tag = group['label']
            keeper = choose_keeper([self.row_by_id(i) for i in group['members']
                                    if self.row_by_id(i) is not None] or [{}])
            btn.ToolTip = 'Merges into: %s\n\n%s' % (
                keeper.get('name', '?'), '\n'.join(group['names']))
            btn.Click += self.on_legend_click
            panel.Children.Add(btn)
        self.update_merge_groups_button()

    @ui_safe
    def on_legend_click(self, sender, args):
        """Pick or unpick a group. The table selects every row in the picked groups,
        so what is about to be merged is what is highlighted."""
        label = safe_str(sender.Tag)
        if label in self.picked_groups:
            self.picked_groups.discard(label)
        else:
            self.picked_groups.add(label)
        self.select_picked_groups()
        self.build_legend()

    def select_picked_groups(self):
        try:
            self.grid.SelectedItems.Clear()
            for item in self.grid.Items:
                try:
                    if safe_str(item['Group']) in self.picked_groups:
                        self.grid.SelectedItems.Add(item)
                except Exception:
                    continue
        except Exception:
            pass

    @ui_safe
    def on_pick_all_groups(self, sender, args):
        self.picked_groups = set(group['label'] for group in self.groups)
        self.select_picked_groups()
        self.build_legend()

    @ui_safe
    def on_clear_groups(self, sender, args):
        self.picked_groups = set()
        try:
            self.grid.UnselectAll()
        except Exception:
            pass
        self.build_legend()

    def update_merge_groups_button(self):
        """Light the button up when there is something to merge."""
        try:
            button = self.find('BtnMergeGroups')
        except Exception:
            return
        if button is None:
            return
        count = len(self.picked_groups)
        busy = getattr(self.app, 'busy', False)
        button.IsEnabled = bool(count) and not busy
        if count:
            button.Content = 'Merge %d Group%s' % (count, '' if count == 1 else 's')
            button.Background = brush_from_hex(ORANGE)
            button.BorderBrush = brush_from_hex('#FFB15C')
            button.Foreground = brush_from_hex('#FFFFFF')
        else:
            button.Content = 'Merge Groups'
            button.ClearValue(WpfControls.Control.BackgroundProperty)
            button.ClearValue(WpfControls.Control.BorderBrushProperty)
            button.ClearValue(WpfControls.Control.ForegroundProperty)

    def group_merge_plan(self):
        """[(label, keeper row, [rows merged into it])] for every picked group."""
        plan = []
        for group in self.groups:
            if group['label'] not in self.picked_groups:
                continue
            members = [self.row_by_id(i) for i in group['members']]
            members = [m for m in members if m is not None and not m.get('builtin')]
            if len(members) < 2:
                continue
            keeper = choose_keeper(members)
            plan.append((group['label'], keeper,
                         [m for m in members if m['id'] != keeper['id']]))
        return plan

    @ui_safe
    def on_merge_groups(self, sender, args):
        if self.app.pending_count():
            self.log('Apply or discard staged changes before merging - a merge deletes '
                     'styles and would strand those edits.')
            return
        plan = self.group_merge_plan()
        if not plan:
            self.log('Pick one or more duplicate groups along the bottom first.')
            return
        unknown = [m['name'] for _label, keeper, drops in plan
                   for m in [keeper] + drops if m.get('usage') is None]
        if unknown:
            self.log('Analyze these first, so the most-used style in each group is known: '
                     '%s' % ', '.join(unknown[:8]) + (' and others' if len(unknown) > 8
                                                      else ''))
            return

        drops = sum(len(d) for _l, _k, d in plan)
        impact = []
        for label, keeper, merged in plan:
            impact.append('Group %s  ->  keep "%s" (%s use%s)'
                          % (label, keeper['name'], keeper.get('usage') or 0,
                             '' if keeper.get('usage') == 1 else 's'))
            for row in merged:
                impact.append('      merge "%s" (%s use%s)'
                              % (row['name'], row.get('usage') or 0,
                                 '' if row.get('usage') == 1 else 's'))

        if (self.needs_analysis or drops >= 50) and not self.confirm_long_run(
                'Merging %d group(s) moves everything off %d %s(s) and deletes them.'
                % (len(plan), drops, self.thing)):
            self.log('Group merge cancelled.')
            return
        confirm = ConfirmDeleteDialog(
            self.app.window, 'Confirm group merge',
            'Merge %d duplicate group(s): %d %s(s) will be merged away.'
            % (len(plan), drops, self.thing),
            'Each group is merged into the style used by the most elements, then the '
            'others in the group are deleted. Each group runs on its own, so one that '
            'Revit refuses does not stop the rest.',
            impact, confirm_label='MERGE %d GROUP%s' % (len(plan),
                                                        '' if len(plan) == 1 else 'S'))
        if not confirm.show():
            self.log('Group merge cancelled.')
            return

        jobs = []
        for label, keeper, merged in plan:
            jobs.append((label, keeper['name'], {
                'keep': keeper['id'],
                'drop': [m['id'] for m in merged],
                'overrides': True,
                'delete': True,
            }))
        self.app.set_busy(True)
        self.log('Merging %d group(s)...' % len(jobs))
        rows_copy = list(self.rows)
        self.app.queue(lambda uiapp: self._run_group_merge(uiapp, rows_copy, jobs))

    def _run_group_merge(self, uiapp, rows, jobs):
        """Every picked group in one pass, then one re-read at the end."""
        doc = uiapp.ActiveUIDocument.Document
        lines = []
        done = 0
        for index, (label, keep_name, result) in enumerate(jobs):
            self.progress(index, len(jobs), 'Merging group %s into %s (%d of %d)'
                          % (label, keep_name, index + 1, len(jobs)))
            lines.append('--- Group %s: keeping "%s" ---' % (label, keep_name))
            try:
                lines.extend(self.merge_impl(doc, rows, result))
                done += 1
            except Exception as ex:
                lines.append('Group %s failed and was left as it was: %s' % (label, ex))
        self.progress(0, 0)
        lines.insert(0, 'Merged %d of %d group(s).' % (done, len(jobs)))
        if self.app.settings.get('write_log_files', True):
            path = write_log(lines, 'merge_groups_%s' % self.key)
            if path:
                lines.append('Log written to %s' % path)
        self.post_many(lines)
        self.picked_groups = set()
        self.app.window.Dispatcher.Invoke(Action(self.after_merge))

    def select_group(self, label):
        if not label:
            return
        self.grid.SelectedItems.Clear()
        for item in self.grid.Items:
            try:
                if safe_str(item['Group']) == label:
                    self.grid.SelectedItems.Add(item)
            except Exception:
                continue
        self.log('Selected %d %s(s) in group %s.'
                 % (self.grid.SelectedItems.Count, self.thing, label))

    def selected_rows(self):
        ids = []
        for item in self.grid.SelectedItems:
            try:
                if safe_str(item['RowKind']) == 'header':
                    continue
                ids.append(int(item['ElemId']))
            except Exception:
                continue
        return [r for r in [self.row_by_id(i) for i in ids] if r is not None]

    # -- staging -----------------------------------------------------------
    def stage(self, rid, field, value):
        row = self.row_by_id(rid)
        if row is None:
            return
        original = safe_str(row['values'].get(field, ''))
        if safe_str(value).strip() == original.strip():
            self.clear_stage(rid, field)
            return
        change = self.pending.get(rid)
        if change is None:
            change = {}
            self.pending[rid] = change
        change[field] = value
        if not getattr(self, '_batch', False):
            self.log('Staged: "%s" %s -> %s' % (row['name'], field, value))

    def clear_stage(self, rid, field):
        change = self.pending.get(rid)
        if not change:
            return
        change.pop(field, None)
        if not change:
            del self.pending[rid]

    def discard(self):
        self.pending = {}
        self.pending_new = []

    def pending_count(self):
        return len(self.pending) + len(self.pending_new)

    # -- editing -----------------------------------------------------------
    @ui_safe
    def on_beginning_edit(self, sender, e):
        header = safe_str(e.Column.Header)
        col = None
        for c in self.columns:
            if c['header'] == header:
                col = c
                break
        if col is None:
            e.Cancel = True
            return
        try:
            rid = int(e.Row.Item['ElemId'])
        except Exception:
            e.Cancel = True
            return
        row = self.row_by_id(rid)
        if row is None or not self.can_edit(row, col):
            e.Cancel = True
            if row is None:
                return
            if row.get('builtin'):
                reason = 'built in'
            else:
                reason = ('the family does not expose %s as a writable type parameter'
                          % col['header'])
            message = '"%s": %s.' % (row['name'], reason)
            if message != getattr(self, '_last_block', ''):
                self._last_block = message
                self.log(message)

    @ui_safe
    def on_preparing_edit(self, sender, e):
        editor = e.EditingElement
        if isinstance(editor, ComboBox):
            # the click that opened the cell was swallowed to protect the
            # selection, so drop the list down here rather than making the user
            # click a second time
            def drop():
                try:
                    editor.IsDropDownOpen = True
                except Exception:
                    pass
            try:
                self.app.window.Dispatcher.BeginInvoke(
                    DispatcherPriority.Input, Action(drop))
            except Exception:
                pass
            return
        try:
            editor.SelectAll()
            editor.Focus()
        except Exception:
            pass

    @ui_safe
    def on_cell_edit_ending(self, sender, e):
        if e.EditAction != DataGridEditAction.Commit:
            return
        header = safe_str(e.Column.Header)
        col = None
        for c in self.columns:
            if c['header'] == header:
                col = c
                break
        if col is None or not col.get('edit'):
            return
        try:
            editor = e.EditingElement
            if isinstance(editor, ComboBox):
                text = safe_str(editor.SelectedItem if editor.SelectedItem is not None
                                else editor.Text)
            else:
                text = safe_str(editor.Text)
            rid = int(e.Row.Item['ElemId'])
        except Exception:
            return
        self.app.window.Dispatcher.BeginInvoke(
            DispatcherPriority.Background,
            Action(lambda: self.commit_cell(rid, col, text)))

    @ui_safe
    def commit_cell(self, rid, col, text):
        if col['name'] == 'Name' and not safe_str(text).strip():
            self.log('A name cannot be blank.')
            self.refresh_table()
            return

        targets = [rid]
        if col['name'] != 'Name':
            # Ctrl-select a run of rows, change one cell, and the rest follow. Names
            # are excluded because setting the same name on several rows would just
            # auto-number them into nonsense.
            selected = set(r['id'] for r in self.selected_rows())
            if len(selected) < 2 and rid in self.click_selection:
                # the click that opened this cell collapsed the selection
                selected = set(self.click_selection)
            if rid in selected and len(selected) > 1:
                targets = [i for i in selected if self.row_by_id(i) is not None]

        applied = 0
        blocked = 0
        self._batch = len(targets) > 1
        for target in targets:
            row = self.row_by_id(target)
            if row is None:
                continue
            if not self.can_edit(row, col):
                blocked += 1
                continue
            self.stage(target, col['name'], safe_str(text))
            applied += 1

        self._batch = False
        if len(targets) > 1:
            self.log('%s set to "%s" on the %d selected %s(s)%s. Nothing is written '
                     'until APPLY CHANGES.'
                     % (col['header'], safe_str(text), applied, self.thing,
                        ', %d skipped' % blocked if blocked else ''))
        self.refresh_table()

    def begin_cell_edit(self, header):
        item = self.grid.SelectedItem
        if item is None:
            self.log('Select a row first.')
            return
        column = None
        for col in self.grid.Columns:
            if safe_str(col.Header) == header:
                column = col
                break
        if column is None:
            return
        try:
            self.grid.ScrollIntoView(item, column)
            self.grid.CurrentCell = DataGridCellInfo(item, column)
            self.grid.Focus()
            self.grid.BeginEdit()
        except Exception as ex:
            self.log('Could not start editing: %s' % ex)

    @ui_safe
    def on_menu_rename(self, sender, args):
        col = self.column_by_name('Name')
        self.begin_cell_edit(col['header'])

    @ui_safe
    def on_menu_group(self, sender, args):
        item = self.grid.SelectedItem
        if item is None:
            return
        self.select_group(safe_str(item['Group']))

    @ui_safe
    def on_right_click(self, sender, e):
        node = e.OriginalSource
        row = None
        for _ in range(12):
            if node is None:
                break
            if isinstance(node, DataGridRow):
                row = node
                break
            try:
                node = VisualTreeHelper.GetParent(node)
            except Exception:
                break
        if row is None:
            return
        if not row.IsSelected:
            self.grid.SelectedItems.Clear()
            row.IsSelected = True
        try:
            self.mnu_group.IsEnabled = bool(safe_str(row.Item['Group']))
            self.mnu_merge.IsEnabled = self.grid.SelectedItems.Count > 1
        except Exception:
            pass

    @ui_safe
    def on_filter_changed(self, sender, args):
        try:
            if sender is self.find('ChkUnusedOnly') \
                    and self.find('ChkUnusedOnly').IsChecked and self.needs_analysis \
                    and not [r for r in self.rows if r.get('usage') is not None]:
                self.log('Nothing has been analysed yet, so nothing is known to be '
                         'unused. Select some %ss and press Analyze first.' % self.thing)
        except Exception:
            pass
        try:
            if sender is self.find('ChkDupOnly'):
                self.sort_by_group = bool(self.find('ChkDupOnly').IsChecked)
        except Exception:
            pass
        self.apply_view_filter()

    # -- commands ----------------------------------------------------------
    @ui_safe
    def on_refresh(self, sender, args):
        self.changed_ids = set()
        try:
            self.find('ChkChangedOnly').IsChecked = False
        except Exception:
            pass
        self.app.request_reload(self)

    # -- analyze -----------------------------------------------------------
    needs_analysis = False

    @ui_safe
    def on_analyze(self, sender, args):
        if not self.needs_analysis:
            self.log('Usage on this tab is counted on every refresh - nothing to analyse.')
            return
        rows = self.selected_rows()
        if not rows:
            self.log('Select the %ss you want to analyse first. Analysing everything at '
                     'once on a large model takes a long time.' % self.thing)
            return
        self.app.set_busy(True)
        self.log('Analysing %d %s(s)...' % (len(rows), self.thing))
        self.app.queue(lambda uiapp: self._run_analyze(uiapp, list(rows)))

    def _run_analyze(self, uiapp, rows):
        doc = uiapp.ActiveUIDocument.Document
        lines, results = self.analyze(doc, rows)
        self.post_many(lines)
        self.app.window.Dispatcher.Invoke(
            Action(lambda: self.apply_analysis(results)))

    def analyze(self, doc, rows):
        return [], {}

    @ui_safe
    def apply_analysis(self, results):
        for rid, payload in results.items():
            row = self.row_by_id(rid)
            if row is None:
                continue
            count, where = payload
            row['usage'] = count
            row['usage_names'] = where
            row['analysed'] = True
            row['values']['Uses'] = str(count)
            row['values']['Status'] = 'Unused' if not count else 'OK'
            row['status'] = row['values']['Status']
        self.refresh_table()
        self.app.set_busy(False)

    def merge_targets(self):
        """Everything that could be the target of a merge, beyond the selection."""
        return []

    @ui_safe
    def on_dupes(self, sender, args):
        if not self.groups:
            self.log('No duplicates found - every %s in this project is unique.' % self.thing)
            return
        self.sort_by_group = True
        self.find('ChkDupOnly').IsChecked = True
        lines = ['Duplicate groups, matching on %s:'
                 % ', '.join(self.rule_labels(self.active_dup_keys()))]
        for group in self.groups:
            lines.append('  Group %s (%d): %s' % (group['label'], group['count'],
                                                  ', '.join(group['names'])))
        self.log_many(lines)

    @ui_safe
    def on_unused(self, sender, args):
        if self.column_by_name('Uses') is None and self.column_by_name('TotalUses') is None:
            self.log('Usage is not counted on this tab.')
            return
        self.grid.SelectedItems.Clear()
        for item in self.grid.Items:
            try:
                row = self.row_by_id(int(item['ElemId']))
                if row is None or row.get('usage') is None:
                    continue
                if not row['usage']:
                    self.grid.SelectedItems.Add(item)
            except Exception:
                continue
        self.log('Selected %d unused %s(s).' % (self.grid.SelectedItems.Count, self.thing))

    @ui_safe
    def on_rename_key(self, sender, e):
        try:
            if e.Key == System.Windows.Input.Key.Return:
                self.on_mass_rename(sender, e)
        except Exception:
            pass

    @ui_safe
    def on_mass_rename(self, sender, args):
        find_text = safe_str(self.find('FindBox').Text)
        replace_text = safe_str(self.find('ReplaceBox').Text)
        if not find_text:
            self.log('Type the text to find before applying a bulk rename.')
            return
        name_col = self.column_by_name('Name')
        if name_col is None or not name_col.get('edit'):
            self.log('%ss cannot be renamed on this tab.' % self.thing.capitalize())
            return
        rows = self.selected_rows()
        if not rows:
            self.log('Select the %ss you want to rename in the table first.' % self.thing)
            return

        taken = set()
        for row in self.rows:
            change = self.pending.get(row['id'], {})
            taken.add(safe_str(change.get('Name') or row['name']).lower())

        staged = 0
        collisions = 0
        for row in rows:
            if row.get('builtin'):
                self.log('Skipped "%s" - built-in styles cannot be renamed.' % row['name'])
                continue
            change = self.pending.get(row['id'], {})
            current = safe_str(change.get('Name') or row['name'])
            if find_text not in current:
                continue
            wanted = current.replace(find_text, replace_text).strip()
            if not wanted or wanted == current:
                continue
            taken.discard(current.lower())
            final = unique_name_in(wanted, taken)
            taken.add(final.lower())
            if final != wanted:
                collisions += 1
                self.log('"%s" -> "%s" (name "%s" would already be in use)'
                         % (current, final, wanted))
            self.stage(row['id'], 'Name', final)
            staged += 1

        if not staged:
            self.log('None of the %d selected %s(s) contain "%s".'
                     % (len(rows), self.thing, find_text))
            return
        self.refresh_table()
        self.log('Staged %d rename(s)%s. Press APPLY CHANGES to write them.'
                 % (staged, ' (%d auto-numbered to stay unique)' % collisions
                    if collisions else ''))

    # -- merge -------------------------------------------------------------
    def merge_summary(self, row):
        return ', '.join('%s %s' % (c['header'], row['values'].get(c['name'], ''))
                         for c in self.columns[1:4])

    @ui_safe
    def on_merge(self, sender, args):
        if self.app.pending_count():
            self.log('Apply or discard staged changes before merging - a merge deletes '
                     'styles and would strand those edits.')
            return
        rows = [r for r in self.selected_rows() if not r.get('builtin')]
        if len(rows) < 2:
            self.log('Select at least two %ss in the table before merging.' % self.thing)
            return
        dialog = MergeDialog(self.app.window, rows, self.thing,
                             show_overrides=(self.key == 'filters'),
                             summary=self.merge_summary,
                             all_targets=self.merge_targets(),
                             check_groups=self.allow_duplicates)
        result = dialog.show()
        if not result:
            self.log('Merge cancelled.')
            return
        self.app.set_busy(True)
        self.log('Merging %d %s(s)...' % (len(result['drop']), self.thing))
        rows_copy = list(self.rows)
        self.app.queue(lambda uiapp: self._run_merge(uiapp, rows_copy, result))

    def _run_merge(self, uiapp, rows, result):
        doc = uiapp.ActiveUIDocument.Document
        lines = self.merge_impl(doc, rows, result)
        if self.app.settings.get('write_log_files', True):
            path = write_log(lines, 'merge_%s' % self.key)
            if path:
                lines.append('Log written to %s' % path)
        self.post_many(lines)
        self.app.window.Dispatcher.Invoke(Action(self.after_merge))

    @ui_safe
    def after_merge(self):
        # come back with what is left of the duplicates grouped together
        self.sort_by_group = True
        try:
            self.find('ChkDupOnly').IsChecked = True
        except Exception:
            pass
        self.app.request_reload(self, True)

    def merge_impl(self, doc, rows, result):
        raise NotImplementedError

    # -- delete ------------------------------------------------------------
    def impact_lines(self, rows):
        out = []
        for row in rows:
            out.append('%s   (%d use%s)' % (row['name'], row.get('usage', 0),
                                            '' if row.get('usage', 0) == 1 else 's'))
            for name in row.get('usage_names', [])[:25]:
                out.append('      %s' % name)
            if len(row.get('usage_names', [])) > 25:
                out.append('      ... and %d more' % (len(row['usage_names']) - 25))
        return out

    @ui_safe
    def on_delete(self, sender, args):
        if self.app.pending_count():
            self.log('Apply or discard staged changes before deleting.')
            return
        rows = self.selected_rows()
        if not rows:
            self.log('Select the %ss you want to delete first.' % self.thing)
            return
        blocked = [r['name'] for r in rows if not r.get('deletable', True)]
        rows = [r for r in rows if r.get('deletable', True)]
        for name in blocked:
            self.log('"%s" cannot be deleted - it is built in to Revit.' % name)
        if not rows:
            return

        used = [r for r in rows if r.get('usage', 0)]
        total_uses = sum(r.get('usage', 0) for r in rows)
        warning = 'Delete %d %s(s)?' % (len(rows), self.thing)
        if used:
            warning = ('Delete %d %s(s)? %d of them are still in use (%d place%s).'
                       % (len(rows), self.thing, len(used), total_uses,
                          '' if total_uses == 1 else 's'))
        dialog = ConfirmDeleteDialog(
            self.app.window, 'Confirm delete', warning, self.delete_warning,
            self.impact_lines(rows) or ['(nothing is using these)'])
        if not dialog.show():
            self.log('Delete cancelled.')
            return

        ids = [r['id'] for r in rows]
        names = [r['name'] for r in rows]
        self.app.set_busy(True)
        self.log('Deleting %d %s(s)...' % (len(ids), self.thing))
        self.app.queue(lambda uiapp: self._run_delete(uiapp, ids, names))

    def _run_delete(self, uiapp, ids, names):
        name_map = dict(zip(ids, names))
        doc = uiapp.ActiveUIDocument.Document
        trans = DB.Transaction(doc, 'RevoBIM PY - Delete %s' % self.tab_title)
        trans.Start()
        try:
            opts = trans.GetFailureHandlingOptions()
            opts.SetFailuresPreprocessor(WarningSwallower())
            trans.SetFailureHandlingOptions(opts)
        except Exception:
            pass
        try:
            lines, deleted = delete_elements(doc, ids, self.tab_title, name_map)
            trans.Commit()
        except Exception as ex:
            try:
                trans.RollBack()
            except Exception:
                pass
            lines = ['Delete aborted, nothing was removed: %s' % ex]
        lines.insert(0, 'Delete requested for: %s' % ', '.join(names))
        if self.app.settings.get('write_log_files', True):
            path = write_log(lines, 'delete_%s' % self.key)
            if path:
                lines.append('Log written to %s' % path)
        self.post_many(lines)
        self.app.window.Dispatcher.Invoke(Action(lambda: self.app.request_reload(self, True)))

    # -- Excel -------------------------------------------------------------
    def excel_columns(self):
        cols = [c for c in self.columns if c['name'] == 'ElemId']
        cols.extend([c for c in self.columns if c['name'] != 'ElemId'])
        return cols

    @ui_safe
    def on_export(self, sender, args):
        if not self.rows:
            self.log('Nothing to export - refresh first.')
            return
        dialog = SaveFileDialog()
        dialog.Title = 'Export %s to Excel' % self.tab_title
        dialog.Filter = 'Excel Workbook (*.xlsx)|*.xlsx'
        dialog.DefaultExt = '.xlsx'
        stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M')
        base = re.sub(r'[^A-Za-z0-9_\- ]', '', self.app.project_name or 'Project').strip()
        dialog.FileName = '%s_%s_%s.xlsx' % (base or 'Project',
                                             self.sheet_name.replace(' ', ''), stamp)
        last_dir = self.app.settings.get('last_export_dir', '')
        if last_dir and os.path.isdir(last_dir):
            dialog.InitialDirectory = last_dir
        if not dialog.ShowDialog():
            self.log('Export cancelled.')
            return
        path = dialog.FileName
        self.app.set_busy(True)
        self.log('Writing %d row(s) to %s ...' % (len(self.rows), path))
        try:
            values = []
            for row in self.rows:
                item = {}
                for col in self.columns:
                    item[col['name']] = self.display_value(row, col)
                values.append(item)
            export_to_excel(self.excel_columns(), values, path,
                            self.app.project_name, self.sheet_name, self.excel_notes)
            self.app.settings['last_export_dir'] = os.path.dirname(path)
            self.app.settings['last_export_file'] = path
            save_settings(self.app.settings)
            self.log('Export complete. Orange cells are editable, grey cells are read only.')
            PromptDialog(self.app.window, 'Export complete',
                         '%d %s(s) were written to Excel. Edit the orange cells, save, then '
                         'use Import from Excel - the edits are staged in this window and '
                         'nothing reaches the model until you press APPLY CHANGES.'
                         % (len(self.rows), self.thing),
                         detail=path, primary='Open folder location', secondary='Close',
                         open_path=path).show()
        except Exception as ex:
            self.log('Export failed: %s' % ex)
            self.log(traceback.format_exc())
        finally:
            self.app.set_busy(False)

    def diff_records(self, records):
        """Generic diff: stage any changed editable cell. Returns (pending, created, lines)."""
        pending = {}
        lines = []
        matched = 0
        ignored = 0
        id_header = self.column_by_name('ElemId')['header'].strip().lower()
        for rec in records:
            excel_row = rec.get('_excel_row', '?')
            raw = safe_str(rec.get(id_header, '')).strip()
            try:
                rid = int(float(raw))
            except Exception:
                lines.append('Row %s: ignored - unreadable id "%s"' % (excel_row, raw))
                continue
            row = self.row_by_id(rid)
            if row is None:
                lines.append('Row %s: ignored - id %d is not in this model'
                             % (excel_row, rid))
                continue
            change = {}
            for col in self.columns:
                if not col.get('edit'):
                    continue
                value = rec.get(col['header'].strip().lower())
                if value is None or not safe_str(value).strip():
                    continue
                current = safe_str(row['values'].get(col['name'], ''))
                if safe_str(value).strip() == current.strip():
                    continue
                if not self.can_edit(row, col):
                    ignored += 1
                    lines.append('Row %s: %s edit ignored for "%s" - not writable'
                                 % (excel_row, col['header'], row['name']))
                    continue
                change[col['name']] = safe_str(value).strip()
            if change:
                pending[rid] = change
            else:
                matched += 1
        lines.insert(0, '%d %s(s) with pending edits, %d row(s) already matched the model, '
                        '%d edit(s) ignored as not writable.'
                     % (len(pending), self.thing, matched, ignored))
        return pending, [], lines

    def show_import_summary(self, path, pending, created, lines):
        """Say what the workbook changed, before anything is written.

        Counted from this import alone, not from edits already staged by hand.
        """
        changed = len(pending) + len(created)
        cells = sum(len(change) for change in pending.values())
        ignored = len([line for line in lines if 'ignored' in line.lower()])
        if not changed:
            PromptDialog(self.app.window, 'Import checked',
                         'The workbook matches the model - no %ss were changed, so '
                         'there is nothing to apply.' % self.thing,
                         detail=os.path.basename(path), primary='OK',
                         secondary=None).show()
            return

        fields = {}
        for change in pending.values():
            for name in change.keys():
                col = self.column_by_name(name)
                label = col['header'] if col else name
                fields[label] = fields.get(label, 0) + 1
        breakdown = ['%s: %d' % (label, fields[label]) for label in sorted(fields)]
        if created:
            breakdown.append('New %ss to create: %d' % (self.thing, len(created)))
        if ignored:
            breakdown.append('Edits ignored as not writable: %d (listed in the status box)'
                             % ignored)

        body = ('%d %s(s) changed in the workbook - %d setting(s) in all%s.\n\n'
                'They are highlighted in orange and shown on their own. Nothing has '
                'been written to the model: press APPLY CHANGES to write them, or '
                'Discard Changes to drop them.'
                % (changed, self.thing, cells,
                   ', plus %d new' % len(created) if created else ''))
        self.log('Import staged %d %s(s), %d setting(s). Waiting for APPLY CHANGES.'
                 % (changed, self.thing, cells))
        PromptDialog(self.app.window, 'Import ready to review', body,
                     detail='\n'.join(breakdown), primary='Review changes',
                     secondary=None).show()

    @ui_safe
    def on_import(self, sender, args):
        dialog = OpenFileDialog()
        dialog.Title = 'Import edited %s from Excel' % self.tab_title
        dialog.Filter = 'Excel Workbook (*.xlsx;*.xlsm)|*.xlsx;*.xlsm'
        dialog.Multiselect = False
        last_file = self.app.settings.get('last_export_file', '')
        last_dir = self.app.settings.get('last_export_dir', '')
        if last_file and os.path.isfile(last_file):
            dialog.InitialDirectory = os.path.dirname(last_file)
            dialog.FileName = os.path.basename(last_file)
        elif last_dir and os.path.isdir(last_dir):
            dialog.InitialDirectory = last_dir
        if not dialog.ShowDialog():
            self.log('Import cancelled.')
            return
        path = dialog.FileName
        self.app.set_busy(True)
        self.log('Reading %s ...' % path)
        try:
            records, sheet = import_from_excel(path, self.sheet_name)
        except Exception as ex:
            self.log('Could not read the workbook: %s' % ex)
            self.app.set_busy(False)
            return
        if not records:
            self.log('No data rows found on sheet "%s".' % sheet)
            self.app.set_busy(False)
            return
        self.app.settings['last_export_dir'] = os.path.dirname(path)
        self.app.settings['last_export_file'] = path
        save_settings(self.app.settings)

        pending, created, lines = self.diff_records(records)
        for rid, change in pending.items():
            existing = self.pending.get(rid)
            if existing:
                existing.update(change)
            else:
                self.pending[rid] = change
        self.pending_new.extend(created)
        self.log_many(lines)

        # Clear the selection before redrawing: the table puts a selection back
        # after every refresh, and the selection colour paints over the orange
        # that marks a staged row - so a row left selected from before the
        # import would hide that it had changed.
        try:
            self.grid.UnselectAll()
        except Exception:
            pass
        if pending or created:
            self.find('ChkChangedOnly').IsChecked = True
        self.refresh_table()
        try:
            self.grid.UnselectAll()
        except Exception:
            pass
        self.app.set_busy(False)
        self.show_import_summary(path, pending, created, lines)

    # -- Revit hand-off ----------------------------------------------------
    @ui_safe
    def on_edit_in_revit(self, sender, args):
        if self.revit_dialogs is None:
            return
        rows = self.selected_rows()
        if len(rows) != 1:
            self.log('Select a single %s first.' % self.thing)
            return
        if self.app.pending_count():
            self.log('Apply or discard staged changes before editing in Revit.')
            return
        row = rows[0]
        try:
            System.Windows.Clipboard.SetText(row['name'])
        except Exception:
            pass
        commands, captions = self.revit_dialogs
        self.log('Opening Revit and selecting "%s"...' % row['name'])
        self.app.queue(lambda uiapp: self._open_revit(uiapp, row, commands, captions))

    def _open_revit(self, uiapp, row, commands, captions):
        select_in_revit_dialog(captions, row['name'])
        for command in commands:
            try:
                cmd = getattr(UI.PostableCommand, command)
                cmd_id = UI.RevitCommandId.LookupPostableCommandId(cmd)
                if cmd_id is not None and uiapp.CanPostCommand(cmd_id):
                    uiapp.PostCommand(cmd_id)
                    self.post('Revit dialog opened (%s) and "%s" selected where Revit allows '
                              'it. The name is also on the clipboard.' % (command, row['name']))
                    return
            except Exception:
                continue
        self.post('Revit would not accept the command - close any open dialog and try again.')

    # -- model -------------------------------------------------------------
    def read(self, doc, reuse_usage=False):
        raise NotImplementedError

    def write(self, doc, rows, pending, created):
        raise NotImplementedError

    def assign_groups(self, rows):
        """Colour and label the rows.

        Duplicates by the rules the user has ticked where the tab looks for them;
        tabs where "identical settings" is not a useful question group by a
        column instead, or not at all.
        """
        if not self.allow_duplicates and not self.group_column:
            for row in rows:
                row['group'] = ''
                row['chip'] = ''
            return []
        if self.allow_duplicates:
            keys = self.active_dup_keys()
            for row in rows:
                if row.get('dup_eligible') and keys:
                    row['signature'] = build_signature(row, keys, self.dup_scope(row))
                else:
                    row['signature'] = None
            return compute_duplicates(rows, self.registry)
        return self.group_by_column(rows)

    # -- duplicate rules ---------------------------------------------------
    def dup_scope(self, row):
        """A part of the signature the user cannot switch off. Object styles use it
        so subcategories of different parents are never called duplicates -
        Revit could not merge them."""
        return u''

    def default_dup_keys(self):
        return [key for key, _label, ticked in self.dup_rules if ticked]

    def active_dup_keys(self):
        valid = [key for key, _label, _ticked in self.dup_rules]
        try:
            saved = self.app.settings.get('dup_rules', {}).get(self.key)
        except Exception:
            saved = None
        if saved:
            keys = [key for key in valid if key in saved]
            if keys:
                return keys
        return self.default_dup_keys()

    def save_dup_keys(self, keys):
        rules = dict(self.app.settings.get('dup_rules') or {})
        if sorted(keys) == sorted(self.default_dup_keys()):
            rules.pop(self.key, None)
        else:
            rules[self.key] = list(keys)
        self.app.settings['dup_rules'] = rules
        save_settings(self.app.settings)

    def rule_labels(self, keys):
        labels = dict((key, label) for key, label, _ticked in self.dup_rules)
        return [labels.get(key, key) for key in keys]

    @ui_safe
    def on_dup_rules(self, sender, args):
        """Drop the rules menu under the button. Rebuilt each time so it always
        shows what is saved."""
        menu = ContextMenu()
        self.rule_items = []
        active = set(self.active_dup_keys())

        heading = MenuItem()
        heading.Header = 'Count as duplicates when these match:'
        heading.IsEnabled = False
        menu.Items.Add(heading)
        for key, label, _ticked in self.dup_rules:
            item = MenuItem()
            item.Header = label
            item.Tag = key
            item.IsCheckable = True
            item.IsChecked = key in active
            item.StaysOpenOnClick = True
            item.Click += self.on_rule_clicked
            menu.Items.Add(item)
            self.rule_items.append(item)

        menu.Items.Add(Separator())
        for header, handler in (('Tick all', self.on_rules_all),
                                ('Reset to defaults', self.on_rules_default)):
            item = MenuItem()
            item.Header = header
            item.Click += handler
            menu.Items.Add(item)
        note = self.dup_rules_note()
        if note:
            info = MenuItem()
            info.Header = note
            info.IsEnabled = False
            menu.Items.Add(info)

        menu.PlacementTarget = sender
        menu.Placement = WpfPrimitives.PlacementMode.Bottom
        menu.IsOpen = True

    def dup_rules_note(self):
        return ''

    def ticked_rule_keys(self):
        return [safe_str(item.Tag) for item in getattr(self, 'rule_items', [])
                if item.IsChecked]

    @ui_safe
    def on_rule_clicked(self, sender, args):
        keys = self.ticked_rule_keys()
        if not keys:
            sender.IsChecked = True
            self.log('At least one setting has to match, or every %s would be a '
                     'duplicate of every other.' % self.thing)
            return
        self.apply_dup_rules(keys)

    @ui_safe
    def on_rules_all(self, sender, args):
        for item in getattr(self, 'rule_items', []):
            item.IsChecked = True
        self.apply_dup_rules(self.ticked_rule_keys())

    @ui_safe
    def on_rules_default(self, sender, args):
        defaults = set(self.default_dup_keys())
        for item in getattr(self, 'rule_items', []):
            item.IsChecked = safe_str(item.Tag) in defaults
        self.apply_dup_rules(self.default_dup_keys())

    def apply_dup_rules(self, keys):
        """Save the rules and regroup from what is already in memory - no model
        read is needed, so this is instant even on a large tab."""
        self.save_dup_keys(keys)
        self.groups = self.assign_groups(self.rows)
        self.refresh_table()
        dup = sum(g['count'] for g in self.groups)
        self.log('Duplicates now match on: %s. %d duplicate(s) in %d group(s).'
                 % (', '.join(self.rule_labels(self.active_dup_keys())), dup,
                    len(self.groups)))
        try:
            self.app.find('FooterLeft').Text = self.summary_text()
        except Exception:
            pass

    def group_by_column(self, rows):
        """One colour per value of group_column, and a second colour per family so
        both readings are visible at once."""
        buckets = {}
        for row in rows:
            key = safe_str(row['values'].get(self.group_column, '')) or '(none)'
            row['group_key'] = key
            buckets.setdefault(key, []).append(row)

        self.registry.resolve(sorted(u'CAT||%s' % k for k in buckets.keys()))
        family_values = sorted(set(
            safe_str(r['values'].get('FamilyName', '')) for r in rows))
        self.family_registry.resolve([u'FAM||%s' % f for f in family_values if f])

        groups = []
        for key in sorted(buckets.keys(), key=lambda t: t.lower()):
            members = buckets[key]
            label, colour = self.registry.get(u'CAT||%s' % key)
            for member in members:
                member['group'] = label
                family = safe_str(member['values'].get('FamilyName', ''))
                _flabel, fcolour = self.family_registry.get(u'FAM||%s' % family)
                member['chip'] = fcolour or colour
                member['row_colour'] = colour
            groups.append({'label': label, 'colour': colour, 'signature': key,
                           'count': len(members), 'key': key,
                           'members': [m['id'] for m in members],
                           'names': [m['name'] for m in members]})
        return groups

    def populate(self, rows):
        previous = dict((r['id'], r) for r in self.rows
                        if r.get('usage') is not None)
        for row in rows:
            old = previous.get(row['id'])
            if old is not None and row.get('usage') is None:
                row['usage'] = old['usage']
                row['usage_names'] = old.get('usage_names', [])
                row['analysed'] = True
                row['values']['Uses'] = str(old['usage'])
                row['values']['Status'] = 'Unused' if not old['usage'] else 'OK'
                row['status'] = row['values']['Status']
        self.rows = rows
        self.row_index = dict((row['id'], row) for row in rows)
        # A reader marks a row it is willing to compare by giving it any
        # signature; the duplicate rules then build the real one. Rows a reader
        # leaves at None - built-in styles, complex filters - stay out.
        for row in rows:
            row['dup_eligible'] = row.get('signature') is not None
        before = set(self.registry.assigned.keys())
        self.groups = self.assign_groups(rows)
        resolved = len(before - set(self.registry.assigned.keys()))
        if resolved and self.allow_duplicates:
            self.log('%d duplicate group(s) resolved - their colour has been released and '
                     'the remaining groups keep theirs.' % resolved)
        live = set(r['id'] for r in rows)
        for rid in list(self.pending.keys()):
            if rid not in live:
                del self.pending[rid]
        self.refresh_table()

    def summary_text(self):
        dup = sum(g['count'] for g in self.groups)
        analysed = [r for r in self.rows if r.get('usage') is not None]
        unused = len([r for r in analysed if not r['usage']])
        text = '%d %ss  |  %d duplicate(s) in %d group(s)' % (
            len(self.rows), self.thing, dup, len(self.groups))
        if self.needs_analysis and len(analysed) < len(self.rows):
            text += '  |  %d analysed, %d unused' % (len(analysed), unused)
        else:
            text += '  |  %d unused' % unused
        return text


class FilterPanel(BasePanel):
    dup_rules = [('Categories', 'Categories', True),
                 ('Logic', 'AND / OR logic', True),
                 ('Rules', 'Filter rules', True)]
    key = 'filters'
    needs_analysis = False
    tab_title = 'Filters'
    icon_file = 'tab_filters.png'
    thing = 'filter'
    sheet_name = 'Filters'
    revit_dialogs = (['Filters', 'VisibilityGraphics'], ['Filters', 'Edit Filters'])
    delete_warning = ('Deleting a filter removes it from every view and template that uses '
                      'it. The views themselves are not affected.')
    columns = [
        {'header': 'Filter Name', 'name': 'Name', 'width': 240, 'edit': True, 'xl_width': 38},
        {'header': 'Type', 'name': 'Kind', 'width': 70},
        {'header': 'Categories', 'name': 'Categories', 'width': 190, 'edit': True,
         'xl_width': 34, 'wrap': True},
        {'header': 'Logic', 'name': 'Logic', 'width': 55, 'edit': True},
        {'header': 'Rules', 'name': 'Rules', 'width': 330, 'edit': True,
         'xl_width': 62, 'wrap': True},
        {'header': 'Rule Count', 'name': 'RuleCount', 'width': 42, 'type': 'int'},
        {'header': 'Used On Views', 'name': 'ViewUses', 'width': 55, 'type': 'int'},
        {'header': 'Used On Templates', 'name': 'TemplateUses', 'width': 78, 'type': 'int'},
        {'header': 'Via View Template', 'name': 'Inherited', 'width': 60, 'type': 'int'},
        {'header': 'Total Uses', 'name': 'TotalUses', 'width': 55, 'type': 'int'},
        {'header': 'Status', 'name': 'Status', 'width': 120},
        {'header': 'Filter Id', 'name': 'ElemId', 'width': 80},
    ]
    excel_notes = [
        ('Rules format', '[Parameter Name] operator value - one rule per line (Alt+Enter).'),
        ('Operators', 'equals, not equals, contains, does not contain, begins with, '
                      'does not begin with, ends with, does not end with, >, >=, <, <=, '
                      'has value, has no value'),
        ('Numbers', 'Numeric values are in project display units.'),
        ('New filters', 'Leave Filter Id blank or type NEW to create a filter.'),
    ]

    def __init__(self, app):
        BasePanel.__init__(self, app)
        self.usage_cache = None

    def can_edit(self, row, col):
        if not col.get('edit'):
            return False
        if col['name'] == 'Name':
            return True
        return row['kind'] == 'Rules' and not row['complex']

    def read(self, doc, reuse_usage=False):
        usage = self.usage_cache if (reuse_usage and self.usage_cache is not None) else None
        rows, usage = gather_filters(
            doc, bool(self.app.settings.get('include_selection_filters', True)), usage)
        self.usage_cache = usage
        for row in rows:
            row['usage'] = len(row['views']) + len(row['templates'])
            row['usage_names'] = (['[Template] %s' % n for n in row['templates']] +
                                  row['views'])
            row['deletable'] = True
            row['builtin'] = False
            row['values'] = {
                'Name': row['name'],
                'Kind': row['kind'],
                'Categories': u', '.join(row['cat_names']),
                'Logic': row['logic'],
                'Rules': u'   |   '.join(row['rule_texts']),
                'RuleCount': len(row['rule_texts']),
                'ViewUses': len(row['views']),
                'TemplateUses': len(row['templates']),
                'Inherited': len(row['inherited']),
                'TotalUses': row['usage'],
                'Status': row['status'],
                'ElemId': str(row['id']),
            }
        return rows

    def merge_summary(self, row):
        return u'   |   '.join(row['rule_texts'])

    def diff_records(self, records):
        pending, created, lines = diff_excel_records(records, self.rows)
        mapped = {}
        for rid, change in pending.items():
            item = {}
            if change.get('name'):
                item['Name'] = change['name']
            if change.get('cats'):
                item['Categories'] = change['cats']
            if change.get('logic'):
                item['Logic'] = change['logic']
            if change.get('rules'):
                item['Rules'] = safe_str(change['rules']).replace('\r', '\n')\
                    .replace('\n', '   |   ')
            if item:
                mapped[rid] = item
        return mapped, created, lines

    def write(self, doc, rows, pending, created):
        translated = {}
        for rid, change in pending.items():
            item = {}
            if change.get('Name'):
                item['name'] = change['Name']
            if change.get('Categories'):
                item['cats'] = change['Categories']
            if change.get('Logic'):
                item['logic'] = safe_str(change['Logic']).strip().upper()
            if change.get('Rules'):
                item['rules'] = safe_str(change['Rules']).replace('|', '\n')
            translated[rid] = item
        return write_filter_changes(doc, rows, translated, created)

    def merge_impl(self, doc, rows, result):
        return merge_filters(doc, result['keep'], result['drop'],
                             result['overrides'], result['delete'])


class LinePanel(BasePanel):
    dup_rules = [('Weight', 'Line weight', True),
                 ('Colour', 'Line colour', True),
                 ('Pattern', 'Line pattern', True)]
    key = 'lines'
    tab_title = 'Line Styles'
    icon_file = 'tab_lines.png'
    thing = 'line style'
    sheet_name = 'Line Styles'
    revit_dialogs = (['LineStyles'], ['Line Styles'])
    delete_warning = ('Revit deletes every line drawn with a line style when the style '
                      'itself is deleted. Merge them onto another style first if you want '
                      'to keep the geometry.')
    columns = [
        {'header': 'Line Style Name', 'name': 'Name', 'width': 260, 'edit': True,
         'xl_width': 38},
        {'header': 'Weight', 'name': 'Weight', 'width': 70, 'edit': True},
        {'header': 'Colour (R,G,B)', 'name': 'Colour', 'width': 120, 'edit': True},
        {'header': 'Line Pattern', 'name': 'Pattern', 'width': 170, 'edit': True,
         'xl_width': 24},
        {'header': 'Uses', 'name': 'Uses', 'width': 70, 'type': 'int'},
        {'header': 'Status', 'name': 'Status', 'width': 120},
        {'header': 'Line Style Id', 'name': 'ElemId', 'width': 100},
    ]
    excel_notes = [
        ('Weight', 'Line weight is a whole number from 1 to 16.'),
        ('Colour', 'Colour is "R,G,B" with each channel 0-255.'),
        ('Line Pattern', 'Use the exact pattern name as it appears in the project, '
                         'or Solid.'),
        ('Built in styles', 'Revit built-in line styles are read only and cannot be '
                            'deleted.'),
    ]

    def read(self, doc, reuse_usage=False):
        return gather_line_styles(doc)

    def impact_lines(self, rows):
        out = []
        for row in rows:
            out.append('%s   -   %d curve(s) drawn with this style will be deleted'
                       % (row['name'], row.get('usage', 0)))
        return out

    def merge_summary(self, row):
        return 'weight %s, colour %s, pattern %s' % (
            row['values'].get('Weight', '-'), row['values'].get('Colour', '-'),
            row['values'].get('Pattern', '-'))

    def write(self, doc, rows, pending, created):
        return write_line_changes(doc, rows, pending)

    def merge_impl(self, doc, rows, result):
        trans = DB.Transaction(doc, 'RevoBIM PY - Merge Line Styles')
        trans.Start()
        try:
            opts = trans.GetFailureHandlingOptions()
            opts.SetFailuresPreprocessor(WarningSwallower())
            trans.SetFailureHandlingOptions(opts)
        except Exception:
            pass
        try:
            lines, _deleted = merge_line_styles(doc, rows, result['keep'], result['drop'],
                                                result['delete'])
            trans.Commit()
        except Exception as ex:
            try:
                trans.RollBack()
            except Exception:
                pass
            lines = ['Merge aborted, nothing was changed: %s' % ex]
        return lines


class TextPanel(BasePanel):
    dup_rules = [('Font', 'Font', True),
                 ('Size', 'Text size', True),
                 ('Width', 'Width factor', True),
                 ('Bold', 'Bold', True),
                 ('Italic', 'Italic', True),
                 ('Underline', 'Underline', True),
                 ('Colour', 'Colour', True),
                 ('LineWeight', 'Line weight', True),
                 ('Background', 'Background (opaque / transparent)', True),
                 ('ShowBorder', 'Show border', True),
                 ('LeaderOffset', 'Leader / border offset', True),
                 ('TabSize', 'Tab size', True),
                 ('Arrowhead', 'Leader arrowhead', True)]
    key = 'text'
    tab_title = 'Text Styles'
    icon_file = 'tab_text.png'
    thing = 'text style'
    sheet_name = 'Text Styles'
    delete_warning = ('Revit deletes every text note that uses a text style when the style '
                      'itself is deleted. Merge them onto another style first if you want '
                      'to keep the notes.')
    columns = [
        {'header': 'Text Style Name', 'name': 'Name', 'width': 230, 'edit': True,
         'xl_width': 38},
        {'header': 'Font', 'name': 'Font', 'width': 150, 'edit': True, 'xl_width': 24},
        {'header': 'Size', 'name': 'Size', 'width': 80, 'edit': True},
        {'header': 'Width Factor', 'name': 'Width', 'width': 85, 'edit': True},
        {'header': 'Bold', 'name': 'Bold', 'width': 60, 'edit': True, 'choices': True},
        {'header': 'Italic', 'name': 'Italic', 'width': 60, 'edit': True,
         'choices': True},
        {'header': 'Underline', 'name': 'Underline', 'width': 75, 'edit': True,
         'choices': True},
        {'header': 'Colour (R,G,B)', 'name': 'Colour', 'width': 110, 'edit': True},
        {'header': 'Line Weight', 'name': 'LineWeight', 'width': 85, 'edit': True},
        {'header': 'Background', 'name': 'Background', 'width': 105, 'edit': True,
         'choices': True},
        {'header': 'Show Border', 'name': 'ShowBorder', 'width': 90, 'edit': True,
         'choices': True},
        {'header': 'Leader/Border Offset', 'name': 'LeaderOffset', 'width': 130,
         'edit': True},
        {'header': 'Tab Size', 'name': 'TabSize', 'width': 80, 'edit': True},
        {'header': 'Leader Arrowhead', 'name': 'Arrowhead', 'width': 160, 'edit': True,
         'choices': True, 'xl_width': 24},
        {'header': 'Uses', 'name': 'Uses', 'width': 60, 'type': 'int'},
        {'header': 'Status', 'name': 'Status', 'width': 100},
        {'header': 'Text Style Id', 'name': 'ElemId', 'width': 100},
    ]
    excel_notes = [
        ('Size', 'Type the size the way Revit shows it, for example 2.5 mm.'),
        ('Bold / Italic / Underline', 'Yes or No.'),
        ('Width Factor', 'A plain number, for example 0.8.'),
        ('Colour', 'R,G,B with each channel 0-255.'),
        ('Background', 'Opaque or Transparent.'),
        ('Show Border', 'Yes or No.'),
        ('Line Weight', 'A whole number from 1 to 16.'),
        ('Leader Arrowhead', 'The exact arrowhead name from the project, or (none).'),
    ]

    def read(self, doc, reuse_usage=False):
        try:
            self.arrowhead_names = sorted(
                element_name(doc.GetElement(eid))
                for eid in arrowhead_lookup(doc).values())
        except Exception:
            self.arrowhead_names = []
        return gather_text_styles(doc)

    def choices_for(self, name):
        if name in ('Bold', 'Italic', 'Underline', 'ShowBorder'):
            return YES_NO_CHOICES
        if name == 'Background':
            return BACKGROUND_CHOICES
        if name == 'Arrowhead':
            return [NO_VALUE] + [n for n in getattr(self, 'arrowhead_names', []) if n]
        return []

    def can_edit(self, row, col):
        if not col.get('edit'):
            return False
        if col['name'] == 'Name':
            return True
        editable = row.get('editable')
        if editable is None:
            return True
        return col['name'] in editable

    def impact_lines(self, rows):
        out = []
        for row in rows:
            out.append('%s   -   %d text note(s) using this style will be deleted'
                       % (row['name'], row.get('usage', 0)))
        return out

    def merge_summary(self, row):
        return '%s %s, width %s' % (row['values'].get('Font', ''),
                                    row['values'].get('Size', ''),
                                    row['values'].get('Width', ''))

    def write(self, doc, rows, pending, created):
        return write_text_changes(doc, rows, pending)

    def merge_impl(self, doc, rows, result):
        trans = DB.Transaction(doc, 'RevoBIM PY - Merge Text Styles')
        trans.Start()
        try:
            opts = trans.GetFailureHandlingOptions()
            opts.SetFailuresPreprocessor(WarningSwallower())
            trans.SetFailureHandlingOptions(opts)
        except Exception:
            pass
        try:
            lines, _deleted = merge_text_styles(doc, rows, result['keep'], result['drop'],
                                                result['delete'])
            trans.Commit()
        except Exception as ex:
            try:
                trans.RollBack()
            except Exception:
                pass
            lines = ['Merge aborted, nothing was changed: %s' % ex]
        return lines


DIM_FIELDS = [
    ('Font', 'TEXT_FONT', 'string'),
    ('Size', 'TEXT_SIZE', 'valuestring'),
    ('Width', 'TEXT_WIDTH_SCALE', 'double'),
    ('Bold', 'TEXT_STYLE_BOLD', 'bool'),
    ('Italic', 'TEXT_STYLE_ITALIC', 'bool'),
    ('Underline', 'TEXT_STYLE_UNDERLINE', 'bool'),
    ('Units', 'DIM_STYLE_LENGTH_UNITS_FORMAT', 'valuestring'),
    ('TickMark', 'DIM_STYLE_TICK_MARK', 'valuestring'),
    ('LineWeight', 'DIM_STYLE_DIM_LINE_WEIGHT', 'int'),
    ('TickWeight', 'DIM_STYLE_TICK_MARK_PEN', 'int'),
    ('WitnessGap', 'DIM_STYLE_WITNESS_LINE_GAP_TO_ELEMENT', 'valuestring'),
    ('WitnessExt', 'DIM_STYLE_WITNESS_LINE_EXTENSION', 'valuestring'),
    ('TextOffset', 'DIM_STYLE_TEXT_DIST_TO_LINE', 'valuestring'),
    ('Centreline', 'DIM_STYLE_CENTERLINE_SYMBOL', 'valuestring'),
]


class DimensionPanel(BasePanel):
    dup_rules = [('Font', 'Font', True),
                 ('Size', 'Text size', True),
                 ('Width', 'Width factor', True),
                 ('Bold', 'Bold', True),
                 ('Italic', 'Italic', True),
                 ('Underline', 'Underline', True),
                 ('Units', 'Units format', True),
                 ('TickMark', 'Tick mark', True),
                 ('LineWeight', 'Dimension line weight', True),
                 ('TickWeight', 'Tick mark line weight', True),
                 ('WitnessGap', 'Witness line gap', True),
                 ('WitnessExt', 'Witness line extension', True),
                 ('TextOffset', 'Text offset from line', True),
                 ('Centreline', 'Centreline symbol', True)]
    key = 'dimensions'
    tab_title = 'Dimension Styles'
    icon_file = 'tab_dims.png'
    thing = 'dimension style'
    sheet_name = 'Dimension Styles'
    delete_warning = ('Revit deletes every dimension that uses a dimension style when the '
                      'style itself is deleted. Merge them onto another style first if you '
                      'want to keep the dimensions.')
    columns = [
        {'header': 'Dimension Style Name', 'name': 'Name', 'width': 230, 'edit': True,
         'xl_width': 38},
        {'header': 'Font', 'name': 'Font', 'width': 140, 'edit': True, 'xl_width': 22},
        {'header': 'Text Size', 'name': 'Size', 'width': 80, 'edit': True},
        {'header': 'Width Factor', 'name': 'Width', 'width': 80, 'edit': True},
        {'header': 'Bold', 'name': 'Bold', 'width': 55, 'edit': True},
        {'header': 'Italic', 'name': 'Italic', 'width': 55, 'edit': True},
        {'header': 'Underline', 'name': 'Underline', 'width': 70, 'edit': True},
        {'header': 'Units Format', 'name': 'Units', 'width': 120, 'xl_width': 22},
        {'header': 'Tick Mark', 'name': 'TickMark', 'width': 130, 'edit': True,
         'xl_width': 22},
        {'header': 'Line Weight', 'name': 'LineWeight', 'width': 80, 'edit': True},
        {'header': 'Tick Weight', 'name': 'TickWeight', 'width': 80, 'edit': True},
        {'header': 'Witness Gap', 'name': 'WitnessGap', 'width': 90, 'edit': True},
        {'header': 'Witness Extension', 'name': 'WitnessExt', 'width': 100, 'edit': True},
        {'header': 'Text Offset', 'name': 'TextOffset', 'width': 90, 'edit': True},
        {'header': 'Centreline Symbol', 'name': 'Centreline', 'width': 110},
        {'header': 'Uses', 'name': 'Uses', 'width': 60, 'type': 'int'},
        {'header': 'Status', 'name': 'Status', 'width': 90},
        {'header': 'Dimension Style Id', 'name': 'ElemId', 'width': 100},
    ]
    excel_notes = [
        ('Sizes and distances', 'Type them the way Revit shows them, for example 2.5 mm.'),
        ('Bold / Italic / Underline', 'Yes or No.'),
        ('Width Factor', 'A plain number, for example 0.8.'),
        ('Weights', 'Whole numbers 1-16.'),
        ('Units Format', 'Read only here - open the type in Revit to change it.'),
    ]

    def read(self, doc, reuse_usage=False):
        return gather_type_styles(doc, DB.DimensionType, DIM_FIELDS, DB.Dimension)

    def impact_lines(self, rows):
        return ['%s   -   %d dimension(s) using this style will be deleted'
                % (r['name'], r.get('usage', 0)) for r in rows]

    def merge_summary(self, row):
        return '%s %s, tick %s' % (row['values'].get('Font', ''),
                                   row['values'].get('Size', ''),
                                   row['values'].get('TickMark', ''))

    def write(self, doc, rows, pending, created):
        return write_type_changes(doc, rows, pending, DIM_FIELDS)

    def merge_impl(self, doc, rows, result):
        return run_in_transaction(
            doc, 'RevoBIM PY - Merge Dimension Styles',
            lambda: merge_type_styles(doc, rows, result['keep'], result['drop'],
                                      DB.Dimension, 'dimension', result['delete']))


class ObjectStylePanel(BasePanel):
    dup_rules = [('ProjWeight', 'Projection line weight', True),
                 ('CutWeight', 'Cut line weight', True),
                 ('Colour', 'Line colour', True),
                 ('ProjPattern', 'Projection line pattern', True),
                 ('CutPattern', 'Cut line pattern', True),
                 ('Material', 'Material', False)]

    def dup_scope(self, row):
        return safe_str(row.get('parent', '')).lower()

    def dup_rules_note(self):
        return 'Always within the same parent category'
    key = 'objects'
    tab_title = 'Object Styles'
    icon_file = 'tab_objects.png'
    thing = 'object style'
    sheet_name = 'Object Styles'
    revit_dialogs = (['ObjectStyles'], ['Object Styles'])
    needs_analysis = True
    delete_warning = ('Deleting a custom subcategory does NOT delete geometry: the elements '
                      'on it revert to the parent category style, exactly as if you had '
                      'merged them into the parent. The one exception is a subcategory that '
                      'came in with an import, where the imported geometry goes with it.')
    columns = [
        {'header': 'Object Style', 'name': 'FullName', 'width': 250, 'xl_width': 40},
        {'header': 'Name', 'name': 'Name', 'width': 170, 'edit': True, 'xl_width': 28},
        {'header': 'Parent Category', 'name': 'Parent', 'width': 150, 'xl_width': 26},
        {'header': 'Type', 'name': 'Kind', 'width': 130, 'xl_width': 20},
        {'header': 'Projection Weight', 'name': 'ProjWeight', 'width': 90, 'edit': True},
        {'header': 'Cut Weight', 'name': 'CutWeight', 'width': 80, 'edit': True},
        {'header': 'Line Colour (R,G,B)', 'name': 'Colour', 'width': 115, 'edit': True},
        {'header': 'Projection Pattern', 'name': 'ProjPattern', 'width': 135, 'edit': True,
         'xl_width': 22},
        {'header': 'Cut Pattern', 'name': 'CutPattern', 'width': 125, 'edit': True,
         'xl_width': 22},
        {'header': 'Material', 'name': 'Material', 'width': 150, 'edit': True,
         'xl_width': 26},
        {'header': 'Uses', 'name': 'Uses', 'width': 60},
        {'header': 'Status', 'name': 'Status', 'width': 110},
        {'header': 'Category Id', 'name': 'ElemId', 'width': 95},
    ]
    excel_notes = [
        ('Weights', 'Whole numbers 1-16. Blank means inherit from the parent category.'),
        ('Colour', 'Line colour is "R,G,B" with each channel 0-255.'),
        ('Patterns', 'Use the exact line pattern name from the project, or Solid.'),
        ('Material', 'Use the exact material name from the project.'),
        ('Uses', '"?" means not yet analysed, "-" means Revit will not report usage for '
                 'that built-in style.'),
        ('Categories', 'Revit categories and its own built-in subcategories cannot be '
                       'renamed or deleted, but they can be merge targets.'),
    ]

    def read(self, doc, reuse_usage=False):
        return gather_object_styles(doc)

    def analyze(self, doc, rows):
        return analyze_object_styles(doc, self.rows, rows, report=self.post)

    def can_edit(self, row, col):
        if not col.get('edit'):
            return False
        if col['name'] == 'Name':
            return not row.get('builtin')
        return True

    def merge_targets(self):
        """Built-in categories and subcategories are not in the table but are valid
        targets, which is how a stray subcategory is folded back into the standard."""
        selected = self.selected_rows()
        parents = set(r['parent'] for r in selected if not r.get('is_category'))
        if len(parents) != 1:
            return list(self.rows)
        parent = list(parents)[0]
        return [r for r in self.rows
                if r.get('parent') == parent or
                (r.get('is_category') and r['name'] == parent)]

    def impact_lines(self, rows):
        out = []
        for row in rows:
            uses = row.get('usage')
            out.append('%s   -   %s' % (
                row['name'],
                'not analysed, usage unknown' if uses is None
                else '%d element(s) will revert to the "%s" category style'
                     % (uses, row['parent'])))
        return out

    def merge_summary(self, row):
        return 'proj %s / cut %s, colour %s' % (row['values'].get('ProjWeight', '-'),
                                                row['values'].get('CutWeight', '-'),
                                                row['values'].get('Colour', '-'))

    def write(self, doc, rows, pending, created):
        return write_object_style_changes(doc, rows, pending)

    def merge_impl(self, doc, rows, result):
        # No run_in_transaction: EditFamily and LoadFamily refuse to run with a
        # transaction open, so merge_object_styles owns its own.
        lines, _deleted = merge_object_styles(doc, rows, result['keep'], result['drop'],
                                              result['delete'], report=self.post)
        return lines

    @ui_safe
    def on_analyze(self, sender, args):
        rows = [r for r in self.selected_rows() if not r.get('builtin')]
        if not rows:
            self.log('Select the object styles you want to analyse first.')
            return
        if not self.confirm_long_run(
                'Counting what uses %d object style(s) means opening every family of the '
                'parent category, and any family nested inside them.' % len(rows)):
            self.log('Analysis cancelled.')
            return
        self.app.set_busy(True)
        self.log('Analysing %d object style(s)...' % len(rows))
        self.app.queue(lambda uiapp: self._run_analyze(uiapp, list(rows)))

    @ui_safe
    def on_merge(self, sender, args):
        if self.app.pending_count():
            self.log('Apply or discard staged changes before merging.')
            return
        rows = [r for r in self.selected_rows() if not r.get('builtin')]
        if not rows:
            self.log('Select the custom subcategories you want to merge away. Revit '
                     'categories and built-in subcategories can be the target of a merge '
                     'but cannot themselves be merged away.')
            return
        parents = set(r['parent'] for r in rows)
        if len(parents) > 1:
            self.log('Those subcategories belong to different categories (%s). Revit can '
                     'only merge subcategories that share a parent category.'
                     % ', '.join(sorted(p for p in parents if p)))
            return
        if any(r.get('usage') is None for r in rows):
            self.log('Analyze the selected subcategories first, so you can see what will '
                     'move before anything is written.')
            return

        dialog = MergeDialog(self.app.window, rows, self.thing, show_overrides=False,
                             summary=self.merge_summary, all_targets=self.merge_targets())
        result = dialog.show()
        if not result:
            self.log('Merge cancelled.')
            return
        if result['keep'] in [r['id'] for r in rows]:
            drops = [r for r in rows if r['id'] != result['keep']]
        else:
            drops = list(rows)
            result['drop'] = [r['id'] for r in drops]
        if not drops:
            self.log('Nothing to merge - the target is the only style selected.')
            return

        keep_row = self.row_by_id(result['keep'])
        keep_name = keep_row['name'] if keep_row else ''
        moving = sum(r.get('usage') or 0 for r in drops)
        confirm = ConfirmDeleteDialog(
            self.app.window, 'Confirm object style merge',
            'Merging subcategories edits and reloads families.',
            'Subcategory assignment lives inside each family, so every "%s" family - and '
            'any family nested inside them - has to be opened, repointed onto "%s" and '
            'loaded back over itself. About %d element(s) will move. This can take a while '
            'and cannot be undone with a single Ctrl+Z, so save or sync first.'
            % (list(parents)[0], keep_name, moving),
            self.impact_lines(drops), confirm_label='MERGE AND RELOAD FAMILIES')
        if not confirm.show():
            self.log('Merge cancelled.')
            return

        self.app.set_busy(True)
        self.log('Merging %d subcategory(ies) - editing and reloading families...'
                 % len(result['drop']))
        rows_copy = list(self.rows)
        self.app.queue(lambda uiapp: self._run_merge(uiapp, rows_copy, result))

    @ui_safe
    def on_delete(self, sender, args):
        rows = [r for r in self.selected_rows() if not r.get('builtin')]
        if any(r.get('usage') is None for r in rows):
            self.log('Analyze the selected subcategories first, so the confirmation can '
                     'tell you how many elements will revert to the parent style.')
            return
        BasePanel.on_delete(self, sender, args)


class MaterialPanel(BasePanel):
    dup_rules = [('Colour', 'Shading colour', True),
                 ('Transparency', 'Transparency', True),
                 ('SurfacePattern', 'Surface pattern', True),
                 ('SurfaceColour', 'Surface pattern colour', True),
                 ('CutPattern', 'Cut pattern', True),
                 ('CutColour', 'Cut pattern colour', True),
                 ('Shininess', 'Shininess', False),
                 ('Smoothness', 'Smoothness', False),
                 ('Class', 'Material class', False),
                 ('Category', 'Material category', False)]
    key = 'materials'
    tab_title = 'Materials'
    icon_file = 'tab_materials.png'
    thing = 'material'
    sheet_name = 'Materials'
    revit_dialogs = (['Materials'], ['Material Browser', 'Materials'])
    delete_warning = ('Anything painted or built with a deleted material falls back to the '
                      'category material. Merge onto another material first to keep the '
                      'appearance.')
    columns = [
        {'header': 'Material Name', 'name': 'Name', 'width': 230, 'edit': True,
         'xl_width': 40},
        {'header': 'Class', 'name': 'Class', 'width': 120, 'edit': True, 'xl_width': 20},
        {'header': 'Category', 'name': 'Category', 'width': 120, 'edit': True,
         'xl_width': 20},
        {'header': 'Shading Colour (R,G,B)', 'name': 'Colour', 'width': 130, 'edit': True},
        {'header': 'Transparency', 'name': 'Transparency', 'width': 90, 'edit': True},
        {'header': 'Shininess', 'name': 'Shininess', 'width': 80, 'edit': True},
        {'header': 'Smoothness', 'name': 'Smoothness', 'width': 85, 'edit': True},
        {'header': 'Surface Pattern', 'name': 'SurfacePattern', 'width': 140, 'edit': True,
         'xl_width': 22},
        {'header': 'Surface Colour', 'name': 'SurfaceColour', 'width': 110, 'edit': True},
        {'header': 'Cut Pattern', 'name': 'CutPattern', 'width': 140, 'edit': True,
         'xl_width': 22},
        {'header': 'Cut Colour', 'name': 'CutColour', 'width': 110, 'edit': True},
        {'header': 'Uses', 'name': 'Uses', 'width': 60, 'type': 'int'},
        {'header': 'Status', 'name': 'Status', 'width': 90},
        {'header': 'Material Id', 'name': 'ElemId', 'width': 100},
    ]
    excel_notes = [
        ('Colours', 'All colours are "R,G,B" with each channel 0-255.'),
        ('Transparency', '0-100. Shininess is 0-128, Smoothness is 0-100.'),
        ('Patterns', 'Use the exact fill pattern name from the project.'),
        ('Appearance assets', 'Rendering assets are not editable here - use Revit\'s '
                              'Material Browser.'),
    ]

    def read(self, doc, reuse_usage=False):
        return gather_materials(doc)

    def impact_lines(self, rows):
        return ['%s   -   used by %d element(s), which will fall back to their category '
                'material' % (r['name'], r.get('usage', 0)) for r in rows]

    def merge_summary(self, row):
        return 'colour %s, surface %s' % (row['values'].get('Colour', '-'),
                                          row['values'].get('SurfacePattern', '-'))

    def write(self, doc, rows, pending, created):
        return write_material_changes(doc, rows, pending)

    def merge_impl(self, doc, rows, result):
        return run_in_transaction(
            doc, 'RevoBIM PY - Merge Materials',
            lambda: merge_materials(doc, rows, result['keep'], result['drop'],
                                    result['delete']))


class LinePatternPanel(BasePanel):
    dup_rules = [('Segments', 'Dashes, dots and spaces', True)]
    key = 'linepatterns'
    tab_title = 'Line Patterns'
    nav_label = 'Line\nPatterns'
    icon_file = 'tab_linepatterns.png'
    thing = 'line pattern'
    sheet_name = 'Line Patterns'
    revit_dialogs = (['LinePatterns'], ['Line Patterns'])
    delete_warning = ('Anything drawn with a deleted line pattern falls back to a solid '
                      'line. Merge onto another pattern first to keep the appearance.')
    columns = [
        {'header': 'Line Pattern Name', 'name': 'Name', 'width': 260, 'edit': True,
         'xl_width': 40},
        {'header': 'Segments', 'name': 'Segments', 'width': 300, 'xl_width': 46,
         'wrap': True},
        {'header': 'Uses', 'name': 'Uses', 'width': 70, 'type': 'int'},
        {'header': 'Status', 'name': 'Status', 'width': 110},
        {'header': 'Line Pattern Id', 'name': 'ElemId', 'width': 100},
    ]
    excel_notes = [
        ('Segments', 'Read only - segment lengths are edited in Revit.'),
        ('Uses', 'How many categories and subcategories draw with the pattern.'),
    ]

    def read(self, doc, reuse_usage=False):
        return gather_line_patterns(doc)

    def merge_summary(self, row):
        return row['values'].get('Segments', '')

    def write(self, doc, rows, pending, created):
        return write_named_element_changes(doc, rows, pending)

    def merge_impl(self, doc, rows, result):
        lines, _deleted = merge_by_repoint(doc, rows, result['keep'], result['drop'],
                                           'line pattern', result['delete'],
                                           extra=repoint_category_line_patterns)
        return lines


class FilledRegionPanel(BasePanel):
    dup_rules = [('Foreground', 'Foreground pattern', True),
                 ('ForeColour', 'Foreground colour', True),
                 ('Background', 'Background pattern', True),
                 ('BackColour', 'Background colour', True),
                 ('Masking', 'Masking', True),
                 ('Weight', 'Line weight', False),
                 ('Boundary', 'Boundary line style', False)]
    key = 'filledregions'
    tab_title = 'Filled Regions'
    nav_label = 'Filled\nRegions'
    icon_file = 'tab_filledregions.png'
    thing = 'filled region type'
    sheet_name = 'Filled Regions'
    delete_warning = ('Revit deletes every filled region drawn with a type when the type '
                      'itself is deleted. Merge them onto another type first.')
    columns = [
        {'header': 'Filled Region Type', 'name': 'Name', 'width': 230, 'edit': True,
         'xl_width': 38},
        {'header': 'Foreground Pattern', 'name': 'Foreground', 'width': 160,
         'xl_width': 24},
        {'header': 'Foreground Colour', 'name': 'ForeColour', 'width': 115},
        {'header': 'Background Pattern', 'name': 'Background', 'width': 160,
         'xl_width': 24},
        {'header': 'Background Colour', 'name': 'BackColour', 'width': 115},
        {'header': 'Masking', 'name': 'Masking', 'width': 70},
        {'header': 'Line Weight', 'name': 'Weight', 'width': 80},
        {'header': 'Boundary Line Style', 'name': 'Boundary', 'width': 160,
         'xl_width': 24},
        {'header': 'Uses', 'name': 'Uses', 'width': 60, 'type': 'int'},
        {'header': 'Status', 'name': 'Status', 'width': 100},
        {'header': 'Filled Region Id', 'name': 'ElemId', 'width': 100},
    ]
    excel_notes = [
        ('Patterns and colours', 'Read only in this first release - edit them in Revit '
                                 'type properties. Names can be changed here.'),
    ]

    def read(self, doc, reuse_usage=False):
        return gather_filled_regions(doc)

    def merge_summary(self, row):
        return '%s / %s' % (row['values'].get('Foreground', '-'),
                            row['values'].get('Background', '-'))

    def write(self, doc, rows, pending, created):
        return write_named_element_changes(doc, rows, pending)

    def merge_impl(self, doc, rows, result):
        return run_in_transaction(
            doc, 'RevoBIM PY - Merge Filled Regions',
            lambda: merge_type_styles(doc, rows, result['keep'], result['drop'],
                                      DB.FilledRegion, 'filled region', result['delete']))


class FillPatternPanel(BasePanel):
    dup_rules = [('Definition', 'Pattern lines (angle, spacing, dashes)', True),
                 ('Target', 'Drafting or model', True),
                 ('Orientation', 'Orientation in host', True)]
    key = 'fillpatterns'
    tab_title = 'Fill Patterns'
    nav_label = 'Fill\nPatterns'
    icon_file = 'tab_fillpatterns.png'
    thing = 'fill pattern'
    sheet_name = 'Fill Patterns'
    revit_dialogs = (['FillPatterns'], ['Fill Patterns'])
    delete_warning = ('Materials and filled regions using a deleted fill pattern lose it '
                      'and fall back to no pattern. Merge first to keep the appearance.')
    columns = [
        {'header': 'Fill Pattern Name', 'name': 'Name', 'width': 260, 'edit': True,
         'xl_width': 40},
        {'header': 'Target', 'name': 'Target', 'width': 110},
        {'header': 'Orientation', 'name': 'Orientation', 'width': 140, 'xl_width': 22},
        {'header': 'Grid Lines', 'name': 'Grids', 'width': 75, 'type': 'int'},
        {'header': 'Pattern Lines (angle @ spacing mm)', 'name': 'Definition',
         'width': 260, 'xl_width': 46, 'wrap': True},
        {'header': 'Uses', 'name': 'Uses', 'width': 70, 'type': 'int'},
        {'header': 'Status', 'name': 'Status', 'width': 110},
        {'header': 'Fill Pattern Id', 'name': 'ElemId', 'width': 100},
    ]
    excel_notes = [
        ('Uses', 'How many material and filled region slots reference the pattern.'),
        ('Target', 'Drafting patterns scale with the view; model patterns do not.'),
    ]

    def read(self, doc, reuse_usage=False):
        return gather_fill_patterns(doc)

    def merge_summary(self, row):
        return '%s, %s' % (row['values'].get('Target', ''),
                           row['values'].get('Orientation', ''))

    def write(self, doc, rows, pending, created):
        return write_named_element_changes(doc, rows, pending)

    def merge_impl(self, doc, rows, result):
        lines, _deleted = merge_by_repoint(doc, rows, result['keep'], result['drop'],
                                           'fill pattern', result['delete'],
                                           extra=repoint_fill_patterns)
        return lines


class AppearanceAssetPanel(BasePanel):
    dup_rules = [('Settings', 'Every appearance setting', True),
                 ('Schema', 'Asset type', True)]
    dup_extra_keys = ['Settings']
    key = 'assets'
    tab_title = 'Material Appearance Assets'
    nav_label = 'Material\nAppearance Assets'
    icon_file = 'tab_assets.png'
    thing = 'appearance asset'
    sheet_name = 'Appearance Assets'
    delete_warning = ('A material whose appearance asset is deleted loses its rendering '
                      'appearance. Merge onto another asset first.')
    columns = [
        {'header': 'Appearance Asset', 'name': 'Name', 'width': 300, 'edit': True,
         'xl_width': 44},
        {'header': 'Asset Schema', 'name': 'Schema', 'width': 220, 'xl_width': 30},
        {'header': 'Settings Compared', 'name': 'Properties', 'width': 120,
         'type': 'int'},
        {'header': 'Materials Using It', 'name': 'Uses', 'width': 110, 'type': 'int'},
        {'header': 'Status', 'name': 'Status', 'width': 110},
        {'header': 'Asset Id', 'name': 'ElemId', 'width': 100},
    ]
    excel_notes = [
        ('Editing', 'Only the name can be changed here - the asset itself is edited in '
                    "Revit's Material Browser."),
    ]

    def read(self, doc, reuse_usage=False):
        return gather_appearance_assets(doc)

    def merge_summary(self, row):
        return row['values'].get('Schema', '')

    def write(self, doc, rows, pending, created):
        return write_named_element_changes(doc, rows, pending)

    def merge_impl(self, doc, rows, result):
        lines, _deleted = merge_by_repoint(doc, rows, result['keep'], result['drop'],
                                           'appearance asset', result['delete'],
                                           extra=repoint_appearance_assets)
        return lines


class ViewTemplatePanel(BasePanel):
    # nothing on this tab ever produced a duplicate, so the controls for them
    # are hidden rather than left there finding nothing
    allow_duplicates = False
    key = 'viewtemplates'
    tab_title = 'View Templates'
    nav_label = 'View\nTemplates'
    icon_file = 'tab_viewtemplates.png'
    thing = 'view template'
    sheet_name = 'View Templates'
    delete_warning = ('Views driven by a deleted template keep their current settings but '
                      'stop being controlled. No views are deleted.')
    columns = [
        {'header': 'View Template', 'name': 'Name', 'width': 280, 'edit': True,
         'xl_width': 44},
        {'header': 'View Type', 'name': 'ViewType', 'width': 150, 'xl_width': 22},
        {'header': 'Parameters Controlled', 'name': 'Controlled', 'width': 140},
        {'header': 'Views Using It', 'name': 'Uses', 'width': 100, 'type': 'int'},
        {'header': 'Status', 'name': 'Status', 'width': 100},
        {'header': 'Template Id', 'name': 'ElemId', 'width': 100},
    ]
    excel_notes = [
        ('Editing', 'Only the name can be changed here - the settings themselves are '
                    'edited in Revit.'),
        ('Duplicates', 'Templates are not compared for identical settings in this first '
                       'release; the duplicate columns stay blank.'),
    ]

    def read(self, doc, reuse_usage=False):
        return gather_view_templates(doc)

    def merge_summary(self, row):
        return '%s, %s controlled' % (row['values'].get('ViewType', ''),
                                      row['values'].get('Controlled', ''))

    def write(self, doc, rows, pending, created):
        return write_named_element_changes(doc, rows, pending)

    def merge_impl(self, doc, rows, result):
        lines, _deleted = merge_by_repoint(doc, rows, result['keep'], result['drop'],
                                           'view template', result['delete'],
                                           extra=repoint_view_templates,
                                           include_types=False)
        return lines


class ViewportPanel(BasePanel):
    dup_rules = [('ShowTitle', 'Show title', True),
                 ('ShowExtension', 'Show extension line', True),
                 ('LineWeight', 'Line weight', True),
                 ('TitleType', 'Title family', True)]
    key = 'viewports'
    tab_title = 'Viewports'
    nav_label = 'Viewports'
    icon_file = 'tab_viewports.png'
    thing = 'viewport type'
    sheet_name = 'Viewports'
    delete_warning = ('Revit will not delete a viewport type that is still in use. Merge '
                      'the placed views onto another type first.')
    columns = [
        {'header': 'Viewport Type', 'name': 'Name', 'width': 280, 'edit': True,
         'xl_width': 42},
        {'header': 'Show Title', 'name': 'ShowTitle', 'width': 110},
        {'header': 'Show Extension Line', 'name': 'ShowExtension', 'width': 130},
        {'header': 'Line Weight', 'name': 'LineWeight', 'width': 90},
        {'header': 'Title Family', 'name': 'TitleType', 'width': 180, 'xl_width': 26},
        {'header': 'Views Using It', 'name': 'Uses', 'width': 100, 'type': 'int'},
        {'header': 'Status', 'name': 'Status', 'width': 100},
        {'header': 'Viewport Type Id', 'name': 'ElemId', 'width': 100},
    ]
    excel_notes = [
        ('Editing', 'Only the name can be changed here in this first release.'),
    ]

    def read(self, doc, reuse_usage=False):
        return gather_viewports(doc)

    def merge_summary(self, row):
        return 'title %s, %s' % (row['values'].get('ShowTitle', ''),
                                 row['values'].get('TitleType', ''))

    def write(self, doc, rows, pending, created):
        return write_named_element_changes(doc, rows, pending)

    def merge_impl(self, doc, rows, result):
        return run_in_transaction(
            doc, 'RevoBIM PY - Merge Viewport Types',
            lambda: merge_type_styles(doc, rows, result['keep'], result['drop'],
                                      DB.Viewport, 'viewport', result['delete']))


class ScopeBoxPanel(BasePanel):
    # nothing on this tab ever produced a duplicate, so the controls for them
    # are hidden rather than left there finding nothing
    allow_duplicates = False
    key = 'scopeboxes'
    tab_title = 'Scope Boxes'
    nav_label = 'Scope\nBoxes'
    icon_file = 'tab_scopeboxes.png'
    thing = 'scope box'
    sheet_name = 'Scope Boxes'
    delete_warning = ('Views cropped to a deleted scope box lose that crop, and datums '
                      'scoped to it revert to their own extents. No views are deleted.')
    columns = [
        {'header': 'Scope Box Name', 'name': 'Name', 'width': 300, 'edit': True,
         'xl_width': 44},
        {'header': 'Views and Datums Using It', 'name': 'Uses', 'width': 160,
         'type': 'int'},
        {'header': 'Status', 'name': 'Status', 'width': 110},
        {'header': 'Scope Box Id', 'name': 'ElemId', 'width': 100},
    ]
    excel_notes = [
        ('Extents', 'A scope box has no properties beyond its name and its extents, '
                    'which are set by dragging it in a view.'),
    ]

    def read(self, doc, reuse_usage=False):
        return gather_scope_boxes(doc)

    def merge_summary(self, row):
        return '%s use(s)' % row['values'].get('Uses', 0)

    def write(self, doc, rows, pending, created):
        return write_named_element_changes(doc, rows, pending)

    def merge_impl(self, doc, rows, result):
        lines, _deleted = merge_by_repoint(doc, rows, result['keep'], result['drop'],
                                           'scope box', result['delete'])
        return lines


class FontPanel(BasePanel):
    # nothing on this tab ever produced a duplicate, so the controls for them
    # are hidden rather than left there finding nothing
    allow_duplicates = False
    key = 'fonts'
    tab_title = 'Fonts'
    nav_label = 'Fonts'
    icon_file = 'tab_fonts.png'
    thing = 'font'
    sheet_name = 'Fonts'
    delete_warning = ''
    columns = [
        {'header': 'Font', 'name': 'Name', 'width': 300, 'xl_width': 40},
        {'header': 'Text Styles', 'name': 'TextStyles', 'width': 110, 'type': 'int'},
        {'header': 'Dimension Styles', 'name': 'DimStyles', 'width': 130, 'type': 'int'},
        {'header': 'Total Uses', 'name': 'Uses', 'width': 100, 'type': 'int'},
        {'header': 'Status', 'name': 'Status', 'width': 110},
        {'header': 'Row Key', 'name': 'ElemId', 'width': 100},
    ]
    excel_notes = [
        ('Fonts are not elements', 'A font is a piece of text on a style, not something '
                                   'Revit stores as an element, so fonts cannot be renamed '
                                   'or deleted - only merged, which rewrites the styles '
                                   'that use them.'),
    ]

    def read(self, doc, reuse_usage=False):
        return gather_fonts(doc)

    def merge_summary(self, row):
        return '%s text, %s dimension style(s)' % (row['values'].get('TextStyles', 0),
                                                   row['values'].get('DimStyles', 0))

    def write(self, doc, rows, pending, created):
        return [], []

    def merge_impl(self, doc, rows, result):
        lines, _deleted = merge_fonts(doc, rows, result['keep'], result['drop'])
        return lines

    @ui_safe
    def on_delete(self, sender, args):
        self.log('A font is not a Revit element, so there is nothing to delete. Merge it '
                 'into another font instead - that rewrites every text and dimension '
                 'style using it, and the font simply stops being referenced.')


class ArrowheadPanel(BasePanel):
    dup_rules = [('Style', 'Arrow style', True),
                 ('Size', 'Arrow size', True),
                 ('TickSize', 'Tick size', True),
                 ('Filled', 'Filled', True),
                 ('Closed', 'Closed', True),
                 ('Angle', 'Tick angle', True),
                 ('LineWeight', 'Line weight', True)]
    key = 'arrowheads'
    tab_title = 'Arrowheads'
    nav_label = 'Arrowheads'
    icon_file = 'tab_arrowheads.png'
    thing = 'arrowhead'
    sheet_name = 'Arrowheads'
    delete_warning = ('Text, dimension and spot types pointing at a deleted arrowhead fall '
                      'back to another one. Merge first to control which.')
    columns = [
        {'header': 'Arrowhead Name', 'name': 'Name', 'width': 230, 'edit': True,
         'xl_width': 38},
        {'header': 'Arrow Style', 'name': 'Style', 'width': 150, 'edit': True,
         'choices': True, 'xl_width': 22},
        {'header': 'Arrow Size', 'name': 'Size', 'width': 100, 'edit': True},
        {'header': 'Tick Size', 'name': 'TickSize', 'width': 90, 'edit': True},
        {'header': 'Filled', 'name': 'Filled', 'width': 75, 'edit': True,
         'choices': True},
        {'header': 'Closed', 'name': 'Closed', 'width': 75, 'edit': True,
         'choices': True},
        {'header': 'Tick Angle', 'name': 'Angle', 'width': 95, 'edit': True},
        {'header': 'Line Weight', 'name': 'LineWeight', 'width': 90, 'edit': True},
        {'header': 'Types Using It', 'name': 'Uses', 'width': 105, 'type': 'int'},
        {'header': 'Status', 'name': 'Status', 'width': 95},
        {'header': 'Arrowhead Id', 'name': 'ElemId', 'width': 95},
    ]
    excel_notes = [
        ('Arrow Style', 'Use the wording Revit shows, for example "Arrow Filled 30 '
                        'Degree" or "Diagonal Tick Mark".'),
        ('Sizes and angles', 'Type them the way Revit shows them, for example 2.5 mm.'),
        ('Filled / Closed', 'Yes or No.'),
        ('Mass editing', 'In the window, ctrl-select several rows and change one cell - '
                         'every selected row takes the same value.'),
    ]

    def read(self, doc, reuse_usage=False):
        return gather_arrowheads(doc)

    def choices_for(self, name):
        if name in ('Filled', 'Closed'):
            return YES_NO_CHOICES
        if name == 'Style':
            seen = []
            for row in self.rows:
                value = safe_str(row['values'].get('Style', '')).strip()
                if value and value not in seen:
                    seen.append(value)
            return sorted(seen)
        return []

    def can_edit(self, row, col):
        if not col.get('edit'):
            return False
        if col['name'] == 'Name':
            return True
        editable = row.get('editable')
        if editable is None:
            return True
        return col['name'] in editable

    def merge_summary(self, row):
        return '%s, size %s' % (row['values'].get('Style', ''),
                                row['values'].get('Size', ''))

    def write(self, doc, rows, pending, created):
        return write_type_changes(doc, rows, pending, ARROW_FIELDS)

    def merge_impl(self, doc, rows, result):
        lines, _deleted = merge_by_repoint(doc, rows, result['keep'], result['drop'],
                                           'arrowhead', result['delete'])
        return lines


class TagStylePanel(BasePanel):
    key = 'tags'
    tab_title = 'Tag Styles'
    nav_label = 'Tag\nStyles'
    icon_file = 'tab_tags.png'
    thing = 'tag type'
    sheet_name = 'Tag Styles'
    # Two tag types having the same font is not a duplicate worth merging, so the
    # colours group by tagged category and tag family instead.
    allow_duplicates = False
    group_column = 'Category'
    header_rows = True
    delete_warning = ('Revit deletes every tag placed with a type when the type itself is '
                      'deleted. Merge them onto another type first.')
    columns = [
        {'header': 'Tag Family : Type', 'name': 'FullName', 'width': 250, 'xl_width': 42},
        {'header': 'Tagged Category', 'name': 'Category', 'width': 155, 'xl_width': 24},
        {'header': 'Family', 'name': 'FamilyName', 'width': 175, 'xl_width': 28},
        {'header': 'Type Name', 'name': 'Name', 'width': 165, 'edit': True,
         'xl_width': 26},
        {'header': 'Leader Arrowhead', 'name': 'Arrowhead', 'width': 160, 'edit': True,
         'choices': True, 'xl_width': 24},
        {'header': 'Font', 'name': 'Font', 'width': 140, 'edit': True, 'xl_width': 22},
        {'header': 'Text Size', 'name': 'Size', 'width': 90, 'edit': True},
        {'header': 'Width Factor', 'name': 'Width', 'width': 90, 'edit': True},
        {'header': 'Bold', 'name': 'Bold', 'width': 65, 'edit': True, 'choices': True},
        {'header': 'Italic', 'name': 'Italic', 'width': 65, 'edit': True,
         'choices': True},
        {'header': 'Underline', 'name': 'Underline', 'width': 80, 'edit': True,
         'choices': True},
        {'header': 'Colour (R,G,B)', 'name': 'Colour', 'width': 110, 'edit': True},
        {'header': 'Background', 'name': 'Background', 'width': 110, 'edit': True},
        {'header': 'Tags Placed', 'name': 'Uses', 'width': 95, 'type': 'int'},
        {'header': 'Status', 'name': 'Status', 'width': 95},
        {'header': 'Tag Type Id', 'name': 'ElemId', 'width': 95},
    ]
    excel_notes = [
        ('Mass editing', 'In the window, ctrl-select several rows and change one cell - '
                         'every selected row takes the same value.'),
        ('Leader Arrowhead', 'Use the exact arrowhead name from the project.'),
        ('Bold / Italic / Underline', 'Yes or No.'),
        ('Blank cells', 'The tag family does not expose that setting as a type parameter.'),
    ]

    def __init__(self, app):
        BasePanel.__init__(self, app)
        self.arrowhead_names = []

    def read(self, doc, reuse_usage=False):
        try:
            self.arrowhead_names = sorted(
                element_name(doc.GetElement(eid))
                for eid in arrowhead_lookup(doc).values())
        except Exception:
            self.arrowhead_names = []
        return gather_tag_styles(doc, report=self.progress)

    @ui_safe
    def on_refresh(self, sender, args):
        if not self.confirm_long_run(
                'Reading every tag type means walking every annotation element in the '
                'model to count what is placed.'):
            self.log('Refresh cancelled.')
            return
        BasePanel.on_refresh(self, sender, args)

    def choices_for(self, name):
        if name == 'Arrowhead':
            seen = list(getattr(self, 'arrowhead_names', []))
            for row in self.rows:
                value = safe_str(row['values'].get('Arrowhead', '')).strip()
                if value and value != NO_VALUE and value not in seen:
                    seen.append(value)
            return [NO_VALUE] + sorted(v for v in seen if v)
        if name in ('Bold', 'Italic', 'Underline'):
            return YES_NO_CHOICES
        return []

    def can_edit(self, row, col):
        if not col.get('edit'):
            return False
        if col['name'] == 'Name':
            return True
        # Decided from the parameter itself, recorded when the type was read. A
        # blank cell is not the test: a leader arrowhead set to none reads blank
        # and is still perfectly writable.
        editable = row.get('editable')
        if editable is None:
            return True
        return col['name'] in editable

    def merge_summary(self, row):
        return '%s, %s %s' % (row['values'].get('Category', ''),
                              row['values'].get('Font', ''),
                              row['values'].get('Size', ''))

    def build_legend(self):
        panel = self.find('LegendPanel')
        panel.Children.Clear()
        for group in self.groups:
            btn = Button()
            btn.Content = '%s  (%d)' % (group['key'] or '(none)', group['count'])
            btn.Background = brush_from_hex(group['colour'])
            btn.Foreground = brush_from_hex('#1A1A1A')
            btn.BorderThickness = Thickness(0)
            btn.Padding = Thickness(10, 3, 10, 3)
            btn.Margin = Thickness(0, 0, 6, 6)
            btn.FontWeight = System.Windows.FontWeights.Bold
            btn.Cursor = System.Windows.Input.Cursors.Hand
            btn.Tag = group['key']
            btn.ToolTip = '\n'.join(group['names'][:30])
            btn.Click += self.on_category_click
            panel.Children.Add(btn)

    @ui_safe
    def on_category_click(self, sender, args):
        key = safe_str(sender.Tag)
        self.grid.SelectedItems.Clear()
        for item in self.grid.Items:
            try:
                if safe_str(item['RowKind']) == 'header':
                    continue
                if safe_str(item['GroupKey']) == key:
                    self.grid.SelectedItems.Add(item)
            except Exception:
                continue
        self.log('Selected %d tag type(s) in "%s".'
                 % (self.grid.SelectedItems.Count, key or '(none)'))

    def write(self, doc, rows, pending, created):
        return write_tag_changes(doc, rows, pending, report=self.progress)

    def merge_impl(self, doc, rows, result):
        return run_in_transaction(
            doc, 'RevoBIM PY - Merge Tag Types',
            lambda: merge_type_styles(doc, rows, result['keep'], result['drop'],
                                      DB.FamilyInstance, 'tag', result['delete']))


class ParameterPanel(BasePanel):
    key = 'parameters'
    tab_title = 'Parameters'
    nav_label = 'Parameters'
    icon_file = 'tab_parameters.png'
    thing = 'parameter'
    sheet_name = 'Parameters'
    needs_analysis = True
    # Two parameters with the same data type are not duplicates of each other -
    # they hold different values on different elements - so the whole duplicate
    # idea is switched off here rather than offering something meaningless.
    allow_duplicates = False
    delete_warning = ('Deleting a project parameter removes it from every category it is '
                      'bound to, and every value held against it goes with it. Analyze '
                      'first so you can see which ones nothing is using.')
    columns = [
        {'header': 'Parameter Name', 'name': 'Name', 'width': 250, 'edit': True,
         'xl_width': 40},
        {'header': 'Type', 'name': 'Kind', 'width': 90},
        {'header': 'Instance / Type', 'name': 'Binding', 'width': 105},
        {'header': 'Discipline', 'name': 'Discipline', 'width': 120, 'xl_width': 18},
        {'header': 'Type of Parameter', 'name': 'DataType', 'width': 155,
         'xl_width': 24},
        {'header': 'Group Under', 'name': 'ParamGroup', 'width': 165,
         'xl_width': 24},
        {'header': 'Categories', 'name': 'Categories', 'width': 260, 'xl_width': 46,
         'wrap': True},
        {'header': 'Categories Bound', 'name': 'CategoryCount', 'width': 120,
         'type': 'int'},
        {'header': 'Elements With A Value', 'name': 'Uses', 'width': 145},
        {'header': 'GUID', 'name': 'Guid', 'width': 240, 'xl_width': 40},
        {'header': 'Status', 'name': 'Status', 'width': 150},
        {'header': 'Parameter Id', 'name': 'ElemId', 'width': 100},
    ]

    excel_notes = [
        ('The list', 'Read from the project binding table, so non-shared project '
                     'parameters are included as well as shared ones. Anything defined '
                     'but bound to no category is listed too.'),
        ('Elements With A Value', '"?" means not yet analysed. Analyze walks every element '
                                  'of every category the parameter is bound to and counts '
                                  'those actually holding a value.'),
        ('Renaming', 'A shared parameter renamed here is renamed in the project only; the '
                     'shared parameter file is untouched and the GUID does not change.'),
        ('Read only columns', 'Discipline, type of parameter, group and categories are set '
                              "when the parameter is created - change them in Revit's "
                              'Project Parameters dialog.'),
        ('Merging', 'Not offered - moving values from one parameter to another is a data '
                    'migration rather than a style change.'),
    ]

    def read(self, doc, reuse_usage=False):
        return gather_parameters(doc)

    def analyze(self, doc, rows):
        return analyze_parameters(doc, self.rows, rows, report=self.progress)

    @ui_safe
    def apply_analysis(self, results):
        for rid, payload in results.items():
            row = self.row_by_id(rid)
            if row is None:
                continue
            count, where = payload
            row['usage'] = count
            row['usage_names'] = where
            row['analysed'] = True
            row['values']['Uses'] = usage_text(count)
            row['values']['Status'] = 'Used' if count else 'Unused'
            row['status'] = row['values']['Status']
        self.refresh_table()
        self.app.set_busy(False)

    @ui_safe
    def on_analyze(self, sender, args):
        rows = self.selected_rows()
        if not rows:
            self.log('Select the parameters you want to analyse first, or use Select All '
                     'in the table. Every bound category has to be walked element by '
                     'element, so a whole-model sweep is slow.')
            return
        cats = set()
        for row in rows:
            cats |= set(row.get('cat_ids', []))
        if not self.confirm_long_run(
                'Analysing %d parameter(s) means walking every element in %d category(ies) '
                'and reading the value each one holds.' % (len(rows), len(cats))):
            self.log('Analysis cancelled.')
            return
        self.app.set_busy(True)
        self.log('Analysing %d parameter(s)...' % len(rows))
        self.app.queue(lambda uiapp: self._run_analyze(uiapp, list(rows)))

    @ui_safe
    def on_unused(self, sender, args):
        analysed = [r for r in self.rows if r.get('usage') is not None]
        if not analysed:
            self.log('Analyze some parameters first - until then there is no way to know '
                     'which are unused.')
            return
        self.grid.SelectedItems.Clear()
        for item in self.grid.Items:
            try:
                row = self.row_by_id(int(item['ElemId']))
                if row is not None and row.get('usage') == 0:
                    self.grid.SelectedItems.Add(item)
            except Exception:
                continue
        self.log('Selected %d analysed parameter(s) that no element holds a value for.'
                 % self.grid.SelectedItems.Count)

    def impact_lines(self, rows):
        out = []
        for row in rows:
            uses = row.get('usage')
            if uses is None:
                out.append('%s   -   NOT ANALYSED, usage unknown' % row['name'])
            elif uses:
                out.append('%s   -   %d element(s) hold a value that will be lost'
                           % (row['name'], uses))
            else:
                out.append('%s   -   nothing holds a value for it' % row['name'])
        return out

    @ui_safe
    def on_delete(self, sender, args):
        rows = self.selected_rows()
        if not rows:
            self.log('Select the parameters you want to delete first.')
            return
        unknown = [r['name'] for r in rows if r.get('usage') is None]
        if unknown:
            self.log('Analyze these first so you can see what holds a value: %s'
                     % ', '.join(unknown[:6]))
            return
        BasePanel.on_delete(self, sender, args)

    def write(self, doc, rows, pending, created):
        return write_named_element_changes(doc, rows, pending)

    def merge_impl(self, doc, rows, result):
        return ['Merging parameters is not offered.']

    @ui_safe
    def on_merge(self, sender, args):
        self.log('Merging is not offered for parameters. Two parameters with the same '
                 'name hold different values on different elements, so combining them '
                 'means migrating data rather than repointing a style.')


class GlobalParameterPanel(BasePanel):
    # nothing on this tab ever produced a duplicate, so the controls for them
    # are hidden rather than left there finding nothing
    allow_duplicates = False
    key = 'globalparameters'
    tab_title = 'Global Parameters'
    nav_label = 'Global\nParameters'
    icon_file = 'tab_globalparameters.png'
    thing = 'global parameter'
    sheet_name = 'Global Parameters'
    delete_warning = ('Dimensions and parameters driven by a deleted global parameter stop '
                      'being driven and keep their current values.')
    columns = [
        {'header': 'Global Parameter', 'name': 'Name', 'width': 240, 'edit': True,
         'xl_width': 38},
        {'header': 'Data Type', 'name': 'DataType', 'width': 150, 'xl_width': 22},
        {'header': 'Value', 'name': 'Value', 'width': 150, 'xl_width': 22},
        {'header': 'Formula', 'name': 'Formula', 'width': 220, 'xl_width': 34},
        {'header': 'Reporting', 'name': 'Reporting', 'width': 90},
        {'header': 'Driving', 'name': 'Uses', 'width': 90, 'type': 'int'},
        {'header': 'Status', 'name': 'Status', 'width': 100},
        {'header': 'Parameter Id', 'name': 'ElemId', 'width': 100},
    ]
    excel_notes = [
        ('Values and formulas', 'Read only in this first release - edit them in Revit.'),
    ]

    def read(self, doc, reuse_usage=False):
        return gather_global_parameters(doc)

    def merge_summary(self, row):
        return '%s = %s' % (row['values'].get('DataType', ''),
                            row['values'].get('Value', ''))

    def write(self, doc, rows, pending, created):
        return write_named_element_changes(doc, rows, pending)

    def merge_impl(self, doc, rows, result):
        lines, _deleted = merge_by_repoint(doc, rows, result['keep'], result['drop'],
                                           'global parameter', result['delete'])
        return lines


# ---------------------------------------------------------------------------
#  MAIN WINDOW
# ---------------------------------------------------------------------------
# The ribbon, grouped the way Ideate StyleManager groups it. Panels are named
# rather than referenced directly so that one missing class is reported and
# skipped instead of stopping the window from opening at all.
NAV_GROUPS = [
    ['ObjectStylePanel', 'LinePanel', 'LinePatternPanel'],
    ['FilledRegionPanel', 'FillPatternPanel'],
    ['MaterialPanel', 'AppearanceAssetPanel'],
    ['FilterPanel', 'ViewTemplatePanel', 'ViewportPanel', 'ScopeBoxPanel'],
    ['TagStylePanel'],
    ['TextPanel', 'FontPanel'],
    ['DimensionPanel', 'ArrowheadPanel'],
    ['ParameterPanel', 'GlobalParameterPanel'],
]



class StyleManagerWindow(object):
    def __init__(self):
        self.settings = load_settings()
        self.busy = False
        self.project_name = ''

        self.handler = RevoBimHandler()
        self.handler.owner = self
        self.ext_event = ExternalEvent.Create(self.handler)

        self.startup_errors = []
        self.window = parse_xaml('MAIN_XAML', MAIN_XAML)
        apply_window_chrome(self.window)
        self.find('VersionText').Text = 'v%s' % VERSION

        self.find('HeaderBar').MouseLeftButtonDown += self.on_drag
        self.find('BtnClose').Click += self.on_close_click
        self.find('BtnMin').Click += self.on_minimise
        self.find('BtnMax').Click += self.on_maximise
        self.find('BtnApply').Click += self.on_apply
        self.find('BtnDiscard').Click += self.on_discard
        self.window.Closing += self.on_closing
        self.window.Closed += self.on_closed

        # Grouped the way Ideate StyleManager's ribbon groups them, which is also
        # roughly the order these things sit in Revit's own graphic hierarchy.
        self.panels = []
        self.nav_buttons = {}
        self.active = None
        registry = globals()
        groups = []
        for group_names in NAV_GROUPS:
            group = []
            for name in group_names:
                panel_class = registry.get(name)
                if panel_class is None:
                    self.startup_errors.append(
                        '%s is missing from this build and was skipped.' % name)
                    continue
                group.append(panel_class)
            if group:
                groups.append(group)

        nav = self.find('NavBar')

        for group_index, group in enumerate(groups):
            if group_index:
                divider = Border()
                divider.Width = 1
                divider.Background = brush_from_hex('#41474F')
                divider.Margin = Thickness(5, 5, 7, 5)
                nav.Children.Add(divider)
            for panel_class in group:
                try:
                    panel = panel_class(self)
                except Exception as ex:
                    self.startup_errors.append('%s tab could not be built: %s'
                                               % (panel_class.tab_title, ex))
                    self.startup_errors.append(traceback.format_exc())
                    continue
                self.panels.append(panel)
                nav.Children.Add(self.build_nav_button(panel))

        if not self.panels:
            # Every tab failed. The reasons were being collected and then thrown
            # away behind a bare "No tabs could be built", so they go in the
            # message itself.
            detail = '\n'.join(self.startup_errors[:8]) or 'no reason was recorded'
            raise Exception('No tabs could be built.\n\n%s' % detail)
        self.select_panel(self.panels[0])

        self.log('%s - %s v%s  (build %s)' % (BRAND, TOOL_NAME, VERSION, BUILD_DATE))
        self.log('%d tabs across the top. Click a selected row again (or press F2) to '
                 'edit it in place.' % len(self.panels))
        self.log('Nothing is written to the model until you press APPLY CHANGES.')
        self.log_many(self.startup_errors)

    # -- plumbing ----------------------------------------------------------
    def find(self, name):
        return self.window.FindName(name)

    def startup_note(self, message):
        try:
            self.startup_errors.append(safe_str(message))
        except Exception:
            pass

    def show(self):
        self.window.Show()
        # Only the tab on screen is read at startup. Seventeen tabs' worth of
        # collectors on a real model would take far too long to sit through, so the
        # rest are read the first time they are opened.
        first = self.panels[0]
        first.loaded = True
        self.request_reload(first)

    def log(self, message):
        box = self.find('StatusBox')
        stamp = datetime.datetime.now().strftime('%H:%M:%S')
        box.AppendText('[%s] %s\n' % (stamp, safe_str(message)))
        box.ScrollToEnd()

    def post(self, message):
        try:
            self.window.Dispatcher.Invoke(Action(lambda: self.log(message)))
        except Exception:
            pass

    def log_many(self, lines):
        """Write a block of lines in one go. One AppendText and one scroll, rather
        than one of each per line - a merge report of a few hundred lines used to
        repaint the status box a few hundred times."""
        if not lines:
            return
        box = self.find('StatusBox')
        stamp = datetime.datetime.now().strftime('%H:%M:%S')
        box.AppendText(''.join('[%s] %s\n' % (stamp, safe_str(line)) for line in lines))
        box.ScrollToEnd()

    def post_many(self, lines):
        """log_many from the Revit thread: one hop to the UI thread for the whole
        block instead of a blocking Dispatcher.Invoke per line."""
        lines = list(lines or [])
        if not lines:
            return
        try:
            self.window.Dispatcher.Invoke(Action(lambda: self.log_many(lines)))
        except Exception:
            pass

    def set_progress(self, done, total, text=''):
        """Show the progress band. done/total of 0 hides it again."""
        try:
            panel = self.find('ProgressPanel')
            if not total:
                panel.Visibility = Visibility.Collapsed
                return
            percent = int(round(100.0 * max(0, min(done, total)) / float(total)))
            panel.Visibility = Visibility.Visible
            self.find('ProgressBarCtl').Value = percent
            self.find('ProgressPercent').Text = '%d%%' % percent
            self.find('ProgressText').Text = safe_str(text)
        except Exception:
            pass

    def post_progress(self, done, total, text=''):
        """Progress from the Revit worker thread."""
        try:
            self.window.Dispatcher.Invoke(
                Action(lambda: self.set_progress(done, total, text)))
        except Exception:
            pass

    def confirm_long_run(self, what):
        """The standing warning before anything that opens or rewrites families."""
        return PromptDialog(
            self.window, 'This could take some time',
            'This could take some time, suggest syncing before running this command.',
            what, primary='Continue', secondary='Cancel').show()

    def post_busy(self, state):
        try:
            self.window.Dispatcher.Invoke(Action(lambda: self.set_busy(state)))
        except Exception:
            pass

    def set_busy(self, state):
        self.busy = state
        if not state:
            try:
                self.set_progress(0, 0)
            except Exception:
                pass
        try:
            self.find('BtnApply').IsEnabled = (not state) and self.pending_count() > 0
            self.find('BtnDiscard').IsEnabled = (not state) and self.pending_count() > 0
        except Exception:
            pass
        for panel in getattr(self, 'panels', []):
            try:
                panel.update_merge_groups_button()
            except Exception:
                pass
            for name in ('BtnRefresh', 'BtnAnalyze', 'BtnDupes', 'BtnDupRules',
                         'BtnMerge', 'BtnDelete',
                         'BtnExcel', 'BtnUnused', 'BtnRevit', 'BtnRenameApply'):
                try:
                    panel.find(name).IsEnabled = not state
                except Exception:
                    pass

    def queue(self, fn):
        self.handler.enqueue(fn)
        self.ext_event.Raise()

    def build_nav_button(self, panel):
        """One ribbon button: icon on the left, label on the right, two lines where
        the name is long. RadioButtons rather than plain buttons, so only one can
        be lit at a time without any bookkeeping."""
        button = RadioButton()
        try:
            button.Style = self.window.FindResource('NavBtn')
        except Exception:
            pass
        button.GroupName = 'StyleManagerNav'
        button.Tag = panel.key

        content = StackPanel()
        content.Orientation = Orientation.Horizontal
        icon = load_icon(panel.icon_file)
        if icon is not None:
            image = Image()
            image.Source = icon
            image.Width = 26
            image.Height = 26
            image.Margin = Thickness(0, 0, 7, 0)
            image.VerticalAlignment = System.Windows.VerticalAlignment.Center
            content.Children.Add(image)
        label = TextBlock()
        label.Text = getattr(panel, 'nav_label', None) or panel.tab_title
        label.FontSize = 12
        label.LineHeight = 14
        label.VerticalAlignment = System.Windows.VerticalAlignment.Center
        content.Children.Add(label)
        button.Content = content
        button.ToolTip = panel.tab_title
        button.Checked += self.on_nav_checked
        self.nav_buttons[panel.key] = button
        return button

    @ui_safe
    def on_nav_checked(self, sender, args):
        key = safe_str(sender.Tag)
        for panel in self.panels:
            if panel.key == key:
                self.show_panel(panel)
                return

    def select_panel(self, panel):
        button = self.nav_buttons.get(panel.key)
        if button is not None and not button.IsChecked:
            button.IsChecked = True      # raises Checked, which shows the panel
        else:
            self.show_panel(panel)

    @ui_safe
    def show_panel(self, panel):
        self.active = panel
        self.find('TabHost').Content = panel.root
        self.find('FooterLeft').Text = panel.summary_text()
        if not panel.loaded:
            panel.loaded = True
            self.request_reload(panel)

    def current_panel(self):
        return self.active or (self.panels[0] if self.panels else None)

    def pending_count(self):
        return sum(p.pending_count() for p in getattr(self, 'panels', []))

    # -- chrome ------------------------------------------------------------
    @ui_safe
    def on_drag(self, sender, args):
        try:
            self.window.DragMove()
        except Exception:
            pass

    @ui_safe
    def on_minimise(self, sender, args):
        self.window.WindowState = WindowState.Minimized

    @ui_safe
    def on_maximise(self, sender, args):
        self.window.WindowState = WindowState.Normal \
            if self.window.WindowState == WindowState.Maximized else WindowState.Maximized

    @ui_safe
    def on_close_click(self, sender, args):
        self.window.Close()

    @ui_safe
    def on_closing(self, sender, e):
        if not self.pending_count():
            return
        dialog = PromptDialog(
            self.window, 'Unapplied changes',
            '%d staged change(s) have not been written to the model. Close anyway?'
            % self.pending_count(), '',
            primary='Discard and close', secondary='Keep editing')
        if not dialog.show():
            e.Cancel = True

    @ui_safe
    def on_closed(self, sender, args):
        save_settings(self.settings)
        try:
            AppDomain.CurrentDomain.SetData(WINDOW_KEY, None)
        except Exception:
            pass
        try:
            self.ext_event.Dispose()
        except Exception:
            pass

    # -- reload ------------------------------------------------------------
    def request_reload(self, panel=None, reuse_usage=False, panels=None):
        self.set_busy(True)
        if panels:
            targets = list(panels)
        elif panel is not None:
            targets = [panel]
        else:
            targets = [p for p in self.panels if p.loaded]
        if not targets:
            targets = [self.current_panel()]
        self.log('Reading %s from the model...'
                 % ', '.join(p.tab_title.lower() for p in targets))
        self.queue(lambda uiapp: self._read(uiapp, targets, reuse_usage))

    def _read(self, uiapp, targets, reuse_usage):
        doc = uiapp.ActiveUIDocument.Document
        results = []
        for index, panel in enumerate(targets):
            self.post_progress(index, len(targets),
                               'Reading %s...' % panel.tab_title.lower())
            try:
                results.append((panel, panel.read(doc, reuse_usage)))
            except Exception as ex:
                self.post('Could not read %s: %s' % (panel.tab_title, ex))
                self.post(traceback.format_exc())
                results.append((panel, []))
        self.post_progress(len(targets), len(targets), 'Building the tables...')
        try:
            project_name = doc.Title
        except Exception:
            project_name = ''
        self.window.Dispatcher.Invoke(
            Action(lambda: self._populate(results, project_name)))

    @ui_safe
    def _populate(self, results, project_name):
        self.project_name = project_name
        for panel, rows in results:
            panel.populate(rows)
            self.log('%s: %s' % (panel.tab_title, panel.summary_text()))
        current = self.current_panel()
        if current is not None:
            self.find('FooterLeft').Text = current.summary_text()
        self.find('FooterRight').Text = '%s  |  %s v%s' % (project_name, TOOL_NAME, VERSION)
        self.set_busy(False)

    # -- pending -----------------------------------------------------------
    @ui_safe
    def update_pending_ui(self):
        count = self.pending_count()
        apply_btn = self.find('BtnApply')
        apply_btn.IsEnabled = count > 0 and not self.busy
        self.find('BtnDiscard').IsEnabled = count > 0 and not self.busy
        apply_btn.Content = 'APPLY CHANGES' if not count else 'APPLY %d CHANGE%s' % (
            count, '' if count == 1 else 'S')
        if count:
            parts = []
            for panel in self.panels:
                if panel.pending_count():
                    parts.append('%d %s' % (panel.pending_count(), panel.tab_title.lower()))
            self.find('PendingText').Text = 'Staged: %s' % ', '.join(parts)
            self.find('PendingText').Foreground = brush_from_hex(ORANGE)
            self.find('PendingHint').Text = ('Nothing has been written to the model yet. '
                                             'APPLY commits every tab in one transaction.')
        else:
            self.find('PendingText').Text = 'No pending changes'
            self.find('PendingText').Foreground = brush_from_hex('#8A9099')
            self.find('PendingHint').Text = ('Edits on every tab are held in the table until '
                                             'you apply them.')

    @ui_safe
    def on_discard(self, sender, args):
        count = self.pending_count()
        if not count:
            return
        for panel in self.panels:
            panel.discard()
            panel.refresh_table()
        self.log('Discarded %d staged change(s). The model was never touched.' % count)

    @ui_safe
    def on_apply(self, sender, args):
        count = self.pending_count()
        if not count:
            self.log('There is nothing staged to apply.')
            return
        if count >= 150 and not self.confirm_long_run(
                '%d staged change(s) will be written in one transaction.' % count):
            self.log('Apply cancelled - your changes are still staged.')
            return
        self.set_busy(True)
        self.log('Applying %d staged change(s) in one transaction...' % count)
        snapshot = []
        for panel in self.panels:
            if panel.pending_count():
                snapshot.append((panel, list(panel.rows),
                                 dict((k, dict(v)) for k, v in panel.pending.items()),
                                 list(panel.pending_new)))
        self.queue(lambda uiapp: self._do_apply(uiapp, snapshot))

    def _do_apply(self, uiapp, snapshot):
        doc = uiapp.ActiveUIDocument.Document
        started = datetime.datetime.now()
        all_lines = []
        results = []

        trans = DB.Transaction(doc, 'RevoBIM PY - Apply Style Changes')
        trans.Start()
        try:
            opts = trans.GetFailureHandlingOptions()
            opts.SetFailuresPreprocessor(WarningSwallower())
            opts.SetClearAfterRollback(True)
            trans.SetFailureHandlingOptions(opts)
        except Exception:
            pass
        try:
            for index, (panel, rows, pending, created) in enumerate(snapshot):
                self.post_progress(index, len(snapshot),
                                   'Writing %s...' % panel.tab_title.lower())
                lines, changed = panel.write(doc, rows, pending, created)
                all_lines.append('--- %s ---' % panel.tab_title)
                all_lines.extend(lines)
                results.append((panel, set(changed)))
            trans.Commit()
        except Exception as ex:
            try:
                trans.RollBack()
            except Exception:
                pass
            self.post('Apply aborted, nothing was written: %s' % ex)
            self.post(traceback.format_exc())
            self.post_busy(False)
            return

        elapsed = (datetime.datetime.now() - started).total_seconds()
        all_lines.insert(0, 'Committed in %.1f second(s).' % elapsed)
        if self.settings.get('write_log_files', True):
            path = write_log(all_lines, 'apply')
            if path:
                all_lines.append('Log written to %s' % path)
        for panel, changed in results:
            panel.changed_ids = changed
            panel.pending = {}
            panel.pending_new = []
        self.written_panels = [panel for panel, _changed in results]
        self.post_many(all_lines)
        self.window.Dispatcher.Invoke(Action(self.after_apply))

    @ui_safe
    def after_apply(self):
        # Only the tabs that were written are read back. Re-reading every opened
        # tab after renaming three line styles used to re-read materials, filters
        # and parameters too. Names, rules and formatting cannot change where a
        # style is used, so the cached usage sweep is reused as well.
        written = getattr(self, 'written_panels', None) or None
        self.request_reload(None, True, panels=written)


# ---------------------------------------------------------------------------
#  ENTRY POINT
# ---------------------------------------------------------------------------
def main():
    try:
        existing = AppDomain.CurrentDomain.GetData(WINDOW_KEY)
    except Exception:
        existing = None
    if existing is not None:
        try:
            existing.Activate()
            existing.Focus()
            return
        except Exception:
            try:
                AppDomain.CurrentDomain.SetData(WINDOW_KEY, None)
            except Exception:
                pass

    doc = UIAPP.ActiveUIDocument.Document if UIAPP.ActiveUIDocument else None
    if doc is None or doc.IsFamilyDocument:
        out = script.get_output()
        out.print_md('**%s - %s**: open a project document first.' % (BRAND, TOOL_NAME))
        return

    tool = StyleManagerWindow()
    try:
        AppDomain.CurrentDomain.SetData(WINDOW_KEY, tool.window)
    except Exception:
        pass
    tool.show()


try:
    main()
except Exception:
    DETAIL = traceback.format_exc()
    LOG_PATH = None
    try:
        LOG_PATH = write_log(DETAIL.replace('\r', '').split('\n'), 'startup_error')
    except Exception:
        LOG_PATH = None
    try:
        OUT = script.get_output()
        OUT.print_md('## %s - %s v%s could not start' % (BRAND, TOOL_NAME, VERSION))
        OUT.print_md('Please send this text back so it can be fixed:')
        OUT.print_md('```\n%s\n```' % DETAIL)
        if LOG_PATH:
            OUT.print_md('A copy was saved to `%s`' % LOG_PATH)
    except Exception:
        raise


