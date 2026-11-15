# -*- coding: utf-8 -*-
"""The category / family / type tree.

Every node is built as a real WPF element in code rather than bound to a Python
object - binding WPF to IronPython attributes is unreliable across engine
versions, and building the items here is also what makes lazy expansion and
tri-state ticking straightforward.
"""

import snte_clr  # noqa: F401  - must be first

from System.Windows import Thickness, VerticalAlignment, Visibility
from System.Windows.Controls import TreeViewItem, CheckBox, TextBlock, \
    Grid, ColumnDefinition

import snte_core as core

DUMMY = "__dummy__"


def _brush(element, key):
    try:
        return element.FindResource(key)
    except Exception:
        return None


class TreeBuilder(object):
    """Owns the TreeView and keeps it in step with the data nodes."""

    def __init__(self, tree_view, empty_label, on_change):
        self.tree = tree_view
        self.empty_label = empty_label
        self.on_change = on_change
        self.cat_nodes = []
        self._map = {}
        self._updating = False

    # -- building -----------------------------------------------------
    def set_nodes(self, cat_nodes):
        self.cat_nodes = cat_nodes
        self.rebuild("")

    def rebuild(self, keyword):
        """Filter on all three levels, and open each branch only as far as the
        level the keyword actually matched.

        A hit on the category name shows that category collapsed - the match is
        already visible. A hit further down opens the branch until the matching
        family, or the matching type, is on screen.
        """
        keyword = (keyword or "").strip().lower()
        self._updating = True
        try:
            self.tree.Items.Clear()
            self._map = {}      # realised items are gone, so their entries go too
            shown = 0
            for cnode in self.cat_nodes:
                if keyword and not cnode.match(keyword):
                    continue
                own = (not keyword) or (keyword in cnode.name.lower())
                item = self._make_item(cnode, "cat", lazy=own)
                if not own:
                    # matched below the category, so build the matching part of
                    # the branch now and open it
                    self._add_children(item, cnode, "cat", keyword, False)
                    item.IsExpanded = True
                self.tree.Items.Add(item)
                shown += 1
        finally:
            self._updating = False
        if self.empty_label is not None:
            self.empty_label.Visibility = \
                Visibility.Visible if shown == 0 else Visibility.Collapsed

    def _add_children(self, item, node, kind, keyword, ancestor_matched):
        """Children that match, built eagerly. ancestor_matched means a name
        further up already matched, so everything below it belongs."""
        if kind == "cat":
            for child in node.family_list:
                own = ancestor_matched or (keyword in child.name.lower())
                if not own and not child.match(keyword):
                    continue
                sub = self._make_item(child, "fam", lazy=own)
                if not own:
                    self._add_children(sub, child, "fam", keyword, False)
                    sub.IsExpanded = True
                item.Items.Add(sub)
        elif kind == "fam":
            for child in node.type_list:
                if not ancestor_matched and not child.match(keyword):
                    continue
                item.Items.Add(self._make_item(child, "type", lazy=False))

    def _make_item(self, node, kind, lazy=True):
        item = TreeViewItem()
        item.Header = self._make_header(node, kind, item)
        item.IsExpanded = False

        if kind in ("cat", "fam") and lazy:
            item.Items.Add(DUMMY)          # realised on first expand
            item.Expanded += self._expanded
        return item

    def _make_header(self, node, kind, item):
        grid = Grid()
        grid.ColumnDefinitions.Add(ColumnDefinition())
        col = ColumnDefinition()
        col.Width = _auto()
        grid.ColumnDefinitions.Add(col)

        check = CheckBox()
        check.Content = node.name
        check.IsThreeState = (kind != "type")
        check.VerticalAlignment = VerticalAlignment.Center
        check.Margin = Thickness(0, 0, 8, 0)
        try:
            check.Style = self.tree.FindResource("DarkCheck")
        except Exception:
            pass
        if kind == "cat":
            check.FontWeight = _semibold()
        state = node.state()
        check.IsChecked = state if state is not None else None
        check.Tag = item
        check.Checked += self._toggled
        check.Unchecked += self._toggled
        check.Indeterminate += self._toggled
        Grid.SetColumn(check, 0)
        grid.Children.Add(check)

        count = TextBlock()
        count.Text = "{0}".format(node.count)
        count.FontSize = 11
        count.VerticalAlignment = VerticalAlignment.Center
        count.Margin = Thickness(0, 0, 6, 0)
        brush = _brush(self.tree, "DimBrush")
        if brush is not None:
            count.Foreground = brush
        Grid.SetColumn(count, 1)
        grid.Children.Add(count)

        # a plain dictionary keyed by the item id keeps the WPF objects free of
        # Python attributes WPF might otherwise be asked to read
        self._map[id(item)] = {"node": node, "kind": kind, "check": check,
                               "item": item}
        return grid

    def _info(self, item):
        return self._map.get(id(item))

    # -- lazy expansion -----------------------------------------------
    def _expanded(self, sender, args):
        item = sender
        if item.Items.Count != 1:
            return
        if item.Items[0] != DUMMY:
            return
        info = self._info(item)
        if info is None:
            return
        node = info["node"]
        kind = info["kind"]

        self._updating = True
        try:
            item.Items.Clear()
            if kind == "cat":
                for child in node.family_list:
                    item.Items.Add(self._make_item(child, "fam", lazy=True))
            elif kind == "fam":
                for child in node.type_list:
                    item.Items.Add(self._make_item(child, "type", lazy=False))
        finally:
            self._updating = False
        args.Handled = True

    # -- ticking ------------------------------------------------------
    def _toggled(self, sender, args):
        if self._updating:
            return
        item = sender.Tag
        info = self._info(item) if item is not None else None
        if info is None:
            return
        node = info["node"]

        value = sender.IsChecked
        if value is None:
            # a user click never lands on indeterminate: that state is only
            # ever set from code, so treat a click through it as "tick all"
            value = True
            self._updating = True
            try:
                sender.IsChecked = True
            finally:
                self._updating = False

        node.set_state(bool(value))
        self.refresh_states()
        if self.on_change is not None:
            self.on_change()

    def refresh_states(self):
        """Push the data model's state back onto whichever checkboxes exist."""
        self._updating = True
        try:
            for entry in self._map.values():
                node = entry["node"]
                check = entry["check"]
                try:
                    state = node.state()
                    check.IsChecked = state if state is not None else None
                except Exception:
                    continue
        finally:
            self._updating = False

    # -- bulk ---------------------------------------------------------
    def set_visible(self, value, keyword):
        """All / None act on exactly what the search is showing, using the same
        matching rule the tree was built with."""
        keyword = (keyword or "").strip().lower()
        for cnode in self.cat_nodes:
            if not keyword:
                cnode.set_state(value)
                continue
            if not cnode.match(keyword):
                continue
            if keyword in cnode.name.lower():
                cnode.set_state(value)
                continue
            for fnode in cnode.families.values():
                if keyword in fnode.name.lower():
                    fnode.set_state(value)
                    continue
                for tnode in fnode.types.values():
                    if tnode.match(keyword):
                        tnode.set_state(value)
        self.refresh_states()
        if self.on_change is not None:
            self.on_change()

    def restore_selection(self, names):
        """Re-tick categories by name after a refresh."""
        wanted = set([n.lower() for n in (names or [])])
        if not wanted:
            return
        for cnode in self.cat_nodes:
            if cnode.name.lower() in wanted:
                cnode.set_state(True)
        self.refresh_states()


# ---------------------------------------------------------------------------
#  little helpers kept out of the class
# ---------------------------------------------------------------------------
def _auto():
    from System.Windows import GridLength, GridUnitType
    return GridLength(1, GridUnitType.Auto)


def _semibold():
    from System.Windows import FontWeights
    return FontWeights.SemiBold
