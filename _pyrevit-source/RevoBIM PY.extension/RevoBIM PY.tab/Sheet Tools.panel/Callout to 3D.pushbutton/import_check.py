# -*- coding: utf-8 -*-
"""Callout to 3D - the bench check.

Run under plain CPython from this folder:

    python import_check.py
    python import_check.py --selftest

It loads every shipped module against a stub Revit and .NET API that declares
each name in the namespace the real API puts it in, so a mis-namespaced import
fails here instead of showing up in Revit as a blank white pyRevit window, and
then runs a set of static rules over the source and the XAML.

--selftest breaks each rule on purpose and confirms the check catches it.  A
rule nobody has tested is a rule that does not work.
"""

from __future__ import print_function

import os
import re
import shutil
import subprocess
import sys
import tempfile
import types
import xml.dom.minidom

HERE = os.path.dirname(os.path.abspath(__file__))

MODULES = ["c3d_clr", "c3d_core", "c3d_geom", "c3d_model", "c3d_ops",
           "theme", "c3d_ui", "c3d_preview", "c3d_sheet", "c3d_grid", "c3d_debug",
           "c3d_settings", "c3d_window"]

LAYOUTS = ["CalloutTo3D.xaml", "CalloutTo3DSettings.xaml", "CalloutTo3DPrompt.xaml"]
THEME = "Theme.xaml"

SCRIPTS = ["script.py"]

# ---------------------------------------------------------------------------
# the stub API - each name declared in the namespace the real API puts it in
# ---------------------------------------------------------------------------

NAMESPACES = {
    "Autodesk": [],
    "Autodesk.Revit": [],
    "Autodesk.Revit.DB": [
        "BoundingBoxXYZ", "Transform", "XYZ", "ElementId", "BuiltInParameter",
        "BuiltInCategory", "FilteredElementCollector", "View", "ViewPlan",
        "ViewSection", "View3D", "ViewSheet", "Viewport", "ElementType",
        "FamilySymbol", "Level", "ViewFamilyType", "ViewFamily", "StorageType",
        "Transaction", "TransactionGroup", "TransactionStatus", "Element",
        "IFailuresPreprocessor", "FailureProcessingResult", "ViewDuplicateOption",
        "ElementTransformUtils", "ViewOrientation3D", "ElementTypeGroup",
        "WorksharingUtils", "PlumbingUtils", "Line", "Curve", "Solid", "Grid", "DatumEnds",
        "DatumExtentType",
        "Options", "Reference", "UnitUtils", "Document", "Category",
    ],
    "Autodesk.Revit.DB.Architecture": ["Room"],
    "Autodesk.Revit.DB.Plumbing": ["Pipe", "PipeType"],
    "Autodesk.Revit.UI": [
        "IExternalEventHandler", "ExternalEvent", "TaskDialog",
        "TaskDialogCommonButtons", "TaskDialogResult", "UIThemeManager",
        "UIApplication", "UIDocument",
    ],
    "System": ["Object", "Action", "AppDomain", "Uri", "String", "Array",
               "Convert", "Math", "Exception", "TimeSpan", "Double"],
    "System.Collections.Generic": ["List", "Dictionary"],
    "System.Diagnostics": ["Process"],
    "System.Drawing": ["Point", "Rectangle", "Size"],
    "System.IO": ["FileStream", "FileMode", "FileAccess", "MemoryStream", "File",
                  "Path", "Directory"],
    "System.IO.Compression": ["ZipArchive", "ZipArchiveMode"],
    "System.Windows": [
        "DataTemplate", "FrameworkElement", "FrameworkElementFactory",
        "Thickness", "HorizontalAlignment", "VerticalAlignment", "FontWeights",
        "TextTrimming", "CornerRadius", "GridLength", "GridUnitType",
        "RoutedEventHandler", "PresentationSource", "SystemParameters",
        "Visibility", "TextWrapping", "Point", "Window", "ResourceDictionary",
        "TextAlignment", "PropertyPath", "Application", "MessageBox", "Clipboard",
        "WindowStyle", "SizeToContent", "WindowStartupLocation", "Size",
    ],
    "System.Windows.Controls": [
        "TextBlock", "CheckBox", "TextBox", "Button", "StackPanel",
        "Orientation", "DataGridTemplateColumn", "DataGridLength",
        "DataGridLengthUnitType", "Grid", "ColumnDefinition", "RowDefinition",
        "Border", "ScrollViewer", "Image", "ComboBox", "ComboBoxItem", "Canvas",
        "ListBox", "ListBoxItem", "DataGrid", "ToolTip", "Label", "Separator",
    ],
    "System.Windows.Controls.Primitives": ["Popup", "PlacementMode", "Thumb",
                                           "ButtonBase", "ToggleButton"],
    "System.Windows.Data": ["Binding", "IValueConverter", "BindingMode"],
    "System.Windows.Input": ["Cursors", "Key", "MouseButtonEventHandler",
                             "KeyEventHandler", "Keyboard", "ModifierKeys"],
    "System.Windows.Interop": ["WindowInteropHelper"],
    "System.Windows.Markup": ["XamlReader"],
    "System.Windows.Media": ["SolidColorBrush", "ColorConverter", "Geometry",
                             "Stretch", "DoubleCollection", "PointCollection",
                             "Brushes", "Color", "Brush", "CompositionTarget", "FontFamily",
                             "RotateTransform"],
    "System.Windows.Media.Imaging": ["BitmapImage", "BitmapCacheOption"],
    "System.Windows.Shapes": ["Line", "Rectangle", "Polygon", "Ellipse", "Path"],
    "System.Windows.Threading": ["DispatcherPriority", "DispatcherTimer"],
    "System.Windows.Forms": ["Screen"],
}

# which assembly has to be referenced before a namespace can be reached at all
ASSEMBLY_FOR = {
    "Autodesk.Revit.DB": "RevitAPI",
    "Autodesk.Revit.DB.Architecture": "RevitAPI",
    "Autodesk.Revit.DB.Plumbing": "RevitAPI",
    "Autodesk.Revit.UI": "RevitAPIUI",
    "System.Windows": "PresentationFramework",
    "System.Windows.Controls": "PresentationFramework",
    "System.Windows.Controls.Primitives": "PresentationFramework",
    "System.Windows.Data": "PresentationFramework",
    "System.Windows.Input": "PresentationCore",
    "System.Windows.Interop": "PresentationCore",
    "System.Windows.Markup": "PresentationFramework",
    "System.Windows.Media": "PresentationCore",
    "System.Windows.Media.Imaging": "PresentationCore",
    "System.Windows.Shapes": "PresentationFramework",
    "System.Windows.Threading": "WindowsBase",
    "System.Windows.Forms": "System.Windows.Forms",
    "System.Drawing": "System.Drawing",
    "System.IO.Compression": "System.IO.Compression",
}


class _StubMeta(type):
    """Every stub is a class rather than an instance, so a shipped module can
    subclass it the way it subclasses IExternalEventHandler or
    IValueConverter."""

    def __getattr__(cls, item):
        if item.startswith("__"):
            raise AttributeError(item)
        return make_stub("{0}.{1}".format(getattr(cls, "_stub_name", "stub"), item))

    def __getitem__(cls, item):
        # generic .NET types are written List[Object] in IronPython
        return cls


def _instance_getattr(self, item):
    if item.startswith("__"):
        raise AttributeError(item)
    return make_stub("{0}.{1}".format(getattr(self, "_stub_name", "stub"), item))


def make_stub(name):
    body = {
        "_stub_name": name,
        "__getattr__": _instance_getattr,
        "__init__": lambda self, *args, **kwargs: None,
        "__call__": lambda self, *args, **kwargs: make_stub(name + "()")(),
        "__repr__": lambda self: "<stub {0}>".format(name),
        "__iter__": lambda self: iter([]),
    }
    return _StubMeta(str("Stub_" + re.sub(r"\W", "_", name)), (object,), body)


class StubNamespace(types.ModuleType):
    """A module that only hands over the names the real namespace declares."""

    def __init__(self, name, allowed):
        types.ModuleType.__init__(self, name)
        self._allowed = set(allowed)
        self.__path__ = []

    def __getattr__(self, item):
        if item.startswith("__"):
            raise AttributeError(item)
        child = "{0}.{1}".format(self.__name__, item)
        if child in sys.modules:
            return sys.modules[child]
        if item in self._allowed:
            return make_stub(child)
        raise ImportError(
            "cannot import name {0} - {1} does not declare it. Check which "
            "namespace the real API puts it in.".format(item, self.__name__))


class StubClr(types.ModuleType):
    def __init__(self):
        types.ModuleType.__init__(self, "clr")
        self.referenced = []

    def AddReference(self, name):
        self.referenced.append(name)
        return None

    def AddReferenceByName(self, name):
        return self.AddReference(name)


def install_stubs():
    """Put the stub API in sys.modules.  Returns the clr stub so a caller can
    see which assemblies were asked for."""
    clr_stub = StubClr()
    sys.modules["clr"] = clr_stub
    for name in sorted(NAMESPACES.keys()):
        module = StubNamespace(name, NAMESPACES[name])
        sys.modules[name] = module
    for name in sorted(NAMESPACES.keys()):
        if "." not in name:
            continue
        parent_name, leaf = name.rsplit(".", 1)
        parent = sys.modules.get(parent_name)
        if parent is not None:
            setattr(parent, leaf, sys.modules[name])
    return clr_stub


# ---------------------------------------------------------------------------
# source helpers
# ---------------------------------------------------------------------------


def read(path):
    handle = open(path, "rb")
    try:
        return handle.read().decode("utf-8")
    finally:
        handle.close()


_STRING_START = re.compile(r"""(?P<prefix>[uUbBrRfF]{0,2})(?P<quote>'''|\"\"\"|'|\")""")


def code_only(text):
    """Blank out comments and the inside of every string, keeping the same
    number of characters so line and column numbers still line up, and keeping
    the quote characters and their prefixes so a rule about f-strings still
    sees them.  Token spacing has to survive or rules silently stop firing."""
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
        match = _STRING_START.match(text, index)
        if match and match.group("quote"):
            prefix = match.group("prefix")
            quote = match.group("quote")
            if prefix and index > 0 and (text[index - 1].isalnum() or text[index - 1] == "_"):
                out.append(char)
                index += 1
                continue
            out.append(prefix)
            out.append(quote)
            index = match.end()
            while index < length:
                if text[index] == "\\":
                    out.append("  ")
                    index += 2
                    continue
                if text.startswith(quote, index):
                    out.append(quote)
                    index += len(quote)
                    break
                out.append("\n" if text[index] == "\n" else " ")
                index += 1
            continue
        out.append(char)
        index += 1
    return "".join(out)


def parse_xml(path):
    return xml.dom.minidom.parse(path)


def xaml_text(path):
    return read(path)


def theme_keys(root):
    text = xaml_text(os.path.join(root, THEME))
    return set(re.findall(r'x:Key="([^"]+)"', text))


def theme_target_types(root):
    text = xaml_text(os.path.join(root, THEME))
    found = {}
    for match in re.finditer(r'<Style([^>]*)>', text):
        chunk = match.group(1)
        key = re.search(r'x:Key="([^"]+)"', chunk)
        target = re.search(r'TargetType="([^"]+)"', chunk)
        if key and target:
            found[key.group(1)] = target.group(1)
    return found


# ---------------------------------------------------------------------------
# the rules
# ---------------------------------------------------------------------------


def rule_xaml_parses(root, problems):
    for name in LAYOUTS + [THEME]:
        path = os.path.join(root, name)
        if not os.path.isfile(path):
            problems.append(("xaml_parses", "{0} is missing".format(name)))
            continue
        try:
            parse_xml(path)
        except Exception as err:
            problems.append(("xaml_parses", "{0} will not parse as XML: {1}".format(name, err)))


def rule_xml_comment_dashes(root, problems):
    for name in LAYOUTS + [THEME]:
        path = os.path.join(root, name)
        if not os.path.isfile(path):
            continue
        for number, line in enumerate(read(path).splitlines(), 1):
            for comment in re.findall(r"<!--(.*?)-->", line):
                if "--" in comment:
                    problems.append(("xml_comment_dashes",
                                     "{0} line {1}: a run of hyphens inside an XML "
                                     "comment. Draw banners with '='".format(name, number)))


def _module_files(root):
    files = []
    for name in MODULES:
        files.append((name + ".py", os.path.join(root, name + ".py")))
    for name in SCRIPTS:
        files.append((name, os.path.join(root, name)))
    return files


def referenced_assemblies(root):
    """The ASSEMBLIES list out of c3d_clr, read with ast rather than a regex -
    a regex over the source pairs quotes wrongly across a docstring and comes
    back empty, which would turn this rule off without saying so."""
    import ast
    tree = ast.parse(read(os.path.join(root, "c3d_clr.py")))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if getattr(target, "id", None) == "ASSEMBLIES":
                    try:
                        return set(ast.literal_eval(node.value))
                    except Exception:
                        return set()
    return set()


def rule_clr_first(root, problems):
    """No module may reach into System.* or Autodesk.* before importing
    c3d_clr, and the assembly its namespace needs must be in c3d_clr."""
    referenced = referenced_assemblies(root)
    if not referenced:
        problems.append(("clr_first", "c3d_clr declares no ASSEMBLIES at all"))
    for label, path in _module_files(root):
        if not os.path.isfile(path):
            problems.append(("clr_first", "{0} is missing".format(label)))
            continue
        if label == "c3d_clr.py":
            continue
        source = code_only(read(path))
        clr_line = None
        for number, line in enumerate(source.splitlines(), 1):
            if re.match(r"\s*import\s+c3d_clr", line):
                clr_line = number
                break
        for number, line in enumerate(source.splitlines(), 1):
            match = re.match(r"\s*(?:from|import)\s+((?:System|Autodesk)[\w\.]*)", line)
            if not match:
                continue
            namespace = match.group(1)
            if clr_line is None:
                problems.append(("clr_first",
                                 "{0} line {1} reaches into {2} but never imports "
                                 "c3d_clr".format(label, number, namespace)))
                continue
            if label.endswith("script.py") and namespace.startswith("Autodesk.Revit"):
                # the staged loader's failure reporter has to be able to raise a
                # Revit dialog even when c3d_clr is the thing that failed
                continue
            if number < clr_line:
                problems.append(("clr_first",
                                 "{0} line {1} reaches into {2} before c3d_clr is "
                                 "imported on line {3}".format(label, number, namespace,
                                                               clr_line)))
            assembly = ASSEMBLY_FOR.get(namespace)
            if assembly and assembly not in referenced:
                problems.append(("clr_first",
                                 "{0} uses {1}, which needs clr.AddReference('{2}') "
                                 "in c3d_clr".format(label, namespace, assembly)))


def rule_no_static_resource(root, problems):
    for name in LAYOUTS:
        path = os.path.join(root, name)
        if not os.path.isfile(path):
            continue
        for number, line in enumerate(read(path).splitlines(), 1):
            if "StaticResource" in line:
                problems.append(("no_static_resource",
                                 "{0} line {1} uses StaticResource. Theme.xaml is merged "
                                 "in after the layout is parsed".format(name, number)))


def rule_dynamic_keys_exist(root, problems):
    keys = theme_keys(root)
    for name in LAYOUTS:
        path = os.path.join(root, name)
        if not os.path.isfile(path):
            continue
        text = read(path)
        for number, line in enumerate(text.splitlines(), 1):
            for key in re.findall(r"\{DynamicResource ([^}]+)\}", line):
                if key.strip() not in keys:
                    problems.append(("dynamic_keys_exist",
                                     "{0} line {1} asks for {2}, which Theme.xaml does "
                                     "not define".format(name, number, key.strip())))


def rule_style_target_matches(root, problems):
    targets = theme_target_types(root)
    for name in LAYOUTS:
        path = os.path.join(root, name)
        if not os.path.isfile(path):
            continue
        text = read(path)
        for match in re.finditer(r"<([A-Za-z][\w\.]*)([^>]*?)>", text, re.S):
            element = match.group(1)
            chunk = match.group(2)
            style = re.search(r'Style="\{DynamicResource ([^}]+)\}"', chunk)
            if not style:
                continue
            key = style.group(1).strip()
            target = targets.get(key)
            if target and target != element:
                problems.append(("style_target_matches",
                                 "{0}: {1} carries {2}, whose TargetType is {3}. WPF "
                                 "raises when the style is applied, which shows as a dead "
                                 "window".format(name, element, key, target)))


def rule_findname_has_xname(root, problems):
    names = {}
    for layout in LAYOUTS:
        path = os.path.join(root, layout)
        if os.path.isfile(path):
            names[layout] = set(re.findall(r'x:Name="([^"]+)"', read(path)))
    declared = set()
    for values in names.values():
        declared |= values

    for label, path in _module_files(root):
        if not os.path.isfile(path):
            continue
        source = read(path)
        # both the literal call and the aliased form, since the code does
        # find = self.window.FindName
        for match in re.finditer(r'(?:FindName|self\.find|find)\(\s*"([^"]+)"\s*\)', source):
            key = match.group(1)
            if key not in declared:
                problems.append(("findname_has_xname",
                                 "{0} looks for '{1}', which no layout declares as "
                                 "x:Name".format(label, key)))


def rule_no_fstrings(root, problems):
    for label, path in _module_files(root):
        if not os.path.isfile(path):
            continue
        source = code_only(read(path))
        for number, line in enumerate(source.splitlines(), 1):
            if re.search(r"(?<![A-Za-z0-9_])[fF]['\"]", line):
                problems.append(("no_fstrings",
                                 "{0} line {1} uses an f-string. IronPython 2.7 has "
                                 "none".format(label, number)))


def rule_no_print(root, problems):
    for label, path in _module_files(root):
        if not os.path.isfile(path):
            continue
        source = code_only(read(path))
        for number, line in enumerate(source.splitlines(), 1):
            if re.search(r"(?<![A-Za-z0-9_.])print\s*\(", line):
                problems.append(("no_print",
                                 "{0} line {1} calls print, which opens a pyRevit output "
                                 "window".format(label, number)))


def rule_no_bare_integervalue(root, problems):
    for label, path in _module_files(root):
        if not os.path.isfile(path):
            continue
        source = code_only(read(path))
        for number, line in enumerate(source.splitlines(), 1):
            if ".IntegerValue" not in line:
                continue
            if label == "c3d_core.py":
                continue           # the guarded eid_value helper lives there
            problems.append(("no_bare_integervalue",
                             "{0} line {1} touches .IntegerValue, which Revit 2026 "
                             "removed. Go through eid_value".format(label, number)))


def rule_no_system_uri(root, problems):
    for label, path in _module_files(root):
        if not os.path.isfile(path):
            continue
        source = code_only(read(path))
        for number, line in enumerate(source.splitlines(), 1):
            if re.search(r"from\s+System\s+import\s+.*\bUri\b", line) or \
               re.search(r"\bSystem\.Uri\b", line):
                problems.append(("no_system_uri",
                                 "{0} line {1} uses System.Uri, which moved assemblies "
                                 "in Revit 2025".format(label, number)))


def rule_palette_covers_theme(root, problems):
    keys = theme_keys(root)
    text = read(os.path.join(root, "theme.py"))
    dark = set(re.findall(r'"(\w+Brush)"\s*:', text.split("LIGHT")[0]))
    light = set(re.findall(r'"(\w+Brush)"\s*:', text.split("LIGHT")[1].split("PALETTES")[0]))
    brush_keys = set([key for key in keys if key.endswith("Brush")])
    for key in sorted(brush_keys):
        if key not in dark:
            problems.append(("palette_covers_theme",
                             "the dark palette has no {0}".format(key)))
        if key not in light:
            problems.append(("palette_covers_theme",
                             "the light palette has no {0}".format(key)))
    for key in sorted(dark):
        if key not in brush_keys:
            problems.append(("palette_covers_theme",
                             "Theme.xaml has no brush called {0}".format(key)))


def rule_resource_keys_exist(root, problems):
    """Every key asked for from Python has to be in Theme.xaml."""
    keys = theme_keys(root)
    for label, path in _module_files(root):
        if not os.path.isfile(path):
            continue
        source = read(path)
        for match in re.finditer(r'(?:TryFindResource|FindResource|SetResourceReference)'
                                 r'\(\s*"([^"]+)"', source):
            key = match.group(1)
            if key not in keys:
                problems.append(("resource_keys_exist",
                                 "{0} asks for the resource '{1}', which Theme.xaml does "
                                 "not define".format(label, key)))
        for match in re.finditer(r'window\.Resources\[\s*"([^"]+)"\s*\]', source):
            key = match.group(1)
            if key not in keys:
                problems.append(("resource_keys_exist",
                                 "{0} writes the resource '{1}', which Theme.xaml does "
                                 "not define".format(label, key)))


def rule_globals_exist(root, problems):
    """Every global name a function reaches for exists in its module.  This is
    the rule that catches a helper deleted by a block rewrite."""
    import symtable
    for label, path in _module_files(root):
        if not os.path.isfile(path):
            continue
        source = read(path)
        try:
            table = symtable.symtable(source, label, "exec")
        except SyntaxError as err:
            problems.append(("globals_exist", "{0} will not compile: {1}".format(label, err)))
            continue
        top = set(table.get_identifiers())
        builtins = set(dir(__builtins__) if isinstance(__builtins__, type(sys)) else __builtins__)
        builtins |= set(["__file__", "__name__", "__doc__", "unicode", "xrange",
                         "basestring", "long", "reduce", "__revit__", "self"])

        def walk(node):
            for child in node.get_children():
                for symbol in child.get_symbols():
                    if symbol.is_global() and not symbol.is_assigned():
                        name = symbol.get_name()
                        if name not in top and name not in builtins:
                            problems.append((
                                "globals_exist",
                                "{0}: {1} reaches for '{2}', which the module does not "
                                "define".format(label, child.get_name(), name)))
                walk(child)

        walk(table)


def rule_egg_wired(root, problems):
    """The easter egg has to be wired to the RevoBIM logo in every window.

    The canonical rule lives in lib\\revobim\\egg\\egg_rule.py; it is imported
    from there when the extension root is reachable, and the equivalent check
    runs locally when it is not, so the bench still works on a copy of just
    this folder.
    """
    shared = os.path.abspath(os.path.join(root, "..", "..", "..", "lib", "revobim", "egg"))
    if os.path.isdir(shared):
        if shared not in sys.path:
            sys.path.insert(0, shared)
        try:
            import egg_rule
            for entry in ("check", "rule", "run"):
                function = getattr(egg_rule, entry, None)
                if function is None:
                    continue
                try:
                    found = function(root)
                except TypeError:
                    found = function()
                for line in (found or []):
                    problems.append(("egg_wired", "{0}".format(line)))
                return
        except Exception as err:
            problems.append(("egg_wired",
                             "the shared egg rule would not run ({0}); the local "
                             "equivalent ran instead".format(err)))

    for layout in LAYOUTS:
        path = os.path.join(root, layout)
        if not os.path.isfile(path):
            continue
        if 'x:Name="LogoZone"' not in read(path):
            problems.append(("egg_wired",
                             "{0} has no LogoZone for the egg to hang off".format(layout)))

    ui_source = read(os.path.join(root, "c3d_ui.py"))
    if "class EggWatcher" not in ui_source:
        problems.append(("egg_wired", "c3d_ui.py has no EggWatcher"))
    if "launch_egg" not in ui_source or "revobim.egg" not in ui_source:
        problems.append(("egg_wired", "c3d_ui.py does not reach for lib/revobim/egg"))
    if not re.search(r"len\(self\.clicks\)\s*>=\s*3", ui_source):
        problems.append(("egg_wired", "the egg does not open on three clicks"))
    if not re.search(r"MIN_GAP\s*=", ui_source):
        problems.append(("egg_wired", "the egg does not insist the clicks are slow"))

    for name in ("c3d_window.py", "c3d_settings.py"):
        source = read(os.path.join(root, name))
        if "EggWatcher" not in source or "LogoZone" not in source:
            problems.append(("egg_wired", "{0} does not wire the egg to its logo".format(name)))


def rule_names_match_folders(root, problems):
    """pyRevit names a ribbon item after its folder, so a rename has to reach
    the folder, the bundle and the window header together."""
    expected = "Callout to 3D"
    # one ribbon button since 2.1.0, with Settings behind the gear in its header
    if os.path.basename(root) != expected + ".pushbutton":
        problems.append(("names_match_folders",
                         "the button folder is not '{0}.pushbutton'".format(expected)))
    for stray in (expected + ".pushbutton", "Callout Settings.pushbutton"):
        if os.path.isdir(os.path.join(root, stray)):
            problems.append(("names_match_folders",
                             "'{0}' is nested inside the button - a leftover of the "
                             "old pulldown".format(stray)))
    core_source = read(os.path.join(root, "c3d_core.py"))
    match = re.search(r'TOOL_NAME\s*=\s*"([^"]+)"', core_source)
    if not match or match.group(1) != expected:
        problems.append(("names_match_folders",
                         "TOOL_NAME does not read '{0}'".format(expected)))
    layout = read(os.path.join(root, "CalloutTo3D.xaml"))
    if 'Text="{0}"'.format(expected) not in layout:
        problems.append(("names_match_folders",
                         "the window header does not read '{0}'".format(expected)))


def rule_modules_import(root, problems):
    """Load every module against the stub API."""
    install_stubs()
    if root not in sys.path:
        sys.path.insert(0, root)
    for name in MODULES:
        for cached in list(sys.modules.keys()):
            if cached in MODULES:
                del sys.modules[cached]
        try:
            __import__(name)
        except Exception as err:
            problems.append(("modules_import", "{0}: {1}".format(name, err)))


def rule_settings_round_trip(root, problems):
    """Every default has to survive a save and a load."""
    install_stubs()
    if root not in sys.path:
        sys.path.insert(0, root)
    for cached in list(sys.modules.keys()):
        if cached in MODULES:
            del sys.modules[cached]
    try:
        import c3d_core as core
    except Exception as err:
        problems.append(("settings_round_trip", "c3d_core will not load: {0}".format(err)))
        return
    handle, path = tempfile.mkstemp(suffix=".txt")
    os.close(handle)
    try:
        values = dict(core.DEFAULTS)
        values["sheet_name_pattern"] = "Callout_{abbrev}_{level} Detail {d}"
        # the size to title block map's value carries '=' signs of its own, so
        # this is what proves the loader splits on the first one only
        values["sheet_titleblocks"] = "A0=BGL_Title Block: A0|A1=BGL_Title Block: A1"
        core.save_settings(values, path)
        back = core.load_settings(path)
        for key in core.DEFAULTS:
            if key not in back:
                problems.append(("settings_round_trip", "{0} was lost".format(key)))
            elif u"{0}".format(back[key]) != u"{0}".format(values[key]):
                problems.append(("settings_round_trip",
                                 "{0} came back as '{1}' rather than '{2}'"
                                 .format(key, back[key], values[key])))
    finally:
        try:
            os.remove(path)
        except Exception:
            pass


def rule_no_duplicate_definitions(root, problems):
    """Nothing may be defined twice in one module.

    Python does not complain: it runs the first definition, throws it away and
    keeps the last.  A block rewrite that lands beside the block it was meant
    to replace therefore leaves the OLD code running, with the new code sitting
    right there in the file looking correct.  That cost several versions of
    "nothing changed" on the sheet layout - `_place_group` was written three
    times and the stale copy was the one Revit ran every time.
    """
    import ast
    for label, path in _module_files(root):
        if not os.path.isfile(path):
            continue
        try:
            tree = ast.parse(read(path))
        except SyntaxError as err:
            problems.append(("no_duplicate_definitions",
                             "{0} will not compile: {1}".format(label, err)))
            continue

        def check_body(body, where):
            seen = {}
            for node in body:
                if not isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                    continue
                if node.name in seen:
                    problems.append((
                        "no_duplicate_definitions",
                        "{0}: {1} is defined twice{2} - lines {3} and {4}. Python "
                        "keeps the last one, so the first is dead code".format(
                            label, node.name, where, seen[node.name], node.lineno)))
                seen[node.name] = node.lineno

        check_body(tree.body, "")
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                check_body(node.body, " in class {0}".format(node.name))


FIELD_KINDS = ("check", "text", "int", "float", "choice", "combo3d", "combosec",
               "combovp", "paramrows", "sizemap")


def rule_settings_have_readers(root, problems):
    """Every setting has something that reads it, and every settings field
    names a setting that exists.

    A key in DEFAULTS that nothing reads is a setting that looks like it works.
    v1.13 shipped two of them: the "picking a view family type offers its own
    template" feature had its keys and its lists, while the half of the patch
    that drew the tick boxes and wired the combos never landed - and nothing
    noticed for eight versions.  A settings field counts as a place the key is
    shown, never as a place it is read.
    """
    import ast
    core_source = read(os.path.join(root, "c3d_core.py"))
    tree = ast.parse(core_source)
    defaults, block = None, None
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", None) == "DEFAULTS":
            defaults = [key.value if hasattr(key, "value") else key.s for key in node.value.keys]
            block = (node.lineno, node.end_lineno)
    if not defaults:
        problems.append(("settings_have_readers", "c3d_core.py has no DEFAULTS"))
        return

    field = re.compile(r'\(\s*"(?:%s)"\s*,\s*"([^"]+)"' % "|".join(FIELD_KINDS))
    readers = {}
    shown = set()
    for label, path in _module_files(root):
        if not os.path.isfile(path):
            continue
        for number, line in enumerate(read(path).splitlines(), 1):
            if label == "c3d_core.py" and block[0] <= number <= block[1]:
                continue
            for key in field.findall(line):
                if key not in FIELD_KINDS:      # a ("kind", "kind", ...) test, not a field
                    shown.add(key)
            line_without_fields = field.sub("", line)
            for key in re.findall(r'"([a-z0-9_]+)"', line_without_fields):
                readers.setdefault(key, set()).add(label)

    for key in defaults:
        if key in ("settings_version",):
            continue
        if key not in readers:
            problems.append((
                "settings_have_readers",
                "the setting '{0}' is {1} but nothing reads it".format(
                    key, "shown in Settings" if key in shown else "never shown either")))
    for key in sorted(shown):
        if key not in defaults:
            problems.append(("settings_have_readers",
                             "Settings shows a field for '{0}', which is not in "
                             "DEFAULTS".format(key)))


def rule_drawer_on_every_window(root, problems):
    """Every window carries the shrink-to-taskbar drawer, and the button that
    drives it is actually handed to it.  A button drawn and never wired is a
    control that does nothing, which looks exactly like a broken one."""
    for name in LAYOUTS:
        path = os.path.join(root, name)
        if not os.path.isfile(path):
            continue
        text = read(path)
        if 'x:Name="HeaderBar"' in text and 'x:Name="ShrinkButton"' not in text:
            problems.append(("drawer_on_every_window",
                             "{0} has a header but no ShrinkButton".format(name)))
        if 'x:Name="ShrinkButton"' in text and \
                'Style="{DynamicResource ShrinkButton}"' not in text:
            problems.append(("drawer_on_every_window",
                             "{0}: the ShrinkButton does not carry the ShrinkButton "
                             "style, so it has no glyph".format(name)))
    chromes = 0
    for label, path in _module_files(root):
        if not os.path.isfile(path):
            continue
        for number, line in enumerate(code_only(read(path)).splitlines(), 1):
            if re.search(r"\bChrome\(", line) and "class Chrome" not in line:
                chromes += 1
                whole = read(path).splitlines()
                call = " ".join(whole[number - 1:number + 2])
                if "ShrinkButton" not in call:
                    problems.append(("drawer_on_every_window",
                                     "{0} line {1} builds a Chrome without handing it "
                                     "the ShrinkButton".format(label, number)))
    if chromes < 3:
        problems.append(("drawer_on_every_window",
                         "only {0} window(s) build a Chrome - the main window, "
                         "Settings and the prompt all need one".format(chromes)))
    if 'x:Key="ShrinkButton"' not in read(os.path.join(root, THEME)):
        problems.append(("drawer_on_every_window", "Theme.xaml has no ShrinkButton style"))


def rule_shrink_stays_live(root, problems):
    """The shrink button stays usable while a run holds Revit - it is the one
    control somebody wants at exactly that moment."""
    source = read(os.path.join(root, "c3d_window.py"))
    match = re.search(r"BUSY_DEAF\s*=\s*\(([^)]*)\)", source)
    if not match:
        problems.append(("shrink_stays_live", "c3d_window.py has no BUSY_DEAF list"))
    elif "ShrinkButton" in match.group(1):
        problems.append(("shrink_stays_live",
                         "ShrinkButton is in BUSY_DEAF, so it dies during a run"))
    if re.search(r"self\.window\.IsHitTestVisible\s*=", code_only(source)):
        problems.append(("shrink_stays_live",
                         "c3d_window.py makes the whole window hit-test-dead, which "
                         "takes the shrink button with it"))


def rule_no_held_animation(root, problems):
    """No Storyboard or BeginAnimation anywhere.  An animation holds its end
    value and outranks every later assignment, so a drawer slid that way and
    never released leaves a window that can never be moved or resized again,
    with nothing raised.  The drawer is eased by hand on a timer instead."""
    for label, path in _module_files(root):
        if not os.path.isfile(path):
            continue
        for number, line in enumerate(code_only(read(path)).splitlines(), 1):
            if re.search(r"\b(BeginAnimation|Storyboard|DoubleAnimation)\b", line):
                problems.append(("no_held_animation",
                                 "{0} line {1} animates a property - ease it by hand "
                                 "on a timer".format(label, number)))
    for name in LAYOUTS + [THEME]:
        path = os.path.join(root, name)
        if os.path.isfile(path) and re.search(r"<(Storyboard|DoubleAnimation)\b", read(path)):
            problems.append(("no_held_animation", "{0} carries a Storyboard".format(name)))


_MARKUP = re.compile(r"^\{(\}|DynamicResource |StaticResource |Binding|TemplateBinding|"
                     r"RelativeSource|x:)")


def rule_no_bare_brace(root, problems):
    """An attribute that starts with a brace is a markup extension to WPF.

    The naming rules' tooltips list {level} {abbrev} ... and written plainly
    that is "the markup extension called level", which throws as the window
    loads - long after any XML check has passed.  A literal brace has to be
    escaped with a leading {}.
    """
    for name in LAYOUTS + [THEME]:
        path = os.path.join(root, name)
        if not os.path.isfile(path):
            continue
        for number, line in enumerate(read(path).splitlines(), 1):
            for value in re.findall(r'\s[\w:.]+="(\{[^"]*)"', line):
                if not _MARKUP.match(value):
                    problems.append(("no_bare_brace",
                                     "{0} line {1}: {2!r} would be read as a markup "
                                     "extension - start it with {{}}".format(name, number, value[:30])))


GROUP_PREFIXES = ("Selection", "Array", "Sheet")


def rule_groups_wired(root, problems):
    """The three stacked groups each have every part the fold needs, and the
    window builds a fold for each of them.

    A group missing its Body would open and shut nothing; one missing from
    the window would sit there open for good with a header that does nothing.
    """
    layout = read(os.path.join(root, "CalloutTo3D.xaml"))
    names = set(re.findall(r'x:Name="([^"]+)"', layout))
    for prefix in GROUP_PREFIXES:
        for part in ("Header", "Body", "Chevron", "Summary"):
            if prefix + part not in names:
                problems.append(("groups_wired", "CalloutTo3D.xaml has no {0}{1}".format(prefix, part)))
    source = read(os.path.join(root, "c3d_window.py"))
    for prefix in GROUP_PREFIXES:
        if not re.search(r'"%s"\s*,' % prefix, source):
            problems.append(("groups_wired",
                             "c3d_window.py never builds a fold for the {0} group".format(prefix)))
    if "ui.Fold(" not in source:
        problems.append(("groups_wired", "c3d_window.py builds no ui.Fold at all"))


def rule_one_layout(root, problems):
    """The preview and the run lay a sheet out with the same function, and
    both put the dragged boxes back through apply_moves.

    Two layouts is two answers: the preview would show one sheet and the run
    build another, and a box moved in the preview would land somewhere else.
    """
    for label, needed in (("c3d_ops.py", ("geom.layout_for(", "geom.apply_moves(")),
                          ("c3d_window.py", ("geom.layout_for(", "geom.apply_moves("))):
        source = code_only(read(os.path.join(root, label)))
        for call in needed:
            if call not in source:
                problems.append(("one_layout", "{0} does not call {1}".format(label, call[:-1])))
        if "geom.two_column_layout(" in source:
            problems.append(("one_layout",
                             "{0} lays a sheet out with two_column_layout directly instead "
                             "of the preset".format(label)))


def rule_defaults_marked(root, problems):
    """Every dropdown with a 'use the default' entry is marked red or green.

    The marking lives in fill_combo itself, so no combo can be filled with a
    blank entry and miss it - which is only true while fill_combo calls it."""
    source = code_only(read(os.path.join(root, "c3d_ui.py")))
    match = re.search(r"def fill_combo\(.*?\n(?=def )", source, re.S)
    if not match or "watch_default(" not in match.group(0):
        problems.append(("defaults_marked",
                         "c3d_ui.fill_combo no longer marks a combo sitting on its default"))


def rule_frame_keys(root, problems):
    """Nothing may ask a callout frame for a key crop_frame does not put in it.

    The frame is a plain dict handed between four modules, so a key renamed in
    one place fails everywhere else at run time and nowhere at load time.  In
    1.5.0 two stale keys survived a rewrite of crop_frame and every row threw
    on the way out - the table came up empty with nothing said.
    """
    source = read(os.path.join(root, "c3d_geom.py"))
    builders = ["_frame_from_crop_shape", "_frame_from_crop_box"]
    sets = {}
    for name in builders:
        block = source.split("def {0}(".format(name), 1)
        if len(block) < 2:
            problems.append(("frame_keys",
                             "c3d_geom.py has no {0}".format(name)))
            continue
        body = block[1].split("\ndef ", 1)[0]
        sets[name] = set(re.findall(r'"(\w+)"\s*:', body))
    if not sets:
        problems.append(("frame_keys", "nothing in c3d_geom.py builds a frame"))
        return
    known = set()
    for keys in sets.values():
        known |= keys
    if not known:
        problems.append(("frame_keys", "the frame builders build no dictionary at all"))
        return
    # every route that can produce a frame has to produce the same one, or a
    # reader works against one and fails against the other
    for name, keys in sets.items():
        missing = known - keys
        if missing:
            problems.append(("frame_keys",
                             "{0} does not set {1}, which the other route does"
                             .format(name, ", ".join(sorted(missing)))))

    for label, path in _module_files(root):
        if not os.path.isfile(path):
            continue
        # the raw source, not code_only: a dictionary key IS a string literal,
        # so blanking string contents would turn this rule off without saying so
        for number, line in enumerate(read(path).splitlines(), 1):
            if line.strip().startswith("#"):
                continue
            for key in re.findall(r'frame\[\s*"(\w+)"\s*\]', line):
                if key not in known:
                    problems.append(("frame_keys",
                                     "{0} line {1} reads frame['{2}'], which crop_frame "
                                     "does not put in it".format(label, number, key)))
            for key in re.findall(r'frame\.get\(\s*"(\w+)"', line):
                if key not in known:
                    problems.append(("frame_keys",
                                     "{0} line {1} reads frame.get('{2}'), which "
                                     "crop_frame does not put in it".format(label, number, key)))


RULES = [
    ("xaml_parses", rule_xaml_parses),
    ("xml_comment_dashes", rule_xml_comment_dashes),
    ("clr_first", rule_clr_first),
    ("no_static_resource", rule_no_static_resource),
    ("dynamic_keys_exist", rule_dynamic_keys_exist),
    ("style_target_matches", rule_style_target_matches),
    ("findname_has_xname", rule_findname_has_xname),
    ("no_fstrings", rule_no_fstrings),
    ("no_print", rule_no_print),
    ("no_bare_integervalue", rule_no_bare_integervalue),
    ("no_system_uri", rule_no_system_uri),
    ("palette_covers_theme", rule_palette_covers_theme),
    ("resource_keys_exist", rule_resource_keys_exist),
    ("globals_exist", rule_globals_exist),
    ("no_duplicate_definitions", rule_no_duplicate_definitions),
    ("settings_have_readers", rule_settings_have_readers),
    ("drawer_on_every_window", rule_drawer_on_every_window),
    ("shrink_stays_live", rule_shrink_stays_live),
    ("no_held_animation", rule_no_held_animation),
    ("frame_keys", rule_frame_keys),
    ("no_bare_brace", rule_no_bare_brace),
    ("groups_wired", rule_groups_wired),
    ("one_layout", rule_one_layout),
    ("defaults_marked", rule_defaults_marked),
    ("egg_wired", rule_egg_wired),
    ("names_match_folders", rule_names_match_folders),
    ("modules_import", rule_modules_import),
    ("settings_round_trip", rule_settings_round_trip),
]


def check(root=HERE):
    problems = []
    for name, function in RULES:
        try:
            function(root, problems)
        except Exception as err:
            problems.append((name, "the rule itself threw: {0}".format(err)))
    return problems


# ---------------------------------------------------------------------------
# selftest - break each rule on purpose
# ---------------------------------------------------------------------------


def _edit(path, old, new):
    text = read(path)
    if old not in text:
        raise AssertionError("the selftest could not find {0!r} in {1}".format(old[:40], path))
    handle = open(path, "wb")
    try:
        handle.write(text.replace(old, new, 1).encode("utf-8"))
    finally:
        handle.close()


def _append(path, text):
    handle = open(path, "ab")
    try:
        handle.write(text.encode("utf-8"))
    finally:
        handle.close()


BREAKAGES = {
    "xaml_parses": lambda root: _edit(os.path.join(root, "CalloutTo3D.xaml"),
                                      "</Window>", "<Oops>"),
    "xml_comment_dashes": lambda root: _edit(
        os.path.join(root, "CalloutTo3D.xaml"),
        "<!-- ===================== header ===================== -->",
        "<!-- --------------------- header --------------------- -->"),
    "clr_first": lambda root: _edit(os.path.join(root, "c3d_preview.py"),
                                    "import c3d_clr", "import os  # was c3d_clr"),
    "no_static_resource": lambda root: _edit(os.path.join(root, "CalloutTo3D.xaml"),
                                             '{DynamicResource TitleText}',
                                             '{StaticResource TitleText}'),
    "dynamic_keys_exist": lambda root: _edit(os.path.join(root, "CalloutTo3D.xaml"),
                                             "{DynamicResource BlueBrush}",
                                             "{DynamicResource BlueishBrush}"),
    "style_target_matches": lambda root: _edit(
        os.path.join(root, "CalloutTo3D.xaml"),
        '<TextBlock x:Name="VersionText" Grid.Column="4" Text="v"',
        '<Button x:Name="VersionText" Grid.Column="4" Content="v"'),
    "findname_has_xname": lambda root: _edit(os.path.join(root, "c3d_window.py"),
                                             'self.find("StatusText")',
                                             'self.find("StatusBar")'),
    "no_fstrings": lambda root: _append(os.path.join(root, "c3d_core.py"),
                                        '\n\ndef _broken(x):\n    return f"{x}"\n'),
    "no_print": lambda root: _append(os.path.join(root, "c3d_core.py"),
                                     '\n\ndef _noisy():\n    print("hello")\n'),
    "no_bare_integervalue": lambda root: _append(
        os.path.join(root, "c3d_model.py"),
        '\n\ndef _old(eid):\n    return eid.IntegerValue\n'),
    "no_system_uri": lambda root: _append(
        os.path.join(root, "c3d_ui.py"),
        '\n\ndef _bad():\n    from System import Uri\n    return Uri\n'),
    "palette_covers_theme": lambda root: _edit(os.path.join(root, "theme.py"),
                                               '"GreenHoverBrush": "#4EC06D",\n    "RedBrush"',
                                               '"RedBrush"'),
    "resource_keys_exist": lambda root: _edit(os.path.join(root, "c3d_grid.py"),
                                              'TryFindResource("GhostButton")',
                                              'TryFindResource("GhostyButton")'),
    "globals_exist": lambda root: _edit(os.path.join(root, "c3d_core.py"),
                                        "def clean_name(name):", "def _was_clean_name(name):"),
    "no_duplicate_definitions": lambda root: _append(
        os.path.join(root, "c3d_ops.py"),
        "\n\ndef band_for(row, settings):\n    return (0.0, 0.0)\n"),
    "settings_have_readers": lambda root: _edit(
        os.path.join(root, "c3d_core.py"),
        '    "sec_sign": "-1",',
        '    "sec_sign": "-1",\n    "nothing_reads_this": "1",'),
    "drawer_on_every_window": lambda root: _edit(
        os.path.join(root, "c3d_settings.py"),
        'find("GripGrid"),\n                                find("ShrinkButton"))',
        'find("GripGrid"))'),
    "shrink_stays_live": lambda root: _edit(
        os.path.join(root, "c3d_window.py"),
        'BUSY_DEAF = ("CreateButton",', 'BUSY_DEAF = ("ShrinkButton", "CreateButton",'),
    "no_held_animation": lambda root: _append(
        os.path.join(root, "c3d_ui.py"),
        "\n\ndef _slide_badly(window, animation):\n"
        "    window.BeginAnimation(window.TopProperty, animation)\n"),
    "no_bare_brace": lambda root: _edit(
        os.path.join(root, "CalloutTo3D.xaml"), 'ToolTip="{}{level}', 'ToolTip="{level}'),
    "groups_wired": lambda root: _edit(
        os.path.join(root, "CalloutTo3D.xaml"), 'x:Name="ArrayBody"', 'x:Name="ArrayBox"'),
    "one_layout": lambda root: _edit(
        os.path.join(root, "c3d_ops.py"), "layout = geom.layout_for(\n        preset,",
        "layout = geom.two_column_layout("),
    "defaults_marked": lambda root: _edit(
        os.path.join(root, "c3d_ui.py"), "                watch_default(combo, blank_label)",
        "                pass"),
    "frame_keys": lambda root: _edit(os.path.join(root, "c3d_model.py"),
                                     'frame["half_x"] * 2.0', 'frame["x1"] * 2.0'),
    "egg_wired": lambda root: _edit(os.path.join(root, "c3d_ui.py"),
                                    "len(self.clicks) >= 3", "len(self.clicks) >= 2"),
    "names_match_folders": lambda root: _edit(os.path.join(root, "c3d_core.py"),
                                              'TOOL_NAME = "Callout to 3D"',
                                              'TOOL_NAME = "Callout To 3d"'),
    "modules_import": lambda root: _edit(
        os.path.join(root, "c3d_geom.py"),
        "from Autodesk.Revit.DB import (                      # noqa: E402\n    BoundingBoxXYZ",
        "from Autodesk.Revit.DB.Plumbing import (             # noqa: E402\n    BoundingBoxXYZ"),
    "settings_round_trip": lambda root: _edit(
        os.path.join(root, "c3d_core.py"),
        'key, value = line.split("=", 1)      # first \'=\' only',
        'key, value = line.split("=")[0], line.split("=")[1]'),
}


def _run_in_copy(root, rule_name):
    """Run one broken copy in its own interpreter, so a mutated module cannot
    poison the modules already imported here."""
    temp = tempfile.mkdtemp(prefix="c3d_bench_")
    target = os.path.join(temp, "Callout to 3D.pushbutton")
    shutil.copytree(root, target)
    try:
        BREAKAGES[rule_name](target)
        script = (
            "import sys, json\n"
            "sys.path.insert(0, {0!r})\n"
            "import import_check\n"
            "print(json.dumps([name for name, _ in import_check.check({0!r})]))\n"
        ).format(target)
        result = subprocess.Popen([sys.executable, "-c", script],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = result.communicate()
        text = out.decode("utf-8", "replace").strip().splitlines()
        if not text:
            return [], err.decode("utf-8", "replace")
        import json
        return json.loads(text[-1]), err.decode("utf-8", "replace")
    finally:
        shutil.rmtree(temp, ignore_errors=True)


def selftest(root=HERE):
    print("Selftest - breaking each rule on purpose")
    passed, failed = 0, 0
    for name, _function in RULES:
        if name not in BREAKAGES:
            print("  {0:24} NO BREAKAGE WRITTEN".format(name))
            failed += 1
            continue
        fired, err = _run_in_copy(root, name)
        if name in fired:
            print("  {0:24} caught".format(name))
            passed += 1
        else:
            print("  {0:24} DID NOT CATCH ITS OWN BREAKAGE  (fired: {1})"
                  .format(name, ", ".join(sorted(set(fired))) or "nothing"))
            if err.strip():
                print("      {0}".format(err.strip().splitlines()[-1]))
            failed += 1
    print("\n{0} of {1} rules caught their own breakage".format(passed, passed + failed))
    return failed == 0


def main():
    if "--selftest" in sys.argv:
        return 0 if selftest() else 1
    problems = check()
    if not problems:
        print("Callout to 3D: all {0} rules pass".format(len(RULES)))
        return 0
    print("Callout to 3D: {0} problem(s)".format(len(problems)))
    for name, message in problems:
        print("  [{0}] {1}".format(name, message))
    return 1


if __name__ == "__main__":
    sys.exit(main())
