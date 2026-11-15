# -*- coding: utf-8 -*-
"""Excel for Revit — edit the selected schedule in a spreadsheet grid.

Opens the schedule that is active or selected in the Project Browser as an
editable grid.  Type parameter cells are orange, instance parameter cells are
blue, read-only cells are grey.  Nothing is written to the model until APPLY.

Runs on Revit 2024 - 2027 (IronPython 2.7 and IronPython 3).
"""

__version__ = "1.20.0"
__doc__ = "Edit the selected schedule in a spreadsheet grid, then apply in one transaction."

import os
import time
import sys
import json
import re
import traceback

# pyRevit first
from pyrevit import revit                                    # noqa: E402

import clr                                                   # noqa: E402

# Every namespace this module imports from has to have its assembly referenced
# here first, or the import throws "Cannot import name X" at load and the tool
# opens as a blank white window.  An assembly being loaded in the process is
# not enough: IronPython only exposes namespaces from assemblies referenced
# into its runtime, so one that happens to be pulled in as a dependency of
# another works until the day it does not.  The list is deliberately long and
# covers both .NET Framework 4.8 (Revit 2024) and .NET 8 (Revit 2025+), which
# split the same namespaces across different assemblies — `System.dll` holds
# ListSortDirection on 4.8, `System.ObjectModel.dll` holds it on .NET 8.
# Each is requested on its own so a name that does not exist on a given
# release is skipped rather than taking the rest of the list with it.
# import_check.py's `assemblies_referenced` rule keeps this honest.
for _asm in ('mscorlib', 'System', 'System.Runtime', 'System.Core',
             'RevitAPI', 'RevitAPIUI', 'AdWindows',
             'PresentationCore', 'PresentationFramework', 'WindowsBase',
             'System.Xaml', 'System.Xml', 'System.Drawing',
             'System.Windows.Forms', 'WindowsFormsIntegration',
             'System.Data', 'System.Data.Common',
             'System.ObjectModel', 'System.ComponentModel',
             'System.ComponentModel.Primitives',
             'System.ComponentModel.TypeConverter',
             'System.Diagnostics.Process',
             'System.IO.Compression', 'System.IO.Compression.FileSystem'):
    try:
        clr.AddReference(_asm)
    except Exception:
        pass

from Autodesk.Revit import DB                                 # noqa: E402
from Autodesk.Revit import UI                                 # noqa: E402

import System                                                 # noqa: E402
from System import Action                                     # noqa: E402
from System import TimeSpan                                   # noqa: E402
from System.Data import DataTable                             # noqa: E402
from System.Data import DataView                              # noqa: E402
from System.ComponentModel import ListSortDirection           # noqa: E402
from System.IO import File, FileStream, FileMode, FileAccess, MemoryStream   # noqa: E402

from System.Windows import Window                             # noqa: E402
from System.Windows import Thickness                          # noqa: E402
from System.Windows import GridLength                         # noqa: E402
from System.Windows import GridUnitType                       # noqa: E402
from System.Windows import HorizontalAlignment                # noqa: E402
from System.Windows import VerticalAlignment                  # noqa: E402
from System.Windows import Visibility                         # noqa: E402
from System.Windows import FontWeights                        # noqa: E402
from System.Windows import WindowStyle                        # noqa: E402
from System.Windows import WindowStartupLocation              # noqa: E402
from System.Windows import ResizeMode                         # noqa: E402
from System.Windows import SizeToContent                      # noqa: E402
from System.Windows import Point                              # noqa: E402
from System.Windows import CornerRadius                       # noqa: E402
from System.Windows import Clipboard                          # noqa: E402
from System.Windows import TextWrapping                       # noqa: E402
from System.Windows import Duration                           # noqa: E402

from System.Windows.Controls import Grid as WGrid             # noqa: E402
from System.Windows.Controls import RowDefinition             # noqa: E402
from System.Windows.Controls import ColumnDefinition          # noqa: E402
from System.Windows.Controls import StackPanel                # noqa: E402
from System.Windows.Controls import WrapPanel                 # noqa: E402
from System.Windows.Controls import Border                    # noqa: E402
from System.Windows.Controls import TextBlock                 # noqa: E402
from System.Windows.Controls import TextBox                   # noqa: E402
from System.Windows.Documents import Run                      # noqa: E402
from System.Windows import TextTrimming                       # noqa: E402
from System.Windows.Controls import Button                    # noqa: E402
from System.Windows.Controls import CheckBox                  # noqa: E402
from System.Windows.Controls import RadioButton               # noqa: E402
from System.Windows.Controls import ContextMenu                # noqa: E402
from System.Windows.Controls import MenuItem                   # noqa: E402
from System.Windows.Controls import Separator                  # noqa: E402
from System.Windows.Controls import ListBox                   # noqa: E402
from System.Windows.Controls import ListBoxItem               # noqa: E402
from System.Windows.Controls import ScrollViewer              # noqa: E402
from System.Windows.Controls import ScrollBarVisibility       # noqa: E402
from System.Windows.Controls import Orientation               # noqa: E402
from System.Windows import SystemParameters                   # noqa: E402
from System.Windows import PresentationSource                 # noqa: E402
from System.Windows.Input import Cursors                      # noqa: E402
from System.Windows.Input import MouseButtonState             # noqa: E402
from System.Windows.Input import Mouse                        # noqa: E402
from System.Windows.Controls import Canvas                    # noqa: E402
from System.Windows.Controls import Image                     # noqa: E402
from System.Windows.Controls import DataGrid                  # noqa: E402
from System.Windows.Controls import DataGridTextColumn        # noqa: E402
from System.Windows.Controls import DataGridLength            # noqa: E402
from System.Windows.Controls import DataGridLengthUnitType    # noqa: E402
from System.Windows.Controls import DataGridRow               # noqa: E402
from System.Windows.Controls import DataGridEditAction            # noqa: E402
from System.Windows.Controls import DataGridCellInfo          # noqa: E402
from System.Windows.Controls import DataGridCell              # noqa: E402
from System.Windows.Controls.Primitives import DataGridColumnHeader  # noqa: E402
from System.Windows.Controls.Primitives import PlacementMode  # noqa: E402

from System.Windows.Media import SolidColorBrush              # noqa: E402
from System.Windows.Media import ColorConverter               # noqa: E402
from System.Windows.Media import VisualTreeHelper             # noqa: E402
from System.Windows.Media.Imaging import BitmapImage          # noqa: E402
from System.Windows.Media.Imaging import BitmapCacheOption    # noqa: E402
from System.Windows.Media.Animation import DoubleAnimation    # noqa: E402
from System.Windows.Media.Animation import CubicEase          # noqa: E402
from System.Windows.Media.Animation import EasingMode         # noqa: E402
from System.Windows.Media.Animation import FillBehavior       # noqa: E402
from System.Windows.Markup import XamlReader                  # noqa: E402
from System.Windows.Data import Binding                       # noqa: E402
from System.Windows.Input import Key                          # noqa: E402
from System.Windows.Input import ModifierKeys                 # noqa: E402
from System.Windows.Input import Keyboard                     # noqa: E402

SCRIPT_DIR = os.path.dirname(__file__)
if SCRIPT_DIR and SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

# the Excel layer is a separate module so its rules can be bench-tested off Revit
EXCEL_ERROR = ''
try:
    import excel_bridge
    import xlsx_io
except Exception:
    excel_bridge = None
    xlsx_io = None
    EXCEL_ERROR = traceback.format_exc()
XAML_PATH = os.path.join(SCRIPT_DIR, 'ExcelForRevit.xaml')
ICON_PATH = os.path.join(SCRIPT_DIR, 'icon.png')

# ---------------------------------------------------------------- palette ----
#
# Two themes with identical keys.  set_theme() writes the chosen one into module
# globals, so every C_* reference below picks the new value up on its next call
# — which is why nothing reads a colour at import time.

# Dark follows Revit's own dark UI (2024 and later), as the shared RevoBIM
# "Revit dark" palette in the theme reference — the same values Project Browser
# Pro, Filter Manager and Pro Sheets Exporter use, so the tools match each
# other as well as Revit: #3C4454 body, #222933 title bar, #1B1F24 toolbar,
# #2D3441 fields, #323C48 headings, #444E5E hover, #3A7392 selection, #EEF0F4
# text, with muted text and blue lifted for the lighter body.  Two additions of
# this tool's own: red is lifted to #FA8880 so read-only column names stay
# readable on the headings, and the cell-state washes are lifted so each stands
# clearly off the field rather than relying on hue alone.
DARK_THEME = {
    'C_WINDOW': '#3C4454',
    'C_CARD': '#1B1F24',
    'C_FIELD': '#2D3441',
    'C_BAR': '#222933',
    'C_EDGE': '#4A5364',
    'C_EDGE_SOFT': '#515C6B',
    'C_TEXT': '#EEF0F4',
    'C_MUTED': '#A4AAB1',
    'C_BLUE': '#5AAEEB',
    'C_ORANGE': '#E8912D',
    'C_GREEN': '#3FA75A',
    'C_GREEN_HI': '#4EC06D',
    'C_RED': '#FA8880',
    'C_SEL': '#3A7392',
    'C_SEL_FG': '#FFFFFF',
    'C_TYPE_BG': '#5E4018',
    'C_TYPE_FG': '#F7C384',
    'C_INST_BG': '#24527A',
    'C_INST_FG': '#B2DBF8',
    'C_RO_BG': '#5E3639',
    'C_RO_FG': '#F2B9B6',
    'C_EDIT_BG': '#2E6040',
    'C_EDIT_FG': '#93EBB0',
    'C_FAIL_BG': '#A3302B',
    'C_FAIL_FG': '#FFECEA',
    'C_TEST_BG': '#493C68',
    'C_TEST_FG': '#D3C6F7',
    'C_IMP_BG': '#165A62',
    'C_IMP_FG': '#93E7EF',
    'C_CLEAR': '#00000000',
    'C_COPY_BG': '#585020',
    'C_COPY_FG': '#F0E5A2',
    'C_INDEX_BG': '#283039',
    'C_HEADER_BG': '#323C48',
    'C_BTN_BG': '#2D3441',
    'C_BTN_EDGE': '#4A5364',
    'C_SCROLL_BG': '#2D3441',
    'C_SCROLL_THUMB': '#56606F',
    'C_EDITOR_BG': '#1B1F24',
    'C_EDITOR_FG': '#FFFFFF',
    'C_BTN_HOVER': '#444E5E',
    'C_BTN_OFF': '#262D37',
    'C_TEXT_OFF': '#6E7785',
    'C_GRIDLINE': '#3C4454',
    'C_ROW_HOVER': '#444E5E',
    'C_RED_SOFT': '#4D2B2E',
    'C_ORANGE_SOFT': '#3A2E1C',
    'C_ORANGE_SOFT_HI': '#4C3A20',
    'C_GREEN_OFF': '#2F4736',
    'C_GREEN_OFF_FG': '#7E8F84',
}

LIGHT_THEME = {
    'C_WINDOW': '#F2F2F5',
    'C_CARD': '#FFFFFF',
    'C_FIELD': '#FFFFFF',
    'C_BAR': '#E7E7EC',
    'C_EDGE': '#D2D2D9',
    'C_EDGE_SOFT': '#BFBFC7',
    'C_TEXT': '#1F1F23',
    'C_MUTED': '#67676E',
    'C_BLUE': '#1E6FB8',
    'C_ORANGE': '#B96A0C',
    'C_GREEN': '#2E8B48',
    'C_GREEN_HI': '#37A455',
    'C_RED': '#C0392B',
    'C_SEL': '#BCD9F2',
    'C_SEL_FG': '#10243A',
    'C_TYPE_BG': '#FBE7CC',
    'C_TYPE_FG': '#8A4E07',
    'C_INST_BG': '#D9E9F8',
    'C_INST_FG': '#13507F',
    'C_RO_BG': '#F8DAD8',
    'C_RO_FG': '#8E3733',
    'C_EDIT_BG': '#D8F0DF',
    'C_EDIT_FG': '#1B6634',
    'C_FAIL_BG': '#C0392B',
    'C_FAIL_FG': '#FFFFFF',
    'C_TEST_BG': '#E7E1F8',
    'C_TEST_FG': '#4B3A86',
    'C_IMP_BG': '#D2EFF2',
    'C_IMP_FG': '#0F5158',
    'C_CLEAR': '#00000000',
    'C_COPY_BG': '#FBF3C9',
    'C_COPY_FG': '#6B5A12',
    'C_INDEX_BG': '#EDEDF1',
    'C_HEADER_BG': '#E2E2E8',
    'C_BTN_BG': '#FFFFFF',
    'C_BTN_EDGE': '#C9C9D1',
    'C_SCROLL_BG': '#EDEDF1',
    'C_SCROLL_THUMB': '#B6B6BE',
    'C_EDITOR_BG': '#FFFFFF',
    'C_EDITOR_FG': '#101014',
    'C_BTN_HOVER': '#EBEBF1',
    'C_BTN_OFF': '#EFEFF3',
    'C_TEXT_OFF': '#A8A8B0',
    'C_GRIDLINE': '#E3E3E8',
    'C_ROW_HOVER': '#EFF4FA',
    'C_RED_SOFT': '#FADCDA',
    'C_ORANGE_SOFT': '#FBEAD3',
    'C_ORANGE_SOFT_HI': '#F6DFC0',
    'C_GREEN_OFF': '#DCEDE1',
    'C_GREEN_OFF_FG': '#8AA491',
}

# Highlight swatches, resolved by name at paint time so a highlight survives a
# theme switch instead of being burnt in as a hex value.
HIGHLIGHT_COLOURS = ('Yellow', 'Orange', 'Blue', 'Green', 'Purple', 'Red',
                     'Teal', 'Grey')

HIGHLIGHT_DARK = {
    'Yellow': ('#5C4A16', '#F5D783'),
    'Orange': ('#5A3413', '#F5B27A'),
    'Blue': ('#173F5E', '#8FC8F2'),
    'Green': ('#1E4A2C', '#8BE0A6'),
    'Purple': ('#3C2C5C', '#C3AAF0'),
    'Red': ('#552322', '#F0A19D'),
    'Teal': ('#12474A', '#84D8DC'),
    'Grey': ('#3A3A40', '#C8C8CE'),
}

HIGHLIGHT_LIGHT = {
    'Yellow': ('#FBF0C4', '#6B5410'),
    'Orange': ('#FBE0C6', '#8A4A0C'),
    'Blue': ('#D5E8FA', '#11527F'),
    'Green': ('#D6F1DE', '#1B6634'),
    'Purple': ('#E6DEF8', '#4A3785'),
    'Red': ('#FADCDA', '#8E322D'),
    'Teal': ('#D2EFF1', '#0F5155'),
    'Grey': ('#E4E4E9', '#4A4A52'),
}

THEME_NAME = 'dark'


def set_theme(name):
    """Write one palette into module globals. Every C_* below follows."""
    global THEME_NAME
    THEME_NAME = 'light' if name == 'light' else 'dark'
    globals().update(LIGHT_THEME if THEME_NAME == 'light' else DARK_THEME)


def highlight_colours(name):
    table = HIGHLIGHT_LIGHT if THEME_NAME == 'light' else HIGHLIGHT_DARK
    return table.get(name, table['Yellow'])


set_theme('dark')

_BRUSHES = {}


def brush(hexstr):
    """Cached SolidColorBrush from a hex string."""
    b = _BRUSHES.get(hexstr)
    if b is None:
        try:
            b = SolidColorBrush(ColorConverter.ConvertFromString(hexstr))
            b.Freeze()
        except Exception:
            b = SolidColorBrush()
        _BRUSHES[hexstr] = b
    return b


# ---------------------------------------------------------------- helpers ----

def eid_value(element_id):
    """ElementId -> int, across Revit 2024 (IntegerValue) and 2026+ (Value)."""
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


def make_eid(value):
    """ElementId from a number, whichever constructor this release carries.

    2024 takes Int32, 2026+ prefers Int64.  Only used as a fallback — the read
    pass keeps the real ElementId objects and apply() reuses those.
    """
    try:
        return DB.ElementId(System.Int64(value))
    except Exception:
        pass
    try:
        return DB.ElementId(int(value))
    except Exception:
        return DB.ElementId.InvalidElementId


def field_id_key(field_id):
    """Stable key for a ScheduleFieldId, whichever property this release has."""
    for attr in ('IntegerValue', 'Value'):
        try:
            return to_text(getattr(field_id, attr))
        except Exception:
            continue
    try:
        return to_text(field_id.GetHashCode())
    except Exception:
        return to_text(field_id)


def is_valid_id(element_id):
    return element_id is not None and eid_value(element_id) != -1 and eid_value(element_id) != 0


def elem_name(elem):
    if elem is None:
        return ''
    try:
        n = DB.Element.Name.GetValue(elem)
        if n:
            return n
    except Exception:
        pass
    try:
        return elem.Name or ''
    except Exception:
        return ''


def to_text(value):
    if value is None:
        return ''
    try:
        return u'{0}'.format(value)
    except Exception:
        return str(value)


_NAT_RE = re.compile(r'(\d+)')


def natural_key(text):
    """Sort key that treats digit runs as numbers, so P10 follows P9."""
    out = []
    for part in _NAT_RE.split(to_text(text)):
        if part.isdigit():
            out.append((1, int(part), ''))
        else:
            out.append((0, 0, part.lower()))
    return out


def load_image(path):
    """Load a BitmapImage from bytes — System.Uri is not importable on 2025+."""
    bi = BitmapImage()
    bi.BeginInit()
    bi.StreamSource = MemoryStream(File.ReadAllBytes(path))
    bi.CacheOption = BitmapCacheOption.OnLoad
    bi.EndInit()
    try:
        bi.Freeze()
    except Exception:
        pass
    return bi


def load_xaml(path):
    stream = FileStream(path, FileMode.Open, FileAccess.Read)
    try:
        return XamlReader.Load(stream)
    finally:
        try:
            stream.Close()
        except Exception:
            pass


def set_name(elem, new_name):
    """Rename an element — which route works varies with the engine."""
    try:
        elem.Name = new_name
    except Exception:
        pass
    if elem_name(elem) == new_name:
        return True
    try:
        DB.Element.Name.SetValue(elem, new_name)
    except Exception:
        pass
    return elem_name(elem) == new_name


# --------------------------------------------------- parameter read/write ----

def _spec_is(param, spec_name, group):
    try:
        dt = param.Definition.GetDataType()
        return dt == getattr(getattr(DB.SpecTypeId, group), spec_name)
    except Exception:
        return False


def is_yesno(param):
    try:
        if param.Definition.GetDataType() == DB.SpecTypeId.Boolean.YesNo:
            return True
    except Exception:
        pass
    try:
        return to_text(param.Definition.ParameterType) == 'YesNo'
    except Exception:
        return False


def is_plain_number(param):
    try:
        return param.Definition.GetDataType() == DB.SpecTypeId.Number
    except Exception:
        return False


def read_param(doc, param):
    """Display text for a parameter, in project display units."""
    if param is None:
        return ''
    try:
        st = param.StorageType
    except Exception:
        return ''
    try:
        if st == DB.StorageType.String:
            return param.AsString() or ''
        if st == DB.StorageType.Integer:
            if is_yesno(param):
                return 'Yes' if param.AsInteger() else 'No'
            vs = param.AsValueString()
            if vs:
                return vs
            return to_text(param.AsInteger())
        if st == DB.StorageType.Double:
            vs = param.AsValueString()
            if vs is not None and vs != '':
                return vs
            return to_text(round(param.AsDouble(), 6))
        if st == DB.StorageType.ElementId:
            vs = param.AsValueString()
            if vs:
                return vs
            eid = param.AsElementId()
            if not is_valid_id(eid):
                return ''
            return elem_name(doc.GetElement(eid))
    except Exception:
        return ''
    return ''


# ---------------------------------------------------------------- worksets ---
#
# A schedule can show the Workset each element sits on.  The value behind that
# column is a workset *id* — an integer — shown as the workset's name, so the
# cell edits as a name and is written as an id.  Every way a value reaches a
# cell (typing, paste, fill, find and replace, Excel import, the dropdown)
# passes through stage(), which only accepts the name of a workset that
# exists; Apply turns that name back into its id.


def partition_param_id():
    """The parameter id of an element's Workset, looked up when needed rather
    than at import, like every other BuiltInParameter member here."""
    try:
        return int(getattr(DB.BuiltInParameter, 'ELEM_PARTITION_PARAM'))
    except Exception:
        return None


def wsid_value(workset_id):
    """A WorksetId as an integer.  WorksetId kept IntegerValue when ElementId
    lost it, but it is still read by name so nothing here touches the
    ElementId property the bench bans."""
    try:
        return int(getattr(workset_id, 'IntegerValue'))
    except Exception:
        return None


def read_worksets(doc):
    """[(name, id)] for every user workset, in natural name order.  Empty for a
    model that is not workshared, which is what makes the column read only."""
    out = []
    try:
        if not doc.IsWorkshared:
            return out
        kind = getattr(DB.WorksetKind, 'UserWorkset')
        for ws in DB.FilteredWorksetCollector(doc).OfKind(kind):
            value = wsid_value(ws.Id)
            if value is not None:
                out.append((to_text(ws.Name), value))
    except Exception:
        return []
    out.sort(key=lambda pair: natural_key(pair[0]))
    return out


def workset_named(worksets, text):
    """The workset a typed or pasted name means, as (name, id), or None.

    Matching ignores case and runs of spaces, so "level 2  - mechanical"
    finds "Level 2 - Mechanical"; the workset's own spelling is what is
    staged.  Anything that matches no workset is refused rather than guessed.
    """
    want = u' '.join(to_text(text).split()).lower()
    if not want:
        return None
    for name, value in worksets:
        if u' '.join(name.split()).lower() == want:
            return (name, value)
    return None


def fill_copy_only(seeds, count, downward):
    """Fill that copies and never counts — for workset names.

    "Level 2 - Mechanical" has a number in it, and the ordinary fill would
    step it to "Level 3 - Mechanical", which is not a workset.  The seeds are
    swapped for digit-free tokens, passed through the ordinary fill so a block
    of several still repeats exactly as it does in any other column, and
    swapped back.
    """
    if not seeds or count <= 0:
        return []
    tokens = []
    for i in range(len(seeds)):
        token, n = u'', i
        while True:
            token = u'abcdefghijklmnopqrstuvwxyz'[n % 26] + token
            n = n // 26
            if n == 0:
                break
        tokens.append(u'ws' + token)
    back = dict(zip(tokens, seeds))
    return [back.get(v, seeds[0]) for v in fill_plan(tokens, count, downward)]


def write_workset(param, text, worksets):
    """Move an element to the workset a staged name names."""
    if param is None:
        return False, 'parameter not found on the element'
    found = workset_named(worksets, text)
    if found is None:
        return False, u'no workset called "{0}" in this model'.format(text)
    try:
        if param.Set(int(found[1])):
            return True, ''
    except Exception as ex:
        return False, to_text(ex)
    return False, (u'Revit would not move it — it may be borrowed by someone '
                   u'else, or sit in a group')


def write_param(param, text):
    """Write display text back. Returns (ok, message)."""
    if param is None:
        return False, 'parameter not found'
    try:
        if param.IsReadOnly:
            return False, 'parameter is read only'
    except Exception:
        pass
    text = to_text(text)
    try:
        st = param.StorageType
        if st == DB.StorageType.String:
            return bool(param.Set(text)), ''
        if st == DB.StorageType.Integer:
            low = text.strip().lower()
            if is_yesno(param):
                if low in ('yes', 'y', 'true', '1', 'on'):
                    return bool(param.Set(1)), ''
                if low in ('no', 'n', 'false', '0', 'off', ''):
                    return bool(param.Set(0)), ''
                return False, 'expected Yes or No'
            if low == '':
                return False, 'cannot clear a numeric parameter'
            try:
                return bool(param.Set(int(round(float(low))))), ''
            except Exception:
                if param.SetValueString(text):
                    return True, ''
                return False, 'not a whole number'
        if st == DB.StorageType.Double:
            if text.strip() == '':
                return False, 'cannot clear a numeric parameter'
            ok = False
            try:
                ok = param.SetValueString(text)
            except Exception:
                ok = False
            if ok:
                return True, ''
            if is_plain_number(param):
                try:
                    return bool(param.Set(float(text))), ''
                except Exception:
                    return False, 'not a number'
            return False, 'not a valid value for these units'
        if st == DB.StorageType.ElementId:
            return False, 'element-valued parameters are read only in v1.0.0'
    except Exception as ex:
        return False, to_text(ex)
    return False, 'unsupported parameter type'


# ------------------------------------------------------ combined parameters --
#
# A "Combine Parameters" schedule field has no ParameterId of its own: it is a
# list of parts, each a parameter with a prefix, a suffix and the separator that
# follows it. The tool used to see the invalid id, call the field read only, and
# never read it at all — so the column came out blank.

def combined_parts(field):
    """[(param_id, prefix, suffix, separator)] for a combined field, else None.

    Revit 2022 and later only. Anything missing on an older release simply
    means the field is not treated as combined.
    """
    try:
        if not field.IsCombinedParameterField:
            return None
    except Exception:
        return None
    parts = []
    try:
        for data in field.GetCombinedParameters():
            parts.append((data.ParamId,
                          to_text(getattr(data, 'Prefix', '') or ''),
                          to_text(getattr(data, 'Suffix', '') or ''),
                          to_text(getattr(data, 'Separator', '') or '')))
    except Exception:
        return None
    return parts or None


def join_combined(pieces):
    """Build the text the way Revit's schedule shows it.

    pieces: [(prefix, value, suffix, separator)] in field order. Every part
    contributes prefix + value + suffix, and each part's separator goes between
    it and the next one — never after the last. Revit does not drop the prefix,
    suffix or separator of a part whose value is empty, so neither does this:
    the aim is to show exactly what the schedule shows.
    """
    out = []
    last = len(pieces) - 1
    for i, piece in enumerate(pieces):
        prefix, value, suffix, separator = piece
        out.append(u'{0}{1}{2}'.format(prefix, value, suffix))
        if i < last:
            out.append(separator)
    return u''.join(out)


def combined_value(doc, parts, imap, tmap):
    """The combined text for one element, from its own and its type's maps."""
    pieces = []
    for pid, prefix, suffix, separator in parts:
        key = eid_value(pid)
        param = imap.get(key)
        if param is None:
            param = tmap.get(key)
        value = read_param(doc, param) if param is not None else u''
        pieces.append((prefix, value, suffix, separator))
    return join_combined(pieces)


# ------------------------------------------------------- parameter lookup ----
#
# Reading a schedule used to list every parameter on every element — a
# hundred to three hundred on a typical MEP family, two calls into .NET each —
# to use the ten or twenty the schedule actually shows.  On a few thousand
# rows that listing was most of the time between pressing the button and
# seeing the grid.
#
# The fast path asks the element for exactly the parameter it needs, by its
# Definition, which `Element.get_Parameter` has accepted on every release this
# tool supports.  The Definition is learnt from the first full listing that
# carries the parameter, so nothing is constructed from an id and no enum is
# cast from an integer — the two things that differ between 2024 and 2026.
#
# It is not trusted on faith.  For the first PARAM_VERIFY elements **of each
# category** that ask for a given parameter, both paths run and are compared;
# one disagreement and that parameter goes back to the full listing for the
# rest of the read.  Per category, because a multi-category schedule can list
# a few hundred ducts before its first pipe, and checking only the first few
# rows would never see the pipes.  The worst case is therefore the old speed,
# never a different answer.

PARAM_VERIFY = 25


def param_map(elem):
    """Every parameter on an element, keyed by parameter id — the slow way."""
    pmap = {}
    if elem is None:
        return pmap
    try:
        for p in elem.Parameters:
            try:
                pmap[eid_value(p.Id)] = p
            except Exception:
                pass
    except Exception:
        pass
    return pmap


def same_param(a, b):
    """Do two lookups agree: both absent, or the same parameter."""
    if a is None or b is None:
        return a is None and b is None
    try:
        return eid_value(a.Id) == eid_value(b.Id)
    except Exception:
        return False


class ParamLookup(object):
    """What the read has learnt about finding each parameter quickly."""

    def __init__(self, verify=PARAM_VERIFY):
        self.verify = verify
        self.defs = {}       # pid -> Definition, learnt from a full listing
        self.slow = set()    # pids the fast path got wrong at least once
        self.checks = {}     # (category, pid) -> elements verified on
        self.listings = 0    # full listings made, for the bench

    def view(self, elem):
        return ParamView(self, elem, category_key(elem))


def category_key(elem):
    """Which category an element belongs to, for per-category checking."""
    try:
        return eid_value(elem.Category.Id)
    except Exception:
        return None


class ParamView(object):
    """One element's parameters, read on demand.

    Dict-like on purpose — `.get(pid)` is all the reader and combined_value
    have ever asked of the old map, so it drops in where the map was.
    """

    def __init__(self, lookup, elem, category=None):
        self.lookup = lookup
        self.elem = elem
        self.category = category
        self._full = None
        self._known = {}     # pid -> the answer already given for this element

    def full(self):
        if self._full is None:
            self.lookup.listings += 1
            self._full = param_map(self.elem)
        return self._full

    def get(self, pid, default=None):
        """The parameter, or `default`.

        Each element answers each parameter once and remembers it.  A type is
        one view shared by every row of that type, so without this its rows
        would each ask Revit again — and each spend one of the category's
        verification checks on the same element, leaving the other families
        in the category unchecked.
        """
        if self.elem is None:
            return default
        if pid in self._known:
            p = self._known[pid]
            return default if p is None else p
        p = self._resolve(pid)
        self._known[pid] = p
        return default if p is None else p

    def _resolve(self, pid):
        lk = self.lookup
        defn = lk.defs.get(pid)
        if defn is None or pid in lk.slow:
            p = self.full().get(pid)
            if p is not None and defn is None and pid not in lk.slow:
                try:
                    lk.defs[pid] = p.Definition
                except Exception:
                    lk.slow.add(pid)
            return p
        try:
            p = self.elem.get_Parameter(defn)
        except Exception:
            lk.slow.add(pid)
            return self.full().get(pid)
        tally = (self.category, pid)
        n = lk.checks.get(tally, 0)
        if n < lk.verify:
            lk.checks[tally] = n + 1
            q = self.full().get(pid)
            if not same_param(p, q):
                lk.slow.add(pid)
                p = q
        return p


# ------------------------------------------------------------ field types ----

def _sft(name):
    try:
        return getattr(DB.ScheduleFieldType, name)
    except Exception:
        return None


SFT_INSTANCE = _sft('Instance')
SFT_TYPE = _sft('ElementType')


# ------------------------------------------------------------- data model ----

class FieldInfo(object):
    def __init__(self):
        self.index = 0
        self.name = ''
        self.col = 'c0'
        self.is_type = False
        self.param_id = DB.ElementId.InvalidElementId
        self.supported = False
        self.reason = ''
        self.letter = ''
        self.combined = None     # [(param_id, prefix, suffix, separator)]
        self.scratch = False


_NO_KEY = object()   # a cell whose key has not been worked out yet


class CellInfo(object):
    def __init__(self):
        self.target_id = None      # element the parameter lives on (instance or type)
        self.param_id = None
        self.editable = False
        self.reason = ''
        self.original = ''
        self.is_type = False
        self.scratch = False
        self.key = _NO_KEY         # (target, parameter) ints, filled on first use


class RowInfo(object):
    def __init__(self):
        self.elem_id = None
        self.type_id = None
        self.cells = []
        self.sort_text = []


class ScheduleModel(object):
    """Reads a ViewSchedule into rows of cells, and writes staged edits back."""

    def __init__(self, doc, sched):
        self.doc = doc
        self.sched = sched
        self.error = None
        self.notes = []
        self.fields = []
        self.rows = []
        self.edits = {}          # (target_id_int, param_id_int) -> text
        self.failed = set()      # same key
        self.scratch_values = {}  # ('S', ridx, field_index) -> text, never applied
        self.level_edits = {}     # ridx -> (level id, level name), staged
        self._param_cache = {}
        self.lookup = None
        self.worksets = []        # [(name, id)] user worksets, natural order
        self.workset_fields = set()   # field indices showing an element's Workset
        try:
            self._load()
        except Exception:
            self.error = 'Could not read this schedule:\n\n' + traceback.format_exc()

    # -- reading ------------------------------------------------------------

    def _param_map(self, elem):
        return param_map(elem)

    def _load(self):
        doc = self.doc
        sched = self.sched
        defn = sched.Definition

        try:
            if defn.IsMaterialTakeoff:
                self.error = ('Material takeoffs are not supported.\n\n'
                              'Their rows are materials within elements rather than '
                              'elements, so they cannot be edited cell for cell.')
                return
        except Exception:
            pass

        # fields -------------------------------------------------------------
        try:
            order = list(defn.GetFieldOrder())
        except Exception:
            order = [defn.GetFieldId(i) for i in range(defn.GetFieldCount())]

        idx = 0
        for fid in order:
            try:
                f = defn.GetField(fid)
            except Exception:
                continue
            try:
                if f.IsHidden:
                    continue
            except Exception:
                pass
            fi = FieldInfo()
            fi.index = idx
            fi.col = 'c{0}'.format(idx)
            try:
                fi.name = f.ColumnHeading or f.GetName()
            except Exception:
                try:
                    fi.name = f.GetName()
                except Exception:
                    fi.name = 'Field {0}'.format(idx + 1)
            try:
                ft = f.FieldType
            except Exception:
                ft = None
            fi.is_type = (SFT_TYPE is not None and ft == SFT_TYPE)
            try:
                fi.param_id = f.ParameterId
            except Exception:
                fi.param_id = DB.ElementId.InvalidElementId
            fi.combined = combined_parts(f)
            if fi.combined:
                # shown as Revit builds it; it has no parameter of its own to
                # write back to, so edits go to the parameters it is made from
                fi.supported = False
                fi.reason = (u'combined parameter — shown as the schedule builds '
                             u'it; edit the parameters it is made from')
            elif ft is not None and SFT_INSTANCE is not None and ft not in (SFT_INSTANCE, SFT_TYPE):
                fi.supported = False
                fi.reason = u'calculated field ({0}) — read only'.format(to_text(ft))
            elif not is_valid_id(fi.param_id):
                fi.supported = False
                fi.reason = u'combined or calculated field — read only'
            else:
                fi.supported = True
            self.fields.append(fi)
            idx += 1

        if not self.fields:
            self.error = 'This schedule has no visible fields.'
            return

        # elements -----------------------------------------------------------
        try:
            elements = list(DB.FilteredElementCollector(doc, sched.Id).ToElements())
        except Exception:
            elements = []

        clean = []
        for e in elements:
            try:
                if e is None or not is_valid_id(e.Id):
                    continue
                if eid_value(e.Id) == eid_value(sched.Id):
                    continue
            except Exception:
                continue
            clean.append(e)

        # which columns show an element's Workset, and what it can be set to
        part = partition_param_id()
        self.workset_fields = set(
            fi.index for fi in self.fields
            if part is not None and fi.param_id is not None
            and eid_value(fi.param_id) == part)
        if self.workset_fields:
            self.worksets = read_worksets(doc)

        type_maps = {}
        lookup = ParamLookup()
        self.lookup = lookup
        for e in clean:
            row = RowInfo()
            row.elem_id = e.Id
            imap = lookup.view(e)

            tid = None
            try:
                tid = e.GetTypeId()
            except Exception:
                tid = None
            if is_valid_id(tid):
                telem = doc.GetElement(tid)
            else:
                telem = e if isinstance(e, DB.ElementType) else None
                tid = telem.Id if telem is not None else None
            row.type_id = tid

            if tid is not None and eid_value(tid) not in type_maps:
                type_maps[eid_value(tid)] = lookup.view(telem)
            tmap = type_maps.get(eid_value(tid), {}) if tid is not None else {}

            for fi in self.fields:
                ci = CellInfo()
                ci.is_type = fi.is_type
                ci.param_id = fi.param_id
                if not fi.supported:
                    ci.editable = False
                    ci.reason = fi.reason
                    if fi.combined:
                        ci.original = combined_value(doc, fi.combined, imap, tmap)
                    row.cells.append(ci)
                    continue
                pid = eid_value(fi.param_id)
                if fi.is_type:
                    ci.target_id = tid
                    p = tmap.get(pid)
                else:
                    ci.target_id = e.Id
                    p = imap.get(pid)
                    if p is None:
                        p = tmap.get(pid)
                        if p is not None:
                            ci.target_id = tid
                            ci.is_type = True
                if p is None:
                    ci.editable = False
                    ci.reason = 'parameter not present on this element'
                    ci.original = ''
                else:
                    ci.original = read_param(doc, p)
                    read_only = False
                    try:
                        read_only = p.IsReadOnly
                    except Exception:
                        read_only = True
                    if read_only:
                        ci.reason = 'read only in the model'
                    elif p.StorageType == DB.StorageType.ElementId:
                        ci.reason = u'element-valued parameter — read only in v1.0.0'
                    elif fi.index in self.workset_fields and not self.worksets:
                        ci.reason = u'not a workshared model — there are no worksets'
                    else:
                        ci.editable = True
                row.cells.append(ci)

            row.sort_text = [c.original for c in row.cells]
            self.rows.append(row)

        self._apply_schedule_sort(defn)

        n_type = len([f for f in self.fields if f.is_type])
        self.notes.append('{0} rows, {1} fields ({2} type, {3} instance).'.format(
            len(self.rows), len(self.fields), n_type, len(self.fields) - n_type))

    def _apply_schedule_sort(self, defn):
        """Order rows the way the schedule orders them, as far as we can."""
        try:
            sorts = list(defn.GetSortGroupFields())
        except Exception:
            return
        if not sorts:
            return
        fid_to_index = {}
        try:
            order = list(defn.GetFieldOrder())
        except Exception:
            return
        visible = 0
        for fid in order:
            try:
                f = defn.GetField(fid)
                hidden = f.IsHidden
            except Exception:
                continue
            if hidden:
                continue
            fid_to_index[field_id_key(fid)] = visible
            visible += 1
        keys = []
        for sf in sorts:
            try:
                k = field_id_key(sf.FieldId)
            except Exception:
                continue
            i = fid_to_index.get(k)
            if i is None:
                continue
            desc = False
            try:
                desc = (to_text(sf.SortOrder) == 'Descending')
            except Exception:
                desc = False
            keys.append((i, desc))
        if not keys:
            return
        for i, desc in reversed(keys):
            try:
                self.rows.sort(key=lambda r: natural_key(r.sort_text[i]), reverse=desc)
            except Exception:
                pass

    # -- staged edits -------------------------------------------------------

    def key_of(self, row, field_index):
        """Which staged-edit slot a cell writes to.

        Asked for every cell on every repaint, and it used to make two calls
        into .NET each time to rebuild an answer that never changes once the
        schedule is read — the target and the parameter are fixed at load. It
        is worked out once and kept on the cell.
        """
        ci = row.cells[field_index]
        if getattr(ci, 'scratch', False):
            # scratch cells are per row and column, and never reach the model;
            # not cached, because the row number is only fixed per build
            return ('S', row.ridx, field_index)
        key = getattr(ci, 'key', _NO_KEY)
        if key is _NO_KEY:
            if ci.target_id is None or ci.param_id is None:
                key = None
            else:
                key = (eid_value(ci.target_id), eid_value(ci.param_id))
            try:
                ci.key = key
            except Exception:
                pass
        return key

    def store_for(self, key):
        return self.scratch_values if (key and key[0] == 'S') else self.edits

    def current_text(self, row, field_index):
        key = self.key_of(row, field_index)
        if key is not None:
            store = self.store_for(key)
            if key in store:
                return store[key]
        return row.cells[field_index].original

    def is_edited(self, row, field_index):
        key = self.key_of(row, field_index)
        return key is not None and key[0] != 'S' and key in self.edits

    def rows_sharing(self, key):
        """Every row that displays the same (target, parameter) pair."""
        out = []
        for r in self.rows:
            for i in range(len(self.fields)):
                if self.key_of(r, i) == key:
                    out.append((r, i))
        return out

    # -- writing ------------------------------------------------------------

    def apply(self):
        """Write every staged edit in one transaction. Returns a result dict."""
        doc = self.doc
        res = {'cells': 0, 'instances': 0, 'types': 0, 'rows_affected': 0,
               'levels': 0, 'failures': [], 'ok': True}
        if not self.edits and not self.level_edits:
            return res

        # which rows each edited key touches, for the affected-rows count
        index = build_key_index(self)
        touched_rows = set()
        self.failed = set()

        # Real ElementId objects kept from the read pass, so nothing has to be
        # rebuilt from an integer — the ElementId(int) constructor is the part
        # Autodesk moved to Int64 across the 2024 - 2027 span.
        id_map = {}
        for row in self.rows:
            for ci in row.cells:
                if ci.target_id is not None:
                    id_map.setdefault(eid_value(ci.target_id), ci.target_id)

        # Borrow before the transaction opens.  CheckoutElements is refused
        # inside one, and the refusal was swallowed — so Set Level, which used
        # to borrow from inside the transaction, borrowed nothing at all on a
        # workshared model.  Moving an element to another workset needs the
        # element borrowed just the same.
        part = partition_param_id()
        borrow = []
        for key in self.edits.keys():
            if part is not None and key[1] == part and key[0] in id_map:
                borrow.append(id_map[key[0]])
        for r in self.level_edits:
            if r < len(self.rows):
                borrow.append(self.rows[r].elem_id)
        if borrow:
            checkout_elements(doc, borrow)

        tx = DB.Transaction(doc, u'Excel for Revit — apply schedule edits')
        try:
            tx.Start()
            try:
                opts = tx.GetFailureHandlingOptions()
                opts.SetFailuresPreprocessor(WarningSwallower())
                opts.SetClearAfterRollback(True)
                tx.SetFailureHandlingOptions(opts)
            except Exception:
                pass

            done_ok = []
            for key in list(self.edits.keys()):
                text = self.edits[key]
                target_int, param_int = key
                elem = None
                target_eid = id_map.get(target_int)
                try:
                    if target_eid is None:
                        target_eid = make_eid(target_int)
                    elem = doc.GetElement(target_eid)
                except Exception:
                    elem = None
                if elem is None:
                    res['failures'].append(('#{0}'.format(target_int), '', 'element no longer in the model'))
                    self.failed.add(key)
                    continue
                param = None
                try:
                    for p in elem.Parameters:
                        if eid_value(p.Id) == param_int:
                            param = p
                            break
                except Exception:
                    param = None
                label = '{0} [{1}]'.format(elem_name(elem) or 'Element', target_int)
                pname = ''
                try:
                    pname = param.Definition.Name if param is not None else ''
                except Exception:
                    pname = ''
                if part is not None and param_int == part:
                    ok, msg = write_workset(param, text, self.worksets)
                else:
                    ok, msg = write_param(param, text)
                if ok:
                    res['cells'] += 1
                    done_ok.append(key)
                    if isinstance(elem, DB.ElementType):
                        res['types'] += 1
                    else:
                        res['instances'] += 1
                    for r, _i in index.get(key, []):
                        touched_rows.add(id(r))
                else:
                    self.failed.add(key)
                    res['failures'].append((label, pname, msg or 'refused by Revit'))

            if self.level_edits:
                apply_level_edits(doc, self, res, touched_rows)

            tx.Commit()
            res['rows_affected'] = len(touched_rows)
            for key in done_ok:
                self.edits.pop(key, None)
        except Exception:
            try:
                if tx.HasStarted() and not tx.HasEnded():
                    tx.RollBack()
            except Exception:
                pass
            res['ok'] = False
            res['failures'].append(('Transaction', '', traceback.format_exc().splitlines()[-1]))
            return res

        # refresh originals from the model so further edits diff correctly
        try:
            self.refresh_originals()
        except Exception:
            pass
        return res

    def refresh_originals(self):
        doc = self.doc
        if self.workset_fields:
            # a workset renamed or added in Revit while the window is open
            fresh = read_worksets(doc)
            if fresh:
                self.worksets = fresh
        cache = {}
        for row in self.rows:
            for ci in row.cells:
                if ci.target_id is None or ci.param_id is None:
                    continue
                tkey = eid_value(ci.target_id)
                pmap = cache.get(tkey)
                if pmap is None:
                    pmap = self._param_map(doc.GetElement(ci.target_id))
                    cache[tkey] = pmap
                p = pmap.get(eid_value(ci.param_id))
                if p is not None:
                    ci.original = read_param(doc, p)
        self.refresh_combined(cache)

    def refresh_combined(self, cache=None):
        """Rebuild combined cells from the model.

        A combined value is made of other parameters, so writing to one of them
        changes it. Re-read after APPLY and Reload, or it would show the text it
        had before the edit that changed it.
        """
        combined = [fi for fi in self.fields if getattr(fi, 'combined', None)]
        if not combined:
            return
        doc = self.doc
        cache = cache if cache is not None else {}

        def pmap_of(eid):
            if eid is None:
                return {}
            key = eid_value(eid)
            if key not in cache:
                cache[key] = self._param_map(doc.GetElement(eid))
            return cache[key]

        for row in self.rows:
            imap = pmap_of(row.elem_id)
            tmap = pmap_of(row.type_id)
            for fi in combined:
                try:
                    row.cells[fi.index].original = combined_value(
                        doc, fi.combined, imap, tmap)
                except Exception:
                    continue



# =========================================================== level changing ==
#
# Re-levelling without moving anything.
#
# An element's elevation is stored against its level, so writing a new level
# normally drags it through space by the difference between the two. Some
# categories compensate on their own and some do not, and which is which varies
# by category and by release. Rather than pair every level parameter with the
# right offset parameter and hope, the position is **measured before and after
# and any movement is undone** — which is correct for every category, including
# ones this tool has never seen.

LEVEL_PARAM_NAMES = (
    'FAMILY_LEVEL_PARAM',            # most family instances
    'RBS_START_LEVEL_PARAM',         # pipes, ducts, trays, conduit
    'INSTANCE_REFERENCE_LEVEL_PARAM',
    'FAMILY_BASE_LEVEL_PARAM',       # things with a base and a top
    'WALL_BASE_CONSTRAINT',
    'STAIRS_BASE_LEVEL_PARAM',
    'ROOF_BASE_LEVEL_PARAM',
    'LEVEL_PARAM',
    'SCHEDULE_LEVEL_PARAM',          # last: read only on plenty of categories
)


def level_param_of(elem):
    """The writable level parameter on this element, or None.

    Built-in parameters are looked up by name inside the function rather than
    at import time, so a member missing from one release cannot stop the tool
    loading.
    """
    for name in LEVEL_PARAM_NAMES:
        bip = getattr(DB.BuiltInParameter, name, None)
        if bip is None:
            continue
        try:
            p = elem.get_Parameter(bip)
        except Exception:
            p = None
        if p is not None and not p.IsReadOnly and p.StorageType == DB.StorageType.ElementId:
            return p
    # nothing built in: any writable ElementId parameter already pointing at a
    # level will do, which covers shared parameters used as a level
    try:
        for p in elem.Parameters:
            if p.IsReadOnly or p.StorageType != DB.StorageType.ElementId:
                continue
            try:
                target = elem.Document.GetElement(p.AsElementId())
            except Exception:
                target = None
            if isinstance(target, DB.Level):
                return p
    except Exception:
        pass
    return None


def best_3d_view(doc):
    """The default 3D view, or the next best one. None if there are none."""
    best = None
    best_rank = 99
    try:
        for view in DB.FilteredElementCollector(doc).OfClass(DB.View3D)\
                .WhereElementIsNotElementType():
            try:
                if view.IsTemplate:
                    continue
            except Exception:
                continue
            rank = default_3d_rank(elem_name(view))
            if rank < best_rank:
                best, best_rank = view, rank
    except Exception:
        return None
    return best


def project_levels(doc):
    """Every level, lowest first."""
    out = []
    try:
        for lv in DB.FilteredElementCollector(doc).OfClass(DB.Level)\
                .WhereElementIsNotElementType():
            out.append(lv)
    except Exception:
        return []
    try:
        out.sort(key=lambda lv: lv.Elevation)
    except Exception:
        pass
    return out


def element_anchor(elem):
    """A point that stands for where the element is, in feet.

    The location point or the start of the location curve where there is one,
    the centre of the bounding box otherwise. Only the change in it matters, so
    any consistent point does the job.
    """
    try:
        loc = elem.Location
    except Exception:
        loc = None
    try:
        if isinstance(loc, DB.LocationPoint):
            return loc.Point
        if isinstance(loc, DB.LocationCurve):
            return loc.Curve.GetEndPoint(0)
    except Exception:
        pass
    try:
        box = elem.get_BoundingBox(None)
        if box is not None:
            return DB.XYZ((box.Min.X + box.Max.X) / 2.0,
                          (box.Min.Y + box.Max.Y) / 2.0,
                          (box.Min.Z + box.Max.Z) / 2.0)
    except Exception:
        pass
    return None


def set_level_keeping_place(doc, elem, level_id, tolerance=1e-7):
    """Move an element onto another level without moving it in space.

    Returns (ok, message). Runs inside the caller's transaction.
    """
    param = level_param_of(elem)
    if param is None:
        return False, 'no level parameter that can be written'
    try:
        if eid_value(param.AsElementId()) == eid_value(level_id):
            return True, 'already on that level'
    except Exception:
        pass

    was_pinned = False
    try:
        was_pinned = bool(elem.Pinned)
        if was_pinned:
            elem.Pinned = False
    except Exception:
        was_pinned = False

    before = element_anchor(elem)
    try:
        param.Set(level_id)
    except Exception as err:
        if was_pinned:
            try:
                elem.Pinned = True
            except Exception:
                pass
        return False, 'Revit refused the level: {0}'.format(err)

    try:
        doc.Regenerate()
    except Exception:
        pass

    moved = 0.0
    after = element_anchor(elem)
    if before is not None and after is not None:
        try:
            delta = DB.XYZ(before.X - after.X, before.Y - after.Y,
                           before.Z - after.Z)
            moved = delta.GetLength()
            if moved > tolerance:
                DB.ElementTransformUtils.MoveElement(doc, elem.Id, delta)
                doc.Regenerate()
        except Exception as err:
            if was_pinned:
                try:
                    elem.Pinned = True
                except Exception:
                    pass
            return False, 'the level changed but it could not be put back: {0}'.format(err)

    if was_pinned:
        try:
            elem.Pinned = True
        except Exception:
            pass

    # prove it, rather than trusting a call that raised nothing
    try:
        check = level_param_of(elem)
        if check is None or eid_value(check.AsElementId()) != eid_value(level_id):
            return False, 'the level did not stick'
    except Exception:
        pass
    final = element_anchor(elem)
    if before is not None and final is not None:
        try:
            drift = DB.XYZ(before.X - final.X, before.Y - final.Y,
                           before.Z - final.Z).GetLength()
            if drift > 1e-6:
                return False, 'it ended up {0}mm from where it started'.format(
                    to_text(round(drift * 304.8, 1)))
        except Exception:
            pass
    if moved > tolerance:
        return True, 'level changed, position corrected'
    return True, 'level changed'


def checkout_elements(doc, ids):
    """Borrow before writing. A write to an element nobody has borrowed writes
    nothing and says nothing — Revit asks in a dialog, and a run that suppresses
    dialogs answers it."""
    try:
        if not doc.IsWorkshared:
            return
    except Exception:
        return
    try:
        from System.Collections.Generic import List
        bag = List[DB.ElementId]()
        for eid in ids:
            if eid is not None:
                bag.Add(eid)
        if bag.Count:
            DB.WorksharingUtils.CheckoutElements(doc, bag)
    except Exception:
        pass


def apply_level_edits(doc, model, res, touched_rows):
    """Runs inside the apply transaction, so a failure rolls back with it."""
    for ridx in sorted(model.level_edits.keys()):
        level_id, level_name = model.level_edits[ridx]
        try:
            row = model.rows[ridx]
        except Exception:
            continue
        elem = None
        try:
            elem = doc.GetElement(row.elem_id)
        except Exception:
            elem = None
        label = 'Element [{0}]'.format(eid_value(row.elem_id))
        if elem is not None:
            label = '{0} [{1}]'.format(elem_name(elem) or 'Element',
                                       eid_value(row.elem_id))
        if elem is None:
            res['failures'].append((label, 'Level', 'the element is gone'))
            res['ok'] = False
            continue
        ok, msg = set_level_keeping_place(doc, elem, level_id)
        if ok:
            res['levels'] += 1
            touched_rows.add(id(row))
        else:
            res['failures'].append((label, 'Level', msg))
            res['ok'] = False


class WorkHandler(UI.IExternalEventHandler):
    """The only way a modeless window can touch the model.

    A modeless window runs outside Revit's API context, so it cannot open a
    transaction directly. Every write is queued here and raised through an
    ExternalEvent, which Revit calls back on its own thread when it is safe.
    """

    def __init__(self):
        self.job = None
        self.name = 'RevoBIM Excel for Revit'

    def Execute(self, uiapp):
        job = self.job
        self.job = None
        if job is None:
            return
        try:
            job(uiapp)
        except Exception:
            try:
                report_error('Excel for Revit', traceback.format_exc())
            except Exception:
                pass

    def GetName(self):
        return self.name


def report_error(title, text):
    themed_message(title, text, accent=C_RED, width=700)


class WarningSwallower(DB.IFailuresPreprocessor):
    def PreprocessFailures(self, accessor):
        try:
            for f in accessor.GetFailureMessages():
                if f.GetSeverity() == DB.FailureSeverity.Warning:
                    accessor.DeleteWarning(f)
        except Exception:
            pass
        return DB.FailureProcessingResult.Continue


def set_flag(row, name, value):
    """Write a bookkeeping flag into a bound row only if it actually changes.

    Every write to a row of the bound table is reported through the DataView
    to the grid, which re-reads that row's bindings — whether or not the value
    moved.  Re-applying a filter used to rewrite the flag on every row in the
    schedule, so a filter that changed ten rows still sent thousands of change
    notices.  Reading first is one call; a write that changes nothing is a
    cascade of them.
    """
    try:
        if to_text(row[name]) == value:
            return False
    except Exception:
        pass
    row[name] = value
    return True


_STALE = object()    # a remembered answer that has to be worked out again
PAINT_RETRIES = 4    # layout passes to wait for a row's cells to be generated


# The bookkeeping columns every grid row carries ahead of the schedule's own,
# in table order.  Both the column list and each row's values are built from
# this one tuple, so the two cannot drift apart.
GRID_META_COLS = (
    'ridx',     # the row's index in the model
    'rn',       # the row number shown in the first column
    'eid',      # the element id shown in the second
    'vis',      # filter snapshot, never shown
    'gkey',     # sort key that keeps a heading with its group
    'grp',      # group number, set on heading rows only
    'show',     # vis, minus anything in a collapsed group
)


def grid_row_values(model, row, n):
    """One grid row's values, in the same order as the table's columns."""
    meta = {
        'ridx': to_text(n),
        'rn': to_text(n + 1),
        'eid': to_text(eid_value(row.elem_id)),
        'vis': '1',
        'gkey': '',
        'grp': '',
        'show': '1',
    }
    values = [meta[name] for name in GRID_META_COLS]
    for fi in model.fields:
        values.append(model.current_text(row, fi.index))
    return values


def build_key_index(model):
    """(target, param) -> [(row, field_index), ...] for the whole grid."""
    index = {}
    for r in model.rows:
        for i in range(len(model.fields)):
            k = model.key_of(r, i)
            if k is None or k[0] == 'S':
                continue
            index.setdefault(k, []).append((r, i))
    return index


# ========================================================== themed dialogs ===

def _tb(text, colour=C_TEXT, size=12, bold=False, wrap=False):
    t = TextBlock()
    t.Text = text
    t.Foreground = brush(colour)
    t.FontSize = size
    if bold:
        t.FontWeight = FontWeights.SemiBold
    if wrap:
        t.TextWrapping = TextWrapping.Wrap
    return t


_BTN_TEMPLATE_XAML = """
<ControlTemplate xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
                 xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml" TargetType="Button">
  <Border x:Name="B" Background="{TemplateBinding Background}"
          BorderBrush="{TemplateBinding BorderBrush}" BorderThickness="1"
          CornerRadius="3" Padding="{TemplateBinding Padding}">
    <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
  </Border>
  <ControlTemplate.Triggers>
    <Trigger Property="IsMouseOver" Value="True">
      <Setter TargetName="B" Property="Opacity" Value="0.82"/>
    </Trigger>
    <Trigger Property="IsEnabled" Value="False">
      <Setter TargetName="B" Property="Opacity" Value="0.40"/>
    </Trigger>
  </ControlTemplate.Triggers>
</ControlTemplate>"""

_BTN_TEMPLATE = [None]


def _btn_template():
    if _BTN_TEMPLATE[0] is None:
        try:
            _BTN_TEMPLATE[0] = XamlReader.Parse(_BTN_TEMPLATE_XAML)
        except Exception:
            _BTN_TEMPLATE[0] = False
    return _BTN_TEMPLATE[0] or None


def _styled_button(text, kind='ghost', width=None):
    b = Button()
    try:
        tpl = _btn_template()
        if tpl is not None:
            b.Template = tpl
    except Exception:
        pass
    b.Content = text
    b.Padding = Thickness(16, 7, 16, 7)
    b.Margin = Thickness(6, 0, 0, 0)
    b.BorderThickness = Thickness(1)
    b.FontSize = 12
    if width:
        b.Width = width
    # palette colours, not literals: these were dark greys written in by hand,
    # so every prompt's buttons stayed dark on a light canvas
    if kind == 'green':
        b.Background = brush(C_GREEN)
        b.BorderBrush = brush(C_GREEN)
        b.Foreground = brush('#FFFFFF')
        b.FontWeight = FontWeights.SemiBold
    elif kind == 'red':
        b.Background = brush(C_RED_SOFT)
        b.BorderBrush = brush(C_RED)
        b.Foreground = brush(C_RED)
    elif kind == 'orange':
        b.Background = brush(C_ORANGE_SOFT)
        b.BorderBrush = brush(C_ORANGE)
        b.Foreground = brush(C_ORANGE)
    else:
        b.Background = brush(C_BTN_BG)
        b.BorderBrush = brush(C_BTN_EDGE)
        b.Foreground = brush(C_TEXT)
    return b


def _dark_textbox(width=220, text=''):
    tbx = TextBox()
    tbx.Width = width
    tbx.Text = text
    tbx.Background = brush(C_FIELD)
    tbx.Foreground = brush(C_TEXT)
    tbx.BorderBrush = brush(C_EDGE)
    tbx.BorderThickness = Thickness(1)
    tbx.Padding = Thickness(6, 4, 6, 4)
    tbx.CaretBrush = brush(C_ORANGE)
    return tbx


def _dark_check(label, checked=False):
    c = CheckBox()
    c.Content = label
    c.Foreground = brush(C_TEXT)
    c.IsChecked = checked
    c.Margin = Thickness(0, 4, 16, 4)
    return c


_WIN_BTN_TEMPLATE_XAML = """
<ControlTemplate xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
                 xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml" TargetType="Button">
  <Border x:Name="B" Background="Transparent" CornerRadius="3">
    <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
  </Border>
  <ControlTemplate.Triggers>
    <Trigger Property="IsMouseOver" Value="True">
      <Setter TargetName="B" Property="Background"
              Value="{Binding Tag, RelativeSource={RelativeSource TemplatedParent}}"/>
    </Trigger>
  </ControlTemplate.Triggers>
</ControlTemplate>"""

_WIN_BTN_TEMPLATE = [None]


def _win_button(glyph, tip=''):
    """A header control shaped like the main window's: flat, 44x26, hover grey.

    The dialogs build their chrome in code while the main window takes its own
    from the layout file, so the same button is written out twice; keeping the
    size, the corner and the hover in one place is what stops the two drifting
    apart.  The hover colour rides on Tag so it follows the palette rather than
    being baked into the shared template.
    """
    b = Button()
    if _WIN_BTN_TEMPLATE[0] is None:
        try:
            _WIN_BTN_TEMPLATE[0] = XamlReader.Parse(_WIN_BTN_TEMPLATE_XAML)
        except Exception:
            _WIN_BTN_TEMPLATE[0] = False
    if _WIN_BTN_TEMPLATE[0]:
        try:
            b.Template = _WIN_BTN_TEMPLATE[0]
        except Exception:
            pass
    b.Content = glyph
    b.Width = 44
    b.Height = 26
    b.FontSize = 14
    b.Focusable = False
    b.Cursor = Cursors.Hand
    b.Foreground = brush(C_TEXT)
    b.Background = brush('#00FFFFFF')
    b.BorderThickness = Thickness(0)
    b.Tag = brush(C_BTN_HOVER)
    if tip:
        b.ToolTip = tip
    return b


# ======================================================= shrink to taskbar ===
#
# Every window in this tool can be shrunk to its own title bar and parked at
# the bottom of the screen, so Revit can be seen without closing anything and
# losing the pending edits.  The motion is a drawer: the window slides down
# and its body slides out of sight behind the bottom edge, leaving the bar
# floating just above the taskbar.  The button then becomes a green up arrow
# that pulls the drawer back open.

DRAWER_MS = 240              # one slide, each way
DRAWER_GAP_PX = 10           # air between the parked bar and the taskbar
DRAWER_DOWN = u'⤓'      # downwards arrow to bar, for "put it away"
DRAWER_UP = u'⤒'        # upwards arrow to bar, for "bring it back"
DRAWER_MOVED_PX = 3.0        # slack when deciding whether the bar was dragged
DRAWER_TIP_DOWN = u'Shrink to the taskbar so Revit can be seen (Ctrl+Shift+H)'
DRAWER_TIP_UP = u'Expand the window again (Ctrl+Shift+H)'


def screen_work_area(window):
    """The working area of the screen `window` is on, in WPF units.

    `SystemParameters.WorkArea` is the *primary* screen, so on a second
    monitor a maximise, a stretch or a parked drawer threw the window back
    onto the first one.  The screen is found from the window handle, and its
    pixels are divided by the DPI scale or it overshoots on a scaled display.
    """
    try:
        import System.Windows.Forms as WinForms
        from System.Windows.Interop import WindowInteropHelper
        handle = WindowInteropHelper(window).Handle
        area = WinForms.Screen.FromHandle(handle).WorkingArea
        sx, sy = 1.0, 1.0
        try:
            source = PresentationSource.FromVisual(window)
            if source is not None:
                matrix = source.CompositionTarget.TransformToDevice
                sx = float(matrix.M11) or 1.0
                sy = float(matrix.M22) or 1.0
        except Exception:
            pass
        return (area.Left / sx, area.Top / sy,
                area.Width / sx, area.Height / sy)
    except Exception:
        a = SystemParameters.WorkArea
        return (a.Left, a.Top, a.Width, a.Height)


def drawer_park_top(area_top, area_height, bar):
    """Where the parked bar sits: just clear of the bottom of the screen.

    Clamped to the top of the work area, because a screen shorter than the
    bar would otherwise park it below the desktop and out of reach.
    """
    target = area_top + area_height - bar - DRAWER_GAP_PX
    return area_top if target < area_top else target


def drawer_moved(left, top, docked):
    """Did the user carry the bar away from where the drawer parked it?

    A few pixels of slack, so the window manager nudging a docked window by
    a pixel does not count as the user having moved it.
    """
    if docked is None:
        return False
    return (abs(left - docked[0]) > DRAWER_MOVED_PX or
            abs(top - docked[1]) > DRAWER_MOVED_PX)


def drawer_open_top(bar_top, bar, height, area_top, saved_top, moved):
    """Where the window goes when the drawer opens again.

    Left where it was parked, it returns to exactly where it came from.
    Carried somewhere else, it opens upward from the bar instead — jumping
    back to a position the user has already moved on from reads as a bug.
    """
    if not moved:
        return saved_top
    target = bar_top + bar - height
    return area_top if target < area_top else target


def palette_brushes():
    """(resource key, colour) for every brush the layouts look up by name.

    One list for every window: the main window rewrites these on a theme
    switch, and each dialog writes them into its own resources when it is
    built.  Read at call time, so it always reflects the current theme.
    """
    return (
        ('BgWindow', C_WINDOW), ('BgCard', C_CARD), ('BgField', C_FIELD),
        ('BgBar', C_BAR), ('Edge', C_EDGE), ('EdgeSoft', C_EDGE_SOFT),
        ('TextBody', C_TEXT), ('TextMute', C_MUTED), ('Blue', C_BLUE),
        ('Orange', C_ORANGE), ('Green', C_GREEN), ('GreenHi', C_GREEN_HI),
        ('Red', C_RED), ('Sel', C_SEL), ('SelFg', C_SEL_FG),
        ('HeaderBg', C_HEADER_BG), ('BtnBg', C_BTN_BG), ('BtnEdge', C_BTN_EDGE),
        ('BtnHover', C_BTN_HOVER), ('BtnOff', C_BTN_OFF),
        ('TextOff', C_TEXT_OFF),
        ('ScrollBg', C_SCROLL_BG), ('ScrollTh', C_SCROLL_THUMB),
        ('GridLine', C_GRIDLINE), ('OrangeSoft', C_ORANGE_SOFT),
        ('OrangeSoftHi', C_ORANGE_SOFT_HI), ('GreenOff', C_GREEN_OFF),
        ('GreenOffFg', C_GREEN_OFF_FG), ('RowHover', C_ROW_HOVER),
    )


# The control styles a window built in code does not get.  The main window
# takes its styles from ExcelForRevit.xaml; a ThemedDialog has no layout file,
# so every list, scrollbar, text box and tick box in it fell back to Windows'
# own light chrome: grey scrollbars with arrows, a pale selected row, a blue
# focus border, white tick boxes.  Every brush here is a DynamicResource that
# the dialog writes into its own resources from palette_brushes(), so the
# styles follow the theme without being rebuilt.
_DIALOG_THEME_XAML = """
<ResourceDictionary xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
                    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml">

  <Style x:Key="SbThumb" TargetType="Thumb">
    <Setter Property="MinHeight" Value="26"/>
    <Setter Property="MinWidth" Value="26"/>
    <Setter Property="Template">
      <Setter.Value>
        <ControlTemplate TargetType="Thumb">
          <Border x:Name="T" Background="{DynamicResource ScrollTh}" CornerRadius="4" Margin="2"/>
          <ControlTemplate.Triggers>
            <Trigger Property="IsMouseOver" Value="True">
              <Setter TargetName="T" Property="Background" Value="{DynamicResource TextMute}"/>
            </Trigger>
            <Trigger Property="IsDragging" Value="True">
              <Setter TargetName="T" Property="Background" Value="{DynamicResource Blue}"/>
            </Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>

  <Style x:Key="SbLine" TargetType="RepeatButton">
    <Setter Property="Focusable" Value="False"/>
    <Setter Property="Template">
      <Setter.Value>
        <ControlTemplate TargetType="RepeatButton"><Border Background="Transparent"/></ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>

  <Style TargetType="ScrollBar">
    <Setter Property="Background" Value="{DynamicResource ScrollBg}"/>
    <Setter Property="Width" Value="14"/>
    <Setter Property="MinWidth" Value="14"/>
    <Setter Property="Template">
      <Setter.Value>
        <ControlTemplate TargetType="ScrollBar">
          <Grid Background="{DynamicResource ScrollBg}">
            <Track x:Name="PART_Track" IsDirectionReversed="True"
                   ViewportSize="{TemplateBinding ViewportSize}"
                   Minimum="{TemplateBinding Minimum}"
                   Maximum="{TemplateBinding Maximum}"
                   Value="{TemplateBinding Value}">
              <Track.DecreaseRepeatButton>
                <RepeatButton Style="{DynamicResource SbLine}" Command="ScrollBar.PageUpCommand"/>
              </Track.DecreaseRepeatButton>
              <Track.Thumb><Thumb Style="{DynamicResource SbThumb}"/></Track.Thumb>
              <Track.IncreaseRepeatButton>
                <RepeatButton Style="{DynamicResource SbLine}" Command="ScrollBar.PageDownCommand"/>
              </Track.IncreaseRepeatButton>
            </Track>
          </Grid>
          <ControlTemplate.Triggers>
            <Trigger Property="Orientation" Value="Horizontal">
              <Setter TargetName="PART_Track" Property="IsDirectionReversed" Value="False"/>
              <Setter Property="Height" Value="14"/>
              <Setter Property="MinHeight" Value="14"/>
              <Setter Property="Width" Value="Auto"/>
              <Setter Property="MinWidth" Value="0"/>
            </Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>

  <Style TargetType="TextBox">
    <Setter Property="Background" Value="{DynamicResource BgField}"/>
    <Setter Property="Foreground" Value="{DynamicResource TextBody}"/>
    <Setter Property="CaretBrush" Value="{DynamicResource Orange}"/>
    <Setter Property="BorderBrush" Value="{DynamicResource Edge}"/>
    <Setter Property="BorderThickness" Value="1"/>
    <Setter Property="Padding" Value="6,4"/>
    <Setter Property="SelectionBrush" Value="{DynamicResource Sel}"/>
    <Setter Property="Template">
      <Setter.Value>
        <ControlTemplate TargetType="TextBox">
          <Border x:Name="B" Background="{TemplateBinding Background}"
                  BorderBrush="{TemplateBinding BorderBrush}"
                  BorderThickness="{TemplateBinding BorderThickness}" CornerRadius="3">
            <Grid>
              <TextBlock x:Name="Hint" Foreground="{DynamicResource TextMute}"
                         Text="{Binding Tag, RelativeSource={RelativeSource TemplatedParent}}"
                         Margin="{TemplateBinding Padding}" Padding="2,0,0,0"
                         VerticalAlignment="Center" IsHitTestVisible="False"
                         Visibility="Collapsed"/>
              <ScrollViewer x:Name="PART_ContentHost" Margin="{TemplateBinding Padding}"
                            VerticalAlignment="Center"/>
            </Grid>
          </Border>
          <ControlTemplate.Triggers>
            <Trigger Property="Text" Value="">
              <Setter TargetName="Hint" Property="Visibility" Value="Visible"/>
            </Trigger>
            <Trigger Property="IsMouseOver" Value="True">
              <Setter TargetName="B" Property="BorderBrush" Value="{DynamicResource EdgeSoft}"/>
            </Trigger>
            <Trigger Property="IsKeyboardFocused" Value="True">
              <Setter TargetName="B" Property="BorderBrush" Value="{DynamicResource Orange}"/>
            </Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>

  <Style TargetType="ListBox">
    <Setter Property="Background" Value="{DynamicResource BgField}"/>
    <Setter Property="Foreground" Value="{DynamicResource TextBody}"/>
    <Setter Property="BorderBrush" Value="{DynamicResource Edge}"/>
    <Setter Property="BorderThickness" Value="1"/>
    <!-- no sideways scrolling: where two scrollbars meet, WPF fills the corner
         with a system-grey square that no style reaches -->
    <Setter Property="ScrollViewer.HorizontalScrollBarVisibility" Value="Disabled"/>
  </Style>

  <Style TargetType="ListBoxItem">
    <Setter Property="Foreground" Value="{DynamicResource TextBody}"/>
    <Setter Property="Padding" Value="8,4"/>
    <Setter Property="FocusVisualStyle" Value="{x:Null}"/>
    <Setter Property="Template">
      <Setter.Value>
        <ControlTemplate TargetType="ListBoxItem">
          <Border x:Name="B" Background="Transparent" Padding="{TemplateBinding Padding}">
            <ContentPresenter VerticalAlignment="Center"/>
          </Border>
          <ControlTemplate.Triggers>
            <Trigger Property="IsMouseOver" Value="True">
              <Setter TargetName="B" Property="Background" Value="{DynamicResource RowHover}"/>
            </Trigger>
            <Trigger Property="IsSelected" Value="True">
              <Setter TargetName="B" Property="Background" Value="{DynamicResource Sel}"/>
              <Setter Property="Foreground" Value="{DynamicResource SelFg}"/>
            </Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>

  <Style TargetType="CheckBox">
    <Setter Property="Foreground" Value="{DynamicResource TextBody}"/>
    <Setter Property="Cursor" Value="Hand"/>
    <Setter Property="FocusVisualStyle" Value="{x:Null}"/>
    <Setter Property="Template">
      <Setter.Value>
        <ControlTemplate TargetType="CheckBox">
          <StackPanel Orientation="Horizontal" Background="Transparent">
            <Border x:Name="Box" Width="15" Height="15" CornerRadius="3"
                    Background="{DynamicResource BgField}"
                    BorderBrush="{DynamicResource EdgeSoft}" BorderThickness="1"
                    VerticalAlignment="Center">
              <Path x:Name="Tick" Data="M 2.5,7 L 5.5,10 L 11,3.5"
                    Stroke="{DynamicResource Orange}" StrokeThickness="2"
                    Visibility="Collapsed"/>
            </Border>
            <ContentPresenter Margin="7,0,0,0" VerticalAlignment="Center"/>
          </StackPanel>
          <ControlTemplate.Triggers>
            <Trigger Property="IsChecked" Value="True">
              <Setter TargetName="Tick" Property="Visibility" Value="Visible"/>
              <Setter TargetName="Box" Property="BorderBrush" Value="{DynamicResource Orange}"/>
            </Trigger>
            <Trigger Property="IsMouseOver" Value="True">
              <Setter TargetName="Box" Property="BorderBrush" Value="{DynamicResource Orange}"/>
            </Trigger>
            <Trigger Property="IsEnabled" Value="False">
              <Setter Property="Opacity" Value="0.45"/>
            </Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>

  <Style TargetType="RadioButton">
    <Setter Property="Foreground" Value="{DynamicResource TextBody}"/>
    <Setter Property="Cursor" Value="Hand"/>
    <Setter Property="FocusVisualStyle" Value="{x:Null}"/>
    <Setter Property="Template">
      <Setter.Value>
        <ControlTemplate TargetType="RadioButton">
          <StackPanel Orientation="Horizontal" Background="Transparent">
            <Grid Width="15" Height="15" VerticalAlignment="Center">
              <Ellipse x:Name="Ring" Fill="{DynamicResource BgField}"
                       Stroke="{DynamicResource EdgeSoft}" StrokeThickness="1"/>
              <Ellipse x:Name="Dot" Width="7" Height="7"
                       Fill="{DynamicResource Orange}" Visibility="Collapsed"/>
            </Grid>
            <ContentPresenter Margin="7,0,0,0" VerticalAlignment="Center"/>
          </StackPanel>
          <ControlTemplate.Triggers>
            <Trigger Property="IsChecked" Value="True">
              <Setter TargetName="Dot" Property="Visibility" Value="Visible"/>
              <Setter TargetName="Ring" Property="Stroke" Value="{DynamicResource Orange}"/>
            </Trigger>
            <Trigger Property="IsMouseOver" Value="True">
              <Setter TargetName="Ring" Property="Stroke" Value="{DynamicResource Orange}"/>
            </Trigger>
            <Trigger Property="IsEnabled" Value="False">
              <Setter Property="Opacity" Value="0.45"/>
            </Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>

</ResourceDictionary>
"""

_DIALOG_THEME = [None]


def theme_window(window):
    """Give a window built in code what the main window gets from its layout:
    the palette's brushes by name, and the control styles that use them."""
    res = window.Resources
    for key, value in palette_brushes():
        try:
            res[key] = brush(value)
        except Exception:
            pass
    if _DIALOG_THEME[0] is None:
        try:
            _DIALOG_THEME[0] = XamlReader.Parse(_DIALOG_THEME_XAML)
        except Exception:
            _DIALOG_THEME[0] = False     # unthemed beats a dialog that will not open
    if _DIALOG_THEME[0]:
        try:
            res.MergedDictionaries.Add(_DIALOG_THEME[0])
        except Exception:
            pass


class WindowDrawer(object):
    """Shrinks a window down to its header bar and parks it at the bottom.

    Driven by one button, which doubles as the state: a down arrow while the
    window is open, a green up arrow while it is away.  Both the main window
    and every ThemedDialog hand one of these their own chrome, so the gesture
    is identical wherever it appears.
    """

    def __init__(self, window, header, root, button, state_hook=None):
        self.window = window        # the Window being shrunk
        self.header = header        # the Border that stays on screen
        self.root = root            # the body holder, pinned during the slide
        self.button = button        # the arrow, repainted on every change
        self.state_hook = state_hook  # host callback, so it can park its grips
        self.shrunk = False
        self.busy = False
        self.saved = None           # (Left, Top, Width, Height) before shrinking
        self.docked = None          # where the bar was parked, to spot a drag
        self.saved_min_h = 0.0
        self.paint_button()

    # -- measurement --------------------------------------------------------

    def bar_height(self):
        """How tall the parked window is: the header plus the shell border."""
        try:
            h = float(self.header.ActualHeight)
        except Exception:
            h = 0.0
        if h < 24.0:
            h = 46.0                        # not laid out yet; a fair guess
        try:
            edge = self.window.Content.BorderThickness
            h += float(edge.Top) + float(edge.Bottom)
        except Exception:
            h += 2.0
        return h

    # -- the body -----------------------------------------------------------

    def pin(self):
        """Freeze the body at its present size for the length of the slide.

        Without this the grid re-measures on every animation frame — a
        virtualising panel realising and dropping rows twenty times a second
        — and the window looks squashed rather than drawn away.  Pinned, the
        body keeps its height and the shrinking window simply clips it.
        """
        try:
            self.root.Height = self.root.ActualHeight
            self.root.VerticalAlignment = VerticalAlignment.Top
        except Exception:
            pass
        try:
            self.window.Content.ClipToBounds = True
        except Exception:
            pass

    def unpin(self):
        try:
            self.root.Height = System.Double.NaN
            self.root.VerticalAlignment = VerticalAlignment.Stretch
        except Exception:
            pass

    # -- the arrow ----------------------------------------------------------

    def paint_button(self):
        if self.button is None:
            return
        try:
            if self.shrunk:
                self.button.Content = DRAWER_UP
                self.button.Foreground = brush(C_GREEN_HI)
                self.button.ToolTip = DRAWER_TIP_UP
            else:
                self.button.Content = DRAWER_DOWN
                self.button.Foreground = brush(C_TEXT)
                self.button.ToolTip = DRAWER_TIP_DOWN
        except Exception:
            pass

    def notify(self):
        if self.state_hook is None:
            return
        try:
            self.state_hook(self.shrunk)
        except Exception:
            pass

    # -- the slide ----------------------------------------------------------

    def slide(self, top, height, done=None):
        """Animate Top and Height together, then hand the properties back.

        An animation holds its end value and outranks any later plain
        assignment, so each one is cleared the moment it finishes and the
        final number written straight onto the window — otherwise every
        resize and move from then on would be silently ignored.
        """
        w = self.window
        self.busy = True
        state = {'done': False}

        def finish(sender, args):
            if state['done']:
                return
            state['done'] = True
            self.busy = False
            try:
                w.BeginAnimation(Window.TopProperty, None)
                w.BeginAnimation(Window.HeightProperty, None)
            except Exception:
                pass
            # a separate try, because the release above is also the path
            # taken when the animation could not start at all — and the
            # window still has to end up where it was asked to go
            try:
                w.Top = top
                w.Height = height
            except Exception:
                pass
            if done is not None:
                try:
                    done()
                except Exception:
                    pass

        try:
            ease = CubicEase()
            ease.EasingMode = EasingMode.EaseInOut
            span = Duration(TimeSpan.FromMilliseconds(DRAWER_MS))

            high = DoubleAnimation()
            high.To = float(height)
            high.Duration = span
            high.EasingFunction = ease
            high.FillBehavior = FillBehavior.HoldEnd
            high.Completed += finish

            down = DoubleAnimation()
            down.To = float(top)
            down.Duration = span
            down.EasingFunction = ease
            down.FillBehavior = FillBehavior.HoldEnd

            w.BeginAnimation(Window.TopProperty, down)
            w.BeginAnimation(Window.HeightProperty, high)
        except Exception:
            finish(None, None)          # no animation beats no drawer

    # -- the two directions -------------------------------------------------

    def shrink(self):
        if self.shrunk or self.busy:
            return
        w = self.window
        try:
            self.saved = (w.Left, w.Top, w.ActualWidth, w.ActualHeight)
            self.saved_min_h = w.MinHeight
        except Exception:
            return
        bar = self.bar_height()
        area_left, area_top, area_w, area_h = screen_work_area(w)
        target = drawer_park_top(area_top, area_h, bar)
        try:
            # SizeToContent and MinHeight both veto a Height animation, and a
            # vetoed one leaves the window half shut.  Both come off before
            # the body is pinned, so the pin cannot trigger a re-measure that
            # SizeToContent would then act on.
            w.SizeToContent = SizeToContent.Manual
            w.MinHeight = 0
        except Exception:
            pass
        self.pin()
        self.shrunk = True
        self.paint_button()
        self.notify()
        self.slide(target, bar, self.parked)

    def parked(self):
        try:
            self.docked = (self.window.Left, self.window.Top)
        except Exception:
            self.docked = None

    def expand(self):
        if not self.shrunk or self.busy:
            return
        w = self.window
        if self.saved is None:
            left, top, width, height = (w.Left, w.Top, w.ActualWidth, 480.0)
        else:
            left, top, width, height = self.saved
        try:
            moved = drawer_moved(w.Left, w.Top, self.docked)
        except Exception:
            moved = False
        area_left, area_top, area_w, area_h = screen_work_area(w)
        try:
            target = drawer_open_top(w.Top, w.ActualHeight, height,
                                     area_top, top, moved)
        except Exception:
            target = top
        if not moved:
            try:
                w.Left = left
            except Exception:
                pass
        self.shrunk = False
        self.paint_button()
        self.notify()
        self.slide(target, height, self.opened)

    def opened(self):
        try:
            self.window.MinHeight = self.saved_min_h
        except Exception:
            pass
        self.unpin()
        self.docked = None

    def toggle(self, sender=None, args=None):
        if self.busy:
            return
        if self.shrunk:
            self.expand()
        else:
            self.shrink()


class ThemedDialog(object):
    """A small RevoBIM-themed window built in code, so no extra XAML files."""

    def __init__(self, subtitle, width=520, height=None, owner=None, accent=C_ORANGE):
        self.result = None
        self.window = Window()
        self.window.Title = u'RevoBIM — ' + subtitle
        self.window.WindowStyle = getattr(WindowStyle, 'None')
        self.window.AllowsTransparency = True
        self.window.Background = brush('#00FFFFFF')
        self.window.ResizeMode = ResizeMode.NoResize
        self.window.WindowStartupLocation = WindowStartupLocation.CenterOwner
        self.window.Width = width
        self.window.FontFamily = System.Windows.Media.FontFamily('Segoe UI')
        self.window.FontSize = 12
        theme_window(self.window)
        if height:
            self.window.Height = height
        else:
            self.window.SizeToContent = SizeToContent.Height
        if owner is not None:
            try:
                self.window.Owner = owner
            except Exception:
                pass
            try:
                # an owner shrunk to its own title bar has no middle worth
                # centring on, so a prompt raised over a parked window goes
                # to the middle of the screen instead of the taskbar
                if owner.ActualHeight < 140:
                    self.window.WindowStartupLocation = \
                        WindowStartupLocation.CenterScreen
            except Exception:
                pass
        else:
            self.window.WindowStartupLocation = WindowStartupLocation.CenterScreen

        shell = Border()
        shell.Background = brush(C_WINDOW)
        shell.BorderBrush = brush(C_EDGE_SOFT)
        shell.BorderThickness = Thickness(1)
        shell.CornerRadius = CornerRadius(6)
        self.window.Content = shell

        root = WGrid()
        for h in ('auto', 'star', 'auto'):
            rd = RowDefinition()
            rd.Height = GridLength(1, GridUnitType.Auto) if h == 'auto' else GridLength(1, GridUnitType.Star)
            root.RowDefinitions.Add(rd)
        shell.Child = root

        # header
        head = Border()
        head.Background = brush(C_BAR)
        head.CornerRadius = CornerRadius(6, 6, 0, 0)
        head.Padding = Thickness(14, 8, 10, 8)
        hg = WGrid()
        for w in ('auto', 'star', 'auto'):
            cd = ColumnDefinition()
            cd.Width = GridLength(1, GridUnitType.Auto) if w == 'auto' else GridLength(1, GridUnitType.Star)
            hg.ColumnDefinitions.Add(cd)
        titles = StackPanel()
        titles.Children.Add(_tb('RevoBIM', C_BLUE, 20, True))
        sub = _tb(subtitle, accent, 15)
        sub.Margin = Thickness(1, -2, 0, 0)
        titles.Children.Add(sub)
        WGrid.SetColumn(titles, 0)
        hg.Children.Add(titles)
        chrome = StackPanel()
        chrome.Orientation = Orientation.Horizontal
        chrome.VerticalAlignment = VerticalAlignment.Top
        chrome.HorizontalAlignment = HorizontalAlignment.Right
        chrome.Margin = Thickness(0, -2, -6, 0)
        ver = _tb('v' + __version__, C_MUTED, 11)
        ver.VerticalAlignment = VerticalAlignment.Center
        ver.Margin = Thickness(0, 0, 8, 0)
        chrome.Children.Add(ver)
        self.shrink_btn = _win_button(DRAWER_DOWN, DRAWER_TIP_DOWN)
        chrome.Children.Add(self.shrink_btn)
        WGrid.SetColumn(chrome, 2)
        hg.Children.Add(chrome)
        head.Child = hg
        WGrid.SetRow(head, 0)
        root.Children.Add(head)
        try:
            head.MouseLeftButtonDown += self._drag
        except Exception:
            pass

        # body
        self.body = StackPanel()
        self.body.Margin = Thickness(16, 14, 16, 14)
        holder = ScrollViewer()
        holder.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
        holder.HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled
        holder.Content = self.body
        WGrid.SetRow(holder, 1)
        root.Children.Add(holder)

        # footer
        foot = Border()
        foot.Background = brush(C_BAR)
        foot.BorderBrush = brush(C_EDGE)
        foot.BorderThickness = Thickness(0, 1, 0, 0)
        foot.CornerRadius = CornerRadius(0, 0, 6, 6)
        foot.Padding = Thickness(12, 10, 12, 10)
        self.footer = StackPanel()
        self.footer.Orientation = Orientation.Horizontal
        self.footer.HorizontalAlignment = HorizontalAlignment.Right
        foot.Child = self.footer
        WGrid.SetRow(foot, 2)
        root.Children.Add(foot)

        # every window in the tool shrinks the same way, this one included
        self.drawer = WindowDrawer(self.window, head, root, self.shrink_btn)
        try:
            self.shrink_btn.Click += self.drawer.toggle
        except Exception:
            pass

    def _drag(self, sender, args):
        try:
            self.window.DragMove()
        except Exception:
            pass

    def add(self, element):
        self.body.Children.Add(element)
        return element

    def add_button(self, label, kind='ghost', value=None, close=True, handler=None):
        btn = _styled_button(label, kind)

        def _click(sender, args):
            if handler is not None:
                handler()
            if close:
                self.close_with(value)
        btn.Click += _click
        self.footer.Children.Add(btn)
        return btn

    def close_with(self, value):
        """Close the way a footer button does, so a double-click or Enter on a
        list can stand in for pressing the button."""
        self.result = value
        try:
            self.window.DialogResult = True
        except Exception:
            pass
        try:
            self.window.Close()
        except Exception:
            pass

    def show(self):
        try:
            self.window.ShowDialog()
        except Exception:
            self.window.Show()
        return self.result


def themed_message(subtitle, message, owner=None, accent=C_ORANGE, width=520):
    dlg = ThemedDialog(subtitle, width=width, owner=owner, accent=accent)
    dlg.add(_tb(message, C_TEXT, 12, False, True))
    dlg.add_button('OK', 'ghost', 'ok')
    return dlg.show()


# ================================================== schedule resolution ======

def _is_editable_schedule(v):
    if not isinstance(v, DB.ViewSchedule):
        return False
    try:
        if v.IsTemplate:
            return False
    except Exception:
        pass
    try:
        if v.IsTitleblockRevisionSchedule:
            return False
    except Exception:
        pass
    return True


def resolve_schedule(uidoc, doc):
    """Active schedule view, else Project Browser selection, else a picker."""
    try:
        av = uidoc.ActiveView
        if _is_editable_schedule(av):
            return av
    except Exception:
        pass
    try:
        for eid in uidoc.Selection.GetElementIds():
            e = doc.GetElement(eid)
            if _is_editable_schedule(e):
                return e
    except Exception:
        pass
    return pick_schedule(doc)


def pick_schedule(doc):
    scheds = []
    try:
        for v in DB.FilteredElementCollector(doc).OfClass(DB.ViewSchedule):
            if _is_editable_schedule(v):
                scheds.append(v)
    except Exception:
        pass
    if not scheds:
        themed_message('Excel for Revit', 'There are no schedules in this model.')
        return None
    scheds.sort(key=lambda v: natural_key(elem_name(v)))

    # sized to its content: at a fixed 520px the list and its hint overran the
    # body, and the dialog grew a second scrollbar around the first
    dlg = ThemedDialog('Excel for Revit', width=560, accent=C_ORANGE)
    dlg.add(_tb('No schedule was active or selected. Pick one to open.',
                C_MUTED, 12, False, True))
    box = _dark_textbox(500)
    box.Tag = u'Search schedules'            # the placeholder, while it is empty
    box.Margin = Thickness(0, 10, 0, 8)
    dlg.add(box)
    lst = ListBox()
    lst.Height = 340
    lst.Background = brush(C_FIELD)
    lst.Foreground = brush(C_TEXT)
    lst.BorderBrush = brush(C_EDGE)
    lst.BorderThickness = Thickness(1)
    dlg.add(lst)
    hint = _tb(u'Double-click a schedule, or press Enter, to open it.',
               C_MUTED, 11)
    hint.Margin = Thickness(0, 6, 0, 0)
    dlg.add(hint)

    # names read once: asking Revit for every schedule's name again on each
    # keystroke in the search box was most of what the box cost
    named = [(v, elem_name(v)) for v in scheds]
    lowered = [n.lower() for v, n in named]
    state = {'items': []}

    def fill(term=''):
        term = (term or '').lower()
        lst.Items.Clear()
        state['items'] = []
        for (v, n), low in zip(named, lowered):
            if term and term not in low:
                continue
            state['items'].append(v)
            lst.Items.Add(n)
        if state['items']:
            lst.SelectedIndex = 0       # Enter always has something to open
    fill()

    def on_search(sender, args):
        fill(box.Text)
    box.TextChanged += on_search

    dlg.result_view = None

    def open_selected():
        i = lst.SelectedIndex
        if 0 <= i < len(state['items']):
            dlg.result_view = state['items'][i]
            dlg.close_with('open')

    def on_double(sender, args):
        # only a double-click that lands on a schedule opens it; one on the
        # scrollbar or the empty space under a short list does nothing
        # walked up rather than asked of ItemsControl.ContainerFromElement,
        # which is both a static and an instance method and leaves IronPython
        # unsure which one it is being asked to call
        hit = walk_up(args.OriginalSource, ListBoxItem)
        if hit is None:
            return
        args.Handled = True
        open_selected()
    lst.MouseDoubleClick += on_double

    def on_keys(sender, args):
        key = args.Key
        if key == Key.Enter or key == Key.Return:
            if isinstance(Keyboard.FocusedElement, Button):
                return          # Tab to Cancel then Enter means Cancel
            args.Handled = True
            open_selected()
        elif key == Key.Escape:
            args.Handled = True
            dlg.close_with(None)
        elif key == Key.Down and box.IsKeyboardFocusWithin:
            # from the search box straight into the list, as a combo would
            args.Handled = True
            if lst.Items.Count:
                if lst.SelectedIndex < 0:
                    lst.SelectedIndex = 0
                try:
                    item = lst.ItemContainerGenerator.ContainerFromIndex(
                        lst.SelectedIndex)
                    (item or lst).Focus()
                except Exception:
                    lst.Focus()
    dlg.window.PreviewKeyDown += on_keys

    def on_shown(sender, args):
        try:
            box.Focus()
        except Exception:
            pass
    dlg.window.ContentRendered += on_shown

    dlg.add_button('Cancel', 'ghost', None)
    dlg.add_button('Open', 'green', 'open', False, open_selected)
    dlg.show()
    return getattr(dlg, 'result_view', None)


# ======================================================== find and replace ===

def screen_point(element, x, y):
    """A point on `element`, as a position on screen in WPF units — what a
    window's Left and Top take.  PointToScreen answers in device pixels."""
    pt = element.PointToScreen(Point(x, y))
    try:
        source = PresentationSource.FromVisual(element)
        if source is not None:
            pt = source.CompositionTarget.TransformFromDevice.Transform(pt)
    except Exception:
        pass
    return pt


class WorksetDropdown(object):
    """The list of worksets that opens from a Workset cell.

    A small borderless window owned by the main window, not a WPF Popup: a text
    box inside a Popup is unreliable at taking typing in a modeless window that
    another application hosts, and the search box here has to.  It is a
    dropdown, not a window of its own, so it closes when anything else is
    clicked and carries no title bar or shrink button.

    Choosing a workset stages it on every cell it was opened for — the whole
    selection in the Workset column — through the same stage() as every other
    edit, so it colours green, undoes in one step and waits for APPLY.
    """

    LIST_MAX = 300
    ROW_PX = 24
    GRACE_S = 0.6        # about a double-click: a click this soon is its second half

    def __init__(self, host, targets, names, current, seed=u''):
        self.host = host
        self.targets = targets
        self.names = list(names)
        self.shown = list(names)
        self.closed = False
        self.opened_at = 0.0

        w = Window()
        w.WindowStyle = getattr(WindowStyle, 'None')
        w.AllowsTransparency = True
        w.Background = brush('#00000000')
        w.ShowInTaskbar = False
        w.ResizeMode = ResizeMode.NoResize
        w.SizeToContent = SizeToContent.Height
        w.FontFamily = System.Windows.Media.FontFamily('Segoe UI')
        w.FontSize = 12
        theme_window(w)
        self.window = w

        shell = Border()
        shell.Background = brush(C_FIELD)
        shell.BorderBrush = brush(C_EDGE_SOFT)
        shell.BorderThickness = Thickness(1)
        shell.CornerRadius = CornerRadius(4)
        shell.Padding = Thickness(8)
        body = StackPanel()
        shell.Child = body
        w.Content = shell

        count = len(set(r for r, f in targets))
        head = _tb(u'Workset for {0} row{1}'.format(count, '' if count == 1 else 's'),
                   C_MUTED, 11)
        head.Margin = Thickness(2, 0, 0, 6)
        body.Children.Add(head)

        box = TextBox()
        box.Tag = u'Search worksets'
        box.Margin = Thickness(0, 0, 0, 6)
        body.Children.Add(box)
        self.box = box

        lst = ListBox()
        lst.MaxHeight = self.LIST_MAX
        body.Children.Add(lst)
        self.lst = lst

        hint = _tb(u'Click to set  \u00b7  Enter  \u00b7  Esc to cancel', C_MUTED, 10)
        hint.Margin = Thickness(2, 6, 0, 0)
        body.Children.Add(hint)

        self.fill(u'')
        if current in self.shown:
            lst.SelectedIndex = self.shown.index(current)
        elif self.shown:
            lst.SelectedIndex = 0

        box.TextChanged += self._search
        lst.PreviewMouseLeftButtonUp += self._click
        w.PreviewKeyDown += self._keys
        w.Deactivated += self._deactivated
        w.Closed += self._closed
        self.seed = to_text(seed or u'')

    def fill(self, term):
        term = to_text(term).strip().lower()
        self.shown = [n for n in self.names if not term or term in n.lower()]
        self.lst.Items.Clear()
        for name in self.shown:
            self.lst.Items.Add(name)
        if self.shown:
            self.lst.SelectedIndex = 0

    def _search(self, sender, args):
        self.fill(self.box.Text)

    def _click(self, sender, args):
        item = walk_up(args.OriginalSource, ListBoxItem)
        if item is None:
            return                          # the scrollbar, or empty space
        try:
            index = self.lst.ItemContainerGenerator.IndexFromContainer(item)
        except Exception:
            index = -1
        if 0 <= index < len(self.shown):
            args.Handled = True
            self.choose(self.shown[index])

    def _keys(self, sender, args):
        key = args.Key
        if key == Key.Escape:
            args.Handled = True
            self.close()
        elif key == Key.Enter or key == Key.Return:
            args.Handled = True
            i = self.lst.SelectedIndex
            if 0 <= i < len(self.shown):
                self.choose(self.shown[i])
        elif key == Key.Down and self.box.IsKeyboardFocusWithin and self.shown:
            args.Handled = True
            self.focus_item(max(self.lst.SelectedIndex, 0))
        elif (key == Key.Up and self.lst.IsKeyboardFocusWithin
              and self.lst.SelectedIndex <= 0):
            args.Handled = True
            self.box.Focus()

    def focus_item(self, index):
        self.lst.SelectedIndex = index
        try:
            item = self.lst.ItemContainerGenerator.ContainerFromIndex(index)
            (item or self.lst).Focus()
        except Exception:
            self.lst.Focus()

    def choose(self, name):
        targets = self.targets
        self.close()
        self.host.apply_workset(targets, name)
        try:
            self.host.window.Activate()
        except Exception:
            pass

    def _deactivated(self, sender, args):
        # A click anywhere else closes it, as a dropdown does — after the
        # deactivation has finished, not from inside it.  Except straight
        # after opening: the second click of the double-click that opened it
        # lands on the grid, and closing then reopening it is a flicker.  The
        # grid hands that click back through reclaim(); anything else is
        # caught by the check once the moment has passed.
        if time.time() - self.opened_at < self.GRACE_S:
            try:
                timer = DispatcherTimer()
                timer.Interval = TimeSpan.FromMilliseconds(self.GRACE_S * 1000)

                def _later(sender, args):
                    timer.Stop()
                    if not self.closed and not self.window.IsActive:
                        self.close()
                timer.Tick += _later
                timer.Start()
                return
            except Exception:
                pass
        try:
            self.window.Dispatcher.BeginInvoke(DispatcherPriority.Background,
                                               Action(self.close))
        except Exception:
            self.close()

    def reclaim(self):
        """Take the focus back after the second click of a double-click."""
        try:
            self.window.Activate()
            self.box.Focus()
        except Exception:
            pass

    def _closed(self, sender, args):
        self.closed = True
        if self.host.ws_dropdown is self:
            self.host.ws_dropdown = None

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            self.window.Close()
        except Exception:
            pass

    def show_at(self, left, top, bottom, width):
        """Open under the cell (top..bottom in screen units), or above it when
        there is no room below, kept on the screen the grid is on."""
        w = self.window
        w.Width = max(260.0, float(width))
        rows = min(len(self.names), self.LIST_MAX // self.ROW_PX)
        est = 110.0 + rows * self.ROW_PX
        a_left, a_top, a_w, a_h = screen_work_area(self.host.window)
        y = bottom
        if y + est > a_top + a_h and top - est >= a_top:
            y = top - est
        x = min(max(left, a_left), a_left + a_w - w.Width)
        w.Left = x
        w.Top = y
        try:
            w.Owner = self.host.window
        except Exception:
            pass
        self.opened_at = time.time()
        w.Show()
        try:
            w.Activate()
        except Exception:
            pass
        self.box.Focus()
        if self.seed:
            # typing on a Workset cell opens this with what was typed
            self.box.Text = self.seed
            self.box.CaretIndex = len(self.seed)


class FindReplace(object):
    def __init__(self, host):
        self.host = host
        dlg = ThemedDialog('Find and Replace', width=520, owner=host.window)
        self.dlg = dlg
        dlg.add(_tb('Find what', C_MUTED, 11))
        self.find_box = _dark_textbox(470)
        dlg.add(self.find_box)
        lbl = _tb('Replace with', C_MUTED, 11)
        lbl.Margin = Thickness(0, 10, 0, 0)
        dlg.add(lbl)
        self.repl_box = _dark_textbox(470)
        dlg.add(self.repl_box)

        opts = StackPanel()
        opts.Orientation = Orientation.Horizontal
        opts.Margin = Thickness(0, 12, 0, 0)
        self.cs = _dark_check('Match case')
        self.whole = _dark_check('Whole cell')
        self.selonly = _dark_check('Selection only')
        opts.Children.Add(self.cs)
        opts.Children.Add(self.whole)
        opts.Children.Add(self.selonly)
        dlg.add(opts)

        self.status = _tb('', C_MUTED, 11, False, True)
        self.status.Margin = Thickness(0, 10, 0, 0)
        dlg.add(self.status)

        dlg.add_button('Close', 'ghost', None)
        dlg.add_button('Find Next', 'ghost', None, False, self.find_next)
        dlg.add_button('Replace', 'orange', None, False, self.replace_one)
        dlg.add_button('Replace All', 'green', None, False, self.replace_all)
        self._last = (-1, -1)

    def show(self):
        try:
            self.dlg.window.Show()
            self.find_box.Focus()
        except Exception:
            pass

    def _match(self, text, term):
        if not term:
            return False
        a, b = text, term
        if not self.cs.IsChecked:
            a, b = a.lower(), b.lower()
        if self.whole.IsChecked:
            return a == b
        return b in a

    def _replaced(self, text, term, repl):
        if self.whole.IsChecked:
            return repl
        if self.cs.IsChecked:
            return text.replace(term, repl)
        out = ''
        low_t, low_term = text.lower(), term.lower()
        i = 0
        while True:
            j = low_t.find(low_term, i)
            if j < 0:
                out += text[i:]
                break
            out += text[i:j] + repl
            i = j + len(term)
        return out

    def _scope(self):
        host = self.host
        if self.selonly.IsChecked:
            cells = host.sel_cells()
            if cells:
                return [(c['pos'], c['col']) for c in cells]
        out = []
        cols = host.ordered_field_columns()
        for i in range(host.dg.Items.Count):
            for col in cols:
                out.append((i, col))
        return out

    def find_next(self):
        term = self.find_box.Text
        if not term:
            self.status.Text = 'Type something to find.'
            return
        scope = self._scope()
        start = 0
        for n, (pos, col) in enumerate(scope):
            if (pos, id(col)) == (self._last[0], self._last[1]):
                start = n + 1
                break
        for n in range(len(scope)):
            pos, col = scope[(start + n) % len(scope)]
            text = self.host.text_at(pos, col)
            if text is not None and self._match(text, term):
                self.host.select_cell(pos, col)
                self._last = (pos, id(col))
                self.status.Text = 'Found in row {0}.'.format(pos + 1)
                return
        self.status.Text = 'No match.'

    def replace_one(self):
        term = self.find_box.Text
        if not term:
            return
        cells = self.host.sel_cells()
        if cells:
            c = cells[0]
            text = self.host.text_at(c['pos'], c['col'])
            if text is not None and self._match(text, term):
                self.host.begin_batch()
                self.host.stage_cell(c['pos'], c['col'],
                                     self._replaced(text, term, self.repl_box.Text))
                self.host.end_batch()
                self.status.Text = 'Replaced 1 cell.'
        self.find_next()

    def replace_all(self):
        term = self.find_box.Text
        if not term:
            return
        repl = self.repl_box.Text
        scope = self._scope()
        self.host.begin_batch()
        count = 0
        skipped = 0
        for pos, col in scope:
            text = self.host.text_at(pos, col)
            if text is None or not self._match(text, term):
                continue
            if not self.host.stage_cell(pos, col, self._replaced(text, term, repl)):
                skipped += 1
                continue
            count += 1
        self.host.end_batch()
        msg = 'Replaced {0} cell{1}.'.format(count, '' if count == 1 else 's')
        if skipped:
            msg += self.host.skipped_note(skipped)
        self.status.Text = msg
        self.host.set_status(msg)


# ============================================================= main window ===

from System.Windows import Style as WStyle                    # noqa: E402
from System.Windows import Setter as WSetter                  # noqa: E402
from System.Windows.Threading import DispatcherPriority       # noqa: E402
from System.Windows.Threading import DispatcherTimer          # noqa: E402
from System import TimeSpan                                   # noqa: E402

try:
    from System.Windows.Controls import ScrollChangedEventHandler
except Exception:
    ScrollChangedEventHandler = None

_ABSENT = object()
_NUM_RE = re.compile(r'^(.*?)(\d+)(\D*)$')


def split_number(text):
    """(prefix, digits, suffix) around the last run of digits, or None.

    A leading minus counts as a sign only at the very start or after a space.
    In a tag like AHU-1 or SD-001 the hyphen is a separator, and reading it as
    a negative sign is what made a drag fill from AHU-1 produce AHU0.
    """
    text = to_text(text)
    m = _NUM_RE.match(text)
    if not m:
        return None
    prefix, digits, suffix = m.group(1), m.group(2), m.group(3)
    if prefix.endswith('-') and (len(prefix) == 1 or prefix[-2].isspace()):
        prefix, digits = prefix[:-1], '-' + digits
    return (prefix, digits, suffix)


def has_number(text):
    return split_number(text) is not None


def infer_step(values):
    """Step implied by a run of seed values, or None if there is not one.

    Every value has to carry a number and the gaps have to agree; anything
    else is not a series and gets copied instead of guessed at.
    """
    nums = []
    for v in values:
        parts = split_number(v)
        if parts is None:
            return None
        try:
            nums.append(int(parts[1]))
        except Exception:
            return None
    if len(nums) < 2:
        return None
    step = nums[1] - nums[0]
    for i in range(2, len(nums)):
        if nums[i] - nums[i - 1] != step:
            return None
    return step


def fill_plan(seeds, count, downward):
    """The values a drag fill should write, as a plain list.

    seeds:    the selected cells' current text, top to bottom
    count:    how many cells to fill
    downward: True dragging down, False dragging up

    The rule, and it is the whole of the rule:
      - no number anywhere in the seed  ->  copy it
      - a number in the seed            ->  step it, in the drag direction
      - several seeds with an even gap  ->  keep that gap
      - several seeds without one       ->  repeat the block
    """
    if count <= 0:
        return []
    seeds = [to_text(s) for s in seeds]
    if not seeds:
        return []

    step = infer_step(seeds)

    if step is None and len(seeds) > 1:
        # a block with no series in it repeats, the way Excel repeats it
        out = []
        for i in range(count):
            src = seeds[i % len(seeds)] if downward else\
                seeds[-1 - (i % len(seeds))]
            out.append(src)
        return out

    if step is None:
        step = 1

    anchor = seeds[-1] if downward else seeds[0]
    if not has_number(anchor):
        return [anchor] * count            # plain text: copy, never invent

    direction = 1 if downward else -1
    if len(seeds) > 1:
        # an explicit gap keeps its own sign when dragged down, and is
        # mirrored when dragged up
        delta = step if downward else -step
    else:
        delta = direction * abs(step)

    return [series_value(anchor, delta, i + 1) for i in range(count)]


def series_value(seed, step, n):
    """seed text advanced by step*n, keeping any zero padding.

    Padding is kept only when the seed is actually zero-padded: SD-005 goes to
    SD-004, but AHU-10 goes to AHU-9 rather than AHU-09.
    """
    parts = split_number(seed)
    if parts is None:
        return seed
    prefix, digits, suffix = parts
    neg = digits.startswith('-')
    body = digits[1:] if neg else digits
    padded = len(body) > 1 and body.startswith('0')
    width = len(body) if padded else 0
    val = int(digits) + step * n
    sign = '-' if val < 0 else ''
    out = to_text(abs(val))
    if len(out) < width:
        out = '0' * (width - len(out)) + out
    return prefix + sign + out + suffix


def col_letter(index):
    """0 -> A, 25 -> Z, 26 -> AA. The reference used in formulas."""
    n = int(index)
    out = ''
    while True:
        out = chr(ord('A') + (n % 26)) + out
        n = n // 26 - 1
        if n < 0:
            break
    return out


# ============================================================ formula engine ==
#
# A small expression parser, deliberately not eval().  It knows column letters,
# text and numbers, & + - * / and comparisons, and the function set below.
# Everything is evaluated against one row at a time and written back as static
# text — the model never stores a formula.

class FormulaError(Exception):
    pass


_TOKEN_RE = re.compile(
    r'\s*(?:'
    r'(?P<num>\d+(?:\.\d+)?)'
    r'|(?P<dq>"(?:[^"]|"")*")'
    r"|(?P<sq>'(?:[^']|'')*')"
    r'|(?P<cell>[A-Za-z]{1,3}\$?[0-9]+)'
    r'|(?P<name>[A-Za-z_][A-Za-z_0-9]*)'
    r'|(?P<op><>|<=|>=|[&+\-*/()<>=,])'
    r')')


def _tokenize(text):
    tokens = []
    pos = 0
    n = len(text)
    while pos < n:
        if text[pos].isspace():
            pos += 1
            continue
        m = _TOKEN_RE.match(text, pos)
        if not m or m.end() == pos:
            raise FormulaError('cannot read "{0}"'.format(text[pos:pos + 12]))
        pos = m.end()
        if m.group('num') is not None:
            tokens.append(('num', float(m.group('num'))))
        elif m.group('dq') is not None:
            tokens.append(('str', m.group('dq')[1:-1].replace('""', '"')))
        elif m.group('sq') is not None:
            tokens.append(('str', m.group('sq')[1:-1].replace("''", "'")))
        elif m.group('cell') is not None:
            tokens.append(('cell', m.group('cell')))
        elif m.group('name') is not None:
            tokens.append(('name', m.group('name')))
        else:
            tokens.append(('op', m.group('op')))
    tokens.append(('end', None))
    return tokens


def as_text(value):
    if value is None:
        return ''
    if isinstance(value, float):
        if abs(value - round(value)) < 1e-9:
            return to_text(int(round(value)))
        out = '{0:.6f}'.format(value).rstrip('0').rstrip('.')
        return out
    return to_text(value)


def as_number(value, what='value'):
    if isinstance(value, float):
        return value
    text = to_text(value).strip()
    if not text:
        return 0.0
    text = text.replace(',', '')
    m = re.search(r'-?\d+(?:\.\d+)?', text)
    if not m:
        raise FormulaError('"{0}" is not a number'.format(what))
    return float(m.group(0))


def _pad(text, width):
    parts = split_number(text)
    if parts is None:
        return text
    prefix, digits, suffix = parts
    neg = digits.startswith('-')
    body = digits[1:] if neg else digits
    if len(body) < width:
        body = '0' * (width - len(body)) + body
    return prefix + ('-' if neg else '') + body + suffix


def _proper(text):
    out = []
    cap = True
    for ch in to_text(text):
        if ch.isalpha():
            out.append(ch.upper() if cap else ch.lower())
            cap = False
        else:
            out.append(ch)
            cap = True
    return ''.join(out)


def _fn(name, args, ctx):
    name = name.upper()
    def txt(i, default=''):
        return as_text(args[i]) if i < len(args) else default

    def num(i, default=0.0):
        return as_number(args[i], name) if i < len(args) else default

    if name in ('CONCAT', 'CONCATENATE', 'JOIN'):
        return ''.join([as_text(a) for a in args])
    if name == 'UPPER':
        return txt(0).upper()
    if name == 'LOWER':
        return txt(0).lower()
    if name == 'PROPER':
        return _proper(txt(0))
    if name == 'TRIM':
        return re.sub(r'\s+', ' ', txt(0)).strip()
    if name == 'LEN':
        return float(len(txt(0)))
    if name == 'LEFT':
        return txt(0)[:int(num(1, 1.0))]
    if name == 'RIGHT':
        k = int(num(1, 1.0))
        return txt(0)[-k:] if k > 0 else ''
    if name == 'MID':
        start = max(1, int(num(1, 1.0)))
        length = int(num(2, 1.0))
        return txt(0)[start - 1:start - 1 + length]
    if name in ('REPLACE', 'SUBSTITUTE'):
        return txt(0).replace(txt(1), txt(2))
    if name == 'PAD':
        return _pad(txt(0), int(num(1, 0.0)))
    if name == 'SEQ':
        start = num(0, 1.0)
        step = num(1, 1.0) if len(args) > 1 else 1.0
        value = start + step * (ctx.get('n', 1) - 1)
        text = as_text(value)
        if len(args) > 2:
            text = _pad(text, int(num(2, 0.0)))
        return text
    if name == 'ROUND':
        places = int(num(1, 0.0))
        value = round(num(0), places)
        return float(value)
    if name in ('VALUE', 'NUM'):
        return as_number(txt(0), name)
    if name == 'IF':
        test = args[0] if args else ''
        truthy = bool(test) if not isinstance(test, float) else test != 0.0
        if isinstance(test, bool):
            truthy = test
        return args[1] if truthy else (args[2] if len(args) > 2 else '')
    raise FormulaError('unknown function {0}()'.format(name))


class _Parser(object):

    def __init__(self, tokens, ctx):
        self.tokens = tokens
        self.i = 0
        self.ctx = ctx

    def peek(self):
        return self.tokens[self.i]

    def take(self):
        tok = self.tokens[self.i]
        self.i += 1
        return tok

    def expect_op(self, op):
        kind, value = self.take()
        if kind == 'end':
            raise FormulaError('a closing "{0}" is missing'.format(op))
        if kind != 'op' or value != op:
            raise FormulaError('expected "{0}"'.format(op))

    def parse(self):
        value = self.comparison()
        if self.peek()[0] != 'end':
            raise FormulaError('unexpected "{0}"'.format(as_text(self.peek()[1])))
        return value

    def comparison(self):
        left = self.concat()
        kind, value = self.peek()
        if kind == 'op' and value in ('=', '<>', '<', '>', '<=', '>='):
            self.take()
            right = self.concat()
            if isinstance(left, float) or isinstance(right, float):
                a, b = as_number(left), as_number(right)
            else:
                a, b = as_text(left), as_text(right)
            if value == '=':
                return a == b
            if value == '<>':
                return a != b
            if value == '<':
                return a < b
            if value == '>':
                return a > b
            if value == '<=':
                return a <= b
            return a >= b
        return left

    def concat(self):
        value = self.additive()
        while True:
            kind, op = self.peek()
            if kind == 'op' and op == '&':
                self.take()
                value = as_text(value) + as_text(self.additive())
            else:
                return value

    def additive(self):
        value = self.multiplicative()
        while True:
            kind, op = self.peek()
            if kind == 'op' and op in ('+', '-'):
                self.take()
                right = self.multiplicative()
                value = as_number(value) + as_number(right) if op == '+'\
                    else as_number(value) - as_number(right)
            else:
                return value

    def multiplicative(self):
        value = self.unary()
        while True:
            kind, op = self.peek()
            if kind == 'op' and op in ('*', '/'):
                self.take()
                right = as_number(self.unary())
                if op == '*':
                    value = as_number(value) * right
                else:
                    if right == 0:
                        raise FormulaError('division by zero')
                    value = as_number(value) / right
            else:
                return value

    def unary(self):
        kind, op = self.peek()
        if kind == 'op' and op == '-':
            self.take()
            return -as_number(self.unary())
        if kind == 'op' and op == '+':
            self.take()
            return self.unary()
        return self.primary()

    def primary(self):
        kind, value = self.take()
        if kind == 'num':
            return value
        if kind == 'str':
            return value
        if kind == 'op' and value == '(':
            inner = self.comparison()
            self.expect_op(')')
            return inner
        if kind == 'end':
            raise FormulaError('the formula ends before it is finished')
        if kind == 'cell':
            return self.cell_reference(value)
        if kind == 'name':
            nxt_kind, nxt_val = self.peek()
            if nxt_kind == 'op' and nxt_val == '(':
                self.take()
                args = []
                if not (self.peek()[0] == 'op' and self.peek()[1] == ')'):
                    while True:
                        args.append(self.comparison())
                        k, v = self.peek()
                        if k == 'op' and v == ',':
                            self.take()
                            continue
                        break
                self.expect_op(')')
                return _fn(value, args, self.ctx)
            return self.reference(value)
        raise FormulaError('unexpected "{0}"'.format(as_text(value)))

    def cell_reference(self, text):
        """A5 and A$5 — a column letter with a row number.

        Relative like Excel: A5 written against row 5 means "this row", and the
        same formula on row 6 reads A6. A$5 locks the row. A bare letter is the
        short way of writing the same-row form.
        """
        m = re.match(r'^([A-Za-z]{1,3})(\$?)([0-9]+)$', text)
        if m is None:
            raise FormulaError('"{0}" is not a cell'.format(text))
        column = m.group(1).upper()
        locked = m.group(2) == '$'
        want = int(m.group(3))
        cells = self.ctx.get('cells') or {}
        if column not in cells:
            raise FormulaError(
                'there is no column {0} in this schedule'.format(column))
        if locked:
            row = want
        else:
            anchor = int(self.ctx.get('anchor', self.ctx.get('row', want)) or want)
            row = int(self.ctx.get('row', want)) + (want - anchor)
        lookup = self.ctx.get('lookup')
        if lookup is None:
            raise FormulaError('cell references are not available here')
        value = lookup(column, row)
        if value is None:
            raise FormulaError('row {0} is not in this schedule'.format(row))
        return value

    def reference(self, name):
        upper = name.upper()
        if upper == 'ROW':
            return float(self.ctx.get('row', 0))
        if upper in ('N', 'INDEX'):
            return float(self.ctx.get('n', 0))
        if upper == 'ID':
            return self.ctx.get('id', '')
        if upper == 'THIS':
            return self.ctx.get('this', '')
        cells = self.ctx.get('cells') or {}
        if upper in cells:
            return cells[upper]
        if re.match(r'^[A-Z]+$', upper):
            raise FormulaError('there is no column {0} in this schedule'.format(upper))
        raise FormulaError('unknown name "{0}"'.format(name))


def evaluate_formula(text, ctx):
    """Evaluate one formula against one row. Raises FormulaError."""
    body = to_text(text).strip()
    if body.startswith('='):
        body = body[1:]
    if not body:
        raise FormulaError('the formula is empty')
    result = _Parser(_tokenize(body), ctx).parse()
    if isinstance(result, bool):
        return 'TRUE' if result else 'FALSE'
    return as_text(result)


FORMULA_REF_COLOURS = ('C_BLUE', 'C_GREEN', 'C_TEST_FG', 'C_IMP_FG',
                       'C_COPY_FG', 'C_RO_FG')


def formula_spans(text):
    """Break a formula into (start, length, kind, key) runs, for colouring.

    kind is one of: plain, func, cell, text, number, op. `key` groups the cell
    references — every mention of the same cell gets the same key, so the same
    colour, which is what makes a long formula readable at a glance.

    `=`, `(`, `)` and `,` stay plain deliberately: they are punctuation, and
    colouring them adds noise without adding meaning.
    """
    spans = []
    body = to_text(text)
    i = 0
    n = len(body)
    while i < n:
        ch = body[i]
        if ch in '="\'':
            pass
        if ch == '=' and i == 0:
            spans.append((i, 1, 'plain', None))
            i += 1
            continue
        if ch in '(),':
            spans.append((i, 1, 'plain', None))
            i += 1
            continue
        if ch in '"\'':
            quote = ch
            j = i + 1
            while j < n:
                if body[j] == quote:
                    if j + 1 < n and body[j + 1] == quote:
                        j += 2
                        continue
                    j += 1
                    break
                j += 1
            spans.append((i, j - i, 'text', None))
            i = j
            continue
        m = re.match(r'[A-Za-z]{1,3}\$?[0-9]+', body[i:])
        if m and (i == 0 or not (body[i - 1].isalnum() or body[i - 1] == '_')):
            token = m.group(0)
            spans.append((i, len(token), 'cell', token.upper().replace('$', '')))
            i += len(token)
            continue
        m = re.match(r'[A-Za-z_][A-Za-z_0-9]*', body[i:])
        if m:
            word = m.group(0)
            after = body[i + len(word):].lstrip()
            kind = 'func' if after.startswith('(') else 'cell'
            key = None if kind == 'func' else word.upper()
            spans.append((i, len(word), kind, key))
            i += len(word)
            continue
        m = re.match(r'[0-9]+(\.[0-9]+)?', body[i:])
        if m:
            spans.append((i, len(m.group(0)), 'number', None))
            i += len(m.group(0))
            continue
        if ch in '&+-*/<>':
            spans.append((i, 1, 'op', None))
            i += 1
            continue
        spans.append((i, 1, 'plain', None))
        i += 1
    return spans


def formula_ref_colour(key, order):
    """A stable colour per distinct reference, in the order they first appear."""
    if key not in order:
        order.append(key)
    name = FORMULA_REF_COLOURS[order.index(key) % len(FORMULA_REF_COLOURS)]
    return globals().get(name, '#4FA3E3')


def default_3d_rank(name):
    """How good a candidate a 3D view is, lowest first.

    Revit's own default is called {3D}; a per-user one is {3D - someone}. Both
    beat a named working view, and a named view beats nothing at all.
    """
    text = to_text(name).strip()
    if text == '{3D}':
        return 0
    if text.startswith('{3D'):
        return 1
    return 2


def find_duplicates(values):
    """Values that appear more than once, blanks excluded, in natural order.

    Blanks are left out: an empty cell repeated forty times is not the kind of
    duplicate anyone is hunting for, and counting them would drown the real
    ones.
    """
    counts = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return [v for v in sorted(counts.keys(), key=lambda v: natural_key(v))
            if counts[v] > 1 and to_text(v).strip()]


def sql_like_escape(term):
    out = []
    for ch in to_text(term):
        if ch == "'":
            out.append("''")
        elif ch in '[]%*':
            out.append('[' + ch + ']')
        else:
            out.append(ch)
    return ''.join(out)


def _hint(text):
    tb = _tb(text, C_MUTED, 11, False, True)
    tb.Margin = Thickness(0, 6, 0, 0)
    return tb


def _field_row(label, control, note=None):
    """Label above a control, as one block for the dialog body."""
    panel = StackPanel()
    panel.Margin = Thickness(0, 10, 0, 0)
    cap = _tb(label, C_TEXT, 12, True)
    cap.Margin = Thickness(0, 0, 0, 4)
    panel.Children.Add(cap)
    panel.Children.Add(control)
    if note:
        panel.Children.Add(_hint(note))
    return panel


class CellToolDialog(object):
    """Shared frame for the three cell tools: a live preview over the selection."""

    def __init__(self, host, subtitle, width=620):
        self.host = host
        self.cells = host.sel_cells()
        self.dlg = ThemedDialog(subtitle, width=width, owner=host.window, accent=C_ORANGE)
        self.preview = _tb('', C_MUTED, 11, False, True)
        self.preview.FontFamily = System.Windows.Media.FontFamily('Consolas')
        self.applied = 0

    def writable(self):
        """Selected cells that can actually take a value, in visual order."""
        out = []
        for c in self.cells:
            try:
                if self.host.model.rows[c['ridx']].cells[c['fidx']].editable:
                    out.append(c)
            except Exception:
                continue
        return out

    def add_preview(self):
        box = Border()
        box.Background = brush(C_FIELD)
        box.BorderBrush = brush(C_EDGE)
        box.BorderThickness = Thickness(1)
        box.CornerRadius = CornerRadius(3)
        box.Padding = Thickness(10, 8, 10, 8)
        box.Margin = Thickness(0, 12, 0, 0)
        inner = StackPanel()
        cap = _tb('Preview', C_BLUE, 11, True)
        cap.Margin = Thickness(0, 0, 0, 4)
        inner.Children.Add(cap)
        inner.Children.Add(self.preview)
        box.Child = inner
        self.dlg.add(box)

    def set_preview(self, lines, colour=C_MUTED):
        try:
            self.preview.Text = '\n'.join(lines) if lines else u'—'
            self.preview.Foreground = brush(colour)
        except Exception:
            pass

    def write(self, values):
        """values: [(cell, text), ...] staged as one undo batch."""
        host = self.host
        host.begin_batch()
        n = 0
        for cell, text in values:
            if host.stage_cell(cell['pos'], cell['col'], text):
                n += 1
        host.end_batch()
        self.applied = n
        return n


def sequence_dialog(host):
    """Number the selection: start, step, padding, prefix and suffix."""
    tool = CellToolDialog(host, 'Number Sequence', width=600)
    cells = tool.writable()
    if not cells:
        themed_message('Number Sequence', 'Select the editable cells to number first.',
                       owner=host.window)
        return

    tool.dlg.add(_tb('The selection is numbered top to bottom. Where the selection '
                     'covers more than one column, each column starts again.',
                     C_TEXT, 12, False, True))

    saved = host.seq_settings
    start = _dark_textbox(width=110, text=saved.get('start', '001'))
    step = _dark_textbox(width=110, text=saved.get('step', '1'))
    pad = _dark_textbox(width=110, text=saved.get('pad', '0'))
    prefix = _dark_textbox(width=240, text=saved.get('prefix', ''))
    suffix = _dark_textbox(width=240, text=saved.get('suffix', ''))
    keep = _dark_check('Keep the existing cell text in front of the number',
                       saved.get('keep', False))

    numbers = StackPanel()
    numbers.Orientation = Orientation.Horizontal
    for label, ctrl in (('Start', start), ('Step', step), ('Pad to digits', pad)):
        block = _field_row(label, ctrl)
        block.Margin = Thickness(0, 10, 16, 0)
        numbers.Children.Add(block)
    tool.dlg.add(numbers)
    tool.dlg.add(_hint(
        u'Leading zeros in the start number set the width: 001 gives 001, 002, '
        '003 and rolls on to 010 and 100; 01 gives 01, 02, 03. Pad to digits is '
        'there to force a wider field than the start number implies — leave it '
        'at 0 to take the width from the start number.'))

    texts = StackPanel()
    texts.Orientation = Orientation.Horizontal
    tb1 = _field_row('Prefix', prefix)
    tb1.Margin = Thickness(0, 10, 16, 0)
    texts.Children.Add(tb1)
    texts.Children.Add(_field_row('Suffix', suffix))
    tool.dlg.add(texts)

    keep.Margin = Thickness(0, 12, 0, 0)
    tool.dlg.add(keep)
    tool.add_preview()

    state = {'values': [], 'ok': False}

    def recompute(*_args):
        raw_start = to_text(start.Text).strip() or '1'
        try:
            s0 = int(float(raw_start))
            st = int(float(to_text(step.Text).strip() or '1'))
            pd = int(float(to_text(pad.Text).strip() or '0'))
        except Exception:
            state['ok'] = False
            tool.set_preview(['Start, step and padding must be whole numbers.'], C_FAIL_FG)
            return
        # 001 means three digits, 01 means two — the start number carries the
        # width, and the pad box can only widen it further
        digits = raw_start[1:] if raw_start.startswith('-') else raw_start
        if digits.startswith('0') and len(digits) > 1:
            pd = max(pd, len(digits))
        by_col = {}
        for cell in cells:
            by_col.setdefault(cell['col'].DisplayIndex, []).append(cell)
        values = []
        for disp in sorted(by_col.keys()):
            group = sorted(by_col[disp], key=lambda d: d['pos'])
            for i, cell in enumerate(group):
                body = to_text(s0 + st * i)
                if pd > 0:
                    neg = body.startswith('-')
                    digits = body[1:] if neg else body
                    if len(digits) < pd:
                        digits = '0' * (pd - len(digits)) + digits
                    body = ('-' if neg else '') + digits
                text = to_text(prefix.Text) + body + to_text(suffix.Text)
                if keep.IsChecked:
                    text = to_text(host.text_at(cell['pos'], cell['col'])) + text
                values.append((cell, text))
        state['values'] = values
        state['ok'] = bool(values)
        lines = [v[1] for v in values[:4]]
        if len(values) > len(lines):
            lines.append('... {0} cells in total'.format(len(values)))
        tool.set_preview(lines, C_EDIT_FG)

    for ctrl in (start, step, pad, prefix, suffix):
        try:
            ctrl.TextChanged += recompute
        except Exception:
            pass
    try:
        keep.Checked += recompute
        keep.Unchecked += recompute
    except Exception:
        pass
    recompute()

    def apply_now():
        recompute()
        if not state['ok']:
            return
        host.seq_settings = {'start': to_text(start.Text), 'step': to_text(step.Text),
                             'pad': to_text(pad.Text), 'prefix': to_text(prefix.Text),
                             'suffix': to_text(suffix.Text), 'keep': bool(keep.IsChecked)}
        n = tool.write(state['values'])
        host.set_status('Numbered {0} cell{1}.'.format(n, '' if n == 1 else 's'))
        tool.dlg.result = 'apply'
        try:
            tool.dlg.window.DialogResult = True
        except Exception:
            pass
        tool.dlg.window.Close()

    tool.dlg.add_button('Cancel', 'ghost', 'cancel')
    tool.dlg.add_button('Number {0} cell{1}'.format(
        len(cells), '' if len(cells) == 1 else 's'), 'green', 'apply',
        close=False, handler=apply_now)
    tool.dlg.show()


def affix_dialog(host):
    """Add a prefix and/or suffix to what the selected cells already hold."""
    tool = CellToolDialog(host, 'Add Prefix / Suffix', width=600)
    cells = tool.writable()
    if not cells:
        themed_message('Add Prefix / Suffix',
                       'Select the editable cells to add to first.', owner=host.window)
        return

    tool.dlg.add(_tb('The text is wrapped around whatever each selected cell already '
                     'holds. Nothing is written until APPLY on the main window.',
                     C_TEXT, 12, False, True))

    saved = host.affix_settings
    prefix = _dark_textbox(width=260, text=saved.get('prefix', ''))
    suffix = _dark_textbox(width=260, text=saved.get('suffix', ''))
    skip_empty = _dark_check('Leave empty cells alone', saved.get('skip_empty', True))
    skip_have = _dark_check('Skip cells that already start with the prefix',
                            saved.get('skip_have', True))

    row = StackPanel()
    row.Orientation = Orientation.Horizontal
    block = _field_row('Prefix', prefix)
    block.Margin = Thickness(0, 10, 16, 0)
    row.Children.Add(block)
    row.Children.Add(_field_row('Suffix', suffix))
    tool.dlg.add(row)

    skip_empty.Margin = Thickness(0, 12, 0, 0)
    skip_have.Margin = Thickness(0, 6, 0, 0)
    tool.dlg.add(skip_empty)
    tool.dlg.add(skip_have)
    tool.add_preview()

    state = {'values': [], 'skipped': 0}

    def recompute(*_args):
        pre = to_text(prefix.Text)
        suf = to_text(suffix.Text)
        values = []
        skipped = 0
        for cell in cells:
            current = to_text(host.text_at(cell['pos'], cell['col']))
            if skip_empty.IsChecked and not current.strip():
                skipped += 1
                continue
            if skip_have.IsChecked and pre and current.startswith(pre):
                skipped += 1
                continue
            values.append((cell, pre + current + suf))
        state['values'] = values
        state['skipped'] = skipped
        lines = ['{0}  ->  {1}'.format(
            to_text(host.text_at(c['pos'], c['col'])) or '(empty)', t)
            for c, t in values[:4]]
        if len(values) > len(lines):
            lines.append('... {0} cells in total'.format(len(values)))
        if skipped:
            lines.append('{0} cell{1} left alone'.format(
                skipped, '' if skipped == 1 else 's'))
        tool.set_preview(lines, C_EDIT_FG if values else C_MUTED)

    for ctrl in (prefix, suffix):
        try:
            ctrl.TextChanged += recompute
        except Exception:
            pass
    for chk in (skip_empty, skip_have):
        try:
            chk.Checked += recompute
            chk.Unchecked += recompute
        except Exception:
            pass
    recompute()

    def apply_now():
        recompute()
        if not state['values']:
            return
        host.affix_settings = {'prefix': to_text(prefix.Text),
                               'suffix': to_text(suffix.Text),
                               'skip_empty': bool(skip_empty.IsChecked),
                               'skip_have': bool(skip_have.IsChecked)}
        n = tool.write(state['values'])
        extra = ''
        if state['skipped']:
            extra = ', {0} left alone'.format(state['skipped'])
        host.set_status('Prefix / suffix wrote {0} cell{1}{2}.'.format(
            n, '' if n == 1 else 's', extra))
        tool.dlg.result = 'apply'
        try:
            tool.dlg.window.DialogResult = True
        except Exception:
            pass
        tool.dlg.window.Close()

    tool.dlg.add_button('Cancel', 'ghost', 'cancel')
    tool.dlg.add_button('Add to selection', 'green', 'apply',
                        close=False, handler=apply_now)
    tool.dlg.show()


ICONS_DIR = os.path.join(SCRIPT_DIR, 'icons')

SETTINGS_DIR = os.path.join(os.environ.get('APPDATA', SCRIPT_DIR), 'RevoBIM PY')
SETTINGS_PATH = os.path.join(SETTINGS_DIR, 'excel_for_revit_settings.json')


def _forms():
    """WinForms dialogs, imported late so a missing assembly cannot kill load."""
    import System.Windows.Forms as WinForms
    return WinForms


def remembered_folder():
    """Where the last export or import went. Falls back to Documents."""
    folder = to_text(load_settings().get('excel_folder', ''))
    if folder and os.path.isdir(folder):
        return folder
    try:
        docs = os.path.join(os.environ.get('USERPROFILE', ''), 'Documents')
        if os.path.isdir(docs):
            return docs
    except Exception:
        pass
    return ''


def remember_folder(path):
    try:
        folder = os.path.dirname(path)
        if folder:
            save_settings({'excel_folder': folder})
    except Exception:
        pass


def ask_save_path(suggested_name):
    """Windows Save As, opening where the last one went."""
    try:
        WinForms = _forms()
        dialog = WinForms.SaveFileDialog()
        dialog.Title = 'Export to Excel'
        dialog.Filter = 'Excel workbook (*.xlsx)|*.xlsx'
        dialog.DefaultExt = 'xlsx'
        dialog.AddExtension = True
        dialog.OverwritePrompt = True
        dialog.FileName = safe_filename(suggested_name)
        folder = remembered_folder()
        if folder:
            dialog.InitialDirectory = folder
        if dialog.ShowDialog() != WinForms.DialogResult.OK:
            return None
        return dialog.FileName
    except Exception:
        return None


def ask_open_path():
    try:
        WinForms = _forms()
        dialog = WinForms.OpenFileDialog()
        dialog.Title = 'Import from Excel'
        dialog.Filter = 'Excel workbook (*.xlsx)|*.xlsx'
        dialog.Multiselect = False
        folder = remembered_folder()
        if folder:
            dialog.InitialDirectory = folder
        if dialog.ShowDialog() != WinForms.DialogResult.OK:
            return None
        return dialog.FileName
    except Exception:
        return None


def safe_filename(name):
    out = re.sub(r'[<>:"/\\|?*]', '-', to_text(name)).strip() or 'Schedule'
    return out[:120] + '.xlsx'


def reveal_in_explorer(path):
    """Open the containing folder with the file selected."""
    try:
        import System.Diagnostics as Diagnostics
        Diagnostics.Process.Start('explorer.exe', '/select,"{0}"'.format(path))
        return True
    except Exception:
        pass
    try:
        import System.Diagnostics as Diagnostics
        Diagnostics.Process.Start(os.path.dirname(path))
        return True
    except Exception:
        return False


def load_settings():
    try:
        if os.path.isfile(SETTINGS_PATH):
            handle = open(SETTINGS_PATH, 'r')
            try:
                return json.loads(handle.read() or '{}') or {}
            finally:
                handle.close()
    except Exception:
        pass
    return {}


def save_settings(values):
    """Merge and write. Never allowed to interrupt the tool."""
    try:
        if not os.path.isdir(SETTINGS_DIR):
            os.makedirs(SETTINGS_DIR)
        current = load_settings()
        current.update(values or {})
        handle = open(SETTINGS_PATH, 'w')
        try:
            handle.write(json.dumps(current, indent=2))
        finally:
            handle.close()
    except Exception:
        pass
_ICON_CACHE = {}


def toolbar_icon(name):
    """Themed 24px glyph. <name>.png on dark, <name>.light.png on light."""
    suffix = '.light.png' if THEME_NAME == 'light' else '.png'
    path = os.path.join(ICONS_DIR, name + suffix)
    if path in _ICON_CACHE:
        return _ICON_CACHE[path]
    img = None
    try:
        if os.path.isfile(path):
            img = load_image(path)
    except Exception:
        img = None
    _ICON_CACHE[path] = img
    return img


def build_wide_button(button, icon_name, label, tooltip=None):
    """Icon beside the label, for the footer, where a stacked one is too tall."""
    stack = StackPanel()
    stack.Orientation = Orientation.Horizontal
    stack.HorizontalAlignment = HorizontalAlignment.Center
    image = Image()
    image.Width = 26
    image.Height = 26
    image.Margin = Thickness(0, 0, 8, 0)
    image.VerticalAlignment = VerticalAlignment.Center
    try:
        image.Source = toolbar_icon(icon_name)
    except Exception:
        pass
    stack.Children.Add(image)
    text = _tb(label, C_TEXT, 12.5, True)
    text.VerticalAlignment = VerticalAlignment.Center
    stack.Children.Add(text)
    button.Content = stack
    if tooltip:
        button.ToolTip = tooltip
    button.Tag = (icon_name, image, text)
    return button


def build_tool_button(button, icon_name, label, tooltip):
    """Icon above text, so the strip reads as a ribbon rather than a word soup."""
    stack = StackPanel()
    stack.Orientation = Orientation.Vertical
    stack.HorizontalAlignment = HorizontalAlignment.Center
    image = Image()
    image.Width = 22
    image.Height = 22
    image.Margin = Thickness(0, 0, 0, 3)
    image.HorizontalAlignment = HorizontalAlignment.Center
    try:
        image.Source = toolbar_icon(icon_name)
    except Exception:
        pass
    stack.Children.Add(image)
    text = _tb(label, C_TEXT, 10.5)
    text.HorizontalAlignment = HorizontalAlignment.Center
    stack.Children.Add(text)
    button.Content = stack
    button.Padding = Thickness(8, 5, 8, 4)
    button.MinWidth = 58
    button.Margin = Thickness(1, 0, 1, 0)
    if tooltip:
        button.ToolTip = tooltip
    button.Tag = (icon_name, image, text)
    return button


def highlight_dialog(host):
    """Colour cells, whole rows or whole columns. Keyed on the data, not the view."""
    dlg = ThemedDialog('Highlight', width=560, owner=host.window, accent=C_ORANGE)
    cells = host.sel_cells()

    dlg.add(_tb(u'Highlights are held against the element and the column, so they '
                'stay with the data when the grid is filtered, sorted or '
                'reloaded. They are a working aid — nothing is written to the '
                'model, and a staged edit or a refusal still shows through.',
                C_TEXT, 12, False, True))

    saved = host.hl_settings
    state = {'colour': saved.get('colour', 'Yellow'),
             'mode': saved.get('mode', 'fill'),
             'scope': saved.get('scope', 'cells')}

    swatch_row = WrapPanel()
    swatch_row.Margin = Thickness(0, 12, 0, 0)
    swatches = {}

    def select_colour(name):
        state['colour'] = name
        for key, border in swatches.items():
            border.BorderThickness = Thickness(3 if key == name else 1)
            border.BorderBrush = brush(C_TEXT if key == name else C_EDGE)

    def make_swatch(name):
        bg, fg = highlight_colours(name)
        b = Border()
        b.Background = brush(bg)
        b.BorderBrush = brush(C_EDGE)
        b.BorderThickness = Thickness(1)
        b.CornerRadius = CornerRadius(3)
        b.Width = 60
        b.Height = 34
        b.Margin = Thickness(0, 0, 6, 6)
        b.Cursor = Cursors.Hand
        label = _tb(name, fg, 11, True)
        label.HorizontalAlignment = HorizontalAlignment.Center
        label.VerticalAlignment = VerticalAlignment.Center
        b.Child = label

        def _click(sender, args):
            select_colour(name)
        try:
            b.MouseLeftButtonUp += _click
        except Exception:
            pass
        swatches[name] = b
        return b

    for name in HIGHLIGHT_COLOURS:
        swatch_row.Children.Add(make_swatch(name))
    dlg.add(_field_row('Colour', swatch_row))
    select_colour(state['colour'])

    def radio_group(label, options, key):
        panel = StackPanel()
        panel.Orientation = Orientation.Horizontal
        buttons = {}

        def choose(value):
            state[key] = value
            for k, btn in buttons.items():
                btn.IsChecked = (k == value)

        for value, caption in options:
            rb = RadioButton()
            rb.Content = caption
            rb.Foreground = brush(C_TEXT)
            rb.Margin = Thickness(0, 0, 16, 0)
            rb.GroupName = key
            rb.IsChecked = (state[key] == value)

            def _make(v):
                def _checked(sender, args):
                    state[key] = v
                return _checked
            try:
                rb.Checked += _make(value)
            except Exception:
                pass
            buttons[value] = rb
            panel.Children.Add(rb)
        return _field_row(label, panel)

    dlg.add(radio_group('Apply to', (('cells', 'Selected cells'),
                                     ('rows', 'Whole rows'),
                                     ('cols', 'Whole columns')), 'scope'))
    dlg.add(radio_group('Style', (('fill', 'Fill'),
                                  ('text', 'Text colour'),
                                  ('both', 'Fill and text')), 'mode'))

    count = _tb('{0} cell{1} selected.'.format(len(cells), '' if len(cells) == 1 else 's'),
                C_MUTED, 11, False, True)
    count.Margin = Thickness(0, 12, 0, 0)
    dlg.add(count)

    def do_apply():
        host.hl_settings = dict(state)
        n = host.apply_highlight(state['colour'], state['mode'], state['scope'])
        if n:
            noun = {'cells': 'cell', 'rows': 'row', 'cols': 'column'}[state['scope']]
            host.set_status('Highlighted {0} {1}{2} in {3}.'.format(
                n, noun, '' if n == 1 else 's', state['colour'].lower()))

    def do_clear_sel():
        n = host.clear_highlight('selection')
        host.set_status('Cleared {0} highlight{1}.'.format(n, '' if n == 1 else 's'))

    def do_clear_all():
        n = host.clear_highlight('all')
        host.set_status('Cleared all {0} highlight{1}.'.format(n, '' if n == 1 else 's'))

    dlg.add_button('Close', 'ghost', 'close')
    dlg.add_button('Clear all', 'red', None, close=False, handler=do_clear_all)
    dlg.add_button('Clear from selection', 'orange', None, close=False, handler=do_clear_sel)
    dlg.add_button('Highlight', 'green', None, close=False, handler=do_apply)
    dlg.show()


def export_dialog(host):
    """Pick which of the two exports, then Save As."""
    if excel_bridge is None:
        themed_message('Export to Excel',
                       'The Excel module could not be loaded:\n\n' + EXCEL_ERROR,
                       accent=C_RED, width=680, owner=host.window)
        return

    dlg = ThemedDialog('Export to Excel', width=680, owner=host.window, accent=C_ORANGE)
    dlg.add(_tb('Two exports, for two different jobs.', C_TEXT, 12, False, True))

    state = {'kind': to_text(load_settings().get('excel_export_kind', 'round')) or 'round'}
    picks = {}

    def choose(kind):
        state['kind'] = kind
        for key, border in picks.items():
            on = (key == kind)
            border.BorderBrush = brush(C_GREEN if on else C_EDGE)
            border.BorderThickness = Thickness(2 if on else 1)
            border.Background = brush(C_EDIT_BG if on else C_FIELD)

    def card(kind, title, lines):
        b = Border()
        b.CornerRadius = CornerRadius(4)
        b.Padding = Thickness(12, 10, 12, 10)
        b.Margin = Thickness(0, 10, 0, 0)
        b.Cursor = Cursors.Hand
        stack = StackPanel()
        head = _tb(title, C_TEXT, 13, True)
        stack.Children.Add(head)
        body = _tb(lines, C_MUTED, 11.5, False, True)
        body.Margin = Thickness(0, 5, 0, 0)
        stack.Children.Add(body)
        b.Child = stack

        def _click(sender, args):
            choose(kind)
        try:
            b.MouseLeftButtonUp += _click
        except Exception:
            pass
        picks[kind] = b
        return b

    dlg.add(card('round', u'Round trip — edit in Excel and bring it back',
                 u'A flat list with a Revit ID column, filters on, and every value '
                 'column coloured the way this grid colours it: blue for instance '
                 'parameters, orange for type parameters, red for anything read '
                 'only. Sort and filter it in Excel as much as you like — rows '
                 'come back matched on the Revit ID, not on their position. A '
                 'second sheet carries the legend.'))
    dlg.add(card('clean', u'Presentation — a clean sheet to issue',
                 'Title band, headers, borders, banded rows, column widths sized '
                 'to the content and text wrapped where it needs to be. Numbers '
                 'come through as numbers so Excel can total them. One '
                 'direction only: it carries no Revit IDs and cannot be '
                 'imported back.'))
    choose(state['kind'])

    dlg.add_button('Cancel', 'ghost', 'cancel')
    dlg.add_button('Choose a location...', 'green', 'go')
    if dlg.show() != 'go':
        return

    kind = state['kind']
    save_settings({'excel_export_kind': kind})
    model = host.model
    name = elem_name(model.sched)
    suffix = '' if kind == 'clean' else ' (editable)'
    path = ask_save_path(name + suffix)
    if not path:
        return
    if not path.lower().endswith('.xlsx'):
        path += '.xlsx'

    fields, rows = host.export_payload()
    try:
        doc_title = to_text(host.doc.Title)
    except Exception:
        doc_title = ''
    try:
        if kind == 'clean':
            count = excel_bridge.export_presentation(path, name, fields, rows, doc_title)
        else:
            count = excel_bridge.export_round_trip(path, name, fields, rows, doc_title)
    except Exception:
        themed_message('Export to Excel',
                       'The workbook could not be written:\n\n' + traceback.format_exc(),
                       accent=C_RED, width=700, owner=host.window)
        return

    remember_folder(path)
    host.set_status('Exported {0} rows to {1}.'.format(count, os.path.basename(path)))

    done = ThemedDialog('Exported', width=620, owner=host.window, accent=C_GREEN)
    done.add(_tb('{0} row{1} exported'.format(count, '' if count == 1 else 's'),
                 C_GREEN, 22, True))
    where = _tb(path, C_MUTED, 11, False, True)
    where.Margin = Thickness(0, 8, 0, 0)
    done.add(where)
    if kind == 'round':
        note = _tb('Edit the coloured columns, save, then use Import from Excel '
                   'on the toolbar. Read-only columns are ignored on the way back.',
                   C_TEXT, 12, False, True)
    else:
        note = _tb('This layout is for issuing. Use the round-trip export if you '
                   'want to edit in Excel and bring the changes back.',
                   C_TEXT, 12, False, True)
    note.Margin = Thickness(0, 12, 0, 0)
    done.add(note)
    done.add_button('Close', 'ghost', 'close')
    done.add_button('Open file location', 'green', 'open')
    if done.show() == 'open':
        reveal_in_explorer(path)


def import_report(host, res, path):
    """What the file would do, before anything is staged."""
    ok = len(res.changes)
    accent = C_GREEN if ok else C_ORANGE
    dlg = ThemedDialog('Import from Excel', width=700, owner=host.window, accent=accent)

    dlg.add(_tb('{0} change{1} found'.format(ok, '' if ok == 1 else 's'),
                accent, 24, True))
    sub = _tb(os.path.basename(path), C_MUTED, 11, False, True)
    sub.Margin = Thickness(0, 6, 0, 0)
    dlg.add(sub)

    lines = ['{0} row{1} read, {2} matched this schedule.'.format(
        res.rows_seen, '' if res.rows_seen == 1 else 's',
        res.rows_seen - len(res.unmatched_rows)),
        '{0} value{1} already matched the model and were left alone.'.format(
            res.unchanged, '' if res.unchanged == 1 else 's'),
        '{0} column{1} matched by heading.'.format(
            len(res.matched_cols), '' if len(res.matched_cols) == 1 else 's')]
    body = _tb('\n'.join(lines), C_TEXT, 12, False, True)
    body.Margin = Thickness(0, 12, 0, 0)
    dlg.add(body)

    def block(title, colour, items, formatter):
        if not items:
            return
        cap = _tb(title, colour, 12, True, True)
        cap.Margin = Thickness(0, 14, 0, 6)
        dlg.add(cap)
        box = Border()
        box.Background = brush(C_FIELD)
        box.BorderBrush = brush(C_EDGE)
        box.BorderThickness = Thickness(1)
        box.CornerRadius = CornerRadius(3)
        box.Padding = Thickness(8)
        sv = ScrollViewer()
        sv.MaxHeight = 150
        sv.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
        stack = StackPanel()
        for item in items[:200]:
            t = _tb(formatter(item), C_MUTED, 11, False, True)
            t.Margin = Thickness(0, 1, 0, 1)
            stack.Children.Add(t)
        if len(items) > 200:
            stack.Children.Add(_tb('... and {0} more'.format(len(items) - 200),
                                   C_MUTED, 11, False, True))
        sv.Content = stack
        box.Child = sv
        dlg.add(box)

    block('Will be staged:', C_GREEN, res.changes,
          lambda c: u'{0}  \u2022  {1}:  {2}  \u2192  {3}'.format(
              c[0], host.model.fields[c[1]].name, c[2] or '(empty)', c[3] or '(empty)'))
    block(u'Ignored — the parameter is read only in Revit:', C_RO_FG,
          res.skipped_readonly, lambda c: u'{0}  \u2022  {1}'.format(c[0], c[1]))
    block(u'Ignored — no element with that Revit ID in this schedule:', C_RED,
          res.unmatched_rows, lambda c: to_text(c))
    block(u'Ignored — no column of that name in this schedule:', C_RED,
          res.unmatched_cols, lambda c: to_text(c))

    tail = _tb('Nothing is written to the model yet. Staged changes show green '
               'in the grid; press APPLY when you are happy with them.',
               C_TEXT, 12, False, True)
    tail.Margin = Thickness(0, 14, 0, 0)
    dlg.add(tail)

    dlg.add_button('Cancel', 'ghost', 'cancel')
    if ok:
        dlg.add_button('Stage {0} change{1}'.format(ok, '' if ok == 1 else 's'),
                       'green', 'stage')
    else:
        dlg.add_button('Close', 'green', 'cancel')
    return dlg.show()


def tick_filter_dialog(host, fi):
    """Excel's autofilter: everything ticked means no filter, unticking narrows."""
    values = host.column_values(fi)
    dlg = ThemedDialog(u'Filter — {0}'.format(fi.name), width=460,
                       owner=host.window, accent=C_ORANGE)
    hidden = host.column_values_limited(fi)
    if hidden:
        limited = _tb(u'Showing the {0} value{1} the other columns\' filters '
                      u'allow. {2} more {3} in this column but filtered out '
                      u'elsewhere.'.format(
                          len(values), '' if len(values) == 1 else 's', hidden,
                          'is' if hidden == 1 else 'are'),
                      C_BLUE, 11, False, True)
        limited.Margin = Thickness(0, 0, 0, 8)
        dlg.add(limited)

    stale = host.stale_rows()
    if stale:
        note = _tb('{0} row{1} on screen no longer match{2} the current filters. '
                   'They are kept visible so they can still be edited and copied '
                   'from; applying here reapplies everything.'.format(
                       stale, '' if stale == 1 else 's',
                       'es' if stale == 1 else ''),
                   C_ORANGE, 11, False, True)
        note.Margin = Thickness(0, 0, 0, 8)
        dlg.add(note)

    current = host.col_picks.get(fi.index)
    boxes = []

    search = _dark_textbox(width=400)
    search.Tag = 'Search these values'
    dlg.add(_field_row('', search))

    holder = Border()
    holder.Background = brush(C_FIELD)
    holder.BorderBrush = brush(C_EDGE)
    holder.BorderThickness = Thickness(1)
    holder.CornerRadius = CornerRadius(3)
    holder.Padding = Thickness(6)
    holder.Margin = Thickness(0, 8, 0, 0)
    sv = ScrollViewer()
    sv.MaxHeight = 320
    sv.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
    stack = StackPanel()
    for value, count in values:
        chk = _dark_check('', True)
        label = '(blank)' if value == '' else value
        chk.Content = u'{0}   \u00b7 {1}'.format(label, count)
        chk.IsChecked = (current is None) or (value in current)
        chk.Margin = Thickness(0, 1, 0, 1)
        chk.Tag = value
        stack.Children.Add(chk)
        boxes.append((value, chk, to_text(label).lower()))
    sv.Content = stack
    holder.Child = sv

    tally = _tb('', C_MUTED, 11)
    tally.VerticalAlignment = VerticalAlignment.Center
    tally.Margin = Thickness(12, 0, 0, 0)

    def count_ticked():
        ticked = 0
        for _value, chk, _label in boxes:
            try:
                if chk.IsChecked:
                    ticked += 1
            except Exception:
                continue
        try:
            tally.Text = u'{0} of {1} ticked'.format(ticked, len(boxes))
        except Exception:
            pass
        return ticked

    bar = StackPanel()
    bar.Orientation = Orientation.Horizontal
    bar.Margin = Thickness(0, 8, 0, 0)
    btn_all = _styled_button('Select all', 'ghost')
    btn_none = _styled_button('Untick all', 'ghost')
    btn_none.Margin = Thickness(8, 0, 0, 0)
    bar.Children.Add(btn_all)
    bar.Children.Add(btn_none)
    bar.Children.Add(tally)
    dlg.add(bar)
    dlg.add(holder)

    for _value, chk, _label in boxes:
        try:
            chk.Checked += (lambda sender, args: count_ticked())
            chk.Unchecked += (lambda sender, args: count_ticked())
        except Exception:
            continue

    def on_search(sender, args):
        term = to_text(search.Text).strip().lower()
        for _value, chk, label in boxes:
            try:
                chk.Visibility = (Visibility.Visible
                                  if (not term or term in label)
                                  else Visibility.Collapsed)
            except Exception:
                pass
    search.TextChanged += on_search

    def set_visible(state):
        """Only what the search box is showing, so a search narrows what the
        two buttons act on rather than them always taking the whole list."""
        for _value, chk, _label in boxes:
            try:
                if chk.Visibility == Visibility.Visible:
                    chk.IsChecked = state
            except Exception:
                pass
        count_ticked()

    btn_all.Click += (lambda sender, args: set_visible(True))
    btn_none.Click += (lambda sender, args: set_visible(False))
    count_ticked()

    def do_clear():
        host.col_picks.pop(fi.index, None)
        host.apply_filters()
        host.set_status('Filter cleared on {0}.'.format(fi.name))

    def do_apply():
        picked = set()
        for value, chk, _label in boxes:
            if chk.IsChecked:
                picked.add(value)
        if len(picked) == len(boxes):
            host.col_picks.pop(fi.index, None)   # everything ticked is no filter
        else:
            host.col_picks[fi.index] = picked
        host.apply_filters()

    dlg.add_button('Clear', 'orange', 'close', close=True, handler=do_clear)
    dlg.add_button('Apply', 'green', 'close', close=True, handler=do_apply)
    dlg.show()


# ------------------------------------------------------- drag auto-scroll ----
#
# Excel scrolls while you hold a drag past the edge of the grid, and the
# further past you go the faster it runs.  A fixed one-row-per-tick — what this
# tool did before — is unusable on a long schedule and twitchy on a short one.
#
# The curve: nothing inside a small dead zone, a gentle rate the moment you
# cross it, then accelerating to a fast rate over a couple of hundred pixels.
# Rates are rows per second, so they are independent of the timer interval,
# and the leftover fraction is carried between ticks — otherwise a rate below
# one row per tick would round to zero and never scroll at all.

EDGE_INSET = 8.0             # start scrolling just inside the edge, like Excel

AUTOFIT_MIN = 124.0          # a header carries a filter box, a caret and an outline
AUTOFIT_MAX = 380.0          # one long comments field must not push the rest off
AUTOFIT_PAD = 8.0            # breathing room either side of the measured text

SNAP_BREAK_PX = 6.0          # slack before a drag undoes a vertical snap

SCROLL_TICK_MS = 33          # ~30 a second, smooth without being busy
SCROLL_DEAD_PX = 4.0         # slack so a drag along the edge does not creep
SCROLL_MIN_RATE = 7.0        # rows a second just past the edge
SCROLL_MAX_RATE = 95.0       # rows a second when dragged well past it
SCROLL_RAMP_PX = 200.0       # distance over which it reaches full speed
SCROLL_CURVE = 1.45          # >1 keeps the slow end fine and the fast end fast


# Each level of a sort gets its own colour, resolved at paint time so it
# follows the theme. Orange is the primary because that is the accent the rest
# of the tool uses for "this is the one that matters".
SORT_LEVEL_COLOURS = ('C_ORANGE', 'C_BLUE', 'C_GREEN', 'C_TEST_FG',
                      'C_IMP_FG', 'C_COPY_FG')
SORT_LEVEL_MAX = 6


def sort_level_colour(level):
    name = SORT_LEVEL_COLOURS[level % len(SORT_LEVEL_COLOURS)]
    return globals().get(name, '#E8912D')


def scroll_rate(overshoot):
    """Rows per second for a pointer this many pixels past the grid edge."""
    try:
        distance = abs(float(overshoot))
    except Exception:
        return 0.0
    if distance <= SCROLL_DEAD_PX:
        return 0.0
    t = (distance - SCROLL_DEAD_PX) / SCROLL_RAMP_PX
    if t > 1.0:
        t = 1.0
    return SCROLL_MIN_RATE + (SCROLL_MAX_RATE - SCROLL_MIN_RATE) * (t ** SCROLL_CURVE)


def set_level_dialog(host):
    """Pick a level for the selected elements, staged like any other edit."""
    rows = host.selected_rows()
    if not rows:
        themed_message('Set Level',
                       u'Select cells on the rows you want to re-level first.\n\n'
                       'One cell anywhere on a row is enough — the whole '
                       'element is what moves.', owner=host.window)
        return

    levels = project_levels(host.doc)
    if not levels:
        themed_message('Set Level', 'This project has no levels.',
                       accent=C_RED, owner=host.window)
        return

    dlg = ThemedDialog('Set Level', width=560, owner=host.window, accent=C_ORANGE)
    dlg.add(_tb('{0} element{1} selected. Pick the level they should belong '
                'to.'.format(len(rows), '' if len(rows) == 1 else 's'),
                C_TEXT, 13, True, True))
    note = _tb('Nothing moves. The position is measured before and after, and '
               'any shift the level change causes is undone, so the elements '
               'stay exactly where they are in the model and only their level '
               'changes.', C_MUTED, 11.5, False, True)
    note.Margin = Thickness(0, 8, 0, 0)
    dlg.add(note)

    holder = Border()
    holder.Background = brush(C_FIELD)
    holder.BorderBrush = brush(C_EDGE)
    holder.BorderThickness = Thickness(1)
    holder.CornerRadius = CornerRadius(3)
    holder.Padding = Thickness(6)
    holder.Margin = Thickness(0, 12, 0, 0)
    sv = ScrollViewer()
    sv.MaxHeight = 300
    sv.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
    stack = StackPanel()

    state = {'level': None}
    cards = {}

    def choose(level):
        state['level'] = level
        key = eid_value(level.Id)
        for other, card in cards.items():
            on = (other == key)
            card.Background = brush(C_EDIT_BG if on else C_CARD)
            card.BorderBrush = brush(C_GREEN if on else C_EDGE)

    for level in levels:
        card = Border()
        card.Background = brush(C_CARD)
        card.BorderBrush = brush(C_EDGE)
        card.BorderThickness = Thickness(1)
        card.CornerRadius = CornerRadius(3)
        card.Padding = Thickness(9, 6, 9, 6)
        card.Margin = Thickness(0, 0, 0, 4)
        card.Cursor = Cursors.Hand
        inner = WGrid()
        inner.ColumnDefinitions.Add(ColumnDefinition())
        right = ColumnDefinition()
        right.Width = GridLength(110)
        inner.ColumnDefinitions.Add(right)
        name = _tb(elem_name(level) or 'Level', C_TEXT, 12.5, True)
        WGrid.SetColumn(name, 0)
        inner.Children.Add(name)
        try:
            mm = level.Elevation * 304.8
        except Exception:
            mm = 0.0
        elev = _tb('{0} mm'.format(to_text(int(round(mm)))), C_MUTED, 11.5)
        elev.HorizontalAlignment = HorizontalAlignment.Right
        WGrid.SetColumn(elev, 1)
        inner.Children.Add(elev)
        card.Child = inner

        def _click(sender, args, lv=level):
            choose(lv)
        try:
            card.MouseLeftButtonUp += _click
        except Exception:
            pass
        cards[eid_value(level.Id)] = card
        stack.Children.Add(card)

    sv.Content = stack
    holder.Child = sv
    dlg.add(holder)

    # start on the level the selection already shares, where they share one
    try:
        current = set([host.level_of_row(r) for r in rows])
        if len(current) == 1:
            only = list(current)[0]
            for level in levels:
                if only is not None and eid_value(level.Id) == only:
                    choose(level)
                    break
    except Exception:
        pass

    def do_ok():
        level = state['level']
        if level is None:
            return
        n = host.stage_levels(rows, level)
        host.set_status(u'{0} element{1} set to {2} — nothing is written until '
                        'APPLY.'.format(n, '' if n == 1 else 's',
                                        elem_name(level)))

    dlg.add_button('Cancel', 'ghost', None)
    dlg.add_button('OK', 'green', 'ok', close=True, handler=do_ok)
    dlg.show()


def cell_of(content):
    """DataGridCell that owns a generated cell element."""
    if content is None:
        return None
    try:
        parent = content.Parent
        if isinstance(parent, DataGridCell):
            return parent
    except Exception:
        pass
    return walk_up(content, DataGridCell)


def walk_up(element, wanted):
    node = element
    guard = 0
    while node is not None and guard < 60:
        if isinstance(node, wanted):
            return node
        try:
            node = VisualTreeHelper.GetParent(node)
        except Exception:
            return None
        guard += 1
    return None


class ExcelForRevitWindow(object):

    def __init__(self, uidoc, doc, model):
        # first, because set_status is reachable from almost everything below
        # and it asks whether the engine has proved itself yet
        self._proved = False
        self._shown = False          # show() has returned: proof can count now
        self.last_refusal = u''      # why stage() last turned a value away
        self.refused = 0             # values stage() turned away this batch
        self.ws_dropdown = None      # the open workset list, if any
        self._ws_hints = 0           # times the Workset hint has been shown
        self.uidoc = uidoc
        self.doc = doc
        self.model = model
        self.col_field = {}
        self.undo_stack = []
        self.redo_stack = []
        self._batch = None
        self.editing = False
        self._closing_ok = False
        self._dirty_paint = True
        self._filling = False
        self._fill_src = None
        self._fill_target = -1
        self._fill_col = None
        self._scroll_timer = None
        self._scroll_over = 0.0
        self._scroll_over_x = 0.0
        self._scroll_accum = 0.0
        self._scroll_accum_x = 0.0
        self._drag_mode = None
        self._sel_anchor = None
        self._sel_pos = -1
        self._sel_col = None
        self._sel_cur_col = None
        self._sel_rect = None        # the rectangle extend_selection last drew
        self._sel_pending = False    # a selection refresh is already queued
        self._last_sel = _STALE      # bottom-right selected cell, once worked out
        self._pos_cache = None       # (row count, {model row: grid position})
        self.live_rows = set()       # row containers the grid has realised
        self._dirty_rows = set()     # realised rows still showing old colours
        self._paint_tries = {}       # container -> attempts before its cells existed
        self._header_tall = set()    # containers last given a heading's height
        self._down_at = None
        self.copy_marks = set()      # (ridx, field_index) shown as copy source
        self.grouping = False
        self.group_of = {}           # ridx -> group number
        self.group_labels = {}       # group number -> (label, row count)
        self.group_row = {}          # group number -> its row index in the table
        self.collapsed = set()       # group numbers currently shut
        self.btn_expand = None
        self.btn_excel = None
        self.btn_isolate = None
        self.btn_theme = None
        self.group_bar = None
        self.tool_strip = None
        self.tool_grid = None
        self.sort_col = None
        self.sort_field = None
        self.sort_desc = False
        self.sort_snapshot = {}      # ridx -> the values the order was built on
        self.sort_stack = []         # [(field, descending)], primary first
        self.sort_snapshot = {}      # ridx -> the values the order was built on
        self.sort_stack = []         # [(field, descending)], primary first
        self.btn_group = None
        self._first_render_done = False
        self.active_clause = ''      # the filter behind the current snapshot
        self.col_filters = {}        # field index -> keyword
        self.col_picks = {}          # field index -> set of allowed values
        self.dup_isolated = set()    # columns currently isolated to duplicates
        self.dup_saved_picks = {}    # the tick filter each one had before
        self._menu_col = None        # the column the grid menu was opened on
        self.header_boxes = {}
        self.header_carets = {}
        self.header_titles = {}
        self.header_badges = {}
        self.header_outlines = {}
        self._filter_timer = None
        self.finder = None
        self.last_formula = ''
        self.formula_bar = None
        self.formula_box = None
        self.formula_ink = None
        self.formula_hint = None
        self.formula_cells = []
        self.formula_pick = True
        self.btn_pick = None
        self.seq_settings = {}
        self.affix_settings = {}
        self.hl_settings = {}
        self.cell_hl = {}
        self.row_hl = {}
        self.col_hl = {}
        self.scratch = 0
        self.plus_col = None
        self.imported = set()    # (ridx, field_index) staged by an Excel import
        self._importing = False
        self._grips = {}
        self.applying = False
        self.handler = None
        self.event = None
        # Modeless keeps Revit usable, but it depends on pyRevit honouring
        # __persistentengine__: where it does not, the engine is torn down when
        # the command returns and every handler in the window dies with it —
        # the window is still there and nothing works. So it is opt in, and the
        # tool defaults to the modal behaviour that cannot fail that way.
        self.modeless = bool(load_settings().get('modeless', True))
        if self.modeless:
            try:
                self.handler = WorkHandler()
                self.event = UI.ExternalEvent.Create(self.handler)
            except Exception:
                self.handler = None
                self.event = None
                self.modeless = False
        self.restore_rect = None
        self.vstretch = None
        self._snap_break = 0.0
        self.legend_host = None
        self.max_btn = None
        self.drawer = None

        self.window = load_xaml(XAML_PATH)
        w = self.window

        def f(name):
            return w.FindName(name)

        self.dg = f('DataGridMain')
        self.grid_host = f('GridHost')
        self.handle = f('FillHandle')
        self.preview = f('FillPreview')
        self.status = f('StatusText')
        self.pending = f('PendingText')
        self.btn_revert_sel = f('BtnRevertSelected')
        self.btn_apply = f('BtnApply')

        f('VersionText').Text = 'v' + __version__
        f('ScheduleTitle').Text = elem_name(model.sched)
        f('ScheduleSub').Text = '  '.join(model.notes)

        try:
            f('IconImage').Source = load_image(ICON_PATH)
        except Exception:
            pass
        # toolbar: (button name, icon, label, tooltip, handler)
        self.tool_defs = (
            ('BtnFillDown', 'filldown', 'Fill Down', 'Fill the top cell of the selection down (Ctrl+D)', self.on_fill_down),
            ('BtnFormula', 'formula', 'Formula', 'Build values from other columns, e.g. =CONCAT(A," - ",B)  (Ctrl+Shift+F)', self.on_formula),
            ('BtnSequence', 'sequence', 'Sequence', 'Number the selection, keeping the padding of the start number (Ctrl+Shift+N)', self.on_sequence),
            ('BtnAffix', 'affix', 'Prefix', 'Wrap text around what the selected cells already hold (Ctrl+Shift+P)', self.on_affix),
            ('BtnFindView', 'findview', 'Find in View', 'Select the elements on the picked rows in Revit and show them in a view', self.on_find_in_view),
            ('BtnSetLevel', 'setlevel', 'Set Level', 'Put the selected elements on another level without moving them', self.on_set_level),
            ('BtnHighlight', 'highlight', 'Highlight', u'Colour cells, rows or columns — the colour follows the data through filters (Ctrl+Shift+H)', self.on_highlight),
            ('BtnFind', 'find', 'Find and Replace', 'Find and replace across the schedule (Ctrl+H)', self.on_find),
            ('BtnRevertAll', 'revert', 'Revert All', 'Drop every staged edit', self.on_revert_all),
            ('BtnGroup', 'group', 'Group', 'Break the table with a coloured heading each time the sorted column changes value', self.on_group_toggle),
            ('BtnExpand', 'expand', 'Collapse All', 'Open or close every group at once', self.on_expand_all),
            ('BtnReload', 'reload', 'Reload', 'Re-read the schedule from the model', self.on_reload),
        )
        self.tool_buttons = {}
        for name, icon, label, tip, handler in self.tool_defs:
            try:
                btn = f(name)
                build_tool_button(btn, icon, label, tip)
                btn.Click += handler
                self.tool_buttons[name] = btn
            except Exception:
                pass

        for name, handler in (('CloseBtn', self.on_close_click),
                              ('BtnClose', self.on_close_click),
                              ('MaxBtn', self.on_maximise),
                              ('BtnTheme', self.on_theme),
                              ('BtnApply', self.on_apply),
                              ('BtnExcel', self.on_excel),
                              ('BtnRevertSelected', self.on_revert_selected),
                              ):
            try:
                f(name).Click += handler
            except Exception:
                pass

        self.wire_formula_bar(f)
        self.wire_grips(f)
        self.btn_theme = f('BtnTheme')
        self.btn_isolate = f('BtnIsolate')
        try:
            build_wide_button(self.btn_isolate, 'isolate', 'Isolate Selected',
                              'Open the default 3D view and temporarily isolate '
                              'the selected elements, keeping the section box')
            self.btn_isolate.Click += self.on_isolate_selected
        except Exception:
            pass
        self.btn_excel = f('BtnExcel')
        try:
            build_wide_button(self.btn_excel, 'excel', 'Excel',
                              'Export to Excel, or import an edited workbook back')
        except Exception:
            pass
        self.group_bar = f('GroupBar')
        self.tool_strip = f('ToolStrip')
        self.tool_grid = f('ToolGrid')
        self.btn_group = self.tool_buttons.get('BtnGroup')
        self.show_theme_state()
        self.btn_expand = self.tool_buttons.get('BtnExpand')
        self.legend_host = f('LegendHost')
        self.build_legend()
        try:
            f('HeaderBar').MouseLeftButtonDown += self.on_header_click
        except Exception:
            pass
        self.max_btn = f('MaxBtn')
        self.build_drawer(f)

        self.build_grid()

        try:
            if load_settings().get('theme') == 'light':
                self.set_theme_to('light')
        except Exception:
            pass

        try:
            self.dg.BeginningEdit += self.on_begin_edit
            self.dg.CellEditEnding += self.on_cell_edit_ending
            self.dg.SelectedCellsChanged += self.on_selection_changed
            self.dg.LoadingRow += self.on_loading_row
            self.dg.UnloadingRow += self.on_unloading_row
            self.dg.LayoutUpdated += self.on_layout_updated
        except Exception:
            pass
        # each in its own try: these only keep the fill handle exact after a
        # column moves, and neither may take the paint hook above down with it
        try:
            self.dg.ColumnReordered += self.on_columns_changed
        except Exception:
            pass
        try:
            self.dg.Columns.CollectionChanged += self.on_columns_changed
        except Exception:
            pass
        if ScrollChangedEventHandler is not None:
            try:
                self.dg.AddHandler(ScrollViewer.ScrollChangedEvent,
                                   ScrollChangedEventHandler(self.on_scroll))
            except Exception:
                pass
        try:
            self.handle.MouseLeftButtonDown += self.on_handle_down
            self.handle.MouseMove += self.on_handle_move
            self.handle.MouseLeftButtonUp += self.on_handle_up
        except Exception:
            pass

        self.build_context_menu()
        try:
            self.dg.ContextMenuOpening += self.on_grid_menu_opening
        except Exception:
            pass
        try:
            self.dg.Sorting += self.on_sorting
            self.dg.CurrentCellChanged += self.on_current_cell_changed
            self.dg.PreviewMouseRightButtonDown += self.on_right_click
            self.dg.PreviewMouseRightButtonUp += self.on_header_right_up
            self.dg.PreviewMouseLeftButtonDown += self.on_grid_mouse_down
            self.dg.MouseMove += self.on_grid_mouse_move
            self.dg.PreviewMouseLeftButtonUp += self.on_grid_mouse_up
            self.dg.LostMouseCapture += self.on_grid_mouse_up
        except Exception:
            pass

        self.attach_egg(f)

        w.SizeChanged += self.on_size_changed
        w.ContentRendered += self.on_first_render
        w.PreviewKeyDown += self.on_key
        w.PreviewMouseMove += self.on_any_mouse
        w.Closing += self.on_closing
        self.update_pending()
        self.set_status('{0} rows loaded. Edit cells, then press APPLY.'.format(len(model.rows)))

    # -- construction -------------------------------------------------------

    # -- duplicates ---------------------------------------------------------

    def column_counts(self, fi):
        """Every value in a column and how many rows carry it."""
        counts = {}
        for row in self.model.rows:
            value = self.model.current_text(row, fi.index)
            counts[value] = counts.get(value, 0) + 1
        return counts

    def duplicate_values(self, fi):
        """Values that appear on more than one row.

        Blanks are left out: an empty cell repeated forty times is not the kind
        of duplicate anyone is hunting for, and including them would drown the
        real ones.
        """
        return find_duplicates([self.model.current_text(row, fi.index)
                                for row in self.model.rows])

    def highlight_duplicates(self, fi):
        """A colour per duplicate set, so which rows clash with which is
        readable without comparing values by eye."""
        dups = self.duplicate_values(fi)
        # drop any previous marking on this column before re-marking it
        for key in list(self.cell_hl.keys()):
            if key[1] == fi.index:
                self.cell_hl.pop(key, None)
        if not dups:
            self.repaint_soon()
            self.set_status('No duplicates in {0}.'.format(fi.name))
            return 0
        colour_of = {}
        for n, value in enumerate(dups):
            colour_of[value] = HIGHLIGHT_COLOURS[n % len(HIGHLIGHT_COLOURS)]
        rows = 0
        for row in self.model.rows:
            value = self.model.current_text(row, fi.index)
            if value in colour_of:
                self.cell_hl[(row.ridx, fi.index)] = (colour_of[value], 'both')
                rows += 1
        self.repaint_soon()
        note = ''
        if len(dups) > len(HIGHLIGHT_COLOURS):
            note = '  Colours repeat after {0} sets.'.format(
                len(HIGHLIGHT_COLOURS))
        self.set_status('{0} duplicate value{1} in {2}, across {3} rows.{4}'.format(
            len(dups), '' if len(dups) == 1 else 's', fi.name, rows, note))
        return len(dups)

    def isolate_duplicates(self, fi, on):
        """Show only the rows that clash, using the column's own tick filter.

        Only this column is touched — any other column's filter, and the sort
        and the grouping, are left exactly as they were.
        """
        if on:
            dups = self.duplicate_values(fi)
            if not dups:
                self.set_status('No duplicates in {0} to isolate.'.format(fi.name))
                return False
            if fi.index not in self.dup_isolated:
                # a tick filter the user had set here comes back afterwards
                self.dup_saved_picks[fi.index] = self.col_picks.get(fi.index)
            self.col_picks[fi.index] = set(dups)
            self.dup_isolated.add(fi.index)
        else:
            saved = self.dup_saved_picks.pop(fi.index, None)
            if saved is None:
                self.col_picks.pop(fi.index, None)
            else:
                self.col_picks[fi.index] = saved
            self.dup_isolated.discard(fi.index)
        self.apply_filters()
        shown = 0
        try:
            shown = self.dg.Items.Count
        except Exception:
            pass
        if on:
            self.set_status('Isolated {0} row{1} with duplicate {2} values.'.format(
                shown, '' if shown == 1 else 's', fi.name))
        else:
            self.set_status('Stopped isolating duplicates in {0}.'.format(fi.name))
        return on

    def next_unique(self, taken, seed):
        """The next value not already in use, counting on the rightmost number.

        `SD-01` with `SD-02` taken gives `SD-03`; the padding and everything
        either side of the number are kept. A value with no number at all gets
        one added rather than being left as a clash.
        """
        parts = split_number(seed)
        if parts is None:
            base = to_text(seed).rstrip()
            n = 2
            while True:
                candidate = '{0} {1}'.format(base, n) if base else to_text(n)
                if candidate not in taken:
                    return candidate
                n += 1
        step = 1
        for _ in range(100000):
            candidate = series_value(seed, step, 1)
            if candidate not in taken:
                return candidate
            step += 1
        return seed

    def on_unique_sequence(self, sender=None, args=None):
        """Give every selected cell a value nothing else in its column uses."""
        cells = [c for c in self.sel_cells()
                 if self.model.rows[c['ridx']].cells[c['fidx']].editable]
        if not cells:
            self.set_status('Select one or more editable cells first.')
            return
        by_field = {}
        for c in cells:
            by_field.setdefault(c['fidx'], []).append(c)

        self.begin_batch()
        changed = 0
        left = 0
        for fidx, group in by_field.items():
            fi = self.model.fields[fidx]
            taken = set(self.column_counts(fi).keys())
            counts = self.column_counts(fi)
            for cell in sorted(group, key=lambda d: d['pos']):
                current = self.text_at(cell['pos'], cell['col']) or ''
                if counts.get(current, 0) < 2:
                    left += 1
                    continue          # already unique: nothing to solve
                value = self.next_unique(taken, current)
                if self.stage_cell(cell['pos'], cell['col'], value):
                    taken.add(value)
                    counts[value] = 1
                    counts[current] = counts.get(current, 1) - 1
                    changed += 1
        self.end_batch()

        msg = 'Renumbered {0} cell{1} to unique values.'.format(
            changed, '' if changed == 1 else 's')
        if left:
            msg += '  {0} {1} already unique.'.format(
                left, 'was' if left == 1 else 'were')
        self.set_status(msg)

    # -- column filters -----------------------------------------------------

    def column_header(self, fi):
        """Heading, a keyword box and a tick-filter caret, built as elements.

        The header is set to a live UIElement rather than a string, so there is
        no DataTemplate and no question of whether WPF can see a Python
        attribute — the same reason the rows are built this way.
        """
        panel = StackPanel()
        panel.Orientation = Orientation.Vertical

        top = StackPanel()
        top.Orientation = Orientation.Horizontal
        top.Margin = Thickness(0, 0, 0, 4)

        # the formula reference, as a quiet badge rather than part of the name
        badge = Border()
        badge.Width = 17
        badge.Height = 17
        badge.CornerRadius = CornerRadius(9)
        badge.BorderBrush = brush(C_ORANGE)
        badge.BorderThickness = Thickness(1)
        badge.Background = brush(C_TYPE_BG)
        badge.Margin = Thickness(0, 0, 6, 0)
        badge.VerticalAlignment = VerticalAlignment.Center
        letter = _tb(fi.letter, C_ORANGE, 9.5, True)
        letter.HorizontalAlignment = HorizontalAlignment.Center
        letter.VerticalAlignment = VerticalAlignment.Center
        badge.Child = letter
        badge.ToolTip = u'Column {0} — the name to use in a formula'.format(fi.letter)
        top.Children.Add(badge)

        title = _tb(fi.name,
                    C_TYPE_FG if fi.is_type else
                    (C_RO_FG if not fi.supported else C_INST_FG), 12, True)
        title.TextTrimming = TextTrimming.CharacterEllipsis
        title.VerticalAlignment = VerticalAlignment.Center
        tip = 'Type parameter' if fi.is_type else 'Instance parameter'
        if not fi.supported:
            tip = fi.reason or 'Read only'
        title.ToolTip = u'{0} — column {1}'.format(tip, fi.letter)
        top.Children.Add(title)
        self.header_badges[fi.index] = (badge, letter)
        panel.Children.Add(top)

        row = WGrid()
        row.ColumnDefinitions.Add(ColumnDefinition())
        cd = ColumnDefinition()
        cd.Width = GridLength(20)
        row.ColumnDefinitions.Add(cd)

        box = TextBox()
        box.Height = 22
        box.MinHeight = 22
        box.Padding = Thickness(4, 1, 2, 1)
        box.FontWeight = FontWeights.Normal
        box.FontSize = 11
        box.Tag = 'Filter'
        box.ToolTip = 'Show only rows where {0} contains this'.format(fi.name)
        try:
            box.Text = self.col_filters.get(fi.index, '')
        except Exception:
            pass

        def _changed(sender, args):
            try:
                text = sender.Text or ''
            except Exception:
                text = ''
            if text.strip():
                self.col_filters[fi.index] = text
            else:
                self.col_filters.pop(fi.index, None)
            self.debounce_filter()

        box.TextChanged += _changed
        # clicking in the box must not sort the column underneath it
        box.PreviewMouseLeftButtonDown += self._stop_header_click
        WGrid.SetColumn(box, 0)
        row.Children.Add(box)

        caret = Button()
        caret.Content = u'\u25BE'
        caret.Width = 18
        caret.Height = 22
        caret.Padding = Thickness(0)
        caret.ToolTip = 'Pick which values to show'
        try:
            caret.Style = self.window.Resources['CaretBtn']
        except Exception:
            pass

        # The header underneath sorts on click, so the caret has to mark the
        # event handled. Doing that in PreviewMouseLeftButtonDown *and* relying
        # on Click cannot work: handling the preview stops the button ever
        # raising Click, which is why the caret did nothing at all. Open the
        # filter from the preview instead, and handle it there.
        # the last test column carries a remove button instead of a filter,
        # since a test column is disposable and only the last can go without
        # shifting the ones after it
        last_scratch = (getattr(fi, 'scratch', False) and
                        fi.index == len(self.model.fields) - 1)
        if last_scratch:
            caret.Content = u'\u2715'
            caret.ToolTip = 'Remove this test column'

            def _drop(sender, args):
                args.Handled = True
                if self.remove_scratch_column():
                    self.set_status('Removed the test column.')
            caret.PreviewMouseLeftButtonDown += _drop
        else:
            def _caret_down(sender, args, field=fi):
                args.Handled = True
                self.open_tick_filter(field)
            caret.PreviewMouseLeftButtonDown += _caret_down
        WGrid.SetColumn(caret, 1)
        row.Children.Add(caret)

        panel.Children.Add(row)
        self.header_boxes[fi.index] = box
        self.header_carets[fi.index] = caret
        self.header_titles[fi.index] = title

        # the outline lives on a Border of our own rather than on the header's
        # template, which hardcodes its brush. The thickness never changes —
        # only the colour — so lighting it cannot nudge the layout.
        outline = Border()
        outline.BorderBrush = brush(C_CLEAR)
        outline.BorderThickness = Thickness(2)
        outline.CornerRadius = CornerRadius(3)
        outline.Padding = Thickness(3, 1, 3, 1)
        outline.Child = panel
        outline.Background = brush(C_CLEAR)   # hit-testable across its width
        self.header_outlines[fi.index] = outline
        return outline

    def duplicate_items(self, menu, field_of):
        """Add the duplicate commands to a menu.

        `field_of` answers "which column?" when the menu opens, so the same
        items serve the heading menu (always its own column) and the cell menu
        (whichever column was right-clicked). The isolate item is an ordinary
        item whose label flips between isolating and un-isolating, rather than a
        checkable one whose state cannot be trusted inside its own Click.
        """
        highlight = MenuItem()
        highlight.FontWeight = FontWeights.Bold
        isolate = MenuItem()
        clear = MenuItem()

        def _opening(sender, args):
            fi = field_of()
            ok = fi is not None
            for item in (highlight, isolate, clear):
                item.Visibility = Visibility.Visible if ok else Visibility.Collapsed
            if not ok:
                return
            dups = self.duplicate_values(fi)
            highlight.Header = u'Highlight duplicates in {0}'.format(fi.name)
            highlight.IsEnabled = bool(dups)
            if not dups:
                highlight.Header = u'No duplicates in {0}'.format(fi.name)
            if fi.index in self.dup_isolated:
                isolate.Header = u'Un-isolate duplicates in {0}'.format(fi.name)
                isolate.IsEnabled = True
            else:
                isolate.Header = u'Isolate duplicates in {0}{1}'.format(
                    fi.name, u' ({0} set{1})'.format(
                        len(dups), '' if len(dups) == 1 else 's') if dups else '')
                isolate.IsEnabled = bool(dups)
            clear.Header = u'Clear highlighting in {0}'.format(fi.name)
            clear.IsEnabled = any(k[1] == fi.index for k in self.cell_hl)

        def _highlight(sender, args):
            fi = field_of()
            if fi is not None:
                self.highlight_duplicates(fi)

        def _isolate(sender, args):
            fi = field_of()
            if fi is not None:
                self.isolate_duplicates(fi, fi.index not in self.dup_isolated)

        def _clear(sender, args):
            fi = field_of()
            if fi is not None:
                self.clear_column_highlight(fi)

        highlight.Click += _highlight
        isolate.Click += _isolate
        clear.Click += _clear
        menu.Opened += _opening
        menu.Items.Add(highlight)
        menu.Items.Add(isolate)
        menu.Items.Add(clear)

    def header_menu(self, fi):
        """The right-click menu on a column heading."""
        menu = ContextMenu()
        self.duplicate_items(menu, lambda: fi)
        menu.Items.Add(Separator())
        for label, handler in (
                ('Clear this column filter',
                 lambda sender, args: self.clear_column_filter(fi)),
                ('Pick values to show...',
                 lambda sender, args: self.open_tick_filter(fi))):
            item = MenuItem()
            item.Header = label
            item.Click += handler
            menu.Items.Add(item)
        return menu

    def header_under_pointer(self):
        """(heading, field) under the mouse, or (None, None).

        The filter box inside a heading does not count: it keeps its own
        cut / copy / paste menu.
        """
        try:
            hit = self.dg.InputHitTest(Mouse.GetPosition(self.dg))
        except Exception:
            return None, None
        header = walk_up(hit, DataGridColumnHeader)
        if header is None:
            return None, None
        if walk_up(hit, TextBox) is not None:
            return None, None
        return header, self.col_field.get(header.Column)

    def open_header_menu(self, header, fi):
        try:
            menu = self.header_menu(fi)
            menu.PlacementTarget = header
            menu.Placement = PlacementMode.MousePoint
            menu.IsOpen = True
            return True
        except Exception:
            return False

    def on_header_right_up(self, sender, args):
        """Right-click anywhere on a heading opens that column's menu.

        Handled on the button *coming up*, which is when Windows opens a
        context menu, and marked handled, so nothing else gets the chance to
        open the cell menu in its place. This does not depend on the grid
        deciding to raise ContextMenuOpening for a heading, or on which part of
        the heading happens to be hit-testable.
        """
        header, fi = self.header_under_pointer()
        if header is None:
            return
        args.Handled = True
        if fi is None:
            return                # the # and Id columns have no menu
        self._menu_col = fi
        self.open_header_menu(header, fi)

    def on_grid_menu_opening(self, sender, args):
        """The keyboard route to the same menu (the menu key, Shift+F10), and a
        second line of defence if the mouse route were ever bypassed."""
        header, fi = self.header_under_pointer()
        if header is None:
            return
        args.Handled = True
        if fi is not None:
            self._menu_col = fi
            self.open_header_menu(header, fi)

    def clear_column_highlight(self, fi):
        n = 0
        for key in list(self.cell_hl.keys()):
            if key[1] == fi.index:
                self.cell_hl.pop(key, None)
                n += 1
        self.repaint_soon()
        self.set_status('Cleared {0} highlighted cell{1} in {2}.'.format(
            n, '' if n == 1 else 's', fi.name))

    def clear_column_filter(self, fi):
        self.col_picks.pop(fi.index, None)
        self.col_filters.pop(fi.index, None)
        box = self.header_boxes.get(fi.index)
        try:
            if box is not None:
                box.Text = ''
        except Exception:
            pass
        self.apply_filters()
        self.set_status('Cleared the filter on {0}.'.format(fi.name))

    def mark_sorted_column(self):
        """Outline the column the table is sorted by, and show the direction.

        The header template draws no sort arrow of its own, so without this a
        sorted table gives no clue which column it is sorted on or which way.
        """
        for index, outline in self.header_outlines.items():
            try:
                colour = self.sort_colour(index)
                outline.BorderBrush = brush(colour or C_CLEAR)
            except Exception:
                pass
        for index, title in self.header_titles.items():
            try:
                fi = self.model.fields[index]
                title.Text = fi.name + self.sort_arrow(index)
                title.Foreground = brush(self.sort_colour(index) or (
                    C_TYPE_FG if fi.is_type else
                    (C_RO_FG if not fi.supported else C_INST_FG)))
            except Exception:
                pass
        for index, pair in self.header_badges.items():
            try:
                badge, letter = pair
                badge.BorderBrush = brush(C_ORANGE)
                badge.Background = brush(C_TYPE_BG)
                letter.Foreground = brush(C_ORANGE)
            except Exception:
                pass

    def sort_level_of(self, index):
        """Where this column sits in the sort: 0 primary, 1 secondary, else None."""
        for n, entry in enumerate(self.sort_stack):
            try:
                if entry[0].index == index:
                    return n
            except Exception:
                continue
        return None

    def sort_colour(self, index):
        level = self.sort_level_of(index)
        if level is None:
            return None
        return sort_level_colour(level)

    def sort_arrow(self, index):
        level = self.sort_level_of(index)
        if level is None:
            return ''
        desc = self.sort_stack[level][1]
        arrow = u'\u25BC' if desc else u'\u25B2'
        if len(self.sort_stack) > 1:
            return u'   {0}{1}'.format(level + 1, arrow)
        return u'   ' + arrow

    def _stop_header_click(self, sender, args):
        """Give the box the keyboard without letting the header sort.

        Only the first click is swallowed. Handling every one would take the
        mouse away from the text box as well as from the header, leaving no way
        to place the caret or select inside the filter text.
        """
        try:
            if sender.IsKeyboardFocusWithin:
                return
            sender.Focus()
            args.Handled = True
        except Exception:
            pass

    def debounce_filter(self):
        """Coalesce keystrokes — refiltering on every one is visibly slow."""
        if self._filter_timer is None:
            self._filter_timer = DispatcherTimer()
            self._filter_timer.Interval = TimeSpan.FromMilliseconds(220)

            def _tick(sender, args):
                self._filter_timer.Stop()
                self.apply_filters()
            self._filter_timer.Tick += _tick
        self._filter_timer.Stop()
        self._filter_timer.Start()

    def open_tick_filter(self, fi):
        try:
            tick_filter_dialog(self, fi)
        except Exception:
            themed_message(u'Filter — {0}'.format(fi.name),
                           'That filter could not be opened:\n\n'
                           + traceback.format_exc(),
                           accent=C_RED, width=680, owner=self.window)

    def column_values(self, fi):
        """The values worth offering in this column's filter list.

        Only the rows the **other** columns' filters allow, so filtering by
        Level and then opening the System list offers the systems on that level
        rather than every system in the schedule. This column's own filter is
        left out of that, or a filter could only ever be narrowed and never
        widened again.
        """
        clause = self.filter_clause(exclude=fi.index)
        allowed = self.rows_matching(clause) if clause else None
        seen = {}
        for row in self.model.rows:
            if allowed is not None and to_text(row.ridx) not in allowed:
                continue
            value = self.model.current_text(row, fi.index)
            seen[value] = seen.get(value, 0) + 1
        return sorted(seen.items(), key=lambda kv: natural_key(kv[0]))

    def column_values_limited(self, fi):
        """True when the other filters are hiding values this column has."""
        try:
            shown = len(self.column_values(fi))
            total = len(set([self.model.current_text(row, fi.index)
                             for row in self.model.rows]))
            return total - shown
        except Exception:
            return 0

    def apply_filters(self):
        """One RowFilter from the search box and every column filter.

        The filter is applied as a **snapshot**, the way Excel's autofilter
        behaves: whatever is on screen stays on screen until the filter is
        changed or re-applied. Without that, editing a cell in a filtered
        column makes its row stop matching and vanish the instant the value is
        committed — usually mid-fill, taking the cell being copied from with
        it.

        That falls out of filtering on a hidden `vis` flag rather than on the
        values themselves: editing a value column cannot change `vis`, so the
        row cannot move. Re-evaluating only happens here, when a filter
        actually changes or Reapply is pressed.
        """
        clause = self.filter_clause()
        self.active_clause = clause
        try:
            count = len(self.model.rows)
            if not clause:
                for i in range(count):
                    set_flag(self.table.Rows[i], 'vis', '1')
            else:
                matching = self.rows_matching(clause)
                for i in range(count):
                    row = self.table.Rows[i]
                    set_flag(row, 'vis',
                             '1' if to_text(row['ridx']) in matching else '0')
        except Exception:
            self.set_status('That filter could not be used.')
            return
        # a heading only belongs where its group still has rows
        if self.grouping:
            self.apply_sort()
        else:
            self.refresh_shown()
        self.mark_filtered_columns()
        self.report_rows()
        self.place_handle()
        self.repaint_soon()

    def filter_clause(self, exclude=None):
        """The real filter, before the snapshot is taken.

        `exclude` leaves one column's own filter out, which is what a filter
        dropdown needs: it should offer the values available under everything
        *else*, including the ones its own filter is currently hiding, or there
        would be no way to widen it again.
        """
        clauses = []
        for index, text in self.col_filters.items():
            if index == exclude:
                continue
            try:
                fi = self.model.fields[index]
            except Exception:
                continue
            if not to_text(text).strip():
                continue
            clauses.append("[{0}] LIKE '%{1}%'".format(
                fi.col, sql_like_escape(to_text(text).strip())))

        for index, allowed in self.col_picks.items():
            if index == exclude:
                continue
            try:
                fi = self.model.fields[index]
            except Exception:
                continue
            if allowed is None:
                continue
            if not allowed:
                clauses.append('1 = 0')          # nothing ticked shows nothing
                continue
            parts = []
            for value in allowed:
                if value == '':
                    parts.append("[{0}] = ''".format(fi.col))
                else:
                    parts.append("[{0}] = '{1}'".format(
                        fi.col, to_text(value).replace("'", "''")))
            clauses.append('(' + ' OR '.join(parts) + ')')
        return ' AND '.join(clauses)

    def rows_matching(self, clause):
        """Row indexes the clause selects, worked out on a throwaway view.

        A second DataView leaves the grid's own view — and its sort, and the
        selection — untouched while the question is asked.
        """
        out = set()
        try:
            probe = DataView(self.table)
            probe.RowFilter = ("({0}) AND [ridx] <> ''".format(clause)
                               if clause else "[ridx] <> ''")
            for i in range(probe.Count):
                out.add(to_text(probe[i]['ridx']))
        except Exception:
            pass
        return out

    def stale_rows(self):
        """Rows on screen that the filter would now drop, kept for editing."""
        if not self.active_clause:
            return 0
        matching = self.rows_matching(self.active_clause)
        n = 0
        try:
            view = self.table.DefaultView
            for i in range(view.Count):
                rid = to_text(view[i]['ridx'])
                if rid and rid not in matching:
                    n += 1
        except Exception:
            return 0
        return n

    def report_rows(self):
        shown = self.dg.Items.Count
        total = len(self.model.rows)
        if shown == total and not self.active_clause:
            self.set_status('{0} rows.'.format(total))
            return
        msg = '{0} of {1} rows shown by the filters.'.format(shown, total)
        stale = self.stale_rows()
        if stale:
            msg += (u'  {0} no longer match{1} but {2} being kept visible — '
                    'Reapply filters to drop {3}.'.format(
                        stale, 'es' if stale == 1 else '',
                        'is' if stale == 1 else 'are',
                        'it' if stale == 1 else 'them'))
        self.set_status(msg)

    def on_reapply_filters(self, sender=None, args=None):
        """Re-run the filter and let anything that no longer matches go."""
        if not self.active_clause and not self.grouping and not self.sort_stack:
            self.set_status('There is nothing to reapply.')
            return
        if not self.active_clause:
            self.apply_sort()
            self.set_status('Re-sorted{0}.'.format(
                ' and regrouped' if self.grouping else ''))
            return
        before = self.dg.Items.Count
        self.apply_filters()
        self.apply_sort()
        gone = before - self.dg.Items.Count
        if gone > 0:
            self.set_status(u'Reapplied — {0} row{1} dropped out of the filter.'.format(
                gone, '' if gone == 1 else 's'))
        else:
            self.set_status(u'Reapplied — every row still matches.')

    def mark_filtered_columns(self):
        """A filtered column's caret goes orange, so it is obvious why rows
        are missing — a filter you cannot see is a filter you forget."""
        for index, caret in self.header_carets.items():
            active = bool(to_text(self.col_filters.get(index, '')).strip()) or\
                self.col_picks.get(index) is not None
            try:
                caret.Content = u'\u25BC' if active else u'\u25BE'
                caret.Foreground = brush(C_ORANGE if active else C_MUTED)
            except Exception:
                pass

    def clear_all_filters(self):
        self.col_filters = {}
        self.col_picks = {}
        self.dup_isolated = set()
        for box in self.header_boxes.values():
            try:
                box.Text = ''
            except Exception:
                pass
        self.apply_filters()

    # -- group headers ------------------------------------------------------

    def is_header_row(self, item):
        """Header rows carry no ridx — that is what marks them."""
        try:
            return to_text(item['ridx']) == ''
        except Exception:
            return False

    def is_header_pos(self, pos):
        try:
            return self.is_header_row(self.dg.Items[pos])
        except Exception:
            return False

    def data_positions(self, start, downward, count):
        """`count` real row positions from `start`, stepping over any headers.

        Group headings are decoration. A paste or a fill that ran across one
        would otherwise drop a value into it and lose that value, so the walk
        skips them without consuming anything.
        """
        out = []
        try:
            total = self.dg.Items.Count
        except Exception:
            return out
        pos = start
        step = 1 if downward else -1
        while len(out) < count and 0 <= pos < total:
            if not self.is_header_pos(pos):
                out.append(pos)
            pos += step
        return out

    def group_colour(self, order):
        """A different colour per group, cycling once the palette runs out."""
        name = HIGHLIGHT_COLOURS[order % len(HIGHLIGHT_COLOURS)]
        return highlight_colours(name)

    def on_group_toggle(self, sender=None, args=None):
        self.grouping = not self.grouping
        self.show_group_state()
        if self.grouping and self.sort_field is None:
            # nothing sorted yet: group by the first column, which is what
            # "the sorted column" means when the user has not picked one
            try:
                self.sort_col = self.field_cols[0]
                self.sort_field = self.col_field.get(self.sort_col)
                self.sort_desc = False
                self.sort_stack = [(self.sort_field, False)]
                self.sort_col.SortDirection = ListSortDirection.Ascending
            except Exception:
                pass
        if not self.grouping:
            self.collapsed = set()
        self.apply_sort()
        self.show_expand_state()
        if self.grouping and self.sort_field is not None:
            self.set_status(u'Grouped by {0} — click a heading to open or close '
                            'it.'.format(self.sort_field.name))
        else:
            self.set_status('Grouping off.')

    def show_group_state(self):
        """Orange label when grouping is on, ordinary when off."""
        if self.btn_group is None:
            return
        try:
            icon_name, image, text = self.btn_group.Tag
            text.Text = 'Grouped' if self.grouping else 'Group'
            text.Foreground = brush(C_ORANGE if self.grouping else C_TEXT)
        except Exception:
            pass

    def on_sorting(self, sender, args):
        """Take the sort over, so grouping can order the headings with it."""
        try:
            col = args.Column
        except Exception:
            return
        if self.col_field.get(col) is None:
            return
        args.Handled = True
        field = self.col_field.get(col)
        shift = False
        try:
            shift = (Keyboard.Modifiers & ModifierKeys.Shift) == ModifierKeys.Shift
        except Exception:
            shift = False

        # clicking a column already in the sort flips its own direction;
        # anything else takes a place in it
        existing = None
        for entry in self.sort_stack:
            if entry[0] is field:
                existing = entry
                break

        if existing is not None:
            # a column already in the sort keeps its place and flips direction
            index = self.sort_stack.index(existing)
            self.sort_stack[index] = (field, not existing[1])
        elif shift and self.sort_stack:
            # shift keeps adding levels underneath, each a tie-break for the
            # ones above it
            if len(self.sort_stack) >= SORT_LEVEL_MAX:
                self.set_status('{0} sort levels is as deep as it goes.'.format(
                    SORT_LEVEL_MAX))
                return
            self.sort_stack = self.sort_stack + [(field, False)]
        else:
            self.sort_stack = [(field, False)]

        self.sort_col = col
        self.sort_field = self.sort_stack[0][0]
        self.sort_desc = self.sort_stack[0][1]
        for other in self.dg.Columns:
            try:
                other.SortDirection = None
            except Exception:
                pass
        for entry in self.sort_stack:
            for c, f in self.col_field.items():
                if f is entry[0]:
                    try:
                        c.SortDirection = (ListSortDirection.Descending if entry[1]
                                           else ListSortDirection.Ascending)
                    except Exception:
                        pass
        self.apply_sort()
        if len(self.sort_stack) > 1:
            names = ', then '.join([e[0].name for e in self.sort_stack])
            self.set_status('Sorted by {0}. Shift-click another heading to sort '
                            'inside that.'.format(names))
        elif self.sort_stack:
            self.set_status('Sorted by {0}. Shift-click another heading to sort '
                            'inside it.'.format(self.sort_stack[0][0].name))

    def apply_sort(self):
        """Rebuild the headings, work out what is showing, and sort."""
        view = self.table.DefaultView
        if self.grouping and self.sort_field is not None:
            self.rebuild_groups()
            self.refresh_shown()
            try:
                view.Sort = '[gkey] ASC'
            except Exception:
                pass
        else:
            self.clear_groups()
            self.refresh_shown()
            try:
                if self.sort_stack:
                    self.assign_sort_keys()
                    view.Sort = '[gkey] ASC'
                else:
                    self.sort_snapshot = {}
                    view.Sort = ''
            except Exception:
                pass
        self.mark_sorted_column()
        self.place_handle()
        self.repaint_soon()

    def assign_sort_keys(self):
        """Sort by a key worked out once, not by the live value.

        A DataView sorted on a value column re-evaluates the moment that value
        changes, so typing into the sorted column makes the row jump away from
        the cursor before it can be finished — the same trap as filtering on the
        values. Writing the order into a key column freezes it until the sort is
        asked for again, and it lets the order be **natural**, so P10 follows P9
        rather than P1.
        """
        if not self.sort_stack:
            return
        model = self.model
        ordered = [row.ridx for row in model.rows]
        snapshot = {}
        for row in model.rows:
            snapshot[row.ridx] = tuple(
                [model.current_text(row, e[0].index) for e in self.sort_stack])

        # least significant level first, then the most significant, because a
        # stable sort layers that way — which is also how each level keeps its
        # own direction, something one composite key cannot do
        for level in range(len(self.sort_stack) - 1, -1, -1):
            field, desc = self.sort_stack[level]
            ordered.sort(
                key=lambda ridx, f=field: natural_key(
                    model.current_text(model.rows[ridx], f.index)),
                reverse=desc)

        for n, ridx in enumerate(ordered):
            try:
                self.table.Rows[ridx]['gkey'] = '{0:08d}'.format(n)
            except Exception:
                pass
        self.sort_snapshot = snapshot

    def sort_stale(self):
        """Rows edited since the order was worked out, so still in their old
        place."""
        if not self.sort_snapshot or not self.sort_stack:
            return 0
        model = self.model
        n = 0
        for row in model.rows:
            was = self.sort_snapshot.get(row.ridx)
            if was is None:
                continue
            now = tuple([model.current_text(row, e[0].index)
                         for e in self.sort_stack])
            if now != was:
                n += 1
        return n

    def refresh_shown(self):
        """`show` = passes the filters **and** its group is not collapsed.

        Two separate reasons a row can be hidden, kept in two separate places:
        `vis` is the filter's answer and nothing else touches it, so collapsing
        a group cannot quietly drop rows out of the filter snapshot, and
        expanding it again brings back exactly what the filter allowed.
        """
        try:
            count = len(self.model.rows)
            for i in range(count):
                row = self.table.Rows[i]
                shown = to_text(row['vis']) == '1'
                if shown and self.collapsed:
                    group = self.group_of.get(i)
                    if group is not None and group in self.collapsed:
                        shown = False
                set_flag(row, 'show', '1' if shown else '0')
            for i in range(count, self.table.Rows.Count):
                set_flag(self.table.Rows[i], 'show', '1')   # headings always show
            self.table.DefaultView.RowFilter = "[show] = '1'"
        except Exception:
            pass

    # -- collapsing ---------------------------------------------------------

    def toggle_group(self, number):
        if number in self.collapsed:
            self.collapsed.discard(number)
        else:
            self.collapsed.add(number)
        self.write_header_text(number)
        self.refresh_shown()
        self.place_handle()
        self.repaint_soon()
        return number not in self.collapsed

    def set_all_groups(self, collapsed):
        if not self.grouping or not self.group_labels:
            self.set_status('Turn Group on first.')
            return
        if collapsed:
            self.collapsed = set(self.group_labels.keys())
        else:
            self.collapsed = set()
        for number in self.group_labels:
            self.write_header_text(number)
        self.refresh_shown()
        self.place_handle()
        self.repaint_soon()
        self.show_expand_state()
        self.set_status('{0} all {1} group{2}.'.format(
            'Collapsed' if collapsed else 'Expanded',
            len(self.group_labels), '' if len(self.group_labels) == 1 else 's'))

    def on_expand_all(self, sender=None, args=None):
        """One button for both, because there is only ever one sensible next
        move: if anything is open, close everything; otherwise open everything."""
        if not self.grouping:
            self.set_status(u'Grouping is off — there is nothing to collapse.')
            return
        any_open = len(self.collapsed) < len(self.group_labels)
        self.set_all_groups(any_open)

    def reflow_toolbar(self):
        """Keep the icons and Sort Headings on one row while they both fit.

        When they stop fitting the icons drop to a row of their own underneath,
        rather than being clipped or pushing Sort Headings off the edge. The
        two thresholds differ by a margin so a window dragged slowly across the
        boundary settles instead of flickering between the two layouts.
        """
        if self.tool_strip is None or self.group_bar is None:
            return
        try:
            total = float(self.tool_grid.ActualWidth)
            needed = float(self.tool_strip.DesiredSize.Width)
            aside = float(self.group_bar.ActualWidth) + 16.0
        except Exception:
            return
        if total <= 0 or needed <= 0:
            return
        stacked = (WGrid.GetRow(self.tool_strip) == 1)
        if not stacked and needed + aside > total:
            WGrid.SetRow(self.tool_strip, 1)
            WGrid.SetColumn(self.tool_strip, 0)
            WGrid.SetColumnSpan(self.tool_strip, 2)
            self.tool_strip.Margin = Thickness(0, 8, 0, 0)
        elif stacked and needed + aside + 24.0 <= total:
            WGrid.SetRow(self.tool_strip, 0)
            WGrid.SetColumn(self.tool_strip, 0)
            WGrid.SetColumnSpan(self.tool_strip, 1)
            self.tool_strip.Margin = Thickness(0)

    def align_group_bar(self):
        """Kept for the callers that ask for a relayout after the columns move."""
        self.reflow_toolbar()

    def show_expand_state(self):
        if self.btn_expand is None:
            return
        try:
            icon_name, image, text = self.btn_expand.Tag
            all_shut = (self.grouping and self.group_labels and
                        len(self.collapsed) >= len(self.group_labels))
            text.Text = 'Expand All' if all_shut else 'Collapse All'
        except Exception:
            pass

    def clear_groups(self):
        """Drop the heading rows. They live at the end of the table, so
        removing them cannot disturb `table.Rows[ridx]` for the real rows."""
        self.group_of = {}
        self.group_row = {}
        try:
            while self.table.Rows.Count > len(self.model.rows):
                self.table.Rows.RemoveAt(self.table.Rows.Count - 1)
        except Exception:
            pass

    def rebuild_groups(self):
        """One heading row per run of equal values in the sorted column."""
        self.clear_groups()
        fi = self.sort_field
        if fi is None:
            return
        model = self.model

        values = {}
        for row in model.rows:
            try:
                if to_text(self.table.Rows[row.ridx]['vis']) != '1':
                    continue
            except Exception:
                continue
            values.setdefault(model.current_text(row, fi.index), []).append(row.ridx)

        order = sorted(values.keys(), key=lambda v: natural_key(v))
        if self.sort_desc:
            order.reverse()

        # a group that keeps its label keeps its collapsed state across a
        # refilter or a re-sort, so reapplying a filter does not spring
        # everything open again
        was_shut = set([self.group_labels[n][0] for n in self.collapsed
                        if n in self.group_labels])
        self.group_of = {}
        self.group_labels = {}
        self.group_row = {}
        self.collapsed = set()
        for n, value in enumerate(order):
            key = '{0:06d}'.format(n)
            members = list(values[value])
            # least significant first, so a stable sort layers them correctly
            for level in range(len(self.sort_stack) - 1, 0, -1):
                sub, sub_desc = self.sort_stack[level]
                members.sort(
                    key=lambda r, f=sub: natural_key(
                        model.current_text(model.rows[r], f.index)),
                    reverse=sub_desc)
            for place, ridx in enumerate(members):
                try:
                    self.table.Rows[ridx]['gkey'] = key + '\x01' +\
                        '{0:08d}'.format(place)
                except Exception:
                    pass
                self.group_of[ridx] = n
            try:
                header = self.table.NewRow()
                header['ridx'] = ''
                header['rn'] = ''
                header['eid'] = ''
                header['vis'] = '1'
                header['gkey'] = key + '\x00'
                header['grp'] = to_text(n)
                # the label goes in the first value column so it reads on the
                # left; every other column is left empty
                self.table.Rows.Add(header)
                self.group_row[n] = self.table.Rows.Count - 1
            except Exception:
                pass
            label = value if value != '' else '(blank)'
            self.group_labels[n] = (label, len(values[value]))
            if label in was_shut:
                self.collapsed.add(n)
            self.write_header_text(n)

        # rows the filter is hiding still need a key, or the sort throws
        for row in model.rows:
            try:
                if not to_text(self.table.Rows[row.ridx]['gkey']):
                    self.table.Rows[row.ridx]['gkey'] = 'zzzzzz'
            except Exception:
                pass

    def group_index_of_header(self, item):
        try:
            return int(to_text(item['grp']))
        except Exception:
            return 0

    def build_grid(self):
        model = self.model
        table = DataTable('schedule')
        for name in GRID_META_COLS:
            table.Columns.Add(name)
        for fi in model.fields:
            table.Columns.Add(fi.col)

        # One call per row rather than one per cell.  Setting each cell by
        # column name was seven calls into .NET plus one per field, for every
        # row; a whole row as an object[] is one, and BeginLoadData switches
        # off the change notifications and index upkeep nobody is listening
        # to yet — the table is not bound until the end of this method.
        table.BeginLoadData()
        try:
            for n, row in enumerate(model.rows):
                row.ridx = n
                values = grid_row_values(model, row, n)
                try:
                    table.Rows.Add(System.Array[System.Object](values))
                except Exception:
                    # the slow way, cell by cell, if the array form is refused
                    dr = table.NewRow()
                    for i, value in enumerate(values):
                        dr[i] = value
                    table.Rows.Add(dr)
        finally:
            table.EndLoadData()

        self.table = table
        self.key_index = build_key_index(model)

        edit_style = self.make_edit_style()

        self.dg.Columns.Clear()
        self.col_field = {}

        c = DataGridTextColumn()
        c.Header = '#'
        c.Binding = Binding('rn')
        c.IsReadOnly = True
        c.Width = DataGridLength(46, DataGridLengthUnitType.Pixel)
        c.CanUserSort = False
        self.dg.Columns.Add(c)

        c = DataGridTextColumn()
        c.Header = 'Id'
        c.Binding = Binding('eid')
        c.IsReadOnly = True
        c.Width = DataGridLength(78, DataGridLengthUnitType.Pixel)
        self.dg.Columns.Add(c)

        self.field_cols = []
        for n, fi in enumerate(model.fields):
            fi.letter = col_letter(n)
        self.header_boxes = {}
        self.header_carets = {}
        self.header_titles = {}
        self.header_badges = {}
        self.header_outlines = {}
        for fi in model.fields:
            col = DataGridTextColumn()
            col.Header = self.column_header(fi)
            col.Binding = Binding(fi.col)
            col.Width = DataGridLength(150, DataGridLengthUnitType.Pixel)
            col.EditingElementStyle = edit_style
            col.IsReadOnly = False
            self.dg.Columns.Add(col)
            self.col_field[col] = fi
            self.field_cols.append(col)

        self.add_column_button()
        self.dg.ItemsSource = table.DefaultView
        self._pos_cache = None
        self._last_sel = _STALE
        try:
            # every sort, filter and edit is reported here, which is what lets
            # the row positions be remembered between scrolls
            table.DefaultView.ListChanged += self.on_view_changed
        except Exception:
            pass
        self._dirty_paint = True

    def ordered_field_columns(self):
        cols = list(self.field_cols)
        cols.sort(key=lambda c: c.DisplayIndex)
        return cols

    # -- resizing -----------------------------------------------------------

    def wire_grips(self, f):
        """A borderless AllowsTransparency window carries its own frame."""
        self._grips = {}
        for name, horiz, vert in (('GripN', 0, -1), ('GripS', 0, 1),
                                  ('GripW', -1, 0), ('GripE', 1, 0),
                                  ('GripNW', -1, -1), ('GripNE', 1, -1),
                                  ('GripSW', -1, 1), ('GripSE', 1, 1)):
            try:
                thumb = f(name)
                if thumb is None:
                    continue
                self._grips[thumb] = (horiz, vert)
                thumb.DragDelta += self.on_grip_drag
                thumb.DragStarted += self.on_grip_start
                if name in ('GripN', 'GripS'):
                    # preview, not MouseDoubleClick: a Thumb marks the mouse
                    # down handled to start its drag, which can swallow the
                    # double-click event entirely
                    thumb.PreviewMouseLeftButtonDown += self.on_edge_double_click
            except Exception:
                continue

    def on_grip_start(self, sender, args):
        self._snap_break = 0.0

    def build_drawer(self, f):
        """Wire the shrink-to-taskbar control, the same one every dialog gets."""
        try:
            self.grip_host = f('GripHost')
        except Exception:
            self.grip_host = None
        button = f('ShrinkBtn')
        self.drawer = WindowDrawer(self.window, f('HeaderBar'), f('RootGrid'),
                                   button, self.on_drawer_state)
        try:
            button.Click += self.drawer.toggle
        except Exception:
            pass

    def on_drawer_state(self, shrunk):
        """Park the resize grips with the window.

        They sit in an overlay spanning every row, so left behind they would
        line the parked bar with invisible drag handles and swallow clicks on
        the arrow that brings the window back.
        """
        try:
            if self.grip_host is not None:
                self.grip_host.Visibility = (Visibility.Collapsed if shrunk
                                             else Visibility.Visible)
        except Exception:
            pass
        if not shrunk:
            # cell colours are painted onto realised rows, so the grid gets
            # the same nudge it gets after a maximise
            self.repaint_soon()

    def window_work_area(self):
        """The working area of the screen this window is on, in WPF units.

        Shared with the drawer, which parks the window against the bottom of
        this same rectangle, so there is one answer rather than two.
        """
        return screen_work_area(self.window)

    def on_edge_double_click(self, sender, args):
        """Fill the screen height, keeping the width — the vertical half of a
        maximise, which is what a double-click on a window edge does."""
        if self.drawer is not None and (self.drawer.shrunk or self.drawer.busy):
            return                      # nothing to stretch while it is away
        try:
            if args.ClickCount != 2:
                return
            args.Handled = True
        except Exception:
            return
        w = self.window
        try:
            if self.vstretch is None:
                left, top, width, height = self.window_work_area()
                self.vstretch = (w.Top, w.Height)
                self.restore_rect = None
                w.Top = top
                w.Height = height
                self.set_status(u'Stretched to the full height — double-click an '
                                'edge again to put it back.')
            else:
                top, height = self.vstretch
                self.vstretch = None
                w.Top = top
                w.Height = height
        except Exception:
            pass
        self.align_group_bar()
        self.place_handle()

    def on_grip_drag(self, sender, args):
        if self.drawer is not None and (self.drawer.shrunk or self.drawer.busy):
            return                      # the parked bar is not resizable
        edges = self._grips.get(sender)
        if edges is None:
            return
        horiz, vert = edges
        w = self.window
        self.restore_rect = None

        if self.vstretch is not None and vert:
            # Pulling a vertical edge away from the snap puts the window back to
            # the height it had before, rather than resizing from the stretched
            # one. A few pixels of slack first, so a twitch on the way to a
            # sideways drag cannot undo the snap.
            try:
                self._snap_break += abs(args.VerticalChange)
            except Exception:
                self._snap_break = SNAP_BREAK_PX + 1
            if self._snap_break < SNAP_BREAK_PX:
                return
            top, height = self.vstretch
            self.vstretch = None
            try:
                # the edge under the cursor stays put; the opposite one moves
                if vert < 0:
                    w.Height = height
                else:
                    bottom = w.Top + w.ActualHeight
                    w.Top = bottom - height
                    w.Height = height
            except Exception:
                pass
            self.set_status('Back to its own height.')
        elif self.vstretch is not None and horiz:
            pass                     # a sideways drag leaves the snap alone

        try:
            min_w = w.MinWidth or 320
            min_h = w.MinHeight or 240
            dx = args.HorizontalChange
            dy = args.VerticalChange

            if horiz > 0:
                w.Width = max(min_w, w.ActualWidth + dx)
            elif horiz < 0:
                new_w = max(min_w, w.ActualWidth - dx)
                w.Left = w.Left + (w.ActualWidth - new_w)
                w.Width = new_w

            if vert > 0:
                w.Height = max(min_h, w.ActualHeight + dy)
            elif vert < 0:
                new_h = max(min_h, w.ActualHeight - dy)
                w.Top = w.Top + (w.ActualHeight - new_h)
                w.Height = new_h
        except Exception:
            pass
        self.place_handle()

    # -- Excel round trip ---------------------------------------------------

    def export_payload(self):
        """The grid as plain values, in the order the grid is currently showing.

        Scratch columns are left out — they mean nothing outside this window and
        would come back as unmatched headings.
        """
        model = self.model
        fields = []
        keep = []
        for fi in model.fields:
            if getattr(fi, 'scratch', False):
                continue
            keep.append(fi)
            fields.append({'name': fi.name, 'letter': fi.letter,
                           'is_type': bool(fi.is_type),
                           'editable': bool(fi.supported),
                           'reason': fi.reason})
        rows = []
        order = self.visible_row_order()
        for ridx in order:
            row = model.rows[ridx]
            values = []
            editable = []
            is_type = []
            for fi in keep:
                ci = row.cells[fi.index]
                values.append(model.current_text(row, fi.index))
                editable.append(bool(ci.editable))
                is_type.append(bool(ci.is_type))
            rows.append({'eid': to_text(eid_value(row.elem_id)),
                         'values': values, 'editable': editable,
                         'is_type': is_type})
        return fields, rows

    def visible_row_order(self):
        """Row indexes as the grid shows them, so the export matches the screen."""
        out = []
        try:
            for i in range(self.dg.Items.Count):
                item = self.dg.Items[i]
                if self.is_header_row(item):
                    continue
                out.append(int(item['ridx']))
        except Exception:
            out = [row.ridx for row in self.model.rows]
        return out

    def on_excel(self, sender=None, args=None):
        """Both directions behind one button, since they are the same job."""
        dlg = ThemedDialog('Excel', width=560, owner=self.window, accent=C_GREEN)
        dlg.add(_tb('Take this schedule out to a workbook, or bring an edited '
                    'one back.', C_TEXT, 12, False, True))
        note = _tb(u'Only the round-trip export can be imported again — the '
                   'presentation layout carries no Revit IDs to match on.',
                   C_MUTED, 11, False, True)
        note.Margin = Thickness(0, 10, 0, 0)
        dlg.add(note)
        dlg.add_button('Cancel', 'ghost', None)
        dlg.add_button('Import from Excel', 'orange', 'import')
        dlg.add_button('Export to Excel', 'green', 'export')
        choice = dlg.show()
        if choice == 'export':
            self.on_export()
        elif choice == 'import':
            self.on_import()

    def on_export(self, sender=None, args=None):
        try:
            export_dialog(self)
        except Exception:
            themed_message('Export to Excel',
                           'The export could not be run:\n\n' + traceback.format_exc(),
                           accent=C_RED, width=700, owner=self.window)

    def on_import(self, sender=None, args=None):
        if excel_bridge is None:
            themed_message('Import from Excel',
                           'The Excel module could not be loaded:\n\n' + EXCEL_ERROR,
                           accent=C_RED, width=680, owner=self.window)
            return
        path = ask_open_path()
        if not path:
            return
        try:
            table = xlsx_io.read_sheet(path, 0)
        except Exception:
            themed_message('Import from Excel',
                           'That workbook could not be read:\n\n' + traceback.format_exc(),
                           accent=C_RED, width=700, owner=self.window)
            return

        fields, rows = self.export_payload()
        # the field list the import matches against is the same one the export
        # wrote, so a scratch column can never collide with a real heading
        keep = [fi for fi in self.model.fields if not getattr(fi, 'scratch', False)]
        by_eid = {}
        for row in rows:
            by_eid[row['eid']] = row

        try:
            res = excel_bridge.parse_import(table, fields, by_eid)
        except Exception:
            themed_message('Import from Excel',
                           'That workbook could not be matched to this schedule:\n\n'
                           + traceback.format_exc(),
                           accent=C_RED, width=700, owner=self.window)
            return

        if res.errors:
            themed_message('Import from Excel', '\n\n'.join(res.errors),
                           accent=C_RED, width=680, owner=self.window)
            return

        remember_folder(path)
        if import_report(self, res, path) != 'stage':
            self.set_status(u'Import cancelled — nothing was staged.')
            return

        index = {}
        for row in self.model.rows:
            index[to_text(eid_value(row.elem_id))] = row.ridx

        self.begin_batch()
        self._importing = True
        staged = 0
        turned = 0
        for eid, fidx, old, new in res.changes:
            ridx = index.get(eid)
            if ridx is None:
                continue
            real = keep[fidx].index if fidx < len(keep) else fidx
            if self.stage(ridx, real, new):
                self.imported.add((ridx, real))
                staged += 1
            else:
                turned += 1
        self._importing = False
        self.end_batch()
        self.build_legend()
        self.repaint_soon()
        msg = (u'Imported {0} change{1} from {2} — check the grid, then '
               u'press APPLY.'.format(staged, '' if staged == 1 else 's',
                                      os.path.basename(path)))
        msg += self.skipped_note(turned, 'not imported')
        self.set_status(msg)

    # -- formula bar --------------------------------------------------------

    def wire_formula_bar(self, f):
        self.formula_bar = f('FormulaBar')
        self.formula_box = f('FormulaBox')
        self.formula_ink = f('FormulaInk')
        self.formula_hint = f('FormulaHint')
        self.btn_pick = f('BtnFormulaPick')
        try:
            self.btn_pick.Click += self.on_pick_toggle
        except Exception:
            pass
        for name, handler in (('BtnFormulaApply', self.on_formula_apply),
                              ('BtnFormulaCancel', self.on_formula_cancel)):
            try:
                f(name).Click += handler
            except Exception:
                pass
        try:
            self.formula_box.TextChanged += self.on_formula_changed
            self.formula_box.PreviewKeyDown += self.on_formula_key
        except Exception:
            pass

    def on_formula(self, sender, args):
        """Open the bar on the current selection, or shut it if it is open."""
        if self.formula_bar is None:
            themed_message('Formula',
                           'The formula bar did not load with the window, so it '
                           'cannot be opened. Please report this.',
                           accent=C_RED, owner=self.window)
            return
        try:
            if self.formula_bar.Visibility == Visibility.Visible:
                self.close_formula_bar()
                return
        except Exception:
            pass
        # opens whether or not anything is selected: an empty bar that says
        # what it needs is better than a button that appears to do nothing
        self.formula_cells = self.editable_selection()
        self.formula_pick = bool(self.formula_cells)
        self.show_pick_state()
        try:
            self.formula_bar.Visibility = Visibility.Visible
            self.formula_box.Text = self.last_formula or '='
            self.formula_box.CaretIndex = len(self.formula_box.Text)
            self.formula_box.Focus()
        except Exception:
            pass
        self.paint_formula()
        self.reflow_toolbar()

    def editable_selection(self):
        out = []
        for c in self.sel_cells():
            try:
                if self.model.rows[c['ridx']].cells[c['fidx']].editable:
                    out.append(c)
            except Exception:
                continue
        return out

    def on_pick_toggle(self, sender=None, args=None):
        self.formula_pick = not self.formula_pick
        if self.formula_pick:
            self.formula_cells = self.editable_selection() or self.formula_cells
        self.show_pick_state()
        self.paint_formula()

    def show_pick_state(self):
        if self.btn_pick is None:
            return
        try:
            self.btn_pick.Content = ('Picking refs' if self.formula_pick
                                     else 'Pick refs')
            self.btn_pick.Foreground = brush(
                C_ORANGE if self.formula_pick else C_MUTED)
            self.btn_pick.ToolTip = (
                u'Clicking a cell puts its reference in the formula — turn off '
                'to choose the cells to write into instead'
                if self.formula_pick else
                u'Clicking a cell selects it as a target — turn on to put cell '
                'references into the formula instead')
        except Exception:
            pass

    def close_formula_bar(self):
        self.formula_cells = []
        self.formula_pick = True
        self.btn_pick = None
        try:
            self.formula_bar.Visibility = Visibility.Collapsed
        except Exception:
            pass
        self.focus_grid()

    def on_formula_cancel(self, sender, args):
        self.close_formula_bar()
        self.set_status('Formula cancelled.')

    def formula_open(self):
        try:
            return self.formula_bar.Visibility == Visibility.Visible
        except Exception:
            return False

    def on_formula_changed(self, sender, args):
        self.paint_formula()

    def on_formula_key(self, sender, args):
        try:
            key = args.Key
        except Exception:
            return
        if key == Key.Enter:
            args.Handled = True
            self.on_formula_apply(None, None)
        elif key == Key.Escape:
            args.Handled = True
            self.on_formula_cancel(None, None)

    def paint_formula(self):
        """Redraw the coloured text behind the editor, and preview a row."""
        text = ''
        try:
            text = self.formula_box.Text or ''
        except Exception:
            pass
        try:
            self.formula_ink.Inlines.Clear()
            order = []
            for start, length, kind, key in formula_spans(text):
                run = Run(text[start:start + length])
                if kind == 'cell':
                    run.Foreground = brush(formula_ref_colour(key, order))
                    run.FontWeight = FontWeights.Bold
                elif kind == 'func':
                    run.Foreground = brush(C_ORANGE)
                    run.FontWeight = FontWeights.Bold
                elif kind == 'text':
                    run.Foreground = brush(C_EDIT_FG)
                elif kind == 'number':
                    run.Foreground = brush(C_IMP_FG)
                elif kind == 'op':
                    run.Foreground = brush(C_MUTED)
                else:
                    run.Foreground = brush(C_TEXT)
                self.formula_ink.Inlines.Add(run)
        except Exception:
            pass
        self.preview_formula(text)

    def preview_formula(self, text):
        cells = self.formula_cells
        if not cells:
            try:
                self.formula_hint.Text = (
                    'No cells picked to write into. Turn Pick refs off and '
                    'select the cells you want the result in.')
                self.formula_hint.Foreground = brush(C_ORANGE)
            except Exception:
                pass
            return
        try:
            if not to_text(text).strip().lstrip('='):
                self.formula_hint.Text = (
                    'Type a formula, or click cells in the table to put their '
                    'references into it. A5 means that cell and follows the row '
                    'down; A$5 stays on row 5; a bare A is this row.')
                self.formula_hint.Foreground = brush(C_MUTED)
                return
        except Exception:
            pass
        ok = 0
        first = ''
        error = ''
        for i, cell in enumerate(cells):
            ctx = self.formula_context(cell, i + 1)
            try:
                out = evaluate_formula(text, ctx)
            except FormulaError as err:
                error = to_text(err)
                break
            except Exception:
                error = 'that formula could not be read'
                break
            ok += 1
            if not first:
                first = out
        try:
            if error:
                self.formula_hint.Text = error
                self.formula_hint.Foreground = brush(C_FAIL_FG)
            else:
                self.formula_hint.Text = u'{0} \u2192 "{1}"   and {2} cell{3} in ' \
                    u'all'.format(cells[0]['col'].Header if False else 'first cell',
                                  first, ok, '' if ok == 1 else 's')
                self.formula_hint.Foreground = brush(C_EDIT_FG)
        except Exception:
            pass

    def insert_reference(self, ridx, fi):
        """Put a clicked cell's address into the formula at the caret."""
        if not self.formula_open():
            return False
        try:
            row_number = self.model.rows[ridx].ridx + 1
            ref = '{0}{1}'.format(fi.letter, row_number)
            box = self.formula_box
            at = box.CaretIndex
            text = box.Text or ''
            box.Text = text[:at] + ref + text[at:]
            box.CaretIndex = at + len(ref)
            box.Focus()
        except Exception:
            return False
        return True

    def on_formula_apply(self, sender, args):
        text = ''
        try:
            text = self.formula_box.Text or ''
        except Exception:
            pass
        cells = self.formula_cells
        if not cells or not to_text(text).strip().lstrip('='):
            return
        values = []
        for i, cell in enumerate(cells):
            ctx = self.formula_context(cell, i + 1)
            try:
                values.append((cell, evaluate_formula(text, ctx)))
            except FormulaError as err:
                self.formula_hint.Text = to_text(err)
                self.formula_hint.Foreground = brush(C_FAIL_FG)
                return
            except Exception:
                self.formula_hint.Text = 'that formula could not be read'
                self.formula_hint.Foreground = brush(C_FAIL_FG)
                return
        self.last_formula = text
        self.begin_batch()
        n = 0
        for cell, value in values:
            if self.stage_cell(cell['pos'], cell['col'], value):
                n += 1
        self.end_batch()
        self.close_formula_bar()
        self.set_status('Formula wrote {0} cell{1}.'.format(
            n, '' if n == 1 else 's'))

    # -- legend, theme, window size ----------------------------------------

    def build_legend(self):
        """The footer key. Rebuilt on a theme switch so it always matches."""
        host = self.legend_host
        if host is None:
            return
        try:
            host.Children.Clear()
        except Exception:
            return
        cap = _tb('Cell colours', C_MUTED, 11, True)
        cap.VerticalAlignment = VerticalAlignment.Center
        cap.Margin = Thickness(0, 0, 10, 0)
        host.Children.Add(cap)
        entries = [
            (C_INST_BG, C_INST_FG, C_BLUE, u'Instance parameter — edits this element only'),
            (C_TYPE_BG, C_TYPE_FG, C_ORANGE, u'Type parameter — edits every element of that type'),
            (C_RO_BG, C_RO_FG, C_RO_FG, u'Not editable — read only'),
            (C_EDIT_BG, C_EDIT_FG, C_GREEN, u'Edited — not yet applied'),
            (C_FAIL_BG, C_FAIL_FG, C_RED, 'Refused by Revit'),
        ]
        if self.imported:
            entries.append((C_IMP_BG, C_IMP_FG, C_IMP_FG,
                            u'Changed by the Excel import — not yet applied'))
        if self.scratch:
            entries.append((C_TEST_BG, C_TEST_FG, C_TEST_FG,
                            u'Test column — never written to the model'))
        for bg, fg, edge, label in entries:
            chip = Border()
            chip.Background = brush(bg)
            chip.BorderBrush = brush(edge)
            chip.BorderThickness = Thickness(1)
            chip.CornerRadius = CornerRadius(2)
            chip.Padding = Thickness(7, 2, 7, 2)
            chip.Margin = Thickness(0, 0, 6, 3)
            chip.Child = _tb(label, fg, 11)
            host.Children.Add(chip)

    def on_theme(self, sender, args):
        self.set_theme_to('light' if THEME_NAME == 'dark' else 'dark')

    def set_theme_to(self, name):
        set_theme(name)
        res = self.window.Resources
        for key, value in palette_brushes():
            try:
                res[key] = brush(value)
            except Exception:
                pass
        # toolbar glyphs and labels
        for name, icon, label, tip, handler in self.tool_defs:
            btn = self.tool_buttons.get(name)
            if btn is None:
                continue
            try:
                icon_name, image, text = btn.Tag
                image.Source = toolbar_icon(icon_name)
                text.Foreground = brush(C_TEXT)
            except Exception:
                pass
        try:
            for button in (self.btn_excel, self.btn_isolate):
                icon_name, image, text = button.Tag
                image.Source = toolbar_icon(icon_name)
                text.Foreground = brush(C_TEXT)
        except Exception:
            pass
        self.show_theme_state()
        # headers are built in code, so their brushes need setting by hand
        try:
            for box in self.header_boxes.values():
                box.Foreground = brush(C_TEXT)
        except Exception:
            pass
        self.mark_filtered_columns()
        self.mark_sorted_column()
        self.show_group_state()
        self.show_expand_state()
        # the cell editor is built in code, so it needs rebuilding by hand
        try:
            style = self.make_edit_style()
            for col in self.field_cols:
                col.EditingElementStyle = style
        except Exception:
            pass
        self.build_legend()
        self.save_settings()
        self._dirty_paint = True
        self.repaint_soon()
        self.set_status('Switched to the {0} canvas.'.format(THEME_NAME))

    @property
    def theme_name(self):
        """What the egg asks for, so its games open in the right palette."""
        return THEME_NAME

    def show_theme_state(self):
        """The chip names the canvas it is on; the tooltip names the switch.

        Both readings of a theme button are common — the mode you are in, and
        the mode you would go to — so it says one and explains the other rather
        than picking one and leaving it ambiguous.
        """
        if self.drawer is not None:
            # the arrow carries a local brush, which a palette swap cannot
            # reach, so it is repainted alongside the chip
            self.drawer.paint_button()
        if self.btn_theme is None:
            return
        try:
            light = (THEME_NAME == 'light')
            self.btn_theme.Content = 'Light' if light else 'Dark'
            self.btn_theme.ToolTip = (
                u'Light canvas — click for dark (Ctrl+Shift+T)' if light
                else u'Dark canvas — click for light (Ctrl+Shift+T)')
        except Exception:
            pass

    def on_maximise(self, sender, args):
        if self.drawer is not None and self.drawer.shrunk:
            # F11 or a double-click on the parked bar means "bring it back",
            # not "fill the screen with a window nobody can see"
            self.drawer.expand()
            return
        w = self.window
        try:
            if self.restore_rect is None:
                self.vstretch = None
                self.restore_rect = (w.Left, w.Top, w.Width, w.Height)
                left, top, width, height = self.window_work_area()
                w.Left = left
                w.Top = top
                w.Width = width
                w.Height = height
                if self.max_btn is not None:
                    self.max_btn.Content = u'\u2750'
                    self.max_btn.ToolTip = 'Restore the window size (F11)'
            else:
                left, top, width, height = self.restore_rect
                self.restore_rect = None
                w.Left = left
                w.Top = top
                w.Width = width
                w.Height = height
                if self.max_btn is not None:
                    self.max_btn.ToolTip = 'Full screen (F11, or double-click the header)'
        except Exception:
            pass
        self.repaint_soon()

    # -- highlights ---------------------------------------------------------

    def highlight_for(self, ridx, fidx):
        """Cell beats row beats column, so a single cell can override a band."""
        for store, key in ((self.cell_hl, (ridx, fidx)),
                           (self.row_hl, ridx),
                           (self.col_hl, fidx)):
            hit = store.get(key)
            if hit is not None:
                return hit
        return None

    def on_highlight(self, sender, args):
        try:
            highlight_dialog(self)
        except Exception:
            self.set_status('The highlight tool could not be opened.')

    def apply_highlight(self, colour, mode, scope):
        cells = self.sel_cells()
        if not cells:
            self.set_status('Select the cells to highlight first.')
            return 0
        n = 0
        if scope == 'rows':
            for ridx in set([c['ridx'] for c in cells]):
                self.row_hl[ridx] = (colour, mode)
                n += 1
        elif scope == 'cols':
            for fidx in set([c['fidx'] for c in cells]):
                self.col_hl[fidx] = (colour, mode)
                n += 1
        else:
            for c in cells:
                self.cell_hl[(c['ridx'], c['fidx'])] = (colour, mode)
                n += 1
        self.repaint_soon()
        return n

    def clear_highlight(self, scope):
        cells = self.sel_cells()
        n = 0
        if scope == 'all':
            n = len(self.cell_hl) + len(self.row_hl) + len(self.col_hl)
            self.cell_hl = {}
            self.row_hl = {}
            self.col_hl = {}
        else:
            for c in cells:
                if self.cell_hl.pop((c['ridx'], c['fidx']), None) is not None:
                    n += 1
                if self.row_hl.pop(c['ridx'], None) is not None:
                    n += 1
                if self.col_hl.pop(c['fidx'], None) is not None:
                    n += 1
        self.repaint_soon()
        return n

    # -- scratch columns ----------------------------------------------------

    def add_column_button(self):
        """A last column carrying nothing but the green +.

        A DataGrid has nowhere to hang a control at the right of the header
        strip, so the + is the header of a column of its own. It stays last, and
        new scratch columns are inserted in front of it.
        """
        col = DataGridTextColumn()
        button = Button()
        button.Content = '+'
        button.ToolTip = (u'Add a test column — scratch space for building '
                          'formulas, never written to the model')
        try:
            button.Style = self.window.Resources['AddColBtn']
        except Exception:
            pass
        button.Click += (lambda sender, args: self.on_add_scratch())
        col.Header = button
        col.Width = DataGridLength(40, DataGridLengthUnitType.Pixel)
        col.CanUserSort = False
        col.CanUserResize = False
        col.IsReadOnly = True
        self.dg.Columns.Add(col)
        self.plus_col = col
        return col

    def on_add_scratch(self):
        if self.add_scratch_column():
            self.set_status(u'Added test column {0} — it takes formulas like any '
                            'other and is never written to the model.'.format(
                                self.model.fields[-1].letter))

    def add_scratch_column(self):
        model = self.model
        if len(model.fields) >= 60:
            return False
        fi = FieldInfo()
        fi.index = len(model.fields)
        fi.col = 's{0}'.format(self.scratch)
        fi.letter = col_letter(fi.index)
        fi.name = 'Test {0}'.format(self.scratch + 1)
        fi.scratch = True
        fi.supported = True
        model.fields.append(fi)
        for row in model.rows:
            ci = CellInfo()
            ci.editable = True
            ci.scratch = True
            ci.original = ''
            row.cells.append(ci)
        try:
            self.table.Columns.Add(fi.col)
            for row in model.rows:
                self.table.Rows[row.ridx][fi.col] = ''
        except Exception:
            return False
        col = DataGridTextColumn()
        col.Header = self.column_header(fi)
        col.Binding = Binding(fi.col)
        col.Width = DataGridLength(150, DataGridLengthUnitType.Pixel)
        col.EditingElementStyle = self.make_edit_style()
        try:
            at = self.dg.Columns.IndexOf(self.plus_col)
            if at < 0:
                at = self.dg.Columns.Count
            self.dg.Columns.Insert(at, col)
        except Exception:
            self.dg.Columns.Add(col)
        self.col_field[col] = fi
        self.field_cols.append(col)
        self.scratch += 1
        self.refresh_scratch_headers()
        self.build_legend()
        self.repaint_soon()
        return True

    def remove_scratch_column(self):
        model = self.model
        if not self.scratch:
            return False
        fi = model.fields[-1]
        if not getattr(fi, 'scratch', False):
            return False
        col = None
        for c, f in self.col_field.items():
            if f is fi:
                col = c
                break
        try:
            if col is not None:
                self.dg.Columns.Remove(col)
                self.col_field.pop(col, None)
                if col in self.field_cols:
                    self.field_cols.remove(col)
            self.table.Columns.Remove(fi.col)
        except Exception:
            pass
        model.fields.pop()
        for row in model.rows:
            if row.cells:
                row.cells.pop()
            model.scratch_values.pop(('S', row.ridx, fi.index), None)
        for key in list(self.col_hl.keys()):
            if key >= fi.index:
                self.col_hl.pop(key, None)
        for key in list(self.cell_hl.keys()):
            if key[1] >= fi.index:
                self.cell_hl.pop(key, None)
        self.scratch -= 1
        self.refresh_scratch_headers()
        self.build_legend()
        self.repaint_soon()
        return True

    def refresh_scratch_headers(self):
        """Rebuild the test columns' headings, so the remove button sits on
        whichever one is now last."""
        try:
            for col, fi in self.col_field.items():
                if getattr(fi, 'scratch', False):
                    col.Header = self.column_header(fi)
        except Exception:
            pass

    def make_edit_style(self):
        style = WStyle(clr.GetClrType(TextBox))
        style.Setters.Add(WSetter(TextBox.BackgroundProperty, brush(C_EDITOR_BG)))
        style.Setters.Add(WSetter(TextBox.ForegroundProperty, brush(C_EDITOR_FG)))
        style.Setters.Add(WSetter(TextBox.BorderBrushProperty, brush(C_ORANGE)))
        style.Setters.Add(WSetter(TextBox.BorderThicknessProperty, Thickness(1)))
        style.Setters.Add(WSetter(TextBox.PaddingProperty, Thickness(4, 0, 0, 0)))
        style.Setters.Add(WSetter(TextBox.CaretBrushProperty, brush(C_ORANGE)))
        return style

    def save_settings(self):
        try:
            save_settings({'theme': THEME_NAME})
        except Exception:
            pass

    # -- small utilities ----------------------------------------------------

    def prove_alive(self):
        """Called by every handler that might be the first to run after the
        window is shown.  If none ever reaches it, the engine died with the
        command and the window is inert.

        Proof only counts once show() has returned.  Before 1.19.0 it counted
        from the constructor, whose "rows loaded" status line used up the
        one-shot proof before the window existed — so no launch was ever
        recorded as alive, every next launch looked like a dead window, and
        the tool kept offering to switch to modal.  Anyone who accepted was
        left with Revit blocked for good.
        """
        # plain reads on purpose: getattr with a default would hide these from
        # the bench check, and both flags are the first things __init__ sets
        if self._proved or not self._shown:
            return
        self._proved = True
        try:
            if load_settings().get('modeless_pending'):
                save_settings({'modeless_pending': False, 'modeless_proved': True})
        except Exception:
            pass

    def on_any_mouse(self, sender, args):
        """The pointer crossing the window is the earliest sign of life a
        modeless window gets.  One attribute read once it has been seen."""
        if not self._proved:
            self.prove_alive()

    def set_status(self, text):
        self.prove_alive()
        try:
            self.status.Text = text
        except Exception:
            pass

    def update_pending(self):
        n = len(self.model.edits)
        levels = len(self.model.level_edits)
        try:
            if n or levels:
                bits = []
                if n:
                    bits.append('{0} cell edit{1}'.format(n, '' if n == 1 else 's'))
                if levels:
                    bits.append('{0} level change{1}'.format(
                        levels, '' if levels == 1 else 's'))
                self.pending.Text = u'{0} pending — nothing is written until APPLY'.format(
                    ' and '.join(bits))
                self.pending.Foreground = brush(C_EDIT_FG)
            else:
                self.pending.Text = 'No pending edits'
                self.pending.Foreground = brush(C_MUTED)
            self.btn_apply.IsEnabled = bool(n or levels)
        except Exception:
            pass

    def pos_map(self):
        """Where each model row sits in the grid as it is currently ordered.

        Walking every row costs three calls into .NET per row, and this was
        rebuilt on every scroll tick and every selection change.  It is now
        kept until the view's order can have changed — the DataView reports
        every sort, filter and row change through ListChanged — with the row
        count checked as well, as a second line of defence.
        """
        items = self.dg.Items
        count = items.Count
        cache = self._pos_cache
        if cache is not None and cache[0] == count:
            return cache[1]
        out = {}
        for i in range(count):
            try:
                out[int(items[i]['ridx'])] = i
            except Exception:
                pass
        self._pos_cache = (count, out)
        return out

    def on_view_changed(self, sender, args):
        """The rows have been sorted, filtered, added to or edited."""
        self._pos_cache = None
        self._last_sel = _STALE

    def on_columns_changed(self, sender, args):
        """A column moved or was added, so the right-most selected cell may
        be a different one — the fill handle has to look again.  A rebuild
        adds every column in turn, so this goes through the same once-per-
        burst queue as a selection change."""
        self.on_selection_changed(sender, args)

    def sel_cells(self):
        out = []
        try:
            pmap = self.pos_map()
            for ci in self.dg.SelectedCells:
                try:
                    col = ci.Column
                    fi = self.col_field.get(col)
                    if fi is None:
                        continue
                    ridx = int(ci.Item['ridx'])
                    out.append({'pos': pmap.get(ridx, -1), 'col': col,
                                'ridx': ridx, 'fidx': fi.index})
                except Exception:
                    continue
        except Exception:
            pass
        out = [d for d in out if d['pos'] >= 0]
        out.sort(key=lambda d: (d['pos'], d['col'].DisplayIndex))
        return out

    def text_at(self, pos, col):
        fi = self.col_field.get(col)
        if fi is None:
            return None
        try:
            ridx = int(self.dg.Items[pos]['ridx'])
        except Exception:
            return None
        return self.model.current_text(self.model.rows[ridx], fi.index)

    def select_cell(self, pos, col):
        try:
            item = self.dg.Items[pos]
            info = DataGridCellInfo(item, col)
            self.dg.SelectedCells.Clear()
            self.dg.SelectedCells.Add(info)
            self.dg.CurrentCell = info
            self.dg.ScrollIntoView(item, col)
        except Exception:
            pass

    # -- staged edits -------------------------------------------------------

    def begin_batch(self):
        self._batch = {}
        self.last_refusal = u''
        self.refused = 0

    # -- worksets ------------------------------------------------------------

    def workset_col(self, col):
        fi = self.col_field.get(col)
        return fi is not None and fi.index in self.model.workset_fields

    def workset_targets(self, cell=None):
        """The editable Workset cells a choice will be staged on, as
        (row, field) pairs: every one in the selection, or just the cell that
        was clicked when it is not part of the selection."""
        out, seen, clicked_in = [], set(), False
        for info in self.dg.SelectedCells:
            try:
                fi = self.col_field.get(info.Column)
                if fi is None or fi.index not in self.model.workset_fields:
                    continue
                ridx = int(info.Item['ridx'])
                if (cell is not None and info.Item is cell.DataContext
                        and info.Column is cell.Column):
                    clicked_in = True
            except Exception:
                continue
            pair = (ridx, fi.index)
            if pair in seen:
                continue
            seen.add(pair)
            if self.model.rows[ridx].cells[fi.index].editable:
                out.append(pair)
        if cell is not None and not clicked_in:
            out = []
            try:
                fi = self.col_field.get(cell.Column)
                ridx = int(cell.DataContext['ridx'])
                if self.model.rows[ridx].cells[fi.index].editable:
                    out.append((ridx, fi.index))
            except Exception:
                pass
        return out

    def cell_selected(self, cell):
        """Is this cell in the selection?  Asked of the collection itself — one
        call into .NET, not a Python loop over a selection that can run to a
        hundred thousand cells after Ctrl+A."""
        try:
            return bool(self.dg.SelectedCells.Contains(
                DataGridCellInfo(cell.DataContext, cell.Column)))
        except Exception:
            pass
        for info in self.dg.SelectedCells:
            try:
                if info.Item is cell.DataContext and info.Column is cell.Column:
                    return True
            except Exception:
                continue
        return False

    def double_click_workset(self, args):
        """The second click of a double-click on a Workset cell.  True when it
        was dealt with here."""
        try:
            cell = walk_up(self.dg.InputHitTest(args.GetPosition(self.dg)),
                           DataGridCell)
        except Exception:
            cell = None
        if cell is None or not self.workset_col(cell.Column):
            return False
        args.Handled = True
        drop = self.ws_dropdown
        if drop is not None and not drop.closed:
            drop.reclaim()
        else:
            self.open_workset_dropdown_soon(cell)
        return True

    def current_cell_element(self):
        """The DataGridCell of the current cell, if it is on screen."""
        try:
            current = self.dg.CurrentCell
            container = self.dg.ItemContainerGenerator.ContainerFromItem(
                current.Item)
            content = current.Column.GetCellContent(container)
            return walk_up(content, DataGridCell)
        except Exception:
            return None

    def open_workset_dropdown_soon(self, cell=None, seed=u''):
        """Open the list once the grid has finished with the click or key that
        asked for it — opened from inside the grid's own handling, the mouse
        release lands on the main window and takes the focus straight back."""
        def _open():
            self.open_workset_dropdown(cell, seed)
        try:
            self.window.Dispatcher.BeginInvoke(DispatcherPriority.Background,
                                               Action(_open))
        except Exception:
            _open()

    def open_workset_dropdown(self, cell=None, seed=u''):
        model = self.model
        if not model.workset_fields:
            self.set_status('This schedule has no Workset column.')
            return
        if not model.worksets:
            self.set_status(u'Not a workshared model \u2014 there are no '
                            u'worksets to choose from.')
            return
        targets = self.workset_targets(cell)
        if not targets:
            self.set_status(u'Select one or more cells in the Workset column '
                            u'first \u2014 read-only ones are left out.')
            return
        if self.ws_dropdown is not None:
            self.ws_dropdown.close()
        values = set(model.current_text(model.rows[r], f) for r, f in targets)
        current = values.pop() if len(values) == 1 else None
        names = [name for name, _id in model.worksets]
        drop = WorksetDropdown(self, targets, names, current, seed)
        self.ws_dropdown = drop
        if cell is None:
            cell = self.current_cell_element()
        try:
            if cell is not None:
                top_left = screen_point(cell, 0, 0)
                bottom = screen_point(cell, 0, cell.ActualHeight)
                drop.show_at(top_left.X, top_left.Y, bottom.Y, cell.ActualWidth)
            else:
                pointer = Mouse.GetPosition(self.dg)
                at = screen_point(self.dg, pointer.X, pointer.Y)
                drop.show_at(at.X, at.Y, at.Y, 260)
        except Exception:
            self.ws_dropdown = None
            self.set_status('Could not open the workset list.')

    def apply_workset(self, targets, name):
        """Stage one workset on every target cell, as one undo step."""
        self.begin_batch()
        done, skipped = 0, 0
        for ridx, fidx in targets:
            if self.stage(ridx, fidx, name):
                done += 1
            else:
                skipped += 1
        self.end_batch()
        rows = len(set(r for r, f in targets))
        msg = u'Workset "{0}" staged on {1} row{2}.'.format(
            name, rows, '' if rows == 1 else 's')
        msg += self.skipped_note(skipped)
        msg += u'  Nothing moves in the model until APPLY.'
        self.set_status(msg)

    def on_set_workset(self, sender=None, args=None):
        self.open_workset_dropdown_soon(None)

    def fill_values(self, col, seeds, count, downward):
        """What a fill writes: the ordinary series, or a straight copy in a
        Workset column, where counting would invent workset names."""
        fi = self.col_field.get(col)
        if fi is not None and fi.index in self.model.workset_fields:
            return fill_copy_only(seeds, count, downward)
        return fill_plan(seeds, count, downward)

    def skipped_note(self, skipped, verb='left alone'):
        """'  N cells left alone.' - saying why, when the reason is not simply
        that they are read only (a workset name that is not a workset, say)."""
        if not skipped:
            return u''
        refused = min(self.refused, skipped)
        read_only = skipped - refused
        out = u''
        if read_only:
            out += u'  {0} read-only cell{1} {2}.'.format(
                read_only, '' if read_only == 1 else 's', verb)
        if refused:
            out += u'  {0} refused \u2014 {1}{2}.'.format(
                refused, self.last_refusal,
                u' (and others)' if refused > 1 else u'')
        return out

    def end_batch(self):
        if self._batch:
            self.undo_stack.append(self._batch)
            del self.redo_stack[:]
        self._batch = None
        self.update_pending()
        self.repaint_soon()
        self.note_stale()

    def note_stale(self):
        """Say when edits have left rows out of the filter or out of order.

        Both are deliberate — a row must not move or vanish while it is being
        typed into — but silence would make them look like bugs.
        """
        parts = []
        if self.active_clause:
            n = self.stale_rows()
            if n:
                parts.append('{0} row{1} no longer match{2} the filter'.format(
                    n, '' if n == 1 else 's', 'es' if n == 1 else ''))
        n = self.sort_stale()
        if n:
            parts.append('{0} row{1} {2} out of sort order'.format(
                n, '' if n == 1 else 's', 'is' if n == 1 else 'are'))
        if not parts:
            return
        self.set_status(u'{0} — left in place so they can be edited. F5 to '
                        'reapply.'.format(', and '.join(parts)))

    def stage(self, ridx, fidx, text):
        model = self.model
        try:
            row = model.rows[ridx]
        except Exception:
            return False
        cell = row.cells[fidx]
        if not cell.editable:
            return False
        if fidx in model.workset_fields:
            # only a workset that exists, spelled the way the model spells it
            found = workset_named(model.worksets, text)
            if found is None:
                typed = to_text(text).strip()
                self.last_refusal = (
                    u'"{0}" is not a workset in this model'.format(typed)
                    if typed else u'a Workset cell cannot be left blank')
                self.refused += 1
                return False
            text = found[0]
        key = model.key_of(row, fidx)
        if key is None:
            return False
        store = model.store_for(key)
        text = to_text(text)
        if self._batch is not None and key not in self._batch:
            self._batch[key] = store.get(key, _ABSENT)
        if text == cell.original:
            store.pop(key, None)
        else:
            store[key] = text
        model.failed.discard(key)
        if not self._importing:
            self.imported.discard((ridx, fidx))
        self.push_to_table(key)
        return True

    def stage_cell(self, pos, col, text):
        fi = self.col_field.get(col)
        if fi is None:
            return False
        try:
            ridx = int(self.dg.Items[pos]['ridx'])
        except Exception:
            return False
        return self.stage(ridx, fi.index, text)

    def push_to_table(self, key):
        """Mirror a staged value into every grid cell that shows it."""
        model = self.model
        if key and key[0] == 'S':
            try:
                row = model.rows[key[1]]
                self.table.Rows[row.ridx][model.fields[key[2]].col] =\
                    model.current_text(row, key[2])
            except Exception:
                pass
            return
        for row, fidx in self.key_index.get(key, []):
            try:
                self.table.Rows[row.ridx][model.fields[fidx].col] = model.current_text(row, fidx)
            except Exception:
                pass

    def repaint_soon(self):
        self._dirty_paint = True
        try:
            self.window.Dispatcher.BeginInvoke(DispatcherPriority.Background, Action(self.repaint))
        except Exception:
            self.repaint()

    def repaint(self):
        """Colour every row that is on screen.

        Only the realised rows are visited.  This used to walk every row in
        the schedule and ask the grid for each one's container — itself a
        search through the realised rows — so a 5,000-row schedule cost tens
        of thousands of calls into .NET per repaint to colour the forty rows
        anyone could see.  The grid already reports which containers exist,
        through LoadingRow and UnloadingRow, so that set is kept instead.
        """
        self._dirty_paint = False
        rows = list(self.live_rows)
        if not rows:
            self.repaint_scan()
            return
        self._dirty_rows.clear()
        for container in rows:
            if not self.paint_container(container):
                self._dirty_rows.add(container)

    def repaint_dirty(self):
        """Colour only the rows that have just been realised.

        Scrolling recycles a handful of containers for new rows; those come
        through LoadingRow and are the only ones whose colours are stale.  A
        row whose cells are not generated yet stays queued for the next
        layout pass, a few times at most.
        """
        rows = list(self._dirty_rows)
        self._dirty_rows.clear()
        for container in rows:
            if container not in self.live_rows:
                continue
            if self.paint_container(container):
                self._paint_tries.pop(container, None)
                continue
            tries = self._paint_tries.get(container, 0) + 1
            if tries < PAINT_RETRIES:
                self._paint_tries[container] = tries
                self._dirty_rows.add(container)
            else:
                self._paint_tries.pop(container, None)

    def repaint_scan(self):
        """The old full walk, kept only for when no rows have been reported —
        so a grid whose row events never arrived still gets its colours."""
        dg = self.dg
        try:
            items = dg.Items
            count = items.Count
        except Exception:
            return
        for i in range(count):
            try:
                container = dg.ItemContainerGenerator.ContainerFromIndex(i)
            except Exception:
                continue
            if container is not None:
                self.paint_container(container)

    def paint_container(self, container):
        """Colour one realised row.  True when every cell was there to paint."""
        dg = self.dg
        model = self.model
        try:
            item = container.Item
        except Exception:
            return True
        if self.is_header_row(item):
            self.paint_header_row(dg, container, item)
            return True
        if container in self._header_tall:
            # A recycled heading container keeps the height it was given as a
            # heading — a local value survives recycling — so an ordinary row
            # handed this container came out 30px tall partway down a
            # grouped table.  Given back to the row's own sizing.
            self._header_tall.discard(container)
            try:
                container.Height = System.Double.NaN
            except Exception:
                pass
        try:
            ridx = int(item['ridx'])
            row = model.rows[ridx]
        except Exception:
            return True                     # nothing of ours in this row
        complete = True
        for col in dg.Columns:
            try:
                content = col.GetCellContent(container)
                if content is None:
                    complete = False        # not generated yet; try again
                    continue
                cell = cell_of(content)
                if cell is None:
                    continue
                fi = self.col_field.get(col)
                if fi is None:
                    # the row number and id columns; an element waiting for
                    # a new level is flagged here, since the level itself
                    # may not be one of the schedule's columns
                    pending_level = ridx in model.level_edits
                    cell.Tag = brush(C_EDIT_BG if pending_level else C_INDEX_BG)
                    cell.Foreground = brush(C_EDIT_FG if pending_level else C_MUTED)
                    cell.FontWeight = (FontWeights.SemiBold if pending_level
                                       else FontWeights.Normal)
                    cell.ToolTip = ('Level will be set to "{0}" on APPLY'.format(
                        model.level_edits[ridx][1]) if pending_level else None)
                    continue
                ci = row.cells[fi.index]
                key = model.key_of(row, fi.index)
                scratch = getattr(ci, 'scratch', False)
                if key is not None and key in model.failed:
                    bg, fg, bold = C_FAIL_BG, C_FAIL_FG, True
                elif not scratch and key is not None and key in model.edits:
                    if (ridx, fi.index) in self.imported:
                        bg, fg, bold = C_IMP_BG, C_IMP_FG, True
                    else:
                        bg, fg, bold = C_EDIT_BG, C_EDIT_FG, True
                elif scratch:
                    bg, fg, bold = C_TEST_BG, C_TEST_FG, False
                elif (ridx, fi.index) in self.copy_marks:
                    # the clipboard source, until it is pasted or cleared
                    bg, fg, bold = C_COPY_BG, C_COPY_FG, False
                elif not ci.editable:
                    bg, fg, bold = C_RO_BG, C_RO_FG, False
                elif ci.is_type:
                    bg, fg, bold = C_TYPE_BG, C_TYPE_FG, False
                else:
                    bg, fg, bold = C_INST_BG, C_INST_FG, False
                # a highlight sits over the resting states but never hides
                # a staged edit or a refusal
                hl = self.highlight_for(ridx, fi.index)
                if hl is not None and not (key is not None and (
                        key in model.failed or
                        (not scratch and key in model.edits))):
                    hl_bg, hl_fg = highlight_colours(hl[0])
                    if hl[1] in ('fill', 'both'):
                        bg = hl_bg
                    if hl[1] in ('text', 'both'):
                        fg = hl_fg
                        bold = True
                cell.Tag = brush(bg)
                cell.Foreground = brush(fg)
                cell.FontWeight = FontWeights.SemiBold if bold else FontWeights.Normal
                if scratch:
                    cell.ToolTip = (u'Test column — scratch space for formulas, '
                                    'never written to the model')
                elif not ci.editable:
                    cell.ToolTip = ci.reason or 'read only'
                elif ci.is_type:
                    cell.ToolTip = u'Type parameter — changing it changes every element of this type'
                else:
                    cell.ToolTip = None
            except Exception:
                continue
        return complete

    def paint_header_row(self, dg, container, item):
        """A group heading: the whole row in the group's colour, label at left,
        and the open / shut button in the column beside it.

        Purely visual — it holds no element, takes no edit, and every operation
        steps over it.
        """
        number = self.group_index_of_header(item)
        bg, fg = self.group_colour(number)
        shut = number in self.collapsed
        label, count = self.group_labels.get(number, ('', 0))
        try:
            container.Height = 30
            self._header_tall.add(container)
        except Exception:
            pass
        for col in dg.Columns:
            try:
                content = col.GetCellContent(container)
                if content is None:
                    continue
                cell = cell_of(content)
                if cell is None:
                    continue
                cell.Tag = brush(bg)
                cell.Foreground = brush(fg)
                cell.FontWeight = FontWeights.Bold
                cell.ToolTip = ('Click to open this group' if shut
                                else 'Click to close this group')
            except Exception:
                continue

    def write_header_text(self, number):
        """The heading's label and its open / shut button, written into the
        table so the normal binding shows them.

        Not written onto the TextBlock: a local value on a bound property
        sticks to that element, and with recycling turned on the element is
        later reused for a real row, which would leave a group label sitting
        in the middle of the data.
        """
        index = self.group_row.get(number)
        if index is None or not self.field_cols:
            return
        label, count = self.group_labels.get(number, ('', 0))
        shut = number in self.collapsed
        text = u'{0}  {1}'.format(u'\u25B8' if shut else u'\u25BE', label)
        if count:
            text += u'   \u00b7 {0} row{1}'.format(count, '' if count == 1 else 's')
        try:
            row = self.table.Rows[index]
            row[self.col_field[self.field_cols[0]].col] = text
            if len(self.field_cols) > 1:
                row[self.col_field[self.field_cols[1]].col] = (
                    u'[ + ]  Expand' if shut else u'[ \u2212 ]  Collapse')
        except Exception:
            pass

    # -- grid events --------------------------------------------------------

    def on_header_click(self, sender, args):
        try:
            if args.ClickCount == 2:
                self.on_maximise(None, None)
                return
        except Exception:
            pass
        shrunk = self.drawer is not None and (self.drawer.shrunk
                                              or self.drawer.busy)
        if self.vstretch is not None and not shrunk:
            # carrying the parked bar around must not restore the height it
            # had before a vertical stretch — that would blow the drawer open
            # halfway through the drag
            top, height = self.vstretch
            self.vstretch = None
            try:
                self.window.Height = height
            except Exception:
                pass
        try:
            self.window.DragMove()
        except Exception:
            pass

    def on_current_cell_changed(self, sender, args):
        # moving off a cell always ends any edit; belt and braces for the flag
        if not self.text_has_focus():
            self.editing = False

    def on_begin_edit(self, sender, args):
        self.editing = True
        try:
            if self.is_header_row(args.Row.Item):
                args.Cancel = True
                self.editing = False
                return
        except Exception:
            pass
        try:
            fi = self.col_field.get(args.Column)
            ridx = int(args.Row.Item['ridx'])
            if fi is None or not self.model.rows[ridx].cells[fi.index].editable:
                args.Cancel = True
                self.editing = False
                reason = 'this column is read only'
                try:
                    reason = self.model.rows[ridx].cells[fi.index].reason or reason
                except Exception:
                    pass
                self.set_status(u'Not editable — ' + reason)
                return
            if fi.index in self.model.workset_fields:
                # a Workset cell is chosen from a list, not typed into; what
                # was typed, if editing began with a key, seeds its search
                args.Cancel = True
                self.editing = False
                seed = u''
                try:
                    seed = to_text(getattr(args.EditingEventArgs, 'Text', u'') or u'')
                except Exception:
                    seed = u''
                cell = None
                try:
                    cell = walk_up(args.Column.GetCellContent(args.Row),
                                   DataGridCell)
                except Exception:
                    cell = None
                self.open_workset_dropdown_soon(cell, seed)
        except Exception:
            self.editing = False

    def on_cell_edit_ending(self, sender, args):
        self.editing = False
        try:
            if args.EditAction != DataGridEditAction.Commit:
                return
            fi = self.col_field.get(args.Column)
            if fi is None:
                return
            ridx = int(args.Row.Item['ridx'])
            text = args.EditingElement.Text
        except Exception:
            return

        def _commit():
            self.begin_batch()
            ok = self.stage(ridx, fi.index, text)
            self.end_batch()
            if not ok:
                try:
                    self.table.Rows[ridx][fi.col] = self.model.current_text(
                        self.model.rows[ridx], fi.index)
                except Exception:
                    pass
                self.set_status(u'That cell is read only — the value was put back.')
                return
            row = self.model.rows[ridx]
            if row.cells[fi.index].is_type:
                n = len(self.key_index.get(self.model.key_of(row, fi.index), []))
                if n > 1:
                    self.set_status(u'Type parameter — {0} scheduled rows share this value.'.format(n))
        try:
            self.window.Dispatcher.BeginInvoke(DispatcherPriority.Background, Action(_commit))
        except Exception:
            _commit()

    def on_selection_changed(self, sender, args):
        """Queue one refresh for a whole burst of selection changes.

        The grid raises this once per cell added or removed, and a drag
        rebuilds its rectangle cell by cell — so selecting 2,000 cells raised
        it 2,000 times, and each one used to rebuild the entire selection
        twice over.  That made a drag quadratic in the size of what was being
        dragged over.  Now every event in a burst just marks the selection
        stale, and the work runs once, after the burst, when the dispatcher
        next comes up for air.
        """
        self._last_sel = _STALE
        if self._sel_pending:
            return
        self._sel_pending = True
        try:
            self.window.Dispatcher.BeginInvoke(DispatcherPriority.Background,
                                               Action(self.after_selection))
        except Exception:
            self.after_selection()

    def hint_workset(self):
        """Say, the first few times, that a Workset cell has a list behind it —
        nothing else on screen does."""
        if self._ws_hints >= 3 or not self.model.workset_fields:
            return
        try:
            # one cell only: a paste or fill that leaves a selection behind
            # has its own message, which this must not write over
            if self.dg.SelectedCells.Count != 1:
                return
            if not self.workset_col(self.dg.CurrentCell.Column):
                return
        except Exception:
            return
        self._ws_hints += 1
        self.set_status(u'Workset \u2014 click the cell again, or press F2, to '
                        u'choose from the worksets. Select several rows first '
                        u'to set them all at once.')

    def any_field_selected(self):
        """Is any selected cell one a command can act on?  Usually answered by
        the first cell; the row number and id columns do not count."""
        for info in self.dg.SelectedCells:
            try:
                if self.col_field.get(info.Column) is not None:
                    return True
            except Exception:
                continue
        return False

    def after_selection(self):
        self._sel_pending = False
        self.hint_workset()
        try:
            self.btn_revert_sel.IsEnabled = self.any_field_selected()
        except Exception:
            pass
        # with the formula bar open and not picking references, the cells the
        # result goes into follow the selection, so they can be chosen after
        # the bar is opened rather than only before
        try:
            if self.formula_open() and not self.formula_pick:
                self.formula_cells = self.editable_selection()
                self.paint_formula()
        except Exception:
            pass
        self.place_handle()

    def on_loading_row(self, sender, args):
        """A container has been prepared for a row — new, or recycled from
        one that scrolled away — so its colours belong to the old row."""
        try:
            container = args.Row
            self.live_rows.add(container)
            self._dirty_rows.add(container)
        except Exception:
            self._dirty_paint = True

    def on_unloading_row(self, sender, args):
        try:
            container = args.Row
            self.live_rows.discard(container)
            self._dirty_rows.discard(container)
            self._paint_tries.pop(container, None)
        except Exception:
            pass

    def on_scroll(self, sender, args):
        # No repaint here.  Vertical scrolling hands recycled containers to
        # new rows, and every one of them comes through LoadingRow; column
        # virtualisation is off, so a sideways scroll realises nothing new.
        self.place_handle()

    def on_layout_updated(self, sender, args):
        # raised for every layout pass anywhere in the window, so the common
        # case — nothing to do — has to cost two attribute reads and no more
        if self._dirty_paint:
            self.repaint()
        elif self._dirty_rows:
            self.repaint_dirty()

    def text_has_focus(self):
        """True when a text box owns the keyboard.

        Windows shortcuts belong to whatever has focus: inside the search box or
        a cell editor, Ctrl+C, Ctrl+V, Delete and Backspace are the text box's,
        not the grid's.  Stealing them there is how Backspace in the search box
        ended up wiping selected cells.
        """
        try:
            focused = Keyboard.FocusedElement
        except Exception:
            return False
        try:
            return isinstance(focused, TextBox)
        except Exception:
            return False

    def is_editing(self):
        """Edit state read from the grid, not only from our own flag.

        The flag alone could stick True if BeginningEdit threw, and every
        shortcut in the window would go dead until the tool was restarted.
        """
        if self.text_has_focus():
            return True
        return bool(self.editing)

    def focus_grid(self):
        try:
            self.dg.Focus()
        except Exception:
            pass

    def on_key(self, sender, args):
        ctrl = (Keyboard.Modifiers & ModifierKeys.Control) == ModifierKeys.Control
        shift = (Keyboard.Modifiers & ModifierKeys.Shift) == ModifierKeys.Shift
        key = args.Key
        if ctrl and shift and key == Key.H:
            args.Handled = True
            if self.drawer is not None:
                self.drawer.toggle()
            return
        if self.drawer is not None and self.drawer.shrunk:
            # while it is parked the only keys that can mean anything are the
            # two that bring it back; Escape must not reach the close prompt
            if key == Key.Escape or key == Key.Enter or key == Key.F11:
                args.Handled = True
                self.drawer.expand()
            return
        if key == Key.F11:
            args.Handled = True
            self.on_maximise(None, None)
            return
        if key == Key.F5:
            args.Handled = True
            self.on_reapply_filters()
            return

        in_text = self.text_has_focus()
        if key == Key.Escape and self._filling:
            args.Handled = True
            self.cancel_fill()
            self.set_status('Fill cancelled.')
            return
        if key == Key.Escape and self.copy_marks and not in_text:
            args.Handled = True
            self.clear_copy_marks()
            self.set_status('Copy cleared.')
            return
        if key == Key.Escape:
            if self.editing or in_text:
                # leave the editor or the filter box, not the tool
                if in_text and not self.editing:
                    args.Handled = True
                    try:
                        focused = Keyboard.FocusedElement
                        for box in self.header_boxes.values():
                            if box is focused and (box.Text or ''):
                                box.Text = ''
                                break
                    except Exception:
                        pass
                    self.focus_grid()
                return
            args.Handled = True
            self.window.Close()
            return

        if self.is_editing():
            # a text box has the keyboard: let Windows do its own thing, and
            # only keep the shortcuts that cannot mean anything to a text box
            if ctrl and shift and key == Key.T:
                args.Handled = True
                self.on_theme(None, None)
            elif ctrl and key == Key.S:
                args.Handled = True
                self.on_apply(None, None)
            return

        if key == Key.F2:
            args.Handled = True
            self.begin_edit_current()
        elif ctrl and key == Key.X:
            args.Handled = True
            self.on_cut(None, None)
        elif ctrl and key == Key.C:
            args.Handled = True
            self.on_copy(None, None)
        elif ctrl and key == Key.V:
            args.Handled = True
            self.on_paste(None, None)
        elif ctrl and key == Key.D:
            args.Handled = True
            self.on_fill_down(None, None)
        elif ctrl and shift and key == Key.E:
            args.Handled = True
            self.on_export(None, None)
        elif ctrl and shift and key == Key.I:
            args.Handled = True
            self.on_import(None, None)
        elif ctrl and key == Key.E:
            args.Handled = True
            self.on_fill_series(None, None)
        elif ctrl and shift and key == Key.F:
            args.Handled = True
            self.on_formula(None, None)
        elif ctrl and shift and key == Key.N:
            args.Handled = True
            self.on_sequence(None, None)
        elif ctrl and shift and key == Key.P:
            args.Handled = True
            self.on_affix(None, None)
        elif ctrl and shift and key == Key.H:
            args.Handled = True
            self.on_highlight(None, None)
        elif ctrl and shift and key == Key.T:
            args.Handled = True
            self.on_theme(None, None)
        elif ctrl and (key == Key.H or key == Key.F):
            args.Handled = True
            self.on_find(None, None)
        elif ctrl and (key == Key.Y or (shift and key == Key.Z)):
            args.Handled = True
            self.on_redo(None, None)
        elif ctrl and key == Key.Z:
            args.Handled = True
            self.on_undo(None, None)
        elif ctrl and key == Key.S:
            args.Handled = True
            self.on_apply(None, None)
        elif key == Key.Delete or key == Key.Back:
            args.Handled = True
            self.on_clear(None, None)

    # -- clipboard ----------------------------------------------------------

    def on_copy(self, sender, args):
        cells = self.sel_cells()
        if not cells:
            self.set_status('Nothing selected to copy.')
            return
        grid = {}
        cols = []
        rows = []
        for c in cells:
            grid[(c['pos'], c['col'].DisplayIndex)] = self.text_at(c['pos'], c['col']) or ''
            if c['col'].DisplayIndex not in cols:
                cols.append(c['col'].DisplayIndex)
            if c['pos'] not in rows:
                rows.append(c['pos'])
        cols.sort()
        rows.sort()
        lines = []
        for r in rows:
            lines.append('\t'.join([grid.get((r, cc), '') for cc in cols]))
        try:
            Clipboard.SetText('\r\n'.join(lines))
        except Exception:
            self.set_status('Could not reach the clipboard.')
            return
        self.set_copy_marks(cells)
        self.set_status(u'Copied {0} row{1} x {2} column{3} — select where it goes '
                        'and press Ctrl+V. Escape clears it.'.format(
                            len(rows), '' if len(rows) == 1 else 's',
                            len(cols), '' if len(cols) == 1 else 's'))

    def set_copy_marks(self, cells):
        """Show which cells the clipboard came from, the way Excel does.

        Kept as (row, field) rather than a screen position so the marks follow
        the data through a filter or a sort instead of pointing at whatever
        happens to be in that spot afterwards.
        """
        self.copy_marks = set([(c['ridx'], c['fidx']) for c in cells])
        self.repaint_soon()

    def clear_copy_marks(self):
        if not self.copy_marks:
            return
        self.copy_marks = set()
        self.repaint_soon()

    def on_cut(self, sender, args):
        """Copy, then empty whatever of the selection can be emptied."""
        cells = self.sel_cells()
        if not cells:
            self.set_status('Nothing selected to cut.')
            return
        self.on_copy(None, None)
        self.begin_batch()
        n = 0
        for c in cells:
            if self.stage_cell(c['pos'], c['col'], ''):
                n += 1
        self.end_batch()
        self.clear_copy_marks()
        skipped = len(cells) - n
        msg = 'Cut {0} cell{1}.'.format(n, '' if n == 1 else 's')
        if skipped:
            msg += self.skipped_note(skipped, 'copied but left alone')
        self.set_status(msg)

    def begin_edit_current(self):
        try:
            self.dg.BeginEdit()
        except Exception:
            pass

    def on_right_click(self, sender, args):
        """Right-click selects the cell under the pointer unless it is already
        part of the selection — the Windows convention, and without it the menu
        would act on whatever was selected before."""
        try:
            hit = self.dg.InputHitTest(args.GetPosition(self.dg))
            cell = walk_up(hit, DataGridCell)
            if cell is None:
                # a heading: whichever menu opens should act on this column,
                # not on the last cell that was right-clicked
                header = walk_up(hit, DataGridColumnHeader)
                if header is not None:
                    self._menu_col = self.col_field.get(header.Column)
                return
            self._menu_col = self.col_field.get(cell.Column)
            for info in self.dg.SelectedCells:
                try:
                    if info.Column is cell.Column and info.Item is cell.DataContext:
                        return
                except Exception:
                    continue
            self.dg.SelectedCells.Clear()
            self.dg.SelectedCells.Add(DataGridCellInfo(cell.DataContext, cell.Column))
            self.dg.CurrentCell = DataGridCellInfo(cell.DataContext, cell.Column)
        except Exception:
            pass

    def build_context_menu(self):
        """The right-click menu — the other half of what people expect from
        Windows, and the discoverable route to the same commands."""
        menu = ContextMenu()
        items = (
            ('Cut', 'Ctrl+X', self.on_cut),
            ('Copy', 'Ctrl+C', self.on_copy),
            ('Paste', 'Ctrl+V', self.on_paste),
            ('Clear', 'Delete', self.on_clear),
            (None, None, None),
            ('Set Workset...', 'F2', self.on_set_workset),
            (None, None, None),
            ('Fill Down', 'Ctrl+D', self.on_fill_down),
            ('Fill Series', 'Ctrl+E', self.on_fill_series),
            (None, None, None),
            ('Undo', 'Ctrl+Z', self.on_undo),
            ('Redo', 'Ctrl+Y', self.on_redo),
            (None, None, None),
            ('Formula...', 'Ctrl+Shift+F', self.on_formula),
            ('Number Sequence...', 'Ctrl+Shift+N', self.on_sequence),
            ('Add Prefix / Suffix...', 'Ctrl+Shift+P', self.on_affix),
            ('Highlight...', 'Ctrl+Shift+H', self.on_highlight),
            ('Create Unique Sequence', None, self.on_unique_sequence),
            (None, None, None),
            ('Find and Replace...', 'Ctrl+H', self.on_find),
            ('Reapply filters', 'F5', self.on_reapply_filters),
            ('Clear all filters', None, self.on_clear_filters),
            ('Auto-fit columns', None, self.on_autofit),
            ('Revert Selected Cells', None, self.on_revert_selected),
            (None, None, None),
            ('Keep Revit usable while this is open...', None, self.on_toggle_modeless),
        )
        # the column's own duplicate commands lead the menu
        self.duplicate_items(menu, lambda: self._menu_col)
        menu.Items.Add(Separator())
        for label, gesture, handler in items:
            if label is None:
                menu.Items.Add(Separator())
                continue
            item = MenuItem()
            item.Header = label
            if gesture:
                item.InputGestureText = gesture
            try:
                item.Click += handler
            except Exception:
                pass
            menu.Items.Add(item)
        try:
            self.dg.ContextMenu = menu
        except Exception:
            pass
        return menu

    def on_paste(self, sender, args):
        try:
            raw = Clipboard.GetText()
        except Exception:
            raw = None
        if not raw:
            self.set_status('The clipboard is empty.')
            return
        cells = self.sel_cells()
        if not cells:
            self.set_status('Select a cell to paste into.')
            return
        block = [ln.split('\t') for ln in raw.replace('\r\n', '\n').replace('\r', '\n').split('\n')]
        while block and len(block[-1]) == 1 and block[-1][0] == '':
            block.pop()
        if not block:
            return

        cols_sorted = self.ordered_field_columns()
        anchor_pos = cells[0]['pos']
        anchor_disp = cells[0]['col'].DisplayIndex

        self.begin_batch()
        written = 0
        skipped = 0
        if len(block) == 1 and len(block[0]) == 1 and len(cells) > 1:
            # single value into every selected cell
            for c in cells:
                if self.stage_cell(c['pos'], c['col'], block[0][0]):
                    written += 1
                else:
                    skipped += 1
        else:
            targets = self.data_positions(anchor_pos, True, len(block))
            for dr, line in enumerate(block):
                if dr >= len(targets):
                    break
                pos = targets[dr]
                for dc, value in enumerate(line):
                    col = None
                    for cc in cols_sorted:
                        if cc.DisplayIndex == anchor_disp + dc:
                            col = cc
                            break
                    if col is None:
                        continue
                    if self.stage_cell(pos, col, value):
                        written += 1
                    else:
                        skipped += 1
        self.end_batch()
        self.clear_copy_marks()
        msg = 'Pasted {0} cell{1}.'.format(written, '' if written == 1 else 's')
        if skipped:
            msg += self.skipped_note(skipped)
        self.set_status(msg)

    def on_clear(self, sender, args):
        cells = self.sel_cells()
        if not cells:
            return
        self.begin_batch()
        n = 0
        for c in cells:
            if self.stage_cell(c['pos'], c['col'], ''):
                n += 1
        self.end_batch()
        self.set_status('Cleared {0} cell{1}.'.format(n, '' if n == 1 else 's'))

    # -- fill ---------------------------------------------------------------

    def _fill(self, sequence):
        cells = self.sel_cells()
        if len(cells) < 2:
            self.set_status('Select the seed cell and the cells to fill.')
            return
        by_col = {}
        for c in cells:
            by_col.setdefault(c['col'].DisplayIndex, []).append(c)
        self.begin_batch()
        n = 0
        for disp in sorted(by_col.keys()):
            group = sorted(by_col[disp], key=lambda d: d['pos'])
            col = group[0]['col']
            seed = self.text_at(group[0]['pos'], col) or ''
            step = 1
            # a series of workset names would count its way into other,
            # real worksets and stage them without a word
            sequence = sequence and not self.workset_col(col)
            if sequence and len(group) > 1:
                a = split_number(seed)
                b = split_number(self.text_at(group[1]['pos'], col) or '')
                if a and b and (int(b[1]) - int(a[1])) != 0:
                    step = int(b[1]) - int(a[1])
            for i, c in enumerate(group[1:]):
                value = series_value(seed, step, i + 1) if sequence else seed
                if self.stage_cell(c['pos'], col, value):
                    n += 1
        self.end_batch()
        self.set_status('{0} {1} cell{2}.'.format(
            'Sequenced' if sequence else 'Filled', n, '' if n == 1 else 's'))

    def on_fill_down(self, sender, args):
        self._fill(False)

    def on_fill_series(self, sender, args):
        self._fill(True)

    # -- drag fill handle ---------------------------------------------------

    def cell_rect(self, pos, col):
        try:
            container = self.dg.ItemContainerGenerator.ContainerFromIndex(pos)
            if container is None:
                return None
            content = col.GetCellContent(container)
            if content is None:
                return None
            cell = cell_of(content)
            if cell is None:
                return None
            origin = cell.TransformToAncestor(self.grid_host).Transform(Point(0, 0))
            return (origin.X, origin.Y, cell.ActualWidth, cell.ActualHeight)
        except Exception:
            return None

    def last_selected(self):
        """The bottom-right selected cell as (position, column), or None.

        The fill handle only ever needs this one cell, but used to build and
        sort the entire selection to find it — on every scroll tick.  It is
        found in a single pass and kept until the selection or the row order
        changes, so scrolling past a large selection costs nothing.
        """
        if self._last_sel is not _STALE:
            return self._last_sel
        best = None
        try:
            pmap = self.pos_map()
            for info in self.dg.SelectedCells:
                try:
                    col = info.Column
                    if self.col_field.get(col) is None:
                        continue
                    pos = pmap.get(int(info.Item['ridx']), -1)
                    if pos < 0:
                        continue
                    rank = (pos, col.DisplayIndex)
                except Exception:
                    continue
                if best is None or rank > best[0]:
                    best = (rank, col)
        except Exception:
            best = None
        self._last_sel = None if best is None else (best[0][0], best[1])
        return self._last_sel

    def place_handle(self):
        try:
            last = self.last_selected()
            if last is None:
                self.handle.Visibility = Visibility.Collapsed
                return
            rect = self.cell_rect(last[0], last[1])
            if rect is None:
                self.handle.Visibility = Visibility.Collapsed
                return
            Canvas.SetLeft(self.handle, rect[0] + rect[2] - 5)
            Canvas.SetTop(self.handle, rect[1] + rect[3] - 5)
            self.handle.Visibility = Visibility.Visible
        except Exception:
            try:
                self.handle.Visibility = Visibility.Collapsed
            except Exception:
                pass

    def row_area(self):
        """(top, bottom) of the scrollable row area, in grid_host coordinates.

        The overshoot has to be measured against **the viewport**, not against
        the rows. A virtualising panel keeps rows realised a little beyond the
        visible area, so measuring against the last realised row meant dragging
        to the bottom of the window still landed *inside* a row, reported no
        overshoot, and never scrolled — which is why the auto-scroll appeared
        to do nothing at all.
        """
        top = 0.0
        try:
            top = float(self.dg.ColumnHeaderHeight)
        except Exception:
            top = 0.0
        if top <= 0:
            top = 56.0
        bottom = top + 100.0
        try:
            bottom = float(self.grid_host.ActualHeight)
        except Exception:
            pass
        if bottom <= top:
            bottom = top + 100.0
        return top, bottom

    def row_at_y(self, y, col=None, point=None):
        """(row index under the pointer, pixels past the edge of the viewport).

        Inside the grid the row comes from a hit test, which is cheap and
        exact. Outside it there is no row to find, so the overshoot is what
        matters and the timer walks the target along instead.
        """
        top, bottom = self.row_area()
        if y < top + EDGE_INSET:
            return None, y - (top + EDGE_INSET)          # negative: above
        if y > bottom - EDGE_INSET:
            return None, y - (bottom - EDGE_INSET)       # positive: below
        return self.row_under(y, col, point), 0.0

    def row_under(self, y, col=None, point=None):
        """The row at this position inside the grid, or None."""
        if point is not None:
            try:
                hit = self.dg.InputHitTest(point)
                row = walk_up(hit, DataGridRow)
                if row is not None:
                    index = self.dg.ItemContainerGenerator.IndexFromContainer(row)
                    if index >= 0:
                        return index
            except Exception:
                pass
        # fall back to measuring, for the gaps a hit test lands in.  Only a
        # realised row can be under the pointer, so only those are measured —
        # walking from the top of the schedule meant thousands of lookups for
        # a gridline-thin miss once the grid was scrolled a long way down.
        for container in list(self.live_rows):
            try:
                origin = container.TransformToAncestor(self.grid_host).Transform(
                    Point(0, 0))
                if origin.Y <= y < origin.Y + container.ActualHeight:
                    index = self.dg.ItemContainerGenerator.IndexFromContainer(
                        container)
                    if index >= 0:
                        return index
            except Exception:
                continue                      # detached while being recycled
        if self.live_rows:
            return None
        col = col or self._fill_col
        if col is None:
            try:
                col = self.dg.Columns[0]
            except Exception:
                return None
        try:
            count = self.dg.Items.Count
        except Exception:
            return None
        for i in range(count):
            rect = self.cell_rect(i, col)
            if rect is None:
                continue                      # not realised: virtualised away
            if rect[1] <= y < rect[1] + rect[3]:
                return i
            if rect[1] > y:
                break                         # rows are in order: stop early
        return None

    # -- drag auto-scroll ---------------------------------------------------

    def start_drag_scroll(self, mode):
        """One timer serves both drags: the fill handle and a selection drag."""
        self._drag_mode = mode
        self._scroll_over = 0.0
        self._scroll_over_x = 0.0
        self._scroll_accum = 0.0
        self._scroll_accum_x = 0.0
        if self._scroll_timer is None:
            self._scroll_timer = DispatcherTimer()
            self._scroll_timer.Interval = TimeSpan.FromMilliseconds(SCROLL_TICK_MS)
            self._scroll_timer.Tick += self.on_drag_scroll
        self._scroll_timer.Start()

    def stop_drag_scroll(self):
        self._drag_mode = None
        self._scroll_over = 0.0
        self._scroll_over_x = 0.0
        self._scroll_accum = 0.0
        self._scroll_accum_x = 0.0
        try:
            if self._scroll_timer is not None:
                self._scroll_timer.Stop()
        except Exception:
            pass

    def on_drag_scroll(self, sender, args):
        """Advance by however many whole rows this tick has earned.

        The fraction is carried over, so a rate below one row per tick still
        scrolls instead of rounding to nothing.
        """
        if not self._drag_mode:
            return
        try:
            if Mouse.LeftButton != MouseButtonState.Pressed:
                # released off the window, or over something that swallowed the
                # event: a timer left running would scroll forever
                if self._drag_mode == 'select':
                    self.stop_drag_scroll()
                    return
        except Exception:
            pass
        self.scroll_sideways()
        rate = scroll_rate(self._scroll_over)
        if rate <= 0:
            self._scroll_accum = 0.0
            return
        self._scroll_accum += rate * (SCROLL_TICK_MS / 1000.0)
        steps = int(self._scroll_accum)
        if steps < 1:
            return
        self._scroll_accum -= steps
        if self._scroll_over < 0:
            steps = -steps
        try:
            count = self.dg.Items.Count
        except Exception:
            return
        if self._drag_mode == 'fill':
            target = max(0, min(count - 1, self._fill_target + steps))
            if target == self._fill_target:
                return
            self._fill_target = target
            self.scroll_row_into_view(target, self._fill_col)
            self.draw_fill_preview()
        else:
            target = max(0, min(count - 1, self._sel_pos + steps))
            self._sel_pos = target
            col = self._sel_cur_col or self._sel_col
            self.scroll_row_into_view(target, col)
            self.extend_selection(target, col)

    def column_overshoot(self, x):
        """Pixels past the left or right edge of the grid."""
        try:
            width = float(self.grid_host.ActualWidth)
        except Exception:
            return 0.0
        if x < EDGE_INSET:
            return x - EDGE_INSET
        if x > width - EDGE_INSET:
            return x - (width - EDGE_INSET)
        return 0.0

    def step_column(self, steps):
        """Walk the current column sideways, for a drag past the side edge."""
        cols = self.ordered_field_columns()
        if not cols:
            return None
        current = self._sel_cur_col or self._sel_col
        try:
            i = cols.index(current)
        except Exception:
            i = 0
        i = max(0, min(len(cols) - 1, i + steps))
        self._sel_cur_col = cols[i]
        return cols[i]

    def scroll_sideways(self):
        """Columns step more slowly than rows — they are much wider."""
        if self._drag_mode != 'select' or not self._scroll_over_x:
            self._scroll_accum_x = 0.0
            return
        rate = scroll_rate(self._scroll_over_x) / 6.0
        if rate <= 0:
            return
        self._scroll_accum_x += rate * (SCROLL_TICK_MS / 1000.0)
        steps = int(self._scroll_accum_x)
        if steps < 1:
            return
        self._scroll_accum_x -= steps
        if self._scroll_over_x < 0:
            steps = -steps
        col = self.step_column(steps)
        if col is not None:
            self.scroll_row_into_view(self._sel_pos, col)
            self.extend_selection(self._sel_pos, col)

    def scroll_row_into_view(self, pos, col):
        try:
            item = self.dg.Items[pos]
            if col is not None:
                self.dg.ScrollIntoView(item, col)
            else:
                self.dg.ScrollIntoView(item)
        except Exception:
            pass

    # -- selection drag -----------------------------------------------------

    def on_grid_mouse_down(self, sender, args):
        """Remember where a drag-select started, and arm the scroller.

        WPF handles the drag itself perfectly well while the pointer is inside
        the grid; it is only past the edge that it stops, so the timer does
        nothing until the overshoot is non-zero.
        """
        if self._filling:
            return
        try:
            if args.ClickCount == 2:
                # the second click of a double-click belongs to the DataGrid:
                # it is what starts a cell edit, and arming the drag scroller
                # here is what stopped edits beginning at all — except in a
                # Workset column, where the first click has already opened the
                # list; handing this one to the grid would collapse the
                # selection and open the list a second time
                self.double_click_workset(args)
                return
        except Exception:
            pass
        try:
            self._down_at = args.GetPosition(self.dg)
        except Exception:
            self._down_at = None
        try:
            hit = self.dg.InputHitTest(args.GetPosition(self.dg))
            cell = walk_up(hit, DataGridCell)
            if cell is None:
                return
            if (self.formula_open() and self.formula_pick
                    and not self.is_header_row(cell.DataContext)):
                fi = self.col_field.get(cell.Column)
                if fi is not None:
                    for i in range(self.dg.Items.Count):
                        if self.dg.Items[i] is cell.DataContext:
                            ridx = int(self.dg.Items[i]['ridx'])
                            if self.insert_reference(ridx, fi):
                                args.Handled = True
                            return
            if self.is_header_row(cell.DataContext):
                # the whole heading is the button, so it is hard to miss
                args.Handled = True
                number = self.group_index_of_header(cell.DataContext)
                opened = self.toggle_group(number)
                label = self.group_labels.get(number, ('', 0))[0]
                self.show_expand_state()
                self.set_status(u'{0} {1}.'.format(
                    'Opened' if opened else 'Closed', label))
                return
            col = cell.Column
            if self.col_field.get(col) is None:
                return
            if self.workset_col(col) and self.dg.SelectedCells.Count > 1:
                plain = True
                try:
                    # int(): a .NET enum never equals a Python int under
                    # IronPython, so comparing the flags with 0 was always
                    # False and this whole branch was dead
                    plain = int(Keyboard.Modifiers & (ModifierKeys.Control |
                                                      ModifierKeys.Shift)) == 0
                except Exception:
                    plain = True
                if plain and self.cell_selected(cell):
                    # Clicking inside a selection would collapse it to one
                    # cell.  In the Workset column that click means "set all
                    # of these", so the selection is kept and the list opens.
                    args.Handled = True
                    self.open_workset_dropdown_soon(cell)
                    return
            try:
                pos = self.dg.Items.IndexOf(cell.DataContext)
            except Exception:
                pos = -1
                for i in range(self.dg.Items.Count):
                    if self.dg.Items[i] is cell.DataContext:
                        pos = i
                        break
            if pos < 0:
                return
            self._sel_anchor = pos
            self._sel_rect = None        # a new drag draws its own rectangle
            self._sel_pos = pos
            self._sel_col = col
            self._sel_cur_col = col
        except Exception:
            return
        self.start_drag_scroll('select')

    def on_grid_mouse_move(self, sender, args):
        if self._filling or self._drag_mode != 'select':
            return
        try:
            if args.LeftButton != MouseButtonState.Pressed:
                self.stop_drag_scroll()
                return
        except Exception:
            return
        try:
            p = args.GetPosition(self.grid_host)
            point = args.GetPosition(self.dg)
        except Exception:
            return
        # nothing counts as a drag until the pointer has actually travelled:
        # rebuilding the selection on the tiny movement between the two clicks
        # of a double-click takes the cell out from under the edit
        if not self.past_drag_threshold(point):
            return
        pos, over = self.row_at_y(p.Y, self._sel_col, point)
        self._scroll_over = over
        self._scroll_over_x = self.column_overshoot(p.X)
        try:
            # the column under the pointer first, so the rectangle drawn on
            # this move reaches it rather than catching up on the next; and on
            # every move, since the auto-scroll at the edges reads it too
            cell = walk_up(self.dg.InputHitTest(point), DataGridCell)
            if cell is not None and self.col_field.get(cell.Column) is not None:
                self._sel_cur_col = cell.Column
        except Exception:
            pass
        if pos is not None:
            self._sel_pos = pos
            adding = False
            try:
                adding = (Keyboard.Modifiers & ModifierKeys.Control) ==\
                    ModifierKeys.Control
            except Exception:
                adding = False
            if not adding:
                self.extend_selection(pos, self._sel_cur_col or self._sel_col)

    def past_drag_threshold(self, point):
        """Has the pointer moved far enough since the button went down?"""
        if self._down_at is None:
            return True
        try:
            dx = abs(point.X - self._down_at.X)
            dy = abs(point.Y - self._down_at.Y)
            wide = SystemParameters.MinimumHorizontalDragDistance
            tall = SystemParameters.MinimumVerticalDragDistance
        except Exception:
            return True
        return dx >= wide or dy >= tall

    def on_grid_mouse_up(self, sender, args):
        if self._drag_mode == 'select':
            self.stop_drag_scroll()

    def extend_selection(self, pos, col):
        """Anchor to here, as a rectangle across the columns dragged over."""
        if self._sel_anchor is None or col is None:
            return
        try:
            cols = self.ordered_field_columns()
            anchor_col = self._sel_col or col
            a = cols.index(anchor_col) if anchor_col in cols else 0
            b = cols.index(col) if col in cols else a
            lo_c, hi_c = min(a, b), max(a, b)
            lo_r, hi_r = min(self._sel_anchor, pos), max(self._sel_anchor, pos)
            rect = (lo_r, hi_r, lo_c, hi_c)
            if (self._sel_rect is not None and self._sel_rect[0] == rect and
                    self.dg.SelectedCells.Count == self._sel_rect[1]):
                # Most mouse moves stay inside the cell they started in, and
                # rebuilding an identical rectangle on each one was the other
                # half of what made a drag-select drag.  Skipped only while
                # the grid still holds exactly what was drawn: WPF runs its
                # own drag selection inside the grid too, and when it has
                # added the row number or id cells the count gives it away.
                return
            self._sel_rect = None
            self.dg.SelectedCells.Clear()
            added = 0
            for r in range(lo_r, hi_r + 1):
                item = self.dg.Items[r]
                if self.is_header_row(item):
                    continue
                for ci in range(lo_c, hi_c + 1):
                    self.dg.SelectedCells.Add(DataGridCellInfo(item, cols[ci]))
                    added += 1
            # recorded only once the whole rectangle is in, so a failure
            # halfway cannot be mistaken for a finished selection next time
            self._sel_rect = (rect, added)
            self.dg.CurrentCell = DataGridCellInfo(self.dg.Items[pos], col)
        except Exception:
            pass

    def group_end(self, pos):
        """The last data row of the block `pos` sits in.

        With grouping on that is the row before the next heading; with it off
        there are no headings, so it is the last row on the list. Either way it
        is where a double-click fill should stop.
        """
        last = pos
        try:
            total = self.dg.Items.Count
        except Exception:
            return last
        p = pos + 1
        while p < total:
            if self.is_header_pos(p):
                break
            last = p
            p += 1
        return last

    def fill_to_group_end(self):
        """Excel's double-click autofill, stopped at the group heading."""
        src = self.sel_cells()
        if not src:
            self.set_status('Select the cell to fill from first.')
            return
        by_col = {}
        for c in src:
            by_col.setdefault(c['col'].DisplayIndex, []).append(c)

        self.begin_batch()
        written = 0
        skipped = 0
        reached = None
        for disp in sorted(by_col.keys()):
            group = sorted(by_col[disp], key=lambda d: d['pos'])
            col = group[0]['col']
            bottom = group[-1]['pos']
            target = self.group_end(bottom)
            if target <= bottom:
                continue
            dest = [p for p in range(bottom + 1, target + 1)
                    if not self.is_header_pos(p)]
            seeds = [self.text_at(c['pos'], col) or '' for c in group]
            values = self.fill_values(col, seeds, len(dest), True)
            for pos, value in zip(dest, values):
                if self.stage_cell(pos, col, value):
                    written += 1
                else:
                    skipped += 1
            reached = target
        self.end_batch()

        if not written and not skipped:
            self.set_status(u'Nothing below to fill — already at the end of the '
                            'group.' if self.grouping else 'Nothing below to fill.')
            return
        msg = 'Filled {0} cell{1} down to the '.format(
            written, '' if written == 1 else 's')
        msg += 'end of the group.' if self.grouping else 'end of the list.'
        if skipped:
            msg += self.skipped_note(skipped)
        self.set_status(msg)
        if reached is not None:
            self.scroll_row_into_view(reached, src[-1]['col'])

    def on_handle_down(self, sender, args):
        cells = self.sel_cells()
        if not cells:
            return
        try:
            double = args.ClickCount == 2
        except Exception:
            double = False
        if double:
            # a double-click fills rather than drags, so no capture and no timer
            args.Handled = True
            self.fill_to_group_end()
            return
        self._filling = True
        self._fill_src = cells
        self._fill_col = cells[0]['col']
        self._fill_target = cells[-1]['pos']
        try:
            self.handle.CaptureMouse()
        except Exception:
            pass
        self.start_drag_scroll('fill')
        args.Handled = True

    def on_handle_move(self, sender, args):
        if not self._filling:
            return
        try:
            y = args.GetPosition(self.grid_host).Y
            point = args.GetPosition(self.dg)
        except Exception:
            return
        pos, over = self.row_at_y(y, self._fill_col, point)
        self._scroll_over = over
        if pos is not None and not self.is_header_pos(pos):
            self._fill_target = pos
        self.draw_fill_preview()

    def draw_fill_preview(self):
        """The orange outline over everything the drop would write."""
        try:
            src = self._fill_src or []
            if not src:
                return
            target = self._fill_target
            first = src[0]
            last = src[-1]
            top_pos = min(first['pos'], target)
            bottom_pos = max(last['pos'], target)
            top = self.cell_rect(top_pos, first['col'])
            bottom = self.cell_rect(bottom_pos, last['col'])
            if top is None or bottom is None:
                # the far end is scrolled out of view: clamp to what is drawn
                top = top or self.cell_rect(first['pos'], first['col'])
                bottom = bottom or self.cell_rect(last['pos'], last['col'])
                if top is None or bottom is None:
                    return
            Canvas.SetLeft(self.preview, top[0])
            Canvas.SetTop(self.preview, top[1])
            self.preview.Width = max(1, bottom[0] + bottom[2] - top[0])
            self.preview.Height = max(1, bottom[1] + bottom[3] - top[1])
            self.preview.Visibility = Visibility.Visible
            n = abs(target - (last['pos'] if target > last['pos'] else first['pos']))
            if n:
                self.set_status(u'Fill {0} cell{1} — release to write, Escape to '
                                'cancel.'.format(n, '' if n == 1 else 's'))
        except Exception:
            pass

    def cancel_fill(self):
        self._filling = False
        self.stop_drag_scroll()
        try:
            self.handle.ReleaseMouseCapture()
        except Exception:
            pass
        try:
            self.preview.Visibility = Visibility.Collapsed
        except Exception:
            pass

    def on_handle_up(self, sender, args):
        if not self._filling:
            return
        src = self._fill_src or []
        target = self._fill_target
        self.cancel_fill()
        if not src or target < 0:
            return

        by_col = {}
        for c in src:
            by_col.setdefault(c['col'].DisplayIndex, []).append(c)

        self.begin_batch()
        written = 0
        skipped = 0
        for disp in sorted(by_col.keys()):
            group = sorted(by_col[disp], key=lambda d: d['pos'])
            col = group[0]['col']
            top = group[0]['pos']
            bottom = group[-1]['pos']
            if target > bottom:
                span = [p for p in range(bottom + 1, target + 1)
                        if not self.is_header_pos(p)]
                dest = span
                downward = True
            elif target < top:
                span = [p for p in range(top - 1, target - 1, -1)
                        if not self.is_header_pos(p)]
                dest = span
                downward = False
            else:
                continue
            seeds = [self.text_at(c['pos'], col) or '' for c in group]
            values = self.fill_values(col, seeds, len(dest), downward)
            for pos, value in zip(dest, values):
                if self.stage_cell(pos, col, value):
                    written += 1
                else:
                    skipped += 1
        self.end_batch()

        if written or skipped:
            msg = 'Filled {0} cell{1}.'.format(written, '' if written == 1 else 's')
            if skipped:
                msg += self.skipped_note(skipped)
            self.set_status(msg)
        args.Handled = True

    # -- toolbar ------------------------------------------------------------

    def selected_rows(self):
        """Distinct row indexes covered by the selection, in view order."""
        seen = []
        for c in self.sel_cells():
            if c['ridx'] not in seen:
                seen.append(c['ridx'])
        return seen

    def level_of_row(self, ridx):
        """The level the element currently sits on, as an int, or None."""
        try:
            elem = self.doc.GetElement(self.model.rows[ridx].elem_id)
            param = level_param_of(elem)
            if param is None:
                return None
            return eid_value(param.AsElementId())
        except Exception:
            return None

    def on_isolate_selected(self, sender=None, args=None):
        """Open the default 3D view and isolate the picked rows' elements.

        Temporary isolation, the same as Revit's own — it leaves the view's
        real visibility alone and goes away with Reset. The section box is kept
        on and kept **visible**, which means putting it in the isolated set:
        temporary isolation hides everything that is not in it, the section box
        element included, so the box would vanish while still cropping the view.
        """
        rows = self.selected_rows()
        if not rows:
            self.set_status('Select cells on the rows you want to isolate first.')
            return
        ids = []
        for ridx in rows:
            try:
                ids.append(self.model.rows[ridx].elem_id)
            except Exception:
                continue
        if not ids:
            self.set_status('Nothing to isolate.')
            return

        def _job(uiapp):
            from System.Collections.Generic import List
            doc = self.doc
            view = best_3d_view(doc)
            if view is None:
                return ('noview', None)
            try:
                if self.uidoc.ActiveView.Id != view.Id:
                    # the active view cannot be changed inside a transaction
                    self.uidoc.ActiveView = view
            except Exception:
                pass

            bag = List[DB.ElementId]()
            for eid in ids:
                bag.Add(eid)
            boxed = False
            try:
                if view.IsSectionBoxActive:
                    boxed = True
                    for box in DB.FilteredElementCollector(doc, view.Id)\
                            .OfCategory(DB.BuiltInCategory.OST_SectionBox)\
                            .WhereElementIsNotElementType():
                        bag.Add(box.Id)
            except Exception:
                pass

            tx = DB.Transaction(doc, u'Excel for Revit - isolate selected')
            try:
                tx.Start()
                try:
                    opts = tx.GetFailureHandlingOptions()
                    opts.SetFailuresPreprocessor(WarningSwallower())
                    opts.SetClearAfterRollback(True)
                    tx.SetFailureHandlingOptions(opts)
                except Exception:
                    pass
                view.IsolateElementsTemporary(bag)
                tx.Commit()
            except Exception:
                try:
                    tx.RollBack()
                except Exception:
                    pass
                return ('refused', None)
            try:
                self.uidoc.Selection.SetElementIds(bag)
            except Exception:
                pass
            try:
                # a view changed from a modeless window does not redraw itself
                self.uidoc.RefreshActiveView()
            except Exception:
                pass
            return ('done', (elem_name(view), boxed))

        n = len(ids)
        self.set_status('Isolating {0} element{1}...'.format(
            n, '' if n == 1 else 's'))

        def _done(outcome):
            state, detail = outcome if outcome else ('busy', None)
            if state == 'done':
                view_name, boxed = detail
                self.set_status(u'Isolated {0} element{1} in {2}.{3} Reset '
                                u'Temporary Hide/Isolate in Revit to put it '
                                u'back.'.format(
                                    n, '' if n == 1 else 's', view_name,
                                    u' The section box is still on, so anything '
                                    u'outside it stays hidden.' if boxed else ''))
            elif state == 'noview':
                self.set_status('This project has no 3D view to isolate in.')
            elif state == 'refused':
                self.set_status('Revit would not isolate those elements.')
            else:
                self.set_status('Revit would not take the request.')

        self.run_in_revit(_job, _done)

    def on_find_in_view(self, sender=None, args=None):
        """Select the rows' elements in Revit and show them in a view.

        `ShowElements` is what Revit's own "Show" does from a warning dialog:
        it finds a view the elements appear in, opens it if needed, and zooms
        to them. Selecting them first is what leaves them highlighted once it
        has finished.
        """
        rows = self.selected_rows()
        if not rows:
            self.set_status('Select cells on the rows you want to find first.')
            return
        ids = []
        for ridx in rows:
            try:
                ids.append(self.model.rows[ridx].elem_id)
            except Exception:
                continue
        if not ids:
            self.set_status('Nothing to find.')
            return

        def _job(uiapp):
            from System.Collections.Generic import List
            bag = List[DB.ElementId]()
            for eid in ids:
                bag.Add(eid)
            try:
                self.uidoc.Selection.SetElementIds(bag)
            except Exception:
                pass
            try:
                self.uidoc.ShowElements(bag)
                return 'shown'
            except Exception:
                # ShowElements raises when no open-able view contains them —
                # the selection still stands, which is half the job
                return 'selected'

        n = len(ids)

        def _done(outcome):
            if outcome == 'shown':
                self.set_status('Found {0} element{1} in Revit.'.format(
                    n, '' if n == 1 else 's'))
            elif outcome == 'selected':
                self.set_status('Selected {0} element{1}, but no open view '
                                'shows {2}.'.format(
                                    n, '' if n == 1 else 's',
                                    'it' if n == 1 else 'them'))
            else:
                self.set_status('Revit would not take the request.')

        self.set_status('Finding {0} element{1}...'.format(
            n, '' if n == 1 else 's'))
        self.run_in_revit(_job, _done)

    def on_set_level(self, sender=None, args=None):
        try:
            set_level_dialog(self)
        except Exception:
            themed_message('Set Level',
                           'Set Level could not be opened:\n\n'
                           + traceback.format_exc(),
                           accent=C_RED, width=680, owner=self.window)

    def stage_levels(self, rows, level):
        """Stage a level change per row. Nothing touches the model until APPLY."""
        level_id = level.Id
        name = elem_name(level) or 'Level'
        n = 0
        for ridx in rows:
            self.model.level_edits[ridx] = (level_id, name)
            n += 1
        self.update_pending()
        self.repaint_soon()
        return n

    def clear_level_edits(self):
        n = len(self.model.level_edits)
        self.model.level_edits = {}
        self.update_pending()
        self.repaint_soon()
        return n

    def formula_context(self, cell, n):
        """What a formula can see for one target cell."""
        model = self.model
        row = model.rows[cell['ridx']]
        cells = {}
        for fi in model.fields:
            cells[fi.letter] = model.current_text(row, fi.index)
        def lookup(column, number):
            index = number - 1
            if index < 0 or index >= len(model.rows):
                return None
            target = model.rows[index]
            for f in model.fields:
                if f.letter == column:
                    return model.current_text(target, f.index)
            return None

        return {'cells': cells,
                'row': row.ridx + 1,
                'anchor': self.formula_cells[0]['ridx'] + 1
                          if self.formula_cells else row.ridx + 1,
                'n': n,
                'id': to_text(eid_value(row.elem_id)),
                'this': model.current_text(row, cell['fidx']),
                'lookup': lookup}

    def on_sequence(self, sender, args):
        try:
            sequence_dialog(self)
        except Exception:
            self.set_status('The sequence tool could not be opened.')

    def on_affix(self, sender, args):
        try:
            affix_dialog(self)
        except Exception:
            self.set_status('The prefix tool could not be opened.')

    def on_find(self, sender, args):
        try:
            if self.finder is None:
                self.finder = FindReplace(self)
                self.finder.dlg.window.Closed += self._finder_closed
            self.finder.show()
            self.finder.dlg.window.Activate()
        except Exception:
            self.finder = None
            self.set_status('Could not open Find and Replace.')

    def _finder_closed(self, sender, args):
        self.finder = None

    def on_undo(self, sender, args):
        if not self.undo_stack:
            self.set_status('Nothing to undo.')
            return
        batch = self.undo_stack.pop()
        redo = {}
        for key, old in batch.items():
            store = self.model.store_for(key)
            redo[key] = store.get(key, _ABSENT)
            if old is _ABSENT:
                store.pop(key, None)
            else:
                store[key] = old
            self.push_to_table(key)
        self.redo_stack.append(redo)
        self.update_pending()
        self.repaint_soon()
        self.set_status('Undid {0} cell change{1}.'.format(len(batch), '' if len(batch) == 1 else 's'))

    def on_redo(self, sender, args):
        if not self.redo_stack:
            self.set_status('Nothing to redo.')
            return
        batch = self.redo_stack.pop()
        undo = {}
        for key, new in batch.items():
            store = self.model.store_for(key)
            undo[key] = store.get(key, _ABSENT)
            if new is _ABSENT:
                store.pop(key, None)
            else:
                store[key] = new
            self.push_to_table(key)
        self.undo_stack.append(undo)
        self.update_pending()
        self.repaint_soon()
        self.set_status('Redid {0} cell change{1}.'.format(len(batch), '' if len(batch) == 1 else 's'))

    def on_revert_selected(self, sender, args):
        cells = self.sel_cells()
        if not cells:
            return
        self.begin_batch()
        n = 0
        for c in cells:
            row = self.model.rows[c['ridx']]
            if self.stage(c['ridx'], c['fidx'], row.cells[c['fidx']].original):
                n += 1
        self.end_batch()
        self.set_status('Reverted {0} cell{1}.'.format(n, '' if n == 1 else 's'))

    def on_revert_all(self, sender, args):
        levels = self.clear_level_edits()
        if not self.model.edits:
            self.set_status('Dropped {0} level change{1}.'.format(
                levels, '' if levels == 1 else 's') if levels
                else 'There is nothing to revert.')
            return
        n = len(self.model.edits)
        self.begin_batch()
        for key in list(self.model.edits.keys()):
            if self._batch is not None:
                self._batch[key] = self.model.edits.get(key, _ABSENT)
            self.model.edits.pop(key, None)
            self.push_to_table(key)
        self.end_batch()
        self.set_status('Reverted all {0} pending edit{1}.'.format(n, '' if n == 1 else 's'))

    def autofit(self, announce=True):
        """Size every value column to its content, then freeze it in pixels.

        Two steps rather than just leaving the columns on Auto. Auto keeps
        re-measuring as new rows are realised while scrolling, so columns
        visibly jump about halfway down a long schedule; and Auto has no
        ceiling, so one long comments field can push everything else off the
        edge. Measuring once and then writing the result back as pixels gives
        a stable layout with a floor and a ceiling.

        The floor is not cosmetic: each header carries a filter box and a
        caret, so a column narrower than that clips its own controls.
        """
        cols = list(self.field_cols)
        if not cols:
            return
        for col in cols:
            try:
                col.Width = DataGridLength(1, DataGridLengthUnitType.Auto)
            except Exception:
                pass

        def _freeze():
            widest = 0.0
            for col in cols:
                try:
                    width = float(col.ActualWidth)
                except Exception:
                    continue
                if width <= 0:
                    continue
                width = max(AUTOFIT_MIN, min(AUTOFIT_MAX, width + AUTOFIT_PAD))
                widest = max(widest, width)
                try:
                    col.Width = DataGridLength(width, DataGridLengthUnitType.Pixel)
                except Exception:
                    pass
            self.place_handle()
            self.align_group_bar()
            self.repaint_soon()
            if announce:
                self.set_status('Columns fitted to their content.')

        # measurement is only meaningful once the rows have been laid out
        try:
            self.window.Dispatcher.BeginInvoke(DispatcherPriority.Loaded,
                                               Action(_freeze))
        except Exception:
            _freeze()

    def on_autofit(self, sender, args):
        self.autofit()

    def on_size_changed(self, sender, args):
        if self.drawer is not None and (self.drawer.shrunk or self.drawer.busy):
            # the body is pinned for the slide, so there is nothing to reflow
            # and twenty toolbar relayouts a second is what makes it stutter
            return
        self.reflow_toolbar()
        self.place_handle()

    def on_first_render(self, sender, args):
        """Fit the columns once, the first time the grid is actually drawn.

        ContentRendered rather than Loaded: the row containers do not exist
        until the grid has been through a layout pass, and measuring before
        that fits every column to its header alone.
        """
        if self._first_render_done:
            return
        self._first_render_done = True
        self.autofit(announce=False)
        self.align_group_bar()

    def on_reload(self, sender, args):
        if self.model.edits or self.model.level_edits:
            dlg = ThemedDialog('Reload from model', width=520, owner=self.window, accent=C_RED)
            pending = len(self.model.edits) + len(self.model.level_edits)
            dlg.add(_tb('Reloading discards {0} pending edit{1}.'.format(
                pending, '' if pending == 1 else 's'),
                C_TEXT, 12, False, True))
            dlg.add_button('Cancel', 'ghost', None)
            dlg.add_button('Discard and reload', 'red', 'go')
            if dlg.show() != 'go':
                return
        self.model.edits.clear()
        self.model.failed.clear()
        self.model.level_edits = {}
        self.imported = set()
        del self.undo_stack[:]
        del self.redo_stack[:]
        try:
            self.model.refresh_originals()
            for row in self.model.rows:
                for fi in self.model.fields:
                    self.table.Rows[row.ridx][fi.col] = self.model.current_text(row, fi.index)
        except Exception:
            pass
        # the sort, the grouping and the filters are all snapshots taken from
        # values that have just changed, so they are taken again rather than
        # left pointing at the old ones — and the sort survives a reload
        self.apply_filters()
        self.apply_sort()
        self.update_pending()
        self.repaint_soon()
        self.set_status('Reloaded from the model.')

    def on_clear_filters(self, sender=None, args=None):
        self.clear_all_filters()
        self.set_status('All column filters cleared.')

    # -- apply and close ----------------------------------------------------

    def on_apply(self, sender, args, then=None):
        """Queue the write. `then` is called with True when it all went in.

        The work happens in Revit's own callback, so everything that follows
        it lives in `apply_finished` rather than after the call.
        """
        if not self.model.edits and not self.model.level_edits:
            self.set_status('There are no pending edits to apply.')
            if then is not None:
                then(True)
            return
        if self.applying:
            self.set_status(u'Already applying — one moment.')
            return
        staged = len(self.model.edits)
        self.applying = True
        try:
            self.btn_apply.IsEnabled = False
        except Exception:
            pass
        self.set_status('Applying {0} edit{1}...'.format(
            staged, '' if staged == 1 else 's'))
        self.run_in_revit(lambda uiapp: self.model.apply(),
                          lambda res: self.apply_finished(res, staged, then))

    def apply_finished(self, res, staged, then=None):
        self.applying = False
        if res is None:
            self.set_status(u'Revit would not take the write — nothing was '
                            'applied, and the edits are still staged.')
            self.update_pending()
            if then is not None:
                then(False)
            return
        self.model.level_edits = {}
        self.imported = set()
        del self.undo_stack[:]
        del self.redo_stack[:]
        try:
            for row in self.model.rows:
                for fi in self.model.fields:
                    self.table.Rows[row.ridx][fi.col] = self.model.current_text(row, fi.index)
        except Exception:
            pass
        self.update_pending()
        self.repaint_soon()
        show_results(self.window, res, staged)
        elements = res['instances'] + res['types'] + res.get('levels', 0)
        self.set_status(u'Applied — {0} element{1} changed. The window is still '
                        'open for more edits.'.format(
                            elements, '' if elements == 1 else 's'))
        if then is not None:
            then(not res['failures'])

    def on_toggle_modeless(self, sender=None, args=None):
        """Switch between the modal and the modeless window, next time it runs."""
        now = bool(load_settings().get('modeless', True))
        dlg = ThemedDialog('Window behaviour', width=600, owner=self.window,
                           accent=C_ORANGE)
        dlg.add(_tb('This window is currently {0}.'.format(
            u'modeless — Revit stays usable while it is open' if now
            else u'modal — Revit is blocked while it is open'),
            C_TEXT, 13, True, True))
        note = _tb(u'Modeless lets you keep working in Revit while the schedule '
                   'is open. It relies on pyRevit keeping this tool\'s engine '
                   'alive, which needs a pyRevit reload after installing a new '
                   'version — without that the window opens and nothing in it '
                   'responds. If that happens the tool notices next time and '
                   'offers to open modally instead.\n\nThe change takes effect '
                   'the next time the tool is opened.', C_MUTED, 12, False, True)
        note.Margin = Thickness(0, 10, 0, 0)
        dlg.add(note)
        dlg.add_button('Cancel', 'ghost', None)
        dlg.add_button('Use modal (Revit blocked)' if now else
                       'Use modeless (Revit usable)', 'green', 'switch')
        if dlg.show() != 'switch':
            return
        save_settings({'modeless': not now})
        self.set_status(u'Saved — the window will be {0} next time it is '
                        'opened.'.format('modal' if now else 'modeless'))

    def on_close_click(self, sender, args):
        self.window.Close()

    def on_closing(self, sender, args):
        pending = len(self.model.edits) + len(self.model.level_edits)
        if self._closing_ok or not pending:
            self._shutdown()
            return
        args.Cancel = True
        choice = ask_exit(self.window, pending)
        if choice == 'apply':
            def _after(ok):
                if self.model.edits or self.model.level_edits:
                    self.set_status(u'Some edits could not be applied — the '
                                    'window stayed open.')
                    return
                self._closing_ok = True
                self.window.Close()
            # the write happens in Revit's callback, so the close waits for it
            self.on_apply(None, None, then=_after)
        elif choice == 'discard':
            self._closing_ok = True
            self.window.Close()

    def run_in_revit(self, job, done=None):
        """Queue work for Revit and return at once.

        **You cannot wait for an ExternalEvent from the window.** Revit raises
        it on the same thread the window lives on, so blocking that thread to
        wait for the answer is a deadlock: the handler never gets a turn, the
        wait times out, and the command looks as though it did nothing. That is
        exactly what it did.

        So the job is queued and this returns immediately; whatever it produces
        comes back through `done`, marshalled onto the dispatcher so it can
        touch the window safely.
        """
        if not self.modeless or self.handler is None or self.event is None:
            # modal: the command is still inside Revit's API context, so the
            # work can simply be done here
            outcome = None
            try:
                outcome = job(None)
            except Exception:
                themed_message('Excel for Revit', traceback.format_exc(),
                               accent=C_RED, width=700, owner=self.window)
            if done is not None:
                done(outcome)
            return

        def _wrapped(uiapp):
            box = {'value': None, 'error': None}
            try:
                box['value'] = job(uiapp)
            except Exception:
                box['error'] = traceback.format_exc()

            def _back():
                if box['error']:
                    themed_message('Excel for Revit', box['error'],
                                   accent=C_RED, width=700, owner=self.window)
                elif done is not None:
                    done(box['value'])
            try:
                self.window.Dispatcher.BeginInvoke(
                    DispatcherPriority.Background, Action(_back))
            except Exception:
                pass

        self.handler.job = _wrapped
        try:
            self.event.Raise()
        except Exception:
            if done is not None:
                done(None)

    def _shutdown(self):
        global LIVE_WINDOW
        LIVE_WINDOW = None
        try:
            if self.finder is not None:
                self.finder.dlg.window.Close()
        except Exception:
            pass

    def attach_egg(self, f):
        """Wire the shared RevoBIM easter egg to the logo.

        Three slow clicks on the wordmark open the mini game launcher. It lives
        in the extension's own lib\\revobim\\egg, so this is a soft dependency:
        anything at all going wrong here is swallowed, because a decoration
        must never be able to stop a schedule being edited.
        """
        try:
            from revobim.egg import egg_hook
        except Exception:
            return
        try:
            targets = []
            for name in ('LogoText', 'IconImage'):
                try:
                    element = f(name)
                    if element is not None:
                        targets.append(element)
                except Exception:
                    continue
            if not targets:
                return
            egg_hook.attach(targets, host_window=self.window,
                            theme=lambda: self.theme_name)
        except Exception:
            pass

    def show(self):
        """Modal by default; modeless when the setting asks for it.

        Modeless is owned to Revit's main window, or an unowned modeless window
        slips behind Revit and reads as a crash, and parked in a module level
        variable as well, or the persistent engine can collect it.
        """
        global LIVE_WINDOW, LIVE_HANDLER, LIVE_EVENT
        if not self.modeless:
            self.window.ShowDialog()
            return
        owned = False
        try:
            from System.Windows.Interop import WindowInteropHelper
            import Autodesk.Windows as AdWindows
            helper = WindowInteropHelper(self.window)
            helper.Owner = AdWindows.ComponentManager.ApplicationWindow
            owned = True
        except Exception:
            pass
        if not owned:
            # Owned is what keeps it in front of Revit; unowned, a click in
            # the model sends it behind Revit and it reads as a crash.  Revit's
            # own process window is the same owner by another route.
            try:
                from System.Windows.Interop import WindowInteropHelper
                from System.Diagnostics import Process
                helper = WindowInteropHelper(self.window)
                helper.Owner = Process.GetCurrentProcess().MainWindowHandle
            except Exception:
                pass
        try:
            # A modeless WPF window inside a host with its own message loop
            # needs its keystrokes routed to it, or typing in a cell can be
            # taken by Revit's shortcuts instead.  Harmless where not needed.
            from System.Windows.Forms.Integration import ElementHost
            ElementHost.EnableModelessKeyboardInterop(self.window)
        except Exception:
            pass
        LIVE_WINDOW = self
        LIVE_HANDLER = self.handler        # the event and its handler have to
        LIVE_EVENT = self.event            # outlive the command as well
        # A torn-down engine leaves the window on screen with every handler
        # dead, and nothing inside it can report that — including the switch
        # back to modal. So the fact that a modeless window was opened is
        # written down here, and cleared again by the first handler that runs.
        # If it is still set at the next launch, the last one never responded.
        save_settings({'modeless_pending': True})
        self.window.Show()
        try:
            self.window.Activate()
        except Exception:
            pass
        # From here on the command has done its work.  Any handler that still
        # runs after this is running on a live engine, so it may prove it.
        self._shown = True


# ------------------------------------------------------------- result UI ----

def ask_exit(owner, pending):
    dlg = ThemedDialog('Unsaved edits', width=560, owner=owner, accent=C_ORANGE)
    dlg.add(_tb('{0} edit{1} have not been written to the model.'.format(
        pending, '' if pending == 1 else 's'), C_TEXT, 14, True, True))
    note = _tb('Closing now discards them. Nothing in this session has touched the '
               'model yet.', C_MUTED, 12, False, True)
    note.Margin = Thickness(0, 8, 0, 0)
    dlg.add(note)
    dlg.add_button('Cancel', 'ghost', 'cancel')
    dlg.add_button('Exit without saving', 'red', 'discard')
    dlg.add_button('Apply and exit', 'green', 'apply')
    return dlg.show()


def show_results(owner, res, staged):
    elements = res['instances'] + res['types'] + res.get('levels', 0)
    ok = len(res['failures']) == 0
    accent = C_GREEN if ok else C_ORANGE
    dlg = ThemedDialog('Applied to the model', width=620, owner=owner, accent=accent)

    head = _tb('{0} element{1} changed'.format(elements, '' if elements == 1 else 's'),
               C_GREEN if ok else C_ORANGE, 26, True)
    dlg.add(head)

    lines = [
        '{0} cell{1} written of {2} staged.'.format(
            res['cells'], '' if res['cells'] == 1 else 's', staged),]
    if res.get('levels'):
        lines.append('{0} element{1} moved to a different level, without '
                     'moving in the model.'.format(
                         res['levels'], '' if res['levels'] == 1 else 's'))
    lines += [
        '{0} instance parameter{1} and {2} type parameter{3} written.'.format(
            res['instances'], '' if res['instances'] == 1 else 's',
            res['types'], '' if res['types'] == 1 else 's'),
        '{0} scheduled row{1} affected.'.format(
            res['rows_affected'], '' if res['rows_affected'] == 1 else 's'),
    ]
    if res['types']:
        lines.append('Type parameter changes reach every element of those types, '
                     'including ones outside this schedule.')
    body = _tb('\n'.join(lines), C_TEXT, 12, False, True)
    body.Margin = Thickness(0, 10, 0, 0)
    dlg.add(body)

    if res['failures']:
        warn = _tb(u'{0} cell{1} refused — left staged and marked red in the grid:'.format(
            len(res['failures']), '' if len(res['failures']) == 1 else 's'),
            C_RED, 12, True, True)
        warn.Margin = Thickness(0, 14, 0, 6)
        dlg.add(warn)
        box = Border()
        box.Background = brush(C_FIELD)
        box.BorderBrush = brush(C_EDGE)
        box.BorderThickness = Thickness(1)
        box.CornerRadius = CornerRadius(3)
        box.Padding = Thickness(8)
        sv = ScrollViewer()
        sv.MaxHeight = 220
        sv.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
        stack = StackPanel()
        for label, pname, msg in res['failures'][:200]:
            t = _tb(u'{0}  \u2022  {1}  \u2014  {2}'.format(label, pname or 'parameter', msg),
                    C_MUTED, 11, False, True)
            t.Margin = Thickness(0, 1, 0, 1)
            stack.Children.Add(t)
        sv.Content = stack
        box.Child = sv
        dlg.add(box)

    tail = _tb('The window stays open for more edits.', C_MUTED, 11, False, True)
    tail.Margin = Thickness(0, 12, 0, 0)
    dlg.add(tail)
    dlg.add_button('OK', 'green', 'ok')
    return dlg.show()


# ------------------------------------------------------------------ main ----

LIVE_WINDOW = None      # keeps the modeless window alive under the engine
LIVE_HANDLER = None
LIVE_EVENT = None


WINDOW_SETTINGS_VERSION = 2


def migrate_window_settings():
    """Undo, once, the modal setting the old false alarm talked people into.

    Up to 1.18.0 the liveness proof was used up before the window was shown,
    so every launch after the first was reported as a dead window with an
    offer to switch to modal — and accepting it made Revit blocked for good.
    Settings written by those versions are put back to modeless, with the
    health record cleared, so the corrected check starts from nothing.
    """
    settings = load_settings()
    if settings.get('window_settings') == WINDOW_SETTINGS_VERSION:
        return
    save_settings({'modeless': True,
                   'modeless_pending': False,
                   'modeless_proved': False,
                   'window_settings': WINDOW_SETTINGS_VERSION})


def check_modeless_health():
    """Offer a way out when the last modeless window never answered.

    A torn-down engine leaves the window on screen with every handler dead, so
    it cannot report the problem or offer the switch back to modal. The flag it
    left behind can, and this runs before the window exists.
    """
    settings = load_settings()
    if not settings.get('modeless_pending'):
        return
    save_settings({'modeless_pending': False})
    if settings.get('modeless_proved'):
        return          # it has worked here before; assume a normal close

    dlg = ThemedDialog('Window behaviour', width=640, accent=C_ORANGE)
    dlg.add(_tb('The last time this opened, nothing in the window responded.',
                C_TEXT, 14, True, True))
    note = _tb(u'That happens when pyRevit does not keep this tool\'s engine '
               'alive: the window appears, and every button in it is dead.\n\n'
               'Two things fix it. **Reload pyRevit** (pyRevit tab > Reload) '
               'and try again — the setting that keeps the engine alive only '
               'takes effect after a reload. Or open the window modally, which '
               'always works but blocks Revit while it is open.'.replace('**', ''),
               C_MUTED, 12, False, True)
    note.Margin = Thickness(0, 10, 0, 0)
    dlg.add(note)
    dlg.add_button('Try modeless again', 'ghost', 'keep')
    dlg.add_button('Open it modally instead', 'green', 'modal')
    if dlg.show() == 'modal':
        save_settings({'modeless': False})


def log_failure(stage, detail):
    """Write the failure somewhere it can be read after the dialog is gone."""
    try:
        if not os.path.isdir(SETTINGS_DIR):
            os.makedirs(SETTINGS_DIR)
        handle = open(os.path.join(SETTINGS_DIR, 'excel_for_revit_last_error.txt'), 'w')
        try:
            handle.write('stage: {0}\n\n{1}'.format(stage, detail))
        finally:
            handle.close()
    except Exception:
        pass


def busy_cursor(on):
    """The wait cursor, for the seconds a large schedule takes to read and lay
    out — without it the button looks as if it did nothing, and gets pressed
    again."""
    try:
        Mouse.OverrideCursor = Cursors.Wait if on else None
    except Exception:
        pass


def main():
    """Load in stages, and say which stage failed.

    A tool this size fails in one of a handful of places, and "nothing
    happens" is not a diagnosis. Each stage names itself, so a report can say
    where it stopped instead of that it stopped.
    """
    stage = 'starting'
    try:
        stage = 'reading the document'
        try:
            uidoc = revit.uidoc
            doc = revit.doc
        except Exception:
            uidoc, doc = None, None
        if doc is None or uidoc is None:
            themed_message('Excel for Revit',
                           'Open a project before running this tool.')
            return
        try:
            if doc.IsFamilyDocument:
                themed_message('Excel for Revit',
                               'This tool works on project schedules. Open a '
                               'project document.')
                return
        except Exception:
            pass

        stage = 'finding the schedule'
        sched = resolve_schedule(uidoc, doc)
        if sched is None:
            return

        stage = 'reading the schedule'
        busy_cursor(True)
        try:
            model = ScheduleModel(doc, sched)
        finally:
            busy_cursor(False)          # every prompt below needs a pointer
        if model.error:
            themed_message('Excel for Revit', model.error, accent=C_RED, width=600)
            return
        if not model.rows:
            themed_message('Excel for Revit',
                           u'"{0}" has no elements to edit.\n\nIt may be empty, '
                           u'filtered to nothing, or a key schedule with no keys '
                           u'defined.'.format(elem_name(sched)))
            return

        stage = 'checking the last session'
        migrate_window_settings()
        check_modeless_health()

        stage = 'building the window'
        busy_cursor(True)
        try:
            win = ExcelForRevitWindow(uidoc, doc, model)
        finally:
            busy_cursor(False)

        stage = 'showing the window'
        win.show()
    except Exception:
        busy_cursor(False)
        detail = traceback.format_exc()
        log_failure(stage, detail)
        try:
            themed_message('Excel for Revit',
                           'Failed while {0}.\n\n{1}\n\nThis was also written '
                           'to %APPDATA%\\RevoBIM PY\\'
                           'excel_for_revit_last_error.txt'.format(stage, detail),
                           accent=C_RED, width=720)
        except Exception:
            pass

