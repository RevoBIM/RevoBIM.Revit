# -*- coding: utf-8 -*-
"""Bench check for the View Template Manager.

Run it on a desktop Python 3 before shipping, from this folder:

    python import_check.py              the checks
    python import_check.py --selftest   break every rule on purpose, and prove
                                        each breakage is caught

The modules are loaded against a stub Revit and .NET API that declares each
name in the namespace the real API puts it in, so a mis-namespaced import fails
here instead of showing up in Revit as a blank white pyRevit window. Every
other rule is static. Each failure is tagged with its rule, which is how the
selftest knows the right rule caught its breakage rather than some other one.

Rules:
  xaml_parses        every .xaml parses as XML
  static_resource    no StaticResource in a layout (Theme.xaml is merged later)
  dynamic_keys       every DynamicResource key a layout asks for is defined
  style_target       a Style key is only used on the type it targets
  find_name          every find("X") / FindName("X") has an x:Name in a layout
  handlers           every `+= self.on_x` handler is defined
  fstring            no f-strings (found from tokens, not by regex)
  print              no print statements
  uri                no System.Uri (it moved assemblies in Revit 2025)
  integer_value      no bare .IntegerValue outside eid_value
  compiles           every module compiles
  clr_first          vtm_clr is imported before any System.* / Autodesk.* line
  assemblies         every System.* namespace imported maps to an assembly
                     vtm_clr references - the only rule that can catch a
                     missing clr.AddReference, since a stub has no assemblies
  palette_parity     both palettes carry exactly the same keys
  palette_theme      every palette key is a brush in Theme.xaml and back
  brush_keys         every theme.brush("K") names a palette key
  duplicate_defs     no function defined twice in one scope - the second wins
  version            script.py and vtm_core agree, and CHANGELOG has the entry
  imports            every module loads against the stub API

Found by review in 1.2.0, kept so they cannot come back:
  header_style       a column's HeaderStyle is never set to None or to a
                     lookup that can be None - a local None outranks the
                     grid's ColumnHeaderStyle and drops to the system header
  drag_refreeze      the freeze is not put back synchronously in
                     ColumnHeaderDragCompleted - WPF checks the drop after it
  header_chevron     the header menu handler checks it was the chevron:
                     DataGridColumnHeader is a ButtonBase, so any click on a
                     heading raises Click

Shrink to the taskbar (1.3.0):
  shrink_button      every layout has a ShrinkButton in its HeaderBar, styled
                     BtnShrink
  shrink_drawer      every window class that loads a layout builds a Drawer
                     from that ShrinkButton - a button drawn but never wired
                     is a dead button
  shrink_input       every window's header handler asks drawer.header_down
                     and its key handler asks drawer.handle_key first, so a
                     parked bar is dragged / reopened rather than closed
  shrink_release     Drawer.finish stops the timer and clears `sliding` - a
                     slide never released leaves a window that will not move
  shrink_size        save_settings reads drawer.true_size(), so closing a
                     parked window never saves a 54-pixel window
"""

import ast
import io
import os
import re
import shutil
import sys
import tempfile
import tokenize
import types
import xml.dom.minidom

HERE = os.path.dirname(os.path.abspath(__file__))
MODULES = ["vtm_clr", "vtm_settings", "vtm_theme", "vtm_core", "vtm_drawer",
           "vtm_window"]
SOURCES = MODULES + ["script"]
LAYOUTS = ["ViewTemplateManager.xaml", "ViewTemplateReport.xaml"]
THEME = "Theme.xaml"
NEEDS_CLR = ["vtm_theme", "vtm_core", "vtm_drawer", "vtm_window"]

# What each namespace is allowed to hand out. Anything asked for that is not
# listed is a mis-namespaced import and fails the check.
DECLARED = {
    "System": ["Action", "Convert", "Double", "Enum", "TimeSpan"],
    "System.IO": ["File", "MemoryStream", "StringReader"],
    "System.Threading": ["Thread"],
    "System.Xml": ["XmlReader"],
    "System.Collections.Generic": ["List"],
    "System.Windows": ["Clipboard", "CornerRadius", "DataTemplate",
                       "FrameworkElement", "FrameworkElementFactory",
                       "HorizontalAlignment", "Point", "PresentationSource",
                       "Rect", "RoutedEventHandler", "Setter", "SizeToContent",
                       "Style",
                       "SystemParameters", "TextTrimming", "Thickness",
                       "VerticalAlignment", "Visibility", "Window"],
    "System.Windows.Controls": ["Border", "Canvas", "CheckBox", "ComboBox",
                                "DataGrid", "DataGridCell", "DataGridColumn",
                                "DataGridLength",
                                "DataGridTemplateColumn",
                                "ScrollChangedEventHandler", "ScrollViewer",
                                "StackPanel", "TextBlock", "TextBox"],
    "System.Windows.Controls.Primitives": ["ButtonBase",
                                           "DataGridCellsPresenter",
                                           "DataGridColumnHeader", "Popup",
                                           "Thumb", "ToggleButton"],
    "System.Windows.Data": ["Binding", "IValueConverter"],
    "System.Windows.Forms": ["Screen"],
    "System.Windows.Input": ["Cursors", "Key", "Keyboard", "ModifierKeys"],
    "System.Windows.Interop": ["WindowInteropHelper"],
    "System.Windows.Markup": ["XamlReader"],
    "System.Windows.Media": ["ColorConverter", "SolidColorBrush",
                             "VisualTreeHelper"],
    "System.Windows.Media.Imaging": ["BitmapCacheOption", "BitmapImage"],
    "System.Windows.Threading": ["DispatcherPriority", "DispatcherTimer"],
    "Autodesk.Revit": ["DB", "UI"],
}

# Which assemblies can provide each namespace. One of them must be in
# vtm_clr.ASSEMBLIES. Autodesk.* is pyRevit's own and is never referenced.
ASSEMBLY_FOR = {
    "System": ["mscorlib", "System"],
    "System.IO": ["mscorlib"],
    "System.Threading": ["mscorlib"],
    "System.Collections.Generic": ["mscorlib"],
    "System.Xml": ["System.Xml"],
    "System.Windows": ["PresentationFramework", "PresentationCore", "WindowsBase"],
    "System.Windows.Controls": ["PresentationFramework"],
    "System.Windows.Controls.Primitives": ["PresentationFramework"],
    "System.Windows.Data": ["PresentationFramework"],
    "System.Windows.Forms": ["System.Windows.Forms"],
    "System.Windows.Input": ["PresentationCore"],
    "System.Windows.Interop": ["PresentationFramework", "PresentationCore"],
    "System.Windows.Markup": ["PresentationFramework"],
    "System.Windows.Media": ["PresentationCore"],
    "System.Windows.Media.Imaging": ["PresentationCore"],
    "System.Windows.Threading": ["WindowsBase"],
}

# Names the code is allowed to reach for on Autodesk.Revit.DB.
DB_NAMES = [
    "BuiltInParameter", "Element", "ElementId", "FailureProcessingResult",
    "FilteredElementCollector", "IFailuresPreprocessor", "LabelUtils",
    "Phase", "PhaseFilter", "SpecTypeId", "StorageType", "Transaction",
    "View", "ViewFamilyType", "DisplayStyle", "PartsVisibility",
    "ViewDetailLevel", "ViewDiscipline",
]


# --------------------------------------------------------------------------
# the stub API
# --------------------------------------------------------------------------


def _make_class(name):
    return type(str(name), (object,), {"__stub__": True})


class StubModule(types.ModuleType):
    def __init__(self, name, allowed=None):
        types.ModuleType.__init__(self, name)
        self._allowed = allowed
        self._cache = {}

    def __getattr__(self, item):
        if item.startswith("__"):
            raise AttributeError(item)
        if item in self._cache:
            return self._cache[item]
        if self._allowed is not None and item not in self._allowed:
            raise ImportError(
                "'{0}' is not in {1} - check the namespace".format(item, self.__name__))
        made = _make_class(item)
        self._cache[item] = made
        return made


def install_stubs():
    clr_module = types.ModuleType("clr")
    clr_module.AddReference = lambda *args, **kwargs: None
    clr_module.GetClrType = lambda *args, **kwargs: None
    sys.modules["clr"] = clr_module

    for name, allowed in DECLARED.items():
        sys.modules[name] = StubModule(name, allowed)
    for name in ["Autodesk", "System.Collections"]:
        if name not in sys.modules:
            sys.modules[name] = StubModule(name, None)

    db = StubModule("Autodesk.Revit.DB", DB_NAMES)
    sys.modules["Autodesk.Revit.DB"] = db
    ui = StubModule("Autodesk.Revit.UI", None)
    sys.modules["Autodesk.Revit.UI"] = ui
    revit = sys.modules["Autodesk.Revit"]
    revit._cache["DB"] = db
    revit._cache["UI"] = ui
    # `import Autodesk.Revit.UI as x` walks the packages by attribute, so each
    # parent has to hand back the real stub child, not a made-up class.
    for name in list(sys.modules.keys()):
        if "." not in name or not isinstance(sys.modules[name], StubModule):
            continue
        parent, child = name.rsplit(".", 1)
        holder = sys.modules.get(parent)
        if isinstance(holder, StubModule):
            holder._cache[child] = sys.modules[name]


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


class Checker(object):
    def __init__(self, folder):
        self.folder = folder
        self.failures = []

    def fail(self, rule, message):
        self.failures.append("[{0}] {1}".format(rule, message))

    def read(self, name):
        with io.open(os.path.join(self.folder, name), "r", encoding="utf-8") as handle:
            return handle.read()

    # ------------------------------------------------------------ python

    @staticmethod
    def tokens(text):
        try:
            return list(tokenize.generate_tokens(io.StringIO(text).readline))
        except Exception:
            return []

    def code_only(self, text):
        """Source with comments and string literals blanked, line count kept,
        so a rule about code is never tripped by prose describing it."""
        lines = text.split("\n")
        for token in self.tokens(text):
            kind = token.type
            if kind not in (tokenize.COMMENT, tokenize.STRING) and \
                    tokenize.tok_name.get(kind, "") not in ("FSTRING_MIDDLE",):
                continue
            (sr, sc), (er, ec) = token.start, token.end
            for row in range(sr, er + 1):
                line = lines[row - 1]
                start = sc if row == sr else 0
                end = ec if row == er else len(line)
                lines[row - 1] = line[:start] + " " * (end - start) + line[end:]
        return "\n".join(lines)

    def check_python(self, module):
        name = module + ".py"
        text = self.read(name)
        bare = self.code_only(text)

        try:
            compile(text, name, "exec")
        except SyntaxError as error:
            self.fail("compiles", "{0}: will not compile - {1}".format(name, error))
            return

        for token in self.tokens(text):
            kind = tokenize.tok_name.get(token.type, "")
            if kind == "FSTRING_START":
                self.fail("fstring", "{0}:{1}: f-string - IronPython cannot parse "
                          "it.".format(name, token.start[0]))
            elif token.type == tokenize.STRING:
                prefix = re.match(r"^([A-Za-z]*)", token.string).group(1).lower()
                if "f" in prefix:
                    self.fail("fstring", "{0}:{1}: f-string - IronPython cannot "
                              "parse it.".format(name, token.start[0]))

        if re.search(r"^\s*print\s*[\(\s]", bare, re.M):
            self.fail("print", "{0}: print statement.".format(name))
        if re.search(r"\bSystem\s*\.\s*Uri\b|from\s+System\s+import\s+[^\n]*\bUri\b",
                     bare):
            self.fail("uri", "{0}: System.Uri - it moved assemblies in Revit "
                      "2025.".format(name))

        tree = ast.parse(text)
        helper = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "eid_value":
                for inner in ast.walk(node):
                    helper.add(id(inner))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "IntegerValue" \
                    and id(node) not in helper:
                self.fail("integer_value", "{0}:{1}: bare .IntegerValue outside "
                          "eid_value - gone in Revit 2026.".format(name, node.lineno))

        self.check_duplicates(name, tree)
        if module == "vtm_window":
            self.check_window_rules(name, tree)
        self.check_handlers(name, tree, bare)
        if module in NEEDS_CLR:
            self.check_clr_first(name, tree)
        self.check_assemblies(name, tree)

    def check_window_rules(self, name, tree):
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Attribute) and target.attr == "HeaderStyle":
                        value = node.value
                        if (isinstance(value, ast.Constant) and value.value is None) or \
                                (isinstance(value, ast.Call) and
                                 isinstance(value.func, ast.Attribute) and
                                 value.func.attr == "get"):
                            self.fail("header_style", "{0}:{1}: HeaderStyle set to "
                                      "something that can be None - clear it with "
                                      "ClearValue instead.".format(name, node.lineno))
            if isinstance(node, ast.FunctionDef):
                if node.name == "on_header_drag_completed":
                    for stmt in node.body:
                        call = getattr(stmt, "value", None)
                        if isinstance(call, ast.Call) and \
                                isinstance(call.func, ast.Attribute) and \
                                call.func.attr == "refreeze":
                            self.fail("drag_refreeze", "{0}:{1}: refreeze() called "
                                      "straight from DragCompleted - WPF checks the "
                                      "drop after it; defer it.".format(name, stmt.lineno))
                if node.name == "on_header_menu":
                    source = ast.get_source_segment(self.read(name), node) or ""
                    if "PART_HeaderMenu" not in source:
                        self.fail("header_chevron", "{0}:{1}: on_header_menu does "
                                  "not check the click came from the chevron.".format(
                                      name, node.lineno))

    def check_shrink(self):
        for layout in LAYOUTS:
            text = self.read(layout)
            start = text.find('x:Name="HeaderBar"')
            end = text.find("</Border>", start)
            header = text[start:end] if start >= 0 else ""
            if not re.search(r'x:Name="ShrinkButton"[^>]*Style="\{DynamicResource '
                             r'BtnShrink\}"', header):
                self.fail("shrink_button", "{0}: no ShrinkButton styled BtnShrink in "
                          "the HeaderBar.".format(layout))

        source = self.read("vtm_window.py")
        tree = ast.parse(source)
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            text = ast.get_source_segment(source, node) or ""
            if "load_window(" not in text:
                continue
            if not re.search(r'Drawer\((?:(?!\)\n).){0,200}?find\("ShrinkButton"\)',
                             text, re.S):
                self.fail("shrink_drawer", "vtm_window.{0}: loads a window but builds "
                          "no Drawer from its ShrinkButton.".format(node.name))
            methods = dict((m.name, m) for m in node.body
                           if isinstance(m, ast.FunctionDef))
            for handler, call in (("on_drag", "drawer.header_down"),
                                  ("on_key", "drawer.handle_key")):
                method = methods.get(handler)
                body = ast.get_source_segment(source, method) if method else ""
                body = self.code_only(body or "") if handler == "on_drag" else body
                if call not in (body or ""):
                    self.fail("shrink_input", "vtm_window.{0}.{1} does not ask {2} "
                              "first.".format(node.name, handler, call))
                    continue
                code = self.code_only(body)
                if handler == "on_key" and "Escape" in code and \
                        code.index(call) > code.index("Escape"):
                    self.fail("shrink_input", "vtm_window.{0}.on_key handles Escape "
                              "before the drawer sees it.".format(node.name))

        save = re.search(r"def save_settings\(self\):.*?(?=\n    def |\Z)", source, re.S)
        if save is None or "drawer.true_size()" not in save.group(0):
            self.fail("shrink_size", "vtm_window.save_settings does not use "
                      "drawer.true_size().")

        drawer = self.read("vtm_drawer.py")
        finish = re.search(r"    def finish\(self\):.*?(?=\n    def )", drawer, re.S)
        body = self.code_only(finish.group(0)) if finish else ""
        if "self.timer.Stop()" not in body or "self.sliding = False" not in body:
            self.fail("shrink_release", "vtm_drawer.Drawer.finish must stop the timer "
                      "and clear sliding.")

    def check_duplicates(self, name, tree):
        scopes = [tree] + [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
        for scope in scopes:
            seen = {}
            for node in scope.body:
                if isinstance(node, ast.FunctionDef):
                    if node.name in seen:
                        self.fail("duplicate_defs", "{0}:{1}: {2} defined twice "
                                  "(first at {3}) - the second silently wins.".format(
                                      name, node.lineno, node.name, seen[node.name]))
                    seen.setdefault(node.name, node.lineno)

    def check_handlers(self, name, tree, bare):
        defined = set(n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
        for match in re.finditer(r"\+=[ \t]*self\.(\w+)[ \t]*$", bare, re.M):
            if match.group(1) not in defined:
                line = bare[:match.start()].count("\n") + 1
                self.fail("handlers", "{0}:{1}: handler self.{2} is not "
                          "defined.".format(name, line, match.group(1)))

    def check_clr_first(self, name, tree):
        clr_line = None
        for node in tree.body:
            if isinstance(node, ast.Import) and \
                    any(a.name == "vtm_clr" for a in node.names):
                clr_line = node.lineno
                break
        for node in tree.body:
            module = None
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
            elif isinstance(node, ast.Import):
                module = node.names[0].name
            if module and (module.startswith("System") or module.startswith("Autodesk")):
                if clr_line is None or node.lineno < clr_line:
                    self.fail("clr_first", "{0}:{1}: {2} imported before vtm_clr - "
                              "its assembly may not be referenced yet.".format(
                                  name, node.lineno, module))
                return

    def referenced(self):
        tree = ast.parse(self.read("vtm_clr.py"))
        for node in tree.body:
            if isinstance(node, ast.Assign) and \
                    any(getattr(t, "id", "") == "ASSEMBLIES" for t in node.targets):
                return set(ast.literal_eval(node.value))
        return set()

    def check_assemblies(self, name, tree):
        have = self.referenced()
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            module = node.module
            if not module.startswith("System"):
                continue
            providers = ASSEMBLY_FOR.get(module)
            if providers is None:
                self.fail("assemblies", "{0}:{1}: {2} is not in the assembly table "
                          "- add it.".format(name, node.lineno, module))
            elif not have.intersection(providers):
                self.fail("assemblies", "{0}:{1}: {2} needs one of {3} in "
                          "vtm_clr.ASSEMBLIES.".format(name, node.lineno, module,
                                                       ", ".join(providers)))

    # ------------------------------------------------------------ xaml

    def theme_styles(self):
        """{style key: target type name} from Theme.xaml."""
        out = {}
        text = self.read(THEME)
        for match in re.finditer(
                r'<Style\s+x:Key="([^"]+)"\s+TargetType="\{x:Type (\w+)\}"', text):
            out[match.group(1)] = match.group(2)
        return out

    def check_xaml(self):
        for name in LAYOUTS + [THEME]:
            try:
                xml.dom.minidom.parseString(self.read(name).encode("utf-8"))
            except Exception as error:
                self.fail("xaml_parses", "{0}: will not parse - {1}".format(name, error))
                return

        theme_text = self.read(THEME)
        keys = set(re.findall(r'x:Key="([^"]+)"', theme_text))
        styles = self.theme_styles()
        names = set()
        for layout in LAYOUTS:
            text = self.read(layout)
            if "StaticResource" in text:
                self.fail("static_resource", "{0}: StaticResource - Theme.xaml is "
                          "merged after the layout is parsed.".format(layout))
            for key in re.findall(r"\{DynamicResource ([^}]+)\}", text):
                if key.strip() not in keys:
                    self.fail("dynamic_keys", "{0}: asks for '{1}', which Theme.xaml "
                              "does not define.".format(layout, key.strip()))
            for match in re.finditer(r'<(\w+)\b[^>]*?Style="\{DynamicResource (\w+)\}"',
                                     text):
                element, key = match.group(1), match.group(2)
                target = styles.get(key)
                if target is not None and target != element:
                    self.fail("style_target", "{0}: {1} given style {2}, which "
                              "targets {3}.".format(layout, element, key, target))
            names.update(re.findall(r'x:Name="([^"]+)"', text))

        for module in MODULES:
            text = self.read(module + ".py")
            for wanted in re.findall(r'(?:FindName|find)\("([^"]+)"\)', text):
                if wanted not in names:
                    self.fail("find_name", "{0}: '{1}' has no x:Name in a "
                              "layout.".format(module, wanted))

    # ------------------------------------------------------------ palettes

    def palettes(self):
        tree = ast.parse(self.read("vtm_theme.py"))
        for node in tree.body:
            if isinstance(node, ast.Assign) and \
                    any(getattr(t, "id", "") == "PALETTES" for t in node.targets):
                out = {}
                for key_node, value_node in zip(node.value.keys, node.value.values):
                    out[getattr(key_node, "id", None) or ast.literal_eval(key_node)] = \
                        ast.literal_eval(value_node)
                return out
        return {}

    def check_palettes(self):
        palettes = self.palettes()
        if len(palettes) < 2:
            self.fail("palette_parity", "vtm_theme: PALETTES needs a dark and a "
                      "light set.")
            return
        sets = list(palettes.values())
        first = set(sets[0].keys())
        for other in sets[1:]:
            missing = first.symmetric_difference(other.keys())
            if missing:
                self.fail("palette_parity", "vtm_theme: the palettes differ on "
                          "{0} - a swap would leave those at their dark "
                          "default.".format(", ".join(sorted(missing))))
        brushes = set(re.findall(r'<SolidColorBrush x:Key="([^"]+)"',
                                 self.read(THEME)))
        for key in sorted(first - brushes):
            self.fail("palette_theme", "palette key {0} has no brush in "
                      "Theme.xaml.".format(key))
        for key in sorted(brushes - first):
            self.fail("palette_theme", "Theme.xaml brush {0} is in no palette, so "
                      "it never changes with the theme.".format(key))
        for module in MODULES:
            text = self.read(module + ".py")
            for key in re.findall(r'theme\.brush\("([^"]+)"\)', text):
                if key not in first:
                    self.fail("brush_keys", "{0}: theme.brush('{1}') is not a "
                              "palette key.".format(module, key))

    # ------------------------------------------------------------ version

    def check_version(self):
        def version_of(name):
            match = re.search(r'^__version__\s*=\s*"([^"]+)"', self.read(name), re.M)
            return match.group(1) if match else None
        script = version_of("script.py")
        core = version_of("vtm_core.py")
        if script is None or script != core:
            self.fail("version", "script.py says {0}, vtm_core says {1}.".format(
                script, core))
            return
        if "## " + script not in self.read("CHANGELOG.md"):
            self.fail("version", "CHANGELOG.md has no entry for {0}.".format(script))

    # ------------------------------------------------------------ imports

    def check_imports(self):
        install_stubs()
        for module in MODULES:
            sys.modules.pop(module, None)
        sys.path.insert(0, self.folder)
        try:
            for module in MODULES:
                try:
                    __import__(module)
                except Exception as error:
                    self.fail("imports", "{0}: failed to import - {1}: {2}".format(
                        module, type(error).__name__, error))
        finally:
            sys.path.remove(self.folder)
            for module in MODULES:
                sys.modules.pop(module, None)

    # ------------------------------------------------------------ run

    def run(self):
        for module in SOURCES:
            self.check_python(module)
        self.check_xaml()
        self.check_shrink()
        self.check_palettes()
        self.check_version()
        self.check_imports()
        return self.failures


# --------------------------------------------------------------------------
# selftest: break each rule on purpose and prove it is caught
# --------------------------------------------------------------------------

# (rule, file, find, replace) - each makes exactly one rule fail.
BREAKAGES = [
    ("xaml_parses", "ViewTemplateManager.xaml", "<Grid x:Name=\"GripLayer\"/>",
     "<!-- -- --><Grid x:Name=\"GripLayer\"/>"),
    ("static_resource", "ViewTemplateManager.xaml",
     "Style=\"{DynamicResource BtnOrange}\" Content=\"Reset filters\"",
     "Style=\"{StaticResource BtnOrange}\" Content=\"Reset filters\""),
    ("dynamic_keys", "ViewTemplateManager.xaml",
     "Style=\"{DynamicResource BtnOrange}\" Content=\"Reset filters\"",
     "Style=\"{DynamicResource BtnNotThere}\" Content=\"Reset filters\""),
    ("style_target", "ViewTemplateManager.xaml",
     "<ToggleButton x:Name=\"UnusedToggle\" Grid.Column=\"4\" Margin=\"14,0,0,0\"\n"
     "                        Style=\"{DynamicResource BtnToggle}\"",
     "<ToggleButton x:Name=\"UnusedToggle\" Grid.Column=\"4\" Margin=\"14,0,0,0\"\n"
     "                        Style=\"{DynamicResource BtnBase}\""),
    ("find_name", "vtm_window.py", 'find("ResetFiltersButton")',
     'find("ResetFilterButton")'),
    ("handlers", "vtm_window.py", "self.reset_filters_button.Click += self.on_reset_filters",
     "self.reset_filters_button.Click += self.on_reset_filter"),
    ("fstring", "vtm_core.py", 'return SKIPPED, u"read only"\n\n    cell',
     'return SKIPPED, f"read only"\n\n    cell'),
    ("print", "vtm_settings.py", "    data = dict(DEFAULTS)\n    if not text:",
     "    data = dict(DEFAULTS)\n    print(data)\n    if not text:"),
    ("uri", "vtm_window.py", "from System import Action\n",
     "from System import Action, Uri\n"),
    ("integer_value", "vtm_core.py", "        self.id_value = eid_value(view.Id)",
     "        self.id_value = view.Id.IntegerValue"),
    ("compiles", "vtm_settings.py", "def as_int(data, key, fallback):",
     "def as_int(data, key, fallback)"),
    ("clr_first", "vtm_theme.py",
     "import vtm_clr  # noqa: F401  - assemblies first, always\n\n"
     "from System.Windows.Media import SolidColorBrush, ColorConverter",
     "from System.Windows.Media import SolidColorBrush, ColorConverter\n"
     "import vtm_clr  # noqa: F401  - assemblies first, always\n"),
    ("assemblies", "vtm_clr.py", '"System.Windows.Forms", ', ""),
    ("palette_parity", "vtm_theme.py", '        "BrushCopy": "#FFF1B8",\n', ""),
    ("palette_theme", "Theme.xaml",
     '  <SolidColorBrush x:Key="BrushCopy"           Color="#55502C"/>\n', ""),
    ("brush_keys", "vtm_window.py", 'theme.brush("BrushCopy")',
     'theme.brush("BrushCopyMark")'),
    ("duplicate_defs", "vtm_settings.py", "def decode_list(text):",
     "def encode_list(text):\n    return text\n\n\ndef decode_list(text):"),
    ("version", "script.py", '__version__ = "1.3.1"', '__version__ = "1.3.2"'),
    ("shrink_button", "ViewTemplateReport.xaml",
     '<Button x:Name="ShrinkButton" Style="{DynamicResource BtnShrink}"',
     '<Button x:Name="ShrinkButton" Style="{DynamicResource BtnChip}"'),
    ("shrink_drawer", "vtm_window.py",
     '        self.drawer = drawer_mod.Drawer(self.window, find("HeaderBar"),\n'
     '                                        find("ShrinkButton"))\n',
     '        self.drawer = drawer_mod.Drawer(self.window, find("HeaderBar"), None)\n'),
    ("shrink_input", "vtm_window.py",
     "        if self.drawer.header_down(args):\n            return\n"
     "        try:\n            self.window.DragMove()",
     "        try:\n            self.window.DragMove()"),
    ("shrink_release", "vtm_drawer.py",
     "        anim, self.anim = self.anim, None\n        self.sliding = False\n",
     "        anim, self.anim = self.anim, None\n"),
    ("shrink_size", "vtm_window.py", "            parked = self.drawer.true_size()",
     "            parked = None"),
    ("header_style", "vtm_window.py",
     "            if style is not None:\n                column.HeaderStyle = style\n",
     "            column.HeaderStyle = self.header_styles.get(tag)\n"
     "            if style is not None:\n                column.HeaderStyle = style\n"),
    ("drag_refreeze", "vtm_window.py",
     "        self.window.Dispatcher.BeginInvoke(DispatcherPriority.Background,\n"
     "                                           Action(self.refreeze))",
     "        self.refreeze()"),
    ("header_chevron", "vtm_window.py",
     '        if getattr(args.OriginalSource, "Name", None) != "PART_HeaderMenu":\n'
     "            return\n", ""),
    ("imports", "vtm_window.py", "from System.Windows.Input import Cursors,",
     "from System.Windows import Cursors\nfrom System.Windows.Input import"),
]


def selftest():
    problems = []
    for rule, name, find, replace in BREAKAGES:
        folder = tempfile.mkdtemp(prefix="vtm_check_")
        try:
            for item in os.listdir(HERE):
                path = os.path.join(HERE, item)
                if os.path.isfile(path):
                    shutil.copy(path, folder)
            path = os.path.join(folder, name)
            with io.open(path, "r", encoding="utf-8") as handle:
                text = handle.read()
            if find not in text:
                problems.append("{0}: the breakage text is not in {1} - update "
                                "the selftest.".format(rule, name))
                continue
            with io.open(path, "w", encoding="utf-8") as handle:
                handle.write(text.replace(find, replace, 1))
            caught = [f for f in Checker(folder).run()
                      if f.startswith("[{0}]".format(rule))]
            if not caught:
                problems.append("{0}: the breakage in {1} was not caught.".format(
                    rule, name))
        finally:
            shutil.rmtree(folder, ignore_errors=True)
    return problems


def main(argv):
    if "--selftest" in argv:
        problems = selftest()
        if problems:
            sys.stderr.write("SELFTEST FAILED\n")
            for line in problems:
                sys.stderr.write("  " + line + "\n")
            return 1
        sys.stderr.write("import_check selftest: all {0} breakages caught\n".format(
            len(BREAKAGES)))
        return 0

    failures = Checker(HERE).run()
    if failures:
        sys.stderr.write("FAILED\n")
        for line in failures:
            sys.stderr.write("  " + line + "\n")
        return 1
    sys.stderr.write("import_check: all clear ({0} rules)\n".format(
        len(set(b[0] for b in BREAKAGES))))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
