# -*- coding: utf-8 -*-
"""Find in View - bench check.

Runs under plain CPython from the pushbutton folder:

    python import_check.py
    python import_check.py --selftest

It loads every shipped module against a stub Revit and .NET API that declares
each name in the namespace the REAL API puts it in, so a mis-namespaced import
fails on the bench instead of showing up in Revit as a blank white pyRevit
window with no traceback in it.

--selftest breaks each rule on purpose and confirms the check catches it. A
rule nobody has tested is a rule that does not work.
"""

import os
import re
import shutil
import sys
import symtable
import tempfile
import xml.dom.minidom

HERE = os.path.dirname(os.path.abspath(__file__))

MODULES = ['fiv_clr', 'fiv_core', 'theme', 'fiv_ui', 'fiv_model', 'fiv_window']
LAYOUTS = ['FindInView.xaml', 'FindInViewMessage.xaml', 'FindById.xaml']
THEME_FILE = 'Theme.xaml'
FOLDER_NAME = 'Find in View'

# ---------------------------------------------------------------------------
# the stub API
# ---------------------------------------------------------------------------
#
# Each namespace declares exactly the names the real API puts in it.  Anything
# else raises ImportError, which is what Revit would do at module load.

NAMESPACES = {
    'clr': ['AddReference', 'AddReferenceByName', 'GetClrType', 'Reference'],
    'System': ['Object', 'Action', 'Func', 'String', 'Exception', 'Convert',
               'TimeSpan',
               'Environment', 'Uri', 'Array', 'Math', 'Double', 'Int32', 'Int64',
               'Boolean'],
    'System.IO': ['StringReader', 'StringWriter', 'MemoryStream', 'File', 'Path',
                  'Directory', 'FileStream'],
    'System.Xml': ['XmlReader', 'XmlDocument', 'XmlWriter'],
    'System.Collections.Generic': ['List', 'Dictionary', 'HashSet', 'IList'],
    'System.ComponentModel': ['ListSortDirection', 'INotifyPropertyChanged',
                              'PropertyChangedEventArgs'],
    'System.Globalization': ['CultureInfo'],
    'System.Windows': ['Window', 'ResourceDictionary', 'Visibility', 'SystemParameters',
                       'GridLength', 'GridUnitType', 'DataTemplate',
                       'FrameworkElementFactory', 'FrameworkElement',
                       'VerticalAlignment', 'HorizontalAlignment', 'Thickness',
                       'TextTrimming', 'TextWrapping', 'WindowState', 'WindowStyle',
                       'PresentationSource', 'Point', 'Rect', 'Size',
                       'DependencyProperty', 'RoutedEventArgs', 'MessageBox',
                       'FontWeights', 'Application', 'DragDeltaEventArgs',
                       'ResizeMode', 'SizeToContent', 'CornerRadius', 'Duration'],
    'System.Windows.Controls': ['CheckBox', 'TextBlock', 'TextBox', 'Button', 'Path',
                                'ListBox', 'ListBoxItem', 'ComboBox', 'ComboBoxItem',
                                'DataGrid', 'DataGridTemplateColumn', 'DataGridTextColumn',
                                'DataGridLength', 'DataGridLengthUnitType',
                                'ProgressBar', 'Border', 'Grid', 'StackPanel',
                                'ScrollViewer', 'Image', 'GridSplitter', 'Label',
                                'ColumnDefinition', 'RowDefinition', 'ToolTip'],
    'System.Windows.Controls.Primitives': ['Thumb', 'RepeatButton', 'ButtonBase'],
    'System.Windows.Data': ['Binding', 'IValueConverter', 'BindingMode'],
    'System.Windows.Input': ['Key', 'Cursors', 'Mouse', 'Keyboard', 'ModifierKeys',
                             'KeyEventArgs', 'MouseButtonEventArgs'],
    'System.Windows.Markup': ['XamlReader', 'XamlWriter'],
    'System.Windows.Interop': ['WindowInteropHelper', 'HwndSource'],
    'System.Windows.Media': ['SolidColorBrush', 'ColorConverter', 'Brush', 'Brushes',
                             'Color', 'Colors', 'VisualTreeHelper', 'RotateTransform'],
    'System.Windows.Media.Imaging': ['BitmapImage', 'BitmapCacheOption', 'BitmapFrame'],
    'System.Windows.Threading': ['Dispatcher', 'DispatcherFrame', 'DispatcherPriority',
                                 'DispatcherTimer'],
    'System.Windows.Forms': ['Screen', 'Application'],
    'Autodesk': [],
    'Autodesk.Revit': [],
    'Autodesk.Revit.DB': ['FilteredElementCollector', 'View', 'ViewSheet', 'ViewType',
                          'ViewPlan', 'View3D', 'ViewFamilyType', 'Element', 'ElementId',
                          'ElementMulticategoryFilter', 'ElementCategoryFilter',
                          'BuiltInCategory', 'BuiltInParameter', 'XYZ', 'Transform',
                          'BoundingBoxXYZ', 'Level', 'Transaction', 'TransactionGroup',
                          'SubTransaction', 'Category', 'WorksharingUtils',
                          'IFailuresPreprocessor', 'FailureProcessingResult'],
    'Autodesk.Revit.UI': ['TaskDialog', 'TaskDialogCommonButtons', 'TaskDialogResult',
                          'UIDocument', 'UIApplication', 'UIView', 'ExternalEvent',
                          'IExternalEventHandler', 'RevitCommandId',
                          'PostableCommand'],
    'Autodesk.Revit.UI.Selection': ['ObjectType', 'ISelectionFilter'],
}


class _StubMeta(type):
    """Stub CLASSES are permissive: any member access hands back another stub.

    Only the MODULE level is strict, which is where a mis-namespaced import
    actually bites.
    """

    def __getattr__(cls, name):
        return _make_class(name)

    def __call__(cls, *args, **kwargs):
        return _StubInstance()

    def __getitem__(cls, item):
        return cls


def _make_class(name):
    return _StubMeta(str(name), (object,), {})


class _StubInstance(object):

    def __getattr__(self, name):
        return _make_class(name)()

    def __call__(self, *args, **kwargs):
        return _StubInstance()

    def __iter__(self):
        return iter([])


class _StubModule(object):

    def __init__(self, name, allowed):
        self.__name__ = name
        self._allowed = set(allowed)
        self._cache = {}

    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        if name not in self._allowed:
            raise ImportError(
                "Cannot import name {0} from {1} - the real API does not put it "
                "there".format(name, self.__name__))
        if name not in self._cache:
            self._cache[name] = _make_class(name)
        return self._cache[name]


def install_stubs():
    removed = {}
    for name in list(sys.modules.keys()):
        if name in NAMESPACES or name in MODULES:
            removed[name] = sys.modules.pop(name)
    for name in NAMESPACES:
        sys.modules[name] = _StubModule(name, NAMESPACES[name])
    return removed


def remove_stubs(removed):
    for name in list(sys.modules.keys()):
        if name in NAMESPACES or name in MODULES:
            sys.modules.pop(name, None)
    for name in removed:
        sys.modules[name] = removed[name]


# ---------------------------------------------------------------------------
# small readers
# ---------------------------------------------------------------------------

def read(path):
    handle = open(path, 'r')
    try:
        return handle.read()
    finally:
        handle.close()


def code_only(text):
    """Blank out comments and the CONTENTS of every string literal.

    The quotes and any prefix are kept, so an f-string is still recognisable
    while a docstring that talks about System.Uri or .IntegerValue cannot trip
    the text rules.  Line numbers are preserved.
    """
    out = []
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char == '#':
            while index < length and text[index] != '\n':
                out.append(' ')
                index += 1
            continue
        if char in ('"', "'"):
            triple = text[index:index + 3]
            delimiter = triple if triple in ('"""', "'''") else char
            out.append(delimiter)
            index += len(delimiter)
            while index < length:
                if text[index] == '\\':
                    out.append(' ')
                    if index + 1 < length:
                        out.append('\n' if text[index + 1] == '\n' else ' ')
                    index += 2
                    continue
                if text.startswith(delimiter, index):
                    out.append(delimiter)
                    index += len(delimiter)
                    break
                out.append('\n' if text[index] == '\n' else ' ')
                index += 1
            continue
        out.append(char)
        index += 1
    return ''.join(out)


def read_code(path):
    return code_only(read(path))


def module_files(folder):
    out = []
    for name in MODULES + ['script']:
        path = os.path.join(folder, name + '.py')
        if os.path.isfile(path):
            out.append((name, path))
    return out


def xaml_files(folder):
    out = []
    for name in LAYOUTS + [THEME_FILE]:
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            out.append((name, path))
    return out


def theme_keys(folder):
    keys = set()
    path = os.path.join(folder, THEME_FILE)
    if not os.path.isfile(path):
        return keys
    for match in re.finditer(r'x:Key\s*=\s*"([^"]+)"', read(path)):
        keys.add(match.group(1))
    return keys


def theme_style_targets(folder):
    """{style key: TargetType} for every keyed Style in Theme.xaml."""
    targets = {}
    path = os.path.join(folder, THEME_FILE)
    if not os.path.isfile(path):
        return targets
    for match in re.finditer(r'<Style\b([^>]*)>', read(path)):
        attributes = match.group(1)
        key = re.search(r'x:Key\s*=\s*"([^"]+)"', attributes)
        target = re.search(r'TargetType\s*=\s*"([^"]+)"', attributes)
        if key and target:
            targets[key.group(1)] = target.group(1).split(':')[-1]
    return targets


# ---------------------------------------------------------------------------
# the rules
# ---------------------------------------------------------------------------

def rule_xaml_parses(folder):
    """Every .xaml parses as XML.

    Catches an unclosed tag, a bare & , and a comment banner drawn with a run
    of hyphens - XML forbids '--' inside a comment, and XamlReader.Load
    throwing is the quiet way to get a blank white window.
    """
    problems = []
    for name, path in xaml_files(folder):
        try:
            xml.dom.minidom.parseString(read(path))
        except Exception as error:
            problems.append('{0} will not parse as XML: {1}'.format(name, error))
    return problems


def rule_clr_first(folder):
    """No module reaches into System.* or Autodesk.* before importing fiv_clr."""
    problems = []
    for name, path in module_files(folder):
        if name == 'fiv_clr':
            continue
        lines = read_code(path).splitlines()
        clr_line = None
        first_dotnet = None
        for index, line in enumerate(lines):
            stripped = line.strip()
            if re.match(r'^(import|from)\s+fiv_clr\b', stripped):
                if clr_line is None:
                    clr_line = index
            if re.match(r'^(import|from)\s+(System|Autodesk)\b', stripped):
                if first_dotnet is None:
                    first_dotnet = index
        if first_dotnet is None:
            continue
        if clr_line is None:
            problems.append(
                '{0} imports {1} without importing fiv_clr at all'.format(
                    name, lines[first_dotnet].strip()))
        elif clr_line > first_dotnet:
            problems.append(
                '{0} imports fiv_clr too late: line {1} comes after line {2}'.format(
                    name, clr_line + 1, first_dotnet + 1))
    return problems


def rule_namespaces(folder):
    """Every module loads against the stub API."""
    problems = []
    removed = install_stubs()
    inserted = False
    if folder not in sys.path:
        sys.path.insert(0, folder)
        inserted = True
    try:
        for name in MODULES:
            try:
                __import__(name)
            except Exception as error:
                problems.append('{0} will not import: {1}: {2}'.format(
                    name, type(error).__name__, error))
    finally:
        if inserted:
            try:
                sys.path.remove(folder)
            except ValueError:
                pass
        remove_stubs(removed)
    return problems


def rule_no_static_resource(folder):
    """No StaticResource in a layout file.

    Theme.xaml is merged in AFTER XamlReader has parsed the layout, so a
    StaticResource fails at load - the blank white window again.
    """
    problems = []
    for name in LAYOUTS:
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            continue
        if 'StaticResource' in read(path):
            problems.append('{0} uses StaticResource: layouts may only use '
                            'DynamicResource'.format(name))
    theme_path = os.path.join(folder, THEME_FILE)
    if os.path.isfile(theme_path):
        text = read(theme_path)
        for key in theme_keys(folder):
            if 'StaticResource ' + key in text and key.endswith(('Bg', 'Brush', 'Hover',
                                                                 'Edge', 'Text')):
                problems.append('Theme.xaml resolves the palette key {0} with '
                                'StaticResource: it would bake the dark colour '
                                'in'.format(key))
    return problems


def rule_dynamic_keys_exist(folder):
    """Every DynamicResource key is defined in Theme.xaml."""
    problems = []
    keys = theme_keys(folder)
    for name, path in xaml_files(folder):
        for match in re.finditer(r'\{DynamicResource\s+([^}]+)\}', read(path)):
            key = match.group(1).strip()
            if key not in keys:
                problems.append('{0} asks for DynamicResource {1}, which '
                                'Theme.xaml does not define'.format(name, key))
    return problems


def rule_style_targettype(folder):
    """No Style="{DynamicResource K}" on an element K's TargetType does not match.

    WPF raises that when the style is APPLIED, so it surfaces as a dead window.
    """
    problems = []
    targets = theme_style_targets(folder)
    for name, path in xaml_files(folder):
        for match in re.finditer(r'<([A-Za-z][\w.:]*)\b([^>]*)>', read(path)):
            tag = match.group(1).split(':')[-1]
            attributes = match.group(2)
            style = re.search(r'Style\s*=\s*"\{DynamicResource\s+([^}"]+)\}"', attributes)
            if not style:
                continue
            key = style.group(1).strip()
            wanted = targets.get(key)
            if wanted and wanted != tag:
                problems.append('{0}: style {1} targets {2} but is applied to '
                                'a {3}'.format(name, key, wanted, tag))
    return problems


def rule_findname_has_xname(folder):
    """No FindName without a matching x:Name.

    The call is aliased in this tool (self.find = self.window.FindName), so the
    rule matches the alias as well as the literal call - a rule that only
    matched FindName("X") would be doing nothing at all here.
    """
    problems = []
    names = set()
    for _name, path in xaml_files(folder):
        for match in re.finditer(r'x:Name\s*=\s*"([^"]+)"', read(path)):
            names.add(match.group(1))
    pattern = re.compile(r'(?:FindName|\bfind|self\.find)\(\s*[\'"]([^\'"]+)[\'"]\s*\)')
    for name, path in module_files(folder):
        for match in pattern.finditer(read(path)):
            wanted = match.group(1)
            if wanted not in names:
                problems.append('{0} looks up "{1}", which no layout declares '
                                'as an x:Name'.format(name, wanted))
    return problems


def rule_no_fstrings(folder):
    """No f-strings: IronPython 2.7 cannot parse them."""
    problems = []
    pattern = re.compile(r'(^|[^\w\'"])[fF][\'"]')
    for name, path in module_files(folder):
        for index, line in enumerate(read_code(path).splitlines()):
            if pattern.search(line):
                problems.append('{0} line {1} uses an f-string'.format(name, index + 1))
    return problems


def rule_no_print(folder):
    """No print statements in the shipped modules: tools finish silently."""
    problems = []
    pattern = re.compile(r'(^|[^\w.])print\s*[\(\'"]')
    for name, path in module_files(folder):
        for index, line in enumerate(read_code(path).splitlines()):
            if pattern.search(line):
                problems.append('{0} line {1} prints'.format(name, index + 1))
    return problems


def rule_no_bare_integervalue(folder):
    """No bare .IntegerValue: it was removed in Revit 2026.

    Allowed only inside the guarded eid_value helper.
    """
    problems = []
    for name, path in module_files(folder):
        lines = read_code(path).splitlines()
        inside_helper = False
        for index, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith('def '):
                inside_helper = stripped.startswith('def eid_value')
            if '.IntegerValue' in line and not inside_helper:
                problems.append('{0} line {1} touches .IntegerValue outside '
                                'eid_value'.format(name, index + 1))
    return problems


def rule_no_system_uri(folder):
    """No System.Uri: it moved assemblies and throws ImportError on 2025+."""
    problems = []
    for name, path in module_files(folder):
        text = read_code(path)
        if re.search(r'from\s+System\s+import\s+[^\n]*\bUri\b', text) or 'System.Uri' in text:
            problems.append('{0} reaches for System.Uri; load images from bytes '
                            'through a MemoryStream instead'.format(name))
    return problems


def rule_palette_keys(folder):
    """Both palettes cover the same keys, and every one has a brush in Theme.xaml."""
    problems = []
    text = read(os.path.join(folder, 'theme.py'))
    palettes = {}
    for match in re.finditer(r'^(DARK|LIGHT)\s*=\s*\{(.*?)^\}', text, re.S | re.M):
        keys = set(re.findall(r"'([A-Za-z]\w*)'\s*:", match.group(2)))
        palettes[match.group(1)] = keys
    if len(palettes) != 2:
        return ['theme.py does not declare both a DARK and a LIGHT palette']
    dark = palettes['DARK']
    light = palettes['LIGHT']
    for key in sorted(dark - light):
        problems.append('the light palette has no {0}'.format(key))
    for key in sorted(light - dark):
        problems.append('the dark palette has no {0}'.format(key))
    keys = theme_keys(folder)
    for key in sorted(dark | light):
        if key not in keys:
            problems.append('palette key {0} has no brush in Theme.xaml'.format(key))
    return problems


def rule_setresourcereference_keys(folder):
    """Every SetResourceReference key exists in Theme.xaml."""
    problems = []
    keys = theme_keys(folder)
    pattern = re.compile(r'SetResourceReference\([^,]+,\s*[\'"]([^\'"]+)[\'"]\)')
    for name, path in module_files(folder):
        for match in pattern.finditer(read(path)):
            if match.group(1) not in keys:
                problems.append('{0} sets a resource reference to {1}, which '
                                'Theme.xaml does not define'.format(name, match.group(1)))
    return problems


_BUILTINS = set(dir(__builtins__)) if isinstance(__builtins__, dict) is False else set(__builtins__)


def rule_globals_exist(folder):
    """Every global name a function reaches for exists in its module.

    This is the rule that catches a function deleted by a block rewrite while
    its callers stayed behind.
    """
    problems = []
    removed = install_stubs()
    inserted = False
    if folder not in sys.path:
        sys.path.insert(0, folder)
        inserted = True
    try:
        import builtins as builtin_module
        known_builtins = set(dir(builtin_module))
        for name in MODULES:
            path = os.path.join(folder, name + '.py')
            try:
                module = __import__(name)
                defined = set(dir(module))
            except Exception:
                continue
            try:
                table = symtable.symtable(read(path), path, 'exec')
            except Exception:
                continue
            for wanted in _globals_used(table):
                if wanted in defined or wanted in known_builtins:
                    continue
                problems.append('{0} reaches for the global name "{1}", which '
                                'the module does not define'.format(name, wanted))
    finally:
        if inserted:
            try:
                sys.path.remove(folder)
            except ValueError:
                pass
        remove_stubs(removed)
    return problems


def _globals_used(table, out=None):
    if out is None:
        out = set()
    for symbol in table.get_symbols():
        try:
            if symbol.is_global() and symbol.is_referenced():
                out.add(symbol.get_name())
        except Exception:
            pass
    for child in table.get_children():
        _globals_used(child, out)
    return out


def rule_version_and_names(folder):
    """The version is in one place, and the tool name agrees everywhere.

    pyRevit names a ribbon item after its folder, so a rename that misses one
    of these leaves the old name showing somewhere.
    """
    problems = []
    core = read(os.path.join(folder, 'fiv_core.py'))
    match = re.search(r'__version__\s*=\s*"([\d.]+)"', core)
    if not match:
        return ['fiv_core.py declares no __version__']
    version = match.group(1)

    name_match = re.search(r'TOOL_NAME\s*=\s*"([^"]+)"', core)
    tool_name = name_match.group(1) if name_match else ''
    if tool_name != FOLDER_NAME:
        problems.append('TOOL_NAME is "{0}" but the folder is "{1}"'.format(
            tool_name, FOLDER_NAME))

    bundle = os.path.join(folder, 'bundle.yaml')
    if os.path.isfile(bundle):
        title = re.search(r'^title:\s*(.+)$', read(bundle), re.M)
        if not title or title.group(1).strip() != FOLDER_NAME:
            problems.append('bundle.yaml title does not match the folder name')

    changelog = os.path.join(folder, 'CHANGELOG.md')
    if os.path.isfile(changelog):
        if '## ' + version not in read(changelog):
            problems.append('CHANGELOG.md has no entry for {0}'.format(version))

    for name in LAYOUTS:
        path = os.path.join(folder, name)
        if os.path.isfile(path) and 'VersionText' not in read(path):
            problems.append('{0} has no VersionText: the version belongs in the '
                            'top right of every window'.format(name))
    return problems


def rule_late_enum_members(folder):
    """Enum members that vary by release are looked up late, not at import.

    PostableCommand.TileWindows arrived in 2019 and the extension targets 2024
    to 2027, but the same trap has bitten this extension before with
    BuiltInCategory: a member touched at module level dies before the tool can
    say why.
    """
    problems = []
    for name, path in module_files(folder):
        for index, line in enumerate(read_code(path).splitlines()):
            if 'PostableCommand.' in line and 'getattr' not in line:
                problems.append('{0} line {1} touches a PostableCommand member '
                                'directly; look it up with getattr inside a '
                                'function'.format(name, index + 1))
    return problems


def shared_egg_rule(folder):
    """Load the extension's own egg bench rule, if the extension is there.

    The rule lives once, at lib/revobim/egg/egg_rule.py, and every tool's bench
    imports it from there rather than carrying a copy - a copied rule drifts
    from the egg it is meant to be checking.
    """
    here = os.path.abspath(folder)
    for _step in range(6):
        candidate = os.path.join(here, 'lib', 'revobim', 'egg', 'egg_rule.py')
        if os.path.isfile(candidate):
            try:
                import imp
                return imp.load_source('egg_rule', candidate)
            except Exception:
                try:
                    import importlib.util as util
                    spec = util.spec_from_file_location('egg_rule', candidate)
                    module = util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    return module
                except Exception:
                    return None
        parent = os.path.dirname(here)
        if parent == here:
            break
        here = parent
    return None


def rule_easter_egg(folder):
    """Every window carrying the RevoBIM logo wires it to the shared egg.

    Two halves: what can be checked here, and the extension's own egg_rule
    where the extension is installed beside the bench.
    """
    problems = []

    logos = []
    for name in LAYOUTS:
        path = os.path.join(folder, name)
        if os.path.isfile(path) and 'x:Name="HeaderIcon"' in read(path):
            logos.append(name)

    wired = 0
    for _name, path in module_files(folder):
        wired += len(re.findall(r'wire_egg\(', read_code(path)))
    # one definition plus one call per window carrying the logo
    if wired < len(logos) + 1:
        problems.append('{0} windows carry the RevoBIM logo but only {1} '
                        'wire_egg references exist: every logo has to open the '
                        'egg'.format(len(logos), wired))

    ui_path = os.path.join(folder, 'fiv_ui.py')
    ui_code = read_code(ui_path)
    # the module path is a string literal, so it has to be read raw - the
    # scrubber blanks the inside of every string
    if 'revobim.egg' not in read(ui_path) or 'EGG_ENTRY_POINTS' not in ui_code:
        problems.append('nothing points at the shared egg at lib/revobim/egg')
    if 'PreviewMouseLeftButtonDown' not in ui_code:
        problems.append('the logo click has to be handled in the tunnelling '
                        'event, or the header drag swallows it')

    shared = shared_egg_rule(folder)
    if shared is not None:
        for name in ('check', 'run', 'rule', 'problems'):
            function = getattr(shared, name, None)
            if function is None:
                continue
            try:
                found = function(folder)
            except Exception as error:
                problems.append('the shared egg_rule threw: {0}'.format(error))
                break
            if found:
                for entry in found:
                    problems.append('egg_rule: {0}'.format(entry))
            break
    return problems


# Every feature the changelog claims, and the call site that makes it real.
# A function that exists but is never called passes every other rule here and
# ships nothing - which is exactly how the 1.6.0 tiling hint and the 1.7.0
# remembered view went out missing for several versions.
FEATURES = [
    # the exact call, not the function name: the hidden-view lookup calls the
    # same function, so a loose needle passes with the real call knocked out
    ('fiv_window.py', 'remembered = fiv_model.find_remembered(rows,',
     '1.7.0 last view found by id, then name'),
    ('fiv_window.py', 'self.hidden_last_view = hidden', '1.7.0 last view hidden by the filters'),
    ('fiv_window.py', "self.settings['last_view_id']", '1.7.0 last view saved by id'),
    ('fiv_window.py', 'self._scroll_to_selection()', '1.7.0 list scrolled to the last view'),
    ('fiv_window.py', 'Your layout is not re-tiled', '1.6.0 tiling hint matches the rule'),
    ('fiv_window.py', 'More than one view is open', '1.6.0 tiling hint for several views'),
    ('fiv_model.py', 'check_zoom(ui_view', '1.6.0 zoom read back and checked'),
    ('fiv_model.py', 'plan_tiling(read_window_rects(', '1.4.0 tiling planned from the windows'),
    ('fiv_model.py', 'post_tile_windows(uiapp)', '1.4.1 tile command posted'),
    ('fiv_model.py', 'make_visible(uidoc.Document', '1.10.0 hidden category switched on'),
    ('fiv_model.py', 'still_missing(uidoc.Document', '1.10.0 what is still not drawn'),
    ('fiv_window.py', 'fiv_model.selection_properties(', '1.11.0 properties panel'),
    ('fiv_window.py', 'fiv_model.find_by_ids(', '1.9.0 find by id inside the tool'),
    ('fiv_window.py', 'fiv_core.first_field(', '1.11.1 caret in the id box when skipped'),
    ('fiv_window.py', 'self.chrome.drawer = self.drawer', '1.13.0 chrome defers to the drawer'),
    ('fiv_model.py', 'drawn_in_view(uidoc.Document, view, element_ids, category_ids)',
     '1.14.0 zoom-here check narrowed by category'),
    ('fiv_model.py', 'still_missing(uidoc.Document, view, element_ids, category_ids)',
     '1.14.0 after-open check narrowed by category'),
    ('fiv_window.py', 'self.drawer.true_height()', '1.13.0 parked height not saved'),
    ('fiv_window.py', 'self.drawer.restore_now()', '1.13.0 closing while parked'),
    ('fiv_ui.py', 'chrome.drawer = WindowDrawer(', '1.13.0 message window shrinks too'),
    ('script.py', 'fiv_window.FindByIdWindow(', '1.8.0 Find by ID with nothing selected'),
    ('script.py', 'by_id.skipped', '1.9.0 skip straight to the views'),
    ('script.py', 'fiv_model.zoom_here(', '1.12.0 zoom in the view you are in'),
    ('fiv_window.py', "settings['zoom_here']", '1.12.0 zoom here remembered'),
    ('script.py', 'element_ids = window.element_ids', '1.9.0 zoom uses the final selection'),
    ('script.py', 'category_ids = window.category_ids', '1.10.0 categories passed to the open'),
]


def rule_features_wired(folder):
    """Every feature in the changelog has its call site."""
    problems = []
    for filename, needle, feature in FEATURES:
        path = os.path.join(folder, filename)
        if not os.path.isfile(path):
            problems.append('{0} is missing, so "{1}" cannot ship'.format(filename, feature))
            continue
        if needle not in read(path):
            problems.append('"{0}" is not wired: {1} never mentions {2}'.format(
                feature, filename, needle))
    return problems


def rule_shrink_drawer(folder):
    """Every window shrinks to the taskbar, and the slide is always released.

    Four of the five ways this breaks fail silently: a window with no drawer at
    all, a button drawn but never wired, a MinHeight left clamped so the slide
    stops half way, and a body never unpinned so the window can never be
    resized again.
    """
    problems = []

    windows = []
    for name in LAYOUTS:
        path = os.path.join(folder, name)
        if os.path.isfile(path) and 'x:Name="HeaderBar"' in read(path):
            windows.append(name)

    for name in windows:
        text = read(os.path.join(folder, name))
        for needed in ('x:Name="ShrinkBtn"', 'x:Name="PathShrink"',
                       'x:Name="PathExpand"', 'x:Name="RootGrid"'):
            if needed not in text:
                problems.append('{0} is a window with no {1}: every window '
                                'shrinks to the taskbar'.format(name, needed))

    wired = 0
    for _name, path in module_files(folder):
        wired += len(re.findall(r'WindowDrawer\(', read_code(path)))
    # one class plus one drawer per window
    if wired < len(windows) + 1:
        problems.append('{0} windows carry a header but only {1} WindowDrawer '
                        'references exist: a shrink button drawn and never '
                        'wired does nothing'.format(len(windows), wired))

    ui_code = read_code(os.path.join(folder, 'fiv_ui.py'))
    for needed, why in (
            ('MinHeight = 0', 'MinHeight vetoes the slide and leaves it half shut'),
            ('SizeToContent.Manual', 'SizeToContent vetoes the slide too'),
            ('ResizeMode.NoResize', 'a parked bar must not be resizable'),
            ('self.window.MinHeight = min_height', 'MinHeight is never put back')):
        if needed not in ui_code:
            problems.append('the drawer never does "{0}": {1}'.format(needed, why))

    # both ways out have to unpin: the slide back AND the no-animation restore
    # used when the window is closed while parked. One of the two is a half fix
    # that leaves a window nobody can resize.
    if ui_code.count('Double.NaN') < 2:
        problems.append('the body is unpinned on only one path out of the '
                        'drawer; both expanding and restoring have to do it, '
                        'or the window can never be resized again')

    if 'self.grips' not in ui_code:
        problems.append('the resize grips are never parked with the window, so '
                        'they line the bar with invisible drag handles')
    return problems


RULES = [
    ('xaml parses as XML', rule_xaml_parses),
    ('fiv_clr imported before any .NET name', rule_clr_first),
    ('every module loads against the stub API', rule_namespaces),
    ('no StaticResource in a layout', rule_no_static_resource),
    ('every DynamicResource key exists', rule_dynamic_keys_exist),
    ('style TargetType matches the element', rule_style_targettype),
    ('every FindName has an x:Name', rule_findname_has_xname),
    ('no f-strings', rule_no_fstrings),
    ('no print', rule_no_print),
    ('no bare .IntegerValue', rule_no_bare_integervalue),
    ('no System.Uri', rule_no_system_uri),
    ('both palettes cover every brush', rule_palette_keys),
    ('every SetResourceReference key exists', rule_setresourcereference_keys),
    ('every global a function uses exists', rule_globals_exist),
    ('version and tool name agree', rule_version_and_names),
    ('release specific enum members looked up late', rule_late_enum_members),
    ('every RevoBIM logo opens the easter egg', rule_easter_egg),
    ('every shipped feature is actually wired', rule_features_wired),
    ('every window shrinks to the taskbar', rule_shrink_drawer),
]


def run(folder=HERE, only=None):
    failures = []
    for label, rule in RULES:
        if only and rule.__name__ != only:
            continue
        try:
            problems = rule(folder)
        except Exception as error:
            problems = ['the rule itself threw: {0}: {1}'.format(
                type(error).__name__, error)]
        if problems:
            failures.append((label, problems))
    return failures


def report(failures, out=sys.stdout):
    if not failures:
        out.write('all {0} rules pass\n'.format(len(RULES)))
        return 0
    for label, problems in failures:
        out.write('FAIL  {0}\n'.format(label))
        for problem in problems:
            out.write('        {0}\n'.format(problem))
    out.write('{0} of {1} rules failed\n'.format(len(failures), len(RULES)))
    return 1


# ---------------------------------------------------------------------------
# self test
# ---------------------------------------------------------------------------
#
# Each entry breaks one rule on purpose.  A rule that does not catch its own
# breakage is doing nothing, however reassuring it looks in the pass list.

def _break_replace(folder, filename, old, new):
    path = os.path.join(folder, filename)
    text = read(path)
    if old not in text:
        raise Exception('selftest could not find {0!r} in {1}'.format(old, filename))
    handle = open(path, 'w')
    try:
        handle.write(text.replace(old, new, 1))
    finally:
        handle.close()


def _break_append(folder, filename, text):
    path = os.path.join(folder, filename)
    handle = open(path, 'a')
    try:
        handle.write(text)
    finally:
        handle.close()


BREAKAGES = [
    ('rule_xaml_parses', lambda f: _break_replace(
        f, 'FindInView.xaml', '<!-- ===================== header ===================== -->',
        '<!-- --------------------- header --------------------- -->')),
    ('rule_clr_first', lambda f: _break_replace(
        f, 'fiv_model.py', 'import fiv_clr  # noqa: F401', '# fiv_clr removed')),
    ('rule_namespaces', lambda f: _break_replace(
        f, 'fiv_window.py', 'from System.ComponentModel import ListSortDirection',
        'from System.Windows.Controls import ListSortDirection')),
    ('rule_no_static_resource', lambda f: _break_replace(
        f, 'FindInView.xaml', 'Style="{DynamicResource ChipButton}"',
        'Style="{StaticResource ChipButton}"')),
    ('rule_dynamic_keys_exist', lambda f: _break_replace(
        f, 'FindInView.xaml', '{DynamicResource ChipButton}',
        '{DynamicResource ChipButtonn}')),
    ('rule_style_targettype', lambda f: _break_replace(
        f, 'FindInView.xaml', 'Style="{DynamicResource ChipButton}"',
        'Style="{DynamicResource ThemedTextBox}"')),
    ('rule_findname_has_xname', lambda f: _break_replace(
        f, 'fiv_window.py', "find('CountText')", "find('CountTextt')")),
    ('rule_no_fstrings', lambda f: _break_append(
        f, 'fiv_core.py', '\n\ndef _broken(value):\n    return f"{value}"\n')),
    ('rule_no_print', lambda f: _break_append(
        f, 'fiv_core.py', '\n\ndef _noisy():\n    print("hello")\n')),
    ('rule_no_bare_integervalue', lambda f: _break_append(
        f, 'fiv_model.py', '\n\ndef _bad(element_id):\n    return element_id.IntegerValue\n')),
    ('rule_no_system_uri', lambda f: _break_append(
        f, 'fiv_ui.py', '\nfrom System import Uri\n')),
    ('rule_palette_keys', lambda f: _break_replace(
        f, 'theme.py', "    'RedBrush':      '#B4302C',\n", '')),
    ('rule_setresourcereference_keys', lambda f: _break_replace(
        f, 'fiv_window.py', "'ThemedCheckBox')", "'ThemedCheckBoxx')")),
    ('rule_globals_exist', lambda f: _break_replace(
        f, 'fiv_model.py', 'def view_type_label(view):', 'def view_type_label_renamed(view):')),
    ('rule_version_and_names', lambda f: _break_replace(
        f, 'fiv_core.py', 'TOOL_NAME = "Find in View"', 'TOOL_NAME = "Find In Views"')),
    ('rule_late_enum_members', lambda f: _break_replace(
        f, 'fiv_model.py', 'member = getattr(PostableCommand, name, None)',
        'member = PostableCommand.TileWindows')),
    ('rule_shrink_drawer', lambda f: _break_replace(
        f, 'fiv_ui.py', 'self.root.Height = Double.NaN', 'pass  #')),
    ('rule_features_wired', lambda f: _break_replace(
        f, 'fiv_window.py', 'remembered = fiv_model.find_remembered(rows,',
        'remembered = None  # (')),
    ('rule_easter_egg', lambda f: _break_replace(
        f, 'fiv_window.py',
        "fiv_ui.wire_egg(find('HeaderIcon'), self.window, self.palette_name)\n        self.chrome",
        'self.chrome')),
]


def selftest(out=sys.stdout):
    baseline = run(HERE)
    if baseline:
        out.write('the tool as shipped does not pass its own check:\n')
        report(baseline, out)
        return 1

    caught = 0
    missed = []
    for rule_name, breakage in BREAKAGES:
        folder = tempfile.mkdtemp(prefix='fiv_selftest_')
        target = os.path.join(folder, FOLDER_NAME + '.pushbutton')
        shutil.copytree(HERE, target)
        try:
            breakage(target)
            failures = run(target, only=rule_name)
            if failures:
                caught += 1
                out.write('caught   {0}\n'.format(rule_name))
            else:
                missed.append(rule_name)
                out.write('MISSED   {0}\n'.format(rule_name))
        except Exception as error:
            missed.append(rule_name)
            out.write('MISSED   {0} (the breakage itself failed: {1})\n'.format(
                rule_name, error))
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    out.write('{0} of {1} deliberate breakages caught\n'.format(
        caught, len(BREAKAGES)))
    return 0 if not missed else 1


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(selftest())
    sys.exit(report(run(HERE)))
