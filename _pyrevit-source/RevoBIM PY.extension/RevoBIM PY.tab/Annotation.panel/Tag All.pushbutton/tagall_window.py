# -*- coding: utf-8 -*-
"""The Tag All window - both tabs, the tree, the table and the run.

Everything visible is built as WPF elements in code and coloured through
SetResourceReference, so a palette swap on the open window reaches every
row. WPF is never asked to read a Python attribute.
"""
import os
import traceback

import tagall_clr  # noqa: F401  (assemblies first)
import tagall_core as core
import tagall_model as model
import tagall_ops as ops
import tagall_tidy as tidy
import tagall_ui as ui
import theme
from tagall_core import eid_value, to_text

TIDY_NOTE = (u"Once a view is tagged, its new tags are stacked into tidy columns with 45 degree "
             u"leaders, clear of other annotation. Same undo step.")

from System import TimeSpan, Double
from System.Windows import (Visibility, Thickness, HorizontalAlignment, VerticalAlignment,
                            GridLength, GridUnitType, FontWeights, TextTrimming, TextWrapping)
from System.Windows.Controls import (Grid, ColumnDefinition, StackPanel, TextBlock, CheckBox,
                                     Button, ComboBox, Border, Orientation, ScrollBarVisibility)
from System.Windows.Threading import DispatcherTimer

HERE = os.path.dirname(os.path.abspath(__file__))

# parked at module level so the persistent engine cannot collect them
WINDOW = None
DISPATCHER = None

TABLE_COLUMNS = ((u"Category", 1.0, 70), (u"Family", 1.3, 80), (u"Type", 1.2, 80),
                 (u"#", 0.0, 44), (u"Model", 0.8, 60), (u"Tag family : type", 2.0, 140), (u"", 0.0, 26))


def star(value):
    return GridLength(value, GridUnitType.Star)


def pixels(value):
    return GridLength(value, GridUnitType.Pixel)


def text_block(text, key="TextBrush", size=None, bold=False):
    block = TextBlock()
    block.Text = to_text(text)
    block.VerticalAlignment = VerticalAlignment.Center
    ui.set_brush(block, "Foreground", key)
    if size:
        block.FontSize = size
    if bold:
        block.FontWeight = FontWeights.SemiBold
    return block


def row_grid(columns):
    """A Grid with the shared column recipe, so header and rows line up."""
    grid = Grid()
    for _label, weight, minimum in columns:
        column = ColumnDefinition()
        column.Width = star(weight) if weight else pixels(minimum)
        column.MinWidth = minimum
        grid.ColumnDefinitions.Add(column)
    return grid


def place(grid, element, column):
    Grid.SetColumn(element, column)
    grid.Children.Add(element)


# ====================== views picker ======================

DEFAULT_TAG_WIDTH = 168      # the dropdown plus its margin, shared with the header


class Tree(object):
    """category -> family -> TypeNode, drawn as nested rows built in code.

    Tick state lives in three dicts keyed by name and node key, so a rebuild
    for a search or an expand keeps every tick. Children are built only when
    a category is open, so a project with thousands of types opens fast.

    Each category row carries a **Default tag** dropdown: the tag that
    category's rows start on when they go into the table. Only the tags that
    suit the category are offered, and a change is saved straight away.
    """

    def __init__(self, window, host, search, count_block, header=None):
        self.window = window
        self.owner = window
        self.host = host
        self.search = search
        self.count_block = count_block
        self.nodes = []
        self.data = {}          # category -> family -> [TypeNode]
        # categories and families start open, down to the types; these hold
        # the ones shut by hand
        self.collapsed_categories = set()
        self.collapsed_families = set()
        self.cat_ticks = {}
        self.fam_ticks = {}
        self.type_ticks = {}
        self.timer = DispatcherTimer()
        self.timer.Interval = TimeSpan.FromMilliseconds(220)
        self.timer.Tick += ui.ui_safe(window, self._tick, "tree search")
        search.TextChanged += ui.ui_safe(window, self._text_changed, "tree search")
        if header is not None:
            header.Child = self._header()

    def _header(self):
        """Lined up with the category rows: indent and tick, name, default
        tag, count."""
        grid = Grid()
        for width in (42, 0, DEFAULT_TAG_WIDTH, 46):
            column = ColumnDefinition()
            column.Width = star(1) if width == 0 else pixels(width)
            grid.ColumnDefinitions.Add(column)
        for index, text in ((1, u"Category / family / type"), (2, u"Default tag"), (3, u"#")):
            block = text_block(text, "MutedBrush", size=11.5, bold=True)
            block.Margin = Thickness(4 if index == 2 else 0, 0, 6, 0)
            if index == 3:
                block.HorizontalAlignment = HorizontalAlignment.Right
            place(grid, block, index)
        return grid

    def load(self, nodes):
        self.nodes = nodes
        data = {}
        for node in nodes:
            data.setdefault(node.category, {}).setdefault(node.family, []).append(node)
        for category in data:
            for family in data[category]:
                data[category][family].sort(key=lambda n: (n.source.is_link, core.natural_key(n.type_name)))
        self.data = data
        self.rebuild()

    def _text_changed(self, sender, args):
        self.timer.Stop()
        self.timer.Start()

    def _tick(self, sender, args):
        self.timer.Stop()
        self.rebuild()

    def expand_all(self, on):
        if on:
            self.collapsed_categories = set()
            self.collapsed_families = set()
        else:
            self.collapsed_categories = set(self.data.keys())
            self.collapsed_families = set([(category, family) for category in self.data
                                           for family in self.data[category]])
        self.rebuild()

    def clear_ticks(self):
        self.cat_ticks = {}
        self.fam_ticks = {}
        self.type_ticks = {}
        self.rebuild()

    # ---------- what is visible ----------

    def _family_matches(self, category, family, query):
        if not query:
            return True, None
        if core.matches_keywords(category, query) or core.matches_keywords(family, query):
            return True, None
        nodes = [n for n in self.data[category][family] if core.matches_keywords(n.display, query)]
        return bool(nodes), nodes

    def _visible_families(self, category, query):
        out = []
        for family in sorted(self.data[category].keys(), key=core.natural_key):
            shown, nodes = self._family_matches(category, family, query)
            if shown:
                out.append((family, nodes if nodes is not None else self.data[category][family]))
        return out

    def rebuild(self):
        query = self.search.Text
        self.host.Children.Clear()
        shown_cats = 0
        for category in sorted(self.data.keys(), key=core.natural_key):
            families = self._visible_families(category, query)
            if not families:
                continue
            shown_cats += 1
            open_it = core.family_open(category, self.collapsed_categories, query)
            count = sum([n.count for fam, nodes in families for n in nodes])
            panel = StackPanel()
            panel.Children.Add(self._row(0, open_it, self.cat_ticks.get(category, False), category, count,
                                         self._make_toggle(category, None), self._make_cat_tick(category),
                                         any_link=any([n.source.is_link for fam, nodes in families for n in nodes]),
                                         bold=True, extra=self._default_combo(category)))
            if open_it:
                for family, nodes in families:
                    fam_key = (category, family)
                    fam_open = core.family_open(fam_key, self.collapsed_families, query)
                    fam_count = sum([n.count for n in nodes])
                    panel.Children.Add(self._row(1, fam_open, self.fam_ticks.get(fam_key, False), family, fam_count,
                                                 self._make_toggle(category, family), self._make_fam_tick(fam_key),
                                                 any_link=any([n.source.is_link for n in nodes]),
                                                 extra=self._default_combo(category, family)))
                    if fam_open:
                        for node in nodes:
                            label = node.type_name
                            if node.source.is_link:
                                label = u"{0}   [{1}]".format(node.type_name, node.source.name)
                            panel.Children.Add(self._row(2, None, self.type_ticks.get(node.key, False), label, node.count,
                                                         None, self._make_type_tick(node.key), any_link=node.source.is_link))
            self.host.Children.Add(panel)
        total_types = len(self.nodes)
        links = len([n for n in self.nodes if n.source.is_link])
        if links:
            self.count_block.Text = u"{0} categories, {1} types ({2} from links)".format(len(self.data), total_types, links)
        else:
            self.count_block.Text = u"{0} categories, {1} types".format(len(self.data), total_types)
        if not self.data:
            self.host.Children.Add(text_block(u"Nothing taggable in the views ticked. Tick more views, or a linked model.", "MutedBrush"))

    def _row(self, depth, expanded, ticked, label, count, toggle_handler, tick_handler, any_link=False,
             bold=False, extra=None):
        """One line of the tree: indent, twisty, tick, label, default tag,
        count.

        The label column is the only star-sized one, so a long type name
        gives up its width to an ellipsis rather than pushing the count off
        the right hand edge. The default tag column is sized to its content,
        so family and type rows - which carry none - give it back to the
        label, while the count stays lined up down the whole tree.
        """
        grid = Grid()
        for width in (18 + depth * 16, 24, 0, -1, 46):
            column = ColumnDefinition()
            if width == 0:
                column.Width = star(1)
            elif width < 0:
                column.Width = GridLength.Auto
            else:
                column.Width = pixels(width)
                column.MinWidth = width
            grid.ColumnDefinitions.Add(column)
        grid.Margin = Thickness(0, 1, 0, 1)
        if toggle_handler is not None:
            toggle = Button()
            toggle.Content = u"\u25BE" if expanded else u"\u25B8"
            toggle.HorizontalAlignment = HorizontalAlignment.Right
            toggle.SetResourceReference(Button.StyleProperty, "TreeToggle")
            toggle.Click += toggle_handler
            place(grid, toggle, 0)
        box = CheckBox()
        box.IsChecked = bool(ticked)
        box.Margin = Thickness(6, 0, 0, 0)
        box.VerticalAlignment = VerticalAlignment.Center
        box.Checked += tick_handler
        box.Unchecked += tick_handler
        place(grid, box, 1)
        block = text_block(label, "LinkBrush" if any_link else "TextBrush", bold=bold)
        block.TextTrimming = TextTrimming.CharacterEllipsis
        block.ToolTip = to_text(label)
        place(grid, block, 2)
        if extra is not None:
            place(grid, extra, 3)
        count_block = text_block(u"{0}".format(count), "MutedBrush", size=11)
        count_block.HorizontalAlignment = HorizontalAlignment.Right
        count_block.Margin = Thickness(0, 0, 6, 0)
        place(grid, count_block, 4)
        return grid

    # ---------- the default tag per category ----------

    def _default_combo(self, category, family=None):
        """A Default tag dropdown: the category's on a category row, a
        family's own on a family row. Built with its saved value already
        selected and the handler attached after, so drawing the tree never
        reads as a change. A family following its category shows the
        category's tag in muted text; one set by hand shows it in full."""
        offered = [choice[0] for choice in model.tags_for_category(self.owner.tag_symbols, category)]
        combo = ComboBox()
        combo.Width = DEFAULT_TAG_WIDTH - 8
        combo.Margin = Thickness(4, 0, 4, 0)
        combo.MinHeight = 24 if family is None else 22
        combo.Padding = Thickness(6, 1, 6, 1)
        combo.FontSize = 11.5 if family is None else 11
        combo.VerticalAlignment = VerticalAlignment.Center
        if not offered:
            combo.Items.Add(u"(no tag loaded)")
            combo.SelectedIndex = 0
            combo.IsEnabled = False
            combo.ToolTip = u"No tag family is loaded for {0}".format(category)
            return combo
        combo.Items.Add(core.NONE_TAG)
        for name in offered:
            combo.Items.Add(name)
        settings = self.owner.settings
        if family is None:
            chosen = core.default_tag_for(core.remembered_tag(settings, category), offered)
            combo.ToolTip = self._default_tip(category, chosen)
            handler = self._make_default(category)
        else:
            chosen = core.default_tag_for(core.remembered_family_tag(settings, category, family), offered)
            follows = core.family_follows_category(settings, category, family)
            combo.SetResourceReference(ComboBox.ForegroundProperty, "MutedBrush" if follows else "TextBrush")
            combo.ToolTip = self._family_tip(category, family, chosen, follows)
            handler = self._make_family_default(category, family)
        combo.SelectedItem = chosen
        combo.SelectionChanged += handler
        return combo

    def _default_tip(self, category, chosen):
        if chosen == core.NONE_TAG:
            return u"{0} rows start on <None> in the table. Pick a tag to make it the default for every family.".format(category)
        return u"{0} rows start on {1} in the table. Each family can be given its own below.".format(category, chosen)

    def _family_tip(self, category, family, chosen, follows):
        if follows:
            return u"{0} follows {1}: its rows start on {2}. Pick a tag to give it its own.".format(
                family, category, chosen)
        return u"{0}'s own default: its rows start on {1}. Setting {2}'s default puts it back.".format(
            family, chosen, category)

    def _make_default(self, category):
        def handler(sender, args):
            chosen = to_text(sender.SelectedItem) or core.NONE_TAG
            core.remember_tag(self.owner.settings, category, chosen)
            self.owner.save()
            sender.ToolTip = self._default_tip(category, chosen)
            if chosen == core.NONE_TAG:
                self.owner.set_status(u"{0} has no default tag - its families start on <None>".format(category))
            else:
                self.owner.set_status(u"Every {0} family now starts on {1} - change any family below; "
                                      u"remembered for next time".format(category, chosen))
            # the family dropdowns follow; redrawn once this pick has finished
            ui.make_timer(1, self.rebuild)
        return ui.ui_safe(self.window, handler, "default tag")

    def _make_family_default(self, category, family):
        def handler(sender, args):
            chosen = to_text(sender.SelectedItem) or core.NONE_TAG
            settings = self.owner.settings
            core.remember_family_tag(settings, category, family, chosen)
            self.owner.save()
            follows = core.family_follows_category(settings, category, family)
            sender.SetResourceReference(ComboBox.ForegroundProperty, "MutedBrush" if follows else "TextBrush")
            sender.ToolTip = self._family_tip(category, family, chosen, follows)
            if follows:
                self.owner.set_status(u"{0} follows {1} again - its rows start on {2}".format(family, category, chosen))
            else:
                self.owner.set_status(u"{0} rows now start on {1} - remembered for next time".format(family, chosen))
        return ui.ui_safe(self.window, handler, "family default tag")

    # ---------- handlers ----------

    def _make_toggle(self, category, family):
        def handler(sender, args):
            if family is None:
                if category in self.collapsed_categories:
                    self.collapsed_categories.discard(category)
                else:
                    self.collapsed_categories.add(category)
            else:
                key = (category, family)
                if key in self.collapsed_families:
                    self.collapsed_families.discard(key)
                else:
                    self.collapsed_families.add(key)
            self.rebuild()
        return ui.ui_safe(self.window, handler, "tree toggle")

    def _make_cat_tick(self, category):
        def handler(sender, args):
            on = bool(sender.IsChecked)
            self.cat_ticks[category] = on
            for family in self.data.get(category, {}):
                self.fam_ticks[(category, family)] = on
                for node in self.data[category][family]:
                    self.type_ticks[node.key] = on
            self.rebuild()
        return ui.ui_safe(self.window, handler, "category tick")

    def _make_fam_tick(self, fam_key):
        def handler(sender, args):
            on = bool(sender.IsChecked)
            self.fam_ticks[fam_key] = on
            for node in self.data.get(fam_key[0], {}).get(fam_key[1], []):
                self.type_ticks[node.key] = on
            if not on:
                self.cat_ticks[fam_key[0]] = False
            self.rebuild()
        return ui.ui_safe(self.window, handler, "family tick")

    def _make_type_tick(self, node_key):
        def handler(sender, args):
            self.type_ticks[node_key] = bool(sender.IsChecked)
        return ui.ui_safe(self.window, handler, "type tick")

    def ticked_nodes(self):
        out = []
        for node in self.nodes:
            if self.type_ticks.get(node.key) or self.fam_ticks.get((node.category, node.family)) \
                    or self.cat_ticks.get(node.category):
                out.append(node)
        return out


# ====================== the table ======================

class TagRow(object):
    def __init__(self, node, choices, combo, border):
        self.node = node
        self.choices = choices      # [(display, type_id, is_multi)]
        self.combo = combo
        self.border = border

    @property
    def key(self):
        return self.node.key

    @property
    def names(self):
        return [choice[0] for choice in self.choices]

    @property
    def tag_display(self):
        try:
            value = to_text(self.combo.SelectedItem)
        except Exception:
            value = u""
        return u"" if value == core.NONE_TAG else value

    @property
    def tag_type_id(self):
        display = self.tag_display
        for name, type_id, _multi in self.choices:
            if name == display:
                return type_id
        return None


class TagTable(object):
    """The families to tag, one row per type, each starting at <None>.

    Rows highlight like every other list in the tool - click, Shift+click,
    Ctrl+click. Picking a tag on any highlighted row, or from the dropdown
    above the table, puts it on every highlighted row that can take it; a row
    whose category cannot is left alone and named in the status line.
    """

    def __init__(self, owner, host, header, count_block, tag_symbols, highlight_combo):
        self.owner = owner
        self.window = owner.window
        self.host = host
        self.count_block = count_block
        self.tag_symbols = tag_symbols
        self.highlight_combo = highlight_combo
        self.rows = []
        self.selected = set()
        self.anchor = None
        self.applying = False
        header.Child = self._header()
        highlight_combo.SelectionChanged += ui.ui_safe(owner, self._highlight_pick, "tag for highlighted")
        self._fill_highlight_combo()
        self._count()

    def _header(self):
        grid = row_grid(TABLE_COLUMNS)
        for index, (label, _w, _m) in enumerate(TABLE_COLUMNS):
            block = text_block(label, "MutedBrush", size=11.5, bold=True)
            block.Margin = Thickness(4, 0, 4, 0)
            place(grid, block, index)
        return grid

    def _choices_map(self):
        return dict([(row.key, row.names) for row in self.rows])

    def _order(self):
        return [row.key for row in self.rows]

    def has(self, node):
        return any([row.key == node.key for row in self.rows])

    def add(self, nodes):
        added = 0
        for node in nodes:
            if self.has(node):
                continue
            self._add_row(node)
            added += 1
        self._count()
        return added

    def _add_row(self, node):
        choices = model.tags_for_category(self.tag_symbols, node.category)
        grid = row_grid(TABLE_COLUMNS)
        place(grid, self._cell(node.category), 0)
        place(grid, self._cell(node.family), 1)
        place(grid, self._cell(node.type_name), 2)
        count = self._cell(u"{0}".format(node.count), "MutedBrush")
        count.HorizontalAlignment = HorizontalAlignment.Right
        place(grid, count, 3)
        place(grid, self._cell(node.source.name, "LinkBrush" if node.source.is_link else "MutedBrush"), 4)
        combo = ComboBox()
        combo.Margin = Thickness(2, 1, 2, 1)
        combo.MinHeight = 26
        combo.Padding = Thickness(6, 1, 6, 1)
        combo.Items.Add(core.NONE_TAG)
        for name, _id, _multi in choices:
            combo.Items.Add(name)
        # the category's default, set before the pick handler is attached, so
        # starting a row on it is not read as a pick by hand
        combo.SelectedItem = core.default_tag_for(
            core.remembered_family_tag(self.owner.settings, node.category, node.family),
            [name for name, _id, _multi in choices])
        if not choices:
            combo.ToolTip = u"No tag family is loaded for {0}".format(node.category)
        place(grid, combo, 5)
        remove = Button()
        remove.Content = u"✕"
        remove.SetResourceReference(Button.StyleProperty, "TreeToggle")
        remove.ToolTip = u"Remove this row"
        place(grid, remove, 6)
        border = Border()
        border.Padding = Thickness(4, 1, 4, 1)
        border.CornerRadius = ui.corner(3)
        border.Background = ui.transparent()
        border.Cursor = ui.hand_cursor()
        border.Child = grid
        row = TagRow(node, choices, combo, border)
        border.MouseLeftButtonDown += self._make_click(row)
        combo.SelectionChanged += self._make_pick(row)
        remove.Click += self._make_remove(row)
        self.rows.append(row)
        self.host.Children.Add(border)

    def _cell(self, text, key="TextBrush"):
        block = text_block(text, key)
        block.Margin = Thickness(4, 0, 4, 0)
        block.TextTrimming = TextTrimming.CharacterEllipsis
        block.ToolTip = to_text(text)
        return block

    # ---------- highlight ----------

    def _make_click(self, row):
        def handler(sender, args):
            self.selected, self.anchor = core.pick_rows(
                self.selected, self.anchor, row.key, self._order(),
                ui.control_held(), ui.shift_held())
            self._paint()
        return ui.ui_safe(self.window, handler, "highlight row")

    def _paint(self):
        for row in self.rows:
            if row.key in self.selected:
                ui.set_brush(row.border, "Background", "SelectBrush")
            else:
                row.border.Background = ui.transparent()
        self._fill_highlight_combo()
        self._count()

    def _fill_highlight_combo(self):
        combo = self.highlight_combo
        keys = [row.key for row in self.rows if row.key in self.selected]
        self.applying = True
        try:
            combo.Items.Clear()
            if not keys:
                combo.Items.Add(u"Highlight rows to set their tag together")
                combo.SelectedIndex = 0
                combo.IsEnabled = False
                return
            combo.Items.Add(u"Choose a tag for the {0} highlighted row{1}".format(
                len(keys), u"" if len(keys) == 1 else u"s"))
            combo.Items.Add(core.NONE_TAG)
            for tag in core.any_tag_choices(self._choices_map(), keys):
                combo.Items.Add(tag)
            combo.SelectedIndex = 0
            combo.IsEnabled = True
        finally:
            self.applying = False

    # ---------- setting tags ----------

    def _set_tags(self, applied, tag):
        self.applying = True
        try:
            for row in self.rows:
                if row.key in applied:
                    row.combo.SelectedItem = tag
        finally:
            self.applying = False

    def _report(self, applied, refused, tag):
        if not refused:
            if len(applied) > 1:
                self.owner.set_status(u"{0} set on {1} rows".format(tag, len(applied)))
            return
        names = sorted(set([row.node.category for row in self.rows if row.key in refused]))
        self.owner.set_status(u"{0} set on {1} row{2}; {3} {4} cannot take it ({5})".format(
            tag, len(applied), u"" if len(applied) == 1 else u"s", len(refused),
            u"row" if len(refused) == 1 else u"rows", u", ".join(names)), True)

    def _make_pick(self, row):
        def handler(sender, args):
            if self.applying:
                return
            tag = to_text(row.combo.SelectedItem) or core.NONE_TAG
            applied, refused = core.apply_tag_to_rows(self._choices_map(), self.selected, row.key, tag)
            self._set_tags(applied, tag)
            self._report(applied, refused, tag)
            self.owner._update_button()
        return ui.ui_safe(self.window, handler, "tag pick")

    def _highlight_pick(self, sender, args):
        if self.applying or self.highlight_combo.SelectedIndex < 1:
            return
        tag = to_text(self.highlight_combo.SelectedItem)
        applied, refused = core.apply_tag_to_rows(self._choices_map(), self.selected, None, tag)
        self._set_tags(applied, tag)
        self._report(applied, refused, tag)
        self._fill_highlight_combo()
        self.owner._update_button()

    # ---------- removing ----------

    def _make_remove(self, row):
        def handler(sender, args):
            self._remove([row.key])
        return ui.ui_safe(self.window, handler, "remove row")

    def remove_highlighted(self):
        if not self.selected:
            self.owner.set_status(u"Highlight the rows to remove first")
            return
        self._remove(list(self.selected))

    def _remove(self, keys):
        keys = set(keys)
        for row in [row for row in self.rows if row.key in keys]:
            self.rows.remove(row)
            self.host.Children.Remove(row.border)
        self.selected.difference_update(keys)
        if self.anchor in keys:
            self.anchor = None
        self._paint()
        self.owner._update_button()

    def clear(self):
        self.rows = []
        self.selected = set()
        self.anchor = None
        self.host.Children.Clear()
        self._paint()

    def _count(self):
        if not self.rows:
            self.count_block.Text = u"tick families in Categories and add them"
            return
        unset = len([row for row in self.rows if not row.tag_display])
        text = u"{0} row{1}".format(len(self.rows), u"" if len(self.rows) == 1 else u"s")
        links = len([row for row in self.rows if row.node.source.is_link])
        if links:
            text += u", {0} from links".format(links)
        if unset:
            text += u", {0} without a tag".format(unset)
        if self.selected:
            text += u", {0} highlighted".format(len(self.selected))
        self.count_block.Text = text

    # ---------- what the run asks for ----------

    def specs(self):
        return [(row.node, row.tag_type_id, row.tag_display) for row in self.rows if row.tag_display]

    def unset_count(self):
        return len([row for row in self.rows if not row.tag_display])


# ====================== the column value popup ======================

def open_value_popup(table, column, caret):
    """Excel's value list for one column, shared by the view and sheet tables.

    `table` carries owner, popup, keywords, ticks, base_rows() and
    rebuild(). Everything ticked is no filter; unticking narrows; nothing
    ticked shows nothing. The list leaves the column's own filter out, so a
    value it is hiding can be ticked back on.
    """
    from System.Windows.Controls import TextBox, ScrollViewer, WrapPanel
    owner = table.owner
    choices = core.column_choices(table.base_rows(), column, table.keywords, table.ticks)
    listed = [value for value, _count in choices]
    allowed = table.ticks.get(column)

    frame = Border()
    frame.SetResourceReference(Border.StyleProperty, "Card")
    frame.MinWidth = 240
    frame.MaxWidth = 380
    panel = StackPanel()
    search = TextBox()
    search.Tag = u"Search values"
    search.Margin = Thickness(0, 0, 0, 6)
    panel.Children.Add(search)
    tools = WrapPanel()
    tools.Margin = Thickness(0, 0, 0, 6)
    everything = ui.icon_button("tick", u"All")
    nothing = ui.icon_button("cross", u"None")
    for button in (everything, nothing):
        button.Padding = Thickness(7, 1, 7, 1)
        button.MinHeight = 22
        button.FontSize = 11
        button.Margin = Thickness(0, 0, 4, 0)
        tools.Children.Add(button)
    panel.Children.Add(tools)
    scroll = ScrollViewer()
    scroll.MaxHeight = 300
    scroll.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
    values = StackPanel()
    scroll.Content = values
    panel.Children.Add(scroll)
    frame.Child = panel

    boxes = []

    def _make_value_tick(value):
        def handler(sender, args):
            table.ticks[column] = core.tick_filter_after(
                table.ticks.get(column), listed, value, bool(sender.IsChecked))
            table.rebuild()
        return ui.ui_safe(owner, handler, "tick value")

    for value, count in choices:
        box = CheckBox()
        box.Content = u"{0}   ({1})".format(value or core.BLANK_LABEL, count)
        box.Margin = Thickness(0, 2, 0, 2)
        box.IsChecked = allowed is None or value in allowed
        box.Click += _make_value_tick(value)
        boxes.append((box, value))
        values.Children.Add(box)
    if not choices:
        values.Children.Add(text_block(u"Nothing left to filter here.", "MutedBrush"))

    def searched(sender, args):
        query = to_text(search.Text)
        for box, value in boxes:
            shown = core.matches_keywords(value or core.BLANK_LABEL, query)
            box.Visibility = Visibility.Visible if shown else Visibility.Collapsed

    def tick_everything(sender, args):
        table.ticks[column] = None
        for box, _value in boxes:
            box.IsChecked = True
        table.rebuild()

    def tick_nothing(sender, args):
        table.ticks[column] = set()
        for box, _value in boxes:
            box.IsChecked = False
        table.rebuild()

    search.TextChanged += ui.ui_safe(owner, searched, "search values")
    everything.Click += ui.ui_safe(owner, tick_everything, "all values")
    nothing.Click += ui.ui_safe(owner, tick_nothing, "no values")
    table.popup.Child = frame
    table.popup.PlacementTarget = caret
    table.popup.IsOpen = True
    search.Focus()


# ====================== the sheet table ======================

SHEET_HEADINGS = {"number": u"Number", "name": u"Sheet name", "g1": u"View group",
                  "g2": u"View group 2", "views": u"Views"}
SHEET_WIDTHS = (("twisty", 0, 20), ("tick", 0, 24), ("number", 0.8, 56), ("name", 2.0, 110),
                ("g1", 1.0, 60), ("g2", 1.0, 60), ("views", 0, 50))
# the columns a reader can resize, their starting widths and their floors -
# a floor is not cosmetic: a heading carries a sort badge, a caret and a
# filter box, and a narrower column clips its own controls
SHEET_DATA = ("number", "name", "g1", "g2", "views")
SHEET_DEFAULT_WIDTHS = (70.0, 175.0, 88.0, 88.0, 52.0)
SHEET_MIN_WIDTHS = (56.0, 90.0, 60.0, 60.0, 44.0)


class SheetTable(object):
    """Every sheet, ticked to tag in the views placed on it.

    Columns: Number, Sheet name, two group columns whose sheet parameters
    are picked from dropdowns, and how many views on the sheet this tab can
    tag. Each heading carries a keyword box and the shared Excel-style value
    list; clicking a heading's name sorts by it, clicking again flips it,
    and Shift+click adds a level beneath (core.next_sort_stack).

    Every sheet expands to show the views placed on it - collapsed until
    asked - with the ones this tab cannot tag greyed. Ticks are per sheet:
    a ticked sheet means every taggable view on it. Highlight and tick work
    as everywhere else in the tool.
    """

    def __init__(self, owner, host, title, key, on_change):
        self.owner = owner
        self.window = owner.window
        self.key = key
        self.on_change = on_change
        self.records = []
        self.by_key = {}
        self.ticked = set()
        self.selected = set()
        self.anchor = None
        self.keywords = {}
        self.ticks = {}
        self.sort = [("number", False)]
        self.expanded = set()
        self.group_1 = u""
        self.group_2 = u""
        self.names = []
        self.order = []
        self.row_ui = {}
        self.loading = False
        self.timer = DispatcherTimer()
        self.timer.Interval = TimeSpan.FromMilliseconds(220)
        self.timer.Tick += ui.ui_safe(owner, self._filter_settled, "sheet filter")
        self.weights = list(SHEET_DEFAULT_WIDTHS)
        self.row_grids = []
        self._build(host, title)

    # ---------- construction ----------

    def _build(self, host, title):
        from System.Windows.Controls import RowDefinition, WrapPanel, ScrollViewer
        from System.Windows.Controls.Primitives import Popup, PlacementMode
        root = Grid()
        for height in ("auto", "auto", "auto", "star", "auto"):
            row = RowDefinition()
            row.Height = GridLength.Auto if height == "auto" else star(1)
            root.RowDefinitions.Add(row)

        head = StackPanel()
        head.Orientation = Orientation.Horizontal
        head.Margin = Thickness(0, 0, 0, 8)
        tick = Border()
        tick.SetResourceReference(Border.StyleProperty, "OrangeTick")
        head.Children.Add(tick)
        heading = text_block(title)
        heading.SetResourceReference(TextBlock.StyleProperty, "Heading")
        head.Children.Add(heading)
        self.count_block = text_block(u"", "MutedBrush", size=11.5)
        self.count_block.Margin = Thickness(8, 0, 0, 0)
        head.Children.Add(self.count_block)
        Grid.SetRow(head, 0)
        root.Children.Add(head)

        columns = Grid()
        for width in ("auto", "star", "auto", "star"):
            column = ColumnDefinition()
            column.Width = GridLength.Auto if width == "auto" else star(1)
            columns.ColumnDefinitions.Add(column)
        label = text_block(u"View group", "MutedBrush")
        label.Margin = Thickness(0, 0, 8, 0)
        place(columns, label, 0)
        self.group_1_combo = ComboBox()
        self.group_1_combo.ToolTip = u"The sheet parameter the View group column reads"
        place(columns, self.group_1_combo, 1)
        label = text_block(u"View group 2", "MutedBrush")
        label.Margin = Thickness(10, 0, 8, 0)
        place(columns, label, 2)
        self.group_2_combo = ComboBox()
        self.group_2_combo.ToolTip = u"The sheet parameter the View group 2 column reads"
        place(columns, self.group_2_combo, 3)
        self.group_1_combo.SelectionChanged += ui.ui_safe(self.owner, self._group_changed, "sheet group")
        self.group_2_combo.SelectionChanged += ui.ui_safe(self.owner, self._group_changed, "sheet group 2")
        columns.Margin = Thickness(0, 0, 0, 8)
        Grid.SetRow(columns, 1)
        root.Children.Add(columns)

        tools = WrapPanel()
        tools.Margin = Thickness(0, 0, 0, 6)
        for icon, text, handler, tip in (
                ("expand", u"Expand all", self._expand_all, u"Show the views on every sheet listed"),
                ("collapse", u"Collapse all", self._collapse_all, None),
                ("tick", u"Tick all", self._tick_all, u"Tick every sheet the filters leave showing"),
                ("box", u"Untick all", self._untick_all, u"Untick every sheet the filters leave showing"),
                ("cross", u"Clear filters", self._clear_filters, None)):
            button = ui.icon_button(icon, text, tooltip=tip)
            button.Padding = Thickness(7, 1, 7, 1)
            button.MinHeight = 22
            button.FontSize = 11
            button.Margin = Thickness(0, 0, 4, 4)
            button.Click += ui.ui_safe(self.owner, handler, text.lower())
            tools.Children.Add(button)
        Grid.SetRow(tools, 2)
        root.Children.Add(tools)

        frame = Border()
        frame.SetResourceReference(Border.StyleProperty, "Field")
        Grid.SetRow(frame, 3)
        root.Children.Add(frame)
        inner = Grid()
        for height in ("auto", "star"):
            row = RowDefinition()
            row.Height = GridLength.Auto if height == "auto" else star(1)
            inner.RowDefinitions.Add(row)
        frame.Child = inner
        self.header = Border()
        self.header.SetResourceReference(Border.BackgroundProperty, "HeaderRowBrush")
        self.header.SetResourceReference(Border.BorderBrushProperty, "EdgeBrush")
        self.header.BorderThickness = Thickness(0, 0, 0, 1)
        self.header.Padding = Thickness(4, 4, 14, 5)
        inner.Children.Add(self.header)
        scroll = ScrollViewer()
        scroll.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
        scroll.HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled
        self.list_host = StackPanel()
        self.list_host.Margin = Thickness(2)
        scroll.Content = self.list_host
        Grid.SetRow(scroll, 1)
        inner.Children.Add(scroll)

        hint = text_block(u"Tick a sheet to tag in every view on it. Click a heading to sort, "
                          u"Shift+click to add a level. Click to highlight, Shift+click for a run, "
                          u"then tick one to tick them all.", "MutedBrush", size=11)
        hint.TextWrapping = TextWrapping.Wrap
        hint.Margin = Thickness(0, 6, 0, 0)
        Grid.SetRow(hint, 4)
        root.Children.Add(hint)

        self.popup = Popup()
        self.popup.StaysOpen = False
        self.popup.AllowsTransparency = True
        self.popup.Placement = PlacementMode.Bottom
        root.Children.Add(self.popup)

        self.keyword_boxes = {}
        self.carets = {}
        self.header_labels = {}
        self.badges = {}
        self._build_header()
        host.Child = root

    def _row_grid(self):
        """Header and rows share one recipe, read from the current widths,
        so a drag on a heading moves every row with it."""
        grid = Grid()
        for column, _weight, minimum in SHEET_WIDTHS:
            definition = ColumnDefinition()
            if column in SHEET_DATA:
                index = SHEET_DATA.index(column)
                definition.Width = star(self.weights[index])
                definition.MinWidth = SHEET_MIN_WIDTHS[index]
            else:
                definition.Width = pixels(minimum)
            grid.ColumnDefinitions.Add(definition)
        return grid

    def _apply_widths(self):
        offset = len(SHEET_WIDTHS) - len(SHEET_DATA)
        for grid in [self.header_grid] + self.row_grids:
            for index, weight in enumerate(self.weights):
                grid.ColumnDefinitions[offset + index].Width = star(weight)

    def _current_widths(self):
        """The widths as laid out, read off the header. Until the first
        layout pass they are all 0, so the stored weights stand in."""
        offset = len(SHEET_WIDTHS) - len(SHEET_DATA)
        actual = [self.header_grid.ColumnDefinitions[offset + index].ActualWidth
                  for index in range(len(SHEET_DATA))]
        if not all(actual):
            return list(self.weights)
        return actual

    def _make_resize(self, index):
        def handler(sender, args):
            self.weights = core.resize_columns(self._current_widths(), index,
                                               args.HorizontalChange, SHEET_MIN_WIDTHS)
            self._apply_widths()
        return ui.ui_safe(self.owner, handler, "resize column")

    def _resize_done(self, sender, args):
        self.owner.save()

    def _reset_widths(self, sender, args):
        self.weights = list(SHEET_DEFAULT_WIDTHS)
        self._apply_widths()
        self.owner.save()

    def _grip(self, index):
        """The drag handle on a heading's right edge, over a hairline that
        shows where the edge is."""
        from System.Windows.Controls.Primitives import Thumb
        line = Border()
        line.Width = 1
        line.HorizontalAlignment = HorizontalAlignment.Right
        line.Margin = Thickness(0, 2, 0, 2)
        line.IsHitTestVisible = False
        line.SetResourceReference(Border.BackgroundProperty, "EdgeBrush")
        grip = Thumb()
        grip.SetResourceReference(Thumb.StyleProperty, "Grip")
        grip.Width = 8
        grip.HorizontalAlignment = HorizontalAlignment.Right
        grip.Margin = Thickness(0, 0, -4, 0)
        grip.Cursor = ui.resize_cursor()
        grip.ToolTip = u"Drag to resize. Double-click to put every column back."
        grip.DragDelta += self._make_resize(index)
        grip.DragCompleted += ui.ui_safe(self.owner, self._resize_done, "resize column")
        grip.MouseDoubleClick += ui.ui_safe(self.owner, self._reset_widths, "reset columns")
        return line, grip

    def _build_header(self):
        from System.Windows.Controls import TextBox
        grid = self._row_grid()
        for index, (column, _weight, _minimum) in enumerate(SHEET_WIDTHS):
            if column in ("twisty", "tick"):
                continue
            cell = StackPanel()
            cell.Margin = Thickness(3, 0, 3, 0)
            line = Grid()
            for width in ("star", "auto", "auto"):
                definition = ColumnDefinition()
                definition.Width = star(1) if width == "star" else GridLength.Auto
                line.ColumnDefinitions.Add(definition)
            sorter = Border()
            sorter.Background = ui.transparent()
            sorter.Cursor = ui.hand_cursor()
            sorter.ToolTip = u"Sort by this column. Click again to flip it, Shift+click to add a level."
            label = text_block(SHEET_HEADINGS[column], "MutedBrush", size=11.5, bold=True)
            label.TextTrimming = TextTrimming.CharacterEllipsis
            sorter.Child = label
            sorter.MouseLeftButtonDown += self._make_sort(column)
            place(line, sorter, 0)
            badge = text_block(u"", "OrangeBrush", size=11, bold=True)
            badge.Margin = Thickness(3, 0, 2, 0)
            place(line, badge, 1)
            caret = Button()
            caret.SetResourceReference(Button.StyleProperty, "TreeToggle")
            caret.Content = u"▾"
            caret.ToolTip = u"Tick which values to show"
            caret.Click += self._make_caret(column)
            place(line, caret, 2)
            cell.Children.Add(line)
            box = TextBox()
            box.Tag = u"Filter"
            box.MinHeight = 24
            box.Padding = Thickness(4, 0, 4, 0)
            box.FontSize = 11.5
            box.Margin = Thickness(0, 3, 0, 0)
            box.TextChanged += self._make_keyword(column)
            cell.Children.Add(box)
            self.keyword_boxes[column] = box
            self.carets[column] = caret
            self.header_labels[column] = label
            self.badges[column] = badge
            place(grid, cell, index)
            # every heading but the last has an edge to drag
            data_index = SHEET_DATA.index(column)
            if data_index < len(SHEET_DATA) - 1:
                line, grip = self._grip(data_index)
                place(grid, line, index)
                place(grid, grip, index)
        self.header_grid = grid
        self.header.Child = grid

    # ---------- loading ----------

    def load(self, records, names, group_1, group_2, ticked=None, widths=None):
        self.weights = core.parse_widths(widths or u"", SHEET_DEFAULT_WIDTHS, SHEET_MIN_WIDTHS)
        self._apply_widths()
        self.loading = True
        try:
            self.records = list(records)
            self.by_key = dict([(record.key, record) for record in self.records])
            self.names = list(names)
            if ticked is not None:
                self.ticked = set([key for key in ticked if key in self.by_key])
            self.expanded = set()
            for combo, chosen in ((self.group_1_combo, group_1), (self.group_2_combo, group_2)):
                combo.Items.Clear()
                combo.Items.Add(core.NONE_TAG)
                for name in self.names:
                    combo.Items.Add(name)
                combo.SelectedItem = chosen if chosen in self.names else core.NONE_TAG
            self.group_1 = self._combo_value(self.group_1_combo)
            self.group_2 = self._combo_value(self.group_2_combo)
        finally:
            self.loading = False
        self._relabel()
        self.rebuild()

    def _combo_value(self, combo):
        value = to_text(combo.SelectedItem)
        return u"" if value == core.NONE_TAG else value

    def _relabel(self):
        self.header_labels["g1"].Text = self.group_1 or SHEET_HEADINGS["g1"]
        self.header_labels["g2"].Text = self.group_2 or SHEET_HEADINGS["g2"]

    # ---------- the rows the table is showing ----------

    def base_rows(self):
        return [(record.key, record.cells(self.group_1, self.group_2)) for record in self.records]

    def shown_rows(self):
        return core.sort_rows(core.filter_rows(self.base_rows(), self.keywords, self.ticks), self.sort)

    def rebuild(self):
        rows = self.shown_rows()
        self.order = [row[0] for row in rows]
        self.list_host.Children.Clear()
        self.row_ui = {}
        self.row_grids = []
        for key, cells in rows:
            self.list_host.Children.Add(self._row(key, cells))
            if key in self.expanded:
                for child in self._children(self.by_key[key]):
                    self.list_host.Children.Add(child)
        if not self.records:
            self.list_host.Children.Add(text_block(u"No sheets in this model.", "MutedBrush"))
        elif not rows:
            self.list_host.Children.Add(text_block(u"No sheets match the filters.", "MutedBrush"))
        self._paint()
        self._paint_header()
        self._count()

    def _row(self, key, cells):
        border = Border()
        border.Padding = Thickness(2, 2, 2, 2)
        border.CornerRadius = ui.corner(3)
        border.Background = ui.transparent()
        border.Cursor = ui.hand_cursor()
        grid = self._row_grid()
        self.row_grids.append(grid)
        record = self.by_key[key]
        if record.placed:
            toggle = Button()
            toggle.SetResourceReference(Button.StyleProperty, "TreeToggle")
            toggle.Content = u"▾" if key in self.expanded else u"▸"
            toggle.ToolTip = u"Show the views on this sheet"
            toggle.Click += self._make_fold(key)
            place(grid, toggle, 0)
        box = CheckBox()
        box.Margin = Thickness(2, 0, 0, 0)
        box.VerticalAlignment = VerticalAlignment.Center
        box.Focusable = False
        box.Click += self._make_tick(key)
        place(grid, box, 1)
        for index, column in enumerate(("number", "name", "g1", "g2", "views")):
            value = cells.get(column, u"")
            if column == "number":
                tone = "BlueBrush"
            elif column == "name":
                tone = "TextBrush"
            elif column == "views" and value == u"0":
                tone = "DisabledBrush"
            else:
                tone = "MutedBrush"
            block = text_block(value, tone, bold=(column == "number"))
            block.TextTrimming = TextTrimming.CharacterEllipsis
            block.Margin = Thickness(4, 0, 4, 0)
            block.ToolTip = value or None
            if column == "views":
                block.HorizontalAlignment = HorizontalAlignment.Right
                block.ToolTip = u"Views on this sheet this tab can tag"
            place(grid, block, index + 2)
        border.Child = grid
        border.MouseLeftButtonDown += self._make_click(key)
        self.row_ui[key] = (border, box)
        return border

    def _children(self, record):
        """The views placed on a sheet, under it. Read-only: the tick is the
        sheet's. A view this tab cannot tag is greyed and says why."""
        out = []
        for _value, name, family_type, taggable in record.placed:
            line = Grid()
            for width in (50, 0, 0):
                definition = ColumnDefinition()
                definition.Width = pixels(width) if width else star(1)
                line.ColumnDefinitions.Add(definition)
            mark = text_block(u"└", "EdgeBrush")
            mark.HorizontalAlignment = HorizontalAlignment.Right
            mark.Margin = Thickness(0, 0, 6, 0)
            place(line, mark, 0)
            label = text_block(name, "TextBrush" if taggable else "DisabledBrush", size=11.5)
            label.TextTrimming = TextTrimming.CharacterEllipsis
            label.ToolTip = name
            place(line, label, 1)
            kind = text_block(family_type if taggable else u"{0} - cannot tag here".format(family_type),
                              "MutedBrush" if taggable else "DisabledBrush", size=11)
            kind.TextTrimming = TextTrimming.CharacterEllipsis
            kind.Margin = Thickness(8, 0, 4, 0)
            place(line, kind, 2)
            line.Margin = Thickness(0, 1, 0, 1)
            out.append(line)
        return out

    def _paint(self):
        for key, pair in self.row_ui.items():
            border, box = pair
            box.IsChecked = key in self.ticked
            if key in self.selected:
                ui.set_brush(border, "Background", "SelectBrush")
            else:
                border.Background = ui.transparent()

    def _paint_header(self):
        for column, caret in self.carets.items():
            filtered = core.is_filtered(column, self.keywords, self.ticks)
            caret.Content = u"▼" if filtered else u"▾"
            ui.set_brush(caret, "Foreground", "OrangeBrush" if filtered else "MutedBrush")
        for column, badge in self.badges.items():
            badge.Text = core.sort_badge(self.sort, column)
            sorted_here = bool(badge.Text)
            ui.set_brush(self.header_labels[column], "Foreground", "OrangeBrush" if sorted_here else "MutedBrush")

    def _count(self):
        shown = len(self.order)
        total = len(self.records)
        text = u"{0} sheets".format(total) if shown == total else u"{0} of {1} sheets".format(shown, total)
        ticked = self.ticked_records()
        if ticked:
            views = len(self.view_keys())
            text = u"{0}, {1} ticked - {2} view{3} to tag".format(
                text, len(ticked), views, u"" if views == 1 else u"s")
        self.count_block.Text = text

    # ---------- gestures ----------

    def _make_click(self, key):
        def handler(sender, args):
            self.selected, self.anchor = core.pick_rows(
                self.selected, self.anchor, key, self.order,
                ui.control_held(), ui.shift_held())
            self._paint()
        return ui.ui_safe(self.owner, handler, "highlight sheet")

    def _make_tick(self, key):
        def handler(sender, args):
            self.ticked = core.apply_tick(self.ticked, self.selected, key, bool(sender.IsChecked))
            self._paint()
            self._count()
            self._changed()
        return ui.ui_safe(self.owner, handler, "tick sheet")

    def _make_fold(self, key):
        def handler(sender, args):
            if key in self.expanded:
                self.expanded.discard(key)
            else:
                self.expanded.add(key)
            self.rebuild()
        return ui.ui_safe(self.owner, handler, "show views on sheet")

    def _make_sort(self, column):
        def handler(sender, args):
            self.sort = core.next_sort_stack(self.sort, column, ui.shift_held())
            self.rebuild()
        return ui.ui_safe(self.owner, handler, "sort sheets")

    def _make_caret(self, column):
        def handler(sender, args):
            open_value_popup(self, column, sender)
        return ui.ui_safe(self.owner, handler, "column values")

    def _make_keyword(self, column):
        def handler(sender, args):
            if self.loading:
                return
            self.keywords[column] = to_text(sender.Text).strip()
            self.timer.Stop()
            self.timer.Start()
        return ui.ui_safe(self.owner, handler, "sheet filter")

    def _filter_settled(self, sender, args):
        self.timer.Stop()
        self.rebuild()

    def _expand_all(self, sender, args):
        self.expanded = set([key for key in self.order if self.by_key[key].placed])
        self.rebuild()

    def _collapse_all(self, sender, args):
        self.expanded = set()
        self.rebuild()

    def _tick_all(self, sender, args):
        self.ticked.update(self.order)
        self._paint()
        self._count()
        self._changed()

    def _untick_all(self, sender, args):
        self.ticked.difference_update(self.order)
        self._paint()
        self._count()
        self._changed()

    def _clear_filters(self, sender, args):
        self.keywords = {}
        self.ticks = {}
        self.loading = True
        try:
            for box in self.keyword_boxes.values():
                box.Text = u""
        finally:
            self.loading = False
        self.rebuild()

    def _group_changed(self, sender, args):
        if self.loading:
            return
        self.group_1 = self._combo_value(self.group_1_combo)
        self.group_2 = self._combo_value(self.group_2_combo)
        # the group columns now read different parameters, so their filters
        # and any sort on them mean nothing any more
        for column in ("g1", "g2"):
            self.ticks.pop(column, None)
            self.keywords.pop(column, None)
        self.sort = [level for level in self.sort if level[0] not in ("g1", "g2")] or [("number", False)]
        self.loading = True
        try:
            for column in ("g1", "g2"):
                self.keyword_boxes[column].Text = u""
        finally:
            self.loading = False
        self._relabel()
        self.rebuild()
        self.owner.save()

    def _changed(self):
        if self.on_change:
            self.on_change()

    # ---------- what a run asks for ----------

    def use_active(self):
        return False

    def ticked_records(self):
        return [record for record in self.records if record.key in self.ticked]

    def count(self):
        return len(self.ticked_records())

    def view_keys(self):
        """The taggable views on the ticked sheets, each once, in sheet
        order (core.views_from_sheets)."""
        pairs = [(record.key, record.view_ids) for record in self.records]
        keys, _empty = core.views_from_sheets(pairs, self.ticked)
        return keys

    def empty_ticked(self):
        pairs = [(record.key, record.view_ids) for record in self.records]
        _keys, empty = core.views_from_sheets(pairs, self.ticked)
        return [self.by_key[key] for key in empty if key in self.by_key]


# ====================== the view table ======================

VIEW_HEADINGS = {"name": u"View name", "type": u"Family and type",
                 "g1": u"View group", "g2": u"View group 2"}
VIEW_WIDTHS = (("tick", 0, 28), ("name", 2.0, 120), ("type", 1.4, 90),
               ("g1", 1.0, 70), ("g2", 1.0, 70))


class ViewTable(object):
    """The view list both tabs use, built in code so it is the same control
    in both places.

    Four columns - View name, Family and type, and two View group columns
    whose parameters are chosen from dropdowns of the views' own parameters.
    Each heading carries a keyword box and a tick-list caret, Excel-style; a
    column's own filter is left out of its own list, and a filtered caret
    turns orange, because a filter you cannot see is a filter you forget.
    Rows group under both View group columns with collapsible headings.

    Highlight and tick are separate, as everywhere else in the tool: click,
    Shift+click and Ctrl+click highlight, and ticking a highlighted row
    ticks every highlighted row.

    Views selected in Revit before the tool opened narrow the list to
    themselves and come in ticked, until Show All Views is pressed - which
    shows the rest and leaves the ticks alone.

    Every rule it applies lives in tagall_core and is benched there; this
    class only draws and routes clicks.
    """

    def __init__(self, owner, host, title, key, on_change, modes_outside=False):
        self.owner = owner
        # Family Tags picks Current view / Ticked views from its group header,
        # so its own radios stay hidden there and are driven through set_mode
        self.modes_outside = modes_outside
        self.window = owner.window
        self.key = key
        self.on_change = on_change
        self.records = []
        self.by_key = {}
        self.ticked = set()
        self.selected = set()
        self.anchor = None
        self.keywords = {}
        self.ticks = {}
        self.collapsed = set()
        self.group_1 = u""
        self.group_2 = u""
        self.names = []
        self.preselected = set()
        self.show_all = False
        self.order = []
        self.row_ui = {}
        self.group_boxes = []
        self.loading = False
        self.reason = core.OPEN_VIEW
        self.tick_width = 28
        self.timer = DispatcherTimer()
        self.timer.Interval = TimeSpan.FromMilliseconds(220)
        self.timer.Tick += ui.ui_safe(owner, self._filter_settled, "view filter")
        self._build(host, title)

    # ---------- construction ----------

    def _build(self, host, title):
        from System.Windows.Controls import RadioButton, RowDefinition, WrapPanel, ScrollViewer, TextBox
        from System.Windows.Controls.Primitives import Popup, PlacementMode
        root = Grid()
        for height in ("auto", "auto", "auto", "auto", "star"):
            row = RowDefinition()
            row.Height = GridLength.Auto if height == "auto" else star(1)
            root.RowDefinitions.Add(row)

        # heading line: title, count, Show All Views
        head = Grid()
        for width in ("auto", "auto", "star", "auto"):
            column = ColumnDefinition()
            column.Width = GridLength.Auto if width == "auto" else star(1)
            head.ColumnDefinitions.Add(column)
        tick = Border()
        tick.SetResourceReference(Border.StyleProperty, "OrangeTick")
        place(head, tick, 0)
        heading = text_block(title)
        heading.SetResourceReference(TextBlock.StyleProperty, "Heading")
        place(head, heading, 1)
        self.count_block = text_block(u"", "MutedBrush", size=11.5)
        self.count_block.Margin = Thickness(8, 0, 0, 0)
        Grid.SetColumn(self.count_block, 2)
        head.Children.Add(self.count_block)
        self.show_all_button = ui.icon_button("eye", u"Show All Views", tooltip=(
            u"Views selected in Revit narrowed this list. Show the rest; "
            u"their ticks stay as they are."))
        self.show_all_button.Padding = Thickness(8, 2, 8, 2)
        self.show_all_button.MinHeight = 24
        self.show_all_button.Visibility = Visibility.Collapsed
        self.show_all_button.Click += ui.ui_safe(self.owner, self._show_all_click, "show all views")
        place(head, self.show_all_button, 3)
        head.Margin = Thickness(0, 0, 0, 8)
        Grid.SetRow(head, 0)
        root.Children.Add(head)

        # mode: current view only, or the ticked views below
        modes = StackPanel()
        modes.Orientation = Orientation.Horizontal
        modes.Margin = Thickness(0, 0, 0, 8)
        self.current_radio = RadioButton()
        self.current_radio.Content = u"Current view only"
        self.current_radio.GroupName = u"ViewMode_" + self.key
        self.current_radio.Margin = Thickness(0, 0, 18, 0)
        self.ticked_radio = RadioButton()
        self.ticked_radio.Content = u"Ticked views"
        self.ticked_radio.GroupName = u"ViewMode_" + self.key
        self.current_radio.Checked += ui.ui_safe(self.owner, self._mode_changed, "current view only")
        self.ticked_radio.Checked += ui.ui_safe(self.owner, self._mode_changed, "ticked views")
        modes.Children.Add(self.current_radio)
        modes.Children.Add(self.ticked_radio)
        Grid.SetRow(modes, 1)
        root.Children.Add(modes)
        if self.modes_outside:
            modes.Visibility = Visibility.Collapsed

        # everything below greys out with Current view only
        self.body = Grid()
        Grid.SetRow(self.body, 2)
        Grid.SetRowSpan(self.body, 3)
        root.Children.Add(self.body)
        for height in ("auto", "auto", "auto", "star", "auto"):
            row = RowDefinition()
            row.Height = GridLength.Auto if height == "auto" else star(1)
            self.body.RowDefinitions.Add(row)

        groups = Grid()
        for width in ("auto", "star", "auto", "star"):
            column = ColumnDefinition()
            column.Width = GridLength.Auto if width == "auto" else star(1)
            groups.ColumnDefinitions.Add(column)
        label = text_block(u"Group by", "MutedBrush")
        label.Margin = Thickness(0, 0, 8, 0)
        place(groups, label, 0)
        self.group_1_combo = ComboBox()
        self.group_1_combo.ToolTip = u"The parameter the View group column reads, and the first level of grouping"
        place(groups, self.group_1_combo, 1)
        label = text_block(u"then", "MutedBrush")
        label.Margin = Thickness(10, 0, 8, 0)
        place(groups, label, 2)
        self.group_2_combo = ComboBox()
        self.group_2_combo.ToolTip = u"The parameter the View group 2 column reads, and the second level"
        place(groups, self.group_2_combo, 3)
        self.group_1_combo.SelectionChanged += ui.ui_safe(self.owner, self._group_changed, "view group")
        self.group_2_combo.SelectionChanged += ui.ui_safe(self.owner, self._group_changed, "view group 2")
        groups.Margin = Thickness(0, 0, 0, 8)
        Grid.SetRow(groups, 0)
        self.body.Children.Add(groups)

        tools = WrapPanel()
        tools.Margin = Thickness(0, 0, 0, 6)
        for icon, text, handler, tip in (
                ("expand", u"Expand all", self._expand_all, None),
                ("collapse", u"Collapse all", self._collapse_all, None),
                ("tick", u"Tick all", self._tick_all, u"Tick every view the filters leave showing"),
                ("box", u"Untick all", self._untick_all, u"Untick every view the filters leave showing"),
                ("cross", u"Clear filters", self._clear_filters, None)):
            button = ui.icon_button(icon, text, tooltip=tip)
            button.Padding = Thickness(7, 1, 7, 1)
            button.MinHeight = 22
            button.FontSize = 11
            button.Margin = Thickness(0, 0, 4, 4)
            button.Click += ui.ui_safe(self.owner, handler, text.lower())
            tools.Children.Add(button)
        Grid.SetRow(tools, 1)
        self.body.Children.Add(tools)

        frame = Border()
        frame.SetResourceReference(Border.StyleProperty, "Field")
        Grid.SetRow(frame, 2)
        Grid.SetRowSpan(frame, 2)
        self.body.Children.Add(frame)
        inner = Grid()
        for height in ("auto", "star"):
            row = RowDefinition()
            row.Height = GridLength.Auto if height == "auto" else star(1)
            inner.RowDefinitions.Add(row)
        frame.Child = inner
        self.header = Border()
        self.header.SetResourceReference(Border.BackgroundProperty, "HeaderRowBrush")
        self.header.SetResourceReference(Border.BorderBrushProperty, "EdgeBrush")
        self.header.BorderThickness = Thickness(0, 0, 0, 1)
        self.header.Padding = Thickness(4, 4, 14, 5)
        inner.Children.Add(self.header)
        scroll = ScrollViewer()
        scroll.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
        scroll.HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled
        self.list_host = StackPanel()
        self.list_host.Margin = Thickness(2)
        scroll.Content = self.list_host
        Grid.SetRow(scroll, 1)
        inner.Children.Add(scroll)

        hint = text_block(u"Click to highlight, Shift+click for a run, Ctrl+click to add one - "
                          u"then tick any highlighted view to tick them all. A heading's box "
                          u"ticks its whole group.", "MutedBrush", size=11)
        hint.TextWrapping = TextWrapping.Wrap
        hint.Margin = Thickness(0, 6, 0, 0)
        Grid.SetRow(hint, 4)
        self.body.Children.Add(hint)

        # the tick-list popup, kept in the tree so its themed resources resolve
        self.popup = Popup()
        self.popup.StaysOpen = False
        self.popup.AllowsTransparency = True
        self.popup.Placement = PlacementMode.Bottom
        root.Children.Add(self.popup)
        self.popup_column = None

        self.keyword_boxes = {}
        self.carets = {}
        self.header_labels = {}
        self._build_header()
        host.Child = root

    def _build_header(self):
        from System.Windows.Controls import TextBox
        grid = self._row_grid()
        for index, (column, _weight, _minimum) in enumerate(VIEW_WIDTHS):
            if column == "tick":
                continue
            cell = StackPanel()
            cell.Margin = Thickness(3, 0, 3, 0)
            line = Grid()
            first = ColumnDefinition()
            first.Width = star(1)
            line.ColumnDefinitions.Add(first)
            second = ColumnDefinition()
            second.Width = GridLength.Auto
            line.ColumnDefinitions.Add(second)
            label = text_block(VIEW_HEADINGS[column], "MutedBrush", size=11.5, bold=True)
            label.TextTrimming = TextTrimming.CharacterEllipsis
            place(line, label, 0)
            caret = Button()
            caret.SetResourceReference(Button.StyleProperty, "TreeToggle")
            caret.Content = u"▾"
            caret.ToolTip = u"Tick which values to show"
            caret.Click += self._make_caret(column)
            place(line, caret, 1)
            cell.Children.Add(line)
            box = TextBox()
            box.Tag = u"Filter"
            box.MinHeight = 24
            box.Padding = Thickness(4, 0, 4, 0)
            box.FontSize = 11.5
            box.Margin = Thickness(0, 3, 0, 0)
            box.TextChanged += self._make_keyword(column)
            cell.Children.Add(box)
            self.keyword_boxes[column] = box
            self.carets[column] = caret
            self.header_labels[column] = label
            place(grid, cell, index)
        self.header_grid = grid
        self.header.Child = grid

    def _row_grid(self):
        """Header and rows share one recipe, so the columns line up. The
        tick column widens with the grouping depth, because each level
        indents the tick box under its heading."""
        grid = Grid()
        for column, weight, minimum in VIEW_WIDTHS:
            definition = ColumnDefinition()
            if column == "tick":
                definition.Width = pixels(self.tick_width)
            else:
                definition.Width = star(weight)
                definition.MinWidth = minimum
            grid.ColumnDefinitions.Add(definition)
        return grid

    # ---------- loading ----------

    def load(self, records, names, group_1, group_2, ticked=None, scope=None):
        """Fill the table. `scope` is core.opening_scope's answer for this
        list - (current only, narrowed keys, reason) - which decides the mode
        it starts in and the views it starts narrowed to and ticked."""
        current_only, narrowed, reason = scope or (True, set(), core.OPEN_VIEW)
        self.loading = True
        try:
            self.records = list(records)
            self.by_key = dict([(record.key, record) for record in self.records])
            self.names = list(names)
            if ticked is not None:
                self.ticked = set([key for key in ticked if key in self.by_key])
            self.preselected = set([key for key in narrowed if key in self.by_key])
            self.reason = reason
            self.show_all = False
            if self.preselected:
                # the views the tool opened on come in ticked, and the list starts on them
                self.ticked |= self.preselected
                current_only = False
            self.show_all_button.Visibility = Visibility.Visible if self.preselected else Visibility.Collapsed
            ui.set_label(self.show_all_button, u"Show All Views")
            self.show_all_button.ToolTip = (
                u"This list starts on the views on the open sheet. Show the rest; their ticks stay as they are."
                if reason == core.OPEN_SHEET else
                u"This list starts on the views picked in Revit. Show the rest; their ticks stay as they are.")
            for combo, chosen in ((self.group_1_combo, group_1), (self.group_2_combo, group_2)):
                combo.Items.Clear()
                combo.Items.Add(core.NONE_TAG)
                for name in self.names:
                    combo.Items.Add(name)
                combo.SelectedItem = chosen if chosen in self.names else core.NONE_TAG
            self.group_1 = self._combo_value(self.group_1_combo)
            self.group_2 = self._combo_value(self.group_2_combo)
            if current_only:
                self.current_radio.IsChecked = True
            else:
                self.ticked_radio.IsChecked = True
        finally:
            self.loading = False
        self._relabel()
        self._apply_mode()
        self.rebuild()

    def _combo_value(self, combo):
        value = to_text(combo.SelectedItem)
        return u"" if value == core.NONE_TAG else value

    # ---------- the rows the table is showing ----------

    def base_rows(self):
        rows = [(record.key, record.cells(self.group_1, self.group_2)) for record in self.records]
        return core.restrict_to_preselection(rows, self.preselected, self.show_all)

    def shown_rows(self):
        return core.filter_rows(self.base_rows(), self.keywords, self.ticks)

    def rebuild(self):
        rows = self.shown_rows()
        use_1 = bool(self.group_1)
        use_2 = bool(self.group_2)
        groups = core.group_rows(rows, use_1, use_2)
        self.order = core.flatten_visible(groups, self.collapsed, use_1, use_2)
        self.tick_width = 28 + 16 * ((1 if use_1 else 0) + (1 if use_2 else 0))
        self.header_grid.ColumnDefinitions[0].Width = pixels(self.tick_width)
        self.list_host.Children.Clear()
        self.row_ui = {}
        self.group_boxes = []
        for first, inner in groups:
            members_1 = [row[0] for _second, members in inner for row in members]
            open_1 = True
            if use_1:
                gid = core.group_id(first)
                open_1 = gid not in self.collapsed
                self.list_host.Children.Add(self._heading(0, first, gid, members_1, open_1))
            if not open_1:
                continue
            for second, members in inner:
                keys = [row[0] for row in members]
                open_2 = True
                if use_2:
                    gid = core.group_id(first, second)
                    open_2 = gid not in self.collapsed
                    self.list_host.Children.Add(self._heading(1 if use_1 else 0, second, gid, keys, open_2))
                if not open_2:
                    continue
                for key, cells in members:
                    self.list_host.Children.Add(self._row(key, cells, (use_1 and 1 or 0) + (use_2 and 1 or 0)))
        if not self.records:
            self.list_host.Children.Add(text_block(u"No views of a kind this tab can tag in.", "MutedBrush"))
        elif not rows:
            self.list_host.Children.Add(text_block(u"No views match the filters.", "MutedBrush"))
        self._paint()
        self._paint_carets()
        self._count()

    def _heading(self, depth, label, gid, keys, is_open):
        border = Border()
        border.Padding = Thickness(2 + depth * 16, 3, 4, 3)
        border.Margin = Thickness(0, 2 if depth == 0 else 0, 0, 0)
        if depth == 0:
            border.SetResourceReference(Border.BackgroundProperty, "HeaderRowBrush")
        line = StackPanel()
        line.Orientation = Orientation.Horizontal
        toggle = Button()
        toggle.SetResourceReference(Button.StyleProperty, "TreeToggle")
        toggle.Content = u"▾" if is_open else u"▸"
        toggle.Click += self._make_fold(gid)
        line.Children.Add(toggle)
        box = CheckBox()
        box.Margin = Thickness(4, 0, 6, 0)
        box.VerticalAlignment = VerticalAlignment.Center
        box.Click += self._make_group_tick(keys)
        line.Children.Add(box)
        self.group_boxes.append((box, keys))
        text = text_block(label or core.BLANK_LABEL, "BlueBrush" if depth == 0 else "OrangeBrush", bold=(depth == 0))
        line.Children.Add(text)
        count = text_block(u"  {0}".format(len(keys)), "MutedBrush", size=11)
        line.Children.Add(count)
        border.Child = line
        return border

    def _row(self, key, cells, depth):
        border = Border()
        border.Padding = Thickness(2, 2, 2, 2)
        border.CornerRadius = ui.corner(3)
        border.Background = ui.transparent()
        border.Cursor = ui.hand_cursor()
        grid = self._row_grid()
        box = CheckBox()
        box.Margin = Thickness(4 + depth * 16, 0, 0, 0)
        box.VerticalAlignment = VerticalAlignment.Center
        box.Focusable = False
        box.Click += self._make_tick(key)
        place(grid, box, 0)
        for index, column in enumerate(("name", "type", "g1", "g2")):
            value = cells.get(column, u"")
            block = text_block(value, "TextBrush" if column == "name" else "MutedBrush")
            block.TextTrimming = TextTrimming.CharacterEllipsis
            block.Margin = Thickness(4, 0, 4, 0)
            block.ToolTip = value or None
            place(grid, block, index + 1)
        border.Child = grid
        border.MouseLeftButtonDown += self._make_click(key)
        self.row_ui[key] = (border, box)
        return border

    def _paint(self):
        for key, pair in self.row_ui.items():
            border, box = pair
            box.IsChecked = key in self.ticked
            if key in self.selected:
                ui.set_brush(border, "Background", "SelectBrush")
            else:
                border.Background = ui.transparent()
        for box, keys in self.group_boxes:
            box.IsChecked = bool(keys) and set(keys).issubset(self.ticked)

    def _paint_carets(self):
        for column, caret in self.carets.items():
            filtered = core.is_filtered(column, self.keywords, self.ticks)
            caret.Content = u"▼" if filtered else u"▾"
            ui.set_brush(caret, "Foreground", "OrangeBrush" if filtered else "MutedBrush")

    def _count(self):
        shown = len(self.shown_rows())
        total = len(self.base_rows())
        ticked = len(self.ticked)
        if shown == total:
            text = u"{0} views".format(total)
        else:
            text = u"{0} of {1} views".format(shown, total)
        if ticked:
            text = u"{0}, {1} ticked".format(text, ticked)
        self.count_block.Text = text

    def _relabel(self):
        self.header_labels["g1"].Text = self.group_1 or VIEW_HEADINGS["g1"]
        self.header_labels["g2"].Text = self.group_2 or VIEW_HEADINGS["g2"]

    # ---------- gestures ----------

    def _make_click(self, key):
        def handler(sender, args):
            self.selected, self.anchor = core.pick_rows(
                self.selected, self.anchor, key, self.order,
                ui.control_held(), ui.shift_held())
            self._paint()
        return ui.ui_safe(self.owner, handler, "highlight view")

    def _make_tick(self, key):
        def handler(sender, args):
            self.ticked = core.apply_tick(self.ticked, self.selected, key, bool(sender.IsChecked))
            self._paint()
            self._count()
            self._changed()
        return ui.ui_safe(self.owner, handler, "tick view")

    def _make_group_tick(self, keys):
        def handler(sender, args):
            self.ticked = core.toggle_group(self.ticked, keys)
            self._paint()
            self._count()
            self._changed()
        return ui.ui_safe(self.owner, handler, "tick group")

    def _make_fold(self, gid):
        def handler(sender, args):
            if gid in self.collapsed:
                self.collapsed.discard(gid)
            else:
                self.collapsed.add(gid)
            self.rebuild()
        return ui.ui_safe(self.owner, handler, "fold group")

    def _expand_all(self, sender, args):
        self.collapsed = set()
        self.rebuild()

    def _collapse_all(self, sender, args):
        groups = core.group_rows(self.shown_rows(), bool(self.group_1), bool(self.group_2))
        self.collapsed = core.all_group_ids(groups, bool(self.group_1), bool(self.group_2))
        self.rebuild()

    def _tick_all(self, sender, args):
        self.ticked.update([row[0] for row in self.shown_rows()])
        self._paint()
        self._count()
        self._changed()

    def _untick_all(self, sender, args):
        self.ticked.difference_update([row[0] for row in self.shown_rows()])
        self._paint()
        self._count()
        self._changed()

    def _clear_filters(self, sender, args):
        self.keywords = {}
        self.ticks = {}
        self.loading = True
        try:
            for box in self.keyword_boxes.values():
                box.Text = u""
        finally:
            self.loading = False
        self.rebuild()

    def _show_all_click(self, sender, args):
        self.show_all = not self.show_all
        ui.set_label(self.show_all_button,
                     core.opening_back_label(self.reason) if self.show_all else u"Show All Views")
        self.rebuild()

    def set_mode(self, current_only):
        """Current view only, or the ticked views - from outside the table.
        The radio's own Checked handler does the rest."""
        if current_only:
            self.current_radio.IsChecked = True
        else:
            self.ticked_radio.IsChecked = True

    def _mode_changed(self, sender, args):
        if self.loading:
            return
        self._apply_mode()
        self._changed()

    def _apply_mode(self):
        greyed = self.use_active()
        self.body.IsEnabled = not greyed
        self.body.Opacity = 0.45 if greyed else 1.0

    def _group_changed(self, sender, args):
        if self.loading:
            return
        self.group_1 = self._combo_value(self.group_1_combo)
        self.group_2 = self._combo_value(self.group_2_combo)
        # the group columns now read different parameters, so their filters
        # and the folds keyed by their values mean nothing any more
        for column in ("g1", "g2"):
            self.ticks.pop(column, None)
        self.collapsed = set()
        self._relabel()
        self.rebuild()
        self.owner.save()

    def _make_keyword(self, column):
        def handler(sender, args):
            if self.loading:
                return
            self.keywords[column] = to_text(sender.Text).strip()
            self.timer.Stop()
            self.timer.Start()
        return ui.ui_safe(self.owner, handler, "view filter")

    def _filter_settled(self, sender, args):
        self.timer.Stop()
        self.rebuild()

    def _changed(self):
        if self.on_change:
            self.on_change()

    # ---------- the tick-list popup ----------

    def _make_caret(self, column):
        def handler(sender, args):
            self._open_popup(column, sender)
        return ui.ui_safe(self.owner, handler, "column values")

    def _open_popup(self, column, caret):
        open_value_popup(self, column, caret)

    # ---------- what a run asks for ----------

    def use_active(self):
        return bool(self.current_radio.IsChecked)

    def ticked_records(self):
        return [record for record in self.records if record.key in self.ticked]

    def count(self):
        return len([key for key in self.ticked if key in self.by_key])


class TagAllWindow(object):

    def __init__(self, uiapp, settings, dispatcher, owner_handle=None):
        self.uiapp = uiapp
        self.settings = settings
        self.dispatcher = dispatcher
        self.mode = settings.get("theme_mode", core.THEME_AUTO)
        if self.mode not in core.THEME_ORDER:
            self.mode = core.THEME_AUTO
        self.busy = False
        self.closed = False
        self.sources = []
        self.tag_symbols = {}
        self.link_boxes = {}
        self.room_tag_types = []
        self.room_views_records = []
        self.family_records = []
        self.room_sheet_records = []
        self.context = {"active_key": 0, "active_is_sheet": False, "sheet_views": [],
                        "selected_views": set(), "selected_sheets": set()}
        self.tree_views_loaded = None   # which views the tree was last read from
        self.links_open = True
        self.links_loaded = set()      # which models the tree was last read from
        self.links_timer = DispatcherTimer()
        self.links_timer.Interval = TimeSpan.FromMilliseconds(core.LINK_SETTLE_MS)
        self.links_timer.Tick += ui.ui_safe(self, self._links_settled, "read linked models")
        self.window = ui.load_window("TagAll.xaml", self.mode)
        self.find = self.window.FindName
        find = self.find
        ui.own_to_revit(self.window, owner_handle)
        find("VersionText").Text = u"v{0}".format(core.__version__)
        find("ToolTitle").Text = core.TOOL_NAME
        ui.load_icon(find("LogoImage"))
        try:
            # three columns want the room; a size saved by 1.0 is too narrow
            self.window.Width = max(1240.0, core.parse_float(settings.get("window_w"), 1560))
            self.window.Height = max(680.0, core.parse_float(settings.get("window_h"), 880))
        except Exception:
            pass

        ui.iconize_named(self.window)

        # ---- chrome
        grips = ui.grips_of(self.window, ("GripN", "GripS", "GripE", "GripW", "GripNE", "GripNW", "GripSE", "GripSW"))
        self.chrome = ui.Chrome(self.window, find("HeaderBar"), grips, find("FullScreenButton"),
                                shrink_button=find("ShrinkButton"))
        find("CloseButton").Click += ui.ui_safe(self, self._close_click, "close")
        find("ThemeChip").Click += ui.ui_safe(self, self._theme_click, "theme")
        self._label_theme()
        self.window.Closed += self._closed
        ui.attach_egg(self.window, find("LogoHost"), self.mode)
        self._hook_theme_changed()

        # ---- family tab: three stacked groups, each shutting to its header
        self._setup_groups()
        self.tree = Tree(self, find("TreeHost"), find("FamilySearch"), find("TreeCount"), find("TreeHeader"))
        self.table = None
        find("ExpandAll").Click += ui.ui_safe(self, lambda s, a: self.tree.expand_all(True), "expand")
        find("CollapseAll").Click += ui.ui_safe(self, lambda s, a: self.tree.expand_all(False), "collapse")
        find("ClearTicks").Click += ui.ui_safe(self, lambda s, a: self.tree.clear_ticks(), "untick")
        find("AddSelected").Click += ui.ui_safe(self, self._add_ticked, "add ticked")
        find("AddFromRevit").Click += ui.ui_safe(self, self._add_from_revit, "add from selection")
        find("ClearTable").Click += ui.ui_safe(self, self._clear_table, "clear table")
        find("RemoveHighlighted").Click += ui.ui_safe(self, self._remove_highlighted, "remove rows")
        for name in ("OffsetX", "OffsetY", "ElbowMm"):
            ui.select_all_on_focus(find(name))
        find("LinksToggle").Click += ui.ui_safe(self, self._links_toggle, "links")
        find("LinksAll").Click += ui.ui_safe(self, self._links_all, "tick every link")
        find("LinksNone").Click += ui.ui_safe(self, self._links_none, "untick every link")
        for name in ("UntangleCheck", "TidyCheck"):
            find(name).Checked += ui.ui_safe(self, self._after_placing_changed, "untangle or tidy")
            find(name).Unchecked += ui.ui_safe(self, self._after_placing_changed, "untangle or tidy")
        grip = find("LinksGrip")
        grip.DragDelta += ui.ui_safe(self, self._links_drag, "resize the linked models list")
        grip.DragCompleted += ui.ui_safe(self, self._links_drag_done, "resize the linked models list")
        grip.MouseDoubleClick += ui.ui_safe(self, self._links_reset, "put the linked models list back")
        find("LinksRefresh").Click += ui.ui_safe(self, self._refresh_tree, "refresh")
        self.family_views = ViewTable(self, find("FamilyViewHost"), u"Views", u"family",
                                      self._family_views_changed, modes_outside=True)
        self.family_sheets = SheetTable(self, find("FamilySheetHost"), u"Sheets", u"family",
                                        self._family_views_changed)
        self.family_list_index = 0
        find("FamilyListTabs").SelectionChanged += ui.ui_safe(self, self._family_source_changed, "views or sheets")
        find("SourceCurrent").Click += self._make_source_click(core.SOURCE_CURRENT)
        find("SourceTicked").Click += self._make_source_click(core.SOURCE_TICKED)
        find("SourceSheets").Click += self._make_source_click(core.SOURCE_SHEETS)
        self.run_sheets = []
        # ---- room tab
        self.room_views = ViewTable(self, find("RoomViewHost"), u"Plan views to tag rooms in", u"room",
                                    self._update_button)
        self.room_sheets = SheetTable(self, find("RoomSheetHost"), u"Sheets to tag the rooms on", u"room",
                                      self._update_button)
        find("RoomSource").SelectionChanged += ui.ui_safe(self, self._room_source_changed, "room source")
        find("RoomByViews").Checked += ui.ui_safe(self, self._room_list_changed, "list by views")
        find("RoomBySheets").Checked += ui.ui_safe(self, self._room_list_changed, "list by sheets")
        find("Tabs").SelectionChanged += ui.ui_safe(self, self._tab_changed, "tab")
        find("TagAllButton").Click += ui.ui_safe(self, self._run_click, "tag all")
        self.window.PreviewKeyDown += ui.ui_safe(self, self._key, "key")

        self._apply_settings()
        self._initial_read()
        self._update_button()

    # ---------- settings in and out ----------

    def _apply_settings(self):
        s = self.settings
        find = self.find
        find("LeaderCheck").IsChecked = core.parse_bool(s.get("leader"), True)
        find("OffsetX").Text = to_text(s.get("offset_x", u"600"))
        find("OffsetY").Text = to_text(s.get("offset_y", u"600"))
        find("ElbowCheck").IsChecked = core.parse_bool(s.get("elbow"), True)
        find("ElbowMm").Text = to_text(s.get("elbow_mm", u"300"))
        self._apply_links_height()
        find("RemovePrevious").IsChecked = core.parse_bool(s.get("remove_previous"), False)
        find("OnlyUntagged").IsChecked = core.parse_bool(s.get("only_untagged"), True)
        untangle, tidy_on = core.after_placing(core.parse_bool(s.get("untangle"), False),
                                               core.parse_bool(s.get("tidy"), True))
        find("UntangleCheck").IsChecked = untangle
        find("TidyCheck").IsChecked = tidy_on
        self._paint_after_placing()
        try:
            find("TidyNote").Text = TIDY_NOTE + u" " + tidy.describe()
        except Exception:
            pass
        find("RoomRemoveUnassigned").IsChecked = core.parse_bool(s.get("room_remove_unassigned"), True)
        find("RoomOnlyUntagged").IsChecked = core.parse_bool(s.get("room_only_untagged"), True)
        if to_text(s.get("room_list")) == u"sheets":
            find("RoomBySheets").IsChecked = True
        else:
            find("RoomByViews").IsChecked = True
        if s.get("tab") == "room":
            find("Tabs").SelectedIndex = 1

    def collect_settings(self):
        s = self.settings
        find = self.find
        s["theme_mode"] = self.mode
        s["leader"] = core.bool_text(find("LeaderCheck").IsChecked)
        s["offset_x"] = to_text(core.parse_float(find("OffsetX").Text, 600))
        s["offset_y"] = to_text(core.parse_float(find("OffsetY").Text, 600))
        s["elbow"] = core.bool_text(find("ElbowCheck").IsChecked)
        s["elbow_mm"] = to_text(core.parse_float(find("ElbowMm").Text, 300))
        s["remove_previous"] = core.bool_text(find("RemovePrevious").IsChecked)
        s["only_untagged"] = core.bool_text(find("OnlyUntagged").IsChecked)
        s["untangle"] = core.bool_text(find("UntangleCheck").IsChecked)
        s["tidy"] = core.bool_text(find("TidyCheck").IsChecked)
        for table, prefix in ((self.family_sheets, u"family"), (self.room_sheets, u"room")):
            s[prefix + u"_sheet_group_1"] = table.group_1
            s[prefix + u"_sheet_group_2"] = table.group_2
            s[prefix + u"_sheet_widths"] = core.widths_text(table.weights)
        for table, prefix in ((self.family_views, u"family"), (self.room_views, u"room")):
            s[prefix + u"_view_group_1"] = table.group_1
            s[prefix + u"_view_group_2"] = table.group_2
        s["room_remove_unassigned"] = core.bool_text(find("RoomRemoveUnassigned").IsChecked)
        s["room_only_untagged"] = core.bool_text(find("RoomOnlyUntagged").IsChecked)
        s["room_list"] = self._room_list_mode()
        s["tab"] = u"room" if find("Tabs").SelectedIndex == 1 else u"family"
        try:
            s["room_tag_type"] = to_text(find("RoomTagType").SelectedItem)
        except Exception:
            pass
        source = self._room_source()
        if source is not None:
            s["room_source"] = source.key if not source.is_link else source.name
        try:
            links_h = self.find("LinksScroll").Height
            s["links_height"] = u"" if links_h != links_h else to_text(int(round(links_h)))
        except Exception:
            pass
        s["links"] = core.join_pipe([name for name, box in self.link_boxes.items() if box.IsChecked])
        try:
            if not self.chrome.is_full():
                # the real size, not the parked bar's, if it is closed while shrunk
                width, height = self.chrome.true_size()
                s["window_w"] = to_text(int(width))
                s["window_h"] = to_text(int(height))
        except Exception:
            pass
        return s

    def save(self):
        try:
            core.save_settings(self.collect_settings())
        except Exception:
            core.log(u"settings save failed:\n{0}".format(traceback.format_exc()))

    # ---------- theme ----------

    def _label_theme(self):
        ui.set_label(self.find("ThemeChip"), core.theme_label(self.mode))

    def _theme_click(self, sender, args):
        self.mode = core.next_theme_mode(self.mode)
        theme.apply(self.window, theme.resolve(self.mode))
        self._label_theme()
        self.settings["theme_mode"] = self.mode
        self.save()

    def _hook_theme_changed(self):
        """Revit 2024+ raises ThemeChanged; in Auto the window follows it.
        Hooked once, guarded by the closed flag rather than unhooked."""
        try:
            self.uiapp.ThemeChanged += self._theme_changed
        except Exception:
            pass

    def _theme_changed(self, sender, args):
        try:
            if self.closed or self.mode != core.THEME_AUTO:
                return
            theme.apply(self.window, theme.resolve(self.mode))
        except Exception:
            pass

    # ---------- reading the model ----------

    def _uidoc(self):
        return self.uiapp.ActiveUIDocument

    def _initial_read(self):
        """The first read runs inside the command, so the API context is
        valid. Later refreshes try the same direct read and fall back to the
        ExternalEvent if Revit objects."""
        try:
            self._read_all(self.uiapp)
        except Exception:
            core.log(u"initial read failed:\n{0}".format(traceback.format_exc()))
            self.set_status(u"The first read failed - see the log", True)

    def _read_all(self, uiapp):
        uidoc = uiapp.ActiveUIDocument
        doc = uidoc.Document
        self.sources = model.list_sources(doc)
        self.tag_symbols = model.list_tag_symbols(doc)
        self.table = TagTable(self, self.find("TableHost"), self.find("TableHeader"),
                              self.find("TableCount"), self.tag_symbols, self.find("HighlightTag"))
        self._build_links()
        # what the tool opened on: a sheet, viewports picked on it, views
        # picked in the Project Browser, or a plain view
        self.context = model.opening_context(uidoc)
        family_records = model.list_views(doc, model.FAMILY_VIEW_TYPES)
        self.room_views_records = model.list_views(doc, model.ROOM_VIEW_TYPES)
        family_scope = self._load_view_table(self.family_views, family_records, u"family")
        self._load_view_table(self.room_views, self.room_views_records, u"room")
        # every sheet for Family Tags; for Room Tags only sheets carrying a plan
        self.family_records = family_records
        family_sheets, _none = model.list_sheets(doc, family_records, include_empty=True)
        self.room_sheet_records, _skipped = model.list_sheets(doc, self.room_views_records)
        # sheets picked in the Project Browser, or the sheet the tool opened on, come in ticked
        sheet_ticks = set(self.context["selected_sheets"])
        if self.context["active_is_sheet"]:
            sheet_ticks.add(self.context["active_key"])
        self._load_sheet_table(self.family_sheets, family_sheets, u"family", sheet_ticks)
        self._load_sheet_table(self.room_sheets, self.room_sheet_records, u"room", sheet_ticks)
        self._show_room_list()
        self._paint_sources()
        self._read_tree(uiapp)
        self._build_room_sources()
        self._build_room_tags(doc)
        self.set_status(self._opening_text(family_scope))

    def _load_view_table(self, table, records, prefix):
        names = model.view_parameter_names(records)
        default_1, default_2 = model.default_groups(names)
        group_1 = to_text(self.settings.get(prefix + u"_view_group_1")) or default_1
        group_2 = to_text(self.settings.get(prefix + u"_view_group_2")) or default_2
        context = self.context
        scope = core.opening_scope([record.key for record in records], context["active_key"],
                                   context["active_is_sheet"], context["sheet_views"],
                                   context["selected_views"])
        table.load(records, names, group_1, group_2, ticked=None, scope=scope)
        return scope

    def _load_sheet_table(self, table, records, prefix, ticked):
        names = model.view_parameter_names(records)
        default_1, default_2 = model.default_groups(names, model.SHEET_GROUP_DEFAULTS)
        group_1 = to_text(self.settings.get(prefix + u"_sheet_group_1")) or default_1
        group_2 = to_text(self.settings.get(prefix + u"_sheet_group_2")) or default_2
        table.load(records, names, group_1, group_2,
                   ticked=[record.key for record in records if record.key in ticked],
                   widths=self.settings.get(prefix + u"_sheet_widths"))

    def _opening_text(self, scope):
        """One line saying why the Views list starts where it does."""
        _current, narrowed, reason = scope
        count = len(narrowed)
        plural = u"" if count == 1 else u"s"
        if reason == core.OPEN_SHEET:
            return (u"Opened on a sheet - the views list starts on its {0} view{1}, ticked. "
                    u"Show All Views lists the rest.".format(count, plural))
        if reason == core.OPEN_SHEET_SELECTION:
            return (u"{0} view{1} picked on the sheet - the views list starts on them, ticked. "
                    u"Show All Views lists the rest.".format(count, plural))
        if reason == core.OPEN_SELECTION:
            return (u"{0} view{1} picked in Revit - the views list starts on them, ticked. "
                    u"Show All Views lists the rest.".format(count, plural))
        if reason == core.OPEN_SHEET_EMPTY:
            return u"Opened on a sheet with no view on it this tool can tag - tick views to tag in."
        if reason == core.OPEN_UNLISTED:
            return u"The open view cannot be tagged - tick views to tag in."
        return u"Tagging the current view. Press Ticked views or Sheets above to tag others."

    def _build_links(self):
        host = self.find("LinksList")
        host.Children.Clear()
        self.link_boxes = {}
        remembered = set(core.split_pipe(self.settings.get("links", u"")))
        links = [source for source in self.sources if source.is_link]
        for source in links:
            box = CheckBox()
            box.Content = source.name
            box.Margin = Thickness(0, 3, 0, 3)
            box.IsChecked = source.name in remembered
            ui.set_brush(box, "Foreground", "LinkBrush")
            box.Checked += ui.ui_safe(self, self._links_label, "link tick")
            box.Unchecked += ui.ui_safe(self, self._links_label, "link tick")
            self.link_boxes[source.name] = box
            host.Children.Add(box)
        if not links:
            host.Children.Add(text_block(u"No loaded links in this model.", "MutedBrush"))
        self.find("LinksAll").IsEnabled = bool(links)
        self.find("LinksNone").IsEnabled = bool(links)
        self._show_links(False)        # the list starts shut; the badge says what is ticked
        self._links_label(None, None)

    def _ticked_link_names(self):
        return set([name for name, box in self.link_boxes.items() if box.IsChecked])

    def _links_label(self, sender, args):
        """The heading, the count badge and the orange dot that says the ticks
        have moved on from what the tree was read with."""
        ticked = self._ticked_link_names()
        total = len(self.link_boxes)
        caret = u"\u25BE" if self.links_open else u"\u25B8"
        ui.set_label(self.find("LinksToggle"), u"Linked models  {0}".format(caret))
        badge = self.find("LinksBadge")
        if ticked:
            self.find("LinksCount").Text = u"{0} of {1} ticked".format(len(ticked), total)
            badge.Visibility = Visibility.Visible
        elif total:
            self.find("LinksCount").Text = u"{0} available".format(total)
            badge.Visibility = Visibility.Visible
        else:
            badge.Visibility = Visibility.Collapsed
        dirty = ticked != self.links_loaded
        self.find("LinksDirty").Visibility = Visibility.Visible if dirty else Visibility.Collapsed
        if sender is not None and dirty:
            self._schedule_links_read()

    def _schedule_links_read(self):
        """Re-read the tree by itself once the ticking stops.

        Restarted on every tick, so ticking three models in a row - or
        pressing All - is one read of three rather than three reads. A tag
        run owns the document while it is going, so a read waits for it and
        the orange dot stays up meanwhile.
        """
        self._schedule_tree_read(u"Reading the ticked models...")

    def _schedule_tree_read(self, text):
        if self.busy:
            self.set_status(u"The categories will be read once this run has finished")
            return
        self.links_timer.Stop()
        self.links_timer.Start()
        self.set_status(text)

    def _links_settled(self, sender, args):
        self.links_timer.Stop()
        if self.busy:
            return
        self._refresh_tree(sender, args)

    def _show_links(self, on):
        self.links_open = bool(on)
        self.find("LinksPanel").Visibility = Visibility.Visible if on else Visibility.Collapsed
        self._links_label(None, None)

    def _links_toggle(self, sender, args):
        self._show_links(not self.links_open)

    def _links_all(self, sender, args):
        for box in self.link_boxes.values():
            box.IsChecked = True

    def _links_none(self, sender, args):
        for box in self.link_boxes.values():
            box.IsChecked = False

    def _ticked_sources(self):
        ticked = self._ticked_link_names()
        out = [source for source in self.sources if not source.is_link]
        out.extend([source for source in self.sources
                    if source.is_link and source.name in ticked])
        return out

    def _family_source(self):
        """Views or sheets: whichever tab is showing on the left is the one
        Categories reads and Tag All runs from."""
        return u"sheets" if self.find("FamilyListTabs").SelectedIndex == 1 else u"views"

    # ---------- what the run works through, from the Views / Sheets header ----------

    SOURCE_BUTTONS = (("SourceCurrent", core.SOURCE_CURRENT), ("SourceTicked", core.SOURCE_TICKED),
                      ("SourceSheets", core.SOURCE_SHEETS))

    def _make_source_click(self, source):
        def handler(sender, args):
            self._end_group_slide()
            before = dict(self.groups_open)
            index, current_only, self.groups_open = core.pick_view_source(self.groups_open, source)
            tabs = self.find("FamilyListTabs")
            if tabs.SelectedIndex != index:
                tabs.SelectedIndex = index
            if current_only is not None:
                self.family_views.set_mode(current_only)
            self._paint_sources()
            self._slide_groups(before)
        return ui.ui_safe(self, handler, "what to tag: " + source)

    def _paint_sources(self):
        """Light the header button for what the run will work through."""
        try:
            lit = core.view_source(self.find("FamilyListTabs").SelectedIndex,
                                   self.family_views.use_active())
        except Exception:
            return
        for name, source in self.SOURCE_BUTTONS:
            try:
                button = self.find(name)
                on = source == lit
                button.SetResourceReference(Button.BackgroundProperty, "SelectBrush" if on else "CardBrush")
                button.SetResourceReference(Button.BorderBrushProperty, "BlueBrush" if on else "EdgeBrush")
            except Exception:
                pass

    def _family_source_changed(self, sender, args):
        # SelectionChanged bubbles up from every dropdown inside the tabs;
        # only a real change of tab counts
        index = sender.SelectedIndex
        if index == self.family_list_index:
            return
        self.family_list_index = index
        self._family_views_changed()

    def _tree_views(self, uidoc):
        """The views the Categories column reads: the current view, every view
        ticked on the left, or every taggable view on the ticked sheets."""
        if self._family_source() == u"sheets":
            by_key = dict([(record.key, record) for record in self.family_records])
            return [by_key[key].view for key in self.family_sheets.view_keys() if key in by_key]
        if self.family_views.use_active():
            view = model.active_view(uidoc)
            return [view] if view is not None else []
        return [record.view for record in self.family_views.ticked_records()]

    def _read_tree(self, uiapp):
        uidoc = uiapp.ActiveUIDocument
        views = self._tree_views(uidoc)
        sources = self._ticked_sources()
        node_lists = []
        for source in sources:
            node_lists.append(model.collect_type_nodes_many(source, views))
        nodes = model.merge_nodes(node_lists)
        self.tree.load(nodes)
        self.links_loaded = self._ticked_link_names()
        self.tree_views_loaded = self._tree_view_signature()
        self._links_label(None, None)
        if self._family_source() == u"sheets":
            sheets = self.family_sheets.count()
            scope = u"From {0} view{1} on {2} ticked sheet{3}".format(
                len(views), u"" if len(views) == 1 else u"s", sheets, u"" if sheets == 1 else u"s")
            if not sheets:
                scope = u"Tick sheets to list what is in their views"
        elif self.family_views.use_active():
            scope = u"From the current view"
            if views:
                scope = u"From the current view, {0}".format(model.safe_name(views[0]))
        elif views:
            scope = u"From {0} ticked view{1}".format(len(views), u"" if len(views) == 1 else u"s")
        else:
            scope = u"Tick views on the left to list what is in them"
        self.find("TreeScope").Text = scope
        links = len([source for source in sources if source.is_link])
        detail = u"{0} model{1}".format(len(sources), u"" if len(sources) == 1 else u"s")
        if links:
            detail = u"{0} ({1} linked)".format(detail, links)
        self.set_status(u"Read {0} types from {1} in {2} view{3}".format(
            len(nodes), detail, len(views), u"" if len(views) == 1 else u"s"))

    def _tree_view_signature(self):
        if self._family_source() == u"sheets":
            return (u"sheets",) + tuple(sorted(self.family_sheets.ticked))
        if self.family_views.use_active():
            return (u"active",)
        return tuple(sorted(self.family_views.ticked))

    def _family_views_changed(self):
        """Ticking views on the left re-reads the Categories column by
        itself, on the same settle as ticking a linked model."""
        self._update_button()
        self._paint_sources()
        if self.table is None:
            return                      # still loading
        if self._tree_view_signature() != self.tree_views_loaded:
            self._schedule_tree_read(u"Reading the ticked views...")

    def _refresh_tree(self, sender, args):
        self.links_timer.Stop()
        self.set_status(u"Reading...")
        ui.pump(self.window)
        try:
            self._read_tree(self.uiapp)
        except Exception:
            core.log(u"direct tree read refused, going through the event:\n{0}".format(traceback.format_exc()))
            self.dispatcher.submit(u"read tree", lambda uiapp: self._read_tree(uiapp), self._read_done)

    def _read_done(self, result, error):
        if error:
            self.set_status(u"The read failed - see the log", True)

    # ---------- family tab actions ----------

    def _add_ticked(self, sender, args):
        nodes = self.tree.ticked_nodes()
        if not nodes:
            self.set_status(u"Tick a category, family or type first")
            return
        added = self.table.add(nodes)
        self.tree.clear_ticks()
        self.set_status(u"{0} row{1} added to the table".format(added, u"" if added == 1 else u"s"))
        self._update_button()
        # the rows are in Families to tag now: show them there
        self._end_group_slide()
        before = dict(self.groups_open)
        self.groups_open = core.show_families_group(self.groups_open)
        self._slide_groups(before)

    # ---------- the linked models list, dragged taller ----------

    def _links_drag(self, sender, args):
        scroll = self.find("LinksScroll")
        current = scroll.Height
        if current != current:              # NaN: still at its built height
            current = scroll.ActualHeight
        scroll.Height = core.links_height(current + args.VerticalChange)
        scroll.MaxHeight = Double.PositiveInfinity

    def _links_drag_done(self, sender, args):
        self.save()

    def _links_reset(self, sender, args):
        scroll = self.find("LinksScroll")
        scroll.Height = Double.NaN
        scroll.MaxHeight = 110
        self.save()

    # ---------- untangle or Tag Tidy: one or the other ----------

    def _after_placing_changed(self, sender, args):
        self._paint_after_placing()

    def _paint_after_placing(self):
        """Untangle and Tag Tidy each lay the new tags out, so while one is
        ticked the other is greyed out and cannot be ticked."""
        untangle_box = self.find("UntangleCheck")
        tidy_box = self.find("TidyCheck")
        can_untangle, can_tidy = core.after_placing_enabled(bool(untangle_box.IsChecked), bool(tidy_box.IsChecked))
        untangle_box.IsEnabled = can_untangle
        tidy_box.IsEnabled = can_tidy
        untangle_box.ToolTip = None if can_untangle else u"Untick Tag Tidy to untangle instead"
        tidy_box.ToolTip = None if can_tidy else u"Untick Untangle to use Tag Tidy instead"

    def _apply_links_height(self):
        height = core.saved_links_height(self.settings.get("links_height", u""))
        if height is None:
            return
        scroll = self.find("LinksScroll")
        scroll.Height = height
        scroll.MaxHeight = Double.PositiveInfinity

    def _add_from_revit(self, sender, args):
        ids = model.selected_ids(self._uidoc())
        if not ids:
            self.set_status(u"Nothing is selected in Revit")
            return
        host = [s for s in self.sources if not s.is_link][0]
        nodes = model.nodes_for_elements(host, ids)
        if not nodes:
            self.set_status(u"The selection holds nothing that can be tagged")
            return
        added = self.table.add(nodes)
        self.set_status(u"{0} type{1} added from the selection".format(added, u"" if added == 1 else u"s"))
        self._update_button()

    def _remove_highlighted(self, sender, args):
        self.table.remove_highlighted()

    def _clear_table(self, sender, args):
        self.table.clear()
        self._update_button()

    # ---------- room tab ----------

    def _build_room_sources(self):
        combo = self.find("RoomSource")
        combo.Items.Clear()
        wanted = self.settings.get("room_source", core.HOST_KEY)
        index = 0
        for position, source in enumerate(self.sources):
            combo.Items.Add(source.name)
            if source.key == wanted or source.name == wanted:
                index = position
        combo.SelectedIndex = index

    def _room_list_mode(self):
        try:
            return u"sheets" if self.find("RoomBySheets").IsChecked else u"views"
        except Exception:
            return u"views"

    def _show_room_list(self):
        """Views or sheets: the view table, or the sheet list, on the right.
        Each keeps its own ticks, so switching across and back loses
        nothing."""
        sheets = self._room_list_mode() == u"sheets"
        self.find("RoomViewHost").Visibility = Visibility.Collapsed if sheets else Visibility.Visible
        self.find("RoomSheetsPanel").Visibility = Visibility.Visible if sheets else Visibility.Collapsed

    def _room_list_changed(self, sender, args):
        self._show_room_list()
        self._update_button()

    def _room_source(self):
        try:
            index = self.find("RoomSource").SelectedIndex
            if 0 <= index < len(self.sources):
                return self.sources[index]
        except Exception:
            pass
        return None

    def _room_source_changed(self, sender, args):
        source = self._room_source()
        if source is None:
            return
        try:
            rooms = model.collect_rooms(source)
            self.find("RoomInfo").Text = u"{0} placed room{1}".format(len(rooms), u"" if len(rooms) == 1 else u"s")
        except Exception:
            self.find("RoomInfo").Text = u"could not count the rooms - see the log"
            core.log(traceback.format_exc())

    def _build_room_tags(self, doc):
        combo = self.find("RoomTagType")
        combo.Items.Clear()
        self.room_tag_types = model.list_room_tag_types(doc)
        wanted = self.settings.get("room_tag_type", u"")
        index = 0
        for position, (display, _id) in enumerate(self.room_tag_types):
            combo.Items.Add(display)
            if display == wanted:
                index = position
        if self.room_tag_types:
            combo.SelectedIndex = index
        else:
            combo.Items.Add(u"(no room tag family loaded)")
            combo.SelectedIndex = 0
            combo.IsEnabled = False

    def _room_tag(self):
        try:
            index = self.find("RoomTagType").SelectedIndex
            if 0 <= index < len(self.room_tag_types):
                return self.room_tag_types[index]
        except Exception:
            pass
        return (u"", None)

    # ---------- the run ----------

    def _tab_changed(self, sender, args):
        self._update_button()
        # SelectionChanged bubbles up from every dropdown on the tabs; only a
        # real change of tab refits the window
        index = self.find("Tabs").SelectedIndex
        if index == self.main_tab_index:
            return
        self.main_tab_index = index
        self._end_group_slide()
        self._refit_window()

    def _current_tab(self):
        return u"room" if self.find("Tabs").SelectedIndex == 1 else u"family"

    def _update_button(self):
        """Tag All is enabled when there is something to tag and somewhere to
        tag it, and its label says where: the current view, or how many
        ticked views or sheets."""
        button = self.find("TagAllButton")
        if self.busy:
            button.IsEnabled = False
            return
        if self._current_tab() == u"room":
            picker = self.room_sheets if self._room_list_mode() == u"sheets" else self.room_views
            ready = self._room_source() is not None
            base = u"Tag All Rooms"
        else:
            picker = self.family_sheets if self._family_source() == u"sheets" else self.family_views
            ready = self.table is not None and bool(self.table.specs())
            base = u"Tag All"
        count = picker.count()
        if not picker.use_active() and not count:
            ready = False
        if picker.use_active():
            label = base
        elif isinstance(picker, SheetTable):
            label = u"{0} - {1} sheet{2}".format(base, count, u"" if count == 1 else u"s") if count else base
        else:
            label = u"{0} - {1} view{2}".format(base, count, u"" if count == 1 else u"s") if count else base
        ui.set_label(button, label)
        if self.table is not None:
            self.table._count()
        button.IsEnabled = ready

    def _views_for(self, picker, plan_only):
        """The views a run will work in, and why not where there are none."""
        if picker.use_active():
            view = model.active_view(self._uidoc())
            if view is None:
                return None, u"There is no active graphical view"
            record = model.ViewRecord(view)
            try:
                if view.IsTemplate:
                    return None, u"The active view is a view template"
            except Exception:
                pass
            if model.is_sheet(view):
                return None, u"The current view is a sheet - tick the views on it to tag in them instead"
            if plan_only and not record.is_plan:
                return None, u"Rooms are tagged in plan views - the active view is a {0}".format(record.kind)
            return [record], None
        if picker is self.room_sheets:
            return self._views_from_sheets(picker, self.room_views_records)
        if picker is self.family_sheets:
            return self._views_from_sheets(picker, self.family_records)
        records = picker.ticked_records()
        if not records:
            return None, u"Tick at least one view, or use the current view"
        return records, None

    def _views_from_sheets(self, table, records):
        """Ticked sheets, expanded to the taggable views placed on them. A
        view on two ticked sheets is tagged once; a ticked sheet with nothing
        taggable on it is named rather than passed over."""
        if not table.count():
            return None, u"Tick at least one sheet"
        by_key = dict([(record.key, record) for record in records])
        found = [by_key[key] for key in table.view_keys() if key in by_key]
        if not found:
            return None, u"The ticked sheets carry no view this tab can tag"
        empty = table.empty_ticked()
        if empty:
            self.set_status(u"{0} passed over - no view on {1} this tab can tag".format(
                u", ".join([record.number for record in empty][:6]),
                u"it" if len(empty) == 1 else u"them"))
        return found, None

    def _run_click(self, sender, args):
        if self.busy:
            return
        self.collect_settings()
        if self._current_tab() == u"room":
            self._run_rooms()
        else:
            self._run_families()

    def _run_families(self):
        rows = self.table.specs()
        unset = self.table.unset_count()
        if not rows:
            if unset:
                self.set_status(u"Choose a tag family for the rows first - every row is still <None>", True)
            else:
                self.set_status(u"Add families to the table first")
            return
        if unset and not self.confirm(
                u"{0} row{1} still {2} no tag family and will be left untagged. "
                u"Tag the other {3}?".format(unset, u"" if unset == 1 else u"s",
                                            u"has" if unset == 1 else u"have", len(rows))):
            self.set_status(u"Cancelled - nothing was changed")
            return
        picker = self.family_sheets if self._family_source() == u"sheets" else self.family_views
        records, why = self._views_for(picker, False)
        if why:
            self.set_status(why, True)
            return
        self.run_sheets = picker.ticked_records() if picker is self.family_sheets else []
        options = {
            "leader": core.parse_bool(self.settings["leader"]),
            "offset_x": core.parse_float(self.settings["offset_x"], 600),
            "offset_y": core.parse_float(self.settings["offset_y"], 600),
            "elbow": core.parse_bool(self.settings["elbow"]),
            "elbow_mm": core.parse_float(self.settings["elbow_mm"], 300),
            "remove_previous": core.parse_bool(self.settings["remove_previous"]),
            "only_untagged": core.parse_bool(self.settings["only_untagged"]),
            "untangle": core.parse_bool(self.settings["untangle"]),
            "tidy": core.parse_bool(self.settings["tidy"]),
        }
        spec = ops.FamilySpec(rows, records, options)
        self._start(u"family run", lambda uiapp: ops.run_family(uiapp, spec, self.progress, self.confirm))

    def _run_rooms(self):
        source = self._room_source()
        if source is None:
            self.set_status(u"Choose the model holding the rooms")
            return
        picker = self.room_sheets if self._room_list_mode() == u"sheets" else self.room_views
        records, why = self._views_for(picker, True)
        self.run_sheets = picker.ticked_records() if picker is self.room_sheets else []
        if why:
            self.set_status(why, True)
            return
        display, tag_type_id = self._room_tag()
        options = {
            "remove_unassigned": core.parse_bool(self.settings["room_remove_unassigned"]),
            "only_untagged": core.parse_bool(self.settings["room_only_untagged"]),
        }
        spec = ops.RoomSpec(source, tag_type_id, display, records, options)
        if picker is self.room_sheets:
            self.set_status(u"{0} sheet{1} -> {2} plan view{3}".format(
                self.room_sheets.count(), u"" if self.room_sheets.count() == 1 else u"s",
                len(records), u"" if len(records) == 1 else u"s"))
        self._start(u"room run", lambda uiapp: ops.run_room(uiapp, spec, self.progress, self.confirm))

    def _start(self, label, work):
        self.busy = True
        self.save()
        progress = self.find("Progress")
        progress.Value = 0
        self.find("ProgressPercent").Text = u"0%"
        self.find("ProgressPanel").Visibility = Visibility.Visible
        self._update_button()
        self.set_status(u"Waiting for Revit...")
        try:
            self.dispatcher.submit(label, work, self._finished)
        except Exception as error:
            self.busy = False
            self.find("ProgressPanel").Visibility = Visibility.Collapsed
            self._update_button()
            self.set_status(to_text(error), True)

    def progress(self, done, total, text):
        """Called between transactions only - repainting inside one is a
        crash. The bar and its percentage sit in the footer beside Tag All,
        and the status line names the view being tagged."""
        try:
            value = core.percent(done, total)
            self.find("Progress").Value = value
            self.find("ProgressPercent").Text = u"{0}%".format(value)
            self.set_status(text)
            self.window.IsHitTestVisible = False
            ui.pump(self.window)
        except Exception:
            pass

    def confirm(self, message):
        return ui.ask(self.window, u"Tag All", message, self.mode)

    def _finished(self, result, error):
        """The bar stays up at 100% while the Done prompt is open, and comes
        down however this returns."""
        self.busy = False
        self.window.IsHitTestVisible = True
        self._update_button()
        sheets = list(self.run_sheets)
        self.run_sheets = []
        try:
            self._report_run(result, error, sheets)
        finally:
            self.find("ProgressPanel").Visibility = Visibility.Collapsed

    def _report_run(self, result, error, sheets):
        if error:
            self.set_status(u"The run failed - see the log", True)
            ui.show_message(self.window, u"Tag All failed", u"The run threw before it finished. The traceback is in\n{0}\n\n{1}".format(core.log_path(), error[-1200:]), self.mode)
            return
        if result is None:
            self.set_status(u"Done")
            return
        if result.cancelled:
            self.set_status(u"Cancelled - nothing was changed")
            return
        core.log(u"run: {0}; {1} problems; {2} notes".format(result.summary, len(result.problems), len(result.notes)))
        self.set_status(result.summary, bool(result.problems))
        if sheets:
            self.find("Progress").Value = 100
            self.find("ProgressPercent").Text = u"100%"
            if ui.ask(self.window, u"Done", core.open_sheets_prompt(result.summary, len(sheets)), self.mode,
                      yes=u"Open sheet" if len(sheets) == 1 else u"Open sheets", no=u"Not now"):
                self._open_sheets(sheets)
        if core.should_show_results(self.settings.get("show_results"), result.problems):
            ui.Results(self.window, result.summary, result.problems, result.notes, self.mode).show()
        elif result.notes and not result.created and not result.deleted:
            self.set_status(result.notes[0])
        # a link ticked mid-run was deferred rather than dropped
        if self._ticked_link_names() != self.links_loaded:
            self._schedule_links_read()

    def _open_sheets(self, sheets):
        """Open the sheets the run came from. Setting the active view is a
        Revit API call, so it goes through the ExternalEvent like a write."""
        ids = [record.sheet_id for record in sheets]

        def work(uiapp):
            uidoc = uiapp.ActiveUIDocument
            doc = uidoc.Document
            opened = 0
            for sheet_id in ids:
                view = doc.GetElement(sheet_id)
                if view is None:
                    continue
                uidoc.ActiveView = view
                opened += 1
            return opened

        def done(opened, error):
            if error:
                self.set_status(u"Could not open the sheets - see the log", True)
            elif opened:
                self.set_status(u"Opened {0} sheet{1}".format(opened, u"" if opened == 1 else u"s"))
            else:
                self.set_status(u"The sheets no longer exist", True)

        try:
            self.dispatcher.submit(u"open sheets", work, done)
        except Exception as problem:
            self.set_status(to_text(problem), True)

    # ---------- odds and ends ----------

    def set_status(self, text, is_problem=False):
        block = self.find("StatusText")
        block.Text = to_text(text)
        ui.set_brush(block, "Foreground", "RedBrush" if is_problem else "MutedBrush")

    # ---------- the Family Tags groups ----------

    # group -> (header button, body, row) as named in the layout
    GROUP_PARTS = {
        "views": ("ViewsGroupToggle", "ViewsGroupBody", "ViewsGroupRow"),
        "categories": ("CategoriesGroupToggle", "CategoriesGroupBody", "CategoriesGroupRow"),
        "families": ("FamiliesGroupToggle", "FamiliesGroupBody", "FamiliesGroupRow"),
    }
    # the clipping border each body slides in
    GROUP_SLIDES = {"views": "ViewsGroupSlide", "categories": "CategoriesGroupSlide",
                    "families": "FamiliesGroupSlide"}
    # the whole header strip: a click anywhere on it opens or shuts the group
    GROUP_HEADERS = {"views": "ViewsGroupHeader", "categories": "CategoriesGroupHeader",
                     "families": "FamiliesGroupHeader"}

    def _setup_groups(self):
        self.groups_open = dict(core.GROUP_START)
        self.categories_opened_before = False
        self.group_slide = None
        self.groups_fitted = False        # the window shrunk to its group bars
        self.full_height = None           # and the height it goes back to
        self.base_min_height = self.window.MinHeight
        self.main_tab_index = 0
        for group in core.GROUP_ORDER:
            toggle = self.GROUP_PARTS[group][0]
            icon, title = ui.GROUP_FOR[toggle]
            button = self.find(toggle)
            ui.group_toggle(button, icon, title)
            button.Click += self._make_group_click(group)
            # a click anywhere else on the bar does the same; a button on it
            # (the toggle, Remove, Clear) marks its own click handled, so it
            # never reaches here and never toggles twice
            self.find(self.GROUP_HEADERS[group]).MouseLeftButtonUp += self._make_header_click(group)
        self._paint_groups()

    def _make_group_click(self, group):
        def handler(sender, args):
            self._group_clicked(group)
        return ui.ui_safe(self, handler, "open or shut " + group)

    def _window_blocked(self):
        """Full screen or parked on the taskbar: the window's height is not
        the groups' to change."""
        try:
            if self.chrome.is_full():
                return True
            drawer = self.chrome.drawer
            return drawer is not None and (drawer.shrunk or drawer.busy())
        except Exception:
            return True

    def _refit_window(self):
        """Fit or unfit the window at once - after a change of tab, where
        Room Tags always has the full height."""
        fit = core.fit_window(self.groups_open, self._current_tab() == u"family", self._window_blocked())
        if fit == self.groups_fitted:
            return
        if fit:
            self.full_height = float(self.window.ActualHeight)
            self.window.UpdateLayout()
            slack = float(self.find("GroupsFillerRow").ActualHeight)
            height = max(240.0, self.full_height - slack)
            self.window.MinHeight = min(self.base_min_height, height)
            self.window.Height = height
        else:
            self.window.Height = self.full_height or self.window.ActualHeight
            self.window.MinHeight = self.base_min_height
        self.groups_fitted = fit

    def _make_header_click(self, group):
        def handler(sender, args):
            if args.Handled:
                return
            args.Handled = True
            self._group_clicked(group)
        return ui.ui_safe(self, handler, "group header")

    def _group_clicked(self, group):
        self._end_group_slide()          # a slide still running lands first
        before = dict(self.groups_open)
        self.groups_open, self.categories_opened_before = core.toggle_family_group(
            self.groups_open, group, self.categories_opened_before)
        self._slide_groups(before)

    def _slide_groups(self, before):
        """Open and shut groups like a drawer.

        The final layout is laid out once, out of sight, to learn how tall
        each opening group will end up; then every changing group is put back
        where it started as an Auto row and its clipping border is eased from
        the start height to the end one. The body inside is pinned at its
        full height for the slide, so its rows are not re-measured every frame
        and it reads as a drawer drawn out rather than a panel being squashed.
        When it lands the real layout goes back on.
        """
        opening, closing, steady = core.group_changes(before, self.groups_open)
        if not opening and not closing:
            self._paint_groups()
            return
        try:
            starts = {}
            pins = {}
            for group in closing:
                starts[group] = float(self.find(self.GROUP_SLIDES[group]).ActualHeight)
                pins[group] = float(self.find(self.GROUP_PARTS[group][1]).ActualHeight)
            fit_after = core.fit_window(self.groups_open, self._current_tab() == u"family", self._window_blocked())
            window_start = float(self.window.ActualHeight)
            refit = fit_after != self.groups_fitted
            if refit and fit_after:
                self.full_height = window_start
            elif refit:
                # laid out at the height it is going back to, to measure there
                self.window.Height = self.full_height or window_start
            self._paint_groups()
            self.window.UpdateLayout()
            window_end = None
            if refit and fit_after:
                slack = float(self.find("GroupsFillerRow").ActualHeight)
                window_end = max(240.0, window_start - slack)
                self.window.MinHeight = min(self.base_min_height, window_end)
            elif refit:
                window_end = float(self.window.Height)
                self.window.Height = window_start
            self.groups_fitted = fit_after
            ends = {}
            for group in opening:
                ends[group] = float(self.find(self.GROUP_SLIDES[group]).ActualHeight)
                pins[group] = float(self.find(self.GROUP_PARTS[group][1]).ActualHeight)
                starts[group] = 0.0
            for group in closing:
                ends[group] = 0.0
            for group in opening + closing:
                _toggle, body, row = self.GROUP_PARTS[group]
                self.find(row).Height = GridLength.Auto
                body_part = self.find(body)
                body_part.Visibility = Visibility.Visible
                body_part.Height = pins[group]
                body_part.VerticalAlignment = VerticalAlignment.Top
                self.find(self.GROUP_SLIDES[group]).Height = starts[group]
            # nothing open throughout to take up the slack: the filler does
            self.find("GroupsFillerRow").Height = GridLength(0) if steady else star(1)
            slide = {"started": ui.PLATFORM.now(), "starts": starts, "ends": ends, "timer": None,
                     "window": (window_start, window_end) if window_end is not None else None}
            self.group_slide = slide
            slide["timer"] = ui.PLATFORM.timer(core.DRAWER_TICK_MS, self._group_tick)
        except Exception:
            core.log(u"group slide failed, laying out at once:\n{0}".format(traceback.format_exc()))
            self._end_group_slide()

    def _group_tick(self, timer):
        slide = self.group_slide
        if slide is None:
            try:
                timer.Stop()
            except Exception:
                pass
            return
        try:
            progress = (ui.PLATFORM.now() - slide["started"]) / float(core.GROUP_SLIDE_MS)
            for group, start in slide["starts"].items():
                self.find(self.GROUP_SLIDES[group]).Height = core.slide_height(start, slide["ends"][group], progress)
            if slide["window"] is not None:
                self.window.Height = core.slide_height(slide["window"][0], slide["window"][1], progress)
            if progress >= 1.0:
                self._end_group_slide()
        except Exception:
            core.log(u"group slide tick failed:\n{0}".format(traceback.format_exc()))
            self._end_group_slide()

    def _end_group_slide(self):
        """Land any slide: stop its timer, unpin every body and border, and put
        the real layout back on. Safe to call with nothing sliding."""
        slide = self.group_slide
        self.group_slide = None
        if slide is None:
            return
        try:
            if slide["timer"] is not None:
                slide["timer"].Stop()
        except Exception:
            pass
        for group in core.GROUP_ORDER:
            try:
                body = self.find(self.GROUP_PARTS[group][1])
                body.Height = Double.NaN
                body.VerticalAlignment = VerticalAlignment.Stretch
                self.find(self.GROUP_SLIDES[group]).Height = Double.NaN
            except Exception:
                pass
        if slide["window"] is not None:
            try:
                self.window.Height = slide["window"][1]
                if not self.groups_fitted:
                    self.window.MinHeight = self.base_min_height
            except Exception:
                pass
        self._paint_groups()

    def _paint_groups(self):
        heights, filler = core.group_heights(self.groups_open)
        for group, height in zip(core.GROUP_ORDER, heights):
            toggle, body, row = self.GROUP_PARTS[group]
            is_open = bool(self.groups_open.get(group))
            self.find(row).Height = star(1) if height == u"star" else GridLength.Auto
            self.find(body).Visibility = Visibility.Visible if is_open else Visibility.Collapsed
            button = self.find(toggle)
            ui.set_group_open(button, is_open)
            try:
                button.ToolTip = u"Collapse" if is_open else u"Expand"
            except Exception:
                pass
        self.find("GroupsFillerRow").Height = star(1) if filler == u"star" else GridLength(0)

    def _key(self, sender, args):
        try:
            from System.Windows.Input import Key
            if args.Key == Key.F5:
                self._refresh_tree(sender, args)
                args.Handled = True
        except Exception:
            pass

    def _close_click(self, sender, args):
        if self.busy:
            self.set_status(u"A run is in progress - wait for it to finish")
            return
        self.window.Close()

    def _closed(self, sender, args):
        self.closed = True
        self.save()

    def show(self):
        self.window.Show()


def open_window(uiapp, owner_handle=None):
    """Build, park and show the window. Parked at module level because the
    persistent engine collects anything it cannot reach."""
    global WINDOW, DISPATCHER
    if WINDOW is not None:
        try:
            if not WINDOW.closed:
                WINDOW.window.Activate()
                return WINDOW
        except Exception:
            pass
    if DISPATCHER is None:
        DISPATCHER = ops.Dispatcher()
    settings = core.load_settings()
    WINDOW = TagAllWindow(uiapp, settings, DISPATCHER, owner_handle)
    WINDOW.show()
    return WINDOW
