# -*- coding: utf-8 -*-
"""RevoBIM Tag Tidy.

Select a set of tags, run the command, and they are tidied into a neat column
one under another beside the elements they tag, with level shoulders and 45
degree leaders.  Anything a tag or a leader would land on is avoided where a
clear position can be found nearby; anything that cannot be cleared is
reported by name.

The modules live in the Tag Tidy pulldown folder, one level up, shared with the
settings button.  Loads in stages and reports which stage failed, because a
module that dies at import time shows up in Revit as a blank white pyRevit
window with no traceback in it.  The version lives in tidy_core.__version__.
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
    text = "RevoBIM Tag Tidy failed while {0}.\n\n{1}".format(stage, error)
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
        TaskDialog.Show("RevoBIM Tag Tidy", text)
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
    import tidy_ops
    import tidy_ui

    _STAGE = "reading the settings"
    cfg = tidy_core.load_settings()

    _STAGE = "reading the document"
    uidoc = __revit__.ActiveUIDocument
    if uidoc is None or uidoc.Document is None:
        _report("reading the document", "No document is open.")
        return

    _STAGE = "collecting the tags"
    tags, others, message = tidy_ops.gather_tags(uidoc, cfg)
    if not tags:
        if message:
            tidy_ui.show_results(cfg, "Nothing to do", message, [], "",
                                 can_flip=False, final=True, uiapp=__revit__)
        return

    _STAGE = "tidying the tags"
    ui = tidy_ui.Presenter(__revit__)
    tidy_ops.run(uidoc, tags, others, cfg, ui)


if not os.environ.get("REVOBIM_IMPORT_CHECK"):
    try:
        main()
    except Exception:
        _report(_STAGE, traceback.format_exc())
