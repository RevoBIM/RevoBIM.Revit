# -*- coding: utf-8 -*-
"""Every smaller window. Each is a ThemedWindow, so each has the drawer."""
import pm_clr
import clr
import os

from System import Boolean, Int32, String
from System.Collections.Generic import List
from System.Data import DataTable
from System.Windows import Visibility
from System.Windows.Threading import DispatcherTimer
from System import TimeSpan
from Microsoft.Win32 import OpenFileDialog

import pm_chrome
import pm_core as core
import pm_spfile as spfile


def string_list(items):
    out = List[String]()
    for item in items:
        out.Add(item)
    return out


def make_table(columns):
    table = DataTable()
    for name, kind in columns:
        table.Columns.Add(name, clr.GetClrType(kind))
    return table



class Dialog(pm_chrome.ThemedWindow):
    def __init__(self, layout, title, owner):
        pm_chrome.ThemedWindow.__init__(self, layout, title, owner.settings, owner)
        self.result = None
        yes = self.e('YesBtn')
        if yes is not None:
            yes.Click += self.on_yes
        no = self.e('NoBtn')
        if no is not None:
            no.Click += self.on_no

    def on_yes(self, sender, args):
        self.result = True
        self.win.Close()

    def on_no(self, sender, args):
        self.result = None
        self.win.Close()

    def show(self):
        self.win.ShowDialog()
        return self.result


def ask(owner, title, text, yes=u'OK', no=u'Cancel'):
    box = Dialog('Prompt.xaml', title, owner)
    box.e('Message').Text = text
    box.e('YesBtn').Content = yes
    if no:
        box.e('NoBtn').Content = no
    else:
        box.e('NoBtn').Visibility = Visibility.Collapsed
    return bool(box.show())


def tell(owner, title, text):
    ask(owner, title, text, no=None)


class InputDialog(Dialog):
    def __init__(self, owner, title, label, value=u'', choices=None):
        Dialog.__init__(self, 'Input.xaml', title, owner)
        self.e('Label').Text = label
        self.choices = choices
        if choices is not None:
            self.e('Box').Visibility = Visibility.Collapsed
            pick = self.e('Pick')
            pick.Visibility = Visibility.Visible
            pick.ItemsSource = string_list(choices)
            pick.SelectedItem = value if value in choices else (choices[0] if choices else None)
        else:
            self.e('Box').Text = value

    def on_yes(self, sender, args):
        if self.choices is not None:
            self.result = core.to_text(self.e('Pick').SelectedItem)
        else:
            self.result = self.e('Box').Text.strip()
        self.win.Close()


def ask_text(owner, title, label, value=u''):
    return InputDialog(owner, title, label, value).show()


def ask_choice(owner, title, label, choices, value=None):
    return InputDialog(owner, title, label, value, choices).show()


class CategoriesWindow(Dialog):
    """Ticks what the parameter has. Across several parameters an orange mark means 'some of them':
    left alone, those stay as they are on each parameter."""

    def __init__(self, owner, labels, sets, groups, groups_file):
        Dialog.__init__(self, 'Categories.xaml', u'Categories', owner)
        self.groups = groups
        self.groups_file = groups_file
        self.busy = True
        every, some = core.shared_state(sets)
        self.rows = []
        self.table = make_table((('tick', Boolean), ('mixed', Boolean), ('name', String),
                                 ('disc', String), ('sub', Boolean), ('vis', String)))
        for label in sorted(labels, key=lambda t: t.lower()):
            row = self.table.NewRow()
            row['tick'] = label in every
            row['mixed'] = label in some
            row['name'] = label
            row['disc'] = core.category_discipline(label)
            row['sub'] = u' | ' in label
            row['vis'] = u'1'
            self.table.Rows.Add(row)
            self.rows.append(row)
        self.view = self.table.DefaultView
        self.view.RowFilter = "vis = '1'"
        self.e('CatGrid').ItemsSource = self.view
        disciplines = [u'<All Disciplines>'] + sorted(set(core.to_text(r['disc']) for r in self.rows))
        combo = self.e('DisciplineCombo')
        combo.ItemsSource = string_list(disciplines)
        combo.SelectedIndex = 0
        combo.SelectionChanged += self.on_filter
        self.fill_groups()
        self.e('GroupCombo').SelectionChanged += self.on_group
        self.e('SaveGroupBtn').Click += self.on_save_group
        self.e('DeleteGroupBtn').Click += self.on_delete_group
        self.e('TickAll').Click += self.on_tick_all
        self.e('HideUnchecked').Click += self.on_filter
        self.e('ShowSub').Click += self.on_filter
        self.timer = DispatcherTimer()
        self.timer.Interval = TimeSpan.FromMilliseconds(220)
        self.timer.Tick += self.on_search_tick
        self.e('SearchBox').TextChanged += self.on_search
        self.table.ColumnChanged += self.on_cell
        self.busy = False
        self.count()

    def fill_groups(self):
        names = [u'Choose Group'] + sorted(self.groups)
        combo = self.e('GroupCombo')
        combo.ItemsSource = string_list(names)
        combo.SelectedIndex = 0

    def count(self):
        total = len([r for r in self.rows if r['tick']])
        self.e('CountText').Text = u'Total number of selected categories {0}'.format(total)

    def on_cell(self, sender, args):
        if self.busy or args.Column.ColumnName != 'tick':
            return
        self.busy = True
        args.Row['mixed'] = False
        self.busy = False
        self.count()

    def on_search(self, sender, args):
        self.timer.Stop()
        self.timer.Start()

    def on_search_tick(self, sender, args):
        self.timer.Stop()
        self.refilter()

    def on_filter(self, sender, args):
        self.refilter()

    def refilter(self):
        search = self.e('SearchBox').Text
        discipline = core.to_text(self.e('DisciplineCombo').SelectedItem)
        hide = bool(self.e('HideUnchecked').IsChecked)
        subs = bool(self.e('ShowSub').IsChecked)
        self.busy = True
        for row in self.rows:
            show = core.words_match(search, [row['name']])
            if show and not discipline.startswith(u'<') and row['disc'] != discipline:
                show = False
            if show and hide and not (row['tick'] or row['mixed']):
                show = False
            if show and not subs and row['sub']:
                show = False
            flag = u'1' if show else u'0'
            if core.to_text(row['vis']) != flag:
                row['vis'] = flag
        self.busy = False

    def on_tick_all(self, sender, args):
        value = bool(self.e('TickAll').IsChecked)
        self.busy = True
        for row in self.rows:
            if core.to_text(row['vis']) == u'1':
                row['tick'] = value
                row['mixed'] = False
        self.busy = False
        self.count()

    def on_group(self, sender, args):
        combo = self.e('GroupCombo')
        chosen = combo.SelectedIndex > 0
        self.e('DeleteGroupBtn').IsEnabled = chosen
        if not chosen:
            return
        members = set(self.groups.get(core.to_text(combo.SelectedItem), []))
        self.busy = True
        for row in self.rows:
            row['tick'] = core.to_text(row['name']) in members
            row['mixed'] = False
        self.busy = False
        self.count()

    def on_save_group(self, sender, args):
        combo = self.e('GroupCombo')
        current = core.to_text(combo.SelectedItem) if combo.SelectedIndex > 0 else u''
        name = ask_text(self, u'Save Group', u'Name this group of categories', current)
        if not name:
            return
        self.groups[name] = [core.to_text(r['name']) for r in self.rows if r['tick']]
        core.save_category_groups(self.groups_file, self.groups)
        self.fill_groups()
        combo.SelectedItem = name

    def on_delete_group(self, sender, args):
        name = core.to_text(self.e('GroupCombo').SelectedItem)
        if ask(self, u'Delete Group', u'Delete the group "{0}"?'.format(name), u'Delete'):
            self.groups.pop(name, None)
            core.save_category_groups(self.groups_file, self.groups)
            self.fill_groups()

    def on_yes(self, sender, args):
        ticked = [core.to_text(r['name']) for r in self.rows if r['tick']]
        cleared = [core.to_text(r['name']) for r in self.rows
                   if not r['tick'] and not r['mixed']]
        self.result = (ticked, cleared)
        self.win.Close()


class GroupsWindow(Dialog):
    """Staged on the file in memory, like every other shared parameter edit."""

    def __init__(self, owner, sp):
        Dialog.__init__(self, 'Groups.xaml', u'Groups', owner)
        self.sp = sp
        self.e('AddBtn').Click += self.on_add
        self.e('RenameBtn').Click += self.on_rename
        self.e('DeleteBtn').Click += self.on_delete
        self.fill()

    def fill(self):
        self.e('GroupList').ItemsSource = string_list(sorted(g.name for g in self.sp.groups))

    def chosen(self):
        name = core.to_text(self.e('GroupList').SelectedItem)
        for group in self.sp.groups:
            if group.name == name:
                return group
        return None

    def clashes(self, name):
        return name.lower() in [g.name.lower() for g in self.sp.groups]

    def on_add(self, sender, args):
        name = ask_text(self, u'Add Group', u'New group name')
        if name and not self.clashes(name):
            self.sp.add_group(name)
            self.fill()

    def on_rename(self, sender, args):
        group = self.chosen()
        if group is None:
            return
        name = ask_text(self, u'Rename Group', u'New name for {0}'.format(group.name), group.name)
        if name and not self.clashes(name):
            group.name = name
            self.fill()

    def on_delete(self, sender, args):
        group = self.chosen()
        if group is None:
            return
        used = spfile.group_use(self.sp, group.gid)
        target = None
        if used:
            others = sorted(g.name for g in self.sp.groups if g is not group)
            if not others:
                tell(self, u'Delete Group', u'Add another group for its parameters to go to first.')
                return
            target = ask_choice(self, u'Delete Group',
                                u'{0} parameter(s) use this group. Move them to:'.format(used), others)
            if not target:
                return
        if target:
            gid = self.sp.group_id(target)
            for row in self.sp.live_rows():
                if row.group_id == group.gid:
                    row.group_id = gid
        self.sp.groups.remove(group)
        self.fill()

    def on_yes(self, sender, args):
        self.result = True
        self.win.Close()


class RenameWindow(Dialog):
    def __init__(self, owner, names):
        Dialog.__init__(self, 'Rename.xaml', u'Rename', owner)
        self.names = names
        for box in ('FindBox', 'ReplaceBox', 'PrefixBox', 'SuffixBox'):
            self.e(box).TextChanged += self.on_change
        self.on_change(None, None)

    def values(self):
        return (self.e('FindBox').Text, self.e('ReplaceBox').Text,
                self.e('PrefixBox').Text, self.e('SuffixBox').Text)

    def on_change(self, sender, args):
        find, replace, prefix, suffix = self.values()
        self.e('Preview').ItemsSource = string_list(
            [core.rename_preview(n, find, replace, prefix, suffix) for n in self.names])

    def on_yes(self, sender, args):
        self.result = self.values()
        self.win.Close()


class PickParamsWindow(Dialog):
    """Add existing definitions from a shared parameter file to the project."""

    def __init__(self, owner, path, taken_guids, taken_names):
        Dialog.__init__(self, 'PickParams.xaml', u'Add from Shared Parameter File', owner)
        self.taken_guids = taken_guids
        self.taken_names = taken_names
        self.rows = []
        self.sprows = {}
        self.table = make_table((('rid', Int32), ('tick', Boolean), ('name', String),
                                 ('ptype', String), ('grp', String), ('vis', String)))
        self.view = self.table.DefaultView
        self.view.RowFilter = "vis = '1'"
        self.e('PickGrid').ItemsSource = self.view
        self.e('BrowseBtn').Click += self.on_browse
        self.e('SearchBox').TextChanged += self.on_search
        self.path = u''
        if path and os.path.isfile(path):
            self.load(path)

    def load(self, path):
        with open(path, 'rb') as src:
            sp = spfile.parse_bytes(src.read())
        self.path = path
        self.e('PathBox').Text = path
        self.table.Rows.Clear()
        self.rows = []
        self.sprows = {}
        skipped = 0
        for index, row in enumerate(sp.rows):
            if row.guid.lower() in self.taken_guids or row.name.lower() in self.taken_names:
                skipped += 1
                continue
            item = self.table.NewRow()
            item['rid'] = index
            item['tick'] = False
            item['name'] = row.name
            item['ptype'] = spfile.type_label(row.dtype)
            item['grp'] = sp.group_name(row.group_id)
            item['vis'] = u'1'
            self.table.Rows.Add(item)
            self.rows.append(item)
            self.sprows[index] = row
        self.e('CountText').Text = u'{0} available, {1} already in the project'.format(
            len(self.rows), skipped)

    def on_browse(self, sender, args):
        dialog = OpenFileDialog()
        dialog.Filter = 'Shared parameter files (*.txt)|*.txt|All files (*.*)|*.*'
        if dialog.ShowDialog():
            self.load(dialog.FileName)

    def on_search(self, sender, args):
        search = self.e('SearchBox').Text
        for row in self.rows:
            flag = u'1' if core.words_match(search, [row['name'], row['ptype'], row['grp']]) else u'0'
            if core.to_text(row['vis']) != flag:
                row['vis'] = flag

    def on_yes(self, sender, args):
        self.result = (self.path, [(self.sprows[int(r['rid'])], core.to_text(r['grp']))
                                   for r in self.rows if r['tick']])
        self.win.Close()
