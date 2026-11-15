# -*- coding: utf-8 -*-
"""Add or edit one of the Revision Manager's extra columns.

Name, type of data, the choices for a choice list, and the parameter it is
pushed into. Modal; show() returns what to do, or None.
"""

import ps_refs  # noqa: F401  - must be first

from System.Windows import Visibility

import ps_revdata
import ps_ui


class ColumnDialog(object):
    """show() -> None, {'action': 'remove'}, or {'action': 'save', ...}."""

    # The three types of column: Custom - a column of its own, any type of
    # data - then the two Yes/No groups the Excel plots.
    NO_GROUP = u'Custom'

    def __init__(self, columns, column=None, parameter_lookup=None,
                 theme_name='dark', owner=None, group=u''):
        self.columns = columns
        self.column = column
        # The group a new column starts in - the + on a group's band.
        self.start_group = column.group if column is not None else group
        self.lookup = parameter_lookup
        self.result = None
        self._parameters = {}       # target -> [(name, storage)]

        self.window = ps_ui.load_window('ProSheetsRevColumn.xaml', theme_name)
        self.chrome = ps_ui.Chrome(self.window, on_close=self._cancel)
        if owner is not None:
            try:
                self.window.Owner = owner
            except Exception:
                pass

        self.name_box = ps_ui.find(self.window, 'ColumnNameBox')
        self.group_combo = ps_ui.find(self.window, 'ColumnGroupCombo')
        self.kind_combo = ps_ui.find(self.window, 'ColumnKindCombo')
        self.kind_note = ps_ui.find(self.window, 'ColumnKindNote')
        self.choices_panel = ps_ui.find(self.window, 'ChoicesPanel')
        self.choices_box = ps_ui.find(self.window, 'ColumnChoicesBox')
        self.target_combo = ps_ui.find(self.window, 'ColumnTargetCombo')
        self.parameter_combo = ps_ui.find(self.window, 'ColumnParameterCombo')
        self.parameter_note = ps_ui.find(self.window, 'ColumnParameterNote')
        self.status = ps_ui.find(self.window, 'StatusText')

        self._fill()
        self._wire()

    # ------------------------------------------------------------------
    def _fill(self):
        column = self.column
        ps_ui.set_text(ps_ui.find(self.window, 'SubtitleText'),
                       u'Edit "{0}"'.format(column.name) if column
                       else u'New revision column')
        ps_ui.set_text(self.name_box, column.name if column else u'')
        kind_labels = [label for _kind, label in ps_revdata.KINDS]
        ps_ui.fill_combo(self.kind_combo, kind_labels,
                         selected=ps_revdata.KIND_LABELS[column.kind]
                         if column else kind_labels[0])
        if column is not None:
            try:
                self.kind_combo.IsEnabled = False
            except Exception:
                pass
            ps_ui.set_visible(ps_ui.find(self.window, 'RemoveColumnButton'),
                              True)
        else:
            ps_ui.set_text(self.kind_note, u'Text, Yes/No, Number, Date or a '
                                           u'list of choices. It cannot be '
                                           u'changed once the column exists.')
        ps_ui.set_text(self.choices_box, u'\n'.join(column.choices)
                       if column else u'')
        status = self.start_group == ps_revdata.STATUS
        groups = [self.NO_GROUP] + [label for _g, label in ps_revdata.GROUPS]
        if status:
            groups = [ps_revdata.GROUP_LABELS[ps_revdata.STATUS]]
        ps_ui.fill_combo(self.group_combo, groups, selected=(
            ps_revdata.GROUP_LABELS.get(self.start_group) or self.NO_GROUP))
        if status or (column is not None and column.kind != 'yesno'):
            # Issue Status stays itself; a column that is not Yes/No cannot
            # join a group of ticks.
            try:
                self.group_combo.IsEnabled = False
            except Exception:
                pass
        target_labels = [label for _target, label in ps_revdata.TARGETS]
        ps_ui.fill_combo(self.target_combo, target_labels,
                         selected=ps_revdata.TARGET_LABELS[column.target]
                         if column else target_labels[0])
        self._group_changed()
        self._target_changed(keep=column.parameter if column else u'')

    def _wire(self):
        for name, handler in (('OkButton', self._ok),
                              ('CancelButton',
                               lambda sender, args: self._cancel()),
                              ('RemoveColumnButton', self._remove)):
            button = ps_ui.find(self.window, name)
            if button is not None:
                try:
                    button.Click += handler
                except Exception:
                    pass
        for combo, handler in (
                (self.group_combo,
                 lambda sender, args: self._group_changed()),
                (self.kind_combo, lambda sender, args: self._kind_changed()),
                (self.target_combo,
                 lambda sender, args: self._target_changed()),
                (self.parameter_combo,
                 lambda sender, args: self._parameter_changed())):
            if combo is not None:
                try:
                    combo.SelectionChanged += handler
                except Exception:
                    pass

    # ------------------------------------------------------------------
    def kind(self):
        label = ps_ui.combo_text(self.kind_combo)
        for kind, text in ps_revdata.KINDS:
            if text == label:
                return kind
        return 'text'

    def group(self):
        label = ps_ui.combo_text(self.group_combo)
        for group, text in ps_revdata.GROUP_LABELS.items():
            if group and text == label:
                return group
        return u''

    def _group_changed(self):
        """A grouped column is Yes/No: the type follows the group."""
        grouped = self.group() in (ps_revdata.ISSUED_TO, ps_revdata.METHOD)
        if grouped:
            ps_ui.fill_combo(self.kind_combo, [label for _k, label in
                                               ps_revdata.KINDS],
                             selected=ps_revdata.KIND_LABELS['yesno'])
        if self.column is None:
            try:
                self.kind_combo.IsEnabled = not grouped
            except Exception:
                pass
        self._kind_changed()

    def target(self):
        label = ps_ui.combo_text(self.target_combo)
        for target, text in ps_revdata.TARGETS:
            if text == label:
                return target
        return u''

    def parameter(self):
        try:
            return u'{0}'.format(self.parameter_combo.Text or u'').strip()
        except Exception:
            return ps_ui.combo_text(self.parameter_combo)

    def choices(self):
        try:
            text = u'{0}'.format(self.choices_box.Text or u'')
        except Exception:
            text = u''
        return [line.strip() for line in text.replace(u'\r', u'').split(u'\n')
                if line.strip()]

    def _kind_changed(self):
        ps_ui.set_visible(self.choices_panel, self.kind() == 'choice')
        self._parameter_changed()

    def _target_changed(self, keep=None):
        target = self.target()
        names = []
        if target:
            if target not in self._parameters:
                try:
                    self._parameters[target] = list(self.lookup(target)) \
                        if self.lookup else []
                except Exception:
                    self._parameters[target] = []
            names = [name for name, _storage in self._parameters[target]]
        wanted = keep if keep is not None else self.parameter()
        ps_ui.fill_combo(self.parameter_combo, names,
                         selected=wanted if wanted in names else None)
        try:
            self.parameter_combo.IsEnabled = bool(target)
            if wanted and wanted not in names:
                self.parameter_combo.Text = wanted
        except Exception:
            pass
        self._parameter_changed()

    def storage_of(self, name):
        for found, storage in self._parameters.get(self.target(), []):
            if found == name:
                return storage
        return u''

    def problem(self):
        """Why the mapping will not work, or u''."""
        target = self.target()
        name = self.parameter()
        if not target:
            return u''
        if not name:
            return u'Choose the parameter to push into.'
        storage = self.storage_of(name)
        if not storage:
            return (u'No sheet or cloud in the model has a writable "{0}". '
                    u'Add it as a project or shared parameter first; until '
                    u'then nothing is pushed.'.format(name)
                    if self._parameters.get(target) is not None else u'')
        if storage not in ps_revdata.ACCEPTS.get(self.kind(), ()):
            return (u'"{0}" holds {1}; a {2} column needs {3}.'.format(
                name, self._storage_words(storage),
                ps_revdata.KIND_LABELS[self.kind()],
                u' or '.join([self._storage_words(one) for one in
                              ps_revdata.ACCEPTS[self.kind()]])))
        return u''

    @staticmethod
    def _storage_words(storage):
        return {'String': u'text', 'Integer': u'a whole number or Yes/No',
                'Double': u'a number'}.get(storage, storage)

    def _parameter_changed(self):
        problem = self.problem()
        storage = self.storage_of(self.parameter())
        if problem:
            ps_ui.set_text(self.parameter_note, problem)
        elif self.target() and storage:
            ps_ui.set_text(self.parameter_note, u'A {0} parameter - each {1} '
                           u'takes the value on Apply.'.format(
                               self._storage_words(storage),
                               u'sheet' if self.target() == 'sheets'
                               else u'cloud'))
        else:
            ps_ui.set_text(self.parameter_note, u'')

    # ------------------------------------------------------------------
    def _ok(self, sender, args):
        try:
            name = u'{0}'.format(self.name_box.Text or u'')
        except Exception:
            name = u''
        reason = ps_revdata.column_problem(
            name, self.kind(), self.choices(), self.columns,
            self.column.id if self.column else None)
        problem = self.problem()
        if not reason and problem and self.storage_of(self.parameter()):
            reason = problem         # the wrong type of parameter
        if reason:
            ps_ui.set_text(self.status, reason)
            return
        self.result = {'action': 'save', 'name': name.strip(),
                       'kind': self.kind(), 'choices': self.choices(),
                       'target': self.target(),
                       'parameter': self.parameter() if self.target()
                       else u'',
                       'group': self.group()}
        self._close(True)

    def _remove(self, sender, args):
        self.result = {'action': 'remove'}
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
