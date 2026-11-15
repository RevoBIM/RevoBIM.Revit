# -*- coding: utf-8 -*-
"""Bench check for RevoBIM Pipe Slope Assigner, under plain CPython.

    python import_check.py              run every rule against the shipped files
    python import_check.py --selftest   break each rule on purpose and confirm
                                        the rule catches it

Every rule here stands for a way a RevoBIM tool has shipped broken before -
most of them as a blank white pyRevit window with nothing readable in it. The
rules read the files into memory first, so the selftest can break a copy and
never touch the real thing.

A rule nobody has tested is a rule that does not work: --selftest is the proof.
"""

from __future__ import print_function

import ast
import importlib.util
import io
import os
import re
import sys
import tokenize
import types
import xml.dom.minidom

HERE = os.path.dirname(os.path.abspath(__file__))
EXTENSION = os.path.normpath(os.path.join(HERE, '..', '..', '..', '..'))

MODULES = ['psa_clr.py', 'psa_core.py', 'psa_theme.py', 'psa_ui.py',
           'psa_revit.py', 'psa_main.py', 'script.py']
LOAD_ORDER = ['psa_core', 'psa_theme', 'psa_ui', 'psa_revit', 'psa_main']
LAYOUTS = ['PipeSlopeAssigner.xaml', 'PipeSlopeResults.xaml']
XAMLS = LAYOUTS + ['Theme.xaml']
TEXTS = ['bundle.yaml', 'CHANGELOG.md']
CLR_MODULE = 'psa_clr'

# Where the real API puts each name. A name imported from any other namespace
# fails here instead of at load in Revit.
API = {
    'System': ['AppDomain', 'Exception', 'String', 'Environment'],
    'System.Collections.Generic': ['List', 'Dictionary'],
    'System.IO': ['MemoryStream', 'File', 'Path'],
    'System.Windows': ['Visibility', 'Thickness', 'TextWrapping', 'Clipboard', 'Window',
                       'WindowStyle', 'FontWeights', 'SystemParameters',
                       'WindowStartupLocation'],
    'System.Windows.Controls': ['Border', 'TextBlock', 'DockPanel', 'Dock', 'StackPanel',
                                'Button', 'RadioButton', 'CheckBox', 'TextBox'],
    'System.Windows.Markup': ['XamlReader'],
    'System.Windows.Media': ['SolidColorBrush', 'ColorConverter', 'Brushes'],
    'System.Windows.Media.Imaging': ['BitmapImage', 'BitmapCacheOption'],
    'System.Windows.Interop': ['WindowInteropHelper'],
    'System.Diagnostics': ['Process'],
    'Autodesk.Revit.DB': [
        'BuiltInCategory', 'BuiltInParameter', 'ConnectorType', 'ElementId',
        'ElementTransformUtils', 'FailureProcessingResult', 'FailureSeverity',
        'FamilyInstance', 'IFailuresPreprocessor', 'Line', 'LocationPoint',
        'StorageType', 'Transaction', 'TransactionGroup', 'TransactionStatus',
        'WorksharingUtils', 'XYZ', 'RoutingPreferenceRuleGroupType'],
    'Autodesk.Revit.DB.Plumbing': ['Pipe', 'PlumbingUtils', 'PipeType'],
    'Autodesk.Revit.UI': ['TaskDialog', 'TaskDialogCommonButtons', 'UIApplication',
                          'ExternalEvent', 'IExternalEventHandler'],
    'Autodesk.Revit.UI.Selection': ['ISelectionFilter', 'ObjectType'],
}

# The assembly each .NET namespace lives in. None: always loaded (mscorlib, or
# RevitAPI / RevitAPIUI, which pyRevit references before any script runs).
ASSEMBLY_FOR = {
    'System': None,
    'System.Collections.Generic': None,
    'System.IO': None,
    'System.Windows': 'PresentationFramework',
    'System.Windows.Controls': 'PresentationFramework',
    'System.Windows.Markup': 'PresentationFramework',
    'System.Windows.Interop': 'PresentationFramework',
    'System.Windows.Media': 'PresentationCore',
    'System.Windows.Media.Imaging': 'PresentationCore',
    'System.Diagnostics': 'System',
    'Autodesk.Revit.DB': None,
    'Autodesk.Revit.DB.Plumbing': None,
    'Autodesk.Revit.UI': None,
    'Autodesk.Revit.UI.Selection': None,
}

WPF_EVENTS = ('Click', 'Checked', 'Unchecked', 'MouseLeftButtonDown', 'PreviewKeyDown',
              'KeyDown', 'TextChanged', 'SelectionChanged', 'Loaded', 'Closed',
              'PreviewMouseLeftButtonDown', 'MouseDoubleClick', 'ContentRendered')

SHARED_FILES = ('startup.py', os.path.join('lib', 'revobim', '__init__.py'))


# ====================== reading ======================

def read_all(folder=HERE):
    files = {}
    for name in MODULES + XAMLS + TEXTS:
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            handle = io.open(path, 'r', encoding='utf-8')
            try:
                files[name] = handle.read()
            finally:
                handle.close()
    files['__folder__'] = os.path.basename(folder)
    files['__tree__'] = shipped_tree()
    return files


def shipped_tree():
    """Every file in the delivery, relative to the extension folder."""
    out = []
    if not os.path.isdir(EXTENSION):
        return out
    for root, dirs, names in os.walk(EXTENSION):
        dirs[:] = [d for d in dirs if d != '__pycache__']
        for n in names:
            out.append(os.path.relpath(os.path.join(root, n), EXTENSION))
    return out


def py_files(files):
    return [n for n in MODULES if n in files]


def _code_only(src):
    """Source with comments and strings blanked to spaces, so a rule reading
    the code is not set off by a docstring explaining the rule. Positions and
    line breaks are kept, so line numbers still point at the right place."""
    lines = src.splitlines(True)
    chars = [list(line) for line in lines]
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type not in (tokenize.COMMENT, tokenize.STRING):
                continue
            (r0, c0), (r1, c1) = tok.start, tok.end
            for r in range(r0 - 1, r1):
                start = c0 if r == r0 - 1 else 0
                stop = c1 if r == r1 - 1 else len(chars[r])
                for c in range(start, stop):
                    if chars[r][c] not in '\r\n':
                        chars[r][c] = ' '
    except Exception:
        return src
    return ''.join(''.join(line) for line in chars)


def trees(files):
    out = {}
    for name in py_files(files):
        out[name] = ast.parse(files[name], name)
    return out


# ====================== the rules ======================

RULES = []


def rule(fn):
    RULES.append(fn)
    return fn


@rule
def rule_xaml_parses(files):
    """Every .xaml parses as XML - a run of hyphens in a comment, an unclosed
    tag or a bare & is the blank white window."""
    out = []
    for name in XAMLS:
        try:
            xml.dom.minidom.parseString(files[name].encode('utf-8'))
        except Exception as ex:
            out.append(u'{0}: {1}'.format(name, ex))
    return out


@rule
def rule_no_double_hyphen_in_xaml_comments(files):
    out = []
    for name in XAMLS:
        for body in re.findall(r'<!--(.*?)-->', files[name], re.S):
            if '--' in body:
                out.append(u'{0}: "--" inside a comment'.format(name))
    return out


@rule
def rule_no_static_resource(files):
    return [u'{0}: StaticResource in a layout'.format(n) for n in LAYOUTS
            if 'StaticResource' in files[n]]


@rule
def rule_no_baseline(files):
    return [u'{0}: VerticalAlignment="Baseline" is not a WPF value'.format(n)
            for n in XAMLS if 'VerticalAlignment="Baseline"' in files[n]]


def theme_keys(files):
    return set(re.findall(r'x:Key="([^"]+)"', files['Theme.xaml']))


def palettes(files):
    tree = ast.parse(files['psa_theme.py'])
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
            name = node.targets[0].id
            if name in ('DARK', 'LIGHT'):
                out[name] = set(k.value for k in node.value.keys)
    return out


@rule
def rule_dynamic_keys_exist(files):
    keys = theme_keys(files)
    out = []
    for name in XAMLS:
        for key in set(re.findall(r'DynamicResource\s+([A-Za-z0-9_]+)', files[name])):
            if key not in keys:
                out.append(u'{0}: DynamicResource {1} is not in Theme.xaml'.format(name, key))
    return out


@rule
def rule_palettes_match_theme(files):
    keys = theme_keys(files)
    pals = palettes(files)
    out = []
    if set(pals) != {'DARK', 'LIGHT'}:
        return [u'psa_theme.py: DARK and LIGHT palettes not both found']
    if pals['DARK'] != pals['LIGHT']:
        out.append(u'palettes differ: {0}'.format(sorted(pals['DARK'] ^ pals['LIGHT'])))
    for k in sorted(pals['DARK'] | pals['LIGHT']):
        if k not in keys:
            out.append(u'palette key {0} has no default brush in Theme.xaml'.format(k))
    return out


@rule
def rule_resource_references_exist(files):
    keys = theme_keys(files)
    out = []
    for name in py_files(files):
        for key in re.findall(r"SetResourceReference\([^,]+,\s*'([A-Za-z]+)'\)", files[name]):
            if key not in keys:
                out.append(u'{0}: SetResourceReference to unknown key {1}'.format(name, key))
        if 'ROW_BRUSH' in files[name]:
            m = re.search(r'ROW_BRUSH = \{([^}]*)\}', files[name])
            if m:
                for key in re.findall(r":\s*'([A-Za-z]+)'", m.group(1)):
                    if key not in keys:
                        out.append(u'{0}: row brush {1} is not a theme key'.format(name, key))
    return out


@rule
def rule_style_target_types(files):
    text = files['Theme.xaml']
    targets = dict(re.findall(r'<Style x:Key="([^"]+)" TargetType="([^"]+)"', text))
    out = []
    for name in LAYOUTS:
        for tag, key in re.findall(r'<([A-Za-z]+)\b[^>]*?Style="\{DynamicResource ([A-Za-z]+)\}"',
                                   files[name]):
            want = targets.get(key)
            if want is None:
                out.append(u'{0}: style {1} not defined'.format(name, key))
            elif want != tag:
                out.append(u'{0}: <{1}> given style {2} for {3}'.format(name, tag, key, want))
    return out


def x_names(files):
    names = set()
    for n in LAYOUTS:
        names.update(re.findall(r'x:Name="([^"]+)"', files[n]))
    return names


@rule
def rule_find_name_matches(files):
    """Every FindName has an x:Name - including the aliased form
    find = window.FindName, which a literal FindName("X") match misses."""
    names = x_names(files)
    out = []
    for name in py_files(files):
        src = files[name]
        for key in re.findall(r"""(?:FindName|\bfind)\(\s*u?'([^']+)'""", src):
            if '{0}' in key:
                pattern = re.compile('^' + re.escape(key).replace(r'\{0\}', '.+') + '$')
                if not any(pattern.match(x) for x in names):
                    out.append(u'{0}: FindName("{1}") matches no x:Name'.format(name, key))
            elif key not in names:
                out.append(u'{0}: FindName("{1}") has no x:Name'.format(name, key))
    for n in (100, 80, 60, 40):
        if 'Slope{0}'.format(n) not in names:
            out.append(u'slope tile Slope{0} missing from the prompt'.format(n))
    return out


@rule
def rule_no_fstrings_or_print(files):
    out = []
    for name, tree in trees(files).items():
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr):
                out.append(u'{0}:{1}: f-string'.format(name, node.lineno))
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == 'print'):
                out.append(u'{0}:{1}: print'.format(name, node.lineno))
    return out


@rule
def rule_integer_value_only_in_helper(files):
    """ElementId.IntegerValue was removed in 2026: only eid_value may touch it."""
    out = []
    for name, tree in trees(files).items():
        allowed = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == 'eid_value':
                for sub in ast.walk(node):
                    allowed.add(id(sub))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute) and node.attr == 'IntegerValue'
                    and id(node) not in allowed):
                out.append(u'{0}:{1}: bare .IntegerValue'.format(name, node.lineno))
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == 'getattr' and id(node) not in allowed
                    and 'IntegerValue' in ast.dump(node)):
                out.append(u'{0}:{1}: IntegerValue through getattr'.format(name, node.lineno))
        if 'Integer' + "' + '" in files[name] or "'Integer' + 'Value'" in files[name]:
            out.append(u'{0}: IntegerValue spelled in pieces to dodge the check'.format(name))
    return out


@rule
def rule_no_system_uri(files):
    out = []
    for name in py_files(files):
        code = _code_only(files[name])
        if re.search(r'\bUri\b', code):
            out.append(u'{0}: System.Uri (moved assemblies in 2025)'.format(name))
    return out


@rule
def rule_ascii_only(files):
    """Non-ASCII outside a u'' escape breaks IronPython 2.7 without a coding
    line, and quietly mangles text with one. Escape it: u'\\u00d8'."""
    out = []
    for name in py_files(files):
        for i, line in enumerate(files[name].splitlines(), 1):
            if any(ord(ch) > 127 for ch in line):
                out.append(u'{0}:{1}: non-ASCII character'.format(name, i))
    return out


def top_level_imports(tree):
    out = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            for a in node.names:
                out.append((node.lineno, a.name))
        elif isinstance(node, ast.ImportFrom):
            out.append((node.lineno, node.module or ''))
    return out


@rule
def rule_clr_first(files):
    """Every module touching System.* or Autodesk.* at the top imports psa_clr
    first. pyRevit does not preload WPF into every engine."""
    out = []
    for name, tree in trees(files).items():
        if name in ('script.py', 'psa_clr.py'):
            continue
        imports = top_level_imports(tree)
        dotnet = [ln for ln, mod in imports if mod.split('.')[0] in ('System', 'Autodesk')]
        clr_line = [ln for ln, mod in imports if mod == CLR_MODULE]
        if not dotnet:
            continue
        if not clr_line:
            out.append(u'{0}: reaches into .NET without importing {1}'.format(name, CLR_MODULE))
        elif clr_line[0] > min(dotnet):
            out.append(u'{0}: imports {1} after a .NET import'.format(name, CLR_MODULE))
    return out


@rule
def rule_names_in_their_namespace(files):
    out = []
    for name, tree in trees(files).items():
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            mod = node.module
            if mod.split('.')[0] not in ('System', 'Autodesk'):
                continue
            if mod not in API:
                out.append(u'{0}:{1}: namespace {2} not in the stub API'.format(
                    name, node.lineno, mod))
                continue
            for a in node.names:
                if a.name not in API[mod]:
                    out.append(u'{0}:{1}: {2} is not in {3}'.format(name, node.lineno, a.name, mod))
    return out


@rule
def rule_script_is_thin(files):
    """script.py imports nothing that can fail before its try/except."""
    tree = ast.parse(files['script.py'])
    out = []
    for ln, mod in top_level_imports(tree):
        if mod not in ('os', 'sys', 'traceback'):
            out.append(u'script.py:{0}: top-level import of {1}'.format(ln, mod))
    if 'psa_main.main(__revit__)' not in files['script.py']:
        out.append(u'script.py does not hand __revit__ to psa_main.main')
    return out


@rule
def rule_handlers_through_ui_safe(files):
    """A WPF handler that throws quietly is a dead button."""
    out = []
    for name in py_files(files):
        for ln, line in enumerate(files[name].splitlines(), 1):
            m = re.search(r'\.(\w+)\s*\+=\s*(.+)$', line)
            if not m or m.group(1) not in WPF_EVENTS:
                continue
            if 'uiapp.' in line:
                continue            # a Revit event, hooked once with its own try/except
            if not m.group(2).strip().startswith('ui_safe('):
                out.append(u'{0}:{1}: {2} handler not wrapped in ui_safe'.format(
                    name, ln, m.group(1)))
    return out


@rule
def rule_no_duplicate_definitions(files):
    out = []
    for name, tree in trees(files).items():
        scopes = [tree] + [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
        for scope in scopes:
            seen = set()
            for node in scope.body:
                if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                    if node.name in seen:
                        out.append(u'{0}:{1}: {2} defined twice'.format(name, node.lineno,
                                                                      node.name))
                    seen.add(node.name)
    return out


@rule
def rule_globals_exist(files):
    """Every bare name a function reaches for exists in its module."""
    import builtins
    out = []
    for name, tree in trees(files).items():
        defined = set(dir(builtins)) | {'__file__', '__name__', '__revit__', 'unicode'}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                defined.add(node.name)
            elif isinstance(node, ast.Import):
                for a in node.names:
                    defined.add((a.asname or a.name).split('.')[0])
            elif isinstance(node, ast.ImportFrom):
                for a in node.names:
                    defined.add(a.asname or a.name)
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                defined.add(node.id)
            elif isinstance(node, ast.arg):
                defined.add(node.arg)
            elif isinstance(node, ast.ExceptHandler) and node.name:
                defined.add(node.name)
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                if node.id not in defined:
                    out.append(u'{0}:{1}: {2} is not defined'.format(name, node.lineno, node.id))
    return out


@rule
def rule_names_and_version(files):
    """The ribbon name is unique and RevoBIM-prefixed, the folder matches the
    tool name, the version is in the changelog and shown on both windows."""
    out = []
    core_src = files['psa_core.py']
    tool = re.search(r'TOOL_NAME = u"([^"]+)"', core_src).group(1)
    ribbon = re.search(r'RIBBON_NAME = u"([^"]+)"', core_src).group(1)
    version = re.search(r'__version__ = "([0-9.]+)"', core_src).group(1)
    if not ribbon.startswith('RevoBIM ') or not ribbon.endswith(tool):
        out.append(u'ribbon name {0} is not "RevoBIM {1}"'.format(ribbon, tool))
    title = re.search(r'^title:\s*(.+)$', files['bundle.yaml'], re.M)
    if title is None or title.group(1).strip() != ribbon:
        out.append(u'bundle.yaml title is not {0}'.format(ribbon))
    if files['__folder__'] != tool + '.pushbutton':
        out.append(u'folder {0} is not "{1}.pushbutton"'.format(files['__folder__'], tool))
    if u'## ' + version not in files['CHANGELOG.md'] and u'v' + version not in files['CHANGELOG.md']:
        out.append(u'CHANGELOG.md has no entry for {0}'.format(version))
    for n in LAYOUTS:
        if 'x:Name="VersionText"' not in files[n]:
            out.append(u'{0}: no VersionText top right'.format(n))
        if tool not in files[n]:
            out.append(u'{0}: header does not name the tool'.format(n))
        if 'x:Name="ThemeButton"' not in files[n] or 'x:Name="RevoLogo"' not in files[n]:
            out.append(u'{0}: no theme chip or RevoBIM logo'.format(n))
    return out


@rule
def rule_egg_attached(files):
    src = _code_only(files['psa_ui.py'])
    out = []
    if 'from revobim.egg import egg_hook' not in files['psa_ui.py']:
        out.append(u'psa_ui.py: egg_hook not imported')
    if 'attach_to_window(window, theme=palette, tool=core.TOOL_NAME)' not in src:
        out.append(u'psa_ui.py: attach_to_window not called with tool=')
    if 'except TypeError' not in src:
        out.append(u'psa_ui.py: no fallback for an older attach_to_window')
    if 'attach(logo_host, host_window=window, theme=palette)' not in src:
        out.append(u'psa_ui.py: no attach(logo_host, ...) fallback')
    if not re.search(r'(?<!def )\battach_egg\(window', src):
        out.append(u'psa_ui.py: the windows never call attach_egg')
    return out


@rule
def rule_no_shared_files_shipped(files):
    """startup.py, lib\\revobim\\__init__.py and a Routines bundle.yaml are
    shared and singular: shipping one overwrites whatever is there."""
    out = []
    for rel in files['__tree__']:
        norm = rel.replace('\\', '/')
        if norm in [s.replace('\\', '/') for s in SHARED_FILES]:
            out.append(u'delivery ships {0}'.format(rel))
        if norm.startswith('hooks/'):
            out.append(u'delivery ships a hook: {0}'.format(rel))
        parts = norm.split('/')
        if parts[-1] == 'bundle.yaml' and not any(p.endswith('.pushbutton') for p in parts):
            out.append(u'delivery ships a panel or pulldown bundle.yaml: {0}'.format(rel))
    return out


@rule
def rule_modeless_kept_alive(files):
    """A modeless window needs __persistentengine__ in script.py, its
    ExternalEvent and handler parked, and every model write routed through
    the event. Without the engine the window opens with every handler dead."""
    out = []
    main_src = _code_only(files['psa_main.py'])
    if 'ExternalEvent.Create' not in main_src:
        return out
    if not re.search(r'^__persistentengine__\s*=\s*True', files['script.py'], re.M):
        out.append(u'script.py: modeless window without __persistentengine__ = True')
    if not re.search(r'PARKED\.update\(', main_src) or 'rv.park_window(' not in main_src:
        out.append(u'psa_main.py: window, event and handler not parked')
    if 'window.Show()' not in _code_only(files['psa_ui.py']):
        out.append(u'psa_ui.py: the modeless window is never shown modeless')
    if 'arm_alive_check()' not in main_src:
        out.append(u'psa_main.py: no dead-engine note armed for the modeless window')
    if not re.search(r'(?<!def )\bmark_alive\(\)', _code_only(files['psa_ui.py'])):
        out.append(u'psa_ui.py: no handler clears the dead-engine note')
    return out


@rule
def rule_never_wait_for_the_event(files):
    """Revit raises an ExternalEvent on the thread the window lives on, so
    waiting for it from the window is a deadlock that looks like a dead tool."""
    out = []
    for name in py_files(files):
        code = _code_only(files[name])
        for word in ('time.sleep', '.WaitOne(', 'DoEvents', '.Join('):
            if word in code:
                out.append(u'{0}: {1} - never wait for the ExternalEvent'.format(name, word))
    return out


# ---------- loading against the stub API ----------

class _Stub(object):
    def __init__(self, *a, **k):
        pass

    def __call__(self, *a, **k):
        return _Stub()

    def __getattr__(self, name):
        return _Stub()

    def __iadd__(self, other):
        return self


class _Finder(object):
    """Serves System.* / Autodesk.* / clr, and refuses a .NET namespace whose
    assembly nothing has referenced yet - which is what IronPython does."""

    def __init__(self):
        self.referenced = set()

    def find_module(self, fullname, path=None):
        top = fullname.split('.')[0]
        if fullname == 'clr' or top in ('System', 'Autodesk'):
            return self
        return None

    def find_spec(self, fullname, path=None, target=None):
        if self.find_module(fullname) is None:
            return None
        return importlib.util.spec_from_loader(fullname, self)

    def create_module(self, spec):
        return self.load_module(spec.name)

    def exec_module(self, module):
        pass

    def load_module(self, fullname):
        if fullname in sys.modules:
            return sys.modules[fullname]
        mod = types.ModuleType(fullname)
        mod.__path__ = []
        if fullname == 'clr':
            mod.AddReference = lambda name: self.referenced.add(name)
        else:
            known = [ns for ns in API if ns == fullname or ns.startswith(fullname + '.')]
            if not known:
                raise ImportError(u'No module named {0}'.format(fullname))
            need = ASSEMBLY_FOR.get(fullname)
            if need is not None and need not in self.referenced:
                raise ImportError(u'{0}: assembly {1} not referenced'.format(fullname, need))
            for n in API.get(fullname, []):
                setattr(mod, n, type(n, (_Stub,), {}))
        sys.modules[fullname] = mod
        return mod


@rule
def rule_modules_load(files):
    """Every module loads against the stub Revit and .NET API, in a fresh
    engine, from copies of the files."""
    import tempfile
    folder = tempfile.mkdtemp()
    for name in py_files(files):
        handle = io.open(os.path.join(folder, name), 'w', encoding='utf-8')
        try:
            handle.write(files[name])
        finally:
            handle.close()
    out = []
    for target in LOAD_ORDER:
        saved_modules = dict(sys.modules)
        saved_path = list(sys.path)
        finder = _Finder()
        sys.meta_path.insert(0, finder)
        sys.path.insert(0, folder)
        for k in list(sys.modules):
            if k.startswith('psa_') or k == 'clr' or k.split('.')[0] in ('System', 'Autodesk'):
                del sys.modules[k]
        try:
            __import__(target)
        except Exception as ex:
            out.append(u'{0} does not load: {1}: {2}'.format(target, type(ex).__name__, ex))
        finally:
            sys.meta_path.remove(finder)
            sys.path[:] = saved_path
            for k in list(sys.modules):
                if k not in saved_modules:
                    del sys.modules[k]
            sys.modules.update(saved_modules)
    try:
        compile(files['script.py'], 'script.py', 'exec')
    except SyntaxError as ex:
        out.append(u'script.py: {0}'.format(ex))
    return out


# ====================== selftest ======================

def _sub(name, old, new, count=1):
    def breaker(files):
        if old not in files[name]:
            raise AssertionError(u'breakage for {0} no longer applies: {1!r}'.format(name, old))
        files[name] = files[name].replace(old, new, count)
    return breaker


def _add_tree(rel):
    def breaker(files):
        files['__tree__'] = list(files['__tree__']) + [rel]
    return breaker


BREAKAGES = [
    ('rule_xaml_parses', _sub('PipeSlopeAssigner.xaml', '</Window>', '')),
    ('rule_no_double_hyphen_in_xaml_comments',
     _sub('PipeSlopeResults.xaml', '<Border', '<!-- ---- banner ---- --><Border')),
    ('rule_no_static_resource',
     _sub('PipeSlopeAssigner.xaml', 'DynamicResource BgCard', 'StaticResource BgCard')),
    ('rule_no_baseline',
     _sub('PipeSlopeAssigner.xaml', '<TextBlock ', '<TextBlock VerticalAlignment="Baseline" ')),
    ('rule_dynamic_keys_exist',
     _sub('PipeSlopeResults.xaml', 'DynamicResource Text}', 'DynamicResource Textt}')),
    ('rule_palettes_match_theme', _sub('psa_theme.py', "'Red': '#C0392B',", '')),
    ('rule_resource_references_exist', _sub('psa_ui.py', "'bad': 'Red'", "'bad': 'Crimson'")),
    ('rule_style_target_types',
     _sub('PipeSlopeAssigner.xaml', 'Style="{DynamicResource PsaCheck}"',
          'Style="{DynamicResource PsaRadio}"')),
    ('rule_find_name_matches', _sub('psa_ui.py', "find('DirAutoHint')", "find('DirHint')")),
    ('rule_find_name_matches', _sub('psa_ui.py', "find('Slope{0}'", "find('Tile{0}'")),
    ('rule_no_fstrings_or_print',
     _sub('psa_core.py', "return u'1:{0}'.format(int(n))", "return f'1:{int(n)}'")),
    ('rule_no_fstrings_or_print', _sub('psa_main.py', '    started = time.time()',
                                       '    print(1)\n    started = time.time()')),
    ('rule_integer_value_only_in_helper',
     _sub('psa_revit.py', 'return eid_value(el.Id)', 'return el.Id.IntegerValue')),
    ('rule_no_system_uri',
     _sub('psa_ui.py', 'from System.IO import MemoryStream, File',
          'from System.IO import MemoryStream, File\nfrom System import Uri')),
    ('rule_ascii_only', _sub('psa_core.py', u"u' \\u00d8", u"u' \u00d8")),
    ('rule_clr_first', _sub('psa_ui.py', 'import psa_clr  # noqa', 'import os as _os  # noqa')),
    ('rule_modules_load', _sub('psa_ui.py', 'import psa_clr  # noqa', 'import os as _os  # noqa')),
    ('rule_names_in_their_namespace',
     _sub('psa_revit.py', 'from Autodesk.Revit.DB.Plumbing import Pipe',
          'from Autodesk.Revit.DB.Plumbing import Pipe, RoutingPreferenceRuleGroupType')),
    ('rule_modules_load',
     _sub('psa_revit.py', 'from Autodesk.Revit.DB.Plumbing import Pipe',
          'from Autodesk.Revit.DB.Plumbing import Pipe, RoutingPreferenceRuleGroupType')),
    ('rule_script_is_thin', _sub('script.py', 'import traceback', 'import traceback\nimport psa_ui')),
    ('rule_handlers_through_ui_safe',
     _sub('psa_ui.py', "self.apply_button.Click += ui_safe(self.on_apply, self.chrome.status)",
          "self.apply_button.Click += self.on_apply")),
    ('rule_no_duplicate_definitions',
     _sub('psa_core.py', 'def fmt_pt(pt):', 'def node_text(key):\n    return 0\n\n\ndef fmt_pt(pt):')),
    ('rule_globals_exist', _sub('psa_main.py', 'return core.ft_to_mm(moved)',
                                'return core.ft_to_mm(moved_mm)')),
    ('rule_names_and_version', _sub('bundle.yaml', 'title: RevoBIM Pipe Slope Assigner',
                                    'title: Pipe Slope Assigner')),
    ('rule_names_and_version', _sub('psa_core.py', '__version__ = "1.2.0"',
                                    '__version__ = "9.9.9"')),
    ('rule_egg_attached', _sub('psa_ui.py', 'attach_egg(window, self.mode',
                               'None and (window, self.mode')),
    ('rule_modeless_kept_alive', _sub('script.py', '__persistentengine__ = True',
                                      '__persistentengine__ = False')),
    ('rule_modeless_kept_alive', _sub('psa_main.py', 'PARKED.update(', 'dict(')),
    ('rule_modeless_kept_alive', _sub('psa_ui.py', '    mark_alive()\n        try:',
                                      '        try:')),
    ('rule_never_wait_for_the_event',
     _sub('psa_main.py', "        answer = event.Raise()",
          "        answer = event.Raise()\n        time.sleep(0.5)")),
    ('rule_no_shared_files_shipped', _add_tree('startup.py')),
    ('rule_no_shared_files_shipped',
     _add_tree(os.path.join('RevoBIM PY.tab', 'Coordination.panel', 'Routines.pulldown',
                            'bundle.yaml'))),
]


def run(files):
    results = {}
    for fn in RULES:
        try:
            results[fn.__name__] = fn(files)
        except Exception as ex:
            results[fn.__name__] = [u'rule crashed: {0}: {1}'.format(type(ex).__name__, ex)]
    return results


def selftest():
    base = read_all()
    clean = run(base)
    ok = True
    if any(clean.values()):
        print(u'The shipped files do not pass - fix those first.')
        return False
    covered = set()
    for name, breaker in BREAKAGES:
        files = dict(base)
        try:
            breaker(files)
        except AssertionError as ex:
            print(u'  STALE   {0}: {1}'.format(name, ex))
            ok = False
            continue
        fn = [r for r in RULES if r.__name__ == name][0]
        try:
            problems = fn(files)
        except Exception as ex:
            problems = [u'crashed: {0}'.format(ex)]
        caught = bool(problems)
        ok = ok and caught
        covered.add(name)
        print(u'  {0}  {1}{2}'.format(u'caught' if caught else u'MISSED', name,
                                      u'  - ' + problems[0] if caught else u''))
    for fn in RULES:
        if fn.__name__ not in covered:
            print(u'  UNTESTED {0}'.format(fn.__name__))
            ok = False
    return ok


def main(argv):
    if '--selftest' in argv:
        print(u'Breaking each rule on purpose:')
        good = selftest()
        print(u'Every rule caught its breakage.' if good else u'SELFTEST FAILED.')
        return 0 if good else 1
    results = run(read_all())
    bad = 0
    for fn in RULES:
        problems = results[fn.__name__]
        bad += len(problems)
        print(u'  {0}  {1}'.format(u'FAIL' if problems else u'ok  ', fn.__name__))
        for p in problems:
            print(u'        ' + p)
    print(u'{0} rules, {1} problem(s).'.format(len(RULES), bad))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
