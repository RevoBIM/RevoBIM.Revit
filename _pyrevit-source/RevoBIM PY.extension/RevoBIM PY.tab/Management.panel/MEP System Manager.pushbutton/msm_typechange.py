# -*- coding: utf-8 -*-
"""The Change Pipe Type window: every current type and size in the selection
on the left, grouped by size and coloured per size; on the right the new pipe
type and, per row, the size it goes to - picked from the sizes that type's
routing preferences offer. Apply returns the mapping; the window runs it."""
import msm_clr  # noqa: F401  - assemblies first

from System.Windows import Thickness, VerticalAlignment, GridLength, GridUnitType, \
    FontWeights, TextTrimming, CornerRadius
from System.Windows.Controls import Grid, ColumnDefinition, TextBlock, Border, ComboBox

import msm_core as core
import msm_theme as theme
import msm_ui as ui

# bar | current type | pipes | arrow | new type | from size | new size
# the two sizes sit side by side, which is what the mapping is read on
WIDTHS = ((10, False), (2.2, True), (64, False), (34, False), (2.2, True), (90, False),
          (150, False))


def res(element, prop, key):
    try:
        element.SetResourceReference(prop, key)
    except Exception:
        pass


class TypeChangeDialog(object):
    def __init__(self, owner, settings, rows, target_name, available, systems):
        self.settings = settings.copy()
        self.rows = rows
        self.target_name = target_name
        self.available = list(available or [])
        self.choices = {}
        for row in rows:
            self.choices[row[u"key"]] = core.default_target(row[u"size"], self.available)
        self.combos = {}
        self.answer = None
        self.window = ui.load_window(u"MsmTypeChange.xaml", settings.get(u"theme", u"auto"))
        w = self.window
        find = w.FindName
        self.find = find
        if owner is not None:
            try:
                w.Owner = owner
            except Exception:
                pass
        find(u"VersionText").Text = u"v{0}".format(core.__version__)
        ui.load_icon(find(u"Logo"))
        ui.Chrome(w, header=find(u"HeaderBar"), close_button=find(u"BtnClose"),
                  resizable=False)
        ui.attach_egg(w, find(u"LogoHost"),
                      lambda: theme.palette(theme.resolve(self.settings.get(u"theme"))))

        count = sum([r[u"count"] for r in rows])
        find(u"SelText").Text = u"{0} pipe{1} on {2} system{3} \u2192 {4}".format(
            count, u"" if count == 1 else u"s", len(systems), u"" if len(systems) == 1 else u"s",
            target_name)
        if self.available:
            find(u"StatusText").Text = u"Sizes {0} offers: {1}".format(
                target_name, u", ".join([core.format_size(s) for s in self.available]))
        else:
            find(u"StatusText").Text = (u"The sizes {0} offers could not be read from its routing "
                                        u"preferences - each pipe keeps its size.".format(target_name))
        for _key, label in core.SIZE_SORTS:
            find(u"CmbSort").Items.Add(label)
        find(u"CmbSort").SelectedIndex = 0
        find(u"CmbSort").SelectionChanged += ui.ui_safe(lambda a, b: self.fill(), u"Sort")
        find(u"BtnCancel").Click += lambda a, b: w.Close()
        find(u"BtnApply").Click += ui.ui_safe(lambda a, b: self.apply(), u"Apply")
        self.fill()

    def sort_key(self):
        index = self.find(u"CmbSort").SelectedIndex
        return core.SIZE_SORTS[index][0] if 0 <= index < len(core.SIZE_SORTS) else u"size"

    def fill(self):
        host = self.find(u"RowsHost")
        host.Children.Clear()
        self.combos = {}
        colours = core.size_colours(self.rows)
        for index, row in enumerate(core.sort_size_rows(self.rows, self.sort_key())):
            host.Children.Add(self.make_row(row, colours.get(row[u"size"], 0), index))

    def make_row(self, row, colour, index):
        grid = Grid()
        grid.Margin = Thickness(0, 0, 0, 0)
        grid.MinHeight = 34
        if index % 2:
            res(grid, Grid.BackgroundProperty, u"RowAlt")
        for width, star in WIDTHS:
            column = ColumnDefinition()
            column.Width = GridLength(width, GridUnitType.Star if star else GridUnitType.Pixel)
            grid.ColumnDefinitions.Add(column)
        key = u"Type{0}".format(colour)
        bar = Border()
        bar.Width = 4
        bar.Margin = Thickness(3, 5, 3, 5)
        bar.CornerRadius = CornerRadius(2)
        res(bar, Border.BackgroundProperty, key)
        grid.Children.Add(bar)
        cells = ((1, row[u"type"], u"Text", False),
                 (2, u"{0}".format(row[u"count"]), u"Muted", False),
                 (3, u"\u2192", u"Orange", True),
                 (4, self.target_name, u"Text", False),
                 (5, core.format_size(row[u"size"]), key, True))
        for column, text, brush, bold in cells:
            block = TextBlock()
            block.Text = text
            block.VerticalAlignment = VerticalAlignment.Center
            block.TextTrimming = TextTrimming.CharacterEllipsis
            block.Margin = Thickness(4, 0, 6, 0)
            if bold:
                block.FontWeight = FontWeights.SemiBold
            res(block, TextBlock.ForegroundProperty, brush)
            Grid.SetColumn(block, column)
            grid.Children.Add(block)
        combo = ComboBox()
        combo.Margin = Thickness(0, 3, 8, 3)
        sizes = self.available or [row[u"size"]]
        for size in sizes:
            combo.Items.Add(core.format_size(size))
        chosen = self.choices.get(row[u"key"])
        if chosen is None:
            chosen = row[u"size"]
        for i, size in enumerate(sizes):
            if abs(size - chosen) <= 0.5:
                combo.SelectedIndex = i
        combo.SelectionChanged += ui.ui_safe(
            lambda a, b, k=row[u"key"], c=combo, s=sizes: self.pick(k, c, s), u"Size")
        Grid.SetColumn(combo, 6)
        grid.Children.Add(combo)
        self.combos[row[u"key"]] = combo
        return grid

    def pick(self, key, combo, sizes):
        index = combo.SelectedIndex
        if 0 <= index < len(sizes):
            self.choices[key] = sizes[index]

    def apply(self):
        if not self.available:
            self.choices = dict((row[u"key"], None) for row in self.rows)
        self.answer = dict(self.choices)
        self.window.Close()

    def show(self):
        self.window.ShowDialog()
        return self.answer
