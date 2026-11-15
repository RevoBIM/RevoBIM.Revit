# -*- coding: utf-8 -*-
"""RevoBIM PY - Nudge Settings

Sets the increment used by Nudge Up and Nudge Down, and how they behave.

Settings are shared by all three buttons and are kept in
%APPDATA%\\RevoBIM PY\\nudge_settings.json, so they survive a Revit restart
and a pyRevit reload.
"""

__title__ = 'Nudge Settings'
__author__ = 'RevoBIM PY'
__doc__ = ('Set the Nudge increment (default 50 mm) and how Nudge Up and '
           'Nudge Down behave.')

import os

from pyrevit import forms, script

# Visibility lives in PresentationCore. Depending on what has already been
# loaded, that assembly is not always referenced in the IronPython engine by
# the time this script imports, so ask for it explicitly rather than assuming.
# If it still cannot be found the window is fine without it - hiding a spare
# preset chip is the only thing it is used for.
try:
    import clr
    clr.AddReference('PresentationCore')
    clr.AddReference('PresentationFramework')
    clr.AddReference('WindowsBase')
    from System.Windows import Visibility
except Exception:
    Visibility = None

from revobim import nudge_settings
from revobim import revit_shortcuts as ks

COMMANDS = (
    ('ks_up', 'Nudge Up'),
    ('ks_down', 'Nudge Down'),
    ('ks_settings', 'Nudge Settings'),
)

__version__ = nudge_settings.VERSION

logger = script.get_logger()

XAML = os.path.join(os.path.dirname(__file__), 'NudgeSettings.xaml')
ICON = os.path.join(os.path.dirname(__file__), 'icon.png')


class NudgeSettingsWindow(forms.WPFWindow):
    """Dark themed settings window, same palette as the other RevoBIM tools."""

    def __init__(self):
        forms.WPFWindow.__init__(self, XAML)
        self.version_tb.Text = 'v' + __version__
        if os.path.isfile(ICON):
            try:
                self.set_image_source(self.tool_icon, ICON)
            except Exception:
                pass
        self._load()
        self._load_shortcuts()

    # ------------------------------------------------------------ shortcuts

    def _load_shortcuts(self):
        """Read what Revit currently has assigned to the three commands."""
        self.ks_path = None
        self.ks_doc = None
        try:
            self.ks_path = ks.shortcuts_path(__revit__.Application)
            self.ks_doc = ks.load(self.ks_path)
        except Exception as err:
            logger.debug('shortcuts file unreadable: %s', err)

        if self.ks_doc is None:
            self.ks_note.Text = (
                'Revit\'s shortcuts file has not been found. Open Keyboard '
                'Shortcuts (type KS), press OK once to create it, then come '
                'back here.')
            for field, _ in COMMANDS:
                getattr(self, field).IsEnabled = False
            return

        missing = []
        for field, command in COMMANDS:
            item = ks.find(self.ks_doc, command)
            box = getattr(self, field)
            if item is None:
                box.IsEnabled = False
                missing.append(command)
            else:
                box.Text = ks.get_keys(item)

        if missing:
            self.ks_note.Text = (
                'Revit has not registered {0} yet. It only reads the ribbon '
                'at startup, so restart Revit fully - a pyRevit reload is not '
                'enough - then reopen this window.'
                .format(', '.join(missing)))

    def _save_shortcuts(self):
        """Write the three shortcuts. Returns a note, or None if untouched."""
        if self.ks_doc is None:
            return None

        changed = []
        clashed = []
        for field, command in COMMANDS:
            box = getattr(self, field)
            if not box.IsEnabled:
                continue
            item = ks.find(self.ks_doc, command)
            if item is None:
                continue
            wanted = str(box.Text).strip().upper()
            if wanted == ks.get_keys(item):
                continue
            for other in ks.clashes(self.ks_doc, wanted, ignore=item):
                clashed.append(other)
            ks.set_keys(item, wanted)
            changed.append(command)

        if not changed:
            return None

        try:
            ks.save(self.ks_doc, self.ks_path)
        except Exception as err:
            logger.debug('could not write shortcuts: %s', err)
            return 'Settings saved, but the shortcuts file could not be written.'

        note = 'Shortcuts set. Restart Revit for them to take effect.'
        if clashed:
            note += ' Note {0} already uses one of those keys.'.format(
                clashed[0])
        return note

    # ---------------------------------------------------------------- state

    def _load(self):
        cfg = nudge_settings.load()
        self.tb_step.Text = _fmt(cfg['step_mm'])
        self.cb_snap.IsChecked = bool(cfg['snap_enabled'])
        self.tb_snap.Text = _fmt(cfg['snap_mm'] or
                                 nudge_settings.DEFAULTS['snap_mm'])
        self.cb_keep.IsChecked = bool(cfg['keep_selection'])
        self.cb_loop.IsChecked = bool(cfg['repeat_loop'])
        self.cb_fittings.IsChecked = bool(cfg['allow_fittings'])
        self.cb_fab.IsChecked = bool(cfg['allow_fabrication'])
        self.cb_rods.IsChecked = bool(cfg['recut_rods'])

        presets = list(cfg.get('presets') or nudge_settings.DEFAULTS['presets'])
        chips = (self.chip_1, self.chip_2, self.chip_3, self.chip_4)
        for index, chip in enumerate(chips):
            if index < len(presets):
                chip.Content = _fmt(presets[index])
                _show(chip, True)
            else:
                chip.Content = ''
                _show(chip, False)

    def _collect(self):
        try:
            step = float(str(self.tb_step.Text).strip().replace(',', '.'))
        except (TypeError, ValueError):
            return None
        if step <= 0:
            return None

        try:
            snap = float(str(self.tb_snap.Text).strip().replace(',', '.'))
        except (TypeError, ValueError):
            snap = -1.0
        if snap < 0:
            return None

        return {
            'step_mm': step,
            'snap_enabled': bool(self.cb_snap.IsChecked),
            'snap_mm': snap,
            'keep_selection': bool(self.cb_keep.IsChecked),
            'repeat_loop': bool(self.cb_loop.IsChecked),
            'allow_fittings': bool(self.cb_fittings.IsChecked),
            'allow_fabrication': bool(self.cb_fab.IsChecked),
            'recut_rods': bool(self.cb_rods.IsChecked),
        }

    # ------------------------------------------------------------- handlers

    def header_drag(self, sender, args):
        try:
            self.DragMove()
        except Exception:
            pass

    def close_click(self, sender, args):
        self.Close()

    def preset_click(self, sender, args):
        value = str(sender.Content).strip()
        if value:
            self.tb_step.Text = value
            self.status_tb.Text = 'Increment set to {0} mm. Press Save.'.format(
                value)

    def reset_click(self, sender, args):
        defaults = nudge_settings.DEFAULTS
        self.tb_step.Text = _fmt(defaults['step_mm'])
        self.cb_snap.IsChecked = defaults['snap_enabled']
        self.tb_snap.Text = _fmt(defaults['snap_mm'])
        self.cb_keep.IsChecked = defaults['keep_selection']
        self.cb_loop.IsChecked = defaults['repeat_loop']
        self.cb_fittings.IsChecked = defaults['allow_fittings']
        self.cb_fab.IsChecked = defaults['allow_fabrication']
        self.cb_rods.IsChecked = defaults['recut_rods']
        self.status_tb.Text = 'Back to defaults. Press Save to keep them.'

    def save_click(self, sender, args):
        cfg = self._collect()
        if cfg is None:
            self.status_tb.Text = ('The increment must be a positive number '
                                   'and the rounding must not be negative. '
                                   'Try 50 and 5.')
            return
        if not nudge_settings.save(cfg):
            self.status_tb.Text = ('Could not write to {0}.'
                                   .format(nudge_settings.path()))
            return

        logger.debug('Nudge settings saved: %s', cfg)

        note = None
        try:
            note = self._save_shortcuts()
        except Exception as err:
            logger.debug('shortcut write failed: %s', err)
            note = 'Settings saved, but the shortcuts could not be written.'

        if note:
            # leave the window up so the restart message is actually read
            self.status_tb.Text = note
            return
        self.Close()


def _show(control, visible):
    """Show or collapse a control, whether or not Visibility resolved."""
    if Visibility is not None:
        control.Visibility = Visibility.Visible if visible \
            else Visibility.Collapsed
    else:
        # no enum available - fall back to collapsing it by size
        control.IsEnabled = bool(visible)
        control.Opacity = 1.0 if visible else 0.0
        control.Width = float('NaN') if visible else 0.0


def _fmt(value):
    """50.0 -> '50', 12.5 -> '12.5'."""
    number = float(value)
    if abs(number - round(number)) < 1e-9:
        return str(int(round(number)))
    return ('%g' % number)


NudgeSettingsWindow().ShowDialog()
