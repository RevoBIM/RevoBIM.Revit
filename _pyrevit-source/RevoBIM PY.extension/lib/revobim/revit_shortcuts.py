# -*- coding: utf-8 -*-
"""revobim.revit_shortcuts - read and write Revit's KeyboardShortcuts.xml.

Revit builds that file from the ribbon at startup and only reads it back at
startup, so assigning a shortcut always costs a restart whichever way you do
it. This module just saves the hunting about in the dialog.

    from revobim import revit_shortcuts as ks

    path = ks.shortcuts_path(__revit__.Application)
    doc = ks.load(path)
    item = ks.find(doc, 'Nudge Up')
    ks.set_keys(item, 'NU')
    ks.save(doc, path)          # writes a .bak alongside first

Uses System.Xml rather than the Python stdlib so the file comes back out with
its structure intact under IronPython.
"""

import os

import clr
clr.AddReference('System.Xml')
from System.Xml import XmlDocument


FILENAME = 'KeyboardShortcuts.xml'


def shortcuts_path(app=None, version_name=None):
    """Best guess at where the running Revit keeps its shortcuts file.

    Pass either the Application object or a version name such as
    'Autodesk Revit 2024'.
    """
    if version_name is None and app is not None:
        try:
            version_name = app.VersionName
        except Exception:
            version_name = None
    if not version_name:
        try:
            version_name = 'Autodesk Revit ' + str(app.VersionNumber)
        except Exception:
            return None

    roaming = os.getenv('APPDATA')
    if not roaming:
        return None
    return os.path.join(roaming, 'Autodesk', 'Revit', version_name, FILENAME)


def exists(path):
    return bool(path) and os.path.isfile(path)


def load(path):
    """Parse the file. Returns an XmlDocument, or None if it is not there."""
    if not exists(path):
        return None
    doc = XmlDocument()
    doc.Load(path)
    return doc


def items(doc):
    """Every ShortcutItem in the file."""
    if doc is None:
        return []
    return list(doc.GetElementsByTagName('ShortcutItem'))


def find(doc, command_name):
    """The ShortcutItem for a command, matched on CommandName.

    Exact match first, then a case-insensitive contains, so a slightly
    different label still gets picked up.
    """
    if doc is None:
        return None
    wanted = (command_name or '').strip().lower()
    if not wanted:
        return None

    loose = None
    for item in items(doc):
        name = (item.GetAttribute('CommandName') or '').strip()
        if name.lower() == wanted:
            return item
        if loose is None and wanted in name.lower():
            loose = item
    return loose


def get_keys(item):
    if item is None:
        return ''
    return (item.GetAttribute('Shortcuts') or '').strip()


def set_keys(item, keys):
    """Assign the shortcut. Several are separated by #, as Revit does it."""
    if item is None:
        return False
    keys = (keys or '').strip().upper()
    if keys:
        item.SetAttribute('Shortcuts', keys)
    elif item.HasAttribute('Shortcuts'):
        item.RemoveAttribute('Shortcuts')
    return True


def path_of(item):
    """The ribbon path Revit shows in the dialog, e.g. 'RevoBIM PY>Coordination'."""
    if item is None:
        return ''
    return (item.GetAttribute('Paths') or '').strip()


def clashes(doc, keys, ignore=None):
    """Commands already using any of these keystrokes.

    Returns a list of command names. Revit will happily let two commands
    share a shortcut and then cycle between them, which is rarely what
    anyone wants, so it is worth saying something.

    `ignore` is matched on CommandId rather than object identity - the XML
    node you hold and the one that comes back out of the node list are not
    necessarily the same wrapper object.
    """
    wanted = set(k.strip().upper()
                 for k in (keys or '').split('#') if k.strip())
    if not wanted:
        return []

    skip_id = None
    if ignore is not None:
        skip_id = ignore.GetAttribute('CommandId')

    found = []
    for item in items(doc):
        if skip_id and item.GetAttribute('CommandId') == skip_id:
            continue
        existing = set(k.strip().upper()
                       for k in get_keys(item).split('#') if k.strip())
        if existing & wanted:
            name = item.GetAttribute('CommandName') or '(unnamed)'
            found.append(name)
    return found


def save(doc, path, backup=True):
    """Write the file back, keeping one backup copy."""
    if doc is None or not path:
        return False
    if backup and os.path.isfile(path):
        spare = path + '.bak'
        try:
            if os.path.isfile(spare):
                os.remove(spare)
            import shutil
            shutil.copy2(path, spare)
        except Exception:
            # a failed backup should not stop the write
            pass
    doc.Save(path)
    return True
