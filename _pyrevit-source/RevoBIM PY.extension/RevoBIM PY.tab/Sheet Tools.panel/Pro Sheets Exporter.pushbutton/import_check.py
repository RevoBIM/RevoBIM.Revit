# -*- coding: utf-8 -*-
"""Bench check for Pro Sheets Exporter. Run it from this folder:

    python import_check.py            run every rule
    python import_check.py --selftest prove every rule by breaking it

This tool is too big to click through by hand, and the failures that matter
most are the silent ones: a blank white pyRevit window, a dead handler, a
style that never applies. Every rule here exists because that class of
failure has actually shipped in this extension before.

**Every rule is proved by deliberately breaking it.** ``--selftest`` copies
the tool to a temporary folder, breaks one thing at a time, and confirms the
matching rule fires. A rule nobody has tested is a rule that does not work.
"""

import ast
import os
import re
import shutil
import zipfile
import sys
import tempfile
import types
import xml.dom.minidom


HERE = os.path.dirname(os.path.abspath(__file__))

MODULES = [
    'ps_version', 'ps_refs', 'theme', 'ps_naming', 'ps_paths', 'ps_config',
    'ps_model', 'ps_register', 'ps_export', 'ps_context', 'ps_ui',
    'ps_xlsx', 'ps_regexport', 'ps_revdata', 'ps_revisions',
    'ps_namewin', 'ps_orderwin', 'ps_pickwin', 'ps_setupwin', 'ps_tokenwin',
    'ps_revaddwin', 'ps_revcolwin', 'ps_revsetwin', 'ps_revswapwin',
    'ps_revwin',
    'ps_ramp', 'ps_regview', 'ps_window', 'ps_express',
]

LAYOUTS = ['ProSheets.xaml', 'ProSheetsCustomName.xaml',
           'ProSheetsOrder.xaml', 'ProSheetsPrompt.xaml',
           'ProSheetsTokens.xaml', 'ProSheetsPick.xaml',
           'ProSheetsSetup.xaml', 'ProSheetsRevisions.xaml',
           'ProSheetsRevColumn.xaml', 'ProSheetsRevSettings.xaml',
           'ProSheetsRevSwap.xaml', 'ProSheetsRevAdd.xaml']

THEME_FILE = 'Theme.xaml'


# ==========================================================================
# results
# ==========================================================================

class Failures(object):

    def __init__(self):
        self.items = []

    def add(self, rule, text):
        self.items.append((rule, text))

    def rules_hit(self):
        return set([rule for rule, _text in self.items])

    def __len__(self):
        return len(self.items)


def read(path):
    handle = open(path, 'rb')
    try:
        raw = handle.read()
    finally:
        handle.close()
    try:
        return raw.decode('utf-8')
    except Exception:
        return raw.decode('latin-1')


def source_files(root):
    return [os.path.join(root, name + '.py') for name in MODULES
            if os.path.isfile(os.path.join(root, name + '.py'))]


# ==========================================================================
# the stub .NET and Revit API
#
# Each namespace declares the names it really provides. A name imported from
# the wrong namespace is not in the list and the import fails here, on the
# bench, instead of at the user's desk as a blank window.
# ==========================================================================

NAMESPACES = {
    'clr': ['AddReference', 'GetClrType', 'Reference'],
    'System': ['Action', 'AppDomain', 'Array', 'Boolean', 'DateTime', 'Guid',
               'Environment',
               'Func', 'Int32', 'Int64', 'Object', 'String', 'Double',
               'Tuple',
               'EventHandler', 'TimeSpan'],
    'System.Collections.Generic': ['List', 'Dictionary', 'IList'],
    'System.Data': ['DataTable', 'DataView', 'DataRow', 'DataRowView',
                    'DataColumn'],
    'System.Diagnostics': ['Process', 'Stopwatch'],
    'System.Drawing.Printing': ['PrinterSettings', 'PrintDocument'],
    'System.Printing': ['LocalPrintServer', 'PrintQueue'],
    'System.IO': ['File', 'Directory', 'FileMode', 'FileStream',
                  'MemoryStream', 'Path'],
    'System.IO.Compression': ['ZipArchive', 'ZipArchiveMode'],
    'System.Text': ['UTF8Encoding', 'Encoding'],
    'System.Windows': ['Application', 'Clipboard', 'CornerRadius',
                       'WindowStartupLocation',
                       'FontWeights', 'FrameworkElement', 'GridLength',
                       'GridUnitType', 'HorizontalAlignment', 'Point',
                       'TextTrimming', 'TextWrapping',
                       'PresentationSource', 'ResourceDictionary',
                       'SystemParameters', 'Thickness', 'Visibility',
                       'VerticalAlignment', 'Window', 'WindowState',
                       'MessageBox', 'DependencyProperty', 'RoutedEventArgs',
                       'Size', 'SystemColors'],
    'System.Windows.Controls': ['Border', 'Button', 'Canvas', 'CheckBox',
                                'ColumnDefinition',
                                'DataGridCell', 'DataGridCellInfo',
                                'ComboBox',
                                'ContentPresenter', 'ContextMenu', 'DataGrid',
                                'DataGridLength', 'DataGridLengthUnitType',
                                'DataGridRow', 'DataGridTextColumn', 'Grid',
                                'Image', 'Label', 'ItemsControl', 'ListBox', 'ListBoxItem',
                                'MenuItem', 'SelectionMode',
                                'DataGridTemplateColumn', 'Orientation',
                                'ProgressBar', 'RadioButton',
                                'ScrollBarVisibility', 'ScrollViewer',
                                'Separator',
                                'StackPanel', 'TextBlock', 'TextBox',
                                'ToolTip', 'WrapPanel'],
    'System.Windows.Controls.Primitives': ['DataGridColumnHeader', 'Thumb',
                                           'PlacementMode', 'Popup',
                                           'RepeatButton'],
    'System.Windows.Data': ['Binding', 'IValueConverter', 'BindingMode'],
    'System.Windows.Forms': ['DialogResult', 'FolderBrowserDialog',
                             'OpenFileDialog', 'SaveFileDialog', 'Screen'],
    'System.Windows.Input': ['Key', 'Keyboard', 'ModifierKeys', 'Cursors'],
    'System.Windows.Interop': ['WindowInteropHelper', 'HwndSource'],
    'System.Windows.Markup': ['XamlReader', 'XamlWriter'],
    'System.Windows.Media': ['Brush', 'Brushes', 'Color', 'ColorConverter',
                             'Brushes', 'FontFamily', 'RotateTransform',
                             'ScaleTransform',
                             'SolidColorBrush', 'Stretch',
                             'VisualTreeHelper'],
    'System.Windows.Media.Imaging': ['BitmapCacheOption', 'BitmapImage',
                                     'BitmapSource'],
    'System.Windows.Threading': ['DispatcherPriority', 'DispatcherTimer'],
    'System.Xml': ['XmlReader', 'XmlDocument'],
    'Autodesk': ['Revit'],
    'Autodesk.Revit': ['DB', 'UI', 'ApplicationServices'],
    'Autodesk.Revit.DB': [
        'ACADVersion', 'BuiltInCategory', 'BuiltInParameter', 'ColorDepthType',
        'DWGExportOptions', 'Element', 'ElementId', 'ExportDWGSettings',
        'ExportPaperFormat', 'FilteredElementCollector', 'HiddenLineViewsType',
        'IFailuresPreprocessor', 'MarginType', 'PDFExportOptions',
        'PageOrientationType', 'PaperPlacementType', 'PrintRange',
        'RasterQualityType', 'Revision', 'StorageType', 'Transaction',
        'RevisionCloud', 'RevisionNumbering', 'RevisionNumberingSequence',
        'RevisionSettings', 'RevisionVisibility', 'SpecTypeId',
        'View', 'ViewSet', 'ViewSheet', 'ViewSheetSet', 'ViewType',
        'Viewport', 'ZoomType', 'PDFExportQualityType',
        'BrowserOrganization',
    ],
    'Autodesk.Revit.DB.ExtensibleStorage': ['AccessLevel', 'DataStorage',
                                            'Entity', 'Schema',
                                            'SchemaBuilder'],
    'Autodesk.Revit.UI': ['ExternalEvent', 'IExternalEventHandler',
                          'PostableCommand', 'RevitCommandId',
                          'TaskDialog', 'UIApplication', 'UIDocument',
                          'UITheme', 'UIThemeManager',
                          # Revit 2025 and up only. They are in the stub so
                          # the bench can load the module; the version gate
                          # in ps_context is what keeps them off 2024.
                          'CommandMenuItem', 'ContextMenu',
                          'IContextMenuCreator', 'IExternalCommand',
                          'UIControlledApplication'],
    'revobim': ['egg'],
    'revobim.egg': ['egg_hook'],
    'revobim.egg.egg_hook': ['attach'],
}

# Names this tool must never touch, whatever namespace they live in.
BANNED_NAMES = {
    'Uri': ('System.Uri moved assemblies: "from System import Uri" throws '
            'ImportError at module load on Revit 2025 and later, killing the '
            'script before any of it runs. Load images from bytes instead.'),
}


class StubMeta(type):

    def __getattr__(cls, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return make_stub('{0}.{1}'.format(cls.__name__, name))

    def __iter__(cls):
        return iter([])


StubBase = StubMeta('StubBase', (object,), {})


def make_stub(name):
    return StubMeta(str(name), (StubBase,), {})


class StubModule(types.ModuleType):

    def __init__(self, name, allowed):
        types.ModuleType.__init__(self, name)
        self._allowed = set(allowed)
        self.__path__ = []

    def __getattr__(self, item):
        if item.startswith('__'):
            raise AttributeError(item)
        if item in BANNED_NAMES:
            raise ImportError(
                'cannot import name {0}: {1}'.format(item, BANNED_NAMES[item]))
        if item not in self._allowed:
            raise ImportError(
                'cannot import name {0} from {1}: it does not live in that '
                'namespace'.format(item, self.__name__))
        return make_stub(item)


def install_stubs():
    """Put the stub namespaces into sys.modules, keeping what was there."""
    saved = {}
    for name, allowed in NAMESPACES.items():
        saved[name] = sys.modules.get(name)
        sys.modules[name] = StubModule(name, allowed)
    return saved


def remove_stubs(saved):
    for name, previous in saved.items():
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous


# ==========================================================================
# rule 1 : every .xaml parses as XML
# ==========================================================================

def rule_xaml_parses(root, fail):
    for name in LAYOUTS + [THEME_FILE]:
        path = os.path.join(root, name)
        if not os.path.isfile(path):
            fail.add('xaml_parses', '{0} is missing'.format(name))
            continue
        try:
            xml.dom.minidom.parse(path)
        except Exception as err:
            fail.add('xaml_parses',
                     '{0} will not parse as XML: {1}'.format(name, err))


# ==========================================================================
# rule 2 : script.py stays a thin loader
# ==========================================================================

SAFE_TOP_IMPORTS = set(['os', 'sys', 'traceback'])


def rule_thin_loader(root, fail):
    path = os.path.join(root, 'script.py')
    if not os.path.isfile(path):
        fail.add('thin_loader', 'script.py is missing')
        return
    tree = ast.parse(read(path))
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split('.')[0] not in SAFE_TOP_IMPORTS:
                    fail.add('thin_loader',
                             'script.py imports "{0}" at module level; it has '
                             'no runtime left to report a failure in it'
                             .format(alias.name))
        elif isinstance(node, ast.ImportFrom):
            root_name = (node.module or '').split('.')[0]
            if root_name not in SAFE_TOP_IMPORTS:
                fail.add('thin_loader',
                         'script.py imports from "{0}" at module level'
                         .format(node.module))
    if '__persistentengine__' not in read(path):
        fail.add('thin_loader',
                 'script.py does not set __persistentengine__; a modeless '
                 'window opens with every handler in it dead')


# ==========================================================================
# rule 3 : ps_refs is imported first, before any System.* or Autodesk.*
# ==========================================================================

def rule_refs_first(root, fail):
    for path in source_files(root):
        name = os.path.basename(path)
        if name in ('ps_refs.py', 'ps_version.py', 'ps_naming.py',
                    'ps_paths.py'):
            continue
        tree = ast.parse(read(path))
        refs_line = None
        first_dotnet = None
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == 'ps_refs' and refs_line is None:
                        refs_line = node.lineno
                    if (alias.name.split('.')[0] in ('System', 'Autodesk')
                            and first_dotnet is None):
                        first_dotnet = node.lineno
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ''
                if (module.split('.')[0] in ('System', 'Autodesk')
                        and first_dotnet is None):
                    first_dotnet = node.lineno
        if first_dotnet is None:
            continue
        if refs_line is None:
            fail.add('refs_first',
                     '{0} reaches into System/Autodesk without importing '
                     'ps_refs at all'.format(name))
        elif refs_line > first_dotnet:
            fail.add('refs_first',
                     '{0} imports ps_refs on line {1}, after the .NET import '
                     'on line {2}: the reference has to win'
                     .format(name, refs_line, first_dotnet))


# ==========================================================================
# rule 3b : every namespace imported has its assembly referenced
#
# The stub API cannot catch this, because under CPython a namespace either
# resolves or it does not - there is no assembly to reference. Under
# IronPython a namespace is invisible until clr.AddReference has been called
# for the assembly holding it, and the failure reads as
# "ImportError: No module named Data", which names the namespace rather than
# the missing reference and sends you looking in the wrong place.
#
# System.Data is a separate assembly from System. So are System.Xml,
# System.Drawing and System.Windows.Forms. This mapping is the whole rule.
# ==========================================================================

NAMESPACE_ASSEMBLIES = {
    'System': ['mscorlib', 'System'],
    'System.Collections': ['mscorlib'],
    'System.Collections.Generic': ['mscorlib'],
    'System.Data': ['System.Data'],
    'System.Diagnostics': ['System', 'mscorlib'],
    'System.Drawing': ['System.Drawing'],
    'System.Drawing.Printing': ['System.Drawing'],
    'System.IO': ['mscorlib'],
    'System.IO.Compression': ['System.IO.Compression'],
    'System.Printing': ['System.Printing', 'ReachFramework'],
    'System.Text': ['mscorlib'],
    'System.Threading': ['mscorlib'],
    'System.Windows': ['PresentationFramework', 'PresentationCore',
                       'WindowsBase'],
    'System.Windows.Controls': ['PresentationFramework'],
    'System.Windows.Controls.Primitives': ['PresentationFramework'],
    'System.Windows.Data': ['PresentationFramework'],
    'System.Windows.Forms': ['System.Windows.Forms'],
    'System.Windows.Input': ['PresentationCore'],
    'System.Windows.Interop': ['PresentationCore'],
    'System.Windows.Markup': ['PresentationFramework', 'System.Xaml'],
    'System.Windows.Media': ['PresentationCore'],
    'System.Windows.Media.Imaging': ['PresentationCore'],
    'System.Windows.Threading': ['WindowsBase'],
    'System.Xml': ['System.Xml'],
    'Autodesk.Revit': ['RevitAPI'],
    'Autodesk.Revit.ApplicationServices': ['RevitAPI'],
    'Autodesk.Revit.DB': ['RevitAPI'],
    'Autodesk.Revit.DB.ExtensibleStorage': ['RevitAPI'],
    'Autodesk.Revit.UI': ['RevitAPIUI'],
}


def referenced_assemblies(root):
    """The assembly list ps_refs actually asks for, read out of the source."""
    path = os.path.join(root, 'ps_refs.py')
    if not os.path.isfile(path):
        return set()
    tree = ast.parse(read(path))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if getattr(target, 'id', None) != '_ASSEMBLIES':
                continue
            if not isinstance(node.value, ast.List):
                continue
            found = set()
            for item in node.value.elts:
                value = getattr(item, 's', getattr(item, 'value', None))
                if isinstance(value, str):
                    found.add(value)
            return found
    return set()


def imported_namespaces(root):
    """Every .NET namespace the tool imports from, with where it happens."""
    found = {}
    for path in source_files(root) + [os.path.join(root, 'script.py')]:
        if not os.path.isfile(path):
            continue
        base = os.path.basename(path)
        tree = ast.parse(read(path))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.ImportFrom):
                names.append(node.module or '')
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    names.append(alias.name)
            for name in names:
                if name.split('.')[0] not in ('System', 'Autodesk'):
                    continue
                found.setdefault(name, []).append(
                    '{0} line {1}'.format(base, node.lineno))
    return found


def rule_assemblies_referenced(root, fail):
    have = referenced_assemblies(root)
    for namespace, places in sorted(imported_namespaces(root).items()):
        wanted = NAMESPACE_ASSEMBLIES.get(namespace)
        if wanted is None:
            fail.add('assemblies_referenced',
                     '{0} is imported ({1}) but import_check does not know '
                     'which assembly provides it; add it to '
                     'NAMESPACE_ASSEMBLIES'.format(namespace, places[0]))
            continue
        if not [name for name in wanted if name in have]:
            fail.add('assemblies_referenced',
                     '{0} is imported ({1}) but ps_refs references none of '
                     '{2}; under IronPython that namespace does not exist '
                     'and the import fails with "No module named {3}"'
                     .format(namespace, places[0], ', '.join(wanted),
                             namespace.split('.')[-1]))


# ==========================================================================
# rule 4 : layouts use DynamicResource only, and every key exists
# ==========================================================================

KEY_PATTERN = re.compile(r'\{DynamicResource\s+([A-Za-z0-9_.]+)\s*\}')
STATIC_PATTERN = re.compile(r'\{StaticResource\s+([A-Za-z0-9_.]+)\s*\}')


def theme_keys(root):
    text = read(os.path.join(root, THEME_FILE))
    return set(re.findall(r'x:Key="([^"]+)"', text))


def rule_resources(root, fail):
    known = theme_keys(root)
    for name in LAYOUTS:
        path = os.path.join(root, name)
        if not os.path.isfile(path):
            continue
        text = read(path)
        for key in STATIC_PATTERN.findall(text):
            fail.add('resources',
                     '{0} uses StaticResource "{1}"; Theme.xaml is merged in '
                     'after XamlReader parses the layout, so it fails at load'
                     .format(name, key))
        for key in KEY_PATTERN.findall(text):
            if key not in known:
                fail.add('resources',
                         '{0} asks for "{1}", which Theme.xaml does not define'
                         .format(name, key))
    # Theme.xaml referring to its own keys must find them too.
    text = read(os.path.join(root, THEME_FILE))
    for key in KEY_PATTERN.findall(text):
        if key not in known:
            fail.add('resources',
                     'Theme.xaml asks for "{0}", which it does not define'
                     .format(key))

    # And XAML embedded in Python, which a layout scan would walk straight
    # past. The tick column's cell template is a string in ps_window.
    for path in source_files(root):
        base = os.path.basename(path)
        body = read(path)
        for key in KEY_PATTERN.findall(body):
            if key not in known:
                fail.add('resources',
                         '{0} builds XAML asking for "{1}", which Theme.xaml '
                         'does not define'.format(base, key))
        for key in STATIC_PATTERN.findall(body):
            fail.add('resources',
                     '{0} builds XAML using StaticResource "{1}"; the theme '
                     'is merged in after parsing'.format(base, key))


# ==========================================================================
# rule 5 : a Style only goes on an element its TargetType matches
# ==========================================================================

STYLE_ON = re.compile(
    r'<([A-Za-z][A-Za-z0-9]*)\b[^>]*?(?:\s|")([A-Za-z]*)Style='
    r'"\{DynamicResource\s+([A-Za-z0-9_]+)\s*\}"', re.S)

# A style-bearing property whose value is a style for something OTHER
# than the element carrying it. RowStyle on a DataGrid is a style for
# its rows, not for the grid - reading it as the grid's own style is
# how this rule used to report a false fault on perfectly good XAML.
STYLE_PROPERTY_TARGETS = {
    'Row': 'DataGridRow',
    'Cell': 'DataGridCell',
    'ColumnHeader': 'DataGridColumnHeader',
    'RowHeader': 'DataGridRowHeader',
    'Header': 'DataGridColumnHeader',
    'Element': 'TextBlock',
    'EditingElement': 'TextBox',
}


def style_targets(root):
    text = read(os.path.join(root, THEME_FILE))
    found = {}
    for block in re.findall(r'<Style\b[^>]*>', text):
        key = re.search(r'x:Key="([^"]+)"', block)
        target = re.search(r'TargetType="\{x:Type\s+([A-Za-z0-9]+)\}"', block)
        if not target:
            target = re.search(r'TargetType="([A-Za-z0-9]+)"', block)
        if key and target:
            found[key.group(1)] = target.group(1)
    return found


def rule_style_targets(root, fail):
    targets = style_targets(root)
    for name in LAYOUTS + [THEME_FILE]:
        path = os.path.join(root, name)
        if not os.path.isfile(path):
            continue
        for element, prefix, key in STYLE_ON.findall(read(path)):
            # RowStyle, CellStyle and the rest carry a style for
            # something the element contains, not for the element.
            expected = STYLE_PROPERTY_TARGETS.get(prefix, element)
            where = (element if not prefix
                     else '{0}.{1}Style'.format(element, prefix))
            wanted = targets.get(key)
            if wanted is None:
                fail.add('style_targets',
                         '{0} puts style "{1}" on {2}, but no such style is '
                         'keyed in Theme.xaml'.format(name, key, where))
            elif wanted != expected:
                fail.add('style_targets',
                         '{0} puts style "{1}" (TargetType {2}) on {3}, '
                         'which wants a {4}; WPF raises when the style is '
                         'applied, which reads as a dead window'
                         .format(name, key, wanted, where, expected))


# ==========================================================================
# rule 6 : every name looked up has a matching x:Name
# ==========================================================================

FIND_CALLS = [
    re.compile(r"ps_ui\.find\(\s*[A-Za-z_][A-Za-z0-9_.]*\s*,\s*'([^']+)'"),
    re.compile(r'ps_ui\.find\(\s*[A-Za-z_][A-Za-z0-9_.]*\s*,\s*"([^"]+)"'),
    re.compile(r"\.FindName\(\s*'([^']+)'"),
    re.compile(r'\.FindName\(\s*"([^"]+)"'),
]

# Every way the code asks for a resource by name. A key that does not
# exist is a silent miss: TryFindResource hands back null, and assigning
# null to Style suppresses the implicit style too, so the control falls all
# the way to the OS chrome. That is what put a light grey lozenge in the
# middle of a dark header in 1.6.0.
RESOURCE_CALLS = [
    re.compile(r"TryFindResource\(\s*'([^']+)'"),
    re.compile(r"SetResourceReference\([^,]+,\s*'([^']+)'"),
    re.compile(r"_styled\(\s*[A-Za-z_][A-Za-z0-9_.]*\s*,\s*'([^']+)'"),
]


def xaml_names(root):
    found = set()
    for name in LAYOUTS:
        path = os.path.join(root, name)
        if not os.path.isfile(path):
            continue
        found.update(re.findall(r'x:Name="([^"]+)"', read(path)))
    return found


def rule_find_names(root, fail):
    declared = xaml_names(root)
    keys = theme_keys(root)
    runtime = set(['PromptInput'])          # registered in code, not in XAML
    for path in source_files(root):
        text = read(path)
        base = os.path.basename(path)
        for pattern in FIND_CALLS:
            for name in pattern.findall(text):
                if name not in declared and name not in runtime:
                    fail.add('find_names',
                             '{0} looks up "{1}", which no layout declares as '
                             'an x:Name'.format(base, name))
        for pattern in RESOURCE_CALLS:
            for name in pattern.findall(text):
                if name not in keys:
                    fail.add('find_names',
                             '{0} asks for resource "{1}", which Theme.xaml '
                             'does not define'.format(base, name))
    # And the grab list in ps_window, which is the same idea by another route.
    window = os.path.join(root, 'ps_window.py')
    if os.path.isfile(window):
        tree = ast.parse(read(window))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if getattr(target, 'id', None) != 'names':
                    continue
                if not isinstance(node.value, ast.List):
                    continue
                for item in node.value.elts:
                    value = getattr(item, 's', getattr(item, 'value', None))
                    if isinstance(value, str) and value not in declared:
                        fail.add('find_names',
                                 'ps_window grabs "{0}", which no layout '
                                 'declares as an x:Name'.format(value))


# ==========================================================================
# rule 7 : IronPython 2.7 and 3 both have to run this
# ==========================================================================

def rule_python_dialect(root, fail):
    for path in source_files(root) + [os.path.join(root, 'script.py')]:
        if not os.path.isfile(path):
            continue
        base = os.path.basename(path)
        text = read(path)
        tree = ast.parse(text)

        # eid_value is the one place allowed to name IntegerValue, because it
        # is the helper everything else goes through.
        allowed_lines = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == 'eid_value':
                for inner in ast.walk(node):
                    if hasattr(inner, 'lineno'):
                        allowed_lines.add(inner.lineno)

        for node in ast.walk(tree):
            if node.__class__.__name__ == 'JoinedStr':
                fail.add('python_dialect',
                         '{0} line {1}: f-string, which IronPython 2.7 cannot '
                         'parse'.format(base, node.lineno))
            if (isinstance(node, ast.Attribute)
                    and node.attr == 'IntegerValue'
                    and node.lineno not in allowed_lines):
                fail.add('python_dialect',
                         '{0} line {1}: bare .IntegerValue, removed in Revit '
                         '2026; go through eid_value'.format(base, node.lineno))
            if isinstance(node, ast.Call):
                target = node.func
                if (isinstance(target, ast.Name) and target.id == 'print'
                        and base != 'import_check.py'):
                    fail.add('python_dialect',
                             '{0} line {1}: print(), which does not belong in '
                             'a pyRevit tool'.format(base, node.lineno))
            # Uri is checked on the import statement itself, not on the text
            # of the file: a docstring warning people off System.Uri is not a
            # use of System.Uri, and flagging it trains people to ignore the
            # check.
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name == 'Uri':
                        fail.add('python_dialect',
                                 '{0} line {1}: System.Uri, which throws '
                                 'ImportError on Revit 2025 and later'
                                 .format(base, node.lineno))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.endswith('.Uri') or alias.name == 'Uri':
                        fail.add('python_dialect',
                                 '{0} line {1}: System.Uri, which throws '
                                 'ImportError on Revit 2025 and later'
                                 .format(base, node.lineno))
            if (isinstance(node, ast.Attribute) and node.attr == 'UriSource'):
                fail.add('python_dialect',
                         '{0} line {1}: BitmapImage.UriSource needs System.Uri'
                         .format(base, node.lineno))


# ==========================================================================
# rule 8 : nothing non-ASCII outside a u'' literal
# ==========================================================================

def rule_ascii(root, fail):
    for path in source_files(root) + [os.path.join(root, 'script.py')]:
        if not os.path.isfile(path):
            continue
        base = os.path.basename(path)
        for line_number, line in enumerate(read(path).split('\n'), 1):
            if all(ord(ch) < 128 for ch in line):
                continue
            stripped = line.strip()
            if stripped.startswith('#'):
                continue
            if re.search(r"u'[^']*'", line) or re.search(r'u"[^"]*"', line):
                continue
            fail.add('ascii',
                     '{0} line {1}: non-ASCII outside a u\'\' literal'
                     .format(base, line_number))


# ==========================================================================
# rule 9 : both palettes carry the same keys, and Theme.xaml has a brush
#          for every one of them
# ==========================================================================

def rule_palettes(root, fail):
    text = read(os.path.join(root, 'theme.py'))
    tree = ast.parse(text)
    palettes = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            name = getattr(target, 'id', None)
            if name not in ('DARK', 'LIGHT'):
                continue
            if not isinstance(node.value, ast.Dict):
                continue
            keys = []
            for item in node.value.keys:
                value = getattr(item, 's', getattr(item, 'value', None))
                if isinstance(value, str):
                    keys.append(value)
            palettes[name] = set(keys)

    if 'DARK' not in palettes or 'LIGHT' not in palettes:
        fail.add('palettes', 'theme.py does not declare both DARK and LIGHT')
        return

    only_dark = palettes['DARK'] - palettes['LIGHT']
    only_light = palettes['LIGHT'] - palettes['DARK']
    for key in sorted(only_dark):
        fail.add('palettes',
                 '"{0}" is in the dark palette but not the light one'.format(key))
    for key in sorted(only_light):
        fail.add('palettes',
                 '"{0}" is in the light palette but not the dark one'.format(key))

    declared = theme_keys(root)
    for key in sorted(palettes['DARK']):
        if key not in declared:
            fail.add('palettes',
                     'Theme.xaml has no brush for palette key "{0}", so the '
                     'templates fall back to the system theme'.format(key))


# ==========================================================================
# rule 10 : no method defined twice
# ==========================================================================

def rule_no_duplicate_methods(root, fail):
    for path in source_files(root):
        base = os.path.basename(path)
        tree = ast.parse(read(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            seen = {}
            for item in node.body:
                if not isinstance(item, ast.FunctionDef):
                    continue
                if item.name in seen:
                    fail.add('no_duplicate_methods',
                             '{0}: {1}.{2} is defined twice (lines {3} and '
                             '{4}); the second one silently wins'
                             .format(base, node.name, item.name,
                                     seen[item.name], item.lineno))
                seen[item.name] = item.lineno
        # module level too
        seen = {}
        for item in tree.body:
            if isinstance(item, ast.FunctionDef):
                if item.name in seen:
                    fail.add('no_duplicate_methods',
                             '{0}: {1}() is defined twice (lines {2} and {3})'
                             .format(base, item.name, seen[item.name],
                                     item.lineno))
                seen[item.name] = item.lineno


# ==========================================================================
# rule 11 : nothing reachable from __init__ reads an attribute nothing set
#
# This one has to WALK THE CALL GRAPH, not one level of it. The bug it was
# written for was three deep. Two refinements keep it useful rather than
# noisy: calls made inside nested functions are not followed, since those
# are handlers being wired rather than work being done; and a write in the
# same method counts only when it comes before the read, which is the
# difference between a guard and a bug.
# ==========================================================================

def _self_writes(node):
    written = []
    for item in ast.walk(node):
        if isinstance(item, ast.Assign):
            for target in item.targets:
                if (isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == 'self'):
                    written.append((target.attr, item.lineno))
        elif isinstance(item, (ast.AugAssign,)):
            target = item.target
            if (isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == 'self'):
                written.append((target.attr, item.lineno))
    return written


def _nested_lines(node):
    lines = set()
    for item in ast.walk(node):
        if item is node:
            continue
        if isinstance(item, (ast.FunctionDef, ast.Lambda)):
            for inner in ast.walk(item):
                if hasattr(inner, 'lineno'):
                    lines.add(inner.lineno)
    return lines


def _self_reads(node):
    skip = _nested_lines(node)
    reads = []
    for item in ast.walk(node):
        if not isinstance(item, ast.Attribute):
            continue
        if not (isinstance(item.value, ast.Name) and item.value.id == 'self'):
            continue
        if not isinstance(item.ctx, ast.Load):
            continue
        if item.lineno in skip:
            continue
        reads.append((item.attr, item.lineno))
    return reads


def _direct_self_calls(node):
    skip = _nested_lines(node)
    calls = []
    for item in ast.walk(node):
        if not isinstance(item, ast.Call):
            continue
        target = item.func
        if not isinstance(target, ast.Attribute):
            continue
        if not (isinstance(target.value, ast.Name) and target.value.id == 'self'):
            continue
        if target.lineno in skip:
            continue
        calls.append((target.attr, target.lineno))
    return calls


def rule_init_attributes(root, fail):
    for path in source_files(root):
        base = os.path.basename(path)
        tree = ast.parse(read(path))
        for cls in ast.walk(tree):
            if not isinstance(cls, ast.ClassDef):
                continue
            methods = dict([(item.name, item) for item in cls.body
                            if isinstance(item, ast.FunctionDef)])
            init = methods.get('__init__')
            if init is None:
                continue

            declared = set()
            for item in cls.body:
                if isinstance(item, ast.Assign):
                    for target in item.targets:
                        if isinstance(target, ast.Name):
                            declared.add(target.id)
            for item in ast.walk(cls):
                if isinstance(item, ast.Assign):
                    for target in item.targets:
                        if (isinstance(target, ast.Name)
                                and target.id == '__slots__'
                                and isinstance(item.value, (ast.Tuple, ast.List))):
                            for slot in item.value.elts:
                                value = getattr(slot, 's',
                                                getattr(slot, 'value', None))
                                if isinstance(value, str):
                                    declared.add(value)

            set_so_far = set(declared)
            problems = []
            visited = set()

            def walk(method_name):
                """Replay one method in source order, then follow its calls.

                Order is the whole point. Collecting a method's writes and
                then recursing would treat an attribute set at the bottom of
                __init__ as available to a helper called at the top, which is
                exactly the bug this rule exists to catch.
                """
                if method_name in visited:
                    return
                visited.add(method_name)
                method = methods.get(method_name)
                if method is None:
                    return

                events = []
                for attr, line in _self_writes(method):
                    events.append((line, 0, 'write', attr))
                for attr, line in _self_reads(method):
                    events.append((line, 1, 'read', attr))
                for attr, line in _direct_self_calls(method):
                    events.append((line, 2, 'call', attr))
                events.sort()

                for _line, _order, kind, attr in events:
                    if kind == 'write':
                        set_so_far.add(attr)
                    elif kind == 'read':
                        if attr in methods or attr in set_so_far:
                            continue
                        problems.append((cls.name, method_name, attr, _line))
                    else:
                        walk(attr)

            walk('__init__')

            for class_name, method_name, attr, line in problems:
                fail.add('init_attributes',
                         '{0}: {1}.{2} reads self.{3} on line {4} before '
                         'anything sets it'.format(base, class_name,
                                                   method_name, attr, line))


# ==========================================================================
# rule 12 : the whole tool loads against the stub API
# ==========================================================================

def rule_modules_load(root, fail):
    saved_path = list(sys.path)
    saved_modules = dict(sys.modules)
    stubs = install_stubs()
    sys.path.insert(0, root)
    for name in MODULES:
        sys.modules.pop(name, None)
    try:
        for name in MODULES:
            try:
                __import__(name)
            except Exception as err:
                fail.add('modules_load',
                         '{0} would not load: {1}: {2}'
                         .format(name, err.__class__.__name__, err))
    finally:
        remove_stubs(stubs)
        for name in MODULES:
            sys.modules.pop(name, None)
        sys.modules.update(
            dict([(k, v) for k, v in saved_modules.items()
                  if k in MODULES]))
        sys.path[:] = saved_path


# ==========================================================================
# rule 13 : the naming and path engines behave, against a table of cases
# ==========================================================================

def rule_naming_behaviour(root, fail):
    saved_path = list(sys.path)
    sys.path.insert(0, root)
    for name in ('ps_naming', 'ps_paths'):
        sys.modules.pop(name, None)
    try:
        import ps_naming
        import ps_paths
    except Exception as err:
        fail.add('naming_behaviour', 'could not load the engines: {0}'.format(err))
        sys.path[:] = saved_path
        return

    def lookup_from(values):
        return lambda name: values.get(name, u'')

    rule = ps_naming.Rule
    cases = [
        ('number then name',
         [rule(u'Sheet Number', separator=u'-'), rule(u'Sheet Name')],
         {u'Sheet Number': u'E-1101', u'Sheet Name': u'CONTAINMENT'},
         u'E-1101-CONTAINMENT'),
        ('an empty parameter takes its separator with it',
         [rule(u'Sheet Number', separator=u'-'),
          rule(u'Revision', separator=u'-'),
          rule(u'Sheet Name')],
         {u'Sheet Number': u'E-1101', u'Revision': u'',
          u'Sheet Name': u'CONTAINMENT'},
         u'E-1101-CONTAINMENT'),
        ('prefix and suffix survive an empty value',
         [rule(u'Revision', prefix=u'[', suffix=u']')],
         {u'Revision': u''},
         u'[]'),
        ('the last separator is dropped',
         [rule(u'Sheet Number', separator=u'-')],
         {u'Sheet Number': u'E-1101'},
         u'E-1101'),
        ('illegal characters become underscores',
         [rule(u'Sheet Name')],
         {u'Sheet Name': u'PLANT / RISER: L1'},
         u'PLANT _ RISER_ L1'),
        ('a trailing dot is dropped, as Windows would',
         [rule(u'Sheet Name')],
         {u'Sheet Name': u'LEVEL 1.'},
         u'LEVEL 1'),
        ('a reserved device name is escaped',
         [rule(u'Sheet Name')],
         {u'Sheet Name': u'CON'},
         u'_CON'),
    ]
    for label, rules, values, wanted in cases:
        got = ps_naming.build_name(rules, lookup_from(values))
        if got != wanted:
            fail.add('naming_behaviour',
                     '{0}: expected "{1}", got "{2}"'.format(label, wanted, got))

    preview = ps_naming.preview([rule(u'Sheet Number', separator=u'-'),
                                 rule(u'Sheet Name')])
    if preview != u'Sheet Number-Sheet Name':
        fail.add('naming_behaviour',
                 'preview should read "Sheet Number-Sheet Name", got "{0}"'
                 .format(preview))

    settled = ps_naming.unique_names([(1, u'A'), (2, u'A'), (3, u'A'),
                                      (4, u'B')])
    if [name for _key, name in settled] != [u'A', u'A (2)', u'A (3)', u'B']:
        fail.add('naming_behaviour',
                 'repeated names should gain (2) and (3), got {0}'
                 .format([name for _key, name in settled]))

    if not ps_naming.clashes([(1, u'A'), (2, u'a')]):
        fail.add('naming_behaviour',
                 'a clash that differs only in case is still a clash on '
                 'Windows and must be reported')

    values = {u'Project Number': u'24-0810',
              u'BGL_Sheet Discipline': u'Electrical',
              u'Empty': u''}
    got = ps_paths.expand(u'{Project Number}\\{BGL_Sheet Discipline}',
                          lookup_from(values))
    if got.replace('\\', '/') != u'24-0810/Electrical':
        fail.add('naming_behaviour',
                 'folder tokens should expand to 24-0810/Electrical, got "{0}"'
                 .format(got))

    got = ps_paths.expand(u'{Project Number}\\{Empty}\\x', lookup_from(values))
    levels = [part for part in got.replace('\\', '/').split('/') if part]
    if len(levels) != 3:
        fail.add('naming_behaviour',
                 'an empty token must keep its folder level rather than '
                 'flattening the tree, got "{0}"'.format(got))

    # Date and time tokens. The trap is %m against %M, which is exactly why
    # the picker offers the named ones - but both spellings have to work.
    stamped = ps_paths.expand(u'{Year}\\{Month}', lambda n: u'')
    parts = [part for part in stamped.replace('\\', '/').split('/') if part]
    if len(parts) != 2:
        fail.add('naming_behaviour',
                 'named date tokens should give two folder levels, got "{0}"'
                 .format(stamped))
    else:
        if not (len(parts[0]) == 4 and parts[0].isdigit()):
            fail.add('naming_behaviour',
                     'Year should be four digits, got "{0}"'.format(parts[0]))
        if not (len(parts[1]) == 2 and parts[1].isdigit()
                and 1 <= int(parts[1]) <= 12):
            fail.add('naming_behaviour',
                     'Month should be a two digit month, got "{0}"'
                     .format(parts[1]))

    for token, length in ((u'{Day}', 2), (u'{Hour}', 2), (u'{Minute}', 2),
                          (u'{Second}', 2), (u'{Date}', 10)):
        got = ps_paths.expand(token, lambda n: u'')
        if len(got) != length or not got.strip():
            fail.add('naming_behaviour',
                     '{0} should be {1} characters, got "{2}"'
                     .format(token, length, got))

    # Each named token must give the value it says on the tin. A length
    # check is not enough: a minute rendered as a month is still two digits,
    # which is how the mix-up survives being looked at.
    import datetime as _dt

    def _both(code):
        """The value now and a moment later, so a tick over does not fail."""
        return set([_dt.datetime.now().strftime(code)])

    for label, code in ((u'{Year}', '%Y'), (u'{Month}', '%m'),
                        (u'{Day}', '%d'), (u'{Hour}', '%H'),
                        (u'{Minute}', '%M'), (u'{Second}', '%S')):
        before = _both(code)
        got = ps_paths.expand(label, lambda n: u'')
        allowed = before | _both(code)
        if got not in allowed:
            fail.add('naming_behaviour',
                     '{0} should render strftime {1} - expected one of {2}, '
                     'got "{3}"'.format(label, code, sorted(allowed), got))

    # And against a pinned clock where every field differs. Against the
    # real one a minute-for-month mix-up passes whenever the minute happens
    # to equal the month - 15:10 in October let it through in 1.26.0's
    # selftest.
    saved_now = ps_paths._now
    ps_paths._now = lambda: _dt.datetime(2027, 3, 4, 5, 46, 57)
    try:
        for label, wanted in ((u'{Year}', u'2027'), (u'{Month}', u'03'),
                              (u'{Day}', u'04'), (u'{Hour}', u'05'),
                              (u'{Minute}', u'46'), (u'{Second}', u'57')):
            got = ps_paths.expand(label, lambda n: u'')
            if got != wanted:
                fail.add('naming_behaviour',
                         '{0} at 05:46:57 on 4 March 2027 gave "{1}", wanted '
                         '"{2}"'.format(label, got, wanted))
    finally:
        ps_paths._now = saved_now

    month = ps_paths.expand_strftime(u'%m')
    minute = ps_paths.expand_strftime(u'%M')
    try:
        month_ok = len(month) == 2 and 1 <= int(month) <= 12
        minute_ok = len(minute) == 2 and 0 <= int(minute) <= 59
    except Exception:
        month_ok = minute_ok = False
    if not month_ok:
        fail.add('naming_behaviour',
                 'strftime %m must be the month, got "{0}"'.format(month))
    if not minute_ok:
        fail.add('naming_behaviour',
                 'strftime %M must be the minute, got "{0}"'.format(minute))
    if ps_paths.expand_strftime(u'%h') != ps_paths.expand_strftime(u'%H'):
        fail.add('naming_behaviour',
                 '%h is accepted as an alias for the hour and must match %H')
    if ps_paths.expand_strftime(u'100%% sure') != u'100% sure':
        fail.add('naming_behaviour',
                 'a doubled percent should give one per cent sign')
    if ps_paths.expand_strftime(u'no codes here') != u'no codes here':
        fail.add('naming_behaviour',
                 'text with no codes must come back unchanged')

    # Two folders are the same folder, or one is inside the other.
    # Deliberately not built on os.path.abspath or normcase: those
    # answer for the platform the check runs on, and this bench runs on
    # Linux while the tool runs on Windows - so a comparison built on
    # them passes here and fails there.
    folders = [
        ('separator and case do not matter', 'same',
         ('C:\\A\\B', 'c:/a/b/'), True),
        ('different folders', 'same', ('C:\\A', 'C:\\B'), False),
        ('an empty path matches nothing', 'same', ('', 'C:\\A'), False),
        ('a subfolder is inside its parent', 'inside',
         ('C:\\A\\B\\PDF', 'C:\\A\\B'), True),
        ('a parent is not inside its child', 'inside',
         ('C:\\A', 'C:\\A\\B'), False),
        ('a name that merely starts the same is not inside', 'inside',
         ('C:\\AB', 'C:\\A'), False),
        ('a folder is inside itself', 'inside',
         ('C:\\A\\B', 'C:\\A\\B'), True),
    ]
    for label, kind, given, wanted in folders:
        call = (ps_paths.same_folder if kind == 'same'
                else ps_paths.inside_folder)
        got = bool(call(*given))
        if got != wanted:
            fail.add('naming_behaviour',
                     '{0}: {1}{2} is {3}, wanted {4}'
                     .format(label, kind, given, got, wanted))

    catalogue = ps_paths.token_catalogue([(u'BGL_Sheet Discipline', u'Sheet')])
    names = [entry[0] for entry in catalogue]
    for wanted in (u'Year', u'Month', u'Hour', u'Minute',
                   u'BGL_Sheet Discipline'):
        if wanted not in names:
            fail.add('naming_behaviour',
                     'the folder picker should offer "{0}"'.format(wanted))

    sys.path[:] = saved_path


# ==========================================================================
# rule 14 : paper sizing, against a table of cases
#
# The size a sheet prints on is decided from its extents, and every branch
# of that decision is a plain function. Which makes it testable, which is
# the only reason to trust it on four hundred sheets.
# ==========================================================================

def rule_paper_sizing(root, fail):
    saved_path = list(sys.path)
    saved_modules = dict(sys.modules)
    stubs = install_stubs()
    sys.path.insert(0, root)
    for name in ('ps_refs', 'ps_model'):
        sys.modules.pop(name, None)
    try:
        import ps_model
    except Exception as err:
        fail.add('paper_sizing', 'could not load ps_model: {0}'.format(err))
        return
    finally:
        remove_stubs(stubs)
        sys.path[:] = saved_path

    try:
        exact = [
            ('A1 landscape', 841.0, 594.0, 'A1', True),
            ('A1 portrait', 594.0, 841.0, 'A1', False),
            ('A0 landscape', 1189.0, 841.0, 'A0', True),
            ('A0 portrait', 841.0, 1189.0, 'A0', False),
            ('A2 landscape', 594.0, 420.0, 'A2', True),
            ('A2 portrait', 420.0, 594.0, 'A2', False),
            ('A3 landscape', 420.0, 297.0, 'A3', True),
            ('a title block drawn a couple of mm under', 838.0, 592.0,
             'A1', True),
        ]
        for label, width, height, wanted, landscape in exact:
            got = ps_model.match_iso(width, height)
            if got != wanted:
                fail.add('paper_sizing',
                         '{0}: {1}x{2} should be {3}, got {4}'
                         .format(label, width, height, wanted, got))
            size = ps_model.SheetSize(wanted, width, height,
                                      width >= height, u'test', True)
            if size.landscape != landscape:
                fail.add('paper_sizing',
                         '{0}: orientation should be {1}'
                         .format(label, 'landscape' if landscape else 'portrait'))
            if wanted.lower() not in size.label().lower():
                fail.add('paper_sizing',
                         '{0}: the label should name the size, got "{1}"'
                         .format(label, size.label()))

        # A non-standard sheet fits up to the smallest standard that holds it.
        fitted = [
            ('a cut down schematic sheet', 420.0, 387.0, 'A2'),
            ('slightly over A2', 600.0, 430.0, 'A1'),
            ('slightly over A1', 850.0, 600.0, 'A0'),
            ('tiny', 100.0, 100.0, 'A6'),
        ]
        for label, width, height, wanted in fitted:
            got = ps_model.smallest_containing(width, height)
            if got != wanted:
                fail.add('paper_sizing',
                         '{0}: {1}x{2} should fit up to {3}, got {4}'
                         .format(label, width, height, wanted, got))

        if ps_model.smallest_containing(2000.0, 3000.0) is not None:
            fail.add('paper_sizing',
                     'a sheet bigger than A0 has nothing to fit up to and '
                     'must give None rather than guessing')
        if ps_model.match_iso(0, 0) is not None:
            fail.add('paper_sizing', 'a sheet with no size must match nothing')

        # A fitted size has to say so; silently rounding somebody's paper is
        # exactly the kind of thing nobody notices until it is printed.
        rough = ps_model.SheetSize('A2', 420.0, 387.0, True, u'test', False)
        if 'fitted' not in rough.label().lower():
            fail.add('paper_sizing',
                     'a fitted size must say so in its label, got "{0}"'
                     .format(rough.label()))

        for name, short, long_edge in ps_model.ISO_SIZES:
            dims = ps_model.iso_dimensions(name)
            if dims != (short, long_edge):
                fail.add('paper_sizing',
                         '{0} dimensions came back as {1}'.format(name, dims))
    finally:
        for name in ('ps_refs', 'ps_model'):
            sys.modules.pop(name, None)
        sys.modules.update(dict([(k, v) for k, v in saved_modules.items()
                                 if k in ('ps_refs', 'ps_model')]))


# ==========================================================================
# rule 18 : every row and column a Grid declares has something in it
#
# A child with no Grid.Row lands in row 0. Where the layout meant it to be
# in row 2, it silently stacks on top of whatever is in row 0 and the row
# it was meant to fill stays empty - which is how the Selection grid ended
# up drawn over the toolbar with a screen of blank underneath it. Nothing
# throws, the XAML is valid, and it only shows up by eye.
#
# An empty declared row is the signature of that mistake. A layout that
# genuinely wants a spacer row can say so with a comment containing
# "spacer row".
# ==========================================================================

GRID_PROPERTY_ELEMENTS = ('Grid.RowDefinitions', 'Grid.ColumnDefinitions',
                          'Grid.Resources')


def _element_children(node):
    out = []
    for child in node.childNodes:
        if child.nodeType != child.ELEMENT_NODE:
            continue
        if child.tagName in GRID_PROPERTY_ELEMENTS:
            continue
        # A property element like <Border.Child> belongs to its owner, not
        # to the Grid.
        if '.' in child.tagName:
            continue
        out.append(child)
    return out


def _declared(node, tag):
    for child in node.childNodes:
        if child.nodeType == child.ELEMENT_NODE and child.tagName == tag:
            return len([g for g in child.childNodes
                        if g.nodeType == g.ELEMENT_NODE])
    return 0


def rule_grid_placement(root, fail):
    for name in LAYOUTS:
        path = os.path.join(root, name)
        if not os.path.isfile(path):
            continue
        body = read(path)
        allow_spacers = 'spacer row' in body.lower()
        try:
            document = xml.dom.minidom.parse(path)
        except Exception:
            continue                      # rule_xaml_parses reports that
        for grid in document.getElementsByTagName('Grid'):
            rows = _declared(grid, 'Grid.RowDefinitions')
            columns = _declared(grid, 'Grid.ColumnDefinitions')
            children = _element_children(grid)
            if not children:
                continue

            for count, attribute, word in ((rows, 'Grid.Row', 'row'),
                                           (columns, 'Grid.Column', 'column')):
                if count < 2:
                    continue
                used = set()
                for child in children:
                    value = child.getAttribute(attribute) or '0'
                    try:
                        used.add(int(value))
                    except Exception:
                        continue
                missing = [index for index in range(count)
                           if index not in used]
                if missing and not allow_spacers:
                    fail.add('grid_placement',
                             '{0}: a Grid declares {1} {2}s but nothing sits '
                             'in {2} {3}. A child with no {4} lands in {2} 0 '
                             'and draws on top of whatever is already there.'
                             .format(name, count, word,
                                     ', '.join([str(m) for m in missing]),
                                     attribute))


# ==========================================================================
# rule 17 : template bundles survive a round trip
#
# A bundle is the thing that leaves the machine and comes back on another
# one, so it is the last place a silent change of format is acceptable.
# ==========================================================================

def rule_template_bundles(root, fail):
    saved_path = list(sys.path)
    saved_modules = dict(sys.modules)
    stubs = install_stubs()
    sys.path.insert(0, root)
    sys.modules.pop('ps_config', None)
    sys.modules.pop('ps_refs', None)
    try:
        import ps_config
    except Exception as err:
        fail.add('template_bundles', 'could not load ps_config: {0}'.format(err))
        return
    finally:
        remove_stubs(stubs)
        sys.path[:] = saved_path

    folder = tempfile.mkdtemp(prefix='prosheets_bundle_')
    try:
        path = os.path.join(folder, 'bundle' + ps_config.BUNDLE_EXTENSION)
        templates = {
            u'Standard issue': {'mode': 'sheets', 'pdf.zoom': '100',
                                'out.tokens': u'{Project Number}\\{Month}'},
            u'Coordination': {'mode': 'views', 'formats': u'pdf\tdwg',
                              'name.rule.1.prefix': u'= a tricky value ='},
            u'Has A Blank': {'out.root': u''},
        }
        if not ps_config.write_bundle(path, templates):
            fail.add('template_bundles', 'a bundle would not write')
            return

        back = ps_config.read_bundle(path)
        if set(back.keys()) != set(templates.keys()):
            fail.add('template_bundles',
                     'names did not survive the round trip: wrote {0}, read '
                     '{1}'.format(sorted(templates.keys()), sorted(back.keys())))
        for name, values in templates.items():
            got = back.get(name, {})
            for key, value in values.items():
                if got.get(key) != value:
                    fail.add('template_bundles',
                             '{0}: "{1}" came back as {2!r}, not {3!r}'
                             .format(name, key, got.get(key), value))

        # A plain single profile with no @template line still has to load.
        loose = os.path.join(folder, 'Just One.txt')
        ps_config.write_store(loose, {'mode': 'sheets'})
        single = ps_config.read_bundle(loose)
        if len(single) != 1 or 'Just One' not in single:
            fail.add('template_bundles',
                     'a plain profile file should load as one template named '
                     'after the file, got {0}'.format(sorted(single.keys())))

        # Clashing names gain (1), (2) rather than overwriting.
        taken = [u'Standard issue']
        first = ps_config.unique_template_name(taken, u'Standard issue')
        if first != u'Standard issue (1)':
            fail.add('template_bundles',
                     'a clashing name should become "Standard issue (1)", '
                     'got "{0}"'.format(first))
        taken.append(first)
        second = ps_config.unique_template_name(taken, u'Standard issue')
        if second != u'Standard issue (2)':
            fail.add('template_bundles',
                     'the second clash should become "(2)", got "{0}"'
                     .format(second))
        if ps_config.unique_template_name(taken, u'Fresh') != u'Fresh':
            fail.add('template_bundles',
                     'a name nothing else uses must be left alone')
        # Case does not make a name unique on Windows.
        if ps_config.unique_template_name([u'Alpha'], u'alpha') == u'alpha':
            fail.add('template_bundles',
                     'names differing only in case must still be treated as '
                     'a clash')
    finally:
        shutil.rmtree(folder, ignore_errors=True)
        sys.modules.pop('ps_config', None)
        sys.modules.update(dict([(k, v) for k, v in saved_modules.items()
                                 if k == 'ps_config']))


# ==========================================================================
# rule 16 : the easter egg is armed on the logo of one window only
#
# It fired while people were clicking Close on export reports, because
# every message window armed it and the arming code was willing to hand the
# whole window over as the hit area. Both halves of that need holding shut.
# ==========================================================================

def rule_egg_arming(root, fail):
    call_sites = []
    for path in source_files(root):
        base = os.path.basename(path)
        if base == 'ps_ui.py':
            continue
        for line_number, line in enumerate(read(path).split('\n'), 1):
            if re.search(r'\battach_egg\s*\(', line) and not line.strip().startswith('#'):
                call_sites.append((base, line_number))

    if not call_sites:
        fail.add('egg_arming',
                 'nothing arms the easter egg any more; this tool is one of '
                 'its anchors and should arm it on its main window')
    for base, line_number in call_sites:
        if base != 'ps_window.py':
            fail.add('egg_arming',
                     '{0} line {1} arms the easter egg. Only the main window '
                     'should: a dialog or a report is something people '
                     'dismiss repeatedly, and arming it turns clicking Close '
                     'into a way to start the game'.format(base, line_number))
    if len(call_sites) > 1:
        fail.add('egg_arming',
                 'the easter egg is armed from {0} places; it should be one'
                 .format(len(call_sites)))

    ui = os.path.join(root, 'ps_ui.py')
    if not os.path.isfile(ui):
        fail.add('egg_arming', 'ps_ui.py is missing')
        return
    tree = ast.parse(read(ui))
    body = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == 'attach_egg':
            body = node
            break
    if body is None:
        fail.add('egg_arming', 'ps_ui has no attach_egg')
        return

    # Never hand the window over as the thing being clicked.
    for node in ast.walk(body):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        name = getattr(target, 'id', None) or getattr(target, 'attr', None)
        if name != 'attach':
            continue
        if not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Name) and first.id == 'window' \
                and len(node.args) == 1:
            fail.add('egg_arming',
                     'ps_ui.attach_egg line {0} passes the whole window as '
                     'the element, which makes three clicks anywhere set the '
                     'egg off'.format(node.lineno))

    # And never fall back to the window when there is no logo.
    source = read(ui)
    start = source.index('def attach_egg(')
    chunk = source[start:start + 4000]
    if re.search(r'target\s*=\s*host\s+if\s+host\s+is\s+not\s+None\s+else\s+window',
                 chunk):
        fail.add('egg_arming',
                 'ps_ui.attach_egg falls back to the window when there is no '
                 'logo; it should arm nothing instead')


# ==========================================================================
# running them
# ==========================================================================

# ==========================================================================
# rule 19 : the format registry and the Format tab agree
#
# Before 1.8.0 each format's tick, tile and panel were named by hand in
# six different methods, and DGN and IMG ended up drawn on the tab with
# nothing behind them. The registry is now the single list; this rule is
# what stops it drifting from the layout it describes.
# ==========================================================================

def _window_module(root, rule, fail):
    """ps_window imported against the stub API, or None."""
    saved_path = list(sys.path)
    stubs = install_stubs()
    sys.path.insert(0, root)
    for name in MODULES:
        sys.modules.pop(name, None)
    try:
        import ps_window
        return ps_window
    except Exception as err:
        fail.add(rule, 'could not load ps_window: {0}: {1}'
                 .format(err.__class__.__name__, err))
        return None
    finally:
        remove_stubs(stubs)
        sys.path[:] = saved_path


def rule_format_registry(root, fail):
    module = _window_module(root, 'format_registry', fail)
    if module is None:
        return
    declared = xaml_names(root)
    layout = read(os.path.join(root, 'ProSheets.xaml'))

    seen = set()
    for row in getattr(module, 'FORMATS', []):
        fmt, tick, tile, group, panel, label, live = row
        seen.add(fmt)
        for name in (tick, tile, group):
            if name not in declared:
                fail.add('format_registry',
                         'the "{0}" row names "{1}", which no layout '
                         'declares as an x:Name'.format(fmt, name))
        if live and not panel:
            fail.add('format_registry',
                     '"{0}" is live but names no settings panel, so its '
                     'tile would open nothing'.format(fmt))
        if panel and panel not in declared:
            fail.add('format_registry',
                     'the "{0}" row names panel "{1}", which no layout '
                     'declares'.format(fmt, panel))
        if not label:
            fail.add('format_registry',
                     '"{0}" has no label to show'.format(fmt))

    # Every tile on the tab has to be in the registry, or it is a tile
    # nothing wires up - exactly what DGN and IMG were.
    for name in re.findall(r'x:Name="([A-Za-z0-9_]+)Tile"', layout):
        if name.lower() not in seen:
            fail.add('format_registry',
                     'the layout draws a "{0}Tile" that the registry does '
                     'not list, so nothing wires it up'.format(name))

    for gone in ('Dgn', 'Img'):
        if 'x:Name="{0}Check"'.format(gone) in layout:
            fail.add('format_registry',
                     '{0} was removed in 1.8.0 but is still drawn on the '
                     'Format tab'.format(gone.upper()))

    for fmt in getattr(module, 'VIEW_ONLY_FORMATS', ()):
        if fmt not in seen:
            fail.add('format_registry',
                     '"{0}" is listed as view only but is not a format'
                     .format(fmt))

    # Each tile carries a mark of its own. A duplicated tile whose
    # drawing was never changed is the easy mistake here, and it is the
    # kind nobody reports - two formats with the same icon just look
    # like a tool that could not be bothered.
    marks = {}
    for row in getattr(module, 'FORMATS', []):
        fmt, _tick, tile, _group, _panel, _label, _live = row
        opener = 'x:Name="{0}"'.format(tile)
        if opener not in layout:
            continue
        chunk = layout.split(opener, 1)[1].split('</Button>', 1)[0]
        if '<Canvas' not in chunk:
            fail.add('format_registry',
                     'the {0} tile draws no Canvas, so it has no mark'
                     .format(fmt))
            continue
        # The drawing alone. The label underneath carries the format's
        # own name, so leaving it in would make every tile look unique
        # however identical the picture above it.
        drawing = chunk.split('<Canvas', 1)[1].split('</Canvas>', 1)[0]
        # Everything but the page colour, which is allowed to be the only
        # thing two formats have in common.
        shape = re.sub(r'\{DynamicResource [A-Za-z0-9]+\}', '', drawing)
        shape = re.sub(r'\s+', ' ', shape).strip()
        if shape in marks:
            fail.add('format_registry',
                     'the {0} and {1} tiles are drawn identically; one of '
                     'them was copied and never changed'
                     .format(marks[shape], fmt))
        marks[shape] = fmt


# ==========================================================================
# rule 20 : sheets and views each get their own columns
#
# A view has no sheet number, no revision and no paper size. Showing the
# sheet columns in Views mode left three permanently empty columns taking
# half the grid, which is what 1.8.0 fixed.
# ==========================================================================

def rule_mode_columns(root, fail):
    module = _window_module(root, 'mode_columns', fail)
    if module is None:
        return
    window = getattr(module, 'ProSheetsWindow', None)
    if window is None:
        fail.add('mode_columns', 'ps_window declares no ProSheetsWindow')
        return

    known = set(getattr(window, 'KNOWN_COLUMNS', ()))
    for mode in ('sheets', 'views'):
        order = window.default_column_order(mode)
        if not order or order[0] != 'sel':
            fail.add('mode_columns',
                     'the {0} columns do not start with the tick column'
                     .format(mode))
        if 'fname' not in order:
            fail.add('mode_columns',
                     'the {0} columns have no Custom File Name column, so '
                     'there is no way to open the naming dialog'.format(mode))
        for col_id in order:
            if col_id not in known:
                fail.add('mode_columns',
                         '"{0}" is in the {1} columns but not in '
                         'KNOWN_COLUMNS, so a saved template holding it is '
                         'thrown away'.format(col_id, mode))

    # The columns a sheet list starts in. Parameter columns sit
    # between Size and Custom File Name, which reads last.
    extras = ['Current Revision Date', 'Series', 'Discipline']
    started = window.starting_columns('sheets', extras)
    for name in extras:
        if u'p:{0}'.format(name) not in started:
            fail.add('mode_columns',
                     '"{0}" is not among the columns a sheet list starts '
                     'with'.format(name))
    if started and started[-1] != 'fname':
        fail.add('mode_columns',
                 'Custom File Name is not the last starting column; it is '
                 'the one that reads best on the right')
    if started[:5] != ['sel', 'num', 'name', 'rev', 'size']:
        fail.add('mode_columns',
                 'the fixed sheet columns are no longer first: {0}'
                 .format(started[:5]))
    if window.starting_columns('views', extras) != \
            window.default_column_order('views'):
        fail.add('mode_columns',
                 'the sheet parameter columns are being added to the Views '
                 'list, where no view has a value for any of them')
    if window.starting_columns('sheets', []) != \
            window.default_column_order('sheets'):
        fail.add('mode_columns',
                 'a project with neither parameter named still gets extra '
                 'columns')
    if window.starting_columns('sheets', ['A', 'A', '']).count('p:A') != 1:
        fail.add('mode_columns',
                 'a parameter named twice becomes two columns')

    # The sort a list opens in. A template with its own sort keeps it;
    # anything else starts on the series, and the column is put back
    # where a template predating it left it out - you cannot sort on a
    # column that is not there, and abandoning the sort silently was
    # how a template from last week opened unsorted with nothing to
    # explain it.
    class SortStand(object):
        _apply_default_sort = window._apply_default_sort

        def __init__(self, order, stack, series='p:Series'):
            self.column_order = list(order)
            self.sort_stack = list(stack)
            self._series = series

        def series_column(self):
            return self._series

    stand = SortStand(['sel', 'num', 'p:Series', 'fname'], [])
    if not stand._apply_default_sort() or \
            stand.sort_stack != [('p:Series', False)]:
        fail.add('mode_columns',
                 'a list with no saved sort does not open on the series')

    stand = SortStand(['sel', 'num', 'rev', 'fname'], [])
    stand._apply_default_sort()
    if 'p:Series' not in stand.column_order:
        fail.add('mode_columns',
                 'the series column is not put back when a template left '
                 'it out, so the default sort has nothing to sort on')
    if stand.column_order[-1] != 'fname':
        fail.add('mode_columns',
                 'the series column was put after Custom File Name')
    if stand.sort_stack != [('p:Series', False)]:
        fail.add('mode_columns',
                 'the default sort was abandoned rather than the column '
                 'being put back')

    stand = SortStand(['sel', 'num', 'fname'], [('num', True)])
    if stand._apply_default_sort() or stand.sort_stack != [('num', True)]:
        fail.add('mode_columns',
                 "a template's own sort was overwritten by the default")

    stand = SortStand(['sel', 'num', 'fname'], [], series=None)
    if stand._apply_default_sort():
        fail.add('mode_columns',
                 'a project with no series parameter still got a default '
                 'sort')

    # And default_column_order stays the fixed set alone, because
    # _sane_order uses it to decide which fixed columns belong to a
    # mode - a parameter column in there comes back every time one is
    # removed.
    for mode in ('sheets', 'views'):
        for col_id in window.default_column_order(mode):
            if window.is_parameter_column(col_id):
                fail.add('mode_columns',
                         'default_column_order({0}) carries the parameter '
                         'column "{1}"; that belongs in starting_columns'
                         .format(mode, col_id))

    headings = dict([(entry[0], entry[1])
                     for entry in window.columns_for('views')])
    if headings.get('name') != u'View Name':
        fail.add('mode_columns',
                 'the Views mode name column is headed "{0}"; it should read '
                 '"View Name"'.format(headings.get('name')))
    for gone in ('num', 'rev', 'size'):
        if gone in headings:
            fail.add('mode_columns',
                     'the Views columns still carry "{0}", which no view '
                     'has a value for'.format(gone))

    # A template saved against sheets, opened in Views mode: the sheet-only
    # columns go, the parameter columns stay, and nothing is lost.
    class Stand(object):
        default_column_order = staticmethod(window.default_column_order)
        is_parameter_column = staticmethod(window.is_parameter_column)

        def _mode_name(self):
            return 'views'

    saved = ['sel', 'num', 'p:Discipline', 'name', 'rev', 'size', 'fname']
    order = window._sane_order(Stand(), saved, 'views')
    for gone in ('num', 'rev', 'size'):
        if gone in order:
            fail.add('mode_columns',
                     'a sheet template opened in Views mode keeps "{0}", '
                     'which would be an empty column'.format(gone))
    if 'p:Discipline' not in order:
        fail.add('mode_columns',
                 'a sheet template opened in Views mode loses the parameter '
                 'columns, which are the only part the user built by hand')
    if order and order[0] != 'sel':
        fail.add('mode_columns',
                 'the tick column does not come first after a mode swap')
    if 'fname' not in order:
        fail.add('mode_columns',
                 'Custom File Name is lost when a sheet template is opened '
                 'in Views mode')

    # And the other way: a views template opened against sheets has to get
    # Sheet Number, Revision and Size back rather than go without them.
    class SheetStand(Stand):
        def _mode_name(self):
            return 'sheets'

    order = window._sane_order(SheetStand(),
                               ['sel', 'name', 'p:Discipline', 'fname'],
                               'sheets')
    for wanted in ('num', 'rev', 'size'):
        if wanted not in order:
            fail.add('mode_columns',
                     'a views template opened in Sheets mode never gets '
                     '"{0}" back'.format(wanted))


# ==========================================================================
# rule 21 : the context menu stays dormant on Revit 2024
#
# IContextMenuCreator, ContextMenu, CommandMenuItem and
# RegisterContextMenu are all 2025 API. ps_context is imported from the
# extension's shared startup.py, and a startup.py that throws stops
# pyRevit loading every tool in the extension - so one of those names at
# the top of ps_context would not break this tool on 2024, it would break
# all of them.
# ==========================================================================

CONTEXT_ONLY_2025 = ('IContextMenuCreator', 'ContextMenu', 'CommandMenuItem')


def rule_context_menu_gate(root, fail):
    path = os.path.join(root, 'ps_context.py')
    if not os.path.isfile(path):
        fail.add('context_menu_gate', 'ps_context.py is missing')
        return
    body = read(path)
    try:
        tree = ast.parse(body)
    except Exception as err:
        fail.add('context_menu_gate',
                 'ps_context.py will not parse: {0}'.format(err))
        return

    for node in tree.body:
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        for alias in node.names:
            if alias.name in CONTEXT_ONLY_2025:
                fail.add('context_menu_gate',
                         '"{0}" is imported at the top of ps_context.py. It '
                         'does not exist before Revit 2025, so the import '
                         'throws at load and takes the shared startup.py - '
                         'and every tool in the extension - with it. Import '
                         'it inside a function, past the version gate.'
                         .format(alias.name))

    # The creator class has the same problem: a class statement is run at
    # import, so a 2025-only base class at module level is a load failure
    # on 2024 exactly like the import is.
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for base in node.bases:
            name = getattr(base, 'id', getattr(base, 'attr', None))
            if name in CONTEXT_ONLY_2025:
                fail.add('context_menu_gate',
                         'class {0} subclasses "{1}" at module level. That '
                         'base does not exist before Revit 2025 and the '
                         'class statement runs at import.'
                         .format(node.name, name))

    version = None
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if getattr(target, 'id', None) != 'MIN_VERSION':
                continue
            version = getattr(node.value, 'n', getattr(node.value, 'value',
                                                       None))
    if version is None:
        fail.add('context_menu_gate', 'ps_context declares no MIN_VERSION')
    elif version != 2025:
        fail.add('context_menu_gate',
                 'MIN_VERSION is {0}; the context menu API arrived in the '
                 'Revit 2025 API and nothing earlier has it'.format(version))

    for wanted in ('def register(', 'def available(', 'def audit(',
                   'def resolve_command('):
        if wanted not in body:
            fail.add('context_menu_gate',
                     'ps_context has no {0}...)'.format(wanted))

    # Resolving the command at registration rather than at right click
    # time is the bug that makes the entry stop working after a pyRevit
    # reload, because the generated assembly is rewritten under a new name.
    if 'resolve_command()' not in body.split('def build_menu(')[-1]:
        fail.add('context_menu_gate',
                 'build_menu does not call resolve_command. The command has '
                 'to be looked up on each right click: pyRevit rewrites its '
                 'generated assembly on every reload, so anything captured '
                 'at startup is stale.')

    fragment = os.path.join(root, 'startup_fragment.py')
    if not os.path.isfile(fragment):
        fail.add('context_menu_gate',
                 'startup_fragment.py is missing, so the delivery has no way '
                 'to say what goes in the shared startup.py')
        return
    text = read(fragment)
    if 'ps_context.register' not in text:
        fail.add('context_menu_gate',
                 'startup_fragment.py never calls ps_context.register')
    if 'try:' not in text or 'except Exception:' not in text:
        fail.add('context_menu_gate',
                 'the startup fragment is not wrapped. Anything pasted into '
                 'a shared startup.py has to swallow its own exceptions.')
    if '# ======' not in text:
        fail.add('context_menu_gate',
                 'the startup fragment is not banded, so there is no way to '
                 'see where it starts and stops in somebody else\'s file')


# ==========================================================================
# rule 32 : the context menu is registered on an object that has the method
#
# The 1.18.1 bug, and the reason the feature was invisible for nine
# releases. RegisterContextMenu is on UIApplication from Revit 2025, but it
# was only added to UIControlledApplication in 2026. ps_context was handed
# a UIControlledApplication and tested hasattr on it, so on Revit 2025 -
# the release the feature was asked for - the gate decided the API was
# missing and went dormant. Nothing threw and nothing was on screen to
# notice.
#
# So: the host is chosen by capability from several candidates, the
# fragment hands over every name pyRevit might have put it on, and there is
# a deferred route for the case where the types are present but no
# candidate carries the method.
# ==========================================================================

def rule_context_menu_host(root, fail):
    path = os.path.join(root, 'ps_context.py')
    if not os.path.isfile(path):
        fail.add('context_menu_host', 'ps_context.py is missing')
        return
    body = read(path)
    code = code_only(body)

    for wanted in ('def can_register(', 'def pick_host(', 'def _defer(',
                   'def api_present('):
        if wanted not in body:
            fail.add('context_menu_host',
                     'ps_context has no {0}...). The host has to be chosen '
                     'by capability: a 2025 UIControlledApplication has no '
                     'RegisterContextMenu, a 2025 UIApplication does.'
                     .format(wanted))

    # register() taking exactly one argument is the old shape, which cannot
    # be handed an alternative to try.
    if 'def register(*candidates)' not in body:
        fail.add('context_menu_host',
                 'register() does not take *candidates, so the caller cannot '
                 'offer both __revit__ and __uicontrolledapplication__ and '
                 'let ps_context pick the one this Revit put the method on')

    # The specific 1.18.1 line: a single assumed object asked whether it has
    # the method, with a dormant return when it does not. Matched on the
    # call rather than on the method name, because code_only blanks string
    # literals and the name is one.
    if re.search(r"hasattr\(\s*uiapp\s*,", code):
        fail.add('context_menu_host',
                 'ps_context tests hasattr(uiapp, "RegisterContextMenu") on '
                 'a single assumed object. That is the 1.18.1 bug: on Revit '
                 '2025 a UIControlledApplication answers no and the feature '
                 'goes dormant on the release it was built for. Ask each '
                 'candidate instead - can_register / pick_host.')

    # The deferred route is the whole point of surviving a no-candidate
    # answer, so it has to run after the gate rather than instead of it.
    tail = body.split('def register(')[-1]
    if 'api_present()' not in tail or '_defer(' not in tail:
        fail.add('context_menu_host',
                 'register() does not fall back to the deferred route. Where '
                 'the context menu types are present but no candidate has '
                 'the method, ApplicationInitialized is the first moment a '
                 'UIApplication can be built.')

    if 'ApplicationInitialized' not in body:
        fail.add('context_menu_host',
                 'nothing waits on ApplicationInitialized, so a Revit 2025 '
                 'given only a UIControlledApplication has no route at all')

    # IronPython does not reliably find the same handler again to detach,
    # and a half-detached handler is worse than one left attached.
    if re.search(r'ApplicationInitialized\s*-=', code):
        fail.add('context_menu_host',
                 'ApplicationInitialized is detached with -=. IronPython '
                 'does not reliably match the handler, and already_registered '
                 'already makes a second pass a no-op.')

    # Registering from a pushbutton is reported not to call BuildContextMenu
    # back. If somebody adds it as a second anchor it will look like it
    # works and the entry will do nothing.
    if re.search(r'def\s+\w*audit\w*\([^)]*\)[\s\S]{0,400}?RegisterContextMenu',
                 code):
        fail.add('context_menu_host',
                 'audit() calls RegisterContextMenu. Registering once the '
                 'tool is running does not work - the item appears but '
                 'BuildContextMenu is never called back. It has to happen '
                 'while Revit is building its UI.')

    if "ITEM_TEXT = u'Print in ProSheets'" not in body:
        fail.add('context_menu_host',
                 'ITEM_TEXT is not "Print in ProSheets"')

    fragment = os.path.join(root, 'startup_fragment.py')
    if not os.path.isfile(fragment):
        fail.add('context_menu_host', 'startup_fragment.py is missing')
        return
    text = read(fragment)
    # Matched against the candidate list the fragment actually iterates,
    # not against the file as a whole: both names appear in the fragment's
    # own log messages, so a plain "is it mentioned" check passes even
    # when one of them has been dropped from the list.
    offered = ''
    for group in re.findall(r'for\s+\w+\s+in\s*\(([^)]*)\)\s*:', text):
        if '__' in group:          # the candidate loop, not the step loop
            offered = group
            break
    for name in ('__revit__', '__uicontrolledapplication__'):
        if name not in offered:
            fail.add('context_menu_host',
                     'the startup fragment never offers {0} as a candidate. '
                     'Which name carries RegisterContextMenu depends on the '
                     'Revit release and the pyRevit build, so both are '
                     'passed.'.format(name))
    if 'register(*' not in text:
        fail.add('context_menu_host',
                 'the startup fragment does not unpack its candidates into '
                 'register(), so only one of them is ever tried')

    # A fragment that cannot reach ps_context cannot use ps_context's log,
    # so it has to carry its own. Without it, "the block is in the wrong
    # startup.py" and "the block was never pasted" look identical: no log
    # file at all. That cost a round trip on Revit 2026.
    if 'def _rb_note(' not in text:
        fail.add('context_menu_host',
                 'the startup fragment has no fallback log of its own. Every '
                 'failure before "import ps_context" succeeds is then '
                 'completely silent and cannot be told apart from the block '
                 'never having been pasted.')
    if 'APPDATA' not in text:
        fail.add('context_menu_host',
                 'the fragment\'s fallback log does not write to APPDATA, so '
                 'it will not land beside the tool\'s own log')
    if text.count('except Exception') < 3:
        fail.add('context_menu_host',
                 'the fragment does not wrap its own logging. Anything '
                 'pasted into a shared startup.py has to swallow every '
                 'exception it can raise, including from the code that '
                 'reports exceptions.')

    # Assuming startup.py sits exactly at the extension root is a silent
    # failure when it does not.
    if 'dirname' not in text or text.count('dirname') < 2:
        fail.add('context_menu_host',
                 'the fragment does not walk up looking for the tool folder. '
                 'A startup.py one folder away from where it was expected '
                 'then fails with nothing on screen and nothing in a log.')


# ==========================================================================
# rule 22 : no delivery ships a shared and singular file
#
# Straight out of the shared files rule in the project. These are the
# files there is exactly one of per extension, and a tool that ships one
# silently deletes whatever the last tool put in it. Nothing fails at the
# time; the feature that lived there just stops existing.
# ==========================================================================

SHARED_FILES = {
    'startup.py': 'the extension owns it, and the easter egg is armed in it',
    'shutdown.py': 'the extension owns it',
}


def _delivery_root(root):
    """The extension folder if this is a real tree, else the tool folder."""
    here = os.path.abspath(root)
    for _step in range(6):
        if here.lower().endswith('.extension'):
            return here
        parent = os.path.dirname(here)
        if parent == here:
            break
        here = parent
    return os.path.abspath(root)


def rule_shared_files(root, fail):
    base = _delivery_root(root)
    for folder, folders, files in os.walk(base):
        name = os.path.basename(folder)
        if name in ('__pycache__', '.git'):
            folders[:] = []
            continue
        if name.lower() == 'hooks':
            fail.add('shared_files',
                     'the delivery carries a hooks folder. Hooks are shared '
                     'and singular: shipping one replaces whatever the last '
                     'tool put there, and nothing reports it.')
            folders[:] = []
            continue
        for entry in files:
            if entry in SHARED_FILES:
                fail.add('shared_files',
                         'the delivery carries {0} - {1}. Ship a banded '
                         'fragment to paste in, not the file.'
                         .format(entry, SHARED_FILES[entry]))
            if entry == '__init__.py' and name == 'revobim':
                fail.add('shared_files',
                         'the delivery carries lib\\revobim\\__init__.py. '
                         'IronPython 2.7 has no namespace packages, so '
                         'replacing it stops every shared module importing '
                         'at once.')
            if entry == 'bundle.yaml':
                lowered = name.lower()
                if lowered.endswith('.panel') or lowered.endswith('.pulldown'):
                    fail.add('shared_files',
                             'the delivery carries {0}\\bundle.yaml. That '
                             'panel already exists, so shipping its bundle '
                             'reverts its title and icon.'.format(name))


# ==========================================================================
# rule 23 : the known-driver match is neither deaf nor greedy
#
# "diroots.prosheets" is the one installed printer this tool claims to
# know something about, and both ways of getting it wrong are quiet. Too
# strict and a machine that has it gets the built-in exporter by default
# and nobody notices. Too loose and a plain PDF24 printer is announced as
# "already set not to ask where to save", which is exactly the advice that
# wastes an afternoon.
# ==========================================================================

def rule_known_printers(root, fail):
    saved_path = list(sys.path)
    stubs = install_stubs()
    sys.path.insert(0, root)
    for name in ('ps_refs', 'ps_paths', 'ps_export'):
        sys.modules.pop(name, None)
    try:
        import ps_export
    except Exception as err:
        fail.add('known_printers',
                 'could not load ps_export: {0}'.format(err))
        return
    finally:
        remove_stubs(stubs)
        sys.path[:] = saved_path

    should_match = [
        'diroots.prosheets',
        'DiRoots.ProSheets',
        'diroots prosheets',
        'DiRoots ProSheets (redirected 2)',
        'diroots.prosheets on WORKSTATION',
    ]
    should_not = [
        'PDF24',
        'PDF24 PDF',
        'Microsoft Print to PDF',
        'Adobe PDF',
        'Bluebeam PDF',
        'DiRoots Reroot',
        'ProSheets',
        '',
    ]

    for name in should_match:
        if ps_export.known_printer(name) is None:
            fail.add('known_printers',
                     '"{0}" is the ProSheets driver and was not recognised, '
                     'so a machine that has it would be left on the built-in '
                     'exporter'.format(name))
    for name in should_not:
        if ps_export.known_printer(name) is not None:
            fail.add('known_printers',
                     '"{0}" was announced as a known good driver. It is not '
                     'one, and the note tells the user it does not prompt.'
                     .format(name))

    picked = ps_export.preferred_printer(
        ['Microsoft Print to PDF', 'PDF24', 'diroots.prosheets', 'Adobe PDF'])
    if picked != 'diroots.prosheets':
        fail.add('known_printers',
                 'preferred_printer picked "{0}" out of a list holding the '
                 'ProSheets driver'.format(picked))
    if ps_export.preferred_printer(['PDF24', 'Adobe PDF']):
        fail.add('known_printers',
                 'preferred_printer found something in a list with no known '
                 'driver in it')
    if ps_export.preferred_printer([]):
        fail.add('known_printers',
                 'preferred_printer found something in an empty list')

    # The run that cannot write anything, which has to be caught before
    # it starts rather than reported once per sheet afterwards.
    window_module = _window_module(root, 'known_printers', fail)
    window = getattr(window_module, 'ProSheetsWindow', None) \
        if window_module is not None else None
    if window is not None:
        blocked = [
            ('a driver with no folder', ['pdf'], 'PDF24', '', True),
            ('a driver with a folder', ['pdf'], 'PDF24', 'C:\\stage', False),
            ("Revit's own exporter", ['pdf'],
             'Revit built-in PDF export', '', False),
            ('nothing chosen', ['pdf'], '', '', False),
            ('no PDF in the run', ['dwg'], 'PDF24', '', False),
            ('a folder of only spaces', ['pdf'], 'PDF24', '   ', True),
        ]
        for label, formats, printer, staging, wanted in blocked:
            got = bool(window.pdf_blocked(formats, printer, staging))
            if got != wanted:
                fail.add('known_printers',
                         '{0}: blocked is {1}, wanted {2}'
                         .format(label, got, wanted))

    # A template carrying a driver this machine cannot use. Obeying it
    # is a run that fails on every sheet; falling back to the built-in
    # exporter is a run that works and a line saying what changed.
    if window is not None:
        # prefer_native on is the shipped default: a template's driver
        # never overrides the machine's choice of the built-in
        # exporter. The rest of the table is with it off, which is what
        # somebody who has deliberately opted into a driver gets.
        cases = [
            ('the house default refuses a template driver',
             ('PDF24', 'C:\\stage', ['PDF24'], True, True),
             ('', 'PDF24', 'prefer-native')),
            ('no printer named, house default',
             ('', '', ['PDF24'], True, True), ('', '', '')),
            ('an old Revit keeps the driver even so',
             ('PDF24', '', ['PDF24'], False, True), ('PDF24', '', '')),
            ('a driver with a folder here, opted in',
             ('PDF24', 'C:\\stage', ['PDF24'], True, False),
             ('PDF24', '', '')),
            ('a driver with no folder here, opted in',
             ('PDF24', '', ['PDF24'], True, False),
             ('', 'PDF24', 'no-folder')),
            ('a driver not installed here, opted in',
             ('Bluebeam', 'C:\\stage', ['PDF24'], True, False),
             ('', 'Bluebeam', 'not-installed')),
            ('no printer named, opted in',
             ('', '', ['PDF24'], True, False), ('', '', '')),
            ('no built-in exporter to fall back to',
             ('PDF24', '', ['PDF24'], False, False), ('PDF24', '', '')),
            ('a folder of only spaces, opted in',
             ('PDF24', '   ', ['PDF24'], True, False),
             ('', 'PDF24', 'no-folder')),
        ]
        for label, given, wanted in cases:
            got = tuple(window.usable_printer(*given))
            if got != wanted:
                fail.add('known_printers',
                         '{0}: got {1}, wanted {2}'
                         .format(label, got, wanted))

    known = ps_export.known_printer('diroots.prosheets')
    if known is not None and not known[1]:
        fail.add('known_printers',
                 'the ProSheets driver is marked as needing no staging '
                 'folder. It is a PDF24 instance, so it still writes to '
                 'PDF24\'s own output folder rather than the path Revit '
                 'asks for.')


# ==========================================================================
# rule 24 : runs of matching values, and what is not one
#
# Colouring every distinct value is what makes automatic grouping worse
# than none: sort by Sheet Number, where nothing repeats, and you get a
# heading per row. A run of one is not a run.
# ==========================================================================

def rule_value_runs(root, fail):
    module = _window_module(root, 'value_runs', fail)
    if module is None:
        return
    window = getattr(module, 'ProSheetsWindow', None)
    if window is None:
        fail.add('value_runs', 'ps_window declares no ProSheetsWindow')
        return

    cases = [
        ('nothing at all', [], []),
        ('one row', ['A'], [('A', 0, 1)]),
        ('all the same', ['A', 'A', 'A'], [('A', 0, 3)]),
        ('all different', ['A', 'B', 'C'],
         [('A', 0, 1), ('B', 1, 1), ('C', 2, 1)]),
        ('a run then a singleton',
         ['A', 'A', 'B'], [('A', 0, 2), ('B', 2, 1)]),
        ('two runs touching',
         ['A', 'A', 'B', 'B'], [('A', 0, 2), ('B', 2, 2)]),
        ('a singleton between two runs',
         ['A', 'A', 'B', 'C', 'C'],
         [('A', 0, 2), ('B', 2, 1), ('C', 3, 2)]),
        ('blanks are a value like any other',
         ['', '', 'A'], [('', 0, 2), ('A', 2, 1)]),
        # Runs are consecutive, not distinct. After a sort the two are
        # the same thing, but building them from distinct values means a
        # value that reappears swallows everything in between.
        ('a value that comes back later starts a new run',
         ['A', 'B', 'A'], [('A', 0, 1), ('B', 1, 1), ('A', 2, 1)]),
    ]
    for label, given, wanted in cases:
        try:
            got = window.value_runs(given)
        except Exception as err:
            fail.add('value_runs', '{0}: threw {1}'.format(label, err))
            continue
        if list(got) != wanted:
            fail.add('value_runs',
                     '{0}: got {1}, wanted {2}'.format(label, got, wanted))

    # Every row has to land in exactly one run, or rows go missing from
    # the grid without anything reporting it.
    given = ['A', 'A', 'B', 'C', 'C', 'C', 'D']
    covered = 0
    for _label, start, count in window.value_runs(given):
        covered += count
    if covered != len(given):
        fail.add('value_runs',
                 'the runs cover {0} of {1} rows'.format(covered, len(given)))

    # Every distinct value gets a heading of its own, including the ones
    # that turn up once, so that every value can be collapsed.
    if not window.is_group(1):
        fail.add('value_runs',
                 'a value that appears once gets no heading, so it cannot be '
                 'collapsed like every other value can')
    if not window.is_group(2):
        fail.add('value_runs', 'a run of two does not count as a group')


# ==========================================================================
# rule 25 : the theme follows Revit, and keeps following it
#
# The bug this exists to stop is subtle: saving the resolved palette
# rather than the chosen mode. Everything looks right - the window opens
# in Revit's theme - until somebody touches the chip once, after which
# "follow" has been overwritten with "dark" and it never follows again.
# ==========================================================================

def rule_theme_modes(root, fail):
    saved_path = list(sys.path)
    stubs = install_stubs()
    sys.path.insert(0, root)
    for name in ('ps_refs', 'theme'):
        sys.modules.pop(name, None)
    try:
        import theme as theme_module
    except Exception as err:
        fail.add('theme_modes', 'could not load theme: {0}'.format(err))
        return
    finally:
        remove_stubs(stubs)
        sys.path[:] = saved_path

    for given, wanted in ((None, 'follow'), ('', 'follow'),
                          ('follow', 'follow'), ('FOLLOW', 'follow'),
                          (' dark ', 'dark'), ('light', 'light'),
                          ('nonsense', 'follow')):
        got = theme_module.mode(given)
        if got != wanted:
            fail.add('theme_modes',
                     'theme.mode({0!r}) is {1!r}, wanted {2!r}'
                     .format(given, got, wanted))

    body = read(os.path.join(root, 'ps_window.py'))
    if "settings.set('theme_mode', self.theme_name)" in body \
            or "settings.set('theme', self.theme_name)" in body:
        fail.add('theme_modes',
                 'ps_window saves the resolved palette as the theme setting. '
                 'That overwrites "follow" the first time the chip is '
                 'touched and the window never follows Revit again - save '
                 'self.theme_mode.')
    if "settings.set('theme_mode', self.theme_mode)" not in body:
        fail.add('theme_modes', 'ps_window never saves the theme mode')
    if "text('theme_mode')" not in body:
        fail.add('theme_modes',
                 'ps_window reads the pre-1.10.0 "theme" key. The chip used '
                 'to write the resolved palette into it, so a value there '
                 'cannot be told apart from a deliberate pin and everybody '
                 'who ever clicked the chip stays pinned after upgrading.')

    window_module = _window_module(root, 'theme_modes', fail)
    if window_module is None:
        return
    window = getattr(window_module, 'ProSheetsWindow', None)
    modes = list(getattr(window, 'THEME_MODES', []))
    if modes[:1] != ['follow']:
        fail.add('theme_modes',
                 'the chip does not start on follow, so the house standard '
                 'of matching Revit\'s canvas is not the default')
    for wanted in ('dark', 'light'):
        if wanted not in modes:
            fail.add('theme_modes',
                     'the chip cannot be pinned to {0}'.format(wanted))

    for wanted in ('def _start_theme_watch(', 'def _theme_tick('):
        if wanted not in body:
            fail.add('theme_modes',
                     'ps_window has no {0}...), so the window stops '
                     'following Revit the moment it is open'.format(wanted))
    if '_theme_timer.Stop()' not in body:
        fail.add('theme_modes',
                 'the theme watch timer is never stopped, so it keeps '
                 'ticking against a closed window')


# ==========================================================================
# rule 26 : Windows never gets to paint any of this
#
# Two ways the OS chrome gets back in, and both of them look like
# nothing until something is selected.
#
# A local null on a Style property is the first. WPF treats it as a value
# rather than as "unset", and a local value stops the implicit style
# applying - so the element drops to the default template. An unstyled
# DataGridCell is transparent and invisible on a dark grid right up to
# the moment it is selected, when it paints itself with the system
# highlight. That is the white bar across the selected row in 1.10.0,
# and the light grey lozenge where the Custom File Name heading should
# have been in 1.6.0. Same mechanism, two releases apart.
#
# SystemColors is the second. Anything that does fall back paints its
# selection from there, and the inactive variant on Windows 10 and 11 is
# near white - which is what a grid that has just lost focus to a column
# heading is showing.
# ==========================================================================

STYLE_PROPERTIES = ('Style', 'CellStyle', 'RowStyle', 'HeaderStyle',
                    'ColumnHeaderStyle', 'ElementStyle',
                    'EditingElementStyle', 'CellTemplate', 'ItemContainerStyle')

STYLE_NULL = re.compile(
    r'\.(' + '|'.join(STYLE_PROPERTIES) + r')\s*=\s*None\b')

STYLE_LOOKUP = re.compile(
    r'\.(' + '|'.join(STYLE_PROPERTIES) + r')\s*=\s*[^\n]*TryFindResource')

SYSTEM_COLOUR_KEYS = ('HighlightBrushKey', 'HighlightTextBrushKey',
                      'InactiveSelectionHighlightBrushKey',
                      'InactiveSelectionHighlightTextBrushKey')


def code_only(text):
    """The source with every string and comment blanked out.

    Line numbers are preserved. Without this the rule below reads its own
    explanation in a docstring - "never element.Style = TryFindResource"
    - as an instance of the thing it is warning about.
    """
    lines = text.split('\n')
    try:
        import tokenize
        import io as _io
        readline = _io.StringIO(text).readline
        for token in tokenize.generate_tokens(readline):
            kind, _value, start, end, _raw = token
            if kind not in (tokenize.STRING, tokenize.COMMENT):
                continue
            first, column = start
            last, end_column = end
            for number in range(first, last + 1):
                line = lines[number - 1]
                begin = column if number == first else 0
                stop = end_column if number == last else len(line)
                lines[number - 1] = (line[:begin]
                                     + ' ' * (stop - begin)
                                     + line[stop:])
    except Exception:
        # A file this cannot tokenise is one rule_python_dialect has
        # already failed on; scanning it raw is no worse than not at all.
        return text
    return '\n'.join(lines)


def rule_selection_chrome(root, fail):
    for path in source_files(root):
        base = os.path.basename(path)
        for line_number, line in enumerate(
                code_only(read(path)).split('\n'), 1):
            found = STYLE_NULL.search(line)
            if found:
                fail.add('selection_chrome',
                         '{0} line {1} assigns None to {2}. A local null on '
                         'a style property is a value, not "unset", so it '
                         'stops the implicit style applying and the element '
                         'drops to OS chrome - invisible until it is '
                         'selected, then white. Leave the property alone '
                         'instead.'.format(base, line_number, found.group(1)))
            found = STYLE_LOOKUP.search(line)
            if found:
                fail.add('selection_chrome',
                         '{0} line {1} assigns a TryFindResource straight to '
                         '{2}. That lookup returns null when the key is '
                         'missing, which is the same local null again. Hold '
                         'it in a variable and only assign it when it is '
                         'not None.'.format(base, line_number,
                                            found.group(1)))

    body = read(os.path.join(root, 'theme.py'))
    if 'SystemColors' not in body:
        fail.add('selection_chrome',
                 'theme.py never touches SystemColors, so anything that '
                 'falls back to a default template paints its selection in '
                 'the OS colours. The inactive one on Windows 10 and 11 is '
                 'near white, which is what a grid shows the moment focus '
                 'moves to a column heading.')
        return
    for key in SYSTEM_COLOUR_KEYS:
        if key not in body:
            fail.add('selection_chrome',
                     'theme.py does not override SystemColors.{0}'.format(key))
    if 'apply_system_colours' not in body:
        fail.add('selection_chrome',
                 'theme.py has no apply_system_colours, so the overrides '
                 'cannot follow a live palette swap')


# ==========================================================================
# rule 27 : a colour per group, and a heading its text can be read on
#
# The heading band is the quiet tone and the cell is the loud one, which
# is the opposite of what it looks like it should be. Heading text is
# blue; blue on a saturated green or teal band cannot be read at all. Get
# those two the wrong way round and the group labels disappear into their
# own colour.
# ==========================================================================

HEX_COLOUR = re.compile(r'^#[0-9A-F]{6}$')


def _channels(text):
    return (int(text[1:3], 16), int(text[3:5], 16), int(text[5:7], 16))


def _lightness(text):
    red, green, blue = _channels(text)
    return (max(red, green, blue) + min(red, green, blue)) / 510.0


def rule_group_colours(root, fail):
    saved_path = list(sys.path)
    stubs = install_stubs()
    sys.path.insert(0, root)
    for name in ('ps_refs', 'theme'):
        sys.modules.pop(name, None)
    try:
        import theme as theme_module
    except Exception as err:
        fail.add('group_colours', 'could not load theme: {0}'.format(err))
        return
    finally:
        remove_stubs(stubs)
        sys.path[:] = saved_path

    count = getattr(theme_module, 'GROUP_HUES', 0)
    if count < 8:
        fail.add('group_colours',
                 'only {0} group colours, which a discipline column runs '
                 'through before it is halfway down'.format(count))

    for name in ('dark', 'light'):
        seen = {}
        for index in range(count):
            cell = theme_module.group_colour(index, name)
            head = theme_module.group_colour(index, name, heading=True)
            for text, what in ((cell, 'cell'), (head, 'heading')):
                if not HEX_COLOUR.match(u'{0}'.format(text)):
                    fail.add('group_colours',
                             '{0} group {1} {2} is "{3}", not a hex colour'
                             .format(name, index, what, text))
                    return
            if cell in seen:
                fail.add('group_colours',
                         '{0} groups {1} and {2} are both {3}'
                         .format(name, seen[cell], index, cell))
            seen[cell] = index

            # The heading carries blue text, so in dark mode it has to be
            # darker than the cell and in light mode lighter. Getting this
            # backwards puts blue on a saturated band.
            if name == 'dark' and _lightness(head) >= _lightness(cell):
                fail.add('group_colours',
                         'dark group {0}: the heading band is no darker than '
                         'the cell, so the blue heading text sits on a '
                         'saturated colour and cannot be read'.format(index))
            if name == 'light' and _lightness(head) <= _lightness(cell):
                fail.add('group_colours',
                         'light group {0}: the heading band is no lighter '
                         'than the cell'.format(index))

        # Neighbours are what actually have to be told apart.
        for index in range(count - 1):
            first = _channels(theme_module.group_colour(index, name))
            second = _channels(theme_module.group_colour(index + 1, name))
            gap = sum([abs(a - b) for a, b in zip(first, second)])
            if gap < 24:
                fail.add('group_colours',
                         '{0} groups {1} and {2} are too close to tell '
                         'apart'.format(name, index, index + 1))

        # And it has to keep answering past the end of the ramp.
        if theme_module.group_colour(count, name) != \
                theme_module.group_colour(0, name):
            fail.add('group_colours',
                     '{0} does not cycle cleanly at {1}'.format(name, count))

    layout = read(os.path.join(root, THEME_FILE))
    if 'ChipButtonOn' not in layout:
        fail.add('group_colours',
                 'Theme.xaml has no ChipButtonOn, so Collapse all cannot '
                 'show that grouping is live')
    # Read inside the GridCell style itself, not the whole file. From
    # 1.20.0 the register's RegisterRow style carries an ishead trigger
    # too, and a whole-file search was satisfied by that one with the
    # cell's own trigger gone - the selftest caught the rule passing for
    # the wrong reason.
    cell_style = re.search(r'<Style x:Key="GridCell".*?</Style>', layout, re.S)
    cell_style = cell_style.group(0) if cell_style else ''
    if 'Binding="{Binding ishead}"' not in cell_style:
        fail.add('group_colours',
                 'no heading DataTrigger in Theme.xaml. The cell style sets '
                 'Foreground and FontSize explicitly, and an explicit setter '
                 'beats anything the row hands down by inheritance, so blue '
                 'heading text set on the row alone would never show.')


# ==========================================================================
# rule 28 : a heading's tick is the group's tick
#
# Both directions matter. Ticking the heading has to reach every member
# including the ones a collapsed group is hiding - a tick that quietly
# meant "all but the ones you cannot see" would be a trap. And ticking
# the last member by hand has to light the heading, or the heading is
# telling you something that is no longer true.
# ==========================================================================

class _Row(dict):
    """Something that behaves enough like a DataRow for the tick logic."""


def rule_group_ticks(root, fail):
    module = _window_module(root, 'group_ticks', fail)
    if module is None:
        return
    window = getattr(module, 'ProSheetsWindow', None)
    if window is None:
        fail.add('group_ticks', 'ps_window declares no ProSheetsWindow')
        return

    def heading(gid, ticked):
        return _Row({'gid': gid, 'ishead': '1', 'sel': ticked, 'key': ''})

    def sheet(ticked):
        return _Row({'gid': '', 'ishead': '', 'sel': ticked, 'key': '7'})

    class Stand(object):
        _suspend_ticks = False
        _as_int = window._as_int
        _is_heading = window._is_heading
        _tick_group = window._tick_group
        _sync_group_ticks = window._sync_group_ticks

        def __init__(self, groups, rows):
            self.groups = groups
            self.table = type('T', (object,), {'Rows': rows})()

    # Ticking a heading ticks the group, hidden members included.
    members = [sheet(False), sheet(False), sheet(False)]
    head = heading('1', True)
    stand = Stand({1: members}, [head] + members)
    stand._tick_group(head)
    if not all([bool(m['sel']) for m in members]):
        fail.add('group_ticks',
                 'ticking a group heading did not tick its members')

    # And unticking unticks.
    head['sel'] = False
    stand._tick_group(head)
    if any([bool(m['sel']) for m in members]):
        fail.add('group_ticks',
                 'unticking a group heading did not untick its members')

    # A heading whose group is not all ticked must not read as ticked.
    members = [sheet(True), sheet(False)]
    head = heading('1', True)
    stand = Stand({1: members}, [head] + members)
    stand._sync_group_ticks()
    if bool(head['sel']):
        fail.add('group_ticks',
                 'a heading reads as ticked while one of its members is not')

    # Tick the last one and the heading follows.
    members[1]['sel'] = True
    stand._sync_group_ticks()
    if not bool(head['sel']):
        fail.add('group_ticks',
                 'ticking the last member of a group left its heading '
                 'unticked')

    # A heading with no members behind it is never ticked.
    head = heading('9', True)
    stand = Stand({}, [head])
    stand._sync_group_ticks()
    if bool(head['sel']):
        fail.add('group_ticks', 'a heading with no group reads as ticked')

    # The click that reaches the tick box. _row_click runs on
    # PreviewMouseLeftButtonDown, before the CheckBox sees anything, and
    # sets Handled - so without this exception a heading's tick box can
    # only ever collapse the group, which is what 1.11.1 shipped.
    cases = [
        ('a heading, not on the tick box', (True, True, False), True),
        ('a heading, on the tick box', (True, True, True), False),
        ('an ordinary row', (True, False, False), False),
        ('an ordinary row tick box', (True, False, True), False),
        ('grouping off', (False, True, False), False),
        ('grouping off, on the tick box', (False, True, True), False),
    ]
    for label, given, wanted in cases:
        got = bool(window.wants_collapse(*given))
        if got != wanted:
            fail.add('group_ticks',
                     'clicking {0}: collapse is {1}, wanted {2}'
                     .format(label, got, wanted))

    # A tick on a row inside a highlighted block applies to the block;
    # one outside it applies to itself alone, or a tick would reach
    # rows highlighted for some unrelated reason.
    spread = [
        ('inside a block of three', '2', ['1', '2', '3'], set(['1', '2', '3'])),
        ('outside the block', '9', ['1', '2', '3'], set(['9'])),
        ('a block of one', '1', ['1'], set(['1'])),
        ('nothing highlighted', '4', [], set(['4'])),
        ('keys that are not strings', 2, [1, 2, 3], set(['1', '2', '3'])),
    ]
    for label, changed, picked, wanted in spread:
        got = window.tick_targets(changed, set(picked))
        if got != wanted:
            fail.add('group_ticks',
                     'ticking {0}: reached {1}, wanted {2}'
                     .format(label, sorted(got), sorted(wanted)))

    # The colour a Create row ends up in as files land. A failure has
    # to win and to stay won: a row that went green because the DWG
    # landed, while its PDF did not, is a row that lies.
    states = [
        ('first success', ('', True), 'done'),
        ('first failure', ('', False), 'failed'),
        ('a success after a success', ('done', True), 'done'),
        ('a failure after a success', ('done', False), 'failed'),
        ('a success after a failure', ('failed', True), 'failed'),
        ('a failure after a failure', ('failed', False), 'failed'),
    ]
    for label, given, wanted in states:
        got = window.plan_state(*given)
        if got != wanted:
            fail.add('group_ticks',
                     '{0}: row goes {1}, wanted {2}'
                     .format(label, got, wanted))

    # And the sync must leave real sheets alone.
    members = [sheet(True), sheet(True)]
    loose = sheet(False)
    head = heading('1', False)
    stand = Stand({1: members}, [head, loose] + members)
    stand._sync_group_ticks()
    if bool(loose['sel']):
        fail.add('group_ticks',
                 'the heading sync ticked a sheet that is not in a group')


# ==========================================================================
# rule 29 : sorting turns grouping on, and lets go of what was collapsed
#
# Two things that are only noticed as confusion rather than as a fault.
# Sorting with grouping switched off gives a plain sorted list and no
# explanation, when sorting by a column and colouring its matching
# values are the same intent. And a group number is a position in one
# sort's list of values, so carrying the collapsed set across a sort
# reopens the list with unrelated groups shut.
# ==========================================================================

def rule_sort_groups(root, fail):
    module = _window_module(root, 'sort_groups', fail)
    if module is None:
        return
    window = getattr(module, 'ProSheetsWindow', None)
    if window is None:
        fail.add('sort_groups', 'ps_window declares no ProSheetsWindow')
        return

    class Stand(object):
        _ensure_grouped = window._ensure_grouped

        def __init__(self, grouped):
            self.grouped = grouped
            self._suspend_group_toggle = False

        def c(self, _name):
            return None

    stand = Stand(False)
    turned = stand._ensure_grouped()
    if not stand.grouped:
        fail.add('sort_groups',
                 'sorting does not turn grouping on, so a sort after the '
                 'tick box was cleared gives a plain list and no reason why')
    if not turned:
        fail.add('sort_groups',
                 '_ensure_grouped did not report that it turned grouping on')
    # The handler has to be let go of again, or the tick box stops
    # working for the rest of the session.
    if stand._suspend_group_toggle:
        fail.add('sort_groups',
                 'the grouping toggle is left suppressed, so the tick box '
                 'does nothing from here on')

    stand = Stand(True)
    if stand._ensure_grouped():
        fail.add('sort_groups',
                 '_ensure_grouped reports a change when grouping was '
                 'already on')

    body = read(os.path.join(root, 'ps_window.py'))
    sorting = body.split('def _on_sorting(', 1)[-1].split('\n    def ', 1)[0]
    if '_ensure_grouped()' not in sorting:
        fail.add('sort_groups', '_on_sorting never calls _ensure_grouped')
    if 'self.collapsed = set()' not in sorting:
        fail.add('sort_groups',
                 '_on_sorting does not clear the collapsed set. Group '
                 'numbers are positions in one sort\'s values, so the old '
                 'set shuts unrelated groups in the new one.')

    toggling = body.split('def toggle_grouping(', 1)[-1].split(
        '\n    def ', 1)[0]
    if '_suspend_group_toggle' not in toggling:
        fail.add('sort_groups',
                 'toggle_grouping does not honour the suppression flag, so '
                 'turning grouping on from a sort rebuilds the groups '
                 'against the order that sort is about to replace')


# ==========================================================================
# rule 30 : one module never calls something another module has not got
#
# ps_ui.theme_of() got as far as a shipped build. It sat in a branch
# that only runs when the user presses one button on one window, so
# importing the module proved nothing and neither did opening it. The
# name does not exist and never did.
#
# Every ps_x.something in this tool is checked against what ps_x
# actually defines. Static, so a branch nobody walked is checked exactly
# like one that runs on load.
# ==========================================================================

def _top_level_names(body, found):
    """Every name a list of statements binds, following the branches a
    module can take - if/else, try/except - but not descending into a
    function or a class, whose own names are local to it.
    """
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            found.add(node.name)
            continue
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    found.add(target.id)
                elif isinstance(target, (ast.Tuple, ast.List)):
                    for piece in target.elts:
                        if isinstance(piece, ast.Name):
                            found.add(piece.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            # A guarded import - "try: from ... import X / except: X = None"
            # for a name a given Revit may not have - defines X just as a
            # plain one does.
            for alias in node.names:
                found.add(alias.asname or alias.name.split('.')[0])
        for field in ('body', 'handlers', 'orelse', 'finalbody'):
            branch = getattr(node, field, None)
            if isinstance(branch, list) and branch and \
                    isinstance(branch[0], ast.AST):
                _top_level_names(branch, found)
    return found


def _module_names(path):
    """Everything a module defines at its top level."""
    try:
        tree = ast.parse(read(path))
    except Exception:
        return None
    return _top_level_names(tree.body, set())


def rule_module_calls(root, fail):
    known = {}
    for name in MODULES:
        path = os.path.join(root, name + '.py')
        if not os.path.isfile(path):
            continue
        names = _module_names(path)
        if names is not None:
            known[name] = names

    for path in source_files(root):
        base = os.path.basename(path)
        mine = os.path.splitext(base)[0]
        try:
            tree = ast.parse(read(path))
        except Exception:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            holder = node.value
            if not isinstance(holder, ast.Name):
                continue
            module = holder.id
            if module == mine or module not in known:
                continue
            if node.attr.startswith('__'):
                continue
            if node.attr not in known[module]:
                fail.add('module_calls',
                         '{0} uses {1}.{2}, which {1} does not define. A '
                         'name in a branch nobody walked is still a name '
                         'that is not there.'.format(base, module, node.attr))


# ==========================================================================
# rule 31 : nothing prints with a transaction open
#
# PrintManager.SubmitPrint() with a transaction still open prints
# nothing, and on Revit 2024 and later it does not complain - the call
# returns, at once, successfully, having done nothing. Two machines and
# two afternoons went on "SubmitPrint returned with no error" followed
# by no file. The paper size does need a transaction, so the shape has
# to be: open, set the paper, commit, then submit.
# ==========================================================================

def rule_print_outside_transaction(root, fail):
    body = read(os.path.join(root, 'ps_export.py'))
    cursor = 0
    while True:
        start = body.find('transaction.Start()', cursor)
        if start < 0:
            break
        commit = body.find('transaction.Commit()', start)
        if commit < 0:
            fail.add('print_outside_transaction',
                     'a transaction is started in ps_export and never '
                     'committed')
            break
        if 'SubmitPrint' in body[start:commit]:
            fail.add('print_outside_transaction',
                     'SubmitPrint is called between transaction.Start() and '
                     'transaction.Commit(). Revit 2024 and later return '
                     'from that immediately and successfully having '
                     'printed nothing, so the only symptom is a missing '
                     'file. Commit the print setup first.')
        cursor = commit + 1

    # And the timing check that makes the next one of these obvious in
    # the log rather than in a week of guessing.
    if 'too quick to have rendered a sheet' not in body:
        fail.add('print_outside_transaction',
                 'the debug log no longer flags an implausibly fast '
                 'SubmitPrint. That timing is what gave this away.')

    # How long a driver is given to write the file. A fixed fifteen
    # seconds declared failure on a sheet Revit had taken nine seconds
    # just to spool, and the PDF landed after the tool had moved on.
    saved_path = list(sys.path)
    stubs = install_stubs()
    sys.path.insert(0, root)
    for name in ('ps_refs', 'ps_paths', 'ps_export'):
        sys.modules.pop(name, None)
    try:
        import ps_export
    except Exception as err:
        fail.add('print_outside_transaction',
                 'could not load ps_export: {0}'.format(err))
        return
    finally:
        remove_stubs(stubs)
        sys.path[:] = saved_path

    cases = [
        ('an instant render still waits a real time', 0.1, 60.0),
        ('a nine second render waits about a minute', 9.0, 60.0),
        ('a thirty second render waits longer', 30.0, 180.0),
        ('a very slow render is capped', 600.0, 420.0),
        ('nonsense falls back to the floor', None, 60.0),
    ]
    for label, given, wanted in cases:
        got = ps_export.driver_wait_budget(given)
        if abs(got - wanted) > 0.01:
            fail.add('print_outside_transaction',
                     '{0}: waits {1:.0f}s, wanted {2:.0f}s'
                     .format(label, got, wanted))
    if ps_export.driver_wait_budget(9.0) < 30.0:
        fail.add('print_outside_transaction',
                 'the driver wait is short enough to declare failure while '
                 'a large sheet is still converting')


# ==========================================================================
# rule 33 : the Document Register reads and decides the way the paper does
#
# Run against made-up sheets and revisions, off Revit. The decisions are
# the Drawing Register's, which each cost a round trip the first time:
# the cell is what the sheet prints (GetRevisionNumberOnSheet, never the
# project-wide RevisionNumber), groups and tabs sit where their first
# drawing does rather than alphabetically, blanks go last, each tab shows
# only the revisions its drawings use, and the status letter is derived
# from the codes by majority.
# ==========================================================================

def _module_under_stubs(root, name, rule, fail):
    """One of the tool's modules imported against the stub API, or None."""
    saved_path = list(sys.path)
    stubs = install_stubs()
    sys.path.insert(0, root)
    for other in MODULES:
        sys.modules.pop(other, None)
    try:
        return __import__(name)
    except Exception as err:
        fail.add(rule, 'could not load {0}: {1}: {2}'
                 .format(name, err.__class__.__name__, err))
        return None
    finally:
        remove_stubs(stubs)
        sys.path[:] = saved_path


class _FakeId(object):
    def __init__(self, value):
        self.Value = value


class _FakeRevision(object):
    def __init__(self, number, sequence, date):
        self.Id = _FakeId(number)
        self.SequenceNumber = sequence
        self.RevisionDate = date
        self.Description = u'Issue {0}'.format(sequence)
        self.IssuedBy = u'AB'
        self.IssuedTo = u'Client'
        self.Issued = True

    @property
    def RevisionNumber(self):
        raise AssertionError('Revision.RevisionNumber was read. It is the '
                             'project-wide number, deprecated since 2022 and '
                             'gone in later releases; the cell has to be '
                             'GetRevisionNumberOnSheet.')


class _FakeSheet(object):
    def __init__(self, number, carried, current):
        self.number = number
        self._carried = carried          # {revision id: number on sheet}
        self._current = current

    def GetAllRevisionIds(self):
        return [_FakeId(key) for key in sorted(self._carried)]

    def GetRevisionNumberOnSheet(self, revision_id):
        return self._carried.get(revision_id.Value, u'')

    def GetCurrentRevision(self):
        return _FakeId(self._current)


class _FakeDoc(object):
    def __init__(self, revisions):
        self._revisions = dict([(rev.Id.Value, rev) for rev in revisions])

    def GetElement(self, element_id):
        return self._revisions.get(element_id.Value)


class _FakeSheetRow(object):
    def __init__(self, key, number, name, sheet):
        self.key = key
        self.number = number
        self.name = name
        self.element = sheet
        self.is_sheet = True
        self.size = u'A1'


def rule_register_logic(root, fail):
    module = _module_under_stubs(root, 'ps_register', 'register_logic', fail)
    if module is None:
        return

    # -- status letters
    cases = [
        ('one letter', ['P01', 'P02', 'P03'], 'P'),
        ('majority wins', ['P01', 'P02', 'C01'], 'P'),
        ('a tie goes to the alphabetically first', ['P01', 'C01'], 'C'),
        ('two letters', ['AB1', 'AB2'], 'AB'),
        ('lower case is read', ['p01'], 'P'),
        ('blanks are ignored', ['', 'C02', ''], 'C'),
        ('plain numbers have no letter', ['1', '2'], ''),
        ('an empty column has no letter', [], ''),
    ]
    for label, codes, wanted in cases:
        got = module.status_letter(codes)
        if got != wanted:
            fail.add('register_logic', 'status letter, {0}: got "{1}", '
                     'wanted "{2}"'.format(label, got, wanted))

    # -- groups in order of first appearance, blanks last
    class Row(object):
        def __init__(self, key, series=u'', discipline=u'', cells=None):
            self.key = key
            self.series = series
            self.discipline = discipline
            self.cells = cells or {}

    rows = [Row(1, '200', 'Mech'), Row(2, '100', 'Elec'), Row(3, '200', 'Mech'),
            Row(4, '', ''), Row(5, '100', 'Mech')]
    groups = module.first_appearance(rows, lambda row: row.series, u'(none)')
    got = [(label, [row.key for row in members]) for label, members in groups]
    wanted = [('200', [1, 3]), ('100', [2, 5]), ('(none)', [4])]
    if got != wanted:
        fail.add('register_logic',
                 'series groups: got {0}, wanted {1}. Groups go where their '
                 'first drawing is, every member gathered under them, and '
                 'blanks last - alphabetical order shuffles a register into '
                 'blocks that read wrong'.format(got, wanted))

    tabs = module.discipline_tabs(rows)
    labels = [label for label, _members in tabs]
    if labels != [module.ALL_TAB, 'Mech', 'Elec', module.NO_DISCIPLINE]:
        fail.add('register_logic',
                 'discipline tabs: got {0}. All comes first, then each '
                 'discipline where its first drawing is, then the blanks'
                 .format(labels))
    elif len(tabs[0][1]) != len(rows):
        fail.add('register_logic', 'the All tab does not hold every drawing')

    unfilled = [Row(1), Row(2)]
    if [label for label, _m in module.discipline_tabs(unfilled)] != \
            [module.ALL_TAB]:
        fail.add('register_logic',
                 'with no discipline filled in anywhere there should be only '
                 'the All tab, not a second tab holding the same drawings')

    # -- only the revisions a tab uses, in sequence order
    later = module.RevisionColumn(30, sequence=3)
    first = module.RevisionColumn(10, sequence=1)
    unused = module.RevisionColumn(20, sequence=2)
    used_rows = [Row(1, cells={later.key: 'P03'}),
                 Row(2, cells={first.key: 'P01', unused.key: ''})]
    got = [column.sequence for column in
           module.columns_used([later, unused, first], used_rows)]
    if got != [1, 3]:
        fail.add('register_logic',
                 'columns used: got sequences {0}, wanted [1, 3] - only '
                 'revisions a drawing on the tab carries, in sequence order'
                 .format(got))

    if [row.key for row in module.carrying(used_rows, later.key)] != [1]:
        fail.add('register_logic',
                 'a revision header click would tick the wrong drawings')

    # -- column keys never collide with the fixed columns
    for text, wanted in (('r123', True), ('rev', False), ('rdate', False),
                         ('r', False), ('key', False), ('ishead', False)):
        if bool(module.is_column_key(text)) != wanted:
            fail.add('register_logic',
                     '"{0}" is{1} taken for a revision column'.format(
                         text, '' if module.is_column_key(text) else ' not'))

    # -- Excel's filters: a set of allowed values, u'' for a blank cell,
    #    None for no filter at all
    row_values = {'num': u'M-100', 'r1': u''}
    for filters, wanted in (({'num': None}, True),
                            ({'num': set([u'M-100'])}, True),
                            ({'num': set([u'M-101'])}, False),
                            ({'r1': set([u''])}, True),
                            ({'r1': set([u'P01'])}, False),
                            ({'r9': set([u'P01'])}, True),
                            ({'num': set()}, False)):
        if module.passes(row_values, filters) != wanted:
            fail.add('register_logic',
                     'filter {0} on {1}: passes should be {2}'.format(
                         filters, row_values, wanted))
    choices = module.filter_choices([u'P-10', u'', u'P-9', u'P-10', u' '])
    if choices != [u'P-9', u'P-10', module.BLANKS]:
        fail.add('register_logic',
                 'a filter list of {0}; wanted each value once in natural '
                 'order, then (Blanks) once, last'.format(choices))

    # -- the All tab's headings: discipline, then series inside it
    tree = module.group_tree(rows, True, True)
    shape = [(label, [inner for inner, _r, _c in children])
             for label, _members, children in tree]
    if shape != [('Mech', ['200', '100']), ('Elec', ['100']),
                 (module.NO_DISCIPLINE, [])]:
        fail.add('register_logic',
                 'the All tab grouped as {0}; wanted each discipline with its '
                 'own series under it, in order of first appearance'.format(
                     shape))
    if [label for label, _m, _c in module.group_tree(rows, False, True)] != \
            ['200', '100', '(no series)']:
        fail.add('register_logic', 'a discipline tab is not grouped by series')
    plain = module.group_tree([Row(1), Row(2)], False, True)
    if [(label, len(members), children) for label, members, children
            in plain] != [(None, 2, [])]:
        fail.add('register_logic', 'a tab with no series values got headings')

    # -- which revision columns
    if [c.sequence for c in module.revisions_for(
            [later, unused, first], used_rows, True)] != [1, 3]:
        fail.add('register_logic', 'Hide unused did not keep only the used '
                 'revisions')
    if [c.sequence for c in module.revisions_for(
            [later, unused, first], used_rows, False)] != [1, 2, 3]:
        fail.add('register_logic', 'with Hide unused off, not every revision '
                 'is listed in sequence order')

    # -- the register's folder alongside a run: above PDF and DWG
    one_series = [u'C:\\Out\\NPE7\\2026-10-06_09_30\\570\\PDF',
                  u'C:\\Out\\NPE7\\2026-10-06_09_30\\570\\DWG']
    two_series = [u'C:\\Out\\NPE7\\2026-10-06_09_30\\570\\PDF',
                  u'C:\\Out\\NPE7\\2026-10-06_09_30\\520\\PDF']
    for given, per_format, wanted in (
            (one_series, True, u'C:\\Out\\NPE7\\2026-10-06_09_30\\570'),
            (one_series[:1], True, u'C:\\Out\\NPE7\\2026-10-06_09_30\\570'),
            (two_series, True, u'C:\\Out\\NPE7\\2026-10-06_09_30'),
            ([u'C:\\Out\\NPE7\\Issue'], False, u'C:\\Out\\NPE7\\Issue')):
        got = module.register_folder(given, per_format)
        if got != wanted:
            fail.add('register_logic',
                     'the register for {0} would go to "{1}", not "{2}" - it '
                     'belongs above the PDF and DWG folders, never inside '
                     'one'.format(given, got, wanted))

    # -- under "Included only" a discipline with nothing in has no tab
    members = [Row(1), Row(2)]
    for label, included, only, current, wanted in (
            (u'Mech', set(), False, False, True),
            (u'Mech', set(), True, False, False),
            (u'Mech', set([u'2']), True, False, True),
            (module.ALL_TAB, set(), True, False, True),
            (u'Mech', set(), True, True, True)):
        if module.tab_shows(label, members, included, only, current) != wanted:
            fail.add('register_logic',
                     'tab "{0}" with {1} included, included only {2}, on '
                     'screen {3}: shown should be {4}'.format(
                         label, sorted(included), only, current, wanted))

    # -- scale
    for given, wanted in (([], 'NTS'), ([100], '1:100'), ([100, 100], '1:100'),
                          ([50, 100], 'As Shown'), ([0], 'NTS')):
        got = module.scale_label(given)
        if got != wanted:
            fail.add('register_logic', 'scale for {0}: got "{1}", wanted '
                     '"{2}"'.format(given, got, wanted))

    # -- the read itself, against a fake model
    revisions = [_FakeRevision(501, 1, u'01/02/26'),
                 _FakeRevision(502, 2, u'15/03/26'),
                 _FakeRevision(503, 3, u'')]
    doc = _FakeDoc(revisions)
    sheets = [
        _FakeSheetRow(1, u'M-100', u'Ground', _FakeSheet(
            u'M-100', {501: u'P01', 502: u'P02'}, 502)),
        _FakeSheetRow(2, u'M-101', u'First', _FakeSheet(
            u'M-101', {502: u'C01'}, 502)),
    ]

    class _Revisions(object):
        @staticmethod
        def GetAllRevisionIds(_doc):
            return [rev.Id for rev in revisions]

    saved = (getattr(module, 'Revision', None), module.read_scales)
    module.Revision = _Revisions
    module.read_scales = lambda _doc: {1: u'1:50'}
    try:
        try:
            columns, rows = module.read_register(doc, sheets, u'', u'')
        except AssertionError as err:
            fail.add('register_logic', u'{0}'.format(err))
            return
        except Exception as err:
            fail.add('register_logic', 'read_register threw {0}: {1}'.format(
                err.__class__.__name__, err))
            return
    finally:
        module.Revision, module.read_scales = saved

    by_key = dict([(column.element_key, column) for column in columns])
    if sorted(by_key) != [501, 502, 503]:
        fail.add('register_logic', 'read {0} revisions, wanted all three'
                 .format(len(by_key)))
        return
    if rows[0].cells.get(by_key[501].key) != u'P01':
        fail.add('register_logic',
                 'the cell is not the number the sheet prints: got {0!r} for '
                 'P01. Only GetRevisionNumberOnSheet agrees with the sheet\'s '
                 'own revision schedule.'.format(
                     rows[0].cells.get(by_key[501].key)))
    if rows[0].current_key != by_key[502].key or rows[0].current != u'P02':
        fail.add('register_logic',
                 'the current revision is not picked out: key {0!r}, '
                 'number {1!r}'.format(rows[0].current_key, rows[0].current))
    if rows[0].current_date != u'15/03/26':
        fail.add('register_logic', 'the Rev Date column is not the current '
                 'revision\'s date')
    if rows[0].current_sequence != u'2':
        fail.add('register_logic', 'the Sequence Number column is {0!r}, not '
                 'the current revision\'s sequence number (2)'.format(
                     rows[0].current_sequence))
    for given, wanted in ((3, u'3'), (u'12', u'12'), (0, u''), (None, u''),
                          (u'x', u'')):
        if module.sequence_text(given) != wanted:
            fail.add('register_logic', 'sequence {0!r} shown as {1!r}'.format(
                given, module.sequence_text(given)))
    if rows[0].scale != u'1:50' or rows[1].scale != u'NTS':
        fail.add('register_logic', 'scales are not taken from the one-pass '
                 'read, NTS where a sheet has none')
    # P01 and P02 against C01 in the second column: 1 P against 1 C.
    if by_key[501].status_letter != u'P':
        fail.add('register_logic', 'the status letter is not derived after '
                 'the read')
    if by_key[503].heading() != u'Seq 3':
        fail.add('register_logic', 'an undated revision has no header text')

    # -- and nothing anywhere reads the deprecated property
    if re.search(r'\.RevisionNumber\b',
                 code_only(read(os.path.join(root, 'ps_register.py')))):
        fail.add('register_logic',
                 'ps_register reads .RevisionNumber - project-wide, '
                 'deprecated since 2022, and gone in later releases')


# ==========================================================================
# rule 34 : the register keeps its own list, and its headers include
#
# 1.21.0 turned the register's ticks from "print" into "in the register".
# So the register must never reach into the Selection tab's print ticks;
# what it includes is written to a View/Sheet Set only through the external
# event; a header click is an include and the sort it would start is always
# cancelled; nothing re-filters under the cursor when a tick changes; and
# the columns are fitted to their text in pixels, never left on Auto.
# ==========================================================================

def rule_register_view(root, fail):
    path = os.path.join(root, 'ps_regview.py')
    if not os.path.isfile(path):
        fail.add('register_view', 'ps_regview.py is missing')
        return
    text = read(path)
    code = code_only(text)

    def body(name, raw=False):
        found = re.search(r'\n    def ' + name + r'\(.*?(?=\n    def |\Z)',
                          text, re.S)
        if not found:
            return ''
        return found.group(0) if raw else code_only(found.group(0))

    # Its own list. The 1.20.0 bridge to the print ticks must not come back.
    for name in ('tick_sheets', 'sheet_ticks'):
        if name in code:
            fail.add('register_view',
                     'ps_regview reaches the Selection tab\'s print ticks '
                     'through host.{0}. A tick on the register means "in the '
                     'register", and the drawings on a register are not the '
                     'ones being printed today.'.format(name))
    if 'self.included' not in body('_add_drawing'):
        fail.add('register_view',
                 'a drawing row does not take its tick from the register\'s '
                 'own included list')

    # A set is written through Revit's event, never from the window.
    if 'Transaction' in code:
        fail.add('register_view',
                 'ps_regview opens a Transaction itself. A modeless window '
                 'cannot; the write has to go out through host._queue.')
    if 'self.host._queue(' not in body('apply_set'):
        fail.add('register_view',
                 'apply_set does not go through the external event')
    if 'ps_model.save_view_sheet_set(' not in body('_do_apply') or \
            'keep_other_views=True' not in body('_do_apply'):
        fail.add('register_view',
                 '_do_apply does not write through save_view_sheet_set with '
                 'the set\'s own views kept - Apply would drop every view '
                 'somebody else put in the set')

    # Nothing moves under the cursor: a tick does not re-filter.
    if '_apply_filters(' in body('set_included'):
        fail.add('register_view',
                 'set_included re-filters, so unticking a drawing while '
                 '"Included only" is showing whisks it away from under the '
                 'cursor. Leave it pale until the next filter or F5.')

    # A header click includes, and the sort is cancelled before anything
    # that can return.
    sorting = body('_on_sorting')
    handled = sorting.find('args.Handled = True')
    first_return = sorting.find('return')
    if handled < 0 or (0 <= first_return < handled):
        fail.add('register_view',
                 '_on_sorting does not cancel the sort first thing, so a '
                 'click on a header can resort the register and scatter its '
                 'headings')
    if 'self.isolated = ' not in sorting or 'self.included' in sorting \
            or 'set_included' in sorting:
        fail.add('register_view',
                 'a revision header click does not isolate the sheets '
                 'carrying it, or still ticks them in or out of the '
                 'register')

    # The filter under a heading is a Button opening Excel's list. A Button
    # handles its own click, so it never reaches the heading; and nothing
    # is applied until OK, so the grid does not reshape - or drop the very
    # column the list belongs to - while the list is open.
    if 'Button()' not in body('_filter_button'):
        fail.add('register_view',
                 'the column filter is not a button, so its click reaches '
                 'the heading - which includes a revision\'s drawings')
    opener = body('_open_filter')
    if 'self.set_filter(' not in opener:
        fail.add('register_view', 'the filter list never applies')
    search_part = opener.split('def on_search', 1)[-1].split('def on_every')[0]
    if '_apply_filters' in search_part or 'set_filter' in search_part:
        fail.add('register_view',
                 'typing in the filter list\'s search box filters the grid; '
                 'only OK should')
    if 'shell.MouseLeftButtonDown += swallow' not in opener:
        fail.add('register_view',
                 'clicks on the filter list are not stopped at its border, so '
                 'they bubble to the heading - and a heading click on a '
                 'revision column includes every drawing carrying it')
    if 'ps_register.BLANKS' not in opener:
        fail.add('register_view',
                 'the filter list has no (Blanks) entry, as Excel does')
    if 'holder.Children.Add(popup)' not in body('_open_filter', raw=True):
        fail.add('register_view',
                 'the filter list is not put in the heading\'s panel, so it '
                 'is outside the window\'s tree and renders with no theme')
    choices = body('_choices', raw=True)
    if 'key != col_id' not in choices:
        fail.add('register_view',
                 'a column\'s list is narrowed by its own filter, so a value '
                 'it hides can never be ticked back on')

    # Coloured like the Selection tab's groups, from the same helper, on
    # every row realised so a recycled container never keeps a stripe.
    painter = body('_paint_row')
    if 'self.host._shade_brushes(' not in painter or \
            'Brushes.Transparent' not in painter:
        fail.add('register_view',
                 'the register\'s rows are not painted with the Selection '
                 'tab\'s group colours, reset on every row')
    if 'self.register.repaint()' not in \
            read(os.path.join(root, 'ps_window.py')):
        fail.add('register_view',
                 'a palette swap does not repaint the register\'s colours')

    if 'RenderTransform' in code:
        fail.add('register_view',
                 'a rotated header uses RenderTransform, which does not '
                 'change the space it asks for')
    if 'LayoutTransform = RotateTransform(' not in code:
        fail.add('register_view', 'the revision dates are not rotated')
    if 'FrozenColumnCount = len(self.IDENTITY)' not in code:
        fail.add('register_view', 'the drawing columns are not frozen')

    # Fitted once, in pixels. Auto re-measures as rows are realised.
    if 'ps_register.column_width(' not in body('_fit_columns'):
        fail.add('register_view',
                 'the columns are not fitted to their text')
    if re.search(r'DataGridLengthUnitType|SizeToCells|DataGridLength\.Auto',
                 code):
        fail.add('register_view',
                 'a register column is left on Auto, which re-measures as '
                 'rows are realised and shifts the columns under the reader')
    floor = re.search(r'REVISION_FLOOR = (\d+)', text)
    if not floor or int(floor.group(1)) < 44:
        fail.add('register_view',
                 'the revision columns can be narrower than 44px, which '
                 'clipped "P02" in 1.20.0')
    # Read from the raw source: code_only blanks the 'num' literal.
    if "self._measure(entry['num'], 14, True)" not in \
            body('_fit_columns', raw=True):
        fail.add('register_view',
                 'the Drawing No column is not fitted to the series headings, '
                 'which are 14pt bold - 1.20.0 cut them off')

    match = re.search(r"CELL_STYLE = \((.*?)\)\n\n", text, re.S)
    cell = match.group(1) if match else ''
    if '{{DynamicResource OrangeBrush}}' not in cell:
        fail.add('register_view',
                 'the current revision is not coloured from OrangeBrush as a '
                 'DynamicResource')
    if '{{Binding sel}}' not in cell:
        fail.add('register_view',
                 'a revision cell does not fade when its drawing is left out')

    # Add to export has to show on the Create list and land above the
    # format folders. 1.21.0 did neither: nothing on the Create tab said
    # the register was coming, and it was written into the deepest folder
    # the run's files shared - the PDF folder itself on a one-series run.
    if 'self.host._refresh_plan()' not in body('_export_toggled'):
        fail.add('register_view',
                 'ticking Add to export does not update the Create list')
    window_text = read(os.path.join(root, 'ps_window.py'))

    def window_body(name):
        found = re.search(r'\n    def ' + name + r'\(.*?(?=\n    def |\Z)',
                          window_text, re.S)
        return found.group(0) if found else ''
    plan = window_body('_refresh_plan')
    if 'self.register.add_to_export()' not in plan or \
            "entry['key'] = u'register'" not in plan:
        fail.add('register_view',
                 'the Create list does not show the Document Register when it '
                 'is added to the export - and without the "register" key its '
                 'row cannot turn green or red with the run')
    if 'self.register_folder(jobs, formats)' not in window_body('_do_export'):
        fail.add('register_view',
                 'the run does not put the register in the folder above the '
                 'PDF and DWG folders')

    # The paler text for drawings left out, on the cell where it can win.
    theme_text = read(os.path.join(root, THEME_FILE))
    style = re.search(r'<Style x:Key="RegisterCell".*?</Style>', theme_text,
                      re.S)
    style = style.group(0) if style else ''
    if 'BasedOn="{StaticResource GridCell}"' not in style or \
            '{Binding sel}' not in style or 'MutedBrush' not in style:
        fail.add('register_view',
                 'Theme.xaml has no RegisterCell based on GridCell that mutes '
                 'a drawing left out of the register')
    layout = read(os.path.join(root, 'ProSheets.xaml'))
    grid = re.search(r'<DataGrid x:Name="RegisterGrid".*?/>', layout, re.S)
    if not grid or 'CellStyle="{DynamicResource RegisterCell}"' not in \
            grid.group(0):
        fail.add('register_view',
                 'the register grid does not use RegisterCell, so a drawing '
                 'left out looks the same as one in')


# ==========================================================================
# rule 35 : tabs are named, never numbered
#
# 1.20.0 put the Document Register second. Every literal 2 in the window
# that meant Create would have quietly started meaning Format: the Export
# button on the wrong page, a run opening the wrong tab. The constants
# have to match the layout, and nothing compares a tab index with a
# number.
# ==========================================================================

def rule_tab_indices(root, fail):
    path = os.path.join(root, 'ps_window.py')
    text = read(path)
    tree = ast.parse(text)

    constants = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != 'ProSheetsWindow':
            continue
        for item in node.body:
            if not isinstance(item, ast.Assign):
                continue
            for target in item.targets:
                name = getattr(target, 'id', '')
                if name.startswith('TAB_'):
                    value = getattr(item.value, 'n',
                                    getattr(item.value, 'value', None))
                    constants[name] = value

    layout = read(os.path.join(root, 'ProSheets.xaml'))
    tab_count = len(re.findall(r'<TabItem>', layout))
    headers = re.findall(r'<TabItem>.*?<TextBlock Text="([^"]+)"', layout, re.S)
    for wanted in ('TAB_SELECTION', 'TAB_REGISTER', 'TAB_FORMAT',
                   'TAB_CREATE'):
        if wanted not in constants:
            fail.add('tab_indices', 'ProSheetsWindow has no {0}'.format(wanted))
            return
    if constants['TAB_CREATE'] != tab_count - 1:
        fail.add('tab_indices',
                 'TAB_CREATE is {0} but the layout has {1} tabs, so Create is '
                 '{2}'.format(constants['TAB_CREATE'], tab_count,
                              tab_count - 1))
    expected = {'TAB_SELECTION': 'Selection',
                'TAB_REGISTER': 'Document Register',
                'TAB_FORMAT': 'Format', 'TAB_CREATE': 'Create'}
    for name, title in expected.items():
        index = constants.get(name)
        if index is None or index >= len(headers):
            continue
        if headers[index] != title:
            fail.add('tab_indices',
                     '{0} is {1}, but tab {1} in the layout is "{2}", not '
                     '"{3}"'.format(name, index, headers[index], title))

    def is_index(node):
        if isinstance(node, ast.Name) and node.id == 'index':
            return True
        return (isinstance(node, ast.Call)
                and getattr(node.func, 'attr', '') == '_tab_index')

    def is_number(node):
        value = getattr(node, 'n', getattr(node, 'value', None))
        return isinstance(value, int) and not isinstance(value, bool)

    for func in ast.walk(tree):
        if not isinstance(func, ast.FunctionDef):
            continue
        source = ast.get_source_segment(text, func) or ''
        about_tabs = ('_tab_index()' in source or func.name == '_set_tab')
        for node in ast.walk(func):
            if (isinstance(node, ast.Call)
                    and getattr(node.func, 'attr', '') == '_set_tab'
                    and node.args and is_number(node.args[0])):
                fail.add('tab_indices',
                         '{0} line {1}: _set_tab with a bare number - name '
                         'the tab'.format(func.name, node.lineno))
            if not about_tabs:
                continue
            if isinstance(node, ast.Compare):
                sides = [node.left] + list(node.comparators)
                if any(is_index(side) for side in sides) and \
                        any(is_number(side) for side in sides):
                    fail.add('tab_indices',
                             '{0} line {1}: a tab index compared with a bare '
                             'number'.format(func.name, node.lineno))
            if (func.name == '_set_tab' and isinstance(node, ast.Call)
                    and getattr(node.func, 'id', '') in ('min', 'max')
                    and any(is_number(arg) and getattr(
                        arg, 'n', getattr(arg, 'value', 0)) > 0
                        for arg in node.args)):
                fail.add('tab_indices',
                         '_set_tab line {0}: clamped to a bare number'
                         .format(node.lineno))


# ==========================================================================
# rule 36 : ticked means exported, whatever is on screen
#
# Up to 1.19.2 ticked_rows walked the table's DefaultView, which is
# filtered to the rows showing. A sheet ticked inside a collapsed group, or
# ticked and then searched out of sight, counted as ticked on the status
# line and was silently left out of the run. The Document Register ticks
# sheets the Selection tab may be hiding, so it stopped being an edge case.
# ==========================================================================

def rule_export_ticked(root, fail):
    text = read(os.path.join(root, 'ps_window.py'))
    found = re.search(r'\n    def ticked_rows\(.*?(?=\n    def |\Z)', text, re.S)
    if not found:
        fail.add('export_ticked', 'ps_window has no ticked_rows')
        return
    body = code_only(found.group(0))
    if 'DefaultView' in body:
        fail.add('export_ticked',
                 'ticked_rows walks the DefaultView, which only holds the rows '
                 'showing - a ticked sheet in a collapsed group or behind a '
                 'search is then left out of the export without a word')
    if "[ord] ASC" not in found.group(0):
        fail.add('export_ticked',
                 'ticked_rows does not keep the Selection tab\'s order, so '
                 'a combined PDF comes out in table order rather than the '
                 'order on screen')
    if 'if not key' not in body:
        fail.add('export_ticked',
                 'ticked_rows does not step over group headings, which hold '
                 'a tick and no sheet')


# ==========================================================================
# rule 37 : a tick on the register is a tick on the Selection tab
#
# Behavioural, not textual: the real RegisterView driven against a stand-in
# DataTable and a stand-in window holding the one list of ticks. Ticks a
# series heading, clicks a revision date twice, ticks a highlighted block,
# searches and ticks what is left, and checks the Selection side after each.
# ==========================================================================

class _RegSlot(object):
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def fire(self, *args):
        for handler in list(self.handlers):
            handler(*args)


class _RegCol(object):
    def __init__(self, name):
        self.ColumnName = name
        self.DefaultValue = None


class _RegCols(object):
    def __init__(self):
        self.items = []

    def Add(self, name, _kind=None):
        column = _RegCol(name)
        self.items.append(column)
        return column

    def Remove(self, column):
        self.items.remove(column)

    def __iter__(self):
        return iter(list(self.items))


class _RegChangeArgs(object):
    def __init__(self, row, name):
        self.Row = row
        self.Column = _RegCol(name)


class _RegRow(object):
    def __init__(self, table):
        self._table = table
        self._values = dict([(column.ColumnName, column.DefaultValue)
                             for column in table.Columns])
        self._attached = False

    def __getitem__(self, name):
        return self._values.get(name)

    def __setitem__(self, name, value):
        self._values[name] = value
        if self._attached:
            self._table.ColumnChanged.fire(self._table,
                                           _RegChangeArgs(self, name))


class _RegRows(object):
    def __init__(self):
        self.items = []

    def Add(self, row):
        row._attached = True
        self.items.append(row)

    def Clear(self):
        self.items = []

    def __iter__(self):
        return iter(list(self.items))


class _RegView(object):
    RowFilter = ''
    Sort = ''


class _RegTable(object):
    def __init__(self, _name=''):
        self.Columns = _RegCols()
        self.Rows = _RegRows()
        self.ColumnChanged = _RegSlot()
        self.DefaultView = _RegView()

    def NewRow(self):
        return _RegRow(self)


class _RegSettings(object):
    def __init__(self):
        self.store = {'param_discipline': u'BGL_Sheet Discipline',
                      'param_series': u'BGL_Sheet Series',
                      'reg_last_set': u'', 'reg_show': u'all',
                      'reg_title': u'Document Register & Issue Sheet',
                      'reg_legend': u'P - Preliminary\tC - Construction',
                      'reg_issued_to': u'Client\tFile'}
        self.saved = 0

    def text(self, key, default=u''):
        return self.store.get(key, default)

    def flag(self, key, default=False):
        return self.store.get(key, '1' if default else '0') == '1'

    def set(self, key, value):
        self.store[key] = u'{0}'.format(value)

    def save(self):
        self.saved += 1


class _RegSheet(object):
    def __init__(self, key):
        self.key = key
        self.element = 'sheet-{0}'.format(key)
        self.is_sheet = True


class _RegDoc(object):
    Title = u'NPE7-MEP'
    ProjectInformation = type('P', (object,), {'Number': u'NPE7',
                                                 'Name': u'Process 7'})()


class _RegHost(object):
    TICK_TEMPLATE = u''
    theme_name = 'dark'

    def __init__(self, window_module):
        self.window = None
        self.doc = _RegDoc()
        self.settings = _RegSettings()
        self.sheet_sets = {u'Issue A': set([1, 3, 99])}
        self.queued = []
        self.said = []
        self._targets = window_module.ProSheetsWindow.tick_targets

    def tick_targets(self, key, selection):
        return self._targets(key, selection)

    def sheet_rows(self):
        return [_RegSheet(key) for key in (1, 2, 3, 4, 5)]

    def say(self, text):
        self.said.append(text)

    def on_register_tab(self):
        return True

    def open_setup(self, section=None):
        pass

    def refresh_sheet_sets(self):
        pass

    def _queue(self, work):
        self.queued.append(work)
        return True

    def _on_ui(self, call):
        call()

    def _styled(self, _element, _key):
        return True

    def _under_checkbox(self, _source):
        return False

    def _row_under(self, _source):
        return None

    def _focus_search(self, sender, args):
        pass

    def _run_brushes(self, place):
        return ('cell', 'wash', 'head')


class _RegSortArgs(object):
    def __init__(self, key):
        self.Handled = False
        self.Column = type('C', (object,), {'SortMemberPath': key})()


class _RegText(object):
    def __init__(self, text):
        self.Text = text


def rule_register_ticks(root, fail):
    regview = _module_under_stubs(root, 'ps_regview', 'register_ticks', fail)
    if regview is None:
        return
    window = _window_module(root, 'register_ticks', fail)
    if window is None:
        return
    register = regview.ps_register

    def row(key, number, discipline, series, cells):
        made = register.RegisterRow(key, number, u'Title ' + number)
        made.discipline = discipline
        made.series = series
        made.cells = cells
        return made

    first = register.RevisionColumn(501, sequence=1, date=u'01/02/26')
    second = register.RevisionColumn(502, sequence=2, date=u'15/03/26')
    rows = [
        row(1, u'M-100', u'Mech', u'100', {first.key: u'P01', second.key: u'P02'}),
        row(2, u'M-101', u'Mech', u'100', {second.key: u'P02'}),
        row(3, u'M-200', u'Mech', u'200', {first.key: u'P01'}),
        row(4, u'E-100', u'Elec', u'100', {second.key: u'C01'}),
        row(5, u'X-001', u'', u'', {}),
    ]
    rows[0].current_sequence = u'2'
    rows[2].current_sequence = u'1'

    by_hand = {'excluded': None, 'writes': []}
    written = []

    def read_excluded(_doc):
        return None if by_hand['excluded'] is None \
            else set(by_hand['excluded'])

    def write_excluded(_doc, keys):
        by_hand['excluded'] = set(keys)
        by_hand['writes'].append(set(keys))
        return True

    def save_set(_doc, name, sheets, keep_other_views=True):
        written.append((name, sorted(sheets), keep_other_views))
        return True, u'saved'

    config = regview.ps_config
    model = regview.ps_model
    ui = regview.ps_ui
    saved = (regview.DataTable, register.read_register,
             config.read_register_excluded, config.write_register_excluded,
             model.save_view_sheet_set, ui.ask_text,
             config.read_register_skipped, config.write_register_skipped)
    config.read_register_skipped = lambda doc: set()
    config.write_register_skipped = lambda doc, names: True
    regview.DataTable = _RegTable
    register.read_register = lambda doc, sheets, d, s, *more: ([first, second], rows)
    config.read_register_excluded = read_excluded
    config.write_register_excluded = write_excluded
    model.save_view_sheet_set = save_set
    try:
        host = _RegHost(window)
        try:
            view = regview.RegisterView(host)
            view.reload()
        except Exception as err:
            fail.add('register_ticks', 'the register would not build: '
                     '{0}: {1}'.format(err.__class__.__name__, err))
            return

        def entries():
            return [entry for entry in view.table.Rows]

        def find(number):
            for entry in entries():
                if entry['num'] == number:
                    return entry
                if entry['ishead'] == u'1' and entry['glabel'] == number:
                    return entry
            return None

        # -- by hand, nothing saved yet: everything is in.
        if view.included != set([u'1', u'2', u'3', u'4', u'5']):
            fail.add('register_ticks',
                     'a project with nothing saved should start with every '
                     'drawing in the register, got {0}'.format(
                         sorted(view.included)))

        view.select_tab(1)
        layout = [entry['glabel'] if entry['ishead'] == u'1' else entry['num']
                  for entry in entries()]
        if layout != [u'100', u'M-100', u'M-101', u'200', u'M-200']:
            fail.add('register_ticks', 'the Mech tab is laid out {0}; wanted '
                     'each series heading over its drawings'.format(layout))
            return

        # -- 1.25.0: the current revision's sequence number in its own
        #    column, and over each date in the header. Screen only.
        seqs = dict([(entry['num'], u'{0}'.format(entry['seq'] or u''))
                     for entry in entries() if entry['ishead'] != u'1'])
        if seqs.get(u'M-100') != u'2' or seqs.get(u'M-200') != u'1':
            fail.add('register_ticks', 'the Sequence Number column does not '
                     'carry each drawing\'s current sequence: {0}'.format(seqs))
        if 'seq' not in [one[0] for one in regview.RegisterView.IDENTITY] or \
                [one[0] for one in regview.RegisterView.IDENTITY].index('seq') \
                != [one[0] for one in regview.RegisterView.IDENTITY].index(
                    'rev') + 1:
            fail.add('register_ticks', 'Sequence Number is not the column '
                     'next to Rev')
        source = read(os.path.join(root, 'ps_regview.py'))
        header = source[source.find('    def _revision_header('):]
        header = header[:header.find('\n    def ', 10)]
        at_sequence = header.find('panel.Children.Add(sequence)')
        if at_sequence < 0 or at_sequence > header.find(
                'panel.Children.Add(date)'):
            fail.add('register_ticks', 'the revision header does not carry '
                     'the sequence number above the date')

        # -- 1.26.0: Reset filters clears every column filter, and is only
        #    live while there is one to clear.
        class _Button(object):
            IsEnabled = None
        view.reset_button = _Button()
        view.set_filter('num', set([u'M-100']))
        view.set_filter('rev', set([u'P01']))
        if view.reset_button.IsEnabled is not True:
            fail.add('register_ticks', 'Reset filters is not live with two '
                     'columns filtered')
        view.reset_filters()
        if view.column_filters:
            fail.add('register_ticks', 'Reset filters left {0} filtered'
                     .format(sorted(view.column_filters)))
        if view.reset_button.IsEnabled is not False:
            fail.add('register_ticks', 'Reset filters stays live with '
                     'nothing to clear')
        if [entry for entry in entries() if entry['ishead'] != u'1'
                and entry['show'] != u'1']:
            fail.add('register_ticks', 'drawings stayed hidden after Reset '
                     'filters')
        source = read(os.path.join(root, 'ps_regview.py'))
        if 'self._click(self.reset_button,' not in source:
            fail.add('register_ticks', 'the Reset filters button is not wired')
        current = getattr(regview, 'CURRENT_STYLE', u'')
        if 'FontWeight" Value="Bold"' not in current or \
                'BlueBrush' not in current or \
                "if col_id == 'rev':\n            column.ElementStyle = " \
                "self._current_style()" not in source:
            fail.add('register_ticks', 'the Rev column is not bold and blue')
        theme_xaml = read(os.path.join(root, 'Theme.xaml'))
        layout_xaml = read(os.path.join(root, 'ProSheets.xaml'))
        switch = theme_xaml[theme_xaml.find('x:Key="SwitchButtonOn"'):]
        switch = switch[:switch.find('</Style>')]
        if "'SwitchButtonOn' if on_all else 'ChipButton'" not in source or \
                "'ChipButton' if on_all else 'SwitchButtonOn'" not in source \
                or 'Background="{DynamicResource OrangeBrush}"' not in switch:
            fail.add('register_ticks', 'the chosen half of All sheets / '
                     'Included only is not solid orange')
        excel = theme_xaml[theme_xaml.find('x:Key="ExcelButton"'):]
        excel = excel[:excel.find('</Style>')]
        button = layout_xaml[layout_xaml.find('x:Name="RegisterExportButton"'):]
        button = button[:button.find('</Button>')]
        if 'Value="{DynamicResource GreenBrush}"' not in excel or \
                'Value="Bold"' not in excel or \
                'Style="{DynamicResource ExcelButton}"' not in button or \
                'Background="{DynamicResource GreenBrush}"' not in button:
            fail.add('register_ticks', 'Export to Excel is not the green, '
                     'bold button with the green spreadsheet icon')
        seq = [one for one in regview.RegisterView.IDENTITY if one[0] == 'seq']
        if not seq or seq[0][1] != u'Seq No' or seq[0][2] > 64:
            fail.add('register_ticks', 'the sequence column is not the '
                     'narrow "Seq No" one: {0}'.format(seq))

        # -- 1.24.0: heading ticks only under All sheets, and not with
        #    everything collapsed; a drawing's tick is never hidden.
        def hidden(kind):
            return sorted(set([u'{0}'.format(entry['hidetick'])
                               for entry in entries()
                               if (entry['ishead'] == u'1') == (kind == 'head')
                               and entry['show'] == u'1']))
        if hidden('head') != [u'0'] or hidden('drawing') != [u'0']:
            fail.add('register_ticks',
                     'under All sheets the heading ticks are hidden: '
                     'headings {0}, drawings {1}'.format(hidden('head'),
                                                         hidden('drawing')))
        view.set_show('included')
        if hidden('head') != [u'1'] or hidden('drawing') != [u'0']:
            fail.add('register_ticks',
                     'under "Included only" a heading still shows its tick '
                     '(or a drawing lost its own): headings {0}, drawings '
                     '{1}'.format(hidden('head'), hidden('drawing')))
        view.set_show('all')
        view.toggle_collapse_all()
        if hidden('head') != [u'1']:
            fail.add('register_ticks',
                     'with everything collapsed the headings still show tick '
                     'boxes: {0}'.format(hidden('head')))
        view.toggle_collapse_all()
        if hidden('head') != [u'0']:
            fail.add('register_ticks',
                     'expanding again did not bring the heading ticks back')
        template = getattr(regview.RegisterView, 'TICK_TEMPLATE', u'')
        try:
            import xml.dom.minidom as _minidom
            parsed = _minidom.parseString(template.encode('utf-8'))
            names = [node.getAttribute('x:Name') for node in
                     parsed.getElementsByTagName('CheckBox')]
            setters = [node for node in parsed.getElementsByTagName('Setter')
                       if node.getAttribute('Property') == 'Visibility'
                       and node.getAttribute('TargetName') in names]
            triggers = [node for node in
                        parsed.getElementsByTagName('DataTrigger')
                        if 'hidetick' in node.getAttribute('Binding')]
            if not names or not setters or not triggers:
                fail.add('register_ticks',
                         'the register tick template has no trigger hiding '
                         'the box on a row whose hidetick is 1')
        except Exception as err:
            fail.add('register_ticks', 'the register tick template is not '
                     'XAML: {0}'.format(err))
        source = read(os.path.join(root, 'ps_regview.py'))
        if 'XamlReader.Parse(self.TICK_TEMPLATE)' not in source:
            fail.add('register_ticks', 'the tick column does not use the '
                     'register\'s own template, so nothing hides')

        # -- a tick out, kept for the project as the ones left out.
        find(u'M-100')['sel'] = False
        if u'1' in view.included:
            fail.add('register_ticks', 'unticking did not take it out')
        if by_hand['excluded'] != set([u'1']):
            fail.add('register_ticks',
                     'ticks made by hand were not kept for the project as the '
                     'drawings left out: {0}'.format(by_hand['excluded']))

        # -- nothing vanishes under the cursor.
        view.set_show('included')
        if find(u'M-100')['show'] != u'0':
            fail.add('register_ticks',
                     '"Included only" still shows a drawing that is out')
        find(u'M-101')['sel'] = False
        if find(u'M-101')['show'] != u'1':
            fail.add('register_ticks',
                     'unticking under "Included only" hid the row at once, '
                     'under the cursor')
        view._apply_filters()
        if find(u'M-101')['show'] != u'0':
            fail.add('register_ticks',
                     'the next filter did not catch the view up')
        view.set_show('all')

        # -- a heading includes its whole series.
        find(u'100')['sel'] = True
        if not set([u'1', u'2']) <= view.included:
            fail.add('register_ticks', 'ticking the 100 heading did not put '
                     'its drawings back in')

        # -- the print ticks are not this tab's business.
        if hasattr(host, 'ticks'):
            fail.add('register_ticks', 'the register touched print ticks')

        # -- a revision heading: the first click isolates the sheets that
        #    carry it, touching no tick; the second shows them all again.
        before = set(view.included)
        args = _RegSortArgs(first.key)
        view._on_sorting(None, args)
        if not args.Handled:
            fail.add('register_ticks',
                     'the header click was let through as a sort')
        shown = set(view._visible_keys())
        if view.isolated != [first.key] or not shown or \
                not shown <= set([u'1', u'3']):
            fail.add('register_ticks',
                     'clicking a revision heading did not isolate the sheets '
                     'carrying it: isolated {0}, showing {1}'.format(
                         view.isolated, sorted(shown)))
        if view.included != before:
            fail.add('register_ticks',
                     'clicking a revision heading ticked or unticked sheets')
        view._on_sorting(None, _RegSortArgs(first.key))
        if view.isolated or u'2' not in set(view._visible_keys()):
            fail.add('register_ticks',
                     'a second click on the heading did not show every sheet '
                     'again')

        # -- a series folds away and comes back.
        view.toggle_group(u'100')
        if find(u'M-100')['show'] != u'0' or find(u'100')['show'] != u'1':
            fail.add('register_ticks',
                     'folding a series did not hide its drawings and keep '
                     'its heading')
        if not u'{0}'.format(find(u'100')['num']).startswith(
                regview.COLLAPSED):
            fail.add('register_ticks', 'a folded heading does not say so')
        view.toggle_group(u'100')
        if find(u'M-100')['show'] != u'1':
            fail.add('register_ticks', 'unfolding did not bring it back')

        # -- a column filter is a set of allowed values, Excel style.
        view.set_filter('num', set([u'M-200']))
        showing = [entry['num'] for entry in entries()
                   if entry['show'] == u'1' and entry['ishead'] != u'1']
        if showing != [u'M-200']:
            fail.add('register_ticks',
                     'filtering Drawing No to M-200 left {0}'.format(showing))
        # Its own list still offers the values it hides.
        if view._choices('num') != [u'M-100', u'M-101', u'M-200']:
            fail.add('register_ticks',
                     'the Drawing No list offered {0} - a column\'s own '
                     'filter must not narrow its own list'.format(
                         view._choices('num')))
        # Another column's list is narrowed by it: only M-200 is left,
        # which carries P01.
        if view._choices(first.key) != [u'P01']:
            fail.add('register_ticks',
                     'with Drawing No filtered to M-200, the {0} list offered '
                     '{1} - the other filters have to narrow it'.format(
                         first.key, view._choices(first.key)))
        view.set_filter('num', None)
        # A blank cell is "(Blanks)", last; and picking only blanks keeps
        # exactly the drawings without that revision.
        if view._choices(first.key) != [u'P01', register.BLANKS]:
            fail.add('register_ticks',
                     'the {0} list offered {1}, wanted P01 then (Blanks)'
                     .format(first.key, view._choices(first.key)))
        view.set_filter(first.key, set([u'']))
        showing = [entry['num'] for entry in entries()
                   if entry['vis'] == u'1' and entry['ishead'] != u'1']
        if showing != [u'M-101']:
            fail.add('register_ticks',
                     'filtering {0} to (Blanks) left {1}, wanted M-101'
                     .format(first.key, showing))
        # And the filtered column stays on screen, even though nothing
        # showing carries it - or the filter could never be cleared.
        if first.key not in [column.key for column in view.used_columns]:
            fail.add('register_ticks',
                     'a filtered revision column was hidden as unused, '
                     'taking the way to clear its filter with it')
        view.set_filter(first.key, None)
        view.set_filter('num', set([u'']))
        if [entry['num'] for entry in entries()
                if entry['vis'] == u'1' and entry['ishead'] != u'1']:
            fail.add('register_ticks',
                     'a filter allowing only blanks let a numbered drawing '
                     'through')
        view.clear_filters()

        # -- hide unused revisions follows what is on screen
        view.hide_unused = True
        view.set_filter('num', set([u'M-101']))
        if [column.key for column in view.used_columns] != [second.key]:
            fail.add('register_ticks',
                     'with Hide unused on and only M-101 showing, the '
                     'revision columns were {0}'.format(
                         [c.key for c in view.used_columns]))
        view.hide_unused = False
        view._apply_filters()
        if [column.key for column in view.used_columns] != \
                [first.key, second.key]:
            fail.add('register_ticks',
                     'with Hide unused off, not every revision was shown')
        view.hide_unused = True
        view.clear_filters()

        # -- the All tab: discipline, then series inside it
        view.select_tab(0)
        heads = [(entry['level'], entry['glabel']) for entry in entries()
                 if entry['ishead'] == u'1']
        wanted_heads = [(u'1', u'Mech'), (u'2', u'100'), (u'2', u'200'),
                        (u'1', u'Elec'), (u'2', u'100'),
                        (u'1', register.NO_DISCIPLINE)]
        if heads != wanted_heads:
            fail.add('register_ticks',
                     'the All tab is headed {0}; wanted each discipline, '
                     'then its series'.format(heads))
        # Folding a discipline folds its series headings with it.
        view.toggle_group(u'Mech')
        mech_series = [entry['show'] for entry in entries()
                       if entry['gpath'] in (u'Mech/100', u'Mech/200')]
        if mech_series != [u'0', u'0'] or find(u'M-100')['show'] != u'0':
            fail.add('register_ticks',
                     'folding a discipline left its series or drawings '
                     'showing')
        view.toggle_group(u'Mech')
        # A discipline heading includes every drawing under its series.
        view.set_included([u'1', u'2', u'3'], False)
        for entry in entries():
            if entry['gpath'] == u'Mech':
                entry['sel'] = True
                break
        if not set([u'1', u'2', u'3']) <= view.included:
            fail.add('register_ticks',
                     'ticking a discipline heading missed drawings in its '
                     'series')
        # Colours: a discipline's heading takes its tab's colour.
        mech_head = [entry['gcolor'] for entry in entries()
                     if entry['gpath'] == u'Mech']
        if mech_head != [u'{0}'.format(view.shown_colour(
                u'Mech', 1, view.disc_colour.get(u'Mech')))]:
            fail.add('register_ticks',
                     'the Mech heading is not the colour of the Mech tab')
        view.select_tab(1)

        # -- a View/Sheet Set drives the ticks; Apply writes them back.
        view._adopt(u'Issue A')
        view.sync_ticks()
        if view.included != set([u'1', u'3']):
            fail.add('register_ticks',
                     'choosing a set ticked {0}, not its sheets'.format(
                         sorted(view.included)))
        if view.dirty():
            fail.add('register_ticks', 'a set just chosen reads as changed')
        view.set_included([u'2'], True)
        if not view.dirty():
            fail.add('register_ticks',
                     'ticking another drawing did not mark the set changed')
        view.apply_set()
        if len(host.queued) != 1:
            fail.add('register_ticks',
                     'Apply did not go out through the external event')
        else:
            host.queued.pop()(None)
            if not written or written[-1][0] != u'Issue A' or \
                    written[-1][1] != ['sheet-1', 'sheet-2', 'sheet-3'] or \
                    not written[-1][2]:
                fail.add('register_ticks',
                         'Apply wrote {0}'.format(written[-1:]))
            if view.dirty():
                fail.add('register_ticks',
                         'after Apply the set still reads as changed')

        # -- + names a new set, empty, written only on Save.
        ui.ask_text = lambda *args, **kwargs: u'Issue B'
        before = len(written)
        view.new_set()
        if view.set_name != u'Issue B' or not view.set_new or view.included:
            fail.add('register_ticks',
                     'a new set should start named, unsaved and empty')
        # Queued counts as written: anything sent to Revit's event before
        # Save would make an empty set, which Revit cannot hold.
        if len(written) != before or host.queued:
            fail.add('register_ticks',
                     'a new set was sent to Revit before Save was pressed')
        view.set_included([u'4'], True)
        view.apply_set()
        if host.queued:
            host.queued.pop()(None)
        if not written or written[-1][0] != u'Issue B' or view.set_new:
            fail.add('register_ticks', 'Save new set did not write it')

        # -- Included only, from a discipline with nothing in, goes to All.
        view.select_tab(1)
        view.set_show('included')
        if view.tab_index != 0:
            fail.add('register_ticks',
                     'switching to "Included only" left the register on a '
                     'discipline with nothing in it, whose tab is hidden')
        view.set_show('all')

        # -- and the export uses what is in, minus unticked disciplines.
        view.set_included([u'1', u'2', u'3', u'4'], True)
        view.skip_tabs = set([u'Elec'])
        out = os.path.join(tempfile.mkdtemp(), 'register.xlsx')
        try:
            ok, message = view.write_excel(out)
            if not ok or not os.path.isfile(out):
                fail.add('register_ticks',
                         'the register would not write: {0}'.format(message))
            else:
                archive = zipfile.ZipFile(out)
                try:
                    book = archive.read('xl/workbook.xml').decode('utf-8')
                finally:
                    archive.close()
                names = re.findall(r'<sheet name="([^"]+)"', book)
                if u'Elec' in names or u'Mech' not in names:
                    fail.add('register_ticks',
                             'an unticked discipline still got a worksheet: '
                             '{0}'.format(names))
            view.skip_tabs = set([u'Mech', u'Elec'])
            ok, message = view.write_excel(out)
            if ok:
                fail.add('register_ticks',
                         'with every discipline unticked the register still '
                         'claimed to write')
        finally:
            shutil.rmtree(os.path.dirname(out), ignore_errors=True)
    finally:
        (regview.DataTable, register.read_register,
         config.read_register_excluded, config.write_register_excluded,
         model.save_view_sheet_set, ui.ask_text,
         config.read_register_skipped, config.write_register_skipped) = saved


# ==========================================================================
# rule 38 : the register's Excel file is a file Excel opens
#
# OOXML fixes the order of the elements inside <worksheet>, and lenient
# readers do not care - which is how a file that opens everywhere else
# still makes Excel offer to repair it. So the order is checked against the
# schema rather than by opening the file, and openpyxl opens it as well.
# ==========================================================================

WORKSHEET_ORDER = ['sheetPr', 'dimension', 'sheetViews', 'sheetFormatPr',
                   'cols', 'sheetData', 'sheetProtection', 'autoFilter',
                   'mergeCells', 'conditionalFormatting', 'dataValidations',
                   'hyperlinks', 'printOptions', 'pageMargins', 'pageSetup',
                   'headerFooter', 'drawing']

def _png_bytes(width, height):
    """A real PNG, built by hand, so a reader can decode it as well as
    read its size."""
    import struct as _struct
    import zlib as _zlib

    def chunk(kind, data):
        body = kind + data
        return (_struct.pack('>I', len(data)) + body +
                _struct.pack('>I', _zlib.crc32(body) & 0xffffffff))
    raw = b''.join([b'\x00' + b'\x1b\x72\xbe' * width for _ in range(height)])
    return (b'\x89PNG\r\n\x1a\n' +
            chunk(b'IHDR', _struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)) +
            chunk(b'IDAT', _zlib.compress(raw)) + chunk(b'IEND', b''))


def rule_register_xlsx(root, fail):
    export = _module_under_stubs(root, 'ps_regexport', 'register_xlsx', fail)
    if export is None:
        return
    register = export.ps_register
    xlsx = export.ps_xlsx

    # -- dates as typed in Revit
    for text, wanted in ((u'01/02/26', (1, 2, 26)),
                         (u'1.2.2026', (1, 2, 26)),
                         (u'2026-02-01', (1, 2, 26)),
                         (u'1 Feb 2026', (1, 2, 26)),
                         (u'15th March 26', (15, 3, 26)),
                         (u'13/13/26', None), (u'TBC', None), (u'', None)):
        got = export.parse_date(text)
        if got != wanted:
            fail.add('register_xlsx', 'date "{0}" read as {1}, wanted {2}'
                     .format(text, got, wanted))

    # -- the dates up the issue columns (1.44.0: one rotated line)
    for text, wanted in ((u'1 Feb 2026', u'01/02/26'), (u'TBC', u'TBC'),
                         (u'', u'')):
        if export.date_text(text) != wanted:
            fail.add('register_xlsx', 'date "{0}" runs up its column as '
                     '{1!r}, wanted {2!r}'.format(text,
                                                 export.date_text(text),
                                                 wanted))

    # -- a discipline unticked on the tab strip gets no worksheet, and
    #    neither does one with nothing in it
    class _Disc(object):
        def __init__(self, key, discipline):
            self.key, self.discipline = key, discipline
    sample = [_Disc(1, u'Mech'), _Disc(2, u'Elec'), _Disc(3, u'Mech')]
    if [name for name, _m in export.worksheets(sample, set([u'Elec']))] != \
            [u'Mech']:
        fail.add('register_xlsx', 'an unticked discipline still gets a '
                 'worksheet')
    if export.worksheets([], set()) != []:
        fail.add('register_xlsx', 'an empty register still gets a worksheet')

    # -- worksheet names Excel accepts
    taken = set()
    long_a = u'Mechanical and Public Health Services North Block'
    long_b = u'Mechanical and Public Health Services South Block'
    made = [xlsx.safe_sheet_name(name, taken) for name in
            (u'Elec/Power: [Main]', long_a, long_b, u'', u'Sheet')]
    for name in made:
        if len(name) > 31 or re.search(r'[\[\]:*?/\\]', name) or not name:
            fail.add('register_xlsx', 'worksheet name "{0}" is one Excel '
                     'refuses'.format(name))
    if len(set([name.lower() for name in made])) != len(made):
        fail.add('register_xlsx', 'two worksheet names collide after the '
                 '31 character cut: {0}'.format(made))

    # -- a row with a height and no cells is still written. Checked on the
    #    writer itself: every row the register lays out happens to carry a
    #    styled cell, so the form alone would never catch this.
    bare = xlsx.Sheet(u'Bare')
    bare.set(1, 1, u'x')
    bare.height(3, 40)
    if not re.search(r'<row r="3"[^>]*ht="40', bare.xml()):
        fail.add('register_xlsx',
                 'a row carrying only a height was dropped - heights live '
                 'on <row>, so it has to be written with no cells in it')

    # -- a .NET zip that refuses falls back to Python's rather than losing
    #    the register
    saved_writer = xlsx._save_dotnet

    def refuse(path, parts):
        raise IOError('the .NET zip writer said no')
    xlsx._save_dotnet = refuse
    spare = tempfile.mkdtemp()
    try:
        book = xlsx.Workbook()
        book.add_sheet(u'Register').set(1, 1, u'x')
        ok, error = book.save(os.path.join(spare, 'fallback.xlsx'))
        if not ok:
            fail.add('register_xlsx',
                     'with .NET\'s zip refusing, the register was not written '
                     'at all: {0}'.format(error))
    finally:
        xlsx._save_dotnet = saved_writer
        shutil.rmtree(spare, ignore_errors=True)

    # -- the folder a register lands in alongside a run
    for given, wanted in (
            ([u'C:\\Out\\NPE7\\2026-10-06_09_30\\570',
              u'C:\\Out\\NPE7\\2026-10-06_09_30\\520'],
             u'C:\\Out\\NPE7\\2026-10-06_09_30'),
            ([u'C:\\Out\\NPE7\\Issue'], u'C:\\Out\\NPE7\\Issue'),
            ([u'C:\\A', u'D:\\B'], u''), ([], u'')):
        got = register.common_folder(given)
        if got != wanted:
            fail.add('register_xlsx', 'common folder of {0}: got "{1}", '
                     'wanted "{2}"'.format(given, got, wanted))

    # -- 1.24.0 pure decisions: paper, shading, logos
    for text, wanted in ((u'A4 portrait', (9, False)), (u'A3', (8, False)),
                         (u'A3 landscape', (8, True)), (u'', (9, False))):
        if export.paper_setup(text) != wanted:
            fail.add('register_xlsx', 'paper "{0}" read as {1}, wanted {2}'
                     .format(text, export.paper_setup(text), wanted))
    placed = export.fit_logos([(600, 300), (300, 300), (0, 0)], 500, 900, 176)
    shown = [one for one in placed if one]
    if len(placed) != 3 or placed[2] is not None or len(shown) != 2:
        fail.add('register_xlsx', 'logos placed as {0}'.format(placed))
    else:
        if shown[1][0] + shown[1][2] > 900 or shown[0][0] < 500 or \
                shown[1][0] < shown[0][0] + shown[0][2]:
            fail.add('register_xlsx', 'two logos run past the form or into '
                     'each other: {0}'.format(placed))
        for x, y, width, height in shown:
            if abs((176 - height) - 2 * y) > 2:
                fail.add('register_xlsx', 'a logo is not centred in the '
                         'title band: {0}'.format(placed))

    # -- a PNG and a JPEG in one book: each extension declared once
    folder = tempfile.mkdtemp()
    try:
        png = os.path.join(folder, 'a.png')
        jpeg = os.path.join(folder, 'b.jpg')
        handle = open(png, 'wb')
        handle.write(_png_bytes(20, 10))
        handle.close()
        handle = open(jpeg, 'wb')
        # Just enough JPEG for its size to be read: SOI, then SOF0.
        handle.write(b'\xff\xd8\xff\xc0\x00\x11\x08\x00\x10\x00\x20\x03'
                     + b'\x00' * 32)
        handle.close()
        book = xlsx.Workbook()
        first_sheet = book.add_sheet(u'One')
        first_sheet.set(1, 1, u'x')
        first_sheet.image(png, 10, 10, 20, 10)
        first_sheet.image(jpeg, 40, 10, 32, 16)
        second_sheet = book.add_sheet(u'Two')
        second_sheet.set(1, 1, u'x')
        second_sheet.image(png, 10, 10, 20, 10)
        parts = dict(book.parts())
        types = parts[u'[Content_Types].xml']
        for extension in ('png', 'jpeg'):
            if types.count('Extension="{0}"'.format(extension)) != 1:
                fail.add('register_xlsx', 'the {0} type is declared {1} '
                         'times - Excel refuses a picture whose extension '
                         'has no Default, and a repeated one'.format(
                             extension, types.count(
                                 'Extension="{0}"'.format(extension))))
        media = sorted([name for name, _payload in book.parts()
                        if name.startswith(u'xl/media/')])
        if media != [u'xl/media/image1.png', u'xl/media/image2.jpeg']:
            fail.add('register_xlsx', 'the same logo on two worksheets '
                     'should be one file in the book, each picture once '
                     'under its own name: {0}'.format(media))
        for number in (1, 2):
            targets = re.findall(r'Target="\.\./media/([^"]+)"', parts.get(
                u'xl/drawings/_rels/drawing{0}.xml.rels'.format(number), u''))
            for target in targets:
                if u'xl/media/' + target not in media:
                    fail.add('register_xlsx', 'drawing{0} points at {1}, '
                             'which is not in the book'.format(number, target))
        links = parts.get(u'xl/drawings/_rels/drawing1.xml.rels', u'')
        if links.count('Relationship ') != 2:
            fail.add('register_xlsx', 'two logos on a sheet need two '
                     'relationships from its drawing')
    finally:
        shutil.rmtree(folder, ignore_errors=True)

    # -- a whole register, written and taken apart
    columns = [register.RevisionColumn(501, 1, u'01/02/26', u'Stage 3', u'DB',
                                       u'Client'),
               register.RevisionColumn(502, 2, u'TBC', u'', u'DREW',
                                       u'Client, Architect')]
    columns[0].uid, columns[1].uid = u'u501', u'u502'

    def drawing(key, number, discipline, series, cells, current):
        made = register.RegisterRow(key, number, u'Title ' + number)
        made.discipline, made.series = discipline, series
        made.size, made.scale = u'A1', u'1:50'
        made.cells = dict([(columns[i].key, v) for i, v in cells.items()])
        made.current_key = columns[current].key
        made.current = made.cells.get(made.current_key, u'')
        made.current_sequence = u'987'
        made.status = u'S4'
        return made

    drawings = [drawing(1, u'M-1', u'Mechanical', u'570', {0: u'P01', 1: u'P02'}, 1),
                drawing(2, u'M-2', u'Mechanical', u'520', {0: u'D'}, 0),
                drawing(3, u'E-1', u'Electrical', u'630', {1: u'C01'}, 1)]
    register.assign_status_letters(columns, drawings)
    folder = tempfile.mkdtemp()
    try:
        logo = os.path.join(folder, 'logo.png')
        client = os.path.join(folder, 'client.png')
        for path, size in ((logo, (60, 20)), (client, (40, 30))):
            handle = open(path, 'wb')
            handle.write(_png_bytes(*size))
            handle.close()
        info = export.Info()
        info.logo = logo
        info.client_logo = client
        # The Revision Manager's columns: Issued To 1 ticked on both
        # issues, Issued To 2 on neither (left off), Method 1 on the
        # second; the first issue's status stored, the second's read from
        # its drawings.
        info.revision_columns = export.ps_revdata.default_columns()
        info.revision_values = {
            u'u501': {u'it1': u'1', u'status': u'S3'},
            u'u502': {u'it1': u'1', u'm1': u'1', u'it2': u'0'}}
        info.project_number = u'5797'
        info.series_param = u'BGL_Sheet Series'
        path = os.path.join(folder, 'register.xlsx')
        ok, message = export.write(path, columns, drawings, info)
        if not ok:
            fail.add('register_xlsx', 'not written: {0}'.format(message))
            return
        archive = zipfile.ZipFile(path)
        try:
            names = archive.namelist()
            types = archive.read('[Content_Types].xml').decode('utf-8')
            book = archive.read('xl/workbook.xml').decode('utf-8')
            styles = archive.read('xl/styles.xml').decode('utf-8')
            sheets = [archive.read(name).decode('utf-8') for name in names
                      if re.match(r'xl/worksheets/sheet\d+\.xml$', name)]
            drawing_xml = archive.read('xl/drawings/drawing1.xml').decode(
                'utf-8') if 'xl/drawings/drawing1.xml' in names else u''
        finally:
            archive.close()
        if len(sheets) != 2:
            fail.add('register_xlsx', '{0} worksheets for two disciplines'
                     .format(len(sheets)))
        if [one for one in sheets if '987' in one or 'Sequence' in one]:
            fail.add('register_xlsx', 'the sequence number reached the Excel '
                     'file - it is on screen only, the RD9 sheet has no '
                     'place for it')
        stored = [n for n in names if n.startswith('xl/media/')]
        if 'Extension="png"' not in types or len(stored) != 2 or \
                len(set(stored)) != len(stored):
            fail.add('register_xlsx', 'the company and client logos are not '
                     'both in the workbook')
        if drawing_xml.count('<xdr:pic>') != 2:
            fail.add('register_xlsx', 'the title band does not carry both '
                     'the client logo and the company logo')
        # 1.46.0: the company logo first, the client's to its right. The
        # company logo here is 60 x 20, the client's 40 x 30, so the first
        # picture drawn is the wider one.
        sizes = re.findall(r'<xdr:ext cx="(\d+)" cy="(\d+)"', drawing_xml)
        if len(sizes) == 2 and \
                float(sizes[0][0]) / float(sizes[0][1]) < \
                float(sizes[1][0]) / float(sizes[1][1]):
            fail.add('register_xlsx', 'the client logo comes before the '
                     'company logo - it belongs to its right')
        if '_xlnm.Print_Titles' not in book or '_xlnm.Print_Area' not in book:
            fail.add('register_xlsx', 'the form does not repeat on every '
                     'printed page, or prints beyond itself')
        defined = re.findall(r'<definedName name="([^"]+)" localSheetId="(\d+)"',
                             book)
        if defined != sorted(defined):
            fail.add('register_xlsx', 'defined names out of Excel\'s order '
                     '{0} - Excel repairs the book'.format(defined))
        for number, xml_text in enumerate(sheets, 1):
            order = [tag for tag in re.findall(
                r'<(\w+)[\s/>]', xml_text.split('<worksheet', 1)[1])
                if tag in WORKSHEET_ORDER]
            seen = []
            for tag in order:
                if not seen or seen[-1] != tag:
                    seen.append(tag)
            positions = [WORKSHEET_ORDER.index(tag) for tag in seen]
            if positions != sorted(positions):
                fail.add('register_xlsx',
                         'sheet{0}: elements out of schema order {1} - Excel '
                         'offers to repair the file'.format(number, seen))
            for ref in re.findall(r'<mergeCell ref="([A-Z]+\d+):([A-Z]+\d+)"',
                                  xml_text):
                if ref[0] == ref[1]:
                    fail.add('register_xlsx',
                             'sheet{0}: a single-cell merge at {1}, which '
                             'Excel calls corrupt'.format(number, ref[0]))
            if not re.search(r'<row r="2"[^>]*ht="35', xml_text):
                fail.add('register_xlsx',
                         'sheet{0}: the title band lost its height'
                         .format(number))
            if 'orientation="portrait"' not in xml_text or \
                    'paperSize="9"' not in xml_text or \
                    'left="0.25"' not in xml_text:
                fail.add('register_xlsx', 'sheet{0}: not the form\'s A4 '
                         'portrait page with its margins'.format(number))
            formats = re.findall(r'<xf [^>]*?(?:/>|>.*?</xf>)',
                                 styles.split('<cellXfs', 1)[-1], re.S)
            rotated = [str(index) for index, xf in enumerate(formats)
                       if 'textRotation="90"' in xf]
            used = set(re.findall(r' s="(\d+)"', xml_text))
            if not used & set(rotated):
                fail.add('register_xlsx',
                         'sheet{0}: nothing is rotated - the dates, Scale '
                         'and Current Rev run up the page on the form'
                         .format(number))

        # -- every logo anchored inside the cell it starts in
        widths = {}
        first_sheet_xml = sheets[0] if sheets else u''
        for low, high, width in re.findall(
                r'<col min="(\d+)" max="(\d+)" width="([\d.]+)"',
                first_sheet_xml):
            for col in range(int(low), int(high) + 1):
                widths[col - 1] = float(width)
        for col, offset, row in re.findall(
                r'<xdr:col>(\d+)</xdr:col><xdr:colOff>(\d+)</xdr:colOff>'
                r'<xdr:row>(\d+)</xdr:row>', drawing_xml):
            span = xlsx.width_pixels(widths.get(int(col), 8.43)) * \
                xlsx.EMU_PER_PIXEL
            if int(offset) >= span or int(row) > 1:
                fail.add('register_xlsx', 'a logo is anchored at column {0} '
                         'with an offset past its edge, or below the band - '
                         'Excel moves it'.format(col))

        try:
            import openpyxl
        except Exception:
            openpyxl = None
        if openpyxl is not None:
            try:
                loaded = openpyxl.load_workbook(path)
                first = loaded['Mechanical']
                # The TIDP form (1.44.0): Current Rev in E, the issues from
                # F; Issued To 1 then Method 1 (Issued To 2 has no tick and
                # is left off); the headings; the discipline; series 570, a
                # blank row, series 520; the footer.
                want = {'A3': u'Project No:', 'B3': u'Project Title:',
                        'C3': u'Day', 'C4': u'Month', 'C5': u'Year',
                        'A6': u'Issue Status: ', 'A8': u'Issued to:',
                        'B8': u'Issued To 1', 'B9': u'Issued Method 1',
                        'A4': u'5797',
                        'F3': u'01/02/26', 'G3': u'TBC',
                        'F6': u'S3', 'G6': u'S4',
                        'F8': u'x', 'G8': u'x', 'F9': None, 'G9': u'x',
                        'A10': u'Document No', 'B10': u'Document Title',
                        'C10': u'Sheet Size', 'D10': u'Scale',
                        'E10': export.DEFAULT_SNAPSHOT,
                        'F10': u'Document Issued',
                        'A11': u'Mechanical', 'A12': u'M-1', 'A13': None,
                        'A14': u'M-2', 'E12': u'P02', 'G12': u'P02',
                        'F14': u'D', 'D12': u'1:50'}
                for ref, value in sorted(want.items()):
                    if first[ref].value != value:
                        fail.add('register_xlsx',
                                 '{0} is {1!r}, the TIDP form has {2!r} '
                                 'there'.format(ref, first[ref].value, value))
                if first.max_column != 5 + export.MIN_ISSUE_COLUMNS:
                    fail.add('register_xlsx',
                             'the form is {0} columns wide - four, Current '
                             'Rev and at least {1} issue columns'.format(
                                 first.max_column, export.MIN_ISSUE_COLUMNS))
                for ref, colour in (('E10', export.CURRENT_FILL),
                                    ('E12', export.CURRENT_FILL),
                                    ('E13', export.CURRENT_FILL),
                                    ('F3', export.HEAD_FILL),
                                    ('A10', export.HEAD_FILL),
                                    ('F6', u'00000000'),
                                    ('F12', u'00000000')):
                    got = first[ref].fill.fgColor.rgb
                    if u'{0}'.format(got).upper() != colour.upper():
                        fail.add('register_xlsx', '{0} is shaded {1}; the '
                                 'form shades it {2}'.format(ref, got, colour))
                if first['F3'].alignment.text_rotation != 90 or \
                        first['E10'].alignment.text_rotation != 90:
                    fail.add('register_xlsx', 'the dates and Current Rev do '
                             'not run up the page')
                if first['B8'].border.bottom.style != 'medium':
                    fail.add('register_xlsx', 'no heavy line between the '
                             'Issued To rows and the Method rows')
                # 1.46.0: the Issued to block as the office bordered it -
                # heavy round it and between "Issued to:" and the names,
                # the issue columns carried through on thin lines.
                for ref, side, style in (
                        ('B8', 'top', 'medium'), ('G8', 'top', 'medium'),
                        ('B9', 'bottom', 'medium'),
                        ('G9', 'bottom', 'medium'),
                        ('B8', 'left', 'medium'), ('B9', 'left', 'medium'),
                        ('F8', 'left', 'thin'), ('E8', 'right', 'thin'),
                        ('F6', 'left', 'medium')):
                    got = getattr(first[ref].border, side).style
                    if got != style:
                        fail.add('register_xlsx', 'the Issued to block\'s '
                                 '{0} edge at {1} is {2}, the office form '
                                 'has {3}'.format(side, ref, got, style))
                if first['E12'].border.left.style != 'medium' or \
                        first['F12'].border.left.style != 'medium':
                    fail.add('register_xlsx', 'Current Rev and the issues '
                             'are not set off by heavy lines')
                footer = [str(one) for one in first.merged_cells.ranges
                          if one.min_row == one.max_row == 15]
                if footer != [u'A15:{0}15'.format(
                        xlsx.column_letter(first.max_column))]:
                    fail.add('register_xlsx', 'the footer is not one box '
                             'across the form under the drawings: {0}'
                             .format(footer))
            except Exception as err:
                fail.add('register_xlsx', 'openpyxl could not open it: '
                         '{0}: {1}'.format(err.__class__.__name__, err))

        # -- and with the Current Rev heading cleared, no such column
        info.snapshot = u''
        bare = export.build(columns, drawings, info)
        if bare.sheets[0].extent()[1] != 4 + export.MIN_ISSUE_COLUMNS:
            fail.add('register_xlsx', 'a blank Current Rev heading still '
                     'leaves the column')
    finally:
        shutil.rmtree(folder, ignore_errors=True)


# ==========================================================================
# rule 39 : a View/Sheet Set is written the way Revit will accept it
#
# Three silent failures in the 1.20.0 writer. ViewSheetSetting only works
# with the print range on Select; an existing set has to be made current
# before Save, because SaveAs on a taken name throws and Save on its own
# writes over whichever set happens to be current; and a set's own views are
# kept when the register only manages its sheets.
# ==========================================================================

class _FakeViewSet(list):
    def Insert(self, view):
        if view not in self:
            self.append(view)
        return True


class _FakeSetting(object):
    def __init__(self, manager):
        self.manager = manager
        self.calls = []
        self.current = type('S', (object,), {'Views': None})()

    def _get_current(self):
        return self.current

    def _set_current(self, value):
        self.calls.append(('current', value))
        self.current = value

    CurrentViewSheetSet = property(_get_current, _set_current)

    def Save(self):
        self.calls.append(('save', None))

    def SaveAs(self, name):
        self.calls.append(('saveas', name))


class _FakeManager(object):
    def __init__(self):
        self.PrintRange = 'current'
        self._setting = _FakeSetting(self)

    @property
    def ViewSheetSetting(self):
        if self.PrintRange != 'select':
            raise Exception('ViewSheetSetting needs PrintRange.Select')
        return self._setting


class _FakeTransaction(object):
    log = []

    def __init__(self, doc, name):
        pass

    def Start(self):
        _FakeTransaction.log.append('start')

    def Commit(self):
        _FakeTransaction.log.append('commit')

    def RollBack(self):
        _FakeTransaction.log.append('rollback')


class _FakeSheetElement(object):
    def __init__(self, name):
        self.name = name


class _FakeSavedSet(object):
    def __init__(self, views):
        self.Views = views


def rule_sheet_sets(root, fail):
    model = _module_under_stubs(root, 'ps_model', 'sheet_sets', fail)
    if model is None:
        return
    saved = (model.Transaction, model.ViewSet, model.PrintRange,
             model.ViewSheet, model.find_view_sheet_set)
    model.Transaction = _FakeTransaction
    model.ViewSet = _FakeViewSet
    model.PrintRange = type('PR', (object,), {'Select': 'select'})
    model.ViewSheet = _FakeSheetElement
    try:
        legend = 'a legend view'
        existing = _FakeSavedSet([_FakeSheetElement('old'), legend])
        sheets = [_FakeSheetElement('A'), _FakeSheetElement('B')]

        # -- updating a set that exists
        model.find_view_sheet_set = lambda doc, name: existing
        doc = type('D', (object,), {})()
        doc.PrintManager = _FakeManager()
        _FakeTransaction.log = []
        ok, message = model.save_view_sheet_set(doc, u'Issue A', sheets)
        setting = doc.PrintManager._setting
        if not ok:
            fail.add('sheet_sets', 'updating a set failed: {0}'.format(message))
        else:
            if ('current', existing) not in setting.calls:
                fail.add('sheet_sets',
                         'the existing set was not made current before it was '
                         'saved, so Save writes over whichever set was')
            if ('save', None) not in setting.calls or \
                    [c for c in setting.calls if c[0] == 'saveas']:
                fail.add('sheet_sets',
                         'an existing set has to be updated with Save; SaveAs '
                         'on a taken name throws')
            views = list(setting.current.Views or [])
            if legend not in views:
                fail.add('sheet_sets',
                         'the views already in the set were dropped')
            if [v for v in views if getattr(v, 'name', '') == 'old']:
                fail.add('sheet_sets',
                         'a sheet taken out of the register stayed in the set')
            if _FakeTransaction.log != ['start', 'commit']:
                fail.add('sheet_sets', 'not one transaction, committed: '
                         '{0}'.format(_FakeTransaction.log))

        # -- a new set
        model.find_view_sheet_set = lambda doc, name: None
        doc.PrintManager = _FakeManager()
        ok, message = model.save_view_sheet_set(doc, u'Issue B', sheets)
        calls = doc.PrintManager._setting.calls
        if not ok or ('saveas', u'Issue B') not in calls:
            fail.add('sheet_sets', 'a new set was not made with SaveAs: '
                     '{0} {1}'.format(message, calls))

        # -- an empty set is refused before Revit is asked
        doc.PrintManager = _FakeManager()
        _FakeTransaction.log = []
        ok, message = model.save_view_sheet_set(doc, u'Issue C', [])
        if ok or _FakeTransaction.log:
            fail.add('sheet_sets',
                     'an empty set was sent to Revit, which cannot hold one')
    except Exception as err:
        fail.add('sheet_sets', 'the writer threw {0}: {1}'.format(
            err.__class__.__name__, err))
    finally:
        (model.Transaction, model.ViewSet, model.PrintRange,
         model.ViewSheet, model.find_view_sheet_set) = saved

# ==========================================================================
# rule 40 : Revit's own PDF exporter is the default, and stays it
#
# A default only applies where the settings file says nothing, so a machine
# that once had a driver picked in Setup kept going to it. The v4 migration
# lets go of that for everybody once, and moves the register's untouched
# defaults onto the RD9 sheet without overwriting anything typed.
# ==========================================================================

def rule_pdf_default(root, fail):
    config = _module_under_stubs(root, 'ps_config', 'pdf_default', fail)
    window = _window_module(root, 'pdf_default', fail)
    if config is None or window is None:
        return
    defaults = config.SETTINGS_DEFAULTS
    if defaults.get('default_printer') != '' or \
            defaults.get('prefer_native_pdf') != '1':
        fail.add('pdf_default', 'a new machine does not start on Revit\'s '
                 'own PDF exporter')

    saved = (config.read_store, config.settings_path)
    config.settings_path = lambda: u'settings.txt'
    try:
        def settle(stored):
            config.read_store = lambda path: dict(stored)
            return config.Settings()

        # -- a machine left on PDF24 by Setup under 1.23.0
        old = settle({'settings_version': '3', 'default_printer': 'PDF24',
                      'prefer_native_pdf': '0',
                      'reg_title': u'Document Register & Issue Sheet',
                      'reg_legend': config.OLD_REG_DEFAULTS['reg_legend'],
                      'reg_issued_to': u'Client\tQS',
                      'reg_paper': u'A3'})
        store = old.store
        if store.get('default_printer') != '' or \
                store.get('prefer_native_pdf') != '1':
            fail.add('pdf_default', 'after the update a machine set to a '
                     'driver is still on it: "{0}", prefer native {1}'.format(
                         store.get('default_printer'),
                         store.get('prefer_native_pdf')))
        if not old.migrated or store.get('settings_version') != \
                u'{0}'.format(config.SETTINGS_VERSION):
            fail.add('pdf_default', 'the migration did not say it changed '
                     'anything, so nothing is saved and it runs again '
                     'every time')
        if store.get('reg_title') != defaults['reg_title'] or \
                store.get('reg_legend') != defaults['reg_legend']:
            fail.add('pdf_default', 'the register\'s untouched defaults did '
                     'not move onto the RD9 sheet\'s')
        if store.get('reg_issued_to') != u'Client\tQS':
            fail.add('pdf_default', 'a recipients list somebody typed was '
                     'replaced by the default: {0!r}'.format(
                         store.get('reg_issued_to')))
        if store.get('reg_paper') != u'A4 portrait':
            fail.add('pdf_default', 'the old A3 default became {0!r}, not '
                     'the form\'s A4 portrait'.format(store.get('reg_paper')))
        if settle({'settings_version': '3', 'reg_paper': u'A3 '}).store.get(
                'reg_paper') not in (u'A4 portrait', u'A3 portrait'):
            fail.add('pdf_default', 'a paper size with no orientation was '
                     'left without one')

        # -- once migrated, a driver chosen deliberately is kept
        chosen = settle({'settings_version': u'{0}'.format(
            config.SETTINGS_VERSION), 'default_printer': 'PDF24',
            'prefer_native_pdf': '0'})
        if chosen.store.get('default_printer') != 'PDF24' or chosen.migrated:
            fail.add('pdf_default', 'a driver chosen after the update was '
                     'taken away again')
    finally:
        config.read_store, config.settings_path = saved

    # -- and a template asking for a driver does not override the machine
    printer, refused, why = window.ProSheetsWindow.usable_printer(
        u'PDF24', u'C:\\Out', [u'PDF24'], True, True)
    if printer or refused != u'PDF24' or why != 'prefer-native':
        fail.add('pdf_default', 'a template naming PDF24 took the run off '
                 'Revit\'s own exporter: {0}'.format((printer, refused, why)))


# ==========================================================================
# rule 41 : "Open folder" lands in the issue, not one sheet series
#
# Exports go to root \ ... \ dated folder \ {series} \ PDF. The folder wanted
# after a run is the dated one, cut from a folder the plan built - expanding
# the tokens again at report time would give a different minute.
# ==========================================================================

def rule_issue_folder(root, fail):
    paths = _module_under_stubs(root, 'ps_paths', 'issue_folder', fail)
    window = _window_module(root, 'issue_folder', fail)
    if paths is None or window is None:
        return
    tokens = u'{Project Number}\\%Y-%m-%d_{Time}\\{BGL_Sheet Series}'
    series = u'BGL_Sheet Series'
    for given, wanted in (
            ((u'C:\\Out', tokens,
              u'C:\\Out\\NPE7\\2026-10-06_09_30\\570\\PDF', series),
             u'C:\\Out\\NPE7\\2026-10-06_09_30'),
            ((u'c:\\out\\', tokens,
              u'C:\\Out\\NPE7\\2026-10-06_09_30\\570', series),
             u'C:\\Out\\NPE7\\2026-10-06_09_30'),
            ((u'C:\\Out', u'{BGL_Sheet Series}\\{Date}',
              u'C:\\Out\\570\\2026-10-06\\PDF', series), u'C:\\Out'),
            ((u'\\\\srv\\jobs\\Out', u'{Project Number}/{BGL_Sheet Series}',
              u'\\\\srv\\jobs\\Out\\NPE7\\570\\DWG', series),
             u'\\\\srv\\jobs\\Out\\NPE7'),
            ((u'C:\\Out', u'{Date}\\{Sheet Series}',
              u'C:\\Out\\2026-10-06\\570\\PDF', u''),
             u'C:\\Out\\2026-10-06'),
            ((u'C:\\Out', u'{Project Number}\\{Date}',
              u'C:\\Out\\NPE7\\2026-10-06\\PDF', series), u''),
            ((u'C:\\Out', tokens, u'D:\\Elsewhere\\NPE7\\x\\570', series),
             u'')):
        got = paths.folder_before(*given)
        if got != wanted:
            fail.add('issue_folder', 'folder before the series for {0}: got '
                     '"{1}", wanted "{2}"'.format(given[2], got, wanted))

    # -- the window: planned from the jobs, opened when it exists
    class _Job(object):
        def __init__(self, folders):
            self.folders = folders

    class _Settings(object):
        def text(self, key, default=u''):
            return {'param_series': series}.get(key, default)

    class _Fake(object):
        settings = _Settings()
        _issue_folder = u''

        def _text_of(self, name):
            return {'RootFolderBox': u'C:\\Out',
                    'TokenBox': tokens}.get(name, u'')

        def register_folder(self, jobs, formats):
            return u'fallback'

        def _flag_of(self, name, default=False):
            return default

    fake = _Fake()
    jobs = [_Job({'pdf': u'C:\\Out\\NPE7\\2026-10-06_09_30\\570\\PDF',
                  'dwg': u'C:\\Out\\NPE7\\2026-10-06_09_30\\570\\DWG'}),
            _Job({'pdf': u'C:\\Out\\NPE7\\2026-10-06_09_30\\520\\PDF'})]
    got = window.ProSheetsWindow.issue_folder(fake, jobs, ['pdf', 'dwg'])
    if got != u'C:\\Out\\NPE7\\2026-10-06_09_30':
        fail.add('issue_folder', 'the run would open "{0}" rather than the '
                 'dated folder'.format(got))

    # -- 1.27.0: the register with a run goes to the same issue folder - it
    #    covers every series, and with one series ticked "above PDF" was
    #    that series' own folder.
    one_series = [_Job({'pdf': u'C:\\Out\\NPE7\\2026-10-06_09_30\\570\\PDF'})]
    got = window.ProSheetsWindow.register_folder(fake, one_series, ['pdf'])
    if got != u'C:\\Out\\NPE7\\2026-10-06_09_30':
        fail.add('issue_folder', 'with one series ticked the register went to '
                 '"{0}", inside that series, not the dated folder'.format(got))
    fake._text_of = lambda name: {'RootFolderBox': u'C:\\Out',
                                  'TokenBox': u'{Date}'}.get(name, u'')
    got = window.ProSheetsWindow.register_folder(
        fake, [_Job({'pdf': u'C:\\Out\\2026-10-06\\PDF'})], ['pdf'])
    if got.replace('/', '\\') != u'C:\\Out\\2026-10-06':
        fail.add('issue_folder', 'with no series level the register is not '
                 'in the folder above PDF: "{0}"'.format(got))

    # -- and its file carries the day it was written
    import datetime as _dt
    named = window.ps_register.register_file_name(
        u'Wrexham AFC', _dt.date(2026, 10, 6))
    if named != u'Wrexham AFC - Document Register - 2026-10-06.xlsx':
        fail.add('issue_folder', 'the register file is named "{0}", not '
                 '"<project> - Document Register - YYYY-MM-DD.xlsx"'
                 .format(named))
    if not re.search(r' - \d{4}-\d{2}-\d{2}\.xlsx$',
                     window.ps_register.register_file_name(u'P')):
        fail.add('issue_folder', 'the register file has no date suffix')
    fake._text_of = lambda name: {'RootFolderBox': u'C:\\Out',
                                  'TokenBox': u'{Date}'}.get(name, u'')
    if window.ProSheetsWindow.issue_folder(fake, jobs, ['pdf']) != \
            u'fallback':
        fail.add('issue_folder', 'with no series level it does not fall '
                 'back to the folder above the formats')

    class _Outcome(object):
        def __init__(self, path):
            self.path = path

    class _Report(object):
        def __init__(self, written):
            self._written = [_Outcome(path) for path in written]

        def written(self):
            return self._written

        def folders(self):
            return sorted(set([os.path.dirname(one.path)
                               for one in self._written]))

    planned = tempfile.mkdtemp()
    try:
        deep = os.path.join(planned, '570', 'PDF', 'M-1.pdf')
        fake._issue_folder = planned
        if window.ProSheetsWindow.folder_to_open(fake, _Report([deep])) != \
                planned:
            fail.add('issue_folder', 'Open folder went past the issue folder '
                     'into one series')
        fake._issue_folder = os.path.join(planned, 'gone')
        if window.ProSheetsWindow.folder_to_open(fake, _Report([deep])) != \
                os.path.dirname(deep):
            fail.add('issue_folder', 'with the issue folder missing it does '
                     'not fall back to where the files went')
    finally:
        shutil.rmtree(planned, ignore_errors=True)

    # -- 1.26.0: the register on its own, with nothing ticked
    class _Lookup(object):
        def __call__(self, name):
            return {u'Project Name': u'Wrexham AFC Kop Stand',
                    u'Project Number': u'5797'}.get(name, u'')

    def levels(path):
        return [part for part in re.split(r'[\\/]+', path) if part]

    made = paths.project_folder(
        u'C:\\Out', u'{Project Name}\\{Year}-{Month}-{Day}_{Hour}_{Minute}'
        u'\\{BGL_Sheet Series}', _Lookup(), series)
    if len(levels(made)) != 4 or levels(made)[2] != u'Wrexham AFC Kop Stand' \
            or not re.match(r'\d{4}-\d{2}-\d{2}_\d{2}_\d{2}$',
                            levels(made)[3]):
        fail.add('issue_folder', 'the register alone went to "{0}", not the '
                 'dated folder under the project'.format(made))
    made = paths.project_folder(u'C:\\Out', u'{Project Number}\\'
                                u'{BGL_Sheet Discipline}\\{Date}', _Lookup(),
                                series)
    if levels(made) != [u'C:', u'Out', u'5797']:
        fail.add('issue_folder', 'a level only a sheet can fill was made for '
                 'the register alone: "{0}"'.format(made))
    if paths.project_folder(u'', u'{Project Number}', _Lookup(), series):
        fail.add('issue_folder', 'with no root the register alone still got '
                 'a folder')

    class _Register(object):
        def __init__(self, on):
            self.on = on

        def add_to_export(self):
            return self.on

    lone = _Fake()
    lone.register = _Register(True)
    if not window.ProSheetsWindow.register_alone(lone, []) or \
            window.ProSheetsWindow.register_alone(lone, jobs):
        fail.add('issue_folder', 'a run with nothing ticked and Add to export '
                 'on is not the register alone (or one with sheets is)')
    lone.register = _Register(False)
    if window.ProSheetsWindow.register_alone(lone, []):
        fail.add('issue_folder', 'with Add to export off, nothing ticked is '
                 'still a register run')
    lone.register_alone_folder = lambda: u'alone'
    if window.ProSheetsWindow.register_folder(lone, [], []) != u'alone':
        fail.add('issue_folder', 'the register alone is not written into '
                 'the folder the tokens name without a sheet')

    source = read(os.path.join(root, 'ps_window.py'))
    start = source[source.find('    def start_export('):]
    start = start[:start.find('\n    def ', 10)]
    if start.find('self._start_register_alone()') < 0 or \
            start.find('self._start_register_alone()') > start.find(
                'Tick some sheets and at least one format first.'):
        fail.add('issue_folder', 'Export with nothing ticked stops at "tick '
                 'some sheets" instead of writing the register alone')
    ready = source[source.find('    def _say_export_ready('):]
    ready = ready[:ready.find('\n    def ', 10)]
    if 'self.register_alone(jobs)' not in ready:
        fail.add('issue_folder', 'the Export button stays greyed with only '
                 'the register to write')
    plan = source[source.find('    def _refresh_plan('):]
    plan = plan[:plan.find('\n    def ', 10)]
    if 'alone = self.register_alone(jobs)' not in plan or \
            'with_register = alone or' not in plan:
        fail.add('issue_folder', 'the Create list does not show the register '
                 'when it is the only thing to write')

    report = source[source.find('    def _show_report('):]
    report = report[:report.find('\n    def ', 10)]
    if report.count('ps_export.open_folder(target)') != 2 or \
            'self.folder_to_open(report)' not in report:
        fail.add('issue_folder', 'the report\'s two Open folder buttons do '
                 'not both open the issue folder')
    # 1.56.0: Export and Express Export both start the run through
    # _launch_export.
    if 'self._launch_export(jobs, formats, profile, quiet)' not in \
            _method_body(source, 'start_export'):
        fail.add('issue_folder', 'Export no longer starts the run through '
                 '_launch_export')
    start = _method_body(source, '_launch_export')
    planned_at = start.find('self._issue_folder = self.issue_folder(jobs, '
                            'formats)')
    if planned_at < 0 or planned_at > start.find('self._queue('):
        fail.add('issue_folder', 'the issue folder is not decided from the '
                 'plan before the run starts')


# ==========================================================================
# rule 42 : no precision format on a number that might be an int
#
# u'{0:.2f}'.format(15) is 15.00 in CPython and "Precision not allowed in
# integer format specifier" in IronPython. 1.24.0 lost every Document
# Register to a row height of 15. Nothing on the bench could see it, since
# the bench runs CPython - so the rule is about the source: every value
# given a precision has to be put through float() at the call.
# ==========================================================================

_PRECISION = re.compile(r'\.\d')


def _precision_fields(template):
    """[(argument index or name)] of the fields carrying a precision."""
    import string as _string
    found = []
    auto = 0
    try:
        parsed = list(_string.Formatter().parse(template))
    except Exception:
        return found
    for _literal, field, spec, _conv in parsed:
        if field is None:
            continue
        name = field.split('.', 1)[0].split('[', 1)[0]
        if name == '':
            key = auto
            auto += 1
        elif name.isdigit():
            key = int(name)
        else:
            key = name
        if spec and _PRECISION.search(spec) and spec.rstrip()[-1:] in 'fFeEgG%':
            found.append(key)
    return found


def _is_float_call(node):
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == 'float')


def rule_int_precision(root, fail):
    for path in source_files(root) + [os.path.join(root, 'script.py')]:
        if not os.path.isfile(path):
            continue
        base = os.path.basename(path)
        tree = ast.parse(read(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and \
                    isinstance(node.func, ast.Attribute) and \
                    node.func.attr == 'format' and \
                    isinstance(node.func.value, ast.Constant) and \
                    isinstance(node.func.value.value, str):
                for key in _precision_fields(node.func.value.value):
                    if isinstance(key, int):
                        arg = node.args[key] if key < len(node.args) else None
                    else:
                        arg = dict([(kw.arg, kw.value)
                                    for kw in node.keywords]).get(key)
                    if arg is None or not _is_float_call(arg):
                        fail.add('int_precision',
                                 '{0} line {1}: field {2} has a precision and '
                                 'its value is not put through float() - '
                                 'IronPython throws "Precision not allowed in '
                                 'integer format specifier" when it is an '
                                 'int'.format(base, node.lineno, key))
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod) \
                    and isinstance(node.left, ast.Constant) and \
                    isinstance(node.left.value, str) and \
                    re.search(r'%[-+ #0]*\d*\.\d+[fFeEgG]', node.left.value):
                values = node.right.elts if isinstance(node.right, ast.Tuple) \
                    else [node.right]
                if not all([_is_float_call(one) for one in values]):
                    fail.add('int_precision',
                             '{0} line {1}: a % format with a precision on a '
                             'value not put through float()'.format(
                                 base, node.lineno))


# ==========================================================================
# rule 43 : the Revision Manager stages, then writes in an order Revit takes
#
# Revit keeps an issued revision as it is and only merges two revisions that
# sit next to each other. So the order Apply writes in is the whole game:
# un-issue before editing, issue after, move a revision next to the one it
# merges into before combining. A fake Revit below refuses exactly what the
# real one refuses, and the staging is driven the way the window drives it.
# ==========================================================================

class _FakeRevit(object):
    """Revit's revisions, refusing what Revit refuses."""

    def __init__(self, rows):
        self.fields = dict([(key, dict(fields)) for key, fields in rows])
        self.order = [key for key, _fields in rows]
        self.log = []
        self.merged = []
        self._next = 900

    def ids(self):
        return list(self.order)

    def label(self, key):
        return u'{0}'.format(key)

    def create(self):
        self._next += 1
        self.fields[self._next] = {'issued': False}
        self.order.append(self._next)
        self.log.append(('create', self._next))
        return self._next

    def set_field(self, key, field, value):
        if field != 'issued' and self.fields[key].get('issued'):
            raise ValueError('revision {0} is issued'.format(key))
        self.fields[key][field] = value
        self.log.append(('set', key, field))

    def combine_with_previous(self, key):
        index = self.order.index(key)
        if index == 0:
            raise ValueError('nothing before it')
        into = self.order[index - 1]
        if self.fields[key].get('issued') or self.fields[into].get('issued'):
            raise ValueError('only unissued revisions merge')
        self.order.remove(key)
        self.merged.append((key, into))
        self.log.append(('merge', key, into))

    def delete(self, key):
        self.order.remove(key)
        self.log.append(('delete', key))

    def reorder(self, keys):
        if sorted(keys) != sorted(self.order):
            raise ValueError('every revision has to be in the new order')
        self.order = list(keys)
        self.log.append(('reorder',))

    def set_setting(self, name, value):
        self.log.append(('setting', name, value))


# The oldest Revit this tool may be dropped into. The brief is 2024-2027,
# but it has been opened on 2021, and a tool that will not load at all is a
# worse answer than one feature that says it needs a newer Revit.
OLDEST_REVIT = 2021

# Revit API names newer than that, and the release that introduced them.
# Grouped "from Autodesk.Revit.DB import (A, B, C)" is all or nothing: one
# name the host has never heard of throws ImportError at module load, and
# every module that imports it dies with it. Revit 2021 lost the whole tool
# to RevisionNumberingSequence this way - script.py -> ps_window ->
# ps_regview -> ps_revisions - so a name from this table has to be asked
# for inside try/except, with a fallback for every name in that import.
NEW_API_NAMES = {
    'RevisionNumberingSequence': 2022,
    'PDFExportOptions': 2022,
    'PDFExportQualityType': 2022,
    'ExportPaperFormat': 2022,
    'ColorDepthType': 2022,
    'UITheme': 2024,
    'UIThemeManager': 2024,
    'ContextMenu': 2025,
    'CommandMenuItem': 2025,
    'IContextMenuCreator': 2025,
}


def _handler_names(node):
    """Every name the except branches of a try assign."""
    found = set()
    for handler in getattr(node, 'handlers', []) or []:
        _top_level_names(getattr(handler, 'body', []) or [], found)
    return found


def rule_api_version_imports(root, fail):
    """A Revit API name newer than OLDEST_REVIT, imported where a missing
    one would take the module - and the tool - down with it.

    No run of the bench can see this: the stub namespace answers to every
    name. It is the shape of the import that has to be right.
    """
    for path in source_files(root):
        try:
            tree = ast.parse(read(path))
        except Exception:
            continue
        name = os.path.basename(path)
        tries = [node for node in ast.walk(tree) if isinstance(node, ast.Try)]
        inside = {}
        for node in tries:
            for statement in node.body:
                for one in ast.walk(statement):
                    if isinstance(one, ast.ImportFrom):
                        inside[one] = node
        at_module = set()

        def walk_module(body):
            for node in body:
                if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                    continue
                if isinstance(node, ast.ImportFrom):
                    at_module.add(node)
                for field in ('body', 'handlers', 'orelse', 'finalbody'):
                    branch = getattr(node, field, None)
                    if isinstance(branch, list) and branch and \
                            isinstance(branch[0], ast.AST):
                        walk_module(branch)

        walk_module(tree.body)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if not u'{0}'.format(node.module or u'').startswith(
                    'Autodesk.Revit'):
                continue
            names = [alias.asname or alias.name for alias in node.names]
            new = [one for one in names
                   if NEW_API_NAMES.get(one, 0) > OLDEST_REVIT]
            if not new:
                continue
            held = inside.get(node)
            if held is None:
                fail.add('api_version_imports',
                         '{0} line {1} imports {2} where nothing catches it. '
                         '{3} arrived in Revit {4}, so on anything older this '
                         'import throws at load and takes the module with '
                         'it - put it in its own try/except with a '
                         'fallback.'.format(
                             name, node.lineno, ', '.join(names), new[0],
                             NEW_API_NAMES[new[0]]))
                continue
            if node not in at_module:
                # Inside a function: the try's except is the fallback, and
                # nothing outside reads the name.
                continue
            missing = [one for one in names if one not in _handler_names(held)]
            if missing:
                fail.add('api_version_imports',
                         '{0} line {1} guards {2} but its except assigns no '
                         'fallback for {3}. On an older Revit the module '
                         'loads and then dies with NameError the first time '
                         'that name is read.'.format(
                             name, node.lineno, ', '.join(names),
                             ', '.join(missing)))

    # -- ElementId is only ever built through ps_model.make_id. A Python int
    #    handed to ElementId matches three constructors on Revit 2026 and
    #    IronPython refuses to choose - the 1.39.0 Change revision failure.
    for path in source_files(root):
        name = os.path.basename(path)
        try:
            tree = ast.parse(read(path))
        except Exception:
            continue
        allowed = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == 'make_id' \
                    and name == 'ps_model.py':
                for inner in ast.walk(node):
                    allowed.add(inner)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or node in allowed:
                continue
            func = node.func
            called = func.id if isinstance(func, ast.Name) else \
                (func.attr if isinstance(func, ast.Attribute) else u'')
            if called == 'ElementId':
                fail.add('api_version_imports',
                         '{0} line {1} builds an ElementId directly. On Revit '
                         '2026 a number matches ElementId(BuiltInParameter), '
                         '(BuiltInCategory) and (Int64) alike and IronPython '
                         'throws "Multiple targets could match" - go through '
                         'ps_model.make_id'.format(name, node.lineno))
    model = _module_under_stubs(root, 'ps_model', 'api_version_imports', fail)
    if model is not None:
        class _Int64(object):
            def __init__(self, value):
                self.value = value

        class _Int32(_Int64):
            pass

        class _Id2026(object):
            # Revit 2026: Int64, BuiltInCategory, BuiltInParameter - a bare
            # int is ambiguous.
            def __init__(self, value):
                if not isinstance(value, _Int64) or isinstance(value, _Int32):
                    raise TypeError('Multiple targets could match: '
                                    'ElementId(BuiltInParameter), '
                                    'ElementId(BuiltInCategory), '
                                    'ElementId(Int64)')
                self.Value = value.value

        class _Id2023(object):
            # Revit 2023: Int32 only.
            def __init__(self, value):
                if not isinstance(value, _Int32):
                    raise TypeError('expected Int32')
                self.Value = value.value
        kept = (model.ElementId, model.Int64, model.Int32)
        try:
            model.Int64, model.Int32 = _Int64, _Int32
            for era, kind in (('2026', _Id2026), ('2023', _Id2023)):
                model.ElementId = kind
                try:
                    got = model.make_id(u'501').Value
                except Exception as err:
                    got = err
                if got != 501:
                    fail.add('api_version_imports', 'make_id on a Revit {0} '
                             'ElementId gave {1}'.format(era, got))
        finally:
            model.ElementId, model.Int64, model.Int32 = kept

    # And the behaviour the fallback buys: no sequences, nothing thrown.
    revisions = _module_under_stubs(root, 'ps_revisions',
                                    'api_version_imports', fail)
    if revisions is not None:
        kept = revisions.RevisionNumberingSequence
        try:
            revisions.RevisionNumberingSequence = None
            if revisions.sequence_names(object()) != ({}, []):
                fail.add('api_version_imports', 'with no numbering sequence '
                         'API, sequence_names does not come back empty')
            # No doc on it: the refusal has to come before the write
            # touches the model at all.
            api = revisions.RevitApi.__new__(revisions.RevitApi)
            api.sequences = {}
            try:
                api.set_field(501, 'numbering', u'Sequence 1')
            except Exception as err:
                if '2022' not in u'{0}'.format(err):
                    fail.add('api_version_imports', 'setting Numbering '
                             'without the API says "{0}" - it should say '
                             'which Revit it needs'.format(err))
            else:
                fail.add('api_version_imports', 'setting Numbering without '
                         'the API was not refused')
        finally:
            revisions.RevisionNumberingSequence = kept


def rule_revision_manager(root, fail):
    revisions = _module_under_stubs(root, 'ps_revisions', 'revision_manager',
                                    fail)
    if revisions is None:
        return
    Entry, Staging = revisions.Entry, revisions.Staging

    # -- moving several at once
    keys = [u'a', u'b', u'c', u'd', u'e']
    for selected, step, wanted in (
            ([u'b', u'c'], -1, [u'b', u'c', u'a', u'd', u'e']),
            ([u'a', u'b'], -1, keys),
            ([u'a', u'c'], -1, [u'a', u'c', u'b', u'd', u'e']),
            ([u'd', u'e'], 1, keys),
            ([u'b', u'd'], 1, [u'a', u'c', u'b', u'e', u'd'])):
        got = revisions.move_within(keys, selected, step)
        if got != wanted:
            fail.add('revision_manager', 'moving {0} {1} gave {2}, wanted {3}'
                     .format(selected, u'up' if step < 0 else u'down', got,
                             wanted))
    got = revisions.move_keeping([u'a', u'X', u'b', u'c'],
                                 [u'a', u'b', u'c'], [u'b'], -1)
    if got != [u'b', u'X', u'a', u'c']:
        fail.add('revision_manager', 'a row staged to go was shuffled by a '
                 'move: {0}'.format(got))

    # -- a search on each column
    values = {'desc': u'Stage 3 Tender', 'date': u'01/02/26'}
    if not revisions.matches(values, {'desc': u'tender'}) or \
            revisions.matches(values, {'desc': u'tender', 'date': u'03'}) or \
            not revisions.matches(values, {'desc': u'', 'date': u'02'}):
        fail.add('revision_manager', 'column searches are not "contains, '
                 'any case, every column at once"')

    def staging():
        return Staging([
            Entry(501, 501, 1, {'numbering': u'Numeric', 'date': u'01/02/26',
                                'desc': u'Stage 3', 'issued': True,
                                'show': u'Cloud and Tag'},
                  [u'M-1', u'M-2'], 2),
            Entry(502, 502, 2, {'numbering': u'Numeric', 'desc': u'Tender',
                                'show': u'Cloud and Tag'}, [u'M-1'], 1),
            Entry(503, 503, 3, {'numbering': u'Alpha', 'desc': u'Draft',
                                'show': u'Tag'}),
            Entry(504, 504, 4, {'numbering': u'Alpha', 'desc': u'Late',
                                'show': u'Tag'})],
            revisions.PER_PROJECT, 5.0, [u'Numeric', u'Alpha'])

    # -- issued revisions are locked, as in Revit
    st = staging()
    ok, _message = st.set_field(u'501', 'desc', u'changed')
    if ok:
        fail.add('revision_manager', 'an issued revision took an edit Revit '
                 'would refuse')
    ok, _message = st.set_field(u'502', 'desc', u'Tender issue')
    if not ok or st.changed(u'502') != set(['desc']) or \
            st.pending(u'502') != u'Edited' or st.change_count() != 1:
        fail.add('revision_manager', 'one edit is not one green cell: '
                 'changed {0}, pending "{1}", count {2}'.format(
                     sorted(st.changed(u'502')), st.pending(u'502'),
                     st.change_count()))
    st.set_field(u'502', 'desc', u'Tender')
    if st.dirty():
        fail.add('revision_manager', 'typing a value back to what it was '
                 'still counts as a change')

    # -- deleting: in use is reported, the last one is kept, again restores
    st = staging()
    if [row[0] for row in st.in_use([u'501', u'502', u'503'])] != [1, 2]:
        fail.add('revision_manager', 'in use: {0}'.format(
            st.in_use([u'501', u'502', u'503'])))
    st.delete([u'502'])
    if st.entries[u'502'].live or st.pending(u'502') != u'Delete':
        fail.add('revision_manager', 'Delete did not stage the revision')
    st.delete([u'502'])
    if not st.entries[u'502'].live:
        fail.add('revision_manager', 'Delete on a staged row did not restore '
                 'it')
    ok, _message = st.delete([u'501', u'502', u'503', u'504'])
    if ok or not st.live_order():
        fail.add('revision_manager', 'every revision could be deleted - Revit '
                 'needs at least one')

    # -- merging: neighbours only, unissued only
    st = staging()
    ok, _message = st.merge(u'502', -1)
    if ok:
        fail.add('revision_manager', 'merged into an issued revision')

    # -- the whole of Revit's dialog at once, then written
    st = staging()
    st.set_setting('numbering', revisions.PER_SHEET)
    if st.set_setting('arc_mm', u'abc') or st.set_setting('arc_mm', 0):
        fail.add('revision_manager', 'an arc length that is not a positive '
                 'number was taken')
    st.set_field(u'501', 'issued', False)               # un-issue, then edit
    st.set_field(u'501', 'desc', u'Stage 3 rev')
    st.set_field(u'502', 'issued', True)                # edit, then issue
    new = st.add()
    st.set_field(new, 'desc', u'Construction')
    st.set_field(new, 'issued', True)
    st.move([u'504'], -1)                               # 501 502 504 503 new
    st.move([u'504'], -1)                               # 501 504 502 503 new
    ok, _message = st.merge(u'504', -1)                 # into 501: issued
    if ok:
        fail.add('revision_manager', 'merged into a revision issued in the '
                 'model')
    st.move([u'504'], 1)                                # 501 502 504 503 new
    st.move([u'504'], 1)                                # 501 502 503 504 new
    st.move([u'504'], 1)                                # 501 502 503 new 504
    st.move([new], -1)                                  # 501 502 new 503 504
    ok, message = st.merge(u'504', -1)                  # into 503
    if not ok:
        fail.add('revision_manager', 'merging two unissued neighbours was '
                 'refused: {0}'.format(message))
    plan = st.plan()
    if plan['edits'] != [(501, {'desc': u'Stage 3 rev'})]:
        fail.add('revision_manager', 'edits planned: {0}'.format(
            plan['edits']))
    if plan['unissue'] != [501] or plan['issue'] != [502, new] or \
            plan['merges'] != [(504, 503)] or \
            plan['settings'] != {'numbering': revisions.PER_SHEET}:
        fail.add('revision_manager', 'plan: unissue {0}, issue {1}, merges '
                 '{2}, settings {3}'.format(plan['unissue'], plan['issue'],
                                            plan['merges'], plan['settings']))

    fake = _FakeRevit([
        (501, {'issued': True}), (502, {'issued': False}),
        (503, {'issued': False}), (504, {'issued': False})])
    done, errors = revisions.execute(fake, plan)
    if errors:
        fail.add('revision_manager', 'Revit refused part of a valid plan: '
                 '{0}'.format(errors))
    if fake.merged != [(504, 503)]:
        fail.add('revision_manager', 'merged {0}, wanted 504 into 503'
                 .format(fake.merged))
    created = [entry[1] for entry in fake.log if entry[0] == 'create']
    if fake.order != [501, 502] + created + [503]:
        fail.add('revision_manager', 'the model ended in the order {0}, not '
                 'the one staged'.format(fake.order))
    if not (fake.fields[501].get('desc') == u'Stage 3 rev' and
            fake.fields[502].get('issued') and created and
            fake.fields[created[0]].get('issued') and
            fake.fields[created[0]].get('desc') == u'Construction'):
        fail.add('revision_manager', 'the written revisions are not what '
                 'was staged')

    # A merge whose neighbours were only neighbours after a staged move:
    # Revit merges with the one before, so it has to be put there first.
    st = staging()
    st.move([u'504'], -1)
    st.move([u'504'], -1)                               # 501 504 502 503
    st.merge(u'502', -1)                                # 502 into 504
    fake = _FakeRevit([
        (501, {'issued': True}), (502, {'issued': False}),
        (503, {'issued': False}), (504, {'issued': False})])
    revisions.execute(fake, st.plan())
    if fake.merged != [(502, 504)]:
        fail.add('revision_manager', 'a merge with a revision only next to it '
                 'after a move went into {0}'.format(fake.merged))

    # One refusal is reported and the rest still go in.
    fake = _FakeRevit([(501, {'issued': True}), (502, {'issued': False})])
    done, errors = revisions.execute(fake, {
        'settings': {}, 'unissue': [], 'creates': [], 'merges': [],
        'deletes': [], 'order': None, 'issue': [],
        'edits': [(501, {'desc': u'x'}), (502, {'desc': u'y'})]})
    if len(errors) != 1 or fake.fields[502].get('desc') != u'y':
        fail.add('revision_manager', 'one refused edit stopped the rest, or '
                 'was not reported: {0}'.format(errors))

    # -- the window and the register
    window = read(os.path.join(root, 'ps_revwin.py'))
    regview = read(os.path.join(root, 'ps_regview.py'))
    layout = read(os.path.join(root, 'ProSheets.xaml'))
    theme_xaml = read(os.path.join(root, 'Theme.xaml'))

    def body(text, name):
        part = text[text.find('    def {0}('.format(name)):]
        return part[:part.find('\n    def ', 10)]

    edit = body(window, '_beginning_edit')
    if 'self.staging.locked(key)' not in edit or 'args.Cancel = True' not in \
            edit:
        fail.add('revision_manager', 'an issued revision opens for editing')
    delete = body(window, '_delete')
    if 'self.staging.in_use(keys)' not in delete or \
            'self._confirm_delete(used)' not in delete:
        fail.add('revision_manager', 'a revision in use is deleted without '
                 'asking')
    apply_body = body(window, '_apply')
    if 'self.result = plan' not in apply_body or \
            'self._close(True)' not in apply_body:
        fail.add('revision_manager', 'Apply does not hand back the plan and '
                 'return to the register')
    if "('used', u'Used on sheets'" not in window:
        fail.add('revision_manager', 'no column of how many sheets use each '
                 'revision')
    if 'self._make_search(field)' not in window:
        fail.add('revision_manager', 'the columns have no search boxes')
    written = body(regview, '_revisions_written')
    opened = body(regview, 'open_revision_manager')
    if 'self.reload()' not in written or \
            'self._write_revisions(plan)' not in opened:
        fail.add('revision_manager', 'Apply is not written through Revit\'s '
                 'event, or the register is not read again afterwards')
    button = layout[layout.find('x:Name="RevisionManagerButton"'):]
    button = button[:button.find('</Button>')]
    big = theme_xaml[theme_xaml.find('x:Key="BigActionButton"'):]
    big = big[:big.find('</Style>')]
    if 'Style="{DynamicResource BigActionButton}"' not in button or \
            'Revision Manager' not in button or \
            'DropShadowEffect' not in big or 'IsPressed' not in big:
        fail.add('revision_manager', 'the Revision Manager is not the big, '
                 'pressable, shadowed button on the register tab')
    # 1.28.1: a plain blue triangle, nothing in it.
    if 'Stroke="{DynamicResource BlueBrush}"' not in button or \
            '<TextBlock Text="1"' in button:
        fail.add('revision_manager', 'the Revision Manager icon is not the '
                 'plain blue triangle')
    excel = theme_xaml[theme_xaml.find('x:Key="ExcelButton"'):]
    excel = excel[:excel.find('</Style>')]
    if 'DropShadowEffect' not in excel:
        fail.add('revision_manager', 'Export to Excel has no shadow')
    manager = read(os.path.join(root, 'ProSheetsRevisions.xaml'))
    for name in ('RevAddButton', 'RevDeleteButton', 'RevMoveUpButton',
                 'RevMoveDownButton'):
        part = manager[manager.find('x:Name="{0}"'.format(name)):]
        part = part[:part.find('</Button>')]
        if '<Path' not in part:
            fail.add('revision_manager', '{0} has no icon'.format(name))
    arc = manager[manager.find('x:Name="RevArcBox"'):]
    arc = arc[:arc.find('/>')]
    height = re.search(r'Height="(\d+)"', arc)
    if not height or int(height.group(1)) < 30:
        fail.add('revision_manager', 'the arc length box is too short to read '
                 'its number')


# ==========================================================================
# rule 44 : the Revision Manager's own columns survive the trip into the model
#
# Revit takes no parameters on revisions, so the extra columns live in
# Extensible Storage as text - every tab, newline and backslash in a note has
# to come back as it went in. Then they are pushed into real parameters, and
# a parameter of the wrong kind has to be refused rather than half-written.
# ==========================================================================

def rule_revision_columns(root, fail):
    revisions = _module_under_stubs(root, 'ps_revisions', 'revision_columns',
                                    fail)
    if revisions is None:
        return
    data = revisions.ps_revdata
    Column = data.Column

    # -- storage text round trips
    awkward = u'line one\nline\ttwo \\ back|slash'
    if data.unescape(data.escape(awkward)) != awkward:
        fail.add('revision_columns', 'a note with a tab, newline or backslash '
                 'does not come back as it went in')
    columns = [Column(u'notes', u'Revision notes', 'text'),
               Column(u'c1', u'Approved', 'yesno', target='sheets',
                      parameter=u'Rev Approved'),
               Column(u'c2', u'Stage', 'choice', [u'S2', u'S4'], 'clouds',
                      u'Stage')]
    back = data.decode_columns(data.encode_columns(columns))
    if back is None or len(back) != 3 or \
            not all([one.same(other) for one, other in zip(back, columns)]):
        fail.add('revision_columns', 'column definitions do not survive '
                 'being stored')
    if data.decode_columns(u'not ours') is not None:
        fail.add('revision_columns', 'text that is not ours was read as '
                 'column definitions')
    values = {u'uid-1': {u'notes': awkward, u'c1': u'1'},
              u'uid-2': {u'notes': u''}}
    back = data.decode_values(data.encode_values(values))
    if back != {u'uid-1': {u'notes': awkward, u'c1': u'1'}}:
        fail.add('revision_columns', 'values do not survive being stored: '
                 '{0}'.format(back))

    # -- what a cell takes
    number = Column(u'c3', u'Cost', 'number')
    for column, given, wanted in (
            (number, u'12.5', (True, u'12.5')), (number, u'abc', None),
            (columns[1], True, (True, u'1')), (columns[1], u'no', (True, u'0')),
            (columns[2], u'S9', None), (columns[2], u'', (True, u''))):
        got = data.normalise(column, given)
        if (wanted is None and got[0]) or (wanted is not None and
                                           got != wanted):
            fail.add('revision_columns', '{0} given {1!r} gave {2}'.format(
                column.name, given, got))
    for name, kind, choices, wanted in (
            (u'', 'text', [], False), (u'revision NOTES', 'text', [], False),
            (u'Stage 2', 'choice', [], False), (u'Checked', 'yesno', [], True)):
        if (not data.column_problem(name, kind, choices, columns)) != wanted:
            fail.add('revision_columns', 'a column "{0}" ({1}) was {2}'.format(
                name, kind, u'refused' if wanted else u'allowed'))
    if data.column_problem(u'Revision notes', 'text', [], columns, u'notes'):
        fail.add('revision_columns', 'a column cannot keep its own name')

    # -- into a parameter
    text = columns[0]
    for column, storage, value, wanted in (
            (text, 'String', u'hi', (True, u'hi')),
            (columns[1], 'Integer', u'1', (True, 1)),
            (columns[1], 'String', u'0', (True, u'No')),
            (number, 'Double', u'2.5', (True, 2.5)),
            (number, 'Integer', u'2.6', (True, 3)),
            (text, 'Integer', u'12', None), (number, 'Double', u'', None)):
        got = data.parameter_value(column, storage, value)
        if (wanted is None and got[0]) or (wanted is not None and
                                           got != wanted):
            fail.add('revision_columns', '{0} into a {1} parameter: {2}'
                     .format(column.name, storage, got))
    got = data.sheet_values([(1, 501), (2, None), (3, 999)],
                            {501: {u'notes': u'A'}, 999: {}}, text)
    if got != {1: u'A', 2: u'', 3: u''}:
        fail.add('revision_columns', 'sheets took {0} - a sheet with no '
                 'current revision, or one with no note, has to be '
                 'cleared'.format(got))

    # -- staged with everything else
    def staging(columns=None):
        return revisions.Staging([
            revisions.Entry(501, 501, 1, {'desc': u'Stage 3', 'issued': True},
                            uid=u'u501', custom={u'notes': u'old'}),
            revisions.Entry(502, 502, 2, {'desc': u'Tender'}, uid=u'u502')],
            revisions.PER_PROJECT, 5.0, [u'Numeric'], columns)

    st = staging()
    # 1.44.0: Revision notes, then Issue Status and the Issued To / Method
    # groups the Excel register plots.
    if [column.name for column in st.columns] != [
            data.DEFAULT_NOTES, data.STATUS_NAME, u'Issued To 1',
            u'Issued To 2', u'Issued To 3', u'Issued Method 1',
            u'Issued Method 2']:
        fail.add('revision_columns', 'a model with nothing stored does not '
                 'start with Revision notes, Issue Status and the Issued To '
                 'and Method columns: {0}'.format(
                     [column.name for column in st.columns]))
    if st.dirty():
        fail.add('revision_columns', 'the default column counts as a change')
    ok, message = st.set_custom(u'501', u'notes', u'Issued for tender')
    if not ok or u'x_notes' not in st.changed(u'501') or \
            st.pending(u'501') != u'Notes' or st.change_count() != 1:
        fail.add('revision_columns', 'a note on an issued revision was not '
                 'staged as one green cell: {0}'.format(message))
    ok, found = st.add_column(u'Revision NOTES', 'text')
    if ok:
        fail.add('revision_columns', 'two columns with one name')
    ok, cost = st.add_column(u'Cost', 'number')
    ok2, _message = st.set_custom(u'502', cost, u'lots')
    if not ok or ok2:
        fail.add('revision_columns', 'a Number column took text')
    new = st.add()
    st.set_custom(new, u'notes', u'For construction')
    st.delete([u'502'])
    plan = st.plan()
    custom = plan['custom']
    if not custom or [column.name for column in custom['columns']
                      if not column.group] != \
            [data.DEFAULT_NOTES, u'Cost'] or \
            custom['values'].get(501) != {u'notes': u'Issued for tender'} or \
            502 in custom['values'] or \
            custom['values'].get(new) != {u'notes': u'For construction'}:
        fail.add('revision_columns', 'the stored columns and values are not '
                 'what was staged: {0}'.format(custom))
    if plan['push']:
        fail.add('revision_columns', 'a push planned with nothing mapped')

    mapped = [Column(u'notes', u'Revision notes', 'text', target='sheets',
                     parameter=u'Rev Notes')]
    st = staging(mapped)
    if not revisions.plan_is_empty(st.plan()):
        fail.add('revision_columns', 'a mapped column with nothing changed '
                 'still plans a write')
    st.set_field(u'502', 'desc', u'Tender 2')
    plan = st.plan()
    if not plan['push'] or not plan['custom']:
        fail.add('revision_columns', 'an Apply with a column mapped does not '
                 'push it - a sheet whose revision moved keeps the old note')
    st = staging(mapped)
    st.push_requested = True
    if not st.plan()['push']:
        fail.add('revision_columns', 'Push to parameters planned nothing')

    # -- written after everything else, new revisions under their new ids
    class _Api(_FakeRevit):
        def write_custom(self, columns, values):
            self.log.append(('store', sorted(values)))

        def push(self, columns, values):
            self.log.append(('push', sorted(values)))
            return 2, [u'Revision notes -> "Rev Notes": 1 sheet not written']

    st = staging(mapped)
    new = st.add()
    st.set_custom(new, u'notes', u'New one')
    st.set_field(new, 'issued', True)
    fake = _Api([(501, {'issued': True}), (502, {'issued': False})])
    done, errors = revisions.execute(fake, st.plan())
    kinds = [entry[0] for entry in fake.log]
    created = [entry[1] for entry in fake.log if entry[0] == 'create']
    if kinds[-2:] != ['store', 'push'] or kinds.count('push') != 1:
        fail.add('revision_columns', 'the columns were not stored and then '
                 'pushed last: {0}'.format(kinds))
    elif not created or fake.log[-2][1] != sorted([501, 502] + created):
        fail.add('revision_columns', 'a new revision\'s values were not '
                 'stored under the id Revit gave it: {0}'.format(fake.log[-2]))
    if errors != [u'Revision notes -> "Rev Notes": 1 sheet not written']:
        fail.add('revision_columns', 'what the push could not write was not '
                 'reported: {0}'.format(errors))

    # -- the window
    window = read(os.path.join(root, 'ps_revwin.py'))
    dialog = read(os.path.join(root, 'ps_revcolwin.py'))
    regview = read(os.path.join(root, 'ps_regview.py'))
    if 'self.grid.Columns.Add(self._plus_column())' not in window or \
            'GreenBrush' not in window[window.find('PLUS_ICON = ('):][:400]:
        fail.add('revision_columns', 'no green + to add a column')
    if "not field.startswith(u'x_')" not in window:
        fail.add('revision_columns', 'issued revisions lock their notes too')
    if 'ps_revdata.KINDS' not in dialog or 'ColumnNameBox' not in dialog:
        fail.add('revision_columns', 'adding a column does not ask for its '
                 'name and type')
    if 'ps_revdata.bound_parameters(doc)' not in regview:
        fail.add('revision_columns', 'the column dialog cannot list the '
                 'parameters to map to')


# ==========================================================================
# rule 45 : the Revision Manager's own button opens it, from beside the tool
#
# The button is a thin loader in its own folder next to this one. It keeps no
# copy of the code: it puts this folder on the path and calls
# ps_revwin.run_standalone, so there is one manager and one version number.
# ==========================================================================

SIBLING_BUTTONS = ['Revision Manager.pushbutton']


def _png_size(path):
    try:
        handle = open(path, 'rb')
        try:
            head = handle.read(24)
        finally:
            handle.close()
    except Exception:
        return None
    if head[:8] != b'\x89PNG\r\n\x1a\n':
        return None
    import struct as _struct
    return _struct.unpack('>II', head[16:24])


def rule_revision_button(root, fail):
    button = os.path.join(os.path.dirname(os.path.abspath(root)),
                          'Revision Manager.pushbutton')
    if not os.path.isdir(button):
        fail.add('revision_button', 'there is no Revision Manager.pushbutton '
                 'beside the tool')
        return
    script_path = os.path.join(button, 'script.py')
    if not os.path.isfile(script_path):
        fail.add('revision_button', 'the Revision Manager button has no '
                 'script.py')
        return
    text = read(script_path)
    try:
        tree = ast.parse(text)
    except SyntaxError as err:
        fail.add('revision_button', 'its script.py will not parse: {0}'
                 .format(err))
        return
    for node in tree.body:
        names = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or '']
        for name in names:
            if name.split('.')[0] not in SAFE_TOP_IMPORTS:
                fail.add('revision_button', 'its script.py imports "{0}" at '
                         'module level, with nothing left to report a failure'
                         .format(name))
    for node in ast.walk(tree):
        if node.__class__.__name__ == 'JoinedStr':
            fail.add('revision_button', 'an f-string in its script.py, which '
                     'IronPython 2.7 cannot parse')
    if "'Pro Sheets Exporter.pushbutton'" not in text or \
            'sys.path.append(TOOL)' not in text:
        fail.add('revision_button', 'its script.py does not put Pro Sheets '
                 'Exporter on the path, so the manager cannot load')
    if 'ps_revwin.run_standalone(uiapp)' not in text:
        fail.add('revision_button', 'its script.py does not open the manager '
                 'on its own')
    if "__title__ = 'Revision\\nManager'" not in text:
        fail.add('revision_button', 'the button is not called Revision Manager')
    bundle = os.path.join(button, 'bundle.yaml')
    if not os.path.isfile(bundle) or 'Revision' not in read(bundle) or \
            'Manager' not in read(bundle):
        fail.add('revision_button', 'its bundle.yaml is missing or does not '
                 'title it Revision Manager')
    for name, size in (('icon.png', (96, 96)), ('icon.small.png', (32, 32))):
        if _png_size(os.path.join(button, name)) != size:
            fail.add('revision_button', '{0} is missing or not {1}x{2}'
                     .format(name, size[0], size[1]))
    window = read(os.path.join(root, 'ps_revwin.py'))
    body = window[window.find('def run_standalone('):]
    if 'ps_revisions.write(doc, plan)' not in body or \
            'uiapp.MainWindowHandle' not in body:
        fail.add('revision_button', 'run_standalone does not write the plan, '
                 'or does not sit in front of Revit')
    if '__persistentengine__ = True' not in text:
        fail.add('revision_button', 'its script.py does not keep the engine '
                 'alive. The manager is modeless, so the command returns '
                 'while the window is still up - without this every handler '
                 'in it, the Idling one included, is dead')


# ==========================================================================
# rule 46 : sheet series per revision, and mapping only to parameters that
#           can take the value
#
# A revision's series are the series of the sheets that carry it - each once.
# A column can only be pushed into an instance parameter bound to Sheets or
# Revision Clouds that holds the right kind of data: a type parameter would
# give every sheet one value, and a number in a Yes/No parameter is nonsense.
# ==========================================================================

def rule_revision_series(root, fail):
    revisions = _module_under_stubs(root, 'ps_revisions', 'revision_series',
                                    fail)
    if revisions is None:
        return
    data = revisions.ps_revdata

    got = revisions.series_of([(501, u'EC-CONTAINMENT'),
                               (501, u'BW-BUILDERSWORK'),
                               (501, u'EC-CONTAINMENT'), (502, u''),
                               (503, u' X ')])
    if got != {501: [u'BW-BUILDERSWORK', u'EC-CONTAINMENT'], 503: [u'X']}:
        fail.add('revision_series', 'series per revision: {0} - each series '
                 'once, blanks left out, in order'.format(got))
    entry = revisions.Entry(501, 501, 1, {'desc': u'Stage 3'})
    entry.series = [u'BW-BUILDERSWORK', u'EC-CONTAINMENT']
    st = revisions.Staging([entry, revisions.Entry(502, 502, 2, {})])
    if st.values(u'501').get('series') != u'BW-BUILDERSWORK, EC-CONTAINMENT' \
            or st.visible({'series': u'contain'}) != [u'501']:
        fail.add('revision_series', 'the Sheet series column cannot be '
                 'searched')

    parameters = [
        {'name': u'Rev Notes', 'categories': set(['sheets']),
         'instance': True, 'data': 'String'},
        {'name': u'Rev Type', 'categories': set(['sheets']),
         'instance': False, 'data': 'String'},
        {'name': u'Cloud Note', 'categories': set(['clouds']),
         'instance': True, 'data': 'String'},
        {'name': u'Approved', 'categories': set(['sheets']),
         'instance': True, 'data': 'YesNo'},
        {'name': u'Cost', 'categories': set(['sheets']),
         'instance': True, 'data': 'Double'}]
    for target, kind, wanted in (
            ('sheets', 'text', [u'Rev Notes']),
            ('sheets', 'yesno', [u'Approved', u'Rev Notes']),
            ('sheets', 'number', [u'Cost', u'Rev Notes']),
            ('clouds', 'text', [u'Cloud Note']),
            ('clouds', 'yesno', [u'Cloud Note'])):
        names = [name for name, _data in data.usable(parameters, target,
                                                      kind)]
        if names != wanted:
            fail.add('revision_series', '{0} column on {1} offered {2}, '
                     'wanted {3} - instance parameters on that category, of '
                     'data the column can be written as'.format(
                         kind, target, names, wanted))
    for name, kind, words in ((u'Rev Type', 'text', u'type parameter'),
                              (u'Nope', 'text', u'not in the project'),
                              (u'Cloud Note', 'text', u'not bound to'),
                              (u'Approved', 'text', u'holds Yes/No')):
        if words not in data.why_not(parameters, 'sheets', kind, name):
            fail.add('revision_series', 'why "{0}" is not offered: "{1}"'
                     .format(name, data.why_not(parameters, 'sheets', kind,
                                                name)))
    yesno = data.Column(u'c1', u'Ok', 'yesno')
    number = data.Column(u'c2', u'Cost', 'number')
    if data.parameter_value(yesno, 'YesNo', u'1') != (True, 1) or \
            data.parameter_value(number, 'YesNo', u'5')[0]:
        fail.add('revision_series', 'a Yes/No parameter is not written as '
                 'one, or takes a number')

    # -- the windows
    setwin = _module_under_stubs(root, 'ps_revsetwin', 'revision_series', fail)
    if setwin is not None:
        if not setwin.status_of(parameters, 'text', u'', u'')[0] or \
                setwin.status_of(parameters, 'text', 'sheets', u'')[0] or \
                setwin.status_of(parameters, 'text', 'sheets', u'Rev Type')[0] \
                or not setwin.status_of(parameters, 'text', 'sheets',
                                        u'Rev Notes')[0]:
            fail.add('revision_series', 'the Status column misreports a '
                     'mapping')
    window = read(os.path.join(root, 'ps_revwin.py'))
    regview = read(os.path.join(root, 'ps_regview.py'))
    manager = read(os.path.join(root, 'ProSheetsRevisions.xaml'))
    settings = read(os.path.join(root, 'ProSheetsRevSettings.xaml'))
    setup = read(os.path.join(root, 'ProSheetsSetup.xaml'))
    if "('series', u'Sheet series'" not in window or \
            'theme.group_colour(index, self.theme_name)' not in window:
        fail.add('revision_series', 'no coloured Sheet series column')
    template = window[window.find('SERIES_TEMPLATE = ('):]
    template = template[:template.find('\n\n')]
    if 'Binding series_open, Mode=TwoWay' not in template or \
            'series_items' not in template or 'series_head' not in template:
        fail.add('revision_series', 'clicking a Sheet series cell does not '
                 'open the full list')
    # 1.34.0: every cell open by default, chips wrapping to the column, and
    # one button to fold or unfold them all, remembered.
    config = read(os.path.join(root, 'ps_config.py'))
    toggle = window[window.find('    def _toggle_series('):]
    toggle = toggle[:toggle.find('    def _paint_series_button(')]
    if "'rev_series_open': '1'," not in config or \
            "row['series_open'] = self.series_open" not in window:
        fail.add('revision_series', 'the Sheet series cells do not open '
                 'expanded')
    if '<WrapPanel Orientation="Horizontal"/>' not in template or \
            'DockPanel.Dock="Right"' not in template:
        fail.add('revision_series', 'expanded series do not wrap to the '
                 'column width')
    if 'x:Name="RevSeriesToggleButton"' not in manager or \
            "('RevSeriesToggleButton', self._toggle_series)," not in window \
            or "row['series_open'] = self.series_open" not in toggle or \
            "self.settings.set('rev_series_open'," not in toggle:
        fail.add('revision_series', 'no Collapse/Expand series button, or '
                 'it does not reach every row or is not remembered')
    if 'x:Name="RevSettingsButton"' not in manager or \
            "('RevSettingsButton', self._open_settings)," not in window:
        fail.add('revision_series', 'no Settings button at the top right of '
                 'the manager')
    if 'x:Name="ProjectParamsButton"' not in settings or \
            'x:Name="MappingHelp"' not in settings or \
            'ps_revdata.MAPPING_HELP' not in read(os.path.join(
                root, 'ps_revsetwin.py')):
        fail.add('revision_series', 'the settings have no way to Project '
                 'Parameters, or no explanation of mapping')
    if "self.post_command = 'ProjectParameters'" not in window or \
            'RevitCommandId.LookupPostableCommandId' not in window:
        fail.add('revision_series', 'Open Project Parameters does not post '
                 'Revit\'s Project Parameters command')
    job = regview[regview.find('        def job(uiapp):'):]
    job = job[:job.find('        if self.host._queue(job):')]
    if 'self._write_revisions(plan)' not in job or \
            'ps_revwin.post_command(uiapp, post)' not in job:
        fail.add('revision_series', 'the write and the Project Parameters '
                 'command are not one job - the external event holds one, '
                 'and the second would replace the first')
    # -- 1.32.0: one Sheet series column, Used on sheets before it, red at
    #    0 and blue otherwise; columns dragged and remembered; parameters
    #    found by keyword.
    winmod = _module_under_stubs(root, 'ps_revwin', 'revision_series', fail)
    if winmod is not None:
        class _Fake(object):
            staging = type('S', (object,), {'columns': [
                data.Column(u'notes', u'Revision notes')]})()

            def _saved_order(self):
                return []

            def _group_of(self, field):
                return u''
        fields = [entry[0] for entry in
                  winmod.RevisionManager._layout(_Fake())]
        if fields.count('series') != 1 or fields.count('used') != 1:
            fail.add('revision_series', 'the manager lays out {0} - one '
                     'Sheet series column and one Used on sheets'.format(
                         fields))
        elif fields.index('used') + 1 != fields.index('series'):
            fail.add('revision_series', 'Used on sheets is not just left of '
                     'Sheet series: {0}'.format(fields))
        if 'pending' in fields or u"u'Change'" in window:
            fail.add('revision_series', 'the Change column is back')
        if 'ToolTip="{Binding pending}"' not in window:
            fail.add('revision_series', 'nothing says what is staged for a '
                     'row any more - it belongs on the Sequence cell')
        got = winmod.column_order([u'a', u'b', u'c', u'd'],
                                  [u'c', u'z', u'a'])
        if got != [u'c', u'a', u'b', u'd']:
            fail.add('revision_series', 'a dragged column order came back '
                     'as {0}'.format(got))
        used = getattr(winmod, 'USED_TEMPLATE', u'')
        if '<DataTrigger Binding="{{Binding used}}" Value="0">' not in used \
                or 'RedBrush' not in used or 'BlueBrush' not in used:
            fail.add('revision_series', 'Used on sheets is not red at 0 and '
                     'blue otherwise')
        # -- 1.36.0: the columns fit their text. Sheet series cannot: its
        #    chips wrap to the column, and a self-fitting column gives them
        #    no edge to wrap at. Description takes what is left rather than
        #    growing to its longest line.
        wide = dict([(entry[0], entry[2]) for entry in winmod.COLUMNS])
        loose = [field for field, width in wide.items()
                 if not winmod.fits(width)]
        if sorted(loose) != ['desc', 'series']:
            fail.add('revision_series', 'these columns do not fit their '
                     'text: {0} - every one but Description and Sheet '
                     'series should'.format(sorted(loose)))
        if wide.get('desc') != 0 or not wide.get('series') > 0:
            fail.add('revision_series', 'Description should take what is '
                     'left (0) and Sheet series keep a width its chips can '
                     'wrap at, not {0} and {1}'.format(wide.get('desc'),
                                                       wide.get('series')))
        unfitted = [kind for kind, width in winmod.CUSTOM_WIDTHS.items()
                    if not winmod.fits(width)]
        if unfitted:
            fail.add('revision_series', 'added columns of these kinds do '
                     'not fit their text: {0}'.format(sorted(unfitted)))
        if not winmod.AUTO_MIN or not winmod.AUTO_MAX > winmod.AUTO_MIN:
            fail.add('revision_series', 'a fitting column has no floor to '
                     'keep its search box usable, or no ceiling')
    if 'CanUserReorderColumns="True"' not in manager or \
            'self.grid.ColumnReordered += self._column_moved' not in window \
            or 'column.CanUserReorder = False' not in window or \
            "settings=self.host.settings" not in regview:
        fail.add('revision_series', 'the columns cannot be dragged, or the '
                 'order is not kept')
    names = [u'Revision Notes', u'Rev Type', u'Cloud Note']
    if data.matching(names, u'rev note') != [u'Revision Notes'] or \
            data.matching(names, u'') != names or \
            data.matching(names, u'NOTE') != [u'Revision Notes',
                                              u'Cloud Note']:
        fail.add('revision_series', 'keyword search over parameters is not '
                 '"every word, anywhere, any case"')
    setsource = read(os.path.join(root, 'ps_revsetwin.py'))
    if 'matcher=ps_revdata.matching' not in setsource:
        fail.add('revision_series', 'the settings have no keyword search for '
                 'parameters')

    fit = window[window.find('    def _fit_columns('):]
    fit = fit[:fit.find('    def _build_columns(')]
    if 'column.Width = DataGridLength.Auto' not in window or \
            'column.MinWidth = AUTO_MIN' not in window or \
            'column.MaxWidth = AUTO_MAX' not in window:
        fail.add('revision_series', 'the columns are not built to fit their '
                 'text, within a floor and a ceiling')
    if 'x:Name="RevFitColumnsButton"' not in manager or \
            "('RevFitColumnsButton', self._fit_columns)," not in window:
        fail.add('revision_series', 'no Fit columns button, or it is not '
                 'wired - a dragged column edge could never be handed back')
    if 'if not fits(wide.get(field, 0)):' not in fit or \
            'continue' not in fit:
        fail.add('revision_series', 'Fit columns re-fits Sheet series too, '
                 'whose chips would then never wrap')

    standalone = window[window.find('def run_standalone('):]
    if 'x:Name="SetupRevReopen"' not in setup or \
            "settings.flag('rev_reopen', True)" not in standalone or \
            'if post or not reopen:' not in standalone:
        fail.add('revision_series', 'Setup has no Revision Manager section, '
                 'or reopening after Apply ignores it')


def rule_revision_filters(root, fail):
    """1.33.0: a value list on every Revision Manager column, Excel's way,
    with Ctrl/Shift multi-select; and a Parameter box in the settings that
    narrows as you type into it."""
    revisions = _module_under_stubs(root, 'ps_revisions', 'revision_filters',
                                    fail)
    if revisions is None:
        return
    one = revisions.Entry(501, 501, 1, {'desc': u'Stage 3',
                                        'issued_to': u'Client'})
    one.series = [u'BW-BUILDERSWORK', u'EC-CONTAINMENT']
    two = revisions.Entry(502, 502, 2, {'desc': u'Stage 4', 'issued_to': u''})
    two.series = [u'EC-CONTAINMENT']
    three = revisions.Entry(503, 503, 3, {'desc': u'Tender',
                                          'issued_to': u'Client'})
    st = revisions.Staging([one, two, three])
    got = st.choices('series')
    if got != [u'BW-BUILDERSWORK', u'EC-CONTAINMENT', u'(Blanks)']:
        fail.add('revision_filters', 'the Sheet series list offers {0} - '
                 'each series on its own, once, blanks last'.format(got))
    got = st.choices('issued_to')
    if got != [u'Client', u'(Blanks)']:
        fail.add('revision_filters', 'the Issued to list offers {0}'.format(
            got))
    checks = (
        ({'series': set([u'BW-BUILDERSWORK'])}, [u'501']),
        ({'series': set([u'EC-CONTAINMENT'])}, [u'501', u'502']),
        ({'series': set([u''])}, [u'503']),
        ({'issued_to': set([u'Client'])}, [u'501', u'503']),
        ({'issued_to': set([u'Client']),
          'series': set([u'EC-CONTAINMENT'])}, [u'501']),
        ({}, [u'501', u'502', u'503']))
    for picks, wanted in checks:
        got = st.visible({}, picks)
        if got != wanted:
            fail.add('revision_filters', 'value filter {0} shows {1}, wanted '
                     '{2} - a row passes when any of its values is '
                     'ticked'.format(sorted(picks.items()), got, wanted))
    if st.visible({'desc': u'stage'}, {'series': set([u'EC-CONTAINMENT'])}) \
            != [u'501', u'502'] or \
            st.visible({'desc': u'tender'},
                       {'series': set([u'EC-CONTAINMENT'])}) != []:
        fail.add('revision_filters', 'searches and value filters do not '
                 'both apply')
    # Excel's rule: a column's own filter does not shrink its own list, the
    # others' do.
    picks = {'issued_to': set([u'Client'])}
    if st.choices('issued_to', {}, picks) != [u'Client', u'(Blanks)'] or \
            st.choices('series', {}, picks) != [u'BW-BUILDERSWORK',
                                                u'EC-CONTAINMENT',
                                                u'(Blanks)'] or \
            st.choices('series', {}, {'issued_to': set([u''])}) != \
            [u'EC-CONTAINMENT']:
        fail.add('revision_filters', 'a list shows what its own filter hides, '
                 'or ignores the other columns\' filters')

    window = read(os.path.join(root, 'ps_revwin.py'))
    manager = read(os.path.join(root, 'ProSheetsRevisions.xaml'))
    header = window[window.find('    def _header('):]
    header = header[:header.find('    def _make_search(')]
    if 'line.Children.Add(self._filter_button(field))' not in header:
        fail.add('revision_filters', 'the column headings have no value list')
    if 'visible = set(self.staging.visible(self.filters, self.picks,' \
            not in window or \
            'shown = len(self.staging.visible(self.filters, self.picks,' \
            not in window or \
            'self.staging.choices(field, self.filters, self.picks)' \
            not in window:
        fail.add('revision_filters', 'the value lists do not filter the grid')
    opener = window[window.find('    def _open_filter('):]
    opener = opener[:opener.find('    def set_pick(')]
    for needed, why in (
            ('listing.SelectionMode = SelectionMode.Extended',
             'Ctrl and Shift cannot select several values'),
            ('set_all(group, bool(sender.IsChecked))',
             'ticking one of several selected values does not tick them all'),
            ('if key != Key.Space:', 'Space does not tick the selected values'),
            ("every.Click += lambda sender, args: set_all(shown(), True)",
             'no All'),
            ("none.Click += lambda sender, args: set_all(shown(), False)",
             'no None'),
            ("self.set_pick(field, None if len(ticked) == len(boxes)",
             'everything ticked is still a filter'),
            ('holder.Children.Add(popup)', 'the list floats free of the '
             'window and loses its theme'),
            ('shell.MouseLeftButtonDown += swallow', 'a press in the list can '
             'start a column drag')):
        if needed not in opener:
            fail.add('revision_filters', why)
    keys = window[window.find('    def _key_down('):]
    keys = keys[:keys.find('    # ====')]
    if 'if self._filter_open:' not in keys:
        fail.add('revision_filters', 'Ctrl+Up in an open value list moves '
                 'revisions in the grid behind it')
    clear = window[window.find('    def _clear_searches('):]
    clear = clear[:clear.find('    def _key_down(')]
    if 'self.picks.pop(field, None)' not in clear or \
            'Content="Clear filters"' not in manager:
        fail.add('revision_filters', 'Clear filters leaves the value lists '
                 'filtering')

    ui = _module_under_stubs(root, 'ps_ui', 'revision_filters', fail)
    if ui is not None:
        picker = getattr(ui, 'SearchPicker', None)
        names = [u'Revision Notes', u'Rev Type', u'Cloud Note']
        if picker is None:
            fail.add('revision_filters', 'no SearchPicker in ps_ui')
        else:
            for text, value, wanted in (
                    (u'', u'', names),
                    (u'note', u'', [u'Revision Notes', u'Cloud Note']),
                    (u'REV NOTE', u'', [u'Revision Notes']),
                    (u'Rev Type', u'Rev Type', names),
                    (u'zzz', u'', [])):
                got = picker.shown(names, text, value)
                if got != wanted:
                    fail.add('revision_filters', 'typing "{0}" lists {1}, '
                             'wanted {2}'.format(text, got, wanted))
            if picker.resolve(names, u'rev type') != u'Rev Type' or \
                    picker.resolve(names, u'rev') != u'':
                fail.add('revision_filters', 'a part-typed name counts as '
                         'picked, or a whole one does not')
    uisource = read(os.path.join(root, 'ps_ui.py'))
    for needed in ('self.box.TextChanged += self._typed',
                   'self.box.PreviewKeyDown += self._key',
                   'self.list.PreviewMouseLeftButtonUp += self._clicked',
                   'self.element.Children.Add(self.popup)'):
        if needed not in uisource:
            fail.add('revision_filters', 'the Parameter box is not wired: '
                     '{0}'.format(needed))
    setwin = _module_under_stubs(root, 'ps_revsetwin', 'revision_filters', fail)
    if setwin is not None:
        if u'Search' in setwin.HEADINGS or \
                len(setwin.HEADINGS) != len(setwin.WIDTHS):
            fail.add('revision_filters', 'the settings still have a separate '
                     'Search column: {0}'.format(setwin.HEADINGS))
    setsource = read(os.path.join(root, 'ps_revsetwin.py'))
    if 'parameter = ps_ui.SearchPicker(' not in setsource or \
            'self._place(line, parameter.element, 3)' not in setsource or \
            'parameter.on_change = self._make_picked(row)' not in setsource:
        fail.add('revision_filters', 'the Parameter box cannot be typed into')


# ==========================================================================
# rule 49 : the standalone Revision Manager is modeless
#
# Revit stays usable while it is open, which is three rules in one and all
# three are how a modeless Revit tool is usually wrong:
#   - a modeless window is in NO API context, so Apply has to go out through
#     an ExternalEvent, and reading the model has to happen in Idling;
#   - the command returns while the window is still up, so the engine has to
#     be persistent and the window has to be referenced at module level, or
#     pyRevit collects it and every handler in it dies;
#   - an Idling handler left subscribed after the window has gone is a
#     handler Revit calls into a dead engine.
# ==========================================================================

def rule_revision_modeless(root, fail):
    window = read(os.path.join(root, 'ps_revwin.py'))
    manager = read(os.path.join(root, 'ProSheetsRevisions.xaml'))
    winmod = _module_under_stubs(root, 'ps_revwin', 'revision_modeless', fail)
    revisions = _module_under_stubs(root, 'ps_revisions', 'revision_modeless',
                                    fail)

    # -- which row a selection takes the list to
    if winmod is not None:
        order = [u'501', u'502', u'503']
        for keys, current, wanted in (
                ([u'502'], [], u'502'),
                ([u'502'], [u'502'], None),       # already there: leave it
                ([u'502'], [u'501'], u'502'),
                ([u'999'], [], None),             # not in the list at all
                ([u'999', u'503'], [], u'503'),   # the first one it holds
                # Two clouds, both revisions in the list: the FIRST wins.
                ([u'503', u'502'], [], u'503'),
                ([u'502', u'503'], [], u'502'),
                ([], [u'501'], None),
                ([u'502'], [u'502', u'503'], u'502')):
            got = winmod.jump_target(keys, order, current)
            if got != wanted:
                fail.add('revision_modeless', 'selecting {0} with {1} '
                         'selected in the list goes to {2}, wanted {3}'
                         .format(keys, current, got, wanted))

    # -- clouds to revision keys, and never raising on the way
    if revisions is not None:
        class _Cloud(object):
            def __init__(self, value):
                self.RevisionId = value

        class _Wall(object):
            pass
        got = revisions.revision_keys_of(
            [_Wall(), _Cloud(_FakeId(501)), _Cloud(_FakeId(502)),
             _Cloud(_FakeId(501)), _Wall(), _Cloud(_FakeId(-1))])
        # Text keys: Entry.key is text, so an int here would match nothing
        # in staging.order and the list would never move.
        if got != [u'501', u'502']:
            fail.add('revision_modeless', 'the revisions of a selection came '
                     'back as {0} - every cloud once, in order, anything '
                     'else skipped'.format(got))

        class _Hostile(object):
            def __getattr__(self, name):
                raise ValueError('no document here')
        if revisions.selection_token(_Hostile()) != () or \
                revisions.selected_revision_keys(_Hostile()) != []:
            fail.add('revision_modeless', 'reading the selection throws '
                     'instead of coming back empty. It runs on every Idling '
                     'tick, and one throw there is a dialog in the user\'s '
                     'face every second')

    # -- modeless, and all three of its consequences
    body = window[window.find('def run_standalone('):]
    job = body[body.find('        def job(event_uiapp):'):]
    job = job[:job.find('        HANDLER.work = job')]
    for needed, why in (
            ('self.window.Show()',
             'the manager is still shown modal, so Revit is blocked'),
            ('if not self.modeless:',
             'DialogResult is set on a modeless window, which throws'),
            ('uiapp.Idling += self._idling',
             'nothing follows the selection in Revit'),
            ('self._uiapp.Idling -= self._idling',
             'Idling is never handed back, so Revit keeps calling into the '
             'window after it has gone'),
            ('self.window.Closed += self._on_closed',
             'closing the window does not unsubscribe Idling'),
            ('if not self.follow or self._editing:',
             'the list is yanked about mid-edit, or cannot be told to stop '
             'following'),
            ('self._editing = True',
             'nothing marks an edit as open, so following cannot hold off'),
            ('ps_ui.set_visible(self.follow_button, self.modeless)',
             'the follow chip shows on the modal manager, where Revit '
             'cannot be touched anyway'),
            ("('RevFollowButton', self._toggle_follow),",
             'the follow chip is not wired')):
        if needed not in window:
            fail.add('revision_modeless', why)
    if 'x:Name="RevFollowButton"' not in manager:
        fail.add('revision_modeless', 'no follow chip in the manager')
    for needed, why in (
            ('EVENT = ExternalEvent.Create(HANDLER)',
             'Apply has no external event to go through'),
            ('HANDLER.work = job', 'the plan is never queued'),
            ('EVENT.Raise()', 'the queued plan is never raised'),
            ('MANAGER.window.Activate()',
             'a second manager opens over the first, each with its own '
             'staged changes'),
            ('manager.watch_selection(uiapp)',
             'the window never starts following the selection'),
            ('manager.show_modeless()', 'the window is not shown modeless')):
        if needed not in body:
            fail.add('revision_modeless', why)
    if 'MANAGER = None' not in window or 'HANDLER = None' not in window or \
            'EVENT = None' not in window:
        fail.add('revision_modeless', 'the window, handler and event are not '
                 'parked at module level - pyRevit collects what it does not '
                 'consider referenced, and takes the live window with it')
    if 'ps_revisions.write(doc, plan)' not in job:
        fail.add('revision_modeless', 'the write does not happen inside the '
                 'queued job. A modeless window is in no API context, so '
                 'writing where it stands throws')
    if 'manager.on_ui(back)' not in body:
        fail.add('revision_modeless', 'the window is updated straight from '
                 'the external event rather than on its own thread')


# ==========================================================================
# rule 50 : picking on the Document Register - Isolate, Change revision on
#           sheet - and the tool's size
#
# The sequence number picks a revision column; a revision cell can be picked
# too. Both follow Excel's click rules. Change revision on sheet follows a
# revision to both places it can live on a sheet - added by hand, and drawn
# as clouds - and never re-points a cloud that also shows on a sheet nobody
# picked, which would quietly change that sheet too.
# ==========================================================================

def _method_body(text, name):
    """One method of a class, exactly: from its def to the next def at the
    same depth. Slicing "to the next method by name" breaks the moment a
    method is added in between - and then the newcomer's lines answer for
    the method being checked."""
    start = text.find('    def {0}('.format(name))
    if start < 0:
        return u''
    end = text.find('\n    def ', start + 1)
    return text[start:end if end > 0 else len(text)]


class _SwapSheet(object):
    def __init__(self, key, number, additional, views=None):
        self.Id = _FakeId(key)
        self.SheetNumber = number
        self.additional = [int(one) for one in additional]
        self.views = list(views or [])

    def GetAllPlacedViews(self):
        return [_FakeId(one) for one in self.views]

    def GetAdditionalRevisionIds(self):
        return [_FakeId(one) for one in self.additional]

    def SetAdditionalRevisionIds(self, ids):
        self.additional = sorted([int(one.Value) for one in ids])


class _SwapCloud(object):
    def __init__(self, key, revision, sheets):
        self.Id = _FakeId(key)
        self.RevisionId = _FakeId(revision)
        self.sheets = sheets

    def GetSheetIds(self):
        return [_FakeId(one) for one in self.sheets]


class _SwapRevision(object):
    def __init__(self, key, issued=False):
        self.Id = _FakeId(key)
        self.Issued = issued


class _SwapDoc(object):
    def __init__(self, elements, clouds):
        self.elements = dict([(one.Id.Value, one) for one in elements])
        self.clouds = clouds
        for cloud in clouds:
            self.elements[cloud.Id.Value] = cloud
        self.transactions = []

    def GetElement(self, element_id):
        return self.elements.get(int(element_id.Value))

    def Delete(self, element_id):
        gone = self.elements.pop(int(element_id.Value), None)
        if gone in self.clouds:
            self.clouds.remove(gone)
        self.deleted = getattr(self, 'deleted', []) + [int(element_id.Value)]


class _SwapCollector(object):
    """FilteredElementCollector: the whole model, or - given a view - what
    that view shows, from the doc's ``shows`` map {view id: [cloud ids]}.
    A doc with no map answers a view-scoped collector the way a Revit that
    shows no annotation would: by refusing."""

    def __init__(self, doc, view_id=None):
        self.doc = doc
        self.view_id = view_id

    def OfClass(self, kind):
        if self.view_id is None:
            return list(self.doc.clouds)
        shows = getattr(self.doc, 'shows', None)
        if shows is None:
            raise ValueError('no view-scoped collector here')
        wanted = set(shows.get(int(self.view_id.Value), []))
        return [cloud for cloud in self.doc.clouds
                if int(cloud.Id.Value) in wanted]


class _SwapTransaction(object):
    def __init__(self, doc, name):
        self.doc = doc
        self.state = 'new'
        doc.transactions.append(self)

    def Start(self):
        self.state = 'started'

    def Commit(self):
        self.state = 'committed'

    def RollBack(self):
        self.state = 'rolled back'


def rule_register_picks(root, fail):
    register = _module_under_stubs(root, 'ps_register', 'register_picks', fail)
    revisions = _module_under_stubs(root, 'ps_revisions', 'register_picks',
                                    fail)
    ui = _module_under_stubs(root, 'ps_ui', 'register_picks', fail)
    swapwin = _module_under_stubs(root, 'ps_revswapwin', 'register_picks',
                                  fail)
    view = read(os.path.join(root, 'ps_regview.py'))
    layout = read(os.path.join(root, 'ProSheets.xaml'))

    # -- the click rules
    if register is not None:
        order = [u'r1', u'r2', u'r3', u'r4']
        for picked, key, anchor, ctrl, shift, wanted in (
                ([], u'r2', None, False, False, ([u'r2'], u'r2')),
                ([u'r2'], u'r2', u'r2', False, False, ([], u'r2')),
                ([u'r1'], u'r3', u'r1', False, False, ([u'r3'], u'r3')),
                ([u'r1'], u'r3', u'r1', True, False, ([u'r1', u'r3'], u'r3')),
                ([u'r1', u'r3'], u'r3', u'r3', True, False, ([u'r1'], u'r3')),
                ([u'r2'], u'r4', u'r2', False, True,
                 ([u'r2', u'r3', u'r4'], u'r2')),
                ([u'r1'], u'r3', u'r3', True, True,
                 ([u'r1', u'r3'], u'r3')),
                ([u'r1'], u'r9', u'r1', False, False, ([u'r1'], u'r1'))):
            got = register.column_picks(picked, key, anchor, order, ctrl,
                                        shift)
            if got != wanted:
                fail.add('register_picks', 'a click on {0} (ctrl {1}, shift '
                         '{2}) with {3} picked gave {4}, wanted {5}'.format(
                             key, ctrl, shift, picked, got, wanted))
        rows, cols = [u'a', u'b', u'c'], [u'r1', u'r2']

        def filled(sheet, column):
            return (sheet, column) != (u'b', u'r2')
        for picked, cell, anchor, ctrl, shift, wanted in (
                (set(), (u'a', u'r1'), None, False, False,
                 set([(u'a', u'r1')])),
                (set([(u'a', u'r1')]), (u'a', u'r1'), (u'a', u'r1'), False,
                 False, set()),
                (set([(u'a', u'r1')]), (u'c', u'r2'), (u'a', u'r1'), True,
                 False, set([(u'a', u'r1'), (u'c', u'r2')])),
                (set(), (u'c', u'r2'), (u'a', u'r1'), False, True,
                 set([(u'a', u'r1'), (u'a', u'r2'), (u'b', u'r1'),
                      (u'c', u'r1'), (u'c', u'r2')])),
                (set([(u'a', u'r1')]), (u'b', u'r2'), None, False, False,
                 set([(u'a', u'r1')]))):
            got = register.cell_picks(picked, cell, anchor, rows, cols,
                                      filled, ctrl, shift)[0]
            if got != wanted:
                fail.add('register_picks', 'a click on cell {0} (ctrl {1}, '
                         'shift {2}) gave {3}, wanted {4} - an empty cell '
                         'carries no revision and is never picked'.format(
                             cell, ctrl, shift, sorted(got), sorted(wanted)))

        class _Row(object):
            def __init__(self, key, cells):
                self.key = key
                self.cells = cells
        sample = [_Row(1, {u'r1': u'P01'}), _Row(2, {u'r2': u'P02'}),
                  _Row(3, {u'r1': u'', u'r3': u'P03'})]
        if [row.key for row in register.isolated_rows(sample, [u'r1', u'r2'])] \
                != [1, 2] or \
                len(register.isolated_rows(sample, [])) != 3:
            fail.add('register_picks', 'Isolate does not keep the sheets '
                     'carrying ANY of the picked revisions, or isolates to '
                     'nothing when none is picked')
        if register.element_of(u'r1234') != u'1234' or \
                register.element_of(u'num') != u'':
            fail.add('register_picks', 'a revision column key does not lead '
                     'back to its revision')

    # -- what Change revision on sheet decides
    if revisions is not None:
        clouds = [(u'c1', u'10', set([u'1'])),
                  (u'c2', u'10', set([u'1', u'2'])),
                  (u'c3', u'10', set([u'2', u'3'])),
                  (u'c4', u'11', set([u'3']))]
        by_hand = {u'1': set([u'10']), u'2': set(), u'3': set([u'11'])}
        got = revisions.plan_swap({u'1': set([u'10']), u'2': set([u'10'])},
                                  u'20', by_hand, clouds, set())
        if sorted(got['clouds']) != [u'c1', u'c2']:
            fail.add('register_picks', 'clouds re-pointed: {0}. c1 and c2 '
                     'only reach picked sheets; c3 also shows on sheet 3, '
                     'which was not picked, and moving it would change that '
                     'sheet too'.format(sorted(got['clouds'])))
        if got['additional'] != {u'1': set([u'20'])}:
            fail.add('register_picks', 'the revision added by hand was not '
                     'swapped on the sheet: {0}'.format(got['additional']))
        if got['changed'] != [(u'1', u'10')] or \
                [one[:2] for one in got['skipped']] != [(u'2', u'10')] or \
                'also show' not in got['skipped'][0][2]:
            fail.add('register_picks', 'sheet 2 still carries the old '
                     'revision through the shared cloud, and has to be '
                     'reported, not counted as changed: {0} / {1}'.format(
                         got['changed'], got['skipped']))
        got = revisions.plan_swap({u'3': set([u'11', u'30'])}, u'20',
                                  {u'3': set([u'11', u'30'])}, clouds,
                                  set([u'30']))
        if got['changed'] != [(u'3', u'11')] or \
                [one[:2] for one in got['skipped']] != [(u'3', u'30')] or \
                'issued' not in got['skipped'][0][2] or \
                u'30' not in got['additional'].get(u'3', set()):
            fail.add('register_picks', 'an issued revision was taken off a '
                     'sheet, or took the rest down with it: {0}'.format(got))
        got = revisions.plan_swap({u'1': set([u'10'])}, u'30', by_hand,
                                  clouds, set([u'30']))
        if got['clouds'] or got['additional'] or not got['skipped']:
            fail.add('register_picks', 'cells were moved ONTO an issued '
                     'revision, which Revit refuses')
        got = revisions.plan_swap({u'1': set([u'20'])}, u'20', by_hand,
                                  clouds, set())
        if got['changed'] or 'already' not in got['skipped'][0][2]:
            fail.add('register_picks', 'changing a cell to what it already '
                     'is was not left alone')
        got = revisions.plan_swap({u'2': set([u'11'])}, u'20', by_hand,
                                  clouds, set())
        if got['changed'] or 'Refresh' not in got['skipped'][0][2]:
            fail.add('register_picks', 'a sheet the revision is no longer on '
                     'was not reported')

        # And the executor, against a model that answers like Revit.
        kept = dict([(name, getattr(revisions, name)) for name in
                     ('FilteredElementCollector', 'Transaction', '_id',
                      '_id_list')])
        try:
            revisions.FilteredElementCollector = _SwapCollector
            revisions.Transaction = _SwapTransaction
            revisions._id = lambda value: _FakeId(int(value))
            revisions._id_list = lambda keys: [_FakeId(int(one))
                                               for one in keys]
            sheet_one = _SwapSheet(1, u'A101', [10])
            sheet_two = _SwapSheet(2, u'A102', [])
            sheet_three = _SwapSheet(3, u'A103', [11])
            moved = [_SwapCloud(101, 10, [1]), _SwapCloud(102, 10, [1, 2])]
            shared = _SwapCloud(103, 10, [2, 3])
            doc = _SwapDoc([sheet_one, sheet_two, sheet_three,
                            _SwapRevision(10), _SwapRevision(11),
                            _SwapRevision(20)], moved + [shared])
            changed, skipped, errors = revisions.swap_on_sheets(
                doc, {u'1': set([u'10']), u'2': set([u'10'])}, u'20')
            if errors:
                fail.add('register_picks', 'the swap reported errors against '
                         'a model that took everything: {0}'.format(errors))
            if sheet_one.additional != [20] or sheet_two.additional != []:
                fail.add('register_picks', 'the sheets\' own revisions came '
                         'out {0} and {1}, wanted [20] and []'.format(
                             sheet_one.additional, sheet_two.additional))
            if [cloud.RevisionId.Value for cloud in moved] != [20, 20] or \
                    shared.RevisionId.Value != 10:
                fail.add('register_picks', 'clouds came out {0} and the '
                         'shared one {1} - the two reaching only picked '
                         'sheets move, the one also on A103 stays'.format(
                             [cloud.RevisionId.Value for cloud in moved],
                             shared.RevisionId.Value))
            if [one.state for one in doc.transactions] != ['committed']:
                fail.add('register_picks', 'the swap was not one committed '
                         'transaction: {0}'.format(
                             [one.state for one in doc.transactions]))
            if changed != [(u'1', u'10')] or len(skipped) != 1:
                fail.add('register_picks', 'the swap reported changed {0}, '
                         'skipped {1}'.format(changed, skipped))
        finally:
            for name, value in kept.items():
                setattr(revisions, name, value)

    # -- the revision list
    if swapwin is not None:
        class _Rev(object):
            def __init__(self, key, sequence, issued=False, date=u'',
                         description=u''):
                self.element_key = key
                self.sequence = sequence
                self.issued = issued
                self.date = date
                self.description = description
        if swapwin.choosable(_Rev(30, 3, issued=True), [u'10'])[0] or \
                swapwin.choosable(_Rev(10, 1), [u'10'])[0] or \
                not swapwin.choosable(_Rev(10, 1), [u'10', u'11'])[0] or \
                not swapwin.choosable(_Rev(20, 2), [u'10'])[0]:
            fail.add('register_picks', 'the revision list offers an issued '
                     'revision, or the one every picked cell already is, or '
                     'refuses an ordinary one')
        if not swapwin.matches(_Rev(20, 4, date=u'2026-09-12',
                                    description=u'Stage 4 Issue'),
                               u'stage 09') or \
                swapwin.matches(_Rev(20, 4, description=u'Stage 4'),
                                u'tender') or \
                swapwin.matches(_Rev(20, 4, description=u'Stage 4'),
                                u'stage tender'):
            fail.add('register_picks', 'searching the revision list is not '
                     '"every word, anywhere"')

    # -- the size of the tool
    if ui is not None:
        for current, direction, wanted in (
                (1.0, 1, 1.1), (1.0, -1, 0.9), (0.7, 0, 1.0),
                (1.6, 1, 1.6), (0.6, -1, 0.6), (0.85, 1, 0.9),
                (0.85, -1, 0.8), (u'junk', 1, 1.1)):
            got = ui.zoom_step(current, direction)
            if abs(got - wanted) > 0.0001:
                fail.add('register_picks', 'stepping the size {0} from {1} '
                         'gave {2}, wanted {3}'.format(direction, current,
                                                       got, wanted))
        if ui.zoom_label(0.8) != u'80%' or ui.zoom_clamp(9) != \
                ui.ZOOM_STEPS[-1] or ui.zoom_clamp(u'x') != 1.0:
            fail.add('register_picks', 'the size label or its limits are '
                     'wrong')
    uisource = read(os.path.join(root, 'ps_ui.py'))
    zoom = uisource[uisource.find('class Zoom('):]
    zoom = zoom[:zoom.find('\n# =====')]
    if 'self.window.Content.LayoutTransform = ScaleTransform(' not in zoom:
        fail.add('register_picks', 'the size is not a LayoutTransform on the '
                 'window\'s content. A RenderTransform only draws smaller - '
                 'the layout still takes the full size and the edges are cut '
                 'off - so there is no more room to see more')
    if 'window.PreviewKeyDown += self._key' not in zoom or \
            "self.settings.set(self.key," not in zoom:
        fail.add('register_picks', 'Ctrl+minus/plus do nothing, or the size '
                 'is not kept')
    if 'self.zoom = ps_ui.Zoom(self.window, self.settings)' not in read(
            os.path.join(root, 'ps_window.py')):
        fail.add('register_picks', 'the main window has no - and +')
    for name in ('ZoomOutButton', 'ZoomResetButton', 'ZoomInButton',
                 'RegisterIsolateButton', 'RegisterChangeRevButton'):
        if 'x:Name="{0}"'.format(name) not in layout:
            fail.add('register_picks', 'no {0} in the window'.format(name))

    # -- the register itself
    header = view[view.find('    def _revision_header('):]
    header = header[:header.find('    def _filter_button(')]
    if 'sequence = Button()' not in header or \
            'sequence.Click += self._make_seq_click(revision.key)' \
            not in header:
        fail.add('register_picks', 'the sequence number is not a button of '
                 'its own. A click on a TextBlock falls through to the '
                 'heading, which includes every drawing carrying the '
                 'revision rather than picking it')
    style = view[view.find('CELL_STYLE = ('):]
    style = style[:style.find('\n\n')]
    if style.find('Binding p_{1}') < style.find('Binding sel}'):
        fail.add('register_picks', 'a picked cell is not styled last, so a '
                 'picked cell on the sheet\'s current revision, or on a '
                 'drawing left out, does not look picked')
    for needed, why in (
            ('self.table.Columns.Add(PICK_PREFIX + revision.key, String)',
             'no flag column to mark a picked cell on'),
            ("if self.isolated and not [key for key in self.isolated",
             'Isolate does not narrow the view'),
            ("self._cell_click(entry, self._column_under(source))",
             'a click on a revision cell does not pick it'),
            ("style.BasedOn = base",
             'a picked column\'s wash is not based on RegisterCell, so its '
             'cells lose their template and the muted rows'),
            ("self._click(self.isolate_button,",
             'the Isolate button is not wired'),
            ("self._click(self.change_button,",
             'the Change revision button is not wired'),
            ("self.isolated = []\n        self.clear_filters()",
             'Reset filters leaves the view isolated'),
            ("if key == Key.Escape and (self.picked_cells or "
             "self.picked_columns):",
             'Escape does not let go of what is picked'),
            ("result = ps_revisions.swap_on_sheets(doc, picks, target,",
             'Change revision does not go through swap_on_sheets')):
        if needed not in view:
            fail.add('register_picks', why)
    # Scoped to the method: the Revision Manager's hand-off has the same
    # line, and would answer for this one if it went missing.
    # From 1.42.0 Change is staged; Apply revisions is what writes, and it
    # is the one that must go through the external event.
    change = _method_body(view, 'apply_revisions')
    if 'if self.host._queue(job):' not in change or \
            'def job(uiapp):' not in change or \
            'self._stage(edit)' not in _method_body(view, 'change_revision'):
        fail.add('register_picks', 'Change revision does not go through the '
                 'external event. The Pro Sheets window is modeless, so it '
                 'is in no API context, and writing where it stands throws')
    clicked = view[view.find('    def _row_click('):]
    clicked = clicked[:clicked.find('    def _selected_keys(')]
    picked_branch = clicked[clicked.find('if not self._is_heading(entry):'):]
    picked_branch = picked_branch[:picked_branch.find('self.toggle_group(')]
    if 'args.Handled' in picked_branch:
        fail.add('register_picks', 'picking a cell swallows the click, so '
                 'the grid no longer selects the row - and the multi-row '
                 'tick goes with it')


# ==========================================================================
# rule 51 : adding a revision where it belongs; new revisions brought to the
#           eye; taking revisions off sheets
#
# Add asks where the revision goes first - washed orange, defaulting to last
# - and the one already there moves down a slot. The new row is green and in
# the middle of the grid. Back on the register, a new revision is on no
# sheet, so every revision is shown and the new ones washed green. Picked
# cells get a toolset: Change, and Remove - which deletes clouds, so it asks,
# and never deletes one that also reaches a sheet nobody picked.
# ==========================================================================

def rule_revision_add(root, fail):
    revisions = _module_under_stubs(root, 'ps_revisions', 'revision_add',
                                    fail)
    addwin = _module_under_stubs(root, 'ps_revaddwin', 'revision_add', fail)
    window = read(os.path.join(root, 'ps_revwin.py'))
    view = read(os.path.join(root, 'ps_regview.py'))
    layout = read(os.path.join(root, 'ProSheets.xaml'))
    adding = read(os.path.join(root, 'ProSheetsRevAdd.xaml'))
    addsource = read(os.path.join(root, 'ps_revaddwin.py'))

    # -- where a new revision goes
    if revisions is not None:
        live = [u'a', u'b', u'c']
        for order, position, wanted in (
                ([u'a', u'b', u'c'], 1, [u'n', u'a', u'b', u'c']),
                ([u'a', u'b', u'c'], 2, [u'a', u'n', u'b', u'c']),
                ([u'a', u'b', u'c'], 4, [u'a', u'b', u'c', u'n']),
                ([u'a', u'b', u'c'], None, [u'a', u'b', u'c', u'n']),
                ([u'a', u'b', u'c'], 0, [u'n', u'a', u'b', u'c']),
                # x is staged to go: it keeps its slot but is not counted
                ([u'a', u'x', u'b', u'c'], 2,
                 [u'a', u'x', u'n', u'b', u'c'])):
            got = revisions.insert_at(order, live, u'n', position)
            if got != wanted:
                fail.add('revision_add', 'a new revision at sequence {0} in '
                         '{1} came out {2}, wanted {3}'.format(
                             position, order, got, wanted))
        one = revisions.Entry(501, 501, 1, {'desc': u'Stage 3'})
        two = revisions.Entry(502, 502, 2, {'desc': u'Stage 4'})
        st = revisions.Staging([one, two])
        key = st.add(1, {'desc': u'Tender', 'issued': 1,
                         'issued_to': u'Client'}, {u'c1': u'note'})
        entry = st.entries[key]
        if st.staged_sequence(key) != 1 or st.staged_sequence(u'501') != 2 \
                or st.staged_sequence(u'502') != 3:
            fail.add('revision_add', 'a revision added at sequence 1 did not '
                     'push the others down a slot')
        if entry.fields.get('desc') != u'Tender' or \
                entry.fields.get('issued') is not True or \
                entry.fields.get('issued_to') != u'Client' or \
                entry.custom.get(u'c1') != u'note':
            fail.add('revision_add', 'what was filled in for the new '
                     'revision did not reach it: {0} / {1}'.format(
                         entry.fields, entry.custom))
        last = st.add()
        if st.order[-1] != last:
            fail.add('revision_add', 'a plain add no longer goes last')

    if addwin is not None:
        for text, count, wanted in ((u'2', 3, (True, 2)),
                                    (u'4', 3, (True, 4)),
                                    (u'5', 3, False), (u'0', 3, False),
                                    (u'x', 3, False), (u' 1 ', 3, (True, 1))):
            got = addwin.read_position(text, count)
            if (got if wanted is not False else got[0]) != wanted:
                fail.add('revision_add', 'sequence "{0}" of {1} read as '
                         '{2}'.format(text, count, got))
        rows = [(1, u'"A"'), (2, u'"B"'), (3, u'"C"')]
        if u'last' not in addwin.position_note(4, rows) or \
                u'"C" moves down to 4' not in addwin.position_note(3, rows) \
                or u'the 2 after it' not in addwin.position_note(1, rows):
            fail.add('revision_add', 'the note under the sequence does not '
                     'say what moves')
    if 'x:Name="SequenceCard"' not in adding or \
            'Background="{DynamicResource PickWashBrush}"' not in adding or \
            "ps_ui.set_text(self.box, u'{0}'.format(self.count + 1))" \
            not in addsource:
        fail.add('revision_add', 'the sequence is not washed orange to be '
                 'chosen first, or does not start at last')

    # -- the manager: dialog, sequence, green, centred
    add = window[window.find('    def _add(self, sender, args):'):]
    add = add[:add.find('    def _fresh_row_style(')]
    for needed, why in (
            ('answer = ps_revaddwin.ask(', 'Add does not ask first'),
            ("key = self.staging.add(answer['position'], answer['fields'],",
             'the sequence chosen is not where the revision goes'),
            ('self._centre_on(key)', 'the grid does not go to the new row'),
            ('self.grid.SelectedItems.Clear()',
             'the new row is left selected, which draws it blue, not '
             'green')):
        if needed not in add:
            fail.add('revision_add', why)
    if "self._put(row, 'fresh', u'1' if entry.is_new and entry.live" \
            not in window or \
            'self.grid.RowStyle = self._fresh_row_style()' not in window or \
            '<DataTrigger Binding="{{Binding fresh}}" Value="1">' \
            not in window:
        fail.add('revision_add', 'a new revision\'s row is not green')

    # -- the register after the manager
    written = view[view.find('    def _revisions_written('):]
    written = written[:written.find('    def new_set(')]
    if 'self.fresh_columns = set(fresh)' not in written or \
            'self.set_show_all_revisions(True, quiet=True)' not in written:
        fail.add('revision_add', 'coming back from the manager does not '
                 'show every revision and wash the new ones green')
    wash = view[view.find('    def _column_wash('):]
    wash = wash[:wash.find('    def _paint_picked_columns(')]
    if not 0 <= wash.find('self.picked_columns') < \
            wash.find('self.fresh_columns'):
        fail.add('revision_add', 'a new revision\'s green beats the orange of '
                 'a picked column')
    if 'self.fresh_columns = set()' not in \
            view[view.find('    def reload('):view.find(
                '    def _reset_revision_columns(')]:
        fail.add('revision_add', 'the green on new revisions never goes')
    if 'x:Name="RegisterAllRevsButton"' not in layout or \
            "self._click(self.all_revs_button," not in view:
        fail.add('revision_add', 'no Show all revisions button')

    # -- the picked-cell toolset, and Remove
    if 'x:Name="RegisterCellTools"' not in layout or \
            'x:Name="RegisterRemoveRevButton"' not in layout or \
            'ps_ui.set_visible(self.cell_tools, bool(count))' not in view or \
            "self._click(self.remove_button," not in view:
        fail.add('revision_add', 'the picked cells have no toolset, or it '
                 'does not come and go with them')
    # Remove is staged (1.42.0): Apply revisions asks, then writes.
    remove = _method_body(view, 'apply_revisions') + \
        _method_body(view, '_run_edit')
    for needed, why in (
            (u'Deletes the rev clouds from all associated views ',
             'Remove does not say it deletes the rev clouds'),
            ("if answer != 'primary':", 'Remove does not ask first'),
            ('result = ps_revisions.remove_on_sheets(doc, picks, sheets,',
             'Remove does not go through remove_on_sheets'),
            ('if self.host._queue(job):',
             'Remove does not go through the external event')):
        if needed not in remove:
            fail.add('revision_add', why)
    if 'self._stage(edit)' not in _method_body(view, 'remove_revision'):
        fail.add('revision_add', 'Remove writes at once instead of waiting '
                 'for Apply revisions')

    if revisions is not None:
        clouds = [(u'c1', u'10', set([u'1'])),
                  (u'c2', u'10', set([u'1', u'2'])),
                  (u'c3', u'10', set([u'2', u'3']))]
        got = revisions.plan_remove({u'1': set([u'10']), u'2': set([u'10'])},
                                    {u'1': set([u'10', u'11'])}, clouds,
                                    set())
        if got['additional'] != {u'1': set([u'11'])}:
            fail.add('revision_add',
                     'removing took {0} off sheet 1 by hand - wanted just '
                     'the picked revision gone, nothing put on'.format(
                         got['additional']))
        if sorted(got['clouds']) != [u'c1', u'c2']:
            fail.add('revision_add', 'clouds to delete: {0}. c3 also shows on '
                     'sheet 3, which was not picked - deleting it would take '
                     'the revision off that sheet too'.format(
                         sorted(got['clouds'])))
        got = revisions.plan_remove({u'1': set([u'30'])}, {}, [], set([u'30']))
        if got['changed'] or 'issued' not in got['skipped'][0][2]:
            fail.add('revision_add', 'an issued revision was taken off a sheet')

        kept = dict([(name, getattr(revisions, name)) for name in
                     ('FilteredElementCollector', 'Transaction', '_id',
                      '_id_list')])
        try:
            revisions.FilteredElementCollector = _SwapCollector
            revisions.Transaction = _SwapTransaction
            revisions._id = lambda value: _FakeId(int(value))
            revisions._id_list = lambda keys: [_FakeId(int(one))
                                               for one in keys]
            sheet_one = _SwapSheet(1, u'A101', [10, 11])
            sheet_two = _SwapSheet(2, u'A102', [])
            sheet_three = _SwapSheet(3, u'A103', [])
            going = [_SwapCloud(101, 10, [1]), _SwapCloud(102, 10, [1, 2])]
            shared = _SwapCloud(103, 10, [2, 3])
            doc = _SwapDoc([sheet_one, sheet_two, sheet_three,
                            _SwapRevision(10), _SwapRevision(11)],
                           going + [shared])
            removed, skipped, errors = revisions.remove_on_sheets(
                doc, {u'1': set([u'10']), u'2': set([u'10'])})
            if errors or sorted(getattr(doc, 'deleted', [])) != [101, 102]:
                fail.add('revision_add', 'Remove deleted {0} ({1}) - wanted '
                         'the two clouds reaching only picked sheets'.format(
                             sorted(getattr(doc, 'deleted', [])), errors))
            if shared.RevisionId.Value != 10 or 103 not in doc.elements:
                fail.add('revision_add', 'the cloud shared with A103 was '
                         'touched')
            if sheet_one.additional != [11]:
                fail.add('revision_add', 'A101\'s own revisions came out {0}, '
                         'wanted [11]'.format(sheet_one.additional))
            if [one.state for one in doc.transactions] != ['committed']:
                fail.add('revision_add', 'Remove was not one committed '
                         'transaction')
            if removed != [(u'1', u'10')] or len(skipped) != 1:
                fail.add('revision_add', 'Remove reported removed {0}, '
                         'skipped {1}'.format(removed, skipped))
        finally:
            for name, value in kept.items():
                setattr(revisions, name, value)


# ==========================================================================
# rule 52 : finding the clouds a sheet really shows; the revision tools on
#           the register; several revisions edited at once; the open sheet
#
# 1.40.0 refused nearly every change: RevisionCloud.GetSheetIds lists every
# sheet a cloud MAY show on, so a cloud in a parent view counted on the sheet
# of every dependent view, and was left as "shared". Now each sheet is looked
# inside - the sheet, then every view on it - for the clouds it really shows.
# A cloud that truly is on another sheet is asked about, not dead-ended.
# ==========================================================================

def _swap_patch(revisions):
    kept = dict([(name, getattr(revisions, name)) for name in
                 ('FilteredElementCollector', 'Transaction', '_id',
                  '_id_list')])
    revisions.FilteredElementCollector = _SwapCollector
    revisions.Transaction = _SwapTransaction
    revisions._id = lambda value: _FakeId(int(value))
    revisions._id_list = lambda keys: [_FakeId(int(one)) for one in keys]
    return kept


def _dependent_model(revisions):
    """Sheets 1, 2 and 3 each hold a dependent view (11, 21, 31) of one
    parent plan. The parent carries two clouds for revision 75: c501 in the
    zone sheet 1 shows, c502 in the zone sheet 2 shows. Revit's GetSheetIds
    says both MAY appear on all three. Sheet 1 also holds legend 99, which
    is on sheet 4 as well, with cloud c503 in it - truly on both."""
    sheets = [_SwapSheet(1, u'A101', [], [11, 99]),
              _SwapSheet(2, u'A102', [], [21]),
              _SwapSheet(3, u'A103', [], [31]),
              _SwapSheet(4, u'A104', [], [99])]
    clouds = [_SwapCloud(501, 75, [1, 2, 3]), _SwapCloud(502, 75, [1, 2, 3]),
              _SwapCloud(503, 75, [1, 4])]
    doc = _SwapDoc(sheets + [_SwapRevision(75), _SwapRevision(80)], clouds)
    doc.shows = {11: [501], 21: [502], 31: [], 99: [503]}
    return doc, sheets, clouds


def rule_revision_sheets(root, fail):
    revisions = _module_under_stubs(root, 'ps_revisions', 'revision_sheets',
                                    fail)
    winmod = _module_under_stubs(root, 'ps_revwin', 'revision_sheets', fail)
    addwin = _module_under_stubs(root, 'ps_revaddwin', 'revision_sheets', fail)
    window = read(os.path.join(root, 'ps_revwin.py'))
    view = read(os.path.join(root, 'ps_regview.py'))
    layout = read(os.path.join(root, 'ProSheets.xaml'))
    manager = read(os.path.join(root, 'ProSheetsRevisions.xaml'))

    if revisions is not None:
        # -- the 1.40.0 failure: change A101's revision 75
        kept = _swap_patch(revisions)
        try:
            doc, sheets, clouds = _dependent_model(revisions)
            report = {}
            changed, skipped, errors = revisions.swap_on_sheets(
                doc, {u'1': set([u'75'])}, u'80', None, False, report)
            if clouds[0].RevisionId.Value != 80:
                fail.add('revision_sheets', 'the cloud A101 really shows was '
                         'not changed - left as "also shows on sheets not '
                         'picked" because GetSheetIds lists every dependent '
                         'view\'s sheet. This is the 1.40.0 failure: look '
                         'inside each view on the sheet instead')
            if clouds[1].RevisionId.Value != 75:
                fail.add('revision_sheets', 'the cloud only A102 shows was '
                         'changed for A101')
            if clouds[2].RevisionId.Value != 75 or \
                    [one[2] for one in report.get('shared', [])] != [u'503'] \
                    or report['shared'][0][3] != [u'4']:
                fail.add('revision_sheets', 'the cloud in the legend on A101 '
                         'and A104 was changed without asking, or not '
                         'reported as shared: {0}'.format(
                             report.get('shared')))
            # -- asked, and told yes: the shared one goes too
            report = {}
            changed, skipped, errors = revisions.swap_on_sheets(
                doc, {u'1': set([u'75'])}, u'80', None, True, report)
            if clouds[2].RevisionId.Value != 80 or \
                    changed != [(u'1', u'75')] or errors:
                fail.add('revision_sheets', 'told to take the shared cloud '
                         'too, it was not: {0} {1}'.format(changed, errors))
            # -- Remove the same way
            doc, sheets, clouds = _dependent_model(revisions)
            removed, skipped, errors = revisions.remove_on_sheets(
                doc, {u'1': set([u'75'])}, None, False, {})
            if sorted(getattr(doc, 'deleted', [])) != [501]:
                fail.add('revision_sheets', 'Remove deleted {0} for A101 - '
                         'wanted only the cloud A101 shows'.format(
                             sorted(getattr(doc, 'deleted', []))))
            # -- a sheet that will not be looked into never throws
            class _Hostile(object):
                def __getattr__(self, name):
                    raise ValueError('no')
            if revisions.clouds_seen_on(doc, _Hostile(), set([u'75'])) != \
                    set():
                fail.add('revision_sheets', 'looking inside a broken sheet '
                         'threw or found something')
            # -- create the revision, then move the cells onto it
            doc, sheets, clouds = _dependent_model(revisions)
            kept_write = (revisions.write, revisions.revision_keys)

            def made(doc_in, plan):
                created = _SwapRevision(90)
                doc_in.elements[90] = created
                return 1, []
            revisions.write = made
            revisions.revision_keys = lambda doc_in: [
                u'{0}'.format(key) for key, one in doc_in.elements.items()
                if isinstance(one, _SwapRevision)]
            try:
                new, changed, skipped, errors = revisions.create_and_swap(
                    doc, None, {u'1': set([u'75'])})
                if new != u'90' or clouds[0].RevisionId.Value != 90:
                    fail.add('revision_sheets', 'Create new revision did not '
                             'put the new revision on the picked cell: new '
                             '{0}, cloud on {1}'.format(
                                 new, clouds[0].RevisionId.Value))
                revisions.write = lambda doc_in, plan: (0, [u'refused'])
                doc, sheets, clouds = _dependent_model(revisions)
                try:
                    new, changed, skipped, errors = \
                        revisions.create_and_swap(doc, None,
                                                  {u'1': set([u'75'])})
                except Exception as err:
                    new, errors = u'?', [u'threw: {0}'.format(err)]
                if new != u'' or clouds[0].RevisionId.Value != 75 or \
                        len(errors) < 2:
                    fail.add('revision_sheets', 'with no revision made, '
                             'Create still changed the sheets, or did not say '
                             'why: {0}'.format(errors))
                # Two revisions appeared - which is ours cannot be told, so
                # nothing on the sheets may move.

                def made_two(doc_in, plan):
                    doc_in.elements[90] = _SwapRevision(90)
                    doc_in.elements[91] = _SwapRevision(91)
                    return 1, []
                revisions.write = made_two
                doc, sheets, clouds = _dependent_model(revisions)
                try:
                    new, changed, skipped, errors = \
                        revisions.create_and_swap(doc, None,
                                                  {u'1': set([u'75'])})
                except Exception as err:
                    new, errors = u'?', [u'threw: {0}'.format(err)]
                if new != u'' or clouds[0].RevisionId.Value != 75:
                    fail.add('revision_sheets', 'with two new revisions and '
                             'no telling which is ours, Create still moved '
                             'the sheets onto {0}'.format(new))
            finally:
                revisions.write, revisions.revision_keys = kept_write
        finally:
            for name, value in kept.items():
                setattr(revisions, name, value)

        # -- several revisions at once, never the date
        one = revisions.Entry(501, 501, 1, {'desc': u'A'}, [u'A101'])
        two = revisions.Entry(502, 502, 2, {'desc': u'B', 'issued': True},
                              [u'A102'])
        three = revisions.Entry(503, 503, 3, {'desc': u'C'}, [u'A101'])
        st = revisions.Staging([one, two, three])
        changed, refusals = st.set_field_many([u'501', u'502', u'503'],
                                              'issued_to', u'Client')
        if changed != [u'501', u'503'] or not refusals or \
                st.entries[u'503'].fields['issued_to'] != u'Client':
            fail.add('revision_sheets', 'one value into several revisions '
                     'gave {0} / {1} - the issued one refuses for itself and '
                     'the rest still take it'.format(changed, refusals))
        changed, refusals = st.set_field_many([u'501', u'503'], 'date',
                                              u'01/01/27')
        if changed or st.entries[u'501'].fields['date'] == u'01/01/27':
            fail.add('revision_sheets', 'a date went onto several revisions '
                     'at once')
        # -- the sheet filter
        new = st.add()
        got = st.visible({}, None, u'A101')
        if got != [u'501', u'503', new] or \
                len(st.visible({}, None, None)) != 4:
            fail.add('revision_sheets', 'filtered to A101 the list showed '
                     '{0} - its revisions, plus any not yet applied'.format(
                         got))

        class _Sheet(object):
            SheetNumber = u'A101'

        class _Plan(object):
            pass
        if revisions.sheet_number_of(_Sheet()) != u'A101' or \
                revisions.sheet_number_of(_Plan()) is not None or \
                revisions.sheet_number_of(None) is not None:
            fail.add('revision_sheets', 'a sheet is not told from another '
                     'kind of view')

    if winmod is not None:
        for field, wanted in (('desc', True), ('issued_to', True),
                              ('issued', True), ('show', True),
                              ('x_c1', True), ('date', False),
                              ('seq', False), ('used', False),
                              ('series', False)):
            if winmod.together(field) != wanted:
                fail.add('revision_sheets', 'an edit to {0} {1} every '
                         'selected revision'.format(
                             field, u'does not go to' if wanted
                             else u'goes to'))
    if addwin is not None:
        if addwin.starting_position(71, 80) != 71 or \
                addwin.starting_position(95, 80) != 81 or \
                addwin.starting_position(None, 80) != 81 or \
                addwin.starting_position(0, 80) != 1:
            fail.add('revision_sheets', 'the Add window does not start where '
                     'it is told')

    # -- the manager
    press = _method_body(window, '_grid_press')
    for needed, where, why in (
            ('self.grid.PreviewMouseLeftButtonDown += self._grid_press',
             window, 'a press in a multi-selection is not seen'),
            ('self._multi = list(keys)', press,
             'the revisions selected together are not noted'),
            ('self.grid.BeginEdit()', press,
             'the press narrows the selection to one row before the edit'),
            ('others = self._others(key, field)',
             _method_body(window, '_cell_changed'),
             'an edit does not go to the other selected revisions'),
            ("others = self._others(key, u'x_' + column_id)",
             _method_body(window, '_custom_changed'),
             'an edit to an own column does not go to the others'),
            ('self.track_sheet(uidoc)', _method_body(window, '_idling'),
             'changing sheet in Revit is not noticed'),
            ("('RevSheetFilterButton', self._toggle_sheet_filter),", window,
             'the sheet filter button is not wired'),
            ('button.IsEnabled = on_sheet',
             _method_body(window, '_paint_sheet_button'),
             'the sheet filter is not greyed out off a sheet'),
            ('if focus:\n            self.focus(focus)', window,
             'the manager does not open on the revisions asked for'),
            ('modeless=True, focus=focus,', window,
             'the selected cloud\'s revision is not opened on')):
        if needed not in where:
            fail.add('revision_sheets', why)
    if 'x:Name="RevSheetFilterButton"' not in manager:
        fail.add('revision_sheets', 'no Filter revisions on current sheet '
                 'button')

    # -- the register
    for needed, where, why in (
            ('focus = ps_revisions.selected_revision_keys(uidoc)',
             _method_body(view, 'open_revision_manager'),
             'opened from the register, the manager ignores the selected '
             'cloud'),
            ('self.open_revision_manager(focus=sorted(keys))',
             _method_body(view, 'edit_revision'),
             'Edit revision does not open on the picked revisions'),
            ('position = (max(after) + 1) if after else None',
             _method_body(view, 'create_revision'),
             'Create new revision does not start just after the one picked'),
            ('new, errors = ps_revisions.create_only(doc, plan)',
             _method_body(view, 'create_revision'),
             'Create new revision does not make the revision'),
            ("self._stage({'kind': 'change', 'target': column, 'picks': "
             "chosen})", _method_body(view, '_created'),
             'Create new revision does not stage the picked cells onto it'),
            ('if self._ask_shared(mode, shared, summary):',
             _method_body(view, '_applied'),
             'clouds really on other sheets are not asked about'),
            ('if (sheet, old) not in finished])',
             _method_body(view, '_applied'),
             'the second pass does the finished cells again'),
            ('self._again(leftovers)', _method_body(view, '_applied'),
             'the shared clouds are never gone back for'),
            ('self._run_edit(doc, edit, sheets, True, rest)',
             _method_body(view, '_again'),
             'the second pass leaves the shared clouds out again'),
            ('result = ps_revisions.swap_on_sheets(doc, picks, target,\n'
             '                                                     sheets, '
             'include_shared,', _method_body(view, '_run_edit'),
             'a second Change pass cannot take the shared clouds'),
            ("self._click(self.create_button,", view,
             'Create new revision is not wired'),
            ("self._click(self.edit_button,", view,
             'Edit revision is not wired')):
        if needed not in where:
            fail.add('revision_sheets', why)
    for name in ('RegisterCreateRevButton', 'RegisterEditRevButton'):
        if 'x:Name="{0}"'.format(name) not in layout:
            fail.add('revision_sheets', 'no {0}'.format(name))


class _CarrySheet(_SwapSheet):
    """A sheet that also shows revisions drawn as clouds."""

    def __init__(self, key, number, additional, clouded=None):
        _SwapSheet.__init__(self, key, number, additional)
        self.clouded = [int(one) for one in (clouded or [])]

    def GetAllRevisionIds(self):
        return [_FakeId(one) for one in sorted(set(self.additional +
                                                   self.clouded))]


class _ToolStand(object):
    """Enough of RegisterView for its menu and pick logic."""

    def __init__(self, regview, selected=(), columns=(), cells=(),
                 isolated=(), used=()):
        self._regview = regview
        self.selected = set(selected)
        self.picked_columns = list(columns)
        self.picked_cells = set(cells)
        self.isolated = list(isolated)
        self.used_columns = [_ToolColumn(key) for key in used]
        self.calls = []

    def __getattr__(self, name):
        method = getattr(self._regview.RegisterView, name)
        return lambda *args, **kw: method(self, *args, **kw)

    def _selected_keys(self):
        return set(self.selected)

    def edit_revision_box(self, key):
        self.calls.append(('box', key))

    def open_revision_manager(self, focus=None):
        self.calls.append(('manager', focus))


class _ToolColumn(object):
    def __init__(self, key):
        self.key = key


def rule_register_tools(root, fail):
    """1.42.0: the register's sheet toolset, its right-click menu, the Edit
    revision window, the bottom tabs and the Views list's Project Browser
    columns."""
    register = _module_under_stubs(root, 'ps_register', 'register_tools',
                                   fail)
    revisions = _module_under_stubs(root, 'ps_revisions', 'register_tools',
                                    fail)
    regview = _module_under_stubs(root, 'ps_regview', 'register_tools', fail)
    model = _module_under_stubs(root, 'ps_model', 'register_tools', fail)
    view = read(os.path.join(root, 'ps_regview.py'))
    theme = read(os.path.join(root, 'Theme.xaml'))
    layout = read(os.path.join(root, 'ProSheets.xaml'))
    adding = read(os.path.join(root, 'ProSheetsRevAdd.xaml'))
    addsource = read(os.path.join(root, 'ps_revaddwin.py'))
    winsource = read(os.path.join(root, 'ps_window.py'))

    # -- the icons on the bottom tabs
    if register is not None:
        icons = getattr(register, 'TAB_ICONS', {})
        for label, wanted in ((u'All', 'all'), (u'ALL', 'all'),
                              (u'E - Electrical', 'electrical'),
                              (u'MECHANICAL SERVICES', 'mechanical'),
                              (u'Mechanical', 'mechanical'),
                              (u'Coordination', 'coordination'),
                              (u'Co-ordination', 'coordination'),
                              (u'Builderswork', 'builderswork'),
                              (u"Builder's Work", 'builderswork'),
                              (u'BWIC', 'builderswork'),
                              (u'Plumbing', None), (u'', None)):
            got = register.tab_icon(label)
            if got != (icons.get(wanted) if wanted else None):
                fail.add('register_tools', 'the "{0}" tab does not wear the '
                         '{1} icon'.format(label, wanted or 'no'))
        if len(set(icons.values())) != 5:
            fail.add('register_tools', 'the five tab icons are not five '
                     'different drawings')
    paint = _method_body(view, '_paint_tab_strip')
    if 'text.FontWeight = FontWeights.Bold\n' not in paint or \
            'FontWeights.Normal' in paint:
        fail.add('register_tools', 'the tab names are not bold on every tab')
    if 'icon = self._tab_icon(label)' not in \
            _method_body(view, '_build_tab_strip'):
        fail.add('register_tools', 'the tabs are built without their icons')
    for key in ('SheetTab', 'SheetTabOn'):
        start = theme.find('<Style x:Key="{0}" '.format(key))
        style = theme[start:theme.find('</Style>', start)] if start >= 0 \
            else u''
        if '<Setter Property="FontWeight" Value="Bold"/>' not in style or \
                '<Border.Effect>\n              <DropShadowEffect' \
                not in style or \
                '<Setter Property="FontSize" Value="13"/>' not in style:
            fail.add('register_tools', 'the {0} style is not bold, larger '
                     'and raised on a shadow'.format(key))

    # -- Assign revision to selected
    if revisions is not None:
        plan = revisions.plan_assign(
            [u'1', u'2', u'3'], u'75', {u'1': set([u'80']), u'2': set()},
            {u'1': set([u'80']), u'2': set(), u'3': set([u'75'])}, set())
        if plan['additional'] != {u'1': set([u'75', u'80']),
                                  u'2': set([u'75'])} or \
                plan['skipped'] != [(u'3', u'already carries it')]:
            fail.add('register_tools', 'Assign planned {0} / {1}: a sheet '
                     'must keep what was put on it by hand, and one already '
                     'carrying the revision is left'.format(
                         plan['additional'], plan['skipped']))
        plan = revisions.plan_assign([u'1'], u'75', {}, {}, set([u'75']))
        if plan['additional'] or plan['skipped'] != \
                [(u'1', revisions.SWAP_ISSUED)]:
            fail.add('register_tools', 'an issued revision was planned onto '
                     'a sheet - Revit locks it')
        kept = _swap_patch(revisions)
        try:
            sheets = [_CarrySheet(1, u'A101', [80]),
                      _CarrySheet(2, u'A102', []),
                      _CarrySheet(3, u'A103', [], [75])]
            doc = _SwapDoc(sheets + [_SwapRevision(75), _SwapRevision(80),
                                     _SwapRevision(85, issued=True)], [])
            done, skipped, errors = revisions.assign_to_sheets(
                doc, [u'1', u'2', u'3'], u'75')
            if sheets[0].additional != [75, 80] or \
                    sheets[1].additional != [75] or \
                    sheets[2].additional != [] or errors or \
                    sorted(done) != [u'1', u'2']:
                fail.add('register_tools', 'Assign wrote {0} {1} {2} '
                         '(done {3}, errors {4})'.format(
                             sheets[0].additional, sheets[1].additional,
                             sheets[2].additional, done, errors))
            if [one.state for one in doc.transactions] != ['committed']:
                fail.add('register_tools', 'Assign did not run in one '
                         'committed transaction')
            done, skipped, errors = revisions.assign_to_sheets(
                doc, [u'2'], u'85')
            if done or sheets[1].additional != [75] or \
                    len(doc.transactions) != 1:
                fail.add('register_tools', 'an issued revision was put on '
                         'a sheet, or a transaction opened for nothing')
        except Exception as err:
            fail.add('register_tools', 'Assign threw: {0}: {1}'.format(
                err.__class__.__name__, err))
        finally:
            for name, value in kept.items():
                setattr(revisions, name, value)

        # -- the Edit revision window's answers, in Revit's order
        one = revisions.Entry(501, 501, 1, {'desc': u'Old', 'issued': True})
        two = revisions.Entry(502, 502, 2, {'desc': u'Old', 'issued': False})
        st = revisions.Staging([one, two])
        # Issued named first on purpose: the window's order must not be
        # the order things are staged in.
        refused = st.edit(u'501', {'issued': False, 'desc': u'New'})
        if refused or one.fields.get('desc') != u'New' or \
                one.fields.get('issued') is not False:
            fail.add('register_tools', 'un-issuing and editing in one go was '
                     'refused: {0}'.format(refused))
        refused = st.edit(u'502', {'issued': True, 'desc': u'Final'})
        if refused or two.fields.get('desc') != u'Final' or \
                two.fields.get('issued') is not True:
            fail.add('register_tools', 'editing then issuing in one go was '
                     'refused - Issued went on before the rest: {0}'.format(
                         refused))
        refused = st.edit(u'502', {'desc': u'Again', 'issued': True})
        if not refused or two.fields.get('desc') != u'Final':
            fail.add('register_tools', 'an issued revision was edited')

    # -- the menu, the picks and where Edit goes
    if regview is not None:
        stand = _ToolStand(regview, selected=[u'1', u'2'])
        entries = stand.menu_entries()
        actions = [entry[1] for entry in entries if entry]
        # 1.55.0: Open sheets leads, Assign straight after.
        if actions[:2] != ['open_sheets', 'assign_revision'] or \
                entries[0][0] != u'Open sheets' or \
                u'2 selected sheets' not in entries[1][0] or \
                actions[-1] != 'open_revision_manager':
            fail.add('register_tools', 'right-click on highlighted sheets '
                     'does not offer Open sheets then Assign: {0}'.format(
                         actions))
        stand = _ToolStand(regview, columns=[u'r502'], used=[u'r501',
                                                              u'r502'])
        actions = [entry[1] for entry in stand.menu_entries() if entry]
        if 'edit_revision' not in actions or 'toggle_isolate' not in actions \
                or 'assign_revision' in actions:
            fail.add('register_tools', 'right-click on a revision does not '
                     'offer Edit revision and Isolate: {0}'.format(actions))
        stand = _ToolStand(regview, cells=[(u'1', u'r501')],
                           used=[u'r501'])
        actions = [entry[1] for entry in stand.menu_entries() if entry]
        for wanted in ('create_revision', 'change_revision',
                       'remove_revision', 'edit_revision'):
            if wanted not in actions:
                fail.add('register_tools', 'right-click on a revision cell '
                         'does not offer {0}'.format(wanted))
        for action in actions:
            if not hasattr(regview.RegisterView, action):
                fail.add('register_tools', 'the menu offers {0}, which the '
                         'register does not have'.format(action))
        stand = _ToolStand(regview, columns=[u'r502'],
                           cells=[(u'1', u'r501'), (u'2', u'r502')],
                           used=[u'r501', u'r502'])
        if stand._picked_revisions() != [u'501', u'502']:
            fail.add('register_tools', 'the picked revisions came out {0} - '
                     'a column and the cells, each once, in column '
                     'order'.format(stand._picked_revisions()))
        stand.edit_revision()
        if stand.calls != [('manager', [u'501', u'502'])]:
            fail.add('register_tools', 'Edit with two revisions picked did '
                     'not open the Revision Manager on them: {0}'.format(
                         stand.calls))
        stand = _ToolStand(regview, columns=[u'r502'], used=[u'r502'])
        stand.edit_revision()
        if stand.calls != [('box', u'502')]:
            fail.add('register_tools', 'Edit with one revision picked did '
                     'not open the Edit revision window: {0}'.format(
                         stand.calls))
    manager = _method_body(view, 'open_revision_manager')
    if manager.find('focus = self._picked_revisions()') < 0 or \
            manager.find('focus = self._picked_revisions()') > \
            manager.find('selected_revision_keys(uidoc)'):
        fail.add('register_tools', 'the Revision Manager does not open on '
                 'the revision picked in the register')
    box = _method_body(view, 'edit_revision_box')
    for needed, why in (
            ('ps_revaddwin.ask_edit(', 'Edit does not open the Edit '
             'revision window'),
            ("staging.edit(key, answer['fields'], answer['custom'])",
             "the window's answers are not staged"),
            ('self._write_revisions(plan)', 'Apply writes nothing')):
        if needed not in box:
            fail.add('register_tools', why)
    if 'def ask_edit(' not in addsource or "u'Apply'" not in addsource or \
            'x:Name="DialogSubtitle"' not in adding:
        fail.add('register_tools', 'the Add revision window has no edit '
                 'mode with Apply')
    for needed, why in (
            ('self.grid.SelectionChanged += self._rows_selected',
             'highlighting sheets does not show their toolset'),
            ('self.grid.PreviewMouseRightButtonDown += self._right_press',
             'a right-click does not pick what it lands on'),
            ('self.grid.PreviewMouseRightButtonUp += self._right_release',
             'a right-click opens no menu'),
            ('lambda sender, args: self.assign_revision())',
             'Assign revision to selected does nothing')):
        if needed not in view:
            fail.add('register_tools', why)
    if 'ps_ui.set_visible(self.sheet_tools, bool(keys))' not in \
            _method_body(view, '_paint_sheet_tools'):
        fail.add('register_tools', 'the sheet toolset does not follow the '
                 'highlighted sheets')
    release = _method_body(view, '_right_release')
    if 'menu.PlacementTarget = self.grid' not in release or \
            'menu.IsOpen = True' not in release:
        fail.add('register_tools', 'the right-click menu is not placed in '
                 'the window - one with no target opens nowhere')
    if 'x:Name="RegisterSheetTools" Visibility="Collapsed"' not in layout or \
            'x:Name="RegisterAssignRevButton"' not in layout:
        fail.add('register_tools', 'the sheet toolset is missing, or shows '
                 'with nothing highlighted')

    # -- the divider and the +
    columns = _method_body(view, '_build_columns')
    if 'self.grid.Columns.Add(self._divider_column())' not in columns or \
            'self.grid.FrozenColumnCount = len(self.IDENTITY) + 1' \
            not in columns:
        fail.add('register_tools', 'no dividing line before the revisions, '
                 'or it scrolls away with them')
    sync = _method_body(view, '_sync_revision_columns')
    if 'self.grid.Columns.Remove(self.plus_column)\n' \
            '                self.grid.Columns.Add(self.plus_column)' \
            not in sync:
        fail.add('register_tools', 'the + does not stay after the last '
                 'revision')
    if 'self.new_revision()' not in _method_body(view, '_plus_column') or \
            'self._write_revisions(plan)' not in \
            _method_body(view, 'new_revision'):
        fail.add('register_tools', 'the + does not make a revision')

    # -- Views: the Project Browser's columns, sorted its way
    if model is not None:
        for samples, wanted in (
                ([[u'Discipline', u'Sub-Discipline']], [u'Discipline',
                                                        u'Sub-Discipline']),
                ([[u'Discipline'], [u'Discipline', u'Sub-Discipline']],
                 [u'Discipline', u'Sub-Discipline']),
                ([[u'', u'Zone'], [u'Level', u'Zone']], [u'Level', u'Zone']),
                ([[u'A', u'B'], [u'A', u'X']], [u'A', u'B']),
                ([], [])):
            got = model.browser_levels(samples)
            if got != wanted:
                fail.add('register_tools', 'the browser folders read {0} '
                         'from {1}, wanted {2}'.format(got, samples, wanted))
        if model.browser_columns([u'Discipline', u'View Type']) != \
                [u'Discipline', u'View Type'] or \
                model.browser_columns([]) != [u'View Type']:
            fail.add('register_tools', 'the view type is not the column '
                     'after the browser folders')

        class _Param(object):
            def __init__(self, key, name):
                self.Id = _FakeId(key)
                self.Definition = type('D', (), {'Name': name})()

        class _View(object):
            Parameters = [_Param(-1005, u'Discipline'), _Param(77, u'Zone')]
        if model._parameter_name(None, _View(), _FakeId(-1005)) != \
                u'Discipline' or \
                model._parameter_name(None, _View(), _FakeId(77)) != u'Zone':
            fail.add('register_tools', 'a browser folder parameter is not '
                     'named from the view')
    window = _window_module(root, 'register_tools', fail)
    if window is not None:
        cls = window.ProSheetsWindow
        got = cls.starting_columns('views', [u'Series'],
                                   [u'Discipline', u'View Type'])
        if got != ['sel', 'name', u'p:Discipline', u'p:View Type', 'fname']:
            fail.add('register_tools', 'the Views list does not start with '
                     'the Project Browser columns: {0}'.format(got))

        class _Stand(object):
            MAX_SORT_LEVELS = cls.MAX_SORT_LEVELS
            _apply_default_sort = cls._apply_default_sort
            _apply_browser_sort = cls._apply_browser_sort

            def __init__(self, names):
                self.browser_names = names
                self.column_order = ['sel', 'name', 'fname']
                self.sort_stack = []

            def _is_views_mode(self):
                return True

            def series_column(self):
                return u'p:Series'

        stand = _Stand([u'Discipline', u'Sub-Discipline', u'View Type'])
        if not stand._apply_default_sort() or stand.sort_stack != [
                (u'p:Discipline', False), (u'p:Sub-Discipline', False),
                (u'p:View Type', False), ('name', False)] or \
                stand.column_order[-1] != 'fname' or \
                u'p:Discipline' not in stand.column_order:
            fail.add('register_tools', 'the Views list is not sorted by the '
                     'first browser folder, then the second: {0}'.format(
                         stand.sort_stack))
        stand = _Stand([])
        if stand._apply_default_sort() or stand.sort_stack:
            fail.add('register_tools', 'a Views list with no browser columns '
                     'took the sheet series sort')
    if 'ps_model.browser_folder_parameters(self.doc, self.rows)' not in \
            _method_body(winsource, '_read_model'):
        fail.add('register_tools', 'the browser organisation is never read')
    if "if mode == 'views' or getattr(self, '_ready', False):\n" \
            "                self.sort_stack = []\n" \
            "            self._apply_default_sort()" not in \
            _method_body(winsource, '_adopt_columns'):
        fail.add('register_tools', 'switching to Views does not sort it the '
                 'Project Browser way')


class _StageStand(object):
    """Enough of RegisterView to paint staged edits and undo them."""

    def __init__(self, regview, register, cells):
        self._regview = regview
        self.pending = register.PendingEdits()
        self._pending_flags = {}
        self._suspend = False
        self.rows_by_key = {}
        self._entries = {}
        for key, held in cells.items():
            row = register.RegisterRow(key, u'S-' + key, u'Sheet ' + key)
            row.cells = dict(held)
            self.rows_by_key[key] = row
            self._entries[key] = dict(held)
        self.said = []
        self.host = self
        self.show_mode = 'included'
        self.included = set()
        self.isolated = []
        self.shown_all = False

    def __getattr__(self, name):
        method = getattr(self._regview.RegisterView, name)
        return lambda *args, **kw: method(self, *args, **kw)

    def say(self, text):
        self.said.append(text)

    def _paint_pending_buttons(self):
        pass

    def _set_picked_cells(self, picked):
        pass

    def _labels(self, columns):
        return u', '.join(columns)

    def set_show(self, mode):
        self.shown_all = mode == 'all'
        self.show_mode = mode


def rule_register_staging(root, fail):
    """1.42.0: the register's sheet revision edits wait for Apply
    revisions, with Undo and Redo; isolating a revision off the set shows
    All sheets; the Add revision sequence box is tall enough to read."""
    register = _module_under_stubs(root, 'ps_register', 'register_staging',
                                   fail)
    regview = _module_under_stubs(root, 'ps_regview', 'register_staging',
                                  fail)
    view = read(os.path.join(root, 'ps_regview.py'))
    layout = read(os.path.join(root, 'ProSheets.xaml'))
    adding = read(os.path.join(root, 'ProSheetsRevAdd.xaml'))
    winsource = read(os.path.join(root, 'ps_window.py'))

    if register is not None:
        present = {u'1': set([u'r1']), u'2': set([u'r1', u'r2']),
                   u'3': set()}
        for edits, wanted, why in (
                ([{'kind': 'assign', 'target': u'r2',
                   'sheets': [u'1', u'3']}],
                 {(u'1', u'r2'): 'add', (u'3', u'r2'): 'add'},
                 'Assign does not show the revision going on'),
                ([{'kind': 'change', 'target': u'r3',
                   'picks': {u'2': [u'r1']}}],
                 {(u'2', u'r1'): 'del', (u'2', u'r3'): 'add'},
                 'Change does not show one revision off and one on'),
                ([{'kind': 'remove', 'picks': {u'2': [u'r1', u'r2']}}],
                 {(u'2', u'r1'): 'del', (u'2', u'r2'): 'del'},
                 'Remove does not show the revisions coming off'),
                ([{'kind': 'assign', 'target': u'r2', 'sheets': [u'1']},
                  {'kind': 'remove', 'picks': {u'1': [u'r2']}}],
                 {}, 'assigned then removed still shows as a change'),
                ([{'kind': 'assign', 'target': u'r2', 'sheets': [u'3']},
                  {'kind': 'change', 'target': u'r4',
                   'picks': {u'3': [u'r2']}}],
                 {(u'3', u'r4'): 'add'},
                 'a staged cell changed again is shown wrong'),
                ([], {}, 'nothing staged still flags cells')):
            got = register.pending_flags(present, edits)
            if got != wanted:
                fail.add('register_staging', '{0}: {1}'.format(why, got))
        if register.pending_cells({'kind': 'change', 'target': u'r1',
                                   'picks': {u'1': [u'r2', u'r3'],
                                             u'2': [u'r2']}}) != 3:
            fail.add('register_staging', 'a change is not counted by cell')

        log = register.PendingEdits()
        one = {'kind': 'assign', 'target': u'r1', 'sheets': [u'1']}
        two = {'kind': 'remove', 'picks': {u'2': [u'r2']}}
        log.push(one)
        log.push(two)
        if log.undo() is not two or log.edits != [one] or \
                log.undone != [two]:
            fail.add('register_staging', 'Undo does not take back the last '
                     'edit')
        if log.redo() is not two or log.edits != [one, two]:
            fail.add('register_staging', 'Redo does not bring it back')
        log.undo()
        log.push({'kind': 'remove', 'picks': {u'1': [u'r1']}})
        if log.undone or log.redo() is not None:
            fail.add('register_staging', 'after a new edit, Redo still '
                     'brings back what was undone before it')
        log = register.PendingEdits()
        log.push({'kind': 'assign', 'target': u'r9', 'sheets': [u'1']})
        log.push({'kind': 'assign', 'target': u'r1',
                  'sheets': [u'1', u'gone']})
        log.push({'kind': 'change', 'target': u'r1',
                  'picks': {u'1': [u'r9'], u'2': [u'r2']}})
        dropped = log.prune([u'r1', u'r2'], [u'1', u'2'])
        if dropped != 1 or log.edits[0]['sheets'] != [u'1'] or \
                log.edits[1]['picks'] != {u'2': [u'r2']}:
            fail.add('register_staging', 'after a read, staged edits naming '
                     'a revision or sheet no longer in the model are kept: '
                     '{0}'.format(log.edits))
        got = register.outside_set(
            [u'1', u'2', u'3'], [u'r1'], set([u'1']),
            lambda sheet, column: sheet in (u'1', u'2'))
        if got != [u'2']:
            fail.add('register_staging', 'the sheets an isolated revision '
                     'has outside the set came out {0}'.format(got))

    if register is not None and regview is not None:
        stand = _StageStand(regview, register,
                            {u'1': {u'r1': u'P01'}, u'2': {}})
        stand.pending.push({'kind': 'change', 'target': u'r2',
                            'picks': {u'1': [u'r1']}})
        stand._paint_pending()
        entry = stand._entries[u'1']
        if entry.get(u'r2') != u'+' or entry.get(u's_r2') != 'add' or \
                entry.get(u's_r1') != 'del' or entry.get(u'r1') != u'P01':
            fail.add('register_staging', 'a staged change is not painted: '
                     '{0}'.format(entry))
        if stand._filled(u'1', u'r1') or not stand._filled(u'1', u'r2'):
            fail.add('register_staging', 'picking does not follow what is '
                     'staged - a cell staged off can still be picked')
        stand.undo()
        if entry.get(u'r2') != u'' or entry.get(u's_r2') != u'' or \
                entry.get(u's_r1') != u'':
            fail.add('register_staging', 'Undo leaves the cells painted: '
                     '{0}'.format(entry))
        stand.redo()
        if entry.get(u'r2') != u'+':
            fail.add('register_staging', 'Redo does not paint it again')

        stand = _StageStand(regview, register,
                            {u'1': {u'r1': u'P01'}, u'2': {u'r1': u'C01'}})
        stand.included = set([u'1'])
        stand.isolated = [u'r1']
        if stand._reveal_isolated() != 1 or not stand.shown_all:
            fail.add('register_staging', 'isolating a revision on a sheet '
                     'outside the set does not switch to All sheets')
        stand = _StageStand(regview, register, {u'1': {u'r1': u'P01'}})
        stand.included = set([u'1'])
        stand.isolated = [u'r1']
        if stand._reveal_isolated() or stand.shown_all:
            fail.add('register_staging', 'All sheets was switched on with '
                     'every sheet already in the set')

    for name, needed, why in (
            ('change_revision', 'self._stage(edit)',
             'Change writes at once'),
            ('assign_revision', "self._stage({'kind': 'assign',",
             'Assign writes at once'),
            ('apply_revisions', 'results = [self._run_edit(doc, edit, '
             'sheets, False)\n                       for edit in others]',
             'Apply does not write the edits in the order made'),
            ('_key_down', 'if key in (Key.Z, Key.Y) and not self._typing():',
             'Ctrl+Z / Ctrl+Y do nothing'),
            ('_key_down', 'if key == Key.Z:\n                self.undo()',
             'Ctrl+Z does not undo'),
            ('_typing', 'isinstance(Keyboard.FocusedElement, TextBox)',
             'Ctrl+Z is taken from the search box'),
            ('_fill', 'self._paint_pending()',
             'a new tab forgets to show what is staged'),
            ('reload', 'self.pending.prune(known, set(self.rows_by_key),',
             'a read keeps edits on revisions that have gone'),
            ('_on_sorting', 'revealed = self._reveal_isolated()',
             'a heading click does not look outside the set'),
            ('toggle_isolate', 'if not self._reveal_isolated():',
             'Isolate does not look outside the set')):
        if needed not in _method_body(view, name):
            fail.add('register_staging', why)
    for needed, why in (
            ('Value="Strikethrough"', 'a cell staged off is not struck '
             'through'),
            ('<DataTrigger Binding="{{Binding s_{1}}}" Value="add">',
             'a cell staged on is not green'),
            ('self.table.Columns.Add(PENDING_PREFIX + revision.key, String)',
             'the table has no staged flag per revision')):
        if needed not in view:
            fail.add('register_staging', why)
    for name in ('RegisterUndoButton', 'RegisterRedoButton',
                 'RegisterApplyRevsButton', 'RegisterDiscardRevsButton'):
        if 'x:Name="{0}"'.format(name) not in layout:
            fail.add('register_staging', '{0} is missing'.format(name))
    if layout.find('x:Name="RegisterUndoButton"') > \
            layout.find('x:Name="RegisterAddToExport"'):
        fail.add('register_staging', 'Undo is not at the top left')
    if 'if not self.register.can_close():' not in \
            _method_body(winsource, 'close'):
        fail.add('register_staging', 'closing throws staged changes away '
                 'without asking')
    found = re.search(r'x:Name="SequenceBox"[^>]*?\bHeight="(\d+)"', adding)
    if not found or int(found.group(1)) < 40:
        fail.add('register_staging', 'the Add revision sequence box is too '
                 'short for its 18pt number - the digits are cropped')


def rule_register_tidp(root, fail):
    """1.44.0: the TIDP register - the Revision Manager's Issue Status and
    Issued To / Method columns, the scale and status parameters, and Apply
    and Discard at the bottom right of the register."""
    data = _module_under_stubs(root, 'ps_revdata', 'register_tidp', fail)
    revisions = _module_under_stubs(root, 'ps_revisions', 'register_tidp',
                                    fail)
    register = _module_under_stubs(root, 'ps_register', 'register_tidp',
                                   fail)
    export = _module_under_stubs(root, 'ps_regexport', 'register_tidp', fail)
    winmod = _module_under_stubs(root, 'ps_revwin', 'register_tidp', fail)
    config = _module_under_stubs(root, 'ps_config', 'register_tidp', fail)
    layout = read(os.path.join(root, 'ProSheets.xaml'))
    setup = read(os.path.join(root, 'ProSheetsSetup.xaml'))
    setupsource = read(os.path.join(root, 'ps_setupwin.py'))
    view = read(os.path.join(root, 'ps_regview.py'))
    colwin = read(os.path.join(root, 'ps_revcolwin.py'))
    adding = read(os.path.join(root, 'ProSheetsRevColumn.xaml'))

    if data is not None:
        # -- the grouped columns, stored and read back
        columns = data.default_columns()
        groups = [(one.id, one.group, one.kind) for one in columns]
        if groups != [(u'notes', u'', 'text'),
                      (u'status', data.STATUS, 'text'),
                      (u'it1', data.ISSUED_TO, 'yesno'),
                      (u'it2', data.ISSUED_TO, 'yesno'),
                      (u'it3', data.ISSUED_TO, 'yesno'),
                      (u'm1', data.METHOD, 'yesno'),
                      (u'm2', data.METHOD, 'yesno')]:
            fail.add('register_tidp', 'the default columns are {0}'.format(
                groups))
        back = data.decode_columns(data.encode_columns(columns))
        if back is None or [(one.id, one.group) for one in back] != \
                [(one.id, one.group) for one in columns]:
            fail.add('register_tidp', 'a column\'s group is lost when '
                     'stored and read back')
        old = u'v1\nnotes\tRevision notes\ttext\t\t\t'
        read_old = data.decode_columns(old)
        if read_old is None or [one.id for one in read_old] != \
                [one.id for one in columns]:
            fail.add('register_tidp', 'a model stored before 1.44.0 does not '
                     'gain the Issue Status, Issued To and Method columns')
        taken = data.decode_columns(u'v1\nc1\tIssued To 1\ttext\t\t\t')
        if taken is None or [one.name for one in taken].count(
                u'Issued To 1') != 1:
            fail.add('register_tidp', 'a default was added over a column '
                     'the model already has by that name')
        if data.Column(u'x', u'X', 'text', group=data.METHOD).kind != \
                'yesno':
            fail.add('register_tidp', 'a Method column is not Yes/No')
        order = [one.id for one in data.group_order(
            [data.Column(u'm9', u'M', group=data.METHOD),
             data.Column(u'a', u'A'),
             data.Column(u'i9', u'I', group=data.ISSUED_TO),
             data.Column(u's', u'S', group=data.STATUS)])]
        if order != [u'a', u's', u'i9', u'm9']:
            fail.add('register_tidp', 'columns laid out {0} - plain, Issue '
                     'Status, Issued To, Method'.format(order))
        rows = data.issue_rows(columns, {
            u'r1': {u'it1': u'1', u'm2': u'1'},
            u'r2': {u'it1': u'0', u'it3': u'1', u'it2': u'0'}},
            [u'r1', u'r2'])
        if rows != [(u'Issued To 1', data.ISSUED_TO, [True, False]),
                    (u'Issued To 3', data.ISSUED_TO, [False, True]),
                    (u'Issued Method 2', data.METHOD, [True, False])]:
            fail.add('register_tidp', 'the Issued to rows came out {0} - '
                     'Issued To then Method, a column ticked nowhere left '
                     'off'.format(rows))

    if revisions is not None and data is not None:
        st = revisions.Staging([
            revisions.Entry(501, 501, 1, {'desc': u'A'}, uid=u'u1',
                            custom={u'status': u'S2'}),
            revisions.Entry(502, 502, 2, {'desc': u'B'}, uid=u'u2')])
        filled = st.fill_statuses({u'501': u'S4', u'502': u'S3'})
        entry = st.entries[u'502']
        if filled != [u'502'] or entry.custom.get(u'status') != u'S3' or \
                st.entries[u'501'].custom.get(u'status') != u'S2':
            fail.add('register_tidp', 'Issue Status from the sheets '
                     'overwrote a stored one, or did not fill an empty one')
        if u'x_status' not in st.changed(u'502'):
            fail.add('register_tidp', 'a status filled from the sheets is not '
                     'staged, so Apply would never keep it')
        if revisions.common_status([u'S3', u'', u'S4', u'S4']) != u'S4' or \
                revisions.common_status([u'S3', u'S4']) != u'S3' or \
                revisions.common_status([]) != u'':
            fail.add('register_tidp', 'the most common sheet status is '
                     'worked out wrong')
        ok, made = st.add_column(u'Courier', 'text', group=data.ISSUED_TO)
        if not ok or st.column(made).kind != 'yesno' or \
                st.column(made).group != data.ISSUED_TO:
            fail.add('register_tidp', 'a column added to Issued To is not a '
                     'Yes/No member of it')
        ok, _why = st.update_column(made, u'Courier', group=data.METHOD)
        if not ok or st.column(made).group != data.METHOD:
            fail.add('register_tidp', 'a Yes/No column cannot move to '
                     'Method')
        ok, _why = st.update_column(u'notes', u'Revision notes',
                                    group=data.METHOD)
        if ok:
            fail.add('register_tidp', 'a text column joined Method')

    if register is not None:
        class _El(object):
            def __init__(self, values):
                self.values = values
        saved = register.ps_model.param_text
        register.ps_model.param_text = \
            lambda element, name: element.values.get(name, u'')
        try:
            for sheet, block, wanted in (
                    ({u'S': u'1:50'}, {u'S': u'1:100'}, u'1:50'),
                    ({}, {u'S': u'1:100'}, u'1:100'),
                    ({}, {}, u'1:200')):
                got = register.scale_text(_El(sheet), _El(block), u'S',
                                          u'1:200')
                if got != wanted:
                    fail.add('register_tidp', 'the scale came out {0!r}, '
                             'wanted {1!r} - sheet, then title block, then '
                             'Revit'.format(got, wanted))
            if register.scale_text(_El({u'S': u'X'}), None, u'',
                                   u'1:200') != u'1:200':
                fail.add('register_tidp', 'Revit\'s own scale is not used '
                         'when the parameter method is off')
        finally:
            register.ps_model.param_text = saved

    if export is not None and register is not None:
        info = export.Info()
        info.revision_columns = export.ps_revdata.default_columns()
        one = register.RevisionColumn(1, 1)
        two = register.RevisionColumn(2, 2)
        one.uid, two.uid = u'a', u'b'
        info.revision_values = {u'a': {u'status': u'S2'}}
        rows = []
        for key, status, carried in ((1, u'S4', two.key), (2, u'S4', two.key),
                                     (3, u'S3', two.key)):
            made = register.RegisterRow(key)
            made.status = status
            made.cells = {carried: u'P1'}
            rows.append(made)
        got = export.issue_statuses([one, two], rows, info)
        if got != {one.key: u'S2', two.key: u'S4'}:
            fail.add('register_tidp', 'each issue\'s status came out {0} - '
                     'the stored one first, then most of its drawings'
                     .format(got))
        for name, members, wanted in (
                (u'Electrical', [], u'Electrical'),
                (u'Register', [], u'')):
            if export.discipline_heading(name, members) != wanted:
                fail.add('register_tidp', 'the discipline line for "{0}" '
                         'is wrong'.format(name))

    if winmod is not None:
        groups = {u'x_a': u'i', u'x_b': u'i', u'x_c': u'm'}
        got = winmod.keep_groups([u'desc', u'x_a', u'x_c', u'date', u'x_b'],
                                 lambda field: groups.get(field, u''))
        if got != [u'desc', u'x_a', u'x_b', u'x_c', u'date']:
            fail.add('register_tidp', 'a dragged order split a group: '
                     '{0}'.format(got))
        # 1.45.0: one merged band per run of side-by-side columns of a
        # kind - Standard, Custom, Issue Status, Issued To, Issued Method -
        # the + column leaving a gap.
        kinds = {u'seq': u's', u'desc': u's', u'x_n': u'c', u'x_a': u'i',
                 u'x_b': u'i', u'x_c': u'm'}
        runs = winmod.band_runs(
            [(u'seq', 50), (u'desc', 100), (u'x_n', 80), (u'x_a', 40),
             (u'x_b', 40), (u'x_c', 60), (u'plus', 44)],
            lambda field: kinds.get(field, u''))
        if runs != [(u's', 0.0, 150), (u'c', 150.0, 80), (u'i', 230.0, 80),
                    (u'm', 310.0, 60)]:
            fail.add('register_tidp', 'the bands over the headings came out '
                     '{0} - one per kind, merged across its columns'
                     .format(runs))
        if len(set([brush for _k, _n, brush, _a in winmod.BANDS])) != 5 or \
                [name for _k, name, _b, _a in winmod.BANDS] != [
                    u'Standard', u'Custom', u'Issue Status', u'Issued To',
                    u'Issued Method']:
            fail.add('register_tidp', 'the five bands are not five colours: '
                     'Standard, Custom, Issue Status, Issued To, Issued '
                     'Method')
        if revisions is not None and data is not None:
            class _BandStand(object):
                staging = revisions.Staging(
                    [], columns=data.default_columns())
            got = [winmod.RevisionManager._band_of(_BandStand(), field)
                   for field in (u'desc', u'used', u'x_notes', u'x_status',
                                 u'x_it1', u'x_m1', u'plus')]
            if got != [u'standard', u'standard', u'custom', data.STATUS,
                       data.ISSUED_TO, data.METHOD, u'']:
                fail.add('register_tidp', 'columns sit under the wrong '
                         'bands: {0}'.format(got))
        # 1.46.0: as wide as the columns need, capped at the screen.
        ui = winmod.ps_ui
        for needed, area, minimum, wanted in ((1500, 1920, 900, 1500.0),
                                              (2600, 1920, 900, 1896.0),
                                              (700, 1920, 900, 900.0)):
            got = ui.snug_width(needed, area, minimum)
            if got != wanted:
                fail.add('register_tidp', 'a window needing {0} on a {1} '
                         'screen opens {2} wide, wanted {3}'.format(
                             needed, area, got, wanted))
        if winmod.description_width([u'Stage 3']) != winmod.DESCRIPTION_MIN \
                or winmod.description_width([u'x' * 200]) != \
                winmod.DESCRIPTION_MAX or \
                winmod.needed_width(1000, 300, 250) != 1550.0:
            fail.add('register_tidp', 'the width the manager wants is worked '
                     'out wrong')
        fit = _method_body(read(os.path.join(root, 'ps_revwin.py')),
                           '_fit_window')
        if 'finally:' not in fit or 'self.window.Opacity = 1' not in \
                fit[fit.find('finally:'):]:
            fail.add('register_tidp', 'the manager opens hidden and may stay '
                     'hidden - it must be shown whatever the sizing does')
    if winmod is not None:
        ui = winmod.ps_ui
        top, height, saved = ui.full_height((0, 10, 1920, 1030), 200, 720)
        back = ui.full_height((0, 10, 1920, 1030), top, height, saved)
        if (top, height) != (10.0, 1030.0) or saved != (200.0, 720.0) or \
                back != (200.0, 720.0, None):
            fail.add('register_tidp', 'a double-click on the bottom bar does '
                     'not stretch the window to the screen\'s height and '
                     'back: {0} {1}'.format((top, height, saved), back))
    revsource = read(os.path.join(root, 'ps_revwin.py'))
    for needed, why in (
            ('footer.MouseLeftButtonDown += self._footer_click',
             'a double-click on the bottom bar does nothing'),
            ('if self._ancestor(args.OriginalSource, Button) is not None:',
             'a double-click on Apply or Cancel stretches the window'),
            ('self.window.ContentRendered += self._fit_window',
             'the manager opens at its old size, not its columns\' width'),
            ('self.grid.FrozenColumnCount = 1',
             'nothing stays put when the manager has to scroll sideways'),
            ('self.grid.LayoutUpdated += self._paint_bands',
             'the bands do not follow the columns'),
            ('if signature == self._band_sig:',
             'the bands are redrawn on every layout pass')):
        if needed not in revsource:
            fail.add('register_tidp', why)
    if "NO_GROUP = u'Custom'" not in colwin:
        fail.add('register_tidp', 'a new column is not offered as Custom, '
                 'Issued To or Issued Method')


    if config is not None:
        settings = config.Settings.__new__(config.Settings)
        settings.store = dict(config.SETTINGS_DEFAULTS)
        settings.store.update({'settings_version': '4',
                               'reg_title': config.RD9_TITLE,
                               'reg_legend': u'\t'.join(config.RD9_LEGEND),
                               'reg_snapshot': u'Asite Snapshot'})
        settings.migrate()
        if settings.store['reg_title'] != config.REG_TITLE or \
                settings.store['reg_snapshot'] != u'Current Rev' or \
                settings.store['reg_legend'] != \
                u'\t'.join(config.REG_LEGEND):
            fail.add('register_tidp', 'an untouched RD9 default was not '
                     'moved to the TIDP form')
        settings.store.update({'settings_version': '4',
                               'reg_title': u'Our register'})
        settings.migrate()
        if settings.store['reg_title'] != u'Our register':
            fail.add('register_tidp', 'a title somebody typed was replaced')
        for key, wanted in (('reg_status_param', u'BGL_Sheet Status'),
                            ('reg_scale_param',
                             u'BGL_Title Block Scale Text'),
                            ('reg_scale_mode', config.SCALE_PARAMETER)):
            if config.SETTINGS_DEFAULTS.get(key) != wanted:
                fail.add('register_tidp', '{0} does not default to {1}'
                         .format(key, wanted))

    # -- 1.46.0: the All tab ticked into the export
    if register is not None and export is not None:
        skip = set()
        if register.tab_ticked(register.ALL_TAB, skip) or \
                not register.tab_ticked(u'Elec', skip):
            fail.add('register_tidp', 'All should start unticked and a '
                     'discipline ticked')
        skip = register.tick_tab(register.ALL_TAB, True, skip)
        skip = register.tick_tab(u'Elec', False, skip)
        if not register.tab_ticked(register.ALL_TAB, skip) or \
                register.tab_ticked(u'Elec', skip) or \
                not register.tab_ticked(u'Mech', skip):
            fail.add('register_tidp', 'ticking All or unticking a '
                     'discipline is not kept: {0}'.format(sorted(skip)))
        if register.tab_ticked(register.ALL_TAB,
                               register.tick_tab(register.ALL_TAB, False,
                                                 skip)):
            fail.add('register_tidp', 'All cannot be unticked again')

        made = []
        for key, disc, series in ((1, u'Elec', u'1'), (2, u'Elec', u'2'),
                                  (3, u'Mech', u'1')):
            row = register.RegisterRow(key, u'D-{0}'.format(key))
            row.discipline, row.series = disc, series
            made.append(row)
        names = [name for name, _rows in
                 export.worksheets(made, set([register.ALL_INCLUDED]))]
        if names != [register.ALL_TAB, u'Elec', u'Mech']:
            fail.add('register_tidp', 'with All ticked the worksheets are '
                     '{0} - All first, then each discipline'.format(names))
        if [name for name, _rows in export.worksheets(made, set())] != \
                [u'Elec', u'Mech']:
            fail.add('register_tidp', 'an All worksheet appears unticked')
        info = export.Info()
        info.series_param = u'Series'
        parts = export.sections(register.ALL_TAB, made, info)
        if [heading for heading, _groups in parts] != [u'Elec', u'Mech'] or \
                [len(groups) for _heading, groups in parts] != [2, 1]:
            fail.add('register_tidp', 'the All worksheet is not one section '
                     'per discipline, its series kept: {0}'.format(
                         [(h, len(g)) for h, g in parts]))
        info.skip = set([register.ALL_INCLUDED])
        book = export.build([], made, info)
        first = book.sheets[0] if book.sheets else None
        if first is None:
            fail.add('register_tidp', 'no workbook with All ticked')
        else:
            texts = [value for (row, col), (value, _s, _n) in
                     sorted(first.cells.items()) if col == 1 and value]
            for wanted in (u'Elec', u'D-1', u'D-2', u'Mech', u'D-3'):
                if wanted not in texts:
                    fail.add('register_tidp', 'the All worksheet is missing '
                             '{0}: {1}'.format(wanted, texts))
                    break
            else:
                if texts.index(u'Mech') < texts.index(u'D-2'):
                    fail.add('register_tidp', 'the All worksheet does not '
                             'keep each discipline under its own heading')
    if 'check.IsChecked = ps_register.tab_ticked(label,' not in view or \
            'label != ps_register.ALL_TAB:' in _method_body(
                view, '_build_tab_strip') or \
            'self.skip_tabs = ps_register.tick_tab(label, wanted,' not in view:
        fail.add('register_tidp', 'the All tab has no tick, or it is not '
                 'kept')

    # -- 1.46.0: clouds in views on no sheet, and Find clouds on views
    if revisions is not None:
        drawn = [(u'3', u'901', u'40'), (u'3', u'902', u'40'),
                 (u'3', u'903', u'41'), (u'4', u'904', u'50')]
        by_view = revisions.clouds_by_view(drawn)
        if by_view != {u'3': {u'40': [u'901', u'902'], u'41': [u'903']},
                       u'4': {u'50': [u'904']}}:
            fail.add('register_tidp', 'clouds by view came out {0}'.format(
                by_view))
        three = revisions.Entry(3, 3, 1, {'desc': u'DRAINAGE'}, clouds=3)
        three.cloud_views = by_view[u'3']
        three.off_views = [(u'40', u'Level 1 working', 2)]
        four = revisions.Entry(4, 4, 2, {'desc': u'B'}, clouds=1)
        four.cloud_views = by_view[u'4']
        if three.unplaced != 2 or four.unplaced != 0:
            fail.add('register_tidp', 'clouds off sheets counted {0} and '
                     '{1}, wanted 2 and 0'.format(three.unplaced,
                                                  four.unplaced))
        st = revisions.Staging([three, four])
        used = st.in_use([u'3'])
        if not used or used[0][4] != 2:
            fail.add('register_tidp', 'Delete is not told how many clouds '
                     'are in views on no sheet: {0}'.format(used))
        views = revisions.views_to_open([three, four])
        if views != {u'40': [u'901', u'902'], u'41': [u'903'],
                     u'50': [u'904']}:
            fail.add('register_tidp', 'the views to open came out {0}'
                     .format(views))
        if u'2 views opened, 3 clouds isolated' not in \
                revisions.clouds_report(2, 3, []):
            fail.add('register_tidp', 'Find clouds on views does not say '
                     'what it did')

        class _View(object):
            def __init__(self, key):
                self.Id = _FakeId(key)
                self.Name = u'View {0}'.format(key)
                self.isolated = None

            def IsTemporaryHideIsolateActive(self):
                return False

            def IsolateElementsTemporary(self, ids):
                self.isolated = sorted([int(one.Value) for one in ids])

        class _UiDoc(object):
            def __init__(self, doc):
                self.Document = doc
                self.opened = []

            def _set(self, view):
                self.opened.append(int(view.Id.Value))
            ActiveView = property(lambda self: None, _set)

        kept = _swap_patch(revisions)
        try:
            a, b = _View(40), _View(41)
            doc = _SwapDoc([a, b], [])
            uidoc = _UiDoc(doc)
            opened, isolated, errors = revisions.show_clouds(
                uidoc, {u'40': [u'901', u'902'], u'41': [u'903'],
                        u'99': [u'905']})
            if a.isolated != [901, 902] or b.isolated != [903] or \
                    isolated != 3:
                fail.add('register_tidp', 'the clouds were not isolated in '
                         'their views: {0} {1}'.format(a.isolated,
                                                       b.isolated))
            if opened != 2 or uidoc.opened[-1] != 40:
                fail.add('register_tidp', 'the views were not all opened, '
                         'the first one last so it is in front: {0}'.format(
                             uidoc.opened))
            if [one.state for one in doc.transactions] != ['committed'] or \
                    len(errors) != 1:
                fail.add('register_tidp', 'the isolation did not run in one '
                         'transaction, or a missing view was not reported')
        except Exception as err:
            fail.add('register_tidp', 'show_clouds threw: {0}: {1}'.format(
                err.__class__.__name__, err))
        finally:
            for name, value in kept.items():
                setattr(revisions, name, value)

    if winmod is not None:
        if winmod.place_after([u'a', u'used', u'series', u'x_1',
                               u'unplaced'], [u'a', u'series'], u'unplaced',
                              u'series') != [u'a', u'used', u'series',
                                             u'unplaced', u'x_1']:
            fail.add('register_tidp', 'Clouds off sheets is not put after '
                     'Sheet series in a saved order')
        fields = [entry[0] for entry in winmod.COLUMNS]
        if u'unplaced' not in fields:
            fail.add('register_tidp', 'no Clouds off sheets column')
    revtext = read(os.path.join(root, 'ps_revwin.py'))
    for needed, why in (
            ('self.grid.PreviewMouseRightButtonUp += self._right_release',
             'right-click in the manager opens no menu'),
            ("'find_clouds', bool(views)),",
             'the menu has no Find clouds on views'),
            ('self.on_find(views)',
             'Find clouds on views does nothing when opened on its own'),
            ('self.find_request = views',
             'Find clouds on views does nothing when opened from the '
             'register'),
            ('manager.on_find = find_clouds',
             'the manager on its own has nothing to run Find with'),
            ("u' ({0} in views on no sheet - right-click > '",
             'Delete does not say where the clouds are'),
            ("ordered = place_after(column_order(",
             'Clouds off sheets lands at the far end of a saved order')):
        if needed not in revtext:
            fail.add('register_tidp', why)
    if 'ps_revisions.show_clouds(\n                        uiapp.ActiveUIDocument, find)' \
            not in view or 'find = manager.find_request' not in view:
        fail.add('register_tidp', 'the register does not open the views '
                 'the manager asked for')

    # -- 1.47.0: a double-click on the top or bottom edge, on any window
    #    the tool draws its own edges for
    if winmod is not None:
        ui = winmod.ps_ui

        class _Win(object):
            Top, Height = 200.0, 720.0

        class _Args(object):
            def __init__(self, clicks):
                self.ClickCount = clicks
                self.Handled = False

        chrome = ui.Chrome.__new__(ui.Chrome)
        chrome.window = _Win()
        chrome.full_screen = False
        chrome.tall_saved = None
        chrome.shrunk = False
        chrome._drawer = None
        saved_area = ui.working_area
        ui.working_area = lambda window: (0, 10, 1920, 1030)
        try:
            chrome._edge_down(None, _Args(1))
            if (chrome.window.Top, chrome.window.Height) != (200.0, 720.0):
                fail.add('register_tidp', 'a single click on the edge '
                         'stretched the window')
            args = _Args(2)
            chrome._edge_down(None, args)
            if (chrome.window.Top, chrome.window.Height) != (10.0, 1030.0) \
                    or not args.Handled:
                fail.add('register_tidp', 'a double-click on the top or '
                         'bottom edge did not stretch the window to the '
                         'screen\'s height')
            chrome._edge_down(None, _Args(2))
            if (chrome.window.Top, chrome.window.Height) != (200.0, 720.0):
                fail.add('register_tidp', 'a second double-click on the edge '
                         'did not put the window back')
            chrome.full_screen = True
            if chrome.toggle_tall() is not None or \
                    chrome.window.Height != 720.0:
                fail.add('register_tidp', 'a full screen window was '
                         'stretched')
        except Exception as err:
            fail.add('register_tidp', 'the edge double-click threw: {0}: '
                     '{1}'.format(err.__class__.__name__, err))
        finally:
            ui.working_area = saved_area
    uitext = read(os.path.join(root, 'ps_ui.py'))
    if "TALL_EDGES = ('GripN', 'GripS')" not in uitext or \
            'thumb.PreviewMouseLeftButtonDown += self._edge_down' \
            not in uitext:
        fail.add('register_tidp', 'the top and bottom edges take no '
                 'double-click')
    if 'stretched = self.chrome.toggle_tall()' not in \
            read(os.path.join(root, 'ps_revwin.py')):
        fail.add('register_tidp', 'the bottom bar and the edges keep '
                 'separate memories of the height, so one cannot undo the '
                 'other')

    # -- wiring
    for needed, where, why in (
            ("settings.text('reg_status_param', u''),", view,
             'the register does not read the sheet status'),
            ("ps_config.SCALE_REVIT else u''", view,
             'the scale method setting is ignored'),
            # In export_info itself: from 1.51.0 the register's own block
            # reads the same store, and a whole-file search was satisfied
            # by that with the Excel's read gone.
            ('ps_revdata.read(self.host.doc)',
             _method_body(view, 'export_info'),
             'the Excel has no Issued To / Method data'),
            ("'SetupStatusCombo', 'reg_status_param'", setupsource,
             'the status parameter cannot be chosen'),
            ("'SetupScaleCombo', 'reg_scale_param'", setupsource,
             'the scale parameter cannot be chosen'),
            ('x:Name="SetupScaleRevitRadio"', setup,
             "Revit's own scale cannot be chosen"),
            ('x:Name="ColumnGroupCombo"', adding,
             'a column cannot be put in a group'),
            ("'group': self.group()}", colwin,
             'the group chosen is not handed back'),
            ('keep_groups(ordered, self._group_of)',
             read(os.path.join(root, 'ps_revwin.py')),
             'the manager lets a dragged order split a group')):
        if needed not in where:
            fail.add('register_tidp', why)
    if 'SetupRegIssuedTo' in setup:
        fail.add('register_tidp', 'Setup still asks for an Issued to list '
                 'the register no longer uses')
    tabs = layout.find('x:Name="RegisterTabs"')
    discard = layout.find('x:Name="RegisterDiscardRevsButton"')
    apply_at = layout.find('x:Name="RegisterApplyRevsButton"')
    if not (0 < tabs < discard < apply_at):
        fail.add('register_tidp', 'Discard and Apply are not along the '
                 'bottom, Discard to the left of Apply')
    for name, style in (('RegisterApplyRevsButton', 'PrimaryButton'),
                        ('RegisterDiscardRevsButton', 'DangerButton')):
        start = layout.find('x:Name="{0}"'.format(name))
        if 'Style="{{DynamicResource {0}}}"'.format(style) not in \
                layout[start:start + 200]:
            fail.add('register_tidp', '{0} is not {1} - green to apply, red '
                     'to discard'.format(name, style))


# ==========================================================================
# rule : Express print - Project Browser Pro's headless run
#
# ps_express is driven against a stand-in window module and a stand-in
# pbp_handoff, so every check below is about what express decides, not
# about WPF. The real window's methods it leans on are checked by name.
# ==========================================================================

class _ExControl(object):

    def __init__(self, text=u'', checked=False):
        self.Text = text
        self.IsChecked = checked


class _ExElement(object):

    def __init__(self, uid):
        self.UniqueId = uid


class _ExRow(object):

    def __init__(self, key, number, uid, is_sheet=True):
        self.key = key
        self.number = number
        self.is_sheet = is_sheet
        self.element = _ExElement(uid)


class _ExTable(object):

    def __init__(self):
        self.Rows = []


class _ExReport(object):

    def __init__(self, written, failed, cancelled=False):
        self._written = written
        self._failed = failed
        self.cancelled = cancelled

    def written(self):
        return list(self._written)

    def failed(self):
        return list(self._failed)

    def summary(self):
        return u'{0} written'.format(len(self._written))


class _ExOutcome(object):

    def __init__(self, label, fmt, message=u''):
        self.label = label
        self.fmt = fmt
        self.message = message
        self.path = u'C:\\out\\{0}.{1}'.format(label, fmt)


class _ExClosable(object):

    def __init__(self, record, name):
        self.record = record
        self.name = name

    def close(self):
        self.record.append(self.name)

    def Close(self):
        self.record.append(self.name)

    def Stop(self):
        self.record.append(self.name)


def _ex_window_module(case):
    """A stand-in ps_window: ProSheetsWindow plus the modules it carries."""
    module = types.ModuleType('ps_window')
    module.REVIT_PDF = u'Revit built-in PDF export'
    module.WINDOW = None
    record = case.setdefault('record', [])
    state = case.setdefault('state', {'suppressed': False})

    setup = types.ModuleType('ps_setupwin')
    setup.needed = lambda settings: True
    module.ps_setupwin = setup
    case['original_needed'] = setup.needed

    paths = types.ModuleType('ps_paths')
    paths.writable = lambda root: ((False, u'denied') if root == u'Z:\\locked'
                                   else (True, u''))
    module.ps_paths = paths

    ui = types.ModuleType('ps_ui')
    ui.combo_text = lambda control, default=u'': control.Text

    def fill_combo(control, items, selected=None):
        control.Text = selected
    ui.fill_combo = fill_combo
    module.ps_ui = ui

    export = types.ModuleType('ps_export')
    export.debug_reset = lambda: record.append('debug_reset')

    def begin(uiapp):
        state['suppressed'] = True
        record.append('suppress on')

    def end():
        state['suppressed'] = False
        record.append('suppress off')
        return []
    export.begin_suppression = begin
    export.end_suppression = end
    module.ps_export = export

    sheets = [_ExRow(1, u'M-01', u'uid-1'), _ExRow(2, u'M-02', u'uid-2'),
              _ExRow(3, u'M-03', u'uid-3')]
    views = [_ExRow(11, u'Floor Plan', u'view-1', False),
             _ExRow(12, u'Section', u'view-2', False)]

    class Window(object):

        def __init__(self, uiapp):
            if case.get('build_raises'):
                raise Exception('the model would not read')
            case['needed_during_build'] = setup.needed(None)
            self.uiapp = uiapp
            self.ui = {
                'ViewsRadio': _ExControl(checked=case.get('views', False)),
                'SheetsRadio': _ExControl(
                    checked=not case.get('views', False)),
                'PrinterCombo': _ExControl(case.get('printer',
                                                    module.REVIT_PDF)),
                'StagingBox': _ExControl(case.get('staging', u'')),
                'RootFolderBox': _ExControl(case.get('root', u'C:\\out')),
            }
            self.printer_list = [module.REVIT_PDF, u'PDF24']
            self.exporting = False
            self.last_report = None
            self._theme_timer = _ExClosable(record, 'theme timer')
            self._filter_timer = None
            self._progress_done = 0
            self._export_total = 0
            self._issue_folder = u''
            self._hunted_folder = u''
            self.register = _ExClosable(record, 'register closed')
            self.window = _ExClosable(record, 'window closed')
            self._read()
            case['window'] = self

        def _read(self):
            self.rows = list(views if self._is_views_mode() else sheets)
            self.table = _ExTable()
            self.table.Rows.append({'key': u'', 'sel': False})
            # The template's own tick - M-03, never sent - on every read,
            # as the real window's isolation and template give it back.
            for row in self.rows:
                self.table.Rows.append({'key': u'{0}'.format(row.key),
                                        'sel': row.key == 3})

        def c(self, name):
            return self.ui.get(name)

        def _is_views_mode(self):
            return bool(self.ui['ViewsRadio'].IsChecked)

        def _mode_changed(self, sender, args):
            self._read()

        def chosen_formats(self):
            return list(case.get('formats', ['pdf']))

        def plan_jobs(self):
            keys = [entry['key'] for entry in self.table.Rows
                    if entry['key'] and entry['sel']]
            case['planned'] = keys
            return [_ExRow(key, key, key) for key in keys], {}

        def _pdf_blocker(self, formats):
            if ('pdf' in formats
                    and self.ui['PrinterCombo'].Text != module.REVIT_PDF
                    and not self.ui['StagingBox'].Text):
                return u'no staging folder'
            return u''

        def _printer_changed(self, sender, args):
            record.append('printer changed')

        def _text_of(self, name, default=u''):
            return self.ui[name].Text or default

        def _collect_profile(self):
            return {'pdf.printer': self.ui['PrinterCombo'].Text}

        def issue_folder(self, jobs, formats):
            return u'C:\\out\\issue'

        def _file_count(self, jobs, formats):
            return len(jobs) * len(formats)

        def _begin_progress(self, total):
            self.exporting = True
            self._export_total = total
            self._progress_done = 0

        def _progress(self, index, total, label, fmt):
            self._progress_done += 1

        def _show_report(self, report):
            case.setdefault('shown', []).append(report)

        def _do_export(self, uiapp, jobs, formats, profile):
            case['profile'] = profile
            case['suppressed_in_run'] = state['suppressed']
            if case.get('export_raises'):
                raise Exception('Revit refused the print')
            written = []
            for index, job in enumerate(jobs):
                self._progress(index + 1, len(jobs), u'M-0{0}'
                               .format(job.key), 'pdf')
                written.append(_ExOutcome(u'M-0{0}'.format(job.key), 'pdf'))
            failed = list(case.get('failed', []))
            export.end_suppression()
            report = _ExReport(written, failed)
            self.last_report = report
            self._show_report(report)

        def folder_to_open(self, report):
            return u'C:\\out\\issue'

    module.ProSheetsWindow = Window
    return module


def _ex_handoff(case):
    module = types.ModuleType('pbp_handoff')
    calls = case.setdefault('calls', [])

    def take(folder, project_title):
        calls.append(('take', project_title))
        return case.get('request')

    def progress(folder, token, done, total, current_label):
        calls.append(('progress', token, done, total, current_label))

    def finish(folder, token, ok, out_folder=u'', files=0, message=u''):
        calls.append(('finish', token, ok, out_folder, files, message))
    module.take = take
    module.progress = progress
    module.finish = finish
    return module


class _ExDoc(object):
    Title = u'Wrexham'


class _ExUiDoc(object):
    Document = _ExDoc()


class _ExUiApp(object):
    ActiveUIDocument = _ExUiDoc()


def _ex_request(**changes):
    request = {'request': u'express', 'token': u't-1',
               'sheet_uids': [u'uid-1', u'uid-2'],
               'sheet_numbers': [u'M-01', u'M-02'],
               'headless': True, 'open_folder': False}
    request.update(changes)
    return request


def _ex_run(express, tab, case):
    """ps_express.run against the stand-ins; the finish calls it made."""
    handoff = _ex_handoff(case)
    window = _ex_window_module(case)
    here = os.path.join(tab, 'Sheet Tools.panel',
                        'Pro Sheets Exporter.pushbutton')
    saved = dict((name, sys.modules.get(name))
                 for name in ('pbp_handoff', 'ps_window'))
    saved_path = list(sys.path)
    sys.modules['pbp_handoff'] = handoff
    sys.modules['ps_window'] = window
    try:
        case['result'] = express.run(_ExUiApp(), here)
    finally:
        sys.path[:] = saved_path
        for name, value in saved.items():
            if value is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value
    case['module'] = window
    return [call for call in case.get('calls', []) if call[0] == 'finish']


def rule_express_print(root, fail):
    rule = 'express_print'
    path = os.path.join(root, 'ps_express.py')
    if not os.path.isfile(path):
        fail.add(rule, 'ps_express.py is missing - Express print from '
                 'Project Browser Pro opens the window instead')
        return

    # script.py asks before it builds anything, and stops when answered.
    script = code_only(read(os.path.join(root, 'script.py')))
    asked = script.find('ps_express.run(uiapp, HERE)')
    built = script.find('ps_window.show(uiapp)')
    if asked < 0 or built < 0 or asked > built:
        fail.add(rule, 'script.py does not call ps_express.run before it '
                 'builds the window')
    elif not re.search(r'if ps_express\.run\(uiapp, HERE\):\s*\n\s*return\b',
                       script):
        fail.add(rule, 'script.py carries on to build the window after an '
                 'express run was answered - two exports, or a window '
                 'nobody asked for')

    express = _module_under_stubs(root, 'ps_express', rule, fail)
    if express is None:
        return

    # The real window still has every method express leans on.
    window_source = read(os.path.join(root, 'ps_window.py'))
    for name in ('plan_jobs', 'chosen_formats', '_pdf_blocker',
                 '_printer_changed', '_text_of', '_collect_profile',
                 'issue_folder', '_file_count', '_begin_progress',
                 '_progress', '_do_export', '_show_report', 'folder_to_open',
                 '_is_views_mode', '_mode_changed'):
        if not re.search(r'\n    def {0}\('.format(re.escape(name)),
                         window_source):
            fail.add(rule, 'ps_window has no {0} any more - express relies '
                     'on it'.format(name))
    if "if not ps_setupwin.needed(self.settings):" not in window_source:
        fail.add(rule, 'the first run setup check moved - express holds '
                 'ps_setupwin.needed off to build the window hidden')

    # Matching: UniqueId first, the number as a sheets only fallback.
    rows = [_ExRow(1, u'M-01', u'uid-1'), _ExRow(2, u'M-02', u'uid-2'),
            _ExRow(3, u'M-03', u'uid-3'),
            _ExRow(9, u'M-09', u'view-9', is_sheet=False)]
    uid_of = express.sheet_uid
    keys, missed = express.wanted_keys(
        rows, [u'uid-2', u'gone', u'gone-2', u'gone-3'],
        [u'M-99', u'M-03', u'M-09', u''], uid_of)
    if keys[:1] != [2]:
        fail.add(rule, 'a sheet renumbered since the browser read it is not '
                 'found by its UniqueId')
    if 3 not in keys:
        fail.add(rule, 'a sheet whose UniqueId changed is not found by its '
                 'number')
    if 9 in keys:
        fail.add(rule, 'the number fallback matched a view - only sheets '
                 'are ever sent')
    if keys != [2, 3] or missed != 2:
        fail.add(rule, 'matching gave {0} with {1} missed, expected '
                 '[2, 3] with 2'.format(keys, missed))
    line = express.failure_message(
        [_ExOutcome(u'M-03', 'pdf', u'offline\nmore'),
         _ExOutcome(u'M-04', 'dwg')])
    if line != u'2 did not write - M-03 [PDF]: offline; M-04 [DWG]':
        fail.add(rule, 'the failure line reads "{0}"'.format(line))

    holder = tempfile.mkdtemp(prefix='prosheets_express_')
    saved_appdata = os.environ.get('APPDATA')
    os.environ['APPDATA'] = os.path.join(holder, 'appdata')
    try:
        tab = os.path.join(holder, 'with', 'RevoBIM PY.tab')
        browser = os.path.join(tab, 'Management.panel',
                               'Project Browser Pro.pushbutton')
        os.makedirs(browser)
        _write(browser, 'pbp_handoff.py', u'# stand-in\n')
        bare = os.path.join(holder, 'bare', 'RevoBIM PY.tab')
        os.makedirs(os.path.join(bare, 'Management.panel'))
        moved = os.path.join(holder, 'moved', 'RevoBIM PY.tab')
        moved_browser = os.path.join(moved, 'Coordination.panel',
                                     'Project Browser Pro.pushbutton')
        os.makedirs(moved_browser)
        _write(moved_browser, 'pbp_handoff.py', u'# stand-in\n')

        # Found where it ships, and where it has been moved to.
        here = os.path.join(moved, 'Sheet Tools.panel', 'Pro Sheets.pushbutton')
        if express.browser_folder(here) != moved_browser:
            fail.add(rule, 'Project Browser Pro is not found outside the '
                     'Management panel - Express quietly opens the window')
        here = os.path.join(bare, 'Sheet Tools.panel', 'Pro Sheets.pushbutton')
        if express.browser_folder(here) is not None:
            fail.add(rule, 'a tab with no Project Browser Pro still found '
                     'a hand-off folder')

        # Appended to sys.path, never inserted ahead of Pro Sheets.
        saved_path = list(sys.path)
        saved_module = sys.modules.pop('pbp_handoff', None)
        try:
            express.load_handoff(browser)
            if sys.path[:len(saved_path)] != saved_path or \
                    sys.path[-1] != browser:
                fail.add(rule, "Project Browser Pro's folder went in ahead "
                         "of Pro Sheets' own on sys.path - a shared module "
                         "name would load the browser's copy")
        finally:
            sys.path[:] = saved_path
            sys.modules.pop('pbp_handoff', None)
            if saved_module is not None:
                sys.modules['pbp_handoff'] = saved_module

        # The whole run: exactly the sheets sent, no window, reported.
        case = {'request': _ex_request(), 'views': True,
                'printer': u'PDF24'}
        finished = _ex_run(express, tab, case)
        if case.get('result') is not True:
            fail.add(rule, 'an express request was not taken - the window '
                     'opened instead')
        if case.get('planned') != [u'1', u'2']:
            fail.add(rule, 'the run planned {0}, not exactly the two '
                     'sheets sent - the template\'s own ticks leaked in'
                     .format(case.get('planned')))
        if case.get('shown'):
            fail.add(rule, 'the report window was shown on an express run')
        if case.get('needed_during_build') is not False:
            fail.add(rule, 'the first run setup check was not held off while '
                     'the hidden window was built - a setup window can open')
        module = case.get('module')
        if module is not None and \
                module.ps_setupwin.needed is not case.get('original_needed'):
            fail.add(rule, 'ps_setupwin.needed was not put back after the '
                     'hidden build - the window never offers setup again')
        if (case.get('profile') or {}).get('pdf.printer') != \
                u'Revit built-in PDF export':
            fail.add(rule, 'a print driver with no staging folder was kept - '
                     'every sheet fails with "no file appeared"')
        if not case.get('suppressed_in_run'):
            fail.add(rule, "Revit's dialogs were not suppressed for the run")
        progress = [call for call in case.get('calls', [])
                    if call[0] == 'progress']
        if len(progress) < 3 or progress[-1][2:4] != (1, 2):
            fail.add(rule, 'the browser\'s progress strip was not told about '
                     'each file: {0}'.format(progress))
        if len(finished) != 1 or finished[0][2:5] != \
                (True, u'C:\\out\\issue', 2):
            fail.add(rule, 'finish was not called once with the folder and '
                     'file count: {0}'.format(finished))
        record = case.get('record', [])
        if 'window closed' not in record or 'theme timer' not in record:
            fail.add(rule, 'the hidden window was left open, or its theme '
                     'timer running')

        # Suppression is handed back even when the run throws.
        case = {'request': _ex_request(), 'export_raises': True}
        finished = _ex_run(express, tab, case)
        if case.get('state', {}).get('suppressed'):
            fail.add(rule, "a run that threw left Revit's dialogs being "
                     "answered automatically")
        if len(finished) != 1 or finished[0][2] is not False or \
                not finished[0][5].startswith(u'Pro Sheets stopped'):
            fail.add(rule, 'a run that threw was not reported through '
                     'finish - the browser waits for its timeout: {0}'
                     .format(finished))

        # A build that throws is reported too, and the check put back.
        case = {'request': _ex_request(), 'build_raises': True}
        finished = _ex_run(express, tab, case)
        if len(finished) != 1 or finished[0][2] is not False:
            fail.add(rule, 'a window that would not build was not reported '
                     'through finish')
        module = case.get('module')
        if module is not None and \
                module.ps_setupwin.needed is not case.get('original_needed'):
            fail.add(rule, 'ps_setupwin.needed was left patched after a '
                     'build that threw')

        # Refusals: through finish, with a reason.
        for changes, request, why in (
                ({'formats': []}, _ex_request(), 'no format ticked'),
                ({}, _ex_request(sheet_uids=[u'x'], sheet_numbers=[u'Z']),
                 'no sheet found'),
                ({'root': u'Z:\\locked'}, _ex_request(), 'a locked folder')):
            case = dict(changes)
            case['request'] = request
            finished = _ex_run(express, tab, case)
            if len(finished) != 1 or finished[0][2] is not False or \
                    not finished[0][5] or 'profile' in case:
                fail.add(rule, '{0} was not refused through finish with a '
                         'reason'.format(why))

        # A plain Print opens the window.
        case = {'request': _ex_request(request=u'print', headless=False)}
        finished = _ex_run(express, tab, case)
        if case.get('result') is not False or finished:
            fail.add(rule, 'a plain Print was run headless - it should open '
                     'the window with the sheets ticked')

        # No request at all opens the window.
        case = {'request': None}
        _ex_run(express, tab, case)
        if case.get('result') is not False:
            fail.add(rule, 'with no hand-off the window does not open')

        # No browser installed: the hand-off is never even asked.
        case = {'request': _ex_request()}
        _ex_run(express, bare, case)
        if case.get('result') is not False or case.get('calls'):
            fail.add(rule, 'with no Project Browser Pro installed the '
                     'window does not open as before')
    finally:
        if saved_appdata is None:
            os.environ.pop('APPDATA', None)
        else:
            os.environ['APPDATA'] = saved_appdata
        shutil.rmtree(holder, ignore_errors=True)


# ==========================================================================
# rule : headings wear Project Browser Pro's trade ramps
#
# One product, one look: the register's discipline and series headings
# and the Selection tab's groups take the browser's colours - a ramp per
# trade, dark to light down a level, the same on both themes, black or
# white text by contrast, a rounded pill with its shadow behind the text.
# ==========================================================================

BROWSER_RAMPS = {
    'electrical': ('#17572B', '#A9DFA6'),
    'mechanical': ('#173F78', '#A9D0F4'),
    'plumbing': ('#4F3220', '#D9B892'),
    'other': ('#4B2A6E', '#CDB2EA'),
}

BROWSER_TRADES = [
    (u'Electrical', 'electrical'), (u'Fire Alarm', 'electrical'),
    (u'E_Lighting', 'electrical'), (u'Data & Comms', 'electrical'),
    (u'Lightning Protection', 'electrical'),
    (u'Fire Protection', 'other'), (u'Sprinklers', 'other'),
    (u'Mechanical', 'mechanical'), (u'M-Ductwork', 'mechanical'),
    (u'Heating Pipework', 'mechanical'), (u'Chilled Water', 'mechanical'),
    (u'Public Health', 'plumbing'), (u'Hot Water', 'plumbing'),
    (u'Soil Vent Pipe', 'plumbing'), (u'Plumbing Fixtures', 'plumbing'),
    (u'SOLVENT', None), (u'Architecture', None), (u'General', None),
]


class _RampStand(object):

    def __init__(self, tab_label, disc_colour):
        self.tab_label = tab_label
        self.disc_colour = disc_colour


def rule_heading_ramps(root, fail):
    rule = 'heading_ramps'
    ramp = _module_under_stubs(root, 'ps_ramp', rule, fail)
    if ramp is None:
        return
    for trade, ends in BROWSER_RAMPS.items():
        if tuple(ramp.RAMPS.get(trade, ())) != ends:
            fail.add(rule, 'the {0} ramp is {1}, not Project Browser Pro\'s '
                     '{2}'.format(trade, ramp.RAMPS.get(trade), ends))
    if ramp.LADDER.get(1) != (0.0, 0.3) or ramp.LADDER.get(2) != (0.38, 0.95):
        fail.add(rule, 'the ladder is {0}, not the browser\'s main 0-0.3 and '
                 'next 0.38-0.95'.format(ramp.LADDER))
    for name, trade in BROWSER_TRADES:
        if ramp.trade_of(name) != trade:
            fail.add(rule, '"{0}" reads as {1}, expected {2}'
                     .format(name, ramp.trade_of(name), trade))

    # Every shade readable: black or white, at least AA.
    for trade in BROWSER_RAMPS:
        for step in range(0, 101, 5):
            colour = ramp.shade(trade, step / 100.0)
            ink = ramp.text_on(colour)
            if ramp.contrast(colour, ink) < 4.5:
                fail.add(rule, '{0} text on {1} ({2}) reads at {3:.2f}:1'
                         .format(ink, colour, trade,
                                 float(ramp.contrast(colour, ink))))
                break
    if ramp.text_on(BROWSER_RAMPS['other'][0]) != u'#FFFFFF' or \
            ramp.text_on(BROWSER_RAMPS['electrical'][1]) != u'#000000':
        fail.add(rule, 'heading text is not white on the dark end and black '
                 'on the light end')

    # The plan: dark to light per trade and level, series inherit.
    found = ramp.plan([(0, u'Architecture', 1, None),
                       (1, u'Structure', 1, None),
                       (2, u'General', 1, None),
                       (3, u'Electrical', 1, None),
                       (4, u'Lighting', 2, 3), (5, u'Level 01', 2, 3),
                       (6, u'Level 02', 2, 3)])
    other = [found[0], found[1], found[2]]
    if other != [ramp.shade('other', 0.0), ramp.shade('other', 0.15),
                 ramp.shade('other', 0.3)]:
        fail.add(rule, 'three "other" main headings are {0}, not spread '
                 'dark to light across 0-0.3'.format(other))
    if found[3] != BROWSER_RAMPS['electrical'][0]:
        fail.add(rule, 'a lone Electrical heading is {0}, not the darkest '
                 'green'.format(found[3]))
    series = [found[4], found[5], found[6]]
    if series != [ramp.shade('electrical', 0.38),
                  ramp.shade('electrical', 0.665),
                  ramp.shade('electrical', 0.95)]:
        fail.add(rule, 'series under Electrical are {0}: they should take '
                 'its greens, lighter, dark to light'.format(series))

    # The register plans its tree with them.
    view = _module_under_stubs(root, 'ps_regview', rule, fail)
    if view is not None:
        disc = view.RegisterView.discipline_colours(
            [u'Architecture', u'Electrical', u'Mechanical'])
        if disc.get(u'Electrical') != BROWSER_RAMPS['electrical'][0] or \
                disc.get(u'Mechanical') != BROWSER_RAMPS['mechanical'][0]:
            fail.add(rule, 'the register\'s discipline colours are {0}'
                     .format(disc))
        tree = [(u'Electrical', [], [(u'Lighting', [], None),
                                     (u'Level 01', [], None)]),
                (u'Mechanical', [], [(u'Ductwork', [], None)])]
        stand = _RampStand(view.ps_register.ALL_TAB, disc)
        colours = view.RegisterView.heading_colours(stand, tree, True)
        expected = {0: disc[u'Electrical'],
                    1: ramp.shade('electrical', 0.38),
                    2: ramp.shade('electrical', 0.95),
                    3: disc[u'Mechanical'],
                    4: ramp.shade('mechanical', 0.38)}
        if colours != expected:
            fail.add(rule, 'the All tab\'s headings are {0}, expected {1}'
                     .format(colours, expected))
        # The All tab's disciplines wear the tab strip's colours, which are
        # planned over every discipline, not just the ones on screen.
        strip = view.RegisterView.discipline_colours(
            [u'General', u'Architecture', u'Structure'])
        stand = _RampStand(view.ps_register.ALL_TAB, strip)
        colours = view.RegisterView.heading_colours(
            stand, [(u'Architecture', [], None), (u'Structure', [], None)],
            True)
        if colours.get(0) != strip[u'Architecture']:
            fail.add(rule, 'Architecture\'s heading is {0} but its tab is '
                     '{1}'.format(colours.get(0), strip[u'Architecture']))
        stand = _RampStand(u'Electrical', disc)
        colours = view.RegisterView.heading_colours(
            stand, [(u'Level 01', [], None), (u'Level 02', [], None)], False)
        if colours != {0: ramp.shade('electrical', 0.0),
                       1: ramp.shade('electrical', 0.3)}:
            fail.add(rule, 'on the Electrical tab, series naming no trade '
                     'are {0} - they should be the tab\'s greens'
                     .format(colours))

    # Wiring.
    regview = read(os.path.join(root, 'ps_regview.py'))
    painter = _method_body(regview, '_paint_row')
    if 'self.host._shade_brushes(' not in painter or \
            'Brushes.Transparent' not in painter:
        fail.add(rule, 'the register\'s rows are not painted from their '
                 'heading\'s colour, reset on every row')
    filler = _method_body(regview, '_fill')
    if 'self.heading_colours(tree, by_discipline)' not in filler:
        fail.add(rule, 'the register does not plan its headings\' colours '
                 'over the whole tab')
    if "head['gink'] = self.host._ink_brush(place)" not in \
            _method_body(regview, '_add_heading'):
        fail.add(rule, 'a register heading carries no text colour - blue '
                 'text on a dark green pill')
    window = read(os.path.join(root, 'ps_window.py'))
    if 'self._plan_runs([run[0] for run in runs])' not in \
            _method_body(window, '_apply_grouping'):
        fail.add(rule, 'the Selection tab\'s groups are not planned on the '
                 'ramps')
    if "heading['gink'] = self._ink_brush(" not in \
            _method_body(window, '_apply_grouping'):
        fail.add(rule, 'a Selection heading carries no text colour')
    if 'return self._shade_brushes(self._run_hex(place))' not in \
            _method_body(window, '_run_brushes'):
        fail.add(rule, 'the Selection tab still colours runs by hue, not by '
                 'trade ramp')

    layout = read(os.path.join(root, THEME_FILE))
    cell_style = re.search(r'<Style x:Key="GridCell".*?</Style>', layout, re.S)
    cell_style = cell_style.group(0) if cell_style else ''
    if '<Setter Property="Foreground" Value="{Binding gink}"/>' not in \
            cell_style:
        fail.add(rule, 'GridCell\'s heading text is not black or white by '
                 'contrast (gink)')
    if 'BorderBrush="{TemplateBinding BorderBrush}"' not in cell_style or \
            '<Setter Property="BorderBrush" Value="Transparent"/>' not in \
            cell_style:
        fail.add(rule, 'grid lines run across a heading\'s pill')
    pill = re.search(r'<ControlTemplate x:Key="HeadingRowTemplate".*?'
                     r'</ControlTemplate>', layout, re.S)
    pill = pill.group(0) if pill else ''
    if 'CornerRadius="4"' not in pill or 'DataGridCellsPresenter' not in pill:
        fail.add(rule, 'no rounded heading pill template')
    else:
        shadow = pill.find('DropShadowEffect')
        cells = pill.find('<DataGridCellsPresenter')
        worn = re.search(r'<Border[^>]*CornerRadius="4"[^>]*>\s*'
                         r'<Border\.Effect>\s*<DropShadowEffect', pill)
        if worn is None or shadow < 0 or cells < shadow or \
                pill.find('</Border>', shadow) > cells:
            fail.add(rule, 'the pill\'s shadow is not on its own Border '
                     'behind the cells - it would shadow the text too')
    row_style = re.search(r'<Style x:Key="GridRow".*?</Style>', layout, re.S)
    row_style = row_style.group(0) if row_style else ''
    if '{StaticResource HeadingRowTemplate}' not in row_style:
        fail.add(rule, 'heading rows do not wear the pill')


# ==========================================================================
# rule : every window shrinks to its title bar and comes back
#
# The shrink button top right of every Pro Sheets window slides it down to
# the bottom of the screen, title bar only, so Revit can be seen; the
# button turns into a green up arrow that slides it back. Driven against a
# stand-in window and a clock that moves on each read. The stand-in timer
# never ticks inside Start(): a real DispatcherTimer does not, and a fake
# that does hides a tick that throws inside Start()'s own fallback (the
# RevoBIM theme reference's warning). _drawer_pump runs the ticks the way
# the dispatcher would, recording what escapes; the rule fails on it.
# ==========================================================================

_DRAWER_RUNNING = []
_DRAWER_ERRORS = []


def _drawer_pump(limit=2000):
    for _step in range(limit):
        live = [timer for timer in _DRAWER_RUNNING if timer.running]
        if not live:
            return
        for timer in live:
            for handler in list(timer.Tick.handlers):
                try:
                    handler(timer, None)
                except Exception as err:
                    _DRAWER_ERRORS.append(err)
                    timer.running = False
    _DRAWER_ERRORS.append(Exception('a timer never stopped'))

class _DrawerEvent(object):

    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self


class _DrawerTimer(object):

    def __init__(self):
        self.Tick = _DrawerEvent()
        self.Interval = None
        self.running = False

    def Start(self):
        self.running = True
        _DRAWER_RUNNING.append(self)

    def Stop(self):
        self.running = False


class _DrawerClock(object):

    def __init__(self):
        self.now = 1000.0

    def time(self):
        self.now += 0.02
        return self.now


class _DrawerVisibility(object):
    Visible = 'visible'
    Collapsed = 'collapsed'


class _DrawerCorner(object):

    def __init__(self, radius):
        self.TopLeft = radius


class _DrawerPoint(object):

    def __init__(self, y):
        self.Y = y


class _DrawerPart(object):

    def __init__(self, parent=None):
        self.Visibility = 'visible'
        self.Parent = parent


class _DrawerPanel(object):

    def __init__(self):
        self.Children = []


class _DrawerHeader(_DrawerPart):

    def __init__(self, panel):
        _DrawerPart.__init__(self, panel)
        self.ActualHeight = 40.0
        self.CornerRadius = _DrawerCorner(5)

    def TranslatePoint(self, point, target):
        return _DrawerPoint(1.0)


class _DrawerButton(object):

    def __init__(self):
        self.Click = _DrawerEvent()
        self.Tag = None
        self.ToolTip = None


class _DrawerContent(object):

    def __init__(self):
        self.Height = float('nan')
        self.VerticalAlignment = 'stretch'


class _DrawerWindow(object):

    def __init__(self, top=200.0, height=700.0, owner=None):
        self.fail_set = False
        self.drags = 0
        self.Content = _DrawerContent()
        self.WindowStartupLocation = 'owner'
        self.SourceInitialized = _DrawerEvent()
        self.PreviewKeyDown = _DrawerEvent()
        self.Left = 300.0
        self.Top = top
        self.Width = 900.0
        self.Height = height
        self.MinHeight = 420.0
        self.Owner = owner
        self.tops = []
        self.Closed = _DrawerEvent()
        self.KeyDown = _DrawerEvent()
        panel = _DrawerPanel()
        self.header = _DrawerHeader(panel)
        self.body = _DrawerPart(panel)
        self.footer = _DrawerPart(panel)
        panel.Children.extend([self.header, self.body, self.footer])
        self.names = {'HeaderBar': self.header,
                      'ShrinkButton': _DrawerButton(),
                      'CloseButton': _DrawerButton()}
        self.activated = 0

    def __setattr__(self, name, value):
        if name in ('Top', 'Height') and self.__dict__.get('fail_set'):
            raise Exception('the window refused the move')
        if name == 'Top' and 'tops' in self.__dict__:
            self.tops.append(value)
        object.__setattr__(self, name, value)

    def FindName(self, name):
        return self.names.get(name)

    def Activate(self):
        self.activated += 1

    def DragMove(self):
        self.drags += 1


class _DrawerKey(object):
    H = 'H'
    Escape = 'Escape'
    Enter = 'Enter'
    Return = 'Enter'
    F11 = 'F11'


class _DrawerModifiers(object):
    Control = 2
    Shift = 4


class _DrawerKeyboard(object):
    Modifiers = 0


class _DrawerKeyArgs(object):

    def __init__(self, key):
        self.Key = key
        self.Handled = False


class _DrawerAlign(object):
    Top = 'top'
    Stretch = 'stretch'


class _DrawerStartup(object):
    Manual = 'manual'


def _element_text(text, name):
    """The whole element carrying x:Name="name", nested tags and all."""
    mark = text.find('x:Name="{0}"'.format(name))
    if mark < 0:
        return ''
    start = text.rfind('<', 0, mark)
    tag = re.match(r'<([\w:.]+)', text[start:]).group(1)
    depth = 0
    for found in re.finditer(r'<(/?)' + re.escape(tag) + r'\b[^>]*?(/?)>',
                             text[start:]):
        if found.group(1):
            depth -= 1
        elif not found.group(2):
            depth += 1
        if depth == 0:
            return text[start:start + found.end()]
    return text[start:]


def rule_shrink_drawer(root, fail):
    rule = 'shrink_drawer'

    # Every window carries the button in its header, before close.
    for name in LAYOUTS:
        text = read(os.path.join(root, name))
        header = _element_text(text, 'HeaderBar') or text
        shrink = header.find('x:Name="ShrinkButton"')
        close = header.find('x:Name="CloseButton"')
        if shrink < 0:
            fail.add(rule, '{0} has no shrink button in its title bar'
                     .format(name))
            continue
        if close < shrink:
            fail.add(rule, '{0}: the shrink button is not before close'
                     .format(name))
        full = header.find('x:Name="FullScreenButton"')
        if full >= 0 and full < shrink:
            fail.add(rule, '{0}: the shrink button is not first, before '
                     'full screen'.format(name))
        button = re.search(r'<Button x:Name="ShrinkButton"[^>]*>', header)
        if button is None or \
                'Style="{DynamicResource ShrinkButton}"' not in \
                button.group(0):
            fail.add(rule, '{0}: the shrink button does not wear the '
                     'ShrinkButton style'.format(name))

    layout = read(os.path.join(root, THEME_FILE))
    style = re.search(r'<Style x:Key="ShrinkButton".*?\n  </Style>', layout,
                      re.S)
    style = style.group(0) if style else ''
    trigger = style[style.find('<Style.Triggers>'):] if style else ''
    if not style:
        fail.add(rule, 'Theme.xaml has no ShrinkButton style')
    else:
        if '<Trigger Property="Tag" Value="shrunk">' not in trigger or \
                'Fill="{DynamicResource GreenBrush}"' not in trigger:
            fail.add(rule, 'shrunk, the button does not turn into a green '
                     'up arrow')
        if '<Setter Property="ContentTemplate">' not in \
                style[:style.find('<Style.Triggers>')]:
            fail.add(rule, 'the shrink glyphs are not a ContentTemplate - '
                     'one Path shared by every window can only have one '
                     'parent')

    ui = _module_under_stubs(root, 'ps_ui', rule, fail)
    if ui is None:
        return
    source = read(os.path.join(root, 'ps_ui.py'))
    if "shrink_button.Click += self._shrink_clicked" not in \
            _method_body(source, '_wire'):
        fail.add(rule, 'the shrink button is not wired')

    ui.DispatcherTimer = _DrawerTimer
    ui.time = _DrawerClock()
    ui.Visibility = _DrawerVisibility
    ui.CornerRadius = _DrawerCorner
    ui.Point = lambda x, y: None
    ui.working_area = lambda window: (0.0, 0.0, 1920.0, 1040.0)

    class _Span(object):
        @staticmethod
        def FromMilliseconds(value):
            return value
    ui.TimeSpan = _Span
    ui.Key = _DrawerKey
    ui.Keyboard = _DrawerKeyboard
    ui.ModifierKeys = _DrawerModifiers
    ui.VerticalAlignment = _DrawerAlign
    ui.WindowStartupLocation = _DrawerStartup
    del ui._CHROMES[:]
    del ui._SHRUNK[:]
    del _DRAWER_RUNNING[:]
    del _DRAWER_ERRORS[:]

    window = _DrawerWindow()
    chrome = ui.Chrome(window)
    bottom = 1040.0 - ui.Chrome.BAR_MARGIN
    window.tops = []
    chrome.toggle_shrink()
    if window.Content.Height != 700.0 or \
            window.Content.VerticalAlignment != 'top':
        fail.add(rule, 'the body was not pinned for the slide - the grid is '
                 're-measured on every frame')
    _drawer_pump()
    if window.Content.Height == window.Content.Height or \
            window.Content.VerticalAlignment != 'stretch':
        fail.add(rule, 'the body was left pinned once the slide finished')
    if not chrome.shrunk or window.Height != 42.0 or \
            window.Top != bottom - 42.0:
        fail.add(rule, 'shrunk to top {0}, height {1}: expected the 42 '
                 'high title bar on the bottom of the screen at {2}'
                 .format(window.Top, window.Height, bottom - 42.0))
    if len(window.tops) < 4 or window.tops != sorted(window.tops):
        fail.add(rule, 'the window jumped rather than sliding down like a '
                 'drawer: {0}'.format(window.tops[:6]))
    if window.MinHeight != 0:
        fail.add(rule, 'MinHeight was left on, so the window cannot get '
                 'down to its title bar')
    if window.body.Visibility != 'collapsed' or \
            window.footer.Visibility != 'collapsed' or \
            window.header.Visibility != 'visible':
        fail.add(rule, 'shrunk, more than the title bar is showing')
    if window.names['ShrinkButton'].Tag != u'shrunk':
        fail.add(rule, 'shrunk, the button did not turn into the up arrow')
    if chrome.true_size() != (900.0, 700.0):
        fail.add(rule, 'shrunk, the size to remember is {0}, not the '
                 'window\'s own'.format(chrome.true_size()))
    if chrome.toggle_tall() is not None:
        fail.add(rule, 'a shrunk bar stretched to the full screen height')
    chrome.toggle_full_screen()
    if chrome.full_screen:
        fail.add(rule, 'a shrunk bar went full screen')

    window.tops = []
    chrome.toggle_shrink()
    if window.Content.Height != 700.0:
        fail.add(rule, 'the body was not pinned at its full height for the '
                 'slide back up')
    _drawer_pump()
    if chrome.shrunk or (window.Left, window.Top, window.Height,
                         window.MinHeight) != (300.0, 200.0, 700.0, 420.0):
        fail.add(rule, 'expanding put the window at {0}, not back where it '
                 'was'.format((window.Left, window.Top, window.Height,
                               window.MinHeight)))
    if len(window.tops) < 4:
        fail.add(rule, 'the window jumped back rather than sliding up')
    if window.body.Visibility != 'visible' or \
            window.names['ShrinkButton'].Tag != u'':
        fail.add(rule, 'expanded, the body or the shrink glyph did not come '
                 'back')

    # A double-click on the shrunk bar brings it back.
    chrome.shrink()
    _drawer_pump()

    class _Click(object):
        ClickCount = 2

    class _Press(object):
        ClickCount = 1

    # Not dragged while a job runs; dragged otherwise.
    chrome.busy = lambda: True
    chrome._header_down(None, _Press())
    if window.drags:
        fail.add(rule, 'the shrunk bar was dragged mid-export - a modal '
                 'loop inside Revit\'s API context')
    chrome.busy = None
    chrome._header_down(None, _Press())
    if window.drags != 1:
        fail.add(rule, 'the shrunk bar cannot be dragged')
    chrome._header_down(None, _Click())
    _drawer_pump()
    if chrome.shrunk:
        fail.add(rule, 'double-clicking the shrunk bar did not bring the '
                 'window back')

    # A dialog takes its Pro Sheets owner down with it, stacked, and
    # brings it back.
    owner_window = _DrawerWindow()
    owner = ui.Chrome(owner_window)
    child_window = _DrawerWindow(top=300.0, height=500.0,
                                 owner=owner_window)
    child = ui.Chrome(child_window)
    child.shrink()
    _drawer_pump()
    if not owner.shrunk:
        fail.add(rule, 'a dialog shrank but the main window stayed over '
                 'Revit')
    elif child_window.Top != owner_window.Top - ui.Chrome.BAR_GAP - 42.0:
        fail.add(rule, 'the dialog\'s bar sits at {0}, not stacked above '
                 'its owner\'s at {1}'.format(child_window.Top,
                                              owner_window.Top))
    child.expand()
    _drawer_pump()
    if owner.shrunk or owner_window.Height != 700.0:
        fail.add(rule, 'expanding the dialog left its owner shrunk')
    child.shrink()
    _drawer_pump()
    child._forget()
    _drawer_pump()
    if owner.shrunk:
        fail.add(rule, 'a dialog closed from its bar left its owner shrunk')

    # A dialog opening over a shrunk owner is centred on the screen.
    owner.shrink()
    _drawer_pump()
    dialog_window = _DrawerWindow(owner=owner_window)
    dialog_window.Width = 600.0
    dialog_window.Height = 400.0
    dialog = ui.Chrome(dialog_window)
    dialog._place_start()
    if (dialog_window.WindowStartupLocation, dialog_window.Left,
            dialog_window.Top) != ('manual', 660.0, 320.0):
        fail.add(rule, 'a dialog opening over a shrunk window was not '
                 'centred on the screen: {0}'.format(
                     (dialog_window.WindowStartupLocation,
                      dialog_window.Left, dialog_window.Top)))
    owner.expand()
    _drawer_pump()
    plain_window = _DrawerWindow(owner=owner_window)
    ui.Chrome(plain_window)._place_start()
    if plain_window.WindowStartupLocation != 'owner':
        fail.add(rule, 'a dialog over an open window was moved off its '
                 'owner')

    # Keys: Ctrl+Shift+H shrinks; shrunk, Escape brings it back.
    _DrawerKeyboard.Modifiers = 6
    press = _DrawerKeyArgs('H')
    chrome._preview_key(None, press)
    _drawer_pump()
    _DrawerKeyboard.Modifiers = 0
    if not chrome.shrunk or not press.Handled:
        fail.add(rule, 'Ctrl+Shift+H did not shrink the window')
    press = _DrawerKeyArgs('Escape')
    chrome._preview_key(None, press)
    _drawer_pump()
    if chrome.shrunk or not press.Handled:
        fail.add(rule, 'Escape on a shrunk window did not bring it back - '
                 'it reached the dialog\'s Cancel instead')

    # A window that refuses a move mid-slide still finishes the slide.
    stubborn_window = _DrawerWindow()
    stubborn = ui.Chrome(stubborn_window)
    stubborn_window.fail_set = True
    try:
        stubborn.shrink()
        _drawer_pump()
    except Exception as err:
        fail.add(rule, 'a window that refused a move broke the shrink: '
                 '{0}'.format(err))
    stubborn_window.fail_set = False
    if stubborn._drawer is not None or \
            stubborn_window.body.Visibility != 'collapsed':
        fail.add(rule, 'a tick that threw left the drawer stuck mid-slide')
    if _DRAWER_ERRORS:
        fail.add(rule, 'a drawer tick let an error escape to the '
                 'dispatcher: {0}'.format(_DRAWER_ERRORS[0]))

    # Put back at once before a close.
    chrome.shrink()
    _drawer_pump()
    chrome.restore_now()
    if chrome.shrunk or window.Height != 700.0 or window.MinHeight != 420.0:
        fail.add(rule, 'restore_now did not put the window back')

    window_source = read(os.path.join(root, 'ps_window.py'))
    if 'self.chrome.busy = lambda: bool(self.exporting)' not in \
            window_source:
        fail.add(rule, 'the main window does not tell its Chrome an export '
                 'is running, so the shrunk bar can be dragged mid-run')
    if _method_body(window_source, 'remember_window').count(
            'self.chrome.true_size()') != 1 or \
            _method_body(window_source, '_collect_profile').count(
                'self.chrome.true_size()') != 1:
        fail.add(rule, 'the window\'s size is remembered from the shrunk '
                 'bar - the next launch opens 42 pixels high')


# ==========================================================================
# rule : dark is Revit's own dark theme
#
# From 1.50.0 the dark palette is measured from Revit's dark Project
# Browser, the same family as Project Browser Pro's, so the tool reads as
# part of Revit. Theme.xaml's defaults are what a window shows before the
# palette is applied, so they must be the same colours.
# ==========================================================================

REVIT_DARK = {
    'BarBg': '#222933',        # title bar
    'WindowBg': '#3C4454',     # body
    'FieldBg': '#2D3441',      # search field
    'HoverBrush': '#444E5E',   # row hover
    'SelectionBrush': '#3A7392',   # Revit's active blue
}


def _contrast(first, second):
    def lum(text):
        total = 0.0
        for weight, value in zip((0.2126, 0.7152, 0.0722), _channels(text)):
            part = value / 255.0
            part = part / 12.92 if part <= 0.03928 else \
                ((part + 0.055) / 1.055) ** 2.4
            total += weight * part
        return total + 0.05
    one, two = lum(first), lum(second)
    return max(one, two) / min(one, two)


def rule_revit_dark(root, fail):
    rule = 'revit_dark'
    theme_module = _module_under_stubs(root, 'theme', rule, fail)
    if theme_module is None:
        return
    dark = theme_module.DARK
    for key, wanted in REVIT_DARK.items():
        if u'{0}'.format(dark.get(key, u'')).upper() != wanted:
            fail.add(rule, 'dark {0} is {1}, not Revit\'s {2}'
                     .format(key, dark.get(key), wanted))
    layout = read(os.path.join(root, THEME_FILE))
    for key, value in dark.items():
        found = re.search(r'<SolidColorBrush x:Key="{0}"\s+Color="(#[0-9A-Fa-f]{{6}})"'
                          .format(re.escape(key)), layout)
        if found and found.group(1).upper() != u'{0}'.format(value).upper():
            fail.add(rule, 'Theme.xaml\'s {0} is {1} but the dark palette '
                     'says {2} - a window flashes the old colour before the '
                     'palette lands'.format(key, found.group(1), value))
    for ink, minimum, grounds in (
            ('TextBrush', 7.0, ('WindowBg', 'CardBg', 'FieldBg', 'BarBg',
                                'HoverBrush')),
            ('MutedBrush', 4.0, ('WindowBg', 'CardBg', 'FieldBg', 'BarBg')),
            ('BlueBrush', 4.0, ('WindowBg', 'CardBg', 'FieldBg', 'BarBg'))):
        for ground in grounds:
            ratio = _contrast(dark[ink], dark[ground])
            if ratio < minimum:
                fail.add(rule, 'dark {0} on {1} reads at {2:.2f}:1, under '
                         '{3}'.format(ink, ground, float(ratio),
                                      float(minimum)))


# ==========================================================================
# rule : the register's issue data block (1.51.0)
#
# Issue Status and the Issued To / Issued Method ticks as rows under the
# revision headings, read from the Revision Manager's columns, staged on
# the register's own Undo / Redo and written only by Apply revisions.
# ==========================================================================

class _IssueControl(object):

    def __init__(self, kind):
        self.kind = kind
        self.IsChecked = False
        self.Text = u''
        self.IsKeyboardFocusWithin = False


class _IssueTick(_IssueControl):
    pass


class _IssueRowStand(object):

    def __init__(self):
        self.background = None

    def SetResourceReference(self, prop, key):
        self.background = key

    def ClearValue(self, prop):
        self.background = None


class _IssueRevision(object):

    def __init__(self, key, uid, element_key):
        self.key = key
        self.uid = uid
        self.element_key = element_key
        self.sequence = int(element_key)
        self.date = u''


class _IssueStand(object):
    """Enough of RegisterView to stage, paint and describe issue data."""

    def __init__(self, regview, register, revdata):
        self._regview = regview
        self.pending = register.PendingEdits()
        self._pending_flags = {}
        self._suspend = False
        self.rows_by_key = {}
        self._entries = {}
        self.said = []
        self.host = self
        self._issue_painting = False
        self.revisions = [_IssueRevision(u'r11', u'uid-11', 11),
                          _IssueRevision(u'r12', u'uid-12', 12)]
        self.used_columns = list(self.revisions)
        self.issue_fields = revdata.issue_block(revdata.default_columns())
        self.issue_stored = {}
        for revision in self.revisions:
            for field in self.issue_fields:
                self.issue_stored[(revision.key, field.id)] = \
                    revdata.stored_value(field, u'')
        self.issue_stored[(u'r11', u'status')] = u'S4'
        self.issue_stored[(u'r11', u'it1')] = u'1'
        self.issue_cells = {}
        self.issue_rows = {}
        self.issue_pieces = {}

    def __getattr__(self, name):
        method = getattr(self._regview.RegisterView, name)
        return lambda *args, **kw: method(self, *args, **kw)

    def say(self, text):
        self.said.append(text)

    def _paint_pending_buttons(self):
        pass

    def _set_picked_cells(self, picked):
        pass

    def _labels(self, columns):
        return u', '.join(columns)

    def set_show_all_revisions(self, show_all, quiet=False):
        self.said.append('show all')


def rule_register_issue_block(root, fail):
    rule = 'register_issue_block'
    revdata = _module_under_stubs(root, 'ps_revdata', rule, fail)
    register = _module_under_stubs(root, 'ps_register', rule, fail)
    view = _module_under_stubs(root, 'ps_regview', rule, fail)
    if revdata is None or register is None or view is None:
        return

    # The block: Issue Status, then Issued To, then Method - never a
    # plain column.
    columns = revdata.default_columns()
    block = revdata.issue_block(columns)
    if [(one.id, one.group) for one in block] != [
            (u'status', u'status'), (u'it1', u'issued_to'),
            (u'it2', u'issued_to'), (u'it3', u'issued_to'),
            (u'm1', u'method'), (u'm2', u'method')]:
        fail.add(rule, 'the block is {0}, not Issue Status then Issued To '
                 'then Method'.format([one.id for one in block]))
    edges = revdata.block_edges(block)
    if edges != ['frame', 'line', 'line', 'frame', 'line', None]:
        fail.add(rule, 'the block\'s dividing lines are {0}: a medium line '
                 'under Issue Status and between the groups, thin between '
                 'rows'.format(edges))
    tick = block[1]
    if revdata.stored_value(tick, u'') != u'0' or \
            revdata.stored_value(tick, u'1') != u'1':
        fail.add(rule, 'an empty Yes/No does not read as unticked')

    values, done, problems = revdata.apply_changes(
        columns + [revdata.Column(u'n1', u'Count', 'number')],
        {u'uid-1': {u'it1': u'1', u'notes': u'kept'}},
        [(u'uid-1', u'it1', u'0'), (u'uid-1', u'status', u'S4'),
         (u'uid-1', u'status', u'S2'), (u'uid-2', u'it2', u'yes'),
         (u'uid-1', u'gone', u'x'), (u'', u'it1', u'1'),
         (u'uid-1', u'n1', u'abc')])
    if values.get(u'uid-1') != {u'it1': u'0', u'notes': u'kept',
                                u'status': u'S2'} or \
            values.get(u'uid-2') != {u'it2': u'1'} or done != 4 or \
            len(problems) != 3:
        fail.add(rule, 'staged issue data played over the store gave {0}, '
                 '{1} done, problems {2}'.format(values, done, problems))

    # Staging: meta edits overlay, net out, count as one cell, survive a
    # read only while their revision and column do.
    stored = {(u'r1', u'it1'): u'1', (u'r1', u'status'): u'S4'}
    edits = [{'kind': 'meta', 'target': u'r1', 'field': u'it1',
              'value': u'0'},
             {'kind': 'meta', 'target': u'r1', 'field': u'status',
              'value': u'S2'},
             {'kind': 'meta', 'target': u'r1', 'field': u'status',
              'value': u'S4'}]
    if register.meta_values(stored, edits) != {(u'r1', u'it1'): u'0',
                                               (u'r1', u'status'): u'S4'}:
        fail.add(rule, 'the staged edits are not played over the store in '
                 'order')
    if register.meta_changed(stored, edits) != set([(u'r1', u'it1')]):
        fail.add(rule, 'a status edited and edited back still shows as '
                 'changed')
    if register.pending_cells(edits[0]) != 1:
        fail.add(rule, 'an issue data edit does not count as one change')
    if register.pending_flags({u'S1': set([u'r1'])}, edits):
        fail.add(rule, 'an issue data edit was painted as a sheet change')
    pending = register.PendingEdits()
    for edit in edits + [{'kind': 'meta', 'target': u'r9', 'field': u'it1',
                          'value': u'1'}]:
        pending.push(edit)
    pending.prune([u'r1'], [u'S1'], [u'status'])
    if [edit['field'] for edit in pending.edits] != [u'status', u'status']:
        fail.add(rule, 'a read kept issue data edits whose revision or '
                 'column has gone: {0}'.format(pending.edits))

    # The view: stage, paint, undo, describe.
    stand = _IssueStand(view, register, revdata)
    for cell in list(stand.issue_stored):
        stand.issue_cells[cell] = _IssueControl('text') \
            if cell[1] == u'status' else _IssueTick('tick')
        stand.issue_rows[cell] = _IssueRowStand()
    view.CheckBox = _IssueTick
    if stand.stage_issue((u'r11', u'it1'), u'1') is not None:
        fail.add(rule, 'ticking an already ticked box staged a change')
    edit = stand.stage_issue((u'r12', u'it2'), u'1')
    if edit != {'kind': 'meta', 'target': u'r12', 'field': u'it2',
                'value': u'1'} or len(stand.pending) != 1:
        fail.add(rule, 'a tick was not staged as an issue data edit: '
                 '{0}'.format(edit))
    stand.stage_issue((u'r11', u'status'), u' S2 ')
    values = stand.issue_values()
    if values.get((u'r12', u'it2')) != u'1' or \
            values.get((u'r11', u'status')) != u'S2':
        fail.add(rule, 'staged values are not what the block shows: {0}'
                 .format(values))
    stand._paint_issue_block()
    if not stand.issue_cells[(u'r12', u'it2')].IsChecked or \
            stand.issue_cells[(u'r11', u'status')].Text != u'S2':
        fail.add(rule, 'the block is not painted with the staged values')
    if stand.issue_rows[(u'r12', u'it2')].background != 'GreenWashBrush' \
            or stand.issue_rows[(u'r11', u'it1')].background is not None:
        fail.add(rule, 'a staged cell is not washed green, or an unchanged '
                 'one is')
    if not [line for line in stand.said if u'Nothing is written' in line]:
        fail.add(rule, 'staging an issue value does not say it waits for '
                 'Apply')
    stand.undo()
    if stand.issue_values().get((u'r11', u'status')) != u'S4' or \
            len(stand.pending) != 1:
        fail.add(rule, 'Undo did not take the status back')
    stand.redo()
    if stand.issue_values().get((u'r11', u'status')) != u'S2':
        fail.add(rule, 'Redo did not put the status back')
    text = stand._describe(edit)
    if u'Issued To 2' not in text or u'ticked' not in text:
        fail.add(rule, 'the edit reads "{0}" in the Apply list'.format(text))
    changes, keys = stand._issue_changes(stand.pending.edits)
    if changes != [(u'uid-12', u'it2', u'1'), (u'uid-11', u'status',
                                              u'S2')] or \
            keys != {u'uid-11': 11, u'uid-12': 12}:
        fail.add(rule, 'Apply would write {0} / {1}'.format(changes, keys))

    # Wiring and layout, read from the source.
    source = read(os.path.join(root, 'ps_regview.py'))
    apply_body = _method_body(source, 'apply_revisions')
    if 'results.append(self._run_meta(doc, changes, keys_by_uid))' not in \
            apply_body or 'if edit.get(\'kind\') != ps_register.META]' not \
            in apply_body:
        fail.add(rule, 'Apply revisions does not write the staged issue data '
                 'in a run of its own')
    if 'ps_revdata.write_changes(doc, changes,' not in \
            _method_body(source, '_run_meta'):
        fail.add(rule, 'the issue data is not written through '
                 'ps_revdata.write_changes')
    data_source = read(os.path.join(root, 'ps_revdata.py'))
    start = data_source.find('\ndef write_changes(')
    end = data_source.find('\ndef ', start + 1)
    writer = data_source[start:end] if start >= 0 else ''
    for needed, why in (
            ('transaction.Start()', 'outside a transaction'),
            ('columns, values = read(doc)', 'over a stale copy of the store'),
            ('apply_changes(columns, values, changes)',
             'without playing the changes in order'),
            ('write(doc, columns, values)', 'not stored at all'),
            ('push(doc, columns, by_key)',
             'without pushing to the mapped parameters'),
            ('transaction.RollBack()', 'half way when it fails')):
        if needed not in writer:
            fail.add(rule, 'the issue data is written {0}'.format(why))
    if 'self._paint_issue_block()' not in _method_body(source,
                                                        '_paint_pending'):
        fail.add(rule, 'Undo and Redo do not repaint the block')
    if 'self._read_issue_data()' not in _method_body(source, 'reload'):
        fail.add(rule, 'the register does not read the issue data')
    header = _method_body(source, '_revision_header')
    piece = header.find('panel.Children.Add(self._issue_piece(revision))')
    foot = header.find('panel.Children.Add(self._footer(foot))')
    if piece < 0:
        fail.add(rule, 'the revision headings carry no issue data')
    elif foot < 0 or foot < piece or \
            'foot.Children.Add(self._filter_button(revision.key))' not in \
            header:
        fail.add(rule, 'a revision\'s filter is not at the foot of its '
                 'heading, under the issue data')
    identity = _method_body(source, '_identity_column')
    if identity.count('column.Header = self._under_block(') != 2 or \
            'column.Header = self._under_block(button)' not in \
            _method_body(source, '_plus_column'):
        fail.add(rule, 'a heading leaves no room for the block, so the '
                 'rows do not line up across the headings')
    under = _method_body(source, '_under_block')
    if under.find('panel.Children.Add(spacer)') < 0 or \
            under.find('panel.Children.Add(spacer)') > \
            under.find('panel.Children.Add(self._footer(content))'):
        fail.add(rule, 'the drawing columns\' names are not under the '
                 'issue data, right above the drawings')
    builder = _method_body(source, '_build_columns')
    if 'self._build_issue_labels()' not in builder or \
            'self.grid.LayoutUpdated += self._place_issue_labels' not in \
            _method_body(source, '_wire'):
        fail.add(rule, 'the block\'s row names are missing, or do not '
                 'follow the headings')
    if 'self._issue_label_column()' in source:
        fail.add(rule, 'the row names still take a column of their own')
    spot = view.RegisterView.label_spot(None, 500, 120, 150, True)
    if spot != (350.0, 120.0) or \
            view.RegisterView.label_spot(None, 500, 120, 150, False) \
            is not None:
        fail.add(rule, 'the row names are placed at {0}, not right-aligned '
                 'against the revisions'.format(spot))
    layout = read(os.path.join(root, 'ProSheets.xaml'))
    canvas = re.search(r'<Canvas x:Name="RegisterIssueLabels"[^>]*/>',
                       layout)
    if canvas is None or layout.find('x:Name="RegisterGrid"') > \
            layout.find('x:Name="RegisterIssueLabels"') or \
            'Background' in canvas.group(0) or \
            'ClipToBounds="True"' not in canvas.group(0):
        fail.add(rule, 'the names\' canvas is missing, under the grid, '
                 'catches every click, or spills outside it')
    frame = _method_body(source, '_block_frame')
    if 'frame.MouseLeftButtonDown += self._swallow' not in frame:
        fail.add(rule, 'a click on the block reaches the heading and '
                 'includes the revision\'s drawings')
    if "'MutedBrush'" not in frame or 'self.BLOCK_FRAME' not in frame:
        fail.add(rule, 'the block has no defining border')
    if view.RegisterView.BLOCK_MARGIN != (-5, 6, -5, 6):
        fail.add(rule, 'the block does not reach the heading\'s edges, so '
                 'the border breaks between revisions')
    edges_body = _method_body(source, '_paint_issue_edges')
    if 'self.BLOCK_FRAME if key == last else 1' not in edges_body:
        fail.add(rule, 'the last revision does not close the border')
    tick_body = _method_body(source, '_make_issue_tick')
    if 'if self._issue_painting:' not in tick_body:
        fail.add(rule, 'painting the block stages edits of its own')


# ==========================================================================
# rule : the register's heading colour modes (1.52.0)
#
# A button cycles the headings through the trade colours, plain greys and
# colours picked heading by heading (right-click a heading); the picks are
# kept per project, by heading name.
# ==========================================================================

class _ModeStand(object):
    """Enough of RegisterView for the heading colour modes."""

    def __init__(self, regview):
        self._regview = regview
        self.host = self
        self.theme_name = 'dark'
        self.heading_mode = 'colour'
        self.heading_custom = {}
        self._menu_heading = None
        self.loaded = True
        self.tab_index = 0
        self.refilled = 0
        self.saved = []
        self.said = []
        self.settings_written = {}
        self.picked_cells = set()
        self.picked_columns = []
        self.isolated = []
        self.pending = None
        self.heading_mode_text = None
        self.heading_mode_button = None

    def __getattr__(self, name):
        method = getattr(self._regview.RegisterView, name)
        return lambda *args, **kw: method(self, *args, **kw)

    def say(self, text):
        self.said.append(text)

    def select_tab(self, index):
        self.refilled += 1

    def _setting(self, key, value):
        self.settings_written[key] = value

    def _save_heading_colours(self):
        self.saved.append(dict(self.heading_custom))

    def _selected_keys(self):
        return []

    def _picked_revisions(self):
        return []


def rule_heading_modes(root, fail):
    rule = 'heading_modes'
    ramp = _module_under_stubs(root, 'ps_ramp', rule, fail)
    config = _module_under_stubs(root, 'ps_config', rule, fail)
    view = _module_under_stubs(root, 'ps_regview', rule, fail)
    if ramp is None or config is None or view is None:
        return

    if [ramp.next_mode(m) for m in ('colour', 'grey', 'custom')] != \
            ['grey', 'custom', 'colour'] or ramp.heading_mode('odd') != \
            'colour':
        fail.add(rule, 'the button does not cycle Coloured, Grey, Custom')
    green = u'#17572B'
    if ramp.mode_colour('colour', green, 1, 'dark', u'#FF0000') != green:
        fail.add(rule, 'a picked colour shows outside Custom headers')
    if ramp.mode_colour('custom', green, 1, 'dark', u'#FF0000') != \
            u'#FF0000' or ramp.mode_colour('custom', green, 2, 'light',
                                            None) != ramp.GREYS['light'][2]:
        fail.add(rule, 'Custom headers do not use the picked colour, or '
                 'are not grey where none is picked')
    greys = [ramp.mode_colour('grey', green, level, theme_name, u'#FF0000')
             for theme_name in ('dark', 'light') for level in (1, 2)]
    if greys != [ramp.GREYS['dark'][1], ramp.GREYS['dark'][2],
                 ramp.GREYS['light'][1], ramp.GREYS['light'][2]] or \
            greys[0] == greys[1] or greys[2] == greys[3]:
        fail.add(rule, 'grey headers are {0}: a darker grey for a '
                 'discipline, a lighter one for a series, per theme'
                 .format(greys))
    for colour in greys + list(ramp.SWATCHES):
        if ramp.contrast(colour, ramp.text_on(colour)) < 4.5:
            fail.add(rule, 'heading text on {0} is hard to read'
                     .format(colour))
            break
    if ramp.parse_hex(u' 3fa75a') != u'#3FA75A' or \
            ramp.parse_hex(u'#12345') is not None or \
            ramp.parse_hex(u'GGGGGG') is not None:
        fail.add(rule, 'typed colours are not checked')

    colours = {u'E-100-CONTAINMENT': u'#17572B', u'A=B': u'#4B2A6E'}
    if config.decode_heading_colours(
            config.encode_heading_colours(colours)) != colours:
        fail.add(rule, 'picked colours do not survive being saved')

    stand = _ModeStand(view)
    stand.cycle_heading_mode()
    if stand.heading_mode != 'grey' or \
            stand.settings_written.get('reg_heading_mode') != 'grey' or \
            not stand.refilled:
        fail.add(rule, 'the button does not move on, remember the mode and '
                 'repaint the headings')
    stand.heading_mode = 'colour'
    stand.set_heading_colour(u'E-200-SMALL POWER', u'#8B1E1E')
    if stand.heading_mode != 'custom' or \
            stand.heading_custom.get(u'E-200-SMALL POWER') != u'#8B1E1E' \
            or not stand.saved:
        fail.add(rule, 'picking a heading colour does not keep it and '
                 'switch to Custom headers')
    if stand.shown_colour(u'E-200-SMALL POWER', 2, green) != u'#8B1E1E' or \
            stand.shown_colour(u'E-300-LIGHTING', 2, green) != \
            ramp.GREYS['dark'][2]:
        fail.add(rule, 'the headings do not wear their picked colours')
    stand._menu_heading = u'E-200-SMALL POWER'
    actions = [entry[1] for entry in stand.menu_entries() if entry]
    for needed in ('heading_swatches', 'custom_heading_colour',
                   'reset_heading_colour', 'reset_heading_colours'):
        if needed not in actions:
            fail.add(rule, 'right-clicking a heading does not offer {0}'
                     .format(needed))
    stand._menu_heading = None
    if 'heading_swatches' in [entry[1] for entry in stand.menu_entries()
                              if entry]:
        fail.add(rule, 'the colour menu shows on a click off the headings')
    stand._menu_heading = u'E-200-SMALL POWER'
    stand.reset_heading_colour()
    if stand.heading_custom:
        fail.add(rule, 'resetting a heading does not forget its colour')

    source = read(os.path.join(root, 'ps_regview.py'))
    filler = _method_body(source, '_fill')
    if 'colour = self.shown_colour(label, 1, next_colour())' not in \
            filler or 'inner_colour = self.shown_colour(inner, 2, ' \
            'next_colour())' not in filler:
        fail.add(rule, 'the headings ignore the colour mode')
    if 'colour = self.shown_colour(label, 1, colour)' not in \
            _method_body(source, '_paint_tab_strip'):
        fail.add(rule, 'the tabs ignore the colour mode')
    if 'self.cycle_heading_mode()' not in _method_body(source, '_wire'):
        fail.add(rule, 'the heading colour button is not wired')
    press = _method_body(source, '_right_press')
    if "self._menu_heading = u'{0}'.format(entry['glabel'])" not in press \
            or press.find('self._menu_heading = None') > \
            press.find('source = args.OriginalSource'):
        fail.add(rule, 'a right-click on a heading is not remembered, or an '
                 'old one is kept')
    if "if action == 'heading_swatches':" not in \
            _method_body(source, '_register_menu'):
        fail.add(rule, 'the swatches never reach the menu')
    if 'menu.IsOpen = False' not in _method_body(source,
                                                  '_make_swatch_pick'):
        fail.add(rule, 'picking a swatch leaves the menu open')
    if 'if self.heading_mode == ps_ramp.GREY and self.loaded:' not in \
            _method_body(source, 'repaint'):
        fail.add(rule, 'grey headers keep the old theme\'s grey after a '
                 'theme change')
    layout = read(os.path.join(root, 'ProSheets.xaml'))
    if 'x:Name="RegisterHeadingModeButton"' not in layout or \
            'x:Name="RegisterHeadingModeText"' not in layout:
        fail.add(rule, 'the register has no heading colour button')


# ==========================================================================
# rule : the issue data frozen, or as rows that scroll (1.53.0); the
# register's toolbar - Settings by the Revision Manager, the colour button
# in its own colours, the freeze button
# ==========================================================================

class _RowsList(list):

    def Add(self, row):
        self.append(row)


class _RowsTable(object):

    def __init__(self):
        self.Rows = _RowsList()

    def NewRow(self):
        return {}


def rule_register_issue_rows(root, fail):
    rule = 'register_issue_rows'
    revdata = _module_under_stubs(root, 'ps_revdata', rule, fail)
    register = _module_under_stubs(root, 'ps_register', rule, fail)
    view = _module_under_stubs(root, 'ps_regview', rule, fail)
    if revdata is None or register is None or view is None:
        return

    tick = revdata.Column(u'it1', u'WLG', 'yesno', group=revdata.ISSUED_TO)
    status = revdata.Column(u'status', u'Issue Status', 'text',
                            group=revdata.STATUS)
    texts = [view.RegisterView.issue_cell_text(None, tick, u'1'),
             view.RegisterView.issue_cell_text(None, tick, u'0'),
             view.RegisterView.issue_cell_text(None, status, u'S4')]
    if texts != [u'x', u'', u'S4']:
        fail.add(rule, 'an issue row shows {0}: an x for a tick, the status '
                 'as typed'.format(texts))

    stand = _IssueStand(view, register, revdata)
    stand.issue_frozen = False
    stand.table = _RowsTable()
    if stand.block_shown():
        fail.add(rule, 'unfrozen, the block is still drawn in the heading')
    stand.issue_frozen = True
    if not stand.block_shown():
        fail.add(rule, 'frozen, the block is not in the heading')
    stand.issue_frozen = False
    stand._add_issue_rows()
    rows = stand.table.Rows
    keys = [row.get('key') for row in rows]
    if keys != [view.ISSUE_PREFIX + field.id for field in stand.issue_fields]:
        fail.add(rule, 'the issue rows are {0}'.format(keys))
    if [row.get('ord') for row in rows] != sorted(
            [row.get('ord') for row in rows]) or \
            not all([row.get('ord') < u'000000' for row in rows]):
        fail.add(rule, 'the issue rows do not sort above every heading')
    if not all([row.get('sel') is True and row.get('hidetick') == u'1' and
                row.get('show') == u'1' for row in rows]):
        fail.add(rule, 'an issue row is drawn muted, shows a tick, or is '
                 'hidden')
    if [row.get('level') for row in rows] != \
            (revdata.block_edges(stand.issue_fields)[:-1] + ['last']):
        fail.add(rule, 'the issue rows do not carry the block\'s lines')
    if rows[0].get('name') != u'Issue Status:' or \
            rows[1].get('num') != u'Issued to':
        fail.add(rule, 'the issue rows are not named as the Excel names '
                 'them')
    if stand._is_drawing(rows[0]) or not stand._is_issue(rows[0]):
        fail.add(rule, 'an issue row counts as a drawing')

    for row in rows:
        for revision in stand.revisions:
            row[revision.key] = u''
            row[view.PENDING_PREFIX + revision.key] = u''
    stand.stage_issue((u'r12', u'it2'), u'1')
    stand._paint_issue_rows()
    it2 = [row for row in rows if row['key'] == view.ISSUE_PREFIX + u'it2'][0]
    it1 = [row for row in rows if row['key'] == view.ISSUE_PREFIX + u'it1'][0]
    first = rows[0]
    if it2.get(u'r12') != u'x' or \
            it2.get(view.PENDING_PREFIX + u'r12') != register.PENDING_ADD:
        fail.add(rule, 'a staged tick is not shown, or not washed green, in '
                 'its row')
    if it1.get(u'r11') != u'x' or first.get(u'r11') != u'S4' or \
            it1.get(view.PENDING_PREFIX + u'r11'):
        fail.add(rule, 'the stored values are not in the rows, or are washed')
    stand._issue_row_click(it1, u'r11')
    if stand.issue_values().get((u'r11', u'it1')) != u'0':
        fail.add(rule, 'a click on a ticked cell does not untick it')
    stand._issue_row_click(it1, u'name')
    if len(stand.pending) != 2:
        fail.add(rule, 'a click outside the revisions staged something')

    source = read(os.path.join(root, 'ps_regview.py'))
    filler = _method_body(source, '_fill')
    if 'if self.issue_fields and not self.issue_frozen:\n                ' \
            'self._add_issue_rows()' not in filler:
        fail.add(rule, 'unfrozen, the issue rows are never added')
    if 'self._paint_issue_rows()' not in _method_body(source,
                                                       '_paint_pending'):
        fail.add(rule, 'Undo and Redo do not repaint the issue rows')
    click = _method_body(source, '_row_click')
    if click.find('self._issue_row_click(') < 0 or \
            click.find('self._issue_row_click(') > \
            click.find('self._cell_click('):
        fail.add(rule, 'a click on an issue row picks a cell instead')
    for name, why in (('_visible_keys', 'the header tick puts issue rows '
                       'in the register'),
                      ('_choices', 'a filter list offers the issue rows\' '
                       'values'),
                      ('_shown_rows', 'Shift+click runs through the issue '
                       'rows'),
                      ('_selected_keys', 'a highlighted issue row is '
                       'assigned a revision'),
                      ('sync_ticks', 'the issue rows are unticked and '
                       'drawn muted')):
        if 'self._is_drawing(entry)' not in _method_body(source, name):
            fail.add(rule, why)
    if "entry['show'] = u'1'\n                continue" not in \
            _method_body(source, '_apply_filters'):
        fail.add(rule, 'a search hides the issue rows')
    if 'if self._is_issue(entry):\n            return' not in \
            _method_body(source, '_tick_changed'):
        fail.add(rule, 'an issue row\'s tick changes the register')
    if 'row.ClearValue(DataGridRow.BorderThicknessProperty)' not in \
            _method_body(source, '_paint_issue_row') or \
            'if self._paint_issue_row(row, entry):' not in \
            _method_body(source, '_paint_row'):
        fail.add(rule, 'a recycled row keeps an issue row\'s lines')
    if "        self.issue_frozen = True\n" not in \
            _method_body(source, '__init__'):
        fail.add(rule, 'the issue rows do not open frozen')
    frozen = _method_body(source, 'set_issue_frozen')
    if 'if self.loaded:\n            self.select_tab(self.tab_index)' not in \
            frozen:
        fail.add(rule, 'the freeze button does not rebuild the grid')
    if 'self.toggle_issue_frozen()' not in _method_body(source, '_wire'):
        fail.add(rule, 'the freeze button is not wired')
    if 'SetResourceReference' in _method_body(source,
                                              '_paint_heading_mode_button'):
        fail.add(rule, 'the colour button is restyled to a plain chip')

    layout = read(os.path.join(root, 'ProSheets.xaml'))
    corner = _element_text(layout, 'RevisionManagerButton')
    top_right = re.search(r'<StackPanel Grid\.Row="0" Grid\.RowSpan="2" '
                          r'Grid\.Column="1".*?</StackPanel>\s*</Button>\s*'
                          r'</StackPanel>', layout, re.S)
    top_right = top_right.group(0) if top_right else ''
    if 'x:Name="RegisterSetupButton"' not in top_right or \
            'x:Name="RegisterSource"' not in top_right or \
            top_right.find('RegisterSetupButton') > \
            top_right.find('RevisionManagerButton'):
        fail.add(rule, 'Settings and the register\'s source are not beside '
                 'the Revision Manager')
    if 'Height="56"' not in corner or 'MinWidth' in corner:
        fail.add(rule, 'the Revision Manager button is not a little taller '
                 'and only as wide as its words')
    refresh = layout.find('x:Name="RegisterRefreshButton"')
    colour = layout.find('x:Name="RegisterHeadingModeButton"')
    freeze = layout.find('x:Name="RegisterFreezeButton"')
    if not (0 < refresh < colour < freeze):
        fail.add(rule, 'the colour and freeze buttons are not after Refresh')
    if 'Style="{DynamicResource HeadingModeButton}"' not in \
            _element_text(layout, 'RegisterHeadingModeButton'):
        fail.add(rule, 'the colour button wears a plain chip\'s colours')
    theme_text = read(os.path.join(root, THEME_FILE))
    style = re.search(r'<Style x:Key="HeadingModeButton".*?</Style>',
                      theme_text, re.S)
    if style is None or '{DynamicResource HeadingModeFill}' not in \
            style.group(0) or 'x:Key="HeadingModeFill"' not in theme_text:
        fail.add(rule, 'the colour button has no colours of its own')


# ==========================================================================
# rule : the register's name and logos in the heading, the tidied toolbar,
# greyscale by default, and the heading colours on the Selection tab
# (1.54.0)
# ==========================================================================

class _RunStand(object):

    def __init__(self, ramp):
        self.run_colours = [u'#17572B', u'#173F78', u'#4F3220']
        self.run_labels = [u'ELECTRICAL', u'MECHANICAL', u'PUBLIC HEALTH']
        self.heading_mode = ramp.GREY
        self.heading_custom = {}
        self.theme_name = 'dark'


def rule_register_brand(root, fail):
    rule = 'register_brand'
    ramp = _module_under_stubs(root, 'ps_ramp', rule, fail)
    view = _module_under_stubs(root, 'ps_regview', rule, fail)
    window = _window_module(root, rule, fail)
    if ramp is None or view is None or window is None:
        return
    box = view.RegisterView.brand_box(None, 10, 100, 300, 600, 50)
    if box != (18.0, 106.0, 574.0, 236.0) or \
            view.RegisterView.brand_box(None, 10, 100, 90, 600, 50) \
            is not None or \
            view.RegisterView.brand_box(None, 10, 100, 300, 100, 50) \
            is not None:
        fail.add(rule, 'the name and logos are placed at {0}, not in the '
                 'headings\' free space'.format(box))
    size = view.RegisterView.logo_size(None, 574, 236, 2, 30)
    if size != (269.0, 120.0) or \
            view.RegisterView.logo_size(None, 574, 236, 0, 30) != \
            (0.0, 0.0) or \
            view.RegisterView.logo_size(None, 80, 236, 2, 30) != (0.0, 0.0):
        fail.add(rule, 'the logos are sized {0}: half the room each, no '
                 'taller than 120'.format(size))

    source = read(os.path.join(root, 'ps_regview.py'))
    brand = _method_body(source, '_build_brand')
    for needed, why in (
            ("getattr(self, 'issue_frozen', True)",
             'the name and logos show with the rows scrolling'),
            ("settings.text('reg_title', u'')", 'the register\'s name is '
             'not the one in Settings'),
            ("for key in ('reg_logo', 'reg_client_logo'):",
             'the logos are not the ones in Settings'),
            ('panel.IsHitTestVisible = False',
             'the name and logos catch clicks meant for the headings')):
        if needed not in brand:
            fail.add(rule, why)
    labels = _method_body(source, '_build_issue_labels')
    if labels.find('self._build_brand()') < 0 or \
            labels.find('self._build_brand()') > \
            labels.find('if not self.block_shown() or canvas is None:'):
        fail.add(rule, 'the name and logos are only built with an issue '
                 'block')
    place = _method_body(source, '_place_issue_labels')
    if place.find('self._place_label_block()') < 0 or \
            place.find('self._place_brand()') < \
            place.find('self._place_label_block()'):
        fail.add(rule, 'the name and logos are placed before the names\' '
                 'block they must stop short of')
    if "host.settings.text('reg_heading_mode', u'') or ps_ramp.GREY" not \
            in source:
        fail.add(rule, 'the register\'s headings are not grey by default')
    if 'self.host.take_heading_colours(self.heading_custom)' not in \
            _method_body(source, '_save_heading_colours'):
        fail.add(rule, 'a colour picked on the register misses the '
                 'Selection tab')

    layout = read(os.path.join(root, 'ProSheets.xaml'))
    top_right = re.search(r'<StackPanel Grid\.Row="0" Grid\.RowSpan="2" '
                          r'Grid\.Column="1".*?</StackPanel>\s*</Button>\s*'
                          r'</StackPanel>', layout, re.S)
    top_right = top_right.group(0) if top_right else ''
    search = top_right.find('x:Name="RegisterSearch"')
    if search < 0 or search > top_right.find('x:Name="RegisterSetupButton"'):
        fail.add(rule, 'the search box is not top right, before Settings')
    source_line = re.search(r'<TextBlock x:Name="RegisterSource"[^>]*/>',
                            layout)
    if source_line is None or 'Visibility="Collapsed"' not in \
            source_line.group(0):
        fail.add(rule, 'the words under Settings still show')
    row_one = layout[layout.find('x:Name="RegisterNewSetButton"'):
                     layout.find('<!-- Row two')]
    refresh = _element_text(layout, 'RegisterRefreshButton')
    if 'x:Name="RegisterRefreshButton"' not in row_one or \
            '<Path' not in refresh:
        fail.add(rule, 'Refresh is not where the search was, or has no '
                 'icon')

    stand = _RunStand(ramp)
    run_hex = window.ProSheetsWindow._run_hex
    greys = [run_hex(stand, 0), run_hex(stand, 1)]
    if greys != [ramp.GREYS['dark'][1], ramp.GREYS['dark'][2]]:
        fail.add(rule, 'grey Selection headings are {0}: two greys taking '
                 'turns'.format(greys))
    stand.heading_mode = ramp.CUSTOM
    stand.heading_custom = {u'MECHANICAL': u'#D9B23C'}
    if run_hex(stand, 1) != u'#D9B23C' or \
            run_hex(stand, 2) != ramp.GREYS['dark'][1]:
        fail.add(rule, 'custom Selection headings do not wear the picked '
                 'colour, grey elsewhere')
    stand.heading_mode = ramp.COLOURED
    if run_hex(stand, 1) != u'#173F78':
        fail.add(rule, 'coloured Selection headings lost the trade ramp')
    entries = [action for _text, action in
               window.ProSheetsWindow.heading_menu_entries(stand,
                                                           u'MECHANICAL')]
    if entries != ['swatches', 'custom', 'reset', 'reset_all']:
        fail.add(rule, 'the Selection heading menu offers {0}'
                 .format(entries))
    window_source = read(os.path.join(root, 'ps_window.py'))
    if "self.settings.text('sel_heading_mode', u'') or ps_ramp.GREY" not \
            in window_source:
        fail.add(rule, 'the Selection tab\'s headings are not grey by '
                 'default')
    if "('SelectionHeadingModeButton', self.cycle_heading_mode)," not in \
            window_source:
        fail.add(rule, 'the Selection tab\'s colour button is not wired')
    if 'self._heading_right_click(args)' not in \
            _method_body(window_source, '_header_right_click'):
        fail.add(rule, 'right-clicking a Selection heading offers no colour')
    if 'self.register.take_heading_colours(colours)' not in \
            _method_body(window_source, '_keep_heading_colours'):
        fail.add(rule, 'a colour picked on the Selection tab misses the '
                 'register')
    if 'Style="{DynamicResource HeadingModeButton}"' not in \
            _element_text(layout, 'SelectionHeadingModeButton'):
        fail.add(rule, 'the Selection tab has no heading colour button')


# ==========================================================================
# 1.55.0 - Sheets and Views named apart, the sort remembered, Open sheets
# ==========================================================================

class _Delegate(object):
    """A stand-in whose missing attributes are the class's own methods,
    bound to the stand-in."""
    _cls = None

    def __getattr__(self, name):
        method = getattr(self._cls, name)
        return lambda *args, **kw: method(self, *args, **kw)


def rule_naming_modes(root, fail):
    rule = 'naming_modes'
    naming = _module_under_stubs(root, 'ps_naming', rule, fail)
    window = _window_module(root, rule, fail)
    if naming is None or window is None:
        return
    Rule = naming.Rule
    if naming.default_rules('views') != [Rule(u'View Name')] or \
            naming.default_rules() != naming.default_rules('sheets') or \
            naming.default_rules('sheets')[0].param != u'Sheet Number':
        fail.add(rule, 'Views do not start from the view name, Sheets from '
                 'the number and name')
    # An old profile: one set, under name.
    old = {}
    naming.rules_to_store([Rule(u'Sheet Number', separator=u'_'),
                           Rule(u'Drawing Title')], old)
    sets = naming.rules_by_mode(old)
    if [r.param for r in sets['sheets']] != [u'Sheet Number',
                                             u'Drawing Title'] or \
            [r.param for r in sets['views']] != [u'Sheet Number',
                                                 u'Drawing Title']:
        fail.add(rule, 'a template from before 1.55.0 lost its custom name '
                 'in one of the modes: {0}'.format(sets))
    stock = {}
    naming.rules_to_store(naming.default_rules('sheets'), stock)
    sets = naming.rules_by_mode(stock)
    if sets['views'] != [Rule(u'View Name')] or \
            sets['sheets'] != naming.default_rules('sheets'):
        fail.add(rule, 'a stock template names views by sheet number')
    if naming.rules_by_mode({})['views'] != [Rule(u'View Name')]:
        fail.add(rule, 'no template at all names views by sheet number')
    # Both sets kept apart through a save.
    store = {}
    naming.store_rules_by_mode({'sheets': [Rule(u'Sheet Number')],
                                'views': [Rule(u'View Name', u'V-')]},
                               store)
    back = naming.rules_by_mode(store)
    if back['sheets'] != [Rule(u'Sheet Number')] or \
            back['views'] != [Rule(u'View Name', u'V-')] or \
            store.get('name.rule.1.param') != u'Sheet Number' or \
            store.get('vname.rule.1.param') != u'View Name':
        fail.add(rule, 'the two naming sets do not survive a save apart: '
                 '{0}'.format(sorted(store.items())))
    store = {}
    naming.store_rules_by_mode({'sheets': [Rule(u'A'), Rule(u'B')],
                                'views': [Rule(u'C')]}, store)
    naming.store_rules_by_mode({'sheets': [Rule(u'A')],
                                'views': [Rule(u'C')]}, store)
    if naming.rules_by_mode(store)['sheets'] != [Rule(u'A')]:
        fail.add(rule, 'a removed sheet rule comes back from the old save')

    cls = window.ProSheetsWindow

    class _NameStand(_Delegate):
        _cls = cls

        def __init__(self):
            self.rules = [Rule(u'Sheet Number')]
            self.rules_by_mode = {}

    Rule = window.ps_naming.Rule

    def shape(rules):
        return [(r.param, r.prefix, r.suffix, r.separator) for r in rules]

    stand = _NameStand()
    stand.rules = [Rule(u'Sheet Number')]
    stand._park_rules('sheets')
    stand._adopt_rules('views')
    if shape(stand.rules) != [(u'View Name', u'', u'', u'')]:
        fail.add(rule, 'switching to Views keeps the sheet naming')
    stand.rules = [Rule(u'View Name', suffix=u'-X')]
    stand._park_rules('views')
    stand.rules.append(Rule(u'Typed after'))
    if shape(stand.rules_by_mode['views']) != [
            (u'View Name', u'', u'-X', u'')]:
        fail.add(rule, 'the parked naming is the live list, so an edit '
                 'after a switch leaks into the other mode')
    stand._adopt_rules('sheets')
    if shape(stand.rules) != [(u'Sheet Number', u'', u'', u'')]:
        fail.add(rule, 'switching back to Sheets loses the sheet naming')
    stand._adopt_rules('views')
    if shape(stand.rules) != [(u'View Name', u'', u'-X', u'')]:
        fail.add(rule, 'the views naming is lost switching modes')

    source = read(os.path.join(root, 'ps_window.py'))
    changed = _method_body(source, '_mode_changed')
    if changed.find('self._park_rules(self._other_mode())') < 0 or \
            changed.find('self._park_rules(self._other_mode())') > \
            changed.find('self._read_model()') or \
            'self._adopt_rules(self._mode_name())' not in changed:
        fail.add(rule, 'switching mode does not swap the naming sets')
    collect = _method_body(source, '_collect_profile')
    if collect.find('self._park_rules(self._mode_name())') < 0 or \
            collect.find('self._park_rules(self._mode_name())') > \
            collect.find('ps_naming.store_rules_by_mode(self.rules_by_mode, '
                         'profile)'):
        fail.add(rule, 'a template saves the naming without the mode on '
                 'screen')
    applied = _method_body(source, '_apply_profile')
    if 'self.rules_by_mode = ps_naming.rules_by_mode(profile)' not in \
            applied or 'self._adopt_rules(self._mode_name())' not in applied:
        fail.add(rule, 'a template does not load both naming sets')
    dialog = _method_body(source, 'open_name_dialog')
    if 'self.window, label, mode=mode)' not in dialog or \
            'self._park_rules(mode)' not in dialog:
        fail.add(rule, 'the Custom File Name window does not edit the '
                 'mode on screen only')
    namewin = read(os.path.join(root, 'ps_namewin.py'))
    if "'NameModeText'" not in namewin or \
            'ps_naming.default_rules(self.mode)' not in namewin or \
            "ps_naming.default_rules(getattr(self, 'mode'," not in \
            _method_body(namewin, '_reset'):
        fail.add(rule, 'the Custom File Name window does not say or reset '
                 'to the mode it is naming')
    if 'x:Name="NameModeText"' not in read(
            os.path.join(root, 'ProSheetsCustomName.xaml')):
        fail.add(rule, 'the Custom File Name window has no mode title')


class _SortSettings(object):
    def __init__(self, store=None):
        self.store = dict(store or {})
        self.saves = 0

    def set(self, key, value):
        self.store[key] = u'{0}'.format(value)

    def save(self):
        self.saves += 1


def rule_sort_memory(root, fail):
    rule = 'sort_memory'
    window = _window_module(root, rule, fail)
    if window is None:
        return
    cls = window.ProSheetsWindow

    class _SortStand(_Delegate):
        _cls = cls
        MAX_SORT_LEVELS = cls.MAX_SORT_LEVELS
        SORT_MEMORY = getattr(cls, 'SORT_MEMORY', 'x')
        GROUP_MEMORY = getattr(cls, 'GROUP_MEMORY', 'y')

        def __init__(self, settings, mode='sheets'):
            self.settings = settings
            self.mode = mode
            self.column_order = ['sel', 'num', 'name', 'fname']
            self.sort_stack = []
            self.grouped = True
            self._template_sort = u'Old'

        def _mode_name(self):
            return self.mode

        def c(self, name):
            return None

    settings = _SortSettings()
    stand = _SortStand(settings)
    if stand._restore_sort() or stand._remembered_sort() is not None:
        fail.add(rule, 'a machine that never sorted has a remembered sort')
    stand.sort_stack = [(u'p:Series', False), ('num', True)]
    stand.grouped = False
    if not stand.remember_sort() or not settings.saves or \
            'sel_sort.sheets' not in settings.store:
        fail.add(rule, 'a sort set by hand is not kept on this machine')
    fresh = _SortStand(settings)
    if not fresh._restore_sort() or \
            fresh.sort_stack != [(u'p:Series', False), ('num', True)] or \
            fresh.grouped is not False:
        fail.add(rule, 'the sort and grouping do not come back next time: '
                 '{0} {1}'.format(fresh.sort_stack, fresh.grouped))
    if fresh.column_order != ['sel', 'num', 'name', u'p:Series', 'fname']:
        fail.add(rule, 'a remembered column missing from the list is not '
                 'put back before Custom File Name: {0}'.format(
                     fresh.column_order))
    if fresh._template_sort:
        fail.add(rule, 'the template\'s sort is still announced over the '
                 'remembered one')
    views = _SortStand(settings, 'views')
    if views._remembered_sort() is not None or views._restore_sort():
        fail.add(rule, 'the Sheets sort is remembered for Views as well')
    odd = _SortStand(_SortSettings({'sel_sort.views': u'rev|asc'}), 'views')
    odd.column_order = ['sel', 'name', 'fname']
    if odd._restore_sort() or odd.sort_stack:
        fail.add(rule, 'a remembered column that is not in this mode is '
                 'sorted on anyway')
    fresh.forget_sort()
    if fresh._remembered_sort() is not None:
        fail.add(rule, 'Reset columns does not forget the remembered sort')

    source = read(os.path.join(root, 'ps_window.py'))
    for method, needed, why in (
            ('_on_sorting', 'self.remember_sort()',
             'clicking a heading to sort is not remembered'),
            ('toggle_grouping', 'self.remember_sort()',
             'turning grouping off or on is not remembered'),
            ('toggle_grouping', 'self.sort_stack = [(series, False)]',
             'grouping with nothing sorted does not group on the series'),
            ('reset_columns', 'self.forget_sort()',
             'Reset columns keeps the old sort for next time'),
            ('_adopt_columns', 'if not self._restore_sort(mode):',
             'switching mode does not bring back that mode\'s sort'),
            ('_profile_changed', 'self.remember_sort()',
             'a template picked does not become the sort to open in'),
            ('open_setup', 'series != series_before',
             'a sheet series named in Setup is not grouped on first')):
        if needed not in _method_body(source, method):
            fail.add(rule, why)
    startup = source.find('        if self._restore_sort():\n'
                          '            self._build_columns()\n'
                          '        self._ready = True\n')
    if startup < 0:
        fail.add(rule, 'the window does not open in the remembered sort')


class _OpenView(object):
    def __init__(self, name, refuse=False):
        self.Name = name
        self.refuse = refuse


class _OpenDoc(object):
    def __init__(self):
        self.opened = []
        self._active = None

    @property
    def ActiveView(self):
        return self._active

    @ActiveView.setter
    def ActiveView(self, view):
        if view.refuse:
            raise Exception('no')
        self.opened.append(view.Name)
        self._active = view


class _OpenItems(object):
    def __init__(self, order):
        self.order = order

    def IndexOf(self, item):
        return self.order.index(item)


class _OpenGrid(object):
    def __init__(self, selected, order):
        self.SelectedItems = list(selected)
        self.Items = _OpenItems(order)


class _OpenItem(object):
    def __init__(self, **row):
        self.Row = row


def rule_open_sheets(root, fail):
    rule = 'open_sheets'
    revisions = _module_under_stubs(root, 'ps_revisions', rule, fail)
    view = _module_under_stubs(root, 'ps_regview', rule, fail)
    window = _window_module(root, rule, fail)
    if revisions is None or view is None or window is None:
        return
    uidoc = _OpenDoc()
    got = revisions.open_views(uidoc, [_OpenView(u'A'), _OpenView(u'B'),
                                       _OpenView(u'C', refuse=True), None])
    if got[0] != 2 or len(got[1]) != 1 or uidoc.opened != [u'B', u'A'] or \
            uidoc.ActiveView.Name != u'A':
        fail.add(rule, 'the sheets are not opened with the first in front: '
                 '{0} {1}'.format(got, uidoc.opened))
    if revisions.opened_report(2, [], u'sheet') != u'2 sheets opened.' or \
            revisions.opened_report(1, [], u'view') != u'1 view opened.':
        fail.add(rule, 'Open sheets does not say what it opened')

    cls = window.ProSheetsWindow

    class _Chrome(object):
        def __init__(self):
            self.shrunk = 0

        def shrink(self):
            self.shrunk += 1
            return True

    class _App(object):
        def __init__(self, doc):
            self.ActiveUIDocument = doc

    class _OpenStand(_Delegate):
        _cls = cls

        def __init__(self, views=False):
            self.views = views
            self.chrome = _Chrome()
            self.jobs = []
            self.said = []
            self.exporting = False
            self.grid = None
            self.rows_by_key = {}

        def _is_views_mode(self):
            return self.views

        def _queue(self, job):
            self.jobs.append(job)
            return True

        def _on_ui(self, call):
            call()

        def say(self, text):
            self.said.append(text)

        def c(self, name):
            return self.grid

        def _as_key(self, key):
            return key

    stand = _OpenStand()
    if stand.row_menu_entries(2) != [(u'Open sheets', 'open_highlighted')] \
            or stand.row_menu_entries(1) != [(u'Open sheet',
                                              'open_highlighted')] \
            or stand.row_menu_entries(0):
        fail.add(rule, 'a right-click on highlighted sheets does not offer '
                 'Open sheets')
    if _OpenStand(views=True).row_menu_entries(3) != [
            (u'Open views', 'open_highlighted')]:
        fail.add(rule, 'Views mode offers to open sheets')

    class _Row(object):
        def __init__(self, element):
            self.element = element

    one, two = _Row(_OpenView(u'S1')), _Row(_OpenView(u'S2'))
    first = _OpenItem(key=u'k1', ishead=u'0')
    second = _OpenItem(key=u'k2', ishead=u'0')
    head = _OpenItem(key=u'', ishead=u'1')
    stand.grid = _OpenGrid([second, head, first], [head, first, second])
    # A heading is never a sheet to open, whatever its key finds.
    stand.rows_by_key = {u'k1': one, u'k2': two,
                         u'': _Row(_OpenView(u'Heading'))}
    if stand.highlighted_rows() != [one, two]:
        fail.add(rule, 'the highlighted sheets are not taken top of the '
                 'list first, headings left out')
    if not stand.open_highlighted() or len(stand.jobs) != 1 or \
            stand.chrome.shrunk != 1:
        fail.add(rule, 'Open sheets does not open them and shrink the '
                 'window to the bottom')
    else:
        doc = _OpenDoc()
        stand.jobs[0](_App(doc))
        if doc.opened != [u'S2', u'S1'] or \
                stand.said[-1] != u'2 sheets opened.':
            fail.add(rule, 'the Open sheets job opens {0}'.format(
                doc.opened))
    busy = _OpenStand()
    busy.exporting = True
    if busy.open_sheets([_OpenView(u'X')]) or busy.jobs or \
            busy.chrome.shrunk:
        fail.add(rule, 'Open sheets takes the event from a running export')
    empty = _OpenStand()
    if empty.open_sheets([]) or empty.jobs or empty.chrome.shrunk:
        fail.add(rule, 'Open sheets with nothing highlighted shrinks the '
                 'window anyway')

    # The register: the same, through the host.
    class _Host(object):
        def __init__(self):
            self.calls = []

        def open_sheets(self, views, word=u'sheet'):
            self.calls.append(([v.Name for v in views], word))
            return True

    class _RegStand(_Delegate):
        _cls = view.RegisterView

        def __init__(self):
            self.host = _Host()
            self.elements = {u'a': _OpenView(u'A1'), u'b': _OpenView(u'B1'),
                             u'issue:status': _OpenView(u'Issue')}

    reg = _RegStand()
    row_a = _OpenItem(key=u'a', ishead=u'0')
    row_b = _OpenItem(key=u'b', ishead=u'0')
    issue = _OpenItem(key=u'issue:status', ishead=u'0')
    reg.grid = _OpenGrid([row_b, issue, row_a], [issue, row_a, row_b])
    if not reg.open_sheets() or reg.host.calls != [([u'A1', u'B1'],
                                                    u'sheet')]:
        fail.add(rule, 'the register\'s Open sheets does not open the '
                 'highlighted drawings: {0}'.format(reg.host.calls))

    source = read(os.path.join(root, 'ps_window.py'))
    if 'self._row_right_click(row, args)' not in \
            _method_body(source, '_heading_right_click'):
        fail.add(rule, 'a right-click on a sheet in Selection opens no menu')
    click = _method_body(source, '_row_right_click')
    if 'grid.SelectedItems.Add(row.Item)' not in click or \
            'if row is not None and not bool(row.IsSelected):' not in click:
        fail.add(rule, 'a right-click on a sheet not highlighted acts on the '
                 'old highlight')


# ==========================================================================
# 1.56.0 - Express Export from the Selection tab
# ==========================================================================

class _ExpressReport(object):
    def __init__(self, failed=(), folders=(u'C:\\out',)):
        self._failed = list(failed)
        self._folders = list(folders)
        self.debug_path = u''

    def summary(self):
        return u'5 files written.'

    def failed(self):
        return list(self._failed)

    def folders(self):
        return list(self._folders)


class _ExpressOutcome(object):
    def __init__(self, label, fmt):
        self.label = label
        self.fmt = fmt


def rule_express_export(root, fail):
    rule = 'express_export'
    window = _window_module(root, rule, fail)
    if window is None:
        return
    cls = window.ProSheetsWindow
    holder = tempfile.mkdtemp(prefix='express_check_')
    blocked_file = os.path.join(holder, 'a_file')
    open(blocked_file, 'w').close()

    class _ExpressStand(_Delegate):
        _cls = cls
        TAB_SELECTION = cls.TAB_SELECTION
        TAB_CREATE = cls.TAB_CREATE

        def __init__(self, jobs=(u'A101',), formats=('pdf',), alone=False,
                     root_folder=None, blocker=u''):
            self.exporting = False
            self._express_run = False
            self.jobs = list(jobs)
            self.formats = list(formats)
            self.alone = alone
            self.root_folder = holder if root_folder is None \
                else root_folder
            self.blocker = blocker
            self.calls = []
            self.said = []
            self.printer_list = []
            self.uiapp = None

        def plan_jobs(self):
            return list(self.jobs), {}

        def chosen_formats(self):
            return list(self.formats)

        def register_alone(self, jobs):
            return self.alone and not jobs

        def _text_of(self, name):
            return self.root_folder if name == 'RootFolderBox' else u''

        def _pdf_blocker(self, formats):
            return self.blocker

        def _printer_changed(self, sender, args):
            self.calls.append(('printer',))

        def _collect_profile(self):
            return {'p': '1'}

        def _launch_export(self, jobs, formats, profile, quiet):
            self.calls.append(('launch', jobs, formats, profile, quiet,
                               self._express_run))

        def _start_register_alone(self):
            self.calls.append(('alone', self._express_run))

        def _is_views_mode(self):
            return False

        def say(self, text):
            self.said.append(text)

        def c(self, name):
            return None

        def _end_progress(self):
            self.calls.append(('end',))

        def _write_debug_log(self):
            return u'log.txt'

        def _flag_of(self, name, default=False):
            return self.calls.append(('flag', name)) or True

        def folder_to_open(self, report):
            return u'C:\\issue'

    try:
        stand = _ExpressStand()
        if not stand.express_export() or not stand.calls or \
                stand.calls[-1] != ('launch', [u'A101'], ['pdf'],
                                    {'p': '1'}, True, True):
            fail.add(rule, 'Express Export does not start the run quietly '
                     'with the template\'s settings: {0}'.format(stand.calls))
        for maker, why, word in (
                (lambda: _ExpressStand(jobs=()), 'nothing ticked', u'tick'),
                (lambda: _ExpressStand(formats=()), 'no format', u'tick'),
                (lambda: _ExpressStand(root_folder=u''), 'no root folder',
                 u'no root folder'),
                (lambda: _ExpressStand(
                    root_folder=os.path.join(blocked_file, 'sub')),
                 'a folder that cannot be written', u'cannot be written')):
            stand = maker()
            if stand.express_export() or stand.calls or not stand.said or \
                    word not in stand.said[-1] or stand._express_run:
                fail.add(rule, 'Express Export starts a run with {0}, or '
                         'stops without saying why'.format(why))
        stand = _ExpressStand(blocker=u'no staging folder')
        if not stand.express_export() or ('printer',) not in stand.calls \
                or stand.calls[-1][0] != 'launch' or \
                u'Revit\'s own exporter' not in u' '.join(stand.said):
            fail.add(rule, 'a print driver with nowhere to collect from '
                     'stops Express Export instead of switching to Revit\'s '
                     'own exporter: {0}'.format(stand.calls))
        stand = _ExpressStand(jobs=(), alone=True)
        if not stand.express_export() or stand.calls != [('alone', True)]:
            fail.add(rule, 'Express Export does not write the register on '
                     'its own: {0}'.format(stand.calls))
        busy = _ExpressStand()
        busy.exporting = True
        if busy.express_export() or busy.calls:
            fail.add(rule, 'Express Export starts a second run over one '
                     'already going')

        # The end: no report window.
        opened = []
        saved_open = window.ps_export.open_folder
        window.ps_export.open_folder = lambda path, *a: opened.append(path)
        try:
            stand = _ExpressStand()
            stand._express_run = True
            stand._show_report(_ExpressReport(
                failed=[_ExpressOutcome(u'A101', u'pdf')]))
            if stand._express_run or ('end',) not in stand.calls or \
                    opened != [u'C:\\issue'] or not stand.said or \
                    u'A101 [pdf]' not in stand.said[-1] or \
                    u'5 files written.' not in stand.said[-1]:
                fail.add(rule, 'an Express Export does not finish on the '
                         'status line, opening the folder: {0} {1} {2}'
                         .format(stand.calls, opened, stand.said))
            del opened[:]
            stand = _ExpressStand()
            stand._express_run = True
            stand._show_report(_ExpressReport(folders=()))
            if opened:
                fail.add(rule, 'an Express Export that wrote nothing opens '
                         'a folder')
        finally:
            window.ps_export.open_folder = saved_open
    finally:
        shutil.rmtree(holder, ignore_errors=True)

    source = read(os.path.join(root, 'ps_window.py'))
    if "('ExpressExportButton', self.express_export)," not in \
            _method_body(source, '_wire'):
        fail.add(rule, 'the Express Export button does nothing')
    if 'self._express_run = False' not in _method_body(source,
                                                       'start_export'):
        fail.add(rule, 'a full Export after an Express one that never ran '
                 'stays silent')
    if "if not getattr(self, '_express_run', False):\n" \
            "            self._set_tab(self.TAB_CREATE)" not in \
            _method_body(source, '_begin_progress'):
        fail.add(rule, 'Express Export jumps to the Create tab')
    for method in ('_begin_progress', '_end_progress'):
        if "'ExpressExportButton'" not in _method_body(source, method):
            fail.add(rule, 'the Express Export button is not held off '
                     'while a run is going')
    if "ps_ui.set_visible(self.c('ExpressExportButton'),\n" \
            "                          index == self.TAB_SELECTION)" not in \
            _method_body(source, '_say_step'):
        fail.add(rule, 'the Express Export button is not on the Selection '
                 'tab only')
    alone = _method_body(source, '_start_register_alone')
    if "if getattr(self, '_express_run', False):\n" \
            "            ps_export.begin_suppression(self.uiapp)" not in alone:
        fail.add(rule, 'an Express Export of the register alone lets '
                 'Revit\'s dialogs through')
    layout = read(os.path.join(root, 'ProSheets.xaml'))
    express = re.search(r'<Button x:Name="ExpressExportButton".*?</Button>',
                        layout, re.S)
    express = express.group(0) if express else u''
    if not express or 'Style="{DynamicResource PrimaryButton}"' not in \
            express or '<Path ' not in express or \
            'Text="Express Export"' not in express:
        fail.add(rule, 'there is no green Express Export button with a '
                 'printer in it')
    elif layout.find('x:Name="ExpressExportButton"') > \
            layout.find('<Button x:Name="BackButton"') or \
            layout.find('<Button x:Name="BackButton"') - \
            layout.find('</Button>', layout.find(
                'x:Name="ExpressExportButton"')) > 40:
        fail.add(rule, 'Express Export is not just left of Back')


# ==========================================================================
# 1.56.1 - the footer's buttons always whole
# ==========================================================================

class _SettleControl(object):
    def __init__(self, log, name):
        self.log = log
        self.name = name

    def InvalidateMeasure(self):
        self.log.append(('measure', self.name))


class _SettleEvent(object):
    def __init__(self, log):
        self.log = log

    def __iadd__(self, handler):
        self.log.append(('subscribe',))
        return self

    def __isub__(self, handler):
        self.log.append(('unsubscribe',))
        return self


class _SettleWindow(object):
    def __init__(self, log):
        self.log = log
        self.Content = _SettleControl(log, 'content')
        self.ContentRendered = _SettleEvent(log)

    def UpdateLayout(self):
        self.log.append(('layout',))


def rule_footer_layout(root, fail):
    rule = 'footer_layout'
    layout = read(os.path.join(root, 'ProSheets.xaml'))
    footer = re.search(r'<DockPanel x:Name="FooterDock".*?</DockPanel>',
                       layout, re.S)
    footer = footer.group(0) if footer else u''
    if not footer or 'LastChildFill="True"' not in footer:
        fail.add(rule, 'the footer is not a DockPanel with the status line '
                 'filling what is left')
        return
    buttons = footer.find('<StackPanel x:Name="FooterButtons" '
                          'DockPanel.Dock="Right"')
    status = footer.find('<StackPanel x:Name="FooterStatus"')
    if buttons < 0 or status < 0 or status < buttons or \
            footer.find('x:Name="BackButton"') < buttons or \
            footer.find('x:Name="NextButton"') > status:
        fail.add(rule, 'Back and Next are not docked right ahead of the '
                 'status line, so they can be squeezed off the end')
    if 'ColumnDefinition Width="*"' in footer[:status] or \
            'Grid.Column=' in footer[:status]:
        fail.add(rule, 'the footer\'s buttons sit in a star/Auto Grid again')
    text = re.search(r'<TextBlock x:Name="StatusText".*?/>', footer, re.S)
    if text is None or 'TextTrimming="CharacterEllipsis"' not in \
            text.group(0):
        fail.add(rule, 'a long status line can push the buttons out')

    window = _window_module(root, rule, fail)
    if window is None:
        return
    source = read(os.path.join(root, 'ps_window.py'))
    init = _method_body(source[source.find('class ProSheetsWindow'):],
                        '__init__')
    if 'self.window.ContentRendered += self._settle_layout' not in init:
        fail.add(rule, 'the window is not laid out again once it is drawn')
    cls = window.ProSheetsWindow

    class _SettleStand(_Delegate):
        _cls = cls

        def __init__(self):
            self.log = []
            self.window = _SettleWindow(self.log)
            self.ui = {'FooterButtons': _SettleControl(self.log, 'buttons'),
                       'FooterDock': _SettleControl(self.log, 'dock')}

        def c(self, name):
            return self.ui.get(name)

    stand = _SettleStand()
    stand._settle_layout()
    log = stand.log
    if ('unsubscribe',) not in log or ('measure', 'buttons') not in log or \
            ('measure', 'content') not in log or log[-1] != ('layout',):
        fail.add(rule, 'the settling pass does not measure the footer and '
                 'the window again, once: {0}'.format(log))


RULES = [
    ('xaml_parses', rule_xaml_parses),
    ('thin_loader', rule_thin_loader),
    ('refs_first', rule_refs_first),
    ('assemblies_referenced', rule_assemblies_referenced),
    ('resources', rule_resources),
    ('style_targets', rule_style_targets),
    ('find_names', rule_find_names),
    ('python_dialect', rule_python_dialect),
    ('ascii', rule_ascii),
    ('palettes', rule_palettes),
    ('no_duplicate_methods', rule_no_duplicate_methods),
    ('init_attributes', rule_init_attributes),
    ('modules_load', rule_modules_load),
    ('naming_behaviour', rule_naming_behaviour),
    ('paper_sizing', rule_paper_sizing),
    ('egg_arming', rule_egg_arming),
    ('template_bundles', rule_template_bundles),
    ('grid_placement', rule_grid_placement),
    ('format_registry', rule_format_registry),
    ('mode_columns', rule_mode_columns),
    ('context_menu_gate', rule_context_menu_gate),
    ('context_menu_host', rule_context_menu_host),
    ('shared_files', rule_shared_files),
    ('known_printers', rule_known_printers),
    ('value_runs', rule_value_runs),
    ('theme_modes', rule_theme_modes),
    ('selection_chrome', rule_selection_chrome),
    ('group_colours', rule_group_colours),
    ('group_ticks', rule_group_ticks),
    ('sort_groups', rule_sort_groups),
    ('module_calls', rule_module_calls),
    ('print_outside_transaction', rule_print_outside_transaction),
    ('register_logic', rule_register_logic),
    ('register_view', rule_register_view),
    ('tab_indices', rule_tab_indices),
    ('export_ticked', rule_export_ticked),
    ('register_ticks', rule_register_ticks),
    ('register_xlsx', rule_register_xlsx),
    ('sheet_sets', rule_sheet_sets),
    ('pdf_default', rule_pdf_default),
    ('issue_folder', rule_issue_folder),
    ('int_precision', rule_int_precision),
    ('revision_manager', rule_revision_manager),
    ('revision_columns', rule_revision_columns),
    ('revision_button', rule_revision_button),
    ('revision_series', rule_revision_series),
    ('revision_filters', rule_revision_filters),
    ('api_version_imports', rule_api_version_imports),
    ('revision_modeless', rule_revision_modeless),
    ('register_picks', rule_register_picks),
    ('revision_add', rule_revision_add),
    ('revision_sheets', rule_revision_sheets),
    ('register_tools', rule_register_tools),
    ('register_staging', rule_register_staging),
    ('register_tidp', rule_register_tidp),
    ('express_print', rule_express_print),
    ('heading_ramps', rule_heading_ramps),
    ('shrink_drawer', rule_shrink_drawer),
    ('revit_dark', rule_revit_dark),
    ('register_issue_block', rule_register_issue_block),
    ('heading_modes', rule_heading_modes),
    ('register_issue_rows', rule_register_issue_rows),
    ('register_brand', rule_register_brand),
    ('naming_modes', rule_naming_modes),
    ('sort_memory', rule_sort_memory),
    ('open_sheets', rule_open_sheets),
    ('express_export', rule_express_export),
    ('footer_layout', rule_footer_layout),
]


def run(root=HERE, quiet=False):
    fail = Failures()
    for name, rule in RULES:
        try:
            rule(root, fail)
        except Exception as err:
            fail.add(name, 'the rule itself threw: {0}: {1}'
                     .format(err.__class__.__name__, err))
    if not quiet:
        _say('RevoBIM Pro Sheets Exporter : bench check')
        _say('=' * 58)
        if not fail.items:
            _say('{0} rules, nothing to report.'.format(len(RULES)))
        else:
            current = None
            for rule_name, text in fail.items:
                if rule_name != current:
                    current = rule_name
                    _say('')
                    _say('[{0}]'.format(rule_name))
                _say('  ' + text)
            _say('')
            _say('{0} problem(s) across {1} rule(s).'
                 .format(len(fail), len(fail.rules_hit())))
    return fail


def _say(text):
    sys.stdout.write(u'{0}\n'.format(text))


# ==========================================================================
# the selftest : break each rule and confirm it fires
# ==========================================================================

def _copy_tool():
    """The tool folder copied, with its sibling buttons beside it.

    The Revision Manager has a ribbon button of its own next to this
    folder, and its rule looks there - so the copy keeps the same shape:
    <temp>\\Pro Sheets Exporter.pushbutton plus its siblings.
    """
    holder = tempfile.mkdtemp(prefix='prosheets_check_')
    target = os.path.join(holder, os.path.basename(HERE))
    os.makedirs(target)
    for name in os.listdir(HERE):
        source = os.path.join(HERE, name)
        if os.path.isfile(source):
            shutil.copy2(source, os.path.join(target, name))
    for sibling in SIBLING_BUTTONS:
        source = os.path.join(os.path.dirname(HERE), sibling)
        if os.path.isdir(source):
            shutil.copytree(source, os.path.join(holder, sibling),
                            ignore=shutil.ignore_patterns('__pycache__'))
    return target


def _discard(root):
    holder = os.path.dirname(root)
    if os.path.basename(holder).startswith('prosheets_check_'):
        shutil.rmtree(holder, ignore_errors=True)
    else:
        shutil.rmtree(root, ignore_errors=True)


def _write(root, name, text):
    handle = open(os.path.join(root, name), 'wb')
    try:
        handle.write(text.encode('utf-8'))
    finally:
        handle.close()


def _patch(root, name, old, new, count=1):
    path = os.path.join(root, name)
    text = read(path)
    if old not in text:
        raise Exception('selftest could not find the text to break in ' + name)
    # A replace without a count hits every match, which is its own bug.
    text = text.replace(old, new, count)
    handle = open(path, 'wb')
    try:
        handle.write(text.encode('utf-8'))
    finally:
        handle.close()


BREAKAGES = [
    # The default sort given up on when the column is missing, which
    # is a template from last week opening unsorted for no visible
    # reason.
    ('mode_columns',
     lambda root: _patch(root, 'ps_window.py',
                         "        if series not in self.column_order:\n            order = list(self.column_order)",
                         "        if series not in self.column_order:\n            return False\n        if False:\n            order = list(self.column_order)")),
    # The parameter columns put on the end, after Custom File Name.
    ('mode_columns',
     lambda root: _patch(root, 'ps_window.py',
                         "        where = order.index('fname') if 'fname' in order else len(order)\n        return order[:where] + wanted + order[where:]",
                         "        return order + wanted")),
    # Sheet parameters pushed onto the Views list too, where nothing
    # has a value for any of them.
    ('mode_columns',
     lambda root: _patch(root, 'ps_window.py',
                         "            extras = browser\n",
                         "            pass\n")),
    # A row allowed to go back to green after a failure, so a sheet
    # whose PDF never appeared reads as written because its DWG did.
    ('group_ticks',
     lambda root: _patch(root, 'ps_window.py',
                         "        if u'{0}'.format(was) == 'failed':\n            return 'failed'\n        return 'done' if good else 'failed'",
                         "        return 'done' if good else 'failed'")),
    # A row style handed to the wrong kind of property. RowStyle wants
    # a DataGridRow style; giving it a cell one throws at load.
    ('style_targets',
     lambda root: _patch(root, 'ProSheets.xaml',
                         'RowStyle="{DynamicResource PlanRow}"',
                         'RowStyle="{DynamicResource GridCell}"')),
    # The old fifteen second wait, which gave up while the driver was
    # still converting an A0.
    ('print_outside_transaction',
     lambda root: _patch(root, 'ps_export.py',
                         'def driver_wait_budget(render_seconds, floor=60.0, ceiling=420.0):',
                         'def driver_wait_budget(render_seconds, floor=15.0, ceiling=15.0):')),
    # The transaction put back around the submit, which is the bug that
    # printed nothing on two machines while reporting no error.
    ('print_outside_transaction',
     lambda root: _patch(root, 'ps_export.py',
                         "            try:\n                started = time.time()\n                manager.SubmitPrint(job.view)",
                         "            transaction.Start()\n            try:\n                started = time.time()\n                manager.SubmitPrint(job.view)\n                transaction.Commit()")),
    # Folder comparison built on the running platform's path rules,
    # which passes on the bench and fails on the machine.
    ('naming_behaviour',
     lambda root: _patch(root, 'ps_paths.py',
                         "    text = u'{0}'.format(path or u'').strip().replace(u'/', u'\\\\')",
                         "    text = u'{0}'.format(path or u'').strip()")),
    # A template's driver obeyed on a machine that has never been told
    # where that driver saves, which is a run that cannot write a file.
    ('known_printers',
     lambda root: _patch(root, 'ps_window.py',
                         "        if not u'{0}'.format(staging or u'').strip():\n            return u'', name, 'no-folder'\n        return name, u'', u''",
                         "        return name, u'', u''")),
    # The house default ignored, so a shared template drags a whole
    # team back onto a print driver nobody chose.
    ('known_printers',
     lambda root: _patch(root, 'ps_window.py',
                         "        if prefer_native:\n            return u'', name, 'prefer-native'",
                         "        if False:\n            return u'', name, 'prefer-native'")),
    # The run allowed to start with a driver and no staging folder,
    # which is how a first time user gets "no file appeared" once per
    # sheet and nothing pointing at the cause.
    ('known_printers',
     lambda root: _patch(root, 'ps_window.py',
                         "        return not u'{0}'.format(staging or u'').strip()",
                         "        return False")),
    # The one that shipped: a helper that does not exist, called from a
    # branch that only runs on a button press.
    ('module_calls',
     lambda root: _patch(root, 'ps_setupwin.py',
                         'theme_name=self.theme_name, owner=self.window).show()',
                         'theme_name=ps_ui.theme_of(self.window),\n'
                         '            owner=self.window).show()')),
    # A tick reaching every highlighted row whether or not the row
    # ticked was one of them, so a tick anywhere drags in a block
    # highlighted for something else entirely.
    ('group_ticks',
     lambda root: _patch(root, 'ps_window.py',
                         '        if key in picked and len(picked) > 1:',
                         '        if len(picked) > 1:')),
    # Sorting no longer turns grouping back on.
    ('sort_groups',
     lambda root: _patch(root, 'ps_window.py',
                         '        self._ensure_grouped()\n\n        self._apply_order()',
                         '        self._apply_order()')),
    # The collapsed set carried across a sort, shutting groups in the
    # new sort that have nothing to do with what was shut in the old.
    ('sort_groups',
     lambda root: _patch(root, 'ps_window.py',
                         '        self.collapsed = set()\n        self._ensure_grouped()',
                         '        self._ensure_grouped()')),
    # The suppression flag left on, which quietly kills the tick box.
    ('sort_groups',
     lambda root: _patch(root, 'ps_window.py',
                         '        finally:\n            self._suspend_group_toggle = False\n        return True',
                         '        return True')),
    # Two formats wearing the same mark, which is what a copied tile
    # looks like when nobody changes the drawing.
    ('format_registry',
     lambda root: _patch(
         root, 'ProSheets.xaml',
         '<Rectangle Canvas.Left="6" Canvas.Top="15" Width="11" Height="11"\n'
         '                   Stroke="#FFFFFF" StrokeThickness="1.5"/>\n'
         '        <Rectangle Canvas.Left="13" Canvas.Top="21" Width="13" Height="12"\n'
         '                   Fill="{DynamicResource FmtNwcInk}"\n'
         '                   Stroke="#FFFFFF" StrokeThickness="1.5"/>',
         '<Rectangle Canvas.Left="7" Canvas.Top="16" Width="18" Height="3"\n'
         '                   RadiusX="1.5" RadiusY="1.5" Fill="#FFFFFF"/>\n'
         '        <Rectangle Canvas.Left="7" Canvas.Top="22" Width="18" Height="3"\n'
         '                   RadiusX="1.5" RadiusY="1.5" Fill="#FFFFFF"/>\n'
         '        <Rectangle Canvas.Left="7" Canvas.Top="28" Width="12" Height="3"\n'
         '                   RadiusX="1.5" RadiusY="1.5" Fill="#FFFFFF"/>')),
    # The tick box swallowed into a collapse again, which is the whole
    # of the 1.11.1 fault.
    ('group_ticks',
     lambda root: _patch(root, 'ps_window.py',
                         'return bool(grouped and on_heading and not on_checkbox)',
                         'return bool(grouped and on_heading)')),
    # A heading tick that stops at the rows you can see, so collapsing a
    # group and ticking it quietly leaves most of it unticked.
    ('group_ticks',
     lambda root: _patch(root, 'ps_window.py',
                         "            for entry in members:\n"
                         "                # Hidden members included. A collapsed group is still a\n"
                         "                # group, and ticking its heading meaning \"all but the\n"
                         "                # ones you cannot see\" would be a trap.\n"
                         "                entry['sel'] = wanted",
                         "            for entry in members:\n"
                         "                if u'{0}'.format(entry['show']) != '1':\n"
                         "                    continue\n"
                         "                entry['sel'] = wanted")),
    # A heading that lights up when any member is ticked rather than all
    # of them, which says the group is ticked when it is not.
    ('group_ticks',
     lambda root: _patch(root, 'ps_window.py',
                         "                whole = bool(members) and all(\n"
                         "                    [bool(member['sel']) for member in members])",
                         "                whole = bool(members) and any(\n"
                         "                    [bool(member['sel']) for member in members])")),
    # Heading band louder than the cell, which puts blue heading text on
    # a saturated green and makes the labels unreadable.
    ('group_colours',
     lambda root: _patch(root, 'theme.py',
                         "    'dark':  (0.42, 0.36, 0.17),",
                         "    'dark':  (0.42, 0.36, 0.44),")),
    # Too few hues, so a discipline column runs out of colours early.
    ('group_colours',
     lambda root: _patch(root, 'theme.py',
                         'GROUP_HUES = 12', 'GROUP_HUES = 4')),
    # The heading trigger gone from the cell style: the blue would be set
    # on the row and never reach the text, because the cell style sets
    # Foreground explicitly.
    ('group_colours',
     lambda root: _patch(root, 'Theme.xaml',
                         '<DataTrigger Binding="{Binding ishead}" Value="1">',
                         '<DataTrigger Binding="{Binding nothing}" Value="1">')),
    # Exactly the 1.10.0 fault: clearing CellStyle on the columns that are
    # not the sorted one, which lands as a local null on every cell and
    # drops them to OS chrome - a white bar on the selected row.
    ('selection_chrome',
     lambda root: _patch(root, 'ps_window.py',
                         "                style = grouped if col_id == wanted else plain\n"
                         "                # Never assign the null a failed lookup returns; leaving\n"
                         "                # the property untouched keeps the implicit style.\n"
                         "                if style is not None:\n"
                         "                    column.CellStyle = style",
                         "                if col_id == wanted:\n"
                         "                    column.CellStyle = grouped\n"
                         "                else:\n"
                         "                    column.CellStyle = None")),
    # The 1.6.0 fault: a resource lookup assigned straight to Style, which
    # is a local null whenever the key is missing.
    ('selection_chrome',
     lambda root: _patch(root, 'ps_window.py',
                         "            element.SetResourceReference(FrameworkElement.StyleProperty, key)",
                         "            element.Style = element.TryFindResource(key)")),
    # No SystemColors override, so an unfocused selection goes near white.
    ('selection_chrome',
     lambda root: _patch(root, 'theme.py',
                         "        ('InactiveSelectionHighlightBrushKey', 'SelectionBrush'),\n",
                         '')),
    # Single values left without a heading, so they are the one kind of
    # group that cannot be collapsed.
    ('value_runs',
     lambda root: _patch(root, 'ps_window.py',
                         '    MIN_RUN = 1', '    MIN_RUN = 2')),
    # An off by one in where a run starts. The members are taken as
    # sorted_rows[start:start + count], so every group takes the row
    # above the one it should.
    ('value_runs',
     lambda root: _patch(root, 'ps_window.py',
                         '                runs.append([label, index, 1])',
                         '                runs.append([label, index - 1, 1])')),
    # Runs built from distinct values rather than touching ones, so a
    # value that comes back later swallows everything between.
    ('value_runs',
     lambda root: _patch(root, 'ps_window.py',
                         "            if runs and runs[-1][0] == label:",
                         "            if runs and label in [r[0] for r in runs]:")),
    # The 1.9.1 behaviour: saving the resolved palette instead of the
    # chosen mode, so one click on the chip stops it following for good.
    ('theme_modes',
     lambda root: _patch(root, 'ps_window.py',
                         "            self.settings.set('theme_mode', self.theme_mode)",
                         "            self.settings.set('theme_mode', self.theme_name)")),
    ('theme_modes',
     lambda root: _patch(root, 'theme.py',
                         "    return text if text in MODES else 'follow'",
                         "    return text if text in MODES else 'dark'")),
    # Too greedy: a plain PDF24 printer announced as one that does not
    # prompt, which is the advice that wastes an afternoon.
    ('known_printers',
     lambda root: _patch(root, 'ps_export.py',
                         "    ('dirootsprosheets',", "    ('pdf',")),
    # Too strict: the dot in the printer name taken literally, so the
    # driver is never found and the machine quietly stays on the built-in
    # exporter.
    ('known_printers',
     lambda root: _patch(root, 'ps_export.py',
                         "def _token(text):\n    return re.sub(r'[^a-z0-9]', '', u'{0}'.format(text or u'').lower())",
                         "def _token(text):\n    return u'{0}'.format(text or u'').lower()")),
    # A 2025-only name at the top of ps_context: on Revit 2024 that import
    # throws at load and takes the shared startup.py, and every tool in the
    # extension, down with it.
    ('context_menu_gate',
     lambda root: _patch(root, 'ps_context.py',
                         'import ps_config\n',
                         'import ps_config\nfrom Autodesk.Revit.UI import IContextMenuCreator\n')),
    ('context_menu_gate',
     lambda root: _patch(root, 'ps_context.py',
                         'MIN_VERSION = 2025', 'MIN_VERSION = 2024')),
    # Resolving the command once instead of on every right click: the
    # entry works until somebody reloads pyRevit, then silently stops.
    ('context_menu_gate',
     lambda root: _patch(root, 'ps_context.py',
                         '    resolved = resolve_command()',
                         '    resolved = _RESOLVED_ONCE')),
    # Exactly the 1.18.1 fault: one assumed object asked whether it has the
    # method, so Revit 2025 - where only UIApplication has it - goes
    # dormant on the release the feature was built for.
    ('context_menu_host',
     lambda root: _patch(root, 'ps_context.py',
                         "    host, index = pick_host(live)\n"
                         "    if host is None:",
                         "    host, index = (None, -1)\n"
                         "    if not hasattr(uiapp, 'RegisterContextMenu'):")),
    # register() narrowed back to a single argument, which leaves the
    # fragment no way to offer an alternative.
    ('context_menu_host',
     lambda root: _patch(root, 'ps_context.py',
                         'def register(*candidates):',
                         'def register(uiapp):')),
    # The deferred route dropped, so a 2025 handed only a
    # UIControlledApplication has nowhere left to go.
    ('context_menu_host',
     lambda root: _patch(root, 'ps_context.py',
                         '                deferred, detail = _defer(candidate)',
                         '                deferred, detail = (False, u"")')),
    # Detaching the handler from IronPython, which does not reliably find
    # the same one again.
    ('context_menu_host',
     lambda root: _patch(root, 'ps_context.py',
                         '        controlled.ApplicationInitialized += _on_initialised',
                         '        controlled.ApplicationInitialized += _on_initialised\n'
                         '        controlled.ApplicationInitialized -= _on_initialised')),
    # The label Drew asked for, put back to what shipped before it.
    ('context_menu_host',
     lambda root: _patch(root, 'ps_context.py',
                         "ITEM_TEXT = u'Print in ProSheets'",
                         "ITEM_TEXT = u'Print Selected'")),
    # The fragment offering only the object that does NOT have the method
    # on 2025 - which is how this went unnoticed for nine releases.
    ('context_menu_host',
     lambda root: _patch(root, 'startup_fragment.py',
                         "    for _rb_name in ('__revit__', '__uicontrolledapplication__'):",
                         "    for _rb_name in ('__uicontrolledapplication__',):")),
    # Registering from the running tool, which accepts the call but never
    # gets BuildContextMenu called back.
    ('context_menu_host',
     lambda root: _patch(root, 'ps_context.py',
                         '        version = host_version(uiapp)\n'
                         '        if version and version < MIN_VERSION:',
                         '        uiapp.RegisterContextMenu(ADDIN_ID, _creator())\n'
                         '        version = host_version(uiapp)\n'
                         '        if version and version < MIN_VERSION:')),
    # The fragment stripped of its own fallback log, which is what made a
    # misplaced block on Revit 2026 indistinguishable from no block.
    ('context_menu_host',
     lambda root: _patch(root, 'startup_fragment.py',
                         '    def _rb_note(_rb_text):', '    def _rb_quiet(_rb_text):')),
    # The folder walk replaced by the old single assumed location.
    ('context_menu_host',
     lambda root: _patch(root, 'startup_fragment.py',
                         "        _rb_walk = _rb_os.path.dirname(_rb_walk)",
                         "        pass")),
    # ---------------------------------------------------- 1.20.0
    # The minority letter winning a mixed column.
    ('register_logic',
     lambda root: _patch(root, 'ps_register.py',
                         "key=lambda item: (-item[1], item[0]))",
                         "key=lambda item: (item[1], item[0]))")),
    # Series sorted alphabetically - the Drawing Register's first mistake.
    ('register_logic',
     lambda root: _patch(root, 'ps_register.py',
                         "    groups = [(value, members[value]) for value in order]",
                         "    groups = [(value, members[value]) for value in sorted(order)]")),
    # The unfinished sheets leading the register.
    ('register_logic',
     lambda root: _patch(root, 'ps_register.py',
                         "        groups.append((blank_label, blanks))",
                         "        groups.insert(0, (blank_label, blanks))")),
    # Every revision on every tab, forty empty columns across Mechanical.
    ('register_logic',
     lambda root: _patch(root, 'ps_register.py',
                         "    return [column for column in ordered if column.key in used]",
                         "    return ordered")),
    # The cell no longer what the sheet prints.
    ('register_logic',
     lambda root: _patch(root, 'ps_register.py',
                         "        shown = sheet.GetRevisionNumberOnSheet(revision_id)",
                         "        shown = None")),
    # "rev" and "rdate" mistaken for revision columns.
    ('register_logic',
     lambda root: _patch(root, 'ps_register.py',
                         "            and text[len(COLUMN_PREFIX):].lstrip('-').isdigit())",
                         "            )")),
    # Two scales on a sheet reported as the first one found.
    ('register_logic',
     lambda root: _patch(root, 'ps_register.py',
                         "    if len(distinct) > 1:\n        return u'As Shown'",
                         "    if len(distinct) > 1:\n        return u'1:{0}'.format(min(distinct))")),
    # The 1.19.2 numbers, after the register went in second.
    ('tab_indices',
     lambda root: _patch(root, 'ps_window.py',
                         "        ps_ui.set_visible(nxt, index < self.TAB_CREATE)",
                         "        ps_ui.set_visible(nxt, index < 2)")),
    ('tab_indices',
     lambda root: _patch(root, 'ps_window.py',
                         "        self._set_tab(self.TAB_CREATE)\n",
                         "        self._set_tab(2)\n")),
    ('tab_indices',
     lambda root: _patch(root, 'ps_window.py',
                         "    TAB_CREATE = 3", "    TAB_CREATE = 2")),
    # The pre-1.20.0 export: only what the filter leaves on screen.
    ('export_ticked',
     lambda root: _patch(root, 'ps_window.py',
                         "            entries = self.table.Select(u'', u'[ord] ASC')",
                         "            entries = [item.Row for item in self.table.DefaultView]")),
    # ---------------------------------------------------- 1.21.0
    # The 1.20.0 bridge back: a register tick written into the print ticks.
    ('register_view',
     lambda root: _patch(root, 'ps_regview.py',
                         "        self._sync_headings()\n        self._save_by_hand()",
                         "        self._sync_headings()\n        self.host.tick_sheets(keys, wanted)\n        self._save_by_hand()")),
    # Unticking re-filters, so the row vanishes under the cursor.
    ('register_view',
     lambda root: _patch(root, 'ps_regview.py',
                         "        self._sync_headings()\n        self._save_by_hand()\n        self._paint_apply()",
                         "        self._sync_headings()\n        self._apply_filters()\n        self._save_by_hand()\n        self._paint_apply()")),
    # The 1.20.0 width that clipped the codes.
    ('register_view',
     lambda root: _patch(root, 'ps_regview.py',
                         "    REVISION_FLOOR = 48", "    REVISION_FLOOR = 34")),
    # The heading column fitted to the drawing numbers only.
    ('register_view',
     lambda root: _patch(root, 'ps_regview.py',
                         "                widths += [self._measure(entry['num'], 14, True) + 4\n"
                         "                           for entry in heads]\n",
                         "\n")),
    # Left-out drawings looking the same as included ones.
    ('register_view',
     lambda root: _patch(root, 'ProSheets.xaml',
                         'CellStyle="{DynamicResource RegisterCell}"', '')),
    ('register_view',
     lambda root: _patch(root, 'ps_regview.py',
                         "        date.LayoutTransform = RotateTransform(-90)",
                         "        date.RenderTransform = RotateTransform(-90)")),
    # Apply writing over the views somebody else put in the set.
    ('register_view',
     lambda root: _patch(root, 'ps_regview.py',
                         "            self.host.doc, name, sheets, keep_other_views=True)",
                         "            self.host.doc, name, sheets, keep_other_views=False)")),
    # A heading that ticks nothing.
    ('register_ticks',
     lambda root: _patch(root, 'ps_regview.py',
                         "            keys = set(self.groups.get(self._as_int(entry['hid']), []))",
                         "            keys = set()")),
    # A heading click that only ever isolates, so a second click cannot
    # bring the other sheets back.
    ('register_ticks',
     lambda root: _patch(root, 'ps_regview.py',
                         "            wanted = set() if self.isolated == [column_key] \\\n                else set([column_key])",
                         "            wanted = set([column_key])")),
    # By-hand ticks not kept for the project.
    ('register_ticks',
     lambda root: _patch(root, 'ps_regview.py',
                         "    def _save_by_hand(self):\n        if self.set_name:\n            return\n",
                         "    def _save_by_hand(self):\n        return\n")),
    # A set that never reads as changed, so Apply never lights.
    ('register_ticks',
     lambda root: _patch(root, 'ps_regview.py',
                         "        return self.included != self.set_base",
                         "        return False")),
    # A new set written the moment it is named, empty.
    ('register_ticks',
     lambda root: _patch(root, 'ps_regview.py',
                         "        self.set_name = name\n        self.set_new = True\n        self.included = set()",
                         "        self.set_name = name\n        self.set_new = True\n        self.host._queue(lambda uiapp: None)\n        self.included = set()")),
    # Dates read month first.
    ('register_xlsx',
     lambda root: _patch(root, 'ps_regexport.py',
                         "            day, month, year = [int(part) for part in match.groups()]",
                         "            month, day, year = [int(part) for part in match.groups()]")),
    # The image type left out of the content types.
    ('register_xlsx',
     lambda root: _patch(root, 'ps_xlsx.py',
                         "            types.append(u'<Default Extension=\"{0}\" ContentType=\"{1}\"/>'",
                         "            types.append(u''")),
    # The drawing written before the page setup: Excel repairs the file.
    ('register_xlsx',
     lambda root: _patch(root, 'ps_xlsx.py',
                         "        out.append(u'<pageMargins left=\"{0}\"",
                         "        if drawing_rid:\n            out.append(u'<drawing r:id=\"{0}\"/>'.format(drawing_rid))\n        out.append(u'<pageMargins left=\"{0}\"")),
    # Rows that carry only a height dropped.
    ('register_xlsx',
     lambda root: _patch(root, 'ps_xlsx.py',
                         "        rows = set([key[0] for key in self.cells]) | set(self.heights.keys())",
                         "        rows = set([key[0] for key in self.cells])")),
    # Sheet names cut to 31 without checking they are still unique.
    ('register_xlsx',
     lambda root: _patch(root, 'ps_xlsx.py',
                         "    while candidate.lower() in taken:",
                         "    while False:")),
    # A single-cell merge.
    ('register_xlsx',
     lambda root: _patch(root, 'ps_xlsx.py',
                         "        merges = [m for m in self.merges if (m[0], m[1]) != (m[2], m[3])]",
                         "        merges = list(self.merges) + [(1, 1, 1, 1)]")),
    # The print range left alone, so ViewSheetSetting throws.
    ('sheet_sets',
     lambda root: _patch(root, 'ps_model.py',
                         "        manager.PrintRange = PrintRange.Select\n", "")),
    # The 1.20.0 shape: never switch to the set being updated.
    ('sheet_sets',
     lambda root: _patch(root, 'ps_model.py',
                         "        if existing is not None:\n            setting.CurrentViewSheetSet = existing\n",
                         "")),
    # SaveAs whatever the name.
    ('sheet_sets',
     lambda root: _patch(root, 'ps_model.py',
                         "        if existing is not None:\n            setting.Save()\n        else:\n            setting.SaveAs(name)",
                         "        setting.SaveAs(name)")),
    # The set's own views thrown away.
    ('sheet_sets',
     lambda root: _patch(root, 'ps_model.py',
                         "                if not isinstance(view, ViewSheet):\n                    views.append(view)",
                         "                pass")),
    # ---------------------------------------------------- 1.22.0
    # The 1.21.0 folder: the deepest shared one, inside PDF on one series.
    ('register_logic',
     lambda root: _patch(root, 'ps_register.py',
                         "        if per_format and u'\\\\' in text:",
                         "        if False:")),
    # Every tab on the strip whatever is in it.
    ('register_logic',
     lambda root: _patch(root, 'ps_register.py',
                         "    if not included_only or label == ALL_TAB or current:",
                         "    if True:")),
    # Included only left on a discipline whose tab has gone.
    ('register_ticks',
     lambda root: _patch(root, 'ps_regview.py',
                         "        if self.show_mode == 'included' and self.tabs and \\\n"
                         "                not self._tab_has_included(self.tab_index):",
                         "        if False:")),
    # Add to export invisible on the Create tab.
    ('register_view',
     lambda root: _patch(root, 'ps_window.py',
                         "        with_register = alone or (bool(jobs) and\n                                  self.register.add_to_export())",
                         "        with_register = False")),
    ('register_view',
     lambda root: _patch(root, 'ps_regview.py',
                         "            self.host._refresh_plan()\n", "            pass\n")),
    # The run deciding the folder from what happened to be written.
    ('register_view',
     lambda root: _patch(root, 'ps_window.py',
                         "                    self.register_folder(jobs, formats), report)",
                         "                    self.register_folder([], formats), report)")),
    # .NET refusing and the register lost with it.
    ('register_xlsx',
     lambda root: _patch(root, 'ps_xlsx.py',
                         "            except Exception as err:\n                errors.append(u'{0}: {1}'.format(route, err))",
                         "            except Exception as err:\n                return False, u'{0}'.format(err)")),
    # ---------------------------------------------------- 1.23.0
    # A filter that allows blanks matching nothing, so "(Blanks)" is useless.
    ('register_logic',
     lambda root: _patch(root, 'ps_register.py',
                         "        if u'{0}'.format(values.get(column) or u'').strip() not in allowed:",
                         "        if u'{0}'.format(values.get(column) or u'').strip() not in allowed or not values.get(column):")),
    # The filter list in plain text order: P-10 before P-9.
    ('register_logic',
     lambda root: _patch(root, 'ps_register.py',
                         "    values.sort(key=_natural)", "    values.sort()")),
    # The All tab grouped by discipline only.
    ('register_logic',
     lambda root: _patch(root, 'ps_register.py',
                         "        return [(label, members, series_of(members))",
                         "        return [(label, members, [])")),
    # Hide unused ignored.
    ('register_logic',
     lambda root: _patch(root, 'ps_register.py',
                         "    if hide_unused:\n        return columns_used(revisions, rows)",
                         "    if False:\n        return columns_used(revisions, rows)")),
    # A column's list narrowed by its own filter.
    ('register_view',
     lambda root: _patch(root, 'ps_regview.py',
                         "                       self.column_filters.items() if key != col_id])",
                         "                       self.column_filters.items()])")),
    # The grid re-filtered on every keystroke in the list's search box.
    ('register_view',
     lambda root: _patch(root, 'ps_regview.py',
                         "                    else Visibility.Collapsed\n",
                         "                    else Visibility.Collapsed\n            self._apply_filters()\n")),
    # The register's colours left alone on a palette swap.
    ('register_view',
     lambda root: _patch(root, 'ps_window.py',
                         "            self.register.repaint()\n", "            pass\n")),
    # A filtered revision column hidden as unused.
    ('register_ticks',
     lambda root: _patch(root, 'ps_regview.py',
                         "        keep |= set([key for key, allowed in self.column_filters.items()",
                         "        keep |= set([key for key, allowed in {}.items()")),
    # Folding a discipline that leaves its series headings showing.
    ('register_ticks',
     lambda root: _patch(root, 'ps_regview.py',
                         "            shown = group in alive and not (parent is not None and\n"
                         "                                             self._folded(parent))",
                         "            shown = group in alive")),
    # A discipline heading that ticks only the drawings directly under it.
    ('register_ticks',
     lambda root: _patch(root, 'ps_regview.py',
                         "        self.groups[group_id] = [u'{0}'.format(row.key) for row in rows]",
                         "        self.groups[group_id] = [u'{0}'.format(row.key) for row in rows][:1]")),
    # An unticked discipline exported anyway.
    ('register_xlsx',
     lambda root: _patch(root, 'ps_regexport.py',
                         "           if label != ps_register.ALL_TAB and label not in skip",
                         "           if label != ps_register.ALL_TAB")),
    # Clicks on the filter list bubbling to the heading.
    ('register_view',
     lambda root: _patch(root, 'ps_regview.py',
                         "        shell.MouseLeftButtonDown += swallow\n", "")),
    # ---------------------------------------------------- 1.24.0
    # Heading ticks back with everything collapsed.
    ('register_ticks',
     lambda root: _patch(root, 'ps_register.py',
                         "    return (not included_only) and bool(drawings_showing)",
                         "    return not included_only")),
    # Heading ticks back under "Included only".
    ('register_ticks',
     lambda root: _patch(root, 'ps_regview.py',
                         "            self.show_mode == 'included', drawings)",
                         "            False, drawings)")),
    # The flag set and nothing in the template acting on it.
    ('register_ticks',
     lambda root: _patch(root, 'ps_regview.py',
                         "        u'<Setter TargetName=\"Tick\" Property=\"Visibility\" Value=\"Hidden\"/>'",
                         "        u''")),
    # The tick column back on the Selection tab's template.
    ('register_ticks',
     lambda root: _patch(root, 'ps_regview.py',
                         "XamlReader.Parse(self.TICK_TEMPLATE)",
                         "XamlReader.Parse(self.host.TICK_TEMPLATE)")),
    # A machine left on the driver Setup once chose.
    ('pdf_default',
     lambda root: _patch(root, 'ps_config.py',
                         "        if found < 4:\n            self.store['default_printer'] = ''\n            self.store['prefer_native_pdf'] = '1'\n",
                         "        if found < 4:\n")),
    # The new defaults written over a list somebody typed.
    ('pdf_default',
     lambda root: _patch(root, 'ps_config.py',
                         "                if get_text(self.store, key, old) == old:",
                         "                if True:")),
    # A template's driver obeyed over the machine's preference.
    ('pdf_default',
     lambda root: _patch(root, 'ps_window.py',
                         "        if prefer_native:\n            return u'', name, 'prefer-native'\n",
                         "")),
    # Cut one level too deep: into the first series.
    ('issue_folder',
     lambda root: _patch(root, 'ps_paths.py',
                         "    kept = job_parts[:len(root_parts) + cut]",
                         "    kept = job_parts[:len(root_parts) + cut + 1]")),
    # The root compared case-sensitively, as Windows does not.
    ('issue_folder',
     lambda root: _patch(root, 'ps_paths.py',
                         "    if [part.lower() for part in job_parts[:len(root_parts)]] != \\\n            [part.lower() for part in root_parts]:",
                         "    if job_parts[:len(root_parts)] != root_parts:")),
    # A UNC share losing its leading slashes.
    ('issue_folder',
     lambda root: _patch(root, 'ps_paths.py',
                         "        joined = u'\\\\\\\\' + joined", "        pass")),
    # Back to the deepest folder written.
    ('issue_folder',
     lambda root: _patch(root, 'ps_window.py',
                         "        if planned and os.path.isdir(planned):\n            return planned\n",
                         "")),
    # The primary button left on the first folder written.
    ('issue_folder',
     lambda root: _patch(root, 'ps_window.py',
                         "        if ask_to_open and answer == 'primary':\n            ps_export.open_folder(target)",
                         "        if ask_to_open and answer == 'primary':\n            ps_export.open_folder(folders[0])")),
    # The folder worked out again at report time.
    ('issue_folder',
     lambda root: _patch(root, 'ps_window.py',
                         "            self._issue_folder = self.issue_folder(jobs, formats)\n        except Exception:",
                         "            self._issue_folder = u''\n        except Exception:")),
    # Drafts shaded like every other issue.
    ('register_xlsx',
     lambda root: _patch(root, 'ps_regexport.py',
                         "            if col == self.current:\n                left = u'medium'",
                         "            if col == self.current:\n                left = u'thin'")),
    # No blank row between series.
    ('register_xlsx',
     lambda root: _patch(root, 'ps_regexport.py',
                         "        if not first:\n            row += 1\n            _blank(form, row, current, last)\n",
                         "")),
    # The client logo left out of the band.
    ('register_xlsx',
     lambda root: _patch(root, 'ps_regexport.py',
                         "    for path in (info.logo, info.client_logo):",
                         "    for path in (info.logo,):")),
    # Logos run off a narrow form rather than shrunk to fit it.
    ('register_xlsx',
     lambda root: _patch(root, 'ps_regexport.py',
                         "    if need > room > 0:\n        shrink = float(room) / need",
                         "    if False:\n        shrink = 1.0")),
    # No blank issue columns: the form changes width with every issue.
    ('register_xlsx',
     lambda root: _patch(root, 'ps_regexport.py',
                         "    columns = max(len(issues), MIN_ISSUE_COLUMNS)",
                         "    columns = len(issues)")),
    # The snapshot column always there, whatever Setup says.
    ('register_xlsx',
     lambda root: _patch(root, 'ps_regexport.py',
                         "    first_issue = COL_CURRENT + 1 if snapshot else COL_CURRENT\n",
                         "    first_issue = COL_CURRENT + 1\n")),
    # Landscape A3, the 1.23.0 page.
    ('register_xlsx',
     lambda root: _patch(root, 'ps_regexport.py',
                         "    sheet.paper, sheet.landscape = paper_setup(info.paper)",
                         "    sheet.paper, sheet.landscape = 8, True")),
    # Every picture anchored at A1 with its offset running past the column.
    ('register_xlsx',
     lambda root: _patch(root, 'ps_xlsx.py',
                         "            if x < left + span or col >= 16384:",
                         "            if True:")),
    # No print area.
    ('register_xlsx',
     lambda root: _patch(root, 'ps_xlsx.py',
                         "            if sheet.print_area:", "            if False:")),
    # Defined names out of Excel's order.
    ('register_xlsx',
     lambda root: _patch(root, 'ps_xlsx.py',
                         "            for name, index, value in sorted(names):",
                         "            for name, index, value in reversed(sorted(names)):")),
    # A JPEG beside a PNG with no type of its own.
    ('register_xlsx',
     lambda root: _patch(root, 'ps_xlsx.py',
                         "            declared.add(extension)\n",
                         "            declared.add(extension)\n            break\n")),
    # The same logo stored once per worksheet.
    ('register_xlsx',
     lambda root: _patch(root, 'ps_xlsx.py',
                         "                if path in media:\n                    continue\n",
                         "                if False:\n                    continue\n")),
    # ---------------------------------------------------- 1.25.0
    # The Sequence Number column left empty.
    ('register_ticks',
     lambda root: _patch(root, 'ps_regview.py',
                         "        entry['seq'] = getattr(row, 'current_sequence', u'') or u''\n",
                         "")),
    # The column put after Rev Date rather than next to Rev.
    ('register_ticks',
     lambda root: _patch(root, 'ps_regview.py',
                         "        ('seq', u'Seq No', 60),\n        ('rdate', u'Rev Date', 80),\n",
                         "        ('rdate', u'Rev Date', 80),\n        ('seq', u'Seq No', 60),\n")),
    # The sequence number built and never put in the header.
    ('register_ticks',
     lambda root: _patch(root, 'ps_regview.py',
                         "        panel.Children.Add(sequence)\n", "")),
    # The element id shown as the sequence number.
    ('register_logic',
     lambda root: _patch(root, 'ps_register.py',
                         "            row.current_sequence = sequence_text(column.sequence)",
                         "            row.current_sequence = sequence_text(column.element_key)")),
    # A revision with no sequence shown as 0.
    ('register_logic',
     lambda root: _patch(root, 'ps_register.py',
                         "    return u'{0}'.format(number) if number > 0 else u''",
                         "    return u'{0}'.format(number)")),
    # The sequence number written into the Excel file.
    ('register_xlsx',
     lambda root: _patch(root, 'ps_regexport.py',
                         "            form.put(row, COL_TITLE, drawing.name, size=10,",
                         "            form.put(row, COL_TITLE, drawing.name + u' ' + getattr(drawing, 'current_sequence', u''), size=10,")),
    # ---------------------------------------------------- 1.26.0
    # The 1.24.0 line: a row height written with a precision, as given.
    ('int_precision',
     lambda root: _patch(root, 'ps_xlsx.py',
                         "                    float(self.heights[row]))",
                         "                    self.heights[row])")),
    # A wait budget that may be a whole number of seconds.
    ('int_precision',
     lambda root: _patch(root, 'ps_export.py',
                         "                      .format(float(budget), printer_name))",
                         "                      .format(budget, printer_name))")),
    # Reset filters that leaves the filters on.
    ('register_ticks',
     lambda root: _patch(root, 'ps_regview.py',
                         "        self.isolated = []\n        self.clear_filters()\n",
                         "        self.isolated = []\n")),
    # The button never relit.
    ('register_ticks',
     lambda root: _patch(root, 'ps_regview.py',
                         "        self._paint_ticks()\n        self._paint_reset_button()\n",
                         "        self._paint_ticks()\n")),
    # The Rev column back to plain.
    ('register_ticks',
     lambda root: _patch(root, 'ps_regview.py',
                         "        if col_id == 'rev':\n            column.ElementStyle = self._current_style()\n        elif col_id in self.CENTRED:",
                         "        if col_id in self.CENTRED:")),
    # Nothing ticked stops at "tick some sheets", register or not.
    ('issue_folder',
     lambda root: _patch(root, 'ps_window.py',
                         "        if self.register_alone(jobs):\n            self._start_register_alone()\n            return\n",
                         "")),
    # The Export button greyed with only the register to write.
    ('issue_folder',
     lambda root: _patch(root, 'ps_window.py',
                         "        ready = ((bool(jobs) and bool(formats)) or self.register_alone(jobs)) \\\n",
                         "        ready = ((bool(jobs) and bool(formats))) \\\n")),
    # An _unset folder made for a sheet parameter the project cannot fill.
    ('issue_folder',
     lambda root: _patch(root, 'ps_paths.py',
                         "        if not resolvable:\n            break\n", "")),
    # The register alone dropped in the bare root.
    ('issue_folder',
     lambda root: _patch(root, 'ps_window.py',
                         "        if not folders:\n            # Nothing ticked: the register on its own, in the issue folder\n            # the tokens name without a sheet.\n            return self.register_alone_folder()\n",
                         "")),
    # ---------------------------------------------------- 1.27.0
    # The register back inside the one series' folder.
    ('issue_folder',
     lambda root: _patch(root, 'ps_window.py',
                         "        if cut:\n            return cut\n        found = ps_register.register_folder(",
                         "        found = ps_register.register_folder(")),
    # No date on the file, so each issue overwrites the last.
    ('issue_folder',
     lambda root: _patch(root, 'ps_register.py',
                         "    return u'{0} - Document Register - {1}.xlsx'.format(",
                         "    return u'{0} - Document Register.xlsx{1}'.format(")),
    # The chosen switch back to the blue outline.
    ('register_ticks',
     lambda root: _patch(root, 'ps_regview.py',
                         "'SwitchButtonOn' if on_all else 'ChipButton')",
                         "'ChipButtonOn' if on_all else 'ChipButton')")),
    # Export to Excel back to the orange outline.
    ('register_ticks',
     lambda root: _patch(root, 'ProSheets.xaml',
                         'Style="{DynamicResource ExcelButton}" Margin="0,0,20,6"',
                         'Style="{DynamicResource AccentButton}" Margin="0,0,20,6"')),
    # ---------------------------------------------------- 1.28.0
    # A selected block that leapfrogs itself.
    ('revision_manager',
     lambda root: _patch(root, 'ps_revisions.py',
                         "            if result[index] in picked and result[index - 1] not in picked:",
                         "            if result[index] in picked:")),
    # Issued revisions open to edits Revit will refuse on Apply.
    ('revision_manager',
     lambda root: _patch(root, 'ps_revisions.py',
                         "        if field != 'issued' and self.locked(key):",
                         "        if False:")),
    # Un-issue never written, so the edits behind it are refused.
    ('revision_manager',
     lambda root: _patch(root, 'ps_revisions.py',
                         "    for element_key in plan['unissue']:",
                         "    for element_key in []:")),
    # Issue never written.
    ('revision_manager',
     lambda root: _patch(root, 'ps_revisions.py',
                         "    for one in plan['issue']:",
                         "    for one in []:")),
    # A merge with whatever happens to sit before it in the model.
    ('revision_manager',
     lambda root: _patch(root, 'ps_revisions.py',
                         "            api.reorder(order)\n            api.combine_with_previous(element_key)",
                         "            api.combine_with_previous(element_key)")),
    # The last revision deletable.
    ('revision_manager',
     lambda root: _patch(root, 'ps_revisions.py',
                         "        if len([key for key in self.live_order() if key not in going]) < 1:",
                         "        if False:")),
    # Issued revisions mergeable.
    ('revision_manager',
     lambda root: _patch(root, 'ps_revisions.py',
                         "            if one.fields.get('issued') or one.originally_issued():",
                         "            if False:")),
    # Every field written back, changed or not.
    ('revision_manager',
     lambda root: _patch(root, 'ps_revisions.py',
                         "            edits = dict([(field, entry.fields[field]) for field in FIELDS\n                          if field != 'issued' and\n                          entry.fields[field] != entry.original[field]])",
                         "            edits = dict([(field, entry.fields[field]) for field in FIELDS\n                          if field != 'issued'])")),
    # A revision in use deleted without asking.
    ('revision_manager',
     lambda root: _patch(root, 'ps_revwin.py',
                         "            if used and not self._confirm_delete(used):",
                         "            if False:")),
    # The grid opening an issued revision for editing.
    ('revision_manager',
     lambda root: _patch(root, 'ps_revwin.py',
                         "        elif field != 'issued' and not field.startswith(u'x_') and \\\n                self.staging.locked(key):",
                         "        elif False:")),
    # The register left showing the revisions as they were.
    ('revision_manager',
     lambda root: _patch(root, 'ps_regview.py',
                         "                      for revision in self.revisions])\n        self.reload()\n",
                         "                      for revision in self.revisions])\n")),
    # ---------------------------------------------------- 1.28.1
    # The "1" back in the triangle.
    ('revision_manager',
     lambda root: _patch(root, 'ProSheets.xaml',
                         'Data="M 13,1 L 25,23 L 1,23 Z"/>\n',
                         'Data="M 13,1 L 25,23 L 1,23 Z"/>\n                    <TextBlock Text="1"/>\n')),
    # Move Up back to a bare word.
    ('revision_manager',
     lambda root: _patch(root, 'ProSheetsRevisions.xaml',
                         '                  <Path Width="12" Height="9" Stretch="Uniform"\n                        Margin="0,0,8,0" VerticalAlignment="Center"\n                        Fill="{DynamicResource BlueBrush}"\n                        Data="M 6,0 L 12,9 L 0,9 Z"/>\n',
                         '')),
    # The arc box back to the height that clipped its number.
    ('revision_manager',
     lambda root: _patch(root, 'ProSheetsRevisions.xaml',
                         '<TextBox x:Name="RevArcBox" Margin="0,0,0,14" Height="34"',
                         '<TextBox x:Name="RevArcBox" Margin="0,0,0,14" Height="26"')),
    # ---------------------------------------------------- 1.29.0
    # A tab in a note splitting the stored line.
    ('revision_columns',
     lambda root: _patch(root, 'ps_revdata.py',
                         ".replace(u'\\\\', u'\\\\\\\\').replace(u'\\t', u'\\\\t')",
                         ".replace(u'\\\\', u'\\\\\\\\')")),
    # A Number column taking text.
    ('revision_columns',
     lambda root: _patch(root, 'ps_revdata.py',
                         "        if text and not _NUMBER.match(text):",
                         "        if False:")),
    # Two columns with one name.
    ('revision_columns',
     lambda root: _patch(root, 'ps_revdata.py',
                         "        if column.id != column_id and column.name.lower() == name.lower():",
                         "        if False:")),
    # Text written into a whole-number parameter.
    ('revision_columns',
     lambda root: _patch(root, 'ps_revdata.py',
                         "    'text': ('String',),",
                         "    'text': ('String', 'Integer'),")),
    # A superseded revision's note left on a sheet with no current one.
    ('revision_columns',
     lambda root: _patch(root, 'ps_revdata.py',
                         "            if revision_key is not None else u''\n    return out",
                         "            if revision_key is not None else u'old'\n    return out")),
    # Mapped columns pushed only when asked.
    ('revision_columns',
     lambda root: _patch(root, 'ps_revisions.py',
                         "        plan['push'] = bool(pushed) and (self.push_requested or others or\n                                         self.custom_changed())",
                         "        plan['push'] = bool(pushed) and self.push_requested")),
    # Pushed before the issues and the order went in.
    ('revision_columns',
     lambda root: _patch(root, 'ps_revisions.py',
                         "    for one in plan['issue']:",
                         "    if plan.get('push') and plan.get('custom'):\n        api.push(plan['custom']['columns'], {})\n    for one in plan['issue']:")),
    # A new revision's notes stored under its staging key.
    ('revision_columns',
     lambda root: _patch(root, 'ps_revisions.py',
                         "            element_key = made.get(key, key)\n            if not isinstance(element_key, type(u'')):\n                values[element_key] = row",
                         "            if not isinstance(key, type(u'')):\n                values[key] = row")),
    # Notes locked on issued revisions, like Revit's own fields.
    ('revision_columns',
     lambda root: _patch(root, 'ps_revwin.py',
                         "        elif field != 'issued' and not field.startswith(u'x_') and \\\n                self.staging.locked(key):",
                         "        elif field != 'issued' and \\\n                self.staging.locked(key):")),
    # Issued revisions refusing a note in the staging too.
    ('revision_columns',
     lambda root: _patch(root, 'ps_revisions.py',
                         "        ok, stored = ps_revdata.normalise(column, value)",
                         "        if self.locked(key):\n            return False, u'locked'\n        ok, stored = ps_revdata.normalise(column, value)")),
    # ---------------------------------------------------- 1.30.0
    # The button opening Pro Sheets instead of the manager.
    ('revision_button',
     lambda root: _patch(root, '../Revision Manager.pushbutton/script.py',
                         "        ps_revwin.run_standalone(uiapp)",
                         "        ps_revwin.RevisionManager(None)")),
    # The tool folder looked for under the wrong name.
    ('revision_button',
     lambda root: _patch(root, '../Revision Manager.pushbutton/script.py',
                         "TOOL = os.path.join(os.path.dirname(HERE), 'Pro Sheets Exporter.pushbutton')",
                         "TOOL = os.path.join(os.path.dirname(HERE), 'ProSheets.pushbutton')")),
    # An import at module level, before anything can report it.
    ('revision_button',
     lambda root: _patch(root, '../Revision Manager.pushbutton/script.py',
                         "import traceback\n",
                         "import traceback\nimport ps_revwin\n")),
    # The icon left out of the delivery.
    ('revision_button',
     lambda root: os.remove(os.path.join(os.path.dirname(root),
                                         'Revision Manager.pushbutton',
                                         'icon.png'))),
    # Apply staged and never written when opened on its own.
    ('revision_button',
     lambda root: _patch(root, 'ps_revwin.py',
                         "        done, errors = ps_revisions.write(doc, plan)",
                         "        done, errors = 0, []")),
    # ---------------------------------------------------- 1.31.0
    # One sheet series counted once per sheet that carries it.
    ('revision_series',
     lambda root: _patch(root, 'ps_revisions.py',
                         "        if series not in bucket:\n            bucket.append(series)",
                         "        bucket.append(series)")),
    # Type parameters offered: every sheet would show one value.
    ('revision_series',
     lambda root: _patch(root, 'ps_revdata.py',
                         "        if not parameter.get('instance'):\n            continue\n",
                         "")),
    # Parameters on any category offered.
    ('revision_series',
     lambda root: _patch(root, 'ps_revdata.py',
                         "        if target not in parameter.get('categories', ()):\n            continue\n",
                         "")),
    # A number written into a Yes/No parameter.
    ('revision_series',
     lambda root: _patch(root, 'ps_revdata.py',
                         "    'number': ('Double', 'Integer', 'String'),",
                         "    'number': ('Double', 'Integer', 'String', 'YesNo'),")),
    # The series cell that never opens.
    ('revision_series',
     lambda root: _patch(root, 'ps_revwin.py',
                         "    u' IsChecked=\"{{Binding series_open, Mode=TwoWay, '",
                         "    u' IsChecked=\"{{Binding live, Mode=OneWay, '")),
    # The Settings button drawn and not wired.
    ('revision_series',
     lambda root: _patch(root, 'ps_revwin.py',
                         "                ('RevSettingsButton', self._open_settings),\n",
                         "")),
    # Project Parameters queued as a second job, replacing the write.
    ('revision_series',
     lambda root: _patch(root, 'ps_regview.py',
                         "            if post:\n                ps_revwin.post_command(uiapp, post)\n",
                         "")),
    # Reopening after Apply whatever Setup says.
    ('revision_series',
     lambda root: _patch(root, 'ps_revwin.py',
                         "                if post or not reopen:",
                         "                if post:")),
    # ---------------------------------------------------- 1.32.0
    # The 1.31.0 layout: Sheet series twice.
    ('revision_series',
     lambda root: _patch(root, 'ps_revwin.py',
                         "        out = [(field, title, width, kind, None)\n               for field, title, width, kind in COLUMNS]",
                         "        out = [(field, title, width, kind, None)\n               for field, title, width, kind in COLUMNS] + [('series', u'Sheet series', 190, 'series', None)]")),
    # Used on sheets all one colour.
    ('revision_series',
     lambda root: _patch(root, 'ps_revwin.py',
                         "    u'<DataTrigger Binding=\"{{Binding used}}\" Value=\"0\">'",
                         "    u'<DataTrigger Binding=\"{{Binding used}}\" Value=\"-\">'")),
    # Columns fixed in place.
    ('revision_series',
     lambda root: _patch(root, 'ProSheetsRevisions.xaml',
                         'CanUserReorderColumns="True"',
                         'CanUserReorderColumns="False"')),
    # A dragged order forgotten.
    ('revision_series',
     lambda root: _patch(root, 'ps_revwin.py',
                         "    known = [field for field in saved if field in fields]",
                         "    known = []")),
    # Any word matching rather than every word.
    ('revision_series',
     lambda root: _patch(root, 'ps_revdata.py',
                         "            if all([word in u'{0}'.format(name).lower() for word in words])]",
                         "            if any([word in u'{0}'.format(name).lower() for word in words])]")),
    # The parameter list not narrowed by what is typed.
    ('revision_series',
     lambda root: _patch(root, 'ps_revsetwin.py',
                         "                                       matcher=ps_revdata.matching)",
                         "                                       )")),
    # ---------------------------------------------------- 1.33.0
    # A revision on two series only shown when both are ticked.
    ('revision_filters',
     lambda root: _patch(root, 'ps_revisions.py',
                         "        if not [token for token in tokens if token in allowed]:",
                         "        if [token for token in tokens if token not in allowed]:")),
    # Sheet series listed as one joined string.
    ('revision_filters',
     lambda root: _patch(root, 'ps_revisions.py',
                         "        if field == 'series':\n            series =",
                         "        if field == 'never':\n            series =")),
    # A column's own filter shrinking its own list.
    ('revision_filters',
     lambda root: _patch(root, 'ps_revisions.py',
                         "                    lambda name: self.tokens(key, name, values), picks,\n                    skip=field):",
                         "                    lambda name: self.tokens(key, name, values), picks,\n                    skip=None):")),
    # The lists drawn but the grid not filtered by them.
    ('revision_filters',
     lambda root: _patch(root, 'ps_revwin.py',
                         "        visible = set(self.staging.visible(self.filters, self.picks,",
                         "        visible = set(self.staging.visible(self.filters, None,")),
    # One value at a time.
    ('revision_filters',
     lambda root: _patch(root, 'ps_revwin.py',
                         "        listing.SelectionMode = SelectionMode.Extended",
                         "        listing.SelectionMode = SelectionMode.Single")),
    # Ticking one of several selected values ticks only that one.
    ('revision_filters',
     lambda root: _patch(root, 'ps_revwin.py',
                         "                    set_all(group, bool(sender.IsChecked))",
                         "                    pass")),
    # Space doing nothing.
    ('revision_filters',
     lambda root: _patch(root, 'ps_revwin.py',
                         "            if key != Key.Space:",
                         "            if key != Key.F12:")),
    # No list under the headings.
    ('revision_filters',
     lambda root: _patch(root, 'ps_revwin.py',
                         "        line.Children.Add(self._filter_button(field))",
                         "        pass")),
    # Ctrl+Up in the list moving revisions behind it.
    ('revision_filters',
     lambda root: _patch(root, 'ps_revwin.py',
                         "        if self._filter_open:\n            return\n",
                         "")),
    # Clear filters leaving the value lists on.
    ('revision_filters',
     lambda root: _patch(root, 'ps_revwin.py',
                         "        for field in list(self.picks.keys()):\n            self.picks.pop(field, None)\n",
                         "        for field in list(self.picks.keys()):\n            self.picks.get(field, None)\n")),
    # Everything ticked kept as a filter.
    ('revision_filters',
     lambda root: _patch(root, 'ps_revwin.py',
                         "            self.set_pick(field, None if len(ticked) == len(boxes)",
                         "            self.set_pick(field, ticked if len(ticked) == len(boxes)")),
    # The Parameter box ignoring what is typed.
    ('revision_filters',
     lambda root: _patch(root, 'ps_ui.py',
                         "        return (matcher or words_match)(items, text)",
                         "        return list(items)")),
    # Part of a name counting as picked.
    ('revision_filters',
     lambda root: _patch(root, 'ps_ui.py',
                         "            if u'{0}'.format(item).lower() == text:",
                         "            if text in u'{0}'.format(item).lower():")),
    # Typing into the box doing nothing.
    ('revision_filters',
     lambda root: _patch(root, 'ps_ui.py',
                         "        self.box.TextChanged += self._typed",
                         "        pass")),
    # The separate Search column back.
    ('revision_filters',
     lambda root: _patch(root, 'ps_revsetwin.py',
                         "HEADINGS = [u'Column', u'Type', u'Push to', u'Parameter', u'Status']",
                         "HEADINGS = [u'Column', u'Type', u'Push to', u'Search', u'Parameter', u'Status']")),
    # ---------------------------------------------------- 1.34.0
    # Sheet series folded by default.
    ('revision_series',
     lambda root: _patch(root, 'ps_config.py',
                         "    'rev_series_open': '1',",
                         "    'rev_series_open': '0',")),
    # Rows filled without the open state.
    ('revision_series',
     lambda root: _patch(root, 'ps_revwin.py',
                         "                row['series_open'] = self.series_open\n",
                         "")),
    # The Collapse/Expand button drawn and doing nothing.
    ('revision_series',
     lambda root: _patch(root, 'ps_revwin.py',
                         "                ('RevSeriesToggleButton', self._toggle_series),\n",
                         "")),
    # Chips in one long line that never wraps.
    ('revision_series',
     lambda root: _patch(root, 'ps_revwin.py',
                         "    u'<WrapPanel Orientation=\"Horizontal\"/>'",
                         "    u'<StackPanel Orientation=\"Horizontal\"/>'")),
    # The choice forgotten next time.
    ('revision_series',
     lambda root: _patch(root, 'ps_revwin.py',
                         "                self.settings.set('rev_series_open',",
                         "                self.settings.set('rev_series_shut',")),
    # ---------------------------------------------------- 1.35.0
    # The Change column back.
    ('revision_series',
     lambda root: _patch(root, 'ps_revwin.py',
                         "    ('seq', u'Sequence', AUTO, 'read'),",
                         "    ('pending', u'Change', 104, 'read'),\n    ('seq', u'Sequence', AUTO, 'read'),")),
    # What was staged for a row nowhere to be read.
    ('revision_series',
     lambda root: _patch(root, 'ps_revwin.py',
                         "                   'seq': u' ToolTip=\"{Binding pending}\"'}.get(field, u'')",
                         "                   }.get(field, u'')")),
    # ---------------------------------------------------- 1.36.0
    # Sheet series fitting itself, so its chips never wrap.
    ('revision_series',
     lambda root: _patch(root, 'ps_revwin.py',
                         "    ('series', u'Sheet series', 190, 'series'),",
                         "    ('series', u'Sheet series', AUTO, 'series'),")),
    # Description grown to its longest line instead of taking what is left.
    ('revision_series',
     lambda root: _patch(root, 'ps_revwin.py',
                         "    ('desc', u'Description', 0, 'text'),",
                         "    ('desc', u'Description', AUTO, 'text'),")),
    # An added column back to a fixed width.
    ('revision_series',
     lambda root: _patch(root, 'ps_revwin.py',
                         "CUSTOM_WIDTHS = {'text': AUTO, 'yesno': AUTO, 'number': AUTO, 'date': AUTO,",
                         "CUSTOM_WIDTHS = {'text': 220, 'yesno': AUTO, 'number': AUTO, 'date': AUTO,")),
    # Nothing fitted at all.
    ('revision_series',
     lambda root: _patch(root, 'ps_revwin.py',
                         "    return width == AUTO",
                         "    return False")),
    # No floor, so a fitted column can hide its own search box.
    ('revision_series',
     lambda root: _patch(root, 'ps_revwin.py',
                         "AUTO_MIN = 78",
                         "AUTO_MIN = 0")),
    # The Fit columns button drawn and doing nothing.
    ('revision_series',
     lambda root: _patch(root, 'ps_revwin.py',
                         "                ('RevFitColumnsButton', self._fit_columns),\n",
                         "")),
    # Fit columns re-fitting every column, Sheet series included.
    ('revision_series',
     lambda root: _patch(root, 'ps_revwin.py',
                         "            if not fits(wide.get(field, 0)):\n                continue\n",
                         "")),
    # ---------------------------------------------------- 1.37.0
    # The Revit 2021 crash itself: a post-2021 name in a grouped import.
    ('api_version_imports',
     lambda root: _patch(root, 'ps_revisions.py',
                         "                               RevisionSettings, RevisionVisibility,",
                         "                               RevisionNumberingSequence, RevisionSettings,\n                               RevisionVisibility,")),
    # Guarded, but with no fallback, so the name is missing later instead.
    ('api_version_imports',
     lambda root: _patch(root, 'ps_revisions.py',
                         "except Exception:\n    RevisionNumberingSequence = None",
                         "except Exception:\n    pass")),
    # Revit 2024's theme API read where nothing catches it.
    ('api_version_imports',
     lambda root: _patch(root, 'theme.py',
                         "    try:\n        from Autodesk.Revit.UI import UIThemeManager, UITheme",
                         "    from Autodesk.Revit.UI import UIThemeManager, UITheme\n    try:")),
    # Numbering refused without saying which Revit it needs.
    ('api_version_imports',
     lambda root: _patch(root, 'ps_revisions.py',
                         "            raise ValueError(u'numbering sequences need Revit 2022 or later'\n                             u' - this Revit has none')",
                         "            raise ValueError(u'no numbering sequences here')")),
    # ---------------------------------------------------- 1.38.0
    # Modal again, so Revit is blocked while the manager is open.
    ('revision_modeless',
     lambda root: _patch(root, 'ps_revwin.py',
                         "    def show_modeless(self):\n        try:\n            self.window.Show()",
                         "    def show_modeless(self):\n        try:\n            self.window.ShowDialog()")),
    # Writing from the window's own thread, outside any API context.
    ('revision_modeless',
     lambda root: _patch(root, 'ps_revwin.py',
                         "        def job(event_uiapp):",
                         "        job = None\n        if job is None:")),
    # Idling never handed back.
    ('revision_modeless',
     lambda root: _patch(root, 'ps_revwin.py',
                         "            self._uiapp.Idling -= self._idling",
                         "            pass")),
    # Nothing follows the selection.
    ('revision_modeless',
     lambda root: _patch(root, 'ps_revwin.py',
                         "            uiapp.Idling += self._idling",
                         "            pass")),
    # The list yanked about while a cell is being edited.
    ('revision_modeless',
     lambda root: _patch(root, 'ps_revwin.py',
                         "        if not self.follow or self._editing:",
                         "        if not self.follow:")),
    # A jump to a revision the list is already on.
    ('revision_modeless',
     lambda root: _patch(root, 'ps_revwin.py',
                         "            return None if list(current or []) == [key] else key",
                         "            return key")),
    # The first selected cloud's revision ignored for a later one.
    ('revision_modeless',
     lambda root: _patch(root, 'ps_revwin.py',
                         "    for key in keys or []:\n        if key in (order or []):",
                         "    for key in reversed(keys or []):\n        if key in (order or []):")),
    # Every cloud of a revision listed again and again.
    ('revision_modeless',
     lambda root: _patch(root, 'ps_revisions.py',
                         "        if not key or key in (u'0', u'-1') or key in keys:",
                         "        if not key or key in (u'0', u'-1'):")),
    # Reading the selection left to throw, on every Idling tick.
    ('revision_modeless',
     lambda root: _patch(root, 'ps_revisions.py',
                         "                             for one in ids]))\n    except Exception:\n        return ()",
                         "                             for one in ids]))\n    except KeyboardInterrupt:\n        return ()")),
    # A second manager over the first.
    ('revision_modeless',
     lambda root: _patch(root, 'ps_revwin.py',
                         "            MANAGER.window.Activate()",
                         "            pass")),
    # The engine collected the moment the command returns.
    ('revision_button',
     lambda root: _patch(root, '../Revision Manager.pushbutton/script.py',
                         "__persistentengine__ = True",
                         "__persistentengine__ = False")),
    # ---------------------------------------------------- 1.39.0
    # A second plain click on the only column picked keeps it.
    ('register_picks',
     lambda root: _patch(root, 'ps_register.py',
                         "    if picked == [key]:\n        return [], key\n    return [key], key",
                         "    return [key], key")),
    # Ctrl+Shift replacing the picks with the run instead of adding it.
    ('register_picks',
     lambda root: _patch(root, 'ps_register.py',
                         "        wanted = (set(picked) | run) if ctrl else run",
                         "        wanted = run")),
    # Empty cells picked inside a Shift block.
    ('register_picks',
     lambda root: _patch(root, 'ps_register.py',
                         "                if filled(one, other):\n                    block.add((one, other))",
                         "                block.add((one, other))")),
    # Isolate keeping only sheets carrying EVERY picked revision.
    ('register_picks',
     lambda root: _patch(root, 'ps_register.py',
                         "            if [key for key in keys\n                if u'{0}'.format(row.cells.get(key, u'') or u'').strip()]]",
                         "            if all([u'{0}'.format(row.cells.get(key, u'') or u'').strip()\n                    for key in keys])]")),
    # A column key leading back to the wrong revision.
    ('register_picks',
     lambda root: _patch(root, 'ps_register.py',
                         "    return text[len(COLUMN_PREFIX):] if is_column_key(text) else u''",
                         "    return text")),
    # The cloud in a legend on twenty sheets re-pointed for the two picked.
    ('register_picks',
     lambda root: _patch(root, 'ps_revisions.py',
                         "                if reaches <= leaving.get(old, set()):",
                         "                if reaches:")),
    # The revision added by hand taken off, and the new one never put on.
    ('register_picks',
     lambda root: _patch(root, 'ps_revisions.py',
                         "                if target is not None:\n                    now.add(target)",
                         "                if target is not None:\n                    pass")),
    # An issued revision changed anyway.
    ('register_picks',
     lambda root: _patch(root, 'ps_revisions.py',
                         "            if old in issued:\n                result['skipped'].append((sheet, old, SWAP_ISSUED))\n                continue\n",
                         "")),
    # Cells moved onto an issued revision.
    ('register_picks',
     lambda root: _patch(root, 'ps_revisions.py',
                         "    if target in issued:\n        for sheet in sorted(picks):",
                         "    if False:\n        for sheet in sorted(picks):")),
    # The swap never committed.
    ('register_picks',
     lambda root: _patch(root, 'ps_revisions.py',
                         "                                  else u'move', err))\n    try:\n        transaction.Commit()\n    except Exception as err:\n        try:\n            transaction.RollBack()",
                         "                                  else u'move', err))\n    try:\n        pass\n    except Exception as err:\n        try:\n            transaction.RollBack()")),
    # Clouds left on the old revision.
    ('register_picks',
     lambda root: _patch(root, 'ps_revisions.py',
                         "            doc.GetElement(_id(cloud_key)).RevisionId = target_id",
                         "            pass")),
    # An issued revision offered in the list.
    ('register_picks',
     lambda root: _patch(root, 'ps_revswapwin.py',
                         "    if getattr(revision, 'issued', False):\n        return False, u'issued - Revit keeps it locked'\n",
                         "")),
    # Searching the list matching any word rather than every one.
    ('register_picks',
     lambda root: _patch(root, 'ps_revswapwin.py',
                         "    return all([word in line for word in words])",
                         "    return any([word in line for word in words]) or not words")),
    # The size stepping off past its ends.
    ('register_picks',
     lambda root: _patch(root, 'ps_ui.py',
                         "        return bigger[0] if bigger else ZOOM_STEPS[-1]",
                         "        return bigger[0] if bigger else current + 0.1")),
    # A size between steps not snapping to the next one.
    ('register_picks',
     lambda root: _patch(root, 'ps_ui.py',
                         "    smaller = [one for one in ZOOM_STEPS if one < current - 0.001]\n    return smaller[-1] if smaller else ZOOM_STEPS[0]",
                         "    return max(ZOOM_STEPS[0], current - 0.1)")),
    # Drawn smaller, laid out full size: nothing more fits.
    ('register_picks',
     lambda root: _patch(root, 'ps_ui.py',
                         "            self.window.Content.LayoutTransform = ScaleTransform(",
                         "            self.window.Content.RenderTransform = ScaleTransform(")),
    # The main window with no - and +.
    ('register_picks',
     lambda root: _patch(root, 'ps_window.py',
                         "        self.zoom = ps_ui.Zoom(self.window, self.settings)",
                         "        self.zoom = None")),
    # The sequence number's click falling through to the heading.
    ('register_picks',
     lambda root: _patch(root, 'ps_regview.py',
                         "        sequence.Click += self._make_seq_click(revision.key)\n",
                         "")),
    # A picked cell's chip losing to the current revision's orange.
    ('register_picks',
     lambda root: _patch(root, 'ps_regview.py',
                         "    u'<DataTrigger Binding=\"{{Binding p_{1}}}\" Value=\"1\">'",
                         "    u'<DataTrigger Binding=\"{{Binding q_{1}}}\" Value=\"1\">'")),
    # Isolate pressed and nothing narrows.
    ('register_picks',
     lambda root: _patch(root, 'ps_regview.py',
                         "        if self.isolated and not [key for key in self.isolated",
                         "        if False and not [key for key in self.isolated")),
    # Reset filters leaving the view isolated.
    ('register_picks',
     lambda root: _patch(root, 'ps_regview.py',
                         "        self.isolated = []\n        self.clear_filters()",
                         "        self.clear_filters()")),
    # Picking a cell swallowing the click, so the row is never selected.
    ('register_picks',
     lambda root: _patch(root, 'ps_regview.py',
                         "            self._cell_click(entry, self._column_under(source))\n            return",
                         "            self._cell_click(entry, self._column_under(source))\n            args.Handled = True\n            return")),
    # Escape doing nothing.
    ('register_picks',
     lambda root: _patch(root, 'ps_regview.py',
                         "        if key == Key.Escape and (self.picked_cells or self.picked_columns):",
                         "        if key == Key.F24 and (self.picked_cells or self.picked_columns):")),
    # No flag column to mark a picked cell on.
    ('register_picks',
     lambda root: _patch(root, 'ps_regview.py',
                         "                self.table.Columns.Add(PICK_PREFIX + revision.key, String)\n",
                         "")),
    # Change revision written straight from the window.
    ('register_picks',
     lambda root: _patch(root, 'ps_regview.py',
                         "        if self.host._queue(job):\n            self.host.say(u'Writing {0} revision change",
                         "        if job(None) or True:\n            self.host.say(u'Writing {0} revision change")),
    # ---------------------------------------------------- 1.40.0
    # The 1.39.0 failure itself: a bare number into ElementId.
    ('api_version_imports',
     lambda root: _patch(root, 'ps_revisions.py',
                         "    return ps_model.make_id(value)",
                         "    return ElementId(int(value))")),
    # Int64 only, so Revit 2023 and older cannot build one.
    ('api_version_imports',
     lambda root: _patch(root, 'ps_model.py',
                         "    try:\n        return ElementId(Int64(number))\n    except Exception:\n        return ElementId(Int32(number))",
                         "    return ElementId(Int64(number))")),
    # The plain int back inside make_id.
    ('api_version_imports',
     lambda root: _patch(root, 'ps_model.py',
                         "        return ElementId(Int64(number))",
                         "        return ElementId(number)")),
    # A new revision always last, whatever sequence was asked for.
    ('revision_add',
     lambda root: _patch(root, 'ps_revisions.py',
                         "    if position > len(live):\n        return order + [key]",
                         "    if True:\n        return order + [key]")),
    # A row staged to go counted as a slot.
    ('revision_add',
     lambda root: _patch(root, 'ps_revisions.py',
                         "    ahead_of = live[position - 1]",
                         "    ahead_of = order[position - 1]")),
    # What was filled in for the new revision dropped.
    ('revision_add',
     lambda root: _patch(root, 'ps_revisions.py',
                         "        for field, value in (fields or {}).items():\n            if field == 'issued':\n                start[field] = bool(value)",
                         "        for field, value in {}.items():\n            if field == 'issued':\n                start[field] = bool(value)")),
    # The manager's own columns dropped from a new revision.
    ('revision_add',
     lambda root: _patch(root, 'ps_revisions.py',
                         "        entry = Entry(key, None, 0, start, custom=dict(custom or {}))",
                         "        entry = Entry(key, None, 0, start)")),
    # A sequence past the end taken.
    ('revision_add',
     lambda root: _patch(root, 'ps_revaddwin.py',
                         "    if value < 1 or value > count + 1:",
                         "    if value < 1 or value > count + 2:")),
    # The note saying the wrong place.
    ('revision_add',
     lambda root: _patch(root, 'ps_revaddwin.py',
                         "        position, label or u'Sequence {0}'.format(sequence), position + 1,",
                         "        position, label or u'Sequence {0}'.format(sequence), position,")),
    # The sequence chosen ignored.
    ('revision_add',
     lambda root: _patch(root, 'ps_revwin.py',
                         "        key = self.staging.add(answer['position'], answer['fields'],",
                         "        key = self.staging.add(None, answer['fields'],")),
    # The grid left where it was.
    ('revision_add',
     lambda root: _patch(root, 'ps_revwin.py',
                         "        self._centre_on(key)\n",
                         "")),
    # The new row never green.
    ('revision_add',
     lambda root: _patch(root, 'ps_revwin.py',
                         "            self.grid.RowStyle = self._fresh_row_style()",
                         "            pass")),
    # Back from the manager, the new revision still hidden as unused.
    ('revision_add',
     lambda root: _patch(root, 'ps_regview.py',
                         "                self.set_show_all_revisions(True, quiet=True)",
                         "                pass")),
    # ... and not washed green.
    ('revision_add',
     lambda root: _patch(root, 'ps_regview.py',
                         "            self.fresh_columns = set(fresh)",
                         "            pass")),
    # Green beating a picked column's orange.
    ('revision_add',
     lambda root: _patch(root, 'ps_regview.py',
                         "        if column_key in self.picked_columns:\n            return self._picked_column_style()\n        if column_key in self.fresh_columns:\n            return self._fresh_column_style()",
                         "        if column_key in self.fresh_columns:\n            return self._fresh_column_style()\n        if column_key in self.picked_columns:\n            return self._picked_column_style()")),
    # The toolset never shown.
    ('revision_add',
     lambda root: _patch(root, 'ps_regview.py',
                         "        ps_ui.set_visible(self.cell_tools, bool(count))",
                         "        ps_ui.set_visible(self.cell_tools, False)")),
    # Clouds deleted without asking.
    ('revision_add',
     lambda root: _patch(root, 'ps_regview.py',
                         "            if answer != 'primary':\n                self.host.say(u'Apply revisions cancelled - still staged.')",
                         "            if False:\n                self.host.say(u'Apply revisions cancelled - still staged.')")),
    # Remove re-pointing clouds at nothing instead of deleting them.
    ('revision_add',
     lambda root: _patch(root, 'ps_revisions.py',
                         "            if target_id is None:\n                doc.Delete(_id(cloud_key))",
                         "            if False:\n                doc.Delete(_id(cloud_key))")),
    # Remove putting "None" on the sheet in place of the revision.
    ('revision_add',
     lambda root: _patch(root, 'ps_revisions.py',
                         "                if target is not None:\n                    now.add(target)",
                         "                now.add(target)")),
    # The Remove button drawn and doing nothing.
    ('revision_add',
     lambda root: _patch(root, 'ps_regview.py',
                         "        self._click(self.remove_button,",
                         "        self._click(None,")),
    # ---------------------------------------------------- 1.41.0
    # The 1.40.0 failure: Revit's "may appear" list taken as where it is.
    ('revision_sheets',
     lambda root: _patch(root, 'ps_revisions.py',
                         "        clouds.append((cloud_key, revision, seen.get(cloud_key) or may))",
                         "        clouds.append((cloud_key, revision, may))")),
    # Only the sheet itself looked into, not the views on it.
    ('revision_sheets',
     lambda root: _patch(root, 'ps_revisions.py',
                         "    try:\n        views.extend(list(sheet.GetAllPlacedViews()))\n    except Exception:\n        pass\n",
                         "")),
    # Told yes, and the shared cloud still left.
    ('revision_sheets',
     lambda root: _patch(root, 'ps_revisions.py',
                         "                if include_shared:\n                    if cloud_key not in chosen:",
                         "                if False:\n                    if cloud_key not in chosen:")),
    # A shared cloud left without a word.
    ('revision_sheets',
     lambda root: _patch(root, 'ps_revisions.py',
                         "                result['shared'].append(\n",
                         "                [].append(\n")),
    # Looking inside a sheet allowed to throw.
    ('revision_sheets',
     lambda root: _patch(root, 'ps_revisions.py',
                         "    try:\n        views.append(sheet.Id)\n    except Exception:\n        return found",
                         "    views.append(sheet.Id)")),
    # Create changing the sheets though no revision was made.
    ('revision_sheets',
     lambda root: _patch(root, 'ps_revisions.py',
                         "    if len(new) != 1:\n        errors.append(",
                         "    if not new:\n        errors.append(")),
    # Create putting the cells on some other revision.
    ('revision_sheets',
     lambda root: _patch(root, 'ps_revisions.py',
                         "    new = [key for key in revision_keys(doc) if key not in before]",
                         "    new = sorted(revision_keys(doc))[:1]")),
    # One date put on several revisions.
    ('revision_sheets',
     lambda root: _patch(root, 'ps_revisions.py',
                         "        if field in ALL_AT_ONCE_REFUSED:\n            return [], [",
                         "        if False:\n            return [], [")),
    # One refusal stopping the rest.
    ('revision_sheets',
     lambda root: _patch(root, 'ps_revisions.py',
                         "            ok, message = self.set_field(key, field, value)\n            if ok:\n                changed.append(key)\n            elif message not in refusals:\n                refusals.append(message)",
                         "            ok, message = self.set_field(key, field, value)\n            if ok:\n                changed.append(key)\n            else:\n                refusals.append(message)\n                break")),
    # The sheet filter dropping the revision just added.
    ('revision_sheets',
     lambda root: _patch(root, 'ps_revisions.py',
                         "                if not entry.is_new and on_sheet not in entry.sheets:",
                         "                if on_sheet not in entry.sheets:")),
    # Any view taken for a sheet.
    ('revision_sheets',
     lambda root: _patch(root, 'ps_revisions.py',
                         "        number = view.SheetNumber",
                         "        number = getattr(view, 'SheetNumber', u'?')")),
    # The date edited on every selected revision.
    ('revision_sheets',
     lambda root: _patch(root, 'ps_revwin.py',
                         "    return field in ps_revisions.FIELDS and \\\n        field not in ps_revisions.ALL_AT_ONCE_REFUSED",
                         "    return field in ps_revisions.FIELDS")),
    # An edit kept to the one row.
    ('revision_sheets',
     lambda root: _patch(root, 'ps_revwin.py',
                         "        others = self._others(key, field)\n        if others:",
                         "        others = []\n        if others:")),
    # The press narrowing the selection before the edit.
    ('revision_sheets',
     lambda root: _patch(root, 'ps_revwin.py',
                         "            self.grid.BeginEdit()",
                         "            pass")),
    # A change of sheet in Revit never noticed.
    ('revision_sheets',
     lambda root: _patch(root, 'ps_revwin.py',
                         "        if not self._editing:\n            self.track_sheet(uidoc)",
                         "        if not self._editing:\n            pass")),
    # The sheet filter offered with no sheet open.
    ('revision_sheets',
     lambda root: _patch(root, 'ps_revwin.py',
                         "            button.IsEnabled = on_sheet",
                         "            button.IsEnabled = True")),
    # Opening on nothing in particular.
    ('revision_sheets',
     lambda root: _patch(root, 'ps_revwin.py',
                         "        if focus:\n            self.focus(focus)",
                         "        if False:\n            self.focus(focus)")),
    # The selected cloud forgotten on the way in.
    ('revision_sheets',
     lambda root: _patch(root, 'ps_revwin.py',
                         "                              modeless=True, focus=focus,",
                         "                              modeless=True, focus=None,")),
    # Edit revision opening on the top of the list.
    ('revision_sheets',
     lambda root: _patch(root, 'ps_regview.py',
                         "        self.open_revision_manager(focus=sorted(keys))",
                         "        self.open_revision_manager()")),
    # Create starting the sequence at the end, not after the one picked.
    ('revision_sheets',
     lambda root: _patch(root, 'ps_regview.py',
                         "        position = (max(after) + 1) if after else None",
                         "        position = None")),
    # Clouds really on other sheets: still a dead end.
    ('revision_sheets',
     lambda root: _patch(root, 'ps_regview.py',
                         "            if self._ask_shared(mode, shared, summary):",
                         "            if False:")),
    # The second pass redoing the cells already done.
    ('revision_sheets',
     lambda root: _patch(root, 'ps_regview.py',
                         "                            if (sheet, old) not in finished])",
                         "                            ])")),
    # 1.42.0 - the register's tools, tabs and the Views list.
    ('register_tools',
     lambda root: _patch(root, 'ps_register.py',
                         "    ('electrical', (u'ELECTRIC',)),",
                         "    ('electrical', (u'ELECTRICAL SERVICES',)),")),
    ('register_tools',
     lambda root: _patch(root, 'ps_regview.py',
                         "                    text.FontWeight = FontWeights.Bold\n",
                         "                    text.FontWeight = FontWeights.Bold if active else FontWeights.Normal\n")),
    ('register_tools',
     lambda root: _patch(root, 'ps_regview.py',
                         "            icon = self._tab_icon(label)\n",
                         "            icon = None\n")),
    ('register_tools',
     lambda root: _patch(root, 'Theme.xaml',
                         '            <Border.Effect>\n              <DropShadowEffect BlurRadius="7" ShadowDepth="2.5"\n                                Direction="290" Opacity="0.45"\n                                Color="#000000"/>\n            </Border.Effect>\n',
                         '')),
    ('register_tools',
     lambda root: _patch(root, 'ps_revisions.py',
                         "        if revision in issued:\n            result['skipped'].append((sheet, SWAP_ISSUED))\n            continue\n",
                         "")),
    ('register_tools',
     lambda root: _patch(root, 'ps_revisions.py',
                         "        result['additional'][sheet] = by_hand | set([revision])",
                         "        result['additional'][sheet] = set([revision])")),
    ('register_tools',
     lambda root: _patch(root, 'ps_revisions.py',
                         "        if wanted is not None and was and not wanted:\n            self.set_field(key, 'issued', False)\n",
                         "")),
    ('register_tools',
     lambda root: _patch(root, 'ps_revisions.py',
                         "        for field, value in (fields or {}).items():\n            if field == 'issued':\n                continue",
                         "        for field, value in (fields or {}).items():\n            if field == 'issued':\n                self.set_field(key, 'issued', value)\n                continue")),
    ('register_tools',
     lambda root: _patch(root, 'ps_regview.py',
                         "                self.grid.PreviewMouseRightButtonUp += self._right_release\n",
                         "")),
    ('register_tools',
     lambda root: _patch(root, 'ps_regview.py',
                         "        if sheets:\n            entries.append((u'Open sheet'",
                         "        if False:\n            entries.append((u'Open sheet'")),
    ('register_tools',
     lambda root: _patch(root, 'ps_regview.py',
                         "        for _sheet, column in self.picked_cells:\n            if column not in columns:",
                         "        for _sheet, column in []:\n            if column not in columns:")),
    ('register_tools',
     lambda root: _patch(root, 'ps_regview.py',
                         "        if len(keys) == 1:\n            self.edit_revision_box(keys[0])\n            return\n",
                         "")),
    ('register_tools',
     lambda root: _patch(root, 'ps_regview.py',
                         "        if focus is None and self._picked_revisions():\n            # A revision picked here - its column, or a cell - is the one\n            # to open on.\n            focus = self._picked_revisions()\n",
                         "")),
    ('register_tools',
     lambda root: _patch(root, 'ps_regview.py',
                         "        self._click(self.assign_button,\n                    lambda sender, args: self.assign_revision())\n",
                         "")),
    ('register_tools',
     lambda root: _patch(root, 'ps_regview.py',
                         "        ps_ui.set_visible(self.sheet_tools, bool(keys))",
                         "        ps_ui.set_visible(self.sheet_tools, False)")),
    ('register_tools',
     lambda root: _patch(root, 'ps_regview.py',
                         "            menu.PlacementTarget = self.grid\n",
                         "")),
    ('register_tools',
     lambda root: _patch(root, 'ps_regview.py',
                         "            answer = ps_revaddwin.ask_edit(staging, key, self.host.theme_name,",
                         "            answer = ps_revaddwin.ask(staging, self.host.theme_name,")),
    ('register_tools',
     lambda root: _patch(root, 'ps_regview.py',
                         "            self.grid.Columns.Add(self._divider_column())\n",
                         "            pass\n")),
    ('register_tools',
     lambda root: _patch(root, 'ps_regview.py',
                         "                self.grid.Columns.Remove(self.plus_column)\n                self.grid.Columns.Add(self.plus_column)\n",
                         "                pass\n")),
    ('register_tools',
     lambda root: _patch(root, 'ps_model.py',
                         "            if name and not levels[depth]:",
                         "            if name:")),
    ('register_tools',
     lambda root: _patch(root, 'ps_model.py',
                         "    for name in list(levels or []) + [VIEW_TYPE_COLUMN]:",
                         "    for name in list(levels or []):")),
    ('register_tools',
     lambda root: _patch(root, 'ps_window.py',
                         "            extras = browser\n",
                         "            extras = []\n")),
    ('register_tools',
     lambda root: _patch(root, 'ps_window.py',
                         "        levels = wanted[:self.MAX_SORT_LEVELS - 1]",
                         "        levels = wanted[:1]")),
    ('register_tools',
     lambda root: _patch(root, 'ps_window.py',
                         "            self._apply_default_sort()\n        self._build_columns()\n",
                         "        self._build_columns()\n")),
    ('register_tools',
     lambda root: _patch(root, 'ps_window.py',
                         "            self.browser_names = ps_model.browser_columns(\n                ps_model.browser_folder_parameters(self.doc, self.rows))",
                         "            self.browser_names = ps_model.browser_columns([])")),
    # 1.42.0 - staged sheet revision edits, Undo / Redo, reveal on isolate.
    ('register_staging',
     lambda root: _patch(root, 'ps_register.py',
                         "                if kind == 'change':\n                    held.add(edit['target'])\n",
                         "")),
    ('register_staging',
     lambda root: _patch(root, 'ps_register.py',
                         "        self.edits.append(edit)\n        self.undone = []\n",
                         "        self.edits.append(edit)\n")),
    ('register_staging',
     lambda root: _patch(root, 'ps_register.py',
                         "        before = len(self.edits)\n        self.edits = [",
                         "        before = len(self.edits)\n        return 0\n        self.edits = [")),
    ('register_staging',
     lambda root: _patch(root, 'ps_register.py',
                         "            if sheet not in included and\n",
                         "            if True and\n")),
    ('register_staging',
     lambda root: _patch(root, 'ps_regview.py',
                         "                    entry[column] = u'+' if flag == ps_register.PENDING_ADD \\\n                        else base\n",
                         "                    entry[column] = base\n")),
    ('register_staging',
     lambda root: _patch(root, 'ps_regview.py',
                         "        if flag:\n            return flag == ps_register.PENDING_ADD\n",
                         "")),
    ('register_staging',
     lambda root: _patch(root, 'ps_regview.py',
                         "        self._paint_pending()\n        self.host.say(u'Undone",
                         "        self.host.say(u'Undone")),
    ('register_staging',
     lambda root: _patch(root, 'ps_regview.py',
                         "            if key == Key.Z:\n                self.undo()",
                         "            if key == Key.Y:\n                self.undo()")),
    ('register_staging',
     lambda root: _patch(root, 'ps_regview.py',
                         "            return isinstance(Keyboard.FocusedElement, TextBox)",
                         "            return False")),
    ('register_staging',
     lambda root: _patch(root, 'ps_regview.py',
                         "        self._sync_headings()\n        self._paint_pending()\n",
                         "        self._sync_headings()\n")),
    ('register_staging',
     lambda root: _patch(root, 'ps_regview.py',
                         "        self.pending.prune(known, set(self.rows_by_key),\n                           set([field.id for field in self.issue_fields]))\n",
                         "")),
    ('register_staging',
     lambda root: _patch(root, 'ps_regview.py',
                         "    u'<Setter Property=\"TextDecorations\" Value=\"Strikethrough\"/>'\n",
                         "")),
    ('register_staging',
     lambda root: _patch(root, 'ps_regview.py',
                         "            self.set_show('all')\n        return len(hidden)",
                         "            pass\n        return len(hidden)")),
    ('register_staging',
     lambda root: _patch(root, 'ps_regview.py',
                         "        revealed = self._reveal_isolated()\n",
                         "        revealed = 0\n")),
    ('register_staging',
     lambda root: _patch(root, 'ps_regview.py',
                         "        self._set_picked_cells(set())\n        self._stage(edit)\n\n    def _picks_by_sheet(",
                         "        self._set_picked_cells(set())\n        self._run_edit(self.host.doc, edit, {}, False)\n\n    def _picks_by_sheet(")),
    ('register_staging',
     lambda root: _patch(root, 'ps_regview.py',
                         "            results = [self._run_edit(doc, edit, sheets, False)\n                       for edit in others]",
                         "            results = [self._run_edit(doc, edit, sheets, False)\n                       for edit in reversed(others)]")),
    ('register_staging',
     lambda root: _patch(root, 'ps_window.py',
                         "            if not self.register.can_close():\n                return\n",
                         "            pass\n")),
    ('register_staging',
     lambda root: _patch(root, 'ProSheetsRevAdd.xaml',
                         'Width="74" Height="44"\n                           MinHeight="44"',
                         'Width="74" Height="32"\n                           MinHeight="24"')),
    # 1.44.0 - the TIDP register.
    ('register_tidp',
     lambda root: _patch(root, 'ps_revdata.py',
                         "                                 escape(column.parameter),\n                                 escape(column.group)]))",
                         "                                 escape(column.parameter)]))")),
    ('register_tidp',
     lambda root: _patch(root, 'ps_revdata.py',
                         "    if version == FORMAT:\n        columns = with_groups(columns)\n",
                         "")),
    ('register_tidp',
     lambda root: _patch(root, 'ps_revdata.py',
                         "        if self.group in (ISSUED_TO, METHOD):\n            # Ticked or not, per revision: where the issue went, and how.\n            self.kind = 'yesno'",
                         "        if False:\n            self.kind = 'yesno'")),
    ('register_tidp',
     lambda root: _patch(root, 'ps_revdata.py',
                         "            if True in ticks:\n                rows.append",
                         "            if True:\n                rows.append")),
    ('register_tidp',
     lambda root: _patch(root, 'ps_revdata.py',
                         "    ranks = {u'': 0, STATUS: 1, ISSUED_TO: 2, METHOD: 3}",
                         "    ranks = {u'': 0, STATUS: 1, ISSUED_TO: 3, METHOD: 2}")),
    ('register_tidp',
     lambda root: _patch(root, 'ps_revisions.py',
                         "            if not wanted or not entry.live or \\\n                    self.custom_value(entry, column):",
                         "            if not wanted or not entry.live:")),
    ('register_tidp',
     lambda root: _patch(root, 'ps_revisions.py',
                         "    return sorted(order, key=lambda one: (-counts[one], order.index(one)))[0]\n\n\ndef read(",
                         "    return order[-1]\n\n\ndef read(")),
    ('register_tidp',
     lambda root: _patch(root, 'ps_revisions.py',
                         "            if column.kind != 'yesno' or group not in movable or \\\n",
                         "            if group not in movable or \\\n")),
    ('register_tidp',
     lambda root: _patch(root, 'ps_register.py',
                         "        for element in (sheet, block):",
                         "        for element in (block, sheet):")),
    ('register_tidp',
     lambda root: _patch(root, 'ps_regexport.py',
                         "        if not stored:\n            stored = common_status(",
                         "        if True:\n            stored = common_status(")),
    ('register_tidp',
     lambda root: _patch(root, 'ps_revwin.py',
                         "                keep_groups(ordered, self._group_of)]",
                         "                ordered]")),
    ('register_tidp',
     lambda root: _patch(root, 'ps_revwin.py',
                         "        if band and runs and runs[-1][0] == band and \\\n",
                         "        if False and \\\n")),
    ('register_tidp',
     lambda root: _patch(root, 'ps_config.py',
                         "                    ('reg_snapshot', u'Asite Snapshot', u'Current Rev')):",
                         "                    ):")),
    ('register_tidp',
     lambda root: _patch(root, 'ps_regview.py',
                         "            info.revision_columns, info.revision_values = \\\n                ps_revdata.read(self.host.doc)",
                         "            info.revision_columns, info.revision_values = [], {}")),
    ('register_tidp',
     lambda root: _patch(root, 'ProSheets.xaml',
                         'Style="{DynamicResource PrimaryButton}"\n                        IsEnabled="False" Margin="0,6,2,0"',
                         'Style="{DynamicResource ChipButton}"\n                        IsEnabled="False" Margin="0,6,2,0"')),
    ('register_xlsx',
     lambda root: _patch(root, 'ps_regexport.py',
                         "        if self.split and row == self.split and col > COL_NUMBER:\n            bottom = u'medium'\n",
                         "")),
    ('register_xlsx',
     lambda root: _patch(root, 'ps_regexport.py',
                         "            form.put(row, first_issue + offset, u'x' if went else None,",
                         "            form.put(row, first_issue + offset, u'x' if True else None,")),
    ('register_xlsx',
     lambda root: _patch(root, 'ps_regexport.py',
                         "    current = COL_CURRENT if snapshot else 0\n    first_issue = COL_CURRENT + 1 if snapshot else COL_CURRENT",
                         "    current = COL_CURRENT if snapshot else 0\n    first_issue = COL_CURRENT")),
    ('register_xlsx',
     lambda root: _patch(root, 'ps_regexport.py',
                         "        form.block(3, col, 5, col, text or None, size=8, bold=True,\n                   h=u'center', rotate=90, fill=HEAD_FILL)",
                         "        form.block(3, col, 5, col, text or None, size=8, bold=True,\n                   h=u'center', fill=HEAD_FILL)")),
    # 1.45.0 - the Revision Manager's bands, full width, the column types.
    ('register_tidp',
     lambda root: _patch(root, 'ps_revwin.py',
                         "        if field in [entry[0] for entry in COLUMNS]:\n            return STANDARD\n",
                         "")),
    ('register_tidp',
     lambda root: _patch(root, 'ps_revwin.py',
                         "            return column.group or CUSTOM",
                         "            return CUSTOM")),
    ('register_tidp',
     lambda root: _patch(root, 'ps_revwin.py',
                         "         (ps_revdata.STATUS, u'Issue Status', 'SortL5', False),",
                         "         (ps_revdata.STATUS, u'Issue Status', 'GreenBrush', False),")),
    ('register_tidp',
     lambda root: _patch(root, 'ps_revwin.py',
                         "                self.grid.LayoutUpdated += self._paint_bands\n",
                         "")),
    ('register_tidp',
     lambda root: _patch(root, 'ps_revwin.py',
                         "            self.window.ContentRendered += self._fit_window\n",
                         "            pass\n")),
    ('register_tidp',
     lambda root: _patch(root, 'ps_revwin.py',
                         "            self.grid.FrozenColumnCount = 1\n",
                         "            pass\n")),
    ('register_tidp',
     lambda root: _patch(root, 'ps_ui.py',
                         "    return max(float(minimum), min(float(needed),\n                                   float(area_width) - 2 * margin))",
                         "    return max(float(minimum), float(needed))")),
    ('register_tidp',
     lambda root: _patch(root, 'ps_revwin.py',
                         "        finally:\n            try:\n                self.window.Opacity = 1",
                         "        else:\n            try:\n                self.window.Opacity = 1")),

    ('register_tidp',
     lambda root: _patch(root, 'ps_revcolwin.py',
                         "    NO_GROUP = u'Custom'",
                         "    NO_GROUP = u'None - a column of its own'")),
    ('register_tidp',
     lambda root: _patch(root, 'ps_config.py',
                         "            if get_text(self.store, 'reg_title', TIDP_TITLE) == TIDP_TITLE:\n                self.store['reg_title'] = RD9_TITLE\n",
                         "            pass\n")),
    # 1.46.0 - the All tab ticked into the export.
    ('register_tidp',
     lambda root: _patch(root, 'ps_regexport.py',
                         "    if ps_register.all_ticked(skip) and rows:\n        out.insert(0, (ps_register.ALL_TAB, list(rows)))\n",
                         "")),
    ('register_tidp',
     lambda root: _patch(root, 'ps_register.py',
                         "    if label == ALL_TAB:\n        return all_ticked(skip)\n    return label not in set(skip or ())",
                         "    return label not in set(skip or ())")),
    ('register_tidp',
     lambda root: _patch(root, 'ps_register.py',
                         "        marked = wanted\n        label = ALL_INCLUDED",
                         "        marked = not wanted\n        label = ALL_INCLUDED")),
    ('register_tidp',
     lambda root: _patch(root, 'ps_regexport.py',
                         "        if len(tabs) > 1:\n            return [(label, _series_groups(members, info))\n                    for label, members in tabs]\n",
                         "")),
    ('register_tidp',
     lambda root: _patch(root, 'ps_regview.py',
                         "            if several:\n                # The All tab's tick",
                         "            if several and label != ps_register.ALL_TAB:\n                # The All tab's tick")),
    # 1.46.0 - the Issued to borders, the bottom bar's double-click.
    ('register_xlsx',
     lambda root: _patch(root, 'ps_regexport.py',
                         "            if col == COL_TITLE:\n                left = u'medium'\n            if col == self.first_issue:\n                left = u'thin'",
                         "            if col == self.first_issue:\n                left = u'thin'")),
    ('register_xlsx',
     lambda root: _patch(root, 'ps_regexport.py',
                         "            if row == self.issued[0]:\n                top = u'medium'\n",
                         "")),
    ('register_xlsx',
     lambda root: _patch(root, 'ps_regexport.py',
                         "            if col == self.first_issue:\n                left = u'thin'\n            if col == self.first_issue - 1:\n                right = u'thin'\n        return",
                         "        return")),
    ('register_tidp',
     lambda root: _patch(root, 'ps_ui.py',
                         "    return float(area[1]), float(area[3]), (float(top), float(height))",
                         "    return float(area[1]), float(height), (float(top), float(height))")),
    ('register_tidp',
     lambda root: _patch(root, 'ps_revwin.py',
                         "                footer.MouseLeftButtonDown += self._footer_click\n",
                         "                pass\n")),
    ('register_xlsx',
     lambda root: _patch(root, 'ps_regexport.py',
                         "    for path in (info.logo, info.client_logo):",
                         "    for path in (info.client_logo, info.logo):")),
    # 1.46.0 - clouds off sheets, Find clouds on views.
    ('register_tidp',
     lambda root: _patch(root, 'ps_revisions.py',
                         "        found.setdefault(revision, {}).setdefault(view, []).append(cloud)",
                         "        found.setdefault(revision, {}).setdefault(revision, []).append(cloud)")),
    ('register_tidp',
     lambda root: _patch(root, 'ps_revisions.py',
                         "                              entry.used, entry.clouds, entry.unplaced))",
                         "                              entry.used, entry.clouds, 0))")),
    ('register_tidp',
     lambda root: _patch(root, 'ps_revisions.py',
                         "            view.IsolateElementsTemporary(_id_list(clouds))\n",
                         "            pass\n")),
    ('register_tidp',
     lambda root: _patch(root, 'ps_revisions.py',
                         "    for view, _clouds in reversed(views):",
                         "    for view, _clouds in views:")),
    ('register_tidp',
     lambda root: _patch(root, 'ps_revwin.py',
                         "            self.on_find(views)\n",
                         "            pass\n")),
    ('register_tidp',
     lambda root: _patch(root, 'ps_regview.py',
                         "        find = manager.find_request\n",
                         "        find = None\n")),
    ('register_tidp',
     lambda root: _patch(root, 'ps_revwin.py',
                         "        ordered = place_after(column_order([entry[0] for entry in out],\n                                           saved), saved, 'unplaced',\n                              'series')",
                         "        ordered = column_order([entry[0] for entry in out], saved)")),
    # 1.47.0 - the top and bottom edges' double-click.
    ('register_tidp',
     lambda root: _patch(root, 'ps_ui.py',
                         "                    thumb.PreviewMouseLeftButtonDown += self._edge_down\n",
                         "                    pass\n")),
    ('register_tidp',
     lambda root: _patch(root, 'ps_ui.py',
                         "            if args.ClickCount != 2:\n                return\n            args.Handled = True\n        except Exception:\n            return\n        self.toggle_tall()",
                         "            args.Handled = True\n        except Exception:\n            return\n        self.toggle_tall()")),
    ('register_tidp',
     lambda root: _patch(root, 'ps_ui.py',
                         "        if self.full_screen or self.shrunk:\n            return None\n        area = working_area(self.window)",
                         "        if self.shrunk:\n            return None\n        area = working_area(self.window)")),
    ('register_tidp',
     lambda root: _patch(root, 'ps_revwin.py',
                         "        stretched = self.chrome.toggle_tall()",
                         "        stretched = None")),
    # Express print: the window built and shown after the run answered.
    ('express_print',
     lambda root: _patch(root, 'script.py',
                         '        if ps_express.run(uiapp, HERE):\n            return\n',
                         '        ps_express.run(uiapp, HERE)\n')),
    # The hook moved after the window is built.
    ('express_print',
     lambda root: _patch(root, 'script.py',
                         "        import ps_express\n        if ps_express.run(uiapp, HERE):\n            return\n\n        stage = 'building the window'\n        ps_window.show(uiapp)",
                         "        stage = 'building the window'\n        ps_window.show(uiapp)\n        import ps_express\n        if ps_express.run(uiapp, HERE):\n            return")),
    # Sheets matched by number only.
    ('express_print',
     lambda root: _patch(root, 'ps_express.py',
                         '        key = by_uid.get(uid) if uid else None',
                         '        key = None')),
    # The number fallback let loose on views.
    ('express_print',
     lambda root: _patch(root, 'ps_express.py',
                         "        if not getattr(row, 'is_sheet', False):\n            continue\n        uid = ",
                         "        uid = ")),
    # The template's own ticks left in.
    ('express_print',
     lambda root: _patch(root, 'ps_express.py',
                         "            entry['sel'] = key in wanted",
                         "            if key in wanted:\n                entry['sel'] = True")),
    # A plain Print run headless.
    ('express_print',
     lambda root: _patch(root, 'ps_express.py',
                         "    if not as_flag(request.get('headless')):",
                         "    if False:")),
    # No Project Browser Pro: the tab itself taken for its folder.
    ('express_print',
     lambda root: _patch(root, 'ps_express.py',
                         '    return None\n\n\ndef load_handoff',
                         '    return tab\n\n\ndef load_handoff')),
    # An exception swallowed - the browser waits for its timeout.
    ('express_print',
     lambda root: _patch(root, 'ps_express.py',
                         "        _fail(handoff, folder, token, u'Pro Sheets stopped: {0}'.format(err))",
                         "        pass")),
    # The browser only looked for in the Management panel.
    ('express_print',
     lambda root: _patch(root, 'ps_express.py',
                         "            if HANDOFF_MODULE + '.py' in files:",
                         "            if False:")),
    # The browser's folder inserted ahead of Pro Sheets'.
    ('express_print',
     lambda root: _patch(root, 'ps_express.py',
                         '        sys.path.append(folder)',
                         '        sys.path.insert(0, folder)')),
    # The report window left in.
    ('express_print',
     lambda root: _patch(root, 'ps_express.py',
                         '    win._show_report = lambda report: reports.append(report)',
                         '    pass')),
    # Suppression only handed back by a run that finished.
    ('express_print',
     lambda root: _patch(root, 'ps_express.py',
                         '        ps_export.end_suppression()\n\n    report =',
                         '        pass\n\n    report =')),
    # The setup check never put back.
    ('express_print',
     lambda root: _patch(root, 'ps_express.py',
                         '        setup.needed = needed\n',
                         '        pass\n')),
    # The setup check not held off for the build.
    ('express_print',
     lambda root: _patch(root, 'ps_express.py',
                         '    setup.needed = lambda *args, **kwargs: False\n',
                         '')),
    # A driver with no staging folder kept.
    ('express_print',
     lambda root: _patch(root, 'ps_express.py',
                         '    if win._pdf_blocker(formats):',
                         '    if False:')),
    # No progress to the browser's strip.
    ('express_print',
     lambda root: _patch(root, 'ps_express.py',
                         '    win._progress = progress\n',
                         '')),
    # A refusal that never tells the browser.
    ('express_print',
     lambda root: _patch(root, 'ps_express.py',
                         "        handoff.finish(folder, token, False, u'', 0, message)",
                         "        pass")),
    # The hidden window left open.
    ('express_print',
     lambda root: _patch(root, 'ps_express.py',
                         '        _close_quietly(win)',
                         '        pass')),
    # Heading ramps: a ramp that is not the browser's.
    ('heading_ramps',
     lambda root: _patch(root, 'ps_ramp.py',
                         "    ELECTRICAL: ('#17572B', '#A9DFA6'),",
                         "    ELECTRICAL: ('#17572C', '#A9DFA6'),")),
    # The main headings spread over half the ramp.
    ('heading_ramps',
     lambda root: _patch(root, 'ps_ramp.py',
                         '    1: (0.0, 0.3),', '    1: (0.0, 0.5),')),
    # Fire protection lost from "other".
    ('heading_ramps',
     lambda root: _patch(root, 'ps_ramp.py',
                         "    (OTHER, ['FIRE PROTECTION',",
                         "    (OTHER, ['FIRE PROTECTIONS',")),
    # Words matched inside words: SOLVENT is LV.
    ('heading_ramps',
     lambda root: _patch(root, 'ps_ramp.py',
                         "            if u' ' + word + u' ' in padded:",
                         "            if word in padded:")),
    # White on the light end.
    ('heading_ramps',
     lambda root: _patch(root, 'ps_ramp.py',
                         "    if contrast(hex_text, u'#000000') >= contrast(hex_text, u'#FFFFFF'):",
                         "    if contrast(hex_text, u'#000000') <= contrast(hex_text, u'#FFFFFF'):")),
    # A series naming nothing loses its discipline's trade.
    ('heading_ramps',
     lambda root: _patch(root, 'ps_ramp.py',
                         '        trade = trade_of(label) or trades.get(parent) or fallback or OTHER',
                         '        trade = trade_of(label) or fallback or OTHER')),
    # Every heading of a trade the same shade.
    ('heading_ramps',
     lambda root: _patch(root, 'ps_ramp.py',
                         '                low + (high - low) * index / float(count - 1)',
                         '                low')),
    # The register painted from the old hue cycle.
    ('heading_ramps',
     lambda root: _patch(root, 'ps_regview.py',
                         '            _cell, wash, head = self.host._shade_brushes(place)',
                         '            _cell, wash, head = self.host._run_brushes(0)')),
    # A discipline's tab forgetting its trade.
    ('heading_ramps',
     lambda root: _patch(root, 'ps_regview.py',
                         '        inherit = None if by_discipline else self.tab_label',
                         '        inherit = None')),
    # The All tab's disciplines not matching the tab strip.
    ('heading_ramps',
     lambda root: _patch(root, 'ps_regview.py',
                         '                    found[hid] = self.disc_colour[label]',
                         '                    pass')),
    # A register heading with no text colour.
    ('heading_ramps',
     lambda root: _patch(root, 'ps_regview.py',
                         "            head['gink'] = self.host._ink_brush(place)",
                         "            pass")),
    # Blue heading text again.
    ('heading_ramps',
     lambda root: _patch(root, 'Theme.xaml',
                         '        <Setter Property="Foreground" Value="{Binding gink}"/>',
                         '        <Setter Property="Foreground" Value="{DynamicResource BlueBrush}"/>')),
    # Grid lines across the pill.
    ('heading_ramps',
     lambda root: _patch(root, 'Theme.xaml',
                         '        <Setter Property="BorderBrush" Value="Transparent"/>\n        <Setter Property="FontSize" Value="14"/>',
                         '        <Setter Property="FontSize" Value="14"/>')),
    # The pill with no shadow.
    ('heading_ramps',
     lambda root: _patch(root, 'Theme.xaml',
                         '        <Border.Effect>\n          <DropShadowEffect BlurRadius="5"',
                         '        <Border.Tag>\n          <DropShadowEffect BlurRadius="5"')),
    # Heading rows square again.
    ('heading_ramps',
     lambda root: _patch(root, 'Theme.xaml',
                         '        <Setter Property="Template" Value="{StaticResource HeadingRowTemplate}"/>\n',
                         '')),
    # The Selection tab's groups not planned.
    ('heading_ramps',
     lambda root: _patch(root, 'ps_window.py',
                         '            self._plan_runs([run[0] for run in runs])\n',
                         '')),
    # A Selection heading with no text colour.
    ('heading_ramps',
     lambda root: _patch(root, 'ps_window.py',
                         "                heading['gink'] = self._ink_brush(self._run_hex(place))\n",
                         '')),
    # Shrink drawer: a dialog with no shrink button.
    ('shrink_drawer',
     lambda root: _patch(root, 'ProSheetsRevAdd.xaml',
                         'x:Name="ShrinkButton"', 'x:Name="ShrinkButtonGone"')),
    # The main window with none.
    ('shrink_drawer',
     lambda root: _patch(root, 'ProSheets.xaml',
                         'x:Name="ShrinkButton"', 'x:Name="ShrinkButtonGone"')),
    # A shrink button in the wrong style.
    ('shrink_drawer',
     lambda root: _patch(root, 'ProSheetsRevisions.xaml',
                         'x:Name="ShrinkButton" Style="{DynamicResource ShrinkButton}"',
                         'x:Name="ShrinkButton" Style="{DynamicResource IconButton}"')),
    # The up arrow not green.
    ('shrink_drawer',
     lambda root: _patch(root, 'Theme.xaml',
                         'Fill="{DynamicResource GreenBrush}"\n                    Data="M 7,0',
                         'Fill="{DynamicResource BlueBrush}"\n                    Data="M 7,0')),
    # The glyph as one shared element.
    ('shrink_drawer',
     lambda root: _patch(root, 'Theme.xaml',
                         '    <Setter Property="ToolTip" Value="Shrink to the bottom of the screen"/>\n    <Setter Property="ContentTemplate">',
                         '    <Setter Property="ToolTip" Value="Shrink to the bottom of the screen"/>\n    <Setter Property="Content2">')),
    # The button never wired.
    ('shrink_drawer',
     lambda root: _patch(root, 'ps_ui.py',
                         '                shrink_button.Click += self._shrink_clicked',
                         '                pass')),
    # The bar's height without the window's edge.
    ('shrink_drawer',
     lambda root: _patch(root, 'ps_ui.py',
                         '            return float(header.ActualHeight + 2 * max(0.0, offset))',
                         '            return float(header.ActualHeight)')),
    # Shrunk to the top of the screen.
    ('shrink_drawer',
     lambda root: _patch(root, 'ps_ui.py',
                         '    bottom = float(area[1]) + float(area[3]) - float(margin)',
                         '    bottom = float(area[1]) + float(margin)')),
    # No drawer: a jump.
    ('shrink_drawer',
     lambda root: _patch(root, 'ps_ui.py',
                         '        self._animate(window.Top, window.Height, top, bar, self._shrunk_done)',
                         '        window.Top = top\n        window.Height = bar\n        self._shrunk_done()')),
    # MinHeight left on.
    ('shrink_drawer',
     lambda root: _patch(root, 'ps_ui.py',
                         '            window.MinHeight = 0\n', '')),
    # The body left showing under the bar.
    ('shrink_drawer',
     lambda root: _patch(root, 'ps_ui.py',
                         '                child.Visibility = Visibility.Collapsed\n',
                         '                pass\n')),
    # No green arrow.
    ('shrink_drawer',
     lambda root: _patch(root, 'ps_ui.py',
                         "            button.Tag = u'shrunk' if self.shrunk else u''",
                         "            button.Tag = u''")),
    # The shrunk bar's size taken as the window's.
    ('shrink_drawer',
     lambda root: _patch(root, 'ps_ui.py',
                         '        if self.shrink_saved is not None:\n            return self.shrink_saved[2]',
                         '        if False:\n            return self.shrink_saved[2]')),
    # A shrunk bar stretched by an edge double-click.
    ('shrink_drawer',
     lambda root: _patch(root, 'ps_ui.py',
                         '        if self.full_screen or self.shrunk:\n            return None',
                         '        if self.full_screen:\n            return None')),
    # A shrunk bar sent full screen.
    ('shrink_drawer',
     lambda root: _patch(root, 'ps_ui.py',
                         '        if self.shrunk:\n            return\n        self.set_full_screen(not self.full_screen)',
                         '        self.set_full_screen(not self.full_screen)')),
    # Double-clicking the bar does not bring it back.
    ('shrink_drawer',
     lambda root: _patch(root, 'ps_ui.py',
                         '                if self.shrunk:\n                    self.expand()\n                    return\n',
                         '')),
    # MinHeight never put back.
    ('shrink_drawer',
     lambda root: _patch(root, 'ps_ui.py',
                         '                self.window.MinHeight = saved[4]',
                         '                pass')),
    # Expanding as a jump.
    ('shrink_drawer',
     lambda root: _patch(root, 'ps_ui.py',
                         '        self._animate(self.window.Top, self.window.Height, saved[1],\n                      saved[3], done)',
                         '        self.window.Top = saved[1]\n        self.window.Height = saved[3]\n        done()')),
    # The body not brought back.
    ('shrink_drawer',
     lambda root: _patch(root, 'ps_ui.py',
                         '        self._show_parts()\n        self.shrunk = False\n        if self in _SHRUNK:',
                         '        self.shrunk = False\n        if self in _SHRUNK:')),
    # A dialog shrinking alone, its owner still over Revit.
    ('shrink_drawer',
     lambda root: _patch(root, 'ps_ui.py',
                         '        if owner is not None and not owner.shrunk:\n            if owner.shrink():',
                         '        if False:\n            if owner.shrink():')),
    # Bars piled on top of each other.
    ('shrink_drawer',
     lambda root: _patch(root, 'ps_ui.py',
                         '            below = [other.bar_height() for other in _SHRUNK]',
                         '            below = []')),
    # The owner left down when the dialog comes back.
    ('shrink_drawer',
     lambda root: _patch(root, 'ps_ui.py',
                         '            if owner is not None:\n                owner.expand()\n            try:\n                self.window.Activate()',
                         '            try:\n                self.window.Activate()')),
    # The owner left down when the dialog is closed from its bar.
    ('shrink_drawer',
     lambda root: _patch(root, 'ps_ui.py',
                         '\n        if owner is not None:\n            owner.expand()',
                         '\n        pass')),
    # restore_now does nothing.
    ('shrink_drawer',
     lambda root: _patch(root, 'ps_ui.py',
                         '            (self.window.Left, self.window.Top, self.window.Width,\n             self.window.Height, self.window.MinHeight) = saved',
                         '            pass')),
    # The shrunk bar remembered as the window size.
    ('shrink_drawer',
     lambda root: _patch(root, 'ps_window.py',
                         '            width, height = self.chrome.true_size()\n            self.settings.set',
                         '            width, height = self.window.Width, self.window.Height\n            self.settings.set')),
    # Dark: the house near-black body again.
    ('revit_dark',
     lambda root: _patch(root, 'theme.py',
                         "    'WindowBg':        '#3C4454',",
                         "    'WindowBg':        '#232326',")),
    # Dark: Theme.xaml's defaults left on the old colours.
    ('revit_dark',
     lambda root: _patch(root, 'Theme.xaml',
                         '<SolidColorBrush x:Key="BarBg"           Color="#222933"/>',
                         '<SolidColorBrush x:Key="BarBg"           Color="#1C1C1F"/>')),
    # Dark: the old blue, too dim on Revit's lighter body.
    ('revit_dark',
     lambda root: _patch(root, 'theme.py',
                         "    'BlueBrush':       '#5AAEEB',",
                         "    'BlueBrush':       '#3F7FB3',")),
    # Dark: the old muted grey, too dim on the body.
    ('revit_dark',
     lambda root: _patch(root, 'theme.py',
                         "    'MutedBrush':      '#A4AAB1',",
                         "    'MutedBrush':      '#7A7F86',")),
    # Shrink drawer (1.50.0): the body not pinned for the slide.
    ('shrink_drawer',
     lambda root: _patch(root, 'ps_ui.py',
                         '        self._pin(window.Height)\n', '')),
    # The body left pinned once shrunk.
    ('shrink_drawer',
     lambda root: _patch(root, 'ps_ui.py',
                         '        self._hide_parts()\n        self._unpin()',
                         '        self._hide_parts()')),
    # The bar dragged mid-export.
    ('shrink_drawer',
     lambda root: _patch(root, 'ps_ui.py',
                         '                if self.busy is not None and self.busy():\n                    return\n',
                         '')),
    # The main window never says it is exporting.
    ('shrink_drawer',
     lambda root: _patch(root, 'ps_window.py',
                         '        self.chrome.busy = lambda: bool(self.exporting)\n',
                         '')),
    # A dialog centred on a shrunk bar, mostly off the screen.
    ('shrink_drawer',
     lambda root: _patch(root, 'ps_ui.py',
                         '        if owner is None or not owner.shrunk:\n            return\n        area = working_area(owner.window)',
                         '        return\n        area = working_area(owner.window)')),
    # No Ctrl+Shift+H.
    ('shrink_drawer',
     lambda root: _patch(root, 'ps_ui.py',
                         '            if key == Key.H and control and shift:',
                         '            if False:')),
    # Escape on a shrunk dialog reaching its Cancel.
    ('shrink_drawer',
     lambda root: _patch(root, 'ps_ui.py',
                         '            if self.shrunk and key in (Key.Escape, Key.Enter, Key.Return,',
                         '            if self.shrunk and key in (Key.Enter, Key.Return,')),
    # A tick that throws escapes to the dispatcher, the drawer stuck.
    ('shrink_drawer',
     lambda root: _patch(root, 'ps_ui.py',
                         '            except Exception:\n                progress = 1.0',
                         '            except Exception:\n                raise')),
    # Issue block (1.51.0): a plain column shown as a row.
    ('register_issue_block',
     lambda root: _patch(root, 'ps_revdata.py',
                         '        block.extend([column for column in columns if column.group == group])',
                         '        block.extend([column for column in columns if column.group in (group, u\'\')])')),
    # No medium line between the groups.
    ('register_issue_block',
     lambda root: _patch(root, 'ps_revdata.py',
                         "        elif column.group == STATUS or following.group != column.group:",
                         "        elif column.group == STATUS:")),
    # An empty Yes/No compared as different from an unticked one.
    ('register_issue_block',
     lambda root: _patch(root, 'ps_revdata.py',
                         "        return u'1' if text == u'1' else u'0'\n    return text",
                         "        return text\n    return text")),
    # A refused value stored anyway.
    ('register_issue_block',
     lambda root: _patch(root, 'ps_revdata.py',
                         "        if not ok:\n            problems.append(stored)\n            continue\n        out.setdefault",
                         "        out.setdefault")),
    # Edits played out of order.
    ('register_issue_block',
     lambda root: _patch(root, 'ps_register.py',
                         "    for edit in edits or []:\n        if edit.get('kind') == META:",
                         "    for edit in reversed(edits or []):\n        if edit.get('kind') == META:")),
    # An edited-back cell still washed.
    ('register_issue_block',
     lambda root: _patch(root, 'ps_register.py',
                         "                if value != u'{0}'.format(stored.get(cell, u''))])",
                         "                if cell in stored or value])")),
    # A read keeping edits on a gone column.
    ('register_issue_block',
     lambda root: _patch(root, 'ps_register.py',
                         "                if fields is not None and edit.get('field') not in fields:\n                    return None\n",
                         "")),
    # Same value staged again.
    ('register_issue_block',
     lambda root: _patch(root, 'ps_regview.py',
                         "        if self.issue_values().get(cell, u'') == stored:\n            return None\n",
                         "")),
    # Staged but not washed.
    ('register_issue_block',
     lambda root: _patch(root, 'ps_regview.py',
                         "                        row.SetResourceReference(Border.BackgroundProperty,\n                                                 'GreenWashBrush')",
                         "                        row.ClearValue(Border.BackgroundProperty)")),
    # Undo not repainting the block.
    ('register_issue_block',
     lambda root: _patch(root, 'ps_regview.py',
                         "        self._paint_pending_buttons()\n        self._paint_issue_block()\n",
                         "        self._paint_pending_buttons()\n")),
    # Apply forgetting the issue data.
    ('register_issue_block',
     lambda root: _patch(root, 'ps_regview.py',
                         "                results.append(self._run_meta(doc, changes, keys_by_uid))",
                         "                pass")),
    # Written without pushing to the mapped parameters.
    ('register_issue_block',
     lambda root: _patch(root, 'ps_revdata.py',
                         "        _count, pushed = push(doc, columns, by_key)",
                         "        _count, pushed = 0, []")),
    # The headings' data never read.
    ('register_issue_block',
     lambda root: _patch(root, 'ps_regview.py',
                         "        self._read_issue_data()\n", "")),
    # A drawing heading with no room for the block.
    ('register_issue_block',
     lambda root: _patch(root, 'ps_regview.py',
                         "        panel.Children.Add(self._filter_button(col_id))\n        column.Header = self._under_block(panel, col_id)",
                         "        panel.Children.Add(self._filter_button(col_id))\n        column.Header = panel")),
    # The row names scrolling away with the revisions.
    ('register_issue_block',
     lambda root: _patch(root, 'ps_regview.py',
                         "                self.grid.LayoutUpdated += self._place_issue_labels",
                         "                pass")),
    # The names placed by their left edge, off the revisions.
    ('register_issue_block',
     lambda root: _patch(root, 'ps_regview.py',
                         "        return (float(right) - float(width), float(top))",
                         "        return (float(right), float(top))")),
    # The names' canvas gone from the layout.
    ('register_issue_block',
     lambda root: _patch(root, 'ProSheets.xaml',
                         'x:Name="RegisterIssueLabels"', 'x:Name="RegisterIssueLabelsGone"')),
    # The names' canvas painted, so it swallows every click on the grid.
    ('register_issue_block',
     lambda root: _patch(root, 'ProSheets.xaml',
                         '<Canvas x:Name="RegisterIssueLabels" Grid.Row="2" Grid.ColumnSpan="2"',
                         '<Canvas x:Name="RegisterIssueLabels" Grid.Row="2" Grid.ColumnSpan="2" Background="Transparent"')),
    # The drawing columns' names above the block again.
    ('register_issue_block',
     lambda root: _patch(root, 'ps_regview.py',
                         "        panel = StackPanel()\n        panel.Orientation = Orientation.Vertical\n        if self.block_shown():\n            spacer = Border()",
                         "        panel = StackPanel()\n        panel.Orientation = Orientation.Vertical\n        panel.Children.Add(self._footer(content))\n        if self.block_shown():\n            spacer = Border()")),
    # A revision's filter above its issue data.
    ('register_issue_block',
     lambda root: (_patch(root, 'ps_regview.py',
                          "        if self.block_shown():\n            panel.Children.Add(self._issue_piece(revision))\n        foot = StackPanel()",
                          "        foot = StackPanel()"),
                   _patch(root, 'ps_regview.py',
                          "        panel.Children.Add(self._footer(foot))\n",
                          "        panel.Children.Add(self._footer(foot))\n        if self.block_shown():\n            panel.Children.Add(self._issue_piece(revision))\n"))),
    # A click on the block including the revision.
    ('register_issue_block',
     lambda root: _patch(root, 'ps_regview.py',
                         "        frame.MouseLeftButtonDown += self._swallow\n", "")),
    # The border broken between revisions.
    ('register_issue_block',
     lambda root: _patch(root, 'ps_regview.py',
                         "    BLOCK_MARGIN = (-5, 6, -5, 6)",
                         "    BLOCK_MARGIN = (0, 6, 0, 6)")),
    # Painting a tick staging a change.
    ('register_issue_block',
     lambda root: _patch(root, 'ps_regview.py',
                         "        def handler(sender, args):\n            if self._issue_painting:\n                return\n            try:\n                ticked",
                         "        def handler(sender, args):\n            try:\n                ticked")),
    # Heading modes (1.52.0): Grey skipped by the button.
    ('heading_modes',
     lambda root: _patch(root, 'ps_ramp.py',
                         'HEADING_MODES = [COLOURED, GREY, CUSTOM]',
                         'HEADING_MODES = [COLOURED, CUSTOM, GREY]')),
    # A picked colour showing in Coloured headers too.
    ('heading_modes',
     lambda root: _patch(root, 'ps_ramp.py',
                         '        return custom or grey(level, theme_name)\n    return ramp',
                         '        return custom or grey(level, theme_name)\n    return custom or ramp')),
    # Custom headers starting from the trade colours, not grey.
    ('heading_modes',
     lambda root: _patch(root, 'ps_ramp.py',
                         '        return custom or grey(level, theme_name)',
                         '        return custom or ramp')),
    # One grey for both levels.
    ('heading_modes',
     lambda root: _patch(root, 'ps_ramp.py',
                         "    'dark': {1: '#2B313C', 2: '#4A5464'},",
                         "    'dark': {1: '#2B313C', 2: '#2B313C'},")),
    # Any text taken as a colour.
    ('heading_modes',
     lambda root: _patch(root, 'ps_ramp.py',
                         "        if char not in u'0123456789ABCDEF':\n            return None",
                         "        pass")),
    # Picked colours lost on save: split on the first '='.
    ('heading_modes',
     lambda root: _patch(root, 'ps_config.py',
                         "        name, mark, colour = u'{0}'.format(entry).rpartition(u'=')",
                         "        name, mark, colour = u'{0}'.format(entry).partition(u'=')")),
    # A pick that does not switch to Custom headers.
    ('heading_modes',
     lambda root: _patch(root, 'ps_regview.py',
                         "        if self.heading_mode != ps_ramp.CUSTOM:\n            self.set_heading_mode(ps_ramp.CUSTOM, quiet=True)",
                         "        if False:\n            self.set_heading_mode(ps_ramp.CUSTOM, quiet=True)")),
    # The mode not remembered.
    ('heading_modes',
     lambda root: _patch(root, 'ps_regview.py',
                         "        self._setting('reg_heading_mode', self.heading_mode)\n",
                         "")),
    # Series headings ignore the mode.
    ('heading_modes',
     lambda root: _patch(root, 'ps_regview.py',
                         "                    inner_colour = self.shown_colour(inner, 2, next_colour())",
                         "                    inner_colour = next_colour()")),
    # Tabs ignore the mode.
    ('heading_modes',
     lambda root: _patch(root, 'ps_regview.py',
                         "                colour = self.shown_colour(label, 1, colour)\n",
                         "")),
    # No colour menu on a heading.
    ('heading_modes',
     lambda root: _patch(root, 'ps_regview.py',
                         "        heading = getattr(self, '_menu_heading', None)\n        if heading:",
                         "        heading = getattr(self, '_menu_heading', None)\n        if False:")),
    # A stale heading kept for the next menu.
    ('heading_modes',
     lambda root: _patch(root, 'ps_regview.py',
                         "        self._menu_heading = None\n        try:\n            source = args.OriginalSource",
                         "        try:\n            source = args.OriginalSource")),
    # Swatches never shown.
    ('heading_modes',
     lambda root: _patch(root, 'ps_regview.py',
                         "            if action == 'heading_swatches':",
                         "            if False:")),
    # Grey not refreshed for the theme.
    ('heading_modes',
     lambda root: _patch(root, 'ps_regview.py',
                         "        if self.heading_mode == ps_ramp.GREY and self.loaded:",
                         "        if False:")),
    # The button gone.
    ('heading_modes',
     lambda root: _patch(root, 'ProSheets.xaml',
                         'x:Name="RegisterHeadingModeButton"', 'x:Name="RegisterHeadingModeGone"')),
    # Issue rows (1.53.0): a tick shown as Yes/No text.
    ('register_issue_rows',
     lambda root: _patch(root, 'ps_regview.py',
                         "            return u'x' if value == u'1' else u''",
                         "            return u'Yes' if value == u'1' else u'No'")),
    # The block drawn in the heading while unfrozen too.
    ('register_issue_rows',
     lambda root: _patch(root, 'ps_regview.py',
                         "        return bool(self.issue_fields) and \\\n            bool(getattr(self, 'issue_frozen', True))",
                         "        return bool(self.issue_fields)")),
    # Issue rows sorted among the drawings.
    ('register_issue_rows',
     lambda root: _patch(root, 'ps_regview.py',
                         "            entry['ord'] = u'!{0:03d}'.format(index)",
                         "            entry['ord'] = u'{0:06d}'.format(900000 + index)")),
    # Issue rows drawn muted.
    ('register_issue_rows',
     lambda root: _patch(root, 'ps_regview.py',
                         "            entry['sel'] = True\n", "")),
    # A staged value not washed.
    ('register_issue_rows',
     lambda root: _patch(root, 'ps_regview.py',
                         "                    flag = ps_register.PENDING_ADD if cell in changed \\\n                        else u''",
                         "                    flag = u''")),
    # A tick never flipped from its row.
    ('register_issue_rows',
     lambda root: _patch(root, 'ps_regview.py',
                         "            self.stage_issue(cell, u'0' if now == u'1' else u'1')",
                         "            self.stage_issue(cell, u'1')")),
    # Unfrozen with no rows.
    ('register_issue_rows',
     lambda root: _patch(root, 'ps_regview.py',
                         "            if self.issue_fields and not self.issue_frozen:\n                self._add_issue_rows()\n",
                         "")),
    # A click on an issue row picking a cell.
    ('register_issue_rows',
     lambda root: _patch(root, 'ps_regview.py',
                         "            self._issue_row_click(entry, self._column_under(source))\n",
                         "            self._cell_click(entry, self._column_under(source))\n")),
    # The header tick putting issue rows in the register.
    ('register_issue_rows',
     lambda root: _patch(root, 'ps_regview.py',
                         "        for entry in self.table.Rows:\n            if not self._is_drawing(entry):\n                continue\n            if u'{0}'.format(entry['show']) == u'1':",
                         "        for entry in self.table.Rows:\n            if self._is_heading(entry):\n                continue\n            if u'{0}'.format(entry['show']) == u'1':")),
    # A search hiding the issue rows.
    ('register_issue_rows',
     lambda root: _patch(root, 'ps_regview.py',
                         "                entry['vis'] = u'1'\n                entry['show'] = u'1'\n                continue\n",
                         "")),
    # Recycled rows keeping the lines.
    ('register_issue_rows',
     lambda root: _patch(root, 'ps_regview.py',
                         "                row.ClearValue(DataGridRow.BorderThicknessProperty)\n",
                         "")),
    # Opening unfrozen.
    ('register_issue_rows',
     lambda root: _patch(root, 'ps_regview.py',
                         "        self.issue_frozen = True\n",
                         "        self.issue_frozen = False\n")),
    # The freeze not rebuilding the grid.
    ('register_issue_rows',
     lambda root: _patch(root, 'ps_regview.py',
                         "        self._paint_freeze_button()\n        if self.loaded:\n            self.select_tab(self.tab_index)",
                         "        self._paint_freeze_button()\n        if False:\n            self.select_tab(self.tab_index)")),
    # Settings left on the toolbar.
    ('register_issue_rows',
     lambda root: (_patch(root, 'ProSheets.xaml',
                          '                  <Button x:Name="RegisterSetupButton" Content="Settings"',
                          '                  <Button x:Name="RegisterSetupGone" Content="Settings"'),
                   _patch(root, 'ProSheets.xaml',
                          '                <Button x:Name="RegisterRefreshButton"',
                          '                <Button x:Name="RegisterSetupButton" Content="Settings"/>\n                <Button x:Name="RegisterRefreshButton"'))),
    # The Revision Manager two rows high again.
    ('register_issue_rows',
     lambda root: _patch(root, 'ProSheets.xaml',
                         '                        Height="56" Padding="16,0" VerticalAlignment="Top"',
                         '                        Height="56" MinWidth="210" VerticalAlignment="Top"')),
    # The colour button back to a plain chip.
    ('register_issue_rows',
     lambda root: _patch(root, 'ProSheets.xaml',
                         'x:Name="RegisterHeadingModeButton"\n                        Style="{DynamicResource HeadingModeButton}"',
                         'x:Name="RegisterHeadingModeButton"\n                        Style="{DynamicResource ChipButton}"')),
    # The colour button restyled in code.
    ('register_issue_rows',
     lambda root: _patch(root, 'ps_regview.py',
                         "        ps_ui.set_text(self.heading_mode_text,\n                       ps_ramp.MODE_LABELS.get(self.heading_mode, u''))\n",
                         "        ps_ui.set_text(self.heading_mode_text,\n                       ps_ramp.MODE_LABELS.get(self.heading_mode, u''))\n        self.heading_mode_button.SetResourceReference(Button.StyleProperty, 'ChipButton')\n")),
    # Brand (1.54.0): placed over the drawing names.
    ('register_brand',
     lambda root: _patch(root, 'ps_regview.py',
                         '        tall = float(height) - float(footer) - 6 - margin',
                         '        tall = float(height) - 6 - margin')),
    # Logos stretched to the full height.
    ('register_brand',
     lambda root: _patch(root, 'ps_regview.py',
                         '        return (min(wide, 300.0), min(tall, 120.0))',
                         '        return (wide, tall)')),
    # Shown with the rows scrolling.
    ('register_brand',
     lambda root: _patch(root, 'ps_regview.py',
                         "        if canvas is None or not getattr(self, 'issue_frozen', True):",
                         "        if canvas is None:")),
    # Catching clicks.
    ('register_brand',
     lambda root: _patch(root, 'ps_regview.py',
                         '        panel.IsHitTestVisible = False\n        name = TextBlock()',
                         '        name = TextBlock()')),
    # Only with an issue block.
    ('register_brand',
     lambda root: (_patch(root, 'ps_regview.py',
                          '        self.label_block = None\n        self._build_brand()\n',
                          '        self.label_block = None\n'),
                   _patch(root, 'ps_regview.py',
                          '        widest = 0\n        frame, rows = self._block_frame(self.BLOCK_FRAME, 0)',
                          '        self._build_brand()\n        widest = 0\n        frame, rows = self._block_frame(self.BLOCK_FRAME, 0)'))),
    # Coloured by default.
    ('register_brand',
     lambda root: _patch(root, 'ps_regview.py',
                         "host.settings.text('reg_heading_mode', u'') or ps_ramp.GREY",
                         "host.settings.text('reg_heading_mode', u'') or ps_ramp.COLOURED")),
    # The register's picks kept from the Selection tab.
    ('register_brand',
     lambda root: _patch(root, 'ps_regview.py',
                         '            self.host.take_heading_colours(self.heading_custom)\n',
                         '            pass\n')),
    # The words under Settings back.
    ('register_brand',
     lambda root: _patch(root, 'ProSheets.xaml',
                         '<TextBlock x:Name="RegisterSource" Style="{DynamicResource MutedText}"\n                             Visibility="Collapsed" Text=""/>',
                         '<TextBlock x:Name="RegisterSource" Style="{DynamicResource MutedText}"\n                             Text=""/>')),
    # Refresh without its icon.
    ('register_brand',
     lambda root: _patch(root, 'ProSheets.xaml',
                         '                    <Path Width="12" Height="12" Margin="0,0,6,0" Stretch="Uniform"\n                          VerticalAlignment="Center"\n                          Fill="{Binding Foreground, RelativeSource={RelativeSource AncestorType=Button}}"\n                          Data="M 7,0 C 3.1,0',
                         '                    <Border Width="12" Height="12" Margin="0,0,6,0"\n                          VerticalAlignment="Center" Tag="M 7,0 C 3.1,0')),
    # One grey for every Selection run.
    ('register_brand',
     lambda root: _patch(root, 'ps_window.py',
                         '            level = 1 if int(place) % 2 == 0 else 2',
                         '            level = 1')),
    # Selection ignoring the picked colours.
    ('register_brand',
     lambda root: _patch(root, 'ps_window.py',
                         "            (getattr(self, 'heading_custom', None) or {}).get(label))",
                         "            None)")),
    # Selection coloured by default.
    ('register_brand',
     lambda root: _patch(root, 'ps_window.py',
                         "self.settings.text('sel_heading_mode', u'') or ps_ramp.GREY",
                         "self.settings.text('sel_heading_mode', u'') or ps_ramp.COLOURED")),
    # The Selection button never wired.
    ('register_brand',
     lambda root: _patch(root, 'ps_window.py',
                         "            ('SelectionHeadingModeButton', self.cycle_heading_mode),\n",
                         "")),
    # No colour menu on a Selection heading.
    ('register_brand',
     lambda root: _patch(root, 'ps_window.py',
                         "            self._heading_right_click(args)\n",
                         "")),
    # The Selection's picks kept from the register.
    ('register_brand',
     lambda root: _patch(root, 'ps_window.py',
                         "            self.register.take_heading_colours(colours)\n",
                         "            pass\n")),
    # 1.55.0 - Sheets and Views named apart.
    ('naming_modes',
     lambda root: _patch(root, 'ps_naming.py',
                         "    if mode == 'views':\n        return [Rule(u'View Name')]\n",
                         "")),
    ('naming_modes',
     lambda root: _patch(root, 'ps_naming.py',
                         "MODE_KEYS = {'sheets': 'name', 'views': 'vname'}",
                         "MODE_KEYS = {'sheets': 'name', 'views': 'name'}")),
    ('naming_modes',
     lambda root: _patch(root, 'ps_naming.py',
                         "    elif sheets != default_rules('sheets'):",
                         "    elif False:")),
    ('naming_modes',
     lambda root: _patch(root, 'ps_naming.py',
                         "    else:\n        views = default_rules('views')\n    return",
                         "    else:\n        views = sheets\n    return")),
    ('naming_modes',
     lambda root: _patch(root, 'ps_naming.py',
                         "        rules_to_store(rules, store, mode_key(mode))",
                         "        rules_to_store(rules, store)")),
    ('naming_modes',
     lambda root: _patch(root, 'ps_window.py',
                         "        sets[mode] = list(self.rules)",
                         "        sets[mode] = self.rules")),
    ('naming_modes',
     lambda root: _patch(root, 'ps_window.py',
                         "        self.rules = list(sets.get(mode) or ps_naming.default_rules(mode))",
                         "        self.rules = list(sets.get(mode) or self.rules)")),
    ('naming_modes',
     lambda root: _patch(root, 'ps_window.py',
                         "        self._park_rules(self._other_mode())\n",
                         "")),
    ('naming_modes',
     lambda root: _patch(root, 'ps_window.py',
                         "        self._adopt_rules(self._mode_name())\n        self._fill_table()",
                         "        self._fill_table()")),
    ('naming_modes',
     lambda root: _patch(root, 'ps_window.py',
                         "        self._park_rules(self._mode_name())\n        ps_naming.store_rules_by_mode",
                         "        ps_naming.store_rules_by_mode")),
    ('naming_modes',
     lambda root: _patch(root, 'ps_window.py',
                         "        self.rules_by_mode = ps_naming.rules_by_mode(profile)\n",
                         "")),
    ('naming_modes',
     lambda root: _patch(root, 'ps_window.py',
                         "            self.window, label, mode=mode)",
                         "            self.window, label)")),
    ('naming_modes',
     lambda root: _patch(root, 'ps_window.py',
                         "        self.rules = chosen\n        self._park_rules(mode)\n",
                         "        self.rules = chosen\n")),
    ('naming_modes',
     lambda root: _patch(root, 'ps_namewin.py',
                         "        self._load_rules(ps_naming.default_rules(getattr(self, 'mode',",
                         "        self._load_rules(ps_naming.default_rules(getattr(self, 'xmode',")),
    ('naming_modes',
     lambda root: _patch(root, 'ProSheetsCustomName.xaml',
                         'x:Name="NameModeText" ', '')),
    # 1.55.0 - the sort and grouping remembered.
    ('sort_memory',
     lambda root: _patch(root, 'ps_window.py',
                         "        if key not in store:\n            return None\n",
                         "")),
    ('sort_memory',
     lambda root: _patch(root, 'ps_window.py',
                         "        key = self.SORT_MEMORY + mode\n",
                         "        key = self.SORT_MEMORY + 'sheets'\n")),
    ('sort_memory',
     lambda root: _patch(root, 'ps_window.py',
                         "            settings.save()\n        except Exception:\n            return False\n        return True",
                         "        except Exception:\n            return False\n        return True")),
    ('sort_memory',
     lambda root: _patch(root, 'ps_window.py',
                         "        grouped = ps_config.get_bool(store, self.GROUP_MEMORY + mode, True)",
                         "        grouped = True")),
    ('sort_memory',
     lambda root: _patch(root, 'ps_window.py',
                         "                if not col_id.startswith(u'p:'):\n                    continue\n",
                         "")),
    ('sort_memory',
     lambda root: _patch(root, 'ps_window.py',
                         "                order.insert(where, col_id)\n            kept.append((col_id, down))",
                         "                continue\n            kept.append((col_id, down))")),
    ('sort_memory',
     lambda root: _patch(root, 'ps_window.py',
                         "        self.grouped = bool(grouped)\n        self._template_sort = u''\n",
                         "        self.grouped = bool(grouped)\n")),
    ('sort_memory',
     lambda root: _patch(root, 'ps_window.py',
                         "            settings.store.pop(key, None)",
                         "            pass")),
    ('sort_memory',
     lambda root: _patch(root, 'ps_window.py',
                         "        self._paint_sort_headers()\n        self.remember_sort()\n        self._say_sort()",
                         "        self._paint_sort_headers()\n        self._say_sort()")),
    ('sort_memory',
     lambda root: _patch(root, 'ps_window.py',
                         "        self._refresh_counts()\n        self.remember_sort()\n        if not self.grouped:",
                         "        self._refresh_counts()\n        if not self.grouped:")),
    ('sort_memory',
     lambda root: _patch(root, 'ps_window.py',
                         "        self.forget_sort()\n", "")),
    ('sort_memory',
     lambda root: _patch(root, 'ps_window.py',
                         "        if not self._restore_sort(mode):\n",
                         "        if True:\n")),
    ('sort_memory',
     lambda root: _patch(root, 'ps_window.py',
                         "        if self._restore_sort():\n            self._build_columns()\n        self._ready = True\n",
                         "        self._ready = True\n")),
    ('sort_memory',
     lambda root: _patch(root, 'ps_window.py',
                         "        self.settings.save()\n        self.remember_sort()",
                         "        self.settings.save()")),
    ('sort_memory',
     lambda root: _patch(root, 'ps_window.py',
                         "        if series and series != series_before and not self._is_views_mode():",
                         "        if False:")),
    # 1.55.0 - Open sheets on the right-click.
    ('open_sheets',
     lambda root: _patch(root, 'ps_revisions.py',
                         "    for view in reversed(list(views or [])):",
                         "    for view in list(views or []):")),
    ('open_sheets',
     lambda root: _patch(root, 'ps_revisions.py',
                         "            uidoc.ActiveView = view\n            opened += 1\n        except Exception as err:\n            try:",
                         "            uidoc.ActiveView = view\n        except Exception as err:\n            try:")),
    ('open_sheets',
     lambda root: _patch(root, 'ps_revisions.py',
                         "    text = u'{0} {1}{2} opened.'.format(opened, word,",
                         "    text = u'{0} {1}{2} done.'.format(opened, word,")),
    ('open_sheets',
     lambda root: _patch(root, 'ps_window.py',
                         "        return [(u'Open {0}{1}'.format(word, u'' if count == 1 else u's'),",
                         "        return [(u'Open {0}{1}'.format(u'sheet', u'' if count == 1 else u's'),")),
    ('open_sheets',
     lambda root: _patch(root, 'ps_window.py',
                         "        if count <= 0:\n            return []\n        word = u'view'",
                         "        word = u'view'")),
    ('open_sheets',
     lambda root: _patch(root, 'ps_window.py',
                         "                if u'{0}'.format(entry['ishead']) == u'1':\n                    continue\n                row = self.rows_by_key.get(",
                         "                row = self.rows_by_key.get(")),
    ('open_sheets',
     lambda root: _patch(root, 'ps_window.py',
                         "        found.sort(key=lambda pair: pair[0])\n        return [row for _place, row in found]",
                         "        return [row for _place, row in found]")),
    ('open_sheets',
     lambda root: _patch(root, 'ps_window.py',
                         "            self.chrome.shrink()\n        except Exception:\n            pass\n        return True",
                         "            pass\n        except Exception:\n            pass\n        return True")),
    ('open_sheets',
     lambda root: _patch(root, 'ps_window.py',
                         "        if getattr(self, 'exporting', False):\n            self.say(u'Wait for the export",
                         "        if False:\n            self.say(u'Wait for the export")),
    ('open_sheets',
     lambda root: _patch(root, 'ps_window.py',
                         "        if not views:\n            self.say(u'Highlight the {0}s to open first.'.format(word))\n            return False\n",
                         "")),
    ('open_sheets',
     lambda root: _patch(root, 'ps_window.py',
                         "            self._row_right_click(row, args)\n",
                         "            pass\n")),
    ('open_sheets',
     lambda root: _patch(root, 'ps_window.py',
                         "                grid.SelectedItems.Clear()\n                grid.SelectedItems.Add(row.Item)\n",
                         "                pass\n")),
    ('open_sheets',
     lambda root: _patch(root, 'ps_regview.py',
                         "            if not self._is_drawing(entry):\n                continue\n            sheet = elements.get(",
                         "            sheet = elements.get(")),
    ('open_sheets',
     lambda root: _patch(root, 'ps_regview.py',
                         "        found.sort(key=lambda pair: pair[0])\n        return [sheet for _place, sheet in found]",
                         "        return [sheet for _place, sheet in found]")),
    ('open_sheets',
     lambda root: _patch(root, 'ps_regview.py',
                         "        return self.host.open_sheets(self.highlighted_sheets(), u'sheet')",
                         "        return self.host.open_sheets([], u'sheet')")),
    ('register_tools',
     lambda root: _patch(root, 'ps_regview.py',
                         "            entries.append((u'Open sheet' if len(sheets) == 1 else\n                            u'Open sheets', 'open_sheets'))\n",
                         "")),
    # 1.56.0 - Express Export.
    ('express_export',
     lambda root: _patch(root, 'ps_window.py',
                         "            self._launch_export(jobs, formats, self._collect_profile(), True)",
                         "            self._launch_export(jobs, formats, self._collect_profile(), False)")),
    ('express_export',
     lambda root: _patch(root, 'ps_window.py',
                         "        self._express_run = True\n        if alone:",
                         "        if alone:")),
    ('express_export',
     lambda root: _patch(root, 'ps_window.py',
                         "        if not alone and (not jobs or not formats):",
                         "        if not alone and not jobs:")),
    ('express_export',
     lambda root: _patch(root, 'ps_window.py',
                         "        if not root:\n            self.say(u'Express Export: the template has no root folder.",
                         "        if False:\n            self.say(u'Express Export: the template has no root folder.")),
    ('express_export',
     lambda root: _patch(root, 'ps_window.py',
                         "        if not ok:\n            self.say(u'Express Export: {0} cannot be written to",
                         "        if False:\n            self.say(u'Express Export: {0} cannot be written to")),
    ('express_export',
     lambda root: _patch(root, 'ps_window.py',
                         "        if not alone and self._pdf_blocker(formats):",
                         "        if False:")),
    ('express_export',
     lambda root: _patch(root, 'ps_window.py',
                         "        if self.exporting:\n            return False\n        jobs, _clashes = self.plan_jobs()",
                         "        jobs, _clashes = self.plan_jobs()")),
    ('express_export',
     lambda root: _patch(root, 'ps_window.py',
                         "        if alone:\n            self._start_register_alone()\n        else:",
                         "        if False:\n            self._start_register_alone()\n        else:")),
    ('express_export',
     lambda root: _patch(root, 'ps_window.py',
                         "        if getattr(self, '_express_run', False):\n            self._express_finished(report)\n            return\n",
                         "")),
    ('express_export',
     lambda root: _patch(root, 'ps_window.py',
                         "        self._express_run = False\n        self._end_progress()",
                         "        self._end_progress()")),
    ('express_export',
     lambda root: _patch(root, 'ps_window.py',
                         "        if report.folders() and self._flag_of('OpenFolderCheck', True):",
                         "        if False:")),
    ('express_export',
     lambda root: _patch(root, 'ps_window.py',
                         "        if failed:\n            text = u'{0} Not written: {1}{2}'.format(",
                         "        if False:\n            text = u'{0} Not written: {1}{2}'.format(")),
    ('express_export',
     lambda root: _patch(root, 'ps_window.py',
                         "        # The full Export always asks and reports, whatever an Express run\n        # that never reached Revit left behind.\n        self._express_run = False\n",
                         "")),
    ('express_export',
     lambda root: _patch(root, 'ps_window.py',
                         "        if not getattr(self, '_express_run', False):\n            self._set_tab(self.TAB_CREATE)",
                         "        if True:\n            self._set_tab(self.TAB_CREATE)")),
    ('express_export',
     lambda root: _patch(root, 'ps_window.py',
                         "        for name in ('BackButton', 'NextButton', 'ExpressExportButton'):",
                         "        for name in ('BackButton', 'NextButton'):")),
    ('express_export',
     lambda root: _patch(root, 'ps_window.py',
                         "                          index == self.TAB_SELECTION)",
                         "                          True)")),
    ('express_export',
     lambda root: _patch(root, 'ps_window.py',
                         "        if getattr(self, '_express_run', False):\n            ps_export.begin_suppression(self.uiapp)\n",
                         "")),
    ('express_export',
     lambda root: _patch(root, 'ProSheets.xaml',
                         '              <Button x:Name="ExpressExportButton"\n                      Style="{DynamicResource PrimaryButton}"',
                         '              <Button x:Name="ExpressExportButton"')),
    ('express_export',
     lambda root: _patch(root, 'ProSheets.xaml',
                         '                  <TextBlock Text="Express Export" VerticalAlignment="Center"/>',
                         '                  <TextBlock Text="Quick" VerticalAlignment="Center"/>')),
    ('issue_folder',
     lambda root: _patch(root, 'ps_window.py',
                         "        self._launch_export(jobs, formats, profile, quiet)\n",
                         "")),
    ('express_export',
     lambda root: _patch(root, 'ps_window.py',
                         "            ('ExpressExportButton', self.express_export),\n",
                         "")),
    # 1.56.1 - the footer's buttons always whole.
    ('footer_layout',
     lambda root: _patch(root, 'ProSheets.xaml',
                         '<DockPanel x:Name="FooterDock" LastChildFill="True">',
                         '<DockPanel x:Name="FooterDock" LastChildFill="False">')),
    ('footer_layout',
     lambda root: _patch(root, 'ProSheets.xaml',
                         '<StackPanel x:Name="FooterButtons" DockPanel.Dock="Right"',
                         '<StackPanel x:Name="FooterButtons" DockPanel.Dock="Left"')),
    ('footer_layout',
     lambda root: _patch(root, 'ProSheets.xaml',
                         '                         TextTrimming="CharacterEllipsis"\n                         ToolTip="{Binding Text, RelativeSource={RelativeSource Self}}"\n                         Text="Ready."/>',
                         '                         Text="Ready."/>')),
    ('footer_layout',
     lambda root: _patch(root, 'ps_window.py',
                         "            self.window.ContentRendered += self._settle_layout\n",
                         "            pass\n")),
    ('footer_layout',
     lambda root: _patch(root, 'ps_window.py',
                         "            self.window.ContentRendered -= self._settle_layout\n",
                         "            pass\n")),
    ('footer_layout',
     lambda root: _patch(root, 'ps_window.py',
                         "            self.window.Content.InvalidateMeasure()\n            self.window.UpdateLayout()",
                         "            self.window.Content.InvalidateMeasure()")),
    ('footer_layout',
     lambda root: _patch(root, 'ps_window.py',
                         "        for name in ('FooterButtons', 'FooterDock'):",
                         "        for name in ():")),
    # A delivery that ships the shared startup.py rather than a fragment.
    ('shared_files',
     lambda root: _write(root, 'startup.py',
                         '# a delivery that overwrites the shared file\n')),
    # A tile drawn on the tab that the registry does not list: nothing
    # wires it up, which is what DGN and IMG were before 1.8.0.
    ('format_registry',
     lambda root: _patch(root, 'ps_window.py',
                         "    ('ifc', 'IfcCheck', 'IfcTile', 'IfcGroup', 'IfcPanel', u'IFC', True),\n",
                         '')),
    # A live format with no panel: its tile would open nothing.
    ('format_registry',
     lambda root: _patch(root, 'ps_window.py',
                         "'NwcGroup', 'NwcPanel', u'NWC', True)",
                         "'NwcGroup', '', u'NWC', True)")),
    # Views mode back on the sheet columns, which is the empty-column
    # fault this release fixed.
    ('mode_columns',
     lambda root: _patch(root, 'ps_window.py',
                         "    VIEW_COLUMNS = [\n        ('sel', u'', 0.0, 44),\n        ('name', u'View Name', 2.4, 200),",
                         "    VIEW_COLUMNS = [\n        ('sel', u'', 0.0, 44),\n        ('num', u'Sheet Number', 1.1, 120),\n        ('rev', u'Revision', 0.6, 85),\n        ('size', u'Size', 1.0, 130),\n        ('name', u'View Name', 2.4, 200),")),
    # A saved order sanitised by throwing the parameter columns away
    # rather than by dropping the fixed ones that do not fit.
    ('mode_columns',
     lambda root: _patch(root, 'ps_window.py',
                         "        order = [col_id for col_id in saved\n                 if self.is_parameter_column(col_id) or col_id in wanted]",
                         "        order = [col_id for col_id in saved if col_id in wanted]")),
    ('xaml_parses',
     lambda root: _patch(root, 'ProSheets.xaml', '<!-- ==========',
                         '<!-- ----------')),
    ('thin_loader',
     lambda root: _patch(root, 'script.py', 'import os\nimport sys',
                         'import os\nimport ps_window\nimport sys')),
    # Anchored on the shape of the file, not on the exact import list,
    # so adding a name to that import does not silently disarm the rule.
    ('refs_first',
     lambda root: _patch(
         root, 'theme.py',
         'import ps_refs  # noqa: F401  - must be first, see its docstring',
         '# ps_refs deliberately moved below the .NET import for the selftest')
     or _patch(root, 'theme.py', 'DARK = {',
               'import ps_refs  # too late: the .NET import is above\n\n\nDARK = {')),
    # The bug that shipped in 1.0.0: System.Data is its own assembly, and
    # without the reference the window died with "No module named Data".
    ('assemblies_referenced',
     lambda root: _patch(root, 'ps_refs.py', "    'System.Data',\n", '')),
    ('resources',
     lambda root: _patch(root, 'ProSheetsPrompt.xaml',
                         '{DynamicResource WindowBg}',
                         '{DynamicResource NoSuchBrush}')),
    ('style_targets',
     lambda root: _patch(root, 'ProSheetsOrder.xaml',
                         '<Button x:Name="SortButton" Content="Sheet number order"\n                  Style="{DynamicResource ChipButton}"',
                         '<Button x:Name="SortButton" Content="Sheet number order"\n                  Style="{DynamicResource GripThumb}"')),
    ('find_names',
     lambda root: _patch(root, 'ps_orderwin.py',
                         "ps_ui.find(self.window, 'OrderList')",
                         "ps_ui.find(self.window, 'OrderListTypo')")),
    ('python_dialect',
     lambda root: _patch(root, 'ps_paths.py',
                         'def ensure(folder):',
                         'def ensure(folder):\n    _ = folder.IntegerValue')),
    ('ascii',
     lambda root: _patch(root, 'ps_paths.py',
                         "EMPTY_PLACEHOLDER = u'_unset'",
                         "EMPTY_PLACEHOLDER = '_unset—'")),
    ('palettes',
     lambda root: _patch(root, 'theme.py', "    'ChipBg':          '#DCDCE2',",
                         '')),
    ('no_duplicate_methods',
     lambda root: _patch(root, 'ps_orderwin.py',
                         '    def _sort(self, sender, args):',
                         '    def _fill(self):\n        pass\n\n'
                         '    def _sort(self, sender, args):')),
    # _fill reads self.list_box, so calling it before that attribute is set
    # is the three-deep bug in miniature.
    ('init_attributes',
     lambda root: _patch(root, 'ps_orderwin.py',
                         "        self.list_box = ps_ui.find(self.window, 'OrderList')\n"
                         "        self._fill()",
                         "        self._fill()\n"
                         "        self.list_box = ps_ui.find(self.window, 'OrderList')")),
    ('modules_load',
     lambda root: _patch(root, 'ps_model.py',
                         'from Autodesk.Revit.DB import (',
                         'from Autodesk.Revit.UI import ViewSheet\nfrom Autodesk.Revit.DB import (')),
    ('paper_sizing',
     lambda root: _patch(root, 'ps_model.py', 'SIZE_TOLERANCE_MM = 8.0',
                         'SIZE_TOLERANCE_MM = 0.0')),
    ('find_names',
     lambda root: _patch(root, 'ps_window.py',
                         "self._styled(button, 'ChipButton')",
                         "self._styled(button, 'NoSuchChipButton')")),
    # The bug that shipped in 1.6.0 and showed up in 1.7.1.
    ('grid_placement',
     lambda root: _patch(root, 'ProSheets.xaml',
                         '<DataGrid x:Name="SheetGrid" Grid.Row="2"',
                         '<DataGrid x:Name="SheetGrid"')),
    ('template_bundles',
     lambda root: _patch(root, 'ps_config.py',
                         "        candidate = u'{0} ({1})'.format(base, index)",
                         "        candidate = u'{0}'.format(base)")),
    # The bug that shipped: a dialog arming the egg as well.
    ('egg_arming',
     lambda root: _patch(root, 'ps_orderwin.py',
                         '        # The egg is armed on the main window only; see ps_ui.attach_egg.',
                         '        ps_ui.attach_egg(self.window)')),
    # The trap this whole feature is shaped around: month against minute.
    ('naming_behaviour',
     lambda root: _patch(root, 'ps_paths.py',
                         "    (u'Minute', '%M', u'05'),",
                         "    (u'Minute', '%m', u'05'),")),
    ('naming_behaviour',
     lambda root: _patch(root, 'ps_naming.py',
                         "        if not value and not rule.prefix and not rule.suffix:\n            continue",
                         '        pass')),
]


def selftest():
    _say('RevoBIM Pro Sheets Exporter : proving each rule by breaking it')
    _say('=' * 66)

    clean = run(HERE, quiet=True)
    if len(clean):
        _say('The tool itself is not clean, so the selftest would not mean '
             'anything. Fix these first:')
        for rule_name, text in clean.items:
            _say('  [{0}] {1}'.format(rule_name, text))
        return 1

    bad = 0
    for rule_name, break_it in BREAKAGES:
        root = _copy_tool()
        try:
            break_it(root)
            result = run(root, quiet=True)
            if rule_name in result.rules_hit():
                _say('  caught  : {0}'.format(rule_name))
            else:
                bad += 1
                _say('  MISSED  : {0} - the rule did not fire when broken'
                     .format(rule_name))
                for hit_rule, text in result.items[:4]:
                    _say('            (other rules said: [{0}] {1})'
                         .format(hit_rule, text))
        except Exception as err:
            bad += 1
            _say('  BROKEN  : {0} - the selftest itself failed: {1}'
                 .format(rule_name, err))
        finally:
            _discard(root)

    _say('')
    if bad:
        _say('{0} rule(s) did not fire when broken. A rule nobody has tested '
             'is a rule that does not work.'.format(bad))
        return 1
    _say('Every one of the {0} rules fired when broken.'.format(len(BREAKAGES)))
    return 0


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(selftest())
    sys.exit(1 if len(run()) else 0)
