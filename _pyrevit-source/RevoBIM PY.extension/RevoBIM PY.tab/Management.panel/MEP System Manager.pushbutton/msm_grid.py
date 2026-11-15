# -*- coding: utf-8 -*-
"""One Expander per service type, each holding its own grid with its own
sort and its own column filters.

The grid is bound to a DataTable rather than to Python objects - WPF cannot
be relied on to see IronPython attributes. The rows are rebuilt from the
filtered, sorted list every time something changes: nothing here is edited
in place, so there is no row to slide out from under a cursor.
"""
import msm_clr  # noqa: F401  - assemblies first

from System import TimeSpan
from System.Data import DataTable
from System.Windows import (Thickness, HorizontalAlignment, VerticalAlignment,
                            Visibility, FontWeights, CornerRadius, UIElement,
                            TextTrimming)
from System.Windows.Documents import Run, TextElement
from System.Windows.Controls import (Expander, DataGrid, DataGridTextColumn,
                                     DataGridLength, DataGridLengthUnitType,
                                     StackPanel, DockPanel, TextBlock, TextBox,
                                     Button, CheckBox, ScrollViewer, Border,
                                     Orientation, Dock, ScrollBarVisibility,
                                     ItemsControl)
from System.Windows.Controls.Primitives import Popup, PlacementMode
from System.Windows.Data import Binding
from System.Windows.Input import Keyboard, ModifierKeys, MouseWheelEventArgs
from System.Windows.Shapes import Path
from System.Windows.Media import Geometry
from System.Windows.Threading import DispatcherTimer

import msm_core as core

COLUMN_MIN = {u"system": 140, u"ptype": 160, u"size": 90, u"count": 76, u"length": 90,
              u"fittings": 84, u"check": 190,
              u"workset": 220, u"elements": 84, u"new_workset": 160, u"system_type": 170}
COLUMN_STAR = {u"system": 2.0, u"ptype": 2.4, u"size": 1.0, u"count": 0.8, u"length": 1.0,
               u"fittings": 0.8, u"check": 3.0,
               u"workset": 3.0, u"elements": 0.8, u"new_workset": 2.0, u"system_type": 2.0}
SORT_COLOURS = (u"Orange", u"Blue", u"Green")


def ctrl_held():
    try:
        return (Keyboard.Modifiers & ModifierKeys.Control) == ModifierKeys.Control
    except Exception:
        return False


def res(element, prop, key):
    try:
        element.SetResourceReference(prop, key)
    except Exception:
        pass


def text_block(text, key=u"Text", size=None, bold=False):
    block = TextBlock()
    block.Text = text
    res(block, TextBlock.ForegroundProperty, key)
    block.VerticalAlignment = VerticalAlignment.Center
    if size:
        block.FontSize = size
    if bold:
        block.FontWeight = FontWeights.SemiBold
    return block


class GroupSection(object):
    """A service type: header, grid, sort stack, column filters."""

    def __init__(self, host, name, rows, expanded, fields=None, note=u"", sort=None,
                 note_colour=u"Blue", note_parts=None, title=None, accent=None):
        self.host = host                  # the main window controller
        self.name = name
        self.title = title or name       # what the heading shows; name is the key
        self.accent = accent             # a System No fold's own colour (TypeN brush)
        self.fields = tuple(fields or core.FIELDS)
        self.note = note
        self.note_colour = note_colour
        self.note_parts = note_parts or []
        self.outer = None                 # the discipline expander, on the workset tab
        self.rows = rows
        self.sort_stack = list(sort or core.default_sort(None))
        self.col_keywords = {}
        self.col_ticks = {}
        self.visible_rows = []
        self.header_labels = {}
        self.header_frames = {}
        self.carets = {}
        self.filter_boxes = {}
        self.popup = None
        self.timer = None
        self.suspend = False

        self.table = DataTable(u"rows")
        # flag drives the red wash on a row that needs a look (Theme.xaml)
        # flag drives the red wash, pend the orange one for a staged change
        for field in self.fields + (u"key", u"flag", u"pend", u"mixed", u"tcol"):
            self.table.Columns.Add(field)

        self.grid = DataGrid()
        self.grid.Margin = Thickness(0, 2, 6, 4)
        self.grid.VerticalScrollBarVisibility = ScrollBarVisibility.Disabled
        self.grid.HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled
        self.grid.ItemsSource = self.table.DefaultView
        self.grid.Sorting += self.on_sorting
        self.grid.SelectionChanged += self.on_selection
        self.grid.PreviewMouseWheel += self.on_wheel
        self.grid.MouseDoubleClick += self.on_double
        for field in self.fields:
            self.grid.Columns.Add(self.make_column(field))

        self.expander = Expander()
        self.expander.Header = self.make_header()
        self.expander.Content = self.grid
        self.expander.IsExpanded = expanded
        self.expander.Expanded += lambda s, a: self.host.on_expand_changed()
        self.expander.Collapsed += lambda s, a: self.host.on_expand_changed()
        self.refresh()

    # ---------------- building ----------------

    def make_header(self):
        panel = DockPanel()
        panel.LastChildFill = True
        panel.MinWidth = 600

        # docked right in turn, so Select none sits at the far right with
        # Select all beside it
        select_none = Button()
        select_none.Content = u"Select none"
        select_none.Padding = Thickness(10, 1, 10, 1)
        select_none.MinHeight = 24
        select_none.FontSize = 11.5
        select_none.Margin = Thickness(6, 0, 0, 0)
        select_none.ToolTip = u"Clear the selection in this group - the other groups keep theirs"
        select_none.Click += lambda s, a: self.select_none()
        DockPanel.SetDock(select_none, Dock.Right)
        panel.Children.Add(select_none)

        select_all = Button()
        select_all.Content = u"Select all"
        select_all.Padding = Thickness(10, 1, 10, 1)
        select_all.MinHeight = 24
        select_all.FontSize = 11.5
        select_all.ToolTip = (u"Select every row shown in this group - the other groups are "
                              u"cleared; hold Ctrl to add this group to them")
        select_all.Click += lambda s, a: self.select_all()
        DockPanel.SetDock(select_all, Dock.Right)
        panel.Children.Add(select_all)

        self.count_text = text_block(u"", u"Muted", 11.5)
        self.count_text.Margin = Thickness(0, 0, 12, 0)
        DockPanel.SetDock(self.count_text, Dock.Right)
        panel.Children.Add(self.count_text)

        if self.note_parts:
            note = TextBlock()
            note.FontSize = 11.5
            note.FontWeight = FontWeights.SemiBold
            note.VerticalAlignment = VerticalAlignment.Center
            for text, colour in self.note_parts:
                run = Run(text)
                res(run, TextElement.ForegroundProperty,
                    u"Type{0}".format(colour) if colour is not None else u"Muted")
                note.Inlines.Add(run)
            note.Margin = Thickness(0, 0, 12, 0)
            note.MaxWidth = 560
            note.TextTrimming = TextTrimming.CharacterEllipsis
            note.ToolTip = self.note
            DockPanel.SetDock(note, Dock.Right)
            panel.Children.Add(note)
            self.note_text = note
        elif self.note:
            note = text_block(self.note, self.note_colour, 11.5, True)
            note.Margin = Thickness(0, 0, 12, 0)
            note.MaxWidth = 560
            note.TextTrimming = TextTrimming.CharacterEllipsis
            note.ToolTip = self.note
            DockPanel.SetDock(note, Dock.Right)
            panel.Children.Add(note)
            self.note_text = note

        self.flag_text = text_block(u"", u"Red", 11.5, True)
        self.flag_text.Margin = Thickness(0, 0, 12, 0)
        DockPanel.SetDock(self.flag_text, Dock.Right)
        panel.Children.Add(self.flag_text)

        tick = Border()
        tick.Width = 4
        tick.Height = 16
        tick.CornerRadius = CornerRadius(2)
        tick.Margin = Thickness(0, 0, 8, 0)
        res(tick, Border.BackgroundProperty, u"Orange")
        DockPanel.SetDock(tick, Dock.Left)
        panel.Children.Add(tick)

        if self.accent:
            bar = Border()
            bar.Width = 5
            bar.Height = 18
            bar.CornerRadius = CornerRadius(2)
            bar.Margin = Thickness(0, 0, 8, 0)
            bar.VerticalAlignment = VerticalAlignment.Center
            res(bar, Border.BackgroundProperty, self.accent)
            panel.Children.Add(bar)
        title = text_block(self.title, self.accent or u"Text", 13.5, True)
        panel.Children.Add(title)
        return panel

    def make_column(self, field):
        column = DataGridTextColumn()
        column.Binding = Binding(field)
        column.SortMemberPath = field
        column.Width = DataGridLength(COLUMN_STAR[field], DataGridLengthUnitType.Star)
        column.MinWidth = COLUMN_MIN[field]
        column.CanUserSort = True
        column.Header = self.make_column_header(field)
        if field == u"check":
            style = self.host.window.TryFindResource(u"CellTextRed")
            if style is not None:
                column.ElementStyle = style
            if not self.host.checks_on():
                column.Visibility = Visibility.Collapsed
        if field == u"workset":
            style = self.host.window.TryFindResource(u"CellMixed")
            if style is not None:
                column.CellStyle = style
        if field == u"ptype":
            style = self.host.window.TryFindResource(u"CellTypeColour")
            if style is not None:
                column.CellStyle = style
        return column

    def make_column_header(self, field):
        outer = StackPanel()
        outer.Orientation = Orientation.Vertical
        # the box round a sorted heading: always there, only its colour
        # changes, so lighting it cannot nudge the layout
        frame = Border()
        frame.BorderThickness = Thickness(1.5)
        frame.CornerRadius = CornerRadius(3)
        frame.Padding = Thickness(4, 2, 4, 3)
        frame.Child = outer
        self.header_frames[field] = frame

        top = DockPanel()
        caret = Button()
        caret.Style = self.host.window.TryFindResource(u"BtnCaret")
        caret.ToolTip = u"Tick the values to show"
        glyph = Path()
        glyph.Data = Geometry.Parse(u"M0,0 L4,4 L8,0")
        glyph.StrokeThickness = 1.5
        res(glyph, Path.StrokeProperty, u"Muted")
        caret.Content = glyph
        caret.Click += lambda s, a, f=field: self.open_ticks(f, s)
        DockPanel.SetDock(caret, Dock.Right)
        top.Children.Add(caret)
        self.carets[field] = (caret, glyph)

        label = text_block(self.host.field_titles()[field], u"Muted", 12, True)
        top.Children.Add(label)
        self.header_labels[field] = label
        outer.Children.Add(top)

        box = TextBox()
        box.Tag = u"filter"
        box.MinHeight = 26
        box.Height = 26
        box.FontSize = 11.5
        box.Margin = Thickness(0, 3, 0, 0)
        box.TextChanged += lambda s, a, f=field: self.on_keyword(f, s)
        outer.Children.Add(box)
        self.filter_boxes[field] = box
        return frame

    # ---------------- filtering and sorting ----------------

    def global_text(self):
        return self.host.global_search()

    def refresh(self):
        """Filter, sort, rebuild the rows, keep whatever was selected."""
        keep = set(self.selected_keys())
        self.suspend = True
        try:
            passing = core.filter_rows(self.rows, self.col_keywords,
                                       self.col_ticks, self.global_text())
            passing = core.only_flagged(passing, self.host.issues_only())
            self.visible_rows = core.sort_rows(passing, self.sort_stack)
            self.table.Rows.Clear()
            for row in self.visible_rows:
                data = self.table.NewRow()
                for field in self.fields:
                    data[field] = core.cell_text(row, field)
                data[u"key"] = row[u"key"]
                data[u"pend"] = u"1" if row.get(u"pend") else u""
                data[u"mixed"] = u"1" if row.get(u"mixed") else u""
                colour = self.host.type_colours().get(row.get(u"ptype"))
                data[u"tcol"] = u"{0}".format(colour) if colour is not None else u""
                data[u"flag"] = u"1" if row.get(u"flag") else u""
                self.table.Rows.Add(data)
            self.grid.SelectedItems.Clear()
            if keep:
                for item in self.grid.Items:
                    try:
                        if item[u"key"] in keep:
                            self.grid.SelectedItems.Add(item)
                    except Exception:
                        pass
        finally:
            self.suspend = False
        self.paint_headers()
        self.update_counts()
        self.update_flags()
        has_rows = len(self.visible_rows) > 0
        hidden_by_search = (bool(self.global_text()) or self.host.issues_only()) \
            and not has_rows
        self.expander.Visibility = (Visibility.Collapsed if hidden_by_search
                                    else Visibility.Visible)

    def update_counts(self):
        pipes = sum([r[u"count"] for r in self.visible_rows])
        total = sum([r[u"count"] for r in self.rows])
        systems = set()
        for r in self.visible_rows:
            if r.get(u"system") and not r[u"system"].endswith(u"systems"):
                systems.add(r[u"system"])
        if len(self.visible_rows) == len(self.rows):
            self.count_text.Text = u"{0} rows \u00b7 {1} {2}".format(
                len(self.rows), total, self.host.noun(total))
        else:
            self.count_text.Text = u"{0} of {1} rows \u00b7 {2} of {3} {4}".format(
                len(self.visible_rows), len(self.rows), pipes, total, self.host.noun(total))

    def update_flags(self):
        flagged = len([r for r in self.rows if r.get(u"flag")])
        self.flag_text.Text = (u"" if not flagged else
                               u"{0} row{1} need{2} a look".format(
                                   flagged, u"" if flagged == 1 else u"s",
                                   u"s" if flagged == 1 else u""))

    def header_text(self, field):
        """(the heading's text, its colour key or None) - shared with the
        frozen headings so the two always read the same."""
        place = core.sort_place(self.sort_stack, field)
        title = self.host.field_titles()[field]
        if place is None:
            return title, None
        arrow = u"\u25bc" if place[1] else u"\u25b2"
        if len(self.sort_stack) > 1:
            return u"{0} {1}{2}".format(title, place[0] + 1, arrow), \
                SORT_COLOURS[min(place[0], len(SORT_COLOURS) - 1)]
        return u"{0} {1}".format(title, arrow), SORT_COLOURS[0]

    def sort_by(self, field, add_level):
        """Sort by a column, as clicking its heading does."""
        self.sort_stack = core.toggle_sort(self.sort_stack, field, add_level)
        self.refresh()

    def paint_headers(self):
        for field, label in self.header_labels.items():
            place = core.sort_place(self.sort_stack, field)
            title = self.host.field_titles()[field]
            frame = self.header_frames.get(field)
            if frame is not None:
                if place is None:
                    frame.ClearValue(Border.BorderBrushProperty)
                else:
                    res(frame, Border.BorderBrushProperty,
                        SORT_COLOURS[min(place[0], len(SORT_COLOURS) - 1)])
            if place is None:
                label.Text = title
                res(label, TextBlock.ForegroundProperty, u"Muted")
            else:
                arrow = u"\u25bc" if place[1] else u"\u25b2"
                if len(self.sort_stack) > 1:
                    label.Text = u"{0} {1}{2}".format(title, place[0] + 1, arrow)
                else:
                    label.Text = u"{0} {1}".format(title, arrow)
                res(label, TextBlock.ForegroundProperty,
                    SORT_COLOURS[min(place[0], len(SORT_COLOURS) - 1)])
            caret, glyph = self.carets[field]
            filtered = self.col_ticks.get(field) is not None
            res(glyph, Path.StrokeProperty, u"Orange" if filtered else u"Muted")
            glyph.StrokeThickness = 2.2 if filtered else 1.5

    def on_sorting(self, sender, args):
        """Take the sort over: the DataGrid's own would fight the rebuild."""
        args.Handled = True
        try:
            field = args.Column.SortMemberPath
            shift = (Keyboard.Modifiers & ModifierKeys.Shift) == ModifierKeys.Shift
            self.sort_by(field, shift)
            self.host.update_sticky(force=True)
        except Exception:
            self.host.report_error(u"Sorting")

    def on_keyword(self, field, box):
        self.col_keywords[field] = box.Text
        self.debounce()

    def debounce(self):
        if self.timer is None:
            self.timer = DispatcherTimer()
            self.timer.Interval = TimeSpan.FromMilliseconds(220)
            self.timer.Tick += self.on_timer
        self.timer.Stop()
        self.timer.Start()

    def on_timer(self, sender, args):
        self.timer.Stop()
        try:
            self.refresh()
            self.host.on_selection_changed()
        except Exception:
            self.host.report_error(u"Filtering")

    # ---------------- tick list ----------------

    def open_ticks(self, field, anchor):
        try:
            values = core.tick_values(self.rows, field, self.col_keywords,
                                      self.col_ticks, self.global_text())
            allowed = self.col_ticks.get(field)
            self.popup = TickPopup(self, field, values, allowed, anchor)
        except Exception:
            self.host.report_error(u"Opening the filter list")

    def apply_ticks(self, field, values, ticked):
        self.col_ticks[field] = core.ticks_to_filter(values, ticked)
        self.refresh()
        self.host.on_selection_changed()

    # ---------------- selection ----------------

    def selected_keys(self):
        out = []
        try:
            for item in self.grid.SelectedItems:
                try:
                    out.append(item[u"key"])
                except Exception:
                    pass
        except Exception:
            pass
        return out

    def selected_rows(self):
        keys = set(self.selected_keys())
        return [r for r in self.visible_rows if r[u"key"] in keys]

    def select_all(self):
        """Every row of this group; the other groups' selection goes unless
        Ctrl is held, which adds this group to it."""
        if not ctrl_held():
            self.host.keep_only(self)
        try:
            self.expander.IsExpanded = True
            self.suspend = True
            self.grid.SelectAll()
        except Exception:
            pass
        finally:
            self.suspend = False
        self.host.on_selection_changed()

    def select_none(self):
        self.clear_selection()
        self.host.on_selection_changed()

    def state(self):
        ticks = {}
        for field, allowed in self.col_ticks.items():
            ticks[field] = None if allowed is None else set(allowed)
        return {u"sort": list(self.sort_stack), u"keywords": dict(self.col_keywords),
                u"ticks": ticks}

    def apply_state(self, sort_stack, keywords, ticks):
        """Put back a sort and filters saved before a refresh."""
        if sort_stack:
            self.sort_stack = list(sort_stack)
        self.col_keywords = dict(keywords or {})
        self.col_ticks = dict(ticks or {})
        for field, box in self.filter_boxes.items():
            text = self.col_keywords.get(field, u"") or u""
            if box.Text != text:
                box.Text = text
        self.refresh()

    def select_keys(self, keys):
        """Select the rows with these keys; returns how many were found."""
        keys = set(keys)
        found = 0
        self.suspend = True
        try:
            self.grid.SelectedItems.Clear()
            for item in self.grid.Items:
                try:
                    if item[u"key"] in keys:
                        self.grid.SelectedItems.Add(item)
                        found += 1
                except Exception:
                    pass
        finally:
            self.suspend = False
        return found

    def clear_selection(self):
        try:
            self.suspend = True
            self.grid.UnselectAll()
        finally:
            self.suspend = False

    def on_selection(self, sender, args):
        """A click that selects rows here clears every other group, as a
        plain click does in Windows; Ctrl keeps them. Selections the tool
        makes itself (Pick System, a refresh, Assign) run with suspend set and
        never come through here."""
        if self.suspend:
            return
        try:
            added = args.AddedItems.Count > 0
        except Exception:
            added = False
        if added and not ctrl_held():
            self.host.keep_only(self)
        self.host.on_selection_changed()

    def on_double(self, sender, args):
        """Double-click a row to isolate it."""
        if self.host.busy:
            return
        try:
            # only a double-click on a row - not on a heading or its filter box
            if ItemsControl.ContainerFromElement(self.grid, args.OriginalSource) is None:
                return
            self.host.isolate()
        except Exception:
            self.host.report_error(u"Isolate")

    def on_wheel(self, sender, args):
        """The grid sits in the page's scroll viewer and has no scrolling of
        its own; hand the wheel on so the page scrolls over a grid too."""
        try:
            args.Handled = True
            forwarded = MouseWheelEventArgs(args.MouseDevice, args.Timestamp, args.Delta)
            forwarded.RoutedEvent = UIElement.MouseWheelEvent
            forwarded.Source = sender
            self.host.body_scroll.RaiseEvent(forwarded)
        except Exception:
            pass


class TickPopup(object):
    """Excel-style tick list: search, All / None, the values, OK."""

    def __init__(self, section, field, values, allowed, anchor):
        self.section = section
        self.field = field
        self.values = values
        self.boxes = []

        popup = Popup()
        popup.PlacementTarget = anchor
        popup.Placement = PlacementMode.Bottom
        popup.StaysOpen = False
        popup.AllowsTransparency = True
        self.popup = popup

        border = Border()
        border.BorderThickness = Thickness(1)
        border.Padding = Thickness(8)
        border.MinWidth = 230
        res(border, Border.BackgroundProperty, u"Card")
        res(border, Border.BorderBrushProperty, u"Edge")

        panel = StackPanel()
        search = TextBox()
        search.Tag = u"Search values..."
        search.Margin = Thickness(0, 0, 0, 6)
        search.TextChanged += lambda s, a: self.on_search(s.Text)
        panel.Children.Add(search)

        buttons = StackPanel()
        buttons.Orientation = Orientation.Horizontal
        buttons.Margin = Thickness(0, 0, 0, 6)
        for caption, state in ((u"All", True), (u"None", False)):
            b = Button()
            b.Content = caption
            b.MinHeight = 24
            b.Padding = Thickness(10, 1, 10, 1)
            b.Margin = Thickness(0, 0, 6, 0)
            b.Click += lambda s, a, st=state: self.set_all(st)
            buttons.Children.Add(b)
        panel.Children.Add(buttons)

        scroll = ScrollViewer()
        scroll.MaxHeight = 260
        scroll.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
        items = StackPanel()
        for value in values:
            box = CheckBox()
            box.Content = value if value else u"(blank)"
            box.Tag = value
            box.Margin = Thickness(0, 2, 0, 2)
            box.IsChecked = allowed is None or value in allowed
            items.Children.Add(box)
            self.boxes.append(box)
        scroll.Content = items
        panel.Children.Add(scroll)

        footer = StackPanel()
        footer.Orientation = Orientation.Horizontal
        footer.HorizontalAlignment = HorizontalAlignment.Right
        footer.Margin = Thickness(0, 8, 0, 0)
        ok = Button()
        ok.Content = u"OK"
        ok.Style = section.host.window.TryFindResource(u"BtnGreen")
        ok.Click += lambda s, a: self.on_ok()
        footer.Children.Add(ok)
        panel.Children.Add(footer)

        border.Child = panel
        popup.Child = border
        # parented inside the window, so the theme's implicit styles and the
        # palette brushes reach it - a free-floating Popup sees neither
        self.layer = section.host.popup_layer()
        if self.layer is not None:
            self.layer.Children.Add(popup)
        popup.Closed += self.on_closed
        popup.IsOpen = True
        search.Focus()

    def on_closed(self, sender, args):
        try:
            if self.layer is not None:
                self.layer.Children.Remove(self.popup)
        except Exception:
            pass

    def on_search(self, text):
        for box in self.boxes:
            match = core.keyword_match(u"{0}".format(box.Tag or u""), text)
            box.Visibility = Visibility.Visible if match else Visibility.Collapsed

    def set_all(self, state):
        for box in self.boxes:
            if box.Visibility == Visibility.Visible:
                box.IsChecked = state

    def on_ok(self):
        ticked = [box.Tag for box in self.boxes if box.IsChecked]
        self.popup.IsOpen = False
        self.section.apply_ticks(self.field, self.values, ticked)
