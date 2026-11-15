# -*- coding: utf-8 -*-
"""RevoBIM Tag Elbow Settings - the settings window for Tag Leader Elbow.

The modules live in the command button's own folder, because the Routines
pulldown is shared with other tools and nothing of ours belongs in it.
"""

import os
import sys
import traceback

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOL = os.path.join(os.path.dirname(_HERE), "RevoBIM Tag Leader Elbow.pushbutton")
for _path in (_TOOL, _HERE):
    if _path not in sys.path:
        sys.path.append(_path)

_STAGE = "starting"


def _report(stage, error):
    text = "RevoBIM Tag Elbow Settings failed while {0}.\n\n{1}".format(stage, error)
    try:
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        folder = os.path.join(base, "RevoBIM")
        if not os.path.isdir(folder):
            os.makedirs(folder)
        handle = open(os.path.join(folder, "tag_leader_elbow_last_error.txt"), "w")
        try:
            handle.write(text)
        finally:
            handle.close()
    except Exception:
        pass
    try:
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show("RevoBIM Tag Elbow Settings", text)
    except Exception:
        pass


def main():
    global _STAGE

    _STAGE = "finding the tool folder"
    if not os.path.isdir(_TOOL):
        _report("finding the tool folder",
                "The RevoBIM Tag Leader Elbow.pushbutton folder is not beside this "
                "one.  Both buttons have to sit in the same Routines pulldown.")
        return

    _STAGE = "referencing the assemblies"
    import tle_clr  # noqa: F401

    _STAGE = "loading the modules"
    import tle_core
    import tle_ui

    _STAGE = "reading the settings"
    cfg = tle_core.load_settings()

    _STAGE = "showing the window"
    window = tle_ui.SettingsWindow(cfg, __revit__)
    try:
        tle_ui.own_to_revit(window.window, __revit__)
    except Exception:
        pass
    window.show()


if not os.environ.get("REVOBIM_IMPORT_CHECK"):
    try:
        main()
    except Exception:
        _report(_STAGE, traceback.format_exc())
