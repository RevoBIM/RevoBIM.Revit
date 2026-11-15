# -*- coding: utf-8 -*-
"""RevoBIM Sheet Name Push.

Sheet browser, editor and parameter push in one window:

  * tick sheets, click text to highlight, ctrl-click to add to the
    selection, shift-click for a range
  * double-click a sheet number or name to edit it; edits are staged
    (shown orange) until Apply Edits is pressed
  * duplicate sheet numbers flagged red, with a filter to isolate them
  * Find and Replace, and Prefix / Suffix, staged the same way
  * push sheet-name segments (split on "_") into three target
    parameters, chosen in Settings

Compatible with Revit 2021 - 2027. No f-strings, no bare .IntegerValue,
no System.Uri.
"""

import os
import re

from pyrevit import revit, DB, forms, script

import clr
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

from System.Windows import (GridLength, GridUnitType, Thickness, FontWeights,
                            TextWrapping, TextTrimming, Visibility,
                            VerticalAlignment, CornerRadius)
from System.Windows.Controls import (Grid, ColumnDefinition, TextBlock, TextBox,
                                     CheckBox, Border, StackPanel, Orientation)
from System.Windows.Input import Keyboard, ModifierKeys, Key
from System.Windows.Media import SolidColorBrush, Color, Brushes
from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption
from System.IO import MemoryStream, File

__version__ = "2.2.2"

doc = revit.doc

BUNDLE_DIR = os.path.dirname(__file__)
XAML_MAIN = os.path.join(BUNDLE_DIR, "ui.xaml")
XAML_RESULTS = os.path.join(BUNDLE_DIR, "results.xaml")
XAML_SETTINGS = os.path.join(BUNDLE_DIR, "settings.xaml")
XAML_FIND = os.path.join(BUNDLE_DIR, "findreplace.xaml")
XAML_AFFIX = os.path.join(BUNDLE_DIR, "affix.xaml")

ICON_MAIN = os.path.join(BUNDLE_DIR, "icon.png")
ICON_GEAR = os.path.join(BUNDLE_DIR, "gear.png")
ICON_FIND = os.path.join(BUNDLE_DIR, "findreplace.png")
ICON_AFFIX = os.path.join(BUNDLE_DIR, "affix.png")

DEFAULT_PARAMS = ["BGL_Sheet Title 1", "BGL_Sheet Title 2", "BGL_Sheet Title 3"]

SETTINGS_DIR = os.path.join(os.getenv("APPDATA") or "", "RevoBIM")
SETTINGS_FILE = os.path.join(SETTINGS_DIR, "sheet_management.txt")
SETTINGS_VERSION = "3"

MODE_LABELS = {
    "upper": "UPPERCASE",
    "title": "Camel Case (Capitalize Each Word)",
    "none": "Don't Format Text",
}

# --- house palette ---
C_TEXT = Color.FromRgb(0xE4, 0xE4, 0xE4)
C_MUTED = Color.FromRgb(0x9A, 0x9A, 0x9E)
C_BLUE = Color.FromRgb(0x4F, 0xA3, 0xE3)
C_ORANGE = Color.FromRgb(0xE8, 0x91, 0x2D)
C_GREEN = Color.FromRgb(0x3F, 0xA7, 0x5A)
C_GREEN_HOVER = Color.FromRgb(0x4E, 0xC0, 0x6D)
C_RED = Color.FromRgb(0xD9, 0x53, 0x4F)
C_SEL = Color.FromRgb(0x2B, 0x54, 0x73)
C_BORDER = Color.FromRgb(0x3E, 0x3E, 0x42)

B_SEL = SolidColorBrush(C_SEL)
B_GREEN = SolidColorBrush(C_GREEN)
B_ORANGE = SolidColorBrush(C_ORANGE)
B_TRANSPARENT = Brushes.Transparent

STATUS_COLORS = {"OK": C_GREEN, "skipped (no segment)": C_ORANGE}

CHAR_PX = 7.1


# ===================== helpers =====================

def eid_value(element_id):
    """ElementId integer across Revit 2021-2027.

    .IntegerValue was deprecated in 2024 for .Value (Int64) and removed
    in 2026, so prefer .Value and fall back.
    """
    if element_id is None:
        return 0
    try:
        return element_id.Value
    except Exception:
        pass
    try:
        return element_id.IntegerValue
    except Exception:
        return 0


def load_bitmap(path):
    """Load a PNG from bytes - never System.Uri, which throws on 2025+."""
    try:
        if not os.path.exists(path):
            return None
        stream = MemoryStream(File.ReadAllBytes(path))
        bmp = BitmapImage()
        bmp.BeginInit()
        bmp.StreamSource = stream
        bmp.CacheOption = BitmapCacheOption.OnLoad
        bmp.EndInit()
        bmp.Freeze()
        return bmp
    except Exception:
        return None


def set_element_name(elem, value):
    """Rename an element - which route works varies by IronPython version."""
    try:
        elem.Name = value
    except Exception:
        try:
            DB.Element.Name.SetValue(elem, value)
        except Exception:
            return False
    try:
        return elem.Name == value
    except Exception:
        return False


# ---------- settings ----------

def load_settings():
    """Plain key=value under %APPDATA%\\RevoBIM - falls back key by key."""
    cfg = {
        "settings_version": SETTINGS_VERSION,
        "param_1": DEFAULT_PARAMS[0],
        "param_2": DEFAULT_PARAMS[1],
        "param_3": DEFAULT_PARAMS[2],
        "format_mode": "upper",
    }
    try:
        if os.path.exists(SETTINGS_FILE):
            handle = open(SETTINGS_FILE, "r")
            try:
                for line in handle:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    key = key.strip()
                    if key in cfg:
                        cfg[key] = value.strip()
            finally:
                handle.close()
    except Exception:
        pass

    if cfg.get("format_mode") not in MODE_LABELS:
        cfg["format_mode"] = "upper"
    return cfg


def save_settings(cfg):
    try:
        if not os.path.isdir(SETTINGS_DIR):
            os.makedirs(SETTINGS_DIR)
        handle = open(SETTINGS_FILE, "w")
        try:
            handle.write("# RevoBIM Sheet Name Push settings\n")
            for key in sorted(cfg.keys()):
                handle.write("{0}={1}\n".format(key, cfg[key]))
        finally:
            handle.close()
        return True
    except Exception:
        return False


def sheet_text_parameters():
    """Writable string parameters found on sheets, for the Settings lists."""
    names = set()
    try:
        sheets = DB.FilteredElementCollector(doc) \
            .OfClass(DB.ViewSheet).WhereElementIsNotElementType().ToElements()
        for sheet in list(sheets)[:40]:
            for param in sheet.Parameters:
                try:
                    if param.IsReadOnly:
                        continue
                    if param.StorageType != DB.StorageType.String:
                        continue
                    names.add(param.Definition.Name)
                except Exception:
                    continue
    except Exception:
        pass
    return sorted(names)


def text_cell(text, column, color=None, bold=False, size=12, wrap=False):
    tb = TextBlock()
    tb.Text = "" if text is None else str(text)
    tb.FontSize = size
    tb.Margin = Thickness(0, 0, 10, 0)
    tb.Foreground = SolidColorBrush(color if color is not None else C_TEXT)
    if bold:
        tb.FontWeight = FontWeights.SemiBold
    if wrap:
        tb.TextWrapping = TextWrapping.Wrap
    else:
        tb.TextTrimming = TextTrimming.CharacterEllipsis
    Grid.SetColumn(tb, column)
    return tb


def preview_line(before, after):
    """One 'old -> new' line for the Find/Affix preview panes."""
    panel = StackPanel()
    panel.Orientation = Orientation.Horizontal
    panel.Margin = Thickness(0, 2, 0, 2)

    old = TextBlock()
    old.Text = before
    old.FontSize = 11
    old.Foreground = SolidColorBrush(C_MUTED)

    arrow = TextBlock()
    arrow.Text = "   \u2192   "
    arrow.FontSize = 11
    arrow.Foreground = SolidColorBrush(C_MUTED)

    new = TextBlock()
    new.Text = after
    new.FontSize = 11
    new.FontWeight = FontWeights.SemiBold
    new.Foreground = SolidColorBrush(C_ORANGE)

    panel.Children.Add(old)
    panel.Children.Add(arrow)
    panel.Children.Add(new)
    return panel


class ThemedWindow(forms.WPFWindow):
    """Shared chrome: draggable header, icon, version."""

    def _init_chrome(self, icon_path=None):
        try:
            self.tb_version.Text = "v" + __version__
        except Exception:
            pass
        try:
            bmp = load_bitmap(icon_path or ICON_MAIN)
            if bmp is not None:
                self.img_icon.Source = bmp
        except Exception:
            pass

    def header_drag(self, sender, args):
        try:
            self.DragMove()
        except Exception:
            pass


# ===================== Settings window =====================

class SettingsWindow(ThemedWindow):

    def __init__(self, cfg):
        forms.WPFWindow.__init__(self, XAML_SETTINGS)
        self._init_chrome()
        self.cfg = dict(cfg)
        self.saved = False

        available = sheet_text_parameters()
        self.boxes = [self.cb_p1, self.cb_p2, self.cb_p3]
        keys = ["param_1", "param_2", "param_3"]

        for box, key in zip(self.boxes, keys):
            current = self.cfg.get(key, "")
            items = list(available)
            if current and current not in items:
                items.insert(0, current)
            if not items:
                items = [current]
            box.ItemsSource = items
            try:
                box.SelectedItem = current
            except Exception:
                pass

        if not available:
            self.tb_note.Text = (
                "No writable text parameters were found on the sheets in this "
                "model. The saved names are kept - add the parameters to sheets "
                "and they will appear here.")

    def defaults_click(self, sender, args):
        for box, name in zip(self.boxes, DEFAULT_PARAMS):
            items = list(box.ItemsSource or [])
            if name not in items:
                items.insert(0, name)
                box.ItemsSource = items
            box.SelectedItem = name

    def apply_click(self, sender, args):
        chosen = []
        for box in self.boxes:
            value = box.SelectedItem
            chosen.append("" if value is None else str(value).strip())

        if not any(chosen):
            self.tb_note.Text = "Choose at least one target parameter."
            return

        self.cfg["param_1"], self.cfg["param_2"], self.cfg["param_3"] = chosen
        self.cfg["settings_version"] = SETTINGS_VERSION
        save_settings(self.cfg)
        self.saved = True
        self.DialogResult = True
        self.Close()

    def cancel_click(self, sender, args):
        self.DialogResult = False
        self.Close()


# ===================== Find and Replace =====================

class FindReplaceWindow(ThemedWindow):

    def __init__(self, targets):
        forms.WPFWindow.__init__(self, XAML_FIND)
        self._init_chrome(ICON_FIND)
        self.targets = targets            # list of record dicts
        self.changes = {}                 # id -> {"number":.., "name":..}
        self.tb_scope.Text = "Applies to the {0} sheet(s) currently ticked or shown.".format(
            len(targets))
        self.refresh_preview()

    def _fields(self):
        if self.rb_both.IsChecked:
            return ["number", "name"]
        if self.rb_number.IsChecked:
            return ["number"]
        return ["name"]

    def _replace(self, text, find, repl):
        if not find:
            return text
        if self.cb_case.IsChecked:
            return text.replace(find, repl)
        return re.sub(re.escape(find), repl.replace("\\", "\\\\"),
                      text, flags=re.IGNORECASE)

    def compute(self):
        find = self.tb_find.Text or ""
        repl = self.tb_replace.Text or ""
        changes = {}
        if not find:
            return changes
        for rec in self.targets:
            row = {}
            for field in self._fields():
                before = rec["current"][field]
                after = self._replace(before, find, repl)
                if after != before:
                    row[field] = after
            if row:
                changes[rec["id"]] = row
        return changes

    def refresh_preview(self):
        self.changes = self.compute()
        self.sp_preview.Children.Clear()

        shown = 0
        for rec in self.targets:
            row = self.changes.get(rec["id"])
            if not row:
                continue
            for field in ("number", "name"):
                if field in row:
                    self.sp_preview.Children.Add(
                        preview_line(rec["current"][field], row[field]))
                    shown += 1
            if shown > 200:
                break

        self.tb_status.Text = "{0} change(s) on {1} sheet(s).".format(
            shown, len(self.changes)) if self.changes else "No matches."

    def preview_changed(self, sender, args):
        try:
            self.refresh_preview()
        except Exception:
            pass

    def apply_click(self, sender, args):
        if not self.changes:
            self.tb_status.Text = "Nothing to stage."
            return
        self.DialogResult = True
        self.Close()

    def cancel_click(self, sender, args):
        self.changes = {}
        self.DialogResult = False
        self.Close()


# ===================== Prefix / Suffix =====================

class AffixWindow(ThemedWindow):

    def __init__(self, targets):
        forms.WPFWindow.__init__(self, XAML_AFFIX)
        self._init_chrome(ICON_AFFIX)
        self.targets = targets
        self.changes = {}
        self.tb_scope.Text = "Applies to the {0} sheet(s) currently ticked or shown.".format(
            len(targets))
        self.refresh_preview()

    def _fields(self):
        if self.rb_both.IsChecked:
            return ["number", "name"]
        if self.rb_number.IsChecked:
            return ["number"]
        return ["name"]

    def _apply(self, text, prefix, suffix):
        if self.cb_remove.IsChecked:
            if prefix and text.startswith(prefix):
                text = text[len(prefix):]
            if suffix and text.endswith(suffix):
                text = text[:len(text) - len(suffix)]
            return text
        return prefix + text + suffix

    def compute(self):
        prefix = self.tb_prefix.Text or ""
        suffix = self.tb_suffix.Text or ""
        changes = {}
        if not prefix and not suffix:
            return changes
        for rec in self.targets:
            row = {}
            for field in self._fields():
                before = rec["current"][field]
                after = self._apply(before, prefix, suffix)
                if after != before:
                    row[field] = after
            if row:
                changes[rec["id"]] = row
        return changes

    def refresh_preview(self):
        self.changes = self.compute()
        self.sp_preview.Children.Clear()

        shown = 0
        for rec in self.targets:
            row = self.changes.get(rec["id"])
            if not row:
                continue
            for field in ("number", "name"):
                if field in row:
                    self.sp_preview.Children.Add(
                        preview_line(rec["current"][field], row[field]))
                    shown += 1
            if shown > 200:
                break

        self.tb_status.Text = "{0} change(s) on {1} sheet(s).".format(
            shown, len(self.changes)) if self.changes else "Nothing to change."

    def preview_changed(self, sender, args):
        try:
            self.refresh_preview()
        except Exception:
            pass

    def apply_click(self, sender, args):
        if not self.changes:
            self.tb_status.Text = "Nothing to stage."
            return
        self.DialogResult = True
        self.Close()

    def cancel_click(self, sender, args):
        self.changes = {}
        self.DialogResult = False
        self.Close()


# ===================== Results =====================

class ResultsWindow(ThemedWindow):

    def __init__(self, log_rows, mode_label, sheet_count):
        forms.WPFWindow.__init__(self, XAML_RESULTS)
        self._init_chrome()

        ok = 0
        problems = 0
        for row in log_rows:
            for _, _, status in row["results"]:
                if status == "OK":
                    ok += 1
                elif status != "skipped (no segment)":
                    problems += 1

        self.tb_summary.Text = \
            "{0} sheet(s) - {1} parameter(s) written - text format: {2}".format(
                sheet_count, ok, mode_label)
        self.tb_footer.Text = ("{0} item(s) need a look".format(problems)
                               if problems else "Everything written cleanly.")
        self._size_columns(log_rows)
        for row in log_rows:
            for param_name, value, status in row["results"]:
                self.sp_results.Children.Add(
                    self._build_row(row["number"], row["name"],
                                    param_name, value, status))

    def _size_columns(self, log_rows):
        try:
            longest_num = max([len(str(r["number"])) for r in log_rows] or [10])
            longest_name = max([len(str(r["name"])) for r in log_rows] or [20])
            self._num_w = min(max(longest_num * CHAR_PX + 20, 110), 300)
            self._name_w = min(max(longest_name * CHAR_PX + 20, 180), 620)
            self.col_num.Width = GridLength(self._num_w)
            self.col_name.Width = GridLength(self._name_w)
            total = self._num_w + self._name_w + 150 + 130 + 170 + 34 + 20
            try:
                from System.Windows import SystemParameters
                screen_w = SystemParameters.WorkArea.Width - 80
            except Exception:
                screen_w = 1600
            self.Width = max(620, min(total, screen_w))
        except Exception:
            self._num_w, self._name_w = 120, 200

    def _build_row(self, number, name, param_name, value, status):
        grid = Grid()
        grid.Margin = Thickness(6, 3, 6, 3)
        for w in [GridLength(getattr(self, "_num_w", 120)),
                  GridLength(getattr(self, "_name_w", 200)),
                  GridLength(150), GridLength(130),
                  GridLength(1, GridUnitType.Star)]:
            col = ColumnDefinition()
            col.Width = w
            grid.ColumnDefinitions.Add(col)

        grid.Children.Add(text_cell(number, 0, bold=True, size=11))
        grid.Children.Add(text_cell(name, 1, size=11))
        grid.Children.Add(text_cell(param_name, 2, color=C_MUTED, size=11))
        grid.Children.Add(text_cell(value if value is not None else "-", 3, size=11))
        grid.Children.Add(text_cell(status, 4,
                                    color=STATUS_COLORS.get(status, C_RED),
                                    bold=True, size=11, wrap=True))
        return grid

    def close_click(self, sender, args):
        self.Close()


# ===================== Main window =====================

class SheetNamePushWindow(ThemedWindow):

    def __init__(self, records, preselected_ids, cfg):
        forms.WPFWindow.__init__(self, XAML_MAIN)
        self._init_chrome()
        self.cfg = cfg

        self.records = records
        self.by_id = dict((r["id"], r) for r in records)
        self.preselected_ids = set(preselected_ids or [])
        self.ticked_ids = set(self.preselected_ids)
        self.highlighted = set()
        self.anchor_id = None
        self.edits = {}                      # id -> {"number":.., "name":..}
        self.isolated = bool(self.preselected_ids)
        self.dupes_only = False
        self.result_sheets = []
        self.format_mode = cfg.get("format_mode", "upper")
        self.pushed = False
        self._building = False
        self._visible_order = []

        for name, path in (("img_gear", ICON_GEAR),
                           ("img_find", ICON_FIND),
                           ("img_affix", ICON_AFFIX)):
            try:
                bmp = load_bitmap(path)
                if bmp is not None:
                    getattr(self, name).Source = bmp
            except Exception:
                pass

        self._size_columns()

        # restore the text format chosen last run
        try:
            if self.format_mode == "title":
                self.rb_title.IsChecked = True
            elif self.format_mode == "none":
                self.rb_none.IsChecked = True
            else:
                self.rb_upper.IsChecked = True
        except Exception:
            pass

        if self.preselected_ids:
            self.cb_show_all.Visibility = Visibility.Visible
            self.cb_show_all.IsChecked = False
            self.tb_status.Text = "{0} sheet(s) selected in the Project Browser.".format(
                len(self.preselected_ids))
        else:
            self.tb_status.Text = "Showing all sheets. Double-click a cell to edit it."

        self.rebuild_rows()

    # ---------- current values ----------
    def current(self, rec, field):
        return self.edits.get(rec["id"], {}).get(field, rec[field])

    def is_edited(self, rec, field):
        return field in self.edits.get(rec["id"], {})

    def duplicate_numbers(self):
        """Sheet numbers used more than once, counting staged edits."""
        seen = {}
        for rec in self.records:
            num = self.current(rec, "number").strip().lower()
            seen[num] = seen.get(num, 0) + 1
        return set(n for n, count in seen.items() if count > 1 and n)

    # ---------- sizing ----------
    def _size_columns(self):
        try:
            longest_num = max([len(r["number"]) for r in self.records] or [12])
            self._num_w = min(max(longest_num * CHAR_PX + 30, 130), 340)
            self.col_hdr_number.Width = GridLength(self._num_w)
        except Exception:
            self._num_w = 170

    # ---------- filtering ----------
    def visible_records(self):
        recs = self.records
        if self.isolated and self.preselected_ids:
            recs = [r for r in recs if r["id"] in self.preselected_ids]

        if self.dupes_only:
            dupes = self.duplicate_numbers()
            recs = [r for r in recs
                    if self.current(r, "number").strip().lower() in dupes]

        text = ""
        try:
            text = (self.tb_filter.Text or "").strip().lower()
        except Exception:
            pass
        if text:
            recs = [r for r in recs
                    if text in self.current(r, "number").lower()
                    or text in self.current(r, "name").lower()]
        return recs

    # ---------- rows ----------
    def rebuild_rows(self):
        self._building = True
        try:
            self.sp_sheets.Children.Clear()
            recs = self.visible_records()
            self._visible_order = [r["id"] for r in recs]
            dupes = self.duplicate_numbers()

            for rec in recs:
                self.sp_sheets.Children.Add(self._build_row(rec, dupes))

            self.tb_count.Text = \
                "{0} shown / {1} ticked / {2} edited / {3} in project".format(
                    len(recs), len(self.ticked_ids), len(self.edits),
                    len(self.records))
            self._refresh_apply_button()
        finally:
            self._building = False

    def _build_row(self, rec, dupes):
        wrapper = Border()
        wrapper.CornerRadius = CornerRadius(3)
        wrapper.Padding = Thickness(6, 3, 6, 3)
        wrapper.Margin = Thickness(0, 1, 0, 1)
        wrapper.Background = B_SEL if rec["id"] in self.highlighted else B_TRANSPARENT
        wrapper.Tag = rec["id"]

        grid = Grid()
        for w in [GridLength(26), GridLength(getattr(self, "_num_w", 170)),
                  GridLength(1, GridUnitType.Star)]:
            col = ColumnDefinition()
            col.Width = w
            grid.ColumnDefinitions.Add(col)

        cb = CheckBox()
        cb.IsChecked = rec["id"] in self.ticked_ids
        cb.Tag = rec["id"]
        cb.Click += self.row_ticked
        Grid.SetColumn(cb, 0)
        grid.Children.Add(cb)

        is_dupe = self.current(rec, "number").strip().lower() in dupes
        grid.Children.Add(self._cell(rec, "number", 1, is_dupe))
        grid.Children.Add(self._cell(rec, "name", 2, False))

        wrapper.Child = grid
        wrapper.MouseLeftButtonDown += self.row_click
        return wrapper

    def _cell(self, rec, field, column, is_dupe):
        """A cell holding a TextBlock and a hidden TextBox editor."""
        host = Grid()
        Grid.SetColumn(host, column)

        value = self.current(rec, field)

        label = TextBlock()
        label.Text = value
        label.FontSize = 12
        label.Margin = Thickness(0, 0, 10, 0)
        label.TextTrimming = TextTrimming.CharacterEllipsis
        label.VerticalAlignment = VerticalAlignment.Center

        if is_dupe:
            label.Foreground = SolidColorBrush(C_RED)
            label.FontWeight = FontWeights.SemiBold
            label.ToolTip = "This sheet number is already in use"
        elif self.is_edited(rec, field):
            label.Foreground = SolidColorBrush(C_ORANGE)
            label.FontWeight = FontWeights.SemiBold
            label.ToolTip = "Edited - was: " + rec[field]
        elif field == "number":
            label.Foreground = SolidColorBrush(
                C_BLUE if rec["id"] in self.preselected_ids else C_TEXT)
            label.FontWeight = FontWeights.SemiBold
        else:
            label.Foreground = SolidColorBrush(C_TEXT)

        editor = TextBox()
        editor.Text = value
        editor.Visibility = Visibility.Collapsed
        editor.Tag = (rec["id"], field)
        try:
            editor.Style = self.Resources["CellEditor"]
        except Exception:
            pass
        editor.VerticalAlignment = VerticalAlignment.Center
        editor.KeyDown += self.editor_key
        editor.LostFocus += self.editor_commit

        host.Children.Add(label)
        host.Children.Add(editor)

        label.Tag = editor
        label.MouseLeftButtonDown += self.cell_click
        return host

    # ---------- interaction ----------
    def row_click(self, sender, args):
        """Click anywhere on a row to highlight; shift extends, ctrl adds."""
        if self._building:
            return
        try:
            sid = sender.Tag
        except Exception:
            return
        self._select(sid, shift=self._shift_down(), ctrl=self._ctrl_down())
        args.Handled = False

    def cell_click(self, sender, args):
        """Single click highlights, double click opens the editor."""
        if self._building:
            return
        try:
            if args.ClickCount >= 2:
                editor = sender.Tag
                sender.Visibility = Visibility.Collapsed
                editor.Visibility = Visibility.Visible
                editor.Focus()
                editor.SelectAll()
                args.Handled = True
                return
        except Exception:
            pass

        try:
            parent = sender.Parent.Parent.Parent   # host grid -> row grid -> border
            sid = parent.Tag
        except Exception:
            return
        self._select(sid, shift=self._shift_down(), ctrl=self._ctrl_down())
        args.Handled = True

    @staticmethod
    def _shift_down():
        try:
            return (Keyboard.Modifiers & ModifierKeys.Shift) == ModifierKeys.Shift
        except Exception:
            return False

    @staticmethod
    def _ctrl_down():
        try:
            return (Keyboard.Modifiers & ModifierKeys.Control) == ModifierKeys.Control
        except Exception:
            return False

    def _select(self, sid, shift, ctrl=False):
        """Plain click replaces, ctrl adds/removes, shift extends a range."""
        if shift and self.anchor_id is not None \
                and self.anchor_id in self._visible_order \
                and sid in self._visible_order:
            start = self._visible_order.index(self.anchor_id)
            end = self._visible_order.index(sid)
            if start > end:
                start, end = end, start
            block = set(self._visible_order[start:end + 1])
            # ctrl+shift adds the range to what is already highlighted
            self.highlighted = (self.highlighted | block) if ctrl else block
        elif ctrl:
            if sid in self.highlighted:
                self.highlighted.discard(sid)
            else:
                self.highlighted.add(sid)
            self.anchor_id = sid
        else:
            self.highlighted = set([sid])
            self.anchor_id = sid

        self._paint_highlight()
        if len(self.highlighted) > 1:
            self.tb_status.Text = (
                "{0} row(s) highlighted - tick one of them to tick "
                "them all.".format(len(self.highlighted)))
        elif not self.highlighted:
            self.tb_status.Text = "Nothing highlighted."

    def _paint_highlight(self):
        for child in self.sp_sheets.Children:
            try:
                child.Background = (B_SEL if child.Tag in self.highlighted
                                    else B_TRANSPARENT)
            except Exception:
                continue

    def row_ticked(self, sender, args):
        """Ticking a highlighted row applies to the whole highlight."""
        if self._building:
            return
        sid = sender.Tag
        state = bool(sender.IsChecked)

        if sid in self.highlighted and len(self.highlighted) > 1:
            targets = set(self.highlighted)
        else:
            targets = set([sid])

        for target in targets:
            if state:
                self.ticked_ids.add(target)
            else:
                self.ticked_ids.discard(target)

        if len(targets) > 1:
            self.rebuild_rows()
            self.tb_status.Text = "{0} row(s) {1}.".format(
                len(targets), "ticked" if state else "unticked")
        else:
            self.tb_count.Text = \
                "{0} shown / {1} ticked / {2} edited / {3} in project".format(
                    len(self._visible_order), len(self.ticked_ids),
                    len(self.edits), len(self.records))
        args.Handled = True

    # ---------- editing ----------
    def editor_key(self, sender, args):
        try:
            if args.Key == Key.Enter:
                self._commit(sender)
                args.Handled = True
            elif args.Key == Key.Escape:
                sender.Visibility = Visibility.Collapsed
                self.rebuild_rows()
                args.Handled = True
        except Exception:
            pass

    def editor_commit(self, sender, args):
        self._commit(sender)

    def _commit(self, editor):
        if self._building:
            return
        try:
            sid, field = editor.Tag
        except Exception:
            return

        rec = self.by_id.get(sid)
        if rec is None:
            return

        value = (editor.Text or "").strip()
        original = rec[field]

        row = self.edits.get(sid, {})
        if value == original:
            row.pop(field, None)
        elif value == "":
            self.tb_status.Text = "A sheet {0} cannot be empty - left unchanged.".format(field)
            row.pop(field, None)
        else:
            row[field] = value

        if row:
            self.edits[sid] = row
        else:
            self.edits.pop(sid, None)

        self.rebuild_rows()

    def _refresh_apply_button(self):
        pending = len(self.edits)
        self.btn_apply_edits.IsEnabled = pending > 0
        self.btn_apply_edits.Content = (
            "Apply Edits ({0})".format(pending) if pending else "Apply Edits")
        try:
            if pending:
                # green signals staged, unwritten changes
                self.btn_apply_edits.Style = self.Resources["GreenButton"]
            else:
                self.btn_apply_edits.Style = self.Resources["OrangeButton"]
        except Exception:
            pass

    def revert_click(self, sender, args):
        if not self.edits:
            self.tb_status.Text = "No staged edits to revert."
            return
        count = len(self.edits)
        self.edits = {}
        self.rebuild_rows()
        self.tb_status.Text = "Reverted staged edits on {0} sheet(s).".format(count)

    def apply_edits_click(self, sender, args):
        if not self.edits:
            return

        dupes = self.duplicate_numbers()
        clashing = [sid for sid in self.edits
                    if "number" in self.edits[sid]
                    and self.edits[sid]["number"].strip().lower() in dupes]
        if clashing:
            self.tb_status.Text = (
                "{0} staged sheet number(s) are already in use - "
                "fix the red rows first.".format(len(clashing)))
            return

        written = 0
        failed = []
        with revit.Transaction("Sheet Name Push - Apply Edits"):
            for sid, row in list(self.edits.items()):
                rec = self.by_id.get(sid)
                if rec is None:
                    continue
                sheet = rec["sheet"]
                for field, value in row.items():
                    try:
                        if field == "number":
                            sheet.SheetNumber = value
                            ok = (sheet.SheetNumber == value)
                        else:
                            ok = set_element_name(sheet, value)
                        if ok:
                            rec[field] = value
                            written += 1
                        else:
                            failed.append(rec["number"] + " (" + field + ")")
                    except Exception as ex:
                        failed.append("{0} ({1}): {2}".format(
                            rec["number"], field, ex))

        self.edits = {}
        self.rebuild_rows()
        self.tb_status.Text = (
            "Applied {0} edit(s).".format(written) if not failed
            else "Applied {0}, {1} refused: {2}".format(
                written, len(failed), "; ".join(failed[:3])))

    # ---------- filters / toolbar ----------
    def filter_changed(self, sender, args):
        self.rebuild_rows()

    def show_all_click(self, sender, args):
        self.isolated = not bool(self.cb_show_all.IsChecked)
        self.rebuild_rows()

    def dupes_click(self, sender, args):
        self.dupes_only = bool(self.cb_dupes_only.IsChecked)
        self.rebuild_rows()

    def tick_all_click(self, sender, args):
        for rec in self.visible_records():
            self.ticked_ids.add(rec["id"])
        self.rebuild_rows()

    def tick_none_click(self, sender, args):
        for rec in self.visible_records():
            self.ticked_ids.discard(rec["id"])
        self.rebuild_rows()

    def _tool_targets(self):
        """Ticked sheets, or everything currently shown if none ticked."""
        ticked = [r for r in self.records if r["id"] in self.ticked_ids]
        recs = ticked if ticked else self.visible_records()
        targets = []
        for rec in recs:
            targets.append({
                "id": rec["id"],
                "current": {"number": self.current(rec, "number"),
                            "name": self.current(rec, "name")},
            })
        return targets

    def _stage(self, changes):
        for sid, row in changes.items():
            rec = self.by_id.get(sid)
            if rec is None:
                continue
            staged = self.edits.get(sid, {})
            for field, value in row.items():
                if value == rec[field]:
                    staged.pop(field, None)
                else:
                    staged[field] = value
            if staged:
                self.edits[sid] = staged
            else:
                self.edits.pop(sid, None)
        self.rebuild_rows()

    def findreplace_click(self, sender, args):
        targets = self._tool_targets()
        if not targets:
            self.tb_status.Text = "Nothing to work on."
            return
        win = FindReplaceWindow(targets)
        win.Owner = self
        if win.ShowDialog() and win.changes:
            self._stage(win.changes)
            self.tb_status.Text = "Staged find/replace on {0} sheet(s) - press Apply Edits.".format(
                len(win.changes))

    def affix_click(self, sender, args):
        targets = self._tool_targets()
        if not targets:
            self.tb_status.Text = "Nothing to work on."
            return
        win = AffixWindow(targets)
        win.Owner = self
        if win.ShowDialog() and win.changes:
            self._stage(win.changes)
            self.tb_status.Text = "Staged prefix/suffix on {0} sheet(s) - press Apply Edits.".format(
                len(win.changes))

    def settings_click(self, sender, args):
        win = SettingsWindow(self.cfg)
        win.Owner = self
        if win.ShowDialog() and win.saved:
            self.cfg = win.cfg
            self.tb_status.Text = "Target parameters: {0}, {1}, {2}".format(
                self.cfg["param_1"], self.cfg["param_2"], self.cfg["param_3"])

    def _read_format(self):
        if self.rb_title.IsChecked:
            return "title"
        if self.rb_none.IsChecked:
            return "none"
        return "upper"

    def format_changed(self, sender, args):
        """Remember the chosen format straight away, for the next run."""
        self.format_mode = self._read_format()
        self.cfg["format_mode"] = self.format_mode
        self.cfg["settings_version"] = SETTINGS_VERSION
        save_settings(self.cfg)
        self.tb_status.Text = "Text format set to {0} - remembered for next time.".format(
            MODE_LABELS.get(self.format_mode, self.format_mode))

    # ---------- push ----------
    def push_click(self, sender, args):
        if self.edits:
            self.tb_status.Text = (
                "There are {0} staged edit(s) - apply or revert them "
                "before pushing.".format(len(self.edits)))
            return

        self.format_mode = self._read_format()
        self.cfg["format_mode"] = self.format_mode
        save_settings(self.cfg)

        self.result_sheets = [r["sheet"] for r in self.records
                              if r["id"] in self.ticked_ids]
        if not self.result_sheets:
            self.tb_status.Text = "Tick at least one sheet before pushing."
            return

        self.pushed = True
        self.DialogResult = True
        self.Close()

    def cancel_click(self, sender, args):
        self.DialogResult = False
        self.Close()


# ===================== push logic =====================

def format_text(value, mode):
    value = value.strip()
    if mode == "upper":
        return value.upper()
    if mode == "title":
        return " ".join((w[:1].upper() + w[1:].lower()) if w else w
                        for w in value.split(" "))
    return value


def split_sheet_name(name, mode):
    return [format_text(p, mode) for p in name.split("_")[:3]]


def push_sheet_name(sheet, mode, param_names):
    name = sheet.Name
    segments = split_sheet_name(name, mode)
    row = {"number": sheet.SheetNumber, "name": name, "results": []}

    for i, param_name in enumerate(param_names):
        if not param_name:
            continue
        if i >= len(segments):
            row["results"].append((param_name, None, "skipped (no segment)"))
            continue

        value = segments[i]
        param = sheet.LookupParameter(param_name)
        if param is None:
            row["results"].append((param_name, value, "missing parameter"))
            continue
        if param.IsReadOnly:
            row["results"].append((param_name, value, "read-only"))
            continue
        try:
            param.Set(value)
            row["results"].append((param_name, value, "OK"))
        except Exception as ex:
            row["results"].append((param_name, value, "error: {0}".format(ex)))
    return row


def collect_sheet_records():
    sheets = DB.FilteredElementCollector(doc) \
        .OfClass(DB.ViewSheet).WhereElementIsNotElementType().ToElements()

    records = []
    for s in sheets:
        try:
            if s.IsPlaceholder:
                continue
        except Exception:
            pass
        records.append({"id": eid_value(s.Id), "number": s.SheetNumber,
                        "name": s.Name, "sheet": s})
    records.sort(key=lambda r: r["number"])
    return records


def main():
    cfg = load_settings()

    records = collect_sheet_records()
    if not records:
        forms.alert("No sheets found in this project.", exitscript=True)

    preselected = set()
    try:
        for el in revit.get_selection().elements:
            if isinstance(el, DB.ViewSheet):
                preselected.add(eid_value(el.Id))
    except Exception:
        pass

    window = SheetNamePushWindow(records, preselected, cfg)
    window.ShowDialog()

    if not window.pushed or not window.result_sheets:
        script.exit()

    cfg = window.cfg
    param_names = [cfg.get("param_1", ""), cfg.get("param_2", ""),
                   cfg.get("param_3", "")]
    mode = window.format_mode

    log_rows = []
    with revit.Transaction("Push Sheet Name to Sheet Parameters"):
        for sheet in window.result_sheets:
            log_rows.append(push_sheet_name(sheet, mode, param_names))

    ResultsWindow(log_rows, MODE_LABELS.get(mode, mode), len(log_rows)).ShowDialog()


if __name__ == "__main__":
    main()
