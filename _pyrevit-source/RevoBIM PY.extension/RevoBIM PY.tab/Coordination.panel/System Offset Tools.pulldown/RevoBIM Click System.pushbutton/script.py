# -*- coding: utf-8 -*-
"""Route a service by clicking: a run, then a point, then more.

RevoBIM Click System. Click a pipe, duct, cable tray or
conduit, then click where it should go. The run carries on to
the corner, a 90 degree bend goes in, and a new length runs
out to the click. Every click after that does the same again
from the end of the last one, until Escape.

Where the first corner falls inside the run it is split there
and whatever lies beyond is let go, so the new route is its
own system. Nothing after that is ever cut.

Opens no window, so Revit's own Keyboard Shortcuts dialog can
drive the whole tool.
"""

# ==========================================================
# Thin loader.
#
# A blank white pyRevit window means the script died before
# any of it ran, and there is no traceback to read because
# there was no runtime to raise one. So the very first thing
# this file does, before importing anything that can fail,
# is drop a breadcrumb saying it got this far. Every stage
# overwrites it.
#
#   no file at all       pyRevit never ran the script
#   "reached script.py"  it died on the very first import
#   a named stage        it died there, with the traceback
#
# The file is %APPDATA%\RevoBIM\click_system_last_error.txt
# ==========================================================

__title__ = 'RevoBIM Click System'
__author__ = 'RevoBIM'

_LOG = 'click_system_last_error.txt'
_STAGE = 'reached script.py'


def _write(text):
    """Write the log using nothing that can itself be missing."""
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
    """Which engine and which folder, which is half the answer."""
    try:
        import sys
        return u'engine: {0}\nfolder: {1}\n'.format(
            sys.version.replace('\n', ' '), __file__)
    except Exception:
        return u''


def _mark(stage):
    _write(u'RevoBIM Click System\nstage: {0}\n{1}'.format(stage, _where()))


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
    import so_core

    _STAGE = 'loading so_model'
    _mark(_STAGE)
    import so_model  # noqa: F401

    _STAGE = 'loading so_click'
    _mark(_STAGE)
    import so_click

    _STAGE = 'loading results_window'
    _mark(_STAGE)
    import results_window

    _STAGE = 'reading the settings'
    _mark(_STAGE)
    settings = so_core.load_settings()

    _STAGE = 'reaching Revit'
    _mark(_STAGE)
    uiapp = __revit__  # noqa: F821  pyRevit provides this

    _STAGE = 'running the picks'
    _mark(_STAGE)
    records = so_click.run(uiapp)

    _STAGE = 'reporting'
    _mark(_STAGE)
    if records and results_window.should_show(settings, records):
        results_window.show(records, settings,
                            so_core.to_text(settings.get('theme', 'revit')),
                            u'Click System')

    _write(u'RevoBIM Click System finished cleanly.\n{0}'.format(_where()))

except Exception:
    _text = u'RevoBIM Click System failed at stage: {0}\n'.format(_STAGE)
    try:
        import traceback as _tb
        _text = (u'RevoBIM Click System could not start.\n\nStage: {0}\n\n'
                 u'{1}\n{2}').format(_STAGE, _tb.format_exc(), _where())
    except Exception:
        pass
    _write(_text)
    try:
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show('RevoBIM Click System', _text[:2000])
    except Exception:
        pass
