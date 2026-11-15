# -*- coding: utf-8 -*-
"""Tag Aligner: XAML loading, theming, window chrome, the theme chip, the
Settings window and the Results window.

Every event handler is wrapped: an exception inside a WPF closure is
swallowed silently otherwise, and the window just stops responding.
"""
import ta_clr  # noqa: F401  must stay first

import os
import traceback

from System.Diagnostics import Process
from System.IO import File, MemoryStream
from System.Windows import TextWrapping, Thickness, Visibility
from System.Windows.Controls import TextBlock
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Markup import XamlReader
from System.Windows.Media import Color, SolidColorBrush
from System.Windows.Media.Imaging import BitmapCacheOption, BitmapImage

import ta_core as core
import ta_theme as theme

HERE = os.path.dirname(os.path.abspath(__file__))
THEME_XAML = os.path.join(HERE, "TagAlignerTheme.xaml")
SETTINGS_XAML = os.path.join(HERE, "TagAlignerSettings.xaml")
RESULTS_XAML = os.path.join(HERE, "TagAlignerResults.xaml")
HEADER_ICON = os.path.join(HERE, "tag_aligner_header.png")

LEVEL_KEYS = {u"ok": u"Green", u"warn": u"Orange", u"error": u"Red"}


# ==========================================================================
# Loading and theming
# ==========================================================================

def load_window(path):
    window = XamlReader.Parse(File.ReadAllText(path))
    window.Resources.MergedDictionaries.Add(
        XamlReader.Parse(File.ReadAllText(THEME_XAML)))
    return window


def apply_palette(window, mode):
    """Write the live palette straight onto window.Resources, in front of
    the merged Theme.xaml, so an open window re-themes in place."""
    palette = theme.PALETTES[theme.resolve(mode)]
    for key, value in palette.items():
        r, g, b = theme.hex_to_rgb(value)
        window.Resources[key] = SolidColorBrush(Color.FromArgb(255, r, g, b))


def own_to_revit(window, uiapp):
    try:
        WindowInteropHelper(window).Owner = uiapp.MainWindowHandle
    except Exception:
        pass


def load_icon(image, path):
    """MemoryStream, never a Uri: System.Uri moved assembly in Revit 2025."""
    try:
        if image is None or not os.path.isfile(path):
            return
        bmp = BitmapImage()
        bmp.BeginInit()
        bmp.StreamSource = MemoryStream(File.ReadAllBytes(path))
        bmp.CacheOption = BitmapCacheOption.OnLoad
        bmp.EndInit()
        image.Source = bmp
    except Exception:
        pass


class ThemeChip(object):
    """The Auto / Dark / Light chip at the top right of every RevoBIM window.
    Click cycles Auto -> Dark -> Light; the choice is saved straight away."""

    def __init__(self, window, values):
        self.window = window
        self.values = values
        self.chip = window.FindName("ThemeChip")
        self.label = window.FindName("ThemeChipText")
        self.glyphs = {
            u"follow": window.FindName("GlyphAuto"),
            u"dark": window.FindName("GlyphDark"),
            u"light": window.FindName("GlyphLight"),
        }
        self.chip.MouseLeftButtonUp += self._clicked
        self.refresh()

    def refresh(self):
        mode = self.values.get(u"theme", u"follow")
        apply_palette(self.window, mode)
        self.label.Text = theme.LABELS.get(mode, u"Auto")
        self.chip.ToolTip = theme.tooltip(mode)
        for key, glyph in self.glyphs.items():
            if glyph is not None:
                glyph.Visibility = Visibility.Visible if key == mode \
                    else Visibility.Collapsed

    def _clicked(self, sender, args):
        try:
            self.values[u"theme"] = theme.next_mode(
                self.values.get(u"theme", u"follow"))
            self.refresh()
            core.save_theme_only(self.values[u"theme"])
        except Exception:
            pass


def wire_chrome(window, title=None):
    """Header drag, close button, version and icon."""
    header = window.FindName("HeaderBar")
    close = window.FindName("CloseButton")
    version = window.FindName("VersionText")
    version.Text = u"v" + core.__version__
    load_icon(window.FindName("HeaderIcon"), HEADER_ICON)

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

    header.MouseLeftButtonDown += _drag
    close.Click += _close
    if title:
        try:
            window.FindName("TitleText").Text = title
        except Exception:
            pass


# ==========================================================================
# Settings window
# ==========================================================================

class SettingsWindow(object):
    RADIOS = {
        u"align_reference": {u"first": "RefFirst", u"average": "RefAverage",
                             u"pick": "RefPick"},
        u"text_height_source": {u"auto": "THAuto", u"fixed": "THFixed"},
        u"v_mode": {u"gap": "VModeGap", u"pitch": "VModePitch"},
        u"h_mode": {u"gap": "HModeGap", u"pitch": "HModePitch"},
        u"untangle_anchor": {u"centre": "AnchorCentre",
                             u"first": "AnchorFirst"},
        u"pinned": {u"skip": "PinSkip", u"unpin": "PinUnpin"},
        u"show_results": {u"needed": "ShowNeeded", u"always": "ShowAlways",
                          u"never": "ShowNever"},
    }
    NUMBERS = {
        u"text_height_mm": "TextHeight",
        u"v_gap": "VGap",
        u"v_pitch": "VPitch",
        u"h_gap": "HGap",
        u"h_pitch": "HPitch",
    }
    CHECKS = {u"move_elbows": "MoveElbows", u"debug": "DebugLog"}
    NUMBER_LABELS = {
        u"text_height_mm": u"Text height",
        u"v_gap": u"Vertical gap",
        u"v_pitch": u"Vertical pitch",
        u"h_gap": u"Horizontal gap",
        u"h_pitch": u"Horizontal pitch",
    }

    def __init__(self, uiapp):
        self.uiapp = uiapp
        self.values = core.load_settings()
        self.window = load_window(SETTINGS_XAML)
        self.chip = ThemeChip(self.window, self.values)
        wire_chrome(self.window)
        self.status = self.window.FindName("StatusText")
        self._fill(self.values)
        self._wire()

    def _ctl(self, name):
        return self.window.FindName(name)

    def _fill(self, values):
        for key, options in self.RADIOS.items():
            for value, name in options.items():
                self._ctl(name).IsChecked = (values[key] == value)
        for key, name in self.NUMBERS.items():
            self._ctl(name).Text = core.format_number(values[key])
        for key, name in self.CHECKS.items():
            self._ctl(name).IsChecked = bool(values[key])
        self._preview()

    def _wire(self):
        self._ctl("ApplyButton").Click += self._apply
        self._ctl("CancelButton").Click += self._cancel
        self._ctl("ResetButton").Click += self._reset
        for name in self.NUMBERS.values():
            self._ctl(name).TextChanged += self._changed
        for options in self.RADIOS.values():
            for name in options.values():
                self._ctl(name).Checked += self._changed

    def _read(self):
        """(values, problems). Nothing is saved from here."""
        out = dict(self.values)
        problems = []
        for key, options in self.RADIOS.items():
            for value, name in options.items():
                if self._ctl(name).IsChecked:
                    out[key] = value
        for key, name in self.NUMBERS.items():
            v = core._to_float(self._ctl(name).Text, key)
            if v is None:
                lo, hi = core.FLOATS[key]
                problems.append(u"{0} must be a number from {1} to {2}".format(
                    self.NUMBER_LABELS[key], core.format_number(lo),
                    core.format_number(hi)))
            else:
                out[key] = v
        for key, name in self.CHECKS.items():
            out[key] = bool(self._ctl(name).IsChecked)
        out[u"theme"] = self.values.get(u"theme", u"follow")
        return out, problems

    def _preview(self):
        try:
            values, _ = self._read()
            th = values[u"text_height_mm"]
            for prefix, target in ((u"v_", "VPreview"), (u"h_", "HPreview")):
                lines = []
                for scale in (50, 100):
                    lines.append(core.spacing_preview(
                        th, values[prefix + u"mode"], values[prefix + u"gap"],
                        values[prefix + u"pitch"], scale))
                if values[prefix + u"mode"] == u"gap":
                    lines.append(u"(single line tag; taller or wider tags "
                                 u"get their own size plus the gap)")
                self._ctl(target).Text = u"\n".join(lines)
        except Exception:
            pass

    def _changed(self, sender, args):
        self._preview()

    def _apply(self, sender, args):
        try:
            values, problems = self._read()
            if problems:
                self.status.Text = problems[0]
                self.status.SetResourceReference(TextBlock.ForegroundProperty,
                                                 u"Red")
                return
            core.save_settings(values)
            self.values.update(values)
            self.window.Close()
        except Exception as ex:
            self.status.Text = u"Could not save: {0}".format(ex)

    def _cancel(self, sender, args):
        try:
            self.window.Close()
        except Exception:
            pass

    def _reset(self, sender, args):
        try:
            defaults = core.default_settings()
            defaults[u"theme"] = self.values.get(u"theme", u"follow")
            self._fill(defaults)
            self.status.Text = u"Defaults loaded. Press Apply to keep them."
        except Exception:
            pass

    def show(self):
        own_to_revit(self.window, self.uiapp)
        self.window.ShowDialog()


# ==========================================================================
# Results window
# ==========================================================================

class ResultsWindow(object):
    def __init__(self, uiapp, report, log_path):
        self.uiapp = uiapp
        self.log_path = log_path
        self.values = core.load_settings()
        self.window = load_window(RESULTS_XAML)
        self.chip = ThemeChip(self.window, self.values)
        wire_chrome(self.window, u"Tag Aligner - " + report.title)
        panel = self.window.FindName("LinesPanel")
        for level, text in report.lines:
            block = TextBlock()
            block.Text = text
            block.TextWrapping = TextWrapping.Wrap
            block.Margin = Thickness(0, 2, 0, 4)
            block.SetResourceReference(TextBlock.ForegroundProperty,
                                       LEVEL_KEYS.get(level, u"Text"))
            panel.Children.Add(block)
        status = self.window.FindName("StatusText")
        status.Text = u"{0} tag(s) moved".format(report.moved)
        open_log = self.window.FindName("OpenLogButton")
        open_log.IsEnabled = bool(log_path) and os.path.isfile(log_path)
        open_log.Click += self._open_log
        self.window.FindName("OkButton").Click += self._ok

    def _open_log(self, sender, args):
        try:
            Process.Start(self.log_path)
        except Exception:
            pass

    def _ok(self, sender, args):
        try:
            self.window.Close()
        except Exception:
            pass

    def show(self):
        own_to_revit(self.window, self.uiapp)
        self.window.ShowDialog()


def show_results(uiapp, report, log_path):
    ResultsWindow(uiapp, report, log_path).show()


def show_settings(uiapp):
    SettingsWindow(uiapp).show()


def failure_text(stage):
    return u"Tag Aligner stopped while {0}.\n\n{1}".format(
        stage, traceback.format_exc())
