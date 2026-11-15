# -*- coding: utf-8 -*-
"""Bench check for Duct Accessory Resize. Run from this folder:

    python import_check.py             check the shipped files
    python import_check.py --selftest  break every rule on purpose and
                                       confirm the check catches it

Every rule looks at code, never at prose: comments and docstrings are
stripped first, because rules that matched their own docstrings have
passed their selftests while doing nothing.
"""

from __future__ import print_function

import ast
import io
import os
import re
import sys
import tokenize
import xml.dom.minidom

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bench_stubs  # noqa: E402

MODULES = ("dar_clr.py", "dar_core.py", "dar_revit.py", "dar_ui.py",
           "dar_drawer.py", "dar_window.py", "script.py")
TOOL_MODULES = ("dar_core.py", "dar_revit.py", "dar_ui.py", "dar_drawer.py",
                "dar_window.py")
LAYOUTS = ("DuctAccessoryResize.xaml",)
THEME = "Theme.xaml"
OTHER = ("CHANGELOG.md",)


def load_files():
    files = {}
    for name in MODULES + LAYOUTS + (THEME,) + OTHER:
        with io.open(os.path.join(HERE, name), "r", encoding="utf-8") as h:
            files[name] = h.read()
    return files


# ============================================================
# code only - comments and docstrings out
# ============================================================

def code_only(text):
    tree = ast.parse(text)
    doc_lines = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(
                    getattr(body[0], "value", None), ast.Constant) and \
                    isinstance(body[0].value.value, str):
                for line in range(body[0].lineno, body[0].end_lineno + 1):
                    doc_lines.add(line)
    out = []
    for number, line in enumerate(text.splitlines(), 1):
        if number in doc_lines:
            out.append(u"")
            continue
        out.append(_strip_comment(line))
    return u"\n".join(out)


def _strip_comment(line):
    quote = None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote and line[i - 1] != "\\":
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#":
            return line[:i]
    return line


def tokens(text):
    return list(tokenize.generate_tokens(io.StringIO(text).readline))


def xml_names(text):
    return set(re.findall(r'x:Name="(\w+)"', text))


# ============================================================
# rules - each returns a list of problems
# ============================================================

def rule_xaml_parses(files):
    """Every .xaml parses as XML - an unclosed tag, a bare & or '--' in a
    comment kills XamlReader and shows a blank window."""
    out = []
    for name in LAYOUTS + (THEME,):
        try:
            xml.dom.minidom.parseString(files[name].encode("utf-8"))
        except Exception as error:
            out.append("{0} does not parse: {1}".format(name, error))
    return out


def rule_clr_first(files):
    """No System.* or Autodesk.* import before 'import dar_clr' in a tool
    module - pyRevit does not preload WPF into every engine."""
    out = []
    for name in TOOL_MODULES:
        seen_clr = False
        touches_net = False
        for number, line in enumerate(code_only(files[name]).splitlines(), 1):
            stripped = line.strip()
            if re.match(r"import\s+dar_clr\b", stripped):
                seen_clr = True
            if re.match(r"(from|import)\s+(System|Autodesk)\b", stripped):
                touches_net = True
                if name == "dar_core.py":
                    out.append("dar_core.py:{0} touches .NET - the rules must "
                               "stay testable under CPython".format(number))
                elif not seen_clr:
                    out.append("{0}:{1} reaches into .NET before "
                               "dar_clr".format(name, number))
        if touches_net and not seen_clr:
            out.append("{0} never imports dar_clr".format(name))
    return out


def rule_namespaces(files):
    """Every .NET name is imported from the namespace the real API keeps it
    in (the stub table) - v2.1.0 of Drainage Elevation Match asked
    Plumbing for a name that lives in DB."""
    out = []
    for name in MODULES:
        for node in ast.walk(ast.parse(files[name])):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            root = node.module.split(".")[0]
            if root not in ("System", "Autodesk"):
                continue
            known = bench_stubs.KNOWN.get(node.module)
            if known is None:
                out.append("{0}: unknown namespace {1}".format(name,
                                                               node.module))
                continue
            for alias in node.names:
                if alias.name not in known:
                    out.append("{0}: {1} is not in {2}".format(
                        name, alias.name, node.module))
    return out


def rule_no_static_resource(files):
    """Theme.xaml is merged after the layout is parsed, so a StaticResource
    in a layout fails at load."""
    return ["{0} uses StaticResource".format(n) for n in LAYOUTS
            if "StaticResource" in files[n]]


def theme_keys(files):
    return set(re.findall(r'x:Key="(\w+)"', files[THEME]))


def rule_dynamic_keys_exist(files):
    keys = theme_keys(files)
    out = []
    for name in LAYOUTS + (THEME,):
        for key in re.findall(r"\{DynamicResource (\w+)\}", files[name]):
            if key not in keys:
                out.append("{0}: DynamicResource {1} is not in {2}".format(
                    name, key, THEME))
    return out


def rule_style_target_types(files):
    """A style applied to an element its TargetType does not match raises
    when applied - another dead window."""
    targets = dict(re.findall(
        r'<Style x:Key="(\w+)" TargetType="\{x:Type (\w+)\}"', files[THEME]))
    out = []
    for name in LAYOUTS:
        for element, key in re.findall(
                r'<(\w+)\b[^>]*?Style="\{DynamicResource (\w+)\}"',
                files[name]):
            if key in targets and targets[key] != element:
                out.append("{0}: {1} styled with {2} (TargetType {3})".format(
                    name, element, key, targets[key]))
    return out


def rule_names_exist(files):
    """Every ctl()/FindName() name has an x:Name in the layout."""
    names = set()
    for layout in LAYOUTS:
        names |= xml_names(files[layout])
    out = []
    for name in TOOL_MODULES:
        code = code_only(files[name])
        used = re.findall(r'(?:ctl|FindName)\(\s*u?["\'](\w+)["\']', code)
        for table in re.findall(r'\{([^{}]*)\}', code):
            used += re.findall(r':\s*u"(\w+(?:Combo|Search|Block|Width|'
                               r'Height|Diameter))"', table)
        used += re.findall(r'u"(\w+Button)"', code)
        for item in used:
            if item not in names:
                out.append("{0}: no x:Name {1}".format(name, item))
    return out


def rule_banned_code(files):
    """No f-strings, no print, no bare .IntegerValue (only inside
    eid_value), no System.Uri, no nonlocal, no non-ASCII - IronPython 2.7
    and Revit 2026 compatibility."""
    out = []
    for name in MODULES:
        text = files[name]
        try:
            text.encode("ascii")
        except UnicodeError:
            out.append("{0}: non-ASCII character in source".format(name))
        for tok in tokens(text):
            kind = tokenize.tok_name.get(tok.type, "")
            if kind == "FSTRING_START" or (kind == "STRING" and re.match(
                    r"^[rRbBuU]*[fF]", tok.string)):
                out.append("{0}:{1} f-string".format(name, tok.start[0]))
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                    and node.func.id == "print":
                out.append("{0}:{1} print".format(name, node.lineno))
            if isinstance(node, ast.Nonlocal):
                out.append("{0}:{1} nonlocal".format(name, node.lineno))
            if isinstance(node, ast.Attribute) and node.attr == "Uri":
                out.append("{0}:{1} System.Uri".format(name, node.lineno))
            if isinstance(node, ast.ImportFrom) and node.module == "System" \
                    and any(a.name == "Uri" for a in node.names):
                out.append("{0}:{1} imports Uri".format(name, node.lineno))
        for func in [n for n in ast.walk(tree)
                     if isinstance(n, ast.FunctionDef)] + [tree]:
            body = func.body if func is not tree else [
                n for n in tree.body if not isinstance(n, ast.FunctionDef)]
            if isinstance(func, ast.FunctionDef) and func.name == "eid_value":
                continue
            for stmt in body:
                if isinstance(stmt, ast.FunctionDef):
                    continue
                for node in ast.walk(stmt):
                    if isinstance(node, ast.Attribute) and \
                            node.attr == "IntegerValue":
                        out.append("{0}:{1} bare .IntegerValue".format(
                            name, node.lineno))
    return sorted(set(out))


def rule_palettes(files):
    """Both palettes carry the same keys and every key has a brush in
    Theme.xaml, so a theme switch never leaves a surface unthemed."""
    bench_stubs.install()
    bench_stubs.forget()
    core = _load_core(files)
    out = []
    dark = set(core.PALETTES["dark"])
    light = set(core.PALETTES["light"])
    for key in sorted(dark ^ light):
        out.append("palette key {0} missing from one palette".format(key))
    keys = theme_keys(files)
    for key in sorted(dark | light):
        if key + "Brush" not in keys:
            out.append("{0}Brush not defined in Theme.xaml".format(key))
    for key in sorted(k for k in keys if k.endswith("Brush")):
        if key[:-5] not in dark:
            out.append("Theme.xaml brush {0} has no palette entry".format(key))
    return out


def _load_core(files):
    module = type(sys)("dar_core")
    module.__file__ = os.path.join(HERE, "dar_core.py")
    exec(compile(files["dar_core.py"], "dar_core.py", "exec"), module.__dict__)
    return module


def rule_script_thin(files):
    """script.py sets __persistentengine__ (the window is modeless) and
    imports nothing at module level that can fail."""
    out = []
    tree = ast.parse(files["script.py"])
    engine = False
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", "") == "__persistentengine__"
                for t in node.targets):
            engine = getattr(node.value, "value", None) is True
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name not in ("os", "sys", "traceback", "io"):
                    out.append("script.py imports {0} at module level".format(
                        alias.name))
        if isinstance(node, ast.ImportFrom):
            out.append("script.py imports from {0} at module level".format(
                node.module))
    if not engine:
        out.append("script.py does not set __persistentengine__ = True")
    return out


def rule_no_duplicate_defs(files):
    """Python silently keeps the last of two definitions of one name."""
    out = []
    for name in MODULES:
        tree = ast.parse(files[name])
        scopes = [tree] + [n for n in ast.walk(tree)
                           if isinstance(n, ast.ClassDef)]
        for scope in scopes:
            seen = set()
            for node in scope.body:
                if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                    if node.name in seen:
                        out.append("{0}: {1} defined twice".format(
                            name, node.name))
                    seen.add(node.name)
    return out


def rule_changelog(files):
    core = _load_core(files)
    if "## " + core.__version__ not in files["CHANGELOG.md"]:
        return ["CHANGELOG.md has no entry for {0}".format(core.__version__)]
    return []


def rule_egg_wired(files):
    """The easter egg is attached to the window's logo."""
    out = []
    if "attach_to_window" not in code_only(files["dar_ui.py"]):
        out.append("dar_ui never asks egg_hook for attach_to_window")
    if not re.search(r"ui\.attach_egg\(", code_only(files["dar_window.py"])):
        out.append("dar_window never calls ui.attach_egg")
    if "LogoHost" not in xml_names(files["DuctAccessoryResize.xaml"]):
        out.append("the layout has no LogoHost for the egg")
    return out


def rule_enums_late(files):
    """BuiltInCategory / BuiltInParameter members are looked up when
    called, never at import."""
    out = []
    for name in TOOL_MODULES:
        tree = ast.parse(files[name])
        for stmt in tree.body:
            if isinstance(stmt, (ast.FunctionDef, ast.ClassDef, ast.Import,
                                 ast.ImportFrom)):
                continue
            for node in ast.walk(stmt):
                if isinstance(node, ast.Attribute) and isinstance(
                        node.value, ast.Name) and node.value.id in (
                        "BuiltInCategory", "BuiltInParameter"):
                    out.append("{0}:{1} {2}.{3} at import time".format(
                        name, node.lineno, node.value.id, node.attr))
    return out


def rule_modules_load(files):
    """Every module loads against the stub API."""
    out = []
    bench_stubs.install()
    bench_stubs.forget()
    temp = {}
    for name in ("dar_clr.py",) + TOOL_MODULES:
        module_name = name[:-3]
        module = type(sys)(module_name)
        module.__file__ = os.path.join(HERE, name)
        sys.modules[module_name] = module
        temp[module_name] = module
    for name in ("dar_clr.py",) + TOOL_MODULES:
        module = temp[name[:-3]]
        try:
            exec(compile(files[name], name, "exec"), module.__dict__)
        except Exception as error:
            out.append("{0} does not load: {1!r}".format(name, error))
    bench_stubs.forget()
    return out


def rule_raise_checked(files):
    """ExternalEvent.Raise() status is always read - a refused request that
    nobody looks at is a button that does nothing."""
    out = []
    for name in TOOL_MODULES:
        for node in ast.walk(ast.parse(files[name])):
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) \
                    and getattr(node.value.func, "attr", "") == "Raise":
                out.append("{0}:{1} Raise() result thrown away".format(
                    name, node.lineno))
    return out


def rule_handlers_exist(files):
    """Every self.guard(self.X) names a method the window defines."""
    code = code_only(files["dar_window.py"])
    defined = set(re.findall(r"def (\w+)\(self", code))
    return ["dar_window: handler {0} is not defined".format(h)
            for h in re.findall(r"self\.guard\(\s*self\.(\w+)", code)
            if h not in defined]


def rule_window_chrome(files):
    """AllowsTransparency needs WindowStyle None or Show() throws, and
    VerticalAlignment=Baseline kills XamlReader silently."""
    out = []
    for name in LAYOUTS:
        text = files[name]
        if 'AllowsTransparency="True"' in text and \
                'WindowStyle="None"' not in text:
            out.append("{0}: AllowsTransparency without WindowStyle None".format(
                name))
        if 'VerticalAlignment="Baseline"' in text:
            out.append("{0}: VerticalAlignment Baseline".format(name))
    return out


def rule_detach_order(files):
    """Inside the resize: accessories detached, sizes written, model
    regenerated, connections put back - in that order. v1.0.0 wrote sizes
    into a connected network and Revit refused every element."""
    code = code_only(files["dar_revit.py"])
    body = code[code.find("def attempt(chunk)"):]
    steps = ["detach_accessories(", "write_row(", "doc.Regenerate()",
             "reattach("]
    places = [body.find(step) for step in steps]
    if -1 in places:
        return ["attempt() is missing {0}".format(
            steps[places.index(-1)])]
    if places != sorted(places):
        return ["attempt() runs {0} out of order".format(", ".join(steps))]
    return []


def _nested(tree, *names):
    """The innermost of a chain of nested function definitions."""
    node = tree
    for name in names:
        found = None
        for child in ast.walk(node):
            if isinstance(child, ast.FunctionDef) and child.name == name:
                found = child
                break
        if found is None:
            return None
        node = found
    return node


def _handler_calls(node, name):
    """True when any except handler inside node calls name()."""
    for child in ast.walk(node):
        if not isinstance(child, ast.Try):
            continue
        for handler in child.handlers:
            for inner in ast.walk(handler):
                if isinstance(inner, ast.Call) and \
                        getattr(inner.func, "id", "") == name:
                    return True
    return False


def rule_drawer(files):
    """Shrink to taskbar, and the four traps that fail silently.

    The slide is eased by hand, so there is no animation to leave holding
    its end value. What has to hold instead: MinHeight put back, the body
    unpinned, the grips parked, and - the one that cost Panel Template Mngr
    a bench - the tick having its OWN fallback. An exception escaping a
    tick reaches the dispatcher, not the try around Start(), and leaves the
    drawer sliding for ever with nothing raised to say so."""
    out = []
    drawer = files["dar_drawer.py"]
    window = files["dar_window.py"]
    drawer_code = code_only(drawer)
    window_code = code_only(window)

    for name in LAYOUTS:
        names = xml_names(files[name])
        shrink = [n for n in names if n.endswith("ShrinkButton")]
        if not shrink:
            out.append("{0} has no shrink button".format(name))
        for button in shrink:
            if not re.search(r'ctl\(\s*u?["\']{0}["\']\s*\)\s*\.Click'
                             .format(button), window_code):
                out.append("{0} is drawn but its Click is never wired"
                           .format(button))
            if re.search(r'ACTION_BUTTONS[^)]*{0}'.format(button),
                         window_code, re.S):
                out.append("{0} is disabled while a job runs - it is the one "
                           "control that must stay live".format(button))

    if not re.search(r"drawer\.Drawer\(", window_code):
        out.append("the window is built without a drawer")

    if "Storyboard" in drawer_code or "BeginAnimation" in drawer_code:
        out.append("dar_drawer animates the slide - ease it by hand, or the "
                   "animation holds its end value for ever")

    tree = ast.parse(drawer)
    if not re.search(r"self\.window\.MinHeight\s*=\s*self\.saved",
                     drawer_code):
        out.append("dar_drawer never puts MinHeight back - the window can be "
                   "dragged shut for the rest of the session")
    if not re.search(r"self\.body\.Height\s*=\s*Double\.NaN", drawer_code):
        out.append("dar_drawer never unpins the body")

    def calls(node, name):
        return any(isinstance(c, ast.Call) and
                   getattr(c.func, "attr", "") == name
                   for c in ast.walk(node))

    # every way out of the drawer, not just the slide back: unpinning on
    # one of them is a half fix that still leaves a window nobody can resize
    for path in ("restore", "settle"):
        node = _nested(tree, path)
        if node is None:
            out.append("dar_drawer has no {0}()".format(path))
            continue
        if not calls(node, "_unpin_body"):
            out.append("dar_drawer.{0}() leaves the body pinned".format(path))
        if not calls(node, "_put_back"):
            out.append("dar_drawer.{0}() leaves MinHeight clamped"
                       .format(path))
        if not calls(node, "_show_grips"):
            out.append("dar_drawer.{0}() leaves the grips parked - invisible "
                       "drag handles over the bar".format(path))
    shrink = _nested(tree, "shrink")
    if shrink is not None and not calls(shrink, "_show_grips"):
        out.append("dar_drawer.shrink() leaves the grips over the parked "
                   "bar, swallowing the click that opens it again")

    slide = _nested(tree, "_slide")
    if slide is None:
        out.append("dar_drawer has no _slide()")
    else:
        tick = _nested(slide, "on_tick")
        if tick is None:
            out.append("_slide has no tick handler")
        elif not _handler_calls(tick, "land"):
            out.append("the tick handler has no fallback of its own - an "
                       "exception in a tick reaches the dispatcher, not the "
                       "try around Start(), and the drawer slides for ever")
        starts = [n for n in ast.walk(slide)
                  if isinstance(n, ast.Try) and any(
                      isinstance(c, ast.Call) and
                      getattr(c.func, "attr", "") == "Start"
                      for c in ast.walk(n))]
        if not starts:
            out.append("_slide never starts a timer")
        elif not any(_handler_calls(t, "land") for t in starts):
            out.append("_slide does not land the window when no timer can "
                       "start")
    return out


def rule_no_literal_colour(files):
    """Colours live in Theme.xaml and the palettes, never in a layout - one
    painted into a layout survives a palette swap and sits there light on
    light."""
    out = []
    for name in LAYOUTS:
        for line, text in enumerate(files[name].splitlines(), 1):
            if re.search(r'(Background|Foreground|Fill|Stroke|'
                         r'BorderBrush|Color)="#[0-9A-Fa-f]{3,8}"', text):
                out.append("{0}:{1} paints a literal colour".format(name,
                                                                    line))
    return out


RULES = [
    rule_xaml_parses, rule_clr_first, rule_namespaces,
    rule_no_static_resource, rule_dynamic_keys_exist,
    rule_style_target_types, rule_names_exist, rule_banned_code,
    rule_palettes, rule_script_thin, rule_no_duplicate_defs, rule_changelog,
    rule_egg_wired, rule_enums_late, rule_modules_load, rule_raise_checked,
    rule_handlers_exist, rule_window_chrome, rule_detach_order,
    rule_drawer, rule_no_literal_colour,
]


def run(files):
    problems = {}
    for rule in RULES:
        try:
            found = rule(files)
        except Exception as error:
            found = ["rule crashed: {0!r}".format(error)]
        if found:
            problems[rule.__name__] = found
    return problems


# ============================================================
# selftest - every rule must catch its own breakage
# ============================================================

def _sub(name, old, new, count=1):
    def mutate(files):
        assert old in files[name], "selftest anchor missing: " + old
        files[name] = files[name].replace(old, new, count)
    return mutate


def _append(name, text):
    def mutate(files):
        files[name] = files[name] + text
    return mutate


BREAKS = [
    ("rule_xaml_parses", _sub("DuctAccessoryResize.xaml", "<!-- ============== header",
                              "<!-- -- header -- --><!-- ============== header")),
    ("rule_xaml_parses", _sub("Theme.xaml", "</ResourceDictionary>", "")),
    ("rule_clr_first", _sub("dar_ui.py", "import dar_clr  # noqa",
                            "from System.IO import File\nimport dar_clr  # noqa")),
    ("rule_clr_first", _sub("dar_core.py", "import datetime",
                            "import datetime\nfrom System import String")),
    ("rule_namespaces", _sub("dar_revit.py", "import dar_core as core",
                             "from Autodesk.Revit.DB.Plumbing import "
                             "TransactionGroup\nimport dar_core as core")),
    ("rule_namespaces", _sub("dar_window.py", "Clipboard, VerticalAlignment",
                             "Clipboard, Thumb, VerticalAlignment")),
    ("rule_no_static_resource", _sub("DuctAccessoryResize.xaml",
                                     "{DynamicResource MutedBrush}",
                                     "{StaticResource MutedBrush}")),
    ("rule_dynamic_keys_exist", _sub("DuctAccessoryResize.xaml",
                                     "{DynamicResource OrangeBrush}",
                                     "{DynamicResource OrangishBrush}")),
    ("rule_style_target_types", _sub("DuctAccessoryResize.xaml",
                                     '<TextBlock x:Name="CountText"',
                                     '<TextBlock x:Name="CountText" '
                                     'Style="{DynamicResource BtnGhost}"')),
    ("rule_names_exist", _sub("dar_window.py", 'self.ctl(u"CountText")',
                              'self.ctl(u"CountTxt")')),
    ("rule_names_exist", _sub("dar_window.py", 'u"d": u"AccDiameterCombo"',
                              'u"d": u"AccDiamCombo"')),
    ("rule_names_exist", _sub("dar_window.py", 'u"d": u"TermDiameterCombo"',
                              'u"d": u"TermDiamCombo"')),
    ("rule_banned_code", _append("dar_core.py", '\nX_ = f"{1}"\n')),
    ("rule_banned_code", _append("dar_core.py", '\nprint("")\n')),
    ("rule_banned_code", _append("dar_revit.py",
                                 "\n\ndef bad_(e):\n    return e.IntegerValue\n")),
    ("rule_banned_code", _append("dar_ui.py", "\nU_ = System.Uri\n")),
    ("rule_banned_code", _append("dar_core.py", u'\nX_ = u"\u00d8"\n')),
    ("rule_banned_code", _append("dar_core.py",
                                 "\n\ndef n_():\n    x = 1\n\n    def m_():\n"
                                 "        nonlocal x\n    return m_\n")),
    ("rule_palettes", _sub("Theme.xaml",
                           '<SolidColorBrush x:Key="HoverBrush" Color="#414B5A"/>', "")),
    ("rule_palettes", _sub("dar_core.py", 'u"Hover": u"#ECECF0", ', "")),
    ("rule_script_thin", _sub("script.py", "__persistentengine__ = True",
                              "__persistentengine__ = False")),
    ("rule_script_thin", _sub("script.py", "import os\n",
                              "import os\nimport dar_window\n")),
    ("rule_no_duplicate_defs", _append("dar_core.py",
                                       "\n\ndef fmt_mm(v):\n    return v\n")),
    ("rule_changelog", _sub("CHANGELOG.md", "## 1.3.0", "## 0.9.9")),
    ("rule_egg_wired", _sub("dar_window.py", "ui.attach_egg(", "ui.attach_eggs_off(")),
    ("rule_enums_late", _append("dar_revit.py",
                                "\nW_ = BuiltInParameter.RBS_CURVE_WIDTH_PARAM\n")),
    ("rule_modules_load", _append("dar_core.py", "\nY_ = undefined_name_xyz\n")),
    ("rule_raise_checked", _sub("dar_window.py",
                                "status = core.to_text(self.event.Raise())",
                                "self.event.Raise()\n        status = u\"Accepted\"")),
    ("rule_handlers_exist", _sub("dar_window.py", "def on_clear(self",
                                 "def on_clearx(self")),
    ("rule_detach_order", _sub("dar_revit.py", "            doc.Regenerate()\n", "")),
    ("rule_detach_order", _sub("dar_revit.py",
                               "            pairs = detach_accessories(\n"
                               "                doc, [e for e in elements if e is not None], log)\n",
                               "            pairs = []\n")),
    ("rule_drawer", _sub("dar_window.py", "self.drawer = drawer.Drawer(",
                         "self.drawer = _no_drawer(")),
    ("rule_drawer", _sub("dar_window.py",
                         '.Click += self.guard(self.on_shrink)',
                         '.ToolTip = u"shrink"')),
    ("rule_drawer", _sub("dar_window.py",
                         'ACTION_BUTTONS = (u"SelectButton"',
                         'ACTION_BUTTONS = (u"ShrinkButton", u"SelectButton"')),
    ("rule_drawer", _sub("dar_drawer.py", "self.window.MinHeight = self.saved",
                         "self.window.MinHeight = 0.0  # self.saved")),
    ("rule_drawer", _sub("dar_drawer.py", "self.body.Height = Double.NaN",
                         "self.body.Height = 0.0")),
    # the trap: the tick losing its own fallback, which the try around
    # Start() does NOT cover
    ("rule_drawer", _sub("dar_drawer.py",
                         "            except Exception:\n"
                         "                self._stop_timer()\n"
                         "                land()\n",
                         "            except Exception:\n"
                         "                self._stop_timer()\n")),
    ("rule_drawer", _sub("dar_drawer.py",
                         "        except Exception:\n"
                         "            self.timer = None\n"
                         "            land()\n",
                         "        except Exception:\n"
                         "            self.timer = None\n")),
    ("rule_drawer", _sub("dar_drawer.py", "            self._show_grips(True)\n",
                         "", 2)),
    ("rule_no_literal_colour", _sub("DuctAccessoryResize.xaml",
                                    '<TextBlock x:Name="CountText"',
                                    '<TextBlock x:Name="CountText" Foreground="#FF0000"')),
    ("rule_window_chrome", _sub("DuctAccessoryResize.xaml", 'WindowStyle="None" ', "")),
    ("rule_window_chrome", _sub("DuctAccessoryResize.xaml", 'x:Name="StatusText"',
                                'x:Name="StatusText" VerticalAlignment="Baseline"')),
]


def selftest():
    clean = load_files()
    baseline = run(dict(clean))
    if baseline:
        print("the shipped files fail - fix them before the selftest:")
        report(baseline)
        return 1
    failures = 0
    covered = set()
    for rule_name, mutate in BREAKS:
        files = dict(clean)
        mutate(files)
        found = run(files)
        messages = found.get(rule_name, [])
        # a rule that crashed has not caught anything - it just fell over
        caught = bool(messages) and not any(
            m.startswith("rule crashed") for m in messages)
        covered.add(rule_name)
        print("  {0:<28} {1}".format(rule_name, ("caught: " + messages[0])
                                     if caught else "MISSED ITS OWN BREAKAGE"))
        if not caught:
            failures += 1
    for rule in RULES:
        if rule.__name__ not in covered:
            print("  {0:<28} HAS NO SELFTEST".format(rule.__name__))
            failures += 1
    print("")
    print("selftest: {0} breakages, {1} missed".format(len(BREAKS), failures))
    return 1 if failures else 0


def report(problems):
    for rule, found in sorted(problems.items()):
        print(rule)
        for item in found:
            print("    " + item)


def main():
    if "--selftest" in sys.argv:
        return selftest()
    problems = run(load_files())
    if problems:
        report(problems)
        return 1
    print("import_check: {0} rules, all clean".format(len(RULES)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
