# -*- coding: utf-8 -*-
"""Link two runs at any rotation, slope or level, working out the route.

Opens no window. It reads the saved settings and goes straight to the picks,
so Revit's Keyboard Shortcuts dialog can bind keys to it - keys, click, click.
The name is prefixed RevoBIM so it can be found in that list; plain names
clash with other addins and cannot be picked out.

Settings live behind Link Settings in the same pulldown.
"""

__title__ = "RevoBIM Corner Link"
__author__ = "RevoBIM"

from pyrevit import revit, script

import mep_link_core as core

core.begin(revit.uidoc, script.get_logger())
settings = core.load_settings()

angle = core.setting_angle(settings, "corner_angle")

done, problems = core.run_pair_loop(
    lambda a, b: core.corner_link_pair(a, b, angle),
    "Corner Link - pick the FIRST element (Esc to finish)",
    "Corner Link - pick the SECOND element to turn into",
    "RevoBIM - Corner Link",
    settings.get("keep_going", "yes") == "yes")

core.report(done, problems, "Corners made", settings)
