# -*- coding: utf-8 -*-
"""Number Sequencer - the Category > Family > Type tree with ticks.

One class used by both tabs. Unticked types are walked through but take no
number. Categories start open, families closed; each family gets its own
colour, shared by its types.
"""

import nsq_clr  # noqa: F401  (must stay the first import)

from System.Windows import Thickness, CornerRadius, FontWeights, GridLength, VerticalAlignment, Visibility
from System.Windows.Controls import StackPanel, Grid, Border, TextBlock, CheckBox, ColumnDefinition
from System.Windows.Shapes import Path, Shape
from System.Windows.Media import Geometry

import nsq_core as core
import nsq_ui as ui

ARROW_RIGHT = u"M0,0 L4,4 L0,8"
ARROW_DOWN = u"M0,0 L4,4 L8,0"


class FamilyTree(object):
    """host: StackPanel the rows go in. count_text: TextBlock for the total.
    search: TextBox whose words filter the rows. skipped: the set of type
    keys left out (shared with the caller, saved by it). on_changed() runs
    after any tick; on_select(element keys) on a double-click."""

    def __init__(self, host, count_text, search, guard, mode, skipped, on_changed, on_select):
        self.host = host
        self.count_text = count_text
        self.search = search
        self.guard = guard
        self.mode = mode
        self.skipped = skipped
        self.on_changed = on_changed
        self.on_select = on_select
        self.rows = []
        self.total = 0
        self.expanded = set()
        self.collapsed = set()
        self.colours = {}
        self.boxes = []

    # ---------------------------------------------------- data
    def set_rows(self, rows, total=None, reset=False):
        self.rows = list(rows)
        self.total = len(self.rows) if total is None else total
        if reset:
            self.expanded = set()
            self.collapsed = set()
            self.colours = {}

    def type_keys(self):
        return set([core.type_key(c, f, t) for k, c, f, t in self.rows])

    # ---------------------------------------------------- building
    def _colour_for(self, cat, fam):
        key = (cat, fam)
        if key not in self.colours:
            self.colours[key] = len(self.colours)
        return core.group_colour(self.colours[key], self.mode())

    def _is_open(self, expand_id):
        """Categories start open, families start closed."""
        if expand_id[0] == u"c":
            return expand_id not in self.collapsed
        return expand_id in self.expanded

    def build(self):
        host = self.host
        host.Children.Clear()
        self.boxes = []
        if not self.rows:
            self.count_text.Text = u""
            return
        query = self.search.Text or u""
        searching = bool(query.strip())
        tree = core.build_tree(self.rows)
        for cat in tree:
            # colours over the whole tree so a search never recolours
            for fam in cat[u"families"]:
                self._colour_for(cat[u"name"], fam[u"name"])
        for cat in tree:
            fam_blocks = []
            for fam in cat[u"families"]:
                types = [t for t in fam[u"types"] if core.matches(
                    u" ".join([cat[u"name"], fam[u"name"], t[u"name"]]), query)]
                if types:
                    fam_blocks.append((fam, types))
            if not fam_blocks:
                continue
            cat_keys = [t[u"key"] for f, ts in fam_blocks for t in ts]
            cat_id = (u"c", cat[u"name"])
            cat_count = sum([len(t[u"ids"]) for f, ts in fam_blocks for t in ts])
            outer, body = self._row(0, cat[u"name"], cat_count, None, cat_keys, cat_id,
                                    searching or self._is_open(cat_id),
                                    [i for f, ts in fam_blocks for t in ts for i in t[u"ids"]])
            host.Children.Add(outer)
            for fam, types in fam_blocks:
                colour = self._colour_for(cat[u"name"], fam[u"name"])
                fam_id = (u"f", cat[u"name"], fam[u"name"])
                fam_ids = [i for t in types for i in t[u"ids"]]
                f_outer, f_body = self._row(1, fam[u"name"], len(fam_ids), colour,
                                            [t[u"key"] for t in types], fam_id,
                                            searching or self._is_open(fam_id), fam_ids)
                body.Children.Add(f_outer)
                for t in types:
                    t_outer, t_body = self._row(2, t[u"name"], len(t[u"ids"]), colour, [t[u"key"]],
                                                None, False, t[u"ids"])
                    f_body.Children.Add(t_outer)
        self.count_text.Text = u"{0} elements".format(self.total)
        self.sync()

    def _row(self, level, text, count, colour, keys, expand_id, is_open, elem_keys):
        outer = StackPanel()
        head = Border()
        head.CornerRadius = CornerRadius(3)
        head.Margin = Thickness(0, 1, 0, 1)
        head.Padding = Thickness(4 + level * 18, 3, 8, 3)
        if colour is not None:
            head.Background = ui.brush(colour, 0x38 if level == 1 else 0x18)
        else:
            head.SetResourceReference(Border.BackgroundProperty, u"Card")
        grid = Grid()
        for w in (18, 22, 10):
            cd = ColumnDefinition()
            cd.Width = GridLength(w)
            grid.ColumnDefinitions.Add(cd)
        grid.ColumnDefinitions.Add(ColumnDefinition())
        auto = ColumnDefinition()
        auto.Width = GridLength.Auto
        grid.ColumnDefinitions.Add(auto)

        arrow = None
        if expand_id is not None:
            arrow = Path()
            arrow.Data = Geometry.Parse(ARROW_DOWN if is_open else ARROW_RIGHT)
            arrow.StrokeThickness = 1.6
            arrow.SetResourceReference(Shape.StrokeProperty, u"Muted")
            arrow.VerticalAlignment = getattr(VerticalAlignment, u"Center")
            arrow.Margin = Thickness(3, 0, 0, 0)
            Grid.SetColumn(arrow, 0)
            grid.Children.Add(arrow)

        cb = CheckBox()
        cb.IsThreeState = False
        Grid.SetColumn(cb, 1)
        grid.Children.Add(cb)

        if colour is not None:
            bar = Border()
            bar.Width = 4 if level == 1 else 3
            bar.Height = 14
            bar.CornerRadius = CornerRadius(1)
            bar.Background = ui.brush(colour)
            Grid.SetColumn(bar, 2)
            grid.Children.Add(bar)

        name = TextBlock()
        name.Text = text
        name.Margin = Thickness(4, 0, 6, 0)
        name.SetResourceReference(TextBlock.ForegroundProperty, u"Text")
        if level == 0:
            name.FontWeight = FontWeights.SemiBold
            name.FontSize = 13
        elif level == 1:
            name.FontWeight = FontWeights.SemiBold
        Grid.SetColumn(name, 3)
        grid.Children.Add(name)

        cnt = TextBlock()
        cnt.Text = u"{0}".format(count)
        cnt.SetResourceReference(TextBlock.ForegroundProperty, u"Muted")
        Grid.SetColumn(cnt, 4)
        grid.Children.Add(cnt)

        head.Child = grid
        outer.Children.Add(head)
        body = StackPanel()
        ui.show(body, is_open)
        outer.Children.Add(body)

        self.boxes.append((cb, list(keys)))
        cb.Click += self.guard(self._tick_handler(cb, list(keys)))
        head.MouseLeftButtonDown += self.guard(self._head_handler(expand_id, body, arrow, elem_keys))
        head.ToolTip = u"Click to expand or collapse, double-click to select in Revit" \
            if expand_id is not None else u"Double-click to select in Revit"
        return outer, body

    # ---------------------------------------------------- behaviour
    def _tick_handler(self, cb, keys):
        def handler(sender, e):
            # a mixed box ticks everything; otherwise follow the box. Compare
            # by value - a boxed .NET bool is not always the False object.
            before = core.group_state(keys, self.skipped)
            on = True if before is None else (cb.IsChecked == True)  # noqa: E712
            for k in keys:
                if on:
                    self.skipped.discard(k)
                else:
                    self.skipped.add(k)
            self.sync()
            self.on_changed()
        return handler

    def _head_handler(self, expand_id, body, arrow, elem_keys):
        def handler(sender, e):
            if e.ClickCount == 2:
                self.on_select(elem_keys)
                e.Handled = True
                return
            if expand_id is None:
                return
            opening = body.Visibility != getattr(Visibility, u"Visible")
            self._set_open(expand_id, opening, body, arrow)
            e.Handled = True
        return handler

    def _set_open(self, expand_id, opening, body, arrow):
        if opening:
            self.expanded.add(expand_id)
            self.collapsed.discard(expand_id)
        else:
            self.expanded.discard(expand_id)
            self.collapsed.add(expand_id)
        ui.show(body, opening)
        if arrow is not None:
            arrow.Data = Geometry.Parse(ARROW_DOWN if opening else ARROW_RIGHT)

    def sync(self):
        for cb, keys in self.boxes:
            cb.IsChecked = core.group_state(keys, self.skipped)

    def _all_ids(self):
        out = []
        for cat in core.build_tree(self.rows):
            out.append((u"c", cat[u"name"]))
            for fam in cat[u"families"]:
                out.append((u"f", cat[u"name"], fam[u"name"]))
        return out

    def expand_all(self):
        self.collapsed = set()
        self.expanded = set(self._all_ids())
        self.build()

    def collapse_all(self):
        self.expanded = set()
        self.collapsed = set(self._all_ids())
        self.build()

    def tick_all(self):
        for k in self.type_keys():
            self.skipped.discard(k)
        self.sync()
        self.on_changed()

    def untick_all(self):
        for k in self.type_keys():
            self.skipped.add(k)
        self.sync()
        self.on_changed()
