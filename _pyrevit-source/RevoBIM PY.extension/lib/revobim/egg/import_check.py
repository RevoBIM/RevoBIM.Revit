# -*- coding: utf-8 -*-
"""Bench check for the easter egg. Runs under plain CPython.

    python import_check.py
    python import_check.py --selftest

The selftest breaks each rule on purpose and confirms the check catches it. A
rule nobody has tested is a rule that does not work - two of the rules in the
other RevoBIM tools were doing nothing at all until their selftest proved it.
"""

import os
import re
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
GAMES = os.path.join(HERE, "games")

MODULES = ["egg_clr.py", "egg_log.py", "egg_settings.py", "egg_scores.py",
           "egg_theme.py", "egg_surface.py", "egg_registry.py", "egg_shell.py",
           "egg_hook.py", "egg_launcher.py", "egg_desktop.py", "egg_auto.py",
           "__init__.py"]

# Modules that must run with no .NET at all, because the desktop build imports
# them outside Revit under plain CPython. This list is the contract that makes
# running outside Revit possible; adding a System.* import to any of them
# silently breaks the standalone app while leaving the Revit one working.
PORTABLE = ["egg_log.py", "egg_settings.py", "egg_scores.py", "egg_theme.py",
            "egg_registry.py", "egg_desktop.py", "egg_launcher.py",
            "__init__.py"]

# Modules that are allowed to reach into System.* - all of them must import
# egg_clr first, and these are the ones that do.
CLR_FIRST = ["egg_surface.py", "egg_shell.py", "egg_hook.py", "egg_auto.py"]

BANNED = [
    (re.compile(r"""(^|[^A-Za-z0-9_])f["']"""), "f-string"),
    (re.compile(r"^\s*print\s+[^(=]"), "print statement"),
    (re.compile(r"\.IntegerValue"), "bare .IntegerValue"),
    (re.compile(r"from\s+System\s+import\s+[^\n]*\bUri\b"), "System.Uri"),
    (re.compile(r"System\.Uri"), "System.Uri"),
    (re.compile(r"WindowStyle\s*\.\s*None"), "WindowStyle.None written directly"),
]

FORBIDDEN_REFS = ("RevitAPI", "RevitAPIUI")

GAME_ATTRS = ("NAME", "KEY", "TICK_MS", "KEYS", "Game")
GAME_METHODS = ("start", "stop", "tick", "render", "key", "status",
                "is_over", "width", "height")


class Failure(Exception):
    pass


def _read(path):
    handle = open(path, "r")
    try:
        return handle.read()
    finally:
        handle.close()


def _sources(folder, names=None):
    out = []
    for entry in sorted(os.listdir(folder)):
        if not entry.endswith(".py"):
            continue
        if names is not None and entry not in names:
            continue
        out.append((entry, os.path.join(folder, entry)))
    return out


# -- the rules ===========================================================

def rule_compiles(report, texts):
    """Every module compiles."""
    for name, text in texts:
        try:
            compile(text, name, "exec")
        except SyntaxError:
            error = sys.exc_info()[1]
            raise Failure("{0} will not compile: line {1}: {2}".format(
                name, error.lineno, error.msg))
    report.append("compiles: {0} modules".format(len(texts)))


def rule_no_banned(report, texts):
    """No f-strings, print statements, .IntegerValue, System.Uri.

    All four run on IronPython 2.7 as well as 3, which is what pyRevit may pick
    depending on the release.
    """
    hits = 0
    for name, text in texts:
        for number, line in enumerate(text.splitlines(), 1):
            if line.strip().startswith("#"):
                continue
            for pattern, label in BANNED:
                if pattern.search(line):
                    raise Failure("{0}:{1} uses {2}".format(name, number,
                                                            label))
            hits += 1
    report.append("no banned constructs: {0} lines".format(hits))


def rule_no_revit_refs(report, texts):
    """No clr.AddReference for RevitAPI or RevitAPIUI.

    Re-referencing either causes access violations, and the egg has no business
    touching the Revit API at all.
    """
    for name, text in texts:
        for ref in FORBIDDEN_REFS:
            # Not just the literal AddReference("RevitAPI") call: egg_clr loops
            # a tuple of assembly names, so the way this mistake would actually
            # get made is a new entry in that tuple. Any quoted mention at all
            # is the failure.
            if re.search(r'["\']' + ref + r'["\']', text):
                raise Failure("{0} names the assembly {1}".format(name, ref))
    report.append("no RevitAPI / RevitAPIUI references")


def rule_clr_first(report, texts):
    """egg_clr is imported before any System.* name in the file.

    Import order inside a file is load order, and the assembly reference has to
    win. This is the single most likely way to break anything in this extension
    and the least obvious to diagnose: it lands as a blank white pyRevit window
    with no traceback in it.
    """
    lookup = dict(texts)
    for name in CLR_FIRST:
        text = lookup.get(name)
        if text is None:
            continue
        clr_line = None
        system_line = None
        for number, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "egg_clr" in stripped and clr_line is None:
                clr_line = number
            if re.match(r"(from|import)\s+System(\.|\s)", stripped):
                if system_line is None:
                    system_line = number
        if clr_line is None:
            raise Failure("{0} never imports egg_clr".format(name))
        if system_line is not None and system_line < clr_line:
            raise Failure(
                "{0} reaches System.* on line {1}, before egg_clr on line "
                "{2}".format(name, system_line, clr_line))
    report.append("egg_clr imported first: {0} modules".format(len(CLR_FIRST)))


def rule_auto_attach_is_safe(report, texts):
    """The class handler must be cheap, quiet and idempotent.

    `EventManager.RegisterClassHandler` on `Window.Loaded` fires for **every
    window every addin in Revit opens**, not just ours. That is what makes it
    able to wire every tool without editing any of them, and it is also what
    makes it the most dangerous thing in the package:

    1. it must never throw, or window creation breaks for other people's addins
    2. it must not walk the logical tree of every dialog Revit shows, so the
       cheap named lookup has to come first
    3. it must not hook the same window twice when Loaded fires again
    4. installing twice must do nothing, since a pasted-together startup.py can
       easily call it more than once
    """
    lookup = dict(texts)
    auto = lookup.get("egg_auto.py")
    if auto is None:
        raise Failure("egg_auto.py is not in the checked modules")
    code = _code_only(auto)

    start = code.index("def _on_loaded")
    end = code.index("def _name_of")
    handler = code[start:end]
    if "except Exception" not in handler:
        raise Failure("_on_loaded is not wrapped; it runs inside every "
                      "window's Loaded, for every addin in the process")
    if "deep=False" not in handler:
        raise Failure("_on_loaded does the deep tree walk on every window, "
                      "including every dialog Revit opens")
    if "_mark(window, DONE)" not in handler:
        raise Failure("_on_loaded does not mark a window it has wired, so a "
                      "second Loaded stacks a second hook on it")

    install = code[code.index("def install"):code.index("def status")]
    if "_state[\"installed\"]" not in install:
        raise Failure("install() is not idempotent; a startup.py that calls it "
                      "twice would register two class handlers")

    if "def find_logo(window, names=None, deep=True)" not in \
            _code_only(lookup["egg_hook.py"]):
        raise Failure("find_logo has no shallow mode for the auto handler")
    report.append("auto-attach: wrapped, shallow first, marked, idempotent")


def rule_more_than_one_anchor(report, texts):
    r"""The egg must not depend on any single shared file.

    There is exactly one `startup.py` per extension, so every tool that ships
    one is fighting over the same file and whichever zip is unpacked last wins.
    The egg losing that fight is silent - nothing fails, the game simply never
    appears again, and there is no error to go looking for.

    So it is anchored in more than one place, using more than one pyRevit
    mechanism, and every anchor is idempotent so all of them running is fine:

    1. `startup.py` at the extension root
    2. `hooks\app-init.py`  - a different mechanism, a different folder
    3. `hooks\doc-opened.py` - in case a release handles app-init differently
    4. `egg_hook.attach` arms it too, so one hand-wired tool brings the rest
       back even if all three files above have been lost

    This rule fails if fewer than three of the file anchors are present, because
    two is one bad zip away from none.
    """
    root = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
    anchors = [
        ("startup.py", os.path.join(root, "startup.py")),
        ("hooks/app-init.py", os.path.join(root, "hooks", "app-init.py")),
        ("hooks/doc-opened.py", os.path.join(root, "hooks", "doc-opened.py")),
    ]

    live = []
    for label, path in anchors:
        if not os.path.isfile(path):
            continue
        text = _read(path)
        if "egg_auto" not in text or "install()" not in text:
            raise Failure("{0} exists but does not install the "
                          "auto-attachment".format(label))
        if "try:" not in text or "except Exception" not in text:
            raise Failure("{0} is not wrapped; a startup or hook that throws "
                          "breaks the whole extension".format(label))
        if "sys.path" not in text:
            raise Failure("{0} does not put lib on the path, so the import "
                          "will fail".format(label))
        if not _compiles(text, path):
            raise Failure("{0} does not compile".format(label))
        live.append(label)

    if len(live) < 3:
        raise Failure(
            "only {0} anchor(s) present ({1}); the egg must not depend on any "
            "one shared file, because another tool's delivery will overwrite "
            "it and nothing will fail".format(len(live), ", ".join(live)))

    startup = _read(os.path.join(root, "startup.py"))
    if startup.count("=" * 20) < 2:
        raise Failure("startup.py is not banded, so there is nothing to show "
                      "which part to paste into an existing one")

    hook_source = _code_only(dict(texts)["egg_hook.py"])
    if "_arm_auto()" not in hook_source:
        raise Failure("attach() does not arm the automatic attachment, so a "
                      "hand-wired tool cannot bring the others back")
    report.append("anchors: {0}, plus attach() itself".format(len(live)))


def _compiles(text, path):
    try:
        compile(text, path, "exec")
        return True
    except SyntaxError:
        return False


BUTTON = ("RevoBIM PY.tab", "Coordination.panel", "Routines.pulldown",
          "RevoBIM Arcade.pushbutton")


def rule_ribbon_button(report, texts):
    r"""The Arcade button ships, and does not disturb the pulldown it joins.

    Four things, each of which has bitten a RevoBIM tool before:

    1. **pyRevit names a ribbon item after its folder**, so the folder and the
       bundle title have to agree or the ribbon shows one name and the keyboard
       shortcuts dialog another.
    2. **The title is a single line.** A wrapped title comes out mangled in
       Revit's Keyboard Shortcuts list.
    3. **No `Routines.pulldownundle.yaml` is shipped.** That pulldown already
       exists and is shared with QFR Remover and Fire Damper Wall Type Push;
       shipping one would silently revert whatever they set. Same rule as
       startup.py, one level down.
    4. **The script loads in stages and reports which one failed**, rather than
       leaving pyRevit's blank white window.
    """
    root = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
    folder = os.path.join(root, *BUTTON)
    if not os.path.isdir(folder):
        raise Failure("the Arcade pushbutton is not there: {0}".format(folder))

    name = BUTTON[-1].replace(".pushbutton", "")
    bundle = os.path.join(folder, "bundle.yaml")
    if not os.path.isfile(bundle):
        raise Failure("the Arcade button ships no bundle.yaml")
    text = _read(bundle)

    title = None
    for line in text.splitlines():
        if line.strip().startswith("title:"):
            title = line.split(":", 1)[1].strip()
            break
    if title is None:
        raise Failure("the Arcade bundle.yaml sets no title")
    if title != name:
        raise Failure("the bundle title is {0} but the folder is {1}; pyRevit "
                      "names the ribbon item after the folder".format(title,
                                                                      name))
    if "\n" in title or len(title) > 24:
        raise Failure("the button title is not a single short line, so it "
                      "comes out mangled in Keyboard Shortcuts")

    shared = os.path.join(root, "RevoBIM PY.tab", "Coordination.panel",
                          "Routines.pulldown", "bundle.yaml")
    if os.path.isfile(shared):
        raise Failure("a Routines.pulldown bundle.yaml is being shipped; that "
                      "pulldown is shared and this would revert it")
    panel = os.path.join(root, "RevoBIM PY.tab", "Coordination.panel",
                         "bundle.yaml")
    if os.path.isfile(panel):
        raise Failure("a Coordination.panel bundle.yaml is being shipped; that "
                      "panel already exists")

    script = os.path.join(folder, "script.py")
    if not os.path.isfile(script):
        raise Failure("the Arcade button ships no script.py")
    source = _read(script)
    if not _compiles(source, script):
        raise Failure("the Arcade script.py does not compile")
    code = _code_only(source)
    if "_STAGE" not in code or "_report(" not in code:
        raise Failure("the Arcade script does not load in stages, so a failure "
                      "is pyRevit's blank white window")
    if "egg_hook" not in code:
        raise Failure("the Arcade script does not open the game")
    if not os.path.isfile(os.path.join(folder, "icon.png")):
        raise Failure("the Arcade button ships no icon")

    report.append("ribbon: Arcade button, shared bundles left alone")


def rule_runs_off_revits_thread(report, texts):
    """The game must not be stuck on Revit's UI thread.

    A window belongs to the thread that created it and repaints on that thread's
    dispatcher. Up to 1.6.0 the egg was built on Revit's UI thread, so any
    pyRevit tool holding that thread froze the game solid until it finished -
    which is exactly what it did.

    Four things are held here, because each one alone puts it straight back:

    1. there is a threaded path at all, and it runs a dispatcher on it
    2. the thread is STA, which WPF requires, and background, so it cannot keep
       Revit alive after somebody has asked it to close
    3. the window is built *inside* the thread. Building it outside and showing
       it there leaves it owned by Revit's dispatcher and changes nothing
    4. ownership goes through the HWND, not `window.Owner` - WPF will not let a
       window on one thread own a window on another, and it throws
    """
    lookup = dict(texts)
    shell = lookup.get("egg_shell.py")
    if shell is None:
        raise Failure("egg_shell.py is not in the checked modules")
    code = _code_only(shell)

    if "_launch_threaded" not in code:
        raise Failure("no threaded path: the game runs on Revit's UI thread "
                      "and freezes whenever a tool holds it")
    if "Dispatcher.Run()" not in code:
        raise Failure("the game thread never runs a dispatcher, so its window "
                      "will not repaint or take input")
    if "ApartmentState.STA" not in code:
        raise Failure("the game thread is not STA; WPF will refuse to create a "
                      "window on it")
    if "IsBackground = True" not in code:
        raise Failure("the game thread is not a background thread, so it keeps "
                      "Revit alive after somebody has closed it")

    # The window has to be constructed inside the thread body, not handed in.
    start = code.index("def _launch_threaded")
    end = code.index("def _launch_inline")
    body = code[start:end]
    if "EggWindow(" not in body:
        raise Failure("_launch_threaded does not build the window on its own "
                      "thread, so the window still belongs to Revit's")
    if "WindowInteropHelper" not in code or "host_handle" not in code:
        raise Failure("ownership does not go through the window handle; "
                      "window.Owner across threads throws")

    settings = _load_isolated("egg_settings_mode",
                              os.path.join(HERE, "egg_settings.py"))
    if settings.DEFAULTS.get("run_mode") != "auto":
        raise Failure("run_mode does not default to auto, so the fix does not "
                      "reach anybody who has not gone looking for it")

    # Starting a thread and starting a game are not the same event.
    if "_window_appeared" not in code:
        raise Failure("_launch_threaded reports success on Thread.Start "
                      "returning, so a thread that dies on its first line "
                      "looks exactly like a button that does nothing")
    report.append("threading: own STA thread, own dispatcher, proved open")


def rule_no_blocking_sleep_on_revits_thread(report, texts):
    """Nothing waits on Revit's thread with Thread.Sleep or time.sleep.

    Revit's UI thread is STA. `Thread.Sleep` on an STA thread does not pump
    messages, and IronPython says so out loud - a RuntimeWarning written to
    stderr, which is what makes pyRevit throw up a blank white output window
    behind the game. It reads as a crash.

    `Thread.CurrentThread.Join(ms)` is the documented way to wait on an STA
    thread; it pumps, and it says nothing. It lives in one helper, `pause()`,
    and everything that waits goes through it.

    `egg_launcher` is portable and cannot import Thread at all, so its wait is
    injected by the caller instead - `time.sleep` is exactly right on a desktop
    and exactly wrong inside Revit.
    """
    lookup = dict(texts)
    shell = _code_only(lookup["egg_shell.py"])

    if "Thread.CurrentThread.Join" not in shell:
        raise Failure("nothing waits with Join; a Sleep on Revit's STA thread "
                      "prints a warning and pops the output window")

    body = shell
    marker = "def pause("
    if marker in body:
        start = body.index(marker)
        end = body.index("def _window_appeared")
        outside = body[:start] + body[end:]
    else:
        outside = body
    if "Thread.Sleep" in outside:
        raise Failure("Thread.Sleep is used outside the pause() helper")
    if "time.sleep" in outside:
        raise Failure("time.sleep is used on Revit's thread")

    launcher = _code_only(lookup["egg_launcher.py"])
    if "def spawn(game_key=None, pause=None)" not in launcher:
        raise Failure("spawn() does not take an injected pause, so it will "
                      "time.sleep on Revit's STA thread")
    if "pause=pause" not in shell:
        raise Failure("the shell does not pass its STA-safe pause to spawn()")
    report.append("waiting: STA-safe, through one helper")


def rule_nothing_claims_success_it_has_not_checked(report, texts):
    """Starting a thing is not the same event as the thing working.

    Both of the ways the Arcade button silently did nothing were this mistake:
    `Thread.Start` returning was taken as the game having opened, and
    `subprocess.Popen` returning was taken as the desktop build having run.
    Neither is evidence. A Python that is 2, or 3 without tkinter, starts
    perfectly and exits half a second later.

    It is the same lesson as proving a parameter write by reading it back, and
    it is worth a rule because the failure is always invisible: the caller is
    told it worked, so nothing is reported anywhere.
    """
    lookup = dict(texts)

    launcher = _code_only(lookup["egg_launcher.py"])
    if "if not _survives(" not in launcher:
        raise Failure("spawn() returns True on Popen alone; a process that "
                      "exits immediately is reported as a running game")
    if "arcade_process.log" not in launcher:
        raise Failure("nothing captures the spawned process's stderr, so a "
                      "Python that refuses says why into the void")

    shell = _code_only(lookup["egg_shell.py"])
    if "if not _window_appeared()" not in shell:
        raise Failure("_launch_threaded does not wait for the window")

    button = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
    script = os.path.join(button, *BUTTON) + os.sep + "script.py"
    if os.path.isfile(script):
        source = _code_only(_read(script))
        if "__persistentengine__" not in source:
            raise Failure(
                "the Arcade button does not set __persistentengine__, so "
                "pyRevit disposes the engine as the command returns and takes "
                "the game thread with it")
    report.append("evidence: spawn and thread both proved, engine kept alive")


def rule_version_is_present(report, texts):
    """__init__.py declares __version__, and every module can reach it.

    Written after shipping a build whose __init__.py was empty. A bad version
    bump truncated it - `open(path, "w")` is evaluated before the `read()` whose
    result is being written, so the file was emptied before it was read.

    Nothing caught it. An empty file compiles, imports, and passes every other
    rule here. It fails at exactly one line, `from revobim.egg import
    __version__`, which sits inside the try/except that stops the egg breaking a
    tool - so the entire egg was dead and looked like nothing at all.
    """
    lookup = dict(texts)
    init = lookup.get("__init__.py")
    if init is None:
        raise Failure("__init__.py is not in the checked modules")
    if not init.strip():
        raise Failure("__init__.py is empty; every module that reads "
                      "__version__ from it will fail to import")

    found = re.search(r'__version__\s*=\s*["\']([0-9]+\.[0-9]+\.[0-9]+)["\']',
                      _code_only(init))
    if not found:
        raise Failure("__init__.py declares no __version__")
    version = found.group(1)

    for name, text in texts:
        if "from revobim.egg import __version__" in text:
            break

    changelog = os.path.join(HERE, "CHANGELOG.md")
    if os.path.isfile(changelog):
        top = None
        for line in _read(changelog).splitlines():
            hit = re.match(r"##\s+([0-9]+\.[0-9]+\.[0-9]+)", line.strip())
            if hit:
                top = hit.group(1)
                break
        if top and top != version:
            raise Failure("__init__ says {0} but the changelog's newest entry "
                          "is {1}".format(version, top))
    report.append("version: {0}, and the changelog agrees".format(version))


def rule_portable_modules_have_no_dotnet(report, texts):
    """The shared modules must import nothing from .NET.

    The desktop build runs these under plain CPython, outside Revit, with no
    engine and no clr. One `from System.Windows import ...` added to any of them
    breaks the standalone app while leaving the Revit one working perfectly -
    which is the worst shape a regression can take, because the person who added
    it has no reason to look.

    egg_theme's late, guarded peek at Autodesk.Revit.UI is the one exception,
    and it is inside a function in a try/except: it is allowed to fail, and on a
    desktop it always does.
    """
    lookup = dict(texts)
    for name in PORTABLE:
        text = lookup.get(name)
        if text is None:
            raise Failure("{0} is listed as portable but is not "
                          "checked".format(name))
        for number, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#") or not stripped:
                continue
            if re.match(r"(from|import)\s+clr(\.|\s|$)", stripped):
                raise Failure("{0}:{1} imports clr; it has to run outside "
                              "Revit".format(name, number))
            if re.match(r"(from|import)\s+System(\.|\s|$)", stripped):
                raise Failure("{0}:{1} reaches into System.*; it has to run "
                              "outside Revit".format(name, number))
            if "egg_clr" in stripped and "import" in stripped:
                raise Failure("{0}:{1} imports egg_clr, which calls "
                              "clr.AddReference".format(name, number))
            if re.match(r"(from|import)\s+Autodesk", stripped):
                # Only allowed inside a function, guarded - not at module level.
                if not line.startswith("        "):
                    raise Failure(
                        "{0}:{1} imports Autodesk at module level; outside "
                        "Revit that is a hard failure".format(name, number))
    report.append("portable: {0} modules run with no .NET".format(
        len(PORTABLE)))


def rule_desktop_matches_the_surface(report, texts):
    """The Tk surface answers every call the WPF one does.

    A game is written against the surface and nothing else, so a method that
    exists in one implementation and not the other is a game that runs in Revit
    and crashes on the desktop, or the reverse. Checked by parsing both rather
    than by importing, since tkinter is not always installed on a bench.
    """
    import ast

    def methods(source, class_name):
        found = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                for item in node.body:
                    if isinstance(item, ast.FunctionDef):
                        found.add(item.name)
        return found

    lookup = dict(texts)
    wpf = methods(lookup["egg_surface.py"], "Surface")
    tk = methods(lookup["egg_desktop.py"], "TkSurface")

    public_wpf = set([name for name in wpf if not name.startswith("_")])
    public_tk = set([name for name in tk if not name.startswith("_")])
    missing = sorted(public_wpf - public_tk)
    if missing:
        raise Failure("the Tk surface is missing {0}, so a game that calls it "
                      "works in Revit and dies on the desktop".format(
                          ", ".join(missing)))
    report.append("desktop: the Tk surface covers all {0} surface "
                  "calls".format(len(public_wpf)))


def rule_namespaces(report, texts):
    """Every .NET name is imported from the namespace the real API puts it in.

    Same stub trick as the other tools. Orientation in particular lives in
    System.Windows.Controls, not System.Windows, and importing it from the wrong
    one is a module-load failure rather than a runtime error.
    """
    declared = {
        "System": ("Action", "AppDomain", "Environment", "Object",
                   "TimeSpan"),
        "System.Threading": ("ApartmentState", "Thread", "ThreadStart"),
        "System.Diagnostics": ("Process", "Stopwatch"),
        "System.Windows": ("CornerRadius", "FontWeights", "GridLength",
                           "HorizontalAlignment", "Point",
                           "PresentationSource", "ResizeMode", "Size",
                           "EventManager", "FrameworkElement",
                           "LogicalTreeHelper", "RoutedEventHandler",
                           "SystemParameters",
                           "TextAlignment", "Thickness", "UIElement",
                           "VerticalAlignment", "Visibility", "Window",
                           "WindowStartupLocation", "WindowStyle"),
        "System.Windows.Controls": ("Border", "Canvas", "ColumnDefinition",
                                    "Grid", "Image", "Orientation",
                                    "RowDefinition", "StackPanel",
                                    "StretchDirection", "TextBlock",
                                    "Viewbox"),
        "System.Windows.Controls.Primitives": ("Thumb",),
        "System.Windows.Forms": ("Screen",),
        "System.Windows.Input": ("Cursors", "Key",
                                 "MouseButtonEventHandler"),
        "System.Windows.Interop": ("WindowInteropHelper",),
        "System.Windows.Media": ("ArcSegment", "ColorConverter",
                                 "CompositionTarget", "FontFamily",
                                 "LineSegment", "PathFigure", "PathGeometry",
                                 "SolidColorBrush", "Stretch",
                                 "SweepDirection"),
        "System.Windows.Shapes": ("Ellipse", "Path", "Rectangle"),
        "System.Windows.Threading": ("Dispatcher", "DispatcherTimer"),
    }
    known = set()
    for namespace in declared:
        for member in declared[namespace]:
            known.add((namespace, member))

    pattern = re.compile(r"^\s*from\s+(System[\w.]*)\s+import\s+\(?([^)#]*)")
    checked = 0
    for name, text in texts:
        buffer = text.replace("\\\n", " ")
        for block in re.finditer(
                r"from\s+(System[\w.]*)\s+import\s+\(([^)]*)\)", buffer):
            _check_members(name, block.group(1), block.group(2), known,
                           declared)
            checked += 1
        for line in buffer.splitlines():
            if "(" in line:
                continue
            found = pattern.match(line)
            if found:
                _check_members(name, found.group(1), found.group(2), known,
                               declared)
                checked += 1
    report.append("namespaces declared: {0} imports".format(checked))


def _check_members(module_name, namespace, members, known, declared):
    for member in members.split(","):
        member = member.strip().split(" as ")[0].strip()
        if not member or member.startswith("#"):
            continue
        if (namespace, member) in known:
            continue
        homes = [space for space in declared if member in declared[space]]
        if homes:
            raise Failure(
                "{0} imports {1} from {2}; the real API puts it in "
                "{3}".format(module_name, member, namespace, homes[0]))
        raise Failure(
            "{0} imports {1} from {2}, which the bench does not know about - "
            "add it to the declared namespaces".format(module_name, member,
                                                       namespace))


def rule_palettes_match(report, texts):
    """Both palettes carry every key, and every key a game asks for exists."""
    theme = _load_isolated("egg_theme_probe", os.path.join(HERE,
                                                           "egg_theme.py"))
    dark = set(theme.DARK.keys())
    light = set(theme.LIGHT.keys())
    if dark != light:
        missing = sorted(dark.symmetric_difference(light))
        raise Failure("palettes differ: {0}".format(", ".join(missing)))

    used = set()
    for name, path in _sources(GAMES):
        text = _read(path)
        for found in re.finditer(r'"([a-z_0-9]+)"\s*\)', text):
            used.add(found.group(1))
    unknown = sorted([key for key in used
                      if key in _PALETTE_LOOKING and key not in dark])
    if unknown:
        raise Failure("games use palette keys that do not exist: {0}".format(
            ", ".join(unknown)))
    report.append("palettes: {0} keys, both themes".format(len(dark)))


# Words a game passes as a colour. Anything else in that position is a key of
# some other kind and is not the palette's business.
_PALETTE_LOOKING = set([
    "bg", "card", "field", "bar", "edge", "chrome", "text", "muted", "blue",
    "orange", "green", "red", "sel", "maze", "maze_fill", "pellet", "power",
    "hero", "ghost_1", "ghost_2", "ghost_3", "ghost_4", "scared", "scared_end",
    "eyes", "pupil", "veil",
])


def rule_settings_keys(report, texts):
    """Every settings key the code reads is in DEFAULTS.

    A key read but never defaulted comes back as None the first time anybody
    runs the tool, which is the kind of thing that only shows up on a clean
    machine.
    """
    settings = _load_isolated("egg_settings_probe",
                              os.path.join(HERE, "egg_settings.py"))
    defaults = set(settings.DEFAULTS.keys())
    pattern = re.compile(r'settings\s*\.\s*get\(\s*["\']([a-z_]+)["\']')
    for name, text in texts:
        for found in pattern.finditer(text):
            key = found.group(1)
            if key not in defaults and not key.startswith("high_"):
                raise Failure("{0} reads settings key '{1}', which is not in "
                              "DEFAULTS".format(name, key))
    pattern = re.compile(r'get_int\(\s*\w+\s*,\s*["\']([a-z_]+)["\']')
    for name, text in texts:
        for found in pattern.finditer(text):
            key = found.group(1)
            # High scores are keyed per game, so their names are not known up
            # front and cannot sit in DEFAULTS.
            if key not in defaults and not key.startswith("high_"):
                raise Failure("{0} reads settings key '{1}', which is not in "
                              "DEFAULTS".format(name, key))
    report.append("settings keys: {0} defaults".format(len(defaults)))


def rule_games_contract(report, texts):
    """Every game answers the contract, and imports nothing but the standard
    library.

    A game that reached into WPF would work in Revit and be untestable here,
    which is the whole reason the surface exists.
    """
    count = 0
    for name, path in _sources(GAMES):
        if name == "__init__.py":
            continue
        text = _read(path)
        for line in text.splitlines():
            if re.match(r"\s*(from|import)\s+(System|Autodesk|clr)", line):
                raise Failure("{0} imports .NET or the Revit API; games go "
                              "through the surface".format(name))
        module = _load_isolated("game_probe_" + name[:-3], path)
        for attr in GAME_ATTRS:
            if not hasattr(module, attr):
                raise Failure("{0} has no {1}".format(name, attr))
        for method in GAME_METHODS:
            if not hasattr(module.Game, method):
                raise Failure("{0}.Game has no {1}()".format(name, method))
        probe = module.Game(None, {})
        if probe.width() <= 0 or probe.height() <= 0:
            raise Failure("{0} reports a zero sized board".format(name))
        count += 1
    report.append("games: {0} answer the contract".format(count))


def rule_games_play(report, texts):
    """Every game survives a few hundred ticks against a fake surface.

    This is what catches a mover that steps over its alignment point and never
    turns again, or a level that clears into an exception.
    """
    for name, path in _sources(GAMES):
        if name == "__init__.py":
            continue
        module = _load_isolated("game_play_" + name[:-3], path)
        surface = _FakeSurface()
        game = module.Game(surface, {})
        game.start()
        turns = ("Left", "Up", "Right", "Down")
        for step in range(900):
            game.tick()
            game.render(0.5)
            if step % 23 == 0:
                game.key(turns[(step // 23) % 4])
        if surface.drawn == 0:
            raise Failure("{0} drew nothing in 900 ticks".format(name))
    report.append("games play: 900 ticks each")


def rule_pacman_maze(report, texts):
    """The maze is rectangular, walled all round bar the tunnel, and every
    pellet is reachable from the hero's start."""
    pacman = _load_isolated("pacman_maze", os.path.join(GAMES, "pacman.py"))
    maze = pacman.MAZE
    width = len(maze[0])
    for row in range(len(maze)):
        if len(maze[row]) != width:
            raise Failure("maze row {0} is {1} wide, not {2}".format(
                row, len(maze[row]), width))
    for col in range(width):
        if maze[0][col] != "#" or maze[-1][col] != "#":
            raise Failure("maze is open at the top or bottom, column "
                          "{0}".format(col))

    start = None
    for row in range(len(maze)):
        for col in range(width):
            if maze[row][col] == "P":
                start = (col, row)
    if start is None:
        raise Failure("the maze has no hero start")

    seen = set([start])
    queue = [start]
    while queue:
        col, row = queue.pop()
        for step in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            nxt = ((col + step[0]) % width, row + step[1])
            if nxt[1] < 0 or nxt[1] >= len(maze):
                continue
            if maze[nxt[1]][nxt[0]] in ("#", "-"):
                continue
            if nxt in seen:
                continue
            seen.add(nxt)
            queue.append(nxt)

    stranded = []
    for row in range(len(maze)):
        for col in range(width):
            if maze[row][col] in (".", "o") and (col, row) not in seen:
                stranded.append((col, row))
    if stranded:
        raise Failure("{0} pellets cannot be reached, first at {1}".format(
            len(stranded), stranded[0]))
    report.append("maze: {0}x{1}, all pellets reachable".format(
        width, len(maze)))


def rule_tick_does_not_draw(report, texts):
    """Logic in tick(), drawing in render().

    The shell runs the logic on a fixed step and draws every frame the display
    gives it. A game that draws inside tick() paints at the logic rate no matter
    what the render loop does, and the interpolation buys nothing - which looks
    exactly like the smoothing not working, with nothing to point at.

    Removing a shape as it is consumed is not drawing, so remove() and clear()
    are allowed through - and so is banner(), which puts up READY or LEVEL 2
    once on a state change rather than every frame.
    """
    drawing = ("self.s.rect(", "self.s.ellipse(", "self.s.wedge(",
               "self.s.label(", "self.s.move(", "self.s.alpha(",
               "self.s.lift(")
    for name, path in _sources(GAMES):
        if name == "__init__.py":
            continue
        text = _read(path)
        lines = text.splitlines()
        inside = False
        indent = 0
        for number, line in enumerate(lines, 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            here = len(line) - len(line.lstrip())
            if re.match(r"def\s+tick\s*\(", stripped):
                inside = True
                indent = here
                continue
            if inside and here <= indent and stripped.startswith("def "):
                inside = False
            if not inside:
                continue
            for call in drawing:
                if call in line:
                    raise Failure(
                        "{0}:{1} draws inside tick(); drawing belongs in "
                        "render()".format(name, number))
    report.append("tick() draws nothing")


def rule_scoreboard_survives_rubbish(report, texts):
    """A damaged score file costs one row, never the board.

    This file is plain text in AppData, so it will be hand-edited, and a machine
    shut down mid-write leaves a half line. Losing the whole scoreboard to
    either would be a poor trade, and there is nobody to report it to.
    """
    scores = _load_isolated("egg_scores_probe",
                            os.path.join(HERE, "egg_scores.py"))
    rubbish = [
        "",
        "   ",
        "# a comment",
        "pacman",
        "pacman|2026-01-01T00:00:00",
        "pacman|not a date|someone|abc",
        "pacman|2026-01-01T00:00:00|good|1500",
        "\x00\x01 binary",
        "pacman|2026-01-01T00:00:00|good|1500|extra|fields",
    ]
    scores._read_lines = lambda: rubbish
    rows = scores.load("pacman")
    if len(rows) != 3:
        raise Failure("expected 3 readable rows out of the rubbish, got "
                      "{0}".format(len(rows)))
    for row in rows:
        if not isinstance(row["score"], int):
            raise Failure("a score came back as {0}".format(type(row["score"])))
    if scores.pretty_when("not a date") is None:
        raise Failure("pretty_when returned None on a bad date")
    if scores._clean("a|b\nc") != "a b c":
        raise Failure("a separator in a name is not being stripped, so the "
                      "record could not be read back")
    report.append("scoreboard: rubbish lines dropped, not the file")


SIGN_OFF = "Now get back to work!"


DOCSTRING_DOUBLE = re.compile('"' * 3 + '(?:.|\\n)*?' + '"' * 3)
DOCSTRING_SINGLE = re.compile("'" * 3 + '(?:.|\\n)*?' + "'" * 3)


def rule_slow_clicks(report, texts):
    """Three SLOW clicks, and the hook must not be able to miss one.

    The house behaviour, written into every tool's documentation, is three slow
    clicks on the logo - gaps of roughly a quarter of a second to two seconds.
    Up to 1.4.0 the hook allowed 650ms for the *whole run*, which is a fast
    triple click: clicking the way the tools say to never reached three, and
    the egg simply never opened for anybody. Nothing failed and nothing was
    logged, so there was nothing to look at either.

    Three things are held here, because each of them alone was a reason it did
    not work:

    1. the timing is a gap between clicks, not one window for the run, and two
       seconds is inside it
    2. the handler is registered with handledEventsToo, or a header that
       handles the tunnelling click first means the logo never hears it
    3. the same click reaching two hooked elements is counted once
    """
    lookup = dict(texts)
    hook = lookup.get("egg_hook.py")
    if hook is None:
        raise Failure("egg_hook.py is not in the checked modules")

    settings = _load_isolated("egg_settings_clicks",
                              os.path.join(HERE, "egg_settings.py"))
    if "click_gap_max_ms" not in settings.DEFAULTS:
        raise Failure("no click_gap_max_ms: the hook is timing the whole run "
                      "rather than the gap between clicks, so slow clicks "
                      "never reach three")
    longest = _as_number(settings.DEFAULTS.get("click_gap_max_ms"))
    if longest < 2000:
        raise Failure("click_gap_max_ms is {0}ms; the tools tell people to "
                      "click slowly, which means at least 2000".format(longest))
    shortest = _as_number(settings.DEFAULTS.get("click_gap_min_ms"))
    if shortest > 300:
        raise Failure("click_gap_min_ms is {0}ms, which rejects a normal "
                      "deliberate click".format(shortest))

    # Against the code, not the comments. The first cut of this rule looked for
    # the word "Timestamp" anywhere in the file and was satisfied by the
    # docstring explaining why the timestamp matters, so deleting the actual
    # call still passed. A rule that prose can satisfy is not a rule.
    code = _code_only(hook)

    if "counter.delegate, True" not in code:
        raise Failure("the click handler is not registered with "
                      "handledEventsToo, so a header that handles the "
                      "tunnelling click first stops the logo ever hearing it")

    if "args.Timestamp" not in code or "self.stamp" not in code:
        raise Failure("nothing dedupes a click by timestamp, so one click "
                      "landing on two hooked elements counts twice")
    report.append("clicks: slow, heard past handled, counted once")


def _code_only(text):
    """The source with its docstrings and comments taken out.

    Anything that checks for the presence of code has to look at the code.
    Prose about a thing is not the thing.
    """
    stripped = DOCSTRING_DOUBLE.sub("", text)
    stripped = DOCSTRING_SINGLE.sub("", stripped)
    lines = []
    for line in stripped.splitlines():
        lines.append(line.split("#", 1)[0])
    return "\n".join(lines)


def _as_number(value):
    try:
        return int(str(value).strip())
    except Exception:
        return 0


def rule_board_sign_off(report, texts):
    """The scoreboard carries the sign-off, and shows fifteen rows.

    Both are the point of the feature rather than incidental styling, and both
    are the kind of thing a later rewrite of the panel drops without anybody
    noticing until it is in front of somebody.
    """
    lookup = dict(texts)
    shell = lookup.get("egg_shell.py")
    if shell is None:
        raise Failure("egg_shell.py is not in the checked modules")
    if SIGN_OFF not in shell:
        raise Failure("the scoreboard no longer says: {0}".format(SIGN_OFF))

    settings = _load_isolated("egg_settings_rows",
                              os.path.join(HERE, "egg_settings.py"))
    shown = settings.DEFAULTS.get("scores_shown")
    if str(shown) != "15":
        raise Failure("scores_shown defaults to {0}, not 15".format(shown))

    # A default that changed needs a migration, or every existing file keeps the
    # old value for ever - the whole set of keys is written back on every save,
    # so the old one is never missing and never falls through.
    reset = set()
    for version in settings.MIGRATIONS:
        for key in settings.MIGRATIONS[version]:
            reset.add(key)
    if "scores_shown" not in reset:
        raise Failure("scores_shown changed default with no migration, so an "
                      "existing settings file will keep the old one")
    report.append("scoreboard: 15 rows, migrated, and signs off properly")


RULES = [rule_compiles, rule_no_banned, rule_no_revit_refs, rule_clr_first,
         rule_version_is_present, rule_auto_attach_is_safe,
         rule_more_than_one_anchor, rule_ribbon_button,
         rule_runs_off_revits_thread,
         rule_nothing_claims_success_it_has_not_checked,
         rule_no_blocking_sleep_on_revits_thread,
         rule_portable_modules_have_no_dotnet,
         rule_desktop_matches_the_surface,
         rule_namespaces, rule_palettes_match, rule_settings_keys,
         rule_games_contract, rule_games_play, rule_tick_does_not_draw,
         rule_pacman_maze, rule_scoreboard_survives_rubbish,
         rule_board_sign_off, rule_slow_clicks]


# -- plumbing ============================================================

class _FakeSurface(object):
    """Enough of the surface to run a game headless."""

    def __init__(self):
        self.drawn = 0
        self.keys = {}

    def _note(self, key):
        self.drawn += 1
        self.keys[key] = True

    def rect(self, key, x, y, w, h, colour, radius=0):
        self._note(key)

    def ellipse(self, key, cx, cy, r, colour):
        self._note(key)

    def wedge(self, key, cx, cy, r, start, sweep, colour):
        self._note(key)

    def label(self, key, x, y, text, size=12, colour="text", bold=False):
        self._note(key)
        return None

    def banner(self, key, y, width, text, size=15, colour="orange",
               behind="bg"):
        self._note(key)
        return None

    def drop_banner(self, key):
        self.keys.pop(key, None)

    def alpha(self, key, value):
        pass

    def lift(self, key):
        pass

    def move(self, key, x, y):
        pass

    def move_centre(self, key, cx, cy):
        pass

    def fill(self, key, colour):
        pass

    def show(self, key, visible):
        pass

    def has(self, key):
        return key in self.keys

    def remove(self, key):
        self.keys.pop(key, None)

    def clear(self):
        self.keys = {}


def _install_stubs():
    """Stand in for the bits of the engine CPython does not have.

    Only egg_clr and clr are needed: the modules loaded here import nothing
    else out of .NET. The namespace rule is textual on purpose, so it does not
    depend on a stub being complete.
    """
    if "revobim.egg.egg_clr" in sys.modules:
        return
    clr_stub = types.ModuleType("clr")
    clr_stub.AddReference = lambda name: None
    sys.modules["clr"] = clr_stub

    package = types.ModuleType("revobim")
    package.__path__ = []
    egg = types.ModuleType("revobim.egg")
    egg.__path__ = []
    egg.__version__ = "0.0.0"
    inner = types.ModuleType("revobim.egg.egg_clr")
    inner.REFERENCED = []
    inner.MISSING = []
    egg.egg_clr = inner
    package.egg = egg
    sys.modules["revobim"] = package
    sys.modules["revobim.egg"] = egg
    sys.modules["revobim.egg.egg_clr"] = inner


def _load_isolated(name, path):
    """Import a module from a path without needing the package on sys.path."""
    _install_stubs()
    module = types.ModuleType(name)
    module.__file__ = path
    text = _read(path)
    exec(compile(text, path, "exec"), module.__dict__)
    return module


def run(sources=None):
    if sources is None:
        sources = [(name, _read(path))
                   for name, path in _sources(HERE, MODULES)]
    report = []
    for rule in RULES:
        rule(report, sources)
    return report


def _selftest():
    """Break each rule on purpose and confirm it is caught."""
    good = [(name, _read(path)) for name, path in _sources(HERE, MODULES)]
    lookup = dict(good)

    def swap(name, old, new):
        changed = []
        for entry_name, text in good:
            if entry_name == name:
                if old not in text:
                    raise Failure(
                        "selftest cannot break {0}: '{1}' is not in it".format(
                            name, old[:40]))
                text = text.replace(old, new, 1)
            changed.append((entry_name, text))
        return changed

    cases = [
        ("compiles",
         rule_compiles,
         swap("egg_hook.py", "def attach(", "def attach(:(")),
        ("f-string",
         rule_no_banned,
         swap("egg_hook.py", 'DEFAULT_CLICKS = 3',
              'DEFAULT_CLICKS = 3\nBAD = f"{DEFAULT_CLICKS}"')),
        ("WindowStyle.None",
         rule_no_banned,
         swap("egg_shell.py", 'getattr(WindowStyle, "None")',
              'WindowStyle.None')),
        ("RevitAPI reference",
         rule_no_revit_refs,
         swap("egg_clr.py", '"PresentationCore",',
              '"PresentationCore",\n              "RevitAPI",')),
        ("clr imported too late",
         rule_clr_first,
         swap("egg_surface.py",
              "from revobim.egg import egg_clr",
              "from System.Windows import Point as _Early\n"
              "from revobim.egg import egg_clr")),
        ("wrong namespace",
         rule_namespaces,
         swap("egg_shell.py",
              "from System.Windows.Controls import (Border, Canvas, "
              "ColumnDefinition, Grid,",
              "from System.Windows import Orientation\n"
              "from System.Windows.Controls import (Border, Canvas, "
              "ColumnDefinition, Grid,")),
        ("an unwrapped auto-attach handler",
         rule_auto_attach_is_safe,
         swap("egg_auto.py", "    except Exception:\n        # Never let this",
              "    except ValueError:\n        # Never let this")),
        ("the auto handler hooking a window twice",
         rule_auto_attach_is_safe,
         swap("egg_auto.py", "        _mark(window, DONE)", "        pass")),
        ("the auto handler walking every dialog",
         rule_auto_attach_is_safe,
         swap("egg_auto.py", "egg_hook.find_logo(window, deep=False)",
              "egg_hook.find_logo(window)")),
        ("a Sleep on Revit's STA thread",
         rule_no_blocking_sleep_on_revits_thread,
         swap("egg_shell.py", "Thread.CurrentThread.Join(int(milliseconds))",
              "Thread.Sleep(int(milliseconds))")),
        ("spawn sleeping on the caller's thread",
         rule_no_blocking_sleep_on_revits_thread,
         swap("egg_launcher.py", "def spawn(game_key=None, pause=None):",
              "def spawn(game_key=None):")),
        ("a spawn that does not check the process lived",
         rule_nothing_claims_success_it_has_not_checked,
         swap("egg_launcher.py", "if not _survives(",
              "if False and _survives(")),
        ("a threaded launch that does not wait for its window",
         rule_nothing_claims_success_it_has_not_checked,
         swap("egg_shell.py", "if not _window_appeared():", "if False:")),
        ("the game left on Revit's UI thread",
         rule_runs_off_revits_thread,
         swap("egg_shell.py", "                Dispatcher.Run()",
              "                pass")),
        ("a game thread that is not STA",
         rule_runs_off_revits_thread,
         swap("egg_shell.py", "thread.SetApartmentState(ApartmentState.STA)",
              "pass")),
        ("an emptied __init__.py",
         rule_version_is_present,
         swap("__init__.py", '__version__ = "', '# __version__ = "')),
        ("__init__.py with the version deleted",
         rule_version_is_present,
         swap("__init__.py", "__version__ =", "_wrong_name =")),
        ("a portable module reaching into .NET",
         rule_portable_modules_have_no_dotnet,
         swap("egg_scores.py", "import datetime",
              "import datetime\nfrom System.Windows import Window")),
        ("a portable module importing egg_clr",
         rule_portable_modules_have_no_dotnet,
         swap("egg_registry.py", "import os",
              "import os\nfrom revobim.egg import egg_clr")),
        ("the Tk surface missing a call",
         rule_desktop_matches_the_surface,
         swap("egg_desktop.py", "    def lift(self, key):",
              "    def lifted(self, key):")),
        ("a click window too short to click slowly",
         rule_slow_clicks,
         swap("egg_hook.py", "counter.delegate, True", "counter.delegate")),
        ("no dedupe on the click timestamp",
         rule_slow_clicks,
         swap("egg_hook.py", "int(args.Timestamp)", "0")),
        ("the sign-off going missing",
         rule_board_sign_off,
         swap("egg_shell.py", '"Now get back to work!"', '"Bye"')),
        ("settings key with no default",
         rule_settings_keys,
         swap("egg_shell.py", 'self.settings.get("game", "pacman")',
              'self.settings.get("nonesuch", "pacman")')),
    ]

    failures = []
    for label, rule, broken in cases:
        try:
            rule([], broken)
        except Failure:
            sys.stdout.write("  caught: {0}\n".format(label))
            continue
        except SyntaxError:
            sys.stdout.write("  caught: {0}\n".format(label))
            continue
        failures.append(label)
        sys.stdout.write("  MISSED: {0}\n".format(label))

    # The palette, contract, play and maze rules are broken against copies on
    # disk rather than in memory, since they load real files.
    for label, ok in _selftest_on_disk():
        if ok:
            sys.stdout.write("  caught: {0}\n".format(label))
        else:
            failures.append(label)
            sys.stdout.write("  MISSED: {0}\n".format(label))

    return failures


def _remove_anchors(copy_root):
    r"""Delete two of the three anchors and confirm the rule notices.

    The copy tree is `lib\revobim\egg`, so the extension root is three levels
    up from it - the same walk the rule itself does.
    """
    global HERE, GAMES
    was_here, was_games = HERE, GAMES
    root = os.path.abspath(os.path.join(copy_root, "..", "..", ".."))
    hooks = os.path.join(root, "hooks")
    moved = []
    try:
        for name in ("app-init.py", "doc-opened.py"):
            path = os.path.join(hooks, name)
            if os.path.isfile(path):
                moved.append((path, _read(path)))
                os.remove(path)
        HERE, GAMES = copy_root, os.path.join(copy_root, "games")
        try:
            rule_more_than_one_anchor([], [])
            return False
        except Failure:
            return True
        except Exception:
            return True
    finally:
        HERE, GAMES = was_here, was_games
        for path, text in moved:
            handle = open(path, "w")
            try:
                handle.write(text)
            finally:
                handle.close()


def _with_root(copy_root, work):
    """Run a rule against the copied tree rather than the real one."""
    global HERE, GAMES
    was_here, was_games = HERE, GAMES
    HERE, GAMES = copy_root, os.path.join(copy_root, "games")
    try:
        return work()
    finally:
        HERE, GAMES = was_here, was_games


def _ship_shared_bundle(copy_root):
    root = os.path.abspath(os.path.join(copy_root, "..", "..", ".."))
    path = os.path.join(root, "RevoBIM PY.tab", "Coordination.panel",
                        "Routines.pulldown", "bundle.yaml")
    folder = os.path.dirname(path)
    if not os.path.isdir(folder):
        os.makedirs(folder)
    handle = open(path, "w")
    try:
        handle.write("title: Routines\n")
    finally:
        handle.close()

    def check():
        try:
            rule_ribbon_button([], [])
            return False
        except Failure:
            return True
        except Exception:
            return True
    caught = _with_root(copy_root, check)
    os.remove(path)
    return caught


def _rename_button_title(copy_root):
    root = os.path.abspath(os.path.join(copy_root, "..", "..", ".."))
    path = os.path.join(root, *BUTTON) + os.sep + "bundle.yaml"
    text = _read(path)
    handle = open(path, "w")
    try:
        handle.write(text.replace("title: RevoBIM Arcade", "title: Arcade"))
    finally:
        handle.close()

    def check():
        try:
            rule_ribbon_button([], [])
            return False
        except Failure:
            return True
        except Exception:
            return True
    caught = _with_root(copy_root, check)
    handle = open(path, "w")
    try:
        handle.write(text)
    finally:
        handle.close()
    return caught


def _selftest_on_disk():
    import shutil
    import tempfile
    results = []
    scratch = tempfile.mkdtemp()
    try:
        # The anchor rule looks three levels above the egg folder, so the copy
        # has to keep that shape rather than being a bare folder.
        copy = os.path.join(scratch, "ext", "lib", "revobim", "egg")
        shutil.copytree(HERE, copy)
        root = os.path.abspath(os.path.join(copy, "..", "..", ".."))
        real_root = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
        os.makedirs(os.path.join(root, "hooks"))
        for name in ("startup.py",):
            shutil.copy(os.path.join(real_root, name), os.path.join(root, name))
        for name in ("app-init.py", "doc-opened.py"):
            source = os.path.join(real_root, "hooks", name)
            if os.path.isfile(source):
                shutil.copy(source, os.path.join(root, "hooks", name))
        # The ribbon rule reads the button out of the tree too.
        button_src = os.path.join(real_root, *BUTTON)
        if os.path.isdir(button_src):
            shutil.copytree(button_src, os.path.join(root, *BUTTON))

        def with_edit(path, old, new, rule_name, from_root=False):
            global HERE, GAMES
            was_here, was_games = HERE, GAMES
            base = os.path.abspath(os.path.join(copy, "..", "..", "..")) \
                if from_root else copy
            target = os.path.join(base, path)
            text = _read(target)
            handle = open(target, "w")
            try:
                handle.write(text.replace(old, new, 1))
            finally:
                handle.close()
            HERE, GAMES = copy, os.path.join(copy, "games")
            try:
                globals()[rule_name]([], [])
                caught = False
            except Failure:
                caught = True
            except Exception:
                caught = True
            finally:
                HERE, GAMES = was_here, was_games
                handle = open(target, "w")
                try:
                    handle.write(text)
                finally:
                    handle.close()
            return caught

        results.append(("palette key missing from light",
                        with_edit("egg_theme.py", '    "pupil": "#1E1E20",\n',
                                  "", "rule_palettes_match")))
        results.append(("game missing a method",
                        with_edit("games/snake.py", "    def stop(self):",
                                  "    def stopped(self):",
                                  "rule_games_contract")))
        results.append(("game importing WPF",
                        with_edit("games/snake.py", "import random",
                                  "import random\nfrom System.Windows import "
                                  "Point", "rule_games_contract")))
        results.append(("maze with a stranded pellet",
                        with_edit("games/pacman.py",
                                  '    "#.####.#####.####.#",',
                                  '    "###################",',
                                  "rule_pacman_maze")))
        results.append(("a gap too short to click slowly",
                        with_edit("egg_settings.py",
                                  '"click_gap_max_ms": "2000",',
                                  '"click_gap_max_ms": "650",',
                                  "rule_slow_clicks")))
        results.append(("timing the whole run instead of the gap",
                        with_edit("egg_settings.py",
                                  '"click_gap_max_ms": "2000",',
                                  '"click_window_ms": "650",',
                                  "rule_slow_clicks")))
        results.append(("a button without __persistentengine__",
                        with_edit(os.path.join(*BUTTON) + os.sep + "script.py",
                                  "__persistentengine__ = True",
                                  "# engine not kept",
                                  "rule_nothing_claims_success_it_has_not_checked",
                                  from_root=True)))
        results.append(("a shipped Routines.pulldown bundle.yaml",
                        _ship_shared_bundle(copy)))
        results.append(("a button folder and title disagreeing",
                        _rename_button_title(copy)))
        results.append(("only one anchor left",
                        _remove_anchors(copy)))
        results.append(("run_mode not defaulting to auto",
                        with_edit("egg_settings.py", '"run_mode": "auto",',
                                  '"run_mode": "inline",',
                                  "rule_runs_off_revits_thread")))
        results.append(("a changed default with no migration",
                        with_edit("egg_settings.py",
                                  "    2: (\"scores_shown\",),",
                                  "",
                                  "rule_board_sign_off")))
        results.append(("scoreboard losing a good row",
                        with_edit("egg_scores.py",
                                  "        if len(parts) < FIELDS:",
                                  "        if len(parts) != FIELDS:",
                                  "rule_scoreboard_survives_rubbish")))
        results.append(("name separator not stripped",
                        with_edit("egg_scores.py",
                                  '    for bad in (SEPARATOR, "\\r", "\\n", "\\t"):',
                                  '    for bad in ("\\r", "\\n", "\\t"):',
                                  "rule_scoreboard_survives_rubbish")))
        results.append(("drawing inside tick",
                        with_edit("games/snake.py",
                                  "        self.body.insert(0, nxt)",
                                  "        self.s.rect('x', 0, 0, 1, 1, 'bg')",
                                  "rule_tick_does_not_draw")))
        results.append(("game that throws in tick",
                        with_edit("games/snake.py", "        self.dir "
                                  "= self.want",
                                  "        raise ValueError('bench')",
                                  "rule_games_play")))
    finally:
        try:
            shutil.rmtree(scratch)
        except Exception:
            pass
    return results


def main():
    if "--selftest" in sys.argv:
        sys.stdout.write("selftest - breaking each rule on purpose\n")
        missed = _selftest()
        if missed:
            sys.stdout.write("\n{0} rule(s) did not catch their own "
                             "breakage\n".format(len(missed)))
            return 1
        sys.stdout.write("\nevery rule caught its own breakage\n")
        return 0

    try:
        for line in run():
            sys.stdout.write("  ok  {0}\n".format(line))
    except Failure:
        sys.stdout.write("FAIL  {0}\n".format(sys.exc_info()[1]))
        return 1
    sys.stdout.write("\nall checks passed\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
