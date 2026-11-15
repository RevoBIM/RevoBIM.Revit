# -*- coding: utf-8 -*-
"""Circuit Manager - static bench. Run under plain CPython 3 from this folder:

    python import_check.py            check the tool
    python import_check.py --selftest break every rule on purpose and
                                      confirm each one is caught

A rule nobody has seen fail does not work, so every rule has a breakage.
A breakage whose anchor text is missing fails the selftest outright.
"""
import ast
import io
import os
import re
import shutil
import sys
import symtable
import tempfile
import tokenize
import xml.dom.minidom

HERE = os.path.dirname(os.path.abspath(__file__))
XAML_NS = '{http://schemas.microsoft.com/winfx/2006/xaml}'

# namespace -> assemblies that provide it on 4.8 or .NET 8
ASSEMBLY_FOR = {
    'System': ['System', 'mscorlib', 'System.Runtime'],
    'System.IO': ['mscorlib', 'System.Runtime', 'System'],
    'System.Data': ['System.Data', 'System.Data.Common'],
    'System.Collections.Generic': ['mscorlib', 'System.Collections',
                                   'System.Runtime'],
    'System.Windows': ['PresentationFramework', 'PresentationCore',
                       'WindowsBase'],
    'System.Windows.Controls': ['PresentationFramework'],
    'System.Windows.Controls.Primitives': ['PresentationFramework'],
    'System.Windows.Data': ['PresentationFramework'],
    'System.Windows.Input': ['PresentationCore', 'PresentationFramework',
                             'WindowsBase'],
    'System.Windows.Interop': ['PresentationFramework', 'PresentationCore',
                               'WindowsBase'],
    'System.Windows.Markup': ['PresentationFramework', 'System.Xaml'],
    'System.Windows.Media': ['PresentationCore'],
    'System.Windows.Media.Imaging': ['PresentationCore'],
    'System.Windows.Shapes': ['PresentationFramework'],
    'System.Windows.Threading': ['WindowsBase'],
    'System.Windows.Forms': ['System.Windows.Forms'],
}
REQUIRED_CHROME = ['header_bar', 'body', 'root_grid', 'shrink_btn',
                   'shrink_glyph', 'expand_glyph', 'theme_btn',
                   'theme_text', 'theme_glyph', 'version_text', 'close_btn',
                   'icon_img']


def read(folder, name):
    with io.open(os.path.join(folder, name), 'r', encoding='utf-8') as fh:
        return fh.read()


def py_files(folder):
    return sorted(f for f in os.listdir(folder)
                  if f.endswith('.py') and f.startswith(('cm_', 'script')))


def layouts(folder):
    return sorted(f for f in os.listdir(folder)
                  if f.endswith('.xaml') and f != 'Theme.xaml')


def code_only(src):
    """Source with every string literal and comment blanked in place - rules
    must test the code, never a docstring that mentions the thing."""
    lines = src.splitlines(True)
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except Exception:
        return src
    for tok in reversed(toks):
        if tok.type not in (tokenize.STRING, tokenize.COMMENT):
            continue
        (r0, c0), (r1, c1) = tok.start, tok.end
        fill = '""' if tok.type == tokenize.STRING else ''
        if r0 == r1:
            ln = lines[r0 - 1]
            lines[r0 - 1] = ln[:c0] + fill + ln[c1:]
        else:
            first = lines[r0 - 1][:c0] + fill
            last = lines[r1 - 1][c1:]
            lines[r0 - 1:r1] = [first + last]
    return ''.join(lines)


def theme_keys(folder):
    dom = xml.dom.minidom.parseString(read(folder, 'Theme.xaml'))
    keys = set()
    for node in dom.getElementsByTagName('*'):
        k = node.getAttribute('x:Key')
        if k:
            keys.add(k)
    brushes = set(n.getAttribute('x:Key') for n in
                  dom.getElementsByTagName('SolidColorBrush'))
    return keys, brushes


# ======================================================================
# rules - each returns a list of problems
# ======================================================================
def rule_xaml_parses(folder):
    bad = []
    for f in [x for x in os.listdir(folder) if x.endswith('.xaml')]:
        try:
            xml.dom.minidom.parseString(read(folder, f).encode('utf-8'))
        except Exception as ex:
            bad.append('{0}: {1}'.format(f, ex))
    return bad


def rule_clr_first(folder):
    bad = []
    for f in py_files(folder):
        if f in ('cm_clr.py', 'script.py'):
            continue
        tree = ast.parse(read(folder, f))
        seen_clr = False
        for node in tree.body:
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
                if 'cm_clr' in names:
                    seen_clr = True
                if any(n.startswith(('System', 'Autodesk')) for n in names) \
                        and not seen_clr:
                    bad.append('{0}: .NET import before cm_clr'.format(f))
            if isinstance(node, ast.ImportFrom) and node.module and \
                    node.module.startswith(('System', 'Autodesk')) and \
                    not seen_clr:
                bad.append('{0}: from {1} before cm_clr'.format(f, node.module))
    return bad


def referenced_assemblies(folder):
    """Assemblies cm_clr references at import time (outside any def)."""
    tree = ast.parse(read(folder, 'cm_clr.py'))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                getattr(t, 'id', '') == '_ASSEMBLIES' for t in node.targets):
            return set(ast.literal_eval(node.value))
    return set()


def rule_assemblies_referenced(folder):
    have = referenced_assemblies(folder)
    bad = []
    for f in py_files(folder):
        tree = ast.parse(read(folder, f))
        for node in ast.walk(tree):
            mods = []
            if isinstance(node, ast.ImportFrom) and node.module:
                mods = [node.module]
            elif isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            for m in mods:
                if not m.startswith('System'):
                    continue
                need = ASSEMBLY_FOR.get(m)
                if need is None:
                    bad.append('{0}: no assembly table entry for {1}'.format(
                        f, m))
                elif not have.intersection(need):
                    bad.append('{0}: {1} needs one of {2}'.format(f, m, need))
    return bad


def rule_banned_python(folder):
    bad = []
    for f in py_files(folder):
        src = read(folder, f)
        code = code_only(src)
        try:
            toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
        except Exception:
            toks = []
        fstart = getattr(tokenize, 'FSTRING_START', None)   # 3.12+
        for tok in toks:
            if (fstart is not None and tok.type == fstart) or (
                    tok.type == tokenize.STRING and
                    re.match(r'^[rRbBuU]*[fF]', tok.string)):
                bad.append('{0}: f-string'.format(f))
                break
        if re.search(r'^\s*print\s', code, re.M):
            bad.append('{0}: print statement'.format(f))
        if re.search(r'\.IntegerValue\b', code):
            bad.append('{0}: bare .IntegerValue'.format(f))
        if re.search(r'\bUri\b|UriSource', code):
            bad.append('{0}: System.Uri'.format(f))
        if 'Storyboard' in code:
            bad.append('{0}: Storyboard'.format(f))
    return bad


def rule_ascii(folder):
    """Non-ASCII only inside u'' literals (IronPython 2.7 str is bytes)."""
    bad = []
    for f in py_files(folder) + ['import_check.py', 'bench_logic.py']:
        if not os.path.isfile(os.path.join(folder, f)):
            continue
        src = read(folder, f)
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if all(ord(c) < 128 for c in tok.string):
                continue
            if tok.type == tokenize.STRING and tok.string[:1] in 'uU':
                continue
            if tok.type == tokenize.COMMENT:
                continue
            bad.append('{0}:{1} non-ASCII outside u\'\''.format(f, tok.start[0]))
    return bad


def rule_layout_resources(folder):
    keys, brushes = theme_keys(folder)
    bad = []
    for f in [x for x in os.listdir(folder) if x.endswith('.xaml')]:
        text = read(folder, f)
        if f != 'Theme.xaml' and 'StaticResource' in text:
            bad.append('{0}: StaticResource in a layout'.format(f))
        for k in re.findall(r'\{DynamicResource\s+([\w]+)\}', text):
            if k not in keys:
                bad.append('{0}: DynamicResource {1} not in Theme.xaml'.format(
                    f, k))
        if re.search(r'BasedOn="\{DynamicResource', text):
            bad.append('{0}: BasedOn with DynamicResource'.format(f))
        if re.search(r'VerticalAlignment="Baseline"', text):
            bad.append('{0}: Baseline alignment kills XamlReader'.format(f))
    for f in py_files(folder):
        code = read(folder, f)
        for k in code_resource_keys(code):
            if k not in keys:
                bad.append('{0}: resource key {1} not in Theme.xaml'.format(
                    f, k))
        for k in re.findall(r"\{DynamicResource (\w+)\}", code):
            if k not in keys:
                bad.append('{0}: {1} not in Theme.xaml'.format(f, k))
    return bad


def code_resource_keys(code):
    """Every key handed to SetResourceReference, DynamicResourceExtension,
    FindResource or cm_main's STATE_STYLES table - conditional forms too."""
    out = []
    tree = ast.parse(code)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = getattr(node.func, 'attr', getattr(node.func, 'id', ''))
            if name in ('SetResourceReference', 'DynamicResourceExtension',
                        'FindResource'):
                args = node.args[1:] if name == 'SetResourceReference' \
                    else node.args
                for a in args:
                    for c in ast.walk(a):
                        if isinstance(c, ast.Constant) and \
                                isinstance(c.value, str):
                            out.append(c.value)
        if isinstance(node, ast.Assign) and any(
                getattr(t, 'id', '') == 'STATE_STYLES' for t in node.targets):
            for row in ast.literal_eval(node.value):
                out.extend(k for k in row[1:3] if isinstance(k, str))
    return out


def palettes(folder):
    tree = ast.parse(read(folder, 'cm_theme.py'))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                getattr(t, 'id', '') == 'PALETTES' for t in node.targets):
            return ast.literal_eval(node.value)
    return {}


def rule_palettes_match(folder):
    keys, brushes = theme_keys(folder)
    pals = palettes(folder)
    bad = []
    if set(pals) != set(['dark', 'light']):
        bad.append('palettes must be dark and light')
    for name, pal in pals.items():
        if set(pal) != brushes:
            bad.append('{0} palette keys differ from Theme.xaml brushes: {1}'
                       .format(name, sorted(set(pal) ^ brushes)))
    revit_dark = {'TitleBg': '#222933', 'BodyBg': '#3C4454',
                  'FieldBg': '#2D3441', 'SelBg': '#3A7392'}
    for k, v in revit_dark.items():
        if pals.get('dark', {}).get(k, '').upper() != v.upper():
            bad.append('dark {0} is not Revit dark {1}'.format(k, v))
    return bad


def rule_find_names(folder):
    names = set()
    for f in layouts(folder):
        names.update(re.findall(r'x:Name="(\w+)"', read(folder, f)))
    bad = []
    for f in py_files(folder):
        code = read(folder, f)
        for n in re.findall(r"(?:find|FindName)\('(\w+)'\)", code):
            if n not in names:
                bad.append('{0}: find(\'{1}\') has no x:Name'.format(f, n))
    return bad


def rule_window_chrome(folder):
    """Every window draws the full chrome, the expand glyph starts hidden."""
    bad = []
    for f in layouts(folder):
        text = read(folder, f)
        for n in REQUIRED_CHROME:
            if 'x:Name="{0}"'.format(n) not in text:
                bad.append('{0}: missing {1}'.format(f, n))
        m = re.search(r'<Path x:Name="expand_glyph"[^>]*>', text)
        if m and 'Visibility="Collapsed"' not in m.group(0):
            bad.append('{0}: expand_glyph not collapsed at start'.format(f))
        if m and 'Green' not in m.group(0):
            bad.append('{0}: expand arrow is not green'.format(f))
        if 'Text="v0.0.0"' not in text:
            bad.append('{0}: version must come from cm_version'.format(f))
    return bad


def rule_windows_themed(folder):
    """Every class with a LAYOUT builds on ThemedWindow (drawer, chip),
    every layout on disk is used by one, and ThemedWindow attaches it."""
    bad = []
    used = set()
    for f in py_files(folder):
        tree = ast.parse(read(folder, f))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            layout = None
            for st in node.body:
                if isinstance(st, ast.Assign) and any(
                        getattr(t, 'id', '') == 'LAYOUT' for t in st.targets):
                    layout = getattr(st.value, 'value', None)
            if layout is None or node.name == 'ThemedWindow':
                continue
            used.add(layout)
            bases = [getattr(b, 'id', '') for b in node.bases]
            if 'ThemedWindow' not in bases:
                bad.append('{0}.{1}: not a ThemedWindow'.format(f, node.name))
    for f in layouts(folder):
        if f not in used:
            bad.append('{0}: no window class loads it'.format(f))
    chrome = code_only(read(folder, 'cm_chrome.py'))
    if 'cm_drawer.attach(' not in chrome:
        bad.append('ThemedWindow never attaches a drawer')
    if 'theme_btn' not in read(folder, 'cm_chrome.py'):
        bad.append('ThemedWindow never wires the theme chip')
    return bad


def rule_drawer_wired(folder):
    code = code_only(read(folder, 'cm_drawer.py'))
    bad = []
    if not re.search(r'btn\.Click\s*\+=', code):
        bad.append('shrink button never wired')
    if not re.search(r'window\.Closed\s*\+=', code):
        bad.append('drawer never released on close')
    for fn in ('def shrink', 'def expand'):
        i = code.find(fn)
        j = code.find('def ', i + 5)
        if i < 0 or 'release(' not in code[i:j]:
            bad.append('{0}: animations not released'.format(fn))
    if 'BeginAnimation(self.Window.TopProperty, None)' not in code or \
            'BeginAnimation(self.Window.HeightProperty, None)' not in code:
        bad.append('Top / Height never released')
    tick = [n for n in ast.walk(ast.parse(read(folder, 'cm_drawer.py')))
            if isinstance(n, ast.FunctionDef) and n.name == 'tick']
    lands = False
    for fn in tick:
        for t in ast.walk(fn):
            if isinstance(t, ast.Try):
                for h in t.handlers:
                    for c in ast.walk(h):
                        if isinstance(c, ast.Call) and \
                                getattr(c.func, 'id', '') == 'finish':
                            lands = True
    if not lands:
        bad.append('a frame that throws does not land the window')
    return bad


def rule_no_duplicates(folder):
    bad = []
    for f in py_files(folder):
        tree = ast.parse(read(folder, f))
        scopes = [tree] + [n for n in ast.walk(tree)
                           if isinstance(n, ast.ClassDef)]
        for scope in scopes:
            seen = set()
            for st in scope.body:
                if isinstance(st, (ast.FunctionDef, ast.ClassDef)):
                    if st.name in seen:
                        bad.append('{0}: {1} defined twice'.format(f, st.name))
                    seen.add(st.name)
    return bad


BUILTINS = set(dir(__builtins__)) if not isinstance(__builtins__, dict) \
    else set(__builtins__.keys())
BUILTINS.update(['unicode', '__revit__', '__file__', '__name__'])


def rule_globals_exist(folder):
    """Every global a function reaches for exists in its module."""
    bad = []
    for f in py_files(folder):
        src = read(folder, f)
        top = symtable.symtable(src, f, 'exec')
        defined = set(s.get_name() for s in top.get_symbols()
                      if s.is_assigned() or s.is_imported())

        def walk(table):
            for child in table.get_children():
                for s in child.get_symbols():
                    if s.is_global() and s.is_referenced() and \
                            s.get_name() not in defined and \
                            s.get_name() not in BUILTINS:
                        bad.append('{0}: {1} uses undefined {2}'.format(
                            f, child.get_name(), s.get_name()))
                walk(child)
        walk(top)
    # module.attr across the tool's own modules: the helper must still exist
    tops = {}
    for f in py_files(folder):
        tree = ast.parse(read(folder, f))
        names = set()
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    for c in ast.walk(t):
                        if isinstance(c, ast.Name):
                            names.add(c.id)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for a in node.names:
                    names.add((a.asname or a.name).split('.')[0])
        tops[f[:-3]] = names
    for f in py_files(folder):
        for node in ast.walk(ast.parse(read(folder, f))):
            if isinstance(node, ast.Attribute) and \
                    isinstance(node.value, ast.Name) and \
                    node.value.id in tops and node.value.id != f[:-3] and \
                    node.attr not in tops[node.value.id]:
                bad.append('{0}: {1}.{2} does not exist'.format(
                    f, node.value.id, node.attr))
    return bad


def rule_thin_loader(folder):
    tree = ast.parse(read(folder, 'script.py'))
    bad = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mods = [a.name for a in node.names] if isinstance(
                node, ast.Import) else [node.module]
            for m in mods:
                if m not in ('os', 'sys'):
                    bad.append('script.py imports {0} at load'.format(m))
    if 'AddReference' in code_only(read(folder, 'script.py')):
        bad.append('script.py references assemblies')
    if '__persistentengine__ = True' not in read(folder, 'script.py'):
        bad.append('modeless window without a persistent engine')
    return bad


def rule_changelog(folder):
    m = re.search(r'__version__\s*=\s*"([\d.]+)"', read(folder, 'cm_version.py'))
    ver = m.group(1) if m else '?'
    if not os.path.isfile(os.path.join(folder, 'CHANGELOG.md')):
        return ['no CHANGELOG.md']
    if '## ' + ver not in read(folder, 'CHANGELOG.md'):
        return ['CHANGELOG.md has no entry for {0}'.format(ver)]
    return []


def rule_writes_via_event(folder):
    """No Transaction started from the window - writes go through Runner."""
    bad = []
    for f in py_files(folder):
        if f == 'cm_revit.py':
            continue
        if re.search(r'\bTransaction\s*\(', code_only(read(folder, f))):
            bad.append('{0}: starts a Transaction outside cm_revit'.format(f))
    main = code_only(read(folder, 'cm_main.py'))
    if 'self.runner.submit(' not in main:
        bad.append('apply never goes through the ExternalEvent runner')
    rv = code_only(read(folder, 'cm_revit.py'))
    if 'self.queue = []' in rv.split('def submit', 1)[-1].split('def execute')[0]:
        bad.append('submit clears the whole queue')
    return bad


def rule_editable_columns(folder):
    """DataGridBoundColumn coerces IsReadOnly to True for a OneWay or
    OneTime binding - silently. That made Path Offset uneditable in 1.0.0.
    Editable text columns bind TwoWay + Explicit and stage in CellEditEnding."""
    code = code_only(read(folder, 'cm_main.py'))
    bad = []
    if re.search(r'BindingMode\.(OneWay|OneTime)\b', code):
        bad.append('a OneWay / OneTime binding makes its column read only')
    if 'BindingMode.TwoWay' not in code or \
            'UpdateSourceTrigger.Explicit' not in code:
        bad.append('editable columns must bind TwoWay + Explicit')
    if 'CellEditEnding +=' not in code:
        bad.append('nothing stages a typed edit')
    return bad


RULES = [
    ('xaml_parses', rule_xaml_parses),
    ('clr_first', rule_clr_first),
    ('assemblies_referenced', rule_assemblies_referenced),
    ('banned_python', rule_banned_python),
    ('ascii', rule_ascii),
    ('layout_resources', rule_layout_resources),
    ('palettes_match', rule_palettes_match),
    ('find_names', rule_find_names),
    ('window_chrome', rule_window_chrome),
    ('windows_themed', rule_windows_themed),
    ('drawer_wired', rule_drawer_wired),
    ('no_duplicates', rule_no_duplicates),
    ('globals_exist', rule_globals_exist),
    ('thin_loader', rule_thin_loader),
    ('changelog', rule_changelog),
    ('writes_via_event', rule_writes_via_event),
    ('editable_columns', rule_editable_columns),
]


def run(folder, quiet=False):
    failed = {}
    for name, fn in RULES:
        try:
            problems = fn(folder)
        except Exception as ex:
            problems = ['rule crashed: {0!r}'.format(ex)]
        if problems:
            failed[name] = problems
        if not quiet:
            print('{0:24s} {1}'.format(name, 'FAIL' if problems else 'ok'))
            for p in problems:
                print('    - ' + p)
    return failed


# ======================================================================
# selftest - (rule, file, anchor, replacement)
# ======================================================================
BREAKAGES = [
    ('xaml_parses', 'Message.xaml', '<!-- ==================== body',
     '<!-- -- body'),
    ('clr_first', 'cm_theme.py', 'import cm_clr  # noqa: F401\nimport os',
     'import os'),
    ('assemblies_referenced', 'cm_clr.py', "'mscorlib', 'System', 'System.Core', 'System.Data', 'System.Data.Common',",
     "'mscorlib', 'System', 'System.Core',"),
    ('banned_python', 'cm_logic.py', "return u'{0:.1f}'.format(float(mm))",
     "return f'{mm:.1f}'"),
    ('banned_python', 'cm_revit.py', "return getattr(element_id, 'IntegerValue')",
     "return element_id.IntegerValue"),
    ('ascii', 'cm_main.py', "u'Pick values to show'", "'Pick values " + chr(8594) + " show'"),
    ('layout_resources', 'CircuitManager.xaml', '{DynamicResource ToolbarBg}',
     '{StaticResource ToolbarBg}'),
    ('layout_resources', 'cm_main.py', "'StagedBg', 'StagedText'",
     "'StagedBgX', 'StagedText'"),
    ('palettes_match', 'cm_theme.py', "'CopyBg': '#FBE3A6', ", ''),
    ('palettes_match', 'cm_theme.py', "'TitleBg': '#222933'", "'TitleBg': '#1C1C1F'"),
    ('find_names', 'cm_main.py', "self.find('sel_text')", "self.find('sel_txt')"),
    ('window_chrome', 'ParamPicker.xaml', 'x:Name="shrink_btn"', 'x:Name="shrink_button"'),
    ('window_chrome', 'Message.xaml', '<Path x:Name="expand_glyph" Visibility="Collapsed"',
     '<Path x:Name="expand_glyph"'),
    ('windows_themed', 'cm_dialogs.py', 'class ParamPicker(ThemedWindow):',
     'class ParamPicker(object):'),
    ('windows_themed', 'cm_chrome.py', 'self.drawer = cm_drawer.attach(self.win, self.find)',
     'self.drawer = None'),
    ('drawer_wired', 'cm_drawer.py', "btn.Click += lambda s, a: drawer.toggle()",
     "pass"),
    ('drawer_wired', 'cm_drawer.py',
     "            window.BeginAnimation(self.Window.HeightProperty, None)",
     "            pass"),
    ('drawer_wired', 'cm_drawer.py',
     "            except Exception as ex:\n                self.errors.append(ex)\n                finish()\n",
     ""),
    ('no_duplicates', 'cm_main.py', '    def col_label(self, key):',
     '    def undo(self):\n        pass\n\n    def col_label(self, key):'),
    ('globals_exist', 'cm_logic.py', 'def free_slot(used):', 'def free_slot_gone(used):'),
    ('thin_loader', 'script.py', 'import os\nimport sys',
     'import os\nimport sys\nimport clr'),
    ('thin_loader', 'script.py', '__persistentengine__ = True', '__persistentengine__ = False'),
    ('changelog', 'cm_version.py', '__version__ = "1.0.1"', '__version__ = "9.9.9"'),
    ('editable_columns', 'cm_main.py', 'b.Mode = BindingMode.TwoWay',
     'b.Mode = BindingMode.OneWay'),
    ('editable_columns', 'cm_main.py',
     '            b.UpdateSourceTrigger = UpdateSourceTrigger.Explicit\n', ''),
    ('writes_via_event', 'cm_main.py', 'if not self.runner.submit(job, done):',
     'if not cm_revit.apply_changes(self.doc, changes):'),
]


def selftest():
    ok = True
    if run(HERE, quiet=True):
        print('the clean tool fails - fix that first')
        run(HERE)
        return False
    for rule, f, anchor, repl in BREAKAGES:
        tmp = tempfile.mkdtemp()
        try:
            for name in os.listdir(HERE):
                p = os.path.join(HERE, name)
                if os.path.isfile(p):
                    shutil.copy(p, tmp)
            path = os.path.join(tmp, f)
            text = read(tmp, f)
            if anchor not in text:
                print('BROKEN SELFTEST  {0}: anchor missing in {1}'.format(
                    rule, f))
                ok = False
                continue
            with io.open(path, 'w', encoding='utf-8') as fh:
                fh.write(text.replace(anchor, repl, 1))
            failed = run(tmp, quiet=True)
            caught = rule in failed
            print('{0:8s} {1:24s} {2}'.format('caught' if caught else 'MISSED',
                                              rule, f))
            ok = ok and caught
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print('SELFTEST ' + ('PASSED ({0} breakages)'.format(len(BREAKAGES))
                         if ok else 'FAILED'))
    return ok


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(0 if selftest() else 1)
    failed = run(HERE)
    print('IMPORT CHECK ' + ('FAILED' if failed else 'PASSED ({0} rules)'.format(
        len(RULES))))
    sys.exit(1 if failed else 0)
