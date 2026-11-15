# -*- coding: utf-8 -*-
"""RevoBIM PY - Workset Management : the window.

Modal - nothing here needs a pick in the model - so every write runs inside
the command and no ExternalEvent is involved.

Manage Worksets: the table is a DataTable bound through its DefaultView,
filtered on a hidden 'vis' column and sorted on a hidden 'gkey' column, so a
row being edited never moves or disappears under the cursor.  F5 re-takes
the sort and the filters.  Everything staged lives on core.WsRow objects;
the table is a view of them.

Workset Assigner: one row per workset, each with a category picker that only
offers what no other workset holds.
"""

import os

import wsm_clr  # noqa: F401  (assemblies first)

from System import AppDomain                                           # noqa: E402
from System.Data import DataTable                                      # noqa: E402
from System.Diagnostics import Process                                 # noqa: E402
from System.Windows import (CornerRadius, GridLength, GridUnitType,      # noqa: E402
                            HorizontalAlignment, Thickness, VerticalAlignment,
                            Visibility)
from System.Windows.Controls import (Border, CheckBox, ColumnDefinition,  # noqa: E402
                                     DataGridCell, DataGridCellInfo,
                                     DataGridEditingUnit,
                                     DataGridLength, DataGridLengthUnitType,
                                     DataGridTemplateColumn, DataGridTextColumn,
                                     Grid, Orientation,
                                     RowDefinition, ScrollBarVisibility,
                                     ScrollViewer, StackPanel, TextBlock, TextBox,
                                     WrapPanel)
from System.Windows.Controls.Primitives import (PlacementMode, Popup,     # noqa: E402
                                                ToggleButton)
from System.Windows.Data import Binding                                # noqa: E402
from System.Windows.Input import Cursors, Key, Keyboard, ModifierKeys  # noqa: E402

import wsm_core as core                                                # noqa: E402
import wsm_revit as revit                                              # noqa: E402
import wsm_runner as runner_module                                     # noqa: E402
import wsm_scope                                                       # noqa: E402
import wsm_ui as ui                                                    # noqa: E402
import wsm_xlsx as xlsx                                                # noqa: E402

LAYOUT_PATH = os.path.join(ui.HERE, "WorksetManagement.xaml")

TABLE_COLUMNS = ("key", "exp", "colour", "name", "count", "cats", "editable", "visible",
                 "owner", "change", "state", "vis", "gkey")

WINDOW_KEY = "RevoBIM.WorksetManagement.window." + core.VERSION
DOC_KEY = "RevoBIM.WorksetManagement.document." + core.VERSION

# Windows and their runners live here, so the persistent engine never
# collects them while they are open.
PARKED = []

# column -> (stars, minimum width, cell style, filter placeholder)
GRID_COLUMNS = [
    ("name", 2.2, 170, "WsNameText", u"Filter names"),
    ("count", 0.7, 80, "WsCountText", u"e.g. >0"),
    ("cats", 2.4, 170, "WsCatsText", u"e.g. cable tray"),
    ("editable", 0.65, 76, "WsEditableText", u"Yes / No"),
    ("visible", 0.8, 96, "WsVisibleText", u"Yes / No"),
    ("owner", 0.9, 92, "WsPlainText", u"Filter"),
    ("change", 2.0, 150, "WsChangeText", u"Filter"),
]

EXPAND_GLYPH = u"\u25B8"         # closed
COLLAPSE_GLYPH = u"\u25BE"       # open
DETAIL_ITEM_WIDTH = 250.0

SORT_KEYS = ("OrangeBrush", "BlueBrush", "GreenBrush")
CLEAR = "#00000000"


# ================================================================ assigner row

class AssignRow(object):
    """One workset in the assigner: name, element count, category picker."""

    def __init__(self, owner, record):
        self.owner = owner
        self.record = record
        self.name = record.name
        self.boxes = {}
        self.suspend = False
        self.list_panel = None
        self.search = None

        card = Border()
        ui.res(card, Border.BackgroundProperty, "CardBrush")
        ui.res(card, Border.BorderBrushProperty, "EdgeBrush")
        card.BorderThickness = Thickness(1)
        card.CornerRadius = CornerRadius(4)
        card.Margin = Thickness(0, 0, 0, 5)
        card.Padding = Thickness(10, 6, 10, 6)

        grid = Grid()
        for stars in ((2.2, True), (110, False), (3.0, True)):
            column = ColumnDefinition()
            column.Width = GridLength(stars[0], GridUnitType.Star if stars[1] else GridUnitType.Pixel)
            grid.ColumnDefinitions.Add(column)

        line = StackPanel()
        line.Orientation = Orientation.Horizontal
        swatch = Border()
        swatch.Width = 13
        swatch.Height = 13
        swatch.CornerRadius = CornerRadius(3)
        swatch.Margin = Thickness(0, 0, 8, 0)
        swatch.Background = ui.brush(owner.colours.get(record.iid, u"#00000000"))
        ui.res(swatch, Border.BorderBrushProperty, "EdgeBrush")
        swatch.BorderThickness = Thickness(1)
        swatch.ToolTip = u"This workset's colour in the Workset Management 3D view"
        line.Children.Add(swatch)
        line.Children.Add(ui.text_block(record.name, 12, "TextBrush", True))
        grid.Children.Add(line)

        count = ui.text_block(u"{0}".format(record.count), 12, "OrangeBrush", True)
        count.HorizontalAlignment = HorizontalAlignment.Right
        count.Margin = Thickness(0, 0, 14, 0)
        Grid.SetColumn(count, 1)
        grid.Children.Add(count)

        holder = Grid()
        Grid.SetColumn(holder, 2)
        toggle = ToggleButton()
        ui.style(toggle, "WsDropToggle")
        toggle.HorizontalAlignment = HorizontalAlignment.Stretch
        label = ui.text_block(u"Select categories...", 12, "MutedBrush")
        toggle.Content = label
        toggle.Checked += self.on_open
        toggle.Unchecked += self.on_close
        holder.Children.Add(toggle)
        self.toggle = toggle
        self.label = label

        popup = Popup()
        popup.PlacementTarget = toggle
        popup.Placement = PlacementMode.Bottom
        popup.StaysOpen = False
        popup.AllowsTransparency = True
        popup.Closed += self.on_popup_closed
        holder.Children.Add(popup)      # in the logical tree, so styles resolve
        self.popup = popup

        grid.Children.Add(holder)
        card.Child = grid
        self.element = card
        self.refresh_label()

    def selected(self):
        return self.owner.selections.get(self.name, set())

    def refresh_label(self):
        count = core.selection_count(self.selected(), self.owner.scan)
        if count:
            self.label.Text = u"{0} selected".format(count)
            ui.res(self.label, TextBlock.ForegroundProperty, "BlueBrush")
            names = []
            for key in sorted(self.selected()):
                entry = self.owner.scan.by_key.get(key)
                if entry is not None and entry.parent_key not in self.selected():
                    names.append(entry.label if entry.parent_key is None else
                                 u"{0} / {1}".format(self.owner.scan.by_key[entry.parent_key].label,
                                                     entry.label))
            self.toggle.ToolTip = u"\n".join(names)
        else:
            self.label.Text = u"Select categories..."
            ui.res(self.label, TextBlock.ForegroundProperty, "MutedBrush")
            self.toggle.ToolTip = None

    def on_open(self, sender, args):
        try:
            self.build_popup()
            self.popup.IsOpen = True
        except Exception as err:
            self.owner.status(u"Could not open the category list: {0}".format(err))

    def on_close(self, sender, args):
        self.popup.IsOpen = False

    def on_popup_closed(self, sender, args):
        self.toggle.IsChecked = False

    def build_popup(self):
        shell = Border()
        ui.res(shell, Border.BackgroundProperty, "FieldBrush")
        ui.res(shell, Border.BorderBrushProperty, "ChromeBrush")
        shell.BorderThickness = Thickness(1)
        shell.Padding = Thickness(8)
        shell.MinWidth = max(340.0, self.toggle.ActualWidth)
        outer = StackPanel()
        search = TextBox()
        ui.style(search, "WsTextBox")
        search.Tag = u"Search categories"
        search.Height = 26
        search.Margin = Thickness(0, 0, 0, 6)
        search.TextChanged += self.on_search
        outer.Children.Add(search)
        self.search = search
        viewer = ScrollViewer()
        viewer.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
        viewer.HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled
        viewer.MaxHeight = 380
        self.list_panel = StackPanel()
        viewer.Content = self.list_panel
        outer.Children.Add(viewer)
        hint = ui.text_block(u"A category given to another workset is not offered here.",
                             10, "MutedBrush", wrap=True)
        hint.Margin = Thickness(2, 6, 2, 0)
        outer.Children.Add(hint)
        shell.Child = outer
        self.popup.Child = shell
        self.fill_list(u"")

    def fill_list(self, needle):
        self.list_panel.Children.Clear()
        self.boxes = {}
        lines = core.picker_lines(self.name, self.owner.claims, self.owner.scan, needle)
        for entry, depth, enabled in lines:
            box = CheckBox()
            ui.style(box, "WsCheck")
            box.Margin = Thickness(2 + depth * 20, 3, 2, 3)
            box.IsChecked = entry.key in self.selected()
            box.IsEnabled = enabled
            box.Tag = entry.key
            if not enabled:
                box.ToolTip = u"Some of its Service Types are on another workset - tick them one by one."
            line = StackPanel()
            line.Orientation = Orientation.Horizontal
            line.Children.Add(ui.text_block(entry.label, 12,
                                            "MutedBrush" if depth else "TextBrush", depth == 0))
            line.Children.Add(ui.text_block(u"   {0}".format(entry.count), 11, "OrangeBrush"))
            box.Content = line
            box.Checked += self.on_tick
            box.Unchecked += self.on_tick
            self.boxes[entry.key] = box
            self.list_panel.Children.Add(box)
        if not lines:
            self.list_panel.Children.Add(ui.text_block(u"Nothing left to assign.", 11, "MutedBrush"))

    def on_search(self, sender, args):
        try:
            self.fill_list(sender.Text)
        except Exception as err:
            self.owner.status(u"Search failed: {0}".format(err))

    def on_tick(self, sender, args):
        if self.suspend:
            return
        self.suspend = True
        try:
            updated = core.toggle(self.selected(), sender.Tag, bool(sender.IsChecked),
                                  self.owner.scan)
            self.owner.selections[self.name] = updated
            self.owner.rebuild_claims()
            for key, box in self.boxes.items():
                want = key in updated
                if bool(box.IsChecked) != want:
                    box.IsChecked = want
            self.refresh_label()
            self.owner.update_assign_status()
        except Exception as err:
            self.owner.status(u"Selection failed: {0}".format(err))
        finally:
            self.suspend = False


# ================================================================ main window

class MainWindow(object):

    def __init__(self, uiapp, document, direct=False):
        self.uiapp = uiapp
        self.doc = document
        self.title = core.to_text(document.Title)
        self.direct = bool(direct)
        self.settings = core.load_settings()
        self.theme_setting = core.normalise_theme(self.settings.get("theme"))
        self.rows = []
        self.by_key = {}
        self.drows = {}
        self.records = []
        self.scan = core.ModelScan()
        self.filters = {}
        self.ticks = {}
        self.sort_stack = [("name", False)]
        self.headers = {}
        self.case_mode = "keep"
        self.expanded = set()
        self.name_column = None
        self.exp_column = None
        self.exp_header = None
        self.new_counter = 0
        self.guard = 0
        self.closing_ok = False
        self.tab = "manage"
        self.assign_rows = []
        self.selections = {}
        self.claims = {}
        self.canvas = None
        self.colours = {}
        self.isolated = []
        self.view_name = u""
        self.armed = False
        self.closed = False
        self.scope = None

        self.window = ui.load_window(LAYOUT_PATH)
        self.w = self.window.FindName
        self.grid = self.w("WsGrid")
        self.table = DataTable("worksets")
        for name in TABLE_COLUMNS:
            self.table.Columns.Add(name)

        self.filter_timer = ui.debounce(220, self.refresh_view)
        self.preview_timer = ui.debounce(120, self.update_preview)
        self.runner = runner_module.Runner()
        self.runner.setup(uiapp, self.window.Dispatcher, self.direct)
        self.watchdog = ui.repeat(2000, self.on_watchdog)

        self.size_window()
        self.chrome = ui.Chrome(self.window, self.w("HeaderBar"), self.w("GripLayer"),
                                self.w("FullScreenButton"),
                                [self.w("ThemeButton"), self.w("CloseButton"),
                                 self.w("LogoBlock")])
        icon = ui.load_icon()
        if icon is not None:
            self.w("HeaderIcon").Source = icon
        self.w("VersionText").Text = u"v" + core.VERSION
        self.w("AutoEditableCheck").IsChecked = core.as_bool(
            self.settings.get("auto_editable"), True)
        self.apply_theme()
        ui.attach_egg(self.window, self.w("LogoBlock"), self.theme_name)

        self.build_grid()
        self.wire()
        self.scope = wsm_scope.ScopeTab(self)
        # the command is still running here, so the first read is direct
        records, scan = revit.read_model(self.doc, self.settings)
        self.apply_read(records, scan, keep=False)
        self.show_tab(self.settings.get("tab", "manage"))
        self.update_preview()
        self.update_3d_buttons()

    # ---------------------------------------------------------- set up

    def size_window(self):
        width = core.as_int(self.settings.get("width"), 1260)
        height = core.as_int(self.settings.get("height"), 820)
        self.window.Width = max(self.window.MinWidth, min(width, 2600))
        self.window.Height = max(self.window.MinHeight, min(height, 1600))

    def wire(self):
        w = self.w
        w("CloseButton").Click += self.on_close_click
        w("ThemeButton").Click += self.on_theme
        w("TabManage").Click += lambda s, a: self.show_tab("manage")
        w("TabAssign").Click += lambda s, a: self.show_tab("assign")
        w("TabScope").Click += lambda s, a: self.show_tab("scope")
        w("ExportButton").Click += self.on_export
        w("ImportButton").Click += self.on_import
        w("NewButton").Click += self.on_new
        w("EditableButton").Click += self.on_make_editable
        w("DeleteButton").Click += self.on_delete
        w("RevertButton").Click += self.on_revert_selected
        w("RevertAllButton").Click += self.on_revert_all
        w("ClearFiltersButton").Click += self.on_clear_filters
        w("RefreshButton").Click += self.on_refresh
        w("RefreshAssignButton").Click += self.on_refresh
        w("ApplyWorksetsButton").Click += self.on_apply_worksets
        w("RenameStageButton").Click += self.on_stage_rename
        w("RenameResetButton").Click += self.on_reset_rename
        for name in ("FindBox", "ReplaceBox", "PrefixBox", "SuffixBox",
                     "RemoveFirstBox", "RemoveLastBox"):
            w(name).TextChanged += self.on_rename_input
        w("MatchCaseCheck").Click += self.on_rename_input
        w("TidyCheck").Click += self.on_rename_input
        w("CaseKeep").Click += lambda s, a: self.set_case("keep")
        w("CaseUpper").Click += lambda s, a: self.set_case("upper")
        w("CaseLower").Click += lambda s, a: self.set_case("lower")
        w("CaseTitle").Click += lambda s, a: self.set_case("title")
        w("AssignSearch").TextChanged += self.on_assign_search
        w("SaveRoutineButton").Click += self.on_save_routine
        w("LoadRoutineButton").Click += self.on_load_routine
        w("ClearAssignButton").Click += self.on_clear_assign
        w("ApplyAssignButton").Click += self.on_apply_assign
        w("MergeButton").Click += self.on_merge
        w("Show3DButton").Click += self.on_show_3d
        w("IsolateButton").Click += self.on_isolate
        w("UnisolateButton").Click += self.on_unisolate
        w("AutoEditableCheck").Click += self.on_auto_editable
        self.grid.BeginningEdit += self.on_beginning_edit
        self.grid.LoadingRow += self.on_loading_row
        self.grid.RowDetailsVisibilityChanged += self.on_details_changed
        self.grid.LoadingRowDetails += self.on_details_changed
        self.grid.PreviewMouseLeftButtonDown += self.on_grid_mouse_down
        self.grid.SelectionChanged += self.on_selection_changed
        self.table.RowChanged += self.on_row_changed
        self.window.PreviewKeyDown += self.on_key
        self.window.Activated += self.on_activated
        self.window.Closing += self.on_closing
        self.window.Closed += self.on_closed
        self.window.ContentRendered += self.on_rendered

    def build_grid(self):
        self.grid.ItemsSource = self.table.DefaultView
        self.table.DefaultView.RowFilter = "vis = '1'"
        self.table.DefaultView.Sort = "gkey ASC"

        expander = DataGridTextColumn()
        expander.Binding = Binding("exp")
        expander.Width = DataGridLength(30)
        expander.MinWidth = 30
        expander.CanUserResize = False
        expander.IsReadOnly = True
        expander.CanUserSort = False
        expander.ElementStyle = self.window.FindResource("WsExpText")
        head = Border()
        head.Background = ui.brush(CLEAR)
        head.Cursor = Cursors.Hand
        head.ToolTip = u"Expand or collapse the categories on every workset"
        glyph = ui.text_block(EXPAND_GLYPH, 13, "BlueBrush", True)
        glyph.HorizontalAlignment = HorizontalAlignment.Center
        glyph.VerticalAlignment = VerticalAlignment.Top
        glyph.Margin = Thickness(0, 2, 0, 0)
        head.Child = glyph
        head.MouseLeftButtonUp += self.on_expand_all
        expander.Header = head
        self.exp_header = glyph
        self.exp_column = expander
        self.grid.Columns.Add(expander)

        swatch = DataGridTemplateColumn()
        swatch.CellTemplate = self.window.FindResource("WsSwatchTemplate")
        swatch.Width = DataGridLength(24)
        swatch.MinWidth = 24
        swatch.CanUserResize = False
        swatch.IsReadOnly = True
        swatch.CanUserSort = False
        self.grid.Columns.Add(swatch)

        for column, stars, minimum, cell_style, placeholder in GRID_COLUMNS:
            made = DataGridTextColumn()
            made.Binding = Binding(column)
            made.Width = DataGridLength(stars, DataGridLengthUnitType.Star)
            made.MinWidth = minimum
            made.IsReadOnly = column != "name"
            made.CanUserSort = False
            made.ElementStyle = self.window.FindResource(cell_style)
            if column == "name":
                made.EditingElementStyle = self.window.FindResource("WsNameEdit")
            made.Header = self.make_header(column, placeholder)
            self.grid.Columns.Add(made)
            if column == "name":
                self.name_column = made

    def make_header(self, column, placeholder):
        outer = Border()
        outer.BorderThickness = Thickness(0, 0, 0, 2)
        outer.BorderBrush = ui.brush(CLEAR)
        outer.Padding = Thickness(2, 0, 2, 3)
        layout = Grid()
        for height in (GridLength(1, GridUnitType.Auto), GridLength(1, GridUnitType.Auto)):
            row = RowDefinition()
            row.Height = height
            layout.RowDefinitions.Add(row)
        outer.Child = layout

        top = Grid()
        for spec in (GridLength(1, GridUnitType.Star), GridLength(1, GridUnitType.Auto),
                     GridLength(1, GridUnitType.Auto)):
            definition = ColumnDefinition()
            definition.Width = spec
            top.ColumnDefinitions.Add(definition)
        layout.Children.Add(top)

        hit = Border()
        hit.Background = ui.brush(CLEAR)
        hit.Cursor = Cursors.Hand
        hit.ToolTip = u"Click to sort. Shift+click adds a second sort level."
        title = ui.text_block(core.COLUMN_TITLES[column], 12, "TextBrush", True)
        if column == "count":
            ui.res(title, TextBlock.ForegroundProperty, "OrangeBrush")
        hit.Child = title
        hit.MouseLeftButtonUp += self.make_sort_handler(column)
        top.Children.Add(hit)

        badge = ui.text_block(u"", 10, "OrangeBrush", True)
        badge.Margin = Thickness(4, 0, 2, 0)
        Grid.SetColumn(badge, 1)
        top.Children.Add(badge)

        caret = None
        popup = None
        if column in core.TICK_COLUMNS:
            caret = ToggleButton()
            ui.style(caret, "WsCaret")
            caret.ToolTip = u"Pick values to show"
            caret.Margin = Thickness(2, 0, 0, 0)
            Grid.SetColumn(caret, 2)
            top.Children.Add(caret)
            popup = Popup()
            popup.PlacementTarget = caret
            popup.Placement = PlacementMode.Bottom
            popup.StaysOpen = False
            popup.AllowsTransparency = True
            layout.Children.Add(popup)
            caret.Checked += self.make_tick_opener(column)
            popup.Closed += self.make_tick_closer(column)

        box = TextBox()
        ui.style(box, "WsTextBox")
        box.Tag = placeholder
        box.Height = 24
        box.FontSize = 11
        box.Margin = Thickness(0, 4, 0, 0)
        box.TextChanged += self.make_filter_handler(column)
        Grid.SetRow(box, 1)
        layout.Children.Add(box)

        self.headers[column] = {"outer": outer, "badge": badge, "caret": caret,
                                "popup": popup, "box": box}
        return outer

    # ---------------------------------------------------------- theme and tabs

    def theme_name(self):
        return ui.CURRENT.get("name", "dark")

    def apply_theme(self):
        if self.theme_setting == "follow":
            self.canvas = revit.canvas_theme(self.doc)
        name = core.resolve_theme(self.theme_setting, self.canvas)
        if name != ui.CURRENT.get("name") or not self.window.Resources.Contains("WindowBrush"):
            ui.apply_palette(self.window, name)
        self.w("ThemeLabel").Text = core.THEME_LABELS[self.theme_setting]
        if self.theme_setting == "follow":
            tip = u"Auto: following Revit's canvas ({0}). Click for Dark.".format(name)
        elif self.theme_setting == "dark":
            tip = u"Dark. Click for Light."
        else:
            tip = u"Light. Click for Auto (follow Revit's canvas)."
        self.w("ThemeButton").ToolTip = tip

    def on_theme(self, sender, args):
        self.theme_setting = core.next_theme(self.theme_setting)
        self.apply_theme()
        self.save_settings()

    def on_activated(self, sender, args):
        if self.theme_setting == "follow":
            try:
                self.apply_theme()
            except Exception:
                pass

    TABS = (("manage", "TabManage", "ManagePanel", "ManageFooter"),
            ("scope", "TabScope", "ScopePanel", "ScopeFooter"),
            ("assign", "TabAssign", "AssignPanel", "AssignFooter"))

    def show_tab(self, name):
        self.commit_edits()
        if self.scope is not None:
            self.scope.table.commit_edits()
        self.tab = name if name in ("manage", "scope", "assign") else "manage"
        for tab, button, panel, footer in self.TABS:
            on = tab == self.tab
            self.w(panel).Visibility = Visibility.Visible if on else Visibility.Collapsed
            self.w(footer).Visibility = Visibility.Visible if on else Visibility.Collapsed
            ui.style(self.w(button), "WsTabActive" if on else "WsTab")
        if self.tab == "manage":
            self.update_manage_status()
        elif self.tab == "assign":
            self.update_assign_status()
        elif self.scope is not None:
            self.scope.update_status()
            self.scope.ensure_loaded()

    def status(self, text):
        self.w("StatusText").Text = core.to_text(text)

    # ---------------------------------------------------------- reading

    def request_read(self, keep=True, then=None):
        """Read the model again, through Revit."""
        def work(uiapp):
            return revit.read_model(self.doc, self.settings)

        def done(result):
            self.apply_read(result[0], result[1], keep)
            if then is not None:
                then()
        self.run_job(u"read", work, done, u"Reading the model...")

    def apply_read(self, records, scan, keep=True):
        """Take a read into the window.  With keep, staged changes and assigner
        ticks survive: renames and deletes by workset id, new worksets unless
        one of that name now exists."""
        self.commit_edits()
        old_rows = list(self.rows) if keep else []
        self.records, self.scan = records, scan
        self.colours = core.workset_colours([record.iid for record in records])
        fresh = []
        for record in self.records:
            made = core.WsRow(u"ws:{0}".format(record.iid), record.name, record.count,
                              record.editable, record.owner, iid=record.iid,
                              active=record.active)
            made.categories = list(record.categories)
            made.visible = record.visible
            made.colour = self.colours.get(record.iid, core.NO_COLOUR)
            fresh.append(made)
        if old_rows:
            by_iid = dict((row.iid, row) for row in fresh)
            names = set(row.orig.strip().lower() for row in fresh)
            for old in old_rows:
                if old.is_new:
                    if old.name.strip().lower() not in names:
                        fresh.append(old)
                    continue
                row = by_iid.get(old.iid)
                if row is None:
                    continue
                if old.renamed() and old.name != row.orig:
                    row.name = old.name
                if old.delete_to is not None:
                    row.delete_to = old.delete_to
                    row.merge = old.merge
            keys = set(row.key for row in fresh)
            for row in fresh:
                if row.delete_to is not None and row.delete_to not in keys:
                    row.delete_to = None
                    row.merge = False
        self.rows = fresh
        self.populate_table()

        names = set(record.name for record in self.records)
        kept = {}
        for name, keys in self.selections.items():
            if name in names:
                live = set(k for k in keys if k in self.scan.by_key)
                if live:
                    kept[name] = live
        self.selections = kept if keep else {}
        self.rebuild_claims()
        self.build_assign_rows()
        if self.scan.error:
            self.status(self.scan.error)

    def populate_table(self):
        self.guard += 1
        try:
            self.table.Rows.Clear()
            self.drows = {}
            for row in self.rows:
                record = self.table.NewRow()
                record["key"] = row.key
                record["vis"] = "1"
                record["gkey"] = "0"
                self.table.Rows.Add(record)
                self.drows[row.key] = record
        finally:
            self.guard -= 1
        self.by_key = dict((row.key, row) for row in self.rows)
        self.refresh_states()
        self.refresh_view()

    # ---------------------------------------------------------- the table

    def refresh_states(self):
        """Validate, then write every row's text and state into the table."""
        problems = core.validate(self.rows)
        self.by_key = dict((row.key, row) for row in self.rows)
        self.guard += 1
        try:
            for row in self.rows:
                record = self.drows.get(row.key)
                if record is None:
                    continue
                values = {
                    "name": row.name,
                    "count": u"" if row.is_new else u"{0}".format(row.count),
                    "cats": core.category_summary(row.categories),
                    "exp": self.expander_glyph(row),
                    "colour": row.colour or core.NO_COLOUR,
                    "editable": u"" if row.is_new else (u"Yes" if row.editable else u"No"),
                    "visible": core.to_text(core.row_value(row, "visible")),
                    "owner": u"" if row.is_new else (row.owner or u""),
                    "change": core.change_text(row, self.by_key),
                    "state": row.state(),
                }
                for column, value in values.items():
                    if core.to_text(record[column]) != value:
                        record[column] = value
        finally:
            self.guard -= 1
        plan = core.build_plan(self.rows)
        count = core.plan_count(plan)
        label = u"Apply workset changes"
        if count:
            label = u"Apply workset changes ({0})".format(count)
        self.w("ApplyWorksetsLabel").Text = label
        self.w("ApplyWorksetsButton").IsEnabled = bool(count or problems)
        self.w("RevertAllButton").IsEnabled = any(row.staged() for row in self.rows)
        self.update_manage_status(problems)

    def refresh_view(self):
        """Take the sort and the filters again.  Only ever on a sort click, a
        filter change or F5 - never mid-edit."""
        self.commit_edits()
        ordered = core.sort_rows(self.rows, self.sort_stack)
        self.guard += 1
        try:
            for place, row in enumerate(ordered):
                record = self.drows.get(row.key)
                if record is None:
                    continue
                vis = "1" if core.row_passes(row, self.filters, self.ticks, self.by_key) else "0"
                gkey = "{0:06d}".format(place)
                if core.to_text(record["vis"]) != vis:
                    record["vis"] = vis
                if core.to_text(record["gkey"]) != gkey:
                    record["gkey"] = gkey
        finally:
            self.guard -= 1
        self.update_header_marks()
        self.update_manage_status()
        self.update_preview()

    def update_header_marks(self):
        levels = dict((column, index) for index, (column, _) in enumerate(self.sort_stack))
        for column, parts in self.headers.items():
            if column in levels:
                index = levels[column]
                descending = self.sort_stack[index][1]
                ui.res(parts["outer"], Border.BorderBrushProperty, SORT_KEYS[index % 3])
                ui.res(parts["badge"], TextBlock.ForegroundProperty, SORT_KEYS[index % 3])
                arrow = u"\u25BC" if descending else u"\u25B2"
                parts["badge"].Text = (u"{0}{1}".format(index + 1, arrow)
                                       if len(self.sort_stack) > 1 else arrow)
            else:
                parts["outer"].BorderBrush = ui.brush(CLEAR)
                parts["badge"].Text = u""
            caret = parts["caret"]
            if caret is not None:
                caret.Tag = "on" if self.ticks.get(column) is not None else "off"

    def shown_keys(self):
        return [row.key for row in self.rows
                if core.to_text(self.drows[row.key]["vis"]) == "1"]

    def selected_keys(self):
        keys = []
        for item in self.grid.SelectedItems:
            try:
                keys.append(core.to_text(item["key"]))
            except Exception:
                continue
        return [key for key in keys if key in self.by_key]

    def update_manage_status(self, problems=None):
        if self.tab != "manage":
            return
        if problems is None:
            problems = len([row for row in self.rows if row.problem])
        shown = len(self.shown_keys())
        staged = len([row for row in self.rows if row.staged()])
        parts = [u"{0} worksets".format(len([r for r in self.rows if not r.is_new]))]
        if shown != len(self.rows):
            parts.append(u"{0} shown".format(shown))
        if staged:
            parts.append(u"{0} change{1} staged in red - nothing is written until Apply".format(
                staged, u"" if staged == 1 else u"s"))
        if problems:
            parts.append(u"{0} need a look".format(problems))
        self.status(u"   \u00B7   ".join(parts))

    def commit_edits(self):
        try:
            self.grid.CommitEdit(DataGridEditingUnit.Row, True)
        except Exception:
            pass

    def make_sort_handler(self, column):
        def handler(sender, args):
            try:
                self.commit_edits()
                shift = (Keyboard.Modifiers & ModifierKeys.Shift) == ModifierKeys.Shift
                self.sort_stack = core.push_sort(self.sort_stack, column, shift)
                self.refresh_view()
                args.Handled = True
            except Exception as err:
                self.status(u"Sort failed: {0}".format(err))
        return handler

    def make_filter_handler(self, column):
        def handler(sender, args):
            self.filters[column] = core.to_text(sender.Text)
            ui.kick(self.filter_timer)
        return handler

    def make_tick_opener(self, column):
        def handler(sender, args):
            try:
                self.open_ticks(column)
            except Exception as err:
                self.status(u"Could not open the list: {0}".format(err))
        return handler

    def make_tick_closer(self, column):
        def handler(sender, args):
            caret = self.headers[column]["caret"]
            if caret is not None:
                caret.IsChecked = False
        return handler

    def open_ticks(self, column):
        parts = self.headers[column]
        choices = core.tick_choices(self.rows, column, self.filters, self.ticks, self.by_key)
        allowed = self.ticks.get(column)
        shell = Border()
        ui.res(shell, Border.BackgroundProperty, "FieldBrush")
        ui.res(shell, Border.BorderBrushProperty, "ChromeBrush")
        shell.BorderThickness = Thickness(1)
        shell.Padding = Thickness(8)
        shell.MinWidth = 200
        stack = StackPanel()
        viewer = ScrollViewer()
        viewer.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
        viewer.MaxHeight = 320
        viewer.Content = stack
        shell.Child = viewer
        boxes = []
        state = {"busy": False}

        everything = CheckBox()
        ui.style(everything, "WsCheck")
        everything.Content = ui.text_block(u"(Select all)", 12, "MutedBrush")
        everything.IsChecked = allowed is None
        stack.Children.Add(everything)

        def changed(sender, args):
            if state["busy"]:
                return
            state["busy"] = True
            try:
                if sender is everything:
                    for box in boxes:
                        box.IsChecked = bool(everything.IsChecked)
                ticked = set(core.to_text(box.Tag) for box in boxes if box.IsChecked)
                everything.IsChecked = len(ticked) == len(boxes)
                if len(ticked) == len(boxes):
                    self.ticks[column] = None
                else:
                    self.ticks[column] = ticked
                self.refresh_view()
            finally:
                state["busy"] = False

        everything.Click += changed
        for value in choices:
            box = CheckBox()
            ui.style(box, "WsCheck")
            box.Content = ui.text_block(value, 12, "TextBrush")
            box.Tag = value
            box.IsChecked = allowed is None or value in allowed
            box.Click += changed
            boxes.append(box)
            stack.Children.Add(box)
        parts["popup"].Child = shell
        parts["popup"].IsOpen = True

    def on_clear_filters(self, sender, args):
        self.filters = {}
        self.ticks = {}
        for parts in self.headers.values():
            parts["box"].Text = u""
        self.refresh_view()

    def on_beginning_edit(self, sender, args):
        try:
            key = core.to_text(args.Row.Item["key"])
            row = self.by_key.get(key)
            if row is None or args.Column is not self.name_column or \
                    row.delete_to is not None:
                args.Cancel = True
        except Exception:
            args.Cancel = True

    def on_row_changed(self, sender, args):
        if self.guard:
            return
        ui.later(self.window, self.after_edit)

    def after_edit(self):
        """A name typed into the table: stage it on the row."""
        try:
            changed = False
            for row in self.rows:
                record = self.drows.get(row.key)
                if record is None:
                    continue
                typed = core.to_text(record["name"]).strip()
                if not typed and not row.is_new:
                    typed = row.orig
                if typed != row.name:
                    row.name = typed
                    changed = True
            self.refresh_states()
            if changed:
                self.update_preview()
        except Exception as err:
            self.status(u"Edit failed: {0}".format(err))

    def on_selection_changed(self, sender, args):
        ui.kick(self.preview_timer)
        self.update_3d_buttons()

    # ---------------------------------------------------------- category breakdown

    def expander_glyph(self, row):
        if not row.categories:
            return u""
        return COLLAPSE_GLYPH if row.key in self.expanded else EXPAND_GLYPH

    def row_container(self, key):
        for item in self.grid.Items:
            try:
                if core.to_text(item["key"]) == key:
                    return self.grid.ItemContainerGenerator.ContainerFromItem(item)
            except Exception:
                continue
        return None

    def set_expanded(self, keys, open_them):
        """Open or close the breakdown under the rows named."""
        self.guard += 1
        try:
            for key in keys:
                row = self.by_key.get(key)
                if row is None or not row.categories:
                    continue
                if open_them:
                    self.expanded.add(key)
                else:
                    self.expanded.discard(key)
                record = self.drows.get(key)
                if record is not None:
                    record["exp"] = self.expander_glyph(row)
        finally:
            self.guard -= 1
        for key in keys:
            container = self.row_container(key)
            if container is not None:
                container.DetailsVisibility = (Visibility.Visible if key in self.expanded
                                               else Visibility.Collapsed)
        self.exp_header.Text = COLLAPSE_GLYPH if self.expanded else EXPAND_GLYPH

    def on_grid_mouse_down(self, sender, args):
        """A click on the expander cell opens or closes that row's breakdown."""
        try:
            cell = ui.ancestor(args.OriginalSource, DataGridCell, self.grid)
            if cell is None or cell.Column is not self.exp_column:
                return
            key = core.to_text(cell.DataContext["key"])
            self.set_expanded([key], key not in self.expanded)
            args.Handled = True
        except Exception as err:
            self.status(u"Could not open the categories: {0}".format(err))

    def on_expand_all(self, sender, args):
        try:
            self.commit_edits()
            keys = self.shown_keys()
            open_them = not any(key in self.expanded for key in keys)
            self.set_expanded(keys, open_them)
            args.Handled = True
        except Exception as err:
            self.status(u"Could not expand: {0}".format(err))

    def on_loading_row(self, sender, args):
        """Rows are made and dropped as the table scrolls; each new one takes
        its open or closed state from the set, never from the last row."""
        try:
            key = core.to_text(args.Row.Item["key"])
            args.Row.DetailsVisibility = (Visibility.Visible if key in self.expanded
                                          else Visibility.Collapsed)
        except Exception:
            pass

    def on_details_changed(self, sender, args):
        try:
            if args.Row.DetailsVisibility != Visibility.Visible or args.DetailsElement is None:
                return
            key = core.to_text(args.Row.Item["key"])
            self.fill_details(args.DetailsElement, self.by_key.get(key))
        except Exception as err:
            self.status(u"Could not show the categories: {0}".format(err))

    def fill_details(self, host, row):
        """Every category on the workset with its count and a bar against the
        biggest, laid out in as many columns as the width allows."""
        outer = StackPanel()
        if row is None or not row.categories:
            outer.Children.Add(ui.text_block(u"No elements on this workset.", 11, "MutedBrush"))
            host.Child = outer
            return
        total = sum([count for _, count in row.categories])
        heading = ui.text_block(u"{0} categor{1}  \u00B7  {2} elements".format(
            len(row.categories), u"y" if len(row.categories) == 1 else u"ies", total),
            11, "MutedBrush", True)
        heading.Margin = Thickness(0, 0, 0, 6)
        outer.Children.Add(heading)
        biggest = float(row.categories[0][1]) or 1.0
        wrap = WrapPanel()
        wrap.Orientation = Orientation.Horizontal
        for name, count in row.categories:
            item = Grid()
            item.Width = DETAIL_ITEM_WIDTH
            item.Margin = Thickness(0, 0, 18, 6)
            for spec in (GridLength(1, GridUnitType.Star), GridLength(1, GridUnitType.Auto)):
                definition = ColumnDefinition()
                definition.Width = spec
                item.ColumnDefinitions.Add(definition)
            for spec in (GridLength(1, GridUnitType.Auto), GridLength(1, GridUnitType.Auto)):
                definition = RowDefinition()
                definition.Height = spec
                item.RowDefinitions.Add(definition)
            label = ui.text_block(name, 12, "TextBrush")
            label.ToolTip = name
            item.Children.Add(label)
            number = ui.text_block(u"{0}".format(count), 12, "OrangeBrush", True)
            number.Margin = Thickness(8, 0, 0, 0)
            Grid.SetColumn(number, 1)
            item.Children.Add(number)
            track = Border()
            ui.res(track, Border.BackgroundProperty, "EdgeBrush")
            track.Height = 3
            track.CornerRadius = CornerRadius(1.5)
            track.Margin = Thickness(0, 3, 0, 0)
            Grid.SetRow(track, 1)
            Grid.SetColumnSpan(track, 2)
            item.Children.Add(track)
            fill = Border()
            ui.res(fill, Border.BackgroundProperty, "OrangeBrush")
            fill.Height = 3
            fill.CornerRadius = CornerRadius(1.5)
            fill.HorizontalAlignment = HorizontalAlignment.Left
            fill.Width = max(2.0, DETAIL_ITEM_WIDTH * count / biggest)
            fill.Margin = Thickness(0, 3, 0, 0)
            Grid.SetRow(fill, 1)
            Grid.SetColumnSpan(fill, 2)
            item.Children.Add(fill)
            wrap.Children.Add(item)
        outer.Children.Add(wrap)
        host.Child = outer

    # ---------------------------------------------------------- bulk rename

    def read_ops(self):
        w = self.w
        return {
            "find": core.to_text(w("FindBox").Text),
            "replace": core.to_text(w("ReplaceBox").Text),
            "match_case": bool(w("MatchCaseCheck").IsChecked),
            "prefix": core.to_text(w("PrefixBox").Text),
            "suffix": core.to_text(w("SuffixBox").Text),
            "remove_first": core.as_int(w("RemoveFirstBox").Text, 0),
            "remove_last": core.as_int(w("RemoveLastBox").Text, 0),
            "case": self.case_mode,
            "tidy": bool(w("TidyCheck").IsChecked),
        }

    def rename_scope(self):
        selected = self.selected_keys()
        if selected:
            return selected, u"Applies to the {0} selected workset{1}.".format(
                len(selected), u"" if len(selected) == 1 else u"s")
        shown = self.shown_keys()
        return shown, (u"Nothing selected - applies to all {0} worksets shown. "
                       u"Select rows to narrow it.".format(len(shown)))

    def update_preview(self):
        try:
            keys, scope = self.rename_scope()
            self.w("RenameScopeText").Text = scope
            ops = self.read_ops()
            host = self.w("RenamePreviewHost")
            host.Children.Clear()
            plan = [] if core.ops_empty(ops) else core.bulk_rename_plan(self.rows, keys, ops)
            if core.ops_empty(ops):
                host.Children.Add(ui.text_block(u"Type above - the new names appear here.",
                                                11, "MutedBrush", wrap=True))
            elif not plan:
                host.Children.Add(ui.text_block(u"No names change.", 11, "MutedBrush"))
            for key, old, new in plan[:12]:
                line = StackPanel()
                line.Margin = Thickness(0, 1, 0, 1)
                line.Children.Add(ui.text_block(old, 11, "MutedBrush"))
                line.Children.Add(ui.text_block(u"\u2192 " + new, 12, "RedBrush", True))
                host.Children.Add(line)
            if len(plan) > 12:
                host.Children.Add(ui.text_block(u"... and {0} more".format(len(plan) - 12),
                                                11, "MutedBrush"))
            self.w("RenameStageLabel").Text = (u"Stage rename ({0})".format(len(plan))
                                               if plan else u"Stage rename")
            self.w("RenameStageButton").IsEnabled = bool(plan)
        except Exception as err:
            self.status(u"Preview failed: {0}".format(err))

    def on_rename_input(self, sender, args):
        ui.kick(self.preview_timer)

    def set_case(self, mode):
        self.case_mode = mode
        for name, value in (("CaseKeep", "keep"), ("CaseUpper", "upper"),
                            ("CaseLower", "lower"), ("CaseTitle", "title")):
            ui.style(self.w(name), "WsSegmentOn" if value == mode else "WsSegment")
        self.update_preview()

    def on_reset_rename(self, sender, args):
        for name in ("FindBox", "ReplaceBox", "PrefixBox", "SuffixBox",
                     "RemoveFirstBox", "RemoveLastBox"):
            self.w(name).Text = u""
        self.w("MatchCaseCheck").IsChecked = False
        self.w("TidyCheck").IsChecked = False
        self.set_case("keep")

    def on_stage_rename(self, sender, args):
        self.commit_edits()
        keys, scope = self.rename_scope()
        plan = core.bulk_rename_plan(self.rows, keys, self.read_ops())
        if not plan:
            return
        for key, old, new in plan:
            self.by_key[key].name = new
        self.refresh_states()
        self.on_reset_rename(None, None)
        self.status(u"{0} rename{1} staged in red - press Apply workset changes to write "
                    u"them.".format(len(plan), u"" if len(plan) == 1 else u"s"))

    # ---------------------------------------------------------- new, delete, revert

    def on_new(self, sender, args):
        self.commit_edits()
        names = set(row.effective_name().strip().lower() for row in self.rows)
        number = 1
        while u"new workset {0}".format(number) in names:
            number += 1
        self.new_counter += 1
        row = core.WsRow(u"new:{0}".format(self.new_counter),
                         u"New Workset {0}".format(number), is_new=True)
        self.rows.append(row)
        self.populate_table()
        ui.later(self.window, lambda: self.edit_row(row.key))

    def edit_row(self, key):
        for item in self.grid.Items:
            try:
                if core.to_text(item["key"]) != key:
                    continue
            except Exception:
                continue
            self.grid.SelectedItem = item
            self.grid.ScrollIntoView(item)
            self.grid.CurrentCell = DataGridCellInfo(item, self.name_column)
            self.grid.Focus()
            self.grid.BeginEdit()
            return

    def on_delete(self, sender, args):
        self.commit_edits()
        keys = self.selected_keys()
        if not keys:
            self.status(u"Select the worksets to delete first - Ctrl or Shift click for several.")
            return
        deleting = [self.by_key[key] for key in keys]
        existing = [row for row in deleting if not row.is_new]
        if not existing:
            self.rows = [row for row in self.rows if row.key not in keys]
            self.populate_table()
            self.status(u"Removed {0} new workset(s) that had not been applied.".format(len(keys)))
            return
        targets = core.delete_targets(self.rows, keys)
        if not targets:
            ui.message(self.window, u"Delete worksets",
                       [u"At least one workset has to stay, and it has to be one that is "
                        u"not being deleted - its elements need somewhere to go."], 520, 260)
            return
        target = ui.delete_dialog(self.window, existing, targets)
        if not target:
            return
        self.rows, problem = core.stage_deletes(self.rows, keys, target)
        if problem:
            self.status(problem)
            return
        self.populate_table()
        self.status(u"{0} workset(s) staged for deletion in red - their elements go to {1} "
                    u"when you press Apply.".format(len(existing),
                                                    self.by_key[target].effective_name()))

    def on_revert_selected(self, sender, args):
        self.commit_edits()
        keys = self.selected_keys()
        if not keys:
            self.status(u"Select the rows to revert - or use Revert all.")
            return
        self.rows = core.revert(self.rows, set(keys))
        self.populate_table()

    def on_revert_all(self, sender, args):
        self.commit_edits()
        self.rows = core.revert(self.rows)
        self.populate_table()
        self.status(u"Every staged change reverted.")

    # ---------------------------------------------------------- make editable

    def auto_editable(self):
        return bool(self.w("AutoEditableCheck").IsChecked)

    def on_auto_editable(self, sender, args):
        self.save_settings()

    def on_make_editable(self, sender, args):
        self.commit_edits()
        keys = self.selected_keys()
        rows = [self.by_key[key] for key in keys if not self.by_key[key].is_new]
        if not rows:
            self.status(u"Select the worksets to make editable.")
            return
        iids = [row.iid for row in rows]

        def work(uiapp):
            log = self.new_log()
            made, refused = revit.make_editable(self.doc, iids, log)
            log.write(header=u"Make editable")
            return made, refused, revit.read_model(self.doc, self.settings)

        def done(payload):
            made, refused, read = payload
            self.apply_read(read[0], read[1], keep=True)
            if refused:
                ui.message(self.window, u"Make editable",
                           [u"Not made editable:"] +
                           [u"   {0}  -  {1}".format(name, reason) for name, reason in refused],
                           560, 340)
            self.status(u"{0} workset(s) checked out to you.".format(len(made)))
        self.run_job(u"make editable", work, done, u"Checking worksets out...")

    # ---------------------------------------------------------- excel

    def on_export(self, sender, args):
        self.commit_edits()
        try:
            from Microsoft.Win32 import SaveFileDialog
            dialog = SaveFileDialog()
            dialog.Title = u"Save the workset spreadsheet"
            dialog.Filter = u"Excel workbook (*.xlsx)|*.xlsx"
            dialog.DefaultExt = u".xlsx"
            dialog.FileName = u"{0} - Worksets.xlsx".format(core.project_key(self.title))
            folder = core.to_text(self.settings.get("last_export_dir"))
            if folder and os.path.isdir(folder):
                dialog.InitialDirectory = folder
            if not dialog.ShowDialog(self.window):
                return
            path = core.to_text(dialog.FileName)
            sheet = xlsx.workset_sheet_rows(self.rows, core.as_int(self.settings.get("new_rows"), 10))
            ok, problem = xlsx.write_workbook(path, sheet, xlsx.WIDTHS, 1)
            if not ok:
                self.status(u"Could not write the spreadsheet: " + problem)
                return
            self.settings["last_export_dir"] = os.path.dirname(path)
            self.save_settings()
            try:
                Process.Start(u"explorer.exe", u'/select,"{0}"'.format(path))
            except Exception:
                pass
            self.status(u"Written to {0} - rename in the orange cells, add in the green ones, "
                        u"then Import Excel.".format(path))
        except Exception as err:
            self.status(u"Export failed: {0}".format(err))

    def on_import(self, sender, args):
        self.commit_edits()
        try:
            from Microsoft.Win32 import OpenFileDialog
            dialog = OpenFileDialog()
            dialog.Title = u"Open the edited workset spreadsheet"
            dialog.Filter = u"Excel workbook (*.xlsx)|*.xlsx"
            folder = core.to_text(self.settings.get("last_export_dir"))
            if folder and os.path.isdir(folder):
                dialog.InitialDirectory = folder
            if not dialog.ShowDialog(self.window):
                return
            sheet, problem = xlsx.read_sheet(dialog.FileName)
            if problem:
                self.status(problem)
                return
            renames, creates, skipped = core.import_changes(xlsx.sheet_triples(sheet), self.rows)
            for key, name in renames.items():
                row = self.by_key.get(key)
                if row is not None and row.delete_to is None:
                    row.name = name
            for name in creates:
                self.new_counter += 1
                self.rows.append(core.WsRow(u"new:{0}".format(self.new_counter), name,
                                            is_new=True))
            self.populate_table()
            if skipped:
                ui.message(self.window, u"Import Excel",
                           [u"Left alone:"] +
                           [u"   {0}  -  {1}".format(name, reason) for name, reason in skipped])
            self.status(u"Imported {0} rename(s) and {1} new workset(s) - staged in red; press "
                        u"Apply workset changes to write them.".format(len(renames), len(creates)))
        except Exception as err:
            self.status(u"Import failed: {0}".format(err))

    # ---------------------------------------------------------- apply

    def on_apply_worksets(self, sender, args):
        self.commit_edits()
        problems = core.validate(self.rows)
        self.refresh_states()
        if problems:
            ui.message(self.window, u"Apply workset changes",
                       [u"{0} row(s) need a look first - they are marked \u26A0 in the Change "
                        u"column:".format(problems), u""] +
                       [u"   {0}  -  {1}".format(row.name or row.orig, row.problem)
                        for row in self.rows if row.problem], 600, 360)
            return
        plan = core.build_plan(self.rows)
        if not core.plan_count(plan):
            self.status(u"Nothing staged.")
            return
        text = u"This writes the changes below to the model as one undo step."
        if plan["deletes"]:
            text += (u" Elements on a deleted workset are moved to the workset named, "
                     u"never deleted.")
        if self.auto_editable():
            text += u" Worksets that need it are checked out to you first."
        if not ui.confirm(self.window, u"Apply workset changes", text, core.plan_lines(plan),
                          u"Apply {0} change{1}".format(core.plan_count(plan),
                                                        u"" if core.plan_count(plan) == 1 else u"s")):
            return

        auto = self.auto_editable()

        def work(uiapp):
            log = self.new_log()
            result = revit.apply_manage(self.doc, plan, auto, log)
            log.write(header=u"Apply workset changes")
            return result, revit.read_model(self.doc, self.settings)

        def done(payload):
            result, read = payload
            self.apply_read(read[0], read[1], keep=True)
            self.report_manage(result)
        self.run_job(u"apply worksets", work, done, u"Writing the workset changes...")

    def report_manage(self, result):
        lines = []
        for name in result["created"]:
            lines.append(u"Created   {0}".format(name))
        for old, new in result["renamed"]:
            lines.append(u"Renamed   {0}  ->  {1}".format(old, new))
        for name, target, count in result["deleted"]:
            lines.append(u"Deleted   {0}  ({1} elements moved to {2})".format(name, count, target))
        for name, target, count in result["merged"]:
            lines.append(u"Merged    {0}  into  {1}  ({2} elements)".format(name, target, count))
        if result["checked_out"]:
            lines.append(u"")
            lines.append(u"{0} workset(s) were checked out to you first.".format(
                result["checked_out"]))
        if result["refused"] or result["error"]:
            lines.append(u"")
            lines.append(u"Not done - still staged in the table:")
            for what, why in result["refused"]:
                lines.append(u"   {0}  -  {1}".format(what, why))
            if result["error"]:
                lines.append(u"   {0}".format(result["error"]))
        done = len(result["created"]) + len(result["renamed"]) + len(result["deleted"]) + \
            len(result["merged"])
        show = core.to_text(self.settings.get("show_results"))
        if show == "always" or (show != "never" and (result["refused"] or result["error"])):
            ui.message(self.window, u"Workset changes", lines or [u"Nothing changed."])
        self.status(u"{0} change(s) written{1}.".format(
            done, u", {0} refused - still in red".format(len(result["refused"]))
            if result["refused"] else u""))

    # ---------------------------------------------------------- assigner

    def build_assign_rows(self):
        host = self.w("AssignHost")
        host.Children.Clear()
        self.assign_rows = []
        if not self.records:
            host.Children.Add(ui.text_block(u"No worksets in this model.", 12, "MutedBrush"))
            return
        for record in self.records:
            row = AssignRow(self, record)
            self.assign_rows.append(row)
            host.Children.Add(row.element)
        self.filter_assign_rows()
        self.update_assign_status()

    def filter_assign_rows(self):
        needle = core.to_text(self.w("AssignSearch").Text)
        for row in self.assign_rows:
            row.element.Visibility = (Visibility.Visible if core.text_match(row.name, needle)
                                      else Visibility.Collapsed)

    def on_assign_search(self, sender, args):
        self.filter_assign_rows()

    def rebuild_claims(self):
        self.claims = core.build_claims(self.selections, self.scan)

    def assign_plan(self):
        plan = []
        for record in self.records:
            ids = core.element_ids_for(self.selections.get(record.name, set()), self.scan)
            if ids:
                plan.append((record.iid, record.name, ids))
        return plan

    def update_assign_status(self):
        total = sum([len(ids) for _, _, ids in self.assign_plan()])
        worksets = len([n for n in self.selections if self.selections[n]])
        label = u"Apply categories to worksets"
        if total:
            label = u"Apply categories to worksets ({0} elements)".format(total)
        self.w("ApplyAssignLabel").Text = label
        self.w("ApplyAssignButton").IsEnabled = bool(total)
        self.w("ClearAssignButton").IsEnabled = bool(worksets)
        if self.tab == "assign":
            if total:
                self.status(u"{0} element(s) queued for {1} workset(s) - press Apply categories "
                            u"to worksets.".format(total, worksets))
            else:
                self.status(u"{0} worksets, {1} model elements in {2} categories.".format(
                    len(self.records), self.scan.total, len(self.scan.entries)))

    def on_clear_assign(self, sender, args):
        self.selections = {}
        self.rebuild_claims()
        for row in self.assign_rows:
            row.refresh_label()
        self.update_assign_status()

    def on_apply_assign(self, sender, args):
        plan = self.assign_plan()
        if not plan:
            self.status(u"Nothing ticked - pick some categories first.")
            return
        auto = self.auto_editable()

        def work(uiapp):
            log = self.new_log()
            result = revit.apply_assignments(self.doc, plan, auto, log)
            log.write(header=u"Apply categories to worksets")
            read = None if result["error"] else revit.read_model(self.doc, self.settings)
            return result, read

        def done(payload):
            self.report_assign(payload[0], payload[1])
        self.run_job(u"apply categories", work, done, u"Moving elements onto worksets...")

    def report_assign(self, result, read):
        if result["error"]:
            ui.message(self.window, u"Workset Assigner",
                       [u"Nothing was written.", u"", result["error"]], 520, 280)
            self.status(u"Rolled back: " + result["error"])
            return
        self.selections = {}
        self.apply_read(read[0], read[1], keep=True)
        lines = [u"{0} element(s) moved, {1} already on the right workset.".format(
            result["moved"], result["already"]), u""]
        lines.extend(result["lines"])
        trouble = result["owned"] or result["not_borrowed"] or result["refused"]
        if trouble:
            lines.append(u"")
        if result["owned"]:
            owners = u", ".join([u"{0} ({1})".format(name, count)
                                 for name, count in sorted(result["owners"].items())])
            lines.append(u"{0} element(s) are borrowed by someone else and were left alone: "
                         u"{1}.".format(result["owned"], owners))
        if result["not_borrowed"]:
            lines.append(u"{0} element(s) could not be borrowed - usually they changed in "
                         u"central since you last synchronised.".format(result["not_borrowed"]))
        if result["refused"]:
            lines.append(u"{0} element(s) would not take a workset - group members and "
                         u"elements hosted by another are the usual reason.".format(
                             result["refused"]))
        show = core.to_text(self.settings.get("show_results"))
        if show == "always" or (show != "never" and trouble):
            ui.message(self.window, u"Workset Assigner", lines)
        self.status(u"{0} element(s) moved.".format(result["moved"]))

    def on_save_routine(self, sender, args):
        mapping = dict((name, sorted(keys)) for name, keys in self.selections.items() if keys)
        if not mapping:
            self.status(u"Nothing ticked to save.")
            return
        name = ui.prompt_text(self.window, u"Save routine",
                              u"Name this set of assignments. It is saved against this project.")
        if not name:
            return
        if core.save_routine(self.title, name, mapping):
            self.status(u"Routine '{0}' saved for this project.".format(name))
        else:
            self.status(u"Could not write the routine file.")

    def on_load_routine(self, sender, args):
        title = self.title
        routines = core.load_routines(title)
        if not routines:
            self.status(u"No saved routines for this project yet.")
            return

        def remove(name):
            return core.delete_routine(title, name)

        name = ui.prompt_choice(self.window, u"Load routine", u"Saved for this project:",
                                sorted(routines.keys(), key=core.natural_key),
                                on_delete=remove)
        if not name or name not in routines:
            return
        block = routines[name]
        missing = []
        self.selections = {}
        self.rebuild_claims()
        names = set(record.name for record in self.records)
        for workset in sorted(block.keys(), key=core.natural_key):
            if workset not in names:
                missing.append(u"{0}: not a workset in this model".format(workset))
                continue
            for key in block[workset]:
                entry = self.scan.by_key.get(key)
                if entry is None:
                    missing.append(u"{0}: a category no longer in use".format(workset))
                    continue
                if not core.free_for(self.claims, workset, key):
                    missing.append(u"{0}: {1} is already on another workset".format(
                        workset, entry.label))
                    continue
                self.selections[workset] = core.toggle(self.selections.get(workset, set()),
                                                       key, True, self.scan)
                self.rebuild_claims()
        for row in self.assign_rows:
            row.refresh_label()
        self.update_assign_status()
        if missing:
            ui.message(self.window, u"Load routine", [u"Not restored:"] +
                       [u"   " + line for line in missing], 560, 360)
        self.status(u"Routine '{0}' loaded - press Apply categories to worksets to write "
                    u"it.".format(name))

    # ---------------------------------------------------------- refresh, keys, close

    def on_refresh(self, sender, args):
        self.request_read(keep=True, then=lambda: self.status(
            u"Read the model again - staged changes and ticks kept."))

    def on_key(self, sender, args):
        try:
            if ui.text_box_has_focus():
                return
            control = (Keyboard.Modifiers & ModifierKeys.Control) == ModifierKeys.Control
            if args.Key == Key.F5:
                if self.tab == "scope":
                    self.scope.table.refresh_view()
                else:
                    self.commit_edits()
                    self.refresh_view()
                args.Handled = True
            elif self.tab == "scope" and args.Key == Key.Delete:
                self.scope.on_delete(None, None)
                args.Handled = True
            elif self.tab == "manage" and args.Key == Key.Delete:
                self.on_delete(None, None)
                args.Handled = True
            elif self.tab == "manage" and control and args.Key == Key.N:
                self.on_new(None, None)
                args.Handled = True
        except Exception as err:
            self.status(u"{0}".format(err))

    def on_close_click(self, sender, args):
        self.window.Close()

    def save_settings(self):
        self.settings["theme"] = self.theme_setting
        self.settings["tab"] = self.tab
        self.settings["auto_editable"] = "true" if self.auto_editable() else "false"
        if not self.chrome.full:
            self.settings["width"] = u"{0}".format(int(self.window.Width))
            self.settings["height"] = u"{0}".format(int(self.window.Height))
        core.save_settings(self.settings)

    def on_closing(self, sender, args):
        try:
            self.commit_edits()
            if not self.closing_ok:
                staged = core.plan_count(core.build_plan(self.rows)) + \
                    (self.scope.staged_count() if self.scope is not None else 0) + \
                    len([row for row in self.rows if row.problem])
                ticked = len(self.assign_plan())
                if staged or ticked:
                    parts = []
                    if staged:
                        parts.append(u"{0} staged change(s)".format(staged))
                    if ticked:
                        parts.append(u"category ticks on {0} workset(s)".format(ticked))
                    if not ui.confirm(self.window, u"Close", u"{0} have not been applied. "
                                      u"Close without applying them?".format(
                                          u" and ".join(parts)),
                                      None, u"Close", u"Keep working", "WsRedButton", 480, 220):
                        args.Cancel = True
                        return
            self.closing_ok = True
            self.save_settings()
            if self.isolated:
                # leave the view as it was found: everything showing
                self.run_job(u"un-isolate", lambda uiapp: revit.unisolate(
                    uiapp, self.doc, self.new_log()), lambda result: None, u"")
        except Exception:
            pass

    # ---------------------------------------------------------- the runner

    def new_log(self):
        return core.Log(core.as_bool(self.settings.get("debug"), True))

    def run_job(self, label, work, done, busy_text):
        """Hand work to Revit.  work(uiapp) runs in API context; done(result)
        runs back here.  Never waits - see wsm_runner."""
        if self.runner.queued(label):
            self.status(u"Still waiting for Revit to finish the last request.")
            return False

        def guarded(uiapp):
            try:
                valid = self.doc.IsValidObject
            except Exception:
                valid = False
            if not valid:
                raise revit.ToolStop(u"{0} has been closed - close this window and run "
                                     u"the tool again.".format(self.title))
            return work(uiapp)

        def finished(result, error):
            if self.closed:
                return
            self.status(u"")
            if error is not None:
                self.report_error(label, error)
                return
            try:
                done(result)
            except Exception as err:
                self.report_error(label, err)

        ok, why = self.runner.submit(label, guarded, finished)
        if not ok:
            self.status(why)
            return False
        if self.runner.busy():
            self.status(busy_text)
        return True

    def report_error(self, label, error):
        if isinstance(error, revit.ToolStop):
            self.status(core.to_text(error))
            ui.message(self.window, core.TOOL_NAME, [core.to_text(error)], 520, 240)
            return
        detail = self.runner.log[-1] if self.runner.log else core.to_text(error)
        self.status(u"{0} failed: {1}".format(label, error))
        ui.message(self.window, core.TOOL_NAME,
                   [u"{0} failed.".format(label.capitalize()), u"", detail], 680, 420)

    def on_watchdog(self, sender, args):
        dropped = self.runner.watchdog()
        if dropped:
            self.status(u"Revit did not pick up the request ({0}) - finish what you are "
                        u"doing in Revit, then try again.".format(u", ".join(dropped)))

    # ---------------------------------------------------------- 3D view

    def update_3d_buttons(self):
        selected = [key for key in self.selected_keys() if not self.by_key[key].is_new]
        self.w("IsolateButton").IsEnabled = bool(selected)
        self.w("IsolateLabel").Text = (u"Isolate selected ({0})".format(len(selected))
                                       if selected else u"Isolate selected")
        self.w("UnisolateButton").IsEnabled = bool(self.isolated)
        self.w("MergeButton").IsEnabled = len(self.selected_keys()) >= 2
        if self.isolated:
            names = u", ".join(self.isolated[:3])
            if len(self.isolated) > 3:
                names += u" +{0}".format(len(self.isolated) - 3)
            self.w("ViewHint").Text = u"Isolated: " + names
        elif self.view_name:
            self.w("ViewHint").Text = (u"Colours match the '{0}' view - pan in Revit with "
                                       u"this window open.".format(self.view_name))
        else:
            self.w("ViewHint").Text = (u"Show in 3D colours every element by workset, "
                                       u"matching the swatches.")

    def on_show_3d(self, sender, args):
        self.commit_edits()
        colours = dict(self.colours)
        direct = self.direct

        def work(uiapp):
            log = self.new_log()
            result = revit.show_in_3d(uiapp, self.doc, colours, direct, log)
            log.write(header=u"Show in 3D")
            return result

        def done(result):
            self.isolated = []
            self.view_name = result["name"]
            self.update_3d_buttons()
            total = sum(result["counts"].values())
            self.status(u"{0} the '{1}' view: {2} elements coloured over {3} worksets.".format(
                u"Made" if result["made"] else u"Refreshed", result["name"], total,
                len([c for c in result["counts"].values() if c])))
            self.queue_zoom(result["view_id"])
        self.run_job(u"show in 3D", work, done, u"Colouring the 3D view by workset...")

    def queue_zoom(self, view_id):
        """The view change was only requested; zoom once it has happened."""
        def work(uiapp):
            uidoc = revit.active_uidoc(uiapp, self.doc)
            return uidoc is not None and revit.zoom_view(uidoc, view_id)
        self.run_job(u"zoom", work, lambda result: None, u"")

    def on_isolate(self, sender, args):
        self.commit_edits()
        rows = [self.by_key[key] for key in self.selected_keys() if not self.by_key[key].is_new]
        if not rows:
            self.status(u"Select the worksets to isolate.")
            return
        iids = [row.iid for row in rows]
        names = [row.orig for row in rows]
        direct = self.direct

        def work(uiapp):
            log = self.new_log()
            result = revit.isolate_worksets(uiapp, self.doc, iids, direct, log)
            log.write(header=u"Isolate selected")
            return result

        def done(result):
            self.isolated = names
            self.update_3d_buttons()
            self.status(u"Isolated {0} elements on {1} workset(s) - Un-isolate to see "
                        u"everything again.".format(result["count"], len(names)))
        self.run_job(u"isolate", work, done, u"Isolating...")

    def on_unisolate(self, sender, args):
        def work(uiapp):
            return revit.unisolate(uiapp, self.doc, self.new_log())

        def done(result):
            self.isolated = []
            self.update_3d_buttons()
            self.status(u"Every workset showing again.")
        self.run_job(u"un-isolate", work, done, u"Un-isolating...")

    # ---------------------------------------------------------- merge

    def on_merge(self, sender, args):
        self.commit_edits()
        keys = self.selected_keys()
        if len(keys) < 2:
            self.status(u"Select two or more worksets to merge - Ctrl or Shift click.")
            return
        rows = [self.by_key[key] for key in keys]
        master = ui.merge_dialog(self.window, rows)
        if not master:
            return
        self.rows, problem = core.stage_merge(self.rows, keys, master)
        if problem:
            self.status(problem)
            return
        self.populate_table()
        moving = sum([row.count for row in self.rows if row.merge and row.delete_to == master])
        self.status(u"Merge into {0} staged in red - {1} elements move onto it and the "
                    u"others go when you press Apply.".format(
                        self.by_key[master].effective_name(), moving))

    # ---------------------------------------------------------- lifetime

    def on_rendered(self, sender, args):
        """Proof the engine is alive: this only runs if the window's handlers
        work, and only counts once the window is on screen."""
        if self.armed:
            self.armed = False
            clear_alive_note()

    def on_closed(self, sender, args):
        self.closed = True
        for timer in (self.filter_timer, self.preview_timer, self.watchdog):
            try:
                timer.Stop()
            except Exception:
                pass
        try:
            if AppDomain.CurrentDomain.GetData(WINDOW_KEY) is self.window:
                AppDomain.CurrentDomain.SetData(WINDOW_KEY, None)
                AppDomain.CurrentDomain.SetData(DOC_KEY, None)
        except Exception:
            pass
        if self in PARKED and not self.runner.busy():
            PARKED.remove(self)

    def show(self):
        if self.direct:
            self.window.ShowDialog()
            return
        ui.own(self.window, self.uiapp)
        write_alive_note()
        self.armed = True
        self.window.Show()


# ================================================================ launching

def write_alive_note():
    core._write_lines(core.ALIVE_PATH, [core.VERSION])


def clear_alive_note():
    try:
        if os.path.isfile(core.ALIVE_PATH):
            os.remove(core.ALIVE_PATH)
    except Exception:
        pass


def last_run_died():
    """A note left from a modeless run of this version that never proved its
    handlers ran means the engine died under it."""
    lines = core._read_lines(core.ALIVE_PATH)
    return bool(lines) and lines[0].strip() == core.VERSION


def bring_forward(document):
    """The window already open for this model comes to the front.  One open on
    another model is closed (it asks first if anything is staged)."""
    try:
        existing = AppDomain.CurrentDomain.GetData(WINDOW_KEY)
        if existing is None or not existing.IsLoaded:
            return False
        if core.to_text(AppDomain.CurrentDomain.GetData(DOC_KEY)) == \
                core.to_text(document.PathName or document.Title):
            existing.Activate()
            return True
        existing.Close()
        return existing.IsLoaded
    except Exception:
        return False


def run(uiapp, document):
    if bring_forward(document):
        return
    direct = False
    if last_run_died():
        direct = ui.confirm(None, core.TOOL_NAME,
                            u"Last time the window opened but did not respond. Open it as "
                            u"a dialog this time? Revit cannot be used while a dialog is "
                            u"open, but everything in the tool works.", None,
                            u"Open as a dialog", u"Try floating again", "WsOrangeButton",
                            520, 260)
        clear_alive_note()
    window = MainWindow(uiapp, document, direct)
    PARKED.append(window)
    if not direct:
        AppDomain.CurrentDomain.SetData(WINDOW_KEY, window.window)
        AppDomain.CurrentDomain.SetData(DOC_KEY, core.to_text(document.PathName or
                                                             document.Title))
    window.show()
