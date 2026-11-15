# -*- coding: utf-8 -*-
u"""Project Browser Pro - a dockable project browser with more in it.

Thin, staged loader. Shows the docked browser when the startup block has
registered the panes; otherwise opens the same browser as a floating window.
Each stage reports which stage failed, so a broken load is a message naming
the stage and line rather than a blank window.
"""
__title__ = 'Project Browser Pro'
__persistentengine__ = True

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.append(HERE)


def _report(stage):
    text = traceback.format_exc()
    try:
        folder = os.path.join(os.environ.get('APPDATA') or HERE, 'RevoBIM')
        if not os.path.isdir(folder):
            os.makedirs(folder)
        with open(os.path.join(folder, 'project_browser_pro_load_error.txt'), 'w') as handle:
            handle.write(stage + '\n' + text)
    except Exception:
        pass
    try:
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show('RevoBIM Project Browser Pro',
                        'Could not start at stage: {0}\n\n{1}'.format(stage, text[-1500:]))
    except Exception:
        pass


def main():
    stage = 'assemblies'
    try:
        import pbp_clr  # noqa: F401
        stage = 'modules'
        import pbp_log
        import pbp_dock
        import pbp_runner
        uiapp = __revit__  # noqa: F821  (pyRevit's UIApplication)
        stage = 'dockable pane'
        if pbp_dock.show_main(uiapp):
            pbp_log.log('button: showed the main pane')
            import pbp_version
            note = pbp_dock.stale_note(pbp_version.__version__)
            if note:
                import pbp_ui
                import pbp_theme
                pbp_ui.message('Restart Revit to update', note, pbp_theme.resolve('follow'))
            return
        stage = 'floating window'
        pbp_runner.get().ensure_event()
        pbp_dock.hook_events(uiapp)
        import pbp_window
        pbp_window.open_floating(None)
        pbp_log.log('button: panes not registered, opened the floating window')
    except Exception:
        _report(stage)


main()
