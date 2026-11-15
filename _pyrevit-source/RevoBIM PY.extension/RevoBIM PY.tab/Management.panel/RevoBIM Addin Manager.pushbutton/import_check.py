# -*- coding: utf-8 -*-
u"""RevoBIM Addins - static bench check.

Run from this folder under plain CPython:

    python import_check.py
    python import_check.py --selftest

Every rule is proved by deliberately breaking it in a temporary copy of the
tool and confirming the rule fires.  A rule nobody has tested is a rule that
does not work, and four rules in this extension's history passed their own
selftest by matching prose in a docstring rather than the code.  Every
breakage below therefore edits real code.
"""

from __future__ import print_function

import ast
import io
import os
import re
import shutil
import sys
import tempfile
import types
import xml.dom.minidom as minidom

HERE = os.path.dirname(os.path.abspath(__file__))

MODULES = ["rba_core", "rba_scan", "rba_theme", "rba_ui", "rba_launch",
           "rba_pane", "rba_settings", "rba_window", "rba_shortcuts",
           "rba_qat", "rba_menu", "rba_dock", "rba_drawer", "rba_favs",
           "rba_tween"]
LAYOUTS = ["RevoBIMAddins.xaml", "RbaSettings.xaml", "RbaWindow.xaml",
           "RbaShortcut.xaml"]
THEME_FILE = "Theme.xaml"

# ----------------------------------------------------------------------
# the stub API - each name declared in the namespace the real API puts it in
# ----------------------------------------------------------------------

NAMESPACES = {
    "clr": ["AddReference"],
    "System": ["TimeSpan", "Guid", "Action", "IntPtr", "AppDomain", "Object",
               "EventHandler",
               "Double"],
    "System.Diagnostics": ["Process", "Stopwatch"],
    "System.IO": ["File", "FileStream", "FileMode", "FileAccess", "MemoryStream",
                  "FileSystemWatcher", "NotifyFilters", "Path"],
    "System.Windows": ["Thickness", "CornerRadius", "FontWeights", "GridLength",
                       "TextTrimming", "TextWrapping", "HorizontalAlignment",
                       "VerticalAlignment", "Visibility", "Window", "WindowStyle", "Clipboard",
                       "WindowState", "PresentationSource", "TextWrapping", "TextAlignment", "Point", "LogicalTreeHelper",
                       "SizeToContent", "SystemParameters", "WindowStartupLocation",
                       "FrameworkElement", "ResourceDictionary"],
    "System.Windows.Controls": ["Border", "Grid", "StackPanel", "TextBlock", "Image",
                                "TextBox", "Button", "ScrollViewer", "ScrollBarVisibility",
                                "WrapPanel", "Panel",

                                "ContentControl", "ContextMenu", "MenuItem", "Separator",
                                "Orientation",
                                "ColumnDefinition", "RowDefinition", "ToolTip",
                                "TextBox", "Button", "CheckBox", "ComboBox",
                                "ScrollViewer", "UserControl"],
    "System.Windows.Markup": ["XamlReader"],
    "System.Windows.Media.Effects": ["DropShadowEffect"],
    "System.Windows.Controls.Primitives": ["LayoutInformation"],
    "System.Windows.Media": ["FontFamily", "Stretch", "Geometry", "BrushConverter",
                             "ColorConverter", "ScaleTransform", "TranslateTransform",
                             "TransformGroup", "CompositionTarget",
                             "SolidColorBrush", "Brushes"],
    "System.Windows.Media.Imaging": ["BitmapImage", "BitmapCacheOption",
                                     "BitmapCreateOptions"],
    "System.Windows.Shapes": ["Path", "Rectangle", "Ellipse"],
    "System.Windows.Threading": ["DispatcherTimer", "Dispatcher", "DispatcherPriority"],
    "System.Windows.Input": ["Key", "Mouse", "MouseButton", "MouseButtonEventHandler",
                             "Keyboard", "Cursors", "ModifierKeys",
                             "MouseButtonState"],
    "System.Windows.Interop": ["WindowInteropHelper"],
    "System.Windows.Forms": ["FolderBrowserDialog", "DialogResult", "Screen"],
    "Autodesk": [],
    "Autodesk.Revit": ["UI", "DB"],
    "Autodesk.Revit.UI": ["IDockablePaneProvider", "DockablePaneState", "DockablePaneId",
                          "DockablePane", "PostableCommand",
                          "DockPosition", "RevitCommandId", "TaskDialog",
                          "UIThemeManager", "UITheme", "UIApplication"],
    "Autodesk.Revit.DB": ["ElementId", "Rectangle"],
    "Autodesk.Windows": ["ComponentManager", "RibbonButton", "RibbonItemSize"],
}


def _dummy(name):
    return type(str(name), (object,), {"__stub__": True})


class StubModule(types.ModuleType):
    pass


_REAL_MODULES = {}


def install_stubs():
    for namespace in NAMESPACES:
        if namespace in sys.modules and namespace not in _REAL_MODULES:
            _REAL_MODULES[namespace] = sys.modules[namespace]
        module = StubModule(namespace)
        for name in NAMESPACES[namespace]:
            setattr(module, name, _dummy(name))
        if namespace == "clr":
            module.AddReference = lambda *args, **kwargs: None
        sys.modules[namespace] = module
    # Autodesk.Revit.UI has to be reachable as an attribute too, because
    # rba_theme deliberately does "from Autodesk.Revit import UI" and then
    # getattr's UIThemeManager off it.
    sys.modules["Autodesk.Revit"].UI = sys.modules["Autodesk.Revit.UI"]
    sys.modules["Autodesk"].Revit = sys.modules["Autodesk.Revit"]


def button_folders(folder):
    out = []
    try:
        names = sorted(os.listdir(folder))
    except Exception:
        return out
    for name in names:
        path = os.path.join(folder, name)
        if os.path.isdir(path) and name.lower().endswith(".pushbutton"):
            out.append(path)
    return out


def py_files(folder):
    """The shared modules AND each button's script.py.

    A rule that only looked at the shared modules would miss the two thin
    loaders entirely, which is where a stray print or f-string is most likely
    to be left behind.
    """
    out = []
    for module in MODULES:
        path = os.path.join(folder, module + ".py")
        if os.path.isfile(path):
            out.append((module + ".py", path))
    path = os.path.join(folder, "script.py")
    if os.path.isfile(path):
        out.append(("script.py", path))
    for button in button_folders(folder):
        path = os.path.join(button, "script.py")
        if os.path.isfile(path):
            label = os.path.basename(button) + os.sep + "script.py"
            out.append((label, path))
    return out


def read(path):
    handle = io.open(path, "r", encoding="utf-8")
    try:
        return handle.read()
    finally:
        handle.close()


def write(path, text):
    handle = io.open(path, "w", encoding="utf-8")
    try:
        handle.write(text)
    finally:
        handle.close()


# ----------------------------------------------------------------------
# rules
# ----------------------------------------------------------------------

def rule_xaml_parses(folder):
    problems = []
    for name in LAYOUTS + [THEME_FILE]:
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            problems.append("{0} is missing".format(name))
            continue
        try:
            minidom.parse(path)
        except Exception as error:
            problems.append("{0} will not parse as XML: {1}".format(name, error))
    return problems


def rule_no_double_hyphen_comment(folder):
    problems = []
    for name in LAYOUTS + [THEME_FILE]:
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            continue
        for match in re.finditer(r"<!--(.*?)-->", read(path), re.S):
            if "--" in match.group(1):
                problems.append("{0} has a comment containing '--'; "
                                "draw banners with '=' not '-'".format(name))
    return problems


def rule_no_baseline_alignment(folder):
    problems = []
    for name in LAYOUTS + [THEME_FILE]:
        path = os.path.join(folder, name)
        if os.path.isfile(path) and 'Alignment="Baseline"' in read(path):
            problems.append("{0} uses Alignment=\"Baseline\", which throws in "
                            "XamlReader.Load".format(name))
    return problems


def rule_no_static_resource_in_layout(folder):
    problems = []
    for name in LAYOUTS:
        path = os.path.join(folder, name)
        if os.path.isfile(path) and "StaticResource" in read(path):
            problems.append("{0} uses StaticResource; Theme.xaml is merged "
                            "after the layout is parsed".format(name))
    return problems


def theme_keys(folder):
    path = os.path.join(folder, THEME_FILE)
    if not os.path.isfile(path):
        return set()
    return set(re.findall(r'x:Key="([^"]+)"', read(path)))


def rule_dynamic_keys_exist(folder):
    known = theme_keys(folder)
    problems = []
    for name in LAYOUTS:
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            continue
        for key in set(re.findall(r"\{DynamicResource ([^}]+)\}", read(path))):
            if key.strip() not in known:
                problems.append("{0} asks for DynamicResource {1}, which "
                                "Theme.xaml does not define".format(name, key.strip()))
    return problems


def rule_style_target_type_matches(folder):
    path = os.path.join(folder, THEME_FILE)
    targets = {}
    if os.path.isfile(path):
        for key, target in re.findall(
                r'<Style x:Key="([^"]+)"\s+TargetType="([^"]+)"', read(path)):
            targets[key] = target
    problems = []
    for name in LAYOUTS:
        layout = os.path.join(folder, name)
        if not os.path.isfile(layout):
            continue
        text = read(layout)
        for match in re.finditer(r"<(\w+)([^>]*?)Style=\"\{DynamicResource ([^}]+)\}\"",
                                 text, re.S):
            element, key = match.group(1), match.group(3).strip()
            if key in targets and targets[key] != element:
                problems.append(
                    "{0}: style {1} targets {2} but is applied to a {3}".format(
                        name, key, targets[key], element))
    return problems


def rule_findname_has_xname(folder):
    names = set()
    for name in LAYOUTS:
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            names |= set(re.findall(r'x:Name="([^"]+)"', read(path)))
    problems = []
    for module in MODULES:
        path = os.path.join(folder, module + ".py")
        if not os.path.isfile(path):
            continue
        text = read(path)
        # both the literal call and the aliased form the code actually uses
        asked = set(re.findall(r'(?:FindName|find)\(\s*u?"([^"]+)"\s*\)', text))
        for key in asked:
            if key not in names:
                problems.append("{0}.py looks up '{1}', which no layout "
                                "declares as x:Name".format(module, key))
    return problems


def _code_only(text):
    u"""Source with docstrings and comments stripped.

    Every rule below runs against this, so a rule can never pass its own
    selftest by matching prose.
    """
    # Triple quoted blocks first, so a '#' inside a docstring does not survive
    # as code, and a line of prose cannot satisfy a rule.
    text = re.sub(r'u?"""(?:.|\n)*?"""', '""', text)
    text = re.sub(r"u?'''(?:.|\n)*?'''", "''", text)
    lines = []
    for line in text.splitlines():
        if line.strip().startswith("#"):
            continue
        lines.append(line)
    return "\n".join(lines)


def rule_no_fstrings(folder):
    problems = []
    for label, path in py_files(folder):
        if re.search(r"""\bf["']""", _code_only(read(path))):
            problems.append("{0} uses an f-string; IronPython 2.7 cannot "
                            "parse one".format(label))
    return problems


def rule_no_print(folder):
    problems = []
    for label, path in py_files(folder):
        if re.search(r"(^|\s)print\s*\(", _code_only(read(path))):
            problems.append("{0} calls print; tools report through the footer "
                            "and the debug log".format(label))
    return problems


def rule_no_integervalue(folder):
    problems = []
    for label, path in py_files(folder):
        if ".IntegerValue" in _code_only(read(path)):
            problems.append("{0} touches .IntegerValue, which Revit 2026 "
                            "removed".format(label))
    return problems


def rule_no_system_uri(folder):
    problems = []
    for label, path in py_files(folder):
        code = _code_only(read(path))
        if re.search(r"from System import [^\n]*\bUri\b", code) or "System.Uri" in code:
            problems.append("{0} uses System.Uri, which moved assemblies in "
                            "Revit 2025".format(label))
    return problems


def rule_clr_imported_first(folder):
    problems = []
    for module in MODULES:
        path = os.path.join(folder, module + ".py")
        if not os.path.isfile(path):
            continue
        code = _code_only(read(path))
        clr_line = None
        dotnet_line = None
        for number, line in enumerate(code.splitlines(), start=1):
            stripped = line.strip()
            if not stripped.startswith(("import ", "from ")):
                continue
            if stripped.startswith("import rba_clr"):
                if clr_line is None:
                    clr_line = number
                continue
            if re.match(r"(from|import)\s+(System|Autodesk)\b", stripped):
                if dotnet_line is None:
                    dotnet_line = number
        if dotnet_line is not None and (clr_line is None or clr_line > dotnet_line):
            problems.append("{0}.py reaches into System/Autodesk at line {1} "
                            "before importing rba_clr".format(module, dotnet_line))
    return problems


def rule_namespaces_are_real(folder):
    problems = []
    for label, path in py_files(folder):
        code = _code_only(read(path))
        for match in re.finditer(
                r"^\s*from\s+((?:System|Autodesk)[\w.]*)\s+import\s+(.+)$", code, re.M):
            namespace, names = match.group(1), match.group(2)
            if namespace not in NAMESPACES:
                problems.append("{0} imports from unknown namespace "
                                "{1}".format(label, namespace))
                continue
            for raw in names.split(","):
                name = raw.split(" as ")[0].strip().strip("()").strip()
                if not name:
                    continue
                if name not in NAMESPACES[namespace]:
                    problems.append("{0} imports {1} from {2}; the real API does "
                                    "not put it there".format(label, name, namespace))
    return problems


def rule_no_duplicate_definitions(folder):
    problems = []
    for label, path in py_files(folder):
        try:
            tree = ast.parse(read(path))
        except SyntaxError as error:
            problems.append("{0} will not parse: {1}".format(label, error))
            continue
        seen = {}
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                if node.name in seen:
                    problems.append("{0} defines {1} twice; Python silently keeps "
                                    "the last one".format(label, node.name))
                seen[node.name] = True
    return problems


def rule_modules_load(folder):
    problems = []
    install_stubs()
    if folder not in sys.path:
        sys.path.insert(0, folder)
    for module in MODULES:
        for cached in list(sys.modules):
            if cached in MODULES:
                del sys.modules[cached]
    for module in MODULES:
        try:
            __import__(module)
        except Exception as error:
            problems.append("{0}.py will not load against the stub API: "
                            "{1}: {2}".format(module, type(error).__name__, error))
    return problems


def rule_palettes_match(folder):
    problems = []
    path = os.path.join(folder, "rba_theme.py")
    if not os.path.isfile(path):
        return ["rba_theme.py is missing"]
    text = read(path)
    blocks = {}
    for name in ("DARK", "LIGHT"):
        match = re.search(name + r"\s*=\s*\{(.*?)\n\}", text, re.S)
        if not match:
            return ["rba_theme.py has no {0} palette".format(name)]
        blocks[name] = set(re.findall(r'u"(\w+)"\s*:', match.group(1)))
    if blocks["DARK"] != blocks["LIGHT"]:
        missing = blocks["DARK"] ^ blocks["LIGHT"]
        problems.append("the two palettes do not carry the same keys: "
                        "{0}".format(", ".join(sorted(missing))))
    known = theme_keys(folder)
    for key in blocks["DARK"]:
        if key not in known:
            problems.append("palette key {0} has no brush in Theme.xaml".format(key))
    return problems


def rule_changelog_has_version(folder):
    path = os.path.join(folder, "CHANGELOG.md")
    core = os.path.join(folder, "rba_core.py")
    if not os.path.isfile(path) or not os.path.isfile(core):
        return ["CHANGELOG.md or rba_core.py is missing"]
    match = re.search(r'__version__\s*=\s*u?"([\d.]+)"', read(core))
    if not match:
        return ["rba_core.py has no __version__"]
    version = match.group(1)
    if version not in read(path):
        return ["CHANGELOG.md has no entry for v{0}".format(version)]
    return []


def rule_no_shared_files(folder):
    u"""The delivery must not carry a shared and singular file.

    startup.py, hooks and lib\\revobim\\__init__.py are owned by the extension:
    a tool that ships one silently overwrites whatever the last tool put there,
    and nothing fails when it happens.
    """
    banned = ["startup.py", "__init__.py"]
    problems = []
    for name in banned:
        if os.path.isfile(os.path.join(folder, name)):
            problems.append("{0} is a shared and singular file and must ship as "
                            "a banded fragment, not as itself".format(name))
    return problems


def rule_tool_files_present(folder):
    """The three files pyRevit needs beside the loader."""
    problems = []
    for needed in ("script.py", "bundle.yaml", "icon.png"):
        if not os.path.isfile(os.path.join(folder, needed)):
            problems.append("the tool folder has no {0}".format(needed))
    return problems


def rule_name_agrees_everywhere(folder):
    """TOOL_NAME, the folder, the ribbon title and the pane header all agree.

    pyRevit names a ribbon item after its folder, so a rename means renaming
    the folder and deleting the old one or you get two buttons - and a rename
    that reaches three of the four places leaves the old name showing in the
    fourth.
    """
    problems = []
    core = os.path.join(folder, "rba_core.py")
    if not os.path.isfile(core):
        return ["rba_core.py is missing"]
    match = re.search(r'TOOL_NAME\s*=\s*u?"([^"]+)"', read(core))
    if not match:
        return ["rba_core.py has no TOOL_NAME"]
    name = match.group(1)

    stem = os.path.basename(folder.rstrip(os.sep)).rsplit(".", 1)[0].strip()
    if stem.lower() != name.lower():
        problems.append("TOOL_NAME is '{0}' but the folder is '{1}'; pyRevit "
                        "names the ribbon item after the folder".format(name, stem))

    bundle = os.path.join(folder, "bundle.yaml")
    if os.path.isfile(bundle):
        title = ""
        for line in read(bundle).splitlines():
            if line.strip().lower().startswith("title:"):
                title = line.split(":", 1)[1].strip()
                break
        if title.lower() != name.lower():
            problems.append("TOOL_NAME is '{0}' but bundle.yaml says "
                            "'{1}'".format(name, title))

    layout = os.path.join(folder, "RevoBIMAddins.xaml")
    if os.path.isfile(layout):
        text = read(layout)
        tail = name.split(" ", 1)[-1] if " " in name else name
        if 'Text="{0}"'.format(tail) not in text:
            problems.append("the pane header does not carry '{0}', so the "
                            "window still shows the old name".format(tail))
    return problems


def rule_settings_path_unchanged(folder):
    """A rename must not touch the settings path.

    A missing settings file falls back to the defaults silently, so renaming
    it looks exactly like the tool forgetting everything for no stated reason.
    """
    core = os.path.join(folder, "rba_core.py")
    if not os.path.isfile(core):
        return ["rba_core.py is missing"]
    text = read(core)
    for key, wanted in (("SETTINGS_NAME", "revobim_addins.txt"),
                        ("DEBUG_NAME", "revobim_addins_debug.txt")):
        match = re.search(key + r'\s*=\s*u?"([^"]+)"', text)
        if not match:
            return ["rba_core.py has no {0}".format(key)]
        if match.group(1) != wanted:
            return ["{0} is '{1}'; it must stay '{2}' across a rename or every "
                    "saved setting is silently thrown away".format(
                        key, match.group(1), wanted)]
    return []


def rule_no_container_bundle(folder):
    """No bundle.yaml for the panel.

    It is shared and singular: shipping one reverts whatever title or icon the
    panel already has, and nothing fails when it happens.
    """
    panel = os.path.dirname(folder.rstrip(os.sep))
    if os.path.isfile(os.path.join(panel, "bundle.yaml")):
        return ["the panel ships a bundle.yaml; it is shared and singular, so "
                "ship a note instead"]
    return []


def rule_title_is_usable(folder):
    """One line, and prefixed RevoBIM.

    Revit's Keyboard Shortcuts dialog lists ribbon items by title: a plain
    name clashes with other addins and cannot be found in that list, and a
    title carrying a newline is shown wrapped and is awkward to search for.
    """
    path = os.path.join(folder, "bundle.yaml")
    if not os.path.isfile(path):
        return ["bundle.yaml is missing"]
    title = ""
    for line in read(path).splitlines():
        if line.strip().lower().startswith("title:"):
            title = line.split(":", 1)[1].strip()
            break
    if not title:
        return ["bundle.yaml has no title"]
    problems = []
    if "\\n" in title:
        problems.append("the title spans more than one line")
    if not title.lower().startswith("revobim"):
        problems.append("title '{0}' is not prefixed RevoBIM, so it cannot be "
                        "found in Keyboard Shortcuts".format(title))
    return problems


def rule_persistent_engine(folder):
    """A tool that can open a modeless window must keep its engine alive.

    Without __persistentengine__ = True pyRevit tears the engine down when the
    command returns. The window stays on screen with every handler in it dead:
    on screen, responding to nothing, and nothing inside it can report that.
    """
    path = os.path.join(folder, "script.py")
    if not os.path.isfile(path):
        return ["script.py is missing"]
    opens_window = os.path.isfile(os.path.join(folder, "rba_window.py"))
    declared = re.search(r"^__persistentengine__\s*=\s*True", _code_only(read(path)), re.M)
    if opens_window and not declared:
        return ["rba_window.py ships but script.py does not declare "
                "__persistentengine__ = True"]
    return []


def _window_layouts(folder):
    out = []
    for name in LAYOUTS:
        path = os.path.join(folder, name)
        if os.path.isfile(path) and read(path).lstrip().startswith("<Window"):
            out.append(name)
    return out


def rule_window_has_drawer(folder):
    """Every module that opens a Window gives it a drawer.

    The house standard: every window a tool opens - main window and every
    prompt - shrinks to the taskbar. The easy way to break that is a new
    dialog built later that nobody remembered to wire.
    """
    windows = _window_layouts(folder)
    problems = []
    for label, path in py_files(folder):
        code = _code_only(read(path))
        for layout in windows:
            if re.search(r'load_xaml\(\s*u?"' + re.escape(layout) + '"', code):
                if "rba_drawer.attach(" not in code:
                    problems.append("{0} opens {1} without rba_drawer.attach - it "
                                    "cannot shrink to the taskbar".format(label, layout))
    return problems


def rule_shrink_glyphs(folder):
    """Every shrink button carries both glyphs, the up arrow green and hidden.

    Drawn as Paths, never symbol-font characters, so they cannot come out as
    empty boxes on a machine without the font.
    """
    problems = []
    for name in LAYOUTS:
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            continue
        text = read(path)
        if 'x:Name="ShrinkBtn"' not in text:
            continue
        for glyph in ("ShrinkGlyph", "ExpandGlyph"):
            if not re.search(r'<Path x:Name="' + glyph + '"', text):
                problems.append("{0}: ShrinkBtn has no {1} Path".format(name, glyph))
        match = re.search(r'<Path x:Name="ExpandGlyph"([^>]*)>', text, re.S)
        if match:
            attrs = match.group(1)
            if "AccGreen" not in attrs:
                problems.append("{0}: the up arrow is not the palette green".format(name))
            if 'Visibility="Collapsed"' not in attrs:
                problems.append("{0}: the up arrow shows before anything has "
                                "shrunk".format(name))
    return problems


def rule_drawer_wires_everything(folder):
    """rba_drawer.attach wires the button, the keys and the close.

    A shrink button that is drawn and never wired looks exactly like one that
    works, right up to the click.
    """
    path = os.path.join(folder, "rba_drawer.py")
    if not os.path.isfile(path):
        return ["rba_drawer.py is missing"]
    code = _code_only(read(path))
    match = re.search(r"\ndef attach\(.*?(?=\n(?:def |class )|\Z)", code, re.S)
    if not match:
        return ["rba_drawer.py has no attach()"]
    body = match.group(0)
    problems = []
    for needle, what in ((r"glyphs\[0\]\.Click\s*\+=", "the shrink button's Click"),
                         (r"PreviewKeyDown\s*\+=", "PreviewKeyDown"),
                         (r"\.Closed\s*\+=", "Closed")):
        if not re.search(needle, body):
            problems.append("attach() never wires {0}".format(what))
    return problems


def rule_no_window_animation(folder):
    """No WPF animation anywhere: the drawer is eased by hand.

    An animation holds its end value and outranks every later assignment; one
    left on a window's Top or Height freezes it for good, silently.
    """
    problems = []
    for label, path in py_files(folder):
        code = _code_only(read(path))
        for needle in ("BeginAnimation(", "Storyboard", "DoubleAnimation"):
            if needle in code:
                problems.append("{0} uses {1} - ease by hand, as rba_drawer "
                                "does".format(label, needle.rstrip("(")))
    return problems


def rule_registers_only_at_startup(folder):
    """The pane is registered from rba_dock.register alone, on an asked host.

    Registering from a command is accepted and the pane is never created, after
    which GetDockablePane throws for the session. And the host must be asked -
    1.2.0 to 1.3.0 named one directly and failed silently where it was not
    defined.
    """
    problems = []
    for label, path in py_files(folder):
        code = _code_only(read(path))
        if label != "rba_dock.py" and re.search(r"\.RegisterDockablePane\(", code):
            problems.append("{0} registers the pane - only rba_dock.register, "
                            "run from startup.py, may".format(label))
    dock = os.path.join(folder, "rba_dock.py")
    if not os.path.isfile(dock):
        return problems + ["rba_dock.py is missing"]
    code = _code_only(read(dock))
    if not re.search(r"def register\(\s*\*", code):
        problems.append("rba_dock.register no longer takes *candidates")
    if not re.search(r"callable\(getattr\(\s*candidate\s*,", code):
        problems.append("rba_dock no longer asks each candidate for the method")
    return problems


def rule_no_hardcoded_colours(folder):
    """No colour written straight into a layout - every one is a palette key.

    A literal colour is invisible to a theme switch. 1.3.0's floating window
    had its frame edge as #4A4A50 and its title strip painted once at open, so
    switching to light left a dark bar across the top of a light window.
    White text on the blue logo is the one exception: it is white in both.
    """
    allowed = set(["#FFFFFF"])
    problems = []
    for name in LAYOUTS:
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            continue
        for match in re.finditer(r'(\w+)="(#[0-9A-Fa-f]{3,8})"', read(path)):
            if match.group(2).upper() not in allowed:
                problems.append("{0}: {1}=\"{2}\" is not a palette key, so it will "
                                "not follow the theme".format(name, match.group(1),
                                                              match.group(2)))
    return problems


def rule_pane_host_never_black(folder):
    """The docked pane's host is painted, built on more than one event, and
    shows its failures in colours that can be read.

    1.4.0 handed Revit an unpainted Border (drawn black), built only on
    Loaded, and showed a failure as default black text on that black - so a
    pane that was never built and one that failed looked identical and said
    nothing.
    """
    path = os.path.join(folder, "rba_dock.py")
    if not os.path.isfile(path):
        return ["rba_dock.py is missing"]
    code = _code_only(read(path))
    match = re.search(r"\nclass PaneProvider\(.*?(?=\n(?:def |class )\w)", code, re.S)
    if not match:
        return ["rba_dock.py has no PaneProvider"]
    body = match.group(0)
    problems = []
    if not re.search(r"self\.host\.Background\s*=", body):
        problems.append("the pane host is not painted - Revit draws it black")
    if not re.search(r"IsVisibleChanged\s*\+=", body):
        problems.append("the pane is built on Loaded alone")
    message = re.search(r"\ndef _message\(.*?(?=\ndef )", code, re.S)
    if not message or message.group(0).count(".Foreground =") < 2:
        problems.append("the pane's messages fall back to default (black) text")
    return problems


def rule_no_late_imports(folder):
    """No module of the tool's is first imported inside a function.

    The docked panel lives in pyRevit's start up engine, whose sys.path is
    reset once startup.py has run. 1.4.1 built the panel later, on first show,
    with an "import rba_pane" inside the build - and died with "No module
    named rba_pane". The one late import allowed is that build's, and only
    straight after ensure_tool_path() has put the folder back.
    """
    problems = []
    for label, path in py_files(folder):
        if not label.startswith("rba_"):
            continue
        lines = _code_only(read(path)).splitlines()
        for index, line in enumerate(lines):
            if not re.match(r"\s+(import|from)\s+rba_", line):
                continue
            if (label == "rba_dock.py" and "import rba_pane" in line
                    and index > 0 and "ensure_tool_path()" in lines[index - 1]):
                continue
            problems.append("{0} imports {1} inside a function - in the docked "
                            "pane that import runs after pyRevit has reset sys.path"
                            .format(label, line.strip()))
    return problems


RULES = [
    ("every .xaml parses as XML", rule_xaml_parses),
    ("no '--' inside an XML comment", rule_no_double_hyphen_comment),
    ("no Alignment=\"Baseline\"", rule_no_baseline_alignment),
    ("no StaticResource in a layout", rule_no_static_resource_in_layout),
    ("every DynamicResource key exists in Theme.xaml", rule_dynamic_keys_exist),
    ("no style applied to an element its TargetType does not match",
     rule_style_target_type_matches),
    ("every FindName has a matching x:Name", rule_findname_has_xname),
    ("no f-strings", rule_no_fstrings),
    ("no print statements", rule_no_print),
    ("no bare .IntegerValue", rule_no_integervalue),
    ("no System.Uri", rule_no_system_uri),
    ("rba_clr is imported before any System/Autodesk name", rule_clr_imported_first),
    ("every .NET name comes from the namespace the real API puts it in",
     rule_namespaces_are_real),
    ("nothing is defined twice at module level", rule_no_duplicate_definitions),
    ("every module loads against the stub API", rule_modules_load),
    ("both palettes carry the same keys, and Theme.xaml has a brush for each",
     rule_palettes_match),
    ("CHANGELOG.md carries the shipped version", rule_changelog_has_version),
    ("no shared and singular file in the delivery", rule_no_shared_files),
    ("the tool folder carries script.py, bundle.yaml and icon.png", rule_tool_files_present),
    ("the tool name agrees in all four places", rule_name_agrees_everywhere),
    ("a rename has not moved the settings path", rule_settings_path_unchanged),
    ("no bundle.yaml for the panel", rule_no_container_bundle),
    ("the ribbon title is one line and RevoBIM prefixed", rule_title_is_usable),
    ("a tool with a modeless window keeps its engine alive", rule_persistent_engine),
    ("every window the tool opens has a drawer", rule_window_has_drawer),
    ("every shrink button carries both glyphs, the up arrow green", rule_shrink_glyphs),
    ("the drawer wires its button, keys and close", rule_drawer_wires_everything),
    ("no WPF animation is left holding a window", rule_no_window_animation),
    ("the pane is registered at start up only, on an asked host",
     rule_registers_only_at_startup),
    ("no colour is hard coded into a layout", rule_no_hardcoded_colours),
    ("the docked pane is never left black", rule_pane_host_never_black),
    ("no tool module is first imported inside a function", rule_no_late_imports),
]


def run(folder=HERE, quiet=False):
    failures = 0
    for title, rule in RULES:
        try:
            problems = rule(folder)
        except Exception as error:
            problems = ["the rule itself threw: {0}".format(error)]
        if problems:
            failures += 1
            if not quiet:
                print("FAIL  {0}".format(title))
                for problem in problems:
                    print("        {0}".format(problem))
        elif not quiet:
            print("ok    {0}".format(title))
    if not quiet:
        print("")
        print("{0} of {1} rules pass".format(len(RULES) - failures, len(RULES)))
    return failures


# ----------------------------------------------------------------------
# selftest - break each rule on purpose and confirm it fires
# ----------------------------------------------------------------------

def _edit(folder, name, old, new):
    path = os.path.join(folder, name)
    text = read(path)
    if old not in text:
        raise AssertionError("breakage anchor not found in {0}: {1}".format(name, old))
    write(path, text.replace(old, new, 1))


def _bump_version(folder):
    """Break the changelog rule without hard coding a version number.

    The first version of this breakage anchored on the literal 1.0.0 and went
    stale the moment the tool was bumped - the selftest then died on a missing
    anchor rather than reporting a rule that does not work.
    """
    path = os.path.join(folder, "rba_core.py")
    text = read(path)
    match = re.search(r'__version__\s*=\s*u?"[\d.]+"', text)
    if not match:
        raise AssertionError("rba_core.py has no __version__ to break")
    write(path, text.replace(match.group(0), '__version__ = u"9.9.9"', 1))


BREAKAGES = [
    ("every .xaml parses as XML",
     lambda f: _edit(f, "RevoBIMAddins.xaml", "</Grid>", "</Grid")),
    ("no '--' inside an XML comment",
     lambda f: _edit(f, "RevoBIMAddins.xaml", "<!-- ============================ header",
                     "<!-- ---------------------------- header")),
    ("no Alignment=\"Baseline\"",
     lambda f: _edit(f, "RevoBIMAddins.xaml",
                     'HorizontalAlignment="Right" VerticalAlignment="Top">',
                     'HorizontalAlignment="Right" VerticalAlignment="Baseline">')),
    ("no StaticResource in a layout",
     lambda f: _edit(f, "RevoBIMAddins.xaml", '{DynamicResource BgBar}',
                     '{StaticResource BgBar}')),
    ("every DynamicResource key exists in Theme.xaml",
     lambda f: _edit(f, "RevoBIMAddins.xaml", '{DynamicResource AccOrange}',
                     '{DynamicResource AccTangerine}')),
    ("no style applied to an element its TargetType does not match",
     lambda f: _edit(f, "RbaSettings.xaml", '<TextBox x:Name="NameFilterBox"',
                     '<TextBox Style="{DynamicResource GreenButton}" x:Name="NameFilterBox"')),
    ("every FindName has a matching x:Name",
     lambda f: _edit(f, "rba_pane.py", 'self.search_box = self.find(u"SearchBox")',
                     'self.search_box = self.find(u"SerchBox")')),
    ("no f-strings",
     lambda f: _edit(f, "rba_core.py", "def natural_key(value):",
                     "def natural_key(value):\n    _ = f\"{value}\"")),
    ("no print statements",
     lambda f: _edit(f, "rba_core.py", "def natural_key(value):",
                     "def natural_key(value):\n    print(value)")),
    ("no bare .IntegerValue",
     lambda f: _edit(f, "rba_core.py", "def natural_key(value):",
                     "def natural_key(value):\n    _ = value.IntegerValue")),
    ("no System.Uri",
     lambda f: _edit(f, "rba_ui.py", "from System.Windows.Markup import XamlReader",
                     "from System import Uri\nfrom System.Windows.Markup import XamlReader")),
    ("rba_clr is imported before any System/Autodesk name",
     lambda f: _edit(f, "rba_ui.py", "import rba_clr  # noqa: F401", "import os")),
    ("every .NET name comes from the namespace the real API puts it in",
     lambda f: _edit(f, "rba_pane.py",
                     "from System.Windows.Controls import (Border, Grid, StackPanel, TextBlock, Image,",
                     "from System.Windows import Border\nfrom System.Windows.Controls import (Grid, StackPanel, TextBlock, Image,")),
    ("nothing is defined twice at module level",
     lambda f: _edit(f, "rba_core.py", "def natural_key(value):",
                     "def to_text(value):\n    return value\n\n\ndef natural_key(value):")),
    ("every module loads against the stub API",
     lambda f: _edit(f, "rba_scan.py", "import os", "import os\nraise ImportError('bench')")),
    ("both palettes carry the same keys, and Theme.xaml has a brush for each",
     lambda f: _edit(f, "rba_theme.py", '    u"SelHighlight": u"#CBDDEE",', "")),
    ("CHANGELOG.md carries the shipped version",
     _bump_version),
    ("no shared and singular file in the delivery",
     lambda f: write(os.path.join(f, "startup.py"), u"# oops\n")),
    ("the tool folder carries script.py, bundle.yaml and icon.png",
     lambda f: os.remove(os.path.join(f, "icon.png"))),
    ("the tool name agrees in all four places",
     lambda f: _edit(f, "rba_core.py", 'TOOL_NAME = u"RevoBIM Addin Manager"',
                     'TOOL_NAME = u"RevoBIM Addins"')),
    ("a rename has not moved the settings path",
     lambda f: _edit(f, "rba_core.py", 'SETTINGS_NAME = u"revobim_addins.txt"',
                     'SETTINGS_NAME = u"revobim_addin_manager.txt"')),
    ("no bundle.yaml for the panel",
     lambda f: write(os.path.join(os.path.dirname(f.rstrip(os.sep)), "bundle.yaml"),
                     u"title: oops\n")),
    ("the ribbon title is one line and RevoBIM prefixed",
     lambda f: _edit(f, "bundle.yaml", "title: RevoBIM Addin Manager",
                     "title: Addin Manager")),
    ("a tool with a modeless window keeps its engine alive",
     lambda f: _edit(f, "script.py", "__persistentengine__ = True",
                     "# engine left to be torn down")),
    ("every window the tool opens has a drawer",
     lambda f: _edit(f, "rba_settings.py", "    drawers.append(rba_drawer.attach(",
                     "    drawers.append(rba_drawer.Drawer(")),
    ("every shrink button carries both glyphs, the up arrow green",
     lambda f: _edit(f, "RbaShortcut.xaml",
                     'Stroke="{DynamicResource AccGreen}"',
                     'Stroke="{DynamicResource AccBlue}"')),
    ("the drawer wires its button, keys and close",
     lambda f: _edit(f, "rba_drawer.py", "    glyphs[0].Click += on_click\n", "")),
    ("no WPF animation is left holding a window",
     lambda f: _edit(f, "rba_drawer.py", "    def _slide(self, start, end, done, instant):",
                     "    def _slide(self, start, end, done, instant):\n"
                     "        self.window.BeginAnimation(None, None)")),
    ("the pane is registered at start up only, on an asked host",
     lambda f: _edit(f, "rba_pane.py", "    rba_launch.set_uiapp(uiapp)\n    if rba_dock",
                     "    rba_launch.set_uiapp(uiapp)\n"
                     "    uiapp.RegisterDockablePane(None, None, None)\n    if rba_dock")),
    ("no colour is hard coded into a layout",
     lambda f: _edit(f, "RbaWindow.xaml", 'BorderBrush="{DynamicResource BrdWindow}"',
                     'BorderBrush="#4A4A50"')),
    ("the docked pane is never left black",
     lambda f: _edit(f, "rba_dock.py",
                     '        self.host.Background = _brush(self.colours[u"BgWindow"])\n', "")),
    ("no tool module is first imported inside a function",
     lambda f: _edit(f, "rba_dock.py", "            ensure_tool_path()\n", "")),
]


def selftest():
    lookup = dict(RULES)
    caught = 0
    for title, breakage in BREAKAGES:
        rule = lookup.get(title)
        if rule is None:
            print("FAIL  no rule called '{0}'".format(title))
            continue
        folder = tempfile.mkdtemp(prefix="rba_bench_")
        # Copied under its REAL folder name: the pulldown naming rule compares
        # each button folder against the folder it sits in, so a copy called
        # "tool" gave that rule nothing to collide with and it passed its own
        # selftest while doing nothing.
        target = os.path.join(folder, os.path.basename(HERE.rstrip(os.sep)))
        shutil.copytree(HERE, target)
        try:
            try:
                breakage(target)
            except AssertionError as error:
                # A breakage whose anchor has moved proves nothing - say so
                # rather than crash the run or count it as caught.
                print("FAIL  '{0}': {1}".format(title, error))
                continue
            try:
                problems = rule(target)
            except Exception as error:
                problems = ["rule threw: {0}".format(error)]
            if problems:
                caught += 1
                print("ok    caught: {0}".format(title))
            else:
                print("FAIL  breaking '{0}' did not fire the rule".format(title))
        finally:
            shutil.rmtree(folder, ignore_errors=True)
    print("")
    print("{0} of {1} rules caught their own breakage".format(caught, len(BREAKAGES)))
    return len(BREAKAGES) - caught


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(1 if selftest() else 0)
    sys.exit(1 if run() else 0)
