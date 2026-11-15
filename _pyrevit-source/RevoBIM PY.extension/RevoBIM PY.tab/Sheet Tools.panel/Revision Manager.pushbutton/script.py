# -*- coding: utf-8 -*-
"""RevoBIM Revision Manager - the loader for its own ribbon button.

The Revision Manager is part of Pro Sheets Exporter and its code lives in
that button's folder, which keeps one copy of it and one version number
(Pro Sheets Exporter.pushbutton\\ps_version.py). This button only puts that
folder on the path and opens the manager on its own.

Thin and staged like the Pro Sheets loader: nothing at module level can fail,
and a failure names the stage it was on rather than leaving a blank window.
"""

__title__ = 'Revision\nManager'
__author__ = 'RevoBIM PY'
__doc__ = ('Manage the project\'s revisions: add, edit, reorder, merge and '
           'delete, with how many sheets use each one, a search on every '
           'column, and columns of your own such as Revision notes - pushed '
           'into sheet or revision cloud parameters if you map them.\n\n'
           'Opens modeless: Revit stays fully usable while it is open, and '
           'picking a revision cloud in a view takes the list to its '
           'revision.\n\n'
           'Nothing is written until Apply.')

# The window is modeless, so the engine has to survive the command
# returning. Without this the window opens and every handler in it is dead -
# including the Idling handler that follows the selection - which is
# indistinguishable from a broken tool.
__persistentengine__ = True

import os
import sys
import traceback


HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(os.path.dirname(HERE), 'Pro Sheets Exporter.pushbutton')
if TOOL not in sys.path:
    sys.path.append(TOOL)


def _fallback(stage, detail):
    text = u'RevoBIM Revision Manager stopped at "{0}".\n\n{1}'.format(
        stage, detail)
    try:
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show('RevoBIM Revision Manager', text[:3000])
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
        path = os.path.join(folder, 'revision_manager_last_error.txt')
        handle = open(path, 'wb')
        try:
            handle.write(text.encode('utf-8'))
        finally:
            handle.close()
        return path
    except Exception:
        return u'(the log file could not be written)'


def main():
    stage = 'finding Pro Sheets Exporter'
    reporter = None
    try:
        if not os.path.isdir(TOOL):
            raise Exception(u'The Revision Manager is part of Pro Sheets '
                            u'Exporter, expected at:\n{0}'.format(TOOL))
        stage = 'referencing assemblies'
        import ps_refs
        stage = 'loading the tool'
        import ps_ui
        reporter = ps_ui.report_failure
        import ps_revwin

        stage = 'finding the document'
        uiapp = __revit__                                      # noqa: F821
        if uiapp is None:
            raise Exception('Revit did not hand over a UIApplication.')
        uidoc = uiapp.ActiveUIDocument
        if uidoc is None or uidoc.Document is None:
            raise Exception('Open a project before running this tool.')
        if uidoc.Document.IsFamilyDocument:
            raise Exception('Revisions belong to projects, not families.')

        stage = 'running the Revision Manager'
        ps_revwin.run_standalone(uiapp)
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
