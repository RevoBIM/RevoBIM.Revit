# -*- coding: utf-8 -*-
"""RevoBIM PY - Wires bench check.

A blank white pyRevit window means an import blew up at module load, not that
the dialog is broken - and pyRevit's own error window has nothing readable in
it. This loads every shipped module against a stub Revit and .NET API that
declares each name in the namespace the real API puts it in, so a
mis-namespaced import fails here on the bench instead of in Revit.

It also enforces the rules this extension has been caught out by before:

  * no f-strings and no print statements (IronPython 2.7 has neither)
  * no bare .IntegerValue outside the guarded eid_value helper (removed 2026)
  * no System.Uri (moved assemblies between Revit 2024 and 2025)
  * every imported .NET namespace has a matching clr.AddReference in the same
    file - never rely on another module having loaded the assembly first
  * every FindName has a matching x:Name in a layout file
  * every StaticResource key is defined earlier in the same layout file

Run it with any Python 3:  python import_check.py
Exit code 0 means clean.
"""

from __future__ import print_function

import ast
import builtins
import io
import os
import re
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))

MODULES = ['wires_core', 'circuit_core', 'wire_events', 'wires_theme',
           'wires_drawer', 'wires_ui',
           'results_window',
           'settings_window', 'shuffle_window', 'confirm_window']

SCRIPTS = [
    os.path.join('Auto Wire.pushbutton', 'script.py'),
    os.path.join('Apply Wire Types.pushbutton', 'script.py'),
    os.path.join('Align Wire Ends.pushbutton', 'script.py'),
    os.path.join('Re-Route Wires.pushbutton', 'script.py'),
    os.path.join('Reconnect Wires.pushbutton', 'script.py'),
    os.path.join('Settings.pushbutton', 'script.py'),
]

LAYOUTS = ['WiresResults.xaml', 'WiresSettings.xaml', 'WiresShuffle.xaml',
           'WiresConfirm.xaml']


# ---------------------------------------------------------------------------
# The stub API. Each list is the set of names the real assembly puts in that
# namespace. Getting one of these wrong on purpose is how the check was tested.
# ---------------------------------------------------------------------------
NAMESPACES = {
    'Autodesk': [],
    'Autodesk.Revit': [],
    'Autodesk.Revit.DB': [
        'XYZ', 'ElementId', 'Element', 'ElementType', 'BuiltInCategory',
        'BuiltInParameter', 'Category', 'Domain', 'ConnectorType',
        'FilteredElementCollector', 'ElementCategoryFilter',
        'ElementMulticategoryFilter', 'ElementClassFilter',
        'Transaction', 'SubTransaction', 'TransactionGroup', 'TransactionStatus',
        'IFailuresPreprocessor', 'FailureProcessingResult', 'FailureSeverity',
        'FailuresAccessor', 'FailureHandlingOptions',
        'FamilyInstance', 'FamilySymbol', 'MEPModel', 'MEPSystem',
        'Connector', 'ConnectorManager', 'ConnectorSet',
        'Location', 'LocationPoint', 'LocationCurve', 'Curve', 'Line',
        'IndependentTag', 'TagMode', 'TagOrientation', 'Level',
        'ElementTypeGroup', 'GraphicsStyle', 'GraphicsStyleType', 'DetailCurve',
        'Space', 'SpatialElement', 'CurveElement',
        'Transform', 'BoundingBoxXYZ', 'Outline', 'Options', 'View', 'ViewType',
        'StorageType', 'Parameter', 'Reference', 'ElementTransformUtils',
        'UnitUtils', 'WorksetId', 'Workset', 'WorksetKind',
    ],
    'Autodesk.Revit.DB.Electrical': [
        'Wire', 'WireType', 'WiringType', 'ElectricalSystem',
        'PanelScheduleType',
        'ElectricalSystemType', 'ElectricalEquipment', 'PanelScheduleView',
        'CircuitLoadCalculationMethod',
    ],
    'Autodesk.Revit.UI': [
        'TaskDialog', 'TaskDialogResult', 'TaskDialogCommonButtons',
        'UIApplication', 'UIDocument', 'ExternalCommandData', 'Result',
        'IExternalEventHandler', 'ExternalEvent',
        'RevitCommandId', 'PostableCommand',
        'IExternalEventHandler', 'ExternalEvent', 'ExternalEventRequest',
    ],
    'Autodesk.Revit.UI.Selection': [
        'ISelectionFilter', 'ObjectType', 'Selection', 'PickBoxStyle',
    ],
    'Autodesk.Revit.UI.Events': ['DialogBoxShowingEventArgs'],
    'Autodesk.Revit.Exceptions': [
        'OperationCanceledException', 'InvalidOperationException',
        'ArgumentException',
    ],

    'System': ['Guid', 'EventHandler', 'Array', 'Convert', 'Environment',
               'TimeSpan', 'Double'],
    'System.Collections.Generic': ['List', 'Dictionary', 'HashSet'],
    'System.Diagnostics': ['Process'],
    'System.IO': ['File', 'Path', 'MemoryStream', 'StringReader', 'Directory'],
    'System.Xml': ['XmlReader', 'XmlDocument'],
    'System.Windows': [
        'Clipboard',
        'Window', 'Visibility', 'Thickness', 'CornerRadius', 'GridLength',
        'GridUnitType', 'TextWrapping', 'HorizontalAlignment',
        'VerticalAlignment', 'MessageBox', 'ResourceDictionary', 'FontWeights',
        'SystemParameters', 'Duration', 'SizeToContent', 'PresentationSource',
        'LogicalTreeHelper',
    ],
    'System.Windows.Controls': [
        'Grid', 'ColumnDefinition', 'RowDefinition', 'TextBlock', 'TextBox',
        'Border', 'CheckBox', 'ComboBox', 'ComboBoxItem', 'Button', 'StackPanel',
        'ScrollViewer', 'ListBox', 'ListBoxItem', 'Orientation', 'Image',
        'Slider', 'RepeatButton', 'Control',
    ],
    'System.Windows.Input': ['MouseButtonEventHandler', 'MouseButtonEventArgs',
                             'Key', 'Keyboard', 'ModifierKeys'],
    'System.Windows.Media.Animation': ['DoubleAnimation', 'QuadraticEase',
                                       'EasingMode'],
    'System.Windows.Interop': ['WindowInteropHelper'],
    'System.Windows.Markup': ['XamlReader'],
    'System.Windows.Media': ['SolidColorBrush', 'Color', 'Brushes', 'Colors'],
    'System.Windows.Media.Imaging': ['BitmapImage', 'BitmapCacheOption'],
    'System.Windows.Forms': ['Screen'],
}

# A namespace may only be imported by a file that has already asked for the
# assembly it lives in. Never rely on another module having loaded it first.
ASSEMBLY_FOR = {
    'Autodesk.Revit.DB': ['RevitAPI'],
    'Autodesk.Revit.DB.Electrical': ['RevitAPI'],
    'Autodesk.Revit.Exceptions': ['RevitAPI'],
    'Autodesk.Revit.UI': ['RevitAPIUI'],
    'Autodesk.Revit.UI.Selection': ['RevitAPIUI'],
    'Autodesk.Revit.UI.Events': ['RevitAPIUI'],
    'System': ['System', 'mscorlib'],
    'System.Collections.Generic': ['mscorlib'],
    'System.Diagnostics': ['System', 'mscorlib'],
    'System.IO': ['mscorlib'],
    'System.Xml': ['System.Xml'],
    'System.Windows': ['PresentationFramework', 'PresentationCore',
                       'WindowsBase'],
    'System.Windows.Controls': ['PresentationFramework'],
    'System.Windows.Input': ['PresentationCore'],
    'System.Windows.Interop': ['PresentationCore', 'PresentationFramework'],
    'System.Windows.Markup': ['PresentationFramework', 'System.Xaml'],
    'System.Windows.Media': ['PresentationCore'],
    'System.Windows.Media.Imaging': ['PresentationCore'],
    'System.Windows.Media.Animation': ['PresentationCore'],
    'System.Windows.Forms': ['System.Windows.Forms'],
}

# Namespaces whose assembly requirement is satisfied by any one of the list
# above, rather than all of them.
ANY_OF = set(['System', 'System.Diagnostics', 'System.Windows.Interop',
              'System.Windows.Markup'])


class _Stub(object):
    """Stands in for a .NET type. Callable, subscriptable and inheritable.

    __init__ takes anything because subclassing a stub interface makes the
    stub's own class the metaclass, so Python calls it with (name, bases,
    namespace) rather than with a single name.
    """

    def __init__(self, name='stub', *rest):
        self._name = name

    def __repr__(self):
        return self._name

    def __str__(self):
        return self._name

    def __call__(self, *args, **kwargs):
        return self

    def __getitem__(self, item):
        return self

    def __getattr__(self, item):
        if item.startswith('__'):
            raise AttributeError(item)
        return _Stub('{0}.{1}'.format(self._name, item))


def install_stub_api():
    requested = {}

    clr_module = types.ModuleType('clr')

    def add_reference(name):
        requested.setdefault(_CURRENT[0], set()).add(name)
        return None

    clr_module.AddReference = add_reference
    clr_module.AddReferenceByName = add_reference
    clr_module.GetClrType = lambda x: x
    sys.modules['clr'] = clr_module

    for dotted in sorted(NAMESPACES.keys()):
        module = types.ModuleType(dotted)
        for name in NAMESPACES[dotted]:
            setattr(module, name, _Stub(dotted + '.' + name))
        sys.modules[dotted] = module
        if '.' in dotted:
            parent_name, leaf = dotted.rsplit('.', 1)
            parent = sys.modules.get(parent_name)
            if parent is None:
                parent = types.ModuleType(parent_name)
                sys.modules[parent_name] = parent
            setattr(parent, leaf, module)
    return requested


_CURRENT = ['(unknown)']


# ---------------------------------------------------------------------------
# source rules
# ---------------------------------------------------------------------------
PRINT_STATEMENT = re.compile(r'^\s*print\s+[^\(=]', re.MULTILINE)
INTEGER_VALUE = re.compile(r'\.IntegerValue')
SYSTEM_URI = re.compile(r'\bSystem\s*\.\s*Uri\b|from\s+System\s+import\s+.*\bUri\b')


def read(path):
    handle = io.open(path, 'r', encoding='utf-8')
    try:
        return handle.read()
    finally:
        handle.close()


def mask_source(text):
    """Blank out comments and string bodies, keeping every line number.

    Without this the module docstring listing the rules trips every one of
    them, which is a comic way to fail a bench check.
    """
    import tokenize
    try:
        lines = text.splitlines(True)
        masked = list(lines)
        readline = io.StringIO(text).readline
        for token in tokenize.generate_tokens(readline):
            kind, _value, start, end, _line = token
            if kind not in (tokenize.STRING, tokenize.COMMENT):
                continue
            for row in range(start[0], end[0] + 1):
                index = row - 1
                if index >= len(masked):
                    break
                line = masked[index]
                first = start[1] if row == start[0] else 0
                last = end[1] if row == end[0] else len(line.rstrip('\n'))
                body = line.rstrip('\n')
                body = body[:first] + (' ' * max(0, last - first)) + body[last:]
                masked[index] = body + ('\n' if line.endswith('\n') else '')
        return ''.join(masked)
    except Exception:
        return text


def _string_value(node):
    """The literal text of a string node, across Python versions."""
    try:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
    except AttributeError:
        pass
    if not hasattr(ast, 'Constant'):   # Python 3.7 and older
        try:
            if isinstance(node, ast.Str):
                return node.s
        except AttributeError:
            pass
    return None


def add_references_in(tree):
    """Every assembly the file asks for, including via a loop over a tuple."""
    asked = set()
    loops = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.For) and isinstance(node.target, ast.Name):
            if isinstance(node.iter, (ast.Tuple, ast.List)):
                values = []
                for item in node.iter.elts:
                    value = _string_value(item)
                    if value is not None:
                        values.append(value)
                if values:
                    loops[node.target.id] = values
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = None
        if isinstance(node.func, ast.Attribute):
            name = node.func.attr
        elif isinstance(node.func, ast.Name):
            name = node.func.id
        if name not in ('AddReference', 'AddReferenceByName'):
            continue
        for argument in node.args:
            value = _string_value(argument)
            if value is not None:
                asked.add(value)
            elif isinstance(argument, ast.Name):
                asked.update(loops.get(argument.id, []))
    return asked


def check_source(path, problems):
    label = os.path.relpath(path, HERE)
    text = read(path)

    try:
        tree = ast.parse(text, filename=path)
    except SyntaxError as error:
        problems.append('{0}: will not parse - {1}'.format(label, error))
        return None, text

    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            problems.append('{0}:{1}: f-string - IronPython 2.7 has no '
                            'f-strings, use .format()'.format(label, node.lineno))

    masked = mask_source(text)

    for match in PRINT_STATEMENT.finditer(masked):
        line = masked[:match.start()].count('\n') + 1
        problems.append('{0}:{1}: print statement'.format(label, line))

    for match in SYSTEM_URI.finditer(masked):
        line = masked[:match.start()].count('\n') + 1
        problems.append('{0}:{1}: System.Uri - it moved assemblies in Revit '
                        '2025 and throws at module load. Load bitmaps from a '
                        'MemoryStream instead.'.format(label, line))

    guarded = _eid_value_span(tree)
    for match in INTEGER_VALUE.finditer(masked):
        line = masked[:match.start()].count('\n') + 1
        if guarded and guarded[0] <= line <= guarded[1]:
            continue
        problems.append('{0}:{1}: bare .IntegerValue - removed in Revit 2026, '
                        'go through eid_value()'.format(label, line))

    asked = add_references_in(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.module is None:
            continue
        namespace = node.module
        if namespace not in NAMESPACES:
            if namespace.split('.')[0] in ('Autodesk', 'System'):
                problems.append('{0}:{1}: unknown namespace {2} - the stub API '
                                'does not declare it'.format(
                                    label, node.lineno, namespace))
            continue
        declared = set(NAMESPACES[namespace])
        for alias in node.names:
            if alias.name == '*':
                continue
            if alias.name not in declared:
                problems.append(
                    '{0}:{1}: {2} is not in {3} - check which namespace the '
                    'real API puts it in'.format(
                        label, node.lineno, alias.name, namespace))
        needed = ASSEMBLY_FOR.get(namespace, [])
        if needed:
            if namespace in ANY_OF:
                if not (asked & set(needed)):
                    problems.append(
                        '{0}:{1}: {2} imported with no clr.AddReference for '
                        'any of {3} in this file'.format(
                            label, node.lineno, namespace, ', '.join(needed)))
            else:
                missing = [a for a in needed if a not in asked]
                if missing:
                    problems.append(
                        '{0}:{1}: {2} imported with no clr.AddReference({3}) '
                        'in this file'.format(
                            label, node.lineno, namespace,
                            ', '.join(repr(m) for m in missing)))
    return tree, text


def _eid_value_span(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == 'eid_value':
            end = getattr(node, 'end_lineno', node.lineno + 20)
            return (node.lineno, end)
    return None


# ---------------------------------------------------------------------------
# layout rules
# ---------------------------------------------------------------------------
X_NAME = re.compile(r'x:Name\s*=\s*"([^"]+)"')
X_KEY = re.compile(r'x:Key\s*=\s*"([^"]+)"')
STATIC = re.compile(r'\{StaticResource\s+([^\}\s]+)\s*\}')
FIND_NAME = re.compile(r"""FindName\s*\(\s*['"]([^'"]+)['"]\s*\)""")


def check_layouts(problems):
    names = set()
    for layout in LAYOUTS:
        path = os.path.join(HERE, layout)
        if not os.path.isfile(path):
            problems.append('{0}: missing'.format(layout))
            continue
        text = read(path)
        names |= set(X_NAME.findall(text))

        keys = {}
        for match in X_KEY.finditer(text):
            keys[match.group(1)] = match.start()
        for match in STATIC.finditer(text):
            key = match.group(1)
            line = text[:match.start()].count('\n') + 1
            if key not in keys:
                problems.append('{0}:{1}: StaticResource {2} is never '
                                'defined'.format(layout, line, key))
            elif keys[key] > match.start():
                problems.append('{0}:{1}: StaticResource {2} is defined after '
                                'it is used - a StaticResource only sees keys '
                                'already parsed'.format(layout, line, key))
    return names


# Tables whose first column is a control name looked up with FindName. The
# lookup itself goes through a variable, so the literal has to be found here.
NAME_TABLES = ('CHECKS', 'NUMBERS')   # kept for any tool that still uses them


def _table_names(tree):
    """(name, line) for every control name held in a NAME_TABLES table."""
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if not [t for t in targets if t in NAME_TABLES]:
            continue
        if not isinstance(node.value, (ast.Tuple, ast.List)):
            continue
        for row in node.value.elts:
            if isinstance(row, (ast.Tuple, ast.List)) and row.elts:
                value = _string_value(row.elts[0])
                if value is not None:
                    found.append((value, getattr(row, 'lineno', node.lineno)))
    return found


def check_find_names(names, problems):
    for relative in MODULES + SCRIPTS:
        path = relative if relative.endswith('.py') else relative + '.py'
        path = os.path.join(HERE, path)
        if not os.path.isfile(path):
            continue
        label = os.path.relpath(path, HERE)
        text = read(path)
        for match in FIND_NAME.finditer(text):
            wanted = match.group(1)
            if wanted not in names:
                line = text[:match.start()].count('\n') + 1
                problems.append('{0}:{1}: FindName("{2}") has no matching '
                                'x:Name in any layout'.format(
                                    label, line, wanted))
        try:
            tree = ast.parse(text, filename=path)
        except SyntaxError:
            continue
        for wanted, line in _table_names(tree):
            if wanted not in names:
                problems.append('{0}:{1}: "{2}" is looked up with FindName but '
                                'has no matching x:Name in any layout'.format(
                                    label, line, wanted))



# ---------------------------------------------------------------------------
# settings keys
# ---------------------------------------------------------------------------
SETTING_READ = re.compile(
    r"""_settings_bool\(\s*settings\s*,\s*['"]([^'"]+)['"]"""
    r"""|_settings_float\(\s*settings\s*,\s*['"]([^'"]+)['"]"""
    r"""|settings\.get\(\s*['"]([^'"]+)['"]""")


def check_settings_keys(problems):
    """Every settings key read anywhere must exist in DEFAULTS.

    The settings window is built from SCHEMA, so a key typed one way in the
    schema and another way in the code would read its default for ever and
    never report anything. Cheap to catch here.
    """
    try:
        core = sys.modules.get('wires_core') or __import__('wires_core')
        defaults = set(core.DEFAULTS.keys())
    except Exception as error:
        problems.append('wires_core.py: DEFAULTS unreadable - {0}'.format(error))
        return

    for relative in MODULES + SCRIPTS:
        path = relative if relative.endswith('.py') else relative + '.py'
        path = os.path.join(HERE, path)
        if not os.path.isfile(path):
            continue
        label = os.path.relpath(path, HERE)
        # raw, not masked: mask_source blanks string bodies, which is exactly
        # where the key names live
        text = read(path)
        for match in SETTING_READ.finditer(text):
            key = match.group(1) or match.group(2) or match.group(3)
            if not key or key in defaults:
                continue
            line = text[:match.start()].count('\n') + 1
            problems.append('{0}:{1}: settings key "{2}" is read but is not in '
                            'DEFAULTS - it would silently read a default for '
                            'ever'.format(label, line, key))

    try:
        for row in core.SCHEMA:
            if row[2] == 'note':
                continue
            if row[3] not in defaults:
                problems.append('wires_core.py: SCHEMA row "{0}" produced no '
                                'default'.format(row[3]))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# the theme
# ---------------------------------------------------------------------------
THEME = 'Theme.xaml'
DYNAMIC = re.compile(r'\{DynamicResource\s+([^\}\s]+)\s*\}')
BASED_ON = re.compile(r'BasedOn\s*=\s*"\{StaticResource\s+([^\}\s]+)\s*\}"')
STYLE_USE = re.compile(r'<([A-Za-z]+)\b[^>]*?\bStyle\s*=\s*"\{DynamicResource\s+([^\}\s]+)\s*\}"',
                       re.S)
STYLE_DEF = re.compile(r'<Style\b[^>]*?x:Key\s*=\s*"([^"]+)"[^>]*?TargetType\s*=\s*"([^"]+)"'
                       r'|<Style\b[^>]*?TargetType\s*=\s*"([^"]+)"[^>]*?x:Key\s*=\s*"([^"]+)"',
                       re.S)
BRUSH_DEF = re.compile(r'<SolidColorBrush\s+x:Key\s*=\s*"([^"]+)"')
HEX = re.compile(r'#[0-9A-Fa-f]{6}\b')
PAINT_KEY = re.compile(r"""paint\([^,]+,\s*[^,]+,\s*(?:\n\s*)?['"]([A-Za-z]+)['"]""")
PAINT_EITHER = re.compile(r"""paint\([^,]+,\s*[^,]+,\s*(?:\n\s*)?['"]([A-Za-z]+)['"]\s+if\s+.+?\s+else\s+['"]([A-Za-z]+)['"]""",
                          re.S)
RESOURCE_REF = re.compile(r"""SetResourceReference\([^,]+,\s*['"]([A-Za-z]+)['"]""")

# what every window's header and body must carry, for the chip, the drawer
# and the house header order to work at all
WINDOW_PARTS = ('Chrome', 'RootGrid', 'HeaderBar', 'HeaderIcon', 'ToolName',
                'ThemeChip', 'ThemeText', 'VersionText', 'ShrinkButton',
                'ShrinkGlyph', 'ExpandGlyph', 'CloseButton')

# modules that build windows: nothing in them paints a colour by value
WINDOW_MODULES = ('wires_ui', 'wires_drawer', 'results_window',
                  'settings_window', 'shuffle_window', 'confirm_window')


def _line(text, index):
    return text[:index].count('\n') + 1


def check_theme(problems):
    """The rules that keep every window themable and swappable."""
    theme_path = os.path.join(HERE, THEME)
    if not os.path.isfile(theme_path):
        problems.append('{0}: missing'.format(THEME))
        return
    theme_text = read(theme_path)

    keys = {}
    for match in X_KEY.finditer(theme_text):
        keys[match.group(1)] = match.start()
    style_types = {}
    for match in STYLE_DEF.finditer(theme_text):
        key = match.group(1) or match.group(4)
        target = match.group(2) or match.group(3)
        style_types[key] = target

    # StaticResource inside Theme.xaml: BasedOn only, and only backwards
    based = set(m.start() for m in BASED_ON.finditer(theme_text))
    for match in BASED_ON.finditer(theme_text):
        key = match.group(1)
        if key not in keys:
            problems.append('{0}:{1}: BasedOn {2} is never defined'.format(
                THEME, _line(theme_text, match.start()), key))
        elif keys[key] > match.start():
            problems.append('{0}:{1}: BasedOn {2} is defined after it is '
                            'used'.format(THEME, _line(theme_text,
                                                       match.start()), key))
    for match in STATIC.finditer(theme_text):
        inside = [b for b in based
                  if b <= match.start() <= b + 60 + len(match.group(0))]
        if not inside:
            problems.append('{0}:{1}: StaticResource {2} outside a BasedOn - '
                            'it cannot follow a theme swap'.format(
                                THEME, _line(theme_text, match.start()),
                                match.group(1)))

    for name, text in [(THEME, theme_text)] + [
            (layout, read(os.path.join(HERE, layout)))
            for layout in LAYOUTS if os.path.isfile(os.path.join(HERE, layout))]:
        for match in DYNAMIC.finditer(text):
            if match.group(1) not in keys:
                problems.append('{0}:{1}: DynamicResource {2} is not defined '
                                'in {3}'.format(name, _line(text, match.start()),
                                                match.group(1), THEME))
        for match in STYLE_USE.finditer(text):
            tag, key = match.group(1), match.group(2)
            target = style_types.get(key)
            if target is not None and target != tag:
                problems.append('{0}:{1}: <{2}> given Style {3}, whose '
                                'TargetType is {4} - WPF throws when the style '
                                'is applied'.format(name, _line(text,
                                                                match.start()),
                                                    tag, key, target))
        if name == THEME:
            continue
        for match in STATIC.finditer(text):
            problems.append('{0}:{1}: StaticResource {2} in a layout - the '
                            'theme is merged after the parse, so this is a '
                            'blank window'.format(name, _line(text,
                                                              match.start()),
                                                  match.group(1)))
        if '<Window.Resources>' in text:
            problems.append('{0}: carries its own Window.Resources - every '
                            'brush and style belongs in {1}'.format(name, THEME))
        for match in HEX.finditer(text):
            problems.append('{0}:{1}: colour {2} by value in a layout - it '
                            'will not follow the theme'.format(
                                name, _line(text, match.start()),
                                match.group(0)))
        names = set(X_NAME.findall(text))
        for part in WINDOW_PARTS:
            if part not in names:
                problems.append('{0}: no {1} - every window carries the theme '
                                'chip, the shrink control and close in its '
                                'header'.format(name, part))
        glyph = re.search(r'<Path\b[^>]*x:Name="ExpandGlyph"[^>]*>', text, re.S)
        if glyph is not None and 'Stroke="{DynamicResource Green}"' \
                not in glyph.group(0):
            problems.append('{0}: the reopen arrow is not drawn in the '
                            'palette green'.format(name))

    # the palettes
    try:
        theme_module = sys.modules.get('wires_theme') or \
            __import__('wires_theme')
        palettes = theme_module.PALETTES
    except Exception as error:
        problems.append('wires_theme.py: PALETTES unreadable - {0}'.format(
            error))
        return
    names = sorted(palettes.keys())
    first = set(palettes[names[0]].keys())
    for other in names[1:]:
        if set(palettes[other].keys()) != first:
            problems.append('wires_theme.py: palettes {0} and {1} carry '
                            'different keys {2} - a swap leaves a brush '
                            'behind'.format(names[0], other, sorted(
                                first ^ set(palettes[other].keys()))))
    brushes = set(BRUSH_DEF.findall(theme_text))
    for key in sorted(first - brushes):
        problems.append('{0}: no fallback brush for palette key {1}'.format(
            THEME, key))
    for key in sorted(brushes - first):
        problems.append('{0}: brush {1} is in no palette - it would never '
                        'change with the theme'.format(THEME, key))

    for module in MODULES:
        path = os.path.join(HERE, module + '.py')
        if not os.path.isfile(path):
            continue
        text = read(path)
        wanted = []
        for match in PAINT_EITHER.finditer(text):
            wanted.append((match.start(), match.group(1)))
            wanted.append((match.start(), match.group(2)))
        for match in PAINT_KEY.finditer(text):
            wanted.append((match.start(), match.group(1)))
        for match in RESOURCE_REF.finditer(text):
            wanted.append((match.start(), match.group(1)))
        for where, key in wanted:
            if key not in first:
                problems.append('{0}.py:{1}: paints with {2}, which is in no '
                                'palette'.format(module, _line(text, where),
                                                 key))
        if module in WINDOW_MODULES:
            for match in HEX.finditer(text):
                number = _line(text, match.start())
                problems.append('{0}.py:{1}: colour {2} by value - take it from '
                                'the palette with paint()'.format(
                                    module, number, match.group(0)))
            if re.search(r'\.(Background|Foreground|BorderBrush|Fill|Stroke)'
                         r'\s*=\s*(ui\.)?brush\(', text):
                problems.append('{0}.py: a brush assigned by value - a theme '
                                'swap cannot reach it'.format(module))


def _function(tree, name, owner=None):
    for node in ast.walk(tree):
        if owner is not None:
            if not (isinstance(node, ast.ClassDef) and node.name == owner):
                continue
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == name:
                    return item
            return None
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _calls(node, attr):
    found = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            func = sub.func
            if (isinstance(func, ast.Attribute) and func.attr == attr) or \
                    (isinstance(func, ast.Name) and func.id == attr):
                found.append(sub)
    return found


def _assigns_attr(node, attr):
    for sub in ast.walk(node):
        if isinstance(sub, (ast.Assign, ast.AugAssign)):
            targets = sub.targets if isinstance(sub, ast.Assign) \
                else [sub.target]
            for target in targets:
                if isinstance(target, ast.Attribute) and target.attr == attr:
                    return True
    return False


def check_drawer(problems):
    """Every window gets a drawer, the drawer is wired, and it lets go of
    its animations - the three ways shrink-to-taskbar fails silently."""
    # 1. every window built is dressed - which is what builds its drawer
    for module in WINDOW_MODULES:
        path = os.path.join(HERE, module + '.py')
        if not os.path.isfile(path) or module in ('wires_ui', 'wires_drawer'):
            continue
        try:
            tree = ast.parse(read(path))
        except SyntaxError:
            continue      # check_source has already said so
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            loads = [c for c in _calls(node, 'load_window')]
            if not loads:
                continue
            nested = [n for n in ast.walk(node) if isinstance(n, ast.FunctionDef)
                      and n is not node and _calls(n, 'load_window')]
            if nested:
                continue
            if not _calls(node, 'dress_header'):
                problems.append('{0}.py:{1}: {2} loads a window but never '
                                'dresses it - no drawer, no theme chip, no '
                                'close'.format(module, node.lineno, node.name))

    try:
        tree = ast.parse(read(os.path.join(HERE, 'wires_ui.py')))
    except SyntaxError:
        return

    dress = _function(tree, 'dress_header')
    if dress is None:
        problems.append('wires_ui.py: no dress_header')
    else:
        made = _calls(dress, 'WindowDrawer')
        wanted = set(['HeaderBar', 'Chrome', 'ShrinkButton'])
        given = set()
        for call in made:
            for sub in ast.walk(call):
                value = _string_value(sub)
                if value:
                    given.add(value)
        if not made:
            problems.append('wires_ui.py: dress_header builds no WindowDrawer')
        elif not wanted <= given:
            problems.append('wires_ui.py: the WindowDrawer is not handed {0}'
                            .format(', '.join(sorted(wanted - given))))
        chip_wired = False
        for sub in ast.walk(dress):
            if isinstance(sub, ast.AugAssign) and \
                    isinstance(sub.target, ast.Attribute) and \
                    sub.target.attr == 'Click' and \
                    isinstance(sub.value, ast.Name) and \
                    sub.value.id == '_on_theme_chip':
                chip_wired = True
        if not chip_wired:
            problems.append('wires_ui.py: the theme chip is drawn but its '
                            'Click is never wired')
    if _function(tree, 'load_window') is not None and \
            not _calls(_function(tree, 'load_window'), '_attach_theme'):
        problems.append('wires_ui.py: load_window does not merge the theme')

    try:
        tree = ast.parse(read(os.path.join(HERE, 'wires_drawer.py')))
    except SyntaxError:
        return
    init = _function(tree, '__init__', 'WindowDrawer')
    wired = False
    if init is not None:
        for sub in ast.walk(init):
            if isinstance(sub, ast.AugAssign) and \
                    isinstance(sub.target, ast.Attribute) and \
                    sub.target.attr == 'Click' and \
                    isinstance(sub.target.value, ast.Name) and \
                    sub.target.value.id == 'button':
                wired = True
    if not wired:
        problems.append('wires_drawer.py: the shrink button is never wired '
                        'to the drawer')

    land = _function(tree, '_land', 'WindowDrawer')
    if land is None:
        problems.append('wires_drawer.py: no WindowDrawer._land')
        return
    released = set()
    for call in _calls(land, 'BeginAnimation'):
        if len(call.args) == 2 and isinstance(call.args[1], ast.Constant) \
                and call.args[1].value is None and \
                isinstance(call.args[0], ast.Attribute):
            released.add(call.args[0].attr)
    for prop in ('TopProperty', 'HeightProperty'):
        if prop not in released:
            problems.append('wires_drawer.py: _land never releases the {0} '
                            'animation - the window could never be moved or '
                            'sized again'.format(prop))
    for attr in ('Top', 'Height'):
        if not _assigns_attr(land, attr):
            problems.append('wires_drawer.py: _land never writes the final '
                            '{0}'.format(attr))
    for node in ast.walk(land):
        if isinstance(node, ast.Try):
            body = ast.Module(body=node.body, type_ignores=[])
            if _calls(body, 'BeginAnimation') and \
                    (_assigns_attr(body, 'Top') or
                     _assigns_attr(body, 'Height')):
                problems.append('wires_drawer.py:{0}: releasing the animation '
                                'and writing the final numbers share one try '
                                '- a failed release would skip the numbers'
                                .format(node.lineno))
    slide = _function(tree, '_slide', 'WindowDrawer')
    if slide is not None:
        fallback = False
        for node in ast.walk(slide):
            if isinstance(node, ast.Try):
                for handler in node.handlers:
                    holder = ast.Module(body=handler.body, type_ignores=[])
                    if _calls(holder, '_land'):
                        fallback = True
        if not fallback:
            problems.append('wires_drawer.py: _slide has no fallback to land '
                            'when the animation cannot start')
    shrink = _function(tree, 'shrink', 'WindowDrawer')
    reopened = _function(tree, '_reopened', 'WindowDrawer')
    for attr in ('SizeToContent', 'MinHeight'):
        if shrink is None or not _assigns_attr(shrink, attr):
            problems.append('wires_drawer.py: shrink does not relax {0}, '
                            'which vetoes the slide'.format(attr))
        if reopened is None or not _assigns_attr(reopened, attr):
            problems.append('wires_drawer.py: {0} is never put back when the '
                            'window reopens'.format(attr))


def check_settings_used(problems):
    """Every setting on a tab must be read by something. A tick box that
    does nothing is a lie to the person ticking it."""
    try:
        core = sys.modules.get('wires_core') or __import__('wires_core')
    except Exception:
        return
    text_all = []
    for relative in MODULES + SCRIPTS:
        path = relative if relative.endswith('.py') else relative + '.py'
        path = os.path.join(HERE, path)
        if not os.path.isfile(path):
            continue
        text = read(path)
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        lines = text.splitlines(True)
        drop = set()
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                    isinstance(target, ast.Name) and
                    target.id in ('SCHEMA', 'MIGRATIONS')
                    for target in node.targets):
                drop |= set(range(node.lineno - 1,
                                  getattr(node, 'end_lineno', node.lineno)))
        text_all.append(''.join(line for index, line in enumerate(lines)
                                if index not in drop))
    text_all = ''.join(text_all)
    for row in core.SCHEMA:
        if row[2] == 'note':
            continue
        if not re.search(r"""['"]{0}['"]""".format(re.escape(row[3])),
                         text_all):
            problems.append('wires_core.py: setting "{0}" is on the {1} tab '
                            'but nothing reads it'.format(row[3], row[0]))


# ---------------------------------------------------------------------------
# cross-module calls
# ---------------------------------------------------------------------------
def _module_exports(tree):
    """Every top-level name a module offers."""
    names = set(['__version__', '__doc__', '__name__', '__file__'])
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) or isinstance(node, ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
                elif isinstance(target, (ast.Tuple, ast.List)):
                    for item in target.elts:
                        if isinstance(item, ast.Name):
                            names.add(item.id)
        elif isinstance(node, ast.For):
            if isinstance(node.target, ast.Name):
                names.add(node.target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add(alias.asname or alias.name.split('.')[0])
        elif isinstance(node, ast.Try):
            for inner in list(node.body) + list(node.orelse) + list(node.finalbody):
                if isinstance(inner, (ast.Import, ast.ImportFrom)):
                    for alias in inner.names:
                        names.add(alias.asname or alias.name.split('.')[0])
                elif isinstance(inner, (ast.FunctionDef, ast.ClassDef)):
                    names.add(inner.name)
    return names


def check_cross_module_calls(problems):
    """Every name a file reaches for on a sibling module must exist there.

    This rule exists because an edit once sliced a module from one function to
    the end of the file and replaced it, deleting the whole command layer -
    and every other check still passed, because the imports were fine, the
    syntax was fine and nothing in the test suite happened to call the
    functions that had gone. The scripts called them, and only Revit found
    out. Imports being valid says nothing about the calls being valid.
    """
    exports = {}
    for name in MODULES:
        path = os.path.join(HERE, name + '.py')
        if not os.path.isfile(path):
            continue
        try:
            exports[name] = _module_exports(ast.parse(read(path), filename=path))
        except SyntaxError:
            pass

    for relative in MODULES + SCRIPTS:
        path = relative if relative.endswith('.py') else relative + '.py'
        path = os.path.join(HERE, path)
        if not os.path.isfile(path):
            continue
        label = os.path.relpath(path, HERE)
        try:
            tree = ast.parse(read(path), filename=path)
        except SyntaxError:
            continue

        aliases = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in exports:
                        aliases[alias.asname or alias.name] = alias.name

        if not aliases:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            if not isinstance(node.value, ast.Name):
                continue
            module = aliases.get(node.value.id)
            if module is None:
                continue
            if node.attr in exports.get(module, set()):
                continue
            problems.append('{0}:{1}: {2}.{3} does not exist in {2}.py'.format(
                label, node.lineno, node.value.id, node.attr))


def check_no_duplicate_defs(problems):
    """No module may define the same top-level name twice.

    An edit that pastes a block back in without removing the old one leaves
    two copies, Python silently uses the last, and every other check passes -
    the module imports, the syntax is valid, the calls resolve. wires_core.py
    once carried four copies of the same 300-line block this way, a third of
    the file, and nothing caught it until a function was read by hand.
    """
    for name in MODULES:
        path = os.path.join(HERE, name + '.py')
        if not os.path.isfile(path):
            continue
        try:
            tree = ast.parse(read(path), filename=path)
        except SyntaxError:
            continue
        seen = {}
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                continue
            if node.name in seen:
                problems.append(
                    '{0}.py:{1}: {2} is already defined at line {3} - the '
                    'later one silently wins'.format(
                        name, node.lineno, node.name, seen[node.name]))
            else:
                seen[node.name] = node.lineno


def _bound_names(tree):
    """Every name the module binds anywhere, at any scope.

    Deliberately one flat set rather than real scope analysis. A name bound
    in some function and read in another is not an error this check wants to
    chase; a name bound *nowhere* is, and that is the one that gets through
    every other check.
    """
    names = set(dir(builtins))
    names.update(['__name__', '__file__', '__doc__', '__version__',
                  '__revit__', '__title__', '__author__',
                  '__persistentengine__', 'unicode', 'basestring', 'xrange',
                  'long', 'reduce', 'raw_input'])

    def take(node):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, (ast.Tuple, ast.List)):
            for item in node.elts:
                take(item)
        elif isinstance(node, ast.Starred):
            take(node.value)

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names.add(node.name)
            args = getattr(node, 'args', None)
            if args is not None:
                for arg in list(args.args) + list(getattr(args, 'kwonlyargs', [])):
                    names.add(getattr(arg, 'arg', getattr(arg, 'id', '')))
                for slot in ('vararg', 'kwarg'):
                    value = getattr(args, slot, None)
                    if value is not None:
                        names.add(getattr(value, 'arg', str(value)))
        elif isinstance(node, ast.Lambda):
            for arg in list(node.args.args):
                names.add(getattr(arg, 'arg', getattr(arg, 'id', '')))
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                take(target)
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            take(node.target)
        elif isinstance(node, ast.For):
            take(node.target)
        elif isinstance(node, ast.comprehension):
            take(node.target)
        elif isinstance(node, ast.withitem):
            if node.optional_vars is not None:
                take(node.optional_vars)
        elif isinstance(node, ast.ExceptHandler):
            if node.name:
                names.add(node.name if isinstance(node.name, str)
                          else getattr(node.name, 'id', ''))
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            names.update(node.names)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add(alias.asname or alias.name.split('.')[0])
    return names


def check_undefined_names(problems):
    """Flag any name a file reads that it never binds.

    `_LIVE` shipped in v3.0.0 used but never defined: a str.replace that was
    meant to insert it silently matched nothing, the edits either side of it
    applied, and the module imported fine because the name is only read inside
    a function. Every other check passed. Python only finds this when the line
    runs, which in a modeless window is after the user has pressed the button.
    """
    for relative in MODULES + SCRIPTS:
        path = relative if relative.endswith('.py') else relative + '.py'
        path = os.path.join(HERE, path)
        if not os.path.isfile(path):
            continue
        label = os.path.relpath(path, HERE)
        try:
            tree = ast.parse(read(path), filename=path)
        except SyntaxError:
            continue
        bound = _bound_names(tree)
        seen = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Name):
                continue
            if not isinstance(node.ctx, ast.Load):
                continue
            if node.id in bound or node.id in seen:
                continue
            seen.add(node.id)
            problems.append('{0}:{1}: {2} is read but never defined or '
                            'imported anywhere in this file'.format(
                                label, node.lineno, node.id))


# ---------------------------------------------------------------------------
def main():
    problems = []
    install_stub_api()
    if HERE not in sys.path:
        sys.path.insert(0, HERE)

    for name in MODULES:
        path = os.path.join(HERE, name + '.py')
        if not os.path.isfile(path):
            problems.append('{0}.py: missing'.format(name))
            continue
        _CURRENT[0] = name
        check_source(path, problems)

    for relative in SCRIPTS:
        path = os.path.join(HERE, relative)
        if not os.path.isfile(path):
            problems.append('{0}: missing'.format(relative))
            continue
        _CURRENT[0] = relative
        check_source(path, problems)

    # actually load them, which is what catches an import order dependency
    for name in MODULES:
        _CURRENT[0] = name
        try:
            __import__(name)
        except Exception as error:
            problems.append('{0}.py: would not import - {1}: {2}'.format(
                name, type(error).__name__, error))

    names = check_layouts(problems)
    check_find_names(names, problems)
    check_settings_keys(problems)
    check_cross_module_calls(problems)
    check_no_duplicate_defs(problems)
    check_undefined_names(problems)
    check_theme(problems)
    check_drawer(problems)
    check_settings_used(problems)

    if problems:
        sys.stdout.write('WIRES BENCH CHECK - {0} problem(s)\n\n'.format(
            len(problems)))
        for problem in problems:
            sys.stdout.write('  ' + problem + '\n')
        sys.stdout.write('\n')
        return 1

    sys.stdout.write('WIRES BENCH CHECK - clean.\n')
    sys.stdout.write('  {0} modules, {1} scripts, {2} layouts, {3} x:Names.\n'.format(
        len(MODULES), len(SCRIPTS), len(LAYOUTS), len(names)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
