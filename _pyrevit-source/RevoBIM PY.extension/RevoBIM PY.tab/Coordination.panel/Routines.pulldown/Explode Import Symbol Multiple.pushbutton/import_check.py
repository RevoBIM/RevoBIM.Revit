# -*- coding: utf-8 -*-
"""Static bench check for Explode Import Symbol Multiple (plain CPython).

    python import_check.py             run every rule
    python import_check.py --selftest  break each rule on purpose and prove it fires

Every rule reads code with comments and docstrings stripped, so prose can
never satisfy a rule meant for code.
"""
import ast
import io
import os
import re
import sys
import tokenize
import xml.dom.minidom

HERE = os.path.dirname(os.path.abspath(__file__))
EXT_ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))

# namespace -> assemblies that provide it (Autodesk.Revit.* is the host's own)
ASSEMBLY_FOR = {
    'System': ['System', 'mscorlib'],
    'System.IO': ['mscorlib', 'System'],
    'System.Threading': ['mscorlib', 'System'],
    'System.Collections.Generic': ['mscorlib', 'System'],
    'System.Windows': ['PresentationFramework', 'WindowsBase'],
    'System.Windows.Markup': ['PresentationFramework', 'System.Xaml'],
    'System.Windows.Media': ['PresentationCore'],
    'System.Windows.Media.Imaging': ['PresentationCore'],
    'System.Windows.Input': ['PresentationCore', 'WindowsBase'],
    'System.Windows.Interop': ['PresentationFramework', 'PresentationCore'],
    'System.Windows.Automation': ['UIAutomationClient', 'UIAutomationTypes'],
    'System.Data': ['System.Data'],
    'System.Xml': ['System.Xml'],
    'System.Drawing': ['System.Drawing'],
    'Autodesk.Windows': ['AdWindows'],
}
PURE = ('eim_core.py', 'eim_settings.py', 'eim_version.py', 'eim_clr.py',
        'import_check.py', 'bench_logic.py', 'make_icons.py', 'script.py')
SHARED_SINGULAR = ('startup.py', os.path.join('lib', 'revobim', '__init__.py'))


# ==========================================================================
# Loading
# ==========================================================================

def load_files():
    files = {}
    for name in sorted(os.listdir(HERE)):
        if name.endswith(('.py', '.xaml', '.md', '.yaml')):
            with io.open(os.path.join(HERE, name), 'r', encoding='utf-8') as fh:
                files[name] = fh.read()
    return files


def code_only(text):
    """Source with comments and docstrings/strings removed - what runs."""
    out = []
    try:
        toks = tokenize.generate_tokens(io.StringIO(text).readline)
        prev = None
        for tok in toks:
            if tok.type == tokenize.COMMENT:
                continue
            if tok.type == tokenize.STRING:
                out.append('""')
            else:
                out.append(tok.string)
            prev = tok
        return ' '.join(out)
    except Exception:
        return text


def code_with_strings(text):
    """Comments removed, docstrings removed, ordinary strings kept."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return text
    doc_lines = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)):
            body = getattr(node, 'body', [])
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], 'value', None), ast.Constant) \
                    and isinstance(body[0].value.value, str):
                for ln in range(body[0].lineno, body[0].end_lineno + 1):
                    doc_lines.add(ln)
    lines = []
    for i, line in enumerate(text.splitlines(), 1):
        if i in doc_lines:
            continue
        lines.append(re.sub(r'(^|\s)#.*$', '', line) if not re.search(r"""['"].*#.*['"]""", line) else line)
    return '\n'.join(lines)


def _has_fstring(text):
    """A real f-string token, judged by its prefix - not a '%f' inside a string."""
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.STRING:
                prefix = re.match(r'[A-Za-z]*', tok.string).group(0).lower()
                if 'f' in prefix:
                    return True
            elif getattr(tokenize, 'FSTRING_START', None) == tok.type:
                return True
    except Exception:
        return False
    return False


def py_files(files):
    return dict((k, v) for k, v in files.items() if k.endswith('.py'))


def xaml_files(files):
    return dict((k, v) for k, v in files.items() if k.endswith('.xaml'))


# ==========================================================================
# Rules - each returns a list of failure strings
# ==========================================================================

def rule_xaml_parses(files, ext):
    bad = []
    for name, text in xaml_files(files).items():
        try:
            xml.dom.minidom.parseString(text.encode('utf-8'))
        except Exception as ex:
            bad.append('{0} does not parse: {1}'.format(name, ex))
        if 'Baseline' in text:
            bad.append('{0} uses Baseline alignment (XamlReader dies silently)'.format(name))
        if re.search(r'=\s*"\{[^}A-Za-z]', text):
            bad.append('{0} has an attribute starting with a bare {{'.format(name))
    return bad


def rule_no_static_resource(files, ext):
    return ['{0} uses StaticResource'.format(n) for n, t in xaml_files(files).items()
            if 'StaticResource' in t]


def _theme_keys(files):
    return set(re.findall(r'x:Key="([^"]+)"', files.get('Theme.xaml', '')))


def rule_dynamic_keys_defined(files, ext):
    keys = _theme_keys(files)
    bad = []
    for name, text in xaml_files(files).items():
        for key in re.findall(r'\{DynamicResource\s+([^}\s]+)\}', text):
            if key not in keys:
                bad.append('{0}: DynamicResource {1} not defined in Theme.xaml'.format(name, key))
    return bad


def rule_style_target(files, ext):
    theme = files.get('Theme.xaml', '')
    targets = dict(re.findall(r'<Style x:Key="([^"]+)" TargetType="([^"]+)"', theme))
    bad = []
    for name, text in xaml_files(files).items():
        for tag, key in re.findall(r'<(\w+)[^<>]*?Style="\{DynamicResource\s+([^}\s]+)\}"', text):
            if key in targets and targets[key] != tag:
                bad.append('{0}: <{1}> given style {2} for {3}'.format(name, tag, key, targets[key]))
    return bad


def rule_palette_keys(files, ext):
    text = files.get('eim_theme.py', '')
    try:
        tree = ast.parse(text)
    except SyntaxError as ex:
        return ['eim_theme.py does not parse: {0}'.format(ex)]
    palettes = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], 'id', '') == 'PALETTES':
            palettes = ast.literal_eval(node.value)
    if not palettes:
        return ['eim_theme.py has no PALETTES']
    keys = _theme_keys(files)
    bad = []
    names = list(palettes)
    for n in names:
        for k in palettes[n]:
            if k not in keys:
                bad.append('palette {0} key {1} has no brush in Theme.xaml'.format(n, k))
    if set(palettes[names[0]]) != set(palettes[names[-1]]):
        bad.append('dark and light palettes do not carry the same keys')
    return bad


def rule_findname(files, ext):
    win = files.get('eim_window.py', '')
    m = re.search(r'names = \[(.*?)\]', code_with_strings(win), re.S)
    if not m:
        return ['eim_window.py: no names list for FindName']
    wanted = re.findall(r"'(\w+)'", m.group(1))
    have = set(re.findall(r'x:Name="(\w+)"', files.get('ExplodePrompt.xaml', '')))
    return ['FindName {0} has no x:Name in ExplodePrompt.xaml'.format(n) for n in wanted if n not in have]


def _assemblies(files):
    text = files.get('eim_clr.py', '')
    try:
        for node in ast.parse(text).body:
            if isinstance(node, ast.Assign) and getattr(node.targets[0], 'id', '') == '_ASSEMBLIES':
                return set(ast.literal_eval(node.value))
    except SyntaxError:
        pass
    return set()


def _dotnet_imports(text):
    found = []
    for i, line in enumerate(code_with_strings(text).splitlines(), 1):
        m = re.match(r'\s*(?:from\s+((?:System|Autodesk)[\w.]*)\s+import|import\s+((?:System|Autodesk)[\w.]*))', line)
        if m:
            found.append((i, m.group(1) or m.group(2)))
    return found


def rule_assemblies_referenced(files, ext):
    have = _assemblies(files)
    bad = []
    for name, text in py_files(files).items():
        for _, ns in _dotnet_imports(text):
            if ns.startswith('Autodesk.Revit'):
                continue
            need = ASSEMBLY_FOR.get(ns)
            if need is None:
                bad.append('{0}: no ASSEMBLY_FOR entry for {1}'.format(name, ns))
            elif not have.intersection(need):
                bad.append('{0}: {1} needs one of {2} in eim_clr'.format(name, ns, need))
    return bad


def rule_clr_first(files, ext):
    bad = []
    for name, text in py_files(files).items():
        if name in PURE:
            continue
        imports = _dotnet_imports(text)
        if not imports:
            continue
        lines = code_with_strings(text).splitlines()
        clr_line = None
        for i, line in enumerate(lines, 1):
            if re.match(r'\s*import eim_clr\b', line):
                clr_line = i
                break
        if clr_line is None or clr_line > imports[0][0]:
            bad.append('{0}: imports {1} before eim_clr'.format(name, imports[0][1]))
    return bad


def rule_code_bans(files, ext):
    bad = []
    for name, text in py_files(files).items():
        if name in ('import_check.py', 'bench_logic.py', 'make_icons.py'):
            continue
        plain = code_only(text)
        strings = code_with_strings(text)
        if re.search(r'(?<![\w.])print\s*[\("\']', plain) or re.search(r'^\s*print\s', strings, re.M):
            bad.append('{0}: print'.format(name))
        if _has_fstring(text):
            bad.append('{0}: f-string'.format(name))
        if re.search(r'\.\s*IntegerValue\b', plain):
            bad.append('{0}: bare .IntegerValue'.format(name))
        if re.search(r'\bUri\b', plain):
            bad.append('{0}: System.Uri (moved in Revit 2025)'.format(name))
        if re.search(r'AddReference\s*\(\s*""\s*\)', plain) and name != 'eim_clr.py':
            bad.append('{0}: clr.AddReference outside eim_clr'.format(name))
        if re.search(r'\bAddReference\b', plain) and name != 'eim_clr.py':
            bad.append('{0}: clr.AddReference outside eim_clr'.format(name))
        if re.search(r"RevitAPI", strings) and 'AddReference' in strings:
            bad.append('{0}: references RevitAPI'.format(name))
    return bad


def rule_no_duplicate_defs(files, ext):
    bad = []
    for name, text in py_files(files).items():
        try:
            tree = ast.parse(text)
        except SyntaxError as ex:
            bad.append('{0}: syntax error {1}'.format(name, ex))
            continue
        scopes = [tree] + [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
        for scope in scopes:
            seen = set()
            for node in scope.body:
                if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                    if node.name in seen:
                        bad.append('{0}: {1} defined twice'.format(name, node.name))
                    seen.add(node.name)
    return bad


def rule_delegates_held(files, ext):
    """Event handlers must be stored delegate objects, never bound methods,
    or they cannot be unhooked."""
    text = code_with_strings(files.get('eim_runner.py', ''))
    bad = []
    if re.search(r'\+=\s*self\._on_', text):
        bad.append('eim_runner.py: event hooked with a bare bound method')
    for ev in ('Idling', 'DocumentChanged', 'DialogBoxShowing'):
        if ev + ' +=' in text and ev + ' -=' not in text:
            bad.append('eim_runner.py: {0} is hooked but never unhooked'.format(ev))
    if 'SetRaiseWithoutDelay' not in text:
        bad.append('eim_runner.py: Idling never asks to keep firing')
    return bad


def rule_canvas_dark_test(files, ext):
    """UITheme.Dark is 0 - the read must be tested 'is not None'."""
    text = code_with_strings(files.get('eim_theme.py', ''))
    m = re.search(r'def canvas_is_dark\(\):(.*?)(?=\ndef )', text, re.S)
    body = m.group(1) if m else ''
    bad = []
    if 'is not None' not in body:
        bad.append('eim_theme.canvas_is_dark does not test the read with is not None')
    if re.search(r'\bor\s+getattr\(mgr', body) or re.search(r'if\s+value\s*:', body):
        bad.append('eim_theme.canvas_is_dark tests the theme by truthiness')
    if re.search(r'^\s*from Autodesk\.Revit\.UI import UIThemeManager', files.get('eim_theme.py', ''), re.M):
        bad.append('eim_theme imports UIThemeManager at the top (missing before 2024)')
    return bad


def rule_persistent_engine(files, ext):
    text = code_with_strings(files.get('script.py', ''))
    if not re.search(r'^__persistentengine__\s*=\s*True', text, re.M):
        return ['script.py: Idling handlers need __persistentengine__ = True']
    return []


def rule_version_changelog(files, ext):
    m = re.search(r"__version__\s*=\s*u?'(\d+\.\d+\.\d+)'", files.get('eim_version.py', ''))
    if not m:
        return ['eim_version.py: no x.y.z __version__']
    if '## ' + m.group(1) not in files.get('CHANGELOG.md', ''):
        return ['CHANGELOG.md has no entry for ' + m.group(1)]
    if 'VersionText' not in files.get('ExplodePrompt.xaml', '') or '__version__' not in code_with_strings(files.get('eim_window.py', '')):
        return ['the window does not show __version__']
    return []


def rule_no_shared_files(files, ext):
    bad = []
    for rel in SHARED_SINGULAR:
        if os.path.exists(os.path.join(ext, rel)):
            bad.append('delivery ships shared file ' + rel)
    if os.path.isdir(os.path.join(ext, 'hooks')):
        bad.append('delivery ships hooks')
    for root, dirs, fnames in os.walk(ext):
        if root.endswith(('.panel', '.pulldown')) and 'bundle.yaml' in fnames:
            bad.append('delivery ships ' + os.path.relpath(os.path.join(root, 'bundle.yaml'), ext))
    return bad


RULES = [rule_xaml_parses, rule_no_static_resource, rule_dynamic_keys_defined,
         rule_style_target, rule_palette_keys, rule_findname, rule_assemblies_referenced,
         rule_clr_first, rule_code_bans, rule_no_duplicate_defs, rule_delegates_held,
         rule_canvas_dark_test, rule_persistent_engine, rule_version_changelog,
         rule_no_shared_files]


# ==========================================================================
# Selftest - one deliberate breakage per rule
# ==========================================================================

def _sub(name, old, new):
    def mutate(files):
        assert old in files[name], 'selftest anchor missing in {0}: {1!r}'.format(name, old)
        files[name] = files[name].replace(old, new, 1)
    return mutate


def _shared_file(ext_tmp):
    def mutate(files):
        with io.open(os.path.join(ext_tmp, 'startup.py'), 'w', encoding='utf-8') as fh:
            fh.write(u'# shipped by mistake\n')
    return mutate


BREAKAGES = [
    (rule_xaml_parses, _sub('ExplodePrompt.xaml', '<!-- ==================== header', '<!-- -- header')),
    (rule_xaml_parses, _sub('ExplodePrompt.xaml', 'VerticalAlignment="Center"/>', 'VerticalAlignment="Baseline"/>')),
    (rule_no_static_resource, _sub('ExplodePrompt.xaml', '{DynamicResource Bg}', '{StaticResource Bg}')),
    (rule_dynamic_keys_defined, _sub('ExplodePrompt.xaml', '{DynamicResource Bg}', '{DynamicResource Bgx}')),
    (rule_style_target, _sub('ExplodePrompt.xaml', 'x:Name="CloseButton" Style="{DynamicResource CloseBorder}"',
                             'x:Name="CloseButton" Style="{DynamicResource CardButton}"')),
    (rule_palette_keys, _sub('eim_theme.py', "'Sel': '#2B5473'", "'Sel': '#2B5473', 'Ghost': '#000000'")),
    (rule_findname, _sub('eim_window.py', "'StatusText']", "'StatusText', 'NoSuchName']")),
    (rule_assemblies_referenced, _sub('eim_clr.py', "'UIAutomationClient', 'UIAutomationTypes',", '')),
    (rule_assemblies_referenced, _sub('eim_window.py', 'from System.IO import File, MemoryStream',
                                      'from System.IO import File, MemoryStream\nfrom System.Data import DataTable')),
    (rule_clr_first, _sub('eim_runner.py', 'import eim_clr  # noqa: F401  (assembly references first)\n', '')),
    (rule_code_bans, _sub('eim_core.py', "return int(element_id.Value)", "return int(element_id.IntegerValue)")),
    (rule_code_bans, _sub('eim_window.py', "self.VersionText.Text = u'v' + __version__",
                          "self.VersionText.Text = f'v{__version__}'")),
    (rule_code_bans, _sub('eim_window.py', 'from System.IO import File, MemoryStream',
                          'from System import Uri\nfrom System.IO import File, MemoryStream')),
    (rule_no_duplicate_defs, _sub('eim_core.py', 'def plural(', 'def classify(x):\n    return x\n\n\ndef plural(')),
    (rule_delegates_held, _sub('eim_runner.py', 'self.uiapp.Idling += self._idling', 'self.uiapp.Idling += self._on_idling')),
    (rule_delegates_held, _sub('eim_runner.py', 'args.SetRaiseWithoutDelay()', 'pass')),
    (rule_canvas_dark_test, _sub('eim_theme.py', 'if value is not None:', 'if value:')),
    (rule_persistent_engine, _sub('script.py', '__persistentengine__ = True', '__persistentengine__ = False')),
    (rule_version_changelog, _sub('eim_version.py', "__version__ = u'", "__version__ = u'9")),
]


def run(files, ext):
    failures = []
    for rule in RULES:
        for f in rule(files, ext):
            failures.append('{0}: {1}'.format(rule.__name__, f))
    return failures


def selftest():
    import shutil
    import tempfile
    ok = True
    base = load_files()
    for rule, mutate in BREAKAGES:
        files = dict(base)
        mutate(files)
        if not rule(files, EXT_ROOT):
            ok = False
            sys.stdout.write('SELFTEST FAIL: {0} did not catch its breakage\n'.format(rule.__name__))
    tmp = tempfile.mkdtemp()
    try:
        files = dict(base)
        _shared_file(tmp)(files)
        if not rule_no_shared_files(files, tmp):
            ok = False
            sys.stdout.write('SELFTEST FAIL: rule_no_shared_files missed startup.py\n')
    finally:
        shutil.rmtree(tmp)
    covered = set(r for r, _ in BREAKAGES) | set([rule_no_shared_files])
    for rule in RULES:
        if rule not in covered:
            ok = False
            sys.stdout.write('SELFTEST FAIL: {0} has no deliberate breakage\n'.format(rule.__name__))
    sys.stdout.write('selftest: {0} breakages, {1}\n'.format(len(BREAKAGES) + 1, 'all caught' if ok else 'FAILED'))
    return ok


def main():
    if '--selftest' in sys.argv:
        return 0 if selftest() else 1
    failures = run(load_files(), EXT_ROOT)
    for f in failures:
        sys.stdout.write(f + '\n')
    sys.stdout.write('import_check: {0} rules, {1}\n'.format(
        len(RULES), 'all pass' if not failures else '{0} failure(s)'.format(len(failures))))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
