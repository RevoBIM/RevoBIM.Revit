# -*- coding: utf-8 -*-
"""RevoBIM Tag Tidy Settings - the settings window for Tag Tidy.

The modules live in the Tag Tidy pulldown folder, one level up, shared with the
command button.  The version lives in tidy_core.__version__.
"""

import os
import sys
import traceback

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOL = os.path.dirname(_HERE)
for _path in (_TOOL, _HERE):
    if _path not in sys.path:
        sys.path.append(_path)

_STAGE = "starting"


def _report(stage, error):
    text = "RevoBIM Tag Tidy Settings failed while {0}.\n\n{1}".format(stage, error)
    try:
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        folder = os.path.join(base, "RevoBIM")
        if not os.path.isdir(folder):
            os.makedirs(folder)
        handle = open(os.path.join(folder, "tag_tidy_last_error.txt"), "w")
        try:
            handle.write(text)
        finally:
            handle.close()
    except Exception:
        pass
    try:
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show("RevoBIM Tag Tidy Settings", text)
    except Exception:
        pass


def main():
    global _STAGE

    _STAGE = "finding the Tag Tidy modules"
    if not os.path.exists(os.path.join(_TOOL, "tidy_core.py")):
        _report(_STAGE, "tidy_core.py is not in the Tag Tidy.pulldown folder above this "
                        "button.  Copy the whole Tag Tidy.pulldown folder, not the button alone.")
        return

    _STAGE = "referencing the assemblies"
    import tidy_clr  # noqa: F401

    _STAGE = "loading the modules"
    import tidy_core
    import tidy_ui

    _STAGE = "reading the settings"
    cfg = tidy_core.load_settings()

    _STAGE = "showing the window"
    window = tidy_ui.SettingsWindow(cfg, __revit__)
    window.show()


if not os.environ.get("REVOBIM_IMPORT_CHECK"):
    try:
        main()
    except Exception:
        _report(_STAGE, traceback.format_exc())
