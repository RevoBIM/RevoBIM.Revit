# -*- coding: utf-8 -*-
"""Add revision: everything about a new revision, and where it goes.

Opened by the Revision Manager's Add. The first thing asked - washed and
edged in orange so it is the first thing looked at - is the **sequence** it
takes, defaulting to last. The revision already at that sequence, and every
one after it, moves down a slot. Then every property Revit holds for a
revision, and the manager's own columns.

Modal. show() returns None, or {'position': int, 'fields': {field: value},
'custom': {column id: stored value}}. Nothing is written here: the manager
stages it, green, and Apply creates it.
"""

import ps_refs  # noqa: F401  - must be first

from System.Windows import GridLength, Thickness, VerticalAlignment
from System.Windows.Controls import (CheckBox, ColumnDefinition, ComboBox,
                                     Grid, TextBlock, TextBox)
from System.Windows.Input import Key

import ps_revdata
import ps_revisions
import ps_ui


# field, label, kind - the revision's own properties, as the grid orders them
FIELDS = [
    ('numbering', u'Numbering', 'numbering'),
    ('date', u'Date', 'text'),
    ('desc', u'Description', 'text'),
    ('issued_to', u'Issued to', 'text'),
    ('issued_by', u'Issued by', 'text'),
    ('show', u'Show', 'show'),
    ('issued', u'Issued', 'check'),
]


def read_position(text, count):
    """(ok, sequence or why not) for what is typed in the Sequence box.

    ``count`` live revisions, so 1 to count + 1 - one past the end is last.
    """
    try:
        value = int(u'{0}'.format(text or u'').strip())
    except Exception:
        return False, u'The sequence is a whole number, 1 to {0}.'.format(
            count + 1)
    if value < 1 or value > count + 1:
        return False, u'The sequence has to be 1 to {0}.'.format(count + 1)
    return True, value


def position_note(position, rows):
    """What a sequence will do, in words.

    ``rows`` is [(sequence, label)] for the live revisions in order.
    """
    count = len(rows)
    if position > count:
        return u'Goes in last, as sequence {0}.'.format(count + 1)
    sequence, label = rows[position - 1]
    moved = count - position + 1
    return (u'Goes in at sequence {0}. {1} moves down to {2}{3}.'.format(
        position, label or u'Sequence {0}'.format(sequence), position + 1,
        u'' if moved == 1 else
        u', and the {0} after it each move down one'.format(moved - 1)))


def _pick(combo, text):
    """Select the item reading ``text``, if there is one."""
    try:
        for index in range(combo.Items.Count):
            if u'{0}'.format(combo.Items[index]) == u'{0}'.format(text or u''):
                combo.SelectedIndex = index
                return True
    except Exception:
        pass
    return False


def starting_position(position, count):
    """Where the sequence box starts: the position asked for, kept to 1 to
    count + 1 - one past the end being last."""
    try:
        position = int(position)
    except Exception:
        return count + 1
    return max(1, min(count + 1, position))


def row_label(staging, key):
    entry = staging.entries[key]
    desc = entry.fields.get('desc') or u''
    date = entry.fields.get('date') or u''
    parts = [part for part in (date, desc) if part]
    return u'"{0}"'.format(u' - '.join(parts)) if parts else \
        u'Sequence {0}'.format(staging.staged_sequence(key))


class AddDialog(object):

    def __init__(self, staging, theme_name='dark', owner=None,
                 position=None, note=u'', edit_key=None):
        """``position`` is the sequence to start on - last when None, kept
        to 1 .. last. ``note`` goes in the footer: what happens once it is
        made, when that is more than "it is created on Apply".

        ``edit_key`` makes it the Edit revision window instead: the fields
        filled in from that revision, the sequence shown but fixed - moving
        a revision is the Revision Manager's Move up and Move down - and
        Apply in place of Add."""
        self.staging = staging
        self.edit_key = edit_key
        self.rows = [(staging.staged_sequence(key), row_label(staging, key))
                     for key in staging.live_order()]
        self.count = len(self.rows)
        self.result = None
        self.controls = {}       # field or 'x_<id>' -> its control

        self.window = ps_ui.load_window('ProSheetsRevAdd.xaml', theme_name)
        self.chrome = ps_ui.Chrome(self.window, on_close=self._cancel)
        if owner is not None:
            try:
                self.window.Owner = owner
            except Exception:
                pass
        self.form = ps_ui.find(self.window, 'AddForm')
        self.box = ps_ui.find(self.window, 'SequenceBox')
        self.note = ps_ui.find(self.window, 'SequenceNote')
        self.status = ps_ui.find(self.window, 'StatusText')
        ps_ui.set_text(ps_ui.find(self.window, 'SequenceRange'),
                       u'of {0}  (1 is the top)'.format(self.count + 1))
        self._build()
        ps_ui.set_text(self.box, u'{0}'.format(self.count + 1))
        if edit_key is not None:
            self._as_edit(edit_key)
        elif position is not None:
            ps_ui.set_text(self.box, u'{0}'.format(
                starting_position(position, self.count)))
        if note:
            ps_ui.set_text(self.status, note)
        self._wire()
        self._paint_note()
        try:
            self.box.Focus()
            self.box.SelectAll()
        except Exception:
            pass

    # ------------------------------------------------------------------
    def _as_edit(self, key):
        entry = self.staging.entries[key]
        sequence = self.staging.staged_sequence(key) or 1
        ps_ui.set_text(ps_ui.find(self.window, 'DialogSubtitle'),
                       u'Edit revision')
        ps_ui.set_content(ps_ui.find(self.window, 'OkButton'), u'Apply')
        ps_ui.set_text(self.box, u'{0}'.format(sequence))
        try:
            self.box.IsReadOnly = True
        except Exception:
            pass
        for name in ('SequenceDownButton', 'SequenceUpButton'):
            ps_ui.set_visible(ps_ui.find(self.window, name), False)
        ps_ui.set_text(ps_ui.find(self.window, 'SequenceRange'),
                       u'of {0}'.format(self.count))
        for field, _label, kind in FIELDS:
            control = self.controls.get(field)
            if control is None:
                continue
            value = entry.fields.get(field)
            if kind == 'check':
                control.IsChecked = bool(value)
            elif kind in ('numbering', 'show'):
                _pick(control, value)
            else:
                control.Text = u'{0}'.format(value or u'')
        for column in self.staging.columns:
            control = self.controls.get(u'x_' + column.id)
            if control is None:
                continue
            stored = self.staging.custom_value(entry, column)
            if column.kind == 'yesno':
                control.IsChecked = stored == u'1'
            elif column.kind == 'choice':
                _pick(control, stored)
            else:
                control.Text = stored
        ps_ui.set_text(self.status, (
            u'Issued: Revit keeps it as it is. Untick Issued to change the '
            u'rest - your own columns can change either way.')
            if entry.fields.get('issued') else
            u'Written to the model on Apply.')

    def _line(self, label_text):
        line = Grid()
        line.Margin = Thickness(0, 0, 0, 8)
        for width in (130, None):
            definition = ColumnDefinition()
            if width:
                definition.Width = GridLength(width)
            line.ColumnDefinitions.Add(definition)
        label = TextBlock()
        label.Text = label_text
        label.VerticalAlignment = VerticalAlignment.Center
        label.SetResourceReference(TextBlock.StyleProperty, 'FieldLabel')
        Grid.SetColumn(label, 0)
        line.Children.Add(label)
        self.form.Children.Add(line)
        return line

    def _place(self, line, control):
        Grid.SetColumn(control, 1)
        line.Children.Add(control)

    def _build(self):
        if self.form is None:
            return
        live = self.staging.live_order()
        numbering = self.staging.entries[live[-1]].fields.get('numbering') \
            if live else (self.staging.sequences[0]
                          if self.staging.sequences else u'')
        for field, label, kind in FIELDS:
            if kind == 'numbering' and not self.staging.sequences:
                continue            # Revit 2021: no numbering sequences
            line = self._line(label)
            if kind == 'numbering':
                control = ComboBox()
                ps_ui.fill_combo(control, self.staging.sequences,
                                 selected=numbering)
            elif kind == 'show':
                control = ComboBox()
                ps_ui.fill_combo(control, ps_revisions.SHOW_LABELS,
                                 selected=ps_revisions.DEFAULT_SHOW)
            elif kind == 'check':
                control = CheckBox()
                control.IsChecked = False
                control.Content = u'Issued once created - Revit then ' \
                    u'locks it'
            else:
                control = TextBox()
                control.Height = 28
            self._place(line, control)
            self.controls[field] = control
        for column in self.staging.columns:
            line = self._line(column.name)
            if column.kind == 'yesno':
                control = CheckBox()
                control.IsChecked = False
            elif column.kind == 'choice':
                control = ComboBox()
                ps_ui.fill_combo(control, [u''] + list(column.choices or []),
                                 selected=u'')
            else:
                control = TextBox()
                control.Height = 28
                control.Tag = ps_revdata.KIND_LABELS.get(column.kind, u'')
            self._place(line, control)
            self.controls[u'x_' + column.id] = control

    def _wire(self):
        for name, step in (('SequenceDownButton', -1),
                           ('SequenceUpButton', 1)):
            button = ps_ui.find(self.window, name)
            if button is not None:
                try:
                    button.Click += self._make_step(step)
                except Exception:
                    pass
        if self.box is not None:
            try:
                self.box.TextChanged += lambda sender, args: \
                    self._paint_note()
            except Exception:
                pass
        for name, handler in (('OkButton', self._ok),
                              ('CancelButton',
                               lambda sender, args: self._cancel())):
            button = ps_ui.find(self.window, name)
            if button is not None:
                try:
                    button.Click += handler
                except Exception:
                    pass
        try:
            self.window.PreviewKeyDown += self._key
        except Exception:
            pass

    def _make_step(self, step):
        def handler(sender, args):
            ok, value = read_position(self._typed(), self.count)
            value = value if ok else self.count + 1
            value = max(1, min(self.count + 1, value + step))
            ps_ui.set_text(self.box, u'{0}'.format(value))
        return handler

    def _typed(self):
        try:
            return u'{0}'.format(self.box.Text or u'')
        except Exception:
            return u''

    def _paint_note(self):
        if self.edit_key is not None:
            ps_ui.set_text(self.note, u'Sequence {0}. To move it, use Move up '
                           u'and Move down in the Revision Manager.'.format(
                               self._typed()))
            return
        ok, value = read_position(self._typed(), self.count)
        ps_ui.set_text(self.note, position_note(value, self.rows) if ok
                       else value)

    def _key(self, sender, args):
        try:
            if args.Key == Key.Escape:
                self._cancel()
                args.Handled = True
        except Exception:
            pass

    # ------------------------------------------------------------------
    def answers(self):
        """(ok, the result, or why not)."""
        ok, position = read_position(self._typed(), self.count)
        if not ok:
            return False, position
        fields = {}
        for field, _label, kind in FIELDS:
            control = self.controls.get(field)
            if control is None:
                continue
            if kind == 'check':
                fields[field] = bool(control.IsChecked)
            elif kind in ('numbering', 'show'):
                fields[field] = ps_ui.combo_text(control, blank_text=u'')
            else:
                fields[field] = u'{0}'.format(control.Text or u'').strip()
        custom = {}
        for column in self.staging.columns:
            control = self.controls.get(u'x_' + column.id)
            if control is None:
                continue
            if column.kind == 'yesno':
                value = bool(control.IsChecked)
            elif column.kind == 'choice':
                value = ps_ui.combo_text(control, blank_text=u'')
            else:
                value = u'{0}'.format(control.Text or u'')
            good, stored = ps_revdata.normalise(column, value)
            if not good:
                return False, stored
            custom[column.id] = stored
        return True, {'position': position, 'fields': fields,
                      'custom': custom}

    def _ok(self, sender, args):
        ok, answer = self.answers()
        if not ok:
            ps_ui.set_text(self.status, answer)
            return
        self.result = answer
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


def ask(staging, theme_name='dark', owner=None, position=None, note=u''):
    return AddDialog(staging, theme_name, owner, position, note).show()


def ask_edit(staging, key, theme_name='dark', owner=None):
    """The Edit revision window for one revision, or None if cancelled."""
    return AddDialog(staging, theme_name, owner, None, u'',
                     edit_key=key).show()
