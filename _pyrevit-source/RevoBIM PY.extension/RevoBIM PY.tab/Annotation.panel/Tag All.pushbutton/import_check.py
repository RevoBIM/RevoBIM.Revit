# -*- coding: utf-8 -*-
"""Tag All - bench check.

Runs under plain CPython from the pushbutton folder:

    python import_check.py
    python import_check.py --selftest

Every rule below exists because the bug it catches is invisible in Revit: a
mis-namespaced import, a StaticResource in a layout or a run of hyphens in an
XML comment all produce the same blank white pyRevit window with no traceback
in it. `--selftest` breaks each rule on purpose in a scratch copy of the
folder and confirms the rule catches it - a rule nobody has tested is a rule
that does not work.
"""
import ast
import io
import os
import re
import shutil
import symtable
import sys
import tempfile
import types
import xml.dom.minidom

HERE = os.path.dirname(os.path.abspath(__file__))

MODULES = ("tagall_clr", "tagall_core", "theme", "tagall_drawer", "tagall_ui",
           "tagall_model", "tagall_tidy", "tagall_ops", "tagall_window")
LAYOUTS = ("TagAll.xaml", "TagAllResults.xaml", "TagAllPrompt.xaml")
THEME_FILE = "Theme.xaml"
# A scratch copy must never carry __pycache__ across: a .pyc whose timestamp
# still matches the unmodified source is used in preference to the file the
# selftest just broke, and the breakage silently does not happen. That cost
# two "the bench passed with it broken" failures that were not real.
IGNORE_CACHE = shutil.ignore_patterns("__pycache__", "*.pyc")


LOADER = "script.py"


# ============================================================
# the stub .NET and Revit API
# ============================================================
# Each namespace declares exactly the names the real API puts in it, so
# `from System.Windows.Controls import TextTrimming` fails here the way it
# would fail in Revit - TextTrimming lives in System.Windows.

NAMESPACES = {
    "clr": ("AddReference", "AddReferenceByName", "GetClrType", "Reference"),
    "System": ("Action", "TimeSpan", "Double", "Uri", "Convert", "String", "Math", "Array",
               "Object", "Exception", "Environment", "Guid", "DateTime"),
    "System.Collections.Generic": ("List", "Dictionary", "HashSet", "IList"),
    "System.IO": ("File", "Directory", "Path", "MemoryStream", "StringReader",
                  "StreamReader", "FileStream"),
    "System.IO.Compression": ("ZipArchive", "ZipArchiveMode", "ZipFile"),
    "System.Xml": ("XmlReader", "XmlDocument", "XmlWriter"),
    "System.Drawing": ("Bitmap", "Color", "Rectangle", "Size"),
    "System.Windows": ("Window", "Visibility", "Thickness", "CornerRadius", "GridLength", "GridUnitType",
                       "HorizontalAlignment", "VerticalAlignment", "FontWeights",
                       "TextWrapping", "TextTrimming", "WindowStartupLocation",
                       "WindowState", "WindowStyle", "ResizeMode", "SizeToContent",
                       "PresentationSource", "Clipboard", "SystemParameters",
                       "DependencyProperty", "Point", "Rect", "RoutedEventArgs",
                       "MessageBox", "Application", "DataTemplate", "FrameworkElement",
                       "ResourceDictionary", "Style", "Setter"),
    "System.Windows.Controls": ("Grid", "ColumnDefinition", "RowDefinition", "StackPanel",
                                "TextBlock", "TextBox", "CheckBox", "RadioButton", "Button",
                                "ComboBox", "ComboBoxItem", "Border", "Image", "ScrollViewer",
                                "ProgressBar", "TabControl", "TabItem", "Orientation", "Viewbox", "WrapPanel",
                                "DockPanel", "Dock", "ScrollBarVisibility",
                                "ListBox", "ListBoxItem", "ToolTip", "Canvas", "Label",
                                "SelectionChangedEventArgs", "ContentPresenter"),
    "System.Windows.Controls.Primitives": ("Thumb", "ToggleButton", "RepeatButton", "Popup", "PlacementMode",
                                           "Track", "ScrollBar"),
    "System.Windows.Data": ("IValueConverter", "Binding", "BindingMode"),
    "System.Windows.Shapes": ("Path", "Rectangle", "Ellipse", "Line"),
    "System.Windows.Input": ("Key", "Keyboard", "Mouse", "MouseButtonState", "ModifierKeys",
                             "Cursors", "KeyEventArgs", "MouseButtonEventArgs"),
    "System.Windows.Interop": ("WindowInteropHelper", "HwndSource"),
    "System.Windows.Markup": ("XamlReader", "XamlWriter"),
    "System.Windows.Media": ("SolidColorBrush", "Brush", "Brushes", "Color", "ColorConverter",
                             "Geometry", "PenLineCap", "PenLineJoin", "ScaleTransform",
                             "RotateTransform", "VisualTreeHelper", "FontFamily"),
    "System.Windows.Media.Imaging": ("BitmapImage", "BitmapCacheOption", "BitmapSource",
                                     "PngBitmapEncoder", "BitmapFrame"),
    "System.Windows.Threading": ("DispatcherTimer", "DispatcherPriority", "Dispatcher",
                                 "DispatcherFrame"),
    "System.Windows.Forms": ("Screen", "SaveFileDialog", "OpenFileDialog", "FolderBrowserDialog",
                             "DialogResult"),
    "Autodesk.Revit.DB": (
        "FilteredElementCollector", "ElementId", "BuiltInCategory", "BuiltInParameter",
        "CategoryType", "Category", "Element", "ElementType", "FamilySymbol", "FamilyInstance",
        "RevitLinkInstance", "RevitLinkType", "ViewType", "View", "ViewPlan", "View3D", "ViewSheet", "Viewport",
        "IndependentTag", "TagOrientation", "TagMode", "LeaderEndCondition", "Reference",
        "XYZ", "UV", "Transform", "BoundingBoxXYZ", "PlanViewPlane", "LinkElementId",
        "Transaction", "TransactionGroup", "TransactionStatus", "SubTransaction",
        "IFailuresPreprocessor", "FailureProcessingResult", "FailureSeverity",
        "WorksharingUtils", "CheckoutStatus", "Workset", "WorksetTable",
        "ElementTransformUtils", "PlumbingUtils", "Level", "Options", "GeometryInstance",
        "Line", "Curve", "Solid", "Face", "PlanarFace", "SpatialElement", "Grid" ),
    "Autodesk.Revit.DB.Architecture": ("Room", "RoomTag", "RoomTagType"),
    "Autodesk.Revit.DB.Mechanical": ("Space", "SpaceTag", "Duct"),
    "Autodesk.Revit.DB.Plumbing": ("Pipe", "PipeType", "PlumbingUtils"),
    "Autodesk.Revit.DB.Electrical": ("Conduit", "CableTray", "ElectricalSystem"),
    "Autodesk.Revit.UI": ("IExternalEventHandler", "ExternalEvent", "ExternalEventRequest",
                          "TaskDialog", "TaskDialogCommonButtons", "TaskDialogResult",
                          "UIThemeManager", "UIApplication", "UIDocument", "RevitCommandId",
                          "PostableCommand"),
    "Autodesk.Revit.UI.Selection": ("ObjectType", "ISelectionFilter", "Selection"),
    "Autodesk.Revit.Exceptions": ("OperationCanceledException", "InvalidOperationException"),
    "pyrevit": ("HOST_APP", "script", "revit", "forms"),
}

# Which assembly has to be referenced before a namespace can be seen at all.
# Revit's own two are deliberately absent: pyRevit loads them into every
# engine and asking for them again can bind a second copy.
ASSEMBLY_FOR = {
    "System.Windows": "PresentationFramework",
    "System.Windows.Controls": "PresentationFramework",
    "System.Windows.Controls.Primitives": "PresentationFramework",
    "System.Windows.Data": "PresentationFramework",
    "System.Windows.Shapes": "PresentationFramework",
    "System.Windows.Markup": "System.Xaml",
    "System.Windows.Input": "PresentationCore",
    "System.Windows.Interop": "PresentationCore",
    "System.Windows.Media": "PresentationCore",
    "System.Windows.Media.Imaging": "PresentationCore",
    "System.Windows.Threading": "WindowsBase",
    "System.Windows.Forms": "System.Windows.Forms",
    "System.Drawing": "System.Drawing",
    "System.Xml": "System.Xml",
    "System.IO.Compression": "System.IO.Compression",
}

REVIT_ASSEMBLIES = ("RevitAPI", "RevitAPIUI")


class StubMeta(type):
    def __getattr__(cls, item):
        if item.startswith("__"):
            raise AttributeError(item)
        return make_stub(cls.__name__ + "." + item)

    def __call__(cls, *args, **kwargs):
        return super(StubMeta, cls).__call__()


def make_stub(name):
    body = {
        "__getattr__": lambda self, item: make_stub(name + "." + item)(),
        "__iter__": lambda self: iter(()),
        "__len__": lambda self: 0,
        "__nonzero__": lambda self: True,
        "__bool__": lambda self: True,
        "__eq__": lambda self, other: self is other,
        "__ne__": lambda self, other: self is not other,
        "__hash__": lambda self: id(self),
        "__call__": lambda self, *a, **k: make_stub(name + "()")(),
    }
    return StubMeta(str(name.split(".")[-1]), (object,), body)


def install_stubs():
    """Put a module in sys.modules for every namespace above, carrying only
    the names that namespace really has."""
    created = []
    for namespace in sorted(NAMESPACES.keys(), key=lambda n: n.count(".")):
        module = types.ModuleType(str(namespace))
        for name in NAMESPACES[namespace]:
            setattr(module, str(name), make_stub(namespace + "." + name))
        if namespace == "clr":
            module.AddReference = lambda name: None
        sys.modules[str(namespace)] = module
        created.append(namespace)
        if "." in namespace:
            parent, leaf = namespace.rsplit(".", 1)
            if parent in sys.modules:
                setattr(sys.modules[parent], str(leaf), module)
    # namespaces that only ever appear as a parent
    for namespace in ("Autodesk", "Autodesk.Revit"):
        if namespace not in sys.modules:
            module = types.ModuleType(str(namespace))
            sys.modules[str(namespace)] = module
            created.append(namespace)
    sys.modules["Autodesk"].Revit = sys.modules["Autodesk.Revit"]
    for leaf in ("DB", "UI", "Exceptions"):
        full = "Autodesk.Revit." + leaf
        if full in sys.modules:
            setattr(sys.modules["Autodesk.Revit"], str(leaf), sys.modules[full])
    for leaf in ("Architecture", "Mechanical", "Plumbing", "Electrical"):
        full = "Autodesk.Revit.DB." + leaf
        if full in sys.modules:
            setattr(sys.modules["Autodesk.Revit.DB"], str(leaf), sys.modules[full])
    if "Autodesk.Revit.UI.Selection" in sys.modules:
        sys.modules["Autodesk.Revit.UI"].Selection = sys.modules["Autodesk.Revit.UI.Selection"]
    return created


def clear_tool_modules():
    for name in list(sys.modules.keys()):
        if name in MODULES:
            del sys.modules[name]


def import_modules(folder):
    """Import every shipped module against the stubs. Returns
    (imported dict, problems list)."""
    problems = []
    imported = {}
    install_stubs()
    clear_tool_modules()
    sys.path.insert(0, folder)
    try:
        for name in MODULES:
            try:
                imported[name] = __import__(name)
            except Exception as error:
                problems.append(u"{0} will not import: {1}: {2}".format(
                    name, type(error).__name__, error))
    finally:
        if sys.path and sys.path[0] == folder:
            sys.path.pop(0)
    return imported, problems


# ============================================================
# small helpers
# ============================================================

def read(folder, name):
    with io.open(os.path.join(folder, name), "r", encoding="utf-8") as handle:
        return handle.read()


def python_files(folder):
    out = []
    for name in os.listdir(folder):
        if not name.endswith(".py"):
            continue
        if name in ("import_check.py", "bench_logic.py", "make_icon.py"):
            continue
        out.append(name)
    return sorted(out)


def xaml_files(folder):
    return sorted([n for n in os.listdir(folder) if n.endswith(".xaml")])


def code_only(text):
    """The source with comments and string literals blanked out, so a rule
    cannot fire on a word inside a docstring. Token spacing is preserved -
    joining without it turns `from System import Uri` into
    `fromSystemimportUri` and silently disables every rule downstream.
    """
    out = []
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char == "#":
            while index < length and text[index] != "\n":
                out.append(" ")
                index += 1
            continue
        if char in "\"'":
            quote = char
            triple = text[index:index + 3] in ('"""', "'''")
            marker = text[index:index + 3] if triple else quote
            out.append(" " * len(marker))
            index += len(marker)
            while index < length:
                if text[index] == "\\":
                    out.append("  ")
                    index += 2
                    continue
                if text[index:index + len(marker)] == marker:
                    out.append(" " * len(marker))
                    index += len(marker)
                    break
                out.append("\n" if text[index] == "\n" else " ")
                index += 1
            continue
        out.append(char)
        index += 1
    return "".join(out)


def strip_xml_comments(text):
    return re.sub(r"<!--.*?-->", u"", text, flags=re.S)


# ============================================================
# the rules
# ============================================================

def rule_xaml_parses(folder):
    """XML forbids `--` inside a comment, so a banner drawn with hyphens
    stops XamlReader dead and shows as a blank window."""
    problems = []
    for name in xaml_files(folder):
        try:
            xml.dom.minidom.parse(os.path.join(folder, name))
        except Exception as error:
            problems.append(u"{0} is not valid XML: {1}".format(name, error))
    return problems


def rule_no_static_resource(folder):
    """Theme.xaml is merged in after XamlReader has parsed the layout, so a
    StaticResource fails at load. DynamicResource only, everywhere."""
    problems = []
    for name in xaml_files(folder):
        if "StaticResource" in read(folder, name):
            problems.append(u"{0} uses StaticResource - DynamicResource only".format(name))
    return problems


def theme_keys(folder):
    text = read(folder, THEME_FILE)
    return set(re.findall(r'x:Key="([^"]+)"', text))


def rule_dynamic_keys_defined(folder):
    problems = []
    keys = theme_keys(folder)
    for name in xaml_files(folder):
        text = read(folder, name)
        for key in set(re.findall(r"\{DynamicResource\s+([A-Za-z0-9_]+)\}", text)):
            if key not in keys:
                problems.append(u"{0} asks for DynamicResource {1}, which {2} does not define".format(
                    name, key, THEME_FILE))
    return problems


def rule_style_targettype_matches(folder):
    """WPF raises when a style whose TargetType does not match is applied,
    not when it is parsed - so it surfaces as a dead window too."""
    problems = []
    targets = {}
    for match in re.finditer(r'<Style\s+x:Key="([^"]+)"\s+TargetType="([^"]+)"', read(folder, THEME_FILE)):
        targets[match.group(1)] = match.group(2)
    for name in xaml_files(folder):
        if name == THEME_FILE:
            continue
        text = strip_xml_comments(read(folder, name))
        for match in re.finditer(r"<(\w+)\b[^>]*?Style=\"\{DynamicResource\s+([A-Za-z0-9_]+)\}\"", text):
            element, key = match.group(1), match.group(2)
            wanted = targets.get(key)
            if wanted and wanted != element:
                problems.append(u"{0}: <{1}> uses style {2}, whose TargetType is {3}".format(
                    name, element, key, wanted))
    return problems


def xaml_names(folder):
    names = set()
    for name in xaml_files(folder):
        names |= set(re.findall(r'x:Name="([^"]+)"', read(folder, name)))
    return names


def findname_calls(folder):
    """Every FindName("X"), whatever it was aliased to. The alias matters:
    the code says `find = self.window.FindName` and then `find("Progress")`,
    and a rule that only matched literal FindName calls would do nothing."""
    calls = set()
    aliases = set(["FindName"])
    for name in python_files(folder):
        text = code_only(read(folder, name))
        for match in re.finditer(r"(\w+)\s*=\s*(?:self\.)?\w*\.?FindName\b", text):
            aliases.add(match.group(1))
    for name in python_files(folder):
        text = read(folder, name)
        for alias in aliases:
            for match in re.finditer(alias + r"\(\s*[\"']([^\"']+)[\"']\s*\)", text):
                calls.add(match.group(1))
    return calls


def rule_findname_has_xname(folder):
    problems = []
    declared = xaml_names(folder)
    for wanted in sorted(findname_calls(folder)):
        if wanted not in declared:
            problems.append(u"FindName(\"{0}\") has no matching x:Name in any layout".format(wanted))
    return problems


def rule_xname_is_used(folder):
    """The other direction: a control named in a layout that nothing ever
    asks for is either a typo at one end or a feature that was never wired.

    Theme.xaml is exempt - a control template names its parts so its own
    triggers can retarget them, and those names never leave the template.
    """
    problems = []
    used = findname_calls(folder)
    text = u"\n".join([read(folder, name) for name in python_files(folder)])
    for name in xaml_files(folder):
        if name == THEME_FILE:
            continue
        layout = read(folder, name)
        for declared in set(re.findall(r'x:Name="([^"]+)"', layout)):
            if declared in used:
                continue
            # named inside the layout itself: a trigger target or a binding source
            if re.search(r'(TargetName|ElementName)="' + re.escape(declared) + r'"', layout):
                continue
            if re.search(r"[\"']" + re.escape(declared) + r"[\"']", text):
                continue
            problems.append(u"{0} declares x:Name=\"{1}\" that nothing uses".format(name, declared))
    return problems


def rule_no_fstrings(folder):
    problems = []
    for name in python_files(folder):
        for number, line in enumerate(read(folder, name).splitlines(), 1):
            if re.search(r"(^|[^A-Za-z0-9_])f[\"']", line):
                problems.append(u"{0}:{1} f-string - IronPython 2.7 cannot parse one".format(name, number))
    return problems


def rule_no_print(folder):
    problems = []
    for name in python_files(folder):
        text = code_only(read(folder, name))
        for number, line in enumerate(text.splitlines(), 1):
            if re.search(r"(^|\s)print\s*[\(\"' ]", line):
                problems.append(u"{0}:{1} print statement".format(name, number))
    return problems


def rule_no_bare_integervalue(folder):
    """`.IntegerValue` was removed in Revit 2026. Everything goes through
    eid_value, which prefers `.Value` and falls back inside a try."""
    problems = []
    for name in python_files(folder):
        text = code_only(read(folder, name))
        for number, line in enumerate(text.splitlines(), 1):
            if ".IntegerValue" not in line:
                continue
            if name == "tagall_core.py" and 150 < 0:
                continue
            problems.append((name, number, line))
    out = []
    for name, number, line in problems:
        if name == "tagall_core.py" and _inside_eid_value(folder, number):
            continue
        out.append(u"{0}:{1} bare .IntegerValue - use eid_value()".format(name, number))
    return out


def _inside_eid_value(folder, line_number):
    tree = ast.parse(read(folder, "tagall_core.py"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "eid_value":
            last = max([getattr(n, "lineno", node.lineno) for n in ast.walk(node)])
            return node.lineno <= line_number <= last
    return False


def rule_no_system_uri(folder):
    """`from System import Uri` throws at module load on Revit 2025+ - the
    assembly moved. Images load from bytes through a MemoryStream instead.

    Parsed rather than pattern-matched: the selftest caught this rule doing
    nothing at all, because it only looked for `import Uri` on its own and
    the real shape of the mistake is `from System import Action, Uri`.
    """
    problems = []
    for name in python_files(folder):
        text = read(folder, name)
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name == "Uri":
                        problems.append(u"{0}:{1} imports Uri from {2}".format(
                            name, node.lineno, node.module))
            elif isinstance(node, ast.Attribute) and node.attr == "Uri":
                problems.append(u"{0}:{1} reaches for System.Uri".format(name, node.lineno))
        if re.search(r"\bUriSource\b", code_only(text)):
            problems.append(u"{0} sets BitmapImage.UriSource - load from a MemoryStream".format(name))
    return problems


def rule_non_ascii_only_in_u_literals(folder):
    """A bare non-ASCII character in a plain literal fails under IronPython
    2.7. Em dashes and arrows have to sit in a u'' literal."""
    problems = []
    for name in python_files(folder):
        text = read(folder, name)
        stripped = code_only(text)
        for number, line in enumerate(stripped.splitlines(), 1):
            for char in line:
                if ord(char) > 127:
                    problems.append(u"{0}:{1} non-ASCII outside a literal".format(name, number))
                    break
        for number, line in enumerate(text.splitlines(), 1):
            match = re.search(r"(?<![uU])([\"'])((?:[^\"'\\]|\\.)*?)\1", line)
            if not match:
                continue
            if any(ord(char) > 127 for char in match.group(2)):
                problems.append(u"{0}:{1} non-ASCII in a plain literal - use u\"\"".format(name, number))
    return problems


def imported_namespaces(text):
    """(namespace, line number) for every top-level `from X import ...`."""
    out = []
    for number, line in enumerate(code_only(text).splitlines(), 1):
        match = re.match(r"\s*from\s+((?:System|Autodesk)[\w\.]*)\s+import\s", line)
        if match:
            out.append((match.group(1), number))
    return out


def rule_clr_first(folder):
    """An IronPython engine can only see a .NET namespace once its assembly
    has been referenced, and pyRevit does not preload WPF into every engine.
    tagall_clr does every AddReference, and has to be imported before the
    first System.* or Autodesk.* line in the file - import order inside a
    file is load order."""
    problems = []
    for name in python_files(folder):
        if name in ("tagall_clr.py", LOADER):
            continue
        text = read(folder, name)
        uses = imported_namespaces(text)
        if not uses:
            continue
        clr_line = None
        for number, line in enumerate(code_only(text).splitlines(), 1):
            if re.match(r"\s*import\s+tagall_clr\b", line):
                clr_line = number
                break
        if clr_line is None:
            problems.append(u"{0} imports {1} without importing tagall_clr first".format(name, uses[0][0]))
            continue
        first = min([number for _ns, number in uses])
        if clr_line > first:
            problems.append(u"{0} imports tagall_clr at line {1}, after {2} at line {3}".format(
                name, clr_line, uses[0][0], first))
    return problems


def rule_assembly_for(folder):
    """Every namespace imported anywhere in the tool has to have its
    assembly in tagall_clr's own list. This is the rule that catches a new
    import reaching into an assembly nobody referenced."""
    problems = []
    clr_text = read(folder, "tagall_clr.py")
    referenced = set(re.findall(r'"([\w\.]+)"', clr_text))
    for name in python_files(folder):
        text = code_only(read(folder, name))
        wanted = set(re.findall(r"from\s+((?:System|Autodesk)[\w\.]*)\s+import\s", text))
        wanted |= set(re.findall(r"import\s+((?:System|Autodesk)[\w\.]*)\s*$", text, flags=re.M))
        for namespace in wanted:
            assembly = ASSEMBLY_FOR.get(namespace)
            if assembly is None:
                continue
            if assembly not in referenced:
                problems.append(u"{0} imports {1}, but tagall_clr never references {2}".format(
                    name, namespace, assembly))
    return problems


def rule_no_revitapi_reference(folder):
    """pyRevit loads RevitAPI and RevitAPIUI into every engine; referencing
    them again can bind a second copy of the assembly."""
    problems = []
    for name in python_files(folder):
        text = code_only(read(folder, name))
        for assembly in REVIT_ASSEMBLIES:
            if re.search(r"AddReference\s*\(\s*[\"']" + assembly + r"[\"']", read(folder, name)):
                problems.append(u"{0} calls clr.AddReference('{1}') - pyRevit already loaded it".format(
                    name, assembly))
    return problems


def rule_palettes_match(folder):
    """Both palettes carry the same keys, and Theme.xaml has a default brush
    for each - a key present in one palette and missing from the other is a
    control that renders unthemed in exactly one mode."""
    problems = []
    text = read(folder, "theme.py")
    blocks = {}
    for palette in ("DARK", "LIGHT"):
        match = re.search(palette + r"\s*=\s*\{(.*?)\}", text, flags=re.S)
        if not match:
            problems.append(u"theme.py has no {0} palette".format(palette))
            continue
        blocks[palette] = set(re.findall(r'"([A-Za-z0-9_]+)"\s*:', match.group(1)))
    if len(blocks) == 2:
        dark, light = blocks["DARK"], blocks["LIGHT"]
        for key in sorted(dark - light):
            problems.append(u"{0} is in the dark palette and not the light one".format(key))
        for key in sorted(light - dark):
            problems.append(u"{0} is in the light palette and not the dark one".format(key))
        defined = theme_keys(folder)
        for key in sorted(dark & light):
            if key not in defined:
                problems.append(u"palette key {0} has no default brush in {1}".format(key, THEME_FILE))
    return problems


def rule_setresourcereference_keys_exist(folder):
    problems = []
    keys = theme_keys(folder)
    for name in python_files(folder):
        text = read(folder, name)
        found = set(re.findall(r"SetResourceReference\([^,]+,\s*[\"']([A-Za-z0-9_]+)[\"']\)", text))
        found |= set(re.findall(r"set_brush\([^,]+,\s*[\"'][A-Za-z]+[\"']\s*,\s*[\"']([A-Za-z0-9_]+)[\"']\)", text))
        for key in sorted(found):
            if key not in keys:
                problems.append(u"{0} asks for resource {1}, which {2} does not define".format(
                    name, key, THEME_FILE))
    return problems


def rule_no_duplicate_definitions(folder):
    """Python silently keeps the last of two definitions with the same name,
    so a stale copy sits in the file looking alive and does nothing."""
    problems = []
    for name in python_files(folder):
        tree = ast.parse(read(folder, name))
        seen = {}
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                if node.name in seen:
                    problems.append(u"{0}: {1} is defined twice (lines {2} and {3})".format(
                        name, node.name, seen[node.name], node.lineno))
                seen[node.name] = node.lineno
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            methods = {}
            for item in node.body:
                if isinstance(item, ast.FunctionDef):
                    if item.name in methods:
                        problems.append(u"{0}: {1}.{2} is defined twice (lines {3} and {4})".format(
                            name, node.name, item.name, methods[item.name], item.lineno))
                    methods[item.name] = item.lineno
    return problems


def rule_globals_exist(folder, imported=None):
    """Every global name a function reaches for exists in its module. This is
    the rule that catches a function deleted by a block rewrite while its
    callers stayed behind."""
    problems = []
    imported = imported or {}
    for name in python_files(folder):
        module_name = name[:-3]
        module = imported.get(module_name)
        if module is None:
            continue
        available = set(dir(module))
        try:
            import builtins as builtin_module
        except ImportError:
            import __builtin__ as builtin_module
        available |= set(dir(builtin_module))
        # IronPython 2.7 has these and the CPython the bench runs on does
        # not; each use is already guarded by try/except NameError
        available |= set(["unicode", "basestring", "long", "xrange", "unichr", "reduce"])
        table = symtable.symtable(read(folder, name), name, "exec")
        for symbol_table in _walk_tables(table):
            for symbol in symbol_table.get_symbols():
                if not symbol.is_global() or symbol.is_assigned():
                    continue
                if symbol.get_name() in available:
                    continue
                problems.append(u"{0}: {1} reaches for global '{2}', which does not exist".format(
                    name, symbol_table.get_name(), symbol.get_name()))
    return problems


def _walk_tables(table):
    out = [table]
    for child in table.get_children():
        out.extend(_walk_tables(child))
    return out


def rule_call_arity(folder):
    """A module-level function called with the wrong number of arguments -
    the kind of thing a rename leaves behind."""
    problems = []
    for name in python_files(folder):
        tree = ast.parse(read(folder, name))
        signatures = {}
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                args = node.args
                required = len(args.args) - len(args.defaults)
                maximum = None if (args.vararg or args.kwarg) else len(args.args)
                signatures[node.name] = (required, maximum)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            signature = signatures.get(node.func.id)
            if signature is None:
                continue
            if any(isinstance(a, ast.Starred) for a in node.args) or node.keywords:
                continue
            given = len(node.args)
            required, maximum = signature
            if given < required or (maximum is not None and given > maximum):
                problems.append(u"{0}:{1} calls {2}() with {3} arguments, it takes {4}".format(
                    name, node.lineno, node.func.id, given,
                    required if maximum is None else u"{0} to {1}".format(required, maximum)))
    return problems


def rule_cross_module_names(folder, imported=None):
    """`core.plan_targets` has to exist in tagall_core. A typo here is a
    silent AttributeError that only fires on the one code path that uses
    it."""
    problems = []
    imported = imported or {}
    if not imported:
        return problems
    for name in python_files(folder):
        text = read(folder, name)
        aliases = {}
        for match in re.finditer(r"^import\s+(tagall_\w+|theme)\s+as\s+(\w+)", code_only(text), flags=re.M):
            aliases[match.group(2)] = match.group(1)
        for match in re.finditer(r"^import\s+(tagall_\w+|theme)\s*$", code_only(text), flags=re.M):
            aliases[match.group(1)] = match.group(1)
        for alias, module_name in aliases.items():
            module = imported.get(module_name)
            if module is None:
                continue
            for match in re.finditer(r"\b" + alias + r"\.(\w+)", code_only(text)):
                attribute = match.group(1)
                if not hasattr(module, attribute):
                    problems.append(u"{0} uses {1}.{2}, which {3} does not define".format(
                        name, alias, attribute, module_name))
    return problems


def rule_thin_loader(folder):
    """script.py must import nothing that can fail at module level, or there
    is no runtime left to report the failure - which is the blank white
    pyRevit window."""
    problems = []
    tree = ast.parse(read(folder, LOADER))
    allowed = set(["os", "sys", "traceback"])
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name.split(".")[0] for a in node.names] if isinstance(node, ast.Import) \
                else [(node.module or "").split(".")[0]]
            for imported_name in names:
                if imported_name not in allowed:
                    problems.append(u"{0} imports {1} at module level - keep it inside main()".format(
                        LOADER, imported_name))
    if "__persistentengine__" not in read(folder, LOADER):
        problems.append(u"{0} opens a modeless window without __persistentengine__ = True".format(LOADER))
    return problems


def rule_breadcrumb(folder):
    """The loader writes a breadcrumb before every stage and clears it on
    success, so a load that dies without a runtime still leaves something
    behind to read."""
    problems = []
    text = read(folder, LOADER)
    if "breadcrumb" not in text:
        problems.append(u"{0} writes no breadcrumb before the stages that can fail".format(LOADER))
    if "remove_file" not in text:
        problems.append(u"{0} never clears the breadcrumb, so every run looks like a failure".format(LOADER))
    return problems


def rule_no_pump_in_ops(folder):
    """Letting Revit's message loop run between Start and Commit can leave
    the write with nothing committed, and a TransactionGroup held open
    across a dispatcher pump is a hard crash. The write module therefore
    does not touch the dispatcher at all - progress is called back to the
    window, which pumps between transactions."""
    problems = []
    text = code_only(read(folder, "tagall_ops.py"))
    for needle in ("Dispatcher.Invoke", "DoEvents", "ui.pump", "PushFrame"):
        if needle in text:
            problems.append(u"tagall_ops.py calls {0} - no pumping anywhere near a transaction".format(needle))
    return problems


def rule_egg_anchor(folder):
    """Three slow clicks on the RevoBIM logo. Every window with a logo has
    to arm it, and the call has to stay inside a try/except - cosmetics can
    never take a tool down."""
    problems = []
    ui_text = read(folder, "tagall_ui.py")
    if "revobim.egg" not in ui_text:
        problems.append(u"tagall_ui.py does not reach for the shared egg package")
    if "def attach_egg" not in ui_text:
        problems.append(u"tagall_ui.py has no attach_egg")
    everything = u"\n".join([read(folder, name) for name in python_files(folder)])
    for name in xaml_files(folder):
        if name == THEME_FILE:
            continue
        if 'x:Name="LogoHost"' not in read(folder, name):
            continue
        stem = name[:-5]
        if not re.search(r"attach_egg\(", everything):
            problems.append(u"{0} carries a logo that nothing arms the egg on".format(stem))
    calls = len(re.findall(r"attach_egg\(", everything))
    if calls < 4:          # the definition plus one call per window
        problems.append(u"the egg is armed on fewer windows than carry a logo ({0} references)".format(calls))
    return problems


def rule_no_shared_bundles(folder):
    """A shared panel or pulldown bundle.yaml shipped as a plain overwrite
    silently reverts whatever the last tool put there."""
    problems = []
    parent = os.path.dirname(folder)
    if os.path.isfile(os.path.join(parent, "bundle.yaml")):
        problems.append(u"a bundle.yaml is shipped for the shared Annotation panel - "
                        u"the panel already exists, so shipping it reverts its title")
    return problems


def rule_single_version(folder):
    """One __version__, in tagall_core, read by everything else - so bumping
    that one line is the only edit a release needs."""
    problems = []
    holders = []
    for name in python_files(folder):
        if re.search(r"^__version__\s*=", read(folder, name), flags=re.M):
            holders.append(name)
    if holders != ["tagall_core.py"]:
        problems.append(u"__version__ should live only in tagall_core.py, found in: {0}".format(
            u", ".join(holders) or u"nothing"))
    for name in LAYOUTS:
        if re.search(r'Text="v\d', read(folder, name)):
            problems.append(u"{0} hardcodes a version number - the window reads it from the module".format(name))
    return problems


def rule_handlers_guarded(folder):
    """An unguarded WPF handler that throws leaves the window on screen with
    nothing responding and no traceback anywhere - a dead button that cannot
    report itself. Every handler wired in the window goes through ui_safe."""
    problems = []
    text = code_only(read(folder, "tagall_window.py"))
    for number, line in enumerate(text.splitlines(), 1):
        match = re.search(r"\.(Click|Checked|Unchecked|SelectionChanged|TextChanged|Tick|"
                          r"PreviewKeyDown|MouseLeftButtonDown)\s*\+=\s*(.+)$", line)
        if not match:
            continue
        target = match.group(2).strip()
        # a factory - a method or one nested in a function - is guarded where
        # it is built, which the block below proves for every _make_ factory
        if target.startswith("ui.ui_safe") or target.startswith("self._make") or target.startswith("_make"):
            continue
        # a handler built by a _make_* factory is guarded where it is built,
        # which the next block proves rather than assumes
        if target.endswith("_handler") or target == "handler":
            continue
        if target in ("self._closed", "self._theme_changed", "self._showing"):
            continue
        problems.append(u"tagall_window.py:{0} wires {1} unguarded - wrap it in ui.ui_safe".format(
            number, target))
    for match in re.finditer(r"def (_make_\w+)\(.*?\n(.*?)(?=\n    def |\n\nclass |\Z)",
                             read(folder, "tagall_window.py"), flags=re.S):
        if "ui.ui_safe" not in match.group(2):
            problems.append(u"tagall_window.py: {0} builds a handler without ui.ui_safe".format(
                match.group(1)))
    return problems


# Attribute values WPF converts to an enum. A value that is not a member
# parses as XML perfectly well and then throws inside XamlReader.Load, which
# is the blank white pyRevit window all over again - and the exception names
# the line and column of a file the user has never opened. v1.0.0 shipped
# with VerticalAlignment="Baseline", which is a WinForms idea; WPF has Top,
# Center, Bottom and Stretch and nothing else.
ENUM_VALUES = {
    "HorizontalAlignment": ("Left", "Center", "Right", "Stretch"),
    "HorizontalContentAlignment": ("Left", "Center", "Right", "Stretch"),
    "VerticalAlignment": ("Top", "Center", "Bottom", "Stretch"),
    "VerticalContentAlignment": ("Top", "Center", "Bottom", "Stretch"),
    "Orientation": ("Horizontal", "Vertical"),
    "Visibility": ("Visible", "Hidden", "Collapsed"),
    "TextWrapping": ("NoWrap", "Wrap", "WrapWithOverflow"),
    "TextTrimming": ("None", "CharacterEllipsis", "WordEllipsis"),
    "TextAlignment": ("Left", "Right", "Center", "Justify"),
    "Stretch": ("None", "Fill", "Uniform", "UniformToFill"),
    "ResizeMode": ("NoResize", "CanMinimize", "CanResize", "CanResizeWithGrip"),
    "WindowStyle": ("None", "SingleBorderWindow", "ThreeDBorderWindow", "ToolWindow"),
    "WindowState": ("Normal", "Minimized", "Maximized"),
    "WindowStartupLocation": ("Manual", "CenterScreen", "CenterOwner"),
    "SizeToContent": ("Manual", "Width", "Height", "WidthAndHeight"),
    "VerticalScrollBarVisibility": ("Disabled", "Auto", "Hidden", "Visible"),
    "HorizontalScrollBarVisibility": ("Disabled", "Auto", "Hidden", "Visible"),
    "ClickMode": ("Release", "Press", "Hover"),
    "PopupAnimation": ("None", "Fade", "Slide", "Scroll"),
    "Placement": ("Absolute", "AbsolutePoint", "Bottom", "Center", "Custom", "Left",
                  "Mouse", "MousePoint", "Relative", "RelativePoint", "Right", "Top"),
    "FlowDirection": ("LeftToRight", "RightToLeft"),
    "FontStyle": ("Normal", "Italic", "Oblique"),
    "FontWeight": ("Thin", "ExtraLight", "UltraLight", "Light", "Normal", "Regular",
                   "Medium", "DemiBold", "SemiBold", "Bold", "ExtraBold", "UltraBold",
                   "Black", "Heavy"),
    "ResizeBehavior": ("BasedOnAlignment", "CurrentAndNext", "PreviousAndCurrent",
                       "PreviousAndNext"),
    "ResizeDirection": ("Auto", "Columns", "Rows"),
    "Cursor": ("Arrow", "AppStarting", "Cross", "Hand", "Help", "IBeam", "No", "None",
               "Pen", "ScrollAll", "ScrollE", "ScrollN", "ScrollNE", "ScrollNS",
               "ScrollNW", "ScrollS", "ScrollSE", "ScrollSW", "ScrollW", "ScrollWE",
               "SizeAll", "SizeNESW", "SizeNS", "SizeNWSE", "SizeWE", "UpArrow", "Wait"),
}

BOOL_ATTRIBUTES = ("AllowsTransparency", "ShowInTaskbar", "IsHitTestVisible", "Focusable",
                   "IsTabStop", "IsItemsHost", "IsDirectionReversed", "RecognizesAccessKey",
                   "StaysOpen", "IsIndeterminate", "SnapsToDevicePixels", "ClipToBounds")


def rule_enum_attribute_values(folder):
    problems = []
    for name in xaml_files(folder):
        text = strip_xml_comments(read(folder, name))
        lines = text.splitlines()
        for number, line in enumerate(lines, 1):
            for attribute, allowed in ENUM_VALUES.items():
                for match in re.finditer(r'\b' + attribute + r'="([^"]*)"', line):
                    value = match.group(1)
                    if "{" in value or not value:
                        continue
                    if value not in allowed:
                        problems.append(u"{0}:{1} {2}=\"{3}\" is not a member - it is one of {4}".format(
                            name, number, attribute, value, u", ".join(allowed)))
            for attribute in BOOL_ATTRIBUTES:
                for match in re.finditer(r'\b' + attribute + r'="([^"]*)"', line):
                    value = match.group(1)
                    if "{" in value:
                        continue
                    if value not in ("True", "False"):
                        problems.append(u"{0}:{1} {2}=\"{3}\" is not True or False".format(
                            name, number, attribute, value))
            # <Setter Property="X" Value="Y"/> carries the same trap
            for match in re.finditer(r'Property="(?:[\w\.]+\.)?(\w+)"\s+Value="([^"]*)"', line):
                attribute, value = match.group(1), match.group(2)
                allowed = ENUM_VALUES.get(attribute)
                if allowed is None or "{" in value or not value:
                    continue
                if attribute in ("Width", "Height"):
                    continue
                if value not in allowed:
                    problems.append(u"{0}:{1} <Setter {2}> is given \"{3}\" - it is one of {4}".format(
                        name, number, attribute, value, u", ".join(allowed)))
    return problems


def rule_elbow_after_regenerate(folder):
    """A tag has no computed geometry straight after Create, so its head and
    its box mean nothing yet and an elbow set against them is ignored -
    and assigning TagHeadPosition afterwards moves the head and leaves the
    elbow behind. That was the long diagonal leader in v1.0.1. The elbow is
    therefore only ever set from apply_leader_elbow, which runs after a
    regenerate and never touches the head.
    """
    problems = []
    text = read(folder, "tagall_ops.py")
    tree = ast.parse(text)
    bodies = {}
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        last = max([getattr(child, "lineno", node.lineno) for child in ast.walk(node)])
        source = u"\n".join(text.splitlines()[node.lineno - 1:last])
        bodies[node.name] = source
        sets_elbow = ("SetLeaderElbow" in source) or ("LeaderElbow =" in source)
        if sets_elbow and node.name != "apply_leader_elbow":
            problems.append(u"tagall_ops.py: {0} sets a leader elbow - only "
                            u"apply_leader_elbow may, and only after a regenerate".format(node.name))
        if sets_elbow and "TagHeadPosition =" in source:
            problems.append(u"tagall_ops.py: {0} sets the tag head and the elbow in one pass - "
                            u"moving the head leaves the elbow behind".format(node.name))
    untangler = bodies.get("untangle_view", u"")
    if untangler:
        if "doc.Regenerate()" not in untangler or "apply_leader_elbow(" not in untangler:
            problems.append(u"tagall_ops.py: untangle_view moves heads without setting the elbows again "
                            u"after a regenerate - the elbows stay where the tags were")
        elif untangler.index("doc.Regenerate()") > untangler.index("apply_leader_elbow("):
            problems.append(u"tagall_ops.py: untangle_view sets the elbows before it regenerates")
        if "measure_tag_boxes(" not in untangler:
            problems.append(u"tagall_ops.py: untangle_view measures the tags with their leaders on")
    runner = bodies.get("run_family", u"")
    if "untangle_view(" in runner and runner.index("untangle_view(") < runner.index("tag_chunk("):
        problems.append(u"tagall_ops.py: run_family untangles before the view's tags are placed")
    placer = bodies.get("place_tags", u"")
    if "doc.Regenerate()" not in placer:
        problems.append(u"tagall_ops.py: place_tags never regenerates, so no head it reads back is real")
    elif placer.index("doc.Regenerate()") > placer.index("apply_leader_elbow("):
        problems.append(u"tagall_ops.py: place_tags sets the elbows before it regenerates")
    return problems



def rule_box_measured_without_leader(folder):
    """A tag's bounding box in a view covers its leader as well as its text.
    Measured with the leader on, the "edge" of the tag is the far end of the
    leader, out by the element - which is what made the elbow drift. The box
    is therefore read with the leaders switched off inside a SubTransaction
    that is then rolled back, putting every leader back as it was.
    """
    problems = []
    text = read(folder, "tagall_ops.py")
    tree = ast.parse(text)
    found = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "measure_tag_boxes":
            last = max([getattr(child, "lineno", node.lineno) for child in ast.walk(node)])
            found = u"\n".join(text.splitlines()[node.lineno - 1:last])
    if found is None:
        problems.append(u"tagall_ops.py has no measure_tag_boxes")
        return problems
    if "set_leader(tag, False)" not in found:
        problems.append(u"measure_tag_boxes reads the box without switching the leaders off")
    if "SubTransaction" not in found or "RollBack" not in found:
        problems.append(u"measure_tag_boxes does not roll its change back, so the leaders stay off")
    if "doc.Regenerate()" not in found:
        problems.append(u"measure_tag_boxes reads a box it has not regenerated")
    order = [found.find("set_leader(tag, False)"), found.find("doc.Regenerate()"),
             found.find("annotation_corners")]
    if sorted(order) != order:
        problems.append(u"measure_tag_boxes must switch the leaders off, regenerate, then read")
    for name in python_files(folder):
        if name == "tagall_ops.py":
            continue
        if "get_BoundingBox" in code_only(read(folder, name)) and name != "tagall_model.py":
            problems.append(u"{0} reads a bounding box outside the measured path".format(name))
    return problems



def _icon_tables(folder):
    text = read(folder, "tagall_ui.py")
    icons_block = re.search(r"^ICONS = \{(.*?)^\}", text, flags=re.S | re.M)
    icon_for_block = re.search(r"^ICON_FOR = \{(.*?)^\}", text, flags=re.S | re.M)
    exempt = re.search(r"^ICON_EXEMPT = \(([^)]*)\)", text, flags=re.M)
    icons = {}
    if icons_block:
        for name, data in re.findall(r'"(\w+)":\s*"([^"]*)"', icons_block.group(1)):
            icons[name] = data
    icon_for = {}
    if icon_for_block:
        for name, icon in re.findall(r'"(\w+)":\s*\("(\w+)"', icon_for_block.group(1)):
            icon_for[name] = icon
    exempt_names = set(re.findall(r'"(\w+)"', exempt.group(1))) if exempt else set()
    # a group header carries its icon through GROUP_FOR and group_toggle
    group_block = re.search(r"^GROUP_FOR = \{(.*?)^\}", text, flags=re.S | re.M)
    if group_block:
        for name, icon in re.findall(r'"(\w+)":\s*\("(\w+)"', group_block.group(1)):
            icon_for[name] = icon
    return icons, icon_for, exempt_names


def rule_icons_drawn_once(folder):
    """No icon name appears twice in ICONS. A dict literal keeps the last
    one silently, so a second "expand" drawn for the drawer turned every
    Expand button into the drawer's up arrow (1.4.1)."""
    text = read(folder, "tagall_ui.py")
    block = re.search(r"^ICONS = \{(.*?)^\}", text, flags=re.S | re.M)
    if not block:
        return [u"tagall_ui.py has no ICONS table"]
    seen = set()
    problems = []
    for name in re.findall(r'^\s*"(\w+)":', block.group(1), flags=re.M):
        if name in seen:
            problems.append(u"ICONS draws '{0}' twice - the second one wins without a word".format(name))
        seen.add(name)
    return problems


def rule_family_groups(folder):
    """Every Family Tags group has a header, a body and a row in the layout,
    and the window builds them."""
    problems = []
    layout = strip_xml_comments(read(folder, "TagAll.xaml"))
    for name in ("Views", "Categories", "Families"):
        for part in ("GroupToggle", "GroupBody", "GroupRow", "GroupSlide", "GroupHeader"):
            if 'x:Name="{0}{1}"'.format(name, part) not in layout:
                problems.append(u"TagAll.xaml has no {0}{1}".format(name, part))
    if 'x:Name="GroupsFillerRow"' not in layout:
        problems.append(u"TagAll.xaml has no GroupsFillerRow")
    window = code_only(read(folder, "tagall_window.py"))
    if "self._setup_groups()" not in window:
        problems.append(u"the window never builds its groups")
    if "MouseLeftButtonUp += self._make_header_click(" not in window:
        problems.append(u"a click on the rest of a group's header bar does nothing")
    # a header click, Add ticked and the source buttons all slide the groups
    for method in ("_group_clicked", "_add_ticked", "_make_source_click"):
        body = re.search(r"    def {0}\(self.*?(?=\n    def |\Z)".format(method), window, flags=re.S)
        if body is None or "self._slide_groups(before)" not in body.group(0):
            problems.append(u"{0} makes the groups jump rather than slide".format(method))
    if "self._end_group_slide()" not in window:
        problems.append(u"a slide still running is never landed")
    if "core.fit_window(" not in window or "self.window.Height = core.slide_height(" not in window:
        problems.append(u"the footer never rides up when every group is shut")
    families = layout[layout.find('x:Name="FamiliesGroupBody"'):]
    if 'x:Name="LeaderCheck"' not in families:
        problems.append(u"the tagging options are not inside Families to tag")
    if "core.remembered_family_tag(self.owner.settings, node.category, node.family)" not in window:
        problems.append(u"rows going into Families to tag ignore their family's own default tag")
    if "extra=self._default_combo(category, family)" not in window:
        problems.append(u"family rows in the Categories tree carry no default tag dropdown")
    if "core.after_placing(" not in window or "core.after_placing_enabled(" not in window:
        problems.append(u"Untangle and Tag Tidy can both be ticked")
    # greyed when the window opens and again on every tick of either box
    if "self._after_placing_changed" not in window or window.count("self._paint_after_placing()") < 2:
        problems.append(u"ticking Untangle or Tag Tidy does not grey out the other")
    if "self._show_links(False)" not in window:
        problems.append(u"the linked models list does not start collapsed")
    if window.count("core.family_open(") < 2:
        problems.append(u"the Categories tree decides a family's types are open by itself")
    if "core.show_families_group(" not in window:
        problems.append(u"Add ticked leaves Categories open and Families to tag shut")
    ui_text = code_only(read(folder, "tagall_ui.py"))
    if "thumb.MouseDoubleClick += self._edge_double" not in ui_text:
        problems.append(u"a double-click on the top or bottom edge does not fill the screen")
    if 'x:Name="LinksGrip"' not in layout or "DragDelta += ui.ui_safe(self, self._links_drag" not in window:
        problems.append(u"the linked models list cannot be dragged taller")
    if "core.toggle_family_group(" not in window:
        problems.append(u"a group header click does not go through core.toggle_family_group")
    return problems


def rule_buttons_have_icons(folder):
    """Every button carries an icon. A layout button is either in ICON_FOR,
    or exempt because its glyph is the whole button; a button built in code
    is made with icon_button, iconized, or is a glyph-only tree toggle."""
    problems = []
    icons, icon_for, exempt = _icon_tables(folder)
    if not icons or not icon_for:
        return [u"tagall_ui.py has no ICONS or ICON_FOR table"]
    for name, icon in icon_for.items():
        if icon not in icons:
            problems.append(u"{0} asks for icon '{1}', which ICONS does not draw".format(name, icon))
    for layout in xaml_files(folder):
        if layout == THEME_FILE:
            continue
        for name in re.findall(r'<Button\s+x:Name="(\w+)"', strip_xml_comments(read(folder, layout))):
            if name not in icon_for and name not in exempt:
                problems.append(u"{0}: button {1} has no icon".format(layout, name))
    everything = u"\n".join([read(folder, name) for name in python_files(folder)])
    if "ui.iconize_named(self.window)" not in everything:
        problems.append(u"the main window never iconizes its buttons")
    for name in python_files(folder):
        lines = code_only(read(folder, name)).splitlines()
        for number, line in enumerate(lines, 1):
            match = re.match(r"\s*(\w+)\s*=\s*Button\(\)", line)
            if not match:
                continue
            var = match.group(1)
            window = u"\n".join(read(folder, name).splitlines()[number - 1:number + 12])
            if ("iconize(" + var) in window or ('"TreeToggle"' in window) or name == "tagall_ui.py":
                continue
            problems.append(u"{0}:{1} builds a Button with no icon - use ui.icon_button".format(name, number))
    return problems


def rule_icon_labels_not_content(folder):
    """An iconized button keeps its icon in Content. Setting Content again
    throws the icon away, so its label changes through set_label."""
    problems = []
    _icons, icon_for, _exempt = _icon_tables(folder)
    for name in python_files(folder):
        text = code_only(read(folder, name))
        for match in re.finditer(r'(?:find|FindName)\(\s*"(\w+)"\s*\)\.Content\s*=', read(folder, name)):
            if match.group(1) in icon_for:
                problems.append(u"{0} sets Content on {1}, which throws its icon away - use ui.set_label".format(
                    name, match.group(1)))
    return problems


def rule_icon_paths_parse(folder):
    """WPF's path mini-language, checked here because Geometry.Parse throws
    inside a handler at run time - which would take the whole window down
    with it, since every button is iconized as the window opens."""
    problems = []
    icons, _icon_for, _exempt = _icon_tables(folder)
    for name, data in icons.items():
        if not data.strip().startswith("M"):
            problems.append(u"icon {0} does not start with a move (M)".format(name))
        stray = re.sub(r"[MLHVZAQCSmlhvzaqcs0-9.,\-\s]", u"", data)
        if stray:
            problems.append(u"icon {0} carries characters a path cannot: {1!r}".format(name, stray))
        for arc in re.findall(r"A([^MLHVZAQCS]*)", data):
            numbers = re.findall(r"-?\d+(?:\.\d+)?", arc)
            if len(numbers) % 7:
                problems.append(u"icon {0} has an arc without its seven numbers".format(name))
    return problems


def rule_position_boxes_select_all(folder):
    """Clicking into the X, Y and elbow boxes selects their contents, ready
    to type over."""
    problems = []
    text = read(folder, "tagall_window.py")
    match = re.search(r'for name in \(([^)]*)\):\s*\n\s*ui\.select_all_on_focus\(find\(name\)\)', text)
    named = set(re.findall(r'"(\w+)"', match.group(1))) if match else set()
    for box in ("OffsetX", "OffsetY", "ElbowMm"):
        if box not in named:
            problems.append(u"{0} does not select its text on focus".format(box))
    if "def select_all_on_focus" not in read(folder, "tagall_ui.py"):
        problems.append(u"tagall_ui.py has no select_all_on_focus")
    return problems


def rule_opening_reads_viewports(folder):
    """Picking views on a sheet selects Viewport elements, not views. 1.1.0
    read only View and ViewSheet out of the selection, so viewports picked
    on a sheet were silently ignored. The opening read has to turn a
    viewport into its view, and the window has to start each list through
    core.opening_scope rather than reading the selection itself."""
    problems = []
    model_text = read(folder, "tagall_model.py")
    match = re.search(r"def opening_context\(uidoc\):(.*?)\n(?=def )", model_text, flags=re.S)
    if not match:
        return [u"tagall_model.py has no opening_context"]
    body = code_only(match.group(1))
    if not re.search(r"isinstance\(element,\s*Viewport\)", body) or "element.ViewId" not in body:
        problems.append(u"opening_context does not turn a picked viewport into its view")
    if "isinstance(active, ViewSheet)" not in body or "placed_view_keys(active)" not in body:
        problems.append(u"opening_context does not read the views on the open sheet")
    window_text = code_only(read(folder, "tagall_window.py"))
    if "core.opening_scope(" not in window_text:
        problems.append(u"the window does not start its view lists through core.opening_scope")
    if "GetElementIds" in window_text:
        problems.append(u"the window reads the Revit selection itself - go through opening_context")
    return problems


def rule_combo_handler_after_start(folder):
    """A dropdown built in code takes its starting value before its
    SelectionChanged handler is attached. The other way round, drawing the
    tree reads as a pick: every category would save its default again on
    each search keystroke, and every new table row would count as picked by
    hand."""
    problems = []
    text = read(folder, "tagall_window.py")
    tree = ast.parse(text)
    lines = text.splitlines()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        last = max([getattr(child, "lineno", node.lineno) for child in ast.walk(node)])
        body = lines[node.lineno - 1:last]
        attached = {}
        for offset, line in enumerate(body):
            code = code_only(line)
            match = re.match(r"\s*(\w+)\.SelectionChanged\s*\+=", code)
            if match:
                attached.setdefault(match.group(1), offset)
                continue
            match = re.match(r"\s*(\w+)\.(?:SelectedItem|SelectedIndex)\s*=", code)
            # any value set once the handler is on is a value read as a pick
            if match and match.group(1) in attached:
                problems.append(u"tagall_window.py:{0} {1}: {2} is given a value after its "
                                u"SelectionChanged handler is attached".format(
                                    node.lineno + offset, node.name, match.group(1)))
    return problems


def rule_saved_settings_reload(folder, imported=None):
    """load_settings keeps only the keys DEFAULTS lists (and the default-tag
    prefix). A key the window saves that is missing from DEFAULTS is written
    to the file and dropped on the next load - a setting that looks
    remembered and never is."""
    problems = []
    core_module = (imported or {}).get("tagall_core")
    if core_module is None:
        return problems
    known = set(core_module.DEFAULTS.keys())
    text = read(folder, "tagall_window.py")
    match = re.search(r"    def collect_settings\(self\):(.*?)\n    def ", text, flags=re.S)
    if not match:
        return [u"tagall_window.py has no collect_settings"]
    body = match.group(1)
    keys = set(re.findall(r"s\[\s*u?\"(\w+)\"\s*\]\s*=", body))
    prefixes = set(re.findall(r",\s*u?\"(\w+)\"\)", body))
    for suffix in re.findall(r"s\[\s*prefix\s*\+\s*u?\"(\w+)\"\s*\]\s*=", body):
        for prefix in prefixes:
            keys.add(prefix + suffix)
    for key in sorted(keys):
        if key not in known:
            problems.append(u"collect_settings saves '{0}', which DEFAULTS does not list - it is "
                            u"dropped on the next load".format(key))
    return problems


def rule_tab_handler_ignores_bubbling(folder):
    """SelectionChanged bubbles. A ComboBox inside a TabControl raises it up
    through the TabControl, so a tab handler that does not check the tab
    really changed re-reads Categories every time a dropdown is picked."""
    problems = []
    text = read(folder, "tagall_window.py")
    match = re.search(r"    def _family_source_changed\(self, sender, args\):(.*?)\n    def ", text, flags=re.S)
    if not match:
        return [u"tagall_window.py has no _family_source_changed"]
    body = code_only(match.group(1))
    if not re.search(r"if index == self\.family_list_index:\s*\n\s*return", body):
        problems.append(u"_family_source_changed acts on every bubbled SelectionChanged, "
                        u"not only a change of tab")
    return problems


def rule_rows_follow_column_widths(folder):
    """A column drag changes the header's widths and every row's. A row grid
    built without registering itself stays at the old widths while the
    header moves, so the columns stop lining up under their headings."""
    problems = []
    text = read(folder, "tagall_window.py")
    match = re.search(r"class SheetTable\(object\):(.*?)\n(?:# =+ the view table)", text, flags=re.S)
    if not match:
        return [u"tagall_window.py has no SheetTable"]
    body = code_only(match.group(1))
    row = re.search(r"    def _row\(self, key, cells\):(.*?)\n    def ", body, flags=re.S)
    if not row or not re.search(r"grid = self\._row_grid\(\)\s*\n\s*self\.row_grids\.append\(grid\)", row.group(1)):
        problems.append(u"SheetTable._row builds a row grid that column drags never reach")
    apply_ = re.search(r"    def _apply_widths\(self\):(.*?)\n    def ", body, flags=re.S)
    if not apply_ or "self.row_grids" not in apply_.group(1) or "self.header_grid" not in apply_.group(1):
        problems.append(u"SheetTable._apply_widths does not reach both the header and every row")
    rebuild = re.search(r"    def rebuild\(self\):(.*?)\n    def ", body, flags=re.S)
    if not rebuild or "self.row_grids = []" not in rebuild.group(1):
        problems.append(u"SheetTable.rebuild keeps the grids of rows it has thrown away")
    return problems


def _calls(text, name):
    """The full text of every call to `name(...)` - dotted or not, as
    `ui.Chrome(` is - parentheses balanced; not its class statement, and not
    a word inside a longer name."""
    out = []
    for match in re.finditer(r"(?<!\w)" + name + r"\(", text):
        line_start = text.rfind("\n", 0, match.start()) + 1
        if text[line_start:match.start()].strip().startswith("class"):
            continue
        depth = 0
        for index in range(match.end() - 1, len(text)):
            if text[index] == "(":
                depth += 1
            elif text[index] == ")":
                depth -= 1
                if depth == 0:
                    out.append(text[match.start():index + 1])
                    break
    return out


def rule_every_window_shrinks(folder):
    """Every window the tool opens carries the shrink drawer: its layout has
    a ShrinkButton in the header, and the class that opens it hands that
    button to a drawer - through Chrome(shrink_button=...) or make_drawer.
    A button drawn but never wired is a dead button in the corner of every
    window."""
    problems = []
    for name in LAYOUTS:
        text = strip_xml_comments(read(folder, name))
        if 'x:Name="HeaderBar"' not in text:
            continue
        if 'x:Name="ShrinkButton"' not in text:
            problems.append(u"{0} has a header bar and no ShrinkButton".format(name))
    everything = u"\n".join([code_only(read(folder, name)) for name in python_files(folder)])
    raw = u"\n".join([read(folder, name) for name in python_files(folder)])
    for call in _calls(everything, "Chrome"):
        if "shrink_button=" not in call:
            problems.append(u"a Chrome is built without a shrink_button: {0}".format(call[:70]))
    ui_text = read(folder, "tagall_ui.py")
    prompt = re.search(r"class Prompt\(object\):(.*?)\n    def _drag", ui_text, flags=re.S)
    if not prompt or 'make_drawer(w, find("HeaderBar"), find("ShrinkButton"))' not in prompt.group(1):
        problems.append(u"the prompt window is built without a drawer")
    windows = len(re.findall(r'load_window\(\s*"(\w+\.xaml)"', raw))
    drawers = len([call for call in _calls(everything, "Chrome") if "shrink_button=" in call]) + \
        len(re.findall(r"make_drawer\(w,", everything))
    if drawers < windows:
        problems.append(u"{0} windows are loaded and only {1} drawers are built".format(windows, drawers))
    return problems


def rule_no_held_animation(folder):
    """An animation holds its end value and outranks every later plain
    assignment: a Top or Height animation left in place leaves a window that
    can never be moved or resized again, with nothing raised. The drawer
    writes plain values on a timer; nothing else may animate those two."""
    problems = []
    for name in python_files(folder):
        text = code_only(read(folder, name))
        for match in re.finditer(r"BeginAnimation\(\s*\w*\.?(TopProperty|HeightProperty)\s*,\s*(\w+)", text):
            if match.group(2) != "None":
                problems.append(u"{0} animates {1} - the drawer's timer is the only thing that "
                                u"moves a window's Top or Height".format(name, match.group(1)))
    return problems


def rule_keys_defer_to_drawer(folder):
    """While a window is parked, Escape, Enter and F11 have to reopen it.
    Each window's own key handler closes, answers or fills the screen on
    those keys, so each one hands the key to the drawer first."""
    problems = []
    text = read(folder, "tagall_ui.py")
    for owner in ("Chrome", "Prompt", "Results"):
        match = re.search(r"class " + owner + r"\(object\):.*?    def _key\(self, sender, args\):\n(.*?)\n    def ",
                          text, flags=re.S)
        if not match:
            problems.append(u"{0} has no _key".format(owner))
            continue
        lines = [line.strip() for line in code_only(match.group(1)).splitlines() if line.strip()]
        first = u" ".join(lines[:2])
        if "drawer" not in first:
            problems.append(u"{0}._key acts on a key before its drawer has had it".format(owner))
    return problems


def _function_node(folder, file_name, name):
    tree = ast.parse(read(folder, file_name))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _call_lines(node, name):
    lines = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            func = sub.func
            if (isinstance(func, ast.Name) and func.id == name) or \
                    (isinstance(func, ast.Attribute) and func.attr == name):
                lines.append(sub.lineno)
    return sorted(lines)


def rule_tag_tidy_hook(folder):
    """Tag Tidy is a separate tool that may not be installed, so Tag All
    never imports it at load - only tagall_tidy.load() does, from inside a
    run. run_family hands each view's tags to it after they are placed and
    before the TransactionGroup is assimilated, so the two are one undo, and
    nothing but tagall_ops calls the hook."""
    problems = []
    for name in python_files(folder):
        tree = ast.parse(read(folder, name))
        for node in tree.body:
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for module in names:
                if module.startswith("tidy_"):
                    problems.append(u"{0} imports {1} at load - Tag All would not open without "
                                    u"Tag Tidy".format(name, module))
    runner = _function_node(folder, "tagall_ops.py", "run_family")
    if runner is None:
        return problems + [u"tagall_ops.py has no run_family"]
    tidy_at = _call_lines(runner, "tidy_view")
    chunk_at = _call_lines(runner, "tag_chunk")
    assimilate_at = _call_lines(runner, "Assimilate")
    if not tidy_at:
        problems.append(u"run_family never hands its tags to Tag Tidy")
    elif chunk_at and tidy_at[0] < chunk_at[0]:
        problems.append(u"run_family tidies before the view's tags are placed")
    elif assimilate_at and tidy_at[-1] > assimilate_at[0]:
        problems.append(u"run_family tidies after the group is assimilated - two undo steps")
    for name in python_files(folder):
        if name == "tagall_ops.py":
            continue
        if "tidy_tags(" in code_only(read(folder, name)):
            problems.append(u"{0} calls the Tag Tidy hook outside a run".format(name))
    return problems


RULES = [
    ("xaml parses as XML", rule_xaml_parses),
    ("no StaticResource in a layout", rule_no_static_resource),
    ("every enum attribute value is a real member", rule_enum_attribute_values),
    ("every DynamicResource key is defined", rule_dynamic_keys_defined),
    ("styles match their TargetType", rule_style_targettype_matches),
    ("every FindName has an x:Name", rule_findname_has_xname),
    ("every x:Name is used", rule_xname_is_used),
    ("no f-strings", rule_no_fstrings),
    ("no print statements", rule_no_print),
    ("no bare .IntegerValue", rule_no_bare_integervalue),
    ("no System.Uri", rule_no_system_uri),
    ("non-ASCII only in u'' literals", rule_non_ascii_only_in_u_literals),
    ("tagall_clr is imported first", rule_clr_first),
    ("every namespace has its assembly referenced", rule_assembly_for),
    ("no clr.AddReference for RevitAPI", rule_no_revitapi_reference),
    ("both palettes carry the same keys", rule_palettes_match),
    ("every SetResourceReference key exists", rule_setresourcereference_keys_exist),
    ("nothing is defined twice", rule_no_duplicate_definitions),
    ("every global a function reaches for exists", rule_globals_exist),
    ("calls match their signatures", rule_call_arity),
    ("cross-module names exist", rule_cross_module_names),
    ("script.py is a thin loader", rule_thin_loader),
    ("the loader leaves a breadcrumb", rule_breadcrumb),
    ("no dispatcher pump in the write module", rule_no_pump_in_ops),
    ("the elbow is only set after a regenerate", rule_elbow_after_regenerate),
    ("the tag box is measured with the leader off", rule_box_measured_without_leader),
    ("the easter egg is armed on every window", rule_egg_anchor),
    ("no shared panel bundle.yaml is shipped", rule_no_shared_bundles),
    ("one version, in one place", rule_single_version),
    ("every wired handler is guarded", rule_handlers_guarded),
    ("every button carries an icon", rule_buttons_have_icons),
    ("no icon is drawn twice", rule_icons_drawn_once),
    ("the Family Tags groups, the links grip and the edge double-click are wired", rule_family_groups),
    ("an iconized button's label never goes through Content", rule_icon_labels_not_content),
    ("every icon is a valid path", rule_icon_paths_parse),
    ("the position boxes select their text on focus", rule_position_boxes_select_all),
    ("the opening read understands viewports", rule_opening_reads_viewports),
    ("a dropdown's handler is attached after its starting value", rule_combo_handler_after_start),
    ("every setting saved is one load keeps", rule_saved_settings_reload),
    ("the tab handler ignores bubbled selection changes", rule_tab_handler_ignores_bubbling),
    ("every sheet row follows the column widths", rule_rows_follow_column_widths),
    ("every window carries a wired shrink drawer", rule_every_window_shrinks),
    ("no animation holds a window's Top or Height", rule_no_held_animation),
    ("every window's keys go to its drawer first", rule_keys_defer_to_drawer),
    ("Tag Tidy is reached only from inside a run", rule_tag_tidy_hook),
]


def check(folder):
    problems = []
    imported, import_problems = import_modules(folder)
    if import_problems:
        problems.append(("modules load against a stub API", import_problems))
    for label, rule in RULES:
        try:
            if rule in (rule_globals_exist, rule_cross_module_names, rule_saved_settings_reload):
                found = rule(folder, imported)
            else:
                found = rule(folder)
        except Exception as error:
            found = [u"the rule itself threw: {0}: {1}".format(type(error).__name__, error)]
        if found:
            problems.append((label, found))
    return problems


# ============================================================
# selftest
# ============================================================
# Each entry breaks one rule on purpose and names the rule that has to
# notice. A rule nobody has tested is a rule that does not work.

BREAKAGES = [
    ("xaml parses as XML", "TagAll.xaml",
     "<!-- ============ header ============ -->", "<!-- ----------- header ----------- -->"),
    ("no StaticResource in a layout", "TagAll.xaml",
     'Style="{DynamicResource ChipButton}"', 'Style="{StaticResource ChipButton}"'),
    ("every enum attribute value is a real member", "TagAll.xaml",
     'VerticalAlignment="Bottom"', 'VerticalAlignment="Baseline"'),
    ("every DynamicResource key is defined", "TagAll.xaml",
     '{DynamicResource BlueTick}', '{DynamicResource BlueTickle}'),
    ("styles match their TargetType", "TagAll.xaml",
     '<Button x:Name="ThemeChip" Grid.Column="3" Style="{DynamicResource ChipButton}"',
     '<Button x:Name="ThemeChip" Grid.Column="3" Style="{DynamicResource Card}"'),
    ("every FindName has an x:Name", "tagall_window.py",
     'find("VersionText")', 'find("VersionTxt")'),
    ("every x:Name is used", "TagAll.xaml",
     '<TextBlock x:Name="StatusText"', '<TextBlock x:Name="StatusLine"'),
    ("no f-strings", "tagall_core.py",
     'def bool_text(value):', 'def bool_text(value):\n    _ = f"{value}"'),
    ("no print statements", "tagall_core.py",
     'def parse_bool(value, default=False):', 'def parse_bool(value, default=False):\n    print(value)'),
    ("no bare .IntegerValue", "tagall_model.py",
     'def invalid_id():', 'def invalid_id():\n    _ = ElementId(1).IntegerValue'),
    ("no System.Uri", "tagall_ui.py",
     'from System import Action', 'from System import Action, Uri'),
    ("non-ASCII only in u'' literals", "tagall_core.py",
     'TOOL_NAME = u"Tag All"', 'TOOL_NAME = u"Tag All"\nDASH = "\u2014"'),
    ("tagall_clr is imported first", "tagall_model.py",
     'import tagall_clr  # noqa: F401  (assemblies first)\nimport tagall_core as core',
     'import tagall_core as core'),
    ("every namespace has its assembly referenced", "tagall_clr.py",
     '"PresentationCore", "PresentationFramework"', '"PresentationFramework"'),
    ("no clr.AddReference for RevitAPI", "tagall_clr.py",
     'REFERENCED = {}', 'REFERENCED = {}\nclr.AddReference("RevitAPI")'),
    ("both palettes carry the same keys", "theme.py",
     '    "OnAccentBrush": "#1B1F24",     # a glyph on a light accent fill: the tick, a badge\n',
     ''),
    ("every SetResourceReference key exists", "tagall_window.py",
     'ui.set_brush(block, "Foreground", "RedBrush" if is_problem else "MutedBrush")',
     'ui.set_brush(block, "Foreground", "CrimsonBrush")'),
    ("nothing is defined twice", "tagall_core.py",
     'def bool_text(value):', 'def bool_text(value):\n    return u"1"\n\n\ndef bool_text(value):'),
    ("every global a function reaches for exists", "tagall_core.py",
     'def parse_int(value, default=0):', 'def parse_int(value, default=0):\n    return rounded_int(value)'),
    ("calls match their signatures", "tagall_core.py",
     'return percent(done, total) != last_percent', 'return percent(done) != last_percent'),
    ("cross-module names exist", "tagall_window.py",
     'core.percent(done, total)', 'core.percentage(done, total)'),
    ("script.py is a thin loader", "script.py",
     'import os\nimport sys\nimport traceback', 'import os\nimport sys\nimport traceback\nimport tagall_window'),
    ("the loader leaves a breadcrumb", "script.py",
     'core.remove_file(core.breadcrumb_path())', 'pass'),
    ("no dispatcher pump in the write module", "tagall_ops.py",
     'def short_error(error):', 'def short_error(error):\n    ui.pump(None)'),
    ("the tag box is measured with the leader off", "tagall_ops.py",
     '            if model.set_leader(tag, False):\n                switched.append(tag)',
     '            switched.append(tag)'),
    ("the elbow is only set after a regenerate", "tagall_ops.py",
     '    if leader:\n        try:\n            from Autodesk.Revit.DB import LeaderEndCondition',
     '    if leader:\n        tag.SetLeaderElbow(ref, model.to_xyz(head))\n        try:\n            from Autodesk.Revit.DB import LeaderEndCondition'),
    ("the easter egg is armed on every window", "tagall_window.py",
     'ui.attach_egg(self.window, find("LogoHost"), self.mode)', 'pass'),
    ("no shared panel bundle.yaml is shipped", "..bundle.yaml", None, "title: Annotation\n"),
    ("one version, in one place", "tagall_ui.py",
     'HERE = os.path.dirname(os.path.abspath(__file__))', '__version__ = "9.9.9"\nHERE = os.path.dirname(os.path.abspath(__file__))'),
    ("the elbow is only set after a regenerate", "tagall_ops.py",
     "        doc.Regenerate()\n        for tag, ref, corners in moved:",
     "        for tag, ref, corners in moved:"),
    ("no icon is drawn twice", "tagall_ui.py",
     '    "unshrink": "M2.5,2.5', '    "expand": "M2.5,2.5'),
    ("the Family Tags groups, the links grip and the edge double-click are wired", "tagall_window.py",
     '        self._setup_groups()\n', '\n'),
    ("the Family Tags groups, the links grip and the edge double-click are wired", "tagall_window.py",
     "MouseLeftButtonUp += self._make_header_click(group)", "MouseLeftButtonUp += self._make_group_click(group)"),
    ("the Family Tags groups, the links grip and the edge double-click are wired", "tagall_window.py",
     "        self._slide_groups(before)\n", "        self._paint_groups()\n"),
    ("the Family Tags groups, the links grip and the edge double-click are wired", "tagall_window.py",
     '            self._slide_groups(before)\n        return ui.ui_safe(self, handler, "what to tag',
     '            self._paint_groups()\n        return ui.ui_safe(self, handler, "what to tag'),
    ("the Family Tags groups, the links grip and the edge double-click are wired", "tagall_window.py",
     "        self._show_links(False)", "        self._show_links(bool(links))"),
    ("the Family Tags groups, the links grip and the edge double-click are wired", "tagall_window.py",
     "                self.window.Height = core.slide_height(",
     "                pass  # core.slide_height("),
    ("the Family Tags groups, the links grip and the edge double-click are wired", "tagall_window.py",
     "core.remembered_family_tag(self.owner.settings, node.category, node.family)",
     "core.remembered_tag(self.owner.settings, node.category)"),
    ("the Family Tags groups, the links grip and the edge double-click are wired", "tagall_window.py",
     "        self._paint_after_placing()\n", "\n"),
    ("the Family Tags groups, the links grip and the edge double-click are wired", "tagall_ui.py",
     "                thumb.MouseDoubleClick += self._edge_double", "                pass"),
    ("the Family Tags groups, the links grip and the edge double-click are wired", "tagall_window.py",
     "        self.groups_open = core.show_families_group(self.groups_open)\n", "\n"),
    ("the Family Tags groups, the links grip and the edge double-click are wired", "TagAll.xaml",
     'x:Name="FamiliesGroupBody"', 'x:Name="FamiliesGroupInner"'),
    ("every button carries an icon", "TagAll.xaml",
     '<Button x:Name="ClearTable" Grid.Column="5"', '<Button x:Name="ClearTableNow" Grid.Column="5"'),
    ("an iconized button's label never goes through Content", "tagall_window.py",
     'ui.set_label(self.find("ThemeChip"), core.theme_label(self.mode))',
     'self.find("ThemeChip").Content = core.theme_label(self.mode)'),
    ("every icon is a valid path", "tagall_ui.py",
     '"add": "M8,2.5 L8,13.5 M2.5,8 L13.5,8",', '"add": "M8,2.5 L8,13.5 M2.5,8 L13.5,8 #",'),
    ("the position boxes select their text on focus", "tagall_window.py",
     'for name in ("OffsetX", "OffsetY", "ElbowMm"):', 'for name in ("OffsetX", "OffsetY"):'),
    ("the opening read understands viewports", "tagall_model.py",
     "        if Viewport is not None and isinstance(element, Viewport):",
     "        if False:"),
    ("the opening read understands viewports", "tagall_model.py",
     "            out[\"sheet_views\"] = placed_view_keys(active)",
     "            out[\"sheet_views\"] = []"),
    ("a dropdown's handler is attached after its starting value", "tagall_window.py",
     "        combo.SelectedItem = chosen\n        combo.SelectionChanged += handler\n        return combo",
     "        combo.SelectionChanged += handler\n        combo.SelectedItem = chosen\n        return combo"),
    ("every setting saved is one load keeps", "tagall_core.py",
     '    "family_sheet_group_1": u"",      # sheet parameter names; blank = first suitable\n',
     ''),
    ("the tab handler ignores bubbled selection changes", "tagall_window.py",
     "        if index == self.family_list_index:\n            return\n",
     ""),
    ("every sheet row follows the column widths", "tagall_window.py",
     "        grid = self._row_grid()\n        self.row_grids.append(grid)\n",
     "        grid = self._row_grid()\n"),
    ("every window carries a wired shrink drawer", "TagAllResults.xaml",
     '<Button x:Name="ShrinkButton" Grid.Column="3"', '<Button x:Name="ShrinkButtonGone" Grid.Column="3"'),
    ("every window carries a wired shrink drawer", "tagall_window.py",
     ', find("FullScreenButton"),\n                                shrink_button=find("ShrinkButton"))',
     ', find("FullScreenButton"))'),
    ("every window carries a wired shrink drawer", "tagall_ui.py",
     '        self.drawer = make_drawer(w, find("HeaderBar"), find("ShrinkButton"))',
     '        self.drawer = None'),
    ("no animation holds a window's Top or Height", "tagall_ui.py",
     'def make_drawer(window, header, button):',
     'def _slide_top(window, animation):\n    window.BeginAnimation(Window.TopProperty, animation)\n\n\ndef make_drawer(window, header, button):'),
    ("every window's keys go to its drawer first", "tagall_ui.py",
     "        # parked, Escape and Enter reopen the prompt rather than answer it\n        if drawer_key(self.drawer, args):\n            return\n",
     ""),
    ("every wired handler is guarded", "tagall_window.py",
     'find("CloseButton").Click += ui.ui_safe(self, self._close_click, "close")',
     'find("CloseButton").Click += self._close_click'),
    ("Tag Tidy is reached only from inside a run", "tagall_tidy.py",
     "import tagall_core as core\n", "import tagall_core as core\nimport tidy_hook\n"),
    ("Tag Tidy is reached only from inside a run", "tagall_ops.py",
     "        if spec.options.get(\"tidy\") and spec.options.get(\"untangle\"):\n"
     "            result.note(u\"Untangle was skipped: Tag Tidy lays the new tags out instead.\")\n"
     "        group.Assimilate()",
     "        group.Assimilate()\n        tidy_view(doc, plans[0], [], spec, result)"),
]


def apply_breakage(folder, file_name, find_text, replace_text):
    if file_name == "..bundle.yaml":
        with io.open(os.path.join(os.path.dirname(folder), "bundle.yaml"), "w", encoding="utf-8") as handle:
            handle.write(replace_text)
        return True
    path = os.path.join(folder, file_name)
    with io.open(path, "r", encoding="utf-8") as handle:
        text = handle.read()
    if find_text not in text:
        return False
    text = text.replace(find_text, replace_text, 1)
    with io.open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return True


def selftest():
    passed = 0
    failed = []
    for label, file_name, find_text, replace_text in BREAKAGES:
        if find_text is not None and find_text == replace_text:
            failed.append(u"{0}: the breakage changes nothing".format(label))
            continue
        scratch = tempfile.mkdtemp()
        try:
            work = os.path.join(scratch, "panel", "tool")
            os.makedirs(os.path.dirname(work))
            shutil.copytree(HERE, work, ignore=IGNORE_CACHE)
            if not apply_breakage(work, file_name, find_text, replace_text):
                failed.append(u"{0}: could not apply the breakage to {1}".format(label, file_name))
                continue
            found = dict(check(work))
            if label in found:
                passed += 1
            else:
                failed.append(u"{0}: the rule did not fire. Rules that did: {1}".format(
                    label, u", ".join(sorted(found.keys())) or u"none"))
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
    return passed, failed


def main():
    if "--selftest" in sys.argv:
        passed, failed = selftest()
        total = len(BREAKAGES)
        for line in failed:
            sys.stdout.write(u"FAIL  {0}\n".format(line))
        sys.stdout.write(u"\nselftest: {0} of {1} rules caught their own breakage\n".format(passed, total))
        return 0 if passed == total and not failed else 1

    problems = check(HERE)
    if not problems:
        sys.stdout.write(u"import_check: {0} rules, all clean\n".format(len(RULES) + 1))
        return 0
    for label, found in problems:
        sys.stdout.write(u"\n{0}\n".format(label))
        for line in found:
            sys.stdout.write(u"    {0}\n".format(line))
    sys.stdout.write(u"\nimport_check: {0} rule(s) with something to say\n".format(len(problems)))
    return 1


if __name__ == "__main__":
    sys.exit(main())
