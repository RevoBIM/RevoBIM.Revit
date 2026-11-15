# -*- coding: utf-8 -*-
"""Find Room static bench - the rules that keep a pyRevit tool from opening
as a blank white window, or dying on one Revit release and not another.

    python import_check.py             run every rule on the shipped files
    python import_check.py --selftest  break the files on purpose, one rule at
                                       a time, and prove each rule catches it

Rules read CODE, not prose: docstrings and comments are stripped first, so a
rule cannot pass by matching its own explanation.
"""
import ast
import io
import os
import re
import shutil
import sys
import tempfile
import tokenize
from xml.dom import minidom

HERE = os.path.dirname(os.path.abspath(__file__))
MODULES = ["frm_clr", "frm_version", "frm_core", "frm_revit", "frm_runner",
           "frm_ui", "frm_window", "script"]
LAYOUTS = ["FindRoom.xaml"]
THEME = "Theme.xaml"

# namespace -> the assemblies that provide it (any one will do)
ASSEMBLY_FOR = {
    "System": ["System", "mscorlib"],
    "System.IO": ["mscorlib", "System"],
    "System.Collections.Generic": ["mscorlib", "System"],
    "System.Windows": ["PresentationFramework", "PresentationCore", "WindowsBase"],
    "System.Windows.Controls": ["PresentationFramework"],
    "System.Windows.Shapes": ["PresentationFramework"],
    "System.Windows.Input": ["PresentationCore", "WindowsBase"],
    "System.Windows.Threading": ["WindowsBase"],
    "System.Windows.Markup": ["PresentationFramework", "System.Xaml"],
    "System.Windows.Media": ["PresentationCore"],
    "System.Windows.Media.Imaging": ["PresentationCore"],
    "System.Windows.Interop": ["PresentationFramework", "PresentationCore"],
    "System.Windows.Forms": ["System.Windows.Forms"],
    "System.Data": ["System.Data"],
    "System.Xml": ["System.Xml"],
    "System.Drawing": ["System.Drawing"],
    "Autodesk.Revit.DB": ["(revit)"],
    "Autodesk.Revit.UI": ["(revit)"],
}

KNOWN_EXTENSIONS = ("{DynamicResource", "{Binding", "{TemplateBinding", "{StaticResource",
                    "{x:Null", "{RelativeSource", "{}")


# =============================================================================
# File set
# =============================================================================
class Files(object):
    """The tool's files as text, so a selftest can break a copy in memory."""

    def __init__(self, root):
        self.root = root
        self.text = {}
        for name in os.listdir(root):
            if name.endswith((".py", ".xaml", ".md", ".yaml")):
                with io.open(os.path.join(root, name), encoding="utf-8") as h:
                    self.text[name] = h.read()

    def copy(self):
        other = Files.__new__(Files)
        other.root = self.root
        other.text = dict(self.text)
        return other

    def py(self, mod):
        return self.text.get(mod + ".py", u"")


def code_only(source):
    """Source with comments and string literals blanked (docstrings included),
    keeping line structure - rules must look at code, never prose."""
    out = []
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except Exception:
        return source
    last = (1, 0)
    lines = source.splitlines(True)

    def take(a, b):
        if a[0] == b[0]:
            return lines[a[0] - 1][a[1]:b[1]] if a[0] - 1 < len(lines) else u""
        chunk = lines[a[0] - 1][a[1]:]
        for i in range(a[0], b[0] - 1):
            chunk += lines[i]
        chunk += lines[b[0] - 1][:b[1]] if b[0] - 1 < len(lines) else u""
        return chunk
    for tok in tokens:
        out.append(take(last, tok.start))
        if tok.type == tokenize.COMMENT:
            pass
        elif tok.type == tokenize.STRING:
            text = tok.string
            out.append(u"''" + u"\n" * text.count(u"\n"))
        else:
            out.append(tok.string)
        last = tok.end
    return u"".join(out)


# =============================================================================
# Rules - each returns a list of problems
# =============================================================================
def rule_xaml_parses(f):
    bad = []
    for name in LAYOUTS + [THEME]:
        try:
            minidom.parseString(f.text[name].encode("utf-8"))
        except Exception as exc:
            bad.append(u"{0} does not parse: {1}".format(name, exc))
    return bad


def rule_no_baseline(f):
    return [u"{0}: VerticalAlignment=Baseline kills XamlReader".format(n)
            for n in LAYOUTS + [THEME] if u'VerticalAlignment="Baseline"' in f.text[n]]


def rule_no_static_in_layout(f):
    return [u"{0}: StaticResource in a layout (Theme.xaml merges after it parses)".format(n)
            for n in LAYOUTS if u"StaticResource" in f.text[n]]


def _theme_keys(f):
    return set(re.findall(r'x:Key="([^"]+)"', f.text[THEME]))


def rule_dynamic_keys_defined(f):
    keys = _theme_keys(f)
    bad = []
    for n in LAYOUTS + [THEME]:
        for k in re.findall(r"\{DynamicResource ([^}\s]+)\}", f.text[n]):
            if k not in keys:
                bad.append(u"{0}: DynamicResource {1} not defined in Theme.xaml".format(n, k))
    return bad


def rule_style_targets(f):
    targets = dict(re.findall(r'<Style x:Key="([^"]+)" TargetType="([^"]+)"', f.text[THEME]))
    bad = []
    for n in LAYOUTS:
        for tag, key in re.findall(r'<(\w+)\b[^>]*?Style="\{DynamicResource ([^}]+)\}"', f.text[n]):
            want = targets.get(key)
            if want and want != tag:
                bad.append(u"{0}: <{1}> given style {2} for {3}".format(n, tag, key, want))
    return bad


def rule_markup_braces(f):
    bad = []
    for n in LAYOUTS + [THEME]:
        for value in re.findall(r'="(\{[^"]*)"', f.text[n]):
            if not value.startswith(KNOWN_EXTENSIONS):
                bad.append(u"{0}: attribute starting with an unescaped {{: {1}".format(n, value))
    return bad


def rule_findname(f):
    names = set(re.findall(r'x:Name="([^"]+)"', u"".join(f.text[n] for n in LAYOUTS)))
    src = f.py("frm_window") + f.py("frm_ui")
    wanted = set(re.findall(r'FindName\(\s*u?"([^"]+)"', src))
    block = re.search(r"for name in \((.*?)\):\s*\n\s*setattr", f.py("frm_window"), re.S)
    if block:
        wanted |= set(re.findall(r'u"(\w+)"', block.group(1)))
    grips = re.findall(r'u"(Grip\w+)"', f.py("frm_ui"))
    wanted |= set(grips)
    return [u"FindName({0}) has no x:Name in the layout".format(w) for w in sorted(wanted - names)]


def rule_palette_keys(f):
    keys = _theme_keys(f)
    core = f.py("frm_core")
    dark = re.search(r"DARK = \{(.*?)\}", core, re.S)
    light = re.search(r"LIGHT = \{(.*?)\}", core, re.S)
    bad = []
    if not dark or not light:
        return [u"palettes not found in frm_core"]
    dk = set(re.findall(r'u"(\w+)":', dark.group(1)))
    lk = set(re.findall(r'u"(\w+)":', light.group(1)))
    if dk != lk:
        bad.append(u"DARK and LIGHT differ: {0}".format(sorted(dk ^ lk)))
    for k in sorted(dk - keys):
        bad.append(u"palette key {0} has no brush in Theme.xaml".format(k))
    for mod in MODULES:
        for k in re.findall(r'SetResourceReference\([^,]+,\s*u?"(\w+)"', f.py(mod)):
            if k not in keys:
                bad.append(u"{0}: SetResourceReference key {1} not in Theme.xaml".format(mod, k))
        call = r'(?:_tb|_badge|self\.status)\((?:[^()]|\([^()]*\))*?,\s*u"(\w+)"'
        for k in re.findall(call, f.py(mod)):
            if k not in keys:
                bad.append(u"{0}: brush key {1} not in Theme.xaml".format(mod, k))
    return bad


def _imports(source):
    """[(line, namespace)] for every `from X import` / `import X` of System
    or Autodesk."""
    out = []
    try:
        tree = ast.parse(source)
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


def rule_clr_first(f):
    bad = []
    for mod in MODULES:
        if mod in ("frm_clr", "script"):
            continue
        src = f.py(mod)
        imps = _imports(src)
        if not imps:
            continue
        m = re.search(r"^import frm_clr\b", src, re.M)
        if not m:
            bad.append(u"{0} reaches into .NET without importing frm_clr".format(mod))
            continue
        clr_line = src[:m.start()].count(u"\n") + 1
        first = min(ln for ln, ns in imps)
        if first < clr_line:
            bad.append(u"{0}: .NET import on line {1} before frm_clr".format(mod, first))
    return bad


def rule_assemblies_referenced(f):
    listed = set(re.findall(r"'([\w.]+)'", re.search(
        r"_ASSEMBLIES = \[(.*?)\]", f.py("frm_clr"), re.S).group(1)))
    bad = []
    for mod in MODULES:
        for ln, ns in _imports(f.py(mod)):
            if ns in ("Autodesk.Revit.UI", "Autodesk.Revit.DB", "Autodesk.Revit"):
                continue
            want = ASSEMBLY_FOR.get(ns)
            if want is None:
                bad.append(u"{0}:{1} {2} missing from the ASSEMBLY_FOR table".format(mod, ln, ns))
            elif not listed.intersection(want):
                bad.append(u"{0}:{1} imports {2} but none of {3} is referenced".format(
                    mod, ln, ns, want))
    return bad


def _fstrings(source):
    """Line numbers holding an f-string, by token (3.12+ has FSTRING_START),
    falling back to the string prefix on older Pythons."""
    lines = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            name = tokenize.tok_name.get(tok.type, u"")
            if name == u"FSTRING_START":
                lines.append(tok.start[0])
            elif tok.type == tokenize.STRING and re.match(r"[rRbBuU]?[fF]", tok.string):
                lines.append(tok.start[0])
    except Exception:
        pass
    return lines


def rule_banned_code(f):
    bad = []
    for mod in MODULES:
        source = f.py(mod)
        for n in _fstrings(source):
            bad.append(u"{0}:{1} f-string (not IronPython 2.7)".format(mod, n))
        code = code_only(source)
        for n, line in enumerate(code.splitlines(), 1):
            if re.match(r"\s*print\s+[^(=]", line) or re.search(r"(?<![\w.])print\(", line):
                bad.append(u"{0}:{1} print".format(mod, n))
            if u"System.Uri" in line or re.search(r"\bimport\b.*\bUri\b", line) or \
                    u"UriSource" in line:
                bad.append(u"{0}:{1} System.Uri (moved in Revit 2025)".format(mod, n))
            if re.search(r"\bnonlocal\b", line):
                bad.append(u"{0}:{1} nonlocal (not IronPython 2.7)".format(mod, n))
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            bad.append(u"{0} does not parse: {1}".format(mod, exc))
            continue
        allowed = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "eid_value":
                allowed.append((node.lineno, max(getattr(n, "lineno", node.lineno)
                                                 for n in ast.walk(node))))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "IntegerValue":
                if not any(a <= node.lineno <= b for a, b in allowed):
                    bad.append(u"{0}:{1} .IntegerValue outside eid_value (gone in 2026)".format(
                        mod, node.lineno))
    return bad


def rule_ascii_source(f):
    """Non-ASCII in source depends on the coding line surviving every editor;
    write \\u escapes instead."""
    bad = []
    for mod in MODULES:
        for n, line in enumerate(f.py(mod).splitlines(), 1):
            if any(ord(ch) > 127 for ch in line):
                bad.append(u"{0}:{1} non-ASCII character in source".format(mod, n))
    return bad


def rule_no_duplicates(f):
    bad = []
    for mod in MODULES:
        tree = ast.parse(f.py(mod))
        for scope in [tree] + [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
            seen = set()
            for node in scope.body:
                if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                    if node.name in seen:
                        bad.append(u"{0}: {1} defined twice - the second silently wins".format(
                            mod, node.name))
                    seen.add(node.name)
    return bad


def rule_enum_members_at_call_time(f):
    """BuiltInCategory / BuiltInParameter members never read at module load."""
    bad = []
    for mod in MODULES:
        tree = ast.parse(f.py(mod))
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                continue
            for leaf in ast.walk(node):
                if isinstance(leaf, ast.Attribute) and isinstance(leaf.value, ast.Name) and \
                        leaf.value.id in ("BuiltInCategory", "BuiltInParameter"):
                    bad.append(u"{0}:{1} {2}.{3} read at module load".format(
                        mod, leaf.lineno, leaf.value.id, leaf.attr))
    return bad


def rule_loader(f):
    src = code_only(f.py("script"))
    bad = []
    if u"AddReference" in src:
        bad.append(u"script.py calls clr.AddReference - frm_clr owns them")
    if not re.search(r"^__persistentengine__\s*=\s*True", src, re.M):
        bad.append(u"script.py lacks __persistentengine__ = True (modeless window)")
    if u"_fail(" not in src:
        bad.append(u"script.py does not report the stage that failed")
    return bad


def rule_version(f):
    m = re.search(r'__version__\s*=\s*u?"([\d.]+)"', f.py("frm_version"))
    if not m:
        return [u"frm_version has no __version__"]
    v = m.group(1)
    bad = []
    if u"## {0}".format(v) not in f.text.get("CHANGELOG.md", u""):
        bad.append(u"CHANGELOG.md has no entry for {0}".format(v))
    if re.search(r'Text="v\d', f.text["FindRoom.xaml"]) and \
            u"VersionText.Text" not in code_only(f.py("frm_window")).replace(u"''", u""):
        bad.append(u"the window shows a hard-coded version")
    for mod in MODULES:
        if mod != "frm_version" and re.search(r"^__version__\s*=", f.py(mod), re.M):
            bad.append(u"{0} writes its own __version__ - frm_version is the only place".format(mod))
    return bad


def rule_runner_never_clears(f):
    tree = ast.parse(f.py("frm_runner"))
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "submit":
            for leaf in ast.walk(node):
                if isinstance(leaf, ast.Assign):
                    for t in leaf.targets:
                        if isinstance(t, ast.Attribute) and t.attr == "queue":
                            bad.append(u"Runner.submit reassigns the queue - a Pending job is lost")
                if isinstance(leaf, ast.Call) and isinstance(leaf.func, ast.Attribute) and \
                        leaf.func.attr == "clear":
                    bad.append(u"Runner.submit clears the queue")
    return bad


def rule_canvas_not_truthy(f):
    code = code_only(f.py("frm_revit"))
    m = re.search(r"def canvas_theme.*?(?=\ndef )", code, re.S)
    if not m:
        return [u"canvas_theme not found"]
    body = m.group(0)
    bad = []
    if re.search(r"if\s+value\s*:", body) or re.search(r"\bor\b", body.split(u"mgr = getattr")[-1]):
        bad.append(u"canvas_theme tests the theme by truthiness - UITheme.Dark is 0")
    if u"CurrentCanvasTheme" not in f.py("frm_revit"):
        bad.append(u"canvas theme not read from UIThemeManager.CurrentCanvasTheme")
    if re.search(r"^from Autodesk\.Revit\.UI import .*UIThemeManager", f.py("frm_revit"), re.M):
        bad.append(u"UIThemeManager imported at load - it only exists from 2024")
    return bad


def rule_egg_logo_only(f):
    code = code_only(f.py("frm_ui")) + code_only(f.py("frm_window"))
    bad = []
    if re.search(r"egg_hook\.attach", code):
        bad.append(u"egg_hook.attach arms the whole window - launch from the logo only")
    if u"egg_hook.launch(" not in code:
        bad.append(u"easter egg not wired to egg_hook.launch")
    if u"self.egg.reset()" not in code:
        bad.append(u"egg count never resets on clicks elsewhere")
    return bad


def rule_no_shared_files(f):
    """Nothing outside the tool's own folder that another delivery owns."""
    ext = os.path.abspath(os.path.join(f.root, u"..", u"..", u"..", u".."))
    bad = []
    if not ext.endswith(u".extension"):
        return bad
    for dirpath, dirs, files in os.walk(ext):
        rel = os.path.relpath(dirpath, ext)
        for name in files:
            p = os.path.join(rel, name)
            if name in ("startup.py",) or rel.startswith(u"hooks") or \
                    (name == "__init__.py" and u"revobim" in rel) or \
                    (name == "bundle.yaml" and (rel.endswith(u".panel") or rel.endswith(u".pulldown"))):
                bad.append(u"ships shared file {0}".format(p))
    return bad


def rule_modules_load(f):
    """Every module imports against the stub API - names in the namespace the
    real API puts them, so a mis-namespaced import fails here."""
    tmp = tempfile.mkdtemp()
    try:
        for name, text in f.text.items():
            with io.open(os.path.join(tmp, name), "w", encoding="utf-8") as h:
                h.write(text)
        shutil.copy(os.path.join(HERE, "bench_stubs.py"), os.path.join(tmp, "bench_stubs.py"))
        for k in list(sys.modules):
            if k.startswith("frm_") or k == "bench_stubs":
                del sys.modules[k]
        sys.path.insert(0, tmp)
        bad = []
        try:
            import bench_stubs  # noqa: F401
            for mod in MODULES:
                if mod == "script":
                    continue
                try:
                    __import__(mod)
                except Exception as exc:
                    bad.append(u"{0} failed to load: {1}: {2}".format(mod, type(exc).__name__, exc))
        finally:
            sys.path.remove(tmp)
            for k in list(sys.modules):
                if k.startswith("frm_") or k == "bench_stubs":
                    del sys.modules[k]
        return bad
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


RULES = [rule_xaml_parses, rule_no_baseline, rule_no_static_in_layout,
         rule_dynamic_keys_defined, rule_style_targets, rule_markup_braces, rule_findname,
         rule_palette_keys, rule_clr_first, rule_assemblies_referenced, rule_banned_code,
         rule_ascii_source, rule_no_duplicates, rule_enum_members_at_call_time, rule_loader, rule_version,
         rule_runner_never_clears, rule_canvas_not_truthy, rule_egg_logo_only,
         rule_no_shared_files, rule_modules_load]


# =============================================================================
# Selftest - every rule must catch its own breakage
# =============================================================================
def _sub(name, old, new):
    def brk(f):
        if old not in f.text[name]:
            raise RuntimeError(u"breakage text missing in {0}: {1!r}".format(name, old))
        f.text[name] = f.text[name].replace(old, new, 1)
    return brk


BREAKAGES = [
    (rule_xaml_parses, _sub("FindRoom.xaml", u"<!-- ========== Header ========== -->",
                            u"<!-- ---------- Header ---------- -->")),
    (rule_xaml_parses, _sub("Theme.xaml", u"</ResourceDictionary>", u"")),
    (rule_no_baseline, _sub("FindRoom.xaml", u'Text="Find Room" FontSize="15"',
                            u'Text="Find Room" VerticalAlignment="Baseline" FontSize="15"')),
    (rule_no_static_in_layout, _sub("FindRoom.xaml", u'Style="{DynamicResource ChipButton}"',
                                    u'Style="{StaticResource ChipButton}"')),
    (rule_dynamic_keys_defined, _sub("FindRoom.xaml", u'Foreground="{DynamicResource Orange}"/>',
                                     u'Foreground="{DynamicResource Orang}"/>')),
    (rule_style_targets, _sub("FindRoom.xaml", u'<Button x:Name="RefreshBtn" DockPanel.Dock="Right" Style="{DynamicResource GhostButton}"',
                              u'<Button x:Name="RefreshBtn" DockPanel.Dock="Right" Style="{DynamicResource SegRadio}"')),
    (rule_markup_braces, _sub("FindRoom.xaml", u'Tag="Search plans"', u'Tag="{Plan} name"')),
    (rule_findname, _sub("FindRoom.xaml", u'x:Name="ViewsEmpty"', u'x:Name="ViewsEmptyX"')),
    (rule_findname, _sub("FindRoom.xaml", u'x:Name="GripSE"', u'x:Name="GripSEX"')),
    (rule_palette_keys, _sub("frm_core.py", u'u"Overlay": u"#CCF3F3F5",', u'')),
    (rule_palette_keys, _sub("Theme.xaml", u'<SolidColorBrush x:Key="LevelBg" Color="#29292D"/>', u'')),
    (rule_palette_keys, _sub("frm_window.py", u'_tb(core.format_elev(row.elev), u"Faint"',
                             u'_tb(core.format_elev(row.elev), u"Faintt"')),
    (rule_clr_first, _sub("frm_window.py", u"import frm_clr  # noqa: F401 - assemblies first, always\n", u"")),
    (rule_clr_first, _sub("frm_runner.py",
                          u"import frm_clr  # noqa: F401 - assemblies first, always\n\nfrom System import Action, TimeSpan",
                          u"from System import Action, TimeSpan\nimport frm_clr  # noqa: F401")),
    (rule_assemblies_referenced, _sub("frm_clr.py", u"'System.Windows.Forms', ", u"")),
    (rule_assemblies_referenced, _sub("frm_clr.py", u"'WindowsBase',", u"")),
    (rule_banned_code, _sub("frm_core.py", u'return u"{0:.1f} m\\u00b2".format(value)',
                            u'return f"{value:.1f} m2"')),
    (rule_banned_code, _sub("frm_revit.py", u"def bic(name):",
                            u"def _bad(e):\n    return e.Id.IntegerValue\n\n\ndef bic(name):")),
    (rule_banned_code, _sub("frm_ui.py", u"img.StreamSource = MemoryStream(File.ReadAllBytes(path))",
                            u"img.UriSource = path")),
    (rule_banned_code, _sub("frm_ui.py", u"def write_error(text):",
                            u"def _p(x):\n    print(x)\n\n\ndef write_error(text):")),
    (rule_ascii_source, _sub("frm_core.py", u'return u"{0:.1f} m\\u00b2".format(value)',
                             u'return u"{0:.1f} m\u00b2".format(value)')),
    (rule_no_duplicates, _sub("frm_window.py", u"    def _view_by_key(self, key):",
                              u"    def fill_views(self):\n        pass\n\n    def _view_by_key(self, key):")),
    (rule_enum_members_at_call_time, _sub("frm_revit.py", u'FILTER_NAME = u"RevoBIM Find Room"',
                                          u'FILTER_NAME = u"RevoBIM Find Room"\n_ROOMS = BuiltInCategory.OST_Rooms')),
    (rule_loader, _sub("script.py", u"__persistentengine__ = True", u"__persistentengine__ = False")),
    (rule_loader, _sub("script.py", u"import os\n", u"import os\nimport clr\nclr.AddReference('RevitAPI')\n")),
    (rule_version, _sub("CHANGELOG.md", u"## 1.0.0", u"## 0.9.0")),
    (rule_version, _sub("frm_window.py", u"WINDOW_KEY = ", u"__version__ = u\"9.9.9\"\nWINDOW_KEY = ")),
    (rule_runner_never_clears, _sub("frm_runner.py", u"            self.queue.remove(job)",
                                    u"            self.queue = []")),
    (rule_canvas_not_truthy, _sub("frm_revit.py",
                                  u"if value is not None:\n                found = core.theme_from_text",
                                  u"if value:\n                found = core.theme_from_text")),
    (rule_egg_logo_only, _sub("frm_window.py", u"                self.egg.reset()",
                              u"                pass")),
    (rule_egg_logo_only, _sub("frm_ui.py", u'egg_hook.launch(self.window, self.theme_getter(), "pacman")',
                              u'egg_hook.attach(self.window)')),
    (rule_modules_load, _sub("frm_window.py", u"from System.Windows.Shapes import Path",
                             u"from System.Windows import Path")),
    (rule_modules_load, _sub("frm_revit.py", u"    Category, WorksharingUtils,",
                             u"    Category, WorksharingUtils, ViewSheetSetting,")),
]


def run(f, rules=None, quiet=False):
    failed = 0
    for rule in rules or RULES:
        problems = rule(f)
        if problems:
            failed += 1
        if not quiet:
            print(u"  {0:5} {1}".format(u"ok" if not problems else u"FAIL", rule.__name__))
            for p in problems:
                print(u"        - " + p)
    return failed


def selftest(f):
    # the shared-files rule needs a real tree: build one with a stray startup.py
    print(u"selftest: {0} deliberate breakages".format(len(BREAKAGES) + 1))
    bad = 0
    for rule, brk in BREAKAGES:
        g = f.copy()
        try:
            brk(g)
        except Exception as exc:
            print(u"  ERROR  {0}: {1}".format(rule.__name__, exc))
            bad += 1
            continue
        problems = rule(g)
        print(u"  {0} {1}{2}".format(u"caught " if problems else u"MISSED ", rule.__name__,
                                     u"  <- " + problems[0][:90] if problems else u""))
        if not problems:
            bad += 1
    tmp = tempfile.mkdtemp()
    try:
        tool = os.path.join(tmp, u"X.extension", u"X.tab", u"P.panel", u"R.pulldown", u"T.pushbutton")
        os.makedirs(tool)
        open(os.path.join(tmp, u"X.extension", u"startup.py"), "w").close()
        g = f.copy()
        g.root = tool
        problems = rule_no_shared_files(g)
        print(u"  {0} rule_no_shared_files".format(u"caught " if problems else u"MISSED "))
        if not problems:
            bad += 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if run(f, quiet=True):
        print(u"  the clean files no longer pass")
        bad += 1
    return bad


def main():
    f = Files(HERE)
    if "--selftest" in sys.argv:
        bad = selftest(f)
        print(u"selftest {0}".format(u"FAILED ({0})".format(bad) if bad else u"passed"))
        return 1 if bad else 0
    print(u"import_check: {0} rules".format(len(RULES)))
    failed = run(f)
    print(u"{0} rule(s) failed".format(failed) if failed else u"all passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
