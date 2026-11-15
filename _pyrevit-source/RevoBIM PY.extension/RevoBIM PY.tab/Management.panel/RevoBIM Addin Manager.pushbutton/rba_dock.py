# -*- coding: utf-8 -*-
u"""RevoBIM Addin Manager - registering the dockable pane, and saying why not.

Three hard facts shape this module, and each has cost this extension a release:

**Revit only sets a dockable pane up while it is building its user interface.**
`RegisterDockablePane` called any later - from a ribbon command, say - is
accepted, raises nothing, and the pane is never created; `GetDockablePane`
throws for the rest of the session. So registration happens from the
extension's `startup.py` and nowhere else. The button never tries.

**The host object is asked, not assumed.** Which object pyRevit hands
`startup.py`, and under which name, depends on the pyRevit build: recent ones
put a `UIApplication` in `__revit__`, older ones a `UIControlledApplication`,
and some expose `__uiControlledApplication__` while others do not define it at
all. 1.2.0 to 1.3.0 named one of them directly; where that name was undefined
the line raised `NameError`, the wrapper in `startup.py` swallowed it, and the
pane silently never existed. `register(*candidates)` now takes everything the
fragment can find and uses the first that actually has the method.

**Engines do not share modules.** The pane lives in the startup engine; the
button runs in its own. A module level flag set in one is invisible in the
other, and is reset by a pyRevit reload while Revit still holds the old pane.
So the registered state lives in the AppDomain, and Revit itself is asked
(`DockablePane.PaneIsRegistered`) as the final word.

Every attempt writes `%APPDATA%\\RevoBIM\\revobim_addins_startup.txt`, naming
each candidate offered, which one registered, and what went wrong. It carries
the Revit process id, so the button can tell "the startup block never ran this
session" from "it ran and Revit refused", and say which in the footer instead
of a generic "paste the fragment".
"""

import rba_clr  # noqa: F401

import os
import time
import traceback

from System import AppDomain, Guid
from System.Diagnostics import Process
from System.Windows.Media import FontFamily
from System.Windows import (HorizontalAlignment, VerticalAlignment, Thickness,
                            TextWrapping, FontWeights)
from System.Windows.Controls import (Border, TextBlock, TextBox, StackPanel,
                                     Button, ScrollViewer, ScrollBarVisibility)

from Autodesk.Revit.UI import (IDockablePaneProvider, DockablePaneState,
                               DockablePaneId, DockPosition, DockablePane)

import rba_core
import rba_theme

from rba_core import to_text, log, log_exception

# This module's own folder, captured while it is being imported at start up -
# the only moment the tool folder is certain to be on sys.path.
#
# pyRevit resets the start up engine's sys.path once startup.py has run. The
# docked panel is built later, when the pane is first shown, by which time the
# folder the startup block added has gone again: 1.4.1 died there with
# "ImportError: No module named rba_pane". So the folder is remembered here and
# put back just before the panel is built.
TOOL_DIR = os.path.dirname(os.path.abspath(__file__))


def ensure_tool_path():
    import sys
    if TOOL_DIR not in sys.path:
        sys.path.insert(0, TOOL_DIR)

GUARD_KEY = u"RevoBIM.AddinManager.pane"
# The version the docked pane was built from. A docked pane runs the code
# Revit loaded at start up: unzipping an update or reloading pyRevit does not
# replace it, only a Revit restart does. The button compares this with the
# installed version and says so, instead of an update seeming not to work.
VERSION_KEY = u"RevoBIM.AddinManager.pane_version"
PANE_ERROR = u"revobim_addins_pane_error.txt"
STARTUP_LOG = u"revobim_addins_startup.txt"

# Parked at module level so the provider and the pane outlive the call that
# registered them; the persistent engine collects them otherwise and Revit is
# left holding a dead FrameworkElement.
PROVIDER = [None]
PANE = [None]


def pane_id():
    return DockablePaneId(Guid(rba_core.PANE_GUID))


def process_id():
    try:
        return Process.GetCurrentProcess().Id
    except Exception:
        return -1


# ----------------------------------------------------------------------
# the startup log
# ----------------------------------------------------------------------

def startup_log_path():
    return os.path.join(rba_core.appdata_root(), STARTUP_LOG)


def _write_startup_log(lines):
    try:
        rba_core.ensure_root()
        handle = open(startup_log_path(), u"wb")
        try:
            handle.write(u"\n".join([to_text(line) for line in lines]).encode(u"utf-8"))
        finally:
            handle.close()
    except Exception:
        pass


def read_startup_log():
    u"""(pid, outcome, text) from the last attempt, or (None, u"", u"")."""
    path = startup_log_path()
    if not os.path.isfile(path):
        return None, u"", u""
    try:
        handle = open(path, u"rb")
        try:
            text = handle.read().decode(u"utf-8", u"replace")
        finally:
            handle.close()
    except Exception:
        return None, u"", u""
    pid = None
    outcome = u""
    for line in text.splitlines():
        if line.startswith(u"pid="):
            try:
                pid = int(line.split(u"=", 1)[1].strip())
            except Exception:
                pid = None
        elif line.startswith(u"outcome="):
            outcome = line.split(u"=", 1)[1].strip()
    return pid, outcome, text


# ----------------------------------------------------------------------
# the AppDomain guard
# ----------------------------------------------------------------------

def guard_value():
    try:
        return to_text(AppDomain.CurrentDomain.GetData(GUARD_KEY) or u"")
    except Exception:
        return u""


def _set_guard(value):
    try:
        AppDomain.CurrentDomain.SetData(GUARD_KEY, to_text(value))
    except Exception:
        pass


def pane_registered():
    u"""True when Revit holds this pane, whichever engine registered it."""
    try:
        if DockablePane.PaneIsRegistered(pane_id()):
            return True
    except Exception:
        log_exception(u"dock/PaneIsRegistered")
    return guard_value() == u"registered"


# ----------------------------------------------------------------------
# the provider - lazy
# ----------------------------------------------------------------------

class PaneProvider(IDockablePaneProvider):
    u"""Hands Revit a host Border and builds the panel inside it on first show.

    **The host is never left black.** 1.4.0 handed Revit an empty Border with
    no background - which Revit draws black - built the panel only on that
    Border's Loaded event, and on a failure showed a TextBlock with the default
    black text: black on black. Whether the panel was never built or built and
    failed, the pane looked the same and said nothing. Now:

    * the host is painted with the palette at once, and says "Starting..." in
      the palette's text colour, so an empty pane is never the visible state;
    * the build is tried on Loaded, on IsVisibleChanged and once more from the
      dispatcher - whichever comes first - so a dock host that never raises
      one of them cannot strand it;
    * a failure is shown in the pane, readable and copyable, and written to
      %APPDATA%\\RevoBIM\\revobim_addins_pane_error.txt.
    """

    def __init__(self, dock):
        self.dock = dock
        self.built = False
        self.colours = _palette()
        self.host = Border()
        self.host.Background = _brush(self.colours[u"BgWindow"])
        self.host.Child = _message(self.colours, u"RevoBIM Addin Manager",
                                   u"Starting...")
        self.host.Loaded += self._on_loaded
        self.host.IsVisibleChanged += self._on_visible

    def SetupDockablePane(self, data):
        data.FrameworkElement = self.host
        state = DockablePaneState()
        wanted = to_text(self.dock).strip().lower()
        if wanted == u"right":
            state.DockPosition = DockPosition.Right
        elif wanted in (u"floating", u"float"):
            state.DockPosition = DockPosition.Floating
            # Without one the floating rectangle defaults to empty, and the
            # first show can be zero sized or off screen.
            try:
                from Autodesk.Revit.DB import Rectangle
                state.FloatingRectangle = Rectangle(120, 120, 520, 1000)
            except Exception:
                pass
        else:
            state.DockPosition = DockPosition.Left
        data.InitialState = state
        try:
            data.VisibleByDefault = False
        except Exception:
            pass

    def _on_loaded(self, sender, args):
        log(u"pane host: Loaded")
        self._build()

    def _on_visible(self, sender, args):
        try:
            shown = bool(args.NewValue)
        except Exception:
            shown = True
        log(u"pane host: visible={0}".format(shown))
        if shown:
            self._build()
            # A third route, in case neither event reaches a built panel:
            # once the dispatcher is idle, try again (a no-op once built).
            try:
                from System import Action
                from System.Windows.Threading import DispatcherPriority
                self.host.Dispatcher.BeginInvoke(DispatcherPriority.Background,
                                                 Action(self._build))
            except Exception:
                pass

    def _build(self):
        if self.built:
            return
        self.built = True
        try:
            ensure_tool_path()
            import rba_pane
            pane = rba_pane.AddinsPane(mode=u"pane")
            PANE[0] = pane
            self.host.Child = pane.control
            pane.first_read_done = True
            pane.rescan()
            _clear_pane_error()
            log(u"pane built on first show")
        except Exception:
            detail = traceback.format_exc()
            log(u"dock/build failed: " + detail)
            _write_pane_error(detail)
            self.host.Child = _message(
                self.colours, u"RevoBIM Addin Manager could not build its panel",
                u"Copy this and send it over. It is also saved to\n"
                u"%APPDATA%\\RevoBIM\\" + PANE_ERROR, detail)


def _palette():
    u"""The palette the settings ask for, resolved now; dark if anything fails."""
    try:
        settings = rba_core.load_settings()
        return rba_theme.palette(rba_theme.resolve(settings.get(u"theme", u"auto")))
    except Exception:
        return {u"BgWindow": u"#3B4453", u"BgField": u"#2C3440",
                u"FgText": u"#F5F5F5", u"FgMuted": u"#9DA5B0",
                u"AccBlue": u"#4FA3E3", u"BrdEdge": u"#515C6B"}


def _brush(hex_value):
    from System.Windows.Media import BrushConverter
    return BrushConverter().ConvertFromString(hex_value)


def _message(colours, title, body, detail=None):
    u"""A readable panel of text: palette colours set explicitly, never defaults."""
    stack = StackPanel()
    stack.Margin = Thickness(14)

    heading = TextBlock()
    heading.Text = title
    heading.Foreground = _brush(colours.get(u"AccBlue", u"#4FA3E3"))
    heading.FontWeight = FontWeights.SemiBold
    heading.FontSize = 14
    heading.TextWrapping = TextWrapping.Wrap
    stack.Children.Add(heading)

    note = TextBlock()
    note.Text = body
    note.Foreground = _brush(colours.get(u"FgText", u"#F5F5F5"))
    note.FontSize = 12
    note.Margin = Thickness(0, 6, 0, 8)
    note.TextWrapping = TextWrapping.Wrap
    stack.Children.Add(note)

    if detail:
        box = TextBox()
        box.Text = detail
        box.IsReadOnly = True
        box.TextWrapping = TextWrapping.Wrap
        box.FontFamily = FontFamily(u"Consolas")
        box.FontSize = 11
        box.Foreground = _brush(colours.get(u"FgText", u"#F5F5F5"))
        box.Background = _brush(colours.get(u"BgField", u"#2C3440"))
        box.BorderBrush = _brush(colours.get(u"BrdEdge", u"#515C6B"))
        box.MaxHeight = 420
        box.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
        stack.Children.Add(box)

        copy = Button()
        copy.Content = u"Copy details"
        copy.Margin = Thickness(0, 8, 0, 0)
        copy.HorizontalAlignment = HorizontalAlignment.Left
        copy.Padding = Thickness(10, 3, 10, 3)

        def on_copy(sender, args, text=detail):
            try:
                from System.Windows import Clipboard
                Clipboard.SetText(text)
                sender.Content = u"Copied"
            except Exception:
                pass

        copy.Click += on_copy
        stack.Children.Add(copy)

    scroller = ScrollViewer()
    scroller.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
    scroller.Content = stack
    scroller.VerticalAlignment = VerticalAlignment.Stretch
    return scroller


def _pane_error_path():
    return os.path.join(rba_core.appdata_root(), PANE_ERROR)


def _write_pane_error(text):
    try:
        rba_core.ensure_root()
        handle = open(_pane_error_path(), u"wb")
        try:
            handle.write(to_text(text).encode(u"utf-8"))
        finally:
            handle.close()
    except Exception:
        pass


def _clear_pane_error():
    try:
        if os.path.isfile(_pane_error_path()):
            os.remove(_pane_error_path())
    except Exception:
        pass


def pane_version():
    try:
        return to_text(AppDomain.CurrentDomain.GetData(VERSION_KEY) or u"")
    except Exception:
        return u""


def _set_pane_version():
    try:
        AppDomain.CurrentDomain.SetData(VERSION_KEY, rba_core.__version__)
    except Exception:
        pass


# ----------------------------------------------------------------------
# registration
# ----------------------------------------------------------------------

def _can_register(candidate):
    try:
        return callable(getattr(candidate, u"RegisterDockablePane", None))
    except Exception:
        return False


def _describe(candidate):
    if candidate is None:
        return u"not defined"
    try:
        return to_text(candidate.GetType().FullName)
    except Exception:
        return to_text(type(candidate).__name__)


def register(*named_candidates):
    u"""Register the pane on whichever candidate can take it.

    Each argument is either a host object or a (name, object) pair, so the log
    can say which name the working host came from. Returns True when Revit
    holds the pane afterwards. Safe to call any number of times.
    """
    lines = [u"RevoBIM Addin Manager - dockable pane registration",
             u"time={0}".format(time.strftime(u"%Y-%m-%d %H:%M:%S")),
             u"pid={0}".format(process_id()),
             u"version={0}".format(rba_core.__version__)]

    pairs = []
    for index, entry in enumerate(named_candidates):
        if isinstance(entry, tuple) and len(entry) == 2:
            pairs.append((to_text(entry[0]), entry[1]))
        else:
            pairs.append((u"candidate {0}".format(index + 1), entry))
    for name, candidate in pairs:
        lines.append(u"offered {0}: {1}, RegisterDockablePane={2}".format(
            name, _describe(candidate), u"yes" if _can_register(candidate) else u"no"))

    try:
        if DockablePane.PaneIsRegistered(pane_id()):
            _set_guard(u"registered")
            lines.append(u"outcome=already-registered")
            _write_startup_log(lines)
            return True
    except Exception:
        lines.append(u"PaneIsRegistered raised: {0}".format(
            traceback.format_exc().replace(u"\n", u" | ")))

    settings = rba_core.load_settings()
    rba_core.set_debug(rba_core.as_bool(settings, u"debug"))
    dock = settings.get(u"dock", u"left")

    for name, candidate in pairs:
        if not _can_register(candidate):
            continue
        try:
            provider = PaneProvider(dock)
            candidate.RegisterDockablePane(pane_id(), rba_core.TOOL_NAME, provider)
            PROVIDER[0] = provider
            _set_guard(u"registered")
            _set_pane_version()
            lines.append(u"registered on {0}, docking {1}".format(name, dock))
            lines.append(u"outcome=registered")
            _write_startup_log(lines)
            log(u"pane registered on {0}".format(name))
            return True
        except Exception:
            lines.append(u"{0} refused: {1}".format(
                name, traceback.format_exc().replace(u"\n", u" | ")))

    # No candidate could take it directly. Where one carries the controlled
    # application, register from ApplicationInitialized instead - still inside
    # start up, which is all Revit asks. Hooked with += only: IronPython does
    # not reliably find the same handler again to detach, and the guard makes
    # a second pass a no-op.
    for name, candidate in pairs:
        controlled = None
        try:
            controlled = getattr(candidate, u"ControlledApplication", None)
        except Exception:
            controlled = None
        if controlled is None:
            continue
        try:
            def on_initialised(sender, args, _dock=dock, _name=name):
                if guard_value() == u"registered":
                    return
                late = list(lines)
                try:
                    from Autodesk.Revit.UI import UIApplication
                    uiapp = UIApplication(sender)
                    provider = PaneProvider(_dock)
                    uiapp.RegisterDockablePane(pane_id(), rba_core.TOOL_NAME, provider)
                    PROVIDER[0] = provider
                    _set_guard(u"registered")
                    _set_pane_version()
                    late.append(u"registered on ApplicationInitialized via {0}".format(_name))
                    late.append(u"outcome=registered")
                except Exception:
                    late.append(u"ApplicationInitialized route refused: {0}".format(
                        traceback.format_exc().replace(u"\n", u" | ")))
                    late.append(u"outcome=refused")
                _write_startup_log(late)

            controlled.ApplicationInitialized += on_initialised
            lines.append(u"deferred to ApplicationInitialized via {0}".format(name))
            lines.append(u"outcome=deferred")
            _write_startup_log(lines)
            return False
        except Exception:
            lines.append(u"could not hook ApplicationInitialized on {0}: {1}".format(
                name, traceback.format_exc().replace(u"\n", u" | ")))

    lines.append(u"outcome=no-host")
    _write_startup_log(lines)
    return False


# ----------------------------------------------------------------------
# what the button tells the user
# ----------------------------------------------------------------------

def docking_status():
    u"""(code, short, detail) for the floating window's footer and log.

    The cases a user can act on are named: the startup block never ran in this
    Revit session (not pasted, or Revit not restarted since), it ran and found
    no host it could use, or it ran and Revit refused.
    """
    pid, outcome, text = read_startup_log()
    if pid is None or pid != process_id():
        return (u"not-run",
                u"Floating - restart Revit to dock",
                u"The startup block did not run in this Revit session. Check "
                u"it is in RevoBIM PY.extension\\startup.py, then restart Revit "
                u"(a pyRevit reload is not enough).")
    if outcome in (u"registered", u"already-registered"):
        return (u"registered-not-shown",
                u"Floating - Revit would not show the pane",
                u"The pane registered at start up but Revit would not hand it "
                u"back. See {0}".format(startup_log_path()))
    if outcome == u"deferred":
        return (u"deferred",
                u"Floating - pane registration pending",
                u"Registration was deferred to ApplicationInitialized and has "
                u"not completed. See {0}".format(startup_log_path()))
    return (u"refused",
            u"Floating - see the startup log",
            u"The startup block ran but could not register the pane ({0}). "
            u"See {1}".format(outcome or u"unknown", startup_log_path()))
