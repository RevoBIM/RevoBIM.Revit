# -*- coding: utf-8 -*-
"""The modeless window."""

import snte_clr  # noqa: F401  - must be first

import time
import traceback

from System import Action, AppDomain
from System.Collections.ObjectModel import ObservableCollection
from System.Windows import Visibility
from System.Windows.Controls import TextBox
from System.Windows.Input import Key
from System.Windows.Threading import DispatcherPriority

import snte_core as core
import snte_ops as ops
import snte_ui as ui
import snte_tree as tree_mod
import theme as theme_module

PARK_KEY = "RevoBIM_SpaceNameToElement_Window"


class SpaceNameWindow(object):

    # -----------------------------------------------------------------
    #  set up
    # -----------------------------------------------------------------
    def __init__(self, uiapp):
        self.uiapp = uiapp
        self.uidoc = uiapp.ActiveUIDocument
        self.doc = self.uidoc.Document

        self.settings = core.load_settings()
        self.theme_name = self.settings.get("theme", "dark")

        self.busy = False
        self.cancel_asked = False
        self.cat_nodes = []
        self.params = []
        self.params_by_name = {}
        self._suppress = False
        self._last_pct = -1
        self._last_pump = 0.0
        self.spaces_count = 0

        self.handler, self.event = ops.make_event()
        self.handler.on_error = self._handler_error

        self.window = ui.load_window("SpaceNameToElement.xaml")
        ui.apply_theme(self.window, self.theme_name)
        self._bind()
        self._chrome()
        self._apply_settings()

        self.read_model()

    def _find(self, name):
        return self.window.FindName(name)

    def _bind(self):
        """Explicit Python side binding - XAML string based event wiring is
        unreliable under IronPython."""
        window = self.window

        self.info_txt = self._find("info_txt")
        self.search_tb = self._find("search_tb")
        self.cat_tree = self._find("cat_tree")
        self.tree_empty = self._find("tree_empty")
        self.param_cb = self._find("param_cb")
        self.param_info = self._find("param_info")
        self.opt_overwrite = self._find("opt_overwrite")
        self.opt_clear = self._find("opt_clear")
        self.opt_bind = self._find("opt_bind")
        self.status_txt = self._find("status_txt")
        self.run_btn = self._find("run_btn")
        self.cancel_btn = self._find("cancel_btn")
        self.refresh_btn = self._find("refresh_btn")
        self.all_btn = self._find("all_btn")
        self.none_btn = self._find("none_btn")
        self.theme_chip = self._find("theme_chip")
        self.ver_txt = self._find("ver_txt")
        self.logo_img = self._find("logo_img")
        self.prog_panel = self._find("prog_panel")
        self.prog_bar = self._find("prog_bar")
        self.prog_pct = self._find("prog_pct")
        self.prog_label = self._find("prog_label")
        self.full_btn = self._find("full_btn")
        self.close_btn = self._find("close_btn")
        self.header_bar = self._find("header_bar")

        self.ver_txt.Text = "v" + core.__version__
        ui.load_icon(self.logo_img, "icon.png")

        self.search_tb.TextChanged += self.search_changed
        self.all_btn.Click += self.all_click
        self.none_btn.Click += self.none_click
        self.refresh_btn.Click += self.refresh_click
        self.run_btn.Click += self.run_click
        self.cancel_btn.Click += self.cancel_click
        self.theme_chip.Click += self.theme_click
        self.full_btn.Click += self.fullscreen_click
        self.close_btn.Click += self.close_click
        self.header_bar.MouseLeftButtonDown += self.header_drag

        self.param_cb.KeyUp += self.param_key_up
        self.param_cb.PreviewMouseLeftButtonDown += self.param_clicked
        self.param_cb.SelectionChanged += self.param_selection_changed

        window.KeyDown += self.key_down
        window.Closing += self.on_closing

        self.builder = tree_mod.TreeBuilder(self.cat_tree, self.tree_empty,
                                            self.selection_changed)

    def _chrome(self):
        ui.hook_grips(self.window)
        self.full = ui.FullScreen(self.window)
        ui.own_to_revit(self.window, self.uiapp)

    def _apply_settings(self):
        self.opt_overwrite.IsChecked = core.as_bool(self.settings.get("overwrite"))
        self.opt_clear.IsChecked = core.as_bool(self.settings.get("clear_empty"))
        self.opt_bind.IsChecked = core.as_bool(self.settings.get("auto_bind"))
        self.opt_bind.Checked += self._bind_opt_changed
        self.opt_bind.Unchecked += self._bind_opt_changed
        self.theme_chip.Content = theme_module.other(self.theme_name).title()

    def _bind_opt_changed(self, sender, args):
        self.update_param_info()

    # -----------------------------------------------------------------
    #  reading the model
    # -----------------------------------------------------------------
    def read_model(self):
        self.set_busy(True, "Reading the model")
        try:
            def progress(done, total):
                self.report(done, total, "Reading the model")

            self.cat_nodes = core.read_model_tree(self.doc, progress)
            self.params = core.get_instance_text_params(self.doc)
            self.params_by_name = dict(
                [(p.name.lower(), p) for p in self.params])
            self.spaces_count = len(core.get_placed_spaces(self.doc))

            self.builder.set_nodes(self.cat_nodes)
            self.fill_params("")
            remembered = self.settings.get("parameter", "")
            if remembered.lower() in self.params_by_name:
                self._set_param_text(remembered)
            self.info_txt.Text = (
                "{0} placed space(s), {1} categor{2} with placed elements. "
                "Expand a category to pick individual families and types."
                .format(self.spaces_count, len(self.cat_nodes),
                        "y" if len(self.cat_nodes) == 1 else "ies"))
            self.selection_changed()
        finally:
            self.set_busy(False)

    # -----------------------------------------------------------------
    #  the parameter picker
    # -----------------------------------------------------------------
    def fill_params(self, keyword):
        low = (keyword or "").strip().lower()
        items = ObservableCollection[object]()
        for prm in self.params:
            if not low or low in prm.name.lower():
                items.Add(prm.name)
        self._suppress = True
        try:
            self.param_cb.ItemsSource = items
        finally:
            self._suppress = False
        return items.Count

    def _set_param_text(self, text):
        self._suppress = True
        try:
            self.param_cb.Text = text
        finally:
            self._suppress = False

    def current_param(self):
        key = (self.param_cb.Text or "").strip().lower()
        return self.params_by_name.get(key)

    def _caret_to_end(self):
        try:
            self.param_cb.ApplyTemplate()
            editor = self.param_cb.Template.FindName("PART_EditableTextBox",
                                                     self.param_cb)
            if isinstance(editor, TextBox):
                editor.CaretIndex = len(editor.Text or "")
        except Exception:
            pass

    def update_param_info(self):
        prm = self.current_param()
        if prm is None:
            typed = (self.param_cb.Text or "").strip()
            if typed:
                self._say_param("No instance text parameter called '{0}'."
                                .format(typed), "RedBrush")
            else:
                self._say_param("Type a keyword to narrow the list.", "DimBrush")
            return

        picked = core.selected_categories(self.cat_nodes)
        if prm.builtin:
            self._say_param(
                "Built-in instance parameter - available on most categories, "
                "no binding needed.", "DimBrush")
            return

        missing = [c.name for c in picked if not prm.bound_to(c.cat_id_value)]
        base = "{0}{1}, bound to {2} categor{3}.".format(
            prm.kind[0].upper(), prm.kind[1:], len(prm.cat_ids),
            "y" if len(prm.cat_ids) == 1 else "ies")
        if missing and self.opt_bind.IsChecked:
            self._say_param(
                base + " Will be added to: " + ", ".join(sorted(missing)[:4])
                + ("..." if len(missing) > 4 else ""), "OrangeBrush")
        elif missing:
            self._say_param(
                base + " Not bound to: " + ", ".join(sorted(missing)[:4])
                + ("..." if len(missing) > 4 else "")
                + " - tick the option below to add them.", "RedBrush")
        else:
            self._say_param(base + " All ticked categories are bound.",
                            "DimBrush")

    def _say_param(self, text, brush_key):
        self.param_info.Text = text
        try:
            self.param_info.Foreground = self.window.FindResource(brush_key)
        except Exception:
            pass

    # -----------------------------------------------------------------
    #  progress, inside the window
    # -----------------------------------------------------------------
    def set_busy(self, busy, label=""):
        self.busy = busy
        if busy:
            self.cancel_asked = False
        self._last_pct = -1
        self.prog_panel.Visibility = \
            Visibility.Visible if busy else Visibility.Collapsed
        self.cancel_btn.Visibility = \
            Visibility.Visible if busy else Visibility.Collapsed
        self.run_btn.IsEnabled = not busy
        self.refresh_btn.IsEnabled = not busy
        self.all_btn.IsEnabled = not busy
        self.none_btn.IsEnabled = not busy
        self.param_cb.IsEnabled = not busy
        self.search_tb.IsEnabled = not busy
        self.cat_tree.IsEnabled = not busy
        try:
            # set once, here, rather than on every pump - toggling it
            # repeatedly invalidates the hit test tree for nothing
            self.window.IsHitTestVisible = not busy
        except Exception:
            pass
        if busy:
            self.prog_label.Text = label
            self.prog_pct.Text = "0%"
            self.prog_bar.Value = 0
        else:
            # everything the run disabled comes back on, explicitly. Leaving
            # this to the pump is how the window ended up dead to clicks after
            # a run in 2.0.0.
            self.window.IsHitTestVisible = True
            self.cat_tree.IsEnabled = True
            try:
                self.builder.refresh_states()
            except Exception:
                pass
            self.selection_changed()
        self._pump(force=True)

    def report(self, done, total, label=None):
        """Repaint when the whole percent moves, and in any case every 120ms.

        Percent alone is not enough: a few hundred spaces means whole seconds
        can pass inside one percent, and a window that has not painted for a
        second goes white.
        """
        if total <= 0:
            pct = 0
        else:
            pct = int((done * 100.0) / total)
            if pct > 100:
                pct = 100
        if label is not None and self.prog_label.Text != label:
            self.prog_label.Text = label
            self._last_pct = -1
        moved = pct != self._last_pct
        if moved:
            self._last_pct = pct
            self.prog_bar.Value = pct
            self.prog_pct.Text = "{0}%".format(pct)
        self._pump(force=moved)

    def _pump(self, force=False):
        """Let WPF repaint. Never called between a transaction's Start and
        Commit, and the window is not hit testable while busy, so pumped input
        cannot reach a handler mid-run.

        Throttled: a dispatcher frame per element costs more than the work
        being measured, but leaving too long a gap is what turns the window
        white.
        """
        now = time.time()
        if not force and (now - self._last_pump) < 0.12:
            return
        self._last_pump = now
        try:
            self.window.Dispatcher.Invoke(
                DispatcherPriority.Render, Action(_noop))
        except Exception:
            pass

    def cancelled(self):
        return self.cancel_asked

    # -----------------------------------------------------------------
    #  events
    # -----------------------------------------------------------------
    def header_drag(self, sender, args):
        if args.ClickCount == 2:
            self.full.toggle()
            return
        ui.drag_window(self.window)

    def key_down(self, sender, args):
        if self.busy:
            return
        if args.Key == Key.F11:
            self.full.toggle()
        elif args.Key == Key.F5:
            self.refresh_click(sender, args)
        elif args.Key == Key.Escape and self.full.on:
            self.full.restore()

    def search_changed(self, sender, args):
        if self.busy:
            return
        self.builder.rebuild(self.search_tb.Text)

    def all_click(self, sender, args):
        self.builder.set_visible(True, self.search_tb.Text)

    def none_click(self, sender, args):
        self.builder.set_visible(False, self.search_tb.Text)

    def refresh_click(self, sender, args):
        if self.busy:
            return
        kept = [c.name for c in core.selected_categories(self.cat_nodes)]
        self.read_model()
        self.builder.restore_selection(kept)
        self.selection_changed()

    def theme_click(self, sender, args):
        self.theme_name = theme_module.other(self.theme_name)
        ui.apply_theme(self.window, self.theme_name)
        self.theme_chip.Content = theme_module.other(self.theme_name).title()
        self.settings["theme"] = self.theme_name
        core.save_settings(self.settings)
        self.update_param_info()

    def fullscreen_click(self, sender, args):
        self.full.toggle()

    def close_click(self, sender, args):
        if self.busy:
            self.cancel_asked = True
            return
        self.window.Close()

    def cancel_click(self, sender, args):
        self.cancel_asked = True
        self.prog_label.Text = "Stopping after this chunk..."

    def param_clicked(self, sender, args):
        if self.busy:
            return
        if not self.param_cb.IsDropDownOpen:
            keep = self.param_cb.Text or ""
            self.fill_params("")
            self._set_param_text(keep)

    def param_key_up(self, sender, args):
        key = args.Key
        if key in (Key.Up, Key.Down, Key.Left, Key.Right, Key.Tab,
                   Key.LeftShift, Key.RightShift, Key.LeftCtrl, Key.RightCtrl):
            return
        if key == Key.Escape:
            self.param_cb.IsDropDownOpen = False
            return
        if key == Key.Enter:
            self.param_cb.IsDropDownOpen = False
            self.update_param_info()
            self.remember_param()
            return

        keyword = self.param_cb.Text or ""
        count = self.fill_params(keyword)
        self._set_param_text(keyword)
        self._caret_to_end()
        self.param_cb.IsDropDownOpen = count > 0
        self.update_param_info()

    def param_selection_changed(self, sender, args):
        if self._suppress or self.busy:
            return
        self.update_param_info()
        self.remember_param()

    def remember_param(self):
        prm = self.current_param()
        if prm is None:
            return
        if self.settings.get("parameter") != prm.name:
            self.settings["parameter"] = prm.name
            core.save_settings(self.settings)

    def selection_changed(self):
        cats, types, elements = core.selection_counts(self.cat_nodes)
        if elements:
            self.status_txt.Text = \
                "{0} element(s) in {1} type(s), {2} categor{3}".format(
                    elements, types, cats, "y" if cats == 1 else "ies")
        else:
            self.status_txt.Text = "Nothing selected"
        self.run_btn.IsEnabled = elements > 0 and not self.busy
        self.update_param_info()

    def on_closing(self, sender, args):
        if self.busy:
            args.Cancel = True
            self.cancel_asked = True
            return
        self.save_all()
        _unpark()

    def save_all(self):
        self.settings["theme"] = self.theme_name
        self.settings["overwrite"] = "1" if self.opt_overwrite.IsChecked else "0"
        self.settings["clear_empty"] = "1" if self.opt_clear.IsChecked else "0"
        self.settings["auto_bind"] = "1" if self.opt_bind.IsChecked else "0"
        prm = self.current_param()
        if prm is not None:
            self.settings["parameter"] = prm.name
        core.save_settings(self.settings)

    # -----------------------------------------------------------------
    #  the run
    # -----------------------------------------------------------------
    def run_click(self, sender, args):
        if self.busy:
            return
        prm = self.current_param()
        if prm is None:
            self.update_param_info()
            self.param_cb.Focus()
            return
        cats, types, elements = core.selection_counts(self.cat_nodes)
        if not elements:
            return

        self.save_all()

        body = ("About to write '{0}' onto {1} element(s), across {2} type(s) "
                "in {3} categor{4}.\n\n{5} placed space(s) will be scanned."
                .format(prm.name, elements, types, cats,
                        "y" if cats == 1 else "ies", self.spaces_count))
        picked = core.selected_categories(self.cat_nodes)
        missing = [c.name for c in picked if not prm.bound_to(c.cat_id_value)]
        if missing and self.opt_bind.IsChecked and not prm.builtin:
            body += ("\n\nThe parameter will first be added to: {0}."
                     .format(", ".join(sorted(missing))))
        if self.opt_clear.IsChecked:
            body += ("\n\nElements found in no space will have '{0}' cleared."
                     .format(prm.name))

        # a silent "no" from a confirm step is indistinguishable from a broken
        # button, so a failure here falls back to Revit's own dialog
        try:
            go = ui.confirm("Space Name To Element", body, self.theme_name,
                            self.window, "Run", "Cancel")
        except Exception:
            go = _revit_confirm(body)
        if not go:
            return

        options = {
            "overwrite": bool(self.opt_overwrite.IsChecked),
            "clear_empty": bool(self.opt_clear.IsChecked),
            "auto_bind": bool(self.opt_bind.IsChecked),
            "chunk_size": int(self.settings.get("chunk_size", "200") or 200),
        }
        nodes = list(self.cat_nodes)

        def job(uiapp):
            result = None
            try:
                result = ops.run_transfer(
                    self.doc, core.selected_categories(nodes), prm, options,
                    self.report, self.cancelled)
            except Exception:
                detail = traceback.format_exc()
                self.set_busy(False)
                self._later(lambda: ui.alert(
                    "Space Name To Element", "The run failed:\n\n" + detail,
                    self.theme_name, self.window))
                return
            self.set_busy(False)
            # not from in here: a modal ShowDialog opened inside the external
            # event's Execute runs a nested message loop inside Revit's API
            # context, and the window comes back unable to take a click. It
            # goes on the dispatcher instead, once Execute has returned.
            self._later(lambda: self.show_result(result, prm.name))

        # The progress band goes up and the window is repainted *before* the
        # thread goes to work. Raising straight after the confirm dialog closed
        # meant the UI thread blocked before WPF could repaint the area the
        # dialog had covered, and that patch of window stayed white until the
        # first progress update.
        self.set_busy(True, "Starting")
        self.handler.job = job
        self._later(lambda: self.event.Raise())

    def show_result(self, result, param_name):
        lines = []
        if result.cancelled:
            lines.append("Stopped before the end - what had already been "
                         "written is kept.")
            lines.append("")
        if result.bound_added:
            lines.append("Parameter added to: " +
                         ", ".join(sorted(result.bound_added)))
        if result.bound_failed:
            lines.append("Could not be bound: " +
                         ", ".join(sorted(set(result.bound_failed))))
        if result.bound_added or result.bound_failed:
            lines.append("")

        lines.append("Written: {0}".format(result.written))
        if result.cleared:
            lines.append("Cleared: {0}".format(result.cleared))
        lines.append("Already correct: {0}".format(result.unchanged))
        if result.skipped_filled:
            lines.append("Left alone, already had a value: {0}"
                         .format(result.skipped_filled))
        lines.append("Not in any space: {0}".format(result.no_space))
        if result.no_param:
            lines.append("")
            lines.append("No writeable '{0}': {1}".format(param_name,
                                                          result.no_param))
            for cname in sorted(result.missing_by_cat.keys()):
                lines.append("   {0}: {1}".format(cname,
                                                  result.missing_by_cat[cname]))
        if result.locked:
            lines.append("")
            lines.append("Locked by somebody else: {0} ({1})".format(
                result.locked, ", ".join(result.locked_names)))
        if result.spaces_no_geometry:
            lines.append("")
            lines.append("{0} space(s) gave no geometry and were skipped - "
                         "check Area and Volume Computations."
                         .format(result.spaces_no_geometry))
        if result.error:
            lines.append("")
            lines.append(result.error)

        ui.alert("Space Name To Element", "\n".join(lines), self.theme_name,
                 self.window)

    def _handler_error(self, text):
        self.set_busy(False)
        self._later(lambda: ui.alert(
            "Space Name To Element", "The run failed:\n\n" + text,
            self.theme_name, self.window))

    def _later(self, func):
        """Queue something to run once the current call has unwound."""
        try:
            self.window.Dispatcher.BeginInvoke(
                DispatcherPriority.Background, Action(func))
        except Exception:
            try:
                func()
            except Exception:
                pass

    # -----------------------------------------------------------------
    def show(self):
        _park(self)
        self.window.Show()


# ---------------------------------------------------------------------------
#  parking, so the persistent engine cannot collect the window out from under
#  the user, and a second click cannot leave an orphan behind
# ---------------------------------------------------------------------------
def _park(instance):
    try:
        existing = AppDomain.CurrentDomain.GetData(PARK_KEY)
        if existing is not None:
            try:
                existing.window.Close()
            except Exception:
                pass
    except Exception:
        pass
    try:
        AppDomain.CurrentDomain.SetData(PARK_KEY, instance)
    except Exception:
        pass


def _unpark():
    try:
        AppDomain.CurrentDomain.SetData(PARK_KEY, None)
    except Exception:
        pass


def _noop():
    return None


def _revit_confirm(body):
    try:
        from Autodesk.Revit.UI import TaskDialog, TaskDialogCommonButtons, \
            TaskDialogResult
        dialog = TaskDialog("RevoBIM - Space Name To Element")
        dialog.MainInstruction = "Run the transfer?"
        dialog.MainContent = body
        dialog.CommonButtons = TaskDialogCommonButtons.Yes | \
            TaskDialogCommonButtons.No
        return dialog.Show() == TaskDialogResult.Yes
    except Exception:
        return False
