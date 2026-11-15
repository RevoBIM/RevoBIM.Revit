# -*- coding: utf-8 -*-
"""Bench check for Fire Damper Wall Type Push.

A blank white pyRevit window means the script died before any of it ran, so
there is no traceback to read.  This file makes that class of bug findable on
the bench instead of in Revit:

  * every .xaml parses as XML
  * every .NET name is imported from the namespace the real API puts it in
  * nothing reaches into System.* or Autodesk.* before fdwt_clr is imported
  * no StaticResource in a layout, no DynamicResource key Theme.xaml lacks
  * no Style="{DynamicResource K}" on an element K's TargetType does not match
  * no FindName without a matching x:Name
  * no f-strings, no print, no bare .IntegerValue, no System.Uri
  * every palette key has a brush in Theme.xaml, and every
    SetResourceReference key exists

Run it with plain CPython from this folder:

    python import_check.py              check the shipped files
    python import_check.py --selftest   break each rule on purpose and prove
                                        the check catches it
"""

import ast
import os
import re
import shutil
import subprocess
import sys
import tempfile
from xml.dom import minidom

HERE = os.path.dirname(os.path.abspath(__file__))

MODULES = ["fdwt_clr.py", "fdwt_core.py", "script.py"]
CLR_MODULE = "fdwt_clr"

# ---------------------------------------------------------------------------
# the namespace each .NET name really lives in
# ---------------------------------------------------------------------------
NAMESPACES = {
    "Autodesk.Revit.DB": [
        "BooleanOperationsType", "BooleanOperationsUtils",
        "BoundingBoxIntersectsFilter", "BuiltInCategory", "BuiltInParameter",
        "CurveLoop", "Element", "ElementId", "ElementIntersectsSolidFilter",
        "ElementMulticategoryFilter", "ElementTransformUtils",
        "FailureProcessingResult", "FailureSeverity", "FilteredElementCollector",
        "GeometryCreationUtilities", "GeometryInstance", "IFailuresPreprocessor",
        "Line", "Options", "Outline", "RevitLinkInstance", "Solid", "SolidUtils",
        "StorageType", "Transaction", "TransactionStatus", "Transform",
        "ViewDetailLevel", "Wall", "WallType", "WorksharingUtils", "XYZ",
    ],
    "Autodesk.Revit.UI": [
        "TaskDialog", "TaskDialogCommonButtons", "TaskDialogResult",
        "UIApplication", "UIDocument",
    ],
    "Microsoft.Win32": ["OpenFileDialog", "SaveFileDialog"],
    "System": ["Action", "Array", "Convert", "Object", "String"],
    "System.Collections.Generic": ["Dictionary", "List"],
    "System.Diagnostics": ["Process"],
    "System.IO": ["File", "MemoryStream", "Path", "Stream"],
    "System.Windows": [
        "Application", "CornerRadius", "GridLength", "GridUnitType",
        "HorizontalAlignment", "MessageBox", "ResourceDictionary",
        "SystemParameters", "TextTrimming", "TextWrapping", "Thickness",
        "VerticalAlignment", "Visibility", "Window", "WindowStartupLocation",
        "WindowStyle",
    ],
    "System.Windows.Controls": [
        "Border", "Button", "CheckBox", "ColumnDefinition", "ComboBox", "Grid",
        "Image", "ListBox", "RowDefinition", "ScrollBarVisibility",
        "ScrollViewer", "StackPanel", "TextBlock", "TextBox", "ToolTip",
    ],
    "System.Windows.Input": ["Key", "Keyboard", "MouseButtonEventArgs"],
    "System.Windows.Interop": ["WindowInteropHelper"],
    "System.Windows.Markup": ["XamlReader"],
    "System.Windows.Media": ["BrushConverter", "Brushes", "Color", "SolidColorBrush"],
    "System.Windows.Media.Imaging": ["BitmapCacheOption", "BitmapImage"],
    "System.Windows.Threading": [
        "Dispatcher", "DispatcherFrame", "DispatcherOperationCallback",
        "DispatcherPriority",
    ],
}

DOTTED_ROOTS = ("System", "Autodesk", "Microsoft", "Revit")

FORBIDDEN_TEXT = [
    (r"(?<![\w.])print\s+[^(=]", "print statement (IronPython 3 will not take it)"),
    (r"(?<![\w.])print\s*\(", "print (results go in a themed window, not the "
                              "pyRevit output window)"),
    (r"\.IntegerValue", "bare .IntegerValue (removed in Revit 2026 - use eid_value)"),
    (r"from\s+System\s+import\s+([\w,\s]*\b)Uri\b",
     "System.Uri (moved assemblies in Revit 2025 - load images from bytes)"),
    (r"System\.Uri", "System.Uri (moved assemblies in Revit 2025)"),
]


class Problem(Exception):
    pass


def read(path):
    handle = open(path, "r", encoding="utf-8")
    try:
        return handle.read()
    finally:
        handle.close()


def xaml_files(folder):
    return sorted(
        [name for name in os.listdir(folder) if name.lower().endswith(".xaml")]
    )


# ---------------------------------------------------------------------------
# checks
# ---------------------------------------------------------------------------

def check_xaml_parses(folder, problems):
    """Catches the comment drawn with hyphens, an unclosed tag, a bare &."""
    for name in xaml_files(folder):
        try:
            minidom.parse(os.path.join(folder, name))
        except Exception as err:
            problems.append("{0}: will not parse as XML - {1}".format(name, err))


def check_f_strings(folder, problems):
    for name in MODULES:
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            continue
        source = read(path)
        try:
            tree = ast.parse(source)
        except SyntaxError as err:
            problems.append("{0}: will not parse - {1}".format(name, err))
            continue
        for node in ast.walk(tree):
            if node.__class__.__name__ == "JoinedStr":
                problems.append(
                    "{0} line {1}: f-string (IronPython 2.7 cannot parse it)".format(
                        name, node.lineno
                    )
                )


def _eid_value_lines(source):
    """The one place .IntegerValue is allowed: inside the eid_value helper."""
    allowed = set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return allowed
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "eid_value":
            last = getattr(node, "end_lineno", node.lineno + 40)
            for number in range(node.lineno, last + 1):
                allowed.add(number)
    return allowed


def check_forbidden_text(folder, problems):
    for name in MODULES:
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            continue
        source = read(path)
        allowed = _eid_value_lines(source)
        for number, line in enumerate(source.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            for pattern, message in FORBIDDEN_TEXT:
                if not re.search(pattern, line):
                    continue
                if ".IntegerValue" in pattern and number in allowed:
                    continue  # the sanctioned fallback
                problems.append("{0} line {1}: {2}".format(name, number, message))


def _import_nodes(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            yield node


def check_namespaces(folder, problems):
    """Every .NET name imported from the namespace the real API puts it in."""
    for name in MODULES:
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            continue
        try:
            tree = ast.parse(read(path))
        except SyntaxError:
            continue  # already reported
        for node in _import_nodes(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            module = node.module or ""
            if not module.split(".")[0] in DOTTED_ROOTS:
                continue
            known = NAMESPACES.get(module)
            if known is None:
                problems.append(
                    "{0} line {1}: unknown namespace '{2}' - add it to "
                    "NAMESPACES with the names it really holds".format(
                        name, node.lineno, module
                    )
                )
                continue
            for alias in node.names:
                if alias.name not in known:
                    problems.append(
                        "{0} line {1}: '{2}' is not in {3}".format(
                            name, node.lineno, alias.name, module
                        )
                    )


def check_clr_first(folder, problems):
    """Nothing touches System.* or Autodesk.* before fdwt_clr is imported."""
    for name in MODULES:
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            continue
        if name == CLR_MODULE + ".py":
            continue
        try:
            tree = ast.parse(read(path))
        except SyntaxError:
            continue
        clr_line = None
        first_dotnet = None
        for node in _import_nodes(tree):
            names = []
            if isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                names = [alias.name for alias in node.names]
            for target in names:
                if target == CLR_MODULE and clr_line is None:
                    clr_line = node.lineno
                if target.split(".")[0] in DOTTED_ROOTS and first_dotnet is None:
                    first_dotnet = (node.lineno, target)
        if first_dotnet is None:
            continue
        if clr_line is None:
            problems.append(
                "{0}: reaches into {1} at line {2} but never imports {3}".format(
                    name, first_dotnet[1], first_dotnet[0], CLR_MODULE
                )
            )
        elif clr_line > first_dotnet[0]:
            problems.append(
                "{0}: imports {1} at line {2}, after {3} at line {4} - the "
                "assembly reference has to win".format(
                    name, CLR_MODULE, clr_line, first_dotnet[1], first_dotnet[0]
                )
            )


def _theme_keys(folder):
    """(brush keys, {style key: TargetType}) out of Theme.xaml."""
    path = os.path.join(folder, "Theme.xaml")
    document = minidom.parse(path)
    brushes = set()
    styles = {}
    for node in document.getElementsByTagName("*"):
        key = node.getAttribute("x:Key")
        if not key:
            continue
        if node.tagName.endswith("Brush"):
            brushes.add(key)
        elif node.tagName == "Style":
            styles[key] = node.getAttribute("TargetType")
        else:
            brushes.add(key)
    return brushes, styles


def _layouts(folder):
    found = []
    for name in xaml_files(folder):
        path = os.path.join(folder, name)
        try:
            document = minidom.parse(path)
        except Exception:
            continue
        if document.documentElement.tagName == "Window":
            found.append((name, path, document))
    return found


def check_layout_resources(folder, problems):
    brushes, styles = _theme_keys(folder)
    known = set(brushes) | set(styles.keys())
    for name, path, document in _layouts(folder):
        source = read(path)

        # a StaticResource in a layout fails at load: the dictionary is merged
        # in AFTER XamlReader has parsed the layout
        for match in re.finditer(r"\{StaticResource\s+([\w.]+)\}", source):
            problems.append(
                "{0}: StaticResource '{1}' in a layout - use DynamicResource".format(
                    name, match.group(1)
                )
            )

        for match in re.finditer(r"\{DynamicResource\s+([\w.]+)\}", source):
            key = match.group(1)
            if key not in known:
                problems.append(
                    "{0}: DynamicResource '{1}' has nothing in Theme.xaml".format(
                        name, key
                    )
                )

        # WPF raises when a Style is APPLIED to the wrong type, which also
        # surfaces as a dead window
        for node in document.getElementsByTagName("*"):
            value = node.getAttribute("Style")
            if not value:
                continue
            match = re.match(r"\{DynamicResource\s+([\w.]+)\}", value)
            if not match:
                continue
            key = match.group(1)
            target = styles.get(key)
            if target is None:
                continue
            if target != node.tagName:
                problems.append(
                    "{0}: <{1}> uses style '{2}', whose TargetType is "
                    "{3}".format(name, node.tagName, key, target)
                )


def check_find_names(folder, problems):
    names = set()
    for name in xaml_files(folder):
        source = read(os.path.join(folder, name))
        for match in re.finditer(r'x:Name="(\w+)"', source):
            names.add(match.group(1))
    for name in MODULES:
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            continue
        source = read(path)
        # FindName is often aliased first ("find = self.window.FindName"), so
        # follow the aliases too or the whole rule quietly does nothing.
        callers = ["FindName"]
        for match in re.finditer(r"(\w+)\s*=\s*[\w.]*\bFindName\b\s*$", source, re.M):
            callers.append(match.group(1))
        pattern = r'(?:{0})\(\s*"(\w+)"\s*\)'.format("|".join(sorted(set(callers))))
        for match in re.finditer(pattern, source):
            if match.group(1) not in names:
                problems.append(
                    '{0}: FindName("{1}") has no x:Name in any .xaml'.format(
                        name, match.group(1)
                    )
                )


def check_resource_references(folder, problems):
    brushes, styles = _theme_keys(folder)
    known = set(brushes) | set(styles.keys())
    for name in MODULES:
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            continue
        source = read(path)
        for match in re.finditer(
            r'SetResourceReference\(\s*[\w.]+\s*,\s*(?:"(\w+)"|(\w+)\[)', source
        ):
            key = match.group(1)
            if key and key not in known:
                problems.append(
                    "{0}: SetResourceReference to '{1}', which Theme.xaml does "
                    "not define".format(name, key)
                )


def check_palettes(folder, problems):
    """Both palettes cover every brush Theme.xaml declares, and each other."""
    brushes, _styles = _theme_keys(folder)
    source = read(os.path.join(folder, "script.py"))
    tree = ast.parse(source)
    palettes = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in ("DARK", "LIGHT"):
                if isinstance(node.value, ast.Dict):
                    keys = []
                    for item in node.value.keys:
                        if isinstance(item, ast.Str):
                            keys.append(item.s)
                        elif hasattr(ast, "Constant") and isinstance(item, ast.Constant):
                            keys.append(item.value)
                    palettes[target.id] = set(keys)
    if "DARK" not in palettes or "LIGHT" not in palettes:
        problems.append("script.py: DARK and LIGHT palettes not both found")
        return
    if palettes["DARK"] != palettes["LIGHT"]:
        missing = palettes["DARK"] ^ palettes["LIGHT"]
        problems.append(
            "script.py: the two palettes differ on {0}".format(sorted(missing))
        )
    for key in sorted(brushes - palettes["DARK"]):
        problems.append(
            "script.py: Theme.xaml declares brush '{0}' that the palettes do "
            "not set".format(key)
        )
    for key in sorted(palettes["DARK"] - brushes):
        problems.append(
            "Theme.xaml: no brush for palette key '{0}'".format(key)
        )


def check_modules_load(folder, problems):
    """Import the modules against a stub Revit and .NET API.

    A mis-namespaced import fails here instead of showing a blank window in
    Revit.
    """
    script = os.path.join(folder, "_stub_run.py")
    body = STUB_RUNNER.replace("__FOLDER__", folder.replace("\\", "\\\\"))
    body = body.replace("__NAMESPACES__", repr(NAMESPACES))
    handle = open(script, "w", encoding="utf-8")
    try:
        handle.write(body)
    finally:
        handle.close()
    try:
        result = subprocess.run(
            [sys.executable, script], capture_output=True, text=True
        )
        if result.returncode != 0:
            problems.append(
                "modules will not load against the stub API:\n"
                + (result.stderr or result.stdout).strip()
            )
    finally:
        try:
            os.remove(script)
        except Exception:
            pass


STUB_RUNNER = '''
import sys, types, os

FOLDER = r"__FOLDER__"
NAMESPACES = __NAMESPACES__

def make(name):
    module = types.ModuleType(name)
    sys.modules[name] = module
    return module

clr = make("clr")
clr.AddReference = lambda name: None
clr.GetClrType = lambda thing: thing

for namespace, names in NAMESPACES.items():
    parts = namespace.split(".")
    for depth in range(1, len(parts) + 1):
        partial = ".".join(parts[:depth])
        if partial not in sys.modules:
            make(partial)
    module = sys.modules[namespace]
    for entry in names:
        setattr(module, entry, type(entry, (object,), {}))

# generics: List[X] and the enum-ish members the modules touch
generic = sys.modules["System.Collections.Generic"]
class _Generic(object):
    def __getitem__(self, item):
        return lambda *a, **k: []
generic.List = _Generic()

sys.path.insert(0, FOLDER)
import fdwt_clr
import fdwt_core
assert fdwt_core.__version__
assert fdwt_core.eid_value(None) == 0
assert fdwt_core.first_number("60 minutes") == 60.0
values = fdwt_core.load_settings()
assert values["tgt_fire_param"]
print("stub load ok")
'''


def run_checks(folder):
    problems = []
    check_xaml_parses(folder, problems)
    check_f_strings(folder, problems)
    check_forbidden_text(folder, problems)
    check_namespaces(folder, problems)
    check_clr_first(folder, problems)
    check_layout_resources(folder, problems)
    check_find_names(folder, problems)
    check_resource_references(folder, problems)
    check_palettes(folder, problems)
    check_modules_load(folder, problems)
    return problems


# ---------------------------------------------------------------------------
# self test - break each rule on purpose, prove the check catches it
# ---------------------------------------------------------------------------

BREAKAGES = [
    (
        "xaml comment drawn with hyphens",
        "FireDamperWallTypePush.xaml",
        lambda text: text.replace("<!-- =====", "<!-- -----", 1),
        "will not parse as XML",
    ),
    (
        "a name imported from the wrong namespace",
        "fdwt_core.py",
        lambda text: text.replace(
            "from System.Collections.Generic import List",
            "from System.Windows import List",
            1,
        ),
        "is not in System.Windows",
    ),
    (
        "System.* touched before the assembly reference",
        "fdwt_core.py",
        lambda text: text.replace(
            "import fdwt_clr  # noqa: F401  - assembly references MUST be first",
            "from System.Windows import Thickness\nimport fdwt_clr",
            1,
        ),
        "after System.Windows",
    ),
    (
        "StaticResource in a layout",
        "FireDamperWallTypePush.xaml",
        lambda text: text.replace(
            '{DynamicResource RevoChipButton}', '{StaticResource RevoChipButton}', 1
        ),
        "StaticResource",
    ),
    (
        "DynamicResource key Theme.xaml does not define",
        "FireDamperWallTypePush.xaml",
        lambda text: text.replace(
            '{DynamicResource BlueBrush}', '{DynamicResource NotAThing}', 1
        ),
        "has nothing in Theme.xaml",
    ),
    (
        "a style applied to the wrong element type",
        "FireDamperWallTypePush.xaml",
        lambda text: text.replace(
            'Style="{DynamicResource RevoChipButton}"',
            'Style="{DynamicResource RevoTextBox}"',
            1,
        ),
        "whose TargetType is",
    ),
    (
        "FindName with no x:Name",
        "script.py",
        lambda text: text.replace(
            'find("TxtStatus")', 'find("TxtStatusBarThatIsNotThere")', 1
        ),
        "has no x:Name",
    ),
    (
        "an f-string",
        "fdwt_core.py",
        lambda text: text.replace(
            'TOOL_NAME = "Fire Damper Wall Type Push"',
            'TOOL_NAME = f"Fire Damper Wall Type Push"',
            1,
        ),
        "f-string",
    ),
    (
        "a bare .IntegerValue outside the eid_value helper",
        "fdwt_core.py",
        lambda text: text.replace(
            "        self.id = eid_value(element.Id)",
            "        self.id = element.Id.IntegerValue",
            1,
        ),
        ".IntegerValue",
    ),
    (
        "System.Uri",
        "script.py",
        lambda text: text.replace(
            "from System.Diagnostics import Process",
            "from System import Uri\n    from System.Diagnostics import Process",
            1,
        ),
        "Uri",
    ),
    (
        "SetResourceReference to a key that does not exist",
        "script.py",
        lambda text: text.replace(
            'SetResourceReference(TextBlock.ForegroundProperty, colour_key)',
            'SetResourceReference(TextBlock.ForegroundProperty, "NoSuchBrush")',
            1,
        ),
        "which Theme.xaml does not define",
    ),
    (
        "a palette key with no brush in Theme.xaml",
        "script.py",
        lambda text: text.replace(
            '    "HoverBrush": "#33333A",',
            '    "HoverBrush": "#33333A",\n    "MadeUpBrush": "#123456",',
            1,
        ),
        "MadeUpBrush",
    ),
]


def self_test(folder):
    print("Bench check self test - each rule is broken on purpose.\n")
    failures = 0
    for label, filename, mangle, expected in BREAKAGES:
        temp = tempfile.mkdtemp(prefix="fdwt_check_")
        try:
            for name in os.listdir(folder):
                source = os.path.join(folder, name)
                if os.path.isfile(source):
                    shutil.copy2(source, os.path.join(temp, name))
            path = os.path.join(temp, filename)
            text = read(path)
            broken = mangle(text)
            if broken == text:
                print("  ??  {0}: could not break it - the check is untested".format(label))
                failures += 1
                continue
            handle = open(path, "w", encoding="utf-8")
            try:
                handle.write(broken)
            finally:
                handle.close()

            problems = run_checks(temp)
            caught = [p for p in problems if expected in p]
            if caught:
                print("  ok  {0}".format(label))
            else:
                print("  FAIL {0} - not caught. Got: {1}".format(label, problems))
                failures += 1
        finally:
            shutil.rmtree(temp, ignore_errors=True)
    print("")
    if failures:
        print("{0} rule(s) did not catch their own breakage.".format(failures))
        return 1
    print("Every rule caught its own breakage.")
    return 0


def main():
    folder = HERE
    if "--selftest" in sys.argv:
        return self_test(folder)
    problems = run_checks(folder)
    if problems:
        print("Bench check found {0} problem(s):\n".format(len(problems)))
        for problem in problems:
            print("  * " + problem)
        return 1
    print("Bench check passed: {0}".format(folder))
    return 0


if __name__ == "__main__":
    sys.exit(main())
