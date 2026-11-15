# -*- coding: utf-8 -*-
"""Family Viewer - batch rename.

Its own window over the picked rows, carrying the same columns the main window
is showing: the name, and every parameter column added there.  Find and
replace, add prefix and add suffix run over **the cells that are picked** -
click one, ctrl click to add more, shift click for a run down a column - so one
window can rename types and re-stamp a parameter without doing both to
everything.

Every cell previews what it would become before anything is staged.  A name
that clashes with another in the same family, clashes with another row in the
batch, or would come out blank, is flagged red on its own cell rather than
failing halfway through.

Apply here does NOT write to the model.  It hands the new values back to the
main window as staged changes, picked out in green, and Apply there is still
the only thing that writes.
"""

import fv_clr  # noqa: F401  - must be first

from System import Object
from System.Collections.Generic import List
from System.Windows import (
    Clipboard, DataTemplate, FrameworkElement, FrameworkElementFactory,
    FontWeights, HorizontalAlignment, TextTrimming, Thickness,
    VerticalAlignment, Visibility,
)
from System.Windows.Controls import (
    Border, DataGridCell, DataGridCellInfo, DataGridLength,
    DataGridLengthUnitType, DataGridRow, DataGridTemplateColumn, Grid,
    TextBlock, TextBox,
)
from System.Windows.Input import Cursors, ModifierKeys, Keyboard
from System.Windows.Data import Binding, IValueConverter
from System.Windows.Input import Key

import re

import fv_core
import fv_ui

NAME_KEY = '__name__'


def _ancestor_with_fill_tag(element):
    """The little square carries its key in its Tag, so a press on it can be
    told apart from a press anywhere else in the cell."""
    return fv_ui.ancestor(element, tag_prefix='fill|', depth=48)


def _ancestor_of_type(element, wanted):
    return fv_ui.ancestor(element, wanted=wanted, depth=48)


OK = 'ok'
UNCHANGED = 'unchanged'
CLASH = 'clash'
BLANK = 'blank'


LOCKED = 'locked'


class Line(object):
    """One picked row: what each column holds now, and what it would become.

    A family line is in the list for GROUPING - so a bank of types reads under
    the family it belongs to - and only its name can be edited.  A type line
    carries the type name and every editable parameter.  Anything that lives on
    the instance rather than the type is shown and locked, because writing it
    from here would mean writing it to every instance behind the row without
    saying so.
    """

    __slots__ = ('kind', 'element_id', 'family', 'values', 'new', 'state',
                 'note', 'typed', 'editable')

    def __init__(self, kind, element_id, family, values, editable=None):
        self.editable = set(editable if editable is not None else values.keys())
        self.kind = kind                  # 'type' or 'family'
        self.element_id = element_id
        self.family = family
        self.values = dict(values)        # column key -> what it holds now
        self.new = dict(values)           # column key -> what it would become
        self.state = {}                   # column key -> OK / CLASH / ...
        self.note = {}                    # column key -> why not
        # a value typed straight into the cell, the way a spreadsheet works.
        # It wins over the tools, and survives them being retyped.
        self.typed = {}

    def can_edit(self, key):
        return key in self.editable

    def old_of(self, key):
        return self.values.get(key, '')

    def new_of(self, key):
        return self.new.get(key, '')

    def state_of(self, key):
        return self.state.get(key, UNCHANGED)

    def changes(self):
        """The cells that would actually be staged.  A locked cell can never
        be one, however it was edited."""
        return [key for key in self.new
                if self.state_of(key) == OK and self.can_edit(key)]


# ---------------------------------------------------------------------------
# the tools
# ---------------------------------------------------------------------------

def apply_tools(old, find, replace, prefix, suffix, match_case):
    """Find and replace first, then the prefix, then the suffix.

    One order, stated on the window, rather than three tools whose result
    depends on which box was filled in first.
    """
    text = old or ''
    if find:
        if match_case:
            text = text.replace(find, replace or '')
        else:
            text = _replace_blind(text, find, replace or '')
    if prefix:
        text = prefix + text
    if suffix:
        text = text + suffix
    return text


def _replace_blind(text, find, replace):
    """Case-blind replace that keeps everything it is not replacing exactly as
    it was - str.replace cannot do it and lower() would flatten the rest."""
    if not find:
        return text
    out = []
    lower_text = text.lower()
    lower_find = find.lower()
    index = 0
    while True:
        found = lower_text.find(lower_find, index)
        if found < 0:
            out.append(text[index:])
            break
        out.append(text[index:found])
        out.append(replace)
        index = found + len(lower_find)
    return ''.join(out)


def split_number(text):
    """("BGL_Door_", "01", 2) for "BGL_Door_01" - the stem, the number at the
    end and how many digits it was written with, so filling down keeps the
    leading zeros.  (text, None, 0) where there is no number to count on."""
    match = re.search(r'(\d+)\s*$', text or '')
    if match is None:
        return (text or ''), None, 0
    digits = match.group(1)
    return (text or '')[:match.start(1)], int(digits), len(digits)


def fill_values(start, count):
    """What a fill downwards from one cell puts in the cells under it.

    A value ending in a number counts on from it, keeping the width it was
    written with; anything else repeats.  That is what a spreadsheet does and
    it is what makes the handle worth having.
    """
    stem, number, width = split_number(start)
    made = []
    for step in range(1, count + 1):
        if number is None:
            made.append(start)
        else:
            made.append(stem + str(number + step).rjust(width, '0'))
    return made


def evaluate(lines, keys, targets, find, replace, prefix, suffix, match_case,
             taken):
    """Work out every new value and flag the ones that will not do.

    `targets` is the set of (element id, kind, column key) the tools apply to.
    Empty means every NAME cell, which is what the window does with nothing
    picked.  `taken` maps a family to the names already in it, so a clash is
    caught here rather than by Revit halfway through writing.
    """
    for line in lines:
        line.new = dict(line.values)
        line.state = {}
        line.note = {}

    if not targets:
        targets = set([(line.element_id, line.kind, NAME_KEY)
                       for line in lines if line.can_edit(NAME_KEY)])

    for line in lines:
        for key in keys:
            if not line.can_edit(key):
                # shown, so the row reads properly, but never written
                line.state[key] = LOCKED
                continue
            typed = line.typed.get(key)
            if typed is not None:
                # typed straight into the cell: that is the value, whatever the
                # tools say, and it is not undone by retyping them
                line.new[key] = typed
                if key == NAME_KEY and not typed.strip():
                    line.state[key] = BLANK
                    line.note[key] = 'a name cannot be blank'
                elif typed == line.old_of(key):
                    line.state[key] = UNCHANGED
                else:
                    line.state[key] = OK
                continue
            if (line.element_id, line.kind, key) not in targets:
                line.state[key] = UNCHANGED
                continue
            made = apply_tools(line.old_of(key), find, replace, prefix, suffix,
                               match_case)
            line.new[key] = made
            if key == NAME_KEY and not made.strip():
                line.state[key] = BLANK
                line.note[key] = 'a name cannot be blank'
                continue
            if made == line.old_of(key):
                line.state[key] = UNCHANGED
                continue
            line.state[key] = OK

    _check_name_clashes(lines, taken)
    return lines


class QuickPlan(object):
    """What the quick rename on the toolbar would do to the picked names.

    `changes` is [(line, new name)], `refused` is [(line, why)], and
    `unchanged` counts the names the tools leave as they are."""

    __slots__ = ('changes', 'refused', 'unchanged')

    def __init__(self):
        self.changes = []
        self.refused = []
        self.unchanged = 0

    def any_tool(self):
        return bool(self.changes or self.refused)

    def summary(self):
        if not self.changes and not self.refused:
            if self.unchanged:
                return ('Nothing to change yet - ' + str(self.unchanged) +
                        ' name' + ('' if self.unchanged == 1 else 's') +
                        ' picked.')
            return 'Pick families or types in the list first.'
        parts = [str(len(self.changes)) + ' name' +
                 ('' if len(self.changes) == 1 else 's') + ' will change']
        if self.unchanged:
            parts.append(str(self.unchanged) + ' unchanged')
        if self.refused:
            parts.append(str(len(self.refused)) + ' refused (' +
                         self.refused[0][1] + ')')
        return ', '.join(parts) + '.'


def quick_rename(lines, find, replace, prefix, suffix, match_case, taken):
    """The toolbar's batch rename: the same three tools and the same clash
    rules as the full window, run over the NAME of every picked line.

    Kept beside evaluate() and built on it, so the two can never disagree about
    what a rename does or which names are refused.
    """
    plan = QuickPlan()
    evaluate(lines, [NAME_KEY], set(), find, replace, prefix, suffix,
             match_case, taken)
    for line in lines:
        state = line.state_of(NAME_KEY)
        if state == OK:
            plan.changes.append((line, line.new_of(NAME_KEY)))
        elif state in (CLASH, BLANK):
            plan.refused.append((line, line.note.get(NAME_KEY, state)))
        else:
            plan.unchanged += 1
    return plan


def _check_name_clashes(lines, taken):
    """Only names can clash.  A parameter value is free to repeat, and treating
    a repeat as a clash would stop the one thing re-stamping a parameter is
    for."""
    seen = {}
    for line in lines:
        if line.state_of(NAME_KEY) != OK:
            continue
        key = (line.kind, line.family)
        existing = set(taken.get(key, set()))
        for other in lines:
            if other is line or (other.kind, other.family) != key:
                continue
            if other.state_of(NAME_KEY) == OK:
                # being renamed away, so its old name is no longer in the way
                existing.discard(other.old_of(NAME_KEY))
            else:
                # not being renamed, so it is still holding its name
                existing.add(other.old_of(NAME_KEY))
        wanted = line.new_of(NAME_KEY)
        if wanted in existing:
            line.state[NAME_KEY] = CLASH
            line.note[NAME_KEY] = 'that name is already used here'
            continue
        made = seen.get(key)
        if made is None:
            made = set()
            seen[key] = made
        if wanted in made:
            line.state[NAME_KEY] = CLASH
            line.note[NAME_KEY] = 'two rows would end up with this name'
            continue
        made.add(wanted)


# ---------------------------------------------------------------------------
# the grid
# ---------------------------------------------------------------------------

class LineConverter(IValueConverter):
    def __init__(self, window):
        self.window = window

    def Convert(self, value, target_type, parameter, culture):
        try:
            return self._convert(value, str(parameter))
        except Exception:
            return ''

    def ConvertBack(self, value, target_type, parameter, culture):
        return None

    def _convert(self, line, parameter):
        if line is None:
            return ''
        if parameter == 'family':
            return line.family
        role, key = parameter.split('|', 1)
        state = line.state_of(key)
        if role == 'text':
            if state == OK:
                return line.new_of(key)
            return line.old_of(key)
        if role == 'note':
            if line.state_of(key) == LOCKED:
                return ''
            return line.note.get(key, '')
        if role == 'fg':
            return self.window.brush(_colour(state))
        if role == 'weight':
            return FontWeights.SemiBold if state == OK else FontWeights.Normal
        if role == 'handle':
            if not line.can_edit(key):
                return Visibility.Collapsed
            if self.window.fill_anchor == (line.element_id, line.kind, key):
                return Visibility.Visible
            return Visibility.Collapsed
        return ''


def _colour(state):
    if state == OK:
        return 'AccentGreen'
    if state in (CLASH, BLANK):
        return 'WarnRed'
    if state == LOCKED:
        # greyed, so it is obvious the cell is along for the ride
        return 'DisabledFg'
    return 'FgBody'


def _column(converter, heading, parameter, width, fg=None, weight=None,
            handle_key=None):
    """One column.  Where handle_key is given the cell also carries the small
    square at its bottom right that fills downwards, shown only on the cell the
    fill would start from."""
    if handle_key is None:
        return _plain_column(converter, heading, parameter, width, fg, weight)

    root = FrameworkElementFactory(Grid)

    text = _text_factory(converter, parameter, fg, weight)
    root.AppendChild(text)

    handle = FrameworkElementFactory(Border)
    handle.SetValue(FrameworkElement.WidthProperty, 7.0)
    handle.SetValue(FrameworkElement.HeightProperty, 7.0)
    handle.SetValue(FrameworkElement.TagProperty, 'fill|' + handle_key)
    handle.SetValue(FrameworkElement.CursorProperty, Cursors.Cross)
    handle.SetValue(FrameworkElement.HorizontalAlignmentProperty,
                    HorizontalAlignment.Right)
    handle.SetValue(FrameworkElement.VerticalAlignmentProperty,
                    VerticalAlignment.Bottom)
    handle.SetValue(FrameworkElement.MarginProperty,
                    Thickness(0.0, 0.0, 1.0, 1.0))
    handle.SetValue(FrameworkElement.ToolTipProperty,
                    'Drag down to fill')
    handle.SetResourceReference(Border.BackgroundProperty, 'AccentBlue')
    handle.SetBinding(FrameworkElement.VisibilityProperty,
                      _binding(converter, 'handle|' + handle_key))
    root.AppendChild(handle)

    template = DataTemplate()
    template.VisualTree = root
    column = DataGridTemplateColumn()
    column.Header = heading
    column.CellTemplate = template
    column.Width = DataGridLength(width, DataGridLengthUnitType.Pixel)
    column.MinWidth = 80.0
    column.CanUserSort = False
    return column


def _binding(converter, parameter):
    binding = Binding('.')
    binding.Converter = converter
    binding.ConverterParameter = parameter
    return binding


def _text_factory(converter, parameter, fg, weight):
    factory = FrameworkElementFactory(TextBlock)
    factory.SetBinding(TextBlock.TextProperty, _binding(converter, parameter))
    factory.SetValue(TextBlock.VerticalAlignmentProperty,
                     VerticalAlignment.Center)
    factory.SetValue(TextBlock.MarginProperty, Thickness(6.0, 2.0, 6.0, 2.0))
    factory.SetValue(TextBlock.TextTrimmingProperty,
                     TextTrimming.CharacterEllipsis)
    for chosen, target in ((fg, TextBlock.ForegroundProperty),
                           (weight, TextBlock.FontWeightProperty)):
        if chosen:
            factory.SetBinding(target, _binding(converter, chosen))
    return factory


def _plain_column(converter, heading, parameter, width, fg=None, weight=None):
    factory = FrameworkElementFactory(TextBlock)
    binding = Binding('.')
    binding.Converter = converter
    binding.ConverterParameter = parameter
    factory.SetBinding(TextBlock.TextProperty, binding)
    factory.SetValue(TextBlock.VerticalAlignmentProperty,
                     VerticalAlignment.Center)
    factory.SetValue(TextBlock.MarginProperty, Thickness(6.0, 2.0, 6.0, 2.0))
    factory.SetValue(TextBlock.TextTrimmingProperty,
                     TextTrimming.CharacterEllipsis)
    for chosen, target in ((fg, TextBlock.ForegroundProperty),
                           (weight, TextBlock.FontWeightProperty)):
        if not chosen:
            continue
        other = Binding('.')
        other.Converter = converter
        other.ConverterParameter = chosen
        factory.SetBinding(target, other)

    template = DataTemplate()
    template.VisualTree = factory
    column = DataGridTemplateColumn()
    column.Header = heading
    column.CellTemplate = template
    # pixels, not stars, so the columns can be dragged wider and the grid
    # scrolls sideways rather than squeezing every column into nothing
    column.Width = DataGridLength(width, DataGridLengthUnitType.Pixel)
    column.MinWidth = 80.0
    column.CanUserSort = False
    return column


class BatchRenameWindow(object):

    def __init__(self, owner, handle, settings, palette_name, lines, keys,
                 headings, taken):
        self.palette = palette_name
        self.settings = settings
        self.lines = lines
        self.keys = keys                  # column keys, NAME_KEY first
        self.headings = headings          # column key -> heading text
        self.taken = taken
        self.result = None
        self.column_keys = []             # grid column index -> column key
        # Our own record of what is picked.  The grid's own SelectedCells is
        # emptied by Items.Refresh, and refresh runs on every keystroke in the
        # tools, so leaning on it meant a pick never survived long enough to be
        # used - which is what made picking cells look as though it did nothing.
        self.picked = set()
        self.suspend = False
        self.editing = None
        # the cell the fill handle hangs off, and the drag in progress
        self.fill_anchor = None
        self.filling = None

        self.window = fv_ui.load_window('FamilyViewerBatch.xaml', palette_name)
        find = self.window.FindName
        self.find_box = find('BatchFind')
        self.replace_box = find('BatchReplace')
        self.prefix_box = find('BatchPrefix')
        self.suffix_box = find('BatchSuffix')
        self.case_box = find('BatchCase')
        self.reset_btn = find('BatchReset')
        self.clear_btn = find('BatchClear')
        self.grid = find('BatchGrid')
        self.status = find('BatchStatus')
        self.apply_btn = find('BatchApply')
        self.cancel_btn = find('BatchCancel')
        self.close_btn = find('BatchClose')
        self.full_btn = find('BatchFull')
        find('BatchVersion').Text = 'v' + fv_core.__version__

        self.converter = LineConverter(self)
        self._build_columns()

        for box in (self.find_box, self.replace_box, self.prefix_box,
                    self.suffix_box):
            box.TextChanged += self.on_changed
        self.case_box.Checked += self.on_changed
        self.case_box.Unchecked += self.on_changed
        self.find_toggle = find('FindToggle')
        self.find_popup = find('FindPopup')
        self.find_toggle.Click += self.on_find_toggle
        self.find_popup.Closed += self.on_find_closed
        self.reset_btn.Click += self.on_reset
        self.clear_btn.Click += self.on_clear_cells
        self.apply_btn.Click += self.on_apply
        self.cancel_btn.Click += self.on_cancel
        self.close_btn.Click += self.on_cancel
        self.grid.SelectedCellsChanged += self.on_cells_changed
        self.grid.MouseDoubleClick += self.on_cell_double_click
        self.grid.PreviewMouseLeftButtonDown += self.on_grid_mouse_down
        self.grid.PreviewMouseLeftButtonUp += self.on_grid_mouse_up
        self.window.KeyDown += self.on_key

        # the items are set ONCE.  Reassigning ItemsSource rebuilds every row
        # and empties the selection with it.
        self.items = List[Object]()
        for line in self.lines:
            self.items.Add(line)
        self.grid.ItemsSource = self.items

        # the same chrome the main window uses: its own resize grips, because a
        # borderless AllowsTransparency window has nothing hit testable in its
        # frame, and full screen by bounds rather than WindowState.Maximized
        self.chrome = fv_ui.Chrome(self.window, handle, settings)
        self.chrome.wire_header(find('BatchHeader'))
        self.chrome.add_grips(find('BatchResizeLayer'))
        self.full_btn.Click += self.on_full
        self.drawer = fv_ui.WindowDrawer(
            self.window, find('BatchHeader'), find('BatchRoot'),
            find('BatchShrink'), grips=find('BatchResizeLayer'), owner=owner)

        fv_ui.own_dialog(self.window, owner)
        self.refresh()

    def brush(self, key):
        try:
            return self.window.Resources[key]
        except Exception:
            return None

    def on_full(self, sender, args):
        self.chrome.toggle_full()

    def on_key(self, sender, args):
        ctrl = False
        try:
            ctrl = (Keyboard.Modifiers & ModifierKeys.Control) == \
                ModifierKeys.Control
        except Exception:
            ctrl = False
        if ctrl and args.Key == Key.C:
            self.on_copy()
            args.Handled = True
            return
        if ctrl and args.Key == Key.V:
            self.on_paste()
            args.Handled = True
            return
        if args.Key == Key.F11:
            self.chrome.toggle_full()
            args.Handled = True
        elif args.Key == Key.Escape and self.chrome.full:
            self.chrome.toggle_full(False)
            args.Handled = True

    # -- columns ----------------------------------------------------------

    def _build_columns(self):
        self.grid.Columns.Clear()
        self.column_keys = []

        self.grid.Columns.Add(
            _column(self.converter, 'Family', 'family', 190.0))
        self.column_keys.append(None)      # not a cell the tools can touch

        for key in self.keys:
            heading = self.headings.get(key, key)
            self.grid.Columns.Add(
                _column(self.converter, heading, 'text|' + key, 180.0,
                        'fg|' + key, 'weight|' + key, handle_key=key))
            self.column_keys.append(key)

        self.grid.Columns.Add(
            _column(self.converter, 'Note', 'note|' + NAME_KEY, 190.0,
                    'fg|' + NAME_KEY))
        self.column_keys.append(None)

    # -- the picked cells --------------------------------------------------

    def picked_cells(self):
        """(element id, kind, column key) for every cell picked."""
        return set(self.picked)

    def _read_selection(self):
        """Read the grid's selection into our own record.

        Family and Note are not cells the tools can touch, so a click on one is
        ignored rather than quietly renaming something else.
        """
        found = set()
        try:
            cells = list(self.grid.SelectedCells)
        except Exception:
            cells = []
        for cell in cells:
            line = None
            try:
                line = cell.Item
            except Exception:
                line = None
            if line is None:
                continue
            index = -1
            try:
                index = int(cell.Column.DisplayIndex)
            except Exception:
                index = -1
            if index < 0 or index >= len(self.column_keys):
                continue
            key = self.column_keys[index]
            if key is None:
                continue
            if not line.can_edit(key):
                # picking a locked cell is not a request to write it
                continue
            found.add((line.element_id, line.kind, key))
        return found

    def _restore_selection(self):
        """Put the picked cells back after a refresh."""
        if not self.picked:
            return
        columns = {}
        for index, key in enumerate(self.column_keys):
            if key is not None:
                columns[key] = index
        try:
            self.grid.SelectedCells.Clear()
        except Exception:
            return
        for line in self.lines:
            for key in self.keys:
                if (line.element_id, line.kind, key) not in self.picked:
                    continue
                index = columns.get(key)
                if index is None or index >= self.grid.Columns.Count:
                    continue
                try:
                    self.grid.SelectedCells.Add(
                        DataGridCellInfo(line, self.grid.Columns[index]))
                except Exception:
                    continue

    def on_cells_changed(self, sender, args):
        if self.suspend:
            return
        self.picked = self._read_selection()
        self.fill_anchor = self._anchor()
        self.refresh()

    def _anchor(self):
        """The cell the fill handle hangs off: the lowest picked cell in the
        one column that is picked.  With cells picked across several columns
        there is no one place to fill from, so there is no handle."""
        if not self.picked:
            return None
        keys = set([entry[2] for entry in self.picked])
        if len(keys) != 1:
            return None
        key = list(keys)[0]
        order = {}
        for index, line in enumerate(self.lines):
            order[(line.element_id, line.kind)] = index
        best = None
        best_at = -1
        for entry in self.picked:
            at = order.get((entry[0], entry[1]), -1)
            if at > best_at:
                best_at = at
                best = entry
        return best

    # -- fill down ---------------------------------------------------------

    def on_grid_mouse_down(self, sender, args):
        """A press on the little square starts a fill rather than a
        selection."""
        node = _ancestor_with_fill_tag(args.OriginalSource)
        if node is None:
            return
        if self.fill_anchor is None:
            return
        self.filling = self.fill_anchor
        try:
            self.grid.CaptureMouse()
        except Exception:
            pass
        args.Handled = True

    def on_grid_mouse_up(self, sender, args):
        if self.filling is None:
            return
        anchor = self.filling
        self.filling = None
        try:
            self.grid.ReleaseMouseCapture()
        except Exception:
            pass

        line = _ancestor_of_type(args.OriginalSource, DataGridRow)
        target = None
        if line is not None:
            try:
                target = line.Item
            except Exception:
                target = None
        if target is None:
            return

        key = anchor[2]
        start_at = None
        end_at = None
        for index, one in enumerate(self.lines):
            if (one.element_id, one.kind) == (anchor[0], anchor[1]):
                start_at = index
            if one is target:
                end_at = index
        if start_at is None or end_at is None or end_at <= start_at:
            return

        run = self.lines[start_at + 1:end_at + 1]
        source = self.lines[start_at]
        made = fill_values(source.new_of(key), len(run))
        filled = 0
        for one, value in zip(run, made):
            if not one.can_edit(key):
                continue
            one.typed[key] = value
            filled += 1
        self.refresh()
        self.status.Text = (
            str(filled) + ' cell' + ('' if filled == 1 else 's') +
            ' filled down. Nothing is written until Apply.')
        args.Handled = True

    # -- copy and paste ----------------------------------------------------

    def on_copy(self):
        """The picked cells to the clipboard, tab separated by column and
        newline separated by row, which is what Excel reads."""
        if not self.picked:
            return
        keys = [key for key in self.keys
                if key in set([entry[2] for entry in self.picked])]
        rows = []
        for line in self.lines:
            row = []
            wanted = False
            for key in keys:
                if (line.element_id, line.kind, key) in self.picked:
                    row.append(line.new_of(key))
                    wanted = True
                else:
                    row.append('')
            if wanted:
                rows.append('\t'.join(row))
        if not rows:
            return
        try:
            Clipboard.SetText('\r\n'.join(rows))
        except Exception:
            fv_core.log('clipboard refused:\n' + fv_core.format_exc())
            return
        self.status.Text = (str(len(rows)) + ' row' +
                            ('' if len(rows) == 1 else 's') + ' copied.')

    def on_paste(self):
        """From the clipboard into the cells, starting at the picked one.

        A locked cell is stepped over rather than written, and the count says
        how many were skipped - pasting a column over a bank that includes an
        instance parameter should not silently lose part of it.
        """
        anchor = self._anchor() or (self.fill_anchor)
        if anchor is None:
            self.status.Text = 'Pick the cell to paste into first.'
            return
        try:
            text = Clipboard.GetText()
        except Exception:
            text = ''
        if not text:
            return

        grid = [row.split('\t') for row in text.replace('\r\n', '\n')
                .replace('\r', '\n').split('\n') if row != '']
        start_at = None
        for index, line in enumerate(self.lines):
            if (line.element_id, line.kind) == (anchor[0], anchor[1]):
                start_at = index
                break
        if start_at is None:
            return
        start_key = self.keys.index(anchor[2]) if anchor[2] in self.keys else 0

        pasted = 0
        skipped = 0
        for down, row in enumerate(grid):
            at = start_at + down
            if at >= len(self.lines):
                break
            line = self.lines[at]
            for across, value in enumerate(row):
                key_at = start_key + across
                if key_at >= len(self.keys):
                    break
                key = self.keys[key_at]
                if not line.can_edit(key):
                    skipped += 1
                    continue
                line.typed[key] = value
                pasted += 1
        self.refresh()
        parts = [str(pasted) + ' cell' + ('' if pasted == 1 else 's') +
                 ' pasted']
        if skipped:
            parts.append(str(skipped) + ' read only and stepped over')
        self.status.Text = '. '.join(parts) + '.'

    def on_clear_cells(self, sender, args):
        self.picked = set()
        self.fill_anchor = None
        self.suspend = True
        try:
            self.grid.SelectedCells.Clear()
        except Exception:
            pass
        self.suspend = False
        self.refresh()

    # -- typing into a cell -----------------------------------------------

    def on_cell_double_click(self, sender, args):
        """Double click a cell and type the value straight in, the way the
        Excel for Revit tool does.  A typed value wins over the tools."""
        cell = _ancestor_of_type(args.OriginalSource, DataGridCell)
        if cell is None:
            return
        line = None
        try:
            line = cell.Item
        except Exception:
            line = None
        index = -1
        try:
            index = int(cell.Column.DisplayIndex)
        except Exception:
            index = -1
        if line is None or index < 0 or index >= len(self.column_keys):
            return
        key = self.column_keys[index]
        if key is None:
            return
        if not line.can_edit(key):
            self.status.Text = (
                'That cell is read only here - it lives on the instance, not '
                'the type, so it is shown but not written.')
            return

        box = TextBox()
        fv_ui.styled(box, 'CellEditBox')
        box.Text = line.new_of(key)
        box.Margin = Thickness(2.0, 1.0, 2.0, 1.0)
        state = {'done': False}

        def finish(keep):
            if state['done']:
                return
            state['done'] = True
            self.editing = None
            if keep:
                typed = box.Text or ''
                if typed == line.old_of(key):
                    line.typed.pop(key, None)
                else:
                    line.typed[key] = typed
            self.refresh()

        def typed_key(sender_, args_):
            if args_.Key == Key.Enter:
                args_.Handled = True
                finish(True)
            elif args_.Key == Key.Escape:
                args_.Handled = True
                finish(False)

        box.KeyDown += typed_key
        box.LostKeyboardFocus += lambda a, b: finish(True)

        self.editing = cell
        cell.Content = box
        args.Handled = True
        try:
            box.Focus()
            box.SelectAll()
        except Exception:
            pass

    # -- the tools ---------------------------------------------------------

    def on_find_toggle(self, sender, args):
        self.find_popup.IsOpen = bool(self.find_toggle.IsChecked)

    def on_find_closed(self, sender, args):
        self.find_toggle.IsChecked = False

    def _label_find(self):
        """The button says whether anything is set behind it, so a find left
        in the popup cannot quietly go on applying."""
        find_text = self.find_box.Text or ''
        if find_text:
            self.find_toggle.Content = 'Find "' + find_text + '"'
        else:
            self.find_toggle.Content = 'Find and replace'

    def on_changed(self, sender, args):
        self._label_find()
        self.refresh()

    def on_reset(self, sender, args):
        for box in (self.find_box, self.replace_box, self.prefix_box,
                    self.suffix_box):
            box.Text = ''
        self.case_box.IsChecked = False
        for line in self.lines:
            line.typed = {}
        self.refresh()

    def _tools(self):
        return (self.find_box.Text or '', self.replace_box.Text or '',
                self.prefix_box.Text or '', self.suffix_box.Text or '',
                bool(self.case_box.IsChecked))

    def refresh(self):
        find, replace, prefix, suffix, match_case = self._tools()
        targets = self.picked_cells()
        evaluate(self.lines, self.keys, targets, find, replace, prefix, suffix,
                 match_case, self.taken)

        self.suspend = True
        try:
            self.grid.Items.Refresh()
        except Exception:
            pass
        self._restore_selection()
        self.suspend = False

        ready = 0
        bad = 0
        locked = 0
        for line in self.lines:
            for key in self.keys:
                state = line.state_of(key)
                if state == OK:
                    ready += 1
                elif state in (CLASH, BLANK):
                    bad += 1
                elif state == LOCKED:
                    locked += 1

        typed = 0
        for line in self.lines:
            typed += len(line.typed)
        where = 'every name'
        if targets:
            where = (str(len(targets)) + ' picked cell' +
                     ('' if len(targets) == 1 else 's'))
        parts = ['Applying to ' + where,
                 str(ready) + ' would change']
        if typed:
            parts.append(str(typed) + ' typed in by hand')
        if bad:
            parts.append(str(bad) + ' cannot and are left alone')
        if locked:
            parts.append(str(locked) + ' read only')
        self.status.Text = '. '.join(parts) + '.'
        self.apply_btn.IsEnabled = ready > 0

    # -- leaving -----------------------------------------------------------

    def on_apply(self, sender, args):
        staged = []
        for line in self.lines:
            for key in line.changes():
                staged.append((line, key, line.new_of(key)))
        self.result = staged
        try:
            self.window.DialogResult = True
        except Exception:
            self.window.Close()

    def on_cancel(self, sender, args):
        self.result = None
        try:
            self.window.DialogResult = False
        except Exception:
            self.window.Close()

    def show(self):
        try:
            self.window.ShowDialog()
        except Exception:
            fv_core.log('batch rename window failed:\n' + fv_core.format_exc())
            return None
        finally:
            try:
                self.chrome.close()
            except Exception:
                pass
        return self.result


def open_batch_rename(owner, handle, settings, palette_name, lines, keys,
                      headings, taken):
    """Returns [(line, column key, new value)] to stage, or None if cancelled."""
    window = BatchRenameWindow(owner, handle, settings, palette_name, lines,
                               keys, headings, taken)
    return window.show()
