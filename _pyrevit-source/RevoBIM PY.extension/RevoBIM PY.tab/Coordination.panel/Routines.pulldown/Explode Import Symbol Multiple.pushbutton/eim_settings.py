# -*- coding: utf-8 -*-
"""Settings file and debug log for Explode Import Symbol Multiple.

Settings: %APPDATA%\\RevoBIM\\explode_import_multiple.txt (key=value)
Debug:    %APPDATA%\\RevoBIM\\explode_import_multiple_debug.txt
"""
import io
import os
import threading
import datetime

import eim_core
from eim_version import __version__


def folder():
    base = os.environ.get('APPDATA') or os.path.expanduser('~')
    path = os.path.join(base, 'RevoBIM')
    try:
        if not os.path.isdir(path):
            os.makedirs(path)
    except Exception:
        pass
    return path


def settings_path():
    return os.path.join(folder(), 'explode_import_multiple.txt')


def debug_path():
    return os.path.join(folder(), 'explode_import_multiple_debug.txt')


def load():
    text = u''
    try:
        with io.open(settings_path(), 'r', encoding='utf-8') as fh:
            text = fh.read()
    except Exception:
        text = u''
    return eim_core.parse_settings(text)


def save(settings):
    try:
        data = eim_core.dump_settings(settings)
        with io.open(settings_path(), 'w', encoding='utf-8') as fh:
            fh.write(data)
        return True
    except Exception:
        return False


class Log(object):
    """Debug log. Thread safe, because the UI Automation fallback writes from
    a background thread. Never raises."""

    def __init__(self, enabled):
        self.enabled = enabled
        self._lock = threading.Lock()
        self.lines = []
        if enabled:
            self._write(u'w', u'Explode Import Symbol Multiple v{0} - {1}\n'.format(
                __version__, datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))

    def _write(self, how, text):
        try:
            with io.open(debug_path(), how, encoding='utf-8') as fh:
                fh.write(text)
        except Exception:
            pass

    def __call__(self, message):
        try:
            stamp = datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]
            line = u'{0}  {1}'.format(stamp, message)
        except Exception:
            return
        with self._lock:
            self.lines.append(line)
            if self.enabled:
                self._write(u'a', line + u'\n')
