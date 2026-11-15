# -*- coding: utf-8 -*-
"""Number Sequencer - static bench rules. Run with plain CPython 3:

    python import_check.py            check the tool
    python import_check.py --selftest break each rule on purpose and prove it fires

Every rule works on a dict of {file name: text}, so the selftest can break a
copy in memory and nothing on disk is touched.
"""

import ast
import os
import re
import shutil
import sys
import tempfile
import xml.dom.minidom

HERE = os.path.dirname(os.path.abspath(__file__))
MODULES = ["nsq_clr.py", "nsq_core.py", "nsq_revit.py", "nsq_ui.py", "nsq_tree.py",
           "nsq_selector.py", "nsq_views.py", "nsq_window.py"]
LAYOUTS = ["NumberSequencer.xaml", "NumberSequencerResults.xaml", "NumberSequencerPrompt.xaml",
           "NumberSequencerTags.xaml"]
THEME = "Theme.xaml"
BENCH_FILES = ("bench_stubs.py", "import_check.py", "bench_logic.py")

# namespace -> assemblies that provide it (any one referenced is enough)
ASSEMBLY_FOR = {
    "System": ["System", "mscorlib"],
    "System.Collections.Generic": ["mscorlib", "System"],
    "System.IO": ["mscorlib"],
    "System.Windows": ["PresentationFramework", "PresentationCore", "WindowsBase"],
    "System.Windows.Markup": ["PresentationFramework", "System.Xaml"],
    "System.Windows.Media": ["PresentationCore"],
    "System.Windows.Media.Imaging": ["PresentationCore"],
    "System.Windows.Media.Animation": ["PresentationCore"],
    "System.Windows.Interop": ["PresentationFramework"],
    "System.Windows.Input": ["PresentationCore"],
    "System.Windows.Forms": ["System.Windows.Forms"],
    "System.Windows.Data": ["PresentationFramework"],
    "System.Windows.Controls.Primitives": ["PresentationFramework"],
    "System.Windows.Controls": ["PresentationFramework"],
    "System.Windows.Shapes": ["PresentationFramework"],
    "System.Windows.Threading": ["WindowsBase"],
}
PRELOADED_PREFIX = "Autodesk."   # pyRevit loads RevitAPI / RevitAPIUI itself

LAUNCH_ORDER = ["__init__", "read_now"]

ENUMS = ["BuiltInCategory", "BuiltInParameter", "ConnectorType", "Domain", "StorageType",
         "FailureSeverity", "FailureProcessingResult", "TagOrientation", "ObjectType",
         "ConnectorProfileType", "ViewType", "TemporaryViewMode", "MouseButtonState",
         "DragDropEffects", "GridUnitType", "ModifierKeys", "PenLineCap", "PenLineJoin",
         "RelativeSourceMode", "Orientation", "PlacementMode", "ScrollBarVisibility", "EasingMode", "WindowStyle", "Stretch", "DispatcherPriority"]


def load_files(folder=HERE):
    files = {}
    for name in os.listdir(folder):
        if name.endswith((".py", ".xaml", ".md", ".yaml")):
            with open(os.path.join(folder, name), "rb") as fh:
                files[name] = fh.read().decode("utf-8")
    return files


def tool_py(files):
    return [n for n in files if n.endswith(".py") and n not in BENCH_FILES]


def code_only(text):
    """Source with comments and docstrings/strings blanked - rules about code
    must never pass by matching prose."""
    out = []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return text
    lines = text.splitlines()
    blank = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(getattr(node, "value", None), ast.Constant) \
                and isinstance(node.value.value, str):
            for ln in range(node.lineno, getattr(node, "end_lineno", node.lineno) + 1):
                blank.add(ln)
    for i, line in enumerate(lines, 1):
        if i in blank:
            out.append("")
            continue
        out.append(re.sub(r"#.*$", "", line) if "#" in line and not re.search(r"[\"'][^\"']*#", line) else line)
    return "\n".join(out)


def imports_of(text):
    """[(lineno, namespace)] for every 'from X import' / 'import X' of System/Autodesk."""
    out = []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return out
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] in ("System", "Autodesk"):
                out.append((node.lineno, node.module))
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] in ("System", "Autodesk"):
                    out.append((node.lineno, a.name))
    return out


# ============================================================
# Rules
# ============================================================

def rule_xaml_parses(files):
    bad = []
    for n in LAYOUTS + [THEME]:
        try:
            xml.dom.minidom.parseString(files[n].encode("utf-8"))
        except Exception as ex:
            bad.append("{0} does not parse: {1}".format(n, ex))
    return bad


def rule_clr_first(files):
    bad = []
    for n in MODULES:
        if n in ("nsq_clr.py", "nsq_core.py"):
            continue
        text = files[n]
        imps = imports_of(text)
        if not imps:
            continue
        first = min([ln for ln, ns in imps])
        m = re.search(r"^import nsq_clr\b", text, re.M)
        if not m:
            bad.append("{0} reaches .NET without importing nsq_clr".format(n))
            continue
        clr_line = text[:m.start()].count("\n") + 1
        if clr_line > first:
            bad.append("{0} imports nsq_clr on line {1}, after .NET on line {2}".format(n, clr_line, first))
    return bad


def rule_core_pure(files):
    text = code_only(files["nsq_core.py"])
    if re.search(r"^\s*(import|from)\s+(System|Autodesk|clr)\b", text, re.M):
        return ["nsq_core.py must not touch .NET (bench runs it on CPython)"]
    return []


def _clr_list(files):
    m = re.search(r"_ASSEMBLIES\s*=\s*\[(.*?)\]", files["nsq_clr.py"], re.S)
    if not m:
        return []
    return re.findall(r"'([^']+)'", m.group(1)) + re.findall(r'"([^"]+)"', m.group(1))


def rule_assemblies_referenced(files):
    have = set(_clr_list(files))
    bad = []
    for n in tool_py(files):
        for ln, ns in imports_of(files[n]):
            if ns.startswith(PRELOADED_PREFIX):
                continue
            need = ASSEMBLY_FOR.get(ns)
            if need is None:
                bad.append("{0}:{1} imports {2} - add it to ASSEMBLY_FOR".format(n, ln, ns))
            elif not have.intersection(need):
                bad.append("{0}:{1} imports {2} but none of {3} is referenced in nsq_clr".format(n, ln, ns, need))
    return bad


def rule_no_static_resource(files):
    return ["{0} uses StaticResource (Theme.xaml merges after the layout parses)".format(n)
            for n in LAYOUTS if "StaticResource" in files[n]]


def _theme_keys(files):
    return set(re.findall(r'x:Key="([^"]+)"', files[THEME]))


def rule_dynamic_keys_defined(files):
    keys = _theme_keys(files)
    bad = []
    for n in LAYOUTS + [THEME]:
        for k in re.findall(r"\{DynamicResource ([^}]+)\}", files[n]):
            if k.strip() not in keys:
                bad.append("{0} uses DynamicResource {1}, not defined in Theme.xaml".format(n, k))
    for n in tool_py(files):
        for k in re.findall(r"SetResourceReference\([^,]+,\s*u?[\"']([^\"']+)[\"']", files[n]):
            if k not in keys:
                bad.append("{0} SetResourceReference key {1} not in Theme.xaml".format(n, k))
    return bad


def rule_style_targettype(files):
    targets = dict(re.findall(r'<Style x:Key="([^"]+)" TargetType="([^"]+)"', files[THEME]))
    bad = []
    for n in LAYOUTS:
        for tag, key in re.findall(r'<(\w+)[^>]*?Style="\{DynamicResource ([^}]+)\}"', files[n]):
            t = targets.get(key)
            if t is not None and t != tag:
                bad.append("{0}: <{1}> given style {2} whose TargetType is {3}".format(n, tag, key, t))
    return bad


def rule_names_exist(files):
    names = set()
    for n in LAYOUTS:
        names.update(re.findall(r'x:Name="([^"]+)"', files[n]))
    bad = []
    for n in tool_py(files):
        code = files[n]
        for k in re.findall(r"(?:\bctl|\bf|FindName)\(u?[\"']([A-Za-z_]\w*)[\"']\)", code):
            if k not in names:
                bad.append("{0} looks up {1}, which no XAML names".format(n, k))
        for k in re.findall(r"self\.ctl\(\{[^}]*\}", code):
            for kk in re.findall(r"u?[\"']([A-Za-z_]\w*)[\"']", k):
                if kk not in names:
                    bad.append("{0} looks up {1}, which no XAML names".format(n, kk))
    m = re.search(r"GRIPS\s*=\s*\{(.*?)\}", files["nsq_ui.py"], re.S)
    if m:
        for k in re.findall(r"u?\"(Grip\w+)\"", m.group(1)):
            if k not in names:
                bad.append("nsq_ui.py grip {0} missing from the layout".format(k))
    return bad


def rule_no_fstrings(files):
    bad = []
    for n in tool_py(files):
        try:
            tree = ast.parse(files[n])
        except SyntaxError as ex:
            bad.append("{0} does not parse: {1}".format(n, ex))
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr):
                bad.append("{0}:{1} f-string (IronPython 2.7)".format(n, node.lineno))
    return bad


def rule_no_print(files):
    bad = []
    for n in tool_py(files):
        if re.search(r"^\s*print\b", code_only(files[n]), re.M):
            bad.append("{0} uses print".format(n))
    return bad


def rule_integervalue_guarded(files):
    bad = []
    for n in tool_py(files):
        try:
            tree = ast.parse(files[n])
        except SyntaxError:
            continue
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef):
                continue
            if fn.name == "eid_value":
                continue
            for node in ast.walk(fn):
                if isinstance(node, ast.Attribute) and node.attr == "IntegerValue":
                    bad.append("{0}:{1} .IntegerValue outside eid_value (gone in Revit 2026)".format(n, node.lineno))
        for node in tree.body:
            for sub in ast.walk(node):
                if not isinstance(node, (ast.FunctionDef, ast.ClassDef)) and \
                        isinstance(sub, ast.Attribute) and sub.attr == "IntegerValue":
                    bad.append("{0}:{1} .IntegerValue at module level".format(n, sub.lineno))
    return bad


def rule_no_uri(files):
    bad = []
    for n in tool_py(files):
        code = code_only(files[n])
        if re.search(r"\bUri\b", code) or "UriSource" in code:
            bad.append("{0} uses System.Uri (moved in Revit 2025)".format(n))
    return bad


def rule_ascii(files):
    bad = []
    for n in tool_py(files):
        for i, ch in enumerate(files[n]):
            if ord(ch) > 127:
                bad.append("{0} has non-ASCII at char {1}".format(n, i))
                break
    return bad


def _palette(files, name):
    m = re.search(name + r"\s*=\s*\{(.*?)\}", files["nsq_core.py"], re.S)
    if not m:
        return {}
    return dict(re.findall(r"u?\"(\w+)\":\s*u?\"(#[0-9A-Fa-f]{6})\"", m.group(1)))


def rule_palettes_match_theme(files):
    dark = _palette(files, "DARK")
    light = _palette(files, "LIGHT")
    brushes = dict(re.findall(r'<SolidColorBrush x:Key="(\w+)" Color="(#[0-9A-Fa-f]{6})"', files[THEME]))
    bad = []
    if set(dark) != set(light):
        bad.append("DARK and LIGHT palettes have different keys: {0}".format(sorted(set(dark) ^ set(light))))
    if set(dark) != set(brushes):
        bad.append("palette keys and Theme.xaml brushes differ: {0}".format(sorted(set(dark) ^ set(brushes))))
    for k, v in brushes.items():
        if k in dark and dark[k].upper() != v.upper():
            bad.append("Theme.xaml default {0}={1} differs from DARK {2}".format(k, v, dark[k]))
    return bad


def rule_script_thin(files):
    s = files["script.py"]
    bad = []
    if not re.search(r"^__persistentengine__\s*=\s*True", s, re.M):
        bad.append("script.py needs __persistentengine__ = True (modeless window)")
    if "AddReference" in code_only(s):
        bad.append("script.py must not call clr.AddReference")
    if len(s.splitlines()) > 80:
        bad.append("script.py should stay a thin loader")
    return bad


def rule_no_duplicate_defs(files):
    bad = []
    for n in tool_py(files):
        try:
            tree = ast.parse(files[n])
        except SyntaxError:
            continue
        scopes = [("module", tree.body)] + [(c.name, c.body) for c in ast.walk(tree)
                                            if isinstance(c, ast.ClassDef)]
        for scope, body in scopes:
            seen = set()
            for node in body:
                if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                    if node.name in seen:
                        bad.append("{0}: {1}.{2} defined twice - the last silently wins".format(n, scope, node.name))
                    seen.add(node.name)
    return bad


def rule_changelog_version(files):
    m = re.search(r'__version__\s*=\s*u?"([^"]+)"', files["nsq_core.py"])
    if not m:
        return ["nsq_core.py has no __version__"]
    if "## " + m.group(1) not in files.get("CHANGELOG.md", ""):
        return ["CHANGELOG.md has no entry for {0}".format(m.group(1))]
    return []


def rule_version_displayed(files):
    bad = []
    if "core.__version__" not in code_only(files["nsq_window.py"]):
        bad.append("window does not read the version from nsq_core")
    for n in LAYOUTS:
        if not re.search(r'x:Name="[RPT]?Version(Text)?"', files[n]):
            bad.append("{0} has no version text top right".format(n))
    return bad


def rule_egg_wired(files):
    bad = []
    if "egg_hook" not in code_only(files["nsq_ui.py"]):
        bad.append("nsq_ui.py does not reach revobim.egg.egg_hook")
    if "ui.wire_egg(" not in code_only(files["nsq_window.py"]):
        bad.append("nsq_window.py never wires the egg")
    return bad


def rule_enums_late(files):
    bad = []
    for n in tool_py(files):
        try:
            tree = ast.parse(files[n])
        except SyntaxError:
            continue
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                continue
            for sub in ast.walk(node):
                if isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name) \
                        and sub.value.id in ENUMS:
                    bad.append("{0}:{1} {2}.{3} read at module load".format(n, sub.lineno, sub.value.id, sub.attr))
    return bad


def rule_raise_status_read(files):
    bad = []
    for n in tool_py(files):
        try:
            tree = ast.parse(files[n])
        except SyntaxError:
            continue
        assigned = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and \
                    isinstance(node.value.func, ast.Attribute) and node.value.func.attr == "Raise":
                assigned.add(id(node.value))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and node.func.attr == "Raise" and id(node) not in assigned:
                bad.append("{0}:{1} ExternalEvent.Raise() status not read".format(n, node.lineno))
    return bad


def rule_handlers_exist(files):
    bad = []
    for n in tool_py(files):
        text = files[n]
        defs = set(re.findall(r"def (\w+)\(", text))
        for h in set(re.findall(r"self\.(_(?:on|job)_\w+)", text)):
            if h not in defs:
                bad.append("{0} wires self.{1}, which is not defined".format(n, h))
    return bad


def rule_window_chrome(files):
    bad = []
    for n in LAYOUTS:
        t = files[n]
        if 'AllowsTransparency="True"' in t and 'WindowStyle="None"' not in t:
            bad.append("{0}: AllowsTransparency needs WindowStyle=None".format(n))
        if "Baseline" in t:
            bad.append("{0}: Baseline alignment kills XamlReader.Load".format(n))
    return bad


def rule_theme_chip(files):
    t = files["NumberSequencer.xaml"]
    w = code_only(files["nsq_window.py"])
    bad = []
    if 'x:Name="ThemeBtn"' not in t:
        bad.append("no theme chip top right")
    if "canvas_is_dark" not in code_only(files["nsq_ui.py"]) or "core.resolve_theme(" not in w:
        bad.append("theme does not follow the Revit canvas")
    if not re.search(r"\.Activated\s*\+=.*_on_activated", w):
        bad.append("Auto theme is not re-checked when the window is activated")
    return bad


def rule_readback_after_group(files):
    t = code_only(files["nsq_revit.py"])
    m = re.search(r"def apply_job\(.*?(?=\ndef )", t, re.S)
    if not m:
        return ["nsq_revit.apply_job missing"]
    body = m.group(0)
    a = body.find("tg.Assimilate()")
    r = body.find("read_param_value(")
    if a < 0 or r < 0 or r < a:
        return ["values must be read back after the TransactionGroup has closed"]
    return []


def rule_checkout_before_write(files):
    t = code_only(files["nsq_revit.py"])
    m = re.search(r"def apply_job\(.*?(?=\ndef )", t, re.S)
    body = m.group(0) if m else ""
    c = body.find("checkout(")
    w = body.find("_write_one(")
    if c < 0 or w < 0 or c > w:
        return ["workshared elements must be borrowed before any write"]
    return []


def rule_init_order(files):
    """Replay what launch() runs - SequencerWindow.__init__ then read_now - in
    source order, following self.method() calls, and report any self
    attribute read before something set it."""
    tree = ast.parse(files["nsq_window.py"])
    cls = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "SequencerWindow":
            cls = node
    if cls is None:
        return ["SequencerWindow not found"]
    methods = dict((f.name, f) for f in cls.body if isinstance(f, ast.FunctionDef))
    have = set()
    bad = []

    def events(node):
        """(order, kind, name) in evaluation order, skipping nested defs/lambdas."""
        out = []

        def visit(n):
            if isinstance(n, (ast.FunctionDef, ast.Lambda, ast.ClassDef)):
                return
            if isinstance(n, ast.Assign):
                visit(n.value)
                for t in n.targets:
                    visit(t)
                return
            if isinstance(n, ast.AugAssign):
                visit(n.value)
                visit(n.target)
                return
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and \
                    isinstance(n.func.value, ast.Name) and n.func.value.id == "self" and \
                    n.func.attr in methods:
                for a in n.args:
                    visit(a)
                for k in n.keywords:
                    visit(k.value)
                out.append(("call", n.func.attr))
                return
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "self":
                out.append(("store" if isinstance(n.ctx, ast.Store) else "load", n.attr))
                return
            for child in ast.iter_child_nodes(n):
                visit(child)

        visit(node)
        return out

    def replay(name, stack):
        for stmt in methods[name].body:
            for kind, attr in events(stmt):
                if kind == "store":
                    have.add(attr)
                elif kind == "call":
                    if attr not in stack:
                        replay(attr, stack + [attr])
                elif kind == "load":
                    if attr not in have and attr not in methods:
                        bad.append("self.{0} read in {1} before __init__ sets it".format(attr, name))
                        have.add(attr)

    for entry in LAUNCH_ORDER:
        replay(entry, [entry])
    return bad


def rule_modules_load_on_stub(files):
    import bench_stubs
    tmp = tempfile.mkdtemp()
    bad = []
    saved_path = list(sys.path)
    try:
        for n in tool_py(files):
            with open(os.path.join(tmp, n), "wb") as fh:
                fh.write(files[n].encode("utf-8"))
        bench_stubs.uninstall()
        bench_stubs.install()
        sys.path.insert(0, tmp)
        for n in MODULES:
            mod = n[:-3]
            for m in MODULES:
                sys.modules.pop(m[:-3], None)
            try:
                __import__(mod)
            except Exception as ex:
                bad.append("{0} does not load on the stub API: {1}: {2}".format(n, type(ex).__name__, ex))
    finally:
        sys.path[:] = saved_path
        for m in MODULES:
            sys.modules.pop(m[:-3], None)
        bench_stubs.uninstall()
        shutil.rmtree(tmp, ignore_errors=True)
    return bad


def rule_typing_never_chooses(files):
    """Typing in the parameter box filters the list; it must never pick."""
    t = code_only(files["nsq_window.py"])
    m = re.search(r"def _on_param_typed\(.*?(?=\n    def )", t, re.S)
    if not m:
        return ["_on_param_typed missing"]
    if "_choose_param(" in m.group(0) or "param_name =" in m.group(0):
        return ["typing in the parameter box changes the chosen parameter"]
    if "_show_param_list(" not in m.group(0):
        return ["typing in the parameter box does not narrow the list"]
    return []


def rule_pick_systems_loops(files):
    """Pick systems keeps picking until Escape, one system per click."""
    t = code_only(files["nsq_window.py"])
    m = re.search(r"def _job_pick_systems\(.*?(?=\n    def )", t, re.S)
    body = m.group(0) if m else ""
    if "while True" not in body or "pick_duct_element(" not in body or "break" not in body:
        return ["Pick systems must loop on picks until Escape"]
    return []


def _fn_body(text, name, indent=u""):
    m = re.search(r"\n" + indent + r"def " + name + r"\(.*?(?=\n" + indent + r"def |\Z)", text, re.S)
    return m.group(0) if m else u""


def rule_isolate_reset_first(files):
    """Reset the old isolate in its own committed transaction, then isolate -
    in one transaction a leftover isolate showed through."""
    b = _fn_body(code_only(files["nsq_revit.py"]), "isolate_systems")
    d = b.find("DisableTemporaryViewMode(")
    c = b.find(".Commit()", d if d >= 0 else 0)
    i = b.find("IsolateElementsTemporary(")
    if d < 0 or i < 0 or c < 0 or not (d < c < i):
        return ["isolate must reset, commit, then isolate"]
    if "tags_on(" not in b:
        return ["isolate must take the tags on the systems with it"]
    if b.find("tags_on(") < c:
        return ["tags must be gathered after the old isolate is reset (a view collector skips hidden tags)"]
    return []


def rule_overrides_snapshot_first(files):
    b = _fn_body(code_only(files["nsq_revit.py"]), "colour_systems")
    g = b.find("GetElementOverrides(")
    st = b.find("SetElementOverrides(")
    if g < 0 or st < 0 or g > st:
        return ["each element's own overrides must be recorded before it is coloured"]
    c = b.find(".Commit()")
    u = b.find("snapshot.update(")
    if u < 0 or c < 0 or u < c or "snapshot.clear()" in b:
        return ["the record of the view's own overrides may only grow after a committed colouring"]
    if "SetElementOverrides(" not in _fn_body(code_only(files["nsq_revit.py"]), "restore_overrides"):
        return ["restore_overrides must put the recorded overrides back"]
    return []


def rule_colours_turned_off(files):
    sel = code_only(files["nsq_selector.py"])
    win = code_only(files["nsq_window.py"])
    bad = []
    if not re.search(r"u\"after\":\s*self\.after_run", sel) or \
            "_restore_all(" not in _fn_body(sel, "after_run", "    "):
        bad.append("Run must turn the view colours off when it finishes")
    if "after(uiapp)" not in _fn_body(win, "_on_apply", "    "):
        bad.append("the run job never calls the tab's after-run step")
    if "self.sel.on_closed()" not in _fn_body(win, "_on_closed", "    "):
        bad.append("closing the window must put the view colours back")
    return bad


def rule_selector_plans_only(files):
    sel = code_only(files["nsq_selector.py"])
    rv_ = code_only(files["nsq_revit.py"])
    bad = []
    if not re.search(r"u\"plans_only\":\s*True", sel):
        bad.append("the System Selector must tag in plan views only")
    if "plans_only" not in _fn_body(rv_, "_tag"):
        bad.append("the tag step ignores plans_only")
    return bad


def rule_tick_by_value(files):
    """A boxed .NET bool is not always the Python False object - read ticks by value."""
    bad = []
    for n in tool_py(files):
        if re.search(r"IsChecked\s+is\s+(not\s+)?(True|False)", code_only(files[n])):
            bad.append("{0} compares IsChecked by identity".format(n))
    return bad


def rule_selector_skips_accessories(files):
    b = _fn_body(code_only(files["nsq_selector.py"]), "include", "    ")
    if "core.sel_include(" not in b or "passthrough" not in b:
        return ["the System Selector must never number accessories, equipment or terminals"]
    return []


def _icon_keys(files):
    m = re.search(r"ICONS\s*=\s*\{(.*?)\n\}", files["nsq_ui.py"], re.S)
    return set(re.findall(r'u"(\w+)":', m.group(1))) if m else set()


def rule_icons_exist(files):
    """Every icon a layout tags or the code asks for is drawn."""
    keys = _icon_keys(files)
    bad = []
    for n in LAYOUTS:
        for k in re.findall(r'Tag="i:([^"]+)"', files[n]):
            if k not in keys:
                bad.append("{0} asks for icon {1}, which ICONS does not draw".format(n, k))
    for n in tool_py(files):
        for k in re.findall(r"(?:set_button\([^,]+,|set_icon_data\([^,]+,)\s*u?\"(\w+)\"", files[n]):
            if k not in keys:
                bad.append("{0} asks for icon {1}, which ICONS does not draw".format(n, k))
    if "ui.iconize(self.win)" not in code_only(files["nsq_window.py"]):
        bad.append("the window never draws its icons")
    return bad


def rule_close_resets_isolate(files):
    b = _fn_body(code_only(files["nsq_selector.py"]), "on_closed", "    ")
    bad = []
    if not re.search(r"for key in list\(self\.iso_views\):(?:\n\s{20,}.*)*?reset_isolate_view\(", b):
        bad.append("closing the tool must reset every isolate it made")
    if "_restore_all(" not in b:
        bad.append("closing the tool must put the colours back")
    return bad


def rule_events_hooked_once(files):
    """Revit event handlers never pile up: whatever an earlier engine hooked is
    unhooked before hooking, and the window unhooks on close."""
    sel = code_only(files["nsq_selector.py"])
    b = _fn_body(sel, "install_hooks")
    g = b.find("GetData(HOOK_KEY)")
    r = b.find("remove_hooks(")
    h = b.find("+=")
    bad = []
    if g < 0 or r < 0 or h < 0 or not (g < r < h) or "SetData(HOOK_KEY" not in b:
        bad.append("install_hooks must unhook what was left before it hooks, and record what it hooked")
    if "-=" not in _fn_body(sel, "remove_hooks"):
        bad.append("remove_hooks must unhook")
    if "remove_hooks(" not in _fn_body(sel, "on_closed", "    "):
        bad.append("closing the window must unhook the Revit events")
    return bad


def rule_isolate_ticked_families(files):
    b = _fn_body(code_only(files["nsq_selector.py"]), "_isolate_ids", "    ")
    if "self.include(" not in b or "extras" in b:
        return ["isolate must show only the families ticked in the tree (no accessories or terminals)"]
    return []


def rule_start_coloured(files):
    sel = code_only(files["nsq_selector.py"])
    b = _fn_body(sel, "_colour_groups", "    ")
    bad = []
    if "core.start_keys(" not in b or "core.START_COLOUR" not in b or "core.START_WEIGHT" not in b:
        bad.append("the start must be drawn in its own colour and weight")
    if "self.col_on = True" not in _fn_body(sel, "pick_start", "    "):
        bad.append("picking a start must turn the colours on")
    return bad


def rule_shift_moves(files):
    sel = code_only(files["nsq_selector.py"])
    bad = []
    for name in ("_on_up", "_on_down", "_on_key"):
        b = _fn_body(sel, name, "    ")
        if "self._shift()" not in b or "_move_picked(" not in b or "_step(" not in b:
            bad.append("{0}: plain press steps the selection, Shift moves the systems".format(name))
    return bad


def rule_toggle_buttons(files):
    b = _fn_body(code_only(files["nsq_selector.py"]), "_refresh_view_buttons", "    ")
    bad = []
    for on, off in (("Reset 2D isolate", "Isolate Systems 2D"), ("Reset 3D isolate", "Isolate 3D"),
                    ('set_button(col, u"uncolour"', 'set_button(col, u"colour"')):
        if on not in b or off not in b:
            bad.append("{0} / {1} must be one button".format(off, on))
    if b.count('u"ActiveButton"') < 3:
        bad.append("a toggle that is on must change colour")
    return bad


def rule_own_selection_ignored(files):
    b = _fn_body(code_only(files["nsq_selector.py"]), "revit_selection_changed", "    ")
    if not re.search(r"core\.user_selection\([^)]*self\.own_sel", b):
        return ["the tool's own selections must not light Remove from sequence"]
    return []


def rule_follow_view_pick(files):
    """A pick in the view finds its row, and never re-selects in Revit (that
    would replace the user's own selection)."""
    sel = code_only(files["nsq_selector.py"])
    b = _fn_body(sel, "_follow_selection", "    ")
    bad = []
    if "core.systems_holding(" not in b or "_bring_into_view(" not in b:
        bad.append("a pick in the view must select and show its system's row")
    if "_select_picked(" in b or "_select_ids(" in b:
        bad.append("following a pick must not change the Revit selection")
    if "_follow_selection(" not in _fn_body(sel, "revit_selection_changed", "    "):
        bad.append("selection changes never reach _follow_selection")
    return bad


def rule_crop_respected(files):
    b = _fn_body(code_only(files["nsq_revit.py"]), "elements_in_view")
    if "_inside_crop(" not in b:
        return ["systems must be read from inside the crop region / section box only"]
    return []


def rule_butted_parts_joined(files):
    if "core.link_open_ends(" not in _fn_body(code_only(files["nsq_revit.py"]), "read_network"):
        return ["parts butted together but not connected must be joined before grouping"]
    return []


def rule_removed_systems_drop(files):
    sel = code_only(files["nsq_selector.py"])
    bad = []
    if "core.split_gone(" not in _fn_body(sel, "recompute", "    "):
        bad.append("a system with every element removed must leave the list")
    if "core.bring_back(" not in _fn_body(sel, "_on_restore", "    "):
        bad.append("Restore removed must bring dropped systems back")
    if "hide_views" in _fn_body(sel, "_read_job", "    "):
        bad.append("Refresh must work after Remove (only the tool's isolate may block it)")
    return bad


def rule_menu_moves(files):
    sel = code_only(files["nsq_selector.py"])
    b = _fn_body(sel, "_build_menu", "    ")
    bad = []
    for text, fn in ((u"Move to...", "_on_menu_to"), (u"Move to top", "_on_menu_top"),
                     (u"Move to next", "_on_menu_next")):
        if text not in files["nsq_selector.py"] or fn not in b:
            bad.append("the right-click menu needs {0}".format(text))
    if "ui.prompt_number(" not in _fn_body(sel, "_on_menu_to", "    "):
        bad.append("Move to... must prompt for the position")
    if "self._next_place()" not in _fn_body(sel, "_on_menu_next", "    ") or \
            "i = self._index(self.last_key)" not in _fn_body(sel, "_next_place", "    "):
        bad.append("Move to next goes straight after the last system moved")
    if "self._moved(new)" not in _fn_body(sel, "_move_to", "    "):
        bad.append("_move_to must record where it landed for Move to next")
    if "self._note_place(new)" not in _fn_body(sel, "_move_picked", "    ") or \
            "core.step_units(" not in _fn_body(sel, "_move_picked", "    "):
        bad.append("_move_picked must step by groups and record where it landed for Move to next")
    if "_note_place(" not in _fn_body(sel, "_moved", "    "):
        bad.append("a move must record where it landed for Move to next")
    if "holder.ContextMenu = self.menu" not in sel:
        bad.append("the rows never get the menu")
    if "merge_theme(menu)" not in b:
        bad.append("the menu opens outside the window, so it needs its own theme")
    return bad


def rule_auto_next(files):
    sel = code_only(files["nsq_selector.py"])
    b = _fn_body(sel, "auto_next", "    ")
    bad = []
    if "core.next_nearest(" not in b or \
            not re.search(r"end = max\(\[self\._index\(k\) for k in self\._unit_keys\(chain\[-1\]\)\]\) \+ 1", b) or \
            "core.move_many(st[u\"systems\"], set([self._index(k) for k in unit]), end)" not in b:
        bad.append("Auto next must put the nearest system (or its whole group) straight after the last placed")
    r = _fn_body(sel, "_refresh_auto", "    ")
    if 'btn.SetResourceReference(FrameworkElement.StyleProperty, u"GreenButton")' not in r or \
            'st[u"reorder_due"]' not in r or "btn.IsEnabled = started" not in r:
        bad.append("Auto Re-order must light green once a start is picked, and only then")
    if 'pick.SetResourceReference(FrameworkElement.StyleProperty, u"ActiveButton")' not in r:
        bad.append("Pick start must turn orange once a start is picked")
    for fn in ("_on_remove", "_on_restore", "_on_group", "_on_ungroup"):
        if 'st[u"reorder_due"] = True' not in _fn_body(sel, fn, "    "):
            bad.append("{0} must light Auto Re-order again".format(fn))
    p = _fn_body(sel, "pick_start", "    ")
    if "core.move_to_position(" not in p or not re.search(r'st\[u"chain"\] = \[x\[u"key"\] for x in st\[u"systems"\] if x\[u"key"\] in unit', p):
        bad.append("a picked start must put its system at #1 and begin the chain")
    if "self.sel.auto_reorder(" not in _fn_body(code_only(files["nsq_window.py"]), "_on_auto_start", "    ") or \
            "self.auto_reorder(" not in _fn_body(sel, "_on_auto_btn", "    "):
        bad.append("the Auto Re-order button on the System Selector must re-order")
    if 'st[u"chain"] = []' not in _fn_body(sel, "auto_reorder", "    "):
        bad.append("Auto Re-order must work the whole order out again from the start")
    return bad


def rule_no_elementid_from_int(files):
    """ElementId(int) changed in Revit 2026 (Int64) - hold the ElementIds from the read."""
    bad = []
    for n in tool_py(files):
        for m in re.finditer(r"ElementId\(\s*[a-z_]\w*\s*\)", code_only(files[n])):
            bad.append("{0}: {1} builds an ElementId from a number".format(n, m.group(0)))
    return bad


def rule_view_kinds(files):
    v = code_only(files["nsq_views.py"])
    bad = []
    if 'self.excluded[u"kind"]' not in _fn_body(v, "_sync_kinds", "    ") or \
            "_sync_kinds(" not in _fn_body(v, "_values_changed", "    "):
        bad.append("the Show tick boxes and the Type value list must stay one filter")
    if 'u"view_kinds_off"' not in _fn_body(v, "_sync_kinds", "    "):
        bad.append("the view types shown must be remembered")
    return bad


def rule_view_value_lists(files):
    v = code_only(files["nsq_views.py"])
    bad = []
    if "self.excluded" not in _fn_body(v, "shown", "    "):
        bad.append("the views list must honour the heading value lists")
    if "core.column_values(" not in _fn_body(v, "_open_values", "    "):
        bad.append("a heading drop-down must list the column's values")
    if "core.tick_values(" not in _fn_body(v, "_open_values", "    "):
        bad.append("the drop-down needs Select all / Clear all")
    if "top.Children.Add(self.popups[col])" not in _fn_body(v, "_build_head", "    "):
        bad.append("the drop-downs must sit in the heading's tree or they lose the theme")
    return bad


def rule_tag_in_views(files):
    r = code_only(files["nsq_revit.py"])
    b = _fn_body(r, "_tag")
    bad = []
    if 'tag.get(u"views")' not in b or "visible_in_view(" not in b:
        bad.append("ticked views must each be tagged where the elements show")
    if 'u"views": self.views.ticked_ids()' not in code_only(files["nsq_window.py"]) or \
            'u"views_doc": self.views.doc_key' not in code_only(files["nsq_window.py"]):
        bad.append("Apply / Run never passes the ticked views to the tag step")
    fp = _fn_body(r, "tag_views")
    if "IsTemplate" not in fp or "core.TAG_VIEW_KINDS" not in fp:
        bad.append("the view list must hold plans, sections and 3D views only, no templates")
    if "view_can_tag(view, False)" not in b:
        bad.append("a ticked section or locked 3D view must be allowed to take tags")
    if "rv.views_showing(" not in _fn_body(code_only(files["nsq_views.py"]), "_on_find", "    "):
        bad.append("Find views with this system must look for the views showing it")
    return bad


def rule_isolate_in_3d(files):
    """Isolate in 3D isolates and colours the chosen 3D view - not the active
    one - records it for reset, opens it, and keeps it in step with the table."""
    sel = code_only(files["nsq_selector.py"])
    rv_ = code_only(files["nsq_revit.py"])
    bad = []
    iso = _fn_body(rv_, "isolate_systems")
    if not re.search(r"def isolate_systems\(uidoc, ids, log, view=None\)", iso) or \
            not re.search(r"if view is None:\s*\n\s*view = doc\.ActiveView", iso):
        bad.append("isolate_systems must isolate the view it is given")
    b = _fn_body(sel, "_on_iso3d", "    ")
    if not re.search(r"rv\.isolate_systems\(uidoc, ids, self\.w\.log, view\)", b):
        bad.append("Isolate in 3D must isolate the 3D view, not the active view")
    if "rv.colour_systems(" not in b or "self.snapshots.setdefault(key" not in b:
        bad.append("Isolate in 3D must colour the systems, recording the view's own overrides")
    if "self.iso_views[key] = view.Id" not in b:
        bad.append("the 3D isolate must be recorded so closing resets it")
    if "RequestViewChange(view)" not in b:
        bad.append("Isolate in 3D must take you to the 3D view")
    if "rv.default_3d(doc)" not in b or "rv.create_default_3d(" not in b:
        bad.append("with no view picked, Isolate in 3D must use (or make) the default 3D view")
    if "self._sync_3d(" not in _fn_body(sel, "_sync", "    "):
        bad.append("table changes never reach the 3D view")
    if not re.search(r"rv\.isolate_systems\([^)]*view\)", _fn_body(sel, "_sync_3d", "    ")):
        bad.append("the 3D sync must isolate the 3D view")
    if not re.search(r"here == self\.iso3d:\s*\n\s*stale = False", _fn_body(sel, "view_changed", "    ")):
        bad.append("opening the 3D view must not light Refresh")
    return bad


def rule_iso3d_kept_apart(files):
    """Reset isolate and Clear colours leave the 3D view to its own button;
    Run and close tidy it too."""
    sel = code_only(files["nsq_selector.py"])
    bad = []
    if "self._reset_isolates(uiapp, skip=self.iso3d)" not in _fn_body(sel, "_on_isolate", "    "):
        bad.append("Reset isolate also resets the 3D view")
    if "self._restore_all(uiapp, skip=self.iso3d)" not in _fn_body(sel, "_on_colour", "    "):
        bad.append("Clear colours also clears the 3D view")
    if not re.search(r"key == skip", _fn_body(sel, "_reset_isolates", "    ")) or \
            not re.search(r"key == skip", _fn_body(sel, "_restore_all", "    ")):
        bad.append("the skip view is not skipped")
    if "self.col3d = False" not in _fn_body(sel, "after_run", "    "):
        bad.append("Run must turn the 3D colours off too")
    return bad


def rule_3d_picker(files):
    """The 3D view picker: Default first, the choice saved, never saved while filling."""
    sel = code_only(files["nsq_selector.py"])
    bad = []
    x = files["NumberSequencer.xaml"]
    if 'x:Name="SelIso3DBtn"' not in x or 'x:Name="Sel3DCombo"' not in x:
        bad.append("the layout has no Isolate in 3D button or 3D view picker")
    if "core.combo_3d_items(" not in _fn_body(sel, "fill_3d_combo", "    "):
        bad.append("the picker must list Default 3D view first")
    if not re.search(r"if self\.filling_3d:\s*\n\s*return", _fn_body(sel, "_on_3d_choice", "    ")):
        bad.append("filling the picker overwrites the saved 3D view")
    if '"iso3d_view"' not in files["nsq_core.py"]:
        bad.append("the chosen 3D view is not a setting")
    order = [x.find('x:Name="{0}"'.format(n)) for n in
             ("SelIso3DBtn", "SelGroupBtn", "SelPickStartBtn", "SelAutoBtn", "SelIsolateBtn", "SelRestoreBtn")]
    a, z = order[4], order[5]
    if 'Content="Isolate Systems 2D"' not in x or min(order) < 0 or order != sorted(order) or \
            "</WrapPanel>" in x[a:z] or "</WrapPanel>" in x[order[0]:order[3]]:
        bad.append("step 2 row: Isolate 3D, Group systems, Pick start, Auto Re-order; then one row of "
                   "tools from Isolate Systems 2D")
    return bad


def rule_groups_wired(files):
    """Groups: kept whole and together on every recompute, shaded, moved as
    one by Auto order, tidied after every move, made from the view selection."""
    sel = code_only(files["nsq_selector.py"])
    x = files["NumberSequencer.xaml"]
    bad = []
    for n in ("SelGroupBtn", "SelUngroupBtn", "SelGroupOrderBtn"):
        if 'x:Name="{0}"'.format(n) not in x:
            bad.append("the layout has no {0}".format(n))
    if "self._regroup()" not in _fn_body(sel, "recompute", "    "):
        bad.append("recompute must keep the groups whole and together")
    r = _fn_body(sel, "_regroup", "    ")
    for fn in ("core.clean_groups(", "core.gather_groups(", "core.colour_groups(", "core.system_colours("):
        if fn not in r:
            bad.append("_regroup must call {0}".format(fn))
    if 'shade.get(sd[u"key"])' not in _fn_body(sel, "_colour_groups", "    "):
        bad.append("the view colours must use each system's group shade")
    if 'shade.get(sd[u"key"])' not in _fn_body(sel, "_build_rows", "    "):
        bad.append("the table swatch must show the group shade")
    if "core.auto_order_units(" not in _fn_body(sel, "_on_auto_order", "    "):
        bad.append("Auto order must move groups as one")
    if "core.tidy_groups(" not in _fn_body(sel, "_moved", "    "):
        bad.append("a move must tidy the groups")
    for fn in ("_moved", "_move_picked", "_on_group"):
        if "self._gone_keys()" not in _fn_body(sel, fn, "    "):
            bad.append("{0} must keep removed systems in their groups".format(fn))
    if "self.view_sel = [] if own else list(id_values)" not in _fn_body(sel, "revit_selection_changed", "    "):
        bad.append("Group never sees what the user selected in the view")
    if "core.systems_holding(" not in _fn_body(sel, "_view_hits", "    "):
        bad.append("Group must find the systems of the elements selected in the view")
    if "self._entry_skip()" not in _fn_body(sel, "auto_next", "    "):
        bad.append("Auto next must only enter a group at its first system")
    return bad


def rule_sheets_wired(files):
    """Sheets in Tag in views: read with the views, selecting one ticks and
    shows its views, its tick box ticks or unticks them."""
    v = code_only(files["nsq_views.py"])
    rv_ = code_only(files["nsq_revit.py"])
    x = files["NumberSequencer.xaml"]
    bad = []
    for n in ("TagSheetSearch", "TagSheetRows", "TagSheetClearBtn"):
        if 'x:Name="{0}"'.format(n) not in x:
            bad.append("the layout has no {0}".format(n))
    if "rv.sheet_table(" not in _fn_body(v, "_read_job", "    "):
        bad.append("the sheets are never read")
    b = _fn_body(rv_, "sheet_table")
    if "GetAllPlacedViews()" not in b or "IsPlaceholder" not in b:
        bad.append("sheet_table must list placed views and skip placeholder sheets")
    a = _fn_body(v, "_apply_sheets", "    ")
    if "self.ticked.add(" not in a or "self.only = ids" not in a:
        bad.append("selecting a sheet must show and tick its views")
    if "core.sheet_state(sh, ticked) is not True" not in _fn_body(v, "_sheet_tick", "    "):
        bad.append("a sheet's tick box must decide from its views' state before the click")
    if "self._paint_sheets()" not in _fn_body(v, "_count", "    "):
        bad.append("ticking a view must update the sheets' tick boxes")
    return bad


def rule_colours_never_left(files):
    """Colours never stay on: the tool marks its colouring, finds what an
    earlier session left, takes it off on Clear / Run / close, and the close
    tidy-up always runs - colours first."""
    sel = code_only(files["nsq_selector.py"])
    rv_ = code_only(files["nsq_revit.py"])
    bad = []
    if "core.COLOUR_MARK" not in _fn_body(rv_, "colour_settings"):
        bad.append("the colouring must carry the tool's mark")
    b = _fn_body(rv_, "colour_systems")
    if not re.search(r"if is_tool_colour\(before\):\s*\n(\s*#.*\n)*\s*before = OverrideGraphicSettings\(\)", b):
        bad.append("colouring over a left-over colour must record it as no override")
    if "rv.tool_coloured(" not in _fn_body(sel, "_read_job", "    "):
        bad.append("a read must find colours an earlier session left")
    c = _fn_body(sel, "_on_colour", "    ")
    if "if self.col_on or self.leftovers:" not in c or "self._clear_leftovers(" not in c:
        bad.append("Clear colours must also take off colours left from before")
    if "self._clear_leftovers(" not in _fn_body(sel, "after_run", "    "):
        bad.append("Run must take off colours left from before")
    o = _fn_body(sel, "on_closed", "    ")
    a = o.find("_CLOSING.append(self.w)")
    q = o.find("self.w.runner.queue(")
    if a < 0 or q < 0 or a > q:
        bad.append("the closed window must be held until its tidy-up has run")
    if "run_when_idle(" not in o:
        bad.append("a refused tidy-up must run when Revit is idle")
    r = o.find("self._restore_all(uiapp)")
    i = o.find("rv.reset_isolate_view(")
    if r < 0 or i < 0 or r > i or "self._clear_leftovers(uiapp)" not in o:
        bad.append("closing must take the colours off first, before resetting isolates")
    if "or bool(self.leftovers)" not in _fn_body(sel, "colours_on", "    "):
        bad.append("closing must tidy up when only left-over colours remain")
    return bad


def rule_compact_layout(files):
    """Layout: families above the systems (Pick start / Auto Re-order on top
    of them), then start point, parameter and sequence, then Tag Views or
    Sheets; every section folds away (remembered); the tags, sheets and
    views live hidden in the main window and move into their own window."""
    x = files["NumberSequencer.xaml"]
    win = code_only(files["nsq_window.py"])
    ui_ = code_only(files["nsq_ui.py"])
    bad = []
    order = ['x:Name="SelFamBody"', 'x:Name="SelPickStartBtn"', 'x:Name="SelRows"',
             'x:Name="StartBody"', 'x:Name="ParamBody"', 'x:Name="SequenceBody"', 'x:Name="TagOpenBtn"',
             'x:Name="TagStore"', 'x:Name="TagCheck"']
    at = [x.find(o) for o in order]
    if min(at) < 0 or at != sorted(at):
        bad.append("the order must be families, start buttons, systems, start point, parameter, sequence, "
                   "then Tag Views or Sheets")
    if not re.search(r'x:Name="TagStore"[^>]*Visibility="Collapsed"', x):
        bad.append("the tags, sheets and views must be kept hidden in the main window")
    m = re.search(r"SECTIONS = \[(.*?)\n\]", files["nsq_window.py"], re.S)
    listed = re.findall(r'u"(\w+)"', m.group(1)) if m else []
    for name in re.findall(r'x:Name="(\w+Toggle)"', x):
        if name not in listed:
            bad.append("{0} is never wired to fold its section".format(name))
    for name in listed:
        if name.endswith(("Toggle", "Body", "Row")) and 'x:Name="{0}"'.format(name) not in x:
            bad.append("SECTIONS names {0}, which the layout lacks".format(name))
    if not re.search(r"\n        self\._build_sections\(\)\n        self\.loading = False", win):
        bad.append("the sections are never built")
    if 'self.settings[u"collapsed"]' not in _fn_body(win, "_section_changed", "    "):
        bad.append("folded sections must be remembered")
    if "el.BeginAnimation(prop, None)" not in _fn_body(ui_, "animate"):
        bad.append("an animation must let go of its property when it lands")
    o = _fn_body(win, "_on_tag_open", "    ")
    if 'self.ctl(u"TagStore").Child = None' not in o or 'f(u"THost").Child = content' not in o or \
            'self.ctl(u"TagStore").Child = content' not in o:
        bad.append("the tag window must borrow the tags, sheets and views and give them back on closing")
    if 'f(u"TApplyBtn").Click' not in o:
        bad.append("the tag window needs Apply to go back")
    if "tw.Close()" not in _fn_body(win, "_on_closed", "    "):
        bad.append("closing the tool must close the tag window")
    if "SelTreeScroll\").MaxHeight" not in _fn_body(win, "_on_main_size", "    "):
        bad.append("the families must size to their content, up to a share of the window")
    return bad


def rule_section_box_follows(files):
    """Isolate 3D moves an active section box to the systems - on the press
    and whenever the systems change - and turns the colours on."""
    sel = code_only(files["nsq_selector.py"])
    rv_ = code_only(files["nsq_revit.py"])
    bad = []
    f = _fn_body(rv_, "fit_section_box")
    if "IsSectionBoxActive" not in f or "SetSectionBox(" not in f:
        bad.append("fit_section_box must move an active section box")
    b = _fn_body(sel, "_on_iso3d", "    ")
    fi = b.find("rv.fit_section_box(")
    ii = b.find("rv.isolate_systems(uidoc, ids, self.w.log, view)")
    if fi < 0 or ii < 0 or fi > ii:
        bad.append("Isolate 3D must fit the section box before isolating")
    if "rv.fit_section_box(" not in _fn_body(sel, "_sync_3d", "    "):
        bad.append("new systems must move the section box too")
    if "self.col_on = True" not in b:
        bad.append("Isolate 3D must turn Colour systems on")
    if "self.boxes[key] = (view.Id, old_box)" not in b or \
            not re.search(r"if key in self\.boxes:\s*\n\s*rv\.restore_section_box\(", b):
        bad.append("the 3D view's own section box must be kept and put back on Reset")
    if "rv.restore_section_box(" not in _fn_body(sel, "on_closed", "    "):
        bad.append("closing must put the 3D view's own section box back")
    return bad


def rule_run_and_open(files):
    """Run Sequence; Remove from sequence says so, in red; a run that tagged
    in ticked views offers to open them."""
    sel = code_only(files["nsq_selector.py"])
    win = code_only(files["nsq_window.py"])
    bad = []
    if 'u"Run Sequence ({0})"' not in _fn_body(win, "_refresh_apply", "    ") or \
            'Text="Run Sequence"' not in files["NumberSequencer.xaml"]:
        bad.append("the run button must read Run Sequence")
    v = _fn_body(sel, "_refresh_view_buttons", "    ")
    if 'u"RedButton"' not in v or 'u"RedActiveButton"' not in v or 'u"Remove from sequence' not in v:
        bad.append("Remove from sequence must say so, in red")
    a = _fn_body(win, "_applied", "    ")
    if "self._offer_open(tag)" not in a:
        bad.append("a run that tagged in ticked views must offer to open them")
    o = _fn_body(win, "_offer_open", "    ")
    if "core.open_list(" not in o or "ui.ask_yes_no(" not in o or "rv.open_views(" not in o:
        bad.append("the offer must ask, then open the ticked sheets and views")
    if "uidoc.ActiveView = view" not in _fn_body(code_only(files["nsq_revit.py"]), "open_views"):
        bad.append("open_views must open each one in turn")
    return bad


def rule_window_motion(files):
    """The tag window pours out of its button and back (the RevoBIM genie);
    both windows shrink to a floating bar and come back on a green arrow;
    a double-click on the top or bottom edge takes the monitor's full height;
    tags sit above sheets | views, with a splitter between two star columns."""
    ui_ = code_only(files["nsq_ui.py"])
    win = code_only(files["nsq_window.py"])
    x = files["NumberSequencer.xaml"]
    tx = files["NumberSequencerTags.xaml"]
    bad = []
    tw = ui_[ui_.find("class Tween"):]
    if "CompositionTarget.Rendering += self.handler" not in tw or "RenderingTime" not in tw or \
            "self.handler = EventHandler(self._frame)" not in tw:
        bad.append("animations must run on rendered frames, timed from the frame, with one stored handler")
    g = _fn_body(ui_, "genie")
    for need in ("RenderTargetBitmap(", "CroppedBitmap(", "mt.Matrix = Matrix(", "first_frame=hide_real"):
        if need not in g:
            bad.append("genie must {0}".format(need))
    o = _fn_body(win, "_on_tag_open", "    ")
    a = o.find("tw.Opacity = 0.0")
    b = o.find("ui.genie(tw, ui.screen_point(self.ctl(u\"TagOpenBtn\"), self.win), None, reverse=True)")
    if a < 0 or b < 0 or a > b:
        bad.append("the tag window must open out of its button")
    if "on_close=self._close_tagwin" not in o or "self._close_tagwin()" not in o:
        bad.append("Apply and the close button must pour the tag window back")
    if "ui.genie(" not in _fn_body(win, "_close_tagwin", "    "):
        bad.append("closing the tag window must pour it back into its button")
    if 'min_btn=self.ctl(u"MinBtn")' not in win or 'min_btn=f(u"TMinBtn")' not in o:
        bad.append("both windows need the shrink button")
    if 'x:Name="MinBtn"' not in x or 'x:Name="TMinBtn"' not in tx:
        bad.append("the layouts need the shrink buttons")
    ch = ui_[ui_.find("class Chrome"):ui_.find("def wire_egg")]
    if 'p.SetResourceReference(Shape.StrokeProperty, u"Green")' not in ch:
        bad.append("a shrunk window's button must turn into a green up arrow")
    if "w.Height = bar" not in ch or "Tween(SHRINK_MS" not in ch:
        bad.append("shrinking must slide the window down to just its bar")
    if "self._on_edge_down" not in ch or "w.Height = bottom - top" not in ch:
        bad.append("a double-click on the top or bottom edge must take the full height")
    sub = re.findall(r'Style="\{DynamicResource SubStepText\}" Text="([\d.]+)"', x)
    if sub[:2] != ["6.1", "6.2"]:
        bad.append("the tag window needs 6.1 on the tag family and 6.2 on the sheets / views")
    if 'x:Name="TagTabSheets"' not in x or 'x:Name="TagTabViews"' not in x:
        bad.append("sheets and views must be tabs")
    if "self._show_tag_tab()" not in _fn_body(code_only(files["nsq_views.py"]), "_on_tag_tab", "    "):
        bad.append("the Sheets / Views tabs must switch the panels")
    return bad


def rule_step_numbers(files):
    """The to-do order on the headings: white shadowed squares, red bold numbers -
    1-2 the tab's own sections, 3 start point, 4 parameter, 5 sequence,
    6 Tag Views or Sheets, 7 Run Sequence."""
    x = files["NumberSequencer.xaml"]
    theme = files[THEME]

    def block(key):
        i = theme.find('x:Key="{0}"'.format(key))
        return theme[i:theme.find("</Style>", i)] if i >= 0 else ""
    t = block("StepBadge") + "\n" + block("StepText")
    bad = []
    nums = re.findall(r'Style="\{DynamicResource StepText\}" Text="(\d+)"', x)
    if nums != ["1", "2", "1", "2", "3", "4", "5", "6", "7"]:
        bad.append("the step numbers must run 1 2 (Sequencer), 1 2 (System Selector), 3 4 5, 6 7 - got {0}".format(nums))
    if not re.search(r'x:Key="StepBadge".*?Background" Value="\{DynamicResource OnAccent\}"', t, re.S) or \
            not re.search(r'x:Key="StepText".*?Foreground" Value="\{DynamicResource Red\}".*?FontWeight" Value="Bold"', t, re.S) or \
            not re.search(r'x:Key="StepBadge".*?<DropShadowEffect', t, re.S) or \
            not re.search(r'x:Key="StepBadge".*?BorderBrush" Value="\{DynamicResource Red\}"', t, re.S):
        bad.append("the step squares must be white with a thick red edge, shadowed, with red bold numbers")
    return bad


def rule_window_follows_sections(files):
    """Folding a section shrinks the window by what it gave up, opening it
    grows the window back; the size is remembered for next time."""
    ui_ = code_only(files["nsq_ui.py"])
    win = code_only(files["nsq_window.py"])
    bad = []
    sec = ui_[ui_.find("class Section"):ui_.find("class Tween")]
    if "self._tell(target)" not in sec or "self._tell(-h)" not in sec:
        bad.append("a section must say how much height it gives up or takes back")
    if "self._section_resize)" not in _fn_body(win, "_build_sections", "    "):
        bad.append("the sections are never told to resize the window")
    r = _fn_body(win, "_section_resize", "    ")
    if "ui.animate(w, FrameworkElement.HeightProperty" not in r or "self.chrome.full" not in r:
        bad.append("the window must follow the sections (not in full screen or as a bar)")
    if "self._remember_size()" not in _fn_body(win, "_on_closed", "    ") or 'u"win_h"' not in win:
        bad.append("the window size must be remembered")
    return bad


def rule_fold_all(files):
    """Collapse all / Expand all at the top folds the open tab's sections with
    one window move for the lot."""
    win = code_only(files["nsq_window.py"])
    bad = []
    if 'x:Name="FoldAllBtn"' not in files["NumberSequencer.xaml"]:
        bad.append("the layout has no Collapse all button")
    f = _fn_body(win, "_on_fold_all", "    ")
    if "self.fold_batch = 0.0" not in f or "self._section_resize(total)" not in f:
        bad.append("Collapse all must move the window once, by the total")
    if "self.fold_batch += delta" not in _fn_body(win, "_section_resize", "    "):
        bad.append("sections folded by Collapse all must add up, not each move the window")
    if "self._refresh_fold_all()" not in _fn_body(win, "_show_tab", "    "):
        bad.append("Collapse / Expand all must follow the tab")
    return bad


def rule_tags_reach_every_category(files):
    """Each element gets a tag that can take it (the chosen one, else one for
    its category); Tag untagged only (on by default) is honoured; opening
    Tag Views or Sheets switches tagging on; the sheet Number column fits the
    longest number and both narrow columns can be dragged."""
    win = code_only(files["nsq_window.py"])
    rv_ = code_only(files["nsq_revit.py"])
    v = code_only(files["nsq_views.py"])
    bad = []
    a = _fn_body(win, "_on_apply", "    ")
    if 'u"by_host":' not in a or 'u"untagged_only":' not in a:
        bad.append("the run must carry the tag per category and the untagged-only choice")
    t = _fn_body(rv_, "_tag_view")
    if "IndependentTag.Create(doc, use[u\"id\"]" not in t or "core.skip_tagging(" not in t:
        bad.append("each element must be tagged with the tag for its category, untagged only honoured")
    if 'x:Name="TagUntaggedCheck"' not in files["NumberSequencer.xaml"] or \
            'u"tag_untagged": u"on"' not in files["nsq_core.py"]:
        bad.append("Tag untagged only must exist and be on by default")
    o = _fn_body(win, "_on_tag_open", "    ")
    if 'self.ctl(u"TagCheck").IsChecked = True' not in o:
        bad.append("opening Tag Views or Sheets must switch tagging on")
    b = _fn_body(v, "build_sheets", "    ")
    if "self._fit_number(self.sheets)" not in b or "self._build_sheet_head()" not in b:
        bad.append("the sheet Number column must fit the longest number, under draggable headings")
    if "self._resize_sheet_columns()" not in _fn_body(v, "_edge", "    "):
        bad.append("dragging a sheet heading edge must resize every row")
    return bad


def rule_step_two(files):
    """Step 2's own row: 2.1 Isolate 3D (filled green), 2.2 Group systems
    (green, named), 2.3 Pick start (filled green until picked), 2.4 Auto Re-order -
    each sub-step in a small red square; Run Sequence waits for a start."""
    sel = code_only(files["nsq_selector.py"])
    win = code_only(files["nsq_window.py"])
    t = files[THEME]
    bad = []
    for key in ("GreenFillButton", "SubStepBadge", "SubStepText"):
        if 'x:Key="{0}"'.format(key) not in t:
            bad.append("Theme.xaml lacks {0}".format(key))
    if 'STEP_ISO3D = u"2.1"' not in sel or 'STEP_GROUP = u"2.2"' not in sel or \
            'STEP_PICK = u"2.3"' not in sel or 'STEP_AUTO = u"2.4"' not in sel:
        bad.append("the sub-steps must be 2.1 Isolate 3D, 2.2 Group systems, 2.3 Pick start, 2.4 Auto Re-order")
    v = _fn_body(sel, "_refresh_view_buttons", "    ")
    if 'u"Isolate 3D", STEP_ISO3D)' not in v or 'b3.SetResourceReference(FrameworkElement.StyleProperty, u"GreenFillButton")' not in v:
        bad.append("Isolate 3D must be filled green with its 2.1 square")
    r = _fn_body(sel, "_refresh_auto", "    ")
    if 'u"Pick start", STEP_PICK)' not in r or 'pick.SetResourceReference(FrameworkElement.StyleProperty, u"GreenFillButton")' not in r \
            or 'STEP_AUTO)' not in r:
        bad.append("Pick start must be filled green with 2.2, Auto Re-order carry 2.3")
    g = _fn_body(sel, "_refresh_group_buttons", "    ")
    if 'u"Group systems", STEP_GROUP)' not in g or 'u"GreenButton"' not in g:
        bad.append("Group systems must be a named green button")
    if 'self.ctl(u"ApplyBtn").IsEnabled = ok and not waiting' not in _fn_body(win, "_refresh_apply", "    ") or \
            'if src.get(u"needs_start") and not src.get(u"started"):' not in _fn_body(win, "_on_apply", "    "):
        bad.append("Run Sequence must wait for a picked start on the System Selector")
    if "sp.Children.Add(step_badge(step))" not in _fn_body(code_only(files["nsq_ui.py"]), "set_button"):
        bad.append("set_button must draw the sub-step square")
    return bad


RULES = [
    rule_xaml_parses, rule_clr_first, rule_core_pure, rule_assemblies_referenced,
    rule_no_static_resource, rule_dynamic_keys_defined, rule_style_targettype,
    rule_names_exist, rule_no_fstrings, rule_no_print, rule_integervalue_guarded,
    rule_no_uri, rule_ascii, rule_palettes_match_theme, rule_script_thin,
    rule_no_duplicate_defs, rule_changelog_version, rule_version_displayed,
    rule_egg_wired, rule_enums_late, rule_raise_status_read, rule_handlers_exist,
    rule_window_chrome, rule_theme_chip, rule_readback_after_group,
    rule_checkout_before_write, rule_init_order, rule_modules_load_on_stub,
    rule_typing_never_chooses, rule_pick_systems_loops, rule_isolate_reset_first,
    rule_overrides_snapshot_first, rule_colours_turned_off, rule_selector_plans_only,
    rule_selector_skips_accessories, rule_tick_by_value, rule_icons_exist,
    rule_close_resets_isolate, rule_events_hooked_once, rule_isolate_ticked_families,
    rule_start_coloured, rule_shift_moves, rule_toggle_buttons, rule_own_selection_ignored,
    rule_follow_view_pick, rule_crop_respected, rule_butted_parts_joined,
    rule_removed_systems_drop, rule_menu_moves, rule_auto_next, rule_tag_in_views,
    rule_no_elementid_from_int, rule_view_value_lists, rule_view_kinds,
    rule_isolate_in_3d, rule_iso3d_kept_apart, rule_3d_picker, rule_groups_wired, rule_sheets_wired,
    rule_colours_never_left, rule_compact_layout, rule_section_box_follows, rule_run_and_open,
    rule_window_motion, rule_step_numbers, rule_window_follows_sections,
    rule_fold_all, rule_tags_reach_every_category, rule_step_two,
]


# ============================================================
# Selftest: every rule must catch its own deliberate breakage
# ============================================================

def _sub(name, old, new):
    def brk(files):
        assert old in files[name], "breakage anchor missing in {0}: {1!r}".format(name, old)
        files[name] = files[name].replace(old, new, 1)
        return files
    return brk


def _append(name, text):
    def brk(files):
        files[name] = files[name] + text
        return files
    return brk


def _changelog_drop_current(files):
    """Rename the current version's changelog heading, whatever the version."""
    v = re.search(r'__version__\s*=\s*u?"([^"]+)"', files["nsq_core.py"]).group(1)
    assert "## " + v in files["CHANGELOG.md"], "changelog has no current entry"
    files["CHANGELOG.md"] = files["CHANGELOG.md"].replace("## " + v, "## 0.0.0", 1)
    return files


BREAKAGES = [
    (rule_xaml_parses, _sub("NumberSequencer.xaml", "<!-- ======== Header ======== -->",
                            "<!-- -------- Header -------- -->")),
    (rule_xaml_parses, _sub("Theme.xaml", "</ResourceDictionary>", "")),
    (rule_clr_first, _sub("nsq_ui.py", "import nsq_clr  # noqa: F401  (must stay the first import)\n", "")),
    (rule_core_pure, _append("nsq_core.py", "\nimport clr\n")),
    (rule_assemblies_referenced, _sub("nsq_clr.py", "'System.Windows.Forms',", "")),
    (rule_assemblies_referenced, _append("nsq_ui.py", "\nfrom System.Data import DataTable\n")),
    (rule_no_static_resource, _sub("NumberSequencer.xaml", "{DynamicResource Bg}", "{StaticResource Bg}")),
    (rule_dynamic_keys_defined, _sub("NumberSequencer.xaml", "{DynamicResource Bg}", "{DynamicResource Bgg}")),
    (rule_dynamic_keys_defined, _sub("nsq_window.py", 'TextBlock.ForegroundProperty, u"Muted"',
                                     'TextBlock.ForegroundProperty, u"Mute"')),
    (rule_style_targettype, _sub("NumberSequencer.xaml", '<TextBlock x:Name="VersionText"',
                                 '<TextBlock Style="{DynamicResource ChipButton}" x:Name="VersionText"')),
    (rule_names_exist, _sub("nsq_window.py", 'self.ctl(u"PreviewText")', 'self.ctl(u"PreviewTxt")')),
    (rule_names_exist, _sub("NumberSequencerTags.xaml", 'x:Name="TApplyBtn"', 'x:Name="TApplyButton"')),
    (rule_no_fstrings, _append("nsq_core.py", "\nX = f'{1}'\n")),
    (rule_no_print, _append("nsq_core.py", "\nprint('x')\n")),
    (rule_integervalue_guarded, _append("nsq_revit.py", "\ndef _bad(e):\n    return e.Id.IntegerValue\n")),
    (rule_no_uri, _append("nsq_ui.py", "\nfrom System import Uri\n")),
    (rule_ascii, _append("nsq_core.py", u"\n# café\n")),
    (rule_palettes_match_theme, _sub("nsq_core.py", 'u"Hover": u"#E9EEF4",\n', "")),
    (rule_palettes_match_theme, _sub("Theme.xaml", '<SolidColorBrush x:Key="Blue" Color="#4FA3E3"/>',
                                     '<SolidColorBrush x:Key="Blue" Color="#3D9BE9"/>')),
    (rule_script_thin, _sub("script.py", "__persistentengine__ = True", "__persistentengine__ = False")),
    (rule_no_duplicate_defs, _append("nsq_core.py", "\ndef format_number(n, pad):\n    return n\n")),
    (rule_changelog_version, _changelog_drop_current),
    (rule_version_displayed, _sub("NumberSequencerResults.xaml", 'x:Name="RVersion"', 'x:Name="RVer"')),
    (rule_egg_wired, _sub("nsq_window.py", "ui.wire_egg(", "ui.wire_eg(")),
    (rule_enums_late, _append("nsq_revit.py", "\nX = BuiltInCategory.OST_DuctCurves\n")),
    (rule_raise_status_read, _sub("nsq_window.py", "status = self.event.Raise()",
                                  "self.event.Raise()\n        status = None")),
    (rule_handlers_exist, _sub("nsq_window.py", "def _on_tick_all(", "def _on_tick_everything(")),
    (rule_window_chrome, _sub("NumberSequencerResults.xaml", 'WindowStyle="None"', 'WindowStyle="SingleBorderWindow"')),
    (rule_theme_chip, _sub("nsq_window.py", "self.win.Activated += self._guard(self._on_activated)\n", "")),
    (rule_readback_after_group, _sub("nsq_revit.py", "        tg.Assimilate()\n", "")),
    (rule_checkout_before_write, _sub("nsq_revit.py",
                                      "    ok_keys, refused = checkout(doc, write_keys, idmap, log)\n",
                                      "    ok_keys, refused = write_keys, []\n")),
    (rule_init_order, _sub("nsq_window.py", '        self.mode = u"dark"\n', "")),
    (rule_init_order, _sub("nsq_window.py", "        self.busy = False\n", "")),
    (rule_typing_never_chooses, _sub("nsq_window.py",
                                     "        self._show_param_list(self.ctl(u\"ParamBox\").Text or u\"\")\n\n    def _on_param_drop",
                                     "        self._choose_param(self.ctl(u\"ParamBox\").Text)\n\n    def _on_param_drop")),
    (rule_pick_systems_loops, _sub("nsq_window.py", "        while True:\n            n = len(self.systems)",
                                   "        if True:\n            n = len(self.systems)")),
    (rule_isolate_reset_first, _sub("nsq_revit.py", "        t.Commit()\n        # gathered after the reset",
                                    "        # gathered after the reset")),
    (rule_isolate_reset_first, _sub("nsq_revit.py", "    keep = list(ids)\n    tg = TransactionGroup",
                                    "    keep = list(ids) + tags_on(doc, view, values)\n    tg = TransactionGroup")),
    (rule_isolate_reset_first, _sub("nsq_revit.py", "list(ids) + tags_on(doc, view, values) +", "list(ids) +")),
    (rule_overrides_snapshot_first, _sub("nsq_revit.py",
                                         "                    before = view.GetElementOverrides(i)\n",
                                         "")),
    (rule_overrides_snapshot_first, _sub("nsq_revit.py",
                                         "        # nothing changed: keep what an earlier colouring recorded\n",
                                         "        snapshot.clear()\n")),
    (rule_colours_turned_off, _sub("nsq_selector.py", "        n = self._restore_all(uiapp)\n        return n + self._clear_leftovers(uiapp)",
                                   "        return 0")),
    (rule_colours_turned_off, _sub("nsq_window.py", "        self.sel.on_closed()\n", "")),
    (rule_selector_plans_only, _sub("nsq_selector.py", 'u"plans_only": True', 'u"plans_only": False')),
    (rule_selector_skips_accessories, _sub("nsq_selector.py",
                                           "return core.sel_include(key, d[u\"passthrough\"], st[u\"left_out\"], st[u\"type_of\"], self.skipped)",
                                           "return st[u\"type_of\"].get(key) not in self.skipped")),
    (rule_tick_by_value, _sub("nsq_tree.py", "(cb.IsChecked == True)", "(cb.IsChecked is not False)")),
    (rule_icons_exist, _sub("NumberSequencer.xaml", 'Tag="i:order"', 'Tag="i:sortorder"')),
    (rule_icons_exist, _sub("nsq_selector.py", 'ui.set_button(rem, u"hide", u"Remove from sequence")',
                            'ui.set_button(rem, u"hidden", u"Remove from sequence")')),
    (rule_close_resets_isolate, _sub("nsq_selector.py",
                                     "                            rv.reset_isolate_view(doc, self.iso_views.pop(key), self.w.log)\n",
                                     "                            self.iso_views.pop(key)\n")),
    (rule_events_hooked_once, _sub("nsq_selector.py",
                                   "    if old is not None:\n        remove_hooks(uiapp, old, log)\n",
                                   "")),
    (rule_events_hooked_once, _sub("nsq_selector.py",
                                   "        remove_hooks(self.w.uiapp, self.hooks, self.w.log)\n",
                                   "")),
    (rule_isolate_ticked_families, _sub("nsq_selector.py",
                                        "                if k in idmap and self.include(k)]",
                                        "                if k in idmap]")),
    (rule_start_coloured, _sub("nsq_selector.py",
                               "                    self.col_on = True\n                    self.col_auto = False\n                    self.recompute()",
                               "                    self.recompute()")),
    (rule_shift_moves, _sub("nsq_selector.py",
                            "    def _on_up(self, sender, e):\n        if self._shift():\n            self._move_picked(-1)",
                            "    def _on_up(self, sender, e):\n        if True:\n            self._move_picked(-1)")),
    (rule_toggle_buttons, _sub("nsq_selector.py", 'ui.set_button(iso, u"unisolate", u"Reset 2D isolate")',
                               'ui.set_button(iso, u"unisolate", u"Isolated")')),
    (rule_own_selection_ignored, _sub("nsq_selector.py",
                                      "self.user_sel = core.user_selection(id_values, self.own_sel, keys)",
                                      "self.user_sel = core.user_selection(id_values, None, keys)")),
    (rule_follow_view_pick, _sub("nsq_selector.py", "        self._paint_rows()\n        self._bring_into_view(hits[0])",
                                 "        self._paint_rows()\n        self._select_picked(False)")),
    (rule_follow_view_pick, _sub("nsq_selector.py", "        if id_values and not own:\n            self._follow_selection(id_values)\n",
                                 "")),
    (rule_crop_respected, _sub("nsq_revit.py", "            if crop is not None and not _inside_crop(e, crop):",
                               "            if False:")),
    (rule_butted_parts_joined, _sub("nsq_revit.py", "    butted = core.link_open_ends(nodes, core.OPEN_END_TOL_MM / 304.8)",
                                    "    butted = 0")),
    (rule_removed_systems_drop, _sub("nsq_selector.py",
                                     "        st[u\"systems\"], gone = core.split_gone(st[u\"systems\"], st[u\"left_out\"])",
                                     "        gone = []")),
    (rule_removed_systems_drop, _sub("nsq_selector.py", "            if key in self.iso_views:\n",
                                     "            if key in self.iso_views or key in self.hide_views:\n")),
    (rule_menu_moves, _sub("nsq_selector.py", "        i = self._index(self.last_key)\n        if i is None:\n            return None",
                           "        i = 0\n        if i is None:\n            return None")),
    (rule_menu_moves, _sub("nsq_selector.py",
                           "                                                             delta, self._gone_keys())\n        self._note_place(new)\n",
                           "                                                             delta, self._gone_keys())\n")),
    (rule_menu_moves, _sub("nsq_selector.py", "        self._note_place(new)\n        return left, joined", "        return left, joined")),
    (rule_menu_moves, _sub("nsq_selector.py", "        ui.merge_theme(menu)\n", "")),
    (rule_auto_next, _sub("nsq_selector.py",
                          "            end = max([self._index(k) for k in self._unit_keys(chain[-1])]) + 1",
                          "            end = len(st[u\"systems\"])")),
    (rule_auto_next, _sub("nsq_selector.py",
                          'st[u"reorder_due"]:\n            btn.SetResourceReference(FrameworkElement.StyleProperty, u"GreenButton")',
                          'st[u"reorder_due"]:\n            btn.SetResourceReference(FrameworkElement.StyleProperty, u"ToolButton")')),
    (rule_auto_next, _sub("nsq_selector.py", '        st[u"reorder_due"] = True   # the order may want working out again\n', "")),
    (rule_auto_next, _sub("nsq_selector.py", '        if not step:\n            st[u"chain"] = []\n', "")),
    (rule_auto_next, _sub("nsq_selector.py", '                    st[u"chain"] = [x[u"key"] for x in st[u"systems"] if x[u"key"] in unit and x[u"on"]]\n', "")),
    (rule_tag_in_views, _sub("nsq_revit.py", "            shown = visible_in_view(doc, view, None, probe=probe)",
                             "            shown = set(keys)")),
    (rule_tag_in_views, _sub("nsq_window.py", ', u"views": self.views.ticked_ids(),', ",")),
    (rule_tag_in_views, _sub("nsq_revit.py",
                             '            if v.IsTemplate or u"{0}".format(v.ViewType) not in core.TAG_VIEW_KINDS:',
                             '            if v.IsTemplate:')),
    (rule_tag_in_views, _sub("nsq_revit.py", "            ok, why = view_can_tag(view, False)",
                             "            ok, why = view_can_tag(view, True)")),
    (rule_no_elementid_from_int, _append("nsq_revit.py", "\ndef _bad(doc, k):\n    return doc.GetElement(ElementId(k))\n")),
    (rule_view_value_lists, _sub("nsq_views.py",
                                 "self.sort[0], self.sort[1], self.only, self.excluded)",
                                 "self.sort[0], self.sort[1], self.only)")),
    (rule_view_value_lists, _sub("nsq_views.py", "            top.Children.Add(self.popups[col])\n", "")),
    (rule_view_value_lists, _sub("nsq_views.py",
                                 "                    self.excluded[col] = core.tick_values(self.excluded[col], list(shown), on)",
                                 "                    pass")),
    (rule_view_kinds, _sub("nsq_views.py", "        self._paint_funnels()\n        self._sync_kinds()\n",
                           "        self._paint_funnels()\n")),
    (rule_modules_load_on_stub, _sub("nsq_window.py", "from System.Windows.Controls import (Grid,",
                                     "from System.Windows.Media import (Grid,")),
    (rule_isolate_in_3d, _sub("nsq_selector.py", "                uidoc.RequestViewChange(view)", "                pass")),
    (rule_isolate_in_3d, _sub("nsq_selector.py", "            n = rv.isolate_systems(uidoc, ids, self.w.log, view)\n            self.iso_views[key] = view.Id\n            self.hide_views.pop(key, None)\n            self.iso3d = key",
                              "            n = rv.isolate_systems(uidoc, ids, self.w.log)\n            self.iso_views[key] = view.Id\n            self.hide_views.pop(key, None)\n            self.iso3d = key")),
    (rule_isolate_in_3d, _sub("nsq_selector.py", "            self.iso_views[key] = view.Id\n            self.hide_views.pop(key, None)\n            self.iso3d = key",
                              "            self.hide_views.pop(key, None)\n            self.iso3d = key")),
    (rule_isolate_in_3d, _sub("nsq_selector.py", "            self._sync_3d(uidoc, msgs)", "            pass")),
    (rule_isolate_in_3d, _sub("nsq_selector.py", "        if self.iso3d is not None and here == self.iso3d:\n            stale = False\n", "")),
    (rule_isolate_in_3d, _sub("nsq_revit.py", "    if view is None:\n        view = doc.ActiveView", "    view = doc.ActiveView")),
    (rule_iso3d_kept_apart, _sub("nsq_selector.py", "self._reset_isolates(uiapp, skip=self.iso3d)", "self._reset_isolates(uiapp)")),
    (rule_iso3d_kept_apart, _sub("nsq_selector.py", "                if key[0] != here or key == skip:\n                    continue\n                view_id, snap",
                                 "                if key[0] != here:\n                    continue\n                view_id, snap")),
    (rule_iso3d_kept_apart, _sub("nsq_selector.py", "        self.col3d = False\n        self.last_col3d = None\n        n = self._restore_all(uiapp)",
                                 "        n = self._restore_all(uiapp)")),
    (rule_3d_picker, _sub("nsq_selector.py", "        if self.filling_3d:\n            return\n", "")),
    (rule_3d_picker, _sub("NumberSequencer.xaml", 'Content="Isolate Systems 2D"', 'Content="Isolate systems"')),
    (rule_3d_picker, _sub("NumberSequencer.xaml", '<Button x:Name="SelGroupBtn" Style="{DynamicResource GreenButton}"', '<Button x:Name="SelGroupX" Style="{DynamicResource GreenButton}"')),
    (rule_3d_picker, _sub("nsq_core.py", '    u"iso3d_view": u"",\n', "")),
    (rule_groups_wired, _sub("nsq_selector.py", "                st[u\"cur\"] = st[u\"systems\"][0][u\"key\"] if st[u\"systems\"] else None\n        self._regroup()",
                             "                st[u\"cur\"] = st[u\"systems\"][0][u\"key\"] if st[u\"systems\"] else None")),
    (rule_groups_wired, _sub("nsq_selector.py", "        groups = [(shade.get(sd[u\"key\"]) or sd[u\"colour\"],",
                             "        groups = [(sd[u\"colour\"],")),
    (rule_groups_wired, _sub("nsq_selector.py", "core.auto_order_units(st[u\"data\"][u\"nodes\"], st[u\"systems\"], st[u\"groups\"], self.include)",
                             "core.auto_order(st[u\"data\"][u\"nodes\"], st[u\"systems\"], self.include)")),
    (rule_groups_wired, _sub("nsq_selector.py", "        self.view_sel = [] if own else list(id_values)\n", "")),
    (rule_groups_wired, _sub("nsq_selector.py", "core.tidy_groups(st[u\"systems\"], st[u\"groups\"], moved, self._gone_keys())",
                             "core.tidy_groups(st[u\"systems\"], st[u\"groups\"], moved)")),
    (rule_groups_wired, _sub("nsq_selector.py", "set(chain) | self._entry_skip()", "set(chain)")),
    (rule_sheets_wired, _sub("nsq_views.py", "                self.ticked.add(r[u\"uid\"])\n                added += 1", "                added += 1")),
    (rule_sheets_wired, _sub("nsq_views.py", "            on = core.sheet_state(sh, ticked) is not True", "            on = sender.IsChecked == True")),
    (rule_sheets_wired, _sub("nsq_revit.py", "            if sh.IsTemplate or getattr(sh, u\"IsPlaceholder\", False):", "            if sh.IsTemplate:")),
    (rule_sheets_wired, _sub("nsq_views.py", "        self.ctl(u\"TagViewCount\").Text = text\n        self._paint_sheets()", "        self.ctl(u\"TagViewCount\").Text = text")),
    (rule_colours_never_left, _sub("nsq_revit.py", "    _call(ogs, u\"SetSurfaceTransparency\", core.COLOUR_MARK)\n", "")),
    (rule_colours_never_left, _sub("nsq_revit.py", "                        before = OverrideGraphicSettings()\n", "                        pass\n")),
    (rule_colours_never_left, _sub("nsq_selector.py", "        if self.col_on or self.leftovers:", "        if self.col_on:")),
    (rule_colours_never_left, _sub("nsq_selector.py", "        _CLOSING.append(self.w)\n", "")),
    (rule_colours_never_left, _sub("nsq_selector.py", "            run_when_idle(self.w.uiapp, idle, log)", "            pass")),
    (rule_colours_never_left, _sub("nsq_selector.py", "        return n + self._clear_leftovers(uiapp)", "        return n")),
    (rule_colours_never_left, _sub("nsq_selector.py", "            data[u\"leftover\"] = rv.tool_coloured(", "            data[u\"leftover\"] = list(")),
    (rule_compact_layout, _sub("NumberSequencer.xaml", 'x:Name="TagStore" Grid.Column="0" Visibility="Collapsed"', 'x:Name="TagStore" Grid.Column="0"')),
    (rule_compact_layout, _sub("nsq_window.py", '    (u"sequence", u"SequenceToggle", u"SequenceBody", None),\n', "")),
    (rule_compact_layout, _sub("nsq_ui.py", "            el.BeginAnimation(prop, None)\n", "")),
    (rule_compact_layout, _sub("nsq_window.py", '            self.ctl(u"TagStore").Child = content\n', "")),
    (rule_compact_layout, _sub("nsq_window.py", "                tw.Close()\n            except Exception:\n                pass\n        self.sel.on_closed()",
                               "                pass\n            except Exception:\n                pass\n        self.sel.on_closed()")),
    (rule_compact_layout, _sub("nsq_window.py", "        self._build_sections()\n", "")),
    (rule_compact_layout, _sub("nsq_window.py", '        self.settings[u"collapsed"] = core.SKIP_SEP.join(shut)\n', "")),
    (rule_section_box_follows, _sub("nsq_selector.py", "            old_box = rv.fit_section_box(doc, view, ids, self.w.log)\n            boxed",
                                    "            old_box = None\n            boxed")),
    (rule_section_box_follows, _sub("nsq_selector.py", "            # new systems: the section box follows them\n            old_box = rv.fit_section_box(doc, view, ids, self.w.log)",
                                    "            old_box = None")),
    (rule_section_box_follows, _sub("nsq_selector.py", "                    if key in self.boxes:\n                        rv.restore_section_box(",
                                    "                    if False:\n                        rv.restore_section_box(")),
    (rule_section_box_follows, _sub("nsq_selector.py", "                            rv.restore_section_box(doc, view_id, box, log)", "                            pass")),
    (rule_section_box_follows, _sub("nsq_revit.py", "        if not view.IsSectionBoxActive:\n            return None\n", "")),
    (rule_run_and_open, _sub("nsq_window.py", u'u"Run Sequence ({0})"', u'u"Run ({0})"')),
    (rule_run_and_open, _sub("nsq_selector.py", 'rem.SetResourceReference(FrameworkElement.StyleProperty, u"RedButton")',
                             'rem.SetResourceReference(FrameworkElement.StyleProperty, u"ToolButton")')),
    (rule_run_and_open, _sub("nsq_window.py", "            self.win.Dispatcher.BeginInvoke(Action(lambda: self._offer_open(tag)))", "            pass")),
    (rule_run_and_open, _sub("nsq_revit.py", "            uidoc.ActiveView = view\n", "            pass\n")),
    (rule_window_motion, _sub("nsq_ui.py", "        CompositionTarget.Rendering += self.handler", "        pass")),
    (rule_window_motion, _sub("nsq_ui.py", "first_frame=hide_real)", "first_frame=None)")),
    (rule_window_motion, _sub("nsq_window.py", "        ui.genie(tw, ui.screen_point(self.ctl(u\"TagOpenBtn\"), self.win), None, reverse=True)", "        tw.Opacity = 1.0")),
    (rule_window_motion, _sub("nsq_window.py", "on_close=self._close_tagwin)", ")")),
    (rule_window_motion, _sub("nsq_window.py", ', min_btn=self.ctl(u"MinBtn"))', ")")),
    (rule_window_motion, _sub("nsq_ui.py", '            p.SetResourceReference(Shape.StrokeProperty, u"Green")', '            p.SetResourceReference(Shape.StrokeProperty, u"Muted")')),
    (rule_window_motion, _sub("nsq_ui.py", "                g.PreviewMouseLeftButtonDown += self._on_edge_down\n", "                pass\n")),
    (rule_window_motion, _sub("NumberSequencer.xaml", 'Style="{DynamicResource SubStepText}" Text="6.2"', 'Style="{DynamicResource SubStepText}" Text="6"')),
    (rule_window_motion, _sub("NumberSequencer.xaml", 'x:Name="TagTabViews"', 'x:Name="TagTabView"')),
    (rule_window_motion, _sub("nsq_views.py", "        views = self._show_tag_tab()\n", "        views = False\n")),
    (rule_step_numbers, _sub("NumberSequencer.xaml", 'Style="{DynamicResource StepText}" Text="5"', 'Style="{DynamicResource StepText}" Text="6"')),
    (rule_step_numbers, _sub("Theme.xaml", '<Setter Property="FontWeight" Value="Bold"/>', '<Setter Property="FontWeight" Value="Normal"/>')),
    (rule_step_numbers, _sub("Theme.xaml", '<Setter Property="Foreground" Value="{DynamicResource Red}"/>\n        <Setter Property="FontWeight" Value="Bold"/>\n        <Setter Property="FontSize" Value="14"/>',
                             '<Setter Property="Foreground" Value="{DynamicResource OnAccent}"/>\n        <Setter Property="FontWeight" Value="Bold"/>\n        <Setter Property="FontSize" Value="14"/>')),
    (rule_window_follows_sections, _sub("nsq_ui.py", "            self._tell(-h)\n", "")),
    (rule_window_follows_sections, _sub("nsq_window.py", "key in shut, self._section_resize)", "key in shut)")),
    (rule_window_follows_sections, _sub("nsq_window.py", "            self._remember_size()\n", "            pass\n")),
    (rule_step_numbers, _sub("Theme.xaml", '<Setter Property="Background" Value="{DynamicResource OnAccent}"/>\n        <Setter Property="BorderBrush"',
                             '<Setter Property="Background" Value="{DynamicResource Blue}"/>\n        <Setter Property="BorderBrush"')),
    (rule_fold_all, _sub("nsq_window.py", "            self.fold_batch += delta   # Collapse / Expand all: one move for the lot\n            return\n", "            pass\n")),
    (rule_fold_all, _sub("nsq_window.py", "        self._section_resize(total)\n", "")),
    (rule_fold_all, _sub("nsq_window.py", "        self._refresh_shared()\n        self._refresh_fold_all()\n", "        self._refresh_shared()\n")),
    (rule_step_numbers, _sub("Theme.xaml", '<Setter Property="BorderBrush" Value="{DynamicResource Red}"/>\n        <Setter Property="BorderThickness" Value="2.5"/>', "")),
    (rule_tags_reach_every_category, _sub("nsq_revit.py", "IndependentTag.Create(doc, use[u\"id\"]", "IndependentTag.Create(doc, tag[u\"id\"]")),
    (rule_tags_reach_every_category, _sub("nsq_window.py", '                       u"untagged_only": bool(self.ctl(u"TagUntaggedCheck").IsChecked)}', "                       }")),
    (rule_tags_reach_every_category, _sub("nsq_window.py", '            self.ctl(u"TagCheck").IsChecked = True\n', "            pass\n")),
    (rule_tags_reach_every_category, _sub("nsq_views.py", "            self.sheet_num_w = self._fit_number(self.sheets)", "            self.sheet_num_w = 96.0")),
    (rule_tags_reach_every_category, _sub("nsq_views.py", "            self._resize_sheet_columns()\n        th.DragDelta", "            pass\n        th.DragDelta")),
    (rule_step_two, _sub("nsq_window.py", 'self.ctl(u"ApplyBtn").IsEnabled = ok and not waiting', 'self.ctl(u"ApplyBtn").IsEnabled = ok')),
    (rule_step_two, _sub("nsq_selector.py", 'STEP_PICK = u"2.3"', 'STEP_PICK = u"2"')),
    (rule_step_two, _sub("nsq_selector.py", 'u"Group systems", STEP_GROUP)', 'u"Group systems")')),
    (rule_step_two, _sub("nsq_selector.py", 'pick.SetResourceReference(FrameworkElement.StyleProperty, u"GreenFillButton")', 'pick.SetResourceReference(FrameworkElement.StyleProperty, u"GreenButton")')),
    (rule_step_two, _sub("nsq_ui.py", "        sp.Children.Add(step_badge(step))\n", "        pass\n")),
]


def run(files):
    problems = []
    for rule in RULES:
        try:
            for p in rule(files):
                problems.append((rule.__name__, p))
        except Exception as ex:
            problems.append((rule.__name__, "rule crashed: {0!r}".format(ex)))
    return problems


def selftest(files):
    failures = 0
    for rule, brk in BREAKAGES:
        copy = dict(files)
        try:
            copy = brk(copy)
        except AssertionError as ex:
            print("  BROKEN BREAKAGE  {0}: {1}".format(rule.__name__, ex))
            failures += 1
            continue
        try:
            found = rule(copy)
        except Exception as ex:
            found = ["crashed: {0!r}".format(ex)]
        if found:
            print("  caught  {0}: {1}".format(rule.__name__, found[0]))
        else:
            print("  MISSED  {0} did not fire on its breakage".format(rule.__name__))
            failures += 1
    untested = [r.__name__ for r in RULES if r not in [b[0] for b in BREAKAGES]]
    for u in untested:
        print("  UNTESTED  {0} has no breakage".format(u))
        failures += 1
    print("selftest: {0} breakages, {1} failures".format(len(BREAKAGES), failures))
    return failures


def main():
    sys.path.insert(0, HERE)
    files = load_files()
    problems = run(files)
    for name, p in problems:
        print("FAIL  {0}: {1}".format(name, p))
    print("import_check: {0} rules, {1} problems".format(len(RULES), len(problems)))
    rc = 1 if problems else 0
    if "--selftest" in sys.argv:
        if selftest(files):
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
