# -*- coding: utf-8 -*-
"""Bench check for Elevation Push. Runs under plain CPython from the
pushbutton folder:

    python import_check.py
    python import_check.py --selftest

Every rule here exists because breaking it produces a blank white
pyRevit window with no traceback in it.
"""

import ast
import io
import os
import re
import sys
import symtable
import xml.dom.minidom

HERE = os.path.dirname(os.path.abspath(__file__))

PY_FILES = ["script.py", "elevation_push_results.py"]
XAML_FILES = ["ElevationPushResults.xaml"]

# Names the real API puts in these namespaces. An import of a name from
# the wrong namespace fails here rather than in Revit.
NAMESPACES = {
    "System.IO": ["File", "MemoryStream"],
    "System.Windows": ["Thickness", "HorizontalAlignment",
                       "VerticalAlignment", "TextWrapping", "GridLength",
                       "GridUnitType", "Window", "FontWeights",
                       "CornerRadius", "Visibility"],
    "System.Windows.Controls": ["Border", "TextBlock", "StackPanel",
                                "Grid", "ColumnDefinition",
                                "RowDefinition", "Orientation", "Button"],
    "System.Windows.Markup": ["XamlReader"],
    "System.Windows.Media": ["SolidColorBrush", "ColorConverter",
                             "FontFamily"],
    "System.Windows.Media.Imaging": ["BitmapImage", "BitmapCacheOption"],
    "System.Windows.Interop": ["WindowInteropHelper"],
    "System.Diagnostics": ["Process"],
}


def read(path):
    return io.open(path, encoding="utf-8").read()


# ------------------------------------------------------------
# Rules
# ------------------------------------------------------------

def rule_xaml_parses(sources, xamls):
    """A layout that will not parse is the quiet blank window. XML
    forbids -- inside a comment, so banners must be drawn with =."""
    fails = []
    for name, text in xamls.items():
        try:
            xml.dom.minidom.parseString(text.encode("utf-8"))
        except Exception as ex:
            fails.append("{}: will not parse as XML -- {}".format(name, ex))
    return fails


def rule_no_fstrings(sources, xamls):
    fails = []
    for name, text in sources.items():
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.JoinedStr):
                fails.append("{}: f-string at line {}".format(
                    name, node.lineno))
    return fails


def rule_no_print(sources, xamls):
    fails = []
    for name, text in sources.items():
        for node in ast.walk(ast.parse(text)):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "print"):
                fails.append("{}: print() at line {}".format(
                    name, node.lineno))
    return fails


def rule_no_bare_integervalue(sources, xamls):
    """Removed in Revit 2026. Allowed only inside eid_value."""
    fails = []
    for name, text in sources.items():
        tree = ast.parse(text)
        guarded = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "eid_value":
                lines = [getattr(c, "lineno", node.lineno)
                         for c in ast.walk(node)]
                guarded.append((node.lineno, max(lines)))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "IntegerValue":
                if not any(lo <= node.lineno <= hi for lo, hi in guarded):
                    fails.append("{}: bare .IntegerValue at line {}".format(
                        name, node.lineno))
    return fails


def rule_no_system_uri(sources, xamls):
    """System.Uri moved assemblies and throws at module load on 2025+."""
    fails = []
    for name, text in sources.items():
        if re.search(r"\bSystem\s*\.\s*Uri\b", text):
            fails.append("{}: System.Uri used".format(name))
        if re.search(r"from\s+System\s+import\s+[^\n]*\bUri\b", text):
            fails.append("{}: System.Uri imported".format(name))
    return fails


def rule_clr_before_system(sources, xamls):
    """An IronPython engine can only see a .NET namespace once
    clr.AddReference has run. pyRevit does not preload WPF."""
    fails = []
    for name, text in sources.items():
        lines = text.splitlines()
        first_ref = None
        first_use = None
        for index, line in enumerate(lines):
            if first_ref is None and "clr.AddReference" in line:
                first_ref = index
            if first_use is None and re.match(
                    r"\s*(from|import)\s+(System|Autodesk)\b", line):
                first_use = index
        if first_use is not None:
            if first_ref is None:
                fails.append(
                    "{}: reaches into System/Autodesk at line {} with no "
                    "clr.AddReference".format(name, first_use + 1))
            elif first_ref > first_use:
                fails.append(
                    "{}: clr.AddReference at line {} comes after the "
                    "import at line {}".format(
                        name, first_ref + 1, first_use + 1))
    return fails


def rule_namespaces(sources, xamls):
    """Each .NET name must be imported from the namespace the real API
    puts it in."""
    known = {}
    for namespace, names in NAMESPACES.items():
        for item in names:
            known.setdefault(item, set()).add(namespace)

    fails = []
    for name, text in sources.items():
        for node in ast.walk(ast.parse(text)):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            if not node.module.split(".")[0] in ("System", "Autodesk"):
                continue
            for alias in node.names:
                homes = known.get(alias.name)
                if homes and node.module not in homes:
                    fails.append(
                        "{}: {} imported from {} at line {}, the API puts "
                        "it in {}".format(name, alias.name, node.module,
                                          node.lineno, "/".join(sorted(homes))))
    return fails


def rule_findname_has_xname(sources, xamls):
    """A FindName with no matching x:Name returns None and the window
    half works. Matches the aliased form too."""
    declared = set()
    for text in xamls.values():
        declared.update(re.findall(r'x:Name\s*=\s*"([^"]+)"', text))

    fails = []
    for name, text in sources.items():
        for asked in re.findall(r'FindName\(\s*"([^"]+)"\s*\)', text):
            if asked not in declared:
                fails.append(
                    "{}: FindName(\"{}\") has no matching x:Name".format(
                        name, asked))
        alias = re.findall(r'(\w+)\s*=\s*\w+\.FindName\b', text)
        for alias_name in alias:
            for asked in re.findall(
                    re.escape(alias_name) + r'\(\s*"([^"]+)"\s*\)', text):
                if asked not in declared:
                    fails.append(
                        "{}: {}(\"{}\") has no matching x:Name".format(
                            name, alias_name, asked))
    return fails


def rule_dynamicresource_keys_exist(sources, xamls):
    """A DynamicResource key nothing defines renders as an unstyled or
    dead control."""
    fails = []
    for name, text in xamls.items():
        defined = set(re.findall(r'x:Key\s*=\s*"([^"]+)"', text))
        for key in re.findall(r'\{DynamicResource\s+([^}\s]+)\s*\}', text):
            if key not in defined:
                fails.append(
                    "{}: DynamicResource {} is never defined".format(
                        name, key))
    return fails


def rule_globals_exist(sources, xamls):
    """Every global name a function reaches for exists in its module --
    catches a function deleted by a block rewrite."""
    safe = set(dir(__builtins__) if not isinstance(__builtins__, dict)
               else __builtins__.keys())
    safe |= {"True", "False", "None"}

    fails = []
    for name, text in sources.items():
        table = symtable.symtable(text, name, "exec")
        top = set(table.get_identifiers())

        def walk(scope):
            for child in scope.get_children():
                if child.get_type() == "function":
                    for sym in child.get_symbols():
                        ident = sym.get_name()
                        if (sym.is_global() and ident not in top
                                and ident not in safe):
                            fails.append(
                                "{}: {}() reaches for undefined global "
                                "'{}'".format(name, child.get_name(), ident))
                walk(child)

        walk(table)
    return fails


RULES = [
    ("xaml parses as XML", rule_xaml_parses),
    ("no f-strings", rule_no_fstrings),
    ("no print", rule_no_print),
    ("no bare .IntegerValue", rule_no_bare_integervalue),
    ("no System.Uri", rule_no_system_uri),
    ("clr.AddReference before System/Autodesk", rule_clr_before_system),
    ("names come from the right namespace", rule_namespaces),
    ("FindName has a matching x:Name", rule_findname_has_xname),
    ("DynamicResource keys are defined", rule_dynamicresource_keys_exist),
    ("globals a function uses exist", rule_globals_exist),
]


def load():
    sources = {}
    for name in PY_FILES:
        sources[name] = read(os.path.join(HERE, name))
    xamls = {}
    for name in XAML_FILES:
        xamls[name] = read(os.path.join(HERE, name))
    return sources, xamls


def run():
    sources, xamls = load()
    total = 0
    for label, rule in RULES:
        fails = rule(sources, xamls)
        total += len(fails)
        mark = "FAIL" if fails else "ok  "
        sys.stdout.write("{}  {}\n".format(mark, label))
        for line in fails:
            sys.stdout.write("      {}\n".format(line))
    sys.stdout.write(
        "\n{}\n".format("All rules passed."
                        if not total else "{} problem(s).".format(total)))
    return 0 if not total else 1


def selftest():
    """Break each rule on purpose and confirm it is caught. A rule
    nobody has tested is a rule that does not work."""
    good_py = (
        "import clr\n"
        "clr.AddReference('PresentationFramework')\n"
        "from System.Windows import Thickness\n"
        "def eid_value(i):\n"
        "    return i.IntegerValue\n"
        "def use():\n"
        "    return eid_value(1)\n"
        "w = None\n"
        "b = w.FindName(\"Body\")\n"
    )
    good_xaml = (
        '<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/'
        'presentation" xmlns:x="http://schemas.microsoft.com/winfx/2006/'
        'xaml"><Window.Resources><SolidColorBrush x:Key="Fg"/>'
        '</Window.Resources>'
        '<TextBlock x:Name="Body" Foreground="{DynamicResource Fg}"/>'
        '</Window>'
    )

    breakages = [
        ("xaml parses as XML",
         good_py, good_xaml.replace("<TextBlock",
                                    "<!-- ---- x ---- --><TextBlock")),
        ("no f-strings", good_py + "z = f'{1}'\n", good_xaml),
        ("no print", good_py + "print('x')\n", good_xaml),
        ("no bare .IntegerValue",
         good_py + "q = el.Id.IntegerValue\n", good_xaml),
        ("no System.Uri", good_py + "u = System.Uri('a')\n", good_xaml),
        ("clr.AddReference before System/Autodesk",
         "from System.Windows import Thickness\nimport clr\n"
         "clr.AddReference('PresentationFramework')\n", good_xaml),
        ("names come from the right namespace",
         "import clr\nclr.AddReference('x')\n"
         "from System.Windows.Controls import Thickness\n", good_xaml),
        ("FindName has a matching x:Name",
         good_py.replace('FindName("Body")', 'FindName("Nope")'), good_xaml),
        ("DynamicResource keys are defined",
         good_py, good_xaml.replace("DynamicResource Fg",
                                    "DynamicResource Missing")),
        ("globals a function uses exist",
         "def use():\n    return gone_missing()\n", good_xaml),
    ]

    lookup = dict(RULES)
    failures = 0
    for label, py_text, xaml_text in breakages:
        rule = lookup[label]
        try:
            caught = bool(rule({"probe.py": py_text},
                               {"probe.xaml": xaml_text}))
        except SyntaxError:
            caught = True
        if not caught:
            failures += 1
        sys.stdout.write("{}  breaking: {}\n".format(
            "ok  " if caught else "MISS", label))

        clean = rule({"probe.py": good_py}, {"probe.xaml": good_xaml})
        if clean:
            failures += 1
            sys.stdout.write(
                "MISS  false positive on clean input: {}\n".format(label))

    sys.stdout.write(
        "\n{}\n".format("Every rule caught its own breakage."
                        if not failures
                        else "{} rule(s) did not work.".format(failures)))
    return 0 if not failures else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    sys.exit(run())
