# -*- coding: utf-8 -*-
"""Tag Aligner import_check: static rules over the shipped files, plus a load
of every module against the stub Revit and .NET API.

    python import_check.py            run every rule
    python import_check.py --selftest break each rule on purpose and prove
                                      the rule catches it

Rules work on an in-memory copy of the sources, so a selftest breakage never
touches the files on disk. A rule that passes its own breakage is inert and
the selftest fails.
"""
from __future__ import print_function

import ast
import io
import os
import re
import sys
import tempfile
import tokenize
import xml.dom.minidom

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.dirname(HERE)
EXT = os.path.dirname(os.path.dirname(os.path.dirname(LIB)))
PANEL = os.path.join(EXT, "RevoBIM PY.tab", "Annotation.panel")
STACKS = ("Tag Align.stack", "Tag Untangle.stack")

MODULES = ("ta_clr", "ta_core", "ta_theme", "ta_model", "ta_ops", "ta_ui",
           "ta_run")
XAMLS = ("TagAlignerTheme.xaml", "TagAlignerSettings.xaml",
         "TagAlignerResults.xaml")

# namespace -> assemblies that provide it (any one being referenced is enough)
ASSEMBLY_FOR = {
    "System": ["System", "mscorlib"],
    "System.IO": ["mscorlib", "System"],
    "System.Collections.Generic": ["mscorlib", "System"],
    "System.Diagnostics": ["System"],
    "System.Windows": ["PresentationFramework", "PresentationCore", "WindowsBase"],
    "System.Windows.Controls": ["PresentationFramework"],
    "System.Windows.Interop": ["PresentationFramework"],
    "System.Windows.Markup": ["PresentationFramework", "System.Xaml"],
    "System.Windows.Media": ["PresentationCore"],
    "System.Windows.Media.Imaging": ["PresentationCore"],
    "System.Windows.Input": ["PresentationCore"],
}

# modules allowed to import Autodesk.* lazily without ta_clr: ta_run must be
# able to report a failure of ta_clr itself.
CLR_EXEMPT = ("ta_clr", "ta_run")

ENUMS = {
    "VerticalAlignment": {"Top", "Center", "Bottom", "Stretch"},
    "HorizontalAlignment": {"Left", "Center", "Right", "Stretch"},
    "Visibility": {"Visible", "Collapsed", "Hidden"},
    "Orientation": {"Horizontal", "Vertical"},
    "TextWrapping": {"Wrap", "NoWrap", "WrapWithOverflow"},
    "TextTrimming": {"None", "CharacterEllipsis", "WordEllipsis"},
    "WindowStyle": {"None", "SingleBorderWindow", "ThreeDBorderWindow", "ToolWindow"},
    "ResizeMode": {"NoResize", "CanMinimize", "CanResize", "CanResizeWithGrip"},
    "SizeToContent": {"Manual", "Width", "Height", "WidthAndHeight"},
    "WindowStartupLocation": {"Manual", "CenterScreen", "CenterOwner"},
    "DockPanel.Dock": {"Left", "Top", "Right", "Bottom"},
    "FontWeight": {"Thin", "Light", "Normal", "Medium", "SemiBold", "Bold", "ExtraBold", "Black"},
    "VerticalScrollBarVisibility": {"Auto", "Disabled", "Hidden", "Visible"},
    "HorizontalScrollBarVisibility": {"Auto", "Disabled", "Hidden", "Visible"},
    "Cursor": {"Hand", "Arrow", "IBeam", "SizeAll", "SizeNS", "SizeWE"},
}

SHARED_FORBIDDEN = (
    "startup.py",
    os.path.join("lib", "revobim", "__init__.py"),
    os.path.join("RevoBIM PY.tab", "Annotation.panel", "bundle.yaml"),
    "hooks",
)


# ==========================================================================
# Sources: everything the rules read, as text, so breakages stay in memory
# ==========================================================================

class Sources(object):
    def __init__(self):
        self.files = {}
        for root, dirs, names in os.walk(EXT):
            for n in names:
                p = os.path.join(root, n)
                rel = os.path.relpath(p, EXT)
                if n.endswith((".py", ".xaml", ".yaml", ".md")):
                    with io.open(p, "r", encoding="utf-8") as h:
                        self.files[rel] = h.read()
                else:
                    self.files[rel] = None
        self.extra_paths = []

    def copy(self):
        c = Sources.__new__(Sources)
        c.files = dict(self.files)
        c.extra_paths = list(self.extra_paths)
        return c

    def lib(self, name):
        return os.path.join("lib", "revobim", "tagaligner", name)

    def module(self, mod):
        return self.files[self.lib(mod + ".py")]

    def set_module(self, mod, text):
        self.files[self.lib(mod + ".py")] = text

    def xaml(self, name):
        return self.files[self.lib(name)]

    def set_xaml(self, name, text):
        self.files[self.lib(name)] = text

    def scripts(self):
        return dict((k, v) for k, v in self.files.items()
                    if k.endswith("script.py"))

    def bundles(self):
        return dict((k, v) for k, v in self.files.items()
                    if k.endswith(".pushbutton" + os.sep + "bundle.yaml"))

    def paths(self):
        return list(self.files) + self.extra_paths


def code_only(text):
    """Source with every string and comment blanked, so prose can never
    satisfy or break a rule."""
    out = []
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except Exception:
        return text
    skip = {tokenize.COMMENT, tokenize.STRING}
    for t in toks:
        if t.type in skip or t.type == getattr(tokenize, "FSTRING_MIDDLE", -1):
            out.append(("''" if t.type == tokenize.STRING else ""))
        else:
            out.append(t.string)
        out.append(" ")
    return "".join(out)


def tree(text):
    return ast.parse(text)


# ==========================================================================
# Python rules
# ==========================================================================

def rule_no_fstrings(src):
    bad = []
    for mod in MODULES:
        for t in tokenize.generate_tokens(io.StringIO(src.module(mod)).readline):
            if t.type == getattr(tokenize, "FSTRING_START", -99):
                bad.append("{0}: f-string at line {1}".format(mod, t.start[0]))
            elif t.type == tokenize.STRING:
                prefix = re.match(r"^[A-Za-z]*", t.string).group(0).lower()
                if "f" in prefix:
                    bad.append("{0}: f-string at line {1}".format(mod, t.start[0]))
    return bad


def rule_no_print(src):
    bad = []
    for mod in MODULES:
        for node in ast.walk(tree(src.module(mod))):
            if isinstance(node, ast.Name) and node.id == "print":
                bad.append("{0}: print at line {1}".format(mod, node.lineno))
    return bad


def rule_no_bare_integervalue(src):
    bad = []
    for mod in MODULES:
        t = tree(src.module(mod))
        allowed = set()
        for node in ast.walk(t):
            if isinstance(node, ast.FunctionDef) and node.name == "eid_value":
                for sub in ast.walk(node):
                    allowed.add(id(sub))
        for node in ast.walk(t):
            if isinstance(node, ast.Attribute) and node.attr == "IntegerValue" \
                    and id(node) not in allowed:
                bad.append("{0}: .IntegerValue at line {1}".format(mod, node.lineno))
    return bad


def rule_no_system_uri(src):
    bad = []
    for mod in MODULES:
        for node in ast.walk(tree(src.module(mod))):
            if isinstance(node, ast.ImportFrom) and node.module == "System" and \
                    any(a.name == "Uri" for a in node.names):
                bad.append("{0}: from System import Uri".format(mod))
            if isinstance(node, ast.Attribute) and node.attr in ("Uri", "UriSource"):
                bad.append("{0}: {1} at line {2}".format(mod, node.attr, node.lineno))
    return bad


def rule_bip_at_call_time(src):
    bad = []
    for mod in MODULES:
        for node in ast.walk(tree(src.module(mod))):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
                    and node.value.id in ("BuiltInParameter", "BuiltInCategory"):
                bad.append("{0}: {1}.{2} read directly at line {3}".format(
                    mod, node.value.id, node.attr, node.lineno))
    return bad


def _imports(t, top_only):
    """[(lineno, module name)] of imports."""
    out = []
    nodes = t.body if top_only else ast.walk(t)
    for node in nodes:
        if isinstance(node, ast.Import):
            for a in node.names:
                out.append((node.lineno, a.name))
        elif isinstance(node, ast.ImportFrom):
            out.append((node.lineno, node.module or ""))
    return out


def rule_clr_first(src):
    bad = []
    for mod in MODULES:
        if mod in CLR_EXEMPT:
            continue
        t = tree(src.module(mod))
        every = _imports(t, False)
        dotnet = [ln for ln, name in every
                  if name.split(".")[0] in ("System", "Autodesk")]
        if not dotnet:
            continue
        clr_lines = [ln for ln, name in _imports(t, True) if name == "ta_clr"]
        if not clr_lines:
            bad.append("{0}: imports .NET/Revit but never imports ta_clr".format(mod))
        elif clr_lines[0] > min(dotnet):
            bad.append("{0}: ta_clr imported at line {1}, after a .NET import at "
                       "line {2}".format(mod, clr_lines[0], min(dotnet)))
    return bad


def _clr_assemblies(src):
    t = tree(src.module("ta_clr"))
    for node in t.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(x, ast.Name) and x.id == "_ASSEMBLIES" for x in node.targets):
            return [e.value for e in node.value.elts]
    return []


def rule_assemblies_referenced(src):
    have = set(_clr_assemblies(src))
    bad = []
    for mod in MODULES:
        for _, name in _imports(tree(src.module(mod)), False):
            if not name.startswith("System"):
                continue
            providers = ASSEMBLY_FOR.get(name)
            if providers is None:
                bad.append("{0}: namespace {1} missing from ASSEMBLY_FOR".format(mod, name))
            elif not have.intersection(providers):
                bad.append("{0}: {1} needs one of {2} referenced in ta_clr".format(
                    mod, name, providers))
    return bad


def rule_no_duplicate_defs(src):
    bad = []
    for mod in MODULES:
        t = tree(src.module(mod))
        bodies = [("module", t.body)] + [(n.name, n.body) for n in ast.walk(t)
                                         if isinstance(n, ast.ClassDef)]
        for owner, body in bodies:
            seen = {}
            for n in body:
                if isinstance(n, (ast.FunctionDef, ast.ClassDef)):
                    if n.name in seen:
                        bad.append("{0}: {1}.{2} defined twice (lines {3}, {4})".format(
                            mod, owner, n.name, seen[n.name], n.lineno))
                    seen[n.name] = n.lineno
    return bad


def rule_canvas_theme_not_truthy(src):
    """UITheme.Dark is 0: a truthiness test reads Dark as 'no reading'."""
    bad = []
    t = tree(src.module("ta_theme"))
    for fn in ast.walk(t):
        if not (isinstance(fn, ast.FunctionDef) and fn.name == "canvas_is_dark"):
            continue
        for node in ast.walk(fn):
            tests = []
            if isinstance(node, (ast.If, ast.IfExp, ast.While)):
                tests.append(node.test)
            if isinstance(node, ast.BoolOp):
                tests.extend(node.values)
            for test in tests:
                if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
                    test = test.operand
                if isinstance(test, ast.Name) and test.id == "theme":
                    bad.append("ta_theme.canvas_is_dark tests 'theme' for "
                               "truthiness at line {0}".format(node.lineno))
        if "is not None" not in ast.get_source_segment(src.module("ta_theme"), fn):
            bad.append("ta_theme.canvas_is_dark has no 'is not None' test")
    return bad


def _calls_in(fn, name):
    out = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            f = node.func
            n = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
            if n == name:
                out.append(node.lineno)
    return out


def _fn(t, name):
    for node in ast.walk(t):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def rule_head_before_elbow(src):
    """Read elbows, set the head, THEN write elbows (Tag All lesson)."""
    fn = _fn(tree(src.module("ta_model")), "move_tag")
    if fn is None:
        return ["ta_model.move_tag missing"]
    head = [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Assign) and any(
        isinstance(x, ast.Attribute) and x.attr == "TagHeadPosition" for x in n.targets)]
    reads = _calls_in(fn, "read_elbows")
    writes = _calls_in(fn, "write_elbow")
    if not head or not reads or not writes:
        return ["ta_model.move_tag must read elbows, set TagHeadPosition and write elbows"]
    bad = []
    if min(reads) > min(head):
        bad.append("move_tag reads elbows after moving the head")
    if min(writes) < min(head):
        bad.append("move_tag writes an elbow before moving the head")
    return bad


def rule_measure_with_leaders_off(src):
    fn = _fn(tree(src.module("ta_model")), "measure_boxes")
    if fn is None:
        return ["ta_model.measure_boxes missing"]
    code = code_only(ast.get_source_segment(src.module("ta_model"), fn))
    bad = []
    for needle, why in (("SubTransaction (", "no SubTransaction"),
                        ("HasLeader = False", "leaders are not switched off"),
                        ("Regenerate (", "no Regenerate before reading boxes"),
                        ("RollBack (", "SubTransaction is not rolled back")):
        if needle not in code:
            bad.append("measure_boxes: " + why)
    return bad


def rule_family_reads_before_transaction(src):
    """EditFamily and CheckoutElements cannot run inside a transaction."""
    fn = _fn(tree(src.module("ta_ops")), "run")
    tx = _calls_in(fn, "Transaction")
    th = _calls_in(fn, "text_height")
    co = _calls_in(fn, "checkout")
    if not tx or not th or not co:
        return ["ta_ops.run must call text_height, checkout and Transaction"]
    bad = []
    if max(th) > min(tx):
        bad.append("text_height (EditFamily) called after the Transaction is made")
    if max(co) > min(tx):
        bad.append("checkout called after the Transaction is made")
    return bad


def rule_handlers_guarded(src):
    """Every WPF handler (sender, args) wraps its body in try."""
    bad = []
    t = tree(src.module("ta_ui"))
    for node in ast.walk(t):
        if isinstance(node, ast.FunctionDef):
            names = [a.arg for a in node.args.args]
            if names[-2:] == ["sender", "args"]:
                body = [b for b in node.body if not (
                    isinstance(b, ast.Expr) and isinstance(getattr(b, "value", None), ast.Constant))]
                ok = len(body) == 1 and isinstance(body[0], ast.Try)
                # a handler that only calls a guarded method is fine
                if not ok and len(body) == 1 and isinstance(body[0], ast.Expr) and \
                        isinstance(body[0].value, ast.Call):
                    ok = True
                if not ok:
                    bad.append("ta_ui.{0} at line {1} is not wrapped in try".format(
                        node.name, node.lineno))
    return bad


def rule_version_in_changelog(src):
    m = re.search(r'__version__\s*=\s*u?"([0-9.]+)"', src.module("ta_core"))
    if not m:
        return ["ta_core has no __version__"]
    log = src.files.get(src.lib("CHANGELOG.md"))
    if not log:
        return ["CHANGELOG.md missing beside the modules"]
    first = re.search(r"^##\s+v?([0-9.]+)", log, re.M)
    if not first or first.group(1) != m.group(1):
        return ["CHANGELOG top entry {0} != __version__ {1}".format(
            first.group(1) if first else None, m.group(1))]
    return []


def rule_no_shared_files(src):
    bad = []
    for rel in src.paths():
        for f in SHARED_FORBIDDEN:
            if rel == f or rel.startswith(f + os.sep):
                bad.append("ships shared file {0}; ship a banded fragment instead".format(rel))
    return bad


def rule_loaders(src):
    bad = []
    commands = re.search(r"COMMANDS = \(([^)]*)\)", src.module("ta_run")).group(1)
    for rel, text in src.scripts().items():
        code = code_only(text)
        if "AddReference" in code:
            bad.append("{0}: clr.AddReference in a loader".format(rel))
        m = re.search(r'ta_run\.main\(u?"([a-z_]+)"', text)
        if not m or ('"' + m.group(1) + '"') not in commands:
            bad.append("{0}: does not call ta_run.main with a known command".format(rel))
        if not text.startswith("# -*- coding: utf-8 -*-"):
            bad.append("{0}: missing coding line".format(rel))
    return bad


def rule_bundles(src):
    bad = []
    titles = {}
    for rel, text in src.bundles().items():
        m = re.search(r"^title:\s*(.+)$", text, re.M)
        if not m:
            bad.append("{0}: no title".format(rel))
            continue
        title = m.group(1).strip()
        if "\\n" in title or len(title) > 32:
            bad.append("{0}: title must be single line and short".format(rel))
        folder = os.path.basename(os.path.dirname(rel)).replace(".pushbutton", "")
        if title != folder:
            bad.append("{0}: title '{1}' differs from folder '{2}'".format(rel, title, folder))
        if title in titles:
            bad.append("{0}: duplicate title {1}".format(rel, title))
        titles[title] = rel
        if not title.startswith("Tag "):
            bad.append("{0}: title must start 'Tag ' to be findable in Keyboard Shortcuts".format(rel))
        base = os.path.dirname(rel)
        for icon in ("icon.png", "icon.dark.png"):
            if os.path.join(base, icon) not in src.files:
                bad.append("{0}: missing {1}".format(base, icon))
    for stack in STACKS:
        y = src.files.get(os.path.join("RevoBIM PY.tab", "Annotation.panel", stack, "bundle.yaml"))
        listed = re.findall(r"^\s*-\s*(.+)$", y or "", re.M)
        present = sorted(os.path.basename(os.path.dirname(k)).replace(".pushbutton", "")
                         for k in src.bundles() if (os.sep + stack + os.sep) in (os.sep + k))
        if sorted(x.strip() for x in listed) != present:
            bad.append("{0}: layout {1} != buttons {2}".format(stack, listed, present))
        if len(present) > 3:
            bad.append("{0}: a stack holds at most 3 buttons".format(stack))
    return bad


def rule_names_defined(src):
    """Every name read is bound somewhere in the module or is a builtin.
    Scope-blind, but it catches a dropped import, which otherwise only shows
    up as a NameError in Revit halfway through a run."""
    try:
        import builtins
        known_builtins = set(dir(builtins))
    except ImportError:
        import __builtin__
        known_builtins = set(dir(__builtin__))
    known_builtins.update(["__revit__", "__file__", "unicode", "basestring"])
    bad = []
    for mod in MODULES:
        t = tree(src.module(mod))
        bound = set()
        for node in ast.walk(t):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for a in node.names:
                    bound.add((a.asname or a.name).split(".")[0])
            elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                bound.add(node.name)
            elif isinstance(node, ast.arg):
                bound.add(node.arg)
            elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
                bound.add(node.id)
            elif isinstance(node, ast.ExceptHandler) and node.name:
                bound.add(node.name)
        for node in ast.walk(t):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and \
                    node.id not in bound and node.id not in known_builtins:
                bad.append("{0}: name {1} is never defined (line {2})".format(
                    mod, node.id, node.lineno))
    return bad


# ==========================================================================
# XAML rules
# ==========================================================================

def _dom(text):
    return xml.dom.minidom.parseString(text.encode("utf-8"))


def rule_xaml_parses(src):
    bad = []
    for name in XAMLS:
        try:
            _dom(src.xaml(name))
        except Exception as ex:
            bad.append("{0}: {1}".format(name, ex))
    return bad


def rule_no_static_resource(src):
    return ["{0}: StaticResource used".format(n) for n in XAMLS
            if "StaticResource" in src.xaml(n)]


def _elements(text):
    try:
        return _dom(text).getElementsByTagName("*")
    except Exception:
        return []


def rule_enum_values(src):
    bad = []
    for name in XAMLS:
        for el in _elements(src.xaml(name)):
            pairs = [(k, el.getAttribute(k)) for k in ENUMS if el.hasAttribute(k)]
            if el.tagName == "Setter" and el.getAttribute("Property") in ENUMS:
                v = el.getAttribute("Value")
                if not v.startswith("{"):
                    pairs.append((el.getAttribute("Property"), v))
            for k, v in pairs:
                if v not in ENUMS[k]:
                    bad.append("{0}: {1}=\"{2}\" is not a valid value".format(name, k, v))
    return bad


def _theme_keys(src):
    keys = {}
    for el in _elements(src.xaml("TagAlignerTheme.xaml")):
        if el.hasAttribute("x:Key"):
            keys[el.getAttribute("x:Key")] = el
    return keys


def _palettes(src):
    t = tree(src.module("ta_theme"))
    for node in t.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(x, ast.Name) and x.id == "PALETTES" for x in node.targets):
            return ast.literal_eval(node.value)
    return {}


def rule_dynamic_keys_defined(src):
    keys = set(_theme_keys(src))
    pal = _palettes(src)
    for p in pal.values():
        keys.update(p)
    bad = []
    for name in XAMLS:
        for k in re.findall(r"\{DynamicResource\s+([A-Za-z0-9_]+)\}", src.xaml(name)):
            if k not in keys:
                bad.append("{0}: DynamicResource {1} is defined nowhere".format(name, k))
    code = src.module("ta_ui")
    for k in re.findall(r'SetResourceReference\([^,]+,\s*u?"([A-Za-z]+)"', code):
        if k not in keys:
            bad.append("ta_ui: SetResourceReference key {0} undefined".format(k))
    level_keys = re.search(r"LEVEL_KEYS = \{([^}]*)\}", code)
    for k in re.findall(r'u"([A-Za-z]+)"', level_keys.group(1) if level_keys else ""):
        if k[0].isupper() and k not in keys:
            bad.append("ta_ui: LEVEL_KEYS colour {0} undefined".format(k))
    return bad


def rule_palettes_complete(src):
    pal = _palettes(src)
    keys = _theme_keys(src)
    bad = []
    if set(pal.get(u"dark", {})) != set(pal.get(u"light", {})):
        bad.append("dark and light palettes have different keys")
    for mode, p in pal.items():
        for k in p:
            if k not in keys or keys[k].tagName != "SolidColorBrush":
                bad.append("palette key {0} has no SolidColorBrush in Theme.xaml".format(k))
    return bad


def rule_style_targets(src):
    keys = _theme_keys(src)
    bad = []
    for name in XAMLS:
        for el in _elements(src.xaml(name)):
            m = re.match(r"\{DynamicResource\s+(\w+)\}", el.getAttribute("Style") or "")
            if not m:
                continue
            style = keys.get(m.group(1))
            if style is None or style.getAttribute("TargetType") != el.tagName:
                bad.append("{0}: <{1}> uses style {2} for TargetType {3}".format(
                    name, el.tagName, m.group(1),
                    style.getAttribute("TargetType") if style else None))
    return bad


def _xaml_names(src, name):
    return set(el.getAttribute("x:Name") for el in _elements(src.xaml(name))
               if el.hasAttribute("x:Name"))


def rule_findname_matches(src):
    t = tree(src.module("ta_ui"))
    settings = _xaml_names(src, "TagAlignerSettings.xaml")
    results = _xaml_names(src, "TagAlignerResults.xaml")
    scopes = {"SettingsWindow": [settings], "ResultsWindow": [results],
              "ThemeChip": [settings, results], "wire_chrome": [settings, results]}
    bad = []
    for node in t.body:
        if not isinstance(node, (ast.ClassDef, ast.FunctionDef)) or node.name not in scopes:
            continue
        used = set()
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                f = sub.func
                fname = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
                if fname in ("FindName", "_ctl") and sub.args and \
                        isinstance(sub.args[0], ast.Constant):
                    used.add(sub.args[0].value)
            if isinstance(sub, ast.Assign) and any(
                    isinstance(x, ast.Name) and x.id in ("RADIOS", "NUMBERS", "CHECKS")
                    for x in sub.targets):
                for c in ast.walk(sub.value):
                    if isinstance(c, ast.Constant) and isinstance(c.value, str) and \
                            c.value[:1].isupper():
                        used.add(c.value)
        for want in sorted(used):
            for names in scopes[node.name]:
                if want not in names:
                    bad.append("ta_ui.{0} looks for x:Name {1} that a window lacks".format(
                        node.name, want))
    return bad


def rule_theme_chip_everywhere(src):
    """Every window carries the chip, version and close at the top right."""
    bad = []
    for name in XAMLS[1:]:
        names = _xaml_names(src, name)
        for want in ("ThemeChip", "ThemeChipText", "GlyphAuto", "GlyphDark",
                     "GlyphLight", "VersionText", "CloseButton", "HeaderBar"):
            if want not in names:
                bad.append("{0}: header lacks {1}".format(name, want))
    return bad


# ==========================================================================
# Load every module against the stub API
# ==========================================================================

def rule_stub_load(src):
    sys.path.insert(0, HERE)
    import stubs
    stubs.install()
    stubs.uninstall_tool_modules()
    folder = tempfile.mkdtemp(prefix="ta_load_")
    for mod in MODULES:
        with io.open(os.path.join(folder, mod + ".py"), "w", encoding="utf-8") as h:
            h.write(src.module(mod))
    sys.path.insert(0, folder)
    bad = []
    try:
        for mod in MODULES:
            try:
                __import__(mod)
            except Exception as ex:
                bad.append("{0} failed to load: {1!r}".format(mod, ex))
    finally:
        sys.path.remove(folder)
        stubs.uninstall_tool_modules()
    return bad


RULES = [
    rule_no_fstrings, rule_no_print, rule_no_bare_integervalue,
    rule_no_system_uri, rule_bip_at_call_time, rule_clr_first,
    rule_assemblies_referenced, rule_no_duplicate_defs,
    rule_canvas_theme_not_truthy, rule_head_before_elbow,
    rule_measure_with_leaders_off, rule_family_reads_before_transaction,
    rule_handlers_guarded, rule_version_in_changelog, rule_no_shared_files,
    rule_loaders, rule_bundles, rule_xaml_parses, rule_no_static_resource,
    rule_enum_values, rule_dynamic_keys_defined, rule_palettes_complete,
    rule_style_targets, rule_findname_matches, rule_theme_chip_everywhere,
    rule_stub_load, rule_names_defined,
]


# ==========================================================================
# Deliberate breakages: (rule, what it does to a copy of the sources)
# ==========================================================================

def _sub(mod, old, new, xaml=False):
    def apply(src):
        text = src.xaml(mod) if xaml else src.module(mod)
        if old not in text:
            raise AssertionError("breakage anchor not found in {0}: {1!r}".format(mod, old))
        text = text.replace(old, new, 1)
        (src.set_xaml if xaml else src.set_module)(mod, text)
    return apply


def _add_path(rel):
    def apply(src):
        src.extra_paths.append(rel)
    return apply


def _script(old, new):
    def apply(src):
        k = sorted(src.scripts())[0]
        src.files[k] = src.files[k].replace(old, new, 1)
    return apply


def _bundle(old, new):
    def apply(src):
        k = sorted(src.bundles())[0]
        src.files[k] = src.files[k].replace(old, new, 1)
    return apply


BREAKAGES = [
    (rule_no_fstrings, _sub("ta_core", 'v = float(u"{0}".format(text)',
                             'v = float(f"{text}"')),
    (rule_no_fstrings, _sub("ta_core", "    return folder\n",
                             "    return folder\n\n\ndef _x():\n    return f'{1}'\n")),
    (rule_no_print, _sub("ta_core", "        return None\n    if v < lo",
                          "        print(text)\n        return None\n    if v < lo")),
    (rule_no_bare_integervalue, _sub("ta_model", "    keys = set(eid_value(t.Id) for t in tags)",
                                      "    keys = set(t.Id.IntegerValue for t in tags)")),
    (rule_no_system_uri, _sub("ta_ui", "from System.IO import File, MemoryStream",
                               "from System import Uri\nfrom System.IO import File, MemoryStream")),
    (rule_bip_at_call_time, _sub("ta_model", 'pid = bip(param_name)',
                                  'pid = BuiltInParameter.TEXT_SIZE')),
    (rule_clr_first, _sub("ta_model", "import ta_clr  # noqa: F401  must stay first\n\n", "")),
    (rule_clr_first, _sub("ta_ui", "import ta_clr  # noqa: F401  must stay first\n\nimport os",
                           "import os\nfrom System.IO import File\nimport ta_clr")),
    (rule_assemblies_referenced, _sub("ta_clr", '    "PresentationCore",\n', "")),
    (rule_assemblies_referenced, _sub("ta_ui", "from System.Diagnostics import Process",
                                       "from System.Diagnostics import Process\nfrom System.Data import DataTable")),
    (rule_no_duplicate_defs, _sub("ta_core", "def tolerance(scale):",
                                  "def edge(b, s):\n    return 0\n\n\ndef tolerance(scale):")),
    (rule_canvas_theme_not_truthy, _sub("ta_theme", "        if theme is not None:", "        if theme:")),
    (rule_head_before_elbow, _sub("ta_model",
                                  "    tag.TagHeadPosition = tag.TagHeadPosition.Add(vector)\n    expected = []\n    for ref, point in elbows:\n        target = point.Add(vector)\n        write_elbow(tag, ref, target)\n        expected.append((ref, target))\n",
                                  "    expected = []\n    for ref, point in elbows:\n        target = point.Add(vector)\n        write_elbow(tag, ref, target)\n        expected.append((ref, target))\n    tag.TagHeadPosition = tag.TagHeadPosition.Add(vector)\n")),
    (rule_measure_with_leaders_off, _sub("ta_model", "                    t.HasLeader = False", "                    pass")),
    (rule_measure_with_leaders_off, _sub("ta_model", "            sub.RollBack()", "            sub.Commit()")),
    (rule_family_reads_before_transaction, _sub("ta_ops",
                                                "    editable = model.checkout(doc, tags)\n",
                                                "    tx0 = Transaction(doc, u'x')\n    editable = model.checkout(doc, tags)\n")),
    (rule_handlers_guarded, _sub("ta_ui", "    def _cancel(self, sender, args):\n        try:\n            self.window.Close()\n        except Exception:\n            pass\n",
                                 "    def _cancel(self, sender, args):\n        self.window.Close()\n        self.window = None\n")),
    (rule_version_in_changelog, _sub("ta_core", '__version__ = u"1.0.0"', '__version__ = u"1.0.9"')),
    (rule_no_shared_files, _add_path("startup.py")),
    (rule_no_shared_files, _add_path(os.path.join("lib", "revobim", "__init__.py"))),
    (rule_no_shared_files, _add_path(os.path.join("RevoBIM PY.tab", "Annotation.panel", "bundle.yaml"))),
    (rule_loaders, _script("import os\n", "import clr\nclr.AddReference('RevitAPI')\nimport os\n")),
    (rule_loaders, _script("ta_run.main(u\"", "ta_run.main(u\"x")),
    (rule_bundles, _bundle("title: Tag ", "title: Plain ")),
    (rule_xaml_parses, _sub("TagAlignerSettings.xaml", "<!-- ==================== header ==================== -->",
                             "<!-- -------- header -------- -->", xaml=True)),
    (rule_xaml_parses, _sub("TagAlignerResults.xaml", "Title=\"RevoBIM Tag Aligner\"",
                             "Title=\"RevoBIM {}Tag Aligner\" Tag=\"a & b\"", xaml=True)),
    (rule_no_static_resource, _sub("TagAlignerSettings.xaml", "{DynamicResource Bg}", "{StaticResource Bg}", xaml=True)),
    (rule_enum_values, _sub("TagAlignerSettings.xaml", 'VerticalAlignment="Center"/>\n          <StackPanel DockPanel.Dock="Left"',
                             'VerticalAlignment="Baseline"/>\n          <StackPanel DockPanel.Dock="Left"', xaml=True)),
    (rule_dynamic_keys_defined, _sub("TagAlignerResults.xaml", "{DynamicResource Card}", "{DynamicResource Crad}", xaml=True)),
    (rule_dynamic_keys_defined, _sub("ta_ui", 'LEVEL_KEYS = {u"ok": u"Green"', 'LEVEL_KEYS = {u"ok": u"Grene"')),
    (rule_palettes_complete, _sub("ta_theme", '        u"OnAccent": u"#FFFFFF",\n    },\n}', '        u"OnAccent": u"#FFFFFF",\n        u"Extra": u"#000000",\n    },\n}')),
    (rule_style_targets, _sub("TagAlignerSettings.xaml", 'x:Name="ApplyButton" DockPanel.Dock="Right" Style="{DynamicResource TaPrimaryButton}"',
                               'x:Name="ApplyButton" DockPanel.Dock="Right" Style="{DynamicResource TaChip}"', xaml=True)),
    (rule_findname_matches, _sub("TagAlignerResults.xaml", 'x:Name="OpenLogButton"', 'x:Name="OpenLog"', xaml=True)),
    (rule_findname_matches, _sub("ta_ui", '"text_height_mm": "TextHeight"', '"text_height_mm": "TextHeightBox"')),
    (rule_theme_chip_everywhere, _sub("TagAlignerResults.xaml", 'x:Name="GlyphLight"', 'x:Name="GlyphSun"', xaml=True)),
    (rule_stub_load, _sub("ta_model", "from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType",
                          "from Autodesk.Revit.UI import ISelectionFilter, ObjectType")),
    (rule_names_defined, _sub("ta_model", "    SpatialElementTag,\n", "")),
    (rule_names_defined, _sub("ta_ops", "    FailureSeverity,\n", "")),
    (rule_stub_load, _sub("ta_ops", "from Autodesk.Revit.Exceptions import OperationCanceledException",
                          "from Autodesk.Revit.DB import OperationCanceledException")),
]


def run_rules(src, rules=RULES):
    failures = {}
    for rule in rules:
        try:
            problems = rule(src)
        except Exception as ex:
            problems = ["rule raised {0!r}".format(ex)]
        if problems:
            failures[rule.__name__] = problems
    return failures


def main(argv):
    src = Sources()
    failures = run_rules(src)
    for name, problems in sorted(failures.items()):
        for p in problems:
            print("FAIL {0}: {1}".format(name, p))
    print("import_check: {0} rules, {1} failing".format(len(RULES), len(failures)))
    ok = not failures
    if "--selftest" in argv:
        covered = set()
        inert = []
        for rule, breakage in BREAKAGES:
            broken = src.copy()
            try:
                breakage(broken)
            except AssertionError as ex:
                inert.append("{0}: {1}".format(rule.__name__, ex))
                continue
            caught = run_rules(broken, [rule])
            if rule.__name__ not in caught:
                inert.append("{0}: did not catch its breakage".format(rule.__name__))
            covered.add(rule.__name__)
        missing = [r.__name__ for r in RULES if r.__name__ not in covered]
        for line in inert:
            print("INERT " + line)
        for m in missing:
            print("NO BREAKAGE " + m)
        print("selftest: {0} breakages, {1} inert, {2} rules without one".format(
            len(BREAKAGES), len(inert), len(missing)))
        ok = ok and not inert and not missing
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
