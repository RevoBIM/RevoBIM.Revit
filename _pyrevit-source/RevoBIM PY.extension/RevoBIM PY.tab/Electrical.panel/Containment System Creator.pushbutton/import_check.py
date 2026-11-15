# -*- coding: utf-8 -*-
"""Static checks for Containment System Creator.

Run under plain CPython 3 from this folder:

    python import_check.py              every rule against the shipped files
    python import_check.py --selftest   prove every rule by breaking it

A rule nobody has seen fail is a rule that might not work, so ``--selftest``
applies a deliberate breakage for each one, confirms the breakage really
changed something, and confirms the rule then reports a problem. Rules read
code through the AST, never prose, so a docstring cannot satisfy them.
"""

import ast
import os
import re
import sys
import xml.dom.minidom

HERE = os.path.dirname(os.path.abspath(__file__))

SOURCES = ("script.py", "csc_clr.py", "csc_drawer.py")
EXTRA = ("CHANGELOG.md",)

# every .NET namespace the tool may import, and the assemblies that provide it
# across .NET Framework 4.8 (Revit 2024) and .NET 8 (Revit 2025+)
ASSEMBLY_FOR = {
    "System": ("mscorlib", "System.Runtime", "System"),
    "System.IO": ("mscorlib", "System.Runtime", "System"),
    "System.Windows": ("PresentationFramework", "PresentationCore",
                       "WindowsBase"),
    "System.Windows.Controls": ("PresentationFramework",),
    "System.Windows.Media": ("PresentationCore",),
    "System.Windows.Media.Imaging": ("PresentationCore",),
    "System.Windows.Input": ("PresentationCore", "WindowsBase"),
    "System.Windows.Threading": ("WindowsBase",),
    "System.Windows.Interop": ("PresentationFramework", "PresentationCore"),
    "System.Windows.Forms": ("System.Windows.Forms",),
}

EVENT_ATTRS = ("Click", "TextChanged", "SelectionChanged",
               "SelectedItemChanged", "MouseLeftButtonDown")

DRAWER_NAMES = ("header_bar", "shrink_btn", "shrink_glyph", "expand_glyph")


# ===========================================================================
# loading
# ===========================================================================

def load_files():
    files = {}
    names = list(SOURCES) + list(EXTRA)
    names += sorted(n for n in os.listdir(HERE) if n.endswith(".xaml"))
    for name in names:
        with open(os.path.join(HERE, name), "rb") as handle:
            files[name] = handle.read().decode("utf-8")
    return files


def layouts(files):
    return sorted(n for n in files if n.endswith(".xaml"))


def tree(files, name):
    return ast.parse(files[name], name)


def window_classes(script_tree):
    """Classes deriving from forms.WPFWindow."""
    found = []
    for node in script_tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for base in node.bases:
            if (isinstance(base, ast.Attribute) and base.attr == "WPFWindow"
                    and isinstance(base.value, ast.Name)
                    and base.value.id == "forms"):
                found.append(node)
    return found


def method(cls, name):
    for node in cls.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def layout_of(cls):
    """The layout a window class loads through init_window(self, "<x>")."""
    for node in ast.walk(cls):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "init_window" and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)):
            return node.args[1].value
    return None


def is_system_import(node):
    if isinstance(node, ast.ImportFrom):
        return (node.module or "").split(".")[0] == "System"
    if isinstance(node, ast.Import):
        return any(a.name.split(".")[0] == "System" for a in node.names)
    return False


def imports_clr_module(node):
    return (isinstance(node, ast.Import)
            and any(a.name == "csc_clr" for a in node.names))


def named_elements(xaml_text):
    dom = xml.dom.minidom.parseString(xaml_text.encode("utf-8"))
    out = {}
    for element in dom.getElementsByTagName("*"):
        name = element.getAttribute("x:Name")
        if name:
            out[name] = element
    return out


# ===========================================================================
# rules - each returns a list of problems, empty when clean
# ===========================================================================

def rule_xaml_parses(files):
    """Every layout parses as XML - a comment holding "--", an unclosed tag
    or a bare "&" would otherwise be a blank white pyRevit window."""
    problems = []
    for name in layouts(files):
        try:
            xml.dom.minidom.parseString(files[name].encode("utf-8"))
        except Exception as err:
            problems.append("{0}: {1}".format(name, err))
    return problems


def rule_clr_first(files):
    """script.py imports csc_clr before any System import at module level;
    the other modules import nothing from System at load time, and any
    function that does imports csc_clr first."""
    problems = []
    body = tree(files, "script.py").body
    clr_at = [i for i, n in enumerate(body) if imports_clr_module(n)]
    sys_at = [i for i, n in enumerate(body) if is_system_import(n)]
    if not clr_at:
        problems.append("script.py never imports csc_clr")
    elif sys_at and sys_at[0] < clr_at[0]:
        problems.append("script.py line {0}: System import before csc_clr"
                        .format(body[sys_at[0]].lineno))

    for name in ("csc_clr.py", "csc_drawer.py"):
        module = tree(files, name)
        for node in module.body:
            if is_system_import(node):
                problems.append("{0} line {1}: System import at load time"
                                .format(name, node.lineno))
        for func in ast.walk(module):
            if not isinstance(func, ast.FunctionDef):
                continue
            first_sys = None
            first_clr = None
            for node in ast.walk(func):
                if is_system_import(node) and (
                        first_sys is None or node.lineno < first_sys):
                    first_sys = node.lineno
                if imports_clr_module(node) and (
                        first_clr is None or node.lineno < first_clr):
                    first_clr = node.lineno
            if first_sys is not None and (first_clr is None
                                          or first_clr > first_sys):
                problems.append("{0} {1}(): System import without csc_clr "
                                "first".format(name, func.name))
    return problems


def referenced_assemblies(files):
    for node in tree(files, "csc_clr.py").body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "ASSEMBLIES"):
            return set(ast.literal_eval(node.value))
    return set()


def rule_assemblies_referenced(files):
    """Every System namespace imported anywhere maps to an assembly csc_clr
    references - the only rule that can catch a missing clr.AddReference,
    since under CPython there is no assembly to forget."""
    problems = []
    have = referenced_assemblies(files)
    for name in SOURCES:
        for node in ast.walk(tree(files, name)):
            if not isinstance(node, ast.ImportFrom):
                continue
            module = node.module or ""
            if module.split(".")[0] != "System":
                continue
            providers = ASSEMBLY_FOR.get(module)
            if providers is None:
                problems.append("{0} line {1}: {2} is not in ASSEMBLY_FOR"
                                .format(name, node.lineno, module))
            elif not have.intersection(providers):
                problems.append("{0} line {1}: nothing references an assembly "
                                "for {2} ({3})".format(name, node.lineno,
                                                       module,
                                                       ", ".join(providers)))
    return problems


def rule_banned(files):
    """No f-strings or print (IronPython 2.7); no bare .IntegerValue outside
    eid_value (removed in Revit 2026); no System.Uri / UriSource (moved in
    .NET 8)."""
    problems = []
    for name in SOURCES:
        module = tree(files, name)
        allowed = set()
        for func in ast.walk(module):
            if isinstance(func, ast.FunctionDef) and func.name == "eid_value":
                for node in ast.walk(func):
                    allowed.add(id(node))
        for node in ast.walk(module):
            if isinstance(node, ast.JoinedStr):
                problems.append("{0} line {1}: f-string".format(name,
                                                                node.lineno))
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "print"):
                problems.append("{0} line {1}: print".format(name,
                                                             node.lineno))
            if (isinstance(node, ast.Attribute)
                    and node.attr == "IntegerValue" and id(node) not in allowed):
                problems.append("{0} line {1}: bare .IntegerValue"
                                .format(name, node.lineno))
            if isinstance(node, ast.Attribute) and node.attr == "UriSource":
                problems.append("{0} line {1}: UriSource".format(name,
                                                                 node.lineno))
            if (isinstance(node, ast.ImportFrom) and node.module == "System"
                    and any(a.name in ("Uri", "UriKind") for a in node.names)):
                problems.append("{0} line {1}: System.Uri import"
                                .format(name, node.lineno))
    return problems


def rule_every_window_has_drawer(files):
    """Every window class loads through init_window and gives itself a drawer
    in __init__ - a window built without one has no shrink gesture."""
    problems = []
    classes = window_classes(tree(files, "script.py"))
    if not classes:
        problems.append("no window classes found")
    for cls in classes:
        init = method(cls, "__init__")
        if init is None:
            problems.append("{0} has no __init__".format(cls.name))
            continue
        attached = False
        for node in ast.walk(init):
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Attribute)
                    and node.targets[0].attr == "drawer"
                    and isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Attribute)
                    and node.value.func.attr == "attach"
                    and isinstance(node.value.func.value, ast.Name)
                    and node.value.func.value.id == "csc_drawer"):
                attached = True
        if not attached:
            problems.append("{0}.__init__ never calls csc_drawer.attach"
                            .format(cls.name))
        if layout_of(cls) is None:
            problems.append("{0} does not load through init_window"
                            .format(cls.name))
    return problems


def rule_every_layout_loaded(files):
    """Every layout is loaded by a window class - and so has a drawer."""
    loaded = set(layout_of(c) for c in window_classes(tree(files, "script.py")))
    return ["{0} is not loaded by any window class".format(n)
            for n in layouts(files) if n not in loaded]


def rule_shrink_in_every_layout(files):
    """Every layout draws the drawer's parts: a header Border that takes the
    mouse, a shrink Button, the down glyph and the green up glyph (collapsed
    at start)."""
    problems = []
    for name in layouts(files):
        try:
            found = named_elements(files[name])
        except Exception:
            problems.append("{0}: does not parse".format(name))
            continue
        for part in DRAWER_NAMES:
            if part not in found:
                problems.append("{0}: no x:Name=\"{1}\"".format(name, part))
        header = found.get("header_bar")
        if header is not None:
            if header.tagName != "Border":
                problems.append("{0}: header_bar is not a Border".format(name))
            if not header.getAttribute("MouseLeftButtonDown"):
                problems.append("{0}: header_bar takes no mouse".format(name))
        button = found.get("shrink_btn")
        if button is not None and button.tagName != "Button":
            problems.append("{0}: shrink_btn is not a Button".format(name))
        expand = found.get("expand_glyph")
        if expand is not None and expand.getAttribute("Visibility") != "Collapsed":
            problems.append("{0}: expand_glyph shows at start".format(name))
    return problems


def rule_shrink_wired(files):
    """attach() hooks the shrink button, the keys and the close - a button
    drawn but never wired does nothing when pressed."""
    want = {("shrink_btn", "Click"): False, (None, "PreviewKeyDown"): False,
            (None, "Closed"): False}
    module = tree(files, "csc_drawer.py")
    attach = None
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name == "attach":
            attach = node
    if attach is None:
        return ["csc_drawer has no attach()"]
    for node in ast.walk(attach):
        if not (isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Add)
                and isinstance(node.target, ast.Attribute)):
            continue
        event = node.target.attr
        owner = node.target.value
        owner_name = owner.attr if isinstance(owner, ast.Attribute) else None
        for key in want:
            if key[1] == event and (key[0] is None or key[0] == owner_name):
                want[key] = True
    return ["attach() never hooks {0}{1}".format(
        (k[0] + ".") if k[0] else "window.", k[1])
        for k, done in sorted(want.items(), key=str) if not done]


def rule_animation_released(files):
    """No Storyboard or DoubleAnimation anywhere; _release clears Top and
    Height with BeginAnimation(prop, None); shrink and expand both call it."""
    problems = []
    for name in SOURCES:
        for node in ast.walk(tree(files, name)):
            if isinstance(node, (ast.Name, ast.Attribute)):
                label = node.id if isinstance(node, ast.Name) else node.attr
                if label in ("Storyboard", "DoubleAnimation"):
                    problems.append("{0} line {1}: {2}".format(
                        name, node.lineno, label))
            if isinstance(node, ast.alias) and node.name in (
                    "Storyboard", "DoubleAnimation"):
                problems.append("{0}: imports {1}".format(name, node.name))

    drawer_cls = None
    for node in tree(files, "csc_drawer.py").body:
        if isinstance(node, ast.ClassDef) and node.name == "WindowDrawer":
            drawer_cls = node
    if drawer_cls is None:
        return problems + ["csc_drawer has no WindowDrawer"]

    release = method(drawer_cls, "_release")
    cleared = set()
    if release is not None:
        for node in ast.walk(release):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "BeginAnimation" and len(node.args) == 2
                    and isinstance(node.args[1], ast.Constant)
                    and node.args[1].value is None
                    and isinstance(node.args[0], ast.Attribute)):
                cleared.add(node.args[0].attr)
    for prop in ("top_prop", "height_prop"):
        if prop not in cleared:
            problems.append("_release does not clear {0}".format(prop))

    for gesture in ("shrink", "expand"):
        func = method(drawer_cls, gesture)
        calls = func is not None and any(
            isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "_release" for n in ast.walk(func))
        if not calls:
            problems.append("{0}() does not release held animations"
                            .format(gesture))
    return problems


def rule_handlers_exist(files):
    """Every event handler a layout names exists on the class that loads it."""
    problems = []
    by_layout = {}
    for cls in window_classes(tree(files, "script.py")):
        names = set(n.name for n in cls.body if isinstance(n, ast.FunctionDef))
        by_layout[layout_of(cls)] = (cls.name, names)
    pattern = re.compile(r'\b(?:{0})="([A-Za-z_][A-Za-z0-9_]*)"'.format(
        "|".join(EVENT_ATTRS)))
    for name in layouts(files):
        owner = by_layout.get(name)
        if owner is None:
            problems.append("{0}: no class loads it".format(name))
            continue
        for handler in pattern.findall(files[name]):
            if handler not in owner[1]:
                problems.append("{0}: {1} has no method {2}".format(
                    name, owner[0], handler))
    return problems


def rule_no_duplicate_defs(files):
    """No function, class or method defined twice - Python silently keeps the
    second one."""
    problems = []
    for name in SOURCES:
        module = tree(files, name)
        scopes = [("module", module.body)]
        scopes += [(n.name, n.body) for n in module.body
                   if isinstance(n, ast.ClassDef)]
        for scope, body in scopes:
            seen = set()
            for node in body:
                if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                    if node.name in seen:
                        problems.append("{0} {1}: {2} defined twice".format(
                            name, scope, node.name))
                    seen.add(node.name)
    return problems


def script_version(files):
    for node in tree(files, "script.py").body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "__version__"):
            return node.value.value
    return None


def rule_changelog_has_version(files):
    version = script_version(files)
    if version is None:
        return ["script.py has no __version__"]
    if "## v{0} ".format(version) not in files["CHANGELOG.md"]:
        return ["CHANGELOG.md has no entry for v{0}".format(version)]
    return []


def rule_version_shown(files):
    """Every window puts __version__ in its top right corner."""
    problems = []
    for cls in window_classes(tree(files, "script.py")):
        shown = False
        for node in ast.walk(cls):
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Attribute)
                    and node.targets[0].attr == "Text"
                    and isinstance(node.targets[0].value, ast.Attribute)
                    and node.targets[0].value.attr == "version_text"
                    and any(isinstance(n, ast.Name) and n.id == "__version__"
                            for n in ast.walk(node.value))):
                shown = True
        if not shown:
            problems.append("{0} never shows __version__".format(cls.name))
    return problems


def rule_esc_kept_for_drawer(files):
    """init_window asks pyRevit not to hook Esc, or Esc on a parked window
    would close it instead of bringing it back."""
    module = tree(files, "script.py")
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name == "init_window":
            for call in ast.walk(node):
                if isinstance(call, ast.Call):
                    for kw in call.keywords:
                        if (kw.arg == "handle_esc"
                                and isinstance(kw.value, ast.Constant)
                                and kw.value.value is False):
                            return []
            return ["init_window never passes handle_esc=False"]
    return ["script.py has no init_window"]


REVIT_DARK = {
    "WinBg": "#FF3C4454",       # Revit project browser body
    "FieldBg": "#FF2D3441",     # Revit search box
    "EdgeBrush": "#FF4E5665",   # Revit tree lines
    "TextBrush": "#FFE8F0F8",   # Revit text
    "MutedBrush": "#FF9DA4B2",  # Revit icon grey
}
HEADER_BAR = "#FF212932"        # Revit title bar
OLD_GREYS = ("#FF232326", "#FF2B2B2E", "#FF1C1C1F", "#FF3E3E42", "#FFE4E4E4",
             "#FF9A9A9E", "#FF6A6A6E", "#FF3A3A3E", "#FF4A4A50")


def rule_revit_dark_palette(files):
    """Every layout uses Revit's own dark colours, sampled from its project
    browser: the palette keys it defines carry Revit's values, the header bar
    is Revit's title bar colour, and none of the original neutral greys are
    left behind."""
    problems = []
    for name in layouts(files):
        text = files[name]
        for key, value in REVIT_DARK.items():
            match = re.search(r'x:Key="{0}"\s+Color="(#[0-9A-Fa-f]{{8}})"'
                              .format(key), text)
            if match and match.group(1).upper() != value:
                problems.append("{0}: {1} is {2}, not Revit's {3}".format(
                    name, key, match.group(1), value))
        try:
            header = named_elements(text).get("header_bar")
        except Exception:
            header = None
        if header is not None and header.getAttribute("Background").upper() != HEADER_BAR:
            problems.append("{0}: header bar is not Revit's title bar colour"
                            .format(name))
        for grey in OLD_GREYS:
            if grey in text.upper():
                problems.append("{0}: old grey {1} still used".format(name, grey))
    for grey in ("154, 154, 158", "228, 228, 228"):
        if grey in files["script.py"]:
            problems.append("script.py: old grey ({0}) still used".format(grey))
    return problems


RULES = [
    rule_revit_dark_palette,
    rule_xaml_parses,
    rule_clr_first,
    rule_assemblies_referenced,
    rule_banned,
    rule_every_window_has_drawer,
    rule_every_layout_loaded,
    rule_shrink_in_every_layout,
    rule_shrink_wired,
    rule_animation_released,
    rule_handlers_exist,
    rule_no_duplicate_defs,
    rule_changelog_has_version,
    rule_version_shown,
    rule_esc_kept_for_drawer,
]


# ===========================================================================
# selftest - every rule, deliberately broken
# ===========================================================================

def _replace(name, old, new, after=None):
    def apply(files):
        text = files[name]
        start = text.index(after) if after else 0
        head, tail = text[:start], text[start:]
        if old not in tail:
            raise AssertionError("breakage text not found in {0}: {1!r}"
                                 .format(name, old[:60]))
        files[name] = head + tail.replace(old, new, 1)
    return apply


def _append(name, extra):
    def apply(files):
        files[name] = files[name] + extra
    return apply


def _move_line_before(name, line, anchor):
    def apply(files):
        text = files[name]
        if line not in text or anchor not in text:
            raise AssertionError("breakage text not found in " + name)
        text = text.replace(line, "", 1)
        files[name] = text.replace(anchor, line + anchor, 1)
    return apply


BREAKAGES = [
    (rule_revit_dark_palette, "the old window grey put back",
     _replace("EditSystemDialog.xaml", 'x:Key="WinBg"    Color="#FF3C4454"',
              'x:Key="WinBg"    Color="#FF232326"')),
    (rule_revit_dark_palette, "a header bar off Revit's title colour",
     _replace("ResultsDialog.xaml",
              '<Border x:Name="header_bar" Grid.Row="0" Background="#FF212932"',
              '<Border x:Name="header_bar" Grid.Row="0" Background="#FF1B1F24"')),
    (rule_revit_dark_palette, "the old text grey in code",
     _replace("script.py", "Color.FromRgb(232, 240, 248)",
              "Color.FromRgb(228, 228, 228)")),
    (rule_xaml_parses, "a comment drawn with hyphens",
     _replace("ContainmentSystemCreator.xaml", "<!-- HINT -->",
              "<!-- -- HINT -- -->")),
    (rule_clr_first, "a System import above csc_clr",
     _move_line_before("script.py",
                       "from System.Windows.Media import SolidColorBrush, Color\n",
                       "import csc_clr")),
    (rule_clr_first, "a System import at load time in csc_drawer",
     _replace("csc_drawer.py", "import time\n",
              "import time\nfrom System.Windows import Window\n")),
    (rule_assemblies_referenced, "System.Windows.Forms dropped from csc_clr",
     _replace("csc_clr.py", '    "System.Windows.Forms",\n', "")),
    (rule_banned, "a bare IntegerValue",
     _append("script.py", "\n\ndef _probe(e):\n    return e.Id.IntegerValue\n")),
    (rule_banned, "System.Uri imported",
     _append("script.py", "\n\ndef _probe2():\n    from System import Uri\n    return Uri\n")),
    (rule_every_window_has_drawer, "ResultsDialog without a drawer",
     _replace("script.py", "        self.drawer = csc_drawer.attach(self)\n",
              "", after="class ResultsDialog")),
    (rule_every_layout_loaded, "a layout nobody loads",
     _replace("script.py", 'init_window(self, "ResultsDialog.xaml")',
              'init_window(self, "Results.xaml")')),
    (rule_shrink_in_every_layout, "a layout without the shrink button",
     _replace("EditSystemDialog.xaml", 'x:Name="shrink_btn"',
              'x:Name="shrink_button"')),
    (rule_shrink_in_every_layout, "the green arrow showing at start",
     _replace("ResultsDialog.xaml",
              '<Path x:Name="expand_glyph" Visibility="Collapsed"',
              '<Path x:Name="expand_glyph"')),
    (rule_shrink_wired, "the shrink button never wired",
     _replace("csc_drawer.py", "    window.shrink_btn.Click += drawer.on_button\n", "")),
    (rule_animation_released, "Height never released",
     _replace("csc_drawer.py",
              "            self.window.BeginAnimation(wpf.height_prop, None)",
              "            pass")),
    (rule_animation_released, "a Storyboard slide",
     _append("csc_drawer.py", "\n\ndef _slide2(w):\n    return Storyboard()\n")),
    (rule_handlers_exist, "a handler renamed in a layout",
     _replace("CreateSystemDialog.xaml", 'Click="reset_fullname"',
              'Click="reset_full_name"')),
    (rule_no_duplicate_defs, "a function defined twice",
     _append("script.py", "\n\ndef norm(text):\n    return text\n")),
    (rule_changelog_has_version, "no changelog entry for the version",
     _replace("CHANGELOG.md", "## v1.4.1 ", "## v1.3.9 ")),
    (rule_version_shown, "a window without its version",
     _replace("script.py", '        self.version_text.Text = "v" + __version__\n',
              "", after="class EditSystemDialog")),
    (rule_esc_kept_for_drawer, "pyRevit left holding Esc",
     _replace("script.py", "handle_esc=False", "handle_esc=True")),
]


def run(files):
    failures = 0
    for rule in RULES:
        problems = rule(files)
        status = "ok  " if not problems else "FAIL"
        print("  {0} {1}".format(status, rule.__name__))
        for problem in problems:
            print("         - " + problem)
        failures += len(problems)
    return failures


def selftest(files):
    covered = set()
    failures = 0
    for rule, label, breakage in BREAKAGES:
        if rule(files):
            print("  FAIL {0}: fails on the clean files".format(rule.__name__))
            failures += 1
            continue
        broken = dict(files)
        breakage(broken)
        if broken == files:
            print("  FAIL {0}: breakage '{1}' changed nothing".format(
                rule.__name__, label))
            failures += 1
            continue
        if rule(broken):
            print("  ok   {0} catches {1}".format(rule.__name__, label))
            covered.add(rule)
        else:
            print("  FAIL {0} misses {1}".format(rule.__name__, label))
            failures += 1
    for rule in RULES:
        if rule not in covered:
            print("  FAIL {0} has no proving breakage".format(rule.__name__))
            failures += 1
    return failures


def main(argv):
    files = load_files()
    if "--selftest" in argv:
        print("import_check --selftest")
        failures = selftest(files)
    else:
        print("import_check")
        failures = run(files)
    print("{0} problem(s)".format(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
