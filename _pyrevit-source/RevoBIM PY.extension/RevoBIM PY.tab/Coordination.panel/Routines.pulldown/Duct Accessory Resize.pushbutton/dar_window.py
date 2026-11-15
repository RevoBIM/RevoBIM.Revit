# -*- coding: utf-8 -*-
"""Duct Accessory Resize - the modeless window.

Revit stays fully usable while it is open. Every read and write of the
model goes out through one ExternalEvent and comes back on the window's
dispatcher; nothing here ever waits for the event.
"""

import dar_clr  # noqa: F401 - assemblies first, always

import time
import traceback

from System import Action, AppDomain, TimeSpan
from System.Windows import (Thickness, GridLength, GridUnitType, Visibility,
                            TextTrimming, Clipboard, VerticalAlignment,
                            FontWeights)
from System.Windows.Controls import Grid, ColumnDefinition, Border, TextBlock
from System.Windows.Input import Key, Keyboard, ModifierKeys
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Threading import DispatcherTimer
from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent

import dar_core as core
import dar_drawer as drawer
import dar_revit as rv
import dar_ui as ui

APPDOMAIN_KEY = u"RevoBIM.DuctAccessoryResize.window." + core.__version__
WATCHDOG_S = 20.0
_LIVE = []
_DIALOG = {u"hooked": False, u"active": False, u"log": None}

COLUMNS = (
    # key, heading, star width, minimum pixels
    (u"id", u"Element", 0.8, 70),
    (u"cat", u"Category", 1.0, 92),
    (u"ft", u"Family : Type", 2.4, 160),
    (u"src", u"Size from", 0.8, 70),
    (u"cur", u"Current", 1.0, 88),
    (u"new", u"New", 1.0, 88),
    (u"note", u"Status", 2.2, 150),
)

# one set of controls per family kind, since an air terminal rarely names
# its sizes the way a damper does
COMBO = {
    core.KIND_ACC: {u"w": u"AccWidthCombo", u"h": u"AccHeightCombo",
                    u"d": u"AccDiameterCombo"},
    core.KIND_TERM: {u"w": u"TermWidthCombo", u"h": u"TermHeightCombo",
                     u"d": u"TermDiameterCombo"},
}
SEARCH = {
    core.KIND_ACC: {u"w": u"AccWidthSearch", u"h": u"AccHeightSearch",
                    u"d": u"AccDiameterSearch"},
    core.KIND_TERM: {u"w": u"TermWidthSearch", u"h": u"TermHeightSearch",
                     u"d": u"TermDiameterSearch"},
}
PARAM_BLOCK = {
    core.KIND_ACC: {u"w": u"AccWidthBlock", u"h": u"AccHeightBlock",
                    u"d": u"AccDiameterBlock"},
    core.KIND_TERM: {u"w": u"TermWidthBlock", u"h": u"TermHeightBlock",
                     u"d": u"TermDiameterBlock"},
}
PARAM_HINT = {core.KIND_ACC: u"AccParamHint", core.KIND_TERM: u"TermParamHint"}
PARAM_WARNING = {core.KIND_ACC: u"AccParamWarning",
                 core.KIND_TERM: u"TermParamWarning"}
ALL_DIMS = (u"w", u"h", u"d")
NEW_BOX = {u"w": u"NewWidth", u"h": u"NewHeight", u"d": u"NewDiameter"}
NEW_BLOCK = {u"w": u"NewWidthBlock", u"h": u"NewHeightBlock",
             u"d": u"NewDiameterBlock"}
ACTION_BUTTONS = (u"SelectButton", u"UseSelectionButton", u"ClearButton",
                  u"RefreshParamsButton")


# ============================================================
# the ExternalEvent runner
# ============================================================

class Job(object):
    def __init__(self, name, fn, callback):
        self.name = name
        self.fn = fn
        self.callback = callback
        self.started = False
        self.raised = time.time()


class Runner(IExternalEventHandler):
    """Drains the queue each time Revit calls it, and hands each result
    back to the window's dispatcher."""

    def __init__(self):
        self.jobs = []
        self.dispatch = None

    def Execute(self, uiapp):
        while self.jobs:
            job = self.jobs.pop(0)
            job.started = True
            value, error = None, None
            try:
                value = job.fn(uiapp)
            except Exception:
                error = traceback.format_exc()
            self._hand_back(job, value, error)

    def _hand_back(self, job, value, error):
        def done():
            job.callback(value, error)
        try:
            self.dispatch(done)
        except Exception:
            done()

    def GetName(self):
        return u"RevoBIM Duct Accessory Resize"


def _on_dialog(sender, args):
    """Hooked once, switched with a flag: unsubscribing an IronPython bound
    method from a .NET event is not reliable."""
    if not _DIALOG[u"active"]:
        return
    dialog_id = u"?"
    try:
        dialog_id = core.to_text(args.DialogId)
    except Exception:
        pass
    try:
        args.OverrideResult(1)
        answered = u"answered OK"
    except Exception:
        answered = u"could not be answered"
    log = _DIALOG[u"log"]
    if log is not None:
        log.add(u"Revit dialog suppressed: {0} ({1})", dialog_id, answered)


# ============================================================
# the window
# ============================================================

class ResizeWindow(object):

    def __init__(self, uiapp):
        self.uiapp = uiapp
        self.settings = core.load_settings()
        self.log = core.DebugLog(core.flag(self.settings, u"debug"))
        self.rows = []
        self.params = {}
        self.new = {}
        self.input_errors = {}
        self.clash = u""
        self.busy = False
        self.current_job = None
        self.filling = False
        self.resolved = u"dark"
        self.canvas_dark = rv.canvas_is_dark(uiapp)

        self.log.section(u"{0} v{1}".format(core.TOOL_NAME, core.__version__))
        for line in rv.environment(uiapp):
            self.log.add(line)
        self.log.add(u"canvas dark: {0} | engine assemblies: {1}",
                     self.canvas_dark, u", ".join(dar_clr.LOADED))

        self.runner = Runner()
        self.runner.dispatch = self._dispatch
        self.event = ExternalEvent.Create(self.runner)

        self.window = ui.load_window()
        self.full = ui.FullScreen(self.window)
        self.apply_theme()
        self.ctl(u"VersionText").Text = u"v" + core.__version__
        ui.load_icon(self.ctl(u"LogoImage"))
        ui.add_grips(self.window, self.ctl(u"GripLayer"), self.full)
        self.drawer = drawer.Drawer(self.window, self.ctl(u"HeaderBar"),
                                    self.ctl(u"RootBorder"),
                                    self.ctl(u"ShrinkButton"),
                                    self.ctl(u"GripLayer"), self.log)
        egg = ui.attach_egg(self.window, self.ctl(u"LogoHost"),
                            self.get_palette, self.log)
        self.log.add(u"easter egg attached: {0}", egg)

        self._build_header()
        self._restore_controls()
        self._wire()
        self._hook_dialogs()

        self.watchdog = DispatcherTimer()
        self.watchdog.Interval = TimeSpan.FromSeconds(1)
        self.watchdog.Tick += self.guard(self.on_watchdog)
        self.watchdog.Start()

        # the command itself has an API context, so the first read of the
        # model can happen here rather than through the event
        self.load_params(uiapp.ActiveUIDocument.Document)
        ids, dropped = rv.selected_ids(uiapp)
        if ids:
            self.rows, skipped = rv.read_rows(uiapp.ActiveUIDocument.Document,
                                              ids, self.settings, self.log)
            self.set_status(u"Picked up {0} elements already selected in "
                            u"Revit".format(len(self.rows)))
        self.recompute()

    # ---------------------------------------------------------- helpers

    def ctl(self, name):
        return self.window.FindName(name)

    def guard(self, fn):
        """Every handler reports rather than failing silently - a silent
        handler is indistinguishable from a dead button."""
        def handler(sender, args):
            try:
                fn(sender, args)
            except Exception:
                self.log.add(u"handler {0} failed: {1}", fn.__name__,
                             traceback.format_exc())
                self.log.write()
                self.set_status(u"Something went wrong - tick Debug and "
                                u"press Copy debug", u"Red")
        return handler

    def _dispatch(self, fn):
        def run():
            try:
                fn()
            except Exception:
                self.log.add(u"callback failed: {0}", traceback.format_exc())
                self.set_busy(False)
                self.set_status(u"Something went wrong - tick Debug and "
                                u"press Copy debug", u"Red")
        self.window.Dispatcher.BeginInvoke(Action(run))

    def set_status(self, text, colour=u"Muted"):
        status = self.ctl(u"StatusText")
        status.Text = text
        status.SetResourceReference(TextBlock.ForegroundProperty,
                                    colour + u"Brush")

    def shape(self):
        value = self.settings.get(u"shape", core.SHAPE_RECT)
        return value if value in core.DIMS else core.SHAPE_RECT

    def save(self):
        core.save_settings(self.settings)

    def get_palette(self):
        return dict(core.PALETTES.get(self.resolved, core.PALETTES[u"dark"]))

    # ---------------------------------------------------------- theme

    def apply_theme(self):
        mode = self.settings.get(u"theme", u"auto")
        self.resolved = core.resolve_theme(mode, self.canvas_dark)
        ui.apply_palette(self.window, self.resolved)
        chip = self.ctl(u"ThemeChipText")
        if chip is not None:
            chip.Text = core.theme_chip_text(mode, self.resolved)

    def on_theme_chip(self, sender, args):
        self.settings[u"theme"] = core.next_theme(self.settings.get(u"theme"))
        self.save()
        self.canvas_dark = rv.canvas_is_dark(self.uiapp)
        self.apply_theme()
        self.render_rows()

    def on_activated(self, sender, args):
        if self.settings.get(u"theme") != u"auto":
            return
        dark = rv.canvas_is_dark(self.uiapp)
        if dark != self.canvas_dark:
            self.canvas_dark = dark
            self.apply_theme()
            self.render_rows()

    # ---------------------------------------------------------- building

    def _columns(self, grid):
        for key, heading, star, minimum in COLUMNS:
            column = ColumnDefinition()
            column.Width = GridLength(star, GridUnitType.Star)
            column.MinWidth = minimum
            grid.ColumnDefinitions.Add(column)

    def _cell(self, grid, index, text, colour, bold=False):
        block = TextBlock()
        block.Text = text
        block.Margin = Thickness(10, 0, 6, 0)
        block.VerticalAlignment = VerticalAlignment.Center
        block.TextTrimming = TextTrimming.CharacterEllipsis
        if bold:
            block.FontWeight = FontWeights.SemiBold
        block.SetResourceReference(TextBlock.ForegroundProperty,
                                   colour + u"Brush")
        Grid.SetColumn(block, index)
        grid.Children.Add(block)
        return block

    def _build_header(self):
        header = self.ctl(u"TableHeader")
        self._columns(header)
        for index, column in enumerate(COLUMNS):
            self._cell(header, index, column[1], u"Muted", bold=True)

    def _restore_controls(self):
        self.filling = True
        try:
            shape = self.shape()
            self.ctl(u"ShapeRect").IsChecked = shape == core.SHAPE_RECT
            self.ctl(u"ShapeRound").IsChecked = shape == core.SHAPE_ROUND
            self.ctl(u"IncludeDucts").IsChecked = core.flag(
                self.settings, u"include_ducts")
            self.ctl(u"IncludeAccessories").IsChecked = core.flag(
                self.settings, u"include_accessories")
            self.ctl(u"IncludeTerminals").IsChecked = core.flag(
                self.settings, u"include_terminals")
            edit = self.settings.get(u"type_mode") == u"edit"
            self.ctl(u"TypeEdit").IsChecked = edit
            self.ctl(u"TypeSwitch").IsChecked = not edit
            self.ctl(u"DebugCheck").IsChecked = core.flag(self.settings,
                                                          u"debug")
            for dim, box in sorted(NEW_BOX.items()):
                self.ctl(box).Text = self.settings.get(u"new_" + dim, u"")
        finally:
            self.filling = False
        self.show_shape_blocks()
        self.show_debug_button()

    def _wire(self):
        w = self.window
        w.KeyDown += self.guard(self.on_key)
        w.Activated += self.guard(self.on_activated)
        w.Closed += self.guard(self.on_closed)
        self.ctl(u"HeaderBar").MouseLeftButtonDown += self.guard(
            self.on_header_down)
        self.ctl(u"LogoHost").MouseLeftButtonDown += self.guard(
            self.on_logo_down)
        self.ctl(u"CloseButton").Click += self.guard(self.on_close)
        self.ctl(u"FullScreenButton").Click += self.guard(self.on_full)
        self.ctl(u"ShrinkButton").Click += self.guard(self.on_shrink)
        self.ctl(u"ThemeChip").Click += self.guard(self.on_theme_chip)
        for name in (u"ShapeRect", u"ShapeRound"):
            self.ctl(name).Checked += self.guard(self.on_shape)
        for kind in core.FAMILY_KINDS:
            for dim in ALL_DIMS:
                self.ctl(COMBO[kind][dim]).SelectionChanged += self.guard(
                    self._make_combo_handler(kind, dim))
                self.ctl(SEARCH[kind][dim]).TextChanged += self.guard(
                    self._make_search_handler(kind, dim))
        for dim in ALL_DIMS:
            self.ctl(NEW_BOX[dim]).TextChanged += self.guard(self.on_new_size)
        self.ctl(u"RefreshParamsButton").Click += self.guard(
            self.on_refresh_params)
        for name in (u"IncludeDucts", u"IncludeAccessories",
                     u"IncludeTerminals"):
            self.ctl(name).Checked += self.guard(self.on_include)
            self.ctl(name).Unchecked += self.guard(self.on_include)
        for name in (u"TypeSwitch", u"TypeEdit"):
            self.ctl(name).Checked += self.guard(self.on_type_mode)
        self.ctl(u"SelectButton").Click += self.guard(self.on_select)
        self.ctl(u"UseSelectionButton").Click += self.guard(
            self.on_use_selection)
        self.ctl(u"ClearButton").Click += self.guard(self.on_clear)
        self.ctl(u"DebugCheck").Checked += self.guard(self.on_debug)
        self.ctl(u"DebugCheck").Unchecked += self.guard(self.on_debug)
        self.ctl(u"CopyDebugButton").Click += self.guard(self.on_copy_debug)
        self.ctl(u"ResizeButton").Click += self.guard(self.on_resize)

    def _hook_dialogs(self):
        _DIALOG[u"log"] = self.log
        if _DIALOG[u"hooked"]:
            return
        try:
            self.uiapp.DialogBoxShowing += _on_dialog
            _DIALOG[u"hooked"] = True
        except Exception:
            self.log.add(u"could not hook DialogBoxShowing")

    # ---------------------------------------------------------- chrome

    def on_key(self, sender, args):
        if args.Key == Key.H and self._chord():
            self.drawer.toggle()
            args.Handled = True
            return
        if self.drawer.parked:
            # Escape, Enter and F11 open it again rather than answering a
            # prompt nobody can see or filling the screen with a window
            # nobody can see either
            if args.Key in (Key.Escape, Key.Enter, Key.F11):
                self.drawer.restore()
                args.Handled = True
            return
        if args.Key == Key.F11:
            self.full.toggle()
            args.Handled = True
        elif args.Key == Key.Escape and self.full.active:
            self.full.leave()
            args.Handled = True

    def _chord(self):
        try:
            mods = Keyboard.Modifiers
            return (bool(mods & ModifierKeys.Control) and
                    bool(mods & ModifierKeys.Shift))
        except Exception:
            return False

    def on_shrink(self, sender, args):
        self.drawer.toggle()

    def on_header_down(self, sender, args):
        if args.ClickCount == 2:
            # parked, a double click on the bar opens it rather than
            # maximising a window nobody can see
            if self.drawer.parked:
                self.drawer.restore()
            else:
                self.full.toggle()
            return
        if self.busy and self.drawer.parked:
            # DragMove runs a modal message loop, which is not something to
            # start while a job holds Revit's API context
            return
        if self.full.active:
            self.full.leave()
        try:
            self.window.DragMove()
        except Exception:
            pass

    def on_logo_down(self, sender, args):
        # the logo belongs to the easter egg: no drag, no full screen
        args.Handled = True

    def on_full(self, sender, args):
        if self.drawer.parked:
            self.drawer.restore()
            return
        self.full.toggle()

    def on_close(self, sender, args):
        # settle first, so nothing is left pinned or clamped behind it
        self.drawer.settle()
        self.window.Close()

    def on_closed(self, sender, args):
        try:
            self.drawer.settle()
        except Exception:
            pass
        try:
            self.watchdog.Stop()
        except Exception:
            pass
        self.save()
        self.log.write()
        try:
            AppDomain.CurrentDomain.SetData(APPDOMAIN_KEY, None)
        except Exception:
            pass
        if self in _LIVE:
            _LIVE.remove(self)

    # ---------------------------------------------------------- the event

    def submit(self, name, fn, callback, busy_text):
        if self.busy:
            self.log.add(u"click ignored while busy: {0}", name)
            self.set_status(u"Still working on the last request...",
                            u"Orange")
            return False
        job = Job(name, fn, None)

        def finished(value, error):
            self.current_job = None
            self.set_busy(False)
            callback(value, error)
        job.callback = finished
        self.runner.jobs.append(job)
        status = core.to_text(self.event.Raise())
        self.log.add(u"raise {0}: {1}", name, status)
        if status not in (u"Accepted", u"Pending"):
            if job in self.runner.jobs:
                self.runner.jobs.remove(job)
            self.set_status(u"Revit would not take the request ({0}) - "
                            u"try again".format(status), u"Red")
            return False
        self.current_job = job
        self.set_busy(True, busy_text)
        return True

    def set_busy(self, busy, text=None):
        self.busy = busy
        for name in ACTION_BUTTONS:
            self.ctl(name).IsEnabled = not busy
        self.update_resize_button()
        if busy and text:
            self.set_status(text, u"Blue")

    def on_watchdog(self, sender, args):
        """A request Revit never started - it was busy in a command or a
        dialog - frees the window after 20s instead of locking it for good.
        A running request (a pick, a long resize) is left alone."""
        job = self.current_job
        if job is None or job.started:
            return
        if time.time() - job.raised < WATCHDOG_S:
            return
        if job in self.runner.jobs:
            self.runner.jobs.remove(job)
        self.log.add(u"watchdog freed the window: '{0}' never started",
                     job.name)
        self.current_job = None
        self.set_busy(False)
        self.set_status(u"Revit did not run the request - finish what it is "
                        u"doing and press again", u"Orange")

    # ---------------------------------------------------------- parameters

    def load_params(self, doc):
        for kind in core.FAMILY_KINDS:
            names, type_count = rv.collect_params(doc, kind)
            self.params[kind] = names
            self.log.add(u"{0} length parameters on {1} {2} types",
                         len(names), type_count, core.KIND_WORD[kind])
            for dim, key in core.KIND_SETTING[kind].items():
                if not self.settings.get(key):
                    self.settings[key] = core.pick_default(names, dim, kind)
            self.ctl(PARAM_HINT[kind]).Text = (
                u"{0} length parameters found on {1} {2} types in this "
                u"model.".format(len(names), type_count,
                                 core.KIND_WORD[kind]))
            for dim in ALL_DIMS:
                self.fill_combo(kind, dim)
        self.save()

    def fill_combo(self, kind, dim):
        """Searching filters the list and nothing else: the chosen parameter
        only changes when a name is picked from the dropdown."""
        combo = self.ctl(COMBO[kind][dim])
        current = self.settings.get(core.KIND_SETTING[kind][dim], u"")
        search = self.ctl(SEARCH[kind][dim]).Text
        names = list(self.params.get(kind) or [])
        shown, matched = core.search_list(names, current, search)
        if not matched:
            self.set_status(u"No parameter matches '{0}' - showing them "
                            u"all".format(search), u"Orange")
        self.filling = True
        try:
            combo.Items.Clear()
            for name in shown:
                combo.Items.Add(name)
            if current in shown:
                combo.SelectedItem = current
        finally:
            self.filling = False
        if search.strip() and matched:
            combo.IsDropDownOpen = True

    def _make_combo_handler(self, kind, dim):
        def on_combo(sender, args):
            if self.filling:
                return
            value = core.to_text(sender.SelectedItem)
            key = core.KIND_SETTING[kind][dim]
            if not value or value == self.settings.get(key):
                return
            self.settings[key] = value
            self.save()
            self.reread(u"Reading {0} from the selection...".format(value))
        on_combo.__name__ = "on_combo_" + kind + "_" + dim
        return on_combo

    def _make_search_handler(self, kind, dim):
        def on_search(sender, args):
            self.fill_combo(kind, dim)
        on_search.__name__ = "on_search_" + kind + "_" + dim
        return on_search

    def on_refresh_params(self, sender, args):
        def work(uiapp):
            self.load_params(uiapp.ActiveUIDocument.Document)
            return None

        def done(value, error):
            if error:
                self.fail(u"Could not read the parameters", error)
                return
            self.set_status(u"Parameters re-read")
        self.submit(u"refresh params", work, done, u"Reading parameters...")

    # ---------------------------------------------------------- options

    def show_shape_blocks(self):
        shape = self.shape()
        for dim in ALL_DIMS:
            used = dim in core.DIMS[shape]
            blocks = [NEW_BLOCK[dim]] + [PARAM_BLOCK[k][dim]
                                         for k in core.FAMILY_KINDS]
            for block in blocks:
                element = self.ctl(block)
                element.IsEnabled = used
                element.Opacity = 1.0 if used else 0.35

    def on_shape(self, sender, args):
        if self.filling:
            return
        shape = (core.SHAPE_ROUND if self.ctl(u"ShapeRound").IsChecked
                 else core.SHAPE_RECT)
        if shape == self.shape():
            return
        self.settings[u"shape"] = shape
        self.save()
        self.clear_results()
        self.show_shape_blocks()
        self.recompute()

    def on_include(self, sender, args):
        if self.filling:
            return
        self.settings[u"include_ducts"] = (
            u"1" if self.ctl(u"IncludeDucts").IsChecked else u"0")
        self.settings[u"include_accessories"] = (
            u"1" if self.ctl(u"IncludeAccessories").IsChecked else u"0")
        self.settings[u"include_terminals"] = (
            u"1" if self.ctl(u"IncludeTerminals").IsChecked else u"0")
        self.save()
        self.recompute()

    def on_type_mode(self, sender, args):
        if self.filling:
            return
        self.settings[u"type_mode"] = (
            u"edit" if self.ctl(u"TypeEdit").IsChecked else u"switch")
        self.save()

    def on_new_size(self, sender, args):
        if self.filling:
            return
        for dim, box in NEW_BOX.items():
            self.settings[u"new_" + dim] = self.ctl(box).Text
        self.save()
        self.clear_results()
        self.recompute()

    # ---------------------------------------------------------- debug

    def show_debug_button(self):
        on = bool(self.ctl(u"DebugCheck").IsChecked)
        self.ctl(u"CopyDebugButton").Visibility = (
            Visibility.Visible if on else Visibility.Collapsed)

    def on_debug(self, sender, args):
        if self.filling:
            return
        on = bool(self.ctl(u"DebugCheck").IsChecked)
        self.settings[u"debug"] = u"1" if on else u"0"
        self.log.enabled = on
        self.save()
        self.show_debug_button()

    def on_copy_debug(self, sender, args):
        lines = [u"RevoBIM {0} v{1} - debug".format(core.TOOL_NAME,
                                                     core.__version__),
                 u"settings: {0}".format(sorted(self.settings.items())),
                 u"rows on screen: {0}".format(len(self.rows))]
        text = u"\n".join(lines) + u"\n" + self.log.text()
        Clipboard.SetText(text)
        path = self.log.write()
        self.set_status(u"Debug copied to the clipboard - paste it into the "
                        u"chat{0}".format(u" (also " + path + u")"
                                          if path else u""), u"Green")

    def fail(self, headline, error):
        self.log.add(u"{0}: {1}", headline, error)
        path = self.log.write()
        last = core.to_text(error).strip().splitlines()
        tail = last[-1] if last else u""
        self.set_status(u"{0} - {1}{2}".format(
            headline, tail, u" | Copy debug to send it" if path else u""),
            u"Red")

    # ---------------------------------------------------------- selection

    def reread(self, busy_text):
        if not self.rows:
            return
        ids = [r[u"eid"] for r in self.rows]
        settings = dict(self.settings)

        def work(uiapp):
            return rv.read_rows(uiapp.ActiveUIDocument.Document, ids,
                                settings, self.log)

        def done(value, error):
            if error:
                self.fail(u"Could not read the selection", error)
                return
            self.rows = value[0]
            self.recompute()
        self.submit(u"reread", work, done, busy_text or u"Reading...")

    def on_select(self, sender, args):
        settings = dict(self.settings)
        self.log.section(u"select")

        def work(uiapp):
            ids = rv.pick_elements(uiapp)
            if ids is None:
                return None
            return rv.read_rows(uiapp.ActiveUIDocument.Document, ids,
                                settings, self.log)

        def done(value, error):
            if error:
                self.fail(u"Selection failed", error)
                return
            if value is None:
                self.set_status(u"Selection cancelled - nothing changed")
                return
            self.rows, skipped = value
            self.clear_results()
            self.recompute()
            self.set_status(u"{0} selected{1}".format(
                len(self.rows), u", {0} skipped".format(skipped)
                if skipped else u""))
            self.window.Activate()
        self.submit(u"select", work, done,
                    u"Select ducts, duct accessories and air terminals in "
                    u"Revit, then "
                    u"Finish (Escape cancels)")

    def on_use_selection(self, sender, args):
        settings = dict(self.settings)
        self.log.section(u"use selection")

        def work(uiapp):
            ids, dropped = rv.selected_ids(uiapp)
            rows, skipped = rv.read_rows(uiapp.ActiveUIDocument.Document, ids,
                                         settings, self.log)
            return rows, dropped + skipped

        def done(value, error):
            if error:
                self.fail(u"Could not read the selection", error)
                return
            self.rows, dropped = value
            self.clear_results()
            self.recompute()
            if not self.rows:
                self.set_status(u"Nothing in the Revit selection is a duct, "
                                u"duct accessory or air terminal", u"Orange")
            else:
                self.set_status(u"{0} taken from the Revit selection{1}".format(
                    len(self.rows), u", {0} other elements ignored".format(
                        dropped) if dropped else u""))
        self.submit(u"use selection", work, done, u"Reading the selection...")

    def on_clear(self, sender, args):
        self.rows = []
        self.recompute()
        self.set_status(u"Selection cleared")

    # ---------------------------------------------------------- the table

    def clear_results(self):
        for row in self.rows:
            row.pop(u"result", None)

    def recompute(self):
        shape = self.shape()
        texts = dict((d, self.ctl(NEW_BOX[d]).Text) for d in core.DIMS[shape])
        self.new, self.input_errors = core.parse_new_sizes(shape, texts)
        error_box = self.ctl(u"InputError")
        if self.input_errors:
            error_box.Text = u"   ".join(
                u"{0}: {1}".format(core.DIM_NAMES[d], m)
                for d, m in sorted(self.input_errors.items()))
            error_box.Visibility = Visibility.Visible
        else:
            error_box.Visibility = Visibility.Collapsed

        include_ducts = core.flag(self.settings, u"include_ducts")
        include_acc = core.flag(self.settings, u"include_accessories")
        include_term = core.flag(self.settings, u"include_terminals")
        clashes = core.all_clashes(self.settings, shape)
        self.clash = u"  ".join(clashes[k] for k in sorted(clashes))
        for kind in core.FAMILY_KINDS:
            warning = self.ctl(PARAM_WARNING[kind])
            warning.Text = core.param_clash(
                core.settings_names(self.settings, kind), shape)
            warning.Visibility = (Visibility.Visible if kind in clashes
                                  else Visibility.Collapsed)
        for row in self.rows:
            state, note = core.row_status(row, shape, self.new,
                                          include_ducts, include_acc,
                                          include_term)
            row[u"_state"], row[u"_note"] = state, note

        tally = []
        for label, kind in ((u"ducts", u"duct"),
                            (u"accessories", core.KIND_ACC),
                            (u"terminals", core.KIND_TERM)):
            count = len([r for r in self.rows if r[u"kind"] == kind])
            if count:
                tally.append(u"{0} {1}".format(count, label))
        self.ctl(u"CountText").Text = u", ".join(tally)
        live = [r for r in self.rows if core.counts_in_summary(
            r[u"_state"], r[u"_note"])]
        summary = core.summarise(shape, live)
        if not self.rows:
            summary = u"Nothing selected yet"
        elif not summary:
            summary = u"Nothing selected can be resized as {0}".format(
                core.shape_word(shape).lower())
        self.ctl(u"CurrentText").Text = summary
        self.render_rows()
        self.update_resize_button()

    def orange_count(self):
        return len([r for r in self.rows if r.get(u"_state") == u"orange"])

    def update_resize_button(self):
        count = self.orange_count()
        self.ctl(u"ResizeLabel").Text = (u"Resize ({0})".format(count)
                                         if count else u"Resize")
        self.ctl(u"ResizeButton").IsEnabled = (
            count > 0 and not self.busy and not self.input_errors
            and not getattr(self, u"clash", u""))

    def render_rows(self):
        panel = self.ctl(u"TableRows")
        panel.Children.Clear()
        self.ctl(u"EmptyHint").Visibility = (
            Visibility.Collapsed if self.rows else Visibility.Visible)
        shape = self.shape()
        for row in self.rows[:core.MAX_ROWS_DRAWN]:
            panel.Children.Add(self._row_element(row, shape))
        if len(self.rows) > core.MAX_ROWS_DRAWN:
            more = TextBlock()
            more.Margin = Thickness(10, 6, 10, 6)
            more.Text = u"{0} more not drawn - they are still resized".format(
                len(self.rows) - core.MAX_ROWS_DRAWN)
            more.SetResourceReference(TextBlock.ForegroundProperty,
                                      u"MutedBrush")
            panel.Children.Add(more)

    def _source_text(self, row, shape):
        if row[u"kind"] not in core.FAMILY_KINDS:
            return u"duct", u"Muted"
        places = set()
        for dim in core.DIMS[shape]:
            source = (row.get(u"sources") or {}).get(dim)
            if source:
                places.add(source[0])
        if not places:
            return u"-", u"Muted"
        if len(places) > 1:
            return u"mixed", u"Orange"
        place = list(places)[0]
        return place, (u"Orange" if place == u"type" else u"Blue")

    def _row_element(self, row, shape):
        state = row.get(u"_state", u"idle")
        note = row.get(u"_note", u"")
        current = row.get(u"current") or {}
        border = Border()
        border.Padding = Thickness(0, 6, 0, 6)
        border.BorderThickness = Thickness(0, 0, 0, 1)
        border.SetResourceReference(Border.BackgroundProperty,
                                    core.STATE_WASH[state] + u"Brush")
        border.SetResourceReference(Border.BorderBrushProperty, u"EdgeBrush")
        grid = Grid()
        self._columns(grid)
        source, source_colour = self._source_text(row, shape)
        if state in (u"orange", u"green"):
            new_text = core.fmt_size(shape, core.target_sizes(
                shape, current, self.new))
        else:
            new_text = u"-"
        family_type = u"{0} : {1}".format(row.get(u"family") or u"-",
                                          row.get(u"type") or u"-")
        values = (
            (core.to_text(row[u"id"]), u"Muted", False),
            (row.get(u"category", u""), u"Text", False),
            (family_type, u"Text", False),
            (source, source_colour, False),
            (core.fmt_size(shape, current), u"Text", True),
            (new_text, core.STATE_TEXT[state], True),
            (note, core.STATE_TEXT[state], False),
        )
        for index, (text, colour, bold) in enumerate(values):
            self._cell(grid, index, text, colour, bold)
        border.Child = grid
        border.ToolTip = u"Element {0}\n{1}\n{2} -> {3}\n{4}\n" \
                         u"Double click to show it in Revit".format(
                             row[u"id"], family_type,
                             core.fmt_size(shape, current), new_text, note)
        border.MouseLeftButtonDown += self.guard(self._make_row_click(row))
        return border

    def _make_row_click(self, row):
        def on_row(sender, args):
            if args.ClickCount != 2:
                return
            eid = row[u"eid"]

            def work(uiapp):
                rv.show_element(uiapp, eid)

            def done(value, error):
                if error:
                    self.fail(u"Could not show the element", error)
            self.submit(u"show", work, done, u"Showing it in Revit...")
        on_row.__name__ = "on_row_click"
        return on_row

    # ---------------------------------------------------------- resize

    def on_resize(self, sender, args):
        if self.input_errors or self.clash or not self.orange_count():
            return
        rows = list(self.rows)
        shape = self.shape()
        new = dict(self.new)
        settings = dict(self.settings)
        count = self.orange_count()

        def work(uiapp):
            _DIALOG[u"active"] = True
            try:
                result = rv.apply_resize(uiapp, rows, shape, new, settings,
                                         self.log)
            finally:
                _DIALOG[u"active"] = False
            fresh, skipped = rv.read_rows(uiapp.ActiveUIDocument.Document,
                                          [r[u"eid"] for r in rows],
                                          settings, self.log)
            return result, fresh

        def done(value, error):
            if error:
                self.fail(u"Resize failed", error)
                return
            result, fresh = value
            if result.get(u"stopped"):
                self.set_status(result[u"stopped"], u"Red")
                return
            changed = set(result[u"changed"])
            refused = result[u"refused"]
            for row in fresh:
                if row[u"id"] in changed:
                    row[u"result"] = (u"green", u"resized")
                elif row[u"id"] in refused:
                    row[u"result"] = (u"red", refused[row[u"id"]])
            self.rows = fresh
            self.recompute()
            self.log.write()
            if refused:
                self.set_status(u"Resized {0} of {1} - {2} refused, see the "
                                u"red rows".format(len(changed),
                                                   result[u"asked"],
                                                   len(refused)), u"Orange")
            else:
                self.set_status(u"Resized {0} of {1}".format(
                    len(changed), result[u"asked"]), u"Green")
        self.submit(u"resize", work, done,
                    u"Resizing {0} elements...".format(count))

    # ---------------------------------------------------------- show

    def show(self):
        try:
            WindowInteropHelper(self.window).Owner = self.uiapp.MainWindowHandle
        except Exception:
            self.log.add(u"could not own the window to Revit")
        self.window.Show()


def launch(uiapp):
    """One window per session: a second press brings the open one forward."""
    existing = None
    try:
        existing = AppDomain.CurrentDomain.GetData(APPDOMAIN_KEY)
    except Exception:
        existing = None
    if existing is not None:
        try:
            if existing.window.IsVisible:
                existing.window.Activate()
                return existing
        except Exception:
            pass
    tool = ResizeWindow(uiapp)
    _LIVE[:] = [tool]
    try:
        AppDomain.CurrentDomain.SetData(APPDOMAIN_KEY, tool)
    except Exception:
        pass
    tool.show()
    return tool
