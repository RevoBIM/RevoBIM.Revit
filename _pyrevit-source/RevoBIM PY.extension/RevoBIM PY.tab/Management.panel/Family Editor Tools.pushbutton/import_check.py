# =========================================================================
# Family Editor Tools - bench check
#
# Runs under plain CPython from this folder:
#
#     python import_check.py
#     python import_check.py --selftest
#
# The selftest breaks every rule on purpose, in a throwaway copy of the
# folder, and confirms the rule catches it.  A rule nobody has tested is a
# rule that does not work.
# =========================================================================

import os
import re
import shutil
import sys
import symtable
import tempfile
import types
import xml.dom.minidom

HERE = os.path.dirname(os.path.abspath(__file__))

MODULES = (u"fet_clr", u"fet_core", u"fet_planes", u"theme", u"fet_model",
           u"fet_ui", u"fet_ops", u"fet_params_window", u"settings_window",
           u"fet_window")

LAYOUT_XAML = (u"FamilyEditorTools.xaml", u"FetSharedParams.xaml",
               u"FetPrompt.xaml", u"FetSettings.xaml")

THEME_XAML = u"Theme.xaml"

# Names a function may reach for without the module defining them.
ALLOWED_GLOBALS = set([
    u"__revit__", u"__file__", u"__name__", u"__version__", u"__title__",
    u"__doc__", u"__author__", u"__persistentengine__",
])


# =========================================================================
# The stub Revit and .NET API
#
# Every name is declared in the namespace the real API puts it in, and
# nowhere else, so a mis-namespaced import fails here instead of showing up
# in Revit as a blank white pyRevit window.
# =========================================================================

NAMESPACES = {
    u"System": (u"Action", u"AppDomain", u"DateTime", u"Double", u"TimeSpan",
                u"Uri"),
    u"System.Collections.Generic": (u"List",),
    u"System.Diagnostics": (u"Process",),
    u"System.IO": (u"File", u"FileMode", u"FileStream", u"MemoryStream"),
    u"System.Windows": (u"Application", u"Clipboard", u"CornerRadius",
                        u"FontWeights",
                        u"GridLength", u"RoutedEventHandler", u"TextWrapping",
                        u"GridUnitType", u"HorizontalAlignment",
                        u"Point", u"PresentationSource", u"ResizeMode",
                        u"SizeToContent", u"SystemParameters", u"TextTrimming",
                        u"Thickness", u"VerticalAlignment", u"Visibility",
                        u"Window", u"WindowStartupLocation", u"WindowState",
                        u"WindowStyle"),
    u"System.Windows.Controls": (u"Border", u"Canvas", u"CheckBox",
                                 u"TextChangedEventHandler",
                                 u"ColumnDefinition", u"ComboBox",
                                 u"ComboBoxItem", u"Grid", u"ListBoxItem",
                                 u"RowDefinition", u"TextBlock", u"TextBox"),
    u"System.Windows.Controls.Primitives": (u"Thumb",),
    u"System.Windows.Input": (u"Cursors", u"Key"),
    u"System.Windows.Interop": (u"WindowInteropHelper",),
    u"System.Windows.Markup": (u"XamlReader",),
    u"System.Windows.Media": (u"Brush", u"BrushConverter", u"Color",
                              u"DoubleCollection", u"SolidColorBrush"),
    u"System.Windows.Media.Imaging": (u"BitmapCacheOption", u"BitmapImage"),
    u"System.Windows.Shapes": (u"Ellipse", u"Line"),
    u"System.Windows.Threading": (u"DispatcherPriority", u"DispatcherTimer"),
    u"System.Windows.Forms": (u"Screen",),
    u"Microsoft.Win32": (u"OpenFileDialog", u"SaveFileDialog"),
    u"Autodesk.Revit.DB": (
        u"AppearanceAssetElement", u"BuiltInCategory",
        u"BuiltInParameter", u"BuiltInParameterGroup",
        u"Category", u"Color", u"CopyPasteOptions", u"DimensionType",
        u"DuplicateTypeAction", u"Element", u"ElementId",
        u"ElementTransformUtils", u"ExportRange", u"GenericForm",
        u"ZoomFitType",
        u"IDuplicateTypeNamesHandler", u"ImportInstance",
        u"View3D", u"ViewDetailLevel", u"ViewFamily", u"ViewFamilyType",
        u"ViewOrientation3D", u"ViewDisplayBackground",
        u"Transform",
        u"FailureProcessingResult", u"FilteredElementCollector",
        u"FillPatternElement", u"GraphicsStyleType", u"GroupTypeId",
        u"IFailuresPreprocessor", u"LabelUtils", u"Line",
        u"LinePatternElement", u"Material", u"ParameterType", u"Reference",
        u"ReferenceArray", u"ReferencePlane", u"SpecTypeId", u"SubTransaction",
        u"DisplayStyle", u"ImageExportOptions", u"ImageFileType",
        u"ImageResolution", u"SaveAsOptions", u"TextNoteType",
        u"Transaction", u"TransactionGroup",
        u"TransactionStatus", u"View",
        u"ViewType", u"XYZ"),
    u"Autodesk.Revit.DB.Visual": (u"AppearanceAssetEditScope", u"Asset",
                                 u"AssetProperty", u"AssetType"),
    u"Autodesk.Revit.UI": (u"ExternalEvent", u"IExternalEventHandler",
                           u"PostableCommand", u"RevitCommandId", u"TaskDialog",
                           u"UIThemeManager"),
    u"pyrevit": (u"HOST_APP",),
}


class _AnyMeta(type):
    def __getattr__(cls, name):
        if name.startswith(u"__"):
            raise AttributeError(name)
        return _make_stub(name)


_Any = _AnyMeta(str(u"_Any"), (object,), {})


def _make_stub(name):
    def init(self, *args, **kwargs):
        return None

    def call(self, *args, **kwargs):
        return _make_stub(name)()

    body = {u"__init__": init, u"__call__": call}
    return _AnyMeta(str(name), (_Any,), body)


class _StubModule(types.ModuleType):
    def __init__(self, name, declared):
        types.ModuleType.__init__(self, name)
        self._declared = set(declared)
        self.__path__ = []

    def __getattr__(self, name):
        if name in self._declared:
            value = _make_stub(name)
            setattr(self, name, value)
            return value
        raise AttributeError(
            u"'{0}' is not in the namespace '{1}'".format(name, self.__name__))


class _Clr(types.ModuleType):
    def AddReference(self, name):
        return None

    def GetClrType(self, thing):
        return thing


def install_stubs():
    saved = dict(sys.modules)
    for name, declared in NAMESPACES.items():
        sys.modules[name] = _StubModule(name, declared)
    # Parent namespaces have to exist for 'import a.b' to work at all, but
    # they declare nothing of their own beyond their children.
    for name in list(NAMESPACES.keys()):
        parts = name.split(u".")
        for depth in range(1, len(parts)):
            parent = u".".join(parts[:depth])
            if parent not in sys.modules:
                sys.modules[parent] = _StubModule(parent, ())
            child = parts[depth]
            setattr(sys.modules[parent], child,
                    sys.modules.get(u".".join(parts[:depth + 1])))
            sys.modules[parent]._declared.add(child)
    sys.modules[u"clr"] = _Clr(u"clr")
    return saved


def restore_stubs(saved):
    for name in list(sys.modules.keys()):
        if name not in saved:
            del sys.modules[name]
    sys.modules.update(saved)


# =========================================================================
# Reading the folder
# =========================================================================

def strip_comments(text):
    u"""Blank out # comments and keep everything else, including string
    bodies.  Any rule that looks INSIDE a string needs this rather than
    code_only."""
    out = []
    for line in text.splitlines():
        quote = None
        cut = len(line)
        index = 0
        while index < len(line):
            char = line[index]
            if quote:
                if char == u"\\":
                    index += 2
                    continue
                if char == quote:
                    quote = None
            elif char in u"\"'":
                quote = char
            elif char == u"#":
                cut = index
                break
            index += 1
        out.append(line[:cut])
    return u"\n".join(out)


class Ctx(object):
    def __init__(self, root):
        self.root = root
        self._text = {}

    def path(self, name):
        return os.path.join(self.root, name)

    def text(self, name):
        if name not in self._text:
            handle = open(self.path(name), u"rb")
            try:
                self._text[name] = handle.read().decode(u"utf-8", u"ignore")
            finally:
                handle.close()
        return self._text[name]

    def module_text(self, name):
        return self.text(name + u".py")

    def all_xaml(self):
        return list(LAYOUT_XAML) + [THEME_XAML]

    def python_files(self):
        return [m + u".py" for m in MODULES] + [u"script.py"]


def code_only(text):
    u"""Blank out comments and string bodies, replacing every removed
    character with a space.  Joining the pieces WITHOUT preserving the
    spacing silently disables rules like the System.Uri one, because the
    tokens either side run together."""
    out = list(text)
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char == u"#":
            while index < length and text[index] != u"\n":
                out[index] = u" "
                index += 1
            continue
        if char in u"\"'":
            quote = char
            triple = text[index:index + 3] in (quote * 3,)
            size = 3 if triple else 1
            index += size
            while index < length:
                if text[index] == u"\\":
                    out[index] = u" "
                    if index + 1 < length:
                        out[index + 1] = u" "
                    index += 2
                    continue
                if text[index:index + size] == quote * size:
                    index += size
                    break
                if text[index] != u"\n":
                    out[index] = u" "
                index += 1
            continue
        index += 1
    return u"".join(out)


# =========================================================================
# The rules
# =========================================================================

def rule_xaml_is_xml(ctx):
    problems = []
    for name in ctx.all_xaml():
        try:
            xml.dom.minidom.parseString(ctx.text(name).encode(u"utf-8"))
        except Exception as error:
            problems.append(u"{0} will not parse as XML: {1}".format(name, error))
    return problems


def rule_no_hyphen_banner(ctx):
    u"""XML forbids -- inside a comment.  Draw banners with =, not -."""
    problems = []
    for name in ctx.all_xaml():
        for match in re.finditer(u"<!--(.*?)-->", ctx.text(name), re.S):
            if u"--" in match.group(1):
                problems.append(
                    u"{0} has a comment containing a double hyphen".format(name))
    return problems


def rule_no_static_resource(ctx):
    u"""Theme.xaml is merged in AFTER the layout is parsed, so a
    StaticResource in a layout fails at load."""
    problems = []
    for name in LAYOUT_XAML:
        if u"StaticResource" in ctx.text(name):
            problems.append(u"{0} uses StaticResource".format(name))
    return problems


def _dynamic_keys(text):
    return set(re.findall(u"\\{DynamicResource\\s+([A-Za-z0-9_]+)\\}", text))


def _theme_keys(ctx):
    return set(re.findall(u"x:Key=\"([A-Za-z0-9_]+)\"", ctx.text(THEME_XAML)))


def rule_dynamic_keys_exist(ctx):
    problems = []
    known = _theme_keys(ctx)
    for name in ctx.all_xaml():
        for key in _dynamic_keys(ctx.text(name)):
            if key not in known:
                problems.append(
                    u"{0} asks for '{1}', which Theme.xaml does not "
                    u"define".format(name, key))
    for name in ctx.python_files():
        for key in re.findall(
                u"SetResourceReference\\([^,]+,\\s*u?[\"']([A-Za-z0-9_]+)[\"']",
                strip_comments(ctx.text(name))):
            if key not in known:
                problems.append(
                    u"{0} sets a resource reference to '{1}', which "
                    u"Theme.xaml does not define".format(name, key))
    return problems


def rule_no_duplicate_xkeys(ctx):
    problems = []
    seen = set()
    for key in re.findall(u"x:Key=\"([A-Za-z0-9_]+)\"", ctx.text(THEME_XAML)):
        if key in seen:
            problems.append(u"Theme.xaml defines '{0}' twice".format(key))
        seen.add(key)
    return problems


def _x_names(ctx):
    out = set()
    for name in ctx.all_xaml():
        out.update(re.findall(u"x:Name=\"([A-Za-z0-9_]+)\"", ctx.text(name)))
    return out


def rule_findname_has_xname(ctx):
    u"""The rule has to follow the alias too - the code does
    find = self.window.FindName and then find(u'X')."""
    problems = []
    known = _x_names(ctx)
    pattern = u"(?:FindName|\\bfind)\\s*\\(\\s*u?[\"']([A-Za-z0-9_]+)[\"']\\s*\\)"
    for name in ctx.python_files():
        # NOT code_only: that blanks string bodies, and the name being
        # looked up IS a string body. This rule matched nothing at all
        # until that was noticed on the bench.
        for wanted in re.findall(pattern, strip_comments(ctx.text(name))):
            if wanted not in known:
                problems.append(
                    u"{0} looks up '{1}', which no XAML declares as "
                    u"x:Name".format(name, wanted))
    return problems


def rule_no_banned_constructs(ctx):
    problems = []
    for name in ctx.python_files():
        body = code_only(ctx.text(name))
        for number, line in enumerate(body.splitlines(), 1):
            if re.search(u"\\bprint\\s*\\(", line):
                problems.append(u"{0}:{1} uses print".format(name, number))
            if re.search(u"\\bf[\"']", line):
                problems.append(u"{0}:{1} uses an f-string".format(name, number))
            if u".IntegerValue" in line and name != u"fet_core.py":
                problems.append(
                    u"{0}:{1} touches .IntegerValue outside eid_value".format(
                        name, number))
            if re.search(u"System\\s*\\.\\s*Uri", line) or \
                    re.search(u"from\\s+System\\s+import\\s+[^\\n]*\\bUri\\b", line):
                problems.append(u"{0}:{1} uses System.Uri".format(name, number))
    return problems


def rule_clr_first(ctx):
    u"""An IronPython engine can only see a .NET namespace once its
    assembly is referenced, and pyRevit does not preload WPF into every
    engine.  Every module reaching into System.* or Autodesk.* has to
    import fet_clr first."""
    problems = []
    reach = re.compile(
        u"^\\s*(?:from|import)\\s+(System|Autodesk|Microsoft)\\b")
    for name in ctx.python_files():
        if name in (u"fet_clr.py", u"script.py"):
            continue
        clr_line = None
        first_reach = None
        for number, line in enumerate(code_only(ctx.text(name)).splitlines(), 1):
            if re.match(u"^\\s*import\\s+fet_clr\\b", line):
                if clr_line is None:
                    clr_line = number
            elif reach.match(line):
                if first_reach is None:
                    first_reach = number
        if first_reach is None:
            continue
        if clr_line is None:
            problems.append(
                u"{0} reaches into a .NET namespace without importing "
                u"fet_clr".format(name))
        elif clr_line > first_reach:
            problems.append(
                u"{0} imports fet_clr at line {1}, after reaching into a "
                u".NET namespace at line {2}".format(name, clr_line, first_reach))
    return problems


def rule_no_duplicate_definitions(ctx):
    u"""Python silently keeps the last one."""
    problems = []
    for name in ctx.python_files():
        body = code_only(ctx.text(name))
        scopes = {}
        stack = [(-1, u"<module>")]
        for line in body.splitlines():
            match = re.match(u"^(\\s*)(def|class)\\s+([A-Za-z_][A-Za-z0-9_]*)",
                             line)
            if not match:
                continue
            indent = len(match.group(1).expandtabs(4))
            while stack and stack[-1][0] >= indent:
                stack.pop()
            scope = stack[-1][1] if stack else u"<module>"
            key = (scope, match.group(3))
            if key in scopes:
                problems.append(
                    u"{0} defines {1} twice in {2}".format(
                        name, match.group(3), scope))
            scopes[key] = True
            stack.append((indent, match.group(3)))
    return problems


def rule_palette_parity(ctx):
    problems = []
    text = ctx.text(u"theme.py")
    palettes = {}
    for block in re.finditer(
            u"^(DARK|LIGHT)\\s*=\\s*\\{(.*?)^\\}", text, re.S | re.M):
        palettes[block.group(1)] = set(
            re.findall(u"u[\"']([A-Za-z0-9_]+)[\"']\\s*:", block.group(2)))
    if len(palettes) != 2:
        return [u"theme.py does not carry both palettes"]
    missing = palettes[u"DARK"] ^ palettes[u"LIGHT"]
    for key in sorted(missing):
        problems.append(u"'{0}' is in one palette and not the other".format(key))
    known = _theme_keys(ctx)
    for key in sorted(palettes[u"DARK"]):
        if key not in known:
            problems.append(
                u"the palette carries '{0}' and Theme.xaml has no brush for "
                u"it".format(key))
    return problems


def rule_modules_load(ctx):
    problems = []
    saved = install_stubs()
    added = sys.path[:]
    sys.path.insert(0, ctx.root)
    try:
        for name in MODULES:
            for key in list(sys.modules.keys()):
                if key in MODULES:
                    del sys.modules[key]
            try:
                __import__(name)
            except Exception as error:
                problems.append(u"{0} will not load: {1}: {2}".format(
                    name, type(error).__name__, error))
    finally:
        sys.path[:] = added
        restore_stubs(saved)
    return problems


def rule_no_baseline_alignment(ctx):
    problems = []
    for name in ctx.all_xaml():
        if u"VerticalAlignment=\"Baseline\"" in ctx.text(name):
            problems.append(
                u"{0} uses VerticalAlignment=Baseline, which WPF does not "
                u"support".format(name))
    return problems


ENUMS = {
    u"HorizontalAlignment": (u"Left", u"Center", u"Right", u"Stretch"),
    u"VerticalAlignment": (u"Top", u"Center", u"Bottom", u"Stretch"),
    u"Visibility": (u"Visible", u"Hidden", u"Collapsed"),
    u"Orientation": (u"Horizontal", u"Vertical"),
    u"TextTrimming": (u"None", u"CharacterEllipsis", u"WordEllipsis"),
    u"TextWrapping": (u"NoWrap", u"Wrap", u"WrapWithOverflow"),
    u"WindowStyle": (u"None", u"SingleBorderWindow", u"ThreeDBorderWindow",
                     u"ToolWindow"),
    u"ResizeMode": (u"NoResize", u"CanMinimize", u"CanResize",
                    u"CanResizeWithGrip"),
    u"SizeToContent": (u"Manual", u"Width", u"Height", u"WidthAndHeight"),
    u"ClickMode": (u"Release", u"Press", u"Hover"),
    u"PopupAnimation": (u"None", u"Fade", u"Slide", u"Scroll"),
}


def rule_xaml_enum_attributes(ctx):
    u"""WPF raises on a bad enum value when the element is realised, which
    also surfaces as a dead window rather than an error."""
    problems = []
    for name in ctx.all_xaml():
        text = ctx.text(name)
        for attribute, allowed in ENUMS.items():
            for value in re.findall(
                    u"(?<![A-Za-z.])" + attribute + u"=\"([A-Za-z]+)\"", text):
                if value not in allowed:
                    problems.append(
                        u"{0} sets {1}=\"{2}\", which is not a member".format(
                            name, attribute, value))
    return problems


def rule_changelog_has_version(ctx):
    text = ctx.module_text(u"fet_core")
    match = re.search(u"__version__\\s*=\\s*u?[\"']([0-9.]+)[\"']", text)
    if not match:
        return [u"fet_core.py carries no __version__"]
    version = match.group(1)
    if version not in ctx.text(u"CHANGELOG.md"):
        return [u"CHANGELOG.md has no entry for {0}".format(version)]
    return []


def rule_script_is_thin(ctx):
    u"""A tool that is one big script has no runtime left to report its own
    import failure."""
    problems = []
    allowed = set([u"os", u"sys", u"traceback"])
    for number, line in enumerate(code_only(ctx.text(u"script.py")).splitlines(), 1):
        if line[:1] in (u" ", u"\t"):
            continue
        match = re.match(u"^(?:import|from)\\s+([A-Za-z_][A-Za-z0-9_.]*)", line)
        if match and match.group(1).split(u".")[0] not in allowed:
            problems.append(
                u"script.py:{0} imports {1} at module level".format(
                    number, match.group(1)))
    return problems


def _walk_symbols(table, module_names, name, problems):
    for symbol in table.get_symbols():
        if not symbol.is_global() or symbol.is_assigned():
            continue
        wanted = symbol.get_name()
        if wanted in module_names or wanted in ALLOWED_GLOBALS:
            continue
        if wanted in dir(__builtins__) or hasattr(
                sys.modules[u"builtins"], wanted):
            continue
        problems.append(u"{0}: {1} reaches for '{2}', which the module does "
                        u"not define".format(name, table.get_name(), wanted))
    for child in table.get_children():
        _walk_symbols(child, module_names, name, problems)


def rule_undefined_globals(ctx):
    problems = []
    for name in ctx.python_files():
        text = ctx.text(name)
        try:
            top = symtable.symtable(text, name, u"exec")
        except SyntaxError as error:
            problems.append(u"{0} will not compile: {1}".format(name, error))
            continue
        module_names = set(top.get_identifiers())
        for child in top.get_children():
            _walk_symbols(child, module_names, name, problems)
    return problems


def rule_no_dispatcher_in_ops(ctx):
    u"""Never pump the dispatcher inside a transaction.  Keeping every
    Dispatcher call out of the module that owns the transactions is the
    cheap way to make that true and to keep it true."""
    problems = []
    body = code_only(ctx.module_text(u"fet_ops"))
    if u"Dispatcher" in body:
        problems.append(u"fet_ops.py touches the Dispatcher, which must never "
                        u"happen between Transaction.Start and Commit")
    return problems


def rule_no_identity_on_sender(ctx):
    u"""'is' compares Python object identity, not .NET object identity.  A
    handler that compares its sender that way never fires, and nothing
    about it looks wrong.  Compare by role - a Tag, a name - instead."""
    problems = []
    pattern = re.compile(u"\\bsender\\s+is\\b|\\bis\\s+sender\\b")
    for name in ctx.python_files():
        for number, line in enumerate(code_only(ctx.text(name)).splitlines(), 1):
            if pattern.search(line):
                problems.append(
                    u"{0}:{1} compares sender with 'is'".format(name, number))
    return problems


def _function_body(text, name):
    u"""The lines of a top level def, by indentation."""
    lines = text.splitlines()
    out = []
    inside = False
    for line in lines:
        if line.startswith(u"def {0}(".format(name)):
            inside = True
            continue
        if inside:
            if line.strip() and not line.startswith((u" ", u"\t")):
                break
            out.append(line)
    return u"\n".join(out)


def rule_copy_runs_outside_a_transaction(ctx):
    u"""CopyElements between two documents opens its OWN transaction, so
    calling it inside one is answered with 'Copying one or more elements
    failed' - a message that says nothing about the real cause.  So does
    AppearanceAssetEditScope.  Checked in every function that reaches for
    either, not just the one that did it first."""
    problems = []
    body = code_only(ctx.module_text(u"fet_ops"))
    functions = re.findall(u"^def ([A-Za-z_][A-Za-z0-9_]*)\\(", body, re.M)
    checked = 0
    calls = (u"ElementTransformUtils.CopyElements", u"_copy_many(",
             u"_copy_returning_id(", u"AppearanceAssetEditScope(")
    for name in functions:
        text = _function_body(body, name)
        for call in calls:
            at = text.find(call)
            if at < 0:
                continue
            checked += 1
            before = text[:at]
            # A transaction that was started AND committed before the copy
            # is fine - what matters is whether one is still open.
            if before.rfind(u"_start(") > before.rfind(u"_commit("):
                problems.append(
                    u"{0} has a transaction open at a cross document "
                    u"copy".format(name))
    if not checked:
        problems.append(u"fet_ops.py has no cross document copy to check")
    return problems


def rule_flex_is_rolled_back(ctx):
    u"""The one thing worse than a flex run that finds no faults is one
    that leaves the family sitting on a test value.  The run has to open a
    TransactionGroup and roll it back in a finally."""
    problems = []
    body = _function_body(code_only(ctx.module_text(u"fet_ops")), u"run_flex")
    if not body.strip():
        return [u"fet_ops.py has no run_flex to check"]
    if u"TransactionGroup(" not in body:
        problems.append(u"run_flex does not open a transaction group")
    if u"finally:" not in body:
        problems.append(u"run_flex has no finally, so a failure half way "
                        u"through would leave the family changed")
    at = body.find(u"finally:")
    if at >= 0 and u"RollBack()" not in body[at:]:
        problems.append(u"run_flex does not roll the group back in its "
                        u"finally")
    return problems


RULES = (
    (u"xaml parses as XML", rule_xaml_is_xml),
    (u"no double hyphen in an XML comment", rule_no_hyphen_banner),
    (u"no StaticResource in a layout", rule_no_static_resource),
    (u"every DynamicResource key exists", rule_dynamic_keys_exist),
    (u"no duplicate x:Key", rule_no_duplicate_xkeys),
    (u"every FindName has an x:Name", rule_findname_has_xname),
    (u"no banned constructs", rule_no_banned_constructs),
    (u"fet_clr is imported first", rule_clr_first),
    (u"nothing is defined twice", rule_no_duplicate_definitions),
    (u"both palettes match Theme.xaml", rule_palette_parity),
    (u"every module loads against the stub API", rule_modules_load),
    (u"no VerticalAlignment Baseline", rule_no_baseline_alignment),
    (u"every XAML enum value is a member", rule_xaml_enum_attributes),
    (u"the changelog carries this version", rule_changelog_has_version),
    (u"script.py stays a thin loader", rule_script_is_thin),
    (u"no undefined globals", rule_undefined_globals),
    (u"no Dispatcher in the write module", rule_no_dispatcher_in_ops),
    (u"no identity comparison on a handler sender",
     rule_no_identity_on_sender),
    (u"the cross document copy runs outside a transaction",
     rule_copy_runs_outside_a_transaction),
    (u"the flex run is always rolled back", rule_flex_is_rolled_back),
)


def run(root=HERE, quiet=False):
    ctx = Ctx(root)
    failures = 0
    for title, rule in RULES:
        try:
            problems = rule(ctx)
        except Exception as error:
            problems = [u"the rule itself threw: {0}: {1}".format(
                type(error).__name__, error)]
        if problems:
            failures += 1
            if not quiet:
                sys.stdout.write(u"FAIL  {0}\n".format(title))
                for line in problems:
                    sys.stdout.write(u"        {0}\n".format(line))
        elif not quiet:
            sys.stdout.write(u"ok    {0}\n".format(title))
    return failures


def run_one(root, rule):
    ctx = Ctx(root)
    try:
        return rule(ctx)
    except Exception as error:
        return [u"the rule itself threw: {0}".format(error)]


# =========================================================================
# The selftest
# =========================================================================

def _patch(root, name, old, new):
    path = os.path.join(root, name)
    handle = open(path, u"rb")
    try:
        text = handle.read().decode(u"utf-8")
    finally:
        handle.close()
    if old not in text:
        raise AssertionError(u"the selftest could not find its anchor in "
                             u"{0}".format(name))
    handle = open(path, u"wb")
    try:
        handle.write(text.replace(old, new, 1).encode(u"utf-8"))
    finally:
        handle.close()


def _append(root, name, text):
    path = os.path.join(root, name)
    handle = open(path, u"ab")
    try:
        handle.write(text.encode(u"utf-8"))
    finally:
        handle.close()


def _break_changelog(root):
    u"""Take the CURRENT version out of the changelog, whatever it is.  A
    breakage written against a hardcoded version stops breaking anything
    the moment the version moves on."""
    ctx = Ctx(root)
    match = re.search(u"__version__\\s*=\\s*u?[\"']([0-9.]+)[\"']",
                      ctx.module_text(u"fet_core"))
    if not match:
        raise AssertionError(u"the selftest could not find the version")
    _patch(root, u"CHANGELOG.md", match.group(1), u"0.0.0-not-this")


BREAKAGES = (
    (rule_xaml_is_xml,
     lambda root: _patch(root, u"FetPrompt.xaml", u"</Window>",
                         u"<Grid></Window>")),
    (rule_no_hyphen_banner,
     lambda root: _patch(root, u"Theme.xaml", u"<!-- ==",
                         u"<!-- -- panel -- ==")),
    (rule_no_static_resource,
     lambda root: _patch(root, u"FamilyEditorTools.xaml",
                         u"{DynamicResource WindowBg}",
                         u"{StaticResource WindowBg}")),
    (rule_dynamic_keys_exist,
     lambda root: _patch(root, u"FetPrompt.xaml",
                         u"{DynamicResource BlueBrush}",
                         u"{DynamicResource NoSuchBrush}")),
    (rule_no_duplicate_xkeys,
     lambda root: _patch(root, u"Theme.xaml",
                         u"<sys:Double x:Key=\"FieldHeight\">32</sys:Double>",
                         u"<SolidColorBrush x:Key=\"BlueBrush\" Color=\"#FF0000\"/>"
                         u"<sys:Double x:Key=\"FieldHeight\">32</sys:Double>")),
    (rule_findname_has_xname,
     lambda root: _append(root, u"fet_window.py",
                          u"\n\ndef _bench_break(self):\n"
                          u"    return self.find(u\"NotThere\")\n")),
    (rule_no_banned_constructs,
     lambda root: _append(root, u"fet_model.py",
                          u"\n\ndef _bench_break(eid):\n"
                          u"    return eid.IntegerValue\n")),
    (rule_clr_first,
     lambda root: _patch(root, u"theme.py",
                         u"import fet_clr  # noqa: F401  - assemblies first, always\n",
                         u"")),
    (rule_no_duplicate_definitions,
     lambda root: _append(root, u"fet_core.py",
                          u"\n\ndef natural_key(text):\n    return text\n")),
    (rule_palette_parity,
     lambda root: _patch(root, u"theme.py", u"    u\"CloseHoverBrush\": u\"#B4322E\",\n",
                         u"")),
    (rule_modules_load,
     lambda root: _patch(root, u"fet_ops.py", u"from Autodesk.Revit.DB import (Color",
                         u"from Autodesk.Revit.UI import Color\nfrom Autodesk.Revit.DB import (")),
    (rule_no_baseline_alignment,
     lambda root: _patch(root, u"FetPrompt.xaml", u"TextWrapping=\"Wrap\"",
                         u"TextWrapping=\"Wrap\" VerticalAlignment=\"Baseline\"")),
    (rule_xaml_enum_attributes,
     lambda root: _patch(root, u"FamilyEditorTools.xaml",
                         u"ResizeMode=\"NoResize\"", u"ResizeMode=\"Nope\"")),
    (rule_changelog_has_version, lambda root: _break_changelog(root)),
    (rule_script_is_thin,
     lambda root: _patch(root, u"script.py", u"import traceback",
                         u"import traceback\nimport fet_window")),
    (rule_undefined_globals,
     lambda root: _append(root, u"fet_core.py",
                          u"\n\ndef _bench_break():\n"
                          u"    return no_such_name_at_all\n")),
    (rule_no_dispatcher_in_ops,
     lambda root: _append(root, u"fet_ops.py",
                          u"\n\ndef _bench_break(window):\n"
                          u"    return window.Dispatcher\n")),
    (rule_no_identity_on_sender,
     lambda root: _append(root, u"fet_window.py",
                          u"\n\ndef _bench_break(self, sender):\n"
                          u"    return self.window is sender\n")),
    (rule_flex_is_rolled_back,
     lambda root: _patch(root, u"fet_ops.py",
                         u"    finally:\n        try:\n            group.RollBack()",
                         u"    finally:\n        try:\n            pass")),
    (rule_copy_runs_outside_a_transaction,
     lambda root: _patch(root, u"fet_ops.py",
                         u"    already = fet_model.existing_names(doc, kind)\n"
                         u"    if kind == u\"linestyle\":",
                         u"    transaction = _start(doc, u\"break\")\n"
                         u"    already = fet_model.existing_names(doc, kind)\n"
                         u"    if kind == u\"linestyle\":")),
)


def selftest():
    caught = 0
    missed = []
    for rule, breakage in BREAKAGES:
        title = [t for t, r in RULES if r is rule][0]
        root = tempfile.mkdtemp(prefix=u"fetcheck")
        try:
            for item in os.listdir(HERE):
                source = os.path.join(HERE, item)
                if os.path.isfile(source):
                    shutil.copy2(source, os.path.join(root, item))
            breakage(root)
            problems = run_one(root, rule)
            if problems:
                caught += 1
                sys.stdout.write(u"caught  {0}\n".format(title))
            else:
                missed.append(title)
                sys.stdout.write(u"MISSED  {0}\n".format(title))
        finally:
            shutil.rmtree(root, ignore_errors=True)
    sys.stdout.write(u"\n{0} of {1} rules caught their own breakage\n".format(
        caught, len(BREAKAGES)))
    return len(missed)


if __name__ == u"__main__":
    if u"--selftest" in sys.argv:
        sys.exit(1 if selftest() else 0)
    count = run()
    sys.stdout.write(u"\n{0}\n".format(
        u"All rules pass" if not count else
        u"{0} rules failed".format(count)))
    sys.exit(1 if count else 0)
