# -*- coding: utf-8 -*-
"""RevoBIM Tag Leader Elbow.

Select one or more tags, run the command, and every tag that already has a
leader gets an elbow set one leg length horizontally from its head, on the side
its leader already runs.  A tag with no leader is skipped and said so.  The tag
head itself is never moved.

Loads in stages and reports which stage failed, because a module that dies at
import time shows up in Revit as a blank white pyRevit window with no traceback
in it.
"""

import os
import sys
import traceback

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.append(_HERE)

_STAGE = "starting"


def _report(stage, error):
    text = "RevoBIM Tag Leader Elbow failed while {0}.\n\n{1}".format(stage, error)
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
        TaskDialog.Show("RevoBIM Tag Leader Elbow", text)
    except Exception:
        pass


def main():
    global _STAGE

    _STAGE = "referencing the assemblies"
    import tle_clr  # noqa: F401

    _STAGE = "loading the modules"
    import tle_core
    import tle_ops
    import tle_ui

    _STAGE = "reading the settings"
    cfg = tle_core.load_settings()

    _STAGE = "reading the document"
    uidoc = __revit__.ActiveUIDocument
    if uidoc is None or uidoc.Document is None:
        _report("reading the document", "No document is open.")
        return
    doc = uidoc.Document

    _STAGE = "collecting the tags"
    tags, others, message = tle_ops.gather_tags(uidoc, cfg)
    if not tags:
        if message and cfg.get("show_results") != "never":
            tle_ui.show_results(cfg, "Nothing to do", message, [], "")
        return

    _STAGE = "placing the elbows"
    rows, done, skipped, failed = tle_ops.plan_and_write(doc, tags, cfg)

    _STAGE = "reporting"
    show = cfg.get("show_results", "needed")
    needs_a_look = (skipped + failed) > 0
    if show == "never" or (show == "needed" and not needs_a_look):
        return

    view = tle_ops.view_of(doc, tags[0])
    scale = tle_ops.view_scale(view)
    summary = "{0} elbow{1} placed, {2} skipped, {3} refused".format(
        done, "" if done == 1 else "s", skipped, failed)
    detail = "Leg length {0}.  {1} tag{2} looked at{3}.".format(
        tle_core.describe_length(cfg, scale),
        len(tags), "" if len(tags) == 1 else "s",
        ", {0} selected element{1} were not tags".format(
            others, "" if others == 1 else "s") if others else "")
    status = "Nothing was written until this ran; one transaction, one undo step."
    tle_ui.show_results(cfg, summary, detail, [row.as_tuple() for row in rows], status)


if not os.environ.get("REVOBIM_IMPORT_CHECK"):
    try:
        main()
    except Exception:
        _report(_STAGE, traceback.format_exc())
