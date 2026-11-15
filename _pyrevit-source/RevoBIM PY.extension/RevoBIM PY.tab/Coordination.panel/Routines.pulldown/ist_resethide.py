# -*- coding: utf-8 -*-
u"""RevoBIM PY - Hide Service Type : the floating Reset Hide window.

Modeless, owned by Revit's main window so it floats in front of it.  It reads
the hide memory for one model and puts each remembered hide back - or hides it
again - through the ExternalEvent runner.

Two buttons open it (Hide Service Type after a remembered hide, and Reset
Hide), and pyRevit gives each its own engine, so the window cannot be shared
as a Python object.  What crosses between them lives in the AppDomain:

- the WPF window itself, under a version-stamped key, so a second press brings
  the open one forward instead of opening another;
- which model it is showing, as the window's Tag - another engine sets it, and
  the owner's timer picks it up;
- a heartbeat the owner's timer writes every second.  A window whose engine has
  gone (a pyRevit reload) stops beating; the next press closes it and opens a
  working one rather than bringing forward a window that no longer answers.

The window also watches the memory file, so a hide made while it is open shows
up in it within a second without anyone pressing anything.
"""

import ist_clr  # noqa: F401

import time

from System import AppDomain, TimeSpan
from System.Windows import (
    FrameworkElement,
    GridLength,
    SystemParameters,
    TextTrimming,
    Thickness,
    VerticalAlignment,
    WindowState,
)
from System.Windows.Controls import Button, ColumnDefinition, Grid, TextBlock
from System.Windows.Threading import DispatcherTimer

import ist_core
import ist_memory
import ist_runner
import ist_theme
import ist_ui

ICON_FOLDER = u"Reset Hide.pushbutton"
WINDOW_KEY = u"RevoBIM.IsolateServiceType.ResetHide." + ist_core.__version__
BEAT_KEY = WINDOW_KEY + u".beat"
BEAT_STALE = 5.0          # seconds without a beat = the engine is gone
WATCHDOG = 20.0           # seconds a job may wait for Revit before giving up

# The persistent engine collects anything nothing holds on to.
_LIVE = []


class ResetHideWindow(object):

    def __init__(self, key, values):
        self.key = key
        self.values = values
        self.theme = (values.get(u"theme") or u"dark").strip().lower()
        self.stamp = None
        self.busy_since = None
        self.current_uid = None

        self.window = ist_ui.load_window(u"IstResetHide.xaml", self.theme)
        ist_ui.wire_chrome(self.window, icon_folder=ICON_FOLDER)
        ist_ui.owned_by_revit(self.window)
        self.find = self.window.FindName
        self.window.Tag = key
        self._place()

        self.runner = ist_runner.Runner(self._log)
        self._wire()

        self.timer = DispatcherTimer()
        self.timer.Interval = TimeSpan.FromMilliseconds(1000)
        self.timer.Tick += self._tick
        self.timer.Start()
        self.window.Closed += self._closed
        self.refresh()

    # -- placing ---------------------------------------------------------------
    def _place(self):
        u"""Where it was last, else top right of the screen, out of the way."""
        try:
            left = float(self.values.get(u"reset_left") or u"nan")
            top = float(self.values.get(u"reset_top") or u"nan")
        except Exception:
            left = top = float(u"nan")
        area = SystemParameters.WorkArea
        if left != left or top != top:   # nan: never placed
            left = area.Right - self.window.Width - 48
            top = area.Top + 140
        left = max(area.Left, min(left, area.Right - 120))
        top = max(area.Top, min(top, area.Bottom - 80))
        self.window.Left = left
        self.window.Top = top

    def _remember_place(self):
        try:
            values = ist_core.load_settings()
            values[u"reset_left"] = u"{0:.0f}".format(self.window.Left)
            values[u"reset_top"] = u"{0:.0f}".format(self.window.Top)
            ist_core.save_settings(values)
        except Exception:
            pass

    # -- drawing ---------------------------------------------------------------
    def refresh(self):
        data = ist_memory.load(self.key)
        self.stamp = ist_memory.stamp(self.key)
        views = ist_memory.ordered_views(data)
        last = data.get(u"last")
        current = None
        for uid, entry in views:
            if uid == last:
                current = (uid, entry)
        if current is None and views:
            current = views[0]

        view_text = self.find(u"ViewText")
        count_text = self.find(u"CountText")
        main = self.find(u"MainButton")
        forget = self.find(u"ForgetButton")
        if current is None:
            self.current_uid = None
            view_text.Text = u"Nothing remembered"
            count_text.Text = (u"Hide Service Type remembers what it hides; "
                               u"it shows up here to put back.")
            main.Content = u"Reset Hide"
            main.IsEnabled = False
            forget.IsEnabled = False
        else:
            uid, entry = current
            self.current_uid = uid
            hidden = entry.get(u"state") != ist_memory.SHOWN
            view_text.Text = entry.get(u"name") or u"?"
            template = entry.get(u"template") or u""
            count_text.Text = u"{0}{1} - {2}".format(
                u"Template {0}  \u00b7  ".format(template) if template else u"",
                ist_memory.describe(entry),
                u"hidden" if hidden else u"showing")
            self._style(main, hidden)
            main.IsEnabled = self.busy_since is None
            forget.IsEnabled = self.busy_since is None

        holder = self.find(u"OtherViews")
        holder.Children.Clear()
        others = [(u, e) for u, e in views if u != self.current_uid]
        for uid, entry in others:
            holder.Children.Add(self._row(uid, entry))
        label = self.find(u"OthersLabel")
        if label is not None:
            label.Text = u"Other views" if others else u""
        reset_all = self.find(u"ResetAllButton")
        if reset_all is not None:
            reset_all.IsEnabled = self.busy_since is None and bool(
                [e for _, e in views if e.get(u"state") != ist_memory.SHOWN])

    def _style(self, button, hidden):
        button.Content = u"Reset Hide" if hidden else u"Hide again"
        try:
            button.SetResourceReference(
                FrameworkElement.StyleProperty,
                u"IstGreenButton" if hidden else u"IstButton")
        except Exception:
            pass

    def _row(self, uid, entry):
        grid = Grid()
        grid.Margin = Thickness(0, 0, 0, 4)
        grid.ColumnDefinitions.Add(ColumnDefinition())
        col = ColumnDefinition()
        col.Width = GridLength.Auto
        grid.ColumnDefinitions.Add(col)
        hidden = entry.get(u"state") != ist_memory.SHOWN
        text = TextBlock()
        text.Text = u"{0}  -  {1}".format(entry.get(u"name") or u"?",
                                          ist_memory.describe(entry))
        text.FontSize = 11.5
        text.TextTrimming = TextTrimming.CharacterEllipsis
        text.VerticalAlignment = VerticalAlignment.Center
        try:
            text.SetResourceReference(
                TextBlock.ForegroundProperty,
                u"TextBrush" if hidden else u"MutedBrush")
        except Exception:
            pass
        grid.Children.Add(text)
        button = Button()
        button.Content = u"Reset" if hidden else u"Hide again"
        button.Margin = Thickness(8, 0, 0, 0)
        button.IsEnabled = self.busy_since is None
        try:
            button.SetResourceReference(FrameworkElement.StyleProperty,
                                        u"IstChip")
        except Exception:
            pass
        Grid.SetColumn(button, 1)
        button.Click += self._row_handler(uid, hidden)
        grid.Children.Add(button)
        return grid

    def _row_handler(self, uid, hidden):
        def handler(sender, args):
            self._do(u"reset" if hidden else u"redo", uid)
        return handler

    # -- jobs --------------------------------------------------------------------
    def _status(self, text):
        label = self.find(u"StatusText")
        if label is not None:
            label.Text = text

    def _log(self, text):
        self._status(text)

    def _do(self, action, uid):
        if self.busy_since is not None:
            self._status(u"Still working on the last one...")
            return
        key = self.key
        values = ist_core.load_settings()

        def job(uiapp):
            self._run(uiapp, key, action, uid, values)

        self.busy_since = time.time()
        self.refresh()
        self._status(u"Waiting for Revit...")
        ok, why = self.runner.submit(job)
        if not ok:
            self.busy_since = None
            self.refresh()
            self._status(u"Revit would not take it ({0}). Close any dialog "
                         u"or edit mode in Revit and try again.".format(why))

    def _run(self, uiapp, key, action, uid, values):
        report = ist_core.Report()
        try:
            doc = None
            for candidate in uiapp.Application.Documents:
                try:
                    if candidate.IsLinked:
                        continue
                    if ist_memory.model_key(candidate) == key:
                        doc = candidate
                        break
                except Exception:
                    continue
            if doc is None:
                report.refused = u"That model is not open."
            else:
                ist_memory.run_job(doc, action, uid, values, report)
                try:
                    uiapp.ActiveUIDocument.RefreshActiveView()
                except Exception:
                    pass
        except Exception as err:
            report.refused = u"{0}".format(err)
        self.busy_since = None
        self.refresh()
        if report.refused:
            self._status(report.refused)
        else:
            lines = list(report.lines) + list(report.notes)
            self._status(u"  ".join(lines) or u"Done.")

    # -- buttons -------------------------------------------------------------------
    def _main(self, sender, args):
        if self.current_uid is None:
            return
        entry = (ist_memory.load(self.key).get(u"views") or {}).get(
            self.current_uid) or {}
        hidden = entry.get(u"state") != ist_memory.SHOWN
        self._do(u"reset" if hidden else u"redo", self.current_uid)

    def _new_selection(self, sender, args):
        u"""The list, clean, on the view open in Revit - run as a job, since
        hiding from it needs Revit's API context."""
        if self.busy_since is not None:
            self._status(u"Still working on the last one...")
            return

        def job(uiapp):
            report = ist_core.Report()
            try:
                import ist_browser
                import ist_templates
                values = ist_core.load_settings()
                uidoc = uiapp.ActiveUIDocument
                picked = ist_browser.run(uidoc, values, report)
                if picked is not None:
                    report = ist_core.hide_from_list(uidoc, values, picked,
                                                     report)
                    if not picked.get(u"reset") and not picked.get(u"empty"):
                        ist_templates.set_last(picked.get(u"template"))
                    # the list may have been opened on another model
                    self.window.Tag = ist_memory.model_key(uidoc.Document)
                    try:
                        uidoc.RefreshActiveView()
                    except Exception:
                        pass
            except Exception as err:
                report.refused = u"{0}".format(err)
            self.busy_since = None
            self.refresh()
            if report.refused:
                self._status(report.refused)
            elif report.cancelled:
                self._status(u"")
            else:
                self._status(u"  ".join(list(report.lines) +
                                        list(report.notes)) or u"Done.")

        self.busy_since = time.time()
        self.refresh()
        ok, why = self.runner.submit(job)
        if not ok:
            self.busy_since = None
            self.refresh()
            self._status(u"Revit would not take it ({0}).".format(why))

    def _forget(self, sender, args):
        if self.current_uid is not None:
            self._do(u"forget", self.current_uid)

    def _reset_all(self, sender, args):
        self._do(u"reset_all", None)

    def _toggle_theme(self, sender, args):
        self.theme = u"light" if self.theme == u"dark" else u"dark"
        ist_theme.apply(self.window, self.theme)
        try:
            sender.Content = u"Light" if self.theme == u"dark" else u"Dark"
        except Exception:
            pass
        values = ist_core.load_settings()
        values[u"theme"] = self.theme
        ist_core.save_settings(values)

    def _wire(self):
        for name, handler in ((u"MainButton", self._main),
                              (u"NewSelectionButton", self._new_selection),
                              (u"ForgetButton", self._forget),
                              (u"ResetAllButton", self._reset_all),
                              (u"ThemeChip", self._toggle_theme)):
            control = self.find(name)
            if control is not None:
                control.Click += handler
        chip = self.find(u"ThemeChip")
        if chip is not None:
            chip.Content = u"Light" if self.theme == u"dark" else u"Dark"

    # -- the timer -------------------------------------------------------------------
    def _tick(self, sender, args):
        try:
            AppDomain.CurrentDomain.SetData(BEAT_KEY, u"{0}".format(time.time()))
            tag = u"{0}".format(self.window.Tag or u"")
            if tag and tag != self.key:
                self.key = tag
                self.refresh()
            elif ist_memory.stamp(self.key) != self.stamp:
                self.refresh()
            if self.busy_since is not None and \
                    time.time() - self.busy_since > WATCHDOG:
                self.busy_since = None
                self.refresh()
                self._status(u"Revit did not pick that up - a dialog or edit "
                             u"mode may be open. Press it again.")
        except Exception:
            pass

    def _closed(self, sender, args):
        try:
            self.timer.Stop()
        except Exception:
            pass
        self._remember_place()
        self.runner.dispose()
        try:
            held = AppDomain.CurrentDomain.GetData(WINDOW_KEY)
            if held is not None and held.Equals(self.window):
                AppDomain.CurrentDomain.SetData(WINDOW_KEY, None)
        except Exception:
            pass
        AppDomain.CurrentDomain.SetData(BEAT_KEY, None)
        if self in _LIVE:
            _LIVE.remove(self)


def _alive(window):
    u"""The window exists, is open, and its engine is still beating."""
    if window is None:
        return False
    try:
        if not window.IsLoaded:
            return False
    except Exception:
        return False
    try:
        beat = float(u"{0}".format(AppDomain.CurrentDomain.GetData(BEAT_KEY)))
    except Exception:
        return False
    return time.time() - beat < BEAT_STALE


def show(doc, values):
    u"""Bring the floating window forward on `doc`'s memory, opening it if it is
    not open.  Must be called from a command (API context), since opening it
    makes the ExternalEvent."""
    key = ist_memory.model_key(doc)
    existing = AppDomain.CurrentDomain.GetData(WINDOW_KEY)
    if _alive(existing):
        try:
            existing.Tag = key
            if existing.WindowState == WindowState.Minimized:
                existing.WindowState = WindowState.Normal
            existing.Show()
            existing.Activate()
            return existing
        except Exception:
            pass
    if existing is not None:
        try:
            existing.Close()
        except Exception:
            pass
    win = ResetHideWindow(key, values)
    _LIVE.append(win)
    AppDomain.CurrentDomain.SetData(WINDOW_KEY, win.window)
    AppDomain.CurrentDomain.SetData(BEAT_KEY, u"{0}".format(time.time()))
    win.window.Show()
    return win.window
