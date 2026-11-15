# -*- coding: utf-8 -*-
"""Static bench. Every rule is proved by `--selftest`, which breaks the tool on
purpose in a temp copy and fails if the rule does not fire. A breakage whose
anchor text is missing fails the selftest too."""
import ast
import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.dom.minidom

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
BENCH = ('bench_stubs.py', 'bench_logic.py', 'import_check.py', 'make_icon.py')
LAYOUTS = ('FamilyParamPush.xaml', 'Prompt.xaml')
ASSEMBLY_FOR = {
    'System': ('mscorlib', 'System'), 'System.IO': ('mscorlib',),
    'System.Collections.Generic': ('mscorlib', 'System.Collections'),
    'System.Data': ('System.Data', 'System.Data.Common'),
    'System.Windows': ('PresentationFramework', 'WindowsBase'),
    'System.Windows.Controls': ('PresentationFramework',),
    'System.Windows.Controls.Primitives': ('PresentationFramework',),
    'System.Windows.Data': ('PresentationFramework',),
    'System.Windows.Input': ('PresentationCore', 'WindowsBase'),
    'System.Windows.Interop': ('PresentationFramework', 'WindowsBase'),
    'System.Windows.Markup': ('PresentationFramework', 'System.Xaml'),
    'System.Windows.Media': ('PresentationCore',),
    'System.Windows.Media.Imaging': ('PresentationCore',),
    'System.Windows.Threading': ('WindowsBase',),
    'System.Windows.Forms': ('System.Windows.Forms',),
}
# Where the real API puts each name. Kept apart from bench_stubs on purpose: a
# stub only proves what it was told, so it cannot catch a name it misfiled.
API_HOME = {
    'System': 'Action Array Object TimeSpan Double AppDomain Guid',
    'System.IO': 'File FileAccess FileMode FileStream MemoryStream',
    'System.Collections.Generic': 'List',
    'System.Data': 'DataTable',
    'System.Windows': 'Clipboard PresentationSource RoutedEventHandler '
                      'SizeToContent SystemParameters VerticalAlignment '
                      'Visibility WindowStartupLocation',
    'System.Windows.Controls': 'Button DataGridLength DataGridLengthUnitType '
                               'DataGridTemplateColumn DataGridTextColumn '
                               'TextBlock',
    'System.Windows.Controls.Primitives': 'ButtonBase',
    'System.Windows.Data': 'Binding',
    'System.Windows.Forms': 'Screen',
    'System.Windows.Input': 'Key Keyboard ModifierKeys',
    'System.Windows.Interop': 'WindowInteropHelper',
    'System.Windows.Markup': 'XamlReader',
    'System.Windows.Media': 'ColorConverter SolidColorBrush',
    'System.Windows.Media.Imaging': 'BitmapCacheOption BitmapImage',
    'System.Windows.Threading': 'DispatcherPriority DispatcherTimer',
    'Autodesk.Revit.DB': 'ElementId Element FilteredElementCollector '
                         'IFailuresPreprocessor SubTransaction Transaction '
                         'TransactionGroup WorksharingUtils '
                         'FailureProcessingResult FamilySource '
                         'IFamilyLoadOptions',
    'Autodesk.Revit.UI': 'ExternalEvent IExternalEventHandler TaskDialog',
}
RULES = []


def rule(fn):
    RULES.append(fn)
    return fn


def read(name):
    with open(os.path.join(HERE, name), encoding='utf-8') as handle:
        return handle.read()


def tool_modules():
    return sorted([os.path.basename(p) for p in glob.glob(
        os.path.join(HERE, '*.py')) if os.path.basename(p) not in BENCH])


def trees():
    return [(name, ast.parse(read(name))) for name in tool_modules()]


def names_in_layouts():
    out = {}
    for layout in LAYOUTS:
        out[layout] = set(re.findall(r'x:Name="([^"]+)"', read(layout)))
    return out


def theme_keys():
    text = read('Theme.xaml')
    return set(re.findall(r'x:Key="([^"]+)"', text))


def palette_brushes():
    import bench_stubs
    bench_stubs.install()
    import fpp_theme
    return fpp_theme, set([k + 'Brush' for k in fpp_theme.REVIT_DARK])


@rule
def xaml_parses():
    for path in glob.glob(os.path.join(HERE, '*.xaml')):
        xml.dom.minidom.parse(path)


@rule
def no_static_resource_in_layouts():
    for layout in LAYOUTS:
        assert 'StaticResource' not in read(layout), layout


@rule
def dynamic_keys_exist():
    _, brushes = palette_brushes()
    known = brushes | theme_keys()
    for name in LAYOUTS + ('Theme.xaml',):
        for key in re.findall(r'DynamicResource (\w+)', read(name)):
            assert key in known, '{0}: {1}'.format(name, key)
    for key in re.findall(r"'(\w+Brush)'", read('fpp_main.py')):
        assert key in known, key
    for key in re.findall(r"'(\w+Btn)'", read('fpp_dialogs.py')):
        assert key in known, key


@rule
def literal_brace_free():
    for layout in LAYOUTS:
        for value in re.findall(r'(?:Tag|Text|Content)="(\{[^}]*\}[^"]*)"',
                                read(layout)):
            assert value.startswith(('{Binding', '{}', '{TemplateBinding')), value


@rule
def every_find_has_a_name():
    layouts = names_in_layouts()
    both = layouts['FamilyParamPush.xaml'] & layouts['Prompt.xaml']
    for name in re.findall(r"find\('(\w+)'\)", read('fpp_chrome.py')):
        if name.startswith('grip_') or name in ('btn_full', 'grip_layer'):
            assert name in layouts['FamilyParamPush.xaml'], name
        else:
            assert name in both, name
    for grip in ('n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw'):
        assert 'grip_' + grip in layouts['FamilyParamPush.xaml'], grip
    for module in ('fpp_main.py', 'fpp_replace.py'):
        block = re.search(r"for name in \((.*?)\):\s+setattr", read(module),
                          re.S).group(1)
        for name in re.findall(r"'(\w+)'", block):
            assert name in layouts['FamilyParamPush.xaml'], name
    for name in re.findall(r"find\('(\w+)'\)", read('fpp_dialogs.py')):
        assert name in layouts['Prompt.xaml'], name
    for name in ('tab_strip', 'body_grid', 'body_replace', 'footer_bar'):
        assert name in layouts['FamilyParamPush.xaml']
    for name in ('body_panel', 'footer_bar'):
        assert name in layouts['Prompt.xaml']


@rule
def clr_module_is_first():
    for name, tree in trees():
        if name in ('fpp_clr.py', 'script.py'):
            continue
        reaches = [n for n in tree.body if isinstance(n, ast.ImportFrom)
                   and (n.module or '').split('.')[0] in ('System', 'Autodesk')]
        if not reaches:
            continue
        first = [n for n in tree.body if isinstance(n, (ast.Import,
                                                        ast.ImportFrom))][0]
        assert isinstance(first, ast.Import) \
            and first.names[0].name == 'fpp_clr', name


@rule
def assemblies_referenced():
    tree = ast.parse(read('fpp_clr.py'))
    listed = None
    for node in tree.body:
        if isinstance(node, ast.Assign) \
                and node.targets[0].id == '_ASSEMBLIES':
            listed = [e.value for e in node.value.elts]
    for name, module in trees():
        for node in ast.walk(module):
            if isinstance(node, ast.ImportFrom) and (
                    node.module or '').startswith('System'):
                want = ASSEMBLY_FOR.get(node.module)
                assert want, 'no assembly table entry: ' + node.module
                assert set(want) & set(listed), node.module


@rule
def names_come_from_their_real_namespace():
    home = {}
    for space, names in API_HOME.items():
        for name in names.split():
            home[name] = space
    for name, tree in trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) \
                    and (node.module or '').split('.')[0] in ('System',
                                                              'Autodesk'):
                for alias in node.names:
                    assert alias.name in home, \
                        '{0}: {1} not in API_HOME'.format(name, alias.name)
                    assert home[alias.name] == node.module, '{0}: {1} is in ' \
                        '{2}'.format(name, alias.name, home[alias.name])


@rule
def script_is_thin():
    text = read('script.py')
    assert '__persistentengine__ = True' in text
    assert 'clr.AddReference' not in text
    tree = ast.parse(text)
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            raise AssertionError('script.py must not import names at the top')


@rule
def banned_code():
    for name in tool_modules():
        text = read(name)
        tree = ast.parse(text)
        for node in ast.walk(tree):
            assert not isinstance(node, ast.JoinedStr), name + ': f-string'
            if isinstance(node, ast.Call) and getattr(node.func, 'id', '') \
                    == 'print':
                raise AssertionError(name + ': print')
            if isinstance(node, ast.Attribute):
                assert node.attr != 'IntegerValue', name
                assert node.attr not in ('BeginAnimation', 'UriSource'), name
                assert not re.match(r'\w+Property$', node.attr) or not (
                    isinstance(node.value, ast.Attribute)
                    or (isinstance(node.value, ast.Name)
                        and node.value.id[0].islower())), \
                    name + ': dependency property through an instance'
        assert 'Storyboard' not in text, name
        assert not re.search(r'\bUri\b', text.replace('UriSource', '')), name
        assert 'clr.AddReference' not in text or name == 'fpp_clr.py', name


@rule
def ascii_only():
    for path in glob.glob(os.path.join(HERE, '*.py')):
        with open(path, 'rb') as handle:
            handle.read().decode('ascii')


@rule
def nothing_defined_twice():
    for name, tree in trees():
        scopes = [tree] + [n for n in ast.walk(tree)
                           if isinstance(n, ast.ClassDef)]
        for scope in scopes:
            seen = set()
            for node in scope.body:
                if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                    assert node.name not in seen, name + ': ' + node.name
                    seen.add(node.name)


@rule
def no_python_attrs_on_wpf():
    for name, tree in trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Attribute) \
                            and isinstance(target.value, ast.Attribute) \
                            and target.value.attr == 'window' \
                            and target.attr[0].islower():
                        raise AssertionError(name + ': ' + target.attr)


@rule
def globals_all_exist():
    import builtins
    import symtable
    extra = {'__file__', '__revit__'}
    for name in tool_modules():
        top = symtable.symtable(read(name), name, 'exec')
        bound = set(s.get_name() for s in top.get_symbols()
                    if s.is_assigned() or s.is_imported()
                    or s.is_namespace())
        def walk(table):
            for child in table.get_children():
                for symbol in child.get_symbols():
                    if symbol.is_global() and not symbol.is_assigned():
                        got = symbol.get_name()
                        assert got in bound or hasattr(builtins, got) \
                            or got in extra or got in ('unicode', 'basestring'), \
                            '{0}: {1}'.format(name, got)
                walk(child)
        walk(top)


@rule
def every_window_has_a_drawer_and_shrink():
    chrome = read('fpp_chrome.py')
    assert 'self.drawer = Drawer(' in chrome
    assert "button.Click += self.safe(self.on_shrink)" in chrome
    for layout in LAYOUTS:
        text = read(layout)
        for name in ('header_bar', 'shrink_btn', 'shrink_glyph', 'expand_glyph',
                     'root_grid', 'btn_theme', 'txt_version', 'btn_close'):
            assert 'x:Name="{0}"'.format(name) in text, layout + name
        match = re.search(r'x:Name="expand_glyph".*?/>', text, re.S).group(0)
        assert 'Collapsed' in match and 'GreenBrush' in match, layout
    for name, tree in trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and name in ('fpp_main.py',
                                                           'fpp_dialogs.py'):
                if node.name in ('FamilyParamPush', 'Prompt'):
                    bases = [getattr(b, 'id', '') for b in node.bases]
                    assert 'ThemedWindow' in bases, node.name


@rule
def palettes_match_and_read():
    module, _ = palette_brushes()
    assert sorted(module.LIGHT) == sorted(module.REVIT_DARK)
    revit = {'WindowBg': '#3C4454', 'FieldBg': '#2D3441', 'SelectBg': '#3A7392',
             'HeadBg': '#323C48'}
    for key, value in revit.items():
        assert module.REVIT_DARK[key] == value, key
    def lum(value):
        parts = [int(value[i:i + 2], 16) / 255.0 for i in (1, 3, 5)]
        parts = [p / 12.92 if p <= 0.03928 else ((p + 0.055) / 1.055) ** 2.4
                 for p in parts]
        return 0.2126 * parts[0] + 0.7152 * parts[1] + 0.0722 * parts[2]
    def ratio(a, b):
        high, low = sorted([lum(a), lum(b)], reverse=True)
        return (high + 0.05) / (low + 0.05)
    for pal in (module.REVIT_DARK, module.LIGHT):
        for back in ('WindowBg', 'PanelBg', 'FieldBg', 'TitleBg', 'HeadBg'):
            for fore in ('Text', 'Muted'):
                assert ratio(pal[fore], pal[back]) >= 4.0, (fore, back)


@rule
def version_is_logged_and_shown():
    tree = ast.parse(read('fpp_version.py'))
    version = tree.body[-1].value.value
    assert '## ' + version in read('CHANGELOG.md'), version
    assert "txt_version').Text" in read('fpp_chrome.py')


@rule
def ships_no_shared_files():
    parent = os.path.dirname(HERE)
    if os.path.basename(parent).endswith('.pulldown'):
        extra = [n for n in os.listdir(parent) if n == 'bundle.yaml']
        assert not extra, 'pulldown bundle.yaml would overwrite Routines'
    for name in ('startup.py', 'hooks', '__init__.py'):
        assert not os.path.exists(os.path.join(HERE, name)), name


@rule
def button_title_is_one_line():
    assert re.search(r'^title: Family Param Push$', read('bundle.yaml'), re.M)
    assert os.path.exists(os.path.join(HERE, 'icon.png'))


@rule
def writes_only_inside_the_runner():
    words = ('Transaction(', 'run_push(', 'run_replace(', 'discover_params(',
             'read_family_params(', 'read_shared(', 'read_model(')
    for module in ('fpp_main.py', 'fpp_replace.py'):
        main = read(module)
        for word in words:
            for match in re.finditer(re.escape(word), main):
                before = main[:match.start()]
                assert before.rfind('def work(') > before.rfind('\n    def '), word


@rule
def values_are_read_before_the_family_changes():
    tree = ast.parse(read('fpp_family.py'))
    body = [n for n in tree.body if isinstance(n, ast.FunctionDef)
            and n.name == 'replace_family'][0]
    text = ast.get_source_segment(read('fpp_family.py'), body)
    order = [text.index(word) for word in (
        'capture(doc', 'write_backup(', 'checkout(doc', 'doc.EditFamily(',
        'swap_parameters(', 'load_family(', 'restore(doc', 'prove(doc')]
    assert order == sorted(order), order


@rule
def event_status_is_checked():
    text = read('fpp_app.py')
    assert "status = str(self.event.Raise())" in text
    assert 'Thread.Sleep' not in text and '.Join(' not in text


@rule
def armed_after_build_before_show():
    text = read('fpp_app.py')
    note = text.index('fpp_core.write_text(fpp_core.note_path(), __version__)')
    arm = text.index('tool.armed = True')
    show = text.index('tool.window.Show()')
    build = text.index('tool = FamilyParamPush(')
    assert build < note < arm < show


@rule
def modules_load_against_stubs():
    import bench_stubs
    bench_stubs.install()
    for name in tool_modules():
        if name == 'script.py':
            continue
        __import__(name[:-3])


BREAKAGES = [
    ('FamilyParamPush.xaml', 'Title="Family Param Push"', '<!-- a -- b --> Title="x"', 'xaml_parses'),
    ('FamilyParamPush.xaml', 'Style="{DynamicResource GhostBtn}" Padding="9,3"', 'Style="{StaticResource GhostBtn}" Padding="9,3"', 'no_static_resource_in_layouts'),
    ('FamilyParamPush.xaml', '{DynamicResource WindowBgBrush}', '{DynamicResource NopeBrush}', 'dynamic_keys_exist'),
    ('FamilyParamPush.xaml', 'Tag="Search families and types"', 'Tag="{Project}\\x"', 'literal_brace_free'),
    ('FamilyParamPush.xaml', 'x:Name="txt_status"', 'x:Name="txt_state"', 'every_find_has_a_name'),
    ('FamilyParamPush.xaml', 'x:Name="grid_rmaps"', 'x:Name="grid_rmap"', 'every_find_has_a_name'),
    ('FamilyParamPush.xaml', 'x:Name="grip_se"', 'x:Name="grip_xx"', 'every_find_has_a_name'),
    ('fpp_main.py', 'import fpp_clr  # noqa: F401  (must stay first)\n', '', 'clr_module_is_first'),
    ('fpp_clr.py', "'System.Data', 'System.Data.Common',", '', 'assemblies_referenced'),
    ('fpp_chrome.py', 'from System.Windows.Media import ColorConverter, SolidColorBrush', 'from System.Windows.Media import ColorConverter, PresentationSource, SolidColorBrush', 'names_come_from_their_real_namespace'),
    ('fpp_main.py', 'from System.Windows.Data import Binding', 'from System.Windows.Data import Binding, MultiBinding', 'names_come_from_their_real_namespace'),
    ('script.py', '__persistentengine__ = True', '', 'script_is_thin'),
    ('fpp_core.py', 'def to_text(value):\n', 'def to_text(value):\n    x = f"{value}"\n', 'banned_code'),
    ('fpp_core.py', 'def to_text(value):\n', 'def to_text(value):\n    print("x")\n', 'banned_code'),
    ('fpp_revit.py', "getattr(element_id, 'Integer' + 'Value')", 'element_id.IntegerValue', 'banned_code'),
    ('fpp_chrome.py', 'self.window.DragMove()', 'self.window.BeginAnimation(1, None)', 'banned_code'),
    ('fpp_main.py', 'TextBlock.ForegroundProperty', 'self.txt_status.ForegroundProperty', 'banned_code'),
    ('fpp_chrome.py', 'from fpp_drawer import Drawer', 'from fpp_drawer import Drawer\nimport clr\nclr.AddReference("x")', 'banned_code'),
    ('fpp_core.py', '# ===================== settings and log', '# ' + chr(0x2192) + ' settings and log', 'ascii_only'),
    ('fpp_core.py', 'def lerp(a, b, p):', 'def ease_out(p):\n    return p\n\n\ndef lerp(a, b, p):', 'nothing_defined_twice'),
    ('fpp_chrome.py', 'self.full = False\n        self.full_saved', 'self.window.full_flag = False\n        self.full = False\n        self.full_saved', 'no_python_attrs_on_wpf'),
    ('fpp_core.py', 'def ease_out(p):\n    p = max', 'def ease_out(p):\n    missing_helper(p)\n    p = max', 'globals_all_exist'),
    ('Prompt.xaml', 'x:Name="shrink_btn"', 'x:Name="shrink_button"', 'every_window_has_a_drawer_and_shrink'),
    ('fpp_dialogs.py', 'class Prompt(ThemedWindow):', 'class Prompt(object):', 'every_window_has_a_drawer_and_shrink'),
    ('fpp_chrome.py', "button.Click += self.safe(self.on_shrink)", "pass", 'every_window_has_a_drawer_and_shrink'),
    ('fpp_theme.py', "'WindowBg': '#3C4454'", "'WindowBg': '#232326'", 'palettes_match_and_read'),
    ('fpp_theme.py', "'Muted': '#B4BAC2'", "'Muted': '#6A7078'", 'palettes_match_and_read'),
    ('fpp_theme.py', "'WindowBg': '#F3F4F6', ", "", 'palettes_match_and_read'),
    ('CHANGELOG.md', '## 1.2.0', '## 0.0.0', 'version_is_logged_and_shown'),
    ('bundle.yaml', 'title: Family Param Push', 'title: Family Param\\nPush', 'button_title_is_one_line'),
    ('fpp_main.py', 'def work(uiapp):\n            return fpp_revit.read_model', 'def task(uiapp):\n            return fpp_revit.read_model', 'writes_only_inside_the_runner'),
    ('fpp_app.py', 'status = str(self.event.Raise())', 'self.event.Raise()\n        status = "Accepted"', 'event_status_is_checked'),
    ('fpp_app.py', 'tool.armed = True                  # after the build, just before Show\n    tool.window.Show()', 'tool.window.Show()\n    tool.armed = True', 'armed_after_build_before_show'),
    ('fpp_chrome.py', 'from System.Data import DataTable', 'from System.Windows import DataTable', 'modules_load_against_stubs'),
    ('fpp_family.py', "writes, lines = capture(doc, pick, rep)\n    path = write_backup(name, lines)\n    if path:\n        rep['backups'].append(path)\n", "writes, lines = [], []\n", 'values_are_read_before_the_family_changes'),
]
FILE_BREAKS = [('startup.py', 'ships_no_shared_files')]


def run_rules(only=None):
    failed = []
    for fn in RULES:
        if only and fn.__name__ != only:
            continue
        try:
            fn()
        except Exception as err:
            failed.append(fn.__name__)
            print('FAIL {0}: {1!r}'.format(fn.__name__, err))
    return failed


def selftest():
    missed = []
    jobs = BREAKAGES + [(f, None, None, r) for f, r in FILE_BREAKS]
    for file_name, old, new, name in jobs:
        folder = tempfile.mkdtemp()
        copy = os.path.join(folder, 'tool')
        shutil.copytree(HERE, copy, ignore=shutil.ignore_patterns('__pycache__'))
        path = os.path.join(copy, file_name)
        if old is None:
            open(path, 'w').close()
        else:
            with open(path, encoding='utf-8') as handle:
                text = handle.read()
            if old not in text:
                missed.append('ANCHOR MISSING: ' + old[:60])
                continue
            with open(path, 'w', encoding='utf-8') as handle:
                handle.write(text.replace(old, new, 1))
        code = subprocess.call(
            [sys.executable, '-B', os.path.join(copy, 'import_check.py'),
             '--rule', name], stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)
        shutil.rmtree(folder)
        if code == 0:
            missed.append('NOT CAUGHT by {0}: {1}'.format(name, str(old)[:50]))
    covered = set([j[3] for j in jobs])
    for fn in RULES:
        if fn.__name__ not in covered:
            missed.append('NO BREAKAGE FOR RULE ' + fn.__name__)
    for line in missed:
        print(line)
    print('{0} rules, {1} breakages, {2} missed'.format(len(RULES), len(jobs),
                                                        len(missed)))
    return 1 if missed else 0


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(selftest())
    only = sys.argv[sys.argv.index('--rule') + 1] if '--rule' in sys.argv else None
    bad = run_rules(only)
    if not only:
        print('{0} rules, {1} failed'.format(len(RULES), len(bad)))
    sys.exit(1 if bad else 0)
