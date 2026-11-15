# -*- coding: utf-8 -*-
"""Callout to 3D - the callout table.

Every column binds the row object itself with an IValueConverter and the
column key as ConverterParameter, rather than binding properties.  That
sidesteps the question of whether WPF can see Python attributes and is the
same pattern the rest of the extension uses.
"""

import c3d_clr  # noqa: F401  assemblies first, always

from System import Object                                           # noqa: E402
from System.Collections.Generic import List                          # noqa: E402
from System.Windows import (                                         # noqa: E402
    DataTemplate, FrameworkElement, FrameworkElementFactory, Thickness,
    HorizontalAlignment, VerticalAlignment, FontWeights, TextTrimming,
    CornerRadius, GridLength, GridUnitType, RoutedEventHandler,
)
from System.Windows.Controls import (                                # noqa: E402
    TextBlock, CheckBox, TextBox, Button, StackPanel, Orientation,
    DataGridTemplateColumn, DataGridLength, DataGridLengthUnitType, Grid,
    ColumnDefinition, Border, ScrollViewer,
)
from System.Windows.Controls.Primitives import Popup, PlacementMode  # noqa: E402
from System.Windows.Data import Binding, IValueConverter             # noqa: E402


# ---------------------------------------------------------------------------
# columns
# ---------------------------------------------------------------------------

def _size_text(row):
    size = row.get("size_mm") or (0, 0)
    try:
        return u"{0:.0f} x {1:.0f}".format(size[0], size[1])
    except Exception:
        return ""


def _flip_text(row):
    """Which of this row's sections face the other way.

    A whole axis reads as X or Y; a single section turned round on top of that
    reads as its own label, so the column says exactly what will be built.
    """
    parts = [axis for axis, key in (("X", "flip_x"), ("Y", "flip_y"))
             if row.get(key)]
    parts += sorted((row.get("flips") or {}).keys())
    return u" ".join(parts)


COLUMNS = [
    {"key": "tick", "header": "", "width": 34, "kind": "tick"},
    {"key": "name", "header": "Callout", "width": 2.4, "min": 170,
     "get": lambda row: row.get("name", ""), "filter": False},
    {"key": "level_name", "header": "Level", "width": 1.1, "min": 90,
     "get": lambda row: row.get("level_name", ""), "filter": True},
    {"key": "parent_name", "header": "Cut in", "width": 1.6, "min": 110,
     "get": lambda row: row.get("parent_name", ""), "filter": True},
    {"key": "scale", "header": "Scale", "width": 0.7, "min": 58,
     "get": lambda row: (u"1:{0}".format(row.get("scale")) if row.get("scale") else ""),
     "filter": True},
    {"key": "extent", "header": "Extent mm", "width": 1.0, "min": 92,
     "get": _size_text, "filter": False},
    {"key": "x_count", "header": "X", "width": 0.45, "min": 34,
     "get": lambda row: u"{0}".format(row.get("x_count", 0)), "filter": True},
    {"key": "y_count", "header": "Y", "width": 0.45, "min": 34,
     "get": lambda row: u"{0}".format(row.get("y_count", 0)), "filter": True},
    {"key": "flip", "header": "Flip", "width": 0.55, "min": 44,
     "get": _flip_text, "filter": True},
    {"key": "depth_mm", "header": "Depth", "width": 0.7, "min": 58,
     "get": lambda row: u"{0:.0f}".format(row.get("depth_mm", 0) or 0), "filter": True},
    {"key": "size", "header": "Sheet", "width": 0.6, "min": 52,
     "get": lambda row: row.get("size", ""), "filter": True},
    {"key": "sheet_text", "header": "Already on", "width": 1.2, "min": 92,
     "get": lambda row: (u"{0} {1}".format(row.get("sheet_number", ""),
                                           row.get("sheet_text", "")).strip()),
     "filter": True},
    {"key": "status", "header": "Note", "width": 1.6, "min": 110,
     "get": lambda row: row.get("status", ""), "filter": True},
]


def cell_text(row, key):
    for column in COLUMNS:
        if column["key"] == key and "get" in column:
            try:
                return column["get"](row) or ""
            except Exception:
                return ""
    return u"{0}".format(row.get(key, "") or "")


def row_haystack(row):
    parts = []
    for column in COLUMNS:
        if "get" in column:
            parts.append(cell_text(row, column["key"]))
    return u" ".join(parts).lower()


# ---------------------------------------------------------------------------
# converters
# ---------------------------------------------------------------------------


class CellConverter(IValueConverter):
    def Convert(self, value, target_type, parameter, culture):
        try:
            return cell_text(value, u"{0}".format(parameter))
        except Exception:
            return ""

    def ConvertBack(self, value, target_type, parameter, culture):
        return None


class InkConverter(IValueConverter):
    """Orange for a row that will be changed, red for one that needs a look,
    green for one already done."""

    def __init__(self, window):
        self.window = window

    def _brush(self, key):
        try:
            return self.window.TryFindResource(key)
        except Exception:
            return None

    def Convert(self, value, target_type, parameter, culture):
        try:
            state = (value.get("state") or "").lower()
            if state == "problem":
                return self._brush("RedBrush")
            if state == "done":
                return self._brush("GreenBrush")
            if value.get("checked"):
                return self._brush("OrangeBrush")
            return self._brush("TextBrush")
        except Exception:
            return None

    def ConvertBack(self, value, target_type, parameter, culture):
        return None


# ---------------------------------------------------------------------------
# building the grid
# ---------------------------------------------------------------------------


class CalloutGrid(object):
    def __init__(self, window, grid, on_change=None, on_select=None):
        self.window = window
        self.grid = grid
        self.rows = []
        self.visible = []
        self.on_change = on_change
        self.on_select = on_select
        self.searches = {}
        self.filters = {}
        self.keyword = ""
        # an extra test the window owns, applied before the column filters so
        # the tick lists only ever offer values that are actually on show
        self.prefilter = None
        self.sort_key = None
        self.sort_down = False
        self.cell_converter = CellConverter()
        self.ink_converter = InkConverter(window)
        self._popup = None
        self._build_columns()
        try:
            self.grid.Sorting += self._on_sorting
            self.grid.SelectionChanged += self._on_selection
        except Exception:
            pass

    # ------------------------------------------------------------------
    def _header(self, column):
        panel = StackPanel()
        panel.Orientation = Orientation.Vertical

        top = Grid()
        first = ColumnDefinition()
        first.Width = GridLength(1, GridUnitType.Star)
        second = ColumnDefinition()
        second.Width = GridLength(1, GridUnitType.Auto)
        top.ColumnDefinitions.Add(first)
        top.ColumnDefinitions.Add(second)

        label = TextBlock()
        label.Text = column["header"]
        label.VerticalAlignment = VerticalAlignment.Center
        label.FontWeight = FontWeights.Bold
        Grid.SetColumn(label, 0)
        top.Children.Add(label)

        if column.get("filter"):
            caret = Button()
            caret.Content = u"\u25BE"
            caret.Width = 18
            caret.Height = 18
            caret.Tag = column["key"]
            try:
                caret.Style = self.window.TryFindResource("IconButton")
            except Exception:
                pass
            caret.Click += self._on_caret
            Grid.SetColumn(caret, 1)
            top.Children.Add(caret)

        panel.Children.Add(top)

        if "get" in column:
            box = TextBox()
            box.Height = 22
            box.MinHeight = 22
            box.Margin = Thickness(0, 3, 0, 0)
            box.FontSize = 11
            try:
                box.Style = self.window.TryFindResource("ThemedTextBox")
            except Exception:
                pass
            box.Tag = "search"
            box.TextChanged += self._make_search_handler(column["key"], box)
            box.PreviewMouseLeftButtonDown += self._on_box_click
            panel.Children.Add(box)
            self.searches[column["key"]] = box
        return panel

    def _on_box_click(self, sender, args):
        """A click inside a header search box would otherwise sort the column."""
        try:
            if not sender.IsKeyboardFocusWithin:
                sender.Focus()
                args.Handled = True
        except Exception:
            pass

    def _make_search_handler(self, key, box):
        def handler(sender, args):
            self.refresh()
        return handler

    def _build_columns(self):
        try:
            self.grid.Columns.Clear()
        except Exception:
            return
        for column in COLUMNS:
            grid_column = DataGridTemplateColumn()
            grid_column.Header = self._header(column)
            grid_column.CanUserSort = "get" in column
            if "get" in column:
                grid_column.SortMemberPath = column["key"]
            if column.get("kind") == "tick":
                grid_column.Width = DataGridLength(column["width"],
                                                   DataGridLengthUnitType.Pixel)
                grid_column.CellTemplate = self._tick_template()
            else:
                grid_column.Width = DataGridLength(column["width"],
                                                   DataGridLengthUnitType.Star)
                grid_column.MinWidth = column.get("min", 60)
                grid_column.CellTemplate = self._text_template(column["key"])
            self.grid.Columns.Add(grid_column)

    def _text_template(self, key):
        factory = FrameworkElementFactory(TextBlock)
        binding = Binding(".")
        binding.Converter = self.cell_converter
        binding.ConverterParameter = key
        factory.SetBinding(TextBlock.TextProperty, binding)
        ink = Binding(".")
        ink.Converter = self.ink_converter
        factory.SetBinding(TextBlock.ForegroundProperty, ink)
        factory.SetValue(FrameworkElement.MarginProperty, Thickness(6, 0, 6, 0))
        factory.SetValue(FrameworkElement.VerticalAlignmentProperty, VerticalAlignment.Center)
        factory.SetValue(TextBlock.TextTrimmingProperty, TextTrimming.CharacterEllipsis)
        template = DataTemplate()
        template.VisualTree = factory
        return template

    def _tick_template(self):
        factory = FrameworkElementFactory(CheckBox)
        factory.SetValue(FrameworkElement.HorizontalAlignmentProperty,
                         HorizontalAlignment.Center)
        factory.SetValue(FrameworkElement.VerticalAlignmentProperty,
                         VerticalAlignment.Center)
        try:
            factory.SetValue(FrameworkElement.StyleProperty,
                             self.window.TryFindResource("ThemedCheckBox"))
        except Exception:
            pass
        # Loaded is a Direct routed event, so the handler has to be on the
        # factory - one on the grid is never called for a control inside a cell
        factory.AddHandler(FrameworkElement.LoadedEvent,
                           RoutedEventHandler(self._on_tick_loaded))
        template = DataTemplate()
        template.VisualTree = factory
        return template

    def _on_tick_loaded(self, sender, args):
        try:
            row = sender.DataContext
            if row is None:
                return
            sender.IsChecked = bool(row.get("checked"))
            if u"{0}".format(sender.Tag) != "wired":
                sender.Tag = "wired"
                sender.Click += self._on_tick_click
        except Exception:
            pass

    def _on_tick_click(self, sender, args):
        try:
            row = sender.DataContext
            if row is None:
                return
            row["checked"] = bool(sender.IsChecked)
            if self.on_change:
                self.on_change()
        except Exception:
            pass

    # ------------------------------------------------------------------
    def _on_selection(self, sender, args):
        if self.on_select:
            try:
                self.on_select(self.selected_row())
            except Exception:
                pass

    def selected_row(self):
        try:
            item = self.grid.SelectedItem
            return item if item is not None else None
        except Exception:
            return None

    def selected_rows(self):
        out = []
        try:
            for item in self.grid.SelectedItems:
                if item is not None:
                    out.append(item)
        except Exception:
            pass
        return out

    def ticked(self):
        """Only the ticked rows that are actually on show.

        A row ticked and then filtered out of sight must not quietly join the
        run - what is being agreed to is what can be seen.
        """
        shown = self.visible if self.visible is not None else self.rows
        keys = set([id(row) for row in shown])
        return [row for row in shown if row.get("checked")] if keys else []

    def ticked_out_of_sight(self):
        """Rows that are ticked but filtered away, so the window can say so
        rather than silently dropping them."""
        shown = set([id(row) for row in (self.visible or [])])
        return [row for row in self.rows
                if row.get("checked") and id(row) not in shown]

    # ------------------------------------------------------------------
    def _on_sorting(self, sender, args):
        """Sort the row list rather than going through a CollectionView, since
        the grid binds row objects rather than properties."""
        try:
            args.Handled = True
            key = args.Column.SortMemberPath
            if not key:
                return
            if self.sort_key == key:
                self.sort_down = not self.sort_down
            else:
                self.sort_key = key
                self.sort_down = False
            self.refresh()
        except Exception:
            pass

    def _sorted(self, rows):
        key = self.sort_key
        if not key:
            return sorted(rows, key=lambda row: (row.get("level_mm", 0.0),
                                                 row.get("name", "").lower()))
        numeric = key in ("x_count", "y_count", "depth_mm", "scale")

        def sort_value(row):
            if numeric:
                try:
                    return float(row.get(key, 0) or 0)
                except Exception:
                    return 0.0
            return cell_text(row, key).lower()

        return sorted(rows, key=sort_value, reverse=self.sort_down)

    # ------------------------------------------------------------------
    def set_rows(self, rows):
        self.rows = rows
        self.filters = {}
        self.refresh()

    def refresh(self):
        rows = list(self.rows)
        if self.prefilter is not None:
            try:
                rows = [row for row in rows if self.prefilter(row)]
            except Exception:
                pass
        keyword = (self.keyword or "").strip().lower()
        if keyword:
            rows = [row for row in rows if keyword in row_haystack(row)]
        for key, box in self.searches.items():
            try:
                text = (box.Text or "").strip().lower()
            except Exception:
                text = ""
            if text:
                rows = [row for row in rows if text in cell_text(row, key).lower()]
        for key, allowed in self.filters.items():
            if allowed is None:
                continue
            rows = [row for row in rows if cell_text(row, key) in allowed]
        rows = self._sorted(rows)
        self.visible = rows

        items = List[Object]()
        for row in rows:
            items.Add(row)
        try:
            self.grid.ItemsSource = items
        except Exception:
            pass
        if self.on_change:
            try:
                self.on_change()
            except Exception:
                pass

    # ------------------------------------------------------------------
    def _on_caret(self, sender, args):
        key = u"{0}".format(sender.Tag)
        values = []
        seen = set()
        for row in self.rows:
            text = cell_text(row, key)
            if text not in seen:
                seen.add(text)
                values.append(text)
        values.sort(key=lambda text: text.lower())
        allowed = self.filters.get(key)
        self._show_filter(sender, key, values, allowed)

    def _show_filter(self, anchor, key, values, allowed):
        try:
            if self._popup is not None:
                self._popup.IsOpen = False
        except Exception:
            pass

        popup = Popup()
        popup.StaysOpen = False
        popup.AllowsTransparency = True
        popup.Placement = PlacementMode.Bottom
        popup.PlacementTarget = anchor

        border = Border()
        border.CornerRadius = CornerRadius(4)
        border.BorderThickness = Thickness(1)
        try:
            border.Background = self.window.TryFindResource("CardBrush")
            border.BorderBrush = self.window.TryFindResource("FrameBrush")
        except Exception:
            pass
        border.Padding = Thickness(8)

        panel = StackPanel()
        panel.Width = 230

        buttons = StackPanel()
        buttons.Orientation = Orientation.Horizontal
        buttons.Margin = Thickness(0, 0, 0, 6)

        boxes = []

        def set_all(state):
            for box in boxes:
                box.IsChecked = state

        all_button = Button()
        all_button.Content = "All"
        all_button.Margin = Thickness(0, 0, 6, 0)
        try:
            all_button.Style = self.window.TryFindResource("GhostButton")
        except Exception:
            pass
        all_button.Click += lambda s, a: set_all(True)
        buttons.Children.Add(all_button)

        none_button = Button()
        none_button.Content = "None"
        try:
            none_button.Style = self.window.TryFindResource("GhostButton")
        except Exception:
            pass
        none_button.Click += lambda s, a: set_all(False)
        buttons.Children.Add(none_button)
        panel.Children.Add(buttons)

        scroller = ScrollViewer()
        scroller.MaxHeight = 260
        inner = StackPanel()
        for value in values:
            box = CheckBox()
            box.Content = value if value else u"(blank)"
            box.Margin = Thickness(0, 3, 0, 3)
            box.IsChecked = (allowed is None) or (value in allowed)
            box.Tag = value
            try:
                box.Style = self.window.TryFindResource("ThemedCheckBox")
            except Exception:
                pass
            inner.Children.Add(box)
            boxes.append(box)
        scroller.Content = inner
        panel.Children.Add(scroller)

        apply_button = Button()
        apply_button.Content = "Apply"
        apply_button.Margin = Thickness(0, 8, 0, 0)
        try:
            apply_button.Style = self.window.TryFindResource("PrimaryButton")
        except Exception:
            pass

        def on_apply(sender, args):
            chosen = set()
            for box in boxes:
                if box.IsChecked:
                    chosen.add(u"{0}".format(box.Tag))
            if len(chosen) == len(values):
                self.filters.pop(key, None)      # everything ticked is no filter
            else:
                self.filters[key] = chosen
            popup.IsOpen = False
            self.refresh()

        apply_button.Click += on_apply
        panel.Children.Add(apply_button)

        border.Child = panel
        popup.Child = border
        popup.IsOpen = True
        self._popup = popup
