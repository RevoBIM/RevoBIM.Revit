# -*- coding: utf-8 -*-
"""Static bench check for Space Data Push, under plain CPython 3.

    python import_check.py             run every rule against this folder
    python import_check.py --selftest  copy the tool, break ONE thing at a time and
                                       confirm the matching rule fires

A blank white pyRevit window means the script died before any of it ran, and a
stub API cannot see a missing clr.AddReference, so these rules exist to catch
everything that produces one - on the bench instead of in Revit.
"""
import ast
import io
import os
import re
import shutil
import symtable
import sys
import tempfile
import traceback
import xml.dom.minidom as minidom

HERE = os.path.dirname(os.path.abspath(__file__))

PURE_MODULES = ['sdp_logic', 'sdp_version']
LOADER = 'script.py'
NOT_TOOL = ('script.py', 'import_check.py', 'bench_logic.py', 'bench_stub.py')

# namespace -> assemblies that provide it (longest prefix wins). Autodesk.* is
# deliberately absent: pyRevit has already loaded RevitAPI and RevitAPIUI, and the
# reference module must NOT add them.
ASSEMBLY_FOR = [
    ('System.Windows.Forms', ['System.Windows.Forms']),
    ('System.Windows.Threading', ['WindowsBase']),
    ('System.Windows.Input', ['PresentationCore', 'WindowsBase']),
    ('System.Windows.Media', ['PresentationCore']),
    ('System.Windows.Markup', ['PresentationFramework', 'System.Xaml']),
    ('System.Windows.Interop', ['PresentationFramework', 'PresentationCore']),
    ('System.Windows.Controls', ['PresentationFramework']),
    ('System.Windows.Data', ['PresentationFramework']),
    ('System.Windows.Shapes', ['PresentationFramework']),
    ('System.Windows', ['PresentationFramework', 'PresentationCore', 'WindowsBase']),
    ('System.Data', ['System.Data']),
    ('System.Xml', ['System.Xml']),
    ('System.Drawing', ['System.Drawing']),
    ('System.Diagnostics', ['System']),
    ('System.Collections.Generic', ['mscorlib', 'System', 'System.Core']),
    ('System.IO', ['mscorlib']),
    ('System', ['mscorlib', 'System']),
]

LOOKUP_NAMES = ('f', 'find', 'FindName')


# ---------------------------------------------------------------- file helpers

def read(root, name):
    with io.open(os.path.join(root, name), 'r', encoding='utf-8') as fh:
        return fh.read()


def write(root, name, text):
    with io.open(os.path.join(root, name), 'w', encoding='utf-8', newline='') as fh:
        fh.write(text)


def py_files(root):
    return sorted(n for n in os.listdir(root) if n.endswith('.py'))


def tool_modules(root):
    return [n for n in py_files(root) if n not in NOT_TOOL]


def parse(root, name):
    return ast.parse(read(root, name), filename=name)


def dom(root, name):
    return minidom.parseString(read(root, name).encode('utf-8'))


def all_elements(node):
    if node.nodeType == node.ELEMENT_NODE:
        yield node
    for child in node.childNodes:
        for e in all_elements(child):
            yield e


def theme_keys(root):
    """{x:Key: TargetType or None} for everything in Theme.xaml."""
    out = {}
    for e in all_elements(dom(root, 'Theme.xaml').documentElement):
        key = e.getAttribute('x:Key')
        if key:
            out[key] = e.getAttribute('TargetType') or None
    return out


# ----------------------------------------------------------------------- rules

def rule_xaml_parses(root):
    bad = []
    for name in sorted(n for n in os.listdir(root) if n.endswith('.xaml')):
        try:
            dom(root, name)
        except Exception as ex:
            bad.append(u'%s does not parse as XML: %s' % (name, ex))
    return bad


def rule_pure_modules_are_pure(root):
    bad = []
    for name in [m + '.py' for m in PURE_MODULES]:
        for node in ast.walk(parse(root, name)):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                mods = [node.module or u'']
            for m in mods:
                if m.split('.')[0] in ('System', 'Autodesk', 'clr'):
                    bad.append(u'%s imports %s - the rules modules must have no .NET or Revit in them' % (name, m))
    return bad


def _first_line(tree, predicate):
    lines = [n.lineno for n in ast.walk(tree) if predicate(n)]
    return min(lines) if lines else None


def _is_dotnet_import(node):
    if isinstance(node, ast.ImportFrom):
        return (node.module or u'').split('.')[0] in ('System', 'Autodesk')
    if isinstance(node, ast.Import):
        return any(a.name.split('.')[0] in ('System', 'Autodesk') for a in node.names)
    return False


def _is_clr_import(node):
    if isinstance(node, ast.Import):
        return any(a.name == 'sdp_clr' for a in node.names)
    if isinstance(node, ast.ImportFrom):
        return (node.module or u'') == 'sdp_clr'
    return False


def rule_clr_imported_first(root):
    bad = []
    for name in tool_modules(root):
        if name in ('sdp_clr.py',) or name[:-3] in PURE_MODULES:
            continue
        tree = parse(root, name)
        dotnet = _first_line(tree, _is_dotnet_import)
        if dotnet is None:
            continue
        clr_line = _first_line(tree, _is_clr_import)
        if clr_line is None:
            bad.append(u'%s reaches into System/Autodesk but never imports sdp_clr' % name)
        elif clr_line > dotnet:
            bad.append(u'%s imports sdp_clr (line %d) after a System/Autodesk import (line %d)'
                       % (name, clr_line, dotnet))
    return bad


def _referenced_assemblies(root):
    for node in parse(root, 'sdp_clr.py').body:
        if isinstance(node, ast.Assign) and any(getattr(t, 'id', '') == '_ASSEMBLIES' for t in node.targets):
            return [e.value for e in node.value.elts]
    return []


def rule_assemblies_referenced(root):
    have = _referenced_assemblies(root)
    bad = []
    if not have:
        return [u'sdp_clr._ASSEMBLIES could not be read']
    for a in have:
        if a in ('RevitAPI', 'RevitAPIUI'):
            bad.append(u'sdp_clr references %s - pyRevit has already loaded it' % a)
    for name in tool_modules(root):
        for node in ast.walk(parse(root, name)):
            if isinstance(node, ast.ImportFrom):
                mods = [node.module or u'']
            elif isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            else:
                continue
            for m in mods:
                if not m.startswith('System'):
                    continue
                need = None
                for prefix, assemblies in ASSEMBLY_FOR:
                    if m == prefix or m.startswith(prefix + '.'):
                        need = assemblies
                        break
                if need is None:
                    bad.append(u'%s imports %s, which ASSEMBLY_FOR does not know - add it' % (name, m))
                elif not any(a in have for a in need):
                    bad.append(u'%s imports %s but sdp_clr references none of %s' % (name, m, need))
    return bad


def _layout_files(root):
    return [n for n in sorted(os.listdir(root)) if n.endswith('.xaml') and n != 'Theme.xaml']


def rule_no_static_resource_in_layouts(root):
    return [u'%s uses StaticResource (Theme.xaml is merged AFTER the layout is parsed)' % n
            for n in _layout_files(root) if 'StaticResource' in read(root, n)]


def rule_dynamic_keys_exist(root):
    keys = theme_keys(root)
    bad = []
    for n in _layout_files(root):
        for k in re.findall(r'\{DynamicResource\s+([A-Za-z0-9_]+)\}', read(root, n)):
            if k not in keys:
                bad.append(u'%s asks for DynamicResource %s, which Theme.xaml does not define' % (n, k))
    return bad


def rule_style_targets_match(root):
    keys = theme_keys(root)
    bad = []
    for n in _layout_files(root):
        for e in all_elements(dom(root, n).documentElement):
            style = e.getAttribute('Style')
            m = re.match(r'^\{DynamicResource\s+([A-Za-z0-9_]+)\}$', style or u'')
            if not m:
                continue
            target = keys.get(m.group(1))
            if target and target != e.localName:
                bad.append(u'%s: <%s> uses style %s whose TargetType is %s' % (n, e.localName, m.group(1), target))
    return bad


def _xaml_names(root):
    """Names a FindName can legitimately reach: the layouts, plus the template parts
    in Theme.xaml, which are found through a control's own Template.FindName."""
    names = set()
    for n in _layout_files(root) + ['Theme.xaml']:
        for e in all_elements(dom(root, n).documentElement):
            v = e.getAttribute('x:Name')
            if v:
                names.add(v)
    return names


def rule_lookups_have_names(root):
    names = _xaml_names(root)
    bad = []
    for name in tool_modules(root):
        for node in ast.walk(parse(root, name)):
            if isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant) \
                    and isinstance(node.args[0].value, str):
                fn = node.func
                called = fn.id if isinstance(fn, ast.Name) else getattr(fn, 'attr', None)
                if called in LOOKUP_NAMES and node.args[0].value not in names:
                    bad.append(u'%s looks up "%s", which no layout names' % (name, node.args[0].value))
    tree = parse(root, 'sdp_ui.py')
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(getattr(t, 'id', '') == 'GRIPS' for t in node.targets):
            for pair in node.value.elts:
                if pair.elts[0].value not in names:
                    bad.append(u'sdp_ui.GRIPS lists %s, which no layout names' % pair.elts[0].value)
    return bad


def _code_only(text):
    """Source with strings and comments blanked, so a rule reads CODE, never prose."""
    import tokenize
    out = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type in (tokenize.STRING, tokenize.COMMENT):
                out.append(u'""')
            else:
                out.append(tok.string)
            out.append(u' ')
    except Exception:
        return text
    return u''.join(out)


def rule_banned_syntax(root):
    bad = []
    for name in py_files(root):
        if name in NOT_TOOL and name != 'script.py':
            continue
        tree = parse(root, name)
        code = _code_only(read(root, name))
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr):
                bad.append(u'%s line %d: f-string' % (name, node.lineno))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'print':
                bad.append(u'%s line %d: print' % (name, node.lineno))
        for fn in ast.walk(tree):
            if isinstance(fn, ast.FunctionDef) and fn.name != 'eid_value':
                for node in ast.walk(fn):
                    if isinstance(node, ast.Attribute) and node.attr == 'IntegerValue':
                        bad.append(u'%s line %d: bare .IntegerValue (use eid_value)' % (name, node.lineno))
        for node in tree.body:
            for sub_node in ast.walk(node):
                if isinstance(sub_node, ast.Attribute) and sub_node.attr == 'IntegerValue' \
                        and not isinstance(node, ast.FunctionDef) and not isinstance(node, ast.ClassDef):
                    bad.append(u'%s line %d: module-level .IntegerValue' % (name, sub_node.lineno))
        if re.search(r'\bUriSource\b', code):
            bad.append(u'%s: UriSource (System.Uri moved assemblies in 2025 - load icons from bytes)' % name)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or u'') == 'System' \
                    and any(a.name == 'Uri' for a in node.names):
                bad.append(u'%s line %d: from System import Uri' % (name, node.lineno))
    return bad


def rule_ascii_only(root):
    bad = []
    for name in py_files(root):
        text = read(root, name)
        for i, line in enumerate(text.splitlines(), 1):
            if any(ord(c) > 127 for c in line):
                bad.append(u'%s line %d: non-ASCII character (write it as a \\u escape)' % (name, i))
                break
    return bad


def rule_no_duplicate_definitions(root):
    bad = []
    for name in tool_modules(root):
        tree = parse(root, name)
        seen = {}
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                if node.name in seen:
                    bad.append(u'%s defines %s twice (the last one silently wins)' % (name, node.name))
                seen[node.name] = True
            if isinstance(node, ast.ClassDef):
                methods = {}
                for item in node.body:
                    if isinstance(item, ast.FunctionDef):
                        if item.name in methods:
                            bad.append(u'%s: %s.%s defined twice' % (name, node.name, item.name))
                        methods[item.name] = True
    return bad


class _InitWalker(object):
    """Replays __init__ in source order, following self.method() calls where they
    happen, and reports any self.attribute read before anything has set it."""

    def __init__(self, cls):
        self.methods = {}
        self.class_names = set()
        for item in cls.body:
            if isinstance(item, ast.FunctionDef):
                self.methods[item.name] = item
                self.class_names.add(item.name)
            elif isinstance(item, ast.Assign):
                for t in item.targets:
                    if isinstance(t, ast.Name):
                        self.class_names.add(t.id)
        self.set = set()
        self.problems = []
        self.stack = []

    def run(self):
        init = self.methods.get('__init__')
        if init is not None:
            self.stack.append('__init__')
            self.visit_body(init.body)
        return self.problems

    def visit_body(self, body):
        for stmt in body:
            self.visit(stmt)

    def visit(self, node):
        if isinstance(node, (ast.FunctionDef, ast.Lambda, ast.ClassDef)):
            return                       # handlers being wired, not work being done
        if isinstance(node, ast.Assign):
            self.visit(node.value)
            for t in node.targets:
                self.write_target(t)
            return
        if isinstance(node, ast.AugAssign):
            self.visit(node.value)
            self.read_target(node.target)
            self.write_target(node.target)
            return
        if isinstance(node, ast.Call):
            for a in node.args:
                self.visit(a)
            for k in node.keywords:
                self.visit(k.value)
            fn = node.func
            if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name) and fn.value.id == 'self':
                target = self.methods.get(fn.attr)
                if target is not None and fn.attr not in self.stack:
                    self.stack.append(fn.attr)
                    self.visit_body(target.body)
                    self.stack.pop()
                elif target is None:
                    self.read_attr(fn)
            else:
                self.visit(fn)
            return
        if isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id == 'self':
                self.read_attr(node)
            else:
                self.visit(node.value)
            return
        for child in ast.iter_child_nodes(node):
            self.visit(child)

    def read_attr(self, node):
        name = node.attr
        if name in self.set or name in self.class_names:
            return
        self.problems.append(u'line %d: self.%s is read before anything has set it (via %s)'
                             % (node.lineno, name, u' > '.join(self.stack)))

    def read_target(self, t):
        if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == 'self':
            self.read_attr(t)

    def write_target(self, t):
        if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == 'self':
            self.set.add(t.attr)
        elif isinstance(t, (ast.Tuple, ast.List)):
            for e in t.elts:
                self.write_target(e)
        elif isinstance(t, ast.Attribute):
            self.visit(t.value)
        else:
            for child in ast.iter_child_nodes(t):
                self.visit(child)


def rule_init_attributes_set(root):
    bad = []
    for name in tool_modules(root):
        for node in ast.walk(parse(root, name)):
            if isinstance(node, ast.ClassDef):
                for p in _InitWalker(node).run():
                    bad.append(u'%s %s: %s' % (name, node.name, p))
    return bad


def _literal_dict(tree, var):
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, 'id', '') == var for t in node.targets):
            return ast.literal_eval(node.value)
    return None


def rule_palette_complete(root):
    tree = parse(root, 'sdp_theme.py')
    keys = _literal_dict(tree, 'KEYS')
    dark = _literal_dict(tree, 'DARK')
    light = _literal_dict(tree, 'LIGHT')
    bad = []
    if keys is None or dark is None or light is None:
        return [u'sdp_theme KEYS/DARK/LIGHT could not be read']
    if set(dark) != set(keys):
        bad.append(u'DARK keys differ from KEYS: %s' % sorted(set(dark) ^ set(keys)))
    if set(light) != set(keys):
        bad.append(u'LIGHT keys differ from KEYS: %s' % sorted(set(light) ^ set(keys)))
    defined = theme_keys(root)
    for k in keys:
        if k not in defined:
            bad.append(u'Theme.xaml has no brush %s' % k)
    return bad


def rule_resource_keys_exist(root):
    """Every string in the code that names a brush or a style must exist."""
    defined = theme_keys(root)
    bad = []
    for name in tool_modules(root):
        if name == 'sdp_theme.py':
            continue
        for node in ast.walk(parse(root, name)):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                v = node.value
                if re.match(r'^[A-Z][A-Za-z]*Brush$', v) or re.match(r'^Btn[A-Z][A-Za-z]*$', v):
                    if v not in defined:
                        bad.append(u'%s line %d: resource key "%s" is not in Theme.xaml' % (name, node.lineno, v))
    return bad


def rule_no_dead_handlers(root):
    bad = []
    for name in tool_modules(root):
        for cls in ast.walk(parse(root, name)):
            if not isinstance(cls, ast.ClassDef):
                continue
            methods = set(i.name for i in cls.body if isinstance(i, ast.FunctionDef))
            for node in ast.walk(cls):
                if isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Add) \
                        and isinstance(node.value, ast.Attribute) \
                        and isinstance(node.value.value, ast.Name) and node.value.value.id == 'self':
                    if node.value.attr not in methods:
                        bad.append(u'%s %s wires self.%s, which the class does not define'
                                   % (name, cls.name, node.value.attr))
    return bad


def rule_undefined_globals(root):
    """symtable: every global name a function reaches for exists in its module."""
    import builtins
    allowed = set(dir(builtins)) | set(['unicode', 'long', 'basestring', '__revit__'])
    bad = []
    for name in tool_modules(root) + [LOADER]:
        text = read(root, name)
        table = symtable.symtable(text, name, 'exec')
        defined = set()
        for sym in table.get_symbols():
            if sym.is_assigned() or sym.is_imported() or sym.is_namespace():
                defined.add(sym.get_name())

        def walk(t):
            for child in t.get_children():
                for sym in child.get_symbols():
                    if sym.is_global() and sym.is_referenced():
                        n = sym.get_name()
                        if n not in defined and n not in allowed and not n.startswith('__'):
                            bad.append(u'%s: %s uses %s, which is not defined' % (name, child.get_name(), n))
                walk(child)
        walk(table)
    return sorted(set(bad))


def rule_loader_is_thin(root):
    text = read(root, LOADER)
    tree = parse(root, LOADER)
    bad = []
    if not re.search(r'^__persistentengine__\s*=\s*True', text, re.M):
        bad.append(u'script.py must set __persistentengine__ = True (modeless window)')
    if 'AddReference' in _code_only(text) or re.search(r'^\s*import clr\b', text, re.M):
        bad.append(u'script.py must not reference assemblies itself - sdp_clr does that')
    imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
    names = []
    for n in imports:
        names.extend([a.name for a in n.names] if isinstance(n, ast.Import) else [n.module or u''])
    for want in ('sdp_clr', 'sdp_window'):
        if want not in names:
            bad.append(u'script.py never imports %s' % want)
    return bad


def rule_module_prefix(root):
    """Modules share one namespace per engine: a bare 'theme.py' would be shadowed
    by, or would shadow, another RevoBIM tool's."""
    return [u'%s is not prefixed sdp_ - it can collide with another tool in a shared engine' % n
            for n in py_files(root) if n not in NOT_TOOL and not n.startswith('sdp_')]


def rule_version_and_names_agree(root):
    bad = []
    ver = re.search(r'__version__\s*=\s*u?"([^"]+)"', read(root, 'sdp_version.py'))
    tool = re.search(r'TOOL_NAME\s*=\s*u?"([^"]+)"', read(root, 'sdp_version.py'))
    if not ver or not tool:
        return [u'sdp_version does not define __version__ and TOOL_NAME']
    log = re.search(r'^##\s+([0-9][0-9.]*)', read(root, 'CHANGELOG.md'), re.M)
    if not log or log.group(1) != ver.group(1):
        bad.append(u'CHANGELOG.md top entry (%s) does not match __version__ (%s)'
                   % (log.group(1) if log else None, ver.group(1)))
    folder = os.path.basename(os.path.abspath(root))
    if folder != tool.group(1) + '.pushbutton':
        bad.append(u'folder "%s" is not "%s.pushbutton" - pyRevit names the ribbon item after it'
                   % (folder, tool.group(1)))
    title = re.search(r"__title__\s*=\s*'([^']+)'", read(root, LOADER))
    if not title or title.group(1) != tool.group(1):
        bad.append(u'script.py __title__ does not match TOOL_NAME')
    yml = read(root, 'bundle.yaml')
    if not re.search(r'^title:\s*%s\s*$' % re.escape(tool.group(1)), yml, re.M):
        bad.append(u'bundle.yaml title does not match TOOL_NAME')
    if '\n' in re.search(r'^title:.*$', yml, re.M).group(0).strip():
        bad.append(u'bundle.yaml title must be a single line')
    if 'Text="' + tool.group(1) + '"' not in read(root, 'SpaceDataPush.xaml'):
        bad.append(u'SpaceDataPush.xaml ToolText does not show TOOL_NAME')
    if not os.path.exists(os.path.join(root, 'icon.png')):
        bad.append(u'icon.png is missing')
    if os.path.exists(os.path.join(root, '..', 'bundle.yaml')):
        bad.append(u'a pulldown bundle.yaml is shipped - it would overwrite the existing Routines pulldown')
    return bad


def rule_theme_follows_revit(root):
    text = read(root, 'sdp_theme.py')
    m = re.search(r'def revit_theme_name\(.*?(?=\ndef )', text, re.S)
    body = _code_only(m.group(0)) if m else u''
    bad = []
    if not re.search(r'value\s+is\s+not\s+None', body):
        bad.append(u'revit_theme_name must test "is not None" - UITheme.Dark is 0, so truthiness reads Dark as a failed read')
    if not re.search(r'getattr\s*\(\s*revit_ui', body):
        bad.append(u'revit_theme_name must reach UIThemeManager by getattr (it only exists from Revit 2024)')
    win = read(root, 'sdp_window.py')
    if 'revit_theme_name' not in win or 'resolve_theme' not in win:
        bad.append(u'the window does not resolve its theme from Revit')
    if 'Activated' not in win:
        bad.append(u'the window does not re-read Revit\'s theme when it comes to the front')
    return bad


def rule_easter_egg_wired(root):
    bad = []
    win = read(root, 'sdp_window.py')
    if not re.search(r'attach_egg\s*\(', _code_only(win)):
        bad.append(u'sdp_window never calls attach_egg')
    if 'self.logo_host' not in win or "f('LogoHost')" not in win:
        bad.append(u'the easter egg is not wired to LogoHost')
    for e in all_elements(dom(root, 'SpaceDataPush.xaml').documentElement):
        if e.getAttribute('x:Name') == 'LogoHost' and not e.getAttribute('Background'):
            bad.append(u'LogoHost has no Background, so clicks between its children fall through')
    ui = read(root, 'sdp_ui.py')
    for want in ('EGG_MIN_GAP_MS = 250', 'EGG_MAX_GAP_MS = 2000', 'EGG_CLICKS = 3', 'Timestamp'):
        if want not in ui:
            bad.append(u'sdp_ui click counter lost: %s' % want)
    code = _code_only(ui)
    if re.search(r'\battach\s*\(', code):
        bad.append(u'sdp_ui calls the hook\'s own attach() - it may arm controls other than the logo')
    if 'PreviewMouseLeftButtonDown' not in code:
        bad.append(u'the click counter is not wired to the logo')
    counter = re.search(r'class ClickCounter.*?(?=\ndef )', ui, re.S)
    if not counter or 'self.count >= EGG_CLICKS' not in counter.group(0):
        bad.append(u'the click counter does not require EGG_CLICKS clicks')
    return bad


def rule_window_hygiene(root):
    """The rules that came out of earlier tools, kept in one place."""
    bad = []
    ui = read(root, 'sdp_ui.py')
    if 'XamlReader.Parse' not in ui or 'MergedDictionaries.Add' not in ui:
        bad.append(u'sdp_ui.load_window must parse the layout then merge Theme.xaml')
    xaml = read(root, 'SpaceDataPush.xaml')
    if 'WindowStyle="None"' not in xaml:
        bad.append(u'SpaceDataPush.xaml lost WindowStyle="None"')
    # The window is opaque on purpose. A layered window (AllowsTransparency="True")
    # paints nothing where its content does not reach, and the DPI rounding band
    # around its edge on a scaled display then shows Revit straight through - which
    # on a light canvas is a white border round the tool. It also costs the GPU
    # compositing, which is what made the window flash as it opened.
    window_tag = xaml[:xaml.index('>')]
    if 'AllowsTransparency="True"' in window_tag:
        bad.append(u'the Window is layered (AllowsTransparency="True") - its edge shows Revit through it')
    if 'Background="Transparent"' in window_tag:
        bad.append(u'the Window background is Transparent - any edge the content does not cover'
                   u' shows Revit through it')
    if not re.search(r'Background="\{DynamicResource \w+Brush\}"', window_tag):
        bad.append(u'the Window has no theme background brush of its own')
    for e in all_elements(dom(root, 'SpaceDataPush.xaml').documentElement):
        if e.getAttribute('x:Name') == 'Frame' and e.getAttribute('CornerRadius') not in ('', '0'):
            bad.append(u'the Frame is rounded, but an opaque window has square corners behind it')
    win_py = read(root, 'sdp_window.py')
    if 'Window.BackgroundProperty' not in win_py:
        bad.append(u'the window background is not re-pointed at the palette when the theme is swapped')
    if 'VerticalAlignment="Baseline"' in xaml:
        bad.append(u'VerticalAlignment="Baseline" makes XamlReader.Load throw silently')
    win = _code_only(read(root, 'sdp_window.py'))
    if 'WaitOne' in win or 'Thread.Sleep' in win:
        bad.append(u'the window must never wait on the ExternalEvent')
    runner = read(root, 'sdp_runner.py')
    if 'discard(job)' not in runner or 'Pending' not in runner:
        bad.append(u'sdp_runner must remove only a refused job and treat Pending as queued')
    for n in ('Frame',):
        if 'x:Name="%s"' % n not in xaml:
            bad.append(u'layout lost x:Name=%s' % n)
    return bad


def rule_search_in_dropdowns(root):
    """Every list the user picks from narrows as they type: the ComboBox template
    carries the editable text box, and every ComboBox made in code is wrapped."""
    bad = []
    theme = read(root, 'Theme.xaml')
    if 'PART_EditableTextBox' not in theme:
        bad.append(u'Theme.xaml ComboBox template has no PART_EditableTextBox, so it cannot be typed in')
    if 'IsEditable' not in theme:
        bad.append(u'Theme.xaml ComboBox template has no IsEditable trigger')
    ui = read(root, 'sdp_ui.py')
    if 'class FilterCombo' not in ui:
        bad.append(u'sdp_ui has no FilterCombo')
    else:
        fc = re.search(r'class FilterCombo.*?(?=\ndef keyword_filter)', ui, re.S).group(0)
        for want in ('IsEditable = True', 'IsTextSearchEnabled = False', 'IsDropDownOpen = True'):
            if want not in fc:
                bad.append(u'FilterCombo lost: %s' % want)
        if 'def revert' not in fc:
            bad.append(u'FilterCombo never puts an unmatched typed value back')
    win = read(root, 'sdp_window.py')
    for var in re.findall(r'([\w.]+)\s*=\s*ComboBox\(\)', win):
        if not re.search(r'UI\.FilterCombo\(\s*%s\b' % re.escape(var), win):
            bad.append(u'%s is a ComboBox that is not wrapped in FilterCombo, so it cannot be typed in' % var)
    for var in re.findall(r"([\w.]+)\s*=\s*f\('CatCombo'\)", win):
        if not re.search(r'UI\.FilterCombo\(\s*%s\b' % re.escape(var), win):
            bad.append(u'the category ComboBox (%s) is not wrapped in FilterCombo' % var)
    if re.search(r"f\('\w*Search'\)", win):
        bad.append(u'a separate search box is still wired - the search belongs in the dropdown')
    return bad


def rule_no_system_frame(root):
    """Windows draws its own thin frame round a top-level window in the system
    colour - white on a light Windows theme - and WindowStyle="None" does not remove
    it. Both routes that do have to stay wired."""
    ui = read(root, 'sdp_ui.py')
    code = _code_only(ui)
    bad = []
    if 'WindowChrome' not in code:
        bad.append(u'no WindowChrome, so WPF does not own the non-client area')
    for want in ('GlassFrameThickness', 'ResizeBorderThickness', 'CaptionHeight'):
        if want not in code:
            bad.append(u'the WindowChrome does not clear %s' % want)
    if not re.search(r'WS_BORDER|WS_THICKFRAME', code):
        bad.append(u'the window style border bits are not stripped')
    if 'SourceInitialized' not in code:
        bad.append(u'strip_border is not wired to SourceInitialized, so it runs with no handle')
    if 'DWMWA_BORDER_COLOR' not in code:
        bad.append(u'DWM is not asked for no border colour (Windows 11 draws one of its own)')
    win = read(root, 'sdp_window.py')
    if not re.search(r'UI\s*\.\s*frameless\s*\(', _code_only(win)):
        bad.append(u'the window never calls frameless()')
    return bad


def rule_no_dropdown_churn(root):
    """A dropdown must not rebuild itself when nothing has changed, and the window
    must not open with the keyboard inside one: both look like the tool fidgeting
    with its own boxes while it starts."""
    bad = []
    ui = read(root, 'sdp_ui.py')
    fill = re.search(r'    def fill\(self.*?(?=\n    def current_items)', ui, re.S)
    if not fill:
        return [u'FilterCombo.fill is not where the check expects it']
    body = _code_only(fill.group(0))
    guard = re.search(r'same_items\s+and[^\n]*\n\s*return', body)
    if not guard:
        bad.append(u'FilterCombo.fill rebuilds the list without comparing it first')
    if not re.search(r'if\s+query\s*:\s*\n\s*try\s*:', _code_only(ui)):
        bad.append(u'a dropdown opens itself even when nothing has been typed')
    win = read(root, 'sdp_window.py')
    show = re.search(r'    def show\(self.*?(?=\n\n# )', win, re.S)
    if not show or 'pick_space_btn.Focus()' not in show.group(0):
        bad.append(u'the window does not put focus on a button as it opens')
    status = re.search(r'    def set_status.*?(?=\n    def )', win, re.S)
    if not status or 'return' not in status.group(0):
        bad.append(u'set_status repaints even when the text has not changed')
    return bad


def rule_settings_round_trip(root):
    """Everything the window saves has a default, and everything with a default is
    written out - a key missing from either list is silently forgotten."""
    logic = parse(root, 'sdp_logic.py')
    defaults = _literal_dict(logic, 'DEFAULTS')
    order = _literal_dict(logic, 'KEY_ORDER')
    bad = []
    if defaults is None or order is None:
        return [u'sdp_logic DEFAULTS/KEY_ORDER could not be read']
    for k in defaults:
        if k not in order:
            bad.append(u'%s has a default but KEY_ORDER never writes it out' % k)
    for k in order:
        if k not in defaults:
            bad.append(u'KEY_ORDER writes %s, which has no default' % k)
    win = read(root, 'sdp_window.py')
    collect = re.search(r'def collect_settings.*?(?=\n    def )', win, re.S)
    if not collect:
        return bad + [u'sdp_window has no collect_settings']
    for k in re.findall(r"s\['(\w+)'\]\s*=", collect.group(0)):
        if k not in defaults:
            bad.append(u'the window saves "%s", which sdp_logic has no default for' % k)
    for want in ('theme', 'category', 'rows', 'overwrite', 'skip_blank', 'keep_picking',
                 'hide_window', 'win_w', 'win_h'):
        if want not in collect.group(0):
            bad.append(u'collect_settings no longer remembers %s' % want)
    if 'self.save()' not in re.search(r'def on_closing.*?(?=\n    def )', win, re.S).group(0):
        bad.append(u'settings are not saved when the window closes')
    return bad


def rule_returns_after_picking(root):
    """When picking finishes the window comes back, ready for the next space."""
    win = read(root, 'sdp_window.py')
    bad = []
    done = re.search(r'def push_done.*?(?=\n    def come_back)', win, re.S)
    if not done or 'self.come_back()' not in done.group(0):
        bad.append(u'push_done does not bring the window back')
    back = re.search(r'def come_back.*?(?=\n    # )', win, re.S)
    if not back:
        return bad + [u'sdp_window has no come_back']
    body = back.group(0)
    for want in ('Show()', 'Activate()', 'pick_space_btn'):
        if want not in body:
            bad.append(u'come_back lost: %s' % want)
    return bad


def rule_stub_load(root):
    """Every module loads against the stub API, each name in its real namespace."""
    sys.path.insert(0, root)
    bad = []
    try:
        import bench_stub as S
        S.install()
        for mod in ('sdp_clr', 'sdp_logic', 'sdp_version', 'sdp_theme', 'sdp_model',
                    'sdp_runner', 'sdp_ui', 'sdp_window'):
            S.purge()
            try:
                __import__(mod)
            except Exception:
                bad.append(u'%s failed to load against the stub API: %s'
                           % (mod, traceback.format_exc().strip().splitlines()[-1]))
    finally:
        try:
            S.purge()
            S.uninstall()
        except Exception:
            pass
        if root in sys.path:
            sys.path.remove(root)
    return bad


RULES = [
    ('xaml_parses', rule_xaml_parses),
    ('pure_modules_are_pure', rule_pure_modules_are_pure),
    ('clr_imported_first', rule_clr_imported_first),
    ('assemblies_referenced', rule_assemblies_referenced),
    ('no_static_resource_in_layouts', rule_no_static_resource_in_layouts),
    ('dynamic_keys_exist', rule_dynamic_keys_exist),
    ('style_targets_match', rule_style_targets_match),
    ('lookups_have_names', rule_lookups_have_names),
    ('banned_syntax', rule_banned_syntax),
    ('ascii_only', rule_ascii_only),
    ('no_duplicate_definitions', rule_no_duplicate_definitions),
    ('init_attributes_set', rule_init_attributes_set),
    ('palette_complete', rule_palette_complete),
    ('resource_keys_exist', rule_resource_keys_exist),
    ('no_dead_handlers', rule_no_dead_handlers),
    ('undefined_globals', rule_undefined_globals),
    ('loader_is_thin', rule_loader_is_thin),
    ('module_prefix', rule_module_prefix),
    ('version_and_names_agree', rule_version_and_names_agree),
    ('theme_follows_revit', rule_theme_follows_revit),
    ('easter_egg_wired', rule_easter_egg_wired),
    ('window_hygiene', rule_window_hygiene),
    ('search_in_dropdowns', rule_search_in_dropdowns),
    ('no_system_frame', rule_no_system_frame),
    ('no_dropdown_churn', rule_no_dropdown_churn),
    ('settings_round_trip', rule_settings_round_trip),
    ('returns_after_picking', rule_returns_after_picking),
    ('stub_load', rule_stub_load),
]


def run_rules(root, only=None):
    out = {}
    for name, fn in RULES:
        if only and name != only:
            continue
        try:
            out[name] = fn(root)
        except Exception:
            out[name] = [u'the rule itself raised: %s' % traceback.format_exc().strip().splitlines()[-1]]
    return out


# -------------------------------------------------------------------- selftest

def sub(text, old, new, count=1):
    if old not in text:
        raise AssertionError(u'selftest cannot find %r to break it' % old)
    return text.replace(old, new, count)


def append(text, extra):
    return text + u'\n' + extra + u'\n'


# (rule, description, file, mutation)
BREAKAGES = [
    ('xaml_parses', 'a -- inside an XML comment', 'SpaceDataPush.xaml',
     lambda t: sub(t, '</Window>', '<!-- a -- b --></Window>')),
    ('pure_modules_are_pure', 'System import in sdp_logic', 'sdp_logic.py',
     lambda t: append(t, 'from System import Action')),
    ('clr_imported_first', 'sdp_ui without sdp_clr', 'sdp_ui.py',
     lambda t: sub(t, 'import sdp_clr\n', '')),
    ('clr_imported_first', 'sdp_clr imported after System', 'sdp_ui.py',
     lambda t: sub(sub(t, 'import sdp_clr\n', ''), 'from System import Action', 'from System import Action\nimport sdp_clr')),
    ('assemblies_referenced', 'System.Windows.Forms not referenced', 'sdp_clr.py',
     lambda t: sub(t, "'System.Windows.Forms',", '')),
    ('assemblies_referenced', 'RevitAPI referenced', 'sdp_clr.py',
     lambda t: sub(t, "'WindowsBase',", "'WindowsBase', 'RevitAPI',")),
    ('no_static_resource_in_layouts', 'StaticResource in the layout', 'SpaceDataPush.xaml',
     lambda t: sub(t, '{DynamicResource BlueBrush}', '{StaticResource BlueBrush}')),
    ('dynamic_keys_exist', 'a key Theme.xaml lacks', 'SpaceDataPush.xaml',
     lambda t: sub(t, '{DynamicResource BlueBrush}', '{DynamicResource NopeBrush}')),
    ('style_targets_match', 'a Button style on a TextBlock', 'SpaceDataPush.xaml',
     lambda t: sub(t, '<TextBlock x:Name="StatusText"',
                   '<TextBlock Style="{DynamicResource BtnGreen}" x:Name="StatusText"')),
    ('lookups_have_names', 'a lookup with no x:Name', 'sdp_window.py',
     lambda t: sub(t, "f('AddRowBtn')", "f('AddRowBtnX')")),
    ('lookups_have_names', 'a grip with no x:Name', 'sdp_ui.py',
     lambda t: sub(t, "('GripT', 'T')", "('GripTx', 'T')")),
    ('banned_syntax', 'an f-string', 'sdp_logic.py', lambda t: append(t, 'x = f"{1}"')),
    ('banned_syntax', 'a print', 'sdp_logic.py', lambda t: append(t, 'print("x")')),
    ('banned_syntax', 'a bare IntegerValue', 'sdp_window.py',
     lambda t: append(t, 'def _bad(e):\n    return e.IntegerValue')),
    ('banned_syntax', 'System.Uri', 'sdp_ui.py', lambda t: append(t, 'from System import Uri')),
    ('banned_syntax', 'UriSource', 'sdp_ui.py', lambda t: append(t, 'x = 1\ny = bmp.UriSource')),
    ('ascii_only', 'a non-ASCII arrow', 'sdp_logic.py', lambda t: append(t, '# \u2192 arrow')),
    ('no_duplicate_definitions', 'to_text defined twice', 'sdp_logic.py',
     lambda t: append(t, 'def to_text(v):\n    return u""')),
    ('no_duplicate_definitions', 'a method defined twice', 'sdp_window.py',
     lambda t: sub(t, '    def get_theme_name(self):', '    def touch(self):\n        pass\n\n    def get_theme_name(self):')),
    ('init_attributes_set', 'an attribute read before it is set', 'sdp_window.py',
     lambda t: sub(t, '        self.hold = None\n', '')),
    ('palette_complete', 'LIGHT missing a key', 'sdp_theme.py',
     lambda t: sub(t, "    'ThumbBrush': '#B0B0B8',\n", '')),
    ('resource_keys_exist', 'a misspelt brush', 'sdp_window.py',
     lambda t: sub(t, "u'ok': 'GreenBrush'", "u'ok': 'GreeenBrush'")),
    ('no_dead_handlers', 'a handler that does not exist', 'sdp_window.py',
     lambda t: sub(t, 'def on_theme_click(self', 'def on_theme_clik(self')),
    ('undefined_globals', 'a deleted helper', 'sdp_window.py',
     lambda t: sub(t, 'def show_again(window)', 'def show_agan(window)')),
    ('loader_is_thin', 'loader loses persistent engine', 'script.py',
     lambda t: sub(t, '__persistentengine__ = True', '__persistentengine__ = False')),
    ('loader_is_thin', 'loader references assemblies itself', 'script.py',
     lambda t: append(t, 'import clr')),
    ('module_prefix', 'a bare theme.py', 'theme.py', lambda t: u'# stray\n'),
    ('version_and_names_agree', 'changelog out of step', 'CHANGELOG.md',
     lambda t: re.sub(r'^##\s+[0-9][0-9.]*', '## 9.9.9', t, count=1, flags=re.M)),
    ('version_and_names_agree', 'bundle title differs', 'bundle.yaml',
     lambda t: sub(t, 'title: Space Data Push', 'title: Space 2 Element')),
    ('theme_follows_revit', 'truthiness instead of is not None', 'sdp_theme.py',
     lambda t: sub(t, 'if value is not None:', 'if value:')),
    ('theme_follows_revit', 'window never re-reads the theme', 'sdp_window.py',
     lambda t: sub(t, 'self.window.Activated += self.on_activated', 'pass')),
    ('easter_egg_wired', 'attach_egg call removed', 'sdp_window.py',
     lambda t: sub(t, 'UI.attach_egg(', 'UI.attach_egx(')),
    ('easter_egg_wired', 'logo has no background', 'SpaceDataPush.xaml',
     lambda t: sub(t, 'VerticalAlignment="Center" Background="Transparent"\n', 'VerticalAlignment="Center"\n')),
    ('easter_egg_wired', 'the hook attaches itself instead of counting clicks', 'sdp_ui.py',
     lambda t: sub(t, '    counter = ClickCounter(window, hook, theme_getter)',
                   '    hook.attach(window, logo)\n    counter = ClickCounter(window, hook, theme_getter)')),
    ('easter_egg_wired', 'one click is enough', 'sdp_ui.py',
     lambda t: sub(t, 'if self.count >= EGG_CLICKS:', 'if self.count >= 1:')),
    ('easter_egg_wired', 'click gap changed', 'sdp_ui.py',
     lambda t: sub(t, 'EGG_MIN_GAP_MS = 250', 'EGG_MIN_GAP_MS = 25')),
    ('window_hygiene', 'a transparent window background', 'SpaceDataPush.xaml',
     lambda t: sub(t, 'Background="{DynamicResource WindowBrush}"', 'Background="Transparent"')),
    ('window_hygiene', 'a layered window', 'SpaceDataPush.xaml',
     lambda t: sub(t, 'AllowsTransparency="False"', 'AllowsTransparency="True"')),
    ('window_hygiene', 'rounded corners on an opaque window', 'SpaceDataPush.xaml',
     lambda t: sub(t, '<Border x:Name="Frame" CornerRadius="0"', '<Border x:Name="Frame" CornerRadius="6"')),
    ('window_hygiene', 'the background is not re-pointed on a theme swap', 'sdp_window.py',
     lambda t: sub(t, "            self.window.SetResourceReference(Window.BackgroundProperty, 'WindowBrush')",
                   '            pass')),
    ('window_hygiene', 'Baseline alignment', 'SpaceDataPush.xaml',
     lambda t: sub(t, '<TextBlock x:Name="StatusText"', '<TextBlock VerticalAlignment="Baseline" x:Name="StatusText"')),
    ('window_hygiene', 'runner wipes on refusal', 'sdp_runner.py',
     lambda t: sub(t, 'self.queue.discard(job)', 'self.queue.drain()', 2)),
    ('search_in_dropdowns', 'the editable text box removed from the template', 'Theme.xaml',
     lambda t: sub(t, 'PART_EditableTextBox', 'PART_SomethingElse', 3)),
    ('search_in_dropdowns', 'a row ComboBox left unwrapped', 'sdp_window.py',
     lambda t: sub(t, 'row.src_filter = UI.FilterCombo(row.src_box, on_src)', 'row.src_filter = None')),
    ('search_in_dropdowns', 'typing no longer opens the list', 'sdp_ui.py',
     lambda t: sub(t, 'self.combo.IsDropDownOpen = True', 'pass')),
    ('no_system_frame', 'frameless never called', 'sdp_window.py',
     lambda t: sub(t, 'self.keep.append(UI.frameless(self.window))', 'pass')),
    ('no_system_frame', 'the style bits are left alone', 'sdp_ui.py',
     lambda t: sub(t, 'WS_BORDER = 0x00800000', 'WS_UNUSED = 0x00800000').replace(
         'WS_BORDER | WS_DLGFRAME | WS_THICKFRAME', '0').replace('WS_THICKFRAME = 0x00040000', '')),
    ('no_system_frame', 'the border strip runs before there is a handle', 'sdp_ui.py',
     lambda t: sub(t, '    window.SourceInitialized += on_source', '    on_source(None, None)')),
    ('no_dropdown_churn', 'the list is rebuilt every time', 'sdp_ui.py',
     lambda t: sub(t, '        if same_items and text_of(self.combo.Text) == text:\n            return\n', '')),
    ('no_dropdown_churn', 'an empty box opens its own list', 'sdp_ui.py',
     lambda t: sub(t, '        if query:\n', '        if True:\n')),
    ('no_dropdown_churn', 'the window opens with focus in a dropdown', 'sdp_window.py',
     lambda t: sub(t, '            self.pick_space_btn.Focus()\n        except Exception:\n            pass\n        self.timer.Start()',
                   '            pass\n        except Exception:\n            pass\n        self.timer.Start()')),
    ('settings_round_trip', 'a saved key with no default', 'sdp_window.py',
     lambda t: sub(t, "        s['theme'] = self.theme_mode", "        s['theme'] = self.theme_mode\n        s['new_thing'] = '1'")),
    ('settings_round_trip', 'the window size is forgotten', 'sdp_window.py',
     lambda t: sub(t, "                s['win_w'] = u'%d' % int(self.window.Width)", '                pass')),
    ('settings_round_trip', 'a default that is never written out', 'sdp_logic.py',
     lambda t: sub(t, "             'skip_blank', 'keep_picking', 'hide_window', 'debug', 'win_w', 'win_h']",
                   "             'skip_blank', 'keep_picking', 'hide_window', 'debug', 'win_w']")),
    ('returns_after_picking', 'the window never comes back', 'sdp_window.py',
     lambda t: sub(t, '        self.come_back()', '        pass')),
    ('returns_after_picking', 'Pick Space is not made ready', 'sdp_window.py',
     lambda t: sub(t, '            self.pick_space_btn.IsDefault = True\n            self.pick_space_btn.Focus()', '            pass')),
    ('stub_load', 'a name imported from the wrong namespace', 'sdp_ui.py',
     lambda t: sub(t, 'from System.Windows.Forms import Screen', 'from System.Windows import Screen')),
]


def selftest():
    good = run_rules(HERE)
    if any(good.values()):
        print(u'the tool itself fails its own rules; fix that first')
        report(good)
        return 1
    tmp = tempfile.mkdtemp()
    caught = 0
    try:
        for rule, why, fname, mutate in BREAKAGES:
            root = os.path.join(tmp, os.path.basename(HERE))
            if os.path.exists(root):
                shutil.rmtree(root)
            shutil.copytree(HERE, root, ignore=shutil.ignore_patterns('__pycache__'))
            path = os.path.join(root, fname)
            original = read(root, fname) if os.path.exists(path) else u''
            try:
                write(root, fname, mutate(original))
            except AssertionError as ex:
                print(u'  %-30s %-44s SELFTEST BROKEN: %s' % (rule, why, ex))
                continue
            found = run_rules(root, only=rule)[rule]
            if found:
                caught += 1
                print(u'  %-30s %-44s caught' % (rule, why))
            else:
                print(u'  %-30s %-44s NOT CAUGHT' % (rule, why))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    rules_hit = set(r for r, _w, _f, _m in BREAKAGES)
    unproved = [n for n, _f in RULES if n not in rules_hit]
    if unproved:
        print(u'\nrules with no breakage to prove them: %s' % u', '.join(unproved))
    if caught != len(BREAKAGES) or unproved:
        print(u'\nselftest FAILED: %d of %d breakages caught' % (caught, len(BREAKAGES)))
        return 1
    print(u'\nselftest passed: all %d breakages caught, every one of the %d rules proved'
          % (len(BREAKAGES), len(RULES)))
    return 0


def report(results):
    bad = 0
    for name, _fn in RULES:
        found = results.get(name)
        if found is None:
            continue
        if found:
            bad += len(found)
            print(u'FAIL  %s' % name)
            for line in found:
                print(u'        %s' % line)
        else:
            print(u'ok    %s' % name)
    return bad


def main():
    if '--selftest' in sys.argv:
        return selftest()
    bad = report(run_rules(HERE))
    print(u'\n%d rules, %d problem(s)' % (len(RULES), bad))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
