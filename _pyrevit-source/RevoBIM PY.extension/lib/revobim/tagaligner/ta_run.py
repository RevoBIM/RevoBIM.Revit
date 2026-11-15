# -*- coding: utf-8 -*-
"""Tag Aligner: what every ribbon button calls.

Loads in stages and names the stage that failed, in a Revit TaskDialog and in
%APPDATA%\\RevoBIM\\tag_aligner_error.txt, so a broken load is a message with
a traceback rather than a blank pyRevit window.

The five tag commands open no window: they read the saved settings, act on
the selection, and only show the themed results window when something needs
a look (Settings decides). That keeps them fast enough to bind to keys.
"""
import os
import traceback

COMMANDS = (u"align_left", u"align_centre", u"align_right",
            u"untangle_v", u"untangle_h", u"settings")


def _write_error(text):
    try:
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        folder = os.path.join(base, "RevoBIM")
        if not os.path.isdir(folder):
            os.makedirs(folder)
        import codecs
        with codecs.open(os.path.join(folder, "tag_aligner_error.txt"),
                         "w", "utf-8") as handle:
            handle.write(text)
    except Exception:
        pass


def _fail(stage):
    text = u"RevoBIM Tag Aligner stopped while {0}.\n\n{1}".format(
        stage, traceback.format_exc())
    _write_error(text)
    try:
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show(u"RevoBIM Tag Aligner", text[-2000:])
    except Exception:
        pass


def main(command, uiapp):
    stage = u"loading assemblies"
    try:
        import ta_clr  # noqa: F401
        stage = u"loading modules"
        import ta_core as core
        import ta_model  # noqa: F401
        import ta_ops
        import ta_ui
        stage = u"reading settings"
        settings = core.load_settings()
        if command == u"settings":
            stage = u"opening the settings window"
            ta_ui.show_settings(uiapp)
            return
        if command not in COMMANDS:
            raise ValueError(u"unknown command {0}".format(command))
        stage = u"reading the active view"
        uidoc = uiapp.ActiveUIDocument
        if uidoc is None:
            return
        log = core.DebugLog(settings[u"debug"])
        stage = u"moving the tags"
        report = ta_ops.run(uidoc, command, settings, log)
        log_path = log.write()
        stage = u"showing the results"
        if report.should_show(settings[u"show_results"]):
            ta_ui.show_results(uiapp, report, log_path)
    except Exception:
        _fail(stage)
