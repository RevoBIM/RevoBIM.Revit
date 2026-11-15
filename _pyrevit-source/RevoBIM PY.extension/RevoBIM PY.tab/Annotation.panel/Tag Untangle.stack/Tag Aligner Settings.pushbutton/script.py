# -*- coding: utf-8 -*-
"""Settings for Tag Align and Tag Untangle: what to align to, untangle spacing (text height rule), leader elbows, pinned tags, results window, theme."""
# Thin loader. Everything lives in lib\revobim\tagaligner (shared by the six
# Tag Aligner buttons); the version is ta_core.__version__.
import os
import sys


def _lib_folder():
    folder = os.path.dirname(os.path.abspath(__file__))
    for _ in range(8):
        if folder.lower().endswith(".extension"):
            return os.path.join(folder, "lib", "revobim", "tagaligner")
        folder = os.path.dirname(folder)
    return None


_LIB = _lib_folder()
if _LIB and _LIB not in sys.path:
    sys.path.insert(0, _LIB)

try:
    import ta_run
except Exception:
    import traceback
    from Autodesk.Revit.UI import TaskDialog
    TaskDialog.Show(u"RevoBIM Tag Aligner",
                    u"Could not load Tag Aligner from:\n{0}\n\n{1}".format(
                        _LIB, traceback.format_exc()))
else:
    ta_run.main(u"settings", __revit__)
