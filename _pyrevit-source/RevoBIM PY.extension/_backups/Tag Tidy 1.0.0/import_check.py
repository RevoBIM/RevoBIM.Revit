# -*- coding: utf-8 -*-
"""Bench check for RevoBIM Tag Tidy.

Run it under plain CPython from the Tag Tidy.pulldown folder:

    python import_check.py
    python import_check.py --selftest

It loads every shipped module against a stub Revit and .NET API that declares
each name in the namespace the real API puts it in, so a mis-namespaced import
fails on the bench instead of showing up in Revit as a blank white pyRevit
window with no traceback in it.  On top of that it checks the RevoBIM house
rules a stub cannot see: every .NET namespace has its assembly referenced,
every window has a working shrink-to-taskbar drawer, the dark palette is
Revit's own and readable, the ribbon names are unique, and the changelog
carries the version.  --selftest breaks each rule on purpose and confirms the
check catches it: a rule nobody has tested is a rule that does not work.

Rules that require something to be present read the code through the AST,
never the raw text, so a docstring mentioning the thing cannot satisfy them.
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
PULLDOWN_NAME = "Tag Tidy"
COMMAND_FOLDER = "RevoBIM Tag Tidy.pushbutton"
SETTINGS_FOLDER = "RevoBIM Tag Tidy Settings.pushbutton"
BUTTON_FOLDERS = (COMMAND_FOLDER, SETTINGS_FOLDER)
BENCH_FILES = ("import_check.py", "bench_logic.py")
MODULES = ("tidy_clr", "tidy_core", "tidy_theme", "tidy_ui", "tidy_ops")
ENV_FLAG = "REVOBIM_IMPORT_CHECK"

LAYOUTS = ("TagTidyResults.xaml", "TagTidySettings.xaml")


def out(text):
    sys.stdout.write(text + "\n")


# ============================================================================
# the stub API
# ============================================================================

NAMESPACES = {
    "clr": ["AddReference", "AddReferenceByName", "GetClrType"],
    "System": ["Object", "String", "Exception", "Math", "Convert", "Environment",
               "Array", "Double", "Int32", "Boolean", "TimeSpan"],
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
                       "WindowStartupLocation", "MessageBox", "SizeToContent",
                       "Duration"],
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
        "ViewType", "WorksharingUtils", "CheckoutStatus", "ModelUpdatesStatus",
        "LeaderEndCondition", "TagOrientation", "Outline", "BoundingBoxIntersectsFilter",
        "CurveElement", "IFailuresPreprocessor", "FailureProcessingResult",
        "FailureSeverity"],
    "Autodesk.Revit.DB.Architecture": ["RoomTag"],
    "Autodesk.Revit.DB.Mechanical": ["SpaceTag"],
    "Autodesk.Revit.UI": ["TaskDialog", "TaskDialogCommonButtons", "TaskDialogResult",
                          "RevitCommandId", "PostableCommand", "UIApplication",
                          "UIDocument", "ExternalEvent", "IExternalEventHandler",
                          "UIThemeManager", "UITheme"],
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
        sys.modules[name] = _StubModule(name, NAMESPACES[name])
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

def tool_dir(root):
    """The pulldown folder: every shared module, layout and Theme.xaml."""
    return root


def python_files(root):
    found = []
    for name in sorted(os.listdir(root)):
        if name.endswith(".py") and name not in BENCH_FILES:
            found.append(os.path.join(root, name))
    for folder in BUTTON_FOLDERS:
        path = os.path.join(root, folder, "script.py")
        if os.path.exists(path):
            found.append(path)
    return found


def xaml_files(root):
    return [os.path.join(root, name) for name in sorted(os.listdir(root))
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

def rule_xaml_parses(root):
    """1. Every .xaml parses as XML.  A run of hyphens in a comment is illegal
    XML and shows up in Revit only as a dead window."""
    problems = []
    for path in xaml_files(root):
        try:
            minidom.parseString(read(path))
        except Exception as error:
            problems.append("{0} will not parse as XML: {1}".format(
                os.path.basename(path), error))
    return problems


def rule_clr_first(root):
    """2. No module reaches into System.* or Autodesk.* at module level without
    importing tidy_clr first, or importing it too late in the file."""
    problems = []
    pattern = re.compile(r"^(?:from|import)\s+(System|Autodesk)\b")
    for path in python_files(root):
        name = os.path.basename(path)
        lines = read(path).splitlines()
        clr_line = None
        first_dotnet = None
        for index, line in enumerate(lines):
            if line.startswith("import tidy_clr") and clr_line is None:
                clr_line = index
            if pattern.match(line) and first_dotnet is None:
                first_dotnet = index
        if first_dotnet is None:
            continue
        if clr_line is None:
            problems.append("{0} reaches into .NET without importing tidy_clr".format(name))
        elif clr_line > first_dotnet:
            problems.append("{0} imports tidy_clr after line {1}, too late".format(
                name, first_dotnet + 1))
    return problems


def rule_no_static_resource(root):
    """3. No StaticResource in a layout: Theme.xaml is merged in after the
    layout has been parsed, so a StaticResource fails at load."""
    problems = []
    for name in LAYOUTS:
        path = os.path.join(tool_dir(root), name)
        if os.path.exists(path) and "StaticResource" in read(path):
            problems.append("{0} uses StaticResource; layouts may only use "
                            "DynamicResource".format(name))
    return problems


def _theme_keys(root):
    return set(re.findall(r'x:Key="([^"]+)"', read(os.path.join(tool_dir(root), "Theme.xaml"))))


def rule_dynamic_keys_exist(root):
    """4. Every DynamicResource key is defined in Theme.xaml."""
    keys = _theme_keys(root)
    problems = []
    for path in xaml_files(root):
        for used in sorted(set(re.findall(r"\{DynamicResource\s+([A-Za-z0-9_]+)\s*\}",
                                          read(path)))):
            if used not in keys:
                problems.append("{0} asks for DynamicResource {1}, which Theme.xaml "
                                "does not define".format(os.path.basename(path), used))
    return problems


def rule_style_target_types(root):
    """5. No Style="{DynamicResource K}" on an element K's TargetType does not
    match.  WPF raises that when the style is applied, so it is another dead
    window rather than an error anybody sees."""
    theme = minidom.parseString(read(os.path.join(tool_dir(root), "Theme.xaml")))
    targets = {}
    for node in theme.getElementsByTagName("Style"):
        key = node.getAttribute("x:Key")
        target = node.getAttribute("TargetType")
        if key and target:
            targets[key] = target
    problems = []
    for path in xaml_files(root):
        try:
            document = minidom.parseString(read(path))
        except Exception:
            continue  # rule 1 reports this
        for node in document.getElementsByTagName("*"):
            match = re.match(r"\{DynamicResource\s+([A-Za-z0-9_]+)\s*\}",
                             node.getAttribute("Style") or "")
            if not match:
                continue
            wanted = targets.get(match.group(1))
            if wanted and wanted != node.tagName:
                problems.append("{0}: style {1} targets {2} but is applied to a {3}".format(
                    os.path.basename(path), match.group(1), wanted, node.tagName))
    return problems


CONTROL_NAME = re.compile(
    r'"([A-Z][A-Za-z0-9]*(?:Box|Chk|Combo|Btn|Text|Note|Panel|Chip|Bar|Label|Layer))"')


def rule_findname_has_xname(root):
    """6. No FindName without a matching x:Name, following aliases (the code
    writes find = self.window.FindName), and no control name held in a table
    (NUMBER_BOXES, CHECKS, COMBOS) that no layout defines."""
    names = set()
    for path in xaml_files(root):
        names.update(re.findall(r'x:Name="([^"]+)"', read(path)))
    problems = []
    for path in python_files(root):
        text = read(path)
        aliases = set(re.findall(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*[^=\n]*\.FindName\s*$",
                                 text, re.M))
        calls = set(re.findall(r'FindName\(\s*"([^"]+)"\s*\)', text))
        for alias in aliases:
            calls.update(re.findall(r'\b' + alias + r'\(\s*"([^"]+)"\s*\)', text))
        calls.update(CONTROL_NAME.findall(text))
        for call in sorted(calls):
            if call not in names:
                problems.append("{0} asks for x:Name {1}, which no layout defines".format(
                    os.path.basename(path), call))
    return problems


def rule_no_fstrings(root):
    """7. No f-strings: IronPython 2.7 will not parse them."""
    problems = []
    for path in python_files(root):
        for index, line in enumerate(read(path).splitlines()):
            if re.search(r"(?<![A-Za-z0-9_])[fF]['\"]", line):
                problems.append("{0} line {1} looks like an f-string".format(
                    os.path.basename(path), index + 1))
    return problems


def rule_no_print(root):
    """8. No print: it opens pyRevit's output console."""
    problems = []
    for path in python_files(root):
        for index, line in enumerate(read(path).splitlines()):
            if re.search(r"(?<![A-Za-z0-9_.])print\s*[\(\s]", line):
                problems.append("{0} line {1} calls print".format(
                    os.path.basename(path), index + 1))
    return problems


def rule_no_integervalue(root):
    """9. No bare .IntegerValue: removed in Revit 2026.  Allowed only inside
    the guarded eid_value helper in tidy_core."""
    problems = []
    for path in python_files(root):
        name = os.path.basename(path)
        if name == "tidy_core.py":
            continue
        for index, line in enumerate(read(path).splitlines()):
            if ".IntegerValue" in line:
                problems.append("{0} line {1} touches .IntegerValue directly".format(
                    name, index + 1))
    return problems


def rule_no_system_uri(root):
    """10. No System.Uri: it moved assemblies and throws at module load on
    Revit 2025 and later."""
    problems = []
    for path in python_files(root):
        text = read(path)
        if re.search(r"from\s+System\s+import\s+.*\bUri\b", text) or "System.Uri" in text:
            problems.append("{0} uses System.Uri".format(os.path.basename(path)))
    return problems


def rule_modules_load(root):
    """11. Every module loads against the stub API, and so do both scripts."""
    import importlib
    import importlib.util
    problems = []
    if root not in sys.path:
        sys.path.insert(0, root)
    install_stubs()
    os.environ[ENV_FLAG] = "1"
    for name in MODULES:
        sys.modules.pop(name, None)
    try:
        for name in MODULES:
            try:
                importlib.import_module(name)
            except Exception as error:
                problems.append("{0}.py will not load: {1}: {2}".format(
                    name, type(error).__name__, error))
        for folder, label in ((COMMAND_FOLDER, "command"), (SETTINGS_FOLDER, "settings")):
            path = os.path.join(root, folder, "script.py")
            if not os.path.exists(path):
                problems.append("the {0} button has no script.py".format(label))
                continue
            try:
                spec = importlib.util.spec_from_file_location("tidy_script_" + label, path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
            except Exception as error:
                problems.append("the {0} script.py will not load: {1}: {2}".format(
                    label, type(error).__name__, error))
    finally:
        remove_stubs()
        for name in MODULES:
            sys.modules.pop(name, None)
        if root in sys.path:
            sys.path.remove(root)
    return problems


def _literal(path, name):
    """A module-level literal assignment, read through the AST."""
    tree = ast.parse(read(path), os.path.basename(path))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return ast.literal_eval(node.value)
    return None


def rule_palettes_cover_theme(root):
    """12. Both palettes carry a colour for every brush Theme.xaml declares."""
    brush_keys = set(re.findall(r'<SolidColorBrush\s+x:Key="([^"]+)"',
                                read(os.path.join(root, "Theme.xaml"))))
    path = os.path.join(root, "tidy_theme.py")
    problems = []
    for label in ("DARK", "LIGHT"):
        palette = _literal(path, label) or {}
        for key in sorted(brush_keys):
            if key not in palette:
                problems.append("tidy_theme.py {0} has no colour for {1}".format(label, key))
    for key in sorted(_literal(path, "KEYS") or ()):
        if key not in brush_keys:
            problems.append("tidy_theme.py KEYS lists {0}, which Theme.xaml does not "
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
        if not symbol.is_global() or symbol.is_assigned() or name in defined:
            continue
        problems.append("{0}: {1} reaches for {2}, which the module does not "
                        "define".format(filename, ".".join(path) or "module level", name))
    for child in table.get_children():
        _globals_used(child, defined, problems, filename, path + (child.get_name(),))


def rule_globals_exist(root):
    """13. Every global name a function reaches for exists in its module:
    the rule that catches a function using a name its signature does not
    carry, which otherwise gets as far as a live model before anyone sees it."""
    import builtins as _builtins
    problems = []
    for path in python_files(root):
        filename = os.path.basename(path)
        try:
            top = symtable.symtable(read(path), filename, "exec")
        except Exception as error:
            problems.append("{0} will not compile: {1}".format(filename, error))
            continue
        defined = set(dir(_builtins)) | ENGINE_GLOBALS
        defined.update(symbol.get_name() for symbol in top.get_symbols())
        for child in top.get_children():
            _globals_used(child, defined, problems, filename, (child.get_name(),))
    return problems


def rule_call_arity(root):
    """14. Every call to a function in the same module passes a number of
    arguments the function will actually take.  Adding an argument and
    missing a call site is a TypeError, not a name error, so rule 13 does not
    see it; the first thing that would is Revit."""
    problems = []
    for path in python_files(root):
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
            given = len(node.args) + sum(1 for word in node.keywords if word.arg in names)
            if given < least or (most is not None and given > most):
                problems.append(
                    "{0} line {1}: {2}() is given {3} argument{4}, but takes {5}".format(
                        filename, node.lineno, name, given, "" if given == 1 else "s",
                        least if most == least else "{0} to {1}".format(
                            least, most if most is not None else "any")))
    return problems


# ============================================================================
# RevoBIM house rules
# ============================================================================

# Every namespace the tool imports, and every assembly that can provide it on
# .NET Framework 4.8 (Revit 2024) or .NET 8 (Revit 2025 and later).  At least
# one of them has to be in tidy_clr's list.  A stub API cannot catch a missing
# reference, since under CPython a namespace either resolves or it does not;
# this table is the only thing that can.
PROVIDERS = {
    "System": ("mscorlib", "System", "System.Runtime"),
    "System.IO": ("mscorlib", "System.IO", "System.Runtime"),
    "System.Xml": ("System.Xml", "System.Xml.ReaderWriter"),
    "System.Diagnostics": ("System", "System.Diagnostics.Process"),
    "System.Drawing": ("System.Drawing", "System.Drawing.Primitives"),
    "System.Windows.Forms": ("System.Windows.Forms",),
    "System.Windows": ("PresentationFramework", "PresentationCore", "WindowsBase"),
    "System.Windows.Controls": ("PresentationFramework",),
    "System.Windows.Controls.Primitives": ("PresentationFramework",),
    "System.Windows.Markup": ("PresentationFramework", "System.Xaml"),
    "System.Windows.Media": ("PresentationCore",),
    "System.Windows.Media.Imaging": ("PresentationCore",),
    "System.Windows.Input": ("PresentationCore", "WindowsBase"),
    "System.Windows.Interop": ("PresentationFramework", "PresentationCore"),
    "System.Windows.Threading": ("WindowsBase",),
}
# pyRevit hands every engine the running Revit's own assemblies.
PYREVIT_PROVIDES = ("Autodesk.Revit.DB", "Autodesk.Revit.UI", "Autodesk.Revit.UI.Selection",
                    "Autodesk.Revit.DB.Architecture", "Autodesk.Revit.DB.Mechanical",
                    "Autodesk.Revit", "Autodesk")


def _referenced_at_import(root):
    """The assemblies tidy_clr references when it is imported: its
    _ASSEMBLIES tuple, plus any clr.AddReference("...") at module level.
    A reference inside a def only runs after the import it was meant to
    protect, so it does not count."""
    path = os.path.join(root, "tidy_clr.py")
    tree = ast.parse(read(path), "tidy_clr.py")
    found = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "_ASSEMBLIES":
                    found.update(ast.literal_eval(node.value))
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            continue
        for sub in ast.walk(node):
            if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) and
                    sub.func.attr == "AddReference" and sub.args and
                    isinstance(sub.args[0], ast.Constant) and isinstance(sub.args[0].value, str)):
                found.add(sub.args[0].value)
    return found


def _dotnet_imports(root):
    out = []
    for path in python_files(root):
        try:
            tree = ast.parse(read(path), os.path.basename(path))
        except Exception:
            continue
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            elif isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            for name in names:
                if name.split(".")[0] in ("System", "Autodesk"):
                    out.append((os.path.basename(path), node.lineno, name))
    return out


def rule_assemblies_referenced(root):
    """15. Every System.* and Autodesk.* namespace imported anywhere in the
    tool maps back to an assembly tidy_clr references at import time."""
    referenced = _referenced_at_import(root)
    problems = []
    for filename, line, name in _dotnet_imports(root):
        if name in PYREVIT_PROVIDES:
            continue
        providers = PROVIDERS.get(name)
        if providers is None:
            problems.append("{0} line {1} imports {2}, which the PROVIDERS table does not "
                            "know; add the assemblies that provide it".format(filename, line, name))
            continue
        if not any(assembly in referenced for assembly in providers):
            problems.append("{0} line {1} imports {2}, but tidy_clr references none of {3}".format(
                filename, line, name, ", ".join(providers)))
    return problems


def _classes(root, filename):
    tree = ast.parse(read(os.path.join(root, filename)), filename)
    return dict((node.name, node) for node in tree.body if isinstance(node, ast.ClassDef))


def _calls(node, name):
    """Calls inside node to a function or method called name."""
    out = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            func = sub.func
            if (isinstance(func, ast.Name) and func.id == name) or \
                    (isinstance(func, ast.Attribute) and func.attr == name):
                out.append(sub)
    return out


def rule_every_window_has_a_drawer(root):
    """16. Every window the tool opens carries a shrink-to-taskbar drawer: a
    class that loads a layout also builds a drawer, and every layout has the
    header, root, shrink button and grip layer the drawer needs."""
    problems = []
    for name, node in sorted(_classes(root, "tidy_ui.py").items()):
        if _calls(node, "load_window") and not (_calls(node, "add_drawer") or
                                                 _calls(node, "WindowDrawer")):
            problems.append("tidy_ui.{0} opens a window with no shrink-to-taskbar "
                            "drawer".format(name))
    for layout in LAYOUTS:
        text = read(os.path.join(root, layout))
        for needed in ("HeaderBar", "RootBorder", "ShrinkBtn", "GripLayer", "ThemeChip",
                       "VersionText", "CloseBtn"):
            if 'x:Name="{0}"'.format(needed) not in text:
                problems.append("{0} has no {1}".format(layout, needed))
    return problems


def rule_shrink_button_wired(root):
    """17. The drawer wires the shrink button's Click, and Chrome hands it
    the button from the layout.  A button drawn but never wired does
    nothing at all, silently."""
    classes = _classes(root, "tidy_ui.py")
    problems = []
    drawer = classes.get("WindowDrawer")
    if drawer is None:
        return ["tidy_ui has no WindowDrawer"]
    wired = False
    for sub in ast.walk(drawer):
        if isinstance(sub, ast.AugAssign) and isinstance(sub.target, ast.Attribute) and \
                sub.target.attr == "Click":
            wired = True
    if not wired:
        problems.append("WindowDrawer never wires its button's Click")
    chrome = classes.get("Chrome")
    handed = False
    if chrome is not None:
        # window.FindName, or an alias of it such as find = self.window.FindName
        for sub in ast.walk(chrome):
            if isinstance(sub, ast.Call) and sub.args and \
                    isinstance(sub.args[0], ast.Constant) and sub.args[0].value == "ShrinkBtn":
                handed = True
    if not handed:
        problems.append("Chrome never finds ShrinkBtn to hand to the drawer")
    return problems


def rule_animation_released(root):
    """18. When a slide finishes, the drawer releases both Window.TopProperty
    and Window.HeightProperty (BeginAnimation(prop, None)).  An animation
    holds its end value over every later assignment, and a window left that
    way can never be moved or resized again, with nothing raised to say so."""
    drawer = _classes(root, "tidy_ui.py").get("WindowDrawer")
    if drawer is None:
        return ["tidy_ui has no WindowDrawer"]
    released = set()
    for call in _calls(drawer, "BeginAnimation"):
        if len(call.args) == 2 and isinstance(call.args[1], ast.Constant) and \
                call.args[1].value is None and isinstance(call.args[0], ast.Attribute):
            released.add(call.args[0].attr)
    return ["WindowDrawer never releases {0}".format(prop)
            for prop in ("TopProperty", "HeightProperty") if prop not in released]


def rule_changelog_has_version(root):
    """19. CHANGELOG.md beside the modules has an entry for __version__."""
    version = _literal(os.path.join(root, "tidy_core.py"), "__version__")
    path = os.path.join(root, "CHANGELOG.md")
    if not os.path.exists(path):
        return ["there is no CHANGELOG.md"]
    if not re.search(r"^## " + re.escape(str(version)) + r"\b", read(path), re.M):
        return ["CHANGELOG.md has no '## {0}' entry for the version".format(version)]
    return []


# Revit's own dark theme, sampled from its dark Project Browser.
REVIT_DARK = {
    "BarBrush": "#222933",
    "WindowBackBrush": "#3C4454",
    "FieldBrush": "#2D3441",
    "CardBrush": "#323C48",
    "HoverBrush": "#444E5E",
    "SelectionBrush": "#3A7392",
    "EdgeBrush": "#515C6B",
    "TextBrush": "#EEF0F4",
}
DARK_SURFACES = ("WindowBackBrush", "CardBrush", "FieldBrush", "BarBrush")
CONTRAST = (("TextBrush", 7.0), ("MutedBrush", 4.0), ("BlueBrush", 4.0))


def _luminance(hex_value):
    value = hex_value.lstrip("#")[-6:]
    channels = [int(value[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a, b):
    high, low = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def rule_revit_dark(root):
    """20. Dark is Revit's own dark theme, Theme.xaml bakes the same values in
    (or a window shows the old colours for a moment), and text, muted text
    and blue all read on every dark surface."""
    dark = _literal(os.path.join(root, "tidy_theme.py"), "DARK") or {}
    problems = []
    for key, wanted in sorted(REVIT_DARK.items()):
        if dark.get(key, "").upper() != wanted.upper():
            problems.append("DARK {0} is {1}, Revit's dark is {2}".format(
                key, dark.get(key), wanted))
    baked = dict(re.findall(r'<SolidColorBrush\s+x:Key="([^"]+)"\s+Color="([^"]+)"',
                            read(os.path.join(root, "Theme.xaml"))))
    for key, value in sorted(dark.items()):
        if baked.get(key, "").upper() != value.upper():
            problems.append("Theme.xaml bakes {0} as {1}, the dark palette says {2}".format(
                key, baked.get(key), value))
    for fore, least in CONTRAST:
        for back in DARK_SURFACES:
            if fore in dark and back in dark:
                ratio = contrast(dark[fore], dark[back])
                if ratio < least:
                    problems.append("{0} on {1} is {2:.2f}:1, under {3}:1".format(
                        fore, back, ratio, least))
    return problems


def rule_ribbon_names(root):
    """21. The pulldown holds the two buttons, each ribbon name unique and
    prefixed RevoBIM so it can be found in Revit's Keyboard Shortcuts list,
    neither sharing the pulldown's name ("The name already exists"), each
    bundle title matching its folder, and no bundle.yaml on the pulldown
    itself, which would overwrite the panel's own configuration."""
    problems = []
    if os.path.exists(os.path.join(root, "bundle.yaml")):
        problems.append("the pulldown has a bundle.yaml; RevoBIM pulldowns do not")
    seen = set()
    for folder in BUTTON_FOLDERS:
        name = folder[:-len(".pushbutton")]
        if not name.startswith("RevoBIM "):
            problems.append("{0} is not prefixed RevoBIM".format(folder))
        if name == PULLDOWN_NAME:
            problems.append("{0} shares the pulldown's name".format(folder))
        path = os.path.join(root, folder, "bundle.yaml")
        if not os.path.exists(path):
            problems.append("{0} has no bundle.yaml".format(folder))
            continue
        match = re.search(r"^title:\s*(.+?)\s*$", read(path), re.M)
        title = match.group(1) if match else None
        if title != name:
            problems.append("{0} bundle title is {1!r}, not {2!r}".format(folder, title, name))
        if title in seen or title == PULLDOWN_NAME:
            problems.append("{0} bundle title {1!r} is not unique".format(folder, title))
        seen.add(title)
    return problems


RULES = (
    ("every .xaml parses as XML", rule_xaml_parses),
    ("tidy_clr is imported before any .NET name", rule_clr_first),
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
    ("every .NET namespace has its assembly referenced", rule_assemblies_referenced),
    ("every window has a shrink-to-taskbar drawer", rule_every_window_has_a_drawer),
    ("the shrink button is wired", rule_shrink_button_wired),
    ("the drawer releases its animations", rule_animation_released),
    ("the changelog has the version", rule_changelog_has_version),
    ("dark is Revit's own dark, and readable", rule_revit_dark),
    ("ribbon names are unique and prefixed RevoBIM", rule_ribbon_names),
)


def run(root, quiet=False):
    failures = 0
    for label, rule in RULES:
        try:
            problems = rule(root)
        except Exception as error:
            problems = ["the rule itself blew up: {0}: {1}".format(type(error).__name__, error)]
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
    ("every .xaml parses as XML", "TagTidyResults.xaml",
     lambda t: t.replace("<!-- ====================== summary ======================",
                         "<!-- ---------------------- summary ----------------------")),
    ("tidy_clr is imported before any .NET name", "tidy_theme.py",
     lambda t: t.replace("import tidy_clr  # noqa: F401  assemblies first\n", "")),
    ("no StaticResource in a layout", "TagTidySettings.xaml",
     lambda t: t.replace('Style="{DynamicResource ThemedBox}"',
                         'Style="{StaticResource ThemedBox}"', 1)),
    ("every DynamicResource key exists in Theme.xaml", "TagTidyResults.xaml",
     lambda t: t.replace("{DynamicResource WindowBackBrush}",
                         "{DynamicResource NoSuchBrush}", 1)),
    ("no style applied to an element its TargetType does not match",
     "TagTidySettings.xaml",
     lambda t: t.replace('Style="{DynamicResource GhostButton}" MinWidth="90"',
                         'Style="{DynamicResource ThemedBox}" MinWidth="90"', 1)),
    ("no FindName without a matching x:Name", "tidy_ui.py",
     lambda t: t.replace('("ClearanceBox", "clearance_mm"', '("ClearenceBox", "clearance_mm"', 1)),
    ("no f-strings", "tidy_ops.py",
     lambda t: t.replace("    problems = {}\n    transaction",
                         "    problems = {}\n    _bad = f\"broken\"\n    transaction", 1)),
    ("no print", "tidy_core.py",
     lambda t: t.replace("def mm_to_ft(mm):", "def mm_to_ft(mm):\n    print(mm)", 1)),
    ("no bare .IntegerValue", "tidy_ops.py",
     lambda t: t.replace("def view_scale(view):",
                         "def view_scale(view):\n    _ = view.Id.IntegerValue", 1)),
    ("no System.Uri", "tidy_ui.py",
     lambda t: t.replace("from System.IO import StringReader",
                         "from System.IO import StringReader\nfrom System import Uri", 1)),
    ("every module loads against the stub API", "tidy_ops.py",
     lambda t: t.replace("from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter",
                         "from Autodesk.Revit.DB import ObjectType, ISelectionFilter", 1)),
    ("both palettes cover every brush", "tidy_theme.py",
     lambda t: t.replace('    "OrangeBrush": "#B96A12",\n', "", 1)),
    ("every global name a function reaches for exists", "tidy_ops.py",
     lambda t: t.replace("def set_head(doc, entry, point):", "def set_head(doc, point):", 1)),
    ("every call passes a number of arguments the function takes", "tidy_ops.py",
     lambda t: t.replace("_region(job.entries, p)", "_region(job.entries)", 1)),
    ("every .NET namespace has its assembly referenced", "tidy_clr.py",
     lambda t: t.replace('    "System.Xml",\n', "", 1)),
    ("every window has a shrink-to-taskbar drawer", "tidy_ui.py",
     lambda t: t.replace("        self.drawer = self.chrome.add_drawer()\n"
                         "        self.theme = ThemeSwitch(self.window, self.cfg,",
                         "        self.theme = ThemeSwitch(self.window, self.cfg,", 1)),
    ("the shrink button is wired", "tidy_ui.py",
     lambda t: t.replace("            button.Click += self._clicked\n", "            pass\n", 1)),
    ("the drawer releases its animations", "tidy_ui.py",
     lambda t: t.replace("            w.BeginAnimation(Window.HeightProperty, None)\n",
                         "            pass\n", 1)),
    ("the changelog has the version", "tidy_core.py",
     lambda t: re.sub(r'__version__ = "[^"]+"', '__version__ = "9.9.9"', t, count=1)),
    ("dark is Revit's own dark, and readable", "tidy_theme.py",
     lambda t: t.replace('    "MutedBrush": "#A4AAB1",', '    "MutedBrush": "#9A9A9E",', 1)),
    ("ribbon names are unique and prefixed RevoBIM",
     COMMAND_FOLDER + "/bundle.yaml",
     lambda t: t.replace("title: RevoBIM Tag Tidy\n", "title: Tag Tidy\n", 1)),
]


def selftest():
    source = HERE
    out("Baseline:")
    baseline = run(source)
    out("")
    if baseline:
        out("The tool does not pass its own check, so the selftest is meaningless.")
        return 1

    labels = set(label for label, _ in RULES)
    untested = sorted(labels - set(label for label, _, _ in BREAKAGES))
    passed = 0
    for label, filename, break_it in BREAKAGES:
        temp = tempfile.mkdtemp(prefix="tidy_check_")
        try:
            copy = os.path.join(temp, os.path.basename(source))
            shutil.copytree(source, copy, ignore=shutil.ignore_patterns("__pycache__"))
            target = os.path.join(copy, *filename.split("/"))
            if not os.path.exists(target):
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
                [sys.executable, "-I", os.path.join(copy, "import_check.py"), "--dir", copy],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=temp)
            report = result.stdout.decode("utf-8", "replace")
            if ("FAIL  " + label) in report:
                passed += 1
                out("caught  " + label)
            else:
                out("MISSED  " + label)
                out(report)
        finally:
            shutil.rmtree(temp, ignore_errors=True)

    out("")
    for label in untested:
        out("NO BREAKAGE  " + label)
    out("{0} of {1} rules caught their own breakage.".format(passed, len(BREAKAGES)))
    return 0 if passed == len(BREAKAGES) and not untested else 1


def main(argv):
    if "--selftest" in argv:
        return selftest()
    root = HERE
    if "--dir" in argv:
        root = argv[argv.index("--dir") + 1]
    out("RevoBIM Tag Tidy bench check")
    out("")
    failures = run(root)
    out("")
    out("{0} rule{1} failed.".format(failures, "" if failures == 1 else "s")
        if failures else "All rules pass.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
