# -*- coding: utf-8 -*-
"""Bench check for Space Name To Element. Runs under plain CPython.

    python import_check.py
    python import_check.py --selftest

Every rule was proved by deliberately breaking it and confirming the check
caught it - a rule nobody has tested is a rule that does not work.
"""

import os
import re
import sys
import symtable
import xml.dom.minidom

HERE = os.path.dirname(os.path.abspath(__file__))

MODULES = ["snte_clr", "theme", "snte_core", "snte_ops", "snte_ui",
           "snte_tree", "snte_window"]
LAYOUTS = ["SpaceNameToElement.xaml", "SnteMessage.xaml"]
THEME_FILE = "Theme.xaml"
CLR_MODULE = "snte_clr"

failures = []


def fail(rule, detail):
    failures.append("[{0}] {1}".format(rule, detail))


def read(name):
    handle = open(os.path.join(HERE, name), "r")
    try:
        return handle.read()
    finally:
        handle.close()


def py_files():
    return [m + ".py" for m in MODULES] + ["script.py"]


# ---------------------------------------------------------------------------
#  1  every .xaml parses as XML
# ---------------------------------------------------------------------------
def check_xaml_parses(files):
    for name in files:
        path = os.path.join(HERE, name)
        if not os.path.exists(path):
            fail("xaml-parses", name + " is missing")
            continue
        try:
            xml.dom.minidom.parse(path)
        except Exception as err:
            # a run of hyphens in a comment is the classic one - XML forbids
            # '--' inside a comment, and XamlReader.Load throwing shows up as a
            # blank white pyRevit window
            fail("xaml-parses", "{0}: {1}".format(name, err))


# ---------------------------------------------------------------------------
#  2  no System.* / Autodesk.* before snte_clr
# ---------------------------------------------------------------------------
def check_clr_first(files):
    for name in files:
        if name in (CLR_MODULE + ".py", "script.py"):
            continue
        text = read(name)
        clr_line = None
        first_dotnet = None
        for index, line in enumerate(text.splitlines()):
            stripped = line.strip()
            if re.match(r"^import\s+" + CLR_MODULE + r"\b", stripped):
                if clr_line is None:
                    clr_line = index
            if re.match(r"^(from|import)\s+(System|Autodesk)\b", stripped):
                if first_dotnet is None:
                    first_dotnet = index
        if first_dotnet is None:
            continue
        if clr_line is None:
            fail("clr-first",
                 "{0} reaches into System./Autodesk. without importing {1}"
                 .format(name, CLR_MODULE))
        elif clr_line > first_dotnet:
            fail("clr-first",
                 "{0} imports {1} at line {2}, after a .NET import at line {3}"
                 .format(name, CLR_MODULE, clr_line + 1, first_dotnet + 1))


# ---------------------------------------------------------------------------
#  3  no StaticResource in a layout
# ---------------------------------------------------------------------------
def check_no_static_resource(layouts):
    for name in layouts:
        text = read(name)
        for match in re.finditer(r"StaticResource\s+(\w+)", text):
            fail("no-staticresource",
                 "{0} uses StaticResource {1} - Theme.xaml is merged in after "
                 "the layout is parsed".format(name, match.group(1)))


# ---------------------------------------------------------------------------
#  4  every DynamicResource key exists in Theme.xaml
# ---------------------------------------------------------------------------
def theme_keys():
    text = read(THEME_FILE)
    return set(re.findall(r'x:Key="([^"]+)"', text))


def check_dynamic_keys(layouts):
    known = theme_keys()
    for name in layouts + [THEME_FILE]:
        text = read(name)
        for key in set(re.findall(r"DynamicResource\s+([\w\.]+)", text)):
            if key not in known:
                fail("dynamic-key",
                     "{0} asks for DynamicResource {1}, which {2} does not "
                     "define".format(name, key, THEME_FILE))


# ---------------------------------------------------------------------------
#  5  a Style applied to an element its TargetType does not match
# ---------------------------------------------------------------------------
def style_targets():
    text = read(THEME_FILE)
    out = {}
    for match in re.finditer(
            r'<Style\s+x:Key="([^"]+)"\s+TargetType="\{x:Type\s+(\w+)\}"', text):
        out[match.group(1)] = match.group(2)
    return out


def check_style_targets(layouts):
    targets = style_targets()
    for name in layouts:
        text = read(name)
        for match in re.finditer(
                r"<(\w+)\b[^>]*?Style=\"\{DynamicResource\s+(\w+)\}\"", text,
                re.S):
            element, key = match.group(1), match.group(2)
            wanted = targets.get(key)
            if wanted is None:
                continue
            if wanted != element:
                fail("style-target",
                     "{0}: <{1}> uses style {2}, whose TargetType is {3} - WPF "
                     "raises when the style is applied, which reads as a dead "
                     "window".format(name, element, key, wanted))


# ---------------------------------------------------------------------------
#  6  every FindName has a matching x:Name
# ---------------------------------------------------------------------------
def check_findname(files, layouts):
    names = set()
    for name in layouts:
        names.update(re.findall(r'x:Name="(\w+)"', read(name)))
    names.update(re.findall(r'x:Name="(\w+)"', read(THEME_FILE)))

    for name in files:
        text = read(name)
        # both the literal call and the aliased form
        wanted = set(re.findall(r'FindName\(\s*["\'](\w+)["\']\s*\)', text))
        wanted.update(re.findall(r'_find\(\s*["\'](\w+)["\']\s*\)', text))
        for key in wanted:
            if key not in names:
                fail("findname",
                     "{0} looks up '{1}', which no layout declares as x:Name"
                     .format(name, key))


# ---------------------------------------------------------------------------
#  7  every FindResource / palette key exists
# ---------------------------------------------------------------------------
def check_resource_keys(files):
    known = theme_keys()
    for name in files:
        text = read(name)
        keys = set(re.findall(r'FindResource\(\s*["\'](\w+)["\']\s*\)', text))
        keys.update(re.findall(
            r'SetResourceReference\([^,]+,\s*["\'](\w+)["\']\s*\)', text))
        for key in keys:
            if key not in known:
                fail("resource-key",
                     "{0} asks for resource '{1}', which {2} does not define"
                     .format(name, key, THEME_FILE))


# ---------------------------------------------------------------------------
#  8  both palettes cover every brush the theme declares
# ---------------------------------------------------------------------------
def check_palettes():
    text = read("theme.py")
    blocks = dict(re.findall(r"^(DARK|LIGHT)\s*=\s*\{(.*?)^\}", text,
                             re.S | re.M))
    if len(blocks) != 2:
        fail("palette", "theme.py does not declare both DARK and LIGHT")
        return
    sets = {}
    for name in blocks:
        sets[name] = set(re.findall(r'"(\w+)"\s*:', blocks[name]))
    if sets["DARK"] != sets["LIGHT"]:
        diff = sets["DARK"] ^ sets["LIGHT"]
        fail("palette", "DARK and LIGHT differ on: " + ", ".join(sorted(diff)))
    for key in sets["DARK"]:
        if key not in theme_keys():
            fail("palette",
                 "palette key {0} has no brush in {1}".format(key, THEME_FILE))
    for value in re.findall(r'"(#[0-9A-Fa-f]*)"', text):
        if not re.match(r"^#(?:[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$", value):
            fail("palette", "not a hex colour: " + value)


# ---------------------------------------------------------------------------
#  9  IronPython 2.7 / 3 compatibility
# ---------------------------------------------------------------------------
def code_view(text):
    """The source with comments and string literals blanked out, so a rule
    cannot fire on the word it is looking for inside a docstring, and a list
    of the lines that held an f-string prefix."""
    import io
    import tokenize as tk

    lines = text.splitlines()
    blank = list(lines)
    fstring_lines = set()
    try:
        tokens = list(tk.generate_tokens(io.StringIO(text).readline))
    except Exception:
        return lines, fstring_lines

    kill = []
    for token in tokens:
        ttype = token[0]
        tstr = token[1]
        (srow, scol) = token[2]
        (erow, ecol) = token[3]
        name = tk.tok_name.get(ttype, "")
        if name == "FSTRING_START":
            fstring_lines.add(srow)
            continue
        if ttype == tk.STRING:
            if re.match(r"^[rRbBuU]*[fF]", tstr):
                fstring_lines.add(srow)
            kill.append((srow, scol, erow, ecol))
        elif ttype == tk.COMMENT:
            kill.append((srow, scol, erow, len(lines[srow - 1])))

    for (srow, scol, erow, ecol) in kill:
        for row in range(srow, erow + 1):
            if row - 1 >= len(blank):
                continue
            line = blank[row - 1]
            start = scol if row == srow else 0
            end = ecol if row == erow else len(line)
            blank[row - 1] = line[:start] + " " * max(0, end - start) + line[end:]

    return blank, fstring_lines


def check_python_compat(files):
    for name in files:
        text = read(name)
        blank, fstring_lines = code_view(text)
        for row in sorted(fstring_lines):
            fail("no-fstring",
                 "{0}:{1} - f-strings do not exist on IronPython 2.7"
                 .format(name, row))
        for index, line in enumerate(blank):
            stripped = line.strip()
            if not stripped:
                continue
            if re.match(r"^print\s*\(", stripped) or \
                    re.match(r"^print\s+[^=(]", stripped):
                fail("no-print", "{0}:{1}".format(name, index + 1))
            if "System.Uri" in line or \
                    re.search(r"from\s+System\s+import\s+.*\bUri\b", line):
                fail("no-uri",
                     "{0}:{1} - System.Uri moved assemblies in Revit 2025"
                     .format(name, index + 1))


def check_integer_value(files):
    """.IntegerValue is allowed only inside the guarded eid_value helper."""
    for name in files:
        text = read(name)
        blank, _ = code_view(text)
        inside = False
        for index, line in enumerate(blank):
            if re.match(r"^def eid_value\b", line):
                inside = True
                continue
            if inside and line.strip() and not line.startswith((" ", "\t")):
                inside = False
            if ".IntegerValue" in line and not inside:
                fail("no-integervalue",
                     "{0}:{1} - removed in Revit 2026, use eid_value()"
                     .format(name, index + 1))


# ---------------------------------------------------------------------------
# 10  every global a function reaches for exists in its module
# ---------------------------------------------------------------------------
def check_globals(files):
    builtins_names = set(dir(__builtins__)) if not isinstance(__builtins__, dict) \
        else set(__builtins__.keys())
    for name in files:
        text = read(name)
        try:
            table = symtable.symtable(text, name, "exec")
        except SyntaxError as err:
            fail("syntax", "{0}: {1}".format(name, err))
            continue
        top = set([s.get_name() for s in table.get_symbols()])
        _walk_symbols(name, table, top, builtins_names)


def _walk_symbols(filename, table, top, builtins_names):
    for child in table.get_children():
        for symbol in child.get_symbols():
            if not symbol.is_global():
                continue
            sname = symbol.get_name()
            if sname in top or sname in builtins_names:
                continue
            if sname in ("__revit__", "__file__", "__name__", "unicode",
                         "long", "xrange", "basestring", "reduce"):
                continue
            fail("undefined-global",
                 "{0}: {1}() reaches for '{2}', which the module does not "
                 "define".format(filename, child.get_name(), sname))
        _walk_symbols(filename, child, top, builtins_names)


# ---------------------------------------------------------------------------
# 11  the modules load against a stub Revit and .NET API
# ---------------------------------------------------------------------------
def install_stubs():
    """Each name declared in the namespace the real API puts it in, so a
    mis-namespaced import fails on the bench instead of in Revit."""
    import types

    def module(path, names=(), classes=()):
        parts = path.split(".")
        # every level of the namespace has to exist, not just the leaf
        for depth in range(1, len(parts) + 1):
            sub = ".".join(parts[:depth])
            if sub not in sys.modules:
                sys.modules[sub] = types.ModuleType(sub)
            if depth > 1:
                setattr(sys.modules[".".join(parts[:depth - 1])],
                        parts[depth - 1], sys.modules[sub])
        mod = sys.modules[path]
        for item in names:
            setattr(mod, item, _Stub(item))
        for item in classes:
            setattr(mod, item, type(str(item), (object,), {}))
        return mod

    clr_mod = types.ModuleType("clr")
    clr_mod.AddReference = lambda name: None
    sys.modules["clr"] = clr_mod

    module("System", ("Action", "AppDomain", "Array", "Convert"))
    module("System.IO", ("File", "MemoryStream", "StringReader"))
    module("System.Xml", ("XmlReader",))
    module("System.Collections.Generic", ("List",))
    module("System.Collections.ObjectModel", ("ObservableCollection",))
    module("System.Diagnostics", ("Process",))
    module("System.Drawing", ("Rectangle",))
    module("System.Windows.Forms", ("Screen", "MessageBox"))
    module("System.Windows",
           ("Application", "FontWeights", "GridLength", "GridUnitType",
            "HorizontalAlignment", "PresentationSource", "ResourceDictionary",
            "SizeToContent", "Thickness", "VerticalAlignment", "Visibility",
            "WindowState", "RoutedEventHandler"))
    module("System.Windows.Controls",
           ("CheckBox", "ColumnDefinition", "Grid", "Orientation", "StackPanel",
            "TextBlock", "TextBox", "TreeViewItem"))
    module("System.Windows.Controls.Primitives", ("ToggleButton",))
    module("System.Windows.Input", ("Key",))
    module("System.Windows.Interop", ("WindowInteropHelper",))
    module("System.Windows.Markup", ("XamlReader",))
    module("System.Windows.Media",
           ("Brushes", "ColorConverter", "SolidColorBrush", "VisualTreeHelper"))
    module("System.Windows.Media.Imaging", ("BitmapCacheOption", "BitmapImage"))
    module("System.Windows.Threading", ("DispatcherPriority",))

    db = module("Autodesk.Revit.DB",
                ("BuiltInCategory", "BuiltInParameter", "Category",
                 "CategoryType", "CheckoutStatus", "CurveLoop", "Element",
                 "ElementId", "ElementIntersectsSolidFilter",
                 "ElementMulticategoryFilter", "FailureProcessingResult",
                 "FailureSeverity", "FilteredElementCollector",
                 "GeometryCreationUtilities", "GeometryInstance",
                 "InstanceBinding", "LabelUtils", "Line", "Options",
                 "Outline", "BoundingBoxIntersectsFilter", "ParameterType",
                 "SharedParameterElement", "Solid", "SpecTypeId",
                 "StorageType", "Transaction", "TransactionGroup",
                 "TransactionStatus", "ViewDetailLevel", "WorksharingUtils",
                 "XYZ"),
                ("IFailuresPreprocessor",))
    module("Autodesk.Revit.UI",
           ("ExternalEvent", "TaskDialog"), ("IExternalEventHandler",))
    return db


class _Stub(object):
    def __init__(self, name="stub"):
        self._name = name

    def __getattr__(self, item):
        return _Stub(self._name + "." + item)

    def __call__(self, *args, **kwargs):
        return _Stub(self._name + "()")

    def __getitem__(self, item):
        return _Stub(self._name + "[]")

    def __eq__(self, other):
        return False

    def __ne__(self, other):
        return True

    def __hash__(self):
        return hash(self._name)


def check_imports():
    install_stubs()
    sys.path.insert(0, HERE)
    for name in MODULES:
        try:
            __import__(name)
        except Exception as err:
            fail("import",
                 "{0} would not load: {1}: {2}"
                 .format(name, type(err).__name__, err))


# ---------------------------------------------------------------------------
# 12  Setter.TargetName may only name a FrameworkElement
# ---------------------------------------------------------------------------
# WPF cannot retarget a Freezable from a trigger. Naming a RotateTransform and
# setting its Angle threw while the dictionary loaded, the merge was swallowed,
# and every control in the tool silently fell back to its Windows default -
# which reads as a broken dark mode, not as a failure.
NOT_FRAMEWORK_ELEMENTS = (
    "RotateTransform", "ScaleTransform", "TranslateTransform", "SkewTransform",
    "MatrixTransform", "TransformGroup", "SolidColorBrush",
    "LinearGradientBrush", "RadialGradientBrush", "GradientStop",
    "DropShadowEffect", "BlurEffect", "RectangleGeometry", "PathGeometry",
    "EllipseGeometry", "LineGeometry", "GeometryGroup",
)


def check_setter_targets(files):
    for name in files:
        text = read(name)
        bad = set()
        for tag in NOT_FRAMEWORK_ELEMENTS:
            for match in re.finditer(
                    r"<" + tag + r"\b[^>]*?x:Name=\"(\w+)\"", text):
                bad.add((match.group(1), tag))
        for target in re.findall(r'Setter\s+TargetName="(\w+)"', text):
            for (named, tag) in bad:
                if target == named:
                    fail("setter-target",
                         "{0}: a Setter targets '{1}', which is a {2} - WPF "
                         "cannot retarget a Freezable, and the whole "
                         "dictionary fails to load"
                         .format(name, target, tag))


# ---------------------------------------------------------------------------
# 13  every Setter.TargetName exists in its own template
# ---------------------------------------------------------------------------
def check_target_names(files):
    for name in files:
        text = read(name)
        declared = set(re.findall(r'x:Name="(\w+)"', text))
        for target in set(re.findall(r'Setter\s+TargetName="(\w+)"', text)):
            if target not in declared:
                fail("target-name",
                     "{0}: a Setter targets '{1}', which nothing in the file "
                     "declares".format(name, target))


# ---------------------------------------------------------------------------
# 14  a TreeView / DataGrid must not be nested inside a ScrollViewer
# ---------------------------------------------------------------------------
# A control that scrolls itself, put inside a ScrollViewer, grows to its full
# content height. Its own scroll viewer then has nothing to scroll - but it
# still marks the mouse wheel handled, so the outer one never sees it either,
# and the list cannot be scrolled by wheel at all.
SELF_SCROLLING = ("TreeView", "DataGrid", "ListBox", "ListView")


def check_nested_scrollers(layouts):
    for name in layouts:
        text = read(name)
        for match in re.finditer(r"<ScrollViewer\b.*?</ScrollViewer>", text,
                                 re.S):
            block = match.group(0)
            for tag in SELF_SCROLLING:
                if re.search(r"<" + tag + r"\b", block):
                    fail("nested-scroller",
                         "{0}: a <{1}> sits inside a <ScrollViewer> - it will "
                         "not scroll by wheel".format(name, tag))


# ---------------------------------------------------------------------------
# 15  the ribbon name matches the folder
# ---------------------------------------------------------------------------
def check_tool_name():
    folder = os.path.basename(HERE)
    if not folder.endswith(".pushbutton"):
        fail("tool-name", "the tool does not sit in a .pushbutton folder")
        return
    expected = folder[:-len(".pushbutton")]
    core_text = read("snte_core.py")
    match = re.search(r'TOOL_NAME\s*=\s*"([^"]+)"', core_text)
    if match is None:
        fail("tool-name", "snte_core.py has no TOOL_NAME")
        return
    if match.group(1) != expected:
        # pyRevit names a ribbon item after its folder, so a rename that misses
        # one place leaves the old name showing somewhere
        fail("tool-name",
             "TOOL_NAME is '{0}' but the folder is '{1}'"
             .format(match.group(1), expected))
    layout = read("SpaceNameToElement.xaml")
    if expected not in layout:
        fail("tool-name", "the window header does not carry '%s'" % expected)


# ---------------------------------------------------------------------------
#  runner
# ---------------------------------------------------------------------------
def run_all():
    del failures[:]
    files = py_files()
    layouts = LAYOUTS
    check_xaml_parses(layouts + [THEME_FILE])
    check_clr_first(files)
    check_no_static_resource(layouts)
    check_dynamic_keys(layouts)
    check_style_targets(layouts)
    check_findname(files, layouts)
    check_resource_keys(files)
    check_palettes()
    check_python_compat(files)
    check_integer_value(files)
    check_globals(files)
    check_setter_targets(layouts + [THEME_FILE])
    check_target_names(layouts + [THEME_FILE])
    check_nested_scrollers(layouts)
    check_tool_name()
    check_imports()
    return list(failures)


# ---------------------------------------------------------------------------
#  selftest - break each rule on purpose and confirm the check catches it
# ---------------------------------------------------------------------------
BREAKAGES = [
    ("xaml-parses", "SpaceNameToElement.xaml",
     lambda t: t.replace("<!-- ===================== HEADER",
                         "<!-- ------- HEADER")),
    ("clr-first", "snte_core.py",
     lambda t: t.replace("import snte_clr  # noqa: F401  - must be first, "
                         "before any System.* / Autodesk.*\n", "")
                .replace("from Autodesk.Revit import DB",
                         "from Autodesk.Revit import DB\nimport snte_clr")),
    ("no-staticresource", "SpaceNameToElement.xaml",
     lambda t: t.replace('{DynamicResource BtnGreen}',
                         '{StaticResource BtnGreen}', 1)),
    ("dynamic-key", "SpaceNameToElement.xaml",
     lambda t: t.replace('{DynamicResource BtnGreen}',
                         '{DynamicResource BtnNotAThing}', 1)),
    ("style-target", "SpaceNameToElement.xaml",
     lambda t: t.replace('<TextBox Grid.Row="1" Grid.Column="0" x:Name="search_tb"\n'
                         '                         Style="{DynamicResource DarkBox}"',
                         '<TextBox Grid.Row="1" Grid.Column="0" x:Name="search_tb"\n'
                         '                         Style="{DynamicResource BtnGreen}"')),
    ("findname", "snte_window.py",
     lambda t: t.replace('self._find("status_txt")', 'self._find("status_text")')),
    ("resource-key", "snte_window.py",
     lambda t: t.replace('self.window.FindResource(brush_key)',
                         'self.window.FindResource("NoSuchBrush")')),
    ("palette", "theme.py",
     lambda t: t.replace('    "ThumbBg": "#5A5A62",\n', "", 1)),
    ("no-fstring", "snte_core.py",
     lambda t: t.replace('    return name or number or ""',
                         '    return f"{name}"')),
    ("no-print", "snte_core.py",
     lambda t: t.replace("    return name or number or \"\"",
                         "    print(name)\n    return name")),
    ("no-uri", "snte_ui.py",
     lambda t: t.replace("from System.IO import File, MemoryStream, StringReader",
                         "from System import Uri\n"
                         "from System.IO import File, MemoryStream, StringReader")),
    ("no-integervalue", "snte_core.py",
     lambda t: t.replace("        cid = eid_value(cat.Id)",
                         "        cid = cat.Id.IntegerValue")),
    ("undefined-global", "snte_core.py",
     lambda t: t.replace("    return name or number or \"\"",
                         "    return helper_that_does_not_exist(name)")),
    ("tool-name", "snte_core.py",
     lambda t: t.replace('TOOL_NAME = "Space Name To Element"',
                         'TOOL_NAME = "Space Name To Elements"')),
    ("setter-target", "Theme.xaml",
     lambda t: t.replace(
         '<Path x:Name="open" Data="M 0,0 L 8,0 L 4,4.5 Z"',
         '<Path Data="M 0,0 L 8,0 L 4,4.5 Z">\n'
         '<Path.RenderTransform><RotateTransform x:Name="open" Angle="0"/>'
         '</Path.RenderTransform></Path>\n<Path x:Name="spare"')),
    ("target-name", "Theme.xaml",
     lambda t: t.replace('<Setter TargetName="shut" Property="Visibility"',
                         '<Setter TargetName="shutt" Property="Visibility"')),
    ("nested-scroller", "SpaceNameToElement.xaml",
     lambda t: t.replace(
         '<TreeView x:Name="cat_tree" Background="Transparent"',
         '<ScrollViewer><TreeView x:Name="cat_tree" Background="Transparent"')
                .replace('ScrollViewer.CanContentScroll="False"/>',
                         'ScrollViewer.CanContentScroll="False"/></ScrollViewer>')),
    ("import", "snte_core.py",
     lambda t: t.replace("from Autodesk.Revit import DB",
                         "from Autodesk.Revit.DB import ExternalEvent")),
]


def selftest():
    import shutil
    import tempfile

    baseline = run_all()
    if baseline:
        sys.stdout.write("selftest cannot run - the tool does not pass "
                         "cleanly first:\n")
        for item in baseline:
            sys.stdout.write("  " + item + "\n")
        return 1

    global HERE
    original = HERE
    caught = 0
    missed = []

    for rule, filename, mangle in BREAKAGES:
        # the folder has to be named exactly as the real one, or the
        # tool-name rule would fire on the temp folder instead of the breakage
        holder = tempfile.mkdtemp()
        workdir = os.path.join(holder, os.path.basename(original))
        os.makedirs(workdir)
        try:
            for item in os.listdir(original):
                src = os.path.join(original, item)
                if os.path.isfile(src):
                    shutil.copy2(src, os.path.join(workdir, item))
            target = os.path.join(workdir, filename)
            text = open(target, "r").read()
            broken = mangle(text)
            if broken == text:
                missed.append(rule + " (the breakage did not apply)")
                continue
            handle = open(target, "w")
            handle.write(broken)
            handle.close()

            HERE = workdir
            for name in MODULES:
                sys.modules.pop(name, None)
            problems = run_all()
            hit = [p for p in problems if p.startswith("[" + rule + "]")]
            if hit:
                caught += 1
                sys.stdout.write("  caught {0}: {1}\n".format(rule, hit[0]))
            else:
                missed.append("{0} - breaking {1} raised: {2}".format(
                    rule, filename, problems or "nothing"))
        finally:
            HERE = original
            shutil.rmtree(holder, ignore_errors=True)
            for name in MODULES:
                sys.modules.pop(name, None)

    sys.stdout.write("\n{0} of {1} rules caught their own breakage.\n"
                     .format(caught, len(BREAKAGES)))
    for item in missed:
        sys.stdout.write("  NOT CAUGHT: " + item + "\n")
    return 1 if missed else 0


def main():
    if "--selftest" in sys.argv:
        return selftest()
    problems = run_all()
    if problems:
        sys.stdout.write("FAILED - {0} problem(s)\n".format(len(problems)))
        for item in problems:
            sys.stdout.write("  " + item + "\n")
        return 1
    sys.stdout.write("All checks passed.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
