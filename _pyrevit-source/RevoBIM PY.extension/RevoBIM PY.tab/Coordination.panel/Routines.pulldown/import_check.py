# -*- coding: utf-8 -*-
"""Bench check for RevoBIM PY - Isolate Service Type.

Runs under plain CPython from the pulldown folder:

    python import_check.py
    python import_check.py --selftest

It loads the shipped modules against a stub Revit and .NET API that declares
every name in the namespace the real API puts it in, so a mis-namespaced
import fails here rather than showing up in Revit as a blank white pyRevit
window with no traceback in it.  Sixteen rules on top of that, and --selftest
breaks each one on purpose and confirms the check catches it.  A rule nobody
has tested is a rule that does not work.
"""

import ast
import os
import re
import shutil
import sys
import symtable
import tempfile
import types
import xml.dom.minidom

HERE = os.path.dirname(os.path.abspath(__file__))

SHARED = ["ist_clr.py", "ist_core.py", "ist_theme.py", "ist_ui.py",
          "ist_settings.py", "ist_browse.py", "ist_browser.py",
          "ist_memory.py", "ist_runner.py", "ist_resethide.py",
          "ist_templates.py"]
LOADABLE = ["ist_clr", "ist_theme", "ist_core", "ist_ui", "ist_settings",
            "ist_browse", "ist_browser", "ist_memory", "ist_runner",
            "ist_resethide", "ist_templates"]
THEME_XAML = "IstTheme.xaml"
LAYOUTS = ["IstResults.xaml", "IstSettings.xaml", "IstBrowser.xaml",
           "IstResetHide.xaml", "IstPrompt.xaml"]
COMMAND_FOLDER = "Isolate Service Type.pushbutton"
HIDE_FOLDER = "Hide Service Type.pushbutton"
RESET_FOLDER = "Reset Hide.pushbutton"
SETTINGS_FOLDER = "Isolate Svc Settings.pushbutton"
# folder -> the ist_core constant its ribbon name must match
RIBBON_FOLDERS = [(COMMAND_FOLDER, "RIBBON_NAME"),
                  (HIDE_FOLDER, "HIDE_RIBBON_NAME"),
                  (RESET_FOLDER, "RESET_RIBBON_NAME")]
# Buttons whose command leaves a floating window behind: pyRevit must keep
# their engine, or the window's buttons go dead the moment the command ends.
PERSISTENT_FOLDERS = [HIDE_FOLDER, RESET_FOLDER]

BENCH_FILES = ("import_check.py", "bench_logic.py")

# Which assembly has to be referenced before a namespace can be reached.
# Any one of the listed names is enough.
ASSEMBLY_FOR = [
    ("Autodesk.Revit.DB", ("RevitAPI",)),
    ("Autodesk.Revit.UI", ("RevitAPIUI",)),
    ("System.Windows.Media.Imaging", ("PresentationCore",)),
    ("System.Windows.Media", ("PresentationCore",)),
    ("System.Windows.Input", ("PresentationCore",)),
    ("System.Windows.Markup", ("PresentationFramework", "System.Xaml")),
    ("System.Windows.Controls", ("PresentationFramework",)),
    ("System.Windows.Interop", ("PresentationFramework",)),
    ("System.Windows.Threading", ("WindowsBase",)),
    ("System.Windows", ("PresentationFramework", "WindowsBase")),
    ("System.Collections.Generic", ("System", "System.Core")),
    ("System.Diagnostics", ("System",)),
    ("System.Drawing", ("System.Drawing",)),
    ("System.IO", ("System",)),
    ("System.Text", ("System",)),
    ("System.Xml", ("System.Xml",)),
    # last: plain "System" only matches what nothing above did
    ("System", ("System",)),
]


# ===========================================================================
# stub API
# ===========================================================================

def _module(name, names):
    mod = types.ModuleType(name)
    for key in names:
        setattr(mod, key, type(str(key), (object,), {}))
    return mod


class _Clr(types.ModuleType):
    def __init__(self):
        types.ModuleType.__init__(self, "clr")
        self.requested = []

    def AddReference(self, name):
        self.requested.append(name)


def install_stubs():
    stub_clr = _Clr()
    modules = {"clr": stub_clr}

    packages = ["Autodesk", "Autodesk.Revit", "System"]
    for name in packages:
        modules[name] = types.ModuleType(name)

    modules["Autodesk.Revit.DB"] = _module("Autodesk.Revit.DB", [
        "BuiltInCategory", "BuiltInParameter", "ElementId",
        "ElementMulticategoryFilter", "FilteredElementCollector",
        "StorageType", "TemporaryViewMode", "Transaction", "View",
        "Element", "ElementFilter", "InsulationLiningBase",
        "WorksharingUtils", "XYZ", "CategoryType", "RevitLinkInstance",
        "ParameterFilterElement", "ParameterFilterRuleFactory",
        "ParameterFilterUtilities", "ElementParameterFilter", "FilterRule",
        "SharedParameterElement", "ModelPathUtils",
    ])
    modules["Autodesk.Revit.UI.Selection"] = _module(
        "Autodesk.Revit.UI.Selection", ["ObjectType", "ISelectionFilter"])
    modules["Autodesk.Revit.UI"] = _module("Autodesk.Revit.UI", [
        "TaskDialog", "PostableCommand", "RevitCommandId", "UIApplication",
        "UIDocument", "ExternalEvent", "IExternalEventHandler",
        "ExternalEventRequest",
    ])
    modules["System.Windows.Threading"] = _module(
        "System.Windows.Threading", ["DispatcherTimer", "Dispatcher"])
    for name in ("AppDomain", "TimeSpan", "Action", "Object", "String"):
        setattr(modules["System"], name, type(name, (object,), {}))
    modules["System.IO"] = _module("System.IO", [
        "MemoryStream", "File", "Path", "Directory", "Stream"])
    modules["System.Text"] = _module("System.Text", ["Encoding"])
    modules["System.Diagnostics"] = _module("System.Diagnostics", ["Process"])
    modules["System.Collections.Generic"] = _module(
        "System.Collections.Generic", ["List", "Dictionary", "HashSet"])
    modules["System.Windows"] = _module("System.Windows", [
        "Window", "FrameworkElement", "Thickness", "Visibility",
        "FontWeights", "MessageBox", "ResourceDictionary",
        "VerticalAlignment", "SystemParameters", "GridLength",
        "TextTrimming", "WindowState", "HorizontalAlignment", "TextWrapping"])
    modules["System.Windows.Controls"] = _module("System.Windows.Controls", [
        "CheckBox", "ComboBox", "TextBox", "Button", "StackPanel", "ListBox",
        "TextBlock", "RadioButton", "Control", "TreeView", "TreeViewItem",
        "Orientation", "Grid", "ColumnDefinition", "ScrollViewer"])
    modules["System.Windows.Input"] = _module(
        "System.Windows.Input", ["Mouse", "Cursors", "Key"])
    modules["System.Windows.Markup"] = _module(
        "System.Windows.Markup", ["XamlReader"])
    modules["System.Windows.Media"] = _module("System.Windows.Media", [
        "BrushConverter", "SolidColorBrush", "Colors", "Brushes"])
    modules["System.Windows.Media.Imaging"] = _module(
        "System.Windows.Media.Imaging", ["BitmapImage", "BitmapCacheOption"])
    modules["System.Windows.Interop"] = _module(
        "System.Windows.Interop", ["WindowInteropHelper"])

    saved = {}
    for name, mod in modules.items():
        saved[name] = sys.modules.get(name)
        sys.modules[name] = mod
    # make the dotted names reachable as attributes too
    sys.modules["Autodesk"].Revit = sys.modules["Autodesk.Revit"]
    sys.modules["Autodesk.Revit"].DB = sys.modules["Autodesk.Revit.DB"]
    sys.modules["Autodesk.Revit"].UI = sys.modules["Autodesk.Revit.UI"]
    return stub_clr, saved


def remove_stubs(saved):
    for name, mod in saved.items():
        if mod is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = mod


# ===========================================================================
# helpers
# ===========================================================================

def read(path):
    handle = open(path, "rb")
    try:
        return handle.read().decode("utf-8")
    finally:
        handle.close()


def code_only(text):
    """The file with every string literal and comment blanked out, line
    numbers and columns preserved.  A rule that greps raw text fires on its
    own documentation - the docstring of eid_value says ".IntegerValue" and
    ist_ui's says "System.Uri"."""
    import io as _io
    import tokenize
    grid = [list(line) for line in text.splitlines()]
    try:
        tokens = list(tokenize.generate_tokens(_io.StringIO(text).readline))
    except Exception:
        return text
    for token in tokens:
        if token.type not in (tokenize.STRING, tokenize.COMMENT):
            continue
        (srow, scol), (erow, ecol) = token.start, token.end
        for row in range(srow, erow + 1):
            if row - 1 >= len(grid):
                break
            chars = grid[row - 1]
            start = scol if row == srow else 0
            stop = ecol if row == erow else len(chars)
            for column in range(start, min(stop, len(chars))):
                chars[column] = " "
    return "\n".join("".join(row) for row in grid)


def python_files(root):
    out = []
    for folder, _dirs, files in os.walk(root):
        for name in files:
            if name.endswith(".py") and name not in BENCH_FILES:
                out.append(os.path.join(folder, name))
    return sorted(out)


def xaml_files(root):
    out = []
    for folder, _dirs, files in os.walk(root):
        for name in files:
            if name.endswith(".xaml"):
                out.append(os.path.join(folder, name))
    return sorted(out)


def theme_keys(root):
    """Every x:Key in IstTheme.xaml, and the TargetType of each keyed style."""
    text = read(os.path.join(root, THEME_XAML))
    doc = xml.dom.minidom.parseString(text.encode("utf-8"))
    keys = set()
    brushes = set()
    style_targets = {}
    for node in doc.getElementsByTagName("*"):
        key = node.getAttribute("x:Key")
        if not key:
            continue
        keys.add(key)
        tag = node.tagName.split(":")[-1]
        if tag == "SolidColorBrush":
            brushes.add(key)
        if tag == "Style":
            target = node.getAttribute("TargetType")
            match = re.search(r"x:Type\s+([A-Za-z]+)", target or "")
            style_targets[key] = match.group(1) if match else (target or "")
    return keys, brushes, style_targets


def xnames(root):
    out = set()
    for path in xaml_files(root):
        for name in re.findall(r'x:Name\s*=\s*"([^"]+)"', read(path)):
            out.add(name)
    return out


def top_level_imports(tree):
    """(module_name, line) for every import at module level, including inside
    a module-level try block.  Imports inside a function are deferred until it
    is called, so they cannot break module load."""
    out = []

    def walk(body):
        for node in body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    out.append((alias.name, node.lineno))
            elif isinstance(node, ast.ImportFrom):
                out.append((node.module or "", node.lineno))
            elif isinstance(node, (ast.Try, ast.If)):
                walk(node.body)
                for handler in getattr(node, "handlers", []):
                    walk(handler.body)
                walk(getattr(node, "orelse", []) or [])
                walk(getattr(node, "finalbody", []) or [])
    walk(tree.body)
    return out


# ===========================================================================
# rules
# ===========================================================================

def rule_xaml_xml(root, fail):
    for path in xaml_files(root):
        try:
            xml.dom.minidom.parseString(read(path).encode("utf-8"))
        except Exception as err:
            fail("xaml_xml", "{0}: {1}".format(os.path.basename(path), err))


def rule_clr_first(root, fail):
    for path in python_files(root):
        name = os.path.basename(path)
        if name == "ist_clr.py":
            continue
        try:
            tree = ast.parse(read(path))
        except SyntaxError as err:
            fail("clr_first", "{0}: will not parse: {1}".format(name, err))
            continue
        imports = top_level_imports(tree)
        clr_line = None
        dotnet_line = None
        for module_name, line in imports:
            if module_name in ("ist_clr",) and clr_line is None:
                clr_line = line
            if (module_name.startswith("System") or
                    module_name.startswith("Autodesk")):
                if dotnet_line is None:
                    dotnet_line = line
        if dotnet_line is None:
            continue
        if clr_line is None:
            fail("clr_first",
                 "{0} reaches into a .NET namespace and never imports "
                 "ist_clr".format(name))
        elif clr_line > dotnet_line:
            fail("clr_first",
                 "{0} imports ist_clr at line {1}, after a .NET namespace at "
                 "line {2}".format(name, clr_line, dotnet_line))


def rule_no_static_resource(root, fail):
    for path in xaml_files(root):
        if "StaticResource" in read(path):
            fail("no_static_resource",
                 "{0} uses StaticResource".format(os.path.basename(path)))


def rule_dynamic_key_exists(root, fail):
    keys, _brushes, _targets = theme_keys(root)
    for path in xaml_files(root):
        if os.path.basename(path) == THEME_XAML:
            local = keys
        else:
            local = keys
        for key in re.findall(r"\{DynamicResource\s+([A-Za-z0-9_]+)\s*\}",
                              read(path)):
            if key not in local:
                fail("dynamic_key_exists",
                     "{0} asks for {1}, which {2} does not define".format(
                         os.path.basename(path), key, THEME_XAML))


def rule_style_target_type(root, fail):
    _keys, _brushes, targets = theme_keys(root)
    pattern = re.compile(
        r"<\s*([A-Za-z]+)\b[^>]*?Style\s*=\s*\"\{DynamicResource\s+"
        r"([A-Za-z0-9_]+)\s*\}\"", re.S)
    for path in xaml_files(root):
        for tag, key in pattern.findall(read(path)):
            target = targets.get(key)
            if target and target != tag:
                fail("style_target_type",
                     "{0}: <{1}> carries style {2}, whose TargetType is "
                     "{3}".format(os.path.basename(path), tag, key, target))


def _findname_literals(tree):
    """String literals handed to FindName, directly or through an alias -
    the code aliases it as self.find = self.window.FindName."""
    aliases = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Attribute):
            if node.value.attr == "FindName":
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        aliases.add(target.id)
                    elif isinstance(target, ast.Attribute):
                        aliases.add(target.attr)
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        name = None
        if isinstance(func, ast.Attribute):
            name = func.attr
        elif isinstance(func, ast.Name):
            name = func.id
        if name != "FindName" and name not in aliases:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            out.append((first.value, node.lineno))
    return out


def rule_findname_xname(root, fail):
    declared = xnames(root)
    for path in python_files(root):
        try:
            tree = ast.parse(read(path))
        except SyntaxError:
            continue
        for name, line in _findname_literals(tree):
            if name not in declared:
                fail("findname_xname",
                     "{0} line {1}: FindName(\"{2}\") has no x:Name".format(
                         os.path.basename(path), line, name))


def rule_no_fstring(root, fail):
    for path in python_files(root):
        try:
            tree = ast.parse(read(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr):
                fail("no_fstring",
                     "{0} line {1}: f-string, which IronPython 2.7 will not "
                     "parse".format(os.path.basename(path), node.lineno))


def rule_no_print(root, fail):
    for path in python_files(root):
        try:
            tree = ast.parse(read(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                    and node.func.id == "print":
                fail("no_print", "{0} line {1}: print statement".format(
                    os.path.basename(path), node.lineno))


def rule_no_integervalue(root, fail):
    for path in python_files(root):
        text = code_only(read(path))
        guarded = os.path.basename(path) == "ist_core.py"
        for number, line in enumerate(text.splitlines(), start=1):
            if ".IntegerValue" not in line:
                continue
            if guarded and "element_id.IntegerValue" in line:
                continue  # the one guarded fallback inside eid_value
            fail("no_integervalue",
                 "{0} line {1}: bare .IntegerValue, removed in Revit "
                 "2026".format(os.path.basename(path), number))


def rule_no_system_uri(root, fail):
    for path in python_files(root):
        text = code_only(read(path))
        if re.search(r"from\s+System\s+import[^\n]*\bUri\b", text) or \
                re.search(r"\bSystem\.Uri\b", text):
            fail("no_system_uri",
                 "{0} uses System.Uri, which moved assemblies and throws on "
                 "2025+".format(os.path.basename(path)))


def rule_assembly_for_namespace(root, fail):
    clr_text = read(os.path.join(root, "ist_clr.py"))
    requested = set(re.findall(r'u?"([A-Za-z0-9_.]+)"', clr_text))
    for path in python_files(root):
        try:
            tree = ast.parse(read(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            module_name = None
            if isinstance(node, ast.ImportFrom):
                module_name = node.module or ""
            elif isinstance(node, ast.Import):
                module_name = node.names[0].name
            if not module_name:
                continue
            if not (module_name.startswith("System") or
                    module_name.startswith("Autodesk")):
                continue
            for prefix, assemblies in ASSEMBLY_FOR:
                if module_name == prefix or module_name.startswith(prefix + "."):
                    if not [a for a in assemblies if a in requested]:
                        fail("assembly_for_namespace",
                             "{0} imports {1} but ist_clr references none of "
                             "{2}".format(os.path.basename(path), module_name,
                                          ", ".join(assemblies)))
                    break
            else:
                fail("assembly_for_namespace",
                     "{0} imports {1}, which no ASSEMBLY_FOR entry "
                     "covers".format(os.path.basename(path), module_name))


def _palette_keys(text, name):
    """The keys of one palette dict, on its own - reading the whole file at
    once means a key deleted from DARK is still found in LIGHT and the rule
    quietly passes."""
    match = re.search(r"^" + name + r"\s*=\s*\{(.*?)^\}", text, re.M | re.S)
    if not match:
        return set()
    return set(re.findall(r'u"([A-Za-z0-9_]+)":\s*u"#', match.group(1)))


def rule_palette_brush_coverage(root, fail):
    _keys, brushes, _targets = theme_keys(root)
    text = read(os.path.join(root, "ist_theme.py"))
    dark = _palette_keys(text, "DARK")
    light = _palette_keys(text, "LIGHT")
    for key in sorted(dark - brushes):
        fail("palette_brush_coverage",
             "palette key {0} has no brush in {1}".format(key, THEME_XAML))
    for key in sorted(brushes - dark):
        fail("palette_brush_coverage",
             "{0} defines brush {1}, which the dark palette does not "
             "set".format(THEME_XAML, key))
    for key in sorted(dark ^ light):
        fail("palette_brush_coverage",
             "{0} is in one palette but not the other".format(key))


def rule_setresourcereference_key(root, fail):
    keys, _brushes, _targets = theme_keys(root)
    for path in python_files(root):
        for key in re.findall(
                r"SetResourceReference\([^)]*?u?\"([A-Za-z0-9_]+)\"\s*\)",
                read(path), re.S):
            if key not in keys:
                fail("setresourcereference_key",
                     "{0}: SetResourceReference to {1}, which {2} does not "
                     "define".format(os.path.basename(path), key, THEME_XAML))


def rule_symtable_globals(root, fail):
    for path in python_files(root):
        text = read(path)
        name = os.path.basename(path)
        try:
            table = symtable.symtable(text, name, "exec")
            tree = ast.parse(text)
        except SyntaxError:
            continue
        module_names = set(table.get_identifiers())
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    module_names.add((alias.asname or alias.name).split(".")[0])
        builtins = set(dir(__builtins__)) if not isinstance(__builtins__, dict) \
            else set(__builtins__.keys())
        builtins |= set(["unicode", "basestring", "xrange", "long", "reduce",
                         "__revit__", "__file__", "__name__"])

        def walk(sym_table):
            for child in sym_table.get_children():
                if child.get_type() == "function":
                    for symbol in child.get_symbols():
                        if symbol.is_global() and \
                                symbol.get_name() not in module_names and \
                                symbol.get_name() not in builtins:
                            fail("symtable_globals",
                                 "{0}: {1}() reaches for {2}, which the module "
                                 "does not define".format(
                                     name, child.get_name(), symbol.get_name()))
                walk(child)
        walk(table)


def rule_tool_names(root, fail):
    """Every command button's ribbon name has to agree in three places, or the
    keyboard shortcut binds to a name that is not what the button is called."""
    core = read(os.path.join(root, "ist_core.py"))
    for folder, constant in RIBBON_FOLDERS:
        match = re.search(constant + r'\s*=\s*u"([^"]+)"', core)
        ribbon = match.group(1) if match else ""
        if not os.path.isdir(os.path.join(root, folder)):
            fail("tool_names", "no folder called {0}".format(folder))
            continue
        bundle = read(os.path.join(root, folder, "bundle.yaml"))
        title = ""
        for line in bundle.splitlines():
            if line.startswith("title:"):
                title = line.split(":", 1)[1].strip()
        script = read(os.path.join(root, folder, "script.py"))
        match = re.search(r'__title__\s*=\s*"([^"]+)"', script)
        dunder = match.group(1) if match else ""
        if not (ribbon == title == dunder) or not ribbon:
            fail("tool_names",
                 "{0}: the ribbon name disagrees with itself: {1}={2!r}, "
                 "bundle title={3!r}, __title__={4!r}".format(
                     folder, constant, ribbon, title, dunder))
        if "\n" in title:
            fail("tool_names", "the button title must be one line")
    names = set()
    for folder, _constant in RIBBON_FOLDERS:
        names.add(folder)
    if len(names) != len(RIBBON_FOLDERS):
        fail("tool_names", "two command buttons share a folder name")


def rule_modules_load(root, fail):
    stub_clr, saved = install_stubs()
    added = root not in sys.path
    if added:
        sys.path.insert(0, root)
    dropped = {}
    for name in LOADABLE:
        dropped[name] = sys.modules.pop(name, None)
    try:
        for name in LOADABLE:
            try:
                __import__(name)
            except Exception as err:
                fail("modules_load", "{0}: {1}: {2}".format(
                    name, type(err).__name__, err))
    finally:
        for name in LOADABLE:
            sys.modules.pop(name, None)
            if dropped.get(name) is not None:
                sys.modules[name] = dropped[name]
        if added and root in sys.path:
            sys.path.remove(root)
        remove_stubs(saved)


def rule_import_names(root, fail):
    """Imports inside functions do not run at load, so modules_load never sees
    them - a mis-namespaced name there only fails when that button is pressed.
    Every `from X import a` anywhere in a shipped file is checked against the
    stub of X, which declares each name where the real API puts it."""
    stub_clr, saved = install_stubs()
    try:
        for path in python_files(root):
            try:
                tree = ast.parse(read(path))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom) or not node.module:
                    continue
                if not (node.module.startswith("System") or
                        node.module.startswith("Autodesk")):
                    continue
                module = sys.modules.get(node.module)
                if module is None:
                    fail("import_names",
                         "{0} line {1}: imports from {2}, which the stub API "
                         "does not have".format(os.path.basename(path),
                                                node.lineno, node.module))
                    continue
                for alias in node.names:
                    if not hasattr(module, alias.name):
                        fail("import_names",
                             "{0} line {1}: {2} is not in {3}".format(
                                 os.path.basename(path), node.lineno,
                                 alias.name, node.module))
    finally:
        remove_stubs(saved)


ENUM_PROPERTIES = ("VerticalAlignment", "HorizontalAlignment", "TextTrimming",
                   "TextWrapping", "Visibility", "Orientation", "WindowState",
                   "FontWeight", "ResizeMode", "WindowStartupLocation")


def rule_enum_assign(root, fail):
    """A WPF enum property given a bare number, or a module pulled in with
    __import__.  IronPython does not turn 1 into VerticalAlignment.Center -
    it throws, inside an event handler, where nobody sees it."""
    for path in python_files(root):
        name = os.path.basename(path)
        try:
            tree = ast.parse(read(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Attribute) and \
                            target.attr in ENUM_PROPERTIES and \
                            isinstance(node.value, ast.Constant) and \
                            isinstance(node.value.value, (int, float)):
                        fail("enum_assign",
                             "{0} line {1}: .{2} = {3} - use the enum".format(
                                 name, node.lineno, target.attr,
                                 node.value.value))
            if isinstance(node, ast.Call) and \
                    isinstance(node.func, ast.Name) and \
                    node.func.id == "__import__":
                fail("enum_assign", "{0} line {1}: __import__ - import it "
                     "properly so rule 17 can check it".format(
                         name, node.lineno))


def rule_persistent_engine(root, fail):
    """A button that leaves a floating window must keep its engine."""
    for folder in PERSISTENT_FOLDERS:
        path = os.path.join(root, folder, "script.py")
        if not os.path.isfile(path):
            fail("persistent_engine", "{0} has no script.py".format(folder))
            continue
        tree = ast.parse(read(path))
        found = False
        for node in tree.body:
            if isinstance(node, ast.Assign) and \
                    [t for t in node.targets
                     if isinstance(t, ast.Name) and
                     t.id == "__persistentengine__"] and \
                    isinstance(node.value, ast.Constant) and \
                    node.value.value is True:
                found = True
        if not found:
            fail("persistent_engine",
                 "{0}: no __persistentengine__ = True at module level - the "
                 "Reset Hide window would go dead".format(folder))


RULES = [
    ("xaml_xml", rule_xaml_xml),
    ("clr_first", rule_clr_first),
    ("no_static_resource", rule_no_static_resource),
    ("dynamic_key_exists", rule_dynamic_key_exists),
    ("style_target_type", rule_style_target_type),
    ("findname_xname", rule_findname_xname),
    ("no_fstring", rule_no_fstring),
    ("no_print", rule_no_print),
    ("no_integervalue", rule_no_integervalue),
    ("no_system_uri", rule_no_system_uri),
    ("assembly_for_namespace", rule_assembly_for_namespace),
    ("palette_brush_coverage", rule_palette_brush_coverage),
    ("setresourcereference_key", rule_setresourcereference_key),
    ("symtable_globals", rule_symtable_globals),
    ("tool_names", rule_tool_names),
    ("modules_load", rule_modules_load),
    ("import_names", rule_import_names),
    ("enum_assign", rule_enum_assign),
    ("persistent_engine", rule_persistent_engine),
]


def run(root):
    failures = []

    def fail(rule_id, message):
        failures.append((rule_id, message))

    for _rule_id, function in RULES:
        function(root, fail)
    return failures


# ===========================================================================
# self test
# ===========================================================================

def _copy(root):
    folder = tempfile.mkdtemp(prefix="ist_check_")
    target = os.path.join(folder, "pulldown")
    shutil.copytree(root, target)
    return folder, target


def _patch(path, old, new):
    text = read(path)
    if old not in text:
        raise AssertionError("selftest could not find {0!r} in {1}".format(
            old[:40], path))
    handle = open(path, "wb")
    try:
        handle.write(text.replace(old, new, 1).encode("utf-8"))
    finally:
        handle.close()


def _break_xaml_xml(root):
    _patch(os.path.join(root, "IstResults.xaml"),
           "<!-- ============ header ============ -->",
           "<!-- ------------ header ------------ -->")


def _break_clr_first(root):
    _patch(os.path.join(root, "ist_core.py"),
           "import ist_clr  # noqa: F401  - assemblies first, always",
           "pass  # ist_clr removed")


def _break_static_resource(root):
    _patch(os.path.join(root, "IstResults.xaml"),
           '{DynamicResource IstList}', '{StaticResource IstList}')


def _break_dynamic_key(root):
    _patch(os.path.join(root, "IstResults.xaml"),
           '{DynamicResource IstList}', '{DynamicResource NoSuchKey}')


def _break_style_target(root):
    _patch(os.path.join(root, "IstResults.xaml"),
           'Style="{DynamicResource IstList}"',
           'Style="{DynamicResource IstButton}"')


def _break_findname(root):
    _patch(os.path.join(root, "ist_settings.py"),
           'self.find(u"ApplyButton")', 'self.find(u"ApplyButtonn")')


def _break_fstring(root):
    _patch(os.path.join(root, "ist_theme.py"),
           'def palette(name):',
           'def palette(name):\n    _ = f"{name}"')


def _break_print(root):
    _patch(os.path.join(root, "ist_theme.py"),
           'def palette(name):',
           'def palette(name):\n    print(name)')


def _break_integervalue(root):
    _patch(os.path.join(root, "ist_ui.py"),
           "def load_image(path):",
           "def load_image(path):\n    _ = path.Id.IntegerValue")


def _break_system_uri(root):
    _patch(os.path.join(root, "ist_ui.py"),
           "from System.IO import MemoryStream, File",
           "from System.IO import MemoryStream, File\nfrom System import Uri")


def _break_assembly_for(root):
    _patch(os.path.join(root, "ist_clr.py"), 'u"PresentationCore",', "")


def _break_palette(root):
    _patch(os.path.join(root, "ist_theme.py"),
           'u"HoverBrush": u"#33333A",', "")


def _break_setresourcereference(root):
    _patch(os.path.join(root, "ist_settings.py"),
           'FrameworkElement.StyleProperty, u"IstCheck")',
           'FrameworkElement.StyleProperty, u"IstCheque")')


def _break_symtable(root):
    _patch(os.path.join(root, "ist_theme.py"),
           "def palette(name):",
           "def palette(name):\n    _ = MISSING_TABLE")


def _break_tool_names(root):
    _patch(os.path.join(root, COMMAND_FOLDER, "bundle.yaml"),
           "title: RevoBIM Isolate Service Type",
           "title: Isolate Service Type")


def _break_modules_load(root):
    _patch(os.path.join(root, "ist_core.py"),
           "from Autodesk.Revit.DB import (",
           "from Autodesk.Revit.DB import (TaskDialog,")


def _break_import_names(root):
    # Inside a function, so modules_load cannot see it - only rule 17 can.
    _patch(os.path.join(root, "ist_core.py"),
           "    from Autodesk.Revit.DB import ParameterFilterRuleFactory",
           "    from Autodesk.Revit.DB import ParameterFilterRuleFactory, "
           "TreeViewItem")


def _break_enum_assign(root):
    _patch(os.path.join(root, "ist_resethide.py"),
           "text.VerticalAlignment = VerticalAlignment.Center",
           "text.VerticalAlignment = 1")


def _break_persistent_engine(root):
    _patch(os.path.join(root, RESET_FOLDER, "script.py"),
           "__persistentengine__ = True", "__persistentengine__ = False")


BREAKS = [
    ("xaml_xml", _break_xaml_xml),
    ("clr_first", _break_clr_first),
    ("no_static_resource", _break_static_resource),
    ("dynamic_key_exists", _break_dynamic_key),
    ("style_target_type", _break_style_target),
    ("findname_xname", _break_findname),
    ("no_fstring", _break_fstring),
    ("no_print", _break_print),
    ("no_integervalue", _break_integervalue),
    ("no_system_uri", _break_system_uri),
    ("assembly_for_namespace", _break_assembly_for),
    ("palette_brush_coverage", _break_palette),
    ("setresourcereference_key", _break_setresourcereference),
    ("symtable_globals", _break_symtable),
    ("tool_names", _break_tool_names),
    ("modules_load", _break_modules_load),
    ("import_names", _break_import_names),
    ("enum_assign", _break_enum_assign),
    ("persistent_engine", _break_persistent_engine),
]


def selftest():
    bad = 0
    for rule_id, breaker in BREAKS:
        folder, target = _copy(HERE)
        try:
            breaker(target)
            caught = [f for f in run(target) if f[0] == rule_id]
            if caught:
                sys.stdout.write("  caught  {0}\n".format(rule_id))
            else:
                bad += 1
                sys.stdout.write("  MISSED  {0}\n".format(rule_id))
        finally:
            shutil.rmtree(folder, ignore_errors=True)
    sys.stdout.write("{0} of {1} rules caught their own breakage\n".format(
        len(BREAKS) - bad, len(BREAKS)))
    return 0 if bad == 0 else 1


def main():
    if "--selftest" in sys.argv:
        sys.stdout.write("selftest: breaking each rule on purpose\n")
        return selftest()
    failures = run(HERE)
    if failures:
        for rule_id, message in failures:
            sys.stdout.write("FAIL [{0}] {1}\n".format(rule_id, message))
        sys.stdout.write("{0} problem(s)\n".format(len(failures)))
        return 1
    sys.stdout.write("import_check: {0} rules, all clear\n".format(len(RULES)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
