# -*- coding: utf-8 -*-
"""RevoBIM PY - Workset Management : a reusable staged table, and its rename panel.

GridTable is the Manage Worksets table taken apart from what it shows: a
DataGrid over a DataTable, filtered on a hidden 'vis' column and sorted on a
hidden 'gkey' column (so nothing moves while it is edited; F5 re-takes both),
every heading with a filter box and - where the values are worth picking from -
an Excel-style tick list, natural multi-level sorting, and inline renaming.

What it shows comes from a spec of plain functions in wsm_core, so the rules
stay testable on the bench.  Rows only need key, name, orig, delete_to and
state(); the staged state lives on them, never in the grid.

RenamePanel drives a bulk-rename card whose controls share a name prefix.
"""

import wsm_clr  # noqa: F401  (assemblies first)

from System.Data import DataTable                                      # noqa: E402
from System.Windows import (GridLength, GridUnitType, Thickness)       # noqa: E402
from System.Windows.Controls import (Border, CheckBox, ColumnDefinition,  # noqa: E402
                                     DataGridEditingUnit, DataGridLength,
                                     DataGridLengthUnitType, DataGridTextColumn,
                                     Grid, RowDefinition, ScrollBarVisibility,
                                     ScrollViewer, StackPanel, TextBlock, TextBox)
from System.Windows.Controls.Primitives import (PlacementMode, Popup,     # noqa: E402
                                                ToggleButton)
from System.Windows.Data import Binding                                # noqa: E402
from System.Windows.Input import Cursors, Keyboard, ModifierKeys       # noqa: E402

import wsm_core as core                                                # noqa: E402
import wsm_ui as ui                                                    # noqa: E402

SORT_KEYS = ("OrangeBrush", "BlueBrush", "GreenBrush")
CLEAR = "#00000000"


class TableSpec(object):
    """What a table shows.  columns: [(key, stars, minimum, cell style,
    placeholder)]; the rest are wsm_core functions."""

    def __init__(self, columns, titles, numeric, ticks, value, passes, tick_choices,
                 sort, change, validate, tips=None):
        self.columns = columns
        self.titles = titles
        self.numeric = numeric
        self.ticks = ticks
        self.value = value                  # value(row, column) -> shown
        self.passes = passes                # passes(row, filters, ticks, exclude)
        self.tick_choices = tick_choices    # tick_choices(rows, column, filters, ticks)
        self.sort = sort                    # sort(rows, stack)
        self.change = change                # change(row) -> Change text
        self.validate = validate            # validate(rows) -> problem count
        self.tips = tips or {}              # column -> tip(row), shown as a tooltip


class GridTable(object):

    def __init__(self, owner, grid, spec, on_refreshed=None):
        self.owner = owner
        self.window = owner.window
        self.grid = grid
        self.spec = spec
        self.on_refreshed = on_refreshed
        self.rows = []
        self.by_key = {}
        self.drows = {}
        self.filters = {}
        self.ticks = {}
        self.sort_stack = [("name", False)]
        self.headers = {}
        self.guard = 0
        self.problems = 0
        self.name_column = None
        self.filter_timer = ui.debounce(220, self.refresh_view)

        names = ["key", "state", "vis", "gkey"] + [c[0] for c in spec.columns] + \
            [u"tip_" + key for key in spec.tips]
        self.table = DataTable("rows")
        for name in names:
            self.table.Columns.Add(name)
        self.build()
        grid.BeginningEdit += self.on_beginning_edit
        self.table.RowChanged += self.on_row_changed

    # ---------------------------------------------------------- building

    def build(self):
        self.grid.ItemsSource = self.table.DefaultView
        self.table.DefaultView.RowFilter = "vis = '1'"
        self.table.DefaultView.Sort = "gkey ASC"
        for key, stars, minimum, cell_style, placeholder in self.spec.columns:
            column = DataGridTextColumn()
            column.Binding = Binding(key)
            column.Width = DataGridLength(stars, DataGridLengthUnitType.Star)
            column.MinWidth = minimum
            column.IsReadOnly = key != "name"
            column.CanUserSort = False
            column.ElementStyle = self.window.FindResource(cell_style)
            if key == "name":
                column.EditingElementStyle = self.window.FindResource("WsNameEdit")
                self.name_column = column
            column.Header = self.make_header(key, placeholder)
            self.grid.Columns.Add(column)

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
        title = ui.text_block(self.spec.titles[column], 12, "TextBrush", True)
        if column in self.spec.numeric:
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
        if column in self.spec.ticks:
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

    # ---------------------------------------------------------- rows

    def set_rows(self, rows):
        """A fresh set of rows: rebuild the table, keep sort and filters."""
        self.commit_edits()
        self.rows = list(rows)
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
        self.refresh_states()
        self.refresh_view()

    def refresh_states(self):
        """Validate, then write every row's text and state into the table."""
        self.problems = self.spec.validate(self.rows)
        self.by_key = dict((row.key, row) for row in self.rows)
        self.guard += 1
        try:
            for row in self.rows:
                record = self.drows.get(row.key)
                if record is None:
                    continue
                values = {"state": row.state(), "change": self.spec.change(row)}
                for key, _, _, _, _ in self.spec.columns:
                    if key != "change":
                        values[key] = core.to_text(self.spec.value(row, key))
                for key, tip in self.spec.tips.items():
                    values[u"tip_" + key] = tip(row)
                for column, value in values.items():
                    if core.to_text(record[column]) != value:
                        record[column] = value
        finally:
            self.guard -= 1
        if self.on_refreshed is not None:
            self.on_refreshed()

    def refresh_view(self):
        """Take the sort and the filters again - on a sort click, a filter
        change or F5, never mid-edit."""
        self.commit_edits()
        ordered = self.spec.sort(self.rows, self.sort_stack)
        self.guard += 1
        try:
            for place, row in enumerate(ordered):
                record = self.drows.get(row.key)
                if record is None:
                    continue
                vis = "1" if self.spec.passes(row, self.filters, self.ticks, None) else "0"
                gkey = "{0:06d}".format(place)
                if core.to_text(record["vis"]) != vis:
                    record["vis"] = vis
                if core.to_text(record["gkey"]) != gkey:
                    record["gkey"] = gkey
        finally:
            self.guard -= 1
        self.update_header_marks()
        if self.on_refreshed is not None:
            self.on_refreshed()

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
            if parts["caret"] is not None:
                parts["caret"].Tag = "on" if self.ticks.get(column) is not None else "off"

    def shown_keys(self):
        return [row.key for row in self.rows
                if row.key in self.drows and core.to_text(self.drows[row.key]["vis"]) == "1"]

    def selected_keys(self):
        keys = []
        for item in self.grid.SelectedItems:
            try:
                keys.append(core.to_text(item["key"]))
            except Exception:
                continue
        return [key for key in keys if key in self.by_key]

    def commit_edits(self):
        try:
            self.grid.CommitEdit(DataGridEditingUnit.Row, True)
        except Exception:
            pass

    def clear_filters(self):
        self.filters = {}
        self.ticks = {}
        for parts in self.headers.values():
            parts["box"].Text = u""
        self.refresh_view()

    # ---------------------------------------------------------- handlers

    def make_sort_handler(self, column):
        def handler(sender, args):
            try:
                shift = (Keyboard.Modifiers & ModifierKeys.Shift) == ModifierKeys.Shift
                self.sort_stack = core.push_sort(self.sort_stack, column, shift)
                self.refresh_view()
                args.Handled = True
            except Exception as err:
                self.owner.status(u"Sort failed: {0}".format(err))
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
                self.owner.status(u"Could not open the list: {0}".format(err))
        return handler

    def make_tick_closer(self, column):
        def handler(sender, args):
            caret = self.headers[column]["caret"]
            if caret is not None:
                caret.IsChecked = False
        return handler

    def open_ticks(self, column):
        parts = self.headers[column]
        choices = self.spec.tick_choices(self.rows, column, self.filters, self.ticks)
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
                self.ticks[column] = None if len(ticked) == len(boxes) else ticked
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

    def on_beginning_edit(self, sender, args):
        try:
            row = self.by_key.get(core.to_text(args.Row.Item["key"]))
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
        """A name typed into the table: stage it on the row.  Blank puts the
        original back."""
        try:
            for row in self.rows:
                record = self.drows.get(row.key)
                if record is None:
                    continue
                typed = core.to_text(record["name"]).strip()
                if not typed and not row.is_new:
                    typed = row.orig
                if typed != row.name:
                    row.name = typed
            self.refresh_states()
        except Exception as err:
            self.owner.status(u"Edit failed: {0}".format(err))


class RenamePanel(object):
    """The bulk-rename card.  Its controls are the Manage tab's names with a
    prefix: <prefix>FindBox, <prefix>CaseUpper and so on."""

    BOXES = ("FindBox", "ReplaceBox", "PrefixBox", "SuffixBox", "RemoveFirstBox", "RemoveLastBox")
    CASES = (("CaseKeep", "keep"), ("CaseUpper", "upper"), ("CaseLower", "lower"),
             ("CaseTitle", "title"))

    def __init__(self, owner, prefix, table, noun, on_staged):
        self.owner = owner
        self.prefix = prefix
        self.table = table
        self.noun = noun
        self.on_staged = on_staged
        self.case_mode = "keep"
        self.timer = ui.debounce(120, self.update)
        for name in self.BOXES:
            self.find(name).TextChanged += self.on_input
        self.find("MatchCaseCheck").Click += self.on_input
        self.find("TidyCheck").Click += self.on_input
        for name, mode in self.CASES:
            self.find(name).Click += self.make_case_handler(mode)
        self.find("RenameResetButton").Click += self.on_reset
        self.find("RenameStageButton").Click += self.on_stage
        self.table.grid.SelectionChanged += self.on_input

    def find(self, name):
        return self.owner.w(self.prefix + name)

    def ops(self):
        find = self.find
        return {
            "find": core.to_text(find("FindBox").Text),
            "replace": core.to_text(find("ReplaceBox").Text),
            "match_case": bool(find("MatchCaseCheck").IsChecked),
            "prefix": core.to_text(find("PrefixBox").Text),
            "suffix": core.to_text(find("SuffixBox").Text),
            "remove_first": core.as_int(find("RemoveFirstBox").Text, 0),
            "remove_last": core.as_int(find("RemoveLastBox").Text, 0),
            "case": self.case_mode,
            "tidy": bool(find("TidyCheck").IsChecked),
        }

    def scope(self):
        selected = self.table.selected_keys()
        if selected:
            return selected, u"Applies to the {0} selected {1}{2}.".format(
                len(selected), self.noun, u"" if len(selected) == 1 else u"es")
        shown = self.table.shown_keys()
        return shown, (u"Nothing selected - applies to all {0} {1}es shown. Select rows "
                       u"to narrow it.".format(len(shown), self.noun))

    def on_input(self, sender, args):
        ui.kick(self.timer)

    def make_case_handler(self, mode):
        def handler(sender, args):
            self.case_mode = mode
            for name, value in self.CASES:
                ui.style(self.find(name), "WsSegmentOn" if value == mode else "WsSegment")
            self.update()
        return handler

    def update(self):
        try:
            keys, text = self.scope()
            self.find("RenameScopeText").Text = text
            ops = self.ops()
            host = self.find("RenamePreviewHost")
            host.Children.Clear()
            empty = core.ops_empty(ops)
            plan = [] if empty else core.bulk_rename_plan(self.table.rows, keys, ops)
            if empty:
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
            self.find("RenameStageLabel").Text = (u"Stage rename ({0})".format(len(plan))
                                                  if plan else u"Stage rename")
            self.find("RenameStageButton").IsEnabled = bool(plan)
        except Exception as err:
            self.owner.status(u"Preview failed: {0}".format(err))

    def on_reset(self, sender, args):
        for name in self.BOXES:
            self.find(name).Text = u""
        self.find("MatchCaseCheck").IsChecked = False
        self.find("TidyCheck").IsChecked = False
        self.make_case_handler("keep")(None, None)

    def on_stage(self, sender, args):
        self.table.commit_edits()
        keys, _ = self.scope()
        plan = core.bulk_rename_plan(self.table.rows, keys, self.ops())
        if not plan:
            return
        for key, old, new in plan:
            self.table.by_key[key].name = new
        self.table.refresh_states()
        self.on_reset(None, None)
        self.on_staged(len(plan))
