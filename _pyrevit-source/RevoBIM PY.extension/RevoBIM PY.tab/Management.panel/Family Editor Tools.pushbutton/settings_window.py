# =========================================================================
# Family Editor Tools - settings
# =========================================================================

import fet_clr  # noqa: F401  - assemblies first, always

from System.Windows import GridLength, GridUnitType, Thickness
from System.Windows.Controls import (CheckBox, ColumnDefinition, ComboBoxItem,
                                     Grid, TextBlock)

import fet_core
import fet_model
import fet_ui
import theme

THEME_CHOICES = ((u"follow", u"Follow Revit"),
                 (u"dark", u"Dark"),
                 (u"light", u"Light"))

BINDING_CHOICES = ((u"type", u"Type"), (u"instance", u"Instance"))

RESULTS_CHOICES = ((u"needed", u"Only if something needs a look"),
                   (u"always", u"Always"),
                   (u"never", u"Never"))

# Which tab to open on.  The family icon panel's own button opens this same
# window rather than a second copy - two settings windows for one set of
# settings is two places for them to disagree.
TABS = (u"general", u"icon", u"icon_options", u"naming")

TICK_COLUMNS = 2


def _fill(combo, choices, current):
    combo.Items.Clear()
    chosen = 0
    for index, pair in enumerate(choices):
        key, label = pair
        item = ComboBoxItem()
        item.Content = label
        item.Tag = key
        combo.Items.Add(item)
        if key == current:
            chosen = index
    if combo.Items.Count:
        combo.SelectedIndex = chosen


def _value(combo, fallback):
    item = combo.SelectedItem
    if item is None:
        return fallback
    return fet_core._as_text(item.Tag)


class SettingsWindow(object):
    def __init__(self, settings, palette_name, owner=None, on_applied=None,
                 tab=u"general"):
        self.settings = dict(settings)
        self.on_applied = on_applied
        self.ticks = {}
        self.window = fet_ui.load_window(u"FetSettings.xaml", palette_name)
        find = self.window.FindName
        find(u"VersionText").Text = u"v" + fet_core.__version__
        self.status_text = find(u"StatusText")
        self.chrome = fet_ui.Chrome(self.window, find(u"HeaderBar"),
                                    find(u"GripHost"), 680.0, 540.0)

        self.theme_combo = find(u"ThemeCombo")
        self.binding_combo = find(u"BindingCombo")
        self.group_combo = find(u"GroupCombo")
        self.results_combo = find(u"ResultsCombo")
        self.group_by_spf = find(u"GroupBySpfCheck")
        self.overwrite = find(u"OverwriteCheck")
        self.debug = find(u"DebugCheck")
        self.extent_box = find(u"ExtentBox")
        self.dim_offset_box = find(u"DimOffsetBox")
        self.dim_step_box = find(u"DimStepBox")
        self.width_box = find(u"ParamWidthBox")
        self.depth_box = find(u"ParamDepthBox")
        self.height_box = find(u"ParamHeightBox")
        self.clearance_box = find(u"ParamClearanceBox")
        self.create_params = find(u"CreateParamsCheck")
        self.radius_box = find(u"ParamRadiusBox")

        _fill(self.theme_combo, THEME_CHOICES,
              fet_core._as_text(self.settings.get(u"theme", u"follow")))
        _fill(self.binding_combo, BINDING_CHOICES,
              fet_core._as_text(self.settings.get(u"default_binding", u"type")))
        _fill(self.results_combo, RESULTS_CHOICES,
              fet_core._as_text(self.settings.get(u"show_results", u"needed")))

        groups = [(option.key, option.label) for option in fet_model.group_options()]
        if not groups:
            groups = [(u"Data", u"Data")]
        _fill(self.group_combo, groups,
              fet_core._as_text(self.settings.get(u"default_group", u"Data")))

        self.group_by_spf.IsChecked = fet_core.setting_on(self.settings,
                                                          u"group_by_spf_group")
        self.overwrite.IsChecked = fet_core.setting_on(self.settings,
                                                       u"overwrite_existing")
        self.debug.IsChecked = fet_core.setting_on(self.settings, u"debug")
        self.create_params.IsChecked = fet_core.setting_on(self.settings,
                                                           u"create_plane_params")
        self.extent_box.Text = fet_core._as_text(self.settings.get(u"plane_extent_mm"))
        self.dim_offset_box.Text = fet_core._as_text(self.settings.get(u"dim_offset_mm"))
        self.dim_step_box.Text = fet_core._as_text(self.settings.get(u"dim_step_mm"))
        self.width_box.Text = fet_core._as_text(self.settings.get(u"param_width"))
        self.depth_box.Text = fet_core._as_text(self.settings.get(u"param_depth"))
        self.height_box.Text = fet_core._as_text(self.settings.get(u"param_height"))
        self.clearance_box.Text = fet_core._as_text(self.settings.get(u"param_clearance"))
        self.radius_box.Text = fet_core._as_text(self.settings.get(u"param_radius"))
        self._fill_icon()
        self._select_tab(tab)

        self.find = find
        find(u"CloseButton").Click += self.on_close
        find(u"ApplyButton").Click += self.on_apply
        find(u"ShortcutsButton").Click += self.on_shortcuts
        self.theme_combo.SelectionChanged += self.on_theme_picked

        if owner is not None:
            try:
                self.window.Owner = owner
            except Exception:
                pass


    # =====================================================================
    # The family icon and naming tabs
    # =====================================================================
    def _select_tab(self, wanted):
        try:
            index = list(TABS).index(fet_core._as_text(wanted))
        except Exception:
            index = 0
        try:
            self.find(u"SettingsTabs").SelectedIndex = index
        except Exception:
            pass

    def _fill_icon(self):
        find = self.find
        styles = fet_core.DISPLAY_STYLES
        _fill(find(u"Style3DCombo"), styles,
              fet_core._as_text(self.settings.get(u"icon_3d_style")))
        _fill(find(u"Style2DCombo"), styles,
              fet_core._as_text(self.settings.get(u"icon_2d_style")))
        _fill(find(u"Detail3DCombo"), fet_core.DETAIL_LEVELS,
              fet_core._as_text(self.settings.get(u"icon_3d_detail")))
        _fill(find(u"Detail2DCombo"), fet_core.DETAIL_LEVELS,
              fet_core._as_text(self.settings.get(u"icon_2d_detail")))
        _fill(find(u"Scale3DCombo"), fet_core.VIEW_SCALES,
              fet_core._as_text(self.settings.get(u"icon_3d_scale")))
        _fill(find(u"Scale2DCombo"), fet_core.VIEW_SCALES,
              fet_core._as_text(self.settings.get(u"icon_2d_scale")))
        _fill(find(u"ViewTypeCombo"),
              # _fill takes (label, key) - the other way round puts the
              # key on screen and the label in the settings file.
              [(label, key) for key, label, corner in fet_core.VIEW_TYPES],
              fet_core._as_text(self.settings.get(u"icon_view_type")))
        find(u"ViewNameBox").Text = fet_core._as_text(
            self.settings.get(u"icon_view_name"))
        self._build_ticks()
        for name, key in ((u"CompanyListBox", u"name_company_list"),
                          (u"TypeListBox", u"name_type_list"),
                          (u"DisciplineListBox", u"name_discipline_list")):
            find(name).Text = fet_core.abbreviation_lines(
                fet_core.parse_abbreviations(self.settings.get(key, u"")))

    def _build_ticks(self):
        u"""Two columns, filled down the left then down the right, the way
        Revit's own dialogs lay their tick lists out."""
        host = self.find(u"TickHost")
        host.Children.Clear()
        entries = list(fet_core.ICON_TICKS)
        half = (len(entries) + TICK_COLUMNS - 1) // TICK_COLUMNS
        rows = []
        for _index in range(half):
            grid = Grid()
            for _column in range(TICK_COLUMNS):
                definition = ColumnDefinition()
                definition.Width = GridLength(1, GridUnitType.Star)
                grid.ColumnDefinitions.Add(definition)
            rows.append(grid)
            host.Children.Add(grid)
        for index, entry in enumerate(entries):
            key, label = entry
            check = CheckBox()
            check.Content = label
            check.IsChecked = fet_core.setting_on(self.settings, key)
            check.Margin = Thickness(0, 4, 10, 4)
            self.ticks[key] = check
            column = 0 if index < half else 1
            row = index if index < half else index - half
            Grid.SetColumn(check, column)
            rows[row].Children.Add(check)

    def _icon_values(self):
        find = self.find
        values = {}
        values[u"icon_3d_style"] = _value(find(u"Style3DCombo"), u"Realistic")
        values[u"icon_2d_style"] = _value(find(u"Style2DCombo"), u"HiddenLine")
        values[u"icon_3d_detail"] = _value(find(u"Detail3DCombo"), u"Fine")
        values[u"icon_2d_detail"] = _value(find(u"Detail2DCombo"), u"Fine")
        values[u"icon_3d_scale"] = _value(find(u"Scale3DCombo"), u"1")
        values[u"icon_2d_scale"] = _value(find(u"Scale2DCombo"), u"1")
        values[u"icon_view_type"] = _value(find(u"ViewTypeCombo"),
                                           u"top_back_left")
        name = fet_core._as_text(find(u"ViewNameBox").Text).strip()
        values[u"icon_view_name"] = name or fet_core.DEFAULTS[u"icon_view_name"]
        find(u"ViewNameBox").Text = values[u"icon_view_name"]
        for key in self.ticks:
            values[key] = u"on" if self.ticks[key].IsChecked else u"off"
        for name, key in ((u"CompanyListBox", u"name_company_list"),
                          (u"TypeListBox", u"name_type_list"),
                          (u"DisciplineListBox", u"name_discipline_list")):
            items = fet_core.parse_abbreviation_lines(find(name).Text)
            values[key] = fet_core.format_abbreviations(items)
            # Written back from what actually parsed, so a typo shows up
            # straight away rather than silently doing nothing.
            find(name).Text = fet_core.abbreviation_lines(items)
        return values


    def set_status(self, text, kind=u"muted"):
        try:
            self.status_text.Text = text
            key = {u"red": u"RedBrush", u"green": u"GreenBrush",
                   u"orange": u"OrangeBrush"}.get(kind, u"MutedBrush")
            self.status_text.SetResourceReference(TextBlock.ForegroundProperty, key)
        except Exception:
            pass

    @fet_ui.ui_safe
    def on_theme_picked(self, sender, args):
        u"""The theme applies the moment it is picked, on this window, so
        the choice can be seen rather than imagined."""
        chosen = _value(self.theme_combo, u"follow")
        theme.apply(self.window, theme.resolve(chosen))

    @fet_ui.ui_safe
    def on_shortcuts(self, sender, args):
        u"""Revit's own Keyboard Shortcuts dialog.  The tool is a single
        command button with a single line title, so it can be found in
        that list and bound to keys."""
        opened = False
        try:
            from Autodesk.Revit.UI import PostableCommand, RevitCommandId
            from pyrevit import HOST_APP
            command = RevitCommandId.LookupPostableCommandId(
                PostableCommand.KeyboardShortcuts)
            HOST_APP.uiapp.PostCommand(command)
            opened = True
        except Exception:
            opened = False
        if opened:
            self.set_status(u"Search for 'Family Editor Tools'", u"green")
        else:
            self.set_status(u"View > User Interface > Keyboard Shortcuts",
                            u"orange")

    @fet_ui.ui_safe
    def on_apply(self, sender, args):
        values = dict(self.settings)
        values[u"theme"] = _value(self.theme_combo, u"follow")
        values[u"default_binding"] = _value(self.binding_combo, u"type")
        values[u"default_group"] = _value(self.group_combo, u"Data")
        values[u"show_results"] = _value(self.results_combo, u"needed")
        values[u"group_by_spf_group"] = u"on" if self.group_by_spf.IsChecked else u"off"
        values[u"overwrite_existing"] = u"on" if self.overwrite.IsChecked else u"off"
        values[u"debug"] = u"on" if self.debug.IsChecked else u"off"
        values[u"create_plane_params"] = u"on" if self.create_params.IsChecked else u"off"
        for key, box, fallback in (
                (u"plane_extent_mm", self.extent_box, u"1500"),
                (u"dim_offset_mm", self.dim_offset_box, u"250"),
                (u"dim_step_mm", self.dim_step_box, u"150")):
            number = fet_core.to_number(box.Text, None)
            if number is None or number <= 0:
                values[key] = fallback
                box.Text = fallback
            else:
                values[key] = u"{0:g}".format(number)
        for key, box in ((u"param_width", self.width_box),
                         (u"param_depth", self.depth_box),
                         (u"param_height", self.height_box),
                         (u"param_clearance", self.clearance_box),
                         (u"param_radius", self.radius_box)):
            text = fet_core._as_text(box.Text).strip()
            if text:
                values[key] = text
            else:
                box.Text = fet_core.DEFAULTS[key]
                values[key] = fet_core.DEFAULTS[key]
        values.update(self._icon_values())
        if fet_core.save_settings(values):
            self.settings = values
            self.set_status(u"Saved", u"green")
            if self.on_applied:
                self.on_applied(values)
        else:
            self.set_status(u"The settings file would not write", u"red")

    @fet_ui.ui_safe
    def on_close(self, sender, args):
        self.window.Close()

    def show(self):
        try:
            self.window.ShowDialog()
        except Exception:
            fet_core.log(u"the settings window would not open")
        return self.settings
