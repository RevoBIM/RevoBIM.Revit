# -*- coding: utf-8 -*-
"""RevoBIM Match Offset - staged loading.

script.py is a thin loader that imports this and nothing else, because a blank
white pyRevit window means the script died before any of it ran and a tool that
is one big script has no runtime left to report its own import failure. Each
stage here sits in its own try/except and names itself, into a Revit dialog
with the traceback and into %APPDATA%\\RevoBIM\\match_offset_last_error.txt.
"""

import mo_clr  # noqa: F401

import os
import traceback


def _error_file():
    root = os.environ.get('APPDATA') or os.path.expanduser('~')
    folder = os.path.join(root, 'RevoBIM')
    try:
        if not os.path.isdir(folder):
            os.makedirs(folder)
    except Exception:
        pass
    return os.path.join(folder, 'match_offset_last_error.txt')


def report_failure(stage, detail):
    """Say where it died, in a dialog and on disk."""
    try:
        import mo_core
        mo_core.log(u"failed while {0}: {1}".format(stage, detail))
        mo_core.flush_log()
    except Exception:
        pass
    text = u"RevoBIM Match Offset failed while {0}.\n\n{1}".format(
        stage, detail)
    try:
        handle = open(_error_file(), 'wb')
        try:
            handle.write(text.encode('utf-8'))
        finally:
            handle.close()
    except Exception:
        pass
    try:
        from Autodesk.Revit.UI import TaskDialog
        dialog = TaskDialog(u"RevoBIM Match Offset")
        dialog.MainInstruction = u"Failed while {0}".format(stage)
        dialog.MainContent = detail
        dialog.Show()
    except Exception:
        pass


def clear_failure():
    try:
        path = _error_file()
        if os.path.isfile(path):
            os.remove(path)
    except Exception:
        pass


def silent(settings):
    try:
        import mo_core
        return mo_core.is_silent(settings)
    except Exception:
        return False


def show_results(report, settings, label):
    """The results window, unless the run is meant to be silent."""
    if silent(settings):
        return
    try:
        import results_window
        if report.should_show(settings.get(u"show_results", u"problems")):
            results_window.show(report, settings, label)
    except Exception:
        pass


def show_debug(report, settings):
    """The debug report, when the tick is on. Never allowed to take a
    finished run down with it."""
    if getattr(report, 'debug', None) is None or silent(settings):
        return
    try:
        import debug_window
        debug_window.show(report.debug, settings)
    except Exception:
        try:
            report.debug.save()
        except Exception:
            pass


def launch(uiapp, anchor):
    """Run one of the three match commands."""
    stage = u"referencing assemblies"
    try:
        missing = mo_clr.report()
        if missing:
            report_failure(stage, missing)
            return

        stage = u"loading the tool's modules"
        import mo_core
        import mo_run

        stage = u"reading the project"
        if uiapp is None or uiapp.ActiveUIDocument is None:
            report_failure(stage, u"There is no open project.")
            return

        stage = u"picking elements"
        settings, report = mo_run.run(uiapp, anchor)

        stage = u"showing the results"
        show_results(report, settings,
                     mo_core.ANCHOR_LABEL.get(anchor, anchor))
        show_debug(report, settings)
        clear_failure()
    except Exception:
        report_failure(stage, traceback.format_exc())


def launch_slope(uiapp):
    """Run the slope match: click the main, then click branches."""
    stage = u"referencing assemblies"
    try:
        missing = mo_clr.report()
        if missing:
            report_failure(stage, missing)
            return

        stage = u"loading the tool's modules"
        import mos_run

        stage = u"reading the project"
        if uiapp is None or uiapp.ActiveUIDocument is None:
            report_failure(stage, u"There is no open project.")
            return

        stage = u"picking pipes"
        settings, report = mos_run.run(uiapp)

        stage = u"showing the results"
        show_results(report, settings, u"Slope")
        show_debug(report, settings)
        clear_failure()
    except Exception:
        report_failure(stage, traceback.format_exc())


def launch_settings(uiapp):
    """Open the settings window."""
    stage = u"referencing assemblies"
    try:
        missing = mo_clr.report()
        if missing:
            report_failure(stage, missing)
            return

        stage = u"loading the tool's modules"
        import settings_window

        stage = u"showing the window"
        settings_window.show(uiapp)
        clear_failure()
    except Exception:
        report_failure(stage, traceback.format_exc())
