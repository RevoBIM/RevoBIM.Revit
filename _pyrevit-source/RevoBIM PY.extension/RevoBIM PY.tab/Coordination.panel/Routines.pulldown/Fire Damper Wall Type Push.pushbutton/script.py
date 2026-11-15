# -*- coding: utf-8 -*-
"""RevoBIM Fire Damper Wall Type Push.

Finds every duct accessory that passes through a wall or a floor - in the
current model or in a chosen linked model - and pushes two values from that
host onto the accessory:

  1. the host type name       (default source: Family type name)
  2. the host fire rating     (default source: POP_PERF_FireRatingTarget)

Both target parameters are chosen in the window. Nothing is written until
Apply is pressed.

Loads in stages and reports which stage failed, because a blank white pyRevit
window means the script died before any of it ran and there is no traceback to
read.
"""

__title__ = "RevoBIM Fire Damper\nWall Type Push"
__author__ = "RevoBIM"

import io
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.append(HERE)

STAGE = "starting"


def _report_failure(stage, detail):
    """Say which stage died, in a Revit dialog and in a log file."""
    text = "RevoBIM Fire Damper Wall Type Push could not start.\n\n" \
           "Stage: {0}\n\n{1}".format(stage, detail)
    try:
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show("RevoBIM Fire Damper Wall Type Push", text)
    except Exception:
        pass
    try:
        base = os.getenv("APPDATA") or os.path.expanduser("~")
        folder = os.path.join(base, "RevoBIM")
        if not os.path.isdir(folder):
            os.makedirs(folder)
        handle = io.open(
            os.path.join(folder, "fire_damper_wall_type_push.log"),
            "a",
            encoding="utf-8",
        )
        try:
            handle.write(u"{0}\n{1}\n".format(text, "=" * 70))
        finally:
            handle.close()
    except Exception:
        pass


# ============================================================================
# stage 1 - assemblies
# ============================================================================
try:
    STAGE = "referencing assemblies"
    import fdwt_clr  # noqa: F401  - must be first, before any System.* line
except Exception:
    _report_failure("referencing assemblies", traceback.format_exc())
    raise

# ============================================================================
# stage 2 - modules
# ============================================================================
try:
    STAGE = "loading modules"

    import fdwt_core as core

    from System.Diagnostics import Process
    from System.IO import File, MemoryStream
    from System.Windows import (
        CornerRadius,
        GridLength,
        GridUnitType,
        HorizontalAlignment,
        ResourceDictionary,
        SystemParameters,
        TextTrimming,
        Thickness,
        VerticalAlignment,
        Visibility,
    )
    from System.Windows.Controls import (
        Border,
        CheckBox,
        Grid,
        ColumnDefinition,
        TextBlock,
        ToolTip,
    )
    from System.Windows.Input import Key
    from System.Windows.Interop import WindowInteropHelper
    from System.Windows.Markup import XamlReader
    from System.Windows.Media import BrushConverter
    from System.Windows.Media.Imaging import BitmapCacheOption, BitmapImage
    from System.Windows.Threading import (
        Dispatcher,
        DispatcherFrame,
        DispatcherPriority,
        DispatcherOperationCallback,
    )

    from Autodesk.Revit.DB import (
        FailureProcessingResult,
        FailureSeverity,
        IFailuresPreprocessor,
        Transaction,
        TransactionStatus,
    )
    from Autodesk.Revit.UI import (
        TaskDialog,
        TaskDialogCommonButtons,
        TaskDialogResult,
    )
except Exception:
    _report_failure("loading modules", traceback.format_exc())
    raise


# ============================================================================
# palettes
# ============================================================================

DARK = {
    "WindowBg": "#232326",
    "CardBg": "#2B2B2E",
    "FieldBg": "#1C1C1F",
    "BarBg": "#1C1C1F",
    "EdgeBrush": "#3E3E42",
    "OuterEdgeBrush": "#4A4A50",
    "BodyText": "#E4E4E4",
    "MutedText": "#9A9A9E",
    "BlueBrush": "#4FA3E3",
    "OrangeBrush": "#E8912D",
    "GreenBrush": "#3FA75A",
    "GreenHoverBrush": "#4EC06D",
    "RedBrush": "#D9534F",
    "SelectBrush": "#2B5473",
    "HoverBrush": "#33333A",
    "RowChangeBg": "#3A2E1C",
    "RowSameBg": "#1F2E23",
    "RowReviewBg": "#3A2223",
}

# Not the dark palette inverted: the accents are darkened, because the dark
# palette's accents are chosen to sit on near black and wash out on white.
LIGHT = {
    "WindowBg": "#F2F2F4",
    "CardBg": "#FFFFFF",
    "FieldBg": "#FFFFFF",
    "BarBg": "#E4E4E8",
    "EdgeBrush": "#C9C9D0",
    "OuterEdgeBrush": "#B5B5BE",
    "BodyText": "#232326",
    "MutedText": "#6A6A72",
    "BlueBrush": "#1B72BE",
    "OrangeBrush": "#B96A12",
    "GreenBrush": "#2E8546",
    "GreenHoverBrush": "#3FA75A",
    "RedBrush": "#C0392B",
    "SelectBrush": "#BBD7EF",
    "HoverBrush": "#E9E9EE",
    "RowChangeBg": "#FBEFDD",
    "RowSameBg": "#E6F4EA",
    "RowReviewBg": "#FAE3E1",
}

STATUS_TEXT = {
    core.STATUS_CHANGE: "will change",
    core.STATUS_SAME: "already correct",
    core.STATUS_REVIEW: "needs a look",
    core.STATUS_DONE: "written",
    core.STATUS_FAILED: "refused",
}

STATUS_COLOUR = {
    core.STATUS_CHANGE: "OrangeBrush",
    core.STATUS_SAME: "GreenBrush",
    core.STATUS_REVIEW: "RedBrush",
    core.STATUS_DONE: "GreenBrush",
    core.STATUS_FAILED: "RedBrush",
}

STATUS_ROW_BG = {
    core.STATUS_CHANGE: "RowChangeBg",
    core.STATUS_SAME: "RowSameBg",
    core.STATUS_REVIEW: "RowReviewBg",
    core.STATUS_DONE: "RowSameBg",
    core.STATUS_FAILED: "RowReviewBg",
}

COLUMN_WIDTHS = [26.0, 235.0, 58.0, 70.0, 55.0, 175.0, 90.0, -1.0]  # -1 = star

MAX_ROWS_SHOWN = 1500

_BRUSHES = BrushConverter()


def brush(hex_value):
    return _BRUSHES.ConvertFromString(hex_value)


def do_events():
    """Let the window repaint mid-run. Never allowed to take the tool down."""
    try:
        frame = DispatcherFrame()

        def stop(state):
            frame.Continue = False
            return None

        Dispatcher.CurrentDispatcher.BeginInvoke(
            DispatcherPriority.Background, DispatcherOperationCallback(stop), None
        )
        Dispatcher.PushFrame(frame)
    except Exception:
        pass


# ============================================================================
# Revit's own dialogs, suppressed for the duration of a run
# ============================================================================

SUPPRESS = {"on": False}


def _on_dialog_showing(sender, args):
    if not SUPPRESS["on"]:
        return
    # Log what was answered on the user's behalf. A run that writes nothing
    # because Revit quietly asked a question is otherwise unexplainable.
    try:
        core.log_line(u"suppressed Revit dialog: {0}".format(args.DialogId))
    except Exception:
        pass
    try:
        args.OverrideResult(1)
    except Exception:
        pass


try:
    # Hooked ONCE and switched with a flag: unsubscribing an IronPython bound
    # method from a .NET event is not reliable, since each attribute access
    # makes a fresh delegate.
    if not getattr(sys.modules[__name__], "_DIALOG_HOOKED", False):
        __revit__.DialogBoxShowing += _on_dialog_showing  # noqa: F821
        _DIALOG_HOOKED = True
except Exception:
    pass


class SwallowWarnings(IFailuresPreprocessor):
    def PreprocessFailures(self, accessor):
        try:
            for failure in accessor.GetFailureMessages():
                if failure.GetSeverity() == FailureSeverity.Warning:
                    accessor.DeleteWarning(failure)
        except Exception:
            pass
        return FailureProcessingResult.Continue


# ============================================================================
# windows
# ============================================================================

def load_window(filename):
    path = os.path.join(HERE, filename)
    stream = File.OpenRead(path)
    try:
        window = XamlReader.Load(stream)
    finally:
        stream.Close()
    return window


def merge_theme(window):
    path = os.path.join(HERE, "Theme.xaml")
    stream = File.OpenRead(path)
    try:
        dictionary = XamlReader.Load(stream)
    finally:
        stream.Close()
    if not isinstance(dictionary, ResourceDictionary):
        raise Exception("Theme.xaml did not parse as a ResourceDictionary")
    window.Resources.MergedDictionaries.Add(dictionary)
    return dictionary


def apply_palette(window, palette):
    """Straight onto window.Resources, which sits in front of the merged
    dictionary in WPF's lookup order - so the palette swaps on an open window
    with no reload and no loss of state."""
    for key in palette:
        try:
            window.Resources[key] = brush(palette[key])
        except Exception:
            continue


def own_to_revit(window):
    try:
        helper = WindowInteropHelper(window)
        helper.Owner = Process.GetCurrentProcess().MainWindowHandle
    except Exception:
        pass


def load_icon(image_control):
    try:
        path = os.path.join(HERE, "icon.png")
        if not os.path.isfile(path):
            return
        # System.Uri moved assemblies in 2025+, so never UriSource: load the
        # bytes instead.
        bitmap = BitmapImage()
        bitmap.BeginInit()
        bitmap.StreamSource = MemoryStream(File.ReadAllBytes(path))
        bitmap.CacheOption = BitmapCacheOption.OnLoad
        bitmap.EndInit()
        image_control.Source = bitmap
    except Exception:
        pass  # cosmetics can never take a tool down


def show_message(title, body, palette, height=330):
    try:
        window = load_window("FireDamperMessage.xaml")
        merge_theme(window)
        apply_palette(window, palette)
        window.FindName("TxtTitle").Text = title
        window.FindName("TxtBody").Text = body
        window.FindName("TxtVersion").Text = "v" + core.__version__
        window.Height = height
        own_to_revit(window)

        def close(sender, args):
            window.DialogResult = True

        window.FindName("BtnOk").Click += close
        window.FindName("BtnClose").Click += close

        def drag(sender, args):
            try:
                window.DragMove()
            except Exception:
                pass

        window.FindName("HeaderBar").MouseLeftButtonDown += drag
        window.ShowDialog()
    except Exception:
        try:
            TaskDialog.Show("RevoBIM " + title, body)
        except Exception:
            pass


# ============================================================================
# the tool
# ============================================================================

class FireDamperTool(object):

    def __init__(self, uidoc):
        self.uidoc = uidoc
        self.doc = uidoc.Document
        self.settings = core.load_settings()
        self.palette = DARK if self.settings.get("theme") != "light" else LIGHT

        self.links = []              # (label, RevitLinkInstance)
        self.accessories = []
        self.families = []           # (name, CheckBox)
        self.excluded = set()
        self.rows = []
        self.row_panels = []         # (row, Border)
        self.target_names = []
        self.all_target_names = []
        self.src_type_names = [core.TYPE_NAME_KEY]
        self.src_fire_names = []
        self.restore_to = None
        self.progress_done = -1
        self.busy = False
        self.loading = True

        self.window = load_window("FireDamperWallTypePush.xaml")
        merge_theme(self.window)
        apply_palette(self.window, self.palette)

        for key in self.settings.get("excluded_families", "").split("|"):
            if key:
                self.excluded.add(key)

        self._grab_controls()
        self._wire()
        self._populate()

    # -- controls ----------------------------------------------------------

    def _grab_controls(self):
        find = self.window.FindName
        self.header_bar = find("HeaderBar")
        self.header_icon = find("HeaderIcon")
        self.txt_version = find("TxtVersion")
        self.btn_theme = find("BtnTheme")
        self.btn_max = find("BtnMax")
        self.btn_close = find("BtnClose")

        self.grips = [
            (find("GripN"), "N"),
            (find("GripS"), "S"),
            (find("GripW"), "W"),
            (find("GripE"), "E"),
            (find("GripNW"), "NW"),
            (find("GripNE"), "NE"),
            (find("GripSW"), "SW"),
            (find("GripSE"), "SE"),
        ]

        self.cbo_link = find("CboLink")
        self.cbo_src_type = find("CboSrcType")
        self.cbo_src_fire = find("CboSrcFire")
        self.cbo_tgt_type = find("CboTgtType")
        self.cbo_tgt_fire = find("CboTgtFire")
        self.txt_src_type_search = find("TxtSrcTypeSearch")
        self.txt_src_fire_search = find("TxtSrcFireSearch")
        self.txt_tgt_type_search = find("TxtTgtTypeSearch")
        self.txt_tgt_fire_search = find("TxtTgtFireSearch")

        self.chk_overwrite = find("ChkOverwrite")
        self.chk_only_rated = find("ChkOnlyRated")
        self.chk_view_only = find("ChkViewOnly")
        self.chk_walls = find("ChkWalls")
        self.chk_floors = find("ChkFloors")

        self.progress_track = find("ProgressTrack")
        self.progress_fill = find("ProgressFill")
        self.txt_percent = find("TxtPercent")

        self.txt_family_search = find("TxtFamilySearch")
        self.txt_family_heading = find("TxtFamilyHeading")
        self.pnl_families = find("PnlFamilies")
        self.btn_fam_all = find("BtnFamAll")
        self.btn_fam_none = find("BtnFamNone")

        self.txt_preview_heading = find("TxtPreviewHeading")
        self.pnl_rows = find("PnlRows")
        self.txt_col_accessory = find("TxtColAccessory")
        self.txt_col_mark = find("TxtColMark")
        self.txt_col_level = find("TxtColLevel")
        self.txt_col_host = find("TxtColHost")
        self.txt_col_hosttype = find("TxtColHostType")
        self.txt_col_rating = find("TxtColRating")
        self.cbo_col_status = find("CboColStatus")

        self.txt_status = find("TxtStatus")
        self.btn_find = find("BtnFind")
        self.btn_apply = find("BtnApply")
        self.btn_export = find("BtnExport")

    def _wire(self):
        self.btn_close.Click += self.on_close
        self.btn_theme.Click += self.on_theme
        self.btn_max.Click += self.on_full_screen

        for thumb, edge in self.grips:
            thumb.DragDelta += self._grip_handler(edge)

        self.btn_find.Click += self.on_find
        self.btn_apply.Click += self.on_apply
        self.btn_export.Click += self.on_export
        self.btn_fam_all.Click += self.on_family_all
        self.btn_fam_none.Click += self.on_family_none

        self.cbo_link.SelectionChanged += self.on_link_changed
        self.chk_view_only.Checked += self.on_scope_changed
        self.chk_view_only.Unchecked += self.on_scope_changed
        for box in (self.chk_walls, self.chk_floors):
            box.Checked += self.on_hosts_changed
            box.Unchecked += self.on_hosts_changed

        self.txt_family_search.TextChanged += self.on_family_search
        for box in (
            self.txt_src_type_search,
            self.txt_src_fire_search,
            self.txt_tgt_type_search,
            self.txt_tgt_fire_search,
        ):
            box.TextChanged += self.on_param_search

        for box in (
            self.txt_col_accessory,
            self.txt_col_mark,
            self.txt_col_level,
            self.txt_col_host,
            self.txt_col_hosttype,
            self.txt_col_rating,
        ):
            box.TextChanged += self.on_row_filter
        self.cbo_col_status.SelectionChanged += self.on_row_filter

        self.header_bar.MouseLeftButtonDown += self.on_drag
        self.window.KeyDown += self.on_key
        self.window.Closing += self.on_closing

    # -- population --------------------------------------------------------

    def _populate(self):
        self.txt_version.Text = "v" + core.__version__
        self.btn_theme.Content = "Light" if self.palette is DARK else "Dark"
        load_icon(self.header_icon)

        self.chk_overwrite.IsChecked = self.settings.get("overwrite", "1") == "1"
        self.chk_only_rated.IsChecked = self.settings.get("only_rated", "0") == "1"
        self.chk_view_only.IsChecked = self.settings.get("scope", "project") == "view"

        saved_hosts = (self.settings.get("hosts") or "").split(",")
        saved_hosts = core.host_categories([key.strip() for key in saved_hosts])
        self.chk_walls.IsChecked = core.HOST_WALLS in saved_hosts
        self.chk_floors.IsChecked = core.HOST_FLOORS in saved_hosts

        self.links = core.link_instances(self.doc)
        labels = [core.CURRENT_MODEL_KEY]
        for label, _link in self.links:
            labels.append(label)
        self._fill_combo(self.cbo_link, labels, self.settings.get("link"))

        self._fill_combo(
            self.cbo_col_status,
            ["All", "will change", "already correct", "needs a look"],
            "All",
        )

        self._load_accessories()
        self.loading = False
        self._load_source_params()

    def _fill_combo(self, combo, values, selected=None):
        combo.ItemsSource = None
        combo.ItemsSource = list(values)
        if selected is not None and selected in values:
            combo.SelectedItem = selected
        elif combo.Items.Count > 0:
            combo.SelectedIndex = 0

    def _active_view(self):
        if self.chk_view_only.IsChecked:
            try:
                return self.doc.ActiveView
            except Exception:
                return None
        return None

    def _load_accessories(self):
        self.accessories = core.duct_accessories(self.doc, self._active_view())
        counts = {}
        for accessory in self.accessories:
            name = core.family_of(accessory, self.doc)
            counts[name] = counts.get(name, 0) + 1

        self.pnl_families.Children.Clear()
        self.families = []
        for name in sorted(counts.keys(), key=lambda text: text.lower()):
            box = CheckBox()
            box.Content = "{0}  ({1})".format(name, counts[name])
            box.Tag = name
            box.Margin = Thickness(0, 2, 0, 2)
            box.IsChecked = name not in self.excluded
            box.Checked += self.on_family_ticked
            box.Unchecked += self.on_family_ticked
            self.pnl_families.Children.Add(box)
            self.families.append((name, box))

        self.txt_family_heading.Text = "Duct accessory families ({0})".format(
            len(self.families)
        )
        self.target_names = core.writable_instance_param_names(self.accessories)
        self._fill_target_combos()
        self.set_status(
            "{0} duct accessories in {1}.".format(
                len(self.accessories),
                "the active view" if self.chk_view_only.IsChecked else "the project",
            )
        )

    def _fill_target_combos(self):
        wanted_type = self.settings.get("tgt_type_param") or ""
        wanted_fire = self.settings.get("tgt_fire_param") or ""
        names = list(self.target_names)
        for name in (wanted_type, wanted_fire):
            if name and name not in names:
                names.append(name)  # keep a saved choice visible even if unseen
        names.sort(key=lambda text: text.lower())
        self.all_target_names = names
        self._fill_combo(self.cbo_tgt_type, names, wanted_type or None)
        self._fill_combo(self.cbo_tgt_fire, names, wanted_fire or None)

    def _host_keys(self):
        """Which host categories are ticked: walls, floors, or both."""
        keys = []
        if self.chk_walls.IsChecked:
            keys.append(core.HOST_WALLS)
        if self.chk_floors.IsChecked:
            keys.append(core.HOST_FLOORS)
        return core.host_categories(keys)

    def _host_source(self):
        """(host document, transform, label) for the chosen model."""
        label = self.cbo_link.SelectedItem
        if label is None or label == core.CURRENT_MODEL_KEY:
            return self.doc, None, core.CURRENT_MODEL_KEY
        for name, link in self.links:
            if name == label:
                try:
                    return link.GetLinkDocument(), link.GetTotalTransform(), name
                except Exception:
                    return None, None, name
        return None, None, str(label)

    def _load_source_params(self):
        host_doc, _transform, label = self._host_source()
        if host_doc is None:
            self.set_status("Could not read '{0}'. Is the link loaded?".format(label))
            return
        keys = self._host_keys()
        total = 0
        try:
            total = core.host_collector(host_doc, keys).GetElementCount()
        except Exception:
            total = 0

        hosts = []  # a sample is enough to learn the parameter names
        for host in core.host_collector(host_doc, keys):
            hosts.append(host)
            if len(hosts) >= 60:
                break
        if not total:
            total = len(hosts)
        names = core.readable_param_names(hosts, host_doc)

        type_names = [core.TYPE_NAME_KEY]
        for name in names:
            if name != core.TYPE_NAME_KEY:
                type_names.append(name)

        fire_names = list(names)
        saved_fire = self.settings.get("src_fire_param") or ""
        if saved_fire and saved_fire not in fire_names:
            fire_names.insert(0, saved_fire)
        if not fire_names:
            fire_names = [saved_fire] if saved_fire else [""]

        self.src_type_names = type_names
        self.src_fire_names = fire_names

        self._fill_combo(
            self.cbo_src_type, type_names, self.settings.get("src_type_param")
        )
        self._fill_combo(self.cbo_src_fire, fire_names, saved_fire)
        if not self.loading:
            self.on_param_search(None, None)
        self.set_status(
            "{0}: {1} {2}.".format(
                label,
                total,
                " and ".join([core.HOST_LABELS[key].lower() + "s" for key in keys]),
            )
        )

    # -- status and progress -----------------------------------------------

    def show_progress(self, on):
        try:
            self.progress_track.Visibility = (
                Visibility.Visible if on else Visibility.Collapsed
            )
            self.txt_percent.Visibility = (
                Visibility.Visible if on else Visibility.Collapsed
            )
            if not on:
                self.progress_fill.Width = 0
                self.progress_done = -1
            do_events()
        except Exception:
            pass

    def set_progress(self, done, total, text=""):
        """The bar along the top of the window, in whole percent.

        Only repaints when the percent actually moves - pumping the dispatcher
        on every one of several thousand accessories costs more than the work
        being measured.
        """
        try:
            percent = 0
            if total:
                percent = int((done * 100) / total)
            if percent > 100:
                percent = 100
            if percent == self.progress_done:
                return
            self.progress_done = percent

            width = self.progress_track.ActualWidth
            if not width:
                width = self.window.ActualWidth
            self.progress_fill.Width = width * percent / 100.0
            self.txt_percent.Text = "{0}%".format(percent)
            if text:
                self.txt_status.Text = "{0}  -  {1}%".format(text, percent)
            do_events()
        except Exception:
            pass

    def set_status(self, text, pump=False):
        try:
            self.txt_status.Text = text
        except Exception:
            pass
        if pump:
            do_events()

    # -- events ------------------------------------------------------------

    def on_drag(self, sender, args):
        try:
            if args.ClickCount == 2:
                self.on_full_screen(sender, args)
                return
        except Exception:
            pass
        try:
            self.window.DragMove()
        except Exception:
            pass

    def on_key(self, sender, args):
        try:
            if args.Key == Key.Escape and not self.busy:
                self.window.Close()
        except Exception:
            pass

    def on_close(self, sender, args):
        self.window.Close()

    def on_closing(self, sender, args):
        if self.busy:
            try:
                args.Cancel = True
            except Exception:
                pass
            return
        self.save()

    def on_theme(self, sender, args):
        self.palette = LIGHT if self.palette is DARK else DARK
        apply_palette(self.window, self.palette)
        self.btn_theme.Content = "Light" if self.palette is DARK else "Dark"
        self.settings["theme"] = "dark" if self.palette is DARK else "light"
        self._recolour_rows()

    def on_link_changed(self, sender, args):
        if self.busy or self.loading:
            return
        self._load_source_params()

    def on_hosts_changed(self, sender, args):
        if self.busy or self.loading:
            return
        if not self.chk_walls.IsChecked and not self.chk_floors.IsChecked:
            # never leave it with nothing to look at
            self.chk_walls.IsChecked = True
            return
        self._load_source_params()
        self._clear_rows()

    def on_scope_changed(self, sender, args):
        if self.busy or self.loading:
            return
        self._load_accessories()
        self._clear_rows()

    def on_family_ticked(self, sender, args):
        try:
            name = sender.Tag
            if sender.IsChecked:
                self.excluded.discard(name)
            else:
                self.excluded.add(name)
        except Exception:
            pass

    def on_family_all(self, sender, args):
        for name, box in self.families:
            box.IsChecked = True

    def on_family_none(self, sender, args):
        for name, box in self.families:
            box.IsChecked = False

    def on_family_search(self, sender, args):
        needle = (self.txt_family_search.Text or "").strip().lower()
        for name, box in self.families:
            hit = not needle or needle in name.lower()
            box.Visibility = Visibility.Visible if hit else Visibility.Collapsed

    def _search_sets(self):
        """Which search box drives which dropdown, and off which list."""
        return (
            (self.txt_src_type_search, self.cbo_src_type, self.src_type_names),
            (self.txt_src_fire_search, self.cbo_src_fire, self.src_fire_names),
            (self.txt_tgt_type_search, self.cbo_tgt_type, self.all_target_names),
            (self.txt_tgt_fire_search, self.cbo_tgt_fire, self.all_target_names),
        )

    def on_param_search(self, sender, args):
        """Isolate the parameters that match, in every dropdown at once.

        Deliberately does NOT try to work out which box was typed in: an
        earlier version compared the sender with `is`, which compares Python
        object identity on a .NET object and so never matched - the search
        did nothing at all.
        """
        if self.loading:
            return
        misses = []
        for box, combo, names in self._search_sets():
            missed = self._isolate(box, combo, names)
            if missed:
                misses.append(missed)
        if misses:
            self.set_status(
                "No parameter matches {0} - showing what is there.".format(
                    ", ".join(["'{0}'".format(m) for m in misses])
                )
            )

    def _isolate(self, box, combo, names):
        """Narrow one dropdown to the names holding every keyword typed.

        Returns the search text when nothing matched, so the caller can say
        so rather than leaving an empty dropdown.
        """
        words = [word for word in (box.Text or "").lower().split() if word]
        keep = combo.SelectedItem

        if not words:
            matches = list(names)
        else:
            matches = [
                name
                for name in names
                if all(word in name.lower() for word in words)
            ]

        missed = None
        if not matches:
            missed = " ".join(words)
            matches = list(names)  # never leave them with nothing to pick

        if keep and keep not in matches:
            matches = [keep] + matches

        combo.ItemsSource = None
        combo.ItemsSource = matches
        if keep in matches:
            combo.SelectedItem = keep
        elif matches:
            combo.SelectedIndex = 0
        return missed

    # -- window size -------------------------------------------------------

    def _grip_handler(self, edge):
        """One DragDelta handler per edge, closed over which edge it is."""

        def handler(sender, args):
            try:
                self._resize(edge, args.HorizontalChange, args.VerticalChange)
            except Exception:
                pass

        return handler

    def _resize(self, edge, dx, dy):
        window = self.window
        least_width = window.MinWidth or 600
        least_height = window.MinHeight or 400

        if "E" in edge:
            width = window.Width + dx
            if width >= least_width:
                window.Width = width
        if "S" in edge:
            height = window.Height + dy
            if height >= least_height:
                window.Height = height
        if "W" in edge:
            width = window.Width - dx
            if width >= least_width:
                window.Width = width
                window.Left = window.Left + dx
        if "N" in edge:
            height = window.Height - dy
            if height >= least_height:
                window.Height = height
                window.Top = window.Top + dy

    def on_full_screen(self, sender, args):
        """Fill the working area, or go back to where it was.

        Done by hand rather than with WindowState.Maximized, which on a
        transparent borderless window spills over the taskbar.
        """
        try:
            if self.restore_to is None:
                self.restore_to = (
                    self.window.Left,
                    self.window.Top,
                    self.window.Width,
                    self.window.Height,
                )
                self.window.Left = SystemParameters.WorkArea.Left
                self.window.Top = SystemParameters.WorkArea.Top
                self.window.Width = SystemParameters.WorkArea.Width
                self.window.Height = SystemParameters.WorkArea.Height
                self.btn_max.Content = u"❑"
                self.btn_max.ToolTip = "Back to normal size"
            else:
                left, top, width, height = self.restore_to
                self.restore_to = None
                self.window.Left = left
                self.window.Top = top
                self.window.Width = width
                self.window.Height = height
                self.btn_max.Content = u"❐"
                self.btn_max.ToolTip = "Full screen"
        except Exception:
            core.log_line(traceback.format_exc())

    def on_row_filter(self, sender, args):
        self._apply_row_filter()

    # -- find --------------------------------------------------------------

    def on_find(self, sender, args):
        if self.busy:
            return
        host_doc, transform, label = self._host_source()
        if host_doc is None:
            show_message(
                "Cannot read that model",
                "'{0}' has no open document. Load the link and try again.".format(label),
                self.palette,
            )
            return
        keys = self._host_keys()

        wanted = [
            accessory
            for accessory in self.accessories
            if core.family_of(accessory, self.doc) not in self.excluded
        ]
        if not wanted:
            show_message(
                "Nothing to look at",
                "No duct accessory families are ticked, so there is nothing to "
                "check. Tick at least one family on the left.",
                self.palette,
            )
            return

        src_type = self.cbo_src_type.SelectedItem or core.TYPE_NAME_KEY
        src_fire = self.cbo_src_fire.SelectedItem or ""
        tgt_type = self.cbo_tgt_type.SelectedItem or ""
        tgt_fire = self.cbo_tgt_fire.SelectedItem or ""

        if not tgt_type and not tgt_fire:
            show_message(
                "Nowhere to write to",
                "Pick at least one target parameter on the duct accessory.",
                self.palette,
            )
            return

        self.busy = True
        self.btn_find.IsEnabled = False
        self.btn_apply.IsEnabled = False
        self.btn_export.IsEnabled = False
        self._clear_rows()

        against = " and ".join(
            [core.HOST_LABELS[key].lower() + "s" for key in keys]
        )
        self.show_progress(True)

        def progress(done, total):
            self.set_progress(
                done,
                total,
                "Checking {0} of {1} duct accessories against the {2} in "
                "{3}".format(done, total, against, label),
            )

        try:
            self.rows = core.build_rows(
                self.doc,
                wanted,
                host_doc,
                transform,
                src_type,
                src_fire,
                tgt_type,
                tgt_fire,
                only_rated=bool(self.chk_only_rated.IsChecked),
                progress=progress,
                keys=keys,
            )
        except Exception:
            detail = traceback.format_exc()
            core.log_line(detail)
            self.rows = []
            show_message("The search failed", detail, self.palette, height=420)
        finally:
            self.show_progress(False)
            self.busy = False
            self.btn_find.IsEnabled = True

        self._build_rows()
        self.save()

    def _clear_rows(self):
        self.rows = []
        self.row_panels = []
        try:
            self.pnl_rows.Children.Clear()
        except Exception:
            pass
        self.btn_apply.IsEnabled = False
        self.btn_export.IsEnabled = False
        self.txt_preview_heading.Text = "Preview - nothing is written until Apply"

    def _build_rows(self):
        self.pnl_rows.Children.Clear()
        self.row_panels = []
        shown = self.rows[:MAX_ROWS_SHOWN]
        dropped = len(self.rows) - len(shown)

        for row in shown:
            panel = self._row_panel(row)
            self.pnl_rows.Children.Add(panel)
            self.row_panels.append((row, panel))

        changes = len([r for r in self.rows if r.status == core.STATUS_CHANGE])
        same = len([r for r in self.rows if r.status == core.STATUS_SAME])
        review = len([r for r in self.rows if r.status == core.STATUS_REVIEW])

        self.txt_preview_heading.Text = (
            "Preview - {0} to change, {1} already correct, {2} need a look".format(
                changes, same, review
            )
        )
        message = "{0} accessories checked. Nothing is written until Apply.".format(
            len(self.rows)
        )
        if dropped > 0:
            message += "  {0} more rows found than the table shows ({1} shown); " \
                       "Export list writes all of them.".format(dropped, MAX_ROWS_SHOWN)
        self.set_status(message)
        self.btn_apply.IsEnabled = changes > 0
        self.btn_export.IsEnabled = len(self.rows) > 0
        self._apply_row_filter()

    def _row_panel(self, row):
        border = Border()
        border.BorderThickness = Thickness(0, 0, 0, 1)
        border.SetResourceReference(Border.BorderBrushProperty, "EdgeBrush")
        border.SetResourceReference(Border.BackgroundProperty, STATUS_ROW_BG[row.status])
        border.Padding = Thickness(8, 4, 8, 4)

        grid = Grid()
        for width in COLUMN_WIDTHS:
            column = ColumnDefinition()
            if width < 0:
                column.Width = GridLength(1, GridUnitType.Star)
            else:
                column.Width = GridLength(width)
            grid.ColumnDefinitions.Add(column)

        dot = Border()
        dot.Width = 9
        dot.Height = 9
        dot.CornerRadius = CornerRadius(2)
        dot.HorizontalAlignment = HorizontalAlignment.Left
        dot.VerticalAlignment = VerticalAlignment.Center
        dot.SetResourceReference(Border.BackgroundProperty, STATUS_COLOUR[row.status])
        Grid.SetColumn(dot, 0)
        grid.Children.Add(dot)

        status_text = STATUS_TEXT.get(row.status, row.status)
        if row.note:
            status_text = "{0} - {1}".format(status_text, row.note)

        cells = [
            (1, row.label, "BodyText"),
            (2, row.mark, "MutedText"),
            (3, row.level, "MutedText"),
            (4, row.host_kind, "MutedText"),
            (5, row.new_type_value or "", "BodyText"),
            (6, row.new_fire_value or "", "BodyText"),
            (7, status_text, "MutedText"),
        ]
        for column_index, text, colour_key in cells:
            block = TextBlock()
            block.Text = text or ""
            block.FontSize = 12
            block.Margin = Thickness(0, 0, 8, 0)
            block.VerticalAlignment = VerticalAlignment.Center
            block.TextTrimming = TextTrimming.CharacterEllipsis
            block.SetResourceReference(TextBlock.ForegroundProperty, colour_key)
            Grid.SetColumn(block, column_index)
            grid.Children.Add(block)

        try:
            tip = ToolTip()
            tip.Content = self._row_tooltip(row)
            border.ToolTip = tip
        except Exception:
            pass

        border.Child = grid
        border.Tag = row
        return border

    def _row_tooltip(self, row):
        lines = [
            "Element id {0}".format(row.id),
            "{0}".format(row.label),
        ]
        if row.host_id:
            lines.append(
                "{0} id {1} - {2}".format(
                    row.host_kind or "Host", row.host_id, row.host_label
                )
            )
        lines.append(
            "1st value now: {0}   ->   {1}".format(
                row.old_type_value or "(empty)", row.new_type_value or "(nothing)"
            )
        )
        lines.append(
            "2nd value now: {0}   ->   {1}".format(
                row.old_fire_value or "(empty)", row.new_fire_value or "(nothing)"
            )
        )
        if row.note:
            lines.append(row.note)
        return "\n".join(lines)

    def _recolour_rows(self):
        for row, panel in self.row_panels:
            try:
                panel.SetResourceReference(
                    Border.BackgroundProperty, STATUS_ROW_BG[row.status]
                )
            except Exception:
                continue

    def _apply_row_filter(self):
        needles = [
            (1, (self.txt_col_accessory.Text or "").strip().lower()),
            (2, (self.txt_col_mark.Text or "").strip().lower()),
            (3, (self.txt_col_level.Text or "").strip().lower()),
            (4, (self.txt_col_host.Text or "").strip().lower()),
            (5, (self.txt_col_hosttype.Text or "").strip().lower()),
            (6, (self.txt_col_rating.Text or "").strip().lower()),
        ]
        status_wanted = self.cbo_col_status.SelectedItem or "All"

        for row, panel in self.row_panels:
            values = {
                1: row.label,
                2: row.mark,
                3: row.level,
                4: row.host_kind,
                5: row.new_type_value or "",
                6: row.new_fire_value or "",
            }
            hit = True
            for index, needle in needles:
                if needle and needle not in (values[index] or "").lower():
                    hit = False
                    break
            if hit and status_wanted != "All":
                if STATUS_TEXT.get(row.status, "") != status_wanted:
                    hit = False
            panel.Visibility = Visibility.Visible if hit else Visibility.Collapsed

    # -- apply -------------------------------------------------------------

    def on_apply(self, sender, args):
        if self.busy:
            return
        pending = [row for row in self.rows if row.status == core.STATUS_CHANGE]
        if not pending:
            show_message("Nothing to apply", "No row is waiting to change.", self.palette)
            return

        tgt_type = self.cbo_tgt_type.SelectedItem or ""
        tgt_fire = self.cbo_tgt_fire.SelectedItem or ""
        overwrite = bool(self.chk_overwrite.IsChecked)

        preview = [
            "About to write to {0} duct accessories:".format(len(pending)),
            "",
            "  1st value  ->  {0}".format(tgt_type or "(not set)"),
            "  2nd value  ->  {0}".format(tgt_fire or "(not set)"),
            "",
            "Values already in place will be {0}.".format(
                "overwritten" if overwrite else "left alone"
            ),
            "",
        ]
        for row in pending[:12]:
            preview.append(
                "  {0}  ->  {1} / {2}".format(
                    row.label, row.new_type_value or "-", row.new_fire_value or "-"
                )
            )
        if len(pending) > 12:
            preview.append("  ... and {0} more.".format(len(pending) - 12))
        preview.append("")
        preview.append("Press OK to write them. Close this window to stop.")

        if not self._confirm("Apply", "\n".join(preview)):
            self.set_status("Apply cancelled - nothing was written.")
            return

        self.busy = True
        self.btn_apply.IsEnabled = False
        self.btn_find.IsEnabled = False
        SUPPRESS["on"] = True

        core.log_line(
            u"=== Apply {0} rows, 1st -> {1}, 2nd -> {2}, overwrite {3} ===".format(
                len(pending), tgt_type, tgt_fire, overwrite
            )
        )

        written = 0
        refused = 0
        nothing = 0
        not_owned = 0
        failure = None
        status = None

        # Borrow first, outside the transaction. On a cloud workshared model
        # a write to an element you have not borrowed writes nothing, and
        # says nothing.
        self.set_status("Checking out the elements...", pump=True)
        owned, checkout_message = core.checkout(self.doc, [r.element for r in pending])
        if checkout_message:
            core.log_line(u"checkout: {0}".format(checkout_message))

        transaction = Transaction(self.doc, "RevoBIM Fire Damper Wall Type Push")
        try:
            if transaction.Start() != TransactionStatus.Started:
                raise Exception(
                    "Revit would not start a transaction. The model may be "
                    "read only, or another command still has it."
                )
            try:
                options = transaction.GetFailureHandlingOptions()
                options.SetFailuresPreprocessor(SwallowWarnings())
                options.SetClearAfterRollback(True)
                transaction.SetFailureHandlingOptions(options)
            except Exception:
                core.log_line(traceback.format_exc())

            # No dispatcher pumping between Start and Commit: letting Revit's
            # message loop run inside an open transaction is what turns a
            # working write into a silent no-op.
            for row in pending:
                if owned is not None and row.id not in owned:
                    row.status = core.STATUS_FAILED
                    row.note = (
                        "another user has this element - it could not be "
                        "borrowed, so nothing was written to it"
                    )
                    core.log_line(u"row {0} not owned".format(row.id))
                    not_owned += 1
                    refused += 1
                    continue
                if core.apply_row(row, tgt_type, tgt_fire, overwrite, log=True):
                    if row.status == core.STATUS_DONE:
                        written += 1
                    else:
                        nothing += 1
                else:
                    refused += 1

            status = transaction.Commit()
            if status != TransactionStatus.Committed:
                failure = (
                    "Revit did not commit the transaction (it came back "
                    "'{0}'), so nothing was written.".format(status)
                )
        except Exception:
            failure = traceback.format_exc()
            try:
                if transaction.HasStarted():
                    transaction.RollBack()
            except Exception:
                pass
        finally:
            SUPPRESS["on"] = False
            self.busy = False
            self.btn_find.IsEnabled = True

        core.log_line(
            u"=== {0} written, {1} refused, {2} nothing to do, commit {3} ===".format(
                written, refused, nothing, status
            )
        )

        if failure:
            core.log_line(failure)
            self.set_status("The write failed - see the message.")
            show_message(
                "The write failed",
                failure + "\n\nThe same text is in:\n" + core.log_path(),
                self.palette,
                height=440,
            )
            return

        self._build_rows()
        self.save()

        body = [
            "{0} duct accessories updated, and each value was read back off "
            "the element to confirm it landed.".format(written),
            "",
            "  1st value written to: {0}".format(tgt_type or "(not set)"),
            "  2nd value written to: {0}".format(tgt_fire or "(not set)"),
        ]
        if nothing:
            body.append("")
            body.append(
                "{0} had nothing to write - the wall had no value, or "
                "'overwrite' is off and they already had one.".format(nothing)
            )
        if not_owned:
            body.append("")
            body.append(
                "{0} are owned by another user and could not be borrowed. "
                "They need releasing before this can write to them.".format(not_owned)
            )
        if refused:
            body.append("")
            body.append(
                "{0} did not take. They are red in the table with the reason "
                "on the row, and the detail is in:\n{1}".format(
                    refused, core.log_path()
                )
            )
        show_message("Done", "\n".join(body), self.palette, height=380)

    def _confirm(self, title, body):
        """A themed yes/no. OK means go, closing means stop.

        Falls back to Revit's own dialog rather than returning "no" if the
        themed one will not open - a silent False here reads exactly like
        "Apply does nothing", which is the last thing this button should do.
        """
        try:
            window = load_window("FireDamperMessage.xaml")
            merge_theme(window)
            apply_palette(window, self.palette)
            window.FindName("TxtTitle").Text = title
            window.FindName("TxtBody").Text = body
            window.FindName("TxtVersion").Text = "v" + core.__version__
            window.FindName("BtnOk").Content = "Write them"
            window.Height = 430
            own_to_revit(window)
            state = {"go": False}

            def yes(sender, args):
                state["go"] = True
                try:
                    window.DialogResult = True
                except Exception:
                    window.Close()

            def no(sender, args):
                try:
                    window.DialogResult = False
                except Exception:
                    window.Close()

            window.FindName("BtnOk").Click += yes
            window.FindName("BtnClose").Click += no

            def drag(sender, args):
                try:
                    window.DragMove()
                except Exception:
                    pass

            window.FindName("HeaderBar").MouseLeftButtonDown += drag
            window.ShowDialog()
            return state["go"]
        except Exception:
            core.log_line("themed confirm failed:\n" + traceback.format_exc())

        try:
            answer = TaskDialog.Show(
                "RevoBIM Fire Damper Wall Type Push",
                body,
                TaskDialogCommonButtons.Yes | TaskDialogCommonButtons.No,
            )
            return answer == TaskDialogResult.Yes
        except Exception:
            core.log_line("fallback confirm failed:\n" + traceback.format_exc())
            return True  # the preview has already been seen; do not stall here

    # -- export ------------------------------------------------------------

    def on_export(self, sender, args):
        if not self.rows:
            return
        path = None
        try:
            from Microsoft.Win32 import SaveFileDialog

            dialog = SaveFileDialog()
            dialog.Filter = "CSV file (*.csv)|*.csv"
            dialog.FileName = "Fire damper wall type push.csv"
            if dialog.ShowDialog() == True:
                path = dialog.FileName
        except Exception:
            core.log_line(traceback.format_exc())
        if not path:
            return

        try:
            handle = io.open(path, "w", encoding="utf-8")
            try:
                handle.write(
                    u"Element id,Family,Type,Mark,Level,Host,Host id,"
                    u"Host type,1st value now,1st value new,2nd value now,"
                    u"2nd value new,Status,Note\n"
                )
                for row in self.rows:
                    handle.write(
                        u",".join(
                            [
                                csv_cell(row.id),
                                csv_cell(row.family),
                                csv_cell(row.type_name),
                                csv_cell(row.mark),
                                csv_cell(row.level),
                                csv_cell(row.host_kind),
                                csv_cell(row.host_id),
                                csv_cell(row.host_label),
                                csv_cell(row.old_type_value),
                                csv_cell(row.new_type_value),
                                csv_cell(row.old_fire_value),
                                csv_cell(row.new_fire_value),
                                csv_cell(STATUS_TEXT.get(row.status, row.status)),
                                csv_cell(row.note),
                            ]
                        )
                        + u"\n"
                    )
            finally:
                handle.close()
            self.set_status("Written to {0}".format(path))
        except Exception:
            detail = traceback.format_exc()
            core.log_line(detail)
            show_message("Export failed", detail, self.palette)

    # -- settings ----------------------------------------------------------

    def save(self):
        self.settings["link"] = str(self.cbo_link.SelectedItem or core.CURRENT_MODEL_KEY)
        self.settings["src_type_param"] = str(
            self.cbo_src_type.SelectedItem or core.TYPE_NAME_KEY
        )
        self.settings["src_fire_param"] = str(self.cbo_src_fire.SelectedItem or "")
        self.settings["tgt_type_param"] = str(self.cbo_tgt_type.SelectedItem or "")
        self.settings["tgt_fire_param"] = str(self.cbo_tgt_fire.SelectedItem or "")
        self.settings["overwrite"] = "1" if self.chk_overwrite.IsChecked else "0"
        self.settings["only_rated"] = "1" if self.chk_only_rated.IsChecked else "0"
        self.settings["hosts"] = ",".join(self._host_keys())
        self.settings["scope"] = "view" if self.chk_view_only.IsChecked else "project"
        self.settings["excluded_families"] = "|".join(sorted(self.excluded))
        core.save_settings(self.settings)

    def show(self):
        own_to_revit(self.window)
        self.window.ShowDialog()


def utext(value):
    """Anything as unicode text, on IronPython 2 and 3 alike."""
    if value is None:
        return u""
    try:
        return u"{0}".format(value)
    except Exception:
        return u""


def csv_cell(value):
    text = utext(value)
    if u"," in text or u'"' in text or u"\n" in text:
        return u'"' + text.replace(u'"', u'""') + u'"'
    return text


# ============================================================================
# stage 3 and 4 - read the project, then show the window
# ============================================================================

def main():
    global STAGE
    try:
        STAGE = "reading the project"
        uidoc = __revit__.ActiveUIDocument  # noqa: F821
        if uidoc is None:
            raise Exception("No open document.")
        tool = FireDamperTool(uidoc)
    except Exception:
        _report_failure(STAGE, traceback.format_exc())
        return

    try:
        STAGE = "showing the window"
        tool.show()
    except Exception:
        _report_failure(STAGE, traceback.format_exc())


main()
