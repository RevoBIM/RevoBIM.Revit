# -*- coding: utf-8 -*-
"""Model Cleanup bench check. Run under plain CPython from this folder:

    python import_check.py              run every rule
    python import_check.py --selftest   break each rule on purpose and
                                        confirm the rule catches it

Every rule reads code, never prose: strings and comments are stripped
before any text rule looks at a file.
"""
from __future__ import print_function

import ast
import builtins
import importlib.util
import io
import os
import re
import shutil
import symtable
import sys
import tempfile
import tokenize
import types
import xml.dom.minidom

TOOL_DIR = os.path.dirname(os.path.abspath(__file__))
PREFIX = u"mcu_"
CLR_MODULE = u"mcu_clr"
LAYOUTS = [u"ModelCleanup.xaml", u"McuSettings.xaml", u"McuPrompt.xaml"]
HEADER_WINDOWS = [u"ModelCleanup.xaml", u"McuSettings.xaml"]
X = u"{http://schemas.microsoft.com/winfx/2006/xaml}"

# namespace -> assembly that must be referenced before it can be imported
ASSEMBLY_FOR = {
    u"System": u"System",
    u"System.IO": u"System",
    u"System.Xml": u"System.Xml",
    u"System.Data": u"System.Data",
    u"System.Collections.Generic": u"System.Core",
    u"System.Windows": u"PresentationFramework",
    u"System.Windows.Markup": u"PresentationFramework",
    u"System.Windows.Controls": u"PresentationFramework",
    u"System.Windows.Interop": u"PresentationFramework",
    u"System.Windows.Input": u"PresentationCore",
    u"System.Windows.Media": u"PresentationCore",
    u"System.Windows.Media.Imaging": u"PresentationCore",
    u"System.Windows.Threading": u"WindowsBase",
    u"System.Windows.Forms": u"System.Windows.Forms",
    u"System.Windows.Shapes": u"PresentationFramework",
    u"Microsoft.Win32": u"PresentationFramework",
    u"System.Text": u"System",
    u"System.Net": u"System.Net.Requests",
    u"System.Net.Sockets": u"System.Net.Sockets",
    u"System.Diagnostics": u"System.Diagnostics.Process",
    u"System.Security.Cryptography": u"System.Security",
    u"Autodesk.Revit.DB": None,          # pyRevit already has RevitAPI
    u"Autodesk.Revit.UI": None,
    u"Autodesk.Revit.UI.Events": None,
}

# every name declared in the namespace the real API puts it in
NAMESPACES = {
    u"System": u"Action EventHandler TimeSpan Int64 Exception Array Byte Convert Func AppDomain Double",
    u"System.Text": u"Encoding",
    u"System.Net": (u"WebRequest HttpWebRequest WebException ServicePointManager "
                    u"SecurityProtocolType IPAddress"),
    u"System.Net.Sockets": u"TcpListener TcpClient SelectMode Socket",
    u"System.Diagnostics": u"Process ProcessStartInfo",
    u"System.Security.Cryptography": u"ProtectedData DataProtectionScope",
    u"System.IO": u"StringReader StreamReader MemoryStream File Path",
    u"System.Xml": u"XmlReader",
    u"System.Data": u"DataTable DataView",
    u"System.Collections.Generic": u"List HashSet Dictionary",
    u"System.Windows": (u"Window SystemParameters PresentationSource Visibility WindowState "
                        u"Thickness HorizontalAlignment VerticalAlignment "
                        u"TextWrapping TextAlignment FrameworkElement GridLength "
                        u"FontWeights SizeToContent WindowStartupLocation CornerRadius Point"),
    u"System.Windows.Markup": u"XamlReader",
    u"System.Windows.Controls": (u"Button TextBlock TextBox Grid ColumnDefinition "
                                 u"RowDefinition Control Border CheckBox "
                                 u"ListBoxItem ComboBox DataGrid StackPanel Orientation RadioButton "
                                 u"TabControl TabItem"),
    u"System.Windows.Input": u"Key Keyboard Cursors ModifierKeys",
    u"System.Windows.Media": u"SolidColorBrush ColorConverter Color Brushes Geometry",
    u"System.Windows.Media.Imaging": u"BitmapImage BitmapCacheOption",
    u"System.Windows.Threading": u"DispatcherPriority DispatcherTimer Dispatcher",
    u"System.Windows.Interop": u"WindowInteropHelper",
    u"System.Windows.Forms": u"Screen",
    u"System.Windows.Shapes": u"Path Shape Ellipse Rectangle",
    u"Microsoft.Win32": u"SaveFileDialog OpenFileDialog",
    u"Autodesk.Revit.DB": (
        u"FilteredElementCollector ElementId View ViewSheet ViewSchedule "
        u"Viewport ScheduleSheetInstance ElementType Material "
        u"LinePatternElement FillPatternElement Family ParameterFilterElement "
        u"RevitLinkType ImportInstance CADLinkType ViewFamilyType "
        u"ModelPathUtils StartingViewSettings Element Transaction "
        u"TransactionGroup TransactionStatus IFailuresPreprocessor "
        u"FailureProcessingResult FailureSeverity OpenOptions "
        u"DetachFromCentralOption WorksetConfiguration "
        u"WorksetConfigurationOption SaveAsOptions WorksharingSaveAsOptions "
        u"SaveOptions TransactWithCentralOptions SynchronizeWithCentralOptions "
        u"RelinquishOptions WorksharingUtils FilteredWorksetCollector "
        u"WorksetKind WorksetId PointCloudInstance PointCloudType "
        u"ImageInstance ImageType BrowserOrganization FolderItemInfo BuiltInCategory "
        u"View3D OptionalFunctionalityUtils NavisworksExportOptions "
        u"NavisworksExportScope NavisworksCoordinates NavisworksParameters"),
    u"Autodesk.Revit.UI": (u"TaskDialog TaskDialogCommonButtons TaskDialogResult "
                           u"TaskDialogCommandLinkId UIThemeManager UITheme "
                           u"RevitCommandId PostableCommand IExternalEventHandler "
                           u"ExternalEvent ExternalEventRequest"),
    u"Autodesk.Revit.UI.Events": u"DialogBoxShowingEventArgs",
}

PY2_NAMES = set([u"unicode", u"unichr", u"basestring", u"long", u"__revit__",
                 u"__file__", u"__name__"])


# ============================================================
# reading helpers
# ============================================================

def read(root, name):
    with io.open(os.path.join(root, name), u"r", encoding=u"utf-8") as handle:
        return handle.read()


def py_files(root):
    return sorted(n for n in os.listdir(root) if n.endswith(u".py")
                  and n not in (u"import_check.py", u"bench_logic.py"))


def tool_modules(root):
    return [n for n in py_files(root) if n.startswith(PREFIX)]


def code_only(source):
    """Source with every string and comment blanked, line numbers kept."""
    lines = source.splitlines(True)
    out = [list(line) for line in lines]
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, SyntaxError):
        return source
    blank_types = (tokenize.STRING, tokenize.COMMENT)
    fstring_types = tuple(getattr(tokenize, n) for n in
                          (u"FSTRING_START", u"FSTRING_MIDDLE", u"FSTRING_END")
                          if hasattr(tokenize, n))
    for tok in tokens:
        if tok.type in blank_types or tok.type in fstring_types:
            (sr, sc), (er, ec) = tok.start, tok.end
            for row in range(sr, er + 1):
                line = out[row - 1]
                start = sc if row == sr else 0
                end = ec if row == er else len(line)
                for col in range(start, min(end, len(line))):
                    if line[col] != u"\n":
                        line[col] = u" "
    return u"".join(u"".join(line) for line in out)


def parse_xaml(root, name):
    return xml.dom.minidom.parseString(read(root, name).encode(u"utf-8"))


def theme_keys(root):
    dom = parse_xaml(root, u"Theme.xaml")
    keys = {}
    for node in dom.getElementsByTagName(u"*"):
        key = node.getAttribute(u"x:Key")
        if key:
            keys[key] = node
    return keys


def all_elements(dom):
    return dom.getElementsByTagName(u"*")


# ============================================================
# stub .NET and Revit API
# ============================================================

class _StubMeta(type):
    def __getattr__(cls, name):
        return _StubValue()

    def __getitem__(cls, item):
        return cls


class _StubValue(object):
    def __getattr__(self, name):
        return _StubValue()

    def __call__(self, *args, **kwargs):
        return _StubValue()

    def __or__(self, other):
        return self


def _stub_init(self, *args, **kwargs):
    pass


def make_stub_modules():
    modules = {}
    clr = types.ModuleType(u"clr")
    clr.references = []
    clr.AddReference = lambda name: clr.references.append(name)
    modules[u"clr"] = clr
    for namespace, names in NAMESPACES.items():
        module = types.ModuleType(namespace)
        for name in names.split():
            # constructors take any arguments, as the real types do
            setattr(module, name, _StubMeta(name, (object,), {u"__init__": _stub_init}))
        modules[namespace] = module
    for namespace in list(NAMESPACES):
        parts = namespace.split(u".")
        for index in range(1, len(parts)):
            parent = u".".join(parts[:index])
            if parent not in modules:
                modules[parent] = types.ModuleType(parent)
                modules[parent].__path__ = []
            modules[parent].__path__ = []
    for namespace in NAMESPACES:
        parts = namespace.split(u".")
        if len(parts) > 1:
            setattr(modules[u".".join(parts[:-1])], parts[-1], modules[namespace])
    return modules


# ============================================================
# the rules - each returns a list of problems
# ============================================================

def rule_xaml_parses(root):
    problems = []
    for name in LAYOUTS + [u"Theme.xaml"]:
        try:
            parse_xaml(root, name)
        except Exception as error:
            problems.append(u"{0} does not parse: {1}".format(name, error))
    return problems


def _imports(source):
    """(line, namespace) for every System / Autodesk / Microsoft import."""
    out = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            out.append((node.lineno, node.module))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                out.append((node.lineno, alias.name))
    return out


def _is_dotnet(name):
    return name.split(u".")[0] in (u"System", u"Autodesk", u"Microsoft")


def rule_clr_first(root):
    problems = []
    for name in tool_modules(root):
        if name == CLR_MODULE + u".py":
            continue
        imports = _imports(read(root, name))
        dotnet = [line for line, module in imports if _is_dotnet(module)]
        if not dotnet:
            continue
        clr_lines = [line for line, module in imports if module == CLR_MODULE]
        if not clr_lines or min(clr_lines) > min(dotnet):
            problems.append(u"{0} touches .NET before importing {1}".format(name, CLR_MODULE))
    return problems


def _referenced_assemblies(root):
    tree = ast.parse(read(root, CLR_MODULE + u".py"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == u"ASSEMBLIES" for t in node.targets):
            return set(elt.value for elt in node.value.elts)
    return set()


def rule_assembly_for(root):
    problems = []
    referenced = _referenced_assemblies(root)
    for name in py_files(root):
        for line, module in _imports(read(root, name)):
            if not _is_dotnet(module):
                continue
            if module not in ASSEMBLY_FOR:
                problems.append(u"{0}:{1} imports {2}, which ASSEMBLY_FOR does not know".format(
                    name, line, module))
                continue
            needed = ASSEMBLY_FOR[module]
            if needed and needed not in referenced:
                problems.append(u"{0}:{1} needs {2} referenced in {3}".format(
                    name, line, needed, CLR_MODULE))
    return problems


def rule_modules_load(root):
    problems = []
    saved = dict(sys.modules)
    stubs = make_stub_modules()
    sys.path.insert(0, root)
    try:
        for name in list(sys.modules):
            if name.startswith(PREFIX):
                del sys.modules[name]
        sys.modules.update(stubs)
        for name in tool_modules(root):
            module_name = name[:-3]
            try:
                spec = importlib.util.spec_from_file_location(
                    module_name, os.path.join(root, name))
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
            except Exception as error:
                problems.append(u"{0} does not load: {1}: {2}".format(
                    name, type(error).__name__, error))
    finally:
        sys.path.remove(root)
        sys.modules.clear()
        sys.modules.update(saved)
    return problems


def rule_no_static_resource(root):
    return [u"{0} uses StaticResource".format(name) for name in LAYOUTS
            if u"StaticResource" in read(root, name)]


def rule_dynamic_keys_exist(root):
    keys = theme_keys(root)
    problems = []
    for name in LAYOUTS + [u"Theme.xaml"]:
        for key in re.findall(u"DynamicResource\\s+([A-Za-z0-9_]+)", read(root, name)):
            if key not in keys:
                problems.append(u"{0} asks for {1}, which Theme.xaml lacks".format(name, key))
    return problems


def rule_style_target(root):
    keys = theme_keys(root)
    problems = []
    for name in LAYOUTS:
        for node in all_elements(parse_xaml(root, name)):
            match = re.match(u"\\{DynamicResource\\s+(\\w+)\\}", node.getAttribute(u"Style"))
            if not match or match.group(1) not in keys:
                continue
            target = keys[match.group(1)].getAttribute(u"TargetType")
            if target and target != node.tagName:
                problems.append(u"{0}: <{1}> given style {2} for {3}".format(
                    name, node.tagName, match.group(1), target))
    return problems


def _xnames(root):
    names = set()
    for name in LAYOUTS:
        for node in all_elements(parse_xaml(root, name)):
            if node.getAttribute(u"x:Name"):
                names.add(node.getAttribute(u"x:Name"))
    return names


def _find_calls(tree):
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        fname = func.attr if isinstance(func, ast.Attribute) else (
            func.id if isinstance(func, ast.Name) else u"")
        if fname in (u"find", u"FindName"):
            yield node


def rule_findname(root):
    names = _xnames(root)
    problems = []
    for name in tool_modules(root):
        tree = ast.parse(read(root, name))
        for call in _find_calls(tree):
            arg = call.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                if arg.value not in names:
                    problems.append(u"{0}:{1} finds {2}, which no layout names".format(
                        name, call.lineno, arg.value))
        # find(prefix + u"Suffix") inside _paint_step, prefixes from its callers
        suffixes, prefixes = set(), set()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == u"_paint_step":
                for call in _find_calls(node):
                    arg = call.args[0]
                    if isinstance(arg, ast.BinOp) and isinstance(arg.right, ast.Constant):
                        suffixes.add(arg.right.value)
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == u"_paint_step" and node.args
                    and isinstance(node.args[0], ast.Constant)):
                prefixes.add(node.args[0].value)
        for prefix in prefixes:
            for suffix in suffixes:
                if prefix + suffix not in names:
                    problems.append(u"{0}: step {1} has no {2}".format(name, prefix, prefix + suffix))
        # find(self.prefix + u"Suffix") inside RetainList, prefixes from RetainList(...)
        list_suffixes, list_prefixes = set(), set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == u"RetainList":
                for call in _find_calls(node):
                    arg = call.args[0]
                    if isinstance(arg, ast.BinOp) and isinstance(arg.right, ast.Constant):
                        list_suffixes.add(arg.right.value)
            if (isinstance(node, ast.Call) and getattr(node.func, u"id", u"") == u"RetainList"
                    and len(node.args) > 1 and isinstance(node.args[1], ast.Constant)):
                list_prefixes.add(node.args[1].value)
        for prefix in list_prefixes:
            for suffix in list_suffixes:
                if prefix + suffix not in names:
                    problems.append(u"{0}: retain list {1} has no {2}".format(name, prefix, prefix + suffix))
    return problems


def rule_no_fstrings(root):
    problems = []
    for name in py_files(root):
        for tok in tokenize.generate_tokens(io.StringIO(read(root, name)).readline):
            text = tok.string
            if tok.type == getattr(tokenize, u"FSTRING_START", -1) or (
                    tok.type == tokenize.STRING and re.match(u"^[rRbBuU]*[fF]", text)):
                problems.append(u"{0}:{1} f-string".format(name, tok.start[0]))
    return problems


def rule_no_print(root):
    problems = []
    for name in py_files(root):
        for tok in tokenize.generate_tokens(io.StringIO(read(root, name)).readline):
            if tok.type == tokenize.NAME and tok.string == u"print":
                problems.append(u"{0}:{1} print".format(name, tok.start[0]))
    return problems


def rule_no_integer_value(root):
    problems = []
    for name in py_files(root):
        tree = ast.parse(read(root, name))
        allowed = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == u"eid_value":
                allowed.update(id(sub) for sub in ast.walk(node))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == u"IntegerValue" \
                    and id(node) not in allowed:
                problems.append(u"{0}:{1} bare .IntegerValue".format(name, node.lineno))
    return problems


def rule_no_uri(root):
    problems = []
    for name in py_files(root):
        tree = ast.parse(read(root, name))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == u"System" and \
                    any(alias.name == u"Uri" for alias in node.names):
                problems.append(u"{0}:{1} imports System.Uri".format(name, node.lineno))
            if isinstance(node, ast.Attribute) and node.attr in (u"Uri", u"UriSource"):
                problems.append(u"{0}:{1} uses {2}".format(name, node.lineno, node.attr))
    return problems


def _palette_dicts(root):
    tree = ast.parse(read(root, u"mcu_theme.py"))
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in (u"DARK", u"LIGHT"):
                    out[target.id] = set(k.value for k in node.value.keys)
    return out


def rule_palettes(root):
    problems = []
    palettes = _palette_dicts(root)
    if set(palettes) != set([u"DARK", u"LIGHT"]):
        return [u"mcu_theme needs DARK and LIGHT"]
    if palettes[u"DARK"] != palettes[u"LIGHT"]:
        problems.append(u"palettes differ: {0}".format(
            sorted(palettes[u"DARK"] ^ palettes[u"LIGHT"])))
    keys = theme_keys(root)
    for key in palettes[u"DARK"] | palettes[u"LIGHT"]:
        if key not in keys:
            problems.append(u"palette key {0} has no brush in Theme.xaml".format(key))
    return problems


def rule_resource_refs(root):
    keys = set(theme_keys(root))
    problems = []
    for name in tool_modules(root):
        tree = ast.parse(read(root, name))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and node.func.attr in (u"SetResourceReference", u"FindResource"):
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str) \
                            and arg.value not in keys:
                        problems.append(u"{0}:{1} unknown resource {2}".format(
                            name, node.lineno, arg.value))
        for match in re.finditer(u"\\(u\"([A-Za-z]+)\", (True|False), u\"([A-Za-z]+)\"\\)",
                                 read(root, name)):
            if match.group(3) not in keys:
                problems.append(u"{0}: prompt button style {1} unknown".format(name, match.group(3)))
    return problems


def rule_no_duplicate_defs(root):
    problems = []
    for name in py_files(root):
        tree = ast.parse(read(root, name))
        for node in ast.walk(tree):
            body = getattr(node, u"body", None)
            if not isinstance(body, list):
                continue
            seen = set()
            for item in body:
                if isinstance(item, (ast.FunctionDef, ast.ClassDef)):
                    if item.name in seen:
                        problems.append(u"{0}:{1} {2} defined twice".format(
                            name, item.lineno, item.name))
                    seen.add(item.name)
    return problems


def rule_globals_exist(root):
    problems = []
    known = set(dir(builtins)) | PY2_NAMES
    for name in py_files(root):
        top = symtable.symtable(read(root, name), name, u"exec")
        defined = set(s.get_name() for s in top.get_symbols()
                      if s.is_assigned() or s.is_imported() or s.is_namespace())

        def walk(table):
            for child in table.get_children():
                for symbol in child.get_symbols():
                    if symbol.is_global() and symbol.is_referenced() and \
                            symbol.get_name() not in defined and \
                            symbol.get_name() not in known:
                        problems.append(u"{0}: {1} uses undefined {2}".format(
                            name, child.get_name(), symbol.get_name()))
                walk(child)
        walk(top)
    return problems


def rule_script_thin(root):
    tree = ast.parse(read(root, u"script.py"))
    problems = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module]
            for module in names:
                if module not in (u"os", u"sys", u"io", u"traceback"):
                    problems.append(u"script.py imports {0} at load".format(module))
    main = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == u"main"]
    if not main or not any(isinstance(n, ast.Try) for n in main[0].body):
        problems.append(u"script.py main() does not load inside try/except")
    return problems


def _version(root):
    match = re.search(u"^__version__ = u\"([0-9.]+)\"", read(root, u"mcu_core.py"), re.M)
    return match.group(1) if match else u""


def rule_changelog_version(root):
    version = _version(root)
    if not version:
        return [u"mcu_core has no __version__"]
    if not re.search(u"^## " + re.escape(version) + u"\\s*$", read(root, u"CHANGELOG.md"), re.M):
        return [u"CHANGELOG.md has no entry for {0}".format(version)]
    return []


def rule_ascii(root):
    problems = []
    for name in py_files(root):
        for number, line in enumerate(read(root, name).splitlines(), 1):
            if any(ord(ch) > 127 for ch in line):
                problems.append(u"{0}:{1} non-ASCII".format(name, number))
    return problems


def rule_no_baseline(root):
    return [u"{0} uses VerticalAlignment=Baseline".format(name) for name in LAYOUTS
            if re.search(u"VerticalAlignment=\"Baseline\"", read(root, name))]


def rule_ribbon_name(root):
    match = re.search(u"^title:\\s*(.+)$", read(root, u"bundle.yaml"), re.M)
    core = re.search(u"^RIBBON_NAME = u\"(.+)\"", read(root, u"mcu_core.py"), re.M)
    if not match or not core or match.group(1).strip() != core.group(1):
        return [u"bundle.yaml title does not match RIBBON_NAME"]
    return []


def rule_no_shared_files(root):
    """A delivery must not carry the extension's shared singular files."""
    ext = root
    while ext and not ext.endswith(u".extension"):
        parent = os.path.dirname(ext)
        if parent == ext:
            return []
        ext = parent
    problems = []
    for rel in (u"startup.py", u"hooks", os.path.join(u"lib", u"revobim", u"__init__.py")):
        if os.path.exists(os.path.join(ext, rel)):
            problems.append(u"delivery ships shared file " + rel)
    panel = os.path.dirname(root)
    if os.path.exists(os.path.join(panel, u"bundle.yaml")):
        problems.append(u"delivery ships the Management panel bundle.yaml")
    return problems


def _calls(tree, fname):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            called = func.attr if isinstance(func, ast.Attribute) else getattr(func, u"id", u"")
            if called == fname:
                yield node


def rule_egg_wired(root):
    problems = []
    tree = ast.parse(read(root, u"mcu_ui.py"))
    if not list(_calls(tree, u"attach_egg")):
        problems.append(u"attach_egg is never called")
    if not list(_calls(tree, u"attach_to_window")):
        problems.append(u"egg_hook.attach_to_window is never called")
    return problems


def rule_theme_chip(root):
    problems = []
    for name in HEADER_WINDOWS:
        names = set(n.getAttribute(u"x:Name") for n in all_elements(parse_xaml(root, name)))
        for needed in (u"ThemeChip", u"ThemeChipText", u"VersionText", u"LogoText"):
            if needed not in names:
                problems.append(u"{0} has no {1}".format(name, needed))
    if not list(_calls(ast.parse(read(root, u"mcu_ui.py")), u"canvas_is_dark")):
        problems.append(u"nothing asks Revit which canvas theme is in use")
    return problems


def rule_progress_panel(root):
    problems = []
    for name in HEADER_WINDOWS:
        dom = parse_xaml(root, name)
        names = dict((n.getAttribute(u"x:Name"), n) for n in all_elements(dom))
        for needed in (u"ProgressPanel", u"ProgressTrack", u"ProgressFill",
                       u"ProgressPercent", u"ProgressStage", u"ProgressEta"):
            if needed not in names:
                problems.append(u"{0} has no {1}".format(name, needed))
        track = names.get(u"ProgressTrack")
        if track is not None:
            try:
                if float(track.getAttribute(u"Height") or 0) < 18:
                    problems.append(u"{0}: the progress bar is not thick".format(name))
            except ValueError:
                problems.append(u"{0}: progress bar height unreadable".format(name))
        panel = names.get(u"ProgressPanel")
        footer_rows = [int(n.getAttribute(u"Grid.Row")) for n in all_elements(dom)
                       if n.getAttribute(u"Grid.Row") and n.parentNode is (panel.parentNode if panel else None)]
        if panel is not None and int(panel.getAttribute(u"Grid.Row") or 0) < max(footer_rows or [0]) - 1:
            problems.append(u"{0}: the progress bar is not at the bottom".format(name))
    tree = ast.parse(read(root, u"mcu_window.py"))
    if not list(_calls(tree, u"ProgressBar")):
        problems.append(u"the main window never builds the progress bar")
    return problems


def rule_no_sleep(root):
    """Thread.Sleep on Revit's STA thread once opened a blank pyRevit output
    window. Waits poll a socket or use a DispatcherTimer instead."""
    problems = []
    for name in tool_modules(root):
        code = code_only(read(root, name))
        for number, line in enumerate(code.splitlines(), 1):
            if re.search(u"\\bsleep\\s*\\(|\\bSleep\\s*\\(", line):
                problems.append(u"{0}:{1} sleeps on the UI thread".format(name, number))
    return problems


def rule_dp_through_class(root):
    problems = []
    for name in tool_modules(root):
        for number, line in enumerate(code_only(read(root, name)).splitlines(), 1):
            if re.search(u"\\b[a-z_][A-Za-z0-9_]*\\.[A-Z]\\w*Property\\b", line):
                problems.append(u"{0}:{1} dependency property through an instance".format(
                    name, number))
    return problems


def rule_handlers_safe(root):
    problems = []
    allowed = (u"safe_handler", u"safe", u"_prompt_click", u"_grip_handler", u"guarded")
    for name in tool_modules(root):
        tree = ast.parse(read(root, name))
        for node in ast.walk(tree):
            if isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Add) and \
                    isinstance(node.target, ast.Attribute) and \
                    node.target.attr in (u"Click", u"SelectionChanged", u"Tick"):
                value = node.value
                called = u""
                if isinstance(value, ast.Call):
                    func = value.func
                    called = func.attr if isinstance(func, ast.Attribute) else getattr(func, u"id", u"")
                if called not in allowed:
                    problems.append(u"{0}:{1} {2} handler not wrapped by safe_handler".format(
                        name, node.lineno, node.target.attr))
    return problems


def rule_no_pump_in_ops(root):
    code = code_only(read(root, u"mcu_ops.py"))
    problems = []
    if re.search(u"\\bmcu_ui\\b|\\bDispatcher\\b|\\bpump\\(", code):
        problems.append(u"mcu_ops reaches the dispatcher - never inside a transaction")
    return problems


def rule_cleanup_gated(root):
    tree = ast.parse(read(root, u"mcu_window.py"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == u"on_cleanup":
            first = node.body[0]
            text = ast.unparse(first)
            if isinstance(first, ast.If) and u"self.synced" in text and \
                    u"self.saved_as" in text and u"return" in ast.unparse(first.body[-1]):
                return []
            return [u"on_cleanup does not open by refusing until synced and saved as"]
    return [u"mcu_window has no on_cleanup"]


SURFACES = (u"ListBox", u"ListBoxItem", u"CheckBox", u"RadioButton", u"ComboBox",
            u"ComboBoxItem", u"TextBox", u"TabControl", u"TabItem", u"ScrollBar", u"ToolTip")
NEEDS_DISABLED_LOOK = (u"ListBox", u"CheckBox", u"RadioButton", u"ComboBox", u"TextBox")


def rule_surfaces_themed(root):
    """Any control that paints a surface must have its template replaced in
    Theme.xaml - the stock ones fall back to Windows colours (a white box in
    dark mode, most visibly when disabled) - and the ones that can be
    switched off must have a disabled look of their own. DataGrid is only
    themed through its parts, so nothing may disable one."""
    problems = []
    theme = parse_xaml(root, u"Theme.xaml")
    styles = {}
    for style in theme.getElementsByTagName(u"Style"):
        if not style.getAttribute(u"x:Key"):
            styles[style.getAttribute(u"TargetType")] = style
    used = set()
    for name in LAYOUTS:
        for node in all_elements(parse_xaml(root, name)):
            used.add(node.tagName)
    code = u"".join(code_only(read(root, n)) for n in tool_modules(root))
    for surface in SURFACES:
        if re.search(u"\\b" + surface + u"\\(\\)", code):
            used.add(surface)
    for surface in SURFACES:
        if surface not in used:
            continue
        style = styles.get(surface)
        setters = style.getElementsByTagName(u"Setter") if style is not None else []
        if not any(s.getAttribute(u"Property") == u"Template" for s in setters):
            problems.append(u"{0} is used but Theme.xaml does not replace its template".format(surface))
            continue
        if surface in NEEDS_DISABLED_LOOK:
            triggers = style.getElementsByTagName(u"Trigger")
            if not any(t.getAttribute(u"Property") == u"IsEnabled" for t in triggers):
                problems.append(u"{0} has no disabled look".format(surface))
    for name in tool_modules(root):
        if re.search(u"Grid\\w*\"\\)\\.IsEnabled\\s*=", code_only(read(root, name))):
            problems.append(u"{0} disables a DataGrid, which has no themed disabled look".format(name))
    return problems


def rule_nwc_wired(root):
    """Every NWC option has its tick in the layout, the export runs before
    the clean up, and every written file is checked on disk."""
    problems = []
    names = _xnames(root)
    core_tree = ast.parse(read(root, u"mcu_core.py"))
    keys = []
    for node in ast.walk(core_tree):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == u"NWC_BOOL_OPTIONS" for t in node.targets):
            keys = [elt.elts[0].value for elt in node.value.elts]
    if not keys:
        problems.append(u"no NWC_BOOL_OPTIONS in mcu_core")
    for key in keys:
        if u"NwcOpt_" + key not in names:
            problems.append(u"NWC option {0} has no NwcOpt_{0} tick".format(key))
    window = read(root, u"mcu_window.py")
    phase = window.find(u"self.export_nwc_phase(run_template")
    run = window.find(u"report = ops.run_cleanup(")
    if phase < 0 or run < 0 or phase > run:
        problems.append(u"the NWC export does not run before the clean up")
    ops_tree = ast.parse(read(root, u"mcu_ops.py"))
    export = [n for n in ast.walk(ops_tree) if isinstance(n, ast.FunctionDef) and n.name == u"export_nwc"]
    if not export or u"nwc_written" not in ast.unparse(export[0]):
        problems.append(u"export_nwc does not check the files it wrote")
    return problems


def rule_stays_in_front(root):
    """The main window is owned by Revit's window, and comes back up after
    every busy spell (sync, detach, save, clean up, publish)."""
    problems = []
    tree = ast.parse(read(root, u"mcu_window.py"))
    init = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == u"__init__"
            and u"standard_window" in ast.unparse(n)]
    if not init or u"own_to_revit" not in ast.unparse(init[0]):
        problems.append(u"the main window is not owned by Revit's window")
    end = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == u"end_busy"]
    if not end or u"bring_to_front" not in ast.unparse(end[0]):
        problems.append(u"end_busy does not bring the window back to the front")
    ui_code = code_only(read(root, u"mcu_ui.py"))
    if re.search(u"Topmost\\s*=\\s*True", ui_code) and not re.search(u"Topmost\\s*=\\s*False", ui_code):
        problems.append(u"Topmost is switched on and never off")
    return problems


def rule_suffix_respected(root):
    """Every file name the window builds must go through active_suffix, so
    the Suffix tick cannot be bypassed."""
    problems = []
    tree = ast.parse(read(root, u"mcu_window.py"))
    for call in ast.walk(tree):
        if isinstance(call, ast.Call) and getattr(call.func, u"attr", u"") == u"send_file_name":
            if len(call.args) < 2 or u"active_suffix" not in ast.unparse(call.args[1]):
                problems.append(u"mcu_window.py:{0} names a file without active_suffix".format(call.lineno))
    return problems


def rule_close_guarded(root):
    """After a clean up, Close must go through the save prompt; the open
    model is closed by Revit's own command, never Document.Close; a sync of
    a local file needs CONFIRM."""
    problems = []
    tree = ast.parse(read(root, u"mcu_window.py"))
    closing = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == u"on_closing"]
    if not closing or u"finish_and_close" not in ast.unparse(closing[0]):
        problems.append(u"closing after a clean up skips the save prompt")
    saver = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == u"save_and_close_model"]
    if not saver:
        return problems + [u"no save_and_close_model"]
    body = ast.unparse(saver[0])
    if u"confirm_typed" not in body:
        problems.append(u"syncing a local file does not ask for CONFIRM")
    if u"self.post_close = True" not in body:
        problems.append(u"the open model is never queued to close")
    active_branch = body.split(u"if self.target_is_active:")[1].split(u"else:")[0] if \
        u"if self.target_is_active:" in body else u""
    if u"close_document" in active_branch:
        problems.append(u"the open model is closed with Document.Close, which Revit refuses")
    closer = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == u"after_close"]
    if not closer or u"post_close_active" not in ast.unparse(closer[0]):
        problems.append(u"nothing posts Revit's Close command once the window has gone")
    return problems


def rule_debug_wired(root):
    """The debug report has to reach the run, the window has to own one, and
    nothing may write the APS token into it."""
    problems = []
    window = ast.parse(read(root, u"mcu_window.py"))
    runs = [n for n in ast.walk(window) if isinstance(n, ast.Call)
            and getattr(n.func, u"attr", u"") == u"run_cleanup"]
    for call in runs:
        if not any(k.arg == u"debug" for k in call.keywords):
            problems.append(u"run_cleanup is not given the debug report")
        if not any(k.arg == u"uidoc" for k in call.keywords):
            problems.append(u"run_cleanup is not given the view to move off")
    if u"DebugCheck" not in _xnames(root):
        problems.append(u"no Debug report tick box")
    for name in tool_modules(root):
        for number, line in enumerate(code_only(read(root, name)).splitlines(), 1):
            if re.search(u"debug\\w*\\.(line|values|table|section)\\(.*\\b(token|access)\\b", line):
                problems.append(u"{0}:{1} writes a token into the debug report".format(name, number))
    ops_tree = ast.parse(read(root, u"mcu_ops.py"))
    if not [n for n in ast.walk(ops_tree) if isinstance(n, ast.Call)
            and getattr(n.func, u"id", u"") == u"move_off_doomed_views"]:
        problems.append(u"run_cleanup never moves off a view that is being deleted")
    return problems


def rule_skip_guarded(root):
    """Skipping steps 1 and 2 must go through the typed word and must never
    save or sync the open model."""
    problems = []
    tree = ast.parse(read(root, u"mcu_window.py"))
    handler = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == u"on_skip":
            handler = node
    if handler is None:
        return [u"mcu_window has no on_skip"]
    calls = set()
    for node in ast.walk(handler):
        if isinstance(node, ast.Call):
            func = node.func
            calls.add(func.attr if isinstance(func, ast.Attribute) else getattr(func, u"id", u""))
    for needed in (u"confirm_typed", u"skip_warning", u"prompt"):
        if needed not in calls:
            problems.append(u"on_skip never calls " + needed)
    source = ast.unparse(handler)
    confirm_at = source.find(u"confirm_typed")
    skipped_at = source.find(u"self.skipped = True")
    if skipped_at < 0 or confirm_at < 0 or skipped_at < confirm_at:
        problems.append(u"on_skip sets the skip before checking the typed word")
    runs = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
            and getattr(n.func, u"attr", u"") == u"run_cleanup"]
    for call in runs:
        save = [k for k in call.keywords if k.arg == u"save"]
        if not save or u"self.skipped" not in ast.unparse(save[0].value):
            problems.append(u"run_cleanup is not told to skip saving when steps were skipped")
    return problems


# ============================================================
# modeless discipline
# ============================================================

def _class_methods(tree, class_name):
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return dict((n.name, n) for n in node.body if isinstance(n, ast.FunctionDef))
    return {}


def _self_ref(node):
    """self.name as a bare reference (not a call) - a handler being passed."""
    if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
            and node.value.id == u"self"):
        return node.attr
    return None


JOB_CALLS = (u"wire_job", u"request_job", u"request")
API_MODULES = (u"ops", u"model")


def _entries(methods):
    """(ui entry points, job entry points) of the main window."""
    ui_entries, job_entries = set([u"show", u"bring_back"]), set()
    for method in methods.values():
        for node in ast.walk(method):
            if isinstance(node, ast.Call):
                fname = node.func.attr if isinstance(node.func, ast.Attribute) else u""
                refs = [_self_ref(a) for a in node.args] + [_self_ref(k.value) for k in node.keywords]
                refs = [r for r in refs if r in methods]
                if fname in JOB_CALLS:
                    job_entries.update(refs)
                elif fname in (u"wire", u"safe_handler", u"guarded"):
                    ui_entries.update(refs)
            if isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Add):
                ref = _self_ref(node.value)
                if ref in methods:
                    ui_entries.add(ref)
    return ui_entries - job_entries, job_entries


def _reaches_api(methods, start, stop):
    """Path from start to an ops.* / model.* call, not crossing into stop."""
    seen = set()
    queue = [(start, [start])]
    while queue:
        name, path = queue.pop(0)
        if name in seen or name not in methods:
            continue
        seen.add(name)
        for node in ast.walk(methods[name]):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)
                    and func.value.id in API_MODULES):
                return path + [u"{0}.{1}".format(func.value.id, func.attr)]
            if (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)
                    and func.value.id == u"self" and func.attr in methods
                    and func.attr not in stop):
                queue.append((func.attr, path + [func.attr]))
    return None


def rule_modeless_discipline(root):
    """A modeless window is outside Revit's API context except inside a job.
    No button, timer or window event that runs outside a job may reach the
    model - ops.* or model.* - by any chain of calls."""
    tree = ast.parse(read(root, u"mcu_window.py"))
    methods = _class_methods(tree, u"CleanupWindow")
    ui_entries, job_entries = _entries(methods)
    problems = []
    if not job_entries:
        problems.append(u"no button runs as a job")
    for entry in sorted(ui_entries):
        path = _reaches_api(methods, entry, job_entries)
        if path:
            problems.append(u"{0} reaches the model outside a job: {1}".format(
                entry, u" -> ".join(path)))
    return problems


def rule_persistent_engine(root):
    """The window outlives the command: the engine must persist, the window
    must be shown modeless, and a second press must bring it back."""
    problems = []
    tree = ast.parse(read(root, u"script.py"))
    persistent = [n for n in tree.body if isinstance(n, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == u"__persistentengine__" for t in n.targets)
                  and isinstance(n.value, ast.Constant) and n.value.value is True]
    if not persistent:
        problems.append(u"script.py does not set __persistentengine__ = True at module level")
    if u"bring_back_existing" not in code_only(read(root, u"script.py")):
        problems.append(u"script.py opens a second window instead of bringing the first back")
    window = code_only(read(root, u"mcu_window.py"))
    if u"self.window.ShowDialog(" in window:
        problems.append(u"the main window is shown modal")
    if u"self.window.Show()" not in window:
        problems.append(u"the main window is never shown modeless")
    return problems


def rule_raise_checked(root):
    """Every ExternalEvent.Raise() answer is read, and a refusal drops only
    the job that was refused - never the whole queue."""
    problems = []
    tree = ast.parse(read(root, u"mcu_events.py"))
    methods = _class_methods(tree, u"ApiRunner")
    request = methods.get(u"request")
    if request is None:
        return [u"ApiRunner has no request"]
    body = ast.unparse(request)
    if u".Raise()" not in body or u"raise_kept" not in body:
        problems.append(u"Raise() is called without its answer being checked")
    for node in ast.walk(request):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Attribute) and t.attr == u"queue" for t in node.targets):
            problems.append(u"request replaces the whole queue on a refusal")
        if isinstance(node, ast.Delete):
            problems.append(u"request deletes from the queue directly")
    if u"ExternalEvent.Create" not in code_only(read(root, u"mcu_events.py")):
        problems.append(u"no ExternalEvent is created")
    return problems


def rule_drawer_everywhere(root):
    """Every window carries the shrink button and a drawer, the button uses
    the drawn glyph style, and the slide never leaves an animation holding."""
    problems = []
    for name in LAYOUTS:
        nodes = dict((n.getAttribute(u"x:Name"), n) for n in all_elements(parse_xaml(root, name)))
        for needed in (u"ShrinkButton", u"HeaderBar", u"RootGrid"):
            if needed not in nodes:
                problems.append(u"{0} has no {1}".format(name, needed))
        button = nodes.get(u"ShrinkButton")
        if button is not None and u"ShrinkButton" not in button.getAttribute(u"Style"):
            problems.append(u"{0}: the shrink button does not use the ShrinkButton style".format(name))
    keys = theme_keys(root)
    style = keys.get(u"ShrinkButton")
    if style is None:
        problems.append(u"Theme.xaml has no ShrinkButton style")
    else:
        triggers = [t for t in style.getElementsByTagName(u"Trigger")
                    if t.getAttribute(u"Property") == u"Tag" and t.getAttribute(u"Value") == u"shrunk"]
        paths = style.getElementsByTagName(u"Path")
        if not triggers or len(paths) < 2:
            problems.append(u"the ShrinkButton style does not swap two drawn glyphs on Tag=shrunk")
    ui_tree = ast.parse(read(root, u"mcu_ui.py"))
    funcs = dict((n.name, n) for n in ui_tree.body if isinstance(n, ast.FunctionDef))
    for holder in (u"standard_window", u"prompt"):
        node = funcs.get(holder)
        if node is None or u"attach_drawer" not in ast.unparse(node):
            problems.append(u"{0} builds a window without a drawer".format(holder))
    drawer = _class_methods(ui_tree, u"WindowDrawer")
    release = drawer.get(u"_release")
    if release is None or u"BeginAnimation" not in ast.unparse(release):
        problems.append(u"the drawer never releases an animation")
    if u"Storyboard" in code_only(read(root, u"mcu_ui.py")):
        problems.append(u"the drawer uses a Storyboard")
    return problems


def rule_file_dialogs_lock(root):
    """A Windows file dialog shown from a job must keep Revit switched off:
    in the main window every ShowDialog goes through file_dialog."""
    problems = []
    tree = ast.parse(read(root, u"mcu_window.py"))
    methods = _class_methods(tree, u"CleanupWindow")
    for name, method in methods.items():
        if name == u"file_dialog":
            continue
        for node in ast.walk(method):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == u"ShowDialog"):
                problems.append(u"{0} opens a dialog without file_dialog".format(name))
    helper = methods.get(u"file_dialog")
    if helper is None or u"lock_revit" not in ast.unparse(helper):
        problems.append(u"file_dialog does not switch Revit off")
    return problems


def rule_theme_defaults_match(root):
    """Theme.xaml's brush defaults are what the window paints before the
    palette is applied - they must be the dark palette, not an old one."""
    problems = []
    tree = ast.parse(read(root, u"mcu_theme.py"))
    dark = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == u"DARK" for t in node.targets):
            dark = dict((k.value, v.value) for k, v in zip(node.value.keys, node.value.values))
    for key, node in theme_keys(root).items():
        if node.tagName != u"SolidColorBrush" or key not in dark:
            continue
        if node.getAttribute(u"Color").upper() != dark[key].upper():
            problems.append(u"Theme.xaml {0} is {1}, the dark palette says {2}".format(
                key, node.getAttribute(u"Color"), dark[key]))
    return problems


RULES = [
    (u"xaml parses", rule_xaml_parses),
    (u"mcu_clr imported first", rule_clr_first),
    (u"assembly referenced for every namespace", rule_assembly_for),
    (u"modules load against the stub API", rule_modules_load),
    (u"no StaticResource in layouts", rule_no_static_resource),
    (u"DynamicResource keys exist", rule_dynamic_keys_exist),
    (u"styles match their element", rule_style_target),
    (u"find names exist", rule_findname),
    (u"no f-strings", rule_no_fstrings),
    (u"no print", rule_no_print),
    (u"no bare IntegerValue", rule_no_integer_value),
    (u"no System.Uri", rule_no_uri),
    (u"palettes match and have brushes", rule_palettes),
    (u"resource references exist", rule_resource_refs),
    (u"nothing defined twice", rule_no_duplicate_defs),
    (u"every global exists", rule_globals_exist),
    (u"script.py is a thin loader", rule_script_thin),
    (u"changelog has the version", rule_changelog_version),
    (u"python files are ASCII", rule_ascii),
    (u"no Baseline alignment", rule_no_baseline),
    (u"ribbon name matches the tool", rule_ribbon_name),
    (u"no shared files shipped", rule_no_shared_files),
    (u"easter egg wired", rule_egg_wired),
    (u"dark/light chip and canvas detection", rule_theme_chip),
    (u"thick progress bar at the bottom", rule_progress_panel),
    (u"no sleeping on Revit's thread", rule_no_sleep),
    (u"dependency properties through the class", rule_dp_through_class),
    (u"no silent handlers", rule_handlers_safe),
    (u"no dispatcher in the write module", rule_no_pump_in_ops),
    (u"Clean Up gated on sync and save as", rule_cleanup_gated),
    (u"skip needs CONFIRM and never saves", rule_skip_guarded),
    (u"debug report and view switch wired", rule_debug_wired),
    (u"save and close guarded", rule_close_guarded),
    (u"suffix tick respected", rule_suffix_respected),
    (u"window stays in front of Revit", rule_stays_in_front),
    (u"NWC export wired", rule_nwc_wired),
    (u"surface controls themed, disabled too", rule_surfaces_themed),
    (u"nothing outside a job reaches the model", rule_modeless_discipline),
    (u"persistent engine, modeless window, one instance", rule_persistent_engine),
    (u"every Raise checked, refusals drop one job", rule_raise_checked),
    (u"a drawer on every window", rule_drawer_everywhere),
    (u"Theme.xaml defaults are the dark palette", rule_theme_defaults_match),
    (u"file dialogs in a job keep Revit off", rule_file_dialogs_lock),
]


# ============================================================
# selftest - break each rule and confirm it notices
# ============================================================

def _edit(name, old, new):
    def mutate(root):
        path = os.path.join(root, name)
        text = read(root, name)
        if old not in text:
            raise AssertionError(u"selftest anchor missing in {0}: {1}".format(name, old))
        with io.open(path, u"w", encoding=u"utf-8") as handle:
            handle.write(text.replace(old, new, 1))
    return mutate


def _append(name, text):
    def mutate(root):
        with io.open(os.path.join(root, name), u"a", encoding=u"utf-8") as handle:
            handle.write(text)
    return mutate


def _touch_extension(rel):
    def mutate(root):
        ext = root
        while not ext.endswith(u".extension"):
            ext = os.path.dirname(ext)
        with io.open(os.path.join(ext, rel), u"w", encoding=u"utf-8") as handle:
            handle.write(u"# shipped by mistake\n")
    return mutate


BREAKS = {
    u"xaml parses": _edit(u"ModelCleanup.xaml", u"<!-- ==================== header",
                          u"<!-- a -- b --><!-- ==================== header"),
    u"mcu_clr imported first": _edit(
        u"mcu_theme.py", u"import mcu_clr  # noqa: F401 - must come before any System.* import\n",
        u"from System.Windows.Media import ColorConverter\nimport mcu_clr\n"),
    u"assembly referenced for every namespace": _edit(u"mcu_clr.py", u"    u\"System.Data\",\n", u""),
    u"modules load against the stub API": _edit(
        u"mcu_ops.py", u"FilteredWorksetCollector, WorksetKind, WorksetId)",
        u"FilteredWorksetCollector, WorksetKind, WorksetId, DialogBoxShowingEventArgs)"),
    u"no StaticResource in layouts": _edit(u"McuPrompt.xaml", u"{DynamicResource BgBrush}",
                                           u"{StaticResource BgBrush}"),
    u"DynamicResource keys exist": _edit(u"McuPrompt.xaml", u"{DynamicResource BgBrush}",
                                         u"{DynamicResource NoSuchBrush}"),
    u"styles match their element": _edit(u"ModelCleanup.xaml", u"<TextBox x:Name=\"LogBox\"",
                                         u"<TextBox Style=\"{DynamicResource GreenButton}\" x:Name=\"LogBox\""),
    u"find names exist": _edit(u"McuSettings.xaml", u"x:Name=\"SheetCollapseButton\"",
                               u"x:Name=\"SheetFoldButton\""),
    u"no f-strings": _append(u"mcu_core.py", u"\nBROKEN = f\"{TOOL_NAME}\"\n"),
    u"no print": _append(u"mcu_core.py", u"\nprint(TOOL_NAME)\n"),
    u"no bare IntegerValue": _append(u"mcu_core.py", u"\ndef broken(x):\n    return x.IntegerValue\n"),
    u"no System.Uri": _edit(u"mcu_ui.py", u"from System import Action",
                            u"from System import Action, Uri"),
    u"palettes match and have brushes": _edit(u"mcu_theme.py", u"    u\"HoverBrush\": u\"#ECECF0\",\n", u""),
    u"resource references exist": _edit(u"mcu_window.py", u"u\"GreenSoftBrush\")",
                                        u"u\"GreenSoftBrushX\")"),
    u"nothing defined twice": _append(u"mcu_core.py", u"\ndef chunks(a, b):\n    return a\n"),
    u"every global exists": _append(u"mcu_core.py", u"\ndef broken_two():\n    return helper_that_is_gone()\n"),
    u"script.py is a thin loader": _edit(u"script.py", u"import traceback\n", u"import traceback\nimport clr\n"),
    u"changelog has the version": _edit(u"mcu_core.py", u"__version__ = u\"", u"__version__ = u\"9."),
    u"python files are ASCII": _append(u"mcu_core.py", u"\n# caf\u00e9\n"),
    u"no Baseline alignment": _edit(u"McuPrompt.xaml", u"<TextBlock x:Name=\"MessageText\"",
                                    u"<TextBlock VerticalAlignment=\"Baseline\" x:Name=\"MessageText\""),
    u"ribbon name matches the tool": _edit(u"bundle.yaml", u"title: Model Cleanup", u"title: Model Clean Up"),
    u"no shared files shipped": _touch_extension(u"startup.py"),
    u"easter egg wired": _edit(u"mcu_ui.py", u"    attach_egg(window, find(u\"LogoText\"), theme_state)\n", u""),
    u"dark/light chip and canvas detection": _edit(
        u"mcu_ui.py", u"self.canvas_dark = mcu_theme.canvas_is_dark(uiapp)", u"self.canvas_dark = None"),
    u"thick progress bar at the bottom": _edit(
        u"McuSettings.xaml", u"<Grid x:Name=\"ProgressTrack\" Height=\"24\">",
        u"<Grid x:Name=\"ProgressTrack\" Height=\"3\">"),
    u"no sleeping on Revit's thread": _edit(
        u"mcu_web.py", u"            tick()\n", u"            tick()\n            time.sleep(0.2)\n"),
    u"dependency properties through the class": _edit(
        u"mcu_window.py", u"Control.BackgroundProperty, u\"LockedBrush\"",
        u"button.BackgroundProperty, u\"LockedBrush\""),
    u"no silent handlers": _edit(u"mcu_window.py", u"self.find(name).Click += ui.safe_handler(self.window, handler, self.theme)",
                                 u"self.find(name).Click += handler"),
    u"no dispatcher in the write module": _edit(u"mcu_ops.py", u"import mcu_model as model\n",
                                                u"import mcu_model as model\nimport mcu_ui\n"),
    u"nothing outside a job reaches the model": _edit(
        u"mcu_window.py", u"        self.wire_job(u\"ScanButton\", u\"Count\", self.on_scan)",
        u"        self.wire(u\"ScanButton\", self.on_scan)"),
    u"persistent engine, modeless window, one instance": _edit(
        u"script.py", u"__persistentengine__ = True", u"__persistentengine__ = False"),
    u"every Raise checked, refusals drop one job": _edit(
        u"mcu_events.py", u"        self._drop(entry)\n", u"        self.queue = []\n"),
    u"a drawer on every window": _edit(
        u"mcu_ui.py", u"        drawer = attach_drawer(window, find)\n        set_owner(window, owner)",
        u"        drawer = None\n        set_owner(window, owner)"),
    u"file dialogs in a job keep Revit off": _edit(
        u"mcu_window.py", u"        if not self.file_dialog(dialog):\n            return u\"\", u\"\"",
        u"        if not dialog.ShowDialog(self.window):\n            return u\"\", u\"\""),
    u"Theme.xaml defaults are the dark palette": _edit(
        u"Theme.xaml", u"<SolidColorBrush x:Key=\"CardBrush\" Color=\"#3B4453\"/>",
        u"<SolidColorBrush x:Key=\"CardBrush\" Color=\"#2B2B2E\"/>"),
    u"surface controls themed, disabled too": _edit(
        u"Theme.xaml", u"<Setter Property=\"ScrollViewer.CanContentScroll\" Value=\"True\"/>\n        <Setter Property=\"Template\">",
        u"<Setter Property=\"ScrollViewer.CanContentScroll\" Value=\"True\"/>\n        <Setter Property=\"Tag\">"),
    u"NWC export wired": _edit(
        u"McuSettings.xaml", u"x:Name=\"NwcOpt_nwc_urls\"", u"x:Name=\"NwcOpt_urls\""),
    u"window stays in front of Revit": _edit(
        u"mcu_window.py", u"        self.owned = ui.own_to_revit(self.window, uiapp)\n",
        u"        self.owned = False\n"),
    u"suffix tick respected": _edit(
        u"mcu_window.py", u"core.send_file_name(source, core.active_suffix(self.template),",
        u"core.send_file_name(source, self.template.get(u\"file_suffix\"),"),
    u"save and close guarded": _edit(
        u"mcu_window.py", u"                if not answer or not core.confirm_typed(typed):",
        u"                if not answer:"),
    u"debug report and view switch wired": _edit(
        u"mcu_ops.py", u"            active_view_id = move_off_doomed_views(uidoc, doc, before, report, debug)\n",
        u"            pass\n"),
    u"skip needs CONFIRM and never saves": _edit(
        u"mcu_window.py", u"active_id, self._on_step, save=not self.skipped,",
        u"active_id, self._on_step,"),
    u"Clean Up gated on sync and save as": _edit(
        u"mcu_window.py", u"        if self.busy or not ((self.synced and self.saved_as) or self.skipped) or self.cleaned:\n            return\n",
        u""),
}


def run(root, quiet=False):
    failed = 0
    for label, rule in RULES:
        problems = rule(root)
        if problems:
            failed += 1
        if not quiet:
            print(u"{0:5} {1}".format(u"FAIL" if problems else u"ok", label))
            for problem in problems[:12]:
                print(u"        " + problem)
    return failed


def selftest():
    missing = [label for label, _ in RULES if label not in BREAKS]
    if missing:
        print(u"no breakage defined for: " + u", ".join(missing))
        return 1
    ext = TOOL_DIR
    while not ext.endswith(u".extension"):
        ext = os.path.dirname(ext)
    rel = os.path.relpath(TOOL_DIR, os.path.dirname(ext))
    bad = 0
    for label, rule in RULES:
        work = tempfile.mkdtemp()
        try:
            shutil.copytree(ext, os.path.join(work, os.path.basename(ext)))
            root = os.path.join(work, rel)
            if rule(root):
                print(u"BENCH {0}: fails before being broken".format(label))
                bad += 1
                continue
            BREAKS[label](root)
            caught = rule(root)
            print(u"{0:7} {1}".format(u"caught" if caught else u"MISSED", label))
            if not caught:
                bad += 1
        finally:
            shutil.rmtree(work, ignore_errors=True)
    return bad


if __name__ == u"__main__":
    if u"--selftest" in sys.argv:
        result = selftest()
        print(u"selftest: {0}".format(u"all rules caught their breakage" if not result
                                      else u"{0} problem(s)".format(result)))
    else:
        result = run(TOOL_DIR)
        print(u"{0} of {1} rules failed".format(result, len(RULES)))
    sys.exit(1 if result else 0)
