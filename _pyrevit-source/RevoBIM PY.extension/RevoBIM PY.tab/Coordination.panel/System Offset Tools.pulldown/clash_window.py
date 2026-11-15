# -*- coding: utf-8 -*-
# ==========================================================
# RevoBIM Clash Offset - the window
#
# Shows what it worked out before it writes anything: which
# way round each clash, how far, and why. The clearances can
# be changed and everything recalculates; the direction can
# be overruled per clash.
#
# Nothing is written until the button is pressed, which is the
# house rule for anything that decides for itself.
# ==========================================================

import so_clr  # noqa: F401  assembly references first

from System.Windows import Thickness, TextWrapping
from System.Windows.Controls import (
    TextBlock, StackPanel, Border, ComboBox, Orientation)
from System.Windows.Media import SolidColorBrush

import so_core
import so_clash
import so_ui


WAYS = (u'up', u'down', u'left', u'right')


class ClashWindow(object):
    """Returns the list of clashes to act on, or None."""

    def __init__(self, doc, view, services, obstructions, settings):
        self.doc = doc
        self.view = view
        self.services = services
        self.obstructions = obstructions
        self.settings = settings
        self.found = []
        self.overrides = {}
        self.answer = None

        self.theme_setting = so_core.to_text(settings.get('theme', 'revit'))
        self.window, self.applied = so_ui.load_window('ClashOffset.xaml',
                                                      self.theme_setting)
        so_ui.set_version(self.window)
        so_ui.load_icon(self.window)
        so_ui.attach_egg(self.window)
        so_ui.Chrome(self.window)
        so_ui.wire_theme_chip(self.window, self.theme_setting)

        self.find('ClearanceBox').Text = so_core.to_text(
            settings.get('clash_clearance', u'50'))
        self.find('LeadBox').Text = so_core.to_text(
            settings.get('clash_lead', u'100'))

        self._wire()
        self.recalculate()

        if len(services) > 1:
            self.status(u'{0} services move together, parallel and evenly '
                        u'spaced.'.format(len(services)))

    def find(self, name):
        return self.window.FindName(name)

    def status(self, text):
        block = self.find('StatusText')
        if block is not None:
            block.Text = so_core.to_text(text)

    def _wire(self):
        for name in ('ClearanceBox', 'LeadBox'):
            box = self.find(name)
            if box is not None:
                box.LostKeyboardFocus += so_ui.ui_safe(
                    lambda s, a: self.recalculate())

        apply_button = self.find('ApplyButton')
        if apply_button is not None:
            apply_button.Click += so_ui.ui_safe(lambda s, a: self._apply())

        for name in ('CancelButton', 'CloseButton'):
            button = self.find(name)
            if button is not None:
                button.Click += so_ui.ui_safe(lambda s, a: self.window.Close())

    # -- numbers ----------------------------------------------
    def _number(self, name, fallback):
        box = self.find(name)
        try:
            return float(so_core.to_text(box.Text).strip())
        except Exception:
            return fallback

    def recalculate(self):
        clearance = self._number('ClearanceBox', 50.0)
        lead = self._number('LeadBox', 100.0)

        self.found = []
        for index, entry in enumerate(self.obstructions):
            found = so_clash.find_clash(
                self.doc, self.services, entry['points'], self.settings,
                self.view, clearance, lead, entry['kind'],
                self.overrides.get(index), entry.get('solids'))
            found['label'] = entry['label']
            found['index'] = index
            self.found.append(found)

        self._paint()

    # -- the list ---------------------------------------------
    def _line(self, text, key, bold=False, indent=0, size=12.5):
        block = TextBlock()
        block.Text = so_core.to_text(text)
        block.TextWrapping = TextWrapping.Wrap
        block.FontSize = size
        block.Margin = Thickness(indent, 2, 0, 2)
        try:
            brush = self.window.Resources[key]
            if isinstance(brush, SolidColorBrush):
                block.Foreground = brush
        except Exception:
            pass
        if bold:
            from System.Windows import FontWeights
            block.FontWeight = FontWeights.Bold
        return block

    def _paint(self):
        panel = self.find('RowsPanel')
        if panel is None:
            return
        panel.Children.Clear()

        workable = 0
        for found in self.found:
            block = StackPanel()
            ok = found.get('ok')
            block.Children.Add(self._line(found.get('label', u''),
                                          'Green' if ok else 'Red',
                                          bold=True, size=13))
            if ok:
                workable += 1
                block.Children.Add(self._line(so_clash.explain(found),
                                              'BodyText', indent=12))

                row = StackPanel()
                row.Orientation = Orientation.Horizontal
                row.Margin = Thickness(12, 6, 0, 2)
                row.Children.Add(self._line(u'Go', 'MutedText'))

                picker = ComboBox()
                picker.Width = 110
                picker.Margin = Thickness(8, 0, 8, 0)
                available = [w for w in WAYS
                             if found.get('required', {}).get(w) is not None]
                for way in available:
                    picker.Items.Add(way)
                try:
                    picker.SelectedIndex = available.index(found['direction'])
                except Exception:
                    picker.SelectedIndex = 0
                picker.SelectionChanged += so_ui.ui_safe(
                    lambda s, a, spot=found['index'], choices=available:
                    self._override(spot, choices, s))
                row.Children.Add(picker)

                costs = u'  '.join(
                    u'{0} {1:.0f}'.format(way,
                                          found['required'][way])
                    for way in available)
                row.Children.Add(self._line(costs, 'MutedText'))
                block.Children.Add(row)
            else:
                block.Children.Add(self._line(found.get('reason', u''),
                                              'BodyText', indent=12))

            rule = Border()
            rule.Height = 1
            rule.Margin = Thickness(0, 9, 0, 9)
            try:
                rule.Background = self.window.Resources['EdgeBrush']
            except Exception:
                pass
            block.Children.Add(rule)
            panel.Children.Add(block)

        button = self.find('ApplyButton')
        if button is not None:
            button.IsEnabled = workable > 0
        bank = u''
        if len(self.services) > 1:
            bank = u' {0} services move together.'.format(len(self.services))
        self.status(u'{0} of {1} can be offset.{2} Nothing is written until '
                    u'you press the button.'
                    .format(workable, len(self.found), bank))

    def _override(self, index, choices, sender):
        try:
            picked = choices[sender.SelectedIndex]
        except Exception:
            return
        if self.overrides.get(index) == picked:
            return
        self.overrides[index] = picked
        self.recalculate()

    # -- apply -------------------------------------------------
    def _apply(self):
        values = dict(self.settings)
        values['clash_clearance'] = so_core.to_text(
            u'{0:g}'.format(self._number('ClearanceBox', 50.0)))
        values['clash_lead'] = so_core.to_text(
            u'{0:g}'.format(self._number('LeadBox', 100.0)))
        so_core.save_settings(values)

        self.answer = [f for f in self.found if f.get('ok')]
        self.window.Close()

    def show(self):
        self.window.ShowDialog()
        return self.answer


def ask(doc, view, services, obstructions, settings):
    return ClashWindow(doc, view, services, obstructions, settings).show()
