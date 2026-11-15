# -*- coding: utf-8 -*-
"""Bulk Rename static rules. --selftest breaks each rule to prove it fires."""
import ast
import builtins
import importlib
import os
import re
import shutil
import sys
import tempfile
import xml.dom.minidom as minidom

HERE = os.path.dirname(os.path.abspath(__file__))
LAYOUTS = ('BulkRename.xaml', 'Prompt.xaml', 'Settings.xaml')
RULES = []

ASSEMBLY_FOR = {
    'System': ('mscorlib', 'System', 'System.Runtime'),
    'System.Collections.Generic': ('mscorlib', 'System.Collections'),
    'System.IO': ('mscorlib', 'System.IO.FileSystem', 'System.Runtime.Extensions'),
    'System.Windows': ('PresentationFramework', 'PresentationCore', 'WindowsBase'),
    'System.Windows.Controls': ('PresentationFramework',),
    'System.Windows.Documents': ('PresentationFramework',),
    'System.Windows.Forms': ('System.Windows.Forms',),
    'System.Windows.Input': ('PresentationCore', 'WindowsBase'),
    'System.Windows.Interop': ('PresentationFramework',),
    'System.Windows.Markup': ('PresentationFramework',),
    'System.Windows.Media': ('PresentationCore',),
    'System.Windows.Media.Imaging': ('PresentationCore',),
    'System.Windows.Threading': ('WindowsBase',),
    'System.Xml': ('System.Xml', 'System.Xml.ReaderWriter'),
}

# every .NET name the tool imports and its real namespace, written from the API
# rather than from the stub, so one wrong guess cannot pass twice
REAL_HOME = {
    'Action': 'System', 'AppDomain': 'System', 'Double': 'System', 'TimeSpan': 'System',
    'List': 'System.Collections.Generic',
    'File': 'System.IO', 'MemoryStream': 'System.IO', 'StringReader': 'System.IO',
    'FontWeights': 'System.Windows', 'FrameworkElement': 'System.Windows',
    'GridLength': 'System.Windows', 'GridUnitType': 'System.Windows',
    'PresentationSource': 'System.Windows', 'Size': 'System.Windows',
    'SizeToContent': 'System.Windows',
    'SystemParameters': 'System.Windows', 'TextTrimming': 'System.Windows',
    'TextWrapping': 'System.Windows', 'Thickness': 'System.Windows',
    'VerticalAlignment': 'System.Windows', 'Visibility': 'System.Windows',
    'WindowStartupLocation': 'System.Windows',
    'Border': 'System.Windows.Controls', 'ColumnDefinition': 'System.Windows.Controls',
    'Grid': 'System.Windows.Controls', 'TextBlock': 'System.Windows.Controls',
    'Run': 'System.Windows.Documents', 'TextElement': 'System.Windows.Documents',
    'Screen': 'System.Windows.Forms',
    'Key': 'System.Windows.Input', 'Keyboard': 'System.Windows.Input',
    'ModifierKeys': 'System.Windows.Input',
    'WindowInteropHelper': 'System.Windows.Interop',
    'XamlReader': 'System.Windows.Markup',
    'ColorConverter': 'System.Windows.Media', 'SolidColorBrush': 'System.Windows.Media',
    'BitmapCacheOption': 'System.Windows.Media.Imaging',
    'BitmapImage': 'System.Windows.Media.Imaging',
    'DispatcherTimer': 'System.Windows.Threading', 'XmlReader': 'System.Xml',
    'BuiltInParameter': 'Autodesk.Revit.DB', 'CADLinkType': 'Autodesk.Revit.DB',
    'Element': 'Autodesk.Revit.DB', 'ElementId': 'Autodesk.Revit.DB',
    'ElementType': 'Autodesk.Revit.DB', 'Family': 'Autodesk.Revit.DB',
    'FilteredElementCollector': 'Autodesk.Revit.DB',
    'IFailuresPreprocessor': 'Autodesk.Revit.DB',
    'FailureProcessingResult': 'Autodesk.Revit.DB', 'RevitLinkType': 'Autodesk.Revit.DB',
    'SubTransaction': 'Autodesk.Revit.DB', 'Transaction': 'Autodesk.Revit.DB',
    'TransactionGroup': 'Autodesk.Revit.DB',
    'View': 'Autodesk.Revit.DB', 'ViewSheet': 'Autodesk.Revit.DB',
    'WorksharingUtils': 'Autodesk.Revit.DB',
    'ExternalEvent': 'Autodesk.Revit.UI', 'IExternalEventHandler': 'Autodesk.Revit.UI',
    'TaskDialog': 'Autodesk.Revit.UI',
}

# what each element may carry; an XML parse cannot see an unknown member
FW = {'Margin', 'Width', 'Height', 'MinWidth', 'MinHeight', 'MaxHeight', 'MaxWidth',
      'HorizontalAlignment', 'VerticalAlignment', 'Visibility', 'ToolTip', 'Style',
      'Cursor', 'IsHitTestVisible', 'Opacity', 'Tag', 'Grid.Row', 'Grid.Column',
      'Grid.RowSpan', 'Grid.ColumnSpan', 'Background', 'Foreground', 'x:Name', 'IsEnabled'}
KNOWN = {
    'Window': FW | {'Title', 'WindowStyle', 'AllowsTransparency', 'ResizeMode',
                    'ShowInTaskbar', 'FontFamily', 'FontSize', 'SizeToContent',
                    'WindowStartupLocation', 'xmlns', 'xmlns:x'},
    'Border': FW | {'BorderBrush', 'BorderThickness', 'CornerRadius', 'Padding'},
    'Grid': FW, 'StackPanel': FW | {'Orientation'},
    'TextBlock': FW | {'Text', 'FontSize', 'FontWeight', 'TextWrapping', 'TextTrimming'},
    'TextBox': FW, 'CheckBox': FW | {'Content'}, 'Image': FW, 'Thumb': FW,
    'Button': FW | {'IsDefault', 'BorderBrush'}, 'ComboBox': FW,
    'RadioButton': FW | {'GroupName', 'IsChecked'},
    'Path': FW | {'Data', 'Stroke', 'StrokeThickness'},
    'ScrollViewer': FW | {'VerticalScrollBarVisibility', 'HorizontalScrollBarVisibility'},
    'ColumnDefinition': {'Width'}, 'RowDefinition': {'Height'},
}


def rule(fn):
    RULES.append(fn)
    return fn


def read(folder, name):
    with open(os.path.join(folder, name), 'r') as handle:
        return handle.read()


def modules(folder):
    return sorted(f for f in os.listdir(folder)
                  if f.endswith('.py') and f.startswith(('brn_', 'script')))


def strip_comments(text):
    return re.sub(r'<!--.*?-->', '', text, flags=re.S)


@rule
def xaml_parses(folder):
    out = []
    for name in LAYOUTS + ('Theme.xaml',):
        try:
            minidom.parseString(read(folder, name))
        except Exception as error:
            out.append('{0}: {1}'.format(name, error))
    return out


@rule
def no_static_resource_in_layout(folder):
    return [n for n in LAYOUTS if 'StaticResource' in strip_comments(read(folder, n))]


@rule
def resource_keys_exist(folder):
    theme = strip_comments(read(folder, 'Theme.xaml'))
    keys = set(re.findall(r'x:Key="(\w+)"', theme))
    out = []
    for name in LAYOUTS + ('Theme.xaml',):
        for key in re.findall(r'(?:Dynamic|Static)Resource (\w+)', strip_comments(read(folder, name))):
            if key not in keys:
                out.append('{0}: {1}'.format(name, key))
    for name in modules(folder):
        for key in re.findall(r"SetResourceReference\([^,]+,\s*'(\w+)'", read(folder, name)):
            if key not in keys:
                out.append('{0}: {1}'.format(name, key))
    return out


@rule
def keyed_styles_match_element(folder):
    theme = minidom.parseString(read(folder, 'Theme.xaml'))
    targets = {}
    for style in theme.getElementsByTagName('Style'):
        if style.getAttribute('x:Key'):
            targets[style.getAttribute('x:Key')] = style.getAttribute('TargetType')
    out = []
    for name in LAYOUTS:
        for el in minidom.parseString(read(folder, name)).getElementsByTagName('*'):
            found = re.match(r'\{DynamicResource (\w+)\}', el.getAttribute('Style'))
            if found and targets.get(found.group(1)) != el.tagName:
                out.append('{0}: {1} on {2}'.format(name, found.group(1), el.tagName))
    return out


@rule
def members_known(folder):
    out = []
    for name in LAYOUTS:
        for el in minidom.parseString(read(folder, name)).getElementsByTagName('*'):
            tag = el.tagName
            if '.' in tag:
                continue
            if tag not in KNOWN:
                out.append('{0}: element {1}'.format(name, tag))
                continue
            for attr in el.attributes.keys():
                if attr not in KNOWN[tag]:
                    out.append('{0}: {1}.{2}'.format(name, tag, attr))
    return out


@rule
def looked_up_names_exist(folder):
    names = set()
    for name in LAYOUTS:
        names |= set(re.findall(r'x:Name="(\w+)"', read(folder, name)))
    out = []
    for name in modules(folder):
        text = read(folder, name)
        for key in re.findall(r"(?:find|FindName)\('(\w+)'\)", text):
            if key not in names:
                out.append('{0}: {1}'.format(name, key))
    for key in re.findall(r"'(Grip\w+)':", read(folder, 'brn_chrome.py')):
        if key not in names:
            out.append(key)
    return out


@rule
def banned_code(folder):
    out = []
    for name in modules(folder):
        text = read(folder, name)
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr):
                out.append(name + ': f-string')
            if isinstance(node, ast.Call) and getattr(node.func, 'id', '') == 'print':
                out.append(name + ': print')
            if isinstance(node, ast.ImportFrom) and node.module == 'System':
                if 'Uri' in [a.name for a in node.names]:
                    out.append(name + ': System.Uri')
            if isinstance(node, ast.Attribute) and node.attr == 'IntegerValue':
                inside = re.search(r'def eid_value.*?return 0\n', text, re.S)
                if not inside or text.count('.IntegerValue') > 1:
                    out.append(name + ': bare IntegerValue')
        if 'Storyboard' in text:
            out.append(name + ': Storyboard')
    return sorted(set(out))


@rule
def ascii_only(folder):
    out = []
    for name in modules(folder) + list(LAYOUTS) + ['Theme.xaml']:
        with open(os.path.join(folder, name), 'rb') as handle:
            if any(b > 127 for b in handle.read()):
                out.append(name)
    return out


@rule
def clr_imported_first(folder):
    out = []
    for name in modules(folder):
        if name in ('script.py', 'brn_clr.py'):
            continue
        clr_line = None
        for node in ast.parse(read(folder, name)).body:
            if isinstance(node, ast.Import) and node.names[0].name == 'brn_clr':
                clr_line = node.lineno
            module = getattr(node, 'module', None) if isinstance(node, ast.ImportFrom) else None
            if module and module.split('.')[0] in ('System', 'Autodesk'):
                if clr_line is None:
                    out.append(name + ': ' + module)
    return out


@rule
def assemblies_referenced(folder):
    tree = ast.parse(read(folder, 'brn_clr.py'))
    listed = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            listed = [e.value for e in node.value.elts]
    out = []
    for name in modules(folder):
        for node in ast.walk(ast.parse(read(folder, name))):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith('System'):
                need = ASSEMBLY_FOR.get(node.module)
                if need is None or not set(need) & set(listed):
                    out.append('{0}: {1}'.format(name, node.module))
    if 'RevitAPI' in listed or 'RevitAPIUI' in listed:
        out.append('RevitAPI must not be referenced')
    return out


@rule
def imports_in_real_namespace(folder):
    out = []
    for name in modules(folder):
        for node in ast.walk(ast.parse(read(folder, name))):
            if isinstance(node, ast.ImportFrom) and node.module and \
                    node.module.split('.')[0] in ('System', 'Autodesk'):
                for alias in node.names:
                    if REAL_HOME.get(alias.name) != node.module:
                        out.append('{0}: {1}.{2}'.format(name, node.module, alias.name))
    return out


@rule
def nothing_defined_twice(folder):
    out = []
    for name in modules(folder):
        tree = ast.parse(read(folder, name))
        for scope in [tree] + [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
            seen = set()
            for node in scope.body:
                if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                    if node.name in seen:
                        out.append('{0}: {1}'.format(name, node.name))
                    seen.add(node.name)
    return out


@rule
def globals_exist(folder):
    out = []
    for name in modules(folder):
        tree = ast.parse(read(folder, name))
        known = set(dir(builtins)) | {'__file__', '__revit__'}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                known.add(node.name)
            if isinstance(node, ast.FunctionDef):
                known |= {a.arg for a in node.args.args}
            if isinstance(node, ast.Lambda):
                known |= {a.arg for a in node.args.args}
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                known |= {(a.asname or a.name).split('.')[0] for a in node.names}
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                known.add(node.id)
            if isinstance(node, ast.ExceptHandler) and node.name:
                known.add(node.name)
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id not in known:
                out.append('{0}: {1}'.format(name, node.id))
    return out


@rule
def cross_module_names_exist(folder):
    out = []
    tables = {}
    for mod in ('brn_core', 'brn_revit', 'brn_main', 'brn_dialogs', 'brn_theme'):
        tree = ast.parse(read(folder, mod + '.py'))
        names = set()
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, ast.Assign):
                names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                names |= {a.asname or a.name for a in node.names}
        tables[mod] = names
    tables['core'] = tables['brn_core']
    for name in modules(folder):
        for node in ast.walk(ast.parse(read(folder, name))):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                table = tables.get(node.value.id)
                if table is not None and node.attr not in table:
                    out.append('{0}: {1}.{2}'.format(name, node.value.id, node.attr))
    return out


@rule
def thin_loader(folder):
    text = read(folder, 'script.py')
    out = []
    if '__persistentengine__ = True' not in text:
        out.append('no persistent engine')
    if 'AddReference' in text:
        out.append('AddReference in loader')
    if not os.path.exists(os.path.join(folder, 'bundle.yaml')):
        out.append('no bundle.yaml')
    return out


@rule
def changelog_has_version(folder):
    version = re.search(r'"([\d.]+)"', read(folder, 'brn_version.py')).group(1)
    return [] if '## ' + version in read(folder, 'CHANGELOG.md') else ['no entry for ' + version]


@rule
def palettes_match(folder):
    text = read(folder, 'brn_theme.py')
    scope = {}
    exec(compile(text, 'theme', 'exec'), scope)
    dark, light = scope['REVIT_DARK'], scope['LIGHT']
    out = []
    if set(dark) != set(light):
        out.append('palette keys differ')
    theme = read(folder, 'Theme.xaml')
    for key, value in dark.items():
        if 'x:Key="{0}" Color="{1}"'.format(key, value) not in theme:
            out.append('Theme.xaml default for ' + key)
    for key, value in (('Title', '#222933'), ('Window', '#3C4454'), ('Field', '#2D3441'),
                       ('Selection', '#3A7392'), ('Edge', '#515C6B')):
        if dark.get(key) != value:
            out.append('not Revit dark: ' + key)
    return out


def contrast(a, b):
    def lum(h):
        parts = [int(h[i:i + 2], 16) / 255.0 for i in (1, 3, 5)]
        parts = [p / 12.92 if p <= .03928 else ((p + .055) / 1.055) ** 2.4 for p in parts]
        return .2126 * parts[0] + .7152 * parts[1] + .0722 * parts[2]
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + .05) / (lo + .05)


@rule
def text_readable(folder):
    scope = {}
    exec(compile(read(folder, 'brn_theme.py'), 'theme', 'exec'), scope)
    out = []
    for name, pal in (('dark', scope['REVIT_DARK']), ('light', scope['LIGHT'])):
        for ink in ('Text', 'Muted', 'Orange', 'Red'):
            for ground in ('Field', 'Title', 'Window'):
                if ink in ('Text', 'Orange', 'Red') or ground != 'Window':
                    if contrast(pal[ink], pal[ground]) < 3.0:
                        out.append('{0} {1} on {2}'.format(name, ink, ground))
    return out


@rule
def chrome_complete(folder):
    out = []
    need = ('Root', 'Header', 'Logo', 'ThemeChip', 'ThemeLabel', 'VersionText', 'ShrinkBtn',
            'ShrinkGlyph', 'ExpandGlyph', 'FullBtn', 'CloseBtn', 'Grips')
    for name in LAYOUTS:
        text = read(folder, name)
        for key in need:
            if 'x:Name="{0}"'.format(key) not in text:
                out.append('{0}: {1}'.format(name, key))
        if 'WindowStyle="None"' not in text:
            out.append(name + ': system frame')
        if '"Baseline"' in text:
            out.append(name + ': Baseline')
        if not re.search(r'x:Name="ExpandGlyph"[^>]*Green[^>]*Visibility="Collapsed"', text):
            out.append(name + ': green arrow')
    return out


@rule
def every_window_themed(folder):
    out = []
    for name in ('brn_dialogs.py', 'brn_main.py'):
        for node in ast.walk(ast.parse(read(folder, name))):
            if isinstance(node, ast.ClassDef) and node.name.endswith(('Window', 'Prompt')):
                if not [b for b in node.bases if getattr(b, 'id', '') == 'ThemedWindow']:
                    out.append(node.name)
    text = read(folder, 'brn_chrome.py')
    if 'self.shrink_btn.Click +=' not in text or 'WpfDrawer(' not in text:
        out.append('drawer not wired')
    if 'Key.H' not in text:
        out.append('no shortcut')
    return out


@rule
def writes_only_in_job(folder):
    out = []
    for name in modules(folder):
        if name == 'brn_revit.py':
            continue
        text = read(folder, name)
        if re.search(r'\bTransaction\(', text) or '.Name =' in text.replace('x:Name', ''):
            out.append(name)
    return out


@rule
def tab_switch_widens(folder):
    text = read(folder, 'brn_main.py')
    found = re.search(r'def set_field.*?def text_width', text, re.S)
    return [] if found and 'self.widen_to_fit()' in found.group(0) else ['tab switch does not widen']


@rule
def settings_cover_three_slots(folder):
    text = read(folder, 'Settings.xaml')
    return ['Param{0}'.format(i) for i in (1, 2, 3)
            if 'x:Name="Param{0}"'.format(i) not in text]


@rule
def raise_answer_read(folder):
    text = read(folder, 'brn_revit.py')
    return [] if 'answer = str(self.event.Raise())' in text else ['Raise result ignored']


@rule
def no_shared_files(folder):
    return [n for n in ('startup.py', '__init__.py') if os.path.exists(os.path.join(folder, n))]


@rule
def tool_name_everywhere(folder):
    name = os.path.basename(os.path.abspath(folder)).replace('.pushbutton', '')
    if not name.startswith('Bulk Rename') and folder == HERE:
        return ['folder ' + name]
    out = []
    if 'title: Bulk Rename' not in read(folder, 'bundle.yaml'):
        out.append('bundle title')
    if 'Text="Bulk Rename"' not in read(folder, 'BulkRename.xaml'):
        out.append('window header')
    return out


@rule
def modules_load_on_stub(folder):
    sys.path.insert(0, folder)
    out = []
    try:
        for key in [k for k in sys.modules if k.startswith(('brn_', 'bench_stubs'))]:
            del sys.modules[key]
        import bench_stubs
        bench_stubs.install()
        for name in modules(folder):
            if name != 'script.py':
                try:
                    importlib.import_module(name[:-3])
                except Exception as error:
                    out.append('{0}: {1!r}'.format(name, error))
    finally:
        sys.path.remove(folder)
        for key in [k for k in sys.modules if k.startswith(('brn_', 'bench_stubs'))]:
            del sys.modules[key]
    return out


BREAKAGES = [
    ('BulkRename.xaml', '<!-- ======== header ======== -->', '<!-- --- header --- -->', 'xaml_parses'),
    ('BulkRename.xaml', 'Style="{DynamicResource GreenButton}"', 'Style="{StaticResource GreenButton}"', 'no_static_resource_in_layout'),
    ('BulkRename.xaml', '{DynamicResource Muted}', '{DynamicResource Mutedd}', 'resource_keys_exist'),
    ('brn_main.py', "ForegroundProperty, 'Muted'", "ForegroundProperty, 'Nope'", 'resource_keys_exist'),
    ('BulkRename.xaml', '<Button x:Name="ClearBtn" Grid.Column="2" Style="{DynamicResource BaseButton}"', '<Button x:Name="ClearBtn" Grid.Column="2" Style="{DynamicResource TabButton}"', 'keyed_styles_match_element'),
    ('BulkRename.xaml', 'x:Name="FindBox" Tag="Find"', 'x:Name="FindBox" Tag="Find" Placeholder="x"', 'members_known'),
    ('BulkRename.xaml', 'x:Name="ListHost"', 'x:Name="ListHostt"', 'looked_up_names_exist'),
    ('brn_core.py', "return u'{0}'.format(value)", "return f'{value}'", 'banned_code'),
    ('brn_core.py', "    return text\n\n\ndef plural", "    print(text)\n    return text\n\n\ndef plural", 'banned_code'),
    ('brn_core.py', 'def to_text(value):\n', 'def to_text(value):\n    # eé\n', 'ascii_only'),
    ('brn_revit.py', 'import brn_clr  # noqa: F401  must stay first\nimport brn_core as core\n\nfrom System.Collections.Generic import List', 'from System.Collections.Generic import List\nimport brn_clr\nimport brn_core as core\n', 'clr_imported_first'),
    ('brn_clr.py', "'System.Windows.Forms',", "", 'assemblies_referenced'),
    ('brn_clr.py', "'mscorlib',", "'mscorlib', 'RevitAPI',", 'assemblies_referenced'),
    ('brn_core.py', 'def ease(progress):', 'def counts(items):\n    return {}\n\n\ndef ease(progress):', 'nothing_defined_twice'),
    ('brn_main.py', 'text = core.plural(count', 'text = plurall(count', 'globals_exist'),
    ('brn_main.py', 'core.plural(count', 'core.plurall(count', 'cross_module_names_exist'),
    ('script.py', '__persistentengine__ = True', '__persistentengine__ = False', 'thin_loader'),
    ('brn_version.py', '"1.1.0"', '"9.9.9"', 'changelog_has_version'),
    ('brn_chrome.py', 'from System.Windows.Media import ColorConverter, SolidColorBrush', 'from System.Windows.Media import ColorConverter, PresentationSource, SolidColorBrush', 'imports_in_real_namespace'),
    ('brn_chrome.py', 'from System.Windows.Forms import Screen', 'from System.Windows.Forms import Screen, NewThing', 'imports_in_real_namespace'),
    ('brn_theme.py', "'Field': '#2D3441'", "'Field': '#1C1C1F'", 'palettes_match'),
    ('brn_theme.py', "'Muted': '#A4AAB1'", "'Muted': '#4A5060'", 'text_readable'),
    ('Prompt.xaml', 'x:Name="ShrinkBtn"', 'x:Name="ShrinkBtnn"', 'chrome_complete'),
    ('BulkRename.xaml', 'Stroke="{DynamicResource Green}" Visibility="Collapsed"', 'Stroke="{DynamicResource Text}" Visibility="Collapsed"', 'chrome_complete'),
    ('brn_dialogs.py', 'class Prompt(ThemedWindow):', 'class Prompt(object):', 'every_window_themed'),
    ('brn_chrome.py', 'self.shrink_btn.Click +=', 'self.shrink_btnx +=', 'every_window_themed'),
    ('brn_main.py', 'def force_close(self):', 'def force_close(self):\n        t = Transaction(self.doc)', 'writes_only_in_job'),
    ('brn_revit.py', 'answer = str(self.event.Raise())', 'self.event.Raise(); answer = "Accepted"', 'raise_answer_read'),
    ('brn_main.py', '        self.refresh()\n        self.widen_to_fit()\n', '        self.refresh()\n', 'tab_switch_widens'),
    ('Settings.xaml', 'x:Name="Param3"', 'x:Name="Param4"', 'settings_cover_three_slots'),
    ('BulkRename.xaml', 'x:Name="SettingsBtn"', 'x:Name="SettingsBtnn"', 'looked_up_names_exist'),
    ('bundle.yaml', 'title: Bulk Rename', 'title: Rename', 'tool_name_everywhere'),
    ('brn_revit.py', 'BuiltInParameter, CADLinkType,', 'BuiltInParameter, CADLinkType, NoSuchThing,', 'modules_load_on_stub'),
]


def run_rules(folder, only=None):
    failed = {}
    for fn in RULES:
        if only and fn.__name__ != only:
            continue
        try:
            found = fn(folder)
        except Exception as error:
            found = [repr(error)]
        if found:
            failed[fn.__name__] = found
    return failed


def selftest():
    missed = []
    for filename, old, new, name in BREAKAGES:
        folder = tempfile.mkdtemp()
        for item in os.listdir(HERE):
            if os.path.isfile(os.path.join(HERE, item)):
                shutil.copy(os.path.join(HERE, item), folder)
        path = os.path.join(folder, filename)
        with open(path, 'r') as handle:
            text = handle.read()
        if old not in text:
            missed.append('target missing: ' + old)
            continue
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write(text.replace(old, new))
        if name not in run_rules(folder, name):
            missed.append(name + ' missed: ' + old)
        shutil.rmtree(folder)
    print('{0} breakages, {1} missed'.format(len(BREAKAGES), len(missed)))
    for line in missed:
        print('  ' + line)
    return not missed


def main():
    if '--selftest' in sys.argv:
        return 0 if selftest() else 1
    failed = run_rules(HERE)
    print('{0} rules, {1} failed'.format(len(RULES), len(failed)))
    for name, found in failed.items():
        print('  {0}: {1}'.format(name, found[:6]))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
