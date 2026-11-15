# -*- coding: utf-8 -*-
u"""Project Browser Pro - static bench rules, run under plain CPython 3.

    python import_check.py              run every rule
    python import_check.py --selftest   break the tool one way per rule, in a
                                        copy of the delivery, and prove each
                                        rule catches its own breakage

These are the failures no stub run can see: a layout that will not parse (a
blank pyRevit window), a missing clr.AddReference, a 2025-only name imported
where Revit 2024 loads the module, syntax IronPython 2.7 rejects, a theme
key nobody defined, an unguarded WPF handler that fails silently.
"""
import ast
import io
import os
import re
import shutil
import string
import subprocess
import sys
import tempfile
import tokenize
import xml.dom.minidom
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
EXT_ROOT = os.path.normpath(os.path.join(HERE, '..', '..', '..'))
DELIVERY_ROOT = os.path.dirname(EXT_ROOT)
# The block startup.py needs, shipped in the tool's folder so the Dock button can add it.
FRAGMENT = os.path.join(HERE, 'startup_fragment.txt')
BENCH_FILES = ('import_check.py', 'bench_logic.py', 'bench_stub.py')

ASSEMBLY_FOR = {
    'System': ['mscorlib', 'System'],
    'System.IO': ['mscorlib'],
    'System.Collections.Generic': ['mscorlib', 'System'],
    'System.Data': ['System.Data'],
    'System.Diagnostics': ['System', 'System.Diagnostics.Process'],
    'System.Windows': ['PresentationFramework', 'PresentationCore', 'WindowsBase'],
    'System.Windows.Controls': ['PresentationFramework'],
    'System.Windows.Controls.Primitives': ['PresentationFramework'],
    'System.Windows.Media': ['PresentationCore'],
    'System.Windows.Shapes': ['PresentationFramework'],
    'System.Windows.Media.Imaging': ['PresentationCore'],
    'System.Windows.Input': ['PresentationCore'],
    'System.Windows.Markup': ['PresentationFramework', 'System.Xaml'],
    'System.Windows.Threading': ['WindowsBase'],
    'System.Windows.Interop': ['PresentationFramework', 'PresentationCore'],
    'System.Windows.Forms': ['System.Windows.Forms'],
    'System.Xml': ['System.Xml'],
    'Autodesk.Windows': ['AdWindows'],
}
PRELOADED = ('Autodesk.Revit',)
# Revit API names that some Revit from 2021 to 2027 lacks (or that are worth
# guarding anyway). Each may only be imported inside a try with a fallback -
# a grouped import is all or nothing, and one missing name takes the module.
VERSIONED_NAMES = {
    'UIThemeManager': 2024, 'UITheme': 2024, 'IContextMenuCreator': 2025,
    'CommandMenuItem': 2025, 'ContextMenu': 2025, 'PDFExportOptions': 2022,
    'RevisionNumberingSequence': 2022, 'BrowserOrganization': 2019,
    'PanelScheduleView': 2012, 'PanelScheduleSheetInstance': 2012,
}
MARKUP = set(['Binding', 'DynamicResource', 'TemplateBinding', 'x:Null', 'x:Static',
              'x:Type', 'RelativeSource', 'StaticResource'])
HANDLER_MODULES = ('pbp_browser.py', 'pbp_orgwin.py', 'pbp_ui.py', 'pbp_window.py')


# ============================================================
# reading the tool
# ============================================================

def tool_files(ext):
    return sorted(name for name in os.listdir(HERE) if name.endswith(ext))


def py_files():
    return [n for n in tool_files('.py') if n not in BENCH_FILES]


def read(name):
    with io.open(os.path.join(HERE, name), encoding='utf-8') as handle:
        return handle.read()


def tree(name):
    return ast.parse(read(name), name)


def code_only(source):
    u"""Source with every string and comment blanked, so a rule can never be
    satisfied - or tripped - by prose in a docstring."""
    out = []
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except Exception:
        return source
    lines = source.splitlines(True)
    blank = set()
    for tok in tokens:
        name = tokenize.tok_name.get(tok.type, '')
        if name in ('STRING', 'COMMENT', 'FSTRING_START', 'FSTRING_MIDDLE', 'FSTRING_END'):
            for row in range(tok.start[0], tok.end[0] + 1):
                blank.add((row, tok.start if row == tok.start[0] else (row, 0),
                           tok.end if row == tok.end[0] else (row, 10 ** 6)))
    chars = [list(line) for line in lines]
    for row, start, end in blank:
        line = chars[row - 1]
        lo = start[1] if start[0] == row else 0
        hi = min(end[1] if end[0] == row else len(line), len(line))
        for i in range(lo, hi):
            if line[i] not in '\r\n':
                line[i] = ' '
    for line in chars:
        out.append(''.join(line))
    return ''.join(out)


def xaml_text():
    return dict((name, read(name)) for name in tool_files('.xaml'))


def theme_keys():
    keys = set(re.findall(r'x:Key="(\w+)"', read('Theme.xaml')))
    return keys


def palette_dicts():
    found = {}
    for node in tree('pbp_palette.py').body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id in ('DARK', 'LIGHT'):
                found[node.targets[0].id] = ast.literal_eval(node.value)
    return found


def x_names():
    names = set()
    for text in xaml_text().values():
        names.update(re.findall(r'x:Name="(\w+)"', text))
    return names


# ============================================================
# rules
# ============================================================

RULES = []


def rule(fn):
    RULES.append(fn)
    return fn


@rule
def xaml_parses():
    problems = []
    for name in tool_files('.xaml'):
        try:
            xml.dom.minidom.parse(os.path.join(HERE, name))
        except Exception as error:
            problems.append('{0}: {1}'.format(name, error))
    return problems


# ============================================================
# WPF members: what each element in our layouts really has
# ============================================================
# XamlReader.Load throws "Cannot set unknown member X.Y" for an attribute
# the element's type does not have - 1.0.0 shipped FontFamily on a Border
# and died at load. An XML parse cannot see it, so this table holds WPF's
# actual members for every element the layouts use. An element missing
# from the table fails the rule, so the table has to grow with the layouts.

_FE = set('''Width Height MinWidth MinHeight MaxWidth MaxHeight Margin
HorizontalAlignment VerticalAlignment Visibility Opacity OpacityMask Tag
ToolTip Cursor Focusable IsEnabled IsHitTestVisible SnapsToDevicePixels
UseLayoutRounding DataContext Style ContextMenu FlowDirection ClipToBounds
LayoutTransform RenderTransform RenderTransformOrigin Name FocusVisualStyle
OverridesDefaultStyle Resources Triggers InputBindings CommandBindings
AllowDrop Effect Clip Language ForceCursor IsManipulationEnabled
IsMouseOver IsFocused IsKeyboardFocused IsKeyboardFocusWithin IsVisible
IsLoaded IsMouseCaptured'''.split())
_PANEL = _FE | set('Background IsItemsHost Children'.split())
_SHAPE = _FE | set('''Fill Stroke StrokeThickness Stretch StrokeLineJoin
StrokeStartLineCap StrokeEndLineCap StrokeDashArray StrokeDashOffset
StrokeMiterLimit'''.split())
_TEXT = set('Foreground FontFamily FontSize FontWeight FontStyle FontStretch'.split())
_CONTROL = _FE | _TEXT | set('''Background BorderBrush BorderThickness Padding
HorizontalContentAlignment VerticalContentAlignment Template IsTabStop
TabIndex'''.split())
_CONTENT = _CONTROL | set('Content ContentTemplate ContentStringFormat'.split())
_BUTTONBASE = _CONTENT | set('Command CommandParameter CommandTarget ClickMode IsPressed'.split())
_TOGGLE = _BUTTONBASE | set('IsChecked IsThreeState'.split())
_ITEMS = _CONTROL | set('''ItemsSource ItemTemplate ItemContainerStyle ItemsPanel
DisplayMemberPath Items AlternationCount'''.split())
_SELECTOR = _ITEMS | set('SelectedIndex SelectedItem SelectedValue SelectedValuePath IsSynchronizedWithCurrentItem'.split())

WPF_MEMBERS = {
    'Border': _FE | set('Background BorderBrush BorderThickness CornerRadius Padding Child'.split()),
    'Grid': _PANEL | set('ColumnDefinitions RowDefinitions ShowGridLines'.split()),
    'StackPanel': _PANEL | set('Orientation'.split()),
    'WrapPanel': _PANEL | set('Orientation ItemWidth ItemHeight'.split()),
    'DockPanel': _PANEL | set('LastChildFill'.split()),
    'Canvas': _PANEL,
    'UniformGrid': _PANEL | set('Rows Columns FirstColumn'.split()),
    'Viewbox': _FE | set('Child Stretch StretchDirection'.split()),
    'Image': _FE | set('Source Stretch StretchDirection'.split()),
    'Path': _SHAPE | set(['Data']),
    'Ellipse': _SHAPE,
    'Rectangle': _SHAPE | set('RadiusX RadiusY'.split()),
    'TextBlock': _FE | _TEXT | set('''Text Background Padding TextWrapping TextTrimming
        TextAlignment LineHeight Inlines TextDecorations'''.split()),
    'Button': _BUTTONBASE | set('IsDefault IsCancel'.split()),
    'RepeatButton': _BUTTONBASE | set('Delay Interval'.split()),
    'RadioButton': _TOGGLE | set(['GroupName']),
    'CheckBox': _TOGGLE,
    'TextBox': _CONTROL | set('''Text TextWrapping AcceptsReturn AcceptsTab MaxLength
        CaretBrush SelectionBrush IsReadOnly TextAlignment MaxLines MinLines
        HorizontalScrollBarVisibility VerticalScrollBarVisibility'''.split()),
    'ListBox': _SELECTOR | set(['SelectionMode']),
    'ScrollViewer': _CONTENT | set('''HorizontalScrollBarVisibility VerticalScrollBarVisibility
        CanContentScroll'''.split()),
    'ScrollBar': _CONTROL | set('Orientation Minimum Maximum Value ViewportSize'.split()),
    # ContentPresenter's members, plus scrolling (it hosts a ScrollViewer's content)
    'ScrollContentPresenter': _FE | set('''Content ContentTemplate ContentSource RecognizesAccessKey
        CanContentScroll CanHorizontallyScroll CanVerticallyScroll'''.split()),
    'Thumb': _CONTROL,
    'Track': _FE | set('''IsDirectionReversed Orientation Minimum Maximum Value ViewportSize
        DecreaseRepeatButton IncreaseRepeatButton Thumb'''.split()),
    'Separator': _CONTROL,
    'ToolTip': _CONTENT | set('Placement PlacementTarget HasDropShadow IsOpen'.split()),
    'ContextMenu': _ITEMS | set('Placement PlacementTarget HasDropShadow IsOpen'.split()),
    'MenuItem': _ITEMS | set('''Header HeaderTemplate Icon InputGestureText IsCheckable
        IsChecked Command CommandParameter IsHighlighted IsSubmenuOpen'''.split()),
    'ListBoxItem': _CONTENT | set(['IsSelected']),
    'ContentPresenter': _FE | set('''Content ContentSource ContentTemplate RecognizesAccessKey
        ContentStringFormat'''.split()),
    'ItemsPresenter': _FE,
    'Window': _CONTENT | set('''Title SizeToContent WindowStyle AllowsTransparency ResizeMode
        ShowInTaskbar WindowStartupLocation Topmost Icon Left Top WindowState
        ShowActivated'''.split()),
    'DropShadowEffect': set('BlurRadius ShadowDepth Opacity Color Direction RenderingBias'.split()),
    'LinearGradientBrush': set('StartPoint EndPoint GradientStops Opacity MappingMode SpreadMethod'.split()),
    'GradientStop': set('Color Offset'.split()),
    'Popup': _FE | set('''IsOpen Placement PlacementTarget HorizontalOffset VerticalOffset
        AllowsTransparency Child StaysOpen PopupAnimation'''.split()),
    'ColumnDefinition': set('Width MinWidth MaxWidth SharedSizeGroup'.split()),
    'RowDefinition': set('Height MinHeight MaxHeight SharedSizeGroup'.split()),
}
# Elements that describe rather than draw - their attributes are checked
# elsewhere (Setter, Trigger) or carry no members worth checking.
STRUCTURAL = set('''ResourceDictionary Style ControlTemplate DataTemplate Setter
Trigger DataTrigger MultiTrigger Condition'''.split())
ATTACHED_OWNERS = set('''Grid Canvas DockPanel TextOptions TextBlock TextElement
ScrollViewer VirtualizingStackPanel VirtualizingPanel KeyboardNavigation
ToolTipService ContextMenuService Panel Validation RenderOptions'''.split())


def _local(name):
    return name.split('}')[-1]


@rule
def xaml_members_known():
    problems = []
    for name in tool_files('.xaml'):
        root = ET.parse(os.path.join(HERE, name)).getroot()
        parents = {}
        for parent in root.iter():
            for child in parent:
                parents[child] = parent
        for element in root.iter():
            tag = _local(element.tag)
            if '.' in tag:
                continue
            if tag not in WPF_MEMBERS and tag not in STRUCTURAL:
                problems.append('{0}: <{1}> is not in WPF_MEMBERS - add its real members'.format(name, tag))
                continue
            for attr in element.attrib:
                if attr.startswith('{'):
                    continue
                if '.' in attr:
                    owner = attr.split('.')[0]
                    if owner not in ATTACHED_OWNERS:
                        problems.append('{0}: <{1} {2}> - {3} is not a known attached-property owner'.format(
                            name, tag, attr, owner))
                    continue
                if tag in STRUCTURAL:
                    continue
                if attr not in WPF_MEMBERS[tag]:
                    problems.append("{0}: <{1} {2}=...> - {1} has no member {2}; XamlReader.Load "
                                    "throws 'Cannot set unknown member'".format(name, tag, attr))
        # Setters and Triggers: the property must exist on what they target,
        # judged by the NEAREST enclosing Style or ControlTemplate - a Style
        # nested inside a template targets its own type, not the template's.
        def nearest(element):
            node = parents.get(element)
            while node is not None and _local(node.tag) not in ('Style', 'ControlTemplate'):
                node = parents.get(node)
            return node
        named_in = {}
        for inner in root.iter():
            inner_tag = _local(inner.tag)
            if inner_tag not in ('Setter', 'Trigger'):
                continue
            prop = inner.attrib.get('Property', '')
            if not prop or '.' in prop:
                continue
            owner = nearest(inner)
            if owner is None:
                continue
            target_type = owner.attrib.get('TargetType', '')
            if inner_tag == 'Setter' and inner.attrib.get('TargetName'):
                if owner not in named_in:
                    names = {}
                    for item in owner.iter():
                        key = item.attrib.get('{http://schemas.microsoft.com/winfx/2006/xaml}Name')
                        if key:
                            names[key] = _local(item.tag)
                    named_in[owner] = names
                target = named_in[owner].get(inner.attrib['TargetName'])
            else:
                target = target_type
            members = WPF_MEMBERS.get(target)
            if members is not None and prop not in members:
                problems.append('{0}: {1} Property="{2}" on {3}, which has no such member'.format(
                    name, inner_tag, prop, target))
    return problems


# Controls whose system template draws its own chrome - most visibly a white
# disabled background - whatever Background is set to. Each must reach a
# Theme.xaml style that replaces the Template.
SYSTEM_CHROME = set('''ListBox ListBoxItem Button RepeatButton RadioButton CheckBox
TextBox ScrollBar Thumb ToolTip ContextMenu MenuItem Separator ComboBox
ComboBoxItem ScrollViewer'''.split())
# ScrollViewer's system template is plain (two bars and a presenter) and
# picks up the themed ScrollBar style, so it does not need replacing.
CHROME_OK_UNTEMPLATED = set(['ScrollViewer'])


def theme_styles():
    u"""{key or ('implicit', type): (target type, has a Template setter)}"""
    styles = {}
    x_key = '{http://schemas.microsoft.com/winfx/2006/xaml}Key'
    for style in ET.parse(os.path.join(HERE, 'Theme.xaml')).getroot().iter():
        if _local(style.tag) != 'Style':
            continue
        target = style.attrib.get('TargetType', '')
        templated = any(_local(s.tag) == 'Setter' and s.attrib.get('Property') == 'Template'
                        for s in style.iter())
        key = style.attrib.get(x_key) or ('implicit', target)
        styles[key] = (target, templated)
    return styles


@rule
def templated_controls():
    styles = theme_styles()
    problems = []
    for key, (target, templated) in styles.items():
        if target in SYSTEM_CHROME and target not in CHROME_OK_UNTEMPLATED and not templated:
            problems.append('Theme.xaml style {0} ({1}) sets no Template - the system look shows '
                            'through (a white box when disabled)'.format(key, target))
    for name in tool_files('.xaml'):
        if name == 'Theme.xaml':
            continue
        for element in ET.parse(os.path.join(HERE, name)).getroot().iter():
            tag = _local(element.tag)
            if tag not in SYSTEM_CHROME or tag in CHROME_OK_UNTEMPLATED:
                continue
            match = re.match(r'\{DynamicResource\s+(\w+)\}', element.attrib.get('Style', ''))
            if match:
                found = styles.get(match.group(1))
                if found is None or not found[1]:
                    problems.append('{0}: <{1} Style={2}> - that style does not replace the Template'.format(
                        name, tag, match.group(1)))
            elif not styles.get(('implicit', tag), ('', False))[1]:
                problems.append('{0}: <{1} x:Name="{2}"> has no Style and Theme.xaml has no templated '
                                'implicit {1} style - it renders with the Windows look'.format(
                                    name, tag, element.attrib.get(
                                        '{http://schemas.microsoft.com/winfx/2006/xaml}Name', '?')))
    for name in py_files():
        for node in ast.walk(tree(name)):
            if isinstance(node, ast.Call) and getattr(node.func, 'id', getattr(node.func, 'attr', '')) \
                    == 'set_style' and len(node.args) >= 2:
                arg = node.args[1]
                keys = [arg.value] if isinstance(arg, ast.Constant) else [
                    n.value for n in (getattr(arg, 'body', None), getattr(arg, 'orelse', None))
                    if isinstance(n, ast.Constant)]
                for key in keys:
                    found = styles.get(key)
                    if found and found[0] in SYSTEM_CHROME and not found[1] \
                            and found[0] not in CHROME_OK_UNTEMPLATED:
                        problems.append('{0}:{1}: set_style {2} - style replaces no Template'.format(
                            name, node.lineno, key))
    return problems


@rule
def no_static_resource():
    return ['{0}: StaticResource - Theme.xaml is merged after the layout is parsed'.format(n)
            for n, t in xaml_text().items() if 'StaticResource' in t]


@rule
def dynamic_keys_defined():
    known = theme_keys() | set(palette_dicts().get('DARK', {}))
    problems = []
    for name, text in xaml_text().items():
        for key in re.findall(r'\{DynamicResource\s+(\w+)\}', text):
            if key not in known:
                problems.append('{0}: DynamicResource {1} is defined nowhere'.format(name, key))
    return problems


@rule
def style_keys_defined():
    u"""Every key handed to set_style / SetResourceReference exists - a style
    in Theme.xaml or a palette brush (SetResourceReference takes both)."""
    keys = theme_keys() | set(palette_dicts().get('DARK', {}))
    problems = []
    for name in py_files():
        for node in ast.walk(tree(name)):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            called = func.attr if isinstance(func, ast.Attribute) else getattr(func, 'id', '')
            if called not in ('set_style', 'SetResourceReference') or len(node.args) < 2:
                continue
            arg = node.args[1]
            values = []
            if isinstance(arg, ast.Constant):
                values = [arg.value]
            elif isinstance(arg, ast.IfExp):
                values = [n.value for n in (arg.body, arg.orelse) if isinstance(n, ast.Constant)]
            for value in values:
                if isinstance(value, str) and value not in keys:
                    problems.append('{0}:{1}: resource key {2} not in Theme.xaml or the palette'.format(
                        name, node.lineno, value))
    return problems


@rule
def palettes_match():
    found = palette_dicts()
    dark, light = set(found.get('DARK', {})), set(found.get('LIGHT', {}))
    problems = []
    if dark != light:
        problems.append('palettes differ: {0}'.format(sorted(dark ^ light)))
    return problems


@rule
def find_names_exist():
    names = x_names()
    problems = []
    pattern = re.compile(r"(?:find\(\s*[\w.]+\s*,|FindName\()\s*u?['\"](\w+)['\"]")
    for name in py_files():
        for match in pattern.finditer(read(name)):
            if match.group(1) not in names:
                problems.append('{0}: no x:Name {1} in any layout'.format(name, match.group(1)))
    return problems


@rule
def brace_placeholders():
    problems = []
    for name in tool_files('.xaml'):
        for element in ET.parse(os.path.join(HERE, name)).iter():
            for attr, value in element.attrib.items():
                if not value.startswith('{') or value.startswith('{}'):
                    continue
                match = re.match(r'\{([\w:]+)', value)
                if not match or match.group(1) not in MARKUP:
                    problems.append('{0}: {1}="{2}" reads as a markup extension; escape with {{}}'.format(
                        name, attr.split('}')[-1], value))
    return problems


@rule
def no_baseline_alignment():
    return ['{0}: VerticalAlignment="Baseline" kills XamlReader.Load silently'.format(n)
            for n, t in xaml_text().items() if 'VerticalAlignment="Baseline"' in t]


@rule
def ironpython_syntax():
    u"""Python IronPython 2.7 rejects, or that means something else there."""
    problems = []
    for name in py_files() + ['startup_fragment.txt']:
        path = os.path.normpath(os.path.join(HERE, name))
        if not os.path.isfile(path):
            continue
        with io.open(path, encoding='utf-8') as handle:
            source = handle.read()
        label = os.path.basename(path)
        try:
            for tok in tokenize.generate_tokens(io.StringIO(source).readline):
                kind = tokenize.tok_name.get(tok.type, '')
                if kind == 'FSTRING_START' or (kind == 'STRING' and re.match(r'(?i)^[rbu]*f', tok.string)):
                    problems.append('{0}:{1}: f-string'.format(label, tok.start[0]))
                if kind == 'STRING' and re.match(r'(?i)^ur', tok.string):
                    problems.append('{0}:{1}: ur prefix is invalid on Python 3'.format(label, tok.start[0]))
                if kind == 'NAME' and tok.string in ('nonlocal', 'async', 'await'):
                    problems.append('{0}:{1}: {2}'.format(label, tok.start[0], tok.string))
                if kind == 'OP' and tok.string == ':=':
                    problems.append('{0}:{1}: walrus'.format(label, tok.start[0]))
        except tokenize.TokenError as error:
            problems.append('{0}: {1}'.format(label, error))
        code = code_only(source)
        for number, line in enumerate(code.splitlines(), 1):
            if re.match(r'\s*print\s+[^(\s=]', line):
                problems.append('{0}:{1}: print statement'.format(label, number))
            if re.match(r'\s*except\s+[\w.]+\s*,\s*\w+\s*:', line):
                problems.append('{0}:{1}: except X, e'.format(label, number))
            if 'yield from' in line:
                problems.append('{0}:{1}: yield from'.format(label, number))
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = node.args
                if node.returns is not None or args.kwonlyargs or any(
                        a.annotation is not None for a in args.args + args.kwonlyargs):
                    problems.append('{0}:{1}: annotations or keyword-only args'.format(label, node.lineno))
            if isinstance(node, ast.Raise) and node.cause is not None:
                problems.append('{0}:{1}: raise ... from'.format(label, node.lineno))
    return problems


@rule
def no_integer_value():
    return ['{0}: .IntegerValue outside pbp_compat.eid_value (removed in Revit 2026)'.format(n)
            for n in py_files() if n != 'pbp_compat.py' and '.IntegerValue' in code_only(read(n))]


@rule
def no_uri():
    problems = []
    for name in py_files():
        code = code_only(read(name))
        if re.search(r'\bUri\b', code) or 'UriSource' in code:
            problems.append('{0}: System.Uri moved assembly in Revit 2025 - load from bytes'.format(name))
    return problems


def _imports(node_tree):
    for node in ast.walk(node_tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            yield node.lineno, node.module, [a.name for a in node.names]
        elif isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name, []


@rule
def clr_first():
    problems = []
    for name in py_files():
        if name in ('pbp_clr.py', 'script.py'):
            continue
        clr_line = None
        first = None
        for line, module, names in _imports(tree(name)):
            if module == 'pbp_clr' and clr_line is None:
                clr_line = line
            if module.split('.')[0] in ('System', 'Autodesk') and first is None:
                first = line
        if first is not None and (clr_line is None or clr_line > first):
            problems.append('{0}: line {1} reaches .NET before pbp_clr is imported'.format(name, first))
    return problems


def referenced_assemblies():
    for node in tree('pbp_clr.py').body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], 'id', '') == '_ASSEMBLIES':
            return set(ast.literal_eval(node.value))
    return set()


@rule
def assemblies_referenced():
    referenced = referenced_assemblies()
    problems = []
    for name in py_files():
        for line, module, names in _imports(tree(name)):
            if module.split('.')[0] not in ('System', 'Autodesk'):
                continue
            if module.startswith(PRELOADED):
                continue
            needed = ASSEMBLY_FOR.get(module)
            if needed is None:
                problems.append('{0}:{1}: {2} is not in ASSEMBLY_FOR - add it'.format(name, line, module))
            elif not referenced.intersection(needed):
                problems.append('{0}:{1}: {2} needs one of {3} in pbp_clr'.format(name, line, module, needed))
    return problems


@rule
def no_duplicate_defs():
    problems = []
    for name in py_files():
        for node in ast.walk(tree(name)):
            if isinstance(node, (ast.Module, ast.ClassDef)):
                seen = set()
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.ClassDef)):
                        if child.name in seen:
                            problems.append('{0}: {1} defined twice - the second silently wins'.format(
                                name, child.name))
                        seen.add(child.name)
    return problems


@rule
def script_thin():
    source = read('script.py')
    problems = []
    if len(source.splitlines()) > 90:
        problems.append('script.py should stay a thin loader')
    if not re.search(r'^__persistentengine__\s*=\s*True', source, re.M):
        problems.append('script.py must set __persistentengine__ = True')
    if 'AddReference' in code_only(source):
        problems.append('script.py must not reference assemblies; pbp_clr does')
    title = re.search(r"^__title__\s*=\s*'([^']*)'", source, re.M)
    if not title or '\\n' in title.group(1):
        problems.append('single-line __title__ so the tool is findable in Keyboard Shortcuts')
    return problems


@rule
def version_single():
    problems = []
    version = None
    for name in py_files():
        for match in re.finditer(r'^__version__\s*=\s*u?["\']([^"\']+)', read(name), re.M):
            if name != 'pbp_version.py':
                problems.append('{0}: __version__ belongs in pbp_version.py only'.format(name))
            version = match.group(1)
    if version is None:
        problems.append('no __version__ in pbp_version.py')
    elif '## ' + version not in read('CHANGELOG.md'):
        problems.append('CHANGELOG.md has no heading for {0}'.format(version))
    return problems


@rule
def raise_checked():
    problems = []
    for name in py_files():
        for node in ast.walk(tree(name)):
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                func = node.value.func
                if isinstance(func, ast.Attribute) and func.attr == 'Raise':
                    problems.append('{0}:{1}: ExternalEvent.Raise() answer ignored'.format(name, node.lineno))
    return problems


@rule
def no_style_assign():
    problems = []
    for name in py_files():
        for node in ast.walk(tree(name)):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Attribute) and target.attr == 'Style':
                        problems.append('{0}:{1}: .Style = ... (use set_style)'.format(name, node.lineno))
    return problems


@rule
def theme_none_test():
    u"""UITheme.Dark is 0: the read must be tested with `is not None`."""
    for node in ast.walk(tree('pbp_theme.py')):
        if isinstance(node, ast.FunctionDef) and node.name == 'read_revit_theme':
            problems = []
            compared = False
            for inner in ast.walk(node):
                test = getattr(inner, 'test', None)
                if isinstance(inner, (ast.If, ast.IfExp, ast.While)):
                    bare = test.operand if isinstance(test, ast.UnaryOp) else test
                    if isinstance(bare, ast.Name) and bare.id == 'value':
                        problems.append('pbp_theme: truthiness test on the theme value')
                if isinstance(inner, ast.BoolOp):
                    for value in inner.values:
                        if isinstance(value, ast.Name) and value.id == 'value':
                            problems.append('pbp_theme: and/or on the theme value')
                if isinstance(inner, ast.Compare) and isinstance(inner.left, ast.Name) \
                        and inner.left.id == 'value' and isinstance(inner.ops[0], ast.IsNot):
                    compared = True
            if not compared:
                problems.append('pbp_theme: read_revit_theme never tests `value is not None`')
            return problems
    return ['pbp_theme: read_revit_theme is missing']


@rule
def revit_imports_versioned():
    problems = []
    for name in py_files():
        module_tree = tree(name)
        guarded = set()
        for node in ast.walk(module_tree):
            if isinstance(node, ast.Try):
                for inner in node.body:
                    for sub in ast.walk(inner):
                        guarded.add(id(sub))
        for node in ast.walk(module_tree):
            if not (isinstance(node, ast.ImportFrom) and node.module
                    and node.module.startswith('Autodesk')):
                continue
            names = set(a.name for a in node.names)
            risky = names.intersection(VERSIONED_NAMES)
            if not risky:
                continue
            if id(node) not in guarded:
                problems.append('{0}:{1}: {2} imported outside a try - not in every Revit 2021-2027'.format(
                    name, node.lineno, sorted(risky)))
            elif len(names) > 1:
                problems.append('{0}:{1}: {2} grouped with other names - one missing name fails them all'.format(
                    name, node.lineno, sorted(risky)))
    return problems


@rule
def int_precision():
    u"""IronPython refuses '{0:.2f}'.format(15): wrap precision arguments in float()."""
    problems = []
    for name in py_files():
        for node in ast.walk(tree(name)):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == 'format' and isinstance(node.func.value, ast.Constant)
                    and isinstance(node.func.value.value, str)):
                continue
            auto = 0
            for literal, field, spec, conv in string.Formatter().parse(node.func.value.value):
                if field is None:
                    continue
                index = int(field) if field.isdigit() else (auto if field == '' else None)
                if field == '':
                    auto += 1
                if spec and re.search(r'\.\d+[fe%]', spec) and index is not None and index < len(node.args):
                    arg = node.args[index]
                    if not (isinstance(arg, ast.Call) and getattr(arg.func, 'id', '') == 'float'):
                        problems.append('{0}:{1}: precision format without float()'.format(name, node.lineno))
    return problems


@rule
def handlers_safe():
    problems = []
    for name in HANDLER_MODULES:
        for node in ast.walk(tree(name)):
            # .NET events are capitalised (Click, TextChanged); counters are not.
            if isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Add) \
                    and isinstance(node.target, ast.Attribute) and node.target.attr[:1].isupper():
                value = node.value
                if not (isinstance(value, ast.Call) and getattr(value.func, 'id', '') == 'safe'):
                    problems.append('{0}:{1}: WPF handler not wrapped in safe() - it would fail silently'.format(
                        name, node.lineno))
    return problems


@rule
def self_attrs_assigned():
    u"""Nothing reads self.X that no line of the class ever sets."""
    problems = []
    for name in py_files():
        for cls in [n for n in ast.walk(tree(name)) if isinstance(n, ast.ClassDef)]:
            known = set()
            for item in cls.body:
                if isinstance(item, (ast.FunctionDef, ast.ClassDef)):
                    known.add(item.name)
                elif isinstance(item, ast.Assign):
                    known.update(t.id for t in item.targets if isinstance(t, ast.Name))
            reads = []
            for node in ast.walk(cls):
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
                        and node.value.id == 'self':
                    if isinstance(node.ctx, ast.Store):
                        known.add(node.attr)
                    else:
                        reads.append((node.lineno, node.attr))
            if cls.bases:
                base_names = [getattr(b, 'id', '') for b in cls.bases]
                if any(b not in ('object',) for b in base_names):
                    known.update(['Execute', 'GetName'])
            for line, attr in reads:
                if attr not in known:
                    problems.append('{0}:{1}: {2}.{3} is read but never set'.format(name, line, cls.name, attr))
    return problems


@rule
def startup_fragment_wrapped():
    if not os.path.isfile(FRAGMENT):
        return []
    with io.open(FRAGMENT, encoding='utf-8') as handle:
        source = handle.read()
    problems = []
    for node in ast.parse(source).body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue
        if isinstance(node, ast.Try) and any(
                h.type is not None and getattr(h.type, 'id', '') == 'Exception' for h in node.handlers):
            continue
        problems.append('fragment line {0}: outside the try - an error there stops the whole extension'.format(
            node.lineno))
    for name in ('__uiControlledApplication__', '__revit__', 'register('):
        if name not in source:
            problems.append('fragment never offers {0}'.format(name))
    return problems


@rule
def shared_files():
    u"""The delivery must not carry a shared, singular file of the extension."""
    if not os.path.isfile(FRAGMENT):
        return []
    problems = []
    for root, folders, files in os.walk(EXT_ROOT):
        rel = os.path.relpath(root, EXT_ROOT)
        if rel == '.' and 'startup.py' in files:
            problems.append('startup.py in the delivery would overwrite the extension\'s own')
        if rel == '.' and 'hooks' in folders:
            problems.append('a hooks folder in the delivery')
        if rel.replace('\\', '/') == 'lib/revobim' and '__init__.py' in files:
            problems.append('lib/revobim/__init__.py must never ship')
        if (root.endswith('.panel') or root.endswith('.pulldown')) and 'bundle.yaml' in files:
            problems.append('{0}/bundle.yaml would reset an existing panel'.format(rel))
    return problems


# ============================================================
# runner and selftest
# ============================================================

def run(quiet=False):
    failed = []
    for fn in RULES:
        try:
            problems = fn()
        except Exception as error:
            problems = ['rule crashed: {0!r}'.format(error)]
        if problems:
            failed.append(fn.__name__)
        if not quiet:
            print('  {0:<5} {1}'.format('FAIL' if problems else 'ok', fn.__name__))
            for problem in problems[:8]:
                print('          ' + problem)
    if not quiet:
        print('{0} rules, {1} failed'.format(len(RULES), len(failed)))
    return failed


TOOL = 'RevoBIM PY.extension/RevoBIM PY.tab/Management.panel/Project Browser Pro.pushbutton/'
FRAG = TOOL + 'startup_fragment.txt'

# (path in the delivery, anchor or None to create the file, replacement, rule)
BREAKAGES = [
    (TOOL + 'Browser.xaml', '<!-- ====', '<!-- -- ====', 'xaml_parses'),
    (TOOL + 'Browser.xaml', '{DynamicResource BgBrush}', '{StaticResource BgBrush}', 'no_static_resource'),
    (TOOL + 'Browser.xaml', 'Style="{DynamicResource BrowserList}" ', '', 'templated_controls'),
    (TOOL + 'Browser.xaml', 'TextElement.FontFamily="Segoe UI" TextElement.FontSize="12"',
     'FontFamily="Segoe UI" FontSize="12"', 'xaml_members_known'),
    (TOOL + 'Browser.xaml', '{DynamicResource MutedBrush}', '{DynamicResource MutedBrushX}', 'dynamic_keys_defined'),
    (TOOL + 'pbp_browser.py', "u'PbpMenuItem')", "u'PbpMenuItemX')", 'style_keys_defined'),
    (TOOL + 'pbp_palette.py', "    u'TreeLineBrush': u'#DADAE0',\n", '', 'palettes_match'),
    (TOOL + 'pbp_browser.py', "find(r, u'ZoomText')", "find(r, u'ZoomTextX')", 'find_names_exist'),
    (TOOL + 'Browser.xaml', 'Tag="Search" Height="28"', 'Tag="{Search}" Height="28"', 'brace_placeholders'),
    # Anchored on any centred element, not one layout's exact margin, so a
    # redesign of the header cannot disarm it (1.0.5's did).
    (TOOL + 'Browser.xaml', 'VerticalAlignment="Center"', 'VerticalAlignment="Baseline"',
     'no_baseline_alignment'),
    (TOOL + 'pbp_tree.py', "return u'r:' + tab", "return f'r:{tab}'", 'ironpython_syntax'),
    (TOOL + 'pbp_store.py', 'value = eid_value(leaf.eid)', 'value = leaf.eid.IntegerValue', 'no_integer_value'),
    (TOOL + 'pbp_ui.py', 'image.StreamSource = MemoryStream(File.ReadAllBytes(path))',
     'image.UriSource = None', 'no_uri'),
    (TOOL + 'pbp_runner.py', 'import pbp_clr  # noqa: F401\nfrom System import Action\n',
     'from System import Action\nimport pbp_clr  # noqa: F401\n', 'clr_first'),
    (TOOL + 'pbp_clr.py', "'System.Data', ", '', 'assemblies_referenced'),
    (TOOL + 'pbp_browser.py', '    def _selected_keys(self):',
     '    def _status(self, text):\n        pass\n\n    def _selected_keys(self):', 'no_duplicate_defs'),
    (TOOL + 'script.py', '__persistentengine__ = True', '__persistentengine__ = False', 'script_thin'),
    # Anchored on the live version, so a version bump cannot disarm it.
    (TOOL + 'CHANGELOG.md', '## ' + re.search(r'__version__\s*=\s*u?["\']([^"\']+)',
                                              read('pbp_version.py')).group(1),
     '## 0.0.0', 'version_single'),
    (TOOL + 'pbp_runner.py', '            return to_text(self.event.Raise())',
     "            self.event.Raise()\n            return u'Accepted'", 'raise_checked'),
    (TOOL + 'pbp_ui.py', '    element.SetResourceReference(FrameworkElement.StyleProperty, key)',
     '    element.Style = element.TryFindResource(key)', 'no_style_assign'),
    (TOOL + 'pbp_theme.py', '        if value is not None:\n', '        if value:\n', 'theme_none_test'),
    (TOOL + 'pbp_theme.py', 'from System.Windows.Media import SolidColorBrush, ColorConverter\n',
     'from System.Windows.Media import SolidColorBrush, ColorConverter\n'
     'from Autodesk.Revit.UI import UIThemeManager\n', 'revit_imports_versioned'),
    (TOOL + 'pbp_revit.py', "u'{0:.3f}'.format(float(param.AsDouble()))",
     "u'{0:.3f}'.format(param.AsDouble())", 'int_precision'),
    (TOOL + 'pbp_browser.py', "self.search.TextChanged += safe(self._search_changed, u'search')",
     'self.search.TextChanged += self._search_changed', 'handlers_safe'),
    (TOOL + 'pbp_browser.py', "self._status(u'Opened {0}.'.format(result[u'opened']))",
     "self._stauts(u'Opened {0}.'.format(result[u'opened']))", 'self_attrs_assigned'),
    (FRAG, 'try:\n    import os as _pbp_os', 'import os as _pbp_os\ntry:\n    import os as _pbp_os',
     'startup_fragment_wrapped'),
    ('RevoBIM PY.extension/startup.py', None, '# a tool shipping its own startup.py\n', 'shared_files'),
]


def selftest():
    caught = 0
    problems = []
    for relpath, anchor, replacement, expected in BREAKAGES:
        workdir = tempfile.mkdtemp(prefix='pbp_ic_')
        shutil.copytree(EXT_ROOT, os.path.join(workdir, os.path.basename(EXT_ROOT)),
                        ignore=shutil.ignore_patterns('__pycache__'))
        path = os.path.join(workdir, relpath)
        if anchor is None:
            with io.open(path, 'w', encoding='utf-8') as handle:
                handle.write(replacement)
        else:
            with io.open(path, encoding='utf-8') as handle:
                source = handle.read()
            if anchor not in source:
                problems.append('{0}: anchor {1!r} not found - the breakage has disarmed itself'.format(
                    relpath, anchor[:50]))
                shutil.rmtree(workdir, ignore_errors=True)
                continue
            with io.open(path, 'w', encoding='utf-8') as handle:
                handle.write(source.replace(anchor, replacement, 1))
        result = subprocess.run([sys.executable, 'import_check.py', '--names'],
                                cwd=os.path.join(workdir, TOOL), capture_output=True, text=True)
        failed = result.stdout.split()
        if expected in failed:
            caught += 1
            print('  caught  {0:<26} {1}'.format(expected, os.path.basename(relpath)))
        else:
            problems.append('{0} did not catch its breakage in {1} (failed: {2})'.format(
                expected, os.path.basename(relpath), failed))
        shutil.rmtree(workdir, ignore_errors=True)
    for problem in problems:
        print('  MISSED  ' + problem)
    print('{0} breakages, {1} caught'.format(len(BREAKAGES), caught))
    missing = set(fn.__name__ for fn in RULES) - set(b[3] for b in BREAKAGES)
    if missing:
        print('  rules with no breakage to prove them: ' + ', '.join(sorted(missing)))
    return not problems and not missing


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        clean = run(quiet=True)
        if clean:
            print('the rules do not pass on the real tool: ' + ', '.join(clean))
            sys.exit(1)
        sys.exit(0 if selftest() else 1)
    if '--names' in sys.argv:
        print(' '.join(run(quiet=True)))
        sys.exit(0)
    sys.exit(1 if run() else 0)
