# -*- coding: utf-8 -*-
"""Family Viewer - the dockable pane block.  NOT run on its own.

Paste everything below the line into the bottom of the extension's OWN
startup.py:

    RevoBIM PY.extension\\startup.py

then restart Revit.  pyRevit runs that file once at load, which is the only
moment Revit lets an addin register a dockable pane.

This used to ship AS that startup.py, at the extension root - and startup.py is
one shared file for the whole extension.  Merging a Family Viewer zip over it
replaced whatever else it was doing, the easter-egg attachment included,
without a word.  So it ships here, beside the tool, to be pasted in by hand.

The block needs `os`, `sys` and `traceback` imported above it; a startup.py that
does not import them already needs these three lines first:

    import os
    import sys
    import traceback

Without the block the tool still works: it opens as a floating window, and its
"Revit pane" chip explains how to turn the pane on.
"""

# ---- paste from here --------------------------------------------------------

# =========================================================================
# RevoBIM Family Viewer - dockable pane
# =========================================================================

def _register_family_viewer():
    folder = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        'RevoBIM PY.tab', 'Management.panel', 'Family Viewer.pushbutton')
    if not os.path.isdir(folder):
        return
    if folder not in sys.path:
        sys.path.append(folder)
    import fv_dock
    fv_dock.register(__revit__)                        # noqa: F821


try:
    _register_family_viewer()
except Exception:
    try:
        appdata = os.path.join(os.environ.get('APPDATA', ''), 'RevoBIM')
        if not os.path.isdir(appdata):
            os.makedirs(appdata)
        handle = open(os.path.join(appdata, 'startup_last_error.txt'), 'w')
        try:
            handle.write('Family Viewer dockable pane\n\n' +
                         traceback.format_exc())
        finally:
            handle.close()
    except Exception:
        pass

# =========================================================================
# end RevoBIM Family Viewer
# =========================================================================
