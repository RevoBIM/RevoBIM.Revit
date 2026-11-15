# -*- coding: utf-8 -*-
"""RevoBIM PY - Panel Template Mngr: the grids.

Every column is a DataGridTemplateColumn whose binding is `.` with an
IValueConverter and the column key as ConverterParameter.  That sidesteps the
question of whether WPF can see Python attributes, and it is what makes a set of
columns that do not exist until the model is read possible at all.  The cell
converters read their brushes from the window at conversion time, so a palette
switch just needs the rows refreshed.

Runs on IronPython 2.7 and IronPython 3: no f-strings, no print statements.
"""

import pstm_clr                                                  # noqa: F401

from System.Windows import (DataTemplate, FrameworkElementFactory, Thickness,
                            VerticalAlignment, HorizontalAlignment, TextTrimming,
                            FrameworkElement, Visibility, CornerRadius)
from System.Windows.Controls import (Border, TextBlock, TextBox, ComboBox,
                                     StackPanel, Orientation, ListBox, CheckBox,
                                     Button, ScrollViewer, ScrollBarVisibility,
                                     DataGridTemplateColumn, DataGridLength,
                                     DataGridLengthUnitType)
from System.Windows.Controls.Primitives import (Popup, ToggleButton,
                                                 PlacementMode, Selector)
from System.Windows.Data import Binding, IValueConverter, BindingMode


NO_VALUE = '(blank)'


# ---------------------------------------------------------------------------
# Converters
# ---------------------------------------------------------------------------

class RowConverter(IValueConverter):
    """Hands the whole row object to a Python callable with the column key."""

    def __init__(self, fn):
        self.fn = fn

    def Convert(self, value, target_type, parameter, culture):
        try:
            return self.fn(value, parameter)
        except Exception:
            return None

    def ConvertBack(self, value, target_type, parameter, culture):
        return None


# ---------------------------------------------------------------------------
# Column factories
# ---------------------------------------------------------------------------

def _bind(converter, key):
    binding = Binding('.')
    binding.Converter = converter
    binding.ConverterParameter = key
    binding.Mode = BindingMode.OneWay
    return binding


def text_cell_template(text_conv, back_conv, fore_conv, key, bold_conv=None):
    border = FrameworkElementFactory(Border)
    border.SetBinding(Border.BackgroundProperty, _bind(back_conv, key))
    border.SetValue(Border.PaddingProperty, Thickness(7, 0, 7, 0))

    block = FrameworkElementFactory(TextBlock)
    block.SetBinding(TextBlock.TextProperty, _bind(text_conv, key))
    block.SetBinding(TextBlock.ForegroundProperty, _bind(fore_conv, key))
    if bold_conv is not None:
        block.SetBinding(TextBlock.FontWeightProperty, _bind(bold_conv, key))
    block.SetValue(TextBlock.VerticalAlignmentProperty, VerticalAlignment.Center)
    block.SetValue(TextBlock.TextTrimmingProperty, TextTrimming.CharacterEllipsis)
    block.SetBinding(FrameworkElement.ToolTipProperty, _bind(text_conv, key))
    border.AppendChild(block)

    template = DataTemplate()
    template.VisualTree = border
    return template


def combo_cell_template(back_conv, key, on_loaded=None, on_changed=None):
    """The swap dropdown in every row.

    Both handlers are attached to the factory, not to the grid.  Loaded is a
    Direct routed event - its route holds only the element it fired on - so a
    handler registered on the DataGrid is never called for a cell's ComboBox,
    and the dropdown would sit there empty.  `on_loaded` and `on_changed` must
    be live delegates the caller keeps a reference to.
    """
    border = FrameworkElementFactory(Border)
    border.SetBinding(Border.BackgroundProperty, _bind(back_conv, key))
    border.SetValue(Border.PaddingProperty, Thickness(4, 1, 4, 1))

    combo = FrameworkElementFactory(ComboBox)
    combo.SetValue(ComboBox.HeightProperty, 30.0)
    combo.SetValue(ComboBox.MaxDropDownHeightProperty, 320.0)
    if on_loaded is not None:
        combo.AddHandler(FrameworkElement.LoadedEvent, on_loaded)
    if on_changed is not None:
        combo.AddHandler(Selector.SelectionChangedEvent, on_changed)
    border.AppendChild(combo)

    template = DataTemplate()
    template.VisualTree = border
    return template


def make_column(header_content, cell_template, width, key, min_width=70,
                star=None, sortable=True):
    """A column sized in stars shares the grid's width and grows with the window.

    Fixed pixel widths meant the value columns stayed cramped however wide the
    window was stretched, and anything past the right hand edge needed a
    horizontal scroll to read.
    """
    column = DataGridTemplateColumn()
    column.Header = header_content
    column.CellTemplate = cell_template
    column.MinWidth = min_width
    if star:
        column.Width = DataGridLength(float(star), DataGridLengthUnitType.Star)
    elif width:
        column.Width = DataGridLength(float(width), DataGridLengthUnitType.Pixel)
    else:
        column.Width = DataGridLength(1.0, DataGridLengthUnitType.Star)
    try:
        if sortable:
            column.SortMemberPath = key
        else:
            column.CanUserSort = False
    except Exception:
        pass
    return column


# ---------------------------------------------------------------------------
# Column headers: a label (or a parameter picker), a keyword search box, and an
# Excel style tick filter.  Ticking follows Excel's autofilter - everything
# ticked means no filter, unticking narrows, nothing ticked shows nothing.
# ---------------------------------------------------------------------------

class ColumnHeader(object):

    def __init__(self, key, title, on_search, on_filter_open=None,
                 param_items=None, on_param_change=None, searchable=True):
        self.key = key
        self.on_search = on_search
        self.on_param_change = on_param_change
        self.on_filter_open = on_filter_open
        self.search_box = None
        self.param_combo = None
        self.toggle = None
        self.popup = None
        self.allowed = None          # None = no filter on this column
        self._suppress = False

        panel = StackPanel()
        panel.Orientation = Orientation.Vertical
        panel.Margin = Thickness(0)

        top = StackPanel()
        top.Orientation = Orientation.Horizontal
        top.Margin = Thickness(0, 0, 0, 3)

        if param_items is not None:
            combo = ComboBox()
            combo.Height = 32
            combo.MinWidth = 84
            combo.HorizontalAlignment = HorizontalAlignment.Stretch
            combo.MaxDropDownHeight = 340
            combo.Tag = 'pick a parameter'
            for item in param_items:
                combo.Items.Add(item)
            combo.SelectionChanged += self._param_changed
            self.param_combo = combo
            top.Children.Add(combo)
        else:
            label = TextBlock()
            label.Text = title
            label.VerticalAlignment = VerticalAlignment.Center
            top.Children.Add(label)

        if on_filter_open is not None:
            toggle = ToggleButton()
            toggle.SetResourceReference(ToggleButton.StyleProperty, 'FilterCaret')
            toggle.Margin = Thickness(4, 0, 0, 0)
            toggle.Checked += self._open_popup
            toggle.Unchecked += self._close_popup
            self.toggle = toggle
            top.Children.Add(toggle)

        panel.Children.Add(top)

        if searchable:
            box = TextBox()
            box.Height = 32
            box.Tag = 'search'
            box.TextChanged += self._search_changed
            self.search_box = box
            panel.Children.Add(box)

        self.content = panel

    # -- events -----------------------------------------------------------
    def _search_changed(self, sender, args):
        if self._suppress:
            return
        if self.on_search:
            self.on_search()

    def _param_changed(self, sender, args):
        self._name_tooltip()
        if self._suppress:
            return
        if self.on_param_change:
            self.on_param_change(self.key, str(sender.SelectedItem or ''))

    def _name_tooltip(self):
        try:
            chosen = str(self.param_combo.SelectedItem or '')
            self.param_combo.ToolTip = chosen or 'Pick a parameter for this column'
        except Exception:
            pass

    def _open_popup(self, sender, args):
        if self.on_filter_open:
            self.on_filter_open(self)

    def _close_popup(self, sender, args):
        if self.popup is not None:
            try:
                self.popup.IsOpen = False
            except Exception:
                pass

    # -- state ------------------------------------------------------------
    @property
    def search_text(self):
        if self.search_box is None:
            return ''
        return (self.search_box.Text or '').strip().lower()

    def set_param(self, name):
        if self.param_combo is None:
            return
        self._suppress = True
        try:
            if name and name in list(self.param_combo.Items):
                self.param_combo.SelectedItem = name
            else:
                self.param_combo.SelectedIndex = -1
        finally:
            self._suppress = False
        self._name_tooltip()

    def clear(self):
        self._suppress = True
        try:
            if self.search_box is not None:
                self.search_box.Text = ''
        finally:
            self._suppress = False
        self.allowed = None
        self._mark()

    def _mark(self):
        if self.toggle is None:
            return
        try:
            key = 'OrangeBrush' if self.allowed is not None else 'MutedBrush'
            self.toggle.SetResourceReference(ToggleButton.ForegroundProperty, key)
        except Exception:
            pass

    def passes(self, text):
        value = text or ''
        needle = self.search_text
        if needle and needle not in value.lower():
            return False
        if self.allowed is not None:
            if (value or NO_VALUE) not in self.allowed:
                return False
        return True


class TickFilter(object):
    """The tick list behind a column header's caret."""

    def __init__(self, header, values, on_apply):
        self.header = header
        self.on_apply = on_apply
        self.values = list(values)
        self.checks = []

        popup = Popup()
        popup.StaysOpen = False
        popup.AllowsTransparency = True
        popup.Placement = PlacementMode.Bottom
        popup.PlacementTarget = header.toggle
        popup.Closed += self._closed

        border = Border()
        border.CornerRadius = CornerRadius(4.0)
        border.BorderThickness = Thickness(1)
        border.Padding = Thickness(8)
        border.MinWidth = 210
        border.SetResourceReference(Border.BackgroundProperty, 'PopupBg')
        border.SetResourceReference(Border.BorderBrushProperty, 'WindowEdge')

        panel = StackPanel()

        search = TextBox()
        search.Height = 30
        search.Margin = Thickness(0, 0, 0, 5)
        search.TextChanged += self._search
        self.search = search
        panel.Children.Add(search)

        row = StackPanel()
        row.Orientation = Orientation.Horizontal
        row.Margin = Thickness(0, 0, 0, 5)
        all_btn = Button()
        all_btn.Content = 'All'
        all_btn.SetResourceReference(Button.StyleProperty, 'GhostButton')
        all_btn.Margin = Thickness(0, 0, 4, 0)
        all_btn.Click += self._all
        none_btn = Button()
        none_btn.Content = 'None'
        none_btn.SetResourceReference(Button.StyleProperty, 'GhostButton')
        none_btn.Click += self._none
        row.Children.Add(all_btn)
        row.Children.Add(none_btn)
        panel.Children.Add(row)

        scroller = ScrollViewer()
        scroller.MaxHeight = 260
        scroller.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
        scroller.HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled
        self.host = StackPanel()
        scroller.Content = self.host
        panel.Children.Add(scroller)

        apply_btn = Button()
        apply_btn.Content = 'Filter'
        apply_btn.Margin = Thickness(0, 6, 0, 0)
        apply_btn.Click += self._apply
        panel.Children.Add(apply_btn)

        border.Child = panel
        popup.Child = border
        self.popup = popup

        allowed = header.allowed
        for value in self.values:
            box = CheckBox()
            box.Content = value
            box.Margin = Thickness(0, 2, 0, 2)
            box.IsChecked = (allowed is None) or (value in allowed)
            self.checks.append(box)
            self.host.Children.Add(box)

    def show(self):
        self.popup.IsOpen = True

    def _search(self, sender, args):
        needle = (self.search.Text or '').strip().lower()
        for box in self.checks:
            visible = (not needle) or (needle in str(box.Content).lower())
            box.Visibility = Visibility.Visible if visible else Visibility.Collapsed

    def _all(self, sender, args):
        for box in self.checks:
            if box.Visibility == Visibility.Visible:
                box.IsChecked = True

    def _none(self, sender, args):
        for box in self.checks:
            if box.Visibility == Visibility.Visible:
                box.IsChecked = False

    def _apply(self, sender, args):
        ticked = set()
        for box in self.checks:
            if box.IsChecked:
                ticked.add(str(box.Content))
        if len(ticked) == len(self.checks):
            self.header.allowed = None      # everything ticked means no filter
        else:
            self.header.allowed = ticked
        self.header._mark()
        self.popup.IsOpen = False
        if self.on_apply:
            self.on_apply()

    def _closed(self, sender, args):
        try:
            if self.header.toggle is not None:
                self.header.toggle.IsChecked = False
        except Exception:
            pass
