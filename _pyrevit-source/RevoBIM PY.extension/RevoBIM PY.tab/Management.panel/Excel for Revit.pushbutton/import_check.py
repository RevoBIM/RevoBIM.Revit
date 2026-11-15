# -*- coding: utf-8 -*-
"""Bench check for Excel for Revit. Plain CPython, no Revit.

    python import_check.py             run every rule
    python import_check.py --selftest  break each rule and confirm it is caught

The rule that earns its keep: **the module is imported against a stub Revit and
.NET API**, so a name that does not exist fails here instead of showing up in
Revit as a window where nothing works. A tool this size has too many handlers
to click through by hand.
"""

import importlib
import importlib.machinery
import os
import re
import sys
import types
import xml.dom.minidom

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, 'efr_core.py')
LOADER = os.path.join(HERE, 'script.py')
LAYOUT = os.path.join(HERE, 'ExcelForRevit.xaml')


# ------------------------------------------------------------ the stub API --

class Any(object):
    """Answers to anything, so a stub never has to be complete."""

    def __init__(self, *a, **k):
        pass

    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return Any()

    def __call__(self, *a, **k):
        return Any()

    def __setattr__(self, name, value):
        pass

    def __iadd__(self, other):
        return self

    def __getitem__(self, key):
        return Any()

    def __setitem__(self, key, value):
        pass

    def __iter__(self):
        return iter([])

    def __eq__(self, other):
        return False

    def __ne__(self, other):
        return True

    def __hash__(self):
        return id(self)

    def __len__(self):
        return 0

    def __nonzero__(self):
        return True

    __bool__ = __nonzero__


def module(name, names=()):
    m = types.ModuleType(name)
    for n in names:
        setattr(m, n, Any())
    m.__getattr__ = lambda n: Any()
    sys.modules[name] = m
    return m


class StubFinder(object):
    """Hands back an Any-filled module for any namespace the tool asks for."""

    ROOTS = ('clr', 'System', 'Autodesk', 'pyrevit', 'Microsoft')

    def find_module(self, name, path=None):
        root = name.split('.')[0]
        return self if root in self.ROOTS else None

    def load_module(self, name):
        if name in sys.modules:
            return sys.modules[name]
        m = types.ModuleType(name)
        m.__path__ = []
        m.__getattr__ = lambda n: Any()
        sys.modules[name] = m
        return m

    # Python 3 import protocol
    def find_spec(self, name, path=None, target=None):
        root = name.split('.')[0]
        if root not in self.ROOTS:
            return None
        return importlib.machinery.ModuleSpec(name, self)

    def create_module(self, spec):
        m = types.ModuleType(spec.name)
        m.__path__ = []
        return m

    def exec_module(self, mod):
        mod.__getattr__ = lambda n: Any()


def install_stubs():
    sys.meta_path.insert(0, StubFinder())
    clr = module('clr', ('AddReference', 'GetClrType'))
    clr.AddReference = lambda *a, **k: None
    clr.GetClrType = lambda *a, **k: Any()

    # the few names the module actually uses at import time, as real values
    system = module('System')
    system.Int64 = int
    system.Action = lambda f=None: f
    system.TimeSpan = Any()

    module('System.Collections.Generic')
    module('System.Windows')
    module('System.Windows.Controls')
    module('System.Windows.Media')
    module('System.Windows.Input')
    module('System.Windows.Data')
    module('System.Windows.Documents')
    module('System.Windows.Threading')
    module('System.Windows.Interop')
    module('System.Data')
    module('System.ComponentModel')
    module('System.IO')
    module('System.Diagnostics')
    module('System.Windows.Forms')
    module('Autodesk')
    module('Autodesk.Revit')
    module('Autodesk.Revit.DB')
    module('Autodesk.Revit.UI')
    module('pyrevit')


# ------------------------------------------------------------------ rules --

# Where each .NET name really lives. A stub that fabricates any namespace on
# demand will happily import System.Windows.Nowhere, which is the one mistake
# this check exists to catch — so the namespaces are pinned instead.
KNOWN = {
    'System': ('Action', 'TimeSpan', 'Int64', 'Uri'),
    'System.ComponentModel': ('ListSortDirection',),
    'System.Data': ('DataTable', 'DataView'),
    'System.IO': ('File', 'FileAccess', 'FileMode', 'FileStream', 'MemoryStream',
                  'StringReader'),
    'System.Collections.Generic': ('List',),
    'System.Diagnostics': ('Process',),
    'System.Windows': (
        'Clipboard', 'CornerRadius', 'FontWeights', 'GridLength', 'GridUnitType',
        'HorizontalAlignment', 'Point', 'PresentationSource', 'ResizeMode',
        'Setter', 'SizeToContent', 'Style', 'SystemParameters', 'TextTrimming',
        'TextWrapping', 'Thickness', 'VerticalAlignment', 'Visibility', 'Window',
        'WindowStartupLocation', 'WindowStyle', 'MessageBox', 'Application',
        'Duration'),
    'System.Windows.Controls': (
        'Border', 'Button', 'Canvas', 'CheckBox', 'ColumnDefinition',
        'ContextMenu', 'DataGrid', 'DataGridCell', 'DataGridCellInfo',
        'DataGridEditAction', 'DataGridLength', 'DataGridLengthUnitType',
        'DataGridRow', 'DataGridTextColumn', 'Grid', 'Image', 'ListBox',
        'MenuItem', 'Orientation', 'RadioButton', 'RowDefinition',
        'ScrollBarVisibility', 'ScrollViewer', 'Separator', 'StackPanel',
        'TextBlock', 'TextBox', 'WrapPanel', 'ScrollChangedEventHandler',
        'ComboBox', 'Label', 'ItemsControl', 'ListBoxItem'),
    'System.Windows.Controls.Primitives': ('DataGridColumnHeader', 'Thumb',
                                           'ScrollBar', 'Track',
                                           'PlacementMode'),
    'System.Windows.Data': ('Binding',),
    'System.Windows.Documents': ('Run', 'Paragraph', 'FlowDocument'),
    'System.Windows.Input': ('Cursors', 'Key', 'Keyboard', 'ModifierKeys',
                             'Mouse', 'MouseButtonState'),
    'System.Windows.Interop': ('WindowInteropHelper',),
    'System.Windows.Markup': ('XamlReader',),
    'System.Windows.Media': ('ColorConverter', 'SolidColorBrush',
                             'VisualTreeHelper', 'FontFamily', 'Brushes'),
    'System.Windows.Media.Imaging': ('BitmapCacheOption', 'BitmapImage'),
    'System.Windows.Media.Animation': ('CubicEase', 'DoubleAnimation',
                                       'EasingMode', 'FillBehavior'),
    'System.Windows.Threading': ('DispatcherPriority', 'DispatcherTimer',
                                 'Dispatcher', 'DispatcherFrame'),
    'System.Windows.Forms.Integration': ('ElementHost',),
    'System.Windows.Forms': ('Screen', 'SaveFileDialog', 'OpenFileDialog',
                             'DialogResult'),
    'System.Threading': ('Thread',),
    'System.Text': ('Encoding',),
    'System.IO.Compression': ('ZipArchive', 'ZipArchiveMode', 'CompressionLevel'),
    'Autodesk.Revit': ('DB', 'UI'),
    'Autodesk.Windows': (),
}


def rule_known_namespaces(problems):
    """Every .NET name must be imported from the namespace it actually lives in.

    This is the rule that stops a mis-namespaced import reaching Revit, where
    it shows up as a window that never opens with no traceback to read.
    """
    src = open(SCRIPT, encoding='utf-8').read()
    for ns, names in re.findall(r'^\s*from ([\w.]+) import ([\w, ]+)',
                                src, re.M):
        if ns.split('.')[0] not in ('System', 'Autodesk', 'Microsoft'):
            continue
        if ns not in KNOWN:
            problems.append('imports from {0}, which is not a namespace this '
                            'check knows — confirm it is real and add it to '
                            'KNOWN'.format(ns))
            continue
        for name in names.split(','):
            name = name.strip().split(' as ')[0]
            if not name:
                continue
            if KNOWN[ns] and name not in KNOWN[ns]:
                problems.append('{0} is imported from {1}, which is not where '
                                'it lives'.format(name, ns))



def rule_xaml_parses(problems):
    """Every .xaml must be well-formed XML. A run of hyphens in a comment, an
    unclosed tag or a bare & all show up as a window that never opens."""
    for name in os.listdir(HERE):
        if not name.lower().endswith('.xaml'):
            continue
        try:
            xml.dom.minidom.parse(os.path.join(HERE, name))
        except Exception as err:
            problems.append('{0} is not valid XML: {1}'.format(name, err))


def rule_module_imports(problems):
    """The whole module must load against the stub API."""
    os.environ['REVOBIM_BENCH'] = '1'
    install_stubs()
    sys.path.insert(0, HERE)
    try:
        for name in ('efr_core', 'script'):
            if name in sys.modules:
                del sys.modules[name]
        importlib.import_module('efr_core')
    except Exception:
        import traceback
        problems.append('script.py does not import:\n' + traceback.format_exc())


def rule_loader_is_thin(problems):
    """script.py must stay small enough that it cannot fail to load.

    It is the only thing left standing to report an import failure in the rest
    of the tool, which is what turns a blank white window into a message.
    """
    text = open(LOADER, encoding='utf-8').read()
    lines = len(text.split('\n'))
    if lines > 140:
        problems.append('script.py is {0} lines — it is the loader and has to '
                        'stay trivial'.format(lines))
    if 'import efr_core' not in text:
        problems.append('script.py does not load efr_core')
    # only what runs on the way in matters; the error reporter may reach for
    # a MessageBox inside its own try/except, because by then nothing is left
    # to lose
    import ast as _ast
    for node in _ast.parse(text).body:
        if isinstance(node, (_ast.Import, _ast.ImportFrom)):
            name = getattr(node, 'module', None) or ''
            for alias in node.names:
                name = name or alias.name
            if name.split('.')[0] in ('System', 'Autodesk', 'clr'):
                problems.append('script.py imports {0} at module level — '
                                'anything that can fail belongs in '
                                'efr_core'.format(name))


def rule_non_ascii_literals(problems):
    """Any non-ASCII string handed to .NET must be a u'' literal.

    IronPython 2.7 str literals are bytes; an em dash in one is decoded as
    ASCII when it reaches a .NET string property and throws there.
    """
    import ast as _ast
    src = open(SCRIPT, encoding='utf-8').read()
    tree = _ast.parse(src)
    lines = src.split('\n')
    docs = set()
    for node in _ast.walk(tree):
        if isinstance(node, (_ast.Module, _ast.FunctionDef, _ast.ClassDef)):
            body = getattr(node, 'body', None)
            if (body and isinstance(body[0], _ast.Expr)
                    and isinstance(body[0].value, _ast.Constant)
                    and isinstance(body[0].value.value, str)):
                docs.add((body[0].value.lineno, body[0].value.col_offset))
    for node in _ast.walk(tree):
        if not (isinstance(node, _ast.Constant) and isinstance(node.value, str)):
            continue
        if not any(ord(c) > 127 for c in node.value):
            continue
        if (node.lineno, node.col_offset) in docs:
            continue
        head = lines[node.lineno - 1][node.col_offset:node.col_offset + 2]
        if not head.lower().startswith('u'):
            problems.append('non-ASCII text at line {0} is not a u\'\' literal '
                            '— IronPython 2.7 will fail on it'.format(node.lineno))


def rule_no_banned_forms(problems):
    """Things that break IronPython 2.7 or Revit 2026."""
    src = open(SCRIPT, encoding='utf-8').read()
    for pattern, why in (
            (r'[^A-Za-z](f["\'])', 'f-string'),
            (r'(?<![.\w])print\s*\(', 'print()'),
            (r'from System import Uri', 'System.Uri (moved in 2025)'),
            (r'unicode\(', 'unicode()')):
        for m in re.finditer(pattern, src):
            line = src[:m.start()].count('\n') + 1
            problems.append('{0} at line {1} — {2}'.format(why, line, why))
    for m in re.finditer(r'\.IntegerValue', src):
        line = src[:m.start()].count('\n') + 1
        window = src[max(0, m.start() - 400):m.start()]
        if 'def eid_value' in window or 'def field_id_key' in window:
            continue
        problems.append('bare .IntegerValue at line {0}'.format(line))


def rule_names_resolve(problems):
    """Every x:Name the code asks for must exist in the layout, and every
    handler named in the code must exist on the class."""
    import ast
    src = open(SCRIPT, encoding='utf-8').read()
    layout = open(LAYOUT, encoding='utf-8').read()
    named = set(re.findall(r'x:Name="([A-Za-z_][\w]*)"', layout))
    for m in re.finditer(r"f\('([A-Za-z_][\w]*)'\)", src):
        if m.group(1) not in named:
            problems.append('FindName("{0}") has no x:Name in the layout'.format(
                m.group(1)))
    for m in re.finditer(r"\('([A-Za-z_][\w]*)',\s*self\.(on_\w+)\)", src):
        if m.group(1) not in named:
            problems.append('wired "{0}" but the layout has no such element'.format(
                m.group(1)))

    tree = ast.parse(src)
    cls = [n for n in tree.body
           if isinstance(n, ast.ClassDef) and n.name == 'ExcelForRevitWindow'][0]
    methods = set(n.name for n in cls.body if isinstance(n, ast.FunctionDef))
    seen = {}
    for n in cls.body:
        if isinstance(n, ast.FunctionDef):
            seen[n.name] = seen.get(n.name, 0) + 1
    for name, count in seen.items():
        if count > 1:
            problems.append('{0}() is defined {1} times — the later one wins '
                            'and the earlier is dead'.format(name, count))
    for m in re.finditer(r'self\.(on_\w+)', src):
        if m.group(1) not in methods:
            problems.append('self.{0} is referenced but not defined'.format(
                m.group(1)))


def rule_resources_exist(problems):
    """No DynamicResource key the layout uses may be undefined, and BasedOn
    must stay StaticResource — a DynamicResource there refuses to parse."""
    layout = open(LAYOUT, encoding='utf-8').read()
    defined = set(re.findall(r'x:Key="([A-Za-z_][\w]*)"', layout))
    used = set(re.findall(r'\{(?:Dynamic|Static)Resource ([A-Za-z_][\w]*)\}', layout))
    src = open(SCRIPT, encoding='utf-8').read()
    used |= set(re.findall(r"Resources\['([A-Za-z_][\w]*)'\]", src))
    for key in sorted(used - defined):
        problems.append('resource "{0}" is used but never defined'.format(key))
    for m in re.finditer(r'BasedOn="\{DynamicResource', layout):
        line = layout[:m.start()].count('\n') + 1
        problems.append('BasedOn uses DynamicResource at line {0} — BasedOn is '
                        'a plain CLR property and the file will not parse'.format(line))


def rule_palettes_match(problems):
    """Both themes must define the same keys, or a switch leaves a hole."""
    src = open(SCRIPT, encoding='utf-8').read()
    dark = re.search(r'DARK_THEME = \{(.*?)\n\}', src, re.S)
    light = re.search(r'LIGHT_THEME = \{(.*?)\n\}', src, re.S)
    if not dark or not light:
        problems.append('one of the palettes is missing')
        return
    dk = set(re.findall(r"'(C_[A-Z_]+)'", dark.group(1)))
    lt = set(re.findall(r"'(C_[A-Z_]+)'", light.group(1)))
    for key in sorted(dk ^ lt):
        problems.append('palette key {0} is in one theme but not the other'.format(key))
    for key in sorted(set(re.findall(r'\b(C_[A-Z_]+)\b', src)) - dk):
        problems.append('{0} is used but is in neither palette'.format(key))


def rule_liveness_proof_after_show(problems):
    """The modeless health check may only count proof from after show().

    A torn-down engine leaves the window on screen with every handler dead,
    so the tool records "a modeless window was opened" and clears it from the
    first handler that runs.  Up to 1.18.0 that clearing ran from the
    constructor, before the window existed — so every launch was recorded as
    dead, the tool kept offering modal, and accepting it blocked Revit for
    good.  Nothing raised; the window simply opened modal from then on.
    """
    methods = _method_sources('ExcelForRevitWindow')
    prove = methods.get('prove_alive', '')
    if 'not self._shown' not in prove:
        problems.append('liveness: prove_alive() does not wait for show() — '
                        'the constructor will use up the proof and every '
                        'launch will look like a dead window')
    src = open(SCRIPT, encoding='utf-8').read()
    if src.count('self._shown = True') != 1:
        problems.append('liveness: self._shown is set True {0} times; it must '
                        'be set once, at the end of show()'.format(
                            src.count('self._shown = True')))
    show = methods.get('show', '')
    at_show = show.find('self.window.Show()')
    at_flag = show.find('self._shown = True')
    if at_show < 0 or at_flag < 0 or at_flag < at_show:
        problems.append('liveness: show() must mark itself shown only after '
                        'window.Show() returns')
    if 'migrate_window_settings()\n        check_modeless_health()' not in src:
        problems.append('liveness: the one-time reset of the old modal '
                        'setting no longer runs before the health check')


# control types the tool builds in code, and the implicit style each one needs
# so it is not left in Windows' own light chrome inside a dark dialog
CODE_BUILT_CONTROLS = (
    ('ListBox()', ('ListBox', 'ListBoxItem')),
    ('CheckBox()', ('CheckBox',)),
    ('RadioButton()', ('RadioButton',)),
    ('TextBox()', ('TextBox',)),
    ('ScrollViewer()', ('ScrollBar',)),
)


def rule_dialogs_themed(problems):
    """Every window built in code gets the brushes and the control styles.

    A ThemedDialog has no layout file, so whatever it contains falls back to
    Windows' chrome unless it is given styles: grey scrollbars with arrows, a
    pale selected row, a blue focus ring, white tick boxes — all of it light,
    inside an otherwise dark window.  Nothing raises; it just looks broken.
    """
    import xml.dom.minidom
    src = open(SCRIPT, encoding='utf-8').read()
    m = re.search(r'_DIALOG_THEME_XAML = """(.*?)"""', src, re.S)
    if not m:
        problems.append('dialogs: _DIALOG_THEME_XAML is gone')
        return
    text = m.group(1)
    try:
        xml.dom.minidom.parseString(text.encode('utf-8'))
    except Exception as exc:
        problems.append('dialogs: the dialog styles do not parse — {0}'.format(exc))
        return
    styled = set(re.findall(r'<Style TargetType="(\w+)"', text))
    for made, needs in CODE_BUILT_CONTROLS:
        if made not in src:
            continue
        for target in needs:
            if target not in styled:
                problems.append('dialogs: {0} is built in code but has no '
                                '{1} style'.format(made, target))
    start = src.find('def palette_brushes(')
    keys = set(re.findall(r"\('(\w+)', C_[A-Z_]+\)", src[start:start + 3000]))
    keys |= set(re.findall(r'x:Key="(\w+)"', text))
    for used in sorted(set(re.findall(r'\{DynamicResource (\w+)\}', text))):
        if used not in keys:
            problems.append('dialogs: the dialog styles use {0}, which no '
                            'dialog defines — it renders as nothing'.format(used))
    methods = _method_sources('ThemedDialog')
    if 'theme_window(self.window)' not in methods.get('__init__', ''):
        problems.append('dialogs: ThemedDialog no longer calls theme_window, '
                        'so every prompt is in Windows chrome')


def rule_worksets_wired(problems):
    """A Workset column is chosen from a list and written by id.

    Each piece fails quietly on its own: a Workset cell that opens a text box
    takes any text and fails at Apply; a stage() without the name check lets
    paste, fill and import stage names that are not worksets; a fill that
    reaches fill_plan directly steps "Level 2 - Mechanical" to "Level 3 -
    Mechanical"; a write through write_param sends a name where Revit wants an
    id.  And borrowing must happen before the transaction opens, because
    CheckoutElements is refused inside one and the refusal is swallowed —
    which is how Set Level borrowed nothing on a workshared model until 1.20.0.
    """
    window = _method_sources('ExcelForRevitWindow')
    model = _method_sources('ScheduleModel')

    begin = window.get('on_begin_edit', '')
    if ('workset_fields' not in begin
            or 'open_workset_dropdown_soon(' not in begin):
        problems.append('worksets: editing a Workset cell no longer opens the '
                        'list of worksets')
    if 'workset_named(' not in window.get('stage', ''):
        problems.append('worksets: stage() no longer checks that a value is a '
                        'workset, so paste, fill and import can stage any text')
    for name, body in window.items():
        if name != 'fill_values' and 'fill_plan(' in body:
            problems.append('worksets: {0}() calls fill_plan directly, so a '
                            'Workset column would count instead of '
                            'copy'.format(name))
    if 'workset_col(' not in window.get('_fill', ''):
        problems.append('worksets: Ctrl+E fills a Workset column as a series, '
                        'counting into other, real worksets')
    src_all = open(SCRIPT, encoding='utf-8').read()
    # the whole expression, which may run over a line break
    for m in re.finditer(r'Keyboard\.Modifiers\s*&[^=]{0,160}?\)\s*==\s*0\b',
                         src_all):
        if src_all[max(0, m.start() - 4):m.start()] != 'int(':
            problems.append('worksets: line {0} compares key modifiers with 0 '
                            '— a .NET enum never equals a Python int under '
                            'IronPython, so the test is always False'.format(
                                src_all.count('\n', 0, m.start()) + 1))
    if 'open_workset_dropdown_soon(' not in window.get('on_grid_mouse_down', ''):
        problems.append('worksets: clicking inside a selection in the Workset '
                        'column collapses it instead of opening the list')
    if 'Set Workset' not in window.get('build_context_menu', ''):
        problems.append('worksets: the right-click menu lost Set Workset')

    apply_src = model.get('apply', '')
    if 'write_workset(' not in apply_src:
        problems.append('worksets: Apply writes a Workset cell as text, but '
                        'Revit wants the workset id')
    start = apply_src.find('tx.Start()')
    first = apply_src.find('checkout_elements(')
    if start < 0:
        problems.append('worksets: no transaction found in apply()')
    elif first < 0 or first > start:
        problems.append('worksets: elements are not borrowed before the '
                        'transaction opens')
    elif apply_src.find('checkout_elements(', start) >= 0:
        problems.append('worksets: apply() borrows inside the transaction, '
                        'where CheckoutElements is refused and the refusal '
                        'swallowed')


def rule_names_bound(problems):
    """Every name the module reads is bound somewhere in it.

    The stub API answers every attribute it is asked for, so a module that
    forgot an import loads perfectly on the bench and dies with a NameError
    the first time the line runs inside Revit.  1.20.0's draft used time.time()
    for the workset list's double-click grace without importing time — a crash
    on the first double-click on a Workset cell.  The palette constants are
    the one deliberate exception: set_theme writes them into the module at
    run time from DARK_THEME / LIGHT_THEME.
    """
    import ast
    src = open(SCRIPT, encoding='utf-8').read()
    tree = ast.parse(src)
    try:
        import builtins
        bound = set(dir(builtins))
    except ImportError:
        bound = set(dir(__builtins__))
    bound |= set(('unicode', 'long', 'basestring', 'xrange', 'unichr',
                  '__file__'))
    bound |= set(re.findall(r"'(C_[A-Z_]+)':", src))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                bound.add((alias.asname or alias.name).split('.')[0])
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(
                node.ctx, (ast.Store, ast.Del)):
            bound.add(node.id)
    loose = sorted(set(
        n.id for n in ast.walk(tree)
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)) - bound)
    for name in loose:
        problems.append('names: {0} is read but never imported, defined or '
                        'assigned — a NameError the first time that line runs '
                        'in Revit'.format(name))


def rule_layout_matches_dark_palette(problems):
    """The layout's brushes must be the dark palette, colour for colour.

    The window opens on the brushes written in the .xaml; the palette only
    takes over when the theme is switched.  The cells, the prompts and the
    buttons built in code use the palette from the start.  So a colour changed
    in one and not the other shows as chrome and cells that disagree — and
    only in dark mode, only until the first theme switch, which is exactly
    the kind of thing nobody notices on the bench.
    """
    src = open(SCRIPT, encoding='utf-8').read()
    layout = open(LAYOUT, encoding='utf-8').read()
    start = src.find('def palette_brushes(')
    dark = re.search(r'DARK_THEME = \{(.*?)\n\}', src, re.S)
    if start < 0 or not dark:
        problems.append('layout colours: palette_brushes or DARK_THEME is gone')
        return
    pairs = re.findall(r"\('(\w+)', (C_[A-Z_]+)\)", src[start:start + 3000])
    palette = dict(re.findall(r"'(C_[A-Z_]+)': '(#[0-9A-Fa-f]+)'", dark.group(1)))
    brushes = dict(re.findall(
        r'x:Key="(\w+)"\s+Color="(#[0-9A-Fa-f]+)"', layout))
    if not pairs:
        problems.append('layout colours: no brush pairs found in palette_brushes')
    for key, const in pairs:
        want = palette.get(const)
        have = brushes.get(key)
        if want is None or have is None:
            problems.append('layout colours: {0} / {1} missing from one '
                            'side'.format(key, const))
        elif want.upper() != have.upper():
            problems.append('layout colours: {0} is {1} in the layout but {2} '
                            'is {3} in the dark palette'.format(
                                key, have, const, want))


def rule_no_duplicated_blocks(problems):
    """The same block of statements must not appear twice in the class.

    A search-and-replace without a count hits every match, which is how the
    ExternalEvent setup ended up running a second time inside wire_grips.
    """
    src = open(SCRIPT, encoding='utf-8').read()
    for marker, where in (('UI.ExternalEvent.Create', 'the ExternalEvent setup'),
                          ('self.dg.ItemsSource =', 'the grid binding'),
                          ('self.build_context_menu()', 'the context menu build')):
        count = src.count(marker)
        if count > 1:
            problems.append('{0} appears {1} times — it should run once'.format(
                where, count))


EGG_DIR = os.path.abspath(os.path.join(HERE, '..', '..', '..',
                                       'lib', 'revobim', 'egg'))


def rule_easter_egg_wired(problems):
    """The shared easter egg must still be wired to the logo.

    Uses the extension's own egg_rule when it is there, so the one definition
    stays in one place; falls back to checking the wiring here when this tool
    is being benched on its own, away from the rest of the extension.
    """
    if os.path.isdir(EGG_DIR):
        if EGG_DIR not in sys.path:
            sys.path.insert(0, EGG_DIR)
        try:
            import egg_rule
            egg_rule.rule_easter_egg_wired(problems)
            return
        except Exception:
            pass          # fall through to the local check

    layout = open(LAYOUT, encoding='utf-8').read()
    src = open(SCRIPT, encoding='utf-8').read()
    if 'x:Name="LogoText"' not in layout:
        problems.append('the RevoBIM wordmark has no x:Name, so the egg has '
                        'nothing to hook')
    if 'egg_hook' not in src:
        problems.append('egg_hook is never imported — the easter egg is not '
                        'wired')
    if 'egg_hook.attach(' not in src:
        problems.append('egg_hook.attach is never called')
    for needed in ('host_window=', 'theme='):
        if 'egg_hook.attach(' in src and needed not in src:
            problems.append('egg_hook.attach is missing {0}'.format(needed))


def rule_header_menu_reachable(problems):
    """The column heading menu must open from anywhere on the heading.

    It hung off a Border with no Background, which WPF does not hit-test in its
    empty areas, so a right-click anywhere but exactly on the column name opened
    the cell menu instead and the duplicate commands could not be found. The
    grid now routes heading right-clicks itself; this keeps it that way.
    """
    src = open(SCRIPT, encoding='utf-8').read()
    code = '\n'.join(l for l in src.split('\n')
                     if not l.strip().startswith('#'))
    if 'PreviewMouseRightButtonUp += self.on_header_right_up' not in code:
        problems.append('a right-click on a heading is not caught on the way '
                        'up — the heading menu depends on the grid choosing to '
                        'raise ContextMenuOpening')
    if 'ContextMenuOpening += self.on_grid_menu_opening' not in code:
        problems.append('the menu key no longer reaches the heading menu')
    if 'walk_up(hit, DataGridColumnHeader)' not in code:
        problems.append('on_grid_menu_opening does not look for the column '
                        'heading under the pointer')
    if 'self.duplicate_items(menu, lambda: self._menu_col)' not in code:
        problems.append('the cell menu has lost its duplicate commands')


def rule_isolate_keeps_box(problems):
    """Isolate Selected must keep the section box visible.

    Temporary isolation hides everything not in the set, the section box
    element included — so the box disappears while still cropping the view,
    which looks like the tool broke the view.
    """
    src = open(SCRIPT, encoding='utf-8').read()
    code = '\n'.join(l for l in src.split('\n') if not l.strip().startswith('#'))
    if 'OST_SectionBox' not in code:
        problems.append('Isolate Selected does not add the section box to the '
                        'isolated set, so the box would vanish')
    if 'IsolateElementsTemporary' not in code:
        problems.append('Isolate Selected no longer isolates temporarily')
    if 'RefreshActiveView' not in code:
        problems.append('the view is changed from a modeless window without a '
                        'RefreshActiveView, so it will not redraw')


SHIPPABLE = ('.py', '.xaml', '.png', '.yaml', '.md')


def rule_clean_folder(problems):
    """Nothing in the tool folder that should not ship.

    A test run once wrote its error log into a "RevoBIM PY" folder beside the
    script, and it went out in the zip.
    """
    for name in os.listdir(HERE):
        path = os.path.join(HERE, name)
        if os.path.isdir(path):
            if name not in ('icons', '__pycache__'):
                problems.append('stray folder in the tool: {0}'.format(name))
        elif not name.lower().endswith(SHIPPABLE):
            problems.append('stray file in the tool: {0}'.format(name))


def rule_init_order(problems):
    """Nothing reachable from __init__ may read an attribute nothing has set.

    Two refinements earn their keep. Calls inside a nested function are not
    followed: those are event handlers being wired up, not work happening
    during construction, and following them floods the result with things that
    are perfectly fine by the time the user clicks. And a write in the same
    method only counts if it comes *before* the read — which is the difference
    between a guard and a bug, and is exactly the shape the real one had:
    `if self._proved:` above `self._proved = True`, with nothing setting it
    anywhere else.
    """
    import ast
    tree = ast.parse(open(SCRIPT, encoding='utf-8').read())
    cls = [n for n in tree.body
           if isinstance(n, ast.ClassDef) and n.name == 'ExcelForRevitWindow'][0]
    methods = {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}
    init = methods.get('__init__')
    if init is None:
        return

    def outer(node):
        """Walk a body without descending into nested functions."""
        stack = list(ast.iter_child_nodes(node))
        while stack:
            n = stack.pop()
            if isinstance(n, (ast.FunctionDef, ast.Lambda)):
                continue
            yield n
            stack.extend(ast.iter_child_nodes(n))

    def selfs(node, store):
        ctx = ast.Store if store else ast.Load
        return [n for n in outer(node)
                if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                and n.value.id == 'self' and isinstance(n.ctx, ctx)]

    # everything any method of the class ever assigns
    everywhere = set()
    for m in methods.values():
        for n in ast.walk(m):
            if (isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                    and n.value.id == 'self' and isinstance(n.ctx, ast.Store)):
                everywhere.add(n.attr)

    # what __init__ itself sets, and where
    init_writes = {}
    for n in selfs(init, True):
        if n.attr not in init_writes or n.lineno < init_writes[n.attr]:
            init_writes[n.attr] = n.lineno

    reported = set()

    def visit(name, chain, depth, origin):
        if depth > 4 or name not in methods:
            return
        body = methods[name]
        writes = {}
        for n in selfs(body, True):
            # the earliest write, not the first one the walk happens to reach:
            # the traversal order is not source order
            if n.attr not in writes or n.lineno < writes[n.attr]:
                writes[n.attr] = n.lineno
        reads = list(selfs(body, False))
        # getattr(self, 'name', ...) is a read too, and a defensive one is
        # exactly where a missing attribute likes to hide
        for n in outer(body):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                    and n.func.id == 'getattr' and len(n.args) >= 2
                    and isinstance(n.args[0], ast.Name) and n.args[0].id == 'self'
                    and isinstance(n.args[1], ast.Constant)):
                fake = ast.Attribute()
                fake.attr = n.args[1].value
                fake.lineno = n.lineno
                reads.append(fake)
        for n in reads:
            attr = n.attr
            if attr in methods:
                continue
            # already set by __init__ before the call that got us here
            set_at = init_writes.get(attr)
            if set_at is not None and set_at < origin:
                continue
            first_write = writes.get(attr)
            if first_write is not None and first_write < n.lineno:
                continue                      # set before it is read: fine
            if attr in everywhere and attr not in writes:
                continue                      # some other method sets it
            if attr in writes and first_write is not None and first_write < n.lineno:
                continue
            if attr not in everywhere:
                key = (attr, name)
                if key not in reported:
                    reported.add(key)
                    problems.append(
                        'self.{0} is read by {1} but nothing ever sets it '
                        '({2})'.format(attr, name, ' -> '.join(chain)))
                continue
            # assigned only in this method, and only after this read
            if attr in writes:
                key = (attr, name)
                if key not in reported:
                    reported.add(key)
                    problems.append(
                        'self.{0} is read by {1} before anything sets it '
                        '({2})'.format(attr, name, ' -> '.join(chain)))
        for n in outer(body):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and isinstance(n.func.value, ast.Name)
                    and n.func.value.id == 'self'):
                visit(n.func.attr, chain + [n.func.attr], depth + 1,
                      origin if depth else n.lineno)

    visit('__init__', ['__init__'], 0, 10 ** 9)


# Which assemblies provide each namespace.  A namespace is satisfied when the
# tool references at least one of them.  Both spellings are listed wherever
# .NET Framework 4.8 (Revit 2024) and .NET 8 (Revit 2025+) disagree, because
# the same namespace moves between assemblies across that line — which is
# exactly how a tool runs for months on one Revit and dies at load on another.
PROVIDERS = {
    'System': ('mscorlib', 'System.Runtime'),
    'System.Collections.Generic': ('mscorlib', 'System.Runtime'),
    'System.ComponentModel': ('System', 'System.ObjectModel',
                              'System.ComponentModel',
                              'System.ComponentModel.Primitives',
                              'System.ComponentModel.TypeConverter'),
    'System.Data': ('System.Data', 'System.Data.Common'),
    'System.Diagnostics': ('System', 'System.Diagnostics.Process'),
    'System.IO': ('mscorlib', 'System.Runtime'),
    'System.IO.Compression': ('System.IO.Compression',),
    'System.Text': ('mscorlib', 'System.Runtime'),
    'System.Threading': ('mscorlib', 'System.Runtime', 'System.Threading'),
    'System.Windows': ('PresentationFramework', 'PresentationCore',
                       'WindowsBase'),
    'System.Windows.Controls': ('PresentationFramework',),
    'System.Windows.Controls.Primitives': ('PresentationFramework',),
    'System.Windows.Data': ('PresentationFramework',),
    'System.Windows.Documents': ('PresentationFramework',),
    'System.Windows.Forms': ('System.Windows.Forms',),
    'System.Windows.Forms.Integration': ('WindowsFormsIntegration',),
    'System.Windows.Input': ('PresentationCore',),
    'System.Windows.Interop': ('PresentationCore', 'PresentationFramework'),
    'System.Windows.Markup': ('PresentationFramework', 'System.Xaml'),
    'System.Windows.Media': ('PresentationCore',),
    'System.Windows.Media.Animation': ('PresentationCore',),
    'System.Windows.Media.Imaging': ('PresentationCore',),
    'System.Windows.Threading': ('WindowsBase',),
    'Autodesk.Revit': ('RevitAPI', 'RevitAPIUI'),
    'Autodesk.Revit.DB': ('RevitAPI',),
    'Autodesk.Revit.UI': ('RevitAPIUI',),
    'Autodesk.Windows': ('AdWindows',),
}

RUNTIME_MODULES = ('efr_core.py', 'script.py', 'xlsx_io.py',
                   'excel_bridge.py')


def _literal(node):
    """The string a node holds, or None.

    `ast.Str` is named rather than referenced, so this keeps working on the
    old and the new node shape without tripping the deprecation.
    """
    import ast
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if node.__class__.__name__ == 'Str':
        return getattr(node, 's', None)
    return None


def _import_time_nodes(tree):
    """Every node that actually runs when the module is imported.

    A `clr.AddReference` inside a function is not a reference the imports at
    the top of the file can rely on — `script.py` keeps a couple inside its
    error reporter, which by definition only runs once `import efr_core` has
    already failed. Counting those would have the check certify the very
    import order that breaks.
    """
    import ast
    out, stack = [], list(tree.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            continue
        out.append(node)
        stack.extend(ast.iter_child_nodes(node))
    return out


def referenced_assemblies():
    """Every assembly the tool references at import time, across its modules."""
    import ast
    names = set()
    for module in RUNTIME_MODULES:
        path = os.path.join(HERE, module)
        if not os.path.exists(path):
            continue
        try:
            tree = ast.parse(open(path, encoding='utf-8').read())
        except SyntaxError:
            continue
        for node in _import_time_nodes(tree):
            # clr.AddReference('Name')
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == 'AddReference'):
                for arg in node.args:
                    found = _literal(arg)
                    if found:
                        names.add(found)
            # for _asm in ('A', 'B', ...):
            if isinstance(node, ast.For) and isinstance(node.iter,
                                                        (ast.Tuple, ast.List)):
                for element in node.iter.elts:
                    found = _literal(element)
                    if found:
                        names.add(found)
    return names


def rule_assemblies_referenced(problems):
    """Every .NET namespace the tool imports must have its assembly referenced.

    This is the one rule the stub API cannot stand in for.  Under CPython a
    namespace either resolves or it does not and there is no assembly to
    reference, so `rule_module_loads` passes happily on code that dies at
    load inside Revit with "Cannot import name X" and a blank white window.

    An assembly merely being loaded in the process does not count either:
    IronPython exposes namespaces from the assemblies referenced into its
    runtime, so a namespace reached through some other assembly's dependency
    works right up until the day the load order changes.  That is how
    `System.ComponentModel.ListSortDirection` ran for months on
    `clr.AddReference('System.Data')` alone and then stopped.
    """
    referenced = referenced_assemblies()
    for module in RUNTIME_MODULES:
        path = os.path.join(HERE, module)
        if not os.path.exists(path):
            continue
        src = open(path, encoding='utf-8').read()
        wanted = set(re.findall(r'^\s*from ([\w.]+) import ', src, re.M))
        wanted.update(re.findall(r'^\s*import ([\w.]+)', src, re.M))
        for ns in sorted(wanted):
            if ns.split('.')[0] not in ('System', 'Autodesk', 'Microsoft'):
                continue
            if ns not in PROVIDERS:
                problems.append(
                    '{0} imports from {1}, which PROVIDERS does not know — '
                    'add it with the assemblies that provide it'.format(
                        module, ns))
                continue
            if not (set(PROVIDERS[ns]) & referenced):
                problems.append(
                    '{0} imports from {1} but none of its assemblies ({2}) is '
                    'referenced — this throws "Cannot import name" at load '
                    'inside Revit'.format(module, ns,
                                          ', '.join(PROVIDERS[ns])))


def _method_sources(class_name):
    """{method name: source text} for one class in the tool."""
    import ast
    src = open(SCRIPT, encoding='utf-8').read()
    lines = src.splitlines()
    tree = ast.parse(src)
    out = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, ast.FunctionDef):
                    last = max(getattr(n, 'end_lineno', item.lineno) or
                               item.lineno for n in ast.walk(item))
                    out[item.name] = '\n'.join(lines[item.lineno - 1:last])
    return out


def rule_hot_paths_stay_light(problems):
    """What runs per scroll tick, per layout pass and per selected cell.

    These handlers fire dozens to thousands of times a second, and each of
    them once walked every row in the schedule.  None of it shows on a test
    model of fifty rows; all of it shows on a real one.  This rule keeps the
    expensive calls out of them, and keeps the two hooks the caches depend
    on — without UnloadingRow the set of realised rows grows for ever, and
    without ListChanged the remembered row positions go stale and edits land
    in the wrong cells.
    """
    src = open(SCRIPT, encoding='utf-8').read()
    methods = _method_sources('ExcelForRevitWindow')

    for hook, why in (
            ('UnloadingRow += self.on_unloading_row',
             'recycled rows are never dropped from the live set'),
            ('ListChanged += self.on_view_changed',
             'the cached row positions never learn the rows were re-ordered, '
             'so edits can land in the wrong cells')):
        if hook not in src:
            problems.append('hot paths: "{0}" is not wired — {1}'.format(
                hook, why))

    walks = ('Items.Count', 'ContainerFromItem', 'sel_cells(')
    for name in ('on_scroll', 'on_layout_updated', 'repaint',
                 'repaint_dirty', 'place_handle', 'on_selection_changed',
                 'on_loading_row', 'on_unloading_row'):
        body = methods.get(name)
        if body is None:
            problems.append('hot paths: {0}() is gone'.format(name))
            continue
        for walk in walks:
            if walk in body:
                problems.append('hot paths: {0}() calls {1} — that walks the '
                                'whole schedule or the whole selection, and '
                                'this runs on every tick'.format(name, walk))

    body = methods.get('on_selection_changed', '')
    for heavy in ('place_handle(', 'editable_selection(', 'paint_formula('):
        if heavy in body:
            problems.append('hot paths: on_selection_changed() calls {0} '
                            'directly — the grid raises it once per cell, so '
                            'the work has to wait for the burst to '
                            'end'.format(heavy))
    if 'BeginInvoke' not in body:
        problems.append('hot paths: on_selection_changed() no longer queues '
                        'its work, so a drag-select is quadratic again')

    if '_dirty_paint = True' in methods.get('on_scroll', ''):
        problems.append('hot paths: on_scroll() repaints every row on every '
                        'tick; recycled rows already arrive through '
                        'LoadingRow')


def rule_drawer_complete(problems):
    """The shrink-to-taskbar drawer, which fails silently in four ways.

    A WPF animation holds its end value and outranks every later plain
    assignment, so a drawer that does not hand Height and Top back leaves a
    window that can never be resized or moved again — and nothing is raised
    to say so.  The same goes for the MinHeight it has to relax to get the
    window down to bar height: left at zero, the window can be dragged shut
    for the rest of the session.  The other two are a button that is drawn
    but not wired, and a window that was never given a drawer at all.
    """
    import ast
    src = open(SCRIPT, encoding='utf-8').read()
    layout = open(LAYOUT, encoding='utf-8').read()

    if 'x:Name="ShrinkBtn"' not in layout:
        problems.append('the layout has no ShrinkBtn, so the main window '
                        'cannot be shrunk')

    # one per window kind: the dialogs and the main window
    wired = len(re.findall(r'\.Click \+= self\.drawer\.toggle', src))
    if wired < 2:
        problems.append('only {0} window wires a shrink button to '
                        'drawer.toggle — every window in the tool needs '
                        'one'.format(wired))
    built = len(re.findall(r'=\s*WindowDrawer\(', src))
    if built < 2:
        problems.append('WindowDrawer is built {0} time(s) — the main window '
                        'and ThemedDialog each need their own'.format(built))

    tree = ast.parse(src)
    found = [n for n in tree.body
             if isinstance(n, ast.ClassDef) and n.name == 'WindowDrawer']
    if not found:
        problems.append('WindowDrawer is gone, so no window can be shrunk')
        return
    node = found[0]
    lines = src.splitlines()
    last = max(getattr(n, 'end_lineno', node.lineno) or node.lineno
               for n in ast.walk(node))
    text = '\n'.join(lines[node.lineno - 1:last])

    for probe, why in (
            ('BeginAnimation(Window.TopProperty, None)',
             'never releases Top, so the window can never be moved again'),
            ('BeginAnimation(Window.HeightProperty, None)',
             'never releases Height, so the window can never be resized '
             'again'),
            ('MinHeight = self.saved_min_h',
             'relaxes MinHeight to shrink but never puts it back'),
            ('def shrink(', 'has no way in'),
            ('def expand(', 'has no way back out'),
    ):
        if probe not in text:
            problems.append('WindowDrawer {0} (looked for "{1}")'.format(
                why, probe))


RULES = (rule_xaml_parses, rule_loader_is_thin, rule_known_namespaces,
         rule_module_imports, rule_non_ascii_literals, rule_no_banned_forms,
         rule_names_resolve, rule_resources_exist, rule_palettes_match,
         rule_no_duplicated_blocks, rule_easter_egg_wired, rule_clean_folder,
         rule_header_menu_reachable, rule_isolate_keeps_box, rule_init_order,
         rule_drawer_complete, rule_assemblies_referenced,
         rule_hot_paths_stay_light, rule_layout_matches_dark_palette,
         rule_liveness_proof_after_show, rule_dialogs_themed,
         rule_worksets_wired, rule_names_bound)


def run():
    problems = []
    for rule in RULES:
        try:
            rule(problems)
        except Exception:
            import traceback
            problems.append('{0} itself failed:\n{1}'.format(
                rule.__name__, traceback.format_exc()))
    return problems


def selftest():
    """Break each rule on purpose. A rule nobody has tested does not work."""
    print('Self test - each of these must be CAUGHT:')
    ok = True
    checks = [
        ('undefined resource key', rule_resources_exist,
         (LAYOUT, '{DynamicResource Orange}', '{DynamicResource NoSuchKey}')),
        ('BasedOn with DynamicResource', rule_resources_exist,
         (LAYOUT, 'BasedOn="{StaticResource ToolBtn}"',
          'BasedOn="{DynamicResource ToolBtn}"')),
        ('missing x:Name', rule_names_resolve,
         (LAYOUT, 'x:Name="BtnApply"', 'x:Name="BtnApplyX"')),
        ('f-string', rule_no_banned_forms,
         (SCRIPT, 'def to_text(', 'def to_text(\n    _ = f"no"\n')),
        ('palette hole', rule_palettes_match,
         (SCRIPT, "'C_COPY_BG': '#585020',", '')),
        ('mis-namespaced import', rule_known_namespaces,
         (SCRIPT, 'from System.Windows import SystemParameters',
          'from System.Windows.Controls import SystemParameters')),
        ('section box dropped from the isolation', rule_isolate_keeps_box,
         (SCRIPT, 'OST_SectionBox', 'OST_Nothing')),
        ('heading menu not routed', rule_header_menu_reachable,
         (SCRIPT, 'PreviewMouseRightButtonUp += self.on_header_right_up',
          'pass  # routing removed')),
        ('easter egg unwired', rule_easter_egg_wired,
         (SCRIPT, 'egg_hook.attach(targets', 'pass  # (attach removed)')),
        ('attribute read before __init__ sets it', rule_init_order,
         (SCRIPT, '        self._proved = False\n', '')),
        ('plain non-ASCII literal', rule_non_ascii_literals,
         (SCRIPT, "u'Excel for Revit ", "'Excel for Revit ")),
        ('a block that runs twice', rule_no_duplicated_blocks,
         (SCRIPT, 'self.build_context_menu()',
          'self.build_context_menu()\n        self.build_context_menu()')),
        ('unknown namespace', rule_known_namespaces,
         (SCRIPT, 'from System.Windows import Visibility',
          'from System.Windows.Nowhere import Visibility')),
        ('drawer never releases the animated height', rule_drawer_complete,
         (SCRIPT, 'w.BeginAnimation(Window.HeightProperty, None)',
          'pass  # (release removed)')),
        ('drawer leaves MinHeight at zero', rule_drawer_complete,
         (SCRIPT, 'self.window.MinHeight = self.saved_min_h',
          'pass  # (restore removed)')),
        ('a window whose shrink button is not wired', rule_drawer_complete,
         (SCRIPT, 'self.shrink_btn.Click += self.drawer.toggle',
          'pass  # (wiring removed)')),
        ('a window built without a drawer', rule_drawer_complete,
         (SCRIPT, 'self.drawer = WindowDrawer(self.window, head, root,',
          'self.drawer = None  # (')),
        ('shrink button missing from the layout', rule_drawer_complete,
         (LAYOUT, 'x:Name="ShrinkBtn"', 'x:Name="ShrinkBtnX"')),
        ('a namespace whose assembly is never referenced',
         rule_assemblies_referenced,
         (SCRIPT, "             'System.Data', 'System.Data.Common',\n", '')),
        ('recycled rows never leave the live set', rule_hot_paths_stay_light,
         (SCRIPT, 'self.dg.UnloadingRow += self.on_unloading_row',
          'pass  # (unloading unwired)')),
        ('row positions never told the order changed',
         rule_hot_paths_stay_light,
         (SCRIPT, 'table.DefaultView.ListChanged += self.on_view_changed',
          'pass  # (view unwired)')),
        ('repaint walks every row again', rule_hot_paths_stay_light,
         (SCRIPT, '        self._dirty_paint = False\n        rows = list(self.live_rows)',
          '        self._dirty_paint = False\n        n = self.dg.Items.Count\n'
          '        rows = list(self.live_rows)')),
        ('the fill handle rebuilds the whole selection',
         rule_hot_paths_stay_light,
         (SCRIPT, 'last = self.last_selected()',
          'last = self.sel_cells() and self.last_selected()')),
        ('selection handled per cell instead of per burst',
         rule_hot_paths_stay_light,
         (SCRIPT, '        self._last_sel = _STALE\n        if self._sel_pending:',
          '        self.place_handle()\n        self._last_sel = _STALE\n'
          '        if self._sel_pending:')),
        ('every scroll tick repaints every row', rule_hot_paths_stay_light,
         (SCRIPT, '        self.place_handle()\n\n    def on_layout_updated',
          '        self._dirty_paint = True\n        self.place_handle()\n\n'
          '    def on_layout_updated')),
        ('layout brush out of step with the dark palette',
         rule_layout_matches_dark_palette,
         (LAYOUT, 'x:Key="BgWindow" Color="#3C4454"',
          'x:Key="BgWindow" Color="#232326"')),
        ('liveness proof counted before the window is shown',
         rule_liveness_proof_after_show,
         (SCRIPT, 'if self._proved or not self._shown:', 'if self._proved:')),
        ('window marked shown before Show() has run',
         rule_liveness_proof_after_show,
         (SCRIPT, "        save_settings({'modeless_pending': True})\n",
          "        save_settings({'modeless_pending': True})\n"
          "        self._shown = True\n")),
        ('old modal setting never reset', rule_liveness_proof_after_show,
         (SCRIPT, 'migrate_window_settings()\n        check_modeless_health()',
          'check_modeless_health()')),
        ('dialogs left unthemed', rule_dialogs_themed,
         (SCRIPT, '        theme_window(self.window)\n', '')),
        ('a dialog style naming a brush that does not exist',
         rule_dialogs_themed,
         (SCRIPT, 'Value="{DynamicResource RowHover}"',
          'Value="{DynamicResource RowHovr}"')),
        ('list rows without a style', rule_dialogs_themed,
         (SCRIPT, '<Style TargetType="ListBoxItem">',
          '<Style TargetType="ListBoxItemX">')),
        ('dialog styles that do not parse', rule_dialogs_themed,
         (SCRIPT, '<Style TargetType="RadioButton">',
          '<Style TargetType="RadioButton">\n  <Broken>')),
        ('a Workset cell opens a text box', rule_worksets_wired,
         (SCRIPT, '                self.open_workset_dropdown_soon(cell, seed)\n',
          '                pass\n')),
        ('stage() lets any text into a Workset cell', rule_worksets_wired,
         (SCRIPT, 'found = workset_named(model.worksets, text)',
          'found = (text, 0)')),
        ('a fill that bypasses copy-only', rule_worksets_wired,
         (SCRIPT, 'values = self.fill_values(col, seeds, len(dest), True)',
          'values = fill_plan(seeds, len(dest), True)')),
        ('clicking in a selection collapses it', rule_worksets_wired,
         (SCRIPT, '                    self.open_workset_dropdown_soon(cell)\n'
                  '                    return\n',
          '                    return\n')),
        ('Apply writes the workset as text', rule_worksets_wired,
         (SCRIPT, 'ok, msg = write_workset(param, text, self.worksets)',
          'ok, msg = write_param(param, text)')),
        ('no borrowing before the transaction', rule_worksets_wired,
         (SCRIPT, '        if borrow:\n            checkout_elements(doc, borrow)\n',
          '')),
        ('borrowing inside the transaction again', rule_worksets_wired,
         (SCRIPT, '            if self.level_edits:\n'
                  '                apply_level_edits(doc, self, res, touched_rows)',
          '            if self.level_edits:\n'
                  '                checkout_elements(doc, [])\n'
                  '                apply_level_edits(doc, self, res, touched_rows)')),
        ('Ctrl+E counts through workset names', rule_worksets_wired,
         (SCRIPT, '            sequence = sequence and not self.workset_col(col)\n', '')),
        ('modifier flags compared with 0', rule_worksets_wired,
         (SCRIPT, '                    plain = int(Keyboard.Modifiers & (ModifierKeys.Control |',
          '                    plain = (Keyboard.Modifiers & (ModifierKeys.Control |')),
        ('a module used without being imported', rule_names_bound,
         (SCRIPT, 'import os\nimport time\n', 'import os\n')),
        ('a namespace nothing in the table knows about',
         rule_assemblies_referenced,
         (SCRIPT, 'from System.Data import DataTable',
          'from System.Speech import Nothing\nfrom System.Data import '
          'DataTable')),
    ]
    for label, rule, (path, find, replace) in checks:
        original = open(path, encoding='utf-8').read()
        if find not in original:
            # a breakage that never happened proves nothing, so it fails the
            # selftest rather than quietly passing it
            print('  SKIPPED {0} (anchor not found - fix the test)'.format(label))
            ok = False
            continue
        try:
            open(path, 'w', encoding='utf-8').write(
                original.replace(find, replace, 1))
            problems = []
            rule(problems)
            caught = bool(problems)
        finally:
            open(path, 'w', encoding='utf-8').write(original)
        print('  {0} {1}'.format('CAUGHT ' if caught else 'MISSED ', label))
        ok = ok and caught
    return ok


def main():
    if '--selftest' in sys.argv:
        good = selftest()
        print('\nSelf test {0}'.format('PASSED' if good else 'FAILED'))
        return 0 if good else 1
    problems = run()
    if problems:
        print('FAILED - {0} problem(s):'.format(len(problems)))
        for p in problems:
            print('  ' + p)
        return 1
    print('All checks passed.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
