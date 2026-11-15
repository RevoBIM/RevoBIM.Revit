# -*- coding: utf-8 -*-
"""RevoBIM PY - Schematic Builder.

Builds MEP schematics in drafting views: level lines, equipment as detail
items clustered by room, room boxes and labels. Tabs for each schematic
type; Settings for the standards shared by all of them.
"""
__title__ = "Schematic Builder"
__author__ = "RevoBIM PY"
__doc__ = "Build MEP schematics in drafting views: level lines, equipment detail items clustered by room."
__persistentengine__ = True

import os
import sys
import traceback

HERE = os.path.dirname(__file__)
if HERE not in sys.path:
    sys.path.insert(0, HERE)


def _show(title, body):
    """A dialog that works before any of our modules have loaded."""
    try:
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show(title, body)
    except Exception:
        try:
            from pyrevit import forms
            forms.alert(body, title=title)
        except Exception:
            pass


def _stage(name, func):
    try:
        return func()
    except Exception:
        detail = traceback.format_exc()
        body = None
        try:
            import sb_core
            body = sb_core.write_error(name, detail)
        except Exception:
            body = detail
        _show("RevoBIM PY - Schematic Builder",
              "Could not start ({0}).\n\n{1}".format(name, body[-1800:]))
        return None


def _load_modules():
    import sb_clr  # noqa: F401  assemblies first
    import sb_logic
    import sb_core
    import sb_model
    import sb_ops
    import sb_window
    return sb_logic, sb_core, sb_model, sb_ops, sb_window


def main():
    modules = _stage("load modules", _load_modules)
    if modules is None:
        return
    sb_logic, sb_core, sb_model, sb_ops, sb_window = modules

    uidoc = __revit__.ActiveUIDocument  # noqa: F821
    if uidoc is None or uidoc.Document is None:
        _show("RevoBIM PY - Schematic Builder", "Open a project first.")
        return
    doc = uidoc.Document

    def read():
        return sb_model.read_project(doc)
    model = _stage("read model", read)
    if model is None:
        return

    def make_event():
        from System import AppDomain
        from Autodesk.Revit.UI import ExternalEvent
        domain = AppDomain.CurrentDomain
        key = "RevoBIM.SchematicBuilder.{0}".format(sb_logic.__version__)
        # close a window left over from an earlier launch
        old = domain.GetData(key + ".window")
        if old is not None:
            try:
                old.window.Close()
            except Exception:
                pass
        handler = sb_ops.SchematicHandler()
        event = ExternalEvent.Create(handler)
        domain.SetData(key + ".handler", handler)
        domain.SetData(key + ".event", event)
        return domain, key, handler, event
    made = _stage("external event", make_event)
    if made is None:
        return
    domain, key, handler, event = made

    def open_window():
        settings = sb_logic.load_settings()
        window = sb_window.MainWindow(uidoc, settings, model, handler, event)
        domain.SetData(key + ".window", window)
        window.show()
        return window
    _stage("open window", open_window)


main()
