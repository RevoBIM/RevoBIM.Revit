# -*- coding: utf-8 -*-
"""Static bench for Click to RVT Element (CPython 3).

    python import_check.py             run every rule on this folder
    python import_check.py --selftest  break the source on purpose, once per
                                       rule, and prove the rule catches it

Every rule reads a folder, so the selftest copies the tool to a temporary
folder, applies one breakage and runs that rule there. A rule whose
breakage is not caught fails the selftest.
"""
import ast
import io
import os
import re
import shutil
import subprocess
import sys
import symtable
import tempfile
import tokenize
import builtins
from xml.dom import minidom

HERE = os.path.dirname(os.path.abspath(__file__))
LAYOUTS = ['ClickToRvt.xaml', 'Settings.xaml']
THEME = 'Theme.xaml'
NO_NET = ('c2r_core.py', 'c2r_version.py', 'c2r_clr.py')
KNOWN_EXT = ('{DynamicResource ', '{Binding', '{TemplateBinding ', '{RelativeSource ', '{x:Null}', '{x:Static ', '{}')

ASSEMBLY_FOR = {
    'System': ['mscorlib', 'System', 'System.Runtime'],
    'System.IO': ['mscorlib', 'System.Runtime'],
    'System.Collections.Generic': ['mscorlib', 'System.Collections', 'System.Runtime'],
    'System.Windows': ['PresentationFramework', 'PresentationCore', 'WindowsBase'],
    'System.Windows.Controls': ['PresentationFramework'],
    'System.Windows.Controls.Primitives': ['PresentationFramework'],
    'System.Windows.Input': ['PresentationCore', 'WindowsBase'],
    'System.Windows.Interop': ['PresentationFramework', 'PresentationCore'],
    'System.Windows.Markup': ['PresentationFramework', 'System.Xaml'],
    'System.Windows.Media': ['PresentationCore'],
    'System.Windows.Media.Animation': ['PresentationCore'],
    'System.Windows.Media.Imaging': ['PresentationCore'],
    'System.Windows.Shapes': ['PresentationFramework'],
    'System.Windows.Threading': ['WindowsBase'],
    'System.Windows.Forms': ['System.Windows.Forms'],
}


# =====================================================================
# helpers
# =====================================================================

def read(d, name):
    with io.open(os.path.join(d, name), encoding='utf-8') as f:
        return f.read()


def write(d, name, text):
    with io.open(os.path.join(d, name), 'w', encoding='utf-8') as f:
        f.write(text)


def modules(d):
    return sorted(n for n in os.listdir(d) if n.startswith('c2r_') and n.endswith('.py'))


def code_only(src):
    """Source with strings and comments blanked, so grep rules read code."""
    out = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type in (tokenize.STRING, tokenize.COMMENT):
                out.append(' ')
            elif tok.type in (tokenize.NEWLINE, tokenize.NL):
                out.append('\n')
            else:
                out.append(tok.string + ' ')
    except Exception:
        return src
    return ''.join(out)


def theme_keys(d):
    dom = minidom.parseString(read(d, THEME).encode('utf-8'))
    keys = {}
    for el in dom.getElementsByTagName('*'):
        k = el.getAttribute('x:Key')
        if k:
            keys[k] = el
    return keys


def xnames(d):
    names = set()
    for n in LAYOUTS + [THEME]:
        names |= set(re.findall(r'x:Name="([^"]+)"', read(d, n)))
    return names


# =====================================================================
# rules - each returns a list of problems
# =====================================================================

def rule_modules_import(d):
    bad = []
    for m in modules(d):
        env = dict(os.environ)
        env['APPDATA'] = tempfile.gettempdir()
        code = 'import sys; sys.path.insert(0, "."); sys.path.append({0!r}); import bench_stubs; ' \
               'bench_stubs.install(); import {1}'.format(HERE, m[:-3])
        p = subprocess.run([sys.executable, '-c', code], cwd=d, capture_output=True, text=True, env=env)
        if p.returncode != 0:
            bad.append('{0}: {1}'.format(m, (p.stderr.strip().splitlines() or ['?'])[-1]))
    return bad


def rule_xaml_parses(d):
    bad = []
    for n in LAYOUTS + [THEME]:
        try:
            minidom.parseString(read(d, n).encode('utf-8'))
        except Exception as ex:
            bad.append('{0}: {1}'.format(n, ex))
    return bad


def rule_no_static_resource(d):
    return ['{0} uses StaticResource'.format(n) for n in LAYOUTS + [THEME] if 'StaticResource' in read(d, n)]


def rule_dynamic_keys_defined(d):
    keys = set(theme_keys(d))
    bad = []
    for n in LAYOUTS + [THEME]:
        for k in re.findall(r'\{DynamicResource ([^}]+)\}', read(d, n)):
            if k.strip() not in keys:
                bad.append('{0}: DynamicResource {1} is not in Theme.xaml'.format(n, k))
    for m in modules(d):
        for k in re.findall(r"SetResourceReference\([^,]+,\s*u?'([A-Za-z]+)'\)", read(d, m)):
            if k not in keys:
                bad.append('{0}: SetResourceReference {1} is not in Theme.xaml'.format(m, k))
    return bad


def rule_style_targets(d):
    keys = theme_keys(d)
    bad = []
    for n in LAYOUTS:
        dom = minidom.parseString(read(d, n).encode('utf-8'))
        for el in dom.getElementsByTagName('*'):
            st = el.getAttribute('Style')
            m = re.match(r'\{DynamicResource ([^}]+)\}', st or '')
            if not m:
                continue
            k = m.group(1).strip()
            style = keys.get(k)
            if style is None or style.tagName != 'Style':
                bad.append('{0}: {1} styled with {2}, which is not a Style'.format(n, el.tagName, k))
            elif style.getAttribute('TargetType') != el.tagName:
                bad.append('{0}: {1} styled with {2} (TargetType {3})'.format(
                    n, el.tagName, k, style.getAttribute('TargetType')))
    return bad


def rule_no_brace_literal(d):
    bad = []
    for n in LAYOUTS + [THEME]:
        for v in re.findall(r'=\s*"(\{[^"]*)"', read(d, n)):
            if not v.startswith(KNOWN_EXT):
                bad.append('{0}: attribute starts with a brace: {1}'.format(n, v))
    return bad


def rule_names_exist(d):
    names = xnames(d)
    bad = []
    pat = re.compile(r"(?:FindName|\bf)\(u?'([A-Za-z0-9_]+)'\)")
    for m in modules(d):
        for k in pat.findall(read(d, m)):
            if k not in names:
                bad.append('{0}: looks up {1}, no x:Name has it'.format(m, k))
    return bad


def rule_banned(d):
    bad = []
    for m in modules(d) + ['script.py']:
        src = read(d, m)
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr):
                bad.append('{0}:{1} f-string'.format(m, node.lineno))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'print':
                bad.append('{0}:{1} print'.format(m, node.lineno))
        code = code_only(src)
        for ln, line in enumerate(code.splitlines(), 1):
            if re.search(r'\.\s*IntegerValue\b', line) and 'element_id . IntegerValue' not in line:
                bad.append('{0}:{1} bare .IntegerValue'.format(m, ln))
            if re.search(r'\bUri\b', line):
                bad.append('{0}:{1} System.Uri'.format(m, ln))
    return bad


def _first_lines(src):
    tree = ast.parse(src)
    clr_line = None
    net_line = None
    for node in tree.body:
        if isinstance(node, ast.Import) and any(a.name == 'c2r_clr' for a in node.names):
            clr_line = clr_line or node.lineno
        mod = None
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ''
        elif isinstance(node, ast.Import):
            mod = node.names[0].name
        if mod and (mod.startswith('System') or mod.startswith('Autodesk')):
            net_line = net_line or node.lineno
    return clr_line, net_line


def rule_clr_first(d):
    bad = []
    for m in modules(d):
        if m in NO_NET:
            continue
        clr_line, net_line = _first_lines(read(d, m))
        if net_line is not None and (clr_line is None or clr_line > net_line):
            bad.append('{0}: .NET import on line {1} before import c2r_clr'.format(m, net_line))
    return bad


def _referenced(d):
    tree = ast.parse(read(d, 'c2r_clr.py'))
    for node in tree.body:     # module level only - a reference inside a def runs too late
        if isinstance(node, ast.Assign) and any(getattr(t, 'id', '') == '_ASSEMBLIES' for t in node.targets):
            return set(ast.literal_eval(node.value))
    return set()


def rule_assemblies_referenced(d):
    refs = _referenced(d)
    bad = []
    for m in modules(d):
        for node in ast.walk(ast.parse(read(d, m))):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith('System'):
                need = ASSEMBLY_FOR.get(node.module)
                if need is None:
                    bad.append('{0}: {1} is not in ASSEMBLY_FOR'.format(m, node.module))
                elif not refs.intersection(need):
                    bad.append('{0}: {1} needs one of {2} referenced in c2r_clr'.format(m, node.module, need))
    return bad


def rule_no_duplicate_defs(d):
    bad = []
    for m in modules(d):
        tree = ast.parse(read(d, m))
        scopes = [tree] + [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
        for sc in scopes:
            seen = set()
            for node in sc.body:
                if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                    if node.name in seen:
                        bad.append('{0}: {1} defined twice'.format(m, node.name))
                    seen.add(node.name)
    return bad


def rule_globals_bound(d):
    bad = []
    for m in modules(d) + ['script.py']:
        src = read(d, m)
        top = symtable.symtable(src, m, 'exec')
        defined = set(s.get_name() for s in top.get_symbols() if s.is_assigned() or s.is_imported())
        defined |= set(dir(builtins)) | {'__file__', '__revit__', '__name__'}

        def walk(t):
            for ch in t.get_children():
                for s in ch.get_symbols():
                    if s.is_global() and not s.is_assigned() and s.get_name() not in defined:
                        bad.append('{0}: {1} uses unbound global {2}'.format(m, ch.get_name(), s.get_name()))
                walk(ch)
        walk(top)
    return bad


def _self_attr(node):
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == 'self':
        return node.attr
    return None


def _events(stmt):
    """(order, kind, name) for one statement: reads and calls first, in
    source order, then writes - which is how Python runs `self.a = self.b`."""
    reads = []
    writes = []

    def visit(n):
        if isinstance(n, (ast.FunctionDef, ast.Lambda, ast.ClassDef)):
            return          # deferred bodies run later
        if isinstance(n, ast.Call) and _self_attr(n.func):
            for a in n.args + [k.value for k in n.keywords]:
                visit(a)
            reads.append(((n.lineno, n.col_offset), 'call', _self_attr(n.func)))
            return
        name = _self_attr(n)
        if name is not None:
            if isinstance(n.ctx, ast.Store):
                writes.append(((n.lineno, n.col_offset), 'write', name))
            else:
                reads.append(((n.lineno, n.col_offset), 'read', name))
            return
        if isinstance(n, ast.Subscript) and _self_attr(n.value) and isinstance(n.ctx, ast.Store):
            reads.append(((n.lineno, n.col_offset), 'read', _self_attr(n.value)))
            visit(n.slice)
            return
        for ch in ast.iter_child_nodes(n):
            visit(ch)
    if isinstance(stmt, (ast.If, ast.For, ast.While, ast.With, ast.Try)):
        return None
    visit(stmt)
    return sorted(reads) + sorted(writes)


def _replay(cls_methods, class_attrs, name, assigned, visited, bad, where):
    if name in visited or name not in cls_methods:
        return
    visited.add(name)
    fn = cls_methods[name]

    def run(body):
        for stmt in body:
            if isinstance(stmt, (ast.If, ast.For, ast.While)):
                ev = _events(ast.Expr(value=stmt.test if hasattr(stmt, 'test') else stmt.iter,
                                      lineno=stmt.lineno, col_offset=stmt.col_offset))
                handle(ev or [])
                run(stmt.body)
                run(stmt.orelse)
                continue
            if isinstance(stmt, ast.With):
                run(stmt.body)
                continue
            if isinstance(stmt, ast.Try):
                run(stmt.body)
                for h in stmt.handlers:
                    run(h.body)
                run(stmt.finalbody)
                continue
            handle(_events(stmt) or [])

    def handle(events):
        for _pos, kind, attr in events:
            if kind == 'write':
                assigned.add(attr)
            elif kind == 'call':
                if attr in cls_methods:
                    _replay(cls_methods, class_attrs, attr, assigned, visited, bad, where)
                elif attr not in assigned and attr not in class_attrs:
                    bad.append('{0}: {1} calls self.{2} before it is set'.format(where, name, attr))
            elif attr not in assigned and attr not in class_attrs and attr not in cls_methods:
                bad.append('{0}: {1} reads self.{2} before it is set'.format(where, name, attr))
    run(fn.body)


def rule_attr_before_init(d):
    bad = []
    for m in modules(d):
        tree = ast.parse(read(d, m))
        for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
            methods = dict((n.name, n) for n in cls.body if isinstance(n, ast.FunctionDef))
            if '__init__' not in methods:
                continue
            class_attrs = set()
            for n in cls.body:
                if isinstance(n, ast.Assign):
                    for t in n.targets:
                        if isinstance(t, ast.Name):
                            class_attrs.add(t.id)
            _replay(methods, class_attrs, '__init__', set(), set(), bad, '{0}.{1}'.format(m, cls.name))
    return bad


def _brush_colours(d):
    out = {}
    for k, el in theme_keys(d).items():
        if el.tagName == 'SolidColorBrush':
            out[k] = el.getAttribute('Color').upper()
    return out


def _palettes(d):
    sys.path.insert(0, d)
    try:
        src = read(d, 'c2r_core.py')
        ns = {'__name__': 'c2r_core_bench'}
        exec(compile(src, 'c2r_core.py', 'exec'), ns)
        return ns['PALETTES']
    finally:
        sys.path.pop(0)


def rule_palette_keys_have_brush(d):
    pals = _palettes(d)
    brushes = _brush_colours(d)
    bad = []
    keys = set(pals['dark'])
    if set(pals['light']) != keys:
        bad.append('dark and light palettes have different keys')
    for k in sorted(keys):
        if k not in brushes:
            bad.append('palette key {0} has no brush in Theme.xaml'.format(k))
    return bad


def rule_theme_defaults_match_dark(d):
    dark = _palettes(d)['dark']
    brushes = _brush_colours(d)
    return ['Theme.xaml {0} is {1}, dark palette says {2}'.format(k, brushes.get(k), v.upper())
            for k, v in sorted(dark.items()) if brushes.get(k) != v.upper()]


def rule_changelog_has_version(d):
    v = re.search(r'__version__\s*=\s*"([^"]+)"', read(d, 'c2r_version.py')).group(1)
    return [] if '## ' + v in read(d, 'CHANGELOG.md') else ['CHANGELOG.md has no entry for ' + v]


def rule_shrink_everywhere(d):
    bad = []
    for n in LAYOUTS:
        src = read(d, n)
        if not re.search(r'x:Name="ShrinkBtn"[^>]*Style="\{DynamicResource ShrinkBtn\}"', src):
            bad.append('{0}: no ShrinkBtn styled as one'.format(n))
    tree = ast.parse(read(d, 'c2r_ui.py'))
    for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
        src = ast.get_source_segment(read(d, 'c2r_ui.py'), cls)
        if 'load_xaml(' in src and 'Chrome(' not in src:
            bad.append('c2r_ui.{0} opens a window without Chrome (no drawer)'.format(cls.name))
    if not re.search(r'\bWindowDrawer \(', code_only(read(d, 'c2r_ui.py'))):
        bad.append('Chrome never builds a WindowDrawer')
    return bad


def rule_drawer_releases(d):
    src = code_only(read(d, 'c2r_drawer.py'))
    bad = []
    for prop in ('TopProperty', 'HeightProperty'):
        if not re.search(r'BeginAnimation \( Window \. ' + prop + r' , None \)', src):
            bad.append('drawer never releases Window.' + prop)
    for m in modules(d):
        c = code_only(read(d, m))
        if re.search(r'\b(Storyboard|DoubleAnimation)\b', c):
            bad.append('{0} uses a Storyboard / DoubleAnimation'.format(m))
    return bad


def rule_tick_falls_back(d):
    tree = ast.parse(read(d, 'c2r_drawer.py'))
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef) and fn.name == 'tick':
            for t in [n for n in ast.walk(fn) if isinstance(n, ast.Try)]:
                for h in t.handlers:
                    for n in ast.walk(h):
                        if isinstance(n, ast.Call) and getattr(n.func, 'id', '') == 'land':
                            return []
            return ['drawer tick handler does not land the window when a frame throws']
    return ['drawer has no tick handler']


def rule_shrink_stays_live(d):
    src = read(d, 'c2r_ui.py')
    tree = ast.parse(src)
    bad = []
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef) and fn.name == 'set_busy':
            names = [n.value for n in ast.walk(fn) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
            for k in ('ShrinkBtn', 'Header', 'Root', 'RootBorder'):
                if k in names:
                    bad.append('set_busy disables {0}, which takes the shrink button with it'.format(k))
    if re.search(r"ShrinkBtn'\s*\)\s*\.\s*IsEnabled", src) or re.search(r'shrink_btn\s*\.\s*IsEnabled', src):
        bad.append('something disables the shrink button')
    return bad


def rule_no_key_closes(d):
    bad = []
    for m in modules(d):
        tree = ast.parse(read(d, m))
        for fn in ast.walk(tree):
            if isinstance(fn, ast.FunctionDef) and 'key' in fn.name.lower():
                for n in ast.walk(fn):
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == 'Close':
                        bad.append('{0}: key handler {1} closes the window'.format(m, fn.name))
    return bad


def rule_transactions_in_jobs(d):
    bad = []
    for m in modules(d) + ['script.py']:
        if m == 'c2r_jobs.py':
            continue
        if re.search(r'\bTransaction(Group)? \(', code_only(read(d, m))):
            bad.append('{0} opens a Transaction outside c2r_jobs'.format(m))
    return bad


def rule_dialogs_owned(d):
    tree = ast.parse(read(d, 'c2r_ui.py'))
    bad = []
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef):
            calls = [n.func for n in ast.walk(fn) if isinstance(n, ast.Call)]
            shows = [c for c in calls if isinstance(c, ast.Attribute) and c.attr == 'ShowDialog']
            owns = [c for c in calls if getattr(c, 'id', '') == 'own_dialog']
            if shows and not owns:
                bad.append('{0} shows a dialog without own_dialog'.format(fn.name))
    return bad


RULES = [
    rule_modules_import, rule_xaml_parses, rule_no_static_resource, rule_dynamic_keys_defined,
    rule_style_targets, rule_no_brace_literal, rule_names_exist, rule_banned, rule_clr_first,
    rule_assemblies_referenced, rule_no_duplicate_defs, rule_globals_bound, rule_attr_before_init,
    rule_palette_keys_have_brush, rule_theme_defaults_match_dark, rule_changelog_has_version,
    rule_shrink_everywhere, rule_drawer_releases, rule_tick_falls_back, rule_shrink_stays_live,
    rule_no_key_closes, rule_transactions_in_jobs, rule_dialogs_owned,
]


# =====================================================================
# selftest: one deliberate breakage per rule (some rules get several)
# =====================================================================

def _sub(name, old, new):
    def apply(d):
        src = read(d, name)
        if old not in src:
            raise AssertionError('breakage target not found in {0}: {1!r}'.format(name, old))
        write(d, name, src.replace(old, new, 1))
    return apply


BREAKAGES = [
    (rule_modules_import, _sub('c2r_ui.py', 'from System.Windows.Controls import (StackPanel,',
                               'from System.Windows.Controls import (Thickness, StackPanel,')),
    (rule_xaml_parses, _sub('ClickToRvt.xaml', '<!-- ===== body ===== -->', '<!-- -- body -- -->')),
    (rule_no_static_resource, _sub('Settings.xaml', '{DynamicResource Card}', '{StaticResource Card}')),
    (rule_dynamic_keys_defined, _sub('ClickToRvt.xaml', '{DynamicResource Muted}', '{DynamicResource Mutd}')),
    (rule_dynamic_keys_defined, _sub('c2r_ui.py', "SetResourceReference(Shape.FillProperty, u'Dot')",
                                     "SetResourceReference(Shape.FillProperty, u'Dots')")),
    (rule_style_targets, _sub('ClickToRvt.xaml', 'x:Name="FullBtn" Style="{DynamicResource WinBtn}"',
                              'x:Name="FullBtn" Style="{DynamicResource GripThumb}"')),
    (rule_no_brace_literal, _sub('ClickToRvt.xaml', 'Tag="0"', 'Tag="{Insulation}"')),
    (rule_names_exist, _sub('c2r_ui.py', "f(u'ResultTitle').Text", "f(u'ResultTitel').Text")),
    (rule_banned, _sub('c2r_core.py', 'MM_PER_FT = 304.8', 'MM_PER_FT = float(f"{304.8}")')),
    (rule_banned, _sub('c2r_build.py', 'MM = core.MM_PER_FT', 'MM = core.MM_PER_FT\nprint(MM)')),
    (rule_banned, _sub('c2r_jobs.py', "    for i in ids or []:\n", "    for i in ids or []:\n        i.IntegerValue\n")),
    (rule_banned, _sub('c2r_ui.py', 'from System import Action, AppDomain', 'from System import Action, AppDomain, Uri')),
    (rule_clr_first, _sub('c2r_cloud.py', "import c2r_clr  # noqa: F401  (assembly references first)\n\n", "")),
    (rule_assemblies_referenced, _sub('c2r_clr.py', "'System.Drawing', 'System.Windows.Forms',", "'System.Drawing',")),
    (rule_assemblies_referenced, _sub('c2r_clr.py', "'PresentationFramework', ", "")),
    (rule_no_duplicate_defs, _sub('c2r_core.py', 'def v_len(a):', 'def v_add(a, b):\n    return a\n\n\ndef v_len(a):')),
    (rule_no_duplicate_defs, _sub('c2r_ui.py', '    def _on_stop(self, sender, args):',
                                  '    def _on_close(self, sender, args):\n        pass\n\n    def _on_stop(self, sender, args):')),
    (rule_globals_bound, _sub('c2r_build.py', 'def _ccw(points):', 'def _ccw_points(points):')),
    (rule_attr_before_init, _sub('c2r_ui.py', "        self.kind_checks = {}\n", "")),
    (rule_attr_before_init, _sub('c2r_ui.py', "        self.log = Log(st[u'debug'] == u'1')\n        self.win = load_xaml(u'ClickToRvt.xaml')\n",
                                 "        self.win = load_xaml(u'ClickToRvt.xaml')\n")),
    (rule_palette_keys_have_brush, _sub('Theme.xaml', '<SolidColorBrush x:Key="Dot" Color="#7CC0F2"/>', '')),
    (rule_theme_defaults_match_dark, _sub('Theme.xaml', 'x:Key="Bg" Color="#3C4454"', 'x:Key="Bg" Color="#232326"')),
    (rule_changelog_has_version, _sub('c2r_version.py', '__version__ = "1.0.0"', '__version__ = "9.9.9"')),
    (rule_shrink_everywhere, _sub('Settings.xaml', 'x:Name="ShrinkBtn" Style="{DynamicResource ShrinkBtn}"',
                                  'x:Name="ShrinkBtn" Style="{DynamicResource WinBtn}"')),
    (rule_shrink_everywhere, _sub('c2r_ui.py', "        self.chrome = Chrome(self.win, self, DIALOG_GRIPS, main._drawer_error)\n        self.drawer = self.chrome.drawer\n",
                                  "        self.drawer = None\n")),
    (rule_shrink_everywhere, _sub('c2r_ui.py', "        self.drawer = WindowDrawer(win, self.header,", "        self.drawer = Drawer(win, self.header,")),
    (rule_drawer_releases, _sub('c2r_drawer.py', 'self.w.BeginAnimation(Window.HeightProperty, None)', 'pass')),
    (rule_drawer_releases, _sub('c2r_drawer.py', 'def _release(self):', 'def _sb(self):\n        Storyboard()\n\n    def _release(self):')),
    (rule_tick_falls_back, _sub('c2r_drawer.py', "            except Exception as ex:\n                self._err(ex)\n                land()\n",
                                "            except Exception as ex:\n                self._err(ex)\n")),
    (rule_shrink_stays_live, _sub('c2r_ui.py', "(u'Body', u'GearBtn',", "(u'Root', u'GearBtn',")),
    (rule_no_key_closes, _sub('c2r_ui.py', "            elif e.Key == Key.Escape and self.full is not None:",
                              "            elif e.Key == Key.Escape and self.full is None:\n                self.win.Close()\n"
                              "            elif e.Key == Key.Escape and self.full is not None:")),
    (rule_transactions_in_jobs, _sub('c2r_build.py', 'def make_pipe(pl, cand, rec):\n',
                                     'def make_pipe(pl, cand, rec):\n    Transaction(pl.doc, u"x")\n')),
    (rule_dialogs_owned, _sub('c2r_ui.py', '        own_dialog(self.win, self.main.win, self.main.drawer)\n', '')),
]


def _copy():
    tmp = tempfile.mkdtemp(prefix='c2r_bench_')
    for n in os.listdir(HERE):
        p = os.path.join(HERE, n)
        if os.path.isfile(p):
            shutil.copy(p, tmp)
    return tmp


def selftest():
    failed = 0
    covered = set()
    for rule, breakage in BREAKAGES:
        tmp = _copy()
        try:
            clean = rule(tmp)
            if clean:
                print('  ?  {0}: fails on clean source: {1}'.format(rule.__name__, clean[0]))
                failed += 1
                continue
            breakage(tmp)
            got = rule(tmp)
            if got:
                covered.add(rule)
                print('  ok {0}: caught - {1}'.format(rule.__name__, got[0]))
            else:
                failed += 1
                print('  XX {0}: breakage NOT caught'.format(rule.__name__))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    for r in RULES:
        if r not in covered:
            failed += 1
            print('  XX {0}: no breakage proves it'.format(r.__name__))
    print('selftest: {0} breakages, {1} rules, {2} failures'.format(len(BREAKAGES), len(RULES), failed))
    return failed


def main():
    if '--selftest' in sys.argv:
        sys.exit(1 if selftest() else 0)
    failed = 0
    for rule in RULES:
        bad = rule(HERE)
        if bad:
            failed += 1
            print('FAIL {0}'.format(rule.__name__))
            for b in bad[:12]:
                print('     ' + b)
        else:
            print('ok   {0}'.format(rule.__name__))
    print('{0} rules, {1} failing'.format(len(RULES), failed))
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
