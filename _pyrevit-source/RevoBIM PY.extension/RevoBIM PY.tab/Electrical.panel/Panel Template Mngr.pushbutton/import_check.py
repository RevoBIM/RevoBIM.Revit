# -*- coding: utf-8 -*-
"""RevoBIM PY - bench check for the Panel Template Mngr.

A blank white pyRevit window means an import blew up at module load, not a
broken dialog.  This loads every module in the tool against a stub Revit and
.NET API that declares each name in the namespace the real API puts it in, so a
mis-namespaced import fails here rather than in Revit.

It also rejects, across the whole tool:

  * f-strings and print statements      (IronPython 2.7 has neither)
  * bare .IntegerValue                  (removed in Revit 2026)
  * System.Uri                          (moved assemblies in Revit 2025)
  * StaticResource in a layout file     (Theme.xaml is merged in after parsing)
  * a DynamicResource key Theme.xaml does not define
  * a layout or Theme.xaml that is not well formed XML - a run of hyphens in a
    comment is the easy way to do this, since XML forbids '--' inside one
  * a name used at run time that nothing defines - the one an import test can
    never catch, because the module imports perfectly and only falls over when
    the line is reached
  * a Style="{DynamicResource K}" put on an element K's TargetType does not match
  * a FindName('x') with no matching x:Name in any layout
  * a module that reaches into System.* or Autodesk.* before importing
    pstm_clr, which references the assemblies those namespaces live in

Run it with plain CPython or IronPython:

    python import_check.py
"""

import ast
import io
import os
import re
import symtable
import sys
import types
import xml.dom.minidom

try:
    import builtins as _builtins
except ImportError:          # IronPython 2.7
    import __builtin__ as _builtins

# names the host injects or that only exist on one Python
KNOWN_GLOBALS = set(['__revit__', '__file__', '__name__', '__doc__',
                     '__title__', '__author__', '__persistentengine__',
                     'unicode', 'xrange', 'basestring', 'long', 'reduce',
                     'reload', 'execfile', 'raw_input'])

HERE = os.path.dirname(os.path.abspath(__file__))

MODULES = ['pstm_clr', 'theme', 'pstm_core', 'pstm_drawer', 'pstm_ui', 'pstm_grid',
           'pstm_model', 'pstm_ops', 'settings_window', 'pstm_window']

# These do the referencing, or are the bench itself, so the rule does not apply.
BENCH_FILES = ('import_check.py', 'batch_check.py', 'drawer_check.py')

NO_CLR_RULE = ('pstm_clr.py', 'import_check.py', 'batch_check.py',
               'drawer_check.py', 'script.py')

LAYOUT_FILES = ['PanelScheduleTemplateManager.xaml', 'PstmSettings.xaml',
                'PstmPrompt.xaml', 'PstmChoose.xaml', 'PstmRename.xaml']
THEME_FILE = 'Theme.xaml'


# ---------------------------------------------------------------------------
# Stub .NET / Revit API.  The names in each namespace are listed explicitly so
# an import from the wrong namespace fails; members on those names are
# permissive, because the check is about module load, not behaviour.
# ---------------------------------------------------------------------------

class _StubMeta(type):
    def __getattr__(cls, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return _Stub(cls.__name__ + '.' + name)


_StubBase = _StubMeta('_StubBase', (object,), {})


class _Stub(_StubBase):

    def __init__(self, name='stub', *args, **kwargs):
        self._name = name

    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return _Stub(self._name + '.' + name)

    def __call__(self, *args, **kwargs):
        return _Stub(self._name + '()')

    def __iter__(self):
        return iter([])

    def __repr__(self):
        return '<stub {0}>'.format(self._name)


def _make_class(name):
    return _StubMeta(str(name), (_Stub,), {'__module__': 'stub'})


NAMESPACES = {
    'clr': ['AddReference', 'GetClrType', 'Reference'],
    'System': ['Action', 'IntPtr', 'Array', 'Object', 'Enum', 'Convert',
               'String', 'Type', 'Double', 'Boolean', 'Int32', 'TimeSpan',
               'EventHandler'],
    'System.IO': ['FileStream', 'FileMode', 'FileAccess', 'MemoryStream',
                  'File', 'Path'],
    'System.Diagnostics': ['Process'],
    'System.Collections.Generic': ['List', 'Dictionary'],
    'System.Collections.ObjectModel': ['ObservableCollection'],
    'System.Windows': ['Window', 'Rect', 'DataTemplate', 'FrameworkElementFactory',
                       'Thickness', 'VerticalAlignment', 'HorizontalAlignment',
                       'TextTrimming', 'FrameworkElement', 'Visibility',
                       'CornerRadius', 'FontWeights', 'RoutedEventHandler',
                       'PresentationSource', 'DependencyProperty', 'Style',
                       'Setter', 'ResourceDictionary', 'MessageBox',
                       'SizeToContent', 'WindowStyle', 'WindowState',
                       'Application', 'GridLength', 'Point', 'Size', 'ResizeMode',
                       'WindowStartupLocation', 'SystemParameters'],
    'System.Windows.Input': ['Key', 'Keyboard', 'MouseButtonEventHandler',
                             'ModifierKeys'],
    'System.Windows.Threading': ['DispatcherPriority', 'DispatcherTimer'],
    'System.Windows.Markup': ['XamlReader', 'XamlWriter'],
    'System.Windows.Media': ['SolidColorBrush', 'ColorConverter', 'Brushes',
                             'Color', 'Brush', 'VisualTreeHelper'],
    'System.Windows.Media.Imaging': ['BitmapImage', 'BitmapCacheOption'],
    'System.Windows.Interop': ['WindowInteropHelper', 'HwndSource'],
    'System.Windows.Forms': ['Screen'],
    'System.Windows.Controls': ['Border', 'TextBlock', 'TextBox', 'ComboBox',
                                'StackPanel', 'Orientation', 'ListBox',
                                'CheckBox', 'Button', 'ScrollViewer',
                                'ScrollBarVisibility', 'DataGridTemplateColumn',
                                'DataGridLength', 'DataGridLengthUnitType',
                                'SelectionChangedEventHandler', 'Image', 'Grid',
                                'DataGrid', 'TabControl', 'TabItem',
                                'RadioButton', 'WrapPanel', 'ComboBoxItem',
                                'ListBoxItem', 'Label', 'ProgressBar',
                                'GridSplitter'],
    'System.Windows.Controls.Primitives': ['Popup', 'ToggleButton',
                                           'PlacementMode', 'Selector',
                                           'RepeatButton', 'Thumb'],
    'System.Windows.Data': ['Binding', 'IValueConverter', 'BindingMode',
                            'CollectionViewSource'],
    'Autodesk': [],
    'Autodesk.Revit': [],
    'Autodesk.Revit.DB': ['FilteredElementCollector', 'BuiltInCategory',
                          'BuiltInParameter', 'StorageType', 'ElementId',
                          'Element', 'Transaction', 'TransactionStatus', 'XYZ',
                          'ElementTransformUtils', 'IFailuresPreprocessor',
                          'FailureProcessingResult', 'FailureSeverity',
                          'ElementType', 'FamilySymbol', 'View', 'Document',
                          'ViewDuplicateOption', 'InstanceBinding',
                          'TypeBinding', 'TransactionGroup',
                          'ScheduleSheetInstance', 'WorksharingUtils',
                          'CheckoutStatus', 'WorksetTable', 'Workset'],
    'Autodesk.Revit.DB.Electrical': ['PanelScheduleView', 'PanelScheduleTemplate',
                                     'PanelScheduleType', 'PanelConfiguration',
                                     'PanelScheduleData', 'ElectricalSystem',
                                     'PanelSchedulePhaseLoadType'],
    'Autodesk.Revit.UI': ['IExternalEventHandler', 'ExternalEvent', 'TaskDialog',
                          'UIApplication', 'UIDocument', 'IExternalCommand'],
    'Autodesk.Revit.UI.Selection': ['ObjectType', 'ISelectionFilter'],
}


def install_stubs():
    for namespace, names in NAMESPACES.items():
        module = types.ModuleType(namespace)
        for name in names:
            setattr(module, name, _make_class(name))
        module.__all__ = list(names)
        sys.modules[namespace] = module

    # parent packages have to resolve their children as attributes
    for namespace in NAMESPACES:
        if '.' not in namespace:
            continue
        parent_name, child = namespace.rsplit('.', 1)
        parent = sys.modules.get(parent_name)
        if parent is not None:
            setattr(parent, child, sys.modules[namespace])

    # a couple of Enum members the modules actually call
    system = sys.modules['System']

    class _Enum(object):
        @staticmethod
        def GetNames(_type):
            return []
    system.Enum = _Enum
    system.Array = _StubArray()


class _StubArray(object):
    def __getitem__(self, item):
        return lambda seq: list(seq)


# ---------------------------------------------------------------------------
# Source rules
# ---------------------------------------------------------------------------

class SourceCheck(object):

    def __init__(self):
        self.problems = []

    def check_file(self, path):
        name = os.path.basename(path)
        text = io.open(path, encoding='utf-8').read()
        try:
            tree = ast.parse(text, filename=name)
        except SyntaxError as ex:
            self.problems.append('{0}: will not parse - {1}'.format(name, ex))
            return

        for node in ast.walk(tree):
            if node.__class__.__name__ == 'JoinedStr':
                self.problems.append(
                    '{0} line {1}: f-string - IronPython 2.7 has none'.format(
                        name, getattr(node, 'lineno', '?')))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                    and node.func.id == 'print':
                self.problems.append(
                    '{0} line {1}: print - results belong in a themed window'.format(
                        name, node.lineno))
            if isinstance(node, ast.Attribute) and node.attr == 'IntegerValue':
                if name not in ('pstm_core.py', 'import_check.py', 'batch_check.py'):
                    self.problems.append(
                        '{0} line {1}: bare .IntegerValue - removed in Revit '
                        '2026, go through eid_value'.format(name, node.lineno))
            if isinstance(node, ast.Attribute) and node.attr == 'Uri':
                self.problems.append(
                    '{0} line {1}: System.Uri moved assemblies in Revit 2025 - '
                    'load images from bytes'.format(name, node.lineno))

        self._check_clr_first(name, tree)
        self._check_names(name, text, tree)

        if re.search(r'from\s+System\s+import\s+[^\n]*\bUri\b', text):
            self.problems.append(
                '{0}: imports System.Uri - it throws at module load on Revit '
                '2025 and later'.format(name))

        return text


    def _check_names(self, name, text, tree):
        """Every global a function reaches for has to exist in the module.

        This is the gap an import test cannot see: a module whose top level is
        fine imports perfectly and then dies at "global name 'x' is not defined"
        the moment that line runs.  It has happened here by editing a block of
        source and taking a neighbouring function out with it.
        """
        defined = set(dir(_builtins)) | KNOWN_GLOBALS

        def bind(node):
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                defined.add(node.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    for sub in ast.walk(target):
                        if isinstance(sub, ast.Name):
                            defined.add(sub.id)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    defined.add((alias.asname or alias.name).split('.')[0])
            elif isinstance(node, ast.For):
                for sub in ast.walk(node.target):
                    if isinstance(sub, ast.Name):
                        defined.add(sub.id)

        # module level, including inside try/except and if blocks, which is how
        # the optional Revit imports are written
        stack = list(tree.body)
        while stack:
            node = stack.pop()
            bind(node)
            if isinstance(node, (ast.Try, ast.If, ast.For, ast.While)):
                stack.extend(getattr(node, 'body', []))
                stack.extend(getattr(node, 'orelse', []))
                stack.extend(getattr(node, 'finalbody', []))
                for handler in getattr(node, 'handlers', []):
                    stack.extend(handler.body)

        # A comprehension binds its own target.  From CPython 3.12 (PEP 709)
        # comprehensions are inlined into the enclosing scope, so a module level
        # [k for k in ...] puts k in the MODULE's symbol table as a referenced
        # global - which this rule then reports as undefined.  The tool runs on
        # IronPython and is unaffected; the bench is what has to cope.
        for node in ast.walk(tree):
            if isinstance(node, ast.comprehension):
                for sub in ast.walk(node.target):
                    if isinstance(sub, ast.Name):
                        defined.add(sub.id)

        missing = set()

        def scan(table):
            for symbol in table.get_symbols():
                if symbol.is_global() and symbol.is_referenced():
                    if symbol.get_name() not in defined:
                        missing.add(symbol.get_name())
            for child in table.get_children():
                scan(child)

        try:
            scan(symtable.symtable(text, name, 'exec'))
        except Exception:
            return

        for missed in sorted(missing):
            self.problems.append(
                '{0}: uses "{1}" but nothing in the module defines it - this '
                'imports fine and dies when the line runs'.format(name, missed))

    def _check_clr_first(self, name, tree):
        """A .NET namespace is only visible once its assembly is referenced.

        pyRevit does not preload WPF into every engine, so a module whose first
        import is `from System.Windows import ...` throws ImportError at module
        load - and a module that will not load is the blank white pyRevit
        window with no traceback in it.  Every module has to import pstm_clr
        ahead of its first System.* or Autodesk.* import.
        """
        if name in NO_CLR_RULE:
            return

        clr_line = None
        first_dotnet = None
        first_what = ''
        for node in tree.body:          # module level only
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == 'pstm_clr' and clr_line is None:
                        clr_line = node.lineno
                    root = alias.name.split('.')[0]
                    if root in ('System', 'Autodesk') and first_dotnet is None:
                        first_dotnet = node.lineno
                        first_what = alias.name
            elif isinstance(node, ast.ImportFrom):
                root = (node.module or '').split('.')[0]
                if root in ('System', 'Autodesk') and first_dotnet is None:
                    first_dotnet = node.lineno
                    first_what = node.module

        if first_dotnet is None:
            return
        if clr_line is None:
            self.problems.append(
                '{0} line {1}: imports {2} but never imports pstm_clr - the '
                'assembly is not referenced, so this throws at module '
                'load'.format(name, first_dotnet, first_what))
        elif clr_line > first_dotnet:
            self.problems.append(
                '{0}: imports {1} on line {2} but only imports pstm_clr on '
                'line {3} - the reference has to come first'.format(
                    name, first_what, first_dotnet, clr_line))


# ---------------------------------------------------------------------------
# XAML rules
# ---------------------------------------------------------------------------

KEY_RE = re.compile(r'x:Key\s*=\s*"([^"]+)"')
NAME_RE = re.compile(r'x:Name\s*=\s*"([^"]+)"')
DYN_RE = re.compile(r'\{DynamicResource\s+([^\}\s]+)\s*\}')
STATIC_RE = re.compile(r'\{StaticResource\s+([^\}\s]+)\s*\}')
FINDNAME_RE = re.compile(r"FindName\(\s*'([^']+)'\s*\)")


def check_drawers(problems):
    """Every window the tool opens can be shrunk to the taskbar.

    The project rule is "do this for all windows in this tool", and the ways to
    miss one are all silent: a layout with no button, a window class that loads
    a layout but never makes a drawer, a button drawn but never wired, a drag
    handler that does not know about the parked bar, and an animation that is
    never released - which leaves a window that never resizes again.
    """
    # 1. every layout carries the button, styled
    for filename in LAYOUT_FILES:
        try:
            text = io.open(os.path.join(HERE, filename), encoding='utf-8').read()
        except Exception:
            continue
        if 'x:Name="ShrinkButton"' not in text:
            problems.append('{0}: no ShrinkButton in the header - every window '
                            'in this tool shrinks to the taskbar'.format(filename))
        elif 'Style="{DynamicResource ShrinkButton}"' not in text:
            problems.append('{0}: ShrinkButton is not using the ShrinkButton '
                            'style, so it never turns into the green '
                            'arrow'.format(filename))

    # 2. every class that loads a layout makes a drawer for it;
    # 3. every wire_drag hands over the drawer
    for filename in sorted(os.listdir(HERE)):
        if not filename.endswith('.py') or filename in BENCH_FILES:
            continue
        try:
            text = io.open(os.path.join(HERE, filename), encoding='utf-8').read()
            tree = ast.parse(text, filename=filename)
        except Exception:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                calls = [n for n in ast.walk(node) if isinstance(n, ast.Call)]
                names = set()
                for call in calls:
                    func = call.func
                    if isinstance(func, ast.Attribute):
                        names.add(func.attr)
                    elif isinstance(func, ast.Name):
                        names.add(func.id)
                if 'load_window' in names and 'Drawer' not in names:
                    problems.append(
                        '{0}: class {1} opens a window but never makes a '
                        'Drawer for it, so it cannot be shrunk'.format(
                            filename, node.name))
            if isinstance(node, ast.Call):
                func = node.func
                name = func.attr if isinstance(func, ast.Attribute) else \
                    getattr(func, 'id', '')
                if name == 'wire_drag' and len(node.args) < 3:
                    problems.append(
                        '{0} line {1}: wire_drag without the drawer - a double '
                        'click on the parked bar would start a drag instead of '
                        'bringing the window back'.format(filename, node.lineno))

    # 4. the drawer finds and wires the button, and releases the animation
    try:
        drawer = io.open(os.path.join(HERE, 'pstm_drawer.py'),
                         encoding='utf-8').read()
    except Exception:
        problems.append('pstm_drawer.py is missing')
        return
    if "FindName('ShrinkButton')" not in drawer:
        problems.append('pstm_drawer.py never finds the ShrinkButton')
    if 'self.button.Click +=' not in drawer:
        problems.append('pstm_drawer.py never wires the ShrinkButton - drawn but '
                        'dead')
    for prop in ('TopProperty', 'HeightProperty'):
        if 'BeginAnimation(Window.{0}, None)'.format(prop) not in drawer:
            problems.append(
                'pstm_drawer.py never releases {0} - a held animation value '
                'outranks every later assignment and the window never resizes '
                'again'.format(prop))

    # 5. the main window: the shrink button stays live while a job runs, and
    # the header and keys defer to the drawer while it is parked
    try:
        window = io.open(os.path.join(HERE, 'pstm_window.py'),
                         encoding='utf-8').read()
    except Exception:
        return
    start = window.find('BUSY_DEAF = (')
    if start < 0:
        problems.append('pstm_window.py: BUSY_DEAF is gone - the busy guard no '
                        'longer says which header controls go deaf')
    elif 'ShrinkButton' in window[start:window.find(')', start)]:
        problems.append('pstm_window.py: ShrinkButton is in BUSY_DEAF - it is '
                        'the one control that must stay live during a long job')
    for method, needle in (('_header_click', 'on_header_down'),
                           ('_on_key', 'drawer.parked'),
                           ('_toggle_full', 'drawer.parked')):
        at = window.find('def {0}('.format(method))
        body = window[at:window.find('\n    def ', at + 10)] if at >= 0 else ''
        if needle not in body:
            problems.append('pstm_window.py: {0} does not defer to the drawer '
                            '({1})'.format(method, needle))


def check_tool_name(problems):
    """The tool has one name, and every place that shows it must agree.

    A rename touches the folder, the ribbon title, both window headers and the
    error dialog, and missing one leaves the old name showing in exactly the
    place somebody screenshots.  So the name is read out of pstm_core and every
    other place is checked against it.
    """
    try:
        import pstm_core
        name = pstm_core.TOOL_NAME
    except Exception as ex:
        problems.append('cannot read TOOL_NAME from pstm_core: {0}'.format(ex))
        return

    folder = os.path.basename(HERE)
    if folder != name + '.pushbutton':
        problems.append(
            'the folder is "{0}" but TOOL_NAME is "{1}" - pyRevit names the '
            'ribbon button after the folder'.format(folder, name))

    # the ribbon title, which may be split over two lines
    try:
        text = io.open(os.path.join(HERE, 'bundle.yaml'), encoding='utf-8').read()
    except Exception:
        text = ''
    for line in text.splitlines():
        if line.startswith('title:'):
            flat = line.split(':', 1)[1].replace('\\n', ' ')
            flat = ' '.join(flat.split())
            if flat != name:
                problems.append(
                    'bundle.yaml title is "{0}" but TOOL_NAME is "{1}"'.format(
                        flat, name))
            break

    main = os.path.join(HERE, 'PanelScheduleTemplateManager.xaml')
    try:
        layout = io.open(main, encoding='utf-8').read()
    except Exception:
        layout = ''
    if layout and 'Text="{0}"'.format(name) not in layout:
        problems.append('the window header does not show "{0}"'.format(name))


def check_xaml_parses(problems):
    """Every .xaml has to be well formed XML before XamlReader ever sees it.

    XamlReader.Load throwing is the other way to get the blank white pyRevit
    window, and its message ("An XML comment cannot contain '--'") arrives at
    run time with the tool already dead.  minidom catches the same thing here.
    """
    for name in sorted(os.listdir(HERE)):
        if not name.endswith('.xaml'):
            continue
        try:
            xml.dom.minidom.parse(os.path.join(HERE, name))
        except Exception as ex:
            problems.append('{0}: will not parse as XML - {1}'.format(name, ex))


def check_style_targets(problems):
    """A style whose TargetType is not the element it is put on throws.

    WPF raises this when the style is applied, not when the layout is parsed,
    so it surfaces as a dead window rather than as a parse error.
    """
    theme_text = io.open(os.path.join(HERE, THEME_FILE), encoding='utf-8').read()

    targets = {}
    for block in re.findall(r'<Style\b[^>]*>', theme_text):
        key = re.search(r'x:Key\s*=\s*"([^"]+)"', block)
        target = re.search(r'TargetType\s*=\s*"(?:\{x:Type\s+)?([\w\.]+)', block)
        if key and target:
            targets[key.group(1)] = target.group(1).split('.')[-1]

    for filename in LAYOUT_FILES:
        path = os.path.join(HERE, filename)
        if not os.path.isfile(path):
            continue
        try:
            document = xml.dom.minidom.parse(path)
        except Exception:
            continue                      # the parse rule already reported it
        for node in document.getElementsByTagName('*'):
            value = node.getAttribute('Style')
            if not value:
                continue
            match = re.match(r'\{DynamicResource\s+([^\}\s]+)\s*\}', value)
            if not match:
                continue
            key = match.group(1)
            want = targets.get(key)
            if want is None:
                continue                  # the unknown-key rule already has it
            tag = node.tagName.split(':')[-1]
            if tag != want:
                problems.append(
                    '{0}: Style "{1}" targets {2} but is on a {3}'.format(
                        filename, key, want, tag))


def check_xaml(problems):
    theme_path = os.path.join(HERE, THEME_FILE)
    theme_text = io.open(theme_path, encoding='utf-8').read()
    theme_keys = set(KEY_RE.findall(theme_text))

    # every palette key the theme module writes must have a brush in Theme.xaml
    sys.path.insert(0, HERE)
    import theme as theme_mod
    for key in theme_mod.BRUSH_KEYS:
        if key not in theme_keys:
            problems.append(
                'Theme.xaml does not declare a brush for palette key '
                '"{0}"'.format(key))

    names = set()
    for filename in LAYOUT_FILES:
        path = os.path.join(HERE, filename)
        if not os.path.isfile(path):
            problems.append('{0} is missing'.format(filename))
            continue
        text = io.open(path, encoding='utf-8').read()
        names.update(NAME_RE.findall(text))

        for match in STATIC_RE.findall(text):
            problems.append(
                '{0}: StaticResource "{1}" - Theme.xaml is merged in after the '
                'layout is parsed, so a layout may only use '
                'DynamicResource'.format(filename, match))

        for key in DYN_RE.findall(text):
            if key not in theme_keys:
                problems.append(
                    '{0}: DynamicResource "{1}" is not defined in '
                    'Theme.xaml'.format(filename, key))

    for filename in os.listdir(HERE):
        if not filename.endswith('.py') or filename in BENCH_FILES:
            continue
        text = io.open(os.path.join(HERE, filename), encoding='utf-8').read()
        for wanted in set(FINDNAME_RE.findall(text)):
            if wanted not in names:
                problems.append(
                    '{0}: FindName("{1}") has no matching x:Name in any '
                    'layout'.format(filename, wanted))

    # resource keys asked for from code
    setres = re.compile(r"SetResourceReference\([^,]+,\s*'([^']+)'\s*\)")
    for filename in os.listdir(HERE):
        if not filename.endswith('.py') or filename in BENCH_FILES:
            continue
        text = io.open(os.path.join(HERE, filename), encoding='utf-8').read()
        for key in set(setres.findall(text)):
            if key not in theme_keys:
                problems.append(
                    '{0}: SetResourceReference to "{1}", which Theme.xaml does '
                    'not define'.format(filename, key))


# ---------------------------------------------------------------------------

def main():
    problems = []
    install_stubs()
    sys.path.insert(0, HERE)
    checker = SourceCheck()
    for filename in sorted(os.listdir(HERE)):
        if filename.endswith('.py'):
            checker.check_file(os.path.join(HERE, filename))
    problems.extend(checker.problems)

    check_tool_name(problems)
    check_drawers(problems)
    check_xaml_parses(problems)
    check_style_targets(problems)
    check_xaml(problems)

    for name in MODULES:
        try:
            __import__(name)
        except Exception as ex:
            problems.append('{0}: will not import - {1}: {2}'.format(
                name, ex.__class__.__name__, ex))

    out = sys.stdout
    if problems:
        out.write('FAILED - {0} problem(s)\n'.format(len(problems)))
        for problem in problems:
            out.write('  * {0}\n'.format(problem))
        return 1
    out.write('OK - every module loads and every layout key resolves.\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
