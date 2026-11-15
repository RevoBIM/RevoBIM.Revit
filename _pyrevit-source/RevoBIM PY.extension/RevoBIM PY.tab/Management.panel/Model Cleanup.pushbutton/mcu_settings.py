# -*- coding: utf-8 -*-
"""Export Settings - edits one settings template.

The purge list is read from the live model with Revit's own purge query, so
only categories that exist are offered. Ticks are stored as an exclusion
list, so a category that turns up in a later model is purged by default.
"""
import os

import mcu_clr  # noqa: F401 - must come before any System.* import
import mcu_core as core
import mcu_aps as aps
import mcu_model as model
import mcu_nwc as nwc
import mcu_ui as ui

from System.Data import DataTable
from System.Windows import (Thickness, Visibility, GridLength, TextAlignment,
                            VerticalAlignment, FrameworkElement, FontWeights)
from System.Windows.Controls import (CheckBox, Grid, ColumnDefinition,
                                     TextBlock, ListBoxItem, Button, Border,
                                     StackPanel, Orientation, RadioButton)
from System.Windows.Shapes import Path as ShapePath, Shape
from System.Windows.Media import Geometry
from System.Windows.Input import Key
from Microsoft.Win32 import SaveFileDialog, OpenFileDialog
from System.Windows.Threading import DispatcherTimer
from System import TimeSpan

CHECKS = [
    (u"AuditCheck", u"audit", False),
    (u"CompactCheck", u"compact", True),
    (u"RelinquishDefaultCheck", u"relinquish", True),
    (u"OpenWhenDoneCheck", u"open_when_done", True),
    (u"AddDateCheck", u"add_date", True),
    (u"AddSuffixCheck", u"add_suffix", True),
    (u"RemoveLinksCheck", u"remove_revit_links", True),
    (u"RemoveCadCheck", u"remove_cad", True),
    (u"RemovePointCloudsCheck", u"remove_point_clouds", True),
    (u"DeleteUnplacedImagesCheck", u"delete_unplaced_images", True),
    (u"DeleteSheetsCheck", u"delete_sheets_not_retained", False),
    (u"DeleteViewsCheck", u"delete_views_off_sheet", True),
    (u"DeleteSchedulesCheck", u"delete_schedules_off_sheet", True),
    (u"DeleteLegendsCheck", u"delete_legends_off_sheet", False),
    (u"DeleteTemplatesCheck", u"delete_unused_templates", True),
    (u"DeleteFiltersCheck", u"delete_unused_filters", True),
    (u"PurgeCheck", u"purge", True),
    (u"OfferPublishCheck", u"offer_publish", True),
    (u"ShowUsedCheck", u"show_used", False),
]

TEXTS = [
    (u"FileSuffixBox", u"file_suffix"),
    (u"SyncCommentDefaultBox", u"sync_comment"),
    (u"KeepWordsBox", u"keep_view_words"),
    (u"PurgePassesBox", u"purge_passes"),
]

ROW_LIMIT = 20000

LINK_LABELS = [
    (aps.LINKS_ASK, u"Ask each time"),
    (aps.LINKS_WITH, u"Always with links"),
    (aps.LINKS_WITHOUT, u"Always without links"),
]


class RetainList(object):
    """One 'to retain' list: rows grouped as the project browser shows them,
    a search box, a tick per item and a part-tickable tick per folder."""

    INDENT = 18

    def __init__(self, owner, prefix, noun):
        self.owner = owner
        self.find = owner.find
        self.prefix = prefix
        self.noun = noun
        self.items = []
        self.retained = set()
        self.collapsed = set()
        self.only_retained = False
        self.item_checks = {}
        self.header_checks = {}
        self.organisation = u""
        window = owner.window
        safe = ui.safe_handler
        self.find(prefix + u"AllButton").Click += safe(window, self.on_all, owner.theme)
        self.find(prefix + u"NoneButton").Click += safe(window, self.on_none, owner.theme)
        self.find(prefix + u"CollapseButton").Click += safe(window, self.on_collapse, owner.theme)
        self.find(prefix + u"IsolateButton").Click += safe(window, self.on_isolate, owner.theme)
        self.find(prefix + u"SearchBox").TextChanged += self.on_typed
        self.timer = DispatcherTimer()
        self.timer.Interval = TimeSpan.FromMilliseconds(220)
        self.timer.Tick += safe(window, self.on_tick, owner.theme)

    def load(self, items, organisation, retained):
        self.items = items
        self.organisation = organisation
        self.retained = set(retained)
        self.render()

    def keys(self):
        return sorted(self.retained, key=core.natural_key)

    def search(self):
        return core.to_text(self.find(self.prefix + u"SearchBox").Text)

    def render(self):
        listbox = self.find(self.prefix + u"List")
        listbox.Items.Clear()
        self.item_checks = {}
        self.header_checks = {}
        rows = core.retain_rows(self.items, self.search(), self.retained, self.collapsed,
                                self.only_retained)
        for row in rows:
            listbox.Items.Add(self._header(row) if row[u"kind"] == u"header" else self._item(row))
        self.update_summary()

    def _header(self, row):
        item = ListBoxItem()
        panel = StackPanel()
        panel.Orientation = Orientation.Horizontal
        panel.Margin = Thickness(self.INDENT * row[u"level"], 4 if row[u"level"] == 0 else 1, 0, 1)
        arrow = Button()
        arrow.Width = 18
        arrow.Height = 18
        arrow.Padding = Thickness(0)
        arrow.MinHeight = 0
        arrow.Margin = Thickness(0, 0, 4, 0)
        arrow.SetResourceReference(FrameworkElement.StyleProperty, u"WindowButton")
        glyph = ShapePath()
        glyph.Data = Geometry.Parse(u"M 0,0 L 4,4 L 0,8" if row[u"collapsed"] else u"M 0,0 L 4,4 L 8,0")
        glyph.StrokeThickness = 1.6
        glyph.SetResourceReference(Shape.StrokeProperty, u"MutedBrush")
        arrow.Content = glyph
        arrow.Click += ui.safe_handler(self.owner.window, self._toggle_handler(row[u"path"]),
                                       self.owner.theme)
        check = CheckBox()
        check.IsChecked = {u"all": True, u"none": False}.get(row[u"state"], None)
        check.Margin = Thickness(0)
        label = TextBlock()
        label.Text = u"{0}  ({1})".format(row[u"label"], row[u"count"])
        label.FontWeight = FontWeights.SemiBold
        label.SetResourceReference(TextBlock.ForegroundProperty,
                                   u"BlueBrush" if row[u"level"] == 0 else u"OrangeBrush")
        check.Content = label
        check.Click += ui.safe_handler(self.owner.window, self._group_handler(row),
                                       self.owner.theme)
        panel.Children.Add(arrow)
        panel.Children.Add(check)
        item.Content = panel
        item.Tag = u"header"
        self.header_checks[row[u"path"]] = (check, row[u"children"])
        return item

    def _item(self, row):
        item = ListBoxItem()
        check = CheckBox()
        check.Content = row[u"label"]
        check.IsChecked = row[u"checked"]
        check.Margin = Thickness(self.INDENT * row[u"level"] + 22, 0, 0, 0)
        check.Click += ui.safe_handler(self.owner.window, self._item_handler(row[u"key"]),
                                       self.owner.theme)
        item.Content = check
        item.Tag = row[u"key"]
        self.item_checks[row[u"key"]] = check
        return item

    def _item_handler(self, key):
        def handler(sender, args):
            if sender.IsChecked:
                self.retained.add(key)
            else:
                self.retained.discard(key)
            self.refresh_headers()
        return handler

    def _group_handler(self, row):
        def handler(sender, args):
            self.set_keys(row[u"children"], bool(sender.IsChecked))
        return handler

    def _toggle_handler(self, path):
        def handler(sender, args):
            if path in self.collapsed:
                self.collapsed.discard(path)
            else:
                self.collapsed.add(path)
            self.render()
        return handler

    def set_keys(self, keys, on):
        for key in keys:
            if on:
                self.retained.add(key)
            else:
                self.retained.discard(key)
            check = self.item_checks.get(key)
            if check is not None:
                check.IsChecked = on
        self.refresh_headers()

    def refresh_headers(self):
        for check, children in self.header_checks.values():
            state = core.group_state(children, self.retained)
            check.IsChecked = {u"all": True, u"none": False}.get(state, None)
        self.update_summary()

    def update_summary(self):
        text = core.retain_summary(self.items, self.retained, self.noun)
        text += u". Browser organisation: {0}.".format(self.organisation or u"type only")
        if self.only_retained:
            text += u" Showing retained only - anything you untick stays listed until you show all."
        self.find(self.prefix + u"SummaryText").Text = text

    def shown_keys(self):
        rows = core.retain_rows(self.items, self.search(), self.retained,
                                only_retained=self.only_retained)
        return [row[u"key"] for row in rows if row[u"kind"] == u"item"]

    def on_all(self, sender, args):
        self.set_keys(self.shown_keys(), True)

    def on_none(self, sender, args):
        self.set_keys(self.shown_keys(), False)

    def on_isolate(self, sender, args):
        """Show only what is ticked. The list is taken once, so unticking
        something here leaves it in place rather than pulling the row out
        from under the pointer; Show all (or a search) retakes it."""
        self.only_retained = not self.only_retained
        button = self.find(self.prefix + u"IsolateButton")
        if self.only_retained:
            button.Content = u"Show all"
            button.SetResourceReference(FrameworkElement.StyleProperty, u"OrangeButton")
        else:
            button.Content = u"Retained only"
            button.SetResourceReference(FrameworkElement.StyleProperty, u"BaseButton")
        self.render()

    def on_collapse(self, sender, args):
        button = self.find(self.prefix + u"CollapseButton")
        if self.collapsed:
            self.collapsed = set()
            button.Content = u"Collapse all"
        else:
            self.collapsed = set(p for p in core.all_folder_paths(self.items)
                                 if u"\x1f" not in p)
            button.Content = u"Expand all"
        self.render()

    def on_typed(self, sender, args):
        self.timer.Stop()
        self.timer.Start()

    def on_tick(self, sender, args):
        self.timer.Stop()
        self.render()


class NwcPanel(object):
    """The NWC tab: export settings, and the 3D views with one primary."""

    def __init__(self, owner):
        self.owner = owner
        self.find = owner.find
        self.names = []
        self.views = []
        self.primary = u""
        self.only_selected = False
        self.read = False
        self.rows = {}
        self.stem = u"Model"
        window, theme, safe = owner.window, owner.theme, ui.safe_handler
        for combo, options in ((u"NwcCoordinatesCombo", nwc.COORDINATES),
                               (u"NwcParametersCombo", nwc.PARAMETERS)):
            for _, label in options:
                self.find(combo).Items.Add(label)
        self.find(u"NwcAllButton").Click += safe(window, self.on_all, theme)
        self.find(u"NwcNoneButton").Click += safe(window, self.on_none, theme)
        self.find(u"NwcIsolateButton").Click += safe(window, self.on_isolate, theme)
        for name in (u"ExportNwcCheck", u"NwcDefaultsRadio", u"NwcCustomRadio"):
            self.find(name).Click += safe(window, self.on_enable_changed, theme)
        self.find(u"NwcSearchBox").TextChanged += self.on_typed
        self.timer = DispatcherTimer()
        self.timer.Interval = TimeSpan.FromMilliseconds(220)
        self.timer.Tick += safe(window, self.on_tick, theme)

    # ---------------------------------------------------------- values
    def push(self, values):
        find = self.find
        find(u"ExportNwcCheck").IsChecked = core.as_bool(values.get(u"export_nwc"))
        custom = values.get(u"nwc_source") != nwc.SOURCE_DEFAULTS
        find(u"NwcCustomRadio").IsChecked = custom
        find(u"NwcDefaultsRadio").IsChecked = not custom
        find(u"NwcCoordinatesCombo").SelectedIndex = [k for k, _ in nwc.COORDINATES].index(
            nwc.choice(values.get(u"nwc_coordinates"), nwc.COORDINATES, u"shared"))
        find(u"NwcParametersCombo").SelectedIndex = [k for k, _ in nwc.PARAMETERS].index(
            nwc.choice(values.get(u"nwc_parameters"), nwc.PARAMETERS, u"all"))
        for key, _, _, default in nwc.BOOL_OPTIONS:
            find(u"NwcOpt_" + key).IsChecked = core.as_bool(values.get(key, default), default == u"1")
        find(u"NwcFacetingBox").Text = core.to_text(values.get(u"nwc_faceting"))
        self.views, self.primary = nwc.selection(values)
        self.update_enabled()
        if self.read:
            self.render()

    def pull(self, values):
        find = self.find
        values[u"export_nwc"] = core.bool_text(bool(find(u"ExportNwcCheck").IsChecked))
        values[u"nwc_source"] = (nwc.SOURCE_DEFAULTS if find(u"NwcDefaultsRadio").IsChecked
                                 else nwc.SOURCE_CUSTOM)
        coords = find(u"NwcCoordinatesCombo").SelectedIndex
        params = find(u"NwcParametersCombo").SelectedIndex
        values[u"nwc_coordinates"] = nwc.COORDINATES[coords][0] if coords >= 0 else u"shared"
        values[u"nwc_parameters"] = nwc.PARAMETERS[params][0] if params >= 0 else u"all"
        for key, _, _, _ in nwc.BOOL_OPTIONS:
            values[key] = core.bool_text(bool(find(u"NwcOpt_" + key).IsChecked))
        values[u"nwc_faceting"] = u"{0:g}".format(nwc.faceting(find(u"NwcFacetingBox").Text))
        values[u"nwc_views"] = core.join_retain(self.views)
        values[u"nwc_primary"] = self.primary
        return values

    def update_enabled(self):
        on = bool(self.find(u"ExportNwcCheck").IsChecked)
        self.find(u"NwcSettingsPanel").IsEnabled = on
        self.find(u"NwcCustomPanel").IsEnabled = on and bool(self.find(u"NwcCustomRadio").IsChecked)
        # the views stay pickable while export is off, so they can be set up first
        self.find(u"NwcViewList").IsEnabled = True

    # ---------------------------------------------------------- views
    def load(self, doc):
        self.names = sorted(model.three_d_views(doc), key=core.natural_key)
        self.stem = core.model_stem(model.model_title(doc)) or u"Model"
        available = model.nwc_available()
        text = self.find(u"NwcAvailableText")
        text.Text = (u"Navisworks exporter found" if available
                     else u"Navisworks exporter not installed")
        text.SetResourceReference(TextBlock.ForegroundProperty,
                                  u"GreenBrush" if available else u"RedBrush")
        self.read = True
        self.render()

    def search(self):
        return core.to_text(self.find(u"NwcSearchBox").Text)

    def render(self):
        listbox = self.find(u"NwcViewList")
        listbox.Items.Clear()
        self.rows = {}
        for name in nwc.rows(self.names, self.search(), self.views, self.only_selected):
            item = ListBoxItem()
            grid = Grid()
            first = ColumnDefinition()
            second = ColumnDefinition()
            second.Width = GridLength.Auto
            grid.ColumnDefinitions.Add(first)
            grid.ColumnDefinitions.Add(second)
            check = CheckBox()
            check.Content = name
            check.IsChecked = name in self.views
            check.Click += ui.safe_handler(self.owner.window, self._tick(name), self.owner.theme)
            radio = RadioButton()
            radio.GroupName = u"NwcPrimary"
            radio.Content = u"Primary"
            radio.IsChecked = name == self.primary
            radio.Margin = Thickness(12, 0, 4, 0)
            radio.Checked += self._primary(name)
            Grid.SetColumn(radio, 1)
            grid.Children.Add(check)
            grid.Children.Add(radio)
            item.Content = grid
            listbox.Items.Add(item)
            self.rows[name] = (check, radio)
        self.update_summary()

    def sync_rows(self):
        for name, (check, radio) in self.rows.items():
            check.IsChecked = name in self.views
            if name == self.primary and not radio.IsChecked:
                radio.IsChecked = True
            elif name != self.primary and radio.IsChecked:
                radio.IsChecked = False
        self.update_summary()

    def _tick(self, name):
        def handler(sender, args):
            if sender.IsChecked:
                self.views, self.primary = nwc.normalise(self.views + [name], self.primary)
            else:
                self.views, self.primary = nwc.untick(self.views, self.primary, name)
            self.sync_rows()
        return handler

    def _primary(self, name):
        def handler(sender, args):
            try:
                if name == self.primary:
                    return
                self.views, self.primary = nwc.normalise(self.views, name)
                self.sync_rows()
            except Exception:
                core.log(u"nwc primary: " + core.format_exception())
        return handler

    def update_summary(self):
        missing = [v for v in self.views if self.read and v not in self.names]
        text = nwc.summary(self.views, self.primary, self.stem)
        if missing:
            text += u". Not in this model: " + u", ".join(missing)
        self.find(u"NwcSummaryText").Text = text

    def shown(self):
        return nwc.rows(self.names, self.search(), self.views, self.only_selected)

    def on_all(self, sender, args):
        self.views, self.primary = nwc.normalise(self.views + self.shown(), self.primary)
        self.sync_rows()

    def on_none(self, sender, args):
        for name in self.shown():
            self.views, self.primary = nwc.untick(self.views, self.primary, name)
        self.sync_rows()

    def on_isolate(self, sender, args):
        self.only_selected = not self.only_selected
        button = self.find(u"NwcIsolateButton")
        button.Content = u"Show all" if self.only_selected else u"Ticked only"
        button.SetResourceReference(FrameworkElement.StyleProperty,
                                    u"OrangeButton" if self.only_selected else u"BaseButton")
        self.render()

    def on_enable_changed(self, sender, args):
        self.update_enabled()

    def on_typed(self, sender, args):
        self.timer.Stop()
        self.timer.Start()

    def on_tick(self, sender, args):
        self.timer.Stop()
        self.render()


class SettingsWindow(object):

    def __init__(self, owner, template_name):
        self.owner = owner
        self.doc = owner.doc
        self.theme = owner.theme
        self.purge_cache = owner.purge_cache
        self.name = template_name
        self.values = core.load_template(template_name)
        self.excluded = set(core.split_list(self.values.get(u"purge_exclude")))
        self.rows = []
        self.checks = {}
        self.items = {}
        self.selected_group = None
        self.saved_name = u""
        self.loading = False
        self.busy = False

        self.window, self.find, self.chrome, self.drawer = ui.standard_window(
            u"McuSettings.xaml", self.theme, lambda: self.busy)
        ui.set_owner(self.window, owner.window)
        self.progress = ui.ProgressBar(self.window, self.find)
        self.view_list = RetainList(self, u"View", u"views")
        self.nwc_panel = NwcPanel(self)
        self.sheet_list = RetainList(self, u"Sheet", u"sheets")
        self.browser_read = False
        self.table = self.make_table()
        self.find(u"ElementGrid").ItemsSource = self.table.DefaultView

        self.wire(u"SaveButton", self.on_save)
        self.wire(u"CancelButton", self.on_cancel)
        self.wire(u"SaveAsNewButton", self.on_save_as_new)
        self.wire(u"DeleteTemplateButton", self.on_delete)
        self.wire(u"ExportTemplateButton", self.on_export_file)
        self.wire(u"ImportTemplateButton", self.on_import_file)
        self.wire(u"SelectAllButton", self.on_all)
        self.wire(u"SelectNoneButton", self.on_none)
        self.wire(u"RescanButton", self.on_rescan)
        self.wire(u"ApsHelpButton", self.on_aps_help)
        self.wire(u"SignOutButton", self.on_sign_out)
        self.find(u"ApsPortBox").TextChanged += self.on_port_typed
        self.find(u"ApsClientIdBox").TextChanged += self.on_port_typed
        safe = ui.safe_handler
        self.find(u"ShowUsedCheck").Click += safe(self.window, self.on_show_used, self.theme)
        self.find(u"CategoryList").SelectionChanged += safe(
            self.window, self.on_category_picked, self.theme)
        self.find(u"SettingsTemplateCombo").SelectionChanged += safe(
            self.window, self.on_template_changed, self.theme)
        self.find(u"PurgeCheck").Click += safe(self.window, self.on_purge_toggled, self.theme)
        self.find(u"AddSuffixCheck").Click += safe(self.window, self.on_suffix_toggled, self.theme)
        self.window.PreviewKeyDown += self.on_key

        self.search_timer = DispatcherTimer()
        self.search_timer.Interval = TimeSpan.FromMilliseconds(220)
        self.search_timer.Tick += safe(self.window, self.on_search_tick, self.theme)
        self.find(u"CategorySearchBox").TextChanged += self.on_search_typed
        self.find(u"ElementSearchBox").TextChanged += self.on_search_typed
        self.window.ContentRendered += safe(self.window, self.on_first_render, self.theme)

        combo = self.find(u"PublishLinksCombo")
        for _, label in LINK_LABELS:
            combo.Items.Add(label)
        self.find(u"ApsClientIdBox").Text = core.to_text(owner.settings.get(u"aps_client_id"))
        self.find(u"ApsPortBox").Text = core.to_text(owner.settings.get(u"aps_port"))
        self.update_aps_text()

        self.fill_templates()
        self.push_values()

    def wire(self, name, handler):
        self.find(name).Click += ui.safe_handler(self.window, handler, self.theme)

    def show(self):
        self.window.ShowDialog()
        return self.saved_name

    def set_status(self, text):
        self.find(u"StatusText").Text = core.to_text(text)

    # ------------------------------------------------------------
    def make_table(self):
        table = DataTable(u"elements")
        for column in (u"eid", u"name", u"grp", u"status"):
            table.Columns.Add(column)
        return table

    def fill_templates(self):
        self.loading = True
        try:
            combo = self.find(u"SettingsTemplateCombo")
            combo.Items.Clear()
            names = core.list_templates()
            for name in names:
                combo.Items.Add(name)
            self.name = core.pick_template(names, self.name)
            combo.SelectedItem = self.name
        finally:
            self.loading = False

    def push_values(self):
        find = self.find
        values = self.values
        preserve = values.get(u"detach_mode") != core.DETACH_DISCARD
        find(u"PreserveRadio").IsChecked = preserve
        find(u"DiscardRadio").IsChecked = not preserve
        for control, key, default in CHECKS:
            find(control).IsChecked = core.as_bool(values.get(key), default)
        for control, key in TEXTS:
            find(control).Text = core.to_text(values.get(key))
        links = aps.normalise_links(values.get(u"publish_links"))
        keys = [key for key, _ in LINK_LABELS]
        find(u"PublishLinksCombo").SelectedIndex = keys.index(links)
        self.excluded = set(core.split_list(values.get(u"purge_exclude")))
        self.update_purge_enabled()
        self.update_suffix_enabled()
        self.nwc_panel.push(values)
        self.fill_categories()
        if self.browser_read:
            self.view_list.retained = set(core.split_retain(values.get(u"retain_views")))
            self.sheet_list.retained = set(core.split_retain(values.get(u"retain_sheets")))
            self.view_list.render()
            self.sheet_list.render()

    def pull_values(self):
        find = self.find
        values = dict(self.values)
        values[u"detach_mode"] = (core.DETACH_DISCARD if find(u"DiscardRadio").IsChecked
                                  else core.DETACH_PRESERVE)
        for control, key, _ in CHECKS:
            values[key] = core.bool_text(bool(find(control).IsChecked))
        for control, key in TEXTS:
            values[key] = core.to_text(find(control).Text).strip()
        values[u"purge_passes"] = u"{0}".format(
            core.as_int(values[u"purge_passes"], 4, 1, 10))
        self.nwc_panel.pull(values)
        if self.browser_read:
            values[u"retain_views"] = core.join_retain(self.view_list.keys())
            values[u"retain_sheets"] = core.join_retain(self.sheet_list.keys())
        index = find(u"PublishLinksCombo").SelectedIndex
        keys = [key for key, _ in LINK_LABELS]
        values[u"publish_links"] = keys[index] if 0 <= index < len(keys) else aps.LINKS_ASK
        values[u"purge_exclude"] = core.join_list(sorted(self.excluded, key=lambda n: n.lower()))
        return values

    def on_suffix_toggled(self, sender, args):
        self.update_suffix_enabled()

    def update_suffix_enabled(self):
        self.find(u"FileSuffixBox").IsEnabled = bool(self.find(u"AddSuffixCheck").IsChecked)

    def update_purge_enabled(self):
        on = bool(self.find(u"PurgeCheck").IsChecked)
        self.find(u"PurgePassesBox").IsEnabled = on
        self.find(u"CategoryList").IsEnabled = on
        self.find(u"SelectAllButton").IsEnabled = on
        self.find(u"SelectNoneButton").IsEnabled = on

    # ------------------------------------------------------------
    def on_first_render(self, sender, args):
        self.read_browser()
        if self.purge_cache is None:
            self.scan()
        else:
            self.fill_categories()

    def read_browser(self):
        """Views and sheets, grouped as the project browser shows them now."""
        self.busy = True
        self.set_deaf(True)
        self.progress.begin(u"Reading the project browser")
        self.progress.update(0.2, u"Reading views and their browser folders")
        state = u"fail"
        try:
            views, view_org = model.view_retain_items(self.doc)
            self.progress.update(0.6, u"Reading sheets and their browser folders")
            sheets, sheet_org = model.sheet_retain_items(self.doc)
            self.progress.update(0.85, u"Reading 3D views for the NWC export")
            self.nwc_panel.load(self.doc)
            self.browser_read = True
            self.view_list.load(views, view_org,
                                core.split_retain(self.values.get(u"retain_views")))
            self.sheet_list.load(sheets, sheet_org,
                                 core.split_retain(self.values.get(u"retain_sheets")))
            state = u"ok"
        finally:
            self.busy = False
            self.set_deaf(False)
            self.progress.finish(u"Project browser read" if state == u"ok"
                                 else u"Reading the project browser failed", state)

    def set_deaf(self, deaf):
        """Mouse off the body for a read - all but the shrink button."""
        for name in (u"BodyGrid", u"FooterBar", u"ThemeChip", u"FullScreenButton",
                     u"CloseButton"):
            try:
                self.find(name).IsHitTestVisible = not deaf
            except Exception:
                pass

    def scan(self):
        self.busy = True
        self.set_deaf(True)
        self.set_status(u"Reading what can be purged from the live model...")
        self.progress.begin(u"Reading the live model")
        self.progress.update(0.1, u"Asking Revit what is unused (Revit is busy)")
        state = u"fail"
        try:
            self.purge_cache = model.scan_purge(self.doc, True)
            state = u"ok" if self.purge_cache.get(u"ok") else u"warn"
            self.progress.update(0.8, u"Listing categories")
            self.fill_categories()
        finally:
            self.busy = False
            self.set_deaf(False)
            done = {u"ok": u"Model read", u"warn": u"Purge is not available here",
                    u"fail": u"Reading the model failed"}[state]
            self.progress.finish(done, state)
        if not self.purge_cache.get(u"ok"):
            self.set_status(self.purge_cache.get(u"reason"))

    def on_rescan(self, sender, args):
        """Re-read the browser and the purge list, keeping the ticks made so far."""
        if self.browser_read:
            self.values[u"retain_views"] = core.join_retain(self.view_list.keys())
            self.values[u"retain_sheets"] = core.join_retain(self.sheet_list.keys())
        self.nwc_panel.pull(self.values)
        self.read_browser()
        self.purge_cache = None
        self.scan()

    def show_used(self):
        return bool(self.find(u"ShowUsedCheck").IsChecked)

    def fill_categories(self):
        listbox = self.find(u"CategoryList")
        listbox.Items.Clear()
        self.checks = {}
        self.items = {}
        cache = self.purge_cache
        show_used = self.show_used()
        used_visibility = Visibility.Visible if show_used else Visibility.Collapsed
        self.find(u"UsedHeaderText").Visibility = used_visibility
        if cache is None:
            self.find(u"CategorySummaryText").Text = u"Reading the model..."
            return
        rows = core.group_counts(cache.get(u"unused", []), cache.get(u"used", []))
        search = core.to_text(self.find(u"CategorySearchBox").Text)
        shown = core.visible_groups(rows, show_used, search)
        for group, unused, used in shown:
            item = ListBoxItem()
            grid = Grid()
            for width in (None, 56, 56):
                column = ColumnDefinition()
                if width is not None:
                    column.Width = GridLength(width)
                grid.ColumnDefinitions.Add(column)
            check = CheckBox()
            check.Content = group
            check.IsChecked = group not in self.excluded
            check.Margin = Thickness(0, 2, 0, 2)
            check.Click += ui.safe_handler(self.window, self._tick_handler(group), self.theme)
            unused_text = TextBlock()
            unused_text.Text = u"{0}".format(unused)
            unused_text.TextAlignment = TextAlignment.Right
            unused_text.SetResourceReference(TextBlock.ForegroundProperty,
                                             u"OrangeBrush" if unused else u"MutedBrush")
            used_text = TextBlock()
            used_text.Text = u"{0}".format(used)
            used_text.TextAlignment = TextAlignment.Right
            used_text.Visibility = used_visibility
            used_text.SetResourceReference(TextBlock.ForegroundProperty, u"GreenBrush")
            for block in (unused_text, used_text):
                block.VerticalAlignment = VerticalAlignment.Center
            Grid.SetColumn(unused_text, 1)
            Grid.SetColumn(used_text, 2)
            grid.Children.Add(check)
            grid.Children.Add(unused_text)
            grid.Children.Add(used_text)
            item.Content = grid
            item.Tag = group
            listbox.Items.Add(item)
            self.checks[group] = check
            self.items[group] = item
        if self.selected_group in self.items:
            listbox.SelectedItem = self.items[self.selected_group]
        self.update_summary(rows)
        self.fill_elements()

    def _tick_handler(self, group):
        def handler(sender, args):
            if sender.IsChecked:
                self.excluded.discard(group)
            else:
                self.excluded.add(group)
            self.update_summary(None)
        return handler

    def update_summary(self, rows):
        cache = self.purge_cache or {}
        if rows is None:
            rows = core.group_counts(cache.get(u"unused", []), cache.get(u"used", []))
        purge_count = sum(unused for group, unused, _ in rows if group not in self.excluded)
        left_out = len([row for row in rows if row[0] in self.excluded])
        text = u"{0} unused elements would be purged from the live model today".format(purge_count)
        if left_out:
            text += u"; {0} categories left out".format(left_out)
        text += u". The copy is rescanned when Clean Up runs."
        self.find(u"CategorySummaryText").Text = text

    def fill_elements(self):
        table = self.table
        table.Rows.Clear()
        cache = self.purge_cache
        if cache is None or self.selected_group is None:
            return
        show_used = self.show_used()
        words = [word for word in core.to_text(
            self.find(u"ElementSearchBox").Text).lower().split() if word]
        count = 0
        table.BeginLoadData()
        try:
            for value, name, group, status in cache.get(u"rows", []):
                if group != self.selected_group:
                    continue
                if status == u"Used" and not show_used:
                    continue
                lower = name.lower()
                if any(word not in lower for word in words):
                    continue
                row = table.NewRow()
                row[u"eid"] = u"{0}".format(value)
                row[u"name"] = name
                row[u"grp"] = group
                row[u"status"] = status
                table.Rows.Add(row)
                count += 1
                if count >= ROW_LIMIT:
                    break
        finally:
            table.EndLoadData()
        self.set_status(u"{0}: {1} element(s) shown".format(self.selected_group, count))

    # ------------------------------------------------------------
    def on_category_picked(self, sender, args):
        item = self.find(u"CategoryList").SelectedItem
        if item is None:
            return
        self.selected_group = core.to_text(item.Tag)
        self.fill_elements()

    def on_show_used(self, sender, args):
        self.fill_categories()

    def on_purge_toggled(self, sender, args):
        self.update_purge_enabled()

    def on_all(self, sender, args):
        for group, check in self.checks.items():
            check.IsChecked = True
            self.excluded.discard(group)
        self.update_summary(None)

    def on_none(self, sender, args):
        for group, check in self.checks.items():
            check.IsChecked = False
            self.excluded.add(group)
        self.update_summary(None)

    def on_search_typed(self, sender, args):
        self.search_timer.Stop()
        self.search_timer.Start()

    def on_search_tick(self, sender, args):
        self.search_timer.Stop()
        self.fill_categories()

    def on_template_changed(self, sender, args):
        if self.loading:
            return
        chosen = self.find(u"SettingsTemplateCombo").SelectedItem
        if chosen is None or core.to_text(chosen) == self.name:
            return
        self.name = core.to_text(chosen)
        self.values = core.load_template(self.name)
        self.push_values()
        self.set_status(u"Editing " + self.name)

    # ------------------------------------------------------------
    def aps_port(self):
        return core.as_int(self.find(u"ApsPortBox").Text, aps.DEFAULT_PORT, 1024, 65535)

    def update_aps_text(self):
        self.find(u"ApsCallbackText").Text = u"Callback URL: " + aps.callback_url(self.aps_port())
        client = core.to_text(self.find(u"ApsClientIdBox").Text).strip()
        text = u"No Client ID yet - publishing is off."
        if client:
            try:
                import mcu_web as web
                text = web.signed_in_text(client)
            except Exception:
                text = u"Publishing could not load on this Revit."
        self.find(u"ApsSignedInText").Text = text

    def on_port_typed(self, sender, args):
        try:
            self.update_aps_text()
        except Exception:
            pass

    def save_aps(self):
        settings = self.owner.settings
        settings[u"aps_client_id"] = core.to_text(self.find(u"ApsClientIdBox").Text).strip()
        settings[u"aps_port"] = u"{0}".format(self.aps_port())
        core.save_global(settings)

    def on_aps_help(self, sender, args):
        ui.prompt(self.window, u"Publish to ACC",
                  aps.SETUP_HELP.format(callback=aps.callback_url(self.aps_port())),
                  [(u"OK", True, u"BaseButton")], self.theme)

    def on_sign_out(self, sender, args):
        try:
            import mcu_web as web
            web.forget()
        except Exception:
            pass
        self.update_aps_text()
        self.set_status(u"Signed out of Autodesk for this tool.")

    def on_save(self, sender, args):
        self.save_aps()
        values = self.pull_values()
        warnings = core.retention_warnings(values)
        if warnings:
            answer = ui.prompt(
                self.window, u"Retained views and sheets",
                core.retention_message(values, warnings) +
                u"\n\nTurn the matching delete stages on?",
                [(u"Back", None, u"BaseButton"),
                 (u"Save as it is", False, u"OrangeButton"),
                 (u"Turn them on and save", True, u"GreenButton")], self.theme)
            if answer is None:
                return
            if answer:
                values = core.fix_retention(values, warnings)
        if not core.save_template(self.name, values):
            ui.prompt(self.window, u"Save", u"The template could not be written to\n" +
                      core.template_path(self.name), [(u"OK", True, u"BaseButton")], self.theme)
            return
        self.saved_name = self.name
        self.window.Close()

    def on_save_as_new(self, sender, args):
        answer, text = ui.prompt(
            self.window, u"Save as new template", u"Name the new settings template.",
            [(u"Cancel", False, u"BaseButton"), (u"Save", True, u"GreenButton")],
            self.theme, input_text=self.name + u" copy", input_hint=u"Template name")
        if not answer:
            return
        name = core.sanitize_name(text)
        if not name:
            self.set_status(u"A template needs a name.")
            return
        if name in core.list_templates():
            if not ui.prompt(self.window, u"Save as new template",
                             u"{0} already exists. Replace it?".format(name),
                             [(u"Cancel", False, u"BaseButton"),
                              (u"Replace", True, u"OrangeButton")], self.theme):
                return
        if not core.save_template(name, self.pull_values()):
            self.set_status(u"Could not write " + core.template_path(name))
            return
        self.name = name
        self.fill_templates()
        self.set_status(u"Saved as " + name)

    def on_delete(self, sender, args):
        if not ui.prompt(self.window, u"Delete template",
                         u"Delete the settings template {0}?".format(self.name),
                         [(u"Cancel", False, u"BaseButton"),
                          (u"Delete", True, u"RedGhostButton")], self.theme):
            return
        ok, reason = core.delete_template(self.name)
        if not ok:
            self.set_status(reason)
            return
        self.fill_templates()
        self.values = core.load_template(self.name)
        self.push_values()
        self.saved_name = self.name
        self.set_status(u"Deleted. Now editing " + self.name)

    # ---------------------------------------------------------- files
    def on_export_file(self, sender, args):
        """Write this template, as it stands on screen, to a file."""
        values = self.pull_values()
        dialog = SaveFileDialog()
        dialog.Title = u"Save the settings template to a file"
        dialog.Filter = u"Model Cleanup template (*.txt)|*.txt"
        dialog.DefaultExt = u".txt"
        dialog.AddExtension = True
        dialog.FileName = core.export_file_name(self.name)
        folder = self.owner.settings.get(u"template_folder") or u""
        if folder and os.path.isdir(folder):
            dialog.InitialDirectory = folder
        if not dialog.ShowDialog(self.window):
            return
        if not core.export_template(values, self.name, dialog.FileName):
            self.set_status(u"Could not write " + dialog.FileName)
            return
        self.remember_folder(dialog.FileName)
        self.set_status(u"Saved to " + dialog.FileName)

    def on_import_file(self, sender, args):
        dialog = OpenFileDialog()
        dialog.Title = u"Load a settings template from a file"
        dialog.Filter = u"Model Cleanup template (*.txt)|*.txt|All files (*.*)|*.*"
        folder = self.owner.settings.get(u"template_folder") or u""
        if folder and os.path.isdir(folder):
            dialog.InitialDirectory = folder
        if not dialog.ShowDialog(self.window):
            return
        values, suggested, error = core.import_template(dialog.FileName)
        if error:
            ui.prompt(self.window, u"Load from file", error,
                      [(u"OK", True, u"BaseButton")], self.theme)
            return
        self.remember_folder(dialog.FileName)
        answer, typed = ui.prompt(
            self.window, u"Load from file",
            u"Loaded from\n{0}\n\nSave it as a template under this name:".format(dialog.FileName),
            [(u"Cancel", False, u"BaseButton"), (u"Save", True, u"GreenButton")],
            self.theme, input_text=suggested, input_hint=u"Template name")
        if not answer:
            return
        name = core.sanitize_name(typed) or suggested
        existing = core.list_templates()
        if name in existing:
            choice = ui.prompt(
                self.window, u"Load from file",
                u"{0} already exists.".format(name),
                [(u"Cancel", None, u"BaseButton"),
                 (u"Keep both", u"both", u"BaseButton"),
                 (u"Replace it", u"replace", u"OrangeButton")], self.theme)
            if choice is None:
                return
            if choice == u"both":
                name = core.unique_template_name(name, existing)
        if not core.save_template(name, values):
            self.set_status(u"Could not save " + name)
            return
        self.name = name
        self.values = core.load_template(name)
        self.saved_name = name
        self.fill_templates()
        self.push_values()
        self.set_status(u"Loaded " + name + u". It is now the template being edited.")

    def remember_folder(self, path):
        self.owner.settings[u"template_folder"] = os.path.dirname(path)
        core.save_global(self.owner.settings)

    def on_cancel(self, sender, args):
        self.window.Close()

    def on_key(self, sender, args):
        try:
            if args.Handled:
                return
            if self.busy:
                args.Handled = True
                return
            if args.Key == Key.Escape:
                self.window.Close()
                args.Handled = True
        except Exception:
            pass
