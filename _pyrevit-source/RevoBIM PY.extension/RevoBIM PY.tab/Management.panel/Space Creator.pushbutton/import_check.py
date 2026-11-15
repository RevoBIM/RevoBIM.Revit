# -*- coding: utf-8 -*-
"""Bench check, not a ribbon button.

Compiles the tool and the shared modules, and enforces the house rules
that have actually broken this extension before, so they fail here rather
than as a blank white pyRevit window in Revit:

  - no f-strings, no bare .IntegerValue, no System.Uri, no print
  - the embedded XAML parses as XML
  - every x:Name referenced through FindName exists in the XAML

Run under plain CPython from this folder:  python import_check.py
"""
import io
import os
import re
import py_compile
import sys
from xml.dom import minidom

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.abspath(os.path.join(HERE, "..", "..", "..", "lib", "revobim"))

SCRIPT = os.path.join(HERE, "script.py")
TARGETS = [
    SCRIPT,
    os.path.join(LIB, "space_creator_core.py"),
    os.path.join(LIB, "theme.py"),
]

failures = []


def fail(rule, detail):
    failures.append(rule)
    print("FAIL  " + rule + " -- " + detail)


def ok(rule):
    print("OK    " + rule)


def read(path):
    return io.open(path, encoding="utf-8").read()


# 1 - everything compiles
for path in TARGETS:
    try:
        py_compile.compile(path, doraise=True)
    except Exception as ex:
        fail("compiles: " + os.path.basename(path), str(ex))
if not failures:
    ok("all modules compile")


# 2 - banned constructs
BANNED = [
    (r'(?<![A-Za-z0-9_])f"', "f-string"),
    (r"(?<![A-Za-z0-9_])f'", "f-string"),
    (r"\.IntegerValue", "bare .IntegerValue"),
    (r"from System import Uri", "System.Uri"),
    (r"System\.Uri", "System.Uri"),
    (r"^\s*print\s+[^(]", "print statement"),
]

# .IntegerValue is legitimate inside the two guarded helpers that exist to
# wrap it - they try .Value first and fall back. Anywhere else is a bug.
GUARDED_FUNCTIONS = ("eid_value", "workset_id_value")


def code_lines(text):
    """Yields (line_no, line) for real code only - comments and the inside
    of triple-quoted strings are skipped, so prose in a docstring that
    merely names a banned construct is not reported as using one. Not
    having this is why the first run of this check failed on its own
    documentation."""
    in_block = None
    for line_no, line in enumerate(text.splitlines(), 1):
        rest = line
        emitted = line
        while True:
            if in_block:
                idx = rest.find(in_block)
                if idx == -1:
                    emitted = ""
                    break
                rest = rest[idx + 3:]
                emitted = rest
                in_block = None
            else:
                d = rest.find('"""')
                s = rest.find("'''")
                if d == -1 and s == -1:
                    break
                if s == -1 or (d != -1 and d < s):
                    marker, idx = '"""', d
                else:
                    marker, idx = "'''", s
                closing = rest.find(marker, idx + 3)
                if closing == -1:
                    in_block = marker
                    emitted = rest[:idx]
                    break
                rest = rest[closing + 3:]
                emitted = rest
        stripped = emitted.strip()
        if not stripped or stripped.startswith("#"):
            continue
        yield line_no, emitted


def enclosing_function(text, line_no):
    name = None
    for i, line in enumerate(text.splitlines(), 1):
        if i > line_no:
            break
        m = re.match(r"\s*def\s+([A-Za-z_][A-Za-z0-9_]*)", line)
        if m:
            name = m.group(1)
    return name


banned_hits = 0
for path in TARGETS:
    text = read(path)
    for line_no, line in code_lines(text):
        for pattern, label in BANNED:
            if re.search(pattern, line):
                if label == "bare .IntegerValue" and \
                        enclosing_function(text, line_no) in GUARDED_FUNCTIONS:
                    continue
                banned_hits += 1
                fail("banned construct", "{0}:{1} {2}".format(
                    os.path.basename(path), line_no, label))
if banned_hits == 0:
    ok("no banned constructs")


# 3 - every embedded XAML block parses as XML
script_text = read(SCRIPT)
xaml_blocks = re.findall(r'(?:XAML|[A-Z_]+_XAML)\s*=\s*u"""(.*?)"""',
                         script_text, re.DOTALL)
if not xaml_blocks:
    fail("XAML found", "no XAML block in script.py")
    xaml = ""
else:
    parsed_ok = 0
    for index, block in enumerate(xaml_blocks):
        probe = re.sub(r"\{[A-Z_]+\}", "#000000", block)
        probe = probe.replace("__VERSION__", "0.0.0")
        # Shared fragments are not whole documents - they are injected into
        # a Window's resources. Wrap them in a root carrying the namespaces
        # so they are still checked rather than skipped.
        if "<Window" not in probe:
            probe = ('<Root xmlns="http://schemas.microsoft.com/winfx/2006/xaml/'
                     'presentation" xmlns:x="http://schemas.microsoft.com/winfx/'
                     '2006/xaml">' + probe + "</Root>")
        try:
            minidom.parseString(probe.encode("utf-8"))
            parsed_ok += 1
        except Exception as ex:
            fail("XAML parses as XML", "block " + str(index + 1) + ": " + str(ex))
    if parsed_ok == len(xaml_blocks):
        ok("every XAML block parses as XML (" + str(parsed_ok) + " blocks)")
    # names are checked across all blocks together
    xaml = "\n".join(xaml_blocks)


# 4 - every FindName has a matching x:Name / Name in the XAML
if xaml:
    referenced = set(re.findall(r'FindName\("([^"]+)"\)', script_text))

    # Follow aliases: the script does `find = window.FindName` and then
    # calls `find("X")`. Matching only literal FindName(...) calls made
    # this rule check nothing at all - the same way it silently did
    # nothing in Fire Damper Wall Type Push until it was caught.
    aliases = set(re.findall(
        r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*[A-Za-z_][A-Za-z0-9_.]*\.FindName\b",
        script_text))
    for alias in aliases:
        referenced |= set(re.findall(
            r'(?<![A-Za-z0-9_.])' + re.escape(alias) + r'\("([^"]+)"\)',
            script_text))

    declared = set(re.findall(r'\bName="([^"]+)"', xaml))
    xaml_names = declared
    missing = sorted(referenced - declared)
    if not referenced:
        fail("FindName rule is doing something", "no names found to check")
    elif missing:
        fail("FindName has a matching Name", ", ".join(missing))
    else:
        ok("every FindName resolves (" + str(len(referenced)) +
           " checked, aliases: " + (", ".join(sorted(aliases)) or "none") + ")")


# 5 - every core.* the script calls actually exists in the core module
import ast

core_path = os.path.join(LIB, "space_creator_core.py")
core_src = read(core_path)
core_names = set()
try:
    for node in ast.parse(core_src).body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            core_names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    core_names.add(target.id)
except Exception as ex:
    fail("core module parses", str(ex))

used = sorted(set(re.findall(r"\bcore\.([A-Za-z_][A-Za-z0-9_]*)", script_text)))
missing_core = [name for name in used if name not in core_names]
if missing_core:
    fail("every core.* call resolves", ", ".join(missing_core))
elif not used:
    fail("core.* rule is doing something", "no core calls found to check")
else:
    ok("every core.* call resolves (" + str(len(used)) + " checked)")


# 6 - the dispatcher is never pumped inside an open transaction.
#     Pumping between Transaction.Start() and Commit() can leave the write
#     with nothing committed - a documented failure elsewhere in this
#     extension - so progress calls that repaint must sit outside.
PUMPING_CALLS = r"\bprogress\.(start|advance|finish|pump)\("

txn_vars = set()
depth = 0
pump_hits = []
for line_no, line in code_lines(script_text):
    match = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*Transaction\(", line)
    if match:
        txn_vars.add(match.group(1))

    if depth > 0 and re.search(PUMPING_CALLS, line):
        pump_hits.append(line_no)

    for var in txn_vars:
        if re.search(r"\b" + var + r"\.Start\(\)", line):
            depth += 1
        if re.search(r"\b" + var + r"\.(Commit|RollBack)\(\)", line):
            depth = max(0, depth - 1)

if pump_hits:
    fail("no dispatcher pump inside a transaction",
         "line(s) " + ", ".join(str(n) for n in pump_hits))
elif not txn_vars:
    fail("pump rule is doing something", "no transactions found to track")
else:
    ok("no dispatcher pump inside a transaction (" +
       str(len(txn_vars)) + " transaction vars tracked)")


# 7 - the module compiles without SyntaxWarnings. A backslash sequence
#     inside a XAML string ("\\RevoBIM") is read by Python as an escape
#     before XAML ever sees it, and a silent warning today is a mangled
#     string tomorrow.
import warnings

warn_hits = []
for path in TARGETS:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            compile(read(path), path, "exec")
        except Exception as ex:
            fail("compiles cleanly", str(ex))
        for warning in caught:
            if issubclass(warning.category, SyntaxWarning):
                warn_hits.append(os.path.basename(path) + ": " +
                                 str(warning.message))

if warn_hits:
    fail("no SyntaxWarnings", "; ".join(warn_hits))
else:
    ok("no SyntaxWarnings")


# 8 - drawing separation lines must be followed by doc.Regenerate() before
#     any space is created. Revit does not treat a line drawn moments
#     earlier as bounding until it regenerates, and skipping it produces
#     "Space is not in a properly enclosed region" on every space.
line_calls = []
regen_calls = []
space_calls = []
for line_no, line in code_lines(script_text):
    if re.search(r"create_separation_lines_for_(room|curve_loops)\s*\(", line):
        line_calls.append(line_no)
    if re.search(r"\bdoc\.Regenerate\s*\(\s*\)", line):
        regen_calls.append(line_no)
    if re.search(r"create_space_(at_point|for_room)\s*\(", line):
        space_calls.append(line_no)

missing_regen = []
for line_no in line_calls:
    later_regen = [r for r in regen_calls if r > line_no]
    later_space = [s for s in space_calls if s > line_no]
    if not later_space:
        continue
    next_space = min(later_space)
    if not later_regen or min(later_regen) > next_space:
        missing_regen.append(line_no)

if not line_calls or not space_calls:
    fail("regenerate rule is doing something", "no calls found to track")
elif missing_regen:
    fail("regenerate between lines and spaces",
         "line(s) " + ", ".join(str(n) for n in missing_regen))
else:
    ok("regenerate between lines and spaces (" + str(len(line_calls)) +
       " line call(s) checked)")


# 9 - every global name a function reaches for actually exists in its
#     module. This is the rule that catches a definition removed by a
#     block rewrite: `AddFromListHandler` and `run_cleanup` were both
#     deleted by a line-range replacement of run_manual and neither was
#     noticed until the tool would not open, because nothing calls them
#     until main() runs.
import symtable
import builtins

for path in TARGETS:
    source = read(path)
    try:
        table = symtable.symtable(source, path, "exec")
    except Exception as ex:
        fail("symtable parses " + os.path.basename(path), str(ex))
        continue

    module_names = set(table.get_identifiers())
    builtin_names = set(dir(builtins))
    # Names the Revit/WPF runtime supplies that a bench cannot see.
    runtime_names = set(["__version__", "__title__", "__author__",
                         "__persistentengine__", "__file__", "__name__"])
    # IronPython 2 builtins that do not exist under the CPython running
    # this check. They are probed on purpose, inside try/except NameError,
    # to tell which engine the tool is on - so a reference to one is
    # correct code, not a missing definition.
    ipy2_builtins = set(["unicode", "basestring", "long", "xrange"])

    def walk(symbol_table, reported):
        for child in symbol_table.get_children():
            if child.get_type() == "function":
                for symbol in child.get_symbols():
                    name = symbol.get_name()
                    if not symbol.is_global():
                        continue
                    if name in module_names or name in builtin_names \
                            or name in runtime_names or name in ipy2_builtins:
                        continue
                    key = (os.path.basename(path), child.get_name(), name)
                    if key in reported:
                        continue
                    reported.add(key)
                    fail("global name exists",
                         "{0}: {1}() reaches for '{2}'".format(*key))
            walk(child, reported)

    walk(table, set())

if not [f for f in failures if f == "global name exists"]:
    ok("every global name a function reaches for exists")


# 10 - no raw `.Elevation` outside the level_elevation helper.
#      Level.Elevation is relative to the level's Elevation Base, which on
#      a survey-coordinated project is 83m away from the internal
#      coordinates every geometry point is in. Comparing the two picked
#      the basement for a level 4 room. Only level_elevation() may read it.
elevation_hits = []
for path in TARGETS:
    text = read(path)
    inside_helper = False
    for line_no, line in code_lines(text):
        if re.match(r"\s*def\s+level_elevation\b", line):
            inside_helper = True
            continue
        if inside_helper and re.match(r"\s*def\s+", line):
            inside_helper = False
        if inside_helper:
            continue
        if re.search(r"(?<!Project)\.Elevation\b", line):
            elevation_hits.append(os.path.basename(path) + ":" + str(line_no))

if elevation_hits:
    fail("no raw .Elevation outside level_elevation", ", ".join(elevation_hits))
else:
    ok("no raw .Elevation outside level_elevation")


# 11 - names looked up through a variable. wire_resize_grips does
#      find(name) in a loop, so rule 4 cannot see the eight grip names -
#      a typo in one would silently leave that edge unresizable.
grip_names = set(re.findall(r'"(Grip[A-Za-z]+)"', script_text))
missing_grips = sorted(n for n in grip_names if n not in xaml_names)
if not grip_names:
    fail("grip names checked", "no grip names found in script.py")
elif missing_grips:
    fail("grip names exist in XAML", ", ".join(missing_grips))
else:
    ok("every grip name exists in XAML (" + str(len(grip_names)) + " checked)")


print("")
if failures:
    print(str(len(failures)) + " FAILURE(S)")
    sys.exit(1)
print("All bench checks passed.")
