# -*- coding: utf-8 -*-
# ==========================================================
# RevoBIM System Offset - the settings window
#
# Two settings: how far to offset, and at what angle.
# Everything else the tool needs is a constant in so_core -
# a setting nobody changes is only another way to get it
# wrong. The direction is answered per offset at the prompt,
# so it is not a setting at all any more.
#
# Written to %APPDATA%\RevoBIM\system_offset.txt.
# ==========================================================

import so_clr  # noqa: F401  assembly references first

import so_core
import so_ui


ANGLE_CHOICES = (
    (u'22.5', u'22.5 degrees'),
    (u'30',   u'30 degrees'),
    (u'45',   u'45 degrees'),
    (u'60',   u'60 degrees'),
    (u'90',   u'90 degrees, a square offset'),
)


def fill_combo(combo, choices, value):
    if combo is None:
        return
    combo.Items.Clear()
    wanted = 0
    for index, pair in enumerate(choices):
        stored, label = pair
        combo.Items.Add(label)
        if stored == so_core.to_text(value).strip().lower():
            wanted = index
    combo.SelectedIndex = wanted


def read_combo(combo, choices, fallback):
    try:
        index = combo.SelectedIndex
        if index is None or index < 0 or index >= len(choices):
            return fallback
        return choices[index][0]
    except Exception:
        return fallback


class SettingsWindow(object):

    def __init__(self):
        self.settings = so_core.load_settings()
        self.theme_setting = so_core.to_text(self.settings.get('theme', 'revit'))
        self.window, self.applied = so_ui.load_window(
            'SystemOffsetSettings.xaml', self.theme_setting)
        self.saved = False

        so_ui.set_version(self.window)
        so_ui.load_icon(self.window)
        so_ui.attach_egg(self.window)
        so_ui.Chrome(self.window)
        so_ui.wire_theme_chip(self.window, self.theme_setting,
                              self._theme_changed)

        self._load_into_controls()
        self._wire()

    def find(self, name):
        return self.window.FindName(name)

    def _theme_changed(self, setting):
        self.theme_setting = setting
        self.status(u'Theme set. Press Apply to keep it.')

    def status(self, text):
        block = self.find('StatusText')
        if block is not None:
            block.Text = so_core.to_text(text)

    # -- load -------------------------------------------------
    def _load_into_controls(self):
        box = self.find('WidthFactorBox')
        if box is not None:
            box.Text = so_core.to_text(self.settings.get('width_factor'))

        fill_combo(self.find('AngleCombo'), ANGLE_CHOICES,
                   self.settings.get('angle'))

        note = self.find('DistanceNote')
        if note is not None:
            note.Text = (u'The prompt opens with this, rounded up to {0:.0f}mm '
                         u'and never under {1:.0f}mm, and lets it be changed '
                         u'for that one offset.'
                         .format(so_core.ROUND_MM, so_core.MIN_OFFSET_MM))

        angle_note = self.find('AngleNote')
        if angle_note is not None:
            angle_note.Text = (u'Each bend eats offset / tan(angle) of the run, '
                               u'so a 45 degree offset needs the two clicks at '
                               u'least twice the offset apart. 90 degrees needs '
                               u'almost nothing.')

        self.status(so_core.settings_path())

    # -- wiring -----------------------------------------------
    def _wire(self):
        apply_button = self.find('ApplyButton')
        if apply_button is not None:
            apply_button.Click += so_ui.ui_safe(lambda s, a: self._apply())

        cancel = self.find('CancelButton')
        if cancel is not None:
            cancel.Click += so_ui.ui_safe(lambda s, a: self.window.Close())

        shortcut = self.find('ShortcutButton')
        if shortcut is not None:
            shortcut.Click += so_ui.ui_safe(lambda s, a: self._open_shortcuts())

    # -- Revit's own shortcut dialog ---------------------------
    def _open_shortcuts(self):
        """PostCommand launches Revit's Keyboard Shortcuts dialog.

        CanPostCommand is never used as a gate - it reports on
        the command, not on whether posting will work.
        """
        try:
            from Autodesk.Revit.UI import (
                RevitCommandId, PostableCommand, TaskDialog)
            import so_command_host
            uiapp = so_command_host.current_uiapp()
            command_id = RevitCommandId.LookupPostableCommandId(
                PostableCommand.KeyboardShortcuts)
            if uiapp is not None and command_id is not None:
                uiapp.PostCommand(command_id)
                self.status(u'Search for "RevoBIM System Offset". Close this '
                            u'window for the dialog to appear.')
                return
            TaskDialog.Show(
                u'RevoBIM System Offset',
                u'Open View > User Interface > Keyboard Shortcuts and search '
                u'for "RevoBIM System Offset".')
        except Exception:
            self.status(u'Open View > User Interface > Keyboard Shortcuts and '
                        u'search for "RevoBIM System Offset".')

    # -- apply -------------------------------------------------
    def _apply(self):
        values = dict(self.settings)
        values['angle'] = read_combo(self.find('AngleCombo'),
                                     ANGLE_CHOICES, u'45')
        values['theme'] = self.theme_setting

        box = self.find('WidthFactorBox')
        if box is not None:
            text = so_core.to_text(box.Text).strip()
            try:
                number = float(text)
            except Exception:
                self.status(u'"{0}" is not a number.'.format(text))
                return
            if number < 0.1 or number > 20.0:
                self.status(u'The multiplier has to be between 0.1 and 20.')
                return
            values['width_factor'] = so_core.to_text(text)

        if so_core.save_settings(values):
            self.settings = values
            self.saved = True
            self.status(u'Saved to {0}'.format(so_core.settings_path()))
            self.window.Close()
        else:
            self.status(u'Could not write {0}'.format(so_core.settings_path()))

    def show(self):
        self.window.ShowDialog()
        return self.saved
