# -*- coding: utf-8 -*-
"""RevoBIM PY - Panel Template Mngr: the settings dialog.

Settings are global - which parameter holds the number of ways is a house
standard, not a job by job thing.

Runs on IronPython 2.7 and IronPython 3: no f-strings, no print statements.
"""

import pstm_clr                                                  # noqa: F401
import pstm_core as core
import pstm_ui as ui
import pstm_drawer as drawer_mod
import theme as theme_mod


class SettingsWindow(object):

    def __init__(self, owner, settings, param_names, config_names,
                 type_names=None):
        self.settings = dict(settings)
        self.param_names = list(param_names or [])
        self.config_names = list(config_names or [])
        self.type_names = list(type_names or [])
        self.saved = False
        self.palette = self.settings.get('theme', 'dark')

        self.window = ui.load_window('PstmSettings.xaml', self.palette)
        drawer_mod.adopt(self.window, owner)
        w = self.window
        self.w = w
        self.drawer = drawer_mod.Drawer(w)

        try:
            w.FindName('VersionText').Text = 'v' + core.__version__
        except Exception:
            pass
        ui.set_image(w.FindName('ToolIcon'), 'icon.png')
        ui.wire_drag(w, w.FindName('HeaderBar'), self.drawer)

        w.FindName('CloseButton').Click += self._cancel
        w.FindName('CancelButton').Click += self._cancel
        w.FindName('SaveButton').Click += self._save
        w.FindName('DefaultsButton').Click += self._defaults

        self._fill()

        w.FindName('WaysSearch').TextChanged += self._filter_ways
        w.FindName('PhasesSearch').TextChanged += self._filter_phases
        w.FindName('ThemeCombo').SelectionChanged += self._theme_changed
        for name in ('RuleLargest', 'RuleFirst', 'RuleKeyword'):
            w.FindName(name).Checked += self._preview
        w.FindName('KeywordBox').TextChanged += self._preview
        self._preview(None, None)

    # -- filling ----------------------------------------------------------
    def _fill(self):
        w = self.w
        s = self.settings

        self._fill_combo('WaysCombo', self.param_names, s.get('ways_param', ''))
        self._fill_combo('PhasesCombo', self.param_names, s.get('phases_param', ''))

        configs = ['(All)'] + [self._pretty(c) for c in self.config_names]
        want = s.get('default_config', 'OneColumn')
        self._fill_combo('DefaultConfigCombo', configs,
                         '(All)' if want == 'All' else self._pretty(want))

        types = ['(All types)'] + list(self.type_names)
        self._fill_combo('DefaultTypeCombo', types,
                         s.get('default_schedule_type', 'Branch Panel'))

        self._fill_combo('ThemeCombo', ['Dark', 'Light'],
                         'Light' if s.get('theme') == 'light' else 'Dark')

        name_rule = (s.get('name_number_rule') or 'largest').lower()
        w.FindName('RuleLargest').IsChecked = (name_rule == 'largest')
        w.FindName('RuleFirst').IsChecked = (name_rule == 'first')
        w.FindName('RuleKeyword').IsChecked = (name_rule == 'keyword')
        w.FindName('KeywordBox').Text = s.get('name_number_keyword', 'way')

        w.FindName('PhasesFallbackBox').Text = s.get('phases_fallback', '3')
        w.FindName('SlotStepBox').Text = s.get('slot_step', '3')
        w.FindName('SlotMinBox').Text = s.get('slot_min', '3')
        w.FindName('SlotMaxBox').Text = s.get('slot_max', '120')
        w.FindName('MatchTypeCheck').IsChecked = core.as_bool(
            s.get('match_schedule_type'), True)
        w.FindName('ConfirmApplyCheck').IsChecked = core.as_bool(
            s.get('confirm_apply'), True)
        w.FindName('RebuildScheduleCheck').IsChecked = core.as_bool(
            s.get('rebuild_schedule'), True)

    def _fill_combo(self, name, items, selected):
        combo = self.w.FindName(name)
        combo.Items.Clear()
        for item in items:
            combo.Items.Add(item)
        if selected and selected in items:
            combo.SelectedItem = selected
        elif items:
            combo.SelectedIndex = 0
        return combo

    @staticmethod
    def _pretty(name):
        out = []
        text = str(name or '')
        for i, ch in enumerate(text):
            if i and ch.isupper() and not text[i - 1].isupper():
                out.append(' ')
            out.append(ch)
        return ''.join(out)

    def _unpretty(self, pretty):
        if pretty == '(All)':
            return 'All'
        for name in self.config_names:
            if self._pretty(name) == pretty:
                return name
        return str(pretty or '').replace(' ', '')

    # -- events -----------------------------------------------------------
    def _filter(self, search_name, combo_name):
        text = (self.w.FindName(search_name).Text or '').strip().lower()
        combo = self.w.FindName(combo_name)
        keep = combo.SelectedItem
        combo.Items.Clear()
        for item in self.param_names:
            if not text or text in item.lower():
                combo.Items.Add(item)
        if keep is not None and keep in list(combo.Items):
            combo.SelectedItem = keep
        elif combo.Items.Count:
            combo.SelectedIndex = 0

    def _filter_ways(self, sender, args):
        self._filter('WaysSearch', 'WaysCombo')

    def _filter_phases(self, sender, args):
        self._filter('PhasesSearch', 'PhasesCombo')

    def _theme_changed(self, sender, args):
        try:
            choice = str(self.w.FindName('ThemeCombo').SelectedItem or 'Dark').lower()
            self.palette = 'light' if choice == 'light' else 'dark'
            theme_mod.apply(self.window, self.palette)
        except Exception:
            pass

    def _preview(self, sender, args):
        try:
            rule = self._name_rule()
            keyword = self.w.FindName('KeywordBox').Text or 'way'
            sample = 'BGL_Panel Schedule 36 Way TPN Rev 2'
            found = core.extract_template_number(sample, rule, keyword)
            self.w.FindName('NameRulePreview').Text = \
                '"{0}" reads as {1}'.format(sample,
                                            found if found is not None else 'no number')
        except Exception:
            pass

    def _name_rule(self):
        if self.w.FindName('RuleFirst').IsChecked:
            return 'first'
        if self.w.FindName('RuleKeyword').IsChecked:
            return 'keyword'
        return 'largest'

    def _defaults(self, sender, args):
        self.settings = dict(core.DEFAULTS)
        self.palette = self.settings['theme']
        theme_mod.apply(self.window, self.palette)
        self._fill()
        self._preview(None, None)

    def _collect(self):
        w = self.w
        s = dict(self.settings)
        # an empty combo means the search box has filtered everything out, not
        # that the user cleared the setting
        ways = str(w.FindName('WaysCombo').SelectedItem or '')
        phases = str(w.FindName('PhasesCombo').SelectedItem or '')
        s['ways_param'] = ways or self.settings.get('ways_param', '')
        s['phases_param'] = phases or self.settings.get('phases_param', '')
        s['default_schedule_type'] = str(
            w.FindName('DefaultTypeCombo').SelectedItem or 'Branch Panel')
        s['phases_fallback'] = (w.FindName('PhasesFallbackBox').Text or '').strip()
        s['name_number_rule'] = self._name_rule()
        s['name_number_keyword'] = (w.FindName('KeywordBox').Text or 'way').strip()
        s['default_config'] = self._unpretty(
            str(w.FindName('DefaultConfigCombo').SelectedItem or 'OneColumn'))
        s['theme'] = self.palette
        s['slot_step'] = str(core.as_int(w.FindName('SlotStepBox').Text, 3) or 3)
        s['slot_min'] = str(core.as_int(w.FindName('SlotMinBox').Text, 3) or 3)
        s['slot_max'] = str(core.as_int(w.FindName('SlotMaxBox').Text, 120) or 120)
        s['match_schedule_type'] = '1' if w.FindName('MatchTypeCheck').IsChecked else '0'
        s['confirm_apply'] = '1' if w.FindName('ConfirmApplyCheck').IsChecked else '0'
        s['rebuild_schedule'] = \
            '1' if w.FindName('RebuildScheduleCheck').IsChecked else '0'
        return s

    def _save(self, sender, args):
        self.settings = self._collect()
        core.save_settings(self.settings)
        self.saved = True
        try:
            self.window.DialogResult = True
        except Exception:
            self.window.Close()

    def _cancel(self, sender, args):
        self.saved = False
        try:
            self.window.DialogResult = False
        except Exception:
            self.window.Close()

    def show(self):
        try:
            self.window.ShowDialog()
        except Exception:
            pass
        return self.saved, self.settings
