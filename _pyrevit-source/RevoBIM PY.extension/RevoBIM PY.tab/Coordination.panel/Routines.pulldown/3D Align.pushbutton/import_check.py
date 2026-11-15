# -*- coding: utf-8 -*-
"""3D Align - static bench. Run under plain CPython from this folder:

    python import_check.py                     every rule against this folder
    python import_check.py --delivery <root>   also scan a delivery for shared files
    python import_check.py --selftest          break each rule on purpose and
                                               confirm it fires
"""
import ast
import io
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import tokenize
import xml.dom.minidom

HERE = os.path.dirname(os.path.abspath(__file__))
LOADERS = ('script.py', 'config.py')
BENCH = ('import_check.py', 'bench_logic.py', 'bench_stubs.py')
LAYOUTS = ('Align3DResults.xaml', 'Align3DSettings.xaml')
CLR_MODULE = 'a3d_clr'

# namespace -> assemblies, any one of which provides it. Autodesk.* is
# pyRevit's to load, so it maps to nothing and is never AddReference'd.
ASSEMBLY_FOR = {
    'System': ('mscorlib', 'System'),
    'System.Collections.Generic': ('mscorlib', 'System'),
    'System.IO': ('mscorlib',),
    'System.Diagnostics': ('System',),
    'System.Windows': ('PresentationFramework', 'PresentationCore', 'WindowsBase'),
    'System.Windows.Controls': ('PresentationFramework',),
    'System.Windows.Forms': ('System.Windows.Forms',),
    'System.Windows.Input': ('PresentationCore',),
    'System.Windows.Interop': ('PresentationFramework',),
    'System.Windows.Markup': ('PresentationFramework',),
    'System.Windows.Media': ('PresentationCore',),
    'System.Windows.Media.Imaging': ('PresentationCore',),
}


# ==========================================================================
# helpers
# ==========================================================================

def read(root, name):
    with io.open(os.path.join(root, name), 'r', encoding='utf-8') as handle:
        return handle.read()


def tool_modules(root):
    return sorted(n for n in os.listdir(root)
                  if n.endswith('.py') and n not in BENCH)


def xaml_files(root):
    return sorted(n for n in os.listdir(root) if n.endswith('.xaml'))


STRINGISH = set(k for k in (tokenize.STRING, tokenize.COMMENT,
                             getattr(tokenize, 'FSTRING_START', None),
                             getattr(tokenize, 'FSTRING_MIDDLE', None),
                             getattr(tokenize, 'FSTRING_END', None)) if k is not None)


def code_only(text):
    """Source with string literals and comments blanked, so a rule reads code
    and never a docstring that happens to mention what it looks for."""
    out = []
    try:
        tokens = tokenize.generate_tokens(io.StringIO(text).readline)
        last_line, last_col = 1, 0
        lines = text.splitlines(True)
        for kind, value, start, end, _line in tokens:
            if kind in STRINGISH:
                value = "''" if kind == tokenize.STRING else ''
            if start[0] > last_line:
                out.append('\n' * (start[0] - last_line))
                last_col = 0
            out.append(' ' * max(0, start[1] - last_col))
            out.append(value)
            last_line, last_col = end
        return ''.join(out)
    except Exception:
        return text


def theme_keys(root):
    doc = xml.dom.minidom.parseString(read(root, 'Theme.xaml').encode('utf-8'))
    keys = {}
    for node in doc.getElementsByTagName('*'):
        key = node.getAttribute('x:Key')
        if key:
            keys[key] = node
    return keys


def palettes(root):
    tree = ast.parse(read(root, 'theme.py'))
    found = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
            name = node.targets[0].id
            if name in ('DARK', 'LIGHT'):
                found[name] = set(k.value for k in node.value.keys)
    return found


# ==========================================================================
# rules: each returns a list of problems
# ==========================================================================

def rule_xaml_parses(root):
    problems = []
    for name in xaml_files(root):
        try:
            xml.dom.minidom.parseString(read(root, name).encode('utf-8'))
        except Exception as error:
            problems.append('{0} does not parse: {1}'.format(name, error))
    return problems


def rule_loaders_thin(root):
    problems = []
    for name in LOADERS:
        tree = ast.parse(read(root, name))
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module]
                for module in names:
                    if module not in ('os', 'sys', 'traceback'):
                        problems.append('{0} imports {1} outside its try/except'.format(name, module))
        if 'AddReference' in code_only(read(root, name)):
            problems.append('{0} references assemblies; that belongs in {1}'.format(name, CLR_MODULE))
    return problems


IMPORT_DOTNET = re.compile(r'^\s*(from|import)\s+(System|Autodesk)\b', re.M)
IMPORT_CLR = re.compile(r'^\s*import\s+' + CLR_MODULE + r'\b', re.M)


def rule_clr_first(root):
    problems = []
    for name in tool_modules(root):
        if name in LOADERS or name == CLR_MODULE + '.py':
            continue
        code = code_only(read(root, name))
        first_dotnet = IMPORT_DOTNET.search(code)
        if not first_dotnet:
            continue
        clr = IMPORT_CLR.search(code)
        if clr is None or clr.start() > first_dotnet.start():
            problems.append('{0} reaches into .NET before importing {1}'.format(name, CLR_MODULE))
    return problems


def referenced_assemblies(root):
    tree = ast.parse(read(root, CLR_MODULE + '.py'))
    for node in tree.body:
        if isinstance(node, ast.Assign) and node.targets[0].id == '_ASSEMBLIES':
            return set(ast.literal_eval(node.value))
    return set()


def rule_assemblies_referenced(root):
    problems = []
    referenced = referenced_assemblies(root)
    for name in tool_modules(root):
        tree = ast.parse(read(root, name))
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            elif isinstance(node, ast.Import):
                modules = [a.name for a in node.names]
            for module in modules:
                if not module.startswith('System'):
                    continue
                if module not in ASSEMBLY_FOR:
                    problems.append('{0}: {1} has no entry in ASSEMBLY_FOR'.format(name, module))
                elif not referenced.intersection(ASSEMBLY_FOR[module]):
                    problems.append('{0}: {1} needs one of {2} in {3}'.format(
                        name, module, ', '.join(ASSEMBLY_FOR[module]), CLR_MODULE))
    return problems


def rule_no_static_resource(root):
    return ['{0} uses StaticResource; Theme.xaml is merged after the layout parses'.format(n)
            for n in LAYOUTS if 'StaticResource' in read(root, n)]


RESOURCE = re.compile(r'\{(?:Dynamic|Static)Resource\s+([A-Za-z0-9_]+)\}')


def code_resource_keys(root):
    keys = set()
    tree = ast.parse(read(root, 'a3d_ui.py'))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, 'attr', '') == 'SetResourceReference':
            argument = node.args[1] if len(node.args) > 1 else None
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                keys.add(argument.value)
        if isinstance(node, ast.Assign) and getattr(node.targets[0], 'id', '') == 'KINDS':
            for value in ast.literal_eval(node.value).values():
                keys.update(value[1:])
        if isinstance(node, ast.Call) and getattr(node.func, 'id', '') == 'themed_text':
            if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                keys.add(node.args[1].value)
    return keys


def rule_resource_keys_defined(root):
    defined = set(theme_keys(root))
    problems = []
    for name in xaml_files(root):
        for key in RESOURCE.findall(read(root, name)):
            if key not in defined:
                problems.append('{0} asks for {1}, which Theme.xaml does not define'.format(name, key))
    for key in sorted(code_resource_keys(root)):
        if key not in defined:
            problems.append('a3d_ui.py asks for {0}, which Theme.xaml does not define'.format(key))
    return problems


def rule_palettes_cover(root):
    found = palettes(root)
    dark, light = found.get('DARK', set()), found.get('LIGHT', set())
    brushes = set(k for k, n in theme_keys(root).items() if n.tagName == 'SolidColorBrush')
    problems = []
    if dark != light:
        problems.append('palettes differ: {0}'.format(sorted(dark.symmetric_difference(light))))
    if dark | light != brushes:
        problems.append('palette and Theme.xaml brushes differ: {0}'.format(
            sorted((dark | light).symmetric_difference(brushes))))
    return problems


STYLE_USE = re.compile(r'<([A-Za-z]+)\b[^>]*?Style="\{DynamicResource ([A-Za-z0-9_]+)\}"', re.S)


def rule_style_targets(root):
    keys = theme_keys(root)
    problems = []
    for name in xaml_files(root):
        for tag, key in STYLE_USE.findall(read(root, name)):
            node = keys.get(key)
            if node is None or node.tagName != 'Style':
                continue
            if node.getAttribute('TargetType') != tag:
                problems.append('{0}: {1} styled with {2}, which targets {3}'.format(
                    name, tag, key, node.getAttribute('TargetType')))
    return problems


def rule_findname_has_xname(root):
    names = set()
    for name in LAYOUTS:
        names.update(re.findall(r'x:Name="([A-Za-z0-9_]+)"', read(root, name)))
    wanted = set()
    tree = ast.parse(read(root, 'a3d_ui.py'))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            label = getattr(func, 'attr', None) or getattr(func, 'id', None)
            if label in ('FindName', 'find') and node.args and isinstance(node.args[0], ast.Constant):
                wanted.add(node.args[0].value)
        if isinstance(node, ast.Assign):
            target = getattr(node.targets[0], 'id', '')
            if target == 'RADIOS':
                for _key, options in ast.literal_eval(node.value):
                    wanted.update(n for _v, n in options)
            if target == 'sides':
                wanted.update(ast.literal_eval(node.value).keys())
    return ['a3d_ui.py looks for {0}, which no layout names'.format(n) for n in sorted(wanted - names)]


def rule_banned_syntax(root):
    problems = []
    for name in tool_modules(root):
        text = read(root, name)
        # Python 3.12 tokenises an f-string as FSTRING_START..END, not STRING,
        # so a STRING-only test is inert there. Both shapes are checked.
        fstring_start = getattr(tokenize, 'FSTRING_START', None)
        for kind, value, start, _end, _line in tokenize.generate_tokens(io.StringIO(text).readline):
            is_fstring = (kind == fstring_start or
                          (kind == tokenize.STRING and re.match(r'^[rRbBuU]*[fF]', value)))
            if is_fstring:
                problems.append('{0}:{1} f-string'.format(name, start[0]))
        code = code_only(text)
        if re.search(r'^\s*print\b', code, re.M):
            problems.append('{0}: print'.format(name))
        if re.search(r'\bUri\b|UriSource', code):
            problems.append('{0}: System.Uri - moved assembly in Revit 2025'.format(name))
        tree = ast.parse(text)
        allowed = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == 'eid_value':
                allowed.update(id(n) for n in ast.walk(node))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == 'IntegerValue' and id(node) not in allowed:
                problems.append('{0}:{1} bare .IntegerValue - gone in Revit 2026'.format(name, node.lineno))
    return problems


def rule_non_ascii(root):
    problems = []
    for name in tool_modules(root):
        text = read(root, name)
        for kind, value, start, _end, _line in tokenize.generate_tokens(io.StringIO(text).readline):
            if kind == tokenize.COMMENT:
                continue
            if any(ord(c) > 127 for c in value):
                if kind == tokenize.STRING and value[:1] in 'uU':
                    continue
                problems.append('{0}:{1} non-ASCII outside a u\'\' literal'.format(name, start[0]))
    return problems


def rule_no_duplicate_defs(root):
    problems = []
    for name in tool_modules(root):
        tree = ast.parse(read(root, name))
        scopes = [tree] + [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
        for scope in scopes:
            seen = set()
            for node in scope.body:
                if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                    if node.name in seen:
                        problems.append('{0}: {1} defined twice'.format(name, node.name))
                    seen.add(node.name)
    return problems


def rule_late_builtins(root):
    problems = []
    for name in tool_modules(root):
        for node in ast.walk(ast.parse(read(root, name))):
            if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                    and node.value.id in ('BuiltInCategory', 'BuiltInParameter')):
                problems.append('{0}:{1} {2}.{3} - look members up with getattr at call time'.format(
                    name, node.lineno, node.value.id, node.attr))
    return problems


def rule_loads_against_stub(root):
    script = ('import sys; sys.path.insert(0, {0!r}); import bench_stubs; bench_stubs.install(); '
              'import importlib\n'
              'for m in bench_stubs.TOOL_MODULES: importlib.import_module(m)').format(root)
    process = subprocess.Popen([sys.executable, '-c', script], cwd=root,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    output = process.communicate()[0].decode('utf-8', 'replace')
    if process.returncode:
        return ['the tool does not load against the stub API:\n' + output.strip().splitlines()[-1]]
    return []


SETTING_USE = re.compile(r"""(?:settings(?:\.get)?[\[\(]|is_on\(\s*settings\s*,\s*)\s*'([a-z_]+)'""")


def rule_settings_keys_known(root):
    tree = ast.parse(read(root, 'a3d_settings.py'))
    defaults = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], 'id', '') == 'DEFAULTS':
            defaults = set(k.value for k in node.value.keys)
    problems = []
    for name in tool_modules(root):
        for key in SETTING_USE.findall(read(root, name)):
            if key not in defaults:
                problems.append('{0} reads setting {1}, which has no default'.format(name, key))
    return problems


def rule_transactions_handled(root):
    problems = []
    for name in tool_modules(root):
        for node in ast.walk(ast.parse(read(root, name))):
            if not isinstance(node, ast.FunctionDef):
                continue
            body = ast.dump(node)
            if "id='Transaction'" not in body:
                continue
            for needed in ('SetFailuresPreprocessor', 'SetFailureHandlingOptions', 'Committed'):
                if needed not in body:
                    problems.append('{0}.{1} opens a Transaction without {2}'.format(name, node.name, needed))
    return problems


def rule_version_in_changelog(root):
    version = re.search(r"__version__ = '([0-9.]+)'", read(root, 'a3d_settings.py'))
    if not version:
        return ['no __version__ in a3d_settings.py']
    if not re.search(r'^## ' + re.escape(version.group(1)) + r'\s*$', read(root, 'CHANGELOG.md'), re.M):
        return ['CHANGELOG.md has no entry for {0}'.format(version.group(1))]
    return []


def shared_file_problems(base):
    problems = []
    for folder, dirs, files in os.walk(base):
        relative = os.path.relpath(folder, base)
        if 'hooks' in dirs:
            problems.append('ships a hooks folder: {0}'.format(os.path.join(relative, 'hooks')))
        if 'startup.py' in files:
            problems.append('ships startup.py: {0}'.format(relative))
        if '__init__.py' in files and os.path.basename(folder) == 'revobim':
            problems.append('ships lib\\revobim\\__init__.py')
        if 'bundle.yaml' in files and folder.endswith(('.panel', '.pulldown', '.stack')):
            problems.append('ships a shared bundle.yaml: {0}'.format(relative))
    return problems


def rule_shared_files(root, delivery=None):
    problems = shared_file_problems(root)
    if delivery:
        problems += shared_file_problems(delivery)
    return problems


def rule_ribbon_title(root):
    folder = os.path.basename(os.path.normpath(root))
    stem = folder[:-len('.pushbutton')] if folder.endswith('.pushbutton') else None
    title = re.search(r'^title:\s*(.+)$', read(root, 'bundle.yaml'), re.M)
    name = re.search(r"TOOL_NAME = u'([^']+)'", read(root, 'a3d_settings.py'))
    problems = []
    if title is None or name is None:
        return ['bundle.yaml title or TOOL_NAME missing']
    if title.group(1).strip() != name.group(1):
        problems.append('bundle.yaml title {0!r} is not TOOL_NAME {1!r}'.format(title.group(1), name.group(1)))
    if stem is not None and stem != name.group(1):
        problems.append('folder {0!r} is not TOOL_NAME {1!r}'.format(stem, name.group(1)))
    return problems


def png_size(path):
    with open(path, 'rb') as handle:
        head = handle.read(24)
    if head[:8] != b'\x89PNG\r\n\x1a\n':
        return None
    return struct.unpack('>II', head[16:24])


def rule_icons(root):
    problems = []
    for name in ('icon.png', 'icon.dark.png'):
        path = os.path.join(root, name)
        if not os.path.isfile(path):
            problems.append('{0} missing'.format(name))
            continue
        size = png_size(path)
        if size is None or size[0] != size[1]:
            problems.append('{0} is not a square PNG'.format(name))
    return problems


CHROME_NAMES = ('Header', 'Logo', 'ThemeChip', 'ThemeLabel', 'VersionText', 'CloseBtn')


def rule_chrome_in_every_window(root):
    problems = []
    for name in LAYOUTS:
        text = read(root, name)
        for part in CHROME_NAMES:
            if 'x:Name="{0}"'.format(part) not in text:
                problems.append('{0} has no {1} - every window carries the house header'.format(name, part))
    return problems


RULES = [
    ('xaml_parses', rule_xaml_parses),
    ('loaders_thin', rule_loaders_thin),
    ('clr_first', rule_clr_first),
    ('assemblies_referenced', rule_assemblies_referenced),
    ('no_static_resource', rule_no_static_resource),
    ('resource_keys_defined', rule_resource_keys_defined),
    ('palettes_cover', rule_palettes_cover),
    ('style_targets', rule_style_targets),
    ('findname_has_xname', rule_findname_has_xname),
    ('banned_syntax', rule_banned_syntax),
    ('non_ascii', rule_non_ascii),
    ('no_duplicate_defs', rule_no_duplicate_defs),
    ('late_builtins', rule_late_builtins),
    ('loads_against_stub', rule_loads_against_stub),
    ('settings_keys_known', rule_settings_keys_known),
    ('transactions_handled', rule_transactions_handled),
    ('version_in_changelog', rule_version_in_changelog),
    ('shared_files', rule_shared_files),
    ('ribbon_title', rule_ribbon_title),
    ('icons', rule_icons),
    ('chrome_in_every_window', rule_chrome_in_every_window),
]


def run(root, delivery=None, quiet=False):
    failed = {}
    for name, rule in RULES:
        try:
            problems = rule(root, delivery) if name == 'shared_files' else rule(root)
        except Exception as error:
            problems = ['rule crashed: {0}'.format(error)]
        if problems:
            failed[name] = problems
            if not quiet:
                for problem in problems:
                    sys.stdout.write('FAIL  {0}: {1}\n'.format(name, problem))
    if not quiet:
        sys.stdout.write('{0} rules, {1} failed\n'.format(len(RULES), len(failed)))
    return failed


# (rule expected to fire, file, find, replace) - None for find means "create
# the file with this content", and '' for replace with a find means delete it.
BREAKAGES = [
    ('xaml_parses', 'Theme.xaml', '<!-- ==== Header buttons', '<!-- -- Header buttons'),
    ('loaders_thin', 'script.py', 'import traceback\n', 'import traceback\nimport a3d_core\n'),
    ('clr_first', 'a3d_ui.py', 'import a3d_clr  # noqa: F401  - assemblies first, always\n',
     'from System.IO import File\nimport a3d_clr  # noqa: F401  - assemblies first, always\n'),
    ('assemblies_referenced', 'a3d_clr.py', "'System.Drawing', 'System.Windows.Forms',", "'System.Drawing',"),
    ('no_static_resource', 'Align3DResults.xaml', 'Foreground="{DynamicResource Blue}"',
     'Foreground="{StaticResource Blue}"'),
    ('resource_keys_defined', 'a3d_ui.py', "'warn': (u'CHECK', 'Orange', 'RowWarn')",
     "'warn': (u'CHECK', 'Orange', 'RowWarm')"),
    ('palettes_cover', 'theme.py', "'Red': '#C0392B', 'Selection': '#CFE3F5', 'Hover': '#E2E2E8',",
     "'Red': '#C0392B', 'Selection': '#CFE3F5',"),
    ('style_targets', 'Align3DSettings.xaml', '<Button x:Name="ThemeChip" Style="{DynamicResource ChipButton}">',
     '<Button x:Name="ThemeChip" Style="{DynamicResource Segment}">'),
    ('findname_has_xname', 'a3d_ui.py', "'GripBR': (0, 0, 1, 1)", "'GripBX': (0, 0, 1, 1)"),
    ('banned_syntax', 'a3d_geom.py', 'VERTICAL = ', "_bad = f'{STEEP_DEG}'\nVERTICAL = "),
    ('banned_syntax', 'a3d_core.py', '    return (point(curve.GetEndPoint(0))',
     '    _bad = curve.Id.IntegerValue\n    return (point(curve.GetEndPoint(0))'),
    ('banned_syntax', 'a3d_ui.py', '    image.StreamSource = ', '    image.UriSource = None\n    image.StreamSource = '),
    ('non_ascii', 'a3d_settings.py', "TOOL_NAME = u'3D Align'", "TOOL_NAME = u'3D Align'\n_bad = '\u00e9'"),
    ('no_duplicate_defs', 'a3d_geom.py', 'def translate(axis, move):',
     'def pitch_deg(axis):\n    return 0\n\n\ndef translate(axis, move):'),
    ('late_builtins', 'a3d_core.py', "TARGET_CATEGORIES = (",
     "_bad = BuiltInCategory.OST_PipeCurves\nTARGET_CATEGORIES = ("),
    ('loads_against_stub', 'a3d_core.py', 'from Autodesk.Revit.DB import (BuiltInCategory,',
     'from Autodesk.Revit.DB import (BuiltInCategory, ObjectType,'),
    ('settings_keys_known', 'a3d_core.py', "settings.get('on_refusal')", "settings.get('on_refusel')"),
    ('transactions_handled', 'a3d_core.py', '    options.SetFailuresPreprocessor(failures)\n', ''),
    ('version_in_changelog', 'a3d_settings.py', "__version__ = '", "__version__ = '9."),
    ('shared_files', 'startup.py', None, '# a tool delivery must never ship this\n'),
    ('ribbon_title', 'a3d_settings.py', "TOOL_NAME = u'3D Align'", "TOOL_NAME = u'3D Aligner'"),
    ('icons', 'icon.dark.png', b'', ''),
    ('chrome_in_every_window', 'Align3DSettings.xaml', 'x:Name="VersionText"', 'x:Name="Version"'),
]


def selftest():
    misses = 0
    clean = run(HERE, quiet=True)
    if clean:
        sys.stdout.write('the clean tool fails: {0}\n'.format(sorted(clean)))
        return 1
    for rule, filename, old, new in BREAKAGES:
        work = tempfile.mkdtemp()
        target = os.path.join(work, os.path.basename(HERE))
        shutil.copytree(HERE, target, ignore=shutil.ignore_patterns('__pycache__'))
        path = os.path.join(target, filename)
        label = '{0} ({1})'.format(rule, filename)
        if old is None:
            with io.open(path, 'w', encoding='utf-8') as handle:
                handle.write(new)
        elif old == b'':
            os.remove(path)
        else:
            text = read(target, filename)
            if text.count(old) != 1:
                sys.stdout.write('BROKEN BREAKAGE  {0}: anchor found {1} times\n'.format(label, text.count(old)))
                misses += 1
                continue
            with io.open(path, 'w', encoding='utf-8') as handle:
                handle.write(text.replace(old, new))
        fired = rule in run(target, quiet=True)
        sys.stdout.write('{0}  {1}\n'.format('caught ' if fired else 'MISSED ', label))
        misses += 0 if fired else 1
        shutil.rmtree(work, ignore_errors=True)
    sys.stdout.write('{0} breakages, {1} missed\n'.format(len(BREAKAGES), misses))
    return 1 if misses else 0


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(selftest())
    delivery = None
    if '--delivery' in sys.argv:
        delivery = sys.argv[sys.argv.index('--delivery') + 1]
    sys.exit(1 if run(HERE, delivery) else 0)
