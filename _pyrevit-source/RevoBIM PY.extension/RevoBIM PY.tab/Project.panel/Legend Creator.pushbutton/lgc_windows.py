# -*- coding: utf-8 -*-

"""Legend Creator - the picker window and the summary window."""

from pyrevit import forms

import lgc_clr  # noqa: F401 - references first, before any System import
from System.Windows import (GridLength, GridUnitType, HorizontalAlignment,
                            SystemParameters, VerticalAlignment, Visibility)
from System.Windows.Controls import (Border, CheckBox, ColumnDefinition, Grid,
                                     TextBlock)
from System.Windows.Input import Key

from lgc_logic import (CASE_ASIS, CASE_CAMEL, CASE_UPPER, DEFAULT_CASE,
                       DEFAULT_COLUMN_SPACING_MM, DEFAULT_LINE_WEIGHT,
                       DEFAULT_NAME_PARAM, DEFAULT_PHASE, DEFAULT_SCALE,
                       MAX_LINE_WEIGHT, MIN_LINE_WEIGHT, NAME_FAMILY_TYPE,
                       NAME_TYPE_NAME, ROW_SPACING_MM, SCALE_CHOICES,
                       SWATCH_W_MM, SYSTEM_DEFAULT_SCALE, SYSTEM_KINDS,
                       SYSTEM_REFERENCE_SCALE, SYS_HEADING_GAP_MM,
                       SYS_ROW_PITCH_MM, SYS_TEXT_GAP_MM, TEXT_OFFSET_MM,
                       THEME_AUTO, THEME_ORDER, choose_template, clamp_weight,
                       format_kv_list, format_mm, next_theme_mode,
                       parse_kv_list, scaled_mm, unscaled_mm)
from lgc_core import (__version__, eid_value, load_settings, log,
                      save_settings, swallowed)
from lgc_drawer import make_drawer
from lgc_model import (collect_used_types, default_text_type_id, element_name,
                       matching_filter_count, read_duct_systems,
                       read_pipe_systems, read_template_filters,
                       string_parameter_names, view_templates)
from lgc_theme import (apply_palette, brush, load_window, resolve_theme,
                       revit_theme)


# ---------------------------------------------------------------------------
# Category picker window
# ---------------------------------------------------------------------------
class CategoryPicker(forms.WPFWindow):
    """The tool window: family legends on one tab, system colours on the
    other. Dark and light, switched from the chip in the header."""

    def __init__(self, xaml_path, phases, text_types, settings,
                 family_ready=True):
        load_window(self, xaml_path)
        self.version_tb.Text = 'v' + __version__

        self.family_ready = family_ready
        self.sys_entries = []
        self.sys_rows = []
        self._fit_to_screen()
        self.debug_cb.IsChecked = settings.get('debug', '0') == '1'
        self.theme_mode = settings.get('theme_mode', THEME_AUTO)
        if self.theme_mode not in THEME_ORDER:
            self.theme_mode = THEME_AUTO
        self.theme_name = resolve_theme(self.theme_mode)
        self.palette = apply_palette(self, self.theme_name)
        self.drawer = make_drawer(self)
        self._wire_events()

        self.phases = phases
        self.text_types = text_types
        self.settings = settings
        self.rows = []
        self.infos = []
        self.result = []
        self.cache = {}
        self.opts = None
        self.mode = 'family'
        self._captured_before_scale = None
        self._sys_captured = None
        self._loading = True

        log(u'window: filling the family tab')
        self._fill_phases()
        self._fill_text_types()
        self._fill_scales()
        self._restore_case()
        self.combine_cb.IsChecked = settings.get('combined', '0') == '1'

        # Base distances are held at REFERENCE_SCALE and shown restated for
        # the chosen scale, so the boxes always read in real view millimetres.
        self.base = {
            'row': self._setting_float('row_spacing', ROW_SPACING_MM),
            'text': self._setting_float('text_offset', TEXT_OFFSET_MM),
            'column': self._setting_float('column_spacing',
                                          DEFAULT_COLUMN_SPACING_MM),
        }
        self._show_distances()

        # --- system colour legend tab
        self.templates = view_templates()
        self.sys_entries = []
        self.sys_rows = []
        self.sys_notes = []
        self._fill_kinds()
        self._fill_templates()
        self._fill_sys_text_types()
        self._fill_sys_scales()
        self.sys_upper_cb.IsChecked = settings.get('sys_upper', '1') == '1'
        self.sys_lw_tb.Text = str(clamp_weight(
            settings.get('sys_line_weight', DEFAULT_LINE_WEIGHT)))
        self.sys_name_tb.Text = settings.get('sys_view_name', '') or \
            self.selected_kind()['view_name']
        self._apply_kind()
        # Swatch height is per kind - a pipe run is a thin band where a
        # cable tray is a block - so it is held keyed by kind and swapped
        # when the kind changes. The rest are shared.
        self.sys_heights = parse_kv_list(
            settings.get('sys_swatch_h', ''),
            dict((k['key'], k['swatch_h']) for k in SYSTEM_KINDS))
        self._kind_key = self.selected_kind()['key']
        self.sys_base = {
            'swatch_w': self._setting_float('sys_swatch_w', SWATCH_W_MM),
            'row_pitch': self._setting_float('sys_row_pitch',
                                             SYS_ROW_PITCH_MM),
            'text_gap': self._setting_float('sys_text_gap', SYS_TEXT_GAP_MM),
        }
        self._show_sys_distances()
        self._label_theme()

        log(u'window: reading the model')
        self._loading = False
        self.reload_categories()
        self.reload_filters()
        log(u'window: ready')

    # -- population --------------------------------------------------------
    def _fill_phases(self):
        self.phase_cb.Items.Add('All phases')
        wanted = self.settings.get('phase', DEFAULT_PHASE)
        chosen = 0
        for index, (name, _pid) in enumerate(self.phases):
            self.phase_cb.Items.Add(name)
            if name == wanted:
                chosen = index + 1
        if chosen == 0 and wanted != 'All phases' and self.phases:
            # Saved phase is gone from this model. Fall back to the last
            # phase, which is New Construction in a default template.
            chosen = len(self.phases)
        self.phase_cb.SelectedIndex = chosen

    def _fill_text_types(self):
        wanted = self.settings.get('text_type', '')
        default_id = eid_value(default_text_type_id())
        chosen = 0
        for index, (name, tid) in enumerate(self.text_types):
            self.text_cb.Items.Add(name)
            if name == wanted:
                chosen = index
            elif not wanted and eid_value(tid) == default_id:
                chosen = index
        if self.text_cb.Items.Count:
            self.text_cb.SelectedIndex = chosen

    def _fill_params(self):
        self.param_cb.Items.Clear()
        names = [NAME_TYPE_NAME, NAME_FAMILY_TYPE]
        found = string_parameter_names(self.infos)
        if DEFAULT_NAME_PARAM not in found:
            found.insert(0, DEFAULT_NAME_PARAM)
        names.extend(found)

        wanted = self.settings.get('name_param', DEFAULT_NAME_PARAM)
        chosen = 0
        for index, name in enumerate(names):
            self.param_cb.Items.Add(name)
            if name == wanted:
                chosen = index
        self.param_cb.SelectedIndex = chosen

    def _setting_float(self, key, fallback):
        try:
            value = float(self.settings.get(key, fallback))
            return value if value > 0 else float(fallback)
        except Exception:
            return float(fallback)

    def _fill_scales(self):
        wanted = self.settings.get('scale', str(DEFAULT_SCALE))
        chosen = SCALE_CHOICES.index(DEFAULT_SCALE)
        for index, scale in enumerate(SCALE_CHOICES):
            self.scale_cb.Items.Add('1:{0}'.format(scale))
            if str(scale) == str(wanted):
                chosen = index
        self.scale_cb.SelectedIndex = chosen

    def selected_scale(self):
        index = self.scale_cb.SelectedIndex
        if index < 0 or index >= len(SCALE_CHOICES):
            return DEFAULT_SCALE
        return SCALE_CHOICES[index]

    def _show_distances(self):
        """Restate the stored base distances for the chosen scale."""
        scale = self.selected_scale()
        self.row_tb.Text = format_mm(scaled_mm(self.base['row'], scale))
        self.text_tb.Text = format_mm(scaled_mm(self.base['text'], scale))
        self.spacing_tb.Text = format_mm(scaled_mm(self.base['column'], scale))

    def _capture_distances(self):
        """Read the boxes back, converting to base distances. None if bad."""
        scale = self.selected_scale()
        captured = {}
        for key, box in (('row', self.row_tb), ('text', self.text_tb),
                         ('column', self.spacing_tb)):
            try:
                value = float(box.Text.strip())
            except Exception:
                return None
            if value <= 0:
                return None
            captured[key] = unscaled_mm(value, scale)
        return captured

    def _fit_to_screen(self):
        """Keep the window inside the working area.

        The window has no system chrome, so Windows will not rein it in: on a
        laptop or a scaled display it can open taller than the screen and put
        its own footer out of reach, with no way to drag it back. MinHeight
        comes down too, or the clamp cannot take effect.
        """
        try:
            area = SystemParameters.WorkArea
        except Exception:
            swallowed()
            return

        margin = 40.0
        max_width = area.Width - margin
        max_height = area.Height - margin

        if self.MinWidth > max_width:
            self.MinWidth = max(420.0, max_width)
        if self.MinHeight > max_height:
            self.MinHeight = max(380.0, max_height)
        if self.Width > max_width:
            self.Width = max(self.MinWidth, max_width)
        if self.Height > max_height:
            self.Height = max(self.MinHeight, max_height)

        self.Left = area.Left + (area.Width - self.Width) / 2.0
        self.Top = area.Top + (area.Height - self.Height) / 2.0

    def _wire_events(self):
        """Bind every handler from Python.

        XAML string wiring is not dependable through pyRevit's loader - the
        header handler silently never fired, which is what left the window
        unmovable in 2.1.1 - so the house convention is to bind here.
        """
        self.header_bar.MouseLeftButtonDown += self.drag_window
        self.shrink_btn.Click += self.on_shrink
        self.close_btn.Click += self.cancel
        self.cancel_btn.Click += self.cancel
        # after the drawer, which subscribed when it was built: a parked
        # bar has already taken Escape by the time this sees it
        self.PreviewKeyDown += self.on_key
        self.create_btn.Click += self.create
        self.theme_btn.Click += self.toggle_theme
        self.tabs.SelectionChanged += self.tab_changed

        self.filter_tb.TextChanged += self.filter_changed
        self.sel_all_btn.Click += self.select_all
        self.clear_btn.Click += self.clear_all
        self.phase_cb.SelectionChanged += self.phase_changed
        self.scale_cb.DropDownOpened += self.scale_opening
        self.scale_cb.SelectionChanged += self.scale_changed
        self.combine_cb.Click += self.combine_toggled

        self.kind_cb.SelectionChanged += self.kind_changed
        self.template_cb.SelectionChanged += self.template_changed
        self.sys_scale_cb.DropDownOpened += self.sys_scale_opening
        self.sys_scale_cb.SelectionChanged += self.sys_scale_changed
        self.sys_upper_cb.Click += self.sys_upper_toggled
        self.sys_sel_btn.Click += self.sys_select_all
        self.sys_clear_btn.Click += self.sys_clear_all

        self.grip_tl.DragDelta += self.on_grip_tl
        self.grip_t.DragDelta += self.on_grip_t
        self.grip_tr.DragDelta += self.on_grip_tr
        self.grip_l.DragDelta += self.on_grip_l
        self.grip_r.DragDelta += self.on_grip_r
        self.grip_bl.DragDelta += self.on_grip_bl
        self.grip_b.DragDelta += self.on_grip_b
        self.grip_br.DragDelta += self.on_grip_br

    # -- resizing -----------------------------------------------------------
    # WPF will not resize a borderless AllowsTransparency window, so the
    # window moves its own edges. Each grip reports a delta; the edge being
    # dragged moves, and the opposite edge stays where it is.
    def _resize(self, left, top, right, bottom):
        width = self.Width if self.Width == self.Width else self.ActualWidth
        height = self.Height if self.Height == self.Height else self.ActualHeight

        if left:
            new_width = width - left
            if new_width >= self.MinWidth:
                self.Left = self.Left + left
                self.Width = new_width
        if right:
            self.Width = max(self.MinWidth, width + right)
        if top:
            new_height = height - top
            if new_height >= self.MinHeight:
                self.Top = self.Top + top
                self.Height = new_height
        if bottom:
            self.Height = max(self.MinHeight, height + bottom)

    def on_grip_l(self, sender, args):
        self._resize(args.HorizontalChange, 0, 0, 0)

    def on_grip_r(self, sender, args):
        self._resize(0, 0, args.HorizontalChange, 0)

    def on_grip_t(self, sender, args):
        self._resize(0, args.VerticalChange, 0, 0)

    def on_grip_b(self, sender, args):
        self._resize(0, 0, 0, args.VerticalChange)

    def on_grip_tl(self, sender, args):
        self._resize(args.HorizontalChange, args.VerticalChange, 0, 0)

    def on_grip_tr(self, sender, args):
        self._resize(0, args.VerticalChange, args.HorizontalChange, 0)

    def on_grip_bl(self, sender, args):
        self._resize(args.HorizontalChange, 0, 0, args.VerticalChange)

    def on_grip_br(self, sender, args):
        self._resize(0, 0, args.HorizontalChange, args.VerticalChange)

    def toggle_theme(self, sender, args):
        """Auto -> Dark -> Light -> Auto.

        Auto follows Revit's own canvas theme and is the default. The other
        two pin the tool regardless of what Revit is doing.
        """
        self.theme_mode = next_theme_mode(self.theme_mode)
        self.theme_name = resolve_theme(self.theme_mode)
        log(u'theme: {0} -> {1}'.format(self.theme_mode, self.theme_name))
        self.palette = apply_palette(self, self.theme_name)
        self._label_theme()
        # Rows are built in code, so their brushes do not follow a palette
        # swap on their own - rebuild them.
        if not self._loading:
            self.reload_categories()
            self.reload_filters()
        saved = load_settings()
        saved['theme_mode'] = self.theme_mode
        save_settings(saved)

    def _label_theme(self):
        if self.theme_mode != THEME_AUTO:
            self.theme_btn.Content = self.theme_mode.capitalize()
            self.theme_btn.ToolTip = (
                'Pinned to {0}. Click again to follow Revit.'.format(
                    self.theme_mode))
            return
        self.theme_btn.Content = 'Auto'
        following = revit_theme()
        if following:
            self.theme_btn.ToolTip = (
                'Following Revit, currently {0}. Click to pin dark or light.'.format(following))
        else:
            self.theme_btn.ToolTip = (
                'This Revit release does not report a canvas theme, so the '
                'tool is using dark. Click to pin dark or light.')
    def colour(self, key):
        return self.palette.get(key, '#9A9A9E')

    # -- system colour legend ---------------------------------------------
    def _fill_kinds(self):
        wanted = self.settings.get('sys_kind', 'containment')
        chosen = 0
        for index, kind in enumerate(SYSTEM_KINDS):
            self.kind_cb.Items.Add(kind['label'])
            if kind['key'] == wanted:
                chosen = index
        self.kind_cb.SelectedIndex = chosen

    def selected_kind(self):
        index = self.kind_cb.SelectedIndex
        if index < 0 or index >= len(SYSTEM_KINDS):
            return SYSTEM_KINDS[0]
        return SYSTEM_KINDS[index]

    def _fill_templates(self):
        """List every view template, and pick the one that has the filters.

        In order: the template used last time, the kind's own default, then
        whichever template holds the most matching filters. Each template
        that has any shows how many, so the right one can be seen at a
        glance. Never a silent fallback to whatever sorts first - that is
        what made 2.10 look as if it did nothing on a model without the
        default template.
        """
        self.template_cb.Items.Clear()
        kind = self.selected_kind()
        self.template_counts = []
        uses_filters = kind['source'] == 'filters' and kind['ready']
        for name, view in self.templates:
            count = matching_filter_count(view, kind) if uses_filters else 0
            self.template_counts.append(count)
            label = name if not count else u'{0}   ({1} matching)'.format(
                name, count)
            self.template_cb.Items.Add(label)

        names = [name for name, _view in self.templates]
        default = kind['template']
        chosen, why = choose_template(names, self.template_counts,
                                      self.settings.get('sys_template', ''),
                                      default, uses_filters)
        if uses_filters:
            log(u'template choice for {0}: "{1}" - {2}; default "{3}" {4}; '
                u'{5} of {6} templates have matching filters'.format(
                    kind['label'],
                    names[chosen] if chosen >= 0 else u'none', why, default,
                    u'present' if default in names else u'not in this model',
                    len([c for c in self.template_counts if c]),
                    len(names)))
        self.template_cb.SelectedIndex = chosen

    def selected_template(self):
        index = self.template_cb.SelectedIndex
        if index < 0 or index >= len(self.templates):
            return None
        return self.templates[index][1]

    def _fill_sys_text_types(self):
        body = self.settings.get('sys_text_type', '')
        head = self.settings.get('sys_head_type', '')
        default_id = eid_value(default_text_type_id())
        body_index = head_index = 0
        for index, (name, tid) in enumerate(self.text_types):
            self.sys_text_cb.Items.Add(name)
            self.sys_head_cb.Items.Add(name)
            if name == body:
                body_index = index
            elif not body and eid_value(tid) == default_id:
                body_index = index
            if name == head:
                head_index = index
            elif not head and eid_value(tid) == default_id:
                head_index = index
        if self.text_types:
            self.sys_text_cb.SelectedIndex = body_index
            self.sys_head_cb.SelectedIndex = head_index

    def _fill_sys_scales(self):
        wanted = self.settings.get('sys_scale', str(SYSTEM_DEFAULT_SCALE))
        chosen = SCALE_CHOICES.index(SYSTEM_DEFAULT_SCALE)
        for index, scale in enumerate(SCALE_CHOICES):
            self.sys_scale_cb.Items.Add('1:{0}'.format(scale))
            if str(scale) == str(wanted):
                chosen = index
        self.sys_scale_cb.SelectedIndex = chosen

    def selected_sys_scale(self):
        index = self.sys_scale_cb.SelectedIndex
        if index < 0 or index >= len(SCALE_CHOICES):
            return SYSTEM_DEFAULT_SCALE
        return SCALE_CHOICES[index]

    def _show_sys_distances(self):
        scale = self.selected_sys_scale()
        for key, box in (('swatch_w', self.sw_tb),
                         ('row_pitch', self.pitch_tb),
                         ('text_gap', self.gap_tb)):
            box.Text = format_mm(scaled_mm(self.sys_base[key], scale,
                                           SYSTEM_REFERENCE_SCALE))
        self.sh_tb.Text = format_mm(scaled_mm(self.current_height(), scale,
                                              SYSTEM_REFERENCE_SCALE))

    def line_weight(self):
        """The weight box, or None if it is not a usable number."""
        text = self.sys_lw_tb.Text.strip()
        try:
            weight = int(round(float(text)))
        except Exception:
            return None
        if weight < MIN_LINE_WEIGHT or weight > MAX_LINE_WEIGHT:
            return None
        return weight

    def current_height(self):
        kind = self.selected_kind()
        return self.sys_heights.get(kind['key'], kind['swatch_h'])

    def _capture_sys_distances(self):
        scale = self.selected_sys_scale()
        captured = {}
        for key, box in (('swatch_w', self.sw_tb), ('swatch_h', self.sh_tb),
                         ('row_pitch', self.pitch_tb),
                         ('text_gap', self.gap_tb)):
            try:
                value = float(box.Text.strip())
            except Exception:
                return None
            if value <= 0:
                return None
            captured[key] = unscaled_mm(value, scale, SYSTEM_REFERENCE_SCALE)
        return captured

    def reload_filters(self):
        """Re-read the chosen template and rebuild the preview list."""
        kind = self.selected_kind()
        template = self.selected_template()
        log(u'system tab: {0}, template {1}'.format(
            kind['label'], element_name(template) if template
            else u'none'))
        self.sys_rows = []
        self.filter_panel.Children.Clear()

        if not kind['ready']:
            self.sys_entries, self.sys_notes = [], []
            self.sys_status_tb.Text = (
                'This legend kind is not configured yet. Containment is the '
                'one that is.')
            self._update_status()
            return

        if kind['source'] == 'duct_systems':
            self.sys_entries, self.sys_notes = read_duct_systems(kind)
        elif kind['source'] == 'pipe_systems':
            self.sys_entries, self.sys_notes = read_pipe_systems(kind)
        else:
            self.sys_entries, self.sys_notes = read_template_filters(
                template, kind)
        for index, entry in enumerate(self.sys_entries):
            row = Border()
            row.Style = self.FindResource('RowEven' if index % 2 else 'RowOdd')

            grid = Grid()
            for width in (GridLength(26), GridLength(54),
                          GridLength(1, GridUnitType.Star)):
                column = ColumnDefinition()
                column.Width = width
                grid.ColumnDefinitions.Add(column)

            check = CheckBox()
            check.IsChecked = True
            check.VerticalAlignment = VerticalAlignment.Center
            check.Checked += self.toggled
            check.Unchecked += self.toggled

            swatch = Border()
            swatch.Width = 44
            swatch.Height = 15
            swatch.Background = brush(entry.hex_colour())
            swatch.BorderBrush = brush(self.colour('Ink'))
            swatch.BorderThickness = self.FindResource('HairThickness')
            swatch.VerticalAlignment = VerticalAlignment.Center
            swatch.HorizontalAlignment = HorizontalAlignment.Left
            Grid.SetColumn(swatch, 1)

            label = TextBlock()
            text = entry.label.upper() if self.sys_upper_cb.IsChecked \
                else entry.label
            if getattr(entry, 'group', ''):
                text = '{0}   ({1})'.format(text, entry.group)
            label.Text = text
            label.Foreground = brush(self.colour('Ink'))
            label.VerticalAlignment = VerticalAlignment.Center
            label.Margin = self.FindResource('LabelMargin')
            if entry.colour is None:
                label.ToolTip = 'No colour override on this filter'
            Grid.SetColumn(label, 2)

            grid.Children.Add(check)
            grid.Children.Add(swatch)
            grid.Children.Add(label)
            row.Child = grid

            self.filter_panel.Children.Add(row)
            self.sys_rows.append((check, entry, row))

        systems = kind['source'] in ('duct_systems', 'pipe_systems')
        noun = {'duct_systems': 'duct system',
                'pipe_systems': 'pipe system'}.get(kind['source'], 'filter')
        if not self.sys_entries:
            if systems:
                self.sys_status_tb.Text = (
                    'No {0} types are in use in this model.'.format(noun))
            else:
                self.sys_status_tb.Text = (
                    'No filters on this template are on {0} and named "{1}".'
                    .format(' / '.join(c.replace('OST_', '')
                                       for c in kind['categories']),
                            kind['name_token']))
        else:
            grey = len([e for e in self.sys_entries if e.colour is None])
            message = '{0} {1}(s) found'.format(len(self.sys_entries), noun)
            if grey:
                message += '  -  {0} with no colour override'.format(grey)
            self.sys_status_tb.Text = message
        self._update_status()

    def kind_changed(self, sender, args):
        if self._loading:
            return
        log(u'legend type: {0}'.format(self.selected_kind()['label']))
        # Bank whatever is on screen against the kind it was typed for,
        # before the boxes are refilled for the new one.
        captured = self._capture_sys_distances()
        if captured:
            self.sys_heights[self._kind_key] = captured.pop('swatch_h')
            self.sys_base = captured
        self._kind_key = self.selected_kind()['key']

        self._fill_templates()
        self._apply_kind()
        self.sys_name_tb.Text = self.selected_kind()['view_name']
        self._show_sys_distances()
        self.reload_filters()

    def _apply_kind(self):
        """A duct legend reads system types straight out of the model, so the
        template picker has nothing to say. Greyed rather than removed, so it
        stays clear that the setting exists and simply does not apply."""
        uses_template = self.selected_kind()['source'] == 'filters'
        self.template_cb.IsEnabled = uses_template
        self.template_lbl.Opacity = 1.0 if uses_template else 0.45

    def template_changed(self, sender, args):
        if not self._loading:
            self.reload_filters()

    def sys_scale_opening(self, sender, args):
        if not self._loading:
            self._sys_captured = self._capture_sys_distances()

    def sys_scale_changed(self, sender, args):
        if self._loading:
            return
        captured = self._sys_captured or self._capture_sys_distances()
        if captured:
            self.sys_heights[self._kind_key] = captured.pop('swatch_h')
            self.sys_base = captured
        self._sys_captured = None
        self._show_sys_distances()

    def sys_upper_toggled(self, sender, args):
        if not self._loading:
            self.reload_filters()

    def sys_select_all(self, sender, args):
        for check, _entry, _row in self.sys_rows:
            check.IsChecked = True

    def sys_clear_all(self, sender, args):
        for check, _entry, _row in self.sys_rows:
            check.IsChecked = False

    def tab_changed(self, sender, args):
        # SelectionChanged bubbles up from every ComboBox inside the tabs, so
        # only a change of the TabControl itself is a change of tab.
        if self._loading or getattr(args, 'OriginalSource', None) is not \
                self.tabs:
            return
        log(u'tab: {0}'.format(u'System Colour Legend'
                               if self.tabs.SelectedIndex == 1
                               else u'Family Legend'))
        self._update_status()

    def _restore_case(self):
        mode = self.settings.get('text_case', DEFAULT_CASE)
        buttons = {CASE_ASIS: self.case_asis,
                   CASE_UPPER: self.case_upper,
                   CASE_CAMEL: self.case_camel}
        buttons.get(mode, self.case_asis).IsChecked = True

    def _selected_case(self):
        if self.case_upper.IsChecked:
            return CASE_UPPER
        if self.case_camel.IsChecked:
            return CASE_CAMEL
        return CASE_ASIS

    def selected_phase_id(self):
        index = self.phase_cb.SelectedIndex
        if index <= 0 or index > len(self.phases):
            return None
        return self.phases[index - 1][1]

    def selected_phase_name(self):
        index = self.phase_cb.SelectedIndex
        if index <= 0 or index > len(self.phases):
            return 'All phases'
        return self.phases[index - 1][0]

    def reload_categories(self):
        """Re-read the model for the chosen phase, remembering the ticks."""
        ticked = set(info.name for check, info, _row in self.rows
                     if check.IsChecked)

        phase_id = self.selected_phase_id()
        key = eid_value(phase_id) if phase_id is not None else 'all'
        if key not in self.cache:
            self.cache[key] = collect_used_types(phase_id)
        self.infos = self.cache[key]

        self.rows = []
        self.list_panel.Children.Clear()
        for index, info in enumerate(self.infos):
            row = Border()
            row.Style = self.FindResource('RowEven' if index % 2 else 'RowOdd')

            grid = Grid()
            stretch = ColumnDefinition()
            stretch.Width = GridLength(1, GridUnitType.Star)
            fixed = ColumnDefinition()
            fixed.Width = GridLength(70)
            grid.ColumnDefinitions.Add(stretch)
            grid.ColumnDefinitions.Add(fixed)

            check = CheckBox()
            check.Content = info.name
            check.IsChecked = info.name in ticked
            check.Checked += self.toggled
            check.Unchecked += self.toggled

            count = TextBlock()
            count.Text = str(info.count)
            count.FontSize = 11
            count.Foreground = brush(self.colour('Muted'))
            count.HorizontalAlignment = HorizontalAlignment.Center
            count.VerticalAlignment = VerticalAlignment.Center

            pill = Border()
            pill.Style = self.FindResource('Pill')
            pill.Child = count
            Grid.SetColumn(pill, 1)

            grid.Children.Add(check)
            grid.Children.Add(pill)
            row.Child = grid

            self.list_panel.Children.Add(row)
            self.rows.append((check, info, row))

        self._fill_params()
        self.filter_changed(None, None)
        self._update_status()

    # -- events ------------------------------------------------------------
    def drag_window(self, sender, args):
        """No system title bar, so the header bar moves the window. While
        parked a double click opens it; a single click drags the bar."""
        if self.drawer.header_down(args):
            return
        try:
            self.DragMove()
        except Exception:
            pass

    def on_shrink(self, sender, args):
        self.drawer.toggle()

    def on_key(self, sender, args):
        """Escape closes the window, as pyRevit's handler used to - once the
        drawer has had its look, so Escape on a parked bar reopens it."""
        try:
            if not args.Handled and args.Key == Key.Escape:
                args.Handled = True
                self.cancel(None, args)
        except Exception:
            swallowed()

    def phase_changed(self, sender, args):
        if not self._loading:
            self.reload_categories()

    def scale_changed(self, sender, args):
        """Rescale the distance boxes so they stay constant on paper.

        Whatever is currently in the boxes is taken as the truth first, so a
        hand-typed override is carried across the change rather than lost.
        """
        if self._loading:
            return
        captured = self._captured_before_scale or self._capture_distances()
        if captured:
            self.base = captured
        self._captured_before_scale = None
        self._show_distances()
        self._update_status()

    def scale_opening(self, sender, args):
        """Snapshot the boxes against the old scale before it changes."""
        if not self._loading:
            self._captured_before_scale = self._capture_distances()

    def toggled(self, sender, args):
        self._update_status()

    def combine_toggled(self, sender, args):
        self._update_status()

    def filter_changed(self, sender, args):
        needle = self.filter_tb.Text.lower().strip()
        for check, info, row in self.rows:
            visible = needle in info.name.lower()
            row.Visibility = Visibility.Visible if visible \
                else Visibility.Collapsed

    def select_all(self, sender, args):
        for check, _info, row in self.rows:
            if row.Visibility == Visibility.Visible:
                check.IsChecked = True

    def clear_all(self, sender, args):
        for check, _info, _row in self.rows:
            check.IsChecked = False

    def create(self, sender, args):
        if self.drawer.intercept():
            return                      # Enter on a parked window reopens it
        log(u'Create pressed on the {0} tab'.format(
            u'System Colour Legend' if self.tabs.SelectedIndex == 1
            else u'Family Legend'))
        if self.tabs.SelectedIndex == 1:
            self.create_system()
        else:
            self.create_family()

    def create_system(self):
        kind = self.selected_kind()
        if not kind['ready']:
            self.refuse('This legend kind is not configured yet.')
            return

        chosen = [entry for check, entry, _row in self.sys_rows
                  if check.IsChecked]
        if not chosen:
            self.refuse('Tick at least one filter.')
            return

        captured = self._capture_sys_distances()
        if captured is None:
            self.refuse(
                'Swatch and spacing values must all be '
                'positive numbers in mm.')
            return
        weight = self.line_weight()
        if weight is None:
            self.refuse(
                'Line weight must be a whole number '
                'from 1 to 16.')
            return

        self.sys_heights[self._kind_key] = captured['swatch_h']
        self.sys_base = dict((k, v) for k, v in captured.items()
                             if k != 'swatch_h')

        scale = self.selected_sys_scale()
        template = self.selected_template()
        text_index = max(0, self.sys_text_cb.SelectedIndex)
        head_index = max(0, self.sys_head_cb.SelectedIndex)
        name = self.sys_name_tb.Text.strip() or kind['view_name']

        self.result = chosen
        self.mode = 'system'
        self.opts = {
            'kind': kind,
            'theme': self.theme_name,
            'theme_mode': self.theme_mode,
            'debug': bool(self.debug_cb.IsChecked),
            'heading': kind['heading'],
            'region_prefix': kind['region_prefix'],
            'style': kind['style'],
            'centreline': kind.get('centreline', False),
            'line_weight': weight,
            'template_name': element_name(template) if template else '',
            'scale': scale,
            'view_name': name,
            'upper': bool(self.sys_upper_cb.IsChecked),
            'text_type_id': self.text_types[text_index][1],
            'text_type_name': self.text_types[text_index][0],
            'head_type_id': self.text_types[head_index][1],
            'head_type_name': self.text_types[head_index][0],
            'swatch_w': scaled_mm(captured['swatch_w'], scale,
                                  SYSTEM_REFERENCE_SCALE),
            'swatch_h': scaled_mm(captured['swatch_h'], scale,
                                  SYSTEM_REFERENCE_SCALE),
            'row_pitch': scaled_mm(captured['row_pitch'], scale,
                                   SYSTEM_REFERENCE_SCALE),
            'text_gap': scaled_mm(captured['text_gap'], scale,
                                  SYSTEM_REFERENCE_SCALE),
            'heading_gap': scaled_mm(SYS_HEADING_GAP_MM, scale,
                                     SYSTEM_REFERENCE_SCALE),
        }

        saved = load_settings()
        saved.update({
            'sys_kind': kind['key'],
            'sys_template': self.opts['template_name'],
            'sys_scale': str(scale),
            'sys_text_type': self.opts['text_type_name'],
            'sys_head_type': self.opts['head_type_name'],
            'sys_swatch_w': format_mm(captured['swatch_w']),
            'sys_swatch_h': format_kv_list(self.sys_heights),
            'sys_line_weight': str(weight),
            'sys_row_pitch': format_mm(captured['row_pitch']),
            'sys_text_gap': format_mm(captured['text_gap']),
            'sys_view_name': name,
            'sys_upper': '1' if self.opts['upper'] else '0',
            'theme_mode': self.theme_mode,
            'debug': '1' if self.debug_cb.IsChecked else '0',
        })
        save_settings(saved)
        self.Close()

    def create_family(self):
        chosen = [info for check, info, _row in self.rows if check.IsChecked]
        if not chosen:
            self.refuse('Tick at least one category.')
            return
        if not self.text_cb.Items.Count:
            self.refuse('This project has no text note type.')
            return

        captured = self._capture_distances()
        if captured is None:
            self.refuse(
                'Row, text and column distances must all '
                'be positive numbers in mm.')
            return
        self.base = captured

        scale = self.selected_scale()
        text_index = max(0, self.text_cb.SelectedIndex)
        param_index = max(0, self.param_cb.SelectedIndex)

        self.result = chosen
        self.mode = 'family'
        self.opts = {
            'theme': self.theme_name,
            'theme_mode': self.theme_mode,
            'debug': bool(self.debug_cb.IsChecked),
            'phase': self.selected_phase_name(),
            'name_param': self.param_cb.Items[param_index],
            'text_type_id': self.text_types[text_index][1],
            'text_type_name': self.text_types[text_index][0],
            'text_case': self._selected_case(),
            'combined': bool(self.combine_cb.IsChecked),
            'scale': scale,
            # handed on as real view millimetres at the chosen scale
            'row_spacing': scaled_mm(captured['row'], scale),
            'text_offset': scaled_mm(captured['text'], scale),
            'column_spacing': scaled_mm(captured['column'], scale),
        }

        saved = load_settings()
        saved.update({
            'phase': self.opts['phase'],
            'name_param': self.opts['name_param'],
            'text_type': self.opts['text_type_name'],
            'text_case': self.opts['text_case'],
            'combined': '1' if self.opts['combined'] else '0',
            'scale': str(scale),
            'row_spacing': format_mm(captured['row']),
            'text_offset': format_mm(captured['text']),
            'column_spacing': format_mm(captured['column']),
            'theme_mode': self.theme_mode,
            'debug': '1' if self.debug_cb.IsChecked else '0',
        })
        save_settings(saved)
        self.Close()

    def cancel(self, sender, args):
        log(u'closed with {0}'.format(
            u'the X' if sender is self.close_btn else
            u'Escape' if sender is None else u'Cancel'))
        self.result = []
        self.Close()

    # -- helpers -----------------------------------------------------------
    def say(self, text, warn=False):
        """The footer line. Orange when it is telling you why nothing will
        happen, rather than a grey note that is easy to miss."""
        self.status_tb.Text = text
        try:
            self.status_tb.SetResourceReference(
                TextBlock.ForegroundProperty, 'Orange' if warn else 'Muted')
        except Exception:
            swallowed()

    def refuse(self, text):
        """Create was pressed and cannot go ahead - say so, and log it."""
        log(u'create refused: {0}'.format(text))
        self.say(text, warn=True)

    def _blocker(self, system_tab):
        """Why Create cannot run on this tab right now, or None."""
        if system_tab:
            kind = self.selected_kind()
            if not kind['ready']:
                return u'This legend kind is not configured yet.'
            if not self.sys_entries:
                if kind['source'] == 'filters':
                    template = self.selected_template()
                    if any(getattr(self, 'template_counts', [])):
                        return (u'No matching filters on "{0}" - pick a '
                                u'template marked "matching".'.format(
                                    element_name(template) if template
                                    else u'this template'))
                    return (u'No view template in this model has {0} filters '
                            u'named "{1}".'.format(
                                u'/'.join(c.replace('OST_', '')
                                          for c in kind['categories'][:1]),
                                kind['name_token']))
                noun = {'duct_systems': 'duct system',
                        'pipe_systems': 'pipe system'}.get(kind['source'],
                                                           'system')
                return u'No {0} types are in use in this model.'.format(noun)
            if not any(c.IsChecked for c, _e, _r in self.sys_rows):
                return u'Tick at least one row.'
            return None

        if not self.family_ready:
            return (u'Family Legend needs a legend holding one legend '
                    u'component - none in this model. Drag any family type '
                    u'into a legend view, then reopen.')
        if not self.rows:
            return u'Nothing placed on this phase.'
        if not any(c.IsChecked for c, _i, _r in self.rows):
            return u'Tick at least one category.'
        return None

    def _update_status(self):
        try:
            system_tab = self.tabs.SelectedIndex == 1
        except Exception:
            swallowed()
            system_tab = False

        blocker = self._blocker(system_tab)
        try:
            self.create_btn.IsEnabled = blocker is None
        except Exception:
            swallowed()
        if blocker:
            self.say(blocker, warn=True)
            return

        if system_tab:
            picked = len([c for c, _e, _r in self.sys_rows if c.IsChecked])
            self.say(u'{0} of {1} rows  -  1:{2}'.format(
                picked, len(self.sys_rows), self.selected_sys_scale()))
            return

        chosen = [i for c, i, _r in self.rows if c.IsChecked]
        types = sum(i.count for i in chosen)
        if not chosen:
            self.say(u'{0} categories on this phase'.format(len(self.rows)))
            return
        if self.combine_cb.IsChecked and len(chosen) > 1:
            shape = '1 combined legend, {0} columns'.format(len(chosen))
        else:
            shape = '{0} legend{1}'.format(len(chosen),
                                           '' if len(chosen) == 1 else 's')
        self.say(u'{0}  -  {1} types  -  1:{2}'.format(
            shape, types, self.selected_scale()))


class DoneWindow(forms.WPFWindow):
    """Completion prompt, and the one question the run asks.

    The headline pulses via a storyboard in the XAML. Asking whether to open
    the new legend here, rather than in a second window, keeps the promise
    that the summary is the only thing shown after a run.
    """

    def __init__(self, xaml_path, legends, components, skipped, scale,
                 theme_name='dark', first_name='', debug=False):
        load_window(self, xaml_path)
        self.version_tb.Text = 'v' + __version__
        apply_palette(self, theme_name)
        self.drawer = make_drawer(self)
        self.open_requested = False

        self.header_bar.MouseLeftButtonDown += self.drag_window
        self.shrink_btn.Click += self.on_shrink
        self.close_btn.Click += self.dismiss
        self.done_btn.Click += self.dismiss
        self.open_btn.Click += self.open_clicked

        where = ('see the debug log in %APPDATA%\\RevoBIM.' if debug else
                 'tick Debug and run again to see why.')
        if not legends:
            summary = 'Nothing was drawn - ' + where
            self.flash_tb.Text = 'That one needs a look.'
        else:
            bits = ['{0} legend{1}'.format(legends,
                                           '' if legends == 1 else 's'),
                    '{0} row{1}'.format(components,
                                        '' if components == 1 else 's')]
            summary = ' and '.join(bits) + ' at 1:{0}.'.format(scale)
        if skipped:
            summary += '  {0} skipped - {1}'.format(skipped, where)
        self.summary_tb.Text = summary

        if legends and first_name:
            several = legends > 1
            self.ask_tb.Text = u'Open {0}{1} now?'.format(
                first_name, ', the first of them,' if several else '')
            self.open_btn.Content = 'Open legend'
            self.done_btn.Content = 'Not now'
        else:
            # nothing to open - one plain way out
            self.ask_tb.Text = ''
            self.open_btn.Visibility = Visibility.Collapsed
            self.done_btn.Content = 'Close'
            self.done_btn.IsDefault = True

    def drag_window(self, sender, args):
        if self.drawer.header_down(args):
            return
        try:
            self.DragMove()
        except Exception:
            pass

    def on_shrink(self, sender, args):
        self.drawer.toggle()

    def open_clicked(self, sender, args):
        if self.drawer.intercept():
            return
        self.open_requested = True
        self.Close()

    def dismiss(self, sender, args):
        if sender is not self.close_btn and self.drawer.intercept():
            return
        self.open_requested = False
        self.Close()
