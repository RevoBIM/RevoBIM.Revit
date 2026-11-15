# -*- coding: utf-8 -*-
"""RevoBIM PY - Style Manager bench check.

Runs under plain CPython from this folder. It parses script.py without importing
it and enforces the rules that have actually broken this tool in the past:

  1  every panel named in NAV_GROUPS has a class defined
  2  every panel class defines read / write / merge_impl (or inherits them)
  3  every panel column set carries Name, Status and ElemId
  4  every icon a panel asks for exists in icons/
  5  every self.find('X') resolves to an x:Name in some XAML block
  6  every XAML block parses as XML
  7  no f-strings, no print, no bare .IntegerValue, no System.Uri
  8  every global name a function reaches for exists
  9  leading column count matches the columns actually built
 10  wire() attaches through hook() or a try, never directly
 11  no method is defined twice in a class
 12  every self.something a class uses is defined on it or a base
 13  no panel column reuses a name the table keeps for itself
 14  row filters compare against a column of the matching type
 15  every tab that finds duplicates declares duplicate rules it can actually read
 16  no status-box writes one line at a time in a loop
 17  rows are looked up through the index, never by scanning
 18  a multi-group merge runs each group in its own try, so one refusal
     cannot stop the groups after it

Run with --selftest to break each rule on purpose in memory and confirm the rule
reports it. A rule that cannot catch its own breakage is inert.

Rule 12 is here because a block rewrite once deleted two methods that sat between
the markers it replaced. Everything still parsed, every other rule passed, and the
tool only fell over in Revit with "object has no attribute 'on_excel'".

Rule 1 is here because a patch once deleted a panel class while replacing the
block above it, and the only symptom was a NameError at start-up.
"""
import ast
import io
import os
import re
import sys
import symtable
import xml.dom.minidom

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.path.join(HERE, 'script.py')
FAILURES = []


def fail(rule, message):
    FAILURES.append('[%s] %s' % (rule, message))


def load():
    return io.open(SOURCE, encoding='utf-8').read()


def xaml_blocks(text):
    shared = re.search(r'SHARED_STYLES = u"""(.*?)"""', text, re.S)
    shared_text = shared.group(1) if shared else ''
    out = {}
    for match in re.finditer(r'^([A-Z_]+_XAML|CHIP_TEMPLATE) = u"""(.*?)"""',
                             text, re.S | re.M):
        body = match.group(2).replace('__STYLES__', shared_text)
        out[match.group(1)] = body
    if shared:
        out['SHARED_STYLES'] = (
            '<ResourceDictionary '
            'xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" '
            'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml">%s'
            '</ResourceDictionary>' % shared_text)
    return out


def check_panels(text, tree):
    classes = dict((n.name, n) for n in tree.body if isinstance(n, ast.ClassDef))

    match = re.search(r'NAV_GROUPS = \[(.*?)\n\]', text, re.S)
    if not match:
        fail('1', 'NAV_GROUPS table not found')
        return
    named = re.findall(r"'(\w+Panel)'", match.group(1))
    if not named:
        fail('1', 'NAV_GROUPS lists no panels')
    for name in named:
        if name not in classes:
            fail('1', '%s is named in NAV_GROUPS but no class is defined' % name)

    for name in named:
        node = classes.get(name)
        if node is None:
            continue
        methods = set()
        bases = [node]
        while bases:
            current = bases.pop()
            methods |= set(m.name for m in current.body
                           if isinstance(m, ast.FunctionDef))
            for base in current.bases:
                base_name = getattr(base, 'id', None)
                if base_name in classes:
                    bases.append(classes[base_name])
        for required in ('read', 'write', 'merge_impl'):
            if required not in methods:
                fail('2', '%s does not provide %s()' % (name, required))

        body = ast.get_source_segment(text, node) or ''
        columns = re.findall(r"'name': '(\w+)'", body)
        if columns:
            for required in ('Name', 'Status', 'ElemId'):
                if required not in columns:
                    fail('3', '%s columns are missing %s' % (name, required))

        icon = re.search(r"icon_file = '([^']+)'", body)
        if icon and not os.path.isfile(os.path.join(HERE, 'icons', icon.group(1))):
            fail('4', '%s asks for icons/%s which does not exist'
                 % (name, icon.group(1)))


def check_names(text):
    blocks = xaml_blocks(text)
    declared = set()
    for body in blocks.values():
        declared |= set(re.findall(r'x:Name="([^"]+)"', body))
    used = set(re.findall(r"self\.find\('([^']+)'\)", text))
    used |= set(re.findall(r"FindName\('([^']+)'\)", text))
    for name in sorted(used - declared):
        fail('5', "find('%s') has no matching x:Name" % name)

    for label, body in blocks.items():
        try:
            xml.dom.minidom.parseString(body.encode('utf-8'))
        except Exception as ex:
            fail('6', '%s does not parse as XML: %s' % (label, ex))


def docstring_lines(tree):
    """Line numbers covered by a docstring, so prose about a banned name does not
    trip the rule that bans it."""
    covered = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)):
            continue
        body = getattr(node, 'body', None)
        if not body:
            continue
        first = body[0]
        value = getattr(first, 'value', None)
        text = getattr(value, 'value', None)
        if not isinstance(first, ast.Expr) or not isinstance(text, str):
            continue
        start = getattr(first, 'lineno', 0)
        end = getattr(value, 'end_lineno', start)
        for line in range(start - text.count('\n') - 1, end + 1):
            covered.add(line)
    return covered


def check_forbidden(text, tree):
    skip = docstring_lines(tree)
    for index, line in enumerate(text.split('\n'), 1):
        stripped = line.strip()
        if stripped.startswith('#') or index in skip:
            continue
        if re.search(r"\bf'''|\bf\"\"\"|\bf'|\bf\"", line):
            fail('7', 'line %d looks like an f-string' % index)
        if re.match(r'^\s*print\s*\(', line):
            fail('7', 'line %d uses print()' % index)
        if 'System.Uri' in line or re.search(r'from System import .*\bUri\b', line):
            fail('7', 'line %d uses System.Uri' % index)

    # .IntegerValue is allowed only inside the eid_int helper, judged by the
    # helper's real extent rather than a line count above the use
    helper = [n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name in ('eid_int', 'eid_value')]
    spans = [(n.lineno, n.end_lineno) for n in helper]
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == 'IntegerValue':
            if not any(a <= node.lineno <= b for a, b in spans):
                fail('7', 'line %d uses .IntegerValue outside the helper' % node.lineno)


def check_column_indexing(text):
    """Dropdown columns are addressed by index, so the number of columns built in
    front of them has to match the counter. An edit that adds or removes a leading
    column without updating it binds the options to the wrong column."""
    try:
        block = text[text.index('    def build_columns(self):'):
                     text.index('    def wire(self):')]
    except ValueError:
        fail('9', 'build_columns or wire is missing')
        return
    added = block.count('self.grid.Columns.Add(')
    counted = block.count('self.leading_columns += 1')
    if added - 1 != counted:
        fail('9', 'build_columns adds %d leading column(s) but counts %d'
             % (added - 1, counted))
    if 'DataGridLength(' in block:
        fail('9', 'build_columns should size columns through column_width()')
    for name in re.findall(r'self\.grid\.Columns\[([^\]]+)\]', text):
        if 'leading_columns' not in name:
            fail('9', 'grid.Columns[%s] hard-codes a column position' % name.strip())


def check_construction(text):
    try:
        block = text[text.index('    def wire(self):'):
                     text.index('    def configure_panel(self):')]
    except ValueError:
        fail('10', 'wire or configure_panel is missing')
        return
    for line in block.split('\n'):
        stripped = line.strip()
        if re.match(r"self\.(find\('[^']+'\)|grid)\.\w+ \+= ", stripped):
            if 'try' not in block[max(0, block.index(stripped) - 60):block.index(stripped)]:
                fail('10', 'wire() attaches directly: %s' % stripped)


def check_no_duplicate_methods(tree):
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        names = [m.name for m in node.body if isinstance(m, ast.FunctionDef)]
        for name in sorted(set(n for n in names if names.count(n) > 1)):
            fail('11', '%s defines %s() more than once' % (node.name, name))


def check_self_attributes(tree):
    """Every self.x referenced in a class must be defined on it or on a base.

    Catches a method deleted by a block rewrite: the call sites still parse, so
    nothing else notices until Revit raises AttributeError at run time.
    """
    classes = dict((n.name, n) for n in tree.body if isinstance(n, ast.ClassDef))

    def defined_on(node, seen=None):
        seen = seen or set()
        if node.name in seen:
            return set()
        seen.add(node.name)
        names = set()
        for item in ast.walk(node):
            if isinstance(item, ast.FunctionDef):
                names.add(item.name)
            elif isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Attribute) and \
                            isinstance(target.value, ast.Name) and \
                            target.value.id == 'self':
                        names.add(target.attr)
                    elif isinstance(target, ast.Name):
                        names.add(target.id)
            elif isinstance(item, ast.AugAssign):
                target = item.target
                if isinstance(target, ast.Attribute) and \
                        isinstance(target.value, ast.Name) and target.value.id == 'self':
                    names.add(target.attr)
        for base in node.bases:
            base_name = getattr(base, 'id', None)
            if base_name in classes:
                names |= defined_on(classes[base_name], seen)
        return names

    builtin_attrs = set(['__class__', '__dict__', '__doc__', '__module__', '__name__'])
    for name, node in classes.items():
        available = defined_on(node) | builtin_attrs
        used = set()
        for item in ast.walk(node):
            if isinstance(item, ast.Attribute) and isinstance(item.value, ast.Name) \
                    and item.value.id == 'self':
                used.add(item.attr)
        for missing in sorted(used - available):
            fail('12', '%s uses self.%s which is not defined on it or a base'
                 % (name, missing))


def check_reserved_columns(text, tree):
    """A panel column may not reuse one of the table's own column names.

    The DataTable refuses the second column of that name and the whole tab fails
    to build - which is how the Parameters tab, whose "Group Under" column was
    named Group, came up empty.
    """
    match = re.search(r'RESERVED_COLUMNS = \((.*?)\)', text, re.S)
    if not match:
        fail('13', 'RESERVED_COLUMNS table not found')
        return
    reserved = set(re.findall(r"'(\w+)'", match.group(1)))
    for node in tree.body:
        if not (isinstance(node, ast.ClassDef) and node.name.endswith('Panel')):
            continue
        body = ast.get_source_segment(text, node) or ''
        for name in sorted(set(re.findall(r"'name': '(\w+)'", body)) & reserved):
            fail('13', '%s has a column named %s, which the table reserves'
                 % (node.name, name))


def check_filter_types(text, tree):
    """A DataView row filter refuses an unquoted number against a text column.

    The "unused only" filter has to know whether the usage column was declared as
    an int, so the clause is built from the column spec rather than hard-coded.
    """
    if re.search(r'clauses\.append\("\[(Uses|TotalUses)\] = 0"\)', text):
        fail('14', 'the unused filter hard-codes a numeric comparison - build it '
                   'from the column type instead')

    for node in tree.body:
        if not (isinstance(node, ast.ClassDef) and node.name.endswith('Panel')):
            continue
        body = ast.get_source_segment(text, node) or ''
        for match in re.finditer(
                r"\{'header': '[^']*', 'name': '(Uses|TotalUses)'(.*?)\}", body, re.S):
            declared_int = "'type': 'int'" in match.group(2)
            analysed = 'needs_analysis = True' in body
            if analysed and declared_int:
                fail('14', '%s counts usage by Analyze so %s holds "?" and cannot be '
                     'an int column' % (node.name, match.group(1)))


def panel_classes(text, tree):
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name.endswith('Panel') \
                and node.name != 'BasePanel':
            yield node, ast.get_source_segment(text, node) or ''


def check_dup_rules(text, tree):
    """A tab that looks for duplicates must say what it compares, and every rule
    must name a column the tab shows or a key its reader stores separately -
    otherwise the rule quietly compares blanks and calls everything a duplicate."""
    for node, body in panel_classes(text, tree):
        if 'allow_duplicates = False' in body:
            if re.search(r'^    dup_rules = \[', body, re.M):
                fail('15', '%s turns duplicates off but still declares dup_rules'
                     % node.name)
            continue
        match = re.search(r'^    dup_rules = \[(.*?)\]\n', body, re.M | re.S)
        if not match:
            fail('15', '%s finds duplicates but declares no dup_rules' % node.name)
            continue
        rules = re.findall(r"\('(\w+)', '[^']*', (True|False)\)", match.group(1))
        if not rules:
            fail('15', '%s dup_rules could not be read' % node.name)
            continue
        keys = [k for k, _t in rules]
        for key in sorted(set(k for k in keys if keys.count(k) > 1)):
            fail('15', '%s lists the rule %s twice' % (node.name, key))
        if not [t for _k, t in rules if t == 'True']:
            fail('15', '%s has no rule ticked by default' % node.name)
        columns = set(re.findall(r"'name': '(\w+)'", body))
        extra = re.search(r'dup_extra_keys = \[(.*?)\]', body)
        extras = set(re.findall(r"'(\w+)'", extra.group(1))) if extra else set()
        for key in keys:
            if key not in columns and key not in extras:
                fail('15', '%s rule %s is neither a column nor a dup_extra_key'
                     % (node.name, key))


def check_batched_logging(text):
    """The status box is written a block at a time. A loop calling post() per line
    crosses to the UI thread and repaints once per line."""
    for match in re.finditer(r'\n(\s+)for \w+ in [^\n:]+:\n\1    self\.(post|log)\(\w+\)\n',
                             text):
        line = text[:match.start()].count('\n') + 2
        fail('16', 'line %d writes the status box one line at a time - use %s_many'
             % (line, match.group(2)))


def check_row_index(text):
    try:
        block = text[text.index('    def row_by_id(self, rid):'):]
        block = block[:block.index('\n    def ', 10)]
    except ValueError:
        fail('17', 'row_by_id is missing')
        return
    code = '\n'.join(l for l in block.split('\n') if not l.strip().startswith('#'))
    if 'for ' in code or 'row_index' not in code:
        fail('17', 'row_by_id scans the rows instead of using row_index')
    if "self.row_index = dict(" not in text:
        fail('17', 'populate never builds row_index')


def check_group_merge_isolation(text):
    try:
        block = text[text.index('    def _run_group_merge(self'):]
        block = block[:block.index('\n    def ', 10)]
    except ValueError:
        fail('18', '_run_group_merge is missing')
        return
    if not re.search(r'for [^\n]+ in enumerate\(jobs\):.*?\n\s+try:\n\s+'
                     r'lines\.extend\(self\.merge_impl\(', block, re.S):
        fail('18', '_run_group_merge does not wrap each group in its own try')


def check_globals(text):
    try:
        table = symtable.symtable(text, 'script.py', 'exec')
    except Exception as ex:
        fail('8', 'could not build a symbol table: %s' % ex)
        return
    top = set(table.get_identifiers())
    builtins = set(dir(__builtins__)) | set(
        ['unicode', 'reduce', 'xrange', 'basestring', 'long'])

    def walk(node, scope_names):
        for child in node.get_children():
            names = scope_names | set(child.get_identifiers())
            for symbol in child.get_symbols():
                if symbol.is_global() and symbol.get_name() not in top \
                        and symbol.get_name() not in builtins:
                    fail('8', '%s reaches for undefined global "%s"'
                         % (child.get_name(), symbol.get_name()))
            walk(child, names)

    walk(table, top)


def run_all(text):
    del FAILURES[:]
    try:
        tree = ast.parse(text)
    except SyntaxError as ex:
        fail('0', 'script.py does not parse: %s' % ex)
        return list(FAILURES)
    check_panels(text, tree)
    check_names(text)
    check_forbidden(text, tree)
    check_column_indexing(text)
    check_construction(text)
    check_no_duplicate_methods(tree)
    check_self_attributes(tree)
    check_reserved_columns(text, tree)
    check_filter_types(text, tree)
    check_dup_rules(text, tree)
    check_batched_logging(text)
    check_row_index(text)
    check_group_merge_isolation(text)
    check_globals(text)
    return list(FAILURES)


# (rule that must fire, description, text to find, what to put instead)
BREAKAGES = [
    ('1', 'delete a panel class named in the ribbon',
     'class TagStylePanel(BasePanel):', 'class TagStylePanelGone(BasePanel):'),
    ('7', 'read an id with .IntegerValue outside the helper',
     '        tid = eid_int(tt.Id)', '        tid = int(tt.Id.IntegerValue)'),
    ('9', 'drop a leading column counter',
     '                self.grid.Columns.Add(chip)\n                self.leading_columns += 1',
     '                self.grid.Columns.Add(chip)'),
    ('12', 'delete a method the panel calls',
     '    def on_excel(self, sender, args):', '    def on_excel_gone(self, sender, args):'),
    ('13', 'name a parameter column Group',
     "'name': 'ParamGroup'", "'name': 'Group'"),
    ('14', 'hard-code the unused comparison',
     '            clause = self.unused_clause()\n            if clause:\n                clauses.append(clause)',
     '            clauses.append("[Uses] = 0")'),
    ('15', 'give text styles a rule with no column',
     "('TabSize', 'Tab size', True)", "('TabSpacing', 'Tab size', True)"),
    ('15', 'leave line styles with no rules',
     "    dup_rules = [('Weight', 'Line weight', True),", "    no_rules = [('Weight', 'Line weight', True),"),
    ('16', 'log a merge report line by line',
     '        self.log_many(self.startup_errors)',
     '        for line in self.startup_errors:\n            self.log(line)'),
    ('17', 'look rows up by scanning',
     '        return self.row_index.get(rid)',
     '        for row in self.rows:\n            if row[\'id\'] == rid:\n                return row\n        return None'),
    ('18', 'let one refused group stop the rest',
     '            try:\n                lines.extend(self.merge_impl(doc, rows, result))\n'
     '                done += 1\n            except Exception as ex:\n'
     "                lines.append('Group %s failed and was left as it was: %s' % (label, ex))",
     '            lines.extend(self.merge_impl(doc, rows, result))\n            done += 1'),
]


def selftest():
    text = load()
    clean = run_all(text)
    if clean:
        sys.stdout.write('Cannot selftest - the real script already fails:\n')
        for line in clean:
            sys.stdout.write('  %s\n' % line)
        sys.exit(1)
    inert = []
    for rule, label, old, new in BREAKAGES:
        if old not in text:
            inert.append('%s - "%s": the text to break was not found' % (rule, label))
            continue
        found = run_all(text.replace(old, new, 1))
        hit = [f for f in found if f.startswith('[%s]' % rule)]
        status = 'caught' if hit else 'MISSED'
        sys.stdout.write('  rule %-3s %-6s %s\n' % (rule, status, label))
        if not hit:
            inert.append('%s - %s' % (rule, label))
    if inert:
        sys.stdout.write('SELFTEST FAILED - inert rules:\n')
        for line in inert:
            sys.stdout.write('  %s\n' % line)
        sys.exit(1)
    sys.stdout.write('Selftest passed - every rule caught its own breakage.\n')


def main():
    if '--selftest' in sys.argv:
        selftest()
        return
    run_all(load())
    report()


def report():
    if FAILURES:
        sys.stdout.write('FAILED - %d problem(s)\n' % len(FAILURES))
        for line in FAILURES:
            sys.stdout.write('  %s\n' % line)
        sys.exit(1)
    sys.stdout.write('All bench checks passed.\n')


if __name__ == '__main__':
    main()
