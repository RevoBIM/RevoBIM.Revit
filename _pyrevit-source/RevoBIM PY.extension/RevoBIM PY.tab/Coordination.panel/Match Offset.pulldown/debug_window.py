# -*- coding: utf-8 -*-
"""RevoBIM Match Offset - the debug report window.

Opens after a run while the debug tick is on. The whole report is in a
selectable box with a Copy button, because the useful thing to do with it is
paste it somewhere, and it is written to disk as well so closing the window
does not throw it away.
"""

import mo_clr  # noqa: F401

import os

from System.Windows import Clipboard

import mo_debug
import mo_ui
from mo_core import appdata_dir, log, to_text


def show(recorder, settings):
    if recorder is None:
        return
    text = recorder.text()
    path = recorder.save()

    window = mo_ui.load_window('MatchOffsetDebug.xaml',
                               settings.get(u"theme", u"auto"))
    mo_ui.wire_header(window, settings)
    mo_ui.add_resize_grips(window)

    window.FindName('DebugText').Text = text
    window.FindName('DebugLead').Text = (
        u"{0} ran, {1} matched, {2} to look at. Press Copy and paste the lot "
        u"into the chat - it carries the settings, the geometry and Revit's "
        u"own words. Turn it off under Settings > Picking and shortcuts > "
        u"Diagnostics.".format(recorder.tool, recorder.matched,
                               recorder.problems))
    window.FindName('StatusText').Text = (
        path if path else u"the report could not be written to disk")

    def copy(sender, args):
        try:
            Clipboard.SetText(text)
            window.FindName('StatusText').Text = u"Copied. Paste it anywhere."
        except Exception as err:
            window.FindName('StatusText').Text = (
                u"The clipboard refused it: {0}. The file is at {1}".format(
                    to_text(err), path))
    window.FindName('CopyButton').Click += copy

    def reveal(sender, args):
        try:
            os.startfile(appdata_dir())
        except Exception:
            window.FindName('StatusText').Text = path or appdata_dir()
    window.FindName('SaveButton').Click += reveal

    def close(sender, args):
        window.Close()
    window.FindName('DoneButton').Click += close

    log(u"debug report shown, {0} lines".format(len(recorder.lines)))
    window.ShowDialog()


def file_path():
    return os.path.join(appdata_dir(), mo_debug.DEBUG_FILE)
