# -*- coding: utf-8 -*-
u"""Project Browser Pro - debug log and the report Drew pastes back to Claude.

Pure Python (os, io, time, traceback) so it works in every engine and on the
bench. Logging is on by default while the tool is new; the Debug tick in the
footer switches it, and Copy report puts a pasteable block on the clipboard.

The log never raises: a debug feature that can take a tool down is worse
than no debug feature.
"""
import io
import os
import time
import traceback

from pbp_compat import to_text

ENABLED = [True]
RING = []
RING_SIZE = 400
MAX_BYTES = 1024 * 1024
FILE_NAME = u'project_browser_pro_debug.txt'


def appdata_folder():
    base = os.environ.get('APPDATA') or os.path.expanduser('~')
    return os.path.join(to_text(base), u'RevoBIM')


def log_path():
    return os.path.join(appdata_folder(), FILE_NAME)


def set_enabled(value):
    ENABLED[0] = bool(value)


def _stamp():
    return to_text(time.strftime('%Y-%m-%d %H:%M:%S'))


def _append_file(line):
    try:
        folder = appdata_folder()
        if not os.path.isdir(folder):
            os.makedirs(folder)
        path = log_path()
        try:
            if os.path.isfile(path) and os.path.getsize(path) > MAX_BYTES:
                old = path + u'.old'
                if os.path.isfile(old):
                    os.remove(old)
                os.rename(path, old)
        except Exception:
            pass
        handle = io.open(path, 'a', encoding='utf-8')
        try:
            handle.write(line + u'\n')
        finally:
            handle.close()
    except Exception:
        pass


def log(message):
    u"""One line in the ring (always) and in the file (when debug is on)."""
    try:
        line = u'{0}  {1}'.format(_stamp(), to_text(message))
        RING.append(line)
        if len(RING) > RING_SIZE:
            del RING[:len(RING) - RING_SIZE]
        if ENABLED[0]:
            _append_file(line)
    except Exception:
        pass


def exc(where):
    u"""Log the current exception with its traceback and return the text."""
    try:
        text = to_text(traceback.format_exc())
    except Exception:
        text = u'(no traceback)'
    log(u'ERROR in {0}\n{1}'.format(to_text(where), text))
    return text


def report(lines):
    u"""The block Copy report puts on the clipboard.

    `lines` are the environment facts the caller knows (Revit version, pane
    state, counts, organisations); the recent log follows them.
    """
    out = [u'===== RevoBIM Project Browser Pro - debug report =====']
    for line in lines or []:
        out.append(to_text(line))
    out.append(u'----- recent log ({0} lines) -----'.format(min(len(RING), 120)))
    out.extend(RING[-120:])
    out.append(u'===== end of report =====')
    return u'\n'.join(out)
