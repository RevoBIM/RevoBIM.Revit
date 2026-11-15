# -*- coding: utf-8 -*-
"""Window loading, theming, chrome, and the two windows the tool shows."""

import tle_clr  # noqa: F401  assemblies first, always

import os

from System.IO import StringReader
from System.Xml import XmlReader
from System.Windows import (Thickness, CornerRadius, GridLength, GridUnitType,
                            TextWrapping, SystemParameters, Clipboard)
from System.Windows.Markup import XamlReader
from System.Windows.Controls import TextBlock, Border, Grid, ColumnDefinition, ComboBoxItem
from System.Windows.Media import SolidColorBrush, ColorConverter
from System.Windows.Input import Key
from System.Windows.Interop import WindowInteropHelper

import tle_core
import theme as theme_mod

HERE = os.path.dirname(os.path.abspath(__file__))


def _read(name):
    handle = open(os.path.join(HERE, name), "r")
    try:
        return handle.read()
    finally:
        handle.close()


def load_window(layout_name, palette_name):
    """Parse a layout, merge Theme.xaml into it, then write the palette on top.

    Theme.xaml is merged *after* the layout is parsed, which is why the layout
    files may only use DynamicResource.  The palette is written onto
    window.Resources, which sits in front of a merged dictionary in WPF's
    lookup order, so it can be swapped on an open window with no reload.
    """
    window = XamlReader.Load(XmlReader.Create(StringReader(_read(layout_name))))
    try:
        theme_dict = XamlReader.Load(XmlReader.Create(StringReader(_read("Theme.xaml"))))
        window.Resources.MergedDictionaries.Add(theme_dict)
    except Exception:
        pass
    theme_mod.apply(window, palette_name)
    return window


def own_to_revit(window, uiapp):
    """An unowned modeless window slips behind Revit and reads as a crash."""
    try:
        helper = WindowInteropHelper(window)
        helper.Owner = uiapp.MainWindowHandle
    except Exception:
        try:
            from System.Diagnostics import Process
            WindowInteropHelper(window).Owner = Process.GetCurrentProcess().MainWindowHandle
        except Exception:
            pass


# ============================================================================
# chrome
# ============================================================================

class Chrome(object):
    """Drag, close, full screen by bounds, and the eight resize grips."""

    def __init__(self, window, resizable=True, full_screen=True):
        self.window = window
        self.saved = None
        self.full = False

        header = window.FindName("HeaderBar")
        if header is not None:
            header.MouseLeftButtonDown += self._drag
        close_btn = window.FindName("CloseBtn")
        if close_btn is not None:
            close_btn.Click += self._close
        if full_screen:
            full_btn = window.FindName("FullBtn")
            if full_btn is not None:
                full_btn.Click += self._toggle_full
        window.KeyDown += self._key

        if resizable:
            self._grips()

    def _drag(self, sender, args):
        try:
            if args.ClickCount == 2:
                self._toggle_full(sender, args)
                return
        except Exception:
            pass
        if self.full:
            self.restore()
        try:
            self.window.DragMove()
        except Exception:
            pass

    def _close(self, sender, args):
        try:
            self.window.Close()
        except Exception:
            pass

    def _key(self, sender, args):
        if args.Key == Key.Escape:
            self._close(sender, args)
        elif args.Key == Key.F11:
            self._toggle_full(sender, args)

    # ---- full screen by bounds, not WindowState.Maximized -------------------

    def _work_area(self):
        try:
            from System.Windows.Forms import Screen
            from System.Drawing import Point as DrawPoint
            handle = WindowInteropHelper(self.window).Handle
            screen = Screen.FromHandle(handle)
            area = screen.WorkingArea
            scale_x, scale_y = self._dpi()
            return (area.Left / scale_x, area.Top / scale_y,
                    area.Width / scale_x, area.Height / scale_y)
        except Exception:
            rect = SystemParameters.WorkArea
            return (rect.Left, rect.Top, rect.Width, rect.Height)

    def _dpi(self):
        try:
            from System.Windows import PresentationSource
            source = PresentationSource.FromVisual(self.window)
            matrix = source.CompositionTarget.TransformToDevice
            return (matrix.M11 or 1.0, matrix.M22 or 1.0)
        except Exception:
            return (1.0, 1.0)

    def _toggle_full(self, sender, args):
        if self.full:
            self.restore()
        else:
            self.maximise()

    def maximise(self):
        window = self.window
        self.saved = (window.Left, window.Top, window.Width, window.Height)
        left, top, width, height = self._work_area()
        window.Left, window.Top, window.Width, window.Height = left, top, width, height
        self.full = True

    def restore(self):
        if not self.saved:
            self.full = False
            return
        window = self.window
        window.Left, window.Top, window.Width, window.Height = self.saved
        self.full = False

    # ---- resize grips ------------------------------------------------------

    def _grips(self):
        spec = {
            "GripL": (-1, 0), "GripR": (1, 0), "GripT": (0, -1), "GripB": (0, 1),
            "GripTL": (-1, -1), "GripTR": (1, -1), "GripBL": (-1, 1), "GripBR": (1, 1),
        }
        for name, vector in spec.items():
            grip = self.window.FindName(name)
            if grip is None:
                continue
            grip.DragDelta += self._make_grip(vector)

    def _make_grip(self, vector):
        horizontal, vertical = vector
        window = self.window

        def handler(sender, args):
            try:
                if horizontal < 0:
                    width = window.Width - args.HorizontalChange
                    if width >= window.MinWidth:
                        window.Left = window.Left + args.HorizontalChange
                        window.Width = width
                elif horizontal > 0:
                    width = window.Width + args.HorizontalChange
                    if width >= window.MinWidth:
                        window.Width = width
                if vertical < 0:
                    height = window.Height - args.VerticalChange
                    if height >= window.MinHeight:
                        window.Top = window.Top + args.VerticalChange
                        window.Height = height
                elif vertical > 0:
                    height = window.Height + args.VerticalChange
                    if height >= window.MinHeight:
                        window.Height = height
            except Exception:
                pass

        return handler


# ============================================================================
# small helpers
# ============================================================================

def brush(window, key):
    try:
        return window.Resources[key]
    except Exception:
        return SolidColorBrush(ColorConverter.ConvertFromString("#E4E4E4"))


def fill_combo(combo, pairs, value):
    """pairs is a sequence of (stored value, label)."""
    combo.Items.Clear()
    chosen = 0
    for index, pair in enumerate(pairs):
        item = ComboBoxItem()
        item.Content = pair[1]
        item.Tag = pair[0]
        combo.Items.Add(item)
        if pair[0] == value:
            chosen = index
    combo.SelectedIndex = chosen


def combo_value(combo, fallback):
    try:
        item = combo.SelectedItem
        if item is not None and item.Tag is not None:
            return str(item.Tag)
    except Exception:
        pass
    return fallback


# ============================================================================
# results
# ============================================================================

COLOUR_FOR = {"done": "GreenBrush", "skip": "OrangeBrush", "fail": "RedBrush"}


class ResultsWindow(object):
    """Themed report.  Rows are built as WPF elements in code, never bound to
    Python objects, which is unreliable across IronPython engine versions."""

    def __init__(self, cfg, summary, detail, rows, status):
        self.cfg = cfg
        self.rows = rows
        self.palette = cfg.get("theme", "dark")
        self.window = load_window("TagLeaderElbowResults.xaml", self.palette)
        self.chrome = Chrome(self.window, resizable=True, full_screen=True)

        self.window.FindName("VersionText").Text = "v" + tle_core.__version__
        self.window.FindName("SummaryText").Text = summary
        self.window.FindName("DetailText").Text = detail
        self.window.FindName("StatusText").Text = status
        self.window.FindName("OkBtn").Click += self._close
        self.window.FindName("CopyBtn").Click += self._copy

        chip = self.window.FindName("ThemeChip")
        chip.Content = theme_mod.other(self.palette).title()
        chip.Click += self._swap_theme

        self._build_rows()

    def _build_rows(self):
        panel = self.window.FindName("RowsPanel")
        panel.Children.Clear()
        for row in self.rows:
            panel.Children.Add(self._row(row))

    def _row(self, row):
        kind, tag_text, note = row
        grid = Grid()
        grid.Margin = Thickness(0, 2, 0, 2)

        tick_col = ColumnDefinition()
        tick_col.Width = GridLength(13)
        name_col = ColumnDefinition()
        name_col.Width = GridLength(1, GridUnitType.Star)
        name_col.MinWidth = 170
        note_col = ColumnDefinition()
        note_col.Width = GridLength(2.4, GridUnitType.Star)
        note_col.MinWidth = 220
        grid.ColumnDefinitions.Add(tick_col)
        grid.ColumnDefinitions.Add(name_col)
        grid.ColumnDefinitions.Add(note_col)

        tick = Border()
        tick.Width = 4
        tick.Height = 14
        tick.CornerRadius = CornerRadius(2)
        tick.Margin = Thickness(0, 0, 9, 0)
        tick.Background = brush(self.window, COLOUR_FOR.get(kind, "MutedBrush"))
        Grid.SetColumn(tick, 0)
        grid.Children.Add(tick)

        left = TextBlock()
        left.Text = tag_text
        left.Foreground = brush(self.window, "TextBrush")
        left.FontSize = 12.5
        left.TextWrapping = TextWrapping.Wrap
        left.Margin = Thickness(0, 0, 12, 0)
        Grid.SetColumn(left, 1)
        grid.Children.Add(left)

        right = TextBlock()
        right.Text = note
        right.Foreground = brush(self.window, "MutedBrush")
        right.FontSize = 12.0
        right.TextWrapping = TextWrapping.Wrap
        Grid.SetColumn(right, 2)
        grid.Children.Add(right)
        return grid

    def _swap_theme(self, sender, args):
        self.palette = theme_mod.other(self.palette)
        theme_mod.apply(self.window, self.palette)
        sender.Content = theme_mod.other(self.palette).title()
        self.cfg["theme"] = self.palette
        try:
            tle_core.save_settings(self.cfg)
        except Exception:
            pass
        self._build_rows()

    def _copy(self, sender, args):
        lines = []
        for kind, tag_text, note in self.rows:
            lines.append("{0}\t{1}\t{2}".format(kind, tag_text, note))
        try:
            Clipboard.SetText("\n".join(lines))
            self.window.FindName("StatusText").Text = "{0} rows copied to the clipboard".format(
                len(lines))
        except Exception:
            self.window.FindName("StatusText").Text = "The clipboard refused the list"

    def _close(self, sender, args):
        try:
            self.window.Close()
        except Exception:
            pass

    def show(self):
        self.window.ShowDialog()


def show_results(cfg, summary, detail, rows, status):
    ResultsWindow(cfg, summary, detail, rows, status).show()


# ============================================================================
# settings
# ============================================================================

DIRECTION_ITEMS = (
    ("leader", "The way the leader already runs"),
    ("reverse", "The opposite way to the leader"),
)

EXISTING_ITEMS = (
    ("replace", "Re-place the elbow"),
    ("keep", "Leave them alone"),
)

AMBIGUOUS_ITEMS = (
    ("left", "Elbow to the left"),
    ("right", "Elbow to the right"),
    ("skip", "Skip it and say so"),
)

STARTFROM_ITEMS = (
    ("edge", "The end of the tag text"),
    ("head", "The tag head itself"),
)

EXTENT_ITEMS = (
    ("measured", "Measuring the tag itself"),
    ("text", "Measuring its text"),
)

EXTENT_NOTES = {
    "measured": "The tag's own extent is read with its leader switched off "
                "inside a rolled back sub-transaction, so the run into the tag "
                "comes out exactly horizontal. The two settings below are then "
                "only a fallback.",
    "text": "The tag text is measured and the two settings below say where the "
            "head sits in it. Use this if reading the tag itself misbehaves.",
}

JUSTIFY_ITEMS = (
    ("left", "Left justified, text runs right of the head"),
    ("centre", "Centred on the head"),
    ("right", "Right justified, text runs left of the head"),
)

JUSTIFY_NOTES = {
    "left": "Going left the leg starts at the head; going right it starts past "
            "the end of the text.",
    "centre": "Half the text width is cleared whichever way the leg goes.",
    "right": "Going right the leg starts at the head; going left it starts past "
             "the end of the text.",
}

VERTICAL_ITEMS = (
    ("top", "On the top line of the text"),
    ("middle", "On the middle of the text"),
    ("bottom", "On the bottom line of the text"),
)

VERTICAL_NOTES = {
    "top": "The elbow is dropped onto the middle of the text, so the run into "
           "the tag stays horizontal.",
    "middle": "The head is already on the middle, so the elbow is left level "
              "with it.",
    "bottom": "The elbow is raised onto the middle of the text, so the run into "
              "the tag stays horizontal.",
}

RESULTS_ITEMS = (
    ("needed", "Only when something needs a look"),
    ("always", "Always"),
    ("never", "Never"),
)

THEME_ITEMS = (("dark", "Dark"), ("light", "Light"))


class SettingsWindow(object):

    def __init__(self, cfg, uiapp=None):
        self.cfg = dict(cfg)
        self.uiapp = uiapp
        self.saved = False
        self.palette = self.cfg.get("theme", "dark")
        self.window = load_window("TagLeaderElbowSettings.xaml", self.palette)
        self.chrome = Chrome(self.window, resizable=False, full_screen=False)

        self.window.FindName("VersionText").Text = "v" + tle_core.__version__
        self.window.FindName("ApplyBtn").Click += self._apply
        self.window.FindName("CancelBtn").Click += self._cancel
        self.window.FindName("ShortcutBtn").Click += self._shortcuts

        self._load()

    def _load(self):
        cfg = self.cfg
        find = self.window.FindName
        find("ElbowMmBox").Text = str(cfg.get("elbow_mm"))
        find("BaseScaleBox").Text = str(cfg.get("base_scale"))
        find("ScaleChk").IsChecked = tle_core.as_bool(cfg, "scale_with_view")
        find("SpatialChk").IsChecked = tle_core.as_bool(cfg, "include_spatial_tags")
        find("PromptChk").IsChecked = tle_core.as_bool(cfg, "prompt_when_empty")
        find("HeadChk").IsChecked = tle_core.as_bool(cfg, "keep_head_fixed")
        find("UnpinChk").IsChecked = tle_core.as_bool(cfg, "unpin")
        fill_combo(find("ExtentCombo"), EXTENT_ITEMS, cfg.get("tag_extent"))
        find("ExtentCombo").SelectionChanged += self._extent_picked
        fill_combo(find("StartCombo"), STARTFROM_ITEMS, cfg.get("start_from"))
        fill_combo(find("JustifyCombo"), JUSTIFY_ITEMS, cfg.get("justification"))
        find("JustifyCombo").SelectionChanged += self._justify_picked
        fill_combo(find("DirectionCombo"), DIRECTION_ITEMS, cfg.get("direction"))
        fill_combo(find("ExistingCombo"), EXISTING_ITEMS, cfg.get("existing_elbow"))
        fill_combo(find("AmbiguousCombo"), AMBIGUOUS_ITEMS, cfg.get("ambiguous"))
        fill_combo(find("VerticalCombo"), VERTICAL_ITEMS, cfg.get("head_vertical"))
        find("VerticalCombo").SelectionChanged += self._vertical_picked
        fill_combo(find("ResultsCombo"), RESULTS_ITEMS, cfg.get("show_results"))
        fill_combo(find("ThemeCombo"), THEME_ITEMS, cfg.get("theme"))
        find("ThemeCombo").SelectionChanged += self._theme_picked
        find("ExtentNote").Text = EXTENT_NOTES.get(cfg.get("tag_extent"), "")
        find("JustifyNote").Text = JUSTIFY_NOTES.get(cfg.get("justification"), "")
        find("VerticalNote").Text = VERTICAL_NOTES.get(cfg.get("head_vertical"), "")
        self._note()

    def _note(self):
        cfg = self._collect(quiet=True)
        try:
            self.window.FindName("ScaleNote").Text = (
                "At 1:100 that is {0:.0f}mm in the model.".format(
                    tle_core.elbow_length_mm(cfg, 100)))
        except Exception:
            self.window.FindName("ScaleNote").Text = ""

    def _extent_picked(self, sender, args):
        how = combo_value(sender, "measured")
        self.window.FindName("ExtentNote").Text = EXTENT_NOTES.get(how, "")

    def _justify_picked(self, sender, args):
        where = combo_value(sender, "left")
        self.window.FindName("JustifyNote").Text = JUSTIFY_NOTES.get(where, "")

    def _vertical_picked(self, sender, args):
        where = combo_value(sender, "top")
        self.window.FindName("VerticalNote").Text = VERTICAL_NOTES.get(where, "")

    def _theme_picked(self, sender, args):
        self.palette = combo_value(sender, self.palette)
        theme_mod.apply(self.window, self.palette)

    def _collect(self, quiet=False):
        find = self.window.FindName
        cfg = dict(self.cfg)
        cfg["elbow_mm"] = find("ElbowMmBox").Text.strip()
        cfg["base_scale"] = find("BaseScaleBox").Text.strip()
        cfg["scale_with_view"] = "1" if find("ScaleChk").IsChecked else "0"
        cfg["include_spatial_tags"] = "1" if find("SpatialChk").IsChecked else "0"
        cfg["prompt_when_empty"] = "1" if find("PromptChk").IsChecked else "0"
        cfg["keep_head_fixed"] = "1" if find("HeadChk").IsChecked else "0"
        cfg["unpin"] = "1" if find("UnpinChk").IsChecked else "0"
        cfg["tag_extent"] = combo_value(find("ExtentCombo"), "measured")
        cfg["start_from"] = combo_value(find("StartCombo"), "edge")
        cfg["justification"] = combo_value(find("JustifyCombo"), "left")
        cfg["direction"] = combo_value(find("DirectionCombo"), "leader")
        cfg["existing_elbow"] = combo_value(find("ExistingCombo"), "replace")
        cfg["ambiguous"] = combo_value(find("AmbiguousCombo"), "skip")
        cfg["head_vertical"] = combo_value(find("VerticalCombo"), "top")
        cfg["show_results"] = combo_value(find("ResultsCombo"), "needed")
        cfg["theme"] = combo_value(find("ThemeCombo"), "dark")
        return cfg

    def _apply(self, sender, args):
        cfg = self._collect()
        status = self.window.FindName("StatusText")
        try:
            length = float(cfg["elbow_mm"])
            scale = float(cfg["base_scale"])
        except Exception:
            status.Text = "The leg length and the scale both have to be numbers."
            return
        if length <= 0:
            status.Text = "The leg length has to be more than zero."
            return
        if scale <= 0:
            status.Text = "The quoted view scale has to be more than zero."
            return
        cfg["elbow_mm"] = "{0:g}".format(length)
        cfg["base_scale"] = "{0:g}".format(scale)
        try:
            path = tle_core.save_settings(cfg)
        except Exception as error:
            status.Text = "Could not write the settings: {0}".format(error)
            return
        self.cfg = cfg
        self.saved = True
        status.Text = "Saved to " + path
        try:
            self.window.Close()
        except Exception:
            pass

    def _cancel(self, sender, args):
        try:
            self.window.Close()
        except Exception:
            pass

    def _shortcuts(self, sender, args):
        try:
            from Autodesk.Revit.UI import RevitCommandId, PostableCommand
            command = RevitCommandId.LookupPostableCommandId(PostableCommand.KeyboardShortcuts)
            self.uiapp.PostCommand(command)
            self.window.Close()
        except Exception:
            self.window.FindName("StatusText").Text = (
                "View > User Interface > Keyboard Shortcuts, then search "
                "RevoBIM Tag Leader Elbow.")

    def show(self):
        self.window.ShowDialog()
        return self.saved
