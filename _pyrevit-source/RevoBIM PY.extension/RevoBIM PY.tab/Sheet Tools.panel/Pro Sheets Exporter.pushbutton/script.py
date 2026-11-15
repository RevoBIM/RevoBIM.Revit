# -*- coding: utf-8 -*-
"""RevoBIM Pro Sheets Exporter - the loader.

This file stays deliberately thin. It imports nothing that can fail at module
level, adds its own folder to ``sys.path`` and then brings the tool up **in
stages**, each in its own try/except that names the stage it was on.

A blank white pyRevit window means the script died before any of it ran, and
a tool that is one big script has no runtime left to report its own import
failure. Staging it is what turns that blank window into a message naming the
file, the line and the column.
"""

__title__ = 'Pro Sheets\nExporter'
__author__ = 'RevoBIM PY'
__doc__ = ('Batch export sheets and views to PDF and DWG, with custom file '
           'naming from sheet parameters, parameter-driven output folders '
           'and saved templates per project.\n\n'
           'Opens modeless: Revit stays fully usable while it is open, and '
           'sheets selected before launching arrive already isolated.')

# The window is modeless, so the engine has to survive the command returning.
# Without this the window opens and every handler in it is dead, which is
# indistinguishable from a broken tool.
__persistentengine__ = True

import os
import sys
import traceback


HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.append(HERE)


def _fallback(stage, detail):
    """Report a failure with no help from the tool's own modules."""
    text = u'RevoBIM Pro Sheets Exporter stopped at "{0}".\n\n{1}'.format(
        stage, detail)
    try:
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show('RevoBIM Pro Sheets Exporter', text[:3000])
        return
    except Exception:
        pass
    try:
        sys.stderr.write(text)
    except Exception:
        pass


def _write_log(text):
    try:
        from System import Environment
        base = Environment.GetFolderPath(
            Environment.SpecialFolder.ApplicationData)
    except Exception:
        base = os.path.expanduser('~')
    try:
        folder = os.path.join(base, 'RevoBIM', 'logs')
        if not os.path.isdir(folder):
            os.makedirs(folder)
        path = os.path.join(folder, 'pro_sheets_exporter_last_error.txt')
        handle = open(path, 'wb')
        try:
            handle.write(text.encode('utf-8'))
        finally:
            handle.close()
        return path
    except Exception:
        return u'(the log file could not be written)'


def main():
    stage = 'referencing assemblies'
    reporter = None
    try:
        import ps_refs
        stage = 'loading the tool'
        import ps_ui
        reporter = ps_ui.report_failure
        import ps_window

        stage = 'finding the document'
        uiapp = __revit__                                      # noqa: F821
        if uiapp is None:
            raise Exception('Revit did not hand over a UIApplication.')
        uidoc = uiapp.ActiveUIDocument
        if uidoc is None or uidoc.Document is None:
            raise Exception('Open a project before running this tool.')
        if uidoc.Document.IsFamilyDocument:
            raise Exception('This tool works on projects, not families.')

        # Project Browser Pro's Express button: a headless run of the
        # sheets it sent, answered before anything is built. Returns False
        # - and the window opens as always - for anything else.
        stage = 'checking for an Express print'
        import ps_express
        if ps_express.run(uiapp, HERE):
            return

        stage = 'building the window'
        ps_window.show(uiapp)
        del ps_refs
    except Exception as err:
        detail = u'{0}\n\n{1}'.format(err, traceback.format_exc())
        path = _write_log(u'Stage: {0}\n\n{1}'.format(stage, detail))
        if reporter is not None:
            try:
                reporter(stage, err)
                return
            except Exception:
                pass
        _fallback(stage, u'{0}\n\nWritten to {1}'.format(detail, path))


main()
