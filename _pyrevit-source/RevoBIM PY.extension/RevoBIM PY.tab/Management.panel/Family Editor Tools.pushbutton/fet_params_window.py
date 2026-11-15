# =========================================================================
# Family Editor Tools - the shared parameter chooser
#
# Opens a shared parameter file, lists everything in it, lets several be
# ticked at once, and stages them with a type/instance choice and a
# parameter group.  A ticked selection can be saved as a template.
# =========================================================================

import fet_clr  # noqa: F401  - assemblies first, always

import os

from System import TimeSpan
from System.Windows import GridLength, Thickness, Visibility
from System.Windows.Controls import (CheckBox, ColumnDefinition, ComboBox,
                                     ComboBoxItem, Grid, ListBoxItem,
                                     TextBlock)
from System.Windows.Threading import DispatcherTimer

import fet_core
import fet_model
import fet_ui

SEARCH_DEBOUNCE_MS = 220
ALL_GROUPS = u"All groups"


class SharedParamWindow(object):
    def __init__(self, palette_name, settings, owner=None):
        self.settings = settings
        self.palette_name = palette_name
        self.params = []
        self.rows = []
        self.ticked = set()
        self.problems = []
        self.path = u""
        self.staged = None

        self.window = fet_ui.load_window(u"FetSharedParams.xaml", palette_name)
        find = self.window.FindName
        self.window.Title = u"RevoBIM Shared Parameters"
        find(u"VersionText").Text = u"v" + fet_core.__version__

        self.path_box = find(u"PathBox")
        self.search_box = find(u"SearchBox")
        self.group_filter = find(u"GroupFilterCombo")
        self.param_list = find(u"ParamList")
        self.empty_text = find(u"EmptyText")
        self.status_text = find(u"StatusText")
        self.group_combo = find(u"GroupCombo")
        self.type_radio = find(u"TypeRadio")
        self.instance_radio = find(u"InstanceRadio")
        self.template_name = find(u"TemplateNameBox")

        self.chrome = fet_ui.Chrome(self.window, find(u"HeaderBar"),
                                    find(u"GripHost"), 720.0, 480.0)

        find(u"CloseButton").Click += self.on_close
        find(u"BrowseButton").Click += self.on_browse
        find(u"AllButton").Click += self.on_all
        find(u"NoneButton").Click += self.on_none
        find(u"SaveTemplateButton").Click += self.on_save_template
        find(u"StageButton").Click += self.on_stage
        self.search_box.TextChanged += self.on_search_typed
        self.group_filter.SelectionChanged += self.on_group_filter

        self.timer = DispatcherTimer()
        self.timer.Interval = TimeSpan.FromMilliseconds(SEARCH_DEBOUNCE_MS)
        self.timer.Tick += self.on_search_due

        self._fill_group_combo()
        binding = fet_core._as_text(settings.get(u"default_binding", u"type"))
        self.instance_radio.IsChecked = (binding == u"instance")
        self.type_radio.IsChecked = (binding != u"instance")

        if owner is not None:
            try:
                self.window.Owner = owner
            except Exception:
                pass

        last = fet_core._as_text(settings.get(u"last_spf", u""))
        if last and os.path.isfile(last):
            self.open_file(last)

    # ----- helpers ------------------------------------------------------
    def set_status(self, text, kind=u"muted"):
        try:
            self.status_text.Text = text
            key = {u"red": u"RedBrush", u"green": u"GreenBrush",
                   u"orange": u"OrangeBrush"}.get(kind, u"MutedBrush")
            self.status_text.SetResourceReference(TextBlock.ForegroundProperty, key)
        except Exception:
            pass

    def _fill_group_combo(self):
        self.group_combo.Items.Clear()
        wanted = fet_core._as_text(self.settings.get(u"default_group", u"Data"))
        chosen = 0
        for index, option in enumerate(fet_model.group_options()):
            item = ComboBoxItem()
            item.Content = option.label
            item.Tag = option.key
            self.group_combo.Items.Add(item)
            if option.key == wanted or option.label == wanted:
                chosen = index
        if self.group_combo.Items.Count:
            self.group_combo.SelectedIndex = chosen

    def chosen_group_key(self):
        item = self.group_combo.SelectedItem
        if item is None:
            return fet_core._as_text(self.settings.get(u"default_group", u"Data"))
        return fet_core._as_text(item.Tag)

    def is_instance(self):
        return bool(self.instance_radio.IsChecked)

    # ----- opening a file -----------------------------------------------
    @fet_ui.ui_safe
    def on_browse(self, sender, args):
        from Microsoft.Win32 import OpenFileDialog
        dialog = OpenFileDialog()
        dialog.Title = u"Choose a shared parameter file"
        dialog.Filter = u"Shared parameter files (*.txt)|*.txt|All files (*.*)|*.*"
        start = fet_core._as_text(self.settings.get(u"last_spf", u""))
        if start and os.path.isfile(start):
            try:
                dialog.InitialDirectory = os.path.dirname(start)
                dialog.FileName = os.path.basename(start)
            except Exception:
                pass
        if dialog.ShowDialog() != True:
            return
        self.open_file(dialog.FileName)

    def open_file(self, path):
        try:
            params, groups, problems = fet_core.read_shared_parameter_file(path)
        except Exception:
            self.set_status(u"That file would not read", u"red")
            return
        self.path = path
        self.params = params
        self.problems = problems
        self.ticked = set()
        self.path_box.Text = path
        self.settings[u"last_spf"] = path
        fet_core.save_settings(self.settings)
        self._fill_group_filter()
        self.rebuild()
        message = u"{0} parameters in {1} groups".format(
            len(params), len(set([p.group for p in params])))
        if problems:
            message += u" - {0} lines would not read".format(len(problems))
            self.set_status(message, u"orange")
        else:
            self.set_status(message)

    def _fill_group_filter(self):
        self.group_filter.Items.Clear()
        item = ComboBoxItem()
        item.Content = ALL_GROUPS
        item.Tag = u""
        self.group_filter.Items.Add(item)
        for name in sorted(set([p.group for p in self.params]),
                           key=fet_core.natural_key):
            entry = ComboBoxItem()
            entry.Content = name
            entry.Tag = name
            self.group_filter.Items.Add(entry)
        self.group_filter.SelectedIndex = 0

    # ----- the list -----------------------------------------------------
    def rebuild(self):
        needle = self.search_box.Text
        group = u""
        item = self.group_filter.SelectedItem
        if item is not None:
            group = fet_core._as_text(item.Tag)
        shown = fet_core.filter_params(self.params, needle, group or None)

        self.param_list.Items.Clear()
        self.rows = []
        last_group = None
        for param in shown:
            if group == u"" and param.group != last_group:
                last_group = param.group
                self.param_list.Items.Add(self._heading_row(param.group))
            self.param_list.Items.Add(self._param_row(param))

        self.empty_text.Visibility = (Visibility.Visible if not shown
                                      else Visibility.Collapsed)
        if not self.params:
            self.empty_text.Text = u"Choose a shared parameter file to see what is in it."
        else:
            self.empty_text.Text = u"Nothing in this file matches that search."
        self._update_count()

    def _heading_row(self, text):
        item = ListBoxItem()
        item.IsHitTestVisible = False
        block = TextBlock()
        block.Text = text
        block.Margin = Thickness(2, 7, 0, 2)
        block.FontWeight = _bold()
        block.SetResourceReference(TextBlock.ForegroundProperty, u"OrangeBrush")
        item.Content = block
        return item

    def _param_row(self, param):
        grid = Grid()
        for width in (u"*", u"120", u"90"):
            column = ColumnDefinition()
            if width == u"*":
                column.Width = GridLength(1, _star())
            else:
                column.Width = GridLength(float(width))
            grid.ColumnDefinitions.Add(column)

        check = CheckBox()
        check.Content = param.name
        check.IsChecked = param.guid in self.ticked
        check.Tag = param.guid
        check.Checked += self.on_tick
        check.Unchecked += self.on_tick
        check.VerticalAlignment = _centre()
        Grid.SetColumn(check, 0)
        grid.Children.Add(check)

        type_block = TextBlock()
        type_block.Text = param.data_type
        type_block.SetResourceReference(TextBlock.ForegroundProperty, u"MutedBrush")
        type_block.VerticalAlignment = _centre()
        Grid.SetColumn(type_block, 1)
        grid.Children.Add(type_block)

        flag = TextBlock()
        flag.Text = u"" if param.visible else u"hidden"
        flag.SetResourceReference(TextBlock.ForegroundProperty, u"MutedBrush")
        flag.VerticalAlignment = _centre()
        Grid.SetColumn(flag, 2)
        grid.Children.Add(flag)

        item = ListBoxItem()
        item.Content = grid
        if param.description:
            item.ToolTip = u"{0}\n{1}".format(param.description, param.guid)
        else:
            item.ToolTip = param.guid
        self.rows.append((param, check))
        return item

    def _update_count(self):
        self.set_status(u"{0} ticked of {1} in the file".format(
            len(self.ticked), len(self.params)))

    @fet_ui.ui_safe
    def on_tick(self, sender, args):
        guid = fet_core._as_text(sender.Tag)
        if sender.IsChecked:
            self.ticked.add(guid)
        else:
            self.ticked.discard(guid)
        self._update_count()

    @fet_ui.ui_safe
    def on_all(self, sender, args):
        for param, check in self.rows:
            check.IsChecked = True
        self._update_count()

    @fet_ui.ui_safe
    def on_none(self, sender, args):
        for param, check in self.rows:
            check.IsChecked = False
        self._update_count()

    @fet_ui.ui_safe
    def on_search_typed(self, sender, args):
        self.timer.Stop()
        self.timer.Start()

    @fet_ui.ui_safe
    def on_search_due(self, sender, args):
        self.timer.Stop()
        self.rebuild()

    @fet_ui.ui_safe
    def on_group_filter(self, sender, args):
        self.rebuild()

    # ----- staging and templates ---------------------------------------
    def selected_rows(self):
        group = self.chosen_group_key()
        binding = u"instance" if self.is_instance() else u"type"
        out = []
        for param in self.params:
            if param.guid in self.ticked:
                out.append(fet_core.TemplateRow(param.guid, param.name,
                                                binding, group, param.data_type))
        return out

    @fet_ui.ui_safe
    def on_save_template(self, sender, args):
        rows = self.selected_rows()
        if not rows:
            self.set_status(u"Tick some parameters first", u"orange")
            return
        name = fet_core._as_text(self.template_name.Text).strip()
        if not name:
            self.set_status(u"Give the template a name first", u"orange")
            return
        path = fet_core.save_template(name, self.path, rows)
        self.set_status(u"Saved {0} parameters to {1}".format(
            len(rows), os.path.basename(path)), u"green")

    @fet_ui.ui_safe
    def on_stage(self, sender, args):
        rows = self.selected_rows()
        if not rows:
            self.set_status(u"Nothing is ticked", u"orange")
            return
        self.staged = rows
        self.settings[u"default_binding"] = (u"instance" if self.is_instance()
                                             else u"type")
        self.settings[u"default_group"] = self.chosen_group_key()
        fet_core.save_settings(self.settings)
        try:
            self.window.DialogResult = True
        except Exception:
            pass
        self.window.Close()

    @fet_ui.ui_safe
    def on_close(self, sender, args):
        self.staged = None
        try:
            self.window.DialogResult = False
        except Exception:
            pass
        self.window.Close()

    def show(self):
        try:
            self.window.ShowDialog()
        except Exception:
            fet_core.log(u"the shared parameter window would not open")
        return self.staged, self.path


def _bold():
    from System.Windows import FontWeights
    return FontWeights.Bold


def _star():
    from System.Windows import GridUnitType
    return GridUnitType.Star


def _centre():
    from System.Windows import VerticalAlignment
    return VerticalAlignment.Center
