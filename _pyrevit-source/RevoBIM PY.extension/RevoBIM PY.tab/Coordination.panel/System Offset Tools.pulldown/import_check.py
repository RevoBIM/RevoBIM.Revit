# -*- coding: utf-8 -*-
"""RevoBIM System Offset - bench check.

Runs under plain CPython from this folder:

    python import_check.py
    python import_check.py --selftest

It loads every shipped module against a stub Revit and .NET
API that declares each name in the namespace the real API
puts it in, so a mis-namespaced import fails here rather than
showing up in Revit as a blank white pyRevit window with no
traceback in it.

--selftest breaks every rule on purpose and confirms the check
catches it. A rule nobody has tested is a rule that does not
work.
"""

from __future__ import print_function

import os
import re
import sys
import shutil
import tempfile
import types
import xml.dom.minidom

HERE = os.path.dirname(os.path.abspath(__file__))

MODULES = (
    'so_clr', 'theme', 'so_core', 'so_model', 'so_ui',
    'so_command_host', 'offset_prompt', 'angle_prompt', 'so_run', 'so_click',
    'so_clash', 'clash_window', 'so_clash_run',
    'results_window', 'settings_window',
)

LAYOUTS = ('SystemOffsetSettings.xaml', 'SystemOffsetResults.xaml',
           'OffsetPrompt.xaml', 'AnglePrompt.xaml', 'ClashOffset.xaml')
THEME_FILE = 'Theme.xaml'

BUTTONS = (
    'RevoBIM System Offset.pushbutton',
    'RevoBIM Offset Break.pushbutton',
    'RevoBIM Click System.pushbutton',
    'RevoBIM Clash Offset.pushbutton',
    'RevoBIM System Offset Settings.pushbutton',
)

# The two that drive the model. Both come through so_run.run,
# so a copied loader that forgot to change the mode would give
# two buttons doing the same thing and looking correct.
COMMAND_BUTTONS = (
    'RevoBIM System Offset.pushbutton',
    'RevoBIM Offset Break.pushbutton',
    'RevoBIM Click System.pushbutton',
    'RevoBIM Clash Offset.pushbutton',
)

# Names an earlier delivery of this tool used. pyRevit names a
# ribbon item after its folder, so a bundle sharing a name with
# one already installed in the same panel fails the load with
# "The name already exists" - and pyRevit abandons the rest of
# that panel, so half the extension's buttons vanish.
LEGACY_FOLDER_STEMS = ('System Offset',)


# =========================================================
# The stub API
#
# Each name is declared in exactly one namespace and there is
# no __getattr__ fallback - that is the whole point. A module
# asking System.Windows for a name that really lives in
# System.Windows.Controls fails here.
# =========================================================

NAMESPACES = {
    'clr': ('AddReference', 'GetClrType'),
    'System': ('Object', 'String', 'Int32', 'Int64', 'Double'),
    'System.IO': ('StringReader', 'MemoryStream', 'File', 'Path'),
    'System.Xml': ('XmlReader',),
    'System.Windows': (
        'ResourceDictionary', 'WindowState', 'SizeToContent', 'Window',
        'Thickness', 'TextWrapping', 'FontWeights', 'PresentationSource',
        'SystemParameters', 'Visibility',
    ),
    'System.Windows.Markup': ('XamlReader',),
    'System.Windows.Controls': (
        'TextBlock', 'StackPanel', 'Border', 'Button', 'ComboBox',
        'CheckBox', 'RadioButton', 'TextBox', 'ScrollViewer', 'Image',
        'UniformGrid', 'Orientation',
    ),
    'System.Windows.Controls.Primitives': ('Thumb', 'ToggleButton', 'Popup'),
    'System.Windows.Input': ('Cursors', 'Key', 'Keyboard'),
    'System.Windows.Interop': ('WindowInteropHelper',),
    'System.Windows.Media': (
        'SolidColorBrush', 'Color', 'ColorConverter', 'Brush', 'Brushes',
    ),
    'System.Windows.Media.Imaging': ('BitmapImage', 'BitmapCacheOption'),
    'System.Windows.Threading': ('DispatcherTimer',),
    'System.Windows.Forms': ('Screen',),
    'Autodesk.Revit.DB': (
        'XYZ', 'Line', 'Curve', 'Transaction', 'TransactionGroup',
        'Solid', 'GeometryInstance', 'Transform', 'ViewDetailLevel',
        'SolidUtils', 'BooleanOperationsUtils', 'BooleanOperationsType',
        'InsulationLiningBase', 'RevitLinkInstance',
        'TransactionStatus', 'ElementId', 'Element', 'ElementTransformUtils',
        'BuiltInParameter', 'BuiltInCategory', 'IFailuresPreprocessor',
        'FailureProcessingResult', 'Connector', 'ConnectorType',
        'FilteredElementCollector', 'Options', 'Reference',
    ),
    'Autodesk.Revit.DB.Plumbing': ('PlumbingUtils', 'Pipe'),
    'Autodesk.Revit.DB.Mechanical': ('MechanicalUtils', 'Duct'),
    'Autodesk.Revit.DB.Electrical': ('CableTray', 'Conduit'),
    'Autodesk.Revit.UI': (
        'TaskDialog', 'UIThemeManager', 'UITheme', 'RevitCommandId',
        'PostableCommand', 'UIApplication', 'UIDocument',
        'IExternalEventHandler', 'ExternalEvent',
    ),
    'Autodesk.Revit.UI.Selection': ('ObjectType', 'ISelectionFilter'),
    'Autodesk.Revit.Exceptions': ('OperationCanceledException',),
}


class _StubMeta(type):
    """Class level attribute access, so XYZ.Zero and
    ConnectorType.End resolve without being declared."""

    def __getattr__(cls, item):
        if item.startswith('__'):
            raise AttributeError(item)
        return stub_class(cls.__name__ + '.' + item)


def stub_class(name):
    """A declared .NET name, as a class.

    It has to be a class rather than an instance, because the
    tool subclasses ISelectionFilter and IFailuresPreprocessor
    at module load and a subclass of an instance is a TypeError.
    """
    short = str(name.split('.')[-1])

    def _init(self, *args, **kwargs):
        pass

    def _getattr(self, item):
        if item.startswith('__'):
            raise AttributeError(item)
        return stub_class(name + '.' + item)()

    def _call(self, *args, **kwargs):
        return stub_class(name)()

    return _StubMeta(short, (object,), {
        '__init__': _init,
        '__getattr__': _getattr,
        '__call__': _call,
        '_stub_name': name,
    })


def install_stubs():
    made = []
    for namespace in sorted(NAMESPACES.keys()):
        module = types.ModuleType(namespace)
        module.__path__ = []
        for name in NAMESPACES[namespace]:
            setattr(module, name, stub_class(namespace + '.' + name))
        sys.modules[namespace] = module
        made.append(namespace)

    # Parent packages must expose their children by attribute,
    # or "from A.B import C" cannot resolve.
    for namespace in made:
        if '.' not in namespace:
            continue
        parent, child = namespace.rsplit('.', 1)
        if parent in sys.modules:
            setattr(sys.modules[parent], child, sys.modules[namespace])

    sys.modules['clr'].AddReference = lambda *a, **k: None
    return made


# =========================================================
# Small helpers
# =========================================================

def read(path):
    handle = open(path, 'rb')
    try:
        return handle.read().decode('utf-8-sig', 'replace')
    finally:
        handle.close()


def python_files(root):
    found = []
    for name in MODULES:
        path = os.path.join(root, name + '.py')
        if os.path.isfile(path):
            found.append((name + '.py', path))
    for button in BUTTONS:
        path = os.path.join(root, button, 'script.py')
        if os.path.isfile(path):
            found.append((button + '/script.py', path))
    return found


def xaml_files(root):
    found = []
    for name in os.listdir(root):
        if name.lower().endswith('.xaml'):
            found.append((name, os.path.join(root, name)))
    return sorted(found)


def strip_comments(text):
    return re.sub(r'<!--.*?-->', '', text, flags=re.S)


def code_only(text):
    """Python source with comment lines and docstrings dropped.

    A rule that fires on the sentence explaining the rule is a
    rule nobody can keep.
    """
    text = re.sub(r'(?s)""".*?"""', '', text)
    text = re.sub(r"(?s)'''.*?'''", '', text)
    kept = []
    for line in text.splitlines():
        if line.strip().startswith('#'):
            continue
        kept.append(line.split('#')[0])
    return '\n'.join(kept)


def theme_keys(root):
    path = os.path.join(root, THEME_FILE)
    if not os.path.isfile(path):
        return set()
    return set(re.findall(r'x:Key="([^"]+)"', read(path)))


# =========================================================
# The rules
# =========================================================

def rule_xaml_parses(root):
    """Every .xaml parses as XML.

    XML forbids a run of two hyphens inside a comment, so a
    banner drawn with hyphens kills XamlReader.Load with
    nothing readable to show for it.
    """
    problems = []
    for name, path in xaml_files(root):
        try:
            xml.dom.minidom.parseString(read(path).encode('utf-8'))
        except Exception as error:
            problems.append('{0} will not parse as XML: {1}'.format(name, error))
    return problems


def rule_clr_first(root):
    """Nothing reaches into System.* or Autodesk.* before so_clr.

    pyRevit does not preload WPF into every engine, so a module
    opening with "from System.Windows import X" with nothing
    having referenced PresentationFramework throws ImportError
    at module load.
    """
    problems = []
    for name, path in python_files(root):
        if name == 'so_clr.py':
            continue
        lines = read(path).splitlines()
        clr_line = None
        first_dotnet = None
        for index, line in enumerate(lines):
            # Only a module level import runs at load time. One
            # inside a function runs when it is called, which is
            # after so_clr has already done its work.
            if line[:1].isspace():
                continue
            text = line.strip()
            if re.match(r'^(import\s+so_clr|from\s+so_clr\s+import)', text):
                if clr_line is None:
                    clr_line = index
            if re.match(r'^(from|import)\s+(System|Autodesk)\b', text):
                if first_dotnet is None:
                    first_dotnet = index
        if first_dotnet is None:
            continue
        if clr_line is None:
            problems.append('{0} reaches into System/Autodesk but never '
                            'imports so_clr'.format(name))
        elif clr_line > first_dotnet:
            problems.append('{0} imports so_clr at line {1}, after its first '
                            'System/Autodesk import at line {2}'
                            .format(name, clr_line + 1, first_dotnet + 1))
    return problems


def rule_no_static_resource_in_layout(root):
    """No StaticResource in a layout file.

    Theme.xaml is merged in after XamlReader has parsed the
    layout, so a StaticResource fails at load. Theme.xaml itself
    is exempt - it is one dictionary parsed whole.
    """
    problems = []
    for name in LAYOUTS:
        path = os.path.join(root, name)
        if not os.path.isfile(path):
            continue
        if 'StaticResource' in strip_comments(read(path)):
            problems.append('{0} uses StaticResource in a layout'.format(name))
    return problems


def rule_dynamic_keys_exist(root):
    """Every DynamicResource key is defined in Theme.xaml."""
    known = theme_keys(root)
    problems = []
    for name, path in xaml_files(root):
        text = strip_comments(read(path))
        for key in set(re.findall(r'\{DynamicResource\s+([A-Za-z0-9_]+)\}', text)):
            if key not in known:
                problems.append('{0} asks for DynamicResource {1}, which '
                                'Theme.xaml does not define'.format(name, key))
    return problems


def rule_style_target_type(root):
    """No Style="{DynamicResource K}" on an element K's TargetType
    does not match. WPF raises when the style is applied, which
    also surfaces as a dead window."""
    path = os.path.join(root, THEME_FILE)
    if not os.path.isfile(path):
        return []
    theme_text = read(path)
    targets = {}
    for block in re.findall(r'<Style\b[^>]*>', theme_text):
        key = re.search(r'x:Key="([^"]+)"', block)
        target = re.search(r'TargetType="([^"]+)"', block)
        if key and target:
            targets[key.group(1)] = target.group(1).split(':')[-1]

    problems = []
    for name, layout_path in xaml_files(root):
        if name == THEME_FILE:
            continue
        text = strip_comments(read(layout_path))
        for element, attributes in re.findall(r'<([A-Za-z]+)\b([^>]*)>', text):
            match = re.search(r'Style="\{DynamicResource\s+([A-Za-z0-9_]+)\}"',
                              attributes)
            if not match:
                continue
            key = match.group(1)
            if key not in targets:
                continue
            if targets[key] != element:
                problems.append(
                    '{0}: style {1} targets {2} but is applied to a {3}'
                    .format(name, key, targets[key], element))
    return problems


def rule_findname_has_xname(root):
    """Every FindName has a matching x:Name.

    Matches an aliased call too - the code aliases it as
    self.find - because a rule that only catches literal
    FindName("X") does nothing at all.
    """
    names = set()
    for _name, path in xaml_files(root):
        names.update(re.findall(r'x:Name="([^"]+)"', read(path)))

    problems = []
    for name, path in python_files(root):
        text = read(path)
        asked = set(re.findall(
            r'(?:FindName|self\.find|find)\(\s*[\'"]([A-Za-z0-9_]+)[\'"]\s*\)',
            text))
        for key in sorted(asked):
            if key not in names:
                problems.append('{0} looks up "{1}", which no XAML declares'
                                .format(name, key))
    return problems


def rule_no_fstrings(root):
    """No f-strings - IronPython 2.7 cannot parse one."""
    problems = []
    for name, path in python_files(root):
        for index, line in enumerate(read(path).splitlines()):
            if re.search(r'(?<![A-Za-z0-9_])[fF][\'"]', line):
                problems.append('{0} line {1} looks like an f-string'
                                .format(name, index + 1))
    return problems


def rule_no_print(root):
    """No print statements in shipped code."""
    problems = []
    for name, path in python_files(root):
        for index, line in enumerate(read(path).splitlines()):
            stripped = line.strip()
            if stripped.startswith('#'):
                continue
            if re.match(r'^print\b', stripped):
                problems.append('{0} line {1} uses print'.format(name, index + 1))
    return problems


def rule_no_bare_integervalue(root):
    """No bare .IntegerValue - removed in Revit 2026.

    Allowed only inside the guarded eid_value helper.
    """
    problems = []
    for name, path in python_files(root):
        lines = read(path).splitlines()
        inside = False
        for index, line in enumerate(lines):
            if re.match(r'^def\s+eid_value\b', line):
                inside = True
                continue
            if inside and line and not line[0].isspace():
                inside = False
            if line.strip().startswith('#'):
                continue
            if '.IntegerValue' in line.split('#')[0] and not inside:
                problems.append('{0} line {1} touches .IntegerValue outside '
                                'eid_value'.format(name, index + 1))
    return problems


def rule_no_system_uri(root):
    """No System.Uri - the assembly moved in Revit 2025 and the
    import throws before any of the script runs."""
    problems = []
    for name, path in python_files(root):
        text = code_only(read(path))
        if re.search(r'from\s+System\s+import\s+[^\n]*\bUri\b', text):
            problems.append('{0} imports System.Uri'.format(name))
        if re.search(r'\bSystem\.Uri\b', text):
            problems.append('{0} names System.Uri'.format(name))
        if 'UriSource' in text:
            problems.append('{0} uses BitmapImage.UriSource'.format(name))
    return problems


def rule_palettes_match(root):
    """Both palettes carry every key, and Theme.xaml has a brush
    for each one."""
    path = os.path.join(root, 'theme.py')
    if not os.path.isfile(path):
        return ['theme.py is missing']
    text = read(path)

    def keys_in(block_name):
        match = re.search(block_name + r'\s*=\s*\{(.*?)\n\}', text, re.S)
        if not match:
            return set()
        return set(re.findall(r"'([A-Za-z0-9_]+)'\s*:", match.group(1)))

    dark = keys_in('DARK')
    light = keys_in('LIGHT')
    problems = []
    if not dark:
        problems.append('theme.py has no DARK palette')
    for key in sorted(dark - light):
        problems.append('the light palette is missing {0}'.format(key))
    for key in sorted(light - dark):
        problems.append('the dark palette is missing {0}'.format(key))

    known = theme_keys(root)
    for key in sorted(dark):
        if key not in known:
            problems.append('Theme.xaml has no brush for palette key {0}'
                            .format(key))
    return problems


def rule_no_bare_non_ascii(root):
    """No non-ASCII outside a u'' literal.

    An em dash in a plain str literal is a known way to kill a
    module under IronPython 2.7, and it is invisible in a diff.
    """
    problems = []
    for name, path in python_files(root):
        for index, line in enumerate(read(path).splitlines()):
            try:
                line.encode('ascii')
                continue
            except UnicodeEncodeError:
                pass
            if line.strip().startswith('#'):
                continue
            if re.search(r'u[\'"]', line):
                continue
            problems.append('{0} line {1} carries non-ASCII outside a u literal'
                            .format(name, index + 1))
    return problems


def rule_no_duplicate_defs(root):
    """No function or method defined twice in the same scope.

    Python silently keeps the last one, so a duplicate is a
    block of code that quietly stopped existing.

    Walked with ast rather than matched on indentation. The
    indentation version could not tell one class's method from
    another's, so two classes each carrying AllowElement - which
    is correct and normal for two ISelectionFilters - failed
    the check.
    """
    import ast

    problems = []
    for name, path in python_files(root):
        try:
            tree = ast.parse(read(path))
        except SyntaxError as error:
            problems.append('{0} will not parse: {1}'.format(name, error))
            continue

        def scan(node, where):
            seen = {}
            for child in getattr(node, 'body', []):
                if isinstance(child, (ast.FunctionDef,)):
                    if child.name in seen:
                        problems.append(
                            '{0} defines {1}{2} twice, at lines {3} and {4}'
                            .format(name, where, child.name,
                                    seen[child.name], child.lineno))
                    else:
                        seen[child.name] = child.lineno
                    scan(child, where + child.name + '.')
                elif isinstance(child, ast.ClassDef):
                    scan(child, where + child.name + '.')

        scan(tree, '')
    return problems


def rule_globals_exist(root):
    """Every global name a function reaches for exists.

    This is the rule that catches a block edit going wrong: a
    replacement whose anchor did not match leaves the code that
    USES a name while the code that DEFINES it never lands, and
    nothing shows up until the line runs in Revit. That is
    exactly how "global name 'bank' is not defined" shipped.

    symtable rather than a regex, so it understands scopes,
    comprehensions and nested functions without being told.
    """
    import symtable
    try:
        import builtins
    except ImportError:
        import __builtin__ as builtins

    # Names IronPython puts in a pyRevit script's scope that
    # CPython knows nothing about.
    injected = set(['__revit__', '__title__', '__author__', '__doc__',
                    '__file__', '__name__', '__persistentengine__',
                    'unicode', 'basestring', 'xrange', 'long', 'reduce',
                    'raw_input', 'execfile', 'unichr'])

    problems = []
    for name, path in python_files(root):
        source = read(path)
        try:
            table = symtable.symtable(source, name, 'exec')
        except SyntaxError as error:
            problems.append('{0} will not parse: {1}'.format(name, error))
            continue

        known = set(table.get_identifiers()) | injected
        known.update(dir(builtins))

        def walk(scope, where):
            for symbol in scope.get_symbols():
                if not (symbol.is_global() and symbol.is_referenced()):
                    continue
                if symbol.get_name() in known:
                    continue
                problems.append('{0}: {1} reaches for "{2}", which nothing '
                                'defines'.format(name, where or 'the module',
                                                 symbol.get_name()))
            for child in scope.get_children():
                walk(child, child.get_name())

        walk(table, '')
    return problems


def rule_modules_load(root):
    """Every module loads against the stub API."""
    problems = []
    saved_path = list(sys.path)
    saved_modules = dict(sys.modules)
    try:
        install_stubs()
        sys.path.insert(0, root)
        for name in MODULES:
            if name in sys.modules:
                del sys.modules[name]
        for name in MODULES:
            if not os.path.isfile(os.path.join(root, name + '.py')):
                problems.append('{0}.py is missing'.format(name))
                continue
            try:
                __import__(name)
            except Exception as error:
                problems.append('{0}.py will not load: {1}: {2}'
                                .format(name, type(error).__name__, error))
    finally:
        sys.path[:] = saved_path
        for key in list(sys.modules.keys()):
            if key not in saved_modules:
                del sys.modules[key]
        sys.modules.update(saved_modules)
    return problems


def rule_ribbon_name_matches(root):
    """Every ribbon name is unique, prefixed and consistent.

    pyRevit names a ribbon item after its folder, and the bundle
    title and __title__ have to agree with it, or a rename
    leaves the old name showing in one place. A plain name also
    cannot be found in Revit's Keyboard Shortcuts list, because
    it clashes with other addins.
    """
    problems = []
    seen = set()
    for folder_name in BUTTONS:
        folder = os.path.join(root, folder_name)
        if not os.path.isdir(folder):
            problems.append('{0} is missing'.format(folder_name))
            continue

        wanted = folder_name[:-len('.pushbutton')]
        if not wanted.startswith('RevoBIM '):
            problems.append('{0} is not prefixed RevoBIM'.format(folder_name))
        if wanted in seen:
            problems.append('two buttons are called {0}'.format(wanted))
        seen.add(wanted)

        bundle = os.path.join(folder, 'bundle.yaml')
        if os.path.isfile(bundle):
            match = re.search(r'^title:\s*(.+)$', read(bundle), re.M)
            if match and match.group(1).strip() != wanted:
                problems.append('{0}: the bundle title is "{1}"'
                                .format(folder_name, match.group(1).strip()))

        script = os.path.join(folder, 'script.py')
        if os.path.isfile(script):
            match = re.search(r'__title__\s*=\s*[\'"](.+?)[\'"]', read(script))
            if match is None:
                problems.append('{0}: no __title__'.format(folder_name))
            elif match.group(1) != wanted:
                problems.append('{0}: __title__ is "{1}"'
                                .format(folder_name, match.group(1)))
    return problems


def rule_command_buttons_differ(root):
    """No two command buttons may start the same way.

    They share every module and their loaders are near
    identical files, so one copied without changing the entry
    point or the mode gives two buttons that do the same thing
    and look entirely correct.
    """
    calls = {}
    for folder_name in COMMAND_BUTTONS:
        path = os.path.join(root, folder_name, 'script.py')
        if not os.path.isfile(path):
            continue
        match = re.search(r'so_[a-z_]+\.run\(([^)]*)\)', read(path))
        calls[folder_name] = match.group(0).strip() if match else None

    problems = []
    for folder_name, call in sorted(calls.items()):
        if call is None:
            problems.append('{0} never routes into a run loop'
                            .format(folder_name))
    # ANY two matching is the bug, not only all of them. With
    # two buttons those are the same test; with three they are
    # not, and the all-identical version quietly stopped
    # catching anything the moment the third arrived.
    seen = {}
    for folder_name, call in sorted(calls.items()):
        if call is None:
            continue
        if call in seen:
            problems.append('{0} and {1} both start with "{2}", so they do '
                            'the same thing'
                            .format(seen[call], folder_name, call))
        else:
            seen[call] = folder_name
    return problems


def rule_no_legacy_name_collision(root):
    """This bundle's folder cannot collide with an older one.

    Relying on the delivery notes to have the old folder deleted
    is not a design; the second delivery has to be unable to
    collide even when the first is still there.
    """
    stem = os.path.basename(root.rstrip(os.sep))
    for suffix in ('.pulldown', '.pushbutton', '.panel'):
        if stem.endswith(suffix):
            stem = stem[:-len(suffix)]
            break
    problems = []
    if stem in LEGACY_FOLDER_STEMS:
        problems.append(
            'the bundle folder is "{0}", which an earlier delivery also used - '
            'pyRevit will refuse the load and drop the rest of the panel'
            .format(stem))
    return problems


def rule_egg_is_wired(root):
    """The easter egg is wired in, and to the logo.

    Three slow clicks on the RevoBIM logo. Arming it from a tool
    is one of the feature's anchors, so a hand wired tool brings
    it back on its own even if a delivery has clobbered
    startup.py.
    """
    problems = []
    ui_path = os.path.join(root, 'so_ui.py')
    if not os.path.isfile(ui_path):
        return ['so_ui.py is missing']
    text = read(ui_path)
    if 'egg_hook' not in text or 'def attach_egg' not in text:
        problems.append('so_ui.py does not wire the easter egg')
    if 'LogoImage' not in text:
        problems.append('the easter egg is not attached to the logo')

    for name in ('results_window.py', 'settings_window.py',
                 'offset_prompt.py', 'angle_prompt.py', 'clash_window.py'):
        path = os.path.join(root, name)
        if os.path.isfile(path) and 'attach_egg' not in read(path):
            problems.append('{0} never calls attach_egg'.format(name))

    for name in LAYOUTS:
        path = os.path.join(root, name)
        if os.path.isfile(path) and 'x:Name="LogoImage"' not in read(path):
            problems.append('{0} has no LogoImage for the egg to hang on'
                            .format(name))
    return problems


def rule_no_shared_files(root):
    """The delivery ships no shared and singular file.

    startup.py, a hook, lib\\revobim\\__init__.py or a panel
    bundle.yaml shipped from a tool silently overwrites whatever
    the last tool put there, and nothing fails when it happens.
    """
    banned = ('startup.py', '__init__.py')
    problems = []
    for folder, _dirs, files in os.walk(root):
        for name in files:
            if name in banned:
                problems.append('this tool ships {0}, which is a shared file'
                                .format(os.path.join(folder, name)))
    return problems


RULES = (
    ('every .xaml parses as XML', rule_xaml_parses),
    ('so_clr is imported before any System/Autodesk name', rule_clr_first),
    ('no StaticResource in a layout', rule_no_static_resource_in_layout),
    ('every DynamicResource key exists in Theme.xaml', rule_dynamic_keys_exist),
    ('no style applied to a mismatched TargetType', rule_style_target_type),
    ('every FindName has a matching x:Name', rule_findname_has_xname),
    ('no f-strings', rule_no_fstrings),
    ('no print statements', rule_no_print),
    ('no bare .IntegerValue', rule_no_bare_integervalue),
    ('no System.Uri', rule_no_system_uri),
    ('both palettes match and Theme.xaml covers them', rule_palettes_match),
    ("no non-ASCII outside a u'' literal", rule_no_bare_non_ascii),
    ('nothing is defined twice', rule_no_duplicate_defs),
    ('every global a function reaches for exists', rule_globals_exist),
    ('every module loads against the stub API', rule_modules_load),
    ('the ribbon names are unique and consistent', rule_ribbon_name_matches),
    ('no two command buttons start the same way', rule_command_buttons_differ),
    ('the bundle folder cannot collide with an older delivery',
     rule_no_legacy_name_collision),
    ('the easter egg is wired to the logo', rule_egg_is_wired),
    ('no shared and singular file is shipped', rule_no_shared_files),
)


def run(root, quiet=False):
    failures = 0
    for title, rule in RULES:
        try:
            problems = rule(root)
        except Exception as error:
            problems = ['the rule itself threw: {0}: {1}'
                        .format(type(error).__name__, error)]
        if problems:
            failures += 1
            if not quiet:
                sys.stdout.write('FAIL  {0}\n'.format(title))
                for problem in problems:
                    sys.stdout.write('        {0}\n'.format(problem))
        elif not quiet:
            sys.stdout.write('ok    {0}\n'.format(title))
    return failures


# =========================================================
# Selftest
# =========================================================

def _edit(root, relative, find, replace):
    path = os.path.join(root, relative)
    text = read(path)
    if find not in text:
        raise AssertionError('selftest could not find {0!r} in {1}'
                             .format(find[:40], relative))
    handle = open(path, 'wb')
    try:
        handle.write(text.replace(find, replace, 1).encode('utf-8'))
    finally:
        handle.close()


def _append(root, relative, text):
    handle = open(os.path.join(root, relative), 'ab')
    try:
        handle.write(text.encode('utf-8'))
    finally:
        handle.close()


def _rename_root(root, new_name):
    """Move the throwaway copy to a colliding folder name."""
    parent = os.path.dirname(root.rstrip(os.sep))
    target = os.path.join(parent, new_name)
    shutil.move(root, target)
    return target


BREAKAGES = (
    ('every .xaml parses as XML',
     lambda root: _edit(root, 'SystemOffsetResults.xaml',
                        '<!-- ==============================================',
                        '<!-- ----------------------------------------------')),
    ('so_clr is imported before any System/Autodesk name',
     lambda root: _edit(root, 'so_ui.py',
                        'import so_clr  # noqa: F401  assembly references first',
                        '# so_clr deliberately not imported')),
    ('no StaticResource in a layout',
     lambda root: _edit(root, 'SystemOffsetSettings.xaml',
                        'Style="{DynamicResource ChipButton}"',
                        'Style="{StaticResource ChipButton}"')),
    ('every DynamicResource key exists in Theme.xaml',
     lambda root: _edit(root, 'SystemOffsetResults.xaml',
                        '{DynamicResource Blue}', '{DynamicResource NotAKey}')),
    ('no style applied to a mismatched TargetType',
     lambda root: _edit(root, 'SystemOffsetResults.xaml',
                        '<Button x:Name="OkButton" Grid.Column="1"',
                        '<Border x:Name="OkButton" Grid.Column="1"')),
    ('every FindName has a matching x:Name',
     lambda root: _append(root, 'results_window.py',
                          '\n\ndef _selftest_probe(window):\n'
                          '    return window.FindName("NoSuchControl")\n')),
    ('no f-strings',
     lambda root: _append(root, 'so_core.py',
                          '\n\ndef _selftest_fstring(x):\n'
                          '    return f"{x}"\n')),
    ('no print statements',
     lambda root: _append(root, 'so_core.py',
                          '\n\ndef _selftest_print():\n'
                          '    print("hello")\n')),
    ('no bare .IntegerValue',
     lambda root: _append(root, 'so_model.py',
                          '\n\ndef _selftest_integer(element_id):\n'
                          '    return element_id.IntegerValue\n')),
    ('no System.Uri',
     lambda root: _append(root, 'so_ui.py',
                          '\n\ndef _selftest_uri(path):\n'
                          '    from System import Uri\n'
                          '    return Uri(path)\n')),
    ('both palettes match and Theme.xaml covers them',
     lambda root: _edit(root, 'theme.py',
                        "    'DisabledText':  '#A0A0A8',", "")),
    ("no non-ASCII outside a u'' literal",
     lambda root: _append(root, 'so_core.py',
                          '\n\ndef _selftest_dash():\n'
                          '    return "an \u2014 em dash"\n')),
    ('nothing is defined twice',
     lambda root: _append(root, 'so_core.py',
                          '\n\ndef eid_value(element_id):\n'
                          '    return 0\n')),
    ('every global a function reaches for exists',
     lambda root: _append(root, 'so_run.py',
                          '\n\ndef _selftest_missing():\n'
                          '    return len(no_such_name)\n')),
    ('every module loads against the stub API',
     lambda root: _edit(root, 'so_ui.py',
                        'from System.Windows.Input import Cursors, Key',
                        'from System.Windows import Cursors, Key')),
    ('the ribbon names are unique and consistent',
     lambda root: _edit(root, 'RevoBIM System Offset.pushbutton/script.py',
                        "__title__ = 'RevoBIM System Offset'",
                        "__title__ = 'Offset'")),
    ('no two command buttons start the same way',
     lambda root: _edit(root, 'RevoBIM Click System.pushbutton/script.py',
                        "so_click.run(uiapp)",
                        "so_run.run(uiapp)")),
    ('the bundle folder cannot collide with an older delivery',
     lambda root: _rename_root(root, 'System Offset.pulldown')),
    ('the easter egg is wired to the logo',
     lambda root: _edit(root, 'settings_window.py',
                        'so_ui.attach_egg(self.window)', 'pass')),
    ('no shared and singular file is shipped',
     lambda root: _append(root, 'startup.py', '# shared file\n')),
)


def _rule_fired(root, title):
    for name, rule in RULES:
        if name != title:
            continue
        try:
            return bool(rule(root))
        except Exception:
            return True
    return False


def selftest():
    sys.stdout.write('Selftest - breaking each rule on purpose\n\n')
    if run(HERE, quiet=True):
        sys.stdout.write('The tool does not pass its own check as shipped. '
                         'Run without --selftest first.\n')
        return 1

    failures = 0
    for title, breakage in BREAKAGES:
        temporary = tempfile.mkdtemp(prefix='revobim_so_')
        root = os.path.join(temporary, 'tool')
        try:
            shutil.copytree(HERE, root)
            moved = breakage(root)
            if _rule_fired(moved or root, title):
                sys.stdout.write('caught   {0}\n'.format(title))
            else:
                failures += 1
                sys.stdout.write('MISSED   {0}\n'.format(title))
        except Exception as error:
            failures += 1
            sys.stdout.write('BROKE    {0}: {1}\n'.format(title, error))
        finally:
            shutil.rmtree(temporary, ignore_errors=True)

    sys.stdout.write('\n{0} of {1} rules caught their own breakage.\n'
                     .format(len(BREAKAGES) - failures, len(BREAKAGES)))
    return 1 if failures else 0


def main():
    if '--selftest' in sys.argv:
        return selftest()
    sys.stdout.write('RevoBIM System Offset - bench check\n\n')
    failures = run(HERE)
    sys.stdout.write('\n{0} of {1} rules pass.\n'
                     .format(len(RULES) - failures, len(RULES)))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
