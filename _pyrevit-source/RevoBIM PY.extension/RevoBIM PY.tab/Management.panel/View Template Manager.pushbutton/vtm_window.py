# -*- coding: utf-8 -*-
"""RevoBIM PY - View Template Manager: the window.

The grid is built from the model at run time, so every column is a
DataGridTemplateColumn whose binding is the row object itself with an
IValueConverter and the column key as ConverterParameter. That sidesteps the
question of whether WPF can see Python attributes, and it is what makes a
matrix of columns that do not exist until the model is read possible at all.

Editing is an overlay: the grid is read only, a double click puts a themed
editor over the cell it hit. Typing, dropdown picks and paste all stage through
vtm_core.stage_text, so there is one rule for what a cell accepts. Nothing is
written to Revit until Apply.

State the user changes on purpose - theme, column order, which columns are
shown, column widths, window size - is remembered through vtm_settings.
"""

import os
import traceback

import vtm_clr  # noqa: F401  - assemblies first, always

from System import Action
from System.IO import File, MemoryStream, StringReader
from System.Threading import Thread
from System.Xml import XmlReader

from System.Windows import (Clipboard, DataTemplate, FrameworkElement,
                            FrameworkElementFactory, HorizontalAlignment,
                            Rect, RoutedEventHandler, Setter,
                            Style, SystemParameters, TextTrimming, Thickness,
                            VerticalAlignment, Visibility, CornerRadius)
from System.Windows.Controls import (Border, Canvas, CheckBox, ComboBox,
                                     DataGridCell, DataGridColumn,
                                     DataGridLength,
                                     DataGridTemplateColumn,
                                     ScrollChangedEventHandler,
                                     ScrollViewer, TextBlock, TextBox)
from System.Windows.Controls.Primitives import (ButtonBase,
                                                DataGridCellsPresenter,
                                                DataGridColumnHeader, Thumb)
from System.Windows.Data import Binding, IValueConverter
from System.Windows.Input import Cursors, Key, Keyboard, ModifierKeys
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Markup import XamlReader
from System.Windows.Media import VisualTreeHelper
from System.Windows.Media.Imaging import BitmapCacheOption, BitmapImage
from System.Windows.Threading import DispatcherPriority

import vtm_core as core
import vtm_drawer as drawer_mod
import vtm_settings as settings
import vtm_theme as theme

__version__ = core.__version__

work_area = drawer_mod.work_area

HERE = os.path.dirname(os.path.abspath(__file__))

GRIP = 5.0
CORNER = 10.0


# --------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------


def read_text(path):
    try:
        import io
        handle = io.open(path, "r", encoding="utf-8")
        try:
            return handle.read()
        finally:
            handle.close()
    except Exception:
        return File.ReadAllText(path)


def load_xaml(name):
    """Parse a layout or dictionary from this folder."""
    text = read_text(os.path.join(HERE, name))
    if text and text[0] == u"﻿":
        text = text[1:]
    return XamlReader.Load(XmlReader.Create(StringReader(text)))


def load_window(name, palette=None):
    """Parse a layout, merge Theme.xaml into it, then lay the palette over it.

    The theme is merged *after* parsing, which is why the layouts may only ever
    use DynamicResource - a StaticResource would fail at load and show up as a
    blank white pyRevit window.
    """
    window = load_xaml(name)
    try:
        window.Resources.MergedDictionaries.Add(load_xaml("Theme.xaml"))
    except Exception:
        pass
    theme.apply(window, palette or theme.CURRENT["name"])
    return window


def load_icon(path):
    """Icons come from bytes, never from a Uri - System.Uri moved assemblies in
    Revit 2025 and importing it kills the script at module load."""
    try:
        stream = MemoryStream(File.ReadAllBytes(path))
        image = BitmapImage()
        image.BeginInit()
        image.CacheOption = BitmapCacheOption.OnLoad
        image.StreamSource = stream
        image.EndInit()
        image.Freeze()
        return image
    except Exception:
        return None


def own_by_revit(window, uiapp):
    try:
        helper = WindowInteropHelper(window)
        helper.Owner = uiapp.MainWindowHandle
    except Exception:
        pass


def find_descendant(start, wanted_type):
    try:
        count = VisualTreeHelper.GetChildrenCount(start)
    except Exception:
        return None
    for index in range(count):
        child = VisualTreeHelper.GetChild(start, index)
        if isinstance(child, wanted_type):
            return child
        found = find_descendant(child, wanted_type)
        if found is not None:
            return found
    return None


def find_ancestor(start, wanted_type):
    node = start
    while node is not None:
        if isinstance(node, wanted_type):
            return node
        try:
            node = VisualTreeHelper.GetParent(node)
        except Exception:
            return None
    return None


def ui_safe(function):
    """Handlers fail loudly with a readable traceback rather than silently."""

    def wrapper(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Exception:
            detail = traceback.format_exc()
            try:
                args[0].report("Something went wrong", "The tool hit an error.", detail)
            except Exception:
                pass
    wrapper.__name__ = getattr(function, "__name__", "handler")
    return wrapper


def set_clipboard(text):
    """The clipboard is shared with every other program and is sometimes held
    open by one of them; try a few times before giving up."""
    for _attempt in range(6):
        try:
            Clipboard.SetText(text)
            return True
        except Exception:
            Thread.CurrentThread.Join(40)
    return False


def get_clipboard():
    for _attempt in range(6):
        try:
            if not Clipboard.ContainsText():
                return None
            return Clipboard.GetText()
        except Exception:
            Thread.CurrentThread.Join(40)
    return None


# --------------------------------------------------------------------------
# window chrome: resize grips and full screen (shrink is vtm_drawer)
# --------------------------------------------------------------------------


class Chrome(object):
    """Eight resize grips and full screen by bounds, for a borderless
    AllowsTransparency window that WPF itself cannot resize."""

    EDGES = [
        # name, horizontal, vertical, cursor
        ("left", "Left", "Stretch", "SizeWE"),
        ("right", "Right", "Stretch", "SizeWE"),
        ("top", "Stretch", "Top", "SizeNS"),
        ("bottom", "Stretch", "Bottom", "SizeNS"),
        ("topleft", "Left", "Top", "SizeNWSE"),
        ("bottomright", "Right", "Bottom", "SizeNWSE"),
        ("topright", "Right", "Top", "SizeNESW"),
        ("bottomleft", "Left", "Bottom", "SizeNESW"),
    ]

    def __init__(self, window, layer, shell):
        self.window = window
        self.shell = shell
        self.restore = None
        if layer is None:
            return
        try:
            grip_style = window.FindResource("ResizeGrip")
        except Exception:
            grip_style = None
        for name, horizontal, vertical, cursor in self.EDGES:
            grip = Thumb()
            if grip_style is not None:
                grip.Style = grip_style
            grip.HorizontalAlignment = getattr(HorizontalAlignment, horizontal)
            grip.VerticalAlignment = getattr(VerticalAlignment, vertical)
            corner = len(name) > 6
            if horizontal != "Stretch":
                grip.Width = CORNER if corner else GRIP
            if vertical != "Stretch":
                grip.Height = CORNER if corner else GRIP
            grip.Cursor = getattr(Cursors, cursor)
            grip.Tag = name
            grip.DragDelta += self.on_drag
            layer.Children.Add(grip)

    def on_drag(self, sender, args):
        try:
            self.restore = None
            self._square(False)
            name = sender.Tag
            window = self.window
            dx = args.HorizontalChange
            dy = args.VerticalChange
            if "left" in name:
                width = window.ActualWidth - dx
                if width >= window.MinWidth:
                    window.Left += dx
                    window.Width = width
            if "right" in name:
                window.Width = max(window.MinWidth, window.ActualWidth + dx)
            if "top" in name:
                height = window.ActualHeight - dy
                if height >= window.MinHeight:
                    window.Top += dy
                    window.Height = height
            if "bottom" in name:
                window.Height = max(window.MinHeight, window.ActualHeight + dy)
        except Exception:
            pass

    @property
    def full(self):
        return self.restore is not None

    def toggle(self):
        if self.full:
            self.leave()
        else:
            self.enter()

    def enter(self):
        window = self.window
        self.restore = (window.Left, window.Top, window.Width, window.Height)
        left, top, width, height = work_area(window)
        window.Left, window.Top = left, top
        window.Width, window.Height = width, height
        self._square(True)

    def leave(self):
        if self.restore is None:
            return
        left, top, width, height = self.restore
        self.restore = None
        window = self.window
        window.Left, window.Top = left, top
        window.Width, window.Height = width, height
        self._square(False)

    def forget(self):
        """Dragged by its header: no longer full screen, and no jump back."""
        if self.restore is not None:
            self.restore = None
            self._square(False)

    def _square(self, square):
        try:
            self.shell.CornerRadius = CornerRadius(0 if square else 6)
        except Exception:
            pass


# --------------------------------------------------------------------------
# converters
# --------------------------------------------------------------------------


class TextConverter(IValueConverter):
    def __init__(self, owner):
        self.owner = owner

    def Convert(self, value, target_type, parameter, culture):
        try:
            return value.display(parameter, self.owner.mode)
        except Exception:
            return ""

    def ConvertBack(self, value, target_type, parameter, culture):
        return None


class ForegroundConverter(IValueConverter):
    def __init__(self, owner):
        self.owner = owner

    def Convert(self, value, target_type, parameter, culture):
        try:
            if value.is_dirty_cell(parameter, self.owner.mode):
                return theme.brush("BrushOrange")
            if parameter == core.KEY_NAME:
                return theme.brush("BrushText")
            if parameter in (core.KEY_USED, core.KEY_DEFAULT):
                if value.unused:
                    return theme.brush("BrushRed")
                return theme.brush("BrushBlue")
            if self.owner.mode == core.MODE_CONTROLLED:
                if parameter not in value.controllable:
                    return theme.brush("BrushMuted")
                state = value.flag_edits.get(parameter)
                if state is None:
                    state = parameter in value.controlled
                return theme.brush("BrushGreen") if state else theme.brush("BrushMuted")
            cell = value.cells.get(parameter)
            if cell is None or not cell.editable:
                return theme.brush("BrushMuted")
            return theme.brush("BrushText")
        except Exception:
            return theme.brush("BrushText")

    def ConvertBack(self, value, target_type, parameter, culture):
        return None


class BackgroundConverter(IValueConverter):
    """Staged edit outranks a copy mark: an edit waiting for Apply must stay
    readable whatever else is going on."""

    def __init__(self, owner):
        self.owner = owner

    def Convert(self, value, target_type, parameter, culture):
        try:
            if value.is_dirty_cell(parameter, self.owner.mode):
                return theme.brush("BrushDirty")
            if (value.id_value, parameter) in self.owner.copy_marks:
                return theme.brush("BrushCopy")
        except Exception:
            pass
        return theme.brush("BrushTransparent")

    def ConvertBack(self, value, target_type, parameter, culture):
        return None


class ToolTipConverter(IValueConverter):
    def __init__(self, owner):
        self.owner = owner

    def Convert(self, value, target_type, parameter, culture):
        try:
            return self.owner.tooltip_for(value, parameter)
        except Exception:
            return None

    def ConvertBack(self, value, target_type, parameter, culture):
        return None


# --------------------------------------------------------------------------
# the report / confirm window
# --------------------------------------------------------------------------


class ReportWindow(object):
    def __init__(self, owner, title, message, detail, ok_text="OK",
                 cancel_text=None):
        self.window = load_window("ViewTemplateReport.xaml")
        self.result = False
        find = self.window.FindName
        find("TitleText").Text = title
        find("MessageText").Text = message
        find("DetailText").Text = detail or ""
        find("VersionText").Text = "v" + __version__
        self.ok = find("OkButton")
        self.cancel = find("CancelButton")
        self.ok.Content = ok_text
        if cancel_text is None:
            self.cancel.Visibility = Visibility.Collapsed
        else:
            self.cancel.Content = cancel_text
        self.ok.Click += self.on_ok
        self.cancel.Click += self.on_cancel
        find("CloseButton").Click += self.on_cancel
        find("HeaderBar").MouseLeftButtonDown += self.on_drag
        self.window.PreviewKeyDown += self.on_key
        try:
            self.window.Owner = owner
        except Exception:
            pass
        # after Owner, so shrinking this dialog takes the main window down too
        self.drawer = drawer_mod.Drawer(self.window, find("HeaderBar"),
                                        find("ShrinkButton"))

    def on_drag(self, sender, args):
        if self.drawer.header_down(args):
            return
        try:
            self.window.DragMove()
        except Exception:
            pass

    def on_key(self, sender, args):
        try:
            modifiers = Keyboard.Modifiers
            ctrl = (modifiers & ModifierKeys.Control) == ModifierKeys.Control
            shift = (modifiers & ModifierKeys.Shift) == ModifierKeys.Shift
            if self.drawer.handle_key(str(args.Key), ctrl, shift):
                args.Handled = True
        except Exception:
            pass

    def on_ok(self, sender, args):
        self.result = True
        self.window.Close()

    def on_cancel(self, sender, args):
        self.result = False
        self.window.Close()

    def show(self):
        self.window.ShowDialog()
        return self.result


# --------------------------------------------------------------------------
# the manager window
# --------------------------------------------------------------------------


class ManagerWindow(object):

    def __init__(self, uiapp, doc):
        self.uiapp = uiapp
        self.doc = doc
        self.mode = core.MODE_VALUES
        self.model = None
        self.rows_shown = []
        self.column_keys = {}
        self.visible = {core.MODE_VALUES: [], core.MODE_CONTROLLED: []}
        self.order = []
        self.widths = {}
        self.editing = None
        self.editor = None
        self.suspend = False
        self.sort_key = None
        self.sort_descending = False
        # Excel-style column filters, kept per mode because the two modes show
        # different values in the same column.
        self.filters = {core.MODE_VALUES: {}, core.MODE_CONTROLLED: {}}
        self.filter_key = None
        self.filter_values = []
        self.filter_state = {}
        self.copy_marks = set()
        self.highlight = set()
        self.menu_cell = None
        self.first_read = True
        self.closed = False

        # remembered settings, and the palette before anything is drawn
        self.settings = settings.load()
        self.theme_mode = theme.normalise_mode(self.settings.get("theme"))
        palette = theme.resolve(self.theme_mode, uiapp)

        self.window = load_window("ViewTemplateManager.xaml", palette)
        own_by_revit(self.window, uiapp)
        self.restore_size()

        self.text_conv = TextConverter(self)
        self.fg_conv = ForegroundConverter(self)
        self.bg_conv = BackgroundConverter(self)
        self.tip_conv = ToolTipConverter(self)
        self.header_styles = self.make_header_styles()

        find = self.window.FindName
        self.grid = find("TemplateGrid")
        self.editor_layer = find("EditorLayer")
        self.search = find("SearchBox")
        self.type_combo = find("TypeCombo")
        self.unused_toggle = find("UnusedToggle")
        self.reset_filters_button = find("ResetFiltersButton")
        self.values_toggle = find("ValuesToggle")
        self.controlled_toggle = find("ControlledToggle")
        self.columns_button = find("ColumnsButton")
        self.columns_popup = find("ColumnsPopup")
        self.column_list = find("ColumnList")
        self.column_search = find("ColumnSearch")
        self.refresh_button = find("RefreshButton")
        self.status = find("StatusText")
        self.apply_button = find("ApplyButton")
        self.revert_button = find("RevertButton")
        self.delete_selected = find("DeleteSelectedButton")
        self.delete_unused = find("DeleteUnusedButton")
        self.theme_button = find("ThemeButton")
        self.theme_label = find("ThemeLabel")
        self.cell_menu = find("CellMenu")
        self.filter_popup = find("FilterPopup")
        self.filter_column_name = find("FilterColumnName")
        self.filter_search = find("FilterSearch")
        self.filter_list = find("FilterList")
        self.filter_count = find("FilterCount")

        self.chrome = Chrome(self.window, find("GripLayer"), find("WindowShell"))
        self.drawer = drawer_mod.Drawer(self.window, find("HeaderBar"),
                                        find("ShrinkButton"),
                                        grips=find("GripLayer"),
                                        before=self.before_shrink)

        find("VersionText").Text = "v" + __version__
        icon = load_icon(os.path.join(HERE, "icon.png"))
        if icon is not None:
            find("IconImage").Source = icon
            try:
                self.window.Icon = icon
            except Exception:
                pass
        self.show_theme_state(palette)

        # header
        find("CloseButton").Click += self.on_close
        find("FullScreenButton").Click += self.on_full_screen
        self.theme_button.Click += self.on_theme
        find("HeaderBar").MouseLeftButtonDown += self.on_drag
        self.window.Activated += self.on_activated
        self.window.Closed += self.on_closed

        # tool bar
        self.search.TextChanged += self.on_filter_changed
        self.type_combo.SelectionChanged += self.on_filter_changed
        self.unused_toggle.Checked += self.on_filter_changed
        self.unused_toggle.Unchecked += self.on_filter_changed
        self.reset_filters_button.Click += self.on_reset_filters
        self.values_toggle.Checked += self.on_mode_values
        self.controlled_toggle.Checked += self.on_mode_controlled
        self.values_toggle.Unchecked += self.on_mode_guard
        self.controlled_toggle.Unchecked += self.on_mode_guard
        self.columns_button.Click += self.on_columns
        self.columns_popup.Closed += self.on_columns_closed
        self.column_search.TextChanged += self.on_column_search
        find("ColumnsAll").Click += self.on_columns_all
        find("ColumnsNone").Click += self.on_columns_none
        find("ColumnsCore").Click += self.on_columns_core
        find("ColumnsUsed").Click += self.on_columns_used
        find("ColumnsResetOrder").Click += self.on_columns_reset_order
        self.refresh_button.Click += self.on_refresh

        # footer
        self.apply_button.Click += self.on_apply
        self.revert_button.Click += self.on_revert
        self.delete_selected.Click += self.on_delete_selected
        self.delete_unused.Click += self.on_delete_unused

        # one column's sort and filter
        find("SortAscButton").Click += self.on_sort_ascending
        find("SortDescButton").Click += self.on_sort_descending
        find("SortClearButton").Click += self.on_sort_clear
        find("FilterAll").Click += self.on_filter_all
        find("FilterNone").Click += self.on_filter_none
        find("FilterClear").Click += self.on_filter_clear
        find("FilterApply").Click += self.on_filter_apply
        self.filter_search.TextChanged += self.on_filter_search

        # right-click menu on a cell
        find("MenuCopy").Click += self.on_menu_copy
        find("MenuPaste").Click += self.on_menu_paste
        find("MenuEdit").Click += self.on_menu_edit
        find("MenuRevert").Click += self.on_menu_revert
        find("MenuClearMarks").Click += self.on_menu_clear_marks

        # The menu button lives inside the column header's control template, so
        # its Click is caught on the grid as a routed event rather than being
        # declared in XAML - template-scoped handler resolution is unreliable
        # under IronPython.
        try:
            self.grid.AddHandler(ButtonBase.ClickEvent,
                                 RoutedEventHandler(self.on_header_menu))
        except Exception:
            pass

        self.grid.MouseDoubleClick += self.on_double_click
        self.grid.MouseRightButtonUp += self.on_right_click
        self.grid.SelectedCellsChanged += self.on_selection_changed
        self.grid.LoadingRow += self.on_loading_row
        self.grid.ColumnHeaderDragStarted += self.on_header_drag_started
        self.grid.ColumnHeaderDragCompleted += self.on_header_drag_completed
        self.grid.ColumnReordered += self.on_column_reordered
        try:
            self.grid.AddHandler(ScrollViewer.ScrollChangedEvent,
                                 ScrollChangedEventHandler(self.on_scrolled))
        except Exception:
            pass
        self.editor_layer.MouseLeftButtonDown += self.on_layer_click
        self.window.PreviewKeyDown += self.on_key

        self.reload()

    # ---------------------------------------------------------------- show

    def show(self):
        self.window.ShowDialog()

    def report(self, title, message, detail, ok_text="OK", cancel_text=None):
        # a dialog centred on a parked bar would open half off the screen
        self.drawer.restore_now()
        return ReportWindow(self.window, title, message, detail,
                            ok_text, cancel_text).show()

    def restore_size(self):
        width = settings.as_int(self.settings, "width", 1420)
        height = settings.as_int(self.settings, "height", 820)
        try:
            area = SystemParameters.WorkArea
            width = min(width, int(area.Width))
            height = min(height, int(area.Height))
        except Exception:
            pass
        self.window.Width = max(width, int(self.window.MinWidth))
        self.window.Height = max(height, int(self.window.MinHeight))

    # ---------------------------------------------------------------- theme

    def show_theme_state(self, palette):
        self.theme_label.Text = theme.mode_label(self.theme_mode)
        if self.theme_mode == theme.FOLLOW:
            tip = "Theme: Auto - following Revit's canvas ({0}). Click for Dark."
            tip = tip.format(palette.capitalize())
        elif self.theme_mode == theme.DARK:
            tip = "Theme: Dark. Click for Light."
        else:
            tip = "Theme: Light. Click for Auto, which follows Revit's canvas."
        self.theme_button.ToolTip = tip

    def use_palette(self, palette):
        """Swap the palette on the open window. DynamicResources re-resolve by
        themselves; the converters' brushes need the visible cells refreshed."""
        before = theme.CURRENT["name"]
        theme.apply(self.window, palette)
        self.show_theme_state(palette)
        if before != theme.CURRENT["name"]:
            self.refresh_realised()

    @ui_safe
    def on_theme(self, sender, args):
        self.theme_mode = theme.next_mode(self.theme_mode)
        self.use_palette(theme.resolve(self.theme_mode, self.uiapp))
        self.save_settings()

    @ui_safe
    def on_activated(self, sender, args):
        # Auto follows Revit: if the canvas changed while the window was in the
        # background, catch up when it comes back to the front.
        if self.theme_mode == theme.FOLLOW:
            palette = theme.resolve(self.theme_mode, self.uiapp)
            if palette != theme.CURRENT["name"]:
                self.use_palette(palette)

    # ---------------------------------------------------------------- chrome

    def before_shrink(self):
        """Nothing left open over a window that is about to slide away."""
        self.close_editor(commit=True)
        for popup in self.popups_open():
            popup.IsOpen = False
        self.chrome.leave()

    @ui_safe
    def on_drag(self, sender, args):
        if self.drawer.header_down(args):
            return
        if args.ClickCount == 2:
            self.chrome.toggle()
            return
        try:
            self.chrome.forget()
            self.window.DragMove()
        except Exception:
            pass

    @ui_safe
    def on_full_screen(self, sender, args):
        if self.drawer.busy:
            self.drawer.expand()
            return
        self.chrome.toggle()

    # ---------------------------------------------------------------- read

    def reload(self):
        self.close_editor(commit=False)
        self.copy_marks = set()
        self.model = core.read_model(self.doc)
        labels = self.column_labels()

        if self.first_read:
            # the remembered layout, mapped onto this model's columns
            mapping = settings.token_map(labels)
            saved = settings.tokens_to_keys(
                settings.decode_list(self.settings.get("column_order")), mapping)
            self.order = settings.merge_order(saved, self.model.order)
            for mode, field in ((core.MODE_VALUES, "visible_values"),
                                (core.MODE_CONTROLLED, "visible_controlled")):
                keys = settings.tokens_to_keys(
                    settings.decode_list(self.settings.get(field)), mapping)
                self.visible[mode] = keys
            self.widths = settings.decode_widths(
                self.settings.get("column_widths"), mapping)
            self.first_read = False
        else:
            self.order = settings.merge_order(self.order, self.model.order)

        for mode in (core.MODE_VALUES, core.MODE_CONTROLLED):
            for key in list(self.filters[mode].keys()):
                if key not in self.model.columns:
                    self.filters[mode].pop(key, None)
            keep = [k for k in self.visible[mode] if k in self.model.columns]
            if not [k for k in keep if k not in core.FIXED_KEYS]:
                keep = self.default_columns(mode)
            for key in core.FIXED_KEYS:
                if key not in keep:
                    keep.append(key)
            self.visible[mode] = keep

        self.fill_type_combo()
        self.build_columns()
        self.apply_filter()
        self.build_column_list()

    def column_labels(self):
        out = {}
        for key, column in self.model.columns.items():
            out[key] = column.label
        return out

    def default_columns(self, mode):
        keys = []
        for key in self.model.order:
            column = self.model.columns[key]
            if key in core.FIXED_KEYS:
                keys.append(key)
                continue
            if mode == core.MODE_VALUES:
                if column.core and column.kind != core.KIND_FLAGONLY:
                    keys.append(key)
            else:
                if column.controllable > 0:
                    keys.append(key)
        return keys

    def fill_type_combo(self):
        self.suspend = True
        try:
            keep = None
            if self.type_combo.SelectedIndex > 0:
                keep = str(self.type_combo.SelectedItem)
            self.type_combo.Items.Clear()
            self.type_combo.Items.Add("All view types")
            for name in self.model.view_types:
                self.type_combo.Items.Add(name)
            index = 0
            if keep is not None and keep in self.model.view_types:
                index = self.model.view_types.index(keep) + 1
            self.type_combo.SelectedIndex = index
        finally:
            self.suspend = False

    # ---------------------------------------------------------------- grid

    def make_header_styles(self):
        """One header style per state, each a GridHeader with a Tag the
        template's triggers act on. A column with no state has its HeaderStyle
        cleared, which puts it back on the grid's own header style."""
        styles = {}
        try:
            base = self.window.FindResource("GridHeader")
        except Exception:
            return styles
        for tag in ("f", "s", "fs"):
            try:
                style = Style(DataGridColumnHeader)
                style.BasedOn = base
                style.Setters.Add(Setter(FrameworkElement.TagProperty, tag))
                styles[tag] = style
            except Exception:
                continue
        return styles

    def remember_widths(self):
        for column in self.grid.Columns:
            key = self.column_keys.get(column)
            if key is None:
                continue
            try:
                width = column.ActualWidth
            except Exception:
                continue
            if width and width >= 30:
                self.widths[key] = int(round(width))

    def build_columns(self):
        self.close_editor(commit=False)
        if self.grid.Columns.Count:
            self.remember_widths()
        self.grid.Columns.Clear()
        self.column_keys = {}
        visible = set(self.visible[self.mode])
        for key in self.order:
            if key not in visible:
                continue
            definition = self.model.columns.get(key)
            if definition is None:
                continue
            column = DataGridTemplateColumn()
            column.Header = definition.label
            column.CellTemplate = self.make_template(key)
            column.CanUserSort = False
            column.CanUserReorder = True
            column.IsReadOnly = True
            width = self.widths.get(key)
            if width is None:
                width = definition.width
                if key not in core.FIXED_KEYS:
                    width = 120 if self.mode == core.MODE_CONTROLLED else 150
            column.Width = DataGridLength(float(width))
            column.MinWidth = 40
            self.grid.Columns.Add(column)
            self.column_keys[column] = key
        self.refreeze()

    def shown_keys(self):
        """The shown columns' keys, left to right as they are on screen."""
        columns = sorted(list(self.grid.Columns), key=lambda c: c.DisplayIndex)
        return [self.column_keys[c] for c in columns if c in self.column_keys]

    def refreeze(self):
        try:
            self.grid.FrozenColumnCount = settings.leading_frozen(self.shown_keys())
        except Exception:
            pass

    def make_template(self, key):
        border = FrameworkElementFactory(Border)
        background = Binding(".")
        background.Converter = self.bg_conv
        background.ConverterParameter = key
        border.SetBinding(Border.BackgroundProperty, background)
        border.SetValue(Border.PaddingProperty, Thickness(6, 0, 6, 0))

        text = FrameworkElementFactory(TextBlock)
        content = Binding(".")
        content.Converter = self.text_conv
        content.ConverterParameter = key
        text.SetBinding(TextBlock.TextProperty, content)
        foreground = Binding(".")
        foreground.Converter = self.fg_conv
        foreground.ConverterParameter = key
        text.SetBinding(TextBlock.ForegroundProperty, foreground)
        tip = Binding(".")
        tip.Converter = self.tip_conv
        tip.ConverterParameter = key
        text.SetBinding(TextBlock.ToolTipProperty, tip)
        text.SetValue(TextBlock.VerticalAlignmentProperty, VerticalAlignment.Center)
        text.SetValue(TextBlock.TextTrimmingProperty, TextTrimming.CharacterEllipsis)
        if key in (core.KEY_USED, core.KEY_DEFAULT) or \
                self.mode == core.MODE_CONTROLLED and key not in core.FIXED_KEYS:
            text.SetValue(TextBlock.HorizontalAlignmentProperty,
                          HorizontalAlignment.Center)
        border.AppendChild(text)

        template = DataTemplate()
        template.VisualTree = border
        template.Seal()
        return template

    def tooltip_for(self, row, key):
        if key == core.KEY_USED:
            if row.used_views == 0 and row.used_defaults == 0:
                return "Not applied to any view and not the default on any view type."
            lines = []
            if row.used_views:
                lines.append("Applied to {0} view(s):".format(row.used_views))
                lines.extend(["  " + n for n in row.used_names[:25]])
                if row.used_views > len(row.used_names):
                    lines.append("  ...")
            if row.used_defaults:
                lines.append("Default template on {0} view type(s).".format(
                    row.used_defaults))
            return "\n".join(lines)
        if key in core.FIXED_KEYS:
            return None
        definition = self.model.columns.get(key)
        if definition is None:
            return None
        lines = [definition.label]
        if definition.group:
            lines.append("Group: " + definition.group)
        if self.mode == core.MODE_CONTROLLED:
            if key not in row.controllable:
                lines.append("This template does not offer this setting.")
            else:
                lines.append("Double click to include or exclude it.")
            return "\n".join(lines)
        cell = row.cells.get(key)
        if cell is None:
            lines.append("Not a parameter of this template.")
            return "\n".join(lines)
        if key in row.edit_text:
            lines.append("Was: " + (cell.text or ""))
        if key in row.controllable and key not in row.controlled:
            lines.append("The template does not control this setting, so views "
                         "using it keep their own value.")
        if not cell.editable:
            lines.append("Read only.")
        return "\n".join(lines)

    def cells_of(self, container):
        """The realised DataGridCells of one realised row."""
        presenter = find_descendant(container, DataGridCellsPresenter)
        if presenter is None:
            return []
        out = []
        for index in range(self.grid.Columns.Count):
            try:
                cell = presenter.ItemContainerGenerator.ContainerFromIndex(index)
            except Exception:
                cell = None
            if cell is not None:
                out.append(cell)
        return out

    def refresh_realised(self):
        """Re-run the converters on every cell on screen - after a theme swap,
        a paste, or a change of copy marks. Off-screen rows run them when they
        are realised, so they need nothing."""
        generator = self.grid.ItemContainerGenerator
        for item in self.rows_shown:
            try:
                container = generator.ContainerFromItem(item)
            except Exception:
                container = None
            if container is None:
                continue
            for cell in self.cells_of(container):
                self.refresh_cell(cell)

    def refresh_cell(self, cell):
        text_block = find_descendant(cell, TextBlock)
        if text_block is None:
            return
        for prop in (TextBlock.TextProperty, TextBlock.ForegroundProperty,
                     TextBlock.ToolTipProperty):
            try:
                expression = text_block.GetBindingExpression(prop)
                if expression is not None:
                    expression.UpdateTarget()
            except Exception:
                pass
        try:
            parent = VisualTreeHelper.GetParent(text_block)
            if isinstance(parent, Border):
                expression = parent.GetBindingExpression(Border.BackgroundProperty)
                if expression is not None:
                    expression.UpdateTarget()
        except Exception:
            pass

    # ---------------------------------------------------------------- filter

    def passes_toolbar(self, row):
        """The search box, the view type box and the unused toggle."""
        if bool(self.unused_toggle.IsChecked) and not row.unused:
            return False
        if self.type_combo.SelectedIndex > 0:
            if row.view_type != str(self.type_combo.SelectedItem):
                return False
        needle = (self.search.Text or "").strip().lower()
        if needle:
            name = (row.display(core.KEY_NAME, self.mode) or "").lower()
            if needle not in name and needle not in row.view_type.lower():
                return False
        return True

    def passes_columns(self, row, skip_key=None):
        """The per-column tick-box filters. Everything ticked means no filter,
        which is why a cleared column is dropped from the dict entirely."""
        for key, allowed in self.filters[self.mode].items():
            if key == skip_key:
                continue
            if (row.display(key, self.mode) or "") not in allowed:
                return False
        return True

    def passes(self, row, skip_key=None):
        return self.passes_toolbar(row) and self.passes_columns(row, skip_key)

    def any_filter(self):
        if (self.search.Text or "").strip():
            return True
        if self.type_combo.SelectedIndex > 0:
            return True
        if bool(self.unused_toggle.IsChecked):
            return True
        return bool(self.filters[core.MODE_VALUES]) or \
            bool(self.filters[core.MODE_CONTROLLED])

    def apply_filter(self):
        shown = [r for r in self.model.rows if self.passes(r)]
        if self.sort_key is not None:
            shown.sort(key=lambda r: self.sort_value(r, self.sort_key),
                       reverse=self.sort_descending)
        self.rows_shown = shown
        self.highlight = set()
        self.grid.ItemsSource = None
        self.grid.ItemsSource = shown
        self.update_headers()
        self.update_status()

    def update_headers(self):
        """Sort and filter state on the heading: an arrow in the text for the
        sort, plus the header cell's own style - tinted while its column is
        filtering, outlined while the table is sorted on it."""
        filters = self.filters[self.mode]
        for column in self.grid.Columns:
            key = self.column_keys.get(column)
            if key is None:
                continue
            definition = self.model.columns.get(key)
            label = definition.label if definition is not None else str(key)
            tag = ""
            if key in filters:
                tag += "f"
            if self.sort_key == key:
                tag += "s"
                label += u"  ↓" if self.sort_descending else u"  ↑"
            column.Header = label
            style = self.header_styles.get(tag)
            if style is not None:
                column.HeaderStyle = style
            else:
                # A local None would outrank the grid's ColumnHeaderStyle and
                # drop the heading to the stock system header. Clear it.
                column.ClearValue(DataGridColumn.HeaderStyleProperty)

    def sort_value(self, row, key):
        if key in (core.KEY_USED, core.KEY_DEFAULT):
            return (row.used_views if key == core.KEY_USED else row.used_defaults)
        text = row.display(key, self.mode) or ""
        return text.lower()

    def pending_count(self):
        pending = 0
        for row in self.model.rows:
            pending += len(row.edits) + len(row.flag_edits)
        return pending

    def update_status(self):
        total = len(self.model.rows)
        unused = len([r for r in self.model.rows if r.unused])
        pending = self.pending_count()
        parts = ["{0} templates".format(total),
                 "{0} unused".format(unused),
                 "{0} shown".format(len(self.rows_shown))]
        filtered = len(self.filters[self.mode])
        if filtered:
            parts.append("{0} column filter(s)".format(filtered))
        if pending:
            parts.append("{0} edit(s) waiting for Apply".format(pending))
        self.status.Text = "   ·   ".join(parts)
        self.status.ToolTip = None
        self.apply_button.IsEnabled = pending > 0
        self.revert_button.IsEnabled = pending > 0
        self.delete_unused.IsEnabled = unused > 0
        self.reset_filters_button.IsEnabled = self.any_filter()

    def selected_rows(self):
        rows = []
        seen = set()
        try:
            for cell in self.grid.SelectedCells:
                row = cell.Item
                key = id(row)
                if key not in seen:
                    seen.add(key)
                    rows.append(row)
        except Exception:
            pass
        return [r for r in rows if isinstance(r, core.TemplateRow)]

    def selected_positions(self):
        """The selection as (row position, column display position) pairs."""
        index = {}
        for position, row in enumerate(self.rows_shown):
            index[id(row)] = position
        out = set()
        try:
            for info in self.grid.SelectedCells:
                r = index.get(id(info.Item))
                if r is None or info.Column is None:
                    continue
                out.add((r, info.Column.DisplayIndex))
        except Exception:
            pass
        return out

    # ---------------------------------------------------------------- events

    @ui_safe
    def on_close(self, sender, args):
        self.close_editor(commit=False)
        pending = self.pending_count()
        if pending:
            keep = self.report(
                "Close without applying",
                "{0} edit(s) have not been applied.".format(pending),
                "Closing now leaves the model exactly as it is.",
                ok_text="Close anyway", cancel_text="Go back")
            if not keep:
                return
        self.window.Close()

    @ui_safe
    def on_closed(self, sender, args):
        if self.closed:
            return
        self.closed = True
        self.save_settings()

    def popups_open(self):
        out = []
        for popup in (self.filter_popup, self.columns_popup, self.cell_menu):
            if popup is not None and popup.IsOpen:
                out.append(popup)
        return out

    @ui_safe
    def on_key(self, sender, args):
        """The keyboard belongs to whatever has focus: inside the search box,
        a filter box or the cell editor, Ctrl+C and Ctrl+V are the text box's."""
        key = args.Key
        modifiers = Keyboard.Modifiers
        ctrl = (modifiers & ModifierKeys.Control) == ModifierKeys.Control
        shift = (modifiers & ModifierKeys.Shift) == ModifierKeys.Shift

        # While parked: Escape / Enter / F11 open the window again rather than
        # reaching the exit prompt; nothing else acts on the hidden table.
        if self.drawer.handle_key(str(key), ctrl, shift):
            args.Handled = True
            return

        focus = Keyboard.FocusedElement
        in_text = isinstance(focus, TextBox) or self.editing is not None

        if key == Key.Escape:
            args.Handled = True
            popups = self.popups_open()
            if popups:
                for popup in popups:
                    popup.IsOpen = False
                return
            if self.editing is not None:
                self.close_editor(commit=False)
                return
            if self.copy_marks:
                self.clear_copy_marks()
                return
            if isinstance(focus, TextBox) and focus.Text:
                focus.Text = ""
                return
            if self.chrome.full:
                self.chrome.leave()
                return
            self.on_close(sender, args)
            return

        if key == Key.F11:
            self.chrome.toggle()
            args.Handled = True
            return

        if in_text:
            return

        if key == Key.F2:
            self.edit_current()
            args.Handled = True
        elif ctrl and key == Key.C:
            self.copy_selection()
            args.Handled = True
        elif ctrl and key == Key.V:
            self.paste_selection()
            args.Handled = True

    @ui_safe
    def on_filter_changed(self, sender, args):
        if self.suspend:
            return
        self.close_editor(commit=True)
        self.apply_filter()

    @ui_safe
    def on_reset_filters(self, sender, args):
        """Every filter off: column filters in both modes, the search box, the
        view type and Unused only. The sort is not a filter and stays."""
        self.close_editor(commit=True)
        self.filters = {core.MODE_VALUES: {}, core.MODE_CONTROLLED: {}}
        self.suspend = True
        try:
            self.search.Text = ""
            self.type_combo.SelectedIndex = 0
            self.unused_toggle.IsChecked = False
        finally:
            self.suspend = False
        self.apply_filter()

    @ui_safe
    def on_mode_guard(self, sender, args):
        # the two toggles behave as a pair; one of them is always down
        if not self.values_toggle.IsChecked and not self.controlled_toggle.IsChecked:
            self.suspend = True
            try:
                sender.IsChecked = True
            finally:
                self.suspend = False

    @ui_safe
    def on_mode_values(self, sender, args):
        if self.suspend:
            return
        self.suspend = True
        try:
            self.controlled_toggle.IsChecked = False
        finally:
            self.suspend = False
        self.set_mode(core.MODE_VALUES)

    @ui_safe
    def on_mode_controlled(self, sender, args):
        if self.suspend:
            return
        self.suspend = True
        try:
            self.values_toggle.IsChecked = False
        finally:
            self.suspend = False
        self.set_mode(core.MODE_CONTROLLED)

    def set_mode(self, mode):
        self.close_editor(commit=True)
        self.copy_marks = set()
        self.mode = mode
        self.build_columns()
        self.build_column_list()
        self.apply_filter()

    @ui_safe
    def on_refresh(self, sender, args):
        pending = self.pending_count()
        if pending:
            go = self.report("Re-read the model",
                             "{0} edit(s) have not been applied.".format(pending),
                             "Re-reading throws them away.",
                             ok_text="Re-read", cancel_text="Go back")
            if not go:
                return
        self.reload()

    @ui_safe
    def on_scrolled(self, sender, args):
        if self.editing is not None:
            self.close_editor(commit=True)

    def is_in_editor(self, source):
        node = source
        while node is not None:
            if node is self.editor:
                return True
            try:
                node = VisualTreeHelper.GetParent(node)
            except Exception:
                return False
        return False

    @ui_safe
    def on_layer_click(self, sender, args):
        if self.is_in_editor(args.OriginalSource):
            return
        self.close_editor(commit=True)

    # ---------------------------------------------------------- row highlight

    @ui_safe
    def on_selection_changed(self, sender, args):
        rows = self.selected_rows()
        self.delete_selected.IsEnabled = len(rows) > 0
        self.highlight = set([r.id_value for r in rows])
        self.paint_rows()

    def paint_rows(self):
        """Light every row holding a selected cell. Only realised rows have a
        container; the rest are painted by LoadingRow when they scroll in."""
        generator = self.grid.ItemContainerGenerator
        for item in self.rows_shown:
            try:
                container = generator.ContainerFromItem(item)
            except Exception:
                container = None
            if container is not None:
                self.tag_row(container, item)

    def tag_row(self, container, item):
        try:
            wanted = "hl" if getattr(item, "id_value", None) in self.highlight else None
            if container.Tag != wanted:
                container.Tag = wanted
        except Exception:
            pass

    @ui_safe
    def on_loading_row(self, sender, args):
        # Recycling hands an old container to a new row - the tag must follow
        # the row, not the container.
        self.tag_row(args.Row, args.Row.Item)

    # ---------------------------------------------------------- column order

    def horizontal_offset(self):
        viewer = find_descendant(self.grid, ScrollViewer)
        try:
            return viewer.HorizontalOffset if viewer is not None else 0.0
        except Exception:
            return 0.0

    @ui_safe
    def on_header_drag_started(self, sender, args):
        """A frozen column can only be dropped among the frozen ones and the
        rest only among the rest, so the freeze is lifted while a heading is
        dragged - when the table is scrolled to its left edge, where nothing
        moves as a result."""
        self.close_editor(commit=True)
        if self.horizontal_offset() < 1.0:
            try:
                self.grid.FrozenColumnCount = 0
            except Exception:
                pass

    @ui_safe
    def on_header_drag_completed(self, sender, args):
        # WPF raises DragCompleted *before* it checks whether the drop crosses
        # the frozen block, so freezing again here would refuse the very drop
        # the freeze was lifted for. Freeze once the drag has finished.
        self.window.Dispatcher.BeginInvoke(DispatcherPriority.Background,
                                           Action(self.refreeze))

    @ui_safe
    def on_column_reordered(self, sender, args):
        self.order = settings.reorder_full(self.order, self.shown_keys())
        self.refreeze()
        self.save_settings()

    @ui_safe
    def on_columns_reset_order(self, sender, args):
        self.order = list(self.model.order)
        self.widths = {}
        known = set(settings.token_map(self.column_labels()).keys())
        self.settings["column_widths"] = settings.forget_widths(
            self.settings.get("column_widths"), known)
        self.columns_popup.IsOpen = False
        self.grid.Columns.Clear()
        self.build_columns()
        self.apply_filter()
        self.save_settings()
        self.status.Text = "Column order and widths put back to the default."

    # ---------------------------------------------------------------- editing

    @ui_safe
    def on_double_click(self, sender, args):
        header = find_ancestor(args.OriginalSource, DataGridColumnHeader)
        if header is not None:
            key = self.column_keys.get(header.Column)
            if key is not None:
                self.sort_by(key)
            return
        cell = find_ancestor(args.OriginalSource, DataGridCell)
        if cell is None:
            return
        self.begin_edit(cell)

    def sort_by(self, key):
        """Double click a column header to sort on it, again to reverse."""
        if self.sort_key == key:
            self.set_sort(key, not self.sort_descending)
        else:
            self.set_sort(key, False)

    def edit_current(self):
        cell = None
        try:
            if self.grid.CurrentCell.Column is not None:
                cell = self.cell_from_info(self.grid.CurrentCell)
        except Exception:
            cell = None
        if cell is None:
            for info in self.grid.SelectedCells:
                cell = self.cell_from_info(info)
                if cell is not None:
                    break
        if cell is not None:
            self.begin_edit(cell)

    def cell_from_info(self, info):
        """The DataGridCell behind a DataGridCellInfo, or None if it is
        scrolled out of view and therefore virtualised away."""
        try:
            container = self.grid.ItemContainerGenerator.ContainerFromItem(info.Item)
            if container is None:
                return None
            presenter = find_descendant(container, DataGridCellsPresenter)
            if presenter is None:
                return None
            index = self.grid.Columns.IndexOf(info.Column)
            if index < 0:
                return None
            return presenter.ItemContainerGenerator.ContainerFromIndex(index)
        except Exception:
            return None

    def begin_edit(self, cell):
        self.close_editor(commit=True)
        key = self.column_keys.get(cell.Column)
        row = cell.DataContext
        if key is None or not isinstance(row, core.TemplateRow):
            return

        if self.mode == core.MODE_CONTROLLED:
            if key in core.FIXED_KEYS or key not in row.controllable:
                return
            state = row.flag_edits.get(key)
            if state is None:
                state = key in row.controlled
            core.stage_text(row, self.model.columns.get(key), key,
                            core.DASH if state else core.TICK, self.mode)
            self.refresh_cell(cell)
            self.update_status()
            return

        if key in (core.KEY_TYPE, core.KEY_USED, core.KEY_DEFAULT):
            return

        definition = self.model.columns.get(key)
        if key == core.KEY_NAME:
            kind = core.KIND_TEXT
        else:
            info = row.cells.get(key)
            if info is None or not info.editable:
                self.status.Text = "That cell is read only."
                return
            kind = definition.kind
        current = row.display(key, self.mode)

        editor = self.make_editor(kind, definition, current)
        if editor is None:
            return

        try:
            transform = cell.TransformToVisual(self.editor_layer)
            bounds = transform.TransformBounds(
                Rect(0, 0, cell.RenderSize.Width, cell.RenderSize.Height))
        except Exception:
            return

        editor.Width = max(bounds.Width, 120)
        editor.Height = max(bounds.Height, 22)
        Canvas.SetLeft(editor, bounds.X)
        Canvas.SetTop(editor, bounds.Y)
        self.editor_layer.Children.Clear()
        self.editor_layer.Children.Add(editor)
        self.editor_layer.Visibility = Visibility.Visible
        self.editor = editor
        self.editing = (row, key, cell)

        def focus():
            try:
                editor.Focus()
                if isinstance(editor, TextBox):
                    editor.SelectAll()
                elif isinstance(editor, ComboBox):
                    editor.IsDropDownOpen = True
            except Exception:
                pass
        self.window.Dispatcher.BeginInvoke(DispatcherPriority.Input, Action(focus))

    def make_editor(self, kind, definition, current):
        if kind in (core.KIND_TEXT, core.KIND_INT, core.KIND_DOUBLE):
            box = TextBox()
            try:
                box.Style = self.window.FindResource("FieldText")
            except Exception:
                pass
            box.Text = current if current not in (u"—", None) else ""
            box.Padding = Thickness(5, 0, 5, 0)
            box.KeyDown += self.on_editor_key
            box.LostKeyboardFocus += self.on_editor_lost
            return box
        if kind in (core.KIND_YESNO, core.KIND_CHOICE, core.KIND_ELEMENT):
            combo = ComboBox()
            try:
                combo.Style = self.window.FindResource("FieldCombo")
            except Exception:
                pass
            options = definition.options or []
            for value, label in options:
                combo.Items.Add(label)
            index = -1
            for position, pair in enumerate(options):
                if pair[1] == current:
                    index = position
                    break
            combo.SelectedIndex = index
            combo.KeyDown += self.on_editor_key
            combo.SelectionChanged += self.on_editor_picked
            return combo
        return None

    @ui_safe
    def on_editor_key(self, sender, args):
        if args.Key == Key.Enter:
            self.close_editor(commit=True)
            args.Handled = True
        elif args.Key == Key.Escape:
            self.close_editor(commit=False)
            args.Handled = True

    @ui_safe
    def on_editor_lost(self, sender, args):
        if self.editing is not None and sender is self.editor:
            self.close_editor(commit=True)

    @ui_safe
    def on_editor_picked(self, sender, args):
        if self.editing is None or sender is not self.editor:
            return
        if sender.SelectedIndex < 0:
            return
        self.close_editor(commit=True)

    def close_editor(self, commit=True):
        if self.editing is None:
            self.editor_layer.Children.Clear()
            self.editor_layer.Visibility = Visibility.Collapsed
            self.editor = None
            return
        row, key, cell = self.editing
        editor = self.editor
        self.editing = None
        self.editor = None
        try:
            if commit and editor is not None:
                self.stage_from_editor(row, key, editor)
        finally:
            self.editor_layer.Children.Clear()
            self.editor_layer.Visibility = Visibility.Collapsed
        try:
            self.refresh_cell(cell)
        except Exception:
            pass
        self.update_status()

    def stage_from_editor(self, row, key, editor):
        if isinstance(editor, TextBox):
            text = editor.Text
        elif isinstance(editor, ComboBox):
            if editor.SelectedIndex < 0:
                return
            text = u"%s" % editor.SelectedItem
        else:
            return
        result, reason = core.stage_text(row, self.model.columns.get(key), key,
                                         text, self.mode)
        if result == core.SKIPPED:
            self.update_status()
            self.status.Text = u"Not changed: {0}.".format(reason)

    # ---------------------------------------------------------- copy / paste

    def copy_value(self, row, key):
        """What a copy of one cell carries. A dash standing for 'not on this
        template' copies as blank, so it never pastes in as text."""
        if self.mode != core.MODE_CONTROLLED and key not in core.FIXED_KEYS \
                and key not in row.cells:
            return u""
        if self.mode == core.MODE_CONTROLLED and key not in core.FIXED_KEYS \
                and key not in row.controllable:
            return u""
        return row.display(key, self.mode)

    def copy_selection(self):
        positions = self.selected_positions()
        if not positions:
            self.status.Text = "Select the cells to copy first."
            return
        keys = self.shown_keys()
        rows = self.rows_shown

        def value_at(r, c):
            return self.copy_value(rows[r], keys[c])

        text = core.copy_text(positions, value_at)
        if not set_clipboard(text):
            self.status.Text = "The clipboard is in use by another program - try again."
            return
        self.copy_marks = set()
        for r, c in positions:
            self.copy_marks.add((rows[r].id_value, keys[c]))
        self.refresh_realised()
        self.status.Text = "Copied {0} cell(s). Select where it goes and press Ctrl+V.".format(
            len(positions))

    def paste_selection(self):
        positions = self.selected_positions()
        if not positions:
            self.status.Text = "Select the cells to paste into first."
            return
        text = get_clipboard()
        if text is None:
            self.status.Text = "There is no text on the clipboard to paste."
            return
        block = core.parse_clipboard(text)
        keys = self.shown_keys()
        rows = self.rows_shown
        plan = core.paste_plan(block, positions, len(rows), len(keys))

        staged = 0
        same = 0
        reasons = {}
        for r, c, value in plan:
            key = keys[c]
            result, reason = core.stage_text(rows[r], self.model.columns.get(key),
                                             key, value, self.mode)
            if result == core.STAGED:
                staged += 1
            elif result == core.SAME:
                same += 1
            else:
                reasons[reason] = reasons.get(reason, 0) + 1

        self.copy_marks = set()
        self.refresh_realised()
        self.update_status()

        skipped = sum(reasons.values())
        message = u"Pasted into {0} cell(s)".format(staged)
        if same:
            message += u", {0} already had that value".format(same)
        if skipped:
            message += u", {0} skipped".format(skipped)
            lines = []
            for reason in sorted(reasons, key=lambda k: -reasons[k]):
                lines.append(u"{0} x  {1}".format(reasons[reason], reason))
            self.status.ToolTip = u"\n".join(lines)
            message += u" - hover here for why"
        self.status.Text = message + u"."

    def clear_copy_marks(self):
        if self.copy_marks:
            self.copy_marks = set()
            self.refresh_realised()
            self.update_status()

    def revert_selection(self):
        keys = self.shown_keys()
        count = 0
        for r, c in self.selected_positions():
            row = self.rows_shown[r]
            key = keys[c]
            if self.mode == core.MODE_CONTROLLED:
                if row.flag_edits.pop(key, None) is not None:
                    count += 1
            elif key in row.edits:
                row.edits.pop(key, None)
                row.edit_text.pop(key, None)
                count += 1
        self.refresh_realised()
        self.update_status()
        self.status.Text = "{0} edit(s) in the selection reverted.".format(count)

    @ui_safe
    def on_right_click(self, sender, args):
        header = find_ancestor(args.OriginalSource, DataGridColumnHeader)
        if header is not None:
            key = self.column_keys.get(header.Column)
            if key is not None:
                args.Handled = True
                self.open_column_menu(key, header)
            return
        cell = find_ancestor(args.OriginalSource, DataGridCell)
        if cell is None:
            return
        self.close_editor(commit=True)
        if not cell.IsSelected:
            self.grid.UnselectAllCells()
            cell.IsSelected = True
        self.menu_cell = cell
        self.cell_menu.IsOpen = True
        args.Handled = True

    @ui_safe
    def on_menu_copy(self, sender, args):
        self.cell_menu.IsOpen = False
        self.copy_selection()

    @ui_safe
    def on_menu_paste(self, sender, args):
        self.cell_menu.IsOpen = False
        self.paste_selection()

    @ui_safe
    def on_menu_edit(self, sender, args):
        self.cell_menu.IsOpen = False
        if self.menu_cell is not None:
            self.begin_edit(self.menu_cell)

    @ui_safe
    def on_menu_revert(self, sender, args):
        self.cell_menu.IsOpen = False
        self.revert_selection()

    @ui_safe
    def on_menu_clear_marks(self, sender, args):
        self.cell_menu.IsOpen = False
        self.clear_copy_marks()

    # ------------------------------------------------ column sort and filter

    @ui_safe
    def on_header_menu(self, sender, args):
        # DataGridColumnHeader is itself a ButtonBase, so a click anywhere on a
        # heading raises Click too. Only the chevron opens the menu.
        if getattr(args.OriginalSource, "Name", None) != "PART_HeaderMenu":
            return
        header = find_ancestor(args.OriginalSource, DataGridColumnHeader)
        if header is None:
            return
        key = self.column_keys.get(header.Column)
        if key is None:
            return
        args.Handled = True
        self.open_column_menu(key, args.OriginalSource)

    def open_column_menu(self, key, target):
        self.close_editor(commit=True)
        self.filter_key = key
        definition = self.model.columns.get(key)
        self.filter_column_name.Text = definition.label if definition is not None \
            else str(key)

        # The values offered are the ones still standing after every *other*
        # filter, the way Excel's autofilter behaves.
        values = set()
        for row in self.model.rows:
            if self.passes(row, skip_key=key):
                values.add(row.display(key, self.mode) or "")
        self.filter_values = sorted(values, key=lambda v: v.lower())

        allowed = self.filters[self.mode].get(key)
        self.filter_state = {}
        for value in self.filter_values:
            self.filter_state[value] = True if allowed is None else value in allowed

        self.suspend = True
        try:
            self.filter_search.Text = ""
        finally:
            self.suspend = False
        self.build_filter_list()
        try:
            self.filter_popup.PlacementTarget = target
        except Exception:
            pass
        self.filter_popup.IsOpen = True

    def filter_label(self, value):
        return value if value else "(blank)"

    def build_filter_list(self):
        self.filter_list.Children.Clear()
        needle = (self.filter_search.Text or "").strip().lower()
        shown = 0
        for value in self.filter_values:
            label = self.filter_label(value)
            if needle and needle not in label.lower():
                continue
            if shown >= 400:
                break
            box = CheckBox()
            box.Content = label
            box.Margin = Thickness(2, 3, 2, 3)
            box.IsChecked = bool(self.filter_state.get(value, True))
            box.Tag = value
            box.Checked += self.on_filter_ticked
            box.Unchecked += self.on_filter_ticked
            self.filter_list.Children.Add(box)
            shown += 1
        self.show_filter_count()
        if shown >= 400:
            self.filter_count.Text += "   (first 400 shown - search to narrow)"

    def show_filter_count(self):
        ticked = len([v for v in self.filter_values if self.filter_state.get(v)])
        self.filter_count.Text = "{0} of {1} ticked".format(ticked,
                                                           len(self.filter_values))

    @ui_safe
    def on_filter_ticked(self, sender, args):
        self.filter_state[sender.Tag] = bool(sender.IsChecked)
        self.show_filter_count()

    @ui_safe
    def on_filter_search(self, sender, args):
        if self.suspend:
            return
        self.build_filter_list()

    def set_all_ticks(self, state):
        """All / None act on what the search box is currently showing, so a
        search plus None is a quick way to drop a handful of values."""
        needle = (self.filter_search.Text or "").strip().lower()
        for value in self.filter_values:
            if needle and needle not in self.filter_label(value).lower():
                continue
            self.filter_state[value] = state
        self.build_filter_list()

    @ui_safe
    def on_filter_all(self, sender, args):
        self.set_all_ticks(True)

    @ui_safe
    def on_filter_none(self, sender, args):
        self.set_all_ticks(False)

    @ui_safe
    def on_filter_clear(self, sender, args):
        if self.filter_key is not None:
            self.filters[self.mode].pop(self.filter_key, None)
        self.filter_popup.IsOpen = False
        self.apply_filter()

    @ui_safe
    def on_filter_apply(self, sender, args):
        if self.filter_key is None:
            return
        allowed = set([v for v in self.filter_values if self.filter_state.get(v)])
        if len(allowed) == len(self.filter_values):
            self.filters[self.mode].pop(self.filter_key, None)
        else:
            self.filters[self.mode][self.filter_key] = allowed
        self.filter_popup.IsOpen = False
        self.apply_filter()

    @ui_safe
    def on_sort_ascending(self, sender, args):
        self.set_sort(self.filter_key, False)

    @ui_safe
    def on_sort_descending(self, sender, args):
        self.set_sort(self.filter_key, True)

    @ui_safe
    def on_sort_clear(self, sender, args):
        self.set_sort(None, False)

    def set_sort(self, key, descending):
        self.sort_key = key
        self.sort_descending = descending
        self.filter_popup.IsOpen = False
        self.close_editor(commit=True)
        self.apply_filter()

    # ---------------------------------------------------------------- columns

    @ui_safe
    def on_columns(self, sender, args):
        self.close_editor(commit=True)
        self.columns_popup.PlacementTarget = self.columns_button
        self.columns_popup.IsOpen = True

    @ui_safe
    def on_columns_closed(self, sender, args):
        self.build_columns()
        self.apply_filter()
        self.save_settings()

    def build_column_list(self):
        self.column_list.Children.Clear()
        needle = (self.column_search.Text or "").strip().lower()
        visible = self.visible[self.mode]
        for key in self.order:
            definition = self.model.columns.get(key)
            if definition is None:
                continue
            if key in core.FIXED_KEYS:
                continue
            if self.mode == core.MODE_CONTROLLED and definition.controllable == 0:
                continue
            if self.mode == core.MODE_VALUES and definition.kind == core.KIND_FLAGONLY:
                continue
            label = definition.label or str(key)
            if needle and needle not in label.lower():
                continue
            box = CheckBox()
            box.Content = label
            box.Margin = Thickness(2, 3, 2, 3)
            box.IsChecked = key in visible
            box.Tag = key
            box.Checked += self.on_column_ticked
            box.Unchecked += self.on_column_ticked
            self.column_list.Children.Add(box)

    @ui_safe
    def on_column_search(self, sender, args):
        self.build_column_list()

    @ui_safe
    def on_column_ticked(self, sender, args):
        key = sender.Tag
        visible = self.visible[self.mode]
        if sender.IsChecked:
            if key not in visible:
                visible.append(key)
        else:
            if key in visible:
                visible.remove(key)

    def set_columns(self, keys):
        self.visible[self.mode] = list(core.FIXED_KEYS) + \
            [k for k in keys if k not in core.FIXED_KEYS]
        self.build_column_list()

    @ui_safe
    def on_columns_all(self, sender, args):
        keys = []
        for key in self.model.order:
            definition = self.model.columns[key]
            if self.mode == core.MODE_CONTROLLED and definition.controllable == 0:
                continue
            if self.mode == core.MODE_VALUES and definition.kind == core.KIND_FLAGONLY:
                continue
            keys.append(key)
        self.set_columns(keys)

    @ui_safe
    def on_columns_none(self, sender, args):
        self.set_columns([])

    @ui_safe
    def on_columns_core(self, sender, args):
        self.set_columns(self.default_columns(self.mode))

    @ui_safe
    def on_columns_used(self, sender, args):
        """Only the columns something on screen actually carries a value in."""
        keys = []
        for key in self.model.order:
            if key in core.FIXED_KEYS:
                continue
            definition = self.model.columns[key]
            if self.mode == core.MODE_CONTROLLED:
                if definition.controllable > 0:
                    keys.append(key)
                continue
            for row in self.rows_shown:
                cell = row.cells.get(key)
                if cell is not None and cell.text not in ("", u"—"):
                    keys.append(key)
                    break
        self.set_columns(keys)

    # ---------------------------------------------------------------- settings

    def save_settings(self):
        """Theme, column order, shown columns, widths and window size. Columns
        this model does not have keep their place from the last save, so
        opening a project without a shared parameter does not forget where its
        column went."""
        if self.model is None:
            return
        try:
            self.remember_widths()
        except Exception:
            pass
        labels = self.column_labels()
        known = set(settings.token_map(labels).keys())
        data = self.settings

        data["theme"] = self.theme_mode

        order = settings.keys_to_tokens(self.order, labels)
        data["column_order"] = settings.encode_list(settings.carry_unknown(
            order, settings.decode_list(data.get("column_order")), known))

        for mode, field in ((core.MODE_VALUES, "visible_values"),
                            (core.MODE_CONTROLLED, "visible_controlled")):
            shown = settings.keys_to_tokens(self.visible[mode], labels)
            data[field] = settings.encode_list(settings.carry_unknown(
                shown, settings.decode_list(data.get(field)), known))

        data["column_widths"] = settings.merge_widths(
            data.get("column_widths"), self.widths, labels)

        try:
            parked = self.drawer.true_size()
            if parked is not None:
                width, height = parked
            elif self.chrome.full:
                width, height = self.chrome.restore[2], self.chrome.restore[3]
            else:
                width, height = self.window.ActualWidth, self.window.ActualHeight
            if width and height:
                data["width"] = str(int(width))
                data["height"] = str(int(height))
        except Exception:
            pass
        settings.save(data)

    # ---------------------------------------------------------------- write

    @ui_safe
    def on_revert(self, sender, args):
        self.close_editor(commit=False)
        for row in self.model.rows:
            row.clear_edits()
        self.apply_filter()
        self.status.Text = "Edits thrown away."

    @ui_safe
    def on_apply(self, sender, args):
        self.close_editor(commit=True)
        changed, problems = core.apply_edits(self.doc, self.model)
        self.reload()
        if problems:
            self.report("Applied with notes",
                        "{0} change(s) written, {1} need a look.".format(
                            changed, len(problems)),
                        "\n".join(problems))
        self.status.Text = "{0} change(s) written to the model.".format(changed)

    @ui_safe
    def on_delete_unused(self, sender, args):
        self.close_editor(commit=True)
        rows = [r for r in self.model.rows if r.unused]
        self.confirm_delete(rows, "unused")

    @ui_safe
    def on_delete_selected(self, sender, args):
        self.close_editor(commit=True)
        rows = self.selected_rows()
        self.confirm_delete(rows, "selected")

    def confirm_delete(self, rows, what):
        if not rows:
            self.status.Text = "Nothing to delete."
            return
        lines = []
        in_use = 0
        for row in rows:
            note = ""
            if row.used_views:
                note = "   applied to {0} view(s)".format(row.used_views)
                in_use += 1
            if row.used_defaults:
                note += "   default on {0} view type(s)".format(row.used_defaults)
                if not row.used_views:
                    in_use += 1
            lines.append("{0}{1}".format(row.name, note))
        message = "Delete {0} {1} view template(s)?".format(len(rows), what)
        if in_use:
            message += "  {0} of them is in use.".format(in_use)
        detail = "\n".join(lines)
        if in_use:
            detail += ("\n\nViews using a deleted template keep the settings they "
                       "have now; they simply stop being controlled by a template.")
        if not self.report("Delete view templates", message, detail,
                           ok_text="Delete", cancel_text="Cancel"):
            return
        deleted, problems = core.delete_templates(self.doc, rows)
        self.reload()
        if problems:
            self.report("Deleted with notes",
                        "{0} deleted, {1} refused.".format(deleted, len(problems)),
                        "\n".join(problems))
        self.status.Text = "{0} view template(s) deleted.".format(deleted)
