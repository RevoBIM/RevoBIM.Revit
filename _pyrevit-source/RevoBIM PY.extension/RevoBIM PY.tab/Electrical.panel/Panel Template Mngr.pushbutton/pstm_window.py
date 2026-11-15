# -*- coding: utf-8 -*-
"""RevoBIM PY - Panel Template Mngr: the window.

Modeless and owned by Revit's main window, so Revit stays fully navigable and
editable with the manager open, and the manager floats above it rather than
slipping behind.  Nothing is written to the model until Apply (or Create, Delete
or Merge on the duplicator tab) is pressed, and every write goes out through an
ExternalEvent.

Runs on IronPython 2.7 and IronPython 3: no f-strings, no print statements.
"""

import pstm_clr                                                  # noqa: F401
from System import Action
from System.Collections.Generic import List
from System.Windows import FontWeights, Visibility, FrameworkElement
from System.Windows.Input import Key
from System.Windows.Controls import ComboBox, Button
from System.Windows.Controls.Primitives import ToggleButton, Selector
from System.Windows.Threading import DispatcherPriority

import pstm_core as core
import pstm_model as model
import pstm_ops as ops
import pstm_grid as grid
import pstm_ui as ui
import pstm_drawer as drawer_mod
import theme as theme_mod
from settings_window import SettingsWindow


# The persistent engine keeps this module loaded between clicks, so the live
# window is parked here - without a reference somewhere long lived, a modeless
# window is collected out from under the user.
ACTIVE = None

# name -> which edges of the window that grip moves (left, top, right, bottom)
GRIPS = {
    'GripNW': (True, True, False, False),
    'GripN': (False, True, False, False),
    'GripNE': (False, True, True, False),
    'GripW': (True, False, False, False),
    'GripE': (False, False, True, False),
    'GripSW': (True, False, False, True),
    'GripS': (False, False, False, True),
    'GripSE': (False, False, True, True),
}

ALL_TYPES = '(All types)'
NO_PARAM = '(none)'
DROP_COLUMN = '(remove this column)'


def param_key(index):
    return 'p{0}'.format(index)


def param_index(key):
    text = str(key or '')
    if not text.startswith('p') or not text[1:].isdigit():
        return None
    return int(text[1:])


# Header controls that go deaf while a job runs.  The shrink button is the one
# deliberately left off: shrinking touches only the window's own geometry.
BUSY_DEAF = ('SettingsButton', 'ThemeChip', 'FullScreenButton', 'CloseButton')


class ManagerWindow(object):

    # =====================================================================
    # set up
    # =====================================================================

    def __init__(self, uiapp, doc):
        self.uiapp = uiapp
        self.doc = doc
        self.settings = core.load_settings()
        self.palette = self.settings.get('theme', 'dark')

        self.window = ui.load_window('PanelScheduleTemplateManager.xaml', self.palette)
        self.w = self.window
        self.full = ui.FullScreen(self.window)

        self.data = model.ModelData()
        self.headers = {}
        self.col_names = core.initial_columns(self.settings)

        self.display_to_id = {}
        self.id_to_display = {}
        self.visible_rows = []
        self.template_view = []
        self.sort_key = 'panel'
        self.sort_desc = False
        self.dup_source = None
        self.slot_items = []            # [(slots, display)] in list order
        self.slot_lookup = {}           # display -> slots
        self.busy = False
        self._populating = False
        self._active_filter = None
        self._grip_handlers = []
        self._type_note = ''

        self.handler, self.event = ops.make_event()
        self.handler.doc = doc
        self.handler.on_complete = self._job_done
        self._pending_label = ''
        self._apply_wanted = {}
        self._editing_name = ''

        self._build_chrome()
        self._build_columns()
        self._wire()
        self.refresh(first=True)

    # -- chrome -----------------------------------------------------------
    def _build_chrome(self):
        w = self.w
        try:
            w.FindName('VersionText').Text = 'v' + core.__version__
        except Exception:
            pass
        ui.set_image(w.FindName('ToolIcon'), 'icon.png')
        self._set_theme_chip()

        header = w.FindName('HeaderBar')
        header.MouseLeftButtonDown += self._header_click
        # before _wire, so its key handler is attached ahead of _on_key
        self.drawer = drawer_mod.Drawer(self.window)
        self._wire_grips()
        self._set_full_glyph()

    def _set_theme_chip(self):
        try:
            other = theme_mod.other(self.palette)
            self.w.FindName('ThemeChip').Content = other.capitalize()
        except Exception:
            pass

    def _wire_grips(self):
        """Carry the window's own resizing.

        WPF's resize border does not fire on a borderless AllowsTransparency
        window - there is nothing hit testable in the transparent frame - so the
        window could not be stretched at all until these went on.
        """
        for name, edges in GRIPS.items():
            try:
                thumb = self.w.FindName(name)
                if thumb is None:
                    continue
                handler = self._make_grip(*edges)
                self._grip_handlers.append(handler)
                thumb.DragDelta += handler
            except Exception:
                pass

    def _make_grip(self, left, top, right, bottom):
        def _drag(sender, args):
            window = self.window
            if self.drawer.parked:
                return
            try:
                # dragging an edge is a deliberate exit from full screen
                if self.full.is_full:
                    self.full.saved = None
                    self._set_full_glyph()
                dx = args.HorizontalChange
                dy = args.VerticalChange
                if left:
                    wide = window.Width - dx
                    if wide >= window.MinWidth:
                        window.Left = window.Left + dx
                        window.Width = wide
                if right:
                    wide = window.Width + dx
                    if wide >= window.MinWidth:
                        window.Width = wide
                if top:
                    tall = window.Height - dy
                    if tall >= window.MinHeight:
                        window.Top = window.Top + dy
                        window.Height = tall
                if bottom:
                    tall = window.Height + dy
                    if tall >= window.MinHeight:
                        window.Height = tall
            except Exception:
                pass
        return _drag

    def _set_full_glyph(self):
        """One square for go full screen, two for come back."""
        try:
            full = self.full.is_full
            self.w.FindName('MaxGlyph').Visibility = \
                Visibility.Collapsed if full else Visibility.Visible
            self.w.FindName('RestoreGlyph').Visibility = \
                Visibility.Visible if full else Visibility.Collapsed
        except Exception:
            pass

    def _header_click(self, sender, args):
        # A parked bar belongs to the drawer even while a job runs: a double
        # click brings the window back.  It is only dragged when no job is
        # running - DragMove runs a modal loop, and one of those inside Revit's
        # API context is not something to start mid transaction.
        if self.drawer.on_header_down(args, can_drag=not self.busy):
            return
        if self.busy:
            return
        try:
            if args.ClickCount == 2:
                self.full.toggle()
                self._set_full_glyph()
                return
            if self.full.is_full:
                self.full.saved = None
                self._set_full_glyph()
            self.window.DragMove()
        except Exception:
            pass

    # -- events -----------------------------------------------------------
    def _wire(self):
        w = self.w
        w.FindName('CloseButton').Click += self._close
        w.FindName('ThemeChip').Click += self._toggle_theme
        w.FindName('FullScreenButton').Click += self._toggle_full
        w.FindName('SettingsButton').Click += self._open_settings
        w.FindName('RefreshButton').Click += self._on_refresh
        w.FindName('RegenerateButton').Click += self._on_regenerate
        w.FindName('ApplyButton').Click += self._on_apply

        w.FindName('TemplateTypeCombo').SelectionChanged += self._on_template_filter
        w.FindName('TemplateFilterCombo').SelectionChanged += self._on_template_filter
        w.FindName('TemplateSearchBox').TextChanged += self._on_template_search
        w.FindName('EditTemplateItem').Click += self._on_edit_template
        w.FindName('CopyTemplateNameItem').Click += self._on_copy_template_name
        w.FindName('PanelSearchBox').TextChanged += self._on_any_filter
        w.FindName('ClearFiltersButton').Click += self._on_clear_filters
        w.FindName('AutoAssignAllButton').Click += self._on_auto_assign_all
        w.FindName('AutoAssignSelectedButton').Click += self._on_auto_assign_selected
        w.FindName('ResetChangesButton').Click += self._on_reset

        w.FindName('DupSearchBox').TextChanged += self._on_dup_filter
        w.FindName('UnusedOnlyCheck').Click += self._on_dup_filter
        w.FindName('DupUseFiltersCheck').Click += self._on_dup_filter
        w.FindName('DeleteTemplatesButton').Click += self._on_delete
        w.FindName('MergeTemplatesButton').Click += self._on_merge
        w.FindName('RenameTemplatesButton').Click += self._on_rename
        w.FindName('DuplicateButton').Click += self._on_duplicate
        w.FindName('CreateButton').Click += self._on_create
        w.FindName('SlotAllButton').Click += self._slots_all
        w.FindName('SlotNoneButton').Click += self._slots_none
        w.FindName('SlotCommonButton').Click += self._slots_common
        w.FindName('DupBaseName').TextChanged += self._dup_preview
        w.FindName('DupSinglePhaseCheck').Click += self._on_single_phase

        w.FindName('SlotList').SelectionChanged += self._dup_preview

        grid_ctrl = w.FindName('PanelGrid')
        grid_ctrl.Sorting += self._on_sort
        grid_ctrl.SelectionChanged += self._on_panel_selection

        tpl_grid = w.FindName('TemplateGrid')
        tpl_grid.SelectionChanged += self._on_template_selection

        self.window.PreviewKeyDown += self._on_key
        self.window.Closed += self._on_closed

    @staticmethod
    def _make_routed(fn):
        from System.Windows import RoutedEventHandler
        return RoutedEventHandler(fn)

    @staticmethod
    def _make_selection(fn):
        from System.Windows.Controls import SelectionChangedEventHandler
        return SelectionChangedEventHandler(fn)

    # =====================================================================
    # columns
    # =====================================================================

    def _filter_id(self, key):
        """What a column's filter belongs to: a parameter, or a fixed column.

        Keyed by parameter name rather than column key, so adding or removing a
        column - which shifts every later index - does not hand one column's
        filter to another.
        """
        index = param_index(key)
        if index is not None and index < len(self.col_names):
            return 'param:' + (self.col_names[index] or '')
        return 'fixed:' + str(key)

    def _snapshot_filters(self):
        snap = {}
        for key, header in self.headers.items():
            text = ''
            if header.search_box is not None:
                text = header.search_box.Text or ''
            snap[self._filter_id(key)] = (text, header.allowed)
        return snap

    def _restore_filters(self, snap):
        if not snap:
            return
        for key, header in self.headers.items():
            saved = snap.get(self._filter_id(key))
            if not saved:
                continue
            text, allowed = saved
            header._suppress = True
            try:
                if header.search_box is not None:
                    header.search_box.Text = text
            finally:
                header._suppress = False
            header.allowed = allowed
            header._mark()

    def _build_columns(self):
        # The two cell delegates are kept on the window: they are attached to
        # the DataTemplate factory, and nothing else holds them alive.
        self._combo_loaded_handler = self._make_routed(self._combo_loaded)
        self._combo_changed_handler = self._make_selection(self._combo_changed)

        self.text_conv = grid.RowConverter(self.cell_text)
        self.back_conv = grid.RowConverter(self.cell_back)
        self.fore_conv = grid.RowConverter(self.cell_fore)
        self.bold_conv = grid.RowConverter(self.cell_bold)

        self.tpl_text_conv = grid.RowConverter(self.tpl_text)
        self.tpl_back_conv = grid.RowConverter(self.tpl_back)
        self.tpl_fore_conv = grid.RowConverter(self.tpl_fore)

        panel_grid = self.w.FindName('PanelGrid')
        keep_filters = self._snapshot_filters()
        panel_grid.Columns.Clear()
        self.headers = {}

        # (key, heading, star share, minimum px, searchable, kind)
        specs = [('panel', 'Panel', 1.15, 120, True, None),
                 ('template', 'Panel template used', 2.3, 195, True, None)]
        for index in range(len(self.col_names)):
            specs.append((param_key(index), '', 1.25, 120, True, 'param'))
        specs.append(('note', 'Auto Assign', 1.75, 150, False, None))

        for key, title, star, min_width, searchable, kind in specs:
            header = grid.ColumnHeader(
                key, title, self._on_any_filter,
                on_filter_open=self._open_tick_filter if key != 'note' else None,
                param_items=(self.data.param_names if kind == 'param' else None),
                on_param_change=self._on_param_pick if kind == 'param' else None,
                searchable=searchable)
            self.headers[key] = header
            if kind == 'param':
                header.set_param(self.col_names[param_index(key)] or NO_PARAM)
            if key == 'template':
                cell = grid.combo_cell_template(
                    self.back_conv, key,
                    self._combo_loaded_handler, self._combo_changed_handler)
            else:
                cell = grid.text_cell_template(self.text_conv, self.back_conv,
                                               self.fore_conv, key, self.bold_conv)
            panel_grid.Columns.Add(
                grid.make_column(header.content, cell, None, key,
                                 min_width=min_width, star=star))

        # the green + on the end adds another parameter column
        add_button = Button()
        add_button.Content = '+'
        add_button.ToolTip = 'Add another parameter column'
        add_button.Click += self._on_add_column
        try:
            add_button.SetResourceReference(Button.StyleProperty, 'AddButton')
        except Exception:
            pass
        self._add_button = add_button
        panel_grid.Columns.Add(
            grid.make_column(add_button,
                             grid.text_cell_template(self.text_conv, self.back_conv,
                                                     self.fore_conv, 'add'),
                             40, 'add', min_width=40, sortable=False))

        self._restore_filters(keep_filters)
        # (b) a sort on a parameter column means nothing once the columns move
        if param_index(self.sort_key) is not None:
            self.sort_key = 'panel'
            self.sort_desc = False

        tpl_grid = self.w.FindName('TemplateGrid')
        tpl_grid.Columns.Clear()
        for key, title, star, min_width in [('name', 'Template name', 2.4, 210),
                                            ('type', 'Schedule type', 1.0, 115),
                                            ('config', 'Configuration', 1.25, 135),
                                            ('slots', 'Slots', 0.55, 60),
                                            ('used', 'Used by', 0.8, 84),
                                            ('default', 'Default', 0.6, 68)]:
            cell = grid.text_cell_template(self.tpl_text_conv, self.tpl_back_conv,
                                           self.tpl_fore_conv, key)
            column = grid.make_column(title, cell, None, key,
                                      min_width=min_width, star=star)
            tpl_grid.Columns.Add(column)

    def _param_choices(self):
        choices = [NO_PARAM]
        if len(self.col_names) > 2:
            choices.append(DROP_COLUMN)
        choices.extend(self.data.param_names)
        return choices

    def _rebuild_param_items(self):
        for index in range(len(self.col_names)):
            header = self.headers.get(param_key(index))
            if header is None or header.param_combo is None:
                continue
            header._suppress = True
            try:
                header.param_combo.Items.Clear()
                for name in self._param_choices():
                    header.param_combo.Items.Add(name)
            finally:
                header._suppress = False
            header.set_param(self.col_names[index] or NO_PARAM)

    def _on_add_column(self, sender, args):
        self.col_names.append('')
        self._save_columns()
        self._build_columns()
        self._rebuild_param_items()
        self.apply_filters()
        self.status('Added a parameter column - pick what goes in it from its '
                    'heading.')

    def _save_columns(self):
        self.settings['columns'] = '|'.join(self.col_names)
        core.save_settings(self.settings)

    # =====================================================================
    # brushes
    # =====================================================================

    def brush(self, key):
        try:
            found = self.window.Resources[key]
            if found is not None:
                return found
        except Exception:
            pass
        return theme_mod.brush(theme_mod.hex_of(self.palette, key))

    # =====================================================================
    # cell content - panels
    # =====================================================================

    def cell_text(self, row, key):
        if row is None:
            return ''
        if key == 'panel':
            return row.name
        if key == 'template':
            return row.display_template()
        if key == 'note':
            if row.locked:
                return 'LOCKED - {0}'.format(row.locked)
            bits = []
            if row.calc_slots:
                bits.append('{0} slots'.format(row.calc_slots))
            if row.note:
                bits.append(row.note)
            return '  -  '.join(bits)
        index = param_index(key)
        if index is not None and index < len(self.col_names):
            name = self.col_names[index]
            if not name:
                return ''
            return row.value(name)
        return ''

    def _state(self, row):
        if row is None:
            return ''
        if row.locked:
            return 'locked'
        if row.status == 'review':
            return 'review'
        if row.changed:
            return 'changed'
        if row.status == 'multi':
            return 'multi'
        if row.note and row.note.endswith('already right'):
            return 'matched'
        return ''

    def cell_back(self, row, key):
        state = self._state(row)
        if state == 'locked':
            return self.brush('UnusedBg')
        if state == 'review':
            return self.brush('ReviewBg')
        if state in ('changed', 'multi') and key in ('template', 'note'):
            return self.brush('ChangedBg')
        if state == 'matched' and key in ('template', 'note'):
            return self.brush('MatchedBg')
        return None

    def cell_fore(self, row, key):
        state = self._state(row)
        if state == 'locked':
            return self.brush('OrangeBrush') if key == 'note' \
                else self.brush('MutedBrush')
        if state == 'review':
            return self.brush('RedBrush')
        if state in ('changed', 'multi') and key in ('template', 'note'):
            return self.brush('OrangeBrush')
        if state == 'matched' and key == 'note':
            return self.brush('GreenBrush')
        return self.brush('TextBrush')

    def cell_bold(self, row, key):
        state = self._state(row)
        if state in ('changed', 'multi', 'review') and key in ('template', 'note', 'panel'):
            return FontWeights.SemiBold
        return FontWeights.Normal

    # =====================================================================
    # cell content - templates
    # =====================================================================

    def tpl_text(self, tpl, key):
        if tpl is None:
            return ''
        if key == 'name':
            return tpl.name
        if key == 'type':
            return tpl.schedule_type
        if key == 'config':
            return tpl.config_pretty
        if key == 'slots':
            return str(tpl.slots or '')
        if key == 'used':
            if tpl.used_count == 0:
                return 'not used'
            if tpl.used_count == 1:
                return '1 panel'
            return '{0} panels'.format(tpl.used_count)
        if key == 'default':
            return 'default' if tpl.is_default else ''
        return ''

    def tpl_back(self, tpl, key):
        if tpl is not None and tpl.used_count == 0:
            return self.brush('UnusedBg')
        return None

    def tpl_fore(self, tpl, key):
        if tpl is None:
            return self.brush('TextBrush')
        if key == 'used' and tpl.used_count == 0:
            return self.brush('MutedBrush')
        if key == 'default' and tpl.is_default:
            return self.brush('BlueBrush')
        return self.brush('TextBrush')

    # =====================================================================
    # reading the model
    # =====================================================================

    def refresh(self, first=False, keep_changes=False):
        self.status('Reading the model...')
        pending = {}
        if keep_changes:
            for row in self.data.rows:
                if row.changed:
                    pending[row.id_val] = (row.chosen_id, row.chosen_name,
                                           row.status, row.note, row.calc_slots)
        try:
            self.data = model.read(self.doc, self.settings)
        except Exception as ex:
            self.status('Could not read the model: {0}'.format(ex))
            return

        for row in self.data.rows:
            saved = pending.get(row.id_val)
            if saved:
                row.chosen_id, row.chosen_name, row.status, row.note, row.calc_slots = saved

        self._rebuild_param_items()
        self._fill_template_type(first)
        self._fill_template_filter(first)
        self._build_display_map()
        self._fill_template_list()
        self._type_note = ''
        self._guard_type_filter()
        self._fill_slot_list(self._chosen_slots())
        self.apply_filters()
        self.refresh_templates_tab()
        self.update_pending()
        self.status('{0} panels, {1} templates.{2}'.format(
            len(self.data.rows), len(self.data.templates),
            getattr(self, '_type_note', '')))

    def _fill_template_type(self, first):
        combo = self.w.FindName('TemplateTypeCombo')
        want = None if first else combo.SelectedItem
        self._populating = True
        try:
            combo.Items.Clear()
            combo.Items.Add(ALL_TYPES)
            for name in model.SCHEDULE_TYPES:
                combo.Items.Add(name)
            # anything the project uses that is not one of the three
            for tpl in self.data.templates:
                if tpl.schedule_type and tpl.schedule_type not in list(combo.Items):
                    combo.Items.Add(tpl.schedule_type)
            target = want
            if first:
                target = self.settings.get('default_schedule_type', 'Branch Panel')
            if target and target in list(combo.Items):
                combo.SelectedItem = target
            else:
                combo.SelectedIndex = 0
        finally:
            self._populating = False

    def _guard_type_filter(self):
        """A filter that hides every template is worse than no filter.

        If the project's templates do not report a schedule type at all, the
        Branch Panel default would show an empty list and look like the tool had
        found nothing.
        """
        if not self.data.templates:
            return
        if self.templates_in_list():
            return
        if self._type_filter() is None:
            return
        self._populating = True
        try:
            self.w.FindName('TemplateTypeCombo').SelectedIndex = 0
        finally:
            self._populating = False
        self._fill_template_list()
        self._type_note = ('  No template reports that schedule type, so the '
                           'list is showing every type.')

    def _type_filter(self):
        chosen = str(self.w.FindName('TemplateTypeCombo').SelectedItem or '')
        if not chosen or chosen == ALL_TYPES:
            return None
        return chosen

    def _fill_template_filter(self, first):
        combo = self.w.FindName('TemplateFilterCombo')
        want = None
        if not first:
            want = combo.SelectedItem
        self._populating = True
        try:
            combo.Items.Clear()
            combo.Items.Add('(All configurations)')
            for name in model.config_choices():
                combo.Items.Add(model.pretty_enum(name))
            target = want
            if first:
                default = self.settings.get('default_config', 'OneColumn')
                target = '(All configurations)' if default == 'All' \
                    else model.pretty_enum(default)
            if target and target in list(combo.Items):
                combo.SelectedItem = target
            else:
                combo.SelectedIndex = 0
        finally:
            self._populating = False

    def _config_filter(self):
        """The panel configuration the template list is showing, or None."""
        combo = self.w.FindName('TemplateFilterCombo')
        chosen = str(combo.SelectedItem or '')
        if not chosen or chosen.startswith('(All'):
            return None
        for name in model.config_choices():
            if model.pretty_enum(name) == chosen:
                return name
        return None

    def templates_in_list(self):
        want = self._config_filter()
        want_type = self._type_filter()
        needle = (self.w.FindName('TemplateSearchBox').Text or '').strip().lower()
        out = []
        for tpl in self.data.templates:
            if want and tpl.config != want:
                continue
            if want_type and tpl.schedule_type != want_type:
                continue
            if needle and needle not in (tpl.name or '').lower():
                continue
            out.append(tpl)
        return out

    def _build_display_map(self):
        self.display_to_id = {}
        self.id_to_display = {}
        used = set()
        for tpl in self.data.templates:
            base = tpl.name or '(unnamed)'
            if tpl.slots:
                base = '{0}   -   {1} slot'.format(base, tpl.slots)
            display = base
            if display.lower() in used:
                display = '{0}  [{1}]'.format(base, tpl.id_val)
            used.add(display.lower())
            self.display_to_id[display] = tpl.id_val
            self.id_to_display[tpl.id_val] = display

    def _fill_template_list(self):
        listbox = self.w.FindName('TemplateListBox')
        listbox.Items.Clear()
        shown = self.templates_in_list()
        for tpl in shown:
            listbox.Items.Add(self.id_to_display.get(tpl.id_val, tpl.name))
        total = len(self.data.templates)
        self.w.FindName('TemplateCountText').Text = \
            '{0} of {1} templates'.format(len(shown), total)

    # =====================================================================
    # filtering the panel table
    # =====================================================================

    def apply_filters(self):
        needle = (self.w.FindName('PanelSearchBox').Text or '').strip().lower()
        rows = []
        for row in self.data.rows:
            if not self._row_passes(row, needle):
                continue
            rows.append(row)
        rows = self._sorted(rows)
        self.visible_rows = rows

        items = List[object]()
        for row in rows:
            items.Add(row)
        grid_ctrl = self.w.FindName('PanelGrid')
        grid_ctrl.ItemsSource = items

        self.w.FindName('PanelCountText').Text = \
            '{0} of {1} shown'.format(len(rows), len(self.data.rows))
        active = [k for k, h in self.headers.items()
                  if h.search_text or h.allowed is not None]
        self.w.FindName('FilterSummaryText').Text = \
            ('{0} column filters on'.format(len(active)) if active else '')

    def _row_passes(self, row, needle):
        for key, header in self.headers.items():
            if not header.passes(self.cell_text(row, key)):
                return False
        if needle:
            blob = ' '.join([self.cell_text(row, k) or ''
                             for k in self.headers.keys()])
            if needle not in blob.lower():
                return False
        return True

    def _sorted(self, rows):
        key = self.sort_key or 'panel'
        if key == 'panel':
            rows.sort(key=lambda r: model._natural(r.name))
        else:
            rows.sort(key=lambda r: (self.cell_text(r, key) or '').lower())
        if self.sort_desc:
            rows.reverse()
        return rows

    def _on_sort(self, sender, args):
        """Sort the row list, not a CollectionView - the grid binds row objects."""
        try:
            args.Handled = True
            key = args.Column.SortMemberPath
            if key == self.sort_key:
                self.sort_desc = not self.sort_desc
            else:
                self.sort_key = key
                self.sort_desc = False
            self.apply_filters()
        except Exception:
            pass

    def _on_any_filter(self, sender=None, args=None):
        if self._populating:
            return
        self.apply_filters()

    def _on_clear_filters(self, sender, args):
        self._populating = True
        try:
            for header in self.headers.values():
                header.clear()
            self.w.FindName('PanelSearchBox').Text = ''
        finally:
            self._populating = False
        self.apply_filters()

    def _on_param_pick(self, key, name):
        index = param_index(key)
        if index is None or index >= len(self.col_names):
            return
        if name == DROP_COLUMN:
            del self.col_names[index]
            self._save_columns()
            self._build_columns()
            self._rebuild_param_items()
            self.apply_filters()
            self.status('Column removed.')
            return
        self.col_names[index] = '' if name == NO_PARAM else name
        self._save_columns()
        header = self.headers.get(key)
        if header is not None:
            # the old parameter's search text does not apply to the new one
            header.clear()
        self.apply_filters()

    def _open_tick_filter(self, header):
        if header.popup is not None:
            try:
                header.content.Children.Remove(header.popup)
            except Exception:
                pass
            header.popup = None
        values = set()
        for row in self.data.rows:
            values.add(self.cell_text(row, header.key) or grid.NO_VALUE)
        ordered = sorted(values, key=lambda s: s.lower())
        popup = grid.TickFilter(header, ordered, self.apply_filters)
        header.popup = popup.popup
        try:
            header.content.Children.Add(popup.popup)
        except Exception:
            pass
        self._active_filter = popup
        popup.show()

    def _on_template_filter(self, sender, args):
        if self._populating:
            return
        self._fill_template_list()
        self.refresh_templates_tab()
        self.apply_filters()

    def _on_template_search(self, sender, args):
        if self._populating:
            return
        self._fill_template_list()

    # =====================================================================
    # the template combo in every row
    # =====================================================================

    def _combo_loaded(self, sender, args):
        combo = sender if isinstance(sender, ComboBox) else args.OriginalSource
        if not isinstance(combo, ComboBox):
            return
        row = combo.DataContext
        if row is None or not hasattr(row, 'chosen_id'):
            return
        self._populating = True
        try:
            combo.Items.Clear()
            options = self.templates_in_list()
            ids = set([t.id_val for t in options])
            if row.current_id and row.current_id not in ids:
                current = self.data.by_id.get(row.current_id)
                if current is not None:
                    options = [current] + options
                    ids.add(current.id_val)
            if row.chosen_id and row.chosen_id not in ids:
                chosen = self.data.by_id.get(row.chosen_id)
                if chosen is not None:
                    options = [chosen] + options
            seen = set()
            for tpl in options:
                if tpl.id_val in seen:
                    continue
                seen.add(tpl.id_val)
                combo.Items.Add(self.id_to_display.get(tpl.id_val, tpl.name))
            want = self.id_to_display.get(row.chosen_id or row.current_id)
            if want and want in list(combo.Items):
                combo.SelectedItem = want
            else:
                combo.SelectedIndex = -1
                combo.Tag = 'no template on this panel'
        finally:
            self._populating = False

    def _combo_changed(self, sender, args):
        if self._populating:
            return
        combo = sender if isinstance(sender, ComboBox) else args.OriginalSource
        if not isinstance(combo, ComboBox):
            return
        row = combo.DataContext
        if row is None or not hasattr(row, 'chosen_id'):
            return
        display = str(combo.SelectedItem or '')
        tid = self.display_to_id.get(display, 0)
        if not tid:
            return
        tpl = self.data.by_id.get(tid)
        name = tpl.name if tpl is not None else display

        # picking a template on one row of a multi row selection sets them all
        targets = [row]
        picked = self._selected_rows()
        if len(picked) > 1 and any(r is row for r in picked):
            targets = picked

        blocked = [t for t in targets if t.locked]
        for target in targets:
            if target.locked:
                # queueing a change Apply could only skip would be a lie in the
                # table, so a locked row simply does not take one
                continue
            target.set_choice(tid, name)
            # a row the user has fixed by hand is no longer one to review
            target.status = 'changed' if target.changed else ''
            target.note = 'changed by hand' if target.changed else ''

        args.Handled = True
        self._refresh_rows()
        self.update_pending()
        moved = len(targets) - len(blocked)
        if blocked and moved:
            self.status('{0} panels set to "{1}". {2} left alone - {3}.'.format(
                moved, name, len(blocked), blocked[0].locked))
        elif blocked:
            self.status('{0} is locked - {1}.'.format(
                blocked[0].name, blocked[0].locked))
        elif len(targets) > 1:
            self.status('{0} panels set to "{1}".'.format(len(targets), name))

    def _refresh_rows(self):
        grid_ctrl = self.w.FindName('PanelGrid')
        try:
            grid_ctrl.Items.Refresh()
        except Exception:
            self.apply_filters()

    def update_pending(self):
        count = len([r for r in self.data.rows if r.changed])
        review = len([r for r in self.data.rows if r.status == 'review'])
        locked = len([r for r in self.data.rows if r.locked])
        text = ''
        if count:
            text = '{0} change{1} waiting'.format(count, '' if count == 1 else 's')
        if review:
            text = (text + '   ' if text else '') + '{0} to review'.format(review)
        if locked:
            text = (text + '   ' if text else '') + '{0} locked'.format(locked)
        self.w.FindName('PendingText').Text = text
        self.w.FindName('ApplyButton').IsEnabled = bool(count) and not self.busy

    # =====================================================================
    # Auto Assign
    # =====================================================================

    def _on_panel_selection(self, sender, args):
        try:
            self.w.FindName('AutoAssignSelectedButton').IsEnabled = \
                self.w.FindName('PanelGrid').SelectedItems.Count > 0
        except Exception:
            pass

    def _selected_rows(self):
        out = []
        try:
            for item in self.w.FindName('PanelGrid').SelectedItems:
                if item is not None and hasattr(item, 'chosen_id'):
                    out.append(item)
        except Exception:
            pass
        return out

    def _on_auto_assign_all(self, sender, args):
        self._auto_assign(None)

    def _on_auto_assign_selected(self, sender, args):
        rows = self._selected_rows()
        if not rows:
            self.status('Pick the rows you want Auto Assign to work on first.')
            return
        self._auto_assign(rows)

    def _auto_assign(self, rows):
        ways = self.settings.get('ways_param', '')
        phases = self.settings.get('phases_param', '')
        if not ways or not phases:
            ui.info(self.window, self.palette, 'Auto Assign Template',
                    'Set the number of ways and number of phases parameters in '
                    'Settings first, then run Auto Assign again.',
                    'v' + core.__version__)
            return
        try:
            summary = model.auto_assign(self.data, self.settings, rows,
                                        self._config_filter())
        except Exception as ex:
            self.status('Auto Assign failed: {0}'.format(ex))
            return
        self.apply_filters()
        self.update_pending()
        scope = 'all panels' if rows is None else \
            '{0} selected panel(s)'.format(len(rows))
        message = ('Auto Assign over {3}: {0} set, {1} already right, '
                   '{2} to review by hand.').format(
            summary['assigned'], summary['already'],
            summary['review'], scope)
        if summary.get('locked'):
            message += ('  {0} skipped - locked by somebody else.'.format(
                summary['locked']))
        if summary.get('kept'):
            message += '  {0} kept the template you picked by hand.'.format(
                summary['kept'])
        self.status(message)

    # =====================================================================
    # Right click on a template in the list
    # =====================================================================

    def _picked_template(self):
        """The template highlighted in the left hand list, or None."""
        try:
            display = str(self.w.FindName('TemplateListBox').SelectedItem or '')
        except Exception:
            return None
        if not display:
            return None
        return self.data.by_id.get(self.display_to_id.get(display, 0))

    def _on_copy_template_name(self, sender, args):
        tpl = self._picked_template()
        if tpl is None:
            self.status('Click a template in the list first.')
            return
        try:
            from System.Windows import Clipboard
            Clipboard.SetText(tpl.name or '')
            self.status('Copied "{0}".'.format(tpl.name))
        except Exception as ex:
            self.status('Could not reach the clipboard: {0}'.format(ex))

    def _on_edit_template(self, sender, args):
        """Open the picked template in Revit's own editor, then get out of the way.

        Revit has no API for opening the panel schedule template editor on a
        chosen template - PanelScheduleTemplate derives from Element, not from
        View - so this works only where the release exposes the template as a
        view.  Where it does not, it says so and offers the two clicks that do
        it by hand rather than looking like a button that does nothing.
        """
        if self.busy:
            return
        tpl = self._picked_template()
        if tpl is None:
            self.status('Click a template in the list first.')
            return
        self._editing_name = tpl.name
        self._raise(ops.job_edit_template(self.doc, tpl.id, tpl.name),
                    'Opening "{0}" in Revit...'.format(tpl.name), 'edit')

    def _finish_edit(self, result):
        """Close the tool once Revit has the template open, or explain."""
        name = getattr(self, '_editing_name', '') or 'that template'
        if (result or {}).get('ok'):
            self.status('Opening "{0}" in Revit.'.format(name))
            try:
                self.window.Close()
            except Exception:
                pass
            return
        note = (result or {}).get('note') or ''
        try:
            from System.Windows import Clipboard
            Clipboard.SetText(name)
            copied = ('\n\nThe name is on the clipboard, so it can be pasted '
                      'into the search box in that dialog.')
        except Exception:
            copied = ''
        ui.info(self.window, self.palette, 'Revit will not open it from here',
                '{0}\n\nOpen it by hand instead: Manage tab, Panel Schedule '
                'Templates, Edit a Template, then pick\n\n    {1}{2}'.format(
                    note, name, copied),
                'v' + core.__version__)
        self.status('"{0}" has to be opened from Manage, Panel Schedule '
                    'Templates, Edit a Template.'.format(name))

    # =====================================================================
    # Regenerate Templates
    # =====================================================================

    def _on_regenerate(self, sender, args):
        """Push the current template back through every panel schedule.

        Editing a template does not reach the schedules already made from it,
        so one sitting on a sheet keeps showing what it showed the day it was
        generated.  This re-pours every one of them from the template it is
        already on, which is what makes the sheets current.
        """
        if self.busy:
            return
        count = len(ops.instance_views(self.doc))
        if not count:
            self.status('There are no panel schedules in this project to '
                        'regenerate.')
            return
        answer = ui.ask(
            self.window, self.palette, 'Regenerate panel schedules',
            '{0} panel schedule{1} will be re-poured from the template each '
            'one is already on, so the schedules placed on sheets show current '
            'information.\n\nNo template is assigned or changed by this, and '
            'no panel moves onto a different template.\n\nWorth knowing: '
            're-pouring a schedule takes its layout from the template, so '
            'anything moved about on an individual schedule by hand goes back '
            'to what the template says.\n\nOn a project this size it takes a '
            'while - sync first and make a cup of tea.'.format(
                count, '' if count == 1 else 's'),
            [('Cancel', 'ghost'), ('Regenerate', 'primary')], 'orange',
            'v' + core.__version__)
        if answer != 1:
            return
        self._raise(ops.job_regenerate(self.doc, self.progress),
                    'Regenerating {0} panel schedule(s)...'.format(count),
                    'regenerate')

    def _on_reset(self, sender, args):
        for row in self.data.rows:
            row.reset_choice()
        self.apply_filters()
        self.update_pending()
        self.status('Changes cleared. Nothing has been written to the model.')

    # =====================================================================
    # Apply
    # =====================================================================

    def _on_apply(self, sender, args):
        if self.busy:
            return
        changed = [r for r in self.data.rows if r.changed and not r.locked]
        held = [r for r in self.data.rows if r.changed and r.locked]
        if not changed:
            if held:
                self.status('{0} panel(s) have changes waiting but are locked '
                            'by somebody else - nothing to apply.'.format(
                                len(held)))
            return
        if core.as_bool(self.settings.get('confirm_apply'), True):
            preview = []
            for row in changed[:14]:
                preview.append('  {0}   ->   {1}'.format(
                    row.name, row.chosen_name or '(none)'))
            more = len(changed) - len(preview)
            if more > 0:
                preview.append('  ... and {0} more'.format(more))
            held_note = ''
            if held:
                held_note = ('\n\n{0} more are locked by somebody else and '
                             'will be left alone.'.format(len(held)))
            answer = ui.ask(
                self.window, self.palette, 'Apply template changes',
                '{0} panel{1} will be moved onto a different panel schedule '
                'template.\n\n{2}\n\nNothing else in the model is '
                'touched.{3}'.format(
                    len(changed), '' if len(changed) == 1 else 's',
                    '\n'.join(preview), held_note),
                [('Cancel', 'ghost'), ('Apply', 'primary')], 'orange',
                'v' + core.__version__)
            if answer != 1:
                return

        jobs = []
        self._apply_wanted = {}
        for row in changed:
            if row.locked:
                continue
            jobs.append({'panel_id': row.id, 'view_id': row.view_id,
                         'template_id': self._id_of(row.chosen_id),
                         'label': row.name})
            self._apply_wanted[row.id_val] = (row.chosen_id, row.name)
        rebuild = core.as_bool(self.settings.get('rebuild_schedule'), True)
        self._raise(ops.job_apply_assignments(self.doc, jobs, self.progress,
                                              rebuild),
                    'Applying {0} template change(s)...'.format(len(jobs)),
                    'apply')

    def _id_of(self, id_value):
        tpl = self.data.by_id.get(id_value)
        return tpl.id if tpl is not None else None

    # =====================================================================
    # Template Duplicator tab
    # =====================================================================

    def refresh_templates_tab(self):
        self.template_view = self._dup_filtered()
        items = List[object]()
        for tpl in self.template_view:
            items.Add(tpl)
        self.w.FindName('TemplateGrid').ItemsSource = items
        unused = len([t for t in self.data.templates if t.used_count == 0])
        self.w.FindName('DupCountText').Text = \
            '{0} shown, {1} of {2} not used anywhere'.format(
                len(self.template_view), unused, len(self.data.templates))
        self._fill_merge_targets()

    def _dup_filtered(self):
        needle = (self.w.FindName('DupSearchBox').Text or '').strip().lower()
        unused_only = bool(self.w.FindName('UnusedOnlyCheck').IsChecked)
        use_filters = bool(self.w.FindName('DupUseFiltersCheck').IsChecked)
        want_type = self._type_filter() if use_filters else None
        want_config = self._config_filter() if use_filters else None
        bits = [b for b in (want_type,
                            model.pretty_enum(want_config) if want_config else '')
                if b]
        try:
            self.w.FindName('DupFilterText').Text = \
                ('showing ' + ', '.join(bits)) if bits else ''
        except Exception:
            pass
        out = []
        for tpl in self.data.templates:
            if want_type and tpl.schedule_type != want_type:
                continue
            if want_config and tpl.config != want_config:
                continue
            if unused_only and tpl.used_count:
                continue
            if needle and needle not in (tpl.name or '').lower():
                continue
            out.append(tpl)
        return out

    def _on_dup_filter(self, sender, args):
        if self._populating:
            return
        self.refresh_templates_tab()

    def _selected_templates(self):
        grid_ctrl = self.w.FindName('TemplateGrid')
        out = []
        try:
            for item in grid_ctrl.SelectedItems:
                if item is not None:
                    out.append(item)
        except Exception:
            pass
        return out

    def _on_template_selection(self, sender, args):
        if self._populating:
            return
        self._fill_merge_targets()

    def _fill_merge_targets(self):
        """Lead the eye to Duplicate once exactly one template is picked."""
        picked = self._selected_templates()
        button = self.w.FindName('DuplicateButton')
        try:
            if len(picked) == 1:
                button.SetResourceReference(Button.StyleProperty, 'PrimaryButton')
            else:
                button.ClearValue(Button.StyleProperty)
        except Exception:
            pass
        try:
            self.w.FindName('MergeTemplatesButton').IsEnabled = len(picked) > 1
            self.w.FindName('RenameTemplatesButton').IsEnabled = len(picked) > 0
        except Exception:
            pass

    # -- delete -----------------------------------------------------------
    def _on_delete(self, sender, args):
        if self.busy:
            return
        picked = self._selected_templates()
        if not picked:
            self.status('Pick the templates to delete first.')
            return
        in_use = [t for t in picked if t.used_count]
        lines = ['  {0}   -   {1}'.format(
            t.name, 'not used' if not t.used_count else
            '{0} panel(s) use it'.format(t.used_count)) for t in picked[:16]]
        warning = ''
        if in_use:
            warning = ('\n\n{0} of these are still in use. Deleting a template a '
                       'panel is using changes that panel schedule.'.format(len(in_use)))
        answer = ui.ask(
            self.window, self.palette, 'Delete templates',
            'These {0} template(s) will be deleted from the project:\n\n{1}{2}'.format(
                len(picked), '\n'.join(lines), warning),
            [('Cancel', 'ghost'), ('Delete', 'danger')], 'red',
            'v' + core.__version__)
        if answer != 1:
            return
        items = [{'id': t.id, 'label': t.name} for t in picked]
        self._raise(ops.job_delete(self.doc, items, self.progress),
                    'Deleting {0} template(s)...'.format(len(items)), 'delete')

    # -- merge ------------------------------------------------------------
    def _on_merge(self, sender, args):
        if self.busy:
            return
        picked = self._selected_templates()
        if len(picked) < 2:
            self.status('Pick two or more templates to merge.')
            return
        options = [self.id_to_display.get(t.id_val, t.name) for t in picked]
        display = ui.choose(
            self.window, self.palette, 'Merge templates',
            'Which template to merge to?\n\nEvery panel using the others moves '
            'onto the one you pick, and the emptied templates are then deleted.',
            options, 'Merge', 'v' + core.__version__)
        if not display:
            return
        target_id = self.display_to_id.get(str(display), 0)
        target = self.data.by_id.get(target_id)
        if target is None:
            self.status('Could not work out which template you picked.')
            return
        others = [t for t in picked if t.id_val != target.id_val]
        if not others:
            self.status('Choose a merge target that is not the only one picked.')
            return

        moving = []
        for row in self.data.rows:
            if row.current_id in [t.id_val for t in others]:
                moving.append(row)

        answer = ui.ask(
            self.window, self.palette, 'Merge templates',
            'Are you sure you know what you are doing you crazy person!\n\n'
            '{0} template(s) are about to be merged into "{1}".\n'
            '{2} panel(s) move onto it, and the {0} emptied template(s) are then '
            'deleted from the project.\n\nThis one cannot be undone from inside '
            'the tool - only with Revit\'s own undo.'.format(
                len(others), target.name, len(moving)),
            [('Cancel', 'ghost'), ('Yes, merge them', 'danger')], 'red',
            'v' + core.__version__)
        if answer != 1:
            return

        moves = [{'panel_id': r.id, 'view_id': r.view_id,
                  'template_id': target.id, 'label': r.name} for r in moving]
        removals = [{'id': t.id, 'label': t.name} for t in others]
        rebuild = core.as_bool(self.settings.get('rebuild_schedule'), True)
        self._raise(ops.job_merge(self.doc, moves, removals, self.progress,
                                  rebuild),
                    'Merging {0} template(s)...'.format(len(others)), 'merge')

    # -- rename -----------------------------------------------------------
    def _on_rename(self, sender, args):
        if self.busy:
            return
        picked = self._selected_templates()
        if not picked:
            self.status('Pick the templates you want to rename first.')
            return
        pairs = ui.rename(self.window, self.palette, [t.name for t in picked],
                          core, 'v' + core.__version__)
        if not pairs:
            return
        by_name = {}
        for tpl in picked:
            by_name[tpl.name] = tpl
        jobs = []
        for old, new in pairs:
            tpl = by_name.get(old)
            if tpl is not None:
                jobs.append((tpl.element, new))
        if not jobs:
            return
        taken = [t.name for t in self.data.templates]
        self._raise(ops.job_rename_many(self.doc, jobs, taken, self.progress),
                    'Renaming {0} template(s)...'.format(len(jobs)), 'rename')

    # -- duplicate --------------------------------------------------------
    def _on_duplicate(self, sender, args):
        picked = self._selected_templates()
        if len(picked) != 1:
            self.status('Pick one template to duplicate.')
            return
        self.dup_source = picked[0]
        w = self.w
        w.FindName('DupPlaceholder').Visibility = Visibility.Collapsed
        w.FindName('DupPanel').Visibility = Visibility.Visible
        w.FindName('DupSourceText').Text = 'From "{0}" - {1}, {2}{3}'.format(
            self.dup_source.name,
            self.dup_source.schedule_type or 'panel schedule',
            self.dup_source.config_pretty or 'as drawn',
            ', {0} slot'.format(self.dup_source.slots) if self.dup_source.slots else '')
        self._populating = True
        try:
            w.FindName('DupBaseName').Text = self.dup_source.name
            combo = w.FindName('DupConfigCombo')
            combo.Items.Clear()
            for name in model.config_choices():
                combo.Items.Add(model.pretty_enum(name))
            want = model.pretty_enum(self.dup_source.config)
            if want and want in list(combo.Items):
                combo.SelectedItem = want
            elif combo.Items.Count:
                combo.SelectedIndex = 0
            w.FindName('DupSinglePhaseCheck').IsChecked = self.dup_source.single_phase
            # the source decides how many slots a way is, so the list is rebuilt
            # for it rather than left offering multiples of three
            self._fill_slot_list([])
        finally:
            self._populating = False
        self._dup_preview(None, None)

    def _per_way(self):
        """Slots per way for whatever the duplicator is set to build.

        A single phase way takes one slot, not three, so a 12 way single phase
        board is 12 slots.  Ticking Single phase panel re-does the list rather
        than leaving it offering multiples of three that mean nothing.
        """
        single = False
        try:
            single = bool(self.w.FindName('DupSinglePhaseCheck').IsChecked)
        except Exception:
            pass
        return core.slots_per_way(single)

    def _fill_slot_list(self, keep=None):
        """Slot counts as a plain list, so click / shift click / ctrl click all
        behave the way they do everywhere else in Windows."""
        listbox = self.w.FindName('SlotList')
        keep = set(keep or [])
        per_way = self._per_way()
        was_populating = self._populating
        self._populating = True
        try:
            listbox.Items.Clear()
            self.slot_items = []
            self.slot_lookup = {}
            try:
                self.w.FindName('SlotRuleText').Text = (
                    'Single phase: one way is one slot, so the list counts up '
                    'in ones.' if per_way == 1 else
                    'Three phase: one way is {0} slots, so the list counts up '
                    'in {0}s.'.format(per_way))
            except Exception:
                pass
            for number in core.slot_options(self.settings, per_way):
                ways = core.ways_from_slots(number, per_way)
                display = '{0} slot{1}   -   {2} way{3}'.format(
                    number, '' if number == 1 else 's',
                    ways, '' if ways == 1 else 's')
                self.slot_items.append((number, display))
                self.slot_lookup[display] = number
                listbox.Items.Add(display)
            self._select_slots(keep)
        finally:
            self._populating = was_populating
        self._dup_preview(None, None)

    def _on_single_phase(self, sender, args):
        """Keep the same number of WAYS when the phase setting changes.

        Somebody who picked 12 ways on three phase and then ticks single phase
        still wants 12 ways - which is now 12 slots, not 36.
        """
        if self._populating:
            return
        old = self._per_way()
        # the tick has already flipped, so the old step is the other one
        previous = 1 if old != 1 else core.SLOTS_PER_WAY
        wanted = []
        for slots in self._chosen_slots():
            wanted.append(core.ways_from_slots(slots, previous) * old)
        self._fill_slot_list(wanted)

    def _select_slots(self, wanted):
        listbox = self.w.FindName('SlotList')
        wanted = set(wanted or [])
        try:
            listbox.SelectedItems.Clear()
            for number, display in self.slot_items:
                if number in wanted:
                    listbox.SelectedItems.Add(display)
        except Exception:
            pass

    def _chosen_slots(self):
        out = []
        try:
            for item in self.w.FindName('SlotList').SelectedItems:
                number = self.slot_lookup.get(str(item))
                if number:
                    out.append(number)
        except Exception:
            pass
        out.sort()
        return out

    def _slots_all(self, sender, args):
        try:
            self.w.FindName('SlotList').SelectAll()
        except Exception:
            pass

    def _slots_none(self, sender, args):
        try:
            self.w.FindName('SlotList').UnselectAll()
        except Exception:
            pass

    def _slots_common(self, sender, args):
        per_way = self._per_way()
        self._select_slots([n for n, _ in self.slot_items
                            if 4 <= core.ways_from_slots(n, per_way) <= 16])

    def _dup_names(self):
        """Each copy is named for its ways, as a suffix.

        A 36 slot board is a 12 way board, so the copy gets "12 Ways" on the
        end.  A suffix rather than a replacement, because replacing the largest
        number in the name corrupted a source called
        "BGL_Schedule One Column Master (R2)".  A name that already exists gets
        "New" after that rather than overwriting anything.

        The word "Master" is taken out on the way: a copy is not the master.
        """
        base = (self.w.FindName('DupBaseName').Text or '').strip()
        if not base and self.dup_source is not None:
            base = self.dup_source.name
        taken = set([(t.name or '').lower() for t in self.data.templates])
        per_way = self._per_way()
        out = []
        for slots in self._chosen_slots():
            ways = core.ways_from_slots(slots, per_way)
            name = core.unique_name(core.name_with_ways(base, ways), taken)
            taken.add(name.lower())
            out.append((slots, name))
        return out

    def _dup_preview(self, sender, args):
        if self._populating:
            return
        names = self._dup_names()
        button = self.w.FindName('CreateButton')
        button.IsEnabled = bool(names) and not self.busy
        button.Content = 'Create' if not names else \
            'Create {0} template{1}'.format(len(names), '' if len(names) == 1 else 's')
        preview = self.w.FindName('DupPreviewText')
        if not names:
            preview.Text = 'Pick one or more slot counts above.'
            return
        shown = ['  {0}   ({1} slots)'.format(n, s) for s, n in names[:6]]
        if len(names) > 6:
            shown.append('  ... and {0} more'.format(len(names) - 6))
        preview.Text = 'Will create:\n' + '\n'.join(shown)

    def _on_create(self, sender, args):
        if self.busy or self.dup_source is None:
            return
        names = self._dup_names()
        if not names:
            return
        if len(names) > 5:
            answer = ui.ask(
                self.window, self.palette, 'This will take a while',
                'WARNING, this process takes some time if you selected a lot, '
                'I advise you SYNC the model before running and make a cup of '
                'tea.\n\n{0} templates are about to be created.'.format(len(names)),
                [('Cancel', 'ghost'), ('Go on then', 'primary')], 'orange',
                'v' + core.__version__)
            if answer != 1:
                return
        config_name = str(self.w.FindName('DupConfigCombo').SelectedItem or '')
        config_value = None
        for name in model.config_choices():
            if model.pretty_enum(name) == config_name:
                config_value = model.enum_value(model.PanelConfiguration, name)
                break
        flags = dict(self.dup_source.flags)
        flags['IsPanelSinglePhase'] = bool(
            self.w.FindName('DupSinglePhaseCheck').IsChecked)

        taken = set([(t.name or '').lower() for t in self.data.templates])
        specs = []
        for number, new_name in names:
            specs.append({'slots': number, 'name': new_name,
                          'config': config_value, 'flags': flags})
        copy_layout = bool(self.w.FindName('DupCopyLayoutCheck').IsChecked)
        self._raise(ops.job_duplicate(self.doc, self.dup_source.element, specs,
                                      taken, copy_layout, self.progress),
                    'Creating {0} template(s)...'.format(len(specs)), 'create')

    # =====================================================================
    # running a job through the external event
    # =====================================================================

    def _raise(self, job, message, label):
        self._set_busy(True)
        self._pending_label = label
        self.handler.job = job
        self.w.FindName('ApplyButton').IsEnabled = False
        self.w.FindName('CreateButton').IsEnabled = False
        self.w.FindName('RegenerateButton').IsEnabled = False
        self.progress_open(message)
        self.status(message)
        try:
            self.event.Raise()
        except Exception as ex:
            self._set_busy(False)
            self.progress_close()
            self.update_pending()
            self._dup_preview(None, None)
            self.status('Could not reach Revit: {0}'.format(ex))

    def _job_done(self, result, error):
        try:
            self.window.Dispatcher.Invoke(
                Action(lambda: self._finish(result, error)))
        except Exception:
            self._finish(result, error)

    def _finish(self, result, error):
        self._set_busy(False)
        self.progress_close()
        label = self._pending_label
        if error:
            self.status('{0} failed: {1}'.format(label.capitalize(), error))
            if label in ('apply', 'merge'):
                # these run in pieces, so some of it may well have landed
                headline = 'The run stopped early'
                body = ('The {0} stopped on something Revit would not do. Panels '
                        'it had already finished are written; the one it stopped '
                        'on and anything after it are not.\n\n{1}\n\nRe-reading '
                        'the model now - whatever is still outstanding will show '
                        'as waiting for Apply again.'.format(label, error))
            else:
                headline = 'Nothing was changed'
                body = ('Revit refused the {0}, so the whole transaction was '
                        'rolled back and the model is exactly as it was.\n\n'
                        '{1}'.format(label, error))
            ui.info(self.window, self.palette, headline, body,
                    'v' + core.__version__)
            self.refresh(keep_changes=True)
            self.update_pending()
            self._dup_preview(None, None)
            return

        if label == 'edit':
            self._finish_edit(result)
            return
        summary = self._summarise(label, result or {})
        if label == 'create':
            self._select_slots([])
        # keep_changes: a delete or a create on the other tab must not quietly
        # drop assignments that are still waiting for Apply
        self.refresh(keep_changes=True)
        self._dup_preview(None, None)
        if label == 'create':
            summary += self._check_created((result or {}).get('ids') or [],
                                           (result or {}).get('names') or [])
        stayed = []
        if label == 'apply':
            summary, stayed = self._check_applied(summary)
        failed = (result or {}).get('failed') or []
        noted = [(name, note) for name, note in ((result or {}).get('made') or [])
                 if note]
        noted += (result or {}).get('notes') or []
        held = (result or {}).get('locked') or []
        # a panel that failed in the job and is also still on its old template
        # is one problem, not two - and a locked one is already accounted for
        seen = set([name for name, _ in failed])
        seen.update([name for name, _ in held])
        failed = failed + [(name, why) for name, why in stayed
                           if name not in seen]
        if held:
            summary += '  {0} left alone - locked by somebody else.'.format(
                len(held))
        if failed or noted or held:
            lines = []
            if held:
                lines.append('These are locked and were left alone:')
                lines.extend(['  {0}: {1}'.format(who, why)
                              for who, why in held[:12]])
                if len(held) > 12:
                    lines.append('  ... and {0} more'.format(len(held) - 12))
                if failed or noted:
                    lines.append('')
            if failed:
                lines.append('These did not go through:'
                             if label == 'apply' else 'These were skipped:')
                lines.extend(['  {0}: {1}'.format(name, why)
                              for name, why in failed[:12]])
                if len(failed) > 12:
                    lines.append('  ... and {0} more'.format(len(failed) - 12))
            if noted:
                if lines:
                    lines.append('')
                lines.append('These went through, with something to note:')
                lines.extend(['  {0}: {1}'.format(name, note)
                              for name, note in noted[:12]])
                if len(noted) > 12:
                    lines.append('  ... and {0} more'.format(len(noted) - 12))
            title = ('Some panels were left alone' if held and not failed
                     else 'Some of it did not go through')
            ui.info(self.window, self.palette, title,
                    '{0}\n\n{1}'.format(summary, '\n'.join(lines)),
                    'v' + core.__version__)
        self.status(summary)

    def _check_applied(self, summary):
        """Read the model back and see which panels really moved.

        The job's own count says how many calls Revit accepted, which is not the
        same question.  This one is asked of the freshly re-read table: a panel
        whose template is still the old one is reported as staying put, by name,
        instead of being counted as applied.
        """
        wanted = getattr(self, '_apply_wanted', None) or {}
        if not wanted:
            return summary, []
        stayed = []
        moved = 0
        for row in self.data.rows:
            pair = wanted.get(row.id_val)
            if not pair:
                continue
            target, label = pair
            if row.current_id == target:
                moved += 1
            else:
                on = self.data.by_id.get(row.current_id)
                stayed.append((label, 'still on "{0}"'.format(
                    on.name if on is not None else 'no template')))
        self._apply_wanted = {}
        if stayed:
            summary = ('Apply: {0} of {1} panel(s) really moved - {2} did '
                       'not.'.format(moved, moved + len(stayed), len(stayed)))
        else:
            summary = ('Apply: {0} panel(s) moved onto a new template, '
                       'checked against the model.'.format(moved))
        return summary, stayed

    def _check_created(self, ids, names=None):
        """Prove the new templates are really in the model, and show them.

        "It says it created them but they are not there" is one of three things:
        the element never landed, a filter is hiding it, or this check itself is
        wrong.  So it looks by id AND by name - a template found under its name
        but not its id would mean the check is the thing at fault, and it says
        so rather than sending anyone hunting.
        """
        if not ids:
            return ''
        by_name = {}
        for tpl in self.data.templates:
            by_name[(tpl.name or '').lower()] = tpl.id_val
        wanted_names = [n.lower() for n in (names or [])]
        named = [n for n in wanted_names if n in by_name]

        missing = [i for i in ids if i not in self.data.by_id]
        found = [i for i in ids if i in self.data.by_id]

        if missing and named:
            # they are in the model, just not under the ids we captured
            found = found + [by_name[n] for n in named
                             if by_name[n] not in found]
            missing = []
        if missing and not found:
            return ('  None of them are in the model after re-reading - Revit '
                    'took the call but kept nothing.')

        note = ''
        if missing:
            note += '  {0} of them are not in the model after re-reading.'.format(
                len(missing))

        # if the duplicator view would hide them, stop hiding them
        visible = set([t.id_val for t in self._dup_filtered()])
        hidden = [i for i in found if i not in visible]
        if hidden:
            self._populating = True
            try:
                self.w.FindName('DupUseFiltersCheck').IsChecked = False
                self.w.FindName('DupSearchBox').Text = ''
                self.w.FindName('UnusedOnlyCheck').IsChecked = False
            finally:
                self._populating = False
            self.refresh_templates_tab()
            note += ('  {0} of them did not match the filters, so the filters '
                     'have been turned off to show them.').format(len(hidden))

        self._select_templates(found)
        return note

    def _select_templates(self, ids):
        """Pick the given templates in the duplicator list and scroll to them."""
        wanted = set(ids or [])
        if not wanted:
            return
        grid_ctrl = self.w.FindName('TemplateGrid')
        try:
            grid_ctrl.SelectedItems.Clear()
            first = None
            for tpl in self.template_view:
                if tpl.id_val in wanted:
                    grid_ctrl.SelectedItems.Add(tpl)
                    if first is None:
                        first = tpl
            if first is not None:
                grid_ctrl.ScrollIntoView(first)
        except Exception:
            pass

    @staticmethod
    def _summarise(label, result):
        done = len(result.get('done') or [])
        made = len(result.get('made') or [])
        removed = len(result.get('removed') or [])
        failed = len(result.get('failed') or [])
        bits = []
        if label == 'regenerate':
            total = result.get('total') or 0
            sheets = result.get('on_sheet') or 0
            line = '{0} of {1} panel schedule(s) regenerated'.format(done, total)
            if sheets:
                line += ' - {0} of them are on sheets'.format(sheets)
            if failed:
                line += ', {0} skipped'.format(failed)
            return 'Regenerate: {0}.'.format(line)
        if done:
            if label == 'rename':
                bits.append('{0} template(s) renamed'.format(done))
            else:
                bits.append('{0} panel(s) moved onto a new template'.format(done))
        if made:
            bits.append('{0} template(s) created'.format(made))
        if removed:
            bits.append('{0} template(s) deleted'.format(removed))
        if failed:
            bits.append('{0} skipped'.format(failed))
        if not bits:
            bits.append('nothing to do')
        return '{0}: {1}.'.format(label.capitalize(), ', '.join(bits))

    # =====================================================================
    # window level
    # =====================================================================

    # =====================================================================
    # progress
    # =====================================================================

    def progress_open(self, text):
        try:
            self.w.FindName('ProgressBand').Visibility = Visibility.Visible
            self.w.FindName('ProgressBarMain').Value = 0
            self.w.FindName('ProgressPercent').Text = '0%'
            self.w.FindName('ProgressText').Text = text
            self._pump()
        except Exception:
            pass

    def progress(self, done, total, label):
        """Called from the job, which runs on Revit's thread - the same thread
        WPF draws on - so the bar has to be pumped by hand or it never moves."""
        try:
            percent = 100 if not total else int(round(100.0 * done / total))
            if percent < 0:
                percent = 0
            if percent > 100:
                percent = 100
            self.w.FindName('ProgressBarMain').Value = percent
            self.w.FindName('ProgressPercent').Text = '{0}%'.format(percent)
            if label:
                self.w.FindName('ProgressText').Text = '{0}  ({1} of {2})'.format(
                    label, min(done + 1, total), total)
            self._pump()
        except Exception:
            pass

    def _pump(self):
        """Let the bar repaint while the job holds the UI thread.

        Dispatcher.Invoke from the dispatcher's own thread pushes a message
        frame, and that frame dispatches real mouse and key messages - the
        priority only orders the dispatcher queue, it does not hold input back.
        So the window is made deaf for the duration of a job (see _set_busy)
        and every handler that could still be reached checks self.busy.  Without
        that, closing the window mid job tore the callback out from under an
        open transaction.
        """
        try:
            self.window.Dispatcher.Invoke(DispatcherPriority.Render,
                                          Action(lambda: None))
        except Exception:
            pass

    def _set_busy(self, busy):
        """Make the window deaf for the length of a job - all but the shrink button.

        Pumping the dispatcher to move the progress bar also pumps input, so
        a click could reach a handler mid transaction; closing the window that
        way once tore the callback away from an open transaction.  It used to
        be the whole window that went deaf.  Now it is everything except the
        shrink button, because a long Apply or Regenerate is exactly when
        somebody wants to put the window away and watch Revit, and shrinking
        touches nothing but the window's own geometry.
        """
        self.busy = bool(busy)
        live = not self.busy
        header = self.w.FindName('HeaderBar')
        try:
            for child in header.Parent.Children:
                if not drawer_mod._same(child, header):
                    child.IsHitTestVisible = live
        except Exception:
            try:
                self.window.IsHitTestVisible = live
            except Exception:
                pass
        for name in BUSY_DEAF:
            try:
                self.w.FindName(name).IsHitTestVisible = live
            except Exception:
                pass
        try:
            # Apply and Create are re-enabled by what they depend on; this one
            # depends on nothing, so it has to be put back by hand
            self.w.FindName('RegenerateButton').IsEnabled = not self.busy
        except Exception:
            pass

    def progress_close(self):
        try:
            self.w.FindName('ProgressBand').Visibility = Visibility.Collapsed
        except Exception:
            pass

    def status(self, text):
        try:
            self.w.FindName('StatusText').Text = text
        except Exception:
            pass

    def _toggle_theme(self, sender, args):
        if self.busy:
            return
        self.palette = theme_mod.other(self.palette)
        theme_mod.apply(self.window, self.palette)
        self.settings['theme'] = self.palette
        core.save_settings(self.settings)
        self._set_theme_chip()
        self._refresh_rows()
        try:
            self.w.FindName('TemplateGrid').Items.Refresh()
        except Exception:
            pass

    def _toggle_full(self, sender, args):
        if self.drawer.parked:
            # full screen on a window nobody can see would only hide it again
            self.drawer.expand()
            return
        if self.busy:
            return
        self.full.toggle()
        self._set_full_glyph()

    def _open_settings(self, sender, args):
        if self.busy:
            return
        # the configured parameters go into the list even when the panels in
        # this project do not carry them, or Save would silently repoint them
        names = list(self.data.param_names)
        for key in ('ways_param', 'phases_param'):
            value = self.settings.get(key, '')
            if value and value not in names:
                names.insert(0, value)
        dialog = SettingsWindow(self.window, self.settings,
                                names, model.config_choices(),
                                model.SCHEDULE_TYPES)
        saved, values = dialog.show()
        if not saved:
            return
        self.settings = values
        self.col_names = core.columns_after_settings(self.col_names, self.settings)
        self._save_columns()
        self._build_columns()
        if self.settings.get('theme') != self.palette:
            self.palette = self.settings.get('theme', 'dark')
            theme_mod.apply(self.window, self.palette)
            self._set_theme_chip()
        self._fill_slot_list(self._chosen_slots())
        self.refresh(first=True, keep_changes=True)
        self.status('Settings saved.')

    def _on_refresh(self, sender, args):
        if self.busy:
            return
        if any([r.changed for r in self.data.rows]):
            answer = ui.ask(
                self.window, self.palette, 'Re-read the model',
                'There are changes waiting for Apply. Re-reading keeps them '
                'where the panel is still in the model.',
                [('Cancel', 'ghost'), ('Re-read', 'accent')], 'orange',
                'v' + core.__version__)
            if answer != 1:
                return
        self.refresh(keep_changes=True)

    def _on_key(self, sender, args):
        if self.drawer.parked:
            # Escape, Enter and F11 have already brought it back, and nothing
            # else on a bar has anything to do
            return
        if self.busy:
            return
        try:
            if args.Key == Key.F5:
                self.refresh(keep_changes=True)
                args.Handled = True
            elif args.Key == Key.F11:
                self.full.toggle()
                self._set_full_glyph()
                args.Handled = True
            elif args.Key == Key.Escape and self.full.is_full:
                self.full.leave()
                self._set_full_glyph()
                args.Handled = True
        except Exception:
            pass

    def _on_closed(self, sender, args):
        try:
            self.handler.on_complete = None
        except Exception:
            pass

    def _close(self, sender, args):
        if self.busy:
            return
        if any([r.changed for r in self.data.rows]):
            answer = ui.ask(
                self.window, self.palette, 'Close without applying',
                'There are changes waiting for Apply. Closing drops them - '
                'nothing has been written to the model.',
                [('Stay open', 'ghost'), ('Close anyway', 'danger')], 'orange',
                'v' + core.__version__)
            if answer != 1:
                return
        try:
            self.window.Close()
        except Exception:
            pass

    def show(self, main_window_handle=None):
        if main_window_handle is not None:
            ui.own_by_revit(self.window, main_window_handle)
        self.window.Show()
        return self.window
