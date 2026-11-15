# -*- coding: utf-8 -*-
"""RevoBIM PY - Filter Manager : bench check.

Runs under plain CPython from the pushbutton folder:

    python import_check.py
    python import_check.py --selftest

Every rule is proved by deliberately breaking it and confirming the check
catches it. A rule nobody has tested is a rule that does not work.
"""

import ast
import builtins
import os
import re
import sys
import xml.dom.minidom as minidom

HERE = os.path.dirname(os.path.abspath(__file__))

PY_MODULES = ["fm_clr.py", "fm_core.py", "fm_filters.py", "fm_drawer.py",
              "fm_overrides.py", "fm_colour.py", "fm_theme.py", "fm_names.py",
              "fm_egg.py",
              "fm_xlsx.py",
              "fm_events.py", "fm_ui.py", "script.py"]
XAML_FILES = ["ui.xaml", "done.xaml", "create.xaml", "override.xaml",
              "colour.xaml", "rename.xaml"]

# script.py owns the window classes; the handler rule maps XAML -> class
XAML_OWNER = {
    "ui.xaml": "FilterManagerWindow",
    "done.xaml": "DoneWindow",
    "create.xaml": "CreateWindow",
    "override.xaml": "OverrideWindow",
    "colour.xaml": "ColourWindow",
    "rename.xaml": "RenameWindow",
}


# ---------------------------------------------------------------------------
def read(path):
    f = open(path, "r")
    try:
        return f.read()
    finally:
        f.close()



def code_only(text):
    """Source with comments and string literals blanked, line numbers kept.

    Without this a docstring saying "no bare .IntegerValue" trips the rule
    that forbids .IntegerValue.
    """
    import io
    import tokenize
    lines = text.splitlines()
    out = [list(l) for l in lines]
    try:
        toks = tokenize.generate_tokens(io.StringIO(text).readline)
        for tok in toks:
            if tok.type not in (tokenize.COMMENT, tokenize.STRING):
                continue
            (r1, c1), (r2, c2) = tok.start, tok.end
            for r in range(r1, r2 + 1):
                if r - 1 >= len(out):
                    break
                row = out[r - 1]
                a = c1 if r == r1 else 0
                b = c2 if r == r2 else len(row)
                for c in range(a, min(b, len(row))):
                    row[c] = " "
    except Exception:
        pass
    return "\n".join("".join(r) for r in out)


def rule_xaml_parses(files, sources, problems):
    """1. Every .xaml parses as XML. A run of hyphens in a comment shipped once."""
    for name in files:
        try:
            minidom.parseString(sources[name])
        except Exception as ex:
            problems.append("[xaml-parse] {0}: {1}".format(name, ex))


def rule_python_parses(modules, sources, problems):
    """2. Every module compiles."""
    for name in modules:
        try:
            ast.parse(sources[name])
        except SyntaxError as ex:
            problems.append("[py-syntax] {0}: {1}".format(name, ex))


def rule_no_fstrings(modules, sources, problems):
    """3. No f-strings - IronPython 2.7 cannot parse them."""
    for name in modules:
        try:
            tree = ast.parse(sources[name])
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if node.__class__.__name__ == "JoinedStr":
                problems.append("[f-string] {0} line {1}".format(
                    name, getattr(node, "lineno", "?")))


def rule_no_print(modules, sources, problems):
    """4. No print - it opens pyRevit's output console."""
    for name in modules:
        for i, line in enumerate(code_only(sources[name]).splitlines(), 1):
            stripped = line.strip()
            if re.match(r"^print\s*\(", stripped) or re.match(r"^print\s+[^=]", stripped):
                problems.append("[print] {0} line {1}".format(name, i))


def rule_no_get_output(modules, sources, problems):
    """5. No script.get_output() - at module level it is the blank white window."""
    for name in modules:
        if "get_output" in code_only(sources[name]):
            problems.append("[get_output] {0} calls script.get_output()".format(name))


def rule_no_bare_integervalue(modules, sources, problems):
    """6. .IntegerValue only inside the guarded eid_value helper (gone in 2026)."""
    for name in modules:
        try:
            tree = ast.parse(sources[name])
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute) or node.attr != "IntegerValue":
                continue
            base = node.value
            if name == "fm_core.py" and isinstance(base, ast.Name) \
                    and base.id == "element_id":
                continue      # the guarded fallback inside eid_value
            problems.append("[IntegerValue] {0} line {1}".format(
                name, getattr(node, "lineno", "?")))


def rule_no_system_uri(modules, sources, problems):
    """7. No System.Uri - the type moved assemblies in Revit 2025."""
    for name in modules:
        body = code_only(sources[name])
        if re.search(r"from\s+System\s+import\s+[^\n]*\bUri\b", body) \
                or "System.Uri" in body:
            problems.append("[System.Uri] {0}".format(name))


def rule_clr_first(modules, sources, problems):
    """8. No module reaching into System.* or Autodesk.* before importing fm_clr."""
    for name in modules:
        if name == "fm_clr.py":
            continue
        lines = sources[name].splitlines()
        clr_line = None
        dotnet_line = None
        for i, line in enumerate(lines, 1):
            s = line.strip()
            if s.startswith("import fm_clr") or s.startswith("from fm_clr"):
                if clr_line is None:
                    clr_line = i
            if re.match(r"^(from|import)\s+(System|Autodesk)\b", s):
                if dotnet_line is None:
                    dotnet_line = i
        if dotnet_line is not None:
            if clr_line is None:
                problems.append(
                    "[clr-order] {0} touches .NET at line {1} without importing "
                    "fm_clr".format(name, dotnet_line))
            elif clr_line > dotnet_line:
                problems.append(
                    "[clr-order] {0} imports fm_clr at line {1}, after .NET at "
                    "line {2}".format(name, clr_line, dotnet_line))


def collect_resource_keys(text):
    keys = set()
    for m in re.finditer(r'x:Key\s*=\s*"([^"]+)"', text):
        keys.add(m.group(1))
    return keys


def rule_resource_keys_exist(files, sources, problems):
    """9. Every StaticResource / DynamicResource key is defined in that file."""
    for name in files:
        text = sources[name]
        defined = collect_resource_keys(text)
        for m in re.finditer(r'\{(Static|Dynamic)Resource\s+([^\}\s]+)\s*\}', text):
            key = m.group(2)
            if key.startswith("{"):
                continue
            if key not in defined:
                problems.append("[resource] {0}: '{1}' is never defined".format(
                    name, key))


def rule_findname_has_xname(files, sources, problems):
    """10. Every x:Name the code reaches for exists in the XAML.

    Matches self.<name> against the x:Name set, since the code uses pyRevit's
    attribute access rather than literal FindName calls - the rule that did
    nothing in an earlier tool because it only matched FindName("X").
    """
    script = sources["script.py"]
    names = set()
    for name in files:
        for m in re.finditer(r'x:Name\s*=\s*"([^"]+)"', sources[name]):
            names.add(m.group(1))

    prefixes = ("txt", "lst", "cbo", "chk", "btn", "img", "pnl", "tabs", "col")
    used = set()
    for m in re.finditer(r'self\.([A-Za-z_][A-Za-z0-9_]*)', script):
        n = m.group(1)
        for prefix in prefixes:
            # the character after the prefix has to be upper case, or a
            # method like collect_rules reads as a control called "col..."
            if n.startswith(prefix) and len(n) > len(prefix) \
                    and n[len(prefix)].isupper():
                used.add(n)
                break

    for n in sorted(used):
        if n not in names:
            problems.append(
                "[x:Name] script.py uses self.{0} but no XAML declares it".format(n))


def rule_handlers_exist(files, sources, problems):
    """11. Every Click / TextChanged / SelectionChanged handler exists in Python."""
    tree = ast.parse(sources["script.py"])
    methods = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            methods[node.name] = set(
                b.name for b in node.body if isinstance(b, ast.FunctionDef))

    events = ("Click", "TextChanged", "SelectionChanged",
              "MouseLeftButtonDown", "Checked", "Unchecked")
    for name in files:
        owner = XAML_OWNER.get(name)
        available = methods.get(owner, set())
        for ev in events:
            pattern = r'(?<![A-Za-z])' + ev + r'\s*=\s*"([^"]+)"'
            for m in re.finditer(pattern, sources[name]):
                if m.group(1).lstrip().startswith('{'):
                    continue      # a binding, not a handler
                handler = m.group(1)
                if handler not in available:
                    problems.append(
                        "[handler] {0}: {1}=\"{2}\" has no method on {3}".format(
                            name, ev, handler, owner))


def rule_no_double_hyphen_comments(files, sources, problems):
    """12. XML forbids -- inside a comment. Draw banners with = not -."""
    for name in files:
        for m in re.finditer(r'<!--(.*?)-->', sources[name], re.S):
            if "--" in m.group(1):
                problems.append(
                    "[xml-comment] {0}: a comment contains a double hyphen".format(name))


def rule_no_systemcolors_keys(files, sources, problems):
    """13. No {x:Static SystemColors.*Key} resources.

    IronPython's wpf.LoadComponent cannot add a SystemResourceKey to a
    ResourceDictionary: "Add value to dictionary of type
    'System.Windows.ResourceDictionary' threw an exception".
    """
    for name in files:
        if re.search(r'x:Key\s*=\s*"\{x:Static', sources[name]):
            problems.append(
                "[SystemColors] {0}: x:Static resource key will not load "
                "under IronPython".format(name))


def rule_globals_exist(modules, sources, problems):
    """14. Every global name a function reaches for exists in its module.

    Uses symtable so locals, parameters and comprehension variables are not
    mistaken for globals - the rule that would have caught two functions
    deleted by a block rewrite.
    """
    import symtable
    for name in modules:
        try:
            table = symtable.symtable(sources[name], name, "exec")
        except SyntaxError:
            continue
        top = set(table.get_identifiers())
        _walk_symbols(table, top, name, problems)


def _walk_symbols(table, top, name, problems):
    import symtable
    for child in table.get_children():
        for sym in child.get_symbols():
            if not sym.is_global():
                continue
            n = sym.get_name()
            if n in top or n in _BUILTINS or n in dir(builtins):
                continue
            problems.append("[global] {0}: {1}() is not defined at module "
                            "level".format(name, n))
        _walk_symbols(child, top, name, problems)


_BUILTINS = set([
    "len", "str", "int", "float", "bool", "list", "dict", "set", "tuple",
    "range", "enumerate", "zip", "sorted", "round", "abs", "min", "max",
    "open", "isinstance", "getattr", "setattr", "hasattr", "type", "repr",
    "super", "print", "sum", "any", "all", "map", "filter", "reversed",
    "u", "format", "id", "iter", "next", "dir", "vars", "callable",
])


def rule_persistent_engine(modules, sources, problems):
    """15. A modeless window needs __persistentengine__ = True.

    Without it pyRevit tears the engine down when the command returns and
    every button in the window stops working.
    """
    script = sources["script.py"]
    shows_modeless = re.search(r"\.Show\s*\(\s*\)", script) is not None
    declared = "__persistentengine__" in script and \
        re.search(r"__persistentengine__\s*=\s*True", script) is not None
    if shows_modeless and not declared:
        problems.append("[modeless] script.py shows a modeless window but does "
                        "not set __persistentengine__ = True")


def rule_transactions_are_deferred(modules, sources, problems):
    """16. A modeless window cannot start a transaction directly.

    Every Transaction has to be inside the callable handed to the
    ExternalEvent runner, which this tool always names 'work'.
    """
    try:
        tree = ast.parse(sources["script.py"])
    except SyntaxError:
        return

    def scan(node, enclosing):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef):
                scan(child, child.name)
                continue
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name) \
                    and child.func.id == "Transaction":
                if enclosing != "work":
                    problems.append(
                        "[transaction] script.py line {0}: a Transaction is "
                        "started in '{1}', not inside the ExternalEvent "
                        "action".format(getattr(child, "lineno", "?"),
                                        enclosing))
            scan(child, enclosing)

    scan(tree, "<module>")


def rule_no_tabcontrol(files, sources, problems):
    """17. No TabControl or TabItem in a layout.

    A retemplated TabControl threw "Initialization of
    'System.Windows.Controls.TabControl' threw an exception" under
    IronPython's wpf.LoadComponent in v3.0.0, before a single control was
    built. The tab strips are plain Buttons whose Tag drives the styling.
    """
    for name in files:
        if re.search(r"<TabControl\b", sources[name]) \
                or re.search(r"<TabItem\b", sources[name]):
            problems.append(
                "[TabControl] {0}: TabControl/TabItem will not load "
                "retemplated under IronPython".format(name))


def rule_no_revitapi_reference(modules, sources, problems):
    """18. Never clr.AddReference RevitAPI or RevitAPIUI.

    pyRevit has already loaded both. Asking for them again by simple name
    can bind a second copy from a different path, giving two distinct
    Autodesk.Revit.DB types in one process - which surfaces as an access
    violation that kills Revit outright rather than as an exception.
    """
    for name in modules:
        # the raw source, not code_only: this rule is about string literals,
        # and code_only blanks them out
        body = sources[name]
        for m in re.finditer(r"AddReference\s*\(\s*[\"']([^\"']+)[\"']", body):
            if m.group(1) in ("RevitAPI", "RevitAPIUI"):
                problems.append("[RevitAPI-ref] {0} re-references {1}".format(
                    name, m.group(1)))
        if re.search(r"[\"']RevitAPI(UI)?[\"']\s*,", body) \
                or re.search(r",\s*[\"']RevitAPI(UI)?[\"']", body):
            problems.append(
                "[RevitAPI-ref] {0} lists RevitAPI/RevitAPIUI for "
                "clr.AddReference".format(name))


def rule_handlers_guarded(files, sources, problems):
    """19. Every window class has its handlers wrapped by ui.guard_handlers.

    An unhandled Python error in a WPF handler is swallowed by WPF: the
    control silently does nothing and there is no traceback. That is what a
    button that "isn't working" looks like.
    """
    script = sources["script.py"]
    guarded = set(re.findall(r"guard_handlers\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)",
                             script))
    for _xaml, owner in sorted(XAML_OWNER.items()):
        if owner not in guarded:
            problems.append(
                "[unguarded] script.py never calls ui.guard_handlers({0})".format(
                    owner))


# Where the real .NET API puts each name we use. A name imported from the
# wrong namespace raises ImportError at the moment the handler runs, which is
# how "Cannot import name Orientation" reached a user.
NAMESPACE_FOR = {
    # System.Windows
    "Thickness": "System.Windows", "GridLength": "System.Windows",
    "GridUnitType": "System.Windows", "FontWeights": "System.Windows",
    "HorizontalAlignment": "System.Windows", "VerticalAlignment": "System.Windows",
    "TextWrapping": "System.Windows", "Visibility": "System.Windows",
    "FrameworkElement": "System.Windows", "Point": "System.Windows",
    "PresentationSource": "System.Windows", "SystemParameters": "System.Windows",
    "Application": "System.Windows", "Window": "System.Windows",
    "TextAlignment": "System.Windows", "Rect": "System.Windows",
    "Size": "System.Windows", "CornerRadius": "System.Windows",
    "WindowStyle": "System.Windows", "WindowState": "System.Windows",
    "ResizeMode": "System.Windows", "RoutedEventArgs": "System.Windows",
    "DependencyProperty": "System.Windows",

    # System.Windows.Controls
    "Orientation": "System.Windows.Controls", "Grid": "System.Windows.Controls",
    "Border": "System.Windows.Controls", "TextBlock": "System.Windows.Controls",
    "TextBox": "System.Windows.Controls", "Button": "System.Windows.Controls",
    "CheckBox": "System.Windows.Controls", "ComboBox": "System.Windows.Controls",
    "ComboBoxItem": "System.Windows.Controls", "ListBox": "System.Windows.Controls",
    "ListBoxItem": "System.Windows.Controls", "StackPanel": "System.Windows.Controls",
    "WrapPanel": "System.Windows.Controls", "DockPanel": "System.Windows.Controls",
    "Canvas": "System.Windows.Controls", "ScrollViewer": "System.Windows.Controls",
    "ContentControl": "System.Windows.Controls", "Image": "System.Windows.Controls",
    "ColumnDefinition": "System.Windows.Controls",
    "RowDefinition": "System.Windows.Controls",
    "ContentPresenter": "System.Windows.Controls",
    "TabControl": "System.Windows.Controls", "TabItem": "System.Windows.Controls",
    "GridSplitter": "System.Windows.Controls",

    # elsewhere
    "SolidColorBrush": "System.Windows.Media", "Colors": "System.Windows.Media",
    "LinearGradientBrush": "System.Windows.Media",
    "GradientStop": "System.Windows.Media",
    "GradientStopCollection": "System.Windows.Media",
    "PointCollection": "System.Windows.Media", "Brush": "System.Windows.Media",
    "BitmapImage": "System.Windows.Media.Imaging",
    "BitmapCacheOption": "System.Windows.Media.Imaging",
    "Line": "System.Windows.Shapes", "Ellipse": "System.Windows.Shapes",
    "Polygon": "System.Windows.Shapes", "Path": "System.Windows.Shapes",
    "Rectangle": "System.Windows.Shapes",
    "Cursors": "System.Windows.Input", "Mouse": "System.Windows.Input",
    "Key": "System.Windows.Input", "Keyboard": "System.Windows.Input",
    "Thumb": "System.Windows.Controls.Primitives",
    "WindowInteropHelper": "System.Windows.Interop",
    "Screen": "System.Windows.Forms", "Cursor": "System.Windows.Forms",
    "File": "System.IO", "MemoryStream": "System.IO", "StringReader": "System.IO",
    "Process": "System.Diagnostics", "ProcessStartInfo": "System.Diagnostics",
    "AppDomain": "System", "Uri": "System", "TimeSpan": "System",
    "DispatcherTimer": "System.Windows.Threading",
    "Clipboard": "System.Windows", "Geometry": "System.Windows.Media",
    "PlacementMode": "System.Windows.Controls.Primitives",
    "SaveFileDialog": "Microsoft.Win32", "OpenFileDialog": "Microsoft.Win32",
    "Registry": "Microsoft.Win32",
    "SizeToContent": "System.Windows",
    "VisualTreeHelper": "System.Windows.Media",
    "Dock": "System.Windows.Controls", "TextTrimming": "System.Windows",
    "UIThemeManager": "Autodesk.Revit.UI",
    "ContextMenu": "System.Windows.Controls", "MenuItem": "System.Windows.Controls",
    "Separator": "System.Windows.Controls",
    "SelectionMode": "System.Windows.Controls",
    "ScrollBarVisibility": "System.Windows.Controls",
    "RotateTransform": "System.Windows.Media",
    "Popup": "System.Windows.Controls.Primitives",
    "FileStream": "System.IO", "FileMode": "System.IO",
    "FileAccess": "System.IO", "StreamWriter": "System.IO",
    "StreamReader": "System.IO",
    "ZipArchive": "System.IO.Compression",
    "ZipArchiveMode": "System.IO.Compression",
}


def rule_namespaces(modules, sources, problems):
    """20. Every .NET name is imported from the namespace the real API uses.

    A wrong namespace does not fail until the line runs, so it can sit in a
    handler for weeks. ImportError: Cannot import name Orientation shipped
    this way in v3.4.0 - it is in System.Windows.Controls, not System.Windows.
    """
    for name in modules:
        try:
            tree = ast.parse(sources[name])
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            if not node.module.startswith(("System", "Autodesk")):
                continue
            for alias in node.names:
                expected = NAMESPACE_FOR.get(alias.name)
                if expected and expected != node.module:
                    problems.append(
                        "[namespace] {0} line {1}: {2} comes from {3}, not "
                        "{4}".format(name, node.lineno, alias.name,
                                     expected, node.module))


def rule_splitters_are_star_sized(files, sources, problems):
    """21. Both columns either side of a GridSplitter must be star sized.

    With one of them absolute the splitter writes pixels into it, Grid never
    shrinks an absolute column, and widening the panel then shrinking the
    window pushes the table off the edge with no scrollbar to get it back.
    """
    for name in files:
        try:
            doc = minidom.parseString(sources[name])
        except Exception:
            continue
        for grid in doc.getElementsByTagName("Grid"):
            columns = []
            for child in grid.childNodes:
                if getattr(child, "tagName", "") == "Grid.ColumnDefinitions":
                    for cd in child.getElementsByTagName("ColumnDefinition"):
                        columns.append(cd.getAttribute("Width") or "*")
                    break
            if not columns:
                continue
            for splitter in grid.getElementsByTagName("GridSplitter"):
                if splitter.parentNode is not grid:
                    continue
                try:
                    index = int(splitter.getAttribute("Grid.Column") or "0")
                except Exception:
                    continue
                for side in (index - 1, index + 1):
                    if 0 <= side < len(columns):
                        if "*" not in columns[side]:
                            problems.append(
                                "[splitter] {0}: the column beside a "
                                "GridSplitter is '{1}', not star sized".format(
                                    name, columns[side]))


def rule_palette_complete(files, sources, problems):
    """22. Every palette key has a brush in the theme and in both palettes.

    A key the light palette is missing would fall back to the dark colour on
    a light window, which reads as a black hole in the middle of the layout.
    """
    theme = sources["fm_theme.py"]
    dark = set(re.findall(r'"([A-Za-z][A-Za-z0-9_]*)":\s*"#FF[0-9A-Fa-f]{6}"',
                          theme[theme.index("DARK = {"):theme.index("LIGHT = {")]))
    light = set(re.findall(r'"([A-Za-z][A-Za-z0-9_]*)":\s*"#FF[0-9A-Fa-f]{6}"',
                           theme[theme.index("LIGHT = {"):theme.index("PALETTES =")]))
    for key in sorted(dark - light):
        problems.append("[palette] the light palette has no '{0}'".format(key))
    for key in sorted(light - dark):
        problems.append("[palette] the dark palette has no '{0}'".format(key))

    declared = collect_resource_keys(sources["ui.xaml"])
    for key in sorted(dark):
        if key not in declared:
            problems.append(
                "[palette] '{0}' is in fm_theme but no brush declares it "
                "in the theme".format(key))

    for name in files:
        for m in re.finditer(r"pcolour\(\s*[\"']([A-Za-z0-9_]+)[\"']",
                             sources.get("script.py", "")):
            if m.group(1) not in dark:
                problems.append("[palette] script.py asks for unknown key "
                                "'{0}'".format(m.group(1)))
        break


def rule_no_literal_colours(files, sources, problems):
    """23. Layouts carry no literal colours outside the palette definitions.

    A hard coded hex cannot follow a palette switch, so it stays dark on a
    light window.
    """
    for name in files:
        text = sources[name]
        try:
            body = text[text.index("<Style TargetType=\"TextBlock\">"):]
        except ValueError:
            body = text
        for m in re.finditer(r'([A-Za-z.]+)="(#FF[0-9A-Fa-f]{6})"', body):
            problems.append("[literal-colour] {0}: {1}=\"{2}\" will not "
                            "follow the palette".format(
                                name, m.group(1), m.group(2)))


def rule_no_duplicate_resources(files, sources, problems):
    """24. A resource key may only be declared once per layout.

    A ResourceDictionary refuses a key it already holds, and the message is
    "Add value to dictionary of type 'System.Windows.ResourceDictionary'
    threw an exception" at load, before any control is built. Implicit
    styles count: their key is the TargetType.
    """
    for name in files:
        text = sources[name]
        seen = {}

        for m in re.finditer(r'<(?:SolidColorBrush|Style|ControlTemplate|'
                             r'DataTemplate)[^>]*?x:Key="([^"]+)"', text):
            key = "key:" + m.group(1)
            seen[key] = seen.get(key, 0) + 1

        for m in re.finditer(r'<Style\b(?![^>]*x:Key)[^>]*?TargetType="([^"]+)"',
                             text):
            key = "implicit style for " + m.group(1)
            seen[key] = seen.get(key, 0) + 1

        for key in sorted(seen):
            if seen[key] > 1:
                problems.append(
                    "[duplicate-resource] {0}: {1} is declared {2} times".format(
                        name, key, seen[key]))


def rule_tabs_are_wired(files, sources, problems):
    """25. Every tab button has a panel, and select_tab shows exactly one.

    A tab strip built from plain buttons has nothing enforcing that a new
    tab was added to the switch, so a new tab can render as a blank area
    with the previous tab still showing underneath it.
    """
    layout = sources["ui.xaml"]
    script = sources["script.py"]

    buttons = set(re.findall(r'x:Name="(btnTab[A-Za-z0-9_]+)"', layout))
    panels = set(re.findall(r'x:Name="(pnl[A-Za-z0-9_]*Tab)"', layout))

    if len(buttons) != len(panels):
        problems.append(
            "[tabs] {0} tab button(s) but {1} tab panel(s)".format(
                len(buttons), len(panels)))

    try:
        body = script[script.index("def select_tab("):]
        body = body[:body.index("\n    def ")]
    except ValueError:
        problems.append("[tabs] script.py has no select_tab")
        return

    for button in sorted(buttons):
        if button not in body:
            problems.append(
                "[tabs] select_tab never sets {0}".format(button))
    for panel in sorted(panels):
        if panel not in body:
            problems.append(
                "[tabs] select_tab never shows or hides {0}".format(panel))


def rule_getelement_name_guarded(modules, sources, problems):
    """26. Never read .Name straight off a doc.GetElement result.

    Element.Name is not implemented for every class in the Revit API, and
    where it is not it raises rather than returning nothing. The class that
    comes back from GetElement is whatever the model happens to hold, so it
    has to go through ff.element_name or sit inside a try.
    """
    for name in modules:
        try:
            tree = ast.parse(sources[name])
        except SyntaxError:
            continue

        parents = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node

        def guarded(node):
            cur = node
            while cur in parents:
                cur = parents[cur]
                if isinstance(cur, ast.Try):
                    return True
            return False

        def is_get_element(call):
            return (isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "GetElement")

        for node in ast.walk(tree):
            # doc.GetElement(x).Name
            if isinstance(node, ast.Attribute) and node.attr == "Name" \
                    and is_get_element(node.value) and not guarded(node):
                problems.append(
                    "[element-name] {0} line {1}: .Name read straight off "
                    "GetElement".format(name, node.lineno))

        # a variable assigned from GetElement, then read for .Name
        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef,)):
                continue
            tainted = set()
            for node in ast.walk(func):
                if isinstance(node, ast.Assign) and is_get_element(node.value):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            tainted.add(target.id)
            if not tainted:
                continue
            for node in ast.walk(func):
                if isinstance(node, ast.Attribute) and node.attr == "Name" \
                        and isinstance(node.value, ast.Name) \
                        and node.value.id in tainted and not guarded(node):
                    problems.append(
                        "[element-name] {0} line {1}: '{2}' came from "
                        "GetElement, so .Name can raise".format(
                            name, node.lineno, node.value.id))


def rule_menu_buttons_have_menus(files, sources, problems):
    """27. A button that opens a ContextMenu has to own one.

    Opening `sender.ContextMenu` when the button has none does nothing at
    all, which looks exactly like a broken button.
    """
    for name in files:
        try:
            doc = minidom.parseString(sources[name])
        except Exception:
            continue

        openers = set()
        script = sources["script.py"]
        for match in re.finditer(r"def (on_[A-Za-z0-9_]+)\(self, sender, args\):"
                                 r"(.*?)(?=\n    def |\nclass |\Z)",
                                 script, re.S):
            if "sender.ContextMenu" in match.group(2):
                openers.add(match.group(1))
        if not openers:
            continue

        for button in doc.getElementsByTagName("Button"):
            handler = button.getAttribute("Click")
            if handler not in openers:
                continue
            owned = False
            for child in button.childNodes:
                if getattr(child, "tagName", "") == "Button.ContextMenu":
                    owned = True
                    break
            if not owned:
                problems.append(
                    "[menu-button] {0}: '{1}' opens a ContextMenu but the "
                    "button does not declare one".format(name, handler))


def rule_no_duplicate_methods(modules, sources, problems):
    """28. A class may not define the same method twice.

    Python keeps the last one and says nothing, so an older definition
    quietly answers for a newer one - or, worse, one feature's method
    answers for another feature's method of the same name. Two tables in
    this tool both had a `table_header`, and the pusher's version was
    drawing the manager table's heading.
    """
    for name in modules:
        try:
            tree = ast.parse(sources[name])
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            seen = {}
            for item in node.body:
                if isinstance(item, ast.FunctionDef):
                    seen.setdefault(item.name, []).append(item.lineno)
            for method in sorted(seen):
                if len(seen[method]) > 1:
                    problems.append(
                        "[duplicate-method] {0}: {1}.{2} is defined at lines "
                        "{3}".format(name, node.name, method,
                                     ", ".join(str(n) for n in seen[method])))


def rule_no_literal_colours_in_python(modules, sources, problems):
    """29. No colour written into Python outside the palette.

    An element built in code keeps the brush it was built with. A hard coded
    hex therefore survives a switch to the light palette, which is how the
    table tab stayed dark while everything around it changed. Colours come
    from fm_theme through pcolour/pbrush.

    A line may opt out with a trailing "# palette fallback" comment, for the
    one case that has to work when the palette itself cannot be reached.
    """
    for name in modules:
        if name == "fm_theme.py":
            continue
        for number, line in enumerate(sources[name].splitlines(), 1):
            if "palette fallback" in line:
                continue
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if re.search(r'["\']#[0-9A-Fa-f]{6,8}["\']', line):
                problems.append(
                    "[python-colour] {0} line {1}: a colour written into the "
                    "code will not follow a palette switch".format(
                        name, number))
            if re.search(r"From(Rgb|Argb)\s*\(\s*\d+\s*,", line):
                problems.append(
                    "[python-colour] {0} line {1}: a colour built from "
                    "numbers will not follow a palette switch".format(
                        name, number))


def rule_theme_repaints_code_built(modules, sources, problems):
    """30. Every panel built in code is redrawn when the palette changes.

    An element built in code holds the brushes it was built with, so it
    keeps the old palette until it is built again. Whatever fills a panel
    has to be called from repaint_theme, or that panel stays dark on a light
    window - which is exactly what the Filter Manager Table did.
    """
    script = sources["script.py"]
    try:
        body = script[script.index("    def repaint_theme(self):"):]
        # to the next method of any name: stopping at the next "def on_"
        # ran past the helper repaint_theme calls, so its own name appeared
        # in the slice and the check passed with the call removed
        body = body[len("    def repaint_theme(self):"):]
        body = body[:body.index("\n    def ")]
    except ValueError:
        problems.append("[theme] script.py has no repaint_theme")
        return

    # the panels the window fills itself, and the call that refills each
    builders = {
        "pnlProps": "build_props_panel",
        "pnlTableRows": "repaint_table",
        "lstCategories": "fill_categories",
    }
    for panel in sorted(builders):
        if panel not in script:
            continue
        if builders[panel] not in body:
            problems.append(
                "[theme] repaint_theme never calls {0}(), so {1} keeps the "
                "old palette".format(builders[panel], panel))


def rule_closures_are_guarded(modules, sources, problems):
    """31. A handler defined inside a method must be guarded.

    guard_handlers only wraps the on_* methods of a window class. The cells
    of a table wire their events to closures instead, and an error in one of
    those is swallowed by WPF: the edit silently does not happen, and the
    Apply button then reports nothing to write. Every closure goes through
    ui.ui_safe.
    """
    for name in modules:
        try:
            tree = ast.parse(sources[name])
        except SyntaxError:
            continue
        for func in ast.walk(tree):
            if not isinstance(func, ast.FunctionDef):
                continue
            local = set(n.name for n in ast.walk(func)
                        if isinstance(n, ast.FunctionDef) and n is not func)
            if not local:
                continue
            for node in ast.walk(func):
                if isinstance(node, ast.AugAssign) \
                        and isinstance(node.value, ast.Name) \
                        and node.value.id in local:
                    problems.append(
                        "[closure] {0} line {1}: '{2}' is wired to an event "
                        "unguarded, so an error in it is silent".format(
                            name, node.lineno, node.value.id))


def rule_fixed_width_panels_are_aligned(files, sources, problems):
    """32. A panel holding fixed width content must say how it aligns.

    WPF centres an element that has an explicit Width inside a parent that
    stretches. A heading row and its table both being fixed width is not
    enough - one was centred and the other left aligned, so the headings sat
    off their columns.
    """
    partners = {"pnlTableHead": "pnlTableRows"}
    for name in files:
        try:
            doc = minidom.parseString(sources[name])
        except Exception:
            continue
        for element in doc.getElementsByTagName("*"):
            named = element.getAttribute("x:Name")
            if named not in partners:
                continue
            if not element.getAttribute("HorizontalAlignment"):
                problems.append(
                    "[alignment] {0}: {1} holds fixed width content but does "
                    "not set HorizontalAlignment, so it will be centred while "
                    "{2} is not".format(name, named, partners[named]))


# methods the window inherits rather than defines
INHERITED_METHODS = set([
    "set_image_source", "load_xaml", "show", "show_dialog", "hide",
])


def rule_self_calls_exist(modules, sources, problems):
    """33. Every self.<method>() a class calls is defined on that class.

    An edit that rewrites a block of methods can take a neighbour with it,
    and nothing says so until the line runs - which is how a heading that
    sorts became "object has no attribute 'sort_header'" on opening a tab.
    Only lower case names are checked; the WPF methods a window inherits are
    PascalCase.
    """
    for name in modules:
        try:
            tree = ast.parse(sources[name])
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            defined = set(item.name for item in ast.walk(node)
                          if isinstance(item, ast.FunctionDef))
            # an attribute can hold a callable, so self.x = ... counts as
            # defining self.x() for this purpose
            for item in ast.walk(node):
                if isinstance(item, ast.Assign):
                    for target in item.targets:
                        if isinstance(target, ast.Attribute) \
                                and isinstance(target.value, ast.Name) \
                                and target.value.id == "self":
                            defined.add(target.attr)
            for call in ast.walk(node):
                if not isinstance(call, ast.Call):
                    continue
                func = call.func
                if not isinstance(func, ast.Attribute):
                    continue
                if not isinstance(func.value, ast.Name) \
                        or func.value.id != "self":
                    continue
                method = func.attr
                if not method or not method[0].islower():
                    continue
                if method in defined or method in INHERITED_METHODS:
                    continue
                problems.append(
                    "[self-call] {0} line {1}: {2}.{3}() is called but never "
                    "defined".format(name, getattr(call, "lineno", "?"),
                                     node.name, method))


MIN_TEXTBOX_HEIGHT = 32


def rule_textboxes_are_tall_enough(files, sources, problems):
    """34. A text box has to be taller than its font.

    A line of Segoe UI needs about 17px, and the box has to hold that plus
    its padding and its border. A box set shorter clips its own descenders,
    which reads as blurred or half missing text rather than as a mistake.
    """
    for name in files:
        for match in re.finditer(r"<TextBox\b[^>]*>", sources[name], re.S):
            tag = match.group(0)
            height = re.search(r'\bHeight="(\d+)"', tag)
            if height and int(height.group(1)) < MIN_TEXTBOX_HEIGHT:
                named = re.search(r'x:Name="([^"]+)"', tag)
                problems.append(
                    "[textbox-height] {0}: {1} is {2}px tall, under the "
                    "{3}px a line needs".format(
                        name, named.group(1) if named else "a TextBox",
                        height.group(1), MIN_TEXTBOX_HEIGHT))

    if "MinHeight" not in sources["fm_ui.py"].split("def new_textbox")[-1][:600]:
        problems.append("[textbox-height] fm_ui.py: new_textbox does not set "
                        "a MinHeight, so a box built in code can be too short")


# the methods that build a cell of the Filter Manager Table
CELL_BUILDERS = ("paint_block", "category_cell", "rule_parameter_cell",
                 "rule_operator_cell", "rule_value_cell", "column_search_box")


def rule_table_cells_share_a_height(modules, sources, problems):
    """35. Every cell in a table row is built to the one height.

    Cells of different heights make a row read as a set of unrelated
    controls, and a cell shorter than its own text clips it. The height
    lives in one constant so a row cannot drift.
    """
    script = sources["script.py"]
    for builder in CELL_BUILDERS:
        marker = "    def {0}(self".format(builder)
        if marker not in script:
            problems.append("[cell-height] script.py has no {0}".format(builder))
            continue
        body = script[script.index(marker):]
        body = body[:body.index("\n    def ", 10)] if "\n    def " in body[10:] \
            else body
        if "ui.CELL_HEIGHT" not in body:
            problems.append(
                "[cell-height] script.py: {0} builds a cell without "
                "ui.CELL_HEIGHT, so its row will not line up".format(builder))

    if "CELL_HEIGHT" not in sources["fm_ui.py"]:
        problems.append("[cell-height] fm_ui.py does not define CELL_HEIGHT")


def rule_textbox_padding_is_on_the_border(files, sources, problems):
    """36. A text box's padding goes on its border, not on its content host.

    Setting it in both places takes the space twice: the content host is
    inset by the padding inside a border that has already been inset by it,
    and the text loses its top and bottom. WPF's own template puts it on the
    border, and so does this one.
    """
    for name in files:
        text = sources[name]
        for match in re.finditer(
                r'<ControlTemplate TargetType="TextBox">(.*?)</ControlTemplate>',
                text, re.S):
            body = match.group(1)
            host = re.search(r'<ScrollViewer[^>]*x:Name="PART_ContentHost"[^>]*>',
                             body)
            if host and "Margin=" in host.group(0):
                problems.append(
                    "[textbox-padding] {0}: PART_ContentHost carries a Margin, "
                    "which takes the padding twice and clips the text".format(
                        name))
            border = re.search(r'<Border[^>]*x:Name="bd"[^>]*>', body, re.S)
            if border and "Padding=" not in border.group(0):
                problems.append(
                    "[textbox-padding] {0}: the text box border sets no "
                    "Padding, so the text sits against its edge".format(name))


def rule_table_columns_declare_a_share(modules, sources, problems):
    """37. Every table column declares a minimum and a share.

    A column with only a fixed width cannot follow the window, and a table
    of fixed widths either leaves a gap down the right hand side or has to
    be scrolled sideways. Four values per column: key, heading, minimum,
    share of the spare space.
    """
    script = sources["script.py"]
    try:
        block = script[script.index("TABLE_COLUMNS = ["):]
        block = block[:block.index("\n]")]
    except ValueError:
        problems.append("[columns] script.py has no TABLE_COLUMNS")
        return

    rows = re.findall(r"\(([^()]*)\)", block)
    if not rows:
        problems.append("[columns] TABLE_COLUMNS has no columns in it")
        return

    for row in rows:
        parts = [p.strip() for p in row.split(",") if p.strip()]
        if len(parts) != 4:
            problems.append(
                "[columns] a column declares {0} values, not the four it "
                "needs: {1}".format(len(parts), row.strip()))

    shares = re.findall(r",\s*([0-9.]+)\s*\)", block)
    try:
        if sum(float(s) for s in shares) <= 0:
            problems.append("[columns] no column takes a share of the spare "
                            "width, so the table cannot fill the page")
    except Exception:
        pass


# the extension's shared egg, three folders up from a pushbutton
EGG_LIB = os.path.abspath(os.path.join(HERE, "..", "..", "..",
                                       "lib", "revobim", "egg"))


def load_shared_egg_rule():
    """The extension's own egg_rule, when this is run inside the extension.

    The rule belongs with the egg, not copied into each tool, so a change to
    how the egg is wired is made once. When the tool is checked on its own -
    outside the extension - the equivalent below is used instead.
    """
    if not os.path.isdir(EGG_LIB):
        return None
    if EGG_LIB not in sys.path:
        sys.path.insert(0, EGG_LIB)
    try:
        import egg_rule
        return egg_rule
    except Exception:
        return None


def rule_egg_is_wired(files, sources, problems):
    """38. The RevoBIM logo opens the egg, on three slow clicks.

    Every tool in the extension carries the link, so it has to be checked
    the same way in every tool's bench.
    """
    shared = load_shared_egg_rule()
    if shared is not None and hasattr(shared, "check"):
        try:
            for message in shared.check(sources) or []:
                problems.append("[egg] {0}".format(message))
            return
        except Exception:
            pass

    layout = sources["ui.xaml"]
    script = sources["script.py"]

    if 'x:Name="pnlLogo"' not in layout:
        problems.append("[egg] ui.xaml has no logo for the egg to hang off")
    if 'MouseLeftButtonDown="on_logo"' not in layout:
        problems.append("[egg] the logo does not listen for a click")
    if "def on_logo(" not in script:
        problems.append("[egg] script.py has no on_logo handler")
    if "SlowTriple" not in script:
        problems.append("[egg] the clicks are not counted as three slow ones")
    if "fm_egg.launch" not in script:
        problems.append("[egg] nothing ever launches the egg")



def rule_target_subtabs_are_wired(files, sources, problems):
    """39. Column three's two sub-tabs each have a panel, and the switch
    shows exactly one of them.

    Same failure as rule 25 one level down: a sub-tab whose panel the switch
    never touches leaves the other list showing underneath it.
    """
    layout = sources["ui.xaml"]
    script = sources["script.py"]
    pairs = (("btnTgtTemplates", "pnlTgtTemplates"),
             ("btnTgtViews", "pnlTgtViews"))
    try:
        body = script[script.index("def select_target_tab("):]
        body = body[:body.index("\n    def ")]
    except ValueError:
        problems.append("[target-tabs] script.py has no select_target_tab")
        return
    for button, panel in pairs:
        for name in (button, panel):
            if 'x:Name="{0}"'.format(name) not in layout:
                problems.append("[target-tabs] ui.xaml has no {0}".format(name))
            if "self.{0}".format(name) not in body:
                problems.append(
                    "[target-tabs] select_target_tab never sets {0}".format(name))
    if "def push_filters(" in script:
        push = script[script.index("def push_filters("):]
        push = push[:push.index("\n    def ")]
        if "ticked_view_rows" not in push:
            problems.append("[target-tabs] push_filters ignores the ticked "
                            "views on the Target Views tab")


def rule_egg_launch_by_keyword(files, sources, problems):
    """40. The egg is started through egg_hook.launch, arguments by keyword.

    Its signature is launch(host_window, theme, game_key). Guessing entry
    point names and passing the window positionally is how PacMan once
    shipped never opening in another tool.
    """
    egg = sources.get("fm_egg.py", "")
    if not re.search(r"egg_hook\s*\.\s*launch\s*\(\s*host_window\s*=", egg):
        problems.append("[egg-launch] fm_egg does not call "
                        "egg_hook.launch(host_window=...)")
    if "game_key" not in egg:
        problems.append("[egg-launch] fm_egg never names game_key")


def _method_body(script, name):
    try:
        body = script[script.index("def {0}(".format(name)):]
    except ValueError:
        return None
    try:
        return body[:body.index("\n    def ")]
    except ValueError:
        return body


def rule_push_settings_are_honoured(files, sources, problems):
    """41. An unticked setting in "Filters to push" is not pushed.

    The ticks are only worth having if the write reads them: overrides are
    merged group by group, and Visibility and Enable are each skipped when
    unticked. The heading cells stay a fixed width, turned on end.
    """
    script = sources["script.py"]
    run = _method_body(script, "run_push") or ""
    if "merge_overrides" not in run:
        problems.append("[push-settings] run_push never merges the ticked "
                        "settings into the overrides")
    for key in ('groups.get("visible", True)', 'groups.get("enabled", True)'):
        if key not in run:
            problems.append("[push-settings] run_push ignores {0}".format(key))
    host = _method_body(script, "push_from_host") or ""
    if "groups_for=" not in host:
        problems.append("[push-settings] push_from_host does not pass the "
                        "ticks to run_push")
    header = _method_body(script, "build_push_header") or ""
    if "RotateTransform(-90)" not in header:
        problems.append("[push-settings] the setting headings are not "
                        "turned on end")
    columns = _method_body(script, "push_columns") or ""
    if "pixels=self.PUSH_CELL" not in columns:
        problems.append("[push-settings] setting columns are not a fixed width")
    if "ui.col(width_star=1)" not in columns:
        problems.append("[push-settings] the filter name column does not "
                        "fill, so the ticks drift off the right edge")
    if 'x:Key="CellCheck"' not in sources["ui.xaml"] or \
            'FindResource("CellCheck")' not in script:
        problems.append("[push-settings] the setting ticks use the padded "
                        "list checkbox and come out cropped")


def rule_overwrite_mode_is_honoured(files, sources, problems):
    """42. "Overwrite Target New Only" leaves filters the target has alone,
    and there is a button for it at the top right of column 2 on both
    source sub-tabs."""
    layout = sources["ui.xaml"]
    script = sources["script.py"]
    for name in ("btnOverwriteA", "btnOverwriteB"):
        if 'x:Name="{0}"'.format(name) not in layout:
            problems.append("[overwrite] ui.xaml has no {0}".format(name))
    run = _method_body(script, "run_push") or ""
    if "if had_it and new_only:" not in run or '"KEPT"' not in run:
        problems.append("[overwrite] run_push ignores the overwrite mode")
    if 'self.overwrite_mode = "all"' not in script:
        problems.append("[overwrite] the mode does not start on Overwrite All")


def rule_theme_follows_revit(files, sources, problems):
    """43. The theme chip has an Auto mode that follows Revit, and Auto is
    the default rather than whatever an older version saved."""
    theme = sources.get("fm_theme.py", "")
    ui_src = sources.get("fm_ui.py", "")
    script = sources["script.py"]
    if '_MODE = ["auto"]' not in theme:
        problems.append("[theme-auto] fm_theme does not start in Auto")
    if "CurrentCanvasTheme" not in ui_src:
        problems.append("[theme-auto] fm_ui.revit_theme does not read the "
                        "canvas theme")
    if 'saved.get("theme_mode", "auto")' not in script:
        problems.append("[theme-auto] the saved theme does not default to Auto")
    if "self.Activated += self.on_window_activated" not in script:
        problems.append("[theme-auto] a theme change in Revit is never "
                        "picked up while the window is open")


def rule_current_view_and_only_selected(files, sources, problems):
    """44. Target Views has a Current view button that ticks Revit's active
    view and clears whatever would hide it, and a Show only selected toggle
    that the list actually reads."""
    layout = sources["ui.xaml"]
    script = sources["script.py"]
    for name, handler in (("btnCurrentView", "on_current_view"),
                          ("btnOnlySelected", "on_only_selected")):
        if 'x:Name="{0}"'.format(name) not in layout:
            problems.append("[current-view] ui.xaml has no {0}".format(name))
        if 'Click="{0}"'.format(handler) not in layout:
            problems.append("[current-view] {0} is not wired".format(name))
    current = _method_body(script, "on_current_view") or ""
    if "ActiveView" not in current or "self.view_state[idv] = True" not in current:
        problems.append("[current-view] on_current_view does not tick the "
                        "active view")
    if "self.types_hidden.discard" not in current:
        problems.append("[current-view] the dropdown can still hide the "
                        "current view")
    fill = _method_body(script, "fill_target_views") or ""
    if "hide_locked, only)" not in fill:
        problems.append("[current-view] the list ignores Show only selected")


def rule_every_window_shrinks(files, sources, problems):
    """45. Every window in the tool has the shrink-to-taskbar button, and
    its class makes a drawer and lets a shrunk bar drag and expand.

    A window added later without one would sit over Revit with no way to
    get it out of the way short of closing it.
    """
    script = sources["script.py"]
    for xaml, owner in sorted(XAML_OWNER.items()):
        layout = sources.get(xaml, "")
        for needle in ('x:Name="pnlHeader"', 'x:Name="btnShrink"',
                       'Click="on_shrink"', 'x:Name="pthShrink"',
                       'x:Name="pthExpand"'):
            if needle not in layout:
                problems.append("[shrink] {0} has no {1}".format(xaml, needle))
        if 'x:Name="pthExpand"' in layout:
            tail = layout[layout.index('x:Name="pthExpand"'):]
            tail = tail[:tail.index("/>")]
            if 'Fill="{DynamicResource Green}"' not in tail:
                problems.append("[shrink] {0}: the expand arrow is not "
                                "green".format(xaml))
    for _xaml, owner in sorted(XAML_OWNER.items()):
        marker = "class {0}(".format(owner)
        starts = [i for i in range(len(script))
                  if script.startswith(marker, i)]
        if not starts:
            continue
        body = script[starts[-1]:]
        nxt = body.find("\nclass ", 1)
        body = body if nxt < 0 else body[:nxt]
        if "self.drawer = fm_drawer.Drawer(self)" not in body:
            problems.append("[shrink] {0} never makes its drawer".format(owner))
        if "def on_shrink(" not in body:
            problems.append("[shrink] {0} has no on_shrink".format(owner))
        drag = body.find("def on_drag(")
        if drag < 0 or "fm_drawer.on_header_down" not in body[drag:drag + 200]:
            problems.append("[shrink] {0}: a shrunk bar cannot be dragged or "
                            "double clicked open".format(owner))

RULES = [
    ("xaml parses as XML", rule_xaml_parses, "xaml"),
    ("python compiles", rule_python_parses, "py"),
    ("no f-strings", rule_no_fstrings, "py"),
    ("no print statements", rule_no_print, "py"),
    ("no script.get_output()", rule_no_get_output, "py"),
    ("no bare .IntegerValue", rule_no_bare_integervalue, "py"),
    ("no System.Uri", rule_no_system_uri, "py"),
    ("fm_clr imported before .NET", rule_clr_first, "py"),
    ("every resource key defined", rule_resource_keys_exist, "xaml"),
    ("every self.<control> has an x:Name", rule_findname_has_xname, "xaml"),
    ("every XAML handler exists", rule_handlers_exist, "xaml"),
    ("no double hyphen in XML comments", rule_no_double_hyphen_comments, "xaml"),
    ("no x:Static SystemColors keys", rule_no_systemcolors_keys, "xaml"),
    ("no undefined module-level calls", rule_globals_exist, "py"),
    ("modeless declares persistentengine", rule_persistent_engine, "py"),
    ("transactions deferred to the event", rule_transactions_are_deferred, "py"),
    ("no TabControl in a layout", rule_no_tabcontrol, "xaml"),
    ("no RevitAPI re-reference", rule_no_revitapi_reference, "py"),
    ("window handlers are guarded", rule_handlers_guarded, "xaml"),
    ("names come from the right namespace", rule_namespaces, "py"),
    ("splitter neighbours are star sized", rule_splitters_are_star_sized, "xaml"),
    ("both palettes are complete", rule_palette_complete, "xaml"),
    ("no literal colours in a layout", rule_no_literal_colours, "xaml"),
    ("no duplicate resource keys", rule_no_duplicate_resources, "xaml"),
    ("every tab is wired up", rule_tabs_are_wired, "xaml"),
    ("GetElement .Name is guarded", rule_getelement_name_guarded, "py"),
    ("menu buttons own a menu", rule_menu_buttons_have_menus, "xaml"),
    ("no method is defined twice", rule_no_duplicate_methods, "py"),
    ("every self call exists", rule_self_calls_exist, "py"),
    ("no colours written into python", rule_no_literal_colours_in_python, "py"),
    ("the theme repaints code built panels", rule_theme_repaints_code_built, "py"),
    ("event closures are guarded", rule_closures_are_guarded, "py"),
    ("fixed width panels are aligned", rule_fixed_width_panels_are_aligned, "xaml"),
    ("text boxes are tall enough", rule_textboxes_are_tall_enough, "xaml"),
    ("table cells share a height", rule_table_cells_share_a_height, "py"),
    ("table columns declare a share", rule_table_columns_declare_a_share, "py"),
    ("the egg is wired to the logo", rule_egg_is_wired, "xaml"),
    ("text box padding sits on the border", rule_textbox_padding_is_on_the_border, "xaml"),
    ("target sub-tabs are wired", rule_target_subtabs_are_wired, "xaml"),
    ("the egg is launched by keyword", rule_egg_launch_by_keyword, "py"),
    ("push settings are honoured", rule_push_settings_are_honoured, "py"),
    ("overwrite mode is honoured", rule_overwrite_mode_is_honoured, "xaml"),
    ("theme follows Revit", rule_theme_follows_revit, "py"),
    ("current view and only selected", rule_current_view_and_only_selected, "xaml"),
    ("every window shrinks to the taskbar", rule_every_window_shrinks, "xaml"),
]


def load_sources(overrides=None):
    sources = {}
    for name in PY_MODULES + XAML_FILES:
        sources[name] = read(os.path.join(HERE, name))
    if overrides:
        sources.update(overrides)
    return sources


def run(overrides=None, quiet=False):
    sources = load_sources(overrides)
    problems = []
    for label, fn, kind in RULES:
        target = XAML_FILES if kind == "xaml" else PY_MODULES
        try:
            fn(target, sources, problems)
        except Exception as ex:
            problems.append("[rule-crashed] {0}: {1}".format(label, ex))
    if not quiet:
        for p in problems:
            sys.stdout.write(p + "\n")
    return problems


# ---------------------------------------------------------------------------
#  Self test - break each rule on purpose and confirm it is caught
# ---------------------------------------------------------------------------
BREAKAGES = [
    ("xaml parses as XML", "ui.xaml", lambda s: s.replace("</Window>", "</Windo>"),
     "xaml-parse"),
    ("python compiles", "fm_ui.py", lambda s: s + "\ndef broken(:\n", "py-syntax"),
    ("no f-strings", "fm_ui.py", lambda s: s + '\nX = f"{1}"\n', "f-string"),
    ("no print statements", "fm_ui.py", lambda s: s + '\nprint("hi")\n', "print"),
    ("no script.get_output()", "fm_ui.py",
     lambda s: s + "\nout = script.get_output()\n", "get_output"),
    ("no bare .IntegerValue", "fm_ui.py",
     lambda s: s + "\nV = some.Id.IntegerValue\n", "IntegerValue"),
    ("no System.Uri", "fm_ui.py",
     lambda s: s + "\nfrom System import Uri\n", "System.Uri"),
    ("fm_clr imported before .NET", "fm_ui.py",
     lambda s: s.replace("import fm_clr  # noqa  - must be first",
                         "from System.Windows import Thickness\nimport fm_clr"),
     "clr-order"),
    ("every resource key defined", "ui.xaml",
     lambda s: s.replace('Style="{StaticResource Ghost}"',
                         'Style="{StaticResource NoSuchStyle}"', 1), "resource"),
    ("every self.<control> has an x:Name", "ui.xaml",
     lambda s: s.replace('x:Name="txtStatus"', 'x:Name="txtStatusRenamed"', 1),
     "x:Name"),
    ("every XAML handler exists", "ui.xaml",
     lambda s: s.replace('Click="on_add_rule"', 'Click="on_nothing_at_all"', 1),
     "handler"),
    ("no double hyphen in XML comments", "ui.xaml",
     lambda s: s.replace("<!-- HEADER -->", "<!-- ---- HEADER ---- -->", 1),
     "xml-comment"),
    ("no x:Static SystemColors keys", "ui.xaml",
     lambda s: s.replace("<Window.Resources>",
                         '<Window.Resources>\n<SolidColorBrush '
                         'x:Key="{x:Static SystemColors.ControlBrushKey}" '
                         'Color="#FF262626"/>', 1), "SystemColors"),
    ("no undefined module-level calls", "fm_ui.py",
     lambda s: s + "\ndef caller():\n    return never_defined_helper()\n", "global"),
    ("modeless declares persistentengine", "script.py",
     lambda s: s.replace("__persistentengine__ = True", "PLACEHOLDER = True", 1),
     "modeless"),
    ("transactions deferred to the event", "script.py",
     lambda s: s.replace("    def after_delete(self, name):",
                         "    def sneaky(self):\n"
                         "        t = Transaction(doc, 'direct')\n"
                         "        t.Start()\n\n"
                         "    def after_delete(self, name):", 1),
     "transaction"),
    ("no TabControl in a layout", "ui.xaml",
     lambda s: s.replace("<StackPanel Grid.Row=\"0\" Orientation=\"Horizontal\">",
                         "<TabControl/><StackPanel Grid.Row=\"0\" Orientation=\"Horizontal\">", 1),
     "TabControl"),
    ("no RevitAPI re-reference", "fm_clr.py",
     lambda s: s.replace('"System.Xaml", "System", "System.Core",',
                         '"System.Xaml", "System", "RevitAPI",', 1),
     "RevitAPI-ref"),
    ("window handlers are guarded", "script.py",
     lambda s: s.replace(
         'ui.guard_handlers(ColourWindow, ["set_rgb", "set_hsl", "build_swatches"])',
         "pass", 1),
     "unguarded"),
    ("names come from the right namespace", "fm_ui.py",
     lambda s: s.replace("from System.Windows import Thickness, FontWeights",
                         "from System.Windows import Thickness, FontWeights, Orientation",
                         1),
     "namespace"),
    ("splitter neighbours are star sized", "ui.xaml",
     lambda s: s.replace('Width="1.1*" MinWidth="200"',
                         'Width="240" MinWidth="200"', 1),
     "splitter"),
    ("both palettes are complete", "fm_theme.py",
     lambda s: s.replace('    "Sel":           "#FFCBDCEC",\n', "", 1),
     "palette"),
    ("no literal colours in a layout", "ui.xaml",
     lambda s: s.replace('Background="{DynamicResource Panel}"',
                         'Background="#FF333333"', 1),
     "literal-colour"),
    ("no duplicate resource keys", "ui.xaml",
     lambda s: s.replace('<Style TargetType="MenuItem">',
                         '<Style TargetType="MenuItem"/><Style TargetType="MenuItem">',
                         1),
     "duplicate-resource"),
    ("every tab is wired up", "script.py",
     lambda s: s.replace('ui.set_visible(self.pnlTableTab, index == 1)',
                         'pass', 1),
     "tabs"),
    ("GetElement .Name is guarded", "script.py",
     lambda s: s.replace(
         "            text = ff.element_name(doc, shown, str(eid_value(shown)))",
         "            target = doc.GetElement(shown)\n"
         "            text = target.Name",
         1),
     "element-name"),
    ("menu buttons own a menu", "ui.xaml",
     lambda s: s.replace("<Button.ContextMenu>", "<Button.NotAMenu>", 1)
                .replace("</Button.ContextMenu>", "</Button.NotAMenu>", 1),
     "menu-button"),
    ("no method is defined twice", "script.py",
     lambda s: s.replace("    def table_tab(self):",
                         "    def table_tab(self):\n"
                         "        return self.tab_index == 1\n\n"
                         "    def table_tab(self):", 1),
     "duplicate-method"),
    ("every self call exists", "script.py",
     lambda s: s.replace("    def sort_header(self, key, label):",
                         "    def sort_header_gone(self, key, label):", 1),
     "self-call"),
    ("no colours written into python", "fm_ui.py",
     lambda s: s.replace('        b.BorderBrush = pbrush("EdgeStrong")',
                         '        b.BorderBrush = brush("#FF5A5A5A")', 1),
     "python-colour"),
    ("the theme repaints code built panels", "script.py",
     lambda s: s.replace("        self.repaint_table()", "        pass", 1),
     "theme"),
    ("event closures are guarded", "script.py",
     lambda s: s.replace("box.TextChanged += ui.ui_safe(typed)",
                         "box.TextChanged += typed", 1),
     "closure"),
    ("fixed width panels are aligned", "ui.xaml",
     lambda s: s.replace('<StackPanel x:Name="pnlTableHead" HorizontalAlignment="Left"/>',
                         '<StackPanel x:Name="pnlTableHead"/>', 1),
     "alignment"),
    ("text boxes are tall enough", "ui.xaml",
     lambda s: s.replace('x:Name="txtTblSearch" Height="34"',
                         'x:Name="txtTblSearch" Height="22"', 1),
     "textbox-height"),
    ("table cells share a height", "script.py",
     lambda s: s.replace("        box.Height = ui.CELL_HEIGHT\n"
                         "        box.FontSize = 11",
                         "        box.Height = 22\n"
                         "        box.FontSize = 11", 1),
     "cell-height"),
    ("table columns declare a share", "script.py",
     lambda s: s.replace('("uses", "#", 46, 0.0),', '("uses", "#", 46),', 1),
     "columns"),
    ("the egg is wired to the logo", "ui.xaml",
     lambda s: s.replace('MouseLeftButtonDown="on_logo"',
                         'MouseLeftButtonDown="on_drag"', 1),
     "egg"),
    ("text box padding sits on the border", "ui.xaml",
     lambda s: s.replace('<ScrollViewer x:Name="PART_ContentHost"',
                         '<ScrollViewer Margin="6,4" x:Name="PART_ContentHost"',
                         1),
     "textbox-padding"),
    ("target sub-tabs are wired", "script.py",
     lambda s: s.replace("ui.set_visible(self.pnlTgtViews, index == 1)", "", 1),
     "target-tabs"),
    ("the egg is launched by keyword", "fm_egg.py",
     lambda s: s.replace("egg_hook.launch(host_window=owner,",
                         "egg_hook.launch(owner,", 1),
     "egg-launch"),
    ("push settings are honoured", "script.py",
     lambda s: s.replace('if groups is None or groups.get("visible", True):',
                         'if True:', 1),
     "push-settings"),
    ("overwrite mode is honoured", "script.py",
     lambda s: s.replace("if had_it and new_only:", "if False:", 1),
     "overwrite"),
    ("theme follows Revit", "script.py",
     lambda s: s.replace('saved.get("theme_mode", "auto")',
                         'saved.get("theme", "dark")', 1),
     "theme-auto"),
    ("push settings are honoured", "script.py",
     lambda s: s.replace("name_col = ui.col(width_star=1)",
                         "name_col = ui.col(pixels=220)", 1),
     "push-settings"),
    ("current view and only selected", "script.py",
     lambda s: s.replace("hide_locked, only)", "hide_locked)", 1),
     "current-view"),
    ("every window shrinks to the taskbar", "colour.xaml",
     lambda s: s.replace('x:Name="btnShrink"', 'x:Name="btnShrunk"', 1),
     "shrink"),
    ("every window shrinks to the taskbar", "script.py",
     lambda s: s.replace("        self.drawer = fm_drawer.Drawer(self)\n", "", 1),
     "shrink"),
    ("every window shrinks to the taskbar", "override.xaml",
     lambda s: s.replace('Fill="{DynamicResource Green}"\n                              Visibility="Collapsed"',
                         'Fill="{DynamicResource Glyph}"\n                              Visibility="Collapsed"', 1),
     "shrink"),
]


def selftest():
    baseline = run(quiet=True)
    sys.stdout.write("baseline: {0} problem(s)\n".format(len(baseline)))
    for p in baseline:
        sys.stdout.write("   " + p + "\n")

    sources = load_sources()
    passed = failed = 0
    for label, target, mutate, token in BREAKAGES:
        broken = dict(sources)
        broken[target] = mutate(sources[target])
        found = run(overrides=broken, quiet=True)
        caught = any(token in p for p in found)
        if caught:
            passed += 1
            sys.stdout.write("  CAUGHT   {0}\n".format(label))
        else:
            failed += 1
            sys.stdout.write("  MISSED   {0}   (expected token '{1}')\n".format(
                label, token))

    sys.stdout.write("\n{0} rule(s) caught their own breakage, {1} missed\n".format(
        passed, failed))
    return 0 if (failed == 0 and not baseline) else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    found = run()
    if found:
        sys.stdout.write("\n{0} problem(s)\n".format(len(found)))
        sys.exit(1)
    sys.stdout.write("All {0} rules pass.\n".format(len(RULES)))
