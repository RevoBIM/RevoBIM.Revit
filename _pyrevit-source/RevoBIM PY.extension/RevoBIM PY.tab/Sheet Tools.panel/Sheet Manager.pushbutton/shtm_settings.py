# -*- coding: utf-8 -*-
"""The settings window.

Settings are global - which parameter holds the discipline is a house standard.
What is being looked at today is not a setting; that lives in the table.
"""

import shtm_clr  # noqa: F401  - references the assemblies first

import shtm_batch
import shtm_core
import shtm_model
import shtm_ui
from shtm_ui import ui_safe, text_block

from System.Windows import (
    Thickness, GridLength, GridUnitType, VerticalAlignment, TextTrimming,
)
from System.Windows.Controls import Grid, ColumnDefinition, ListBoxItem, TextBlock

THEME_LABELS = ["Auto - follow Revit", "Dark", "Light"]
THEME_KEYS = ["auto", "dark", "light"]

# the same four levels, in the same order, that Revit's own Browser
# Organization Properties dialog offers for sheets
GROUPING_LABELS = [u"1st Grouping", u"2nd Grouping", u"3rd Grouping",
                   u"4th Grouping"]
NAME_LABELS = [u"Sheet name part 1", u"Sheet name part 2", u"Sheet name part 3"]
NO_PARAMETER = u"(none)"


def _col(fixed=None):
    definition = ColumnDefinition()
    if fixed:
        definition.Width = GridLength(float(fixed))
    else:
        definition.Width = GridLength(1, GridUnitType.Star)
    return definition


class SettingsWindow(object):

    def __init__(self, doc, settings, mode, owner=None):
        self.doc = doc
        self.settings = dict(settings)
        self.owner = owner
        self.mode = mode
        self.saved = None
        self.applying = False
        self.window = shtm_ui.load_window("ShtmSettings.xaml", mode)
        self.find = self.window.FindName
        self.chrome = shtm_ui.Chrome(self.window)
        shtm_ui.load_icon(self.find("LogoImage"))
        shtm_ui.attach_egg(self.window, self.find("LogoHost"), self.mode)
        self.find("VersionText").Text = u"v{0}".format(shtm_core.__version__)
        self._fill()
        self._wire()

    def _fill(self):
        settings = self.settings
        theme_box = self.find("ThemeCombo")
        for label in THEME_LABELS:
            theme_box.Items.Add(_item(label))
        current = settings.get("theme", "auto")
        theme_box.SelectedIndex = (THEME_KEYS.index(current)
                                   if current in THEME_KEYS else 0)

        results = self.find("ResultsCombo")
        for key in shtm_core.RESULT_CHOICES:
            results.Items.Add(_item(shtm_core.RESULT_LABELS[key]))
        current = settings.get("show_results", "needed")
        results.SelectedIndex = (shtm_core.RESULT_CHOICES.index(current)
                                 if current in shtm_core.RESULT_CHOICES else 0)

        self.find("IncludePlaceholders").IsChecked = shtm_core.as_bool(
            settings.get("include_placeholders"))
        self.find("OnlyInSheetList").IsChecked = shtm_core.as_bool(
            settings.get("only_in_sheet_list"))
        self.find("ConfirmBox").IsChecked = shtm_core.as_bool(
            settings.get("confirm_before_write"))

        self.find("ColumnsBox").Text = settings.get("columns", u"")
        self._build_grouping(shtm_core.split_list(
            settings.get("grouping_parameters")))
        self._build_name_params(shtm_core.split_slots(
            settings.get("name_parameters")))
        self.find("NameDelimiter").Text = shtm_core.delimiter_of(
            settings.get("name_delimiter"))
        self.find("PathNote").Text = u"Saved at {0}".format(shtm_core.settings_path())
        self._browser_note()
        self._build_presets()

    # ============ view template presets ============

    def _build_presets(self):
        """A template picker, a field for every value a preset can hold, and
        the list of presets kept so far. Kept by template name, so a preset
        follows its template into every project."""
        self.presets = shtm_batch.presets_from_text(self.settings.get("template_presets"))
        self.presets_changed = False
        self.preset_params = shtm_model.grouping_parameters(self.doc, self.settings)
        try:
            grouped = shtm_model.view_templates(self.doc)
        except Exception:
            grouped = {}
        self.template_kinds = {}
        for view_type in grouped:
            for template in grouped[view_type]:
                self.template_kinds[template["name"]] = view_type
        names = sorted(self.template_kinds.keys(), key=shtm_core.natural_key)

        host = self.find("PresetTemplateHost")
        host.Children.Clear()
        self.preset_picker = shtm_ui.ValuePicker(
            names, u"", strict=True, placeholder=u"pick a view template",
            on_pick=self._preset_picked)
        host.Children.Add(self.preset_picker.root)

        fields = self.find("PresetFieldsHost")
        fields.Children.Clear()
        self.preset_boxes = {}
        labels = [(u"number", u"Sheet number becomes"),
                  (u"name", u"Sheet name becomes"),
                  (u"view", u"View name becomes")]
        for key, label in labels:
            box = shtm_ui.text_box(u"blank - type it in Duplicate", None, "Txt.Field")
            fields.Children.Add(self._field_row(label, box))
            self.preset_boxes[key] = box
        for parameter in self.preset_params:
            try:
                values = shtm_model.project_values(self.doc, parameter)
            except Exception:
                values = []
            picker = shtm_ui.ValuePicker(values, u"",
                                         placeholder=u"blank - keep each sheet's")
            fields.Children.Add(self._field_row(parameter, picker.root))
            self.preset_boxes[parameter] = picker.box
        self._fill_preset_list()

    def _field_row(self, label, control):
        line = Grid()
        line.ColumnDefinitions.Add(_col(170))
        line.ColumnDefinitions.Add(_col(None))
        line.Margin = Thickness(0, 0, 0, 5)
        caption = text_block(label, "Lbl.Body")
        caption.VerticalAlignment = VerticalAlignment.Center
        caption.TextTrimming = TextTrimming.CharacterEllipsis
        caption.ToolTip = label
        Grid.SetColumn(caption, 0)
        line.Children.Add(caption)
        Grid.SetColumn(control, 1)
        line.Children.Add(control)
        return line

    def _fill_preset_list(self):
        listing = self.find("PresetList")
        listing.Items.Clear()
        names = sorted(self.presets.keys(), key=shtm_core.natural_key)
        for name in names:
            summary = shtm_batch.preset_summary(self.presets[name], self.preset_params)
            missing = name not in self.template_kinds
            block = TextBlock()
            block.Text = u"{0}{1}   \u2014   {2}".format(
                name, u"  (not in this project)" if missing else u"", summary)
            block.TextTrimming = TextTrimming.CharacterEllipsis
            item = ListBoxItem()
            shtm_ui.styled(item, "Lst.Item")
            item.Content = block
            item.ToolTip = u"{0}\n{1}".format(name, summary)
            item.Tag = name
            listing.Items.Add(item)
        self.find("PresetListTitle").Text = (
            u"Presets ({0})".format(len(names)) if names
            else u"No presets yet - pick a template above, fill in what it brings, "
                 u"and press Keep preset")
        self._paint_preset_buttons()

    def _preset_picked(self, name):
        self._load_preset(name)

    def _load_preset(self, name):
        """Show a template's preset in the fields - or empty fields, ready to
        make one."""
        preset = self.presets.get(name) or {}
        params = preset.get("params") or {}
        for key in self.preset_boxes:
            if key in shtm_batch.FIXED_KEYS:
                value = preset.get(key) or u""
            else:
                value = params.get(key) or u""
            self.preset_boxes[key].Text = value
        self._paint_preset_buttons()
        if name in self.presets:
            self.find("StatusText").Text = u"editing the preset for {0}".format(name)
        elif name:
            self.find("StatusText").Text = (
                u"{0} has no preset yet - fill in what it brings and press "
                u"Keep preset".format(name))

    def _preset_from_fields(self):
        preset = {"params": {}}
        for key in self.preset_boxes:
            value = (self.preset_boxes[key].Text or u"").strip()
            if not value:
                continue
            if key in shtm_batch.FIXED_KEYS:
                preset[key] = value
            else:
                preset["params"][key] = value
        return preset

    def _paint_preset_buttons(self):
        name = (self.preset_picker.text or u"").strip()
        self.find("PresetKeepBtn").IsEnabled = bool(name)
        self.find("PresetDeleteBtn").IsEnabled = name in self.presets

    @ui_safe
    def _preset_keep(self, sender, event):
        name = (self.preset_picker.text or u"").strip()
        if not name:
            self.find("StatusText").Text = u"pick a view template first"
            return
        preset = self._preset_from_fields()
        if shtm_batch.preset_is_empty(preset):
            self.find("StatusText").Text = (
                u"fill in at least one value - an empty preset fills in nothing")
            return
        replacing = name in self.presets
        self.presets[name] = shtm_batch.merge_preset(self.presets.get(name), preset,
                                                     self.preset_params)
        self.presets_changed = True
        self._fill_preset_list()
        self._say_unsaved(u"{0} the preset for {1}".format(
            u"Updated" if replacing else u"Kept", name))

    @ui_safe
    def _preset_delete(self, sender, event):
        name = (self.preset_picker.text or u"").strip()
        if name not in self.presets:
            return
        del self.presets[name]
        self.presets_changed = True
        # empty the fields too - Apply keeps what is in them, and would
        # otherwise put the deleted preset straight back
        self._load_preset(name)
        self._fill_preset_list()
        self._say_unsaved(u"Deleted the preset for {0}".format(name))

    @ui_safe
    def _preset_clear(self, sender, event):
        self.preset_picker.set_text(u"")
        self._load_preset(u"")
        # so clicking the same preset in the list loads it again
        self.find("PresetList").SelectedIndex = -1
        self.find("StatusText").Text = u""

    @ui_safe
    def _preset_listed(self, sender, event):
        item = sender.SelectedItem
        if item is None:
            return
        name = u"{0}".format(item.Tag)
        self.preset_picker.set_text(name)
        self._load_preset(name)

    def _pending_preset(self):
        """(name, merged preset) for what is in the fields when it differs from
        what is kept, else (None, None)."""
        picker = getattr(self, "preset_picker", None)
        if picker is None:
            return None, None
        name = (picker.text or u"").strip()
        if not name:
            return None, None
        preset = self._preset_from_fields()
        if shtm_batch.preset_is_empty(preset):
            return None, None
        merged = shtm_batch.merge_preset(self.presets.get(name), preset,
                                         self.preset_params)
        if self.presets.get(name) == merged:
            return None, None
        return name, merged

    def _keep_pending_preset(self):
        name, merged = self._pending_preset()
        if name is not None:
            self.presets[name] = merged

    def _say_unsaved(self, said):
        status = self.find("StatusText")
        status.Text = u"{0} - press Apply to save it".format(said)
        status.SetResourceReference(TextBlock.ForegroundProperty, "OrangeBrush")

    def _build_grouping(self, chosen):
        """Four pickers, one per level, each a keyword search over the sheet
        parameters this project actually has - the same four levels the Browser
        Organization Properties dialog offers, and in the same order."""
        self.grouping_pickers = self._pickers(self.find("GroupingHost"),
                                              GROUPING_LABELS, chosen)

    def _build_name_params(self, chosen):
        """Three pickers, one per segment of the sheet name. Separate from the
        grouping pickers on purpose: they are separate jobs, and sharing a
        default between them is what wrote 'Level 01' into the discipline."""
        self.name_pickers = self._pickers(self.find("NameParamsHost"),
                                          NAME_LABELS, chosen)

    def _pickers(self, host, labels, chosen):
        host.Children.Clear()
        made = []
        names = [NO_PARAMETER] + shtm_model.sheet_parameter_names(self.doc)
        for index, label in enumerate(labels):
            line = Grid()
            line.ColumnDefinitions.Add(_col(140))
            line.ColumnDefinitions.Add(_col(None))
            line.Margin = Thickness(0, 0, 0, 5)
            caption = text_block(label, "Lbl.Body")
            caption.VerticalAlignment = VerticalAlignment.Center
            Grid.SetColumn(caption, 0)
            line.Children.Add(caption)
            current = chosen[index] if index < len(chosen) else NO_PARAMETER
            if not current:
                current = NO_PARAMETER
            offered = list(names)
            if current not in offered:
                offered.append(current)
            picker = shtm_ui.ValuePicker(offered, current, strict=True,
                                         placeholder=u"pick a sheet parameter")
            Grid.SetColumn(picker.root, 1)
            line.Children.Add(picker.root)
            made.append(picker)
            host.Children.Add(line)
        return made

    def _picked(self, pickers, keep_gaps=False):
        chosen = []
        for picker in pickers or []:
            text = (picker.text or u"").strip()
            if text == NO_PARAMETER:
                text = u""
            if text and text in chosen:
                text = u""
            if text or keep_gaps:
                chosen.append(text)
        return chosen

    def _grouping_values(self):
        return self._picked(getattr(self, "grouping_pickers", []))

    def _browser_note(self):
        names = shtm_model.browser_organisation(self.doc)
        organisation = shtm_model.browser_organisation_name(self.doc)
        if names:
            self.find("BrowserNote").Text = u'"{0}" groups sheets by {1}'.format(
                organisation or u"the current browser organisation", u", ".join(names))
        else:
            self.find("BrowserNote").Text = (
                u"the project browser is not grouping sheets by a parameter")

    def _wire(self):
        self.find("CancelBtn").Click += ui_safe(self._cancel)
        self.window.Closing += self._closing
        self.find("PresetKeepBtn").Click += self._preset_keep
        self.find("PresetDeleteBtn").Click += self._preset_delete
        self.find("PresetClearBtn").Click += self._preset_clear
        self.find("PresetList").SelectionChanged += self._preset_listed
        self.find("ApplyBtn").Click += ui_safe(self._apply)
        self.find("ReadBrowserBtn").Click += ui_safe(self._read_browser)
        self.find("ResetDupBtn").Click += ui_safe(self._reset_dup)

    def _cancel(self, sender, event):
        self.window.Close()

    @ui_safe
    def _closing(self, sender, event):
        """Presets are saved with Apply. Closing any other way - Cancel, the X,
        Esc - with presets changed, or values typed into the preset fields and
        not yet kept, asks first rather than losing them without a word."""
        if self.applying:
            return
        name, _merged = self._pending_preset()
        if not (getattr(self, "presets_changed", False) or name):
            return
        if not shtm_ui.confirm(self.mode, self.window, u"Preset changes",
                               u"The preset changes have not been saved. Close "
                               u"without saving them?", u"Close without saving",
                               u"Go back"):
            event.Cancel = True

    @ui_safe
    def _read_browser(self, sender, event):
        names = shtm_model.browser_organisation(self.doc)
        if not names:
            self.find("StatusText").Text = (
                u"the project browser is not grouping sheets by a parameter")
            return
        self._build_grouping(names)
        self.find("StatusText").Text = u"read {0} grouping parameter(s)".format(len(names))

    @ui_safe
    def _reset_dup(self, sender, event):
        shtm_core.reset_duplicate_options(self.settings)
        self.find("StatusText").Text = u"the duplicate options are back to their defaults"

    @ui_safe
    def _apply(self, sender, event):
        settings = self.settings
        index = self.find("ThemeCombo").SelectedIndex
        settings["theme"] = THEME_KEYS[index] if 0 <= index < len(THEME_KEYS) else "auto"
        index = self.find("ResultsCombo").SelectedIndex
        settings["show_results"] = (shtm_core.RESULT_CHOICES[index]
                                    if 0 <= index < len(shtm_core.RESULT_CHOICES)
                                    else "needed")
        settings["include_placeholders"] = shtm_core.bool_text(
            self.find("IncludePlaceholders").IsChecked)
        settings["only_in_sheet_list"] = shtm_core.bool_text(
            self.find("OnlyInSheetList").IsChecked)
        settings["confirm_before_write"] = shtm_core.bool_text(
            self.find("ConfirmBox").IsChecked)
        settings["columns"] = shtm_core.join_list(
            shtm_core.split_list(self.find("ColumnsBox").Text))
        settings["grouping_parameters"] = shtm_core.join_list(
            self._grouping_values())
        settings["name_parameters"] = shtm_core.join_slots(
            self._picked(getattr(self, "name_pickers", []), True))
        settings["name_delimiter"] = shtm_core.delimiter_stored(
            self.find("NameDelimiter").Text)
        # what is in the preset fields counts, Keep pressed or not: picking a
        # template, typing its values and pressing Apply should not lose them
        self._keep_pending_preset()
        settings["template_presets"] = shtm_batch.presets_to_text(
            getattr(self, "presets", {}))
        try:
            shtm_core.save_settings(settings)
        except Exception as exc:
            self.find("StatusText").Text = u"could not save: {0}".format(exc)
            return
        self.saved = settings
        self.applying = True
        self.window.Close()

    def show(self):
        if self.owner is not None:
            try:
                shtm_ui.bring_back(self.owner)
                self.window.Owner = self.owner
            except Exception:
                pass
        self.window.ShowDialog()
        return self.saved


def _item(text):
    from System.Windows.Controls import ComboBoxItem
    item = ComboBoxItem()
    item.Content = text
    shtm_ui.styled(item, "Cmb.Item")
    return item
