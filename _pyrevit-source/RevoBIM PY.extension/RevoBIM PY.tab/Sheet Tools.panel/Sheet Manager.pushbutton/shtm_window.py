# -*- coding: utf-8 -*-
"""The Sheet Manager window.

Modeless and owned by Revit's main window, so Revit stays fully navigable while
it is open and the window floats above Revit rather than slipping behind it -
an unowned modeless window reads as a crash.

Because it is modeless every write goes out through an ExternalEvent. That is
the only way a modeless window can change the model at all.
"""

import shtm_clr  # noqa: F401  - references the assemblies first

import os
import sys
import traceback

import shtm_core
import shtm_model
import shtm_grid
import shtm_rows
import shtm_fill
import shtm_ui
import shtm_dup
import shtm_vt
import shtm_duplicate
import shtm_settings
import shtm_edit
import shtm_edits
import shtm_xlsx
import theme
from shtm_ui import ui_safe, styled, button, text_box

from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent, ExternalEventRequest

from System.Windows import Visibility, Thickness
from System.Windows.Controls import (
    StackPanel, Border, ListBox, ListBoxItem, CheckBox, ComboBoxItem, Orientation,
)
from System.Windows.Controls import (
    ContextMenu, MenuItem, Border, Separator, StackPanel, TextBlock,
)
from System.Windows.Controls.Primitives import Popup, PlacementMode
from System.Windows import Clipboard, HorizontalAlignment, VerticalAlignment
from System.Windows.Input import Key, Keyboard, ModifierKeys
from System.Windows.Media import VisualTreeHelper
from Microsoft.Win32 import OpenFileDialog, SaveFileDialog
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Threading import DispatcherPriority
from System import Action

NO_GROUP = u"(none)"


# ====================== the write handler ======================

class DuplicateHandler(IExternalEventHandler):
    """Every model write leaves the window through here."""

    def __init__(self):
        self.job = None
        self.done = None
        self.progress = None

    def Execute(self, uiapp):
        job = self.job
        self.job = None
        if job is None:
            return
        report = None
        try:
            document, refused = shtm_ui.job_document(uiapp, job)
            if refused:
                raise Exception(refused)
            duplicator = shtm_dup.Duplicator(document)
            duplicator.debug = bool(job.get("debug"))
            # a job brought by the builder window carries its own progress and
            # per-sheet callbacks, so the rows it is showing can go green
            progress = job.get("progress") or self.progress
            duplicator.on_sheet = job.get("on_sheet")
            if job.get("batches"):
                report = duplicator.run_batches(job["batches"], job["name_params"],
                                                progress)
            else:
                report = duplicator.run(job["plan"], job["sheet_rows"],
                                        job["options"], job["grouping"],
                                        job["name_params"], progress)
        except Exception as exc:
            shtm_ui.log(u"duplicate failed: {0}".format(exc))
            report = {"sheets": [], "views": 0, "reused": 0, "placed": 0,
                      "confirmed": 0, "problems": [u"{0}".format(exc)], "notes": []}
        for callback in (job.get("done"), self.done):
            if callback is None:
                continue
            try:
                callback(report)
            except Exception:
                shtm_ui.log(u"a results callback failed")

    def GetName(self):
        return "RevoBIM Sheet Manager"


class OpenSheetHandler(IExternalEventHandler):
    """Changing the active view is a request Revit will only take in its own
    context, so it goes out through its own event rather than being called
    from the window."""

    def __init__(self):
        self.sheet_id = None

    def Execute(self, uiapp):
        wanted = self.sheet_id
        self.sheet_id = None
        if not wanted:
            return
        try:
            uidoc = uiapp.ActiveUIDocument
            element = uidoc.Document.GetElement(shtm_model.new_element_id(wanted))
            if element is not None:
                uidoc.RequestViewChange(element)
        except Exception as exc:
            shtm_ui.log(u"could not open the sheet: {0}".format(exc))

    def GetName(self):
        return "RevoBIM Sheet Manager - open a sheet"


class DialogGuard(object):
    """Hooked once and switched with a flag: unsubscribing an IronPython bound
    method from a .NET event is not reliable, because each attribute access
    makes a fresh delegate."""

    def __init__(self, uiapp):
        self.active = False
        self.suppressed = []
        try:
            uiapp.DialogBoxShowing += self._showing
        except Exception:
            pass

    def _showing(self, sender, args):
        if not self.active:
            return
        try:
            self.suppressed.append(u"{0}".format(args.DialogId))
        except Exception:
            pass
        try:
            args.OverrideResult(1)
        except Exception:
            pass


# ====================== the window ======================

class SheetManagerWindow(object):

    def __init__(self, uiapp, doc, settings, picked=None):
        self.uiapp = uiapp
        self.doc = doc
        self.settings = settings
        self.sheets = []
        self.rows = []
        self.state = shtm_grid.GridState()
        self.mode = settings.get("theme", "auto")
        self.busy = False

        self.window = shtm_ui.load_window("SheetManager.xaml", self.mode)
        self.find = self.window.FindName
        self.chrome = shtm_ui.Chrome(self.window, on_close=self._closing,
                                     busy=lambda: self.busy)
        # WPF closes owned windows with their owner and ignores their own
        # Closing cancellation, so the builder would vanish mid-run - the
        # owner refuses instead
        self.window.Closing += ui_safe(self._closing_guard)
        shtm_ui.load_icon(self.find("LogoImage"))
        shtm_ui.attach_egg(self.window, self.find("LogoHost"),
                           lambda: self.mode)
        self.find("VersionText").Text = u"v{0}".format(shtm_core.__version__)
        self.find("ThemeChip").Content = theme.label(self.mode)

        self.handler = DuplicateHandler()
        self.handler.done = self._results
        self.handler.progress = self._progress
        self.event = ExternalEvent.Create(self.handler)
        self.opener = OpenSheetHandler()
        self.open_event = ExternalEvent.Create(self.opener)
        # view template duplicate / rename / edit, asked for by the Duplicate
        # window. Created here, while Revit is running the command: a button
        # click on a modeless window is not a context ExternalEvent.Create
        # can be called from
        self.template_handler = shtm_vt.TemplateHandler()
        self.template_event = ExternalEvent.Create(self.template_handler)
        # pending cell edits - nothing is written until Apply
        self.store = shtm_edit.EditStore()
        self.editor = shtm_edits.EditHandler()
        self.editor.done = self._edit_results
        self.edit_event = ExternalEvent.Create(self.editor)
        self.cell_editor = None
        # duplicate highlighting, per column: value -> colour number
        self.highlights = {}
        self.dropping = False
        # column widths, measured once after the first render and frozen
        self.widths = {}
        self.guard = DialogGuard(uiapp)
        self.last_report = None
        # anything that would not wire up, so a window that answers nothing can
        # still say why
        self.wiring_problems = []
        # the create-from-templates window, while it is open
        self.builder = None

        # the sheets selected in Revit when the tool was opened
        self.revit_picked = []

        self._columns_from_settings()
        self._wire()
        self.reload()
        self.use_revit_selection(picked)

    # ============ columns ============

    def _columns_from_settings(self):
        wanted = shtm_core.split_list(self.settings.get("columns"))
        if not wanted:
            wanted = shtm_model.browser_organisation(self.doc)
        columns = list(shtm_grid.FIXED_COLUMNS)
        for name in wanted:
            if name not in columns:
                columns.append(name)
        if len(columns) == len(shtm_grid.FIXED_COLUMNS):
            columns.append(u"Views on sheet")
        self.state.columns = columns
        saved = shtm_core.split_list(self.settings.get("group_by"))
        self.state.group_by = [g for g in saved if g in columns]
        self.state.group_by_sort = shtm_core.as_bool(
            self.settings.get("group_by_sort"))
        # the sorting the table was left with last time, every level of it;
        # a column no longer in the table is dropped from it
        remembered = shtm_core.sorts_from_text(self.settings.get("table_sorts"),
                                               columns)
        if remembered:
            self.state.sorts = remembered
        # a column taken out of the table cannot go on being sorted on
        self.state.drop_missing_sorts()

    def available_parameters(self):
        names = set(shtm_model.sheet_parameter_names(self.doc))
        names.add(u"Views on sheet")
        for column in self.state.columns:
            names.add(column)
        return sorted(names, key=lambda n: n.lower())

    # ============ wiring ============

    def _wire(self):
        """Wired in steps, each on its own, essentials first.

        A single chain of handler hook-ups is one bad line away from a window
        that opens, draws its rows, and answers nothing - which is exactly what
        1.4.1 did. The things the tool cannot be used without go first, each in
        its own try/except, and anything that fails is named in the status bar
        and written to the error file rather than taking the rest with it.
        """
        grid = self.find("SheetGrid")
        # Diagnostics first and on its own: it is the one button that has to
        # work when nothing else does
        try:
            self.find("DiagBtn").Click += ui_safe(self._diagnostics)
        except Exception:
            self.wiring_problems.append(u"Diagnostics: {0}".format(
                traceback.format_exc()))
        steps = [
            ("the sheet list", lambda: self._wire_grid(grid)),
            ("the keyboard", lambda: self.window.KeyDown.__iadd__(
                ui_safe(self._key)) and None),
            ("the toolbar", self._wire_toolbar),
            ("the footer", self._wire_footer),
            ("grouping", self._wire_grouping),
            ("the search box", self._wire_search),
            ("the Revit selection", self._wire_picked),
            ("sorting", lambda: shtm_grid.wire_sorting(grid, self.state,
                                                       self._changed)),
            ("the cell menu", lambda: self._wire_cell_menu(grid)),
            ("the legend", self._build_legend),
        ]
        for label, action in steps:
            try:
                action()
            except Exception:
                self.wiring_problems.append(u"{0}: {1}".format(
                    label, traceback.format_exc()))
        if self.wiring_problems:
            self._report_wiring()

    def _wire_grid(self, grid):
        grid.SelectionChanged += ui_safe(self._selection)
        # down, not up: the press is what selects a row, so a heading has to
        # be taken before the grid gets it - on up the row is already selected
        # and the click has already been counted
        grid.PreviewMouseLeftButtonDown += ui_safe(self._grid_click)
        grid.LoadingRow += ui_safe(self._loading_row)
        grid.MouseDoubleClick += ui_safe(self._cell_double_click)

    def _wire_toolbar(self):
        pairs = [
            ("RefreshBtn", lambda s, e: self.reload()),
            ("ExpandBtn", self._expand_all),
            ("CollapseBtn", self._collapse_all),
            ("ClearFiltersBtn", self._clear_filters),
            ("AddColumnBtn", self._columns_popup),
            ("SettingsBtn", self._settings),
            ("ThemeChip", self._cycle_theme),
            ("GroupBySortChip", self._toggle_group_by_sort),
            ("EditBtn", self._edit_dialog),
            ("ImportBtn", self._import_xlsx),
            ("ClearEditsBtn", self._discard_edits),
            ("FitBtn", self._fit_columns),
        ]
        self._hook(pairs)

    def _wire_footer(self):
        self._hook([
            ("SelectShownBtn", self._select_shown),
            ("ExportBtn", self._export),
            ("ApplyBtn", self._apply_edits),
            ("DuplicateBtn", self._duplicate),
        ])
        debug_box = self.find("DebugBox")
        debug_box.IsChecked = shtm_core.as_bool(self.settings.get("debug"))
        debug_box.Checked += ui_safe(self._debug_changed)
        debug_box.Unchecked += ui_safe(self._debug_changed)
        self._excel_icon()

    def _wire_picked(self):
        box = self.find("OnlyPickedBox")
        box.Checked += ui_safe(self._picked_toggled)
        box.Unchecked += ui_safe(self._picked_toggled)

    # ============ the sheets picked in Revit ============

    def use_revit_selection(self, selected, reopened=False):
        """Show only the sheets that were selected in Revit when the tool was
        opened (or opened again). Anything selected that is not a sheet - a
        view, a wall - is not a filter. Nothing picked: every sheet, and the
        strip stays out of the way."""
        ids = shtm_core.picked_sheet_ids(selected, [s["id"] for s in self.sheets])
        if reopened and (not ids or set(ids) == set(self.revit_picked)):
            # pressed again to bring the window forward: a wall or a viewport
            # selected is not a reason to drop the filter, and the same sheets
            # again leave the tick as it was left
            return
        self.revit_picked = ids
        strip = self.find("PickedStrip")
        box = self.find("OnlyPickedBox")
        if not ids:
            strip.Visibility = Visibility.Collapsed
            self.state.only_ids = None
            self.redraw(False)
            return
        strip.Visibility = Visibility.Visible
        box.Content = u"Only the {0} selected in Revit".format(
            shtm_core.plural(len(ids), u"sheet"))
        self.state.only_ids = set(ids)
        if box.IsChecked:
            self.redraw(False)
        else:
            # the tick's own handler redraws
            box.IsChecked = True
        self._paint_picked()
        # they were selected in Revit, so they are selected here too: Duplicate
        # Selected is ready straight away, with them as its source sheets
        try:
            self.find("SheetGrid").SelectAll()
        except Exception:
            pass

    def bring_forward(self):
        """The ribbon button pressed while the window is shrunk to the taskbar
        opens it again rather than doing nothing visible."""
        if self.chrome.parked():
            self.chrome.drawer.open()

    def _paint_picked(self):
        on = self.state.only_ids is not None
        self.find("PickedNote").Text = (
            u"untick to show every sheet" if on else
            u"showing every sheet - tick to go back to the {0}".format(
                shtm_core.plural(len(self.revit_picked), u"selected sheet")))

    def _picked_toggled(self, sender, event):
        on = bool(self.find("OnlyPickedBox").IsChecked)
        self.state.only_ids = set(self.revit_picked) if (on and self.revit_picked) else None
        self.redraw(False)
        self._paint_picked()

    def _hook(self, pairs):
        """Each button on its own, so one missing name cannot cost the rest."""
        for name, action in pairs:
            try:
                self.find(name).Click += ui_safe(action)
            except Exception:
                self.wiring_problems.append(u"{0}: {1}".format(
                    name, traceback.format_exc()))

    def _wire_grouping(self):
        for name in ("Group1", "Group2", "Group3"):
            self.find(name).SelectionChanged += ui_safe(self._grouping_changed)

    def _wire_search(self):
        timer = shtm_ui.debounce(250, lambda: self.redraw(False))

        @ui_safe
        def typed(sender, event):
            self.state.search_all = sender.Text or u""
            timer.Stop()
            timer.Start()

        self.find("SearchAll").TextChanged += typed

    def _wire_cell_menu(self, grid):
        """Built when it is opened, not when the window is. A menu that throws
        while it is being built at start-up would otherwise take the wiring
        after it down with it."""
        @ui_safe
        def opening(sender, event):
            if grid.ContextMenu is None:
                grid.ContextMenu = self._cell_menu()

        grid.ContextMenuOpening += opening

    def _excel_icon(self):
        """A green rounded square with an X in it, drawn from a Border and a
        TextBlock rather than set in a symbol font, so it cannot come out as an
        empty box on a machine without that font."""
        button = self.find("ExportBtn")
        line = StackPanel()
        line.Orientation = Orientation.Horizontal
        badge = Border()
        badge.Width = 15
        badge.Height = 15
        badge.CornerRadius = shtm_ui._corner(3)
        badge.Background = shtm_ui.solid("#1D7044")
        badge.Margin = Thickness(0, 0, 6, 0)
        badge.VerticalAlignment = VerticalAlignment.Center
        letter = TextBlock()
        letter.Text = u"X"
        letter.FontSize = 10
        letter.FontWeight = _bold()
        letter.Foreground = shtm_ui.solid("#FFFFFF")
        letter.HorizontalAlignment = HorizontalAlignment.Center
        letter.VerticalAlignment = VerticalAlignment.Center
        badge.Child = letter
        line.Children.Add(badge)
        label = shtm_ui.text_block(u"Export", "Lbl.Body")
        label.VerticalAlignment = VerticalAlignment.Center
        line.Children.Add(label)
        button.Content = line
        button.ToolTip = (u"The table as shown, pending edits included, to an "
                          u".xlsx or .csv")

    @ui_safe
    def _diagnostics(self, sender, event):
        """Everything the tool knows about itself, written to a file and shown.
        It does not depend on a run having happened, so a window that answers
        nothing can still be reported."""
        lines = [u"RevoBIM Sheet Manager v{0}".format(shtm_core.__version__)]
        try:
            application = self.doc.Application
            lines.append(u"Revit {0} build {1}".format(
                application.VersionNumber, application.VersionBuild))
        except Exception:
            lines.append(u"Revit version unknown")
        lines.append(u"engine: {0}".format(sys.version.replace(u"\n", u" ")))
        lines.append(u"assemblies loaded: {0}".format(
            u", ".join(shtm_clr.LOADED)))
        if shtm_clr.FAILED:
            lines.append(u"assemblies NOT loaded: {0}".format(
                u", ".join(shtm_clr.FAILED)))
        lines.append(u"")
        if self.wiring_problems:
            lines.append(u"THE WINDOW DID NOT FULLY WIRE UP:")
            for problem in self.wiring_problems:
                lines.append(problem)
        else:
            lines.append(u"every part of the window wired up")
        lines.append(u"")
        lines.append(u"{0} sheet(s) read, {1} row(s) drawn".format(
            len(self.sheets), len(self.rows)))
        lines.append(u"columns: {0}".format(u" | ".join(self.state.columns)))
        lines.append(u"sorts: {0}".format(u" > ".join(
            [u"{0} {1}".format(k, u"asc" if up else u"desc")
             for k, up in self.state.sorts])))
        lines.append(u"grouped by: {0}".format(
            u" > ".join(self.state.grouping()) or u"(nothing)"))
        lines.append(u"collapsed groups: {0}".format(len(self.state.collapsed)))
        lines.append(u"filters: {0}".format(u", ".join(
            sorted(self.state.filters.keys())) or u"(none)"))
        lines.append(u"selected: {0} sheet(s), current column {1}".format(
            len(self.selected_sheets()), self.current_column()))
        lines.append(u"pending edits: {0}".format(self.store.count()))
        lines.append(u"theme: {0}".format(self.mode))
        if self.guard.suppressed:
            lines.append(u"Revit dialogs answered: {0}".format(
                u", ".join(sorted(set(self.guard.suppressed)))))
        if self.last_report is not None:
            lines.append(u"")
            lines.append(u"--- the last run ---")
            for line in (self.last_report.get("debug") or [])[:400]:
                lines.append(line)
            for problem in self.last_report.get("problems") or []:
                lines.append(u"problem: {0}".format(problem))
        text = u"\n".join(lines)

        path = u""
        try:
            folder = shtm_core.settings_folder()
            if not os.path.isdir(folder):
                os.makedirs(folder)
            path = os.path.join(folder, "sheet_manager_diagnostics.txt")
            handle = open(path, "wb")
            try:
                handle.write(text.encode("utf-8"))
            finally:
                handle.close()
        except Exception:
            path = u""
        head = (u"Written to {0}\n\n".format(path) if path
                else u"It could not be written to a file.\n\n")
        choice = shtm_ui.message(self.mode, self.window, u"Diagnostics",
                                 head + text, [u"Copy to clipboard", u"Close"],
                                 width=900, height=680)
        if choice == 0:
            try:
                Clipboard.SetText(text)
                self.status(u"the diagnostics are on the clipboard")
            except Exception:
                self.status(u"the clipboard would not take it")

    def _report_wiring(self):
        """Silent handlers hide dead buttons. Anything that failed to wire is
        said out loud and written down, so a window that answers nothing can
        still be reported."""
        text = u"\n\n".join(self.wiring_problems)
        try:
            folder = shtm_core.settings_folder()
            if not os.path.isdir(folder):
                os.makedirs(folder)
            handle = open(os.path.join(folder, "sheet_manager_wiring.txt"), "wb")
            try:
                handle.write(text.encode("utf-8"))
            finally:
                handle.close()
        except Exception:
            pass
        try:
            self.find("StatusText").Text = (
                u"{0} part(s) of the window did not wire up - press "
                u"Diagnostics".format(len(self.wiring_problems)))
        except Exception:
            pass

    @ui_safe
    def _key(self, sender, event):
        """The Windows conventions - and they belong to whatever has focus.
        Inside a search box or the cell editor, Ctrl+C, Ctrl+V and Delete are
        the text box's, not the grid's. Handling every key at the window level
        is what makes Backspace in a search box wipe selected cells.

        First match wins, so the specific combination goes before the general:
        Ctrl+Shift+Z is checked before Ctrl+Z.
        """
        if event.Key == Key.F5:
            self.refresh_view()
            return
        if self._typing():
            return
        control = bool(Keyboard.Modifiers & ModifierKeys.Control)
        shift = bool(Keyboard.Modifiers & ModifierKeys.Shift)
        if control and shift and event.Key == Key.Z:
            event.Handled = self._redo()
        elif control and event.Key == Key.Z:
            event.Handled = self._undo()
        elif control and event.Key == Key.Y:
            event.Handled = self._redo()
        elif control and event.Key == Key.C:
            event.Handled = self._copy()
        elif control and event.Key == Key.X:
            event.Handled = self._copy(True)
        elif control and event.Key == Key.V:
            event.Handled = self._paste()
        elif control and event.Key == Key.D:
            event.Handled = self._fill_down(False)
        elif control and event.Key == Key.E:
            event.Handled = self._fill_down(True)
        elif control and event.Key == Key.H:
            self._edit_dialog(None, None)
            event.Handled = True
        elif control and event.Key == Key.S:
            self._apply_edits(None, None)
            event.Handled = True
        elif event.Key == Key.Delete:
            event.Handled = self._clear_cells()
        elif event.Key == Key.F2:
            event.Handled = self._edit_current()

    def _typing(self):
        """Whether the keyboard belongs to a text box rather than the grid."""
        if self.cell_editor is not None:
            return True
        try:
            focused = Keyboard.FocusedElement
            from System.Windows.Controls import TextBox
            return isinstance(focused, TextBox)
        except Exception:
            return False

    # ============ reading ============

    def refresh_view(self):
        """F5: re-take the filter, the sort and the grouping together, against
        the pending values, without throwing the pending edits away. Refresh
        re-reads the model; this only catches the view up with what is already
        staged."""
        shtm_rows.take_snapshot(self.sheets, self.state, self.store)
        self.redraw(True)
        self.status(u"view caught up - {0} edit(s) still waiting for "
                    u"Apply".format(self.store.count()))

    def reload(self):
        self.status(u"reading the sheets...")
        self.sheets = shtm_model.read_sheets(self.doc, self.settings)
        self._fill_group_boxes()
        self.redraw(True)

    def redraw(self, rebuild_columns=True):
        grid = self.find("SheetGrid")
        if rebuild_columns:
            shtm_grid.build_columns(grid, self.state, self._changed,
                                    self._distinct, self.store, self.highlights,
                                    self._column_menu, self.widths)
        self.rows, shown = shtm_grid.compute_rows(self.sheets, self.state)
        grid.ItemsSource = None
        grid.ItemsSource = self.rows
        self._remember_sorts()
        pending = self.store.count()
        parts = [u"{0} of {1} sheet(s) shown".format(shown, len(self.sheets))]
        if self.state.only_ids is not None:
            parts[0] += u" (only those selected in Revit)"
        if pending:
            parts.append(u"{0} edit(s) waiting for Apply".format(pending))
        stale = shtm_rows.stale_count(self.sheets, self.state, self.store)
        if stale:
            # everything visible is a snapshot: nothing moves or disappears
            # under the cursor while it is being edited, and F5 catches up
            parts.append(u"{0} row(s) out of order or outside the filter - F5 "
                         u"to catch up".format(stale))
        self.status(u" - ".join(parts))
        self._paint_group_chip()
        self._paint_edit_buttons()
        self._selection(None, None)

    def _remember_sorts(self):
        """Write the sort levels down whenever they change, so the table opens
        sorted the way it was left. Only when they change: redraw runs on every
        keystroke in a search box."""
        text = shtm_core.sorts_to_text(self.state.sorts)
        if text == self.settings.get("table_sorts", u""):
            return
        self.settings["table_sorts"] = text
        try:
            shtm_core.save_settings(self.settings)
        except Exception:
            pass

    @ui_safe
    def _fit_columns(self, sender, event):
        self.widths = shtm_grid.autofit(self.find("SheetGrid"), self.state)
        self.status(u"columns measured and frozen")

    def _build_legend(self):
        """The footer legend, every state named in full."""
        bar = self.find("LegendBar")
        bar.Children.Clear()
        for key, label in [("RefusedBg", u"Revit refused"),
                           ("StagedBg", u"edited, not yet written"),
                           ("ImportBg", u"from an import"),
                           ("CopiedBg", u"copied from"),
                           ("ReadOnlyBg", u"not editable")]:
            swatch = Border()
            swatch.Width = 11
            swatch.Height = 11
            swatch.CornerRadius = shtm_ui._corner(2)
            swatch.Margin = Thickness(0, 0, 4, 0)
            swatch.SetResourceReference(Border.BackgroundProperty, key)
            swatch.SetResourceReference(Border.BorderBrushProperty, "EdgeBrush")
            swatch.BorderThickness = Thickness(1)
            bar.Children.Add(swatch)
            text = shtm_ui.text_block(label, "Lbl.Muted")
            text.FontSize = 10
            text.Margin = Thickness(0, 0, 12, 0)
            bar.Children.Add(text)

    def _paint_edit_buttons(self):
        pending = self.store.count()
        apply_button = self.find("ApplyBtn")
        apply_button.IsEnabled = pending > 0 and not self.busy
        apply_button.Content = (u"Apply {0} edit(s)".format(pending) if pending
                                else u"Apply edits")
        self.find("ClearEditsBtn").IsEnabled = pending > 0

    def _paint_group_chip(self):
        on = self.state.group_by_sort
        chip = self.find("GroupBySortChip")
        if on:
            keys = self.state.sort_keys()
            chip.Content = u"Grouped: {0}".format(u" > ".join(keys))
            chip.SetResourceReference(_foreground_property(), "OrangeBrush")
        else:
            chip.Content = u"Grouped: off"
            chip.SetResourceReference(_foreground_property(), "MutedBrush")
        for name in ("Group1", "Group2", "Group3"):
            self.find(name).IsEnabled = not on

    @ui_safe
    def _toggle_group_by_sort(self, sender, event):
        self.state.group_by_sort = not self.state.group_by_sort
        self.state.collapsed = set()
        self.settings["group_by_sort"] = shtm_core.bool_text(
            self.state.group_by_sort)
        try:
            shtm_core.save_settings(self.settings)
        except Exception:
            pass
        self.redraw(False)

    @ui_safe
    def _debug_changed(self, sender, event):
        self.settings["debug"] = shtm_core.bool_text(bool(sender.IsChecked))
        try:
            shtm_core.save_settings(self.settings)
        except Exception:
            pass

    def _changed(self, rebuild):
        self.redraw(rebuild)

    def _distinct(self, key, with_counts=False):
        """What a column's tick list offers: the values on the sheets the
        *other* filters let through. A column's own filter is excluded from
        its own list, the way Excel does it - otherwise the values it is
        hiding would not be there to tick back on, and a filter could only
        ever be narrowed."""
        counts = shtm_rows.values_allowed(self.sheets, self.state, key)
        if with_counts:
            return counts
        return sorted(counts.keys(), key=shtm_core.natural_key)

    def status(self, text):
        try:
            self.find("StatusText").Text = text
        except Exception:
            pass

    # ============ grouping ============

    def _fill_group_boxes(self):
        options = [NO_GROUP] + list(self.state.columns)
        for index, name in enumerate(("Group1", "Group2", "Group3")):
            box = self.find(name)
            box.Items.Clear()
            for option in options:
                item = ComboBoxItem()
                item.Content = option
                styled(item, "Cmb.Item")
                box.Items.Add(item)
            current = (self.state.group_by[index]
                       if index < len(self.state.group_by) else NO_GROUP)
            box.SelectedIndex = options.index(current) if current in options else 0

    @ui_safe
    def _grouping_changed(self, sender, event):
        chosen = []
        for name in ("Group1", "Group2", "Group3"):
            text = shtm_ui.combo_text(self.find(name))
            if text and text != NO_GROUP and text not in chosen:
                chosen.append(text)
        self.state.group_by = chosen
        self.state.collapsed = set()
        self.settings["group_by"] = shtm_core.join_list(chosen)
        try:
            shtm_core.save_settings(self.settings)
        except Exception:
            pass
        self.redraw(False)

    @ui_safe
    def _expand_all(self, sender, event):
        self.state.collapsed = set()
        self.redraw(False)

    @ui_safe
    def _collapse_all(self, sender, event):
        # every group key, not just the ones currently drawn: a collapsed
        # parent hides its children, so they are not in self.rows to be found
        held = self.state.collapsed
        self.state.collapsed = set()
        keys = set()
        for row in shtm_grid.compute_rows(self.sheets, self.state)[0]:
            if row.kind == "group":
                keys.add(row.key)
        self.state.collapsed = keys or held
        self.redraw(False)

    @ui_safe
    def _grid_click(self, sender, event):
        row = shtm_ui.hit_row(event.OriginalSource)
        if row is None:
            return
        item = row.Item
        try:
            if item.kind != "group":
                return
        except Exception:
            return
        if item.key in self.state.collapsed:
            self.state.collapsed.discard(item.key)
        else:
            self.state.collapsed.add(item.key)
        event.Handled = True
        self.redraw(False)

    @ui_safe
    def _loading_row(self, sender, event):
        shtm_grid.paint_row(event.Row, event.Row.Item, False)

    @ui_safe
    def _clear_filters(self, sender, event):
        self.state.clear_filters()
        self.find("SearchAll").Text = u""
        self.redraw(True)

    # ============ columns ============

    @ui_safe
    def _columns_popup(self, sender, event):
        popup = Popup()
        popup.Placement = PlacementMode.Bottom
        popup.PlacementTarget = sender
        popup.StaysOpen = False
        popup.AllowsTransparency = True

        shell = Border()
        shell.SetResourceReference(Border.BackgroundProperty, "CardBg")
        shell.SetResourceReference(Border.BorderBrushProperty, "EdgeBrush")
        shell.BorderThickness = Thickness(1)
        shell.CornerRadius = shtm_ui._corner(3)
        shell.Padding = Thickness(8)
        shell.MinWidth = 300

        body = StackPanel()
        search = text_box(u"search parameters", None, "Txt.Small")
        body.Children.Add(search)

        listing = ListBox()
        styled(listing, "Lst.Flat")
        listing.MaxHeight = 420
        listing.Margin = Thickness(0, 6, 0, 0)
        body.Children.Add(listing)
        shell.Child = body
        popup.Child = shell

        boxes = {}
        names = self.available_parameters()

        def fill(needle=u""):
            listing.Items.Clear()
            boxes.clear()
            for name in names:
                if needle and needle.lower() not in name.lower():
                    continue
                item = ListBoxItem()
                styled(item, "Lst.Item")
                box = CheckBox()
                box.Content = name
                box.IsChecked = name in self.state.columns
                styled(box, "Chk.Flat")
                if name in shtm_grid.FIXED_COLUMNS:
                    box.IsEnabled = False
                boxes[name] = box
                item.Content = box
                listing.Items.Add(item)

        @ui_safe
        def typed(inner_sender, inner_event):
            fill(inner_sender.Text or u"")

        search.TextChanged += typed

        @ui_safe
        def closed(inner_sender, inner_event):
            columns = list(shtm_grid.FIXED_COLUMNS)
            for name in names:
                if name in shtm_grid.FIXED_COLUMNS:
                    continue
                box = boxes.get(name)
                if box is not None and box.IsChecked:
                    columns.append(name)
                elif box is None and name in self.state.columns:
                    columns.append(name)
            self.state.columns = columns
            self.state.drop_missing_sorts()
            self.settings["columns"] = shtm_core.join_list(
                [c for c in columns if c not in shtm_grid.FIXED_COLUMNS])
            try:
                shtm_core.save_settings(self.settings)
            except Exception:
                pass
            self._fill_group_boxes()
            self.redraw(True)

        popup.Closed += closed
        fill()
        try:
            sender.Parent.Children.Add(popup)
        except Exception:
            pass
        popup.IsOpen = True

    # ============ selection ============

    def selected_sheets(self):
        """Every sheet the user has picked, whether by row or by cell.

        With SelectionUnit on cells, SelectedItems is empty and only
        SelectedCells is filled - reading one and not the other is what left
        Duplicate greyed out however many rows were highlighted. Both are read
        and the result de-duplicated in table order.
        """
        grid = self.find("SheetGrid")
        picked = []
        seen = set()

        def keep(item):
            try:
                if item is None or item.kind != "sheet" or item.sheet is None:
                    return
                if item.sheet["id"] in seen:
                    return
            except Exception:
                return
            seen.add(item.sheet["id"])
            picked.append(item.sheet)

        try:
            for item in grid.SelectedItems:
                keep(item)
        except Exception:
            pass
        try:
            for cell in grid.SelectedCells:
                keep(cell.Item)
        except Exception:
            pass
        if not picked:
            try:
                keep(grid.CurrentItem)
            except Exception:
                pass
        if not picked:
            return picked
        # table order, not click order
        order = {}
        for index, row in enumerate(self.rows):
            if row.kind == "sheet" and row.sheet is not None:
                order[row.sheet["id"]] = index
        picked.sort(key=lambda sheet: order.get(sheet["id"], 0))
        return picked

    @ui_safe
    def _selection(self, sender, event):
        self._drop_headings()
        picked = self.selected_sheets()
        self.find("DuplicateBtn").IsEnabled = bool(self.sheets) and not self.busy
        if picked:
            self.find("DuplicateBtn").Content = u"Duplicate {0} selected...".format(
                len(picked))
        else:
            self.find("DuplicateBtn").Content = u"Duplicate..."

    def _drop_headings(self):
        """A heading holds no element: it takes no edit, and is never part of
        the selection - otherwise Duplicate counts one as a picked sheet.

        Changing the selection from inside a SelectionChanged handler raises
        the event again, so the flag is not optional.
        """
        if self.dropping:
            return
        grid = self.find("SheetGrid")
        try:
            unwanted = [item for item in grid.SelectedItems
                        if getattr(item, "kind", None) != "sheet"]
        except Exception:
            return
        if not unwanted:
            return
        self.dropping = True
        try:
            for item in unwanted:
                try:
                    grid.SelectedItems.Remove(item)
                except Exception:
                    pass
        finally:
            self.dropping = False

    @ui_safe
    def _select_shown(self, sender, event):
        grid = self.find("SheetGrid")
        grid.SelectAll()

    # ============ export ============

    @ui_safe
    def _export(self, sender, event):
        """The table as shown, pending edits included, to an .xlsx the user
        names - and the same file reads straight back in through Import."""
        dialog = SaveFileDialog()
        dialog.Filter = "Excel workbook (*.xlsx)|*.xlsx|CSV (*.csv)|*.csv"
        dialog.FileName = "sheets.xlsx"
        dialog.Title = "Export the sheet list"
        if not dialog.ShowDialog():
            return
        path = dialog.FileName
        sheets = [row.sheet for row in self.rows if row.kind == "sheet"]
        rows = shtm_edit.export_rows(sheets, self.state.columns, self.store)
        try:
            if path.lower().endswith(".csv"):
                handle = open(path, "wb")
                try:
                    handle.write(shtm_edit.to_csv(rows).encode("utf-8-sig"))
                finally:
                    handle.close()
            else:
                shtm_xlsx.write(path, rows)
            self.status(u"{0} row(s) written to {1}".format(len(rows) - 1, path))
        except Exception as exc:
            self.status(u"could not export: {0}".format(exc))

    # ============ selected cells ============

    def current_column(self):
        """The column the cursor is in, which is what the cell commands work
        on. The grid selects whole rows - that is what Duplicate needs and what
        makes a heading click behave - so the column comes from the current
        cell rather than from a cell selection."""
        grid = self.find("SheetGrid")
        try:
            key = u"{0}".format(grid.CurrentCell.Column.SortMemberPath or u"")
            if key in self.state.columns:
                return key
        except Exception:
            pass
        return self.state.columns[0] if self.state.columns else None

    def selected_cells(self, whole_row=False):
        """The cells the commands act on, as (sheet, column) in table order:
        the selected rows crossed with the current column, or with every column
        when the whole row is wanted. Group headings hold no element, so they
        are never in this list."""
        sheets = self.selected_sheets()
        if not sheets:
            return []
        if whole_row:
            columns = list(self.state.columns)
        else:
            column = self.current_column()
            columns = [column] if column else []
        return [(sheet, column) for sheet in sheets for column in columns]

    def _writable(self, cells):
        kept = []
        blocked = 0
        for sheet, column in cells:
            if column in (sheet.get("readonly") or ()):
                blocked += 1
                continue
            kept.append((sheet, column))
        if blocked:
            self.status(u"{0} cell(s) are read only and were left alone".format(
                blocked))
        return kept

    def _copy(self, cut=False):
        cells = self.selected_cells()
        if not cells:
            return False
        rows = []
        marks = []
        for sheet, column in cells:
            if not rows or rows[-1][0] is not sheet:
                rows.append((sheet, []))
            rows[-1][1].append(self.store.value_of(sheet, column))
            marks.append((sheet["id"], column))
        text = shtm_fill.to_block([values for _sheet, values in rows])
        try:
            Clipboard.SetText(text)
        except Exception:
            self.status(u"the clipboard would not take it")
            return True
        self.store.mark_copied(marks)
        if cut:
            self.store.take([(sheet["id"], column,
                              sheet["values"].get(column, u""), u"")
                             for sheet, column in self._writable(cells)])
        self.redraw(True)
        self.status(u"{0} cell(s) copied".format(len(cells)))
        return True

    def _paste(self):
        cells = self._writable(self.selected_cells())
        if not cells:
            return False
        try:
            text = Clipboard.GetText()
        except Exception:
            text = u""
        block = shtm_fill.parse_block(text)
        if not block:
            return False
        data = [row.sheet for row in self.rows if row.kind == "sheet"]
        plan = shtm_fill.paste_plan(block, cells, self.state.columns, data)
        edits = []
        for sheet, column, value in plan:
            if column in (sheet.get("readonly") or ()):
                continue
            edits.append((sheet["id"], column,
                          sheet["values"].get(column, u""), value))
        changed = self.store.take(edits)
        self.store.clear_copied()
        self.redraw(True)
        self.status(u"{0} cell(s) pasted".format(changed))
        return True

    def _fill_down(self, series):
        """Ctrl+D fills the selection from its first row; Ctrl+E does the same
        but numbers a value that has none."""
        cells = self._writable(self.selected_cells())
        if len(cells) < 2:
            return False
        by_column = {}
        for sheet, column in cells:
            by_column.setdefault(column, []).append(sheet)
        edits = []
        for column in by_column:
            sheets = by_column[column]
            seed = self.store.value_of(sheets[0], column)
            plan = (shtm_fill.fill_series if series else shtm_fill.fill_plan)(
                [seed], len(sheets) - 1, True)
            for index, sheet in enumerate(sheets[1:]):
                edits.append((sheet["id"], column,
                              sheet["values"].get(column, u""), plan[index]))
        changed = self.store.take(edits)
        self.redraw(True)
        self.status(u"{0} cell(s) filled".format(changed))
        return True

    def _clear_cells(self):
        cells = self._writable(self.selected_cells())
        if not cells:
            return False
        changed = self.store.take([(sheet["id"], column,
                                    sheet["values"].get(column, u""), u"")
                                   for sheet, column in cells])
        self.redraw(True)
        self.status(u"{0} cell(s) cleared".format(changed))
        return True

    def _edit_current(self):
        grid = self.find("SheetGrid")
        try:
            cells = list(grid.SelectedCells)
        except Exception:
            return False
        if not cells:
            return False
        cell = cells[0]
        row = cell.Item
        if row is None or getattr(row, "kind", None) != "sheet":
            return False
        key = u"{0}".format(cell.Column.SortMemberPath or u"")
        container = _cell_container(grid, row, cell.Column)
        if not key or container is None:
            return False
        self._open_cell_editor(container, row.sheet, key)
        return True

    def _undo(self):
        if not self.store.undo():
            return False
        self.redraw(True)
        self.status(u"undone - {0} edit(s) waiting".format(self.store.count()))
        return True

    def _redo(self):
        if not self.store.redo():
            return False
        self.redraw(True)
        self.status(u"redone - {0} edit(s) waiting".format(self.store.count()))
        return True

    def _cell_menu(self):
        """Right-click a cell. Ctrl+C, Ctrl+V and the rest are on the
        keyboard, but this is where people look for them."""
        menu = ContextMenu()
        styled(menu, "Menu.Flat")

        def entry(text, action, gap=False):
            if gap:
                menu.Items.Add(Separator())
            item = MenuItem()
            item.Header = text
            styled(item, "MenuItem.Flat")
            item.Click += ui_safe(action)
            menu.Items.Add(item)
            return item

        entry(u"Copy\tCtrl+C", lambda s, e: self._copy())
        entry(u"Cut\tCtrl+X", lambda s, e: self._copy(True))
        entry(u"Paste\tCtrl+V", lambda s, e: self._paste())
        entry(u"Fill down\tCtrl+D", lambda s, e: self._fill_down(False), True)
        entry(u"Fill series\tCtrl+E", lambda s, e: self._fill_down(True))
        entry(u"Clear\tDelete", lambda s, e: self._clear_cells())
        entry(u"Create unique sequence",
              lambda s, e: self._unique_sequence(self._current_column()), True)
        entry(u"Undo\tCtrl+Z", lambda s, e: self._undo(), True)
        entry(u"Redo\tCtrl+Y", lambda s, e: self._redo())
        return menu

    def _current_column(self):
        return self.current_column() or self.state.columns[0]

    # ============ duplicates ============

    def _column_menu(self, key):
        menu = ContextMenu()
        styled(menu, "Menu.Flat")

        def entry(text, action):
            item = MenuItem()
            item.Header = text
            styled(item, "MenuItem.Flat")
            item.Click += ui_safe(action)
            menu.Items.Add(item)

        entry(u"Highlight duplicates", lambda s, e: self._highlight_dups(key))
        entry(u"Isolate duplicates", lambda s, e: self._isolate_dups(key))
        entry(u"Create unique sequence", lambda s, e: self._unique_sequence(key))
        entry(u"Clear this column's highlighting",
              lambda s, e: self._clear_highlight(key))
        entry(u"Clear this column's filter", lambda s, e: self._clear_filter(key))
        return menu

    def _dup_groups(self, key):
        sheets = [row.sheet for row in self.rows if row.kind == "sheet"]
        values = [self.store.value_of(sheet, key) for sheet in sheets]
        return sheets, shtm_fill.duplicate_groups(values)

    def _highlight_dups(self, key):
        _sheets, groups = self._dup_groups(key)
        if not groups:
            self.highlights.pop(key, None)
            self.status(u"no duplicate values in {0}".format(key))
        else:
            self.highlights[key] = dict(
                [(value, index) for index, (value, _at) in enumerate(groups)])
            self.status(u"{0} set(s) of duplicates in {1}".format(len(groups), key))
        self.redraw(True)

    def _isolate_dups(self, key):
        _sheets, groups = self._dup_groups(key)
        if not groups:
            self.status(u"no duplicate values in {0}".format(key))
            return
        self._highlight_dups(key)
        # reuse the column's own tick filter, so it composes with everything else
        allowed = set()
        for value, _at in groups:
            for candidate in self._distinct(key):
                if u"{0}".format(candidate).strip().lower() == value:
                    allowed.add(candidate)
        self.state.filters[key] = allowed
        self.redraw(True)

    def _unique_sequence(self, key):
        cells = self._writable([(sheet, key) for sheet in self.selected_sheets()])
        if not cells:
            self.status(u"pick the rows to renumber first")
            return
        taken = [self.store.value_of(sheet, key) for sheet in self.sheets
                 if sheet not in [c[0] for c in cells]]
        values = [self.store.value_of(sheet, key) for sheet, _c in cells]
        plan = shtm_fill.unique_sequence(values, taken)
        edits = []
        for index, (sheet, column) in enumerate(cells):
            _old, new = plan[index]
            edits.append((sheet["id"], column,
                          sheet["values"].get(column, u""), new))
        changed = self.store.take(edits)
        self.redraw(True)
        self.status(u"{0} value(s) renumbered to be unique".format(changed))

    def _clear_highlight(self, key):
        self.highlights.pop(key, None)
        self.redraw(True)

    def _clear_filter(self, key):
        self.state.filters.pop(key, None)
        self.state.searches.pop(key, None)
        self.redraw(True)

    # ============ editing ============

    def _shown_sheets(self):
        return [row.sheet for row in self.rows if row.kind == "sheet"]

    @ui_safe
    def _edit_dialog(self, sender, event):
        dialog = shtm_edits.EditDialog(
            self.settings, self.state.columns, self.selected_sheets(),
            self._shown_sheets(), self.store, self.mode, self.window)
        edits = dialog.show()
        if edits:
            changed = self.store.take(edits)
            self.redraw(False)
            self.status(u"{0} edit(s) added - {1} waiting for Apply".format(
                changed, self.store.count()))

    @ui_safe
    def _discard_edits(self, sender, event):
        count = self.store.count()
        if not count:
            return
        if shtm_ui.confirm(self.mode, self.window, u"Discard edits",
                           u"Throw away {0} pending edit(s)? Nothing has been "
                           u"written to the model.".format(count),
                           u"Discard", u"Keep them"):
            self.store.clear()
            self.redraw(False)

    @ui_safe
    def _cell_double_click(self, sender, event):
        """Edit one cell in place: a popup with a text box over the cell.
        Enter keeps it, Escape drops it, clicking away keeps it."""
        cell = _cell_under(event.OriginalSource)
        if cell is None:
            return
        try:
            key = u"{0}".format(cell.Column.SortMemberPath or u"")
            row = cell.DataContext
        except Exception:
            return
        if not key or row is None or getattr(row, "kind", None) != "sheet":
            return
        sheet = row.sheet
        if sheet is None:
            return
        if key in (sheet.get("readonly") or ()):
            self.status(u"{0} is not editable on this sheet".format(key))
            return
        self._open_cell_editor(cell, sheet, key)

    def _open_cell_editor(self, cell, sheet, key):
        self._close_cell_editor(True)
        popup = Popup()
        popup.Placement = PlacementMode.Relative
        popup.PlacementTarget = cell
        popup.StaysOpen = False
        popup.AllowsTransparency = True
        box = text_box(u"", None, "Txt.Field")
        box.Text = self.store.value_of(sheet, key)
        try:
            box.MinWidth = max(160, cell.ActualWidth)
        except Exception:
            box.MinWidth = 160
        box.Tag = key
        popup.Child = box
        state = {"keep": True}

        @ui_safe
        def key_down(sender, e):
            if e.Key == Key.Enter or e.Key == Key.Return:
                popup.IsOpen = False
            elif e.Key == Key.Escape:
                state["keep"] = False
                popup.IsOpen = False

        @ui_safe
        def closed(sender, e):
            if state["keep"]:
                changed = self.store.set(
                    sheet["id"], key, sheet["values"].get(key, u""),
                    box.Text or u"")
                self.redraw(False)
                if changed:
                    self.status(u"{0} edit(s) waiting for Apply".format(
                        self.store.count()))
            self.cell_editor = None
        # duplicate highlighting, per column: value -> colour number
        self.highlights = {}
        self.dropping = False
        # column widths, measured once after the first render and frozen
        self.widths = {}

        box.KeyDown += key_down
        popup.Closed += closed
        self.cell_editor = popup
        popup.IsOpen = True
        try:
            box.Focus()
            box.SelectAll()
        except Exception:
            pass

    def _close_cell_editor(self, keep):
        popup = self.cell_editor
        if popup is None:
            return
        try:
            popup.IsOpen = False
        except Exception:
            pass
        self.cell_editor = None
        # duplicate highlighting, per column: value -> colour number
        self.highlights = {}
        self.dropping = False
        # column widths, measured once after the first render and frozen
        self.widths = {}

    @ui_safe
    def _apply_edits(self, sender, event):
        if self.busy or not self.store.count():
            return
        blocked = shtm_edit.blockers(self.store, self.sheets)
        if blocked:
            shtm_ui.message(self.mode, self.window, u"Cannot apply",
                            u"\n".join(blocked))
            return
        summary = shtm_edit.apply_summary(self.store)
        if shtm_core.as_bool(self.settings.get("confirm_before_write", "1")):
            if not shtm_ui.confirm(self.mode, self.window, u"About to write",
                                   summary, u"Apply", u"Not yet"):
                return
        job = {"edits": self.store.jobs(), "doc": self.doc,
               "debug": bool(self.find("DebugBox").IsChecked)}
        self.busy = True
        self._paint_edit_buttons()
        self.status(u"applying {0} edit(s)...".format(len(job["edits"])))
        self.guard.active = True
        self.guard.suppressed = []
        self.editor.job = job
        request = self.edit_event.Raise()
        if request != ExternalEventRequest.Accepted:
            self.busy = False
            self.guard.active = False
            self.editor.job = None
            self._paint_edit_buttons()
            self.status(u"Revit would not accept the request ({0})".format(request))

    def _edit_results(self, report):
        self.guard.active = False
        self.busy = False
        problems = report.get("problems") or []
        written = report.get("written", 0)
        # every edit that provably landed is no longer pending; the rest stay
        # orange so they can be looked at and tried again
        if not problems:
            self.store.clear()
        else:
            self._drop_written(report)
            for refusal in report.get("refused") or []:
                self.store.mark_refused(refusal["id"], refusal["column"],
                                        refusal.get("reason", u""))
        self.reload()
        lines = [u"{0} cell(s) written and read back".format(written)]
        if self.guard.suppressed:
            lines.append(u"Revit dialogs answered during the run: {0}".format(
                u", ".join(sorted(set(self.guard.suppressed)))))
        if problems:
            lines.append(u"")
            lines.append(u"Needs a look:")
            for problem in problems:
                lines.append(u"  - {0}".format(problem))
        show = self.settings.get("show_results", "needed")
        if show != "never" and (show == "always" or problems):
            shtm_ui.message(self.mode, self.window, u"Edits applied",
                            u"\n".join(lines))
        else:
            self.status(lines[0])
        if shtm_core.as_bool(self.settings.get("debug")) and report.get("debug"):
            self._debug_report(report)

    def _drop_written(self, report):
        """After a partial write, keep pending only what the model does not
        already show. The reload reads the sheets back, so comparing against
        that is the honest test."""
        try:
            fresh = dict([(s["id"], s) for s in shtm_model.read_sheets(
                self.doc, self.settings)])
        except Exception:
            return
        for key in list(self.store.pending.keys()):
            sheet = fresh.get(key[0])
            if sheet is None:
                continue
            shown = u"{0}".format(sheet["values"].get(key[1], u"") or u"")
            if shown == self.store.pending[key]:
                self.store.drop(key[0], key[1])

    @ui_safe
    def _import_xlsx(self, sender, event):
        dialog = OpenFileDialog()
        dialog.Filter = "Excel workbook (*.xlsx)|*.xlsx|CSV (*.csv)|*.csv"
        dialog.Title = "Import a sheet list"
        if not dialog.ShowDialog():
            return
        path = dialog.FileName
        try:
            if path.lower().endswith(".csv"):
                handle = open(path, "rb")
                try:
                    text = handle.read().decode("utf-8-sig")
                finally:
                    handle.close()
                rows = shtm_edit.from_csv(text)
            else:
                rows = shtm_xlsx.read(path)
        except Exception as exc:
            self.status(u"could not read {0}: {1}".format(path, exc))
            return
        edits, unknown, ignored = shtm_edit.import_diff(
            self.sheets, self.state.columns, rows)
        lines = [u"{0} cell(s) differ from the model".format(len(edits))]
        if ignored:
            lines.append(u"Columns not in the table, ignored: {0}".format(
                u", ".join(ignored)))
        if unknown:
            lines.append(u"Sheet numbers matching nothing: {0}".format(
                u", ".join(unknown[:20]) +
                (u"..." if len(unknown) > 20 else u"")))
        if not edits:
            shtm_ui.message(self.mode, self.window, u"Import", u"\n".join(lines))
            return
        lines.append(u"")
        lines.append(u"Add them as pending edits? Nothing is written until Apply.")
        if shtm_ui.confirm(self.mode, self.window, u"Import", u"\n".join(lines),
                           u"Add them", u"Cancel"):
            changed = self.store.take(edits)
            self.redraw(False)
            self.status(u"{0} edit(s) added from {1}".format(changed, path))

    # ============ settings and theme ============

    @ui_safe
    def _settings(self, sender, event):
        dialog = shtm_settings.SettingsWindow(
            self.doc, self.settings, self.mode, self.window)
        saved = dialog.show()
        if saved is None:
            return
        self.settings = saved
        self.mode = saved.get("theme", "auto")
        theme.apply(self.window, self.mode)
        self.find("ThemeChip").Content = theme.label(self.mode)
        self._columns_from_settings()
        self.reload()
        # an open Duplicate window follows: the theme, and the stars beside
        # templates whose presets were just added or taken away
        if self.builder is not None:
            try:
                self.builder.apply_theme(self.mode)
                self.builder.presets_changed()
            except Exception:
                pass

    @ui_safe
    def _cycle_theme(self, sender, event):
        self._set_theme(theme.next_mode(self.mode))

    # ============ the duplicate ============

    @ui_safe
    def _duplicate(self, sender, event):
        """Open the builder. It is modeless and stays open while Revit works,
        so its rows can go green as each sheet lands; the rows picked here are
        ticked as its source sheets to start with, and more can be ticked
        there."""
        picked = [s["id"] for s in self.selected_sheets()]
        if self.builder is not None:
            try:
                if self.builder.window.IsVisible:
                    self.builder.use_picked(picked)
                    self.builder.window.Activate()
                    return
            except Exception:
                pass
            self.builder = None
        builder = shtm_duplicate.BuilderWindow(
            self.doc, self.settings, self.sheets, picked, self.mode, self.window,
            launch=self._launch_duplicate, theme_changed=self._set_theme,
            get_settings=lambda: self.settings,
            template_job=self.run_template_job)
        builder.window.Closed += ui_safe(lambda s, e: self._builder_closed(builder))
        self.builder = builder
        builder.show()

    def _builder_closed(self, builder):
        if self.builder is builder:
            self.builder = None

    def run_template_job(self, job):
        """Send a view template job to Revit. True when Revit took the
        request; the job's own done callback hears how it went."""
        if self.busy:
            self.status(u"busy - wait for the last run to finish")
            return False
        job["doc"] = self.doc
        self.template_handler.jobs.append(job)
        request = self.template_event.Raise()
        # Pending: the event is already raised and waiting for Revit to go
        # idle - this job is in the queue it will run, so it counts as taken
        if request in (ExternalEventRequest.Accepted, ExternalEventRequest.Pending):
            return True
        try:
            self.template_handler.jobs.remove(job)
        except ValueError:
            pass
        self.status(u"Revit would not accept the view template request ({0})"
                    .format(request))
        return False

    def _launch_duplicate(self, job):
        """Raise the external event for a job the builder has put together.
        True when Revit has accepted it; the builder hears the rest through
        the job's own callbacks."""
        if self.busy:
            self.status(u"busy - wait for the last run to finish")
            return False
        job["debug"] = bool(self.find("DebugBox").IsChecked)
        job["doc"] = self.doc
        self.last_report = None
        self.busy = True
        self.find("DuplicateBtn").IsEnabled = False
        self.status(u"creating sheets...")
        self.guard.active = True
        self.guard.suppressed = []
        self.handler.job = job
        request = self.event.Raise()
        if request != ExternalEventRequest.Accepted:
            self.handler.job = None
            self.guard.active = False
            self.busy = False
            self.status(u"Revit would not accept the request ({0}) - "
                        u"nothing was written".format(request))
            self._selection(None, None)
            return False
        self._watch(job)
        return True

    def _watch(self, job):
        """Accepted is not started. If Revit has not picked the job up within
        20 seconds - a modal dialog open in Revit, a command running - the job
        is withdrawn and both windows are freed, rather than left busy for
        ever with no way to close them. Once Execute has taken the job it is
        no longer in handler.job and the watchdog does nothing."""
        def withdraw():
            if self.handler.job is not job:
                return
            self.handler.job = None
            self.guard.active = False
            report = {"sheets": [], "views": 0, "reused": 0, "placed": 0,
                      "confirmed": 0, "notes": [], "debug": [],
                      "problems": [u"Revit did not start the job within 20 "
                                   u"seconds - is a dialog or command open in "
                                   u"Revit? Nothing was written."]}
            for callback in (job.get("done"), self._results):
                if callback is None:
                    continue
                try:
                    callback(report)
                except Exception:
                    shtm_ui.log(u"a withdrawn job's callback failed")

        timer = shtm_ui.debounce(20000, withdraw)
        timer.Start()
        self.watchdog = timer

    def _set_theme(self, mode):
        """One theme for the tool: the chip in either window sets both."""
        self.mode = mode
        theme.apply(self.window, self.mode)
        self.find("ThemeChip").Content = theme.label(self.mode)
        self.settings["theme"] = self.mode
        try:
            shtm_core.save_settings(self.settings)
        except Exception:
            pass
        self.redraw(True)
        if self.builder is not None:
            try:
                self.builder.apply_theme(mode)
            except Exception:
                pass

    def _progress(self, percent, done, total, label=u""):
        """Called from inside the external event, on Revit's own thread - which
        is also the window's. The duplicator only reports between transactions,
        never inside one, so pumping at Render priority to make the band
        actually move is safe here.
        """
        try:
            band = self.find("ProgressBand")
            fill = self.find("ProgressFill")
            share = max(0, min(100, int(percent))) / 100.0
            fill.Width = max(0.0, band.ActualWidth) * share
            self.find("ProgressText").Text = u"{0}  {1} of {2}".format(
                label, done, total).strip()
            _pump(self.window.Dispatcher)
        except Exception:
            pass

    def _results(self, report):
        self.guard.active = False
        self.busy = False
        self.last_report = report
        debug = shtm_core.as_bool(self.settings.get("debug"))
        if debug and self.guard.suppressed:
            report.setdefault("debug", []).append(
                u"Revit dialogs answered: {0}".format(
                    u", ".join(sorted(set(self.guard.suppressed)))))
        self.find("ProgressBand").Visibility = Visibility.Collapsed
        self.find("ProgressText").Text = u""
        # the sheets just made join the Revit-selection filter, so a table
        # showing only the selected sheets does not hide what the run made
        made = [entry.get("id") for entry in (report.get("sheets") or [])]
        if made and self.revit_picked:
            self.revit_picked = self.revit_picked + [i for i in made
                                                     if i not in self.revit_picked]
            if self.state.only_ids is not None:
                self.state.only_ids = set(self.revit_picked)
            self.find("OnlyPickedBox").Content = u"Only the {0} selected in Revit, and the {1} just made".format(
                shtm_core.plural(len(self.revit_picked) - len(made), u"sheet"),
                len(made))
        confirmed = report.get("confirmed", 0)
        problems = report.get("problems") or []
        self.status(u"{0} sheet(s) made, {1} view(s) created, {2} view(s) placed"
                    u"{3}".format(confirmed, report.get("views", 0),
                                  report.get("placed", 0),
                                  u", {0} to look at".format(len(problems))
                                  if problems else u""))
        self.reload()

        show = self.settings.get("show_results", "needed")
        quiet = (show == "never" or
                 (show == "needed" and not problems and not report.get("notes")))
        if quiet:
            self._offer_to_open(report)
            if debug:
                self._debug_report(report)
            return
        lines = [u"{0} sheet(s) are in the model on their new numbers".format(confirmed),
                 u"{0} view(s) created, {1} reused, {2} placed on the new sheets".format(
                     report.get("views", 0), report.get("reused", 0),
                     report.get("placed", 0))]
        if self.guard.suppressed:
            lines.append(u"Revit dialogs answered during the run: {0}".format(
                u", ".join(sorted(set(self.guard.suppressed)))))
        if problems:
            lines.append(u"")
            lines.append(u"Needs a look:")
            for problem in problems:
                lines.append(u"  - {0}".format(problem))
        shtm_ui.message(self.mode, self.window, u"Duplicate finished",
                        u"\n".join(lines))
        self._offer_to_open(report)
        if debug:
            self._debug_report(report)

    def _offer_to_open(self, report):
        made = report.get("sheets") or []
        if not made:
            return
        labels = [u"{0}  -  {1}".format(s.get("number"), s.get("name"))
                  for s in made]
        picked = shtm_ui.choose(
            self.mode, self.window, u"Open a new sheet",
            u"{0} new sheet(s). Open one of them?".format(len(made)), labels)
        if picked is None:
            return
        index = labels.index(picked) if picked in labels else 0
        self.opener.sheet_id = made[index].get("id")
        request = self.open_event.Raise()
        if request != ExternalEventRequest.Accepted:
            self.status(u"Revit would not accept the request to open the sheet "
                        u"({0})".format(request))

    def _debug_report(self, report):
        """Everything the run saw, in one place, written to a file and shown -
        so a failure can be sent back rather than described."""
        lines = report.get("debug") or []
        text = u"\n".join(lines) if lines else u"the run recorded nothing"
        path = u""
        try:
            folder = shtm_core.settings_folder()
            if not os.path.isdir(folder):
                os.makedirs(folder)
            path = os.path.join(folder, "sheet_manager_debug.txt")
            handle = open(path, "wb")
            try:
                handle.write(text.encode("utf-8"))
            finally:
                handle.close()
        except Exception:
            path = u""
        head = (u"Written to {0}\n\n".format(path) if path
                else u"It could not be written to a file.\n\n")
        choice = shtm_ui.message(self.mode, self.window, u"Debug report",
                                 head + text,
                                 [u"Copy to clipboard", u"Close"],
                                 width=900, height=680)
        if choice == 0:
            try:
                from System.Windows import Clipboard, HorizontalAlignment, VerticalAlignment
                Clipboard.SetText(text)
                self.status(u"the debug report is on the clipboard")
            except Exception:
                self.status(u"the clipboard would not take it - the file is at "
                            u"{0}".format(path))

    # ============ lifetime ============

    def _closing(self):
        try:
            shtm_core.save_settings(self.settings)
        except Exception:
            pass

    def _closing_guard(self, sender, event):
        if self.busy:
            event.Cancel = True
            self.status(u"Revit is part way through a job - this window closes "
                        u"when it finishes")

    def show(self):
        try:
            helper = WindowInteropHelper(self.window)
            helper.Owner = self.uiapp.MainWindowHandle
        except Exception:
            pass
        self.window.ContentRendered += ui_safe(self._first_render)
        self.window.Show()
        return self.window

    @ui_safe
    def _first_render(self, sender, event):
        """Measure the columns after the first render, not in the constructor:
        the row containers do not exist until the grid has been through a
        layout pass, and a fit run earlier sizes every column to its header
        alone."""
        if self.widths:
            return
        self.widths = shtm_grid.autofit(self.find("SheetGrid"), self.state)


def _bold():
    from System.Windows import FontWeights
    return FontWeights.Bold


def _foreground_property():
    from System.Windows.Controls import Control
    return Control.ForegroundProperty


def _cell_container(grid, row, column):
    """The DataGridCell for a row and column, or None when the row is not
    realised - a virtualising grid only builds what is on screen."""
    try:
        container = grid.ItemContainerGenerator.ContainerFromItem(row)
        if container is None:
            return None
        presenter = _descendant(container, "DataGridCellsPresenter")
        if presenter is None:
            return None
        index = list(grid.Columns).index(column)
        return presenter.ItemContainerGenerator.ContainerFromIndex(index)
    except Exception:
        return None


def _descendant(element, type_name):
    try:
        count = VisualTreeHelper.GetChildrenCount(element)
    except Exception:
        return None
    for index in range(count):
        child = VisualTreeHelper.GetChild(element, index)
        if type(child).__name__ == type_name:
            return child
        found = _descendant(child, type_name)
        if found is not None:
            return found
    return None


def _cell_under(element):
    """Walk up the visual tree from whatever was double-clicked to the
    DataGridCell it lives in, or None if it was not in one."""
    from System.Windows.Controls import DataGridCell
    current = element
    for _ in range(40):
        if current is None:
            return None
        if isinstance(current, DataGridCell):
            return current
        try:
            current = VisualTreeHelper.GetParent(current)
        except Exception:
            try:
                current = current.Parent
            except Exception:
                return None
    return None


def _nothing():
    """An empty Action, so the dispatcher can be asked to render without being
    asked to do anything else."""
    return None


def _pump(dispatcher):
    """Let the window repaint. Both argument orders of Dispatcher.Invoke are
    in the framework and which one an engine binds to varies, so both are
    tried rather than assumed."""
    action = Action(_nothing)
    try:
        dispatcher.Invoke(DispatcherPriority.Render, action)
        return True
    except Exception:
        pass
    try:
        dispatcher.Invoke(action, DispatcherPriority.Render)
        return True
    except Exception:
        return False


def _touch():
    """Keeps Orientation and button referenced for the bench import rule."""
    return Orientation is not None and button is not None
