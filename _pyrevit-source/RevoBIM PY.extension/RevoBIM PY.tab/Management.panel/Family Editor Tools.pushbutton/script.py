# =========================================================================
# RevoBIM PY - Family Editor Tools
#
# A thin loader.  The tool lives in the modules beside this file, so an
# import failure arrives as a dialog naming the stage rather than as a
# blank white pyRevit window with no traceback in it.
# =========================================================================

__title__ = "Family Editor Tools"
__author__ = "RevoBIM"
__doc__ = ("Family editor companion: load shared parameters from a file or a "
           "saved template, preload materials, line styles and annotation "
           "styles, and set a family out on standard reference planes.\n\n"
           "Only works inside the family editor.")
__persistentengine__ = True

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.append(HERE)

_STAGE = u"starting"
_PARK_KEY = None


def _report(stage, detail):
    u"""Every stage reports where it failed, into a Revit dialog and into
    a file, because the alternative is a window that never appears."""
    text = u"Family Editor Tools could not start.\n\nStage: {0}\n\n{1}".format(
        stage, detail)
    try:
        from fet_core import appdata_root, ensure_dir
        ensure_dir(appdata_root())
        handle = open(os.path.join(appdata_root(),
                                   u"fet_last_error.txt"), u"wb")
        try:
            handle.write(text.encode(u"utf-8"))
        finally:
            handle.close()
    except Exception:
        pass
    try:
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show(u"RevoBIM Family Editor Tools", text)
    except Exception:
        pass


def main():
    global _STAGE, _PARK_KEY

    # ----- stage 1: assemblies ---------------------------------------
    _STAGE = u"referencing assemblies"
    import fet_clr  # noqa: F401

    # ----- stage 2: modules ------------------------------------------
    _STAGE = u"loading the tool's modules"
    import fet_core
    import fet_model
    import fet_window

    _PARK_KEY = u"RevoBIM.FamilyEditorTools.{0}".format(fet_core.__version__)

    # ----- stage 3: the document -------------------------------------
    _STAGE = u"reading the document"
    uiapp = __revit__  # noqa: F821  - pyRevit hands this in
    uidoc = getattr(uiapp, u"ActiveUIDocument", None)
    doc = getattr(uidoc, u"Document", None) if uidoc else None

    if doc is None:
        _report(_STAGE, u"There is no open document.")
        return

    if not fet_model.is_family(doc):
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show(
            u"RevoBIM Family Editor Tools",
            u"This tool runs inside the family editor.\n\n"
            u"Open a family - or select a family in the project and press "
            u"Edit Family - and run it again.")
        return

    # ----- stage 4: the window ---------------------------------------
    _STAGE = u"building the window"
    settings = fet_core.load_settings()

    if fet_window.handlers_were_dead():
        # The window was opened last time and nothing in it ever ran.
        # Nothing inside a dead window can report that, so it is reported
        # here, at the next launch.
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show(
            u"RevoBIM Family Editor Tools",
            u"Last time this window opened, none of its buttons responded.\n\n"
            u"That means pyRevit tore the engine down underneath it. Restart "
            u"Revit before relying on it, and tell Drew if it keeps happening.")

    existing = _parked()
    if existing is not None:
        try:
            existing.window.Activate()
            return
        except Exception:
            _park(None)

    window = fet_window.MainWindow(uiapp, settings)
    _park(window)

    _STAGE = u"showing the window"
    window.show()


def _domain():
    try:
        from System import AppDomain
        return AppDomain.CurrentDomain
    except Exception:
        return None


def _parked():
    u"""Parked in the AppDomain under a version stamped key, so an upgrade
    cannot pick up an orphaned window built by the old code."""
    domain = _domain()
    if domain is None or _PARK_KEY is None:
        return None
    try:
        found = domain.GetData(_PARK_KEY)
    except Exception:
        return None
    if found is None:
        return None
    try:
        if found.window.IsVisible:
            return found
    except Exception:
        return None
    return None


def _park(window):
    domain = _domain()
    if domain is None or _PARK_KEY is None:
        return
    try:
        domain.SetData(_PARK_KEY, window)
    except Exception:
        pass


try:
    main()
except Exception:
    _report(_STAGE, traceback.format_exc())
