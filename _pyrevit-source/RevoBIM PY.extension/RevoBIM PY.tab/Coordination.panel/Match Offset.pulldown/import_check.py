# -*- coding: utf-8 -*-
"""RevoBIM Match Offset - bench check.

Runs under plain CPython from this folder:

    python import_check.py
    python import_check.py --selftest

The first runs every rule against the shipped files. The second breaks each
rule on purpose and confirms the rule catches its own breakage, because a rule
nobody has tested is a rule that does not work - two of the rules here only
started working after the selftest showed they were inert.

What these rules exist to catch is the class of failure that shows up in Revit
as a blank white pyRevit window with no traceback in it: the script died
before any of it ran, so there was no runtime left to raise.
"""

import ast
import os
import re
import shutil
import subprocess
import sys
import symtable
import tempfile
import types
import xml.dom.minidom

HERE = os.path.dirname(os.path.abspath(__file__))

MODULES = (
    'mo_clr.py', 'mo_core.py', 'mo_shortcuts.py', 'mo_model.py',
    'mo_run.py', 'mo_theme.py', 'mo_ui.py', 'mo_debug.py', 'mo_launch.py',
    'mos_geom.py', 'mos_model.py', 'mos_run.py',
    'settings_window.py', 'results_window.py', 'debug_window.py',
)

# The geometry module is the whole rule set for the slope tool, and it is
# only bench testable because it knows nothing about Revit or WPF.
PURE_MODULES = ('mos_geom.py',)
LAYOUTS = ('MatchOffsetSettings.xaml', 'MatchOffsetResults.xaml',
           'MatchOffsetMessage.xaml', 'MatchOffsetDebug.xaml')
THEME = 'Theme.xaml'
BUTTONS = ('Match Offset Bottom.pushbutton', 'Match Offset Middle.pushbutton',
           'Match Offset Top.pushbutton', 'Match Offset Slope.pushbutton',
           'Match Offset Settings.pushbutton')

# Which assembly has to have been referenced before a namespace exists. This
# is the table that turns "ImportError at module load" into a bench failure.
ASSEMBLY_FOR = {
    'System.Windows': 'PresentationFramework',
    'System.Windows.Controls': 'PresentationFramework',
    'System.Windows.Controls.Primitives': 'PresentationFramework',
    'System.Windows.Markup': 'PresentationFramework',
    'System.Windows.Input': 'PresentationCore',
    'System.Windows.Media': 'PresentationCore',
    'System.Windows.Media.Imaging': 'PresentationCore',
    'System.IO': 'mscorlib',
    'System.Collections.Generic': 'mscorlib',
}

# Every .NET and Revit name the tool imports, in the namespace the real API
# puts it in. An import from the wrong namespace fails here rather than in
# Revit.
NAMESPACES = {
    'System.IO': ('MemoryStream', 'File', 'FileStream', 'FileMode',
                  'FileAccess'),
    'System.Collections.Generic': ('List',),
    'System.Windows': ('WindowStartupLocation', 'HorizontalAlignment',
                       'VerticalAlignment', 'Visibility', 'Thickness',
                       'CornerRadius', 'TextWrapping', 'SizeToContent',
                       'GridLength', 'GridUnitType', 'Clipboard'),
    'System.Windows.Controls': ('Grid', 'Border', 'StackPanel', 'TextBlock',
                                'CheckBox', 'ComboBox', 'TextBox', 'Button',
                                'Orientation', 'ColumnDefinition',
                                'RowDefinition', 'ScrollViewer'),
    'System.Windows.Controls.Primitives': ('Thumb', 'Popup', 'ToggleButton'),
    'System.Windows.Input': ('Cursors',),
    'System.Windows.Markup': ('XamlReader',),
    'System.Windows.Media': ('SolidColorBrush', 'ColorConverter', 'Brushes'),
    'System.Windows.Media.Imaging': ('BitmapImage', 'BitmapCacheOption'),
    'Autodesk.Revit.DB': (
        'BuiltInCategory', 'BuiltInParameter', 'CheckoutStatus', 'ElementId',
        'ElementTransformUtils', 'FilteredElementCollector', 'Level',
        'LocationCurve', 'LocationPoint', 'Line', 'Transaction',
        'TransactionGroup', 'WorksharingUtils', 'XYZ', 'IFailuresPreprocessor',
        'FailureProcessingResult', 'Element', 'SubTransaction',
        'RoutingPreferenceRuleGroupType', 'Connector', 'Transform',
        'FailureSeverity', 'FailureMessage', 'StorageType', 'Parameter',
        'FamilySymbol', 'FamilyInstance', 'Options', 'Solid', 'PlanarFace',
        'Face', 'GeometryInstance', 'GeometryElement', 'ViewDetailLevel',
        'Transform'),
    'Autodesk.Revit.DB.Fabrication': ('FabricationPart',
                                      'FabricationHostedInfo'),
    'Autodesk.Revit.DB.Structure': ('StructuralType',),
    'Autodesk.Revit.DB.Plumbing': ('Pipe', 'PipeType', 'PlumbingUtils',
                                   'FlowDirectionType'),
    'Autodesk.Revit.UI': ('TaskDialog', 'TaskDialogCommonButtons',
                          'TaskDialogResult', 'UIThemeManager',
                          'RevitCommandId', 'PostableCommand'),
    'Autodesk.Revit.UI.Selection': ('ISelectionFilter', 'ObjectType',
                                    'PickBoxStyle'),
    'Autodesk.Revit.Exceptions': ('OperationCanceledException',),
}

# Names the real API does NOT put where a tired author might look for them.
# Anything imported from a namespace that is in NAMESPACES but does not list
# the name is a failure; this list is only here to make the message useful.
COMMON_MISPLACEMENTS = {
    'Uri': 'System (and it moved assemblies in Revit 2025 - do not use it)',
    'Room': 'Autodesk.Revit.DB.Architecture, not Autodesk.Revit.DB',
    'RoutingPreferenceRuleGroupType': 'Autodesk.Revit.DB, not .Plumbing',
}

PALETTE_KEYS = None   # filled in from mo_theme, read as text not imported


# ======================================================================
# corpus
# ======================================================================

def read(path):
    handle = open(path, 'rb')
    try:
        raw = handle.read()
    finally:
        handle.close()
    try:
        return raw.decode('utf-8')
    except Exception:
        return raw.decode('latin-1', 'replace')


def load_corpus():
    corpus = {}
    for name in MODULES + LAYOUTS + (THEME,):
        corpus[name] = read(os.path.join(HERE, name))
    for folder in BUTTONS:
        for leaf in ('script.py', 'bundle.yaml'):
            key = folder + '/' + leaf
            corpus[key] = read(os.path.join(HERE, folder, leaf))
    corpus['bundle.yaml'] = read(os.path.join(HERE, 'bundle.yaml'))
    return corpus


def py_files(corpus):
    return dict([(k, v) for k, v in corpus.items() if k.endswith('.py')])


def module_files(corpus):
    return dict([(k, v) for k, v in corpus.items() if k in MODULES])


def layout_files(corpus):
    return dict([(k, v) for k, v in corpus.items() if k in LAYOUTS])


# ======================================================================
# code_only - comments and string bodies blanked, spacing preserved
# ======================================================================

def code_only(text):
    """Blank out comments and string bodies, character for character.

    Character for character matters: joining tokens without their spacing
    turns "from System import Uri" into "fromSystemimportUri" and every rule
    that looks for it silently stops working, which is a rule that has failed
    without telling anybody.
    """
    out = list(text)
    index = 0
    length = len(text)
    while index < length:
        ch = text[index]
        if ch == '#':
            stop = text.find('\n', index)
            if stop < 0:
                stop = length
            for position in range(index, stop):
                out[position] = ' '
            index = stop
            continue
        if ch in ('"', "'"):
            triple = text[index:index + 3] == ch * 3
            token = ch * 3 if triple else ch
            cursor = index + len(token)
            while cursor < length:
                if text[cursor] == '\\':
                    cursor += 2
                    continue
                if text[cursor:cursor + len(token)] == token:
                    cursor += len(token)
                    break
                cursor += 1
            else:
                cursor = length
            for position in range(index, min(cursor, length)):
                if out[position] != '\n':
                    out[position] = ' '
            index = cursor
            continue
        index += 1
    return ''.join(out)


# ======================================================================
# rules
# ======================================================================

def rule_xaml_parses(corpus):
    """Every .xaml parses as XML.

    XamlReader.Load throwing is the quiet one: no traceback, just a blank
    window. A run of hyphens in a comment banner is the way it has happened
    before, because XML forbids -- inside a comment.
    """
    bad = []
    for name in LAYOUTS + (THEME,):
        try:
            xml.dom.minidom.parseString(corpus[name].encode('utf-8'))
        except Exception as err:
            bad.append('{0}: {1}'.format(name, err))
    return bad


def rule_no_hyphen_banners(corpus):
    """Comment banners are drawn with =, never with runs of hyphens."""
    bad = []
    for name in LAYOUTS + (THEME,):
        for match in re.finditer(r'<!--(.*?)-->', corpus[name], re.S):
            if '--' in match.group(1):
                bad.append('{0}: a comment contains --'.format(name))
    return bad


def rule_no_static_resource(corpus):
    """No StaticResource in a layout.

    Theme.xaml is merged in after XamlReader has parsed the layout, so a
    StaticResource is resolved when the dictionary is not there yet.
    """
    bad = []
    for name, text in layout_files(corpus).items():
        if 'StaticResource' in text.replace('DynamicResource', ''):
            bad.append('{0}: uses StaticResource'.format(name))
    return bad


def theme_keys(corpus):
    return set(re.findall(r'x:Key\s*=\s*"([^"]+)"', corpus[THEME]))


def rule_dynamic_keys_exist(corpus):
    """Every DynamicResource key a layout asks for exists in Theme.xaml."""
    known = theme_keys(corpus)
    bad = []
    for name, text in list(layout_files(corpus).items()) + [(THEME, corpus[THEME])]:
        for key in re.findall(r'\{DynamicResource\s+([A-Za-z0-9_]+)\}', text):
            if key not in known:
                bad.append('{0}: DynamicResource {1} is not in Theme.xaml'
                           .format(name, key))
    return sorted(set(bad))


def rule_style_targettype(corpus):
    """No Style={DynamicResource K} on an element K's TargetType rejects.

    WPF raises that when the style is applied rather than when it is parsed,
    so it also surfaces as a dead window rather than an error.
    """
    targets = {}
    for match in re.finditer(
            r'<Style\s+x:Key\s*=\s*"([^"]+)"\s+TargetType\s*=\s*"([^"]+)"',
            corpus[THEME]):
        targets[match.group(1)] = match.group(2)
    bad = []
    for name, text in layout_files(corpus).items():
        for match in re.finditer(
                r'<(\w+)\b[^>]*?Style\s*=\s*"\{DynamicResource\s+(\w+)\}"',
                text, re.S):
            element, key = match.group(1), match.group(2)
            wanted = targets.get(key)
            if wanted and wanted != element:
                bad.append('{0}: <{1}> uses {2}, whose TargetType is {3}'
                           .format(name, element, key, wanted))
    return bad


def rule_findname_has_xname(corpus):
    """Every FindName('X') has a matching x:Name="X" in some layout.

    The rule matches the aliased form too. It only caught literal
    FindName("X") calls once, and the code aliases it as
    self.find = self.window.FindName, so it was doing nothing at all.
    """
    names = set()
    for name in LAYOUTS:
        names |= set(re.findall(r'x:Name\s*=\s*"([^"]+)"', corpus[name]))
    bad = []
    for name, text in module_files(corpus).items():
        code = code_only(text)
        wanted = set()
        for match in re.finditer(r"FindName\(\s*['\"]([^'\"]+)['\"]\s*\)",
                                 text):
            if code[match.start():match.start() + 8] == 'FindName':
                wanted.add(match.group(1))
        for match in re.finditer(r"self\.find\(\s*['\"]([^'\"]+)['\"]\s*\)",
                                 text):
            wanted.add(match.group(1))
        for wanted_name in sorted(wanted):
            if wanted_name not in names:
                bad.append('{0}: FindName({1}) has no x:Name'.format(
                    name, wanted_name))
    return bad


def rule_setresourcereference_keys(corpus):
    """Every SetResourceReference key exists in Theme.xaml."""
    known = theme_keys(corpus)
    bad = []
    for name, text in module_files(corpus).items():
        for match in re.finditer(
                r"SetResourceReference\([^,]+,\s*['\"]([^'\"]+)['\"]", text):
            if match.group(1) not in known:
                bad.append('{0}: SetResourceReference to {1}, which '
                           'Theme.xaml does not define'.format(
                               name, match.group(1)))
    return bad


def rule_palettes_match(corpus):
    """Both palettes carry the same keys, and Theme.xaml defines them all."""
    text = corpus['mo_theme.py']
    bad = []
    blocks = {}
    for label in ('DARK_PALETTE', 'LIGHT_PALETTE'):
        match = re.search(label + r'\s*=\s*\{(.*?)\n\}', text, re.S)
        if not match:
            return ['mo_theme.py: {0} not found'.format(label)]
        blocks[label] = set(re.findall(r'u"([A-Za-z0-9_]+)"\s*:',
                                       match.group(1)))
    if blocks['DARK_PALETTE'] != blocks['LIGHT_PALETTE']:
        difference = blocks['DARK_PALETTE'] ^ blocks['LIGHT_PALETTE']
        bad.append('palettes differ: {0}'.format(', '.join(sorted(difference))))
    known = theme_keys(corpus)
    for key in sorted(blocks['DARK_PALETTE']):
        if key not in known:
            bad.append('palette key {0} has no brush in Theme.xaml'.format(key))
    return bad


def rule_no_fstrings(corpus):
    """No f-strings: IronPython 2.7 does not have them."""
    bad = []
    for name, text in py_files(corpus).items():
        for match in re.finditer(r"""\bf(['"])""", text):
            line = text.count('\n', 0, match.start()) + 1
            bad.append('{0}:{1} f-string'.format(name, line))
    return bad


def rule_no_print(corpus):
    """No print statements or calls in shipped code.

    The bench files are exempt: they are the one thing that has to talk.
    """
    bad = []
    for name, text in py_files(corpus).items():
        code = code_only(text)
        for match in re.finditer(r'(?<![\w.])print\s*[\(\s]', code):
            line = code.count('\n', 0, match.start()) + 1
            bad.append('{0}:{1} print'.format(name, line))
    return bad


def rule_no_bare_integervalue(corpus):
    """No bare .IntegerValue - it was removed in Revit 2026.

    Allowed only inside the guarded eid_value helper, which prefers .Value.
    """
    bad = []
    for name, text in py_files(corpus).items():
        code = code_only(text)
        inside = False
        for number, line in enumerate(code.splitlines(), start=1):
            if re.match(r'\s*def\s+eid_value\b', line):
                inside = True
                continue
            if inside and line.strip() and not line.startswith((' ', '\t')):
                inside = False
            if '.IntegerValue' in line and not inside:
                bad.append('{0}:{1} bare .IntegerValue'.format(name, number))
    return bad


def rule_no_system_uri(corpus):
    """No System.Uri - it moved assemblies and throws on Revit 2025+."""
    bad = []
    for name, text in py_files(corpus).items():
        code = code_only(text)
        if re.search(r'from\s+System\s+import\s+[^\n]*\bUri\b', code) or \
                re.search(r'\bSystem\.Uri\b', code) or \
                re.search(r'\bUriSource\b', code):
            bad.append('{0}: uses System.Uri'.format(name))
    return bad


def rule_ascii_only(corpus):
    """No non-ASCII anywhere in the .py files.

    An em dash in a plain string literal fails under IronPython 2.7, and the
    cheapest way not to have that argument is not to have the character.
    """
    bad = []
    for name, text in py_files(corpus).items():
        for number, line in enumerate(text.splitlines(), start=1):
            for ch in line:
                if ord(ch) > 127:
                    bad.append('{0}:{1} non-ASCII {2!r}'.format(
                        name, number, ch))
                    break
    return bad


def rule_clr_first(corpus):
    """Every module reaching into System.* or Autodesk.* imports mo_clr first.

    Import order inside a file is load order, and the reference has to win.
    This is the single most likely way to break any tool in this extension
    and the least obvious to diagnose.
    """
    bad = []
    for name, text in module_files(corpus).items():
        if name == 'mo_clr.py':
            continue
        tree = ast.parse(text, name)
        clr_line = None
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == 'mo_clr':
                        clr_line = node.lineno if clr_line is None else min(
                            clr_line, node.lineno)
        first_dotnet = None
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split('.')[0]
                if root in ('System', 'Autodesk'):
                    if first_dotnet is None or node.lineno < first_dotnet:
                        first_dotnet = node.lineno
        if first_dotnet is None:
            continue
        if clr_line is None:
            bad.append('{0}: reaches into .NET without importing mo_clr'
                       .format(name))
        elif clr_line > first_dotnet:
            bad.append('{0}: imports mo_clr at line {1}, after .NET at {2}'
                       .format(name, clr_line, first_dotnet))
    return bad


def rule_assembly_table(corpus):
    """Every namespace imported is one mo_clr has referenced an assembly for."""
    referenced = set(re.findall(r"'([\w.]+)'", re.search(
        r'ASSEMBLIES\s*=\s*\((.*?)\)', corpus['mo_clr.py'], re.S).group(1)))
    referenced.add('mscorlib')
    referenced.add('System.Core')
    bad = []
    for name, text in module_files(corpus).items():
        tree = ast.parse(text, name)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                needed = ASSEMBLY_FOR.get(node.module)
                if needed and needed not in referenced:
                    bad.append('{0}: {1} needs {2}, which mo_clr does not '
                               'reference'.format(name, node.module, needed))
    return sorted(set(bad))


def rule_no_revitapi_addreference(corpus):
    """mo_clr never references RevitAPI or RevitAPIUI.

    pyRevit has already loaded them into the engine, and referencing them
    again is the one AddReference that can fail when the assembly moves.
    """
    text = corpus['mo_clr.py']
    bad = []
    for name in ('RevitAPI', 'RevitAPIUI'):
        if re.search(r"'" + name + r"'", text):
            bad.append('mo_clr.py references {0}'.format(name))
    return bad


def rule_namespaces_correct(corpus):
    """Every .NET name comes from the namespace the real API puts it in."""
    bad = []
    for name, text in module_files(corpus).items():
        tree = ast.parse(text, name)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            declared = NAMESPACES.get(node.module)
            if declared is None:
                continue
            for alias in node.names:
                if alias.name not in declared:
                    hint = COMMON_MISPLACEMENTS.get(alias.name, '')
                    bad.append('{0}: {1} is not in {2}{3}'.format(
                        name, alias.name, node.module,
                        ' - it is in ' + hint if hint else ''))
    return bad


def rule_no_duplicate_definitions(corpus):
    """No top level name defined twice.

    Python silently keeps the last of two, so a stale copy sits there
    visible and dead.
    """
    bad = []
    for name, text in py_files(corpus).items():
        tree = ast.parse(text, name)
        seen = {}
        for node in tree.body:
            label = None
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                label = node.name
            if label is None:
                continue
            if label in seen:
                bad.append('{0}: {1} defined twice, lines {2} and {3}'.format(
                    name, label, seen[label], node.lineno))
            seen[label] = node.lineno
    return bad


def rule_globals_exist(corpus):
    """Every global a function reaches for exists in its module.

    symtable, not a scan: this is the rule that catches a function deleted by
    a block rewrite while its callers stayed behind.
    """
    import builtins as builtin_module
    builtin_names = set(dir(builtin_module))
    bad = []
    for name, text in module_files(corpus).items():
        table = symtable.symtable(text, name, 'exec')
        module_names = set([s.get_name() for s in table.get_symbols()])
        stack = list(table.get_children())
        while stack:
            child = stack.pop()
            stack.extend(child.get_children())
            if child.get_type() != 'function':
                continue
            for symbol in child.get_symbols():
                if not symbol.is_global() or symbol.is_assigned():
                    continue
                label = symbol.get_name()
                if label in module_names or label in builtin_names:
                    continue
                bad.append('{0}: {1}() reaches for {2}, which does not exist'
                           .format(name, child.get_name(), label))
    return sorted(set(bad))


def rule_call_arity(corpus):
    """A call to a function in the same module passes a count it will take."""
    bad = []
    for name, text in module_files(corpus).items():
        tree = ast.parse(text, name)
        signatures = {}
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                args = node.args
                required = len(args.args) - len(args.defaults)
                ceiling = None if args.vararg else len(args.args)
                signatures[node.name] = (required, ceiling,
                                         [a.arg for a in args.args],
                                         args.kwarg is not None)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Name):
                continue
            signature = signatures.get(node.func.id)
            if signature is None:
                continue
            required, ceiling, arg_names, takes_kwargs = signature
            if any([isinstance(a, ast.Starred) for a in node.args]):
                continue
            given = len(node.args)
            named = [k.arg for k in node.keywords if k.arg]
            if any([k.arg is None for k in node.keywords]):
                continue
            if given + len(named) < required:
                bad.append('{0}:{1} {2}() wants {3}, given {4}'.format(
                    name, node.lineno, node.func.id, required,
                    given + len(named)))
            if ceiling is not None and given > ceiling:
                bad.append('{0}:{1} {2}() takes {3}, given {4}'.format(
                    name, node.lineno, node.func.id, ceiling, given))
            if not takes_kwargs:
                for keyword in named:
                    if keyword not in arg_names:
                        bad.append('{0}:{1} {2}() has no argument {3}'.format(
                            name, node.lineno, node.func.id, keyword))
    return bad


def rule_cross_module_names(corpus):
    """mod.name references resolve to something that module defines."""
    exported = {}
    for name, text in module_files(corpus).items():
        tree = ast.parse(text, name)
        names = set()
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        names.add(target.id)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    names.add(alias.asname or alias.name.split('.')[0])
        exported[name[:-3]] = names
    bad = []
    for name, text in module_files(corpus).items():
        tree = ast.parse(text, name)
        # The local name, which "import mos_geom as geom" makes different
        # from the module name. Keying the lookup on the local name alone
        # meant every aliased import resolved against nothing and the rule
        # reported the whole module as missing - loudly, which is the only
        # reason it was noticed.
        imported = {}
        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in exported:
                        imported[alias.asname or alias.name] = alias.name
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            if not isinstance(node.value, ast.Name):
                continue
            target = node.value.id
            if target not in imported:
                continue
            if node.attr.startswith('__'):
                continue
            if node.attr not in exported.get(imported[target], set()):
                bad.append('{0}:{1} {2}.{3} does not exist'.format(
                    name, node.lineno, target, node.attr))
    return sorted(set(bad))


def rule_thin_loaders(corpus):
    """script.py stays a thin loader.

    A tool that is one big script has no runtime left to report its own
    import failure, which is the blank white window with nothing in it.
    """
    allowed = set(['os', 'sys', 'traceback', 'mo_launch'])
    bad = []
    for folder in BUTTONS:
        key = folder + '/script.py'
        tree = ast.parse(corpus[key], key)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name not in allowed:
                        bad.append('{0}: imports {1}'.format(key, alias.name))
            if isinstance(node, ast.ImportFrom) and node.module:
                if not node.module.startswith('Autodesk.Revit.UI'):
                    bad.append('{0}: imports from {1}'.format(
                        key, node.module))
    return bad


def rule_button_titles(corpus):
    """Ribbon names are unique, prefixed RevoBIM, single line, and agree
    with the folder they sit in.

    Single line so Revit's Keyboard Shortcuts dialog lists them; prefixed so
    they can be found in that list at all, because plain names clash with
    other addins; and matching the folder because pyRevit names a ribbon item
    after its folder when a bundle does not override it.
    """
    bad = []
    titles = []
    for folder in BUTTONS:
        text = corpus[folder + '/bundle.yaml']
        match = re.search(r'^title:\s*(.+)$', text, re.M)
        if not match:
            bad.append('{0}: bundle.yaml has no title'.format(folder))
            continue
        title = match.group(1).strip()
        titles.append(title)
        if not title.startswith('RevoBIM '):
            bad.append('{0}: title "{1}" is not prefixed RevoBIM'.format(
                folder, title))
        if '\\n' in title or len(title.splitlines()) > 1:
            bad.append('{0}: title is not a single line'.format(folder))
        wanted = 'RevoBIM ' + folder.replace('.pushbutton', '')
        if title != wanted:
            bad.append('{0}: title "{1}" does not match the folder'.format(
                folder, title))
        script = corpus[folder + '/script.py']
        declared = re.search(r'__title__\s*=\s*"([^"]+)"', script)
        if declared and declared.group(1) != title:
            bad.append('{0}: __title__ "{1}" disagrees with bundle.yaml'
                       .format(folder, declared.group(1)))
    if len(set(titles)) != len(titles):
        bad.append('two buttons share a ribbon name')
    return bad


def rule_no_shared_files(corpus):
    """The delivery ships none of the extension's shared, singular files.

    startup.py, the hooks and lib\\revobim\\__init__.py are the extension's.
    A tool that shipped its own would silently overwrite whatever the last
    tool put there, and nothing would fail: the feature that lived in the
    overwritten file would simply stop existing.
    """
    bad = []
    root = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
    forbidden = (
        os.path.join(root, 'RevoBIM PY.extension', 'startup.py'),
        os.path.join(root, 'RevoBIM PY.extension', 'lib', 'revobim',
                     '__init__.py'),
        os.path.join(root, 'RevoBIM PY.extension', 'hooks'),
        os.path.join(HERE, '..', 'bundle.yaml'),
    )
    for path in forbidden:
        if os.path.exists(path):
            bad.append('the delivery ships {0}'.format(
                os.path.normpath(path)))
    return bad


def rule_settings_split_once(corpus):
    """Settings are split on the first = only.

    A value is allowed to contain = signs, and a loader that splits on every
    one drops everything after the second.
    """
    text = corpus['mo_core.py']
    if 'split(u"=", 1)' not in text:
        return ['mo_core.py: settings are not split on the first = only']
    return []


def rule_code_only_keeps_spacing(corpus):
    """code_only preserves token spacing.

    Proving the helper, not the code: a version that joined tokens without
    their spacing would turn every rule above it into a rule that passes
    because it can no longer see anything.
    """
    sample = 'from System import Uri  # a comment\nx = "a string"\n'
    stripped = code_only(sample)
    bad = []
    if len(stripped) != len(sample):
        bad.append('code_only changed the length of the text')
    if 'from System import Uri' not in stripped:
        bad.append('code_only ate a line of real code')
    if 'a string' in stripped or 'a comment' in stripped:
        bad.append('code_only left a string or comment body behind')
    if stripped.count('\n') != sample.count('\n'):
        bad.append('code_only changed the line count')
    return bad


PER_ELEMENT_FUNCTIONS = ('apply_to', 'take_datum')
SETTINGS_CALLS = ('parse_number', 'is_on', 'enabled_categories',
                  'load_settings', 'parse_settings')


def rule_settings_resolved_once(corpus):
    """Nothing that runs per element re-reads the settings.

    Every value in the settings file is a string. Parsing them again for
    every click produces the same answer it did the click before, and the
    answer is already sitting on the RunConfig.
    """
    tree = ast.parse(corpus['mo_run.py'], 'mo_run.py')
    bad = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name not in PER_ELEMENT_FUNCTIONS:
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name):
                if inner.func.id in SETTINGS_CALLS:
                    bad.append('mo_run.py:{0} {1}() parses settings inside '
                               '{2}()'.format(inner.lineno, inner.func.id,
                                              node.name))
    return bad


def rule_log_is_flushed(corpus):
    """The buffered log is written in a finally, not on the happy path.

    Buffering the log to save a file handle per element is only safe if a
    run that dies still leaves its lines behind.
    """
    tree = ast.parse(corpus['mo_run.py'], 'mo_run.py')
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or node.name != 'run':
            continue
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Try):
                continue
            for statement in inner.finalbody:
                for call in ast.walk(statement):
                    if isinstance(call, ast.Call) and \
                            isinstance(call.func, ast.Name) and \
                            call.func.id == 'flush_log':
                        return []
        return ['mo_run.py: run() does not flush the log in a finally']
    return ['mo_run.py: run() not found']


def rule_no_wrapping_in_a_horizontal_stack(corpus):
    """No wrapped text inside a StackPanel built horizontally in code.

    A horizontal StackPanel measures its children with infinite width, so a
    TextBlock inside one never wraps however TextWrapping is set - the text
    simply runs off the edge and the end of the sentence is lost. It went
    unnoticed because the layout looks right until a message is long enough
    to matter, and the messages that are long enough to matter are the ones
    explaining why something failed.
    """
    bad = []
    for name, text in module_files(corpus).items():
        tree = ast.parse(text, name)
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            horizontal = False
            wrapping = None
            for inner in ast.walk(node):
                if isinstance(inner, ast.Attribute) and \
                        inner.attr == 'Horizontal':
                    horizontal = True
                if isinstance(inner, ast.Assign):
                    for target in inner.targets:
                        if isinstance(target, ast.Attribute) and \
                                target.attr == 'TextWrapping':
                            wrapping = inner.lineno
            if horizontal and wrapping is not None:
                bad.append('{0}:{1} {2}() wraps text inside a horizontal '
                           'StackPanel'.format(name, wrapping, node.name))
    return bad


def rule_geometry_is_pure(corpus):
    """The geometry module imports nothing but the standard library.

    Every rule the slope tool works to lives in mos_geom, and the only
    reason 150 of the bench checks can exercise it is that it has no Revit
    and no WPF in it. One convenient import would take that away and
    nothing would fail until the next bug had nowhere to be caught.
    """
    allowed = set(['math'])
    bad = []
    for name in PURE_MODULES:
        tree = ast.parse(corpus[name], name)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name not in allowed:
                        bad.append('{0}: imports {1}'.format(name, alias.name))
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split('.')[0] not in allowed:
                    bad.append('{0}: imports from {1}'.format(
                        name, node.module))
    return bad


def rule_modules_import(corpus):
    """Every module loads against a stub Revit and .NET API.

    The stub declares each name in the namespace the real API puts it in, so
    a mis-namespaced import fails here rather than as a blank window.
    """
    folder = tempfile.mkdtemp(prefix='mo_bench_')
    try:
        for name, text in corpus.items():
            if '/' in name:
                continue
            handle = open(os.path.join(folder, name), 'wb')
            try:
                handle.write(text.encode('utf-8'))
            finally:
                handle.close()
        script = os.path.join(folder, '_probe.py')
        handle = open(script, 'wb')
        try:
            handle.write(PROBE.encode('utf-8'))
        finally:
            handle.close()
        process = subprocess.Popen(
            [sys.executable, script], cwd=folder,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        output = process.communicate()[0].decode('utf-8', 'replace')
        if process.returncode != 0:
            return [line for line in output.strip().splitlines() if line][-6:]
        return []
    finally:
        shutil.rmtree(folder, ignore_errors=True)


PROBE = '''
import sys, types
NAMESPACES = %r
MODULES = %r


class Anything(type):
    def __getattr__(cls, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return type(str(name), (object,), {})


def make(path, names):
    module = types.ModuleType(path)
    for name in names:
        setattr(module, name, Anything(str(name), (object,), {}))
    sys.modules[path] = module
    parts = path.split('.')
    for depth in range(1, len(parts)):
        parent = '.'.join(parts[:depth])
        if parent not in sys.modules:
            sys.modules[parent] = types.ModuleType(parent)
    if len(parts) > 1:
        setattr(sys.modules['.'.join(parts[:-1])], parts[-1], module)
    return module


for path, names in NAMESPACES.items():
    make(path, names)

clr = types.ModuleType('clr')
clr.AddReference = lambda name: None
sys.modules['clr'] = clr

for name in MODULES:
    __import__(name[:-3])
''' % (NAMESPACES, MODULES)


# ======================================================================
# the register
# ======================================================================

RULES = (
    ('xaml parses as XML', rule_xaml_parses),
    ('no -- inside an XML comment', rule_no_hyphen_banners),
    ('no StaticResource in a layout', rule_no_static_resource),
    ('every DynamicResource key exists', rule_dynamic_keys_exist),
    ('no style applied to a mismatched TargetType', rule_style_targettype),
    ('every FindName has an x:Name', rule_findname_has_xname),
    ('every SetResourceReference key exists', rule_setresourcereference_keys),
    ('both palettes carry the same keys', rule_palettes_match),
    ('no f-strings', rule_no_fstrings),
    ('no print', rule_no_print),
    ('no bare .IntegerValue', rule_no_bare_integervalue),
    ('no System.Uri', rule_no_system_uri),
    ('no non-ASCII in .py', rule_ascii_only),
    ('mo_clr is imported before any .NET name', rule_clr_first),
    ('every namespace has its assembly referenced', rule_assembly_table),
    ('no AddReference for RevitAPI or RevitAPIUI',
     rule_no_revitapi_addreference),
    ('every .NET name comes from the right namespace', rule_namespaces_correct),
    ('no duplicate top level definitions', rule_no_duplicate_definitions),
    ('every global a function reaches for exists', rule_globals_exist),
    ('calls pass an argument count the function takes', rule_call_arity),
    ('cross module names resolve', rule_cross_module_names),
    ('script.py stays a thin loader', rule_thin_loaders),
    ('ribbon names are unique, prefixed and single line', rule_button_titles),
    ('no shared extension file is shipped', rule_no_shared_files),
    ('settings split on the first = only', rule_settings_split_once),
    ('code_only preserves token spacing', rule_code_only_keeps_spacing),
    ('settings are resolved once, not per element',
     rule_settings_resolved_once),
    ('the log is flushed in a finally', rule_log_is_flushed),
    ('the geometry module has no Revit in it', rule_geometry_is_pure),
    ('no wrapped text in a horizontal StackPanel',
     rule_no_wrapping_in_a_horizontal_stack),
    ('every module loads against the stub API', rule_modules_import),
)


# ======================================================================
# deliberate breakages, one per rule
# ======================================================================

def _swap(corpus, name, old, new, count=1):
    broken = dict(corpus)
    if old not in broken[name]:
        raise AssertionError('breakage anchor missing in ' + name)
    broken[name] = broken[name].replace(old, new, count)
    return broken


BREAKAGES = {
    'xaml parses as XML':
        lambda c: _swap(c, 'MatchOffsetResults.xaml', '</Window>', '</Windo>'),
    'no -- inside an XML comment':
        lambda c: _swap(c, 'Theme.xaml', '<!-- Text ',
                        '<!-- ---- Text ---- '),
    'no StaticResource in a layout':
        lambda c: _swap(c, 'MatchOffsetSettings.xaml',
                        '{DynamicResource ChipButton}',
                        '{StaticResource ChipButton}'),
    'every DynamicResource key exists':
        lambda c: _swap(c, 'MatchOffsetResults.xaml',
                        '{DynamicResource MutedText}',
                        '{DynamicResource NoSuchKey}'),
    'no style applied to a mismatched TargetType':
        lambda c: _swap(c, 'MatchOffsetMessage.xaml',
                        'x:Name="MessageBody" Text="" TextWrapping="Wrap"',
                        'x:Name="MessageBody" Text="" '
                        'Style="{DynamicResource PrimaryButton}" '
                        'TextWrapping="Wrap"'),
    'every FindName has an x:Name':
        lambda c: _swap(c, 'results_window.py', "FindName('SummaryLine')",
                        "FindName('SummaryLineTypo')"),
    'every SetResourceReference key exists':
        lambda c: _swap(c, 'results_window.py',
                        "SetResourceReference(Border.BackgroundProperty, "
                        "'CardBrush')",
                        "SetResourceReference(Border.BackgroundProperty, "
                        "'CardBrushh')"),
    'both palettes carry the same keys':
        lambda c: _swap(c, 'mo_theme.py', 'u"HoverBrush": u"#E4E4EA",', ''),
    'no f-strings':
        lambda c: _swap(c, 'mo_core.py', 'return u""',
                        'return f"{0}"', 1),
    'no print':
        lambda c: _swap(c, 'mo_core.py', '    return value_mm\n',
                        '    print(value_mm)\n    return value_mm\n', 1),
    'no bare .IntegerValue':
        lambda c: _swap(c, 'mo_run.py', 'eid_value(element.Category.Id)',
                        'element.Category.Id.IntegerValue'),
    'no System.Uri':
        lambda c: _swap(c, 'mo_ui.py', 'from System.IO import MemoryStream',
                        'from System import Uri\nfrom System.IO import '
                        'MemoryStream'),
    'no non-ASCII in .py':
        lambda c: _swap(c, 'mo_core.py', 'RevoBIM Match Offset',
                        'RevoBIM \u2014 Match Offset'),
    'mo_clr is imported before any .NET name':
        lambda c: _swap(c, 'mo_theme.py', 'import mo_clr  # noqa: F401\n\n',
                        ''),
    'every namespace has its assembly referenced':
        lambda c: _swap(c, 'mo_clr.py', "    'PresentationCore',\n", ''),
    'no AddReference for RevitAPI or RevitAPIUI':
        lambda c: _swap(c, 'mo_clr.py', "    'System.Core',",
                        "    'System.Core',\n    'RevitAPI',"),
    'every .NET name comes from the right namespace':
        # The real one: RoutingPreferenceRuleGroupType lives in
        # Autodesk.Revit.DB, not in Autodesk.Revit.DB.Plumbing, and asking
        # the wrong namespace for it is a blank white window.
        lambda c: _swap(c, 'mos_model.py',
                        'from Autodesk.Revit.DB.Plumbing import Pipe, '
                        'PlumbingUtils',
                        'from Autodesk.Revit.DB.Plumbing import (Pipe, '
                        'PlumbingUtils, RoutingPreferenceRuleGroupType)'),
    'no duplicate top level definitions':
        lambda c: _swap(c, 'mo_theme.py', 'def keys_match():',
                        'def revit_theme():\n    return DARK\n\n\n'
                        'def keys_match():'),
    'every global a function reaches for exists':
        lambda c: _swap(c, 'mo_theme.py', 'return PALETTES.get(',
                        'return PALETTE_TABLE.get('),
    'calls pass an argument count the function takes':
        lambda c: _swap(c, 'mo_core.py', 'round_value(raw_mm, step_mm, mode)',
                        'round_value(raw_mm, step_mm, mode, datum, anchor)'),
    'cross module names resolve':
        lambda c: _swap(c, 'mo_run.py', 'mo_model.describe(element)',
                        'mo_model.describe_it(element)'),
    'script.py stays a thin loader':
        lambda c: _swap(c, 'Match Offset Top.pushbutton/script.py',
                        'import traceback',
                        'import traceback\nimport mo_model'),
    'ribbon names are unique, prefixed and single line':
        lambda c: _swap(c, 'Match Offset Middle.pushbutton/bundle.yaml',
                        'title: RevoBIM Match Offset Middle',
                        'title: Match Offset Middle'),
    'no shared extension file is shipped': None,      # see below
    'settings split on the first = only':
        lambda c: _swap(c, 'mo_core.py', 'line.split(u"=", 1)',
                        'line.split(u"=")'),
    'code_only preserves token spacing': None,        # see below
    'settings are resolved once, not per element':
        lambda c: _swap(c, 'mo_run.py',
                        '    name = mo_model.describe(element)',
                        '    name = mo_model.describe(element)\n'
                        '    step = parse_number(config.settings.get('
                        'u"round_step_mm"), 0.0)'),
    'the log is flushed in a finally':
        lambda c: _swap(c, 'mo_run.py', '        flush_log()\n', ''),
    'the geometry module has no Revit in it':
        lambda c: _swap(c, 'mos_geom.py', 'import math',
                        'import math\nfrom Autodesk.Revit.DB import XYZ'),
    'no wrapped text in a horizontal StackPanel':
        lambda c: _swap(c, 'results_window.py', '    inner = Grid()',
                        '    inner = StackPanel()\n'
                        '    inner.Orientation = Orientation.Horizontal'),
    'every module loads against the stub API':
        lambda c: _swap(c, 'mo_model.py',
                        'from Autodesk.Revit.UI.Selection import '
                        'ISelectionFilter',
                        'from Autodesk.Revit.DB import ISelectionFilter'),
}


def _selftest_shared_files():
    """Prove the shared-file rule by planting one of the files it forbids."""
    path = os.path.abspath(os.path.join(HERE, '..', 'bundle.yaml'))
    handle = open(path, 'wb')
    try:
        handle.write(b'title: Coordination\n')
    finally:
        handle.close()
    try:
        return bool(rule_no_shared_files({}))
    finally:
        os.remove(path)


def _selftest_code_only():
    """Prove the code_only rule by breaking code_only itself."""
    global code_only
    original = code_only

    def joined(text):
        return ''.join(text.split())
    code_only = joined
    try:
        return bool(rule_code_only_keeps_spacing({}))
    finally:
        code_only = original


SPECIAL_SELFTESTS = {
    'no shared extension file is shipped': _selftest_shared_files,
    'code_only preserves token spacing': _selftest_code_only,
}


# ======================================================================
# running
# ======================================================================

def run_rules(corpus):
    failures = []
    for label, rule in RULES:
        found = rule(corpus)
        if found:
            failures.append((label, found))
    return failures


def selftest():
    corpus = load_corpus()
    report = []
    inert = []
    for label, rule in RULES:
        special = SPECIAL_SELFTESTS.get(label)
        if special is not None:
            caught = special()
        else:
            breakage = BREAKAGES.get(label)
            if breakage is None:
                inert.append(label)
                continue
            caught = bool(rule(breakage(corpus)))
        report.append((label, caught))
        if not caught:
            inert.append(label)
    return report, inert


def main(argv):
    corpus = load_corpus()
    if '--selftest' in argv:
        report, inert = selftest()
        lines = ['RevoBIM Match Offset - bench selftest', '']
        for label, caught in report:
            lines.append('  {0}  {1}'.format('caught ' if caught else 'INERT  ',
                                             label))
        lines.append('')
        if inert:
            lines.append('{0} rule(s) did not catch their own breakage: {1}'
                         .format(len(inert), ', '.join(inert)))
            sys.stdout.write('\n'.join(lines) + '\n')
            return 1
        lines.append('all {0} rules caught their own breakage'.format(
            len(report)))
        sys.stdout.write('\n'.join(lines) + '\n')
        return 0

    failures = run_rules(corpus)
    lines = ['RevoBIM Match Offset - bench check', '']
    for label, _rule in RULES:
        found = dict(failures).get(label)
        lines.append('  {0}  {1}'.format('FAIL' if found else 'ok  ', label))
        for detail in (found or [])[:8]:
            lines.append('        {0}'.format(detail))
    lines.append('')
    if failures:
        lines.append('{0} of {1} rules failed'.format(len(failures),
                                                      len(RULES)))
        sys.stdout.write('\n'.join(lines) + '\n')
        return 1
    lines.append('all {0} rules pass'.format(len(RULES)))
    sys.stdout.write('\n'.join(lines) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
