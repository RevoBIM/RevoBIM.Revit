# -*- coding: utf-8 -*-
"""Change revision on sheet: which revision the picked cells become.

Opened from the Document Register once one or more revision cells are
picked. Lists every revision in the project; issued ones are shown but
cannot be chosen, because Revit will not put an issued revision on a sheet
or move a cloud onto one. Modal. show() returns the chosen revision's
element key, or None.

Nothing is written here. The register puts the change through the external
event - see ps_revisions.swap_on_sheets.
"""

import ps_refs  # noqa: F401  - must be first

from System.Windows import Thickness
from System.Windows.Controls import (ListBoxItem, Orientation, StackPanel,
                                     TextBlock)
from System.Windows.Input import Key

import ps_ui


def describe(revision):
    """One line for a revision in the list: sequence, date, description."""
    parts = [u'Seq {0}'.format(revision.sequence)]
    if revision.date:
        parts.append(u'{0}'.format(revision.date))
    if revision.description:
        parts.append(u'{0}'.format(revision.description))
    return u'  ·  '.join(parts)


def matches(revision, text):
    """Every word typed appears in the line, any case."""
    words = u'{0}'.format(text or u'').lower().split()
    line = describe(revision).lower()
    return all([word in line for word in words])


def choosable(revision, olds):
    """(can it be chosen, why not). Issued is locked; choosing what every
    picked cell already is would change nothing."""
    if getattr(revision, 'issued', False):
        return False, u'issued - Revit keeps it locked'
    if olds and set([u'{0}'.format(revision.element_key)]) == set(olds):
        return False, u'every picked cell is this already'
    return True, u''


class SwapDialog(object):

    def __init__(self, revisions, olds, sheet_count, cell_count,
                 theme_name='dark', owner=None, headline=None,
                 from_text=None, note=None, ok_text=None):
        """``revisions`` are ps_register.RevisionColumn; ``olds`` the element
        keys the picked cells are now. The wording can be replaced for
        another use of the same list - Assign revision to selected."""
        self.revisions = sorted(list(revisions or []),
                                key=lambda one: one.sequence)
        self.olds = [u'{0}'.format(one) for one in (olds or [])]
        self.result = None
        self.items = []          # (revision, ListBoxItem, can choose)

        self.window = ps_ui.load_window('ProSheetsRevSwap.xaml', theme_name)
        self.chrome = ps_ui.Chrome(self.window, on_close=self._cancel)
        if owner is not None:
            try:
                self.window.Owner = owner
            except Exception:
                pass
        self.list = ps_ui.find(self.window, 'SwapList')
        self.search = ps_ui.find(self.window, 'SwapSearch')
        self.ok = ps_ui.find(self.window, 'OkButton')
        self.status = ps_ui.find(self.window, 'StatusText')

        ps_ui.set_text(ps_ui.find(self.window, 'SwapHeadline'), headline or (
            u'{0} revision cell{1} on {2} sheet{3}'.format(
                cell_count, u'' if cell_count == 1 else u's',
                sheet_count, u'' if sheet_count == 1 else u's')))
        by_key = dict([(u'{0}'.format(one.element_key), one)
                       for one in self.revisions])
        ps_ui.set_text(ps_ui.find(self.window, 'SwapFrom'), from_text or (
            u'Now: ' + (u';  '.join([describe(by_key[key])
                                     for key in self.olds
                                     if key in by_key]) or u'-')))
        if note:
            ps_ui.set_text(ps_ui.find(self.window, 'SwapNote'), note)
        if ok_text:
            ps_ui.set_content(self.ok, ok_text)
        self._fill()
        self._wire()

    def _fill(self):
        if self.list is None:
            return
        self.list.Items.Clear()
        self.items = []
        for revision in self.revisions:
            ok, why = choosable(revision, self.olds)
            item = ListBoxItem()
            row = StackPanel()
            row.Orientation = Orientation.Horizontal
            line = TextBlock()
            line.Text = describe(revision)
            row.Children.Add(line)
            if not ok:
                note = TextBlock()
                note.Text = u'  ({0})'.format(why)
                note.Margin = Thickness(4, 0, 0, 0)
                note.SetResourceReference(TextBlock.ForegroundProperty,
                                          'MutedBrush')
                row.Children.Add(note)
                item.IsEnabled = False
                item.Opacity = 0.55
            if u'{0}'.format(revision.element_key) in self.olds:
                line.SetResourceReference(TextBlock.ForegroundProperty,
                                          'OrangeBrush')
            item.Content = row
            item.ToolTip = revision.describe()
            self.list.Items.Add(item)
            self.items.append((revision, item, ok))

    def _wire(self):
        if self.list is not None:
            try:
                self.list.SelectionChanged += self._picked
                self.list.MouseDoubleClick += self._double
            except Exception:
                pass
        if self.search is not None:
            try:
                self.search.TextChanged += self._searched
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

    def chosen(self):
        try:
            item = self.list.SelectedItem
        except Exception:
            return None
        for revision, one, ok in self.items:
            if one is item and ok:
                return revision
        return None

    def _picked(self, sender, args):
        revision = self.chosen()
        try:
            self.ok.IsEnabled = revision is not None
        except Exception:
            pass
        ps_ui.set_text(self.status, u'Change to: {0}'.format(
            describe(revision)) if revision is not None
            else u'Pick the revision to change them to.')

    def _searched(self, sender, args):
        try:
            text = u'{0}'.format(self.search.Text or u'')
        except Exception:
            text = u''
        for revision, item, _ok in self.items:
            ps_ui.set_visible(item, matches(revision, text))

    def _double(self, sender, args):
        if self.chosen() is not None:
            self._ok(sender, args)

    def _key(self, sender, args):
        try:
            if args.Key == Key.Escape:
                self._cancel()
                args.Handled = True
        except Exception:
            pass

    def _ok(self, sender, args):
        revision = self.chosen()
        if revision is None:
            return
        self.result = u'{0}'.format(revision.element_key)
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


def choose(revisions, olds, sheet_count, cell_count, theme_name='dark',
           owner=None, **wording):
    return SwapDialog(revisions, olds, sheet_count, cell_count, theme_name,
                      owner, **wording).show()
