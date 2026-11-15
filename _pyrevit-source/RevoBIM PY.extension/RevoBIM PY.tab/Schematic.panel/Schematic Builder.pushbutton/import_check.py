# -*- coding: utf-8 -*-
"""Schematic Builder - bench checker.

Runs under plain CPython, away from Revit:

    python import_check.py            check this folder
    python import_check.py --selftest also break each rule on purpose in a
                                      temporary copy and prove it is caught

The .NET and Revit namespaces are stubbed with EXPLICIT name lists, so a name
imported from the wrong namespace fails here instead of in Revit.
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
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))

MODULES = ["sb_clr", "sb_logic", "sb_lv", "theme", "sb_core", "sb_model", "sb_ui", "sb_picker",
           "sb_mapping", "sb_equipment", "sb_settings", "sb_married", "sb_ops", "sb_window"]
PY_FILES = MODULES + ["script"]
LAYOUTS = ["SchematicBuilder.xaml", "SbSettings.xaml", "SbEquipment.xaml", "SbPicker.xaml",
           "SbMapping.xaml", "SbMessage.xaml"]
THEME = "Theme.xaml"
XAML_NS = "{http://schemas.microsoft.com/winfx/2006/xaml}"

# module -> layout it reads with FindName
LAYOUT_FOR = {
    "sb_window": "SchematicBuilder.xaml",
    "sb_settings": "SbSettings.xaml",
    "sb_equipment": "SbEquipment.xaml",
    "sb_picker": "SbPicker.xaml",
    "sb_mapping": "SbMapping.xaml",
    "sb_married": "SchematicBuilder.xaml",
    "sb_ui": "SbMessage.xaml",
}
# names built with string arithmetic at runtime, per module
COMPUTED_NAMES = {
    "sb_window": (["Tab", "Page", "Browser"], ["Ventilation", "Lv", "Drainage", "Rainwater", "Water"],
                  {"TxtPlaceholder": ["Drainage", "Rainwater", "Water"],
                   "TxtViewName": ["Ventilation", "Lv"],
                   "LstEquipment": ["", "Lv"], "TxtEquipmentInfo": ["", "Lv"]}),
    "sb_settings": (["TxtName"], ["Ventilation", "Lv", "Drainage", "Rainwater", "Water"],
                    {"SetTab": ["General", "Views", "Rooms", "Standards", "Levels", "Spacing", "Params", "Lv"],
                     "SetPage": ["General", "Views", "Rooms", "Standards", "Levels", "Spacing", "Params", "Lv"]}),
}
GRIPS = set(["GripN", "GripS", "GripE", "GripW", "GripNE", "GripNW", "GripSE", "GripSW"])

# the real API: names that live in each namespace. A wrong namespace fails the import.
NAMESPACES = {
    "clr": ["AddReference"],
    "System": ["AppDomain", "Diagnostics", "Predicate", "Double", "TimeSpan"],
    "System.Diagnostics": ["Process"],
    "System.Windows": ["Window", "FrameworkElement", "Thickness", "GridLength", "GridUnitType",
                       "Duration", "SizeToContent",
                       "HorizontalAlignment", "VerticalAlignment", "Visibility", "WindowStartupLocation",
                       "TextTrimming", "PresentationSource"],
    "System.Windows.Controls": ["Grid", "ColumnDefinition", "RowDefinition", "TextBlock", "TextBox", "Button",
                                "GridSplitter",
                                "ComboBox", "CheckBox", "ListBox", "ListBoxItem", "StackPanel", "Orientation",
                                "Border", "ToolTip", "Control", "TextChangedEventHandler"],
    "System.Windows.Controls.Primitives": ["TextBoxBase"],
    "System.Windows.Interop": ["WindowInteropHelper"],
    "System.Windows.Markup": ["XamlReader"],
    "System.Windows.Media": ["SolidColorBrush", "Color"],
    "System.Windows.Media.Animation": ["DoubleAnimation", "CubicEase", "EasingMode"],
    "System.Windows.Input": ["Key", "Cursors", "MouseButton", "Keyboard", "ModifierKeys"],
    "System.Windows.Forms": ["Screen"],
    "System.Drawing": ["Point"],
    "Autodesk": [],
    "Autodesk.Revit": [],
    "Autodesk.Revit.DB": ["ElementId", "UnitUtils", "UnitTypeId", "Element", "StorageType", "BuiltInParameter",
                          "BuiltInCategory", "IFailuresPreprocessor", "FailureSeverity",
                          "FailureProcessingResult", "FilteredElementCollector", "FamilyInstance",
                          "FamilySymbol", "Level", "TextNoteType", "GraphicsStyleType", "View",
                          "ViewFamilyType", "ViewFamily", "RevitLinkInstance", "XYZ", "LocationPoint",
                          "LocationCurve", "ElementCategoryFilter", "Transaction", "TransactionGroup",
                          "ViewDrafting", "Line", "TextNote", "HorizontalTextAlignment",
                          "ElementTransformUtils", "FamilyPlacementType",
                          "VerticalTextAlignment"],
    "Autodesk.Revit.DB.Architecture": ["Room"],
    "Autodesk.Revit.DB.Electrical": ["PanelScheduleView", "ElectricalSystem"],
    "Autodesk.Revit.UI": ["IExternalEventHandler", "ExternalEvent", "TaskDialog"],
}
# which assembly each namespace needs referenced (sb_clr must list it)
ASSEMBLY_FOR = {
    "System": "System",
    "System.Diagnostics": "System",
    "System.Windows": "PresentationFramework",
    "System.Windows.Controls": "PresentationFramework",
    "System.Windows.Controls.Primitives": "PresentationFramework",
    "System.Windows.Interop": "PresentationFramework",
    "System.Windows.Markup": "PresentationFramework",
    "System.Windows.Media": "PresentationCore",
    "System.Windows.Media.Animation": "PresentationCore",
    "System.Windows.Input": "PresentationCore",
    "System.Windows.Forms": "System.Windows.Forms",
    "System.Drawing": "System.Drawing",
}

EXTRA_BUILTINS = set(["long", "unicode", "__revit__", "reduce", "xrange", "basestring"])


# ---------------------------------------------------------------------------
# STUBS
# ---------------------------------------------------------------------------

class _Stub(object):
    def __init__(self, *args, **kwargs):
        pass

    def __getattr__(self, name):
        return _Stub()

    def __call__(self, *args, **kwargs):
        return _Stub()

    def __iter__(self):
        return iter([])


def _make_class(name):
    return type(name, (_Stub,), {})


def install_stubs():
    for name in list(sys.modules.keys()):
        if name.split(".")[0] in ("System", "Autodesk", "clr") or name in MODULES:
            del sys.modules[name]
    for namespace in NAMESPACES:
        module = types.ModuleType(namespace)
        for member in NAMESPACES[namespace]:
            setattr(module, member, _make_class(member))
        if namespace == "clr":
            module.AddReference = lambda assembly: None

        def missing(name, _ns=namespace):
            raise AttributeError("'{0}' is not in namespace {1} (fix the import or the stub map)".format(name, _ns))
        module.__getattr__ = missing
        sys.modules[namespace] = module
    # attach sub-namespaces as attributes of their parents
    for namespace in NAMESPACES:
        parts = namespace.split(".")
        if len(parts) > 1:
            setattr(sys.modules[".".join(parts[:-1])], parts[-1], sys.modules[namespace])


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def read(folder, name):
    handle = io.open(os.path.join(folder, name), "r", encoding="utf-8")
    text = handle.read()
    handle.close()
    return text


def parse_py(folder, module):
    return ast.parse(read(folder, module + ".py"), module + ".py")


def theme_keys(folder):
    root = ET.fromstring(read(folder, THEME).encode("utf-8"))
    brushes = set()
    styles = {}
    for child in root:
        key = child.get(XAML_NS + "Key")
        tag = child.tag.split("}")[-1]
        if tag == "SolidColorBrush" and key:
            brushes.add(key)
        if tag == "Style" and key:
            styles[key] = child.get("TargetType", "")
        elif key and tag != "SolidColorBrush":
            styles[key] = ""        # templates and the like: a key, no target type to match
    return brushes, styles


RES_REF = re.compile(r"\{(DynamicResource|StaticResource)\s+([A-Za-z0-9_]+)\}")


# ---------------------------------------------------------------------------
# RULES  (each returns a list of problem strings)
# ---------------------------------------------------------------------------

def rule_xaml_parses(folder):
    problems = []
    for name in LAYOUTS + [THEME]:
        try:
            ET.fromstring(read(folder, name).encode("utf-8"))
        except Exception as exc:
            problems.append("{0}: {1}".format(name, exc))
    return problems


def rule_clr_first(folder):
    problems = []
    for module in MODULES + ["script"]:
        if module in ("sb_clr", "sb_logic", "sb_lv", "theme"):
            continue
        tree = parse_py(folder, module)
        clr_line = None
        first_net = None
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "sb_clr" and clr_line is None:
                        clr_line = node.lineno
                    if alias.name.split(".")[0] in ("System", "Autodesk") and first_net is None:
                        first_net = node.lineno
            elif isinstance(node, ast.ImportFrom):
                root = (node.module or "").split(".")[0]
                if root in ("System", "Autodesk") and first_net is None:
                    first_net = node.lineno
        if first_net is not None and (clr_line is None or clr_line > first_net):
            if module == "script":
                continue    # script.py imports .NET lazily inside functions after _load_modules
            problems.append("{0}.py: .NET import on line {1} before 'import sb_clr'".format(module, first_net))
    return problems


def rule_no_static_in_layouts(folder):
    problems = []
    for name in LAYOUTS:
        for match in RES_REF.finditer(read(folder, name)):
            if match.group(1) == "StaticResource":
                problems.append("{0}: StaticResource {1} (layouts must use DynamicResource)".format(name, match.group(2)))
    return problems


def rule_resource_keys_exist(folder):
    brushes, styles = theme_keys(folder)
    known = brushes | set(styles.keys())
    problems = []
    for name in LAYOUTS:
        for match in RES_REF.finditer(read(folder, name)):
            if match.group(2) not in known:
                problems.append("{0}: {1} '{2}' is not defined in Theme.xaml".format(name, match.group(1), match.group(2)))
    theme_text = read(folder, THEME)
    for match in RES_REF.finditer(theme_text):
        if match.group(2) not in known:
            problems.append("Theme.xaml: {0} '{1}' is not defined".format(match.group(1), match.group(2)))
    return problems


def rule_style_target_types(folder):
    brushes, styles = theme_keys(folder)
    problems = []
    for name in LAYOUTS:
        root = ET.fromstring(read(folder, name).encode("utf-8"))
        for element in root.iter():
            style = element.get("Style", "")
            match = RES_REF.match(style)
            if not match:
                continue
            key = match.group(2)
            tag = element.tag.split("}")[-1]
            target = styles.get(key)
            if target and target != tag:
                problems.append("{0}: {1} uses style '{2}' made for {3}".format(name, tag, key, target))
    return problems


def rule_python_resource_keys(folder):
    brushes, styles = theme_keys(folder)
    known = brushes | set(styles.keys())
    problems = []
    call = re.compile(r"(?:set_style|colour|SetResourceReference|FindResource|brush)\(([^)]*)\)")
    style_kw = re.compile(r'style="([A-Za-z0-9_]+)"')
    literal = re.compile(r'"([A-Za-z][A-Za-z0-9_]*)"')
    for module in MODULES:
        text = read(folder, module + ".py")
        for match in call.finditer(text):
            args = match.group(1)
            for key in literal.findall(args):
                if key not in known:
                    problems.append("{0}.py: resource key '{1}' is not in Theme.xaml".format(module, key))
        for key in style_kw.findall(text):
            if key not in known:
                problems.append("{0}.py: style '{1}' is not in Theme.xaml".format(module, key))
    return problems


def rule_palette_matches_theme(folder):
    brushes, styles = theme_keys(folder)
    scope = {}
    exec(compile(read(folder, "theme.py"), "theme.py", "exec"), scope)
    problems = []
    for palette_name in ("DARK", "LIGHT"):
        keys = set(scope[palette_name].keys())
        for key in sorted(keys - brushes):
            problems.append("theme.py {0}: '{1}' has no brush in Theme.xaml".format(palette_name, key))
        for key in sorted(brushes - keys):
            problems.append("theme.py {0}: brush '{1}' from Theme.xaml is missing".format(palette_name, key))
    return problems


def rule_find_names(folder):
    problems = []
    find_call = re.compile(r'(?:FindName|find)\(\s*"([A-Za-z0-9_]+)"\s*\)')
    for module in LAYOUT_FOR:
        root = ET.fromstring(read(folder, LAYOUT_FOR[module]).encode("utf-8"))
        names = set([e.get(XAML_NS + "Name") for e in root.iter() if e.get(XAML_NS + "Name")])
        text = read(folder, module + ".py")
        for name in find_call.findall(text):
            if name not in names and name not in GRIPS:
                problems.append("{0}.py: FindName('{1}') is not an x:Name in {2}".format(module, name, LAYOUT_FOR[module]))
        prefixes, suffixes, special = COMPUTED_NAMES.get(module, ([], [], {}))
        for prefix in prefixes:
            for suffix in suffixes:
                if prefix + suffix not in names:
                    problems.append("{0}.py: computed name '{1}' is not in {2}".format(module, prefix + suffix, LAYOUT_FOR[module]))
        for prefix in special:
            for suffix in special[prefix]:
                if prefix + suffix not in names:
                    problems.append("{0}.py: computed name '{1}' is not in {2}".format(module, prefix + suffix, LAYOUT_FOR[module]))
    return problems


def rule_forbidden_syntax(folder):
    problems = []
    for module in PY_FILES:
        text = read(folder, module + ".py")
        tree = ast.parse(text, module + ".py")
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr):
                problems.append("{0}.py:{1}: f-string".format(module, node.lineno))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print":
                problems.append("{0}.py:{1}: print()".format(module, node.lineno))
            if isinstance(node, ast.Attribute) and node.attr == "IntegerValue" and module != "sb_core":
                problems.append("{0}.py:{1}: bare .IntegerValue (use eid_value)".format(module, node.lineno))
        if re.search(r"\bSystem\.Uri\b|\bfrom System import .*\bUri\b", text):
            problems.append("{0}.py: System.Uri".format(module))
    return problems


def rule_duplicate_defs(folder):
    problems = []
    for module in PY_FILES:
        tree = parse_py(folder, module)
        seen = {}
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                if node.name in seen:
                    problems.append("{0}.py: '{1}' defined twice (lines {2} and {3})".format(
                        module, node.name, seen[node.name], node.lineno))
                seen[node.name] = node.lineno
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                methods = {}
                for item in node.body:
                    if isinstance(item, ast.FunctionDef):
                        if item.name in methods:
                            problems.append("{0}.py: method {1}.{2} defined twice".format(module, node.name, item.name))
                        methods[item.name] = item.lineno
    return problems


def rule_undefined_globals(folder):
    problems = []
    builtins_names = set(dir(__builtins__)) if not isinstance(__builtins__, dict) else set(__builtins__.keys())
    builtins_names |= EXTRA_BUILTINS
    for module in PY_FILES:
        text = read(folder, module + ".py")
        tree = ast.parse(text, module + ".py")
        module_names = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                module_names.add(node.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    module_names.add((alias.asname or alias.name).split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    module_names.add(alias.asname or alias.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    for name_node in ast.walk(target):
                        if isinstance(name_node, ast.Name):
                            module_names.add(name_node.id)
            elif isinstance(node, (ast.For, ast.With)):
                for name_node in ast.walk(node.target if isinstance(node, ast.For) else node):
                    if isinstance(name_node, ast.Name):
                        module_names.add(name_node.id)
        table = symtable.symtable(text, module + ".py", "exec")

        def walk(scope):
            for symbol in scope.get_symbols():
                name = symbol.get_name()
                if symbol.is_global() and symbol.is_referenced() and not symbol.is_assigned():
                    if name not in module_names and name not in builtins_names:
                        problems.append("{0}.py: '{1}' used in {2}() but never defined".format(module, name, scope.get_name()))
            for child in scope.get_children():
                walk(child)
        for child in table.get_children():
            walk(child)
    return problems


def rule_unreachable(folder):
    """A statement after return / raise / continue / break in the same block
    never runs - usually a block that was pasted into the wrong place."""
    problems = []
    enders = (ast.Return, ast.Raise, ast.Continue, ast.Break)
    for module in PY_FILES:
        tree = parse_py(folder, module)
        for node in ast.walk(tree):
            for field in ("body", "orelse", "finalbody"):
                block = getattr(node, field, None)
                if not isinstance(block, list):
                    continue
                for index, statement in enumerate(block[:-1]):
                    if isinstance(statement, enders):
                        problems.append("{0}.py:{1}: unreachable code after line {2}".format(
                            module, block[index + 1].lineno, statement.lineno))
                        break
    return problems


def rule_call_arity(folder):
    """Calls to this tool's own top-level functions must fit their signatures."""
    problems = []
    signatures = {}

    def record(module, name, args, drop_self=False):
        names = [a.arg for a in args.args]
        if drop_self and names:
            names = names[1:]
        required = len(names) - len(args.defaults)
        maximum = None if args.vararg else len(names)
        signatures[(module, name)] = (required, maximum, names)

    for module in MODULES:
        tree = parse_py(folder, module)
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                record(module, node.name, node.args)
            elif isinstance(node, ast.ClassDef):
                # a class is called through its __init__, minus self - the rule
                # that would have caught EquipmentDialog(settings=...) in 3.2.0
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                        record(module, node.name, item.args, drop_self=True)
    for module in PY_FILES:
        tree = parse_py(folder, module)
        imported = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in MODULES:
                for alias in node.names:
                    imported[alias.asname or alias.name] = (node.module, alias.name)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            target = None
            if isinstance(node.func, ast.Name) and node.func.id in imported:
                target = imported[node.func.id]
            elif isinstance(node.func, ast.Name) and (module, node.func.id) in signatures:
                target = (module, node.func.id)
            elif isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) \
                    and node.func.value.id in MODULES and (node.func.value.id, node.func.attr) in signatures:
                target = (node.func.value.id, node.func.attr)
            if target is None or target not in signatures:
                continue
            if any([isinstance(a, ast.Starred) for a in node.args]) or any([k.arg is None for k in node.keywords]):
                continue
            required, maximum, names = signatures[target]
            given = len(node.args) + len(node.keywords)
            bad_kw = [k.arg for k in node.keywords if k.arg not in names]
            if given < required or (maximum is not None and given > maximum) or bad_kw:
                problems.append("{0}.py:{1}: {2}.{3}() called with {4} argument(s), wants {5}{6}{7}".format(
                    module, node.lineno, target[0], target[1], given, required,
                    "" if maximum == required else "-{0}".format(maximum),
                    "  unknown keywords " + ", ".join(bad_kw) if bad_kw else ""))
    return problems


CHROME_NAMES = ("HeaderBar", "TxtVersion", "BtnShrink", "BtnFull", "BtnClose",
                "GripN", "GripS", "GripE", "GripW", "GripNE", "GripNW", "GripSE", "GripSW")


def rule_window_chrome(folder):
    """Every window carries the same header controls and grips, so the
    drawer, full screen and resizing behave alike in all of them."""
    problems = []
    for name in LAYOUTS:
        root = ET.fromstring(read(folder, name).encode("utf-8"))
        names = set([e.get(XAML_NS + "Name") for e in root.iter() if e.get(XAML_NS + "Name")])
        for wanted in CHROME_NAMES:
            if wanted not in names:
                problems.append("{0}: no {1} - every window needs the standard header and grips".format(
                    name, wanted))
    return problems


def code_calls(tree, name):
    """Calls to name(...) or x.name(...) in a parsed module, with the def they sit in."""
    found = []
    for func in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)] + [tree]:
        body = func.body if func is not tree else [n for n in tree.body
                                                    if not isinstance(n, (ast.FunctionDef, ast.ClassDef))]
        for stmt in body:
            for node in ast.walk(stmt):
                if not isinstance(node, ast.Call):
                    continue
                target = node.func
                called = target.id if isinstance(target, ast.Name) else (
                    target.attr if isinstance(target, ast.Attribute) else None)
                if called == name:
                    found.append((func.name if func is not tree else "<module>", node))
    return found


def rule_one_window_path(folder):
    """Windows are only built through sb_ui.open_window. Anything that calls
    load_window or Chrome itself makes a window without its drawer."""
    problems = []
    for module in PY_FILES:
        tree = parse_py(folder, module)
        for name in ("load_window", "Chrome", "WindowDrawer"):
            for where, node in code_calls(tree, name):
                allowed = (module == "sb_ui" and
                           ((name == "load_window" and where == "open_window") or
                            (name == "Chrome" and where == "open_window") or
                            (name == "WindowDrawer" and where == "__init__")))
                if not allowed:
                    problems.append("{0}.py:{1}: {2}() called from {3} - build windows with "
                                    "sb_ui.open_window".format(module, node.lineno, name, where))
    return problems


def rule_drawer_released(folder):
    """The drawer has to release both animations when the slide finishes -
    an animation holds its end value and outranks every later assignment,
    so a window left holding one can never be moved or resized again."""
    tree = parse_py(folder, "sb_ui")
    released = set()
    wired = False
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "BeginAnimation" and len(node.args) == 2
                and isinstance(node.args[1], ast.Constant) and node.args[1].value is None
                and isinstance(node.args[0], ast.Attribute)):
            released.add(node.args[0].attr)
        if (isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Attribute)
                and node.target.attr == "Completed"):
            wired = True
    problems = []
    for prop in ("TopProperty", "HeightProperty"):
        if prop not in released:
            problems.append("sb_ui.py: the drawer never releases its {0} animation".format(prop))
    if not wired:
        problems.append("sb_ui.py: the drawer's animation has no Completed handler to release it")
    return problems


def contrast(fore, back):
    """WCAG contrast ratio of two #RRGGBB colours."""
    def lum(text):
        text = text.lstrip("#")
        out = []
        for i in (0, 2, 4):
            c = int(text[i:i + 2], 16) / 255.0
            out.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
        return 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]
    a, b = lum(fore), lum(back)
    if a < b:
        a, b = b, a
    return (a + 0.05) / (b + 0.05)


REVIT_DARK = {"BarBg": "#222933", "ShellBg": "#3C4454", "FieldBg": "#2D3441",
              "PanelBg": "#323C48", "HoverBrush": "#444E5E", "SelBrush": "#3A7392",
              "EdgeBrush": "#515C6B", "TextBrush": "#EEF0F4"}


def rule_revit_dark(folder):
    """Dark is Revit's own dark theme: the sampled values are in the palette,
    Theme.xaml's defaults match it (or a window flashes the wrong colours
    before the palette lands), and every text colour reads on every body
    colour in both palettes."""
    scope = {}
    exec(compile(read(folder, "theme.py"), "theme.py", "exec"), scope)
    problems = []
    dark = scope["DARK"]
    for key in sorted(REVIT_DARK):
        if dark.get(key, "").upper() != REVIT_DARK[key]:
            problems.append("theme.py DARK {0} is {1}, Revit's is {2}".format(key, dark.get(key), REVIT_DARK[key]))
    root = ET.fromstring(read(folder, THEME).encode("utf-8"))
    for child in root:
        key = child.get(XAML_NS + "Key")
        if child.tag.split("}")[-1] == "SolidColorBrush" and key in dark:
            if child.get("Color", "").upper() != dark[key].upper():
                problems.append("Theme.xaml default {0} is {1}, the dark palette says {2}".format(
                    key, child.get("Color"), dark[key]))
    for name in ("DARK", "LIGHT"):
        palette = scope[name]
        for fore in scope["TEXT_KEYS"]:
            for back in scope["BODY_KEYS"]:
                ratio = contrast(palette[fore], palette[back])
                if ratio < scope["MIN_CONTRAST"]:
                    problems.append("theme.py {0}: {1} on {2} is {3:.2f}:1, under {4}".format(
                        name, fore, back, ratio, scope["MIN_CONTRAST"]))
    return problems


def rule_no_dead_code(folder):
    """No import a module never uses, and no top-level function or class
    nothing in the tool reaches. Read from the AST, not the text, so a name
    that only appears in a docstring or a string does not count as a use."""
    problems = []
    used = {}
    trees = {}
    for module in PY_FILES:
        tree = parse_py(folder, module)
        trees[module] = tree
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
        used[module] = names
    for module in PY_FILES:
        for node in trees[module].body:
            if isinstance(node, ast.ImportFrom):
                imported = [alias.asname or alias.name for alias in node.names]
            elif isinstance(node, ast.Import):
                imported = [(alias.asname or alias.name).split(".")[0] for alias in node.names]
            else:
                continue
            for name in imported:
                if name in ("sb_clr", "clr") or name in used[module]:
                    continue
                problems.append("{0}.py:{1}: '{2}' is imported and never used".format(
                    module, node.lineno, name))
    everywhere = set()
    for module in PY_FILES:
        everywhere |= used[module]
        for node in trees[module].body:
            if isinstance(node, ast.ImportFrom):
                everywhere |= set([alias.name for alias in node.names])
    for module in MODULES:
        for node in trees[module].body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name not in everywhere:
                problems.append("{0}.py:{1}: {2} is defined and nothing in the tool uses it".format(
                    module, node.lineno, node.name))
    return problems


def rule_cross_module_names(folder):
    """Every ``other_module.name`` a module reaches for has to exist there.

    A whole-block rewrite can delete a helper the rest of the tool still
    calls, and nothing else notices until it is clicked."""
    problems = []
    defined = {}
    for module in MODULES:
        tree = parse_py(folder, module)
        names = set()
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    for name_node in ast.walk(target):
                        if isinstance(name_node, ast.Name):
                            names.add(name_node.id)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    names.add((alias.asname or alias.name).split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    names.add(alias.asname or alias.name)
        defined[module] = names
    for module in PY_FILES:
        tree = parse_py(folder, module)
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                    and node.value.id in defined and node.attr not in defined[node.value.id]):
                problems.append("{0}.py:{1}: {2}.{3} does not exist".format(
                    module, node.lineno, node.value.id, node.attr))
    return problems


def rule_assemblies_referenced(folder):
    problems = []
    scope = {}
    stub_clr = types.ModuleType("clr")
    stub_clr.AddReference = lambda a: None
    saved = sys.modules.get("clr")
    sys.modules["clr"] = stub_clr
    try:
        exec(compile(read(folder, "sb_clr.py"), "sb_clr.py", "exec"), scope)
    finally:
        if saved is not None:
            sys.modules["clr"] = saved
        else:
            sys.modules.pop("clr", None)
    referenced = set(scope.get("ASSEMBLIES", ()))
    for module in MODULES:
        tree = parse_py(folder, module)
        for node in ast.walk(tree):
            namespace = None
            if isinstance(node, ast.ImportFrom):
                namespace = node.module or ""
            elif isinstance(node, ast.Import):
                namespace = node.names[0].name
            if namespace in ASSEMBLY_FOR and ASSEMBLY_FOR[namespace] not in referenced:
                problems.append("{0}.py imports {1} but sb_clr does not reference {2}".format(
                    module, namespace, ASSEMBLY_FOR[namespace]))
    return problems


def rule_modules_import(folder):
    problems = []
    install_stubs()
    saved_path = list(sys.path)
    sys.path.insert(0, folder)
    try:
        for module in MODULES:
            try:
                __import__(module)
            except Exception as exc:
                problems.append("{0}.py: {1}: {2}".format(module, exc.__class__.__name__, exc))
    finally:
        sys.path[:] = saved_path
        for module in MODULES:
            sys.modules.pop(module, None)
    return problems


RULES = [
    ("XAML files parse", rule_xaml_parses),
    ("sb_clr imported before any .NET import", rule_clr_first),
    ("no StaticResource in layouts", rule_no_static_in_layouts),
    ("every resource key exists in Theme.xaml", rule_resource_keys_exist),
    ("style keys match their element type", rule_style_target_types),
    ("resource keys used from Python exist", rule_python_resource_keys),
    ("palettes and Theme.xaml brushes agree", rule_palette_matches_theme),
    ("FindName targets exist in the layout", rule_find_names),
    ("no f-strings / print / bare IntegerValue / System.Uri", rule_forbidden_syntax),
    ("no duplicate definitions", rule_duplicate_defs),
    ("no undefined globals", rule_undefined_globals),
    ("no unreachable code", rule_unreachable),
    ("calls match signatures", rule_call_arity),
    ("every window has the standard header and grips", rule_window_chrome),
    ("windows are only built through open_window", rule_one_window_path),
    ("the drawer releases its animations", rule_drawer_released),
    ("dark is Revit's own dark, and every text colour reads", rule_revit_dark),
    ("cross module names exist", rule_cross_module_names),
    ("no unused imports or dead definitions", rule_no_dead_code),
    ("every .NET namespace has its assembly referenced", rule_assemblies_referenced),
    ("modules import against the API stubs", rule_modules_import),
]


def run(folder, quiet=False):
    failed = 0
    for label, rule in RULES:
        try:
            problems = rule(folder)
        except Exception as exc:
            problems = ["rule crashed: {0}: {1}".format(exc.__class__.__name__, exc)]
        if not quiet:
            print(("  ok   " if not problems else "  FAIL ") + label)
            for problem in problems:
                print("         " + problem)
        if problems:
            failed += 1
    return failed


# ---------------------------------------------------------------------------
# SELF TEST: break every rule on purpose in a temporary copy
# ---------------------------------------------------------------------------

def _mutate(folder, name, old, new):
    path = os.path.join(folder, name)
    text = read(folder, name)
    if old not in text:
        raise RuntimeError("selftest anchor missing in {0}: {1!r}".format(name, old))
    handle = io.open(path, "w", encoding="utf-8")
    handle.write(text.replace(old, new, 1))
    handle.close()


BREAKS = [
    ("XAML files parse", lambda f: _mutate(f, "SbPicker.xaml", "</Window>", "</Windo>")),
    ("sb_clr imported before any .NET import", lambda f: _mutate(f, "sb_core.py", "import sb_clr  # noqa: F401  (assembly references, must be first)", "")),
    ("no StaticResource in layouts", lambda f: _mutate(f, "SbMessage.xaml", '{DynamicResource Btn}', '{StaticResource Btn}')),
    ("every resource key exists in Theme.xaml", lambda f: _mutate(f, "SbMessage.xaml", '{DynamicResource BtnGreen}', '{DynamicResource BtnGrene}')),
    ("style keys match their element type", lambda f: _mutate(f, "SbMessage.xaml", 'Style="{DynamicResource FieldMulti}"', 'Style="{DynamicResource Btn}"')),
    ("resource keys used from Python exist", lambda f: _mutate(f, "sb_window.py", 'sb_ui.colour(name, "OrangeBrush")', 'sb_ui.colour(name, "OrangBrush")')),
    ("palettes and Theme.xaml brushes agree", lambda f: _mutate(f, "theme.py", '    "PlaceholderBrush": "#8A8A92",', '')),
    ("FindName targets exist in the layout", lambda f: _mutate(f, "sb_picker.py", 'self.find("BtnAll")', 'self.find("BtnAl")')),
    ("no f-strings / print / bare IntegerValue / System.Uri", lambda f: _mutate(f, "sb_model.py", "    levels.sort(key=lambda l: l[\"elev\"])", "    levels.sort(key=lambda l: l[\"elev\"])\n    x = doc.Id.IntegerValue")),
    ("no duplicate definitions", lambda f: _mutate(f, "sb_logic.py", "def text_height(size_mm):", "def text_width(a):\n    return 0\n\n\ndef text_height(size_mm):")),
    ("no undefined globals", lambda f: _mutate(f, "sb_ops.py", "    return fail(u\"The {0} schematic is not built yet.\".format(tab))", "    return faill(u\"x\")")),
    ("no unreachable code", lambda f: _mutate(f, "sb_logic.py", "    return out + u\"\".join(digits)", "    return out + u\"\".join(digits)\n    digits = []")),
    ("calls match signatures", lambda f: _mutate(f, "sb_window.py", "settings=self.settings)", "settings=self.settings, nonsense=1)")),
    ("cross module names exist", lambda f: _mutate(f, "sb_married.py", "sb_ui.combo_text(", "sb_ui.combo_txt(")),
    ("no unused imports or dead definitions", lambda f: _mutate(f, "sb_ui.py", "def star(value=1.0):", "def forgotten():\n    \"\"\"star appears here, in prose only\"\"\"\n    return 0\n\n\ndef star(value=1.0):")),
    ("every window has the standard header and grips", lambda f: _mutate(f, "SbPicker.xaml", 'x:Name="BtnShrink"', 'x:Name="BtnShrunk"')),
    ("windows are only built through open_window", lambda f: _mutate(f, "sb_picker.py", "self.window, self.find, self.chrome = sb_ui.open_window(", "self.window = sb_ui.load_window('SbPicker.xaml', palette_name); self.find, self.chrome = None, sb_ui.open_window(")),
    ("the drawer releases its animations", lambda f: _mutate(f, "sb_ui.py", "window.BeginAnimation(Window.HeightProperty, None)", "pass")),
    ("dark is Revit's own dark, and every text colour reads", lambda f: _break_contrast(f)),
    ("every .NET namespace has its assembly referenced", lambda f: _mutate(f, "sb_clr.py", '    "System.Windows.Forms",\n', '')),
    ("modules import against the API stubs", lambda f: _mutate(f, "sb_ui.py", "from System.Windows.Controls import (  # noqa: E402\n    Grid,", "from System.Windows import (  # noqa: E402\n    Grid,")),
]


def _break_contrast(folder):
    """Put the house red back in BOTH places, so the palette and Theme.xaml
    still agree and only the contrast check is left to catch it."""
    _mutate(folder, "theme.py", '"RedBrush": "#FF948C",', '"RedBrush": "#D9534F",')
    _mutate(folder, "Theme.xaml", 'x:Key="RedBrush" Color="#FF948C"', 'x:Key="RedBrush" Color="#D9534F"')


def selftest():
    print("selftest: breaking each rule in a temporary copy")
    clean = True
    for label, breaker in BREAKS:
        temp = tempfile.mkdtemp(prefix="sb_check_")
        target = os.path.join(temp, "tool")
        shutil.copytree(HERE, target)
        try:
            breaker(target)
            rule = dict(RULES)[label]
            problems = rule(target)
            caught = bool(problems)
        except Exception as exc:
            caught = False
            problems = [str(exc)]
        finally:
            shutil.rmtree(temp, ignore_errors=True)
        print(("  ok   " if caught else "  FAIL ") + "breakage caught: " + label)
        if not caught:
            for problem in problems:
                print("         " + problem)
            clean = False
    return clean


if __name__ == "__main__":
    print("import_check: " + HERE)
    failed = run(HERE)
    clean = failed == 0
    if "--selftest" in sys.argv:
        clean = selftest() and clean
    print("")
    print("CLEAN" if clean else "FAILURES")
    sys.exit(0 if clean else 1)
