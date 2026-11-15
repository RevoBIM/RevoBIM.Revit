# -*- coding: utf-8 -*-
"""RevoBIM Service Spacing Settings - standalone, modal.

Set them, press Apply, and they are written to
%APPDATA%\\RevoBIM\\service_spacing.txt; every later run uses them.
"""

__title__ = "RevoBIM Service Spacing Settings"
__author__ = "RevoBIM PY"

import os
import sys
import clr
import traceback

HERE = os.path.dirname(__file__)
PARENT = os.path.dirname(HERE)
if PARENT not in sys.path:
    sys.path.append(PARENT)

try:
    import service_spacing_core as core
except Exception:
    from pyrevit import forms as _forms
    _forms.alert("Service Spacing Settings could not load its shared "
                 "module.\n\n" + traceback.format_exc(),
                 title="RevoBIM Service Spacing")
    raise

for assembly in ("PresentationCore", "PresentationFramework", "WindowsBase",
                 "System.Xml"):
    try:
        clr.AddReference(assembly)
    except Exception:
        pass

from System.IO import StringReader, MemoryStream, File
from System.Xml import XmlReader
from System.Windows.Markup import XamlReader
from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption
from System.Diagnostics import Process, ProcessStartInfo

__version__ = core.__version__

XAML_PATH = os.path.join(PARENT, "ServiceSpacingSettings.xaml")
ICON_PATH = os.path.join(PARENT, "icon.png")

AXIS = ["auto", "horizontal", "vertical"]
ANCHOR = ["first_along_axis", "first_selected", "largest"]
ORDER = ["spatial", "selection"]
MIXED = ["larger", "services", "containment"]
SHOW = ["auto", "always", "never"]


def _index(options, value):
    try:
        return options.index(value)
    except Exception:
        return 0


def _load_icon(image_control):
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


def build_window():
    handle = open(XAML_PATH, "r")
    try:
        xaml = handle.read()
    finally:
        handle.close()
    if not isinstance(xaml, type(u"")):
        xaml = xaml.decode("utf-8")
    return XamlReader.Load(XmlReader.Create(StringReader(xaml)))


def to_window(window, settings):
    window.FindName("GapServices").Text = settings.text("gap_services")
    window.FindName("GapContainment").Text = settings.text("gap_containment")
    window.FindName("GapTrunking").Text = settings.text("gap_trunking")
    window.FindName("TrunkingToken").Text = settings.text("trunking_token")
    window.FindName("RoundTo").Text = settings.text("round_to")
    window.FindName("RowClear").Text = settings.text("row_clear_mm")
    window.FindName("AngleTolerance").Text = settings.text("angle_tolerance_deg")
    window.FindName("MaxRun").Text = settings.text("max_run_elements")

    window.FindName("MixedGap").SelectedIndex = _index(
        MIXED, settings.text("mixed_gap"))
    window.FindName("SpacingAxis").SelectedIndex = _index(
        AXIS, settings.text("spacing_axis"))
    window.FindName("Anchor").SelectedIndex = _index(
        ANCHOR, settings.text("anchor"))
    window.FindName("Order").SelectedIndex = _index(
        ORDER, settings.text("order"))
    window.FindName("ShowResults").SelectedIndex = _index(
        SHOW, settings.text("show_results"))

    window.FindName("IncludeInsulation").IsChecked = settings.flag(
        "include_insulation")
    window.FindName("TrunkingGapWins").IsChecked = settings.flag(
        "trunking_gap_wins")
    window.FindName("RowSplit").IsChecked = settings.flag("row_split")
    window.FindName("SpaceRows").IsChecked = settings.flag("space_rows")
    window.FindName("MoveRun").IsChecked = settings.flag("move_run")
    window.FindName("Unpin").IsChecked = settings.flag("unpin")


def _number(window, name, fallback, minimum=0.0):
    """A value that will not parse falls back and is said in the status line,
    so a typo shows up straight away rather than silently doing nothing."""
    try:
        value = float(window.FindName(name).Text.strip())
        if value < minimum:
            return fallback, False
        return value, True
    except Exception:
        return fallback, False


def from_window(window, settings):
    complaints = []

    pairs = [
        ("GapServices", "gap_services", 0.0),
        ("GapContainment", "gap_containment", 0.0),
        ("GapTrunking", "gap_trunking", 0.0),
        ("RowClear", "row_clear_mm", 0.0),
        ("RoundTo", "round_to", 0.0),
        ("AngleTolerance", "angle_tolerance_deg", 0.0),
        ("MaxRun", "max_run_elements", 1.0),
    ]
    for control, key, minimum in pairs:
        fallback = float(core.DEFAULTS[key])
        value, ok = _number(window, control, fallback, minimum)
        if not ok:
            complaints.append(key)
        if key == "max_run_elements":
            settings.set(key, int(value))
        else:
            settings.set(key, core.fmt(value, 1).rstrip("0").rstrip("."))

    settings.set("mixed_gap", MIXED[max(0, window.FindName("MixedGap").SelectedIndex)])
    settings.set("spacing_axis", AXIS[max(0, window.FindName("SpacingAxis").SelectedIndex)])
    settings.set("anchor", ANCHOR[max(0, window.FindName("Anchor").SelectedIndex)])
    settings.set("order", ORDER[max(0, window.FindName("Order").SelectedIndex)])
    settings.set("show_results", SHOW[max(0, window.FindName("ShowResults").SelectedIndex)])

    token = window.FindName("TrunkingToken").Text.strip()
    if not token:
        token = core.DEFAULTS["trunking_token"]
        complaints.append("trunking_token")
    settings.set("trunking_token", token)

    settings.set("include_insulation",
                 1 if window.FindName("IncludeInsulation").IsChecked else 0)
    settings.set("trunking_gap_wins",
                 1 if window.FindName("TrunkingGapWins").IsChecked else 0)
    settings.set("row_split", 1 if window.FindName("RowSplit").IsChecked else 0)
    settings.set("space_rows",
                 1 if window.FindName("SpaceRows").IsChecked else 0)
    settings.set("move_run", 1 if window.FindName("MoveRun").IsChecked else 0)
    settings.set("unpin", 1 if window.FindName("Unpin").IsChecked else 0)
    return complaints


def open_shortcuts():
    """Revit's own Keyboard Shortcuts dialog lives under
    View > User Interface; the file behind it is opened here so the command
    can be bound by name."""
    try:
        path = os.path.join(os.getenv("APPDATA") or "", "Autodesk", "Revit")
        info = ProcessStartInfo()
        info.FileName = path
        info.UseShellExecute = True
        Process.Start(info)
        return True
    except Exception:
        return False


def main():
    settings = core.load_settings()
    window = build_window()

    try:
        _load_icon(window.FindName("HeaderIcon"))
    except Exception:
        pass
    try:
        window.FindName("VersionText").Text = "v" + core.__version__
    except Exception:
        pass

    to_window(window, settings)
    status = window.FindName("StatusText")
    status.Text = core.SETTINGS_PATH

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

    def _defaults(sender, args):
        to_window(window, core.Settings())
        status.Text = "Defaults loaded - press Apply to save them."

    def _shortcuts(sender, args):
        if open_shortcuts():
            status.Text = ("Bind keys in Revit: View > User Interface > "
                           "Keyboard Shortcuts, search 'RevoBIM Service "
                           "Spacing'.")
        else:
            status.Text = "The shortcuts folder could not be opened."

    def _apply(sender, args):
        complaints = from_window(window, settings)
        saved = core.save_settings(settings)
        if complaints:
            status.Text = ("Saved, but these would not parse and were reset: "
                           + ", ".join(complaints))
            to_window(window, settings)
        elif saved:
            status.Text = "Saved to " + core.SETTINGS_PATH
        else:
            status.Text = "The settings file could not be written."

    window.FindName("HeaderBar").MouseLeftButtonDown += _drag
    window.FindName("CloseBtn").Click += _close
    window.FindName("DefaultsBtn").Click += _defaults
    window.FindName("ShortcutsBtn").Click += _shortcuts
    window.FindName("ApplyBtn").Click += _apply

    window.ShowDialog()


try:
    main()
except Exception:
    from pyrevit import forms
    forms.alert("Service Spacing Settings stopped:\n\n" +
                traceback.format_exc(), title="RevoBIM Service Spacing")
