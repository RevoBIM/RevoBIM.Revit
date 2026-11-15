# -*- coding: utf-8 -*-
u"""Project Browser Pro - is docking set up, and setting it up.

Revit only takes a dockable pane while it is building its user interface,
so the panes are registered by a block in the extension's own startup.py
(startup_fragment.txt, shipped beside this file). On a machine where that
block was never pasted in, the browser can only open as a floating window -
which is why one machine docks and another does not.

The Dock button asks this module what is wrong and, with the user's yes,
adds the block itself: startup.py is backed up first, the block is appended
(never anything replaced), and it is never added twice. A Revit restart is
still needed - only then does Revit take the panes.

Pure Python: the bench runs it against folders it makes.
"""
import io
import os
import time

FRAGMENT_FILE = u'startup_fragment.txt'
MARKER = u'RevoBIM Project Browser Pro - register the dockable panes'
STARTUP = u'startup.py'


def extension_root(here):
    u"""The *.extension folder this tool sits in, or None."""
    folder = os.path.abspath(here)
    for _ in range(6):
        if folder.lower().endswith(u'.extension'):
            return folder
        parent = os.path.dirname(folder)
        if parent == folder:
            break
        folder = parent
    return None


def _read(path):
    handle = io.open(path, 'r', encoding='utf-8-sig')
    try:
        return handle.read()
    finally:
        handle.close()


def state(here):
    u"""(what, startup.py path):
    'present'      the block is in startup.py
    'missing'      startup.py has no block
    'no_file'      the extension has no startup.py yet
    'no_extension' this tool is not inside a *.extension folder"""
    root = extension_root(here)
    if root is None:
        return u'no_extension', None
    path = os.path.join(root, STARTUP)
    if not os.path.isfile(path):
        return u'no_file', path
    try:
        text = _read(path)
    except Exception:
        return u'missing', path
    return (u'present' if MARKER in text else u'missing'), path


def install(here, now=None):
    u"""Add the block to the extension's startup.py. Returns (ok, message).

    An existing startup.py is copied to startup.py.<stamp>.bak first and the
    block is appended to it - its own content (the easter egg, the Addin
    Manager and Family Viewer panes...) is left exactly as it was."""
    what, path = state(here)
    if what == u'present':
        return True, u'The docking block is already in {0}.'.format(path)
    if what == u'no_extension':
        return False, u'This tool is not inside a .extension folder, so there is no startup.py to add to.'
    try:
        block = _read(os.path.join(os.path.dirname(os.path.abspath(__file__)), FRAGMENT_FILE))
    except Exception as error:
        return False, u'The docking block ({0}) is missing from the tool: {1}'.format(FRAGMENT_FILE, error)
    if MARKER not in block:
        return False, u'{0} is not the docking block.'.format(FRAGMENT_FILE)
    stamp = time.strftime('%Y%m%d-%H%M%S', time.localtime(now if now is not None else time.time()))
    try:
        if what == u'missing':
            existing = _read(path)
            backup = u'{0}.{1}.bak'.format(path, stamp)
            handle = io.open(backup, 'w', encoding='utf-8')
            try:
                handle.write(existing)
            finally:
                handle.close()
            text = existing.rstrip(u'\r\n') + u'\n\n\n' + block
        else:
            backup = u''
            text = block
        handle = io.open(path, 'w', encoding='utf-8')
        try:
            handle.write(text)
        finally:
            handle.close()
    except Exception as error:
        return False, u'Could not write {0}: {1}'.format(path, error)
    note = u' (the old one is kept as {0})'.format(os.path.basename(backup)) if backup else u''
    return True, u'Added the docking block to {0}{1}.'.format(path, note)
