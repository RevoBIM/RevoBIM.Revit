# -*- coding: utf-8 -*-
"""Bench check for Sheet name push - run with plain CPython.

Catches, off-Revit, the classes of bug that otherwise show up as a blank
white pyRevit window:

  * f-strings (IronPython 2.7 cannot parse them)
  * bare .IntegerValue outside the guarded eid_value helper
    (removed in Revit 2026)
  * "from System import Uri" (throws on Revit 2025+)
  * malformed XAML
  * syntax errors in script.py

Usage:  python import_check.py
"""

import io
import os
import re
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "script.py")
XAMLS = ["ui.xaml", "results.xaml", "settings.xaml",
         "findreplace.xaml", "affix.xaml"]

failures = []


def read(path):
    with io.open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def code_lines():
    """script.py lines with comments and string literals blanked out.

    Without this the checks match their own descriptions in the module
    docstring and report false failures.
    """
    import tokenize
    try:
        from StringIO import StringIO
    except ImportError:
        from io import StringIO

    src = read(SCRIPT)
    lines = src.splitlines()
    blanked = list(lines)

    try:
        toks = list(tokenize.generate_tokens(StringIO(src).readline))
    except Exception:
        return list(enumerate(lines, 1))

    for tok_type, tok_str, start, end, _ in toks:
        if tok_type not in (tokenize.STRING, tokenize.COMMENT):
            continue
        srow, scol = start
        erow, ecol = end
        for row in range(srow, erow + 1):
            idx = row - 1
            if idx >= len(blanked):
                continue
            line = blanked[idx]
            a = scol if row == srow else 0
            b = ecol if row == erow else len(line)
            blanked[idx] = line[:a] + (" " * max(0, b - a)) + line[b:]

    return list(enumerate(blanked, 1))


def check_syntax():
    src = read(SCRIPT)
    try:
        compile(src, SCRIPT, "exec")
    except SyntaxError as ex:
        failures.append("script.py syntax error: {0}".format(ex))


def check_fstrings():
    for num, line in code_lines():
        if re.search(r"""(^|[^A-Za-z0-9_])[fF](['"])""", line):
            failures.append("f-string at script.py:{0}".format(num))


def check_integervalue():
    inside_helper = False
    for num, line in code_lines():
        if line.strip().startswith("def eid_value"):
            inside_helper = True
            continue
        if inside_helper and line and not line[0].isspace():
            inside_helper = False
        if ".IntegerValue" in line and not inside_helper:
            failures.append(
                "bare .IntegerValue at script.py:{0} - "
                "use eid_value()".format(num))


def check_uri():
    code = "\n".join(line for _, line in code_lines())
    if re.search(r"from\s+System\s+import\s+.*\bUri\b", code) \
            or "System.Uri" in code:
        failures.append(
            "System.Uri referenced - throws on Revit 2025+; "
            "load images via MemoryStream instead")


def check_xaml():
    for name in XAMLS:
        path = os.path.join(HERE, name)
        if not os.path.exists(path):
            failures.append("missing {0}".format(name))
            continue
        try:
            ET.parse(path)
        except Exception as ex:
            failures.append("{0} malformed: {1}".format(name, ex))


def check_handlers():
    """Every Click=/TextChanged=/MouseLeftButtonDown= in XAML needs a method."""
    src = read(SCRIPT)
    for name in XAMLS:
        path = os.path.join(HERE, name)
        if not os.path.exists(path):
            continue
        xaml = read(path)
        for handler in set(re.findall(
                r'(?:Click|TextChanged|MouseLeftButtonDown)="([A-Za-z_]\w*)"', xaml)):
            if ("def " + handler) not in src:
                failures.append(
                    "{0} references handler '{1}' "
                    "with no def in script.py".format(name, handler))


def check_named_controls():
    """Every self.<name> the script touches should be an x:Name in a XAML."""
    import re as _re
    code = "\n".join(line for _, line in code_lines())
    used = set(_re.findall(r"self\.((?:tb|cb|btn|sp|img|rb|col|sv|brd)_\w+)", code))
    declared = set()
    for name in XAMLS:
        path = os.path.join(HERE, name)
        if os.path.exists(path):
            declared |= set(_re.findall(r'x:Name="(\w+)"', read(path)))
    for name in sorted(used - declared):
        failures.append(
            "script.py uses self.{0} but no x:Name='{0}' in any XAML".format(name))


def check_icons():
    for png in ("icon.png", "gear.png", "findreplace.png", "affix.png"):
        if not os.path.exists(os.path.join(HERE, png)):
            failures.append("missing {0}".format(png))


def main():
    for fn in (check_syntax, check_fstrings, check_integervalue,
               check_uri, check_xaml, check_handlers,
               check_named_controls, check_icons):
        fn()

    if failures:
        sys.stdout.write("FAILED\n")
        for f in failures:
            sys.stdout.write("  - {0}\n".format(f))
        sys.exit(1)

    sys.stdout.write("All checks passed.\n")


if __name__ == "__main__":
    main()
