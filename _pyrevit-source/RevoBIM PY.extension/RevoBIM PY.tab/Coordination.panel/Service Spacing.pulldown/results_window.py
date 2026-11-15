# -*- coding: utf-8 -*-
"""RevoBIM PY - Service Spacing : themed results window."""

import os
import clr

for assembly in ("PresentationCore", "PresentationFramework", "WindowsBase",
                 "System.Xml"):
    try:
        clr.AddReference(assembly)
    except Exception:
        pass

from System.IO import StringReader, MemoryStream, File
from System.Xml import XmlReader
from System.Windows import Window, Visibility
from System.Windows.Markup import XamlReader
from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption

import service_spacing_core as core

HERE = os.path.dirname(__file__)
XAML_PATH = os.path.join(HERE, "ServiceSpacingResults.xaml")
ICON_PATH = os.path.join(HERE, "icon.png")


def _load_icon(image_control):
    """Load from bytes, never from BitmapImage.UriSource - System.Uri moved
    assemblies and throws at module load on Revit 2025+."""
    try:
        if not os.path.isfile(ICON_PATH):
            return
        bitmap = BitmapImage()
        bitmap.BeginInit()
        bitmap.StreamSource = MemoryStream(File.ReadAllBytes(ICON_PATH))
        bitmap.CacheOption = BitmapCacheOption.OnLoad
        bitmap.EndInit()
        image_control.Source = bitmap
    except Exception:
        pass


def _table(result, settings):
    header = "{0:<5}{1:<32}{2:>9}{3:>16}{4:>11}{5:>9}{6:>8}".format(
        "Row", "Service", "Half w", "Gap", "Centre-cen", "Moved", "Lift")
    lines = [header, "-" * len(header)]

    previous_row = None
    for row in result.rows:
        label = row.label
        if len(label) > 31:
            label = label[:28] + "..."
        new_row = (previous_row is not None and row.row != previous_row)
        previous_row = row.row
        if new_row:
            lines.append("")
        if new_row or row.spacing <= 0.0:
            spacing = "-"
            gap = "-"
        else:
            spacing = core.fmt(row.spacing, 1)
            gap = core.fmt(row.gap, 0) + " (" + (row.gap_label or "-") + ")"
        lines.append("{0:<5}{1:<32}{2:>9}{3:>16}{4:>11}{5:>9}{6:>8}".format(
            row.row + 1, label, core.fmt(row.half, 1), gap, spacing,
            core.fmt(row.move, 1), core.fmt(row.lift, 1)))
        if row.carried:
            lines.append("     carries {0} connected element(s) with it".format(
                row.carried))

    lines.append("")
    lines.append("All values in millimetres.  Centre to centre is "
                 "(w1 + w2 + clear gap) rounded up to " +
                 core.fmt(settings.number("round_to")) + "mm.")
    lines.append("Clear gaps: service " + core.fmt(settings.number("gap_services")) +
                 ", cable tray " + core.fmt(settings.number("gap_containment")) +
                 ", trunking " + core.fmt(settings.number("gap_trunking")) + ".")
    if result.row_count > 1:
        lines.append("Rows split at more than " +
                     core.fmt(settings.number("row_clear_mm")) +
                     "mm top edge to bottom edge.")
    return "\n".join(lines)


def show_results(result, settings, owner_handle=None):
    xaml = None
    try:
        handle = open(XAML_PATH, "r")
        try:
            xaml = handle.read()
        finally:
            handle.close()
    except Exception:
        return

    try:
        if not isinstance(xaml, type(u"")):
            xaml = xaml.decode("utf-8")
        window = XamlReader.Load(XmlReader.Create(StringReader(xaml)))
    except Exception:
        return

    try:
        _load_icon(window.FindName("HeaderIcon"))
    except Exception:
        pass

    try:
        window.FindName("VersionText").Text = "v" + core.__version__
    except Exception:
        pass

    try:
        summary = ("{0} service(s) in {1} row(s), spaced along the {2} "
                   "axis.  {3} moved.").format(
            len(result.rows), result.row_count, result.axis_label,
            result.moved)
        window.FindName("SummaryText").Text = summary
        window.FindName("TableText").Text = _table(result, settings)
    except Exception:
        pass

    notes = list(result.notes) + list(result.skipped)
    if notes:
        try:
            window.FindName("NotesText").Text = "\n".join(
                [u"\u2022  " + str(note) for note in notes])
            window.FindName("NotesHeader").Visibility = Visibility.Visible
            window.FindName("NotesBox").Visibility = Visibility.Visible
        except Exception:
            pass

    try:
        window.FindName("StatusText").Text = (
            "Nothing needed a look." if not notes
            else str(len(notes)) + " item(s) need a look")
    except Exception:
        pass

    def _drag(sender, args):
        try:
            window.DragMove()
        except Exception:
            pass

    def _close(sender, args):
        try:
            window.Close()
        except Exception:
            pass

    try:
        window.FindName("HeaderBar").MouseLeftButtonDown += _drag
        window.FindName("CloseBtn").Click += _close
        window.FindName("OkBtn").Click += _close
    except Exception:
        pass

    try:
        window.ShowDialog()
    except Exception:
        pass
