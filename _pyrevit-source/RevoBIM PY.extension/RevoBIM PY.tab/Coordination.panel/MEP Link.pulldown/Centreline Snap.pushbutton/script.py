# -*- coding: utf-8 -*-
"""Rotate an element parallel to another and set it on its centreline.

Opens no window. It reads the saved settings and goes straight to the picks,
so Revit's Keyboard Shortcuts dialog can bind keys to it - keys, click, click.
The name is prefixed RevoBIM so it can be found in that list; plain names
clash with other addins and cannot be picked out.

Settings live behind Link Settings in the same pulldown.
"""

__title__ = "RevoBIM Centreline Snap"
__author__ = "RevoBIM"

from pyrevit import revit, script

import mep_link_core as core

core.begin(revit.uidoc, script.get_logger())
settings = core.load_settings()

mode = settings.get("align_mode", "xy")

done, problems = core.run_pair_loop(
    lambda a, b: core.snap_pair(a, b, mode),
    "Centreline Snap - pick the element to align TO (Esc to finish)",
    "Centreline Snap - pick the element to MOVE",
    "RevoBIM - Centreline Snap",
    settings.get("keep_going", "yes") == "yes")

core.report(done, problems, "Snapped", settings)
