# -*- coding: utf-8 -*-
"""Selected in View - static bench rules.

    python import_check.py             run every rule
    python import_check.py --selftest  break each rule on purpose and prove it fires

Every rule reads the actual code (strings and comments stripped where it
matters), never prose, so a docstring cannot make a rule pass.
"""
import ast
import importlib
import io
import io as _io
import os
import re
import shutil
import sys
import tempfile
import tokenize
import xml.dom.minidom

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL_MODULES = ['siv_clr.py', 'siv_core.py', 'siv_revit.py', 'siv_ui.py', 'siv_window.py']
PY_FILES = TOOL_MODULES + ['script.py']
XAML_FILES = ['SelectedInView.xaml', 'Theme.xaml']
OTHER = ['CHANGELOG.md']
BENCH_FILES = ['bench_stubs.py', 'import_check.py', 'bench_logic.py']

# namespace -> assemblies that provide it (any one is enough)
ASSEMBLY_FOR = {
    'System': ['mscorlib', 'System'],
    'System.Collections.Generic': ['mscorlib', 'System'],
    'System.IO': ['mscorlib', 'System'],
    'System.Windows': ['PresentationFramework', 'PresentationCore', 'WindowsBase'],
    'System.Windows.Controls': ['PresentationFramework'],
    'System.Windows.Controls.Primitives': ['PresentationFramework'],
    'System.Windows.Shapes': ['PresentationFramework'],
    'System.Windows.Media': ['PresentationCore'],
    'System.Windows.Media.Imaging': ['PresentationCore'],
    'System.Windows.Markup': ['PresentationFramework', 'System.Xaml'],
    'System.Windows.Input': ['PresentationCore'],
    'System.Windows.Interop': ['PresentationFramework', 'PresentationCore'],
    'System.Windows.Threading': ['WindowsBase'],
    'System.Windows.Forms': ['System.Windows.Forms'],
    'System.Data': ['System.Data'],
    'System.Xml': ['System.Xml'],
    'System.Drawing': ['System.Drawing'],
}


def read_all(folder=HERE):
    files = {}
    for name in PY_FILES + XAML_FILES + OTHER:
        with io.open(os.path.join(folder, name), 'r', encoding='utf-8') as fh:
            files[name] = fh.read()
    return files


def code_only(src):
    """Source with every string literal blanked and comments removed."""
    out = []
    try:
        toks = list(tokenize.generate_tokens(_io.StringIO(src).readline))
    except Exception:
        return src
    last_line, last_col = 1, 0
    lines = []
    for tok in toks:
        ttype, text, (sl, sc), (el, ec), _line = tok
        if ttype == tokenize.COMMENT:
            continue
        if ttype == tokenize.STRING:
            text = '""'
        lines.append((sl, sc, el, ec, text, ttype))
    cur_line = 1
    for sl, sc, el, ec, text, ttype in lines:
        while cur_line < sl:
            out.append('\n')
            cur_line += 1
        out.append(' ' + text)
        cur_line = max(cur_line, el)
    return ''.join(out)


_STRING_TYPES = set([tokenize.STRING] + [getattr(tokenize, n) for n in ('FSTRING_START',) if hasattr(tokenize, n)])


def string_tokens(src):
    try:
        return [t for t in tokenize.generate_tokens(_io.StringIO(src).readline)
                if t[0] in _STRING_TYPES]
    except Exception:
        return []


def palette_keys():
    sys.path.insert(0, HERE)
    import siv_core
    return siv_core


def theme_keys(files):
    return set(re.findall(r'x:Key="([^"]+)"', files['Theme.xaml']))


# =====================================================================
# Rules - each returns a list of failure strings
# =====================================================================
def rule_xaml_parses(files):
    bad = []
    for name in XAML_FILES:
        try:
            xml.dom.minidom.parseString(files[name].encode('utf-8'))
        except Exception as ex:
            bad.append('{0} does not parse: {1}'.format(name, ex))
    return bad


def rule_no_static_resource(files):
    return ['{0} uses StaticResource'.format(n) for n in XAML_FILES if 'StaticResource' in files[n]]


def rule_dynamic_keys_defined(files, core=None):
    core = core or palette_keys()
    known = set(core.PALETTES['dark'].keys()) | theme_keys(files)
    bad = []
    for name in XAML_FILES:
        for key in re.findall(r'\{DynamicResource ([^}\s]+)\}', files[name]):
            if key not in known:
                bad.append('{0}: DynamicResource {1} is not defined'.format(name, key))
    return bad


def rule_resource_refs_defined(files, core=None):
    core = core or palette_keys()
    known = set(core.PALETTES['dark'].keys()) | theme_keys(files)
    bad = []
    for name in TOOL_MODULES:
        for key in re.findall(r"SetResourceReference\([^,]+,\s*'([A-Za-z]+)'\)", files[name]):
            if key not in known:
                bad.append('{0}: SetResourceReference key {1} undefined'.format(name, key))
    return bad


def rule_findname_has_xname(files):
    names = set(re.findall(r'x:Name="([^"]+)"', files['SelectedInView.xaml']))
    bad = []
    for name in TOOL_MODULES:
        code = files[name]
        for n in re.findall(r"(?:ctl|FindName|\bc)\('([A-Za-z]+)'\)", code):
            if n not in names:
                bad.append('{0}: looks up {1} with no x:Name'.format(name, n))
    return bad


def rule_no_fstrings(files):
    bad = []
    for name in PY_FILES:
        for tok in string_tokens(files[name]):
            prefix = re.match(r'^([A-Za-z]*)', tok[1]).group(1).lower()
            if 'f' in prefix:
                bad.append('{0}:{1} f-string'.format(name, tok[2][0]))
    return bad


def rule_no_print(files):
    bad = []
    for name in PY_FILES:
        if re.search(r'(^|\s)print\b', code_only(files[name])):
            bad.append('{0} uses print'.format(name))
    return bad


def rule_no_bare_integervalue(files):
    """.IntegerValue only inside eid_value()."""
    bad = []
    for name in PY_FILES:
        try:
            tree = ast.parse(files[name])
        except SyntaxError as ex:
            bad.append('{0} syntax error {1}'.format(name, ex))
            continue
        allowed = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == 'eid_value':
                for sub in ast.walk(node):
                    allowed.add(id(sub))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == 'IntegerValue' and id(node) not in allowed:
                bad.append('{0}:{1} bare .IntegerValue'.format(name, node.lineno))
    return bad


def rule_no_system_uri(files):
    bad = []
    for name in PY_FILES:
        code = code_only(files[name])
        if re.search(r'import[^\n]*\bUri\b', code) or 'System.Uri' in code or 'UriSource' in code:
            bad.append('{0} uses System.Uri'.format(name))
    return bad


def _dotnet_imports(tree):
    """(lineno, namespace) for every System.* / Autodesk.* import, top level or nested."""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == 'System' or node.module.startswith(('System.', 'Autodesk')):
                out.append((node.lineno, node.module))
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name == 'System' or a.name.startswith(('System.', 'Autodesk')):
                    out.append((node.lineno, a.name))
    return out


def rule_clr_first(files):
    bad = []
    for name in ['siv_revit.py', 'siv_ui.py', 'siv_window.py']:
        tree = ast.parse(files[name])
        clr_line = None
        for node in tree.body:
            if isinstance(node, ast.Import) and any(a.name == 'siv_clr' for a in node.names):
                clr_line = node.lineno
                break
        dotnet = _dotnet_imports(tree)
        if not dotnet:
            continue
        first = min(l for l, _m in dotnet)
        if clr_line is None or clr_line > first:
            bad.append('{0}: .NET import on line {1} before import siv_clr'.format(name, first))
    return bad


def rule_core_pure(files):
    tree = ast.parse(files['siv_core.py'])
    bad = ['siv_core imports {0}'.format(m) for _l, m in _dotnet_imports(tree)]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(a.name == 'clr' for a in node.names):
            bad.append('siv_core imports clr')
    return bad


def _assembly_list(files):
    tree = ast.parse(files['siv_clr.py'])
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, 'id', '') == '_ASSEMBLIES' for t in node.targets):
            return [e.value for e in node.value.elts]
    return []


def rule_assemblies_referenced(files):
    have = set(_assembly_list(files))
    bad = []
    for name in TOOL_MODULES:
        for _line, ns in _dotnet_imports(ast.parse(files[name])):
            if ns.startswith('Autodesk'):
                continue  # RevitAPI / RevitAPIUI are loaded by pyRevit
            need = ASSEMBLY_FOR.get(ns)
            if need is None:
                bad.append('{0}: no ASSEMBLY_FOR entry for {1}'.format(name, ns))
            elif not have.intersection(need):
                bad.append('{0}: {1} needs one of {2} in siv_clr'.format(name, ns, need))
    return bad


def rule_no_clr_revit_refs(files):
    bad = []
    for a in _assembly_list(files):
        if a in ('RevitAPI', 'RevitAPIUI'):
            bad.append('siv_clr references {0} (pyRevit loads it)'.format(a))
    return bad


def rule_no_duplicate_defs(files):
    bad = []
    for name in PY_FILES:
        tree = ast.parse(files[name])
        scopes = [tree] + [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
        for scope in scopes:
            seen = set()
            for node in scope.body:
                if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                    if node.name in seen:
                        bad.append('{0}: {1} defined twice'.format(name, node.name))
                    seen.add(node.name)
    return bad


def rule_changelog_version(files):
    m = re.search(r"__version__\s*=\s*'([^']+)'", files['siv_core.py'])
    ver = m.group(1) if m else None
    if not ver or ('## ' + ver) not in files['CHANGELOG.md']:
        return ['CHANGELOG.md has no entry for {0}'.format(ver)]
    return []


def rule_script_thin(files):
    src = files['script.py']
    code = code_only(src)
    bad = []
    if not re.search(r'__persistentengine__\s*=\s*True', code):
        bad.append('script.py lacks __persistentengine__ = True')
    if 'AddReference' in code:
        bad.append('script.py calls clr.AddReference')
    if len(src.splitlines()) > 70:
        bad.append('script.py is not a thin loader')
    return bad


def rule_raise_checked(files):
    bad = []
    for name in TOOL_MODULES:
        for line in code_only(files[name]).splitlines():
            if '.Raise ( )' in line.replace('(', ' ( ').replace(')', ' ) ').replace('  ', ' ') or '.Raise()' in line.replace(' ', ''):
                if '=' not in line.split('Raise')[0]:
                    bad.append('{0}: Raise() result not read'.format(name))
    return bad


def rule_window_chrome(files):
    x = files['SelectedInView.xaml']
    bad = []
    if 'AllowsTransparency="True"' in x and 'WindowStyle="None"' not in x:
        bad.append('AllowsTransparency without WindowStyle="None"')
    for name in XAML_FILES:
        if '"Baseline"' in files[name]:
            bad.append('{0} uses VerticalAlignment Baseline'.format(name))
    return bad


def rule_palettes_match(files, core=None):
    core = core or palette_keys()
    d = core.PALETTES['dark']
    l = core.PALETTES['light']
    bad = []
    if set(d) != set(l):
        bad.append('palettes differ: {0}'.format(sorted(set(d) ^ set(l))))
    for mode, pal in (('dark', d), ('light', l)):
        for k, v in pal.items():
            if not re.match(r'^#[0-9A-Fa-f]{6}$', v):
                bad.append('{0}.{1} bad colour {2}'.format(mode, k, v))
    for _key, words in core.COLOUR_RULES:
        if _key not in d:
            bad.append('colour rule {0} has no palette key'.format(_key))
    return bad


def rule_ascii_only(files):
    bad = []
    for name in PY_FILES + XAML_FILES:
        for i, ch in enumerate(files[name]):
            if ord(ch) > 127:
                bad.append('{0}: non-ASCII at offset {1}'.format(name, i))
                break
    return bad


def rule_hooks_paired(files):
    code = code_only(files['siv_window.py'])
    bad = []
    for ev in ('SelectionChanged', 'ViewActivated'):
        adds = len(re.findall(r'\.\s*' + ev + r'\s*\+\s*=', code))
        removes = len(re.findall(r'\.\s*' + ev + r'\s*-\s*=', code))
        if not adds:
            bad.append('{0} is never hooked - rule cannot see the code'.format(ev))
        elif removes < 2:
            bad.append('{0} hooked without unhook in both unhook() and _unhook_saved()'.format(ev))
    return bad


def rule_enums_late(files):
    bad = []
    for name in TOOL_MODULES:
        tree = ast.parse(files[name])
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                continue
            for sub in ast.walk(node):
                if isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name) \
                        and sub.value.id in ('BuiltInCategory', 'BuiltInParameter'):
                    bad.append('{0}:{1} {2}.{3} at module load'.format(name, sub.lineno, sub.value.id, sub.attr))
    return bad


def rule_modules_load(files):
    """Import every module against the stub API from a scratch copy."""
    tmp = tempfile.mkdtemp(prefix='siv_bench_')
    bad = []
    try:
        for name, text in files.items():
            with io.open(os.path.join(tmp, name), 'w', encoding='utf-8') as fh:
                fh.write(text)
        shutil.copy(os.path.join(HERE, 'bench_stubs.py'), tmp)
        saved_path = list(sys.path)
        saved_mods = dict(sys.modules)
        sys.path.insert(0, tmp)
        try:
            for m in [k for k in sys.modules if k.startswith('siv_') or k == 'bench_stubs']:
                del sys.modules[m]
            import bench_stubs
            bench_stubs.install()
            for mod in ['siv_clr', 'siv_core', 'siv_revit', 'siv_ui', 'siv_window']:
                try:
                    importlib.import_module(mod)
                except Exception as ex:
                    bad.append('{0} does not load: {1}: {2}'.format(mod, type(ex).__name__, ex))
        finally:
            sys.path[:] = saved_path
            for k in list(sys.modules):
                if k not in saved_mods:
                    del sys.modules[k]
            sys.modules.update(saved_mods)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return bad


def rule_style_target_types(files):
    """A keyed Style used on the wrong element type throws when applied."""
    theme = files['Theme.xaml']
    targets = dict(re.findall(r'<Style x:Key="([^"]+)" TargetType="([^"]+)"', theme))
    bad = []
    for name in XAML_FILES:
        for el, key in re.findall(r'<([A-Za-z]+)[^>]*Style="\{DynamicResource ([^}]+)\}"', files[name]):
            t = targets.get(key)
            if t is not None and t != el:
                bad.append('{0}: {1} given {2} style for {3}'.format(name, el, key, t))
    for key in re.findall(r"SetResourceReference\(Button\.StyleProperty,\s*'([^']+)'\)", files['siv_window.py']):
        if targets.get(key) != 'Button':
            bad.append('siv_window: Button given style {0}'.format(key))
    return bad


RULES = [
    rule_xaml_parses, rule_no_static_resource, rule_dynamic_keys_defined,
    rule_resource_refs_defined, rule_findname_has_xname, rule_no_fstrings,
    rule_no_print, rule_no_bare_integervalue, rule_no_system_uri,
    rule_clr_first, rule_core_pure, rule_assemblies_referenced,
    rule_no_clr_revit_refs, rule_no_duplicate_defs, rule_changelog_version,
    rule_script_thin, rule_raise_checked, rule_window_chrome,
    rule_palettes_match, rule_ascii_only, rule_hooks_paired, rule_enums_late,
    rule_modules_load, rule_style_target_types,
]


def run(files, rules=RULES):
    failures = []
    for rule in rules:
        try:
            out = rule(files)
        except Exception as ex:
            out = ['{0} crashed: {1}'.format(rule.__name__, ex)]
        failures.extend('[{0}] {1}'.format(rule.__name__, f) for f in out)
    return failures


# =====================================================================
# Self test - each breakage must be caught by its own rule
# =====================================================================
def _sub(name, old, new):
    def f(files):
        if old not in files[name]:
            raise AssertionError('breakage anchor missing in {0}: {1!r}'.format(name, old[:40]))
        files[name] = files[name].replace(old, new, 1)
    return f


def _append(name, text):
    def f(files):
        files[name] = files[name] + text
    return f


BREAKAGES = [
    (rule_xaml_parses, _sub('SelectedInView.xaml', '<!-- ===== Toolbar ===== -->', '<!-- -- Toolbar -- -->')),
    (rule_xaml_parses, _sub('Theme.xaml', '</ResourceDictionary>', '<Style>\n</ResourceDictionary>')),
    (rule_no_static_resource, _sub('SelectedInView.xaml', '{DynamicResource BarBg}', '{StaticResource BarBg}')),
    (rule_dynamic_keys_defined, _sub('SelectedInView.xaml', '{DynamicResource Muted}', '{DynamicResource Mutd}')),
    (rule_resource_refs_defined, _sub('siv_window.py', "'RowHover')", "'RowHovr')")),
    (rule_findname_has_xname, _sub('siv_window.py', "c('AllBtn')", "c('AllButton')")),
    (rule_no_fstrings, _append('siv_ui.py', "\n_X = f'{1}'\n")),
    (rule_no_print, _append('siv_core.py', "\nprint('x')\n")),
    (rule_no_bare_integervalue, _append('siv_revit.py', "\ndef _k(e):\n    return e.Id.IntegerValue\n")),
    (rule_no_system_uri, _sub('siv_ui.py', 'from System.IO import File, MemoryStream', 'from System import Uri\nfrom System.IO import File, MemoryStream')),
    (rule_clr_first, _sub('siv_ui.py', 'import siv_clr  # noqa: F401  (assemblies first)\n\n', '')),
    (rule_core_pure, _sub('siv_core.py', 'import os\n', 'import os\nfrom System.Windows import Thickness\n')),
    (rule_assemblies_referenced, _sub('siv_clr.py', "'System.Drawing', 'System.Windows.Forms',", "'System.Drawing',")),
    (rule_no_clr_revit_refs, _sub('siv_clr.py', "'WindowsBase',", "'WindowsBase', 'RevitAPI',")),
    (rule_no_duplicate_defs, _append('siv_core.py', "\n\ndef matches(q, t):\n    return True\n")),
    (rule_changelog_version, _sub('siv_core.py', "__version__ = '", "__version__ = '9.")),
    (rule_script_thin, _sub('script.py', '__persistentengine__ = True', '__persistentengine__ = False')),
    (rule_raise_checked, _sub('siv_window.py', 'status = self.event.Raise()', 'self.event.Raise()\n        status = None')),
    (rule_window_chrome, _sub('SelectedInView.xaml', 'WindowStyle="None" ', '')),
    (rule_window_chrome, _sub('SelectedInView.xaml', 'VerticalAlignment="Center" Cursor="Hand"/>', 'VerticalAlignment="Baseline" Cursor="Hand"/>')),
    (rule_ascii_only, _sub('siv_core.py', "TOOL_NAME = u'Selected in View'", "TOOL_NAME = u'Sélected in View'")),
    (rule_hooks_paired, _sub('siv_window.py', 'app.SelectionChanged -= saved[1]', 'pass')),
    (rule_enums_late, _append('siv_revit.py', '\n_LINKS = BuiltInCategory.OST_RvtLinks\n')),
    (rule_modules_load, _sub('siv_ui.py', 'from System.Windows.Markup import XamlReader', 'from System.Windows import XamlReader')),
    (rule_modules_load, _sub('siv_window.py', 'from System.Windows.Forms import Screen', 'from System.Windows import Screen')),
    (rule_style_target_types, _sub('SelectedInView.xaml', '<Button x:Name="AllBtn" Grid.Column="0" Style="{DynamicResource ToolButton}"', '<Button x:Name="AllBtn" Grid.Column="0" Style="{DynamicResource ThumbStyle}"')),
]


def palette_breakage():
    """rule_palettes_match reads siv_core.PALETTES - break it in memory."""
    core = palette_keys()
    saved = dict(core.PALETTES['light'])
    try:
        del core.PALETTES['light']['RowHover']
        return rule_palettes_match({}, core)
    finally:
        core.PALETTES['light'].clear()
        core.PALETTES['light'].update(saved)


def selftest():
    base = read_all()
    clean = run(base)
    if clean:
        sys.stdout.write('Rules fail on the real code - fix before selftest:\n  ' + '\n  '.join(clean) + '\n')
        return 1
    caught = 0
    missed = []
    for rule, breakage in BREAKAGES:
        files = dict(base)
        breakage(files)
        out = rule(files)
        if out:
            caught += 1
        else:
            missed.append(rule.__name__)
    if palette_breakage():
        caught += 1
    else:
        missed.append('rule_palettes_match')
    total = len(BREAKAGES) + 1
    sys.stdout.write('selftest: {0}/{1} breakages caught\n'.format(caught, total))
    if missed:
        sys.stdout.write('MISSED: ' + ', '.join(missed) + '\n')
        return 1
    return 0


def main():
    if '--selftest' in sys.argv:
        return selftest()
    failures = run(read_all())
    if failures:
        sys.stdout.write('FAIL\n  ' + '\n  '.join(failures) + '\n')
        return 1
    sys.stdout.write('import_check: {0} rules passed\n'.format(len(RULES)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
