# -*- coding: utf-8 -*-
"""Static rules. python import_check.py, or --selftest to prove every rule catches its breakage."""
import ast
import glob
import importlib
import os
import re
import shutil
import symtable
import sys
import tempfile
import xml.dom.minidom as minidom

HERE = os.path.dirname(os.path.abspath(__file__))
MODULES = ['pm_clr', 'pm_core', 'pm_spfile', 'pm_xlsx', 'pm_revit', 'pm_theme', 'pm_drawer',
           'pm_chrome', 'pm_dialogs', 'pm_main']
LAYOUTS = ['ParaManager', 'Prompt', 'Input', 'Categories', 'Groups', 'Rename', 'PickParams']
ASSEMBLY_FOR = {
    'System': ['System', 'mscorlib'], 'System.Collections.Generic': ['System.Collections', 'mscorlib'],
    'System.Data': ['System.Data', 'System.Data.Common'], 'System.IO': ['mscorlib'],
    'System.IO.Compression': ['System.IO.Compression'], 'System.Text': ['mscorlib'],
    'System.Windows': ['PresentationFramework', 'WindowsBase'],
    'System.Windows.Controls': ['PresentationFramework'],
    'System.Windows.Controls.Primitives': ['PresentationFramework'],
    'System.Windows.Data': ['PresentationFramework'], 'System.Windows.Forms': ['System.Windows.Forms'],
    'System.Windows.Input': ['PresentationCore', 'WindowsBase'],
    'System.Windows.Interop': ['PresentationFramework'], 'System.Windows.Markup': ['PresentationFramework'],
    'System.Windows.Media': ['PresentationCore'], 'System.Windows.Media.Imaging': ['PresentationCore'],
    'System.Windows.Shapes': ['PresentationFramework'],
    'System.Windows.Threading': ['WindowsBase'], 'Microsoft.Win32': ['PresentationFramework'],
}
RUNTIME_KEYS = ['ScopeItems', 'YesNoItems', 'DiscList', 'GroupItems', 'SpTypeItems', 'SpGroupItems']


def read(root, name):
    with open(os.path.join(root, name), encoding='utf-8') as src:
        return src.read()


def sources(root):
    return dict((m, read(root, m + '.py')) for m in MODULES)


def code_only(text):
    """Comments and strings blanked, so no rule can pass by reading prose."""
    tree = ast.parse(text)
    lines = text.split('\n')
    spans = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            spans.append((node.lineno, node.col_offset, node.end_lineno, node.end_col_offset))
    for start, col, end, stop in sorted(spans, reverse=True):
        if start == end:
            line = lines[start - 1].encode('utf-8')
            lines[start - 1] = (line[:col] + b"''" + line[stop:]).decode('utf-8', 'ignore')
        else:
            for number in range(start, end + 1):
                lines[number - 1] = ''
    return '\n'.join(re.sub(r'#.*$', '', l) for l in lines)


def composed(root, layout):
    header = re.search(r"HEADER = u'''(.*?)'''", read(root, 'pm_chrome.py'), re.S).group(1)
    return read(root, layout + '.xaml').replace('@@HEADER@@', header).replace('@@TITLE@@', 'T')


def rule_layouts_parse(root):
    out = []
    for name in LAYOUTS:
        try:
            minidom.parseString(composed(root, name).encode('utf-8'))
        except Exception as error:
            out.append('{0}: {1}'.format(name, error))
    try:
        minidom.parseString(read(root, 'Theme.xaml').encode('utf-8'))
    except Exception as error:
        out.append('Theme: {0}'.format(error))
    return out


def rule_clr_first(root):
    out = []
    for name, text in sources(root).items():
        if name == 'pm_clr':
            continue
        first_clr = text.find('import pm_clr')
        hit = re.search(r'^\s*(from|import) (System|Autodesk|Microsoft)', text, re.M)
        if hit and (first_clr < 0 or first_clr > hit.start()):
            out.append(name + ' reaches .NET before pm_clr')
    return out


def rule_assemblies(root):
    tree = ast.parse(read(root, 'pm_clr.py'))
    listed = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and node.targets[0].id == '_ASSEMBLIES':
            listed = [e.value for e in node.value.elts]
    out = []
    for name, text in sources(root).items():
        for namespace in re.findall(r'^\s*from ((?:System|Microsoft)[\w.]*) import', text, re.M):
            needed = ASSEMBLY_FOR.get(namespace)
            if needed is None:
                out.append('{0}: {1} is not in the table'.format(name, namespace))
            elif not set(needed) & set(listed):
                out.append('{0}: nothing references {1}'.format(name, namespace))
    return out


def rule_banned(root):
    out = []
    for name, text in sources(root).items():
        code = code_only(text)
        for pattern, why in ((r'\bf["\']', 'f-string'), (r'^\s*print\b', 'print'),
                             (r'\.IntegerValue', 'IntegerValue'), (r'\bUri\b', 'Uri'),
                             (r'Storyboard', 'Storyboard')):
            if re.search(pattern, code, re.M):
                out.append('{0}: {1}'.format(name, why))
    return out


def rule_ascii(root):
    out = []
    for path in glob.glob(os.path.join(root, '*.py')) + glob.glob(os.path.join(root, '*.xaml')):
        with open(path, 'rb') as src:
            if [b for b in src.read() if b > 127]:
                out.append(os.path.basename(path))
    return out


def theme_keys(root):
    text = read(root, 'Theme.xaml')
    return set(re.findall(r'x:Key="(\w+)"', text))


def palette(root, name):
    body = re.search(name + r' = \{(.*?)\n\}', read(root, 'pm_theme.py'), re.S).group(1)
    return dict(re.findall(r"'(\w+)': '(#\w+)'", body))


def rule_resources(root):
    out = []
    keys = theme_keys(root) | set(RUNTIME_KEYS) | set(palette(root, 'DARK'))
    texts = [read(root, 'Theme.xaml')] + [composed(root, n) for n in LAYOUTS]
    for text in texts:
        if 'StaticResource' in text:
            out.append('StaticResource used')
        for key in re.findall(r'DynamicResource (\w+)', text):
            if key not in keys:
                out.append('no resource ' + key)
    for name, text in sources(root).items():
        for key in re.findall(r"(?:SetResourceReference\([^,]+, |FindResource\()'(\w+)'", text):
            if key not in keys:
                out.append('no resource ' + key)
    return out


def rule_palettes(root):
    dark = palette(root, 'DARK')
    light = palette(root, 'LIGHT')
    out = []
    if set(dark) != set(light):
        out.append('palettes differ')
    theme = theme_keys(root)
    for key in dark:
        if key not in theme:
            out.append('Theme.xaml has no brush ' + key)
    revit = {'TitleBg': '#222933', 'WindowBg': '#3C4454', 'FieldBg': '#2D3441', 'StripBg': '#1B1F24',
             'HeadBg': '#323C48', 'HoverBg': '#444E5E', 'SelBg': '#3A7392', 'Edge': '#515C6B'}
    for key in revit:
        if dark.get(key) != revit[key]:
            out.append('dark {0} is not Revit dark'.format(key))
    return out


def rule_names(root):
    """Every self.e('X') exists in a layout the class can load."""
    names = set()
    for layout in LAYOUTS:
        names |= set(re.findall(r'x:Name="(\w+)"', composed(root, layout)))
    out = []
    for name, text in sources(root).items():
        for found in re.findall(r"\.e\('(\w+)'\)", text):
            if found not in names:
                out.append('{0}: no element {1}'.format(name, found))
    main = read(root, 'pm_main.py')
    window = set(re.findall(r'x:Name="(\w+)"', composed(root, 'ParaManager')))
    for found in re.findall(r"\('(\w+(?:Btn2?|Tick|P|C|S))', self\.on_\w+\)", main):
        if found not in window:
            out.append('main: no element ' + found)
    return out


def rule_chrome(root):
    out = []
    for layout in LAYOUTS:
        text = read(root, layout + '.xaml')
        for part in ('@@HEADER@@', 'x:Name="Root"', 'x:Name="Body"', 'x:Name="Grips"'):
            if part not in text:
                out.append('{0}: missing {1}'.format(layout, part))
    chrome = read(root, 'pm_chrome.py')
    for part in ('x:Name="ShrinkBtn"', 'x:Name="ThemeBtn"', 'x:Name="VersionText"', 'pm_drawer.Drawer('):
        if part not in chrome:
            out.append('chrome: missing ' + part)
    return out


def rule_windows_themed(root):
    out = []
    for module in ('pm_dialogs', 'pm_main'):
        code = code_only(read(root, module + '.py'))
        if re.search(r'\bWindow\(\)', code) or 'XamlReader' in code:
            out.append(module + ' builds a window outside ThemedWindow')
    return out


def rule_drawer(root):
    text = code_only(read(root, 'pm_drawer.py'))
    out = []
    for part, why in (('BeginAnimation(Window.TopProperty, None)', 'Top not released'),
                      ('BeginAnimation(Window.HeightProperty, None)', 'Height not released'),
                      ('window.MinHeight = 0.0', 'MinHeight not relaxed'),
                      ('SizeToContent.Manual', 'SizeToContent not relaxed'),
                      ('self.root.VerticalAlignment = VerticalAlignment.Top', 'body not pinned'),
                      ('self.grips.Visibility = Visibility.Collapsed', 'grips not parked')):
        if part not in text:
            out.append(why)
    tick = re.search(r'def tick\(.*?(?=\n        try:\n            self\.timer)', text, re.S)
    if tick is None or 'except Exception' not in tick.group(0):
        out.append('a throwing frame does not land')
    return out


def rule_no_duplicates(root):
    out = []
    for name, text in sources(root).items():
        tree = ast.parse(text)
        for scope in [tree] + [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
            seen = set()
            for node in scope.body:
                if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                    if node.name in seen:
                        out.append('{0}: {1} defined twice'.format(name, node.name))
                    seen.add(node.name)
    return out


def rule_globals(root):
    builtins = set(dir(__builtins__)) | {'__file__', 'NotImplementedError', 'unicode'}
    out = []
    for name, text in sources(root).items():
        top = symtable.symtable(text, name, 'exec')
        defined = set(s.get_name() for s in top.get_symbols() if s.is_assigned() or s.is_imported()
                      or s.is_namespace())

        def walk(table):
            for child in table.get_children():
                for symbol in child.get_symbols():
                    if symbol.is_global() and symbol.get_name() not in defined \
                            and symbol.get_name() not in builtins:
                        out.append('{0}: {1} is not defined'.format(name, symbol.get_name()))
                walk(child)
        walk(top)
    return out


def rule_self_attrs(root):
    """Every self.x in a window exists: a handler or helper typed wrong dies when clicked."""
    out = []
    base = ast.parse(read(root, 'pm_chrome.py'))

    def members(tree, cls):
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == cls:
                for sub in ast.walk(node):
                    if isinstance(sub, ast.FunctionDef):
                        names.add(sub.name)
                    if isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name) \
                            and sub.value.id == 'self' and isinstance(sub.ctx, ast.Store):
                        names.add(sub.attr)
        return names

    inherited = members(base, 'ThemedWindow')
    for module in ('pm_main', 'pm_dialogs'):
        tree = ast.parse(read(root, module + '.py'))
        dialog = members(ast.parse(read(root, 'pm_dialogs.py')), 'Dialog')
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.bases:
                have = inherited | dialog | members(tree, node.name)
                if node.name == 'SpecsFor':
                    continue
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name) \
                            and sub.value.id == 'self' and sub.attr not in have:
                        out.append('{0}.{1}: self.{2}'.format(module, node.name, sub.attr))
    return out


def rule_columns_no_dynamic(root):
    """A grid column is not in the element tree, so a DynamicResource on it stays empty."""
    out = []
    for layout in LAYOUTS:
        for tag in re.findall(r'<DataGrid\w*Column\b[^>]*>', read(root, layout + '.xaml')):
            if 'DynamicResource' in tag:
                out.append(layout + ': ' + tag[:60])
    if "FindResource('StateCell')" not in read(root, 'pm_main.py'):
        out.append('nothing gives the state column its template')
    return out


def rule_writes_through_runner(root):
    out = []
    main = code_only(read(root, 'pm_main.py'))
    if re.search(r'\bTransaction\(', main) or 'apply_plan' not in main or 'runner.submit' not in main:
        out.append('main must write through the Runner')
    if 'Dispatcher.Invoke' in main or 'PushFrame' in main:
        out.append('the dispatcher is pumped during a job')
    runner = read(root, 'pm_revit.py')
    if 'ExternalEventRequest.Pending' not in runner:
        out.append('Pending would drop the job')
    return out


def rule_restores_shared_file(root):
    text = code_only(read(root, 'pm_revit.py'))
    body = re.search(r'def _external_definitions.*?(?=\ndef )', text, re.S).group(0)
    if not re.search(r'finally:\s+app\.SharedParametersFilename = original', body):
        return ["Revit's shared parameter file is not put back"]
    return []


def rule_thin_loader(root):
    text = read(root, 'script.py')
    out = []
    if '__persistentengine__ = True' not in text:
        out.append('no persistent engine')
    if 'clr.AddReference' in text or len(text.splitlines()) > 60:
        out.append('script.py is not thin')
    return out


def rule_no_owner_before_show(root):
    launch = read(root, 'pm_main.py').split('def launch(')[1]
    return ['a prompt owned by a window not shown yet throws'] if 'ask(window' in launch else []


def rule_changelog(root):
    version = re.search(r'"([\d.]+)"', read(root, 'pm_version.py')).group(1)
    return [] if '## ' + version in read(root, 'CHANGELOG.md') else ['no changelog entry']


def rule_shared_files(root):
    extension = os.path.abspath(os.path.join(root, '..', '..', '..'))
    out = []
    if os.path.basename(extension) != 'RevoBIM PY.extension':
        return out
    for folder, _dirs, files in os.walk(extension):
        for name in files:
            full = os.path.join(folder, name)
            if not os.path.abspath(full).startswith(os.path.abspath(HERE)):
                out.append(full)
    return out


def rule_loads(root):
    import bench_stubs
    out = []
    saved = dict(sys.modules)
    bench_stubs.install()
    sys.path.insert(0, root)
    try:
        for name in ['pm_version'] + MODULES:
            sys.modules.pop(name, None)
        for name in MODULES:
            try:
                importlib.import_module(name)
            except Exception as error:
                out.append('{0}: {1}'.format(name, error))
    finally:
        sys.path.remove(root)
        sys.modules.clear()
        sys.modules.update(saved)
    return out


RULES = [rule_layouts_parse, rule_clr_first, rule_assemblies, rule_banned, rule_ascii, rule_resources,
         rule_palettes, rule_names, rule_chrome, rule_windows_themed, rule_drawer, rule_no_duplicates,
         rule_globals, rule_self_attrs, rule_columns_no_dynamic, rule_writes_through_runner,
         rule_restores_shared_file, rule_thin_loader, rule_no_owner_before_show, rule_changelog,
         rule_shared_files, rule_loads]

BREAKAGES = [
    (rule_layouts_parse, 'Prompt.xaml', '<Grid x:Name="Body">', '<!-- a -- b --><Grid x:Name="Body">'),
    (rule_clr_first, 'pm_theme.py', 'import pm_clr\n', ''),
    (rule_assemblies, 'pm_clr.py', "'System.Data', 'System.Data.Common',", ''),
    (rule_banned, 'pm_core.py', 'def to_text(value):', 'def to_text(value):\n    x = f"{value}"'),
    (rule_banned, 'pm_revit.py', 'rec.handle.Id', 'rec.handle.Id.IntegerValue'),
    (rule_ascii, 'pm_core.py', "KIND_ALL = u'All'", "KIND_ALL = u'" + chr(196) + "ll'"),
    (rule_resources, 'Prompt.xaml', '{DynamicResource ToolBtn}', '{StaticResource ToolBtn}'),
    (rule_resources, 'ParaManager.xaml', '{DynamicResource GroupItems}', '{DynamicResource GroupItemz}'),
    (rule_palettes, 'pm_theme.py', "'WindowBg': '#3C4454'", "'WindowBg': '#232326'"),
    (rule_palettes, 'pm_theme.py', "'WindowBg': '#F1F1F2', ", ''),
    (rule_names, 'pm_main.py', "self.e('SaveBtn').IsEnabled = dirty", "self.e('SaveBton').IsEnabled = dirty"),
    (rule_chrome, 'Groups.xaml', '<Grid x:Name="Grips" Grid.RowSpan="3"/>', ''),
    (rule_chrome, 'pm_chrome.py', '<Button x:Name="ShrinkBtn"', '<Button x:Name="ShrinkBtnX"'),
    (rule_windows_themed, 'pm_dialogs.py', 'def tell(owner', 'def bare():\n    return Window()\n\n\ndef tell(owner'),
    (rule_drawer, 'pm_drawer.py', 'self.window.BeginAnimation(Window.TopProperty, None)', 'pass'),
    (rule_drawer, 'pm_drawer.py', 'window.MinHeight = 0.0', 'pass'),
    (rule_drawer, 'pm_drawer.py', '            except Exception:\n                finish()\n\n        try:\n            self.timer',
     '            finally:\n                pass\n\n        try:\n            self.timer'),
    (rule_no_duplicates, 'pm_main.py', '    def on_next(self', '    def on_prev(self, sender, args):\n        pass\n\n    def on_next(self'),
    (rule_globals, 'pm_dialogs.py', "def tell(owner, title, text):\n    ask(", "def tell(owner, title, text):\n    askx("),
    (rule_self_attrs, 'pm_main.py', "('SaveBtn', self.on_save)", "('SaveBtn', self.on_saved)"),
    (rule_columns_no_dynamic, 'ParaManager.xaml', '<DataGridTemplateColumn Header="Group Under"', '<DataGridTemplateColumn CellTemplate="{DynamicResource StateCell}" Header="Group Under"'),
    (rule_columns_no_dynamic, 'pm_main.py', "self.win.FindResource('StateCell')", 'None'),
    (rule_writes_through_runner, 'pm_main.py', 'if not self.runner.submit(job, self.after_apply):', 'if not pm_revit.apply_plan(doc, plan, data):'),
    (rule_writes_through_runner, 'pm_main.py', "        self.e('ProgText').Text = u'Completed {0}%'.format(percent)\n", "        self.win.Dispatcher.Invoke(Action(lambda: None))\n"),
    (rule_writes_through_runner, 'pm_revit.py', '(ExternalEventRequest.Accepted, ExternalEventRequest.Pending)', '(ExternalEventRequest.Accepted,)'),
    (rule_restores_shared_file, 'pm_revit.py', "        app.SharedParametersFilename = original or u''\n", '        pass\n'),
    (rule_thin_loader, 'script.py', '__persistentengine__ = True', ''),
    (rule_no_owner_before_show, 'pm_main.py', '    window.win.Show()\n', "    ask(window, u'a', u'b')\n    window.win.Show()\n"),
    (rule_changelog, 'pm_version.py', '1.0.0', '9.9.9'),
    (rule_loads, 'pm_core.py', 'import codecs', 'import codecs\nraise ValueError("boom")'),
]


def run():
    bad = 0
    for rule in RULES:
        problems = rule(HERE)
        print('{0:32} {1}'.format(rule.__name__, 'ok' if not problems else 'FAIL'))
        for problem in problems[:12]:
            print('    ' + str(problem))
        bad += len(problems)
    return bad


def selftest():
    missed = 0
    for rule, name, old, new in BREAKAGES:
        folder = tempfile.mkdtemp()
        root = os.path.join(folder, 'x')
        shutil.copytree(HERE, root, ignore=shutil.ignore_patterns('__pycache__'))
        path = os.path.join(root, name)
        with open(path, encoding='utf-8', newline='') as src:
            text = src.read()
        if old not in text:
            print('ANCHOR MISSING {0} {1!r}'.format(rule.__name__, old[:40]))
            missed += 1
            continue
        with open(path, 'w', encoding='utf-8', newline='') as out:
            out.write(text.replace(old, new, 1))
        try:
            caught = rule(root)
        except Exception as error:
            caught = [str(error)]
        if not caught:
            print('NOT CAUGHT {0} {1!r}'.format(rule.__name__, old[:40]))
            missed += 1
        shutil.rmtree(folder)
    print('{0} breakages, {1} missed'.format(len(BREAKAGES), missed))
    return missed


if __name__ == '__main__':
    sys.path.insert(0, HERE)
    sys.exit(1 if (selftest() if '--selftest' in sys.argv else run()) else 0)
