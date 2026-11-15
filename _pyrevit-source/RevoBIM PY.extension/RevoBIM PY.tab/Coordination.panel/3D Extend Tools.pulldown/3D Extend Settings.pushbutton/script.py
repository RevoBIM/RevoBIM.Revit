# -*- coding: utf-8 -*-
"""Settings for 3D Extend.

Drop angle for cable trays and pipes, whether a tray branch is connected into
the tray system, and the Revit keyboard shortcuts for both buttons.

Apply saves and keeps the window open; Save saves and closes. Whatever is
applied becomes the working setting for every later run until it is changed
and applied again.
"""

__title__ = '3D Extend Settings'
__author__ = 'RevoBIM PY'
__version__ = '4.1.0'

import io
import json
import os
import shutil
import xml.etree.ElementTree as ET

from pyrevit import forms

DEFAULT_TRAY_ANGLE = 90.0
DEFAULT_TRAY_CONNECT = True
DEFAULT_PIPE_ANGLE = 90.0
DEFAULT_DUCT_ANGLE = 90.0
DEFAULT_DUCT_FITTING = 'tap'
DEFAULT_SHOW_REPORT = False

HERE = os.path.dirname(__file__)
XAML_FILE = os.path.join(HERE, 'ExtendConfig.xaml')
ICON_FILE = os.path.join(HERE, 'settings.png')

SETTINGS_DIR = os.path.join(os.getenv('APPDATA') or '', 'RevoBIM PY')
SETTINGS_FILE = os.path.join(SETTINGS_DIR, '3d_extend_settings.json')

TAB_NAME = 'RevoBIM PY'
PANEL_NAME = 'Coordination'
TOOL_BUTTON = '3D Extend'
SETTINGS_BUTTON = '3D Extend Settings'


# --------------------------------------------------------------- settings io
def clamp_angle(value, fallback):
    try:
        number = float(value)
    except Exception:
        return fallback
    if number < 5.0:
        return 5.0
    if number > 90.0:
        return 90.0
    return number


def read_settings():
    data = {}
    try:
        if os.path.isfile(SETTINGS_FILE):
            handle = io.open(SETTINGS_FILE, 'r', encoding='utf-8')
            try:
                data = json.loads(handle.read())
            finally:
                handle.close()
    except Exception:
        data = {}

    return (clamp_angle(data.get('tray_angle', DEFAULT_TRAY_ANGLE),
                        DEFAULT_TRAY_ANGLE),
            bool(data.get('tray_connect', DEFAULT_TRAY_CONNECT)),
            clamp_angle(data.get('pipe_angle', DEFAULT_PIPE_ANGLE),
                        DEFAULT_PIPE_ANGLE),
            clamp_angle(data.get('duct_angle', DEFAULT_DUCT_ANGLE),
                        DEFAULT_DUCT_ANGLE),
            ('tee' if data.get('duct_fitting') == 'tee'
             else DEFAULT_DUCT_FITTING),
            bool(data.get('show_report', DEFAULT_SHOW_REPORT)))


def write_settings(tray_angle, tray_connect, pipe_angle, duct_angle,
                   duct_fitting, show_report):
    """Returns None on success, or the error text so the window can show it."""
    payload = {
        'tray_angle': tray_angle,
        'tray_connect': bool(tray_connect),
        'pipe_angle': pipe_angle,
        'duct_angle': duct_angle,
        'duct_fitting': 'tee' if duct_fitting == 'tee' else 'tap',
        'show_report': bool(show_report),
    }
    try:
        if not os.path.isdir(SETTINGS_DIR):
            os.makedirs(SETTINGS_DIR)
        text = json.dumps(payload, indent=2)
        # io.open wants text, and json.dumps hands back a byte string on
        # IronPython 2.7 but not on CPython, so normalise before writing
        if not isinstance(text, type(u'')):
            text = text.decode('utf-8')
        handle = io.open(SETTINGS_FILE, 'w', encoding='utf-8')
        try:
            handle.write(text)
        finally:
            handle.close()
        return None
    except Exception as err:
        return '{0}'.format(err)


# --------------------------------------------------------- ribbon command ids
def flatten(text):
    if not text:
        return ''
    return ' '.join(text.replace('\r', ' ').replace('\n', ' ').split())


def hunt(items, wanted):
    """Depth first search of ribbon items for one whose text matches."""
    if not items:
        return None
    for item in items:
        try:
            labels = (flatten(getattr(item, 'Text', '')),
                      flatten(getattr(item, 'AutomationName', '')))
            if wanted in labels:
                found = getattr(item, 'Id', None)
                if found:
                    return found
        except Exception:
            pass
        try:
            child = hunt(getattr(item, 'Items', None), wanted)
        except Exception:
            child = None
        if child:
            return child
    return None


def ribbon_command_id(button_name):
    """Read the command id straight off Revit's live ribbon.

    Guessing this string is what caused "can not find target file" - Revit
    throws that when the CommandId in KeyboardShortcuts.xml does not match a
    command it has actually loaded. Asking the ribbon removes the guesswork.

    Returns None if the ribbon cannot be read, which the caller reports rather
    than writing an id that would not work.
    """
    try:
        import clr
        clr.AddReference('AdWindows')
        from Autodesk.Windows import ComponentManager
    except Exception:
        return None

    wanted = flatten(button_name)

    try:
        ribbon = ComponentManager.Ribbon
        if ribbon is None:
            return None

        our_tabs = []
        other_tabs = []
        for tab in ribbon.Tabs:
            names = (flatten(getattr(tab, 'Title', '')),
                     flatten(getattr(tab, 'AutomationName', '')))
            (our_tabs if TAB_NAME in names else other_tabs).append(tab)

        def sweep(tabs, panel_filter):
            for tab in tabs:
                for panel in tab.Panels:
                    source = getattr(panel, 'Source', None)
                    if source is None:
                        continue
                    if panel_filter and \
                            flatten(getattr(source, 'Title', '')) != PANEL_NAME:
                        continue
                    found = hunt(source.Items, wanted)
                    if found:
                        return found
            return None

        # our tab and panel first, then anywhere in our tab, then anywhere
        return (sweep(our_tabs, True)
                or sweep(our_tabs, False)
                or sweep(other_tabs, False))
    except Exception:
        return None


# ----------------------------------------------------------- revit shortcuts
def shortcuts_file():
    try:
        version = __revit__.Application.VersionNumber
    except Exception:
        return None
    appdata = os.getenv('APPDATA')
    if not appdata:
        return None
    return os.path.join(appdata, 'Autodesk', 'Revit',
                        'Autodesk Revit {0}'.format(version),
                        'KeyboardShortcuts.xml')


def find_item(root, button_name, wanted_id):
    """Existing entry for this button, by id first then by name."""
    if wanted_id:
        for item in root.findall('ShortcutItem'):
            if (item.get('CommandId') or '') == wanted_id:
                return item
    for item in root.findall('ShortcutItem'):
        if flatten(item.get('CommandName') or '') == flatten(button_name):
            return item
    tail = '%' + button_name
    for item in root.findall('ShortcutItem'):
        cid = item.get('CommandId') or ''
        if cid.endswith(tail) and TAB_NAME in cid:
            return item
    return None


def read_shortcuts():
    """Current shortcuts for the two buttons, as (tool, settings)."""
    path = shortcuts_file()
    if not path or not os.path.isfile(path):
        return '', ''
    try:
        root = ET.parse(path).getroot()
    except Exception:
        return '', ''

    def grab(name):
        item = find_item(root, name, ribbon_command_id(name))
        return (item.get('Shortcuts') or '') if item is not None else ''

    return grab(TOOL_BUTTON), grab(SETTINGS_BUTTON)


def clashes_with(root, keys, own_ids):
    """Any other command already using one of these keystrokes."""
    wanted = set(k.strip().upper() for k in keys.split('#') if k.strip())
    if not wanted:
        return None
    for item in root.findall('ShortcutItem'):
        if (item.get('CommandId') or '') in own_ids:
            continue
        existing = set(k.strip().upper()
                       for k in (item.get('Shortcuts') or '').split('#')
                       if k.strip())
        hit = wanted & existing
        if hit:
            return '{0} is already used by "{1}"'.format(
                sorted(hit)[0], item.get('CommandName') or 'another command')
    return None


def write_shortcuts(tool_keys, settings_keys):
    """Write both shortcuts into Revit's file. Returns (ok, message)."""
    wanted = [(TOOL_BUTTON, (tool_keys or '').strip()),
              (SETTINGS_BUTTON, (settings_keys or '').strip())]

    ids = {}
    missing = []
    for name, _ in wanted:
        found = ribbon_command_id(name)
        if found:
            ids[name] = found
        else:
            missing.append(name)

    if missing:
        return False, ('could not read the ribbon id for {0}. Reload pyRevit '
                       'so the button is on the ribbon, then try '
                       'again'.format(' and '.join(missing)))

    path = shortcuts_file()
    if not path:
        return False, 'could not work out where Revit keeps its shortcut file'

    if not os.path.isfile(path):
        return False, ("there is no KeyboardShortcuts.xml yet - open Revit's "
                       "Keyboard Shortcuts dialog and press Export once, then "
                       "try again")

    try:
        tree = ET.parse(path)
        root = tree.getroot()
    except Exception as err:
        return False, "could not read Revit's shortcut file ({0})".format(err)

    own_ids = set(ids.values())
    for name, _ in wanted:
        item = find_item(root, name, ids[name])
        if item is not None:
            own_ids.add(item.get('CommandId') or '')

    for name, keys in wanted:
        if not keys:
            continue
        clash = clashes_with(root, keys, own_ids)
        if clash:
            return False, clash

    for name, keys in wanted:
        item = find_item(root, name, ids[name])
        if item is None:
            if not keys:
                continue
            item = ET.SubElement(root, 'ShortcutItem')
        # rewrite the id every time, so an entry left behind by an earlier
        # build with a bad id gets corrected rather than duplicated
        item.set('CommandName', name)
        item.set('CommandId', ids[name])
        item.set('Paths', '{0}>{1}'.format(TAB_NAME, PANEL_NAME))
        item.set('Shortcuts', keys)

    try:
        shutil.copyfile(path, path + '.bak')
    except Exception:
        pass

    try:
        tree.write(path, encoding='utf-8', xml_declaration=True)
    except Exception as err:
        return False, "could not write Revit's shortcut file ({0})".format(err)

    return True, 'written, restart Revit for them to take effect'


# ------------------------------------------------------------------- window
class ExtendSettings(forms.WPFWindow):
    def __init__(self):
        forms.WPFWindow.__init__(self, XAML_FILE)
        self.version_label.Text = 'v{0}'.format(__version__)
        self.apply_icon()
        self.load(read_settings())
        self.load_shortcuts()

    def apply_icon(self):
        if not os.path.exists(ICON_FILE):
            return
        try:
            self.set_icon(ICON_FILE)
        except Exception:
            pass
        try:
            from System import Uri
            from System.Windows.Media.Imaging import BitmapImage
            self.header_icon.Source = BitmapImage(Uri(ICON_FILE))
        except Exception:
            pass

    # ------------------------------------------------------------ helpers
    def set_angle_row(self, angle, rb90, rb45, rb_custom, custom_tb):
        if abs(angle - 90.0) < 0.001:
            rb90.IsChecked = True
            custom_tb.Text = '60'
        elif abs(angle - 45.0) < 0.001:
            rb45.IsChecked = True
            custom_tb.Text = '60'
        else:
            rb_custom.IsChecked = True
            custom_tb.Text = '{0:g}'.format(angle)

    def read_angle_row(self, rb45, rb_custom, custom_tb, fallback):
        if rb45.IsChecked:
            return 45.0
        if rb_custom.IsChecked:
            return clamp_angle(custom_tb.Text, fallback)
        return 90.0

    def load(self, values):
        (tray_angle, tray_connect, pipe_angle, duct_angle,
         duct_fitting, show_report) = values

        self.set_angle_row(tray_angle, self.tray_90_rb, self.tray_45_rb,
                           self.tray_custom_rb, self.tray_custom_tb)
        self.tray_connect_cb.IsChecked = tray_connect

        self.set_angle_row(pipe_angle, self.pipe_90_rb, self.pipe_45_rb,
                           self.pipe_custom_rb, self.pipe_custom_tb)

        self.set_angle_row(duct_angle, self.duct_90_rb, self.duct_45_rb,
                           self.duct_custom_rb, self.duct_custom_tb)

        if duct_fitting == 'tee':
            self.duct_tee_rb.IsChecked = True
        else:
            self.duct_tap_rb.IsChecked = True

        self.show_report_cb.IsChecked = show_report
        self.path_label.Text = SETTINGS_FILE
        self.status_label.Text = ''

    def load_shortcuts(self):
        tool_keys, settings_keys = read_shortcuts()
        self.sc_tool_tb.Text = tool_keys
        self.sc_settings_tb.Text = settings_keys

        found = ribbon_command_id(TOOL_BUTTON)
        self.id_label.Text = (
            'Ribbon id: {0}'.format(found) if found
            else 'Ribbon id could not be read - reload pyRevit before '
                 'setting a shortcut.')

    def gather(self):
        return (self.read_angle_row(self.tray_45_rb, self.tray_custom_rb,
                                    self.tray_custom_tb, DEFAULT_TRAY_ANGLE),
                bool(self.tray_connect_cb.IsChecked),
                self.read_angle_row(self.pipe_45_rb, self.pipe_custom_rb,
                                    self.pipe_custom_tb, DEFAULT_PIPE_ANGLE),
                self.read_angle_row(self.duct_45_rb, self.duct_custom_rb,
                                    self.duct_custom_tb, DEFAULT_DUCT_ANGLE),
                'tee' if self.duct_tee_rb.IsChecked else 'tap',
                bool(self.show_report_cb.IsChecked))

    def commit(self):
        problem = write_settings(*self.gather())
        if problem is not None:
            self.status_label.Text = 'Could not save: {0}'.format(problem)
            return False

        # read straight back off disk, so what you see is what 3D Extend will
        # actually pick up on its next run
        stored = read_settings()
        self.load(stored)

        message = ('Saved. Tray {0:g} deg, connect {1}. Pipes {2:g} deg. '
                   'Ducts {3:g} deg, {4}.'.format(
                       stored[0], 'on' if stored[1] else 'off',
                       stored[2], stored[3],
                       'tee' if stored[4] == 'tee' else 'shoe'))

        if self.sc_tool_tb.Text.strip() or self.sc_settings_tb.Text.strip():
            ok, note = write_shortcuts(self.sc_tool_tb.Text,
                                       self.sc_settings_tb.Text)
            message += '\nShortcuts {0}: {1}'.format(
                'set' if ok else 'NOT set', note)
            self.load_shortcuts()

        self.status_label.Text = message
        return True

    # ------------------------------------------------------------- events
    def on_reset(self, sender, args):
        self.load((DEFAULT_TRAY_ANGLE, DEFAULT_TRAY_CONNECT,
                   DEFAULT_PIPE_ANGLE, DEFAULT_DUCT_ANGLE,
                   DEFAULT_DUCT_FITTING, DEFAULT_SHOW_REPORT))
        self.status_label.Text = 'Defaults loaded - Apply or Save to keep them.'

    def on_cancel(self, sender, args):
        self.Close()

    def on_apply(self, sender, args):
        self.commit()

    def on_save(self, sender, args):
        if self.commit():
            self.Close()


if __name__ == '__main__':
    ExtendSettings().ShowDialog()
