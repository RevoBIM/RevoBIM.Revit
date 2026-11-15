# -*- coding: utf-8 -*-
"""The subfolder parameter picker.

The Create tab used to borrow the Custom File Name dialog for this, which
was wrong in a way that is obvious once you see it: naming a file and
building a folder tree are different jobs. A file name is one string with
prefixes, suffixes and separators; a folder path is a stack of levels. The
naming dialog offered four columns of things that mean nothing to a folder
and no way at all to say "and this is a new level down".

So this is its own window: a searchable list of every sheet and project
parameter plus the date and time tokens, and two buttons - add as a folder
level, or add to the level being built.

The preview underneath is resolved against a real sheet, so an empty
parameter shows up here rather than as a folder called ``_unset`` after two
hundred files have gone into it.
"""

import ps_refs  # noqa: F401  - must be first

from System import String
from System.Data import DataTable

import ps_paths
import ps_ui


ALL_GROUPS = u'All'


class TokenWindow(object):
    """Modal. Returns the finished token string, or None when cancelled."""

    def __init__(self, catalogue, sample_lookup, current=u'',
                 theme_name='dark', owner=None, sample_label=u''):
        self.catalogue = catalogue or []
        self.sample_lookup = sample_lookup
        self.result = None

        self.window = ps_ui.load_window('ProSheetsTokens.xaml', theme_name)
        self.chrome = ps_ui.Chrome(self.window, on_close=self._cancel)
        if owner is not None:
            try:
                self.window.Owner = owner
            except Exception:
                pass

        self.grid = ps_ui.find(self.window, 'TokenGrid')
        self.group_combo = ps_ui.find(self.window, 'TokenGroupCombo')
        self.search_box = ps_ui.find(self.window, 'TokenSearchBox')
        self.string_box = ps_ui.find(self.window, 'TokenStringBox')
        self.preview = ps_ui.find(self.window, 'TokenPreview')

        self.entries = ps_paths.token_catalogue(self.catalogue)

        self.table = DataTable('tokens')
        for name in ('pname', 'pgroup', 'sample'):
            self.table.Columns.Add(name, String)
        try:
            self.grid.ItemsSource = self.table.DefaultView
        except Exception:
            pass

        if sample_label:
            ps_ui.set_text(ps_ui.find(self.window, 'TokenHint'),
                           u'Values shown are from {0}. Double click a row to '
                           u'add it as a folder level.'.format(sample_label))

        try:
            self.string_box.Text = u'{0}'.format(current or u'')
        except Exception:
            pass

        self._fill_groups()
        self._fill_rows()
        self._wire()
        self._refresh_preview()

    # ------------------------------------------------------------- the list
    def _fill_groups(self):
        groups = []
        for _name, group, _sample in self.entries:
            if group not in groups:
                groups.append(group)
        groups.sort(key=lambda g: (g != u'Date and time', g.lower()))
        ps_ui.fill_combo(self.group_combo, [ALL_GROUPS] + groups,
                         selected=ALL_GROUPS)

    def _sample_for(self, name, canned):
        if canned:
            return canned
        stamped = ps_paths.time_token(name)
        if stamped is not None:
            return stamped
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
            for name, owning_group, canned in self.entries:
                if group != ALL_GROUPS and owning_group != group:
                    continue
                if needle and needle not in name.lower():
                    continue
                row = self.table.NewRow()
                row['pname'] = name
                row['pgroup'] = owning_group
                row['sample'] = self._sample_for(name, canned)
                self.table.Rows.Add(row)
        except Exception:
            pass
        ps_ui.set_text(ps_ui.find(self.window, 'StatusText'),
                       u'{0} showing'.format(self.table.Rows.Count))

    # ------------------------------------------------------------- the string
    def _chosen_names(self):
        found = []
        if self.grid is None:
            return found
        try:
            for item in self.grid.SelectedItems:
                row = getattr(item, 'Row', None)
                if row is None:
                    continue
                found.append(u'{0}'.format(row['pname']))
        except Exception:
            return []
        return found

    def _current(self):
        try:
            return u'{0}'.format(self.string_box.Text or u'')
        except Exception:
            return u''

    def _set_current(self, text):
        try:
            self.string_box.Text = text
        except Exception:
            pass
        self._refresh_preview()

    def _add(self, as_level):
        names = self._chosen_names()
        if not names:
            ps_ui.set_text(ps_ui.find(self.window, 'StatusText'),
                           u'Pick a parameter first.')
            return
        tokens = u''.join([u'{{{0}}}'.format(name) for name in names]) \
            if not as_level else \
            u'\\'.join([u'{{{0}}}'.format(name) for name in names])
        current = self._current().rstrip()
        if not current:
            self._set_current(tokens)
            return
        if as_level:
            self._set_current(current.rstrip('\\/') + u'\\' + tokens)
        else:
            self._set_current(current + tokens)

    def _refresh_preview(self):
        text = self._current()
        if not text.strip():
            ps_ui.set_text(self.preview, u'(everything in the root folder)')
            return
        try:
            expanded = ps_paths.expand(text, self.sample_lookup or (lambda n: u''))
        except Exception:
            expanded = u''
        ps_ui.set_text(self.preview, expanded or u'(nothing)')

    # -------------------------------------------------------------- wiring
    def _wire(self):
        pairs = [
            ('AddLevelButton', lambda s, a: self._add(True)),
            ('AppendButton', lambda s, a: self._add(False)),
            ('ClearTokensButton', lambda s, a: self._set_current(u'')),
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
        if self.string_box is not None:
            try:
                self.string_box.TextChanged += self._string_changed
            except Exception:
                pass
        if self.grid is not None:
            try:
                self.grid.MouseDoubleClick += (lambda s, a: self._add(True))
            except Exception:
                pass

    def _filter_changed(self, sender, args):
        self._fill_rows()

    def _string_changed(self, sender, args):
        self._refresh_preview()

    # -------------------------------------------------------------- closing
    def _ok(self, sender, args):
        self.result = self._current().strip()
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


def pick(catalogue, sample_lookup, current=u'', theme_name='dark',
         owner=None, sample_label=u''):
    return TokenWindow(catalogue, sample_lookup, current, theme_name, owner,
                       sample_label).show()
