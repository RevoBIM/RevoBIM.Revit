# -*- coding: utf-8 -*-
"""Number Sequencer - the Tag in views list.

Every floor plan, section and 3D view in the project (no templates), with a
Type column and two group columns whose values come
from view parameters chosen in the column headings (View Group 1 / 2). Each
column filters on what is typed under its heading and sorts when its heading
is clicked. Ticked views get tags on the numbered elements they show when
Apply / Run tags; with nothing ticked the active view is tagged as before.
Find views with this system narrows the list to the views showing the
selected system(s). Sheets: selecting a sheet (Ctrl / Shift for several)
narrows the list to the views placed on it and ticks them; a sheet's own
tick box ticks or unticks its views; double-click opens the sheet.
"""

import nsq_clr  # noqa: F401  (must stay the first import)

import traceback

from System.Windows import Thickness, GridLength, GridUnitType, VerticalAlignment, HorizontalAlignment, TextTrimming
from System.Windows.Controls import (Grid, TextBlock, CheckBox, ColumnDefinition, TextBox,
                                     ComboBox, ComboBoxItem, StackPanel, Border, Button, Control,
                                     ScrollViewer, WrapPanel, ScrollBarVisibility)
from System.Windows.Controls.Primitives import Popup, PlacementMode, Thumb
from System.Windows import CornerRadius, FrameworkElement, FontWeights, Size
from System.Windows.Input import Cursors, Keyboard, ModifierKeys

import nsq_core as core
import nsq_revit as rv
import nsq_ui as ui

SEP = u"||"

# key, heading, width, star, min width - heading, filter row and rows share it
COLUMNS = [
    (u"tick", u"", 26, False, 0),
    (u"name", u"View", 3, True, 90),
    (u"kind", u"Type", 1.3, True, 62),
    (u"g1", u"View Group 1", 2, True, 70),
    (u"g2", u"View Group 2", 2, True, 70),
]


class TagViewsPanel(object):

    def __init__(self, w):
        self.w = w
        self.ctl = w.ctl
        self.rows = []
        self.params = []
        self.only = None
        self.only_label = u""
        self.sort = (u"name", False)
        self.filters = {u"name": u"", u"kind": u"", u"g1": u"", u"g2": u""}
        # Excel-style value lists: {col: values unticked}. Everything ticked = no filter.
        self.excluded = {u"name": set(), u"kind": set(), u"g1": set(), u"g2": set()}
        self.excluded[u"kind"] = set([k for k in (w.settings.get(u"view_kinds_off") or u"").split(SEP) if k])
        self.kind_boxes = {}
        self.funnels = {}
        self.popups = {}
        self.filter_boxes = []
        self.ticked = set([u for u in (w.settings.get(u"tag_views") or u"").split(SEP) if u])
        # as saved: blank = never chosen (a default is found), NONE_MARK = (none) chosen
        self.saved = [w.settings.get(u"view_g1") or u"", w.settings.get(u"view_g2") or u""]
        self.groups = [u"", u""]
        self.doc_key = None
        self.combos = []
        self.sort_labels = {}
        self.filling = False
        # sheets: [{uid, eid, number, name, views (id values listed here), placed}]
        self.sheets = []
        self.sheet_sel = set()
        self.sheet_anchor = None
        self.sheet_rows = []    # (sheet, row, tick box) as shown
        self.sheet_undo = None  # the state before the last sheet click, for a double-click
        # sheet columns: Number fits the longest number until dragged; Views is draggable too
        self.sheet_num_w = None
        self.sheet_views_w = 74.0
        self.sheet_grids = []
        self._build_head()
        g = w._guard
        self.ctl(u"TagViewFindBtn").Click += g(self._on_find)
        self.ctl(u"TagViewAllBtn").Click += g(self._on_all)
        self.ctl(u"TagViewTickBtn").Click += g(self._on_tick_shown)
        self.ctl(u"TagViewUntickBtn").Click += g(self._on_untick_all)
        self.ctl(u"TagViewClearFiltersBtn").Click += g(self._on_clear_filters)
        self.ctl(u"TagSheetSearch").TextChanged += g(self._on_sheet_search)
        # 6.2: sheets and views in tabs, the last one used opens
        tab = self.ctl(u"TagTabViews" if w.settings.get(u"tag_tab") == u"views" else u"TagTabSheets")
        tab.IsChecked = True
        self._show_tag_tab()
        self.ctl(u"TagTabSheets").Checked += g(self._on_tag_tab)
        self.ctl(u"TagTabViews").Checked += g(self._on_tag_tab)
        self.ctl(u"TagSheetClearBtn").Click += g(self._on_sheet_clear)
        for name, kind in ((u"TagKindPlan", u"Floor plan"), (u"TagKindSection", u"Section"), (u"TagKind3D", u"3D")):
            box = self.ctl(name)
            self.kind_boxes[kind] = box
            box.Click += g(self._kind_click(kind, box))
        self._sync_kinds()

    # ---------------------------------------------------- reading
    def _read_job(self):
        groups = list(self.saved)

        def job(uiapp):
            doc = uiapp.ActiveUIDocument.Document
            plans = rv.tag_views(doc)
            names = rv.view_param_names(plans)
            g1 = core.default_group_param(names, groups[0], 0)
            g2 = core.default_group_param(names, groups[1], 1)
            rows, names = rv.view_table(doc, g1, g2)
            sheets = rv.sheet_table(doc, [r[u"id"] for r in rows])
            return {u"rows": rows, u"params": names, u"groups": [g1, g2], u"doc_key": rv.doc_key(doc),
                    u"sheets": sheets}
        return job

    def load_now(self, uiapp):
        """At launch, inside the command."""
        try:
            self._loaded(self._read_job()(uiapp), None)
        except Exception:
            self.w.log.add(u"views read failed: " + traceback.format_exc())

    def refresh(self):
        self.w.runner.queue(u"read views", self._read_job(), self._loaded)

    def _loaded(self, res, err):
        if err or res is None:
            self.w._status(u"Could not read the views - see debug")
            return
        self.rows = res[u"rows"]
        self.params = res[u"params"]
        self.groups = res[u"groups"]
        self.doc_key = res[u"doc_key"]
        # ticks of other projects' views stay in the saved list untouched
        self.w.log.add(u"views: {0} plans / sections / 3D, groups {1!r} / {2!r}".format(
            len(self.rows), self.groups[0], self.groups[1]))
        self.sheets = res.get(u"sheets") or []
        self.sheet_num_w = None   # fit the longest number of these sheets
        here = set([sh[u"uid"] for sh in self.sheets])
        self.sheet_sel = set([u for u in self.sheet_sel if u in here])
        self._fill_combos()
        if self.sheet_sel:
            self.only = core.sheet_views(self.sheets, self.sheet_sel)
        self.build()
        self.build_sheets()

    # ---------------------------------------------------- heading
    def _columns(self, grid):
        for key, head, width, star, minw in COLUMNS:
            cd = ColumnDefinition()
            if star:
                cd.Width = GridLength(width, getattr(GridUnitType, u"Star"))
                cd.MinWidth = minw
            else:
                cd.Width = GridLength(width)
            grid.ColumnDefinitions.Add(cd)

    def _sort_label(self, col, text):
        tb = TextBlock()
        tb.Text = text
        tb.FontSize = 11
        tb.Margin = Thickness(4, 0, 4, 0)
        tb.Cursor = Cursors.Hand
        tb.VerticalAlignment = getattr(VerticalAlignment, u"Center")
        tb.ToolTip = u"Click to sort"
        tb.SetResourceReference(TextBlock.ForegroundProperty, u"Muted")
        tb.MouseLeftButtonUp += self.w._guard(self._sort_click(col))
        self.sort_labels[col] = (tb, text)
        return tb

    def _cell(self, parts):
        """A heading cell: parts laid out left to right, a star part fills."""
        cell = Grid()
        for i, (el, star) in enumerate(parts):
            cd = ColumnDefinition()
            cd.Width = GridLength(1, getattr(GridUnitType, u"Star")) if star else GridLength.Auto
            cell.ColumnDefinitions.Add(cd)
            if el is not None:
                Grid.SetColumn(el, i)
                cell.Children.Add(el)
        return cell

    def _build_head(self):
        """Row 1: View (sort, value list) | sort, parameter, value list for
        group 1 | the same for group 2. Row 2: a text filter under each."""
        outer = StackPanel()
        top = Grid()
        self._columns(top)
        cell = self._cell([(self._sort_label(u"name", u"View"), False), (None, True), (self._funnel(u"name"), False)])
        Grid.SetColumn(cell, 1)
        top.Children.Add(cell)
        cell = self._cell([(self._sort_label(u"kind", u"Type"), False), (None, True), (self._funnel(u"kind"), False)])
        Grid.SetColumn(cell, 2)
        top.Children.Add(cell)
        self.combos = []
        for n, col in ((0, u"g1"), (1, u"g2")):
            combo = ComboBox()
            combo.Height = 24
            combo.FontSize = 11
            combo.Margin = Thickness(0, 0, 2, 0)
            combo.ToolTip = u"View Group {0}: the view parameter shown in this column".format(n + 1)
            combo.SelectionChanged += self.w._guard(self._group_changed(n))
            cell = self._cell([(self._sort_label(col, u"Sort"), False), (combo, True), (self._funnel(col), False)])
            Grid.SetColumn(cell, 3 + n)
            top.Children.Add(cell)
            self.combos.append(combo)
        # the drop-downs live in the heading's tree, so they find the theme
        for col in (u"name", u"kind", u"g1", u"g2"):
            top.Children.Add(self.popups[col])
        outer.Children.Add(top)
        filt = Grid()
        filt.Margin = Thickness(0, 4, 0, 0)
        self._columns(filt)
        self.filter_boxes = []
        for i, col in ((1, u"name"), (2, u"kind"), (3, u"g1"), (4, u"g2")):
            box = TextBox()
            box.Tag = u"Filter"
            box.Height = 24
            box.FontSize = 11
            box.Padding = Thickness(4, 2, 4, 2)
            box.Margin = Thickness(0, 0, 4, 0)
            box.TextChanged += self.w._guard(self._filter_changed(col, box))
            Grid.SetColumn(box, i)
            filt.Children.Add(box)
            self.filter_boxes.append(box)
        outer.Children.Add(filt)
        self.ctl(u"TagViewHead").Child = outer
        self._paint_sort()
        self._paint_funnels()

    # ---------------------------------------------------- Excel-style value lists
    def _funnel(self, col):
        btn = Button()
        btn.SetResourceReference(FrameworkElement.StyleProperty, u"ChromeButton")
        btn.Width = 22
        btn.Height = 22
        btn.Content = ui.icon(u"filter", 12)
        btn.ToolTip = u"Pick the values to show in this column"
        btn.Click += self.w._guard(self._open_values(col))
        pop = Popup()
        pop.PlacementTarget = btn
        pop.Placement = getattr(PlacementMode, u"Bottom")
        pop.StaysOpen = False
        pop.AllowsTransparency = True
        self.funnels[col] = btn
        self.popups[col] = pop
        return btn

    def _paint_funnels(self):
        """A column with values unticked shows its funnel in orange."""
        for col, btn in self.funnels.items():
            if self.excluded[col]:
                btn.SetResourceReference(Control.ForegroundProperty, u"Orange")
                btn.ToolTip = u"{0} value(s) hidden - click to change".format(len(self.excluded[col]))
            else:
                btn.ClearValue(Control.ForegroundProperty)
                btn.ToolTip = u"Pick the values to show in this column"

    def _open_values(self, col):
        def handler(sender, e):
            pop = self.popups[col]
            card = Border()
            card.SetResourceReference(Border.BackgroundProperty, u"Card")
            card.SetResourceReference(Border.BorderBrushProperty, u"Blue")
            card.BorderThickness = Thickness(1)
            card.CornerRadius = CornerRadius(4)
            card.Padding = Thickness(8)
            card.MinWidth = 230
            card.Margin = Thickness(0, 2, 0, 0)
            sp = StackPanel()
            search = TextBox()
            search.Tag = u"Search values"
            search.Height = 26
            search.FontSize = 11
            search.Margin = Thickness(0, 0, 0, 6)
            sp.Children.Add(search)
            bar = WrapPanel()
            bar.Margin = Thickness(0, 0, 0, 6)
            all_btn = Button()
            all_btn.SetResourceReference(FrameworkElement.StyleProperty, u"ChipButton")
            ui.set_button(all_btn, u"tick", u"Select all")
            none_btn = Button()
            none_btn.SetResourceReference(FrameworkElement.StyleProperty, u"ChipButton")
            ui.set_button(none_btn, u"untick", u"Clear all")
            bar.Children.Add(all_btn)
            bar.Children.Add(none_btn)
            sp.Children.Add(bar)
            host = StackPanel()
            sv = ScrollViewer()
            sv.MaxHeight = 280
            sv.VerticalScrollBarVisibility = getattr(ScrollBarVisibility, u"Auto")
            sv.Content = host
            sp.Children.Add(sv)
            note = TextBlock()
            note.FontSize = 11
            note.Margin = Thickness(0, 6, 0, 0)
            note.SetResourceReference(TextBlock.ForegroundProperty, u"Muted")
            note.Text = u"Everything ticked = no filter"
            sp.Children.Add(note)
            card.Child = sp
            shown = []

            def tick(val, cb):
                def h(s2, e2):
                    if cb.IsChecked == True:  # noqa: E712
                        self.excluded[col].discard(val)
                    else:
                        self.excluded[col].add(val)
                    self._values_changed()
                return h

            def fill(text):
                host.Children.Clear()
                del shown[:]
                values = core.column_values(self.rows, col, self.filters, self.excluded, self.only)
                for val, count in values:
                    label = val or u"(blank)"
                    if not core.matches(label, text):
                        continue
                    shown.append(val)
                    cb = CheckBox()
                    cb.Content = u"{0}  ({1})".format(label, count)
                    cb.IsChecked = val not in self.excluded[col]
                    cb.Margin = Thickness(0, 2, 0, 2)
                    cb.Click += self.w._guard(tick(val, cb))
                    host.Children.Add(cb)
                if not shown:
                    tb = TextBlock()
                    tb.Text = u"No values"
                    tb.SetResourceReference(TextBlock.ForegroundProperty, u"Muted")
                    host.Children.Add(tb)

            def set_all(on):
                def h(s2, e2):
                    self.excluded[col] = core.tick_values(self.excluded[col], list(shown), on)
                    self._values_changed()
                    fill(search.Text or u"")
                return h

            search.TextChanged += self.w._guard(lambda s2, e2: fill(search.Text or u""))
            all_btn.Click += self.w._guard(set_all(True))
            none_btn.Click += self.w._guard(set_all(False))
            fill(u"")
            pop.Child = card
            pop.IsOpen = True
            try:
                search.Focus()
            except Exception:
                pass
        return handler

    def _values_changed(self):
        self._paint_funnels()
        self._sync_kinds()
        self.build()

    # ---------------------------------------------------- view types: all on or any one on its own
    def _sync_kinds(self):
        """The Show tick boxes and the Type column's value list are one filter."""
        for kind, box in self.kind_boxes.items():
            box.IsChecked = kind not in self.excluded[u"kind"]
        self.w.settings[u"view_kinds_off"] = SEP.join(sorted(self.excluded[u"kind"]))

    def _kind_click(self, kind, box):
        def handler(sender, e):
            if box.IsChecked == True:  # noqa: E712
                self.excluded[u"kind"].discard(kind)
            else:
                self.excluded[u"kind"].add(kind)
            self.w._save()
            self._values_changed()
        return handler

    def _on_clear_filters(self, sender, e):
        for col in self.excluded:
            self.excluded[col] = set()
        for box in self.filter_boxes:
            box.Text = u""   # each box's TextChanged clears its text filter
        self._values_changed()

    def _fill_combos(self):
        self.filling = True
        try:
            for n, combo in enumerate(self.combos):
                combo.Items.Clear()
                none = ComboBoxItem()
                none.Content = u"(none)"
                none.Tag = u""
                combo.Items.Add(none)
                pick = none
                for name in self.params:
                    item = ComboBoxItem()
                    item.Content = name
                    item.Tag = name
                    combo.Items.Add(item)
                    if name == self.groups[n]:
                        pick = item
                combo.SelectedItem = pick
        finally:
            self.filling = False

    def _group_changed(self, n):
        def handler(sender, e):
            if self.filling:
                return
            item = self.combos[n].SelectedItem
            value = u"{0}".format(item.Tag) if item is not None and item.Tag is not None else u""
            if value == self.groups[n]:
                return
            self.saved[n] = value or core.NONE_MARK
            self.w.settings[u"view_g{0}".format(n + 1)] = self.saved[n]
            self.w._save()
            self.refresh()
        return handler

    def _filter_changed(self, col, box):
        def handler(sender, e):
            self.filters[col] = box.Text or u""
            self.build()
        return handler

    def _sort_click(self, col):
        def handler(sender, e):
            current, desc = self.sort
            self.sort = (col, (not desc) if current == col else False)
            self._paint_sort()
            self.build()
        return handler

    def _paint_sort(self):
        col, desc = self.sort
        for key, (tb, text) in self.sort_labels.items():
            if key == col:
                tb.Text = text + (u" v" if desc else u" ^")
                tb.SetResourceReference(TextBlock.ForegroundProperty, u"Orange")
            else:
                tb.Text = text
                tb.SetResourceReference(TextBlock.ForegroundProperty, u"Muted")

    # ---------------------------------------------------- rows
    def shown(self):
        return core.view_rows(self.rows, self.filters, self.sort[0], self.sort[1], self.only, self.excluded)

    def build(self):
        host = self.ctl(u"TagViewRows")
        host.Children.Clear()
        rows = self.shown()
        if not self.rows:
            tb = TextBlock()
            tb.Text = u"No floor plans, sections or 3D views in the project"
            tb.Margin = Thickness(6)
            tb.SetResourceReference(TextBlock.ForegroundProperty, u"Muted")
            host.Children.Add(tb)
        for r in rows:
            grid = Grid()
            self._columns(grid)
            grid.Margin = Thickness(0, 1, 0, 1)
            grid.Background = ui.brush(u"#00000000")
            grid.Cursor = Cursors.Hand
            cb = CheckBox()
            cb.IsChecked = r[u"uid"] in self.ticked
            cb.HorizontalAlignment = getattr(HorizontalAlignment, u"Center")
            cb.Click += self.w._guard(self._tick(r, cb))
            Grid.SetColumn(cb, 0)
            grid.Children.Add(cb)
            for i, key in ((1, u"name"), (2, u"kind"), (3, u"g1"), (4, u"g2")):
                tb = TextBlock()
                tb.Text = (r.get(u"kind_text") or r.get(key) or u"") if key == u"kind" else (r.get(key) or u"")
                tb.ToolTip = (r.get(key) or u"") + (u"  ({0})".format(r[u"level"]) if key == u"name" and r[u"level"] else u"")
                tb.Margin = Thickness(4, 2, 6, 2)
                tb.TextTrimming = getattr(TextTrimming, u"CharacterEllipsis")
                tb.VerticalAlignment = getattr(VerticalAlignment, u"Center")
                tb.SetResourceReference(TextBlock.ForegroundProperty, u"Text" if key == u"name" else u"Muted")
                Grid.SetColumn(tb, i)
                grid.Children.Add(tb)
            grid.MouseLeftButtonUp += self.w._guard(self._row_click(r, cb))
            host.Children.Add(grid)
        self._count(len(rows))

    def _count(self, shown):
        ticked = self.ticked_count()
        text = u"{0} ticked  |  {1} of {2} views".format(ticked, shown, len(self.rows))
        if self.only is not None:
            text += u"  |  " + self.only_label
        hidden = sum([len(v) for v in self.excluded.values()])
        if hidden or any([t.strip() for t in self.filters.values()]):
            text += u"  |  filtered"
        self.ctl(u"TagViewCount").Text = text
        self._paint_sheets()
        self._paint_tabs()
        self.w._refresh_tag_note(self.w._plan()[0])

    def _tick(self, r, cb):
        def handler(sender, e):
            if cb.IsChecked == True:  # noqa: E712
                self.ticked.add(r[u"uid"])
            else:
                self.ticked.discard(r[u"uid"])
            self._save()
            self._count(len(self.shown()))
        return handler

    def _row_click(self, r, cb):
        def handler(sender, e):
            if e.ClickCount == 2:
                # the first click of the double-click toggled the tick: put it back
                cb.IsChecked = not (cb.IsChecked == True)  # noqa: E712
                self._tick(r, cb)(sender, e)
                self._open(r)
                return
            if isinstance(e.OriginalSource, CheckBox):
                return
            cb.IsChecked = not (cb.IsChecked == True)  # noqa: E712
            self._tick(r, cb)(sender, e)
        return handler

    def _open(self, r):
        """Double-click a view: open it in Revit."""
        def job(uiapp):
            view = uiapp.ActiveUIDocument.Document.GetElement(r[u"eid"])
            if view is not None:
                uiapp.ActiveUIDocument.RequestViewChange(view)
            return True
        def done(res, err):
            self.w._status(u"Could not open {0} - see debug".format(r[u"name"]) if err else
                           u"Opened {0}".format(r[u"name"]))

        self.w.runner.queue(u"open view", job, done)

    def _save(self):
        self.w.settings[u"tag_views"] = SEP.join(sorted(self.ticked))
        self.w._save()

    def ticked_ids(self):
        """ElementIds of the ticked views, for the tag step."""
        return [r[u"eid"] for r in self.rows if r[u"uid"] in self.ticked]

    def ticked_count(self):
        return len([r for r in self.rows if r[u"uid"] in self.ticked])

    # ---------------------------------------------------- buttons
    def _on_tick_shown(self, sender, e):
        for r in self.shown():
            self.ticked.add(r[u"uid"])
        self._save()
        self.build()

    def _on_untick_all(self, sender, e):
        here = set([r[u"uid"] for r in self.rows])
        self.ticked = set([u for u in self.ticked if u not in here])   # other projects keep theirs
        self._save()
        self.build()

    def _on_all(self, sender, e):
        self.only = None
        self.only_label = u""
        self.sheet_sel = set()
        self.refresh()

    def _on_find(self, sender, e):
        """Narrow the list to the views that show the selected system(s)."""
        keys, label = self.w._find_keys()
        if not keys:
            self.w._status(u"Select a system first")
            return
        view_ids = [r[u"eid"] for r in self.rows]

        def job(uiapp):
            return rv.views_showing(uiapp.ActiveUIDocument.Document, view_ids, keys)

        def done(found, err):
            if err or found is None:
                self.w._status(u"Could not search the views - see debug")
                return
            self.only = found
            self.only_label = u"showing " + label
            self.sheet_sel = set()   # the newest narrowing wins
            self.build()
            self.build_sheets()
            self.w._status(u"{0} view(s) show {1}".format(len(found), label))

        self.w._queue(u"find views", job, done, u"Looking for the views that show " + label)

    # ---------------------------------------------------- the Sheets | Views tabs
    def _show_tag_tab(self):
        views = self.ctl(u"TagTabViews").IsChecked == True  # noqa: E712
        ui.show(self.ctl(u"TagViewsPanel"), views)
        ui.show(self.ctl(u"TagSheetsPanel"), not views)
        return views

    def _on_tag_tab(self, sender, e):
        views = self._show_tag_tab()
        self.w.settings[u"tag_tab"] = u"views" if views else u"sheets"
        self.w._save()

    def _paint_tabs(self):
        """The tab labels carry the counts: sheets selected, views ticked."""
        try:
            n = self.ticked_count()
            ui.set_button(self.ctl(u"TagTabViews"), u"show", u"Views ({0} ticked)".format(n) if n else u"Views")
            k = len(self.sheet_sel)
            ui.set_button(self.ctl(u"TagTabSheets"), u"sheet", u"Sheets ({0} selected)".format(k) if k else u"Sheets")
        except Exception:
            pass

    # ---------------------------------------------------- sheets
    def ticked_ids_here(self):
        """Id values of the ticked views of this project."""
        return set([r[u"id"] for r in self.rows if r[u"uid"] in self.ticked])

    # ---------------------------------------------------- sheet columns
    def _fit_number(self, sheets):
        """Number column wide enough for the longest number (bold, as shown)."""
        widest = 40.0
        tb = TextBlock()
        tb.FontWeight = FontWeights.SemiBold
        for sh in sheets:
            tb.Text = sh[u"number"] or u""
            tb.Measure(Size(float(u"inf"), float(u"inf")))
            widest = max(widest, tb.DesiredSize.Width)
        return widest + 14.0   # the cell margins and a little air

    def _sheet_columns(self, grid):
        for w_, star in ((26, False), (self.sheet_num_w, False), (1, True), (self.sheet_views_w, False)):
            cd = ColumnDefinition()
            cd.Width = GridLength(w_, getattr(GridUnitType, u"Star")) if star else GridLength(w_)
            if star:
                cd.MinWidth = 60
            grid.ColumnDefinitions.Add(cd)
        self.sheet_grids.append(grid)

    def _resize_sheet_columns(self):
        for g in self.sheet_grids:
            try:
                g.ColumnDefinitions[1].Width = GridLength(self.sheet_num_w)
                g.ColumnDefinitions[3].Width = GridLength(self.sheet_views_w)
            except Exception:
                pass

    def _edge(self, which):
        """A drag handle on a heading edge: Number's right, Views' left."""
        th = Thumb()
        th.Width = 7
        th.Cursor = getattr(Cursors, u"SizeWE")
        th.SetResourceReference(FrameworkElement.StyleProperty, u"Grip")
        th.ToolTip = u"Drag to size the column"

        def drag(sender, e):
            if which == u"num":
                self.sheet_num_w = max(36.0, self.sheet_num_w + e.HorizontalChange)
            else:
                self.sheet_views_w = max(44.0, self.sheet_views_w - e.HorizontalChange)
            self._resize_sheet_columns()
        th.DragDelta += self.w._guard(drag)
        return th

    def _build_sheet_head(self):
        grid = Grid()
        self._sheet_columns(grid)
        for col, text in ((1, u"Number"), (2, u"Name"), (3, u"Views")):
            tb = TextBlock()
            tb.Text = text
            tb.FontSize = 11
            tb.FontWeight = FontWeights.SemiBold
            tb.Margin = Thickness(4, 0, 6, 0)
            tb.VerticalAlignment = getattr(VerticalAlignment, u"Center")
            tb.SetResourceReference(TextBlock.ForegroundProperty, u"Muted")
            Grid.SetColumn(tb, col)
            grid.Children.Add(tb)
        num = self._edge(u"num")
        num.HorizontalAlignment = getattr(HorizontalAlignment, u"Right")
        Grid.SetColumn(num, 1)
        grid.Children.Add(num)
        views = self._edge(u"views")
        views.HorizontalAlignment = getattr(HorizontalAlignment, u"Left")
        Grid.SetColumn(views, 3)
        grid.Children.Add(views)
        self.ctl(u"TagSheetHead").Child = grid

    def build_sheets(self):
        host = self.ctl(u"TagSheetRows")
        host.Children.Clear()
        self.sheet_rows = []
        self.sheet_grids = []
        if self.sheet_num_w is None and self.sheets:
            self.sheet_num_w = self._fit_number(self.sheets)
        if self.sheet_num_w is None:
            self.sheet_num_w = 96.0
        self._build_sheet_head()
        shown = core.sheet_rows(self.sheets, self.ctl(u"TagSheetSearch").Text)
        if not shown:
            tb = TextBlock()
            tb.Text = u"No sheets match" if self.sheets else u"No sheets in the project"
            tb.Margin = Thickness(6)
            tb.SetResourceReference(TextBlock.ForegroundProperty, u"Muted")
            host.Children.Add(tb)
            return
        for idx, sh in enumerate(shown):
            grid = Grid()
            self._sheet_columns(grid)
            row = Border()
            row.CornerRadius = CornerRadius(3)
            row.Padding = Thickness(0, 1, 0, 1)
            row.Margin = Thickness(0, 0, 0, 1)
            row.Cursor = Cursors.Hand
            row.Child = grid
            cb = CheckBox()
            cb.HorizontalAlignment = getattr(HorizontalAlignment, u"Center")
            cb.VerticalAlignment = getattr(VerticalAlignment, u"Center")
            cb.ToolTip = u"Tick or untick every listed view on this sheet"
            cb.Click += self.w._guard(self._sheet_tick(sh))
            Grid.SetColumn(cb, 0)
            grid.Children.Add(cb)
            listed = len(sh[u"views"])
            for col, text, key in ((1, sh[u"number"], u"Text"), (2, sh[u"name"], u"Text"),
                                   (3, u"{0} view{1}".format(listed, u"" if listed == 1 else u"s"), u"Muted")):
                tb = TextBlock()
                tb.Text = text
                tb.Margin = Thickness(4, 2, 6, 2)
                tb.TextTrimming = getattr(TextTrimming, u"CharacterEllipsis")
                tb.VerticalAlignment = getattr(VerticalAlignment, u"Center")
                tb.SetResourceReference(TextBlock.ForegroundProperty, key)
                if col == 1:
                    tb.FontWeight = FontWeights.SemiBold
                Grid.SetColumn(tb, col)
                grid.Children.Add(tb)
            row.ToolTip = u"{0} - {1}: {2} of its {3} views can take tags here.  Click: find and tick them.  " \
                          u"Ctrl / Shift + click: several sheets.  Double-click: open the sheet.".format(
                              sh[u"number"], sh[u"name"], listed, sh[u"placed"])
            row.MouseLeftButtonUp += self.w._guard(self._sheet_click(idx, sh))
            host.Children.Add(row)
            self.sheet_rows.append((sh, row, cb))
        self._paint_sheets()

    def _paint_sheets(self):
        self._paint_tabs()
        ticked = self.ticked_ids_here()
        for sh, row, cb in self.sheet_rows:
            if sh[u"uid"] in self.sheet_sel:
                row.SetResourceReference(Border.BackgroundProperty, u"Sel")
            else:
                row.Background = ui.brush(u"#00000000")
            cb.IsChecked = core.sheet_state(sh, ticked)
            cb.IsEnabled = bool(sh[u"views"])

    def _sheet_click(self, idx, sh):
        def handler(sender, e):
            if isinstance(e.OriginalSource, CheckBox):
                return
            if e.ClickCount == 2:
                # the first click of the double-click selected and ticked: put it back
                if self.sheet_undo is not None:
                    self.sheet_sel, self.sheet_anchor, self.ticked, self.only, self.only_label = self.sheet_undo
                    self.sheet_undo = None
                    self._save()
                    self.build()
                self._open_sheet(sh)
                return
            self.sheet_undo = (set(self.sheet_sel), self.sheet_anchor, set(self.ticked), self.only, self.only_label)
            m = Keyboard.Modifiers
            ctrl = (m & getattr(ModifierKeys, u"Control")) == getattr(ModifierKeys, u"Control")
            shift = (m & getattr(ModifierKeys, u"Shift")) == getattr(ModifierKeys, u"Shift")
            shown = [r[0] for r in self.sheet_rows]
            now = set([i for i, x in enumerate(shown) if x[u"uid"] in self.sheet_sel])
            anchor = None
            for i, x in enumerate(shown):
                if x[u"uid"] == self.sheet_anchor:
                    anchor = i
            if ctrl and idx in now and len(now) == 1:
                new, anchor = set(), None   # Ctrl+click the only selected sheet: none
            else:
                new, anchor = core.click_selection(now, anchor, idx, ctrl, shift)
            # selections hidden by the search stay selected
            hidden = set([u for u in self.sheet_sel if u not in set([x[u"uid"] for x in shown])])
            self.sheet_sel = hidden | set([shown[i][u"uid"] for i in new])
            self.sheet_anchor = shown[anchor][u"uid"] if anchor is not None else None
            self._apply_sheets()
        return handler

    def _apply_sheets(self):
        """The views on the selected sheets: the list narrows to them and they
        are ticked for tagging."""
        if not self.sheet_sel:
            self.only = None
            self.only_label = u""
            self.build()
            self._paint_sheets()
            self.w._status(u"No sheet selected - every view shown")
            return
        ids = core.sheet_views(self.sheets, self.sheet_sel)
        added = 0
        for r in self.rows:
            if r[u"id"] in ids and r[u"uid"] not in self.ticked:
                self.ticked.add(r[u"uid"])
                added += 1
        chosen = [sh for sh in self.sheets if sh[u"uid"] in self.sheet_sel]
        label = chosen[0][u"number"] if len(chosen) == 1 else u"{0} sheets".format(len(chosen))
        self.only = ids
        self.only_label = u"on " + label
        self._save()
        self.build()
        self._paint_sheets()
        self.w._status(u"{0} view(s) on {1} to tag{2}".format(
            len(ids), label, u" - {0} newly ticked".format(added) if added else u", all ticked already"))

    def _sheet_tick(self, sh):
        def handler(sender, e):
            ticked = self.ticked_ids_here()
            on = core.sheet_state(sh, ticked) is not True   # partly or not ticked -> tick all
            uids = set([r[u"uid"] for r in self.rows if r[u"id"] in set(sh[u"views"])])
            if on:
                self.ticked |= uids
            else:
                self.ticked -= uids
            self._save()
            self.build()
            self.w._status(u"{0}: {1} view(s) {2}".format(sh[u"number"], len(uids), u"ticked" if on else u"unticked"))
        return handler

    def _open_sheet(self, sh):
        def job(uiapp):
            view = uiapp.ActiveUIDocument.Document.GetElement(sh[u"eid"])
            if view is not None:
                uiapp.ActiveUIDocument.RequestViewChange(view)
            return True

        def done(res, err):
            self.w._status(u"Could not open {0} - see debug".format(sh[u"number"]) if err else
                           u"Opened sheet {0}".format(sh[u"number"]))

        self.w.runner.queue(u"open sheet", job, done)

    def _on_sheet_search(self, sender, e):
        self.build_sheets()

    def _on_sheet_clear(self, sender, e):
        self.sheet_sel = set()
        self.sheet_anchor = None
        self.ctl(u"TagSheetSearch").Text = u""
        self._apply_sheets()
