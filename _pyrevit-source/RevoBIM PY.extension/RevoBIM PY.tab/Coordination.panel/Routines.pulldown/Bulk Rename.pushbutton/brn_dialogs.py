# -*- coding: utf-8 -*-
"""The themed prompt: nothing selected, unapplied changes, what went wrong."""
import brn_clr  # noqa: F401  must stay first
from brn_chrome import ThemedWindow

import brn_core as core

from System.Windows import Visibility, WindowStartupLocation


class Prompt(ThemedWindow):
    LAYOUT = 'Prompt.xaml'

    def __init__(self, uiapp, settings, log, message, title=u'Bulk Rename',
                 detail=None, yes=None, no=None, owner=None):
        ThemedWindow.__init__(self, uiapp, settings, log, owner)
        self.answer = False
        find = self.window.FindName
        find('PromptTitle').Text = title
        find('Message').Text = message
        if detail:
            find('Detail').Text = detail
            find('DetailBox').Visibility = Visibility.Visible
        find('YesText').Text = yes or u'OK'
        no_btn = find('NoBtn')
        if no:
            find('NoText').Text = no
            no_btn.Click += self.safe(lambda s, a: self.window.Close())
        else:
            no_btn.Visibility = Visibility.Collapsed
        find('YesBtn').Click += self.safe(self.on_yes)
        if owner is not None:
            if owner.drawer.parked:
                self.window.WindowStartupLocation = WindowStartupLocation.CenterScreen
            else:
                self.window.Owner = owner.window
        else:
            self.window.WindowStartupLocation = WindowStartupLocation.CenterScreen
            self.own_to_revit()

    def on_yes(self, sender, args):
        self.answer = True
        self.window.Close()

    def run(self):
        self.window.ShowDialog()
        return self.answer


class SettingsWindow(ThemedWindow):
    LAYOUT = 'Settings.xaml'
    NONE = u'(none)'

    def __init__(self, uiapp, settings, log, owner, parameters, sample):
        ThemedWindow.__init__(self, uiapp, settings, log, owner)
        find = self.window.FindName
        find('PromptTitle').Text = u'Settings'
        self.sample = sample
        self.saved = False
        self.example = find('Example')
        self.delimiter = find('DelimiterBox')
        self.delimiter.Text = settings.get('sheet_delimiter', '')
        self.combos = []
        for index, key in enumerate(core.PARAM_KEYS):
            combo = find('Param{0}'.format(index + 1))
            current = core.to_text(settings.get(key, ''))
            combo.Items.Add(self.NONE)
            names = list(parameters)
            if current and current not in names:
                names.insert(0, current)
            for name in names:
                combo.Items.Add(name)
            combo.SelectedItem = current or self.NONE
            combo.SelectionChanged += self.safe(self.on_changed)
            self.combos.append((key, combo))
        self.delimiter.TextChanged += self.safe(self.on_changed)
        find('SaveBtn').Click += self.safe(self.on_save)
        find('CancelBtn').Click += self.safe(lambda s, a: self.window.Close())
        self.on_changed(None, None)
        if owner.drawer.parked:
            self.window.WindowStartupLocation = WindowStartupLocation.CenterScreen
        else:
            self.window.Owner = owner.window

    def picked(self):
        out = {'sheet_delimiter': core.to_text(self.delimiter.Text)}
        for key, combo in self.combos:
            value = core.to_text(combo.SelectedItem)
            out[key] = u'' if value == self.NONE else value
        return out

    def on_changed(self, sender, args):
        lines = [u'{0}:  {1}'.format(p, v or u'(blank)')
                 for p, v in core.sheet_writes(self.sample, self.picked())]
        self.example.Text = u'\n'.join([self.sample] + lines)

    def on_save(self, sender, args):
        self.settings.update(self.picked())
        core.save_settings(self.settings)
        self.saved = True
        self.window.Close()

    def run(self):
        self.window.ShowDialog()
        return self.saved


def tell(uiapp, settings, log, message, title=u'Bulk Rename', detail=None,
         owner=None):
    Prompt(uiapp, settings, log, message, title, detail, owner=owner).run()


def ask(uiapp, settings, log, message, yes, no, owner=None):
    return Prompt(uiapp, settings, log, message, yes=yes, no=no, owner=owner).run()
