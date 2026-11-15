# -*- coding: utf-8 -*-
"""Bench check for RevoBIM Sheet Manager.

Runs under plain CPython from the pushbutton folder:

    python import_check.py
    python import_check.py --selftest

It loads every shipped module against a stub Revit and .NET API that declares
each name in the namespace the real API puts it in, so a mis-namespaced import
fails here instead of showing up in Revit as a blank white pyRevit window with
no traceback in it.

--selftest breaks each rule on purpose and confirms the check catches it. A rule
nobody has tested is a rule that does not work.
"""

import io
import os
import re
import shutil
import sys
import symtable
import tempfile
import traceback
import types
import xml.dom.minidom

HERE = os.path.dirname(os.path.abspath(__file__))

MODULES = [
    "shtm_clr", "shtm_core", "theme", "shtm_plan", "shtm_rows", "shtm_batch",
    "shtm_edit",
    "shtm_xlsx", "shtm_ui", "shtm_model", "shtm_grid", "shtm_dup",
    "shtm_vt", "shtm_duplicate", "shtm_settings", "shtm_edits", "shtm_window",
]

LAYOUTS = ["SheetManager.xaml", "ShtmDuplicate.xaml", "ShtmSettings.xaml",
           "ShtmPrompt.xaml", "ShtmEdit.xaml", "ShtmTemplate.xaml"]
THEME_FILE = "Theme.xaml"

WINDOW_MODULES = ["shtm_window", "shtm_duplicate", "shtm_settings", "shtm_ui",
                  "shtm_edits", "shtm_vt"]

# ====================== the stub API ======================

NAMESPACES = {
    "System": ["TimeSpan", "Enum", "Int64", "Int32", "AppDomain", "String",
               "Object", "Exception", "Action", "DateTime"],
    "System.IO": ["StringReader", "MemoryStream", "File", "Path", "FileMode",
                  "StreamReader"],
    "System.IO.Compression": ["ZipArchive", "ZipArchiveMode"],
    "System.Text": ["Encoding"],
    "System.Xml": ["XmlReader", "XmlDocument", "XmlNamespaceManager"],
    "System.Collections.Generic": ["List"],
    "System.Drawing": ["Point", "Rectangle"],
    "System.Windows": [
        "Clipboard", "TextWrapping", "SystemParameters", "Thickness", "GridLength", "GridUnitType",
        "Visibility", "VerticalAlignment", "HorizontalAlignment",
        "TextTrimming", "FrameworkElementFactory", "DataTemplate",
        "FrameworkElement", "CornerRadius", "PresentationSource", "FontWeights",
        "Window", "ResourceDictionary", "WindowState", "PropertyPath",
        "DependencyProperty", "RoutedEventArgs", "SizeToContent", "Point", "Size",
        "LogicalTreeHelper",
    ],
    "System.Windows.Markup": ["XamlReader"],
    "System.Windows.Controls": [
        "Grid", "StackPanel", "TextBlock", "TextBox", "Button", "CheckBox",
        "RadioButton", "ComboBox", "ComboBoxItem", "ListBox", "ListBoxItem",
        "Border", "ScrollViewer", "Orientation", "ColumnDefinition",
        "RowDefinition", "DataGrid", "DataGridRow", "DataGridCell",
        "DataGridTemplateColumn", "DataGridLength", "DataGridLengthUnitType",
        "ContextMenu", "MenuItem", "Separator",
        "Control", "ContentControl", "Image",
        "ScrollBarVisibility", "GridSplitter",
    ],
    "System.Windows.Controls.Primitives": ["Popup", "PlacementMode", "Thumb",
                                           "ToggleButton", "RepeatButton"],
    "System.Windows.Data": ["Binding", "IValueConverter", "BindingMode"],
    "System.Windows.Media": ["Brushes", "BrushConverter", "SolidColorBrush",
                             "VisualTreeHelper", "Colors", "FontFamily",
                             "RotateTransform"],
    "System.Windows.Documents": ["Run", "LineBreak", "Bold", "TextElement"],
    "System.Windows.Media.Imaging": ["BitmapImage", "BitmapCacheOption"],
    "System.Windows.Input": ["Key", "Cursors", "Keyboard", "ModifierKeys", "Mouse",
                             "MouseButtonState"],
    "System.Windows.Threading": ["DispatcherTimer", "DispatcherPriority"],
    "System.Windows.Interop": ["WindowInteropHelper"],
    "System.Windows.Forms": ["Screen"],
    "Microsoft.Win32": ["Registry", "OpenFileDialog", "SaveFileDialog"],
    "Autodesk.Revit.DB": [
        "FilteredElementCollector", "ViewSheet", "Viewport",
        "ScheduleSheetInstance", "View", "ViewSchedule", "ViewType",
        "ElementId", "BuiltInParameter", "BuiltInCategory",
        "BrowserOrganization", "LabelUtils", "StorageType", "WorksharingUtils",
        "CheckoutStatus", "ElementTransformUtils", "Transaction",
        "TransactionGroup", "TransactionStatus", "Element",
        "ViewDuplicateOption", "IFailuresPreprocessor",
        "FailureProcessingResult", "FailureSeverity", "FailureMessage",
        "XYZ", "Line", "CurveLoop", "Parameter",
        "FamilyInstance", "Revision", "PanelScheduleView",
        "RevisionCloud", "Transform", "CopyPasteOptions", "SpecTypeId",
        "TextNote", "IndependentTag", "FilledRegion", "CurveElement", "CurveElementType",
        "SubTransaction",
        "RevitLinkInstance", "LinkElementId", "UV",
    ],
    "Autodesk.Revit.UI": [
        "IExternalEventHandler", "ExternalEvent", "ExternalEventRequest",
        "TaskDialog", "TaskDialogCommonButtons", "TaskDialogResult",
        "UIThemeManager", "UITheme", "UIApplication", "UIDocument",
    ],
}


class _Any(object):
    """Stands in for a .NET type. Members are not policed - namespaces are."""

    def __init__(self, *args, **kwargs):
        pass

    def __call__(self, *args, **kwargs):
        return _Any()

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _Any()


class _AnyMeta(type):
    def __getattr__(cls, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _Any()

    def __call__(cls, *args, **kwargs):
        return _Any()


def _make_type(name):
    return _AnyMeta(str(name), (object,), {})


class _StubModule(types.ModuleType):
    """Only the declared names exist. Anything else is an ImportError, which is
    exactly what the real engine does when a name is in another namespace."""

    def __init__(self, name, declared):
        types.ModuleType.__init__(self, name)
        self.__declared = set(declared)
        for entry in declared:
            setattr(self, entry, _make_type(entry))

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        raise ImportError(
            "'{0}' is not in the namespace '{1}'".format(name, self.__name__))


class _ClrStub(types.ModuleType):
    def __init__(self):
        types.ModuleType.__init__(self, "clr")

    def AddReference(self, name):
        return None

    def AddReferenceByName(self, name):
        return None


def install_stubs():
    sys.modules["clr"] = _ClrStub()
    packages = set()
    for namespace in NAMESPACES:
        parts = namespace.split(".")
        for depth in range(1, len(parts)):
            packages.add(".".join(parts[:depth]))
    for package in sorted(packages):
        if package not in NAMESPACES:
            sys.modules[package] = _StubModule(package, [])
    for namespace in sorted(NAMESPACES):
        sys.modules[namespace] = _StubModule(namespace, NAMESPACES[namespace])
    # a parent namespace has to hand back its children
    for namespace in sorted(NAMESPACES):
        parts = namespace.split(".")
        if len(parts) > 1:
            parent = sys.modules.get(".".join(parts[:-1]))
            if parent is not None:
                object.__setattr__(parent, parts[-1], sys.modules[namespace])
    revit = sys.modules.get("Autodesk.Revit")
    if revit is not None:
        object.__setattr__(revit, "DB", sys.modules["Autodesk.Revit.DB"])
        object.__setattr__(revit, "UI", sys.modules["Autodesk.Revit.UI"])


def clear_stubs():
    for name in list(sys.modules):
        if name == "clr" or name.split(".")[0] in ("System", "Autodesk", "Microsoft"):
            sys.modules.pop(name, None)


# ====================== reading ======================

def read(path):
    handle = io.open(path, encoding="utf-8")
    try:
        return handle.read()
    finally:
        handle.close()


def source_files(folder):
    return [f for f in MODULES if os.path.isfile(os.path.join(folder, f + ".py"))]


def code_only(text):
    """The source with comments and string bodies blanked out.

    A rule that scans raw text fires on its own explanation - the comment saying
    'no System.Uri' is not a use of System.Uri.
    """
    import tokenize
    try:
        lines = text.splitlines(True)
        out = list(lines)
        readline = io.StringIO(text).readline
        for token in tokenize.generate_tokens(readline):
            kind, value, start, end, _line = token
            if kind not in (tokenize.COMMENT, tokenize.STRING):
                continue
            for row in range(start[0], end[0] + 1):
                index = row - 1
                if index >= len(out):
                    continue
                line = out[index]
                begin = start[1] if row == start[0] else 0
                finish = end[1] if row == end[0] else len(line.rstrip("\n"))
                out[index] = (line[:begin] + " " * max(0, finish - begin)
                              + line[finish:])
        return "".join(out)
    except Exception:
        return text


# ====================== the rules ======================

class Result(object):
    def __init__(self):
        self.problems = []

    def fail(self, rule, message):
        self.problems.append(u"[{0}] {1}".format(rule, message))

    @property
    def ok(self):
        return not self.problems


def rule_xaml_parses(folder, result):
    """A layout that will not parse is the quiet blank window. XML forbids --
    inside a comment, so banners are drawn with = not -."""
    for name in LAYOUTS + [THEME_FILE]:
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            result.fail("xaml-parses", u"{0} is missing".format(name))
            continue
        try:
            xml.dom.minidom.parse(path)
        except Exception as exc:
            result.fail("xaml-parses", u"{0}: {1}".format(name, exc))


def rule_clr_first(folder, result):
    """No module reaching into System.* or Autodesk.* without importing
    shtm_clr first, or importing it too late in the file."""
    for name in source_files(folder):
        if name == "shtm_clr":
            continue
        text = read(os.path.join(folder, name + ".py"))
        lines = text.splitlines()
        clr_line = None
        dotnet_line = None
        for index, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if re.match(r"^import\s+shtm_clr\b", stripped):
                if clr_line is None:
                    clr_line = index
            if re.match(r"^(from|import)\s+(System|Autodesk|Microsoft)\b", stripped):
                if dotnet_line is None:
                    dotnet_line = index
        if dotnet_line is None:
            continue
        if clr_line is None:
            result.fail("clr-first",
                        u"{0} reaches into .NET without importing shtm_clr".format(name))
        elif clr_line > dotnet_line:
            result.fail("clr-first",
                        u"{0} imports shtm_clr after line {1}".format(name, dotnet_line + 1))


def rule_no_staticresource(folder, result):
    for name in LAYOUTS:
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            continue
        if "StaticResource" in read(path):
            result.fail("no-staticresource",
                        u"{0} uses StaticResource - Theme.xaml is merged in "
                        u"after the layout is parsed".format(name))


def theme_keys(folder):
    text = read(os.path.join(folder, THEME_FILE))
    return set(re.findall(r'x:Key="([^"]+)"', text))


def rule_dynamic_keys(folder, result):
    """Theme.xaml is checked against itself too - it asks for its own keys, and
    a typo there is the same dead window as a typo in a layout."""
    known = theme_keys(folder)
    for name in LAYOUTS + [THEME_FILE]:
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            continue
        for key in re.findall(r"\{DynamicResource\s+([^}]+)\}", read(path)):
            key = key.strip()
            if key not in known:
                result.fail("dynamic-key",
                            u"{0} asks for '{1}', which Theme.xaml does not "
                            u"define".format(name, key))


SUBCLASSES = {
    "Button": ["ButtonBase", "ContentControl", "Control", "FrameworkElement"],
    "RadioButton": ["ToggleButton", "ButtonBase", "Control"],
    "CheckBox": ["ToggleButton", "ButtonBase", "Control"],
    "RepeatButton": ["ButtonBase", "Control"],
    "ToggleButton": ["ButtonBase", "Control"],
    "TextBox": ["Control"],
    "ComboBox": ["Control"],
    "ComboBoxItem": ["Control"],
    "ListBox": ["Control"],
    "ListBoxItem": ["Control"],
    "DataGrid": ["Control"],
    "Thumb": ["Control"],
    "GridSplitter": ["Thumb", "Control"],
    "TextBlock": ["FrameworkElement"],
}


def rule_style_targets(folder, result):
    """WPF raises when a style is applied, not when it is declared, so a style
    on the wrong element also surfaces as a dead window."""
    theme_text = read(os.path.join(folder, THEME_FILE))
    targets = {}
    for key, target in re.findall(
            r'x:Key="([^"]+)"\s+TargetType="([^"]+)"', theme_text):
        targets[key] = target.split(":")[-1]
    for name in LAYOUTS + [THEME_FILE]:
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            continue
        for tag, key in re.findall(
                r"<([A-Za-z]+)[^>]*?Style=\"\{DynamicResource\s+([^}]+)\}\"",
                read(path)):
            key = key.strip()
            wanted = targets.get(key)
            if wanted is None:
                continue
            if tag == wanted:
                continue
            if wanted in SUBCLASSES.get(tag, []):
                continue
            result.fail("style-target",
                        u"{0}: style '{1}' targets {2} but is on a {3}".format(
                            name, key, wanted, tag))


def rule_findname(folder, result):
    """No FindName without a matching x:Name. The code aliases FindName as
    self.find, so both spellings are looked for - a rule that only matched the
    literal call was doing nothing at all in an earlier tool."""
    names = set()
    for layout in LAYOUTS:
        path = os.path.join(folder, layout)
        if os.path.isfile(path):
            names |= set(re.findall(r'x:Name="([^"]+)"', read(path)))
    asked = []
    for module in source_files(folder):
        text = read(os.path.join(folder, module + ".py"))
        for match in re.findall(r'(?:FindName|self\.find)\(\s*[\'"]([^\'"]+)[\'"]',
                                text):
            asked.append((module, match))
    for module, name in asked:
        if name not in names:
            result.fail("findname",
                        u"{0} asks for '{1}', which no layout declares".format(
                            module, name))


def rule_resource_reference_keys(folder, result):
    known = theme_keys(folder)
    patterns = [
        r"SetResourceReference\([^,]+,\s*[\'\"]([^\'\"]+)[\'\"]",
        r"styled\([^,]+,\s*[\'\"]([^\'\"]+)[\'\"]",
        r"text_block\([^,]+,\s*[\'\"]([^\'\"]+)[\'\"]",
        r"button\([^,]+,\s*[\'\"]([^\'\"]+)[\'\"]",
        r"text_box\([^,]+,[^,]+,\s*[\'\"]([^\'\"]+)[\'\"]",
    ]
    for module in source_files(folder):
        text = read(os.path.join(folder, module + ".py"))
        for pattern in patterns:
            for key in re.findall(pattern, text):
                if key not in known:
                    result.fail("resource-key",
                                u"{0} asks for '{1}', which Theme.xaml does not "
                                u"define".format(module, key))


def rule_palettes_cover_theme(folder, result):
    """Every brush Theme.xaml declares has to be in both palettes, or a switch
    to light leaves half the window dark."""
    text = read(os.path.join(folder, THEME_FILE))
    brushes = set(re.findall(r'<SolidColorBrush\s+x:Key="([^"]+)"', text))
    source = read(os.path.join(folder, "theme.py"))
    for palette in ("DARK", "LIGHT"):
        block = re.search(palette + r"\s*=\s*\{(.*?)\n\}", source, re.S)
        if block is None:
            result.fail("palette", u"theme.py has no {0} palette".format(palette))
            continue
        keys = set(re.findall(r'"([^"]+)"\s*:', block.group(1)))
        missing = brushes - keys
        if missing:
            result.fail("palette",
                        u"{0} is missing {1}".format(palette, ", ".join(sorted(missing))))


def rule_no_fstrings(folder, result):
    for module in source_files(folder):
        text = read(os.path.join(folder, module + ".py"))
        text = _blank_comments(text)
        for index, line in enumerate(text.splitlines()):
            if re.search(r"(?<![A-Za-z0-9_])f[\'\"]", line) and "{" in line:
                result.fail("no-fstrings",
                            u"{0} line {1} looks like an f-string".format(
                                module, index + 1))


def _blank_comments(text):
    lines = []
    for line in text.splitlines():
        hash_at = line.find("#")
        if hash_at >= 0 and line[:hash_at].count('"') % 2 == 0:
            line = line[:hash_at]
        lines.append(line)
    return "\n".join(lines)


def rule_no_print(folder, result):
    for module in source_files(folder):
        text = read(os.path.join(folder, module + ".py"))
        for index, line in enumerate(text.splitlines()):
            if re.match(r"^\s*print\s*[\(\s]", line):
                result.fail("no-print",
                            u"{0} line {1} uses print".format(module, index + 1))


def rule_no_bare_integervalue(folder, result):
    """.IntegerValue was removed in Revit 2026. It is allowed only inside the
    guarded eid_value helper."""
    for module in source_files(folder):
        text = read(os.path.join(folder, module + ".py"))
        for index, line in enumerate(text.splitlines()):
            if ".IntegerValue" not in line:
                continue
            if module == "shtm_core" and _inside_eid_value(text, index):
                continue
            result.fail("integervalue",
                        u"{0} line {1} touches .IntegerValue outside "
                        u"eid_value".format(module, index + 1))


def _inside_eid_value(text, line_index):
    lines = text.splitlines()
    for cursor in range(line_index, -1, -1):
        stripped = lines[cursor]
        if stripped.startswith("def "):
            return stripped.startswith("def eid_value")
    return False


def rule_no_system_uri(folder, result):
    """System.Uri moved assemblies: importing it throws at module load on
    Revit 2025 and later, killing the script before any of it runs."""
    for module in source_files(folder):
        text = code_only(read(os.path.join(folder, module + ".py")))
        if re.search(r"(from\s+System\s+import\s+[^\n]*\bUri\b|System\.Uri|UriSource)",
                     text):
            result.fail("system-uri", u"{0} reaches for System.Uri".format(module))


def rule_grid_lengths(folder, result):
    """A DataGrid column measures in DataGridLength; a Grid's own rows and
    columns measure in GridLength. The two read identically and are not
    interchangeable - Revit answers the wrong one with
    'TypeError: expected DataGridLength, got GridLength' at the moment the
    window is built, which lands in the staged loader as a failure to show the
    window rather than anything to do with the grid."""
    for module in source_files(folder):
        text = _blank_comments(read(os.path.join(folder, module + ".py")))
        for index, line in enumerate(text.splitlines()):
            if re.search(r"\bcolumn\w*\.Width\s*=\s*GridLength\(", line):
                result.fail("grid-length",
                            u"{0} line {1} gives a DataGrid column a "
                            u"GridLength".format(module, index + 1))
            if re.search(r"\b(definition|row|col)(?!umn)\w*\.(Width|Height)\s*=\s*"
                         r"DataGridLength\(", line):
                result.fail("grid-length",
                            u"{0} line {1} gives a Grid definition a "
                            u"DataGridLength".format(module, index + 1))


def rule_no_duplicate_methods(folder, result):
    """No method or function defined twice. Python silently keeps the last, so
    a block rewrite that leaves the old copy behind is invisible until the
    wrong one runs."""
    import ast
    for module in source_files(folder):
        path = os.path.join(folder, module + ".py")
        try:
            tree = ast.parse(read(path), path)
        except Exception as exc:
            result.fail("duplicate-def", u"{0} would not parse: {1}".format(
                module, exc))
            continue
        for node in ast.walk(tree):
            body = getattr(node, "body", None)
            if not isinstance(body, list):
                continue
            seen = {}
            for entry in body:
                if not isinstance(entry, (ast.FunctionDef,)):
                    continue
                if entry.name in seen:
                    where = getattr(node, "name", u"module level")
                    result.fail("duplicate-def",
                                u"{0}: '{1}' is defined twice in {2} (lines "
                                u"{3} and {4})".format(module, entry.name, where,
                                                       seen[entry.name],
                                                       entry.lineno))
                seen[entry.name] = entry.lineno


def rule_unicode_literals(folder, result):
    """No non-ASCII outside a u'' literal. IronPython 2.7 fails on an em dash
    in a plain str literal, and the failure is at module load."""
    for module in source_files(folder):
        path = os.path.join(folder, module + ".py")
        text = read(path)
        for index, line in enumerate(text.splitlines()):
            if all(ord(ch) < 128 for ch in line):
                continue
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            # every non-ASCII run has to sit inside a u"" or u'' literal
            for match in re.finditer(r"[^\x00-\x7F]+", line):
                before = line[:match.start()]
                if re.search(r"u[\"\'][^\"\']*$", before):
                    continue
                result.fail("unicode",
                            u"{0} line {1} has non-ASCII outside a u'' "
                            u"literal".format(module, index + 1))
                break


def rule_wiring_is_guarded(folder, result):
    """The window's handler wiring must go through the guarded step list, not
    a bare chain of `self.find(...).Click += ...`.

    A single chain is one bad line away from a window that opens, draws its
    rows and answers nothing, with no traceback anywhere - which is what 1.4.1
    shipped. Every hook-up either sits in `_hook`, which guards each one, or in
    a step the loop in `_wire` catches for.
    """
    path = os.path.join(folder, "shtm_window.py")
    if not os.path.isfile(path):
        return
    text = _blank_comments(read(path))
    inside = False
    depth = 0
    for index, line in enumerate(text.splitlines()):
        stripped = line.strip()
        if stripped.startswith("def _wire(self)"):
            inside = True
            continue
        if inside and stripped.startswith("def ") and not line.startswith("        "):
            inside = False
        if not inside:
            continue
        # a hook inside its own try/except is guarded, which is the point
        if stripped.startswith("try:"):
            depth = 1
            continue
        if depth and stripped.startswith("except"):
            depth = 0
            continue
        if depth:
            continue
        if re.search(r"self\.find\([^)]*\)\.\w+\s*\+=", stripped):
            result.fail("wiring",
                        u"shtm_window line {0} hooks a handler directly in "
                        u"_wire - it belongs in a guarded step".format(index + 1))


def rule_cross_module_names(folder, result):
    """Every `shtm_x.name` one shipped module reaches for exists at the top
    level of shtm_x.

    The globals rule cannot see this: `shtm_duplicate.DuplicateDialog` is an
    attribute, not a free name, so when the dialog class was replaced the
    window's call to it would have passed every other rule and failed only
    in Revit, at the moment Duplicate was pressed.
    """
    import ast
    names = {}
    for module in source_files(folder):
        try:
            tree = ast.parse(read(os.path.join(folder, module + ".py")))
        except Exception:
            continue
        top = set()
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                top.add(node.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    for leaf in ast.walk(target):
                        if isinstance(leaf, ast.Name):
                            top.add(leaf.id)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    top.add((alias.asname or alias.name).split(".")[0])
            elif isinstance(node, (ast.If, ast.Try)):
                for leaf in ast.walk(node):
                    if isinstance(leaf, (ast.FunctionDef, ast.ClassDef)):
                        top.add(leaf.name)
                    elif isinstance(leaf, ast.Name) and isinstance(leaf.ctx, ast.Store):
                        top.add(leaf.id)
                    elif isinstance(leaf, (ast.Import, ast.ImportFrom)):
                        for alias in leaf.names:
                            top.add((alias.asname or alias.name).split(".")[0])
        names[module] = top
    for module in source_files(folder):
        text = code_only(read(os.path.join(folder, module + ".py")))
        for index, line in enumerate(text.splitlines()):
            for target, attribute in re.findall(
                    r"\b(shtm_[a-z_]+|theme)\.([A-Za-z_][A-Za-z0-9_]*)", line):
                if target not in names or target == module:
                    continue
                if attribute in names[target]:
                    continue
                result.fail("cross-module",
                            u"{0} line {1} reaches for {2}.{3}, which {2} does "
                            u"not define".format(module, index + 1, target,
                                                 attribute))


def rule_converter_knows_its_column(folder, result):
    """Every CellConverter is built with its column index.

    The converter decides from the index what a group heading shows in each
    column - the label in the first, "[ + ] Expand" in the second, nothing in
    the rest. Built without it, the index defaults to 0 and every column of a
    heading repeats the label. That shipped in 1.4.1 because the patch that
    added the argument matched nothing and nothing said so.
    """
    path = os.path.join(folder, "shtm_grid.py")
    if not os.path.isfile(path):
        return
    text = code_only(read(path))
    # constructions only - not the class statement that declares it
    calls = re.findall(r"(?<!class )\bCellConverter\(([^()]*)\)", text)
    if not calls:
        result.fail("converter", u"shtm_grid never builds a CellConverter")
    for arguments in calls:
        if len([a for a in arguments.split(",") if a.strip()]) < 4:
            result.fail("converter",
                        u"CellConverter({0}) is not told which column it is "
                        u"in".format(arguments.strip()))


def rule_jobs_use_their_document(folder, result):
    """No external event writes to whichever document happens to be active.

    The windows are modeless and outlive a switch of project; a job's element
    ids belong to the document it was built in. Every Execute that writes
    goes through shtm_ui.job_document.
    """
    for module in source_files(folder):
        text = code_only(read(os.path.join(folder, module + ".py")))
        inside_helper = False
        for index, line in enumerate(text.splitlines()):
            # the helper's own fallback, for a job built with no document, is
            # the one place this is allowed
            if line.startswith("def "):
                inside_helper = line.startswith("def job_document(")
            if inside_helper:
                continue
            if "uiapp.ActiveUIDocument.Document" in line:
                result.fail("job-document",
                            u"{0} line {1} writes to the active document rather "
                            u"than the job's - use shtm_ui.job_document".format(
                                module, index + 1))


def rule_placeholders_stay_inside(folder, result):
    """Every text box placeholder trims, and the box clips what it holds.

    A placeholder TextBlock with no trimming, in a Grid that does not clip,
    draws past the edge of a narrow box - under the picker's caret and into
    the next cell. That is how "(leave each sheet's own)" ran across the
    table of sets in 1.5.0.
    """
    text = read(os.path.join(folder, THEME_FILE))
    holders = re.findall(r'<TextBlock x:Name="ph"[^>]*>', text)
    if not holders:
        result.fail("placeholder", u"Theme.xaml has no text box placeholders")
    for holder in holders:
        if 'TextTrimming="CharacterEllipsis"' not in holder:
            result.fail("placeholder", u"a text box placeholder does not trim")
    hosts = re.findall(r'<Grid[^>]*>\s*<ScrollViewer x:Name="PART_ContentHost"', text)
    for host in hosts:
        if 'ClipToBounds="True"' not in host:
            result.fail("placeholder", u"a text box does not clip its placeholder")


def rule_builder_reads_live_settings(folder, result):
    """The Duplicate window reads its settings through _settings(), never a
    copy of its own.

    It is modeless and outlives a trip to Settings; the main window replaces
    its settings when Settings is applied, so a copy kept by the builder is
    stale from that moment - and the builder saves when it creates, which put
    the stale copy back over what had just been applied.
    """
    path = os.path.join(folder, "shtm_duplicate.py")
    if not os.path.isfile(path):
        return
    allowed = ("self.settings = settings", "return self.settings")
    text = code_only(read(path))
    for index, line in enumerate(text.splitlines()):
        if "self.settings" not in line:
            continue
        if line.strip() in allowed:
            continue
        result.fail("live-settings",
                    u"shtm_duplicate line {0} reads self.settings - use "
                    u"self._settings()".format(index + 1))


ROUTED_HANDLERS = [
    # (module, method) - handlers on events that bubble or tunnel through
    # controls with event sources of their own inside them
    ("shtm_duplicate", "_sync_header"),
    ("shtm_duplicate", "_cell_key"),
]


def rule_routed_handlers_check_source(folder, result):
    """A handler on a routed event that inner controls also raise must check
    where the event came from.

    ScrollChanged bubbles up from the scroll viewer inside every text box, so
    typing past a cell's width moved the table's heading; PreviewKeyDown
    tunnels through a cell for the search box in its dropdown, so Enter there
    jumped down a row. Neither throws - they just misbehave.
    """
    for module, method in ROUTED_HANDLERS:
        path = os.path.join(folder, module + ".py")
        if not os.path.isfile(path):
            continue
        text = code_only(read(path))
        match = re.search(r"\n    def " + method + r"\(.*?(?=\n    def |\n    @|\Z)",
                          text, re.S)
        if match is None:
            result.fail("routed", u"{0}.{1} is missing".format(module, method))
            continue
        if "OriginalSource" not in match.group(0):
            result.fail("routed",
                        u"{0}.{1} does not check the event's OriginalSource".format(
                            module, method))


def rule_globals_exist(folder, result):
    """Every global name a function reaches for exists in its module - the rule
    that catches a function deleted by a block rewrite."""
    import builtins as builtin_module
    for module in source_files(folder):
        path = os.path.join(folder, module + ".py")
        text = read(path)
        try:
            table = symtable.symtable(text, path, "exec")
        except Exception as exc:
            result.fail("globals", u"{0} would not parse: {1}".format(module, exc))
            continue
        top = set(table.get_identifiers())
        loaded = sys.modules.get(module)
        known = set(dir(loaded)) if loaded is not None else set()
        known |= top | set(dir(builtin_module))
        for child in _walk(table):
            for symbol in child.get_symbols():
                if not symbol.is_global():
                    continue
                if symbol.get_name() in known:
                    continue
                result.fail("globals",
                            u"{0}.{1} reaches for '{2}', which is not in the "
                            u"module".format(module, child.get_name(),
                                             symbol.get_name()))


def _walk(table):
    for child in table.get_children():
        yield child
        for grandchild in _walk(child):
            yield grandchild


def rule_egg_wired(folder, result):
    """The easter egg is wired to the RevoBIM logo in every window the tool
    opens: three slow clicks, the same as every other tool."""
    rule = _shared_egg_rule(folder) if folder == HERE else None
    if rule is not None:
        # the shared rule reads the tool it is run from, so it is only asked
        # when this really is that folder - the selftest works on a copy
        problems = []
        try:
            returned = rule(problems)
            for problem in (returned or []) + problems:
                result.fail("egg", problem)
        except TypeError:
            problems = []
            try:
                for problem in (rule() or []) + problems:
                    result.fail("egg", problem)
            except Exception as exc:
                result.fail("egg", u"the shared egg rule threw: {0}".format(exc))
        except Exception as exc:
            result.fail("egg", u"the shared egg rule threw: {0}".format(exc))
    for module in WINDOW_MODULES:
        path = os.path.join(folder, module + ".py")
        if not os.path.isfile(path):
            continue
        text = _blank_comments(read(path))
        if "attach_egg" not in text:
            result.fail("egg", u"{0} does not wire the easter egg".format(module))
    ui_text = _blank_comments(read(os.path.join(folder, "shtm_ui.py")))
    if "egg_hook" not in ui_text:
        result.fail("egg", u"shtm_ui does not reach the shared egg module")
    # the egg's own entry points, spelled the way the shared package spells
    # them. Guessing at plausible names is how PacMan shipped not working in
    # 1.1.0 - launch() existed and was being called with the game key as its
    # first positional argument, which is host_window.
    if "attach_to_window" not in ui_text:
        result.fail("egg", u"shtm_ui does not call egg_hook.attach_to_window")
    if "egg_hook" in ui_text and "launch" not in ui_text:
        result.fail("egg", u"shtm_ui has no way to open the game directly - "
                           u"egg_hook.launch is the one without the clicks")
    if "egg_auto" not in ui_text or "sys.path" not in ui_text:
        result.fail("egg", u"shtm_ui does not put the extension's lib on "
                           u"sys.path and arm egg_auto the way startup.py "
                           u"does, so the egg is only reachable if something "
                           u"else did it first")
    if "game_key" not in ui_text:
        result.fail("egg", u"nothing asks egg_hook.launch for a game by key, "
                           u"so PacMan cannot be the one that opens")
    for layout in LAYOUTS:
        path = os.path.join(folder, layout)
        if os.path.isfile(path) and 'x:Name="LogoHost"' not in read(path):
            result.fail("egg",
                        u"{0} has no LogoHost for the three slow clicks".format(layout))


def _shared_egg_rule(folder):
    """The canonical rule lives with the egg itself, in the extension's lib.
    Import it where it is available so every tool is held to the same rule."""
    root = folder
    for _ in range(6):
        root = os.path.dirname(root)
        candidate = os.path.join(root, "lib")
        if os.path.isdir(os.path.join(candidate, "revobim")):
            if candidate not in sys.path:
                sys.path.insert(0, candidate)
            try:
                from revobim.egg import egg_rule
            except Exception:
                return None
            for name in ("check", "check_tool", "rule_easter_egg_wired"):
                found = getattr(egg_rule, name, None)
                if found is not None:
                    return found
            return None
    return None


def rule_modules_import(folder, result):
    install_stubs()
    if folder not in sys.path:
        sys.path.insert(0, folder)
    for module in MODULES:
        if not os.path.isfile(os.path.join(folder, module + ".py")):
            continue
        sys.modules.pop(module, None)
    for module in MODULES:
        if not os.path.isfile(os.path.join(folder, module + ".py")):
            continue
        try:
            __import__(module)
        except Exception:
            result.fail("import", u"{0}:\n{1}".format(module, traceback.format_exc()))


def rule_column_helper_takes_every_width(folder, result):
    """shtm_ui._column is handed None, numbers and strings across the tool. In
    1.9.0 it took only strings, threw on the template editor's None, and the
    Edit button did nothing - the error went to the log. Run it, against the
    stubs, with every kind of width."""
    install_stubs()
    if folder not in sys.path:
        sys.path.insert(0, folder)
    try:
        module = __import__("shtm_ui")
    except Exception:
        return   # the import rule reports it
    for width in (None, 240.0, 70, "auto", "*", "2*", "120"):
        try:
            module._column(width)
        except Exception as exc:
            result.fail("columns", u"_column({0!r}) throws: {1}".format(width, exc))


def rule_every_window_shrinks(folder, result):
    """Every window carries the shrink-to-taskbar button in its header, ahead
    of close, on the shared style - and the chrome turns it into a drawer."""
    for name in LAYOUTS:
        dom = xml.dom.minidom.parse(os.path.join(folder, name))
        found = [e for e in dom.getElementsByTagName("Button")
                 if e.getAttribute("x:Name") == "ShrinkBtn"]
        if len(found) != 1:
            result.fail("shrink", u"{0} has no shrink-to-taskbar button".format(name))
            continue
        button = found[0]
        if "Btn.Shrink" not in button.getAttribute("Style"):
            result.fail("shrink", u"{0}: ShrinkBtn is not on Btn.Shrink".format(name))
        node, in_header = button.parentNode, False
        while node is not None and getattr(node, "getAttribute", None):
            if node.getAttribute("x:Name") == "HeaderBar":
                in_header = True
                break
            node = node.parentNode
        if not in_header:
            result.fail("shrink", u"{0}: ShrinkBtn is not in the header".format(name))
        text = read(os.path.join(folder, name))
        if text.find('x:Name="ShrinkBtn"') > text.find('x:Name="CloseBtn"'):
            result.fail("shrink", u"{0}: ShrinkBtn comes after close".format(name))
    ui = code_only(read(os.path.join(folder, "shtm_ui.py")))
    chrome = ui[ui.find("class Chrome"):ui.find("def work_area")]
    if "Drawer(" not in chrome:
        result.fail("shrink", u"Chrome no longer builds the drawer")
    # a double click on the top or bottom edge stretches to the screen's height
    for name in LAYOUTS:
        text = read(os.path.join(folder, name))
        for grip in ("GripT", "GripB"):
            if 'x:Name="{0}"'.format(grip) not in text:
                result.fail("edges", u"{0} has no {1} to double-click".format(name, grip))
    if "_edge_pressed" not in chrome or "PreviewMouseLeftButtonDown" not in chrome:
        result.fail("edges", u"a double click on the top or bottom edge does nothing")


def rule_drawer_is_safe(folder, result):
    """The silent failures of a drawer, each held: no Storyboard anywhere,
    animations released, MinHeight and SizeToContent relaxed, the body pinned,
    the grips parked."""
    for name in os.listdir(folder):
        if name.endswith(".py") and name not in ("import_check.py", "bench_logic.py") \
                or name.endswith(".xaml"):
            text = read(os.path.join(folder, name))
            if name.endswith(".py"):
                text = code_only(text)
            if "Storyboard" in text:
                result.fail("drawer", u"{0} uses a Storyboard".format(name))
    ui = code_only(read(os.path.join(folder, "shtm_ui.py")))
    drawer = ui[ui.find("class Drawer"):]
    for needle, why in [
            ("BeginAnimation(prop, None)", "Top and Height are not released"),
            ("MinHeight = 0", "MinHeight is not relaxed for the slide"),
            ("SizeToContent.Manual", "SizeToContent is not relaxed for the slide"),
            ("root.Height = root.ActualHeight", "the body is not pinned"),
            ("IsHitTestVisible = live", "the grips are not parked")]:
        if needle not in drawer:
            result.fail("drawer", why)
    # a window brought back while still sliding down has to stop that slide,
    # or it carries on and parks the window after all (found in review, 1.8.0)
    unpark = drawer[drawer.find("def _unpark"):drawer.find("def _landed_up")]
    if "self._stop()" not in unpark:
        result.fail("drawer", u"_unpark does not stop a slide already running")
    open_now = drawer[drawer.find("def open_now"):drawer.find("def _bar_height")]
    if "self.sliding" not in open_now:
        result.fail("drawer", u"open_now ignores a window still sliding down")


def rule_owners_brought_back(folder, result):
    """A window given an owner brings that owner back first if it is shrunk
    to the taskbar - centred on a parked bar it would land half off screen."""
    for module in source_files(folder):
        lines = read(os.path.join(folder, module + ".py")).split("\n")
        for index, line in enumerate(lines):
            if not re.match(r"\s+self\.window\.Owner = self\.owner\s*$", line):
                continue
            before = lines[index - 1] if index else u""
            if "bring_back(self.owner)" not in before:
                result.fail("owner", u"{0}.py line {1}: owner set without "
                                     u"bring_back".format(module, index + 1))


def rule_shrink_stays_live(folder, result):
    """The shrink button is the one control wanted while a run is going, and
    touches nothing but the window's own geometry: only the chrome names it."""
    for module in source_files(folder):
        if module == "shtm_ui":
            continue
        if "ShrinkBtn" in read(os.path.join(folder, module + ".py")):
            result.fail("shrink", u"{0}.py reaches for ShrinkBtn".format(module))


def rule_revit_dark_palette(folder, result):
    """Dark is Revit's own dark theme, and Theme.xaml's defaults carry the same
    values, or a window shows the old greys before the palette lands."""
    source = read(os.path.join(folder, "theme.py"))
    block = re.search(r"DARK\s*=\s*\{(.*?)\n\}", source, re.S)
    if block is None:
        result.fail("palette", u"theme.py has no DARK palette")
        return
    dark = dict(re.findall(r'"(\w+)":\s*"(#[0-9A-Fa-f]{6})"', block.group(1)))
    for key, wanted in [("WindowBg", "#3C4454"), ("FieldBg", "#2D3441"),
                        ("BarBg", "#222933"), ("HeaderBg", "#323C48"),
                        ("SelectionBrush", "#3A7392")]:
        if dark.get(key, "").upper() != wanted:
            result.fail("palette", u"DARK {0} is {1}, Revit's is {2}".format(
                key, dark.get(key), wanted))
    xaml = read(os.path.join(folder, THEME_FILE))
    for key, value in re.findall(r'<SolidColorBrush\s+x:Key="(\w+)"\s+Color="(#[0-9A-Fa-f]{6})"',
                                 xaml):
        if key in dark and dark[key].upper() != value.upper():
            result.fail("palette", u"Theme.xaml {0} is {1} but DARK says {2}".format(
                key, value, dark[key]))
    text = code_only(source)
    canvas, ui = source.find('"CurrentCanvasTheme"'), source.find('"CurrentTheme"')
    if canvas < 0 or ui < 0 or canvas > ui:
        result.fail("palette", u"Revit's canvas theme is not read first")


def rule_new_views_start_clean(folder, result):
    """A new sheet or view never carries revisions (1.9.0, forced): every
    copied view has its clouds taken off and every new sheet its revisions
    cleared, and there is no option that brings them back."""
    engine = code_only(read(os.path.join(folder, "shtm_dup.py")))
    one_view = engine[engine.find("def _one_view"):engine.find("def _view_chunk")]
    if "self._strip_clouds(new_view)" not in one_view:
        result.fail("revisions", u"copied views keep their revision clouds")
    clean = engine[engine.find("def _step_clean"):engine.find("def _step_views")]
    if "SetAdditionalRevisionIds(NetList[ElementId]())" not in clean \
            or "self._step_clean)" not in engine:
        result.fail("revisions", u"new sheets are not cleared of revisions")
    # each clean-up is rolled back on its own, never with the view it is on
    for needle in ("lambda: self._strip_clouds(new_view)",
                   "lambda: self._clean_view(new_view, options)",
                   "lambda: self._tag_rooms(new_view)"):
        if needle not in one_view:
            result.fail("cleaning", u"a view clean-up runs outside its sub-transaction")
    if "SubTransaction(self.doc)" not in engine:
        result.fail("cleaning", u"there is no sub-transaction to isolate a clean-up")
    if 'options.get("copy_revisions"' in engine:
        result.fail("revisions", u"an option can still carry revisions across")
    owned = engine[engine.find("def _owned"):engine.find("def _delete")]
    if "OwnerViewId" not in owned:
        result.fail("cleaning", u"cleaning would take elements other views own")
    clean = engine[engine.find("def _clean_view"):engine.find("def _tag_rooms")]
    if "CurveElementType.DetailCurve" not in clean:
        result.fail("cleaning", u"removing lines would take room separation and "
                                u"area boundary lines too")


def rule_events_made_in_context(folder, result):
    """ExternalEvent.Create is called only while Revit runs the command - in
    the main window's constructor - never from a modeless window's click."""
    for module in source_files(folder):
        if module == "shtm_window":
            continue
        if "ExternalEvent.Create" in code_only(read(os.path.join(folder, module + ".py"))):
            result.fail("events", u"{0}.py creates an external event".format(module))


def _locals_read_first(function):
    """Names a function reads on a line before the first line that sets them -
    the UnboundLocalError a stub run never reaches. Nested functions are
    their own scope and are left out of the outer one's count."""
    import ast
    params = set(a.arg for a in function.args.args)
    if function.args.vararg:
        params.add(function.args.vararg.arg)
    if function.args.kwarg:
        params.add(function.args.kwarg.arg)
    stores, loads = {}, {}
    declared = set()

    def walk(node):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.Lambda, ast.ClassDef)):
                if isinstance(child, (ast.FunctionDef, ast.ClassDef)):
                    stores.setdefault(child.name, child.lineno)
                continue
            if isinstance(child, (ast.ListComp, ast.SetComp, ast.DictComp,
                                  ast.GeneratorExp)):
                # a comprehension names its loop variable after using it
                continue
            if isinstance(child, (ast.Global, ast.Nonlocal)):
                declared.update(child.names)
            if isinstance(child, ast.Name):
                table = stores if isinstance(child.ctx, (ast.Store, ast.Del)) else loads
                table[child.id] = min(table.get(child.id, child.lineno), child.lineno)
            if isinstance(child, ast.ExceptHandler) and child.name:
                stores.setdefault(child.name, child.lineno)
            if isinstance(child, (ast.Import, ast.ImportFrom)):
                for alias in child.names:
                    name = (alias.asname or alias.name).split(".")[0]
                    stores[name] = min(stores.get(name, child.lineno), child.lineno)
            walk(child)

    walk(function)
    late = []
    for name in stores:
        if name in params or name in declared or name not in loads:
            continue
        if loads[name] < stores[name]:
            late.append((name, loads[name]))
    return late


def rule_no_read_before_set(folder, result):
    """A local read before it is set throws UnboundLocalError in Revit and,
    inside ui_safe, only lands in the log - 1.9.0's set rows did exactly that
    and stopped the Duplicate window refreshing."""
    import ast
    for module in source_files(folder):
        try:
            tree = ast.parse(read(os.path.join(folder, module + ".py")))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                for name, line in _locals_read_first(node):
                    result.fail("unbound", u"{0}.py line {1}: {2}() reads '{3}' "
                                           u"before setting it".format(
                                               module, line, node.name, name))


RULES = [
    ("every .xaml parses as XML", rule_xaml_parses),
    ("shtm_clr is imported before any .NET name", rule_clr_first),
    ("no StaticResource in a layout", rule_no_staticresource),
    ("every DynamicResource key exists in Theme.xaml", rule_dynamic_keys),
    ("no style applied to an element its TargetType does not match", rule_style_targets),
    ("no FindName without an x:Name", rule_findname),
    ("every SetResourceReference key exists", rule_resource_reference_keys),
    ("both palettes cover every brush", rule_palettes_cover_theme),
    ("no f-strings", rule_no_fstrings),
    ("no print statements", rule_no_print),
    ("no bare .IntegerValue", rule_no_bare_integervalue),
    ("no System.Uri", rule_no_system_uri),
    ("a DataGrid column is measured in DataGridLength", rule_grid_lengths),
    ("every module loads against the stub API", rule_modules_import),
    ("every global a function reaches for exists", rule_globals_exist),
    ("no method defined twice", rule_no_duplicate_methods),
    ("every module.name reached for exists in that module", rule_cross_module_names),
    ("the cell converter is told its column", rule_converter_knows_its_column),
    ("text box placeholders stay inside the box", rule_placeholders_stay_inside),
    ("the Duplicate window reads live settings", rule_builder_reads_live_settings),
    ("routed-event handlers check where the event came from",
     rule_routed_handlers_check_source),
    ("every job writes to its own document", rule_jobs_use_their_document),
    ("the window's wiring is guarded step by step", rule_wiring_is_guarded),
    ("no non-ASCII outside a u'' literal", rule_unicode_literals),
    ("the easter egg is wired to the logo", rule_egg_wired),
    ("every window shrinks to the taskbar", rule_every_window_shrinks),
    ("the drawer cannot strand a window", rule_drawer_is_safe),
    ("an owner is brought back before a window is given to it",
     rule_owners_brought_back),
    ("the shrink button stays live during a run", rule_shrink_stays_live),
    ("dark is Revit's own dark theme, canvas first", rule_revit_dark_palette),
    ("new sheets and views start with no revisions", rule_new_views_start_clean),
    ("external events are made only in the command's context",
     rule_events_made_in_context),
    ("no local is read before it is set", rule_no_read_before_set),
    ("the column helper takes every width", rule_column_helper_takes_every_width),
]


def check(folder=HERE, quiet=False):
    result = Result()
    for _label, rule in RULES:
        try:
            rule(folder, result)
        except Exception:
            result.fail("bench", u"{0} threw:\n{1}".format(
                rule.__name__, traceback.format_exc()))
    if not quiet:
        for problem in result.problems:
            sys.stdout.write(problem + "\n")
        sys.stdout.write("\n{0} rule(s) checked, {1} problem(s)\n".format(
            len(RULES), len(result.problems)))
    return result


# ====================== self test ======================

BREAKAGES = [
    ("every .xaml parses as XML",
     "SheetManager.xaml", lambda t: t.replace("<Grid>", "<!-- -- --><Grid>", 1)),
    ("shtm_clr is imported before any .NET name",
     "shtm_grid.py", lambda t: t.replace("import shtm_clr", "# import shtm_clr", 1)),
    ("no StaticResource in a layout",
     "SheetManager.xaml", lambda t: t.replace("{DynamicResource WindowBg}",
                                              "{StaticResource WindowBg}", 1)),
    ("every DynamicResource key exists in Theme.xaml",
     "SheetManager.xaml", lambda t: t.replace("{DynamicResource WindowBg}",
                                              "{DynamicResource NoSuchBrush}", 1)),
    ("no style applied to an element its TargetType does not match",
     "SheetManager.xaml", lambda t: t.replace('Style="{DynamicResource Lbl.Muted}"',
                                              'Style="{DynamicResource Btn.Flat}"', 1)),
    ("no FindName without an x:Name",
     "shtm_window.py", lambda t: t.replace('self.find("StatusText")',
                                           'self.find("StatusTxt")', 1)),
    ("every SetResourceReference key exists",
     "shtm_grid.py", lambda t: t.replace('"EdgeBrush"', '"NoSuchBrush"', 1)),
    ("both palettes cover every brush",
     "theme.py", lambda t: t.replace('    "GroupRowBg": "#DFE4EA",\n', "", 1)),
    ("no f-strings",
     "shtm_core.py", lambda t: t.replace("def as_bool(value):",
                                         "def as_bool(value):\n    _ = f\"{value}\"",
                                         1)),
    ("no print statements",
     "shtm_core.py", lambda t: t.replace("def as_bool(value):",
                                         "def as_bool(value):\n    print(value)", 1)),
    ("no bare .IntegerValue",
     "shtm_model.py", lambda t: t.replace("def element_name(element):",
                                          "def element_name(element):\n"
                                          "    _ = element.Id.IntegerValue", 1)),
    ("no System.Uri",
     "shtm_ui.py", lambda t: t.replace("from System import TimeSpan",
                                       "from System import TimeSpan, Uri", 1)),
    ("a DataGrid column is measured in DataGridLength",
     "shtm_grid.py", lambda t: t.replace(
         "column.Width = DataGridLength(float(widths[key]))",
         "column.Width = GridLength(float(widths[key]))", 1)),
    ("every module loads against the stub API",
     "shtm_model.py", lambda t: t.replace(
         "from Autodesk.Revit.DB import (",
         "from Autodesk.Revit.DB import TaskDialog\nfrom Autodesk.Revit.DB import (", 1)),
    ("every global a function reaches for exists",
     "shtm_core.py", lambda t: t.replace("def as_bool(value):",
                                         "def as_bool(value):\n"
                                         "    _ = no_such_helper()", 1)),
    ("the window's wiring is guarded step by step",
     "shtm_window.py", lambda t: t.replace(
         "        grid = self.find(\"SheetGrid\")\n        # Diagnostics first",
         "        self.find(\"RefreshBtn\").Click += ui_safe(self._settings)\n"
         "        grid = self.find(\"SheetGrid\")\n        # Diagnostics first", 1)),
    ("every module.name reached for exists in that module",
     "shtm_window.py", lambda t: t.replace(
         "shtm_duplicate.BuilderWindow(", "shtm_duplicate.DuplicateDialog(", 1)),
    ("no method defined twice",
     "shtm_core.py", lambda t: t.replace(
         "def as_bool(value):",
         "def as_bool(value):\n    return False\n\n\ndef as_bool(value):", 1)),
    ("routed-event handlers check where the event came from",
     "shtm_duplicate.py", lambda t: t.replace(
         "        if not sender.Equals(event.OriginalSource):\n            return\n",
         "", 1)),
    ("routed-event handlers check where the event came from",
     "shtm_duplicate.py", lambda t: t.replace(
         "if box is None or not box.Equals(event.OriginalSource):",
         "if box is None:", 1)),
    ("the Duplicate window reads live settings",
     "shtm_duplicate.py", lambda t: t.replace(
         "        settings = self._settings()\n        finds = self.finds()",
         "        settings = self.settings\n        finds = self.finds()", 1)),
    ("text box placeholders stay inside the box",
     "Theme.xaml", lambda t: t.replace(
         'IsHitTestVisible="False" TextTrimming="CharacterEllipsis"',
         'IsHitTestVisible="False"', 1)),
    ("text box placeholders stay inside the box",
     "Theme.xaml", lambda t: t.replace('<Grid ClipToBounds="True">', '<Grid>', 1)),
    ("the cell converter is told its column",
     "shtm_grid.py", lambda t: t.replace(
         "CellConverter(key, first, store, column_index)",
         "CellConverter(key, first, store)", 1)),
    ("every job writes to its own document",
     "shtm_edits.py", lambda t: t.replace(
         "document, refused = shtm_ui.job_document(uiapp, job)",
         "document, refused = uiapp.ActiveUIDocument.Document, None", 1)),
    ("no non-ASCII outside a u'' literal",
     "shtm_core.py", lambda t: t.replace(
         "def as_bool(value):",
         "def as_bool(value):\n    _ = \"caf\u00e9\"", 1)),
    ("the easter egg is wired to the logo",
     "shtm_window.py", lambda t: t.replace("shtm_ui.attach_egg",
                                           "# shtm_ui.attach_egg", 1)),
    ("the easter egg is wired to the logo",
     "shtm_ui.py", lambda t: t.replace("from revobim.egg import egg_auto",
                                       "from revobim.egg import nothing", 1)),
    ("every window shrinks to the taskbar",
     "ShtmPrompt.xaml", lambda t: t.replace(
         '<Button x:Name="ShrinkBtn" Style="{DynamicResource Btn.Shrink}" Margin="0,0,2,0"/>\n',
         "", 1)),
    ("every window shrinks to the taskbar",
     "shtm_ui.py", lambda t: t.replace(
         "self.drawer = Drawer(window, bar, shrink", "self.drawer = None and (window, bar, shrink", 1)),
    ("the drawer cannot strand a window",
     "shtm_ui.py", lambda t: t.replace("self.window.BeginAnimation(prop, None)",
                                       "self.window.BeginAnimation(prop, self.timer)", 1)),
    ("the drawer cannot strand a window",
     "shtm_ui.py", lambda t: t.replace("            window.MinHeight = 0\n", "", 1)),
    ("the drawer cannot strand a window",
     "shtm_ui.py", lambda t: t.replace("from System import TimeSpan",
                                       "from System import TimeSpan\n"
                                       "from System.Windows.Media.Animation import Storyboard",
                                       1)),
    ("every window shrinks to the taskbar",
     "ShtmSettings.xaml", lambda t: t.replace('<Thumb x:Name="GripT"', '<Thumb x:Name="GripTop"', 1)),
    ("the drawer cannot strand a window",
     "shtm_ui.py", lambda t: t.replace("    def _unpark(self, instant=False):\n        self._stop()\n",
                                       "    def _unpark(self, instant=False):\n", 1)),
    ("an owner is brought back before a window is given to it",
     "shtm_settings.py", lambda t: t.replace("                shtm_ui.bring_back(self.owner)\n",
                                             "", 1)),
    ("the shrink button stays live during a run",
     "shtm_duplicate.py", lambda t: t.replace(
         '        self.find("PushNamesBox").IsEnabled = not locked\n',
         '        self.find("PushNamesBox").IsEnabled = not locked\n'
         '        self.find("ShrinkBtn").IsEnabled = not locked\n', 1)),
    ("dark is Revit's own dark theme, canvas first",
     "Theme.xaml", lambda t: t.replace('<SolidColorBrush x:Key="WindowBg"      Color="#3C4454"/>',
                                       '<SolidColorBrush x:Key="WindowBg"      Color="#232326"/>', 1)),
    ("dark is Revit's own dark theme, canvas first",
     "theme.py", lambda t: t.replace('"WindowBg": "#3C4454"', '"WindowBg": "#232326"', 1)),
    ("dark is Revit's own dark theme, canvas first",
     "theme.py", lambda t: t.replace('("CurrentCanvasTheme", "CurrentTheme")',
                                     '("CurrentTheme", "CurrentCanvasTheme")', 1)),
    ("new sheets and views start with no revisions",
     "shtm_dup.py", lambda t: t.replace(
         "lambda: self._strip_clouds(new_view))", "None)", 1)),
    ("new sheets and views start with no revisions",
     "shtm_dup.py", lambda t: t.replace(
         "            (u\"clearing the revisions\", self._step_clean),\n", "", 1)),
    ("new sheets and views start with no revisions",
     "shtm_dup.py", lambda t: t.replace(
         "lambda c: c.CurveElementType == CurveElementType.DetailCurve",
         "lambda c: True", 1)),
    ("the column helper takes every width",
     "shtm_ui.py", lambda t: t.replace(
         "    if width is None:\n        definition.Width = GridLength(1, GridUnitType.Star)\n"
         "        return definition\n", "", 1)),
    ("no local is read before it is set",
     "shtm_duplicate.py", lambda t: t.replace(
         "            state, text = states[index] if index < len(states) else (\"todo\", u\"\")\n"
         "            examples = getattr(self, \"view_example_list\", [])\n",
         "            examples = getattr(self, \"view_example_list\", [])\n"
         "            _peek = state\n"
         "            state, text = states[index] if index < len(states) else (\"todo\", u\"\")\n",
         1)),
    ("external events are made only in the command's context",
     "shtm_duplicate.py", lambda t: t.replace(
         "        self.template_editor = None\n",
         "        self.template_editor = None\n"
         "        self.own_event = ExternalEvent.Create(None)\n", 1)),
]


def selftest():
    baseline = check(HERE, quiet=True)
    if not baseline.ok:
        sys.stdout.write("the tool itself does not pass, so the selftest cannot "
                         "prove anything:\n")
        for problem in baseline.problems:
            sys.stdout.write("  " + problem + "\n")
        return 1

    caught = 0
    for label, target, break_it in BREAKAGES:
        folder = tempfile.mkdtemp(prefix="shtm_bench_")
        try:
            for name in os.listdir(HERE):
                if name.endswith(".py") or name.endswith(".xaml"):
                    shutil.copy(os.path.join(HERE, name), os.path.join(folder, name))
            path = os.path.join(folder, target)
            text = read(path)
            broken = break_it(text)
            if broken == text:
                sys.stdout.write("NOT BROKEN  {0} (the breakage did not apply)\n"
                                 .format(label))
                continue
            handle = io.open(path, "w", encoding="utf-8")
            try:
                handle.write(broken)
            finally:
                handle.close()
            clear_stubs()
            for module in MODULES:
                sys.modules.pop(module, None)
            if HERE in sys.path:
                sys.path.remove(HERE)
            result = check(folder, quiet=True)
            if result.ok:
                sys.stdout.write("MISSED      {0}\n".format(label))
            else:
                caught += 1
                sys.stdout.write("caught      {0}\n".format(label))
        finally:
            shutil.rmtree(folder, ignore_errors=True)
            for module in MODULES:
                sys.modules.pop(module, None)
            clear_stubs()

    sys.stdout.write("\n{0} of {1} deliberate breakages were caught\n".format(
        caught, len(BREAKAGES)))
    return 0 if caught == len(BREAKAGES) else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    sys.exit(0 if check().ok else 1)
