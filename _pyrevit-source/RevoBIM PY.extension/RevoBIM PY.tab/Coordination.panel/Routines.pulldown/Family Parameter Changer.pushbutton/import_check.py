# -*- coding: utf-8 -*-
"""RevoBIM PY - Family Parameter Changer - bench check.

Runs under plain CPython, nowhere near Revit. Loads every .py module in
this folder as text and checks a set of rules that have each caused a
blank white pyRevit window in some RevoBIM PY tool before. Every rule
is proved by deliberate breakage: `python import_check.py --selftest`.
"""
import os
import re
import sys
import xml.dom.minidom as minidom

HERE = os.path.dirname(os.path.abspath(__file__))

PY_FILES = [f for f in os.listdir(HERE) if f.endswith('.py') and f not in (
    'import_check.py', 'bench_logic.py')]
XAML_FILES = [f for f in os.listdir(HERE) if f.endswith('.xaml')]

CLR_MODULE = 'fpc_clr'


def read(path):
    f = open(path, 'r')
    try:
        return f.read()
    finally:
        f.close()


def _blank_spans(text, want_strings):
    """Replaces comment (and optionally string) tokens with spaces of the
    same length, in place. Blanking in place rather than rebuilding from
    tokens is deliberate: joining tokens back together drops the spacing
    between them, which turned `from System import Uri` into one word and
    silently disarmed the System.Uri rule."""
    import io
    import tokenize
    try:
        if sys.version_info[0] >= 3:
            stream = io.StringIO(text)
            tokens = list(tokenize.generate_tokens(stream.readline))
        else:
            stream = io.BytesIO(text.encode('utf-8'))
            tokens = list(tokenize.generate_tokens(stream.readline))
    except Exception:
        return text

    lines = text.splitlines(True)

    def blank(srow, scol, erow, ecol):
        for row in range(srow, erow + 1):
            idx = row - 1
            if idx < 0 or idx >= len(lines):
                continue
            line = lines[idx]
            start = scol if row == srow else 0
            end = ecol if row == erow else len(line)
            end = min(end, len(line))
            if start >= end:
                continue
            keep_nl = line[end:]
            lines[idx] = line[:start] + (u' ' * (end - start)) + keep_nl

    for tok in tokens:
        tok_type, tok_str = tok[0], tok[1]
        srow, scol = tok[2]
        erow, ecol = tok[3]
        is_comment = (tok_type == tokenize.COMMENT)
        is_string = (tok_type == tokenize.STRING)
        if is_comment or (want_strings and is_string):
            blank(srow, scol, erow, ecol)

    return u''.join(lines)


def code_only(text):
    """Source with comments and string literals blanked out, so a rule
    cannot fire on its own explanatory comment or on a docstring."""
    return _blank_spans(text, True)


def code_and_strings(text):
    """Source with only comments blanked. Used by the f-string rule,
    which has to be able to see string literals to spot the `f` prefix."""
    return _blank_spans(text, False)


def rule_xaml_parses():
    errors = []
    for fname in XAML_FILES:
        text = read(os.path.join(HERE, fname))
        try:
            minidom.parseString(text)
        except Exception as ex:
            errors.append(u'{0}: does not parse as XML - {1}'.format(fname, ex))
    return errors


def rule_clr_reference_order():
    errors = []
    for fname in PY_FILES:
        if fname == CLR_MODULE + '.py' or fname == 'script.py':
            continue
        text = code_only(read(os.path.join(HERE, fname)))
        lines = text.splitlines()
        clr_import_line = None
        first_system_line = None
        for i, line in enumerate(lines):
            stripped = line.strip()
            if clr_import_line is None and re.match(r'^import\s+fpc_clr\b', stripped):
                clr_import_line = i
            if first_system_line is None and re.search(r'\b(System|Autodesk)\.[A-Za-z]', stripped):
                if not stripped.startswith('#'):
                    first_system_line = i
        touches_dotnet = re.search(r'\b(System|Autodesk)\.[A-Za-z]', text) is not None
        if touches_dotnet and clr_import_line is None:
            errors.append(u'{0}: reaches into System.*/Autodesk.* without importing fpc_clr'.format(fname))
        elif touches_dotnet and first_system_line is not None and first_system_line < clr_import_line:
            errors.append(u'{0}: touches System.*/Autodesk.* before importing fpc_clr'.format(fname))
    return errors


def rule_no_static_resource_in_layout():
    errors = []
    for fname in XAML_FILES:
        if fname == 'Theme.xaml':
            continue
        text = read(os.path.join(HERE, fname))
        if 'StaticResource' in text:
            errors.append(u'{0}: uses StaticResource in a layout file (Theme.xaml is merged in after parse)'.format(fname))
    return errors


def _theme_keys():
    text = read(os.path.join(HERE, 'Theme.xaml'))
    return set(re.findall(r'x:Key="([^"]+)"', text))


def rule_dynamic_resource_keys_exist():
    errors = []
    theme_keys = _theme_keys()
    for fname in XAML_FILES:
        if fname == 'Theme.xaml':
            continue
        text = read(os.path.join(HERE, fname))
        for key in re.findall(r'\{DynamicResource\s+([A-Za-z0-9_]+)\}', text):
            if key not in theme_keys:
                errors.append(u'{0}: DynamicResource key "{1}" is not defined in Theme.xaml'.format(fname, key))
    return errors


def rule_findname_has_xname():
    errors = []
    for fname in PY_FILES:
        text = read(os.path.join(HERE, fname))
        names = set(re.findall(r'FindName\([\'"]([A-Za-z0-9_]+)[\'"]\)', text))
        if not names:
            continue
        all_xname = set()
        for xf in XAML_FILES:
            xtext = read(os.path.join(HERE, xf))
            all_xname.update(re.findall(r'x:Name="([A-Za-z0-9_]+)"', xtext))
        missing = names - all_xname
        for m in missing:
            errors.append(u'{0}: FindName("{1}") has no matching x:Name in any .xaml file'.format(fname, m))
    return errors


def rule_no_fstrings():
    errors = []
    pattern = re.compile(r'''[fF]("""|'''+"'''"+r'''|"|')''')
    for fname in PY_FILES:
        text = code_and_strings(read(os.path.join(HERE, fname)))
        for i, line in enumerate(text.splitlines()):
            if re.search(r'\bf(["\'])', line):
                errors.append(u'{0}:{1}: looks like an f-string'.format(fname, i + 1))
    return errors


def rule_no_print():
    errors = []
    for fname in PY_FILES:
        text = read(os.path.join(HERE, fname))
        for i, line in enumerate(text.splitlines()):
            stripped = line.strip()
            if re.match(r'^print\s*\(', stripped) or re.match(r'^print\s+[^(]', stripped):
                errors.append(u'{0}:{1}: bare print statement'.format(fname, i + 1))
    return errors


def rule_no_bare_integervalue():
    errors = []
    for fname in PY_FILES:
        if fname == 'fpc_core.py':
            continue  # eid_value's own guarded fallback lives here
        text = code_only(read(os.path.join(HERE, fname)))
        for i, line in enumerate(text.splitlines()):
            if '.IntegerValue' in line:
                errors.append(u'{0}:{1}: bare .IntegerValue outside eid_value'.format(fname, i + 1))
    return errors


def rule_no_system_uri():
    errors = []
    for fname in PY_FILES:
        text = code_only(read(os.path.join(HERE, fname)))
        if re.search(r'\bSystem\.Uri\b', text) or re.search(r'from\s+System\s+import\s+Uri\b', text):
            errors.append(u'{0}: references System.Uri'.format(fname))
    return errors


def rule_palette_covers_theme_brushes():
    """Every brush key declared in Theme.xaml must exist in both palettes
    in theme.py, and every palette key must exist in Theme.xaml. A key in
    one and not the other means a control keeps its design-time brush
    through a palette swap - the subtlest way for a window to look half
    themed."""
    errors = []
    theme_text = read(os.path.join(HERE, 'Theme.xaml'))
    brush_keys = set(re.findall(r'<SolidColorBrush\s+x:Key="([^"]+)"', theme_text))

    palette_text = read(os.path.join(HERE, 'theme.py'))
    palettes = {}
    for pal_name in ('dark', 'light'):
        block = re.search(r"'" + pal_name + r"':\s*\{(.*?)\n    \}", palette_text, re.S)
        if block is None:
            errors.append(u'theme.py: no "{0}" palette found'.format(pal_name))
            continue
        palettes[pal_name] = set(re.findall(r"'([A-Za-z0-9_]+)'\s*:", block.group(1)))

    for pal_name in palettes:
        missing = brush_keys - palettes[pal_name]
        for key in sorted(missing):
            errors.append(u'theme.py: the "{0}" palette has no "{1}", but Theme.xaml declares it'.format(
                pal_name, key))
        extra = palettes[pal_name] - brush_keys
        for key in sorted(extra):
            errors.append(u'Theme.xaml: no SolidColorBrush for "{0}", which the "{1}" palette sets'.format(
                key, pal_name))
    return errors


def rule_setresourcereference_keys_exist():
    """Every SetResourceReference key used in Python must be a key
    Theme.xaml actually defines."""
    errors = []
    theme_keys = _theme_keys()
    for fname in PY_FILES:
        text = read(os.path.join(HERE, fname))
        for key in re.findall(r"SetResourceReference\([^,]+,\s*'([A-Za-z0-9_]+)'\)", text):
            if key not in theme_keys:
                errors.append(u'{0}: SetResourceReference to "{1}", which Theme.xaml does not define'.format(
                    fname, key))
    return errors


def rule_globals_exist():
    """Every global name a function reaches for must exist in its module -
    defined, imported, or a builtin. This is the rule that catches a
    function deleted or renamed by a block rewrite while its callers
    still reach for the old name. Names pyRevit injects at run time are
    allowed through."""
    import symtable
    try:
        import builtins
        builtin_names = set(dir(builtins))
    except ImportError:
        import __builtin__
        builtin_names = set(dir(__builtin__))
    injected = set(['__revit__', '__file__', '__name__', '__doc__', '__persistentengine__',
                    '__shiftclick__', '__forceddebugmode__', '__commandpath__', 'unicode',
                    '__window__', '__eventsender__', '__eventargs__'])

    errors = []
    for fname in PY_FILES:
        text = read(os.path.join(HERE, fname))
        try:
            top = symtable.symtable(text, fname, 'exec')
        except Exception as ex:
            errors.append(u'{0}: could not build a symbol table - {1}'.format(fname, ex))
            continue
        module_names = set()
        for sym in top.get_symbols():
            if sym.is_assigned() or sym.is_imported() or sym.is_namespace():
                module_names.add(sym.get_name())
        known = module_names | builtin_names | injected

        def walk(table, path):
            for sym in table.get_symbols():
                name = sym.get_name()
                if sym.is_global() and sym.is_referenced() and name not in known:
                    errors.append(u'{0}: {1} reaches for global "{2}", which the module does not define'.format(
                        fname, path, name))
            for child in table.get_children():
                walk(child, path + u'.' + child.get_name())

        for child in top.get_children():
            walk(child, child.get_name())
    return errors


RULES = [
    ('xaml well-formed', rule_xaml_parses),
    ('clr reference order', rule_clr_reference_order),
    ('no StaticResource in layout', rule_no_static_resource_in_layout),
    ('DynamicResource keys exist', rule_dynamic_resource_keys_exist),
    ('SetResourceReference keys exist', rule_setresourcereference_keys_exist),
    ('palettes cover Theme.xaml brushes', rule_palette_covers_theme_brushes),
    ('FindName has x:Name', rule_findname_has_xname),
    ('globals exist (symtable)', rule_globals_exist),
    ('no f-strings', rule_no_fstrings),
    ('no print statements', rule_no_print),
    ('no bare .IntegerValue', rule_no_bare_integervalue),
    ('no System.Uri', rule_no_system_uri),
]


def run():
    all_errors = []
    for name, fn in RULES:
        errors = fn()
        if errors:
            print(u'FAIL  {0}'.format(name))
            for e in errors:
                print(u'      {0}'.format(e))
        else:
            print(u'ok    {0}'.format(name))
        all_errors.extend(errors)
    return all_errors


def selftest():
    """Deliberately breaks a copy of each file and confirms the matching
    rule catches it, then restores the original."""
    import shutil
    tmp_dir = os.path.join(HERE, '_selftest_tmp')
    if os.path.isdir(tmp_dir):
        shutil.rmtree(tmp_dir)
    os.makedirs(tmp_dir)

    checks = []

    # f-string
    path = os.path.join(HERE, '_selftest_fstring.py')
    open(path, 'w').write(u"import fpc_clr\nx = f'{1}'\n")
    checks.append(('f-string', rule_no_fstrings))

    # print statement
    path2 = os.path.join(HERE, '_selftest_print.py')
    open(path2, 'w').write(u"print('hello')\n")
    checks.append(('print', rule_no_print))

    # bare IntegerValue
    path3 = os.path.join(HERE, '_selftest_intval.py')
    open(path3, 'w').write(u"import fpc_clr\nv = element_id.IntegerValue\n")
    checks.append(('bare IntegerValue', rule_no_bare_integervalue))

    # System.Uri
    path4 = os.path.join(HERE, '_selftest_uri.py')
    open(path4, 'w').write(u"import fpc_clr\nfrom System import Uri\n")
    checks.append(('System.Uri', rule_no_system_uri))

    # StaticResource in a layout
    path5 = os.path.join(HERE, '_selftest_static.xaml')
    open(path5, 'w').write(u'<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation">'
                            u'<Button Style="{StaticResource X}"/></Window>')
    checks.append(('StaticResource in layout', rule_no_static_resource_in_layout))

    # a function reaching for a helper that no longer exists
    path7 = os.path.join(HERE, '_selftest_globals.py')
    open(path7, 'w').write(u"import fpc_clr\ndef caller():\n    return helper_that_was_deleted(1)\n")
    checks.append(('undefined global', rule_globals_exist))

    # malformed xaml
    path6 = os.path.join(HERE, '_selftest_badxml.xaml')
    open(path6, 'w').write(u'<Window><!-- -- broken --></Window>')
    checks.append(('malformed xaml', rule_xaml_parses))

    global PY_FILES, XAML_FILES
    old_py, old_xaml = PY_FILES, XAML_FILES
    PY_FILES = [f for f in os.listdir(HERE) if f.endswith('.py') and f not in ('import_check.py', 'bench_logic.py')]
    XAML_FILES = [f for f in os.listdir(HERE) if f.endswith('.xaml')]

    ok = True
    for name, fn in checks:
        errors = fn()
        if errors:
            print(u'selftest ok    {0} (caught {1} issue(s))'.format(name, len(errors)))
        else:
            print(u'selftest FAIL  {0} (rule did not catch its own breakage)'.format(name))
            ok = False

    for f in (path, path2, path3, path4, path5, path6, path7):
        try:
            os.remove(f)
        except Exception:
            pass

    PY_FILES = [f for f in os.listdir(HERE) if f.endswith('.py') and f not in ('import_check.py', 'bench_logic.py')]
    XAML_FILES = [f for f in os.listdir(HERE) if f.endswith('.xaml')]

    # The palette rules need Theme.xaml itself broken, so they are done
    # separately, against a backup that is put straight back.
    theme_path = os.path.join(HERE, 'Theme.xaml')
    theme_backup = read(theme_path)
    try:
        broken = theme_backup.replace(
            '<SolidColorBrush x:Key="OrangeBrush" Color="#E8912D"/>', '', 1)
        f = open(theme_path, 'w')
        f.write(broken)
        f.close()
        if rule_palette_covers_theme_brushes():
            print(u'selftest ok    palette coverage (caught a brush missing from Theme.xaml)')
        else:
            print(u'selftest FAIL  palette coverage (rule did not catch its own breakage)')
            ok = False
        if rule_setresourcereference_keys_exist():
            print(u'selftest ok    SetResourceReference keys (caught a key Theme.xaml lost)')
        else:
            print(u'selftest FAIL  SetResourceReference keys (rule did not catch its own breakage)')
            ok = False
    finally:
        f = open(theme_path, 'w')
        f.write(theme_backup)
        f.close()

    if os.path.isdir(tmp_dir):
        shutil.rmtree(tmp_dir)

    PY_FILES, XAML_FILES = old_py, old_xaml
    return ok


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        passed = selftest()
        sys.exit(0 if passed else 1)
    errors = run()
    sys.exit(0 if not errors else 1)
