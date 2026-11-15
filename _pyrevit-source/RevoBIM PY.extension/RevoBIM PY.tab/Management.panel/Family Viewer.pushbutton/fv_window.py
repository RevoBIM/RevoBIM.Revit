# -*- coding: utf-8 -*-
"""Family Viewer - the window.

Modeless and owned by Revit's main window, so Revit stays fully navigable and
editable while it is open and the window floats above Revit rather than
slipping behind it.  Every touch of the API goes out through the ExternalEvent
in fv_ops.
"""

import fv_clr  # noqa: F401  - must be first

import os

from System import Action, Object, TimeSpan
from System.Windows import (
    Clipboard, CornerRadius, DataTemplate, FrameworkElement,
    HorizontalAlignment, Thickness, Visibility,
)
from System.Windows.Controls import (
    Border, Button, CheckBox, ComboBox, ComboBoxItem, ContextMenu,
    DataGridCell, DataGridLength, DataGridLengthUnitType, DataGridRow,
    DataGridTemplateColumn, ListBoxItem, MenuItem, Orientation, StackPanel,
    TextBlock, TextBox,
)
from System.Windows.Controls.Primitives import PlacementMode, Popup
from System.Windows.Input import Key
from System.Windows.Media import (
    BrushConverter, Geometry, ScaleTransform,
)
from System.Windows.Shapes import Path as ShapePath
from System.Windows.Threading import DispatcherPriority, DispatcherTimer

import fv_core
import fv_excel
import fv_grid
import fv_model
import fv_ops
import fv_ui
import theme
from fv_core import as_bool, as_int, as_list, natural_key
from fv_model import FAMILY_ROW, KEY_CATEGORY, KEY_COUNT, KEY_NAME

HERE = os.path.dirname(os.path.abspath(__file__))
ICON = os.path.join(HERE, 'icon.png')

# the two entries the parameter picker always offers, defined next to the
# picker itself in fv_grid so there is only one spelling of them
PARAM_NONE = fv_grid.PARAM_NONE
PARAM_REMOVE = fv_grid.PARAM_REMOVE


def _ancestor_with_tag(element, tag):
    return fv_ui.ancestor(element, tag=tag)


def _ancestor_of_type(element, wanted):
    return fv_ui.ancestor(element, wanted=wanted)



def _nothing():
    """An empty dispatcher job: invoking it is how the UI gets to repaint
    while the thread is otherwise busy."""
    return None

class FamilyViewerWindow(object):

    def __init__(self, uiapp, handler, event, settings, dock_host=None):
        self.uiapp = uiapp
        self.handler = handler
        self.event = event
        self.settings = settings
        # follow / dark / light is what is saved; the palette is what that
        # resolves to against Revit's canvas right now
        self.palette = theme.resolve(settings.get('theme', theme.FOLLOW),
                                     theme.revit_canvas())

        # Two hosts, one body.  dock_host is the Grid Revit's own dockable pane
        # shows; with none, the body goes inside the floating window instead.
        self.dock_host = dock_host
        self.docked = dock_host is not None
        self.window = None
        self.body = None
        if self.docked:
            self.body = fv_ui.load_element('FamilyViewerBody.xaml',
                                           self.palette)
            self.theme_host = self.body
            try:
                dock_host.Children.Clear()
            except Exception:
                pass
            dock_host.Children.Add(self.body)
        else:
            self.window = fv_ui.load_window('FamilyViewer.xaml', self.palette)
            self.theme_host = self.window
            # the body inherits the window's merged Theme.xaml and its palette,
            # so a theme switch has one place to write rather than two
            self.body = fv_ui.load_element('FamilyViewerBody.xaml')
            self.window.FindName('BodyHost').Content = self.body

        self.converter = fv_grid.CellConverter(self)

        # script.py fills this in when the dockable pane is available; None
        # means startup.py never registered one
        self.on_move_to_pane = None

        self.result = None
        self.families = []
        self.shown = []
        self.rows = []
        self.columns = fv_grid.base_columns(settings)
        self.column_signature = None
        self._type_params = None
        self._shade_cache = {}
        # the wash each grouped value gets, and the order they were first seen
        self._tints = {}
        self._tint_order = []
        self.sort_key = KEY_NAME
        self.sort_dir = 1

        self.categories = []
        self.cat_selected = None          # None means every category
        self.phases = []
        self.worksets = []
        self.phase_id = None
        self.scope = settings.get('default_scope', 'project')
        self.doc_title = ''
        self.view_name = ''

        self.previews = {}
        self.preview_queue = []
        self.preview_busy = False

        # staged edits: (kind, element id, column key) -> the typed value.
        # Nothing is written until Apply, and Apply says what it is about to
        # do first.
        self.pending = {}
        # where each staged change came from - typed by hand, the batch rename
        # window, or an imported workbook - so each can be told apart on screen
        # and the edit bar can count them.  One map, cleared in the same
        # places as pending, rather than a set per source kept in step by hand.
        self.staged_from = {}
        self._import_ids = None
        # the last import's summary, for the debug report
        self.last_import = ''
        # after an import the list is isolated to the rows that changed, and
        # what the filters were before is kept so Apply can put them back
        self.isolated = False
        self.before_isolate = None
        # Temporary Hide/Isolate is left in the view until Restore View is
        # pressed, so the button has to remember which of the two it is
        self.view_isolated = False
        # the third level: instances read per type, and whether they are being
        # shown and grouped
        self.instance_rows = {}
        self.showing_instances = False
        self.grouping = False
        # a filter state to put back once the next read has finished.  Apply
        # re-reads the model, and a read clears the filters on purpose, so the
        # restore has to happen after it rather than before
        self.restore_after_read = None
        self.editing = None

        self.busy = False
        self.truncated = False
        self.cat_snapshot = None
        self.closed = False
        self.dirty = False
        self.settle = None
        self.loading = True

        self._grab_elements()
        self._wire()
        self._apply_scale()
        self._restore_from_settings()

    # ------------------------------------------------------------------
    # elements
    # ------------------------------------------------------------------

    def _el(self, name):
        """The body and the window are separate namescopes, so a lookup has to
        try both.  Everything goes through here, so nothing else has to know
        which host the tool is running in."""
        if self.body is not None:
            try:
                found = self.body.FindName(name)
            except Exception:
                found = None
            if found is not None:
                return found
        if self.window is not None:
            try:
                return self.window.FindName(name)
            except Exception:
                return None
        return None

    def _grab_elements(self):
        # window only - absent when the body is in Revit's dockable pane
        self.header_bar = self._el('HeaderBar')
        self.app_icon = self._el('AppIcon')
        self.version_text = self._el('VersionText')
        self.theme_chip = self._el('ThemeChip')
        self.settings_chip = self._el('SettingsChip')
        self.full_btn = self._el('FullBtn')
        self.close_btn = self._el('CloseBtn')
        self.dock_left = self._el('DockLeftChip')
        self.dock_float = self._el('DockFloatChip')
        self.dock_right = self._el('DockRightChip')
        self.dock_pane_btn = self._el('DockPaneBtn')
        self.dock_chip_panel = self._el('DockChips')

        # the body's own header, shown only in the pane
        self.dock_header = self._el('DockHeader')
        self.dock_icon = self._el('DockIcon')
        self.dock_version = self._el('DockVersion')
        self.dock_theme_chip = self._el('DockThemeChip')
        self.dock_settings_chip = self._el('DockSettingsChip')
        self.footer_bar = self._el('FooterBar')
        self.select_label = self._el('SelectLabel')
        self.toolbar_wrap = self._el('ToolbarWrap')

        self.progress = self._el('Progress')
        self.apply_progress = self._el('ApplyProgress')
        self.apply_progress_text = self._el('ApplyProgressText')
        self.apply_progress_percent = self._el('ApplyProgressPercent')
        self.apply_progress_bar = self._el('ApplyProgressBar')
        self.cat_toggle = self._el('CatToggle')
        self.cat_popup = self._el('CatPopup')
        self.cat_search = self._el('CatSearch')
        self.cat_all = self._el('CatAll')
        self.cat_none = self._el('CatNone')
        self.cat_from_view = self._el('CatFromView')
        self.cat_count = self._el('CatCount')
        self.cat_list = self._el('CatList')

        self.scope_toggle = self._el('ScopeToggle')
        self.scope_popup = self._el('ScopePopup')
        self.scope_list = self._el('ScopeList')
        self.scope_glyph = self._el('ScopeGlyph')
        self.restore_btn = self._el('RestoreBtn')
        self.debug_btn = self._el('DebugBtn')
        self.phase_toggle = self._el('PhaseToggle')
        self.phase_popup = self._el('PhasePopup')
        self.phase_list = self._el('PhaseList')
        self.phase_glyph = self._el('PhaseGlyph')
        self.cat_glyph = self._el('CatGlyph')
        self.search_toggle = self._el('SearchToggle')
        self.global_search = self._el('GlobalSearch')
        self.fold_btn = self._el('FoldBtn')
        self.fold_glyph = self._el('FoldGlyph')
        self.excel_toggle = self._el('ExcelToggle')
        self.excel_popup = self._el('ExcelPopup')
        self.rename_toggle = self._el('RenameToggle')
        self.rename_popup = self._el('RenamePopup')
        self.quick_title = self._el('QuickTitle')
        self.quick_find = self._el('QuickFind')
        self.quick_replace = self._el('QuickReplace')
        self.quick_case = self._el('QuickCase')
        self.quick_prefix = self._el('QuickPrefix')
        self.quick_suffix = self._el('QuickSuffix')
        self.quick_preview = self._el('QuickPreview')
        self.quick_sample = self._el('QuickSample')
        self.quick_more = self._el('QuickMore')
        self.quick_apply = self._el('QuickApply')
        self.refresh_glyph = self._el('RefreshGlyph')
        self.refresh_dot = self._el('RefreshDot')
        self.images_toggle = self._el('ImagesToggle')
        self.instances_btn = self._el('InstancesBtn')
        self.instances_glyph = self._el('InstancesGlyph')
        self.group_btn = self._el('GroupBtn')
        self.group_glyph = self._el('GroupGlyph')
        self.export_btn = self._el('ExportBtn')
        self.import_btn = self._el('ImportBtn')
        self.refresh_btn = self._el('RefreshBtn')
        self.scope_note = self._el('ScopeNote')

        self.grid = self._el('FamilyGrid')
        self.empty_note = self._el('EmptyNote')

        self.status_text = self._el('StatusText')
        self.sel_info = self._el('SelInfo')
        self.select_project_btn = self._el('SelectProjectBtn')
        self.select_view_btn = self._el('SelectViewBtn')
        self.isolate_view_btn = self._el('IsolateViewBtn')
        self.edit_bar = self._el('EditBar')
        self.edit_note = self._el('EditNote')
        self.apply_btn = self._el('ApplyBtn')
        self.discard_btn = self._el('DiscardBtn')
        self.isolate_btn = self._el('IsolateBtn')
        self.resize_layer = self._el('ResizeLayer')
        self.root_border = self._el('RootBorder')

    # ------------------------------------------------------------------
    # wiring
    # ------------------------------------------------------------------

    def _wire(self):
        version = 'v' + fv_core.__version__
        image = fv_ui.image_from_file(ICON)
        for label in (self.version_text, self.dock_version):
            if label is not None:
                label.Text = version
        for holder in (self.app_icon, self.dock_icon):
            if holder is not None and image is not None:
                holder.Source = image

        self.chrome = None
        self.drawer = None
        if self.window is not None:
            handle = None
            try:
                handle = self.uiapp.MainWindowHandle
            except Exception:
                handle = None
            self.chrome = fv_ui.Chrome(self.window, handle, self.settings)
            self.chrome.on_state = self._dock_state_changed
            self.chrome.wire_header(self.header_bar)
            self.chrome.add_grips(self.resize_layer)
            # shrink to taskbar - the project standard for every window
            self.drawer = fv_ui.WindowDrawer(
                self.window, self.header_bar, self.root_border,
                self._el('ShrinkBtn'), grips=self.resize_layer)

            self.close_btn.Click += self.on_close_click
            self.full_btn.Click += self.on_full_click
            self.dock_left.Click += self.on_dock_left
            self.dock_float.Click += self.on_dock_float
            self.dock_right.Click += self.on_dock_right
            if self.dock_pane_btn is not None:
                self.dock_pane_btn.Click += self.on_dock_pane
            if self.footer_bar is not None:
                # square corners inside the window's 6px rounded border read as
                # a mistake; a Border does not clip its child, so the footer has
                # to round its own bottom corners
                self.footer_bar.CornerRadius = CornerRadius(0.0, 0.0, 6.0, 6.0)
        else:
            if self.dock_header is not None:
                self.dock_header.Visibility = Visibility.Visible

        for chip in (self.theme_chip, self.dock_theme_chip):
            if chip is not None:
                chip.Click += self.on_theme_click
        for chip in (self.settings_chip, self.dock_settings_chip):
            if chip is not None:
                chip.Click += self.on_settings_click

        self.cat_toggle.Click += self.on_cat_toggle
        self.cat_search.TextChanged += self.on_cat_search
        self.cat_all.Click += self.on_cat_all
        self.cat_none.Click += self.on_cat_none
        self.cat_from_view.Click += self.on_cat_from_view
        self.restore_btn.Click += self.on_restore_default
        self.debug_btn.Click += self.on_debug
        self.cat_popup.Closed += self.on_cat_closed

        self.scope_toggle.Click += self.on_scope_toggle
        self.scope_popup.Closed += self.on_scope_closed
        self.scope_list.SelectionChanged += self.on_scope_picked

        self.phase_toggle.Click += self.on_phase_toggle
        self.phase_popup.Closed += self.on_phase_closed
        self.phase_list.SelectionChanged += self.on_phase_changed

        self.search_toggle.Click += self.on_search_toggle
        self.global_search.TextChanged += self.on_global_search
        self.fold_btn.Click += self.on_fold
        self.images_toggle.Click += self.on_images_toggle
        self.instances_btn.Click += self.on_instances
        self.group_btn.Click += self.on_group
        self.excel_toggle.Click += self.on_excel_toggle
        self.excel_popup.Closed += self.on_excel_closed
        self.rename_toggle.Click += self.on_rename_toggle
        self.rename_popup.Closed += self.on_rename_closed
        for box in [self.quick_find, self.quick_replace, self.quick_prefix,
                    self.quick_suffix]:
            box.TextChanged += self.on_quick_changed
        self.quick_case.Click += self.on_quick_changed
        self.quick_apply.Click += self.on_quick_apply
        self.quick_more.Click += self.on_quick_more
        self.export_btn.Click += self.on_export
        self.import_btn.Click += self.on_import
        self.refresh_btn.Click += self.on_refresh

        try:
            self.grid.CanUserReorderColumns = True
        except Exception:
            pass
        self.grid.LoadingRow += self.on_loading_row
        self.grid.SelectionChanged += self.on_selection_changed
        self.grid.PreviewMouseLeftButtonDown += self.on_grid_click
        self.grid.MouseDoubleClick += self.on_grid_double_click
        self.grid.Sorting += self.on_grid_sorting
        try:
            # the count and the name both stay put while the parameter columns
            # scroll sideways
            self.grid.FrozenColumnCount = 2
        except Exception:
            pass

        self.select_project_btn.Click += self.on_select_project
        self.select_view_btn.Click += self.on_select_view
        self.isolate_view_btn.Click += self.on_isolate_view
        self.apply_btn.Click += self.on_apply
        self.discard_btn.Click += self.on_discard
        self.isolate_btn.Click += self.on_show_everything

        self.grid.MouseRightButtonUp += self.on_grid_right_click
        self.grid.ColumnReordered += self.on_column_reordered

        # the tool has to work squeezed into a Revit dock, so what the body
        # shows follows its own width rather than the window's
        self.body.SizeChanged += self.on_body_resized

        if self.window is not None:
            self.window.KeyDown += self.on_key
            self.window.Closed += self.on_closed
        else:
            self.body.KeyDown += self.on_key

        # the search box is debounced, so typing re-filters once rather than
        # once per keystroke
        self.debounce = DispatcherTimer()
        self.debounce.Interval = TimeSpan.FromMilliseconds(250)
        self.debounce.Tick += self._debounced
        self.pending_filter = False

        self.preview_timer = DispatcherTimer()
        self.preview_timer.Interval = TimeSpan.FromMilliseconds(120)
        self.preview_timer.Tick += self._preview_tick
        self.preview_timer.Start()

        # DocumentChanged must not read the document: it sets a flag and a
        # timer does the read on the dispatcher.  Hooked once and switched
        # with a flag, because unsubscribing an IronPython bound method from a
        # .NET event is not reliable.
        try:
            self.uiapp.Application.DocumentChanged += self.on_document_changed
        except Exception:
            fv_core.log('could not watch DocumentChanged:\n' + fv_core.format_exc())
        # Revit 2024+ raises ThemeChanged when its canvas switches.  Hooked
        # once and gated by the closed flag, like DocumentChanged, because
        # unhooking an IronPython bound method is not reliable.
        try:
            self.uiapp.ThemeChanged += self.on_revit_theme_changed
        except Exception:
            pass
        self.settle = DispatcherTimer()
        self.settle.Interval = TimeSpan.FromMilliseconds(
            as_int(self.settings, 'settle_ms', 200, 10000))
        self.settle.Tick += self._settle_tick

    def _apply_scale(self):
        scale = as_int(self.settings, 'ui_scale', 80, 150) / 100.0
        target = self.root_border if self.root_border is not None else self.body
        try:
            if abs(scale - 1.0) < 0.001:
                target.LayoutTransform = None
            else:
                target.LayoutTransform = ScaleTransform(scale, scale)
        except Exception:
            pass

    def _restore_from_settings(self):
        self.scope = self.settings.get('default_scope', 'project')
        if self.scope not in ('project', 'view', 'all'):
            self.scope = 'project'
        label = theme.other(self.palette).capitalize()
        for chip in (self.theme_chip, self.dock_theme_chip):
            if chip is not None:
                chip.Content = label
        for name in as_list(self.settings, 'columns'):
            self.columns.append(self._new_param_column(name))
        self._paint_images_toggle()
        if self.window is not None:
            side = self.settings.get('dock_side', 'float')
            self._set_dock_chips(side)

    # ------------------------------------------------------------------
    # narrow layouts
    # ------------------------------------------------------------------

    def on_body_resized(self, sender, args):
        try:
            width = float(self.body.ActualWidth)
        except Exception:
            return
        if width <= 0:
            return

        # squeezed right down, the footer label and the dock chips are the
        # first things worth losing: the buttons themselves are not
        if self.select_label is not None:
            self.select_label.Visibility = (
                Visibility.Visible if width >= 620 else Visibility.Collapsed)
        if self.select_project_btn is not None:
            self.select_project_btn.Content = (
                'Entire Project' if width >= 460 else 'Project')
        if self.select_view_btn is not None:
            self.select_view_btn.Content = (
                'Active View' if width >= 460 else 'View')
        if self.isolate_view_btn is not None and not self.view_isolated:
            # Restore View keeps its full name however narrow it gets: it is
            # the one that undoes something
            self.isolate_view_btn.Content = (
                'Isolate in View' if width >= 560 else 'Isolate')
        if self.dock_chip_panel is not None:
            self.dock_chip_panel.Visibility = (
                Visibility.Visible if width >= 900 else Visibility.Collapsed)
        if self.version_text is not None:
            self.version_text.Visibility = (
                Visibility.Visible if width >= 700 else Visibility.Collapsed)

    # ------------------------------------------------------------------
    # opening
    # ------------------------------------------------------------------

    def show(self):
        if self.window is not None:
            self.window.Show()
            self.chrome.own_to_revit()
            side = self.settings.get('dock_side', 'float')
            if side in ('left', 'right'):
                self.chrome.dock(side)
        self.set_status('Reading the project...')
        self.request_lists()

    def request_lists(self):
        payload = {
            'include_system': as_bool(self.settings, 'include_system'),
            'include_annotation': as_bool(self.settings, 'include_annotation'),
        }
        self._raise('lists', payload, self.on_lists_done)

    def _raise(self, kind, payload, done):
        self.handler.add(fv_ops.Job(kind, payload, done, self.on_job_failed))
        try:
            self.event.Raise()
        except Exception:
            self.on_job_failed(fv_core.format_exc())

    def on_job_failed(self, text):
        self.busy = False
        self._set_busy(False)
        # a failed Apply rolled back, so the staged edits are still there and
        # the edit bar comes back with them
        self._show_apply_progress(False)
        self._update_edit_bar()
        fv_core.log(text)
        first = text.strip().splitlines()[-1] if text.strip() else 'unknown'
        self.set_status('Something went wrong: ' + first)
        fv_ui.prompt(self.window, self.palette, 'Family Viewer could not finish',
                     text, 'Close', accent='orange')

    def on_lists_done(self, data):
        self.categories = data.get('categories', [])
        self.phases = data.get('phases', [])
        self.worksets = data.get('worksets', [])
        self.doc_title = data.get('doc_title', '')
        self.view_name = data.get('view_name', '')

        wanted = as_list(self.settings, 'categories')
        if wanted:
            by_name = {}
            for entry in self.categories:
                by_name[entry['name']] = entry['id']
            picked = set()
            for name in wanted:
                if name in by_name:
                    picked.add(by_name[name])
            self.cat_selected = picked or None
        else:
            self.cat_selected = None

        self._fill_scope_list()
        self._fill_phase_list()
        self._fill_category_list()
        self._update_cat_toggle()
        self.request_read()

    # ------------------------------------------------------------------
    # reading
    # ------------------------------------------------------------------

    def request_read(self):
        if self.busy:
            return
        self.reset_filters()
        self.busy = True
        self._set_busy(True)
        self.set_status('Reading families and counting elements...')
        # The scope is passed by name and fv_model.scope_rules turns it into
        # both halves of what it means - where to count, and whether to keep a
        # type with nothing placed. Nothing here second-guesses it.
        payload = {
            'scope': self.scope,
            'categories': list(self.cat_selected) if self.cat_selected else None,
            'columns': self.param_column_names(),
            'include_system': as_bool(self.settings, 'include_system'),
            'include_annotation': as_bool(self.settings, 'include_annotation'),
            'ignore_nested': as_bool(self.settings, 'ignore_nested'),
            'phase_id': self.phase_id,
            'phase_mode': self.settings.get('phase_mode', 'existing'),
        }
        self._raise('read', payload, self.on_read_done)

    def on_read_done(self, result):
        self.busy = False
        # a re-read replaces every row, so a staged edit would be pointing at a
        # row that no longer exists; they go with it, and the status says so
        dropped = len(self.pending)
        self.pending = {}
        self.staged_from = {}
        self._set_busy(False)
        self.result = result
        self._type_params = None
        self.families = result.families
        self.view_name = getattr(result, 'view_name', '') or self.view_name
        self.dirty = False
        self._mark_refresh(False)
        opened = as_bool(self.settings, 'families_open')
        for parent in self.families:
            parent.open = opened
        self.previews = {}
        self.loading = False
        self.rebuild()
        self._paint_fold()

        # the filtering that was in place before an import isolated the list
        if self.restore_after_read is not None:
            state = self.restore_after_read
            self.restore_after_read = None
            self._apply_filter_state(state)
            self.rebuild()
            self.set_status(
                'Applied, and the filters you had before the import are back.')
        if dropped:
            self.set_status(
                str(dropped) + ' staged change' + ('' if dropped == 1 else 's') +
                ' were dropped: the model was re-read and the rows they were '
                'staged against are gone.')

    # ------------------------------------------------------------------
    # columns
    # ------------------------------------------------------------------

    def _new_param_column(self, name):
        column = fv_grid.Column(name, name, 'param', 1.1, 130.0)
        return column

    def param_column_names(self):
        return [column.key for column in self.columns if column.kind == 'param']

    def _signature(self):
        parts = []
        for column in self.columns:
            parts.append(column.key + '|' + column.kind + '|' + str(column.sort))
        return '::'.join(parts)

    def rebuild_columns(self):
        """Columns are only rebuilt when they actually change - typing in a
        search box re-filters rows without relaying the whole grid."""
        signature = self._signature()
        if signature == self.column_signature:
            return
        self.column_signature = signature
        self.grid.Columns.Clear()

        for column in self.columns:
            item = DataGridTemplateColumn()
            if column.key == KEY_NAME:
                item.CellTemplate = fv_grid.name_template(self.converter)
            elif column.key == KEY_COUNT:
                item.CellTemplate = fv_grid._template(
                    fv_grid._text_factory(self.converter, KEY_COUNT,
                                          'count.fg', 'count.weight',
                                          HorizontalAlignment.Center))
            elif column.key == KEY_CATEGORY:
                item.CellTemplate = fv_grid._template(
                    fv_grid._text_factory(self.converter, KEY_CATEGORY, 'name.fg'))
            else:
                item.CellTemplate = fv_grid._template(
                    fv_grid._tinted_factory(
                        self.converter, 'p:' + column.key,
                        'pfg:' + column.key, 'pweight:' + column.key,
                        tint_key='tint:' + column.key))
            item.Header = fv_grid.build_header(column, self)
            if column.key == KEY_NAME:
                # star, so it takes the slack on a wide window and stops at its
                # minimum on a narrow one
                item.Width = DataGridLength(column.width,
                                            DataGridLengthUnitType.Star)
            else:
                item.Width = DataGridLength(column.pixels,
                                            DataGridLengthUnitType.Pixel)
            item.MinWidth = column.minimum
            item.CanUserSort = False
            # the frozen column is the first one by definition, so it does not
            # get dragged out of place
            # the two frozen columns stay where they are; everything else can
            # be dragged about
            item.CanUserReorder = column.key not in (KEY_NAME, KEY_COUNT)
            column.column = item
            self.grid.Columns.Add(item)

        plus = DataGridTemplateColumn()
        plus.Header = fv_grid.plus_button(self.on_add_column)
        plus.Width = DataGridLength(40.0, DataGridLengthUnitType.Pixel)
        plus.CellTemplate = DataTemplate()
        plus.CanUserSort = False
        plus.CanUserReorder = False
        self.grid.Columns.Add(plus)
        self._paint_sort_arrows()

    # ------------------------------------------------------------------
    # removing and reordering columns
    # ------------------------------------------------------------------

    def can_remove(self, column):
        """Family and type is the frozen column and the only one that carries
        the chevron, the preview and the name, so the list makes no sense
        without it.  Everything else can go and be added back from the +."""
        return column.key != KEY_NAME

    def remove_column(self, column):
        if not self.can_remove(column):
            return
        if column not in self.columns:
            return
        self.columns.remove(column)
        self._save_columns()
        self.column_signature = None
        if column.kind == 'param':
            # a parameter column gone means one less thing to read
            self.request_read()
        else:
            self.rebuild()
        self.set_status(
            'Removed the ' + (column.title or 'blank') +
            ' column. The green plus puts it back.')

    def on_column_reordered(self, sender, args):
        """Dragging a heading reorders the row list to match.

        The name column is the frozen one, so it is put back to the left if
        anything is dropped in front of it - a frozen column that is not the
        first one freezes the wrong thing.
        """
        try:
            # the frozen pair are the first two by definition, so anything
            # dropped in front of them is put back behind them
            for wanted, key in ((0, KEY_COUNT), (1, KEY_NAME)):
                for column in self.columns:
                    if column.key != key or column.column is None:
                        continue
                    if column.column.DisplayIndex != wanted:
                        column.column.DisplayIndex = wanted
                    break
        except Exception:
            pass

        ordered = []
        try:
            pairs = []
            for column in self.columns:
                index = 99
                try:
                    index = int(column.column.DisplayIndex)
                except Exception:
                    index = 99
                pairs.append((index, column))
            pairs.sort(key=lambda pair: pair[0])
            ordered = [column for _, column in pairs]
        except Exception:
            ordered = list(self.columns)
        self.columns = ordered
        # the signature carries the order, so the next rebuild agrees with what
        # is on screen rather than relaying it back to where it was
        self.column_signature = self._signature()
        self._save_columns()

    def on_add_column(self, sender, args):
        """The plus offers the fixed columns back first, then a parameter."""
        have = set([column.key for column in self.columns])
        if KEY_CATEGORY not in have:
            self.columns.append(fv_grid.Column(KEY_CATEGORY, 'Category',
                                               'fixed', 1.0, 90.0, 140.0))
            self.column_signature = None
            self.rebuild()
            return
        if KEY_COUNT not in have:
            self.columns.append(fv_grid.Column(KEY_COUNT, 'Count', 'fixed',
                                               0.55, 60.0, 74.0))
            self.column_signature = None
            self.rebuild()
            return
        if not self.result:
            return
        used = self.param_column_names()
        offer = [name for name in self.result.param_names if name not in used]
        if not offer:
            self.set_status(
                'Every parameter these categories carry is already a column.')
            return
        self.columns.append(self._new_param_column(offer[0]))
        self._save_columns()
        self.request_read()

    def param_offer(self, column):
        """What the picker lists: the parameters the categories on show
        actually carry, with the ones already used as columns left out so the
        same parameter cannot land in two columns."""
        names = []
        if self.result:
            names = list(self.result.param_names)
        used = set(self.param_column_names())
        used.discard(column.key)
        offer = [name for name in names if name not in used]
        if column.key and column.key not in offer:
            offer.insert(0, column.key)
        return offer

    def pick_param(self, column, chosen):
        """(none) clears the column, (remove this column) takes it away."""
        if chosen == column.key:
            return
        if chosen == fv_grid.PARAM_REMOVE:
            if column in self.columns:
                self.columns.remove(column)
            self._save_columns()
            self.column_signature = None
            self.request_read()
            return
        if chosen == fv_grid.PARAM_NONE:
            column.key = ''
            column.title = ''
            column.search = ''
            column.allowed = None
            if column.picker_chip is not None:
                column.picker_chip.Content = fv_grid.PARAM_NONE
            self._save_columns()
            self.column_signature = None
            self.rebuild()
            return
        column.key = chosen
        column.title = chosen
        column.search = ''
        column.allowed = None
        if column.picker_chip is not None:
            column.picker_chip.Content = chosen
        self._save_columns()
        self.column_signature = None
        self.request_read()

    def _save_columns(self):
        fv_core.set_list(self.settings, 'columns', self.param_column_names())
        fv_core.save_settings(self.settings)

    # ------------------------------------------------------------------
    # filters
    # ------------------------------------------------------------------

    def on_filter_changed(self):
        self.pending_filter = True
        try:
            self.debounce.Stop()
            self.debounce.Start()
        except Exception:
            self.rebuild()

    def _debounced(self, sender, args):
        try:
            self.debounce.Stop()
        except Exception:
            pass
        if self.pending_filter:
            self.pending_filter = False
            self.rebuild()

    def on_global_search(self, sender, args):
        self.on_filter_changed()

    def fill_tick_list(self, column):
        """Ticking follows Excel's autofilter: everything ticked means no
        filter, unticking narrows, nothing ticked shows nothing."""
        if column.list_box is None:
            return
        needle = ''
        if column.tick_search is not None:
            needle = column.tick_search.Text or ''
        column.list_box.Items.Clear()
        values = fv_grid.distinct_values(self.families, column.key,
                                         self._all_instance_rows())

        def toggled(sender, args):
            chosen = set()
            everything = set()
            for index in range(column.list_box.Items.Count):
                box = column.list_box.Items[index]
                if not isinstance(box, CheckBox):
                    continue
                text = str(box.Tag or '')
                everything.add(text)
                if box.IsChecked:
                    chosen.add(text)
            existing = column.allowed
            if existing is None:
                existing = set([value for value, count in values])
            existing = set(existing) - everything
            existing = existing | chosen
            if len(existing) == len(values):
                column.allowed = None
            else:
                column.allowed = existing
            self.on_filter_changed()

        for value, count in values:
            if needle and not fv_core.matches_search(value or '(blank)', needle):
                continue
            ticked = (column.allowed is None) or (value in column.allowed)
            column.list_box.Items.Add(
                fv_grid.tick_item(value, count, ticked, toggled))

    def set_all_ticks(self, column, state):
        values = [value for value, count in fv_grid.distinct_values(
            self.families, column.key, self._all_instance_rows())]
        column.allowed = None if state else set()
        self.fill_tick_list(column)
        self.on_filter_changed()

    def on_sort(self, column):
        if self.sort_key == column.key:
            self.sort_dir = -self.sort_dir
        else:
            self.sort_key = column.key
            self.sort_dir = 1
        self._paint_sort_arrows()
        self._sorted_changed()
        self.rebuild()

    def _sorted_changed(self):
        """The group button follows the sort, because grouping is by whatever
        column the list is sorted on."""
        if self.grouping and not self._can_group():
            self.grouping = False
        self._paint_instance_buttons()

    def _paint_sort_arrows(self):
        """The sorted column is outlined orange and its arrow lit; the rest
        keep a muted arrow, so every column says it can be sorted by."""
        for column in self.columns:
            sorted_by = (column.key == self.sort_key and self.sort_dir)
            if column.arrow is not None:
                column.arrow.Data = Geometry.Parse(
                    fv_grid.ARROW_UP if (sorted_by and self.sort_dir > 0)
                    else fv_grid.ARROW_DOWN)
                try:
                    column.arrow.SetResourceReference(
                        ShapePath.FillProperty,
                        'AccentOrange' if sorted_by else 'FgMuted')
                    column.arrow.Opacity = 1.0 if sorted_by else 0.45
                except Exception:
                    pass
            if column.outline is None:
                continue
            try:
                if sorted_by:
                    column.outline.SetResourceReference(
                        Border.BorderBrushProperty, 'AccentOrange')
                else:
                    column.outline.BorderBrush = None
            except Exception:
                pass

    def on_grid_sorting(self, sender, args):
        """Sorting is done on the row list, not through a CollectionView, since
        the grid binds row objects rather than properties."""
        args.Handled = True

    # ------------------------------------------------------------------
    # rows
    # ------------------------------------------------------------------

    def rebuild(self):
        self._close_editor()
        if self.loading:
            return
        self.rebuild_columns()
        if self.isolated:
            # isolation ignores the category, the phase and every column filter
            # on purpose: the point is to see what the workbook changed, and a
            # filter set before the import would hide half of it
            shown = self._isolated_families()
        else:
            needle = self.global_search.Text or ''
            active = [column for column in self.columns if column.key]
            shown = fv_grid.apply_filters(self.families, active, needle)
        shown = fv_grid.sort_families(shown, self.sort_key, self.sort_dir)
        self.shown = shown

        self._attach_instances(shown)
        rows = fv_model.flatten(shown)
        cap = as_int(self.settings, 'max_rows', 200, 100000)
        self.truncated = len(rows) > cap
        if self.truncated:
            rows = rows[:cap]
        self.rows = rows

        selected = self._selected_type_ids()
        self.grid.ItemsSource = fv_grid.to_list(rows)
        self._restore_selection(selected)

        if rows:
            self.empty_note.Visibility = Visibility.Collapsed
        else:
            self.empty_note.Visibility = Visibility.Visible
            self.empty_note.Text = self._empty_reason()
        self._queue_previews()
        self.update_footer()

    def _empty_reason(self):
        """Why the list is empty, told apart properly.

        The one message this used to show blamed the column filters whatever
        the cause, and sent two rounds of looking in the wrong place when the
        read itself had come back with nothing.  There are three different
        situations and they get three different answers.
        """
        if self.isolated:
            return 'Nothing was changed by that workbook.'

        # 1. the read came back with nothing at all
        if not self.families:
            notes = []
            if self.result is not None:
                notes = list(self.result.notes)
            head = 'Nothing was found at this scope.'
            if self.scope == fv_model.SCOPE_VIEW:
                head = ('Nothing is placed in the active view' +
                        ((' (' + self.view_name + ')') if self.view_name
                         else '') + '.')
            elif self.scope == fv_model.SCOPE_PROJECT:
                head = 'Nothing is placed anywhere in this project.'
            tail = ('Entire project and Active view only list families that '
                    'are placed. Switch the scope to All families in project '
                    'to see every family loaded.')
            if (self.scope == fv_model.SCOPE_VIEW and self.result is not None
                    and not getattr(self.result, 'in_scope_seen', 0)):
                # the common case, and the one worth naming: the categories
                # are ticked, they exist in the project, and this particular
                # view has none of them in it
                tail = ('The categories you have ticked do exist in the '
                        'project - there is just nothing of them in this '
                        'view. Switch the scope to Entire project to see '
                        'them, or open a view that has some.')
            if self.scope == fv_model.SCOPE_ALL:
                tail = ('Check the category picker - unticking every category '
                        'shows nothing.')
            if self.phase_id is not None:
                # the phase is the filter that emptied this list before, and
                # it is the least visible of them
                tail = ('A phase is set, and the phase icon is orange to say '
                        'so. Set it back to every phase if that is not what '
                        'you meant.\n' + tail)
            return head + '\n' + '\n'.join(notes + [tail])

        # 2. the read found rows and the filters hid all of them
        hidden = 0
        for parent in self.families:
            hidden += len(parent.children)
        narrowed = [column.title or column.key for column in self.columns
                    if column.search or column.allowed is not None]
        if narrowed:
            return ('All ' + str(hidden) + ' types were hidden by the filters '
                    'on ' + ', '.join(narrowed) + '.\nClear those search '
                    'boxes, or tick some values back on.')
        if self.global_search.Text:
            return ('None of the ' + str(hidden) + ' types match "' +
                    self.global_search.Text + '".')

        # 3. neither, which should not happen
        return ('The list is empty, and neither the read nor the filters '
                'explain it. Refresh, and please report it if it happens '
                'again.')

    def _restore_selection(self, type_ids):
        if not type_ids:
            return
        wanted = set(type_ids)
        try:
            self.grid.SelectedItems.Clear()
            for row in self.rows:
                if row.kind != FAMILY_ROW and row.type_id in wanted:
                    self.grid.SelectedItems.Add(row)
        except Exception:
            pass

    def update_footer(self):
        families = len(self.shown)
        types = sum([len(parent.children) for parent in self.shown])
        instances = sum([parent.count for parent in self.shown])
        parts = [
            '{0} families'.format(families) if families != 1 else '1 family',
            '{0} types'.format(types) if types != 1 else '1 type',
            '{0} elements'.format(instances) if instances != 1 else '1 element',
        ]
        text = ' - '.join(parts)
        if self.truncated:
            text += ' - the list is showing the first ' + \
                str(as_int(self.settings, 'max_rows', 200, 100000)) + \
                ' rows; Export list writes them all'
        self.set_status(text)

        where = 'every family placed in the project'
        if self.scope == fv_model.SCOPE_VIEW:
            where = 'every family placed in the active view'
            if self.view_name:
                where += ' (' + self.view_name + ')'
        elif self.scope == fv_model.SCOPE_ALL:
            where = 'every family in the project, placed or not'
        phase = 'every phase'
        if self.phase_id:
            for entry in self.phases:
                if entry['id'] == self.phase_id:
                    phase = 'phase ' + entry['name']
                    mode = self.settings.get('phase_mode', 'existing')
                    phase += ', counting what was created in it' \
                        if mode != 'existing' else ', counting what stands in it'
                    break
        note = 'Counting ' + where + ', ' + phase + '.'
        if self.result is not None and self.result.no_phase:
            note += ' ' + str(self.result.no_phase) + \
                ' elements carry no phase at all and were left out.'
        if self.result is not None and self.result.notes:
            note += ' ' + ' '.join(self.result.notes)
        self.scope_note.Text = note

    def set_status(self, text):
        try:
            self.status_text.Text = text
        except Exception:
            pass

    # ------------------------------------------------------------------
    # previews
    # ------------------------------------------------------------------

    def on_images_toggle(self, sender, args):
        """Family images on or off, from the toolbar and remembered.  The
        same setting the Settings window has, so the two never disagree."""
        showing = bool(self.images_toggle.IsChecked)
        self.settings['show_previews'] = '1' if showing else '0'
        fv_core.save_settings(self.settings)
        self._paint_images_toggle()
        self._refresh_cells()
        if showing:
            self._queue_previews()

    def _paint_images_toggle(self):
        showing = as_bool(self.settings, 'show_previews')
        try:
            self.images_toggle.IsChecked = showing
            self.images_toggle.ToolTip = ('Hide the family images' if showing
                                          else 'Show the family images')
        except Exception:
            pass

    def preview_edge(self, row):
        if not as_bool(self.settings, 'show_previews'):
            return 0
        where = self.settings.get('preview_on', 'family')
        family = (row.kind == FAMILY_ROW)
        if where == 'family' and not family:
            return 0
        if where == 'type' and family:
            return 0
        return as_int(self.settings, 'preview_size', 16, 256)

    def _preview_id(self, row):
        return row.preview_id if row.kind == FAMILY_ROW else row.type_id

    def preview_for(self, row):
        if self.preview_edge(row) <= 0:
            return None
        key = self._preview_id(row)
        if not key:
            return None
        return self.previews.get(key)

    def _queue_previews(self):
        if not as_bool(self.settings, 'show_previews'):
            self.preview_queue = []
            return
        wanted = []
        for row in self.rows:
            if self.preview_edge(row) <= 0:
                continue
            key = self._preview_id(row)
            if key and key not in self.previews and key not in wanted:
                wanted.append(key)
        self.preview_queue = wanted

    def _preview_tick(self, sender, args):
        if self.closed or self.preview_busy or self.busy:
            return
        if not self.preview_queue:
            return
        batch = self.preview_queue[:fv_ops.PREVIEW_BATCH]
        self.preview_queue = self.preview_queue[fv_ops.PREVIEW_BATCH:]
        self.preview_busy = True
        self._raise('preview',
                    {'ids': batch,
                     'size': as_int(self.settings, 'preview_size', 16, 256)},
                    self.on_previews_done)

    def on_previews_done(self, made):
        self.preview_busy = False
        if self.closed:
            return
        for key in made:
            self.previews[key] = made[key]
        selected = self._selected_type_ids()
        try:
            self.grid.Items.Refresh()
        except Exception:
            pass
        self._restore_selection(selected)

    # ------------------------------------------------------------------
    # cell helpers the converter calls back into
    # ------------------------------------------------------------------

    def group_tint(self, row, column_key):
        """The wash behind a grouped cell.

        Only on the column the elements are grouped by, and only on the rows
        the grouping applies to - the heading and the elements under it.  Every
        distinct value gets its own colour, so which elements share a value
        reads without comparing text row by row.
        """
        if not self.grouping or column_key != self.sort_key:
            return None
        if row.kind not in (fv_model.GROUP_ROW, fv_model.INSTANCE_ROW):
            return None
        if row.kind == fv_model.GROUP_ROW:
            value = row.group_key
        else:
            parent = row.parent
            if parent is None or parent.kind != fv_model.GROUP_ROW:
                return None
            value = parent.group_key
        return self._tint_for(value)

    def _tint_for(self, value):
        made = self._tints.get(value)
        if made is not None:
            return made
        palette = (fv_grid.GROUP_TINTS if self.palette == 'dark'
                   else fv_grid.GROUP_TINTS_LIGHT)
        # the order a value is first seen decides its colour, so the same
        # grouping gives the same colours every time it is rebuilt
        if value not in self._tint_order:
            self._tint_order.append(value)
        index = self._tint_order.index(value) % len(palette)
        made = self._brush_from_hex(palette[index])
        self._tints[value] = made
        return made

    def family_font_size(self):
        return as_int(self.settings, 'family_row_size', 11, 22)

    def family_row_brush(self):
        """The band behind a family row.

        A colour set in Settings wins; blank falls back to the palette's own
        FamilyRowBg, so switching between dark and light still works rather
        than leaving one hard-coded shade behind on both.
        """
        chosen = (self.settings.get('family_row_shade', '') or '').strip()
        if chosen:
            made = self._brush_from_hex(chosen)
            if made is not None:
                return made
        return self.brush('FamilyRowBg')

    def _brush_from_hex(self, text):
        if self._shade_cache.get(text) is not None:
            return self._shade_cache[text]
        try:
            made = BrushConverter().ConvertFromString(text)
        except Exception:
            made = None
        self._shade_cache[text] = made
        return made

    def on_loading_row(self, sender, args):
        """A family row gets its band here rather than from a style trigger:
        the row's kind is a Python attribute, and a WPF trigger cannot see
        one."""
        try:
            row = args.Row.Item
        except Exception:
            return
        try:
            if row is not None and row.kind == FAMILY_ROW:
                if self.family_has_import(row):
                    args.Row.Background = self.brush('ImportRowBg')
                else:
                    args.Row.Background = self.family_row_brush()
            else:
                args.Row.ClearValue(DataGridRow.BackgroundProperty)
        except Exception:
            pass

    def brush(self, key):
        try:
            return self.theme_host.Resources[key]
        except Exception:
            pass
        try:
            return self.body.TryFindResource(key)
        except Exception:
            return None

    def tooltip_for(self, row):
        if row is None:
            return ''
        if row.kind == FAMILY_ROW:
            return '{0}\n{1}  -  {2} types  -  {3} elements'.format(
                row.family_name, row.category, len(row.children), row.count)
        return '{0} : {1}\nType id {2}  -  {3} elements'.format(
            row.family_name, row.type_name, row.type_id, row.count)

    # ------------------------------------------------------------------
    # categories
    # ------------------------------------------------------------------

    def _fill_category_list(self):
        needle = self.cat_search.Text or ''
        self.cat_list.Items.Clear()

        def toggled(sender, args):
            picked = set()
            for entry in self.categories:
                if self.cat_selected is None or entry['id'] in self.cat_selected:
                    picked.add(entry['id'])
            for index in range(self.cat_list.Items.Count):
                box = self.cat_list.Items[index]
                if not isinstance(box, CheckBox):
                    continue
                value = int(box.Tag)
                if box.IsChecked:
                    picked.add(value)
                else:
                    picked.discard(value)
            if len(picked) == len(self.categories):
                self.cat_selected = None
            else:
                self.cat_selected = picked
            self._update_cat_toggle()

        for entry in self.categories:
            if needle and not fv_core.matches_search(entry['name'], needle):
                continue
            box = CheckBox()
            fv_ui.styled(box, 'ThemedCheck')
            box.Content = entry['name'] + '   ' + str(entry['types'])
            box.Tag = entry['id']
            box.IsChecked = (self.cat_selected is None or
                             entry['id'] in self.cat_selected)
            box.Margin = Thickness(2.0, 2.0, 2.0, 2.0)
            box.Checked += toggled
            box.Unchecked += toggled
            self.cat_list.Items.Add(box)

        total = len(self.categories)
        shown = self.cat_list.Items.Count
        if shown == total:
            self.cat_count.Text = str(total) + ' categories in this project'
        else:
            self.cat_count.Text = str(shown) + ' of ' + str(total) + ' shown'

    def _update_cat_toggle(self):
        self._paint_filter_icons()
        """The icon has no room for a label, so what it is set to lives in its
        tooltip - which is also what tells you what the button is."""
        if self.cat_selected is None:
            text = 'all ' + str(len(self.categories))
        elif not self.cat_selected:
            text = 'none picked'
        elif len(self.cat_selected) == 1:
            only = list(self.cat_selected)[0]
            text = str(only)
            for entry in self.categories:
                if entry['id'] == only:
                    text = entry['name']
                    break
        else:
            text = str(len(self.cat_selected)) + ' picked'
        try:
            self.cat_toggle.ToolTip = 'Categories - ' + text
        except Exception:
            pass

    def on_cat_toggle(self, sender, args):
        self.cat_popup.IsOpen = bool(self.cat_toggle.IsChecked)
        if self.cat_popup.IsOpen:
            self.cat_snapshot = None if self.cat_selected is None \
                else set(self.cat_selected)
            self._fill_category_list()

    def on_cat_closed(self, sender, args):
        self.cat_toggle.IsChecked = False
        before = self.cat_snapshot
        after = None if self.cat_selected is None else set(self.cat_selected)
        if before == after:
            return
        names = []
        if self.cat_selected is not None:
            for entry in self.categories:
                if entry['id'] in self.cat_selected:
                    names.append(entry['name'])
        fv_core.set_list(self.settings, 'categories', names)
        fv_core.save_settings(self.settings)
        self.request_read()

    def on_cat_search(self, sender, args):
        self._fill_category_list()

    def on_cat_all(self, sender, args):
        self.cat_selected = None
        self._fill_category_list()
        self._update_cat_toggle()

    def on_cat_from_view(self, sender, args):
        """Tick exactly the categories that have something in the active view.

        Read off the elements rather than the view's category settings: a
        category can be switched on in a view and have nothing in it, and
        ticking it would then be a lie.
        """
        self.set_status('Looking at the active view...')
        self._raise('view_categories', {}, self.on_cat_from_view_done)

    def on_cat_from_view_done(self, data):
        found = set(data.get('ids', []))
        known = set([entry['id'] for entry in self.categories])
        picked = found & known
        missing = len(found - known)
        if not picked:
            self.set_status(
                'Nothing in the active view belongs to a category this list '
                'covers, so the ticks were left alone.')
            return
        self.cat_selected = picked
        self._fill_category_list()
        self._update_cat_toggle()
        names = []
        for entry in self.categories:
            if entry['id'] in picked:
                names.append(entry['name'])
        fv_core.set_list(self.settings, 'categories', names)
        fv_core.save_settings(self.settings)
        note = (str(len(picked)) + ' categories ticked from ' +
                (data.get('view_name') or 'the active view') + '.')
        if missing:
            note += (' ' + str(missing) + ' more are in the view but not in '
                     'this list - system or annotation categories, which are '
                     'off in Settings.')
        self.set_status(note)
        self.request_read()

    # ------------------------------------------------------------------
    # the debug report
    # ------------------------------------------------------------------

    def on_debug(self, sender, args):
        self.set_status('Gathering the report...')
        self._raise('debug', {}, self.on_debug_done)

    def on_debug_done(self, data):
        lines = self._debug_lines(data)
        try:
            path = fv_core.write_debug(lines)
        except Exception:
            fv_ui.prompt(self.window, self.palette,
                         'The report could not be written',
                         fv_core.format_exc(), 'Close', accent='orange')
            return
        try:
            Clipboard.SetText('\n'.join(lines))
            copied = ' It is on the clipboard too.'
        except Exception:
            copied = ''
        answer = fv_ui.prompt(
            self.window, self.palette, 'Debug report written',
            'Written to\n' + path + '\n\nIt says what the tool read, what the '
            'filters were set to, and what is actually in the active view by '
            'category.' + copied + '\n\nOpen the folder?',
            'Open folder', 'Not now', accent='green')
        self.set_status('Debug report written to ' + path)
        if not answer:
            return
        fv_ui.open_folder(path)

    def _debug_lines(self, data):
        """Everything needed to tell a real fault from an empty view."""
        out = []

        def head(text):
            out.append('')
            out.append('== ' + text + ' ' + '=' * max(0, 58 - len(text)))

        out.append('RevoBIM Family Viewer - debug report')
        out.append('version ' + fv_core.__version__)

        head('Revit and the document')
        for key in ('revit', 'document', 'path', 'workshared', 'active view',
                    'view type'):
            out.append('  ' + key + ': ' + str(data.get(key, '')))

        head('What the tool was set to')
        out.append('  scope: ' + str(self.scope))
        out.append('  phase: ' + (self._phase_name() or 'every phase'))
        out.append('  phase mode: ' +
                   str(self.settings.get('phase_mode', 'existing')))
        if self.cat_selected is None:
            out.append('  categories: all')
        else:
            names = [entry['name'] for entry in self.categories
                     if entry['id'] in self.cat_selected]
            out.append('  categories ticked (' + str(len(names)) + '): ' +
                       ', '.join(sorted(names)))
        out.append('  columns: ' + ', '.join(self.param_column_names()))
        narrowed = [(column.title or column.key) for column in self.columns
                    if column.search or column.allowed is not None]
        out.append('  column filters: ' +
                   (', '.join(narrowed) if narrowed else 'none'))
        out.append('  search: ' + (self.global_search.Text or '(none)'))

        head('What the read found')
        result = self.result
        if result is None:
            out.append('  nothing has been read yet')
        else:
            for label, key in (
                    ('types read', 'types_found'),
                    ('elements Revit offered', 'instances_seen'),
                    ('of those, in the ticked categories', 'in_scope_seen'),
                    ('of those, whose type was not read', 'in_scope_no_match'),
                    ('elements whose type was not read (any category)',
                     'no_type_match'),
                    ('left out as nested', 'nested_out'),
                    ('left out by the phase', 'phased_out'),
                    ('counted', 'instance_total')):
                out.append('  ' + label + ': ' +
                           str(getattr(result, key, '(not recorded)')))
            out.append('  families shown: ' + str(len(self.shown)))
            out.append('  rows drawn: ' + str(len(self.rows)))
            tally = getattr(result, 'by_category', {}) or {}
            if tally:
                out.append('  counted by category:')
                for name in sorted(tally):
                    out.append('    ' + name + ': ' + str(tally[name]))
            for note in getattr(result, 'notes', []):
                out.append('  note: ' + note)

        head('What is actually in the active view, by category')
        view_tally = data.get('view_categories', {}) or {}
        if not view_tally:
            out.append('  (nothing, or the view could not be read)')
        for name in sorted(view_tally, key=lambda one:
                           (-view_tally[one], one)):
            out.append('  ' + name + ': ' + str(view_tally[name]))

        head('Last import')
        if self.last_import:
            for line in self.last_import.split('\n'):
                out.append('  ' + line)
        else:
            out.append('  (no workbook imported this session)')
        staged = {}
        for key in self.pending:
            source = self.staged_from.get(key, 'hand')
            staged[source] = staged.get(source, 0) + 1
        out.append('  staged now: ' + (', '.join(
            [str(count) + ' ' + source for source, count in
             sorted(staged.items())]) or 'nothing'))

        head('Settings')
        for key in sorted(self.settings):
            out.append('  ' + key + ' = ' + str(self.settings[key]))

        head('Log, most recent last')
        for line in fv_core.log_tail(150):
            out.append('  ' + line)
        return out

    def _phase_name(self):
        for entry in self.phases:
            if entry['id'] == self.phase_id:
                return entry['name']
        return ''

    def on_restore_default(self, sender, args):
        """Back to a reading with nothing hidden.

        The categories are deliberately left alone: they are the one choice
        that is usually a deliberate narrowing of a big model, and throwing
        them away would mean picking them all again.
        """
        answer = fv_ui.prompt(
            self.window, self.palette, 'Restore defaults?',
            'This clears every column search and tick filter, sets the phase '
            'to every phase, and sets the scope to all families in project '
            'including not placed.\n\nThe categories you have picked are kept, '
            'and nothing is written to the model.',
            'Restore', 'Cancel', accent='orange')
        if not answer:
            return
        self.reset_filters()
        self.phase_id = None
        self.settings['default_phase'] = ''
        self.scope = fv_model.SCOPE_ALL
        self.settings['default_scope'] = fv_model.SCOPE_ALL
        fv_core.save_settings(self.settings)
        self.loading = True
        self._fill_scope_list()
        self._fill_phase_list()
        self.loading = False
        self._paint_filter_icons()
        self.set_status('Filters cleared, every phase, all families in project.')
        self.request_read()

    def on_cat_none(self, sender, args):
        self.cat_selected = set()
        self._fill_category_list()
        self._update_cat_toggle()

    # ------------------------------------------------------------------
    # scope and phase
    # ------------------------------------------------------------------

    SCOPES = [
        (fv_model.SCOPE_PROJECT, 'Entire project',
         'every family placed anywhere in the project'),
        (fv_model.SCOPE_VIEW, 'Active view',
         'every family placed in the active view only'),
        (fv_model.SCOPE_ALL, 'All families in project, including not placed',
         'every family in the project, whether anything is placed or not'),
    ]

    def _fill_scope_list(self):
        self.scope_list.Items.Clear()
        chosen = 0
        for index, entry in enumerate(self.SCOPES):
            value, label, note = entry
            item = ListBoxItem()
            item.Content = label
            item.Tag = value
            item.ToolTip = note
            fv_ui.styled(item, 'ThemedListItem')
            self.scope_list.Items.Add(item)
            if value == self.scope:
                chosen = index
        self.scope_list.SelectedIndex = chosen
        self._label_scope()

    def _label_scope(self):
        """The icon has no room for a label, so what it is set to lives in its
        tooltip - which is also what tells you what the button is."""
        for value, label, note in self.SCOPES:
            if value == self.scope:
                try:
                    self.scope_toggle.ToolTip = 'Scope - ' + label.lower()
                except Exception:
                    pass
                return

    def on_scope_toggle(self, sender, args):
        self.scope_popup.IsOpen = bool(self.scope_toggle.IsChecked)

    def on_scope_closed(self, sender, args):
        self.scope_toggle.IsChecked = False

    def on_scope_picked(self, sender, args):
        item = self.scope_list.SelectedItem
        if item is None or self.loading:
            return
        picked = str(item.Tag)
        if picked == self.scope:
            self.scope_popup.IsOpen = False
            return
        self.scope = picked
        self.settings['default_scope'] = picked
        fv_core.save_settings(self.settings)
        self._label_scope()
        self.scope_popup.IsOpen = False
        self.request_read()

    def _fill_phase_list(self):
        self.phase_list.Items.Clear()
        item = ListBoxItem()
        item.Content = '(every phase)'
        item.Tag = 0
        fv_ui.styled(item, 'ThemedListItem')
        self.phase_list.Items.Add(item)

        # always opens on every phase: see fv_core.DEFAULTS
        wanted = ''
        chosen = 0
        for index, entry in enumerate(self.phases):
            item = ListBoxItem()
            item.Content = entry['name']
            item.Tag = entry['id']
            fv_ui.styled(item, 'ThemedListItem')
            self.phase_list.Items.Add(item)
            if wanted and entry['name'] == wanted:
                chosen = index + 1
        self.phase_list.SelectedIndex = chosen
        self.phase_id = None
        if chosen:
            self.phase_id = self.phases[chosen - 1]['id']
        self._label_phase()
        self._paint_filter_icons()

    def _paint_filter_icons(self):
        """An icon whose filter is on goes orange.

        A phase left set from an earlier session emptied the whole list with
        nothing on screen saying a filter was even on. An overarching filter
        has to look different when it is doing something.
        """
        for glyph, on in ((self.phase_glyph, self.phase_id is not None),
                          (self.cat_glyph, self.cat_selected is not None)):
            if glyph is None:
                continue
            try:
                glyph.SetResourceReference(
                    ShapePath.FillProperty,
                    'AccentOrange' if on else 'FgMuted')
            except Exception:
                pass

    def _label_phase(self):
        """The icon has no room for a label, so what it is set to lives in its
        tooltip - which is also what tells you what the button is."""
        name = 'every phase'
        for entry in self.phases:
            if entry['id'] == self.phase_id:
                name = entry['name']
                break
        try:
            self.phase_toggle.ToolTip = 'Phase - ' + name
        except Exception:
            pass

    def on_phase_toggle(self, sender, args):
        self.phase_popup.IsOpen = bool(self.phase_toggle.IsChecked)

    def on_phase_closed(self, sender, args):
        self.phase_toggle.IsChecked = False

    def on_phase_changed(self, sender, args):
        item = self.phase_list.SelectedItem
        if item is None or self.loading:
            return
        value = 0
        try:
            value = int(item.Tag)
        except Exception:
            value = 0
        new_id = value or None
        if new_id == self.phase_id:
            return
        self.phase_id = new_id
        self.settings['default_phase'] = '' if not new_id else str(item.Content)
        self._label_phase()
        self._paint_filter_icons()
        self.phase_popup.IsOpen = False
        self.request_read()

    # ------------------------------------------------------------------
    # the search box, which unfolds from its icon
    # ------------------------------------------------------------------

    def on_search_toggle(self, sender, args):
        open_now = bool(self.search_toggle.IsChecked)
        self.global_search.Visibility = (
            Visibility.Visible if open_now else Visibility.Collapsed)
        if open_now:
            try:
                self.global_search.Focus()
            except Exception:
                pass
        elif self.global_search.Text:
            # folding it away must not leave an invisible filter running
            self.global_search.Text = ''

    # ------------------------------------------------------------------
    # the grid
    # ------------------------------------------------------------------

    def on_grid_click(self, sender, args):
        if _ancestor_with_tag(args.OriginalSource, 'place') is not None:
            row = self._row_under(args.OriginalSource)
            if row is not None and self.can_place(row):
                args.Handled = True
                self.place_row(row)
            return
        node = _ancestor_with_tag(args.OriginalSource, 'chevron')
        if node is None:
            return
        row = self._row_under(args.OriginalSource)
        if row is None:
            return
        if not self._toggle_open(row):
            return
        args.Handled = True
        self.rebuild()

    def _toggle_open(self, row):
        """Open or shut whichever level was clicked.

        A family row on screen is a copy made by the filter, so the family it
        was copied from is the one that has to remember the state; a type and a
        group heading are the real rows and remember it themselves.
        """
        if row.kind == FAMILY_ROW:
            row.open = not row.open
            for parent in self.families:
                if (parent.family_id == row.family_id and
                        parent.family_name == row.family_name and
                        parent.category_id == row.category_id):
                    parent.open = row.open
            return True
        if row.kind == fv_model.GROUP_ROW:
            row.open = not row.open
            return True
        if row.kind == fv_model.TYPE_ROW and row.loaded and row.instances:
            row.open = not row.open
            return True
        return False

    def on_grid_double_click(self, sender, args):
        """A double click on an editable cell edits it; anywhere else on a
        family row opens or shuts it."""
        row = self._row_under(args.OriginalSource)
        if row is None:
            return
        column = self._column_under(args.OriginalSource)
        if column is not None and self.can_edit(row, column):
            if column.key == fv_model.WORKSET_KEY:
                self.begin_workset_edit(row, column, args.OriginalSource)
            else:
                self.begin_edit(row, column, args.OriginalSource)
            args.Handled = True
            return
        if self._toggle_open(row):
            self.rebuild()

    def _column_under(self, source):
        cell = _ancestor_of_type(source, DataGridCell)
        if cell is None:
            return None
        try:
            index = cell.Column.DisplayIndex
        except Exception:
            return None
        for column in self.columns:
            try:
                if column.column is not None and \
                        column.column.DisplayIndex == index:
                    return column
            except Exception:
                continue
        return None

    # ------------------------------------------------------------------
    # editing: staged, highlighted, and written only by Apply
    # ------------------------------------------------------------------

    def _edit_key(self, row, column_key):
        """A type row is edited on its own type; a family row's NAME is edited
        on the family element, and its parameter cells are not editable at all
        because "(varies)" has no single element behind it."""
        if row is None:
            return None
        if row.kind == FAMILY_ROW:
            if column_key != KEY_NAME:
                return None
            if not row.family_id:
                return None
            return ('family', row.family_id, KEY_NAME)
        if row.kind == fv_model.GROUP_ROW:
            # a heading holds no element, so there is nothing to write
            return None
        if row.kind == fv_model.INSTANCE_ROW:
            # an element has no name of its own - what shows there is its mark
            # or its id - but its parameters are its own and are written to it
            # rather than to every instance of the type
            if column_key in (KEY_NAME, KEY_CATEGORY, KEY_COUNT):
                return None
            if not row.element_id:
                return None
            return ('instance', row.element_id, column_key)
        if not row.type_id:
            return None
        return ('type', row.type_id, column_key)

    def can_edit(self, row, column):
        """Category and Count are read out of the model rather than typed into
        it, so they are not editable.  A system family has no family element to
        rename."""
        if column is None or row is None:
            return False
        if column.key in (KEY_CATEGORY, KEY_COUNT, ''):
            return False
        if row.kind == FAMILY_ROW and row.is_system:
            return False
        return self._edit_key(row, column.key) is not None

    def staged(self, row, column_key):
        """The value waiting for Apply, or None where nothing is staged."""
        if not self.pending:
            return None
        key = self._edit_key(row, column_key)
        if key is None:
            return None
        return self.pending.get(key)

    # the colour each source is shown in: orange typed by hand, green from the
    # batch rename window, teal from a workbook
    STAGED_COLOURS = {'hand': 'AccentOrange', 'batch': 'AccentGreen',
                      'import': 'AccentTeal'}

    def staged_brush(self, row, column_key):
        """The colour of a staged value, or None where nothing is staged."""
        if not self.pending:
            return None
        key = self._edit_key(row, column_key)
        if key is None or key not in self.pending:
            return None
        source = self.staged_from.get(key, 'hand')
        return self.brush(self.STAGED_COLOURS.get(source, 'AccentOrange'))

    def _imported_targets(self):
        """(kind, id) of everything holding a staged change from a workbook,
        worked out once per change of the staged set, not once per row drawn."""
        if self._import_ids is None:
            self._import_ids = set([(key[0], key[1])
                                    for key, source in self.staged_from.items()
                                    if source == 'import' and
                                    key in self.pending])
        return self._import_ids

    def family_has_import(self, row):
        """A family holding a staged change from a workbook, at any level."""
        found = self._imported_targets()
        if not found:
            return False
        if ('family', row.family_id) in found:
            return True
        for child in row.children:
            if ('type', child.type_id) in found:
                return True
            for under in self.instance_rows.get(child.type_id, []):
                if ('instance', under.element_id) in found:
                    return True
        return False

    def _current_text(self, row, column):
        staged = self.staged(row, column.key)
        if staged is not None:
            return staged
        if column.key == KEY_NAME:
            return row.label
        text = row.cell(column.key)
        return '' if text == fv_core.VARIES else (text or '')

    def begin_workset_edit(self, row, column, near):
        """The Workset cell is a dropdown, not a text box.

        A workset has to be one of the ones in the project, so typing it is a
        way to get it wrong.  Where several rows are picked, choosing one
        moves all of them - which is the whole reason to want this on a bank
        of types.
        """
        cell = _ancestor_of_type(near, DataGridCell)
        if cell is None:
            return
        if not self.worksets:
            self.set_status(
                'This model is not workshared, so there are no worksets.')
            return
        self._close_editor()

        picked = [one for one in self._selected_rows()
                  if self._edit_key(one, column.key) is not None]
        if row not in picked:
            picked = [row]

        box = ComboBox()
        fv_ui.styled(box, 'MiniCombo')
        current = self._current_text(row, column)
        chosen = -1
        for index, entry in enumerate(self.worksets):
            item = ComboBoxItem()
            item.Content = entry['name']
            item.Tag = entry['name']
            box.Items.Add(item)
            if entry['name'] == current:
                chosen = index
        box.SelectedIndex = chosen
        box.Margin = Thickness(2.0, 1.0, 2.0, 1.0)

        state = {'done': False}

        def finish(sender_=None, args_=None):
            if state['done']:
                return
            item = box.SelectedItem
            if item is None:
                return
            state['done'] = True
            self.editing = None
            wanted = str(item.Tag)
            for one in picked:
                self.stage_edit(one, column, wanted, quiet=True)
            self._refresh_cells()
            self._update_edit_bar()
            if len(picked) > 1:
                self.set_status(
                    str(len(picked)) + ' types staged onto workset "' +
                    wanted + '". Nothing is written until Apply.')

        def dropped(sender_, args_):
            if not box.IsDropDownOpen and not state['done']:
                # closed without picking anything
                state['done'] = True
                self.editing = None
                self._refresh_cells()

        box.SelectionChanged += finish
        box.DropDownClosed += dropped

        self.editing = (cell, row, column)
        cell.Content = box
        try:
            box.IsDropDownOpen = True
        except Exception:
            pass

    def _selected_rows(self):
        found = []
        try:
            for one in self.grid.SelectedItems:
                if one is not None:
                    found.append(one)
        except Exception:
            pass
        return found

    def begin_edit(self, row, column, near):
        """Edit in the cell itself, with the value selected ready to type over.

        The first version put a themed popup over the cell and it flashed up
        and vanished: a Popup with StaysOpen false closes on the next mouse
        event outside it, and the mouse-up that completes the double click
        that opened it is exactly that event.  There is no popup now - the
        cell's own content is swapped for a text box and swapped back on the
        way out, which is also what makes the value land where the eye already
        is.
        """
        self._close_editor()
        cell = _ancestor_of_type(near, DataGridCell)
        if cell is None:
            return

        box = TextBox()
        fv_ui.styled(box, 'CellEditBox')
        box.Text = self._current_text(row, column)
        box.Margin = Thickness(2.0, 1.0, 2.0, 1.0)
        box.MinWidth = 60.0

        state = {'done': False}

        def finish(keep):
            if state['done']:
                return
            state['done'] = True
            self.editing = None
            if keep:
                self.stage_edit(row, column, box.Text)
            else:
                self._refresh_cells()

        def typed(sender, args):
            if args.Key == Key.Enter:
                args.Handled = True
                finish(True)
            elif args.Key == Key.Escape:
                args.Handled = True
                finish(False)

        def left(sender, args):
            # clicking away commits, the way a spreadsheet does
            finish(True)

        box.KeyDown += typed
        box.LostKeyboardFocus += left

        self.editing = (cell, row, column)
        cell.Content = box
        try:
            box.Focus()
            box.SelectAll()
        except Exception:
            pass

    def _close_editor(self):
        """Put a cell that is being edited back to its normal content."""
        if not getattr(self, 'editing', None):
            return
        cell = self.editing[0]
        self.editing = None
        try:
            cell.Content = None
        except Exception:
            pass
        self._refresh_cells()

    def stage_edit(self, row, column, text, quiet=False):
        key = self._edit_key(row, column.key)
        if key is None:
            return
        wanted = (text or '').strip()
        was = self._current_text(row, column)
        original = row.label if column.key == KEY_NAME else (
            row.cell(column.key) or '')
        if wanted == original:
            # typed back to what it already is: that is a cancel, not an edit
            self.pending.pop(key, None)
            self.staged_from.pop(key, None)
        elif column.key == KEY_NAME and not wanted:
            self.set_status('A name cannot be blank, so nothing was staged.')
            return
        else:
            self.pending[key] = wanted
            self.staged_from[key] = 'hand'
        del was
        if quiet:
            # the caller is staging a run of rows and will redraw once at the
            # end; redrawing per row would be slow and would flicker
            return
        self._refresh_cells()
        self._update_edit_bar()

    def clear_edit(self, row, column):
        key = self._edit_key(row, column.key)
        if key is not None and key in self.pending:
            del self.pending[key]
            self.staged_from.pop(key, None)
            self._refresh_cells()
            self._update_edit_bar()

    def _refresh_cells(self):
        selected = self._selected_type_ids()
        try:
            self.grid.Items.Refresh()
        except Exception:
            pass
        self._restore_selection(selected)

    # ------------------------------------------------------------------
    # isolating the list to what an import changed
    # ------------------------------------------------------------------

    def _all_instance_rows(self):
        """Every element row read, flat.  What the tick filters are built
        from, so a value that only exists on an element is offered."""
        found = []
        for rows in self.instance_rows.values():
            found.extend(rows)
        return found

    def _attach_instances(self, shown):
        """Hang the instances that have been read onto the types on screen.

        The rows are read once per type and kept; grouping and ungrouping is
        then a rearrangement of rows already in hand rather than another read
        of the model, which is what makes the group button feel instant.
        """
        sort_key = self.sort_key
        if sort_key in (KEY_CATEGORY, KEY_COUNT):
            sort_key = ''
        group_key = sort_key if (self.grouping and
                                 sort_key not in ('', KEY_NAME)) else ''
        for parent in shown:
            for child in parent.children:
                if child.kind != fv_model.TYPE_ROW:
                    continue
                rows = self.instance_rows.get(child.type_id)
                if rows is None:
                    child.instances = []
                    child.loaded = False
                    continue
                child.loaded = True
                for row in rows:
                    row.family_name = child.family_name
                    row.type_name = child.type_name
                # the elements follow the same column the list is sorted by,
                # so clicking a heading sorts every level rather than only the
                # two above them
                rows = self._filter_instances(rows)
                rows = fv_model.sort_instances(rows, sort_key, self.sort_dir)
                child.instances = fv_model.group_instances(rows, group_key)

    def _filter_instances(self, rows):
        """The column filters apply to the elements as well.

        Offering a value in the tick list and then not filtering by it would
        be worse than not offering it: the list would look filtered and not
        be.
        """
        active = [column for column in self.columns
                  if column.key and (column.search or
                                     column.allowed is not None)]
        if not active:
            return rows
        needle = self.global_search.Text or ''
        return [row for row in rows
                if fv_grid.row_passes(row, active, needle)]

    def on_instances(self, sender, args):
        """Show every placed element under its type, or fold them away."""
        if self.showing_instances:
            self.showing_instances = False
            self.instance_rows = {}
            for parent in self.families:
                for child in parent.children:
                    child.instances = []
                    child.loaded = False
            self._paint_instance_buttons()
            self.rebuild()
            self.set_status('Back to families and types.')
            return
        if self.busy:
            return
        type_ids = []
        for parent in self.shown:
            for child in parent.children:
                if child.type_id:
                    type_ids.append(child.type_id)
        if not type_ids:
            return
        self.busy = True
        self._set_busy(True)
        self.set_status('Reading the elements under ' + str(len(type_ids)) +
                        ' types...')
        self._raise('instances', {
            'type_ids': type_ids,
            'columns': self.param_column_names(),
            'scope': self.scope,
            'ignore_nested': as_bool(self.settings, 'ignore_nested'),
            'phase_id': self.phase_id,
            'phase_mode': self.settings.get('phase_mode', 'existing'),
            'cap': as_int(self.settings, 'max_instances', 500, 200000),
        }, self.on_instances_done)

    def on_instances_done(self, data):
        self.busy = False
        self._set_busy(False)
        rows = data.get('rows', {})
        self.instance_rows = {}
        total = 0
        for type_id, found in rows.items():
            self.instance_rows[int(type_id)] = found
            total += len(found)
        self.showing_instances = True
        for parent in self.families:
            parent.open = True
            for child in parent.children:
                child.open = True
        self._paint_instance_buttons()
        self.rebuild()
        note = (str(total) + ' element' + ('' if total == 1 else 's') +
                ' listed under their types.')
        if data.get('seen', 0) >= data.get('cap', 0):
            note += (' That is the cap - raise "Most elements to list" in '
                     'Settings to see the rest.')
        self.set_status(note)

    def on_group(self, sender, args):
        """Group the elements under each type by the column the list is
        sorted on."""
        if not self._can_group():
            return
        self.grouping = not self.grouping
        self._tints = {}
        self._tint_order = []
        self._paint_instance_buttons()
        self.rebuild()
        if self.grouping:
            self.set_status(
                'Elements grouped by ' + self._sort_column_title() +
                '. Press it again to ungroup.')
        else:
            self.set_status('Elements ungrouped.')

    def _can_group(self):
        """Grouping is by the sorted column, so it needs instances on screen
        and a parameter column to sort on - grouping by the name or the count
        would put one element under each heading."""
        if not self.showing_instances:
            return False
        return self.sort_key not in (KEY_NAME, KEY_CATEGORY, KEY_COUNT, '')

    def _sort_column_title(self):
        for column in self.columns:
            if column.key == self.sort_key:
                return column.title or column.key
        return self.sort_key

    def _paint_instance_buttons(self):
        try:
            self.instances_glyph.SetResourceReference(
                ShapePath.FillProperty,
                'AccentBlue' if self.showing_instances else 'FgMuted')
            self.instances_btn.ToolTip = (
                'Fold the elements away' if self.showing_instances
                else 'Show every placed element under its type')
        except Exception:
            pass
        can = self._can_group()
        try:
            self.group_btn.IsEnabled = can
            self.group_glyph.SetResourceReference(
                ShapePath.FillProperty,
                'AccentBlue' if (can and self.grouping) else 'FgMuted')
            if not self.showing_instances:
                self.group_btn.ToolTip = (
                    'Show the elements first, then group them')
            elif not can:
                self.group_btn.ToolTip = (
                    'Sort by a parameter column first - grouping by the name '
                    'or the count would put one element under each heading')
            elif self.grouping:
                self.group_btn.ToolTip = ('Ungroup the elements')
            else:
                self.group_btn.ToolTip = ('Group the elements by ' +
                                          self._sort_column_title())
        except Exception:
            pass

    def _isolated_families(self):
        """Only the rows carrying a staged change, whatever the filters say."""
        kept = []
        for parent in self.families:
            children = [child for child in parent.children
                        if self._row_is_staged(child)]
            parent_staged = self._row_is_staged(parent)
            if not children and not parent_staged:
                continue
            shown = parent.__class__(FAMILY_ROW)
            shown.family_name = parent.family_name
            shown.family_id = parent.family_id
            shown.category = parent.category
            shown.category_id = parent.category_id
            shown.is_system = parent.is_system
            shown.preview_id = (children[0].type_id if children
                                else parent.preview_id)
            shown.count = sum([child.count for child in children])
            shown.values = dict(parent.values)
            shown.children = children
            shown.open = True
            shown.note = parent.note
            for child in children:
                child.parent = shown
            kept.append(shown)
        return kept

    def _row_is_staged(self, row):
        for column in self.columns:
            if not column.key:
                continue
            if self.staged(row, column.key) is not None:
                return True
        return self.staged(row, KEY_NAME) is not None

    def isolate_changes(self):
        """Show only what changed, and remember what the filters were.

        The filters are put back by Apply, or by the Show everything button -
        either way the staged changes survive it, because isolation is only
        about what is on screen.
        """
        if not self.isolated:
            self.before_isolate = self._filter_state()
        self.isolated = True
        self.isolate_btn.Visibility = Visibility.Visible
        self.rebuild()

    def on_show_everything(self, sender, args):
        self.restore_filters(say=True)

    def restore_filters(self, say=False):
        """Put back the category, phase and column filters isolation set
        aside.  Never touches the staged changes."""
        if not self.isolated:
            return
        self.isolated = False
        self.isolate_btn.Visibility = Visibility.Collapsed
        state = self.before_isolate
        self.before_isolate = None
        if state is not None:
            self._apply_filter_state(state)
        self.rebuild()
        if say:
            self.set_status(
                'Filters put back. The staged changes are still there, still '
                'in orange, and still waiting for Apply.')

    def _filter_state(self):
        columns = {}
        for column in self.columns:
            columns[column.key] = (column.search,
                                   None if column.allowed is None
                                   else set(column.allowed))
        return {
            'search': self.global_search.Text or '',
            'columns': columns,
        }

    def _apply_filter_state(self, state):
        for column in self.columns:
            saved = state['columns'].get(column.key)
            if saved is None:
                continue
            column.search, column.allowed = saved
            try:
                if column.search_box is not None:
                    column.search_box.Text = column.search
            except Exception:
                pass
        try:
            self.global_search.Text = state.get('search', '')
        except Exception:
            pass

    def _update_edit_bar(self):
        self._import_ids = None
        count = len(self.pending)
        if not count:
            self.edit_bar.Visibility = Visibility.Collapsed
            try:
                self.apply_btn.IsEnabled = False
                self.apply_btn.SetResourceReference(
                    FrameworkElement.StyleProperty, 'BtnGhost')
            except Exception:
                pass
            return
        self.edit_bar.Visibility = Visibility.Visible
        tally = {'hand': 0, 'batch': 0, 'import': 0}
        for key in self.pending:
            source = self.staged_from.get(key, 'hand')
            tally[source] = tally.get(source, 0) + 1
        parts = []
        for source, words in (('hand', ' by hand (orange)'),
                              ('batch', ' from batch rename (green)'),
                              ('import', ' from a workbook (teal)')):
            if tally.get(source):
                parts.append(str(tally[source]) + words)
        self.edit_note.Text = (
            str(count) + (' change' if count == 1 else ' changes') +
            ' staged - ' + ', '.join(parts) +
            '. Nothing is written until Apply.')
        # green the moment there is something it can write, so the button says
        # whether it will do anything before it is pressed
        try:
            self.apply_btn.IsEnabled = True
            self.apply_btn.SetResourceReference(
                FrameworkElement.StyleProperty, 'BtnGreen')
        except Exception:
            pass

    def on_discard(self, sender, args):
        if not self.pending:
            return
        self.pending = {}
        self.staged_from = {}
        self.restore_filters()
        self._refresh_cells()
        self._update_edit_bar()
        self.set_status('Staged changes discarded. The model was not touched.')

    def on_apply(self, sender, args):
        """Apply lists exactly what it is about to do first."""
        if not self.pending or self.busy:
            return
        edits = self._edit_payload()
        lines = []
        for edit in edits[:25]:
            lines.append('  ' + edit['label'] + '   ->   ' +
                         (edit['value'] or '(blank)'))
        if len(edits) > 25:
            lines.append('  ...and ' + str(len(edits) - 25) + ' more')
        answer = fv_ui.prompt(
            self.window, self.palette, 'Apply these changes?',
            str(len(edits)) + ' change' + ('' if len(edits) == 1 else 's') +
            ' will be written to the model:\n\n' + '\n'.join(lines),
            'Apply', 'Cancel', accent='orange')
        if not answer:
            return
        self.busy = True
        self._set_busy(True)
        self.set_status('Writing ' + str(len(edits)) + ' change' +
                        ('' if len(edits) == 1 else 's') + '...')
        self._show_apply_progress(True, len(edits))
        self._raise('apply', {'edits': edits,
                              'progress': self._on_apply_progress},
                    self.on_apply_done)

    # ------------------------------------------------------------------
    # Apply's progress bar
    # ------------------------------------------------------------------

    def _show_apply_progress(self, showing, total=0):
        try:
            if showing:
                self.edit_bar.Visibility = Visibility.Collapsed
                self.apply_progress_bar.Value = 0
                self.apply_progress_percent.Text = '0%'
                self.apply_progress_text.Text = (
                    'Getting ready to write ' + '{:,}'.format(total) +
                    ' change' + ('' if total == 1 else 's'))
                self.apply_progress.Visibility = Visibility.Visible
            else:
                self.apply_progress.Visibility = Visibility.Collapsed
        except Exception:
            pass

    def _on_apply_progress(self, percent, text):
        """Called from inside the write, on Revit's UI thread, which is busy
        doing the write - so the bar only repaints if the dispatcher is given a
        moment.  Pumped at Render priority on purpose: that runs layout and the
        repaint but nothing queued below it, and input sits below it, so a
        click or a key press cannot land in the middle of the transaction.
        ProgressMeter already throttles how often this is called."""
        try:
            self.apply_progress_bar.Value = percent
            self.apply_progress_percent.Text = str(percent) + '%'
            self.apply_progress_text.Text = text
            self.window.Dispatcher.Invoke(DispatcherPriority.Render,
                                          Action(_nothing))
        except Exception:
            pass

    def _edit_payload(self):
        """The staged edits as plain data - no Element handles, because a
        handle captured when the window opened is not safe to write through."""
        # labelled from the WHOLE read, not the rows a filter left on screen:
        # a staged change the filter hides is still going to be written, and
        # the Apply prompt has to name it rather than show a bare id
        labels = {}
        for parent in self.families:
            labels[('family', parent.family_id)] = parent.family_name
            for child in parent.children:
                labels[('type', child.type_id)] = (child.family_name + ' : ' +
                                                   child.type_name)
        for rows in self.instance_rows.values():
            for row in rows:
                labels[('instance', row.element_id)] = (
                    row.family_name + ' : ' + row.type_name + ' : ' +
                    row.label)
        payload = []
        for (kind, element_id, column_key), value in self.pending.items():
            name = labels.get((kind, element_id), str(element_id))
            what = 'name' if column_key == KEY_NAME else column_key
            payload.append({'id': element_id, 'kind': kind,
                            'key': column_key, 'value': value,
                            'label': name + '  [' + what + ']'})
        payload.sort(key=lambda edit: natural_key(edit['label']))
        return payload

    def on_apply_done(self, data):
        self.busy = False
        self._set_busy(False)
        self._show_apply_progress(False)
        written = data.get('written', 0)
        problems = data.get('problems', [])
        locked = data.get('locked', [])
        fv_core.log('apply: ' + str(written) + ' written, ' +
                    str(len(problems)) + ' refused, ' + str(len(locked)) +
                    ' owned by somebody else' +
                    ''.join(['\n  refused: ' + str(label) + ' - ' + str(why)
                             for label, why in problems[:40]]))

        self.pending = {}
        self.staged_from = {}
        # back to the filtering that was in place before the import isolated
        # the list.  Apply re-reads the model below and a read clears the
        # filters, so the restore is handed to the read to do afterwards.
        self.isolated = False
        self.isolate_btn.Visibility = Visibility.Collapsed
        self.restore_after_read = self.before_isolate
        self.before_isolate = None
        self._update_edit_bar()

        parts = [str(written) + ' change' + ('' if written == 1 else 's') +
                 ' written']
        if locked:
            parts.append(str(len(locked)) + ' skipped, owned by somebody else')
        if problems:
            parts.append(str(len(problems)) + ' would not take')
        self.set_status('. '.join(parts) + '.')

        if problems or locked:
            lines = []
            for label, why in problems[:30]:
                lines.append('  ' + label + '  -  ' + why)
            if locked:
                lines.append('')
                lines.append('Owned by another user, so left alone:')
                for element_id in locked[:30]:
                    lines.append('  element ' + str(element_id))
            fv_ui.prompt(
                self.window, self.palette, 'Some changes were not written',
                str(written) + ' went in. These did not:\n\n' +
                '\n'.join(lines), 'Close', accent='orange')

        # read the model back, so the list shows what is actually there rather
        # than what was asked for
        self.request_read()

    # ------------------------------------------------------------------
    # batch rename
    # ------------------------------------------------------------------

    def _rename_targets(self):
        """The picked rows that can actually be renamed.

        A family row renames the family; a type row renames the type.  A system
        family has no family element behind it, so it is left out rather than
        offered and then refused.
        """
        found = []
        seen = set()
        try:
            picked = list(self.grid.SelectedItems)
        except Exception:
            picked = []
        for row in picked:
            if row is None:
                continue
            key = self._edit_key(row, KEY_NAME)
            if key is None or key in seen:
                continue
            seen.add(key)
            found.append(row)
        return found

    def _names_in_use(self):
        """What names are already taken, so a clash is caught in the preview
        rather than by Revit halfway through writing."""
        taken = {}
        for parent in self.families:
            families = taken.setdefault(('family', parent.category), set())
            families.add(parent.family_name)
            types = taken.setdefault(('type', parent.family_name), set())
            for child in parent.children:
                types.add(child.type_name)
        return taken

    def open_batch_rename(self):
        """What is picked decides what the window is for.

        Pick families only, and it renames families - nothing else on a family
        line means anything, because "(varies)" has no single element behind
        it.  Pick any type, and it is about types: their names and their
        editable parameters, with the families they belong to listed alongside
        for grouping and locked, so a bank of types reads under the family it
        came from without the family being edited by accident.
        """
        rows = self._rename_targets()
        if not rows:
            self.set_status('Pick one or more families or types to rename.')
            return
        import fv_batch_window as batch

        types = [row for row in rows if row.kind != FAMILY_ROW]
        family_only = not types

        keys = [batch.NAME_KEY]
        headings = {batch.NAME_KEY: 'Name'}
        if not family_only:
            for column in self.columns:
                if column.kind == 'param' and column.key:
                    keys.append(column.key)
                    headings[column.key] = column.title or column.key

        lines = []
        by_key = {}
        wanted = list(rows)
        if not family_only:
            # the families the picked types belong to come along for grouping
            seen = set()
            for row in types:
                parent = row.parent
                if parent is None or not parent.family_id:
                    continue
                if parent.family_id in seen:
                    continue
                seen.add(parent.family_id)
                if parent not in wanted:
                    wanted.append(parent)

        for row in wanted:
            key = self._edit_key(row, KEY_NAME)
            if key is None:
                continue
            kind, element_id, _ = key
            group = row.category if kind == 'family' else row.family_name
            values = {}
            editable = set()
            for column_key in keys:
                real = KEY_NAME if column_key == batch.NAME_KEY else column_key
                staged = self.staged(row, real)
                if staged is not None:
                    values[column_key] = staged
                elif column_key == batch.NAME_KEY:
                    values[column_key] = row.label
                else:
                    text = row.cell(column_key) or ''
                    values[column_key] = ('' if text == fv_core.VARIES
                                          else text)
                if self._batch_can_edit(row, column_key, family_only, batch):
                    editable.add(column_key)
            line = batch.Line(kind, element_id, group, values, editable)
            lines.append(line)
            by_key[(kind, element_id)] = row

        handle = None
        try:
            handle = self.uiapp.MainWindowHandle
        except Exception:
            handle = None

        picked = batch.open_batch_rename(
            self.window, handle, self.settings, self.palette, lines, keys,
            headings, self._names_in_use())
        if picked is None:
            self.set_status('Batch rename cancelled. Nothing was staged.')
            return

        staged = 0
        for line, column_key, value in picked:
            row = by_key.get((line.kind, line.element_id))
            if row is None:
                continue
            real_key = KEY_NAME if column_key == batch.NAME_KEY else column_key
            key = self._edit_key(row, real_key)
            if key is None:
                continue
            original = row.label if real_key == KEY_NAME else (
                row.cell(real_key) or '')
            if value == original:
                self.pending.pop(key, None)
                self.staged_from.pop(key, None)
                continue
            self.pending[key] = value
            self.staged_from[key] = 'batch'
            staged += 1

        self._refresh_cells()
        self._update_edit_bar()
        self.set_status(
            str(staged) + ' change' + ('' if staged == 1 else 's') +
            ' staged from the batch rename, shown in green. Nothing is '
            'written until Apply.')

    def _batch_can_edit(self, row, column_key, family_only, batch):
        """Which cells the batch window may write.

        A family line only ever offers its own name.  A type line offers its
        name and the type parameters; a parameter that lives on the instance is
        shown so the row reads properly, and locked, because writing it from
        here would mean writing it to every instance behind that row without
        saying so.
        """
        if row.kind == FAMILY_ROW:
            return column_key == batch.NAME_KEY
        if family_only:
            return False
        if column_key == batch.NAME_KEY:
            return True
        return column_key in self._type_parameters()

    def _type_parameters(self):
        """The parameter columns that live on the type rather than the
        instance, worked out once per read from what the read itself found."""
        if self._type_params is not None:
            return self._type_params
        found = set()
        if self.result is not None:
            found = set(getattr(self.result, 'type_level', set()))
        self._type_params = found
        return found

    # ------------------------------------------------------------------
    # the right click menu on a row
    # ------------------------------------------------------------------

    def on_grid_right_click(self, sender, args):
        row = self._row_under(args.OriginalSource)
        column = self._column_under(args.OriginalSource)
        if row is None or column is None:
            return
        menu = ContextMenu()
        fv_ui.styled(menu, 'ThemedContextMenu')

        def item(text, enabled, handler):
            entry = MenuItem()
            fv_ui.styled(entry, 'ThemedMenuItem')
            entry.Header = text
            entry.IsEnabled = enabled
            if enabled and handler is not None:
                entry.Click += handler
            menu.Items.Add(entry)
            return entry

        editable = self.can_edit(row, column)
        source = args.OriginalSource

        def edit_it(sender_, args_):
            if column.key == fv_model.WORKSET_KEY:
                self.begin_workset_edit(row, column, source)
            else:
                self.begin_edit(row, column, source)

        def clear_it(sender_, args_):
            self.clear_edit(row, column)

        def place_it(sender_, args_):
            self.on_place(None, None)

        if column.key == KEY_NAME:
            item('Rename...', editable, edit_it)
        else:
            item('Edit value...', editable, edit_it)
        if not editable:
            reason = 'read from the model, not typed into it'
            if row.kind == FAMILY_ROW and column.key != KEY_NAME:
                reason = 'a family line has no single element behind it'
            elif row.kind == FAMILY_ROW and row.is_system:
                reason = 'a system family has no family element to rename'
            item('(' + reason + ')', False, None)
        item('Clear staged change',
             self.staged(row, column.key) is not None, clear_it)
        item('Place instance in the active view', self.can_place(row),
             place_it)

        picked = self._rename_targets()
        entry_text = 'Batch rename'
        if picked:
            entry_text = ('Batch rename ' + str(len(picked)) + ' item' +
                          ('' if len(picked) == 1 else 's'))

        def batch_it(sender_, args_):
            self.open_quick_rename()

        def editor_it(sender_, args_):
            self.open_batch_rename()

        item(entry_text, bool(picked), batch_it)
        item('Batch rename editor (cells and parameters)...', bool(picked),
             editor_it)

        menu.PlacementTarget = self.grid
        menu.IsOpen = True
        args.Handled = True

    def _row_under(self, source):
        container = _ancestor_of_type(source, DataGridRow)
        if container is None:
            return None
        try:
            return container.Item
        except Exception:
            return None

    FOLD_OPEN = ('M 0 1 L 14 1 L 14 3 L 0 3 Z M 4 6 L 14 6 L 14 8 L 4 8 Z '
                 'M 4 11 L 14 11 L 14 13 L 4 13 Z')
    FOLD_SHUT = ('M 0 1 L 14 1 L 14 3 L 0 3 Z M 0 6 L 14 6 L 14 8 L 0 8 Z '
                 'M 0 11 L 14 11 L 14 13 L 0 13 Z')

    def on_fold(self, sender, args):
        """One button that flips, rather than two that are each wrong half the
        time."""
        opening = not self._mostly_open()
        for parent in self.families:
            parent.open = opening
        self.rebuild()
        self._paint_fold()

    def _mostly_open(self):
        if not self.families:
            return False
        open_now = len([one for one in self.families if one.open])
        return open_now * 2 >= len(self.families)

    def _paint_fold(self):
        opening = not self._mostly_open()
        try:
            self.fold_btn.ToolTip = 'Expand all' if opening else 'Collapse all'
            self.fold_glyph.Data = Geometry.Parse(
                self.FOLD_OPEN if opening else self.FOLD_SHUT)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # quick batch rename - the toolbar button and its drop-down
    # ------------------------------------------------------------------

    def _arm_rename(self):
        """The button greys out with nothing to rename and lights green the
        moment names are picked, so it is obvious where the tool lives."""
        try:
            count = len(self._rename_targets())
        except Exception:
            count = 0
        try:
            self.rename_toggle.IsEnabled = count > 0
            self.rename_toggle.Tag = 'armed' if count > 0 else None
            if count:
                self.rename_toggle.ToolTip = (
                    'Batch rename the ' + str(count) + ' picked name' +
                    ('' if count == 1 else 's'))
            else:
                self.rename_toggle.ToolTip = ('Batch rename - pick families '
                                              'or types in the list first')
        except Exception:
            pass
        if count == 0 and self.rename_popup is not None:
            try:
                self.rename_popup.IsOpen = False
            except Exception:
                pass
        elif self.rename_popup is not None and self.rename_popup.IsOpen:
            self._quick_preview()

    def open_quick_rename(self):
        """From the right click menu.  The menu is still closing when this
        runs and a StaysOpen=False popup opened now would see that as a click
        away and shut at once, so it opens on the next pass of the
        dispatcher."""
        if not self._rename_targets():
            self.set_status('Pick one or more families or types to rename.')
            return

        def show():
            try:
                self.rename_toggle.IsChecked = True
                self.rename_popup.IsOpen = True
                self._quick_preview()
                self.quick_find.Focus()
            except Exception:
                fv_core.log('quick rename: ' + fv_core.format_exc())

        try:
            self.window.Dispatcher.BeginInvoke(
                DispatcherPriority.Background, Action(show))
        except Exception:
            show()

    def on_rename_toggle(self, sender, args):
        opening = bool(self.rename_toggle.IsChecked)
        self.rename_popup.IsOpen = opening
        if opening:
            self._quick_preview()
            try:
                self.quick_find.Focus()
            except Exception:
                pass

    def on_rename_closed(self, sender, args):
        self.rename_toggle.IsChecked = False

    def on_quick_changed(self, sender, args):
        self._quick_preview()

    def _quick_tools(self):
        return (self.quick_find.Text or '', self.quick_replace.Text or '',
                self.quick_prefix.Text or '', self.quick_suffix.Text or '',
                bool(self.quick_case.IsChecked))

    def _quick_plan(self):
        """The picked names as batch lines, run through the same rules as the
        full window.  Returns (plan, rows by line)."""
        import fv_batch_window as batch
        lines = []
        by_line = {}
        for row in self._rename_targets():
            key = self._edit_key(row, KEY_NAME)
            if key is None:
                continue
            kind, element_id, _ = key
            group = row.category if kind == 'family' else row.family_name
            staged = self.staged(row, KEY_NAME)
            current = staged if staged is not None else row.label
            line = batch.Line(kind, element_id, group,
                              {batch.NAME_KEY: current}, [batch.NAME_KEY])
            lines.append(line)
            by_line[id(line)] = row
        find, replace, prefix, suffix, case = self._quick_tools()
        plan = batch.quick_rename(lines, find, replace, prefix, suffix, case,
                                  self._names_in_use())
        return plan, by_line

    def _quick_preview(self):
        try:
            plan, _ = self._quick_plan()
        except Exception:
            fv_core.log('quick rename preview: ' + fv_core.format_exc())
            return
        picked = len(plan.changes) + len(plan.refused) + plan.unchanged
        self.quick_title.Text = ('Batch rename ' + str(picked) + ' picked name' +
                                 ('' if picked == 1 else 's'))
        self.quick_preview.Text = plan.summary()
        if plan.changes:
            line, new = plan.changes[0]
            import fv_batch_window as batch
            self.quick_sample.Text = (line.old_of(batch.NAME_KEY) + '  ->  ' +
                                      new)
        else:
            self.quick_sample.Text = ''
        self.quick_apply.IsEnabled = bool(plan.changes)

    def on_quick_apply(self, sender, args):
        """Stage, never write: the new names go in green and the edit bar's
        Apply is still the only thing that touches the model."""
        try:
            plan, by_line = self._quick_plan()
        except Exception:
            fv_core.log('quick rename apply: ' + fv_core.format_exc())
            self.set_status('Could not work out the new names - see the log.')
            return
        staged = 0
        for line, new in plan.changes:
            row = by_line.get(id(line))
            if row is None:
                continue
            key = self._edit_key(row, KEY_NAME)
            if key is None:
                continue
            if new == row.label:
                self.pending.pop(key, None)
                self.staged_from.pop(key, None)
                continue
            self.pending[key] = new
            self.staged_from[key] = 'batch'
            staged += 1
        fv_core.log('quick rename staged ' + str(staged) + ', refused ' +
                    str(len(plan.refused)) + ', unchanged ' +
                    str(plan.unchanged))
        self.rename_popup.IsOpen = False
        for box in [self.quick_find, self.quick_replace, self.quick_prefix,
                    self.quick_suffix]:
            box.Text = ''
        self._refresh_cells()
        self._update_edit_bar()
        note = (str(staged) + ' new name' + ('' if staged == 1 else 's') +
                ' staged in green. Nothing is written until Apply.')
        if plan.refused:
            note += (' ' + str(len(plan.refused)) + ' left alone: ' +
                     plan.refused[0][1] + '.')
        self.set_status(note)

    def on_quick_more(self, sender, args):
        self.rename_popup.IsOpen = False
        self.open_batch_rename()

    # ------------------------------------------------------------------
    # the Excel menu
    # ------------------------------------------------------------------

    def on_excel_toggle(self, sender, args):
        self.excel_popup.IsOpen = bool(self.excel_toggle.IsChecked)

    def on_excel_closed(self, sender, args):
        self.excel_toggle.IsChecked = False

    def on_selection_changed(self, sender, args):
        self._arm_rename()
        ids = self._selected_type_ids()
        elements = self._selected_element_ids()
        has = bool(ids) or bool(elements)
        self.select_project_btn.IsEnabled = has
        self.select_view_btn.IsEnabled = has
        # Restore View stays live with nothing picked - the view is isolated
        # and getting it back must not depend on keeping a selection
        self.isolate_view_btn.IsEnabled = has or self.view_isolated

        if not has:
            self.sel_info.Text = 'Pick a family, a type or an element to ' \
                                 'light up the buttons below.'
            return
        if elements:
            self.sel_info.Text = (
                '{0} element{1} picked. The buttons act on those, not on '
                'every instance of their types.'.format(
                    len(elements), '' if len(elements) == 1 else 's'))
            return
        total = 0
        for row in self.rows:
            if row.kind not in (FAMILY_ROW, fv_model.GROUP_ROW,
                                fv_model.INSTANCE_ROW) and row.type_id in ids:
                total += row.count
        self.sel_info.Text = '{0} types picked, {1} elements between them.'.format(
            len(ids), total)

    def can_place(self, row):
        """Which rows carry a place button.

        A type row that came from a loadable family: a system type has nothing
        to place, and a family line is not one type.
        """
        if row is None:
            return False
        if row.kind == FAMILY_ROW:
            return False
        if row.is_system:
            return False
        return bool(row.type_id)

    # ------------------------------------------------------------------
    # Place Instance
    # ------------------------------------------------------------------

    def place_row(self, row):
        if not self.can_place(row):
            return
        if self.pending:
            # placing hands control to Revit's own command, and the window
            # stops being the thing in front of the user; staged edits would
            # be easy to forget about and easy to lose
            answer = fv_ui.prompt(
                self.window, self.palette, 'There are staged changes',
                'Placing hands you over to Revit\'s placement command. The '
                'changes staged here are not written and will still be waiting '
                'when you come back.\n\nCarry on?',
                'Place anyway', 'Cancel', accent='orange')
            if not answer:
                return
        self.set_status('Starting Revit\'s placement command...')
        self._raise('place', {'type_id': row.type_id}, self.on_place_done)

    def on_place_done(self, data):
        name = data.get('family', '') + ' : ' + data.get('name', '')
        self.set_status(
            'Placing ' + name.strip(' :') + '. Revit has the mouse now - '
            'click in the view to place it, and Escape when you are done.')

    def _selected_type_ids(self):
        """The types behind whatever is picked.

        A family gives its types, a type gives itself, a group heading gives
        the types of the elements under it, and an element gives the type it is
        an instance of - so the Select buttons mean the same thing whichever
        level was clicked.
        """
        ids = set()
        try:
            for row in self.grid.SelectedItems:
                if row is None:
                    continue
                if row.kind == FAMILY_ROW:
                    for child in row.children:
                        ids.add(child.type_id)
                elif row.kind == fv_model.GROUP_ROW:
                    for child in row.children:
                        if child.type_id:
                            ids.add(child.type_id)
                elif row.type_id:
                    ids.add(row.type_id)
        except Exception:
            pass
        return ids

    # ------------------------------------------------------------------
    # the two Select buttons
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # isolating in the Revit view
    # ------------------------------------------------------------------

    def on_isolate_view(self, sender, args):
        if self.view_isolated:
            self.set_status('Putting the view back...')
            self._raise('restore_view', {}, self.on_restore_view_done)
            return
        elements = self._selected_element_ids()
        ids = self._selected_type_ids()
        if not ids and not elements:
            return
        self.set_status('Zooming to them and isolating the view...')
        self._raise('isolate', {
            'element_ids': elements,
            'type_ids': list(ids),
            'ignore_nested': as_bool(self.settings, 'ignore_nested'),
            'phase_id': self.phase_id,
            'phase_mode': self.settings.get('phase_mode', 'existing'),
        }, self.on_isolate_done)

    def on_isolate_done(self, data):
        count = data.get('count', 0)
        if not count:
            self.set_status(
                'None of the picked types have anything in ' +
                (data.get('view_name') or 'the active view') +
                ', so there was nothing to isolate.')
            return
        self.view_isolated = True
        self._paint_isolate_button()
        self.set_status(
            str(count) + ' element' + ('' if count == 1 else 's') +
            ' isolated in ' + (data.get('view_name') or 'the active view') +
            '. Restore View puts everything back.')

    def on_restore_view_done(self, data):
        self.view_isolated = False
        self._paint_isolate_button()
        self.on_selection_changed(None, None)
        self.set_status('Temporary Hide/Isolate reset on ' +
                        (data.get('view_name') or 'the active view') + '.')

    def _paint_isolate_button(self):
        """One button, two jobs, and it says which one it is on."""
        try:
            if self.view_isolated:
                self.isolate_view_btn.Content = 'Restore View'
                self.isolate_view_btn.ToolTip = (
                    'Reset Temporary Hide/Isolate on the active view')
                self.isolate_view_btn.SetResourceReference(
                    FrameworkElement.StyleProperty, 'BtnDanger')
            else:
                self.isolate_view_btn.Content = 'Isolate in View'
                self.isolate_view_btn.ToolTip = (
                    'Zoom to these elements in the active view, then isolate '
                    'them')
                self.isolate_view_btn.SetResourceReference(
                    FrameworkElement.StyleProperty, 'BtnGhost')
        except Exception:
            pass

    def on_select_project(self, sender, args):
        self._select('project')

    def on_select_view(self, sender, args):
        self._select('view')

    def _selected_element_ids(self):
        """The elements picked in their own right.

        Picking element rows means those elements and not every instance of
        their types - otherwise picking one door out of forty would select all
        forty, which is the opposite of what picking one of them says.
        A group heading counts as picking every element under it.
        """
        found = []
        seen = set()
        try:
            picked = list(self.grid.SelectedItems)
        except Exception:
            picked = []
        for row in picked:
            if row is None:
                continue
            if row.kind == fv_model.INSTANCE_ROW:
                rows = [row]
            elif row.kind == fv_model.GROUP_ROW:
                rows = [one for one in row.children
                        if one.kind == fv_model.INSTANCE_ROW]
            else:
                continue
            for one in rows:
                if one.element_id and one.element_id not in seen:
                    seen.add(one.element_id)
                    found.append(one.element_id)
        return found

    def _select(self, scope):
        elements = self._selected_element_ids()
        ids = self._selected_type_ids()
        if not ids and not elements:
            return
        self.set_status('Selecting...')
        payload = {
            'element_ids': elements,
            'type_ids': list(ids),
            'scope': scope,
            'ignore_nested': as_bool(self.settings, 'ignore_nested'),
            'phase_id': self.phase_id,
            'phase_mode': self.settings.get('phase_mode', 'existing'),
            'zoom': as_bool(self.settings, 'zoom_after_select'),
        }
        self._raise('select', payload, self.on_select_done)

    def on_select_done(self, data):
        count = data.get('count', 0)
        where = 'the whole project'
        if data.get('scope') == 'view':
            where = 'the active view'
            if data.get('view_name'):
                where += ' (' + data['view_name'] + ')'
        if data.get('picked'):
            # elements were picked in their own right, so the scope did not
            # decide what was selected and saying it did would be a lie
            where = 'the model'
        if count:
            message = '{0} elements selected in {1}.'.format(count, where)
        else:
            message = 'Nothing to select: no instances of those types in {0}' \
                      ' under the current phase filter.'.format(where)
        self.set_status(message)
        mode = self.settings.get('show_results', 'auto')
        if mode == 'always' or (mode == 'auto' and not count):
            fv_ui.prompt(self.window, self.palette, 'Select all instances',
                         message, 'Close',
                         accent='orange' if not count else 'blue')

    # ------------------------------------------------------------------
    # export
    # ------------------------------------------------------------------

    def on_export(self, sender, args):
        """Out as a real .xlsx, so it can be edited and read back in.

        A CSV cannot carry which cells are safe to edit, and it loses a type
        mark of "007" the moment Excel opens it.
        """
        if not self._excel_ready():
            return
        from Microsoft.Win32 import SaveFileDialog
        dialog = SaveFileDialog()
        dialog.Filter = 'Excel workbook|*.xlsx'
        dialog.FileName = (self.doc_title or 'Family Viewer') + ' - families.xlsx'
        try:
            answer = dialog.ShowDialog()
        except Exception:
            answer = False
        if not answer:
            return
        try:
            count = self._write_workbook(dialog.FileName)
        except Exception:
            fv_ui.prompt(self.window, self.palette, 'The list was not written',
                         fv_core.format_exc(), 'Close', accent='orange')
            return
        self.set_status(
            str(count) + ' rows written to ' + dialog.FileName +
            '. Edit the orange cells, then Import to bring them back.')
        self._offer_folder(dialog.FileName, count)

    def _offer_folder(self, path, count):
        answer = fv_ui.prompt(
            self.window, self.palette, 'Workbook written',
            str(count) + ' rows written to\n' + path + '\n\n'
            'Orange cells can be edited and brought back in with Import. '
            'Open the folder?',
            'Open folder', 'Not now', accent='green')
        if not answer:
            return
        fv_ui.open_folder(path)

    def _excel_ready(self):
        """The zip assembly is asked for at the point of use, so a Revit that
        does not have it costs the export and nothing else - rather than
        killing the tool at module load, which is what shipping the import at
        the top of fv_excel did in 1.3.0."""
        if fv_excel.available():
            return True
        fv_ui.prompt(
            self.window, self.palette, 'Excel is not available here',
            'This Revit will not give up System.IO.Compression, which is what '
            'writes the workbook. Everything else in Family Viewer still '
            'works.\n\n' + fv_core.format_exc(), 'Close', accent='orange')
        return False

    def _export_headings(self):
        headings = [fv_excel.ID_HEAD, fv_excel.KIND_HEAD, fv_excel.FAMILY_HEAD,
                    fv_excel.TYPE_HEAD, fv_excel.CATEGORY_HEAD,
                    fv_excel.COUNT_HEAD]
        headings.extend([column.key for column in self.columns
                         if column.kind == 'param' and column.key])
        return headings

    def _write_workbook(self, path):
        """Every row, including any past the ones the table draws - the run is
        never silently truncated."""
        headings = self._export_headings()
        params = headings[6:]
        rows = []
        for parent in self.shown:
            row = [str(parent.family_id), 'family', parent.family_name, '',
                   parent.category, str(parent.count)]
            for name in params:
                row.append(parent.cell(name))
            rows.append(row)
            for child in parent.children:
                row = [str(child.type_id), 'type', child.family_name,
                       child.type_name, child.category, str(child.count)]
                for name in params:
                    row.append(child.cell(name))
                rows.append(row)

        notes = ['Exported from ' + (self.doc_title or 'the model') + '.']
        if self.scope == 'view':
            notes.append('Scope: the active view' +
                         ((' (' + self.view_name + ')') if self.view_name
                          else '') + '.')
        elif self.scope == 'all':
            notes.append('Scope: every family, placed or not.')
        fv_excel.write(path, headings, rows,
                       'RevoBIM Family Viewer - families and types', notes)
        return len(rows)

    def on_import(self, sender, args):
        """Read an export back and stage what changed.

        Nothing is written here: the differences become staged changes, in
        orange, and Apply is still the only thing that touches the model.
        """
        if not self.result:
            return
        if not self._excel_ready():
            return
        from Microsoft.Win32 import OpenFileDialog
        dialog = OpenFileDialog()
        dialog.Filter = 'Excel workbook|*.xlsx'
        try:
            answer = dialog.ShowDialog()
        except Exception:
            answer = False
        if not answer:
            return
        try:
            headings, rows = fv_excel.read(dialog.FileName)
        except Exception:
            fv_ui.prompt(self.window, self.palette,
                         'That workbook could not be read',
                         fv_core.format_exc(), 'Close', accent='orange')
            return
        self._stage_from_workbook(headings, rows, dialog.FileName)

    def _stage_from_workbook(self, headings, rows, path=''):
        """Stage what a workbook changes.  NOTHING is written here.

        The comparison is fv_excel.plan_import, a plain function the bench
        proves.  This only stages its result - in teal, so it reads apart from
        anything typed by hand - highlights the families holding a change,
        isolates the list to them, and says what happened.  Apply is still the
        only thing that writes, and it is not called from anywhere on this path.
        """
        if not headings or fv_excel.ID_HEAD not in headings:
            fv_ui.prompt(
                self.window, self.palette, 'That is not a Family Viewer export',
                'The first sheet has no "' + fv_excel.ID_HEAD + '" column, so '
                'there is no way to tell which element each row belongs to.\n\n'
                'Export the list again, edit that file, and import it back.',
                'Close', accent='orange')
            return

        plan = fv_excel.plan_import(headings, rows, self._known_rows(),
                                    self._edit_key)
        for key, value, target, head in plan.changes:
            self.pending[key] = value
            self.staged_from[key] = 'import'

        self._update_edit_bar()
        if plan.changes:
            # isolate to what the workbook changed, whatever the category, the
            # phase and the column filters happen to be set to
            self.isolate_changes()
        else:
            self._refresh_cells()

        self.set_status(
            str(len(plan.changes)) + ' change' +
            ('' if len(plan.changes) == 1 else 's') + ' staged from the '
            'workbook across ' + str(len(plan.families)) + ' famil' +
            ('y' if len(plan.families) == 1 else 'ies') + ', ' +
            str(plan.unchanged) + ' rows unchanged, ' + str(plan.failed) +
            ' not imported. Nothing is written until Apply.')
        self.last_import = fv_excel.summary(plan, path)
        fv_core.log('import: ' + str(plan.rows_read) + ' rows, ' +
                    str(len(plan.changes)) + ' changes staged, ' +
                    str(plan.unchanged) + ' unchanged, ' + str(plan.failed) +
                    ' not imported, from ' + str(path) + '\n  headings: ' +
                    ', '.join([str(head) for head in headings]))
        fv_ui.prompt(self.window, self.palette, 'Workbook imported',
                     self.last_import, 'Close',
                     accent='orange' if plan.failed else 'green')

    def _known_rows(self):
        """Every row an export could have come from, keyed as it was exported.

        From the WHOLE read, not the rows on screen: a row hidden by a filter
        is still in the model and still importable, and matching against the
        screen called every one of them "not found".
        """
        known = {}
        for parent in self.families:
            known[('family', parent.family_id)] = parent
            for child in parent.children:
                known[('type', child.type_id)] = child
        for rows in self.instance_rows.values():
            for row in rows:
                known[('instance', row.element_id)] = row
        return known

    # ------------------------------------------------------------------
    # chrome, theme, settings
    # ------------------------------------------------------------------

    def on_close_click(self, sender, args):
        try:
            self.window.Close()
        except Exception:
            pass

    def on_full_click(self, sender, args):
        if self.chrome is not None:
            self.chrome.toggle_full()

    def on_theme_click(self, sender, args):
        self.palette = theme.other(self.palette)
        self.settings['theme'] = self.palette
        fv_core.save_settings(self.settings)
        self._repaint_theme()
        selected = self._selected_type_ids()
        try:
            self.grid.Items.Refresh()
        except Exception:
            pass
        self._restore_selection(selected)

    def on_settings_click(self, sender, args):
        import fv_settings_window
        changed = fv_settings_window.open_settings(
            self.window, self.settings, self.phases, self.palette)
        if not changed:
            return
        self.palette = theme.resolve(
            self.settings.get('theme', theme.FOLLOW), theme.revit_canvas())
        self._repaint_theme()
        self._apply_scale()
        self._paint_images_toggle()
        try:
            self.settle.Interval = TimeSpan.FromMilliseconds(
                as_int(self.settings, 'settle_ms', 200, 10000))
        except Exception:
            pass
        self.previews = {}
        self.request_lists()

    def _repaint_theme(self):
        fv_ui.set_theme(self.theme_host, self.palette)
        # the washes differ between the palettes, so they are worked out again
        self._tints = {}
        label = theme.other(self.palette).capitalize()
        for chip in (self.theme_chip, self.dock_theme_chip):
            if chip is not None:
                chip.Content = label

    def _set_dock_chips(self, side):
        if self.dock_left is None:
            return
        self.dock_left.IsChecked = (side == 'left')
        self.dock_right.IsChecked = (side == 'right')
        self.dock_float.IsChecked = (side not in ('left', 'right'))

    def _dock_state_changed(self, side, full):
        self._set_dock_chips(side)
        self.settings['dock_side'] = side
        fv_core.save_settings(self.settings)

    def on_dock_left(self, sender, args):
        self.chrome.dock('left')

    def on_dock_right(self, sender, args):
        self.chrome.dock('right')

    def on_dock_float(self, sender, args):
        self.chrome.undock()
        self._set_dock_chips('float')

    def on_dock_pane(self, sender, args):
        """Move into Revit's own dockable pane.

        The pane is registered by startup.py at the root of the extension.
        Where that has not run - a first install where Revit has not been
        restarted, or an extension whose own startup.py was kept instead -
        there is nothing to move into, and saying so plainly is better than a
        button that does nothing.
        """
        if self.on_move_to_pane is None:
            fv_ui.prompt(
                self.window, self.palette,
                'The Revit pane is not registered yet',
                'Revit only lets an addin create a dockable pane while it is '
                'starting up, so the pane is registered from the '
                'extension\'s own startup.py.\n\n'
                'Paste the block from startup_block.py (in this tool\'s '
                'folder) into the bottom of RevoBIM PY.extension\\startup.py, '
                'then restart Revit. It ships separately because startup.py '
                'is shared by the whole extension.\n\n'
                'Until then the Left and Right chips snap the window to the '
                'edge of Revit, which is close but is not a real pane.',
                'Close', accent='orange')
            return
        self.on_move_to_pane()

    def _set_busy(self, busy):
        try:
            self.progress.Visibility = Visibility.Visible if busy else Visibility.Collapsed
            self.progress.IsIndeterminate = busy
        except Exception:
            pass
        # While a job runs the BODY and the header's other controls go deaf:
        # pumping the dispatcher also pumps input, and a click landing mid-run
        # has torn a callback away from an open job before.  The shrink button
        # stays live - putting the window away to watch Revit work is exactly
        # what it is for, and it touches nothing but the window's geometry.
        for target in [self.body, self.theme_chip, self.settings_chip,
                       self.dock_chip_panel, self.dock_pane_btn,
                       self.dock_theme_chip, self.dock_settings_chip]:
            if target is None:
                continue
            try:
                target.IsHitTestVisible = not busy
            except Exception:
                pass
        if self.drawer is not None:
            self.drawer.busy = busy

    def _mark_refresh(self, dirty):
        """The icon grows an orange dot the moment the model moves on, so
        "change something in Revit, then refresh" needs no guesswork."""
        try:
            self.refresh_dot.Visibility = (
                Visibility.Visible if dirty else Visibility.Collapsed)
            self.refresh_glyph.SetResourceReference(
                ShapePath.FillProperty,
                'AccentOrange' if dirty else 'FgMuted')
            self.refresh_btn.ToolTip = (
                'The model has changed - re-read it  (F5)' if dirty
                else 'Re-read the model  (F5)')
        except Exception:
            pass

    def on_refresh(self, sender, args):
        self.request_lists()

    def reset_filters(self):
        """Every column search and tick filter cleared.

        A filter is about the list that is on screen, and a re-read replaces
        that list.  Carrying one across is how a refresh looked as though it
        had not worked: the rows were read, and then hidden by a filter set
        against a reading that no longer existed.
        """
        for column in self.columns:
            column.search = ''
            column.allowed = None
            try:
                if column.search_box is not None:
                    column.search_box.Text = ''
            except Exception:
                pass
            try:
                if column.caret is not None:
                    column.caret.IsChecked = False
                if column.popup is not None:
                    column.popup.IsOpen = False
            except Exception:
                pass
        try:
            if self.global_search.Text:
                self.global_search.Text = ''
        except Exception:
            pass

    # ------------------------------------------------------------------
    # watching the model
    # ------------------------------------------------------------------

    def on_revit_theme_changed(self, sender, args):
        """Follow Revit's canvas while open, when following is the setting."""
        if self.closed:
            return
        if self.settings.get('theme', theme.FOLLOW) != theme.FOLLOW:
            return
        wanted = theme.resolve(theme.FOLLOW, theme.revit_canvas())
        if wanted == self.palette:
            return
        self.palette = wanted
        self._repaint_theme()
        self._refresh_cells()

    def on_document_changed(self, sender, args):
        """Sets a flag only.  DocumentChanged must not read the document."""
        if self.closed:
            return
        self.dirty = True
        if as_bool(self.settings, 'watch_model'):
            try:
                self.settle.Stop()
                self.settle.Start()
            except Exception:
                pass
        else:
            self._mark_refresh(True)

    def _settle_tick(self, sender, args):
        try:
            self.settle.Stop()
        except Exception:
            pass
        if self.closed or self.busy:
            return
        if as_bool(self.settings, 'watch_model') and self.dirty:
            self.request_read()

    # ------------------------------------------------------------------
    # keys and closing
    # ------------------------------------------------------------------

    def on_key(self, sender, args):
        if args.Key == Key.F5:
            self.on_refresh(sender, args)
            args.Handled = True
        elif args.Key == Key.F11 and self.chrome is not None:
            self.chrome.toggle_full()
            args.Handled = True
        elif args.Key == Key.Escape:
            if self.chrome is not None and self.chrome.full:
                self.chrome.toggle_full(False)
                args.Handled = True

    def on_closed(self, sender, args):
        self.closed = True
        try:
            self.preview_timer.Stop()
        except Exception:
            pass
        try:
            self.debounce.Stop()
        except Exception:
            pass
        try:
            self.settle.Stop()
        except Exception:
            pass
        try:
            if self.chrome is not None:
                self.chrome.close()
        except Exception:
            pass
        try:
            self.uiapp.Application.DocumentChanged -= self.on_document_changed
        except Exception:
            pass
        fv_core.save_settings(self.settings)
