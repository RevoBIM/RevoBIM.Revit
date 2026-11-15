# -*- coding: utf-8 -*-
"""Schematic Marriage - static bench check. Run under plain CPython 3:

    python import_check.py              run every rule
    python import_check.py --selftest   break each rule on purpose and prove it fires

Every rule works on an in-memory copy of the tool's files, so the selftest
can mutate a copy without touching disk.
"""
from __future__ import print_function

import ast
import io
import os
import re
import sys
import tokenize
import types
import xml.dom.minidom

HERE = os.path.dirname(os.path.abspath(__file__))
BENCH = ('import_check.py', 'bench_logic.py', 'make_icon.py')


def load_files():
    files = {}
    for name in sorted(os.listdir(HERE)):
        if name.endswith('.py') or name.endswith('.xaml') or name.endswith('.md'):
            with io.open(os.path.join(HERE, name), encoding='utf-8') as fh:
                files[name] = fh.read()
    return files


def tool_py(files):
    return [n for n in files if n.endswith('.py') and n not in BENCH]


def layouts(files):
    return [n for n in files if n.endswith('.xaml') and n != 'Theme.xaml']


def code_tokens(text):
    """(type, string) for every token that is code - strings and comments removed."""
    out = []
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        out.append(tok)
    return out


def code_only(text):
    """Source with every string literal and comment blanked, so rules check
    code and never match prose in a docstring."""
    lines = text.splitlines(True)
    chars = [list(l) for l in lines]
    for tok in code_tokens(text):
        if tok.type in (tokenize.STRING, tokenize.COMMENT) or tok.type == getattr(tokenize, 'FSTRING_START', -1):
            (sr, sc), (er, ec) = tok.start, tok.end
            for r in range(sr, er + 1):
                row = chars[r - 1]
                a = sc if r == sr else 0
                b = ec if r == er else len(row)
                for i in range(a, min(b, len(row))):
                    if row[i] != '\n':
                        row[i] = ' '
    return ''.join(''.join(r) for r in chars)


# ==========================================================================
# rules
# ==========================================================================

def rule_xaml_parses(files):
    bad = []
    for n in files:
        if n.endswith('.xaml'):
            try:
                xml.dom.minidom.parseString(files[n].encode('utf-8'))
            except Exception as ex:
                bad.append('{0}: {1}'.format(n, ex))
    return bad


def rule_no_static_resource_in_layouts(files):
    return ['{0}: StaticResource in a layout (Theme.xaml is merged after it is parsed)'.format(n)
            for n in layouts(files) if 'StaticResource' in files[n]]


def rule_no_baseline(files):
    return ['{0}: VerticalAlignment="Baseline" kills XamlReader silently'.format(n)
            for n in files if n.endswith('.xaml') and 'Baseline' in files[n]]


def theme_keys(files):
    return set(re.findall(r'x:Key="([^"]+)"', files.get('Theme.xaml', '')))


def palette_keys(files):
    src = files.get('sm_wpf.py', '')
    m = re.search(r"PALETTES = \{(.*?)\n\}", src, re.S)
    if not m:
        return {}, {}
    body = m.group(1)
    parts = re.split(r"'(dark|light)': \{", body)
    out = {}
    for i in range(1, len(parts), 2):
        out[parts[i]] = set(re.findall(r"'([A-Za-z]+Brush)'", parts[i + 1]))
    return out.get('dark', set()), out.get('light', set())


def rule_resource_keys_defined(files):
    keys = theme_keys(files)
    dark, light = palette_keys(files)
    keys |= dark | light
    bad = []
    for n in files:
        if n.endswith('.xaml'):
            for k in re.findall(r'\{DynamicResource ([A-Za-z0-9_]+)\}', files[n]):
                if k not in keys:
                    bad.append('{0}: DynamicResource {1} is not defined'.format(n, k))
    for n in tool_py(files):
        for k in re.findall(r"SetResourceReference\([^,]+,\s*'([A-Za-z0-9_]+)'\)", files[n]):
            if k not in keys:
                bad.append('{0}: SetResourceReference key {1} is not defined'.format(n, k))
        for k in re.findall(r"brush_key='([A-Za-z0-9_]+)'", files[n]):
            if k not in keys:
                bad.append('{0}: brush_key {1} is not defined'.format(n, k))
        for k in re.findall(r"Resources\['([A-Za-z0-9_]+)'\]", files[n]):
            if k not in keys:
                bad.append('{0}: Resources[{1}] is not defined'.format(n, k))
        for k in re.findall(r"u'([A-Za-z]+Brush)'", files[n]):
            if k not in keys:
                bad.append('{0}: brush {1} is not defined'.format(n, k))
    return bad


def rule_palettes_match(files):
    dark, light = palette_keys(files)
    theme_brushes = set(re.findall(r'<SolidColorBrush x:Key="([^"]+)"', files.get('Theme.xaml', '')))
    bad = []
    if not dark or not light:
        bad.append('PALETTES not found in sm_wpf.py')
    if dark != light:
        bad.append('dark and light palettes differ: {0}'.format(sorted(dark ^ light)))
    if theme_brushes != dark:
        bad.append('Theme.xaml brushes and the palette differ: {0}'.format(sorted(theme_brushes ^ dark)))
    return bad


def xaml_names(files):
    names = {}
    for n in files:
        if n.endswith('.xaml'):
            for x in re.findall(r'x:Name="([^"]+)"', files[n]):
                names.setdefault(x, []).append(n)
    return names


def rule_names_exist(files):
    names = xaml_names(files)
    bad = []
    for n in tool_py(files):
        code = files[n]
        used = re.findall(r"FindName\(u?'([A-Za-z0-9_]+)'\)", code)
        for arg in re.findall(r"self\.n\(([^()]*)\)", code):
            if '+' in arg:
                continue                      # prefix + suffix: checked below
            used += re.findall(r"u?'([A-Z][A-Za-z0-9_]+)'", arg)   # x:Names are PascalCase
        for x in used:
            if x not in names:
                bad.append('{0}: element {1} has no x:Name in any layout'.format(n, x))
        for x in re.findall(r"self\.n\(prefix \+ u'([A-Za-z]+)'\)", code):
            for prefix in ('TxtSrc', 'TxtTgt'):
                if prefix + x not in names:
                    bad.append('{0}: element {1}{2} missing'.format(n, prefix, x))
        m = re.search(r"GRIPS = \(([^)]*)\)", code)
        if m:
            for x in re.findall(r"'([A-Za-z]+)'", m.group(1)):
                for lay in layouts(files):
                    if lay != 'SMPrompt.xaml' and 'x:Name="{0}"'.format(x) not in files[lay]:
                        bad.append('{0}: resize grip {1} missing'.format(lay, x))
    return bad


def rule_unique_names_per_layout(files):
    bad = []
    for n in layouts(files):
        if True:
            seen = set()
            for x in re.findall(r'x:Name="([^"]+)"', files[n]):
                if x in seen:
                    bad.append('{0}: x:Name {1} twice'.format(n, x))
                seen.add(x)
    return bad


def rule_brush_converters_never_unset(files):
    """A brush converter that returns None hands WPF UnsetValue, and the text
    falls to WPF's default brush, not the theme - unreadable on dark (1.0.0)."""
    bad = []
    for n in tool_py(files):
        for node in ast.walk(ast.parse(files[n])):
            if isinstance(node, ast.FunctionDef) and node.name == '_cell_brush':
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Return) and (sub.value is None or (
                            isinstance(sub.value, ast.Constant) and sub.value.value is None)):
                        bad.append('{0}:{1}: _cell_brush returns None'.format(n, sub.lineno))
    return bad


COLOURED_BUTTONS = ('GreenBtn', 'BlueBtn', 'OrangeBtn', 'RedBtn', 'SmallRedBtn', 'SmallBlueBtn', 'CellBtn')


def rule_coloured_buttons_have_shadow(files):
    """Every coloured button gets the clickable shadow template (1.2.0)."""
    theme = files.get('Theme.xaml', '')
    bad = []
    for key in COLOURED_BUTTONS:
        i = theme.find('<Style x:Key="{0}"'.format(key))
        if i < 0:
            bad.append('Theme.xaml: style {0} missing'.format(key))
            continue
        block = theme[i:theme.find('</Style>', i)]
        if 'ShadowBtnTemplate' not in block:
            bad.append('Theme.xaml: {0} has no clickable shadow'.format(key))
    return bad


def rule_assign_only_stages(files):
    """Choosing a template stages it; only Apply Changes writes (1.3.0)."""
    bad = []
    tree = ast.parse(files.get('sm_ui.py', ''))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in ('assign', 'do_undo', 'do_redo'):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Attribute) and sub.attr in ('submit', 'save_records'):
                    bad.append('sm_ui.py:{0}: {1}() writes to the model - it must only stage'.format(
                        sub.lineno, node.name))
    return bad


def rule_every_window_has_drawer(files):
    """Project rule: every window gets the shrink-to-taskbar drawer button
    in its header, with both glyphs (down, and the green up arrow)."""
    bad = []
    for n in sorted(files):
        if not n.endswith('.xaml') or n == 'Theme.xaml':
            continue
        for name in ('BtnDrawer', 'DrawerDown', 'DrawerUp', 'HeaderBar'):
            if 'x:Name="{0}"'.format(name) not in files[n]:
                bad.append('{0}: no {1} - every window needs the shrink-to-taskbar drawer'.format(n, name))
    code = files.get('sm_wpf.py', '')
    if code.count('Drawer(') < 3:          # the class + ThemedWindow + prompt
        bad.append('sm_wpf.py: Drawer is not wired into both the themed windows and the prompt')
    return bad


REVIT_DARK = {      # house values - theme reference, "Revit's own dark palette"
    'CardBrush': '#3C4454', 'FieldBrush': '#2D3441', 'BarBrush': '#222933', 'HeadBrush': '#323C48',
    'EdgeBrush': '#515C6B', 'SelBrush': '#3A7392', 'HoverBrush': '#444E5E', 'TextBrush': '#EEF0F4',
    'MutedBrush': '#A4AAB1', 'BlueBrush': '#5AAEEB',
}


def _luminance(h):
    h = h.lstrip('#')[-6:]
    out = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255.0
        out.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]


def _contrast(a, b):
    la, lb = sorted([_luminance(a), _luminance(b)], reverse=True)
    return (la + 0.05) / (lb + 0.05)


def rule_revit_dark(files):
    """Dark palette = Revit's own dark UI, Theme.xaml defaults = the palette
    (or a window flashes the old colours), and text readable on every dark
    surface: body text >= 4.5:1 everywhere incl. the selection, muted >= 4:1
    on the surfaces it is used on."""
    code = files.get('sm_wpf.py', '')
    m = re.search(r"'dark': \{(.*?)\n    \}", code, re.S)
    if not m:
        return ['sm_wpf.py: dark palette not found']
    dark = dict(re.findall(r"'([A-Za-z]+Brush)': '(#[0-9A-Fa-f]+)'", m.group(1)))
    bad = []
    for k, v in REVIT_DARK.items():
        if dark.get(k, '').upper() != v.upper():
            bad.append('dark {0} is {1}, Revit dark is {2}'.format(k, dark.get(k), v))
    theme = dict(re.findall(r'<SolidColorBrush x:Key="([^"]+)" Color="([^"]+)"', files.get('Theme.xaml', '')))
    for k, v in dark.items():
        if theme.get(k, '').upper() != v.upper():
            bad.append('Theme.xaml {0} is {1}, the dark palette says {2}'.format(k, theme.get(k), v))
    text, muted = dark.get('TextBrush', '#000000'), dark.get('MutedBrush', '#000000')
    for k in ('BgBrush', 'CardBrush', 'FieldBrush', 'BarBrush', 'HeadBrush', 'SelBrush', 'RowAltBrush', 'HoverBrush'):
        if k in dark and _contrast(text, dark[k]) < 4.5:
            bad.append('body text on {0} is {1:.1f}:1 (< 4.5)'.format(k, _contrast(text, dark[k])))
    for k in ('BgBrush', 'CardBrush', 'FieldBrush', 'BarBrush', 'HeadBrush'):
        if k in dark and _contrast(muted, dark[k]) < 4.0:
            bad.append('muted text on {0} is {1:.1f}:1 (< 4.0)'.format(k, _contrast(muted, dark[k])))
    return bad


def rule_code_bans(files):
    bad = []
    for n in tool_py(files):
        text = files[n]
        for tok in code_tokens(text):
            if tok.type == tokenize.STRING and re.match(r'^[rRbBuU]*[fF]', tok.string):
                bad.append('{0}:{1}: f-string'.format(n, tok.start[0]))
            if tok.type == getattr(tokenize, 'FSTRING_START', -1):
                bad.append('{0}:{1}: f-string'.format(n, tok.start[0]))
        code = code_only(text)
        for i, line in enumerate(code.splitlines(), 1):
            if re.search(r'(^|\s)print\b', line):
                bad.append('{0}:{1}: print'.format(n, i))
            if re.search(r'\bSystem\b.*\bUri\b|\bimport\s+Uri\b|\bUri\(', line):
                bad.append('{0}:{1}: System.Uri (moved in Revit 2025)'.format(n, i))
        # .IntegerValue only inside eid_value()
        tree = ast.parse(text)
        allowed = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == 'eid_value':
                for sub in ast.walk(node):
                    allowed.add(id(sub))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == 'IntegerValue' and id(node) not in allowed:
                bad.append('{0}:{1}: bare .IntegerValue (removed in Revit 2026)'.format(n, node.lineno))
    return bad


def rule_ascii_outside_unicode_literals(files):
    bad = []
    for n in tool_py(files):
        text = files[n]
        for tok in code_tokens(text):
            if all(ord(c) < 128 for c in tok.string):
                continue
            if tok.type == tokenize.COMMENT:
                continue
            if tok.type == tokenize.STRING and re.match(r'^[uU]', tok.string):
                continue
            bad.append('{0}:{1}: non-ASCII outside a u\'\' literal'.format(n, tok.start[0]))
    return bad


NAMESPACE_OF = {
    'System': {'Guid', 'String', 'Action', 'TimeSpan', 'AppDomain', 'EventHandler', 'Enum'},
    'System.Collections.Generic': {'List'},
    'System.Diagnostics': {'Stopwatch'},
    'System.IO': {'File', 'FileStream', 'FileMode', 'FileAccess', 'MemoryStream'},
    'System.Text': {'Encoding'},
    'System.Windows': {'Thickness', 'Visibility', 'VerticalAlignment', 'TextTrimming', 'FontWeights',
                       'DataTemplate', 'FrameworkElementFactory', 'RoutedEventHandler',
                       'DependencyProperty', 'PresentationSource', 'SystemParameters', 'TextWrapping',
                       'GridLength', 'GridUnitType', 'Clipboard', 'Window', 'WindowStyle', 'Int32Rect',
                       'Size', 'FrameworkElement', 'Point', 'CornerRadius', 'SizeToContent',
                       'WindowStartupLocation', 'Style', 'Setter', 'DataTrigger', 'DynamicResourceExtension'},
    'System.Windows.Controls': {'TextBlock', 'TextBox', 'Button', 'StackPanel', 'ContextMenu', 'MenuItem',
                                'DataGridTemplateColumn', 'DataGridLength', 'DataGridLengthUnitType',
                                'ListBoxItem', 'Orientation', 'DataGridRow', 'ScrollViewer',
                                'ScrollBarVisibility', 'Canvas', 'Image', 'ToolTipService', 'ToolTipEventHandler'},
    'System.Windows.Controls.Primitives': {'DataGridColumnHeader', 'ScrollBar', 'PlacementMode'},
    'System.Windows.Data': {'Binding', 'IValueConverter', 'RelativeSource', 'RelativeSourceMode'},
    'System.Windows.Input': {'Key', 'Keyboard', 'ModifierKeys'},
    'System.Windows.Interop': {'WindowInteropHelper'},
    'System.Windows.Markup': {'XamlReader'},
    'System.Windows.Media': {'SolidColorBrush', 'ColorConverter', 'VisualTreeHelper', 'FontFamily',
                             'PixelFormats', 'Stretch', 'CompositionTarget', 'MatrixTransform', 'Matrix',
                             'RenderOptions', 'BitmapScalingMode', 'TranslateTransform'},
    'System.Windows.Media.Imaging': {'BitmapImage', 'BitmapCacheOption', 'RenderTargetBitmap', 'CroppedBitmap'},
    'System.Windows.Threading': {'Dispatcher', 'DispatcherPriority', 'DispatcherTimer'},
    'System.Windows.Forms': {'Screen'},
    'Microsoft.Win32': {'OpenFileDialog', 'SaveFileDialog'},
    'Autodesk.Revit.DB': {'Element', 'ElementId', 'FilteredElementCollector', 'Transaction',
                          'TransactionGroup', 'IFailuresPreprocessor', 'FailureProcessingResult',
                          'FailureSeverity', 'WorksharingUtils', 'OverrideGraphicSettings', 'Color',
                          'FillPatternElement', 'View3D', 'ViewFamilyType', 'XYZ', 'BoundingBoxXYZ',
                          'ElementCategoryFilter', 'BuiltInCategory', 'TemporaryViewMode'},
    'Autodesk.Revit.DB.ExtensibleStorage': {'SchemaBuilder', 'Schema', 'Entity', 'AccessLevel',
                                            'DataStorage', 'ExtensibleStorageFilter'},
    'Autodesk.Revit.DB.Events': {'DocumentChangedEventArgs'},
    'Autodesk.Revit.UI': {'ExternalEvent', 'IExternalEventHandler', 'TaskDialog'},
    'Autodesk.Revit.UI.Selection': {'ISelectionFilter', 'ObjectType'},
}

ASSEMBLY_FOR = {
    'System': ['mscorlib', 'System'],
    'System.Collections.Generic': ['mscorlib', 'System'],
    'System.Diagnostics': ['System', 'mscorlib'],
    'System.IO': ['mscorlib'],
    'System.Text': ['mscorlib'],
    'System.Windows': ['PresentationFramework', 'PresentationCore', 'WindowsBase'],
    'System.Windows.Controls': ['PresentationFramework'],
    'System.Windows.Controls.Primitives': ['PresentationFramework'],
    'System.Windows.Data': ['PresentationFramework'],
    'System.Windows.Input': ['PresentationCore'],
    'System.Windows.Interop': ['PresentationFramework'],
    'System.Windows.Markup': ['PresentationFramework'],
    'System.Windows.Media': ['PresentationCore'],
    'System.Windows.Media.Imaging': ['PresentationCore'],
    'System.Windows.Threading': ['WindowsBase'],
    'System.Windows.Forms': ['System.Windows.Forms'],
    'Microsoft.Win32': ['PresentationFramework'],
}
PRELOADED = ('Autodesk.',)


def _imports(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            yield node.module, [a.name for a in node.names], node
        elif isinstance(node, ast.Import):
            for a in node.names:
                yield a.name, [], node


def _dotnet(ns):
    return ns == 'System' or ns.startswith('System.') or ns.startswith('Autodesk.') or ns.startswith('Microsoft.')


def rule_names_in_right_namespace(files):
    bad = []
    for n in tool_py(files):
        for ns, names, node in _imports(ast.parse(files[n])):
            if not _dotnet(ns) or not names:
                continue
            known = NAMESPACE_OF.get(ns)
            if known is None:
                bad.append('{0}:{1}: namespace {2} not in NAMESPACE_OF'.format(n, node.lineno, ns))
                continue
            for name in names:
                if name not in known:
                    home = [k for k, v in NAMESPACE_OF.items() if name in v]
                    bad.append('{0}:{1}: {2} imported from {3}{4}'.format(
                        n, node.lineno, name, ns, (' - it lives in ' + home[0]) if home else ' - unknown name'))
    return bad


def clr_assemblies(files):
    m = re.search(r"ASSEMBLIES = \[(.*?)\]", files.get('sm_clr.py', ''), re.S)
    return set(re.findall(r"'([^']+)'", m.group(1))) if m else set()


def rule_assemblies_referenced(files):
    refs = clr_assemblies(files)
    bad = []
    for n in tool_py(files):
        for ns, _names, node in _imports(ast.parse(files[n])):
            if not _dotnet(ns) or ns.startswith(PRELOADED):
                continue
            need = ASSEMBLY_FOR.get(ns)
            if need is None:
                bad.append('{0}:{1}: no ASSEMBLY_FOR entry for {2}'.format(n, node.lineno, ns))
            elif not any(a in refs for a in need):
                bad.append('{0}:{1}: {2} needs one of {3} in sm_clr.ASSEMBLIES'.format(n, node.lineno, ns, need))
    return bad


def rule_clr_first(files):
    bad = []
    for n in tool_py(files):
        if n in ('sm_clr.py', 'script.py'):
            continue
        tree = ast.parse(files[n])
        first_net, clr_line = None, None
        for node in tree.body:
            if isinstance(node, ast.Import) and any(a.name == 'sm_clr' for a in node.names):
                clr_line = clr_line or node.lineno
            mod = None
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ''
            elif isinstance(node, ast.Import):
                mod = node.names[0].name
            if mod and _dotnet(mod) and first_net is None:
                first_net = node.lineno
        if first_net is not None and (clr_line is None or clr_line > first_net):
            bad.append('{0}: imports .NET at line {1} before sm_clr'.format(n, first_net))
    return bad


def rule_no_duplicate_defs(files):
    bad = []
    for n in tool_py(files):
        tree = ast.parse(files[n])
        scopes = [('module', tree.body)] + [(c.name, c.body) for c in ast.walk(tree) if isinstance(c, ast.ClassDef)]
        for scope, body in scopes:
            seen = set()
            for node in body:
                if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                    if node.name in seen:
                        bad.append('{0}: {1}.{2} defined twice - the second silently wins'.format(n, scope, node.name))
                    seen.add(node.name)
    return bad


def rule_script_is_thin(files):
    s = files.get('script.py', '')
    bad = []
    code = code_only(s)
    if 'AddReference' in code:
        bad.append('script.py: clr.AddReference belongs in sm_clr.py')
    tree = ast.parse(s)
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mod = node.module if isinstance(node, ast.ImportFrom) else node.names[0].name
            if mod and mod.startswith('sm_') and mod != 'sm_version':
                bad.append('script.py: {0} imported at module level - outside the staged try'.format(mod))
    if '__persistentengine__ = True' not in s:
        bad.append('script.py: modeless window needs __persistentengine__ = True')
    return bad


def rule_changelog_has_version(files):
    m = re.search(r'__version__ = "([^"]+)"', files.get('sm_version.py', ''))
    if not m:
        return ['sm_version.py has no __version__']
    if '## ' + m.group(1) not in files.get('CHANGELOG.md', ''):
        return ['CHANGELOG.md has no entry for ' + m.group(1)]
    return []


def rule_version_not_hardcoded(files):
    """The windows read the version - a hard-coded one goes stale."""
    bad = []
    for n in tool_py(files):
        if n == 'sm_version.py':
            continue
        if re.search(r"""Text\s*=\s*u?['"]v\d""", code_only(files[n]) + files[n]):
            bad.append('{0}: version text hard-coded'.format(n))
    return bad


# ---- nothing reachable from __init__ reads an attribute nothing has set ----

class _Cls(object):
    def __init__(self, node, module):
        self.node = node
        self.module = module
        self.methods = dict((f.name, f) for f in node.body if isinstance(f, ast.FunctionDef))
        self.attrs = set()
        for f in node.body:
            if isinstance(f, ast.Assign):
                for t in f.targets:
                    if isinstance(t, ast.Name):
                        self.attrs.add(t.id)
        self.bases = []
        for b in node.bases:
            if isinstance(b, ast.Name):
                self.bases.append(b.id)
            elif isinstance(b, ast.Attribute):
                self.bases.append(b.attr)


def _classes(files):
    out = {}
    for n in tool_py(files):
        for node in ast.walk(ast.parse(files[n])):
            if isinstance(node, ast.ClassDef):
                out[node.name] = _Cls(node, n)
    return out


def _mro(classes, name):
    seen, order, todo = set(), [], [name]
    while todo:
        c = todo.pop(0)
        if c in seen or c not in classes:
            continue
        seen.add(c)
        order.append(classes[c])
        todo.extend(classes[c].bases)
    return order


def _find_method(classes, cls_name, meth):
    for c in _mro(classes, cls_name):
        if meth in c.methods:
            return c, c.methods[meth]
    return None, None


def _known_static(classes, cls_name, attr):
    for c in _mro(classes, cls_name):
        if attr in c.methods or attr in c.attrs:
            return True
    return False


class _Sim(object):
    def __init__(self, classes, concrete):
        self.classes = classes
        self.concrete = concrete
        self.assigned = set()
        self.problems = []
        self.stack = []

    def run_method(self, owner_name, meth):
        c, fn = _find_method(self.classes, owner_name, meth)
        if fn is None:
            return
        key = (c.node.name, meth)
        if key in self.stack:
            return
        self.stack.append(key)
        for stmt in fn.body:
            self.stmt(stmt)
        self.stack.pop()

    def stmt(self, node):
        if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Lambda)):
            return
        if isinstance(node, ast.Assign):
            self.expr(node.value)
            for t in node.targets:
                self.target(t)
            return
        if isinstance(node, ast.AugAssign):
            self.expr(node.value)
            if self._is_self_attr(node.target):
                self.read(node.target)
            else:
                self.expr(node.target)
            self.target(node.target)
            return
        if isinstance(node, ast.AnnAssign):
            if node.value is not None:
                self.expr(node.value)
            self.target(node.target)
            return
        for field, value in ast.iter_fields(node):
            if isinstance(value, list):
                for v in value:
                    if isinstance(v, ast.stmt):
                        self.stmt(v)
                    elif isinstance(v, ast.AST):
                        self.expr(v)
            elif isinstance(value, ast.stmt):
                self.stmt(value)
            elif isinstance(value, ast.AST):
                self.expr(value)

    def target(self, t):
        if self._is_self_attr(t):
            self.assigned.add(t.attr)
        elif isinstance(t, (ast.Tuple, ast.List)):
            for e in t.elts:
                self.target(e)
        else:
            self.expr(t)

    @staticmethod
    def _is_self_attr(node):
        return isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == 'self'

    def read(self, node):
        attr = node.attr
        if attr in self.assigned or _known_static(self.classes, self.concrete, attr):
            return
        self.problems.append('{0}: {1}.__init__ reaches a read of self.{2} (line {3}) before anything sets it'.format(
            self.classes[self.concrete].module, self.concrete, attr, node.lineno))

    def expr(self, node):
        if node is None or isinstance(node, (ast.Lambda, ast.FunctionDef)):
            return
        if isinstance(node, ast.Call):
            f = node.func
            for a in node.args:
                self.expr(a)
            for k in node.keywords:
                self.expr(k.value)
            if self._is_self_attr(f):
                if not self.assigned.issuperset([f.attr]) and _find_method(self.classes, self.concrete, f.attr)[1] is not None:
                    self.run_method(self.concrete, f.attr)
                    return
                self.read(f)
                return
            # Base.__init__(self, ...) / module.Base.method(self, ...)
            if isinstance(f, ast.Attribute) and node.args and isinstance(node.args[0], ast.Name) \
                    and node.args[0].id == 'self':
                base = f.value.attr if isinstance(f.value, ast.Attribute) else getattr(f.value, 'id', None)
                if base in self.classes:
                    c, fn = _find_method(self.classes, base, f.attr)
                    if fn is not None:
                        key = (c.node.name, f.attr)
                        if key not in self.stack:
                            self.stack.append(key)
                            for stmt in fn.body:
                                self.stmt(stmt)
                            self.stack.pop()
                    return
            self.expr(f)
            return
        if self._is_self_attr(node):
            if isinstance(node.ctx, ast.Load):
                self.read(node)
            return
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.AST):
                self.expr(child)


def rule_init_reads_set(files):
    classes = _classes(files)
    bad = []
    for name, c in classes.items():
        if '__init__' not in c.methods:
            continue
        sim = _Sim(classes, name)
        sim.run_method(name, '__init__')
        bad.extend(sim.problems)
    return sorted(set(bad))


# ---- every tool module loads against a stub .NET / Revit API -------------

class _StubMeta(type):
    def __getattr__(cls, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return _stub_class(name)

    def __getitem__(cls, item):
        return cls

    def __call__(cls, *args, **kwargs):
        return type.__call__(cls)


def _stub_class(name):
    return _StubMeta(str(name), (object,), {'__init__': lambda self, *a, **k: None,
                                            '__getattr__': lambda self, n: _stub_class(n)})


class _StubModule(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return _stub_class(name)


class _Finder(object):
    PREFIXES = ('System', 'Autodesk', 'Microsoft', 'clr')

    def find_spec(self, fullname, path, target=None):
        if fullname.split('.')[0] in self.PREFIXES:
            import importlib.machinery
            return importlib.machinery.ModuleSpec(fullname, self, is_package=True)
        return None

    def create_module(self, spec):
        m = _StubModule(spec.name)
        m.__path__ = []
        if spec.name == 'clr':
            m.AddReference = lambda name: None
            m.GetClrType = lambda t: t
        return m

    def exec_module(self, module):
        pass


def rule_modules_load(files, folder=None):
    import tempfile
    import shutil
    import importlib
    tmp = tempfile.mkdtemp()
    bad = []
    try:
        for n, text in files.items():
            with io.open(os.path.join(tmp, n), 'w', encoding='utf-8') as fh:
                fh.write(text)
        finder = _Finder()
        sys.meta_path.insert(0, finder)
        sys.path.insert(0, tmp)
        saved = dict(sys.modules)
        try:
            for n in sorted(tool_py(files)):
                if n == 'script.py':
                    continue
                name = n[:-3]
                for k in list(sys.modules):
                    if k.startswith('sm_'):
                        del sys.modules[k]
                try:
                    importlib.import_module(name)
                except Exception as ex:
                    bad.append('{0}: fails to load against the stub API: {1}: {2}'.format(n, type(ex).__name__, ex))
        finally:
            sys.meta_path.remove(finder)
            sys.path.remove(tmp)
            for k in list(sys.modules):
                if k not in saved:
                    del sys.modules[k]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return bad


RULES = [
    rule_xaml_parses, rule_no_static_resource_in_layouts, rule_no_baseline,
    rule_resource_keys_defined, rule_palettes_match, rule_names_exist,
    rule_unique_names_per_layout, rule_brush_converters_never_unset, rule_coloured_buttons_have_shadow, rule_assign_only_stages, rule_every_window_has_drawer, rule_revit_dark, rule_code_bans, rule_ascii_outside_unicode_literals,
    rule_names_in_right_namespace, rule_assemblies_referenced, rule_clr_first,
    rule_no_duplicate_defs, rule_script_is_thin, rule_changelog_has_version,
    rule_version_not_hardcoded, rule_init_reads_set, rule_modules_load,
]


# ==========================================================================
# selftest: every rule must catch its own deliberate breakage
# ==========================================================================

def _sub(name, old, new, count=1):
    def mutate(files):
        assert old in files[name], 'selftest anchor missing in {0}: {1!r}'.format(name, old)
        files[name] = files[name].replace(old, new, count)
    return mutate


def _append(name, text):
    def mutate(files):
        files[name] = files[name] + text
    return mutate


def _move_after(name, line, after):
    def mutate(files):
        text = files[name]
        assert line in text and after in text, 'selftest anchor missing'
        text = text.replace(line + '\n', '', 1)
        text = text.replace(after + '\n', after + '\n' + line + '\n', 1)
        files[name] = text
    return mutate


BREAKS = {
    'rule_xaml_parses': _sub('SMPrompt.xaml', '<Grid>', '<Grid><!-- banner -- drawn with hyphens -->'),
    'rule_no_static_resource_in_layouts': _sub('SchematicMarriage.xaml', '{DynamicResource Card}', '{StaticResource Card}'),
    'rule_no_baseline': _sub('SchematicMarriage.xaml', 'VerticalAlignment="Bottom"', 'VerticalAlignment="Baseline"'),
    'rule_resource_keys_defined': _sub('SMTemplates.xaml', '{DynamicResource Card}', '{DynamicResource Cardd}'),
    'rule_palettes_match': _sub('sm_wpf.py', "'BlueSoftBrush': '#DCEAF7',", ''),
    'rule_names_exist': _sub('sm_ui.py', "self.n('BtnUpdate')", "self.n('BtnUpdat')"),
    'rule_unique_names_per_layout': _sub('SMPrompt.xaml', 'x:Name="TxtCancel"', 'x:Name="TxtOk"'),
    'rule_brush_converters_never_unset': _sub('sm_tpl_ui.py', "return res['TextBrush']   #", "return None   #"),
    'rule_coloured_buttons_have_shadow': lambda f: f.__setitem__('Theme.xaml', f['Theme.xaml'].replace(
        '<Style x:Key="RedBtn" TargetType="Button">\n        <Setter Property="Template" Value="{StaticResource ShadowBtnTemplate}"/>',
        '<Style x:Key="RedBtn" TargetType="Button">\n        <Setter Property="Template" Value="{StaticResource BtnTemplate}"/>')),
    'rule_assign_only_stages': _sub('sm_ui.py', "        self.state.data_changed()\n        self.status(u'{0} marriage(s) set to",
                                    "        self.state.runner.submit(u'x', None)\n        self.state.data_changed()\n        self.status(u'{0} marriage(s) set to"),
    'rule_every_window_has_drawer': _sub('SMPrompt.xaml', 'x:Name="BtnDrawer"', 'x:Name="BtnShrink"'),
    'rule_revit_dark': _sub('Theme.xaml', '<SolidColorBrush x:Key="CardBrush" Color="#3C4454"/>',
                            '<SolidColorBrush x:Key="CardBrush" Color="#2B2B2E"/>'),
    'rule_code_bans': _append('sm_revit.py', '\n\ndef _old_id(e):\n    return e.Id.IntegerValue\n'),
    'rule_ascii_outside_unicode_literals': _sub('sm_ui.py', "DOT = u'  \\u00b7  '", u"DOT = '  \u00b7  '"),
    'rule_names_in_right_namespace': _sub('sm_ui.py', 'from System.Windows.Controls import DataGridRow, TextBlock',
                                          'from System.Windows import DataGridRow, TextBlock'),
    'rule_assemblies_referenced': _sub('sm_clr.py', "'PresentationFramework', ", ''),
    'rule_clr_first': _move_after('sm_tpl_ui.py', 'import sm_clr  # noqa: F401  (must stay first - references the assemblies)',
                                  'from Microsoft.Win32 import OpenFileDialog, SaveFileDialog'),
    'rule_no_duplicate_defs': _sub('sm_store.py', 'def now_text():', 'def natural_key(text):\n    return text\n\n\ndef now_text():'),
    'rule_script_is_thin': _sub('script.py', 'import os\n', 'import os\nimport sm_ui\n'),
    'rule_changelog_has_version': _sub('CHANGELOG.md', '## ', '## v', count=99),
    'rule_version_not_hardcoded': _sub('sm_wpf.py', "self.n('TxtVersion').Text = u'v' + __version__",
                                       "self.n('TxtVersion').Text = u'v1.0.0'"),
    'rule_init_reads_set': _move_after('sm_ui.py', '        self.text_conv = ui.FuncConverter(self._cell_text)',
                                       '        self._build_columns()'),
    'rule_modules_load': _sub('sm_store.py', 'KIND_MARRIAGE = u\'marriage\'', 'KIND_MARRIAGE = undefined_name'),
}


def run(files, verbose=True):
    total = 0
    for rule in RULES:
        problems = rule(files)
        total += len(problems)
        if verbose:
            print('{0:40s} {1}'.format(rule.__name__, 'ok' if not problems else 'FAIL'))
            for p in problems:
                print('    ' + p)
    return total


def selftest():
    clean = load_files()
    failures = 0
    for rule in RULES:
        name = rule.__name__
        if rule(dict(clean)):
            print('{0:40s} FAIL (fires on the clean tool)'.format(name))
            failures += 1
            continue
        breaker = BREAKS.get(name)
        if breaker is None:
            print('{0:40s} FAIL (no deliberate breakage defined)'.format(name))
            failures += 1
            continue
        broken = dict(clean)
        breaker(broken)
        caught = rule(broken)
        print('{0:40s} {1}'.format(name, 'caught: ' + caught[0][:90] if caught else 'MISSED ITS BREAKAGE'))
        if not caught:
            failures += 1
    return failures


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        bad = selftest()
        print('\nselftest: {0}'.format('all rules proved' if not bad else '{0} rule(s) not proved'.format(bad)))
        sys.exit(1 if bad else 0)
    n = run(load_files())
    print('\n{0}'.format('all checks pass' if not n else '{0} problem(s)'.format(n)))
    sys.exit(1 if n else 0)
