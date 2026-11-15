# -*- coding: utf-8 -*-
u"""RevoBIM PY - Isolate Service Type : the settings window."""

import ist_clr  # noqa: F401

from System.Windows import FrameworkElement
from System.Windows.Controls import CheckBox

import ist_core
import ist_theme
import ist_ui

RESULT_CHOICES = [
    (u"needed", u"only if something needs a look"),
    (u"always", u"always"),
    (u"never", u"never"),
]


class SettingsWindow(object):

    def __init__(self, uiapp, doc):
        self.uiapp = uiapp
        self.doc = doc
        self.values = ist_core.load_settings()
        self.theme = (self.values.get(u"theme") or u"dark").strip().lower()
        self.open_shortcuts = False

        self.window = ist_ui.load_window(u"IstSettings.xaml", self.theme)
        ist_ui.wire_chrome(self.window)
        ist_ui.owned_by_revit(self.window)

        self.find = self.window.FindName
        self.combos = {}
        self.filters = {}
        self.all_names = {}
        self.ticks = {}

        self._build_params()
        self._build_categories()
        self._build_behaviour()
        self._wire()

    # -- building ----------------------------------------------------------
    def _build_params(self):
        pairs = [
            (u"tray", u"TrayCombo", u"TrayFilter"),
            (u"conduit", u"ConduitCombo", u"ConduitFilter"),
            (u"duct", u"DuctCombo", u"DuctFilter"),
            (u"pipe", u"PipeCombo", u"PipeFilter"),
        ]
        for group, combo_name, filter_name in pairs:
            combo = self.find(combo_name)
            box = self.find(filter_name)
            self.combos[group] = combo
            self.filters[group] = box

            names = ist_core.parameter_names_for(
                self.doc, ist_core.GROUP_CHOICES.get(group, []))
            current = ist_core.param_of(self.values, group)
            if current not in names:
                names = sorted(names + [current], key=lambda s: s.lower())
            self.all_names[group] = names
            self._fill_combo(group, u"")

            if box is not None:
                box.TextChanged += self._filter_handler(group)

    def _fill_combo(self, group, needle):
        combo = self.combos.get(group)
        if combo is None:
            return
        current = combo.SelectedItem
        if current is None:
            current = ist_core.param_of(self.values, group)
        names = self.all_names.get(group, [])
        needle = (needle or u"").strip().lower()
        if needle:
            shown = [n for n in names if needle in n.lower()]
            # A search that matches nothing says so and leaves the full list
            # rather than emptying the dropdown.
            if not shown:
                shown = names
                self._status(u'Nothing matches "{0}".'.format(needle))
            else:
                self._status(u"")
        else:
            shown = names
        combo.Items.Clear()
        for name in shown:
            combo.Items.Add(name)
        if current in shown:
            combo.SelectedItem = current
        elif shown:
            combo.SelectedIndex = 0

    def _filter_handler(self, group):
        def handler(sender, args):
            try:
                self._fill_combo(group, sender.Text)
            except Exception:
                pass
        return handler

    def _build_categories(self):
        holders = {
            u"tray": u"CatsTray",
            u"conduit": u"CatsConduit",
            u"duct": u"CatsDuct",
            u"pipe": u"CatsPipe",
        }
        for group, holder_name in holders.items():
            holder = self.find(holder_name)
            if holder is None:
                continue
            picked = ist_core.cats_of(self.values, group)
            self.ticks[group] = []
            for cat_name in ist_core.GROUP_CHOICES.get(group, []):
                box = CheckBox()
                box.Content = ist_core.LABEL_OF.get(cat_name, cat_name)
                box.IsChecked = cat_name in picked
                box.Tag = cat_name
                try:
                    box.SetResourceReference(
                        FrameworkElement.StyleProperty, u"IstCheck")
                except Exception:
                    pass
                holder.Children.Add(box)
                self.ticks[group].append(box)

    def _build_behaviour(self):
        blank = (self.values.get(u"blank_value") or u"skip").strip().lower()
        self._set_checked(u"BlankGroup", blank == u"group")
        self._set_checked(u"BlankBlank", blank == u"blank")
        self._set_checked(u"BlankSkip", blank == u"skip")

        other = (self.values.get(u"other_scope") or u"category").strip().lower()
        self._set_checked(u"OtherCategory", other == u"category")
        self._set_checked(u"OtherFamily", other == u"family")
        self._set_checked(u"OtherType", other == u"type")
        self._set_checked(u"OtherIgnore", other == u"ignore")

        self._set_checked(u"FallbackBuiltin",
                          ist_core.is_on(self.values, u"fallback_builtin"))
        nothing = (self.values.get(u"nothing_selected") or u"pick")\
            .strip().lower()
        self._set_checked(u"NothingPick", nothing != u"reset")
        self._set_checked(u"NothingReset", nothing == u"reset")
        self._set_checked(u"HideBrowse",
                          ist_core.is_on(self.values, u"hide_browse"))
        run_how = (self.values.get(u"template_run") or u"apply")\
            .strip().lower()
        self._set_checked(u"TemplateApply", run_how != u"list")
        self._set_checked(u"TemplateList", run_how == u"list")
        self._set_checked(u"HideReplaces",
                          ist_core.is_on(self.values, u"hide_replaces"))

        self._set_checked(u"MatchCase", ist_core.is_on(self.values, u"match_case"))
        self._set_checked(u"IncludeInsulation",
                          ist_core.is_on(self.values, u"include_insulation"))
        self._set_checked(u"IncludeSelection",
                          ist_core.is_on(self.values, u"include_selection"))
        self._set_checked(u"EmptyResets",
                          ist_core.is_on(self.values, u"empty_selection_resets"))
        self._set_checked(u"HideUncaptured",
                          ist_core.is_on(self.values, u"hide_uncaptured"))

        mode = ist_core.hide_mode_of(self.values)
        self._set_checked(u"HideMemory", mode == u"memory")
        self._set_checked(u"HideTemporary", mode == u"temporary")
        self._set_checked(u"HidePermanent", mode == u"permanent")

        combo = self.find(u"ResultsCombo")
        if combo is not None:
            combo.Items.Clear()
            for _key, label in RESULT_CHOICES:
                combo.Items.Add(label)
            wanted = (self.values.get(u"show_results") or u"needed").strip().lower()
            index = 0
            for position, pair in enumerate(RESULT_CHOICES):
                if pair[0] == wanted:
                    index = position
            combo.SelectedIndex = index

        chip = self.find(u"ThemeChip")
        if chip is not None:
            chip.Content = u"Light" if self.theme == u"dark" else u"Dark"

    def _set_checked(self, name, state):
        control = self.find(name)
        if control is not None:
            control.IsChecked = bool(state)

    def _is_checked(self, name):
        control = self.find(name)
        if control is None:
            return False
        return bool(control.IsChecked)

    def _status(self, text):
        label = self.find(u"StatusText")
        if label is not None:
            label.Text = text

    # -- wiring ------------------------------------------------------------
    def _wire(self):
        apply_button = self.find(u"ApplyButton")
        if apply_button is not None:
            apply_button.Click += self._apply

        cancel = self.find(u"CancelButton")
        if cancel is not None:
            cancel.Click += self._cancel

        chip = self.find(u"ThemeChip")
        if chip is not None:
            chip.Click += self._toggle_theme

        shortcut = self.find(u"ShortcutButton")
        if shortcut is not None:
            shortcut.Click += self._shortcuts

    def _toggle_theme(self, sender, args):
        self.theme = u"light" if self.theme == u"dark" else u"dark"
        ist_theme.apply(self.window, self.theme)
        try:
            sender.Content = u"Light" if self.theme == u"dark" else u"Dark"
        except Exception:
            pass

    def _cancel(self, sender, args):
        try:
            self.window.Close()
        except Exception:
            pass

    def _shortcuts(self, sender, args):
        self.open_shortcuts = True
        try:
            self.window.Close()
        except Exception:
            pass

    def _apply(self, sender, args):
        values = dict(self.values)

        for group in ist_core.GROUP_KEYS:
            combo = self.combos.get(group)
            if combo is not None and combo.SelectedItem is not None:
                values[u"param_" + group] = u"{0}".format(combo.SelectedItem)
            picked = []
            for box in self.ticks.get(group, []):
                if box.IsChecked:
                    picked.append(u"{0}".format(box.Tag))
            values[u"cats_" + group] = u",".join(picked)

        if self._is_checked(u"BlankBlank"):
            values[u"blank_value"] = u"blank"
        elif self._is_checked(u"BlankGroup"):
            values[u"blank_value"] = u"group"
        else:
            values[u"blank_value"] = u"skip"

        values[u"fallback_builtin"] = (
            u"on" if self._is_checked(u"FallbackBuiltin") else u"off")
        values[u"nothing_selected"] = (
            u"reset" if self._is_checked(u"NothingReset") else u"pick")
        values[u"hide_browse"] = (
            u"on" if self._is_checked(u"HideBrowse") else u"off")
        values[u"template_run"] = (
            u"list" if self._is_checked(u"TemplateList") else u"apply")
        values[u"hide_replaces"] = (
            u"on" if self._is_checked(u"HideReplaces") else u"off")

        if self._is_checked(u"OtherFamily"):
            values[u"other_scope"] = u"family"
        elif self._is_checked(u"OtherType"):
            values[u"other_scope"] = u"type"
        elif self._is_checked(u"OtherIgnore"):
            values[u"other_scope"] = u"ignore"
        else:
            values[u"other_scope"] = u"category"

        values[u"match_case"] = u"on" if self._is_checked(u"MatchCase") else u"off"
        values[u"include_insulation"] = (
            u"on" if self._is_checked(u"IncludeInsulation") else u"off")
        values[u"include_selection"] = (
            u"on" if self._is_checked(u"IncludeSelection") else u"off")
        values[u"empty_selection_resets"] = (
            u"on" if self._is_checked(u"EmptyResets") else u"off")
        values[u"hide_uncaptured"] = (
            u"on" if self._is_checked(u"HideUncaptured") else u"off")
        if self._is_checked(u"HidePermanent"):
            values[u"hide_mode"] = u"permanent"
        elif self._is_checked(u"HideTemporary"):
            values[u"hide_mode"] = u"temporary"
        else:
            values[u"hide_mode"] = u"memory"

        combo = self.find(u"ResultsCombo")
        if combo is not None and combo.SelectedIndex >= 0:
            values[u"show_results"] = RESULT_CHOICES[combo.SelectedIndex][0]

        values[u"theme"] = self.theme

        if ist_core.save_settings(values):
            try:
                self.window.Close()
            except Exception:
                pass
        else:
            self._status(u"Could not write {0}".format(ist_core.SETTINGS_PATH))

    def show(self):
        self.window.ShowDialog()
        return self.open_shortcuts
