# -*- coding: utf-8 -*-
"""Bench check for Legend Creator.

Run it on a desktop Python 3, away from Revit, beside the tool's files:

    python import_check.py

It catches the class of bug that shows up in Revit as a blank white pyRevit
window or a button that does nothing - a mis-namespaced import, an f-string
on the IronPython 2.7 engine, a bare .IntegerValue, a FindName with no
matching x:Name, a StaticResource key nothing defines, a module that reads
the document before it was bound, or a name used and never imported.

The tool is script.py (a thin loader), the lgc_*.py modules, three layouts
and the Theme.xaml they share. Rules about code run on every module; rules
about windows run on each layout with the theme spliced in, exactly as
lgc_theme.load_window hands it to WPF.
"""

import ast
import io
import os
import re
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

SCRIPT = 'script.py'
MODULES = ['lgc_clr', 'lgc_logic', 'lgc_core', 'lgc_drawer', 'lgc_model',
           'lgc_build', 'lgc_theme', 'lgc_windows', 'lgc_report', 'lgc_app']
# Imported by the bench under plain CPython, so nothing Revit or WPF may be
# imported at their top level. lgc_clr is here because the loader imports
# it before anything else can have failed.
PURE = ['lgc_clr', 'lgc_logic', 'lgc_core', 'lgc_drawer']
LAYOUTS = ['LegendCreatorWindow.xaml', 'LegendCreatorDone.xaml',
           'LegendCreatorDebug.xaml']
THEME = 'Theme.xaml'

XAML_NS = '{http://schemas.microsoft.com/winfx/2006/xaml}'
HANDLER_ATTRS = ('Click', 'TextChanged', 'SelectionChanged', 'DropDownOpened',
                 'DropDownClosed', 'MouseLeftButtonDown', 'Checked',
                 'Unchecked', 'Loaded', 'PreviewKeyDown', 'KeyDown')

# Names the real Revit API puts in a namespace other than the obvious one.
# A name imported from the wrong namespace loads fine on the bench but throws
# at module load in Revit, so the expected home is asserted here.
NAMESPACE_HOMES = {
    'UnitTypeId': 'Autodesk.Revit.DB',
    'DisplayUnitType': 'Autodesk.Revit.DB',
    'ElementTransformUtils': 'Autodesk.Revit.DB',
    'TextNoteOptions': 'Autodesk.Revit.DB',
    'HorizontalTextAlignment': 'Autodesk.Revit.DB',
    'VerticalTextAlignment': 'Autodesk.Revit.DB',
    'ViewDuplicateOption': 'Autodesk.Revit.DB',
    'TransactionGroup': 'Autodesk.Revit.DB',
    'CopyPasteOptions': 'Autodesk.Revit.DB',
    'SketchPlane': 'Autodesk.Revit.DB',
}

failures = []
notes = []
_WHERE = {'file': None}


def fail(message):
    where = _WHERE['file']
    failures.append(u'{0}: {1}'.format(where, message) if where else message)


def read(path):
    handle = io.open(os.path.join(HERE, path), encoding='utf-8')
    try:
        return handle.read()
    finally:
        handle.close()


def exists(name):
    return os.path.isfile(os.path.join(HERE, name))


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------
def load_sources():
    """{file name: (source, tree or None)} for script.py and every module."""
    sources = {}
    for name in [SCRIPT] + [m + '.py' for m in MODULES]:
        if not exists(name):
            fail('{0} is missing'.format(name))
            continue
        source = read(name)
        try:
            tree = ast.parse(source)
        except SyntaxError as err:
            fail('{0} will not parse: {1}'.format(name, err))
            tree = None
        sources[name] = (source, tree)
    extra = sorted(n for n in os.listdir(HERE)
                   if n.startswith('lgc_') and n.endswith('.py') and
                   n[:-3] not in MODULES)
    for name in extra:
        fail('{0} is not in MODULES - nothing here would check it'
             .format(name))
    return sources


def shipped(module):
    """Import one of the tool's modules, or record why it would not load.

    Several rules read the real values - the palettes, SHRUNK, the splice -
    rather than parsing them out of text. A module broken badly enough not
    to import is reported here, once, instead of taking the bench down with
    a traceback that hides every other result.
    """
    try:
        return __import__(module)
    except Exception as err:
        message = 'could not import {0} on the bench: {1}: {2}'.format(
            module, type(err).__name__, err)
        if message not in failures:
            fail(message)
        return None


def spliced(layout):
    """The layout as WPF receives it: the shared theme in place of the
    marker, by the very function the tool uses."""
    logic = shipped('lgc_logic')
    if logic is None:
        raise ValueError('lgc_logic would not import')
    return logic.splice_theme(read(layout), read(THEME))


def functions(tree):
    """{name: node} for every function anywhere in the tree."""
    found = {}
    if tree is not None:
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                found.setdefault(node.name, node)
    return found


def body_text(source, node):
    lines = source.splitlines()
    last = max(getattr(c, 'lineno', node.lineno) for c in ast.walk(node))
    return '\n'.join(lines[node.lineno - 1:last])


# ---------------------------------------------------------------------------
# Rules carried over from the single-file tool, run on each module
# ---------------------------------------------------------------------------
KIND_REQUIRED = ['key', 'label', 'ready', 'source', 'style', 'template',
                 'categories', 'name_token', 'region_prefix', 'heading',
                 'view_name', 'swatch_h']


# The properties a re-run must write onto an element it is reusing. Dropping
# one is invisible at runtime: the element already exists, nothing throws,
# and it silently keeps whatever it had.
OVERWRITE_WRITES = [
    ('apply_region_style', ['ForegroundPatternColor', 'ForegroundPatternId',
                            'LineWeight', 'IsMasking']),
    ('apply_line_style', ['LineColor', 'SetLineWeight']),
]


# A void API call is not evidence. These functions must read the model back
# after writing, or a silent no-op reports as success.
# (function, the write, the read that must come AFTER it). A void API call is
# not evidence, and a read before the write proves nothing either - a pre-check
# such as "if not pane.IsShown()" once satisfied this rule on its own.
READBACK_REQUIRED = [
    ('open_view', r'\.ActiveView\s*=', r'ActiveView\.Id'),
    ('show_project_browser', r'\.Show\(\)', r'IsShown\(\)'),
    ('select_element', r'SetElementIds\(', r'GetElementIds\(\)'),
    ('_uia_select', r'\.Select\(\)', r'\.IsSelected'),
]


# Settings shown on every tab must be saved by every create path - the
# footer's Debug tick and the theme chip sit outside both tabs.
SHARED_SETTINGS = ['theme_mode', 'debug']


def ast_str(node):
    """The string a literal node holds, on Python 2 and 3 alike.

    ast.Str.s is deprecated from 3.12 and gone in 3.14, and ast.Constant
    does not exist on 2.7, so both are tried rather than either assumed.
    """
    value = getattr(node, 'value', None)
    if isinstance(value, str):
        return value
    if type(node).__name__ != 'Str':
        return None                   # .s only exists, undeprecated, on Str
    value = getattr(node, 's', None)
    return value if isinstance(value, str) else None


def code_only(source, tree):
    """The source with comments and docstrings blanked out.

    Rules that scan text must scan code. Several rules in this suite have in
    the past "passed" by matching an explanation of the very thing they were
    meant to forbid, so prose is removed before matching, line numbers kept.
    """
    lines = source.splitlines()
    if tree is not None:
        for node in ast.walk(tree):
            body = getattr(node, 'body', None)
            if not isinstance(body, list) or not body:
                continue
            first = body[0]
            if isinstance(first, ast.Expr) and ast_str(first.value) is not None:
                end = getattr(first, 'end_lineno', first.lineno)
                for number in range(first.lineno - 1, end):
                    lines[number] = ''
    cleaned = []
    for line in lines:
        # a '#' inside a string literal is rare enough here to accept
        index = line.find('#')
        cleaned.append(line if index < 0 else line[:index])
    return '\n'.join(cleaned)


def class_sources(source, tree):
    """(class name, its own source text) for each class in the module."""
    if tree is None:
        return []
    lines = source.splitlines()
    blocks = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        last = node.lineno
        for child in ast.walk(node):
            last = max(last, getattr(child, 'lineno', 0))
        blocks.append((node.name, '\n'.join(lines[node.lineno - 1:last])))
    return blocks


def check_no_fstrings(source, tree):
    if tree is None:
        return
    found = [n for n in ast.walk(tree)
             if n.__class__.__name__ == 'JoinedStr']
    if found:
        lines = sorted(set(getattr(n, 'lineno', 0) for n in found))
        fail('f-strings are not valid on IronPython 2.7 - lines {0}'.format(
            ', '.join(str(n) for n in lines)))


def check_no_print_statements(source):
    for number, line in enumerate(source.splitlines(), 1):
        stripped = line.strip()
        if re.match(r'^print\s', stripped) or re.match(r'^print\(', stripped):
            fail('print statement at line {0} - use the output window'.format(
                number))


def check_integervalue(source, tree):
    """.IntegerValue is gone in Revit 2026. Only eid_value may touch it.

    Checked on the AST - an actual attribute access - rather than the text,
    which also matched the word inside a string such as a probe's label.
    """
    if tree is None:
        return
    allowed = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == 'eid_value':
            for child in ast.walk(node):
                allowed.add(id(child))
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == 'IntegerValue' \
                and id(node) not in allowed:
            fail('bare .IntegerValue at line {0} - go through eid_value'
                 .format(node.lineno))


def check_no_system_uri(source):
    if re.search(r'from\s+System\s+import\s+.*\bUri\b', source) or \
            re.search(r'\bSystem\.Uri\b', source):
        fail('System.Uri fails to import on Revit 2025+ - load bytes instead')


def check_namespaces(source):
    for name, home in NAMESPACE_HOMES.items():
        pattern = r'from\s+([\w\.]+)\s+import\s+[^\n]*\b' + name + r'\b'
        for match in re.finditer(pattern, source):
            if match.group(1) != home:
                fail('{0} imported from {1}, but it lives in {2}'.format(
                    name, match.group(1), home))


def check_grid_rows(layout):
    """Children of a multi-cell Grid must not silently share a cell.

    A child with no Grid.Row defaults to row 0. Dropping the attribute from
    one child therefore stacks it on top of another with no error anywhere -
    which is how the tab content ended up drawn over the header, hiding the
    close button, the theme chip and the drag bar at once, and pushing the
    footer off the bottom.

    The test is on the row and column together: a grid of eight resize grips
    shares rows and shares columns, but no two grips share a cell.
    """
    path = os.path.join(HERE, layout)
    if not os.path.isfile(path):
        return
    root = ET.fromstring(read(path).encode('utf-8'))
    ns = '{http://schemas.microsoft.com/winfx/2006/xaml/presentation}'

    for grid in root.iter(ns + 'Grid'):
        rows = grid.find(ns + 'Grid.RowDefinitions')
        columns = grid.find(ns + 'Grid.ColumnDefinitions')
        cells = (len(rows) if rows is not None else 1) * \
                (len(columns) if columns is not None else 1)
        if cells < 2:
            continue                 # a single cell is a deliberate stack

        occupied = {}
        for child in grid:
            if child.tag.replace(ns, '').startswith('Grid.'):
                continue
            if child.get('Grid.RowSpan') or child.get('Grid.ColumnSpan'):
                continue             # a deliberate overlay, e.g. the grips
            cell = (child.get('Grid.Row', '0'), child.get('Grid.Column', '0'))
            occupied.setdefault(cell, []).append(
                child.tag.replace(ns, ''))

        for cell, names in sorted(occupied.items()):
            if len(names) > 1:
                fail('{0}: {1} elements share cell row {2} column {3} of a '
                     '{4}-cell Grid ({5}) - one is probably missing its '
                     'Grid.Row or Grid.Column'.format(
                         layout, len(names), cell[0], cell[1], cells,
                         ', '.join(names)))


def check_system_kinds(source, tree):
    """Every SYSTEM_KINDS entry must carry the full set of fields.

    A kind is read by key all over the drawing code, so a missing field is a
    KeyError partway through a run, after elements have already been made.
    """
    if tree is None:
        return
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if 'SYSTEM_KINDS' not in targets:
            continue
        if not isinstance(node.value, ast.List):
            fail('SYSTEM_KINDS is not a list')
            return
        for entry in node.value.elts:
            if not isinstance(entry, ast.Dict):
                fail('a SYSTEM_KINDS entry is not a dictionary')
                continue
            keys = set()
            for key in entry.keys:
                value = ast_str(key)
                if isinstance(value, str):
                    keys.add(value)
            name = 'an entry'
            for key, value in zip(entry.keys, entry.values):
                if ast_str(key) == 'key':
                    name = ast_str(value) or '?'
            for required in KIND_REQUIRED:
                if required not in keys:
                    fail('SYSTEM_KINDS entry "{0}" has no "{1}"'.format(
                        name, required))
        return
    fail('SYSTEM_KINDS not found')


def check_overwrite_writes(source, tree):
    if tree is None:
        return
    bodies = {}
    lines = source.splitlines()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        last = node.lineno
        for child in ast.walk(node):
            last = max(last, getattr(child, 'lineno', 0))
        bodies[node.name] = '\n'.join(lines[node.lineno - 1:last])

    for name, properties in OVERWRITE_WRITES:
        body = bodies.get(name)
        if body is None:
            fail('{0}() is missing - a re-run would not overwrite'.format(
                name))
            continue
        for prop in properties:
            # An assignment, not a mention: these functions read the current
            # value before writing, so the property name appears either way
            # and a plain substring test passes even with the write deleted.
            if prop.startswith('Set'):
                found = re.search(r'\.%s\s*\(' % prop, body)
            else:
                found = re.search(r'\.%s\s*=' % prop, body)
            if not found:
                fail('{0}() never writes {1}, so a re-run leaves it as '
                     'found'.format(name, prop))


def check_readbacks(source, tree):
    if tree is None:
        return
    code = code_only(source, tree)
    lines = code.splitlines()
    bodies = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            last = node.lineno
            for child in ast.walk(node):
                last = max(last, getattr(child, 'lineno', 0))
            bodies[node.name] = '\n'.join(lines[node.lineno - 1:last])

    for name, write, read_back in READBACK_REQUIRED:
        body = bodies.get(name)
        if body is None:
            fail('{0}() is missing'.format(name))
            continue
        written = re.search(write, body)
        if written is None:
            fail('{0}() no longer makes its write ({1})'.format(name, write))
            continue
        if not re.search(read_back, body[written.end():]):
            fail('{0}() never reads the result back after writing, so a '
                 'call that silently does nothing reports as success'
                 .format(name))


def check_status_through_say(source, tree):
    """The footer line is only written by say(), so a refusal is always in
    the warning colour and logged - a plain grey status_tb.Text was what
    made a refused Create look like nothing happening."""
    if tree is None:
        return
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name == 'say':
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.Assign):
                for target in child.targets:
                    if isinstance(target, ast.Attribute) and \
                            target.attr == 'Text' and \
                            getattr(target.value, 'attr', '') == 'status_tb':
                        fail('{0}() writes status_tb.Text directly at line '
                             '{1} - use say() or refuse()'.format(
                                 node.name, child.lineno))


def check_shared_settings(source):
    blocks = re.findall(r'saved\.update\(\{(.*?)\}\)', source, re.S)
    if len(blocks) < 2:
        fail('expected a settings save in each create path, found {0}'
             .format(len(blocks)))
    for index, block in enumerate(blocks, 1):
        for key in SHARED_SETTINGS:
            if "'{0}'".format(key) not in block:
                fail('settings save {0} of {1} does not write "{2}", so it is '
                     'lost when that tab is used'.format(index, len(blocks),
                                                         key))


def check_settings_keys(source):
    """Every DEFAULTS key must be written back somewhere, or it silently
    never persists, and every key read must have a default to fall back to."""
    block = re.search(r'DEFAULTS = \{(.*?)\n\}', source, re.S)
    if not block:
        fail('DEFAULTS dictionary not found')
        return
    keys = set(re.findall(r"'([a-z_]+)'\s*:", block.group(1)))

    written = set()
    for updater in re.finditer(r'saved\.update\(\{(.*?)\}\)', source, re.S):
        written |= set(re.findall(r"'([a-z_]+)'\s*:", updater.group(1)))
    for direct in re.finditer(r'save_settings\(\{(.*?)\}\)', source, re.S):
        written |= set(re.findall(r"'([a-z_]+)'\s*:", direct.group(1)))

    if not written:
        fail('nothing ever writes a settings dictionary')
        return
    for key in sorted(keys - written):
        fail('setting "{0}" has a default but is never saved'.format(key))

    read = set(re.findall(r"settings\.get\('([a-z_]+)'", source))
    for key in sorted(read - keys):
        fail('setting "{0}" is read but has no default'.format(key))


def check_bundle(source):
    """bundle.yaml is plain one-line `key: value` entries, and the title is a
    single line matching the script's __title__.

    pyRevit's own YAML reader copes with block scalars, but not everything
    that reads the bundle does: the RevoBIM command search read
    `title: |-` line by line, showed the tool as "|-", could not match it to
    a loaded command and reported it "not loaded". Single-line titles are
    also what Revit's Keyboard Shortcuts dialog needs.
    """
    path = os.path.join(HERE, 'bundle.yaml')
    if not os.path.isfile(path):
        fail('bundle.yaml is missing')
        return
    entries = {}
    for number, line in enumerate(read(path).splitlines(), 1):
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        if line[:1] in (' ', '\t'):
            fail('bundle.yaml line {0} is a continuation line - keep every '
                 'entry on one line'.format(number))
            continue
        if ':' not in line:
            fail('bundle.yaml line {0} is not `key: value`'.format(number))
            continue
        key, value = line.split(':', 1)
        value = value.strip()
        if value[:1] in ('|', '>'):
            fail('bundle.yaml "{0}" is a block scalar ({1}) - line-by-line '
                 'readers see only "{1}"'.format(key.strip(), value[:2]))
        entries[key.strip()] = value.strip('"\'')

    title = entries.get('title', '')
    if not title:
        fail('bundle.yaml has no title')
    match = re.search(r"^__title__\s*=\s*u?['\"](.*?)['\"]\s*$", source, re.M)
    script_title = match.group(1) if match else None
    if script_title is None:
        fail('script.py has no __title__')
    elif '\\n' in script_title:
        fail('script.py __title__ breaks over two lines - keep it on one')
    elif title and script_title != title:
        fail('bundle.yaml title "{0}" and script.py __title__ "{1}" differ'
             .format(title, script_title))


# ---------------------------------------------------------------------------
# .NET assemblies
# ---------------------------------------------------------------------------
# Namespace prefix -> the assemblies that must be referenced for it. Longest
# prefix wins, so System.Windows.Automation is not satisfied by the WPF trio.
ASSEMBLY_FOR = [
    ('System.Windows.Automation', ('UIAutomationClient', 'UIAutomationTypes')),
    # Windows Forms is its own assembly, not part of WPF, however much its
    # namespace looks like one of WPF's.
    ('System.Windows.Forms', ('System.Windows.Forms',)),
    ('System.Windows', ('PresentationCore', 'PresentationFramework',
                        'WindowsBase')),
]


def clr_assemblies(sources):
    source, tree = sources.get('lgc_clr.py', ('', None))
    for node in (tree.body if tree is not None else []):
        if isinstance(node, ast.Assign) and any(
                getattr(t, 'id', '') == 'ASSEMBLIES' for t in node.targets):
            return set(ast_str(e) for e in node.value.elts)
    fail('lgc_clr.py has no ASSEMBLIES tuple')
    return set()


def check_assemblies(sources):
    """Every System.* import has its assembly referenced in lgc_clr, and a
    module importing System.* at its top does `import lgc_clr` first.

    Imports inside functions count for the first rule: they fail at the
    moment they run, which is the hardest time to find out. They run after
    script.py has imported lgc_clr, which the loader rule checks.
    """
    referenced = clr_assemblies(sources)
    for name, (source, tree) in sorted(sources.items()):
        if tree is None:
            continue
        _WHERE['file'] = name
        clr_line = None
        for node in tree.body:
            if isinstance(node, ast.Import) and any(
                    a.name == 'lgc_clr' for a in node.names):
                clr_line = node.lineno
                break
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            for prefix, assemblies in ASSEMBLY_FOR:
                if node.module == prefix or node.module.startswith(prefix + '.'):
                    for assembly in assemblies:
                        if assembly not in referenced:
                            fail('line {0}: {1} needs {2!r} in lgc_clr.'
                                 'ASSEMBLIES'.format(node.lineno, node.module,
                                                     assembly))
                    break
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module and \
                    node.module.split('.')[0] == 'System':
                if clr_line is None or clr_line > node.lineno:
                    fail('line {0}: imports {1} at module level without '
                         '`import lgc_clr` above it'.format(node.lineno,
                                                            node.module))
    _WHERE['file'] = None


# ---------------------------------------------------------------------------
# The module layout
# ---------------------------------------------------------------------------
def lgc_imports(tree):
    """[(module, line, names)] for every lgc import at module level."""
    out = []
    for node in (tree.body if tree is not None else []):
        if isinstance(node, ast.ImportFrom) and node.module and \
                node.module.startswith('lgc_'):
            out.append((node.module, node.lineno,
                        [a.name for a in node.names]))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith('lgc_'):
                    out.append((alias.name, node.lineno, []))
    return out


def check_import_graph(sources):
    """Module-level lgc imports must form a chain with no loop.

    A loop in IronPython half-initialises one module and the next `from X
    import name` fails with an ImportError that names neither module as the
    cause. Imports inside functions (bind_document's) run after everything
    has loaded, so they are left out.
    """
    edges = {}
    for module in MODULES:
        source, tree = sources.get(module + '.py', ('', None))
        edges[module] = set(m for m, _l, _n in lgc_imports(tree)
                            if m != module)
        for target in edges[module]:
            if target not in MODULES:
                _WHERE['file'] = module + '.py'
                fail('imports {0}, which is not one of the modules'.format(
                    target))
                _WHERE['file'] = None

    state = {}

    def visit(module, path):
        if state.get(module) == 'done':
            return
        if state.get(module) == 'open':
            loop = path[path.index(module):] + [module]
            fail('import loop: {0}'.format(' -> '.join(loop)))
            return
        state[module] = 'open'
        for target in sorted(edges.get(module, ())):
            visit(target, path + [module])
        state[module] = 'done'

    for module in MODULES:
        visit(module, [])


def top_level_names(tree):
    names = set()
    for node in (tree.body if tree is not None else []):
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                names |= set(n.id for n in ast.walk(target)
                             if isinstance(n, ast.Name))
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names |= set((a.asname or a.name).split('.')[0]
                         for a in node.names)
    return names


def check_imported_names(sources):
    """`from lgc_x import name` - the name is really in lgc_x.

    pyflakes cannot see across files, and in Revit a missing name is an
    ImportError at the moment the button is pressed, naming only the
    module that asked.
    """
    homes = {}
    for module in MODULES:
        homes[module] = top_level_names(sources.get(module + '.py',
                                                    ('', None))[1])
    for name, (source, tree) in sorted(sources.items()):
        for module, line, names in lgc_imports(tree):
            for wanted in names:
                if module in homes and wanted not in homes[module]:
                    fail('{0} line {1}: imports {2} from {3}, which does not '
                         'define it'.format(name, line, wanted, module))


def check_purity(sources):
    """The pure modules import nothing from Revit, pyRevit or .NET at their
    top - the bench imports them under CPython, and lgc_clr runs before any
    reference exists."""
    for module in PURE:
        source, tree = sources.get(module + '.py', ('', None))
        if tree is None:
            continue
        _WHERE['file'] = module + '.py'
        for node in tree.body:
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or '']
            for name in names:
                root = name.split('.')[0]
                if root in ('pyrevit', 'System', 'Autodesk', 'clr', 'rpw'):
                    fail('line {0}: imports {1} at module level - this module '
                         'must load without Revit'.format(node.lineno, name))
        if module != 'lgc_clr':
            for node in ast.walk(tree):
                if isinstance(node, ast.Try):
                    for child in node.body:
                        if isinstance(child, ast.Import) and any(
                                a.name == 'clr' for a in child.names):
                            fail('line {0}: imports clr - only lgc_clr does'
                                 .format(child.lineno))
    _WHERE['file'] = None


def check_undefined_names(sources):
    """Every name used is defined or imported, module by module.

    The split into modules is where this bites: a helper moved to another
    module and not imported is a NameError only on the path that calls it,
    which may be the one path nobody tried before shipping. Needs pyflakes;
    skipped, loudly, if it is missing.
    """
    try:
        from pyflakes import api as flakes_api
        from pyflakes import reporter as flakes_reporter
    except ImportError:
        notes.append('undefined names NOT checked - pip install pyflakes')
        return

    class Collect(object):
        def __init__(self):
            self.lines = []

        def write(self, text):
            self.lines.append(text)

        def flush(self):
            pass

    for name, (source, tree) in sorted(sources.items()):
        if tree is None:
            continue
        out = Collect()
        flakes_api.check(source, name,
                         flakes_reporter.Reporter(out, out))
        for line in ''.join(out.lines).splitlines():
            if "'lgc_clr' imported but unused" in line:
                continue        # imported for what it does, not what it holds
            if 'undefined name' in line or 'imported but unused' in line or \
                    'redefinition of unused' in line or \
                    'unable to detect undefined names' in line:
                fail(line.strip())


DOC_MODULES = ['lgc_app', 'lgc_build', 'lgc_model', 'lgc_report']


def check_document_binding(sources):
    """The active document is bound per run, never captured at import.

    pyRevit can keep a module loaded between runs, so a module-level
    `doc = revit.doc` is the model that was open the first time - the wrong
    document after switching, a dead one after closing it. Every module
    that reads `doc` declares `doc = None` and is in bind_document's list,
    and main() binds before anything else reads it.
    """
    readers = set()
    for module in MODULES:
        source, tree = sources.get(module + '.py', ('', None))
        if tree is None:
            continue
        _WHERE['file'] = module + '.py'
        reads = any(isinstance(n, ast.Name) and n.id == 'doc' and
                    isinstance(n.ctx, ast.Load) for n in ast.walk(tree))
        declared = [n for n in tree.body if isinstance(n, ast.Assign) and
                    any(getattr(t, 'id', '') == 'doc' for t in n.targets)]
        for node in declared:
            if not (type(node.value).__name__ in ('Constant', 'NameConstant')
                    and getattr(node.value, 'value', 0) is None):
                fail('line {0}: doc is set at import - declare `doc = None` '
                     'and let bind_document set it'.format(node.lineno))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and \
                    any(a.name == 'doc' for a in node.names):
                fail('line {0}: imports doc from {1} - that copies whatever '
                     'it was at import'.format(node.lineno, node.module))
        if reads:
            readers.add(module)
            if not declared:
                fail('reads doc but never declares `doc = None`')
    _WHERE['file'] = 'lgc_app.py'
    source, tree = sources.get('lgc_app.py', ('', None))
    found = functions(tree)
    bind = found.get('bind_document')
    if bind is None:
        fail('has no bind_document()')
    else:
        # the modules in the loop, not every lgc name in the function - the
        # import line above the loop names them too
        bound = set()
        for loop in ast.walk(bind):
            if isinstance(loop, ast.For):
                bound |= set(n.id for n in ast.walk(loop.iter)
                             if isinstance(n, ast.Name))
        for module in sorted(readers - bound):
            fail('bind_document() never binds {0}, which reads doc'.format(
                module))
        for module in sorted(set(DOC_MODULES) - readers - set(['lgc_app'])):
            notes.append('{0} is in DOC_MODULES but never reads doc'.format(
                module))
    main = found.get('main')
    if main is None:
        fail('has no main()')
    else:
        calls = [n for n in ast.walk(main) if isinstance(n, ast.Call)]
        names = [getattr(c.func, 'id', getattr(c.func, 'attr', ''))
                 for c in sorted(calls, key=lambda c: (c.lineno,
                                                       c.col_offset))]
        for wanted in ('reset_trace', 'bind_document'):
            if wanted not in names:
                fail('main() never calls {0}()'.format(wanted))
        if 'reset_trace' in names and 'bind_document' in names and \
                names.index('bind_document') > 2:
            fail('main() does other work before bind_document()')
    _WHERE['file'] = None


def check_loader(sources):
    """script.py stays a loader: lgc_clr first, then lgc_app, inside a guard
    that re-raises SystemExit (pyRevit's normal way out - a cancel, or an
    alert with exitscript) and reports everything else.

    The report has to be reachable from the guard even when it is the
    import of lgc_app that failed, so _report imports lgc_report itself and
    falls back to a plain alert.
    """
    source, tree = sources.get(SCRIPT, ('', None))
    if tree is None:
        return
    _WHERE['file'] = SCRIPT
    defined = [n.name for n in tree.body
               if isinstance(n, (ast.FunctionDef, ast.ClassDef))]
    for name in defined:
        if name != '_report':
            fail('defines {0} - the tool belongs in the lgc modules, '
                 'script.py only loads them'.format(name))
    entry = [n for n in tree.body if isinstance(n, ast.If) and
             '__main__' in ast.dump(n.test)]
    if not entry:
        fail('no if __name__ == "__main__" entry point found')
        _WHERE['file'] = None
        return
    tries = [t for t in ast.walk(entry[0]) if isinstance(t, ast.Try)]
    if not tries:
        fail('the entry point has no try')
        _WHERE['file'] = None
        return
    guard = tries[0]
    imports = [a.name for s in guard.body if isinstance(s, ast.Import)
               for a in s.names]
    if imports[:1] != ['lgc_clr']:
        fail('the first import inside the guard must be lgc_clr, so every '
             'assembly is referenced before any module needs it')
    if 'lgc_app' not in imports:
        fail('the guard never imports lgc_app')
    names = [getattr(h.type, 'id', None) for h in guard.handlers]
    if 'SystemExit' not in names or 'Exception' not in names or \
            names.index('SystemExit') > names.index('Exception'):
        fail('the entry point must handle SystemExit (re-raise) before '
             'Exception')
    else:
        stop = guard.handlers[names.index('SystemExit')]
        if not any(isinstance(s, ast.Raise) for s in stop.body):
            fail('the SystemExit handler does not re-raise')
        crash = guard.handlers[names.index('Exception')]
        if not any(isinstance(n, ast.Call) and
                   getattr(n.func, 'id', None) == '_report'
                   for n in ast.walk(crash)):
            fail('the crash handler never calls _report')
    report = functions(tree).get('_report')
    if report is None:
        fail('has no _report()')
    else:
        text = body_text(source, report)
        if 'report_crash(' not in text:
            fail('_report() never reaches lgc_report.report_crash')
        if 'forms.alert(' not in text:
            fail('_report() has no plain alert to fall back on')
    _WHERE['file'] = None

    source, tree = sources.get('lgc_report.py', ('', None))
    crash = functions(tree).get('report_crash')
    if crash is None:
        fail('lgc_report.py has no report_crash()')
    elif 'show_debug_report(' not in body_text(source, crash):
        fail('report_crash() never shows the report')


def check_version(sources):
    """One __version__, in lgc_core, shown top right by the main window."""
    holders = []
    for name, (source, tree) in sorted(sources.items()):
        for node in (tree.body if tree is not None else []):
            if isinstance(node, ast.Assign) and any(
                    getattr(t, 'id', '') == '__version__'
                    for t in node.targets):
                holders.append(name)
                value = ast_str(node.value) or ''
                if not re.match(r'^\d+\.\d+\.\d+$', value):
                    fail('{0}: __version__ "{1}" is not x.y.z'.format(
                        name, value))
    if holders != ['lgc_core.py']:
        fail('__version__ must be set once, in lgc_core.py - found in {0}'
             .format(', '.join(holders) or 'nothing'))
    if not re.search(r'version_tb\.Text\s*=.*__version__',
                     sources.get('lgc_windows.py', ('', None))[0]):
        fail('the main window never shows __version__ in version_tb')
    core = shipped('lgc_core')
    if core is not None and exists('CHANGELOG.md'):
        heading = r'^## %s\s*$' % re.escape(core.__version__)
        if not re.search(heading, read('CHANGELOG.md'), re.M):
            fail('CHANGELOG.md has no entry for {0}'.format(core.__version__))


def check_bench_imports(sources):
    """bench_logic.py tests what ships: it may not keep its own copy of any
    function the modules define."""
    if not exists('bench_logic.py'):
        fail('bench_logic.py is missing')
        return
    shipped = set()
    for name, (source, tree) in sources.items():
        for node in (tree.body if tree is not None else []):
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                shipped.add(node.name)
    bench = ast.parse(read('bench_logic.py'))
    for node in bench.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and \
                node.name in shipped and node.name != 'main':
            fail('bench_logic.py defines its own {0}() - import the real '
                 'one, or the test drifts from what ships'.format(node.name))


# ---------------------------------------------------------------------------
# Cross-version and error-handling rules, on every module
# ---------------------------------------------------------------------------
# Revit 2024 to 2027. Each entry is a pattern that breaks on at least one of
# those releases, and why. Matched against code only.
CROSS_VERSION_FORBIDDEN = [
    (r'\bDB\.ElementId\s*\(',
     'constructs an ElementId from a number - the Int32 constructor was '
     'removed in Revit 2026; keep the ElementId Revit handed back'),
    (r"AddReference\(\s*['\"]RevitAPI",
     'references a Revit assembly - pyRevit has them loaded already'),
    (r'\bDisplayUnitType\b',
     'DisplayUnitType was removed in Revit 2022 - use mm / MM_PER_FOOT'),
    (r'\bstr\(\s*err\s*\)',
     'str() on a .NET exception can raise on non-ASCII text - use err_text'),
    (r'from\s+Autodesk\.Revit\.UI\s+import\s+[^\n]*\bUIThemeManager\b',
     'imports UIThemeManager directly - it does not exist before 2024; '
     'reach it by getattr on the namespace'),
]


def check_cross_version(source, tree):
    code = code_only(source, tree)
    for number, line in enumerate(code.splitlines(), 1):
        for pattern, reason in CROSS_VERSION_FORBIDDEN:
            if re.search(pattern, line):
                fail('line {0}: {1}'.format(number, reason))


# Functions allowed to absorb an error without recording it: parsing what a
# user typed, the mouse let go mid-drag, and the recording code itself.
SILENT_ALLOWED = {'log', 'swallowed', 'start_debug', 'crash_text',
                  'copy_to_clipboard', 'show_debug_report',
                  'environment_lines', 'err_text', 'channel',
                  'decode_colour_int', 'clamp_weight', 'parse_kv_list',
                  'scaled_mm', 'unscaled_mm', '_setting_float',
                  '_capture_distances', '_capture_sys_distances',
                  'line_weight', 'drag_window', 'format_mm', 'brush',
                  'settings_lines', 'probe', 'add', 'report_crash',
                  '_report'}


def check_no_silent_handlers(source, tree):
    """An except block that only passes, continues or returns must record
    what it absorbed with swallowed().

    Silent handlers are why "it does not work in 2026" arrived with no error:
    a member missing on that release was caught and dropped, and the tool
    simply did less. Module-level handlers (lgc_clr's references) run before
    swallowed() exists, and record into MISSING instead.
    """
    if tree is None:
        return
    spans = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            end = max(getattr(c, 'lineno', 0) for c in ast.walk(node))
            spans.append((node.name, node.lineno, end))

    def owner(line):
        best = None
        for name, start, end in spans:
            if start <= line <= end and (best is None or start > best[1]):
                best = (name, start)
        return best[0] if best else None

    def fallback(stmt):
        # "value = None" and friends: the error is replaced by a default
        # and forgotten, which is just as silent as pass.
        if not isinstance(stmt, ast.Assign):
            return False
        value = stmt.value
        if isinstance(value, (ast.List, ast.Dict, ast.Tuple)):
            return not getattr(value, 'elts', getattr(value, 'keys', []))
        return ast_str(value) is not None or \
            type(value).__name__ in ('Constant', 'NameConstant', 'Num')

    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        body = node.body
        quiet = all(isinstance(s, (ast.Pass, ast.Continue, ast.Break,
                                   ast.Return)) or fallback(s) for s in body)
        if not quiet:
            continue
        # A handler that hands its own exception on - "return None, err_text(
        # err)" - is reporting it, not hiding it.
        if node.name and any(isinstance(n, ast.Name) and
                             n.id == node.name for s in body
                             for n in ast.walk(s)):
            continue
        name = owner(node.lineno)
        if name is None or name in SILENT_ALLOWED:
            continue
        fail('line {0}: {1}() absorbs an error without swallowed() - a '
             'version difference there would vanish without trace'
             .format(node.lineno, name))


def check_engine_grammars(source):
    """Every file must parse under the grammars pyRevit's engines use.

    The rest of this bench parses with whatever CPython runs it, which
    accepts syntax IronPython 2.7 rejects - and a module that will not parse
    is an ImportError the moment the button is pressed. Needs
    `pip install parso==0.7.1`; skipped, loudly, if it is missing, since 0.8
    dropped the 2.7 grammar.
    """
    try:
        import parso
    except ImportError:
        if not any('engine grammars' in n for n in notes):
            notes.append('engine grammars NOT checked - '
                         'pip install parso==0.7.1')
        return
    for version in ('2.7', '3.4'):
        try:
            grammar = parso.load_grammar(version=version)
        except Exception as err:
            notes.append('engine grammar {0} unavailable in this parso ({1})'
                         .format(version, err))
            continue
        for error in list(grammar.iter_errors(grammar.parse(source)))[:5]:
            fail('line {0} will not parse under Python {1} (pyRevit engine): '
                 '{2}'.format(error.start_pos[0], version, error.message))


# ---------------------------------------------------------------------------
# Windows
# ---------------------------------------------------------------------------
def window_classes(sources):
    """(file, class name, class source) for each class that loads a layout."""
    out = []
    for name, (source, tree) in sorted(sources.items()):
        for cname, body in class_sources(source, tree):
            if 'load_window(self' in body or 'WPFWindow.__init__' in body:
                out.append((name, cname, body))
    return out


def check_load_window(sources):
    """Windows load through lgc_theme.load_window, and only it calls
    WPFWindow.__init__ - with handle_esc off.

    pyRevit's default closes a window on Escape before anything of ours
    sees the key, which closed a parked drawer bar instead of reopening it,
    and a layout loaded any other way would arrive without the theme.
    """
    for name, cname, body in window_classes(sources):
        if 'load_window(self' not in body:
            fail('{0}: {1} does not load through load_window'.format(
                name, cname))
    for name, (source, tree) in sorted(sources.items()):
        code = code_only(source, tree)
        calls = re.findall(r'WPFWindow\.__init__\(([^)]*)\)', code)
        if calls and name != 'lgc_theme.py':
            fail('{0} calls WPFWindow.__init__ itself - use load_window'
                 .format(name))
        if name == 'lgc_theme.py':
            first = [c for c in calls if 'literal_string' in c]
            if not first or 'handle_esc=False' not in first[0]:
                fail('lgc_theme.load_window must pass handle_esc=False')


def check_escape(sources):
    """With pyRevit's Escape handling off, the main window closes on Escape
    itself - after the drawer has had the key, so a parked bar reopens."""
    source = sources.get('lgc_windows.py', ('', None))[0]
    body = dict((c, b) for _n, c, b in window_classes(sources)).get(
        'CategoryPicker', '')
    bind = re.search(r'self\.PreviewKeyDown\s*\+=\s*self\.(\w+)', body)
    drawer = re.search(r'self\.drawer\s*=\s*make_drawer\(self\)', body)
    if bind is None:
        fail('CategoryPicker never binds PreviewKeyDown - Escape will not '
             'close it')
        return
    if drawer is None or drawer.start() > bind.start():
        fail('CategoryPicker binds its keys before the drawer - Escape on a '
             'parked bar would close the window instead of reopening it')
    handler = re.search(r'def %s\(self[^)]*\):(.*?)(?=\n    def |\Z)'
                        % bind.group(1), source, re.S)
    if handler is None or 'Escape' not in handler.group(1) or \
            'Handled' not in handler.group(1):
        fail('CategoryPicker.{0} must close on Escape unless the drawer '
             'already handled it'.format(bind.group(1)))


def layout_texts():
    """{layout: spliced text} - every window rule reads these."""
    texts = {}
    if not exists(THEME):
        fail('{0} is missing'.format(THEME))
        return texts
    try:
        ET.fromstring(read(THEME).encode('utf-8'))
    except Exception as err:
        fail('{0} is not well formed: {1}'.format(THEME, err))
        return texts
    for layout in LAYOUTS:
        if not exists(layout):
            fail('{0} is missing'.format(layout))
            continue
        try:
            text = spliced(layout)
        except ValueError as err:
            fail('{0}: {1}'.format(layout, err))
            continue
        try:
            ET.fromstring(text.encode('utf-8'))
        except Exception as err:
            fail('{0} is not well formed once the theme is in: {1}'.format(
                layout, err))
            continue
        texts[layout] = text
    return texts


def check_layout(texts, defined):
    """Returns the x:Name values declared across the layouts."""
    names = set()
    for layout, text in sorted(texts.items()):
        root = ET.fromstring(text.encode('utf-8'))
        handlers = set()
        for element in root.iter():
            for key, value in element.attrib.items():
                if key == XAML_NS + 'Name':
                    names.add(value)
                base = key.split('}')[-1]
                if base in HANDLER_ATTRS and not value.startswith('{'):
                    handlers.add(value)
        for handler in sorted(handlers):
            if handler not in defined:
                fail('{0} wires {1}() but no module has such a method'.format(
                    layout, handler))

        keys = set(re.findall(r'x:Key="([^"]+)"', text))
        for key in set(re.findall(r'\{StaticResource\s+([^}\s]+)\}', text)):
            if not key.startswith('{x:Type') and key not in keys:
                fail('{0} asks for StaticResource "{1}" which nothing defines'
                     .format(layout, key))

        seen = {}
        for key in re.findall(r'x:Key="([^"]+)"', text):
            seen[key] = seen.get(key, 0) + 1
        for key, count in sorted(seen.items()):
            if count > 1:
                # WPF answers with "Add value to dictionary of type
                # 'System.Windows.ResourceDictionary' threw an exception",
                # which names neither the key nor the file.
                fail('{0} defines x:Key="{1}" {2} times once the theme is in '
                     '- WPF refuses a duplicate key'.format(layout, key,
                                                            count))
    return names


def check_no_xaml_event_wiring():
    """Events must be bound in Python, not wired as XAML attributes.

    String wiring is not dependable through pyRevit's loader: the header's
    MouseLeftButtonDown silently never fired and the window could not be
    dragged, with no error anywhere.
    """
    for layout in LAYOUTS + [THEME]:
        if not exists(layout):
            continue
        for number, line in enumerate(read(layout).splitlines(), 1):
            for attr in HANDLER_ATTRS:
                if re.search(r'\s%s="[a-z_]' % attr, line):
                    fail('{0} line {1} wires {2} in XAML - bind it in Python'
                         .format(layout, number, attr))


def check_findnames(sources, declared):
    """Any lowercase self.<name> a window class never assigns must come from
    a layout, because that is the only other way it can exist."""
    for fname, (source, tree) in sorted(sources.items()):
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            methods, assigned, used = set(), set(), set()
            for child in ast.walk(node):
                if isinstance(child, ast.FunctionDef):
                    methods.add(child.name)
                if isinstance(child, ast.Attribute) and \
                        isinstance(child.value, ast.Name) and \
                        child.value.id == 'self':
                    if isinstance(child.ctx, ast.Store):
                        assigned.add(child.attr)
                    else:
                        used.add(child.attr)
            for name in sorted(used - assigned - methods):
                if not name or not name[0].islower() or name in declared:
                    continue          # WPF members are PascalCase
                fail('{0}: {1} uses self.{2}, which Python never sets and no '
                     'layout declares as x:Name'.format(fname, node.name,
                                                       name))


def check_event_bindings(sources, texts):
    """Interactive elements must actually be bound to something.

    Anchored on what the layouts declare, not on what the code mentions:
    deleting a binding also deletes the only reference to that control, so a
    rule keyed on "the class uses this name" quietly stops checking exactly
    when it matters.
    """
    code = '\n'.join(s for s, _t in sources.values())
    names = set()
    for text in texts.values():
        names |= set(re.findall(r'x:Name="(\w+)"', text))

    for name in sorted(n for n in names if n.endswith('_btn')):
        if not re.search(r'self\.%s\.Click\s*\+=' % name, code):
            fail('{0} is declared in a layout but nothing binds its Click'
                 .format(name))

    # a grip with no DragDelta is an edge that looks draggable and is not
    for name in sorted(n for n in names if n.startswith('grip_')):
        if not re.search(r'self\.%s\.DragDelta\s*\+=' % name, code):
            fail('{0} is declared but nothing binds its DragDelta - that '
                 'edge will not resize'.format(name))

    if 'header_bar' not in names:
        return
    for fname, cname, body in window_classes(sources):
        if not re.search(r'self\.header_bar\.MouseLeftButtonDown\s*\+=',
                         body):
            fail('{0}: {1} never binds header_bar.MouseLeftButtonDown - that '
                 'window will not move'.format(fname, cname))


def check_palettes(sources, texts):
    """Both palettes define the same keys, every DynamicResource a window
    asks for is declared, and every declared brush follows a theme switch."""
    logic = shipped('lgc_logic')
    if logic is None:
        return
    keys = dict((name, set(p)) for name, p in logic.PALETTES.items())
    if sorted(keys) != ['dark', 'light']:
        fail('expected a dark and a light palette')
        return
    for key in sorted(keys['dark'] ^ keys['light']):
        holder = 'dark' if key in keys['dark'] else 'light'
        fail('palette key "{0}" is only in the {1} palette'.format(key,
                                                                  holder))
    declared_all = set()
    for layout, text in sorted(texts.items()):
        declared = set(re.findall(r'<SolidColorBrush x:Key="([^"]+)"', text))
        asked = set(re.findall(r'\{DynamicResource ([A-Za-z]+)\}', text))
        declared_all |= declared
        for key in sorted(asked - declared):
            fail('{0} uses DynamicResource "{1}" which it does not declare'
                 .format(layout, key))
    for key in sorted(declared_all - keys['dark']):
        fail('brush "{0}" is declared but no palette sets it, so it will not '
             'follow a theme switch'.format(key))


def check_findresource(sources, texts):
    """Every FindResource key is defined once the theme is in, or the call
    throws at window build time and the tool dies before it shows."""
    code = '\n'.join(s for s, _t in sources.values())
    wanted = set()
    for call in re.findall(r"FindResource\(([^)]*)\)", code):
        wanted |= set(re.findall(r"'([A-Za-z0-9_]+)'", call))
    declared = set()
    for text in texts.values():
        declared |= set(re.findall(r'x:Key="([^"]+)"', text))
    for key in sorted(wanted - declared):
        fail('FindResource("{0}") but no layout defines that key'.format(key))


def check_drawers(sources, texts):
    """Every window this tool opens carries the shrink drawer, end to end.

    Per window class: it builds a drawer, binds its shrink button, and its
    drag handler gives the drawer the first look at a header click (that is
    what makes a double click reopen a parked bar). Per layout with a header:
    a shrink_btn styled ShrinkBtn, whose Tag trigger value is exactly the
    SHRUNK constant the drawer writes - a mismatch would leave the button
    showing the down arrow on a parked window, with nothing raised.
    """
    for fname, name, body in window_classes(sources):
        if not re.search(r'self\.drawer\s*=\s*make_drawer\(self\)', body):
            fail('{0}: {1} is built without a drawer'.format(fname, name))
        if not re.search(r'self\.shrink_btn\.Click\s*\+=', body):
            fail('{0}: {1} never binds its shrink button'.format(fname, name))
        drag = re.search(r'def drag_window\(self[^)]*\):(.*?)(?=\n    def |\Z)',
                         body, re.S)
        if drag is None:
            fail('{0}: {1} has no drag_window'.format(fname, name))
            continue
        code = drag.group(1)
        first = code.find('self.drawer.header_down(')
        moves = code.find('DragMove(')
        if first < 0 or (moves >= 0 and moves < first):
            fail('{0}: {1}.drag_window does not ask the drawer first, so a '
                 'double click on a parked bar will not reopen it'.format(
                     fname, name))

    drawer = shipped('lgc_drawer')
    SHRUNK = getattr(drawer, 'SHRUNK', None)
    if SHRUNK is None:
        return
    for layout, text in sorted(texts.items()):
        if 'x:Name="header_bar"' not in text:
            continue
        button = re.search(r'<Button x:Name="shrink_btn"[^>]*>', text)
        if button is None:
            fail('{0} has a header but no shrink_btn'.format(layout))
            continue
        if 'Style="{StaticResource ShrinkBtn}"' not in button.group(0):
            fail('{0}: shrink_btn is not styled ShrinkBtn'.format(layout))
        style = re.search(r'<Style x:Key="ShrinkBtn".*?</Style>', text, re.S)
        if style is None:
            fail('{0} has no ShrinkBtn style'.format(layout))
            continue
        trigger = re.search(r'<Trigger Property="Tag" Value="([^"]*)">'
                            r'(.*?)</Trigger>', style.group(0), re.S)
        if trigger is None:
            fail('{0}: ShrinkBtn has no Tag trigger'.format(layout))
        elif trigger.group(1) != SHRUNK:
            fail('{0}: ShrinkBtn trigger waits for Tag "{1}" but the drawer '
                 'sets "{2}"'.format(layout, trigger.group(1), SHRUNK))
        elif not re.search(r'TargetName="pthExpand" Property="Visibility"\s*'
                           r'Value="Visible"', trigger.group(2)):
            fail('{0}: the Tag trigger never shows the up arrow'.format(
                layout))
        if not re.search(r'x:Name="pthExpand"[^>]*Stroke="\{DynamicResource '
                         r'Green\}"', style.group(0), re.S):
            fail('{0}: the up arrow is not drawn in the palette green'.format(
                layout))


def check_grids(texts):
    for layout in LAYOUTS:
        if exists(layout):
            check_grid_rows(layout)


# ---------------------------------------------------------------------------
def main():
    sources = load_sources()
    combined = '\n'.join(sources[n][0] for n in sorted(sources))

    for name, (source, tree) in sorted(sources.items()):
        _WHERE['file'] = name
        check_no_fstrings(source, tree)
        check_no_print_statements(source)
        check_integervalue(source, tree)
        check_no_system_uri(source)
        check_namespaces(source)
        check_cross_version(source, tree)
        check_no_silent_handlers(source, tree)
        check_engine_grammars(source)
    _WHERE['file'] = None

    check_assemblies(sources)
    check_import_graph(sources)
    check_imported_names(sources)
    check_purity(sources)
    check_undefined_names(sources)
    check_document_binding(sources)
    check_loader(sources)
    check_version(sources)
    check_bench_imports(sources)
    check_load_window(sources)
    check_escape(sources)

    def module(name):
        return sources.get(name, ('', None))

    _WHERE['file'] = 'lgc_logic.py'
    check_system_kinds(*module('lgc_logic.py'))
    _WHERE['file'] = 'lgc_build.py'
    check_overwrite_writes(*module('lgc_build.py'))
    check_readbacks(*module('lgc_build.py'))
    _WHERE['file'] = 'lgc_windows.py'
    check_status_through_say(*module('lgc_windows.py'))
    check_shared_settings(module('lgc_windows.py')[0])
    _WHERE['file'] = None
    check_settings_keys(combined)
    check_bundle(module(SCRIPT)[0])

    texts = layout_texts()
    defined = set()
    for source, tree in sources.values():
        defined |= set(functions(tree))
    declared = check_layout(texts, defined)
    check_no_xaml_event_wiring()
    check_findnames(sources, declared)
    check_event_bindings(sources, texts)
    check_palettes(sources, texts)
    check_findresource(sources, texts)
    check_drawers(sources, texts)
    check_grids(texts)

    for note in notes:
        sys.stdout.write('note: {0}\n'.format(note))

    if failures:
        sys.stdout.write('\n{0} problem(s):\n'.format(len(failures)))
        for item in failures:
            sys.stdout.write('  - {0}\n'.format(item))
        return 1

    sys.stdout.write('bench check passed ({0} files, {1} layouts)\n'.format(
        len(sources), len(texts)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
