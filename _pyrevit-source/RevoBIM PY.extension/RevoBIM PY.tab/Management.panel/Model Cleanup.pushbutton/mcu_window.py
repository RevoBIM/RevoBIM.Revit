# -*- coding: utf-8 -*-
"""The Model Cleanup window.

Modeless, so Revit stays usable while it is open. Nothing here touches the
model directly: every button that needs Revit queues a job on the runner
(mcu_events), Revit runs it in API context when it is free, and the job does
the work - prompts included. Three big step buttons in order - Sync, Save As,
Clean Up - and Clean Up stays dark until both of the first two are done.

While a job runs Revit is switched off (the progress bar pumps the
dispatcher, and that would otherwise let a ribbon click start a command
mid-job) and the window's body goes deaf - all but the shrink button, so the
window can still be put away to watch Revit.
"""
import os
import time
import datetime

import mcu_clr  # noqa: F401 - must come before any System.* import
import mcu_core as core
import mcu_aps as aps
import mcu_events as events
import mcu_model as model
import mcu_nwc as nwc
import mcu_ops as ops
import mcu_ui as ui

from System import TimeSpan, Func, AppDomain
from System.Windows import (Thickness, TextWrapping, FrameworkElement, GridLength,
                            Visibility)
from System.Windows.Threading import DispatcherTimer
from System.Windows.Controls import (TextBlock, Grid, ColumnDefinition, Control,
                                     Border)
from System.Windows.Input import Key
from Microsoft.Win32 import SaveFileDialog


class PublishCancelled(Exception):
    pass


INSTANCE_KEY = u"RevoBIM.ModelCleanup.window." + core.__version__
DEAF_NAMES = (u"BodyGrid", u"FooterBar", u"ThemeChip", u"FullScreenButton", u"CloseButton")


def bring_back_existing():
    """A second press of the ribbon button brings the open window back
    instead of opening another. Kept in the AppDomain with the version in the
    key, so a window from an older copy of the tool is never picked up."""
    try:
        found = AppDomain.CurrentDomain.GetData(INSTANCE_KEY)
    except Exception:
        return False
    if found is None:
        return False
    try:
        if found.Invoke():
            return True
    except Exception:
        pass
    try:
        AppDomain.CurrentDomain.SetData(INSTANCE_KEY, None)
    except Exception:
        pass
    return False


class CleanupWindow(object):

    def __init__(self, uiapp):
        self.uiapp = uiapp
        self.uidoc = uiapp.ActiveUIDocument
        self.doc = self.uidoc.Document
        self.settings = core.load_global()
        self.theme = ui.ThemeState(uiapp, self.settings)
        self.busy = False
        self.synced = False
        self.saved_as = False
        self.cleaned = False
        self.target_doc = None
        self.target_path = u""
        self.target_is_active = False
        self.open_after = u""
        self.purge_cache = None
        self.template_name = u""
        self.template = core.default_template()
        self.info = model.describe(self.doc)
        self.cancel_requested = False
        self.skipped = False
        self.debug = core.DebugReport(False)
        self.close_decided = False
        self.run_saved = False
        self.post_close = False
        self.publish_timer = None
        self.publish_target = None
        self.publish_started = 0.0
        self.closed = False
        self.queued_label = None
        self.queued_at = 0.0
        self.watchdog = None
        self.revit_locked = False
        self.revit_window = ui.revit_handle(uiapp)
        # read now, while the command is running: outside a job the window
        # has no business reading the model
        try:
            self.username = core.to_text(uiapp.Application.Username)
        except Exception:
            self.username = u""
        try:
            self.environment = model.environment(uiapp, self.doc)
        except Exception:
            self.environment = [(u"environment", core.format_exception())]
        # the ExternalEvent has to be made while a command is running
        self.runner = events.ApiRunner(on_error=self.on_job_failed)

        self.window, self.find, self.chrome, self.drawer = ui.standard_window(
            u"ModelCleanup.xaml", self.theme, lambda: self.busy)
        self.owned = ui.own_to_revit(self.window, uiapp)
        find = self.find
        self.progress = ui.ProgressBar(self.window, find)
        self.wire_job(u"SyncButton", u"Sync", self.on_sync)
        self.wire_job(u"SaveAsButton", u"Save As", self.on_save_as)
        self.wire_job(u"CleanupButton", u"Clean Up", self.on_cleanup)
        self.wire_job(u"ExportSettingsButton", u"Export Settings", self.on_export_settings)
        self.wire_job(u"ScanButton", u"Count", self.on_scan)
        self.wire_job(u"PublishButton", u"Publish", self.on_publish)
        self.wire(u"BrowseButton", self.on_browse)
        self.wire(u"FooterCloseButton", self.on_close_button)
        self.wire(u"SkipButton", self.on_skip)
        self.wire(u"OpenDebugButton", self.on_open_debug)
        self.find(u"DebugCheck").IsChecked = core.as_bool(self.settings.get(u"debug"))
        self.find(u"DebugCheck").Click += ui.safe_handler(self.window, self.on_debug_toggled, self.theme)
        find(u"TemplateCombo").SelectionChanged += ui.safe_handler(
            self.window, self.on_template_changed, self.theme)
        self.window.Closing += self.on_closing
        self.window.Closed += self.on_closed
        self.window.PreviewKeyDown += self.on_key

        self.fill_model_card()
        self.load_templates(self.settings.get(u"last_template"))
        self.refresh_steps()
        self.log(u"Model Cleanup v{0} - {1}".format(core.__version__, self.info[u"title"]))
        if core.as_bool(self.settings.get(u"debug")):
            self.start_debug()

    # ------------------------------------------------------------
    def wire(self, name, handler):
        self.find(name).Click += ui.safe_handler(self.window, handler, self.theme)

    def wire_job(self, name, label, handler):
        """A button whose work needs Revit: queued on the runner, run in API
        context when Revit is free."""
        def click(sender, args):
            self.request_job(label, lambda uiapp: handler(sender, args))
        self.find(name).Click += ui.safe_handler(self.window, click, self.theme)

    def show(self):
        """Modeless: returns at once and Revit carries on."""
        self.window.Show()
        try:
            AppDomain.CurrentDomain.SetData(INSTANCE_KEY, Func[bool](self.bring_back))
        except Exception:
            core.log(u"could not register the window: " + core.format_exception())

    def bring_back(self):
        if self.closed:
            return False
        try:
            if self.drawer.parked:
                self.drawer.expand()
            ui.bring_to_front(self.window)
            return True
        except Exception:
            return False

    # ============================================================
    # jobs
    # ============================================================
    def is_occupied(self):
        return bool(self.busy or self.queued_label or self.runner.running)

    def request_job(self, label, work):
        if self.closed:
            return False
        if self.is_occupied():
            self.log(u"{0} ignored - the tool is still working on {1}.".format(
                label, self.queued_label or self.runner.running or u"a job"))
            return False
        self.queued_label = label
        self.queued_at = time.time()
        before = core.to_text(self.find(u"StatusText").Text)
        self.set_deaf(True)
        self.set_status(core.waiting_note(0))

        def job(uiapp):
            self.queued_label = None
            self.stop_watchdog()
            self.set_deaf(False)
            self.set_status(before)
            if not self.model_open():
                return
            try:
                work(uiapp)
            finally:
                if self.busy:
                    self.end_busy(u"{0} stopped - see the log".format(label), u"fail")
                self.lock_revit(False)

        kept, status = self.runner.request(label, job)
        if not kept:
            self.queued_label = None
            self.set_deaf(False)
            self.set_status(before)
            self.tell(label, core.RAISE_HELP.format(status))
            return False
        self.start_watchdog()
        return True

    def on_job_failed(self, label, text):
        self.debug.exception(label, text)
        try:
            self.log(u"{0} failed: {1}".format(label, core.to_text(text).strip().splitlines()[-1]))
        except Exception:
            pass
        if not self.closed:
            ui.show_error(self.window, label, text, self.theme)

    def model_open(self):
        """The model this window was opened for may have been closed in
        Revit while the window sat open."""
        try:
            alive = bool(self.doc.IsValidObject)
        except Exception:
            alive = False
        if alive:
            return True
        self.tell(u"Model Cleanup", u"The model this window was opened for has been "
                                    u"closed in Revit, so the window closes too.")
        self.close_decided = True
        self.window.Close()
        return False

    def active_is(self, uiapp, doc):
        try:
            return model.same_document(uiapp.ActiveUIDocument.Document, doc)
        except Exception:
            return False

    def start_watchdog(self):
        self.stop_watchdog()
        timer = DispatcherTimer()
        timer.Interval = TimeSpan.FromSeconds(2)
        timer.Tick += ui.safe_handler(self.window, self.on_watchdog, self.theme)
        self.watchdog = timer
        timer.Start()

    def stop_watchdog(self):
        if self.watchdog is not None:
            try:
                self.watchdog.Stop()
            except Exception:
                pass
        self.watchdog = None

    def on_watchdog(self, sender, args):
        if not self.queued_label:
            self.stop_watchdog()
            return
        self.set_status(core.waiting_note(time.time() - self.queued_at))

    def cancel_queued(self):
        label = self.queued_label
        if not label:
            return False
        self.runner.cancel(label)
        self.queued_label = None
        self.stop_watchdog()
        self.set_deaf(False)
        self.set_status(u"{0} cancelled before Revit picked it up.".format(label))
        self.log(u"{0} cancelled while waiting for Revit.".format(label))
        return True

    def set_deaf(self, deaf):
        for name in DEAF_NAMES:
            try:
                self.find(name).IsHitTestVisible = not deaf
            except Exception:
                pass

    def file_dialog(self, dialog):
        """A Windows file dialog only disables its owner, unlike the themed
        prompts. Inside a job Revit is still in the middle of the job's API
        call, so it is switched off for as long as the dialog is up."""
        in_job = self.runner.running is not None
        was = self.revit_locked
        if in_job:
            self.lock_revit(True)
        try:
            return bool(dialog.ShowDialog(self.window))
        finally:
            if in_job and not was:
                self.lock_revit(False)

    def lock_revit(self, locked):
        if bool(locked) == self.revit_locked:
            return
        if ui.set_revit_enabled(self.revit_window, not locked):
            self.revit_locked = bool(locked)
        elif not locked:
            self.revit_locked = False

    def set_status(self, text):
        self.find(u"StatusText").Text = core.to_text(text)

    def log(self, text):
        box = self.find(u"LogBox")
        stamp = datetime.datetime.now().strftime(u"%H:%M:%S")
        box.AppendText(u"{0}  {1}\n".format(stamp, core.to_text(text)))
        box.ScrollToEnd()
        core.log(text)

    def ask(self, title, message, yes_label, style=u"GreenButton"):
        return ui.prompt(self.window, title, message,
                         [(u"Cancel", False, u"BaseButton"), (yes_label, True, style)],
                         self.theme)

    def tell(self, title, message):
        ui.prompt(self.window, title, message, [(u"OK", True, u"BaseButton")], self.theme)

    def begin_busy(self, text):
        self.busy = True
        self.set_deaf(True)
        self.lock_revit(True)
        self.set_status(text)
        self.refresh_steps()
        self.progress.begin(text)

    def end_busy(self, text, state=u"ok"):
        self.busy = False
        self.set_deaf(False)
        self.lock_revit(False)
        self.progress.finish(text, state)
        self.set_status(text)
        self.refresh_steps()
        # a sync, open or save can hand focus back to Revit - come back up
        ui.bring_to_front(self.window)

    # ------------------------------------------------------------
    def fill_model_card(self):
        info = self.info
        find = self.find
        find(u"ModelNameText").Text = info[u"title"] or u"(untitled)"
        find(u"ModelPathText").Text = info[u"central"] or info[u"path"] or u"Not saved yet"
        find(u"ModelPathText").ToolTip = find(u"ModelPathText").Text
        if info[u"workshared"]:
            kind = u"Workshared, cloud model" if info[u"cloud"] else u"Workshared model"
        else:
            kind = u"Not workshared - step 1 saves it"
        find(u"ModelKindText").Text = kind
        find(u"SyncTitle").Text = core.sync_label(info[u"workshared"])
        if not info[u"workshared"]:
            find(u"SyncSub").Text = u"Save the model so the copy carries the latest work."
            find(u"SyncCommentBox").IsEnabled = False
            find(u"RelinquishCheck").IsEnabled = False

    def load_templates(self, wanted):
        names = core.list_templates()
        combo = self.find(u"TemplateCombo")
        combo.Items.Clear()
        for name in names:
            combo.Items.Add(name)
        chosen = core.pick_template(names, wanted)
        combo.SelectedItem = chosen
        self.apply_template(chosen)

    def apply_template(self, name):
        self.template_name = name
        self.template = core.load_template(name)
        self.settings[u"last_template"] = name
        core.save_global(self.settings)
        find = self.find
        find(u"SyncCommentBox").Text = self.template.get(u"sync_comment", u"")
        find(u"RelinquishCheck").IsChecked = core.as_bool(self.template.get(u"relinquish"), True)
        preserve = self.template.get(u"detach_mode") != core.DETACH_DISCARD
        if self.info[u"workshared"]:
            detach = (u"Detach and preserve worksets" if preserve
                      else u"Detach and discard worksets")
        else:
            detach = u"Copy of the saved file"
        if core.as_bool(self.template.get(u"audit")):
            detach += u", audit"
        if core.as_bool(self.template.get(u"compact"), True):
            detach += u", compact"
        find(u"DetachText").Text = detach
        ops_on = core.enabled_ops(self.template)
        find(u"TemplateSummaryText").Text = u"{0} of {1} clean up actions on".format(
            len(ops_on), len(core.CLEANUP_OPS))
        if not self.saved_as:
            find(u"TargetPathBox").Text = self.suggest_path()
        self.fill_plan(None)

    def suggest_path(self):
        folder = self.settings.get(u"last_folder") or u""
        if not folder or not os.path.isdir(folder):
            try:
                path = self.info[u"path"]
                folder = os.path.dirname(path) if path and not self.info[u"cloud"] else u""
            except Exception:
                folder = u""
        if not folder:
            folder = os.path.join(os.path.expanduser(u"~"), u"Documents")
        user = self.username or None
        source = self.info[u"central"] or self.info[u"path"] or self.info[u"title"]
        name = core.send_file_name(source, core.active_suffix(self.template),
                                   core.as_bool(self.template.get(u"add_date"), True),
                                   user_name=user)
        return os.path.join(folder, name)

    def fill_plan(self, counts):
        panel = self.find(u"PlanPanel")
        panel.Children.Clear()
        for key, label in core.CLEANUP_OPS:
            on = core.as_bool(self.template.get(key))
            row = Grid()
            row.Margin = Thickness(0, 2, 0, 2)
            first = ColumnDefinition()
            second = ColumnDefinition()
            second.Width = self._auto_width()
            row.ColumnDefinitions.Add(first)
            row.ColumnDefinitions.Add(second)
            name = TextBlock()
            name.Text = label
            name.TextWrapping = TextWrapping.Wrap
            value = TextBlock()
            value.Margin = Thickness(10, 0, 0, 0)
            if not on:
                name.SetResourceReference(TextBlock.ForegroundProperty, u"MutedBrush")
                value.Text = u"off"
                value.SetResourceReference(TextBlock.ForegroundProperty, u"MutedBrush")
            elif counts is None or key not in counts:
                value.Text = u"on"
                value.SetResourceReference(TextBlock.ForegroundProperty, u"BlueBrush")
            else:
                value.Text = u"{0}".format(counts[key])
                brush = u"OrangeBrush" if counts[key] else u"GreenBrush"
                value.SetResourceReference(TextBlock.ForegroundProperty, brush)
            Grid.SetColumn(value, 1)
            row.Children.Add(name)
            row.Children.Add(value)
            panel.Children.Add(row)
        left_out = core.split_list(self.template.get(u"purge_exclude"))
        if left_out and core.as_bool(self.template.get(u"purge")):
            note = TextBlock()
            note.Text = u"{0} purge categories left out".format(len(left_out))
            note.SetResourceReference(TextBlock.ForegroundProperty, u"MutedBrush")
            note.Margin = Thickness(0, 6, 0, 0)
            panel.Children.Add(note)

    def _auto_width(self):
        return GridLength.Auto

    # ------------------------------------------------------------
    def refresh_steps(self):
        alive = self.target_doc is not None and self._target_alive()
        synced, saved_as = core.effective_steps(self.synced, self.saved_as, self.skipped)
        states = core.step_states(synced, saved_as, self.cleaned, self.busy, alive)
        if self.skipped:
            states[core.STEP_SYNC] = False
            states[core.STEP_SAVE_AS] = False
        self._paint_step(u"Sync", states[core.STEP_SYNC], self.synced, False, self.skipped)
        self._paint_step(u"SaveAs", states[core.STEP_SAVE_AS], self.saved_as, False, self.skipped)
        self.find(u"SkipButton").IsEnabled = core.can_skip(
            self.synced, self.saved_as, self.skipped, self.cleaned, self.busy)
        self._paint_step(u"Cleanup", states[core.STEP_CLEANUP], self.cleaned, True)
        self.find(u"BrowseButton").IsEnabled = not self.saved_as and not self.busy
        self.find(u"TargetPathBox").IsEnabled = not self.saved_as and not self.busy
        self.find(u"TemplateCombo").IsEnabled = not self.busy and not self.cleaned
        self.find(u"ExportSettingsButton").IsEnabled = not self.busy and not self.cleaned
        self.find(u"ScanButton").IsEnabled = not self.busy
        publishable = self.info[u"cloud"] and self.info[u"workshared"]
        self.find(u"PublishRow").Visibility = (Visibility.Visible if publishable
                                               else Visibility.Collapsed)
        self.find(u"PublishButton").IsEnabled = (
            not self.busy and aps.can_publish(self.info, self.synced) is None)
        close = self.find(u"FooterCloseButton")
        if self.cleaned and self.open_after:
            close.Content = u"Close and open the cleaned copy"
            close.SetResourceReference(FrameworkElement.StyleProperty, u"GreenButton")
        else:
            close.Content = u"Close"

    def _paint_step(self, prefix, enabled, done, lights_up, skipped=False):
        button = self.find(prefix + u"Button")
        badge = self.find(prefix + u"Badge")
        number = self.find(prefix + u"Number")
        number_text = self.find(prefix + u"NumberText")
        title = self.find(prefix + u"Title")
        sub = self.find(prefix + u"Sub")
        button.IsEnabled = bool(enabled)
        badge.Text = core.step_badge(enabled, done, skipped)
        if skipped:
            button.SetResourceReference(Control.BackgroundProperty, u"OrangeSoftBrush")
            button.SetResourceReference(Control.BorderBrushProperty, u"OrangeBrush")
            number.SetResourceReference(Border.BackgroundProperty, u"OrangeBrush")
            number_text.SetResourceReference(TextBlock.ForegroundProperty, u"OnAccentBrush")
            badge.SetResourceReference(TextBlock.ForegroundProperty, u"OrangeBrush")
            title.SetResourceReference(TextBlock.ForegroundProperty, u"MutedBrush")
            sub.SetResourceReference(TextBlock.ForegroundProperty, u"MutedBrush")
        elif done:
            button.SetResourceReference(Control.BackgroundProperty, u"GreenSoftBrush")
            button.SetResourceReference(Control.BorderBrushProperty, u"GreenBrush")
            number.SetResourceReference(Border.BackgroundProperty, u"GreenBrush")
            badge.SetResourceReference(TextBlock.ForegroundProperty, u"GreenBrush")
            title.SetResourceReference(TextBlock.ForegroundProperty, u"TextBrush")
            sub.SetResourceReference(TextBlock.ForegroundProperty, u"MutedBrush")
            number_text.SetResourceReference(TextBlock.ForegroundProperty, u"OnAccentBrush")
        elif enabled and lights_up:
            # Clean Up illuminates only once both earlier steps are done
            button.SetResourceReference(Control.BackgroundProperty, u"GreenBrush")
            button.SetResourceReference(Control.BorderBrushProperty, u"GreenHoverBrush")
            number.SetResourceReference(Border.BackgroundProperty, u"OnAccentBrush")
            number_text.SetResourceReference(TextBlock.ForegroundProperty, u"GreenBrush")
            for block in (badge, title, sub):
                block.SetResourceReference(TextBlock.ForegroundProperty, u"OnAccentBrush")
        elif enabled:
            button.SetResourceReference(Control.BackgroundProperty, u"BlueSoftBrush")
            button.SetResourceReference(Control.BorderBrushProperty, u"BlueBrush")
            number.SetResourceReference(Border.BackgroundProperty, u"BlueBrush")
            number_text.SetResourceReference(TextBlock.ForegroundProperty, u"OnAccentBrush")
            badge.SetResourceReference(TextBlock.ForegroundProperty, u"BlueBrush")
            title.SetResourceReference(TextBlock.ForegroundProperty, u"TextBrush")
            sub.SetResourceReference(TextBlock.ForegroundProperty, u"MutedBrush")
        else:
            button.SetResourceReference(Control.BackgroundProperty, u"LockedBrush")
            button.SetResourceReference(Control.BorderBrushProperty, u"EdgeBrush")
            number.SetResourceReference(Border.BackgroundProperty, u"EdgeBrush")
            number_text.SetResourceReference(TextBlock.ForegroundProperty, u"MutedBrush")
            badge.SetResourceReference(TextBlock.ForegroundProperty, u"MutedBrush")
            title.SetResourceReference(TextBlock.ForegroundProperty, u"MutedBrush")
            sub.SetResourceReference(TextBlock.ForegroundProperty, u"MutedBrush")

    def _target_alive(self):
        try:
            return bool(self.target_doc.IsValidObject)
        except Exception:
            return False

    # ============================================================
    # step 1
    # ============================================================
    def on_sync(self, sender, args):
        if self.busy:
            return
        workshared = self.info[u"workshared"]
        comment = core.to_text(self.find(u"SyncCommentBox").Text)
        relinquish = bool(self.find(u"RelinquishCheck").IsChecked)
        self.begin_busy(u"Syncing with central..." if workshared else u"Saving...")
        self.progress.update(0.05, u"Syncing with central (Revit is busy - the bar moves when it returns)"
                             if workshared else u"Saving (Revit is busy)")
        try:
            ok, message = ops.sync_current(
                self.uiapp, self.doc, comment, relinquish,
                core.as_bool(self.template.get(u"compact"), True))
        except Exception:
            self.debug.exception(u"step 1", core.format_exception())
            self.end_busy(u"Step 1 failed - see the log", u"fail")
            self.log(u"Step 1 failed: " + core.format_exception())
            raise
        self.debug_step(u"Step 1", [(u"ok", ok), (u"message", message),
                                    (u"comment", comment), (u"relinquish", relinquish)])
        if ok:
            self.synced = True
            self.log(message)
            self.end_busy(u"Step 1 done. Step 2 is ready.")
            self.offer_publish_after_sync()
        else:
            self.log(message)
            self.end_busy(message, u"fail")
            self.tell(u"Step 1", message)

    # ============================================================
    # debug report
    # ============================================================
    def start_debug(self):
        if self.debug.enabled:
            return
        self.debug = core.DebugReport(True)
        self.debug.section(u"Session")
        self.debug.values(self.environment)
        self.debug.values([(u"Template", self.template_name),
                           (u"Theme mode", self.settings.get(u"theme_mode")),
                           (u"APS client id set", bool(self.client_id())),
                           (u"Owned by Revit's window", self.owned),
                           (u"Window", u"modeless"),
                           (u"Tool folder", ui.HERE)])
        self.debug.flush()
        self.log(u"Debug report: " + self.debug.path)
        self.find(u"OpenDebugButton").Visibility = Visibility.Visible

    def debug_step(self, title, pairs):
        if self.debug.enabled:
            self.debug.section(title)
            self.debug.values(pairs)
            self.debug.flush()

    def on_debug_toggled(self, sender, args):
        on = bool(self.find(u"DebugCheck").IsChecked)
        self.settings[u"debug"] = core.bool_text(on)
        core.save_global(self.settings)
        if on:
            self.start_debug()
            self.set_status(u"Debug report on: " + self.debug.path)
        else:
            self.debug.flush()
            self.set_status(u"Debug report off. The report so far stays in its file.")

    def on_open_debug(self, sender, args):
        import subprocess
        self.debug.flush()
        path = self.debug.path
        try:
            subprocess.Popen([u"explorer.exe", u"/select,", path])
        except Exception:
            self.tell(u"Debug report", u"The report is here:\n" + path)
            return
        self.set_status(u"Send this file: " + path)

    # ============================================================
    # skipping steps 1 and 2
    # ============================================================
    def on_skip(self, sender, args):
        if self.is_occupied() or not core.can_skip(self.synced, self.saved_as, self.skipped,
                                                   self.cleaned, self.busy):
            return
        answer, typed = ui.prompt(
            self.window, u"Skip steps 1 and 2 - not for central models",
            core.skip_warning(self.info),
            [(u"Cancel", False, u"BaseButton"),
             (u"Skip steps 1 and 2", True, u"RedGhostButton")],
            self.theme, input_text=u"", input_hint=u"Type " + core.CONFIRM_WORD)
        if not answer:
            return
        if not core.confirm_typed(typed):
            self.tell(u"Skip steps 1 and 2",
                      u"Nothing was skipped. The box has to read {0} exactly, in capitals."
                      .format(core.CONFIRM_WORD))
            return
        self.skipped = True
        self.target_doc = self.doc
        self.target_is_active = True
        self.target_path = self.info[u"path"] or self.info[u"title"]
        self.find(u"CleanupTargetText").Text = (
            u"Will clean the OPEN model: {0}. It will not be saved or synced."
            .format(self.info[u"title"]))
        self.find(u"CleanupTargetText").SetResourceReference(
            TextBlock.ForegroundProperty, u"RedBrush")
        self.debug_step(u"Steps 1 and 2 skipped", [(u"model", self.info[u"title"]),
                                                   (u"workshared", self.info[u"workshared"]),
                                                   (u"central", self.info[u"central"])])
        self.log(u"Steps 1 and 2 skipped (typed {0}). Clean Up will run on the open model "
                 u"{1} and will not save it.".format(core.CONFIRM_WORD, self.info[u"title"]))
        self.set_status(u"Steps 1 and 2 skipped. Clean Up runs on the open model.")
        self.refresh_steps()

    # ============================================================
    # publish to ACC (after step 1)
    # ============================================================
    def client_id(self):
        return core.to_text(self.settings.get(u"aps_client_id")).strip()

    def port(self):
        return core.as_int(self.settings.get(u"aps_port"), aps.DEFAULT_PORT, 1024, 65535)

    def offer_publish_after_sync(self):
        if aps.can_publish(self.info, self.synced) is not None:
            return
        if not core.as_bool(self.template.get(u"offer_publish"), True):
            return
        if not self.client_id():
            self.log(u"Publish to ACC is ready to use once an APS app is set up "
                     u"(Export Settings > Publish to ACC).")
            return
        choice = self.ask_links(offer=True)
        if choice is not None:
            self.run_publish(choice)

    def ask_links(self, offer=False):
        """True with links, False without, None to leave it."""
        fixed = aps.normalise_links(self.template.get(u"publish_links"))
        intro = (u"The model is synced. Publish the latest version on ACC now?\n\n"
                 if offer else u"Publish the latest synced version on ACC.\n\n")
        if fixed == aps.LINKS_WITH:
            answer = ui.prompt(self.window, u"Publish to ACC",
                               intro + u"The template publishes with links.",
                               [(u"Not now", None, u"BaseButton"),
                                (u"Publish with links", True, u"GreenButton")], self.theme)
            return answer
        if fixed == aps.LINKS_WITHOUT:
            answer = ui.prompt(self.window, u"Publish to ACC",
                               intro + u"The template publishes without links.",
                               [(u"Not now", None, u"BaseButton"),
                                (u"Publish without links", False, u"GreenButton")], self.theme)
            return answer
        return ui.prompt(
            self.window, u"Publish to ACC",
            intro + u"With links, ACC publishes the model together with the Revit "
                    u"links it carries. Without links is quicker and publishes this "
                    u"model on its own.",
            [(u"Not now", None, u"BaseButton"),
             (u"Publish without links", False, u"OrangeButton"),
             (u"Publish with links", True, u"GreenButton")], self.theme)

    def on_publish(self, sender, args):
        reason = aps.can_publish(self.info, self.synced)
        if reason:
            self.tell(u"Publish to ACC", reason)
            return
        if not self.client_id():
            answer = ui.prompt(
                self.window, u"Publish to ACC",
                aps.SETUP_HELP.format(callback=aps.callback_url(self.port())),
                [(u"Close", False, u"BaseButton"),
                 (u"Open Export Settings", True, u"OrangeButton")], self.theme)
            if answer:
                self.open_settings()
            return
        choice = self.ask_links()
        if choice is not None:
            self.run_publish(choice)

    def _tick(self):
        ui.pump(self.window)
        if self.cancel_requested:
            raise PublishCancelled()

    def run_publish(self, with_links):
        try:
            import mcu_web as web
        except Exception:
            self.tell(u"Publish to ACC", u"The publishing module could not load on this "
                                         u"Revit:\n\n" + core.format_exception()[-800:])
            return
        label = u"with links" if with_links else u"without links"
        self.cancel_requested = False
        self.begin_busy(u"Publishing to ACC " + label)
        try:
            self.progress.update(0.05, u"Signing in to Autodesk (a browser opens the first "
                                       u"time - press Escape to cancel)")
            token = web.get_token(self.client_id(), self.port(), self._tick)
            ui.bring_to_front(self.window)
            self.progress.update(0.35, u"Finding this model on ACC")
            project, item = web.resolve_item(self.doc, token)
            self.progress.update(0.55, u"Checking whether a publish is already running")
            state, status = web.job_state(token, project, item)
            if state == aps.JOB_RUNNING:
                self.log(u"ACC is already publishing this model ({0}).".format(status))
                self.end_busy(u"ACC is already publishing this model", u"warn")
                self.start_publish_poll(project, item)
                return
            self.progress.update(0.75, u"Asking ACC to publish " + label)
            sent, code = web.publish(token, project, item, with_links)
            if not sent and code == 401:
                web.forget()
                self.progress.update(0.8, u"Sign-in expired - signing in again")
                token = web.get_token(self.client_id(), self.port(), self._tick)
                sent, code = web.publish(token, project, item, with_links)
                if not sent:
                    raise web.PublishError(aps.explain_status(401, u""))
        except PublishCancelled:
            self.log(u"Publish cancelled.")
            self.end_busy(u"Publish cancelled", u"warn")
            return
        except web.PublishError as error:
            message = core.to_text(error)
            self.debug_step(u"Publish failed", [(u"links", label), (u"message", message)])
            self.log(u"Publish failed: " + message.splitlines()[0])
            self.end_busy(u"Publish to ACC failed", u"fail")
            self.tell(u"Publish to ACC", message)
            return
        except Exception:
            self.end_busy(u"Publish to ACC failed", u"fail")
            raise
        self.log(u"ACC accepted the publish request ({0}, HTTP {1}).".format(label, code))
        self.debug_step(u"Publish", [(u"links", label), (u"http", code),
                                     (u"project", project), (u"item", item)])
        self.end_busy(u"Publish requested on ACC " + label)
        self.start_publish_poll(project, item)

    def start_publish_poll(self, project, item):
        self.stop_publish_poll()
        self.publish_target = (project, item)
        self.publish_started = time.time()
        self.find(u"PublishStatusText").Text = u"Waiting for ACC..."
        timer = DispatcherTimer()
        timer.Interval = TimeSpan.FromSeconds(10)
        timer.Tick += ui.safe_handler(self.window, self.on_publish_poll, self.theme)
        self.publish_timer = timer
        timer.Start()

    def stop_publish_poll(self):
        if self.publish_timer is not None:
            try:
                self.publish_timer.Stop()
            except Exception:
                pass
        self.publish_timer = None

    def on_publish_poll(self, sender, args):
        """ACC publishes in the cloud and reports no percentage, only a
        status. The window stays usable while this checks every 10 s."""
        if self.busy or self.publish_target is None:
            return
        import mcu_web as web
        elapsed = time.time() - self.publish_started
        text_block = self.find(u"PublishStatusText")
        try:
            token = web.get_token(self.client_id(), self.port(), self._tick, allow_browser=False)
            if token is None:
                text_block.Text = u"Sign-in expired - check the publish on ACC."
                self.stop_publish_poll()
                return
            project, item = self.publish_target
            state, status = web.job_state(token, project, item)
        except Exception as error:
            # a dropped connection must stop the timer, not stack a dialog
            # every ten seconds
            self.stop_publish_poll()
            text_block.Text = u"Stopped watching the publish: " + core.to_text(error).splitlines()[0]
            text_block.SetResourceReference(TextBlock.ForegroundProperty, u"OrangeBrush")
            self.log(u"Publish status check failed: " + core.to_text(error))
            return
        text_block.Text = aps.job_line(state, status, core.format_clock(elapsed))
        brush = {aps.JOB_DONE: u"GreenBrush", aps.JOB_FAILED: u"RedBrush"}.get(state, u"OrangeBrush")
        text_block.SetResourceReference(TextBlock.ForegroundProperty, brush)
        if aps.poll_should_stop(state, elapsed):
            self.stop_publish_poll()
            if state == aps.JOB_DONE:
                self.log(u"ACC finished publishing after " + core.format_duration(elapsed) + u".")
            elif state == aps.JOB_FAILED:
                self.log(u"ACC reports the publish failed - check the model on ACC.")
            else:
                self.log(u"Stopped watching the publish after 15 minutes; ACC is still working on it.")

    # ============================================================
    # step 2
    # ============================================================
    def on_browse(self, sender, args):
        box = self.find(u"TargetPathBox")
        current = core.to_text(box.Text)
        dialog = SaveFileDialog()
        dialog.Title = u"Save the send copy as"
        dialog.Filter = u"Revit project (*.rvt)|*.rvt"
        dialog.DefaultExt = u".rvt"
        dialog.AddExtension = True
        dialog.OverwritePrompt = True
        if current:
            folder = os.path.dirname(current)
            if os.path.isdir(folder):
                dialog.InitialDirectory = folder
            dialog.FileName = os.path.basename(current)
        if self.file_dialog(dialog):
            box.Text = dialog.FileName
            self.settings[u"last_folder"] = os.path.dirname(dialog.FileName)
            core.save_global(self.settings)

    def protected_paths(self):
        paths = [self.info[u"path"]]
        if self.info[u"central"] and not self.info[u"cloud"]:
            paths.append(self.info[u"central"])
        return paths

    def on_save_as(self, sender, args):
        if self.busy or not self.synced:
            return
        target = core.to_text(self.find(u"TargetPathBox").Text).strip()
        problem = core.check_target_path(target, self.protected_paths())
        if problem:
            self.tell(u"Save As", problem)
            return
        route = core.save_as_route(self.info)
        message = core.save_as_confirmation(self.info, target, self.template.get(u"detach_mode"))
        if ops.target_exists(target):
            message += u"\n\nA file with that name already exists and will be replaced."
        if not self.ask(u"Save As Detached Copy", message, u"Save the detached copy"):
            return
        copy = None
        if route == core.ROUTE_SAVE_OPEN:
            self.begin_busy(u"Saving the open ACC model as the detached copy...")
            try:
                self.progress.update(0.1, u"Saving the open model as the detached copy (Revit is busy)")
                ops.save_active_as_copy(self.uiapp, self.doc, target, self.template)
            except Exception:
                self.debug.exception(u"step 2 (save the open model)", core.format_exception())
                self.end_busy(u"Save As failed - see the log", u"fail")
                raise
            self.target_is_active = True
            copy = self.doc
        else:
            self.begin_busy(u"Opening a detached copy and saving it...")
            try:
                self.progress.update(0.05, u"Opening the central detached (Revit is busy)")
                copy = ops.open_detached_copy(
                    self.uiapp, self.doc, target, self.template,
                    lambda label, fraction: self.progress.update(fraction, label))
            except ops.SaveAsFailed as error:
                # it opened; it was the save that failed, and saving the live
                # model to the same place would fail for the same reason
                self.debug.exception(u"step 2 (saving the detached copy)", core.format_exception())
                self.end_busy(u"The detached copy could not be saved", u"fail")
                self.tell(u"Save As Detached Copy",
                          u"Revit opened the detached copy but could not save it to\n{0}\n\n{1}"
                          u"\n\nCheck the folder exists and is writable and the file is not open "
                          u"elsewhere, then try again. The copy has been closed.".format(
                              target, core.to_text(error)))
                return
            except Exception:
                detail = core.format_exception()
                self.debug.exception(u"step 2 (detached copy)", detail)
                self.log(u"Detached copy failed: " + detail.strip().splitlines()[-1])
                core.log(detail)
            if copy is None:
                self.end_busy(u"Revit would not open a detached copy", u"fail")
                copy = self._offer_fallback(target)
                if copy is None:
                    return
                self.begin_busy(u"Saving the open model as the detached copy...")
        self.target_doc = copy
        self.target_path = target
        self.saved_as = True
        self.settings[u"last_folder"] = os.path.dirname(target)
        core.save_global(self.settings)
        self.find(u"CleanupTargetText").Text = u"Will clean the detached copy: " + target
        self.find(u"SaveAsSub").Text = u"The detached copy is saved. Everything from here works on it."
        self.log(u"Detached copy saved: " + target)
        self.debug_step(u"Step 2", [(u"target", target), (u"route", route),
                                    (u"working in the open model", self.target_is_active),
                                    (u"detach", self.template.get(u"detach_mode"))])
        self.end_busy(u"Step 2 done. Clean Up is ready.")

    def _offer_fallback(self, target):
        if not self.info[u"workshared"]:
            self.tell(u"Save As", u"Revit would not open the copied file. The log has the reason.")
            return None
        if self.template.get(u"detach_mode") == core.DETACH_DISCARD:
            self.tell(u"Save As",
                      u"Revit would not open the central a second time, and discarding "
                      u"worksets needs that. Close other copies of this model and try again, "
                      u"or switch the template to preserve worksets.")
            return None
        message = (u"Revit would not open the central a second time.\n\n"
                   u"The open model can be saved as the detached copy instead. It has just "
                   u"been synced, so nothing is lost. The saved file is the detached model, "
                   u"and this session will then be working in it, not the live model.\n\n"
                   u"Save the open model as\n{0}?").format(target)
        if not self.ask(u"Save As Detached Copy", message, u"Save the open model as the copy",
                        u"OrangeButton"):
            return None
        self.begin_busy(u"Saving the open model as the send copy...")
        try:
            self.progress.update(0.1, u"Saving the open model as the copy (Revit is busy)")
            ops.save_active_as_copy(self.uiapp, self.doc, target, self.template)
        except Exception:
            self.end_busy(u"Save As failed - see the log", u"fail")
            raise
        self.target_is_active = True
        self.busy = False
        return self.doc

    # ============================================================
    # step 3
    # ============================================================
    def on_cleanup(self, sender, args):
        if self.busy or not ((self.synced and self.saved_as) or self.skipped) or self.cleaned:
            return
        if self.target_doc is None or not self._target_alive():
            self.tell(u"Clean Up", u"The saved copy is no longer open. Run step 2 again.")
            return
        if self.target_is_active and not self.active_is(self.uiapp, self.target_doc):
            self.tell(u"Clean Up", u"Switch Revit back to {0} - the model this clean up runs "
                                   u"in - then press Clean Up again.".format(self.info[u"title"]))
            return
        warnings = core.retention_warnings(self.template)
        if warnings:
            answer = ui.prompt(
                self.window, u"Clean Up - retained views and sheets",
                core.retention_message(self.template, warnings) +
                u"\n\nTurn the missing delete stages on for this template?",
                [(u"Cancel", None, u"BaseButton"),
                 (u"Run as it is", False, u"OrangeButton"),
                 (u"Turn them on and run", True, u"GreenButton")], self.theme)
            if answer is None:
                return
            if answer:
                self.template = core.fix_retention(self.template, warnings)
                core.save_template(self.template_name, self.template)
                self.fill_plan(None)
                self.log(u"Turned on: " + core.retention_message(self.template, warnings))
            self.debug_step(u"Retention warning", [(u"warnings", u", ".join(warnings)),
                                                   (u"answer", answer)])
        nwc_on = core.as_bool(self.template.get(u"export_nwc"))
        if nwc_on:
            nwc_problems = nwc.problems(self.template, model.nwc_available())
            if nwc_problems:
                answer = ui.prompt(
                    self.window, u"Clean Up - NWC export",
                    u"\n".join(nwc_problems) + u"\n\nClean up without exporting NWC?",
                    [(u"Cancel", None, u"BaseButton"),
                     (u"Clean up without NWC", True, u"OrangeButton")], self.theme)
                if not answer:
                    return
                nwc_on = False
        ops_on = [op for op in core.enabled_ops(self.template)
                  if op[0] != u"export_nwc" or nwc_on]
        if not ops_on:
            self.tell(u"Clean Up", u"The template has every clean up action switched off.")
            return
        nwc_folder, nwc_stem = u"", u""
        if nwc_on:
            nwc_folder, nwc_stem = self.nwc_destination()
            if not nwc_folder:
                return
        active_id = 0
        uidoc = None
        if self.target_is_active:
            uidoc = self.uiapp.ActiveUIDocument
            try:
                active_id = core.eid_value(uidoc.ActiveView.Id)
            except Exception:
                active_id = 0
        try:
            counts = model.plan_counts(self.target_doc, self.template, 0)
        except Exception:
            counts = {}
            self.debug.exception(u"counting before Clean Up", core.format_exception())
        lines = []
        for key, label in ops_on:
            if key == u"export_nwc":
                views, primary = nwc.selection(self.template)
                names = nwc.file_names(nwc_stem, views, primary)
                lines.append(u"  - Export NWC first, to {0}:".format(nwc_folder))
                lines.extend(u"      {0}.nwc   ({1}{2})".format(
                    f, v, u", primary" if v == primary else u"") for v, f in names)
                continue
            if key == u"purge":
                lines.append(u"  - {0}: up to {1} passes".format(
                    label, core.as_int(self.template.get(u"purge_passes"), 4, 1, 10)))
            elif key in counts:
                lines.append(u"  - {0}: {1}".format(label, counts[key]))
            else:
                lines.append(u"  - " + label)
        kept = counts.get(u"_kept") or []
        if kept:
            lines.append(u"")
            lines.append(u"Staying:")
            lines.extend(u"  - " + line for line in kept)
        lines = u"\n".join(lines)
        if self.skipped:
            message = (u"Steps 1 and 2 were skipped. This runs on the OPEN model:\n{0}\n\n"
                       u"{1}\n\nIf the open view is going, a retained one is opened first "
                       u"and the old one closed.\nIt will not be saved or synced. Never a "
                       u"central model.").format(self.info[u"title"], lines)
        else:
            message = (u"This runs on the saved copy only:\n{0}\n\n{1}\n\n"
                       u"The live model is not touched.").format(self.target_path, lines)
        self.debug_step(u"Clean Up asked", [(u"counts", counts)])
        if not self.ask(u"Clean Up", message, u"Clean Up"):
            return
        self.begin_busy(u"Cleaning...")
        run_template = dict(self.template)
        run_template[u"export_nwc"] = core.bool_text(nwc_on)
        if nwc_on and not self.export_nwc_phase(run_template, nwc_folder, nwc_stem):
            return
        try:
            report = ops.run_cleanup(self.uiapp, self.target_doc, run_template,
                                     active_id, self._on_step, save=not self.skipped,
                                     uidoc=uidoc, debug=self.debug)
        except Exception:
            self.debug.exception(u"Clean Up", core.format_exception())
            stopped = (u"Clean Up failed - nothing was removed" if not self._target_modified()
                       else u"Clean Up failed part way - see the log before saving")
            self.end_busy(stopped, u"fail")
            self.log(u"Clean Up failed: " + core.format_exception().strip().splitlines()[-1])
            raise
        for line in report.lines:
            self.log(line)
        self.cleaned = True
        self.run_saved = bool(getattr(report, u"saved", False))
        if core.as_bool(self.template.get(u"open_when_done"), True) and not self.target_is_active:
            self.open_after = self.target_path
        result = u"{0} elements removed".format(report.total())
        if report.kept():
            result += u", {0} views kept because a view that stays depends on them".format(
                report.kept())
        if report.refused():
            result += u", {0} refused (listed in the log)".format(report.refused())
            self.find(u"CleanupResultText").SetResourceReference(
                TextBlock.ForegroundProperty, u"OrangeBrush")
        else:
            self.find(u"CleanupResultText").SetResourceReference(
                TextBlock.ForegroundProperty, u"GreenBrush")
        self.find(u"CleanupResultText").Text = result
        if self.debug.enabled:
            result += u". Debug report written"
        self.end_busy(u"Clean Up done. " + result + u".",
                      u"warn" if report.refused() else u"ok")

    def nwc_destination(self):
        """(folder, model name) for the NWC files: the detached copy's folder.
        An ACC or never-saved model has no folder, so ask for one."""
        path = self.target_path if not self.skipped else self.info[u"path"]
        folder = core.folder_of(path)
        stem = core.model_stem(path or self.info[u"title"])
        if folder and os.path.isdir(folder):
            return folder, stem
        views, primary = nwc.selection(self.template)
        dialog = SaveFileDialog()
        dialog.Title = u"Where should the NWC files go? (name of the primary file)"
        dialog.Filter = u"Navisworks cache (*.nwc)|*.nwc"
        dialog.DefaultExt = u".nwc"
        dialog.FileName = nwc.file_names(stem, views, primary)[0][1] + u".nwc" if views else stem + u".nwc"
        if not self.file_dialog(dialog):
            return u"", u""
        chosen = dialog.FileName
        return os.path.dirname(chosen), core.model_stem(chosen)

    def export_nwc_phase(self, template, folder, stem):
        """The NWC export, before anything is removed. False stops Clean Up."""
        save = not self.skipped
        keys = [k for k, _ in core.enabled_ops(template)] + ([u"save"] if save else [])
        plan = core.stage_plan(keys)

        def progress(local, label):
            self.progress.update(core.plan_fraction(plan, u"export_nwc", local), label)
        try:
            written, failures = ops.export_nwc(self.uiapp, self.target_doc, template,
                                               folder, stem, progress, self.debug)
        except Exception:
            self.debug.exception(u"NWC export", core.format_exception())
            self.end_busy(u"NWC export failed - nothing was removed", u"fail")
            raise
        for view, path in written:
            self.log(u"NWC written: {0}  ({1})".format(path, view))
        for view, reason in failures:
            self.log(u"NWC not written for {0}: {1}".format(view, reason))
        if not failures:
            return True
        answer = ui.prompt(
            self.window, u"NWC export",
            u"{0} of {1} NWC file(s) were written.\n\nNot written:\n{2}\n\n"
            u"Carry on with the clean up?".format(
                len(written), len(written) + len(failures),
                u"\n".join(u"  - {0}: {1}".format(v, r) for v, r in failures)),
            [(u"Stop here", False, u"BaseButton"),
             (u"Carry on", True, u"OrangeButton")], self.theme)
        if not answer:
            self.end_busy(u"Stopped after the NWC export - nothing was removed", u"warn")
            return False
        return True

    def _on_step(self, label, fraction):
        self.progress.update(fraction, label)

    def _target_modified(self):
        try:
            return bool(self.target_doc.IsModified)
        except Exception:
            return True

    # ============================================================
    # template, settings, scan
    # ============================================================
    def on_template_changed(self, sender, args):
        chosen = self.find(u"TemplateCombo").SelectedItem
        if chosen is None or core.to_text(chosen) == self.template_name:
            return
        self.apply_template(core.to_text(chosen))
        self.set_status(u"Template: " + core.to_text(chosen))

    def on_export_settings(self, sender, args):
        self.open_settings()

    def open_settings(self):
        """Modal to this window and run inside a job, so everything the
        dialog reads from the model is read in Revit's API context."""
        import mcu_settings
        dialog = mcu_settings.SettingsWindow(self, self.template_name)
        saved = dialog.show()
        if dialog.purge_cache is not None:
            self.purge_cache = dialog.purge_cache
        self.load_templates(saved or self.template_name)

    def on_scan(self, sender, args):
        self.begin_busy(u"Counting in the live model...")
        try:
            if self.purge_cache is None:
                self.progress.update(0.1, u"Asking Revit what is unused (Revit is busy)")
                self.purge_cache = model.scan_purge(self.doc, True)
            self.progress.update(0.7, u"Counting views, links, templates and filters")
            entries = self.purge_cache.get(u"unused", [])
            active_id = 0
            if self.active_is(self.uiapp, self.doc):
                try:
                    active_id = core.eid_value(self.uiapp.ActiveUIDocument.ActiveView.Id)
                except Exception:
                    active_id = 0
            counts = model.plan_counts(self.doc, self.template, active_id, entries)
        except Exception:
            self.end_busy(u"Count failed", u"fail")
            raise
        self.fill_plan(counts)
        self.end_busy(u"Counts are from the live model; the copy is recounted when it runs.")

    # ============================================================
    # closing after a clean up: save, close, show the folder
    # ============================================================
    def finish_and_close(self, uiapp=None):
        try:
            self._finish_and_close()
        except Exception:
            text = core.format_exception()
            self.debug.exception(u"save and close", text)
            if self.busy:
                self.end_busy(u"Save and close failed", u"fail")
            ui.show_error(self.window, u"Save and close", text, self.theme)

    def _finish_and_close(self):
        open_model = self.target_is_active
        if open_model:
            keep_label = u"Close window, leave the model open"
            text = (u"The clean up is done in the open model, which has NOT been saved.\n\n"
                    u"Save and close saves it compact, relinquishes every workset, "
                    u"shows you its folder and closes the model.")
        else:
            keep_label = (u"Close window and open the copy"
                          if core.as_bool(self.template.get(u"open_when_done"), True)
                          else u"Close window")
            text = (u"The cleaned copy is saved:\n{0}\n\n"
                    u"Save and close saves it compact once more, relinquishes every "
                    u"workset, shows you its folder and closes it.").format(self.target_path)
        choice = ui.prompt(self.window, u"Save and close the model", text,
                           [(u"Cancel", None, u"BaseButton"),
                            (keep_label, u"keep", u"OrangeButton"),
                            (u"Save and close", u"save", u"GreenButton")], self.theme)
        self.debug_step(u"Close asked", [(u"choice", choice), (u"open model", open_model)])
        if choice is None:
            return
        if choice == u"save":
            if not self.save_and_close_model():
                return
            self.open_after = u""
        self.close_decided = True
        self.window.Close()

    def save_and_close_model(self):
        """True when saved (and closed or queued to close)."""
        doc = self.target_doc
        if doc is None or not self._target_alive():
            self.tell(u"Save and close", u"The cleaned model is no longer open.")
            return False
        info = model.describe(doc)
        route = core.save_route(info)
        comment = u"Model Cleanup - cleaned, compacted and relinquished"
        unchanged = False
        try:
            unchanged = self.run_saved and not doc.IsModified
        except Exception:
            unchanged = False
        if unchanged and route in (core.SAVE_SYNC, core.SAVE_PLAIN):
            route = core.SAVE_NONE
        if route == core.SAVE_AS:
            target = self.ask_new_path(info)
            if not target:
                return False
            self.begin_busy(u"Saving the model for the first time")
            self.progress.update(0.2, u"Save As, compact (Revit is busy)")
            try:
                ops.save_new_file(self.uiapp, doc, target)
            except Exception:
                self.end_busy(u"Save As failed", u"fail")
                raise
            self.end_busy(u"Saved as " + target)
            info = model.describe(doc)
            route = core.save_route(info)
        if route == core.SAVE_LOCAL:
            choice = ui.prompt(self.window, u"Save and close - local file",
                               core.local_save_message(info),
                               [(u"Cancel", None, u"BaseButton"),
                                (u"Sync and relinquish", u"sync", u"RedGhostButton"),
                                (u"Save local only", u"local", u"GreenButton")], self.theme)
            if choice is None:
                return False
            if choice == u"sync":
                answer, typed = ui.prompt(
                    self.window, u"Sync the clean up to the central",
                    u"This sends every deletion and the purge to\n{0}\n\nType {1} to sync."
                    .format(info[u"central"] or u"the central model", core.CONFIRM_WORD),
                    [(u"Cancel", False, u"BaseButton"), (u"Sync", True, u"RedGhostButton")],
                    self.theme, input_text=u"", input_hint=u"Type " + core.CONFIRM_WORD)
                if not answer or not core.confirm_typed(typed):
                    self.set_status(u"Not synced.")
                    return False
                route = core.SAVE_SYNC
        self.begin_busy(u"Saving and closing")
        self.progress.update(0.1, {core.SAVE_NONE: u"Already saved by Clean Up - closing",
                                   core.SAVE_SYNC: u"Syncing compact and relinquishing (Revit is busy)",
                                   core.SAVE_PLAIN: u"Saving compact (Revit is busy)",
                                   core.SAVE_LOCAL: u"Saving the local file compact (Revit is busy)"}
                             .get(route, u"Saving"))
        try:
            if route == core.SAVE_NONE:
                message = (u"Already saved compact and relinquished by Clean Up, and "
                           u"nothing has changed since - no second sync needed.")
                route = core.SAVE_SYNC if info[u"workshared"] else core.SAVE_PLAIN
            else:
                message = ops.save_model(self.uiapp, doc, route, comment, self.debug)
        except Exception:
            self.end_busy(u"Saving failed - the model is still open", u"fail")
            raise
        self.log(message)
        path = info[u"central"] if route == core.SAVE_SYNC and info[u"central"] else info[u"path"]
        self.progress.update(0.8, u"Closing the model")
        if self.target_is_active:
            # Revit will not let an add-in close the model in front of it;
            # its own Close command is posted as the window closes
            self.post_close = True
            closed_text = u"The model closes as soon as this window does."
        else:
            ops.close_document(doc, False)
            self.target_doc = None
            closed_text = u"The model is closed."
        self.end_busy(message)
        self.debug_step(u"Saved and closed", [(u"route", route), (u"path", path),
                                              (u"closes after the window", self.post_close)])
        folder = core.folder_of(path)
        if not folder:
            self.tell(u"Saved", u"{0}\n\n{1}\n\nThis model lives on ACC, so there is no "
                                u"folder to open.".format(message, closed_text))
            return True
        answer = ui.prompt(self.window, u"Saved",
                           u"{0}\n\n{1}\n\nOpen the folder?\n{2}".format(message, closed_text, folder),
                           [(u"No", False, u"BaseButton"), (u"Open folder", True, u"GreenButton")],
                           self.theme)
        if answer:
            self.show_in_folder(path)
        return True

    def ask_new_path(self, info):
        dialog = SaveFileDialog()
        dialog.Title = u"Save the cleaned model as"
        dialog.Filter = u"Revit project (*.rvt)|*.rvt"
        dialog.DefaultExt = u".rvt"
        dialog.AddExtension = True
        dialog.FileName = core.send_file_name(info[u"title"] or u"Model",
                                              core.active_suffix(self.template), False)
        folder = self.settings.get(u"last_folder") or u""
        if folder and os.path.isdir(folder):
            dialog.InitialDirectory = folder
        if not self.file_dialog(dialog):
            return u""
        return dialog.FileName

    def show_in_folder(self, path):
        import subprocess
        try:
            if os.path.isfile(path):
                subprocess.Popen([u"explorer.exe", u"/select,", path])
            else:
                subprocess.Popen([u"explorer.exe", core.folder_of(path)])
            self.set_status(u"Opened " + core.folder_of(path))
        except Exception:
            self.tell(u"Folder", u"The model is in:\n" + core.folder_of(path))

    # ============================================================
    # closing
    # ============================================================
    def on_close_button(self, sender, args):
        self.window.Close()

    def on_key(self, sender, args):
        try:
            if args.Handled:
                return
            escape = args.Key == Key.Escape
            if self.queued_label:
                if escape:
                    self.cancel_queued()
                args.Handled = True
                return
            if self.busy:
                # keys could otherwise press a focused button mid-job
                if escape:
                    self.cancel_requested = True
                    self.set_status(u"Cancelling...")
                args.Handled = True
                return
            if escape:
                args.Handled = True
                self.window.Close()
        except Exception:
            pass

    def on_closing(self, sender, args):
        # a job may close the window itself (Save and close, or the model
        # having gone) - it says so with close_decided; anything else waits
        if self.busy or self.queued_label or (self.runner.running and not self.close_decided):
            args.Cancel = True
            return
        if self.cleaned and not self.close_decided:
            args.Cancel = True
            self.request_job(u"Save and close", self.finish_and_close)
            return
        self.stop_publish_poll()
        self.stop_watchdog()
        if not self.cleaned:
            self.open_after = u""
        if self.needs_after_close():
            kept, status = self.runner.request(u"Closing", self.after_close)
            if not kept:
                core.log(u"closing job refused ({0}); the copy stays open".format(status))
        self.debug.section(u"Window closed")
        self.debug.flush()

    def on_closed(self, sender, args):
        self.closed = True
        self.lock_revit(False)
        try:
            AppDomain.CurrentDomain.SetData(INSTANCE_KEY, None)
        except Exception:
            pass

    def needs_after_close(self):
        background = (self.target_doc is not None and not self.target_is_active
                      and self._target_alive())
        return background or self.post_close or bool(self.open_after)

    def after_close(self, uiapp):
        """Runs once the window has gone: closes the background copy, closes
        the cleaned open model, or opens the cleaned copy."""
        doc = self.target_doc
        alive = doc is not None and self._target_alive()
        if alive and not self.target_is_active and not self.post_close:
            ops.close_document(doc, False)
        if self.post_close and alive:
            if self.active_is(uiapp, doc):
                if not ops.post_close_active(uiapp):
                    core.log(u"could not post Revit's Close command")
            else:
                # not the model in front: an add-in may close it directly,
                # and it has just been saved
                ops.close_document(doc, False)
        elif self.open_after:
            core.log(u"opening " + self.open_after)
            try:
                uiapp.OpenAndActivateDocument(self.open_after)
            except Exception:
                core.write_error(u"opening the cleaned copy", core.format_exception())
