# -*- coding: utf-8 -*-
"""Revision Manager settings: the model's own columns and their mapping.

A table, one row per column the user has added: its name, type, where its
values are pushed (Sheets / Revision clouds / nowhere) and into which
parameter. Only instance parameters bound to that category, holding data the
column can be written as, are offered - ps_revdata.usable decides, and
ps_revdata.why_not says why a mapped name no longer fits.

Modal. show() returns None, or {'action': 'save' | 'project_parameters',
'columns': [(id, name, target, parameter)]}. Nothing is written here; the
manager stages it and Apply writes it.
"""

import ps_refs  # noqa: F401  - must be first

from System.Windows import (GridLength, TextWrapping, Thickness,
                            VerticalAlignment)
from System.Windows.Controls import (ColumnDefinition, ComboBox, Grid,
                                     TextBlock, TextBox)

import ps_revdata
import ps_ui


# target, as the table words it
TARGETS = [(u'', u'Nowhere'), ('sheets', u'Sheets'), ('clouds', u'Revision clouds')]
WIDTHS = [190, 84, 130, 280, 0]
HEADINGS = [u'Column', u'Type', u'Push to', u'Parameter', u'Status']
PARAMETER_TIP = (u'Type part of the parameter\'s name - the list narrows to '
                 u'the names containing it ("rev note" finds Revision '
                 u'Notes). The caret shows the whole list.')


def target_of(label):
    for target, text in TARGETS:
        if text == label:
            return target
    return u''


def label_of(target):
    for one, text in TARGETS:
        if one == target:
            return text
    return TARGETS[0][1]


def status_of(parameters, column_kind, target, parameter):
    """(ok, words) for one row - what the Status cell says."""
    if not target:
        return True, u'Kept in the model only'
    if not parameter:
        return False, u'Choose a parameter'
    problem = ps_revdata.why_not(parameters, target, column_kind, parameter)
    if problem:
        return False, problem
    return True, u'Pushed into "{0}" on every Apply'.format(parameter)


class SettingsDialog(object):

    def __init__(self, columns, parameter_reader=None, theme_name='dark',
                 owner=None):
        self.columns = [column.copy() for column in columns]
        self.reader = parameter_reader
        self.parameters = []
        self.rows = []           # (column, name box, target combo, parameter picker, status)
        self.result = None
        self._suspend = False

        self.window = ps_ui.load_window('ProSheetsRevSettings.xaml', theme_name)
        self.chrome = ps_ui.Chrome(self.window, on_close=self._cancel)
        if owner is not None:
            try:
                self.window.Owner = owner
            except Exception:
                pass
        self.table = ps_ui.find(self.window, 'MappingTable')
        self.status = ps_ui.find(self.window, 'StatusText')
        try:
            ps_ui.find(self.window, 'MappingHelp').ToolTip = \
                ps_revdata.MAPPING_HELP
        except Exception:
            pass
        self._read_parameters()
        self._build()
        self._wire()

    # ------------------------------------------------------------------
    def _read_parameters(self):
        try:
            self.parameters = list(self.reader()) if self.reader else []
        except Exception:
            self.parameters = []

    def _line(self):
        line = Grid()
        line.Margin = Thickness(0, 0, 0, 6)
        for width in WIDTHS:
            definition = ColumnDefinition()
            if width:
                definition.Width = GridLength(width)
            line.ColumnDefinitions.Add(definition)
        return line

    def _place(self, line, element, index):
        Grid.SetColumn(element, index)
        element.Margin = Thickness(0, 0, 8, 0)
        line.Children.Add(element)

    def _build(self):
        if self.table is None:
            return
        self._suspend = True
        try:
            self.table.Children.Clear()
            self.rows = []
            ps_ui.set_visible(ps_ui.find(self.window, 'MappingEmpty'),
                              not self.columns)
            if not self.columns:
                return
            head = self._line()
            for index, text in enumerate(HEADINGS):
                label = TextBlock()
                label.Text = text
                label.SetResourceReference(TextBlock.StyleProperty, 'FieldLabel')
                if text == u'Push to':
                    label.ToolTip = ps_revdata.MAPPING_HELP
                elif text == u'Parameter':
                    label.ToolTip = PARAMETER_TIP
                self._place(head, label, index)
            self.table.Children.Add(head)
            for column in self.columns:
                self._add_row(column)
        finally:
            self._suspend = False
        for row in self.rows:
            self._paint(row)

    def _add_row(self, column):
        line = self._line()
        name = TextBox()
        name.Text = column.name
        name.Height = 28
        self._place(line, name, 0)
        kind = TextBlock()
        kind.Text = ps_revdata.KIND_LABELS.get(column.kind, column.kind)
        kind.VerticalAlignment = VerticalAlignment.Center
        self._place(line, kind, 1)
        target = ComboBox()
        target.Height = 28
        target.ToolTip = ps_revdata.MAPPING_HELP
        ps_ui.fill_combo(target, [text for _one, text in TARGETS],
                         selected=label_of(column.target))
        self._place(line, target, 2)
        # Type into the Parameter box itself: the list under it narrows to
        # the names containing what is typed.
        parameter = ps_ui.SearchPicker(hint=u'Type to search parameters',
                                       matcher=ps_revdata.matching)
        self._place(line, parameter.element, 3)
        status = TextBlock()
        status.TextWrapping = TextWrapping.Wrap
        status.VerticalAlignment = VerticalAlignment.Center
        self._place(line, status, 4)
        self.table.Children.Add(line)
        row = (column, name, target, parameter, status)
        self.rows.append(row)
        self._fill_parameters(row, column.parameter)
        target.SelectionChanged += self._make_changed(row, True)
        parameter.on_change = self._make_picked(row)

    def _fill_parameters(self, row, keep):
        """The parameters this row may use - plus the mapped one if it no
        longer qualifies, so the user can see what it was and why not."""
        column, _name, target, parameter, _status = row
        where = target_of(ps_ui.combo_text(target))
        names = [one for one, _data in
                 ps_revdata.usable(self.parameters, where, column.kind)] \
            if where else []
        items = list(names)
        if keep and keep not in items:
            items.append(keep)
        self._suspend = True
        try:
            parameter.set_items(items, keep if where else u'')
            parameter.set_enabled(bool(where))
        except Exception:
            pass
        finally:
            self._suspend = False

    def _make_picked(self, row):
        """Typed into, or a name picked: say what the row will do."""
        def picked(picker):
            if not self._suspend:
                self._paint(row)
        return picked

    def _make_changed(self, row, target_changed):
        def changed(sender, args):
            if self._suspend:
                return
            if target_changed:
                self._fill_parameters(row, self._parameter(row))
            self._paint(row)
        return changed

    def _parameter(self, row):
        return row[3].value

    def _paint(self, row):
        column, _name, target, _parameter, status = row
        ok, words = status_of(self.parameters, column.kind,
                              target_of(ps_ui.combo_text(target)),
                              self._parameter(row))
        typed = row[3].text().strip()
        if typed and not self._parameter(row):
            ok, words = False, u'No parameter here contains "{0}"'.format(
                typed) if not row[3].shown(row[3].items, typed, u'',
                                           row[3].matcher) \
                else u'Pick one of the matches for "{0}"'.format(typed)
        ps_ui.set_text(status, words)
        try:
            status.SetResourceReference(TextBlock.ForegroundProperty,
                                        'GreenBrush' if ok else 'OrangeBrush')
            status.ToolTip = words
        except Exception:
            pass

    def _wire(self):
        for name, handler in (('OkButton', lambda sender, args: self._finish('save')),
                              ('CancelButton', lambda sender, args: self._cancel()),
                              ('ProjectParamsButton',
                               lambda sender, args: self._finish(
                                   'project_parameters')),
                              ('RefreshParamsButton', self._refresh)):
            button = ps_ui.find(self.window, name)
            if button is not None:
                try:
                    button.Click += handler
                except Exception:
                    pass

    def _refresh(self, sender, args):
        self._read_parameters()
        for row in self.rows:
            self._fill_parameters(row, self._parameter(row))
            self._paint(row)
        ps_ui.set_text(self.status, u'{0} usable parameter{1} on Sheets and '
                       u'Revision Clouds.'.format(
                           len(ps_revdata.usable(self.parameters, 'sheets')) +
                           len(ps_revdata.usable(self.parameters, 'clouds')),
                           u'' if len(self.parameters) == 1 else u's'))

    def answers(self):
        """[(id, name, target, parameter)] as the table stands."""
        out = []
        for row in self.rows:
            column, name, target, _parameter, _status = row
            try:
                text = u'{0}'.format(name.Text or u'').strip()
            except Exception:
                text = column.name
            where = target_of(ps_ui.combo_text(target))
            out.append((column.id, text, where,
                        self._parameter(row) if where else u''))
        return out

    def _finish(self, action):
        answers = self.answers()
        for column_id, name, target, parameter in answers:
            column = [one for one in self.columns if one.id == column_id][0]
            others = [one for one in self.columns if one.id != column_id]
            renamed = [ps_revdata.Column(one[0], one[1]) for one in answers
                       if one[0] != column_id]
            problem = ps_revdata.column_problem(name, column.kind,
                                                column.choices or [u'-'],
                                                renamed or others)
            if problem:
                ps_ui.set_text(self.status, problem)
                return
            # A parameter that exists but holds the wrong data would push
            # nothing but errors; one not added yet is allowed, and says so.
            reason = ps_revdata.why_not(self.parameters, target, column.kind,
                                        parameter) if target else u''
            if reason and [one for one in self.parameters
                           if one.get('name') == parameter]:
                ps_ui.set_text(self.status, reason)
                return
        self.result = {'action': action, 'columns': answers}
        self._close(True)

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
