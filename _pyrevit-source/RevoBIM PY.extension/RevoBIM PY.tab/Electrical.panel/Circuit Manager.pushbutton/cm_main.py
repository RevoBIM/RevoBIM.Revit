# -*- coding: utf-8 -*-
"""Circuit Manager - the main window.

Every electrical circuit in the project in one Excel-style table:
- a keyword box and an Excel tick list on every column heading
- parameter columns added from anything electrical circuits carry
- Path Mode: select circuits (Ctrl / Shift), click any selected circuit's
  Path Mode and pick from the dropdown - it is staged on every selected one
- Path Offset: type, or Ctrl+C / Ctrl+V like Excel - one copied value
  fills every selected cell, a block pastes from the top-left
- nothing is written until Apply; one Ctrl+Z per change

Modeless: Revit stays usable, writes go through an ExternalEvent.
Table rules follow the RevoBIM table reference - edits keyed by
(element, column), filter and sort decisions held in hidden columns so
nothing moves under the cursor, F5 catches the view up.
"""
import cm_clr  # noqa: F401
import clr

from System import Array, Object, String, TimeSpan
from System.Data import DataTable
from System.Windows import (Thickness, Visibility, HorizontalAlignment,
                            VerticalAlignment, Setter, Style, DataTrigger,
                            DynamicResourceExtension, FontWeights,
                            Clipboard, CornerRadius, TextTrimming)
from System.Windows.Controls import (DataGrid, DataGridCell,
                                     DataGridTextColumn,
                                     DataGridTemplateColumn, DataGridLength,
                                     DataGridLengthUnitType,
                                     DataGridCellInfo, DataGridEditAction,
                                     TextBlock, TextBox, Button, Border,
                                     StackPanel, DockPanel, Dock, Orientation,
                                     ContextMenu, MenuItem, ListBox,
                                     CheckBox, Separator)
from System.Windows.Controls.Primitives import Popup, PlacementMode
from System.Windows.Data import Binding, BindingMode, UpdateSourceTrigger
from System.Windows.Input import Mouse, Cursors
from System.Windows.Markup import XamlReader
from System.Windows.Media import VisualTreeHelper, Geometry, Brushes
from System.Windows.Shapes import Path
from System.Windows.Threading import DispatcherTimer

import cm_logic
import cm_theme
import cm_revit
import cm_dialogs
from cm_chrome import (ThemedWindow, SETTINGS, log, owned_to_revit, later,
                       mods)
from cm_logic import to_text
from cm_version import __version__

STATE_STYLES = [
    # state value, background key, foreground key, bold
    ('staged', 'StagedBg', 'StagedText', False),
    ('bad', 'BadBg', 'BadText', True),
    ('copy', 'CopyBg', None, False),
    ('ro', 'ReadOnlyBg', None, False),
]

CARET = u'M 0,0 L 8,0 L 4,5 Z'


class CircuitManagerWindow(ThemedWindow):
    LAYOUT = 'CircuitManager.xaml'

    def __init__(self, uiapp, modal=False):
        ThemedWindow.__init__(self)
        self.uiapp = uiapp
        self.doc = uiapp.ActiveUIDocument.Document
        self.modal = modal
        self.runner = cm_revit.Runner(uiapp, modal=modal, log=log)
        self.stage = cm_logic.Stage()
        self.rows = []
        self.by_eid = {}
        self.dt_rows = []
        self.cols = []
        self.col_name = {}
        self.key_of_name = {}
        self.heads = {}
        self.text_filters = {}
        self.tick_filters = {}
        self.bad = {}
        self.copy_marks = set()
        self.selected = set()
        self.hl_rows = set()
        self.sort_key = SETTINGS.get('sort_key') or 'panel'
        self.sort_desc = SETTINGS.get('sort_desc') == '1'
        self.editing = False
        self.alive = False
        self.armed = False
        self.force_close = False
        self._sel_pending = False
        self.table = None
        self.view = None
        self.dressed = []
        self.param_keys = [cm_revit.PARAM_PREFIX + n for n in
                           cm_logic.split_columns(SETTINGS.get('columns'))]

        self.dg = self.find('dg')
        self.status = self.find('status_text')
        self.filter_timer = DispatcherTimer()
        self.filter_timer.Interval = TimeSpan.FromMilliseconds(220)
        self.filter_timer.Tick += self._on_filter_tick
        self.watchdog = DispatcherTimer()
        self.watchdog.Interval = TimeSpan.FromSeconds(20)
        self.watchdog.Tick += self._on_watchdog
        self.tick_popup = self._build_tick_popup()

        self.find('add_col_btn').Click += self._on_add_columns
        self.find('reset_btn').Click += lambda s, a: self.reset_filters()
        self.find('refresh_btn').Click += lambda s, a: self.reload()
        self.find('apply_btn').Click += lambda s, a: self.apply()
        self.find('undo_btn').Click += lambda s, a: self.undo()
        self.find('clear_btn').Click += lambda s, a: self.clear_staged()
        dbg = self.find('debug_chk')
        dbg.IsChecked = SETTINGS.get('debug') == '1'
        dbg.Checked += lambda s, a: SETTINGS.set('debug', '1')
        dbg.Unchecked += lambda s, a: SETTINGS.set('debug', '0')

        self.dg.Sorting += self._on_sorting
        self.dg.SelectedCellsChanged += self._on_selection_changed
        self.dg.PreviewMouseLeftButtonDown += self._on_grid_mouse_down
        self.dg.PreviewKeyDown += self._on_grid_key
        self.dg.BeginningEdit += self._on_beginning_edit
        self.dg.CellEditEnding += self._on_cell_edit_ending
        self.win.Closing += self._on_closing
        self.win.PreviewMouseMove += self._on_first_move

        self.read_model()
        self.build_table()

    # ==================================================================
    # Reading
    # ==================================================================
    def read_model(self):
        Mouse.OverrideCursor = Cursors.Wait
        try:
            self.rows = cm_revit.read_rows(self.doc, self.param_keys)
        finally:
            Mouse.OverrideCursor = None
        self.by_eid = dict((r.eid, i) for i, r in enumerate(self.rows))
        live = set(self.by_eid.keys())
        gone = [k for k in self.stage.edits if k[0] not in live]
        self.stage.clear(gone)
        for k in list(self.bad.keys()):
            if k[0] not in live:
                del self.bad[k]
        log(u'read {0} circuits, {1} parameter columns'.format(
            len(self.rows), len(self.param_keys)))

    def reload(self):
        keep = set(self.rows[i].eid for i in self.selected
                   if i < len(self.rows))
        self.read_model()
        self.build_table(reselect=keep)
        self.set_status(u'Read {0} circuits from the model. Staged changes '
                        u'kept.'.format(len(self.rows)))

    # ==================================================================
    # Columns and table
    # ==================================================================
    def column_defs(self):
        out = []
        for key, head, kind, editable in cm_revit.FIXED:
            out.append((key, head))
        for key in self.param_keys:
            out.append((key, key[len(cm_revit.PARAM_PREFIX):]))
        return out

    def display(self, i, key):
        row = self.rows[i]
        staged = self.stage.get(row.eid, key)
        if staged is not None:
            return staged
        return row.values.get(key, u'')

    def cell_state(self, i, key):
        row = self.rows[i]
        k = (row.eid, key)
        if self.stage.has(row.eid, key):
            return 'staged'
        if k in self.bad:
            return 'bad'
        if k in self.copy_marks:
            return 'copy'
        if self.col_editable(key) and not row.editable.get(key, False):
            return 'ro'
        return ''

    def col_editable(self, key):
        for r in self.rows:
            if r.editable.get(key, False):
                return True
        return False

    def build_table(self, reselect=None):
        defs = self.column_defs()
        self.cols = [k for k, h in defs]
        self.col_name = {}
        self.key_of_name = {}
        table = DataTable('circuits')
        for c in ('ridx', 'vis', 'gkey', 'hl'):
            table.Columns.Add(c, clr.GetClrType(String))
        for i, (key, head) in enumerate(defs):
            name = 'f{0}'.format(i)
            self.col_name[key] = name
            self.key_of_name[name] = key
            table.Columns.Add(name, clr.GetClrType(String))
            table.Columns.Add(name + '_s', clr.GetClrType(String))
        table.BeginLoadData()
        self.dt_rows = []
        for i in range(len(self.rows)):
            values = [to_text(i), u'1', u'', u'0']
            for key in self.cols:
                values.append(self.display(i, key))
                values.append(self.cell_state(i, key))
            self.dt_rows.append(table.Rows.Add(Array[Object](values)))
        table.EndLoadData()
        self.table = table
        self.dg.ItemsSource = None
        self.dg.Columns.Clear()
        self.heads = {}
        self.dressed = []
        for key, head in defs:
            self.dg.Columns.Add(self._make_column(key, head))
        self.view = table.DefaultView
        self.apply_view()
        self.view.RowFilter = "[vis] = '1'"
        self.view.Sort = '[gkey] ASC'
        self.dg.ItemsSource = self.view
        self.selected = set()
        self.hl_rows = set()
        if reselect:
            self._reselect(reselect)
        self.refresh_counts()

    def _reselect(self, eids):
        try:
            for item in self.view:
                i = int(item.Row['ridx'])
                if self.rows[i].eid in eids:
                    for col in self.dg.Columns:
                        self.dg.SelectedCells.Add(DataGridCellInfo(item, col))
        except Exception:
            log(u'reselect failed')

    def _make_column(self, key, head):
        name = self.col_name[key]
        editable = self.col_editable(key)
        if key == 'pm':
            col = DataGridTemplateColumn()
            col.CellTemplate = XamlReader.Parse(
                u'<DataTemplate xmlns="http://schemas.microsoft.com/winfx/'
                u'2006/xaml/presentation"><DockPanel Background="Transparent">'
                u'<Path DockPanel.Dock="Right" Data="{0}" Margin="6,0,2,0" '
                u'VerticalAlignment="Center" Fill="{{DynamicResource Muted}}"/>'
                u'<TextBlock Text="{{Binding {1}}}" VerticalAlignment="Center" '
                u'TextTrimming="CharacterEllipsis"/></DockPanel></DataTemplate>'
                .format(CARET, name))
            col.SortMemberPath = name
            col.IsReadOnly = True
        else:
            col = DataGridTextColumn()
            b = Binding(name)
            # NOT OneWay: DataGridBoundColumn coerces IsReadOnly to True for a
            # OneWay / OneTime binding, silently, which made Path Offset
            # uneditable in 1.0.0. TwoWay + Explicit is editable but never
            # pushes the typed text into the table - CellEditEnding stages
            # it, validated, and the stage writes what the cell shows.
            b.Mode = BindingMode.TwoWay
            b.UpdateSourceTrigger = UpdateSourceTrigger.Explicit
            col.Binding = b
            col.SortMemberPath = name
            col.IsReadOnly = not editable
            if editable:
                col.EditingElementStyle = self.win.FindResource('CmEditBox')
        col.CanUserSort = True
        col.MinWidth = 120 if key in ('pm', 'po', 'load') else 90
        col.Width = DataGridLength(1.4 if key in ('load', 'pm') else 1.0,
                                   DataGridLengthUnitType.Star)
        col.CellStyle = self._cell_style(name, editable)
        col.Header = self._make_header(key, head, editable)
        return col

    def _cell_style(self, name, editable):
        style = Style(clr.GetClrType(DataGridCell),
                      self.win.FindResource('CmCell'))
        if not editable:
            style.Setters.Add(Setter(DataGridCell.ForegroundProperty,
                                     DynamicResourceExtension('Muted')))
        for value, bg, fg, bold in STATE_STYLES:
            trig = DataTrigger()
            trig.Binding = Binding(name + '_s')
            trig.Value = value
            trig.Setters.Add(Setter(DataGridCell.BackgroundProperty,
                                    DynamicResourceExtension(bg)))
            if fg:
                trig.Setters.Add(Setter(DataGridCell.ForegroundProperty,
                                        DynamicResourceExtension(fg)))
            if bold:
                trig.Setters.Add(Setter(DataGridCell.FontWeightProperty,
                                        FontWeights.Bold))
            style.Triggers.Add(trig)
        return style

    # ------------------------------------------------------------------
    def _make_header(self, key, head, editable):
        outer = Border()
        outer.BorderThickness = Thickness(1)
        outer.CornerRadius = CornerRadius(3)
        outer.Padding = Thickness(2)
        outer.Background = Brushes.Transparent
        stack = StackPanel()
        top = DockPanel()
        caret = Button()
        caret.SetResourceReference(Button.StyleProperty, 'ChromeBtn')
        caret.Width = 20
        caret.Height = 18
        caret.ToolTip = u'Pick values to show'
        glyph = Path()
        glyph.Data = Geometry.Parse(CARET)
        glyph.SetResourceReference(Path.FillProperty, 'Muted')
        caret.Content = glyph
        DockPanel.SetDock(caret, Dock.Right)
        caret.Click += self._make_caret_click(key)
        top.Children.Add(caret)
        label = TextBlock()
        label.Text = head
        label.FontWeight = FontWeights.SemiBold
        label.TextTrimming = TextTrimming.CharacterEllipsis
        label.VerticalAlignment = VerticalAlignment.Center
        label.SetResourceReference(TextBlock.ForegroundProperty,
                                   'Blue' if editable else 'Text')
        label.ToolTip = head + (u' - editable' if editable else u' - read only')
        top.Children.Add(label)
        stack.Children.Add(top)
        box = TextBox()
        box.Tag = u'filter...'
        box.Height = 22
        box.FontSize = 11
        box.Margin = Thickness(0, 3, 0, 0)
        box.Text = self.text_filters.get(key, u'')
        box.TextChanged += self._make_filter_changed(key)
        stack.Children.Add(box)
        outer.Child = stack
        menu = ContextMenu()
        for text, fn in ((u'Sort A to Z', lambda: self.sort_by(key, False)),
                         (u'Sort Z to A', lambda: self.sort_by(key, True)),
                         (u'Clear this filter', lambda: self.clear_filter(key))):
            mi = MenuItem()
            mi.Header = text
            mi.Click += self._wrap(fn)
            menu.Items.Add(mi)
        if key.startswith(cm_revit.PARAM_PREFIX):
            menu.Items.Add(Separator())
            mi = MenuItem()
            mi.Header = u'Remove this column'
            mi.Click += self._wrap(lambda: self.remove_column(key))
            menu.Items.Add(mi)
        self.dress(menu)
        outer.ContextMenu = menu
        self.heads[key] = {'border': outer, 'label': label, 'caret': glyph,
                           'box': box, 'head': head}
        self._paint_head(key)
        return outer

    def _wrap(self, fn):
        def handler(sender, args):
            try:
                fn()
            except Exception:
                import traceback
                log(traceback.format_exc())
                self.set_status(u'That did not work - see the debug log.')
        return handler

    def _paint_head(self, key):
        h = self.heads.get(key)
        if h is None:
            return
        sorted_here = key == self.sort_key
        h['border'].SetResourceReference(
            Border.BorderBrushProperty,
            'Orange' if sorted_here else 'HeadingBg')
        arrow = u''
        if sorted_here:
            arrow = u'  ▼' if self.sort_desc else u'  ▲'
        h['label'].Text = h['head'] + arrow
        filtered = cm_logic.is_filtered(key, self.text_filters,
                                        self.tick_filters)
        h['caret'].SetResourceReference(Path.FillProperty,
                                        'Orange' if filtered else 'Muted')

    def dress(self, menu):
        """A context menu is not in the window's tree: give it the theme and
        keep it so a palette swap repaints it too."""
        cm_theme.dress(menu, self.resolved)
        self.dressed.append(menu)

    def on_repainted(self):
        for key in self.heads:
            self._paint_head(key)
        for menu in list(self.dressed):
            try:
                cm_theme.apply_palette(menu, self.resolved)
            except Exception:
                pass

    # ==================================================================
    # Filter, sort, F5
    # ==================================================================
    def row_values(self, i):
        return dict((k, self.display(i, k)) for k in self.cols)

    def apply_view(self):
        """Take the filter and sort decisions again - F5."""
        values = [self.row_values(i) for i in range(len(self.rows))]
        for i, v in enumerate(values):
            vis = u'1' if cm_logic.row_visible(v, self.text_filters,
                                               self.tick_filters) else u'0'
            self._set(self.dt_rows[i], 'vis', vis)
        key = self.sort_key if self.sort_key in self.cols else 'panel'
        order = cm_logic.sort_order(values, 'num', False)
        if key != 'num':
            # stable: circuit number stays the second level, so a panel
            # reads 1, 2, 3 under its heading
            order.sort(key=lambda j: cm_logic.natural_key(
                values[j].get(key, u'')), reverse=self.sort_desc)
        elif self.sort_desc:
            order.reverse()
        for place, i in enumerate(order):
            self._set(self.dt_rows[i], 'gkey', u'{0:08d}'.format(place))
        for k in self.heads:
            self._paint_head(k)
        self.refresh_counts()

    def _set(self, dr, col, value):
        if to_text(dr[col]) == value:
            return False
        dr[col] = value
        return True

    def _make_filter_changed(self, key):
        def handler(sender, args):
            self.text_filters[key] = sender.Text
            self.filter_timer.Stop()
            self.filter_timer.Start()
        return handler

    def _on_filter_tick(self, sender, args):
        self.filter_timer.Stop()
        self.apply_view()

    def clear_filter(self, key):
        self.text_filters.pop(key, None)
        self.tick_filters.pop(key, None)
        h = self.heads.get(key)
        if h is not None:
            h['box'].Text = u''
        self.apply_view()

    def reset_filters(self):
        self.tick_filters = {}
        for key in list(self.heads.keys()):
            self.heads[key]['box'].Text = u''
        self.text_filters = {}
        self.apply_view()
        self.set_status(u'Filters cleared.')

    def sort_by(self, key, desc):
        self.sort_key = key
        self.sort_desc = desc
        SETTINGS.set('sort_key', key, save=False)
        SETTINGS.set('sort_desc', '1' if desc else '0')
        self.apply_view()

    def _on_sorting(self, sender, args):
        args.Handled = True
        key = self.key_of_name.get(args.Column.SortMemberPath)
        if key is None:
            return
        desc = (not self.sort_desc) if key == self.sort_key else False
        self.sort_by(key, desc)

    # ------------------------------------------------------------------
    # Excel tick list
    # ------------------------------------------------------------------
    def _build_tick_popup(self):
        pop = Popup()
        pop.StaysOpen = False
        pop.AllowsTransparency = True
        pop.Placement = PlacementMode.Bottom
        border = Border()
        border.SetResourceReference(Border.BackgroundProperty, 'FieldBg')
        border.SetResourceReference(Border.BorderBrushProperty, 'Edge')
        border.BorderThickness = Thickness(1)
        border.Padding = Thickness(8)
        border.Width = 280
        stack = StackPanel()
        search = TextBox()
        search.Tag = u'Search values...'
        search.Height = 26
        search.TextChanged += lambda s, a: self._tick_search()
        stack.Children.Add(search)
        row = DockPanel()
        row.Margin = Thickness(0, 6, 0, 6)
        b_all = Button()
        b_all.Content = u'Select all'
        b_all.Click += lambda s, a: self._tick_set(True)
        b_none = Button()
        b_none.Content = u'Untick all'
        b_none.Margin = Thickness(6, 0, 0, 0)
        b_none.Click += lambda s, a: self._tick_set(False)
        count = TextBlock()
        count.SetResourceReference(TextBlock.ForegroundProperty, 'Muted')
        count.VerticalAlignment = VerticalAlignment.Center
        count.HorizontalAlignment = HorizontalAlignment.Right
        DockPanel.SetDock(b_all, Dock.Left)
        DockPanel.SetDock(b_none, Dock.Left)
        row.Children.Add(b_all)
        row.Children.Add(b_none)
        row.Children.Add(count)
        stack.Children.Add(row)
        lst = ListBox()
        lst.MaxHeight = 300
        lst.MinHeight = 80
        stack.Children.Add(lst)
        foot = StackPanel()
        foot.Orientation = Orientation.Horizontal
        foot.HorizontalAlignment = HorizontalAlignment.Right
        foot.Margin = Thickness(0, 8, 0, 0)
        cancel = Button()
        cancel.Content = u'Cancel'
        cancel.Click += lambda s, a: self._tick_close(False)
        ok = Button()
        ok.Content = u'OK'
        ok.Margin = Thickness(6, 0, 0, 0)
        ok.SetResourceReference(Button.StyleProperty, 'GreenBtn')
        ok.Click += lambda s, a: self._tick_close(True)
        foot.Children.Add(cancel)
        foot.Children.Add(ok)
        stack.Children.Add(foot)
        border.Child = stack
        pop.Child = border
        # in the window's tree so it inherits the theme and palette
        self.find('root_grid').Children.Add(pop)
        self.tick = {'popup': pop, 'search': search, 'list': lst,
                     'count': count, 'key': None, 'items': []}
        return pop

    def _make_caret_click(self, key):
        def handler(sender, args):
            try:
                self.open_tick_list(key, sender)
            except Exception:
                import traceback
                log(traceback.format_exc())
        return handler

    def open_tick_list(self, key, anchor):
        t = self.tick
        t['key'] = key
        values = cm_logic.list_values(
            [self.row_values(i) for i in range(len(self.rows))], key,
            self.text_filters, self.tick_filters)
        allowed = self.tick_filters.get(key)
        t['list'].Items.Clear()
        t['items'] = []
        for v in values:
            cb = CheckBox()
            cb.Content = v if v != u'' else u'(blank)'
            cb.IsChecked = allowed is None or v in allowed
            cb.Checked += lambda s, a: self._tick_count()
            cb.Unchecked += lambda s, a: self._tick_count()
            t['list'].Items.Add(cb)
            t['items'].append((v, cb))
        t['search'].Text = u''
        t['popup'].PlacementTarget = anchor
        t['popup'].IsOpen = True
        self._tick_count()

    def _tick_search(self):
        term = self.tick['search'].Text
        for v, cb in self.tick['items']:
            cb.Visibility = Visibility.Visible if cm_logic.matches_text(
                v, term) else Visibility.Collapsed

    def _tick_set(self, value):
        for v, cb in self.tick['items']:
            if cb.Visibility == Visibility.Visible:
                cb.IsChecked = value

    def _tick_count(self):
        items = self.tick['items']
        n = len([1 for v, cb in items if cb.IsChecked])
        self.tick['count'].Text = u'{0} / {1}'.format(n, len(items))

    def _tick_close(self, accept):
        t = self.tick
        t['popup'].IsOpen = False
        if not accept or t['key'] is None:
            return
        items = t['items']
        ticked = set(v for v, cb in items if cb.IsChecked)
        if len(ticked) == len(items):
            self.tick_filters.pop(t['key'], None)
        else:
            self.tick_filters[t['key']] = ticked
        self.apply_view()

    # ==================================================================
    # Selection
    # ==================================================================
    def _on_selection_changed(self, sender, args):
        if self._sel_pending:
            return
        self._sel_pending = True
        later(self.win, self._after_selection)

    def _after_selection(self):
        self._sel_pending = False
        sel = set()
        try:
            for info in self.dg.SelectedCells:
                try:
                    sel.add(int(info.Item.Row['ridx']))
                except Exception:
                    pass
        except Exception:
            pass
        self.selected = sel
        for i in self.hl_rows - sel:
            self._set(self.dt_rows[i], 'hl', u'0')
        for i in sel - self.hl_rows:
            self._set(self.dt_rows[i], 'hl', u'1')
        self.hl_rows = sel
        self.refresh_counts()

    def _cell_under(self, source):
        el = source
        while el is not None and not isinstance(el, DataGridCell):
            try:
                el = VisualTreeHelper.GetParent(el)
            except Exception:
                el = getattr(el, 'Parent', None)
        return el

    def _on_grid_mouse_down(self, sender, args):
        """Click a Path Mode on a selected circuit: the dropdown, for all of
        the selection. Handled, so the click does not drop the selection."""
        try:
            ctrl, shift = mods()
            if ctrl or shift or args.ClickCount > 1:
                return
            cell = self._cell_under(args.OriginalSource)
            if cell is None or cell.Column is None:
                return
            if self.key_of_name.get(cell.Column.SortMemberPath) != 'pm':
                return
            i = int(cell.DataContext.Row['ridx'])
            if i in self.selected and len(self.selected) > 1:
                args.Handled = True
                self.open_mode_menu(sorted(self.selected), cell)
            else:
                later(self.win, lambda: self.open_mode_menu([i], cell))
        except Exception:
            import traceback
            log(traceback.format_exc())

    def open_mode_menu(self, targets, anchor):
        targets = [i for i in targets if self.rows[i].editable.get('pm')]
        if not targets:
            self.set_status(u'Path mode cannot be changed on that circuit.')
            return
        menu = ContextMenu()
        cm_theme.dress(menu, self.resolved)     # transient: built per click
        current = set(cm_logic.parse_path_mode(self.display(i, 'pm'))
                      for i in targets)
        n_custom = len([i for i in targets if self.rows[i].custom_ok])
        head = MenuItem()
        head.Header = u'Set path mode on {0} circuit{1}'.format(
            len(targets), u'' if len(targets) == 1 else u's')
        head.IsEnabled = False
        menu.Items.Add(head)
        menu.Items.Add(Separator())
        for name, label in cm_logic.PATH_MODES:
            mi = MenuItem()
            text = label
            if name == 'Custom':
                text = u'{0}  ({1} of {2} have a custom path)'.format(
                    label, n_custom, len(targets))
                mi.IsEnabled = n_custom > 0
            mi.Header = text
            mi.IsChecked = current == set([name])
            mi.Click += self._wrap(
                lambda n=name, t=list(targets): self.stage_mode(t, n))
            menu.Items.Add(mi)
        menu.PlacementTarget = anchor
        menu.Placement = PlacementMode.Bottom
        menu.IsOpen = True

    def stage_mode(self, targets, mode):
        custom = dict((i, self.rows[i].custom_ok) for i in targets)
        ok, refused = cm_logic.mode_targets(targets, mode, custom)
        label = cm_logic.path_mode_label(mode)
        changes = [(i, 'pm', label) for i in ok]
        n = self.stage_changes(changes)
        msg = u'{0} set to {1} on {2} circuit{3}.'.format(
            u'Path mode', label, n, u'' if n == 1 else u's')
        if refused:
            msg += u' {0} skipped: no custom path stored.'.format(len(refused))
        self.set_status(msg)

    # ==================================================================
    # Staging
    # ==================================================================
    def stage_changes(self, changes):
        """changes: [(row index, key, text already validated)]."""
        if not changes:
            return 0
        batch, originals, kinds = [], {}, {}
        for i, key, value in changes:
            row = self.rows[i]
            batch.append((row.eid, key, value))
            originals[(row.eid, key)] = row.values.get(key, u'')
            kinds[key] = row.kinds.get(key, 'string')
            self.bad.pop((row.eid, key), None)
        touched = self.stage.apply_batch(batch, originals, kinds)
        self.repaint_cells(touched)
        self.refresh_counts()
        log(u'staged {0} cell(s)'.format(len(touched)))
        return len(changes)

    def validate(self, i, key, text):
        row = self.rows[i]
        if not row.editable.get(key, False):
            return None, row.reasons.get(key, u'read only')
        kind = row.kinds.get(key, 'string')
        value, err = cm_logic.normalise_input(kind, text)
        if err:
            return None, err
        if key == 'pm' and cm_logic.parse_path_mode(value) == 'Custom' \
                and not row.custom_ok:
            return None, u'no custom path stored'
        return value, None

    def repaint_cells(self, keys):
        for eid, key in keys:
            i = self.by_eid.get(eid)
            if i is None or key not in self.col_name:
                continue
            name = self.col_name[key]
            dr = self.dt_rows[i]
            self._set(dr, name, self.display(i, key))
            self._set(dr, name + '_s', self.cell_state(i, key))

    def undo(self):
        touched = self.stage.undo_last()
        if not touched:
            self.set_status(u'Nothing to undo.')
            return
        self.repaint_cells(touched)
        self.refresh_counts()
        self.set_status(u'Undid {0} staged cell{1}.'.format(
            len(touched), u'' if len(touched) == 1 else u's'))

    def clear_staged(self):
        touched = self.stage.clear()
        self.repaint_cells(touched)
        self.refresh_counts()
        self.set_status(u'Staged changes cleared.')

    # ------------------------------------------------------------------
    def _on_beginning_edit(self, sender, args):
        try:
            key = self.key_of_name.get(args.Column.SortMemberPath)
            i = int(args.Row.Item.Row['ridx'])
            if key is None or not self.rows[i].editable.get(key, False):
                args.Cancel = True
                why = self.rows[i].reasons.get(key, u'read only')
                self.set_status(u'That cell cannot be edited: {0}.'.format(why))
                return
            self.editing = True
        except Exception:
            self.editing = False
            args.Cancel = True

    def _on_cell_edit_ending(self, sender, args):
        self.editing = False
        try:
            if args.EditAction != DataGridEditAction.Commit:
                return
            key = self.key_of_name.get(args.Column.SortMemberPath)
            i = int(args.Row.Item.Row['ridx'])
            text = args.EditingElement.Text
        except Exception:
            return

        def stage():
            value, err = self.validate(i, key, text)
            if err:
                self.repaint_cells([(self.rows[i].eid, key)])
                self.set_status(u'Not staged - {0}: "{1}".'.format(err, text))
                return
            self.stage_changes([(i, key, value)])
        later(self.win, stage)

    # ==================================================================
    # Clipboard
    # ==================================================================
    def _positions(self):
        """Visible rows in display order and the columns by display index."""
        rows = []
        for item in self.view:
            rows.append(int(item.Row['ridx']))
        cols = {}
        for col in self.dg.Columns:
            key = self.key_of_name.get(col.SortMemberPath)
            if key is not None and col.Visibility == Visibility.Visible:
                cols[col.DisplayIndex] = key
        return rows, cols

    def _selected_cells(self):
        """[(row position, column display index)] plus the lookups."""
        rows, cols = self._positions()
        pos_of = dict((r, p) for p, r in enumerate(rows))
        out = []
        for info in self.dg.SelectedCells:
            try:
                i = int(info.Item.Row['ridx'])
                c = info.Column.DisplayIndex
            except Exception:
                continue
            if i in pos_of and c in cols:
                out.append((pos_of[i], c))
        return out, rows, cols

    def copy(self):
        cells, rows, cols = self._selected_cells()
        if not cells:
            self.set_status(u'Select cells to copy.')
            return
        old = list(self.copy_marks)
        self.copy_marks = set()
        block_cells = []
        for p, c in cells:
            i, key = rows[p], cols[c]
            block_cells.append((p, c, self.display(i, key)))
            self.copy_marks.add((self.rows[i].eid, key))
        text = cm_logic.to_clipboard(cm_logic.copy_block(block_cells))
        try:
            Clipboard.SetText(text)
        except Exception:
            self.set_status(u'The clipboard is busy - try again.')
            return
        self.repaint_cells(old + list(self.copy_marks))
        self.set_status(u'Copied {0} cell{1}. Select the cells to change and '
                        u'press Ctrl+V.'.format(len(cells),
                                                u'' if len(cells) == 1 else u's'))

    def paste(self):
        try:
            text = Clipboard.GetText()
        except Exception:
            text = u''
        if not text:
            self.set_status(u'Nothing on the clipboard.')
            return
        cells, rows, cols = self._selected_cells()
        if not cells:
            self.set_status(u'Select the cells to paste into.')
            return
        clip = cm_logic.parse_clipboard(text)
        col_positions = sorted(cols.keys())
        plan = cm_logic.paste_plan(clip, cells, list(range(len(rows))),
                                   col_positions)
        changes, skipped = [], []
        for p, c, raw in plan:
            i, key = rows[p], cols[c]
            value, err = self.validate(i, key, raw)
            if err:
                skipped.append(err)
            else:
                changes.append((i, key, value))
        old = list(self.copy_marks)
        self.copy_marks = set()
        self.repaint_cells(old)
        n = self.stage_changes(changes)
        msg = u'Pasted into {0} cell{1}.'.format(n, u'' if n == 1 else u's')
        if skipped:
            reasons = sorted(set(skipped))
            msg += u' {0} skipped ({1}).'.format(len(skipped),
                                                 u', '.join(reasons[:3]))
        self.set_status(msg)

    def clear_copy_marks(self):
        old = list(self.copy_marks)
        self.copy_marks = set()
        self.repaint_cells(old)

    # ==================================================================
    # Keys
    # ==================================================================
    def _typing(self):
        from System.Windows.Input import Keyboard
        return self.editing or isinstance(Keyboard.FocusedElement, TextBox)

    def _on_grid_key(self, sender, args):
        if self._typing():
            return                      # the text box's own Ctrl+C / Ctrl+V
        key = str(args.Key)
        ctrl, shift = mods()
        handled = True
        if ctrl and key == 'C':
            self.copy()
        elif ctrl and key == 'V':
            self.paste()
        elif ctrl and key == 'Z':
            self.undo()
        elif key == 'Escape' and self.copy_marks:
            self.clear_copy_marks()
        else:
            handled = False
        if handled:
            args.Handled = True

    def on_key(self, args, key, ctrl, shift):
        if key == 'F5':
            self.apply_view()
            args.Handled = True
        elif ctrl and key == 'S':
            self.apply()
            args.Handled = True

    # ==================================================================
    # Columns
    # ==================================================================
    def _on_add_columns(self, sender, args):
        try:
            params = cm_revit.available_parameters(
                cm_revit.collect_circuits(self.doc))
        except Exception:
            import traceback
            log(traceback.format_exc())
            self.set_status(u'Could not list the circuit parameters.')
            return
        shown = [k[len(cm_revit.PARAM_PREFIX):] for k in self.param_keys]
        picked = cm_dialogs.ParamPicker(self, params, shown).show()
        if picked is None:
            return
        keep = [n for n in shown if n in picked]
        new = [n for n, k, w in params if n in picked and n not in keep]
        self.param_keys = [cm_revit.PARAM_PREFIX + n for n in keep + new]
        SETTINGS.set('columns', cm_logic.join_columns(keep + new))
        self.reload()

    def remove_column(self, key):
        if key not in self.param_keys:
            return
        self.param_keys.remove(key)
        self.text_filters.pop(key, None)
        self.tick_filters.pop(key, None)
        SETTINGS.set('columns', cm_logic.join_columns(
            [k[len(cm_revit.PARAM_PREFIX):] for k in self.param_keys]))
        self.reload()

    # ==================================================================
    # Apply
    # ==================================================================
    def apply(self):
        if self.runner.busy:
            self.set_status(u'Still writing the last change...')
            log(u'apply ignored while busy')
            return
        changes = self.stage.by_element()
        if not changes:
            self.set_status(u'Nothing staged to apply.')
            return
        n = self.stage.count()
        summary = {}
        for eid, items in changes.items():
            for key, value in items:
                label = self.col_label(key)
                k = (label, value)
                summary[k] = summary.get(k, 0) + 1
        lines = [u'{0}  ->  {1}   ({2} circuit{3})'.format(
            lab, val, c, u'' if c == 1 else u's')
            for (lab, val), c in sorted(summary.items())]
        body = u'\n'.join(lines[:40])
        if len(lines) > 40:
            body += u'\n... and {0} more'.format(len(lines) - 40)
        choice = cm_dialogs.ask(
            self, u'Apply {0} change{1} to {2} circuit{3}?'.format(
                n, u'' if n == 1 else u's', len(changes),
                u'' if len(changes) == 1 else u's'),
            body, [(u'Cancel', None), (u'Apply', 'GreenBtn')])
        if choice != u'Apply':
            return
        self.set_busy(True)
        self.set_status(u'Writing {0} change{1}...'.format(
            n, u'' if n == 1 else u's'))
        param_keys = list(self.param_keys)

        target_doc = self.doc

        def job(uiapp):
            # the document the window was opened on, not whichever is active
            doc = target_doc
            if not doc.IsValidObject:
                raise Exception(u'The project this window was opened on has '
                                u'been closed.')
            results = cm_revit.apply_changes(doc, changes, log=log)
            fresh = {}
            for es in cm_revit.collect_circuits(doc):
                k = cm_revit.eid_value(es.Id)
                if k in changes:
                    fresh[k] = cm_revit.read_row(es, param_keys)
            return results, fresh

        def done(result, error):
            later(self.win, lambda: self._after_apply(result, error))

        if not self.runner.submit(job, done):
            self.set_busy(False)

    def col_label(self, key):
        h = self.heads.get(key)
        return h['head'] if h else key

    def _after_apply(self, result, error):
        self.set_busy(False)
        if error:
            log(error)
            cm_dialogs.tell(self, u'Nothing was written', to_text(error))
            return
        results, fresh = result
        for eid, row in fresh.items():
            i = self.by_eid.get(eid)
            if i is not None:
                self.rows[i] = row
        ok, refused = [], []
        for (eid, key), reason in results.items():
            if reason is None:
                ok.append((eid, key))
            else:
                refused.append((eid, key, reason))
                self.bad[(eid, key)] = reason
        self.stage.clear([(e, k) for e, k in ok] +
                         [(e, k) for e, k, r in refused])
        touched = list(results.keys())
        self.repaint_cells(touched)
        self.refresh_counts()
        changed = len(set(e for e, k in ok))
        msg = u'Applied {0} change{1} on {2} circuit{3}.'.format(
            len(ok), u'' if len(ok) == 1 else u's', changed,
            u'' if changed == 1 else u's')
        if refused:
            msg += u' {0} refused - shown red.'.format(len(refused))
        self.set_status(msg)
        log(msg)
        if refused:
            lines = []
            for eid, key, reason in sorted(refused):
                i = self.by_eid.get(eid)
                name = eid
                if i is not None:
                    v = self.rows[i].values
                    name = u'{0} / {1}'.format(v.get('panel'), v.get('num'))
                lines.append(u'{0}  {1}: {2}'.format(name, self.col_label(key),
                                                     reason))
            cm_dialogs.tell(self, u'Revit refused {0} change{1}'.format(
                len(refused), u'' if len(refused) == 1 else u's'),
                u'\n'.join(lines[:60]))

    def set_busy(self, busy):
        """Body and buttons go deaf; the shrink button stays live."""
        for name in ('body', 'toolbar', 'footer'):
            el = self.find(name)
            if el is not None:
                el.IsHitTestVisible = not busy
        self.drawer.busy = busy
        if busy:
            self.watchdog.Start()
        else:
            self.watchdog.Stop()

    def _on_watchdog(self, sender, args):
        self.watchdog.Stop()
        if self.runner.busy:
            log(u'watchdog freed a busy window')
            self.runner.free()
            self.set_busy(False)
            self.set_status(u'Revit did not answer - the window is free again. '
                            u'Press Refresh to see what landed.')

    # ==================================================================
    # Status
    # ==================================================================
    def set_status(self, text):
        try:
            self.status.Text = text
        except Exception:
            pass

    def refresh_counts(self):
        try:
            shown = len([1 for dr in self.dt_rows if to_text(dr['vis']) == u'1'])
            self.find('apply_text').Text = u'Apply ({0})'.format(
                self.stage.count())
            self.find('apply_btn').IsEnabled = self.stage.count() > 0
            self.find('undo_btn').IsEnabled = bool(self.stage.undo)
            n = len(self.selected)
            self.find('sel_text').Text = u'{0} circuits  |  {1} shown  |  ' \
                u'{2} selected  |  {3} staged'.format(
                    len(self.rows), shown, n, self.stage.count())
            filtered = any(cm_logic.is_filtered(k, self.text_filters,
                                                self.tick_filters)
                           for k in self.cols)
            self.find('reset_text').Text = u'Reset filters' + (
                u' *' if filtered else u'')
            if not self.status.Text or self.status.Text.startswith(u'Reading'):
                self.set_status(u'{0} circuits read.'.format(len(self.rows)))
        except Exception:
            pass

    # ==================================================================
    # Life cycle
    # ==================================================================
    def _on_first_move(self, sender, args):
        """The engine is alive: clear the note written at launch."""
        if self.armed and not self.alive:
            self.alive = True
            SETTINGS.set('open_note', '')

    def _on_closing(self, sender, args):
        if self.force_close or self.stage.count() == 0:
            return
        n = self.stage.count()
        choice = cm_dialogs.ask(
            self, u'{0} staged change{1} not applied'.format(
                n, u'' if n == 1 else u's'),
            u'Closing now throws them away.',
            [(u'Close without applying', None), (u'Keep open', 'GreenBtn')])
        if choice != u'Close without applying':
            args.Cancel = True

    def on_closed(self):
        try:
            from System import AppDomain
            AppDomain.CurrentDomain.SetData(instance_key(), None)
        except Exception:
            pass
        SETTINGS.save()
        log(u'closed')

    def show(self):
        if self.modal:
            self.armed = True
            self.win.ShowDialog()
            return
        owned_to_revit(self.win, self.uiapp)
        self.win.Show()
        self.armed = True           # only now can a handler prove the engine


def instance_key():
    return 'RevoBIM.CircuitManager.window.' + __version__


def launch(uiapp):
    """Open the window, or bring the open one forward."""
    from System import AppDomain
    try:
        existing = AppDomain.CurrentDomain.GetData(instance_key())
        if existing is not None:
            existing.win.Activate()
            if existing.drawer.parked:
                existing.drawer.expand()
            return existing
    except Exception:
        pass
    modal = False
    if SETTINGS.get('open_note') == __version__:
        choice = cm_dialogs.ask(
            None, u'Circuit Manager did not respond last time',
            u'The window opened but none of its buttons answered - pyRevit '
            u'had not kept the engine alive. Open it modal this time? Revit '
            u'will be locked while it is open.',
            [(u'Open as normal', None), (u'Open modal', 'GreenBtn')])
        modal = choice == u'Open modal'
    if not modal:
        SETTINGS.set('open_note', __version__)
    try:
        window = CircuitManagerWindow(uiapp, modal=modal)
    except Exception:
        SETTINGS.set('open_note', '')     # a build failure is not a dead engine
        raise
    if not modal:
        AppDomain.CurrentDomain.SetData(instance_key(), window)
    window.show()
    return window
