# -*- coding: utf-8 -*-
"""Level Manager - the window, its table, and the dialogs it opens.

Every Revit read and write from here goes out through the ExternalEvent
runner in lvm_ops; the rules it applies live in lvm_core.
"""
import lvm_clr  # noqa: F401
import os
import traceback

from System import Action, AppDomain
from System import TimeSpan
from System.Data import DataTable
from System.Windows import (
    Thickness, Visibility, GridLength, GridUnitType, HorizontalAlignment,
    VerticalAlignment, Clipboard, FontWeights, TextTrimming, TextWrapping, CornerRadius,
    WindowStartupLocation,
)
from System.Windows.Controls import (
    DataGrid, DataGridTemplateColumn, DataGridTextColumn, DataGridLength,
    DataGridLengthUnitType, StackPanel, DockPanel, TextBlock, TextBox, Button,
    CheckBox, Orientation, Dock, ListBoxItem, Border, Grid, ColumnDefinition,
    ScrollViewer,
)
from System.Windows.Controls.Primitives import Popup, PlacementMode
from System.Windows.Data import Binding
from System.Windows.Input import Keyboard, ModifierKeys, Key, Cursors
from System.Windows.Media import VisualTreeHelper
from System.Windows.Threading import DispatcherTimer, DispatcherPriority
from Autodesk.Revit.UI import ExternalEvent, TaskDialog

import lvm_core as core
import lvm_revit as rv
import lvm_ops as ops
import lvm_ui as ui

to_text = core.to_text
DOT = u"  \u00B7  "

# Column key in the model -> column name in the DataTable
BASE_TABLE_COLS = ["key", "kind", "indent", "arrow", "tick", "state", "name",
                   "count", "id", "family", "type", "workset", "elev", "above", "note"]

_KEEP = []          # the window, runner and event, so the engine keeps them


class ModelChanged(Exception):
    pass


def guarded(fn):
    """Report a handler's failure instead of swallowing it: a silent handler
    is a dead button nobody can diagnose."""
    def wrapper(self, *args):
        try:
            return fn(self, *args)
        except Exception:
            self.report_error(fn.__name__, traceback.format_exc())
    wrapper.__name__ = fn.__name__
    return wrapper


def write_text(name, text):
    try:
        folder = core.settings_dir()
        if not os.path.isdir(folder):
            os.makedirs(folder)
        with open(os.path.join(folder, name), "wb") as handle:
            handle.write(to_text(text).encode("utf-8"))
        return True
    except Exception:
        return False


def read_file_text(name):
    try:
        with open(os.path.join(core.settings_dir(), name), "rb") as handle:
            return handle.read().decode("utf-8", "replace")
    except Exception:
        return u""


def remove_file(name):
    try:
        os.remove(os.path.join(core.settings_dir(), name))
    except Exception:
        pass


def text_block(text, muted=False, bold=False):
    tb = TextBlock()
    tb.Text = to_text(text)
    tb.VerticalAlignment = VerticalAlignment.Center
    if bold:
        tb.FontWeight = FontWeights.SemiBold
    if muted:
        tb.SetResourceReference(TextBlock.ForegroundProperty, "Muted")
    return tb


def row_tag(source):
    """Walk up from what was clicked: ('arrow' | 'tick' | None, row view)."""
    tag = None
    node = source
    for _ in range(40):
        if node is None:
            break
        try:
            t = getattr(node, "Tag", None)
            if tag is None and t in ("arrow", "tick"):
                tag = t
            ctx = getattr(node, "DataContext", None)
            if ctx is not None and hasattr(ctx, "Row") and tag is not None:
                return tag, ctx
        except Exception:
            pass
        try:
            node = VisualTreeHelper.GetParent(node)
        except Exception:
            break
    return None, None


def find_scroller(root):
    """The DataGrid's own ScrollViewer, to keep the place across a rebuild."""
    try:
        stack = [root]
        while stack:
            node = stack.pop(0)
            if isinstance(node, ScrollViewer):
                return node
            for i in range(VisualTreeHelper.GetChildrenCount(node)):
                stack.append(VisualTreeHelper.GetChild(node, i))
    except Exception:
        pass
    return None


def row_view_at(source):
    node = source
    for _ in range(40):
        if node is None:
            return None
        try:
            ctx = getattr(node, "DataContext", None)
            if ctx is not None and hasattr(ctx, "Row"):
                return ctx
            node = VisualTreeHelper.GetParent(node)
        except Exception:
            return None
    return None


# =========================================================================
# The main window
# =========================================================================

class LevelManagerWindow(object):

    def __init__(self, uiapp, runner, data, settings, start_ids=None):
        self.uiapp = uiapp
        self.runner = runner
        self.settings = settings
        self.debug = settings.get("debug") == "1"
        self.debug_lines = []
        self.theme_mode = settings.get("theme", "auto")
        self.canvas_dark = rv.canvas_is_dark(uiapp)
        self.busy = False
        self.closed = False
        self.ids = data["ids"]
        self.doc_key = data["doc_key"]
        self.doc_title = data["title"]
        self.header_parts = {}
        self.col_of = {}
        self.table_data = None
        self.quiet = False
        self.popup = None
        self.model = core.Model(data["levels"], data["elements"],
                                core.split_params(settings.get("params", u"")))
        self.model.show_workset = bool(data["workshared"])

        self.win = ui.load_xaml("LevelManager.xaml")
        ui.themed(self.win, self.palette())
        self.grid = self.win.FindName("Table")
        self.status = self.win.FindName("StatusTxt")
        self.assign_btn = self.win.FindName("AssignBtn")
        self.search_box = self.win.FindName("SearchBox")
        self.progress = self.win.FindName("Progress")
        self.progress_txt = self.win.FindName("ProgressTxt")
        self.progress_row = self.win.FindName("ProgressRow")
        self.chips = self.win.FindName("Chips")
        self.chips_row = self.win.FindName("ChipsRow")
        self.debug_chk = self.win.FindName("DebugChk")
        self.theme_btn = self.win.FindName("ThemeBtn")

        self.win.FindName("VersionTxt").Text = u"v" + core.__version__
        ui.set_logo(self.win.FindName("Logo"))
        self.chrome = ui.Chrome(self.win, self.win.FindName("Header"),
                                self.win.FindName("CloseBtn"),
                                self.win.FindName("FullBtn"),
                                self.win.FindName("Grips"),
                                self.win.FindName("FullGlyph"),
                                self.win.FindName("ShrinkBtn"))
        ui.wire_egg(self.win, self.win.FindName("Logo"), self.theme_name)

        self._icons()
        self._restore_bounds()
        self.debug_chk.IsChecked = self.debug

        self.timer = DispatcherTimer()
        self.timer.Interval = TimeSpan.FromMilliseconds(220)
        self.timer.Tick += self.on_timer

        runner.dispatcher = self.win.Dispatcher
        runner.on_busy = self.set_busy
        runner.log = self.dlog

        self._wire()
        self.build_columns()
        self.build_chips()

        if start_ids:
            n = self.model.tick_ids(start_ids)
            if n:
                self.model.open_levels_of(start_ids)
                self.first_note = u"Opened on {0} element{1} selected in Revit - ticked.".format(
                    n, u"" if n == 1 else u"s")
            else:
                self.first_note = u""
        else:
            self.first_note = u""
        self.render()
        if self.first_note:
            self.status.Text = self.first_note + DOT + self.status.Text
        self.dlog(u"opened on {0} ({1} levels, {2} elements)".format(
            self.doc_title, len(self.model.levels), self.model.total()))

    # ---- wiring ------------------------------------------------------------
    def _icons(self):
        f = self.win.FindName
        ui.line_icon(f("ExpandLevelsBtn"), "levels", u"Show categories")
        ui.line_icon(f("ExpandBtn"), "expand", u"Expand all")
        ui.line_icon(f("CollapseBtn"), "collapse", u"Collapse all")
        ui.line_icon(f("ClearFiltersBtn"), "clear", u"Clear filters")
        ui.line_icon(f("UntickBtn"), "untick", u"Untick all")
        ui.line_icon(f("FromRevitBtn"), "fromrevit", u"From Revit selection")
        ui.line_icon(f("AddParamBtn"), "plus", u"Add parameter")
        ui.line_icon(f("RefreshBtn"), "refresh", u"Refresh")
        ui.line_icon(f("CopyDebugBtn"), "copy", u"Copy debug")
        ui.line_icon(f("SelectBtn"), "select", u"Select in Revit")
        ui.line_icon(f("IsolateBtn"), "cube", u"Isolate in 3D in Revit")
        ui.line_icon(f("DeleteLevelBtn"), "delete", u"Delete Level")
        ui.line_icon(self.assign_btn, "assign", u"Assign Level")
        ui.line_icon(self.theme_btn, "theme", core.theme_label(self.theme_mode))

    def _wire(self):
        f = self.win.FindName
        f("ExpandLevelsBtn").Click += self.on_expand_levels
        f("ExpandBtn").Click += self.on_expand_all
        f("CollapseBtn").Click += self.on_collapse_all
        f("ClearFiltersBtn").Click += self.on_clear_filters
        f("UntickBtn").Click += self.on_untick
        f("FromRevitBtn").Click += self.on_from_revit
        f("AddParamBtn").Click += self.on_add_param
        f("RefreshBtn").Click += self.on_refresh
        f("CopyDebugBtn").Click += self.on_copy_debug
        f("SelectBtn").Click += self.on_select
        f("IsolateBtn").Click += self.on_isolate
        f("DeleteLevelBtn").Click += self.on_delete_level
        self.assign_btn.Click += self.on_assign
        self.theme_btn.Click += self.on_theme
        self.debug_chk.Click += self.on_debug
        self.search_box.TextChanged += self.on_search
        self.grid.PreviewMouseLeftButtonDown += self.on_grid_down
        self.grid.MouseDoubleClick += self.on_grid_double
        self.grid.SelectionChanged += self.on_selection
        self.grid.PreviewKeyDown += self.on_grid_key
        self.win.Activated += self.on_activated
        self.win.Closing += self.on_closing
        self.win.Closed += self.on_closed
        self.win.ContentRendered += self.on_rendered

    # ---- theme ---------------------------------------------------------------
    def palette(self):
        return core.palette_for(self.theme_mode, self.canvas_dark)

    def set_vis(self, element, value):
        """Rows the tool shows and hides go through the drawer, so nothing
        pops up inside the parked bar and the row is right when it opens."""
        drawer = getattr(getattr(self, "chrome", None), "drawer", None)
        if drawer is not None:
            drawer.set_visibility(element, value)
        else:
            element.Visibility = value

    def theme_name(self):
        return core.resolve_theme(self.theme_mode, self.canvas_dark)

    @guarded
    def on_theme(self, sender, args):
        self.theme_mode = core.next_theme_mode(self.theme_mode)
        if self.theme_mode == "auto":
            self.canvas_dark = rv.canvas_is_dark(self.uiapp)
        ui.apply_palette(self.win, self.palette())
        ui.set_label(self.theme_btn, core.theme_label(self.theme_mode))
        self.settings["theme"] = self.theme_mode
        core.save_settings_file(self.settings)

    @guarded
    def on_activated(self, sender, args):
        if self.theme_mode != "auto":
            return
        now = rv.canvas_is_dark(self.uiapp)
        if now is not None and now != self.canvas_dark:
            self.canvas_dark = now
            ui.apply_palette(self.win, self.palette())

    # ---- columns -------------------------------------------------------------
    def build_columns(self):
        self.grid.Columns.Clear()
        self.header_parts = {}
        self.col_of = {}
        keys = self.model.visible_keys()
        spec = dict((c[0], c) for c in core.COLUMNS)
        param_index = 0
        for key in keys:
            if core.is_param_key(key):
                col_name = u"p{0}".format(param_index)
                param_index += 1
                title = core.param_name(key)
                min_w, weight, filterable, numeric = 120, 1.0, True, False
            else:
                col_name = key
                _, title, min_w, weight, filterable, numeric = spec[key]
            self.col_of[key] = col_name
            if key == "name":
                col = DataGridTemplateColumn()
                col.CellTemplate = ui.load_xaml("TreeCell.xaml")
            else:
                col = DataGridTextColumn()
                col.Binding = Binding(col_name)
                style = self.win.TryFindResource("CellNumber" if numeric else "CellText")
                if style is not None:
                    col.ElementStyle = style
            col.Header = self.make_header(key, title, filterable and key != "count")
            col.MinWidth = min_w
            col.Width = DataGridLength(weight, DataGridLengthUnitType.Star)
            self.grid.Columns.Add(col)
        self.grid.SetResourceReference(DataGrid.RowStyleProperty, "LvmRow")
        self.paint_headers()

    def make_header(self, key, title, filterable):
        panel = StackPanel()
        title_tb = TextBlock()
        title_tb.Text = to_text(title)
        title_tb.FontWeight = FontWeights.SemiBold
        title_tb.TextTrimming = TextTrimming.CharacterEllipsis
        title_tb.Margin = Thickness(0, 0, 0, 4)
        title_tb.ToolTip = u"Click to sort, Shift+click to add a level"
        if key != "count":
            title_tb.Cursor = Cursors.Hand
            # the header is a ButtonBase that captures the mouse on the way
            # down, so the sort is taken on the preview and marked handled
            title_tb.PreviewMouseLeftButtonDown += self._sort_handler(key)
        panel.Children.Add(title_tb)
        box = None
        caret = None
        if filterable:
            dock = DockPanel()
            caret = Button()
            caret.Width = 24
            caret.Height = 24
            caret.Margin = Thickness(3, 0, 0, 0)
            caret.Padding = Thickness(0)
            caret.ToolTip = u"Pick values to show"
            ui.line_icon(caret, "caret", u"")
            DockPanel.SetDock(caret, Dock.Right)
            caret.Click += self._caret_handler(key)
            dock.Children.Add(caret)
            box = TextBox()
            box.Height = 24
            box.Tag = u"filter"
            box.Padding = Thickness(3, 1, 3, 1)
            box.Text = to_text(self.model.col_filters.get(key, u""))
            box.TextChanged += self._filter_handler(key)
            dock.Children.Add(box)
            panel.Children.Add(dock)
        self.header_parts[key] = (title_tb, box, caret, to_text(title))
        return panel

    def _sort_handler(self, key):
        def handler(sender, args):
            try:
                shift = (Keyboard.Modifiers & ModifierKeys.Shift) == ModifierKeys.Shift
                self.model.click_sort(key, shift)
                self.paint_headers()
                self.render()
                args.Handled = True
            except Exception:
                self.report_error("sort", traceback.format_exc())
        return handler

    def _filter_handler(self, key):
        def handler(sender, args):
            try:
                self.model.col_filters[key] = to_text(sender.Text)
                self.model.filter_collapsed = set()
                self.kick()
            except Exception:
                self.report_error("filter", traceback.format_exc())
        return handler

    def _caret_handler(self, key):
        def handler(sender, args):
            try:
                self.open_value_popup(key, sender)
            except Exception:
                self.report_error("value list", traceback.format_exc())
        return handler

    def paint_headers(self):
        for key, (title_tb, box, caret, title) in self.header_parts.items():
            badge = self.model.sort_badge(key)
            title_tb.Text = u"{0}  {1}".format(title, badge) if badge else title
            if badge:
                title_tb.SetResourceReference(TextBlock.ForegroundProperty, "Orange")
            else:
                title_tb.SetResourceReference(TextBlock.ForegroundProperty, "Text")
            if caret is not None:
                if self.model.val_filters.get(key) is not None:
                    caret.SetResourceReference(Button.ForegroundProperty, "Orange")
                    caret.SetResourceReference(Button.BorderBrushProperty, "Orange")
                else:
                    caret.SetResourceReference(Button.ForegroundProperty, "Muted")
                    caret.SetResourceReference(Button.BorderBrushProperty, "Edge")

    def build_chips(self):
        self.chips.Children.Clear()
        for name in self.model.param_cols:
            chip = Border()
            chip.CornerRadius = CornerRadius(11)
            chip.BorderThickness = Thickness(1)
            chip.Padding = Thickness(8, 1, 2, 1)
            chip.Margin = Thickness(0, 0, 6, 4)
            chip.SetResourceReference(Border.BorderBrushProperty, "Blue")
            chip.SetResourceReference(Border.BackgroundProperty, "Card")
            row = StackPanel()
            row.Orientation = Orientation.Horizontal
            row.Children.Add(text_block(name))
            x = Button()
            x.Width = 20
            x.Height = 20
            x.Padding = Thickness(0)
            x.Margin = Thickness(4, 0, 0, 0)
            x.BorderThickness = Thickness(0)
            x.ToolTip = u"Remove this column"
            ui.line_icon(x, "close", u"")
            x.Click += self._remove_param_handler(name)
            row.Children.Add(x)
            chip.Child = row
            self.chips.Children.Add(chip)
        self.set_vis(self.chips_row, Visibility.Visible if self.model.param_cols else Visibility.Collapsed)

    def _remove_param_handler(self, name):
        def handler(sender, args):
            try:
                key = core.param_key(name)
                self.model.param_cols = [p for p in self.model.param_cols if p != name]
                self.model.col_filters.pop(key, None)
                self.model.val_filters.pop(key, None)
                self.model.sort_stack = [s for s in self.model.sort_stack if s[0] != key]
                self.model.reset_cache()
                self.save_params()
                self.build_columns()
                self.build_chips()
                self.render()
            except Exception:
                self.report_error("remove column", traceback.format_exc())
        return handler

    def save_params(self):
        self.settings["params"] = core.join_params(self.model.param_cols)
        core.save_settings_file(self.settings)

    # ---- rendering -----------------------------------------------------------
    def kick(self):
        self.timer.Stop()
        self.timer.Start()

    @guarded
    def on_timer(self, sender, args):
        self.timer.Stop()
        self.paint_headers()
        self.render()

    def table_columns(self):
        cols = list(BASE_TABLE_COLS)
        for key, col in self.col_of.items():
            if core.is_param_key(key):
                cols.append(col)
        return cols

    def render(self):
        keep = set(self.highlighted_keys())
        rows = self.model.rows()
        table = DataTable("rows")
        cols = self.table_columns()
        for c in cols:
            table.Columns.Add(c)
        reverse = dict((v, k) for k, v in self.col_of.items())
        table.BeginLoadData()
        for r in rows:
            dr = table.NewRow()
            for c in cols:
                if c == "indent":
                    value = to_text(r["depth"] * 16)
                else:
                    value = r.get(reverse.get(c, c), u"")
                dr[c] = to_text(value)
            table.Rows.Add(dr)
        table.EndLoadData()
        self.table_data = table
        scroller = find_scroller(self.grid)
        offset = scroller.VerticalOffset if scroller is not None else 0.0
        self.grid.ItemsSource = table.DefaultView
        if scroller is not None and offset > 0:
            try:
                self.grid.UpdateLayout()
                scroller.ScrollToVerticalOffset(offset)
            except Exception:
                pass
        if keep:
            self.quiet = True
            try:
                for item in self.grid.Items:
                    try:
                        if to_text(item["key"]) in keep:
                            self.grid.SelectedItems.Add(item)
                    except Exception:
                        continue
            finally:
                self.quiet = False
        self.update_status()

    def refresh_ticks(self):
        """Ticks change in place - no rebuild, so nothing moves under the cursor."""
        if self.table_data is None:
            return
        for dr in self.table_data.Rows:
            key = to_text(dr["key"])
            kind, lid, cat, eid = core.parse_key(key)
            if kind == "E":
                value = "1" if eid in self.model.ticked else "0"
            else:
                value = self.model.tick_state(self.model.ids_for_key(key))
            if to_text(dr["tick"]) != value:
                dr["tick"] = value
        self.update_status()

    def highlighted_keys(self):
        out = []
        try:
            for item in self.grid.SelectedItems:
                out.append(to_text(item["key"]))
        except Exception:
            pass
        return out

    def chosen_ids(self):
        return self.model.selection(self.highlighted_keys())

    def update_status(self):
        chosen = self.chosen_ids()
        n = len(chosen)
        parts = [u"{0} levels".format(len(self.model.levels)),
                 u"{0} elements".format(core.thousands(self.model.total()))]
        if self.model.filter_active():
            parts.append(u"{0} match the filters".format(core.thousands(self.model.last_match)))
        if n:
            parts.append(u"{0} chosen ({1} ticked)".format(core.thousands(n), core.thousands(len(self.model.ticked))))
        self.status.Text = DOT.join(parts)
        self.status.ToolTip = self.status.Text
        ready = n > 0 and not self.busy
        self.assign_btn.IsEnabled = ready
        self.win.FindName("SelectBtn").IsEnabled = ready
        self.win.FindName("IsolateBtn").IsEnabled = ready
        level = core.single_level(self.highlighted_keys())
        delete_btn = self.win.FindName("DeleteLevelBtn")
        delete_btn.IsEnabled = level is not None and len(self.model.levels) > 1 and not self.busy
        if level is not None:
            ui.set_label(delete_btn, u"Delete {0}".format(self.model.level_by_id[level]["name"]))
        else:
            ui.set_label(delete_btn, u"Delete Level")
        ui.set_label(self.assign_btn, u"Assign Level ({0})".format(core.thousands(n)) if n else u"Assign Level")

    # ---- table events --------------------------------------------------------
    @guarded
    def on_grid_down(self, sender, args):
        tag, view = row_tag(args.OriginalSource)
        if tag is None or view is None:
            return
        key = to_text(view["key"])
        if tag == "arrow":
            kind = core.parse_key(key)[0]
            if kind in ("L", "C"):
                self.model.toggle_open(key)
                self.render()
            args.Handled = True
        elif tag == "tick":
            self.model.toggle_tick(key, set(self.highlighted_keys()))
            self.refresh_ticks()
            args.Handled = True

    @guarded
    def on_grid_double(self, sender, args):
        if row_tag(args.OriginalSource)[0] is not None:
            args.Handled = True         # the arrow or tick already took both clicks
            return
        view = row_view_at(args.OriginalSource)
        if view is None:
            return
        key = to_text(view["key"])
        kind, lid, cat, eid = core.parse_key(key)
        if kind in ("L", "C"):
            self.model.toggle_open(key)
            self.render()
        elif kind == "E":
            self.select_ids([eid], show=True)
        args.Handled = True

    @guarded
    def on_grid_key(self, sender, args):
        if isinstance(args.OriginalSource, TextBox):
            return                      # typing in a heading's filter box
        keys = self.highlighted_keys()
        if args.Key == Key.Space and keys:
            self.model.toggle_tick(keys[0], set(keys))
            self.refresh_ticks()
            args.Handled = True
        elif args.Key in (Key.Right, Key.Left) and len(keys) == 1:
            kind = core.parse_key(keys[0])[0]
            if kind in ("L", "C"):
                is_open = self.model.is_open(keys[0])
                if (args.Key == Key.Right) != is_open:
                    self.model.toggle_open(keys[0])
                    self.render()
                args.Handled = True

    @guarded
    def on_selection(self, sender, args):
        if self.quiet:
            return
        self.update_status()

    # ---- toolbar -------------------------------------------------------------
    @guarded
    def on_search(self, sender, args):
        self.model.search = to_text(self.search_box.Text)
        self.model.filter_collapsed = set()
        self.kick()

    @guarded
    def on_expand_levels(self, sender, args):
        self.model.expand_all(categories=False)
        self.render()

    @guarded
    def on_expand_all(self, sender, args):
        self.model.expand_all(categories=True)
        self.render()

    @guarded
    def on_collapse_all(self, sender, args):
        self.model.collapse_all()
        self.render()

    @guarded
    def on_clear_filters(self, sender, args):
        self.model.clear_filters()
        self.search_box.Text = u""
        for key, (title_tb, box, caret, title) in self.header_parts.items():
            if box is not None:
                box.Text = u""
        self.model.clear_filters()
        self.timer.Stop()
        self.paint_headers()
        self.render()

    @guarded
    def on_untick(self, sender, args):
        self.model.untick_all()
        self.refresh_ticks()

    @guarded
    def on_debug(self, sender, args):
        self.debug = bool(self.debug_chk.IsChecked)
        self.settings["debug"] = "1" if self.debug else "0"
        core.save_settings_file(self.settings)
        if self.debug:
            self.dlog(u"debug on - Level Manager v{0}".format(core.__version__))
            self.flush_debug()

    @guarded
    def on_copy_debug(self, sender, args):
        self.flush_debug()
        text = read_file_text(core.DEBUG_NAME)
        if not text:
            self.status.Text = u"No debug log yet - tick Debug, run the tool, then copy."
            return
        Clipboard.SetText(text)
        self.status.Text = u"Debug log copied - paste it to Claude."

    # ---- value filter popup ----------------------------------------------------
    def open_value_popup(self, key, anchor):
        title = self.header_parts.get(key, (None, None, None, key))[3]
        values = self.model.values_for(key)
        allowed = self.model.val_filters.get(key)

        def apply(new_allowed):
            if new_allowed is None:
                self.model.val_filters.pop(key, None)
            else:
                self.model.val_filters[key] = new_allowed
            self.model.filter_collapsed = set()
            self.paint_headers()
            self.render()

        self.popup = ValuePopup(self, anchor, title, values, allowed, apply)

    # ---- busy and progress ---------------------------------------------------
    def set_busy(self, value):
        self.busy = value
        try:
            for name in ("RefreshBtn", "AddParamBtn", "FromRevitBtn"):
                self.win.FindName(name).IsEnabled = not value
            if not value:
                self.set_vis(self.progress_row, Visibility.Collapsed)
            self.update_status()
        except Exception:
            pass

    def show_progress(self, done, total):
        """Called between transactions only - repainting inside one is how
        a transaction gets interrupted."""
        try:
            pct = int(100.0 * done / total) if total else 100
            self.set_vis(self.progress_row, Visibility.Visible)
            self.progress.Value = pct
            self.progress_txt.Text = u"{0}%".format(pct)
            self.status.Text = u"Assigning... {0} of {1}".format(done, total)
            # Render only: repaint the bar, leave clicks queued until the run ends
            self.win.Dispatcher.Invoke(DispatcherPriority.Render, Action(lambda: None))
        except Exception:
            pass

    # ---- jobs ------------------------------------------------------------------
    def active_doc(self, uiapp, allow_switch=False):
        uidoc = uiapp.ActiveUIDocument
        if uidoc is None:
            raise ModelChanged(u"No model is open.")
        doc = uidoc.Document
        if not allow_switch and rv.doc_key(doc) != self.doc_key:
            raise ModelChanged(u"The active model is '{0}', but this window was read from '{1}'. "
                               u"Press Refresh to read the active model.".format(
                                   to_text(doc.Title), self.doc_title))
        return doc

    def submit(self, name, job, callback):
        if self.busy and not self.runner.direct:
            self.dlog(u"click ignored while busy: " + name)
            self.status.Text = u"Still working on the last request..."
            return False
        ok = self.runner.submit(name, job, callback)
        if not ok:
            self.status.Text = u"Revit did not accept the request - try again."
        return ok

    def failed(self, result):
        """True when a job came back failed; the status line says why."""
        if isinstance(result, ops.JobFailed):
            text = result.text
            if u"ModelChanged" in text:
                text = text.strip().splitlines()[-1].split(u":", 1)[-1].strip()
                self.status.Text = text
            else:
                self.status.Text = u"That did not work - tick Debug and send the log."
                self.dlog(text)
                write_text(core.ERROR_NAME, text)
            self.flush_debug()
            return True
        return False

    @guarded
    def on_refresh(self, sender, args):
        params = list(self.model.param_cols)

        def job(uiapp):
            doc = self.active_doc(uiapp, allow_switch=True)
            return rv.read_project(doc, params, self.dlog)

        def done(data):
            if self.failed(data):
                return
            switched = data["doc_key"] != self.doc_key
            if switched:
                self.model.untick_all()
            self.reload(data)
            if switched:
                self.status.Text = u"Read '{0}'.".format(self.doc_title) + DOT + self.status.Text
            self.flush_debug()

        self.status.Text = u"Reading the model..."
        self.submit("refresh", job, done)

    def reload(self, data):
        self.ids = data["ids"]
        self.doc_key = data["doc_key"]
        self.doc_title = data["title"]
        had_ws = self.model.show_workset
        self.model.load(data["levels"], data["elements"])
        self.model.reset_cache()
        self.model.show_workset = bool(data["workshared"])
        if had_ws != self.model.show_workset:
            self.build_columns()
        self.render()

    @guarded
    def on_from_revit(self, sender, args):
        def job(uiapp):
            self.active_doc(uiapp)
            return rv.current_selection(uiapp.ActiveUIDocument)

        def done(ids):
            if self.failed(ids):
                return
            if not ids:
                self.status.Text = u"Nothing is selected in Revit."
                return
            n = self.model.tick_ids(ids)
            self.model.open_levels_of(ids)
            self.render()
            missing = len(ids) - n
            text = u"Ticked {0} element{1} selected in Revit.".format(n, u"" if n == 1 else u"s")
            if missing:
                text += u" {0} are not model elements on a level, or the list is out of date (Refresh).".format(missing)
            self.status.Text = text + DOT + self.status.Text

        self.submit("from revit", job, done)

    @guarded
    def on_select(self, sender, args):
        self.select_ids(self.chosen_ids(), show=False)

    def select_ids(self, ids, show=False):
        eids = [self.ids[i] for i in ids if i in self.ids]
        if not eids:
            return

        def job(uiapp):
            self.active_doc(uiapp)
            return rv.select_in_revit(uiapp.ActiveUIDocument, eids, show)

        def done(n):
            if self.failed(n):
                return
            self.status.Text = u"Selected {0} element{1} in Revit.".format(n, u"" if n == 1 else u"s")

        self.submit("select", job, done)

    @guarded
    def on_add_param(self, sender, args):
        infos = list(self.model.elements.values())
        ids = self.ids

        def job(uiapp):
            doc = self.active_doc(uiapp)
            return rv.parameter_names(doc, infos, ids)

        def done(names):
            if self.failed(names):
                return
            chosen = ParamDialog(self, names, self.model.param_cols).show()
            if chosen is None or chosen == self.model.param_cols:
                return
            self.apply_params(chosen)

        self.status.Text = u"Reading the project's parameters..."
        self.submit("parameter names", job, done)

    def apply_params(self, chosen):
        new = [p for p in chosen if p not in self.model.param_cols]
        all_ids = list(self.model.elements.keys())
        idmap = self.ids

        def finish(values):
            for name, vals in values.items():
                self.model.set_param_values(name, vals)
            dropped = [p for p in self.model.param_cols if p not in chosen]
            for name in dropped:
                key = core.param_key(name)
                self.model.col_filters.pop(key, None)
                self.model.val_filters.pop(key, None)
            self.model.sort_stack = [s for s in self.model.sort_stack
                                     if not core.is_param_key(s[0]) or core.param_name(s[0]) in chosen]
            self.model.param_cols = list(chosen)
            self.model.reset_cache()
            self.save_params()
            self.build_columns()
            self.build_chips()
            self.render()

        if not new:
            finish({})
            return

        def job(uiapp):
            doc = self.active_doc(uiapp)
            out = {}
            for name in new:
                out[name] = rv.param_values(doc, all_ids, idmap, name)
            return out

        def done(values):
            if self.failed(values):
                return
            finish(values)

        self.status.Text = u"Reading {0} parameter{1}...".format(len(new), u"" if len(new) == 1 else u"s")
        self.submit("parameter values", job, done)

    # ---- isolate in 3D -----------------------------------------------------------
    @guarded
    def on_isolate(self, sender, args):
        ids = self.chosen_ids()
        eids = [self.ids[i] for i in ids if i in self.ids]
        if not eids:
            return
        level_eids = [self.ids[lv["id"]] for lv in self.model.levels if lv["id"] in self.ids]

        def job(uiapp):
            self.active_doc(uiapp)
            return rv.isolate_in_3d(uiapp.ActiveUIDocument, eids, level_eids, self.dlog)

        def done(rep):
            if self.failed(rep):
                return
            if rep["ok"]:
                text = u"Isolated {0} element{1} in {2}{3} with the levels and section box.".format(
                    rep["isolated"], u"" if rep["isolated"] == 1 else u"s", rep["view"],
                    u" (new view)" if rep["created"] else u"")
                if rep["levels_shown"]:
                    text += u" Levels were hidden in that view and are now shown."
            else:
                text = u"Isolate in 3D did not finish."
            if rep["notes"]:
                text += u" " + u" ".join(rep["notes"])
            self.status.Text = text
            self.dlog(text)
            self.flush_debug()

        self.status.Text = u"Opening the default 3D view..."
        self.submit("isolate", job, done)

    # ---- delete a level -------------------------------------------------------
    @guarded
    def on_delete_level(self, sender, args):
        source = core.single_level(self.highlighted_keys())
        if source is None or len(self.model.levels) < 2:
            return
        idmap = self.ids

        def job(uiapp):
            doc = self.active_doc(uiapp)
            active = None
            try:
                active = uiapp.ActiveUIDocument.ActiveView.Id
            except Exception:
                pass
            return rv.preview_delete(doc, source, idmap, active)

        def done(preview):
            if self.failed(preview):
                return
            impact = core.delete_impact(self.model, source, preview)
            if impact["error"]:
                self.status.Text = u"Revit will not delete this level: " + impact["error"]
                return
            self.dlog(u"delete preview for {0}: {1} moving, {2} lost, {3} views, {4} sheets".format(
                source, len(impact["moving"]), len(impact["lost"]), len(impact["views"]), len(impact["sheets"])))
            self.update_status()
            target = DeleteLevelDialog(self, source, impact).show()
            if target is False:
                return
            self.confirm_delete(source, target, impact)

        self.status.Text = u"Asking Revit what goes with the level..."
        self.submit("delete preview", job, done)

    def confirm_delete(self, source, target, impact):
        name = self.model.level_by_id[source]["name"]
        lines = core.impact_lines(self.model, source, target, impact, limit=5)
        body = u"Are you sure you want to delete {0}?\n\n- {1}\n\nUndo in Revit reverses it as one step.".format(
            name, u"\n- ".join(lines))
        if not ui.ask(self.win, self.palette(), body, yes_text=u"Delete {0}".format(name),
                      title=u"Delete Level"):
            self.status.Text = u"{0} was not deleted.".format(name)
            return
        items = [{"id": i, "route": self.model.elements[i]["route"]} for i in impact["moving"]]
        params = list(self.model.param_cols)

        def job(uiapp):
            doc = self.active_doc(uiapp)
            api = rv.RevitAdapter(doc, self.ids, self.dlog)
            res = core.delete_level(api, items, source, target, self.show_progress, self.dlog)
            data = rv.read_project(doc, params, self.dlog)
            return {"res": res, "data": data}

        def done(out):
            if self.failed(out):
                return
            res = out["res"]
            rows = []
            if res["assign"] is not None:
                a = res["assign"]
                rows = self.result_rows(a["refused"], [], a["skipped"], a["moved"])
            for i in res["blocked"]:
                rows.append([to_text(i), u"", u"", name, u"Would be deleted",
                             u"Revit still takes it with the level"])
            self.debug_report(res["assign"] or core.new_result())
            if res["ok"]:
                target_name = self.model.level_by_id.get(target, {}).get("name", u"-") if target else u"-"
                summary = u"Deleted {0}: {1} element{2} moved to {3}, {4} item{5} went with the level.".format(
                    name, core.thousands(len(items)), u"" if len(items) == 1 else u"s", target_name,
                    core.thousands(len(res["deleted"])), u"" if len(res["deleted"]) == 1 else u"s")
                for i in impact["moving"]:
                    self.model.ticked.discard(i)
            else:
                summary = res["reason"]
            self.reload(out["data"])
            if target in self.model.level_by_id:
                self.model.expanded.add(core.level_key(target))
                self.render()
            self.status.Text = summary + DOT + self.status.Text
            self.flush_debug()
            if not res["ok"]:
                ResultsDialog(self, u"Delete Level", summary, rows).show()

        self.status.Text = u"Deleting {0}...".format(name)
        self.submit("delete level", job, done)

    # ---- assign ----------------------------------------------------------------
    @guarded
    def on_assign(self, sender, args):
        ids = self.chosen_ids()
        if not ids:
            return
        target = AssignDialog(self, ids).show()
        if target is None:
            return
        plan = core.plan_assign(self.model, ids, target)
        lv = self.model.level_by_id.get(target, {})
        if not plan["do"]:
            text = u"Nothing to change - "
            if plan["locked"] and not plan["already"]:
                text += u"none of them can take a new level."
            elif plan["locked"]:
                text += u"they are already on {0}, or cannot take a new level.".format(lv.get("name"))
            else:
                text += u"they are already on {0}.".format(lv.get("name"))
            self.status.Text = text
            if plan["locked"]:
                ResultsDialog(self, u"Assign Level", text, self.result_rows(
                    [], plan["locked"], [], [])).show()
            return
        if len(plan["do"]) > core.BIG_RUN:
            if not ui.ask(self.win, self.palette(),
                          u"This changes {0} elements. On a large workshared model it is worth "
                          u"syncing first. Carry on?".format(core.thousands(len(plan["do"]))),
                          yes_text=u"Assign"):
                return
        items = [{"id": i, "route": self.model.elements[i]["route"]} for i in plan["do"]]
        params = list(self.model.param_cols)
        locked = list(plan["locked"])
        self.dlog(u"assign {0} element(s) to {1} ({2}); {3} already there, {4} locked".format(
            len(items), lv.get("name"), target, len(plan["already"]), len(locked)))

        def job(uiapp):
            doc = self.active_doc(uiapp)
            api = rv.RevitAdapter(doc, self.ids, self.dlog)
            res = core.assign_levels(api, items, target, self.show_progress, self.dlog)
            data = rv.read_project(doc, params, self.dlog)
            return {"res": res, "data": data}

        def done(out):
            if self.failed(out):
                return
            self.after_assign(out["res"], out["data"], target, locked)

        self.status.Text = u"Assigning {0} element{1} to {2}...".format(
            core.thousands(len(items)), u"" if len(items) == 1 else u"s", lv.get("name"))
        self.submit("assign", job, done)

    def result_rows(self, refused, locked, skipped, moved):
        rows = []
        def add(i, outcome, why):
            info = self.model.elements.get(i, {})
            lv = self.model.level_by_id.get(info.get("level"), {})
            rows.append([to_text(i), info.get("category", u""), info.get("name", u""),
                         lv.get("name", u""), outcome, to_text(why)])
        for i, why in moved:
            add(i, u"Would move", u"{0}mm out of place - nothing was kept".format(core.fmt_mm(why)))
        for i, why in refused:
            add(i, u"Refused", why)
        for i, why in skipped:
            add(i, u"Not borrowed", why)
        for i, why in locked:
            add(i, u"Cannot change", why)
        return rows

    def after_assign(self, res, data, target, locked):
        rows = self.result_rows(res["refused"], locked, res["skipped"], res["moved"])
        summary = core.result_summary(res)
        if locked:
            summary += u" {0} could not take a new level.".format(len(locked))
        self.debug_report(res)
        for i in res["done"]:
            self.model.ticked.discard(i)
        self.reload(data)
        self.model.expanded.add(core.level_key(target))
        for i in res["done"]:
            info = self.model.elements.get(i)
            if info is not None:
                self.model.expanded.add(core.cat_key(info["level"], info.get("category")))
        self.render()
        self.status.Text = summary + DOT + self.status.Text
        self.flush_debug()
        if core.needs_a_look(res) or locked:
            ResultsDialog(self, u"Assign Level", summary, rows).show()

    def debug_report(self, res):
        if not self.debug:
            return
        rows = []
        for i in res["done"]:
            rows.append([i, u"done", u", ".join(res["compensated"].get(i, [])) or u"held by Revit"])
        for i, why in res["refused"]:
            rows.append([i, u"refused", why])
        for i, why in res["skipped"]:
            rows.append([i, u"not borrowed", why])
        for i, d in res["moved"]:
            rows.append([i, u"moved", core.fmt_mm(d) + u"mm"])
        self.dlog(u"\n" + core.debug_table(rows, [u"Element", u"Outcome", u"Detail"]))
        if res.get("errors"):
            self.dlog(u"errors: " + u"; ".join(res["errors"]))

    # ---- debug and errors -------------------------------------------------------
    def dlog(self, msg):
        if not self.debug:
            return
        self.debug_lines.append(to_text(msg))
        if len(self.debug_lines) > 4000:
            self.debug_lines = self.debug_lines[-3000:]

    def flush_debug(self):
        if not self.debug:
            return
        head = u"RevoBIM Level Manager v{0}\nModel: {1}\n\n".format(core.__version__, self.doc_title)
        write_text(core.DEBUG_NAME, head + u"\n".join(self.debug_lines))

    def report_error(self, where, text):
        write_text(core.ERROR_NAME, u"{0}\n\n{1}".format(where, text))
        self.dlog(u"error in {0}:\n{1}".format(where, text))
        self.flush_debug()
        try:
            self.status.Text = u"Something went wrong ({0}) - tick Debug and send the log.".format(where)
        except Exception:
            pass

    # ---- lifetime ------------------------------------------------------------
    def _restore_bounds(self):
        try:
            w = float(self.settings.get("width") or 0)
            h = float(self.settings.get("height") or 0)
            if w >= self.win.MinWidth:
                self.win.Width = w
            if h >= self.win.MinHeight:
                self.win.Height = h
            left = self.settings.get("left")
            top = self.settings.get("top")
            if left and top:
                lf, tp = float(left), float(top)
                if -50 < lf < 6000 and -50 < tp < 4000:
                    self.win.WindowStartupLocation = WindowStartupLocation.Manual
                    self.win.Left = lf
                    self.win.Top = tp
        except Exception:
            pass

    @guarded
    def on_rendered(self, sender, args):
        # the engine is alive: clear the note written before Show()
        remove_file(core.NOTE_NAME)

    @guarded
    def on_closing(self, sender, args):
        if self.busy and self.runner.running:
            args.Cancel = True
            self.status.Text = u"Still working - close when it finishes."
            return
        # never save the parked bar or the full-screen size as the window size
        left, top, width, height = self.chrome.true_bounds()
        self.settings.update({"left": to_text(int(left)), "top": to_text(int(top)),
                              "width": to_text(int(width)), "height": to_text(int(height)),
                              "theme": self.theme_mode, "debug": "1" if self.debug else "0"})
        self.save_params()

    @guarded
    def on_closed(self, sender, args):
        self.closed = True
        self.flush_debug()
        self.runner.on_busy = None
        try:
            AppDomain.CurrentDomain.SetData(window_key(), None)
        except Exception:
            pass
        try:
            _KEEP.remove(self)
        except ValueError:
            pass


# =========================================================================
# Value list popup
# =========================================================================

class ValuePopup(object):

    def __init__(self, owner, anchor, title, values, allowed, on_apply):
        self.on_apply = on_apply
        self.root = ui.load_xaml("ValueFilter.xaml")
        ui.themed(self.root, owner.palette())
        f = self.root.FindName
        f("ColTxt").Text = to_text(title)
        self.list = f("ValueList")
        self.find = f("FindBox")
        self.boxes = []
        for value in values:
            cb = CheckBox()
            cb.Content = to_text(value)
            cb.IsChecked = allowed is None or value in allowed
            cb.Margin = Thickness(0, 1, 0, 1)
            self.boxes.append(cb)
            self.list.Items.Add(cb)
        note = u"{0} values".format(len(values))
        if len(values) >= 3000:
            note = u"Showing the first 3000 values - type in the column's filter box to narrow."
        f("NoteTxt").Text = note
        self.find.TextChanged += self.on_find
        f("AllBtn").Click += self.on_all
        f("NoneBtn").Click += self.on_none
        f("OkBtn").Click += self.on_ok
        f("CancelBtn").Click += self.on_cancel
        self.popup = Popup()
        self.popup.Child = self.root
        self.popup.PlacementTarget = anchor
        self.popup.Placement = PlacementMode.Bottom
        self.popup.StaysOpen = False
        self.popup.AllowsTransparency = True
        self.popup.IsOpen = True
        try:
            self.find.Focus()
        except Exception:
            pass

    def on_find(self, sender, args):
        terms = core.words(self.find.Text)
        for cb in self.boxes:
            text = to_text(cb.Content).lower()
            ok = all([t in text for t in terms])
            cb.Visibility = Visibility.Visible if ok else Visibility.Collapsed

    def _set(self, value):
        for cb in self.boxes:
            if cb.Visibility == Visibility.Visible:
                cb.IsChecked = value

    def on_all(self, sender, args):
        self._set(True)

    def on_none(self, sender, args):
        self._set(False)

    def on_ok(self, sender, args):
        ticked = set([to_text(cb.Content) for cb in self.boxes if cb.IsChecked])
        self.popup.IsOpen = False
        if len(ticked) == len(self.boxes):
            self.on_apply(None)          # everything ticked: no filter
        else:
            self.on_apply(ticked)        # nothing ticked shows nothing

    def on_cancel(self, sender, args):
        self.popup.IsOpen = False


# =========================================================================
# Assign Level dialog
# =========================================================================

class AssignDialog(object):

    def __init__(self, owner, ids):
        self.owner = owner
        self.model = owner.model
        self.ids = ids
        self.target = None
        self.win = ui.load_xaml("AssignLevel.xaml")
        ui.dialog_chrome(self.win, owner.palette())
        ui.open_parent(owner.win)
        self.win.Owner = owner.win
        f = self.win.FindName
        self.list = f("LevelList")
        self.preview = f("PreviewTxt")
        self.ok = f("OkBtn")
        ui.line_icon(self.ok, "assign", u"Assign")
        counts = {}
        for i in ids:
            info = self.model.elements.get(i)
            if info is not None:
                counts[info["level"]] = counts.get(info["level"], 0) + 1
        on = []
        for lv in self.model.levels:
            if counts.get(lv["id"]):
                on.append(u"{0} ({1})".format(lv["name"], counts[lv["id"]]))
        f("SelectionTxt").Text = u"{0} element{1} chosen, on {2}.".format(
            core.thousands(len(ids)), u"" if len(ids) == 1 else u"s", u", ".join(on) or u"-")
        self.items = []
        for lv in self.model.levels:
            item = ListBoxItem()
            grid = Grid()
            for weight in (3.0, 1.2, 1.4):
                cd = ColumnDefinition()
                cd.Width = GridLength(weight, GridUnitType.Star)
                grid.ColumnDefinitions.Add(cd)
            name = text_block(lv["name"], bold=True)
            elev = text_block(core.fmt_mm(lv.get("disp")) + u" mm", muted=True)
            elev.HorizontalAlignment = HorizontalAlignment.Right
            here = text_block(u"{0} chosen here".format(counts[lv["id"]]) if counts.get(lv["id"]) else u"", muted=True)
            here.HorizontalAlignment = HorizontalAlignment.Right
            Grid.SetColumn(elev, 1)
            Grid.SetColumn(here, 2)
            grid.Children.Add(name)
            grid.Children.Add(elev)
            grid.Children.Add(here)
            item.Content = grid
            item.Tag = lv["id"]
            self.items.append((item, lv))
            self.list.Items.Add(item)
        f("FilterBox").TextChanged += self.on_filter
        self.list.SelectionChanged += self.on_pick
        self.list.MouseDoubleClick += self.on_double
        self.ok.Click += self.on_ok
        f("CancelBtn").Click += self.on_cancel

    def on_filter(self, sender, args):
        terms = core.words(sender.Text)
        for item, lv in self.items:
            text = to_text(lv["name"]).lower()
            ok = all([t in text for t in terms])
            item.Visibility = Visibility.Visible if ok else Visibility.Collapsed

    def picked(self):
        item = self.list.SelectedItem
        return item.Tag if item is not None else None

    def on_pick(self, sender, args):
        target = self.picked()
        if target is None:
            self.ok.IsEnabled = False
            self.preview.Text = u"Pick a level."
            return
        plan = core.plan_assign(self.model, self.ids, target)
        self.preview.Text = core.plan_summary(self.model, plan, target)
        self.ok.IsEnabled = len(plan["do"]) > 0
        ui.set_label(self.ok, u"Assign to {0}".format(self.model.level_by_id[target]["name"]))

    def on_double(self, sender, args):
        if self.ok.IsEnabled:
            self.on_ok(sender, args)

    def on_ok(self, sender, args):
        self.target = self.picked()
        self.win.Close()

    def on_cancel(self, sender, args):
        self.target = None
        self.win.Close()

    def show(self):
        self.win.ShowDialog()
        return self.target


# =========================================================================
# Delete Level dialog
# =========================================================================

class DeleteLevelDialog(object):
    """Pick the level the elements go to and see Revit's own list of what
    goes with the level. show() returns the target level id, None when the
    level has nothing to move (no target needed), or False for cancel."""

    def __init__(self, owner, source, impact):
        self.owner = owner
        self.model = owner.model
        self.source = source
        self.impact = impact
        self.result = False
        self.win = ui.load_xaml("DeleteLevel.xaml")
        ui.dialog_chrome(self.win, owner.palette())
        ui.open_parent(owner.win)
        self.win.Owner = owner.win
        f = self.win.FindName
        src = self.model.level_by_id[source]
        f("QuestionTxt").Text = u"Delete {0} ({1} mm)?".format(src["name"], core.fmt_mm(src.get("disp")))
        self.list = f("LevelList")
        self.panel = f("ImpactPanel")
        self.ok = f("OkBtn")
        ui.line_icon(self.ok, "delete", u"Delete {0}".format(src["name"]))
        self.items = []
        for lv in self.model.levels:
            if lv["id"] == source:
                continue
            item = ListBoxItem()
            grid = Grid()
            for weight in (3.0, 1.2):
                cd = ColumnDefinition()
                cd.Width = GridLength(weight, GridUnitType.Star)
                grid.ColumnDefinitions.Add(cd)
            name = text_block(lv["name"], bold=True)
            elev = text_block(core.fmt_mm(lv.get("disp")) + u" mm", muted=True)
            elev.HorizontalAlignment = HorizontalAlignment.Right
            Grid.SetColumn(elev, 1)
            grid.Children.Add(name)
            grid.Children.Add(elev)
            item.Content = grid
            item.Tag = lv["id"]
            self.items.append((item, lv))
            self.list.Items.Add(item)
        if impact["blocked"]:
            block = f("BlockTxt")
            block.Text = (u"The active view, {0}, is on this level and Revit cannot delete the view "
                          u"you are in. Open another view, then try again.").format(impact["active_name"])
            block.Visibility = Visibility.Visible
        f("FilterBox").TextChanged += self.on_filter
        self.list.SelectionChanged += self.on_pick
        self.ok.Click += self.on_ok
        f("CancelBtn").Click += self.on_cancel
        self.show_impact()

    def picked(self):
        item = self.list.SelectedItem
        return item.Tag if item is not None else None

    def show_impact(self):
        target = self.picked()
        self.panel.Children.Clear()
        for line in core.impact_lines(self.model, self.source, target, self.impact):
            tb = TextBlock()
            tb.Text = u"\u2022  " + line
            tb.TextWrapping = TextWrapping.Wrap
            tb.Margin = Thickness(0, 0, 0, 3)
            if u"DELETED" in line:
                tb.SetResourceReference(TextBlock.ForegroundProperty, "Red")
            else:
                tb.SetResourceReference(TextBlock.ForegroundProperty, "Text")
            self.panel.Children.Add(tb)
        needs_target = len(self.impact["moving"]) > 0
        self.ok.IsEnabled = (not self.impact["blocked"]) and (target is not None or not needs_target)

    def on_filter(self, sender, args):
        terms = core.words(sender.Text)
        for item, lv in self.items:
            text = to_text(lv["name"]).lower()
            item.Visibility = Visibility.Visible if all([t in text for t in terms]) else Visibility.Collapsed

    def on_pick(self, sender, args):
        self.show_impact()

    def on_ok(self, sender, args):
        self.result = self.picked()
        self.win.Close()

    def on_cancel(self, sender, args):
        self.result = False
        self.win.Close()

    def show(self):
        self.win.ShowDialog()
        return self.result


# =========================================================================
# Parameter column picker
# =========================================================================

class ParamDialog(object):

    def __init__(self, owner, names, current):
        self.result = None
        self.current = list(current)
        self.win = ui.load_xaml("AddParameter.xaml")
        ui.dialog_chrome(self.win, owner.palette())
        ui.open_parent(owner.win)
        self.win.Owner = owner.win
        f = self.win.FindName
        self.list = f("ParamList")
        self.count = f("CountTxt")
        self.boxes = []
        known = set([n for n, k in names])
        rows = list(names) + [(n, u"not found in the sample") for n in current if n not in known]
        for name, kind in rows:
            cb = CheckBox()
            panel = StackPanel()
            panel.Orientation = Orientation.Horizontal
            panel.Children.Add(text_block(name))
            k = text_block(u"   " + to_text(kind), muted=True)
            panel.Children.Add(k)
            cb.Content = panel
            cb.Tag = name
            cb.IsChecked = name in current
            cb.Margin = Thickness(0, 2, 0, 2)
            cb.Click += self.on_tick
            self.boxes.append(cb)
            self.list.Items.Add(cb)
        f("FilterBox").TextChanged += self.on_filter
        f("OkBtn").Click += self.on_ok
        f("CancelBtn").Click += self.on_cancel
        self.on_tick(None, None)

    def on_filter(self, sender, args):
        terms = core.words(sender.Text)
        for cb in self.boxes:
            text = to_text(cb.Tag).lower()
            ok = all([t in text for t in terms])
            cb.Visibility = Visibility.Visible if ok else Visibility.Collapsed

    def ticked(self):
        return [to_text(cb.Tag) for cb in self.boxes if cb.IsChecked]

    def on_tick(self, sender, args):
        self.count.Text = u"{0} ticked".format(len(self.ticked()))

    def on_ok(self, sender, args):
        ticked = self.ticked()
        keep = [p for p in self.current if p in ticked]
        add = sorted([p for p in ticked if p not in keep], key=core.natural_key)
        self.result = keep + add
        self.win.Close()

    def on_cancel(self, sender, args):
        self.result = None
        self.win.Close()

    def show(self):
        self.win.ShowDialog()
        return self.result


# =========================================================================
# Results
# =========================================================================

class ResultsDialog(object):

    HEADINGS = [u"Element ID", u"Category", u"Element", u"Level", u"Outcome", u"Reason"]

    def __init__(self, owner, title, summary, rows):
        self.owner = owner
        self.rows = rows
        self.win = ui.load_xaml("Results.xaml")
        ui.dialog_chrome(self.win, owner.palette())
        ui.open_parent(owner.win)
        self.win.Owner = owner.win
        f = self.win.FindName
        f("TitleTxt").Text = to_text(title)
        f("SummaryTxt").Text = to_text(summary)
        self.grid = f("Table")
        table = DataTable("results")
        for i in range(len(self.HEADINGS)):
            table.Columns.Add(u"c{0}".format(i))
        for row in rows:
            dr = table.NewRow()
            for i, value in enumerate(row):
                dr[u"c{0}".format(i)] = to_text(value)
            table.Rows.Add(dr)
        widths = [0.7, 1.0, 2.0, 1.0, 0.9, 3.0]
        for i, heading in enumerate(self.HEADINGS):
            col = DataGridTextColumn()
            col.Header = heading
            col.Binding = Binding(u"c{0}".format(i))
            col.Width = DataGridLength(widths[i], DataGridLengthUnitType.Star)
            style = self.win.TryFindResource("CellText")
            if style is not None:
                col.ElementStyle = style
            self.grid.Columns.Add(col)
        self.grid.SetResourceReference(DataGrid.RowStyleProperty, "LvmRow")
        self.grid.ItemsSource = table.DefaultView
        f("OkBtn").Click += self.on_close
        f("SelectBtn").Click += self.on_select
        f("CopyBtn").Click += self.on_copy

    def picked_ids(self):
        out = []
        items = list(self.grid.SelectedItems) or list(self.grid.Items)
        for item in items:
            try:
                out.append(int(to_text(item["c0"])))
            except Exception:
                continue
        return out

    def on_select(self, sender, args):
        # modeless, so the window can stay open (or shrunk) while you look
        self.owner.select_ids(self.picked_ids(), show=False)

    def on_copy(self, sender, args):
        lines = [u"\t".join(self.HEADINGS)]
        for row in self.rows:
            lines.append(u"\t".join([to_text(v) for v in row]))
        try:
            Clipboard.SetText(u"\r\n".join(lines))
        except Exception:
            pass

    def on_close(self, sender, args):
        self.win.Close()

    def show(self):
        # modeless: Revit stays usable, and Select in Revit works with it open
        self.win.Show()


# =========================================================================
# Launch
# =========================================================================

def window_key():
    return u"{0}.window.{1}".format(core.APP_KEY, core.__version__)


def _task(text, title=u"RevoBIM Level Manager"):
    try:
        TaskDialog.Show(title, text)
    except Exception:
        pass


def launch(uiapp):
    existing = AppDomain.CurrentDomain.GetData(window_key())
    if existing is not None:
        try:
            if not existing.closed and existing.win.IsVisible:
                existing.win.Activate()
                return existing
        except Exception:
            pass
    uidoc = uiapp.ActiveUIDocument
    if uidoc is None:
        _task(u"Open a project first.")
        return None
    doc = uidoc.Document
    try:
        if doc.IsFamilyDocument:
            _task(u"Level Manager works on projects, not families.")
            return None
    except Exception:
        pass

    settings = core.load_settings_file()
    modal = False
    note = read_file_text(core.NOTE_NAME)
    if note.strip() == core.__version__:
        try:
            from Autodesk.Revit.UI import TaskDialogCommonButtons, TaskDialogResult
            buttons = TaskDialogCommonButtons.Yes | TaskDialogCommonButtons.No
            answer = TaskDialog.Show(
                u"RevoBIM Level Manager",
                u"Last time the Level Manager window may not have responded to clicks.\n\n"
                u"Open it modal this time? (Revit waits while it is open, but every button works.)",
                buttons)
            modal = answer == TaskDialogResult.Yes
        except Exception:
            modal = False
        remove_file(core.NOTE_NAME)

    start_ids = rv.current_selection(uidoc)
    data = rv.read_project(doc, core.split_params(settings.get("params", u"")))

    runner = ops.Runner()
    runner.uiapp = uiapp
    if modal:
        runner.direct = True
        event = None
    else:
        event = ExternalEvent.Create(runner)
        runner.event = event

    window = LevelManagerWindow(uiapp, runner, data, settings, start_ids)
    _KEEP.append(window)
    window.keep = (runner, event)
    AppDomain.CurrentDomain.SetData(window_key(), window)

    if modal:
        window.win.ShowDialog()
    else:
        ui.set_owner(window.win, uiapp.MainWindowHandle)
        write_text(core.NOTE_NAME, core.__version__)      # cleared by ContentRendered
        window.win.Show()
    return window
