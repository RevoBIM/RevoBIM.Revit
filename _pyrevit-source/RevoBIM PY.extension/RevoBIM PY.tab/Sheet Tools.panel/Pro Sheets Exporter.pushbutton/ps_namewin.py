# -*- coding: utf-8 -*-
"""The Custom File Name dialog.

Parameters on the left, the name being built on the right, pushed across
with the arrow buttons. The preview under the table updates on every
keystroke and shows two lines: the shape of the name in parameter names, and
what it actually comes out as on the first ticked sheet. The second line is
what catches an empty parameter before four hundred files are named after it.

The grid is backed by a ``DataTable`` rather than by Python objects. WPF
binding to IronPython attributes is not dependable across the engines
pyRevit picks, and a table of typed columns is what the rest of this
extension already uses.
"""

import ps_refs  # noqa: F401  - must be first

from System import String
from System.Data import DataTable

import ps_model
import ps_naming
import ps_ui


COLUMNS = ['pname', 'prefix', 'sample', 'suffix', 'sep']


class CustomNameWindow(object):
    """Modal. Returns the finished rule list, or None when cancelled."""

    def __init__(self, catalogue, sample_lookup, rules, theme_name='dark',
                 owner=None, sample_label=u'', mode='sheets'):
        self.mode = 'views' if mode == 'views' else 'sheets'
        self.catalogue = catalogue or []
        self.sample_lookup = sample_lookup
        self.theme_name = theme_name
        self.result = None
        self._suspend = False

        self.window = ps_ui.load_window('ProSheetsCustomName.xaml', theme_name)
        self.chrome = ps_ui.Chrome(self.window, on_close=self._cancel)
        # The egg is armed on the main window only; see ps_ui.attach_egg.
        if owner is not None:
            try:
                self.window.Owner = owner
            except Exception:
                pass

        self.available_list = ps_ui.find(self.window, 'AvailableList')
        self.group_combo = ps_ui.find(self.window, 'GroupCombo')
        self.search_box = ps_ui.find(self.window, 'ParamSearchBox')
        self.grid = ps_ui.find(self.window, 'RuleGrid')
        self.preview = ps_ui.find(self.window, 'PreviewText')
        self.real_preview = ps_ui.find(self.window, 'RealPreviewText')
        self.status = ps_ui.find(self.window, 'StatusText')

        # Sheets and views keep separate names, so say which one this is.
        ps_ui.set_text(ps_ui.find(self.window, 'NameModeText'),
                       u'Custom File Name - {0}'.format(
                           u'Views' if self.mode == 'views' else u'Sheets'))
        if sample_label:
            ps_ui.set_text(ps_ui.find(self.window, 'SampleNote'),
                           u'Sample values are from {0}.'.format(sample_label))

        self.table = self._make_table()
        try:
            self.grid.ItemsSource = self.table.DefaultView
        except Exception:
            pass

        self._fill_groups()
        self._fill_available()
        self._load_rules(rules or ps_naming.default_rules(self.mode))
        self._wire()
        self._refresh_preview()

    # ------------------------------------------------------------ the table
    def _make_table(self):
        table = DataTable('rules')
        for name in COLUMNS:
            table.Columns.Add(name, String)
        try:
            table.ColumnChanged += self._cell_changed
        except Exception:
            pass
        return table

    def _cell_changed(self, sender, args):
        if self._suspend:
            return
        self._refresh_preview()

    # -------------------------------------------------------- the left list
    def _fill_groups(self):
        groups = ps_model.catalogue_groups(self.catalogue)
        ps_ui.fill_combo(self.group_combo, groups, selected=u'All')

    def _fill_available(self):
        if self.available_list is None:
            return
        group = ps_ui.combo_text(self.group_combo) or u'All'
        try:
            needle = u'{0}'.format(self.search_box.Text or u'').strip().lower()
        except Exception:
            needle = u''
        try:
            self.available_list.Items.Clear()
            for name, owning_group in self.catalogue:
                if group != u'All' and owning_group != group:
                    continue
                if needle and needle not in name.lower():
                    continue
                self.available_list.Items.Add(name)
        except Exception:
            pass

    # ------------------------------------------------------------- the rules
    def _load_rules(self, rules):
        self._suspend = True
        try:
            self.table.Rows.Clear()
            for rule in rules:
                self._add_row(rule.param, rule.prefix, rule.suffix,
                              rule.separator)
        finally:
            self._suspend = False

    def _add_row(self, param, prefix=u'', suffix=u'', separator=u'-'):
        row = self.table.NewRow()
        row['pname'] = u'{0}'.format(param)
        row['prefix'] = u'{0}'.format(prefix or u'')
        row['suffix'] = u'{0}'.format(suffix or u'')
        row['sep'] = u'{0}'.format(separator if separator is not None else u'')
        row['sample'] = self._sample_for(param)
        self.table.Rows.Add(row)
        return row

    def _sample_for(self, param):
        if self.sample_lookup is None:
            return u''
        try:
            value = self.sample_lookup(param)
        except Exception:
            value = u''
        text = u'{0}'.format(value or u'')
        if not text:
            return u'(empty)'
        return text if len(text) <= 48 else text[:45] + u'...'

    def rules(self):
        """The current table, as an ordered list of Rule objects."""
        out = []
        try:
            for row in self.table.Rows:
                name = u'{0}'.format(row['pname'] or u'').strip()
                if not name:
                    continue
                out.append(ps_naming.Rule(
                    name,
                    u'{0}'.format(row['prefix'] or u''),
                    u'{0}'.format(row['suffix'] or u''),
                    u'{0}'.format(row['sep'] or u'')))
        except Exception:
            pass
        return out

    # ------------------------------------------------------------- preview
    def _refresh_preview(self):
        rules = self.rules()
        ps_ui.set_text(self.preview, ps_naming.preview(rules))
        if self.sample_lookup is not None:
            try:
                real = ps_naming.build_name(rules, self.sample_lookup)
            except Exception:
                real = u''
            ps_ui.set_text(self.real_preview, real + u'.pdf' if real else u'')
        if not rules:
            ps_ui.set_text(self.status,
                           u'With nothing chosen the sheet number is used.')
        else:
            ps_ui.set_text(self.status, u'{0} parameter{1} in the name.'.format(
                len(rules), u'' if len(rules) == 1 else u's'))

    # -------------------------------------------------------------- wiring
    def _wire(self):
        pairs = [
            ('PushRightButton', self._push_right),
            ('PushLeftButton', self._push_left),
            ('MoveTopButton', self._move_top),
            ('MoveUpButton', self._move_up),
            ('MoveDownButton', self._move_down),
            ('MoveBottomButton', self._move_bottom),
            ('ResetButton', self._reset),
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

        if self.group_combo is not None:
            try:
                self.group_combo.SelectionChanged += self._group_changed
            except Exception:
                pass
        if self.search_box is not None:
            try:
                self.search_box.TextChanged += self._search_changed
            except Exception:
                pass
        if self.available_list is not None:
            try:
                self.available_list.MouseDoubleClick += self._push_right
            except Exception:
                pass

    def _group_changed(self, sender, args):
        self._fill_available()

    def _search_changed(self, sender, args):
        self._fill_available()

    # ------------------------------------------------------------- actions
    def _push_right(self, sender, args):
        if self.available_list is None:
            return
        chosen = []
        try:
            for item in self.available_list.SelectedItems:
                chosen.append(u'{0}'.format(item))
        except Exception:
            return
        if not chosen:
            return
        self._suspend = True
        try:
            for name in chosen:
                self._add_row(name)
        finally:
            self._suspend = False
        self._refresh_preview()

    def _selected_indices(self):
        """Which table rows the grid has selected, as table row indexes."""
        found = []
        if self.grid is None:
            return found
        try:
            for item in self.grid.SelectedItems:
                row = getattr(item, 'Row', None)
                if row is None:
                    continue
                index = self.table.Rows.IndexOf(row)
                if index >= 0:
                    found.append(index)
        except Exception:
            return []
        found.sort()
        return found

    def _rewrite(self, order):
        """Rebuild the table in a new order, keeping every value."""
        snapshot = []
        for index in order:
            row = self.table.Rows[index]
            snapshot.append((u'{0}'.format(row['pname'] or u''),
                             u'{0}'.format(row['prefix'] or u''),
                             u'{0}'.format(row['suffix'] or u''),
                             u'{0}'.format(row['sep'] or u''),
                             u'{0}'.format(row['sample'] or u'')))
        self._suspend = True
        try:
            self.table.Rows.Clear()
            for pname, prefix, suffix, separator, sample in snapshot:
                row = self.table.NewRow()
                row['pname'] = pname
                row['prefix'] = prefix
                row['suffix'] = suffix
                row['sep'] = separator
                row['sample'] = sample
                self.table.Rows.Add(row)
        finally:
            self._suspend = False
        self._refresh_preview()

    def _push_left(self, sender, args):
        picked = set(self._selected_indices())
        if not picked:
            return
        keep = [i for i in range(self.table.Rows.Count) if i not in picked]
        self._rewrite(keep)

    def _move_up(self, sender, args):
        self._shift(-1)

    def _move_down(self, sender, args):
        self._shift(1)

    def _shift(self, step):
        picked = self._selected_indices()
        if not picked:
            return
        count = self.table.Rows.Count
        order = list(range(count))
        sequence = picked if step < 0 else list(reversed(picked))
        moved = []
        for index in sequence:
            position = order.index(index)
            target = position + step
            if target < 0 or target >= count:
                continue
            order[position], order[target] = order[target], order[position]
            moved.append(index)
        if not moved:
            return
        self._rewrite(order)
        self._reselect(moved, step)

    def _move_top(self, sender, args):
        picked = self._selected_indices()
        if not picked:
            return
        rest = [i for i in range(self.table.Rows.Count) if i not in picked]
        self._rewrite(picked + rest)
        self._select_range(0, len(picked))

    def _move_bottom(self, sender, args):
        picked = self._selected_indices()
        if not picked:
            return
        rest = [i for i in range(self.table.Rows.Count) if i not in picked]
        self._rewrite(rest + picked)
        self._select_range(len(rest), len(picked))

    def _reselect(self, moved, step):
        try:
            self.grid.SelectedItems.Clear()
            view = self.table.DefaultView
            for index in moved:
                target = index + step
                if 0 <= target < view.Count:
                    self.grid.SelectedItems.Add(view[target])
        except Exception:
            pass

    def _select_range(self, start, count):
        try:
            self.grid.SelectedItems.Clear()
            view = self.table.DefaultView
            for index in range(start, start + count):
                if 0 <= index < view.Count:
                    self.grid.SelectedItems.Add(view[index])
        except Exception:
            pass

    def _reset(self, sender, args):
        self._load_rules(ps_naming.default_rules(getattr(self, 'mode',
                                                         'sheets')))
        self._refresh_preview()

    # --------------------------------------------------------------- closing
    def _ok(self, sender, args):
        self.result = self.rules()
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
