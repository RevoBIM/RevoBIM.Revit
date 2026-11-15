# -*- coding: utf-8 -*-
"""Clash Analysis - static bench. Run under plain CPython from this folder:

    python import_check.py              run every rule against the tool
    python import_check.py --selftest   break the tool on purpose, once per
                                        breakage, and prove the rule meant to
                                        catch it does

A breakage whose anchor text is missing fails the selftest - a breakage
that never happened proves nothing. Finishes by running bench_logic.py.
"""
from __future__ import print_function

import ast
import importlib
import io
import os
import re
import shutil
import subprocess
import symtable
import sys
import tempfile
import tokenize
import xml.dom.minidom

HERE = os.path.dirname(os.path.abspath(__file__))
MODULES = ['ca_clr', 'ca_version', 'ca_core', 'ca_revit', 'ca_jobs',
           'ca_drawer', 'ca_ui']
LAYOUTS = ['ClashAnalysis.xaml', 'Prompt.xaml', 'ViewPicker.xaml']
THEME = 'Theme.xaml'
BENCH_FILES = ('import_check.py', 'bench_logic.py', 'bench_stubs.py')

# Every namespace the tool may import, and the assemblies that provide it on
# Revit 2024 (.NET 4.8) and 2025+ (.NET 8).
NAMESPACE_ASSEMBLIES = {
    'System': ['mscorlib', 'System', 'System.Runtime'],
    'System.Collections.Generic': ['mscorlib', 'System', 'System.Collections'],
    'System.Data': ['System.Data', 'System.Data.Common'],
    'System.IO': ['mscorlib', 'System.IO', 'System.Runtime'],
    'System.Windows': ['PresentationFramework', 'PresentationCore', 'WindowsBase'],
    'System.Windows.Controls': ['PresentationFramework'],
    'System.Windows.Controls.Primitives': ['PresentationFramework'],
    'System.Windows.Data': ['PresentationFramework'],
    'System.Windows.Input': ['PresentationCore', 'WindowsBase'],
    'System.Windows.Interop': ['PresentationFramework', 'PresentationCore', 'WindowsBase'],
    'System.Windows.Markup': ['PresentationFramework', 'System.Xaml'],
    'System.Windows.Media': ['PresentationCore'],
    'System.Windows.Shapes': ['PresentationFramework'],
    'System.Windows.Media.Imaging': ['PresentationCore'],
    'System.Windows.Threading': ['WindowsBase'],
    'System.Windows.Forms': ['System.Windows.Forms'],
    'Autodesk.Revit.DB': ['RevitAPI'],
    'Autodesk.Revit.DB.Structure': ['RevitAPI'],
    'Autodesk.Revit.UI': ['RevitAPIUI'],
}
PRELOADED = set(['RevitAPI', 'RevitAPIUI'])   # pyRevit has these already
MARKUP_EXTENSIONS = ('{DynamicResource', '{Binding', '{TemplateBinding',
                     '{x:Null', '{RelativeSource', '{StaticResource', '{}')
EXTRA_BUILTINS = set(['unicode', '__revit__', '__file__'])


# ======================================================================
# helpers
# ======================================================================

def src(root, name):
    with io.open(os.path.join(root, name), 'r', encoding='utf-8') as fh:
        return fh.read()


def tool_py(root):
    return sorted(f for f in os.listdir(root)
                  if f.endswith('.py') and f not in BENCH_FILES)


def tree(root, name):
    return ast.parse(src(root, name), filename=name)


def code_only(text):
    """Source with comments and string contents blanked, so a rule matching
    code can never be satisfied (or tripped) by a docstring."""
    out = []
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except Exception:
        return text
    lines = text.splitlines(True)
    blank = [list(l) for l in lines]
    for tok in tokens:
        if tok.type in (tokenize.STRING, tokenize.COMMENT):
            (sr, sc), (er, ec) = tok.start, tok.end
            for r in range(sr, er + 1):
                row = blank[r - 1]
                c0 = sc if r == sr else 0
                c1 = ec if r == er else len(row)
                for c in range(c0, c1):
                    if row[c] not in '\r\n':
                        row[c] = ' '
    for row in blank:
        out.append(''.join(row))
    return ''.join(out)


def xaml_doc(root, name):
    return xml.dom.minidom.parseString(src(root, name).encode('utf-8'))


def all_elements(node):
    for child in node.childNodes:
        if child.nodeType == child.ELEMENT_NODE:
            yield child
            for sub in all_elements(child):
                yield sub


def x_names(root, name):
    return set(re.findall(r'x:Name="([^"]+)"', src(root, name)))


def theme_keys(root):
    return set(re.findall(r'x:Key="([^"]+)"', src(root, THEME)))


def load_core(root):
    sys.path.insert(0, root)
    try:
        for key in list(sys.modules):
            if key.startswith('ca_'):
                del sys.modules[key]
        return importlib.import_module('ca_core')
    finally:
        sys.path.remove(root)


def functions(node):
    for n in ast.walk(node):
        if isinstance(n, (ast.FunctionDef,)):
            yield n


def find_def(t, cls_name, fn_name):
    for n in ast.walk(t):
        if isinstance(n, ast.ClassDef) and (cls_name is None or n.name == cls_name):
            for b in n.body:
                if isinstance(b, ast.FunctionDef) and b.name == fn_name:
                    return b
    if cls_name is None:
        for b in t.body:
            if isinstance(b, ast.FunctionDef) and b.name == fn_name:
                return b
    return None


# ======================================================================
# rules - each returns a list of problems
# ======================================================================

def rule_xaml_parses(root):
    bad = []
    for name in LAYOUTS + [THEME]:
        try:
            xaml_doc(root, name)
        except Exception as ex:
            bad.append('{0}: {1}'.format(name, ex))
    return bad


def rule_no_static_resource(root):
    return ['{0} uses StaticResource (Theme.xaml is merged after the layout '
            'is parsed)'.format(n) for n in LAYOUTS
            if 'StaticResource' in src(root, n)]


def rule_resource_keys_defined(root):
    keys = theme_keys(root)
    bad = []
    for name in LAYOUTS + [THEME]:
        for key in re.findall(r'\{DynamicResource ([A-Za-z0-9_]+)\}', src(root, name)):
            if key not in keys:
                bad.append('{0}: DynamicResource {1} is not defined'.format(name, key))
    for name in tool_py(root):
        for key in re.findall(r"SetResourceReference\([^,]+,\s*'([A-Za-z0-9_]+)'\)",
                              src(root, name)):
            if key not in keys:
                bad.append('{0}: SetResourceReference {1} is not defined'.format(name, key))
    return bad


def rule_style_targets(root):
    targets = {}
    for el in all_elements(xaml_doc(root, THEME).documentElement):
        if el.tagName == 'Style' and el.getAttribute('x:Key'):
            targets[el.getAttribute('x:Key')] = el.getAttribute('TargetType')
    bad = []
    for name in LAYOUTS:
        for el in all_elements(xaml_doc(root, name).documentElement):
            m = re.match(r'\{DynamicResource ([A-Za-z0-9_]+)\}', el.getAttribute('Style'))
            if m and targets.get(m.group(1)) != el.tagName:
                bad.append('{0}: <{1}> styled with {2} (TargetType {3})'.format(
                    name, el.tagName, m.group(1), targets.get(m.group(1))))
    return bad


def _names_tuple(t, var):
    for n in t.body:
        if isinstance(n, ast.Assign) and any(
                isinstance(x, ast.Name) and x.id == var for x in n.targets):
            return [e.value for e in n.value.elts]
    return []


def rule_findname_has_xname(root):
    t = tree(root, 'ca_ui.py')
    bad = []
    for var, layout in (('NAMES', 'ClashAnalysis.xaml'), ('PROMPT_NAMES', 'Prompt.xaml'),
                        ('PICKER_NAMES', 'ViewPicker.xaml')):
        have = x_names(root, layout)
        names = _names_tuple(t, var)
        if not names:
            bad.append('ca_ui.{0} is missing'.format(var))
        for n in names:
            if n not in have:
                bad.append('{0} looks up {1}, which {2} has no x:Name for'.format(
                    var, n, layout))
    for name in tool_py(root):
        everything = set()
        for layout in LAYOUTS:
            everything |= x_names(root, layout)
        for n in re.findall(r"FindName\('([^']+)'\)", src(root, name)):
            if n not in everything:
                bad.append('{0}: FindName({1}) has no x:Name'.format(name, n))
    return bad


def rule_python_parses(root):
    bad = []
    for name in tool_py(root):
        try:
            tree(root, name)
        except SyntaxError as ex:
            bad.append('{0}: {1}'.format(name, ex))
    return bad


def rule_no_fstrings(root):
    bad = []
    for name in tool_py(root):
        try:
            t = tree(root, name)
        except SyntaxError:
            continue
        for n in ast.walk(t):
            if isinstance(n, ast.JoinedStr):
                bad.append('{0}:{1} f-string'.format(name, n.lineno))
    return bad


def rule_no_print(root):
    bad = []
    for name in tool_py(root):
        if re.search(r'\bprint\b', code_only(src(root, name))):
            bad.append('{0} uses print'.format(name))
    return bad


def rule_no_bare_integervalue(root):
    bad = []
    for name in tool_py(root):
        if re.search(r'\.IntegerValue\b', code_only(src(root, name))):
            bad.append('{0}: .IntegerValue (removed from ElementId in 2026) - '
                       'use eid_value / getattr'.format(name))
    return bad


def rule_no_uri(root):
    bad = []
    for name in tool_py(root):
        code = code_only(src(root, name))
        if re.search(r'\bUri\b', code) or 'UriSource' in code:
            bad.append('{0}: System.Uri moved assembly in 2025 - load images '
                       'from a MemoryStream'.format(name))
    return bad


def _dotnet_imports(t):
    """Top-level (statement index, namespace) for System / Autodesk imports."""
    out = []
    for i, n in enumerate(t.body):
        if isinstance(n, ast.ImportFrom) and n.module and \
                n.module.split('.')[0] in ('System', 'Autodesk'):
            out.append((i, n.module))
        elif isinstance(n, ast.Import):
            for a in n.names:
                if a.name.split('.')[0] in ('System', 'Autodesk', 'clr'):
                    out.append((i, a.name))
    return out


def rule_clr_first(root):
    bad = []
    for name in tool_py(root):
        if name in ('ca_clr.py', 'script.py'):
            continue
        t = tree(root, name)
        dotnet = _dotnet_imports(t)
        if not dotnet:
            continue
        clr_at = None
        for i, n in enumerate(t.body):
            if isinstance(n, ast.Import) and any(a.name == 'ca_clr' for a in n.names):
                clr_at = i
                break
        if clr_at is None or clr_at > dotnet[0][0]:
            bad.append('{0} imports {1} before ca_clr'.format(name, dotnet[0][1]))
    return bad


def _referenced_assemblies(root):
    """Assemblies ca_clr references at import time (never inside a def)."""
    t = tree(root, 'ca_clr.py')
    refs = set()
    for n in t.body:
        if isinstance(n, ast.Assign) and any(
                isinstance(x, ast.Name) and x.id == '_ASSEMBLIES' for x in n.targets):
            refs |= set(e.value for e in n.value.elts)
    loops = [n for n in t.body if isinstance(n, ast.For)]
    if not any('AddReference' in ast.dump(l) for l in loops):
        return set()
    return refs


def rule_assemblies_referenced(root):
    refs = _referenced_assemblies(root) | PRELOADED
    bad = []
    for name in tool_py(root):
        if name == 'script.py':
            continue
        t = tree(root, name)
        spaces = set()
        for n in ast.walk(t):
            if isinstance(n, ast.ImportFrom) and n.module and \
                    n.module.split('.')[0] in ('System', 'Autodesk'):
                spaces.add(n.module)
            elif isinstance(n, ast.Import):
                for a in n.names:
                    if a.name.split('.')[0] in ('System', 'Autodesk'):
                        spaces.add(a.name)
        for ns in sorted(spaces):
            providers = NAMESPACE_ASSEMBLIES.get(ns)
            if providers is None:
                bad.append('{0}: {1} is not in the namespace table'.format(name, ns))
            elif not refs.intersection(providers):
                bad.append('{0}: {1} needs one of {2} referenced in ca_clr'.format(
                    name, ns, ', '.join(providers)))
    return bad


def rule_no_duplicate_defs(root):
    bad = []
    for name in tool_py(root):
        t = tree(root, name)
        scopes = [t] + [n for n in ast.walk(t) if isinstance(n, ast.ClassDef)]
        for scope in scopes:
            seen = set()
            for n in scope.body:
                if isinstance(n, (ast.FunctionDef, ast.ClassDef)):
                    if n.name in seen:
                        bad.append('{0}: {1} defined twice'.format(name, n.name))
                    seen.add(n.name)
    return bad


def _module_names(t):
    names = set()
    for n in ast.walk(t):
        if isinstance(n, (ast.FunctionDef, ast.ClassDef)):
            names.add(n.name)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                names.add((a.asname or a.name).split('.')[0])
    for n in t.body:
        for target in getattr(n, 'targets', []) + [getattr(n, 'target', None)]:
            for x in ast.walk(target) if target is not None else []:
                if isinstance(x, ast.Name):
                    names.add(x.id)
        if isinstance(n, (ast.For, ast.Try, ast.If, ast.With)):
            for x in ast.walk(n):
                if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Store):
                    names.add(x.id)
    return names


def rule_globals_bound(root):
    import builtins
    allowed = set(dir(builtins)) | EXTRA_BUILTINS
    bad = []
    for name in tool_py(root):
        text = src(root, name)
        t = ast.parse(text)
        defined = _module_names(t) | allowed
        table = symtable.symtable(text, name, 'exec')

        def walk(tbl):
            for child in tbl.get_children():
                if child.get_type() in ('function',):
                    for sym in child.get_symbols():
                        if sym.is_global() and sym.is_referenced() and \
                                sym.get_name() not in defined:
                            bad.append('{0}: {1}() uses undefined global {2}'.format(
                                name, child.get_name(), sym.get_name()))
                walk(child)
        walk(table)
    return bad


class _Replay(object):
    """Walk __init__ in source order, following self.method() calls, and
    report any self.attr read before something has set it."""

    def __init__(self, cls):
        self.cls = cls
        self.methods = dict((b.name, b) for b in cls.body if isinstance(b, ast.FunctionDef))
        self.class_attrs = set(self.methods)
        for b in cls.body:
            if isinstance(b, ast.Assign):
                for x in b.targets:
                    if isinstance(x, ast.Name):
                        self.class_attrs.add(x.id)
        self.assigned = set()
        self.problems = []
        self.stack = []

    def run(self):
        init = self.methods.get('__init__')
        if init is not None:
            self.method(init)
        return self.problems

    def method(self, fn):
        if fn.name in self.stack or len(self.stack) > 8:
            return
        self.stack.append(fn.name)
        for stmt in fn.body:
            self.stmt(stmt)
        self.stack.pop()

    def stmt(self, node):
        if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Lambda)):
            return
        if isinstance(node, ast.Assign):
            self.expr(node.value)
            for t in node.targets:
                self.store(t)
            return
        if isinstance(node, ast.AugAssign):
            self.expr(node.value)
            self.expr(node.target)
            return
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.stmt):
                self.stmt(child)
            elif isinstance(child, ast.expr):
                self.expr(child)
            else:
                for sub in ast.iter_child_nodes(child):
                    if isinstance(sub, ast.stmt):
                        self.stmt(sub)
                    elif isinstance(sub, ast.expr):
                        self.expr(sub)

    def store(self, target):
        for x in ast.walk(target):
            if isinstance(x, ast.Attribute) and isinstance(x.value, ast.Name) and \
                    x.value.id == 'self' and isinstance(x.ctx, ast.Store):
                self.assigned.add(x.attr)
            elif isinstance(x, ast.Attribute) and isinstance(x.ctx, ast.Load):
                self.expr(x)

    def expr(self, node):
        if isinstance(node, ast.Lambda):
            return
        if isinstance(node, ast.Call):
            f = node.func
            for a in node.args:
                self.expr(a)
            for k in node.keywords:
                self.expr(k.value)
            if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and \
                    f.value.id == 'self':
                if f.attr in self.methods:
                    self.method(self.methods[f.attr])
                    return
                if f.attr == 'setattr':
                    return
            elif isinstance(f, ast.Name) and f.id == 'setattr':
                return
            self.expr(f)
            return
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and \
                node.value.id == 'self' and isinstance(node.ctx, ast.Load):
            if node.attr not in self.assigned and node.attr not in self.class_attrs \
                    and not self.dynamic(node.attr):
                self.problems.append('{0}.{1} read at line {2} before it is set'.format(
                    self.cls.name, node.attr, node.lineno))
            return
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.expr):
                self.expr(child)
            elif isinstance(child, ast.comprehension):
                self.expr(child.iter)
                for c in child.ifs:
                    self.expr(c)

    def dynamic(self, attr):
        return attr in self.dynamic_names

    dynamic_names = set()


def rule_attr_before_init(root):
    bad = []
    t_ui = tree(root, 'ca_ui.py')
    # names set by setattr(self, name, ...) loops over NAMES / PROMPT_NAMES / PICKER_NAMES
    dyn = (set(_names_tuple(t_ui, 'NAMES')) | set(_names_tuple(t_ui, 'PROMPT_NAMES')) |
           set(_names_tuple(t_ui, 'PICKER_NAMES')))
    for name in tool_py(root):
        t = tree(root, name)
        for cls in [n for n in ast.walk(t) if isinstance(n, ast.ClassDef)]:
            replay = _Replay(cls)
            replay.dynamic_names = dyn
            bad += ['{0}: {1}'.format(name, p) for p in replay.run()]
    return bad


def rule_palette_keys(root):
    core = load_core(root)
    bad = []
    if set(core.PALETTE_DARK) != set(core.PALETTE_LIGHT):
        bad.append('dark and light palettes have different keys: {0}'.format(
            sorted(set(core.PALETTE_DARK) ^ set(core.PALETTE_LIGHT))))
    brushes = set(re.findall(r'<SolidColorBrush x:Key="([^"]+)"', src(root, THEME)))
    for key in core.PALETTE_DARK:
        if key not in brushes:
            bad.append('palette key {0} has no brush in Theme.xaml'.format(key))
    return bad


def rule_theme_defaults_dark(root):
    core = load_core(root)
    bad = []
    for key, colour in re.findall(r'<SolidColorBrush x:Key="([^"]+)" Color="([^"]+)"',
                                  src(root, THEME)):
        if key in core.PALETTE_DARK and core.PALETTE_DARK[key].upper() != colour.upper():
            bad.append('Theme.xaml {0} is {1}, dark palette says {2}'.format(
                key, colour, core.PALETTE_DARK[key]))
    return bad


def rule_changelog_has_version(root):
    m = re.search(r'__version__\s*=\s*"([^"]+)"', src(root, 'ca_version.py'))
    if not m:
        return ['ca_version.py has no __version__']
    if '## ' + m.group(1) not in src(root, 'CHANGELOG.md'):
        return ['CHANGELOG.md has no entry for {0}'.format(m.group(1))]
    return []


def rule_every_window_has_drawer(root):
    bad = []
    for layout in LAYOUTS:
        text = src(root, layout)
        if '<Window' in text and 'x:Name="ShrinkBtn"' not in text:
            bad.append('{0} has no ShrinkBtn'.format(layout))
    t = tree(root, 'ca_ui.py')
    for cls in [n for n in ast.walk(t) if isinstance(n, ast.ClassDef)]:
        body = ast.dump(cls)
        if "load_xaml" in body and "WindowDrawer" not in body:
            bad.append('ca_ui.{0} builds a window without a WindowDrawer'.format(cls.name))
    ui = code_only(src(root, 'ca_drawer.py'))
    if 'button.Click +=' not in ui:
        bad.append('WindowDrawer never wires its shrink button')
    return bad


def rule_drawer_releases(root):
    bad = []
    code = code_only(src(root, 'ca_drawer.py'))
    for prop in ('TopProperty', 'HeightProperty'):
        if not re.search(r'BeginAnimation\(Window\.' + prop + r',\s*None\)', code):
            bad.append('the drawer never releases the {0} animation'.format(prop))
    for name in tool_py(root):
        if 'Storyboard' in code_only(src(root, name)):
            bad.append('{0} uses a Storyboard'.format(name))
    fn = find_def(tree(root, 'ca_core.py'), 'DrawerMachine', '_tick')
    if fn is None or not any(isinstance(n, ast.Try) and n.handlers and
                             '_land' in ast.dump(n.handlers[0]) for n in fn.body):
        bad.append('DrawerMachine._tick does not land the window when a frame fails')
    return bad


def rule_busy_keeps_shrink(root):
    bad = []
    t = tree(root, 'ca_ui.py')
    fn = find_def(t, 'ClashWindow', 'set_busy')
    if fn is None:
        bad.append('ClashWindow.set_busy is missing')
    elif 'ShrinkBtn' in ast.dump(fn):
        bad.append('set_busy touches the shrink button - it must stay live')
    for name in tool_py(root):
        for fn in functions(tree(root, name)):
            if fn.name in ('on_key', '_on_key', 'handle_key') and \
                    "attr='Close'" in ast.dump(fn):
                bad.append('{0}: {1} closes a window from a key'.format(name, fn.name))
    return bad


def rule_transactions_only_in_jobs(root):
    bad = []
    for name in tool_py(root):
        if name == 'ca_jobs.py':
            continue
        if re.search(r'\bTransaction(Group)?\s*\(', code_only(src(root, name))):
            bad.append('{0} opens a transaction - writes belong in ca_jobs'.format(name))
    return bad


def rule_script_thin(root):
    t = tree(root, 'script.py')
    bad = []
    for n in t.body:
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            mod = getattr(n, 'module', None) or n.names[0].name
            if mod.split('.')[0] in ('System', 'Autodesk', 'clr') or mod.startswith('ca_'):
                bad.append('script.py imports {0} outside a stage'.format(mod))
    if 'AddReference' in code_only(src(root, 'script.py')):
        bad.append('script.py references assemblies itself')
    if '__persistentengine__ = True' not in src(root, 'script.py'):
        bad.append('script.py is not a persistent engine (modeless window)')
    return bad


def rule_no_literal_brace(root):
    bad = []
    for name in LAYOUTS + [THEME]:
        for el in all_elements(xaml_doc(root, name).documentElement):
            for attr, value in el.attributes.items():
                if value.startswith('{') and not value.startswith(MARKUP_EXTENSIONS):
                    bad.append('{0}: {1}="{2}" starts with a literal brace'.format(
                        name, attr, value))
    return bad


def rule_ascii_outside_unicode_literals(root):
    bad = []
    for name in tool_py(root):
        text = src(root, name)
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if any(ord(ch) > 127 for ch in tok.string):
                if tok.type == tokenize.STRING and tok.string[:1] in 'uU':
                    continue
                if tok.type == tokenize.COMMENT:
                    continue
                bad.append('{0}:{1} non-ASCII outside a u\'\' literal'.format(
                    name, tok.start[0]))
    return bad


def rule_modules_import(root):
    sys.path.insert(0, HERE)
    import bench_stubs
    sys.path.remove(HERE)
    bench_stubs.uninstall()
    bench_stubs.install()
    sys.path.insert(0, root)
    bad = []
    try:
        for mod in MODULES:
            try:
                importlib.import_module(mod)
            except Exception as ex:
                bad.append('{0} does not import: {1}: {2}'.format(mod, type(ex).__name__, ex))
    finally:
        sys.path.remove(root)
        bench_stubs.uninstall()
    return bad


def rule_dialogs_owned(root):
    """Every class that shows a dialog hands it its owner through
    own_dialog, so it never centres on a parked bar."""
    bad = []
    for name in tool_py(root):
        t = tree(root, name)
        for cls in [n for n in ast.walk(t) if isinstance(n, ast.ClassDef)]:
            shows = calls = False
            for n in ast.walk(cls):
                if isinstance(n, ast.Call):
                    f = n.func
                    if isinstance(f, ast.Attribute) and f.attr == 'ShowDialog':
                        shows = True
                    if isinstance(f, ast.Name) and f.id == 'own_dialog':
                        calls = True
            if shows and not calls:
                bad.append('{0}: {1} shows a dialog without own_dialog'.format(
                    name, cls.name))
        for fn in t.body:
            if isinstance(fn, ast.FunctionDef) and 'ShowDialog' in ast.dump(fn):
                bad.append('{0}: {1}() shows a dialog outside a window class'.format(
                    name, fn.name))
    return bad


def rule_runner_keeps_queue(root):
    fn = find_def(tree(root, 'ca_ui.py'), 'Runner', 'submit')
    if fn is None:
        return ['Runner.submit is missing']
    dump = ast.dump(fn)
    bad = []
    if 'Delete(' in dump or re.search(r"Assign\(targets=\[Attribute\(value=Name\(id='self'.*attr='jobs'", dump):
        bad.append('Runner.submit clears the whole queue - a Pending job loses its callback')
    if "attr='Pending'" not in dump:
        bad.append('Runner.submit does not treat Pending as queued')
    return bad


def rule_bip_at_call_time(root):
    bad = []
    for name in tool_py(root):
        t = tree(root, name)
        for n in t.body:
            if isinstance(n, (ast.FunctionDef, ast.ClassDef)):
                continue
            if 'BuiltInParameter' in ast.dump(n) and not isinstance(n, ast.ImportFrom):
                bad.append('{0}:{1} reads BuiltInParameter at module load'.format(
                    name, n.lineno))
    return bad


def rule_comment_format(root):
    """The comment written to each clash family uses -vs- between the two."""
    core = load_core(root)
    got = core.comment_text({'category': 'Cable Tray', 'family': 'Cable Tray',
                             'type': ''},
                            {'category': 'Structural Framing', 'family': 'Beam',
                             'type': ''}, 'family')
    return [] if got == u'Cable Tray-vs-Beam' else [
        'comment_text gives {0!r}, expected Cable Tray-vs-Beam'.format(got)]


def rule_rename_reachable(root):
    """Rename is reachable three ways - the button, the right-click menu and
    F2 - the menu is themed like the window, a right-click selects the test
    under the pointer, and the rename is checked before it writes."""
    code = code_only(src(root, 'ca_ui.py'))
    bad = []
    for needle, why in (
            ('self.RenameTestBtn.Click += self.on_rename_test', 'Rename button not wired'),
            ('self.TestList.ContextMenu = menu', 'no right-click menu on the test list'),
            ('self.on_rename_test)', 'the menu has no Rename item'),
            ('self.TestList.PreviewMouseRightButtonDown += self.on_test_right_down',
             'right-click does not select the test under the pointer'),
            ('Key.F2', 'F2 does not rename'),
            ('apply_palette(self.test_menu', 'the menu does not follow a theme swap'),
            ('core.check_test_name(', 'a rename is not checked before writing')):
        if needle not in code:
            bad.append(why)
    menu_fn = find_def(tree(root, 'ca_ui.py'), 'ClashWindow', 'build_test_menu')
    if menu_fn is None or "id='dress'" not in ast.dump(menu_fn):
        bad.append('the menu is not given the theme')
    fn = find_def(tree(root, 'ca_ui.py'), 'ClashWindow', 'rename_test')
    if fn is None:
        bad.append('ClashWindow.rename_test is missing')
    else:
        body = ast.dump(fn)
        if body.find("attr='remove'") < body.find("id='write_text'"):
            bad.append('rename removes the old file before writing the new one')
    return bad


def rule_run_scope_and_level(root):
    """Every run asks for the run scope (current view or whole project), the
    view scope reaches linked models through the view, and a floor plan
    run's level reaches the clash family placement."""
    ui = code_only(src(root, 'ca_ui.py'))
    rv = code_only(src(root, 'ca_revit.py'))
    jobs = code_only(src(root, 'ca_jobs.py'))
    bad = []
    calls = ui.count('rv.run_test(')
    scoped = ui.count('rv.run_scope(uiapp, test)')
    if calls == 0 or scoped < calls:
        bad.append('a clash test run does not pass the run scope ({0} runs, {1} scoped)'.format(
            calls, scoped))
    for needle, text, why in (
            ("test['scope'] = self.tag_of(self.RunScopeCombo)", ui,
             'the Run on choice is not saved with the test'),
            ("self.select_tag(self.RunScopeCombo, test['scope'])", ui,
             'the Run on choice is not shown when a test is picked'),
            ("FilteredElementCollector(scope['doc'], scope['view_id'], model.link_id)", rv,
             'linked models are not filtered by the view'),
            ("FilteredElementCollector(model.doc, scope['view_id'])", rv,
             'the host model is not filtered by the view'),
            ("view.GenLevel", rv, 'a floor plan run does not record its level'),
            ("fmt, stamp, log, level_id)", ui,
             'placement is not given the view level'),
            ("core.marker_level(fixed, level_pairs, pz)", jobs,
             'placement does not choose the view level / level below'),
            ("if not set_level(inst, level):", jobs, 'the level is not read back after placing')):
        if code_only(needle) not in text:
            bad.append(why)
    return bad


def rule_clash_schedule(root):
    """Create Clash schedule: Generic Models, named BIM_Clash Analysis
    Schedule, filtered to the clash family through a hidden field, Level and
    Comments columns, sorted by Level with a header, Comments widened."""
    jobs = code_only(src(root, 'ca_jobs.py'))
    ui = code_only(src(root, 'ca_ui.py'))
    core = src(root, 'ca_core.py')
    bad = []
    if u"SCHEDULE_NAME = u'BIM_Clash Analysis Schedule'" not in core:
        bad.append('the schedule name is not BIM_Clash Analysis Schedule')
    for needle, why in (
            ('BuiltInCategory.OST_GenericModel', 'not a Generic Models schedule'),
            ('sched.Name = core.SCHEDULE_NAME', 'the new schedule is not named'),
            ("f_level.ColumnHeading = u'Level'", 'no Level column'),
            ("f_comments.ColumnHeading = u'Comments'", 'no Comments column'),
            ('f_family.IsHidden = True', 'the family filter column shows'),
            ('ScheduleFilterType.Equal, family', 'not filtered by the clash family'),
            ('by_level.ShowHeader = True', 'Level grouping has no header'),
            ('defn.AddSortGroupField(by_level)', 'not sorted by Level'),
            ("_set_width(f_comments, result['width_mm'])", 'Comments column not widened'),
            ('defn.ClearFilters()', 'an existing schedule keeps old filters')):
        if code_only(needle) not in jobs:
            bad.append(why)
    fn = find_def(tree(root, 'ca_jobs.py'), None, 'make_clash_schedule')
    if fn is not None:
        body = ast.dump(fn)
        if body.find("attr='AddSortGroupField'") < body.find("attr='AddField'"):
            bad.append('sorting is added before the fields exist')
    if 'self.ScheduleBtn.Click += self.on_schedule' not in ui:
        bad.append('Create Clash schedule button not wired')
    return bad


def rule_workset_create(root):
    """A workset the model lacks is offered bold and green with "Create
    Workset?", created inside the job before the command uses it, and the
    lists are read again afterwards."""
    ui = code_only(src(root, 'ca_ui.py'))
    raw = src(root, 'ca_ui.py')
    bad = []
    for needle, why in (
            ('tb.FontWeight = FontWeights.Bold', 'the offer is not bold'),
            ("tb.SetResourceReference(TextBlock.ForegroundProperty, 'Green')",
             'the offer is not green'),
            ('self.WorksetCombo.SelectionChanged += self.on_workset_picked',
             'Custom workset not wired on the placing list'),
            ('self.GroupWorksetCombo.SelectionChanged += self.on_workset_picked',
             'Custom workset not wired on the groups list'),
            ('self.after_workset_job(result)', 'the lists are not refreshed after a create')):
        if code_only(needle) not in ui:
            bad.append(why)
    if u"Create Workset?" not in raw:
        bad.append('the words Create Workset? are missing')
    for fn_name in ('on_place', 'on_assign_workset'):
        fn = find_def(tree(root, 'ca_ui.py'), 'ClashWindow', fn_name)
        body = ast.dump(fn) if fn is not None else ''
        if "attr='ensure_workset'" not in body:
            bad.append('{0} does not create the workset first'.format(fn_name))
    return bad


def rule_floor_groups(root):
    """Placement skips clashes that already have the family, groups per
    floor with the level code in the name, and the Clash Groups list shows
    the level and when the clash test last started running."""
    jobs = code_only(src(root, 'ca_jobs.py'))
    ui = code_only(src(root, 'ca_ui.py'))
    bad = []
    for needle, text, why in (
            ("if already.near((px, py, pz)):", jobs, 'clashes already placed are not skipped'),
            ("already.add((px, py, pz))", jobs, 'two clashes on one spot both get a family'),
            ("rv.family_points(doc, rv.family_of(symbol))", jobs,
             'existing clash families are not read'),
            ("for level, ids in order:", jobs, 'not one group per floor'),
            ("core.clash_group_name(stamp, test_name, codes.get(lname, u''))", jobs,
             'the group name has no level code'),
            ("codes = core.level_codes([rv.elem_name(lvl) for lvl, elev in level_rows])", jobs,
             'level codes not taken from every level in the model'),
            ("self.last_run_of(rec['parsed']['clash'])", ui, 'no last run column'),
            ("result['started'] = started", ui, 'the run start time is not kept'),
            ("result['run_at'] = result.get('started') or self.stamp_now()", ui,
             'last run is not the start time')):
        if code_only(needle) not in text:
            bad.append(why)
    if ui.count(code_only("result['started'] = started")) < 2:
        bad.append('Run all does not keep each start time')
    return bad


def rule_tests_layout(root):
    """Clash Tests tab: Saved clash tests sits above Set A + Set B, both
    collapse with the drawer slide (clicking the header), each Models list
    can be dragged taller or shorter and both stay in step, ticking a model
    lists only Revit's own model categories, and new tests run on the
    current view."""
    xaml = src(root, 'ClashAnalysis.xaml')
    ui = code_only(src(root, 'ca_ui.py'))
    rv = code_only(src(root, 'ca_revit.py'))
    bad = []
    t, a = xaml.find('x:Name="TestsBody"'), xaml.find('x:Name="SetsBody"')
    if t < 0 or a < 0 or t > a:
        bad.append('Saved clash tests is not above Set A + Set B')
    if 'x:Name="TestList"' in xaml and xaml.find('x:Name="TestList"') > a:
        bad.append('the test list is not inside the top section')
    for name in ('SplitA', 'SplitB'):
        if 'x:Name="{0}"'.format(name) not in xaml:
            bad.append('no drag bar under Models ({0})'.format(name))
    if 'MaxHeight="96"' in xaml:
        bad.append('a Models list is still capped at 96 px')
    for needle, text, why in (
            ("self.TestsHeader.MouseLeftButtonUp += lambda s, e: self.toggle_section('tests')",
             ui, 'Saved clash tests header does not collapse'),
            ("self.SetsHeader.MouseLeftButtonUp += lambda s, e: self.toggle_section('sets')",
             ui, 'Set A + Set B header does not collapse'),
            ("ca_drawer.SectionDrawer(", ui, 'sections do not use the drawer slide'),
            ("self.SplitA.DragCompleted += lambda s, e: self.on_models_split('a')", ui,
             'dragging Set A Models is not remembered'),
            ("self.SplitB.DragCompleted += lambda s, e: self.on_models_split('b')", ui,
             'dragging Set B Models is not remembered'),
            ("verdict[ckey] = _listable(cat, model_type)", rv,
             'categories are not limited to model categories'),
            ("if isinstance(el, (ImportInstance, CurveElement)):", rv,
             'imports and lines can still be listed')):
        if code_only(needle) not in text:
            bad.append(why)
    if "'scope': u'view'," not in src(root, 'ca_core.py'):
        bad.append('new tests do not default to the current view')
    if 'Storyboard' in code_only(src(root, 'ca_drawer.py')):
        bad.append('the section slide uses a Storyboard')
    return bad


def rule_isolate_sphere(root):
    """Isolate Clash Sphere: the change is temporary (Temporary View
    Properties before any category is shown, Temporary Isolate), the
    category and Detail Items are shown, the view zooms to fit, a plan on
    another floor is picked from the searchable list, and Reset view ends
    both temporary modes."""
    jobs = code_only(src(root, 'ca_jobs.py'))
    ui = code_only(src(root, 'ca_ui.py'))
    bad = []
    for needle, text, why in (
            ('self.IsolateBtn.Click += self.on_isolate', ui, 'Isolate Clash Sphere not wired'),
            ('self.ResetViewBtn.Click += self.on_reset_view', ui, 'Reset view not wired'),
            ("if info['active_ok']:", ui, 'the active view is never used directly'),
            ('picker = ViewPicker(', ui, 'no floor plan picker for another floor'),
            ('view.IsolateElementsTemporary(_ids(ids))', jobs, 'not a temporary isolate'),
            ('view.SetCategoryHidden(cid, False)', jobs, 'the clash category is not shown'),
            ('BuiltInCategory.OST_DetailComponents', jobs, 'nested plan symbols stay hidden'),
            ('uiv.ZoomToFit()', jobs, 'no zoom extents'),
            ('view.DisableTemporaryViewMode(TemporaryViewMode.TemporaryHideIsolate)', jobs,
             'Reset view leaves the isolate on'),
            ('view.DisableTemporaryViewMode(TemporaryViewMode.TemporaryViewProperties)', jobs,
             'Reset view leaves Temporary View Properties on')):
        if code_only(needle) not in text:
            bad.append(why)
    fn = find_def(tree(root, 'ca_jobs.py'), None, 'isolate_in_view')
    body = ast.dump(fn) if fn is not None else ''
    if body.find("id='_enable_tvp'") < 0 or \
            body.find("id='_enable_tvp'") > body.find("attr='SetCategoryHidden'"):
        bad.append('categories are shown before Temporary View Properties is on')
    return bad


def rule_review_and_3d(root):
    """Clash families in the group: the review blob is the first column,
    the three status buttons and the right-click menu set every highlighted
    family, Zoom to family turns red amber and shrinks the window. View in
    3D boxes the section round the spheres and zooms to fit."""
    ui = code_only(src(root, 'ca_ui.py'))
    jobs = code_only(src(root, 'ca_jobs.py'))
    raw_ui = src(root, 'ca_ui.py')
    bad = []
    if "DETAIL_COLS = [('st', u'Review', 'blob'" not in raw_ui:
        bad.append('the review blob is not the first column')
    for needle, text, why in (
            ("self.StatusNotBtn.Click += lambda s, e: self.set_review(u'not')", ui, 'red button not wired'),
            ("self.StatusReviewedBtn.Click += lambda s, e: self.set_review(u'reviewed')", ui,
             'amber button not wired'),
            ("self.StatusOkBtn.Click += lambda s, e: self.set_review(u'ok')", ui, 'green button not wired'),
            ("self.DetailGrid.ContextMenu = menu", ui, 'no right-click status menu'),
            ("apply_palette(self.detail_menu, self.resolved_theme)", ui,
             'the status menu does not follow a theme swap'),
            ("core.set_reviews(self.reviews, [row.get('uid')], core.after_zoom(state))", ui,
             'Zoom to family does not mark reviewed'),
            ("self.drawer.park()", ui, 'Zoom to family does not shrink the window'),
            ("self.View3DBtn.Click += self.on_view_3d", ui, 'View in 3D not wired'),
            ("view.SetSectionBox(bb)", jobs, 'no section box round the spheres'),
            ("zoomed = zoom_fit(uidoc, view.Id)", jobs, 'View in 3D does not zoom to fit')):
        if code_only(needle) not in text:
            bad.append(why)
    return bad


RULES = [
    rule_xaml_parses, rule_no_static_resource, rule_resource_keys_defined,
    rule_style_targets, rule_findname_has_xname, rule_python_parses,
    rule_no_fstrings, rule_no_print, rule_no_bare_integervalue, rule_no_uri,
    rule_clr_first, rule_assemblies_referenced, rule_no_duplicate_defs,
    rule_globals_bound, rule_attr_before_init, rule_palette_keys,
    rule_theme_defaults_dark, rule_changelog_has_version,
    rule_every_window_has_drawer, rule_drawer_releases, rule_busy_keeps_shrink,
    rule_transactions_only_in_jobs, rule_script_thin, rule_no_literal_brace,
    rule_ascii_outside_unicode_literals, rule_modules_import,
    rule_dialogs_owned, rule_runner_keeps_queue, rule_bip_at_call_time,
    rule_comment_format, rule_rename_reachable, rule_run_scope_and_level,
    rule_clash_schedule, rule_workset_create, rule_floor_groups,
    rule_tests_layout, rule_isolate_sphere, rule_review_and_3d,
]


def run_rules(root, quiet=False):
    failed = {}
    for rule in RULES:
        try:
            problems = rule(root)
        except Exception as ex:
            problems = ['rule crashed: {0}: {1}'.format(type(ex).__name__, ex)]
        if problems:
            failed[rule.__name__] = problems
        if not quiet:
            print('{0:<40} {1}'.format(rule.__name__, 'FAIL' if problems else 'ok'))
            for p in problems:
                print('    - ' + p)
    return failed


# ======================================================================
# selftest: (file, anchor, replacement, rule that must catch it)
# ======================================================================

BREAKAGES = [
    ('ClashAnalysis.xaml', '<!-- ==================== Header', '<!-- -- Header', 'rule_xaml_parses'),
    ('ca_version.py', 'TOOL_NAME = u"Clash Analysis"', 'TOOL_NAME = u"Clash Analysis', 'rule_python_parses'),
    ('Prompt.xaml', '<Border x:Name="OuterBorder" Background="{DynamicResource WindowBg}"',
     '<Border x:Name="OuterBorder" Background="{StaticResource WindowBg}"',
     'rule_no_static_resource'),
    ('ClashAnalysis.xaml', 'Foreground="{DynamicResource Muted}" FontSize="11"',
     'Foreground="{DynamicResource Mutted}" FontSize="11"', 'rule_resource_keys_defined'),
    ('ca_ui.py', "SetResourceReference(TextBlock.ForegroundProperty, 'Muted')",
     "SetResourceReference(TextBlock.ForegroundProperty, 'Grey')", 'rule_resource_keys_defined'),
    ('ClashAnalysis.xaml', '<Button x:Name="ThemeBtn" Style="{DynamicResource ChipBtn}"',
     '<Button x:Name="ThemeBtn" Style="{DynamicResource Card}"', 'rule_style_targets'),
    ('ClashAnalysis.xaml', 'x:Name="AllPairsBtn"', 'x:Name="AllPairButton"',
     'rule_findname_has_xname'),
    ('Prompt.xaml', 'x:Name="MessageText"', 'x:Name="Message"', 'rule_findname_has_xname'),
    ('ca_core.py', "    return u'CLASH-{0:04d}", "    return f'CLASH-{year}' or u'CLASH-{0:04d}",
     'rule_no_fstrings'),
    ('ca_revit.py', '    return out\n\n\ndef user_worksets',
     '    print(out)\n    return out\n\n\ndef user_worksets', 'rule_no_print'),
    ('ca_jobs.py', "    target = rv.workset_int(workset_id)\n    try:",
     "    target = workset_id.IntegerValue\n    try:", 'rule_no_bare_integervalue'),
    ('ca_ui.py', 'bmp.StreamSource = MemoryStream(File.ReadAllBytes(path))',
     'bmp.UriSource = Uri(path)', 'rule_no_uri'),
    ('ca_drawer.py', 'import ca_clr  # noqa: F401  (assembly references first)\n\nfrom System import',
     'from System import Double\nimport ca_clr  # noqa: F401\n\nfrom System import', 'rule_clr_first'),
    ('ca_clr.py', "'mscorlib', 'System', 'System.Core', 'System.Data', 'System.Data.Common',",
     "'mscorlib', 'System', 'System.Core',", 'rule_assemblies_referenced'),
    ('ca_clr.py', "    'System.ComponentModel.TypeConverter',\n",
     "    'System.ComponentModel.TypeConverter',\n]\n_X = [\n", 'rule_assemblies_referenced'),
    ('ca_revit.py', 'from System.Collections.Generic import List',
     'from System.Collections.Generic import List\nfrom System.Linq import Enumerable',
     'rule_assemblies_referenced'),
    ('ca_core.py', 'def ft_to_mm(ft):', 'def mm_to_ft(ft):', 'rule_no_duplicate_defs'),
    ('ca_ui.py', '    def status(self, text):', '    def tag_of(self, text):',
     'rule_no_duplicate_defs'),
    ('ca_jobs.py', 'def set_comment(element, text):', 'def set_comment_old(element, text):',
     'rule_globals_bound'),
    ('ca_ui.py', '        self.current_name = None\n        self.results', '        self.results', 'rule_attr_before_init'),
    ('ca_ui.py', "        self.watchdog = DispatcherTimer()\n",
     "        self.wire()\n        self.watchdog = DispatcherTimer()\n", 'rule_attr_before_init'),
    ('ca_core.py', "    'OnAccent': '#FFFFFF',\n}\n\nPALETTE_KEYS",
     "    'OnAccent': '#FFFFFF',\n    'Extra': '#000000',\n}\n\nPALETTE_KEYS",
     'rule_palette_keys'),
    ('Theme.xaml', '<SolidColorBrush x:Key="SelBg" Color="#3A7392"/>', '',
     'rule_palette_keys'),
    ('Theme.xaml', 'x:Key="WindowBg" Color="#3C4454"', 'x:Key="WindowBg" Color="#232326"',
     'rule_theme_defaults_dark'),
    ('ca_version.py', '__version__ = "', '__version__ = "0.',
     'rule_changelog_has_version'),
    ('Prompt.xaml', '<Button x:Name="ShrinkBtn" Style="{DynamicResource ShrinkButton}"/>',
     '', 'rule_every_window_has_drawer'),
    ('ca_ui.py', "        self.drawer = ca_drawer.WindowDrawer(w, self.HeaderBar, self.RootGrid,\n"
                 "                                             self.ShrinkBtn, None,\n"
                 "                                             on_change=self._on_drawer)\n",
     "        self.drawer = None\n", 'rule_every_window_has_drawer'),
    ('ca_drawer.py', '        button.Click += self._on_click\n', '',
     'rule_every_window_has_drawer'),
    ('ca_drawer.py', '            w.BeginAnimation(Window.HeightProperty, None)',
     '            pass', 'rule_drawer_releases'),
    ('ca_core.py', "        except Exception as ex:\n            self.errors.append(u'tick: {0}'.format(ex))\n            self._land()\n",
     "        except Exception as ex:\n            self.errors.append(u'tick: {0}'.format(ex))\n",
     'rule_drawer_releases'),
    ('ca_ui.py', '        self.MaxBtn.IsHitTestVisible = not flag\n',
     '        self.MaxBtn.IsHitTestVisible = not flag\n        self.ShrinkBtn.IsEnabled = not flag\n',
     'rule_busy_keeps_shrink'),
    ('ca_ui.py', "    def _on_key(self, sender, args):\n        self.drawer.handle_key(args)\n",
     "    def _on_key(self, sender, args):\n        self.drawer.handle_key(args)\n"
     "        if args.Key == Key.Escape:\n            self.window.Close()\n",
     'rule_busy_keeps_shrink'),
    ('ca_revit.py', 'def side_info(item):',
     'def _bad(doc):\n    t = Transaction(doc, "x")\n    return t\n\n\ndef side_info(item):',
     'rule_transactions_only_in_jobs'),
    ('script.py', 'import traceback\n', 'import traceback\nimport ca_ui\n', 'rule_script_thin'),
    ('script.py', '__persistentengine__ = True', '__persistentengine__ = False',
     'rule_script_thin'),
    ('ClashAnalysis.xaml', 'Tag="Search clash tests"', 'Tag="{Test name}"',
     'rule_no_literal_brace'),
    ('ca_core.py', "VS = u'-vs-'", "VS = '-vs-'  \nARROW = '→'",
     'rule_ascii_outside_unicode_literals'),
    ('ca_jobs.py', 'from Autodesk.Revit.DB.Structure import StructuralType',
     'from Autodesk.Revit.DB import StructuralType', 'rule_modules_import'),
    ('ca_ui.py', '        own_dialog(w, owner, owner_drawer)\n', '',
     'rule_dialogs_owned'),
    ('ca_ui.py', "        try:\n            self.jobs.remove(job)\n        except ValueError:\n            pass\n",
     "        del self.jobs[:]\n", 'rule_runner_keeps_queue'),
    ('ca_ui.py', "status == ExternalEventRequest.Pending", "status == ExternalEventRequest.Accepted",
     'rule_runner_keeps_queue'),
    ('ca_revit.py', 'HOST_KEY = u\'HOST\'',
     'HOST_KEY = u\'HOST\'\nCOMMENTS = BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS',
     'rule_bip_at_call_time'),
    ('ca_core.py', "VS = u'-vs-'", "VS = u' vs '", 'rule_comment_format'),
    ('ca_ui.py', '        self.RenameTestBtn.Click += self.on_rename_test\n', '',
     'rule_rename_reachable'),
    ('ca_ui.py', "                ('rename', u'Rename...', u'F2', self.on_rename_test),\n", '',
     'rule_rename_reachable'),
    ('ca_ui.py', '        self.TestList.PreviewMouseRightButtonDown += self.on_test_right_down\n', '',
     'rule_rename_reachable'),
    ('ca_ui.py', '        if args.Key == Key.F2:', '        if args.Key == Key.F3:',
     'rule_rename_reachable'),
    ('ca_ui.py', '        dress(menu)\n', '', 'rule_rename_reachable'),
    ('ca_ui.py', "        new, problem = core.check_test_name(typed, old, self.tests.keys())",
     "        new, problem = typed, None", 'rule_rename_reachable'),
    ('ca_ui.py', """        old_path = self.test_path(old)
        try:""", """        old_path = self.test_path(old)
        os.remove(old_path)
        try:""", 'rule_rename_reachable'),
    ('Prompt.xaml', 'x:Name="InputBox"', 'x:Name="TextInput"', 'rule_findname_has_xname'),
    ('ca_ui.py', "            result = rv.run_test(models, test, log, rv.run_scope(uiapp, test))",
     "            result = rv.run_test(models, test, log)", 'rule_run_scope_and_level'),
    ('ca_ui.py', "        test['scope'] = self.tag_of(self.RunScopeCombo) or u'view'\n", '',
     'rule_run_scope_and_level'),
    ('ca_revit.py', "        col = FilteredElementCollector(scope['doc'], scope['view_id'], model.link_id)",
     "        col = FilteredElementCollector(model.doc)", 'rule_run_scope_and_level'),
    ('ca_ui.py', "fmt, stamp, log, level_id)", "fmt, stamp, log, None)",
     'rule_run_scope_and_level'),
    ('ca_jobs.py', "            idx = core.marker_level(fixed, level_pairs, pz)",
     "            idx = core.choose_level(level_pairs, pz)", 'rule_run_scope_and_level'),
    ('ca_jobs.py', "            if not set_level(inst, level):", "            if False:",
     'rule_run_scope_and_level'),
    ('ca_core.py', "SCHEDULE_NAME = u'BIM_Clash Analysis Schedule'",
     "SCHEDULE_NAME = u'Clash Schedule'", 'rule_clash_schedule'),
    ('ca_jobs.py', "        by_level.ShowHeader = True\n", '', 'rule_clash_schedule'),
    ('ca_jobs.py', "            f_family.IsHidden = True\n", '', 'rule_clash_schedule'),
    ('ca_jobs.py', "        if not _set_width(f_comments, result['width_mm']):",
     "        if False:", 'rule_clash_schedule'),
    ('ca_jobs.py', "        defn.ClearFilters()\n", '', 'rule_clash_schedule'),
    ('ca_ui.py', "        self.ScheduleBtn.Click += self.on_schedule\n", '', 'rule_clash_schedule'),
    ('ca_ui.py', "                tb.FontWeight = FontWeights.Bold\n", '', 'rule_workset_create'),
    ('ca_ui.py', "                wid, made = jobs.ensure_workset(doc, create_ws, log)\n            result = jobs.place_markers(",
     "                pass\n            result = jobs.place_markers(", 'rule_workset_create'),
    ('ca_ui.py', "                wid, made = jobs.ensure_workset(doc, create_ws, log)\n            result = jobs.assign_workset(",
     "                pass\n            result = jobs.assign_workset(", 'rule_workset_create'),
    ('ca_ui.py', "        self.GroupWorksetCombo.SelectionChanged += self.on_workset_picked\n", '',
     'rule_workset_create'),
    ('ca_jobs.py', "            if already.near((px, py, pz)):", "            if False:",
     'rule_floor_groups'),
    ('ca_jobs.py', "            already.add((px, py, pz))\n", '', 'rule_floor_groups'),
    ('ca_jobs.py', "            for level, ids in order:", "            for level, ids in order[:1]:",
     'rule_floor_groups'),
    ('ca_jobs.py', "core.clash_group_name(stamp, test_name, codes.get(lname, u''))",
     "core.clash_group_name(stamp, test_name)", 'rule_floor_groups'),
    ('ca_ui.py', "        result['run_at'] = result.get('started') or self.stamp_now()",
     "        result['run_at'] = self.stamp_now()", 'rule_floor_groups'),
    ('ca_ui.py', "                    result['started'] = started\n", '', 'rule_floor_groups'),
    ('ca_ui.py', "        self.SetsHeader.MouseLeftButtonUp += lambda s, e: self.toggle_section('sets')\n",
     '', 'rule_tests_layout'),
    ('ca_ui.py', "        self.SplitB.DragCompleted += lambda s, e: self.on_models_split('b')\n",
     '', 'rule_tests_layout'),
    ('ca_revit.py', "            if isinstance(el, (ImportInstance, CurveElement)):\n                continue\n",
     '', 'rule_tests_layout'),
    ('ca_core.py', "    'scope': u'view',\n", "    'scope': u'project',\n", 'rule_tests_layout'),
    ('ClashAnalysis.xaml', '<ListBox x:Name="ModelsA" Grid.Row="2"/>',
     '<ListBox x:Name="ModelsA" Grid.Row="2" MaxHeight="96"/>', 'rule_tests_layout'),
    ('ca_jobs.py', "        result['tvp'] = _enable_tvp(view)\n", '', 'rule_isolate_sphere'),
    ('ca_jobs.py', "            view.IsolateElementsTemporary(_ids(ids))",
     "            view.HideElementsTemporary(_ids(ids))",
     'rule_isolate_sphere'),
    ('ca_jobs.py', "                uiv.ZoomToFit()", "                pass", 'rule_isolate_sphere'),
    ('ca_jobs.py', "                view.DisableTemporaryViewMode(TemporaryViewMode.TemporaryViewProperties)",
     "                pass", 'rule_isolate_sphere'),
    ('ca_ui.py', "            if info['active_ok']:\n                self.isolate_in(None, info)\n                return\n",
     '', 'rule_isolate_sphere'),
    ('ViewPicker.xaml', 'x:Name="ViewSearch"', 'x:Name="Search"', 'rule_findname_has_xname'),
    ('ca_ui.py', "                if not self.drawer.parked:\n                    self.drawer.park()",
     "                if not self.drawer.parked:\n                    pass", 'rule_review_and_3d'),
    ('ca_ui.py', "                core.set_reviews(self.reviews, [row.get('uid')], core.after_zoom(state))\n",
     '', 'rule_review_and_3d'),
    ('ca_ui.py', "        self.StatusOkBtn.Click += lambda s, e: self.set_review(u'ok')\n", '',
     'rule_review_and_3d'),
    ('ca_jobs.py', "        view.SetSectionBox(bb)\n", '', 'rule_review_and_3d'),
    ('ca_ui.py', "DETAIL_COLS = [('st', u'Review', 'blob', 0.2, 56), ('no', u'#', 'i', 0.15, 36),",
     "DETAIL_COLS = [('no', u'#', 'i', 0.15, 36), ('st', u'Review', 'blob', 0.2, 56),",
     'rule_review_and_3d'),
    ('ViewPicker.xaml', '<Button x:Name="ShrinkBtn" Style="{DynamicResource ShrinkButton}"/>', '',
     'rule_every_window_has_drawer'),
]


def selftest():
    print('clean run')
    failed = run_rules(HERE, quiet=True)
    if failed:
        print('  the clean tool fails: {0}'.format(sorted(failed)))
        return False
    ok = True
    for i, (fname, anchor, replacement, rule) in enumerate(BREAKAGES):
        tmp = tempfile.mkdtemp(prefix='ca_bench_')
        try:
            for f in os.listdir(HERE):
                p = os.path.join(HERE, f)
                if os.path.isfile(p):
                    shutil.copy(p, tmp)
            path = os.path.join(tmp, fname)
            text = io.open(path, encoding='utf-8').read()
            if anchor not in text:
                print('  [{0:02d}] anchor missing in {1} - breakage never happened: FAIL'.format(i, fname))
                ok = False
                continue
            io.open(path, 'w', encoding='utf-8').write(text.replace(anchor, replacement, 1))
            got = run_rules(tmp, quiet=True)
            caught = rule in got
            print('  [{0:02d}] {1:<38} {2:<20} {3}'.format(
                i, rule, fname, 'caught' if caught else 'MISSED (got {0})'.format(sorted(got))))
            ok = ok and caught
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return ok


def main():
    if '--selftest' in sys.argv:
        good = selftest()
        print('\nSELFTEST {0}: {1} breakages, {2} rules'.format(
            'PASSED' if good else 'FAILED', len(BREAKAGES), len(RULES)))
        caught_rules = set(b[3] for b in BREAKAGES)
        unproven = [r.__name__ for r in RULES if r.__name__ not in caught_rules]
        if unproven:
            print('rules with no breakage: {0}'.format(unproven))
            good = False
        sys.exit(0 if good else 1)
    failed = run_rules(HERE)
    print('\n{0} of {1} rules passed'.format(len(RULES) - len(failed), len(RULES)))
    code = 1 if failed else 0
    if '--no-logic' not in sys.argv:
        print('\n== bench_logic.py ==')
        code = code or subprocess.call([sys.executable, os.path.join(HERE, 'bench_logic.py')])
    sys.exit(code)


if __name__ == '__main__':
    main()
