# -*- coding: utf-8 -*-
"""Space Data Push - thin staged loader.

Push parameter values from a picked space onto elements picked in any other view.
The tool lives in the sdp_* modules beside this file. This loader imports them in
stages and names the stage that failed, in a Revit dialog and in
%APPDATA%\\RevoBIM\\space_data_push_last_error.txt, so a failure is never a blank
white pyRevit window. It carries no clr.AddReference of its own: sdp_clr does that.
"""
__title__ = 'Space Data Push'
__author__ = 'RevoBIM'
__persistentengine__ = True

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)


def _report(stage, text):
    """Write the failure to disk and show it. Never raises."""
    message = u'Space Data Push could not start.\nStage: %s\n\n%s' % (stage, text)
    try:
        base = os.environ.get('APPDATA') or os.path.expanduser('~')
        folder = os.path.join(base, 'RevoBIM')
        if not os.path.isdir(folder):
            os.makedirs(folder)
        with open(os.path.join(folder, 'space_data_push_last_error.txt'), 'w') as fh:
            fh.write(message.encode('utf-8') if not isinstance(message, str) else message)
    except Exception:
        pass
    try:
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show('RevoBIM - Space Data Push', message)
    except Exception:
        pass


def _window_is_open():
    try:
        import sdp_version
        from System import AppDomain
        return AppDomain.CurrentDomain.GetData(sdp_version.PARK_KEY + u'.window') is not None
    except Exception:
        return False


def _fresh_modules():
    """A persistent engine keeps modules between runs, so edited files would not be
    picked up. Drop ours - unless the window is open, whose handlers still use them."""
    if _window_is_open():
        return
    for name in list(sys.modules.keys()):
        if name.startswith('sdp_'):
            try:
                del sys.modules[name]
            except Exception:
                pass


def _run():
    _fresh_modules()

    stage = 'assemblies'
    try:
        import sdp_clr
    except Exception:
        return _report(stage, traceback.format_exc())

    stage = 'modules'
    try:
        import sdp_logic
        import sdp_model
        import sdp_runner
        import sdp_theme
        import sdp_ui
        import sdp_window
    except Exception:
        return _report(stage, traceback.format_exc())

    stage = 'opening the window'
    try:
        sdp_window.launch(__revit__)
    except sdp_logic.UserMessage as ex:
        try:
            from Autodesk.Revit.UI import TaskDialog
            TaskDialog.Show('RevoBIM - Space Data Push', sdp_logic.to_text(ex))
        except Exception:
            pass
    except Exception:
        _report(stage, traceback.format_exc())


_run()
