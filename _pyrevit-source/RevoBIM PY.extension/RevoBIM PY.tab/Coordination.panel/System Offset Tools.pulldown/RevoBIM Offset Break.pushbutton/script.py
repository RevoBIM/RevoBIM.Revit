# -*- coding: utf-8 -*-
"""Cut a run at the second click and step it onto a new line.

RevoBIM Offset Break. The same two clicks and the same prompt
as RevoBIM System Offset, and the same settings - but the run
is cut at the second click rather than brought back onto its
own line, so it steps across and what lies beyond the cut is
left where it was.

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
# The file is %APPDATA%\RevoBIM\offset_break_last_error.txt
# ==========================================================

__title__ = 'RevoBIM Offset Break'
__author__ = 'RevoBIM'

_LOG = 'offset_break_last_error.txt'
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
    _write(u'RevoBIM Offset Break\nstage: {0}\n{1}'.format(stage, _where()))


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
    import so_model

    _STAGE = 'loading offset_prompt'
    _mark(_STAGE)
    import offset_prompt  # noqa: F401

    _STAGE = 'loading so_run'
    _mark(_STAGE)
    import so_run

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
    records = so_run.run(uiapp, so_model.MODE_BREAK, u'Offset Break')

    _STAGE = 'reporting'
    _mark(_STAGE)
    if records and results_window.should_show(settings, records):
        results_window.show(records, settings,
                            so_core.to_text(settings.get('theme', 'revit')))

    _write(u'RevoBIM Offset Break finished cleanly.\n{0}'.format(_where()))

except Exception:
    _text = u'RevoBIM Offset Break failed at stage: {0}\n'.format(_STAGE)
    try:
        import traceback as _tb
        _text = (u'RevoBIM Offset Break could not start.\n\nStage: {0}\n\n'
                 u'{1}\n{2}').format(_STAGE, _tb.format_exc(), _where())
    except Exception:
        pass
    _write(_text)
    try:
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show('RevoBIM Offset Break', _text[:2000])
    except Exception:
        pass
