# -*- coding: utf-8 -*-
"""RevoBIM Smart Dimensions - the command.

Opens no window. It reads the saved settings and goes straight to the picks:

    services (or whatever was already selected)
      -> optional linked walls / columns, Enter to complete
      -> one click for the dimension line
      -> one continuous dimension string

Because it is a single command button with a unique ribbon name, Revit's own
Keyboard Shortcuts dialog can bind keys to it: View > User Interface >
Keyboard Shortcuts, search "RevoBIM Smart Dimensions".
"""

__title__ = "RevoBIM\nSmart Dimensions"
__author__ = "RevoBIM"

import os
import sys
import traceback

# the shared core sits in the pulldown folder beside this button
_HERE = os.path.dirname(__file__)
_PULLDOWN = os.path.dirname(_HERE)
if _PULLDOWN not in sys.path:
    sys.path.append(_PULLDOWN)

_LOAD_ERROR = None
core = None
try:
    import smart_dimensions_core as core
except Exception:
    _LOAD_ERROR = traceback.format_exc()

__version__ = getattr(core, "__version__", "1.0.0") if core else "1.0.0"


def _uidoc_and_uiapp():
    uidoc = None
    uiapp = None
    try:
        from pyrevit import HOST_APP

        uiapp = HOST_APP.uiapp
        uidoc = HOST_APP.uidoc
    except Exception:
        pass
    if uiapp is None:
        try:
            uiapp = __revit__  # noqa: F821  (pyRevit injects this)
        except Exception:
            uiapp = None
    if uidoc is None and uiapp is not None:
        try:
            uidoc = uiapp.ActiveUIDocument
        except Exception:
            uidoc = None
    return uidoc, uiapp


def _show(title, lines, tone="warn"):
    """Themed report window. Falls back to a TaskDialog only if WPF fails."""
    try:
        import results_window

        results_window.show(title, lines, tone, __version__, _PULLDOWN)
        return
    except Exception:
        pass
    try:
        from Autodesk.Revit.UI import TaskDialog

        TaskDialog.Show("RevoBIM Smart Dimensions", "\n".join(lines))
    except Exception:
        pass


def main():
    if _LOAD_ERROR is not None:
        _show(
            "Smart Dimensions could not start",
            [
                "The shared module smart_dimensions_core.py failed to load.",
                "",
                _LOAD_ERROR,
            ],
        )
        return

    uidoc, uiapp = _uidoc_and_uiapp()
    if uidoc is None or uiapp is None:
        _show("Smart Dimensions", ["No active Revit document."])
        return

    settings = core.load_settings()

    try:
        report = core.run(uidoc, uiapp, settings)
    except Exception:
        _show(
            "Smart Dimensions stopped",
            ["Something went wrong before anything was placed.", "", traceback.format_exc()],
        )
        return

    mode = settings.get("results", "issues")
    if mode == "never":
        return
    if mode == "issues" and not report.needs_a_look:
        return
    if report.cancelled and not report.needs_a_look and report.placed == 0:
        return

    lines = []
    if report.placed:
        lines.append(
            "{0} dimension string{1} placed, {2} references, {3} service{4}"
            "{5}.".format(
                report.placed,
                "" if report.placed == 1 else "s",
                report.references,
                report.services,
                "" if report.services == 1 else "s",
                ", {0} linked element{1}".format(
                    report.links, "" if report.links == 1 else "s"
                )
                if report.links
                else "",
            )
        )
        if report.pulled:
            lines.append(
                "{0} small dimension{1} leadered out clear of the string.".format(
                    report.pulled, "" if report.pulled == 1 else "s"
                )
            )
    if report.error:
        lines.append("")
        lines.append(report.error)
    if report.issues:
        lines.append("")
        lines.append("Left out:")
        for issue in report.issues:
            lines.append("  - " + issue)
    if report.notes:
        lines.append("")
        lines.append("Worth knowing:")
        for note in report.notes:
            lines.append("  - " + note)
    if not lines:
        lines.append("Nothing to report.")

    _show("Smart Dimensions", lines, "warn" if report.needs_a_look else "ok")


main()
