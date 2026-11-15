# -*- coding: utf-8 -*-
"""Bench check for Workset Management - run under plain CPython, away from Revit.

    python import_check.py              run every rule against the tool
    python import_check.py --selftest   break each rule on purpose, prove it fires

A blank white pyRevit window means the script died before any of it ran.
These rules catch, on the bench, every way that has happened in this
extension so far, plus the IronPython traps listed in the project notes.

Every rule works on a dict of file texts, so the selftest can break a copy
in memory and confirm the rule notices.  A rule that passes its own selftest
by matching a docstring is inert: the scans blank out strings and comments
first wherever that matters.
"""

import ast
import io
import os
import re
import shutil
import sys
import tempfile
import tokenize
import xml.dom.minidom

HERE = os.path.dirname(os.path.abspath(__file__))

MODULES = ["wsm_clr.py", "wsm_core.py", "wsm_revit.py", "wsm_runner.py", "wsm_xlsx.py",
           "wsm_ui.py", "wsm_table.py", "wsm_scope.py", "wsm_window.py"]
WINDOW_MODULES = ("wsm_window.py", "wsm_scope.py", "wsm_table.py")
LOADER = "script.py"
LAYOUT = "WorksetManagement.xaml"
THEME = "Theme.xaml"
CHANGELOG = "CHANGELOG.md"
PY_FILES = MODULES + [LOADER]

# namespace -> assemblies, any one of which provides it
ASSEMBLY_FOR = {
    "System": ["mscorlib", "System"],
    "System.IO": ["mscorlib"],
    "System.IO.Compression": ["System.IO.Compression", "System.IO.Compression.FileSystem"],
    "System.Text": ["mscorlib"],
    "System.Xml": ["System.Xml"],
    "System.Data": ["System.Data"],
    "System.Diagnostics": ["System"],
    "System.Collections.Generic": ["mscorlib", "System"],
    "System.Windows": ["PresentationFramework", "PresentationCore", "WindowsBase"],
    "System.Windows.Controls": ["PresentationFramework"],
    "System.Windows.Controls.Primitives": ["PresentationFramework"],
    "System.Windows.Data": ["PresentationFramework"],
    "System.Windows.Input": ["PresentationCore"],
    "System.Windows.Interop": ["PresentationFramework", "PresentationCore"],
    "System.Windows.Markup": ["PresentationFramework", "System.Xaml"],
    "System.Windows.Media": ["PresentationCore"],
    "System.Windows.Media.Imaging": ["PresentationCore"],
    "System.Windows.Threading": ["WindowsBase"],
    "System.Windows.Forms": ["System.Windows.Forms"],
    "Microsoft.Win32": ["PresentationFramework"],
}


# ================================================================ helpers

def load_sources(folder=HERE):
    texts = {}
    for name in PY_FILES + [LAYOUT, THEME, CHANGELOG]:
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            handle = io.open(path, "r", encoding="utf-8")
            try:
                texts[name] = handle.read()
            finally:
                handle.close()
    return texts


def code_only(text):
    """The source with every string and comment blanked, line structure kept,
    so a scan never trips over prose or its own documentation."""
    out = []
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except Exception:
        return text
    lines = text.splitlines(True)
    blanked = [list(line) for line in lines]
    for token in tokens:
        if token.type in (tokenize.STRING, tokenize.COMMENT) or \
                getattr(tokenize, "FSTRING_START", -1) == token.type:
            (srow, scol), (erow, ecol) = token.start, token.end
            for row in range(srow, erow + 1):
                if row - 1 >= len(blanked):
                    continue
                start = scol if row == srow else 0
                end = ecol if row == erow else len(blanked[row - 1])
                for col in range(start, end):
                    if blanked[row - 1][col] not in "\r\n":
                        blanked[row - 1][col] = " "
    for line in blanked:
        out.append("".join(line))
    return "".join(out)


def xml_names(text, attribute):
    return set(re.findall(r'{0}="([^"]+)"'.format(re.escape(attribute)), text))


def dynamic_keys(text):
    return set(re.findall(r"\{DynamicResource\s+([A-Za-z0-9_]+)\s*\}", text))


def theme_keys(text):
    return xml_names(text, "x:Key")


def palette_dicts(texts):
    tree = ast.parse(texts["wsm_core.py"])
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "PALETTES" for t in node.targets):
            return ast.literal_eval(node.value)
    return {}


# ================================================================ rules

def rule_xaml_parses(texts):
    problems = []
    for name in (LAYOUT, THEME):
        try:
            xml.dom.minidom.parseString(texts[name].encode("utf-8"))
        except Exception as err:
            problems.append("{0} does not parse: {1}".format(name, err))
    return problems


def rule_no_static_in_layout(texts):
    if "StaticResource" in texts[LAYOUT]:
        return ["{0} uses StaticResource - it is parsed before Theme.xaml is merged, "
                "which is a blank window".format(LAYOUT)]
    return []


def rule_no_baseline(texts):
    problems = []
    for name in (LAYOUT, THEME):
        if 'VerticalAlignment="Baseline"' in texts[name]:
            problems.append("{0}: VerticalAlignment=Baseline makes XamlReader throw".format(name))
    return problems


def rule_comment_dashes(texts):
    problems = []
    for name in (LAYOUT, THEME):
        for comment in re.findall(r"<!--(.*?)-->", texts[name], re.S):
            if "--" in comment:
                problems.append("{0}: '--' inside an XML comment".format(name))
    return problems


def code_resource_keys(texts):
    keys = set()
    for name in MODULES:
        text = texts.get(name, "")
        keys |= set(re.findall(r'ui\.(?:style|res)\([^)]*?"([A-Za-z]+)"\)', text))
        keys |= set(re.findall(r'(?<![a-z])style\([^)]*?"([A-Za-z]+)"\)', text))
        keys |= set(re.findall(r'res\([^)]*?"([A-Za-z]+)"\)', text))
        keys |= set(re.findall(r'FindResource\("([A-Za-z]+)"\)', text))
        keys |= set(re.findall(r'TryFindResource\("([A-Za-z]+)"\)', text))
        keys |= set(re.findall(r'"((?:Ws|)[A-Z][A-Za-z]*Brush)"', text))
    return keys


def rule_resource_keys_defined(texts):
    defined = theme_keys(texts[THEME]) | set(palette_dicts(texts).get("dark", {}).keys())
    wanted = dynamic_keys(texts[LAYOUT]) | dynamic_keys(texts[THEME])
    wanted |= set(k for k in code_resource_keys(texts) if k.startswith("Ws") or k.endswith("Brush"))
    # grid column cell styles are named in a table in the window module
    wanted |= set(re.findall(r'"(Ws[A-Za-z]+Text)"', texts["wsm_window.py"]))
    missing = sorted(k for k in wanted if k not in defined)
    return ["resource key '{0}' is used but defined nowhere".format(k) for k in missing]


def rule_palettes_match(texts):
    palettes = palette_dicts(texts)
    problems = []
    dark = set(palettes.get("dark", {}).keys())
    light = set(palettes.get("light", {}).keys())
    for key in sorted(dark ^ light):
        problems.append("palette key '{0}' is in only one of dark / light".format(key))
    brushes = set(re.findall(r'<SolidColorBrush x:Key="([A-Za-z]+)"', texts[THEME]))
    for key in sorted(dark - brushes):
        problems.append("palette key '{0}' has no default brush in Theme.xaml".format(key))
    for key in sorted(brushes - dark):
        problems.append("Theme.xaml brush '{0}' is not in the palettes, so it never "
                        "changes with the theme".format(key))
    return problems


def rule_findname(texts):
    names = xml_names(texts[LAYOUT], "x:Name")
    problems = []
    for module in MODULES:
        text = texts.get(module, "")
        for found in re.findall(r'(?:\bw|FindName)\("([A-Za-z0-9_]+)"\)', text):
            if found not in names:
                problems.append("{0}: FindName('{1}') has no x:Name in the layout".format(
                    module, found))
    return problems


def rule_handlers_exist(texts):
    problems = []
    for module in MODULES:
        tree = ast.parse(texts[module])
        for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
            methods = set(n.name for n in cls.body if isinstance(n, ast.FunctionDef))
            attrs = set()
            for node in ast.walk(cls):
                if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store) and \
                        isinstance(node.value, ast.Name) and node.value.id == "self":
                    attrs.add(node.attr)
            for node in ast.walk(cls):
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and \
                        node.value.id == "self" and node.attr.startswith("on_"):
                    if node.attr not in methods and node.attr not in attrs:
                        problems.append("{0}: {1}.{2} is wired but not defined".format(
                            module, cls.name, node.attr))
    return sorted(set(problems))


def rule_no_dup_defs(texts):
    problems = []
    for module in PY_FILES:
        tree = ast.parse(texts[module])
        scopes = [tree] + [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
        for scope in scopes:
            seen = set()
            for node in scope.body:
                if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                    if node.name in seen:
                        problems.append("{0}: {1} is defined twice - the second one "
                                        "silently wins".format(module, node.name))
                    seen.add(node.name)
    return problems


def rule_forbidden(texts):
    problems = []
    for module in PY_FILES:
        text = texts[module]
        try:
            tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
        except Exception as err:
            problems.append("{0} does not tokenize: {1}".format(module, err))
            continue
        for token in tokens:
            if getattr(tokenize, "FSTRING_START", -1) == token.type or (
                    token.type == tokenize.STRING and
                    re.match(r"^[rRbBuU]*[fF]", token.string)):
                problems.append("{0}:{1}: f-string".format(module, token.start[0]))
        code = code_only(text)
        for number, line in enumerate(code.splitlines(), 1):
            if re.match(r"^\s*print\s+[^\s(=]", line):
                problems.append("{0}:{1}: print statement".format(module, number))
            if re.search(r"\.None\b", line) and "getattr" not in line:
                problems.append("{0}:{1}: .None is a syntax error in IronPython - "
                                "use getattr(X, 'None')".format(module, number))
            if re.search(r"\bUri\b", line):
                problems.append("{0}:{1}: System.Uri moved assemblies at 2025".format(
                    module, number))
        try:
            tree = ast.parse(text)
        except SyntaxError as err:
            problems.append("{0}:{1}: does not parse - {2}".format(module, err.lineno, err.msg))
            continue
        allowed = ("eid_value", "wsid_value")
        for func in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
            if func.name in allowed:
                continue
            for node in ast.walk(func):
                if isinstance(node, ast.Attribute) and node.attr == "IntegerValue":
                    problems.append("{0}:{1}: bare .IntegerValue outside eid_value - removed "
                                    "in Revit 2026".format(module, node.lineno))
        for node in tree.body:
            for inner in ast.walk(node):
                if isinstance(inner, ast.Attribute) and inner.attr == "IntegerValue" and \
                        not isinstance(node, ast.FunctionDef):
                    problems.append("{0}:{1}: bare .IntegerValue at module level".format(
                        module, inner.lineno))
    return sorted(set(problems))


def rule_ascii(texts):
    problems = []
    for module in PY_FILES:
        for number, line in enumerate(texts[module].splitlines(), 1):
            try:
                line.encode("ascii")
            except UnicodeEncodeError:
                problems.append("{0}:{1}: non-ASCII character - use a \\u escape in a "
                                "u'' literal".format(module, number))
    return problems


def clr_list(texts):
    tree = ast.parse(texts["wsm_clr.py"])
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "ASSEMBLIES" for t in node.targets):
            return set(ast.literal_eval(node.value))
    return set()


def imported_namespaces(text):
    """(namespace, line, top level?) for every from-import of a .NET namespace."""
    found = []
    tree = ast.parse(text)
    top = set(id(n) for n in tree.body)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and \
                node.module.split(".")[0] in ("System", "Microsoft"):
            found.append((node.module, node.lineno, id(node) in top))
    return found


def rule_assemblies_referenced(texts):
    referenced = clr_list(texts)
    problems = []
    for module in MODULES:
        for namespace, line, _ in imported_namespaces(texts[module]):
            providers = ASSEMBLY_FOR.get(namespace)
            if providers is None:
                problems.append("{0}:{1}: {2} is not in the ASSEMBLY_FOR table - add it".format(
                    module, line, namespace))
            elif not referenced.intersection(providers):
                problems.append("{0}:{1}: {2} needs one of {3} in wsm_clr.ASSEMBLIES".format(
                    module, line, namespace, ", ".join(providers)))
    return problems


def rule_clr_first(texts):
    problems = []
    for module in MODULES:
        if module == "wsm_clr.py":
            continue
        tree = ast.parse(texts[module])
        clr_line = None
        for node in tree.body:
            if isinstance(node, ast.Import) and any(a.name == "wsm_clr" for a in node.names):
                clr_line = node.lineno
                break
        for namespace, line, top in imported_namespaces(texts[module]):
            if top and (clr_line is None or line < clr_line):
                problems.append("{0}:{1}: {2} imported before wsm_clr".format(
                    module, line, namespace))
    return problems


def rule_thin_loader(texts):
    tree = ast.parse(texts[LOADER])
    problems = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module and \
                node.module.split(".")[0] in ("System", "Autodesk", "Microsoft"):
            problems.append("script.py imports {0} at load - the loader must import "
                            "nothing that can fail".format(node.module))
        if isinstance(node, ast.Import) and any(a.name.startswith("wsm_") for a in node.names):
            problems.append("script.py imports a tool module outside the staged try")
    if "AddReference" in code_only(texts[LOADER]):
        problems.append("script.py calls clr.AddReference - that belongs in wsm_clr")
    return problems


def rule_style_target(texts):
    targets = {}
    dom = xml.dom.minidom.parseString(texts[THEME].encode("utf-8"))
    for node in dom.getElementsByTagName("Style"):
        key = node.getAttribute("x:Key")
        if key:
            targets[key] = node.getAttribute("TargetType").split(":")[-1]
    problems = []
    layout = xml.dom.minidom.parseString(texts[LAYOUT].encode("utf-8"))
    for node in layout.getElementsByTagName("*"):
        match = re.match(r"\{DynamicResource\s+(\w+)\s*\}", node.getAttribute("Style") or "")
        if match:
            want = targets.get(match.group(1))
            if want and want != node.tagName:
                problems.append("{0} carries style {1}, which targets {2} - WPF throws when "
                                "it is applied".format(node.tagName, match.group(1), want))
    return problems


def rule_based_on(texts):
    problems = []
    for name in (LAYOUT, THEME):
        if re.search(r'BasedOn="\{DynamicResource', texts[name]):
            problems.append("{0}: BasedOn cannot take a DynamicResource".format(name))
    return problems


def rule_changelog(texts):
    match = re.search(r'^VERSION = "([^"]+)"', texts["wsm_core.py"], re.M)
    version = match.group(1) if match else "?"
    if "## {0}".format(version) not in texts.get(CHANGELOG, ""):
        return ["CHANGELOG.md has no entry for {0}".format(version)]
    return []


# ---------------------------------------------------------------- init order

class InitReads(object):
    """Replay __init__ in source order, following self.method() calls, and
    report any self.attr read before anything has set it.  Calls inside
    nested functions and lambdas are handlers being wired, not work being
    done, so they are not followed."""

    def __init__(self, cls):
        self.methods = dict((n.name, n) for n in cls.body if isinstance(n, ast.FunctionDef))
        self.cls = cls.name
        self.set = set()
        for node in cls.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        self.set.add(target.id)
        self.problems = []
        self.stack = []

    def run(self):
        if "__init__" in self.methods:
            self.method("__init__")
        return self.problems

    def method(self, name):
        if name in self.stack or len(self.stack) > 12:
            return
        self.stack.append(name)
        for statement in self.methods[name].body:
            self.statement(statement)
        self.stack.pop()

    def statement(self, node):
        if isinstance(node, (ast.FunctionDef, ast.Lambda, ast.ClassDef)):
            return
        if isinstance(node, ast.Assign):
            self.expr(node.value)
            for target in node.targets:
                self.store(target)
            return
        if isinstance(node, ast.AugAssign):
            self.expr(node.value)
            self.store(node.target)
            return
        for field, value in ast.iter_fields(node):
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, ast.stmt):
                        self.statement(item)
                    elif isinstance(item, ast.AST):
                        self.expr(item)
            elif isinstance(value, ast.stmt):
                self.statement(value)
            elif isinstance(value, ast.AST):
                self.expr(value)

    def store(self, target):
        if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and \
                target.value.id == "self":
            self.set.add(target.attr)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for item in target.elts:
                self.store(item)
        else:
            self.expr(target)

    def expr(self, node):
        if node is None or isinstance(node, (ast.Lambda, ast.FunctionDef)):
            return
        if isinstance(node, ast.Call):
            func = node.func
            for arg in node.args:
                self.expr(arg)
            for keyword in node.keywords:
                self.expr(keyword.value)
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and \
                    func.value.id == "self" and func.attr in self.methods:
                self.method(func.attr)
                return
            self.expr(func)
            return
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and \
                node.value.id == "self":
            if node.attr not in self.set and node.attr not in self.methods:
                self.problems.append("{0}: self.{1} is read in {2} before anything sets "
                                     "it".format(self.cls, node.attr, " -> ".join(self.stack)))
            return
        for child in ast.iter_child_nodes(node):
            self.expr(child)


def rule_init_reads(texts):
    problems = []
    for module in ("wsm_window.py", "wsm_ui.py", "wsm_table.py", "wsm_scope.py"):
        tree = ast.parse(texts[module])
        for cls in [n for n in tree.body if isinstance(n, ast.ClassDef)]:
            problems.extend(InitReads(cls).run())
    return sorted(set(problems))


# ---------------------------------------------------------------- names

try:
    import builtins as _builtins
except ImportError:                      # Python 2
    import __builtin__ as _builtins

BUILTIN_NAMES = set(dir(_builtins)) | set(["__file__", "__name__", "__revit__",
                                           "unicode", "basestring", "long", "xrange"])


def _bound_in(node):
    """Names a function binds: parameters, assignments, loops, imports,
    except-as, with-as, comprehensions, nested defs, global/nonlocal."""
    names = set()
    args = node.args
    for arg in list(args.args) + list(getattr(args, "kwonlyargs", [])) + \
            list(getattr(args, "posonlyargs", [])):
        names.add(arg.arg)
    for extra in (args.vararg, args.kwarg):
        if extra is not None:
            names.add(extra.arg)
    for inner in ast.walk(node):
        if isinstance(inner, ast.Name) and isinstance(inner.ctx, (ast.Store, ast.Del)):
            names.add(inner.id)
        elif isinstance(inner, (ast.FunctionDef, ast.ClassDef)) and inner is not node:
            names.add(inner.name)
        elif isinstance(inner, (ast.Import, ast.ImportFrom)):
            for alias in inner.names:
                names.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(inner, ast.ExceptHandler) and inner.name:
            names.add(inner.name)
        elif isinstance(inner, (ast.Global, ast.Nonlocal)):
            names.update(inner.names)
        elif isinstance(inner, ast.arg):
            names.add(inner.arg)
    return names


def rule_names_defined(texts):
    """Every name a function reads is bound somewhere it can see.  Catches a
    name dropped from an import, which loads fine and then dies with a
    NameError the first time that code runs - usually in front of the user."""
    problems = []
    for module in PY_FILES:
        try:
            tree = ast.parse(texts[module])
        except SyntaxError:
            continue
        module_names = set(BUILTIN_NAMES)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    module_names.add((alias.asname or alias.name).split(".")[0])
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                module_names.add(node.name)
            for inner in ast.walk(node):
                if isinstance(inner, ast.Name) and isinstance(inner.ctx, ast.Store) and \
                        not isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                    module_names.add(inner.id)
            if isinstance(node, ast.ClassDef):
                pass
        functions = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
        for func in functions:
            visible = set(module_names)
            for outer in functions:
                if outer is not func and any(inner is func for inner in ast.walk(outer)):
                    visible |= _bound_in(outer)
            visible |= _bound_in(func)
            for inner in ast.walk(func):
                if isinstance(inner, ast.Lambda):
                    for arg in inner.args.args:
                        visible.add(arg.arg)
            for inner in ast.walk(func):
                if isinstance(inner, ast.Name) and isinstance(inner.ctx, ast.Load) and \
                        inner.id not in visible:
                    problems.append("{0}:{1}: '{2}' is not defined - a NameError when this "
                                    "runs".format(module, inner.lineno, inner.id))
    return sorted(set(problems))


# ---------------------------------------------------------------- modeless

MODEL_CALLS = ("read_model", "apply_manage", "apply_assignments", "make_editable",
               "show_in_3d", "isolate_worksets", "unisolate", "zoom_view",
               "checkout_worksets", "checkout_elements", "read_worksets", "scan_model",
               "read_scope_boxes", "apply_scope")


def rule_persistent_engine(texts):
    tree = ast.parse(texts[LOADER])
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "__persistentengine__" for t in node.targets):
            if isinstance(node.value, ast.Constant) and node.value.value is True:
                return []
    return ["script.py must set __persistentengine__ = True - a modeless window's "
            "handlers die with the engine otherwise"]


def rule_raise_status(texts):
    """Raise()'s answer decides whether the job stays queued; a bare call
    throws it away."""
    problems = []
    for module in MODULES:
        tree = ast.parse(texts[module])
        for node in ast.walk(tree):
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and \
                    isinstance(node.value.func, ast.Attribute) and node.value.func.attr == "Raise":
                problems.append("{0}:{1}: Raise() called without reading its status".format(
                    module, node.lineno))
    return problems


def rule_owner_before_show(texts):
    tree = ast.parse(texts["wsm_window.py"])
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "show":
            source = ast.get_source_segment(texts["wsm_window.py"], node) or ""
            own = source.find("ui.own(")
            show = source.find(".Show()")
            if show < 0:
                return ["MainWindow.show never calls Show()"]
            if own < 0 or own > show:
                return ["MainWindow.show must own the window to Revit before Show() - an "
                        "unowned modeless window slips behind Revit"]
            return []
    return ["MainWindow.show not found"]


def rule_model_calls_in_jobs(texts):
    """A modeless window may only touch the model inside a job handed to the
    ExternalEvent - a nested work() function.  The one exception is the first
    read in __init__, which runs while the command still holds the API."""
    problems = []
    for module in WINDOW_MODULES:
        problems.extend(_model_calls(module, texts[module]))
    return problems


def _model_calls(module, text):
    problems = []
    tree = ast.parse(text)
    for cls in [n for n in tree.body if isinstance(n, ast.ClassDef)]:
        for method in [n for n in cls.body if isinstance(n, ast.FunctionDef)]:
            nested = set()
            for inner in ast.walk(method):
                if isinstance(inner, (ast.FunctionDef, ast.Lambda)) and inner is not method:
                    for deep in ast.walk(inner):
                        nested.add(id(deep))
            for node in ast.walk(method):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "revit"
                        and node.func.attr in MODEL_CALLS):
                    continue
                if id(node) in nested:
                    continue
                if method.name == "__init__" and node.func.attr == "read_model":
                    continue
                problems.append("{0}:{1}: {2}.{3} calls revit.{4} outside a queued "
                                "job".format(module, node.lineno, cls.name, method.name,
                                             node.func.attr))
    return problems


def rule_egg_logo_only(texts):
    """egg_hook.attach / attach_to_window arm the whole window, so clicks on
    rows and headings counted towards the game.  Only launch, behind a counter
    on the logo that any other click resets."""
    code = code_only(texts["wsm_ui.py"])
    problems = []
    if re.search(r"egg_hook\.attach", code):
        problems.append("wsm_ui.py calls egg_hook.attach - it arms the whole window")
    if "egg_hook.launch" not in code and "hook.launch" not in code:
        problems.append("wsm_ui.py never calls launch - the egg is gone")
    if "PreviewMouseLeftButtonDown += counter.on_window" not in code:
        problems.append("the logo counter is not reset by clicks elsewhere in the window")
    return problems


# ---------------------------------------------------------------- loading

def rule_modules_load(texts):
    """Every module imports against the strict stub API.  Run from a temp copy
    so the selftest can load a broken text."""
    folder = tempfile.mkdtemp(prefix="wsm_check_")
    try:
        for name, text in texts.items():
            if name.endswith(".py"):
                handle = io.open(os.path.join(folder, name), "w", encoding="utf-8")
                try:
                    handle.write(text)
                finally:
                    handle.close()
        shutil.copy(os.path.join(HERE, "bench_stubs.py"), folder)
        sys.path.insert(0, folder)
        problems = []
        try:
            for cached in [m for m in list(sys.modules) if m == "bench_stubs"]:
                del sys.modules[cached]
            import bench_stubs
            bench_stubs.install()
            for module in MODULES:
                try:
                    __import__(module[:-3])
                except Exception as err:
                    problems.append("{0} does not load against the real namespaces: "
                                    "{1}".format(module, err))
        finally:
            sys.path.remove(folder)
            for cached in [m for m in list(sys.modules)
                           if m.startswith("wsm_") or m == "bench_stubs"]:
                del sys.modules[cached]
        return problems
    finally:
        shutil.rmtree(folder, ignore_errors=True)


RULES = [
    rule_xaml_parses, rule_no_static_in_layout, rule_no_baseline, rule_comment_dashes,
    rule_resource_keys_defined, rule_palettes_match, rule_findname, rule_handlers_exist,
    rule_no_dup_defs, rule_forbidden, rule_ascii, rule_assemblies_referenced,
    rule_clr_first, rule_thin_loader, rule_style_target, rule_based_on, rule_changelog,
    rule_init_reads, rule_names_defined, rule_persistent_engine, rule_raise_status,
    rule_owner_before_show, rule_model_calls_in_jobs, rule_egg_logo_only,
    rule_modules_load,
]


# ================================================================ selftest

def _sub(name, old, new):
    def breaker(texts):
        if old not in texts[name]:
            raise AssertionError("selftest anchor missing in {0}: {1!r}".format(name, old))
        texts[name] = texts[name].replace(old, new, 1)
    return breaker


def _append(name, extra):
    def breaker(texts):
        texts[name] = texts[name] + extra
    return breaker


BREAKAGES = [
    (rule_xaml_parses, _sub(LAYOUT, "<!-- resize grips", "<!-- a -- b --><!-- resize grips")),
    (rule_no_static_in_layout, _sub(LAYOUT, 'Style="{DynamicResource WsChip}"',
                                    'Style="{StaticResource WsChip}"')),
    (rule_no_baseline, _sub(LAYOUT, 'x:Name="VersionText" Grid.Column="4"',
                            'x:Name="VersionText" VerticalAlignment="Baseline" Grid.Column="4"')),
    (rule_comment_dashes, _sub(THEME, "<!-- tab strip -->", "<!-- tab -- strip -->")),
    (rule_resource_keys_defined, _sub(LAYOUT, "{DynamicResource WsChip}",
                                      "{DynamicResource WsChipp}")),
    (rule_resource_keys_defined, _sub("wsm_window.py", 'ui.style(caret, "WsCaret")',
                                      'ui.style(caret, "WsCarrot")')),
    (rule_palettes_match, _sub("wsm_core.py", '"TickBrush": "#FFFFFF",', "")),
    (rule_findname, _sub("wsm_window.py", 'w("NewButton")', 'w("NewButon")')),
    (rule_handlers_exist, _sub("wsm_window.py", "def on_revert_all(", "def on_revert_everything(")),
    (rule_no_dup_defs, _append("wsm_core.py", "\n\ndef to_text(value):\n    return value\n")),
    (rule_forbidden, _append("wsm_core.py", '\n\nNAME = f"{TOOL_NAME}"\n')),
    (rule_forbidden, _append("wsm_core.py", "\n\ndef shout():\n    print 'x'\n")),
    (rule_forbidden, _append("wsm_revit.py", "\n\ndef bad(e):\n    return e.IntegerValue\n")),
    (rule_forbidden, _append("wsm_ui.py", "\n\ndef bad():\n    return WindowStyle.None\n")),
    (rule_forbidden, _append("wsm_ui.py", "\n\ndef bad():\n    from System import Uri\n")),
    (rule_ascii, _append("wsm_core.py", u"\n\nARROW = u'\u2192'\n")),
    (rule_assemblies_referenced, _sub("wsm_clr.py", '"System.Data", ', "")),
    (rule_clr_first, _sub("wsm_xlsx.py", "import wsm_clr  # noqa: F401  (assemblies first)\n",
                          "from System.Text import Encoding\nimport wsm_clr  # noqa: F401\n")),
    (rule_thin_loader, _sub(LOADER, "import traceback\n",
                            "import traceback\nfrom System.Windows import Window\n")),
    (rule_style_target, _sub(LAYOUT, '<Button x:Name="NewButton" Style="{DynamicResource WsButton}"',
                             '<Button x:Name="NewButton" Style="{DynamicResource WsCheck}"')),
    (rule_based_on, _sub(THEME, 'BasedOn="{StaticResource WsButton}"',
                         'BasedOn="{DynamicResource WsButton}"')),
    (rule_changelog, _sub("wsm_core.py", 'VERSION = "', 'VERSION = "9.')),
    (rule_init_reads, _sub("wsm_window.py", "        self.case_mode = \"keep\"\n", "")),
    (rule_persistent_engine, _sub(LOADER, "__persistentengine__ = True", "__persistentengine__ = False")),
    (rule_raise_status, _sub("wsm_runner.py", "status = core.to_text(self.event.Raise().ToString())",
                             "self.event.Raise()\n            status = u'Accepted'")),
    (rule_owner_before_show, _sub("wsm_window.py", "        ui.own(self.window, self.uiapp)\n", "")),
    (rule_model_calls_in_jobs, _append("wsm_window.py", "\n\nclass Hasty(object):\n"
                                       "    def on_go(self, sender, args):\n"
                                       "        revit.apply_manage(None, {}, True, None)\n")),
    (rule_model_calls_in_jobs, _sub("wsm_scope.py", "    def on_refresh(self, sender, args):\n",
                                    "    def on_refresh(self, sender, args):\n"
                                    "        revit.read_scope_boxes(self.main.doc)\n")),
    (rule_init_reads, _sub("wsm_table.py", "        self.headers = {}\n", "")),
    (rule_egg_logo_only, _sub("wsm_ui.py", "        logo.MouseLeftButtonDown += counter.on_logo\n",
                              "        egg_hook.attach_to_window(window)\n"
                              "        logo.MouseLeftButtonDown += counter.on_logo\n")),
    (rule_egg_logo_only, _sub("wsm_ui.py", "        window.PreviewMouseLeftButtonDown += counter.on_window\n", "")),
    (rule_names_defined, _sub("wsm_ui.py", "                            LogicalTreeHelper,\n", "")),
    (rule_modules_load, _sub("wsm_window.py", "import wsm_xlsx as xlsx", "import wsm_xlsxx as xlsx")),
    (rule_modules_load, _sub("wsm_ui.py", "from System.Windows.Media import (ColorConverter, FontFamily,",
                             "from System.Windows.Media import (ColorConverter, FontFamily, LogicalTreeHelper,")),
]


def run(texts):
    failures = 0
    for rule in RULES:
        problems = rule(texts)
        if problems:
            failures += len(problems)
            print("  FAIL  {0}".format(rule.__name__))
            for line in problems:
                print("          " + line)
        else:
            print("  ok    {0}".format(rule.__name__))
    return failures


def selftest():
    base = load_sources()
    misses = 0
    for rule, breaker in BREAKAGES:
        if rule(dict(base)):
            print("  SKIP  {0} - fails on the clean tree, fix that first".format(rule.__name__))
            misses += 1
            continue
        broken = dict(base)
        breaker(broken)
        if rule(broken):
            print("  ok    {0} catches its breakage".format(rule.__name__))
        else:
            print("  MISS  {0} did not notice its breakage - the rule is inert".format(
                rule.__name__))
            misses += 1
    covered = set(rule for rule, _ in BREAKAGES)
    for rule in RULES:
        if rule not in covered:
            print("  MISS  {0} has no breakage in the selftest".format(rule.__name__))
            misses += 1
    return misses


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        bad = selftest()
        print("\n{0} breakages, {1} missed.".format(len(BREAKAGES), bad))
    else:
        bad = run(load_sources())
        print("\n{0} rules, {1} problem(s).".format(len(RULES), bad))
    sys.exit(1 if bad else 0)
