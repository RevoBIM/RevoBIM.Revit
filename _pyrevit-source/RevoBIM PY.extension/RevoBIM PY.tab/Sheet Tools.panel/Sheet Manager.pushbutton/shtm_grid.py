# -*- coding: utf-8 -*-
"""The sheet table: columns, cell converters, header search boxes, Excel style
tick filters, sorting and the group / cascade rows.

Every column binds the row object itself with an IValueConverter and the column
key as ConverterParameter, rather than binding properties. That sidesteps
whether WPF can see Python attributes, and it is what makes columns that do not
exist until the model is read possible at all.
"""

import shtm_clr  # noqa: F401  - references the assemblies first

import shtm_core
import shtm_ui
import theme
from shtm_ui import ui_safe, styled, text_block, button, text_box

from System.Windows import (
    Thickness, GridLength, GridUnitType, Visibility, VerticalAlignment,
    HorizontalAlignment, TextTrimming,
)
from System.Windows.Controls import (
    Grid, StackPanel, TextBlock, Border, ListBox, ListBoxItem, CheckBox,
    DataGridTemplateColumn, ColumnDefinition, Orientation, ScrollViewer,
    DataGridLength, DataGridLengthUnitType,
)
from System.Windows.Controls.Primitives import Popup, PlacementMode
from System.Windows.Data import Binding, IValueConverter
from System.Windows import FrameworkElementFactory, DataTemplate
from System.Windows.Media import Brushes

from shtm_rows import (
    FIXED_COLUMNS, BLANK_LABEL, Row, GridState, matches, compute_rows,
    export_csv,
)


class CellConverter(IValueConverter):
    """Reads the value out in Python. The binding is always '.'.

    With a store, the cell shows the pending edit rather than the sheet's own
    value - what you see is what Apply will write."""

    def __init__(self, key, first=False, store=None, index=0):
        self.key = key
        self.first = first
        self.index = index
        self.store = store

    def Convert(self, value, target_type, parameter, culture):
        row = value
        if row is None:
            return u""
        try:
            if row.kind == "group":
                # column one carries the label, column two the affordance -
                # a heading that does not say it can be opened does not look
                # as though it can
                if self.index == 0:
                    arrow = u"\u25BE" if row.expanded else u"\u25B8"
                    indent = u"      " * row.level
                    return u"{0}{1}  {2}".format(indent, arrow, row.label)
                if self.index == 1:
                    action = u"[ \u2212 ]  Collapse" if row.expanded else u"[ + ]  Expand"
                    return u"{0}   ({1})".format(action, row.count)
                return u""
            if self.store is not None and row.sheet is not None:
                held = self.store.get(row.sheet["id"], self.key)
                if held is not None:
                    return held
            return row.values.get(self.key, u"")
        except Exception:
            return u""

    def ConvertBack(self, value, target_type, parameter, culture):
        return None


class PendingConverter(IValueConverter):
    """The cell's background, from its state, in the order the reference
    tests them: strong red for a write Revit refused on the last Apply, green
    for a staged edit, teal for one that came from an Excel import, amber for
    the source of the clipboard, a duplicate highlight, light red for a cell
    that cannot be written. Read from the theme at conversion time so a
    palette switch just needs the columns rebuilt."""

    def __init__(self, key, store, highlights=None):
        self.key = key
        self.store = store
        self.highlights = highlights if highlights is not None else {}

    def Convert(self, value, target_type, parameter, culture):
        try:
            row = value
            if row is None or row.kind != "sheet" or row.sheet is None:
                return Brushes.Transparent
            sheet = row.sheet
            state = self.store.state_of(sheet["id"], self.key)
            if state in STATE_BRUSHES:
                return _brush(STATE_BRUSHES[state])
            group = self.highlights.get(self.key, {}).get(
                _dup_key(self.store.value_of(sheet, self.key)))
            if group is not None:
                return _brush(DUP_BRUSHES[group % len(DUP_BRUSHES)])
            if self.key in (sheet.get("readonly") or ()):
                return _brush(STATE_BRUSHES["readonly"])
        except Exception:
            pass
        return Brushes.Transparent

    def ConvertBack(self, value, target_type, parameter, culture):
        return None


def _dup_key(value):
    return u"{0}".format(value if value is not None else u"").strip().lower()


def _brush(key):
    """A brush from the active palette by key, at conversion time."""
    try:
        return theme.brush(theme.CURRENT.get(key))
    except Exception:
        return Brushes.Transparent


# ====================== the grid ======================

def cell_template(key, first, state=None, store=None, highlights=None,
                  column_index=0):
    """A Border around a TextBlock. The Border is what carries the colour bar
    of a sorted column down the table, and the pending-edit tint."""
    shell = FrameworkElementFactory(Border)
    index = state.sort_index(key) if state is not None else -1
    if 0 <= index < len(SORT_BRUSHES):
        shell.SetResourceReference(Border.BorderBrushProperty, SORT_BRUSHES[index])
        shell.SetValue(Border.BorderThicknessProperty, Thickness(2, 0, 2, 0))
    else:
        shell.SetValue(Border.BorderThicknessProperty, Thickness(0))
    if store is not None:
        tint = Binding(".")
        tint.Converter = PendingConverter(key, store, highlights)
        shell.SetBinding(Border.BackgroundProperty, tint)
    shell.SetValue(Border.PaddingProperty, Thickness(2, 0, 2, 0))

    factory = FrameworkElementFactory(TextBlock)
    binding = Binding(".")
    binding.Converter = CellConverter(key, first, store, column_index)
    factory.SetBinding(TextBlock.TextProperty, binding)
    factory.SetValue(TextBlock.VerticalAlignmentProperty, VerticalAlignment.Center)
    factory.SetValue(TextBlock.TextTrimmingProperty, TextTrimming.CharacterEllipsis)
    shell.AppendChild(factory)
    template = DataTemplate()
    template.VisualTree = shell
    return template


def build_columns(grid, state, on_change, distinct_for, store=None,
                  highlights=None, menu_for=None, widths=None):
    grid.Columns.Clear()
    for index, key in enumerate(state.columns):
        column = DataGridTemplateColumn()
        column.Header = header_element(key, state, on_change, distinct_for,
                                       menu_for)
        column.CellTemplate = cell_template(key, index == 0, state, store,
                                            highlights, index)
        # the column's own sort machinery is what turns a header click into an
        # event; the event is then taken over in wire_sorting
        column.CanUserSort = True
        column.SortMemberPath = key
        # a DataGrid column measures in DataGridLength, not GridLength - the
        # two look interchangeable and are not
        if widths and key in widths:
            column.Width = DataGridLength(float(widths[key]))
        else:
            column.Width = DataGridLength(2.0 if index == 0 else 1.6,
                                          DataGridLengthUnitType.Star)
        column.MinWidth = 240 if index == 0 else 110
        grid.Columns.Add(column)


# one colour per sort level, in the order the table reference gives them
SORT_BRUSHES = ["OrangeBrush", "BlueBrush", "GreenBrush", "VioletBrush",
                "TealBrush", "AmberBrush"]
DUP_BRUSHES = ["DupBg1", "DupBg2", "DupBg3", "DupBg4", "DupBg5", "DupBg6"]
STATE_BRUSHES = {
    "created": "CreatedBg",
    "failed": "RefusedBg",
    "refused": "RefusedBg",
    "edited": "StagedBg",
    "imported": "ImportBg",
    "copied": "CopiedBg",
    "readonly": "ReadOnlyBg",
}


WIDTH_FLOOR = 110.0
WIDTH_CEILING = 420.0


def autofit(grid, state):
    """Measure once and freeze the result in pixels, between a floor and a
    ceiling. Leaving columns on Auto looks like autofit and is not: it
    re-measures as rows are realised, so widths shift under the reader, and it
    has no ceiling, so one long value pushes the rest off the edge. The floor
    is not cosmetic - a heading carries a search box and a caret."""
    widths = {}
    try:
        for column in grid.Columns:
            key = u"{0}".format(column.SortMemberPath or u"")
            if not key:
                continue
            column.Width = DataGridLength(1.0, DataGridLengthUnitType.Auto)
        grid.UpdateLayout()
        for column in grid.Columns:
            key = u"{0}".format(column.SortMemberPath or u"")
            if not key:
                continue
            measured = float(column.ActualWidth or 0.0) + 12.0
            widths[key] = max(WIDTH_FLOOR, min(WIDTH_CEILING, measured))
            column.Width = DataGridLength(widths[key])
    except Exception:
        pass
    return widths


def wire_sorting(grid, state, on_change):
    """Sort through the DataGrid's own Sorting event, and cancel its sort.

    A DataGridColumnHeader is a ButtonBase: it captures the mouse on press,
    so a MouseLeftButtonUp on anything inside it routes to the header and never
    reaches the child that was clicked. Handling the header's click through
    the grid's Sorting event is the one route that fires for a click anywhere
    in the cell - and marking it handled stops the grid from also sorting
    through a CollectionView, which knows nothing about group rows.
    """
    @ui_safe
    def sorting(sender, event):
        event.Handled = True
        try:
            key = u"{0}".format(event.Column.SortMemberPath or u"")
        except Exception:
            key = u""
        if not key:
            return
        state.toggle_sort(key, _shift_held())
        state.collapsed = set()
        on_change(True)

    grid.Sorting += sorting


def header_element(key, state, on_change, distinct_for, menu_for=None):
    outer = Border()
    # a Border with no Background is not hit testable, so the click landed only
    # on the letters of the title and the header looked as though it sorted at
    # random. Transparent is a brush; no brush is a hole.
    outer.Background = Brushes.Transparent
    outer.BorderThickness = Thickness(2)
    outer.CornerRadius = shtm_ui._corner(3)
    outer.Padding = Thickness(3, 1, 1, 1)
    outer.HorizontalAlignment = HorizontalAlignment.Stretch
    outer.ToolTip = (u"Click to sort by {0} and group by it. Shift-click "
                     u"another heading for a second level.".format(key))
    index = state.sort_index(key)
    _outline(outer, index)
    # no mouse handler here: a DataGridColumnHeader is a ButtonBase and
    # captures the mouse on press, so a release never reaches a child. The
    # click arrives as the grid's own Sorting event instead - see build_columns
    if menu_for is not None:
        try:
            outer.ContextMenu = menu_for(key)
        except Exception:
            pass

    shell = StackPanel()
    shell.Orientation = Orientation.Vertical
    outer.Child = shell

    line = Grid()
    line.ColumnDefinitions.Add(_col("*"))
    line.ColumnDefinitions.Add(_col("auto"))

    title = TextBlock()
    title.Text = header_text(key, state)
    styled(title, "Lbl.Body")
    title.Margin = Thickness(2, 0, 2, 3)
    title.Cursor = _hand()
    if index >= 0:
        title.SetResourceReference(TextBlock.ForegroundProperty,
                                   SORT_BRUSHES[min(index, len(SORT_BRUSHES) - 1)])
    Grid.SetColumn(title, 0)
    line.Children.Add(title)

    caret = button(u"\u25BE", "Btn.Flat", (0, 0, 0, 3), 22)
    caret.MinHeight = 18
    caret.Height = 18
    caret.ToolTip = u"Filter"
    Grid.SetColumn(caret, 1)
    line.Children.Add(caret)

    popup = filter_popup(key, state, on_change, distinct_for, caret)
    line.Children.Add(popup)

    @ui_safe
    def open_popup(sender, event):
        popup.IsOpen = not popup.IsOpen

    caret.Click += open_popup
    shell.Children.Add(line)

    search = text_box(u"search", None, "Txt.Small")
    search.Text = state.searches.get(key, u"")

    timer = shtm_ui.debounce(250, lambda: on_change(False))

    @ui_safe
    def typed(sender, event):
        state.searches[key] = sender.Text or u""
        timer.Stop()
        timer.Start()

    search.TextChanged += typed
    shell.Children.Add(search)
    return outer


def _outline(border, index):
    """The column sorted on is outlined, and each sort level has its own
    colour - so a second level added with shift is visible as a second level
    rather than as 'something changed'. The title takes the same colour, since
    a two pixel outline on a dark header is easy to miss."""
    if index < 0 or index >= len(SORT_BRUSHES):
        border.BorderBrush = Brushes.Transparent
        return
    border.SetResourceReference(Border.BorderBrushProperty, SORT_BRUSHES[index])


def _shift_held():
    try:
        from System.Windows.Input import Keyboard, ModifierKeys
        return bool(Keyboard.Modifiers & ModifierKeys.Shift)
    except Exception:
        return False


def header_text(key, state):
    index = state.sort_index(key)
    if index < 0:
        return key
    arrow = u"\u25B2" if state.sort_up(key) else u"\u25BC"
    # its place and its arrow: 1▲, 2▼, 3▲ - so a six level sort can be read
    return u"{0}  {1}{2}".format(key, index + 1, arrow)


def filter_popup(key, state, on_change, distinct_for, target):
    popup = Popup()
    popup.Placement = PlacementMode.Bottom
    popup.PlacementTarget = target
    popup.StaysOpen = False
    popup.AllowsTransparency = True

    shell = Border()
    shell.SetResourceReference(Border.BackgroundProperty, "CardBg")
    shell.SetResourceReference(Border.BorderBrushProperty, "EdgeBrush")
    shell.BorderThickness = Thickness(1)
    shell.CornerRadius = shtm_ui._corner(3)
    shell.MinWidth = 240
    shell.Padding = Thickness(8)

    body = StackPanel()
    search = text_box(u"search these values", None, "Txt.Small")
    body.Children.Add(search)

    buttons = StackPanel()
    buttons.Orientation = Orientation.Horizontal
    buttons.Margin = Thickness(0, 6, 0, 6)
    all_button = button(u"All", "Btn.Flat", (0, 0, 6, 0), 60)
    none_button = button(u"None", "Btn.Flat", (0, 0, 0, 0), 60)
    all_button.MinHeight = 24
    none_button.MinHeight = 24
    buttons.Children.Add(all_button)
    buttons.Children.Add(none_button)
    body.Children.Add(buttons)

    listing = ListBox()
    styled(listing, "Lst.Flat")
    listing.MaxHeight = 260
    body.Children.Add(listing)
    shell.Child = body
    popup.Child = shell

    boxes = {}
    counts = {}

    @ui_safe
    def ticked(sender, event):
        if not filling[0]:
            collect()

    filling = [False]

    def fill(needle=u""):
        filling[0] = True
        listing.Items.Clear()
        boxes.clear()
        counts.clear()
        counts.update(distinct_for(key, True))
        allowed = state.filters.get(key)
        for value in distinct_for(key):
            label = value if value else BLANK_LABEL
            if needle and needle.lower() not in label.lower():
                continue
            item = ListBoxItem()
            styled(item, "Lst.Item")
            box = CheckBox()
            box.Content = u"{0}   ({1})".format(label, counts.get(value, 0))
            box.IsChecked = (allowed is None) or (value in allowed)
            styled(box, "Chk.Flat")
            box.Checked += ticked
            box.Unchecked += ticked
            boxes[value] = box
            item.Content = box
            listing.Items.Add(item)
        filling[0] = False

    def collect():
        chosen = set()
        allowed = state.filters.get(key)
        for value in boxes:
            if boxes[value].IsChecked:
                chosen.add(value)
        if allowed is not None:
            # values filtered out of the popup by its own search keep their state
            for value in allowed:
                if value not in boxes:
                    chosen.add(value)
        every = set(distinct_for(key))
        if chosen == every:
            state.filters.pop(key, None)
        else:
            state.filters[key] = chosen
        # rows only: rebuilding the columns would tear down the header this
        # popup lives in, and with it the popup
        on_change(False)
        paint_caret()

    @ui_safe
    def opened(sender, event):
        if popup.IsOpen:
            fill(search.Text or u"")

    popup.Opened += opened

    @ui_safe
    def typed(sender, event):
        fill(sender.Text or u"")

    search.TextChanged += typed

    @ui_safe
    def tick_all(sender, event):
        state.filters.pop(key, None)
        fill(search.Text or u"")
        on_change(False)
        paint_caret()

    @ui_safe
    def tick_none(sender, event):
        state.filters[key] = set()
        fill(search.Text or u"")
        on_change(False)
        paint_caret()

    def paint_caret():
        """The caret says when a filter is on, since the column list does not
        get rebuilt to say it."""
        try:
            if target is not None:
                target.Content = (u"\u25BC\u2022" if key in state.filters
                                  else u"\u25BC")
                target.SetResourceReference(
                    _foreground_property(),
                    "OrangeBrush" if key in state.filters else "MutedBrush")
        except Exception:
            pass

    all_button.Click += tick_all
    none_button.Click += tick_none

    @ui_safe
    def closed(sender, event):
        collect()

    popup.Closed += closed
    return popup


def _foreground_property():
    from System.Windows.Controls import Control
    return Control.ForegroundProperty


def _col(width):
    definition = ColumnDefinition()
    if width == "auto":
        definition.Width = GridLength(1, GridUnitType.Auto)
    else:
        definition.Width = GridLength(1, GridUnitType.Star)
    return definition


def _hand():
    from System.Windows.Input import Cursors
    return Cursors.Hand


GROUP_BRUSHES = ["GroupL1Bg", "GroupL2Bg", "GroupL3Bg", "GroupL4Bg",
                 "GroupL5Bg", "GroupL6Bg"]
BAND_BRUSHES = ["BandL1Bg", "BandL2Bg", "BandL3Bg", "BandL4Bg", "BandL5Bg",
                "BandL6Bg"]


def paint_row(row_element, item, palette_is_light):
    """Group rows get a band across the whole row, one colour per level, so a
    three-deep grouping reads as three depths rather than as three identical
    stripes. Set from LoadingRow rather than a trigger, because a DataTrigger
    would have to read a Python attribute."""
    try:
        band = getattr(item, "band", None) if item is not None else None
        if item is not None and item.kind == "group":
            # each top-level group its own colour, the way Excel for Revit
            # bands them; a nested heading shares its group's colour
            index = band if band is not None else item.level
            row_element.SetResourceReference(
                _background_property(), GROUP_BRUSHES[index % len(GROUP_BRUSHES)])
            row_element.FontWeight = _bold()
        elif band is not None:
            # the rows under a heading carry a soft tint of the same colour
            row_element.SetResourceReference(
                _background_property(), BAND_BRUSHES[band % len(BAND_BRUSHES)])
            row_element.FontWeight = _normal()
        else:
            row_element.ClearValue(_background_property())
            row_element.FontWeight = _normal()
    except Exception:
        pass


def _background_property():
    from System.Windows.Controls import DataGridRow
    return DataGridRow.BackgroundProperty


def _bold():
    from System.Windows import FontWeights
    return FontWeights.Bold


def _normal():
    from System.Windows import FontWeights
    return FontWeights.Normal


def _touch():
    """Keeps Brushes, ScrollViewer and Visibility referenced for the bench."""
    return (Brushes is not None and ScrollViewer is not None
            and Visibility is not None)
