# -*- coding: utf-8 -*-
"""RevoBIM VlookUp - the main window.

Nothing is written to the model until Apply is pressed, and Apply builds the
plan again from scratch before it asks. Every handler is wrapped so a failure
lands in the status line rather than in a raw pyRevit stack trace.
"""

import clr
import os
import traceback

# The System.Windows namespace only carries the names of assemblies that have
# already been referenced. Every module that imports a WPF type has to ask for
# these itself - importing another module that happens to ask for them is not
# enough, because the import above runs before that module is reached.
for _asm in ('PresentationCore', 'PresentationFramework', 'WindowsBase', 'System.Xaml'):
    try:
        clr.AddReference(_asm)
    except Exception:
        pass

from System.Windows import (Thickness, Visibility, GridLength, GridUnitType,
                            TextTrimming, VerticalAlignment, FontWeights)
from System.Windows.Controls import (Grid, ColumnDefinition, RowDefinition, TextBlock,
                                     Button, ComboBox, CheckBox, ToolTip)
from System.Windows.Input import Key

import vlookup_core as core
import vlookup_ui as ui
import xlsx_reader as xr

PREVIEW_ROWS = 40
MIN_COL_WIDTH = 96
MAX_CELL_CHARS = 46


def ui_safe(method):
    def wrapper(self, *args):
        try:
            return method(self, *args)
        except Exception:
            self.fail(traceback.format_exc())
    wrapper.__name__ = getattr(method, '__name__', 'handler')
    return wrapper


class VlookUpWindow(object):

    def __init__(self, doc, uidoc, version):
        self.doc = doc
        self.uidoc = uidoc
        self.version = version
        self.theme = ui.load_theme()
        self.window = ui.load_window('VlookUp.xaml', version, self.theme)
        ui.set_icon(self.window)

        self.workbook = None
        self.sheet = None
        self.headers = []
        self.rows = []
        self.elements = []
        self.scoped = []
        self.key_options = []
        self.instance_targets = []
        self.type_targets = []
        self.map_rows = []              # (column index, ComboBox)
        self.cat_boxes = []             # CheckBox controls
        self.remembered_map = {}        # column caption -> target, survives rebuilds
        self.pending_key = u''
        self.pending_cats = None
        self.loading = True

        self._find_controls()
        self._wire()
        self._populate_static()
        self._restore()
        self.loading = False
        self.refresh_scope()
        self.update_buttons()

    # ------------------------------------------------------------- plumbing

    def _find_controls(self):
        w = self.window
        self.FilePathBox = w.FindName('FilePathBox')
        self.BrowseBtn = w.FindName('BrowseBtn')
        self.ReloadBtn = w.FindName('ReloadBtn')
        self.SheetCombo = w.FindName('SheetCombo')
        self.HeaderRowBox = w.FindName('HeaderRowBox')
        self.LookupCombo = w.FindName('LookupCombo')
        self.IgnoreCaseChk = w.FindName('IgnoreCaseChk')
        self.TrimChk = w.FindName('TrimChk')
        self.NumericChk = w.FindName('NumericChk')
        self.DuplicateCombo = w.FindName('DuplicateCombo')
        self.SheetInfoLabel = w.FindName('SheetInfoLabel')
        self.ScopeCombo = w.FindName('ScopeCombo')
        self.KeyParamCombo = w.FindName('KeyParamCombo')
        self.CatSearchBox = w.FindName('CatSearchBox')
        self.CatAllBtn = w.FindName('CatAllBtn')
        self.CatNoneBtn = w.FindName('CatNoneBtn')
        self.CatPanel = w.FindName('CatPanel')
        self.CatScroller = w.FindName('CatScroller')
        self.ScopeInfoLabel = w.FindName('ScopeInfoLabel')
        self.PreviewGrid = w.FindName('PreviewGrid')
        self.PreviewScroller = w.FindName('PreviewScroller')
        self.PreviewHintLabel = w.FindName('PreviewHintLabel')
        self.MappingPanel = w.FindName('MappingPanel')
        self.MappingScroller = w.FindName('MappingScroller')
        self.AutoMatchBtn = w.FindName('AutoMatchBtn')
        self.ClearMapBtn = w.FindName('ClearMapBtn')
        self.SkipBlanksChk = w.FindName('SkipBlanksChk')
        self.TypeParamsChk = w.FindName('TypeParamsChk')
        self.ProfileCombo = w.FindName('ProfileCombo')
        self.SaveProfileBtn = w.FindName('SaveProfileBtn')
        self.DeleteProfileBtn = w.FindName('DeleteProfileBtn')
        self.PreviewBtn = w.FindName('PreviewBtn')
        self.ApplyBtn = w.FindName('ApplyBtn')
        self.StatusLabel = w.FindName('StatusLabel')

    def _wire(self):
        self.BrowseBtn.Click += self.on_browse
        self.ReloadBtn.Click += self.on_reload
        self.SheetCombo.SelectionChanged += self.on_sheet_changed
        self.HeaderRowBox.LostFocus += self.on_header_row
        self.HeaderRowBox.KeyDown += self.on_header_key
        self.LookupCombo.SelectionChanged += self.on_lookup_changed
        self.ScopeCombo.SelectionChanged += self.on_scope_changed
        self.KeyParamCombo.SelectionChanged += self.on_key_changed
        self.CatSearchBox.TextChanged += self.on_cat_search
        self.CatAllBtn.Click += self.on_cat_all
        self.CatNoneBtn.Click += self.on_cat_none
        self.AutoMatchBtn.Click += self.on_auto_match
        self.ClearMapBtn.Click += self.on_clear_map
        self.TypeParamsChk.Checked += self.on_type_params
        self.TypeParamsChk.Unchecked += self.on_type_params
        self.ProfileCombo.SelectionChanged += self.on_profile_changed
        self.SaveProfileBtn.Click += self.on_save_profile
        self.DeleteProfileBtn.Click += self.on_delete_profile
        self.PreviewBtn.Click += self.on_check
        self.ApplyBtn.Click += self.on_apply
        self.window.PreviewKeyDown += self.on_key
        self.window.Closing += self.on_closing

    def _populate_static(self):
        for _key, label in core.SCOPE_LABELS:
            self.ScopeCombo.Items.Add(label)
        self.ScopeCombo.SelectedIndex = 0
        for _key, label in core.DUP_LABELS:
            self.DuplicateCombo.Items.Add(label)
        self.DuplicateCombo.SelectedIndex = 0
        self.reload_profiles()

    def show(self):
        self.window.ShowDialog()

    def status(self, text):
        try:
            self.StatusLabel.Text = text
            self.StatusLabel.Foreground = self.window.FindResource('TextMuted')
        except Exception:
            pass

    def warn(self, text):
        try:
            self.StatusLabel.Text = text
            self.StatusLabel.Foreground = self.window.FindResource('AccentOrange')
        except Exception:
            pass

    def fail(self, detail):
        lines = detail.strip().split('\n')
        try:
            self.StatusLabel.Text = lines[-1]
            self.StatusLabel.Foreground = self.window.FindResource('WarnRed')
        except Exception:
            pass
        try:
            ui.show_results(self.window, self.version, u'Something went wrong.',
                            [(u'Detail', lines, True)], u'', self.theme, u'VlookUp error')
        except Exception:
            pass

    # ------------------------------------------------------------- settings

    def _restore(self):
        self._apply_values(core.load_settings())

    def _apply_values(self, values):
        was_loading = self.loading
        self.loading = True
        try:
            self.pending_key = values.get('key_parameter') or u''
            self.pending_cats = [c for c in (values.get('categories') or u'').split(u'||') if c]
            self.remembered_map = {}
            for caption, target in core.decode_mapping(values.get('mapping', [])):
                self.remembered_map[caption] = target

            self.set_combo(self.ScopeCombo, self._scope_label(values.get('scope')))
            self.IgnoreCaseChk.IsChecked = values.get('ignore_case', '1') == '1'
            self.TrimChk.IsChecked = values.get('trim', '1') == '1'
            self.NumericChk.IsChecked = values.get('numeric', '1') == '1'
            self.SkipBlanksChk.IsChecked = values.get('skip_blanks', '1') == '1'
            self.TypeParamsChk.IsChecked = values.get('type_parameters', '0') == '1'
            self.set_combo(self.DuplicateCombo, self._dup_label(values.get('duplicates')))

            path = values.get('file') or ''
            if path and os.path.isfile(path):
                self.load_workbook(path, values.get('sheet'),
                                   values.get('header_row'), values.get('lookup_column'))
            elif path:
                self.FilePathBox.Text = path
                self.SheetInfoLabel.Text = u'The last spreadsheet used is no longer at that path.'
        finally:
            self.loading = was_loading

    def _collect_values(self):
        return {
            'settings_version': str(core.SETTINGS_VERSION),
            'file': self.FilePathBox.Text or '',
            'sheet': self.combo_text(self.SheetCombo),
            'header_row': str(self.header_row()),
            'lookup_column': self.combo_text(self.LookupCombo),
            'scope': self.scope_key(),
            'categories': u'||'.join(self.selected_categories()),
            'key_parameter': self.combo_text(self.KeyParamCombo),
            'ignore_case': '1' if self.IgnoreCaseChk.IsChecked else '0',
            'trim': '1' if self.TrimChk.IsChecked else '0',
            'numeric': '1' if self.NumericChk.IsChecked else '0',
            'duplicates': self.duplicates_key(),
            'skip_blanks': '1' if self.SkipBlanksChk.IsChecked else '0',
            'type_parameters': '1' if self.TypeParamsChk.IsChecked else '0',
            'mapping': core.encode_mapping(self.mapping_pairs_by_caption()),
        }

    @ui_safe
    def on_closing(self, sender, args):
        try:
            core.save_settings(self._collect_values())
        except Exception:
            pass

    # ------------------------------------------------------------- combo helpers

    def combo_text(self, combo):
        item = combo.SelectedItem
        return core.as_text(item) if item is not None else u''

    def set_combo(self, combo, text, fallback_index=0):
        if text:
            for i in range(combo.Items.Count):
                if core.as_text(combo.Items[i]) == core.as_text(text):
                    combo.SelectedIndex = i
                    return True
        if combo.Items.Count and combo.SelectedIndex < 0 and fallback_index >= 0:
            combo.SelectedIndex = fallback_index
        return False

    def _scope_label(self, key):
        for item, label in core.SCOPE_LABELS:
            if item == key:
                return label
        return core.SCOPE_LABELS[0][1]

    def scope_key(self):
        label = self.combo_text(self.ScopeCombo)
        for key, text in core.SCOPE_LABELS:
            if text == label:
                return key
        return core.SCOPE_SELECTION

    def _dup_label(self, key):
        for item, label in core.DUP_LABELS:
            if item == key:
                return label
        return core.DUP_LABELS[0][1]

    def duplicates_key(self):
        label = self.combo_text(self.DuplicateCombo)
        for key, text in core.DUP_LABELS:
            if text == label:
                return key
        return core.DUP_FIRST

    def header_row(self):
        try:
            return max(1, int(core.as_text(self.HeaderRowBox.Text).strip()))
        except Exception:
            return 1

    # ------------------------------------------------------------- spreadsheet

    @ui_safe
    def on_browse(self, sender, args):
        path = ui.pick_open_file('Choose the spreadsheet', self.FilePathBox.Text)
        if not path:
            return
        self.load_workbook(path)

    @ui_safe
    def on_reload(self, sender, args):
        path = self.FilePathBox.Text
        if not path:
            self.warn(u'No spreadsheet chosen yet.')
            return
        self.load_workbook(path, self.combo_text(self.SheetCombo),
                           str(self.header_row()), self.combo_text(self.LookupCombo))

    def load_workbook(self, path, sheet_name=None, header_row=None, lookup=None):
        was_loading = self.loading
        self.loading = True
        try:
            try:
                self.workbook = xr.read_workbook(path)
            except xr.SpreadsheetError as err:
                self.workbook = None
                message = core.as_text(err)
                self.warn(message.split('\n')[0])
                ui.prompt(self.window, u'Spreadsheet', message, u'OK', u'Close',
                          None, self.theme)
                return
            self.FilePathBox.Text = path
            self.SheetCombo.Items.Clear()
            for name in self.workbook.sheet_names():
                self.SheetCombo.Items.Add(name)
            if header_row:
                self.HeaderRowBox.Text = core.as_text(header_row)
            self.set_combo(self.SheetCombo, sheet_name)
        finally:
            self.loading = was_loading
        self.refresh_sheet(lookup)

    def refresh_sheet(self, lookup=None):
        if self.workbook is None:
            return
        self.sheet = self.workbook.sheet(self.combo_text(self.SheetCombo))
        if self.sheet is None:
            return
        row_index = self.header_row()
        self.headers = xr.header_names(self.sheet, row_index)
        self.rows = xr.data_rows(self.sheet, row_index)

        was_loading = self.loading
        self.loading = True
        try:
            wanted = lookup if lookup else self.combo_text(self.LookupCombo)
            self.LookupCombo.Items.Clear()
            for i, caption in enumerate(self.headers):
                self.LookupCombo.Items.Add(self._column_label(i, caption))
            self.set_combo(self.LookupCombo, wanted)
        finally:
            self.loading = was_loading

        note = u'{0} : {1} data rows, {2} columns'.format(
            self.sheet.name, len(self.rows), self.sheet.width)
        if self.workbook.stamp:
            note += u'  \u2022  saved {0}'.format(self.workbook.stamp)
        for warning in self.workbook.warnings:
            note += u'  \u2022  ' + warning
        self.SheetInfoLabel.Text = note

        self.build_preview()
        self.build_mapping()
        self.update_buttons()
        self.status(u'Loaded {0}.'.format(os.path.basename(self.FilePathBox.Text)))

    def _column_label(self, index, caption=None):
        if caption is None:
            caption = self.headers[index] if index < len(self.headers) else u''
        return u'{0}  {1}'.format(xr.column_letter(index), caption)

    def lookup_index(self):
        index = self.LookupCombo.SelectedIndex
        return index if index >= 0 else -1

    @ui_safe
    def on_sheet_changed(self, sender, args):
        if self.loading:
            return
        self.refresh_sheet()

    @ui_safe
    def on_header_row(self, sender, args):
        if self.loading or self.workbook is None:
            return
        self.refresh_sheet()

    @ui_safe
    def on_header_key(self, sender, args):
        if args.Key == Key.Enter:
            self.on_header_row(sender, args)

    @ui_safe
    def on_lookup_changed(self, sender, args):
        if self.loading:
            return
        self.build_preview()
        self.build_mapping()
        self.update_buttons()

    # ------------------------------------------------------------- preview

    def build_preview(self):
        grid = self.PreviewGrid
        grid.Children.Clear()
        grid.ColumnDefinitions.Clear()
        grid.RowDefinitions.Clear()
        if not self.headers:
            return

        lookup = self.lookup_index()
        columns = len(self.headers)
        shown = self.rows[:PREVIEW_ROWS]

        number_column = ColumnDefinition()
        number_column.Width = GridLength(46)
        grid.ColumnDefinitions.Add(number_column)
        for _i in range(columns):
            definition = ColumnDefinition()
            definition.Width = GridLength(1, GridUnitType.Auto)
            definition.MinWidth = MIN_COL_WIDTH
            grid.ColumnDefinitions.Add(definition)
        for _i in range(len(shown) + 1):
            grid.RowDefinitions.Add(RowDefinition())

        corner = self._cell_text(u'row', True)
        Grid.SetRow(corner, 0)
        Grid.SetColumn(corner, 0)
        grid.Children.Add(corner)

        for i in range(columns):
            button = Button()
            button.Content = self._column_label(i)
            try:
                button.Style = self.window.FindResource('ColHeaderButton')
                if i == lookup:
                    button.Foreground = self.window.FindResource('AccentOrange')
                    button.FontWeight = FontWeights.SemiBold
            except Exception:
                pass
            button.Tag = i
            button.Click += self.on_header_click
            Grid.SetRow(button, 0)
            Grid.SetColumn(button, i + 1)
            grid.Children.Add(button)

        first_data_row = self.header_row()
        for r, row in enumerate(shown):
            number = self._cell_text(core.as_text(first_data_row + r + 1), False, True)
            Grid.SetRow(number, r + 1)
            Grid.SetColumn(number, 0)
            grid.Children.Add(number)
            for c in range(columns):
                text = row[c] if c < len(row) else u''
                cell = self._cell_text(text, False, False, c == lookup)
                Grid.SetRow(cell, r + 1)
                Grid.SetColumn(cell, c + 1)
                grid.Children.Add(cell)

        if len(self.rows) > PREVIEW_ROWS:
            self.PreviewHintLabel.Text = (
                u'First {0} of {1} rows. Click a column header to use it as the lookup column.'
                .format(PREVIEW_ROWS, len(self.rows)))
        else:
            self.PreviewHintLabel.Text = u'Click a column header to use it as the lookup column.'

    def _cell_text(self, text, header=False, muted=False, highlight=False):
        block = TextBlock()
        value = core.as_text(text)
        if len(value) > MAX_CELL_CHARS:
            block.Text = value[:MAX_CELL_CHARS] + u'\u2026'
            try:
                tip = ToolTip()
                tip.Content = value
                tip.Style = self.window.FindResource('DarkToolTip')
                block.ToolTip = tip
            except Exception:
                pass
        else:
            block.Text = value
        try:
            if header or muted:
                block.Style = self.window.FindResource('MutedText')
            else:
                block.Style = self.window.FindResource('BodyText')
            if highlight:
                block.Foreground = self.window.FindResource('AccentOrange')
        except Exception:
            pass
        block.Margin = Thickness(6, 2, 6, 2)
        block.TextTrimming = TextTrimming.CharacterEllipsis
        return block

    @ui_safe
    def on_header_click(self, sender, args):
        index = sender.Tag
        if index is None:
            return
        if 0 <= index < self.LookupCombo.Items.Count:
            self.LookupCombo.SelectedIndex = index

    # ------------------------------------------------------------- mapping

    def target_items(self):
        items = [core.NONE_TARGET]
        items.extend(self.instance_targets)
        if self.TypeParamsChk.IsChecked:
            items.extend([core.join_target(name, True) for name in self.type_targets])
        return items

    def mapping_pairs(self):
        """[(column index, target)] for everything actually mapped."""
        out = []
        for index, combo in self.map_rows:
            target = self.combo_text(combo)
            if target and target != core.NONE_TARGET:
                out.append((index, target))
        return out

    def mapping_pairs_by_caption(self):
        """What is on screen now, plus anything remembered but not shown."""
        out = []
        live = {}
        for index, combo in self.map_rows:
            target = self.combo_text(combo)
            caption = self.headers[index] if index < len(self.headers) else u''
            live[caption] = True
            if target and target != core.NONE_TARGET:
                out.append((caption, target))
        for caption, target in self.remembered_map.items():
            if caption not in live and target and target != core.NONE_TARGET:
                out.append((caption, target))
        return out

    def build_mapping(self):
        panel = self.MappingPanel
        panel.Children.Clear()
        self.map_rows = []
        if not self.headers:
            return

        lookup = self.lookup_index()
        items = self.target_items()
        was_loading = self.loading
        self.loading = True
        try:
            for i, caption in enumerate(self.headers):
                if i == lookup:
                    continue
                row = Grid()
                row.Margin = Thickness(0, 0, 0, 3)
                left = ColumnDefinition()
                right = ColumnDefinition()
                right.Width = GridLength(228)
                row.ColumnDefinitions.Add(left)
                row.ColumnDefinitions.Add(right)

                label = TextBlock()
                label.Text = self._column_label(i, caption)
                label.TextTrimming = TextTrimming.CharacterEllipsis
                label.Margin = Thickness(2, 0, 6, 0)
                label.VerticalAlignment = VerticalAlignment.Center
                try:
                    label.Style = self.window.FindResource('BodyText')
                    tip = ToolTip()
                    tip.Content = caption
                    tip.Style = self.window.FindResource('DarkToolTip')
                    label.ToolTip = tip
                except Exception:
                    pass
                Grid.SetColumn(label, 0)
                row.Children.Add(label)

                combo = ComboBox()
                try:
                    combo.Style = self.window.FindResource('DarkCombo')
                except Exception:
                    pass
                for item in items:
                    combo.Items.Add(item)
                combo.SelectedIndex = 0
                combo.Tag = caption
                wanted = self.remembered_map.get(caption)
                if wanted:
                    self.set_combo(combo, wanted, -1)
                combo.SelectionChanged += self.on_map_changed
                Grid.SetColumn(combo, 1)
                row.Children.Add(combo)

                panel.Children.Add(row)
                self.map_rows.append((i, combo))
        finally:
            self.loading = was_loading

    @ui_safe
    def on_map_changed(self, sender, args):
        caption = core.as_text(sender.Tag)
        target = self.combo_text(sender)
        if target and target != core.NONE_TARGET:
            self.remembered_map[caption] = target
        else:
            self.remembered_map.pop(caption, None)
        if self.loading:
            return
        self.update_buttons()

    @ui_safe
    def on_type_params(self, sender, args):
        if self.loading:
            return
        self.build_mapping()
        self.update_buttons()

    @ui_safe
    def on_auto_match(self, sender, args):
        if not self.map_rows:
            self.warn(u'Load a spreadsheet first.')
            return
        lowered = {}
        for item in self.target_items():
            lowered[core.as_text(item).strip().lower()] = item
        squashed_index = {}
        for key, item in lowered.items():
            squashed_index[key.replace(u' ', u'').replace(u'_', u'')] = item
        hits = 0
        for index, combo in self.map_rows:
            caption = self.headers[index] if index < len(self.headers) else u''
            probe = core.as_text(caption).strip().lower()
            target = lowered.get(probe)
            if target is None and probe:
                target = squashed_index.get(probe.replace(u' ', u'').replace(u'_', u''))
            if target is not None and target != core.NONE_TARGET:
                if self.set_combo(combo, target, -1):
                    hits += 1
        self.update_buttons()
        self.status(u'Auto-match paired {0} column(s) with a parameter of the same name.'
                    .format(hits))

    @ui_safe
    def on_clear_map(self, sender, args):
        for _index, combo in self.map_rows:
            combo.SelectedIndex = 0
        self.remembered_map = {}
        self.update_buttons()
        self.status(u'Mapping cleared.')

    # ------------------------------------------------------------- model side

    @ui_safe
    def on_scope_changed(self, sender, args):
        if self.loading:
            return
        self.refresh_scope()

    @ui_safe
    def on_key_changed(self, sender, args):
        if self.loading:
            return
        self.update_buttons()

    def refresh_scope(self):
        self.status(u'Reading the model\u2026')
        self.elements = core.collect_elements(self.doc, self.uidoc, self.scope_key())
        wanted = self.pending_cats
        if wanted is None:
            wanted = self.selected_categories()
        self.pending_cats = None
        self.build_categories(wanted)
        self.apply_category_filter()

    def build_categories(self, wanted):
        panel = self.CatPanel
        panel.Children.Clear()
        self.cat_boxes = []
        lookup = set(wanted or [])
        was_loading = self.loading
        self.loading = True
        try:
            for name, count in core.category_names(self.elements):
                box = CheckBox()
                box.Content = u'{0}  ({1})'.format(name, count)
                box.Tag = name
                box.Margin = Thickness(0, 2, 0, 2)
                try:
                    box.Style = self.window.FindResource('DarkCheck')
                except Exception:
                    pass
                box.IsChecked = name in lookup
                box.Checked += self.on_cat_toggle
                box.Unchecked += self.on_cat_toggle
                panel.Children.Add(box)
                self.cat_boxes.append(box)
        finally:
            self.loading = was_loading

    def selected_categories(self):
        return [core.as_text(box.Tag) for box in self.cat_boxes if box.IsChecked]

    @ui_safe
    def on_cat_toggle(self, sender, args):
        if self.loading:
            return
        self.apply_category_filter()

    @ui_safe
    def on_cat_all(self, sender, args):
        was_loading = self.loading
        self.loading = True
        try:
            for box in self.cat_boxes:
                if box.Visibility == Visibility.Visible:
                    box.IsChecked = True
        finally:
            self.loading = was_loading
        self.apply_category_filter()

    @ui_safe
    def on_cat_none(self, sender, args):
        was_loading = self.loading
        self.loading = True
        try:
            for box in self.cat_boxes:
                box.IsChecked = False
        finally:
            self.loading = was_loading
        self.apply_category_filter()

    @ui_safe
    def on_cat_search(self, sender, args):
        probe = core.as_text(self.CatSearchBox.Text).strip().lower()
        for box in self.cat_boxes:
            name = core.as_text(box.Tag).lower()
            if not probe or probe in name:
                box.Visibility = Visibility.Visible
            else:
                box.Visibility = Visibility.Collapsed

    def apply_category_filter(self):
        wanted = self.selected_categories()
        self.scoped = core.filter_by_category(self.elements, wanted)
        keys, instance_targets, type_targets, scanned = core.discover_parameters(
            self.doc, self.scoped)
        self.key_options = keys
        self.instance_targets = instance_targets
        self.type_targets = type_targets

        was_loading = self.loading
        self.loading = True
        try:
            wanted_key = self.pending_key or self.combo_text(self.KeyParamCombo)
            self.pending_key = u''
            self.KeyParamCombo.Items.Clear()
            for name in keys:
                self.KeyParamCombo.Items.Add(name)
            self.set_combo(self.KeyParamCombo, wanted_key, -1)
        finally:
            self.loading = was_loading

        self.build_mapping()

        note = u'{0} element(s) in scope'.format(len(self.scoped))
        if wanted:
            note += u' across {0} categor{1}'.format(
                len(wanted), u'y' if len(wanted) == 1 else u'ies')
        else:
            note += u' (every category)'
        if scanned < len(self.scoped):
            note += u'  \u2022  parameter list read from the first {0}'.format(scanned)
        self.ScopeInfoLabel.Text = note
        self.update_buttons()

    # ------------------------------------------------------------- run

    def options(self):
        opts = core.MatchOptions()
        opts.ignore_case = bool(self.IgnoreCaseChk.IsChecked)
        opts.trim = bool(self.TrimChk.IsChecked)
        opts.numeric = bool(self.NumericChk.IsChecked)
        opts.duplicates = self.duplicates_key()
        opts.skip_blanks = bool(self.SkipBlanksChk.IsChecked)
        return opts

    def ready(self):
        if self.workbook is None or not self.rows:
            return False, u'Choose a spreadsheet with at least one data row.'
        if self.lookup_index() < 0:
            return False, u'Choose the lookup column.'
        if not self.combo_text(self.KeyParamCombo):
            return False, u'Choose the Revit parameter to match on.'
        if not self.scoped:
            return False, u'Nothing is in scope.'
        if not self.mapping_pairs():
            return False, u'Map at least one column to a parameter.'
        return True, u''

    def update_buttons(self):
        ok, message = self.ready()
        self.PreviewBtn.IsEnabled = ok
        self.ApplyBtn.IsEnabled = ok
        if not ok:
            self.status(message)

    def build_plan(self):
        return core.build_plan(self.doc, self.scoped, self.combo_text(self.KeyParamCombo),
                               self.rows, self.lookup_index(), self.mapping_pairs(),
                               self.options())

    def plan_sections(self, plan):
        sections = []
        if plan.unmatched:
            sections.append((
                u'In the model but not in the spreadsheet ({0})'.format(len(plan.unmatched)),
                [u'{0}  \u2014  key "{1}"'.format(a, b) for a, b in plan.unmatched], True))
        if plan.no_key:
            sections.append((
                u'No value in the key parameter ({0})'.format(len(plan.no_key)),
                plan.no_key, True))
        if plan.duplicate_keys:
            sections.append((
                u'Repeated keys in the spreadsheet ({0})'.format(len(plan.duplicate_keys)),
                [u'{0} appears {1} times'.format(core.as_text(k).lstrip(u'#'), n)
                 for k, n in plan.duplicate_keys], True))
        if plan.notes:
            sections.append((
                u'Matched but nothing to write ({0})'.format(len(plan.notes)),
                plan.notes, False))
        return sections

    @ui_safe
    def on_check(self, sender, args):
        ok, message = self.ready()
        if not ok:
            self.warn(message)
            return
        self.status(u'Matching\u2026')
        plan = self.build_plan()
        summary = (u'{0} of {1} element(s) matched a spreadsheet row.\n'
                   u'{2} value(s) would be written across {3} mapped column(s).\n'
                   u'{4} spreadsheet key(s) were not used by anything in scope.'
                   .format(plan.matched, plan.scanned, plan.value_count,
                           len(self.mapping_pairs()), plan.unused_rows))
        self.status(u'{0} matched, {1} unmatched, {2} value(s) ready to write.'
                    .format(plan.matched, len(plan.unmatched), plan.value_count))
        ui.show_results(self.window, self.version, summary, self.plan_sections(plan),
                        u'Nothing has been written - press Apply to write.',
                        self.theme, u'VlookUp check')

    @ui_safe
    def on_apply(self, sender, args):
        ok, message = self.ready()
        if not ok:
            self.warn(message)
            return
        self.status(u'Matching\u2026')
        plan = self.build_plan()
        if not plan.edits:
            self.warn(u'Nothing matched - nothing to write.')
            ui.show_results(self.window, self.version,
                            u'Nothing matched, so nothing was written.',
                            self.plan_sections(plan), u'', self.theme, u'VlookUp check')
            return

        type_targets = [t for _i, t in self.mapping_pairs()
                        if core.as_text(t).startswith(core.TYPE_PREFIX)]
        question = (u'Write {0} value(s) to {1} element(s)?\n\n'
                    u'{2} element(s) in scope did not match and will be left alone.'
                    .format(plan.value_count, plan.matched, len(plan.unmatched)))
        if type_targets:
            question += (u'\n\n{0} of the mapped parameters are TYPE parameters. Writing '
                         u'one changes every instance of that type in the project, not '
                         u'only the elements in scope.'.format(len(type_targets)))
        if ui.prompt(self.window, u'Apply VlookUp', question, u'Write', u'Cancel',
                     None, self.theme) is None:
            self.status(u'Cancelled - nothing was written.')
            return

        self.status(u'Writing\u2026')
        result = core.apply_plan(self.doc, plan)
        sections = self.plan_sections(plan)
        if result.failures:
            sections.insert(0, (
                u'Values that could not be written ({0})'.format(len(result.failures)),
                [u'{0}  \u2014  {1}: {2}'.format(a, b, c) for a, b, c in result.failures],
                True))
        if result.aborted:
            summary = (u'The write was rolled back and nothing was changed.\n\n{0}'
                       .format(result.aborted))
            self.warn(u'Rolled back: {0}'.format(result.aborted))
        else:
            summary = (u'{0} value(s) written across {1} element(s).\n'
                       u'{2} value(s) already agreed with the spreadsheet and were left alone.\n'
                       u'{3} element(s) in scope did not match a row.'
                       .format(result.values_written, result.elements_changed,
                               result.values_unchanged, len(plan.unmatched)))
            if result.type_writes:
                summary += (u'\n{0} of those went to type parameters, on {1} type(s).'
                            .format(result.type_writes, len(result.type_names)))
            self.status(u'{0} value(s) written to {1} element(s).'
                        .format(result.values_written, result.elements_changed))
        ui.show_results(self.window, self.version, summary, sections, u'',
                        self.theme, u'VlookUp results')

    # ------------------------------------------------------------- profiles

    def reload_profiles(self, select=None):
        was_loading = self.loading
        self.loading = True
        try:
            self.ProfileCombo.Items.Clear()
            for name in core.list_profiles():
                self.ProfileCombo.Items.Add(name)
            if select:
                self.set_combo(self.ProfileCombo, select, -1)
        finally:
            self.loading = was_loading

    @ui_safe
    def on_profile_changed(self, sender, args):
        if self.loading:
            return
        name = self.combo_text(self.ProfileCombo)
        if not name:
            return
        values = core.load_profile(name)
        if values is None:
            self.warn(u'That profile could not be read.')
            return
        self._apply_values(values)
        self.refresh_scope()
        self.status(u'Profile "{0}" loaded.'.format(name))

    @ui_safe
    def on_save_profile(self, sender, args):
        current = self.combo_text(self.ProfileCombo)
        name = ui.prompt(self.window, u'Save profile',
                         u'Name this mapping so it can be picked up again later.',
                         u'Save', u'Cancel', current or u'', self.theme)
        if not name:
            return
        saved = core.save_profile(name, self._collect_values())
        if not saved:
            self.warn(u'That name cannot be used.')
            return
        self.reload_profiles(saved)
        self.status(u'Profile "{0}" saved.'.format(saved))

    @ui_safe
    def on_delete_profile(self, sender, args):
        name = self.combo_text(self.ProfileCombo)
        if not name:
            self.warn(u'No profile selected.')
            return
        if ui.prompt(self.window, u'Delete profile',
                     u'Delete the profile "{0}"?'.format(name),
                     u'Delete', u'Cancel', None, self.theme) is None:
            return
        core.delete_profile(name)
        self.reload_profiles()
        self.status(u'Profile "{0}" deleted.'.format(name))

    # ------------------------------------------------------------- keys

    @ui_safe
    def on_key(self, sender, args):
        if args.Key == Key.Escape:
            self.window.Close()
