# -*- coding: utf-8 -*-
"""RevoBIM PY - Filter Manager

Two tabs in one window:

  Filter Manager  (default)  every ParameterFilterElement in the project,
                             with its categories and its rules exposed and
                             editable the way Revit's own dialog does it,
                             plus Create and Delete.

  Filter Pusher              push filters and their graphic override
                             settings from one host view template into any
                             number of target view templates.

Revit 2021 - 2027.  No f-strings, no System.Uri, no bare .IntegerValue,
no print statements.
"""

__title__ = "Filter\nManager"
__persistentengine__ = True
__author__ = "RevoBIM PY"
__doc__ = "Manage every view filter in the project, and push filters between view templates."
__min_revit_ver__ = 2021
__max_revit_ver__ = 2027

import os
import sys
import datetime
import traceback

# the button's own folder has to be importable before anything else
_HERE = os.path.dirname(__file__)
if _HERE not in sys.path:
    sys.path.append(_HERE)

import fm_clr  # noqa  - every clr.AddReference, must come first

from Autodesk.Revit.DB import Transaction, ElementId

from pyrevit import forms

import fm_core
import fm_filters as ff
import fm_overrides as fo
import fm_colour as fc
import fm_theme
import fm_names
import fm_xlsx
import fm_egg
import fm_drawer
import fm_ui as ui
import fm_events as fe

from fm_core import VERSION, eid_value, apply_icon, open_externally, write_text

fm_core.set_uiapp(__revit__)

doc = __revit__.ActiveUIDocument.Document

XAML_MAIN = os.path.join(_HERE, "ui.xaml")
XAML_DONE = os.path.join(_HERE, "done.xaml")
XAML_CREATE = os.path.join(_HERE, "create.xaml")
XAML_OVERRIDE = os.path.join(_HERE, "override.xaml")
XAML_COLOUR = os.path.join(_HERE, "colour.xaml")
XAML_RENAME = os.path.join(_HERE, "rename.xaml")
XAML_RENAME = os.path.join(_HERE, "rename.xaml")

ICON_FILE = os.path.join(_HERE, "icon.large.png")
if not os.path.isfile(ICON_FILE):
    ICON_FILE = os.path.join(_HERE, "icon.png")

# ---------------------------------------------------------------------------
#  Two switches, in case the machine or the model does not like something.
#  Both are one line each so they can be flipped without touching anything
#  else, and the tool reports which mode it is in.
# ---------------------------------------------------------------------------

# False opens the tool as an ordinary modal dialog: Revit is not usable while
# it is open, but there is no modeless window, no persistent engine and no
# ExternalEvent - which removes the whole class of things that can take Revit
# down rather than raise an error.
MODELESS = True

# False skips counting how many views use each filter. That count is the one
# thing the tool does at start up that has to touch every view in the model.
READ_FILTER_USAGE = True

# the columns whose width is remembered between sessions
LAYOUT_COLUMNS = ["colPusherA", "colPusherB", "colPusherC"]

# the table tab: one block per filter, one row per rule, categories stacked
#  key, heading, the width it will not go below, its share of the spare
#  space. A filter name is the thing worth having room for; a count or a
#  remove button gains nothing from being wider, so they take no share.
TABLE_COLUMNS = [
    ("name", "Filter Name", 232, 3.0),
    ("uses", "#", 46, 0.0),
    ("categories", "Categories", 214, 1.0),
    ("match", "Elements must match", 128, 0.0),
    ("parameter", "Parameter", 216, 1.0),
    ("operator", "Operator", 192, 0.5),
    ("value", "Value", 186, 1.5),
    ("actions", "", 78, 0.0),
]

MATCH_LABELS = ["ALL of the rules  (AND)", "ANY of the rules  (OR)"]
MATCH_KEYS = ["AND", "OR"]


def combo_item(text, tag=None):
    from System.Windows.Controls import ComboBoxItem
    it = ComboBoxItem()
    it.Content = text
    it.Tag = tag
    return it


# ===========================================================================
#  Result window
# ===========================================================================
class DoneWindow(forms.WPFWindow):
    def __init__(self, headline, subtitle, stats, log_title, lines, log_path):
        forms.WPFWindow.__init__(self, XAML_DONE)
        ui.apply_palette(self)
        self.drawer = fm_drawer.Drawer(self)
        self.log_path = log_path
        apply_icon(self.imgIcon, ICON_FILE)
        self.txtVersion.Text = VERSION
        self.txtSubtitle.Text = "  " + subtitle
        self.txtHeadline.Text = headline
        self.txtStats.Text = stats
        self.txtLogTitle.Text = log_title
        for line in lines:
            self.lstLog.Items.Add(line)
        self.txtPath.Text = log_path or ""

    def on_shrink(self, sender, args):
        """Slide down to the title bar, or back up again."""
        self.drawer.toggle()

    def on_drag(self, sender, args):
        if fm_drawer.on_header_down(self.drawer, self, args):
            return
        try:
            self.DragMove()
        except Exception:
            pass

    def on_open_log(self, sender, args):
        if not self.log_path or not open_externally(self.log_path):
            forms.alert("Could not open the log file:\n{0}".format(self.log_path),
                        title="RevoBIM Filter Manager")

    def on_close(self, sender, args):
        self.Close()


# ===========================================================================
#  Create filter window
# ===========================================================================
class CreateWindow(forms.WPFWindow):
    def __init__(self, categories, suggested_name):
        forms.WPFWindow.__init__(self, XAML_CREATE)
        ui.apply_palette(self)
        self.drawer = fm_drawer.Drawer(self)
        self.txtVersion.Text = VERSION
        self.all_categories = categories        # [(ElementId, name)]
        self.state = {}                         # category name -> bool
        self.result = None                      # (name, [ElementId])
        self.txtName.Text = suggested_name
        for _cid, nm in categories:
            self.state[nm] = False
        self.fill()

    def fill(self):
        key = self.txtCatSearch.Text.lower().strip()
        self.lstCategories.Items.Clear()
        for cid, nm in self.all_categories:
            if key and key not in nm.lower():
                continue
            cb = ui.new_checkbox(nm, cid, self.state.get(nm, False))
            cb.Checked += self.on_tick
            cb.Unchecked += self.on_tick
            self.lstCategories.Items.Add(cb)
        self.update_count()

    def harvest(self):
        for item in self.lstCategories.Items:
            self.state[item.Content] = bool(item.IsChecked)

    def update_count(self):
        n = len([k for k in self.state if self.state[k]])
        self.txtCatCount.Text = "{0} selected".format(n)

    def on_tick(self, sender, args):
        self.harvest()
        self.update_count()

    def on_cat_search(self, sender, args):
        self.harvest()
        self.fill()

    def on_all(self, sender, args):
        for item in self.lstCategories.Items:
            item.IsChecked = True
        self.harvest()
        self.update_count()

    def on_none(self, sender, args):
        for item in self.lstCategories.Items:
            item.IsChecked = False
        self.harvest()
        self.update_count()

    def on_shrink(self, sender, args):
        """Slide down to the title bar, or back up again."""
        self.drawer.toggle()

    def on_drag(self, sender, args):
        if fm_drawer.on_header_down(self.drawer, self, args):
            return
        try:
            self.DragMove()
        except Exception:
            pass

    def on_cancel(self, sender, args):
        self.result = None
        self.Close()

    def on_ok(self, sender, args):
        self.harvest()
        name = self.txtName.Text.strip()
        picked = [cid for cid, nm in self.all_categories if self.state.get(nm, False)]

        if not name:
            self.txtWarn.Text = "Give the filter a name."
            return
        if not picked:
            self.txtWarn.Text = "Pick at least one category."
            return
        for f in ff.get_all_filters(doc):
            try:
                if f.Name.lower() == name.lower():
                    self.txtWarn.Text = "A filter called that already exists."
                    return
            except Exception:
                pass

        self.result = (name, picked)
        self.Close()


# ===========================================================================
#  Batch rename - find and replace, prefix and suffix, with a live preview
# ===========================================================================
class RenameWindow(forms.WPFWindow):

    def __init__(self, names, other_names):
        forms.WPFWindow.__init__(self, XAML_RENAME)
        ui.apply_palette(self)
        self.drawer = fm_drawer.Drawer(self)
        self.txtVersion.Text = VERSION
        self.names = list(names)
        self.other_names = list(other_names)
        self.rows = []
        self.result = None
        self.txtSubject.Text = "{0} filter(s) selected".format(len(self.names))
        self.refresh()

    def refresh(self):
        self.rows = ff.rename_preview(
            self.names,
            find=self.txtFind.Text,
            replace=self.txtReplace.Text,
            prefix=self.txtPrefix.Text,
            suffix=self.txtSuffix.Text,
            match_case=bool(self.chkMatchCase.IsChecked),
            other_names=self.other_names)

        self.pnlPreview.Children.Clear()
        changed = 0
        problems = 0
        for old, new, problem in self.rows:
            if problem:
                problems += 1
            elif new != old:
                changed += 1
            self.pnlPreview.Children.Add(self.preview_row(old, new, problem))

        if problems:
            self.txtWarn.Text = ("{0} name(s) cannot be used - fix them or "
                                 "they will be left alone.".format(problems))
        elif not changed:
            self.txtWarn.Text = "Nothing would change yet."
        else:
            self.txtWarn.Text = "{0} filter(s) would be renamed.".format(changed)
        self.btnApplyRename.IsEnabled = changed > 0

    def preview_row(self, old, new, problem):
        from System.Windows.Controls import Grid, TextBlock
        from System.Windows import Thickness

        grid = Grid()
        grid.Margin = Thickness(0, 0, 0, 3)
        grid.ColumnDefinitions.Add(ui.col(1))
        grid.ColumnDefinitions.Add(ui.col(pixels=26))
        grid.ColumnDefinitions.Add(ui.col(1.2))

        left = TextBlock()
        left.Text = old
        left.FontSize = 11
        left.TextTrimming = ui.trim()
        left.SetResourceReference(TextBlock.ForegroundProperty, "Dim")
        ui.place(left, grid, 0)

        arrow = TextBlock()
        arrow.Text = ">"
        arrow.FontSize = 11
        arrow.SetResourceReference(TextBlock.ForegroundProperty, "Dim")
        ui.place(arrow, grid, 1)

        right = TextBlock()
        right.FontSize = 11
        right.TextTrimming = ui.trim()
        if problem:
            right.Text = "{0}   -   {1}".format(new, problem)
            right.SetResourceReference(TextBlock.ForegroundProperty, "Red")
        elif new != old:
            right.Text = new
            right.SetResourceReference(TextBlock.ForegroundProperty, "Orange")
        else:
            right.Text = new
            right.SetResourceReference(TextBlock.ForegroundProperty, "Dim")
        ui.place(right, grid, 2)
        return grid

    def on_rule_changed(self, sender, args):
        self.refresh()

    def on_shrink(self, sender, args):
        """Slide down to the title bar, or back up again."""
        self.drawer.toggle()

    def on_drag(self, sender, args):
        if fm_drawer.on_header_down(self.drawer, self, args):
            return
        try:
            self.DragMove()
        except Exception:
            pass

    def on_cancel(self, sender, args):
        self.result = None
        self.Close()

    def on_ok(self, sender, args):
        wanted = []
        for old, new, problem in self.rows:
            if not problem and new != old:
                wanted.append((old, new))
        if not wanted:
            self.txtWarn.Text = "Nothing to do."
            return
        self.result = wanted
        self.Close()


# ===========================================================================
#  Batch rename - find and replace, prefix and suffix, previewed first
# ===========================================================================
class RenameWindow(forms.WPFWindow):

    def __init__(self, rows, existing):
        forms.WPFWindow.__init__(self, XAML_RENAME)
        ui.apply_palette(self)
        self.drawer = fm_drawer.Drawer(self)
        self.txtVersion.Text = VERSION
        self.rows = rows              # [(ElementId, name)]
        self.existing = existing      # every filter name in the project
        self.results = []
        self.result = None            # [(ElementId, new name)] once accepted

        self.txtSubject.Text = "{0} filter(s) selected".format(len(rows))
        self.refresh()

    # -- preview ------------------------------------------------------------
    def refresh(self):
        self.results = fm_names.plan(
            [(fid, name) for fid, name in self.rows],
            self.existing,
            self.txtFind.Text, self.txtReplace.Text,
            bool(self.chkMatchCase.IsChecked),
            self.txtPrefix.Text, self.txtSuffix.Text)

        self.pnlPreview.Children.Clear()
        for _key, old, new, problem in self.results:
            self.pnlPreview.Children.Add(self.preview_row(old, new, problem))

        blocking = fm_names.blocking(self.results)
        changing = fm_names.changing(self.results)

        if blocking:
            self.txtWarn.Text = ("{0} row(s) need looking at - nothing will be "
                                 "written until they are fixed.".format(len(blocking)))
        elif not changing:
            self.txtWarn.Text = "Nothing would change yet."
        else:
            self.txtWarn.Text = ""

        self.btnApplyRename.IsEnabled = bool(changing) and not blocking
        self.btnApplyRename.Content = "RENAME {0}".format(len(changing)) \
            if changing else "RENAME"

    def preview_row(self, old, new, problem):
        from System.Windows.Controls import Grid, TextBlock
        from System.Windows import Thickness

        grid = Grid()
        grid.Margin = Thickness(0, 0, 0, 3)
        grid.ColumnDefinitions.Add(ui.col(1))
        grid.ColumnDefinitions.Add(ui.col(1))
        grid.ColumnDefinitions.Add(ui.col(1.1))

        def cell(text, key):
            block = TextBlock()
            block.Text = text
            block.FontSize = 11
            block.TextTrimming = ui.trim()
            block.Margin = Thickness(0, 0, 8, 0)
            block.SetResourceReference(TextBlock.ForegroundProperty, key)
            return block

        ui.place(cell(old, "Dim"), grid, 0)

        if problem and problem != "unchanged":
            ui.place(cell(new, "Red"), grid, 1)
            ui.place(cell(problem, "Red"), grid, 2)
        elif problem == "unchanged":
            ui.place(cell(new, "Dim"), grid, 1)
            ui.place(cell("unchanged", "Dim"), grid, 2)
        else:
            ui.place(cell(new, "Orange"), grid, 1)
            ui.place(cell("", "Dim"), grid, 2)
        return grid

    # -- window -------------------------------------------------------------
    def on_rule_changed(self, sender, args):
        self.refresh()

    def on_shrink(self, sender, args):
        """Slide down to the title bar, or back up again."""
        self.drawer.toggle()

    def on_drag(self, sender, args):
        if fm_drawer.on_header_down(self.drawer, self, args):
            return
        try:
            self.DragMove()
        except Exception:
            pass

    def on_cancel(self, sender, args):
        self.result = None
        self.Close()

    def on_ok(self, sender, args):
        changing = fm_names.changing(self.results)
        if not changing or fm_names.blocking(self.results):
            return
        self.result = [(key, new) for key, _old, new, _p in changing]
        self.Close()


# ===========================================================================
#  Colour picker - the same shape as Revit's own colour dialog
# ===========================================================================
CUSTOM_COLOURS = []          # kept for the session, like Revit's own row


class ColourWindow(forms.WPFWindow):

    FIELD_W = 236.0
    FIELD_H = 188.0
    LUM_H = 188.0

    def __init__(self, current_hex):
        forms.WPFWindow.__init__(self, XAML_COLOUR)
        ui.apply_palette(self)
        self.drawer = fm_drawer.Drawer(self)
        self.txtVersion.Text = VERSION
        self.result = None           # ("colour", "RRGGBB") | ("none", None)
        self.loading = True

        start = fc.from_hex(current_hex) or (128, 128, 128)
        self.original = start
        self.rgb = start
        self.hsl = fc.rgb_to_hsl(*start)

        self.build_swatches(self.pnlBasic, fc.BASIC_COLOURS)
        self.build_swatches(self.pnlCustom, CUSTOM_COLOURS, 8)

        ui.paint_swatch(self.pnlOriginal, fc.to_hex(self.original))
        self.paint_field()
        self.paint_lum()
        self.push_to_boxes()
        self.loading = False
        self.renaming = None

        self.pnlField.MouseLeftButtonDown += self.on_field_down
        self.pnlField.MouseMove += self.on_field_move
        self.pnlField.MouseLeftButtonUp += self.on_field_up
        self.pnlLum.MouseLeftButtonDown += self.on_lum_down
        self.pnlLum.MouseMove += self.on_lum_move
        self.pnlLum.MouseLeftButtonUp += self.on_lum_up
        self.dragging = None

    # -- swatch grids -------------------------------------------------------
    def build_swatches(self, panel, colours, pad_to=0):
        from System.Windows.Controls import Border
        from System.Windows import Thickness
        panel.Children.Clear()
        items = list(colours)
        while len(items) < pad_to:
            items.append(None)
        for hexv in items:
            cell = Border()
            cell.Width = 27
            cell.Height = 21
            cell.Margin = Thickness(0, 0, 4, 4)
            cell.BorderBrush = ui.pbrush("EdgeStrong")
            cell.BorderThickness = Thickness(1)
            cell.Cursor = ui.cursor_hand()
            ui.paint_swatch(cell, hexv if hexv else ui.pcolour("FieldDeep")[3:])
            if hexv:
                def picked(sender, args, value=hexv):
                    self.set_rgb(fc.from_hex(value))
                cell.MouseLeftButtonDown += ui.ui_safe(picked)
            panel.Children.Add(cell)

    # -- the two gradients --------------------------------------------------
    def paint_field(self):
        """Hue across, saturation down, at a fixed mid luminosity."""
        from System.Windows.Media import (LinearGradientBrush, GradientStop,
                                          GradientStopCollection)
        from System.Windows import Point
        stops = GradientStopCollection()
        for i in range(7):
            hue = (fc.HUE_MAX / 6.0) * i
            r, g, b = fc.hsl_to_rgb(hue, fc.SAT_MAX, fc.LUM_MAX / 2.0)
            stops.Add(GradientStop(ui.colour(r, g, b), i / 6.0))
        rainbow = LinearGradientBrush(stops)
        rainbow.StartPoint = Point(0, 0)
        rainbow.EndPoint = Point(1, 0)
        self.pnlField.Background = rainbow

        fade = GradientStopCollection()
        fade.Add(GradientStop(ui.colour(128, 128, 128, 0), 0.0))
        fade.Add(GradientStop(ui.colour(128, 128, 128, 255), 1.0))
        shade = LinearGradientBrush(fade)
        shade.StartPoint = Point(0, 0)
        shade.EndPoint = Point(0, 1)
        self.pnlFieldShade.Background = shade

    def paint_lum(self):
        from System.Windows.Media import (LinearGradientBrush, GradientStop,
                                          GradientStopCollection)
        from System.Windows import Point
        hue, sat, _lum = self.hsl
        mid = fc.hsl_to_rgb(hue, sat, fc.LUM_MAX / 2.0)
        stops = GradientStopCollection()
        stops.Add(GradientStop(ui.colour(255, 255, 255), 0.0))
        stops.Add(GradientStop(ui.colour(mid[0], mid[1], mid[2]), 0.5))
        stops.Add(GradientStop(ui.colour(0, 0, 0), 1.0))
        brush = LinearGradientBrush(stops)
        brush.StartPoint = Point(0, 0)
        brush.EndPoint = Point(0, 1)
        self.pnlLum.Background = brush

    def paint_marks(self):
        from System.Windows.Shapes import Ellipse, Polygon
        from System.Windows.Controls import Canvas
        from System.Windows import Point
        from System.Windows.Media import PointCollection

        hue, sat, lum = self.hsl
        self.pnlFieldMarks.Children.Clear()
        ring = Ellipse()
        ring.Width = 11
        ring.Height = 11
        ring.Stroke = ui.pbrush("TabActiveTxt")
        ring.StrokeThickness = 2
        x = (hue / fc.HUE_MAX) * self.FIELD_W
        y = (1.0 - (sat / fc.SAT_MAX)) * self.FIELD_H
        Canvas.SetLeft(ring, x - 5.5)
        Canvas.SetTop(ring, y - 5.5)
        self.pnlFieldMarks.Children.Add(ring)

        self.pnlLumMarks.Children.Clear()
        arrow = Polygon()
        pts = PointCollection()
        pts.Add(Point(0, 0))
        pts.Add(Point(8, 5))
        pts.Add(Point(0, 10))
        arrow.Points = pts
        arrow.Fill = ui.pbrush("Orange")
        ly = (1.0 - (lum / fc.LUM_MAX)) * self.LUM_H
        Canvas.SetLeft(arrow, 0)
        Canvas.SetTop(arrow, ly - 5)
        self.pnlLumMarks.Children.Add(arrow)

    # -- state --------------------------------------------------------------
    def set_rgb(self, rgb):
        if rgb is None:
            return
        self.rgb = rgb
        self.hsl = fc.rgb_to_hsl(*rgb)
        self.after_change()

    def set_hsl(self, hsl):
        self.hsl = hsl
        self.rgb = fc.hsl_to_rgb(*hsl)
        self.after_change()

    def after_change(self):
        self.paint_lum()
        self.push_to_boxes()

    def push_to_boxes(self):
        self.loading = True
        try:
            hue, sat, lum = self.hsl
            r, g, b = self.rgb
            self.txtHue.Text = str(int(hue))
            self.txtSat.Text = str(int(sat))
            self.txtLum.Text = str(int(lum))
            self.txtRed.Text = str(int(r))
            self.txtGreen.Text = str(int(g))
            self.txtBlue.Text = str(int(b))
            self.txtHex.Text = fc.to_hex(self.rgb)
            self.txtName.Text = "RGB {0}-{1}-{2}".format(int(r), int(g), int(b))
            ui.paint_swatch(self.pnlNew, fc.to_hex(self.rgb))
            self.paint_marks()
        finally:
            self.loading = False

    def read_int(self, box, high):
        try:
            return fc.clamp(int(box.Text.strip()), 0, high)
        except Exception:
            return None

    def on_hsl_typed(self, sender, args):
        if self.loading:
            return
        h = self.read_int(self.txtHue, int(fc.HUE_MAX))
        s = self.read_int(self.txtSat, int(fc.SAT_MAX))
        l = self.read_int(self.txtLum, int(fc.LUM_MAX))
        if None in (h, s, l):
            return
        self.set_hsl((h, s, l))

    def on_rgb_typed(self, sender, args):
        if self.loading:
            return
        r = self.read_int(self.txtRed, 255)
        g = self.read_int(self.txtGreen, 255)
        b = self.read_int(self.txtBlue, 255)
        if None in (r, g, b):
            return
        self.set_rgb((r, g, b))

    def on_hex_typed(self, sender, args):
        if self.loading:
            return
        rgb = fc.from_hex(self.txtHex.Text)
        if rgb is not None:
            self.set_rgb(rgb)

    # -- dragging on the gradients -----------------------------------------
    def field_from_point(self, args):
        pos = args.GetPosition(self.pnlField)
        hue = fc.clamp(pos.X / self.FIELD_W, 0.0, 1.0) * fc.HUE_MAX
        sat = (1.0 - fc.clamp(pos.Y / self.FIELD_H, 0.0, 1.0)) * fc.SAT_MAX
        self.set_hsl((int(round(hue)), int(round(sat)), self.hsl[2]))

    def lum_from_point(self, args):
        pos = args.GetPosition(self.pnlLum)
        lum = (1.0 - fc.clamp(pos.Y / self.LUM_H, 0.0, 1.0)) * fc.LUM_MAX
        self.set_hsl((self.hsl[0], self.hsl[1], int(round(lum))))

    def on_field_down(self, sender, args):
        self.dragging = "field"
        try:
            self.pnlField.CaptureMouse()
        except Exception:
            pass
        self.field_from_point(args)

    def on_field_move(self, sender, args):
        if self.dragging == "field":
            self.field_from_point(args)

    def on_field_up(self, sender, args):
        self.dragging = None
        try:
            self.pnlField.ReleaseMouseCapture()
        except Exception:
            pass

    def on_lum_down(self, sender, args):
        self.dragging = "lum"
        try:
            self.pnlLum.CaptureMouse()
        except Exception:
            pass
        self.lum_from_point(args)

    def on_lum_move(self, sender, args):
        if self.dragging == "lum":
            self.lum_from_point(args)

    def on_lum_up(self, sender, args):
        self.dragging = None
        try:
            self.pnlLum.ReleaseMouseCapture()
        except Exception:
            pass

    # -- buttons ------------------------------------------------------------
    def on_add_custom(self, sender, args):
        value = fc.to_hex(self.rgb)
        if value not in CUSTOM_COLOURS:
            CUSTOM_COLOURS.insert(0, value)
            while len(CUSTOM_COLOURS) > 16:
                CUSTOM_COLOURS.pop()
        self.build_swatches(self.pnlCustom, CUSTOM_COLOURS, 8)

    def on_shrink(self, sender, args):
        """Slide down to the title bar, or back up again."""
        self.drawer.toggle()

    def on_drag(self, sender, args):
        if fm_drawer.on_header_down(self.drawer, self, args):
            return
        try:
            self.DragMove()
        except Exception:
            pass

    def on_no_override(self, sender, args):
        self.result = ("none", None)
        self.Close()

    def on_cancel(self, sender, args):
        self.result = None
        self.Close()

    def on_ok(self, sender, args):
        self.result = ("colour", fc.to_hex(self.rgb))
        self.Close()


# ===========================================================================
#  Line / pattern override dialog
# ===========================================================================
class OverrideWindow(forms.WPFWindow):
    """The same two dialogs Revit's own Filters tab opens from a cell."""

    LINE_KEYS = {
        "projection": ("proj_colour", "proj_weight", "proj_pattern"),
        "cut": ("cut_colour", "cut_weight", "cut_pattern"),
    }
    PATTERN_KEYS = {
        "surface": ("surf_fg_pattern", "surf_fg_colour",
                    "surf_bg_pattern", "surf_bg_colour"),
        "cutpattern": ("cut_fg_pattern", "cut_fg_colour",
                       "cut_bg_pattern", "cut_bg_colour"),
    }
    TITLES = {
        "projection": "Projection / Surface  -  Lines",
        "cut": "Cut  -  Lines",
        "surface": "Projection / Surface  -  Patterns",
        "cutpattern": "Cut  -  Patterns",
    }

    def __init__(self, kind, spec, subject, line_patterns, fill_patterns,
                 scope_note=""):
        forms.WPFWindow.__init__(self, XAML_OVERRIDE)
        ui.apply_palette(self)
        self.drawer = fm_drawer.Drawer(self)
        self.kind = kind
        self.result = None
        self.is_lines = kind in self.LINE_KEYS
        self.line_patterns = line_patterns
        self.fill_patterns = fill_patterns

        self.txtVersion.Text = VERSION
        self.txtTitle.Text = "  " + self.TITLES.get(kind, "Override")
        self.txtSubject.Text = subject
        self.txtScope.Text = scope_note

        ui.set_visible(self.pnlLines, self.is_lines)
        ui.set_visible(self.pnlPatterns, not self.is_lines)

        if self.is_lines:
            ck, wk, pk = self.LINE_KEYS[kind]
            self.line_colour = spec.get(ck)
            self.load_combo(self.cboWeight, fo.line_weights(), spec.get(wk))
            self.fill_pattern_combo(self.cboLinePattern, line_patterns,
                                    spec.get(pk), "")
            self.paint_colour_button(self.btnLineColour, self.line_colour)
            self.refresh_line_preview()
        else:
            fp, fc_key, bp, bc = self.PATTERN_KEYS[kind]
            self.fg_colour = spec.get(fc_key)
            self.bg_colour = spec.get(bc)
            self.fill_pattern_combo(self.cboFgPattern, fill_patterns,
                                    spec.get(fp), "")
            self.fill_pattern_combo(self.cboBgPattern, fill_patterns,
                                    spec.get(bp), "")
            self.paint_colour_button(self.btnFgColour, self.fg_colour)
            self.paint_colour_button(self.btnBgColour, self.bg_colour)
            self.refresh_fill_previews()

    # -- combos -------------------------------------------------------------
    def load_combo(self, combo, source, current):
        combo.Items.Clear()
        idx = 0
        for i, pair in enumerate(source):
            combo.Items.Add(combo_item(pair[1], pair[0]))
            if pair[0] is None and current is None:
                idx = i
            elif pair[0] is not None and current is not None:
                if isinstance(pair[0], int):
                    if pair[0] == current:
                        idx = i
                elif eid_value(pair[0]) == eid_value(current):
                    idx = i
        combo.SelectedIndex = idx

    def fill_pattern_combo(self, combo, source, current, keyword):
        """Populate a pattern combo, narrowed by a keyword.

        The current value is always kept in the list even when it does not
        match the search, so narrowing the list cannot silently change it.
        """
        key = (keyword or "").lower().strip()
        shown = []
        for pid, name in source:
            keep = (not key) or (key in name.lower())
            if pid is None:
                keep = True
            if current is not None and pid is not None \
                    and eid_value(pid) == eid_value(current):
                keep = True
            if keep:
                shown.append((pid, name))

        combo.Items.Clear()
        idx = 0
        for i, (pid, name) in enumerate(shown):
            combo.Items.Add(combo_item(name, pid))
            if pid is None and current is None:
                idx = i
            elif pid is not None and current is not None \
                    and eid_value(pid) == eid_value(current):
                idx = i
        combo.SelectedIndex = idx if combo.Items.Count else -1

    def on_line_pattern_search(self, sender, args):
        current = ui.combo_tag(self.cboLinePattern)
        self.fill_pattern_combo(self.cboLinePattern, self.line_patterns,
                                current, self.txtLinePatSearch.Text)

    def on_fill_pattern_search(self, sender, args):
        keyword = self.txtFillPatSearch.Text
        self.fill_pattern_combo(self.cboFgPattern, self.fill_patterns,
                                ui.combo_tag(self.cboFgPattern), keyword)
        self.fill_pattern_combo(self.cboBgPattern, self.fill_patterns,
                                ui.combo_tag(self.cboBgPattern), keyword)

    # -- previews -----------------------------------------------------------
    def refresh_line_preview(self):
        try:
            self.pnlLinePreview.Child = ui.line_pattern_preview(
                doc, ui.combo_tag(self.cboLinePattern), 130, 22,
                self.line_colour_stroke())
        except Exception:
            pass

    def line_colour_stroke(self):
        value = getattr(self, "line_colour", None)
        return ("#FF" + value) if fo.parse_hex(value) else ui.pcolour("Txt")

    def refresh_fill_previews(self):
        try:
            self.pnlFgPreview.Child = ui.fill_pattern_preview(
                doc, ui.combo_tag(self.cboFgPattern), 130, 56,
                self.pattern_stroke(getattr(self, "fg_colour", None)))
            self.pnlBgPreview.Child = ui.fill_pattern_preview(
                doc, ui.combo_tag(self.cboBgPattern), 130, 56,
                self.pattern_stroke(getattr(self, "bg_colour", None)))
        except Exception:
            pass

    def pattern_stroke(self, value):
        return ("#FF" + value) if fo.parse_hex(value) else ui.pcolour("Txt")

    def on_line_pattern_changed(self, sender, args):
        self.refresh_line_preview()

    def on_fg_pattern_changed(self, sender, args):
        self.refresh_fill_previews()

    def on_bg_pattern_changed(self, sender, args):
        self.refresh_fill_previews()

    # -- colour buttons -----------------------------------------------------
    def paint_colour_button(self, button, value):
        from System.Windows.Controls import (StackPanel, Border, TextBlock,
                                             Orientation)
        from System.Windows import Thickness, VerticalAlignment

        panel = StackPanel()
        panel.Orientation = Orientation.Horizontal

        chip = Border()
        chip.Width = 26
        chip.Height = 16
        chip.Margin = Thickness(0, 0, 8, 0)
        chip.BorderBrush = ui.pbrush("EdgeStrong")
        chip.BorderThickness = Thickness(1)
        chip.VerticalAlignment = VerticalAlignment.Center
        ui.paint_swatch(chip, value)
        panel.Children.Add(chip)

        label = TextBlock()
        label.Text = ("#" + value) if fo.parse_hex(value) else "No override"
        label.VerticalAlignment = VerticalAlignment.Center
        label.FontSize = 11
        label.SetResourceReference(TextBlock.ForegroundProperty, "Txt")
        panel.Children.Add(label)

        button.Content = panel

    def pick_colour(self, current):
        dlg = ColourWindow(current)
        try:
            dlg.Owner = self
        except Exception:
            pass
        dlg.ShowDialog()
        if dlg.result is None:
            return (False, current)
        kind, value = dlg.result
        return (True, value if kind == "colour" else None)

    def on_pick_line_colour(self, sender, args):
        changed, value = self.pick_colour(self.line_colour)
        if changed:
            self.line_colour = value
            self.paint_colour_button(self.btnLineColour, value)
            self.refresh_line_preview()

    def on_pick_fg_colour(self, sender, args):
        changed, value = self.pick_colour(self.fg_colour)
        if changed:
            self.fg_colour = value
            self.paint_colour_button(self.btnFgColour, value)
            self.refresh_fill_previews()

    def on_pick_bg_colour(self, sender, args):
        changed, value = self.pick_colour(self.bg_colour)
        if changed:
            self.bg_colour = value
            self.paint_colour_button(self.btnBgColour, value)
            self.refresh_fill_previews()

    # -- window -------------------------------------------------------------
    def on_shrink(self, sender, args):
        """Slide down to the title bar, or back up again."""
        self.drawer.toggle()

    def on_drag(self, sender, args):
        if fm_drawer.on_header_down(self.drawer, self, args):
            return
        try:
            self.DragMove()
        except Exception:
            pass

    def on_clear(self, sender, args):
        out = {}
        keys = self.LINE_KEYS[self.kind] if self.is_lines \
            else self.PATTERN_KEYS[self.kind]
        for k in keys:
            out[k] = None
        self.result = out
        self.Close()

    def on_cancel(self, sender, args):
        self.result = None
        self.Close()

    def on_ok(self, sender, args):
        out = {}
        if self.is_lines:
            ck, wk, pk = self.LINE_KEYS[self.kind]
            out[ck] = self.line_colour if fo.parse_hex(self.line_colour) else None
            out[wk] = ui.combo_tag(self.cboWeight)
            out[pk] = ui.combo_tag(self.cboLinePattern)
        else:
            fp, fc_key, bp, bc = self.PATTERN_KEYS[self.kind]
            out[fp] = ui.combo_tag(self.cboFgPattern)
            out[bp] = ui.combo_tag(self.cboBgPattern)
            out[fc_key] = self.fg_colour if fo.parse_hex(self.fg_colour) else None
            out[bc] = self.bg_colour if fo.parse_hex(self.bg_colour) else None
        self.result = out
        self.Close()


# ===========================================================================
#  Main window
# ===========================================================================
class FilterManagerWindow(forms.WPFWindow):

    def __init__(self):
        fm_core.crumb("window: parsing ui.xaml")
        forms.WPFWindow.__init__(self, XAML_MAIN)
        fm_core.crumb("window: ui.xaml parsed")
        ui.apply_palette(self)
        self.drawer = fm_drawer.Drawer(self)
        apply_icon(self.imgIcon, ICON_FILE)
        self.txtVersion.Text = VERSION

        # ---- manager tab state
        self.all_filters = []
        self.usage = {}
        self.current = None            # ParameterFilterElement
        self.cat_state = {}            # category name -> bool
        fm_core.crumb("model: reading filterable categories")
        self.all_categories = ff.filterable_categories(doc)
        fm_core.crumb("model: {0} filterable categories".format(
            len(self.all_categories)))
        self.rule_rows = []
        self.filter_rows = []
        self.inline_row = None
        self.probe = None
        self.param_list = []           # [(ElementId, name)]
        self.loading = False

        # ---- pusher tab state
        self.templates = []
        self.template_counts = {}
        self.host = None
        self.host_filters = []
        self.push_state = {}
        self.target_state = {}

        # ---- pusher "Target Views" sub-tab state
        self.tgt_index = 0             # 0 = view templates, 1 = views
        self.view_rows = []            # fm_filters.get_filterable_views rows
        self.view_state = {}           # view id value -> ticked
        self.types_hidden = set()      # "family|type" unticked in the dropdown
        self.views_loaded = False
        self._bulk = False             # set while code ticks many boxes
        self._pop_closed_at = 0.0
        self.views_only_selected = False
        self._pop_wired = False

        # ---- "Filters to push" table: which settings go with each filter
        self.push_groups = {}          # filter name -> {group: ticked}
        self.push_rows = []            # [{"name", "item", "grid", "pick", cells}]
        self._push_viewer = None
        self.overwrite_mode = "all"    # "all" or "new"

        # ---- pusher "Filters" sub-tab state
        self.all_push_state = {}       # project list: filter name -> ticked
        self.staged = []               # [(ElementId, name)] in the table
        self.staged_ticked = {}        # table: filter name -> row ticked
        self.specs = {}                # filter id value -> override spec
        self.row_controls = []         # the table's live WPF controls
        self._line_patterns = None     # loaded on first use, not at startup
        self._fill_patterns = None

        # ---- tab strip state (plain buttons, not a TabControl)
        self.tab_index = 0
        self.src_index = 0
        self.layout_saved = {}
        self.table_blocks = []
        self.table_visible = []
        self.egg_clicks = fm_egg.SlowTriple()
        self.sort_key = "name"
        self.sort_ascending = True
        self.header = None
        self.widths_now = []
        self.column_search = {"name": "", "uses": "", "categories": "",
                              "parameter": "", "operator": "", "value": ""}

        # ---- modeless plumbing
        self.runner = fe.Runner(direct=not MODELESS)
        self.runner.set_error_reporter(self.report_error)
        self.runner.on_refused = self.report_refused
        ui.set_handler_reporter(self.report_handler_error)
        if self.runner.create_error:
            fm_core.crumb("events: ExternalEvent.Create failed")
        self.screen = ui.ScreenState(self)
        self.searches = {
            "filters": ui.Debounce(self.run_fm_search),
            "table": ui.Debounce(self.fill_table_rows),
            "hosts": ui.Debounce(self.fill_hosts),
            "targets": ui.Debounce(self.fill_targets),
            "views": ui.Debounce(self.fill_target_views),
            "push": ui.Debounce(self.run_push_filter_search),
            "all": ui.Debounce(self.run_all_filter_search),
        }

        self.PreviewKeyDown += self.on_key
        self.Closed += self.on_closed
        self.Loaded += self.on_loaded
        self.Activated += self.on_window_activated
        # the heading over "Filters to push" tracks the list's scrollbar
        self.lstPushFilters.SizeChanged += ui.ui_safe(self.sync_push_header)

        for lbl in MATCH_LABELS:
            self.cboMatch.Items.Add(combo_item(lbl))
        self.cboMatch.SelectedIndex = 0

        fm_core.crumb("model: reading filters")
        self.reload_filters()
        fm_core.crumb("model: {0} filters".format(len(self.all_filters)))
        fm_core.crumb("model: reading view templates")
        self.reload_templates()
        fm_core.crumb("model: {0} view templates".format(len(self.templates)))
        self.build_props_panel()
        self.apply_layout()
        fm_core.crumb("window: built")

        self.refresh_footer()

    # -- chrome -------------------------------------------------------------
    def on_shrink(self, sender, args):
        """Slide down to the title bar, or back up again."""
        self.drawer.toggle()

    def on_drag(self, sender, args):
        if fm_drawer.on_header_down(self.drawer, self, args):
            return
        """Drag the window, or double click to toggle full screen.

        Dragging while full screen breaks out to the previous size first,
        keeping the pointer on the header where it started.
        """
        try:
            if args.ClickCount == 2:
                self.screen.toggle_full()
                return
        except Exception:
            pass
        try:
            if self.screen.full:
                self.screen.break_out(args)
        except Exception:
            pass
        try:
            self.DragMove()
        except Exception:
            pass

    def on_top_edge(self, sender, args):
        """Double click the very top edge to fill the screen vertically."""
        if self.drawer.shrunk or self.drawer.moving:
            return
        try:
            if args.ClickCount == 2:
                self.screen.toggle_vertical()
                args.Handled = True
        except Exception:
            pass

    def on_logo(self, sender, args):
        """Three slow clicks on the logo.

        The click is not marked handled, so dragging the window by the logo
        still works - the press is counted on the way past.
        """
        import time
        if not self.egg_clicks.click(time.time()):
            return
        if fm_egg.launch(self, fm_theme.name()):
            self.txtStatus.Text = "..."
        else:
            self.txtStatus.Text = ("There is no egg installed in this "
                                   "extension's lib\\revobim.")

    def on_theme(self, sender, args):
        """Auto -> Dark -> Light. Auto follows Revit's canvas theme."""
        fm_theme.set_mode(fm_theme.next_mode(fm_theme.mode()),
                          ui.revit_theme())
        self.repaint_theme()
        self.save_layout()

    def on_window_activated(self, sender, args):
        """In Auto, pick up a theme change made in Revit while open."""
        if fm_theme.mode() != "auto":
            return
        before = fm_theme.name()
        fm_theme.set_mode("auto", ui.revit_theme())
        if fm_theme.name() != before:
            self.repaint_theme()

    def repaint_theme(self):
        ui.apply_palette(self)
        self.txtTheme.Text = fm_theme.MODE_LABELS.get(fm_theme.mode(), "Auto")
        try:
            self.btnTheme.ToolTip = (
                "Theme: {0}  ({1} palette)\nClick to cycle Auto, Dark, Light. "
                "Auto follows Revit's canvas theme.".format(
                    fm_theme.MODE_LABELS.get(fm_theme.mode(), "Auto"),
                    fm_theme.name()))
        except Exception:
            pass
        try:
            self.pnlThemeChip.Background = ui.pbrush(
                "Green" if fm_theme.mode() == "auto" else
                ("Blue" if fm_theme.name() == "light" else "Orange"))
        except Exception:
            pass
        # Anything built in code holds the brushes it was built with, so it
        # keeps the old palette until it is built again. The XAML follows on
        # its own, through DynamicResource.
        self.build_props_panel()
        if self.current is not None:
            self.fill_categories()
        self.repaint_table()

    def repaint_table(self):
        """Redraw the Filter Manager Table in the palette now in force."""
        for block in self.table_blocks:
            if not block["hydrated"]:
                continue
            try:
                block["host"].BorderBrush = ui.pbrush("EdgeFaint")
                self.paint_block(block)
            except Exception:
                continue
        if self.table_blocks:
            try:
                self.rebuild_header()
                self.fill_table_rows()
            except Exception:
                pass

    def on_fullscreen(self, sender, args):
        if self.drawer.shrunk or self.drawer.moving:
            self.drawer.expand()
            return
        self.screen.toggle_full()

    def on_key(self, sender, args):
        """Keyboard shortcuts.

        No blanket try/except here: this method is guarded, and swallowing
        everything is how Ctrl+D and F2 came to call methods that did not
        exist without anyone finding out.
        """
        from System.Windows.Input import Key, Keyboard, ModifierKeys

        control = Keyboard.Modifiers == ModifierKeys.Control

        if args.Key == Key.F11:
            self.on_fullscreen(None, None)
            args.Handled = True
        elif args.Key == Key.F5:
            self.on_refresh(None, None)
            args.Handled = True
        elif args.Key == Key.D and control and self.manager_tab():
            self.on_duplicate_filter(None, None)
            args.Handled = True
        elif args.Key == Key.F2 and self.manager_tab():
            self.on_filter_dblclick(None, None)
            args.Handled = True
        elif args.Key == Key.Escape and self.screen.full:
            self.screen.exit_full()
            args.Handled = True

    def on_loaded(self, sender, args):
        """The handle exists by now, so the screen it is on can be asked."""
        self.screen.fit_to_screen()

    def on_closed(self, sender, args):
        self.save_layout()
        fm_core.crumb("window: closed cleanly")
        fe.unpark()

    # -- column widths ------------------------------------------------------
    def table_panel_width(self):
        """The staging table, its arrows and the padding around them."""
        return self.table_width() + 44 + 8 + 8 + 8 + 2 + 18

    def saved_star(self, key, fallback):
        raw = self.layout_saved.get(key)
        try:
            value = float(raw)
            if 0 < value <= 1000:
                return value
        except Exception:
            pass
        return fallback

    def fit_list_column(self):
        """Crop column one to the longest filter name it is showing."""
        widest = 0.0
        for _fid, name in self.all_filter_pairs():
            widest = max(widest, ui.measure_text(name, 12.0))
        if widest <= 0:
            return
        # tick box, padding, border and a scrollbar
        wanted = widest + 34 + 26 + 20
        wanted = max(190.0, min(wanted, 560.0))
        pool = self.colPusherA.ActualWidth + self.colPusherC.ActualWidth
        if pool <= 0:
            self.colPusherA.Width = ui.pixels(wanted)
            return
        spare = max(self.colPusherC.MinWidth, pool - wanted)
        self.set_pair(self.colPusherA, self.colPusherC, pool - spare, spare)

    def on_fit_list(self, sender, args):
        self.fit_list_column()

    def set_pair(self, first, second, width_first, width_second):
        """Write two columns back as star values.

        Pixels would freeze them: Grid never shrinks an absolute column, so a
        widened panel plus a shrunk window pushes the rest off the edge with
        no scrollbar to get it back. Stars keep sharing the window out.
        """
        width_first = max(first.MinWidth, width_first)
        width_second = max(second.MinWidth, width_second)
        first.Width = ui.star(width_first)
        second.Width = ui.star(width_second)

    def wire_splitters(self):
        self.pnlSplitA.DragDelta += self.on_split_a
        self.pnlSplitB.DragDelta += self.on_split_b

    def drag_pair(self, first, second, change):
        new_first, new_second = fm_core.split_widths(
            first.ActualWidth, second.ActualWidth,
            first.MinWidth, second.MinWidth, change)
        self.set_pair(first, second, new_first, new_second)

    def on_split_a(self, sender, args):
        """Column one against column three on the Filters tab, so the
        settings in the middle keep their width; against column two on the
        Templates tab, where there is nothing to protect."""
        other = self.colPusherC if self.source_tab() == 1 else self.colPusherB
        self.drag_pair(self.colPusherA, other, args.HorizontalChange)

    def on_split_b(self, sender, args):
        if self.source_tab() == 1:
            self.drag_pair(self.colPusherC, self.colPusherA,
                           -args.HorizontalChange)
        else:
            self.drag_pair(self.colPusherB, self.colPusherC,
                           args.HorizontalChange)

    # -- remembering how the columns were dragged ---------------------------
    def apply_layout(self):
        """Put the columns back where they were left last time.

        Widths are kept as star values, not pixels. Both columns either side
        of a GridSplitter are star sized, so the splitter writes star values
        back into them, and star widths still share out the window sensibly
        at any size.
        """
        saved = fm_core.load_settings(fm_core.LAYOUT_FILE)
        self.layout_saved = saved
        # "theme_mode" replaces the old "theme" key, which every earlier
        # version wrote on close - honouring it would mean Auto never becomes
        # the default for anyone who has used the tool before.
        fm_theme.set_mode(saved.get("theme_mode", "auto"), ui.revit_theme())
        self.repaint_theme()
        self.wire_splitters()
        self.select_source(self.src_index)
        if not saved:
            return
        from System.Windows import GridLength, GridUnitType
        for name in LAYOUT_COLUMNS:
            raw = saved.get(name)
            if not raw:
                continue
            try:
                value = float(raw)
            except Exception:
                continue
            if value <= 0 or value > 1000:
                continue
            column = getattr(self, name, None)
            if column is None:
                continue
            try:
                column.Width = GridLength(value, GridUnitType.Star)
            except Exception:
                continue

    def save_layout(self):
        values = {}
        for name in LAYOUT_COLUMNS:
            column = getattr(self, name, None)
            if column is None:
                continue
            try:
                width = column.Width
                if width.IsStar and width.Value > 0:
                    values[name] = "{0:.4f}".format(width.Value)
            except Exception:
                continue
        values["theme_mode"] = fm_theme.mode()
        fm_core.save_settings(fm_core.LAYOUT_FILE, values)

    def report_refused(self, status):
        forms.alert(
            "Revit would not accept the request to write (it answered "
            "'{0}').\n\nThe work was run directly instead - check the model, "
            "and if nothing changed please send "
            "%APPDATA%\\RevoBIM\\filter_manager_last_run.txt".format(status),
            title="RevoBIM Filter Manager")

    def report_handler_error(self, name, text):
        forms.alert(
            "RevoBIM Filter Manager {0}\n\n'{1}' failed:\n\n{2}".format(
                VERSION, name, text), title="RevoBIM Filter Manager")

    def report_error(self, text):
        try:
            forms.alert("Revit refused the operation:\n\n{0}".format(text),
                        title="RevoBIM Filter Manager")
        except Exception:
            pass

    def on_cancel(self, sender, args):
        self.Close()

    def select_tab(self, index):
        self.tab_index = index
        self.btnTabManager.Tag = "on" if index == 0 else "off"
        self.btnTabTable.Tag = "on" if index == 1 else "off"
        self.btnTabPusher.Tag = "on" if index == 2 else "off"
        ui.set_visible(self.pnlManagerTab, index == 0)
        ui.set_visible(self.pnlTableTab, index == 1)
        ui.set_visible(self.pnlPusherTab, index == 2)
        if index == 1 and not self.table_blocks:
            self.build_table_tab()
        self.refresh_footer()

    def on_tab_manager(self, sender, args):
        self.select_tab(0)

    def on_tab_table(self, sender, args):
        self.select_tab(1)

    def on_tab_pusher(self, sender, args):
        self.select_tab(2)

    def manager_tab(self):
        return self.tab_index == 0

    def table_tab(self):
        return self.tab_index == 1

    def select_source(self, index):
        """Templates and Filters share the same three columns.

        On the Templates tab all three are star sized and behave normally.
        On the Filters tab the middle column is pinned to the width of the
        staging table, so dragging column one takes its width from the
        target column on the right rather than squeezing the settings.
        """
        self.src_index = index
        self.btnSrcTemplates.Tag = "on" if index == 0 else "off"
        self.btnSrcFilters.Tag = "on" if index == 1 else "off"

        ui.set_visible(self.pnlColHosts, index == 0)
        ui.set_visible(self.pnlColHostFilters, index == 0)
        ui.set_visible(self.pnlColFilterList, index == 1)
        ui.set_visible(self.pnlColTable, index == 1)

        if index == 1:
            self.colPusherB.Width = ui.pixels(self.table_panel_width())
            self.colPusherB.MinWidth = self.table_panel_width()
            if "colPusherA" not in self.layout_saved:
                self.fit_list_column()
        else:
            self.colPusherB.MinWidth = 230
            width = self.saved_star("colPusherB", 2.6)
            self.colPusherB.Width = ui.star(width)

        self.refresh_footer()

    def on_src_templates(self, sender, args):
        self.select_source(0)

    def on_src_filters(self, sender, args):
        self.select_source(1)


    def source_tab(self):
        """0 = Templates, 1 = Filters, inside the pusher tab."""
        return self.src_index

    def refresh_footer(self):
        if self.table_tab():
            pending = len([b for b in self.table_blocks if b["dirty"]])
            self.btnPrimary.Content = "APPLY TABLE" if not pending \
                else "APPLY TABLE  ({0})".format(pending)
            # always clickable: Apply checks the model itself, so pressing it
            # with nothing flagged still writes anything that really differs
            self.btnPrimary.IsEnabled = bool(self.table_blocks)
            ui.set_visible(self.btnCreate, True)
            ui.set_visible(self.btnDuplicate, False)
            ui.set_visible(self.btnDelete, False)
            self.txtStatus.Text = (
                "Edit any cell, then Apply."
                if not pending else
                "{0} filter(s) edited and waiting for Apply.".format(pending))
            return

        if self.manager_tab():
            self.btnPrimary.Content = "APPLY CHANGES"
            ui.set_visible(self.btnCreate, True)
            ui.set_visible(self.btnDelete, True)
            ui.set_visible(self.btnDuplicate, True)
            picked = len(self.selected_filters_in_list())
            self.btnDelete.IsEnabled = self.current is not None
            self.btnDuplicate.IsEnabled = self.current is not None
            self.btnPrimary.IsEnabled = self.current is not None
            if self.current is None:
                self.txtStatus.Text = ("Pick a filter on the left, or press "
                                       "Create Filter.")
            elif picked > 1:
                self.txtStatus.Text = (
                    "{0} filters selected - right click to rename them "
                    "together. Editing  {1}".format(picked, self.current.Name))
            else:
                self.txtStatus.Text = \
                    "Editing  {0}   -   {1} rule(s), {2} categor(ies)".format(
                        self.current.Name, len(self.rule_rows),
                        self.ticked_category_count())
            return

        self.btnPrimary.Content = "PUSH FILTERS"
        ui.set_visible(self.btnCreate, False)
        ui.set_visible(self.btnDelete, False)
        self.btnPrimary.IsEnabled = True
        nt = len([k for k in self.target_state if self.target_state[k]])
        nv = len(self.ticked_view_rows())
        where = "{0} target template(s)".format(nt)
        if nv:
            where += " + {0} view(s)".format(nv)
        if self.overwrite_mode == "new":
            where += "   (new only)"

        if self.source_tab() == 1:
            self.txtStatus.Text = (
                "{0} filter(s) in the table, with the graphics set there   "
                ">>   {1}".format(len(self.staged), where))
        else:
            nf = len([k for k in self.push_state if self.push_state[k]])
            self.txtStatus.Text = (
                "{0} filter(s) with the host's own settings   >>   "
                "{1}".format(nf, where))

    def on_refresh(self, sender, args):
        """Re-read the model. The window is modeless, so it goes stale."""
        keep_filter = self.current.Id if self.current is not None else None
        keep_host = self.host.Id if self.host is not None else None
        self.all_categories = ff.filterable_categories(doc)
        self._line_patterns = None     # loaded on first use, not at startup
        self._fill_patterns = None

        self.reload_filters(keep_filter)
        self.reload_templates(keep_host)

        live = {}
        for fid, nm in self.all_filter_pairs():
            live[eid_value(fid)] = (fid, nm)
        self.staged = [live[eid_value(fid)] for fid, _nm in self.staged
                       if eid_value(fid) in live]
        self.build_props_panel()
        self.table_blocks = []
        self.header = None
        if self.table_tab():
            self.build_table_tab()
        self.refresh_footer()
        self.txtStatus.Text = "Refreshed - {0} filters, {1} view templates.".format(
            len(self.all_filters), len(self.templates))

    def on_primary(self, sender, args):
        if self.manager_tab():
            self.apply_changes()
        elif self.table_tab():
            self.apply_table()
        else:
            self.push_filters()

    # =======================================================================
    #  TAB 1 - FILTER MANAGER
    # =======================================================================
    def reload_filters(self, select_id=None):
        self.all_filters = ff.get_all_filters(doc)
        if READ_FILTER_USAGE:
            fm_core.crumb("model: counting filter use across every view")
            self.usage = ff.filter_usage(doc)
            fm_core.crumb("model: filter use counted")
        else:
            self.usage = {}
        self.fill_filter_list(select_id)
        try:
            self.fill_all_filters()
        except Exception:
            pass

    def fill_filter_list(self, select_id=None):
        search = self.txtFmSearch.Text
        unused_only = bool(self.chkUnusedOnly.IsChecked)
        self.lstFilters.Items.Clear()
        self.filter_rows = []
        self.inline_row = None

        shown = 0
        unused = 0
        for f in self.all_filters:
            try:
                nm = f.Name
            except Exception:
                continue
            used = self.usage.get(eid_value(f.Id), 0) if READ_FILTER_USAGE else 0
            if READ_FILTER_USAGE and used == 0:
                unused += 1
            if not fm_core.row_visible(nm, used, search, unused_only):
                continue

            if READ_FILTER_USAGE:
                label = "{0}   ({1} view{2})".format(
                    nm, used, "" if used == 1 else "s")
            else:
                label = nm
            item = self.filter_row(f, nm, label)
            self.lstFilters.Items.Add(item)
            shown += 1
            if select_id is not None and eid_value(f.Id) == eid_value(select_id):
                item.IsSelected = True

        if not READ_FILTER_USAGE:
            self.chkUnusedOnly.IsEnabled = False
            self.chkUnusedOnly.Content = "Only filters no view uses  (counting is off)"
            self.txtFmCount.Text = "{0} of {1} filters".format(
                shown, len(self.all_filters))
        elif unused_only:
            self.txtFmCount.Text = "{0} of {1} unused filters".format(
                shown, unused)
        else:
            self.txtFmCount.Text = "{0} of {1} filters   -   {2} unused".format(
                shown, len(self.all_filters), unused)

    def on_unused_only(self, sender, args):
        keep = self.current.Id if self.current is not None else None
        self.fill_filter_list(keep)
        self.refresh_footer()

    def filter_row(self, pfe, name, label):
        """A list row that can turn into a text box for renaming in place."""
        from System.Windows.Controls import Grid, TextBlock, TextBox, ListBoxItem
        from System.Windows import Thickness

        item = ListBoxItem()
        item.Tag = pfe
        item.Padding = Thickness(0)

        grid = Grid()
        grid.Margin = Thickness(6, 3, 6, 3)

        block = TextBlock()
        block.Text = label
        block.TextTrimming = ui.trim()
        grid.Children.Add(block)

        box = TextBox()
        box.Text = name
        box.Height = 24
        ui.set_visible(box, False)
        grid.Children.Add(box)

        row = {"item": item, "pfe": pfe, "name": name,
               "label": block, "box": box}

        def key_down(sender, args, r=row):
            from System.Windows.Input import Key
            if args.Key == Key.Enter:
                self.commit_inline_rename(r)
                args.Handled = True
            elif args.Key == Key.Escape:
                self.cancel_inline_rename(r)
                args.Handled = True

        def lost(sender, args, r=row):
            self.commit_inline_rename(r)

        box.KeyDown += ui.ui_safe(key_down)
        box.LostKeyboardFocus += ui.ui_safe(lost)

        item.Content = grid
        self.filter_rows.append(row)
        return item

    # -- renaming in place --------------------------------------------------
    def begin_inline_rename(self, row):
        if self.inline_row is not None and self.inline_row is not row:
            self.cancel_inline_rename(self.inline_row)
        self.inline_row = row
        row["box"].Text = row["name"]
        ui.set_visible(row["label"], False)
        ui.set_visible(row["box"], True)
        try:
            row["box"].Focus()
            row["box"].SelectAll()
        except Exception:
            pass

    def cancel_inline_rename(self, row):
        ui.set_visible(row["box"], False)
        ui.set_visible(row["label"], True)
        if self.inline_row is row:
            self.inline_row = None

    def commit_inline_rename(self, row):
        if self.inline_row is not row:
            return
        wanted = row["box"].Text.strip()
        self.cancel_inline_rename(row)

        if not wanted or wanted == row["name"]:
            return
        for f in self.all_filters:
            try:
                if eid_value(f.Id) != eid_value(row["pfe"].Id) \
                        and f.Name.lower() == wanted.lower():
                    forms.alert("Another filter is already called '{0}'.".format(
                        wanted), title="RevoBIM Filter Manager")
                    return
            except Exception:
                pass
        self.rename_batch([(row["pfe"].Id, wanted)],
                          "Renamed '{0}'".format(row["name"]))

    def on_filter_dblclick(self, sender, args):
        """Double clicking a filter renames it where it sits."""
        item = self.lstFilters.SelectedItem
        if item is None:
            return
        for row in self.filter_rows:
            if row["item"] is item:
                self.begin_inline_rename(row)
                try:
                    args.Handled = True
                except Exception:
                    pass
                return

    # -- the right click menu -----------------------------------------------
    def on_ctx_duplicate(self, sender, args):
        self.on_duplicate_filter(sender, args)

    def on_ctx_rename(self, sender, args):
        self.on_filter_dblclick(sender, args)

    def on_ctx_batch(self, sender, args):
        self.on_rename_batch(sender, args)

    def on_ctx_delete(self, sender, args):
        self.on_delete_filter(sender, args)

    def on_fm_search(self, sender, args):
        self.searches["filters"].poke()

    def run_fm_search(self):
        keep = self.current.Id if self.current is not None else None
        self.fill_filter_list(keep)

    def selected_filters_in_list(self):
        picked = []
        try:
            for item in self.lstFilters.SelectedItems:
                if item is not None and item.Tag is not None:
                    picked.append(item.Tag)
        except Exception:
            pass
        return picked

    def on_filter_changed(self, sender, args):
        item = None
        try:
            added = args.AddedItems
            if added is not None and added.Count:
                item = added[added.Count - 1]
        except Exception:
            item = None
        if item is None:
            item = self.lstFilters.SelectedItem
        if item is not None:
            self.load_filter(item.Tag)
        self.refresh_footer()

    def load_filter(self, pfe):
        self.loading = True
        try:
            self.current = pfe
            self.txtFilterName.Text = pfe.Name

            cat_ids = ff.filter_category_ids(pfe)
            picked = set()
            for c in cat_ids:
                picked.add(eid_value(c))
            self.cat_state = {}
            for cid, nm in self.all_categories:
                self.cat_state[nm] = eid_value(cid) in picked
            self.fill_categories()

            self.rebuild_parameter_context()

            match, rules = ff.read_filter(doc, pfe)
            self.cboMatch.SelectedIndex = 1 if match == "OR" else 0

            self.pnlRules.Children.Clear()
            self.rule_rows = []
            notes = []
            for r in rules:
                row = self.add_rule_row(r)
                if row is not None and row.get("note"):
                    notes.append(row["note"])

            self.txtRuleNote.Text = "  ".join(notes) if notes else ""
        finally:
            self.loading = False
        self.refresh_footer()

    def rebuild_parameter_context(self):
        """Sample elements and the shared parameter list for the ticked cats."""
        cat_ids = self.ticked_category_ids()
        self.param_list = ff.common_parameters(doc, cat_ids)
        self.probe = ff.probe_for(doc, cat_ids)

    # -- categories ---------------------------------------------------------
    def fill_categories(self):
        search = self.txtCatSearch.Text
        used_only = bool(self.chkCatUsedOnly.IsChecked)
        self.lstCategories.Items.Clear()
        for cid, nm in self.all_categories:
            if used_only and not self.cat_state.get(nm, False):
                continue
            if not fm_core.row_visible(nm, 0, search, False):
                continue
            cb = ui.new_checkbox(nm, cid, self.cat_state.get(nm, False))
            cb.Checked += self.on_cat_ticked
            cb.Unchecked += self.on_cat_ticked
            self.lstCategories.Items.Add(cb)

    def harvest_categories(self):
        for item in self.lstCategories.Items:
            self.cat_state[item.Content] = bool(item.IsChecked)

    def ticked_category_ids(self):
        return [cid for cid, nm in self.all_categories
                if self.cat_state.get(nm, False)]

    def ticked_category_count(self):
        return len([k for k in self.cat_state if self.cat_state[k]])

    def on_cat_search(self, sender, args):
        self.harvest_categories()
        self.fill_categories()

    def on_cat_scope(self, sender, args):
        self.harvest_categories()
        self.fill_categories()

    def on_cat_ticked(self, sender, args):
        if self.loading:
            return
        self.harvest_categories()
        self.rebuild_parameter_context()
        self.refresh_parameter_combos()
        self.refresh_footer()

    def on_cats_all(self, sender, args):
        for item in self.lstCategories.Items:
            item.IsChecked = True
        self.on_cat_ticked(None, None)

    def on_cats_none(self, sender, args):
        for item in self.lstCategories.Items:
            item.IsChecked = False
        self.on_cat_ticked(None, None)

    def on_name_typed(self, sender, args):
        if not self.loading:
            self.refresh_footer()

    def on_match_changed(self, sender, args):
        if not self.loading:
            self.refresh_footer()

    # -- rules --------------------------------------------------------------
    def add_rule_row(self, rule=None):
        """One editable rule row: parameter, operator, value, remove."""
        from System.Windows.Controls import Grid, ContentControl
        from System.Windows import Thickness, HorizontalAlignment

        row = {}
        grid = Grid()
        grid.Margin = Thickness(0, 0, 0, 5)
        for star, px in ((2.2, None), (1.8, None), (2.0, None), (None, 34)):
            grid.ColumnDefinitions.Add(ui.col(star, px))

        names = [nm for _pid, nm in self.param_list]
        tags = [pid for pid, _nm in self.param_list]
        note = ""
        idx = 0 if names else -1

        if rule is not None:
            want = eid_value(rule["param_id"])
            idx = -1
            for i, pid in enumerate(tags):
                if eid_value(pid) == want:
                    idx = i
                    break
            if idx < 0:
                # the rule points at a parameter these categories do not share -
                # keep it visible rather than dropping it silently
                extra = ff.parameter_name(doc, rule["param_id"])
                names = [extra + "   (not shared by these categories)"] + names
                tags = [rule["param_id"]] + tags
                idx = 0
                note = "A rule uses a parameter these categories do not share."

        cbo_param = ui.new_combo(names, idx, tags=tags)
        cbo_param.Margin = Thickness(0, 0, 6, 0)
        Grid.SetColumn(cbo_param, 0)
        grid.Children.Add(cbo_param)

        cbo_op = ui.new_combo([], -1)
        cbo_op.Margin = Thickness(0, 0, 6, 0)
        Grid.SetColumn(cbo_op, 1)
        grid.Children.Add(cbo_op)

        host = ContentControl()
        host.Margin = Thickness(0, 0, 6, 0)
        Grid.SetColumn(host, 2)
        grid.Children.Add(host)

        kill = ui.new_button("X", "RowKill", width=28, height=26)
        kill.HorizontalAlignment = HorizontalAlignment.Right
        Grid.SetColumn(kill, 3)
        grid.Children.Add(kill)

        row["grid"] = grid
        row["param"] = cbo_param
        row["op"] = cbo_op
        row["host"] = host
        row["editor"] = None
        row["storage"] = "String"
        row["spec"] = None
        row["yesno"] = False
        row["note"] = note
        row["busy"] = False

        def on_param(sender, args, r=row):
            if not r["busy"]:
                self.rebuild_operators(r, keep_op=True)

        def on_op(sender, args, r=row):
            if not r["busy"]:
                self.rebuild_value_editor(r)

        def on_kill(sender, args, r=row):
            self.remove_rule_row(r)

        cbo_param.SelectionChanged += ui.ui_safe(on_param)
        cbo_op.SelectionChanged += ui.ui_safe(on_op)
        kill.Click += ui.ui_safe(on_kill)

        self.pnlRules.Children.Add(grid)
        self.rule_rows.append(row)

        self.rebuild_operators(row, wanted_op=(rule or {}).get("op"))
        if rule is not None:
            self.seed_value(row, rule)

        return row

    def rebuild_operators(self, row, wanted_op=None, keep_op=False):
        pid = ui.combo_tag(row["param"])
        storage, spec, yesno = "String", None, False
        if pid is not None and self.probe is not None:
            storage, spec, yesno = self.probe.find(pid)
        row["storage"] = storage
        row["spec"] = spec
        row["yesno"] = yesno

        previous = ui.combo_text(row["op"]) if keep_op else None

        row["busy"] = True
        try:
            keys = ff.ops_for_storage(storage, yesno)
            labels = [ff.OP_LABEL[k] for k in keys]
            row["op"].Items.Clear()
            for i in range(len(keys)):
                row["op"].Items.Add(combo_item(labels[i], keys[i]))

            target = 0
            if wanted_op and wanted_op in keys:
                target = keys.index(wanted_op)
            elif previous and previous in labels:
                target = labels.index(previous)
            row["op"].SelectedIndex = target
        finally:
            row["busy"] = False

        self.rebuild_value_editor(row)

    def rebuild_value_editor(self, row):
        op = ui.combo_tag(row["op"]) or "equals"
        storage = row["storage"]

        if not ff.OP_NEEDS_VALUE.get(op, True):
            row["host"].Content = None
            row["editor"] = None
            return

        keep = ""
        try:
            if row["editor"] is not None:
                keep = self.read_editor(row)
                if isinstance(keep, ElementId):
                    keep = ""
        except Exception:
            keep = ""

        if storage == "Integer" and row["yesno"]:
            editor = ui.new_combo(["Yes", "No"], 0, tags=["1", "0"])
        elif storage == "ElementId":
            values = []
            if self.probe is not None:
                values = self.probe.id_values(ui.combo_tag(row["param"]))
            if values:
                editor = ui.new_combo([v[1] for v in values], 0,
                                      tags=[v[0] for v in values])
            else:
                editor = ui.new_textbox("", "element id")
        else:
            hint = ""
            if storage == "Double":
                hint = ff.unit_label(doc, row["spec"])
            editor = ui.new_textbox(keep, hint)

        row["host"].Content = editor
        row["editor"] = editor

    def read_editor(self, row):
        ed = row["editor"]
        if ed is None:
            return ""
        try:
            from System.Windows.Controls import ComboBox
            if isinstance(ed, ComboBox):
                tag = ui.combo_tag(ed)
                return tag if tag is not None else ui.combo_text(ed)
        except Exception:
            pass
        try:
            return ed.Text
        except Exception:
            return ""

    def seed_value(self, row, rule):
        op = rule.get("op")
        if not ff.OP_NEEDS_VALUE.get(op, True):
            return
        storage = row["storage"]
        value = rule.get("value")
        ed = row["editor"]
        if ed is None:
            return

        try:
            from System.Windows.Controls import ComboBox
            if isinstance(ed, ComboBox):
                if storage == "Integer" and row["yesno"]:
                    ui.select_by_tag(ed, "1" if str(value) in ("1", "True") else "0")
                elif storage == "ElementId":
                    hit = ui.select_by_tag(
                        ed, value,
                        compare=lambda a, b: eid_value(a) == eid_value(b))
                    if not hit and value is not None:
                        nm = ff.element_name(doc, value, str(eid_value(value)))
                        ed.Items.Insert(0, combo_item(nm, value))
                        ed.SelectedIndex = 0
                return
        except Exception:
            pass

        try:
            if storage == "Double":
                shown = ff.to_display(doc, float(value), row["spec"])
                ed.Text = u"{0}".format(round(shown, 6))
            else:
                ed.Text = u"" if value is None else u"{0}".format(value)
        except Exception:
            pass

    def refresh_parameter_combos(self):
        """Categories changed, so the shared parameter list changed too."""
        names = [nm for _pid, nm in self.param_list]
        tags = [pid for pid, _nm in self.param_list]
        for row in self.rule_rows:
            keep = ui.combo_tag(row["param"])
            row["busy"] = True
            try:
                row["param"].Items.Clear()
                for i in range(len(names)):
                    row["param"].Items.Add(combo_item(names[i], tags[i]))
                hit = False
                if keep is not None:
                    hit = ui.select_by_tag(
                        row["param"], keep,
                        compare=lambda a, b: eid_value(a) == eid_value(b))
                if not hit and row["param"].Items.Count:
                    row["param"].SelectedIndex = 0
            finally:
                row["busy"] = False
            self.rebuild_operators(row, keep_op=True)

    def on_add_rule(self, sender, args):
        if self.current is None:
            forms.alert("Pick a filter first, or press Create Filter.",
                        title="RevoBIM Filter Manager")
            return
        if not self.param_list:
            forms.alert("These categories share no filterable parameters.\n\n"
                        "Tick fewer categories and try again.",
                        title="RevoBIM Filter Manager")
            return
        self.add_rule_row(None)
        self.refresh_footer()

    def remove_rule_row(self, row):
        try:
            self.pnlRules.Children.Remove(row["grid"])
        except Exception:
            pass
        if row in self.rule_rows:
            self.rule_rows.remove(row)
        self.refresh_footer()

    # -- apply --------------------------------------------------------------
    def collect_rules(self):
        """([FilterRule], [problem strings])"""
        rules = []
        problems = []
        for i, row in enumerate(self.rule_rows):
            pid = ui.combo_tag(row["param"])
            op = ui.combo_tag(row["op"])
            if pid is None or op is None:
                problems.append(
                    "Rule {0}: no parameter or operator picked.".format(i + 1))
                continue
            raw = self.read_editor(row)
            if ff.OP_NEEDS_VALUE.get(op, True):
                blank = raw is None or (not isinstance(raw, ElementId)
                                        and str(raw).strip() == "")
                if blank:
                    problems.append("Rule {0} ({1}): no value entered.".format(
                        i + 1, ff.parameter_name(doc, pid)))
                    continue
            try:
                rules.append(ff.build_rule(doc, pid, op, raw, row["storage"],
                                           row["spec"], row["yesno"]))
            except Exception as ex:
                problems.append("Rule {0} ({1}): {2}".format(
                    i + 1, ff.parameter_name(doc, pid), ex))
        return rules, problems

    def apply_changes(self):
        if self.current is None:
            return

        self.harvest_categories()
        name = self.txtFilterName.Text.strip()
        cats = self.ticked_category_ids()

        if not name:
            forms.alert("The filter needs a name.", title="RevoBIM Filter Manager")
            return
        if not cats:
            forms.alert("A filter must apply to at least one category.",
                        title="RevoBIM Filter Manager")
            return
        for f in self.all_filters:
            try:
                if eid_value(f.Id) != eid_value(self.current.Id) \
                        and f.Name.lower() == name.lower():
                    forms.alert("Another filter is already called '{0}'.".format(name),
                                title="RevoBIM Filter Manager")
                    return
            except Exception:
                pass

        rules, problems = self.collect_rules()
        if problems:
            forms.alert("Nothing was written. Fix these first:\n\n" +
                        "\n".join(problems), title="RevoBIM Filter Manager")
            return
        self.txtStatus.Text = "Writing '{0}'...".format(name)

        match = MATCH_KEYS[max(0, self.cboMatch.SelectedIndex)]
        old_name = self.current.Name
        fid = self.current.Id

        lines = []
        lines.append("Filter        : {0}".format(name))
        if old_name != name:
            lines.append("Renamed from  : {0}".format(old_name))
        lines.append("Categories    : {0}".format(len(cats)))
        lines.append("Match         : {0}".format(
            "ALL rules (AND)" if match == "AND" else "ANY rule (OR)"))
        lines.append("Rules written : {0}".format(len(rules)))
        lines.append("")
        for i, row in enumerate(self.rule_rows):
            pid = ui.combo_tag(row["param"])
            op = ui.combo_tag(row["op"])
            val = self.read_editor(row)
            if isinstance(val, ElementId):
                val = ff.element_name(doc, val, str(eid_value(val)))
            lines.append("  {0}. {1}   {2}   {3}".format(
                i + 1, ff.parameter_name(doc, pid),
                ff.OP_LABEL.get(op, op), val))

        target = self.current

        def work(uiapp):
            t = Transaction(doc, "RevoBIM - Edit Filter")
            t.Start()
            try:
                notes = ff.apply_filter(doc, target, name, cats, rules, match)
                t.Commit()
            except Exception:
                try:
                    t.RollBack()
                except Exception:
                    pass
                forms.alert("Nothing was changed:\n\n{0}".format(
                    traceback.format_exc()), title="RevoBIM Filter Manager")
                return
            self.after_apply(notes, lines, name, cats, rules, fid)

        self.runner.run(work)

    def after_apply(self, notes, lines, name, cats, rules, fid):
        ff.clear_caches()
        for n in notes:
            lines.append("NOTE: {0}".format(n))

        used = self.usage.get(eid_value(fid), 0)
        log_path = self.write_log("FilterManager", lines,
                                  "Edited filter '{0}'".format(name))

        self.reload_filters(fid)
        self.reload_templates(self.host.Id if self.host is not None else None)
        for item in self.lstFilters.Items:
            try:
                if eid_value(item.Tag.Id) == eid_value(fid):
                    self.current = item.Tag
                    break
            except Exception:
                pass
        self.refresh_footer()

        DoneWindow(
            "Wow you just saved loads of time.",
            "Filter Manager",
            "{0} rule(s) and {1} categor(ies) written to '{2}'. "
            "It is used by {3} view(s) or template(s).".format(
                len(rules), len(cats), name, used),
            "WHAT CHANGED", lines, log_path).ShowDialog()

    # -- duplicate ----------------------------------------------------------
    def on_duplicate_filter(self, sender, args):
        if self.current is None:
            self.txtStatus.Text = "Pick a filter to duplicate."
            return

        source = self.current
        taken = []
        for f in self.all_filters:
            try:
                taken.append(f.Name)
            except Exception:
                pass
        new_name = fm_names.duplicate_name(source.Name, taken)
        old_name = source.Name

        def work(uiapp):
            t = Transaction(doc, "RevoBIM - Duplicate Filter")
            t.Start()
            try:
                copy = ff.duplicate_filter(doc, source, new_name)
                t.Commit()
            except Exception:
                try:
                    t.RollBack()
                except Exception:
                    pass
                forms.alert("The filter was not duplicated:\n\n{0}".format(
                    traceback.format_exc()), title="RevoBIM Filter Manager")
                return
            self.after_duplicate(copy, old_name, new_name)

        self.runner.run(work)

    def after_duplicate(self, copy, old_name, new_name):
        """Land on the copy with its settings open, ready to be changed."""
        self.reload_filters(copy.Id)
        for item in self.lstFilters.Items:
            try:
                if eid_value(item.Tag.Id) == eid_value(copy.Id):
                    self.lstFilters.SelectedItems.Clear()
                    item.IsSelected = True
                    self.lstFilters.ScrollIntoView(item)
                    self.load_filter(item.Tag)
                    break
            except Exception:
                continue
        try:
            self.txtFilterName.Focus()
            self.txtFilterName.SelectAll()
        except Exception:
            pass
        self.refresh_footer()
        self.txtStatus.Text = (
            "Duplicated '{0}' as '{1}' - its categories and rules are open on "
            "the right.".format(old_name, new_name))

    # -- batch rename -------------------------------------------------------
    def on_rename_batch(self, sender, args):
        rows = self.selected_filters_in_list()
        if not rows:
            self.txtStatus.Text = "Select the filters you want to rename."
            return

        existing = []
        for f in self.all_filters:
            try:
                existing.append(f.Name)
            except Exception:
                pass

        dlg = RenameWindow(rows, existing)
        try:
            dlg.Owner = self
        except Exception:
            pass
        dlg.ShowDialog()
        if not dlg.result:
            return
        self.rename_batch(dlg.result,
                          "Renamed {0} filter(s)".format(len(dlg.result)))

    def rename_batch(self, pairs, subject):
        """Write the new names, in two passes through a parked name.

        A batch that swaps two names round, or shuffles a set along by one,
        clashes with itself in a single pass. Renaming everything to a name
        nothing holds first removes the problem.
        """
        taken = []
        for f in self.all_filters:
            try:
                taken.append(f.Name)
            except Exception:
                pass
        parked = fm_names.parking_names(len(pairs), taken)
        records = []

        def work(uiapp):
            t = Transaction(doc, "RevoBIM - Rename Filters")
            t.Start()
            try:
                elements = []
                for index, (fid, new_name) in enumerate(pairs):
                    element = doc.GetElement(fid)
                    if element is None:
                        records.append(("(gone)", new_name,
                                        "no longer in the model"))
                        continue
                    old = element.Name
                    if not ff.rename_filter(doc, element, parked[index]):
                        records.append((old, new_name,
                                        "Revit would not take a temporary name"))
                        continue
                    elements.append((element, old, new_name))

                for element, old, new_name in elements:
                    if ff.rename_filter(doc, element, new_name):
                        records.append((old, new_name, ""))
                    else:
                        records.append((old, new_name,
                                        "Revit would not take the new name"))
                t.Commit()
            except Exception:
                try:
                    t.RollBack()
                except Exception:
                    pass
                forms.alert("Nothing was renamed:\n\n{0}".format(
                    traceback.format_exc()), title="RevoBIM Filter Manager")
                return
            self.after_rename(records, subject)

        self.runner.run(work)

    def after_rename(self, records, subject):
        done = [r for r in records if not r[2]]
        failed = [r for r in records if r[2]]

        keep = self.current.Id if self.current is not None else None
        self.reload_filters(keep)
        self.reload_templates(self.host.Id if self.host is not None else None)
        if keep is not None:
            for f in self.all_filters:
                if eid_value(f.Id) == eid_value(keep):
                    self.current = f
                    self.txtFilterName.Text = f.Name
                    break
        self.refresh_footer()

        if failed:
            lines = ["{0}  ->  {1}{2}".format(
                r[0], r[1], ("   " + r[2]) if r[2] else "") for r in records]
            log_path = self.write_log("FilterManager", lines, subject)
            DoneWindow("Renamed, with {0} refused.".format(len(failed)),
                       "Filter Manager",
                       "{0} renamed, {1} left alone".format(len(done),
                                                            len(failed)),
                       "WHAT CHANGED", lines, log_path).ShowDialog()
        else:
            self.txtStatus.Text = "{0}.".format(subject)

    # -- create / delete ----------------------------------------------------
    def on_create_filter(self, sender, args):
        suggested = ff.unique_filter_name(doc, "RevoBIM Filter")
        dlg = CreateWindow(self.all_categories, suggested)
        try:
            dlg.Owner = self
        except Exception:
            pass
        dlg.ShowDialog()
        if not dlg.result:
            return

        name, cats = dlg.result

        def work(uiapp):
            t = Transaction(doc, "RevoBIM - Create Filter")
            t.Start()
            try:
                new_filter = ff.create_filter(doc, name, cats)
                t.Commit()
            except Exception:
                try:
                    t.RollBack()
                except Exception:
                    pass
                forms.alert("The filter was not created:\n\n{0}".format(
                    traceback.format_exc()), title="RevoBIM Filter Manager")
                return
            self.after_create(new_filter, name)

        self.runner.run(work)

    def after_create(self, new_filter, name):
        ff.clear_caches()
        self.reload_filters(new_filter.Id)
        self.reload_templates(self.host.Id if self.host is not None else None)
        for item in self.lstFilters.Items:
            try:
                if eid_value(item.Tag.Id) == eid_value(new_filter.Id):
                    item.IsSelected = True
                    break
            except Exception:
                pass
        self.txtStatus.Text = ("Created '{0}'. Add its rules on the right, "
                               "then press Apply Changes.".format(name))

    def on_delete_filter(self, sender, args):
        if self.current is None:
            return
        picked = self.selected_filters_in_list()
        if len(picked) < 2:
            picked = [self.current]

        names = []
        used_total = 0
        for element in picked:
            try:
                names.append(element.Name)
                used_total += self.usage.get(eid_value(element.Id), 0)
            except Exception:
                continue
        name = ", ".join(names[:6]) + (" ..." if len(names) > 6 else "")

        if len(picked) == 1:
            msg = "Delete the filter '{0}'?".format(name)
        else:
            msg = "Delete these {0} filters?\n\n{1}".format(len(picked), name)
        if used_total:
            msg += ("\n\nThey are used {0} time(s) across views and templates "
                    "and will be removed from all of them.".format(used_total))
        msg += "\n\nOnly Revit's own undo can bring them back."

        if not forms.alert(msg, title="RevoBIM Filter Manager", yes=True, no=True):
            return

        targets = picked

        def work(uiapp):
            t = Transaction(doc, "RevoBIM - Delete Filter")
            t.Start()
            try:
                for element in targets:
                    ff.delete_filter(doc, element)
                t.Commit()
            except Exception:
                try:
                    t.RollBack()
                except Exception:
                    pass
                forms.alert("The filter was not deleted:\n\n{0}".format(
                    traceback.format_exc()), title="RevoBIM Filter Manager")
                return
            self.after_delete(name)

        self.runner.run(work)

    def after_delete(self, name):
        ff.clear_caches()
        self.current = None
        self.pnlRules.Children.Clear()
        self.rule_rows = []
        self.txtFilterName.Text = ""
        self.txtRuleNote.Text = ""
        self.reload_filters()
        self.reload_templates(self.host.Id if self.host is not None else None)
        self.txtStatus.Text = "Deleted '{0}'.".format(name)
        self.refresh_footer()

    # =======================================================================
    #  TAB 2 - FILTER MANAGER TABLE
    #  Every filter on one row block: its name, its categories stacked one
    #  under another, and one row per rule.
    # =======================================================================
    def table_col_width(self, key):
        for index, (name, _label, width, _share) in enumerate(TABLE_COLUMNS):
            if name == key:
                return self.column_widths()[index]
        return 100

    def column_widths(self):
        """What each column is currently worth, in pixels."""
        if self.widths_now:
            return self.widths_now
        return [float(width) for _k, _l, width, _s in TABLE_COLUMNS]

    def measure_columns(self):
        """Share the width of the page out, and remember the answer."""
        try:
            available = self.pnlTableScroll.ViewportWidth
        except Exception:
            available = 0
        if not available or available <= 0:
            return self.column_widths()

        # the border either side, and room for the vertical scrollbar
        available = available - 2
        self.widths_now = fm_core.distribute_widths(
            [width for _k, _l, width, _s in TABLE_COLUMNS],
            [share for _k, _l, _w, share in TABLE_COLUMNS],
            available)
        return self.widths_now

    def apply_column_widths(self):
        """Push the widths onto the heading row and every painted row.

        The grids are adjusted rather than rebuilt: a resize should not cost
        the whole table, and rebuilding would take the focus out of whatever
        cell is being typed in.
        """
        widths = self.measure_columns()
        total = sum(widths)

        grids = []
        if self.header is not None:
            grids.append(self.header)
        for block in self.table_blocks:
            grid = block.get("grid")
            if grid is not None:
                grids.append(grid)

        for grid in grids:
            try:
                grid.Width = total
                for index in range(min(len(widths), grid.ColumnDefinitions.Count)):
                    grid.ColumnDefinitions[index].Width = ui.pixels(widths[index])
            except Exception:
                continue

    def on_table_resized(self, sender, args):
        self.apply_column_widths()

    def table_total_width(self):
        return sum(self.column_widths())

    def ensure_table_blocks(self):
        """Build a block per filter, once.

        The blocks hold pending edits, so rebuilding them on every keystroke
        in the search box would quietly throw away work. Filtering only
        decides which of them are on show.
        """
        if self.table_blocks:
            return
        self.table_blocks = []
        for pfe in self.all_filters:
            try:
                self.table_blocks.append(self.table_block(pfe))
            except Exception:
                continue

    def build_table_tab(self):
        self.ensure_table_blocks()
        if self.header is None:
            self.rebuild_header()
        self.fill_table_rows()
        self.apply_column_widths()

    def rebuild_header(self):
        self.pnlTableHead.Children.Clear()
        self.header = self.table_header()
        self.pnlTableHead.Children.Add(self.header)

    def fill_table_rows(self):
        """Show the blocks that match, without touching the header."""
        self.pnlTableRows.Children.Clear()
        self.table_visible = []

        unused_only = bool(self.chkTblUnused.IsChecked)
        changed_only = bool(self.chkTblChanged.IsChecked)

        shown = 0
        changed = 0
        for block in self.table_blocks:
            if block["dirty"]:
                changed += 1
            if changed_only and not block["dirty"]:
                continue
            if unused_only and self.block_uses(block) > 0:
                continue
            if not self.block_matches(block):
                continue
            self.hydrate(block)
            self.pnlTableRows.Children.Add(block["host"])
            self.table_place_widths(block)
            self.table_visible.append(block)
            shown += 1

        if changed:
            self.txtTblCount.Text = "{0} of {1} filters   -   {2} edited".format(
                shown, len(self.table_blocks), changed)
        else:
            self.txtTblCount.Text = "{0} of {1} filters".format(
                shown, len(self.table_blocks))
        self.chkTblChanged.IsEnabled = changed > 0

    RULE_COLUMNS = ("parameter", "operator", "value")

    def table_place_widths(self, block):
        """Give a row the widths the rest of the table is using."""
        grid = block.get("grid")
        if grid is None or not self.widths_now:
            return
        try:
            grid.Width = sum(self.widths_now)
            for index in range(min(len(self.widths_now),
                                   grid.ColumnDefinitions.Count)):
                grid.ColumnDefinitions[index].Width = ui.pixels(
                    self.widths_now[index])
        except Exception:
            pass

    def block_text(self, block, deep=False):
        """The searchable text of a block, worked out once and kept.

        `deep` asks for the rule columns as well, which means reading the
        filter's rules. Searching by name, use count or category never does
        that, so typing in those boxes stays cheap on a big project.
        """
        if deep:
            self.hydrate(block)
        if block.get("search") is not None:
            return block["search"]

        categories = []
        for cid in block["cats"]:
            categories.append(ff.category_name(doc, cid) or "")

        parameters, operators, values = [], [], []
        for rule in block["rules"]:
            if rule.get("param_id") is not None:
                parameters.append(ff.parameter_name(doc, rule["param_id"]))
            operators.append(ff.OP_LABEL.get(rule.get("op"), ""))
            values.append(self.rule_value_text(rule))

        block["search"] = {
            "name": block["name"],
            "uses": str(self.block_uses(block)),
            "categories": " ".join(categories),
            "parameter": " ".join(parameters),
            "operator": " ".join(operators),
            "value": " ".join(values),
        }
        return block["search"]

    def block_matches(self, block):
        """The box above the table, and the box under each column heading."""
        deep = any(self.column_search.get(k) for k in self.RULE_COLUMNS)
        text = self.block_text(block, deep)

        # the box above the table searches the name and the categories, so
        # "tray duct" finds a tray filter on duct accessories
        if not fm_core.contains_all(
                self.txtTblSearch.Text,
                [text["name"], text["categories"], text["uses"]]):
            return False

        for key in self.column_search:
            wanted = self.column_search[key]
            if not wanted:
                continue
            if key == "uses":
                if not fm_core.uses_match(self.block_uses(block), wanted):
                    return False
            elif not fm_core.contains_all(wanted, [text.get(key, "")]):
                return False
        return True

    def table_header(self):
        """Two rows: the headings, and a search box under each column.

        The same shape as the Excel tool - a keyword box sitting in the
        column it searches, rather than a row of boxes somewhere else.
        """
        from System.Windows.Controls import Grid, TextBlock
        from System.Windows import Thickness, FontWeights

        grid = Grid()
        grid.Width = self.table_total_width()
        grid.HorizontalAlignment = ui.left()
        for _key, _label, width, _share in TABLE_COLUMNS:
            grid.ColumnDefinitions.Add(ui.col(pixels=width))
        grid.RowDefinitions.Add(ui.row())
        grid.RowDefinitions.Add(ui.row())

        for index, (key, label, _width, _share) in enumerate(TABLE_COLUMNS):
            if key in ("name", "uses"):
                self.table_place(grid, self.sort_header(key, label), 0, index)
            else:
                block = TextBlock()
                block.Text = label
                block.FontSize = 10
                block.FontWeight = FontWeights.Bold
                block.Margin = Thickness(8, 7, 6, 4)
                block.SetResourceReference(TextBlock.ForegroundProperty, "Dim")
                self.table_place(grid, block, 0, index)

            if key in self.column_search:
                self.table_place(grid, self.column_search_box(key), 1, index)

        return grid

    def sort_header(self, key, label):
        """A heading that sorts the table when it is clicked."""
        from System.Windows import Thickness

        arrow = ""
        if self.sort_key == key:
            arrow = "  ^" if self.sort_ascending else "  v"

        button = ui.new_button(label + arrow, "Ghost", height=22)
        button.FontSize = 10
        button.Margin = Thickness(4, 5, 4, 2)
        button.HorizontalAlignment = ui.left()
        button.ToolTip = "Sort by {0}".format(label)

        def clicked(sender, args, column=key):
            self.sort_table(column)

        button.Click += ui.ui_safe(clicked)
        return button

    def column_search_box(self, key):
        from System.Windows import Thickness
        hints = {"name": "name", "uses": "0, >2, 1-4", "categories": "category",
                 "parameter": "parameter", "operator": "operator",
                 "value": "value"}

        box = ui.new_textbox(self.column_search.get(key, ""), hints.get(key, ""))
        box.Height = ui.CELL_HEIGHT
        box.FontSize = 11
        box.Margin = Thickness(4, 0, 4, 6)
        if key == "uses":
            box.ToolTip = ("A number, or >2, >=2, <5, <=1, <>0, or a range "
                           "like 2-5")

        def typed(sender, args, column=key):
            self.column_search[column] = sender.Text
            self.searches["table"].poke()

        box.TextChanged += ui.ui_safe(typed)
        return box

    def sort_table(self, key):
        """Sort the blocks themselves, so the order survives a re-filter."""
        if self.sort_key == key:
            self.sort_ascending = not self.sort_ascending
        else:
            self.sort_key = key
            self.sort_ascending = True

        def by_name(block):
            return (block["name"] or "").lower()

        def by_uses(block):
            return (self.block_uses(block), (block["name"] or "").lower())

        try:
            self.table_blocks.sort(
                key=by_uses if key == "uses" else by_name,
                reverse=not self.sort_ascending)
        except Exception:
            pass
        self.build_table_tab()

    # -- one filter ---------------------------------------------------------
    def table_block(self, pfe):
        """A block, created without reading the filter's rules.

        Reading every filter's rules to open the tab means a full parse of
        the whole project before a single row is on screen. A block starts
        with what is cheap - its name and its categories - and its rules are
        read the moment it is shown, exported, imported into or applied.
        """
        from System.Windows.Controls import Border
        from System.Windows import Thickness

        host = Border()
        host.BorderBrush = ui.pbrush("EdgeFaint")
        host.BorderThickness = Thickness(0, 0, 0, 1)
        host.Padding = Thickness(0, 3, 0, 3)

        return {
            "pfe": pfe,
            "name": pfe.Name,
            "match": "AND",
            "cats": ff.filter_category_ids(pfe),
            "rules": [],
            "probe": None,
            "dirty": False,
            "changes": set(),
            "search": None,
            "grid": None,
            "hydrated": False,
            "host": host,
        }

    def hydrate(self, block):
        """Read the block's rules and draw it, once."""
        if block["hydrated"]:
            return block
        block["hydrated"] = True

        match, rules = ff.read_filter(doc, block["pfe"])
        block["match"] = match
        block["rules"] = rules

        # a rule stored in feet needs the parameter's unit to be readable,
        # so a filter with a numeric rule is sampled; the rest are not
        if any(r.get("storage") == "Double" for r in rules):
            self.table_probe(block)
            for rule in rules:
                self.table_enrich(block, rule)
        for rule in rules:
            self.normalise_rule(rule)

        block["search"] = None
        self.paint_block(block)
        return block

    def block_uses(self, block):
        """How many views and view templates use this filter."""
        if not READ_FILTER_USAGE:
            return 0
        return self.usage.get(eid_value(block["pfe"].Id), 0)

    def table_probe(self, block):
        """Sample elements for this filter's categories, once and only when
        something actually needs the parameter list or a storage type."""
        if block["probe"] is None:
            block["probe"] = ff.probe_for(doc, block["cats"])
        return block["probe"]

    def normalise_rule(self, rule):
        """Put a rule's value into the form the table works in.

        A rule read from Revit holds a number in internal units; a rule
        typed in or read from a sheet holds display text. Two conventions in
        one field made every comparison lie - which is why an import
        reported changes nobody had made. Everything is display text from
        here on, except an element id, which stays an id so equals can be
        written.
        """
        if not ff.OP_NEEDS_VALUE.get(rule.get("op"), True):
            rule["value"] = ""
            return rule

        value = rule.get("value")
        if isinstance(value, ElementId):
            return rule

        if rule.get("storage") == "Double":
            try:
                rule["value"] = u"{0}".format(round(
                    ff.to_display(doc, float(value), rule.get("spec")), 6))
            except Exception:
                rule["value"] = u"{0}".format(value)
        else:
            rule["value"] = u"" if value is None else u"{0}".format(value)
        return rule

    def table_enrich(self, block, rule):
        """Fill in the unit and yes/no flag a decoded rule cannot know."""
        probe = block["probe"]
        if probe is None or rule.get("param_id") is None:
            return
        storage, spec, yesno = probe.find(rule["param_id"])
        if rule.get("storage") == "Double" and spec is not None:
            rule["spec"] = spec
        rule["yesno"] = yesno

    def mark_dirty(self, block, *keys):
        """Remember that a block changed, and which cells did.

        The keys drive the highlight, so an import can point at exactly what
        it touched rather than just colouring a whole filter.
        """
        block["dirty"] = True
        for key in keys:
            block["changes"].add(key)
        self.refresh_footer()

    def paint_block(self, block):
        block["search"] = None
        from System.Windows.Controls import Grid, TextBlock, TextBox
        from System.Windows import Thickness, VerticalAlignment

        rows = max(1, len(block["cats"]), len(block["rules"]))
        grid = Grid()
        grid.Width = self.table_total_width()
        for _key, _label, width, _share in TABLE_COLUMNS:
            grid.ColumnDefinitions.Add(ui.col(pixels=width))
        for _i in range(rows + 1):
            grid.RowDefinitions.Add(ui.row())

        # ---- name
        name_box = ui.new_textbox(block["name"])
        name_box.Height = ui.CELL_HEIGHT
        name_box.Margin = Thickness(6, 3, 6, 3)

        def name_typed(sender, args, b=block):
            b["name"] = sender.Text
            self.mark_dirty(b, "name")

        name_box.TextChanged += ui.ui_safe(name_typed)
        self.highlight(name_box, block, "name")
        self.table_place(grid, name_box, 0, 0)

        uses = TextBlock()
        uses.Text = str(self.block_uses(block))
        uses.FontSize = 11
        uses.Margin = Thickness(0, 9, 0, 0)
        uses.HorizontalAlignment = ui.centre()
        uses.SetResourceReference(TextBlock.ForegroundProperty, "Dim")
        uses.ToolTip = "How many views and view templates use this filter"
        self.table_place(grid, uses, 0, 1)

        # ---- match mode
        labels = ["AND - all", "OR - any"]
        keys = ["AND", "OR"]
        match_combo = ui.new_combo(
            labels, keys.index(block["match"]) if block["match"] in keys else 0,
            tags=keys, height=ui.CELL_HEIGHT)
        match_combo.Margin = Thickness(4, 3, 6, 3)

        def match_changed(sender, args, b=block):
            picked = ui.combo_tag(sender)
            if picked and picked != b["match"]:
                b["match"] = picked
                self.mark_dirty(b, "match")

        match_combo.SelectionChanged += ui.ui_safe(match_changed)
        self.highlight(match_combo, block, "match")
        self.table_place(grid, match_combo, 0, 3)

        # ---- categories, one under the other
        for index, cid in enumerate(block["cats"]):
            self.table_place(grid, self.category_cell(block, index, cid),
                             index, 2)

        # ---- rules, one per row
        for index, rule in enumerate(block["rules"]):
            self.table_place(grid, self.rule_parameter_cell(block, index),
                             index, 4)
            self.table_place(grid, self.rule_operator_cell(block, index),
                             index, 5)
            self.table_place(grid, self.rule_value_cell(block, index),
                             index, 6)
            self.table_place(grid, self.rule_remove_cell(block, index),
                             index, 7)

        if not block["rules"]:
            note = TextBlock()
            note.Text = "no rules - matches everything in its categories"
            note.FontSize = 10
            note.VerticalAlignment = VerticalAlignment.Center
            note.Margin = Thickness(6, 3, 6, 3)
            note.SetResourceReference(TextBlock.ForegroundProperty, "Dim")
            self.table_place(grid, note, 0, 4)

        # ---- the add row
        self.table_place(grid, self.add_button(
            "+ category", lambda b=block: self.table_add_category(b)),
            rows, 2)
        self.table_place(grid, self.add_button(
            "+ rule", lambda b=block: self.table_add_rule(b)), rows, 4)

        block["grid"] = grid
        block["host"].Child = grid
        return grid

    def highlight(self, element, block, key):
        """Tint a cell the import or an edit has touched."""
        if key not in block["changes"]:
            return element
        try:
            element.Background = ui.pbrush("ChangedBg")
        except Exception:
            pass
        try:
            element.BorderBrush = ui.pbrush("ChangedEdge")
            element.BorderThickness = ui.thickness(1)
        except Exception:
            pass
        return element

    def table_place(self, grid, element, row, column=None):
        """Place a cell. The header calls it with a column only."""
        if column is None:
            row, column = 0, row
        from System.Windows.Controls import Grid
        Grid.SetRow(element, row)
        Grid.SetColumn(element, column)
        grid.Children.Add(element)
        return element

    def add_button(self, text, action):
        from System.Windows import Thickness, HorizontalAlignment
        button = ui.new_button(text, "Ghost", height=22)
        button.FontSize = 10
        button.Margin = Thickness(6, 2, 6, 4)
        button.HorizontalAlignment = HorizontalAlignment.Left

        def clicked(sender, args):
            action()

        button.Click += ui.ui_safe(clicked)
        return button

    # -- category cell ------------------------------------------------------
    def category_cell(self, block, index, cid):
        from System.Windows.Controls import Grid
        from System.Windows import Thickness

        holder = Grid()
        holder.ColumnDefinitions.Add(ui.col(1))
        holder.ColumnDefinitions.Add(ui.col(pixels=24))
        holder.Margin = Thickness(4, 3, 4, 3)

        names = [nm for _c, nm in self.all_categories]
        tags = [c for c, _nm in self.all_categories]
        selected = -1
        for i, candidate in enumerate(tags):
            if eid_value(candidate) == eid_value(cid):
                selected = i
                break
        combo = ui.new_combo(names, selected, tags=tags,
                             height=ui.CELL_HEIGHT)

        def changed(sender, args, b=block, position=index):
            picked = ui.combo_tag(sender)
            if picked is None:
                return
            if eid_value(picked) == eid_value(b["cats"][position]):
                return
            b["cats"][position] = picked
            b["probe"] = None      # the shared parameter list has moved
            self.mark_dirty(b, "cat:{0}".format(position))

        combo.SelectionChanged += ui.ui_safe(changed)
        self.highlight(combo, block, "cat:{0}".format(index))
        ui.place(combo, holder, 0)

        kill = ui.new_button("x", "RowKill", width=20, height=22)

        def remove(sender, args, b=block, position=index):
            if len(b["cats"]) <= 1:
                self.txtStatus.Text = "A filter must keep at least one category."
                return
            b["cats"].pop(position)
            b["probe"] = None
            self.mark_dirty(b)
            self.paint_block(b)

        kill.Click += ui.ui_safe(remove)
        ui.place(kill, holder, 1)
        return holder

    def table_add_category(self, block):
        for cid, _nm in self.all_categories:
            if not any(eid_value(cid) == eid_value(c) for c in block["cats"]):
                block["cats"].append(cid)
                block["probe"] = None
                self.mark_dirty(block)
                self.paint_block(block)
                return
        self.txtStatus.Text = "Every category is already on this filter."

    # -- rule cells ---------------------------------------------------------
    def rule_parameter_cell(self, block, index):
        from System.Windows import Thickness
        rule = block["rules"][index]
        current = ff.parameter_name(doc, rule["param_id"]) \
            if rule.get("param_id") is not None else "(pick a parameter)"

        combo = ui.new_combo([current], 0, tags=[rule.get("param_id")],
                             height=ui.CELL_HEIGHT)
        combo.Margin = Thickness(4, 3, 4, 3)
        filled = {"done": False}

        def opened(sender, args, b=block, r=rule):
            # the full list costs a scan of the model, so it is not built
            # until the list is actually opened
            if filled["done"]:
                return
            filled["done"] = True
            self.table_probe(b)
            options = ff.common_parameters(doc, b["cats"])
            keep = r.get("param_id")
            sender.Items.Clear()
            chosen = 0
            for i, (pid, nm) in enumerate(options):
                sender.Items.Add(combo_item(nm, pid))
                if keep is not None and eid_value(pid) == eid_value(keep):
                    chosen = i
            if not sender.Items.Count:
                sender.Items.Add(combo_item(current, keep))
            sender.SelectedIndex = chosen

        def changed(sender, args, b=block, r=rule, position=index):
            if not filled["done"]:
                return
            picked = ui.combo_tag(sender)
            if picked is None or (r.get("param_id") is not None
                                  and eid_value(picked) == eid_value(r["param_id"])):
                return
            r["param_id"] = picked
            probe = self.table_probe(b)
            storage, spec, yesno = probe.find(picked)
            r["storage"] = storage
            r["spec"] = spec
            r["yesno"] = yesno
            if r.get("op") not in ff.ops_for_storage(storage, yesno):
                r["op"] = ff.ops_for_storage(storage, yesno)[0]
            r["value"] = ""
            self.mark_dirty(b, "rule:{0}".format(position))
            self.paint_block(b)

        combo.DropDownOpened += ui.ui_safe(opened)
        combo.SelectionChanged += ui.ui_safe(changed)
        return self.highlight(combo, block, "rule:{0}".format(index))

    def rule_operator_cell(self, block, index):
        from System.Windows import Thickness
        rule = block["rules"][index]
        keys = ff.ops_for_storage(rule.get("storage", "String"),
                                  rule.get("yesno", False))
        labels = [ff.OP_LABEL[k] for k in keys]
        chosen = keys.index(rule["op"]) if rule.get("op") in keys else 0

        combo = ui.new_combo(labels, chosen, tags=keys,
                             height=ui.CELL_HEIGHT)
        combo.Margin = Thickness(4, 3, 4, 3)

        def changed(sender, args, b=block, r=rule, position=index):
            picked = ui.combo_tag(sender)
            if picked is None or picked == r.get("op"):
                return
            needed_before = ff.OP_NEEDS_VALUE.get(r.get("op"), True)
            r["op"] = picked
            self.mark_dirty(b, "rule:{0}".format(position))
            if needed_before != ff.OP_NEEDS_VALUE.get(picked, True):
                self.paint_block(b)

        combo.SelectionChanged += ui.ui_safe(changed)
        return self.highlight(combo, block, "rule:{0}".format(index))

    def rule_value_cell(self, block, index):
        from System.Windows.Controls import TextBlock
        from System.Windows import Thickness, VerticalAlignment
        rule = block["rules"][index]

        if not ff.OP_NEEDS_VALUE.get(rule.get("op"), True):
            note = TextBlock()
            note.Text = "no value needed"
            note.FontSize = 10
            note.VerticalAlignment = VerticalAlignment.Center
            note.Margin = Thickness(6, 3, 6, 3)
            note.SetResourceReference(TextBlock.ForegroundProperty, "Dim")
            return note

        storage = rule.get("storage", "String")
        shown = rule.get("value")

        if storage == "Integer" and rule.get("yesno"):
            combo = ui.new_combo(["Yes", "No"],
                                 0 if str(shown) in ("1", "True", "Yes") else 1,
                                 tags=["1", "0"], height=ui.CELL_HEIGHT)
            combo.Margin = Thickness(4, 3, 4, 3)

            def picked(sender, args, b=block, r=rule, position=index):
                r["value"] = ui.combo_tag(sender)
                self.mark_dirty(b, "rule:{0}".format(position))

            combo.SelectionChanged += ui.ui_safe(picked)
            return self.highlight(combo, block, "rule:{0}".format(index))

        if isinstance(shown, ElementId):
            text = ff.element_name(doc, shown, str(eid_value(shown)))
        else:
            text = u"" if shown is None else u"{0}".format(shown)

        box = ui.new_textbox(text, ff.unit_label(doc, rule.get("spec"))
                             if storage == "Double" else "")
        box.Height = ui.CELL_HEIGHT
        box.Margin = Thickness(4, 3, 4, 3)

        def typed(sender, args, b=block, r=rule, position=index):
            r["value"] = sender.Text
            self.mark_dirty(b, "rule:{0}".format(position))

        box.TextChanged += ui.ui_safe(typed)
        return self.highlight(box, block, "rule:{0}".format(index))

    def rule_remove_cell(self, block, index):
        from System.Windows import Thickness, HorizontalAlignment
        kill = ui.new_button("x", "RowKill", width=22, height=22)
        kill.Margin = Thickness(4, 3, 4, 3)
        kill.HorizontalAlignment = HorizontalAlignment.Left

        def remove(sender, args, b=block, position=index):
            b["rules"].pop(position)
            self.mark_dirty(b)
            self.paint_block(b)

        kill.Click += ui.ui_safe(remove)
        return kill

    def table_add_rule(self, block):
        probe = self.table_probe(block)
        options = ff.common_parameters(doc, block["cats"])
        if not options:
            self.txtStatus.Text = ("These categories share no filterable "
                                   "parameters.")
            return
        pid = options[0][0]
        storage, spec, yesno = probe.find(pid)
        block["rules"].append({
            "param_id": pid,
            "op": ff.ops_for_storage(storage, yesno)[0],
            "value": "",
            "storage": storage,
            "spec": spec,
            "yesno": yesno,
        })
        self.mark_dirty(block)
        self.paint_block(block)

    # -- the debug strip ----------------------------------------------------
    def on_toggle_debug(self, sender, args):
        showing = self.pnlDebug.Visibility != ui.hidden()
        ui.set_visible(self.pnlDebug, not showing)
        try:
            self.pnlDebugCaret.Data = ui.geometry(
                "M 0,0 L 9,0 L 4.5,7 Z" if not showing else "M 0,0 L 7,4.5 L 0,9 Z")
        except Exception:
            pass
        if not showing:
            self.refresh_debug()

    def on_debug_refresh(self, sender, args):
        self.refresh_debug()

    def on_debug_copy(self, sender, args):
        try:
            from System.Windows import Clipboard
            Clipboard.SetText(self.txtDebug.Text)
            self.txtStatus.Text = "Debug details copied to the clipboard."
        except Exception:
            self.txtStatus.Text = "The clipboard would not take it."

    def on_debug_open(self, sender, args):
        open_externally(fm_core.settings_folder())

    def refresh_debug(self):
        """What the tool knows about itself, in one readable block."""
        lines = []
        lines.append("RevoBIM Filter Manager {0}".format(VERSION))
        lines.append("Revit {0}   Python {1}".format(
            fm_core.revit_version(), sys.version.split()[0]))
        lines.append("Model: {0}".format(doc.Title))
        lines.append("")

        lines.append("SWITCHES")
        lines.append("  MODELESS            {0}".format(MODELESS))
        lines.append("  READ_FILTER_USAGE   {0}".format(READ_FILTER_USAGE))
        lines.append("")

        lines.append("WRITING")
        runner = getattr(self, "runner", None)
        if runner is None:
            lines.append("  no runner - the tool cannot write at all")
        else:
            lines.append("  ExternalEvent       {0}".format(
                "created" if runner.event is not None else "NOT created"))
            lines.append("  running directly    {0}".format(runner.direct))
            if runner.create_error:
                lines.append("  creation failed:")
                for line in runner.create_error.splitlines()[-4:]:
                    lines.append("      " + line)
            lines.append("  last answer         {0}".format(
                getattr(self, "last_request", "nothing sent yet")))
            lines.append("  queued and waiting  {0}".format(
                len(runner.handler._queue)))
        lines.append("")

        lines.append("WHAT IS LOADED")
        lines.append("  filters             {0}".format(len(self.all_filters)))
        lines.append("  view templates      {0}".format(len(self.templates)))
        lines.append("  table blocks        {0}".format(len(self.table_blocks)))
        lines.append("  showing             {0}".format(len(self.table_visible)))
        dirty = [b for b in self.table_blocks if b["dirty"]]
        lines.append("  edited, not applied {0}".format(len(dirty)))
        for block in dirty[:10]:
            lines.append("      {0}   [{1}]".format(
                block["name"], ", ".join(sorted(block["changes"])) or "flagged"))
        lines.append("")

        lines.append("LAST RUN, most recent last")
        for line in fm_core.recent_crumbs(14):
            lines.append("  " + line)
        lines.append("")
        lines.append("Files: {0}".format(fm_core.settings_folder()))

        self.txtDebug.Text = "\n".join(lines)

    def on_tbl_search(self, sender, args):
        self.searches["table"].poke()

    def on_table_scrolled(self, sender, args):
        """Keep the headings over their columns when the table scrolls."""
        try:
            if self.header is not None:
                self.header.Margin = ui.thickness(
                    -sender.HorizontalOffset, 0, 0, 0)
        except Exception:
            pass

    def on_tbl_unused(self, sender, args):
        self.build_table_tab()

    def on_tbl_changed_only(self, sender, args):
        self.build_table_tab()

    # -- Excel round trip ---------------------------------------------------
    XLS_HEADERS = ["Id", "Filter Name", "Categories", "Elements must match",
                   "Parameter", "Operator", "Value"]
    XLS_WIDTHS = [10, 38, 30, 20, 34, 28, 26]

    def table_to_rows(self):
        """The table laid out for a sheet, grouped exactly as on screen.

        The id is the key on the way back in, so a filter can be renamed in
        Excel and still be matched to the right element.
        """
        rows = [list(self.XLS_HEADERS)]
        for block in self.exportable_blocks():
            self.hydrate(block)
            cats = block["cats"]
            rules = block["rules"]
            depth = max(1, len(cats), len(rules))
            for line in range(depth):
                row = ["", "", "", "", "", "", ""]
                if line == 0:
                    row[0] = str(eid_value(block["pfe"].Id))
                    row[1] = block["name"]
                    row[3] = block["match"]
                if line < len(cats):
                    row[2] = ff.category_name(doc, cats[line]) or ""
                if line < len(rules):
                    rule = rules[line]
                    row[4] = ff.parameter_name(doc, rule.get("param_id")) \
                        if rule.get("param_id") is not None else ""
                    row[5] = ff.OP_LABEL.get(rule.get("op"), "")
                    row[6] = self.rule_value_text(rule)
                rows.append(row)
        return rows

    def exportable_blocks(self):
        """What the sheet covers: whatever the table is currently showing.

        Exporting the whole project when the list has been narrowed to six
        filters is not what the search was for.
        """
        return self.table_visible if self.table_visible else self.table_blocks

    def rule_value_text(self, rule):
        """A rule's value as it should read on screen and in a sheet."""
        if not ff.OP_NEEDS_VALUE.get(rule.get("op"), True):
            return ""
        value = rule.get("value")
        if isinstance(value, ElementId):
            return ff.element_name(doc, value, str(eid_value(value)))
        return u"" if value is None else u"{0}".format(value)

    def same_value(self, left, right):
        """Whether two values mean the same thing.

        Compared as numbers where both are numbers, so 100 and 100.0 and
        100.000000 are one value rather than three - the difference that had
        an import reporting changes nobody made.
        """
        a = self.rule_value_text(left).strip()
        b = self.rule_value_text(right).strip()
        if a == b:
            return True
        try:
            return abs(float(a) - float(b)) < 0.000001
        except Exception:
            return False

    #  Id | Name | Categories | Match | Parameter | Operator | Value
    COLUMN_STYLE = {
        0: "locked",      # the key the import matches on
        1: "filter",      # the filter's own cells
        2: "category",
        3: "filter",
        4: "rule",        # the rule cells, kept visually apart
        5: "rule",
        6: "rule",
    }

    def table_styles(self, rows):
        """Which cells may be edited, and what each one is.

        Three editable colours rather than one: the filter's own cells, its
        categories, and its rules. A rule row reads as a rule at a glance
        instead of as more of the filter above it.
        """
        by_kind = {
            "locked": fm_xlsx.STYLE_LOCKED,
            "filter": fm_xlsx.STYLE_EDITABLE,
            "category": fm_xlsx.STYLE_CATEGORY,
            "rule": fm_xlsx.STYLE_RULE,
        }
        styles = [[fm_xlsx.STYLE_HEADER] * len(self.XLS_HEADERS)]
        for _row in rows[1:]:
            styles.append([by_kind[self.COLUMN_STYLE[index]]
                           for index in range(len(self.XLS_HEADERS))])
        return styles

    def lists_sheet(self):
        """The values each editable column will take, for the dropdowns."""
        categories = sorted(nm for _c, nm in self.all_categories)
        operators = [ff.OP_LABEL[k] for k in
                     [key for key, _l, _f, _n in ff.OPERATORS]]

        params = set()
        for block in self.exportable_blocks():
            self.hydrate(block)
            for pid, name in ff.common_parameters(doc, block["cats"]):
                params.add(name)
        params = sorted(params)

        depth = max(len(categories), len(operators), len(params), 2)
        rows = [["Categories", "Operators", "Elements must match",
                 "Parameters used by the filters in this sheet"]]
        for index in range(depth):
            rows.append([
                categories[index] if index < len(categories) else "",
                operators[index] if index < len(operators) else "",
                ["AND", "OR"][index] if index < 2 else "",
                params[index] if index < len(params) else "",
            ])
        return rows, depth

    def guide_sheet(self):
        """A dark-themed key, on its own tab, explaining the colours.

        Returns (rows, styles). Each colour is shown as a filled swatch
        beside what it means, in the same colours the Filters tab uses, so
        the sheet explains itself without anyone having to remember.
        """
        D = fm_xlsx.STYLE_DARK
        T = fm_xlsx.STYLE_DARK_TITLE

        entries = [
            (fm_xlsx.STYLE_LOCKED, "Id",
             "The Revit element id. This is how Import finds the filter "
             "again, so a name can be changed and still be matched. Do not "
             "edit this column, and do not delete its row."),
            (fm_xlsx.STYLE_EDITABLE, "The filter",
             "Its name, and whether an element has to match ALL of the rules "
             "or ANY of them. Only the first row of each filter carries "
             "these."),
            (fm_xlsx.STYLE_CATEGORY, "Categories",
             "One per row, by name. Add a row under the last one to add a "
             "category; clear a cell to drop it. Pick from the dropdown - "
             "the names have to match Revit's exactly."),
            (fm_xlsx.STYLE_RULE, "Rules",
             "Parameter, operator and value, one rule per row. Add a row to "
             "add a rule. The operator has to be one the parameter suits, "
             "which is what the dropdown offers."),
        ]

        rows = [["RevoBIM Filter Manager", "How to use this workbook"], ["", ""]]
        styles = [[T, T], [D, D]]

        rows.append(["Colour", "What it is"])
        styles.append([T, T])
        for style, title, text in entries:
            rows.append(["", "{0} - {1}".format(title, text)])
            styles.append([style, D])
            rows.append(["", ""])
            styles.append([D, D])

        notes = [
            "How it works",
            "1. Export writes whatever the table is showing, so narrow it "
            "first if you only want some of the filters.",
            "2. Edit the coloured cells here. The dropdowns on the Lists tab "
            "show what each column will take.",
            "3. Import reads the sheet back into the tool and highlights "
            "everything it changed. Nothing touches the model yet.",
            "4. Check the highlighted cells, then press Apply Table. That is "
            "the step that writes to Revit.",
            "",
            "Anything that cannot be matched - a category that does not "
            "exist, a parameter the categories do not share, an id that has "
            "gone - is listed in a log rather than applied quietly.",
        ]
        for index, note in enumerate(notes):
            rows.append([note, ""])
            styles.append([T if index == 0 else D, D])

        return rows, styles

    def on_excel_menu(self, sender, args):
        """One button, then a choice - export or import."""
        from System.Windows.Controls.Primitives import PlacementMode
        menu = sender.ContextMenu
        if menu is None:
            return
        menu.PlacementTarget = sender
        menu.Placement = PlacementMode.Bottom
        menu.IsOpen = True

    def on_export_excel(self, sender, args):
        blocks = self.exportable_blocks()
        if not blocks:
            self.txtStatus.Text = "There is nothing in the table to export."
            return
        narrowed = len(blocks) < len(self.table_blocks)
        from Microsoft.Win32 import SaveFileDialog
        dialog = SaveFileDialog()
        dialog.Filter = "Excel workbook (*.xlsx)|*.xlsx"
        dialog.FileName = "RevoBIM filters.xlsx"
        dialog.Title = "Export the filter table"
        if not dialog.ShowDialog():
            return

        rows = self.table_to_rows()
        lists, depth = self.lists_sheet()
        last = len(rows) + 200        # room for rows added by hand

        guide_rows, guide_styles = self.guide_sheet()
        sheets = [
            {"name": "Filters", "rows": rows, "widths": self.XLS_WIDTHS,
             "styles": self.table_styles(rows),
             "validations": [
                 ("C2:C{0}".format(last),
                  "Lists!$A$2:$A${0}".format(depth + 1)),
                 ("D2:D{0}".format(last), "Lists!$C$2:$C$3"),
                 ("E2:E{0}".format(last),
                  "Lists!$D$2:$D${0}".format(depth + 1)),
                 ("F2:F{0}".format(last),
                  "Lists!$B$2:$B${0}".format(depth + 1)),
             ]},
            {"name": "Guide", "rows": guide_rows, "styles": guide_styles,
             "widths": [16, 104], "header_rows": 0, "freeze": False},
            {"name": "Lists", "rows": lists,
             "widths": [34, 30, 22, 40]},
        ]

        try:
            fm_xlsx.write_workbook(dialog.FileName, sheets)
        except Exception:
            forms.alert("The sheet was not written:\n\n{0}".format(
                traceback.format_exc()), title="RevoBIM Filter Manager")
            return

        self.txtStatus.Text = "Exported {0}{1} filter(s) to {2}".format(
            len(blocks), " of {0}".format(len(self.table_blocks))
            if narrowed else "", dialog.FileName)
        if forms.alert(
                "Exported {0} filter(s){1}.\n\n"
                "The Guide tab explains the colours and how the round trip "
                "works; the Lists tab holds the values each column will "
                "take.\n\n"
                "Open it now?".format(
                    len(blocks),
                    " - the ones the table is showing" if narrowed else ""),
                title="RevoBIM Filter Manager", yes=True, no=True):
            open_externally(dialog.FileName)

    def on_import_excel(self, sender, args):
        from Microsoft.Win32 import OpenFileDialog
        dialog = OpenFileDialog()
        dialog.Filter = "Excel workbook (*.xlsx)|*.xlsx"
        dialog.Title = "Import an edited filter table"
        if not dialog.ShowDialog():
            return

        try:
            rows = fm_xlsx.read_workbook(dialog.FileName)
        except Exception:
            forms.alert("The sheet could not be read:\n\n{0}".format(
                traceback.format_exc()), title="RevoBIM Filter Manager")
            return

        if not self.table_blocks:
            self.build_table_tab()
        changed, notes = self.apply_sheet(rows)

        # no dialog: the counts go on the status line, and anything that
        # needed a decision goes to the log where it can be read at leisure
        log_path = ""
        if notes:
            body = ["Imported from: {0}".format(dialog.FileName),
                    "{0} filter(s) updated".format(changed), ""]
            body.extend(notes)
            log_path = self.write_log("FilterManagerImport", body,
                                      "Imported the filter table")

        if changed:
            self.build_table_tab()
            self.refresh_footer()
            message = ("Imported {0} filter(s) - the changes are highlighted, "
                       "'Only edited filters' isolates them, and nothing is "
                       "written until Apply.".format(changed))
        else:
            message = "Nothing in the sheet differed from the table."

        if notes:
            message += "   {0} row(s) needed a look - see {1}".format(
                len(notes), log_path)
        self.txtStatus.Text = message

    def apply_sheet(self, rows):
        """Read the sheet back into the table, without touching the model."""
        by_id = {}
        for block in self.table_blocks:
            by_id[eid_value(block["pfe"].Id)] = block

        cat_by_name = {}
        for cid, nm in self.all_categories:
            cat_by_name[nm.lower()] = cid

        groups = []
        current = None
        for index, row in enumerate(rows):
            cells = [(c or "").strip() for c in row] + [""] * 7
            if index == 0 and cells[0].lower() == "id":
                continue
            if cells[0]:
                try:
                    key = int(float(cells[0]))
                except Exception:
                    continue
                current = {"key": key, "rows": [cells], "line": index + 1}
                groups.append(current)
            elif current is not None:
                current["rows"].append(cells)

        changed = 0
        notes = []
        for group in groups:
            block = by_id.get(group["key"])
            if block is None:
                notes.append("Row {0}: no filter with id {1} in this "
                             "model.".format(group["line"], group["key"]))
                continue
            if self.apply_sheet_block(block, group, cat_by_name, notes):
                changed += 1
        return changed, notes

    def apply_sheet_block(self, block, group, cat_by_name, notes):
        self.hydrate(block)
        head = group["rows"][0]
        line = group["line"]
        touched = False

        name = head[1]
        if name and name != block["name"]:
            block["name"] = name
            block["changes"].add("name")
            touched = True

        match = head[3].upper()
        if match.startswith("OR"):
            match = "OR"
        elif match.startswith("AND"):
            match = "AND"
        else:
            match = block["match"]
        if match != block["match"]:
            block["match"] = match
            block["changes"].add("match")
            touched = True

        cats = []
        for offset, row in enumerate(group["rows"]):
            if not row[2]:
                continue
            cid = cat_by_name.get(row[2].lower())
            if cid is None:
                notes.append("Row {0}: no category called '{1}'.".format(
                    line + offset, row[2]))
                continue
            if not any(eid_value(cid) == eid_value(c) for c in cats):
                cats.append(cid)
        if cats and [eid_value(c) for c in cats] != \
                [eid_value(c) for c in block["cats"]]:
            for position, cid in enumerate(cats):
                was = block["cats"][position] if position < len(block["cats"]) \
                    else None
                if was is None or eid_value(was) != eid_value(cid):
                    block["changes"].add("cat:{0}".format(position))
            block["cats"] = cats
            block["probe"] = None
            touched = True

        wanted = [(offset, row) for offset, row in enumerate(group["rows"])
                  if row[4]]
        if wanted:
            probe = self.table_probe(block)
            lookup = ff.parameter_lookup(doc, block["cats"])

            rules = []
            for offset, row in wanted:
                found = lookup.get(row[4].lower())
                if found is None:
                    notes.append("Row {0}: no parameter called '{1}' in this "
                                 "project.".format(line + offset, row[4]))
                    continue
                pid, scope = found
                if scope == "partial":
                    notes.append("Row {0}: '{1}' is not shared by every one of "
                                 "this filter's categories - used "
                                 "anyway.".format(line + offset, row[4]))
                elif scope == "project":
                    notes.append("Row {0}: '{1}' is a project parameter rather "
                                 "than one these categories offer - used "
                                 "anyway, Revit may refuse it on "
                                 "Apply.".format(line + offset, row[4]))

                storage, spec, yesno = probe.find(pid)
                op = self.operator_from_text(row[5], storage, yesno)
                if op is None:
                    notes.append("Row {0}: '{1}' is not an operator that suits "
                                 "'{2}'.".format(line + offset, row[5], row[4]))
                    continue

                value = row[6]
                if storage == "ElementId" and op in ("equals", "not_equals") \
                        and value:
                    resolved = self.element_value_from_text(probe, pid, value)
                    if resolved is None:
                        notes.append(
                            "Row {0}: nothing called '{1}' for '{2}' - use "
                            "contains for a text match.".format(
                                line + offset, value, row[4]))
                        continue
                    value = resolved

                rules.append({"param_id": pid, "op": op, "value": value,
                              "storage": storage, "spec": spec,
                              "yesno": yesno})
            if rules and self.rules_differ(block["rules"], rules):
                for position, rule in enumerate(rules):
                    was = block["rules"][position] \
                        if position < len(block["rules"]) else None
                    if was is None or self.rules_differ([was], [rule]):
                        block["changes"].add("rule:{0}".format(position))
                block["rules"] = rules
                touched = True

        if touched:
            block["dirty"] = True
            self.paint_block(block)
        return touched

    def operator_from_text(self, text, storage, yesno):
        """Match an operator by its wording, however it was typed."""
        wanted = (text or "").strip().lower()
        if not wanted:
            return None
        allowed = ff.ops_for_storage(storage, yesno)
        for key in allowed:
            if ff.OP_LABEL[key].lower() == wanted:
                return key
        for key in allowed:
            if key == wanted:
                return key
        # tolerate the shorthand people type
        shorthand = {"=": "equals", "==": "equals", "!=": "not_equals",
                     "<>": "not_equals", ">": "greater", ">=": "greater_equal",
                     "<": "less", "<=": "less_equal"}
        key = shorthand.get(wanted)
        return key if key in allowed else None

    def element_value_from_text(self, probe, pid, text):
        """Turn a typed element name back into the id it stands for."""
        wanted = (text or "").strip().lower()
        try:
            for value, name in probe.id_values(pid):
                if (name or "").strip().lower() == wanted:
                    return value
        except Exception:
            pass
        try:
            return ElementId(int(str(text).strip()))
        except Exception:
            return None

    def rules_differ(self, before, after):
        if len(before) != len(after):
            return True
        for old, new in zip(before, after):
            if eid_value(old.get("param_id")) != eid_value(new.get("param_id")):
                return True
            if old.get("op") != new.get("op"):
                return True
            if not self.same_value(old, new):
                return True
        return False

    # -- writing the table back --------------------------------------------
    def block_differs(self, block):
        """Does this block hold anything the model does not?

        Apply works off this rather than trusting the dirty flag alone. A
        flag can be missed - a handler that failed quietly, an edit path
        nobody thought of - and then Apply writes nothing and says nothing.
        Comparing against the model cannot be missed.
        """
        element = doc.GetElement(block["pfe"].Id)
        if element is None:
            return False
        try:
            if element.Name != block["name"]:
                return True
        except Exception:
            pass

        try:
            was = [eid_value(c) for c in element.GetCategories()]
            now = [eid_value(c) for c in block["cats"]]
            if sorted(was) != sorted(now):
                return True
        except Exception:
            pass

        try:
            match, rules = ff.read_filter(doc, element)
        except Exception:
            return False
        if block["probe"] is not None:
            for rule in rules:
                self.table_enrich(block, rule)
        for rule in rules:
            self.normalise_rule(rule)
        if match != block["match"]:
            return True
        if len(rules) != len(block["rules"]):
            return True
        for was, now in zip(rules, block["rules"]):
            if eid_value(was.get("param_id")) != eid_value(now.get("param_id")):
                return True
            if was.get("op") != now.get("op"):
                return True
            if not self.same_value(was, now):
                return True
        return False

    def apply_table(self):
        fm_core.crumb("apply table: started")
        dirty = []
        for block in self.table_blocks:
            # a block nobody has opened cannot have been edited
            if not block["hydrated"] and not block["dirty"]:
                continue
            if block["dirty"] or self.block_differs(block):
                block["dirty"] = True
                dirty.append(block)

        fm_core.crumb("apply table: {0} filter(s) differ".format(len(dirty)))
        if not dirty:
            forms.alert("Nothing in the table differs from the model, so "
                        "there is nothing to write.",
                        title="RevoBIM Filter Manager")
            self.txtStatus.Text = "Nothing in the table differs from the model."
            return

        names = {}
        for f in self.all_filters:
            try:
                names[eid_value(f.Id)] = f.Name
            except Exception:
                continue
        for block in dirty:
            names[eid_value(block["pfe"].Id)] = block["name"]

        problems = []
        payload = []
        for block in dirty:
            name = (block["name"] or "").strip()
            if not name:
                problems.append("A filter has been left with no name.")
                continue
            clash = False
            for key in names:
                if key != eid_value(block["pfe"].Id) \
                        and names[key].lower() == name.lower():
                    problems.append(
                        "Two filters would both be called '{0}'.".format(name))
                    clash = True
                    break
            if clash:
                continue
            if not block["cats"]:
                problems.append("'{0}' has no categories.".format(name))
                continue

            rules = []
            failed = False
            for index, rule in enumerate(block["rules"]):
                if rule.get("param_id") is None or rule.get("op") is None:
                    problems.append("'{0}' rule {1}: no parameter or "
                                    "operator.".format(name, index + 1))
                    failed = True
                    break
                raw = rule.get("value")
                if ff.OP_NEEDS_VALUE.get(rule["op"], True):
                    blank = raw is None or (not isinstance(raw, ElementId)
                                            and str(raw).strip() == "")
                    if blank:
                        problems.append("'{0}' rule {1}: no value.".format(
                            name, index + 1))
                        failed = True
                        break
                try:
                    rules.append(ff.build_rule(
                        doc, rule["param_id"], rule["op"], raw,
                        rule.get("storage", "String"), rule.get("spec"),
                        rule.get("yesno", False)))
                except Exception as ex:
                    problems.append("'{0}' rule {1}: {2}".format(
                        name, index + 1, ex))
                    failed = True
                    break
            if not failed:
                payload.append((block, name, list(block["cats"]), rules,
                                block["match"]))

        if problems:
            forms.alert("Nothing was written. Fix these first:\n\n" +
                        "\n".join(problems), title="RevoBIM Filter Manager")
            return
        if not payload:
            # never leave silently: a button that appears to do nothing is
            # indistinguishable from a broken one
            forms.alert("{0} filter(s) are marked as edited but none of them "
                        "produced anything to write.\n\nThis should not "
                        "happen - please send the log.".format(len(dirty)),
                        title="RevoBIM Filter Manager")
            return

        fm_core.crumb("apply table: {0} filter(s) ready to write".format(
            len(payload)))
        self.txtStatus.Text = "Writing {0} filter(s)...".format(len(payload))

        lines = []
        records = []

        def work(uiapp):
            t = Transaction(doc, "RevoBIM - Edit Filters")
            t.Start()
            try:
                for block, name, cats, rules, match in payload:
                    element = doc.GetElement(block["pfe"].Id)
                    if element is None:
                        records.append((name, "no longer in the model"))
                        continue
                    old_name = ff.element_name(doc, block["pfe"].Id, name)
                    notes = ff.apply_filter(doc, element, name, cats, rules,
                                            match)
                    lines.append("{0}{1}   {2} categor(ies), {3} rule(s), "
                                 "{4}".format(
                                     name,
                                     "" if old_name == name else
                                     "   (was '{0}')".format(old_name),
                                     len(cats), len(rules),
                                     "ALL rules" if match == "AND"
                                     else "ANY rule"))
                    for note in notes:
                        lines.append("    NOTE: {0}".format(note))

                status = t.Commit()
            except Exception:
                try:
                    t.RollBack()
                except Exception:
                    pass
                forms.alert("Nothing was changed:\n\n{0}".format(
                    traceback.format_exc()),
                    title="RevoBIM Filter Manager")
                return

            try:
                from Autodesk.Revit.DB import TransactionStatus
                if status != TransactionStatus.Committed:
                    forms.alert("Revit did not commit the changes (status "
                                "{0}). Nothing was written.".format(status),
                                title="RevoBIM Filter Manager")
                    return
            except Exception:
                pass

            # a void API call is not evidence: read every filter back
            for block, name, cats, rules, match in payload:
                element = doc.GetElement(block["pfe"].Id)
                if element is None:
                    records.append((name, "gone from the model after the write"))
                    continue
                try:
                    if element.Name != name:
                        records.append((name, "still called '{0}'".format(
                            element.Name)))
                except Exception:
                    pass
                try:
                    written = len(element.GetCategories())
                    if written != len(cats):
                        records.append((name, "{0} categor(ies) written, "
                                        "{1} asked for".format(written,
                                                               len(cats))))
                except Exception:
                    pass

            self.after_table_apply(lines, records, len(payload))

        status = self.runner.run(work)
        self.last_request = status
        fm_core.crumb("apply table: Revit answered '{0}'".format(status))

    def after_table_apply(self, lines, records, count):
        ff.clear_caches()
        if records:
            lines.append("")
            lines.append("DID NOT TAKE")
            for name, note in records:
                lines.append("  {0}: {1}".format(name, note))
        log_path = self.write_log("FilterManager", lines,
                                  "Edited {0} filter(s) in the table".format(count))
        self.reload_filters(self.current.Id if self.current is not None else None)
        self.table_blocks = []
        self.header = None
        self.chkTblChanged.IsChecked = False
        self.build_table_tab()
        self.refresh_footer()

        if records:
            headline = "Written, but {0} did not take.".format(len(records))
        else:
            headline = "Wow you just saved loads of time."
        self.txtStatus.Text = "{0} filter(s) written.".format(count)

        window = DoneWindow(headline, "Filter Manager Table",
                            "{0} filter(s) written{1}.".format(
                                count, " - {0} need a look".format(len(records))
                                if records else ""),
                            "WHAT CHANGED", lines, log_path)
        try:
            window.Owner = self
        except Exception:
            pass
        window.ShowDialog()

    # =======================================================================
    #  TAB 2 - FILTER PUSHER
    # =======================================================================
    def reload_templates(self, keep_host=None):
        self.templates = ff.get_view_templates(doc)
        self.template_counts = ff.template_filter_counts(doc, self.templates)
        names = set()
        for t in self.templates:
            try:
                names.add(t.Name)
            except Exception:
                pass
        for nm in list(self.target_state.keys()):
            if nm not in names:
                del self.target_state[nm]
        for nm in names:
            if nm not in self.target_state:
                self.target_state[nm] = False

        self.host = None
        if keep_host is not None:
            for t in self.templates:
                if eid_value(t.Id) == eid_value(keep_host):
                    self.host = t
                    break

        if self.host is None:
            self.host_filters = []
            self.push_state = {}
            self.txtHostName.Text = "- no host template selected -"
        else:
            self.host_filters = ff.get_template_filters(doc, self.host)
            self.txtHostName.Text = self.host.Name

        live = set()
        for _fid, nm in self.all_filter_pairs():
            live.add(nm)
        for nm in list(self.all_push_state.keys()):
            if nm not in live:
                del self.all_push_state[nm]

        self.fill_hosts()
        self.fill_push_filters()
        self.fill_all_filters()
        self.fill_targets()
        if self.views_loaded:
            self.load_target_views()

    def fill_hosts(self):
        search = self.txtHostSearch.Text
        self.lstHosts.Items.Clear()
        for t in self.templates:
            if not fm_core.row_visible(t.Name, 0, search, False):
                continue
            item = ui.new_listitem("{0}   ({1} filters)".format(
                t.Name, self.template_counts.get(eid_value(t.Id), 0)), t)
            self.lstHosts.Items.Add(item)
            if self.host is not None and eid_value(t.Id) == eid_value(self.host.Id):
                item.IsSelected = True

    def on_host_search(self, sender, args):
        self.searches["hosts"].poke()

    def on_host_changed(self, sender, args):
        item = self.lstHosts.SelectedItem
        if item is None:
            return
        self.host = item.Tag
        self.host_filters = ff.get_template_filters(doc, self.host)
        self.push_state = {}
        self.push_groups = {}
        for _fid, fname in self.host_filters:
            self.push_state[fname] = False
        self.txtHostName.Text = self.host.Name
        self.fill_push_filters()
        self.fill_targets()
        self.refresh_footer()

    # -- "Filters to push": a row per host filter, a tick per setting ----
    #  Settings columns are a fixed narrow width with their headings turned
    #  on end. The name column takes everything else, so the ticks sit
    #  hard against the right whatever the window's size.
    PUSH_CELL = 30
    PUSH_NAME_MIN = 120

    def push_groups_for(self, fname):
        if fname not in self.push_groups:
            self.push_groups[fname] = fo.all_groups(True)
        return self.push_groups[fname]

    def push_columns(self, grid):
        name_col = ui.col(width_star=1)
        name_col.MinWidth = self.PUSH_NAME_MIN
        grid.ColumnDefinitions.Add(name_col)
        for _key, _label in fo.PUSH_GROUPS:
            grid.ColumnDefinitions.Add(ui.col(pixels=self.PUSH_CELL))

    def build_push_header(self):
        from System.Windows.Controls import Grid, Border, TextBlock
        from System.Windows.Media import RotateTransform
        from System.Windows import (Thickness, FontWeights, HorizontalAlignment,
                                    VerticalAlignment)
        from System.Windows.Input import Cursors

        grid = Grid()
        self.push_columns(grid)

        name = TextBlock()
        name.Text = "Filter"
        name.FontSize = 11
        name.FontWeight = FontWeights.Bold
        name.VerticalAlignment = VerticalAlignment.Bottom
        name.Margin = Thickness(6, 0, 10, 6)
        name.SetResourceReference(TextBlock.ForegroundProperty, "Dim")
        ui.place(name, grid, 0)

        for i, (key, label) in enumerate(fo.PUSH_GROUPS):
            cell = Border()
            cell.BorderThickness = Thickness(1, 0, 0, 0)
            cell.SetResourceReference(Border.BorderBrushProperty, "EdgeFaint")
            cell.SetResourceReference(Border.BackgroundProperty, "HeaderRow")
            cell.Cursor = Cursors.Hand
            cell.ToolTip = ("{0}\nClick to tick or untick it on the selected "
                            "rows (every row when none is selected).".format(label))
            text = TextBlock()
            text.Text = label
            text.FontSize = 10
            text.FontWeight = FontWeights.Bold
            text.LayoutTransform = RotateTransform(-90)
            text.HorizontalAlignment = HorizontalAlignment.Center
            text.VerticalAlignment = VerticalAlignment.Bottom
            text.Margin = Thickness(0, 6, 0, 6)
            text.SetResourceReference(TextBlock.ForegroundProperty, "Dim")
            cell.Child = text

            def clicked(sender, args, k=key):
                self.toggle_push_column(k)

            cell.MouseLeftButtonUp += ui.ui_safe(clicked)
            ui.place(cell, grid, i + 1)

        self.pnlPushHeader.Child = grid
        self.push_header_grid = grid
        self.sync_push_header()

    def push_row(self, fid, fname):
        from System.Windows.Controls import Grid, TextBlock, ListBoxItem
        from System.Windows import (Thickness, HorizontalAlignment,
                                    VerticalAlignment, TextTrimming)

        groups = self.push_groups_for(fname)
        grid = Grid()
        self.push_columns(grid)

        # the tick and the name are separate, so clicking the name selects
        # the row (Ctrl/Shift for several) rather than ticking it
        from System.Windows.Controls import DockPanel
        cell = DockPanel()
        cell.Margin = Thickness(0, 2, 6, 2)
        pick = ui.new_checkbox("", fname, self.push_state.get(fname, False))
        pick.ToolTip = "Push this filter"
        pick.VerticalAlignment = VerticalAlignment.Center
        pick.Checked += self.on_push_ticked
        pick.Unchecked += self.on_push_ticked
        from System.Windows.Controls import Dock
        DockPanel.SetDock(pick, Dock.Left)
        cell.Children.Add(pick)
        label = TextBlock()
        label.Text = fname
        label.ToolTip = fname
        label.Margin = Thickness(4, 0, 0, 0)
        label.VerticalAlignment = VerticalAlignment.Center
        label.TextTrimming = TextTrimming.CharacterEllipsis
        cell.Children.Add(label)
        ui.place(cell, grid, 0)

        cells = {}
        for i, (key, title) in enumerate(fo.PUSH_GROUPS):
            cb = ui.new_checkbox("", (fname, key), groups.get(key, True))
            try:
                cb.Style = self.FindResource("CellCheck")
            except Exception:
                pass
            cb.HorizontalAlignment = HorizontalAlignment.Center
            cb.VerticalAlignment = VerticalAlignment.Center
            cb.ToolTip = "Push {0}".format(title)
            cb.Checked += self.on_push_cell
            cb.Unchecked += self.on_push_cell
            ui.place(cb, grid, i + 1)
            cells[key] = cb

        item = ListBoxItem()
        item.Content = grid
        item.Tag = fname
        item.HorizontalContentAlignment = HorizontalAlignment.Stretch
        self.push_rows.append({"name": fname, "id": fid, "item": item,
                               "grid": grid, "pick": pick, "cells": cells})
        return item

    def fill_push_filters(self):
        search = self.txtFilterSearch.Text
        self.lstPushFilters.Items.Clear()
        self.push_rows = []
        self.build_push_header()
        for fid, fname in self.host_filters:
            if not fm_core.row_visible(fname, 0, search, False):
                continue
            self.lstPushFilters.Items.Add(self.push_row(fid, fname))

    def push_row_named(self, fname):
        for row in self.push_rows:
            if row["name"] == fname:
                return row
        return None

    def selected_push_names(self):
        names = []
        for item in self.lstPushFilters.SelectedItems:
            try:
                names.append(item.Tag)
            except Exception:
                continue
        return names

    def push_edit_targets(self, fname):
        """Ticking inside a selected row ticks every selected row; ticking
        in a row that is not selected touches only that row."""
        selected = self.selected_push_names()
        if fname in selected and len(selected) > 1:
            return selected
        return [fname]

    def set_push_cell(self, names, key, value):
        self._bulk = True
        try:
            for nm in names:
                self.push_groups_for(nm)[key] = bool(value)
                row = self.push_row_named(nm)
                if row is not None:
                    row["cells"][key].IsChecked = bool(value)
        finally:
            self._bulk = False

    def set_push_pick(self, names, value):
        self._bulk = True
        try:
            for nm in names:
                self.push_state[nm] = bool(value)
                row = self.push_row_named(nm)
                if row is not None:
                    row["pick"].IsChecked = bool(value)
        finally:
            self._bulk = False

    def on_push_cell(self, sender, args):
        if self._bulk:
            return
        fname, key = sender.Tag
        self.set_push_cell(self.push_edit_targets(fname), key,
                           bool(sender.IsChecked))
        self.refresh_footer()

    def toggle_push_column(self, key):
        names = self.selected_push_names() or [r["name"] for r in self.push_rows]
        if not names:
            return
        all_on = all(self.push_groups_for(nm).get(key, True) for nm in names)
        self.set_push_cell(names, key, not all_on)
        self.refresh_footer()

    def sync_push_header(self, *args):
        """Keep the heading cells over their ticks.

        The rows sit inside the list's scroll viewer and the heading does
        not, so when the vertical scrollbar shows the rows lose its width
        and the heading has to give up the same amount on its right.
        """
        from System.Windows import Thickness
        viewer = self.push_scroller()
        gap = 0.0
        if viewer is not None:
            try:
                gap = max(0.0, viewer.ActualWidth - viewer.ViewportWidth)
            except Exception:
                gap = 0.0
        try:
            self.pnlPushHeader.Padding = Thickness(6, 0, 6 + gap, 0)
        except Exception:
            pass

    def push_scroller(self):
        """The ScrollViewer inside lstPushFilters' template, found once."""
        viewer = getattr(self, "_push_viewer", None)
        if viewer is not None:
            return viewer
        from System.Windows.Media import VisualTreeHelper
        from System.Windows.Controls import ScrollViewer
        stack = [self.lstPushFilters]
        while stack:
            node = stack.pop()
            if isinstance(node, ScrollViewer):
                self._push_viewer = node
                node.ScrollChanged += ui.ui_safe(self.sync_push_header)
                return node
            try:
                for i in range(VisualTreeHelper.GetChildrenCount(node)):
                    stack.append(VisualTreeHelper.GetChild(node, i))
            except Exception:
                continue
        return None

    def harvest_push(self):
        for row in self.push_rows:
            self.push_state[row["name"]] = bool(row["pick"].IsChecked)

    def on_pfilter_search(self, sender, args):
        self.harvest_push()
        self.searches["push"].poke()

    def run_push_filter_search(self):
        self.fill_push_filters()

    def on_push_ticked(self, sender, args):
        if self._bulk:
            return
        fname = sender.Tag
        self.set_push_pick(self.push_edit_targets(fname),
                           bool(sender.IsChecked))
        self.refresh_footer()

    def on_pfilters_all(self, sender, args):
        self.set_push_pick([r["name"] for r in self.push_rows], True)
        self.refresh_footer()

    def on_pfilters_none(self, sender, args):
        self.set_push_pick([r["name"] for r in self.push_rows], False)
        self.refresh_footer()

    # -- overwrite mode -------------------------------------------------------
    OVERWRITE_LABELS = {"all": "Overwrite Target All",
                        "new": "Overwrite Target New Only"}

    def on_overwrite_menu(self, sender, args):
        from System.Windows.Controls import StackPanel, Border, TextBlock, Orientation
        from System.Windows.Controls.Primitives import PlacementMode
        from System.Windows import Thickness, CornerRadius, VerticalAlignment
        menu = sender.ContextMenu
        if menu is None:
            return
        for item in menu.Items:
            try:
                mode = item.Tag
                row = StackPanel()
                row.Orientation = Orientation.Horizontal
                dot = Border()
                dot.Width = 9
                dot.Height = 9
                dot.CornerRadius = CornerRadius(5)
                dot.BorderThickness = Thickness(1)
                dot.Margin = Thickness(0, 0, 8, 0)
                dot.VerticalAlignment = VerticalAlignment.Center
                dot.SetResourceReference(Border.BorderBrushProperty, "Orange")
                if mode == self.overwrite_mode:
                    dot.SetResourceReference(Border.BackgroundProperty, "Orange")
                text = TextBlock()
                text.Text = self.OVERWRITE_LABELS.get(mode, mode)
                row.Children.Add(dot)
                row.Children.Add(text)
                item.Header = row
            except Exception:
                continue
        menu.PlacementTarget = sender
        menu.Placement = PlacementMode.Bottom
        menu.IsOpen = True

    def on_overwrite_pick(self, sender, args):
        self.overwrite_mode = "new" if sender.Tag == "new" else "all"
        label = self.OVERWRITE_LABELS[self.overwrite_mode]
        for box in (self.txtOverwriteA, self.txtOverwriteB):
            try:
                box.Text = label
            except Exception:
                continue
        self.refresh_footer()

    def fill_targets(self):
        search = self.txtTargetSearch.Text
        self.lstTargets.Items.Clear()
        host_val = eid_value(self.host.Id) if self.host is not None else None
        for t in self.templates:
            if host_val is not None and eid_value(t.Id) == host_val:
                continue
            if not fm_core.row_visible(t.Name, 0, search, False):
                continue
            cb = ui.new_checkbox(t.Name, t, self.target_state.get(t.Name, False))
            cb.Checked += self.on_target_ticked
            cb.Unchecked += self.on_target_ticked
            self.lstTargets.Items.Add(cb)

    def harvest_targets(self):
        for item in self.lstTargets.Items:
            self.target_state[item.Content] = bool(item.IsChecked)

    def on_target_search(self, sender, args):
        self.harvest_targets()
        self.searches["targets"].poke()

    def on_target_ticked(self, sender, args):
        self.harvest_targets()
        self.refresh_footer()

    def on_targets_all(self, sender, args):
        for item in self.lstTargets.Items:
            item.IsChecked = True
        self.harvest_targets()
        self.refresh_footer()

    def on_targets_none(self, sender, args):
        for item in self.lstTargets.Items:
            item.IsChecked = False
        self.harvest_targets()
        self.refresh_footer()

    # -- column three: Target View Templates / Target Views ---------------
    def select_target_tab(self, index):
        """0 = view templates, 1 = ordinary views. Ticks on both are kept,
        and a push goes to everything ticked on either."""
        self.tgt_index = index
        self.btnTgtTemplates.Tag = "on" if index == 0 else "off"
        self.btnTgtViews.Tag = "on" if index == 1 else "off"
        ui.set_visible(self.pnlTgtTemplates, index == 0)
        ui.set_visible(self.pnlTgtViews, index == 1)
        if index == 1 and not self.views_loaded:
            self.load_target_views()
        self.refresh_footer()

    def on_tgt_templates(self, sender, args):
        self.select_target_tab(0)

    def on_tgt_views(self, sender, args):
        self.select_target_tab(1)

    def load_target_views(self):
        """Read the project's views. Done on first opening the tab, not at
        start-up: a large model has thousands of views."""
        self.harvest_views()
        self.view_rows = ff.get_filterable_views(doc)
        self.views_loaded = True
        live = set(r["idv"] for r in self.view_rows)
        for key in list(self.view_state.keys()):
            if key not in live:
                del self.view_state[key]
        # hidden types that no longer exist stop mattering; new types arrive
        # ticked, because only the unticked ones are remembered
        keys = set(fm_core.type_key(r) for r in self.view_rows)
        self.types_hidden = set(k for k in self.types_hidden if k in keys)
        self.build_view_type_menu()
        self.fill_target_views()

    # -- the view-type dropdown --------------------------------------------
    def build_view_type_menu(self):
        from System.Windows import Thickness
        self.stkViewTypes.Children.Clear()
        entries = fm_core.view_type_entries(self.view_rows)
        for key, label, count in entries:
            cb = ui.new_checkbox(u"{0}   {1}".format(label, count), key,
                                 key not in self.types_hidden)
            cb.Margin = Thickness(0, 2, 0, 2)
            cb.Checked += self.on_view_type_ticked
            cb.Unchecked += self.on_view_type_ticked
            self.stkViewTypes.Children.Add(cb)
        self.txtViewTypes.Text = fm_core.dropdown_caption(
            len(entries), len(self.types_hidden))

    def on_view_types_open(self, sender, args):
        import time
        if not getattr(self, "_pop_wired", False):
            self._pop_wired = True
            self.popViewTypes.Closed += ui.ui_safe(self.view_types_closed)
        # the click that closes the popup by landing on the button would
        # otherwise open it straight back up
        if time.time() - self._pop_closed_at < 0.3:
            return
        try:
            self.popViewTypes.PlacementTarget = self.btnViewTypes
            self.popViewTypes.MinWidth = max(260, self.btnViewTypes.ActualWidth)
        except Exception:
            pass
        self.popViewTypes.IsOpen = not self.popViewTypes.IsOpen

    def view_types_closed(self, sender, args):
        import time
        self._pop_closed_at = time.time()

    def read_view_type_ticks(self):
        hidden = set()
        for cb in self.stkViewTypes.Children:
            if not cb.IsChecked:
                hidden.add(cb.Tag)
        self.types_hidden = hidden
        self.txtViewTypes.Text = fm_core.dropdown_caption(
            self.stkViewTypes.Children.Count, len(hidden))

    def on_view_type_ticked(self, sender, args):
        if self._bulk:
            return
        self.harvest_views()
        self.read_view_type_ticks()
        self.searches["views"].poke()

    def set_all_view_types(self, ticked):
        self._bulk = True
        try:
            for cb in self.stkViewTypes.Children:
                cb.IsChecked = ticked
        finally:
            self._bulk = False
        self.harvest_views()
        self.read_view_type_ticks()
        self.fill_target_views()

    def on_view_types_all(self, sender, args):
        self.set_all_view_types(True)

    def on_view_types_none(self, sender, args):
        self.set_all_view_types(False)

    def fill_target_views(self):
        search = self.txtViewSearch.Text
        hide_locked = bool(self.chkHideLocked.IsChecked)
        only = None
        if self.views_only_selected:
            only = set(k for k in self.view_state if self.view_state[k])
        self.lstTargetViews.Items.Clear()
        shown = 0
        for row in self.view_rows:
            if not fm_core.view_row_visible(row, self.types_hidden, search,
                                            hide_locked, only):
                continue
            text = u"{0}    [{1}]".format(row["name"], row["type"])
            if row["locked"]:
                text += u"   - template: {0}".format(row["template"])
            cb = ui.new_checkbox(text, row["idv"],
                                 (not row["locked"]) and
                                 self.view_state.get(row["idv"], False))
            if row["locked"]:
                cb.IsEnabled = False
                cb.ToolTip = (u"Filters on this view are set by its view "
                              u"template '{0}'. Push to the template, or "
                              u"untick V/G Filters in that template."
                              ).format(row["template"])
            elif row["template"]:
                cb.ToolTip = u"Template '{0}' leaves filters to the view".format(
                    row["template"])
            cb.Checked += self.on_view_ticked
            cb.Unchecked += self.on_view_ticked
            self.lstTargetViews.Items.Add(cb)
            shown += 1
        self.txtViewCount.Text = "{0} of {1} views".format(
            shown, len(self.view_rows))

    # -- Current view / Show only selected -------------------------------
    def on_current_view(self, sender, args):
        """Tick the view open in Revit now and make sure the list shows it,
        whatever the dropdown, search or "only selected" would say."""
        try:
            uidoc_now = __revit__.ActiveUIDocument
            view = uidoc_now.ActiveView if uidoc_now is not None else None
            same_doc = uidoc_now is not None and \
                uidoc_now.Document.Equals(doc)
        except Exception:
            view, same_doc = None, False
        if view is None or not same_doc:
            self.txtStatus.Text = ("The active view is in another project - "
                                   "switch back to {0}.".format(doc.Title))
            return
        if not self.views_loaded:
            self.load_target_views()
        self.harvest_views()

        idv = eid_value(view.Id)
        row = None
        for r in self.view_rows:
            if r["idv"] == idv:
                row = r
                break
        name = ff.element_name(doc, view, "(view)")
        if row is None:
            self.txtStatus.Text = (
                "'{0}' cannot take filters (sheets, schedules and view "
                "templates are not targets).".format(name))
            return

        # make sure nothing is hiding it
        key = fm_core.type_key(row)
        if key in self.types_hidden:
            self.types_hidden.discard(key)
            self.build_view_type_menu()
        if not fm_core.view_row_visible(row, None, self.txtViewSearch.Text):
            self.txtViewSearch.Text = ""
        if row["locked"] and self.chkHideLocked.IsChecked:
            self.chkHideLocked.IsChecked = False

        if row["locked"]:
            self.fill_target_views()
            self.select_view_item(idv)
            self.txtStatus.Text = (
                "'{0}' takes its filters from the template '{1}' - tick that "
                "on Target View Templates instead.".format(name, row["template"]))
            return

        self.view_state[idv] = True
        self.fill_target_views()
        self.select_view_item(idv)
        self.refresh_footer()
        self.txtStatus.Text = "Ticked the current view: {0}".format(name)

    def select_view_item(self, idv):
        for item in self.lstTargetViews.Items:
            if item.Tag == idv:
                self.lstTargetViews.SelectedItem = item
                self.lstTargetViews.ScrollIntoView(item)
                return

    def on_only_selected(self, sender, args):
        self.harvest_views()
        self.views_only_selected = not self.views_only_selected
        self.paint_only_selected()
        self.fill_target_views()

    def paint_only_selected(self):
        from System.Windows.Controls import Button
        on = self.views_only_selected
        self.txtOnlySelected.Text = "Showing only selected" if on \
            else "Show only selected"
        btn = self.btnOnlySelected
        if on:
            btn.SetResourceReference(Button.BackgroundProperty, "Sel")
            btn.SetResourceReference(Button.BorderBrushProperty, "Orange")
        else:
            btn.SetResourceReference(Button.BackgroundProperty, "Btn")
            btn.SetResourceReference(Button.BorderBrushProperty, "Edge")

    def harvest_views(self):
        for item in self.lstTargetViews.Items:
            if item.IsEnabled:
                self.view_state[item.Tag] = bool(item.IsChecked)

    def ticked_view_rows(self):
        return [r for r in self.view_rows
                if not r["locked"] and self.view_state.get(r["idv"], False)]

    def on_view_search(self, sender, args):
        self.harvest_views()
        self.searches["views"].poke()

    def on_view_ticked(self, sender, args):
        self.harvest_views()
        self.refresh_footer()

    def on_hide_locked(self, sender, args):
        self.harvest_views()
        self.fill_target_views()

    def on_views_all(self, sender, args):
        for item in self.lstTargetViews.Items:
            if item.IsEnabled:
                item.IsChecked = True
        self.harvest_views()
        self.refresh_footer()

    def on_views_none(self, sender, args):
        for item in self.lstTargetViews.Items:
            item.IsChecked = False
        self.harvest_views()
        self.refresh_footer()

    # -- the "Filters" source sub-tab ---------------------------------------
    #  Left: every filter in the project, ticked and moved across with the
    #  arrow. Middle: a table of the staged filters laid out like Revit's own
    #  Filters tab, with each cell editable.
    COLUMNS = [
        ("name", "Name", 206),
        ("enable", "Enable Filter", 76),
        ("visible", "Visibility", 66),
        ("projection", "Lines", 94),
        ("surface", "Patterns", 94),
        ("transparency", "Transparency", 82),
        ("cut", "Lines", 94),
        ("cutpattern", "Patterns", 94),
        ("halftone", "Halftone", 62),
    ]

    def table_width(self):
        """The table is laid out to its own natural width, so the panel it
        sits in is sized to that rather than the table being scrolled."""
        return sum(width for _key, _label, width in self.COLUMNS)

    def line_pattern_list(self):
        if self._line_patterns is None:
            self._line_patterns = fo.line_patterns(doc)
        return self._line_patterns

    def fill_pattern_list(self):
        if self._fill_patterns is None:
            self._fill_patterns = fo.fill_patterns(doc)
        return self._fill_patterns

    def all_filter_pairs(self):
        pairs = []
        for f in self.all_filters:
            try:
                pairs.append((f.Id, f.Name))
            except Exception:
                continue
        return pairs

    def spec_for(self, filter_id):
        key = eid_value(filter_id)
        if key not in self.specs:
            self.specs[key] = fo.new_spec()
        return self.specs[key]

    def is_staged(self, filter_id):
        target = eid_value(filter_id)
        return any(eid_value(fid) == target for fid, _nm in self.staged)

    # -- left hand list -----------------------------------------------------
    def fill_all_filters(self):
        search = self.txtAllFilterSearch.Text
        self.lstAllFilters.Items.Clear()
        for fid, nm in self.all_filter_pairs():
            if not fm_core.row_visible(nm, 0, search, False):
                continue
            staged = self.is_staged(fid)
            label = nm + ("   (staged)" if staged else "")
            cb = ui.new_checkbox(label, fid, self.all_push_state.get(nm, False))
            cb.IsEnabled = not staged
            cb.Checked += self.on_allfilter_ticked
            cb.Unchecked += self.on_allfilter_ticked
            item = ui.new_listitem("", fid)
            item.Content = cb
            self.lstAllFilters.Items.Add(item)

    def harvest_all_filters(self):
        """Read the ticks back, keyed off the element id.

        The label carries a "(staged)" suffix, so parsing the name back out
        of it would be one string edit away from silently losing a tick.
        """
        names = {}
        for fid, nm in self.all_filter_pairs():
            names[eid_value(fid)] = nm
        for item in self.lstAllFilters.Items:
            try:
                nm = names.get(eid_value(item.Tag))
                if nm is not None:
                    self.all_push_state[nm] = bool(item.Content.IsChecked)
            except Exception:
                continue

    def on_allfilter_search(self, sender, args):
        self.harvest_all_filters()
        self.searches["all"].poke()

    def run_all_filter_search(self):
        self.fill_all_filters()

    def on_allfilter_ticked(self, sender, args):
        self.harvest_all_filters()
        self.refresh_footer()

    def on_allfilters_all(self, sender, args):
        for item in self.lstAllFilters.Items:
            try:
                if item.Content.IsEnabled:
                    item.Content.IsChecked = True
            except Exception:
                pass
        self.harvest_all_filters()
        self.refresh_footer()

    def on_allfilters_none(self, sender, args):
        for item in self.lstAllFilters.Items:
            try:
                item.Content.IsChecked = False
            except Exception:
                pass
        self.harvest_all_filters()
        self.refresh_footer()

    # -- the arrows ---------------------------------------------------------
    def on_stage_add(self, sender, args):
        self.harvest_all_filters()
        added = 0
        for fid, nm in self.all_filter_pairs():
            if not self.all_push_state.get(nm, False):
                continue
            if self.is_staged(fid):
                continue
            self.staged.append((fid, nm))
            self.spec_for(fid)
            self.staged_ticked[nm] = False
            added += 1
        if not added:
            self.txtStatus.Text = "Tick a filter on the left first."
            return
        for nm in list(self.all_push_state.keys()):
            self.all_push_state[nm] = False
        self.fill_all_filters()
        self.build_props_panel()
        self.refresh_footer()
        self.txtStatus.Text = "Added {0} filter(s) to the table.".format(added)

    def on_stage_remove(self, sender, args):
        self.harvest_table()
        keep = []
        gone = 0
        for fid, nm in self.staged:
            if self.staged_ticked.get(nm, False):
                gone += 1
            else:
                keep.append((fid, nm))
        if not gone:
            self.txtStatus.Text = "Tick a row in the table first."
            return
        self.staged = keep
        self.fill_all_filters()
        self.build_props_panel()
        self.refresh_footer()
        self.txtStatus.Text = "Removed {0} row(s).".format(gone)

    # -- the table ----------------------------------------------------------
    def build_props_panel(self):
        """A row per staged filter, laid out like Revit's own Filters tab."""
        self.pnlProps.Children.Clear()
        self.row_controls = []

        if not self.staged:
            self.txtPropTarget.Text = "Nothing staged yet."
            self.pnlProps.Children.Add(ui.new_text(
                "Tick filters on the left and press the green arrow to bring "
                "them in here.", "Dim", 11, margin=(8, 8, 8, 8)))
            return

        self.txtPropTarget.Text = "{0} filter(s) staged".format(len(self.staged))
        self.pnlProps.Children.Add(self.staging_header())
        for fid, nm in self.staged:
            self.pnlProps.Children.Add(self.table_row(fid, nm))

    def staging_header(self):
        from System.Windows.Controls import Grid, Border, TextBlock
        from System.Windows import Thickness, FontWeights, HorizontalAlignment

        outer = Border()
        outer.Width = self.table_width()
        outer.Background = ui.pbrush("HeaderRow")
        outer.BorderBrush = ui.pbrush("Edge")
        outer.BorderThickness = Thickness(0, 0, 0, 1)

        grid = Grid()
        for _key, _label, width in self.COLUMNS:
            grid.ColumnDefinitions.Add(ui.col(pixels=width))
        grid.RowDefinitions.Add(ui.row())
        grid.RowDefinitions.Add(ui.row())

        groups = [(3, 5, "Projection / Surface"), (6, 7, "Cut")]
        spanned = {}
        for first, last, title in groups:
            label = TextBlock()
            label.Text = title
            label.FontSize = 10
            label.FontWeight = FontWeights.Bold
            label.HorizontalAlignment = HorizontalAlignment.Center
            label.Margin = Thickness(0, 4, 0, 2)
            label.SetResourceReference(TextBlock.ForegroundProperty, "Blue")
            Grid.SetRow(label, 0)
            Grid.SetColumn(label, first)
            Grid.SetColumnSpan(label, last - first + 1)
            grid.Children.Add(label)
            for c in range(first, last + 1):
                spanned[c] = True

        for i, (_key, label_text, _width) in enumerate(self.COLUMNS):
            tb = TextBlock()
            tb.Text = label_text
            tb.FontSize = 10
            tb.FontWeight = FontWeights.Bold
            tb.TextWrapping = ui.wrap()
            tb.Margin = Thickness(6, 3, 6, 5)
            if i:
                tb.HorizontalAlignment = HorizontalAlignment.Center
            tb.SetResourceReference(TextBlock.ForegroundProperty, "Dim")
            Grid.SetColumn(tb, i)
            if i in spanned:
                Grid.SetRow(tb, 1)
            else:
                Grid.SetRow(tb, 0)
                Grid.SetRowSpan(tb, 2)
            grid.Children.Add(tb)

        outer.Child = grid
        return outer

    def table_row(self, fid, name):
        from System.Windows.Controls import Grid, Border
        from System.Windows import Thickness, HorizontalAlignment

        spec = self.spec_for(fid)
        row = {"id": fid, "name": name}

        outer = Border()
        outer.Width = self.table_width()
        outer.BorderBrush = ui.pbrush("EdgeFaint")
        outer.BorderThickness = Thickness(0, 0, 0, 1)
        outer.Padding = Thickness(0, 2, 0, 2)

        grid = Grid()
        for _key, _label, width in self.COLUMNS:
            grid.ColumnDefinitions.Add(ui.col(pixels=width))

        # name doubles as the row tick
        pick = ui.new_checkbox(name, fid, self.staged_ticked.get(name, False))
        pick.Margin = Thickness(6, 3, 4, 3)
        pick.Checked += self.on_row_ticked
        pick.Unchecked += self.on_row_ticked
        row["pick"] = pick
        ui.place(pick, grid, 0)

        for key, column in (("enabled", 1), ("visible", 2), ("halftone", 8)):
            cb = ui.new_checkbox("", None, spec.get(key))
            cb.HorizontalAlignment = HorizontalAlignment.Center
            cb.Margin = Thickness(0, 4, 0, 4)
            cb.Checked += self.on_cell_toggled
            cb.Unchecked += self.on_cell_toggled
            row[key] = cb
            ui.place(cb, grid, column)

        for kind, column in (("projection", 3), ("surface", 4),
                             ("cut", 6), ("cutpattern", 7)):
            btn = self.override_button(fid, name, kind, spec)
            row[kind] = btn
            ui.place(btn, grid, column)

        box = ui.new_textbox(str(spec.get("transparency") or 0), "0-100", width=56)
        box.HorizontalAlignment = HorizontalAlignment.Center
        box.Margin = Thickness(0, 3, 0, 3)
        box.TextChanged += self.on_cell_toggled
        row["transparency"] = box
        ui.place(box, grid, 5)

        outer.Child = grid
        row["border"] = outer
        self.row_controls.append(row)
        return outer

    def override_button(self, fid, name, kind, spec):
        from System.Windows import Thickness
        btn = ui.new_button("", "Ghost", height=24)
        btn.Margin = Thickness(4, 3, 4, 3)
        btn.Content = self.override_preview(kind, spec)

        def clicked(sender, args, f=fid, n=name, k=kind, b=btn):
            self.edit_override(f, n, k, b)

        btn.Click += ui.ui_safe(clicked)
        return btn

    def override_preview(self, kind, spec):
        """A line sample, a colour swatch, or the word Override."""
        from System.Windows.Controls import Border, TextBlock, Grid
        from System.Windows import Thickness, HorizontalAlignment, VerticalAlignment

        if kind in ("projection", "cut"):
            ck = "proj_colour" if kind == "projection" else "cut_colour"
            wk = "proj_weight" if kind == "projection" else "cut_weight"
            pk = "proj_pattern" if kind == "projection" else "cut_pattern"
            if not (spec.get(ck) or spec.get(wk) or spec.get(pk)):
                return self.override_label()
            line = Border()
            line.Height = max(1, min(5, int(spec.get(wk) or 2)))
            line.Width = 62
            line.VerticalAlignment = VerticalAlignment.Center
            line.HorizontalAlignment = HorizontalAlignment.Center
            ui.paint_swatch(line, spec.get(ck) or ui.pcolour("Txt")[3:])
            return line

        fg = "surf_fg_colour" if kind == "surface" else "cut_fg_colour"
        fp = "surf_fg_pattern" if kind == "surface" else "cut_fg_pattern"
        bg = "surf_bg_colour" if kind == "surface" else "cut_bg_colour"
        bp = "surf_bg_pattern" if kind == "surface" else "cut_bg_pattern"
        if not (spec.get(fg) or spec.get(fp) or spec.get(bg) or spec.get(bp)):
            return self.override_label()

        block = Border()
        block.Height = 15
        block.Width = 62
        block.BorderBrush = ui.pbrush("EdgeStrong")
        block.BorderThickness = Thickness(1)
        ui.paint_swatch(block, spec.get(fg) or spec.get(bg) or ui.pcolour("Dim")[3:])
        return block

    def override_label(self):
        from System.Windows.Controls import TextBlock
        tb = TextBlock()
        tb.Text = "Override..."
        tb.FontSize = 10
        tb.SetResourceReference(TextBlock.ForegroundProperty, "Dim")
        return tb

    def edit_targets(self, fid):
        """Which rows an edit on this row applies to.

        Editing a ticked row edits every ticked row, so several filters can
        be set in one go. Editing a row that is not ticked touches only it.
        """
        self.harvest_table()
        ticked = [f for f, nm in self.staged if self.staged_ticked.get(nm, False)]
        if any(eid_value(f) == eid_value(fid) for f in ticked) and len(ticked) > 1:
            return ticked
        return [fid]

    def edit_override(self, fid, name, kind, button):
        targets = self.edit_targets(fid)
        spec = self.spec_for(fid)

        if len(targets) > 1:
            subject = "{0}  and {1} other ticked filter(s)".format(
                name, len(targets) - 1)
            scope = ("This will be applied to all {0} ticked "
                     "filters.".format(len(targets)))
        else:
            subject = name
            scope = ""

        dlg = OverrideWindow(kind, spec, subject, self.line_pattern_list(),
                             self.fill_pattern_list(), scope)
        try:
            dlg.Owner = self
        except Exception:
            pass
        dlg.ShowDialog()
        if dlg.result is None:
            return

        for target in targets:
            target_spec = self.spec_for(target)
            for k in dlg.result:
                target_spec[k] = dlg.result[k]

        if len(targets) > 1:
            self.build_props_panel()
            self.txtStatus.Text = "Set {0} on {1} ticked filter(s).".format(
                OverrideWindow.TITLES.get(kind, kind), len(targets))
        else:
            button.Content = self.override_preview(kind, spec)

    def on_row_ticked(self, sender, args):
        self.harvest_table()

    def on_cell_toggled(self, sender, args):
        """A cell edited on a ticked row is applied to every ticked row."""
        self.harvest_table()
        row = None
        for candidate in self.row_controls:
            for key in ("enabled", "visible", "halftone", "transparency"):
                if candidate.get(key) is sender:
                    row = candidate
                    break
            if row is not None:
                break
        if row is None:
            return

        targets = [f for f, nm in self.staged if self.staged_ticked.get(nm, False)]
        if len(targets) < 2:
            return
        if not any(eid_value(f) == eid_value(row["id"]) for f in targets):
            return

        source = self.spec_for(row["id"])
        for target in targets:
            if eid_value(target) == eid_value(row["id"]):
                continue
            spec = self.spec_for(target)
            for key in ("enabled", "visible", "halftone", "transparency"):
                spec[key] = source[key]
        self.build_props_panel()

    def harvest_table(self):
        """Read every cell in the table back into the specs."""
        for row in getattr(self, "row_controls", []):
            name = row["name"]
            try:
                self.staged_ticked[name] = bool(row["pick"].IsChecked)
            except Exception:
                pass
            spec = self.spec_for(row["id"])
            for key in ("enabled", "visible", "halftone"):
                try:
                    spec[key] = bool(row[key].IsChecked)
                except Exception:
                    pass
            try:
                spec["transparency"] = max(0, min(100, int(
                    row["transparency"].Text.strip() or 0)))
            except Exception:
                spec["transparency"] = 0

    # -- the three table buttons -------------------------------------------
    def ticked_rows(self):
        self.harvest_table()
        return [(fid, nm) for fid, nm in self.staged
                if self.staged_ticked.get(nm, False)]

    def on_copy_props(self, sender, args):
        rows = self.ticked_rows()
        if not rows:
            self.txtStatus.Text = "Tick the row you want to copy from."
            return
        source = self.spec_for(rows[0][0])
        n = 0
        for fid, _nm in self.staged:
            if eid_value(fid) == eid_value(rows[0][0]):
                continue
            target = self.spec_for(fid)
            for k in source:
                target[k] = source[k]
            n += 1
        self.build_props_panel()
        self.txtStatus.Text = "Copied '{0}' onto {1} other row(s).".format(
            rows[0][1], n)

    def on_read_props(self, sender, args):
        rows = self.ticked_rows()
        if not rows:
            self.txtStatus.Text = "Tick the rows you want to read into."
            return
        if self.host is None:
            forms.alert("Pick a host view template on the Templates tab first, "
                        "then this reads each filter's graphics out of it.",
                        title="RevoBIM Filter Manager")
            return
        try:
            on_host = set(eid_value(f) for f in self.host.GetFilters())
        except Exception:
            on_host = set()

        read = missing = 0
        for fid, _nm in rows:
            if eid_value(fid) in on_host:
                self.specs[eid_value(fid)] = fo.read_overrides(self.host, fid)
                read += 1
            else:
                missing += 1
        self.build_props_panel()
        self.txtStatus.Text = "Read {0} row(s) from '{1}'{2}.".format(
            read, self.host.Name,
            "; {0} not on that template".format(missing) if missing else "")

    def on_reset_props(self, sender, args):
        rows = self.ticked_rows()
        if not rows:
            self.txtStatus.Text = "Tick the rows you want to reset."
            return
        for fid, _nm in rows:
            self.specs[eid_value(fid)] = fo.new_spec()
        self.build_props_panel()
        self.txtStatus.Text = "Reset {0} row(s).".format(len(rows))

    def push_filters(self):
        self.harvest_targets()
        self.harvest_views()
        targets = [t for t in self.templates
                   if self.target_state.get(t.Name, False)]
        for row in self.ticked_view_rows():
            view = doc.GetElement(row["id"])
            if view is not None:
                targets.append(view)

        if not targets:
            forms.alert("Tick at least one target view template or view.",
                        title="RevoBIM Filter Manager")
            return

        if self.source_tab() == 1:
            self.push_from_project(targets)
        else:
            self.push_from_host(targets)

    # -- push from a host template, carrying its own settings ---------------
    def push_from_host(self, targets):
        self.harvest_push()

        if self.host is None:
            forms.alert("Pick a host view template first.",
                        title="RevoBIM Filter Manager")
            return

        filters = [(fid, fname) for fid, fname in self.host_filters
                   if self.push_state.get(fname, False)]
        host_val = eid_value(self.host.Id)
        targets = [t for t in targets if eid_value(t.Id) != host_val]

        if not filters:
            forms.alert("Tick at least one filter to push.",
                        title="RevoBIM Filter Manager")
            return
        if not targets:
            forms.alert("The host template is the only target ticked.",
                        title="RevoBIM Filter Manager")
            return

        host = self.host
        control = bool(self.chkControl.IsChecked)

        def settings_for(fid):
            return (host.GetFilterOverrides(fid),
                    host.GetFilterVisibility(fid),
                    self._enabled_on(host, fid))

        groups = {}
        for _fid, fname in filters:
            groups[fname] = dict(self.push_groups_for(fname))

        def groups_for(fid, fname):
            return groups.get(fname)

        self.run_push(filters, targets, settings_for, control,
                      "Pushed from '{0}'".format(host.Name),
                      "the host template's own settings",
                      groups_for=groups_for)

    # -- push any filter in the project, with graphics set here -------------
    def push_from_project(self, targets):
        self.harvest_table()

        filters = list(self.staged)
        if not filters:
            forms.alert("Nothing is in the table yet.\n\nTick filters on the "
                        "left and press the green arrow to bring them in.",
                        title="RevoBIM Filter Manager")
            return

        specs = {}
        for fid, _nm in filters:
            specs[eid_value(fid)] = self.spec_for(fid)

        def settings_for(fid):
            spec = specs.get(eid_value(fid)) or fo.new_spec()
            return (fo.build_overrides(spec), bool(spec.get("visible", True)),
                    bool(spec.get("enabled", True)))

        self.run_push(filters, targets, settings_for,
                      bool(self.chkControl.IsChecked),
                      "Pushed from the project filter table",
                      "the graphics set in the table", specs)

    def _enabled_on(self, view, fid):
        try:
            return view.GetIsFilterEnabled(fid)
        except Exception:
            return True

    # -- the write ----------------------------------------------------------
    def run_push(self, filters, targets, settings_for, control,
                 subject, source_note, specs=None, groups_for=None):
        """Push, then read the model back to see whether it actually took.

        Element handles captured when the window opened go stale, especially
        with a modeless window the user has been working around, so the
        target views are re-fetched by id inside the transaction.
        """
        target_ids = [t.Id for t in targets]
        filter_ids = [(fid, nm) for fid, nm in filters]

        records = []
        counters = {"added": 0, "updated": 0, "failed": 0, "skipped": 0,
                    "kept": 0}
        skipped_ids = set()
        lock_cache = {}
        new_only = self.overwrite_mode == "new"

        def work(uiapp):
            t = Transaction(doc, "RevoBIM - Push Filters")
            t.Start()
            try:
                for tid in target_ids:
                    tv = doc.GetElement(tid)
                    if tv is None:
                        for _fid, nm in filter_ids:
                            counters["failed"] += 1
                            records.append((nm, "(view gone)",
                                            "FAILED", "no longer in the model"))
                        continue

                    name = ff.target_label(tv)
                    template_name, locked = ff.view_filter_lock(
                        doc, tv, lock_cache)
                    if locked:
                        # the view refuses AddFilter while its template
                        # controls V/G Filters - say so rather than fail
                        skipped_ids.add(eid_value(tid))
                        for _fid, nm in filter_ids:
                            counters["skipped"] += 1
                            records.append((nm, name, "SKIPPED",
                                            "filters set by template '{0}'"
                                            .format(template_name)))
                        continue
                    existing = set()
                    try:
                        for e in tv.GetFilters():
                            existing.add(eid_value(e))
                    except Exception:
                        pass

                    for fid, fname in filter_ids:
                        try:
                            had_it = eid_value(fid) in existing
                            if had_it and new_only:
                                counters["kept"] += 1
                                records.append((fname, name, "KEPT",
                                                "already there - New Only"))
                                continue
                            if had_it:
                                action = "OVERWRITTEN"
                            else:
                                tv.AddFilter(fid)
                                action = "ADDED"

                            overrides, visible, enabled = settings_for(fid)
                            groups = groups_for(fid, fname) if groups_for else None
                            if not fo.groups_all_on(groups):
                                base = tv.GetFilterOverrides(fid) if had_it else None
                                overrides = fo.merge_overrides(overrides, base,
                                                               groups)
                            tv.SetFilterOverrides(fid, overrides)
                            if groups is None or groups.get("visible", True):
                                tv.SetFilterVisibility(fid, visible)
                            if groups is None or groups.get("enabled", True):
                                try:
                                    tv.SetIsFilterEnabled(fid, enabled)
                                except Exception:
                                    pass

                            if action == "ADDED":
                                counters["added"] += 1
                            else:
                                counters["updated"] += 1
                            records.append((fname, name, action, ""))
                        except Exception as ex:
                            counters["failed"] += 1
                            records.append((fname, name, "FAILED", str(ex)))

                    if control and tv.IsTemplate:
                        self.ensure_filters_controlled(tv)

                status = t.Commit()
            except Exception:
                try:
                    t.RollBack()
                except Exception:
                    pass
                forms.alert("Push failed and nothing was changed:\n\n{0}".format(
                    traceback.format_exc()), title="RevoBIM Filter Manager")
                return

            try:
                from Autodesk.Revit.DB import TransactionStatus
                if status != TransactionStatus.Committed:
                    forms.alert("Revit did not commit the push (status {0}). "
                                "Nothing was changed.".format(status),
                                title="RevoBIM Filter Manager")
                    return
            except Exception:
                pass

            # a void API call is not evidence - check the model
            missing = self.verify_push(target_ids, filter_ids, skipped_ids)
            self.after_push(records, counters, filter_ids, target_ids,
                            subject, source_note, specs, missing)

        self.runner.run(work)

    def verify_push(self, target_ids, filter_ids, skip=None):
        """[(filter name, target name)] that are not on the target."""
        missing = []
        for tid in target_ids:
            if skip and eid_value(tid) in skip:
                continue
            tv = doc.GetElement(tid)
            if tv is None:
                continue
            try:
                present = set(eid_value(f) for f in tv.GetFilters())
            except Exception:
                continue
            target_name = ff.target_label(tv)
            for fid, fname in filter_ids:
                if eid_value(fid) not in present:
                    missing.append((fname, target_name))
        return missing

    def after_push(self, records, counters, filters, target_ids,
                   subject, source_note, specs, missing):
        added = counters["added"]
        updated = counters["updated"]
        failed = counters["failed"]
        skipped = counters.get("skipped", 0)
        kept = counters.get("kept", 0)

        by_template = {}
        order = []
        for fname, tname, action, note in records:
            if tname not in by_template:
                by_template[tname] = []
                order.append(tname)
            by_template[tname].append((fname, action, note))

        body = []
        body.append("Source: {0}".format(source_note))
        body.append("Targets: {0}   Filters added: {1}   "
                    "Overwritten: {2}   Kept: {3}   Failed: {4}   "
                    "Skipped: {5}".format(len(target_ids), added, updated,
                                          kept, failed, skipped))
        body.append("Mode: {0}".format(
            self.OVERWRITE_LABELS.get(self.overwrite_mode, "")))
        if not specs:
            body.append("")
            body.append("SETTINGS PUSHED")
            for fid, fname in filters:
                body.append("  {0}: {1}".format(
                    fname, fo.describe_groups(self.push_groups.get(fname))))
        if specs:
            body.append("")
            body.append("GRAPHICS ASSIGNED")
            for fid, fname in filters:
                spec = specs.get(eid_value(fid))
                if spec is not None:
                    body.append("  {0}: {1}".format(fname, fo.describe(spec)))
        body.append("")
        body.append("WHAT WENT WHERE")
        for tname in order:
            body.append("")
            body.append("  {0}".format(tname))
            for fname, action, note in by_template[tname]:
                body.append("      {0}  [{1}]{2}".format(
                    fname, action, ("  " + note) if note else ""))
        if missing:
            body.append("")
            body.append("NOT ON THE TARGET AFTERWARDS")
            for fname, tname in missing:
                body.append("  {0}  ->  {1}".format(fname, tname))

        log_path = self.write_log("FilterPusher", body, subject)

        lines = []
        for tname in order:
            lines.append(tname)
            for fname, action, note in by_template[tname]:
                lines.append("     {0}   [{1}]{2}".format(
                    fname, action, ("  -  " + note) if note else ""))
            lines.append("")
        if missing:
            lines.append("NOT ON THE TARGET AFTERWARDS:")
            for fname, tname in missing:
                lines.append("     {0}  ->  {1}".format(fname, tname))

        self.reload_templates(self.host.Id if self.host is not None else None)
        self.refresh_footer()

        if missing:
            headline = "Pushed, but {0} did not stick.".format(len(missing))
        elif failed:
            headline = "Pushed, with {0} failure(s).".format(failed)
        elif (skipped or kept) and not (added or updated):
            headline = ("Nothing changed - every filter was already there."
                        if kept and not skipped else
                        "Nothing pushed - every view takes its filters "
                        "from a template.")
        else:
            headline = "Wow you just saved loads of time."

        stats = ("{0} filter(s) pushed to {1} target(s)   -   "
                 "{2} added, {3} overwritten, {4} failed".format(
                     len(filters), len(target_ids), added, updated, failed))
        if kept:
            stats += ", {0} kept (already there)".format(kept)
        if skipped:
            stats += ", {0} skipped (template-controlled)".format(skipped)

        window = DoneWindow(headline, "Filter Pusher", stats,
                            "WHAT WENT WHERE", lines, log_path)
        try:
            window.Owner = self
        except Exception:
            pass
        window.ShowDialog()

    def ensure_filters_controlled(self, tv):
        """Take V/G Filters out of the template's non-controlled list."""
        try:
            from Autodesk.Revit.DB import BuiltInParameter
            from System.Collections.Generic import List as GList
            pid = ElementId(BuiltInParameter.VIS_GRAPHICS_FILTERS)
            target = eid_value(pid)
            keep = []
            hit = False
            for e in tv.GetNonControlledTemplateParameterIds():
                if eid_value(e) == target:
                    hit = True
                else:
                    keep.append(e)
            if hit:
                lst = GList[ElementId]()
                for e in keep:
                    lst.Add(e)
                tv.SetNonControlledTemplateParameterIds(lst)
        except Exception:
            pass

    # =======================================================================
    def write_log(self, prefix, body_lines, subject):
        stamp = datetime.datetime.now()
        path = fm_core.log_path(prefix)
        rows = []
        rows.append("RevoBIM PY - Filter Manager {0}".format(VERSION))
        rows.append("Run:    {0}".format(stamp.strftime("%Y-%m-%d %H:%M:%S")))
        rows.append("Revit:  {0}".format(fm_core.revit_version()))
        rows.append("Model:  {0}".format(doc.Title))
        rows.append("Task:   {0}".format(subject))
        rows.append("=" * 96)
        rows.extend(body_lines)
        write_text(path, "\r\n".join(rows) + "\r\n")
        return path


# ===========================================================================
def launch():
    previous = fm_core.crumb_reset()
    died_at = fm_core.last_stage(previous)

    fm_core.crumb("launch: checking UI files")
    for _f in (XAML_MAIN, XAML_DONE, XAML_CREATE, XAML_OVERRIDE,
               XAML_COLOUR, XAML_RENAME):
        if not os.path.isfile(_f):
            raise IOError("Missing UI file:\n{0}".format(_f))

    # already open? bring it forward rather than opening a second copy
    fm_core.crumb("launch: checking for an open window")
    existing = fe.parked()
    if existing is not None:
        try:
            existing.Activate()
            fm_core.crumb("launch: brought the open window forward")
            return
        except Exception:
            fe.unpark()

    fm_core.crumb("launch: building the window")
    window = FilterManagerWindow()

    if not MODELESS:
        fm_core.crumb("launch: showing the window modally")
        window.ShowDialog()
        fm_core.crumb("launch: modal window closed")
        return

    fm_core.crumb("launch: owning the window to Revit")
    fe.own_to_revit(window, __revit__)

    fe.park(window)
    fm_core.crumb("launch: showing the window")
    window.Show()
    fm_core.crumb("launch: window shown")

    if died_at and "closed cleanly" not in died_at and "shown" not in died_at:
        try:
            window.txtStatus.Text = (
                "The previous run stopped at: {0}   -   see {1}".format(
                    died_at, os.path.join(fm_core.settings_folder(),
                                          fm_core.BREADCRUMB)))
        except Exception:
            pass


# ===========================================================================
#  Every handler on every window is guarded, so a Python error in one shows
#  up as a message naming the handler instead of a control that does nothing.
# ===========================================================================
ui.guard_handlers(FilterManagerWindow,
                  ["edit_override", "build_props_panel", "harvest_table",
                   "table_row", "override_button", "push_filters",
                   "push_from_host", "push_from_project"])
ui.guard_handlers(OverrideWindow, ["pick_colour", "refresh_line_preview",
                                   "refresh_fill_previews"])
ui.guard_handlers(ColourWindow, ["set_rgb", "set_hsl", "build_swatches"])
ui.guard_handlers(RenameWindow, ["refresh", "preview_row"])
ui.guard_handlers(RenameWindow, ["refresh", "preview_row"])
ui.guard_handlers(CreateWindow)
ui.guard_handlers(DoneWindow)


if __name__ == "__main__":
    try:
        launch()
    except Exception:
        forms.alert(
            "RevoBIM Filter Manager {0} could not start.\n\n"
            "Revit {1} | Python {2}\n\n{3}".format(
                VERSION, fm_core.revit_version(), sys.version.split()[0],
                traceback.format_exc()),
            title="RevoBIM Filter Manager")
