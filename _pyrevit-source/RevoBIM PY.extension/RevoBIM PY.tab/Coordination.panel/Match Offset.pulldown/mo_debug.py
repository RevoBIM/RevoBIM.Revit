# -*- coding: utf-8 -*-
"""RevoBIM Match Offset - the debug report.

A run collects what it did into one of these, and the window at the end puts
it on the clipboard. It is here because "Revit did not commit the move" is not
a diagnosis: the numbers that produced the move, the case the geometry was
classified as, and Revit's own words about why it refused are all known at the
time and all thrown away unless something writes them down.

Nothing in here touches Revit or WPF, so the bench exercises the whole of it.
"""

import datetime

from mo_core import (
    DEFAULTS, MM_PER_FT, __version__, appdata_dir, ensure_dir, to_text,
)

DEBUG_FILE = u"match_offset_debug.txt"


def mm(value_ft, places=1):
    """Internal feet as millimetres, which is how it is read on a drawing."""
    try:
        return u"{0:.{1}f}".format(float(value_ft) * MM_PER_FT, places)
    except Exception:
        return u"?"


def pt(point, places=1):
    if point is None:
        return u"none"
    try:
        return u"({0}, {1}, {2}) mm".format(mm(point.x, places),
                                            mm(point.y, places),
                                            mm(point.z, places))
    except Exception:
        return to_text(point)


def fall(grad):
    """A gradient the way it gets said out loud."""
    if grad is None:
        return u"none"
    try:
        value = float(grad)
    except Exception:
        return to_text(grad)
    if abs(value) < 1e-7:
        return u"level"
    return u"1 in {0:.1f} {1} ({2:+.6f})".format(
        1.0 / abs(value), u"falling" if value < 0 else u"rising", value)


class Recorder(object):
    """Lines, in order, with the numbers in them."""

    def __init__(self, tool=u"Match Offset"):
        self.tool = tool
        self.lines = []
        self.failures = []
        self.exceptions = []
        self.started = datetime.datetime.now()
        self.matched = 0
        self.problems = 0

    # ------------------------------------------------------------------
    def section(self, title):
        self.lines.append(u"")
        self.lines.append(u"== {0} ".format(to_text(title)).ljust(66, u"="))

    def line(self, text=u""):
        self.lines.append(to_text(text))

    def pair(self, key, value):
        self.lines.append(u"  {0:<34}{1}".format(
            to_text(key), to_text(value)))

    def failure(self, severity, description):
        """One of Revit's own failure messages, in Revit's own words."""
        text = u"{0}: {1}".format(to_text(severity), to_text(description))
        self.failures.append(text)
        self.lines.append(u"  REVIT SAID  {0}".format(text))

    def blew_up(self, where, detail):
        text = u"{0}\n{1}".format(to_text(where), to_text(detail))
        self.exceptions.append(text)
        self.lines.append(u"  THREW       {0}".format(to_text(where)))
        for piece in to_text(detail).splitlines():
            self.lines.append(u"              {0}".format(piece))

    # ------------------------------------------------------------------
    def header(self, uiapp, doc, settings):
        self.section(u"run")
        self.pair(u"tool", self.tool)
        self.pair(u"version", __version__)
        self.pair(u"when", self.started.strftime('%Y-%m-%d %H:%M:%S'))
        try:
            self.pair(u"Revit", u"{0} build {1}".format(
                to_text(uiapp.Application.VersionNumber),
                to_text(uiapp.Application.VersionBuild)))
        except Exception:
            self.pair(u"Revit", u"could not be read")
        try:
            self.pair(u"document", to_text(doc.Title))
            self.pair(u"workshared", to_text(doc.IsWorkshared))
        except Exception:
            self.pair(u"document", u"could not be read")

        self.section(u"settings")
        for key in sorted(DEFAULTS.keys()):
            value = to_text(settings.get(key, u""))
            mark = u"" if value == to_text(DEFAULTS[key]) else u"   <- changed"
            if key == u"categories":
                value = u"{0} categories".format(
                    len(value.split(u"|")) if value else 0)
                mark = u""
            self.pair(key, value + mark)

    def tail(self, report):
        self.matched = report.matched
        self.problems = len(report.problems)
        self.section(u"result")
        self.pair(u"matched", report.matched)
        self.pair(u"problems", len(report.problems))
        for text in report.problems:
            self.line(u"  PROBLEM     {0}".format(text))
        for text in report.notes:
            self.line(u"  note        {0}".format(text))
        if self.failures:
            self.pair(u"Revit failures", len(self.failures))
        self.line()
        self.line(u"Copy all of this and send it over.")

    # ------------------------------------------------------------------
    def text(self):
        return u"\n".join(self.lines) + u"\n"

    def save(self):
        """Also on disk, because a window that is closed is a report lost."""
        try:
            import os
            ensure_dir()
            path = os.path.join(appdata_dir(), DEBUG_FILE)
            handle = open(path, 'wb')
            try:
                handle.write(self.text().encode('utf-8'))
            finally:
                handle.close()
            return path
        except Exception:
            return u""
