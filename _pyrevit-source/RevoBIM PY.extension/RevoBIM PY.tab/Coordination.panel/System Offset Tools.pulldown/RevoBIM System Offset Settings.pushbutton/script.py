# -*- coding: utf-8 -*-
"""Settings for RevoBIM System Offset.

Bend angle, which way the offset goes, how far, rounding,
reporting and theme. Written to
%APPDATA%\\RevoBIM\\system_offset.txt.
"""

# ==========================================================
# Thin loader. Same breadcrumb as the command button, into
# %APPDATA%\RevoBIM\system_offset_settings_last_error.txt
# ==========================================================

__title__ = 'RevoBIM System Offset Settings'
__author__ = 'RevoBIM'

_LOG = 'system_offset_settings_last_error.txt'
_STAGE = 'reached script.py'


def _write(text):
    try:
        import os
        base = os.environ.get('APPDATA') or os.path.expanduser('~')
        folder = os.path.join(base, 'RevoBIM')
        if not os.path.isdir(folder):
            os.makedirs(folder)
        handle = open(os.path.join(folder, _LOG), 'wb')
        try:
            handle.write(text.encode('utf-8'))
        finally:
            handle.close()
    except Exception:
        pass


def _where():
    try:
        import sys
        return u'engine: {0}\nfolder: {1}\n'.format(
            sys.version.replace('\n', ' '), __file__)
    except Exception:
        return u''


def _mark(stage):
    _write(u'RevoBIM System Offset Settings\nstage: {0}\n{1}'
           .format(stage, _where()))


_mark(_STAGE)

try:
    import os
    import sys

    _STAGE = 'putting the tool folder on sys.path'
    _mark(_STAGE)
    HERE = os.path.dirname(os.path.abspath(__file__))
    PARENT = os.path.dirname(HERE)
    if PARENT not in sys.path:
        sys.path.append(PARENT)

    _STAGE = 'referencing assemblies (so_clr)'
    _mark(_STAGE)
    import so_clr  # noqa: F401

    _STAGE = 'loading so_core'
    _mark(_STAGE)
    import so_core  # noqa: F401

    _STAGE = 'loading so_ui'
    _mark(_STAGE)
    import so_ui  # noqa: F401

    _STAGE = 'loading settings_window'
    _mark(_STAGE)
    import so_command_host
    import settings_window

    _STAGE = 'reaching Revit'
    _mark(_STAGE)
    so_command_host.set_uiapp(__revit__)  # noqa: F821  pyRevit provides this

    _STAGE = 'building the window'
    _mark(_STAGE)
    _window = settings_window.SettingsWindow()

    _STAGE = 'showing the window'
    _mark(_STAGE)
    _window.show()

    _write(u'RevoBIM System Offset Settings finished cleanly.\n{0}'
           .format(_where()))

except Exception:
    _text = u'RevoBIM System Offset Settings failed at stage: {0}\n'.format(_STAGE)
    try:
        import traceback as _tb
        _text = (u'RevoBIM System Offset Settings could not start.\n\n'
                 u'Stage: {0}\n\n{1}\n{2}').format(_STAGE, _tb.format_exc(),
                                                   _where())
    except Exception:
        pass
    _write(_text)
    try:
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show('RevoBIM System Offset Settings', _text[:2000])
    except Exception:
        pass
