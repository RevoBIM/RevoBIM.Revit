# -*- coding: utf-8 -*-
"""Bench check for Family Find & Replace.

Run it with CPython from this folder:

    python import_check.py

It loads the shipped modules against a stub Revit and .NET API that declares
every name in the namespace the real API puts it in, so a mis-namespaced
import fails here rather than showing up in Revit as a blank white pyRevit
window.  It also enforces the RevoBIM house rules on the source and the XAML:

  * no f-strings, no print statements - the IronPython engine varies by release
  * no bare .IntegerValue outside the guarded eid_value helper
  * no System.Uri - it moved assemblies in Revit 2025
  * a clr.AddReference in the same file for every namespace it imports from
  * every imported name declared in the namespace the real API puts it in
  * only DynamicResource in the layouts, because Theme.xaml is merged after
    XamlReader has parsed them
  * every DynamicResource key and every brush asked for from code defined in
    Theme.xaml
  * no event handlers wired in XAML - they are unreliable under IronPython 2.7
  * every FindName matched by an x:Name in one of the layouts
"""

import ast
import os
import re
import sys
import types
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))

MODULES = ['ffr_core', 'ffr_ui']
SCRIPTS = ['script.py']
def _discover_layouts():
    """Every .xaml beside this file except the theme.

    Read off disk rather than listed by hand: a hardcoded list means a layout
    added later is checked by nothing at all, silently, which is exactly the
    kind of gap this file exists to close.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    found = []
    for name in sorted(os.listdir(here)):
        if not name.lower().endswith('.xaml'):
            continue
        if name == THEME:
            continue
        found.append(name)
    return found


THEME = 'Theme.xaml'
LAYOUTS = _discover_layouts()
#: Desk tools run under plain CPython, never inside Revit, so the house rules
#: for code that ships into Revit (no print, no f-strings...) do not apply.
SKIP_SOURCE = {'import_check.py', 'make_icon.py', 'bench_logic.py'}

X_NS = '{http://schemas.microsoft.com/winfx/2006/xaml}'


# ---------------------------------------------------------------------------
# what the real API puts where
# ---------------------------------------------------------------------------

NAMESPACE_NAMES = {
    'Autodesk.Revit.DB': [
        'BuiltInCategory', 'BuiltInParameter', 'Category', 'CategoryType',
        'Connector', 'ConnectorManager', 'Document', 'Domain', 'Element',
        'ElementClassFilter', 'ElementId', 'ElementSet',
        'ElementTransformUtils',
        'FailureProcessingResult', 'Family', 'FamilyInstance',
        'FamilyInstanceFilter', 'FamilyPlacementType', 'FamilySymbol',
        'FilteredElementCollector', 'FilteredWorksetCollector', 'Group',
        'GroupType',
        'IFailuresPreprocessor', 'ImportInstance', 'IndependentTag',
        'Level', 'Line',
        'LocationCurve',
        'LocationPoint', 'MEPModel', 'Options', 'Plane', 'Reference',
        'TagOrientation',
        'SketchPlane', 'StorageType', 'SubTransaction', 'Transaction',
        'TransactionGroup', 'Transform', 'UnitTypeId', 'UnitUtils', 'View',
        'ViewType', 'WorksharingUtils', 'XYZ',
    ],
    'Autodesk.Revit.DB.Electrical': [
        'ElectricalSystem', 'ElectricalSystemType', 'PanelScheduleView',
        'Wire',
    ],
    'Autodesk.Revit.DB.Plumbing': ['PlumbingUtils', 'Pipe'],
    'Autodesk.Revit.DB.Structure': ['StructuralType'],
    'Autodesk.Revit.UI': [
        'ExternalEvent', 'IExternalEventHandler', 'TaskDialog',
        'TaskDialogCommonButtons', 'TaskDialogResult', 'UIApplication',
        'UIDocument',
    ],
    'Autodesk.Revit.UI.Selection': [
        'ISelectionFilter', 'ObjectType', 'Selection',
    ],
    'System': ['Action', 'AppDomain', 'Array', 'Double', 'Enum', 'Guid',
               'Math', 'TimeSpan', 'Uri'],
    'System.Collections.Generic': ['Dictionary', 'HashSet', 'List'],
    'System.IO': ['Directory', 'File', 'MemoryStream', 'Path', 'StringReader'],
    'System.Windows': [
        'CornerRadius', 'FontWeights', 'GridLength', 'GridUnitType',
        'HorizontalAlignment', 'Point', 'PresentationSource', 'ResizeMode',
        'ResourceDictionary', 'SizeToContent', 'SystemParameters',
        'TextTrimming', 'TextWrapping', 'Thickness', 'VerticalAlignment',
        'Visibility', 'Window', 'WindowState',
    ],
    'System.Windows.Forms': ['Screen'],
    'System.Windows.Controls': [
        'Border', 'Button', 'CheckBox', 'ColumnDefinition', 'ComboBox',
        'Grid', 'Image', 'ListBox', 'ListBoxItem', 'Orientation',
        'RadioButton', 'RowDefinition', 'ScrollViewer', 'StackPanel',
        'TextBlock', 'TextBox', 'UniformGrid',
    ],
    'System.Windows.Input': ['Cursors', 'Key', 'Keyboard', 'ModifierKeys'],
    'System.Windows.Interop': ['HwndSource', 'WindowInteropHelper'],
    'System.Windows.Markup': ['XamlReader'],
    'System.Windows.Media': ['Brushes', 'Color', 'SolidColorBrush'],
    'System.Windows.Media.Imaging': ['BitmapCacheOption', 'BitmapImage'],
    'System.Windows.Threading': ['DispatcherPriority', 'DispatcherTimer'],
    'System.Xml': ['XmlReader'],
}

#: which assembly a namespace needs requesting from, and the names that count
ASSEMBLY_FOR = [
    ('Autodesk.Revit.DB', ['RevitAPI']),
    ('Autodesk.Revit.UI', ['RevitAPIUI']),
    ('System.Windows.Media', ['PresentationCore']),
    ('System.Windows.Input', ['PresentationCore']),
    ('System.Windows.Controls', ['PresentationFramework']),
    ('System.Windows.Markup', ['PresentationFramework']),
    ('System.Windows.Interop', ['PresentationFramework']),
    ('System.Windows.Threading', ['WindowsBase']),
    ('System.Windows.Forms', ['System.Windows.Forms']),
    ('System.Windows', ['PresentationFramework', 'PresentationCore',
                        'WindowsBase']),
    ('System.Xml', ['System.Xml']),
    ('System.IO', ['mscorlib']),
    ('System.Collections', ['mscorlib']),
    ('System', ['mscorlib']),
]

#: routed events that must be wired from Python with +=, never in XAML
XAML_EVENT_ATTRS = set("""
Click Checked Unchecked SelectionChanged TextChanged Loaded Unloaded Closed
Closing MouseDown MouseUp MouseLeftButtonDown MouseLeftButtonUp MouseMove
MouseDoubleClick KeyDown KeyUp PreviewKeyDown PreviewMouseLeftButtonDown
DragOver Drop Sorting Expanded Collapsed GotFocus LostFocus SizeChanged
StateChanged ValueChanged
""".split())

RESOURCE_KEY_PATTERN = re.compile(
    r"'(Bg[A-Za-z]+|Fg[A-Za-z]+|Acc[A-Za-z]+|Brd[A-Za-z]+|SelHi|Clear)'")

problems = []
notes = []


def fail(text):
    problems.append(text)


def note(text):
    notes.append(text)


# ---------------------------------------------------------------------------
# the stub API
# ---------------------------------------------------------------------------

class StubMeta(type):
    """Any attribute is another stub, so enum members resolve at call time."""

    def __getattr__(cls, item):
        if item.startswith('__'):
            raise AttributeError(item)
        return make_stub(item)


def make_stub(name):
    return StubMeta(str(name), (object,), {})


class StubClr(object):
    def __init__(self):
        self.references = []

    def AddReference(self, name):
        self.references.append(name)

    def AddReferenceByName(self, name):
        self.references.append(name)


def install_namespace(fullname, names):
    parts = fullname.split('.')
    for depth in range(1, len(parts) + 1):
        partial = '.'.join(parts[:depth])
        if partial not in sys.modules:
            sys.modules[partial] = types.ModuleType(partial)
        if depth > 1:
            setattr(sys.modules['.'.join(parts[:depth - 1])],
                    parts[depth - 1], sys.modules[partial])
    module = sys.modules[fullname]
    for name in names:
        setattr(module, name, make_stub(name))


def install_stubs():
    sys.modules['clr'] = StubClr()
    for fullname, names in NAMESPACE_NAMES.items():
        install_namespace(fullname, names)


# ---------------------------------------------------------------------------
# source checks
# ---------------------------------------------------------------------------

def source_files():
    found = []
    for name in sorted(os.listdir(HERE)):
        if name.endswith('.py') and name not in SKIP_SOURCE:
            found.append(name)
    return found


def check_source(name):
    path = os.path.join(HERE, name)
    handle = open(path, 'rb')
    try:
        text = handle.read().decode('utf-8')
    finally:
        handle.close()

    try:
        tree = ast.parse(text, filename=name)
    except SyntaxError as err:
        fail('{0}: will not parse - {1}'.format(name, err))
        return

    for index, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith('#'):
            continue
        if re.search(r"""\bf['"]""", line):
            fail('{0}:{1} f-string - IronPython 2.7 will not parse it'
                 .format(name, index))

    # System.Uri, checked on the tree so prose about it is not a false alarm
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == 'System':
            for alias in node.names:
                if alias.name == 'Uri':
                    fail('{0}:{1} System.Uri - it moved assemblies in Revit '
                         '2025, load images from bytes'.format(name,
                                                               node.lineno))
        if isinstance(node, ast.Attribute) and node.attr in ('Uri', 'UriSource'):
            fail('{0}:{1} {2} - System.Uri moved assemblies in Revit 2025, '
                 'load images from bytes'.format(name, node.lineno, node.attr))

    # print used as a statement or a call
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == 'print':
            fail('{0}:{1} print - the output window is not part of the house '
                 'style'.format(name, node.lineno))

    # .IntegerValue is only allowed inside the guarded helper
    guarded = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == 'eid_value':
            for child in ast.walk(node):
                guarded.add(getattr(child, 'lineno', -1))
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == 'IntegerValue':
            if node.lineno not in guarded:
                fail('{0}:{1} bare .IntegerValue - it was removed in Revit '
                     '2026, go through eid_value'.format(name, node.lineno))

    check_imports(name, tree, text)
    check_undefined_names(name, tree)
    return text


#: Names the module may use without defining: Python's own, the IronPython 2
#: ones a 2/3 guard may touch, and what pyRevit puts in a script's globals.
KNOWN_GLOBALS = set(dir(__builtins__) if isinstance(__builtins__, dict) is False
                    else __builtins__.keys()) | {
    '__file__', '__name__', '__doc__', '__revit__', '__persistentengine__',
    '__shiftclick__', 'unicode', 'basestring', 'long', 'xrange', 'unichr',
}


def check_undefined_names(name, tree):
    """A name used in a module but never imported or defined anywhere in it.

    Coarse on purpose - module wide rather than scope by scope - so it never
    cries wolf, and it still catches the case that matters: ffr_ui.py using
    Transaction without importing it, which parses, passes the stub import,
    and only throws in Revit on the line that needs it. Added in 1.6.1 after
    exactly that.
    """
    defined = set(KNOWN_GLOBALS)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == '*':
                    note('{0} uses import * - undefined-name check skipped'
                         .format(name))
                    return
                defined.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                defined.add(alias.asname or alias.name.split('.')[0])
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, ast.arg):
            defined.add(node.arg)
        elif isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load):
            defined.add(node.id)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            defined.add(node.name)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            defined.update(node.names)
    reported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) \
                and node.id not in defined and node.id not in reported:
            reported.add(node.id)
            fail('{0}:{1} {2} is used but never imported or defined in this '
                 'module - it would throw in Revit on that line'.format(
                     name, node.lineno, node.id))


def check_imports(name, tree, text):
    requested = set(re.findall(r"clr\.AddReference\(\s*'([^']+)'\s*\)", text))
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.module is None:
            continue
        module = node.module
        if not (module.startswith('Autodesk') or module == 'System'
                or module.startswith('System.')):
            continue

        declared = NAMESPACE_NAMES.get(module)
        if declared is None:
            fail('{0}:{1} unknown namespace {2} - add it to NAMESPACE_NAMES '
                 'if it is real'.format(name, node.lineno, module))
            continue
        for alias in node.names:
            if alias.name not in declared:
                fail('{0}:{1} {2} is not in {3} - check which namespace the '
                     'real API puts it in'.format(name, node.lineno,
                                                  alias.name, module))

        wanted = None
        for prefix, assemblies in ASSEMBLY_FOR:
            if module == prefix or module.startswith(prefix + '.'):
                wanted = assemblies
                break
        if wanted and not requested.intersection(wanted):
            fail('{0}:{1} imports from {2} with no clr.AddReference for {3} '
                 'in this file'.format(name, node.lineno, module,
                                       ' or '.join(wanted)))


def import_modules():
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    for name in MODULES:
        try:
            __import__(name)
        except Exception as err:
            fail('{0} would not import: {1}: {2}'
                 .format(name, type(err).__name__, err))
    for name in SCRIPTS:
        path = os.path.join(HERE, name)
        handle = open(path, 'rb')
        try:
            source = handle.read().decode('utf-8')
        finally:
            handle.close()
        scope = {'__name__': '__ffr_bench__', '__file__': path}
        try:
            exec(compile(source, path, 'exec'), scope)
        except Exception as err:
            fail('{0} would not load: {1}: {2}'
                 .format(name, type(err).__name__, err))


# ---------------------------------------------------------------------------
# XAML checks
# ---------------------------------------------------------------------------

def theme_keys():
    path = os.path.join(HERE, THEME)
    if not os.path.isfile(path):
        fail('{0} is missing'.format(THEME))
        return set()
    try:
        root = ET.parse(path).getroot()
    except Exception as err:
        fail('{0} will not parse: {1}'.format(THEME, err))
        return set()
    keys = set()
    for element in root.iter():
        key = element.get(X_NS + 'Key')
        if key:
            keys.add(key)
    # the theme's own StaticResource references must resolve
    handle = open(path, 'rb')
    try:
        text = handle.read().decode('utf-8')
    finally:
        handle.close()
    for asked in set(re.findall(r'\{StaticResource\s+([A-Za-z0-9_]+)\}', text)):
        if asked not in keys:
            fail('{0} asks for {1} and does not define it'.format(THEME, asked))
    return keys


def check_layout(name, keys):
    path = os.path.join(HERE, name)
    if not os.path.isfile(path):
        fail('{0} is missing'.format(name))
        return set()
    handle = open(path, 'rb')
    try:
        text = handle.read().decode('utf-8')
    finally:
        handle.close()
    try:
        root = ET.fromstring(text.encode('utf-8'))
    except Exception as err:
        fail('{0} will not parse: {1}'.format(name, err))
        return set()

    if 'StaticResource' in text:
        fail('{0} uses StaticResource - Theme.xaml is merged after '
             'XamlReader has parsed the layout, so it must be DynamicResource'
             .format(name))

    for asked in set(re.findall(r'\{DynamicResource\s+([A-Za-z0-9_]+)\}', text)):
        if asked not in keys:
            fail('{0} asks for {1}, which {2} does not define'
                 .format(name, asked, THEME))

    names = set()
    for element in root.iter():
        given = element.get(X_NS + 'Name')
        if given:
            if given in names:
                fail('{0} declares x:Name {1} twice'.format(name, given))
            names.add(given)
        for attribute in element.keys():
            plain = attribute.split('}')[-1]
            if plain in XAML_EVENT_ATTRS:
                fail('{0} wires {1} in XAML - handlers must be attached from '
                     'Python with += '.format(name, plain))
    return names


def check_findnames(sources, declared):
    asked = set()
    for name, text in sources.items():
        for hit in re.findall(r"FindName\(\s*'([A-Za-z0-9_]+)'\s*\)", text):
            asked.add(hit)
        for hit in re.findall(r"self\.find\(\s*'([A-Za-z0-9_]+)'\s*\)", text):
            asked.add(hit)
    # side-prefixed lookups, self.find(side + 'FamilyList')
    for name, text in sources.items():
        for hit in re.findall(r"self\.find\(side \+ '([A-Za-z0-9_]+)'\)", text):
            for side in ('Src', 'Tgt'):
                asked.add(side + hit)

    # names listed in a tuple and looked up in a loop still count as used
    literals = set()
    for name, text in sources.items():
        literals |= set(re.findall(r"'([A-Za-z0-9_]+)'", text))

    missing = sorted(n for n in asked if n not in declared)
    for name in missing:
        fail('FindName("{0}") has no matching x:Name in any layout'.format(name))

    unused = sorted(n for n in declared if n not in asked
                    and n not in literals)
    if unused:
        note('x:Name declared but never looked up: ' + ', '.join(unused))


DRAWER_MODULE = 'ffr_drawer.py'


def window_layouts():
    """{file: (header names, shrink button names)} for every layout that is
    a Window - each one is a window the user can open."""
    found = {}
    for layout in LAYOUTS:
        try:
            root = ET.parse(os.path.join(HERE, layout)).getroot()
        except Exception:
            continue
        if not root.tag.endswith('Window'):
            continue
        headers = []
        shrinks = []
        for element in root.iter():
            name = element.get(X_NS + 'Name') or ''
            if name.endswith('HeaderBar'):
                headers.append(name)
            if name.endswith('ShrinkBtn'):
                shrinks.append((name, element.get('Style') or ''))
        found[layout] = (headers, shrinks)
    return found


def _strings_in(node):
    out = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            out.add(child.value)
    return out


def _is_drawer_call(node):
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    return ((isinstance(func, ast.Name) and func.id == 'Drawer') or
            (isinstance(func, ast.Attribute) and func.attr == 'Drawer'))


def check_drawers(sources):
    """Shrink to taskbar, per the RevoBIM theme reference. Fails if:

    * a window is drawn without a header bar and a shrink button styled
      BtnShrink - every window the tool opens carries one;
    * a window's layout is loaded by a function that never builds a Drawer -
      the window is built without a drawer, so its button does nothing;
    * a shrink button is drawn but its name is never handed to a Drawer - the
      button is there and dead;
    * the drawer never releases the animation on Top and Height, or the
      finishing step and the relaxing step do not call that release. A held
      animation outranks every later assignment, so the window could never be
      moved or sized again - silently.

    Added in 1.7.0. Each part proved by deliberate breakage.
    """
    layouts = window_layouts()
    if not layouts:
        fail('no window layouts found - the drawer rule has nothing to check')
        return

    wired = set()
    builders = {}
    for name, text in sources.items():
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if _is_drawer_call(node):
                wired |= _strings_in(node)
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            strings = _strings_in(node)
            has_drawer = any(_is_drawer_call(c) for c in ast.walk(node))
            for layout in layouts:
                if layout in strings:
                    builders.setdefault(layout, []).append(
                        (name, node.name, node.lineno, has_drawer))

    for layout, (headers, shrinks) in sorted(layouts.items()):
        if not headers:
            fail('{0} has no x:Name ending HeaderBar - the drawer needs the '
                 'header bar to leave showing'.format(layout))
        if not shrinks:
            fail('{0} is a window with no shrink button - every window the '
                 'tool opens needs one'.format(layout))
        for button, style in shrinks:
            if 'BtnShrink' not in style:
                fail('{0}: {1} is not styled BtnShrink, so it will not turn '
                     'into the green arrow'.format(layout, button))
            if button not in wired:
                fail('{0}: {1} is drawn but never handed to a Drawer - the '
                     'button would do nothing'.format(layout, button))
            # The button must also be the one Theme.xaml swaps on Tag.
        sites = builders.get(layout, [])
        if not sites:
            note('{0} is never loaded by name - drawer wiring not checked'
                 .format(layout))
        for module, function, line, has_drawer in sites:
            if not has_drawer:
                fail('{0}:{1} {2}() opens {3} without building a Drawer for '
                     'it'.format(module, line, function, layout))

    text = sources.get(DRAWER_MODULE)
    if text is None:
        fail('{0} is missing - every window needs it'.format(DRAWER_MODULE))
        return
    tree = ast.parse(text)
    methods = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            methods[node.name] = node

    release = methods.get('_release')
    released = set()
    if release is not None:
        for node in ast.walk(release):
            if isinstance(node, ast.Call) and \
                    isinstance(node.func, ast.Attribute) and \
                    node.func.attr == 'BeginAnimation' and \
                    len(node.args) == 2 and \
                    isinstance(node.args[1], ast.Constant) and \
                    node.args[1].value is None and \
                    isinstance(node.args[0], ast.Attribute):
                released.add(node.args[0].attr)
    for prop in ('TopProperty', 'HeightProperty'):
        if prop not in released:
            fail('{0}: _release never calls BeginAnimation(Window.{1}, None) '
                 '- a held animation would freeze the window'.format(
                     DRAWER_MODULE, prop))

    for caller in ('_finish', '_relax'):
        node = methods.get(caller)
        calls = set()
        if node is not None:
            for child in ast.walk(node):
                if isinstance(child, ast.Call) and \
                        isinstance(child.func, ast.Attribute):
                    calls.add(child.func.attr)
        if '_release' not in calls:
            fail('{0}: {1} does not call _release - the animation is never '
                 'let go there'.format(DRAWER_MODULE, caller))


def check_resource_keys_in_code(sources, keys):
    for name, text in sources.items():
        for hit in set(RESOURCE_KEY_PATTERN.findall(text)):
            if hit not in keys:
                fail('{0} asks for brush {1}, which {2} does not define'
                     .format(name, hit, THEME))


# ---------------------------------------------------------------------------

def main():
    install_stubs()

    sources = {}
    for name in source_files():
        text = check_source(name)
        if text is not None:
            sources[name] = text

    import_modules()

    keys = theme_keys()
    declared = set()
    for layout in LAYOUTS:
        declared |= check_layout(layout, keys)
    check_findnames(sources, declared)
    check_resource_keys_in_code(sources, keys)
    check_drawers(sources)

    for required in ['icon.png', 'bundle.yaml', 'CHANGELOG.md']:
        if not os.path.isfile(os.path.join(HERE, required)):
            fail('{0} is missing from the bundle'.format(required))

    output = []
    if notes:
        output.append('Notes')
        for text in notes:
            output.append('  - ' + text)
    if problems:
        output.append('{0} problem(s)'.format(len(problems)))
        for text in problems:
            output.append('  ! ' + text)
    else:
        output.append('All checks passed.')
    sys.stdout.write('\n'.join(output) + '\n')
    return 1 if problems else 0


# ---------------------------------------------------------------------------
# selftest: break the tool one way at a time and prove the rule notices
# ---------------------------------------------------------------------------

#: (what is broken, file, text to find, text to put in, message expected)
#: A rule that passes once its own break is in place is inert.
SELFTEST_BREAKS = (
    ('prompt drawn without a shrink button',
     'FamilyFindReplacePrompt.xaml',
     '<Button x:Name="PromptShrinkBtn" Grid.Column="4" Margin="0"\n'
     '                  Style="{DynamicResource BtnShrink}"/>',
     '',
     'is a window with no shrink button'),
    ('shrink button given the close style',
     'FamilyFindReplaceAdjust.xaml',
     '<Button x:Name="AdjShrinkBtn" Grid.Column="4"\n'
     '                  Style="{DynamicResource BtnShrink}"/>',
     '<Button x:Name="AdjShrinkBtn" Grid.Column="4"\n'
     '                  Style="{DynamicResource BtnClose}"/>',
     'is not styled BtnShrink'),
    ('adjust window built without a drawer',
     'ffr_ui.py',
     "        self.drawer = ffr_drawer.Drawer(self.window, header, header.Parent,\n"
     "                                        self.find('AdjShrinkBtn'))",
     "        self.drawer = None",
     'opens FamilyFindReplaceAdjust.xaml without building a Drawer'),
    ('main shrink button never handed to the drawer',
     'ffr_ui.py',
     "                                        self.find('ShrinkBtn'),",
     "                                        None,",
     'ShrinkBtn is drawn but never handed to a Drawer'),
    ('height animation never released',
     'ffr_drawer.py',
     'self.window.BeginAnimation(Window.HeightProperty, None)',
     'pass',
     'never calls BeginAnimation(Window.HeightProperty, None)'),
    ('slide finishes without releasing',
     'ffr_drawer.py',
     '        # Released in a try of its own: this is also the path taken when the\n'
     '        # slide could not start at all.\n'
     '        self._release()',
     '',
     '_finish does not call _release'),
    ('name used but never imported (the 1.6.1 Transaction bug)',
     'ffr_ui.py',
     "reading = core.Transaction(doc,",
     "reading = Transaction(doc,",
     'Transaction is used but never imported or defined'),
    ('StaticResource in a layout',
     'FamilyFindReplacePrompt.xaml',
     'Style="{DynamicResource Wordmark}"',
     'Style="{StaticResource Wordmark}"',
     'uses StaticResource'),
)


def selftest():
    import shutil
    import subprocess
    import tempfile
    here = os.path.dirname(os.path.abspath(__file__))
    problems = 0
    clean = subprocess.run([sys.executable, os.path.join(here,
                                                         'import_check.py')],
                           cwd=here, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, universal_newlines=True)
    if clean.returncode != 0:
        sys.stdout.write('  the unbroken tool fails - fix that first\n')
        return 1
    for label, target, old, new, expect in SELFTEST_BREAKS:
        work = tempfile.mkdtemp(prefix='ffr_selftest_')
        try:
            for name in os.listdir(here):
                path = os.path.join(here, name)
                if os.path.isfile(path):
                    shutil.copy(path, os.path.join(work, name))
            path = os.path.join(work, target)
            text = open(path, 'rb').read().decode('utf-8')
            count = text.count(old)
            if count != 1:
                sys.stdout.write('  {0:<52} STALE - the text to break appears '
                                 '{1} times\n'.format(label, count))
                problems += 1
                continue
            open(path, 'wb').write(text.replace(old, new).encode('utf-8'))
            run = subprocess.run(
                [sys.executable, os.path.join(work, 'import_check.py')],
                cwd=work, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                universal_newlines=True)
            if run.returncode != 0 and expect in run.stdout:
                sys.stdout.write('  {0:<52} caught\n'.format(label))
            else:
                sys.stdout.write('  {0:<52} NOT CAUGHT\n'.format(label))
                problems += 1
        finally:
            shutil.rmtree(work, ignore_errors=True)
    sys.stdout.write('{0} problem(s)\n'.format(problems))
    return 1 if problems else 0


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.stdout.write('selftest - each deliberate break must be caught:\n')
        sys.exit(selftest())
    sys.exit(main())
