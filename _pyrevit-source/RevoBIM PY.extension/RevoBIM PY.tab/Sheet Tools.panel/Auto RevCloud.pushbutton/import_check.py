# -*- coding: utf-8 -*-
"""Auto RevCloud - bench check.  Runs under plain CPython 3 from this folder:

    python import_check.py             check the shipped tool
    python import_check.py --selftest  break every rule on purpose and prove
                                       each breakage is caught

A blank white pyRevit window means the script died before any of it ran, and
there is no traceback to read.  Every rule below is a way that has actually
happened in this extension, or a house convention that stops it happening.
"""
from __future__ import print_function

import ast
import io
import os
import re
import shutil
import sys
import symtable
import tempfile
import types
import xml.dom.minidom

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL_NAME = u"Auto RevCloud"

# Derived from the folder, not listed. A hardcoded list stops covering a
# module the moment a new one is added, and does it silently: arc_compare and
# arc_diff were written, shipped and never once stub-loaded or cross-checked
# because nobody added them here. The same mistake as the old hardcoded
# LAYOUTS, and the same fix.
FIRST = [u"arc_clr", u"theme", u"arc_core"]
SKIP = [u"import_check", u"bench_logic", u"bench_compare", u"script",
        u"arc_diff_stub"]


def _modules():
    here = os.path.dirname(os.path.abspath(__file__))
    found = sorted(f[:-3] for f in os.listdir(here)
                   if f.endswith(u".py") and f[:-3] not in SKIP)
    ordered = [m for m in FIRST if m in found]
    ordered.extend(m for m in found if m not in ordered)
    return ordered


MODULES = _modules()
# Derived, not listed: a hardcoded list silently stops covering a layout the
# moment a new one is added, which is the opposite of what a bench check is
# for. AutoRevCloud.xaml stays first because the names-agree rule reads the
# main window's header out of LAYOUTS[0].
def _layouts():
    here = os.path.dirname(os.path.abspath(__file__))
    found = sorted(f for f in os.listdir(here)
                   if f.endswith(u".xaml") and f != u"Theme.xaml")
    main = u"AutoRevCloud.xaml"
    if main in found:
        found.remove(main)
        found.insert(0, main)
    return found


LAYOUTS = _layouts()
THEME = u"Theme.xaml"

# ---------------------------------------------------------------------------
# the stub API: every name in the namespace the real API puts it in.  A name
# imported from anywhere else fails here rather than in Revit.
# ---------------------------------------------------------------------------
NAMESPACES = {
    u"System": [u"Action", u"Array", u"Byte", u"Enum", u"Int64", u"Single", u"Int32",
                u"Double", u"String", u"Object", u"Exception", u"Environment"],
    u"System.IO": [u"File", u"MemoryStream", u"StringReader", u"Path",
                   u"Directory"],
    u"System.Xml": [u"XmlReader"],
    u"System.Diagnostics": [u"Process", u"ProcessStartInfo"],
    u"System.Collections.Generic": [u"List", u"Dictionary"],
    u"System.Runtime.InteropServices": [u"Marshal"],
    u"System.Drawing": [u"Bitmap", u"Color", u"Graphics", u"GraphicsUnit",
                        u"Point", u"Rectangle", u"Image"],
    u"System.Drawing.Drawing2D": [u"CompositingQuality", u"InterpolationMode",
                                  u"PixelOffsetMode", u"SmoothingMode"],
    u"System.Drawing.Imaging": [u"ColorMatrix", u"ImageAttributes",
                                u"ImageLockMode", u"PixelFormat", u"ImageFormat"],
    u"System.Windows": [u"Clipboard", u"GridLength", u"GridUnitType", u"Thickness",
                        u"Visibility", u"Window", u"FontWeights",
                        u"HorizontalAlignment", u"VerticalAlignment",
                        u"MessageBox", u"RoutedEventHandler"],
    u"System.Windows.Controls": [u"ColumnDefinition", u"ComboBoxItem", u"Grid",
                                 u"ListBoxItem", u"TextBlock", u"Button",
                                 u"TextBox", u"CheckBox", u"ComboBox",
                                 u"ListBox", u"Border", u"StackPanel",
                                 u"RowDefinition", u"Image", u"ToolTip"],
    u"System.Windows.Controls.Primitives": [u"Thumb", u"ButtonBase",
                                            u"ToggleButton"],
    u"System.Windows.Forms": [u"Screen", u"FolderBrowserDialog",
                              u"DialogResult"],
    u"System.Windows.Input": [u"Key", u"Cursors", u"MouseButton"],
    u"System.Windows.Interop": [u"HwndSource", u"WindowInteropHelper"],
    u"System.Windows.Markup": [u"XamlReader"],
    u"System.Windows.Media": [u"Color", u"SolidColorBrush", u"Brushes",
                              u"VisualTreeHelper"],
    u"System.Windows.Media.Imaging": [u"BitmapCacheOption", u"BitmapImage"],
    u"System.Windows.Threading": [u"DispatcherPriority", u"DispatcherTimer"],
    u"System.Windows.Documents": [u"Run"],
    u"Microsoft.Win32": [u"OpenFileDialog", u"SaveFileDialog"],
    u"Microsoft.VisualBasic": [u"Interaction"],
    u"Autodesk.Revit.DB": [
        u"BuiltInCategory", u"CategoryType", u"ColorDepthType", u"Curve",
        u"ElementMulticategoryFilter", u"RevitLinkInstance", u"StorageType",
        u"RevisionNumberingSequence", u"RevisionVisibility", u"RevisionNumberType",
        u"ElementId", u"ExportPaperFormat", u"FailureProcessingResult",
        u"FailureSeverity", u"FilteredElementCollector", u"IFailuresPreprocessor",
        u"ImageType", u"ImageTypeOptions", u"ImageTypeSource", u"Line",
        u"Revision",
        u"RevisionCloud", u"SubTransaction", u"Transaction", u"TransactionGroup",
        u"ViewSheet", u"ViewType", u"XYZ", u"ZoomType", u"Element", u"View",
        u"Viewport", u"Transform", u"BoundingBoxXYZ", u"Outline",
        u"BuiltInParameter", u"Category", u"TransactionStatus",
        u"RevisionNumberType", u"ElementTransformUtils", u"CurveLoop",
        u"TransformWithBoundary", u"WorksharingUtils", u"ElementCategoryFilter", u"BoundingBoxIntersectsFilter",
    ],
    u"Autodesk.Revit.DB.Architecture": [u"Room"],
    u"Autodesk.Revit.DB.Plumbing": [u"PlumbingUtils", u"Pipe"],
    u"Autodesk.Revit.UI": [u"ExternalEvent", u"IExternalEventHandler",
                           u"TaskDialog", u"UIThemeManager", u"UITheme",
                           u"UIApplication", u"UIDocument", u"PostableCommand",
                           u"RevitCommandId"],
    u"Autodesk.Revit.UI.Selection": [u"ObjectType", u"ISelectionFilter"],
}

# Names a function may reach for that are neither builtins nor module
# globals: pyRevit injects these into script.py only.
PYREVIT_GLOBALS = set([u"__revit__", u"__persistentengine__", u"__title__"])

BANNED_PY = [
    (u"System.Uri", re.compile(u"\\bfrom\\s+System\\s+import\\b[^\\n]*\\bUri\\b|\\bSystem\\.Uri\\b")),
    (u"bare .None", re.compile(u"\\.None\\b")),
]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def read(folder, name):
    with io.open(os.path.join(folder, name), u"r", encoding=u"utf-8") as handle:
        return handle.read()


def py_files(folder):
    return sorted(f for f in os.listdir(folder)
                  if f.endswith(u".py") and f not in (u"import_check.py", u"bench_logic.py"))


def xaml_files(folder):
    return sorted(f for f in os.listdir(folder) if f.endswith(u".xaml"))


class Problems(object):
    def __init__(self):
        self.by_rule = {}

    def add(self, rule, text):
        self.by_rule.setdefault(rule, []).append(text)

    def rules_failed(self):
        return set(self.by_rule.keys())


def parse(folder, name):
    return ast.parse(read(folder, name), filename=name)


def code_text(folder, name):
    """The file with every comment and string literal blanked out, line
    numbers and columns preserved.

    The text rules below are searched against this rather than against the
    raw source.  Searching the raw source means a docstring that *describes*
    a banned construct - "no System.Uri, which moved assemblies in 2025" -
    reports itself as a breach, which is exactly what it did.
    """
    text = read(folder, name)
    lines = text.split(u"\n")
    try:
        import tokenize
        try:
            from StringIO import StringIO           # IronPython 2.7
        except ImportError:
            from io import StringIO                 # CPython 3
        try:
            tokens = list(tokenize.generate_tokens(StringIO(text).readline))
        except Exception:
            return text
        for token in tokens:
            kind, value, start, end = token[0], token[1], token[2], token[3]
            if kind not in (tokenize.STRING, tokenize.COMMENT):
                continue
            srow, scol = start[0] - 1, start[1]
            erow, ecol = end[0] - 1, end[1]
            for row in range(srow, erow + 1):
                if row >= len(lines):
                    break
                line = lines[row]
                first = scol if row == srow else 0
                last = ecol if row == erow else len(line)
                lines[row] = line[:first] + u" " * (last - first) + line[last:]
        return u"\n".join(lines)
    except Exception:
        return text


# ---------------------------------------------------------------------------
# the stub API
# ---------------------------------------------------------------------------

class StrictModule(types.ModuleType):
    """A module that only has the names declared for it."""

    def __getattr__(self, name):
        raise AttributeError(u"'{0}' is not in namespace {1}".format(name, self.__name__))


class Stub(object):
    """Stands in for any .NET class: constructible, callable, subscriptable,
    subclassable, with attributes that are themselves stubs."""

    def __init__(self, *args, **kwargs):
        pass

    def __call__(self, *args, **kwargs):
        return Stub()

    def __getitem__(self, item):
        return Stub

    def __getattr__(self, name):
        if name.startswith(u"__"):
            raise AttributeError(name)
        return Stub()

    def __iadd__(self, other):
        return self

    def __isub__(self, other):
        return self


class StubMeta(type):
    def __getattr__(cls, name):
        if name.startswith(u"__"):
            raise AttributeError(name)
        return Stub()

    def __getitem__(cls, item):
        return cls


def make_stub_class(name):
    return StubMeta(str(name), (Stub,), {})


def install_stubs():
    """Register the strict namespaces in sys.modules.  Returns the names
    added so they can be removed again."""
    added = []
    roots = set()
    for namespace, names in NAMESPACES.items():
        parts = namespace.split(u".")
        for depth in range(1, len(parts) + 1):
            partial = u".".join(parts[:depth])
            if partial in sys.modules and isinstance(sys.modules[partial], StrictModule):
                continue
            module = StrictModule(str(partial))
            sys.modules[partial] = module
            added.append(partial)
            roots.add(parts[0])
            if depth > 1:
                parent = sys.modules[u".".join(parts[:depth - 1])]
                types.ModuleType.__setattr__(parent, str(parts[depth - 1]), module)
        module = sys.modules[namespace]
        for name in names:
            types.ModuleType.__setattr__(module, str(name), make_stub_class(name))
    clr = StrictModule(str(u"clr"))
    types.ModuleType.__setattr__(clr, str(u"AddReference"), lambda name: None)
    sys.modules[u"clr"] = clr
    added.append(u"clr")
    return added


def remove_stubs(added):
    for name in added:
        sys.modules.pop(name, None)


def load_modules(folder, problems):
    """Import every module against the stubs; returns {name: module}."""
    loaded = {}
    added = install_stubs()
    for name in MODULES:
        sys.modules.pop(name, None)
    saved_path = list(sys.path)
    sys.path.insert(0, folder)
    saved_appdata = os.environ.get(u"APPDATA")
    os.environ[u"APPDATA"] = tempfile.mkdtemp(prefix=u"arc_bench_")
    try:
        for name in MODULES:
            try:
                loaded[name] = __import__(name)
            except Exception as exc:
                problems.add(u"stub-load", u"{0}: {1}: {2}".format(
                    name, type(exc).__name__, exc))
    finally:
        sys.path[:] = saved_path
        for name in MODULES:
            sys.modules.pop(name, None)
        remove_stubs(added)
        if saved_appdata is None:
            os.environ.pop(u"APPDATA", None)
        else:
            os.environ[u"APPDATA"] = saved_appdata
    return loaded


# ---------------------------------------------------------------------------
# rules on the Python
# ---------------------------------------------------------------------------

def rule_compile(folder, problems):
    for name in py_files(folder):
        try:
            compile(read(folder, name), name, u"exec")
        except SyntaxError as exc:
            problems.add(u"compile", u"{0}: {1}".format(name, exc))


def rule_ast_bans(folder, problems):
    for name in py_files(folder):
        try:
            tree = parse(folder, name)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr):
                problems.add(u"no-fstrings", u"{0}:{1}".format(name, node.lineno))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == u"print":
                problems.add(u"no-print", u"{0}:{1}".format(name, node.lineno))
            if isinstance(node, ast.Attribute) and node.attr == u"IntegerValue":
                if not _inside_function(tree, node, u"eid_value"):
                    problems.add(u"no-bare-IntegerValue", u"{0}:{1}".format(name, node.lineno))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == u"AddReference" and name != u"arc_clr.py":
                    problems.add(u"clr-only-in-arc_clr", u"{0}:{1}".format(name, node.lineno))

def rule_banned_text(folder, problems):
    """The text bans, scanned against code only.

    Deliberately not inside rule_ast_bans: that skips a file it cannot parse,
    and `.None` is itself a syntax error - which is the whole reason it is
    banned, since IronPython needs getattr(X, 'None') to reach a .NET enum
    member of that name.  Behind the parse guard the rule could never fire.
    """
    for name in py_files(folder):
        text = code_text(folder, name)
        for label, regex in BANNED_PY:
            for match in regex.finditer(text):
                line = text.count(u"\n", 0, match.start()) + 1
                problems.add(u"no-" + label.replace(u" ", u"-"), u"{0}:{1}".format(name, line))


def _inside_function(tree, node, func_name):
    for func in ast.walk(tree):
        if isinstance(func, ast.FunctionDef) and func.name == func_name:
            for child in ast.walk(func):
                if child is node:
                    return True
    return False


def rule_clr_first(folder, problems):
    """No module reaches into System.* / Autodesk.* / Microsoft.* before it
    has imported arc_clr, and arc_clr never references RevitAPI itself."""
    for name in py_files(folder):
        if name == u"arc_clr.py":
            text = read(folder, name)
            if re.search(u"AddReference\\(\\s*u?[\"']RevitAPI", text):
                problems.add(u"clr-first", u"arc_clr.py references RevitAPI - pyRevit loads it already")
            continue
        try:
            tree = parse(folder, name)
        except SyntaxError:
            continue
        clr_line = None
        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == u"arc_clr" and clr_line is None:
                        clr_line = node.lineno
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = node.module if isinstance(node, ast.ImportFrom) else node.names[0].name
                if module and module.split(u".")[0] in (u"System", u"Autodesk", u"Microsoft"):
                    if clr_line is None or node.lineno < clr_line:
                        problems.add(u"clr-first", u"{0}:{1} imports {2} before arc_clr".format(
                            name, node.lineno, module))


def rule_assembly_coverage(folder, problems):
    """Every System.* / Microsoft.* namespace imported anywhere has an
    assembly in arc_clr.ASSEMBLY_FOR, and that assembly is in ASSEMBLIES."""
    try:
        tree = parse(folder, u"arc_clr.py")
    except Exception as exc:
        problems.add(u"assembly-coverage", u"arc_clr.py unreadable: {0}".format(exc))
        return
    assemblies = set()
    assembly_for = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target = node.targets[0].id
            try:
                value = ast.literal_eval(node.value)
            except Exception:
                continue
            if target == u"ASSEMBLIES":
                assemblies = set(value)
            elif target == u"ASSEMBLY_FOR":
                assembly_for = dict(value)
    for name in py_files(folder):
        try:
            tree = parse(folder, name)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(u".")[0]
                if root not in (u"System", u"Microsoft"):
                    continue
                assembly = assembly_for.get(node.module)
                if assembly is None:
                    problems.add(u"assembly-coverage", u"{0}:{1} {2} has no entry in ASSEMBLY_FOR".format(
                        name, node.lineno, node.module))
                elif assembly not in assemblies:
                    problems.add(u"assembly-coverage", u"{0}:{1} {2} needs assembly {3}, not in ASSEMBLIES".format(
                        name, node.lineno, node.module, assembly))


def rule_namespaces(folder, problems):
    """Every .NET name imported, at module level or inside a function, is
    declared for that namespace in the stub tables."""
    for name in py_files(folder):
        try:
            tree = parse(folder, name)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(u".")[0]
                if root not in (u"System", u"Autodesk", u"Microsoft"):
                    continue
                declared = NAMESPACES.get(node.module)
                if declared is None:
                    problems.add(u"namespaces", u"{0}:{1} unknown namespace {2}".format(
                        name, node.lineno, node.module))
                    continue
                for alias in node.names:
                    if alias.name not in declared:
                        problems.add(u"namespaces", u"{0}:{1} {2} is not in {3}".format(
                            name, node.lineno, alias.name, node.module))


def rule_globals(folder, problems, loaded):
    """Every global name a function reaches for exists in its module (after
    loading against the stubs), in builtins, or is a pyRevit-provided name.
    The rule that catches a helper deleted by a block rewrite."""
    import builtins
    builtin_names = set(dir(builtins))
    for name in py_files(folder):
        module_name = name[:-3]
        module = loaded.get(module_name)
        if module is None:
            if module_name == u"script":
                module_names = _script_module_names(folder)
            else:
                continue
        else:
            module_names = set(dir(module))
        try:
            table = symtable.symtable(read(folder, name), name, u"exec")
        except SyntaxError:
            continue
        _walk_symtable(table, name, module_names | builtin_names | PYREVIT_GLOBALS, problems)


def _script_module_names(folder):
    """script.py is never imported (it runs), so its globals come from a
    static read of its top-level assignments, defs and imports."""
    names = set()
    try:
        tree = parse(folder, u"script.py")
    except SyntaxError:
        return names
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add((alias.asname or alias.name).split(u".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name)
    # imports done inside main() are module-visible to the rest of main only;
    # symtable already treats them as local, so nothing more to add
    return names


def _walk_symtable(table, filename, known, problems):
    for child in table.get_children():
        if child.get_type() == u"function":
            for symbol in child.get_symbols():
                if symbol.is_global() and symbol.is_referenced() and not symbol.is_assigned():
                    if symbol.get_name() not in known:
                        problems.add(u"globals", u"{0}: {1}() reaches for unknown global '{2}'".format(
                            filename, child.get_name(), symbol.get_name()))
        _walk_symtable(child, filename, known, problems)


def rule_cross_module(folder, problems, loaded):
    """Every arc_x.name / theme.name / settings_window.name attribute access
    resolves in the loaded module."""
    for name in py_files(folder):
        try:
            tree = parse(folder, name)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                owner = node.value.id
                if owner in loaded and owner != name[:-3]:
                    if not hasattr(loaded[owner], node.attr):
                        problems.add(u"cross-module", u"{0}:{1} {2}.{3} does not exist".format(
                            name, node.lineno, owner, node.attr))


PUMP_CALLS = (u"pump", u"report_progress", u"progress", u"report_row",
              u"Invoke", u"DoEvents")
# TransactionGroup is in the list. It was left out on the grounds that a group
# is not a transaction - true, and irrelevant: pumping the dispatcher while
# one is open dispatches real mouse and keyboard messages into Revit and took
# it down. A group held open across a loop that reports progress is the exact
# shape of that crash.
OPENERS = (u"Transaction", u"SubTransaction", u"TransactionGroup")
CLOSERS = (u"Commit", u"RollBack", u"Assimilate")


def rule_no_pump_in_transaction(folder, problems):
    """No dispatcher pump - or progress call, which pumps - between a
    Start() and its Commit()/RollBack()/Assimilate() within one function.

    Transactions, sub-transactions AND transaction groups. Reporting progress
    is the usual way this happens: the callback looks harmless at the call
    site and pumps three frames down."""
    for name in py_files(folder):
        try:
            tree = parse(folder, name)
        except SyntaxError:
            continue
        for func in ast.walk(tree):
            if not isinstance(func, ast.FunctionDef):
                continue
            tx_names = set()
            events = []
            for node in ast.walk(func):
                if isinstance(node, ast.Assign) and _makes_transaction(node.value):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            tx_names.add(target.id)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    owner = node.func.value
                    if isinstance(owner, ast.Name) and owner.id in tx_names:
                        if node.func.attr == u"Start":
                            events.append((node.lineno, u"open"))
                        elif node.func.attr in CLOSERS:
                            events.append((node.lineno, u"close"))
                    if node.func.attr in PUMP_CALLS:
                        events.append((node.lineno, u"pump"))
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in PUMP_CALLS:
                    events.append((node.lineno, u"pump"))
            events.sort()
            open_now = False
            for line, kind in events:
                if kind == u"open":
                    open_now = True
                elif kind == u"close":
                    open_now = False
                elif kind == u"pump" and open_now:
                    problems.add(u"no-pump-in-transaction", u"{0}:{1} in {2}()".format(
                        name, line, func.name))


def _makes_transaction(node):
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id in OPENERS:
            return True
        for arg in node.args:
            if _makes_transaction(arg):
                return True
    return False


def rule_settings_keys(folder, problems):
    """Every settings key the code asks for is in arc_core.DEFAULTS, and the
    settings window's box names exist in ArcSettings.xaml."""
    try:
        tree = parse(folder, u"arc_core.py")
    except Exception as exc:
        problems.add(u"settings-keys", u"arc_core.py unreadable: {0}".format(exc))
        return
    defaults = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id == u"DEFAULTS":
            # Keys only, straight off the AST. literal_eval on the whole
            # table breaks the moment a default is computed rather than
            # written out - which is what a category list joined with "|" is -
            # and the rule then reports the table as unreadable and stops
            # checking anything.
            try:
                for element in node.value.elts:
                    key = _const(element.elts[0])
                    if key is not None:
                        defaults.add(key)
            except Exception:
                pass
            if not defaults:
                try:
                    defaults = set(k for k, _v in ast.literal_eval(node.value))
                except Exception:
                    pass
    if not defaults:
        problems.add(u"settings-keys", u"arc_core.DEFAULTS not readable")
        return
    getters = (u"as_bool", u"as_int", u"as_float")
    for name in py_files(folder):
        try:
            tree = parse(folder, name)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            key = None
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in getters and len(node.args) >= 2:
                key = _const(node.args[1])
            elif isinstance(func, ast.Name) and func.id in getters and len(node.args) >= 2:
                key = _const(node.args[1])
            elif isinstance(func, ast.Attribute) and func.attr == u"get" and isinstance(func.value, ast.Name) \
                    and func.value.id in (u"settings", u"out") and node.args:
                key = _const(node.args[0])
            if key is not None and key not in defaults:
                problems.add(u"settings-keys", u"{0}:{1} settings key '{2}' is not in DEFAULTS".format(
                    name, node.lineno, key))
    # settings window tables
    try:
        tree = parse(folder, u"settings_window.py")
    except Exception:
        return
    xaml_names = set()
    try:
        xaml_names = _x_names(read(folder, u"ArcSettings.xaml"))
    except Exception:
        pass
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) \
                and node.targets[0].id in (u"NUMBER_BOXES", u"CHECKS"):
            try:
                rows = ast.literal_eval(node.value)
            except Exception:
                continue
            for row in rows:
                box, key = row[0], row[1]
                if box not in xaml_names:
                    problems.add(u"settings-keys", u"settings_window: '{0}' has no x:Name in ArcSettings.xaml".format(box))
                if key not in defaults:
                    problems.add(u"settings-keys", u"settings_window: key '{0}' is not in DEFAULTS".format(key))


def _const(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def rule_names_agree(folder, problems):
    """The folder, bundle.yaml, script __title__, the header text and
    TOOL_NAME all say the same thing - pyRevit names the ribbon item after
    the folder, and a rename that misses one place leaves the old name
    showing somewhere."""
    folder_name = os.path.basename(os.path.abspath(folder))
    expected = folder_name[:-len(u".pushbutton")] if folder_name.endswith(u".pushbutton") else None
    core_name = None
    try:
        for node in parse(folder, u"arc_core.py").body:
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id == u"TOOL_NAME":
                core_name = _const(node.value)
    except Exception:
        pass
    if core_name is None:
        problems.add(u"names-agree", u"arc_core.TOOL_NAME not found")
        return
    if expected is not None and expected != core_name:
        problems.add(u"names-agree", u"folder says '{0}', TOOL_NAME says '{1}'".format(expected, core_name))
    try:
        bundle = read(folder, u"bundle.yaml")
        match = re.search(u"^title:\\s*(.+)$", bundle, re.M)
        if not match or match.group(1).strip().strip(u"\"'") != core_name:
            problems.add(u"names-agree", u"bundle.yaml title does not match TOOL_NAME")
    except Exception:
        problems.add(u"names-agree", u"bundle.yaml unreadable")
    try:
        script = read(folder, u"script.py")
        match = re.search(u"__title__\\s*=\\s*u?[\"'](.+?)[\"']", script)
        if not match or match.group(1) != core_name:
            problems.add(u"names-agree", u"script.py __title__ does not match TOOL_NAME")
    except Exception:
        problems.add(u"names-agree", u"script.py unreadable")
    try:
        layout = read(folder, LAYOUTS[0])
        if u"Text=\"{0}\"".format(core_name) not in layout:
            problems.add(u"names-agree", u"{0} header does not show TOOL_NAME".format(LAYOUTS[0]))
    except Exception:
        problems.add(u"names-agree", u"{0} unreadable".format(LAYOUTS[0]))


# ---------------------------------------------------------------------------
# rules on the XAML
# ---------------------------------------------------------------------------

def rule_xaml_parses(folder, problems):
    for name in xaml_files(folder):
        try:
            xml.dom.minidom.parseString(read(folder, name).encode(u"utf-8"))
        except Exception as exc:
            problems.add(u"xaml-parses", u"{0}: {1}".format(name, exc))


def _x_names(text):
    return set(re.findall(u"x:Name=\"([^\"]+)\"", text))


def _theme_keys(folder):
    text = read(folder, THEME)
    return set(re.findall(u"x:Key=\"([^\"]+)\"", text))


def _theme_style_targets(folder):
    """{style key: TargetType} for every keyed Style in Theme.xaml."""
    text = read(folder, THEME)
    out = {}
    for match in re.finditer(u"<Style\\s+x:Key=\"([^\"]+)\"\\s+TargetType=\"([^\"]+)\"", text):
        out[match.group(1)] = match.group(2)
    return out


def rule_resources(folder, problems):
    """No StaticResource in a layout; every DynamicResource key (in layouts
    and in Theme.xaml itself) exists in Theme.xaml; every Style applied by
    key sits on an element of the style's TargetType."""
    try:
        keys = _theme_keys(folder)
        targets = _theme_style_targets(folder)
    except Exception as exc:
        problems.add(u"resources", u"Theme.xaml unreadable: {0}".format(exc))
        return
    for name in xaml_files(folder):
        text = read(folder, name)
        if name != THEME and u"StaticResource" in text:
            problems.add(u"resources", u"{0} uses StaticResource (Theme.xaml is merged after parsing)".format(name))
        for match in re.finditer(u"DynamicResource\\s+([A-Za-z0-9_]+)", text):
            if match.group(1) not in keys:
                problems.add(u"resources", u"{0}: DynamicResource {1} is not defined in Theme.xaml".format(name, match.group(1)))
        for match in re.finditer(u"<([A-Za-z]+)[^>]*?\\sStyle=\"\\{(?:Dynamic|Static)Resource\\s+([A-Za-z0-9_]+)\\}\"", text):
            element, key = match.group(1), match.group(2)
            target = targets.get(key)
            if target is not None and target != element:
                problems.add(u"resources", u"{0}: <{1}> uses style {2} whose TargetType is {3}".format(
                    name, element, key, target))


def rule_findname(folder, problems):
    """Every literal name handed to FindName / find / self.find has an
    x:Name in a layout, and every FindResource / SetResourceReference key
    exists in Theme.xaml."""
    names = set()
    for layout in LAYOUTS:
        try:
            names |= _x_names(read(folder, layout))
        except Exception:
            pass
    keys = _theme_keys(folder)
    for name in py_files(folder):
        try:
            tree = parse(folder, name)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            func = node.func
            label = func.attr if isinstance(func, ast.Attribute) else (func.id if isinstance(func, ast.Name) else u"")
            if label in (u"FindName", u"find", u"f"):
                key = _const(node.args[0])
                if key is not None and key not in names:
                    problems.add(u"findname", u"{0}:{1} FindName('{2}') has no x:Name".format(name, node.lineno, key))
            if label == u"FindResource":
                key = _const(node.args[0])
                if key is not None and key not in keys:
                    problems.add(u"findname", u"{0}:{1} FindResource('{2}') is not in Theme.xaml".format(name, node.lineno, key))
            if label == u"SetResourceReference" and len(node.args) >= 2:
                key = _const(node.args[1])
                if key is not None and key not in keys:
                    problems.add(u"findname", u"{0}:{1} SetResourceReference to '{2}' not in Theme.xaml".format(name, node.lineno, key))
    # also palette keys passed as colour names in make_row lists
    for name in py_files(folder):
        text = read(folder, name)
        for match in re.finditer(u"u\"([A-Za-z]+Brush)\"", text):
            if match.group(1) not in keys:
                line = text.count(u"\n", 0, match.start()) + 1
                problems.add(u"findname", u"{0}:{1} brush key '{2}' not in Theme.xaml".format(name, line, match.group(1)))


def rule_palette(folder, problems, loaded):
    """theme.DARK and theme.LIGHT each cover every SolidColorBrush key in
    Theme.xaml, and define nothing Theme.xaml lacks."""
    module = loaded.get(u"theme")
    if module is None:
        problems.add(u"palette", u"theme module did not load")
        return
    text = read(folder, THEME)
    brushes = set(re.findall(u"<SolidColorBrush\\s+x:Key=\"([^\"]+)\"", text))
    for label in (u"DARK", u"LIGHT"):
        palette = set(getattr(module, label, {}).keys())
        for key in brushes - palette:
            problems.add(u"palette", u"{0} has no colour for brush {1}".format(label, key))
        for key in palette - brushes:
            problems.add(u"palette", u"{0} defines {1} which Theme.xaml lacks".format(label, key))


# ---------------------------------------------------------------------------
# running
# ---------------------------------------------------------------------------

RULES = [u"compile", u"no-fstrings", u"no-print", u"no-bare-IntegerValue",
         u"no-System.Uri", u"no-bare-.None", u"clr-only-in-arc_clr", u"clr-first",
         u"assembly-coverage", u"namespaces", u"stub-load", u"globals",
         u"cross-module", u"no-pump-in-transaction", u"settings-keys",
         u"names-agree", u"xaml-parses", u"resources", u"findname", u"palette",
         u"easter-egg-wired", u"self-methods", u"method-not-called", u"no-view-collector", u"unset-attributes"]


def rule_easter_egg_wired(folder, problems):
    """The shared RevoBIM easter egg must be wired into every tool.

    Standing wiring for the extension: name the header logo, attach the hook
    after the window loads, and let this rule fail a rebuild that forgets.

    The canonical rule lives in the extension's own
    `lib/revobim/egg/egg_rule.py`. It is imported from there when the tool is
    checked inside a full extension tree, so there is ONE definition of what
    "wired" means and every tool is held to the same one. Checked from a bare
    zip - where lib is not present - the equivalent below runs instead, so the
    rule cannot quietly do nothing just because of where it was run from.
    """
    shared = _shared_egg_rule(folder)
    if shared is not None:
        try:
            for text in shared(folder) or []:
                problems.add(u"easter-egg-wired", text)
            return
        except Exception as exc:
            problems.add(u"easter-egg-wired",
                         u"shared egg_rule failed: {0}".format(exc))
            return

    named = False
    for name in xaml_files(folder):
        text = read(folder, name)
        if u'x:Name="RevoBimLogo"' in text:
            named = True
            break
    if not named:
        problems.add(u"easter-egg-wired",
                     u'no layout carries x:Name="RevoBimLogo" for the egg to hook')

    # Matched as a CALL, not as a substring: "egg_hook.attach" also appears
    # inside "egg_hook.attach_disabled", so a plain `in` test passes a tool
    # whose egg has been renamed out of existence. The selftest caught that.
    attached = False
    call = re.compile(u"\\begg_hook\\s*\\.\\s*attach\\s*\\(")
    for name in py_files(folder):
        if call.search(code_text(folder, name)):
            attached = True
            break
    if not attached:
        problems.add(u"easter-egg-wired",
                     u"nothing calls egg_hook.attach - the egg is not wired in")


def _shared_egg_rule(folder):
    """`rule_easter_egg_wired` out of the extension's lib, or None.

    The tool sits at <extension>/<tab>.tab/<panel>.panel/<tool>.pushbutton, so
    lib is three levels up.
    """
    root = os.path.abspath(os.path.join(folder, u"..", u"..", u"..", u"lib"))
    if not os.path.isdir(os.path.join(root, u"revobim", u"egg")):
        return None
    added = False
    try:
        if root not in sys.path:
            sys.path.insert(0, root)
            added = True
        from revobim.egg import egg_rule
        return getattr(egg_rule, u"rule_easter_egg_wired", None)
    except Exception:
        return None
    finally:
        if added:
            try:
                sys.path.remove(root)
            except Exception:
                pass


def rule_self_methods(folder, problems):
    """Every self.something() call has to resolve to something on the class.

    The gap this fills: the `globals` rule walks module level names, and the
    stub load imports each module - but neither of them opens a class and
    checks that the methods it calls itself still exist. A refactor that
    deletes a helper leaves every call to it intact and silent, and the tool
    dies at run time with AttributeError halfway through building its window.
    That is exactly what happened when the PDF plumbing was stripped out and
    `selected_index` and `move` went with it.

    Attributes assigned anywhere in the class count as defined, because
    `self.find = self.window.FindName` is a method by any useful definition.
    Inherited names are allowed for classes with a base other than object.
    """
    for name in py_files(folder):
        try:
            tree = parse(folder, name)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            inherits = any(not (isinstance(b, ast.Name) and b.id == u"object")
                           for b in node.bases)
            if inherits:
                continue
            defined = set()
            for item in ast.walk(node):
                if isinstance(item, (ast.FunctionDef,)):
                    defined.add(item.name)
                if isinstance(item, ast.Attribute) and isinstance(item.ctx, ast.Store):
                    if isinstance(item.value, ast.Name) and item.value.id == u"self":
                        defined.add(item.attr)
            for item in ast.walk(node):
                if not isinstance(item, ast.Call):
                    continue
                func = item.func
                if not isinstance(func, ast.Attribute):
                    continue
                if not (isinstance(func.value, ast.Name) and func.value.id == u"self"):
                    continue
                if func.attr in defined:
                    continue
                problems.add(u"self-methods", u"{0}:{1} {2}.{3}() is not defined "
                             u"on the class".format(name, item.lineno, node.name,
                                                    func.attr))


def rule_method_not_called(folder, problems):
    """`self.doc` where `self.doc()` was meant.

    A method referenced without its brackets is a perfectly valid expression,
    so nothing complains: the bound method sails into a Revit call, fails
    somewhere inside it, and a guarded caller reports "no links in the
    project". This flags a bare reference to a name the same class defines as
    a method, when it is being passed as an argument rather than called,
    assigned or compared.
    """
    for name in py_files(folder):
        try:
            tree = parse(folder, name)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            methods = set()
            assigned = set()
            for item in ast.walk(node):
                if isinstance(item, ast.FunctionDef):
                    methods.add(item.name)
                if isinstance(item, ast.Attribute) and isinstance(item.ctx, ast.Store):
                    if isinstance(item.value, ast.Name) and item.value.id == u"self":
                        assigned.add(item.attr)
            # A name also assigned as an attribute is a value, not a method.
            methods = methods - assigned
            for item in ast.walk(node):
                if not isinstance(item, ast.Call):
                    continue
                # Only cross-module calls, and only positional arguments.
                # Passing a bound method deliberately is normal - as a
                # callback (`on_close=self.on_close`) or to one of the class's
                # own helpers (`self.move(rows, list, 1, self.fill_both)`) -
                # and flagging those would make the rule noise people learn to
                # ignore. What is never deliberate is handing a bound method
                # positionally to another module's function.
                func = item.func
                if not isinstance(func, ast.Attribute):
                    continue
                if not (isinstance(func.value, ast.Name)
                        and func.value.id not in (u"self", u"cls")):
                    continue
                for argument in item.args:
                    if not isinstance(argument, ast.Attribute):
                        continue
                    if not (isinstance(argument.value, ast.Name)
                            and argument.value.id == u"self"):
                        continue
                    if argument.attr in methods:
                        problems.add(u"method-not-called",
                                     u"{0}:{1} self.{2} passed without () - it is "
                                     u"a method on {3}".format(
                                         name, argument.lineno, argument.attr,
                                         node.name))


def rule_no_view_collector(folder, problems):
    """No `FilteredElementCollector(doc, view.Id)`.

    The two-argument form applies view visibility, and to do that Revit
    generates the view-specific graphics of everything in the view. On a real
    services plan that is tens of thousands of elements' worth of geometry
    built only to answer which of them are visible, and it is what took Revit
    down: the journal ends inside `updateGReps 11026 elements`.

    Scope with a bounding box quick filter and decide visibility per element
    instead. A quick filter reads the element record and nothing else.
    """
    for name in py_files(folder):
        try:
            tree = parse(folder, name)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            called = getattr(func, u"id", None) or getattr(func, u"attr", None)
            if called != u"FilteredElementCollector":
                continue
            if len(node.args) >= 2:
                problems.add(u"no-view-collector",
                             u"{0}:{1} FilteredElementCollector with a view id - "
                             u"it regenerates view graphics for the whole "
                             u"view".format(name, node.lineno))


def rule_unset_attributes(folder, problems):
    """Every `self.x` read has to be set somewhere on the class.

    Not a method - `rule_self_methods` covers those - a VALUE. This is the one
    that let the category picker read `self.palette` when nothing ever stored
    it: the handler threw AttributeError, the wrapper caught it and wrote a
    line into a status bar, and the button looked like it did nothing at all.

    Classes with a base other than object are skipped, since the attribute may
    belong to the base.
    """
    for name in py_files(folder):
        try:
            tree = parse(folder, name)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if any(not (isinstance(b, ast.Name) and b.id == u"object")
                   for b in node.bases):
                continue
            stored = set()
            methods = set()
            read = {}
            for item in ast.walk(node):
                if isinstance(item, ast.FunctionDef):
                    methods.add(item.name)
                if not isinstance(item, ast.Attribute):
                    continue
                if not (isinstance(item.value, ast.Name)
                        and item.value.id == u"self"):
                    continue
                if isinstance(item.ctx, ast.Store):
                    stored.add(item.attr)
                elif item.attr not in read:
                    read[item.attr] = item.lineno
            for attr, line in sorted(read.items()):
                if attr in stored or attr in methods:
                    continue
                problems.add(u"unset-attributes",
                             u"{0}:{1} {2}.{3} is read and never set".format(
                                 name, line, node.name, attr))


def run_checks(folder):
    problems = Problems()
    rule_compile(folder, problems)
    rule_ast_bans(folder, problems)
    rule_banned_text(folder, problems)
    rule_clr_first(folder, problems)
    rule_assembly_coverage(folder, problems)
    rule_namespaces(folder, problems)
    loaded = load_modules(folder, problems)
    rule_globals(folder, problems, loaded)
    rule_cross_module(folder, problems, loaded)
    rule_no_pump_in_transaction(folder, problems)
    rule_settings_keys(folder, problems)
    rule_names_agree(folder, problems)
    rule_xaml_parses(folder, problems)
    rule_resources(folder, problems)
    rule_findname(folder, problems)
    rule_palette(folder, problems, loaded)
    rule_self_methods(folder, problems)
    rule_method_not_called(folder, problems)
    rule_no_view_collector(folder, problems)
    rule_unset_attributes(folder, problems)
    rule_easter_egg_wired(folder, problems)
    return problems


def report(problems):
    if not problems.by_rule:
        print(u"import_check: all {0} rules pass".format(len(RULES)))
        return 0
    for rule in RULES:
        for text in problems.by_rule.get(rule, []):
            print(u"[{0}] {1}".format(rule, text))
    print(u"import_check: {0} rule(s) failed".format(len(problems.by_rule)))
    return 1


# ---------------------------------------------------------------------------
# self test: break each rule in a scratch copy, prove it is caught
# ---------------------------------------------------------------------------

def _edit(folder, name, old, new, count=1):
    path = os.path.join(folder, name)
    text = read(folder, name)
    if old not in text:
        raise RuntimeError(u"selftest: '{0}' not found in {1}".format(old, name))
    text = text.replace(old, new, count)
    with io.open(path, u"w", encoding=u"utf-8") as handle:
        handle.write(text)


def _append(folder, name, extra):
    path = os.path.join(folder, name)
    with io.open(path, u"a", encoding=u"utf-8") as handle:
        handle.write(extra)


BREAKAGES = [
    (u"compile", lambda f: _append(f, u"arc_core.py", u"\ndef broken(:\n    pass\n")),
    (u"no-fstrings", lambda f: _append(f, u"arc_core.py", u"\nBAD = f\"{MM_PER_FT}\"\n")),
    (u"no-print", lambda f: _append(f, u"arc_core.py", u"\nprint(MM_PER_FT)\n")),
    (u"no-bare-IntegerValue", lambda f: _append(f, u"arc_model.py", u"\ndef bad(e):\n    return e.Id.IntegerValue\n")),
    (u"no-System.Uri", lambda f: _append(f, u"arc_ui.py", u"\nfrom System import Uri\n")),
    (u"no-bare-.None", lambda f: _append(f, u"arc_ops.py", u"\ndef bad(x):\n    return x.None\n")),
    (u"clr-only-in-arc_clr", lambda f: _append(f, u"arc_ui.py", u"\nimport clr\nclr.AddReference('PresentationCore')\n")),
    (u"clr-first", lambda f: _edit(f, u"arc_diff.py", u"import arc_clr", u"from System import Int32\nimport arc_clr")),
    (u"assembly-coverage", lambda f: _edit(f, u"arc_clr.py", u"    u\"System.Xml\": u\"System.Xml\",\n", u"")),
    (u"namespaces", lambda f: _edit(f, u"arc_model.py", u"from Autodesk.Revit.DB import (FilteredElementCollector,", u"from Autodesk.Revit.DB import (FilteredElementCollector, PlumbingUtils,")),
    (u"stub-load", lambda f: _edit(f, u"arc_ui.py", u"from System.Windows.Markup import XamlReader", u"from System.Windows import XamlReader")),
    (u"globals", lambda f: _edit(f, u"arc_core.py", u"def arc_label(", u"def arc_label_renamed(")),
    (u"cross-module", lambda f: _edit(f, u"arc_window.py", u"arc_core.parse_categories(", u"arc_core.parse_categorys(")),
    (u"no-pump-in-transaction", lambda f: _edit(f, u"arc_ops.py", u"        outward = _arcs_outward(settings)", u"        arc_ui.pump(None)\n        outward = _arcs_outward(settings)")),
    (u"settings-keys", lambda f: _edit(f, u"arc_ops.py", u'as_bool(settings, u"write_comments")', u'as_bool(settings, u"write_comment")')),
    (u"names-agree", lambda f: _edit(f, u"bundle.yaml", u"title: Auto RevCloud", u"title: Auto RevClouds")),
    (u"xaml-parses", lambda f: _edit(f, u"AutoRevCloud.xaml", u"<!-- ==== the link to compare against ====", u"<!-- ---- the link ----")),
    (u"resources", lambda f: _edit(f, u"ArcPrompt.xaml", u"{DynamicResource ArcGreenButton}", u"{DynamicResource ArcGreenBotton}")),
    (u"findname", lambda f: _edit(f, u"arc_window.py", u"f(u\"ReloadLinksButton\")", u"f(u\"ReloadLinksButon\")")),
    (u"palette", lambda f: _edit(f, u"theme.py", u"    u\"ProgressBg\": u\"#2B2B2E\",\n", u"")),
    (u"unset-attributes", lambda f: _edit(f, u"arc_window.py", u"        self.result_template = None\n        self.palette = palette\n", u"        self.result_template = None\n")),
    (u"no-view-collector", lambda f: _edit(f, u"arc_diff.py", u"collector = FilteredElementCollector(doc).OfCategory(bic)", u"collector = FilteredElementCollector(doc, doc.ActiveView.Id).OfCategory(bic)")),
    (u"method-not-called", lambda f: _edit(f, u"arc_window.py", u"arc_model.sheets(self.doc())", u"arc_model.sheets(self.doc)")),
    (u"self-methods", lambda f: _edit(f, u"arc_window.py", u"    def refresh_ready(self):", u"    def refresh_ready_renamed(self):")),
    (u"easter-egg-wired", lambda f: _edit(f, u"arc_window.py", u"egg_hook.attach(", u"egg_hook.attach_disabled(")),
]


class _Sink(object):
    def write(self, text):
        pass

    def flush(self):
        pass


def selftest():
    failures = []
    base = run_checks(HERE)
    if base.by_rule:
        print(u"selftest: the shipped tool must pass first")
        return report(base)
    for rule, breakage in BREAKAGES:
        scratch = tempfile.mkdtemp(prefix=u"arc_selftest_")
        target = os.path.join(scratch, u"Auto RevCloud.pushbutton")
        shutil.copytree(HERE, target)
        try:
            breakage(target)
            # The stub-load rule imports the modules, so a breakage that
            # injects a print statement prints it. Swallow anything the
            # broken copy writes, or the selftest's own report is polluted.
            saved = sys.stdout
            try:
                sys.stdout = _Sink()
                problems = run_checks(target)
            finally:
                sys.stdout = saved
            if rule in problems.rules_failed():
                print(u"  caught  {0}".format(rule))
            else:
                print(u"  MISSED  {0}  (failed: {1})".format(rule, sorted(problems.rules_failed())))
                failures.append(rule)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
    untested = set(RULES) - set(r for r, _b in BREAKAGES)
    if untested:
        print(u"selftest: rules with no breakage: {0}".format(sorted(untested)))
        failures.extend(sorted(untested))
    if failures:
        print(u"selftest: {0} rule(s) not proven".format(len(failures)))
        return 1
    print(u"selftest: every rule catches its own breakage ({0} rules)".format(len(BREAKAGES)))
    return 0


if __name__ == u"__main__":
    if u"--selftest" in sys.argv:
        sys.exit(selftest())
    sys.exit(report(run_checks(HERE)))
