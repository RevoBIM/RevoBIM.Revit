# -*- coding: utf-8 -*-
"""Family Viewer - the list: columns, cell converters, headers, tick filters.

Every column binds the row object itself ('.') with an IValueConverter and the
column key as ConverterParameter, rather than binding properties.  That
sidesteps the question of whether WPF can see IronPython attributes, and it is
what makes columns that do not exist until the model is read possible at all.
"""

import fv_clr  # noqa: F401  - must be first

from System import Object
from System.Collections.Generic import List
from System.Windows import (
    CornerRadius, DataTemplate, FrameworkElement, FrameworkElementFactory,
    FontWeights, GridLength, HorizontalAlignment, Rect, TextTrimming,
    Thickness, VerticalAlignment, Visibility,
)
from System.Windows.Controls import (
    Border, Button, CheckBox, ColumnDefinition, ContextMenu, MenuItem,
    DataGridLength, DataGridLengthUnitType, DataGridTemplateColumn,
    Grid, Image, ListBox, ListBoxItem, Orientation, RowDefinition,
    StackPanel, TextBlock, TextBox,
)
from System.Windows.Controls.Primitives import Popup, PlacementMode, ToggleButton
from System.Windows.Data import Binding, IValueConverter
from System.Windows.Input import Cursors
from System.Windows.Media import (
    Brushes, Geometry, RectangleGeometry, Stretch,
)
from System.Windows.Shapes import Path as ShapePath

import fv_core
import fv_model
from fv_core import matches_search, natural_key
from fv_model import (
    FAMILY_ROW, KEY_CATEGORY, KEY_COUNT, KEY_NAME, TYPE_ROW,
)

CHEVRON_SHUT = 'M 0 0 L 5 4 L 0 8 Z'
CHEVRON_OPEN = 'M 0 0 L 8 0 L 4 5 Z'
# A pointing hand - index finger up, thumb and folded fingers below.  Drawn as
# a Path rather than set in a symbol font, so it cannot come out as an empty box
# on a machine without that font.
PLACE_GLYPH = (
    'M 6.1 0 C 5.2 0 4.5 0.7 4.5 1.6 L 4.5 8.0 L 3.6 6.9 '
    'C 3.1 6.3 2.2 6.2 1.6 6.7 C 1.0 7.2 0.9 8.1 1.4 8.7 '
    'L 4.2 12.2 C 4.9 13.1 6.0 13.6 7.1 13.6 L 10.4 13.6 '
    'C 12.2 13.6 13.7 12.1 13.7 10.3 L 13.7 6.6 '
    'C 13.7 5.9 13.1 5.3 12.4 5.3 C 12.0 5.3 11.7 5.4 11.5 5.7 '
    'C 11.3 5.1 10.8 4.7 10.2 4.7 C 9.8 4.7 9.4 4.9 9.2 5.1 '
    'C 8.9 4.6 8.4 4.3 7.9 4.3 C 7.7 4.3 7.5 4.3 7.3 4.4 '
    'L 7.3 1.6 C 7.3 0.7 6.9 0 6.1 0 Z')
INDENT = 22.0
# Washes for the grouped column, one per distinct value, cycling.  Kept faint:
# they sit behind the value, and a strong fill would fight the staged-edit and
# refusal colours, which have to stay the loudest things in the table.
GROUP_TINTS = ['#4D6A8E', '#4C7457', '#84654A', '#6A5383', '#3E6E77',
               '#82566B']
GROUP_TINTS_LIGHT = ['#D9E5F3', '#DCEBDD', '#F3E6D4', '#E6DCF0', '#D6EBEC',
                     '#F0DCE2']


def _indent_of(row):
    """How far in each level sits: family, type, group heading, element."""
    if row.kind == FAMILY_ROW:
        return 0.0
    if row.kind == TYPE_ROW:
        return INDENT
    if row.kind == fv_model.GROUP_ROW:
        return INDENT * 2.0
    if row.kind == fv_model.INSTANCE_ROW:
        # an instance under a group heading sits one step further in than one
        # under a type, so the two levels do not read as the same one
        under_group = (row.parent is not None and
                       row.parent.kind == fv_model.GROUP_ROW)
        return INDENT * (3.0 if under_group else 2.0)
    return INDENT


# ---------------------------------------------------------------------------
# converters
# ---------------------------------------------------------------------------

class CellConverter(IValueConverter):
    """One converter for every cell.  The column key arrives as the
    ConverterParameter and the row object as the value."""

    def __init__(self, owner):
        self.owner = owner

    def Convert(self, value, target_type, parameter, culture):
        try:
            return self._convert(value, str(parameter))
        except Exception:
            return ''

    def ConvertBack(self, value, target_type, parameter, culture):
        return None

    def _convert(self, row, key):
        owner = self.owner
        if row is None:
            return ''
        family = (row.kind == FAMILY_ROW)

        if key == 'chev.data':
            return Geometry.Parse(CHEVRON_OPEN if row.open else CHEVRON_SHUT)
        if key == 'chev.vis':
            # a chevron on anything that has something under it: a family, a
            # type whose instances have been read, and a group heading
            if family or row.kind == fv_model.GROUP_ROW:
                return Visibility.Visible
            if row.kind == fv_model.TYPE_ROW and row.loaded and row.instances:
                return Visibility.Visible
            return Visibility.Hidden
        if key == 'indent':
            return Thickness(_indent_of(row), 0.0, 0.0, 0.0)

        if key == 'img.size':
            return float(owner.preview_edge(row))
        if key == 'img.src':
            return owner.preview_for(row)
        if key == 'img.vis':
            if owner.preview_edge(row) <= 0:
                return Visibility.Collapsed
            return Visibility.Visible
        if key == 'img.clip':
            # a Border does not clip its child, so the rounded corners have to
            # be a clip on the image itself
            edge = float(owner.preview_edge(row))
            if edge <= 0:
                return None
            clip = RectangleGeometry()
            clip.Rect = Rect(0.0, 0.0, edge, edge)
            radius = min(4.0, edge / 6.0)
            clip.RadiusX = radius
            clip.RadiusY = radius
            return clip

        if key.startswith('tint:'):
            return owner.group_tint(row, key[5:])

        if key == 'place.vis':
            return Visibility.Visible if owner.can_place(row) \
                else Visibility.Collapsed

        if key == 'name.text':
            staged = owner.staged(row, KEY_NAME)
            return row.label if staged is None else staged
        if key == 'name.fg':
            if row.kind == fv_model.GROUP_ROW:
                return owner.brush('AccentOrange')
            if row.kind == fv_model.INSTANCE_ROW:
                return owner.brush('FgMuted')
            staged = owner.staged_brush(row, KEY_NAME)
            if staged is not None:
                return staged
            return owner.brush('AccentBlue' if family else 'FgBody')
        if key == 'name.size':
            # a family name reads as a heading over the types under it
            if family:
                return float(owner.family_font_size())
            if row.kind == fv_model.INSTANCE_ROW:
                return 11.5
            return 12.5
        if key == 'name.weight':
            if owner.staged(row, KEY_NAME) is not None:
                return FontWeights.SemiBold
            return FontWeights.SemiBold if family else FontWeights.Normal

        if key == 'sub.text':
            if family:
                count = len(row.children)
                word = ' type' if count == 1 else ' types'
                extra = ' - system family' if row.is_system else ''
                return str(count) + word + extra
            return ''
        if key == 'sub.vis':
            return Visibility.Visible if family else Visibility.Collapsed

        if key == KEY_COUNT:
            return str(row.count)
        if key == 'count.fg':
            # nothing placed is worth seeing, so a zero is red rather than
            # quietly greyed out
            if row.count == 0:
                return owner.brush('WarnRed')
            return owner.brush('AccentOrange' if family else 'FgBody')
        if key == 'count.weight':
            # the family total is the one to read at a glance
            return FontWeights.Bold if family else FontWeights.Normal

        if key == KEY_CATEGORY:
            return row.category if family else ''

        if key.startswith('p:'):
            name = key[2:]
            staged = owner.staged(row, name)
            if staged is not None:
                return staged
            return row.cell(name) or ''
        if key.startswith('pfg:'):
            name = key[4:]
            # the same colour rule as the name column: before this, a
            # parameter staged by the batch window came out orange while its
            # name came out green
            staged = owner.staged_brush(row, name)
            if staged is not None:
                return staged
            text = row.cell(name)
            if text == fv_core.VARIES:
                return owner.brush('FgMuted')
            return owner.brush('FgBody')
        if key.startswith('pweight:'):
            if owner.staged(row, key[8:]) is not None:
                return FontWeights.SemiBold
            return FontWeights.Normal

        if key == 'tip':
            return owner.tooltip_for(row)
        return row.cell(key)


# ---------------------------------------------------------------------------
# column building
# ---------------------------------------------------------------------------

def _bind(converter, key):
    binding = Binding('.')
    binding.Converter = converter
    binding.ConverterParameter = key
    return binding


def _tinted_factory(converter, key, fg_key=None, weight_key=None, align=None,
                    tint_key=None):
    """A cell whose background can be tinted.

    Used for the grouped column: every distinct value gets its own wash, so
    which elements share a value reads at a glance without comparing the text
    of forty rows by eye.  A TextBlock has no usable background of its own in
    this template, so the tint is a Border round it.
    """
    if tint_key is None:
        return _text_factory(converter, key, fg_key, weight_key, align)

    shell = FrameworkElementFactory(Border)
    shell.SetValue(Border.CornerRadiusProperty, CornerRadius(2.0))
    shell.SetValue(FrameworkElement.MarginProperty,
                   Thickness(2.0, 1.0, 2.0, 1.0))
    shell.SetValue(FrameworkElement.HorizontalAlignmentProperty,
                   HorizontalAlignment.Stretch)
    shell.SetBinding(Border.BackgroundProperty, _bind(converter, tint_key))

    text = FrameworkElementFactory(TextBlock)
    text.SetBinding(TextBlock.TextProperty, _bind(converter, key))
    text.SetValue(TextBlock.VerticalAlignmentProperty,
                  VerticalAlignment.Center)
    text.SetValue(TextBlock.MarginProperty, Thickness(4.0, 1.0, 4.0, 1.0))
    text.SetValue(TextBlock.TextTrimmingProperty,
                  TextTrimming.CharacterEllipsis)
    if fg_key:
        text.SetBinding(TextBlock.ForegroundProperty, _bind(converter, fg_key))
    if weight_key:
        text.SetBinding(TextBlock.FontWeightProperty,
                        _bind(converter, weight_key))
    if align is not None:
        text.SetValue(TextBlock.HorizontalAlignmentProperty, align)
    shell.AppendChild(text)
    return shell


def _text_factory(converter, key, fg_key=None, weight_key=None, align=None):
    factory = FrameworkElementFactory(TextBlock)
    factory.SetBinding(TextBlock.TextProperty, _bind(converter, key))
    factory.SetValue(TextBlock.VerticalAlignmentProperty, VerticalAlignment.Center)
    factory.SetValue(TextBlock.MarginProperty, Thickness(6.0, 2.0, 6.0, 2.0))
    factory.SetValue(TextBlock.TextTrimmingProperty, TextTrimming.CharacterEllipsis)
    if fg_key:
        factory.SetBinding(TextBlock.ForegroundProperty, _bind(converter, fg_key))
    if weight_key:
        factory.SetBinding(TextBlock.FontWeightProperty, _bind(converter, weight_key))
    if align is not None:
        factory.SetValue(TextBlock.HorizontalAlignmentProperty, align)
    return factory


def _template(factory):
    template = DataTemplate()
    template.VisualTree = factory
    return template


def name_template(converter):
    """Chevron, preview image, family or type name, and a small note under a
    family name."""
    root = FrameworkElementFactory(StackPanel)
    root.SetValue(StackPanel.OrientationProperty, Orientation.Horizontal)
    root.SetValue(FrameworkElement.VerticalAlignmentProperty, VerticalAlignment.Center)
    root.SetBinding(FrameworkElement.MarginProperty, _bind(converter, 'indent'))

    chevron_host = FrameworkElementFactory(Grid)
    chevron_host.SetValue(FrameworkElement.WidthProperty, 18.0)
    chevron_host.SetValue(FrameworkElement.TagProperty, 'chevron')
    chevron_host.SetValue(Grid.BackgroundProperty, None)

    chevron = FrameworkElementFactory(ShapePath)
    chevron.SetBinding(ShapePath.DataProperty, _bind(converter, 'chev.data'))
    chevron.SetBinding(FrameworkElement.VisibilityProperty, _bind(converter, 'chev.vis'))
    chevron.SetValue(FrameworkElement.HorizontalAlignmentProperty, HorizontalAlignment.Center)
    chevron.SetValue(FrameworkElement.VerticalAlignmentProperty, VerticalAlignment.Center)
    chevron.SetValue(FrameworkElement.TagProperty, 'chevron')
    chevron.SetResourceReference(ShapePath.FillProperty, 'FgMuted')
    chevron_host.AppendChild(chevron)
    root.AppendChild(chevron_host)

    image = FrameworkElementFactory(Image)
    image.SetBinding(Image.SourceProperty, _bind(converter, 'img.src'))
    image.SetBinding(FrameworkElement.WidthProperty, _bind(converter, 'img.size'))
    image.SetBinding(FrameworkElement.HeightProperty, _bind(converter, 'img.size'))
    image.SetBinding(FrameworkElement.VisibilityProperty, _bind(converter, 'img.vis'))
    image.SetBinding(FrameworkElement.ClipProperty, _bind(converter, 'img.clip'))
    image.SetValue(Image.StretchProperty, Stretch.Uniform)
    image.SetValue(FrameworkElement.MarginProperty, Thickness(2.0, 2.0, 6.0, 2.0))
    image.SetValue(FrameworkElement.VerticalAlignmentProperty, VerticalAlignment.Center)
    root.AppendChild(image)

    # Place instance, in the row rather than in the footer: the thing being
    # placed is the row, so the button belongs beside it
    place = FrameworkElementFactory(Button)
    place.SetValue(FrameworkElement.TagProperty, 'place')
    place.SetValue(FrameworkElement.MarginProperty,
                   Thickness(0.0, 0.0, 7.0, 0.0))
    place.SetValue(FrameworkElement.ToolTipProperty,
                   'Place an instance of this type in the active view')
    place.SetBinding(FrameworkElement.VisibilityProperty,
                     _bind(converter, 'place.vis'))
    place.SetResourceReference(FrameworkElement.StyleProperty, 'RowIconBtn')

    glyph = FrameworkElementFactory(ShapePath)
    glyph.SetValue(ShapePath.DataProperty, Geometry.Parse(PLACE_GLYPH))
    glyph.SetValue(FrameworkElement.WidthProperty, 12.0)
    glyph.SetValue(FrameworkElement.HeightProperty, 12.0)
    glyph.SetValue(ShapePath.StretchProperty, Stretch.Uniform)
    glyph.SetValue(FrameworkElement.TagProperty, 'place')
    glyph.SetResourceReference(ShapePath.FillProperty, 'FgMuted')
    place.AppendChild(glyph)
    root.AppendChild(place)

    stack = FrameworkElementFactory(StackPanel)
    stack.SetValue(StackPanel.OrientationProperty, Orientation.Vertical)
    stack.SetValue(FrameworkElement.VerticalAlignmentProperty, VerticalAlignment.Center)

    label = FrameworkElementFactory(TextBlock)
    label.SetBinding(TextBlock.TextProperty, _bind(converter, 'name.text'))
    label.SetBinding(TextBlock.ForegroundProperty, _bind(converter, 'name.fg'))
    label.SetBinding(TextBlock.FontWeightProperty, _bind(converter, 'name.weight'))
    label.SetBinding(TextBlock.FontSizeProperty, _bind(converter, 'name.size'))
    label.SetValue(TextBlock.MarginProperty, Thickness(0.0, 1.0, 6.0, 0.0))
    stack.AppendChild(label)

    note = FrameworkElementFactory(TextBlock)
    note.SetBinding(TextBlock.TextProperty, _bind(converter, 'sub.text'))
    note.SetBinding(FrameworkElement.VisibilityProperty, _bind(converter, 'sub.vis'))
    note.SetValue(TextBlock.FontSizeProperty, 10.5)
    note.SetResourceReference(TextBlock.ForegroundProperty, 'FgMuted')
    stack.AppendChild(note)

    root.AppendChild(stack)
    return _template(root)


class Column(object):
    """A column in the list, and what the header offers for it."""

    def __init__(self, key, title, kind='fixed', width=1.0, minimum=110.0,
                 pixels=150.0):
        self.key = key
        self.title = title
        self.kind = kind            # fixed | param
        self.width = width
        self.minimum = minimum
        # Every column but the first is sized in PIXELS, not stars.  Star
        # columns share out whatever the grid has and so can never overflow it,
        # which means no horizontal scrollbar however narrow the window gets.
        # Pixels overflow, the first column stays frozen, and the bar appears.
        self.pixels = pixels
        self.search = ''
        self.allowed = None         # None means everything ticked
        self.column = None
        self.search_box = None
        self.caret = None
        self.popup = None
        self.list_box = None
        self.sort = 0               # 0 none, 1 up, -1 down
        self.picker = None
        self.title_block = None
        self.arrow = None
        self.outline = None
        self.tick_search = None
        self.header = None
        self.picker_chip = None
        self.param_search = None
        self.param_list = None
        self.param_note = None
        self.param_popup = None


def base_columns(settings):
    # The count comes first and is frozen with the name, so the number stays
    # in view while the parameter columns scroll. Wide enough for three digits
    # and a heading, and it can still be dragged wider.
    # Family and type is the only star column, so it takes up the slack on a
    # wide window and stops at its minimum on a narrow one.
    return [
        Column(KEY_COUNT, '#', 'fixed', 0.4, 44.0, 52.0),
        Column(KEY_NAME, 'Family and type', 'fixed', 3.0, 180.0, 300.0),
        Column(KEY_CATEGORY, 'Category', 'fixed', 1.0, 90.0, 140.0),
    ]


# ---------------------------------------------------------------------------
# filtering
# ---------------------------------------------------------------------------

def distinct_values(families, key, extra_rows=None):
    """What a tick filter offers.

    Gathered from the type rows AND from the elements under them.  A parameter
    that lives on the instance rather than the type reads "(varies)" on the
    type line, so gathering from the type rows alone offered "(varies)" and
    nothing else - which is every value the list can actually be filtered by
    missing from the filter.
    """
    seen = {}
    rows = []
    for parent in families:
        for child in parent.children:
            rows.append(child)
    rows.extend(extra_rows or [])

    for row in rows:
        if key == KEY_CATEGORY:
            text = row.category
        else:
            text = row.cell(key)
        text = text or ''
        if text == fv_core.VARIES:
            # "(varies)" is the type line saying its instances disagree; the
            # values it stands for are in the list already, from those
            # instances, so offering it as well would only be a way to tick
            # something that filters to nothing
            continue
        seen[text] = seen.get(text, 0) + 1
    values = sorted(seen.keys(), key=natural_key)
    return [(value, seen[value]) for value in values]


def row_passes(row, columns, global_search):
    """A type row passes when every column's search and tick filter passes."""
    if global_search and not matches_search(row.search_text(), global_search):
        return False
    for column in columns:
        if column.key == fv_model.KEY_NAME:
            text = row.family_name + ' ' + row.type_name
        elif column.key == KEY_CATEGORY:
            text = row.category
        elif column.key == KEY_COUNT:
            text = str(row.count)
        else:
            text = row.cell(column.key)
        text = text or ''
        if column.search and not matches_search(text, column.search):
            return False
        if column.allowed is not None and text not in column.allowed:
            return False
    return True


def apply_filters(families, columns, global_search, families_open=None):
    """Filtering runs on the type rows.  A family appears where at least one of
    its types survives, and its Count is the sum of the ones that did - so the
    number on the family line always agrees with the lines under it."""
    kept = []
    for parent in families:
        children = [child for child in parent.children
                    if row_passes(child, columns, global_search)]
        if not children:
            continue
        shown = parent.__class__(FAMILY_ROW)
        shown.family_name = parent.family_name
        shown.family_id = parent.family_id
        shown.category = parent.category
        shown.category_id = parent.category_id
        shown.is_system = parent.is_system
        shown.preview_id = children[0].type_id
        shown.count = sum([child.count for child in children])
        shown.values = dict(parent.values)
        shown.children = children
        shown.open = parent.open if families_open is None else families_open
        shown.note = parent.note
        for child in children:
            child.parent = shown
        kept.append(shown)
    return kept


def sort_families(families, key, direction):
    """Sorting rebuilds the row list rather than going through a
    CollectionView, because the grid binds row objects rather than
    properties."""
    if not key or not direction:
        return families

    def family_key(parent):
        if key == KEY_NAME:
            return natural_key(parent.family_name)
        if key == KEY_CATEGORY:
            return natural_key(parent.category)
        if key == KEY_COUNT:
            return [(1, parent.count, '')]
        return natural_key(parent.cell(key))

    def type_key(child):
        if key == KEY_NAME:
            return natural_key(child.type_name)
        if key == KEY_CATEGORY:
            return natural_key(child.category)
        if key == KEY_COUNT:
            return [(1, child.count, '')]
        return natural_key(child.cell(key))

    ordered = sorted(families, key=family_key, reverse=(direction < 0))
    for parent in ordered:
        parent.children = sorted(parent.children, key=type_key,
                                 reverse=(direction < 0))
    return ordered


def to_list(rows):
    collection = List[Object]()
    for row in rows:
        collection.Add(row)
    return collection


# ---------------------------------------------------------------------------
# headers: a keyword search box on every heading, and an Excel style tick
# filter behind the caret where the values are worth picking from
# ---------------------------------------------------------------------------

ARROW_UP = 'M 4 0 L 8 6 L 0 6 Z'
ARROW_DOWN = 'M 0 0 L 8 0 L 4 6 Z'


def _styled(control, key):
    try:
        control.SetResourceReference(FrameworkElement.StyleProperty, key)
    except Exception:
        pass
    return control


PLUS = 'M 6.4 0 L 9.6 0 L 9.6 6.4 L 16 6.4 L 16 9.6 L 9.6 9.6 L 9.6 16 L 6.4 16 L 6.4 9.6 L 0 9.6 L 0 6.4 L 6.4 6.4 Z'


def plus_button(on_click):
    """The add-column button: a green plus drawn from a Path, not a "+" set in
    a font, so it cannot come out as an empty box."""
    button = Button()
    _styled(button, 'IconGreen')
    button.ToolTip = 'Add a column'
    glyph = ShapePath()
    glyph.Data = Geometry.Parse(PLUS)
    glyph.Width = 11.0
    glyph.Height = 11.0
    glyph.Stretch = Stretch.Uniform
    try:
        glyph.SetResourceReference(ShapePath.FillProperty, 'FgOnAccent')
    except Exception:
        pass
    button.Content = glyph
    button.Click += on_click
    return button


def header_menu(column, owner):
    """Right click a heading to take the column away.

    Family and type is the frozen column and carries the chevron, the preview
    and the name, so it is the one thing that cannot go; its entry is shown
    disabled rather than hidden, so the menu is the same everywhere.
    """
    menu = ContextMenu()
    _styled(menu, 'ThemedContextMenu')

    remove = MenuItem()
    _styled(remove, 'ThemedMenuItem')
    remove.Header = 'Remove this column'
    remove.IsEnabled = owner.can_remove(column)
    if not remove.IsEnabled:
        remove.Header = 'Family and type cannot be removed'

    def removed(sender, args):
        owner.remove_column(column)

    remove.Click += removed
    menu.Items.Add(remove)
    return menu


def build_header(column, owner):
    """The header for one column: its title (or, for a parameter column, a
    picker), a sort arrow, a filter caret and a keyword search box.

    The whole lot sits inside a border that lights orange while the list is
    sorted by that column.  The thickness never changes, only the colour, so
    lighting one cannot nudge the layout of the row of headings.
    """
    outline = Border()
    outline.BorderThickness = Thickness(1.5)
    outline.CornerRadius = CornerRadius(3.0)
    outline.Padding = Thickness(2.0, 1.0, 2.0, 1.0)
    outline.Margin = Thickness(0.0, 0.0, 2.0, 0.0)
    outline.BorderBrush = None
    column.outline = outline

    shell = Grid()
    shell.RowDefinitions.Add(RowDefinition())
    shell.RowDefinitions.Add(RowDefinition())
    shell.Margin = Thickness(0.0, 0.0, 0.0, 2.0)

    top = Grid()
    top.ColumnDefinitions.Add(ColumnDefinition())
    auto = ColumnDefinition()
    auto.Width = GridLength.Auto
    top.ColumnDefinitions.Add(auto)
    caret_column = ColumnDefinition()
    caret_column.Width = GridLength.Auto
    top.ColumnDefinitions.Add(caret_column)
    Grid.SetRow(top, 0)

    if column.kind == 'param':
        picker = _build_param_picker(column, owner)
        Grid.SetColumn(picker, 0)
        top.Children.Add(picker)
        column.picker = picker
    else:
        title = TextBlock()
        title.Text = column.title
        title.VerticalAlignment = VerticalAlignment.Center
        title.TextTrimming = TextTrimming.CharacterEllipsis
        title.Margin = Thickness(2.0, 0.0, 4.0, 0.0)
        title.Cursor = None
        Grid.SetColumn(title, 0)
        top.Children.Add(title)
        column.title_block = title

    # The arrow is its own hit target, and it is on EVERY column.  A parameter
    # column's heading is the picker chip, so clicking the heading cannot be
    # the sort - which left no way at all to sort by a parameter, and grouping
    # is by the sorted column.
    sort_hit = Border()
    # a Border with no Background is not hit testable, so it needs a
    # transparent one to be clickable at all
    sort_hit.Background = Brushes.Transparent
    sort_hit.Cursor = Cursors.Hand
    sort_hit.Padding = Thickness(3.0, 2.0, 5.0, 2.0)
    sort_hit.VerticalAlignment = VerticalAlignment.Center
    sort_hit.ToolTip = 'Sort by this column'

    arrow = ShapePath()
    arrow.Data = Geometry.Parse(ARROW_DOWN)
    arrow.VerticalAlignment = VerticalAlignment.Center
    try:
        arrow.SetResourceReference(ShapePath.FillProperty, 'FgMuted')
    except Exception:
        pass
    sort_hit.Child = arrow
    Grid.SetColumn(sort_hit, 1)
    top.Children.Add(sort_hit)
    column.arrow = arrow

    def on_sort_click(sender, args):
        owner.on_sort(column)

    sort_hit.MouseLeftButtonUp += on_sort_click

    caret = ToggleButton()
    _styled(caret, 'CaretToggle')
    caret.ToolTip = 'Filter this column'
    Grid.SetColumn(caret, 2)
    top.Children.Add(caret)
    column.caret = caret

    search = TextBox()
    _styled(search, 'MiniSearchBox')
    search.Tag = 'search'
    search.Text = column.search or ''
    search.Margin = Thickness(0.0, 2.0, 0.0, 0.0)
    Grid.SetRow(search, 1)
    column.search_box = search

    shell.Children.Add(top)
    shell.Children.Add(search)

    popup = _build_popup(column, owner)
    column.popup = popup
    shell.Children.Add(popup)

    # right click the heading to remove the column
    shell.ContextMenu = header_menu(column, owner)

    def on_search(sender, args):
        column.search = search.Text or ''
        owner.on_filter_changed()

    def on_caret(sender, args):
        if caret.IsChecked:
            owner.fill_tick_list(column)
            popup.PlacementTarget = caret
            popup.IsOpen = True
        else:
            popup.IsOpen = False

    def on_popup_closed(sender, args):
        caret.IsChecked = False

    search.TextChanged += on_search
    caret.Click += on_caret
    popup.Closed += on_popup_closed

    if column.kind != 'param':
        def on_title_click(sender, args):
            owner.on_sort(column)
        column.title_block.MouseLeftButtonUp += on_title_click

    outline.Child = shell
    return outline


PARAM_NONE = '(none)'
PARAM_REMOVE = '(remove this column)'


def _build_param_picker(column, owner):
    """The parameter a column shows, picked from a searchable list.

    A ComboBox was the first version and it does not scale: on a real job the
    list runs to hundreds of names and there is no way to narrow it.  This is
    the same shape as the category picker - a chip that opens a popup with a
    keyword search box over the list - and the list itself only offers the
    parameters the categories on show actually carry.
    """
    chip = ToggleButton()
    _styled(chip, 'ChipToggle')
    chip.HorizontalContentAlignment = HorizontalAlignment.Left
    chip.Content = column.title or PARAM_NONE
    chip.ToolTip = 'Pick the parameter this column shows'

    popup = Popup()
    popup.AllowsTransparency = True
    popup.StaysOpen = False
    popup.Placement = PlacementMode.Bottom
    popup.PlacementTarget = chip

    shell = Border()
    shell.BorderThickness = Thickness(1.0)
    shell.CornerRadius = CornerRadius(4.0)
    shell.Padding = Thickness(8.0)
    shell.MinWidth = 260.0
    try:
        shell.SetResourceReference(Border.BackgroundProperty, 'PopupBg')
        shell.SetResourceReference(Border.BorderBrushProperty, 'ChromeEdge')
    except Exception:
        pass

    body = StackPanel()
    body.Orientation = Orientation.Vertical

    search = TextBox()
    _styled(search, 'SearchBox')
    search.Tag = 'search parameters'
    body.Children.Add(search)

    note = TextBlock()
    note.Margin = Thickness(2.0, 6.0, 2.0, 4.0)
    note.FontSize = 11.0
    try:
        note.SetResourceReference(TextBlock.ForegroundProperty, 'FgMuted')
    except Exception:
        pass
    body.Children.Add(note)

    names = ListBox()
    _styled(names, 'ThemedList')
    names.MaxHeight = 320.0
    body.Children.Add(names)

    shell.Child = body
    popup.Child = shell

    column.param_search = search
    column.param_list = names
    column.param_note = note
    column.param_popup = popup

    def fill(sender=None, args=None):
        needle = search.Text or ''
        offer = owner.param_offer(column)
        shown = [name for name in offer
                 if not needle or matches_search(name, needle)]
        names.Items.Clear()
        for name in [PARAM_REMOVE, PARAM_NONE] + shown:
            item = ListBoxItem()
            item.Content = name
            item.Tag = name
            names.Items.Add(item)
        if needle and not shown:
            # a search that matches nothing says so and leaves the full list,
            # rather than emptying the picker
            note.Text = ('Nothing matches "' + needle + '" - showing all ' +
                         str(len(offer)) + '.')
            for name in offer:
                item = ListBoxItem()
                item.Content = name
                item.Tag = name
                names.Items.Add(item)
        elif needle:
            note.Text = (str(len(shown)) + ' of ' + str(len(offer)) +
                         ' parameters')
        else:
            note.Text = (str(len(offer)) +
                         ' parameters on the categories shown')

    def picked(sender, args):
        item = names.SelectedItem
        if item is None:
            return
        chosen = str(item.Tag)
        names.SelectedItem = None
        popup.IsOpen = False
        chip.IsChecked = False
        owner.pick_param(column, chosen)

    def opened(sender, args):
        if chip.IsChecked:
            fill()
            popup.IsOpen = True
            try:
                search.Focus()
            except Exception:
                pass
        else:
            popup.IsOpen = False

    def closed(sender, args):
        chip.IsChecked = False

    search.TextChanged += fill
    names.SelectionChanged += picked
    chip.Click += opened
    popup.Closed += closed

    holder = Grid()
    holder.Children.Add(popup)
    top_shell = Grid()
    top_shell.Children.Add(chip)
    top_shell.Children.Add(holder)
    column.picker_chip = chip
    return top_shell


def _build_popup(column, owner):
    popup = Popup()
    popup.AllowsTransparency = True
    popup.StaysOpen = False
    popup.Placement = PlacementMode.Bottom

    shell = Border()
    shell.BorderThickness = Thickness(1.0)
    shell.CornerRadius = CornerRadius(4.0)
    shell.Padding = Thickness(8.0)
    shell.MinWidth = 220.0
    try:
        shell.SetResourceReference(Border.BackgroundProperty, 'PopupBg')
        shell.SetResourceReference(Border.BorderBrushProperty, 'ChromeEdge')
    except Exception:
        pass

    body = StackPanel()
    body.Orientation = Orientation.Vertical

    search = TextBox()
    _styled(search, 'MiniSearchBox')
    search.Tag = 'search these values'
    body.Children.Add(search)
    column.tick_search = search

    buttons = StackPanel()
    buttons.Orientation = Orientation.Horizontal
    buttons.Margin = Thickness(0.0, 6.0, 0.0, 6.0)
    all_button = Button()
    all_button.Content = 'All'
    _styled(all_button, 'BtnSmall')
    none_button = Button()
    none_button.Content = 'None'
    none_button.Margin = Thickness(6.0, 0.0, 0.0, 0.0)
    _styled(none_button, 'BtnSmall')
    buttons.Children.Add(all_button)
    buttons.Children.Add(none_button)
    body.Children.Add(buttons)

    ticks = ListBox()
    _styled(ticks, 'ThemedList')
    ticks.MaxHeight = 260.0
    body.Children.Add(ticks)
    column.list_box = ticks

    shell.Child = body
    popup.Child = shell

    def refresh(sender, args):
        owner.fill_tick_list(column)

    def tick_all(sender, args):
        owner.set_all_ticks(column, True)

    def tick_none(sender, args):
        owner.set_all_ticks(column, False)

    search.TextChanged += refresh
    all_button.Click += tick_all
    none_button.Click += tick_none
    return popup


def tick_item(text, count, checked, on_toggle):
    box = CheckBox()
    _styled(box, 'ThemedCheck')
    label = text if text else '(blank)'
    box.Content = label + '   ' + str(count)
    box.Tag = text
    box.IsChecked = checked
    box.Margin = Thickness(2.0, 2.0, 2.0, 2.0)
    box.Checked += on_toggle
    box.Unchecked += on_toggle
    return box
