# -*- coding: utf-8 -*-
"""Bench check for RevoBIM Tag Leader Elbow.

Run it under plain CPython from this folder:

    python import_check.py
    python import_check.py --selftest

It loads every shipped module against a stub Revit and .NET API that declares
each name in the namespace the real API puts it in, so a mis-namespaced import
fails on the bench instead of showing up in Revit as a blank white pyRevit
window with no traceback in it.  --selftest breaks each rule on purpose and
confirms the check catches it: a rule nobody has tested is a rule that does not
work.
"""

import ast
import os
import re
import shutil
import subprocess
import symtable
import sys
import tempfile
import types
from xml.dom import minidom

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL_FOLDER = "RevoBIM Tag Leader Elbow.pushbutton"
SETTINGS_FOLDER = "RevoBIM Tag Elbow Settings.pushbutton"
BENCH_FILES = ("import_check.py", "bench_logic.py")

LAYOUTS = ("TagLeaderElbowResults.xaml", "TagLeaderElbowSettings.xaml")


def out(text):
    sys.stdout.write(text + "\n")


# ============================================================================
# the stub API
# ============================================================================

NAMESPACES = {
    "clr": ["AddReference", "AddReferenceByName", "GetClrType"],
    "System": ["Object", "String", "Exception", "Math", "Convert", "Environment",
               "Array", "Double", "Int32", "Boolean"],
    "System.IO": ["File", "Path", "MemoryStream", "StringReader", "Directory"],
    "System.Xml": ["XmlReader", "XmlDocument"],
    "System.Diagnostics": ["Process", "Stopwatch"],
    "System.Drawing": ["Point", "Rectangle", "Size"],
    "System.Windows.Forms": ["Screen", "SystemInformation"],
    "System.Windows": ["Window", "Thickness", "CornerRadius", "GridLength",
                       "GridUnitType", "TextWrapping", "Visibility", "WindowState",
                       "SystemParameters", "Clipboard", "Application",
                       "ResourceDictionary", "PresentationSource", "Point",
                       "HorizontalAlignment", "VerticalAlignment", "FontWeights",
                       "WindowStartupLocation", "MessageBox"],
    "System.Windows.Controls": ["TextBlock", "Border", "Grid", "StackPanel",
                                "ColumnDefinition", "RowDefinition", "ComboBox",
                                "ComboBoxItem", "CheckBox", "Button", "TextBox",
                                "ScrollViewer", "Orientation", "Image", "Canvas",
                                "ListBox", "ListBoxItem"],
    "System.Windows.Controls.Primitives": ["Thumb", "ToggleButton", "ButtonBase",
                                           "RepeatButton", "Popup"],
    "System.Windows.Media": ["Brush", "SolidColorBrush", "Color", "ColorConverter",
                             "Colors", "Brushes"],
    "System.Windows.Media.Imaging": ["BitmapImage", "BitmapCacheOption"],
    "System.Windows.Markup": ["XamlReader"],
    "System.Windows.Input": ["Key", "Cursors", "Keyboard", "ModifierKeys"],
    "System.Windows.Interop": ["WindowInteropHelper", "HwndSource"],
    "System.Windows.Threading": ["DispatcherTimer", "DispatcherPriority"],
    "Autodesk": [],
    "Autodesk.Revit": [],
    "Autodesk.Revit.DB": [
        "XYZ", "Transaction", "TransactionStatus", "TransactionGroup", "SubTransaction",
        "ElementId", "Element", "ElementTransformUtils", "IndependentTag",
        "SpatialElementTag", "BuiltInCategory", "BuiltInParameter",
        "FilteredElementCollector", "LocationPoint", "LocationCurve", "Line",
        "Options", "Reference", "RevitLinkInstance", "Transform", "View",
        "ViewType", "WorksharingUtils", "LeaderEndCondition", "TagOrientation",
        "IFailuresPreprocessor", "FailureProcessingResult"],
    "Autodesk.Revit.DB.Architecture": ["RoomTag"],
    "Autodesk.Revit.DB.Mechanical": ["SpaceTag"],
    "Autodesk.Revit.UI": ["TaskDialog", "TaskDialogCommonButtons", "TaskDialogResult",
                          "RevitCommandId", "PostableCommand", "UIApplication",
                          "UIDocument", "ExternalEvent", "IExternalEventHandler"],
    "Autodesk.Revit.UI.Selection": ["ObjectType", "ISelectionFilter", "Selection"],
}


class _Stub(object):
    """Stands in for any .NET type.  Real class, so it can be subclassed."""

    def __init__(self, *args, **kwargs):
        pass

    def __getattr__(self, name):
        return _Stub()

    def __call__(self, *args, **kwargs):
        return _Stub()


class _StubModule(types.ModuleType):

    def __init__(self, name, allowed):
        types.ModuleType.__init__(self, name)
        self._allowed = set(allowed)
        self._made = {}

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        if name in self._made:
            return self._made[name]
        if name not in self._allowed:
            raise ImportError(
                "{0} does not live in {1} in the real API".format(name, self.__name__))
        made = type(str(name), (_Stub,), {})
        self._made[name] = made
        return made


def install_stubs():
    for name in sorted(NAMESPACES.keys()):
        module = _StubModule(name, NAMESPACES[name])
        sys.modules[name] = module
    for name in sorted(NAMESPACES.keys()):
        if "." not in name:
            continue
        parent, leaf = name.rsplit(".", 1)
        if parent in sys.modules:
            sys.modules[parent]._made[leaf] = sys.modules[name]
            setattr(sys.modules[parent], leaf, sys.modules[name])


def remove_stubs():
    for name in list(NAMESPACES.keys()):
        sys.modules.pop(name, None)


# ============================================================================
# helpers
# ============================================================================

def tool_dir(pulldown):
    return os.path.join(pulldown, TOOL_FOLDER)


def python_files(pulldown):
    found = []
    for folder in (tool_dir(pulldown), os.path.join(pulldown, SETTINGS_FOLDER)):
        if not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder)):
            if name.endswith(".py") and name not in BENCH_FILES:
                found.append(os.path.join(folder, name))
    return found


def xaml_files(pulldown):
    folder = tool_dir(pulldown)
    return [os.path.join(folder, name) for name in sorted(os.listdir(folder))
            if name.endswith(".xaml")]


def read(path):
    handle = open(path, "r")
    try:
        return handle.read()
    finally:
        handle.close()


# ============================================================================
# the rules
# ============================================================================

def rule_xaml_parses(pulldown):
    """1. Every .xaml parses as XML.  A run of hyphens in a comment is illegal
    XML and shows up in Revit only as a dead window."""
    problems = []
    for path in xaml_files(pulldown):
        try:
            minidom.parseString(read(path))
        except Exception as error:
            problems.append("{0} will not parse as XML: {1}".format(
                os.path.basename(path), error))
    return problems


def rule_clr_first(pulldown):
    """2. No module reaches into System.* or Autodesk.* at module level without
    importing tle_clr first, or importing it too late in the file."""
    problems = []
    pattern = re.compile(r"^(?:from|import)\s+(System|Autodesk)\b")
    for path in python_files(pulldown):
        name = os.path.basename(path)
        lines = read(path).splitlines()
        clr_line = None
        first_dotnet = None
        for index, line in enumerate(lines):
            if line.startswith("import tle_clr"):
                clr_line = index if clr_line is None else clr_line
            if pattern.match(line) and first_dotnet is None:
                first_dotnet = index
        if first_dotnet is None:
            continue
        if clr_line is None:
            problems.append("{0} reaches into .NET without importing tle_clr".format(name))
        elif clr_line > first_dotnet:
            problems.append("{0} imports tle_clr after line {1}, too late".format(
                name, first_dotnet + 1))
    return problems


def rule_no_static_resource(pulldown):
    """3. No StaticResource in a layout: Theme.xaml is merged in after the
    layout has been parsed, so a StaticResource fails at load."""
    problems = []
    for name in LAYOUTS:
        path = os.path.join(tool_dir(pulldown), name)
        if not os.path.exists(path):
            continue
        if "StaticResource" in read(path):
            problems.append("{0} uses StaticResource; layouts may only use "
                            "DynamicResource".format(name))
    return problems


def _theme_keys(pulldown):
    text = read(os.path.join(tool_dir(pulldown), "Theme.xaml"))
    return set(re.findall(r'x:Key="([^"]+)"', text))


def rule_dynamic_keys_exist(pulldown):
    """4. Every DynamicResource key is defined in Theme.xaml."""
    keys = _theme_keys(pulldown)
    problems = []
    for path in xaml_files(pulldown):
        text = read(path)
        for used in sorted(set(re.findall(r"\{DynamicResource\s+([A-Za-z0-9_]+)\s*\}", text))):
            if used not in keys:
                problems.append("{0} asks for DynamicResource {1}, which Theme.xaml "
                                "does not define".format(os.path.basename(path), used))
    return problems


def rule_style_target_types(pulldown):
    """5. No Style="{DynamicResource K}" on an element K's TargetType does not
    match.  WPF raises that when the style is applied, so it is another dead
    window rather than an error anybody sees."""
    theme = minidom.parseString(read(os.path.join(tool_dir(pulldown), "Theme.xaml")))
    targets = {}
    for node in theme.getElementsByTagName("Style"):
        key = node.getAttribute("x:Key")
        target = node.getAttribute("TargetType")
        if key and target:
            targets[key] = target

    problems = []
    for path in xaml_files(pulldown):
        try:
            document = minidom.parseString(read(path))
        except Exception:
            continue  # rule 1 reports this
        for node in document.getElementsByTagName("*"):
            value = node.getAttribute("Style")
            match = re.match(r"\{DynamicResource\s+([A-Za-z0-9_]+)\s*\}", value or "")
            if not match:
                continue
            key = match.group(1)
            wanted = targets.get(key)
            if wanted and wanted != node.tagName:
                problems.append(
                    "{0}: style {1} targets {2} but is applied to a {3}".format(
                        os.path.basename(path), key, wanted, node.tagName))
    return problems


def rule_findname_has_xname(pulldown):
    """6. No FindName without a matching x:Name, following aliases: the code
    writes find = self.window.FindName, so a rule that only matched literal
    FindName("X") calls would be doing nothing at all."""
    names = set()
    for path in xaml_files(pulldown):
        names.update(re.findall(r'x:Name="([^"]+)"', read(path)))

    problems = []
    for path in python_files(pulldown):
        text = read(path)
        aliases = set(re.findall(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*[^=\n]*\.FindName\s*$",
                                 text, re.M))
        calls = set(re.findall(r'FindName\(\s*"([^"]+)"\s*\)', text))
        for alias in aliases:
            calls.update(re.findall(r'\b' + alias + r'\(\s*"([^"]+)"\s*\)', text))
        for call in sorted(calls):
            if call not in names:
                problems.append("{0} asks for x:Name {1}, which no layout defines".format(
                    os.path.basename(path), call))
    return problems


def rule_no_fstrings(pulldown):
    """7. No f-strings: IronPython 2.7 will not parse them."""
    problems = []
    for path in python_files(pulldown):
        for index, line in enumerate(read(path).splitlines()):
            if re.search(r"(?<![A-Za-z0-9_])[fF]['\"]", line):
                problems.append("{0} line {1} looks like an f-string".format(
                    os.path.basename(path), index + 1))
    return problems


def rule_no_print(pulldown):
    """8. No print: it opens pyRevit's output console."""
    problems = []
    for path in python_files(pulldown):
        for index, line in enumerate(read(path).splitlines()):
            if re.search(r"(?<![A-Za-z0-9_.])print\s*[\(\s]", line):
                problems.append("{0} line {1} calls print".format(
                    os.path.basename(path), index + 1))
    return problems


def rule_no_integervalue(pulldown):
    """9. No bare .IntegerValue: removed in Revit 2026.  Allowed only inside
    the guarded eid_value helper in tle_core."""
    problems = []
    for path in python_files(pulldown):
        name = os.path.basename(path)
        for index, line in enumerate(read(path).splitlines()):
            if ".IntegerValue" not in line:
                continue
            if name == "tle_core.py":
                continue
            problems.append("{0} line {1} touches .IntegerValue directly".format(
                name, index + 1))
    return problems


def rule_no_system_uri(pulldown):
    """10. No System.Uri: it moved assemblies and throws at module load on
    Revit 2025 and later."""
    problems = []
    for path in python_files(pulldown):
        text = read(path)
        if re.search(r"from\s+System\s+import\s+.*\bUri\b", text) or "System.Uri" in text:
            problems.append("{0} uses System.Uri".format(os.path.basename(path)))
    return problems


def rule_modules_load(pulldown):
    """11. Every module loads against the stub API."""
    import importlib
    import importlib.util
    problems = []
    folders = [tool_dir(pulldown), os.path.join(pulldown, SETTINGS_FOLDER)]
    for folder in folders:
        if folder not in sys.path:
            sys.path.insert(0, folder)
    install_stubs()
    os.environ["REVOBIM_IMPORT_CHECK"] = "1"
    for name in ("tle_clr", "tle_core", "theme", "tle_ui", "tle_ops"):
        sys.modules.pop(name, None)
    try:
        for name in ("tle_clr", "tle_core", "theme", "tle_ui", "tle_ops"):
            try:
                importlib.import_module(name)
            except Exception as error:
                problems.append("{0}.py will not load: {1}: {2}".format(
                    name, type(error).__name__, error))
        for folder, label in ((folders[0], "command"), (folders[1], "settings")):
            path = os.path.join(folder, "script.py")
            if not os.path.exists(path):
                continue
            try:
                spec = importlib.util.spec_from_file_location(
                    "tle_script_" + label, path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
            except Exception as error:
                problems.append("the {0} script.py will not load: {1}: {2}".format(
                    label, type(error).__name__, error))
    finally:
        remove_stubs()
        for name in ("tle_clr", "tle_core", "theme", "tle_ui", "tle_ops"):
            sys.modules.pop(name, None)
        for folder in folders:
            if folder in sys.path:
                sys.path.remove(folder)
    return problems


def rule_palettes_cover_theme(pulldown):
    """12. Both palettes carry a colour for every brush Theme.xaml declares."""
    text = read(os.path.join(tool_dir(pulldown), "Theme.xaml"))
    brush_keys = set(re.findall(
        r'<SolidColorBrush\s+x:Key="([^"]+)"', text))

    theme_text = read(os.path.join(tool_dir(pulldown), "theme.py"))
    namespace = {}
    exec(compile(theme_text.replace("import tle_clr", "tle_clr = None")
                 .replace("from System.Windows.Media import SolidColorBrush, ColorConverter",
                          "SolidColorBrush = ColorConverter = None"),
                 "theme.py", "exec"), namespace)

    problems = []
    for label in ("DARK", "LIGHT"):
        palette = namespace.get(label, {})
        for key in sorted(brush_keys):
            if key not in palette:
                problems.append("theme.py {0} has no colour for {1}".format(label, key))
    for key in sorted(namespace.get("KEYS", ())):
        if key not in brush_keys:
            problems.append("theme.py KEYS lists {0}, which Theme.xaml does not "
                            "declare".format(key))
    return problems


# Names the engine supplies rather than the module: pyRevit injects __revit__,
# and IronPython 2.7 carries builtins CPython 3 has dropped.
ENGINE_GLOBALS = set([
    "__revit__", "__revit_ui__", "__commandname__", "__file__", "__name__",
    "__title__", "__doc__", "__persistentengine__",
    "unicode", "basestring", "xrange", "long", "reduce", "raw_input", "unichr",
])


def _globals_used(table, defined, problems, filename, path=()):
    for symbol in table.get_symbols():
        name = symbol.get_name()
        if not symbol.is_global():
            continue
        if symbol.is_assigned() or name in defined:
            continue
        problems.append("{0}: {1} reaches for {2}, which the module does not "
                        "define".format(filename, ".".join(path) or "module level", name))
    for child in table.get_children():
        _globals_used(child, defined, problems, filename, path + (child.get_name(),))


def rule_globals_exist(pulldown):
    """13. Every global name a function reaches for exists in its module.

    This is the rule that catches a function using a name its own signature
    does not carry - v2.0.0 shipped with `_do_independent` reading `view`,
    which was only ever a local of its caller, and it got as far as a live
    model before anyone saw it.
    """
    import builtins as _builtins
    problems = []
    for path in python_files(pulldown):
        filename = os.path.basename(path)
        source = read(path)
        try:
            top = symtable.symtable(source, filename, "exec")
        except Exception as error:
            problems.append("{0} will not compile: {1}".format(filename, error))
            continue
        defined = set(dir(_builtins)) | ENGINE_GLOBALS
        defined.update(symbol.get_name() for symbol in top.get_symbols())
        for child in top.get_children():
            _globals_used(child, defined, problems, filename, (child.get_name(),))
    return problems


def rule_call_arity(pulldown):
    """14. Every call to a function in the same module passes a number of
    arguments the function will actually take.

    The other half of the same bug: adding an argument to a function and
    missing one of its call sites is not a name error, so rule 13 does not see
    it - it is a TypeError, and the first thing that reports it is Revit.
    """
    problems = []
    for path in python_files(pulldown):
        filename = os.path.basename(path)
        try:
            tree = ast.parse(read(path), filename)
        except Exception:
            continue  # rule 13 reports this
        signatures = {}
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef):
                continue
            spec = node.args
            positional = list(getattr(spec, "posonlyargs", [])) + list(spec.args)
            least = len(positional) - len(spec.defaults)
            most = None if spec.vararg else len(positional)
            signatures[node.name] = (least, most, [arg.arg for arg in positional])

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            name = node.func.id
            if name not in signatures:
                continue
            least, most, names = signatures[name]
            if any(isinstance(arg, ast.Starred) for arg in node.args):
                continue
            if any(word.arg is None for word in node.keywords):
                continue
            given = len(node.args)
            for word in node.keywords:
                if word.arg in names:
                    given += 1
            if given < least or (most is not None and given > most):
                problems.append(
                    "{0} line {1}: {2}() is given {3} argument{4}, but takes "
                    "{5}".format(filename, node.lineno, name, given,
                                 "" if given == 1 else "s",
                                 least if most == least else "{0} to {1}".format(
                                     least, most if most is not None else "any")))
    return problems


RULES = (
    ("every .xaml parses as XML", rule_xaml_parses),
    ("tle_clr is imported before any .NET name", rule_clr_first),
    ("no StaticResource in a layout", rule_no_static_resource),
    ("every DynamicResource key exists in Theme.xaml", rule_dynamic_keys_exist),
    ("no style applied to an element its TargetType does not match",
     rule_style_target_types),
    ("no FindName without a matching x:Name", rule_findname_has_xname),
    ("no f-strings", rule_no_fstrings),
    ("no print", rule_no_print),
    ("no bare .IntegerValue", rule_no_integervalue),
    ("no System.Uri", rule_no_system_uri),
    ("every module loads against the stub API", rule_modules_load),
    ("both palettes cover every brush", rule_palettes_cover_theme),
    ("every global name a function reaches for exists", rule_globals_exist),
    ("every call passes a number of arguments the function takes", rule_call_arity),
)


def run(pulldown, quiet=False):
    failures = 0
    for label, rule in RULES:
        try:
            problems = rule(pulldown)
        except Exception as error:
            problems = ["the rule itself blew up: {0}: {1}".format(
                type(error).__name__, error)]
        if problems:
            failures += 1
            if not quiet:
                out("FAIL  " + label)
                for problem in problems:
                    out("      " + problem)
        elif not quiet:
            out("ok    " + label)
    return failures


# ============================================================================
# selftest
# ============================================================================

BREAKAGES = [
    ("every .xaml parses as XML", "TagLeaderElbowResults.xaml",
     lambda t: t.replace("<!-- ====================== header ======================",
                         "<!-- ---------------------- header ----------------------")),
    ("tle_clr is imported before any .NET name", "theme.py",
     lambda t: t.replace("import tle_clr  # noqa: F401  assemblies first\n", "")),
    ("no StaticResource in a layout", "TagLeaderElbowSettings.xaml",
     lambda t: t.replace('Style="{DynamicResource ThemedBox}"',
                         'Style="{StaticResource ThemedBox}"', 1)),
    ("every DynamicResource key exists in Theme.xaml", "TagLeaderElbowResults.xaml",
     lambda t: t.replace("{DynamicResource WindowBackBrush}",
                         "{DynamicResource NoSuchBrush}", 1)),
    ("no style applied to an element its TargetType does not match",
     "TagLeaderElbowSettings.xaml",
     lambda t: t.replace('Style="{DynamicResource GhostButton}" MinWidth="90"',
                         'Style="{DynamicResource ThemedBox}" MinWidth="90"', 1)),
    ("no FindName without a matching x:Name", "tle_ui.py",
     lambda t: t.replace('find("ElbowMmBox").Text = str(cfg.get("elbow_mm"))',
                         'find("ElbowMmBoxx").Text = str(cfg.get("elbow_mm"))', 1)),
    ("no f-strings", "tle_ops.py",
     lambda t: t.replace('    rows = []\n    done = 0',
                         '    rows = []\n    _bad = f"broken"\n    done = 0', 1)),
    ("no print", "tle_core.py",
     lambda t: t.replace("def mm_to_ft(mm):", "def mm_to_ft(mm):\n    print(mm)", 1)),
    ("no bare .IntegerValue", "tle_ops.py",
     lambda t: t.replace("def view_scale(view):",
                         "def view_scale(view):\n    _ = view.Id.IntegerValue", 1)),
    ("no System.Uri", "tle_ui.py",
     lambda t: t.replace("from System.IO import StringReader",
                         "from System.IO import StringReader\nfrom System import Uri", 1)),
    ("every module loads against the stub API", "tle_ops.py",
     lambda t: t.replace("from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter",
                         "from Autodesk.Revit.DB import ObjectType, ISelectionFilter", 1)),
    ("both palettes cover every brush", "theme.py",
     lambda t: t.replace('    "OrangeBrush": "#B96A12",\n', "", 1)),
    ("every global name a function reaches for exists", "tle_ops.py",
     lambda t: t.replace("def _do_independent(doc, tag, view, right, length, cfg, box=None):",
                         "def _do_independent(doc, tag, right, length, cfg, box=None):", 1)),
    ("every call passes a number of arguments the function takes", "tle_ops.py",
     lambda t: t.replace("_place(\n            head, up, right, sign, length, box, width, line_ft, lines, cfg)",
                         "_place(\n            head, up, right, sign, length, box, width, line_ft, cfg)", 1)),
]


def selftest():
    source = os.path.dirname(HERE)
    out("Baseline:")
    baseline = run(source)
    out("")
    if baseline:
        out("The tool does not pass its own check, so the selftest is meaningless.")
        return 1

    passed = 0
    for label, filename, break_it in BREAKAGES:
        temp = tempfile.mkdtemp(prefix="tle_check_")
        try:
            copy = os.path.join(temp, os.path.basename(source))
            shutil.copytree(source, copy)
            target = None
            for folder in (os.path.join(copy, TOOL_FOLDER),
                           os.path.join(copy, SETTINGS_FOLDER)):
                candidate = os.path.join(folder, filename)
                if os.path.exists(candidate):
                    target = candidate
                    break
            if target is None:
                out("SKIP  {0}: {1} is not in the tool".format(label, filename))
                continue
            text = read(target)
            broken = break_it(text)
            if broken == text:
                out("SKIP  {0}: the breakage did not change {1}".format(label, filename))
                continue
            handle = open(target, "w")
            try:
                handle.write(broken)
            finally:
                handle.close()

            result = subprocess.run(
                [sys.executable, os.path.join(copy, TOOL_FOLDER, "import_check.py"),
                 "--dir", copy],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=copy)
            report = result.stdout.decode("utf-8", "replace")
            caught = ("FAIL  " + label) in report
            if caught:
                passed += 1
                out("caught  " + label)
            else:
                out("MISSED  " + label)
                out(report)
        finally:
            shutil.rmtree(temp, ignore_errors=True)

    out("")
    out("{0} of {1} rules caught their own breakage.".format(passed, len(BREAKAGES)))
    return 0 if passed == len(BREAKAGES) else 1


def main(argv):
    if "--selftest" in argv:
        return selftest()
    pulldown = os.path.dirname(HERE)
    if "--dir" in argv:
        pulldown = argv[argv.index("--dir") + 1]
    out("RevoBIM Tag Leader Elbow bench check")
    out("")
    failures = run(pulldown)
    out("")
    out("{0} rule{1} failed.".format(failures, "" if failures == 1 else "s")
        if failures else "All rules pass.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
