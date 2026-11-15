# -*- coding: utf-8 -*-
"""Unhide in View - static bench. Plain CPython 3, no Revit.

    python import_check.py             run every rule against this folder
    python import_check.py --selftest  break a copy of the tool on purpose,
                                       once per rule, and prove the rule
                                       catches it

Every rule here exists because its failure has shipped in this extension
before - most of them as a blank white pyRevit window with no traceback.
"""
import ast
import os
import re
import shutil
import sys
import tempfile
import types
import xml.dom.minidom

HERE = os.path.dirname(os.path.abspath(__file__))

LAYOUT = 'UnhideInView.xaml'
THEME = 'Theme.xaml'
TOOL_MODULES = ['uiv_clr.py', 'uiv_core.py', 'uiv_revit.py', 'uiv_ui.py', 'uiv_window.py', 'script.py']
NET_MODULES = ['uiv_revit.py', 'uiv_ui.py', 'uiv_window.py']

# Each .NET namespace the tool imports -> the assemblies that provide it.
# A stub API cannot catch a missing clr.AddReference (under CPython a name
# either resolves or not) - this table is the only thing that can.
# Autodesk.* is left out: pyRevit has RevitAPI / RevitAPIUI loaded already.
ASSEMBLY_FOR = {
    'System': ['mscorlib', 'System'],
    'System.Collections.Generic': ['mscorlib', 'System'],
    'System.Data': ['System.Data'],
    'System.IO': ['mscorlib'],
    'System.Xml': ['System.Xml'],
    'System.Windows': ['PresentationFramework', 'PresentationCore', 'WindowsBase'],
    'System.Windows.Controls': ['PresentationFramework'],
    'System.Windows.Controls.Primitives': ['PresentationFramework'],
    'System.Windows.Data': ['PresentationFramework'],
    'System.Windows.Input': ['PresentationCore'],
    'System.Windows.Media': ['PresentationCore'],
    'System.Windows.Media.Imaging': ['PresentationCore'],
    'System.Windows.Threading': ['WindowsBase'],
    'System.Windows.Interop': ['PresentationFramework'],
    'System.Windows.Markup': ['PresentationFramework', 'System.Xaml'],
    'System.Windows.Forms': ['System.Windows.Forms'],
}


def read(root, name):
    with open(os.path.join(root, name), encoding='utf-8') as f:
        return f.read()


def tree(root, name):
    return ast.parse(read(root, name), filename=name)


def net_imports(src):
    """[(line number, namespace)] for every System.* / Autodesk.* import."""
    out = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split('.')[0] in ('System', 'Autodesk'):
                out.append((node.lineno, node.module))
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split('.')[0] in ('System', 'Autodesk'):
                    out.append((node.lineno, a.name))
    return out


# =====================================================================
# Rules - each returns a list of problems
# =====================================================================

RULES = []


def rule(fn):
    RULES.append(fn)
    return fn


@rule
def xaml_parses(root):
    errs = []
    for name in (LAYOUT, THEME):
        text = read(root, name)
        for body in re.findall(r'<!--(.*?)-->', text, re.S):
            if '--' in body:
                errs.append(name + ': "--" inside a comment (draw banners with =)')
        try:
            xml.dom.minidom.parseString(text.encode('utf-8'))
        except Exception as ex:
            errs.append('{0} does not parse: {1}'.format(name, ex))
    return errs


@rule
def clr_module_first(root):
    errs = []
    for name in NET_MODULES:
        src = read(root, name)
        first_net = min([ln for ln, _ns in net_imports(src)] or [10 ** 6])
        m = None
        for node in ast.parse(src).body:
            if isinstance(node, ast.Import) and any(a.name == 'uiv_clr' for a in node.names):
                m = node.lineno
                break
        if m is None:
            errs.append(name + ' never imports uiv_clr at top level')
        elif m > first_net:
            errs.append('{0} reaches .NET on line {1} before importing uiv_clr on line {2}'.format(
                name, first_net, m))
    return errs


@rule
def core_is_pure(root):
    src = read(root, 'uiv_core.py')
    errs = []
    for node in ast.walk(ast.parse(src)):
        mods = []
        if isinstance(node, ast.Import):
            mods = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods = [node.module]
        for m in mods:
            if m.split('.')[0] in ('System', 'Autodesk', 'clr', 'uiv_clr'):
                errs.append('uiv_core imports ' + m + ' - it must run on the bench with no .NET')
    return errs


def referenced_assemblies(root):
    for node in tree(root, 'uiv_clr.py').body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == 'ASSEMBLIES' for t in node.targets):
            return [e.value for e in node.value.elts]
    return []


@rule
def assemblies_referenced(root):
    refs = set(referenced_assemblies(root))
    errs = []
    for name in TOOL_MODULES:
        for ln, ns in net_imports(read(root, name)):
            if ns.startswith('Autodesk'):
                continue
            need = ASSEMBLY_FOR.get(ns)
            if need is None:
                errs.append('{0}:{1} imports {2} - add it to ASSEMBLY_FOR'.format(name, ln, ns))
            elif not refs.intersection(need):
                errs.append('{0}:{1} imports {2} but uiv_clr references none of {3}'.format(
                    name, ln, ns, need))
    return errs


@rule
def loads_on_stub_api(root):
    """Every module loads against stubs that declare each name only in its
    real namespace - a mis-namespaced import fails here, not in Revit."""
    sys.path.insert(0, HERE)
    import bench_stubs
    bench_stubs.install()
    errs = []
    saved = {}
    for name in [m[:-3] for m in TOOL_MODULES if m != 'script.py']:
        saved[name] = sys.modules.pop(name, None)
    try:
        for fname in [m for m in TOOL_MODULES if m != 'script.py']:
            name = fname[:-3]
            path = os.path.join(root, fname)
            mod = types.ModuleType(name)
            mod.__file__ = path
            sys.modules[name] = mod
            try:
                exec(compile(read(root, fname), path, 'exec'), mod.__dict__)
            except Exception as ex:
                errs.append('{0} fails to load: {1}: {2}'.format(fname, type(ex).__name__, ex))
    finally:
        for name, mod in saved.items():
            sys.modules.pop(name, None)
            if mod is not None:
                sys.modules[name] = mod
        sys.path.remove(HERE)
    return errs


@rule
def no_static_resource_in_layout(root):
    if 'StaticResource' in read(root, LAYOUT):
        return [LAYOUT + ' uses StaticResource - Theme.xaml is merged after the layout parses']
    return []


def theme_keys(root):
    dom = xml.dom.minidom.parseString(read(root, THEME).encode('utf-8'))
    keys = {}
    for el in dom.getElementsByTagName('*'):
        k = el.getAttribute('x:Key')
        if k:
            keys[k] = el
    return keys


@rule
def resource_keys_exist(root):
    keys = theme_keys(root)
    errs = []
    for name in (LAYOUT, THEME):
        for k in re.findall(r'\{(?:Dynamic|Static)Resource (\w+)\}', read(root, name)):
            if k not in keys:
                errs.append('{0} uses resource {1} that Theme.xaml does not define'.format(name, k))
    for name in TOOL_MODULES:
        src = read(root, name)
        for k in re.findall(r"SetResourceReference\([^,]+,\s*'(\w+)'\)", src) + \
                re.findall(r"TryFindResource\('(\w+)'\)", src):
            if k not in keys:
                errs.append('{0} asks for resource {1} that Theme.xaml does not define'.format(name, k))
    return errs


@rule
def styles_match_targets(root):
    keys = theme_keys(root)
    dom = xml.dom.minidom.parseString(read(root, LAYOUT).encode('utf-8'))
    errs = []
    for el in dom.getElementsByTagName('*'):
        st = el.getAttribute('Style')
        m = re.match(r'\{DynamicResource (\w+)\}', st or '')
        if not m:
            continue
        style = keys.get(m.group(1))
        if style is None:
            continue
        target = style.getAttribute('TargetType')
        if target and target != el.tagName:
            errs.append('{0} has Style {1} whose TargetType is {2}'.format(el.tagName, m.group(1), target))
    return errs


def window_names(root):
    for node in ast.walk(tree(root, 'uiv_window.py')):
        if isinstance(node, ast.ClassDef) and node.name == 'UnhideWindow':
            for item in node.body:
                if isinstance(item, ast.Assign) and any(
                        isinstance(t, ast.Name) and t.id == 'NAMES' for t in item.targets):
                    return [e.value for e in item.value.elts]
    return []


@rule
def names_exist(root):
    xnames = set(re.findall(r'x:Name="(\w+)"', read(root, LAYOUT)))
    errs = ['NAMES lists {0} - no x:Name in the layout'.format(n)
            for n in window_names(root) if n not in xnames]
    for name in TOOL_MODULES:
        for n in re.findall(r"FindName\('(\w+)'\)", read(root, name)):
            if n not in xnames:
                errs.append('{0} FindName({1}) - no x:Name in the layout'.format(name, n))
    return errs


@rule
def banned_constructs(root):
    errs = []
    for name in TOOL_MODULES:
        src = read(root, name)
        try:
            src.encode('ascii')
        except UnicodeEncodeError:
            errs.append(name + ' has non-ASCII characters - use \\u escapes in u\'\' literals')
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.JoinedStr):
                errs.append('{0}:{1} f-string (IronPython 2.7 has none)'.format(name, node.lineno))
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'print':
                errs.append('{0}:{1} print'.format(name, node.lineno))
            elif isinstance(node, ast.Attribute) and node.attr == 'IntegerValue':
                errs.append('{0}:{1} .IntegerValue - removed in Revit 2026, use eid_value()'.format(
                    name, node.lineno))
            elif isinstance(node, ast.Nonlocal):
                errs.append('{0}:{1} nonlocal (IronPython 2.7)'.format(name, node.lineno))
            elif isinstance(node, ast.ImportFrom) and node.module == 'System' and any(
                    a.name == 'Uri' for a in node.names):
                errs.append('{0}:{1} System.Uri - moved assembly in Revit 2025'.format(name, node.lineno))
            elif isinstance(node, ast.Attribute) and node.attr == 'UriSource':
                # checked on the code, not the text: a docstring saying
                # "never UriSource" must not trip it (or pass it)
                errs.append('{0}:{1} UriSource - load images from bytes'.format(name, node.lineno))
    return errs


@rule
def no_duplicate_definitions(root):
    errs = []
    for name in TOOL_MODULES:
        t = tree(root, name)
        scopes = [('module', t.body)] + [(n.name, n.body) for n in ast.walk(t) if isinstance(n, ast.ClassDef)]
        for scope, body in scopes:
            seen = set()
            for item in body:
                if isinstance(item, (ast.FunctionDef, ast.ClassDef)):
                    if item.name in seen:
                        errs.append('{0}: {1} defined twice in {2} - the second silently wins'.format(
                            name, item.name, scope))
                    seen.add(item.name)
    return errs


def load_core(root):
    mod = types.ModuleType('uiv_core_check')
    exec(compile(read(root, 'uiv_core.py'), 'uiv_core.py', 'exec'), mod.__dict__)
    return mod


@rule
def palettes_match_theme(root):
    core = load_core(root)
    keys = theme_keys(root)
    brushes = set(k for k, el in keys.items() if el.tagName == 'SolidColorBrush')
    errs = []
    for name, pal in core.PALETTES.items():
        if set(pal.keys()) != brushes:
            missing = sorted(brushes - set(pal.keys()))
            extra = sorted(set(pal.keys()) - brushes)
            errs.append('palette {0} differs from Theme.xaml brushes: missing {1}, extra {2}'.format(
                name, missing, extra))
    return errs


@rule
def script_is_thin(root):
    src = read(root, 'script.py')
    errs = []
    if not re.search(r'^__persistentengine__\s*=\s*True', src, re.M):
        errs.append('script.py: __persistentengine__ = True missing - a modeless window needs it')
    if 'AddReference' in src:
        errs.append('script.py: clr.AddReference belongs in uiv_clr')
    allowed = set(['os', 'sys', 'traceback', 'uiv_clr', 'uiv_core', 'uiv_window'])
    for node in ast.parse(src).body:
        names = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module]
        for n in names:
            if n not in allowed:
                errs.append('script.py imports {0} at top level - keep the loader thin'.format(n))
    return errs


@rule
def changelog_has_version(root):
    core = load_core(root)
    if ('## ' + core.__version__) not in read(root, 'CHANGELOG.md'):
        return ['CHANGELOG.md has no entry for ' + core.__version__]
    return []


@rule
def easter_egg_wired(root):
    ui = read(root, 'uiv_ui.py')
    errs = []
    for word in ("'attach_to_window'", "'attach'", "'launch'"):
        if word not in ui:
            errs.append('uiv_ui.attach_egg no longer tries ' + word)
    if 'ui.attach_egg(' not in read(root, 'uiv_window.py'):
        errs.append('the window never attaches the easter egg')
    return errs


@rule
def enums_looked_up_late(root):
    errs = []
    for name in TOOL_MODULES:
        for node in ast.walk(tree(root, name)):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and \
                    node.value.id in ('BuiltInParameter', 'BuiltInCategory'):
                errs.append('{0}:{1} {2}.{3} - look members up by name at call time'.format(
                    name, node.lineno, node.value.id, node.attr))
    return errs


@rule
def raise_status_read(root):
    errs = []
    for name in TOOL_MODULES:
        for node in ast.walk(tree(root, name)):
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and \
                    isinstance(node.value.func, ast.Attribute) and node.value.func.attr == 'Raise':
                errs.append('{0}:{1} ExternalEvent.Raise() status ignored'.format(name, node.lineno))
    return errs


def window_class(root):
    for node in ast.walk(tree(root, 'uiv_window.py')):
        if isinstance(node, ast.ClassDef) and node.name == 'UnhideWindow':
            return node
    return None


@rule
def handlers_exist(root):
    cls = window_class(root)
    methods = set(f.name for f in cls.body if isinstance(f, ast.FunctionDef))
    attrs = set(f.target.id for f in cls.body if isinstance(f, ast.AnnAssign)) | set(
        t.id for f in cls.body if isinstance(f, ast.Assign) for t in f.targets if isinstance(t, ast.Name))
    assigned = set()
    for node in ast.walk(cls):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and \
                node.value.id == 'self' and isinstance(node.ctx, ast.Store):
            assigned.add(node.attr)
    errs = []
    for node in ast.walk(cls):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and \
                node.value.id == 'self' and isinstance(node.ctx, ast.Load):
            if node.attr not in methods and node.attr not in assigned and node.attr not in attrs:
                errs.append('uiv_window:{0} self.{1} is neither a method nor ever set'.format(
                    node.lineno, node.attr))
    return errs


@rule
def window_flags(root):
    errs = []
    lay = read(root, LAYOUT)
    if 'AllowsTransparency="True"' in lay and 'WindowStyle="None"' not in lay:
        errs.append('AllowsTransparency needs WindowStyle="None" or the window will not open')
    for name in (LAYOUT, THEME):
        if 'Baseline' in read(root, name):
            errs.append(name + ': Baseline alignment makes XamlReader.Load throw silently')
    return errs


@rule
def init_reads_before_writes(root):
    """Replay __init__ in source order, following every self.method() call
    into its body (not into nested functions or lambdas - those are handlers
    being wired, not work being done). Reading an attribute nothing has set
    yet is the bug that shipped as a dead window three calls deep."""
    cls = window_class(root)
    methods = dict((f.name, f) for f in cls.body if isinstance(f, ast.FunctionDef))
    assigned = set(t.id for f in cls.body if isinstance(f, ast.Assign)
                   for t in f.targets if isinstance(t, ast.Name))     # class attributes
    errs = []

    def store(target):
        if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == 'self':
            assigned.add(target.attr)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for e in target.elts:
                store(e)
        elif isinstance(target, ast.Attribute):
            visit(target.value, [])
        elif isinstance(target, ast.Subscript):
            visit(target.value, [])
            visit(target.slice, [])

    def visit(node, stack):
        if isinstance(node, (ast.FunctionDef, ast.Lambda)):
            return
        if isinstance(node, ast.Assign):
            visit(node.value, stack)
            for t in node.targets:
                store(t)
            return
        if isinstance(node, ast.AugAssign):
            visit(node.value, stack)
            if isinstance(node.target, ast.Attribute):
                visit(ast.Attribute(value=node.target.value, attr=node.target.attr, ctx=ast.Load()), stack)
            store(node.target)
            return
        if isinstance(node, ast.Call):
            visit(node.func, stack)
            for a in node.args:
                visit(a, stack)
            for k in node.keywords:
                visit(k.value, stack)
            f = node.func
            if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == 'self' \
                    and f.attr in methods and f.attr not in stack:
                for stmt in methods[f.attr].body:
                    visit(stmt, stack + [f.attr])
            return
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == 'self':
            if isinstance(node.ctx, ast.Load) and node.attr not in assigned and node.attr not in methods:
                errs.append('{0} reads self.{1} before anything sets it (line {2})'.format(
                    ' -> '.join(stack), node.attr, node.lineno))
            return
        for child in ast.iter_child_nodes(node):
            visit(child, stack)

    for stmt in methods['__init__'].body:
        visit(stmt, ['__init__'])
    seen = []
    for e in errs:
        if e not in seen:
            seen.append(e)
    return seen


@rule
def nothing_waits_on_revit(root):
    errs = []
    for name in NET_MODULES:
        src = read(root, name)
        for bad in ('time.sleep(', '.WaitOne(', 'Thread.Sleep('):
            if bad in src:
                errs.append('{0}: {1} - never block the thread an ExternalEvent runs on'.format(name, bad))
    return errs


@rule
def no_shared_files_shipped(root):
    errs = []
    for bad in ('startup.py', 'hooks', '__init__.py', 'lib'):
        if os.path.exists(os.path.join(root, bad)):
            errs.append('the tool folder ships {0} - shared files go as banded fragments'.format(bad))
    return errs


@rule
def shrink_drawer_wired(root):
    """Every window gets the shrink-to-taskbar drawer, and it is wired."""
    errs = []
    lay = read(root, LAYOUT)
    m_shrink = re.search(r'<Button x:Name="ShrinkBtn"[^>]*Style="\{DynamicResource RbShrinkButton\}"', lay)
    if not m_shrink:
        errs.append(LAYOUT + ': no ShrinkBtn styled RbShrinkButton in the header')
    else:
        full = lay.find('x:Name="FullScreenBtn"')
        close = lay.find('x:Name="CloseBtn"')
        if not (0 <= m_shrink.start() < full < close):
            errs.append(LAYOUT + ': ShrinkBtn belongs top right, before full screen and close')
    theme = read(root, THEME)
    m = re.search(r'<Style x:Key="RbShrinkButton".*?</Style>', theme, re.S)
    if not m:
        errs.append(THEME + ': no RbShrinkButton style')
    else:
        st = m.group(0)
        if not re.search(r'<Trigger Property="Tag" Value="shrunk">', st):
            errs.append(THEME + ': RbShrinkButton has no Tag="shrunk" trigger - the arrow never turns')
        if '{DynamicResource Green}' not in st:
            errs.append(THEME + ': the expand arrow is not the palette green')
    win = read(root, 'uiv_window.py')
    t = ast.parse(win)
    for cls in [n for n in ast.walk(t) if isinstance(n, ast.ClassDef)]:
        src = ast.get_source_segment(win, cls) or ''
        if 'ui.load_window(' in src and 'ui.WindowDrawer(' not in src:
            errs.append('uiv_window: {0} builds a window with no WindowDrawer'.format(cls.name))
    if not re.search(r"c\['ShrinkBtn'\]\.Click \+= h\(lambda s, e: self\.drawer\.toggle\(\)\)", win):
        errs.append('uiv_window: ShrinkBtn is drawn but never wired to the drawer')
    if 'self.drawer.on_header_down(e)' not in win:
        errs.append('uiv_window: header clicks never reach the drawer (drag / double-click the bar)')
    if not re.search(r'ctrl and shift and e\.Key == Key\.H', win):
        errs.append('uiv_window: Ctrl+Shift+H does not toggle the drawer')
    if 'self.drawer.true_bounds()' not in win:
        errs.append('uiv_window: closing while shrunk would save the bar size')
    return errs


@rule
def animation_released(root):
    """An animation holds its end value over every later assignment: any
    BeginAnimation must be released with BeginAnimation(prop, None)."""
    errs = []
    for name in TOOL_MODULES:
        starts = 0
        releases = 0
        for node in ast.walk(tree(root, name)):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and \
                    node.func.attr == 'BeginAnimation' and len(node.args) >= 2:
                a = node.args[1]
                if isinstance(a, ast.Constant) and a.value is None:
                    releases += 1
                else:
                    starts += 1
        if starts and not releases:
            errs.append('{0}: BeginAnimation is never released - the window could never be '
                        'moved or resized again'.format(name))
    return errs


# =====================================================================
# Runner and selftest
# =====================================================================

def run(root, only=None, quiet=False):
    problems = []
    for fn in RULES:
        if only is not None and fn.__name__ != only:
            continue
        try:
            errs = fn(root)
        except Exception as ex:
            errs = ['rule crashed: {0}: {1}'.format(type(ex).__name__, ex)]
        problems.extend((fn.__name__, e) for e in errs)
        if not quiet:
            print('{0}  {1}'.format('PASS' if not errs else 'FAIL', fn.__name__))
            for e in errs:
                print('      ' + e)
    return problems


# (rule, file, old, new) - new file when old is None
BREAKAGES = [
    ('xaml_parses', LAYOUT, '<!-- Layout only.', '<!-- -- Layout only.'),
    ('clr_module_first', 'uiv_ui.py', 'import uiv_clr  # noqa: F401  - assembly references first, always\n', ''),
    ('core_is_pure', 'uiv_core.py', 'import os\n', 'import os\nfrom System import String\n'),
    ('assemblies_referenced', 'uiv_clr.py', "'System.Data', ", ''),
    ('loads_on_stub_api', 'uiv_window.py', '    CheckBox, Button, Control,\n)',
     '    CheckBox, Button, Control, Visibility,\n)'),
    ('no_static_resource_in_layout', LAYOUT, 'Style="{DynamicResource RbChip}" Margin="0,0,10,0"',
     'Style="{StaticResource RbChip}" Margin="0,0,10,0"'),
    ('resource_keys_exist', LAYOUT, 'Foreground="{DynamicResource Muted}" VerticalAlignment="Center"\n                         Margin="0,0,10,0"/>',
     'Foreground="{DynamicResource Mutted}" VerticalAlignment="Center"\n                         Margin="0,0,10,0"/>'),
    ('styles_match_targets', LAYOUT, '<CheckBox x:Name="DebugChk" DockPanel.Dock="Left" Content="Debug"\n                      Style="{DynamicResource RbCheck}"',
     '<CheckBox x:Name="DebugChk" DockPanel.Dock="Left" Content="Debug"\n                      Style="{DynamicResource RbButton}"'),
    ('names_exist', LAYOUT, 'x:Name="StatusText"', 'x:Name="StatusTxt"'),
    ('banned_constructs', 'uiv_core.py', "TOOL_NAME = u'Unhide in View'", "TOOL_NAME = f'Unhide in View'"),
    ('banned_constructs', 'uiv_revit.py', "        return getattr(element_id, 'IntegerValue')",
     "        return element_id.IntegerValue"),
    ('banned_constructs', 'uiv_core.py', "TOOL_NAME = u'Unhide in View'", "TOOL_NAME = u'Unhide \u2013 in View'"),
    ('banned_constructs', 'uiv_ui.py', '        bmp.StreamSource = MemoryStream(data)',
     '        bmp.UriSource = MemoryStream(data)'),
    ('no_duplicate_definitions', 'uiv_window.py', '    def _hide_confirm(self):',
     '    def _refilter_cats(self):\n        pass\n\n    def _hide_confirm(self):'),
    ('palettes_match_theme', 'uiv_core.py', "        'Disabled': '#B5B7BD',\n", ''),
    ('script_is_thin', 'script.py', '__persistentengine__ = True', '__persistentengine__ = False'),
    ('changelog_has_version', 'uiv_core.py', "__version__ = '", "__version__ = '9"),
    ('easter_egg_wired', 'uiv_ui.py', "('attach_to_window', 'attach')", "('attach',)"),
    ('enums_looked_up_late', 'uiv_revit.py', "    return getattr(BuiltInParameter, name, None)",
     "    return BuiltInParameter.VIS_GRAPHICS_MODEL"),
    ('raise_status_read', 'uiv_window.py', "            status = str(self.event.Raise())",
     "            self.event.Raise()\n            status = 'Accepted'"),
    ('handlers_exist', 'uiv_window.py', "c['RefreshBtn'].Click += h(lambda s, e: self.load())",
     "c['RefreshBtn'].Click += h(self._on_refresh)"),
    ('window_flags', LAYOUT, 'VerticalAlignment="Center" Cursor="Hand"', 'VerticalAlignment="Baseline" Cursor="Hand"'),
    ('init_reads_before_writes', 'uiv_window.py', '        self.user_jobs = 0\n        self.busy_since = 0.0\n',
     '        self.busy_since = 0.0\n'),
    ('nothing_waits_on_revit', 'uiv_window.py', '        self.runner.dispatcher = self.win.Dispatcher\n',
     '        self.runner.dispatcher = self.win.Dispatcher\n        time.sleep(0.1)\n'),
    ('no_shared_files_shipped', 'startup.py', None, '# overwrites the extension startup\n'),
    ('shrink_drawer_wired', 'uiv_window.py',
     "        self.drawer = ui.WindowDrawer(self.win, self.c['HeaderBar'], self.c['RootGrid'],\n                                      self.c['ShrinkBtn'], self.c['GripLayer'], log=self.log)\n",
     "        self.drawer = None\n"),
    ('shrink_drawer_wired', 'uiv_window.py', "        c['ShrinkBtn'].Click += h(lambda s, e: self.drawer.toggle())\n", ''),
    ('shrink_drawer_wired', THEME, '<Trigger Property="Tag" Value="shrunk">', '<Trigger Property="Tag" Value="parked">'),
    ('shrink_drawer_wired', LAYOUT, '              <Button x:Name="ShrinkBtn" Style="{DynamicResource RbShrinkButton}"\n                      ToolTip="Shrink to the bottom of the screen (Ctrl+Shift+H)"/>\n', ''),
    ('shrink_drawer_wired', 'uiv_window.py', '        if ctrl and shift and e.Key == Key.H:', '        if ctrl and e.Key == Key.H:'),
    ('shrink_drawer_wired', 'uiv_window.py', '            bounds = self.drawer.true_bounds()', '            bounds = (0, 0, self.win.Width, self.win.Height)'),
    ('animation_released', 'uiv_ui.py', "        self._slide(w.Top, self.landing_top, w.Height, self.bar_h, self._landed_parked)",
     "        w.BeginAnimation(w.TopProperty, self.landing_top)\n        self._slide(w.Top, self.landing_top, w.Height, self.bar_h, self._landed_parked)"),
]


def selftest():
    clean = run(HERE, quiet=True)
    if clean:
        print('The clean tool fails - fix that first:')
        for r, e in clean:
            print('  {0}: {1}'.format(r, e))
        return 1
    print('Clean run: all {0} rules pass'.format(len(RULES)))
    missed = 0
    for rname, fname, old, new in BREAKAGES:
        tmp = tempfile.mkdtemp(prefix='uiv_selftest_')
        try:
            for f in os.listdir(HERE):
                src = os.path.join(HERE, f)
                if os.path.isfile(src):
                    shutil.copy(src, tmp)
            path = os.path.join(tmp, fname)
            if old is None:
                with open(path, 'w', encoding='utf-8') as fh:
                    fh.write(new)
            else:
                text = read(tmp, fname)
                if old not in text:
                    print('BAD     breakage for {0} does not apply: {1!r}'.format(rname, old[:50]))
                    missed += 1
                    continue
                with open(path, 'w', encoding='utf-8') as fh:
                    fh.write(text.replace(old, new, 1))
            hits = run(tmp, only=rname, quiet=True)
            if hits:
                print('CAUGHT  {0:28s} {1}'.format(rname, hits[0][1][:90]))
            else:
                print('MISSED  {0} ({1})'.format(rname, fname))
                missed += 1
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print('{0} breakages, {1} missed'.format(len(BREAKAGES), missed))
    return 1 if missed else 0


def main(argv):
    if '--selftest' in argv:
        return selftest()
    problems = run(HERE)
    print('{0} rules, {1} problems'.format(len(RULES), len(problems)))
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
