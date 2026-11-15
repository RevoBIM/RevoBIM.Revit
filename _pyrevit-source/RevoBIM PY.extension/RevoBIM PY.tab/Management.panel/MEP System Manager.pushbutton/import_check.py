# -*- coding: utf-8 -*-
"""Bench check for MEP System Manager. Run from this folder:

    python import_check.py             every rule against the shipped files
    python import_check.py --selftest  break each rule on purpose, confirm it fires

Plain CPython, no Revit. A rule nobody has seen fail is a rule that does not
work, so every rule here has a deliberate breakage in the selftest - and every
rule reads CODE, with comments and docstrings stripped, so a rule cannot pass
by matching its own prose.
"""
import importlib
import io
import os
import re
import shutil
import sys
import symtable
import tempfile
import tokenize
import xml.dom.minidom

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bench_stubs  # noqa: E402

TOOL_MODULES = (u"msm_clr.py", u"msm_core.py", u"msm_xlsx.py", u"msm_theme.py", u"msm_ui.py",
                u"msm_model.py", u"msm_ops.py", u"msm_grid.py",
                u"msm_settings.py", u"msm_standards.py", u"msm_resize.py", u"msm_service.py", u"msm_typechange.py",
                u"msm_window.py")
# no .NET in these, so the bench runs them under plain CPython
PURE_MODULES = (u"msm_core.py", u"msm_xlsx.py")
LOADER = u"script.py"
LAYOUTS = (u"MepSystemManager.xaml", u"MsmSettings.xaml", u"MsmMessage.xaml",
           u"MsmStandards.xaml", u"MsmResize.xaml",
           u"MsmService.xaml", u"MsmTypeChange.xaml")
THEME = u"Theme.xaml"


# ============================================================
# reading
# ============================================================

def read_folder(folder):
    files = {}
    for name in os.listdir(folder):
        if name.endswith((u".py", u".xaml", u".md", u".yaml")):
            with io.open(os.path.join(folder, name), u"r", encoding=u"utf-8") as h:
                files[name] = h.read()
    return files


def code_only(text):
    """The source with every comment and docstring removed, the rest left
    exactly as written (a docstring becomes an empty string literal)."""
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except Exception:
        return text
    lines = text.splitlines(True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))

    def at(row, col):
        return offsets[row - 1] + col

    cuts = []
    previous = tokenize.INDENT
    for tok in tokens:
        kind = tok[0]
        if kind == tokenize.COMMENT:
            cuts.append((at(*tok[2]), at(*tok[3]), u""))
        elif kind == tokenize.STRING and previous in (tokenize.INDENT, tokenize.NEWLINE,
                                                       tokenize.NL, tokenize.DEDENT):
            cuts.append((at(*tok[2]), at(*tok[3]), u'""'))
        if kind not in (tokenize.NL, tokenize.COMMENT):
            previous = kind
    out = text
    for begin, finish, repl in reversed(cuts):
        out = out[:begin] + repl + out[finish:]
    return out


def py_files(files):
    return [(n, files[n]) for n in TOOL_MODULES + (LOADER,) if n in files]


class Fail(Exception):
    pass


# ============================================================
# rules
# ============================================================

def rule_xaml_parses(files):
    for name, text in files.items():
        if name.endswith(u".xaml"):
            try:
                xml.dom.minidom.parseString(text.encode(u"utf-8"))
            except Exception as error:
                raise Fail(u"{0} does not parse: {1}".format(name, error))


def rule_no_double_hyphen_comment(files):
    for name, text in files.items():
        if name.endswith(u".xaml"):
            for body in re.findall(r"<!--(.*?)-->", text, re.S):
                if u"--" in body:
                    raise Fail(u"{0}: '--' inside a comment".format(name))


def rule_no_static_resource_in_layouts(files):
    for name in LAYOUTS:
        if u"StaticResource" in files.get(name, u""):
            raise Fail(u"{0} uses StaticResource - Theme.xaml is merged after the "
                       u"layout is parsed".format(name))


def theme_keys(files):
    return set(re.findall(r'x:Key="([^"]+)"', files.get(THEME, u"")))


def rule_resource_keys_exist(files):
    keys = theme_keys(files)
    for name, text in files.items():
        if name.endswith(u".xaml"):
            for key in re.findall(r"\{DynamicResource ([\w.]+)\}", text):
                if key not in keys:
                    raise Fail(u"{0} asks for {1}, not in Theme.xaml".format(name, key))
    for name, text in py_files(files):
        code = code_only(text)
        for key in re.findall(r"(?:SetResourceReference\([^,]+,|\bres\([^,]+,[^,]+,)\s*u?[\"'](\w+)[\"']", code):
            if key not in keys:
                raise Fail(u"{0} references brush {1}, not in Theme.xaml".format(name, key))
        for key in re.findall(r"TryFindResource\(\s*u?[\"'](\w+)[\"']", code):
            if key not in keys:
                raise Fail(u"{0} finds resource {1}, not in Theme.xaml".format(name, key))


def rule_style_target_types(files):
    targets = dict(re.findall(r'<Style x:Key="(\w+)" TargetType="(\w+)"', files.get(THEME, u"")))
    for name, text in files.items():
        if not name.endswith(u".xaml"):
            continue
        for element, key in re.findall(r"<(\w+)\b[^>]*?Style=\"\{DynamicResource (\w+)\}\"", text):
            wanted = targets.get(key)
            if wanted is not None and wanted != element:
                raise Fail(u"{0}: {1} styled with {2}, which targets {3}".format(
                    name, element, key, wanted))


def rule_findname_has_xname(files):
    names = set()
    for name, text in files.items():
        if name.endswith(u".xaml"):
            names.update(re.findall(r'x:Name="(\w+)"', text))
    for name, text in py_files(files):
        code = code_only(text)
        for found in re.findall(r"\b(?:FindName|find)\(\s*u?[\"'](\w+)[\"']", code):
            if found not in names:
                raise Fail(u"{0} looks up {1}, which no XAML names".format(name, found))


def rule_banned_syntax(files):
    for name, text in py_files(files):
        code = code_only(text)
        if re.search(r"(?<![\w])[fF][rR]?[\"']", code) or re.search(r"(?<![\w])[rR][fF][\"']", code):
            raise Fail(u"{0}: f-string - IronPython 2.7 has none".format(name))
        if re.search(r"^\s*print\b", code, re.M):
            raise Fail(u"{0}: print".format(name))
        if u"System.Uri" in code or re.search(r"from System import[^\n]*\bUri\b", code):
            raise Fail(u"{0}: System.Uri moved assembly in Revit 2025".format(name))
        for match in re.finditer(r"\.IntegerValue\b", code):
            head = code[:match.start()]
            fn = head.rfind(u"def ")
            if fn < 0 or not head[fn:].startswith(u"def eid_value"):
                raise Fail(u"{0}: bare .IntegerValue outside eid_value".format(name))
        if re.search(r"\.None\b", code):
            raise Fail(u"{0}: '.None' is a syntax error on IronPython 3 - use getattr".format(name))


def rule_no_direct_builtin_members(files):
    for name, text in py_files(files):
        code = code_only(text)
        if re.search(r"\bBuiltIn(?:Parameter|Category)\.[A-Za-z_]", code):
            raise Fail(u"{0}: BuiltInParameter/Category member touched directly - look it "
                       u"up at call time with getattr".format(name))


def rule_dependency_property_through_class(files):
    for name, text in py_files(files):
        code = code_only(text)
        found = re.search(r"\b[a-z_][a-z0-9_]*\.[A-Z]\w*Property\b", code)
        if found:
            raise Fail(u"{0}: {1} - reach a dependency property through its class".format(
                name, found.group(0)))


def rule_clr_first(files):
    for name, text in py_files(files):
        if name in (u"msm_clr.py", LOADER) + PURE_MODULES:
            continue
        code = code_only(text)
        lines = code.splitlines()
        clr_line = None
        for index, line in enumerate(lines):
            if re.match(r"\s*import msm_clr\b", line):
                clr_line = index
                break
        for index, line in enumerate(lines):
            if re.match(r"\s*(from|import)\s+(System|Autodesk|Microsoft)\b", line):
                if clr_line is None or index < clr_line:
                    raise Fail(u"{0} line {1} reaches .NET before msm_clr".format(name, index + 1))


def rule_core_is_pure(files):
    for name in PURE_MODULES:
        code = code_only(files.get(name, u""))
        if re.search(r"^\s*(from|import)\s+(clr|System|Autodesk|Microsoft|msm_clr)\b",
                     code, re.M):
            raise Fail(u"{0} must stay free of .NET so the bench can run it".format(name))


def rule_assemblies_referenced(files):
    clr_text = files.get(u"msm_clr.py", u"")
    referenced = set(re.findall(r'u"([\w.]+)"', clr_text))
    for name, text in py_files(files):
        code = code_only(text)
        for namespace in re.findall(r"^\s*from\s+((?:System|Microsoft)[\w.]*)\s+import",
                                    code, re.M):
            needed = bench_stubs.ASSEMBLY_FOR.get(namespace)
            if needed and needed not in referenced:
                raise Fail(u"{0} imports {1}, but msm_clr never references {2}".format(
                    name, namespace, needed))


def rule_loader_thin(files):
    code = code_only(files.get(LOADER, u""))
    for line in code.splitlines():
        found = re.match(r"(from|import)\s+(\w+)", line)
        if found and found.group(2) not in (u"os", u"sys", u"traceback"):
            raise Fail(u"script.py imports {0} at top level - the loader must import "
                       u"nothing that can fail outside its try".format(found.group(2)))
    if u"__persistentengine__ = True" not in code:
        raise Fail(u"script.py lacks __persistentengine__ - a modeless window's handlers die")


def rule_no_duplicate_defs(files):
    for name, text in py_files(files):
        seen = {}
        indent_stack = []
        for line in code_only(text).splitlines():
            found = re.match(r"(\s*)(def|class)\s+(\w+)", line)
            if not found:
                continue
            depth = len(found.group(1))
            while indent_stack and indent_stack[-1][0] >= depth:
                indent_stack.pop()
            scope = tuple(s[1] for s in indent_stack)
            key = (scope, found.group(3))
            if key in seen:
                raise Fail(u"{0}: {1} defined twice - Python keeps the last".format(
                    name, found.group(3)))
            seen[key] = True
            indent_stack.append((depth, found.group(3)))


def rule_globals_exist(files):
    """Every global a function reaches for is defined in its module."""
    import builtins
    for name, text in py_files(files):
        try:
            table = symtable.symtable(text, name, u"exec")
        except SyntaxError as error:
            raise Fail(u"{0}: {1}".format(name, error))
        defined = set(table.get_identifiers())
        known = defined | set(dir(builtins)) | {u"__revit__", u"__file__", u"__name__"}

        def walk(t):
            for child in t.get_children():
                if child.get_type() == u"function":
                    for sym in child.get_symbols():
                        if sym.is_global() and sym.is_referenced() and sym.get_name() not in known:
                            raise Fail(u"{0}: {1}() uses {2}, which the module never "
                                       u"defines".format(name, child.get_name(), sym.get_name()))
                walk(child)
        walk(table)


def rule_modules_load(files):
    folder = tempfile.mkdtemp()
    try:
        for name, text in files.items():
            with io.open(os.path.join(folder, name), u"w", encoding=u"utf-8") as h:
                h.write(text)
        bench_stubs.build()
        bench_stubs.forget_tool_modules()
        sys.path.insert(0, folder)
        try:
            for name in TOOL_MODULES:
                module = name[:-3]
                try:
                    importlib.import_module(module)
                except Exception as error:
                    raise Fail(u"{0} will not load against the Revit API: {1}: {2}".format(
                        name, type(error).__name__, error))
        finally:
            sys.path.remove(folder)
            bench_stubs.forget_tool_modules()
            bench_stubs.remove()
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def rule_palettes_match_theme(files):
    text = code_only(files.get(u"msm_theme.py", u""))
    blocks = re.findall(r"(DARK|LIGHT) = \{(.*?)\}", text, re.S)
    keys = {}
    for label, body in blocks:
        keys[label] = set(re.findall(r'u"(\w+)":', body))
    if set(keys) != {u"DARK", u"LIGHT"}:
        raise Fail(u"msm_theme.py must carry both a DARK and a LIGHT palette")
    if keys[u"DARK"] != keys[u"LIGHT"]:
        raise Fail(u"palettes differ: {0}".format(sorted(keys[u"DARK"] ^ keys[u"LIGHT"])))
    brushes = set(re.findall(r'<SolidColorBrush x:Key="(\w+)"', files.get(THEME, u"")))
    if keys[u"DARK"] != brushes:
        raise Fail(u"palette and Theme.xaml brushes differ: {0}".format(
            sorted(keys[u"DARK"] ^ brushes)))


def rule_no_baseline(files):
    for name, text in files.items():
        if name.endswith(u".xaml") and u'VerticalAlignment="Baseline"' in text:
            raise Fail(u"{0}: VerticalAlignment=Baseline makes XamlReader throw".format(name))


def rule_every_window_has_house_header(files):
    """Logo, RevoBIM text, version top right, close - in every window."""
    for name in LAYOUTS:
        text = files.get(name, u"")
        for part in (u'x:Name="LogoHost"', u'x:Name="Logo"', u'x:Name="LogoText"',
                     u'x:Name="VersionText"', u'x:Name="BtnClose"', u'Text="RevoBIM"'):
            if part not in text:
                raise Fail(u"{0} is missing {1}".format(name, part))
    main = files.get(u"MepSystemManager.xaml", u"")
    for part in (u'x:Name="BtnTheme"', u'x:Name="ThemeLabel"', u'x:Name="BtnFull"'):
        if part not in main:
            raise Fail(u"main window is missing {0}".format(part))


def rule_egg_on_every_window(files):
    """Three slow clicks on the logo, in every window the tool opens."""
    ui_code = code_only(files.get(u"msm_ui.py", u""))
    if not re.search(r"egg_hook\s*,\s*u?[\"']attach_to_window[\"']", ui_code) and \
            not re.search(r"egg_hook\.attach_to_window\s*\(", ui_code):
        raise Fail(u"msm_ui never calls egg_hook.attach_to_window")
    for layout in LAYOUTS:
        found = False
        for name, text in py_files(files):
            code = code_only(text)
            for match in re.finditer(r"load_window\(\s*u?[\"']" + re.escape(layout), code):
                line_start = code.rfind(u"\n", 0, match.start()) + 1
                indent = len(code[line_start:match.start()]) - \
                    len(code[line_start:match.start()].lstrip())
                tail = code[match.end():match.end() + 4000]
                body = tail
                # the call's own function ends at the next def or class that
                # is indented less than the call itself; nested defs belong
                for nxt in re.finditer(r"\n([ \t]*)(def|class) ", tail):
                    if len(nxt.group(1)) < indent:
                        body = tail[:nxt.start()]
                        break
                if u"attach_egg(" in body:
                    found = True
        if not found:
            raise Fail(u"{0} is opened without attach_egg - its logo has no easter egg".format(layout))


def rule_version_everywhere(files):
    core = code_only(files.get(u"msm_core.py", u""))
    found = re.search(r'__version__ = u"(\d+\.\d+\.\d+)"', core)
    if not found:
        raise Fail(u"msm_core.py has no __version__")
    version = found.group(1)
    if u"## {0}".format(version) not in files.get(u"CHANGELOG.md", u""):
        raise Fail(u"CHANGELOG.md has no entry for {0}".format(version))
    for layout in LAYOUTS:
        if u'Text="{0}'.format(version) in files.get(layout, u""):
            raise Fail(u"{0} hardcodes the version - it must read __version__".format(layout))


def _bodies_opening(files, layout):
    """The source of each function that loads `layout`, up to the next def or
    class indented less than the call (nested defs belong to it)."""
    bodies = []
    for name, text in py_files(files):
        code = code_only(text)
        for match in re.finditer(r"load_window\(\s*u?[\"']" + re.escape(layout), code):
            line_start = code.rfind(u"\n", 0, match.start()) + 1
            indent = len(code[line_start:match.start()]) - \
                len(code[line_start:match.start()].lstrip())
            tail = code[match.end():match.end() + 4000]
            body = tail
            for nxt in re.finditer(r"\n([ \t]*)(def|class) ", tail):
                if len(nxt.group(1)) < indent:
                    body = tail[:nxt.start()]
                    break
            bodies.append(body)
    return bodies


def rule_every_window_can_shrink(files):
    """Shrink to the taskbar on every window the tool opens: the button and
    both glyphs in the header, Chrome built on the window (Chrome builds the
    drawer from BtnShrink), the button wired, and the slide's Top and Height
    released when it lands - a held animation freezes the window for good."""
    for layout in LAYOUTS:
        text = files.get(layout, u"")
        for part in (u'x:Name="BtnShrink"', u'x:Name="ShrinkGlyph"', u'x:Name="ExpandGlyph"'):
            if part not in text:
                raise Fail(u"{0} has no {1} - it cannot shrink to the taskbar".format(layout, part))
        expand = re.search(r'<Path x:Name="ExpandGlyph"[^>]*>', text, re.S)
        if not expand or u"{DynamicResource Green}" not in expand.group(0):
            raise Fail(u"{0}: the up arrow is not green".format(layout))
        bodies = _bodies_opening(files, layout)
        if not [b for b in bodies if re.search(r"(?<![A-Za-z_])Chrome\(", b)]:
            raise Fail(u"{0} is opened without Chrome - its shrink button is never wired".format(layout))
    ui_code = code_only(files.get(u"msm_ui.py", u""))
    chrome = ui_code[ui_code.find(u"class Chrome("):]
    if not re.search(r'FindName\(u?"BtnShrink"\)', chrome) or u"WindowDrawer(" not in chrome:
        raise Fail(u"Chrome never builds a WindowDrawer from BtnShrink")
    drawer = ui_code[ui_code.find(u"class WindowDrawer("):ui_code.find(u"class Chrome(")]
    if not re.search(r"button\.Click\s*\+=", drawer):
        raise Fail(u"WindowDrawer never wires its button")
    if not re.search(r"BeginAnimation\(\s*prop\s*,\s*None\s*\)", drawer) or \
            u"Window.TopProperty" not in drawer or u"Window.HeightProperty" not in drawer:
        raise Fail(u"WindowDrawer never releases Top and Height when a slide lands")


def rule_alive_proof_armed_after_show(files):
    """The note that a modeless window opened is cleared by the first handler
    that runs - but filling a dropdown fires SelectionChanged while the window
    builds, inside the command, where the engine is certainly alive. That
    proved nothing and left the note behind, so every first launch asked to
    open modal. prove_alive must wait for an arm that launch() sets only after
    the window is built and the note written."""
    code = code_only(files.get(u"msm_window.py", u""))
    body = re.search(r"def prove_alive\(self\):(.*?)\n    def ", code, re.S)
    if not body or u"self.armed" not in body.group(1):
        raise Fail(u"prove_alive does not wait for self.armed - a handler fired while "
                   u"the window builds would clear the modeless note")
    launch = re.search(r"\ndef launch\(.*", code, re.S)
    text = launch.group(0) if launch else u""
    built = text.find(u"MainWindow(")
    noted = text.find(u"_write_flag()")
    armed = text.find(u"controller.armed = True")
    shown = text.find(u"controller.window.Show()")
    if min(built, noted, armed, shown) < 0 or not (built < noted < armed < shown):
        raise Fail(u"launch() must build the window, write the note, arm, then Show() "
                   u"- in that order")


def rule_selection_survives_refresh(files):
    """reload() must capture the selection before it re-reads the model and
    pass it into the rebuild; build_sections must put it back. Captured after
    the read, the old sections are already gone and nothing is kept."""
    code = code_only(files.get(u"msm_window.py", u""))
    body = re.search(r"def reload\(self\):(.*?)\n    def ", code, re.S)
    text = body.group(1) if body else u""
    captured = text.find(u"self.capture_view_state()")
    read = text.find(u"model.read(")
    rebuilt = text.find(u"self.build_sections(kept")
    if min(captured, read, rebuilt) < 0 or not (captured < read < rebuilt):
        raise Fail(u"reload() must capture the view state before model.read() and "
                   u"pass it to build_sections")
    build = re.search(r"def build_sections\(self[^)]*\):(.*?)\n    def ", code, re.S)
    btext = build.group(1) if build else u""
    cleared = btext.find(u"host.Children.Clear()")
    restored = btext.find(u"self.restore_view_state(")
    if restored < 0 or restored < cleared:
        raise Fail(u"build_sections never restores the captured selection")


def rule_settings_stay_per_tab(files):
    """Settings are a per-tab view over one dict. dict() on it throws or,
    worse, flattens it into a copy whose keys are the Pipe tab's - either
    way a dialog would save the wrong tab. Copy with .copy(), hand a job
    .resolved()."""
    for name, text in py_files(files):
        code = code_only(text)
        if re.search(r"\bdict\(\s*(self\.)?settings\s*\)", code):
            raise Fail(u"{0} calls dict() on a settings view - use .copy() or "
                       u".resolved()".format(name))


def rule_every_discipline_has_a_tab(files):
    """Each discipline in core.DOMAINS needs a tab button in the layout and a
    place in the window's tab sync, or it cannot be reached."""
    core_code = code_only(files.get(u"msm_core.py", u""))
    found = re.search(r"^DOMAINS\s*=\s*\(([^)]*)\)", core_code, re.M)
    domains = re.findall(r'u?"(\w+)"', found.group(1)) if found else []
    if not domains:
        raise Fail(u"msm_core.py has no DOMAINS")
    layout = files.get(u"MepSystemManager.xaml", u"")
    window = code_only(files.get(u"msm_window.py", u""))
    buttons = {u"pipe": u"BtnTabPipe", u"duct": u"BtnTabDuct", u"cont": u"BtnTabCont",
               u"ws": u"BtnTabWs"}
    for domain in domains:
        button = buttons.get(domain)
        if not button:
            raise Fail(u"no tab button name known for {0}".format(domain))
        if u'x:Name="{0}"'.format(button) not in layout:
            raise Fail(u"the layout has no {0} for the {1} tab".format(button, domain))
        if u'(u"{0}", u"{1}")'.format(domain, button) not in window:
            raise Fail(u"sync_toolbar never styles the {0} tab".format(domain))
        if u'self.switch_tab(u"{0}")'.format(domain) not in window:
            raise Fail(u"nothing switches to the {0} tab".format(domain))


def rule_workset_pick_from_the_list_shown(files):
    """The workset dropdown can be narrowed by its search box, so its index
    only means something against the list on screen (ws_choices). Reading
    snapshot.worksets[index] would stage the wrong workset."""
    code = code_only(files.get(u"msm_window.py", u""))
    if re.search(r"snapshot\.worksets\s*\[\s*index\s*\]", code):
        raise Fail(u"a workset pick is read from snapshot.worksets by index - read it "
                   u"from ws_choices, the list the dropdown shows")
    if u"self.ws_choices = shown" not in code:
        raise Fail(u"fill_worksets no longer records the list it shows")
    if re.search(r"snapshot\.types\s*\[\s*index\s*\]", code):
        raise Fail(u"a type pick is read from snapshot.types by index - read it from "
                   u"type_choices, the list the dropdown shows")
    if u"self.type_choices = shown" not in code:
        raise Fail(u"fill_pipe_types no longer records the list it shows")
    body = re.search(r"def apply_worksets\(self\):(.*?)\n    def ", code, re.S)
    text = body.group(1) if body else u""
    if u"core.staged_rows(self.snapshot.systems" not in text or u"s.rows" in text:
        raise Fail(u"apply_worksets must build its list from the whole read "
                   u"(core.staged_rows), not from the rows the table shows")


def rule_workset_tab_reshown_by_discipline(files):
    """The Workset Assigner's sections sit inside discipline expanders. Showing
    the tab again must re-add the disciplines: adding a section straight to
    the page throws, because it already has a parent."""
    code = code_only(files.get(u"msm_window.py", u""))
    body = re.search(r"def show_tab\(self\):(.*?)\n    def ", code, re.S)
    text = body.group(1) if body else u""
    if not re.search(r"for\s+\w+\s*,\s*outer\s*,\s*\w+\s+in\s+self\.outers\s*:\s*\n\s*"
                     r"host\.Children\.Add\(\s*outer\s*\)", text):
        raise Fail(u"show_tab does not put the folds back - sections inside discipline or "
                   u"service type folds would be added straight to the page, which throws")


def rule_fittings_sized_by_parameter(files):
    """A cable tray fitting's connector "Height" is often tied to the tray's
    width in the family. Sizing through connectors put a new height on the
    fittings' width (2.7.0). Sizes go through the fitting's own parameters."""
    code = code_only(files.get(u"msm_ops.py", u""))
    if re.search(r"setattr\(\s*connector", code) or \
            re.search(r"connector\.(Width|Height|Radius)\s*=[^=]", code):
        raise Fail(u"a size is set on a connector - set the fitting's own width / height "
                   u"parameter instead")


def rule_icon_buttons_keep_their_icons(files):
    """A button laid out with an icon and a label must not have its Content
    replaced from code - that throws the icon away. Change its named label."""
    from xml.dom import minidom
    for layout in LAYOUTS:
        text = files.get(layout)
        if not text:
            continue
        try:
            doc = minidom.parseString(text.encode(u"utf-8"))
        except Exception:
            continue
        for button in doc.getElementsByTagName(u"Button"):
            name = button.getAttribute(u"x:Name")
            has_icon = [c for c in button.childNodes if c.nodeType == c.ELEMENT_NODE]
            if not name or not has_icon:
                continue
            for module, code in py_files(files):
                pattern = r"find\(\s*u?[\"']" + re.escape(name) + r"[\"']\s*\)\.Content\s*="
                if re.search(pattern, code_only(code)):
                    raise Fail(u"{0} sets the Content of {1}, which carries an icon - set its "
                               u"label instead".format(module, name))


def rule_change_runs_every_phase(files):
    """Change Type has to run each phase: the pipes, the fittings, the
    retained values, the accessories and the log. A phase that stops being
    called is silent - the bench can only test a phase it is given."""
    code = code_only(files.get(u"msm_ops.py", u""))
    body = re.search(r"def change_type_job\(.*?\n    return job", code, re.S)
    text = body.group(0) if body else u""
    for call in (u"_change_batches(", u"_swap_fitting(", u"restore_pass(",
                 u"_resize_accessories(", u"_close_groups(", u"_change_log("):
        if call not in text:
            raise Fail(u"change_type_job never calls {0}".format(call))


def rule_job_counters_exist(files):
    """Every key a job's helpers add to must be set up by the job. A missing
    one throws when the tallies are added up, and takes the whole run with it
    - 3.6.0 changed one pipe of 27 because "fittings_already" was not there."""
    code = code_only(files.get(u"msm_ops.py", u""))
    body = re.search(r"def change_type_job\(.*?\n    return job", code, re.S)
    text = body.group(0) if body else u""
    setup = re.search(r"data\.update\(\{(.*?)\}\)", text, re.S)
    known = set(re.findall(r'u"([^"]+)"', setup.group(1) if setup else u""))
    known |= set(re.findall(r'data\[u"([^"]+)"\]\s*=[^=]', text))
    helpers = (u"_pipe_chunk", u"_change_batches", u"_swap_fitting", u"_resize_accessories", u"_change_log",
               u"_close_groups", u"_rebuild_group", u"_open_groups", u"_plan_groups")
    for name in helpers:
        found = re.search(r"\ndef " + name + r"\(.*?(?=\ndef )", code, re.S)
        if not found:
            continue
        for key in re.findall(r'data\[u"([^"]+)"\]\s*(?:\+=|\.append|\.extend)', found.group(0)):
            if key not in known:
                raise Fail(u"{0} adds to data[\"{1}\"], which change_type_job never sets "
                           u"up".format(name, key))


def rule_raise_checked(files):
    for name, text in py_files(files):
        code = code_only(text)
        if u".Raise()" in code and u"ExternalEventRequest.Accepted" not in code:
            raise Fail(u"{0}: ExternalEvent.Raise() status is never checked".format(name))


def rule_no_pumping(files):
    for name, text in py_files(files):
        code = code_only(text)
        for bad in (u"DoEvents", u"PushFrame", u"Thread.Sleep"):
            if bad in code:
                raise Fail(u"{0}: {1} - never pump or sleep the UI thread".format(name, bad))


def rule_no_shared_files(files, root=None):
    """No panel bundle.yaml, no startup.py, no lib\\revobim\\__init__.py."""
    root = root or os.path.abspath(os.path.join(HERE, u"..", u"..", u".."))
    panel = os.path.abspath(os.path.join(HERE, u".."))
    bad = [os.path.join(panel, u"bundle.yaml"),
           os.path.join(root, u"startup.py"),
           os.path.join(root, u"lib", u"revobim", u"__init__.py")]
    for path in bad:
        if os.path.exists(path):
            raise Fail(u"{0} is a shared file - never ship it".format(path))


RULES = [
    rule_xaml_parses, rule_no_double_hyphen_comment, rule_no_static_resource_in_layouts,
    rule_resource_keys_exist, rule_style_target_types, rule_findname_has_xname,
    rule_banned_syntax, rule_no_direct_builtin_members, rule_dependency_property_through_class,
    rule_clr_first, rule_core_is_pure, rule_assemblies_referenced, rule_loader_thin,
    rule_no_duplicate_defs, rule_globals_exist, rule_modules_load, rule_palettes_match_theme,
    rule_no_baseline, rule_every_window_has_house_header, rule_egg_on_every_window,
    rule_version_everywhere, rule_alive_proof_armed_after_show, rule_selection_survives_refresh,
    rule_settings_stay_per_tab, rule_every_discipline_has_a_tab,
    rule_workset_pick_from_the_list_shown, rule_workset_tab_reshown_by_discipline,
    rule_fittings_sized_by_parameter, rule_icon_buttons_keep_their_icons,
    rule_change_runs_every_phase, rule_every_window_can_shrink,
    rule_job_counters_exist,
    rule_raise_checked, rule_no_pumping, rule_no_shared_files,
]


def run(files):
    failures = []
    for rule in RULES:
        try:
            rule(files)
        except Fail as error:
            failures.append((rule.__name__, u"{0}".format(error)))
    return failures


# ============================================================
# selftest: break each rule on purpose
# ============================================================

def sub(name, old, new):
    def mutate(files):
        text = files[name]
        if old not in text:
            raise AssertionError(u"selftest anchor missing in {0}: {1!r}".format(name, old))
        files[name] = text.replace(old, new, 1)
    return mutate


def drop_current_changelog_entry(files):
    """Remove the heading for whatever version msm_core carries now, so the
    breakage keeps working through every version bump."""
    found = re.search(r'__version__ = u"(\d+\.\d+\.\d+)"', files[u"msm_core.py"])
    heading = u"## {0}".format(found.group(1))
    if heading not in files[u"CHANGELOG.md"]:
        raise AssertionError(u"selftest anchor missing in CHANGELOG.md: " + heading)
    files[u"CHANGELOG.md"] = files[u"CHANGELOG.md"].replace(heading, u"## 0.0.0")


def add(name, text):
    def mutate(files):
        files[name] = files.get(name, u"") + text
    return mutate


BREAKAGES = [
    (rule_xaml_parses, sub(u"MsmMessage.xaml", u"</Window>", u"")),
    (rule_no_double_hyphen_comment, sub(u"MepSystemManager.xaml",
                                        u"<!-- ==================== header",
                                        u"<!-- -------- header")),
    (rule_no_static_resource_in_layouts, sub(u"MsmSettings.xaml", u"{DynamicResource Bg}",
                                             u"{StaticResource Bg}")),
    (rule_resource_keys_exist, sub(u"MsmMessage.xaml", u"{DynamicResource Bg}",
                                   u"{DynamicResource Background2}")),
    (rule_resource_keys_exist, sub(u"msm_grid.py", u'res(tick, Border.BackgroundProperty, u"Orange")',
                                   u'res(tick, Border.BackgroundProperty, u"Orangey")')),
    (rule_style_target_types, sub(u"MepSystemManager.xaml",
                                  u'<Thumb x:Name="GripN" Style="{DynamicResource GripThumb}"',
                                  u'<Thumb x:Name="GripN" Style="{DynamicResource BtnChip}"')),
    (rule_findname_has_xname, sub(u"msm_window.py", u'find(u"BtnRefresh")', u'find(u"BtnReload")')),
    (rule_banned_syntax, add(u"msm_core.py", u'\n\ndef _bad(x):\n    return f"{x}"\n')),
    (rule_banned_syntax, add(u"msm_ops.py", u"\n\ndef _bad2(e):\n    return e.IntegerValue\n")),
    (rule_banned_syntax, add(u"msm_model.py", u"\n\ndef _bad3():\n    return StorageType.None\n")),
    (rule_no_direct_builtin_members, add(u"msm_model.py",
                                         u"\n\ndef _bad4(p):\n    return p.get_Parameter(BuiltInParameter.RBS_PIPE_DIAMETER_PARAM)\n")),
    (rule_dependency_property_through_class, sub(u"msm_window.py", u"TextBlock.ForegroundProperty",
                                                 u"status.ForegroundProperty")),
    (rule_clr_first, sub(u"msm_ops.py", u"import msm_clr  # noqa: F401  - assemblies first\n", u"")),
    (rule_core_is_pure, add(u"msm_core.py", u"\nimport clr\n")),
    (rule_assemblies_referenced, sub(u"msm_clr.py", u'    u"PresentationCore",\n', u"")),
    (rule_loader_thin, sub(u"script.py", u"import traceback\n", u"import traceback\nimport msm_window\n")),
    (rule_loader_thin, sub(u"script.py", u"__persistentengine__ = True", u"")),
    (rule_no_duplicate_defs, add(u"msm_core.py", u"\n\ndef natural_key(value):\n    return value\n")),
    (rule_globals_exist, sub(u"msm_core.py", u"return tuple(key)", u"return tuple(keyz)")),
    (rule_modules_load, sub(u"msm_ops.py",
                            u"from Autodesk.Revit.UI import (IExternalEventHandler",
                            u"from Autodesk.Revit.DB.Plumbing import RoutingPreferenceRuleGroupType\n"
                            u"from Autodesk.Revit.UI import (IExternalEventHandler")),
    (rule_modules_load, sub(u"msm_grid.py", u"from System.Windows.Data import Binding",
                            u"from System.Windows.Controls import Binding")),
    (rule_palettes_match_theme, sub(u"msm_theme.py", u'    u"GroupHead": u"#EDEDF1",\n', u"")),
    (rule_palettes_match_theme, sub(u"Theme.xaml", u'<SolidColorBrush x:Key="GroupHead" Color="#28282C"/>', u"")),
    (rule_no_baseline, sub(u"MsmMessage.xaml", u'VerticalAlignment="Center"/>',
                           u'VerticalAlignment="Baseline"/>')),
    (rule_every_window_has_house_header, sub(u"MsmSettings.xaml", u'x:Name="VersionText"', u'x:Name="Ver"')),
    (rule_every_window_has_house_header, sub(u"MepSystemManager.xaml", u'x:Name="BtnTheme"', u'x:Name="BtnMode"')),
    (rule_egg_on_every_window, sub(u"msm_settings.py", u"ui.attach_egg(w,", u"ui.attach_nothing(w,")),
    (rule_egg_on_every_window, sub(u"msm_ui.py", u"        attach_egg(window, find(u\"LogoHost\"),",
                                   u"        attach_nothing(window, find(u\"LogoHost\"),")),
    (rule_egg_on_every_window, sub(u"msm_ui.py", u'getattr(egg_hook, u"attach_to_window", None)',
                                   u'getattr(egg_hook, u"attach_elsewhere", None)')),
    (rule_version_everywhere, drop_current_changelog_entry),
    (rule_alive_proof_armed_after_show, sub(u"msm_window.py",
        u"if self.proved_alive or not self.armed:", u"if self.proved_alive:")),
    (rule_alive_proof_armed_after_show, sub(u"msm_window.py",
        u"    controller.armed = True\n    controller.window.Show()",
        u"    controller.window.Show()\n    controller.armed = True")),
    (rule_selection_survives_refresh, sub(u"msm_window.py",
        u"        kept = self.capture_view_state()\n        self.read_from = self.doc_key()",
        u"        self.read_from = self.doc_key()")),
    (rule_selection_survives_refresh, sub(u"msm_window.py",
        u"        self.restore_view_state(kept)\n", u"")),
    (rule_core_is_pure, sub(u"msm_xlsx.py", u"import re\n", u"import re\nimport clr\n")),
    (rule_assemblies_referenced, sub(u"msm_clr.py", u'    u"System.IO.Compression",\n', u"")),
    (rule_settings_stay_per_tab, sub(u"msm_settings.py", u"self.settings = settings.copy()",
                                     u"self.settings = dict(settings)")),
    (rule_every_discipline_has_a_tab, sub(u"MepSystemManager.xaml",
                                          u'x:Name="BtnTabDuct"', u'x:Name="BtnTabDucts"')),
    (rule_every_discipline_has_a_tab, sub(u"msm_window.py",
                                          u'find(u"BtnTabCont").Click += safe(lambda: self.switch_tab(u"cont"), u"Containment tab")',
                                          u'pass')),
    (rule_workset_pick_from_the_list_shown, sub(u"msm_window.py",
        u"        name, number = choices[index]", u"        name, number = self.snapshot.worksets[index]")),
    (rule_workset_pick_from_the_list_shown, sub(u"msm_window.py",
        u"        rows = core.staged_rows(self.snapshot.systems, pending, names)",
        u"        rows = [r for s in self.sections for r in s.rows]")),
    (rule_workset_tab_reshown_by_discipline, sub(u"msm_window.py",
        u"            for _title, outer, _made in self.outers:\n"
        u"                host.Children.Add(outer)",
        u"            for section in self.sections:\n                host.Children.Add(section.expander)")),
    (rule_fittings_sized_by_parameter, add(u"msm_ops.py",
        u"\n\ndef _bad(connector):\n    connector.Height = 1.0\n")),
    (rule_icon_buttons_keep_their_icons, sub(u"msm_window.py",
        u"            find(u\"ChangeTypeLabel\").Text = u\"Change {0}\".format(info[u\"type_word\"])",
        u"            find(u\"BtnChangeType\").Content = u\"Change {0}\".format(info[u\"type_word\"])")),
    (rule_workset_pick_from_the_list_shown, sub(u"msm_window.py",
        u"        type_name, type_id = choices[index]",
        u"        type_name, type_id = self.snapshot.types[index]")),
    (rule_change_runs_every_phase, sub(u"msm_ops.py",
        u"                _resize_accessories(doc, sized, data,", u"                pass  # (")),
    (rule_job_counters_exist, sub(u"msm_ops.py",
        u"u\"fittings_already\": 0, u\"resized\": 0,", u"u\"resized\": 0,")),
    (rule_every_window_can_shrink, sub(u"MsmResize.xaml", u'x:Name="BtnShrink"', u'x:Name="BtnShrunk"')),
    (rule_every_window_can_shrink, sub(u"MsmService.xaml", u'Stroke="{DynamicResource Green}"',
                                       u'Stroke="{DynamicResource Text}"')),
    (rule_every_window_can_shrink, sub(u"msm_standards.py", u"        ui.Chrome(w,", u"        ui.NoChrome(w,")),
    (rule_every_window_can_shrink, sub(u"msm_ui.py", u"            button.Click += self._on_button", u"            pass")),
    (rule_every_window_can_shrink, sub(u"msm_ui.py", u"                w.BeginAnimation(prop, None)", u"                pass")),
    (rule_every_window_can_shrink, sub(u"msm_ui.py", u"            self.drawer = WindowDrawer(window, header, shrink_button)",
                                       u"            self.drawer = None")),
    (rule_raise_checked, sub(u"msm_ops.py",
        u"if status == ExternalEventRequest.Accepted or text.endswith(u\"Pending\"):",
        u"if text.endswith(u\"Accepted\") or text.endswith(u\"Pending\"):")),
    (rule_no_pumping, add(u"msm_ui.py", u"\n\ndef _pump():\n    Thread.Sleep(10)\n")),
]


def selftest(files):
    problems = []
    for rule, mutate in BREAKAGES:
        broken = dict(files)
        mutate(broken)
        try:
            rule(broken)
            problems.append(u"{0} did NOT catch its breakage".format(rule.__name__))
        except Fail:
            pass
    folder = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(folder, u"lib", u"revobim"))
        io.open(os.path.join(folder, u"startup.py"), u"w").close()
        try:
            rule_no_shared_files(files, root=folder)
            problems.append(u"rule_no_shared_files did NOT catch a shipped startup.py")
        except Fail:
            pass
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    covered = set([r.__name__ for r, _m in BREAKAGES]) | {u"rule_no_shared_files"}
    for rule in RULES:
        if rule.__name__ not in covered:
            problems.append(u"{0} has no breakage in the selftest".format(rule.__name__))
    return problems


def main():
    files = read_folder(HERE)
    failures = run(files)
    for name, text in failures:
        sys.stdout.write(u"FAIL {0}: {1}\n".format(name, text))
    sys.stdout.write(u"{0} rules, {1} failed\n".format(len(RULES), len(failures)))
    if u"--selftest" in sys.argv:
        problems = selftest(files)
        for p in problems:
            sys.stdout.write(u"SELFTEST {0}\n".format(p))
        sys.stdout.write(u"selftest: {0} breakages, {1} missed\n".format(
            len(BREAKAGES) + 1, len(problems)))
        return 1 if (failures or problems) else 0
    return 1 if failures else 0


if __name__ == u"__main__":
    sys.exit(main())
