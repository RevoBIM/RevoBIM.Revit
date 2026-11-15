# -*- coding: utf-8 -*-
"""Window loading, theming, chrome, the shrink-to-taskbar drawer, and the two
windows Tag Tidy shows: the preview / results window and the settings."""

import tidy_clr  # noqa: F401  assemblies first, always

import os

from System import Double, TimeSpan
from System.IO import StringReader
from System.Xml import XmlReader
from System.Windows import (Window, Thickness, CornerRadius, GridLength, GridUnitType,
                            TextWrapping, SystemParameters, Clipboard, Visibility,
                            VerticalAlignment, SizeToContent)
from System.Windows.Markup import XamlReader
from System.Windows.Controls import TextBlock, Border, Grid, ColumnDefinition, ComboBoxItem
from System.Windows.Media import SolidColorBrush, ColorConverter
from System.Windows.Input import Key, Keyboard, ModifierKeys
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Threading import DispatcherTimer

import tidy_core as core
import tidy_theme as theme_mod

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
    """A window with no owner can slip behind Revit and read as a crash."""
    try:
        WindowInteropHelper(window).Owner = uiapp.MainWindowHandle
        return
    except Exception:
        pass
    try:
        from System.Diagnostics import Process
        WindowInteropHelper(window).Owner = Process.GetCurrentProcess().MainWindowHandle
    except Exception:
        pass


def _dpi(window):
    try:
        from System.Windows import PresentationSource
        matrix = PresentationSource.FromVisual(window).CompositionTarget.TransformToDevice
        return (matrix.M11 or 1.0, matrix.M22 or 1.0)
    except Exception:
        return (1.0, 1.0)


def work_area(window):
    """(left, top, width, height) of the working area of the screen the
    window is on, in WPF units.  A monitor above the primary has a negative
    top, which is exactly what keeps the parked bar on the right screen."""
    try:
        from System.Windows.Forms import Screen
        handle = WindowInteropHelper(window).Handle
        area = Screen.FromHandle(handle).WorkingArea
        scale_x, scale_y = _dpi(window)
        return (area.Left / scale_x, area.Top / scale_y,
                area.Width / scale_x, area.Height / scale_y)
    except Exception:
        rect = SystemParameters.WorkArea
        return (rect.Left, rect.Top, rect.Width, rect.Height)


def _ctrl_shift():
    try:
        mods = Keyboard.Modifiers
        return ((mods & ModifierKeys.Control) == ModifierKeys.Control and
                (mods & ModifierKeys.Shift) == ModifierKeys.Shift)
    except Exception:
        return False


# ============================================================================
# the shrink-to-taskbar drawer
# ============================================================================

class _Timer(object):
    """A DispatcherTimer behind the start() / stop() the drawer expects."""

    def __init__(self, interval_ms, tick):
        self.tick = tick
        self.timer = DispatcherTimer()
        self.timer.Interval = TimeSpan.FromMilliseconds(interval_ms)
        self.timer.Tick += self._on_tick

    def _on_tick(self, sender, args):
        self.tick()

    def start(self):
        self.timer.Start()

    def stop(self):
        self.timer.Stop()


class WindowDrawer(object):
    """Slides a window down to the bottom of its screen like a drawer closing,
    leaving its own header floating clear of the taskbar so Revit can be seen;
    the button turns into a green up arrow that opens it again.

    The state machine is tidy_core.DrawerCore, which the bench drives with a
    fake window and timer; this class is its host on a real WPF window.
    """

    def __init__(self, window, header, root, button, grips=None):
        self.window = window
        self.header = header
        self.root = root
        self.button = button
        self.grips = grips
        self.min_height = None
        self.core = core.DrawerCore(self)
        if button is not None:
            button.Click += self._clicked

    @property
    def shrunk(self):
        return self.core.shrunk

    def _clicked(self, sender, args):
        self.toggle()

    def toggle(self):
        try:
            self.core.toggle()
        except Exception:
            pass

    def expand(self):
        try:
            self.core.expand()
        except Exception:
            pass

    # host side, called by DrawerCore

    def bounds(self):
        w = self.window
        width = w.ActualWidth if w.ActualWidth > 0 else w.Width
        height = w.ActualHeight if w.ActualHeight > 0 else w.Height
        return (w.Left, w.Top, width, height)

    def set_bounds(self, top, height):
        self.window.Top = top
        self.window.Height = max(height, 1.0)

    def work_area(self):
        return work_area(self.window)

    def bar_height(self):
        try:
            return self.header.ActualHeight + 2.0
        except Exception:
            return 50.0

    def make_timer(self, interval_ms, tick):
        return _Timer(interval_ms, tick)

    def before_slide(self, shrinking):
        if not shrinking:
            return
        w = self.window
        # MinHeight and SizeToContent both veto a shrinking Height
        try:
            self.min_height = w.MinHeight
            w.SizeToContent = SizeToContent.Manual
            w.MinHeight = 0.0
        except Exception:
            pass
        # pin the body so it is clipped, not re-measured, as the window shuts
        try:
            self.root.Height = self.root.ActualHeight
            self.root.VerticalAlignment = VerticalAlignment.Top
        except Exception:
            pass
        # the grip overlay would line the parked bar with invisible handles
        try:
            if self.grips is not None:
                self.grips.Visibility = Visibility.Collapsed
        except Exception:
            pass

    def after_slide(self, shrunk):
        w = self.window
        # an animation holds its end value over every later assignment; clear
        # both, each on its own, so the window can always be moved and resized
        try:
            w.BeginAnimation(Window.TopProperty, None)
        except Exception:
            pass
        try:
            w.BeginAnimation(Window.HeightProperty, None)
        except Exception:
            pass
        try:
            self.button.Tag = "shrunk" if shrunk else "open"
        except Exception:
            pass
        if shrunk:
            return
        try:
            if self.min_height is not None:
                w.MinHeight = self.min_height
        except Exception:
            pass
        try:
            self.root.Height = Double.NaN
            self.root.VerticalAlignment = VerticalAlignment.Stretch
        except Exception:
            pass
        try:
            if self.grips is not None:
                self.grips.Visibility = Visibility.Visible
        except Exception:
            pass


# ============================================================================
# chrome
# ============================================================================

class Chrome(object):
    """Drag, close, full screen by bounds, the eight resize grips, and the
    keys: Escape closes, F11 fills the screen, Ctrl+Shift+H shrinks.  While
    the window is parked, Escape, Enter, F11 and a double click on the bar all
    open it again instead."""

    def __init__(self, window, on_close, resizable=True, full_screen=True):
        self.window = window
        self.on_close = on_close
        self.saved = None
        self.full = False
        self.drawer = None

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

    def add_drawer(self):
        find = self.window.FindName
        self.drawer = WindowDrawer(self.window, find("HeaderBar"), find("RootBorder"),
                                   find("ShrinkBtn"), find("GripLayer"))
        return self.drawer

    def _parked(self):
        return self.drawer is not None and self.drawer.shrunk

    def _drag(self, sender, args):
        try:
            if args.ClickCount == 2:
                if self._parked():
                    self.drawer.expand()
                else:
                    self._toggle_full(sender, args)
                return
        except Exception:
            pass
        if self.full and not self._parked():
            self.restore()
        try:
            self.window.DragMove()
        except Exception:
            pass

    def _close(self, sender, args):
        self.on_close()

    def _key(self, sender, args):
        try:
            if args.Key == Key.H and _ctrl_shift() and self.drawer is not None:
                self.drawer.toggle()
                args.Handled = True
                return
            if self._parked():
                if args.Key in (Key.Escape, Key.Enter, Key.F11):
                    self.drawer.expand()
                    args.Handled = True
                return
            if args.Key == Key.Escape:
                self.on_close()
            elif args.Key == Key.F11:
                self._toggle_full(sender, args)
        except Exception:
            pass

    def _toggle_full(self, sender, args):
        if self._parked():
            self.drawer.expand()
            return
        if self.full:
            self.restore()
        else:
            self.maximise()

    def maximise(self):
        window = self.window
        self.saved = (window.Left, window.Top, window.Width, window.Height)
        left, top, width, height = work_area(window)
        window.Left, window.Top, window.Width, window.Height = left, top, width, height
        self.full = True

    def restore(self):
        if self.saved:
            window = self.window
            window.Left, window.Top, window.Width, window.Height = self.saved
        self.full = False

    def _grips(self):
        spec = {
            "GripL": (-1, 0), "GripR": (1, 0), "GripT": (0, -1), "GripB": (0, 1),
            "GripTL": (-1, -1), "GripTR": (1, -1), "GripBL": (-1, 1), "GripBR": (1, 1),
        }
        for name, vector in spec.items():
            grip = self.window.FindName(name)
            if grip is not None:
                grip.DragDelta += self._make_grip(vector)

    def _make_grip(self, vector):
        horizontal, vertical = vector
        window = self.window
        chrome = self

        def handler(sender, args):
            try:
                chrome.full = False   # dragging an edge counts as leaving full screen
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
# the light / dark / auto chip
# ============================================================================

class ThemeSwitch(object):
    """The chip top right of every window.  Auto follows Revit's canvas;
    a click goes Dark, Light, then back to Auto, and is remembered."""

    def __init__(self, window, cfg, on_change=None, save=True):
        self.window = window
        self.cfg = cfg
        self.on_change = on_change
        self.save = save
        self.setting = cfg.get("theme", "follow")
        if self.setting not in core.THEME_CYCLE:
            self.setting = "follow"
        chip = window.FindName("ThemeChip")
        if chip is not None:
            chip.Click += self._clicked
        self.paint()

    def palette(self):
        return theme_mod.resolve(self.setting)

    def paint(self):
        palette = self.palette()
        theme_mod.apply(self.window, palette)
        try:
            label = self.window.FindName("ThemeLabel")
            label.Text = core.THEME_LABELS.get(self.setting, "Auto")
        except Exception:
            pass
        return palette

    def set(self, setting, save=False):
        self.setting = setting if setting in core.THEME_CYCLE else "follow"
        self.cfg["theme"] = self.setting
        self.paint()
        if save:
            self._save()
        if self.on_change is not None:
            try:
                self.on_change(self.setting)
            except Exception:
                pass

    def _save(self):
        try:
            saved = core.load_settings()
            saved["theme"] = self.setting
            core.save_settings(saved)
        except Exception:
            pass

    def _clicked(self, sender, args):
        self.set(core.next_theme(self.setting), save=self.save)


# ============================================================================
# small helpers
# ============================================================================

def brush(window, key):
    try:
        return window.Resources[key]
    except Exception:
        return SolidColorBrush(ColorConverter.ConvertFromString("#EEF0F4"))


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
# results and preview
# ============================================================================

COLOUR_FOR = {"done": "GreenBrush", "clash": "OrangeBrush", "skip": "BlueBrush",
              "fail": "RedBrush"}


class ResultsWindow(object):
    """Themed report, and the preview of a layout already written but not yet
    kept.  Rows are built as WPF elements in code, never bound to Python
    objects, which is unreliable across IronPython engine versions.

    As a preview, the answer is "keep", "undo" or "flip"; closing it any other
    way is "undo", so nothing stays in the model by accident.  Shrinking it
    shows the model behind it to judge the layout; a modal window still holds
    Revit while it is open, so it shows the model rather than freeing it.
    """

    def __init__(self, cfg, summary, detail, rows, status, can_flip=False, final=True,
                 uiapp=None):
        self.cfg = cfg
        self.rows = rows
        self.final = final
        self.choice = "keep" if final else "undo"
        self.window = load_window("TagTidyResults.xaml",
                                  theme_mod.resolve(cfg.get("theme", "follow")))
        self.chrome = Chrome(self.window, self._dismiss, resizable=True, full_screen=True)
        self.drawer = self.chrome.add_drawer()
        self.theme = ThemeSwitch(self.window, cfg, on_change=self._repaint)
        if uiapp is not None:
            own_to_revit(self.window, uiapp)

        find = self.window.FindName
        find("VersionText").Text = "v" + core.__version__
        find("SummaryText").Text = summary
        find("DetailText").Text = detail
        find("StatusText").Text = status
        find("CopyBtn").Click += self._copy
        find("KeepBtn").Click += self._keep
        find("UndoBtn").Click += self._undo
        find("FlipBtn").Click += self._flip
        if final:
            find("KeepBtn").Content = "Close"
            find("UndoBtn").Visibility = Visibility.Collapsed
            find("FlipBtn").Visibility = Visibility.Collapsed
        elif not can_flip:
            find("FlipBtn").Visibility = Visibility.Collapsed
        self._build_rows()

    def _repaint(self, setting):
        # row ticks and text carry brushes set in code, which a palette swap
        # cannot reach, so the rows are rebuilt
        self._build_rows()

    def _build_rows(self):
        panel = self.window.FindName("RowsPanel")
        panel.Children.Clear()
        for row in self.rows:
            panel.Children.Add(self._row(row))

    def _row(self, row):
        kind, label, note = row
        grid = Grid()
        grid.Margin = Thickness(0, 2, 0, 2)
        widths = ((GridLength(13), 0), (GridLength(1, GridUnitType.Star), 170),
                  (GridLength(2.4, GridUnitType.Star), 240))
        for width, minimum in widths:
            column = ColumnDefinition()
            column.Width = width
            if minimum:
                column.MinWidth = minimum
            grid.ColumnDefinitions.Add(column)

        tick = Border()
        tick.Width = 4
        tick.Height = 14
        tick.CornerRadius = CornerRadius(2)
        tick.Margin = Thickness(0, 0, 9, 0)
        tick.Background = brush(self.window, COLOUR_FOR.get(kind, "MutedBrush"))
        Grid.SetColumn(tick, 0)
        grid.Children.Add(tick)

        left = TextBlock()
        left.Text = label
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

    def _copy(self, sender, args):
        lines = ["{0}\t{1}\t{2}".format(kind, label, note) for kind, label, note in self.rows]
        try:
            Clipboard.SetText("\n".join(lines))
            self.window.FindName("StatusText").Text = "{0} rows copied to the clipboard".format(
                len(lines))
        except Exception:
            self.window.FindName("StatusText").Text = "The clipboard refused the list"

    def _finish(self, choice):
        self.choice = choice
        try:
            self.window.Close()
        except Exception:
            pass

    def _keep(self, sender, args):
        self._finish("keep")

    def _undo(self, sender, args):
        self._finish("undo")

    def _flip(self, sender, args):
        self._finish("flip")

    def _dismiss(self):
        self._finish("keep" if self.final else "undo")

    def show(self):
        self.window.ShowDialog()
        return self.choice


def show_results(cfg, summary, detail, rows, status, can_flip=False, final=True, uiapp=None):
    return ResultsWindow(cfg, summary, detail, rows, status, can_flip, final, uiapp).show()


class Presenter(object):
    """What tidy_ops talks to, so it never imports a window itself."""

    def __init__(self, uiapp):
        self.uiapp = uiapp

    def show_results(self, cfg, summary, detail, rows, status, can_flip=False, final=True):
        return show_results(cfg, summary, detail, rows, status, can_flip, final, self.uiapp)


# ============================================================================
# settings
# ============================================================================

SIDE_ITEMS = (
    ("auto", "Whichever side is clearer"),
    ("left", "Always to the left"),
    ("right", "Always to the right"),
    ("point", "Where I click"),
)

SIDE_NOTES = {
    "auto": "Both sides are tried and the clearer one kept.",
    "left": "Leaders run left from their targets to the column.",
    "right": "Leaders run right from their targets to the column.",
    "point": "You click where the top of the column goes. The whole selection "
             "becomes one column there.",
}

ALIGN_ITEMS = (
    ("leader", "The edge facing the leaders"),
    ("left", "Their left edges, always"),
)

ANGLE_ITEMS = (
    ("45", "45 degrees"),
    ("30", "30 degrees"),
    ("60", "60 degrees"),
    ("90", "90 degrees, straight up or down"),
    ("free", "Free, straight to the target"),
)

ANGLE_NOTES = {
    "45": "Each leader leaves the tag level, then turns 45 degrees to its target.",
    "30": "A shallower turn, which needs the column further out.",
    "60": "A steeper turn, which keeps the column closer in.",
    "90": "Each leader turns straight up or down onto its target.",
    "free": "Each leader leaves the tag level, then runs straight to its target.",
}

NO_LEADER_ITEMS = (("switch_on", "Switch the leader on"), ("skip", "Leave them where they are"))
PINNED_ITEMS = (("unpin", "Unpin, move, and pin again"), ("skip", "Leave them where they are"))
END_ITEMS = (("keep", "Keep them attached"), ("free", "Make them free ends where they are"))
PREVIEW_ITEMS = (
    ("always", "Always, so I can keep, undo or flip it"),
    ("needed", "Only when something needs a look"),
    ("never", "Never, just keep it"),
)
THEME_ITEMS = (("follow", "Auto, following Revit's canvas"), ("dark", "Dark"), ("light", "Light"))

NUMBER_BOXES = (
    ("GapBox", "gap_mm", "the gap between tags"),
    ("ShoulderBox", "min_shoulder_mm", "the shortest shoulder"),
    ("ColumnClearBox", "column_clear_mm", "the clearance from the targets"),
    ("ClusterBox", "cluster_mm", "the separate-columns distance"),
    ("ReachBox", "reach_mm", "the longest level leader run"),
    ("ClearanceBox", "clearance_mm", "the clearance round each tag"),
    ("SlotBox", "slot_depth", "the slots a tag may move"),
    ("StepBox", "column_step_mm", "the column step"),
    ("ShiftBox", "max_shift_mm", "the furthest the column moves"),
    ("BudgetBox", "budget_s", "the search time"),
)

CHECKS = (
    ("SecondChk", "second_column"),
    ("KeepChk", "keep_single"),
    ("ObsAnnotationChk", "obs_annotation"),
    ("ObsPipesChk", "obs_pipes"),
    ("ObsDuctsChk", "obs_ducts"),
    ("ObsTraysChk", "obs_trays"),
    ("ObsConduitChk", "obs_conduit"),
    ("ObsWallsChk", "obs_walls"),
    ("ObsGridsChk", "obs_grids"),
    ("ObsOtherChk", "obs_other"),
    ("ObsLinksChk", "obs_links"),
    ("PromptChk", "prompt_when_empty"),
    ("SpatialChk", "include_spatial_tags"),
    ("DebugChk", "debug"),
)

COMBOS = (
    ("SideCombo", "side", SIDE_ITEMS),
    ("AlignCombo", "align", ALIGN_ITEMS),
    ("AngleCombo", "leg_angle", ANGLE_ITEMS),
    ("NoLeaderCombo", "no_leader", NO_LEADER_ITEMS),
    ("PinnedCombo", "pinned", PINNED_ITEMS),
    ("EndCombo", "leader_end", END_ITEMS),
    ("PreviewCombo", "preview", PREVIEW_ITEMS),
    ("ThemeCombo", "theme", THEME_ITEMS),
)


class SettingsWindow(object):

    def __init__(self, cfg, uiapp=None):
        self.cfg = dict(cfg)
        self.uiapp = uiapp
        self.saved = False
        self.syncing = False
        self.window = load_window("TagTidySettings.xaml",
                                  theme_mod.resolve(self.cfg.get("theme", "follow")))
        self.chrome = Chrome(self.window, self._cancel_now, resizable=True, full_screen=True)
        self.drawer = self.chrome.add_drawer()
        self.theme = ThemeSwitch(self.window, self.cfg, on_change=self._chip_changed)
        if uiapp is not None:
            own_to_revit(self.window, uiapp)

        find = self.window.FindName
        find("VersionText").Text = "v" + core.__version__
        find("ApplyBtn").Click += self._apply
        find("CancelBtn").Click += self._cancel
        find("DefaultsBtn").Click += self._defaults
        find("ShortcutBtn").Click += self._shortcuts
        find("SideCombo").SelectionChanged += self._side_picked
        find("AngleCombo").SelectionChanged += self._angle_picked
        find("ThemeCombo").SelectionChanged += self._theme_picked
        self._load(self.cfg)

    def _load(self, cfg):
        find = self.window.FindName
        self.syncing = True
        try:
            for name, key, _ in NUMBER_BOXES:
                find(name).Text = str(cfg.get(key, core.DEFAULTS[key]))
            for name, key in CHECKS:
                find(name).IsChecked = core.as_bool(cfg, key)
            for name, key, items in COMBOS:
                fill_combo(find(name), items, cfg.get(key, core.DEFAULTS[key]))
            find("SideNote").Text = SIDE_NOTES.get(cfg.get("side"), "")
            find("AngleNote").Text = ANGLE_NOTES.get(cfg.get("leg_angle"), "")
        finally:
            self.syncing = False

    def _side_picked(self, sender, args):
        self.window.FindName("SideNote").Text = SIDE_NOTES.get(combo_value(sender, "auto"), "")

    def _angle_picked(self, sender, args):
        self.window.FindName("AngleNote").Text = ANGLE_NOTES.get(combo_value(sender, "45"), "")

    def _theme_picked(self, sender, args):
        if self.syncing:
            return
        self.syncing = True   # the combo is the source; do not refill it from itself
        try:
            self.theme.set(combo_value(sender, self.theme.setting), save=False)
        finally:
            self.syncing = False

    def _chip_changed(self, setting):
        """The chip and the Theme combo say the same thing."""
        if self.syncing:
            return
        self.syncing = True
        try:
            fill_combo(self.window.FindName("ThemeCombo"), THEME_ITEMS, setting)
        finally:
            self.syncing = False

    def _collect(self):
        find = self.window.FindName
        cfg = dict(self.cfg)
        for name, key, _ in NUMBER_BOXES:
            cfg[key] = find(name).Text.strip()
        for name, key in CHECKS:
            cfg[key] = "1" if find(name).IsChecked else "0"
        for name, key, _ in COMBOS:
            cfg[key] = combo_value(find(name), core.DEFAULTS[key])
        return cfg

    def _apply(self, sender, args):
        cfg = self._collect()
        status = self.window.FindName("StatusText")
        for name, key, words in NUMBER_BOXES:
            try:
                value = float(cfg[key])
            except Exception:
                status.Text = "{0} has to be a number.".format(words.capitalize())
                return
            low, high = core.NUMBERS[key]
            if value < low or value > high:
                status.Text = "{0} has to be between {1:g} and {2:g}.".format(
                    words.capitalize(), low, high)
                return
            cfg[key] = "{0:g}".format(value)
        try:
            path = core.save_settings(cfg)
        except Exception as error:
            status.Text = "Could not write the settings: {0}".format(error)
            return
        self.cfg = cfg
        self.saved = True
        status.Text = "Saved to " + path
        self._cancel_now()

    def _defaults(self, sender, args):
        defaults = dict(core.DEFAULTS)
        defaults["theme"] = self.theme.setting
        self._load(defaults)
        self.window.FindName("StatusText").Text = "Defaults loaded. Apply to keep them."

    def _cancel(self, sender, args):
        self._cancel_now()

    def _cancel_now(self):
        try:
            self.window.Close()
        except Exception:
            pass

    def _shortcuts(self, sender, args):
        try:
            from Autodesk.Revit.UI import RevitCommandId, PostableCommand
            command = RevitCommandId.LookupPostableCommandId(PostableCommand.KeyboardShortcuts)
            self.uiapp.PostCommand(command)
            self._cancel_now()
        except Exception:
            self.window.FindName("StatusText").Text = (
                "View > User Interface > Keyboard Shortcuts, then search RevoBIM Tag Tidy.")

    def show(self):
        self.window.ShowDialog()
        return self.saved
