# -*- coding: utf-8 -*-
"""Family Viewer - bench check.

Runs under plain CPython from the tool folder:

    python import_check.py
    python import_check.py --selftest

It loads every shipped module against a stub Revit and .NET API that declares
each name in the namespace the REAL API puts it in, so a mis-namespaced import
fails on the bench instead of showing up in Revit as a blank white pyRevit
window with no traceback in it.

Every rule below was proved by deliberately breaking it and confirming the
check caught it - that is what --selftest does.  A rule nobody has tested is a
rule that does not work.
"""

import os
import re
import ast
import shutil
import subprocess
import sys
import symtable
import tempfile
import types
import xml.dom.minidom

HERE = os.path.dirname(os.path.abspath(__file__))

MODULES = ['fv_clr', 'fv_core', 'theme', 'fv_ui', 'fv_model', 'fv_grid',
           'fv_ops', 'fv_dock', 'fv_excel', 'fv_batch_window',
           'fv_settings_window', 'fv_window']
LAYOUTS = ['FamilyViewer.xaml', 'FamilyViewerBody.xaml',
           'FamilyViewerSettings.xaml',
           'FamilyViewerPrompt.xaml', 'FamilyViewerBatch.xaml']
THEME = 'Theme.xaml'
TOOL_NAME = 'Family Viewer'


# ===========================================================================
# the stub .NET and Revit API
# ===========================================================================

NAMESPACES = {
    'System': ['Action', 'AppDomain', 'Array', 'Guid', 'IntPtr', 'Object', 'String',
               'TimeSpan', 'Uri', 'Convert', 'Math'],
    'System.Collections.Generic': ['List', 'Dictionary', 'HashSet'],
    'System.IO': ['File', 'MemoryStream', 'Path', 'StringReader',
                  'FileStream', 'Directory'],
    'System.IO.Compression': ['CompressionLevel', 'ZipArchive',
                              'ZipArchiveMode', 'ZipFile'],
    'System.Drawing': ['Size', 'Bitmap', 'Color', 'Rectangle'],
    'System.Drawing.Imaging': ['ImageFormat', 'PixelFormat'],
    'System.Diagnostics': ['Process', 'Stopwatch'],
    'System.Globalization': ['CultureInfo'],
    'System.Text': ['Encoding', 'StringBuilder', 'UTF8Encoding'],
    'System.Xml': ['XmlReader', 'XmlDocument', 'XmlWriter'],
    'System.Windows': [
        'Application', 'Clipboard', 'CornerRadius', 'DataTemplate',
        'DependencyObject',
        'DependencyProperty', 'DataTrigger', 'FontWeights', 'FrameworkElement',
        'FrameworkElementFactory', 'FrameworkTemplate', 'GridLength',
        'HorizontalAlignment', 'MessageBox', 'Point', 'PresentationSource',
        'Rect', 'ResourceDictionary', 'RoutedEventArgs', 'Setter',
        'SizeToContent', 'Style',
        'TextAlignment', 'TextTrimming', 'TextWrapping', 'Thickness',
        'Trigger', 'UIElement', 'VerticalAlignment', 'Visibility', 'Window',
        'WindowState', 'WindowStartupLocation', 'WindowStyle',
    ],
    'System.Windows.Automation': ['AutomationElement', 'TreeScope'],
    'System.Windows.Controls': [
        'Border', 'Button', 'Canvas', 'CheckBox', 'ColumnDefinition',
        'ComboBox', 'ComboBoxItem', 'ContentControl', 'ContextMenu', 'Control',
        'ControlTemplate', 'DataGrid', 'DataGridCell', 'DataGridCellInfo', 'DataGridLength',
        'DataGridLengthUnitType', 'DataGridRow', 'DataGridTemplateColumn',
        'DataGridTextColumn', 'DockPanel', 'Grid', 'Image', 'ItemsControl',
        'Label', 'ListBox', 'ListBoxItem', 'MenuItem', 'Orientation', 'Panel',
        'ProgressBar', 'RadioButton', 'RowDefinition', 'ScrollBarVisibility',
        'ScrollViewer', 'SelectionMode', 'Separator', 'StackPanel',
        'TabControl', 'TabItem', 'TextBlock', 'TextBox', 'ToolTip',
    ],
    'System.Windows.Controls.Primitives': [
        'DataGridColumnHeader', 'PlacementMode', 'Popup', 'RepeatButton',
        'ScrollBar', 'Thumb', 'ToggleButton', 'Track',
    ],
    'System.Windows.Data': ['Binding', 'BindingMode', 'IValueConverter',
                            'CollectionViewSource', 'RelativeSource'],
    'System.Windows.Forms': ['Control', 'Screen', 'SendKeys'],
    'System.Windows.Input': ['Cursor', 'Cursors', 'Key', 'Keyboard',
                             'ModifierKeys', 'Mouse', 'MouseButtonState'],
    'System.Windows.Interop': ['HwndSource', 'Imaging', 'WindowInteropHelper'],
    'System.Windows.Markup': ['XamlReader', 'XamlWriter'],
    'System.Windows.Media': [
        'Brush', 'BrushConverter', 'Brushes', 'Color', 'ColorConverter',
        'Geometry', 'PathGeometry', 'RectangleGeometry', 'RotateTransform',
        'ScaleTransform',
        'SolidColorBrush', 'Stretch', 'TranslateTransform', 'VisualTreeHelper',
    ],
    'System.Windows.Media.Imaging': [
        'BitmapCacheOption', 'BitmapImage', 'BitmapSource', 'PngBitmapEncoder',
    ],
    'System.Windows.Shapes': ['Ellipse', 'Line', 'Path', 'Rectangle'],
    'System.Windows.Threading': ['Dispatcher', 'DispatcherPriority',
                                 'DispatcherTimer'],
    'Microsoft.Win32': ['OpenFileDialog', 'SaveFileDialog'],
    'Autodesk.Revit.DB': [
        'BuiltInCategory', 'BuiltInParameter', 'Category', 'CategoryType',
        'Element', 'ElementId', 'ElementMulticategoryFilter', 'ElementType',
        'Family', 'FamilyInstance', 'FamilySymbol', 'FilteredElementCollector',
        'FailureProcessingResult', 'FilteredWorksetCollector',
        'IFailuresPreprocessor',
        'Parameter', 'Phase', 'StorageType', 'Transaction', 'TransactionGroup',
        'TemporaryViewMode', 'TransactionStatus', 'View', 'Workset',
        'WorksetKind',
        'WorksharingUtils',
    ],
    'Autodesk.Revit.UI': [
        'DockPosition', 'DockablePane', 'DockablePaneId', 'DockablePaneProviderData',
        'DockablePaneState', 'DockablePanes', 'IDockablePaneProvider',
        'ExternalEvent', 'IExternalEventHandler', 'TaskDialog',
        'TaskDialogCommonButtons', 'TaskDialogResult', 'UIApplication',
        'UIDocument',
    ],
}


class StubMeta(type):
    def __getattr__(cls, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return _stub_class(cls.__name__ + '.' + name)

    def __getitem__(cls, item):
        return cls

    def __call__(cls, *args, **kwargs):
        return _StubValue(cls.__name__)


class _StubValue(object):
    def __init__(self, name='stub'):
        object.__setattr__(self, '_name', name)

    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return _StubValue(self._name + '.' + name)

    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)

    def __call__(self, *args, **kwargs):
        return _StubValue(self._name + '()')

    def __iter__(self):
        return iter([])

    def __nonzero__(self):
        return True

    __bool__ = __nonzero__


_CLASSES = {}


def _stub_class(name):
    if name not in _CLASSES:
        _CLASSES[name] = StubMeta(str(name.split('.')[-1]), (object,), {})
    return _CLASSES[name]


def install_stubs():
    clr = types.ModuleType('clr')
    clr.AddReference = lambda name: None
    clr.References = []
    sys.modules['clr'] = clr

    for namespace in sorted(NAMESPACES.keys()):
        parts = namespace.split('.')
        for depth in range(1, len(parts) + 1):
            path = '.'.join(parts[:depth])
            if path not in sys.modules:
                sys.modules[path] = types.ModuleType(path)
        module = sys.modules[namespace]
        for name in NAMESPACES[namespace]:
            setattr(module, name, _stub_class(namespace + '.' + name))
        # a name this namespace does not declare must not resolve
        module.__getattr__ = _refuse(namespace)

    # link every level, so "import System.Windows.Controls as C" resolves the
    # same way "from System.Windows.Controls import X" does
    for path in sorted(sys.modules.keys()):
        if '.' not in path:
            continue
        head, _, tail = path.rpartition('.')
        if head in sys.modules and path in sys.modules:
            try:
                setattr(sys.modules[head], tail, sys.modules[path])
            except Exception:
                pass


def _refuse(namespace):
    def missing(name):
        # dunders are Python's own machinery, not .NET names
        if name.startswith('__') and name.endswith('__'):
            raise AttributeError(name)
        raise ImportError(
            'Cannot import name ' + name + ' from ' + namespace +
            ' - the real API does not put it there')
    return missing


# ===========================================================================
# reading the tool
# ===========================================================================

def sources(folder):
    found = {}
    for name in MODULES:
        path = os.path.join(folder, name + '.py')
        handle = open(path)
        try:
            found[name] = handle.read()
        finally:
            handle.close()
    return found


def read(path):
    handle = open(path)
    try:
        return handle.read()
    finally:
        handle.close()


def xaml_files(folder):
    return [name for name in sorted(os.listdir(folder))
            if name.lower().endswith('.xaml')]


# ===========================================================================
# the rules
# ===========================================================================

def rule_xaml_parses(folder, problems):
    """1. every .xaml parses as XML.  A run of hyphens in a comment shipped
    once: XML forbids '--' inside a comment, and XamlReader.Load throwing is
    the quiet way to get a blank white window.  Draw banners with '='."""
    for name in xaml_files(folder):
        path = os.path.join(folder, name)
        try:
            xml.dom.minidom.parse(path)
        except Exception as error:
            problems.append(('xaml_parses', name + ': ' + str(error)))


def rule_modules_load(folder, problems):
    """2. every module loads against the stub API, so every .NET name comes
    from the namespace the real API puts it in."""
    install_stubs()
    if folder not in sys.path:
        sys.path.insert(0, folder)
    for name in MODULES:
        for loaded in list(sys.modules.keys()):
            if loaded in MODULES:
                del sys.modules[loaded]
        try:
            __import__(name)
        except Exception as error:
            problems.append(('modules_load',
                             name + '.py: ' + type(error).__name__ + ': ' +
                             str(error)))


def rule_clr_first(folder, problems):
    """3. no module reaching into System.* or Autodesk.* without importing
    fv_clr first, or importing it too late in the file.  An IronPython engine
    can only see a .NET namespace once clr.AddReference has been called for
    the assembly holding it, and pyRevit does not preload WPF into every
    engine."""
    for name, text in sources(folder).items():
        if name == 'fv_clr':
            continue
        lines = text.splitlines()
        clr_line = None
        dotnet_line = None
        for index, line in enumerate(lines):
            stripped = line.strip()
            if re.match(r'^import\s+fv_clr\b', stripped):
                if clr_line is None:
                    clr_line = index
            if re.match(r'^(from|import)\s+(System|Autodesk|Microsoft)\b',
                        stripped):
                if dotnet_line is None:
                    dotnet_line = index
        if dotnet_line is None:
            continue
        if clr_line is None:
            problems.append(('clr_first', name + '.py reaches into .NET but '
                                                 'never imports fv_clr'))
        elif clr_line > dotnet_line:
            problems.append(('clr_first', name + '.py imports fv_clr on line ' +
                             str(clr_line + 1) + ', after a .NET import on '
                             'line ' + str(dotnet_line + 1)))


def theme_keys(folder):
    text = read(os.path.join(folder, THEME))
    return set(re.findall(r'x:Key="([^"]+)"', text))


def rule_no_static_in_layout(folder, problems):
    """4. no StaticResource in a layout file.  Theme.xaml is merged in AFTER
    XamlReader has parsed the layout, so a StaticResource fails at load.
    BasedOn is exempt - it is a plain CLR property, not a lookup at render
    time, and it only ever appears inside Theme.xaml itself."""
    for name in LAYOUTS:
        text = read(os.path.join(folder, name))
        for match in re.finditer(r'\{StaticResource\s+([^}]+)\}', text):
            before = text[max(0, match.start() - 40):match.start()]
            if 'BasedOn=' in before:
                continue
            problems.append(('no_static_in_layout',
                             name + ' uses StaticResource ' +
                             match.group(1).strip()))


def rule_dynamic_keys_exist(folder, problems):
    """5. no DynamicResource key Theme.xaml does not define."""
    known = theme_keys(folder)
    for name in xaml_files(folder):
        text = read(os.path.join(folder, name))
        for match in re.finditer(r'\{DynamicResource\s+([^}]+)\}', text):
            key = match.group(1).strip()
            if key not in known:
                problems.append(('dynamic_keys_exist',
                                 name + ' asks for ' + key +
                                 ', which Theme.xaml does not define'))


def rule_style_targettype(folder, problems):
    """6. no Style="{DynamicResource K}" on an element K's TargetType does not
    match.  WPF raises that when the style is APPLIED, so it also surfaces as
    a dead window rather than as an error anyone can read."""
    theme_text = read(os.path.join(folder, THEME))
    targets = {}
    for match in re.finditer(
            r'<Style\s+x:Key="([^"]+)"\s+TargetType="([^"]+)"', theme_text):
        targets[match.group(1)] = match.group(2).split(':')[-1]
    for name in xaml_files(folder):
        text = read(os.path.join(folder, name))
        for match in re.finditer(
                r'<(\w+)\b[^>]*?Style="\{DynamicResource\s+([^}]+)\}',
                text, re.S):
            tag, key = match.group(1), match.group(2).strip()
            wanted = targets.get(key)
            if wanted is None:
                continue
            if wanted != tag:
                problems.append((
                    'style_targettype',
                    name + ': style ' + key + ' targets ' + wanted +
                    ' but is set on a ' + tag))


def rule_findname_has_xname(folder, problems):
    """7. no FindName without a matching x:Name.

    The rule has to know about the aliases as well as the literal call.  In an
    earlier RevoBIM tool this rule matched only FindName("X") while the code
    said 'find = self.window.FindName', so the rule was doing nothing at all.
    Here both FindName('X') and the self._el('X') helper are matched."""
    names = set()
    for name in xaml_files(folder):
        text = read(os.path.join(folder, name))
        names.update(re.findall(r'x:Name="([^"]+)"', text))
    for name, text in sources(folder).items():
        asked = re.findall(r'FindName\(\s*[\'"]([^\'"]+)[\'"]\s*\)', text)
        asked += re.findall(r'\bfind\(\s*[\'"]([^\'"]+)[\'"]\s*\)', text)
        asked += re.findall(r'_el\(\s*[\'"]([^\'"]+)[\'"]\s*\)', text)
        for wanted in asked:
            if wanted not in names:
                problems.append(('findname_has_xname',
                                 name + '.py asks for "' + wanted +
                                 '", which no .xaml declares'))


def _trees(folder):
    for name, text in sorted(sources(folder).items()):
        try:
            yield name, ast.parse(text, name + '.py')
        except SyntaxError as error:
            yield name, error


def rule_no_fstrings(folder, problems):
    """8. no f-strings - IronPython 2.7 cannot parse them, and which engine
    pyRevit selects varies by release.  Read off the syntax tree, so a
    docstring that talks about them is not mistaken for one."""
    for name, tree in _trees(folder):
        if isinstance(tree, SyntaxError):
            problems.append(('no_fstrings', name + '.py will not parse: ' +
                             str(tree)))
            continue
        for node in ast.walk(tree):
            if node.__class__.__name__ == 'JoinedStr':
                problems.append(('no_fstrings', name + '.py line ' +
                                 str(getattr(node, 'lineno', 0))))


def rule_no_print(folder, problems):
    """9. no print statements - they open a pyRevit output window."""
    for name, tree in _trees(folder):
        if isinstance(tree, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                    and node.func.id == 'print':
                problems.append(('no_print', name + '.py line ' +
                                 str(getattr(node, 'lineno', 0))))


# The two functions allowed to touch .IntegerValue, and why:
#   eid_value       the guarded ElementId helper, which tries .Value first
#   workset_number  a WorksetId is NOT an ElementId.  It was not touched by the
#                   2026 removal and carries no .Value, so it has to be read
#                   this way - but it is confined to one audited function so
#                   the rule still means something everywhere else.
INTEGERVALUE_OK = ('eid_value', 'workset_number')


def rule_no_integervalue(folder, problems):
    """10. no bare ElementId.IntegerValue - removed in Revit 2026.  Allowed
    only inside the two audited helpers in INTEGERVALUE_OK."""
    for name, tree in _trees(folder):
        if isinstance(tree, SyntaxError):
            continue
        allowed = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and \
                    node.name in INTEGERVALUE_OK:
                for inner in ast.walk(node):
                    allowed.add(id(inner))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and \
                    node.attr == 'IntegerValue' and id(node) not in allowed:
                problems.append(('no_integervalue', name + '.py line ' +
                                 str(getattr(node, 'lineno', 0))))


def rule_no_system_uri(folder, problems):
    """11. no System.Uri - it moved assemblies and throws ImportError at module
    load on 2025 and later, killing the script before any of it runs.  Load
    images from bytes through a MemoryStream instead."""
    for name, tree in _trees(folder):
        if isinstance(tree, SyntaxError):
            continue
        for node in ast.walk(tree):
            line = str(getattr(node, 'lineno', 0))
            if isinstance(node, ast.ImportFrom) and \
                    (node.module or '') == 'System':
                for alias in node.names:
                    if alias.name == 'Uri':
                        problems.append(('no_system_uri',
                                         name + '.py line ' + line))
            if isinstance(node, ast.Attribute) and node.attr in ('Uri',
                                                                 'UriSource'):
                problems.append(('no_system_uri', name + '.py line ' + line))


# every route a theme key can take out of the code: the WPF call itself, the
# shared helpers that wrap it, and the window's brush lookup.  The first
# version of this rule matched only the text "SetResourceReference(", so the
# moment the streamlining pass moved those calls into fv_ui.styled() the rule
# went blind to every style key it had been guarding - and a brush() lookup of
# a key nobody defined returns None without a word.
KEY_CALLS = ('SetResourceReference', 'styled', '_styled', 'brush')
# dictionaries whose VALUES are theme keys
KEY_TABLES = ('STAGED_COLOURS',)


def _call_name(node):
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ''


def _keys_in(node):
    """Every string constant inside an expression - a key may come through a
    conditional ('AccentBlue' if family else 'FgBody')."""
    found = []
    for inner in ast.walk(node):
        if isinstance(inner, ast.Constant) and isinstance(inner.value, str):
            found.append((inner.value, getattr(inner, 'lineno', 0)))
    return found


def rule_setresourceref_keys(folder, problems):
    """12. every theme key the code asks for exists in Theme.xaml or the
    palettes."""
    known = theme_keys(folder) | set(_palette_names(folder))
    for name, text in sources(folder).items():
        try:
            tree = ast.parse(text)
        except Exception:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _call_name(node) in KEY_CALLS:
                args = list(node.args)
                if _call_name(node) in ('styled', '_styled') or \
                        _call_name(node) == 'SetResourceReference':
                    args = args[1:] if _call_name(node) != 'brush' else args
                for arg in args:
                    for key, line in _keys_in(arg):
                        if key and key[0].isupper() and key not in known:
                            problems.append((
                                'setresourceref_keys',
                                name + '.py line ' + str(line) + ' asks for ' +
                                key + ', which nothing defines'))
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
                names = [t.id for t in node.targets if isinstance(t, ast.Name)]
                if not any(one in KEY_TABLES for one in names):
                    continue
                for value in node.value.values:
                    for key, line in _keys_in(value):
                        if key not in known:
                            problems.append((
                                'setresourceref_keys',
                                name + '.py line ' + str(line) + ' colours a '
                                'source ' + key + ', which nothing defines'))


def _palette_names(folder):
    text = sources(folder).get('theme', '')
    return re.findall(r"^\s+'([A-Za-z0-9_]+)':", text, re.M)


def rule_palette_keys(folder, problems):
    """13. both palettes carry the same keys and Theme.xaml has a brush for
    every one of them, so a palette swap cannot leave a control unpainted."""
    install_stubs()
    if folder not in sys.path:
        sys.path.insert(0, folder)
    for loaded in ['theme', 'fv_clr']:
        if loaded in sys.modules:
            del sys.modules[loaded]
    palettes = __import__('theme')
    dark = set(palettes.DARK.keys())
    light = set(palettes.LIGHT.keys())
    for key in sorted(dark - light):
        problems.append(('palette_keys', 'the light palette has no ' + key))
    for key in sorted(light - dark):
        problems.append(('palette_keys', 'the dark palette has no ' + key))
    known = theme_keys(folder)
    for key in sorted(dark | light):
        if key not in known:
            problems.append(('palette_keys',
                             'Theme.xaml has no fallback brush for ' + key))
    bad_hex = re.compile(r'^#[0-9A-Fa-f]{6}$')
    for palette_name in ('DARK', 'LIGHT'):
        for key, value in getattr(palettes, palette_name).items():
            if not bad_hex.match(str(value)):
                problems.append(('palette_keys',
                                 palette_name + '.' + key + ' is not a hex '
                                 'colour: ' + str(value)))


def rule_globals_exist(folder, problems):
    """14. every global name a function reaches for exists in its module.  The
    rule that catches a function deleted by a block rewrite."""
    install_stubs()
    if folder not in sys.path:
        sys.path.insert(0, folder)
    for name, text in sources(folder).items():
        for loaded in list(sys.modules.keys()):
            if loaded in MODULES:
                del sys.modules[loaded]
        try:
            module = __import__(name)
        except Exception:
            continue
        try:
            table = symtable.symtable(text, name + '.py', 'exec')
        except Exception:
            continue
        available = set(dir(module)) | set(dir(__builtins__)) | \
            set(['__builtins__', '__file__', '__name__', '__revit__'])
        try:
            import builtins
            available |= set(dir(builtins))
        except Exception:
            pass
        for wanted in _walk_symbols(table):
            if wanted not in available:
                problems.append(('globals_exist',
                                 name + '.py reaches for "' + wanted +
                                 '", which does not exist in it'))


def _walk_symbols(table, found=None):
    if found is None:
        found = set()
    for symbol in table.get_symbols():
        try:
            if symbol.is_global() and not symbol.is_assigned():
                found.add(symbol.get_name())
        except Exception:
            continue
    for child in table.get_children():
        _walk_symbols(child, found)
    return found


def rule_tool_name_agrees(folder, problems):
    """15. the folder, the ribbon title and the window header all say the same
    thing.  pyRevit names a ribbon item after its folder, so a rename that
    misses one place leaves the old name showing somewhere."""
    folder_name = os.path.basename(folder.rstrip('\\/'))
    if not folder_name.startswith(TOOL_NAME + '.'):
        problems.append(('tool_name_agrees',
                         'the folder is "' + folder_name + '", not "' +
                         TOOL_NAME + '.pushbutton"'))
    bundle = read(os.path.join(folder, 'bundle.yaml'))
    if re.search(r'^title:\s*' + re.escape(TOOL_NAME) + r'\s*$', bundle,
                 re.M) is None:
        problems.append(('tool_name_agrees',
                         'bundle.yaml title is not "' + TOOL_NAME + '"'))
    layout = read(os.path.join(folder, 'FamilyViewer.xaml'))
    if 'Text="' + TOOL_NAME + '"' not in layout:
        problems.append(('tool_name_agrees',
                         'the window header does not say "' + TOOL_NAME + '"'))


# Which assembly holds each namespace.  A namespace is invisible to an
# IronPython engine until clr.AddReference has been called for the assembly
# holding it, and "it is in the standard library" is not a reason to skip one:
# System.IO.Compression shipped as its own assembly on .NET Framework 4.8 and
# that is what took the tool down in 1.3.0.
NAMESPACE_ASSEMBLIES = {
    'System.Windows': 'PresentationFramework',
    'System.Windows.Automation': 'UIAutomationClient',
    'System.Windows.Controls': 'PresentationFramework',
    'System.Windows.Controls.Primitives': 'PresentationFramework',
    'System.Windows.Data': 'PresentationFramework',
    'System.Windows.Documents': 'PresentationFramework',
    'System.Windows.Forms': 'System.Windows.Forms',
    'System.Windows.Input': 'PresentationCore',
    'System.Windows.Interop': 'PresentationCore',
    'System.Windows.Markup': 'PresentationFramework',
    'System.Windows.Media': 'PresentationCore',
    'System.Windows.Media.Imaging': 'PresentationCore',
    'System.Windows.Shapes': 'PresentationFramework',
    'System.Windows.Threading': 'WindowsBase',
    'System.Xml': 'System.Xml',
    'System.Drawing': 'System.Drawing',
    'System.Drawing.Imaging': 'System.Drawing',
    'System.IO.Compression': 'System.IO.Compression',
    'Autodesk.Revit.DB': 'RevitAPI',
    'Autodesk.Revit.UI': 'RevitAPIUI',
}

# namespaces that live in mscorlib / the core runtime and need no reference
CORE_NAMESPACES = set([
    'System', 'System.Collections.Generic', 'System.IO', 'System.Text',
    'System.Diagnostics', 'System.Globalization', 'System.Threading',
    'Microsoft.Win32',
])


def rule_namespace_assemblies(folder, problems):
    """18. Every namespace the tool imports has its assembly referenced in
    fv_clr.

    The clr_first rule only proves fv_clr was imported before a .NET name was
    reached for.  It does not prove fv_clr actually asks for the assembly that
    name lives in - and a namespace whose assembly was never referenced throws
    ImportError at module load, which is the tool dead before any of it runs.
    That is what shipped in 1.3.0: System.IO.Compression was imported and never
    referenced, and every rule here passed.
    """
    clr_text = sources(folder).get('fv_clr', '')
    referenced = set(re.findall(r"'([A-Za-z0-9_.]+)'", clr_text))

    for name, text in sources(folder).items():
        if name == 'fv_clr':
            continue
        try:
            tree = ast.parse(text)
        except Exception:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            namespace = node.module or ''
            root = namespace.split('.')[0]
            if root not in ('System', 'Autodesk', 'Microsoft'):
                continue
            if namespace in CORE_NAMESPACES:
                continue
            assembly = NAMESPACE_ASSEMBLIES.get(namespace)
            if assembly is None:
                problems.append((
                    'namespace_assemblies',
                    name + '.py line ' + str(node.lineno) + ': the check does '
                    'not know which assembly holds "' + namespace + '" - add '
                    'it to NAMESPACE_ASSEMBLIES or CORE_NAMESPACES'))
                continue
            if assembly not in referenced:
                problems.append((
                    'namespace_assemblies',
                    name + '.py line ' + str(node.lineno) + ': ' + namespace +
                    ' needs "' + assembly + '" referenced in fv_clr.py, and it '
                    'is not'))


# Revit's own dark theme, from the project's theme reference - sampled from
# Revit's dark Project Browser.  Written out HERE, not read from theme.py, so
# the rule cannot agree with a palette it is meant to be checking.
REVIT_DARK_REFERENCE = {
    'BarBg': '#222933', 'WindowBg': '#3C4454', 'FieldBg': '#2D3441',
    'CardBg': '#323C48', 'HoverBg': '#444E5E', 'SelBg': '#3A7392',
    'ChromeEdge': '#515C6B', 'FgBody': '#EEF0F4', 'FgMuted': '#A4AAB1',
    'AccentBlue': '#5AAEEB',
}
DARK_TEXT = ('FgBody', 'FgMuted', 'AccentBlue', 'AccentOrange', 'AccentGreen',
             'WarnRed', 'AccentTeal')
DARK_BACKS = ('WindowBg', 'CardBg', 'FieldBg', 'BarBg', 'FamilyRowBg',
              'ImportRowBg')


def _contrast(a, b):
    def lum(h):
        h = h.lstrip('#')[-6:]
        c = [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
        c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4
             for x in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    high, low = sorted([lum(a), lum(b)], reverse=True)
    return (high + 0.05) / (low + 0.05)


def rule_revit_dark(folder, problems):
    """20. The dark palette is Revit's own, everywhere it is written down.

    Three checks: theme.py's dark values against the reference; Theme.xaml's
    fallback brushes against theme.py, or the window shows the old colours for
    a moment before the palette lands; and every text colour against every
    dark background it sits on, at 4:1 - Revit's body is far lighter than the
    old near-black and drags accents under that without anybody noticing.
    """
    text = sources(folder).get('theme', '')
    try:
        tree = ast.parse(text)
    except Exception as error:
        problems.append(('revit_dark', 'theme.py will not parse: ' + str(error)))
        return
    found = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and \
                isinstance(node.targets[0], ast.Name):
            found[node.targets[0].id] = node.value
    revit = {}
    try:
        revit = ast.literal_eval(found['REVIT_DARK'])
    except Exception:
        problems.append(('revit_dark', 'theme.py has no REVIT_DARK table'))
    for key, value in REVIT_DARK_REFERENCE.items():
        if str(revit.get(key, '')).upper() != value:
            problems.append(('revit_dark', 'REVIT_DARK[' + key + '] is ' +
                             str(revit.get(key)) + ', Revit is ' + value))

    stubs = install_stubs()
    del stubs
    sys.path.insert(0, folder)
    for name in ('theme', 'fv_clr'):
        sys.modules.pop(name, None)
    try:
        import theme as live
    finally:
        sys.path.pop(0)
    dark = live.DARK
    for key, value in REVIT_DARK_REFERENCE.items():
        if str(dark.get(key, '')).upper() != value:
            problems.append(('revit_dark', 'DARK[' + key + '] is ' +
                             str(dark.get(key)) + ', Revit is ' + value))

    xaml = read(os.path.join(folder, THEME))
    for key, value in dark.items():
        match = re.search(r'x:Key="' + key + r'"\s+Color="(#[0-9A-Fa-f]+)"',
                          xaml)
        if match and match.group(1).upper() != value.upper():
            problems.append(('revit_dark', 'Theme.xaml falls back to ' +
                             match.group(1) + ' for ' + key + ', the palette '
                             'says ' + value))

    for fg in DARK_TEXT:
        for bg in DARK_BACKS:
            if fg not in dark or bg not in dark:
                continue
            ratio = _contrast(dark[fg], dark[bg])
            if ratio < 4.0:
                problems.append(('revit_dark', '%s on %s is %.2f:1, under 4:1'
                                 % (fg, bg, ratio)))


def rule_drawer_wired(folder, problems):
    """21. Every window shrinks to the taskbar, and the shrink actually works.

    The project standard: every window a tool opens carries a shrink button.
    Three ways that goes wrong silently - a window built without one, a button
    drawn and never handed to a WindowDrawer (so it does nothing at all), and
    an animation never released (it holds its end value and outranks every
    later assignment, so the window can never be moved or resized again).
    """
    shrink_names = {}
    for name in xaml_files(folder):
        text = read(os.path.join(folder, name))
        if not re.search(r'<Window\b', text):
            continue
        found = re.findall(
            r'<Button[^>]*x:Name="([^"]+)"[^>]*Style="\{DynamicResource '
            r'ShrinkBtn\}"', text)
        found += re.findall(
            r'<Button[^>]*Style="\{DynamicResource ShrinkBtn\}"[^>]*'
            r'x:Name="([^"]+)"', text)
        if not found:
            problems.append(('drawer_wired', name + ' is a window with no '
                             'shrink-to-taskbar button'))
        for button in found:
            shrink_names[button] = name

    wired = set()
    for name, text in sources(folder).items():
        try:
            tree = ast.parse(text)
        except Exception:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and \
                    _call_name(node) == 'WindowDrawer':
                for arg in list(node.args) + [k.value for k in node.keywords]:
                    for key, line in _keys_in(arg):
                        wired.add(key)
        if 'BeginAnimation(' in text:
            if not re.search(r'BeginAnimation\([^)]*None\s*\)', text):
                problems.append(('drawer_wired', name + '.py starts an '
                                 'animation and never releases it'))
    for button, layout in sorted(shrink_names.items()):
        if button not in wired:
            problems.append(('drawer_wired', layout + ' draws ' + button +
                             ' but nothing hands it to a WindowDrawer, so it '
                             'does nothing'))


def rule_defined_once(folder, problems):
    """19. Nothing is defined twice in one scope.

    Python keeps the LAST definition without a word, so a method rewritten
    lower down a class while the old copy stays above it ships the old
    behaviour's tests passing and the new one silently in charge - or the other
    way round.  A streamlining pass that moves code about is exactly when that
    happens.
    """
    for name, text in sources(folder).items():
        try:
            tree = ast.parse(text)
        except Exception:
            continue

        def scan(body, where):
            seen = {}
            for node in body:
                if not isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                    continue
                if node.name in seen:
                    problems.append((
                        'defined_once',
                        name + '.py: ' + where + node.name + ' is defined on '
                        'line ' + str(seen[node.name]) + ' and again on line ' +
                        str(node.lineno) + ' - the second one silently wins'))
                seen[node.name] = node.lineno
                if isinstance(node, ast.ClassDef):
                    scan(node.body, node.name + '.')

        scan(tree.body, '')


def rule_excel_inline_text(folder, problems):
    """17. Every exported cell is written as inline text.

    A shared string table would be smaller, but Excel reading a cell back as a
    number is how a round trip quietly corrupts a schedule: a type mark of
    "007" comes back as 7, and the leading zeros are gone before anybody looks.
    The rule is cheap and the failure is silent, which is exactly the kind
    worth a bench check.
    """
    text = sources(folder).get('fv_excel', '')
    if not text:
        return
    if 't="inlineStr"' not in text:
        problems.append(('excel_inline_text',
                         'fv_excel.py no longer writes cells as inline text'))
    for marker in ('t="n"', 'sharedStrings.xml"'):
        if marker in text and marker == 't="n"':
            problems.append((
                'excel_inline_text',
                'fv_excel.py writes a numeric cell (' + marker + '), which is '
                'how a leading zero is lost on the way back'))


def rule_late_imports_namespaced(folder, problems):
    """16. A .NET import inside a function is checked against the same table as
    a top-level one.

    `rule_modules_load` only ever executes what runs at import time, so an
    import sitting inside a function - and worse, inside a try/except, which is
    where the awkward ones live - is never reached by it.  A mis-namespaced one
    there does not blow up loudly; it is quietly swallowed and the feature just
    never works, which is harder to find than a blank window.  This walks the
    AST instead of running anything.
    """
    for name, text in sources(folder).items():
        try:
            tree = ast.parse(text)
        except Exception as error:
            problems.append(('late_imports_namespaced',
                             name + '.py will not parse: ' + str(error)))
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if node.col_offset == 0:
                continue          # top level, and rule_modules_load ran it
            namespace = node.module or ''
            if not namespace.split('.')[0] in ('System', 'Autodesk',
                                               'Microsoft'):
                continue
            declared = NAMESPACES.get(namespace)
            if declared is None:
                problems.append((
                    'late_imports_namespaced',
                    name + '.py line ' + str(node.lineno) + ': the check has '
                    'no name list for "' + namespace + '", so nothing is '
                    'verifying it - add it to NAMESPACES'))
                continue
            for alias in node.names:
                if alias.name not in declared:
                    problems.append((
                        'late_imports_namespaced',
                        name + '.py line ' + str(node.lineno) + ': ' +
                        alias.name + ' is not in ' + namespace))


RULES = [
    ('xaml_parses', rule_xaml_parses),
    ('modules_load', rule_modules_load),
    ('clr_first', rule_clr_first),
    ('late_imports_namespaced', rule_late_imports_namespaced),
    ('excel_inline_text', rule_excel_inline_text),
    ('namespace_assemblies', rule_namespace_assemblies),
    ('defined_once', rule_defined_once),
    ('revit_dark', rule_revit_dark),
    ('drawer_wired', rule_drawer_wired),
    ('no_static_in_layout', rule_no_static_in_layout),
    ('dynamic_keys_exist', rule_dynamic_keys_exist),
    ('style_targettype', rule_style_targettype),
    ('findname_has_xname', rule_findname_has_xname),
    ('no_fstrings', rule_no_fstrings),
    ('no_print', rule_no_print),
    ('no_integervalue', rule_no_integervalue),
    ('no_system_uri', rule_no_system_uri),
    ('setresourceref_keys', rule_setresourceref_keys),
    ('palette_keys', rule_palette_keys),
    ('globals_exist', rule_globals_exist),
    ('tool_name_agrees', rule_tool_name_agrees),
]


def run(folder):
    problems = []
    for name, rule in RULES:
        try:
            rule(folder, problems)
        except Exception as error:
            problems.append((name, 'the rule itself failed: ' +
                             type(error).__name__ + ': ' + str(error)))
    return problems


def main():
    problems = run(HERE)
    if not problems:
        sys.stdout.write('import_check: all ' + str(len(RULES)) +
                         ' rules pass.\n')
        return 0
    for rule, detail in problems:
        sys.stdout.write('FAIL  ' + rule + '  ' + detail + '\n')
    sys.stdout.write('\nimport_check: ' + str(len(problems)) + ' problems.\n')
    return 1


# ===========================================================================
# selftest: break each rule on purpose and confirm the check catches it
# ===========================================================================

BREAKAGES = [
    ('xaml_parses', 'Theme.xaml',
     lambda text: text.replace('<ResourceDictionary',
                               '<!-- ---- banner ---- -->\n<ResourceDictionary', 1)),
    ('modules_load', 'fv_grid.py',
     lambda text: text.replace('from System.Windows.Data import Binding',
                               'from System.Windows.Controls import Binding')),
    # the breakage has to move fv_clr BELOW a .NET import, not merely move it:
    # the first version of this test put it above one and the rule rightly did
    # not fire, which looked like the rule being broken
    # a .NET import inside a function, in the wrong namespace: never executed
    # by rule_modules_load, and swallowed by the try/except round it in Revit
    # a window drawn with no shrink button
    ('drawer_wired', 'FamilyViewerSettings.xaml',
     lambda text: text.replace('<Button x:Name="SetShrink" Content="" '
                               'Style="{DynamicResource ShrinkBtn}"/>', '', 1)),
    # a shrink button drawn and never wired
    ('drawer_wired', 'fv_batch_window.py',
     lambda text: text.replace("find('BatchShrink')", "None", 1)),
    # an animation that is never released
    ('drawer_wired', 'fv_ui.py',
     lambda text: text.replace("def own_dialog(dialog, owner):",
                               "def _held(window):\n"
                               "    window.BeginAnimation(Window.TopProperty, "
                               "make_slide())\n\n\n"
                               "def own_dialog(dialog, owner):", 1)),
    # a style key nobody defines, through the shared helper - the route the
    # old text-matching rule went blind to
    ('setresourceref_keys', 'fv_window.py',
     lambda text: text.replace("fv_ui.styled(", "fv_ui.styled(None, 'NoSuchStyle') or fv_ui.styled(", 1)),
    # a brush lookup of a key nobody defines, which returns None silently
    ('setresourceref_keys', 'fv_window.py',
     lambda text: text.replace("self.brush('ImportRowBg')", "self.brush('ImportRowBgg')", 1)),
    # a staged source coloured with a key nobody defines
    ('setresourceref_keys', 'fv_window.py',
     lambda text: text.replace("'import': 'AccentTeal'}", "'import': 'AccentTeel'}", 1)),
    # the dark body put back to the old near-black
    ('revit_dark', 'theme.py',
     lambda text: text.replace("'WindowBg': '#3C4454',", "'WindowBg': '#232326',", 1)),
    # a fallback brush left on the old colour
    ('revit_dark', 'Theme.xaml',
     lambda text: text.replace('x:Key="WindowBg"         Color="#3C4454"',
                               'x:Key="WindowBg"         Color="#232326"', 1)),
    # an accent that reads on near-black and not on Revit's body
    ('revit_dark', 'theme.py',
     lambda text: text.replace("'WarnRed':          '#FA928E',",
                               "'WarnRed':          '#D9534F',", 1)),
    # a method written out a second time further down its class
    ('defined_once', 'fv_window.py',
     lambda text: text.replace('    def _filter_state(self):',
                               '    def _filter_state(self):\n'
                               '        return {}\n\n'
                               '    def _filter_state(self):', 1)),
    # a namespace whose assembly fv_clr never asks for: ImportError at module
    # load, and the tool is dead before any of it runs
    ('namespace_assemblies', 'fv_clr.py',
     lambda text: text.replace("    'System.IO.Compression',\n", '', 1)),
    # the Excel round trip: every value goes out as inline text, so a type
    # mark of "007" does not come back as the number seven
    ('excel_inline_text', 'fv_excel.py',
     lambda text: text.replace('t="inlineStr"><is><t xml:space="preserve">',
                               't="n"><v>', 1)),
    ('late_imports_namespaced', 'fv_dock.py',
     lambda text: text.replace('from Autodesk.Revit.UI import DockablePane, DockablePaneId',
                               'from Autodesk.Revit.DB import DockablePane, DockablePaneId', 1)),
    ('clr_first', 'fv_ui.py',
     lambda text: text.replace(
         'import fv_clr  # noqa: F401  - must be first\n', '')
     .replace('from System.Xml import XmlReader\n',
              'from System.Xml import XmlReader\nimport fv_clr\n', 1)),
    ('no_static_in_layout', 'FamilyViewerBody.xaml',
     lambda text: text.replace('Style="{DynamicResource ThemedGrid}"',
                               'Style="{StaticResource ThemedGrid}"')),
    ('dynamic_keys_exist', 'FamilyViewer.xaml',
     lambda text: text.replace('{DynamicResource WindowBg}',
                               '{DynamicResource NoSuchBrush}', 1)),
    ('style_targettype', 'FamilyViewerBody.xaml',
     lambda text: text.replace('<TextBlock x:Name="StatusText" FontSize="12"',
                               '<TextBlock x:Name="StatusText" '
                               'Style="{DynamicResource ThemedGrid}" FontSize="12"')),
    ('findname_has_xname', 'fv_window.py',
     lambda text: text.replace("self.grid = self._el('FamilyGrid')",
                               "self.grid = self._el('NoSuchElement')")),
    ('no_fstrings', 'fv_core.py',
     lambda text: text.replace('def natural_key(text):',
                               'def natural_key(text):\n    _ = f"{text}"')),
    ('no_print', 'fv_core.py',
     lambda text: text.replace('def natural_key(text):',
                               'def natural_key(text):\n    print("hello")')),
    ('no_integervalue', 'fv_model.py',
     lambda text: text.replace('def category_of(element):',
                               'def category_of(element):\n'
                               '    _ = element.Id.IntegerValue')),
    ('no_system_uri', 'fv_ui.py',
     lambda text: text.replace('from System.IO import',
                               'from System import Uri\nfrom System.IO import')),
    ('setresourceref_keys', 'fv_grid.py',
     lambda text: text.replace("_styled(ticks, 'ThemedList')",
                               "ticks.SetResourceReference(0, 'NoSuchStyle')")),
    ('palette_keys', 'theme.py',
     lambda text: text.replace("    'WarnRed':          '#B23B37',\n", '')),
    ('globals_exist', 'fv_core.py',
     lambda text: text.replace('def natural_key(text):',
                               'def natural_key(text):\n'
                               '    _ = a_function_that_does_not_exist()')),
    ('tool_name_agrees', 'bundle.yaml',
     lambda text: text.replace('title: Family Viewer', 'title: Fmly Viewr')),
]


def selftest():
    clean = run(HERE)
    if clean:
        sys.stdout.write('selftest cannot run: the tool does not pass '
                         'import_check yet.\n')
        for rule, detail in clean:
            sys.stdout.write('  FAIL  ' + rule + '  ' + detail + '\n')
        return 1

    failures = 0
    for rule_name, filename, break_it in BREAKAGES:
        folder = tempfile.mkdtemp(prefix='fv_selftest_')
        target = os.path.join(folder, TOOL_NAME + '.pushbutton')
        shutil.copytree(HERE, target,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        path = os.path.join(target, filename)
        original = read(path)
        broken = break_it(original)
        if broken == original:
            sys.stdout.write('BROKEN TEST  ' + rule_name +
                             ': the breakage changed nothing in ' +
                             filename + '\n')
            failures += 1
            shutil.rmtree(folder, ignore_errors=True)
            continue
        handle = open(path, 'w')
        try:
            handle.write(broken)
        finally:
            handle.close()

        found = _run_in_child(target)
        caught = rule_name in found
        sys.stdout.write(('  caught  ' if caught else '  MISSED  ') +
                         rule_name + '  (broke ' + filename + ')\n')
        if not caught:
            failures += 1
            sys.stdout.write('           rules that did fire: ' +
                             (', '.join(sorted(set(found))) or 'none') + '\n')
        shutil.rmtree(folder, ignore_errors=True)

    if failures:
        sys.stdout.write('\nselftest: ' + str(failures) + ' of ' +
                         str(len(BREAKAGES)) + ' breakages went unnoticed.\n')
        return 1
    sys.stdout.write('\nselftest: all ' + str(len(BREAKAGES)) +
                     ' breakages were caught.\n')
    return 0


def _run_in_child(folder):
    """Each breakage runs in its own interpreter: the stub API and the
    imported modules are global state, and a rule that has already imported a
    module would otherwise judge the wrong copy."""
    script = (
        'import sys, json\n'
        'sys.path.insert(0, ' + repr(folder) + ')\n'
        'import import_check\n'
        'print(json.dumps([rule for rule, detail in '
        'import_check.run(' + repr(folder) + ')]))\n'
    )
    try:
        output = subprocess.check_output([sys.executable, '-c', script],
                                         stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as error:
        output = error.output
    text = output.decode('utf-8', 'replace').strip().splitlines()
    for line in reversed(text):
        line = line.strip()
        if line.startswith('['):
            try:
                import json
                return json.loads(line)
            except Exception:
                continue
    return []


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(selftest())
    sys.exit(main())
