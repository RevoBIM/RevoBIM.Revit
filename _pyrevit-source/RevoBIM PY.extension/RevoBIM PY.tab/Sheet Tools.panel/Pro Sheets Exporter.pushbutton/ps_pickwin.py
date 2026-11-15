# -*- coding: utf-8 -*-
"""A plain multi-select parameter picker.

Used by the Selection grid's "Add column" and by anything else that needs
the answer to "which parameters?" and nothing more. The naming dialog and
the subfolder dialog both ask richer questions - a name has prefixes and
separators, a path has levels - so they keep their own windows. This one
returns a list of names and that is all.

Each row shows what the parameter resolves to on a real sheet, because
"BGL_Sheet Stage" tells you nothing about whether it is filled in and
"(empty)" tells you everything.
"""

import ps_refs  # noqa: F401  - must be first

from System import String
from System.Data import DataTable

import ps_model
import ps_ui


ALL_GROUPS = u'All'


class PickWindow(object):
    """Modal. Returns a list of parameter names, or None when cancelled."""

    def __init__(self, catalogue, sample_lookup, theme_name='dark',
                 owner=None, subtitle=u'Choose parameters', already=None,
                 sample_label=u''):
        self.catalogue = catalogue or []
        self.sample_lookup = sample_lookup
        self.already = set(already or [])
        self.result = None

        self.window = ps_ui.load_window('ProSheetsPick.xaml', theme_name)
        self.chrome = ps_ui.Chrome(self.window, on_close=self._cancel)
        if owner is not None:
            try:
                self.window.Owner = owner
            except Exception:
                pass

        ps_ui.set_text(ps_ui.find(self.window, 'SubtitleText'), subtitle)

        self.grid = ps_ui.find(self.window, 'PickGrid')
        self.group_combo = ps_ui.find(self.window, 'PickGroupCombo')
        self.search_box = ps_ui.find(self.window, 'PickSearchBox')

        self.table = DataTable('pick')
        for name in ('pname', 'pgroup', 'sample'):
            self.table.Columns.Add(name, String)
        try:
            self.grid.ItemsSource = self.table.DefaultView
        except Exception:
            pass

        if sample_label:
            ps_ui.set_text(ps_ui.find(self.window, 'StatusText'),
                           u'Values are from {0}. Ctrl and Shift work as '
                           u'usual.'.format(sample_label))

        self._fill_groups()
        self._fill_rows()
        self._wire()

    def _fill_groups(self):
        groups = ps_model.catalogue_groups(self.catalogue)
        ps_ui.fill_combo(self.group_combo, groups, selected=ALL_GROUPS)

    def _sample_for(self, name):
        if self.sample_lookup is None:
            return u''
        try:
            value = self.sample_lookup(name)
        except Exception:
            value = u''
        text = u'{0}'.format(value or u'')
        if not text:
            return u'(empty)'
        return text if len(text) <= 40 else text[:37] + u'...'

    def _fill_rows(self):
        group = ps_ui.combo_text(self.group_combo) or ALL_GROUPS
        try:
            needle = u'{0}'.format(self.search_box.Text or u'').strip().lower()
        except Exception:
            needle = u''
        try:
            self.table.Rows.Clear()
            for name, owning_group in self.catalogue:
                # Something already on the grid is not worth offering twice.
                if name in self.already:
                    continue
                if group != ALL_GROUPS and owning_group != group:
                    continue
                if needle and needle not in name.lower():
                    continue
                row = self.table.NewRow()
                row['pname'] = name
                row['pgroup'] = owning_group
                row['sample'] = self._sample_for(name)
                self.table.Rows.Add(row)
        except Exception:
            pass

    def _wire(self):
        pairs = [
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
                self.group_combo.SelectionChanged += self._filter_changed
            except Exception:
                pass
        if self.search_box is not None:
            try:
                self.search_box.TextChanged += self._filter_changed
            except Exception:
                pass
        if self.grid is not None:
            try:
                self.grid.MouseDoubleClick += self._double_clicked
            except Exception:
                pass

    def _filter_changed(self, sender, args):
        self._fill_rows()

    def _double_clicked(self, sender, args):
        self._ok(sender, args)

    def chosen(self):
        found = []
        if self.grid is None:
            return found
        try:
            for item in self.grid.SelectedItems:
                row = getattr(item, 'Row', None)
                if row is None:
                    continue
                name = u'{0}'.format(row['pname'])
                if name and name not in found:
                    found.append(name)
        except Exception:
            return []
        return found

    def _ok(self, sender, args):
        picked = self.chosen()
        if not picked:
            ps_ui.set_text(ps_ui.find(self.window, 'StatusText'),
                           u'Nothing picked yet.')
            return
        self.result = picked
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


def pick(catalogue, sample_lookup, theme_name='dark', owner=None,
         subtitle=u'Choose parameters', already=None, sample_label=u''):
    return PickWindow(catalogue, sample_lookup, theme_name, owner, subtitle,
                      already, sample_label).show()
