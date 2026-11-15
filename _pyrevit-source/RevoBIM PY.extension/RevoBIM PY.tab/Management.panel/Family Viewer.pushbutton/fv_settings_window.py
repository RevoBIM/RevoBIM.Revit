# -*- coding: utf-8 -*-
"""Family Viewer - the settings dialog.

Modal, two columns so it fits without scrolling.  Settings persist as plain
key=value text under %APPDATA%\\RevoBIM\\, not JSON: no dependency on a module
whose availability varies with the IronPython engine, and it stays readable and
hand editable.
"""

import fv_clr  # noqa: F401  - must be first

from System.Windows.Controls import ComboBoxItem

import re

import fv_core
import fv_ui
import theme
from fv_core import as_bool, as_int

THEMES = [('follow', "Follow Revit's canvas"), ('dark', 'Dark'),
          ('light', 'Light')]
PREVIEW_ON = [('family', 'Family rows'),
              ('type', 'Type rows'),
              ('both', 'Both')]
SCOPES = [('project', 'The entire project'),
          ('view', 'The active view'),
          ('all', 'All families (not placed)')]
PHASE_MODES = [('created', 'What was created in the phase'),
               ('existing', 'What stands in the phase')]
OPEN_IN = [('pane', "Revit's own dockable pane"),
           ('window', 'A floating window')]
RESULTS = [('auto', 'Only when something needs a look'),
           ('always', 'Always'),
           ('never', 'Never')]


def _is_hex(text):
    """#RGB, #RRGGBB or #AARRGGBB."""
    return bool(re.match(r'^#([0-9A-Fa-f]{3}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$',
                         text or ''))


def _fill(combo, pairs, current):
    combo.Items.Clear()
    chosen = 0
    for index, pair in enumerate(pairs):
        value, label = pair
        item = ComboBoxItem()
        item.Content = label
        item.Tag = value
        combo.Items.Add(item)
        if str(value) == str(current):
            chosen = index
    combo.SelectedIndex = chosen


def _picked(combo, fallback):
    item = combo.SelectedItem
    if item is None:
        return fallback
    try:
        return str(item.Tag)
    except Exception:
        return fallback


def _numbers(values):
    return [(str(value), str(value)) for value in values]


def open_settings(owner, settings, phases, palette_name):
    """Returns True where Apply was pressed and the settings were written."""
    window = fv_ui.load_window('FamilyViewerSettings.xaml', palette_name)
    find = window.FindName

    find('SettingsVersion').Text = 'v' + fv_core.__version__
    find('SetPath').Text = fv_core.settings_path()

    _fill(find('SetTheme'), THEMES, settings.get('theme', theme.FOLLOW))
    _fill(find('SetUiScale'), _numbers(fv_core.UI_SCALES),
          as_int(settings, 'ui_scale', 80, 150))
    _fill(find('SetPreviewSize'), _numbers(fv_core.PREVIEW_SIZES),
          as_int(settings, 'preview_size', 16, 256))
    _fill(find('SetPreviewOn'), PREVIEW_ON, settings.get('preview_on', 'family'))
    _fill(find('SetScope'), SCOPES, settings.get('default_scope', 'project'))
    _fill(find('SetPhaseMode'), PHASE_MODES, settings.get('phase_mode', 'created'))
    _fill(find('SetShowResults'), RESULTS, settings.get('show_results', 'auto'))
    _fill(find('SetOpenIn'), OPEN_IN, settings.get('open_in', 'pane'))

    phase_pairs = [('', '(every phase)')]
    for entry in phases or []:
        phase_pairs.append((entry['name'], entry['name']))
    _fill(find('SetPhase'), phase_pairs, settings.get('default_phase', ''))

    checks = [
        ('SetShowPreviews', 'show_previews'),
        ('SetIncludeSystem', 'include_system'),
        ('SetIncludeAnnotation', 'include_annotation'),
        ('SetIgnoreNested', 'ignore_nested'),
        ('SetFamiliesOpen', 'families_open'),
        ('SetWatch', 'watch_model'),
        ('SetZoom', 'zoom_after_select'),
        ('SetFollow', 'follow_revit'),
        ('SetSnap', 'snap_on_drag'),
    ]
    for name, key in checks:
        find(name).IsChecked = as_bool(settings, key)

    boxes = [
        ('SetFamilySize', 'family_row_size'),
        ('SetMaxRows', 'max_rows'),
        ('SetMaxInstances', 'max_instances'),
        ('SetSettle', 'settle_ms'),
        ('SetDockWidth', 'dock_width'),
        ('SetDockInset', 'dock_top_inset'),
    ]
    for name, key in boxes:
        find(name).Text = str(settings.get(key, fv_core.DEFAULTS.get(key, '')))
    find('SetFamilyShade').Text = settings.get('family_row_shade', '')

    answer = {'applied': False}

    def read_back():
        settings['theme'] = _picked(find('SetTheme'), theme.FOLLOW)
        settings['ui_scale'] = _picked(find('SetUiScale'), '100')
        settings['preview_size'] = _picked(find('SetPreviewSize'), '48')
        settings['preview_on'] = _picked(find('SetPreviewOn'), 'family')
        settings['default_scope'] = _picked(find('SetScope'), 'project')
        settings['phase_mode'] = _picked(find('SetPhaseMode'), 'created')
        settings['show_results'] = _picked(find('SetShowResults'), 'auto')
        settings['open_in'] = _picked(find('SetOpenIn'), 'pane')
        settings['default_phase'] = _picked(find('SetPhase'), '')
        # a colour that will not parse is refused rather than saved and then
        # quietly ignored every time the grid draws
        shade = (find('SetFamilyShade').Text or '').strip()
        if shade and not _is_hex(shade):
            shade = ''
            find('SetFamilyShade').Text = ''
        settings['family_row_shade'] = shade
        for name, key in checks:
            settings[key] = '1' if find(name).IsChecked else '0'
        # a typo shows up straight away rather than silently doing nothing:
        # anything that will not parse goes back to the default
        for name, key in boxes:
            raw = (find(name).Text or '').strip()
            try:
                settings[key] = str(int(raw))
            except Exception:
                settings[key] = fv_core.DEFAULTS.get(key, '0')
                find(name).Text = settings[key]

    def on_apply(sender, args):
        read_back()
        fv_core.save_settings(settings)
        answer['applied'] = True
        window.DialogResult = True

    def on_cancel(sender, args):
        window.DialogResult = False

    def on_reset(sender, args):
        ok = fv_ui.prompt(
            window, palette_name, 'Reset every setting?',
            'Every Family Viewer setting goes back to its default. The '
            'parameter columns you have added are kept.',
            'Reset', 'Cancel', accent='orange')
        if not ok:
            return
        keep = settings.get('columns', '')
        for key in fv_core.DEFAULTS:
            settings[key] = fv_core.DEFAULTS[key]
        settings['columns'] = keep
        fv_core.save_settings(settings)
        answer['applied'] = True
        window.DialogResult = True

    def on_drag(sender, args):
        try:
            window.DragMove()
        except Exception:
            pass

    def on_theme_pick(sender, args):
        try:
            fv_ui.set_theme(window, theme.resolve(
                _picked(find('SetTheme'), theme.FOLLOW), theme.revit_canvas()))
        except Exception:
            pass

    find('SetApply').Click += on_apply
    find('SetCancel').Click += on_cancel
    find('SetClose').Click += on_cancel
    find('SetReset').Click += on_reset
    find('SetHeader').MouseLeftButtonDown += on_drag
    find('SetTheme').SelectionChanged += on_theme_pick

    fv_ui.WindowDrawer(window, find('SetHeader'), find('SetRoot'),
                       find('SetShrink'), owner=owner)
    fv_ui.own_dialog(window, owner)
    try:
        window.ShowDialog()
    except Exception:
        fv_core.log('settings window failed:\n' + fv_core.format_exc())
        return False
    return answer['applied']
