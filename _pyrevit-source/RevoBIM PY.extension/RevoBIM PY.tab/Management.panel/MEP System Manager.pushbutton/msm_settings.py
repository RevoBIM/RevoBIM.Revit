# -*- coding: utf-8 -*-
"""The settings window, opened from the gear in the main window's header.
Modal, themed, two columns so it fits without scrolling. Nothing is saved
until Apply."""
import msm_clr  # noqa: F401  - assemblies first

from System.Windows import Thickness, Visibility
from System.Windows.Controls import CheckBox

import msm_core as core
import msm_theme as theme
import msm_ui as ui

SCOPES = ((u"project", u"Whole project"), (u"view", u"Active view only"))
ISOLATE = ((u"pipes", u"The selected rows only"),
           (u"fittings", u"The rows + connected fittings and accessories"),
           (u"systems", u"Whole systems (containment: whole runs)"))
THEMES = ((u"auto", u"Auto - follow Revit's canvas"), (u"dark", u"Dark"), (u"light", u"Light"))
RESULTS = ((u"issues", u"Only if something needs a look"), (u"always", u"Always"),
           (u"never", u"Never"))
SYSTEM_NAME = u"<the system's own name>"
RUN_NAME = u"<the run it belongs to>"


def fill(combo, pairs, current):
    combo.Items.Clear()
    chosen = 0
    for index, (key, text) in enumerate(pairs):
        combo.Items.Add(text)
        if key == current:
            chosen = index
    combo.SelectedIndex = chosen


def picked(combo, pairs):
    index = combo.SelectedIndex
    if 0 <= index < len(pairs):
        return pairs[index][0]
    return pairs[0][0]


class SettingsDialog(object):
    """Settings for the tab it was opened from: grouping, rows, what Change
    Type keeps are that tab's own; isolate, theme and results are shared."""

    def __init__(self, owner, settings, param_names, all_param_names):
        self.settings = settings.copy()
        self.domain = getattr(settings, u"domain", u"pipe")
        info = core.domain_info(self.domain)
        self.group_by = info[u"group_options"]
        self.saved = False
        self.param_names = list(param_names)
        self.all_param_names = list(all_param_names)
        mode = settings.get(u"theme", u"auto")
        self.window = ui.load_window(u"MsmSettings.xaml", mode)
        w = self.window
        find = w.FindName
        self.find = find
        if owner is not None:
            try:
                w.Owner = owner
            except Exception:
                pass
        find(u"VersionText").Text = u"v{0}".format(core.__version__)
        ui.load_icon(find(u"Logo"))
        ui.Chrome(w, header=find(u"HeaderBar"), close_button=find(u"BtnClose"),
                  resizable=False)
        ui.attach_egg(w, find(u"LogoHost"),
                      lambda: theme.palette(theme.resolve(self.settings.get(u"theme"))))

        find(u"SubTitle").Text = u"{0} Settings".format(info[u"tab"])
        cont = self.domain == u"cont"
        find(u"LblGroupBy").Text = u"Service type from" if cont else u"Group services by"
        find(u"LblSystemFrom").Text = u"Run from" if cont else u"System number from"
        find(u"ChkSType").Content = info[u"type_word"]
        find(u"ChkSSystem").Content = info[u"system_word"]
        find(u"ChangeTitle").Text = u"Change {0}".format(info[u"type_word"].lower())
        find(u"ChkFittings").Content = u"Swap fittings to {0}".format(info[u"swap_source"])
        find(u"ChkKeepSize").Content = u"Keep each {0}'s size".format(info[u"noun"][0])

        s = self.settings
        fill(find(u"CmbGroupBy"), self.group_by, s.get(u"group_by"))
        group_params = [(n, n) for n in self.all_param_names]
        fill(find(u"CmbGroupParam"), group_params or [(u"", u"(no parameters found)")],
             s.get(u"group_param"))
        system_from = [(u"", RUN_NAME if cont else SYSTEM_NAME)] + \
            [(n, n) for n in self.all_param_names]
        fill(find(u"CmbSystemFrom"), system_from, s.get(u"system_from"))
        self.system_from = system_from
        self.group_params = group_params
        fill(find(u"CmbSScope"), SCOPES, s.get(u"scope"))
        fill(find(u"CmbIsolateWhat"), ISOLATE, s.get(u"isolate_what"))
        fill(find(u"CmbTheme"), THEMES, s.get(u"theme"))
        fill(find(u"CmbResults"), RESULTS, s.get(u"show_results"))
        find(u"ChkLinked").IsChecked = core.to_bool(s.get(u"lookup_linked", u"0"))
        fill(find(u"CmbFittingMode"), core.FITTING_MODES, s.get(u"fitting_mode"))
        find(u"TxtAccessoryParams").Text = s.get(u"accessory_params", u"")
        find(u"ChkDisconnect").IsChecked = core.to_bool(s.get(u"allow_disconnect"))

        find(u"ChkSSystem").IsChecked = core.to_bool(s.get(u"split_system"))
        find(u"ChkSType").IsChecked = core.to_bool(s.get(u"split_type"))
        find(u"ChkSSize").IsChecked = core.to_bool(s.get(u"split_size"))
        find(u"ChkZoom").IsChecked = core.to_bool(s.get(u"isolate_zoom"))
        find(u"ChkSectionBox").IsChecked = core.to_bool(s.get(u"isolate_section_box"))
        find(u"TxtMargin").Text = s.get(u"section_margin_mm", u"300")
        find(u"ChkSelect").IsChecked = core.to_bool(s.get(u"isolate_select"))
        find(u"ChkFittings").IsChecked = core.to_bool(s.get(u"swap_fittings"))
        find(u"ChkKeepSize").IsChecked = core.to_bool(s.get(u"keep_size"))

        find(u"CmbGroupBy").SelectionChanged += ui.ui_safe(
            lambda a, b: self.sync_group_param(), u"Group by")
        find(u"CmbTheme").SelectionChanged += ui.ui_safe(
            lambda a, b: self.preview_theme(), u"Theme")
        self.sync_group_param()

        self.retain_boxes = []
        retained = set(core.split_list(s.get(u"retain")))
        names = sorted(set(self.param_names) | retained, key=core.natural_key)
        host = find(u"RetainHost")
        for name in names:
            box = CheckBox()
            box.Content = name
            box.Tag = name
            box.Margin = Thickness(0, 3, 0, 3)
            box.IsChecked = name in retained
            box.Checked += ui.ui_safe(lambda a, b: self.count_retained(), u"Retain")
            box.Unchecked += ui.ui_safe(lambda a, b: self.count_retained(), u"Retain")
            host.Children.Add(box)
            self.retain_boxes.append(box)
        find(u"TxtRetainSearch").TextChanged += ui.ui_safe(
            lambda a, b: self.search_retained(), u"Retain search")
        find(u"BtnRetainAll").Click += ui.ui_safe(lambda a, b: self.tick_shown(True), u"All")
        find(u"BtnRetainNone").Click += ui.ui_safe(lambda a, b: self.tick_shown(False), u"None")
        self.count_retained()

        find(u"BtnCancel").Click += lambda a, b: w.Close()
        find(u"BtnApply").Click += ui.ui_safe(lambda a, b: self.apply(), u"Apply",
                                              self.set_status)

    def set_status(self, text):
        try:
            self.find(u"StatusText").Text = text
        except Exception:
            pass

    def sync_group_param(self):
        is_param = picked(self.find(u"CmbGroupBy"), self.group_by) == u"param"
        self.find(u"CmbGroupParam").IsEnabled = is_param

    def preview_theme(self):
        theme.apply(self.window, picked(self.find(u"CmbTheme"), THEMES))

    def search_retained(self):
        text = self.find(u"TxtRetainSearch").Text
        for box in self.retain_boxes:
            match = core.keyword_match(box.Tag, text)
            box.Visibility = Visibility.Visible if match else Visibility.Collapsed

    def tick_shown(self, state):
        for box in self.retain_boxes:
            if box.Visibility == Visibility.Visible:
                box.IsChecked = state
        self.count_retained()

    def count_retained(self):
        ticked = len([b for b in self.retain_boxes if b.IsChecked])
        self.find(u"RetainCount").Text = u"{0} of {1} ticked".format(
            ticked, len(self.retain_boxes))

    def apply(self):
        find = self.find
        s = self.settings
        s[u"group_by"] = picked(find(u"CmbGroupBy"), self.group_by)
        if self.group_params:
            s[u"group_param"] = picked(find(u"CmbGroupParam"), self.group_params)
        s[u"system_from"] = picked(find(u"CmbSystemFrom"), self.system_from)
        s[u"scope"] = picked(find(u"CmbSScope"), SCOPES)
        s[u"isolate_what"] = picked(find(u"CmbIsolateWhat"), ISOLATE)
        s[u"theme"] = picked(find(u"CmbTheme"), THEMES)
        s[u"show_results"] = picked(find(u"CmbResults"), RESULTS)
        s[u"lookup_linked"] = core.from_bool(find(u"ChkLinked").IsChecked)
        s[u"fitting_mode"] = picked(find(u"CmbFittingMode"), core.FITTING_MODES)
        s[u"accessory_params"] = u", ".join(core.split_list(find(u"TxtAccessoryParams").Text))
        s[u"allow_disconnect"] = core.from_bool(find(u"ChkDisconnect").IsChecked)
        s[u"split_system"] = core.from_bool(find(u"ChkSSystem").IsChecked)
        s[u"split_type"] = core.from_bool(find(u"ChkSType").IsChecked)
        s[u"split_size"] = core.from_bool(find(u"ChkSSize").IsChecked)
        s[u"isolate_zoom"] = core.from_bool(find(u"ChkZoom").IsChecked)
        s[u"isolate_section_box"] = core.from_bool(find(u"ChkSectionBox").IsChecked)
        margin = core.to_float(find(u"TxtMargin").Text, None)
        if margin is None or margin < 0:
            self.set_status(u"The section box margin has to be a number of mm.")
            return
        s[u"section_margin_mm"] = core.format_size(margin)
        s[u"isolate_select"] = core.from_bool(find(u"ChkSelect").IsChecked)
        s[u"swap_fittings"] = core.from_bool(find(u"ChkFittings").IsChecked)
        s[u"keep_size"] = core.from_bool(find(u"ChkKeepSize").IsChecked)
        s[u"retain"] = core.join_list([b.Tag for b in self.retain_boxes if b.IsChecked])
        if not core.save_settings(s):
            self.set_status(u"Could not write the settings file - nothing saved.")
            return
        self.saved = True
        self.window.Close()

    def show(self):
        self.window.ShowDialog()
        return self.saved
