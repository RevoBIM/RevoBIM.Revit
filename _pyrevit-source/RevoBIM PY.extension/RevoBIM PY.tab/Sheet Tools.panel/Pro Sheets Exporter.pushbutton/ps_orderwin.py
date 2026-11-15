# -*- coding: utf-8 -*-
"""Page order for a combined PDF.

Only reachable when "Combine multiple views/sheets into a single file" is on,
because it is the only time the order is a decision rather than a side effect
of how the table happens to be sorted.
"""

import ps_refs  # noqa: F401  - must be first

import ps_model
import ps_ui


class OrderWindow(object):
    """Modal. Returns the reordered list of keys, or None when cancelled."""

    def __init__(self, entries, theme_name='dark', owner=None):
        # entries: list of (key, label), already in the current order
        self.entries = list(entries)
        self.result = None

        self.window = ps_ui.load_window('ProSheetsOrder.xaml', theme_name)
        self.chrome = ps_ui.Chrome(self.window, on_close=self._cancel)
        # The egg is armed on the main window only; see ps_ui.attach_egg.
        if owner is not None:
            try:
                self.window.Owner = owner
            except Exception:
                pass

        self.list_box = ps_ui.find(self.window, 'OrderList')
        self._fill()
        self._wire()
        self._say_count()

    def _fill(self):
        if self.list_box is None:
            return
        try:
            self.list_box.Items.Clear()
            for _key, label in self.entries:
                self.list_box.Items.Add(label)
        except Exception:
            pass

    def _say_count(self):
        ps_ui.set_text(ps_ui.find(self.window, 'StatusText'),
                       u'{0} page{1}, top to bottom.'.format(
                           len(self.entries),
                           u'' if len(self.entries) == 1 else u's'))

    def _wire(self):
        pairs = [
            ('MoveTopButton', self._move_top),
            ('MoveUpButton', self._move_up),
            ('MoveDownButton', self._move_down),
            ('MoveBottomButton', self._move_bottom),
            ('SortButton', self._sort),
            ('OkButton', self._ok),
            ('CancelButton', self._cancel_clicked),
        ]
        for name, handler in pairs:
            button = ps_ui.find(self.window, name)
            if button is None:
                continue
            try:
                button.Click += handler
            except Exception:
                continue

    def _selected(self):
        found = []
        if self.list_box is None:
            return found
        try:
            for index in range(self.list_box.Items.Count):
                if self.list_box.SelectedItems.Contains(self.list_box.Items[index]):
                    found.append(index)
        except Exception:
            return []
        return found

    def _apply(self, order, reselect=None):
        self.entries = [self.entries[index] for index in order]
        self._fill()
        if reselect:
            try:
                self.list_box.SelectedItems.Clear()
                for index in reselect:
                    if 0 <= index < self.list_box.Items.Count:
                        self.list_box.SelectedItems.Add(self.list_box.Items[index])
            except Exception:
                pass

    def _shift(self, step):
        picked = self._selected()
        if not picked:
            return
        count = len(self.entries)
        order = list(range(count))
        sequence = picked if step < 0 else list(reversed(picked))
        landed = []
        for index in sequence:
            position = order.index(index)
            target = position + step
            if target < 0 or target >= count:
                landed.append(position)
                continue
            order[position], order[target] = order[target], order[position]
            landed.append(target)
        self._apply(order, landed)

    def _move_up(self, sender, args):
        self._shift(-1)

    def _move_down(self, sender, args):
        self._shift(1)

    def _move_top(self, sender, args):
        picked = self._selected()
        if not picked:
            return
        rest = [i for i in range(len(self.entries)) if i not in picked]
        self._apply(picked + rest, list(range(len(picked))))

    def _move_bottom(self, sender, args):
        picked = self._selected()
        if not picked:
            return
        rest = [i for i in range(len(self.entries)) if i not in picked]
        self._apply(rest + picked,
                    list(range(len(rest), len(rest) + len(picked))))

    def _sort(self, sender, args):
        order = sorted(range(len(self.entries)),
                       key=lambda i: ps_model.natural_key(self.entries[i][1]))
        self._apply(order)

    def _ok(self, sender, args):
        self.result = [key for key, _label in self.entries]
        self._close(True)

    def _cancel_clicked(self, sender, args):
        self._cancel()

    def _cancel(self):
        self.result = None
        self._close(False)

    def _close(self, ok):
        try:
            self.window.DialogResult = bool(ok)
        except Exception:
            pass
        try:
            self.window.Close()
        except Exception:
            pass

    def show(self):
        try:
            self.window.ShowDialog()
        except Exception:
            pass
        return self.result
