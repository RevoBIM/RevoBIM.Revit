# -*- coding: utf-8 -*-
"""Level Manager - static bench rules. Run with plain CPython from this folder:

    python import_check.py              run every rule against the tool
    python import_check.py --selftest   break each rule on purpose and prove it fires

A rule nobody has seen fail is a rule that does not work, so every rule here
has a deliberate breakage in SELFTEST and the selftest fails if it passes.
"""
import ast
import io
import os
import re
import sys
import tokenize
from xml.dom import minidom

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL_MODULES = ["script.py", "lvm_clr.py", "lvm_core.py", "lvm_revit.py",
                "lvm_ops.py", "lvm_ui.py", "lvm_window.py"]
XAMLS = ["Theme.xaml", "LevelManager.xaml", "TreeCell.xaml", "AssignLevel.xaml",
         "AddParameter.xaml", "Results.xaml", "ValueFilter.xaml", "Prompt.xaml",
         "DeleteLevel.xaml"]
WINDOWS = ["LevelManager.xaml", "AssignLevel.xaml", "AddParameter.xaml",
           "Results.xaml", "Prompt.xaml", "DeleteLevel.xaml"]

# namespace -> assemblies that provide it (None: loaded by pyRevit itself)
ASSEMBLY_FOR = {
    "System": ["mscorlib", "System"],
    "System.IO": ["mscorlib", "System"],
    "System.Collections.Generic": ["mscorlib", "System"],
    "System.Data": ["System.Data"],
    "System.Windows": ["PresentationFramework", "PresentationCore", "WindowsBase"],
    "System.Windows.Controls": ["PresentationFramework"],
    "System.Windows.Controls.Primitives": ["PresentationFramework"],
    "System.Windows.Data": ["PresentationFramework"],
    "System.Windows.Input": ["PresentationCore"],
    "System.Windows.Markup": ["PresentationFramework", "System.Xaml"],
    "System.Windows.Media": ["PresentationCore"],
    "System.Windows.Media.Imaging": ["PresentationCore"],
    "System.Windows.Shapes": ["PresentationFramework"],
    "System.Windows.Interop": ["PresentationFramework", "PresentationCore"],
    "System.Windows.Threading": ["WindowsBase"],
    "System.Windows.Forms": ["System.Windows.Forms"],
    "Autodesk.Revit.DB": None,
    "Autodesk.Revit.UI": None,
}

ENUMS = {
    "VerticalAlignment": {"Top", "Center", "Bottom", "Stretch"},
    "HorizontalAlignment": {"Left", "Center", "Right", "Stretch"},
    "VerticalContentAlignment": {"Top", "Center", "Bottom", "Stretch"},
    "HorizontalContentAlignment": {"Left", "Center", "Right", "Stretch"},
    "Visibility": {"Visible", "Hidden", "Collapsed"},
    "Orientation": {"Horizontal", "Vertical"},
    "TextWrapping": {"Wrap", "NoWrap", "WrapWithOverflow"},
    "TextTrimming": {"None", "CharacterEllipsis", "WordEllipsis"},
    "WindowStyle": {"None", "SingleBorderWindow", "ThreeDBorderWindow", "ToolWindow"},
    "ResizeMode": {"NoResize", "CanMinimize", "CanResize", "CanResizeWithGrip"},
    "SelectionMode": {"Single", "Multiple", "Extended"},
    "SelectionUnit": {"Cell", "FullRow", "CellOrRowHeader"},
    "DockPanel.Dock": {"Left", "Top", "Right", "Bottom"},
    "WindowStartupLocation": {"Manual", "CenterScreen", "CenterOwner"},
    "GridLinesVisibility": {"All", "Horizontal", "Vertical", "None"},
    "HeadersVisibility": {"All", "Column", "Row", "None"},
    "FontWeight": {"Normal", "Bold", "SemiBold", "Light", "Medium", "Thin", "Black", "ExtraBold"},
}


# =========================================================================
# Loading
# =========================================================================

def load_files(folder=HERE):
    files = {}
    for name in TOOL_MODULES + XAMLS + ["CHANGELOG.md"]:
        path = os.path.join(folder, name)
        with io.open(path, "r", encoding="utf-8") as handle:
            files[name] = handle.read()
    return files


def code_only(src):
    """Source with comments and docstrings blanked, so a rule can never pass
    or fail on prose."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return src
    doc_starts = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(
                    getattr(body[0], "value", None), ast.Constant) and isinstance(body[0].value.value, str):
                doc_starts.add((body[0].value.lineno, body[0].value.col_offset))
    lines = src.splitlines(True)
    out = list(lines)
    edits = []
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            edits.append((tok.start, tok.end, ""))
        elif tok.type == tokenize.STRING and tok.start in doc_starts:
            edits.append((tok.start, tok.end, '""'))
    for (sr, sc), (er, ec), repl in reversed(edits):
        if sr == er:
            line = out[sr - 1]
            out[sr - 1] = line[:sc] + repl + line[ec:]
        else:
            first = out[sr - 1][:sc] + repl
            last = out[er - 1][ec:]
            out[sr - 1] = first + "\n" * (er - sr) + last
            for r in range(sr, er):
                out[r] = ""
    return "".join(out)


def theme_keys(files):
    keys = set(re.findall(r'x:Key="([^"]+)"', files["Theme.xaml"]))
    return keys


def palette_keys(files):
    tree = ast.parse(files["lvm_core.py"])
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) \
                and node.targets[0].id in ("PALETTE_DARK", "PALETTE_LIGHT"):
            out[node.targets[0].id] = set([k.value for k in node.value.keys])
    return out


def style_targets(files):
    out = {}
    doc = minidom.parseString(files["Theme.xaml"].encode("utf-8"))
    for st in doc.getElementsByTagName("Style"):
        key = st.getAttribute("x:Key")
        if key:
            out[key] = st.getAttribute("TargetType")
    for tpl in doc.getElementsByTagName("ControlTemplate"):
        pass
    return out


# =========================================================================
# Rules - each returns a list of problems (empty = pass)
# =========================================================================

def rule_xaml_parses(files):
    out = []
    for name in XAMLS:
        try:
            minidom.parseString(files[name].encode("utf-8"))
        except Exception as ex:
            out.append("{0}: does not parse - {1}".format(name, ex))
    return out


def rule_xaml_enums(files):
    out = []
    for name in XAMLS:
        try:
            doc = minidom.parseString(files[name].encode("utf-8"))
        except Exception:
            continue
        for el in doc.getElementsByTagName("*"):
            for attr, allowed in ENUMS.items():
                if el.hasAttribute(attr):
                    value = el.getAttribute(attr)
                    if not value.startswith("{") and value not in allowed:
                        out.append("{0}: {1}=\"{2}\" is not a WPF value".format(name, attr, value))
            if el.tagName == "Setter":
                prop = el.getAttribute("Property")
                value = el.getAttribute("Value")
                if prop in ENUMS and value and not value.startswith("{") and value not in ENUMS[prop]:
                    out.append("{0}: Setter {1}=\"{2}\" is not a WPF value".format(name, prop, value))
    return out


def rule_no_static_resource(files):
    return ["{0}: StaticResource used".format(n) for n in XAMLS if "StaticResource" in files[n]]


def rule_resource_keys(files):
    known = theme_keys(files) | palette_keys(files).get("PALETTE_DARK", set())
    out = []
    for name in XAMLS:
        for key in re.findall(r"DynamicResource\s+([A-Za-z0-9_]+)", files[name]):
            if key not in known:
                out.append("{0}: DynamicResource {1} is not defined".format(name, key))
    for name in TOOL_MODULES:
        code = code_only(files[name])
        for key in re.findall(r'SetResourceReference\([^,]+,\s*"([^"]+)"\)', code):
            if key not in known:
                out.append("{0}: SetResourceReference key {1} is not defined".format(name, key))
        for key in re.findall(r'TryFindResource\(\s*"([^"]+)"', code):
            if key not in known:
                out.append("{0}: TryFindResource key {1} is not defined".format(name, key))
        for a, b in re.findall(r'TryFindResource\(\s*"([^"]+)"\s+if[^"]+else\s+"([^"]+)"\)', code):
            for key in (a, b):
                if key not in known:
                    out.append("{0}: TryFindResource key {1} is not defined".format(name, key))
    return out


def rule_keyed_style_targets(files):
    targets = style_targets(files)
    out = []
    for name in XAMLS:
        try:
            doc = minidom.parseString(files[name].encode("utf-8"))
        except Exception:
            continue
        for el in doc.getElementsByTagName("*"):
            st = el.getAttribute("Style")
            m = re.match(r"\{DynamicResource\s+([A-Za-z0-9_]+)\}", st or "")
            if not m:
                continue
            key = m.group(1)
            want = targets.get(key)
            tag = el.tagName.split(":")[-1]
            if want and want != tag:
                out.append("{0}: <{1}> uses style {2} made for {3}".format(name, tag, key, want))
    code = code_only(files["lvm_window.py"])
    for key in set(re.findall(r'"(Cell[A-Za-z]+)"', code)):
        if targets.get(key) != "TextBlock":
            out.append("lvm_window.py: ElementStyle {0} must target TextBlock".format(key))
    for key in re.findall(r'RowStyleProperty,\s*"([^"]+)"', code):
        if targets.get(key) != "DataGridRow":
            out.append("lvm_window.py: RowStyle {0} must target DataGridRow".format(key))
    return out


def rule_palettes_match(files):
    pal = palette_keys(files)
    dark, light = pal.get("PALETTE_DARK", set()), pal.get("PALETTE_LIGHT", set())
    out = []
    if dark != light:
        out.append("palettes differ: {0}".format(sorted(dark ^ light)))
    brushes = set(re.findall(r'<SolidColorBrush x:Key="([^"]+)"', files["Theme.xaml"]))
    if brushes != dark:
        out.append("Theme.xaml brushes and palette differ: {0}".format(sorted(brushes ^ dark)))
    return out


def rule_findname(files):
    names = set()
    for name in XAMLS:
        names.update(re.findall(r'x:Name="([^"]+)"', files[name]))
    out = []
    for name in TOOL_MODULES:
        for key in re.findall(r'(?:FindName|\bf)\(\s*"([^"]+)"\s*\)', code_only(files[name])):
            if key not in names:
                out.append("{0}: FindName(\"{1}\") has no x:Name".format(name, key))
        for key in re.findall(r'for name in \(([^)]*)\)', code_only(files[name])):
            for n in re.findall(r'"([^"]+)"', key):
                if n.endswith("Btn") and n not in names:
                    out.append("{0}: {1} has no x:Name".format(name, n))
    return out


def rule_banned_syntax(files):
    out = []
    for name in TOOL_MODULES:
        code = code_only(files[name])
        if re.search(r"(?<![A-Za-z0-9_])[fF][rR]?['\"]", code):
            out.append("{0}: f-string".format(name))
        if re.search(r"(?m)^\s*print[\s(]", code):
            out.append("{0}: print".format(name))
        if re.search(r"System\.Uri|import\s+Uri|\bUri\(", code):
            out.append("{0}: System.Uri".format(name))
        stripped = re.sub(r"def eid_value\(.*?\n(?=\S)", "", code, flags=re.S)
        if re.search(r"\.IntegerValue\b", stripped):
            out.append("{0}: bare .IntegerValue outside eid_value".format(name))
    return out


def rule_non_ascii(files):
    out = []
    for name in TOOL_MODULES:
        src = files[name]
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            text = tok.string
            if all(ord(c) < 128 for c in text):
                continue
            if tok.type == tokenize.STRING and text[:1] in "uU":
                continue
            out.append("{0}:{1}: non-ASCII outside a u'' literal".format(name, tok.start[0]))
    return out


def _import_lines(code):
    out = []
    for i, line in enumerate(code.splitlines()):
        m = re.match(r"\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", line)
        if m:
            out.append((i, m.group(1) or m.group(2), line))
    return out


def rule_clr_first(files):
    out = []
    for name in TOOL_MODULES:
        if name in ("lvm_clr.py", "script.py", "lvm_core.py"):
            continue
        lines = _import_lines(code_only(files[name]))
        clr_at = None
        for i, mod, line in lines:
            if mod == "lvm_clr":
                clr_at = i
                break
        for i, mod, line in lines:
            if mod.split(".")[0] in ("System", "Autodesk"):
                if clr_at is None or i < clr_at:
                    out.append("{0}:{1}: {2} before lvm_clr".format(name, i + 1, mod))
                break
    return out


def _assemblies(files):
    tree = ast.parse(files["lvm_clr.py"])
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "_ASSEMBLIES":
            return [e.value for e in node.value.elts]
    return []


def rule_assemblies_referenced(files):
    refs = set(_assemblies(files))
    out = []
    for name in TOOL_MODULES:
        for i, mod, line in _import_lines(code_only(files[name])):
            if mod.split(".")[0] not in ("System", "Autodesk"):
                continue
            if mod in ("Autodesk", "Autodesk.Revit"):
                continue
            if mod not in ASSEMBLY_FOR:
                out.append("{0}: namespace {1} is not in ASSEMBLY_FOR".format(name, mod))
                continue
            need = ASSEMBLY_FOR[mod]
            if need is not None and not refs.intersection(need):
                out.append("{0}: {1} needs one of {2} referenced in lvm_clr".format(name, mod, need))
    return out


def rule_no_revitapi_reference(files):
    bad = [a for a in _assemblies(files) if a.startswith("RevitAPI")]
    out = ["lvm_clr.py references {0} (pyRevit loads it)".format(a) for a in bad]
    for name in TOOL_MODULES:
        if re.search(r"AddReference\(\s*['\"]RevitAPI", code_only(files[name])):
            out.append("{0}: clr.AddReference RevitAPI".format(name))
    return out


def rule_no_duplicate_defs(files):
    out = []
    for name in TOOL_MODULES:
        tree = ast.parse(files[name])
        scopes = [("module", tree.body)]
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                scopes.append((node.name, node.body))
        for scope, body in scopes:
            seen = set()
            for node in body:
                if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                    if node.name in seen:
                        out.append("{0}: {1}.{2} defined twice".format(name, scope, node.name))
                    seen.add(node.name)
    return out


def rule_changelog(files):
    m = re.search(r'__version__\s*=\s*"([^"]+)"', files["lvm_core.py"])
    if not m:
        return ["no __version__ in lvm_core.py"]
    if "## " + m.group(1) not in files["CHANGELOG.md"]:
        return ["CHANGELOG.md has no entry for {0}".format(m.group(1))]
    return []


def rule_thin_loader(files):
    src = files["script.py"]
    code = code_only(src)
    out = []
    if not re.search(r"(?m)^__persistentengine__\s*=\s*True", code):
        out.append("script.py: __persistentengine__ = True missing")
    if re.search(r"(?m)^(from|import)\s+(System|Autodesk|clr)", code):
        out.append("script.py: imports .NET at module level")
    if "AddReference" in code:
        out.append("script.py: clr.AddReference in the loader")
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module]
            for n in names:
                if n not in ("os", "sys", "traceback"):
                    out.append("script.py: top-level import of {0} can fail outside the stages".format(n))
    return out


def rule_raise_read(files):
    out = []
    for name in TOOL_MODULES:
        tree = ast.parse(files[name])
        for node in ast.walk(tree):
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) \
                    and isinstance(node.value.func, ast.Attribute) and node.value.func.attr == "Raise":
                out.append("{0}:{1}: Raise() result ignored".format(name, node.lineno))
    return out


def rule_core_pure(files):
    out = []
    for i, mod, line in _import_lines(code_only(files["lvm_core.py"])):
        if mod.split(".")[0] in ("System", "Autodesk", "clr", "lvm_clr"):
            out.append("lvm_core.py: imports {0}".format(mod))
    return out


def rule_enums_late(files):
    out = []
    for name in TOOL_MODULES:
        code = code_only(files[name])
        for m in re.finditer(r"\b(BuiltInParameter|BuiltInCategory)\.[A-Z_]", code):
            out.append("{0}: {1} member read directly - use getattr at call time".format(name, m.group(1)))
    return out


def rule_no_dispatcher_in_logic(files):
    out = []
    for name in ("lvm_core.py", "lvm_revit.py"):
        if "Dispatcher" in code_only(files[name]):
            out.append("{0}: touches the Dispatcher (never pump inside a transaction)".format(name))
    return out


def rule_chrome(files):
    out = []
    for name in WINDOWS:
        src = files[name]
        if 'WindowStyle="None"' not in src or 'AllowsTransparency="True"' not in src:
            out.append("{0}: not borderless custom chrome".format(name))
        if 'x:Name="Header"' not in src:
            out.append("{0}: no Header to drag by".format(name))
        if 'x:Name="VersionTxt"' not in src:
            out.append("{0}: no version in the header".format(name))
    if 'x:Name="ThemeBtn"' not in files["LevelManager.xaml"]:
        out.append("LevelManager.xaml: no theme button top right")
    if 'x:Name="DebugChk"' not in files["LevelManager.xaml"]:
        out.append("LevelManager.xaml: no Debug tick")
    return out


_PATH_OK = re.compile(r"^[MLHVZACQSTmlhvzacqst0-9.,\s-]+$")


def rule_icons_parse(files):
    tree = ast.parse(files["lvm_core.py"])
    out = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "ICONS":
            for k, v in zip(node.value.keys, node.value.values):
                data = v.value
                if not _PATH_OK.match(data) or not data.strip().startswith("M"):
                    out.append("ICONS[{0}] is not path data".format(k.value))
                for cmd in re.findall(r"A([^A-Za-z]*)", data):
                    nums = re.findall(r"-?\d+(?:\.\d+)?", cmd)
                    if len(nums) % 7 != 0:
                        out.append("ICONS[{0}] arc has {1} numbers".format(k.value, len(nums)))
    return out


def rule_shared_files(files, folder=HERE):
    out = []
    root = folder
    for _ in range(4):
        root = os.path.dirname(root)
        if root.endswith(".extension"):
            break
    if not root.endswith(".extension"):
        return out
    for rel in ("startup.py", os.path.join("lib", "revobim", "__init__.py")):
        if os.path.exists(os.path.join(root, rel)):
            out.append("delivery ships shared file {0}".format(rel))
    panel = os.path.dirname(folder)
    if os.path.exists(os.path.join(panel, "bundle.yaml")):
        out.append("delivery ships the panel's bundle.yaml")
    hooks = os.path.join(root, "hooks")
    if os.path.isdir(hooks) and os.listdir(hooks):
        out.append("delivery ships hooks")
    return out


def rule_settings_keys(files):
    tree = ast.parse(files["lvm_core.py"])
    defaults = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "DEFAULTS":
            defaults = set([k.value for k in node.value.keys])
    out = []
    code = code_only(files["lvm_window.py"])
    used = set(re.findall(r'self\.settings\["([^"]+)"\]\s*=', code))
    for block in re.findall(r"self\.settings\.update\(\{(.*?)\}\)", code, re.S):
        used.update(re.findall(r'"([a-z_]+)":', block))
    for key in used:
        if key not in defaults:
            out.append("settings key {0} is saved but not in DEFAULTS - dropped on load".format(key))
    return out


def rule_handlers_exist(files):
    out = []
    tree = ast.parse(files["lvm_window.py"])
    for cls in [n for n in tree.body if isinstance(n, ast.ClassDef)]:
        methods = set([f.name for f in cls.body if isinstance(f, ast.FunctionDef)])
        for node in ast.walk(cls):
            if isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Add) \
                    and isinstance(node.value, ast.Attribute) \
                    and isinstance(node.value.value, ast.Name) and node.value.value.id == "self":
                if node.value.attr not in methods and node.value.attr.startswith("on_"):
                    out.append("{0}: handler self.{1} does not exist".format(cls.name, node.value.attr))
    return out


def rule_icon_label(files):
    out = []
    for name in ("lvm_window.py",):
        code = code_only(files[name])
        targets = set(re.findall(r"ui\.line_icon\(([^,]+),", code))
        for t in targets:
            t = t.strip()
            if re.search(re.escape(t) + r"\.Content\s*=", code):
                out.append("{0}: {1}.Content set after line_icon - the icon is lost".format(name, t))
    return out


def rule_egg_logo_only(files):
    """Pacman is armed on the logo alone - never egg_hook.attach (whole window)."""
    code = code_only(files["lvm_ui.py"])
    out = []
    if re.search(r"\.attach\(", code):
        out.append("lvm_ui.py: egg_hook.attach arms the whole window")
    if not re.search(r"logo\.MouseLeftButtonDown\s*\+=", code):
        out.append("lvm_ui.py: the egg is not wired to the logo")
    if not re.search(r"counter\.reset\(\)", code):
        out.append("lvm_ui.py: clicks elsewhere do not reset the count")
    if re.search(r"\bwindow\.(Preview)?MouseLeftButtonDown\s*\+=\s*on_logo", code):
        out.append("lvm_ui.py: the egg counter is on the window, not the logo")
    return out


def rule_drawer_everywhere(files):
    """Every window carries a shrink button with both glyphs, beside full
    screen and close, and every window the code builds wires it."""
    out = []
    for name in WINDOWS:
        src = files[name]
        for need in ('x:Name="ShrinkBtn"', 'x:Name="ShrinkGlyph"', 'x:Name="ExpandGlyph"'):
            if need not in src:
                out.append("{0}: no {1}".format(name, need.split('"')[1]))
        m = re.search(r'x:Name="ExpandGlyph"[^>]*>', src, re.S) or re.search(r'<Path[^>]*x:Name="ExpandGlyph"[^>]*/>', src, re.S)
        tag = re.search(r'<Path(?:(?!/>).)*x:Name="ExpandGlyph"(?:(?!/>).)*/>', src, re.S)
        if tag:
            t = tag.group(0)
            if 'Visibility="Collapsed"' not in t:
                out.append("{0}: the green arrow shows before the window is shrunk".format(name))
            if "{DynamicResource Green}" not in t:
                out.append("{0}: the up arrow is not green".format(name))
        # dock order: right-docked items appear right to left in source order
        order = [n for n in ("CloseBtn", "FullBtn", "ShrinkBtn", "VersionTxt") if 'x:Name="{0}"'.format(n) in src]
        pos = [src.index('x:Name="{0}"'.format(n)) for n in order]
        if pos != sorted(pos):
            out.append("{0}: shrink is not left of full screen and close".format(name))
    ui_code = code_only(files["lvm_ui.py"])
    win_code = code_only(files["lvm_window.py"])
    if not re.search(r'shrink_btn=window\.FindName\("ShrinkBtn"\)', ui_code):
        out.append("lvm_ui.py: dialog_chrome does not wire ShrinkBtn")
    if not re.search(r"button\.Click\s*\+=\s*self\.on_click", ui_code):
        out.append("lvm_ui.py: the shrink button is drawn but never wired")
    if re.search(r"BeginAnimation\(", ui_code) and not re.search(r"BeginAnimation\([^,()]+,\s*None\)", ui_code):
        out.append("lvm_ui.py: an animation is never released - it holds its end value over every later move")
    if not re.search(r'FindName\("ShrinkBtn"\)\)', win_code):
        out.append("lvm_window.py: the main window's Chrome is built without its shrink button")
    tree = ast.parse(files["lvm_window.py"])
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            body = ast.get_source_segment(files["lvm_window.py"], node) or ""
            for x in re.findall(r'load_xaml\("([A-Za-z]+\.xaml)"\)', body):
                if x in WINDOWS and "dialog_chrome(" not in body and "ShrinkBtn" not in body:
                    out.append("lvm_window.py: {0} opens {1} without a drawer".format(node.name, x))
    for row in ("progress_row", "chips_row"):
        if re.search(r"self\.{0}\.Visibility\s*=".format(row), win_code):
            out.append("lvm_window.py: {0} shown directly - it would appear inside a parked bar".format(row))
    return out


def rule_init_reads(files):
    """Nothing reachable from LevelManagerWindow.__init__ reads an attribute
    before something has set it, walking the call graph in source order."""
    tree = ast.parse(files["lvm_window.py"])
    cls = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "LevelManagerWindow"]
    if not cls:
        return ["LevelManagerWindow not found"]
    cls = cls[0]
    methods = dict((f.name, f) for f in cls.body if isinstance(f, ast.FunctionDef))
    class_attrs = set()
    for n in cls.body:
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    class_attrs.add(t.id)
    written = set()
    problems = []
    stack = []

    def is_self(node):
        return isinstance(node, ast.Name) and node.id == "self"

    def visit(node):
        if isinstance(node, (ast.FunctionDef, ast.Lambda, ast.ClassDef)):
            return
        if isinstance(node, ast.Assign):
            visit(node.value)
            for t in node.targets:
                visit(t)
            return
        if isinstance(node, ast.AugAssign):
            if isinstance(node.target, ast.Attribute) and is_self(node.target.value):
                read(node.target.attr, node)
            else:
                visit(node.target)
            visit(node.value)
            return
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and is_self(node.func.value) and node.func.attr in methods:
            for a in node.args:
                visit(a)
            for k in node.keywords:
                visit(k.value)
            walk(node.func.attr)
            return
        if isinstance(node, ast.Attribute) and is_self(node.value):
            if isinstance(node.ctx, ast.Store):
                written.add(node.attr)
            else:
                read(node.attr, node)
            return
        for child in ast.iter_child_nodes(node):
            visit(child)

    def read(attr, node):
        if attr in written or attr in methods or attr in class_attrs:
            return
        problems.append("LevelManagerWindow: self.{0} read at line {1} before it is set (via {2})".format(
            attr, node.lineno, " > ".join(stack)))

    def walk(name):
        if name in stack:
            return
        stack.append(name)
        for stmt in methods[name].body:
            visit(stmt)
        stack.pop()

    walk("__init__")
    return problems


def rule_modules_load(files):
    """Every module imports against the stub API (names in their real
    namespaces), from a scratch copy of the files given."""
    import shutil
    import tempfile
    sys.path.insert(0, HERE)
    import bench_stubs
    tmp = tempfile.mkdtemp()
    out = []
    try:
        for name in TOOL_MODULES:
            with io.open(os.path.join(tmp, name), "w", encoding="utf-8") as handle:
                handle.write(files[name])
        bench_stubs.install()
        sys.path.insert(0, tmp)
        for mod in ("lvm_clr", "lvm_core", "lvm_revit", "lvm_ops", "lvm_ui", "lvm_window"):
            sys.modules.pop(mod, None)
        for mod in ("lvm_clr", "lvm_core", "lvm_revit", "lvm_ops", "lvm_ui", "lvm_window"):
            try:
                __import__(mod)
            except Exception as ex:
                out.append("{0} does not load: {1}: {2}".format(mod, type(ex).__name__, ex))
    finally:
        sys.path.remove(tmp)
        for mod in ("lvm_clr", "lvm_core", "lvm_revit", "lvm_ops", "lvm_ui", "lvm_window"):
            sys.modules.pop(mod, None)
        shutil.rmtree(tmp, ignore_errors=True)
    return out


RULES = [
    rule_xaml_parses, rule_xaml_enums, rule_no_static_resource, rule_resource_keys,
    rule_keyed_style_targets, rule_palettes_match, rule_findname, rule_banned_syntax,
    rule_non_ascii, rule_clr_first, rule_assemblies_referenced, rule_no_revitapi_reference,
    rule_no_duplicate_defs, rule_changelog, rule_thin_loader, rule_raise_read,
    rule_core_pure, rule_enums_late, rule_no_dispatcher_in_logic, rule_chrome,
    rule_icons_parse, rule_shared_files, rule_settings_keys, rule_handlers_exist,
    rule_icon_label, rule_egg_logo_only, rule_drawer_everywhere, rule_init_reads, rule_modules_load,
]


# =========================================================================
# Self test - one deliberate breakage per rule
# =========================================================================

def _sub(files, name, old, new, count=1):
    out = dict(files)
    if old not in out[name]:
        raise AssertionError("selftest anchor missing in {0}: {1!r}".format(name, old[:60]))
    out[name] = out[name].replace(old, new, count)
    return out


SELFTEST = [
    (rule_xaml_parses, lambda f: _sub(f, "Prompt.xaml", "<!-- ====", "<!-- -- ====")),
    (rule_xaml_enums, lambda f: _sub(f, "LevelManager.xaml", 'VerticalAlignment="Bottom"', 'VerticalAlignment="Baseline"')),
    (rule_no_static_resource, lambda f: _sub(f, "Results.xaml", "{DynamicResource Bg}", "{StaticResource Bg}")),
    (rule_resource_keys, lambda f: _sub(f, "AssignLevel.xaml", "{DynamicResource Muted}", "{DynamicResource Mutted}")),
    (rule_resource_keys, lambda f: _sub(f, "lvm_window.py", '"Muted")', '"Mutted")')),
    (rule_keyed_style_targets, lambda f: _sub(f, "LevelManager.xaml",
                                              '<Button x:Name="CloseBtn" DockPanel.Dock="Right" Style="{DynamicResource CloseButton}"',
                                              '<Button x:Name="CloseBtn" DockPanel.Dock="Right" Style="{DynamicResource TreeTick}"')),
    (rule_keyed_style_targets, lambda f: _sub(f, "lvm_window.py", '"LvmRow")', '"CellText")')),
    (rule_palettes_match, lambda f: _sub(f, "lvm_core.py", '"Violet": "#6A4FC2",', '')),
    (rule_palettes_match, lambda f: _sub(f, "Theme.xaml", '<SolidColorBrush x:Key="Violet" Color="#9B7FE0"/>', '')),
    (rule_findname, lambda f: _sub(f, "lvm_window.py", 'f("ExpandBtn").Click', 'f("ExpandAllBtn").Click')),
    (rule_banned_syntax, lambda f: _sub(f, "lvm_core.py", 'return u"{0} of {1}".format(shown, total)',
                                        'return f"{shown} of {total}"')),
    (rule_banned_syntax, lambda f: _sub(f, "lvm_revit.py", 'lid = eid_value(element.LevelId)',
                                        'lid = element.LevelId.IntegerValue')),
    (rule_banned_syntax, lambda f: _sub(f, "lvm_ui.py", "from System.IO import File, MemoryStream",
                                        "from System.IO import File, MemoryStream\nfrom System import Uri")),
    (rule_non_ascii, lambda f: _sub(f, "lvm_window.py", 'DOT = u"  \\u00B7  "', 'DOT = "  \u00b7  "')),
    (rule_clr_first, lambda f: _sub(f, "lvm_ops.py", "import lvm_clr  # noqa: F401\n",
                                    "from System import Action as _A\nimport lvm_clr  # noqa: F401\n")),
    (rule_assemblies_referenced, lambda f: _sub(f, "lvm_clr.py", '"System.Data", ', '')),
    (rule_assemblies_referenced, lambda f: _sub(f, "lvm_ui.py", "from System.IO import File, MemoryStream",
                                                "from System.IO import File, MemoryStream\nfrom System.Net import WebClient")),
    (rule_no_revitapi_reference, lambda f: _sub(f, "lvm_clr.py", '"WindowsBase",', '"WindowsBase", "RevitAPI",')),
    (rule_no_duplicate_defs, lambda f: _sub(f, "lvm_core.py", "def words(text):",
                                            "def words(text):\n    return []\n\n\ndef words(text):")),
    (rule_changelog, lambda f: _sub(f, "lvm_core.py", '__version__ = "', '__version__ = "9.')),
    (rule_thin_loader, lambda f: _sub(f, "script.py", "__persistentengine__ = True", "__persistentengine__ = False")),
    (rule_thin_loader, lambda f: _sub(f, "script.py", "import traceback\n", "import traceback\nimport lvm_window\n")),
    (rule_raise_read, lambda f: _sub(f, "lvm_ops.py", "status = to_text(self.event.Raise())",
                                     "self.event.Raise()")),
    (rule_core_pure, lambda f: _sub(f, "lvm_core.py", "import os\n", "import os\nfrom System import Action\n")),
    (rule_enums_late, lambda f: _sub(f, "lvm_revit.py", 'p = lv.get_Parameter(bip("LEVEL_ELEV"))',
                                     'p = lv.get_Parameter(BuiltInParameter.LEVEL_ELEV)')),
    (rule_no_dispatcher_in_logic, lambda f: _sub(f, "lvm_core.py", "        count += len(chunk)\n",
                                                 "        count += len(chunk)\n        api.Dispatcher = None\n")),
    (rule_chrome, lambda f: _sub(f, "AddParameter.xaml", 'WindowStyle="None"', 'WindowStyle="SingleBorderWindow"')),
    (rule_chrome, lambda f: _sub(f, "LevelManager.xaml", 'x:Name="ThemeBtn"', 'x:Name="ThemeButton"')),
    (rule_icons_parse, lambda f: _sub(f, "lvm_core.py", '"plus": "M8,2.5', '"plus": "X8,2.5')),
    (rule_settings_keys, lambda f: _sub(f, "lvm_window.py", 'self.settings["theme"] = self.theme_mode',
                                        'self.settings["theme_mode"] = self.theme_mode')),
    (rule_handlers_exist, lambda f: _sub(f, "lvm_window.py", "self.assign_btn.Click += self.on_assign",
                                         "self.assign_btn.Click += self.on_assign_level")),
    (rule_icon_label, lambda f: _sub(f, "lvm_window.py", "ui.set_label(self.theme_btn, core.theme_label(self.theme_mode))",
                                     "self.theme_btn.Content = core.theme_label(self.theme_mode)")),
    (rule_egg_logo_only, lambda f: _sub(f, "lvm_ui.py", "    counter = core.LogoClicks()\n",
                                        "    counter = core.LogoClicks()\n    egg_hook_attach = None\n    window.attach(window)\n")),
    (rule_egg_logo_only, lambda f: _sub(f, "lvm_ui.py", "                counter.reset()", "                pass")),
    (rule_drawer_everywhere, lambda f: _sub(f, "Results.xaml", 'x:Name="ShrinkBtn"', 'x:Name="ShrinkButton"')),
    (rule_drawer_everywhere, lambda f: _sub(f, "AssignLevel.xaml", 'Stroke="{DynamicResource Green}" StrokeThickness="2" Visibility="Collapsed"',
                                            'Stroke="{DynamicResource Green}" StrokeThickness="2"')),
    (rule_drawer_everywhere, lambda f: _sub(f, "lvm_ui.py", '                  shrink_btn=window.FindName("ShrinkBtn"))', '                  )')),
    (rule_drawer_everywhere, lambda f: _sub(f, "lvm_ui.py", "button.Click += self.on_click", "pass")),
    (rule_drawer_everywhere, lambda f: _sub(f, "lvm_window.py", '                                self.win.FindName("ShrinkBtn"))', '                                None)')),
    (rule_drawer_everywhere, lambda f: _sub(f, "lvm_window.py", "self.set_vis(self.progress_row, Visibility.Visible)",
                                            "self.progress_row.Visibility = Visibility.Visible")),
    (rule_drawer_everywhere, lambda f: _sub(f, "lvm_window.py", '        ui.dialog_chrome(self.win, owner.palette())\n        ui.open_parent(owner.win)\n        self.win.Owner = owner.win\n        f = self.win.FindName\n        f("TitleTxt")',
                                            '        ui.themed(self.win, owner.palette())\n        ui.open_parent(owner.win)\n        self.win.Owner = owner.win\n        f = self.win.FindName\n        f("TitleTxt")')),
    (rule_drawer_everywhere, lambda f: _sub(f, "lvm_ui.py", "    def _pin(self, height):",
                                            "    def _bad(self):\n        self.window.BeginAnimation(1, 2)\n\n    def _pin(self, height):")),
    (rule_init_reads, lambda f: _sub(f, "lvm_window.py", "        self.busy = False\n        self.closed = False\n",
                                     "        self.closed = False\n")),
    (rule_modules_load, lambda f: _sub(f, "lvm_window.py", "from System.Windows.Media import VisualTreeHelper",
                                       "from System.Windows.Controls import VisualTreeHelper")),
    (rule_modules_load, lambda f: _sub(f, "lvm_ui.py", "    Thickness, HorizontalAlignment, VerticalAlignment, PresentationSource,",
                                       "    Thickness, HorizontalAlignment, VerticalAlignment, PresentationSource, Border,")),
]


def run(files):
    failed = 0
    for rule in RULES:
        problems = rule(files)
        if problems:
            failed += 1
            print("FAIL {0}".format(rule.__name__))
            for p in problems:
                print("     " + p)
        else:
            print("ok   {0}".format(rule.__name__))
    return failed


def selftest(files):
    covered = set()
    bad = 0
    for rule, breaker in SELFTEST:
        covered.add(rule)
        try:
            broken = breaker(files)
        except AssertionError as ex:
            print("SELFTEST ANCHOR {0}: {1}".format(rule.__name__, ex))
            bad += 1
            continue
        if rule(broken):
            print("ok   {0} catches its breakage".format(rule.__name__))
        else:
            print("FAIL {0} did NOT catch its breakage".format(rule.__name__))
            bad += 1
    for rule in RULES:
        if rule not in covered and rule is not rule_shared_files:
            print("FAIL {0} has no selftest".format(rule.__name__))
            bad += 1
    # shared files: build a fake extension with a startup.py beside the tool
    import tempfile
    import shutil
    tmp = tempfile.mkdtemp()
    try:
        tool = os.path.join(tmp, "X.extension", "X.tab", "P.panel", "T.pushbutton")
        os.makedirs(tool)
        with open(os.path.join(tmp, "X.extension", "startup.py"), "w") as handle:
            handle.write("# shared\n")
        if rule_shared_files(files, tool):
            print("ok   rule_shared_files catches its breakage")
        else:
            print("FAIL rule_shared_files did NOT catch its breakage")
            bad += 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return bad


if __name__ == "__main__":
    FILES = load_files()
    if "--selftest" in sys.argv:
        n = selftest(FILES)
        print("\nselftest: {0}".format("all rules fire" if n == 0 else "{0} problem(s)".format(n)))
    else:
        n = run(FILES)
        print("\nimport_check: {0}".format("all rules pass" if n == 0 else "{0} rule(s) failing".format(n)))
    sys.exit(1 if n else 0)
