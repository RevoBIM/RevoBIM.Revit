# -*- coding: utf-8 -*-
"""Find in View - the window."""

import fiv_clr  # noqa: F401 - must be imported before any System.* name

from System import Object
from System.Collections.Generic import List
from System.ComponentModel import ListSortDirection
from System.Windows import (GridLength, GridUnitType, DataTemplate, Visibility,
                            FrameworkElementFactory, VerticalAlignment, Thickness,
                            TextTrimming, TextWrapping)
from System.Windows.Controls import (CheckBox, TextBlock, DataGridTemplateColumn,
                                     DataGridLength, DataGridLengthUnitType,
                                     Grid, ColumnDefinition)
from System.Windows.Data import Binding, IValueConverter
from System.Windows.Input import Key, ModifierKeys, Keyboard

import fiv_core
import fiv_model
import fiv_ui
import theme as fiv_theme

COLUMNS = [
    ('name',  'View',  3.0, 200.0),
    ('type',  'Type',  1.2, 110.0),
    ('scale', 'Scale', 0.7, 62.0),
    ('sheet', 'Sheet', 1.0, 80.0),
]


class CellConverter(IValueConverter):
    """The grid binds the row object itself with the column key as
    ConverterParameter, rather than binding to Python attributes."""

    def Convert(self, value, target_type, parameter, culture):
        try:
            return value.cell('{0}'.format(parameter))
        except Exception:
            return ''

    def ConvertBack(self, value, target_type, parameter, culture):
        return None


class FindByIdWindow(object):
    """Revit's Select Elements by ID, in the house style, for a run started with
    nothing selected.  Find selects the elements in the model and hands them
    straight to the main window."""

    def __init__(self, uidoc, uiapp, settings):
        self.uidoc = uidoc
        self.uiapp = uiapp
        self.settings = settings
        self.palette_name = (settings.get('theme') or 'dark').lower()
        self.elements = []
        self.element_ids = []
        self.skipped = False

        self.window = fiv_ui.load_window('FindById.xaml', self.palette_name)
        self.find = self.window.FindName
        find = self.find
        find('VersionText').Text = 'v' + fiv_core.__version__
        fiv_ui.load_icon(find('HeaderIcon'))
        fiv_ui.wire_egg(find('HeaderIcon'), self.window, self.palette_name)
        self.chrome = fiv_ui.Chrome(self.window, find('HeaderBar'))
        self.drawer = fiv_ui.WindowDrawer(
            self.window, find('HeaderBar'), find('RootGrid'), find('ShrinkBtn'),
            find('PathShrink'), find('PathExpand'), find('RootBorder'))
        self.chrome.drawer = self.drawer

        find('CloseBtn').Click += self._on_cancel
        find('CancelBtn').Click += self._on_cancel
        find('FindBtn').Click += self._on_find
        find('SkipBtn').Click += self._on_skip
        find('IdBox').TextChanged += self._on_typed
        self.window.PreviewKeyDown += self._on_key
        self.window.Loaded += self._on_loaded

    def _on_loaded(self, sender, args):
        try:
            self.find('IdBox').Focus()
        except Exception:
            pass

    def tokens(self):
        return fiv_core.parse_ids(self.find('IdBox').Text or '')

    def _on_typed(self, sender, args):
        count = len(self.tokens())
        self.find('FindBtn').IsEnabled = count > 0
        self.find('CountText').Text = \
            '' if not count else fiv_core.plural(count, 'id') + ' typed'

    def _on_key(self, sender, args):
        try:
            if self.drawer.shrunk:
                if args.Key in (Key.Escape, Key.Enter, Key.F11) or \
                        fiv_ui.is_shrink_key(args):
                    self.drawer.expand()
                    args.Handled = True
                return
            if fiv_ui.is_shrink_key(args):
                self.drawer.toggle()
                args.Handled = True
            elif args.Key == Key.Escape:
                self._on_cancel(sender, args)
            elif args.Key == Key.Enter and args.KeyboardDevice.Modifiers == ModifierKeys.Control:
                if self.find('FindBtn').IsEnabled:
                    self._on_find(sender, args)
        except Exception:
            pass

    def _on_find(self, sender, args):
        tokens = self.tokens()
        if not tokens:
            return
        elements, ids, missing = fiv_model.find_by_ids(self.uidoc.Document, tokens)

        if not elements:
            self.find('StatusText').Text = (
                'Nothing in this model has {0}. Check the ids, and that they '
                'belong to this model rather than a link.').format(
                    'that id' if len(tokens) == 1 else 'those ids')
            return

        self.elements = elements
        self.element_ids = ids
        if missing:
            # found some: say which were not, then carry on with what there is
            self.find('StatusText').Text = (
                'Found {0}. Not in this model: {1}').format(
                    fiv_core.plural(len(elements), 'element'),
                    ', '.join(missing[:8]) + ('...' if len(missing) > 8 else ''))
            self.find('CountText').Text = 'opening with {0}'.format(
                fiv_core.plural(len(elements), 'element'))
        self.window.Close()

    def _on_skip(self, sender, args):
        """Straight to the view list with nothing selected.

        Show Me still opens the view; there is simply nothing to frame it on.
        """
        self.skipped = True
        self.elements = []
        self.element_ids = []
        self.window.Close()

    def _on_cancel(self, sender, args):
        self.skipped = False
        self.elements = []
        self.element_ids = []
        self.window.Close()

    def show(self):
        fiv_ui.own_to_revit(self.window, self.uiapp)
        self.window.ShowDialog()
        return self.elements, self.element_ids


class FindInViewWindow(object):

    def __init__(self, uidoc, uiapp, settings, rows, elements, element_ids,
                 category_ids, category_names, already_tiled=False,
                 open_view_ids=None):
        self.uidoc = uidoc
        self.uiapp = uiapp
        self.settings = settings
        self.rows = rows
        self.elements = elements
        self.element_ids = element_ids
        self.category_ids = category_ids
        self.category_names = category_names
        self.already_tiled = already_tiled
        self.open_view_ids = set(open_view_ids or [])
        self.reuse_tile = fiv_core.as_bool(settings.get('reuse_tile'), True)

        self.palette_name = (settings.get('theme') or 'dark').lower()
        self.result_row = None
        self.sort_key = 'name'
        self.sort_ascending = True
        self.restored_selection = False
        self.hidden_last_view = ''
        self.type_boxes = {}

        self.window = fiv_ui.load_window('FindInView.xaml', self.palette_name)
        self.find = self.window.FindName
        self.cell_converter = CellConverter()

        self._build_chrome()
        self._build_types()
        self._build_columns()
        self._restore_choices()
        self._wire()
        self._describe_selection()
        self.refresh()

    # ------------------------------------------------------------------ setup

    def _build_chrome(self):
        find = self.find
        find('VersionText').Text = 'v' + fiv_core.__version__
        find('TitleTool').Text = fiv_core.TOOL_NAME
        fiv_ui.load_icon(find('HeaderIcon'))
        fiv_ui.wire_egg(find('HeaderIcon'), self.window, self.palette_name)
        self.chrome = fiv_ui.Chrome(self.window, find('HeaderBar'))
        self.drawer = fiv_ui.WindowDrawer(
            self.window, find('HeaderBar'), find('RootGrid'), find('ShrinkBtn'),
            find('PathShrink'), find('PathExpand'), find('RootBorder'),
            find('GripLayer'))
        self.chrome.drawer = self.drawer
        grips = {}
        for name in ('N', 'S', 'E', 'W', 'NE', 'NW', 'SE', 'SW'):
            try:
                grips[name] = find('Grip' + name)
            except Exception:
                grips[name] = None
        self.chrome.attach_grips(grips)
        self._label_theme_chip()

    def _label_theme_chip(self):
        try:
            self.find('ThemeChip').Content = \
                'Light' if self.palette_name == 'dark' else 'Dark'
        except Exception:
            pass

    def _build_types(self):
        """One tick box per view type actually present in this project."""
        self.type_labels = fiv_model.view_types_present(self.rows)
        wanted = fiv_core.unpack_list(self.settings.get('view_types'))
        for label in self.type_labels:
            box = CheckBox()
            box.Content = label
            box.IsChecked = (not wanted) or (label in wanted)
            box.Margin = Thickness(2, 1, 2, 1)
            try:
                box.SetResourceReference(CheckBox.StyleProperty, 'ThemedCheckBox')
            except Exception:
                pass
            box.Checked += self._on_type_toggled
            box.Unchecked += self._on_type_toggled
            self.type_boxes[label] = box
        self._fill_type_list('')

    def _fill_type_list(self, query):
        listbox = self.find('ViewTypeList')
        listbox.Items.Clear()
        for label in self.type_labels:
            if fiv_core.matches_keywords(label, query):
                listbox.Items.Add(self.type_boxes[label])
        self._update_type_count()

    def _update_type_count(self):
        ticked = len(self.ticked_types())
        self.find('TypeCountText').Text = '{0} of {1}'.format(ticked, len(self.type_labels))

    def _build_columns(self):
        grid = self.find('ViewGrid')
        grid.Columns.Clear()
        for key, header, star, minimum in COLUMNS:
            factory = FrameworkElementFactory(TextBlock)
            binding = Binding('.')
            binding.Converter = self.cell_converter
            binding.ConverterParameter = key
            factory.SetBinding(TextBlock.TextProperty, binding)
            factory.SetValue(TextBlock.VerticalAlignmentProperty, VerticalAlignment.Center)
            factory.SetValue(TextBlock.TextTrimmingProperty, TextTrimming.CharacterEllipsis)
            template = DataTemplate()
            template.VisualTree = factory

            column = DataGridTemplateColumn()
            column.Header = header
            column.CellTemplate = template
            column.SortMemberPath = key
            # star sized with a minimum, never fixed pixels
            column.Width = DataGridLength(star, DataGridLengthUnitType.Star)
            column.MinWidth = minimum
            grid.Columns.Add(column)

    def _restore_choices(self):
        find = self.find
        settings = self.settings
        find('ChkOpenTiled').IsChecked = fiv_core.as_bool(settings.get('open_tiled'))
        find('ChkUnhide').IsChecked = fiv_core.as_bool(settings.get('unhide_categories'), True)
        find('ChkZoomHere').IsChecked = fiv_core.as_bool(settings.get('zoom_here'), True)
        self._describe_tiling()
        if fiv_core.as_bool(settings.get('remember_search')):
            find('SearchBox').Text = settings.get('search') or ''

        width = fiv_core.as_int(settings.get('window_width'), 1040)
        height = fiv_core.as_int(settings.get('window_height'), 700)
        if width >= self.window.MinWidth:
            self.window.Width = width
        if height >= self.window.MinHeight:
            self.window.Height = height
        panel = fiv_core.as_int(settings.get('panel_width'), 300)
        if panel > 0:
            find('PanelColumn').Width = GridLength(panel, GridUnitType.Star)
            find('ListColumn').Width = GridLength(max(width - panel, 380), GridUnitType.Star)

    def _wire(self):
        find = self.find
        find('CloseBtn').Click += self._on_close
        find('CancelBtn').Click += self._on_close
        find('ThemeChip').Click += self._on_theme
        find('FullScreenBtn').Click += self._on_full_screen
        find('ShowMeBtn').Click += self._on_show_me
        find('TypeAll').Click += self._on_type_all
        find('TypeNone').Click += self._on_type_none
        find('TypeSearch').TextChanged += self._on_type_search
        find('SearchBox').TextChanged += self._on_search
        find('IdBox').TextChanged += self._on_id_typed
        find('FindIdBtn').Click += self._on_find_id
        find('ChkOpenTiled').Checked += self._on_tiled_toggled
        find('ChkOpenTiled').Unchecked += self._on_tiled_toggled

        grid = find('ViewGrid')
        grid.SelectionChanged += self._on_selection
        grid.MouseDoubleClick += self._on_double_click
        grid.Sorting += self._on_sorting

        self.window.PreviewKeyDown += self._on_key
        self.window.Loaded += self._on_loaded

    def _describe_selection(self):
        self._describe_properties()
        if not self.elements:
            self.find('SelectionText').Text = (
                'Nothing selected. Show Me will open the view without zooming, '
                'or find an element by id below.')
            return
        counts = fiv_model.category_counts(self.elements)
        parts = []
        for name in sorted(counts.keys()):
            parts.append('{0} x {1}'.format(counts[name], name))
        text = fiv_core.plural(len(self.elements), 'element') + ' selected'
        if parts:
            text = text + '\n' + '\n'.join(parts)
        self.find('SelectionText').Text = text

    def _describe_properties(self):
        """The properties panel, built as WPF elements in code.

        Not bound to Python objects: binding to them is unreliable across
        engine versions, and these rows are rebuilt whenever the selection
        changes anyway.
        """
        panel = self.find('PropsPanel')
        card = self.find('PropsCard')
        panel.Children.Clear()
        if not self.elements:
            card.Visibility = Visibility.Collapsed
            return

        try:
            rows = fiv_model.selection_properties(self.uidoc.Document, self.elements)
        except Exception as error:
            rows = [('Properties', 'could not be read: {0}'.format(error), '')]

        for label, value, note in rows:
            row = Grid()
            row.Margin = Thickness(0, 1, 0, 1)
            first = ColumnDefinition()
            first.Width = GridLength(74)
            second = ColumnDefinition()
            second.Width = GridLength(1, GridUnitType.Star)
            row.ColumnDefinitions.Add(first)
            row.ColumnDefinitions.Add(second)

            name = TextBlock()
            name.Text = label
            name.FontSize = 11.5
            name.SetResourceReference(TextBlock.ForegroundProperty, 'MutedBrush')
            Grid.SetColumn(name, 0)

            reading = TextBlock()
            reading.Text = value or '-'
            reading.FontSize = 12
            reading.TextWrapping = TextWrapping.Wrap
            # the level is what this panel is for, so it reads as the answer
            reading.SetResourceReference(
                TextBlock.ForegroundProperty,
                'OrangeBrush' if label.startswith('Level') else 'TextBrush')
            Grid.SetColumn(reading, 1)

            row.Children.Add(name)
            row.Children.Add(reading)
            panel.Children.Add(row)

            if note:
                aside = TextBlock()
                aside.Text = note
                aside.FontSize = 10.5
                aside.TextWrapping = TextWrapping.Wrap
                aside.Margin = Thickness(74, 0, 0, 3)
                aside.SetResourceReference(TextBlock.ForegroundProperty, 'MutedBrush')
                panel.Children.Add(aside)

        card.Visibility = Visibility.Visible

    # ------------------------------------------------------------- by id

    def _on_id_typed(self, sender, args):
        self.find('FindIdBtn').IsEnabled = bool(
            fiv_core.parse_ids(self.find('IdBox').Text or ''))

    def _on_find_id(self, sender, args):
        """Select an element by id without leaving the tool.

        It becomes the selection Revit shows the properties for AND the
        selection Show Me will zoom to, because those being two different
        things is exactly the confusion worth avoiding.
        """
        tokens = fiv_core.parse_ids(self.find('IdBox').Text or '')
        if not tokens:
            return
        elements, ids, missing = fiv_model.find_by_ids(self.uidoc.Document, tokens)
        if not elements:
            self.find('IdStatus').Text = (
                'Nothing in this model has {0}.').format(
                    'that id' if len(tokens) == 1 else 'those ids')
            return

        self.elements = elements
        self.element_ids = ids
        self.category_ids, self.category_names = fiv_model.categories_of(elements)
        fiv_model.select_elements(self.uidoc, ids)
        try:
            self.uidoc.RefreshActiveView()
        except Exception:
            pass

        note = 'Selected {0} in Revit.'.format(
            fiv_core.plural(len(elements), 'element'))
        if missing:
            note += ' Not in this model: {0}'.format(
                ', '.join(missing[:6]) + ('...' if len(missing) > 6 else ''))
        self.find('IdStatus').Text = note
        self._describe_selection()
        self._update_status()
        self._update_show_me()

    # ---------------------------------------------------------------- filters

    def ticked_types(self):
        ticked = []
        for label in self.type_labels:
            box = self.type_boxes.get(label)
            if box is not None and box.IsChecked:
                ticked.append(label)
        return ticked

    def visible_rows(self):
        ticked = set(self.ticked_types())
        query = self.find('SearchBox').Text or ''

        out = []
        for row in self.rows:
            if fiv_model.passes_filters(row, ticked, query):
                out.append(row)

        reverse = not self.sort_ascending
        try:
            out.sort(key=lambda row: row.sort_key(self.sort_key), reverse=reverse)
        except Exception:
            pass
        return out

    def refresh(self, keep_selection=True):
        grid = self.find('ViewGrid')
        previous = grid.SelectedItem if keep_selection else None
        rows = self.visible_rows()

        items = List[Object]()
        for row in rows:
            items.Add(row)
        grid.ItemsSource = items

        if previous is not None and previous in rows:
            grid.SelectedItem = previous
        elif rows and not self.restored_selection:
            # the last view used is re-selected once, on open - not on every
            # refresh, or it would fight the user every time a filter moves
            self.restored_selection = True
            wanted_id = fiv_core.as_int(self.settings.get('last_view_id'), 0)
            wanted_name = self.settings.get('last_view') or ''
            remembered = fiv_model.find_remembered(rows, wanted_id, wanted_name)
            if remembered is not None:
                grid.SelectedItem = remembered
                self._scroll_to_selection()
            else:
                # in the project but filtered out is worth saying, rather than
                # leaving the list looking arbitrary
                hidden = fiv_model.find_remembered(self.rows, wanted_id, wanted_name)
                self.hidden_last_view = hidden.name if hidden is not None else ''

        self.find('CountText').Text = '{0} of {1}'.format(len(rows), len(self.rows))
        self._update_status()
        self._update_show_me()

    def _update_status(self):
        parts = []
        parts.append('nothing selected' if not self.elements
                     else fiv_core.plural(len(self.elements), 'element') + ' selected')
        if self.category_names:
            parts.append(fiv_core.plural(len(self.category_names), 'category', 'categories'))
        self.find('StatusText').Text = '   |   '.join(parts)

    def _update_show_me(self):
        """The button goes green the moment there is a view to go to."""
        row = self.find('ViewGrid').SelectedItem
        enabled = row is not None
        self.find('ShowMeBtn').IsEnabled = bool(enabled)
        if row is not None:
            beside = ' beside the current view' if self.find('ChkOpenTiled').IsChecked else ''
            ending = ' and zooms to the selection.' if self.elements else '.'
            self.find('HintText').Text = \
                'Show Me opens "{0}"{1}{2}'.format(row.name, beside, ending)
        elif self.hidden_last_view:
            self.find('HintText').Text = (
                'The view you used last, "{0}", is hidden by the view types or '
                'the search.').format(self.hidden_last_view)
        else:
            self.find('HintText').Text = 'Pick a view. Double click one to go straight to it.'

    # ---------------------------------------------------------------- handlers

    def _on_type_toggled(self, sender, args):
        self._update_type_count()
        self.refresh()

    def _on_type_search(self, sender, args):
        self._fill_type_list(sender.Text or '')

    def _on_type_all(self, sender, args):
        for label in self.type_boxes:
            self.type_boxes[label].IsChecked = True

    def _on_type_none(self, sender, args):
        for label in self.type_boxes:
            self.type_boxes[label].IsChecked = False

    def _on_search(self, sender, args):
        self.refresh()

    def _on_tiled_toggled(self, sender, args):
        self._describe_tiling()
        self._update_show_me()

    @property
    def target_already_open(self):
        row = self.find('ViewGrid').SelectedItem
        if row is None:
            return False
        return fiv_core.eid_value(row.view_id) in self.open_view_ids

    def _describe_tiling(self):
        """Say plainly what tiling will do, including what it closes."""
        if self.find('ChkOpenTiled').IsChecked:
            if self.already_tiled and self.target_already_open:
                text = ('That view is already open in its own tile. It is just '
                        'brought forward - nothing closes and nothing re-tiles.')
            elif self.already_tiled and self.reuse_tile:
                text = ('Revit is already tiled. The first tile that is not the '
                        'one you came from is closed and the view opens in its '
                        'place. Your layout is not re-tiled.')
            elif len(self.open_view_ids) > 1:
                text = ('More than one view is open, so the layout is left '
                        'alone and the view opens into it.')
            else:
                text = ('The view you came from is the only one open, so it '
                        'stays open and Revit tiles the two side by side.')
        else:
            text = 'The view opens over the one you came from, as Revit normally does.'
        self.find('TileHint').Text = text

    def _scroll_to_selection(self):
        """Bring the selected row into view.

        Selecting a row does not scroll to it, and a DataGrid will not scroll to
        something it has not laid out yet - so the layout is forced first, and
        the whole thing runs again once the window is up, because the first
        refresh happens before the grid is in a visual tree at all.
        """
        grid = self.find('ViewGrid')
        row = grid.SelectedItem
        if row is None:
            return
        try:
            grid.UpdateLayout()
        except Exception:
            pass
        try:
            grid.ScrollIntoView(row)
        except Exception:
            pass

    def _on_loaded(self, sender, args):
        self._scroll_to_selection()
        # typing is the usual next move - an id when there is nothing selected
        # yet, a view name when there is
        if fiv_core.first_field(bool(self.elements)) == fiv_core.FIELD_ID:
            box = self.find('IdBox')
        else:
            box = self.find('SearchBox')
        try:
            box.Focus()
            Keyboard.Focus(box)
        except Exception:
            pass

    def _on_selection(self, sender, args):
        self._update_show_me()
        self._describe_tiling()

    def _on_double_click(self, sender, args):
        if self.find('ViewGrid').SelectedItem is not None:
            self._on_show_me(sender, args)

    def _on_sorting(self, sender, args):
        """Sort the row list and cancel the event: the grid binds row objects,
        not properties, so a CollectionView has nothing to sort on."""
        try:
            key = args.Column.SortMemberPath
            if key == self.sort_key:
                self.sort_ascending = not self.sort_ascending
            else:
                self.sort_key = key
                self.sort_ascending = True
            args.Column.SortDirection = \
                ListSortDirection.Ascending if self.sort_ascending else ListSortDirection.Descending
            args.Handled = True
            self.refresh()
        except Exception:
            pass

    def _on_theme(self, sender, args):
        self.palette_name = fiv_theme.other(self.palette_name)
        fiv_theme.apply(self.window, self.palette_name)
        self._label_theme_chip()
        self._build_columns()
        self.refresh()

    def _on_full_screen(self, sender, args):
        self.chrome.toggle_full_screen()

    def _on_key(self, sender, args):
        try:
            if self.drawer.shrunk:
                # nothing but reopening, while the window is out of sight
                if args.Key in (Key.Escape, Key.Enter, Key.F11) or \
                        fiv_ui.is_shrink_key(args):
                    self.drawer.expand()
                    args.Handled = True
                return
            if fiv_ui.is_shrink_key(args):
                self.drawer.toggle()
                args.Handled = True
            elif args.Key == Key.Escape:
                if self.chrome.full_screen:
                    self.chrome.toggle_full_screen()
                else:
                    self._on_close(sender, args)
            elif args.Key == Key.F11:
                self.chrome.toggle_full_screen()
            elif args.Key == Key.Enter:
                # Enter in the id box means Find, not Show Me
                if self.find('IdBox').IsKeyboardFocusWithin:
                    if self.find('FindIdBtn').IsEnabled:
                        self._on_find_id(sender, args)
                    args.Handled = True
                elif self.find('ShowMeBtn').IsEnabled:
                    self._on_show_me(sender, args)
        except Exception:
            pass

    def _on_show_me(self, sender, args):
        row = self.find('ViewGrid').SelectedItem
        if row is None:
            return
        self.result_row = row
        self.settings['last_view'] = row.name
        self.settings['last_view_id'] = fiv_core.eid_value(row.view_id)
        self._save()
        self.window.Close()

    def _on_close(self, sender, args):
        self.drawer.restore_now()
        self._save()
        self.window.Close()

    # ---------------------------------------------------------------- settings

    def _save(self):
        try:
            find = self.find
            settings = self.settings
            settings['theme'] = self.palette_name
            ticked = self.ticked_types()
            settings['view_types'] = '' if len(ticked) == len(self.type_labels) \
                else fiv_core.pack_list(ticked)
            settings['open_tiled'] = '1' if find('ChkOpenTiled').IsChecked else '0'
            settings['unhide_categories'] = '1' if find('ChkUnhide').IsChecked else '0'
            settings['zoom_here'] = '1' if find('ChkZoomHere').IsChecked else '0'
            if fiv_core.as_bool(settings.get('remember_search')):
                settings['search'] = find('SearchBox').Text or ''
            if not self.chrome.full_screen:
                settings['window_width'] = int(self.window.Width)
                # parked, the window IS the bar - saving that height would
                # reopen the tool as a 60 pixel sliver next time
                settings['window_height'] = int(self.drawer.true_height())
                panel = int(find('PanelColumn').ActualWidth)
                if panel > 0:
                    settings['panel_width'] = panel
            fiv_core.save_settings(settings)
        except Exception:
            pass

    # -------------------------------------------------------------------- run

    def show(self):
        fiv_ui.own_to_revit(self.window, self.uiapp)
        # modal: nothing has to be picked in the model while it is open, and
        # the active view cannot be changed with a modal dialog up anyway - so
        # the window closes first and the view is opened afterwards.
        self.window.ShowDialog()
        return self.result_row
