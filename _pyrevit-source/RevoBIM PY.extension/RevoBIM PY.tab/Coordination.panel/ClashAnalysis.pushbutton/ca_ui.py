# -*- coding: utf-8 -*-
"""Clash Analysis - the window, its prompts and the ExternalEvent runner."""
import ca_clr  # noqa: F401  (assembly references first)

import datetime
import io
import os
import traceback

from System import (
    Action, AppDomain, Array, Double, EventHandler, Int32, Object, String, TimeSpan,
)
from System.Data import DataTable
from System.IO import File, FileAccess, FileMode, FileStream, MemoryStream
from System.Windows import (
    Clipboard, FontStyles, FontWeights, FrameworkElement, GridLength,
    HorizontalAlignment, TextTrimming, Thickness,
    VerticalAlignment, Visibility, WindowStartupLocation,
)
from System.Windows.Controls import (
    Button, CheckBox, ComboBoxItem, ContextMenu, DataGridLength,
    DataGridLengthUnitType, DataGridTemplateColumn, MenuItem, Separator,
    DataGridTextColumn, Dock, DockPanel, ListBoxItem, Orientation, StackPanel,
    TextBlock,
)
from System.Windows.Data import Binding
from System.Windows.Input import Cursors, Key
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Markup import XamlReader
from System.Windows.Media import ColorConverter, SolidColorBrush, VisualTreeHelper
from System.Windows.Shapes import Ellipse, Shape
from System.Windows.Media.Imaging import BitmapCacheOption, BitmapImage
from System.Windows.Threading import DispatcherTimer

from Autodesk.Revit.UI import (
    ExternalEvent, ExternalEventRequest, IExternalEventHandler,
)
import Autodesk.Revit.UI as RUI

import ca_core as core
import ca_drawer
import ca_jobs as jobs
import ca_revit as rv
from ca_version import TOOL_NAME, __version__

HERE = os.path.dirname(os.path.abspath(__file__))
APPDATA = os.path.join(os.environ.get('APPDATA', HERE), 'RevoBIM')
SETTINGS_PATH = os.path.join(APPDATA, 'clash_analysis.txt')
DEBUG_PATH = os.path.join(APPDATA, 'clash_analysis_debug.txt')
TESTS_ROOT = os.path.join(APPDATA, 'clash_analysis_tests')
WATCHDOG_SECONDS = 20
ZOOM_HALF_MM = 1500.0
LIVE_KEY = 'RevoBIM.ClashAnalysis.window.' + __version__
_KEEP = []

NAMES = (
    'OuterBorder', 'RootGrid', 'HeaderBar', 'LogoIcon', 'ToolText', 'ThemeBtn',
    'ThemeText', 'VersionText', 'ShrinkBtn', 'MaxBtn', 'CloseBtn', 'MainTabs',
    'TabTests', 'TabResults', 'TabGroups', 'TestSearch', 'TestList',
    'NewTestBtn', 'DuplicateTestBtn', 'RenameTestBtn', 'DeleteTestBtn', 'RunAllBtn', 'CountA',
    'ModelsA', 'ClearA', 'ExpandA', 'SearchA', 'TreeA', 'CountB', 'ModelsB',
    'ClearB', 'ExpandB', 'SearchB', 'TreeB', 'TestName', 'ModeCombo',
    'SaveTestBtn', 'RunTestBtn', 'RunTestLabel', 'TouchBox', 'SkipConnected',
    'RunScopeCombo', 'ScheduleBtn', 'TestsHeader', 'TestsChevron', 'TestsSummary',
    'TestsBody', 'SetsCard', 'SetsHeader', 'SetsChevron', 'SetsSummary', 'SetsBody',
    'SetsRow', 'ModelsRowA', 'ModelsRowB', 'SplitA', 'SplitB', 'IsolateBtn',
    'ResetViewBtn', 'View3DCombo', 'View3DBtn', 'StatusNotBtn', 'StatusReviewedBtn',
    'StatusOkBtn', 'ReviewSummary',
    'ResultCombo', 'TotalText', 'ResultInfo', 'AllPairsBtn', 'PairGrid',
    'ClashSearch', 'ClashGrid', 'MarkerCombo', 'WorksetCombo', 'CommentCombo',
    'PlaceBtn', 'PlaceLabel', 'ScopeCombo', 'CommentPreview', 'ShowBtn',
    'SectionBoxChk', 'RefreshGroupsBtn', 'GroupSearch', 'GroupGrid',
    'CopyReportBtn', 'ReportTitle', 'SummaryGrid', 'DetailGrid',
    'DeleteGroupBtn', 'AssignWorksetBtn', 'GroupWorksetCombo',
    'SelectGroupBtn', 'ZoomGroupBtn', 'FooterBar', 'DebugChk', 'StatusText',
    'GripLayer', 'GripL', 'GripR', 'GripT', 'GripB', 'GripTL', 'GripTR',
    'GripBL', 'GripBR',
)

PROMPT_NAMES = ('RootGrid', 'HeaderBar', 'VersionText', 'ShrinkBtn',
                'CloseBtn', 'TitleText', 'MessageText', 'InputBox',
                'ButtonPanel')

PICKER_NAMES = ('RootGrid', 'HeaderBar', 'VersionText', 'ShrinkBtn', 'CloseBtn',
                'TitleText', 'MessageText', 'OnLevelChk', 'ViewSearch', 'ViewGrid',
                'CountText', 'CancelBtn', 'CurrentBtn', 'OpenBtn')
VIEW_COLS = [('name', u'Floor plan', 's', 1.3, 160), ('lv', u'Level', 's', 0.7, 90),
             ('kind', u'Type', 's', 0.45, 70)]

SCOPES = [('all', u'All clashes in this result'),
          ('shown', u'Clashes shown in the list'),
          ('selected', u'Selected clashes only')]


# ======================================================================
# Files, log, theme
# ======================================================================

def _ensure_dir(path):
    try:
        if not os.path.isdir(path):
            os.makedirs(path)
    except Exception:
        pass


def read_text(path):
    try:
        with io.open(path, 'r', encoding='utf-8') as fh:
            return fh.read()
    except Exception:
        return u''


def write_text(path, text):
    _ensure_dir(os.path.dirname(path))
    with io.open(path, 'w', encoding='utf-8') as fh:
        fh.write(core.to_text(text))


def load_settings():
    return core.parse_settings(read_text(SETTINGS_PATH))


def save_settings(values):
    try:
        write_text(SETTINGS_PATH, core.dump_settings(values))
    except Exception:
        pass


class Log(object):
    def __init__(self, enabled):
        self.enabled = enabled

    def write(self, message):
        if not self.enabled:
            return
        try:
            _ensure_dir(APPDATA)
            stamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            with io.open(DEBUG_PATH, 'a', encoding='utf-8') as fh:
                fh.write(u'{0}  {1}\n'.format(stamp, core.to_text(message)))
        except Exception:
            pass


def load_xaml(name):
    stream = FileStream(os.path.join(HERE, name), FileMode.Open, FileAccess.Read)
    try:
        return XamlReader.Load(stream)
    finally:
        stream.Close()


def apply_palette(target, name):
    for key, hex_value in core.palette_for(name).items():
        try:
            brush = SolidColorBrush(ColorConverter.ConvertFromString(hex_value))
            brush.Freeze()
            target.Resources[key] = brush
        except Exception:
            continue


def dress(target):
    """Theme dictionary under a window's (or a menu's) own resources."""
    target.Resources.MergedDictionaries.Add(load_xaml('Theme.xaml'))


def canvas_theme():
    """Revit's canvas theme: 0 Dark, 1 Light, None when it cannot be read.
    UIThemeManager only exists from Revit 2024 - reached by getattr."""
    mgr = getattr(RUI, 'UIThemeManager', None)
    if mgr is None:
        return None
    try:
        value = mgr.CurrentCanvasTheme
    except Exception:
        return None
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return 0 if u'Dark' in core.to_text(value) else 1


def load_image(path):
    try:
        bmp = BitmapImage()
        bmp.BeginInit()
        bmp.StreamSource = MemoryStream(File.ReadAllBytes(path))
        bmp.CacheOption = BitmapCacheOption.OnLoad
        bmp.EndInit()
        bmp.Freeze()
        return bmp
    except Exception:
        return None


def own_dialog(dialog, owner, owner_drawer):
    """Every dialog takes its owner here: centred on it, unless the owner is
    parked as a bar at the bottom of the screen."""
    try:
        dialog.Owner = owner
    except Exception:
        pass
    if owner_drawer is not None and owner_drawer.parked:
        dialog.WindowStartupLocation = WindowStartupLocation.CenterScreen
    else:
        dialog.WindowStartupLocation = WindowStartupLocation.CenterOwner


def drag_header(window, args, busy_and_parked=False):
    if busy_and_parked:
        return
    try:
        window.DragMove()
    except Exception:
        pass


# ======================================================================
# Prompt - every question and report goes through this themed window
# ======================================================================

class Prompt(object):

    def __init__(self, owner, owner_drawer, theme, title, message, buttons,
                 text=None):
        self.result = None
        self.default_key = buttons[-1][1] if buttons else None
        self.owner_drawer = owner_drawer
        self.parked_owner = False
        self.window = load_xaml('Prompt.xaml')
        dress(self.window)
        apply_palette(self.window, theme)
        w = self.window
        for name in PROMPT_NAMES:
            setattr(self, name, w.FindName(name))
        self.TitleText.Text = title
        self.MessageText.Text = message
        self.VersionText.Text = u'v' + __version__
        if text is not None:
            self.InputBox.Visibility = Visibility.Visible
            self.InputBox.Text = text
            self.InputBox.KeyDown += self._on_input_key
            w.Loaded += self._on_loaded
        for label, key, style in buttons:
            btn = Button()
            btn.Content = label
            btn.MinWidth = 86
            btn.Tag = key
            btn.SetResourceReference(FrameworkElement.StyleProperty, style)
            btn.Click += self._on_button
            self.ButtonPanel.Children.Add(btn)
        self.CloseBtn.Click += self._on_close
        self.HeaderBar.MouseLeftButtonDown += self._on_drag
        self.drawer = ca_drawer.WindowDrawer(w, self.HeaderBar, self.RootGrid,
                                             self.ShrinkBtn, None,
                                             on_change=self._on_drawer)
        w.PreviewKeyDown += self._on_key
        w.Closed += self._on_closed
        own_dialog(w, owner, owner_drawer)

    def _on_button(self, sender, args):
        self.result = sender.Tag
        self.window.Close()

    def _on_loaded(self, sender, args):
        self.InputBox.Focus()
        self.InputBox.SelectAll()

    def _on_input_key(self, sender, args):
        # Enter in the text box is the last (default) button
        if args.Key == Key.Enter and not self.drawer.parked:
            args.Handled = True
            self.result = self.default_key
            self.window.Close()

    @property
    def value(self):
        return core.to_text(self.InputBox.Text)

    def _on_close(self, sender, args):
        self.window.Close()

    def _on_drag(self, sender, args):
        if args.ClickCount == 2 and self.drawer.parked:
            self.drawer.reopen()
            return
        drag_header(self.window, args)

    def _on_key(self, sender, args):
        self.drawer.handle_key(args)

    def _on_drawer(self, parked):
        # a modal prompt shrunk alone would leave its owner over Revit
        od = self.owner_drawer
        if od is None:
            return
        if parked and not od.parked:
            od.park()
            self.parked_owner = True
        elif not parked and self.parked_owner and od.parked:
            od.reopen()
            self.parked_owner = False

    def _on_closed(self, sender, args):
        od = self.owner_drawer
        if self.parked_owner and od is not None and od.parked:
            od.reopen()
            self.parked_owner = False

    def show(self):
        self.window.ShowDialog()
        return self.result


class ViewPicker(object):
    """Pick the floor plan to isolate clash spheres in. show() returns
    ('open', view_id), ('current', None) or None."""

    def __init__(self, owner, owner_drawer, theme, info):
        self.result = None
        self.info = info
        self.owner_drawer = owner_drawer
        self.parked_owner = False
        self.rows = []
        self.window = load_xaml('ViewPicker.xaml')
        dress(self.window)
        apply_palette(self.window, theme)
        w = self.window
        for name in PICKER_NAMES:
            setattr(self, name, w.FindName(name))
        self.VersionText.Text = u'v' + __version__
        level = info['level_name'] or u'(no level)'
        self.TitleText.Text = u'Isolate Clash Sphere - pick a floor plan'
        self.MessageText.Text = (
            u'The clash spheres are on level "{0}", but the active view '
            u'("{1}") is not a floor plan on that level. Pick the plan to open '
            u'and isolate them in.'.format(level, info['active_name']))
        self.OnLevelChk.Content = u'Only plans on "{0}"'.format(level)
        self.OnLevelChk.IsEnabled = info['level_key'] is not None
        if info['level_key'] is None:
            self.OnLevelChk.IsChecked = False
        self.table = make_table(VIEW_COLS)
        setup_grid(self.ViewGrid, VIEW_COLS, self.table)
        self.ViewSearch.TextChanged += lambda s, e: self.fill()
        self.OnLevelChk.Click += lambda s, e: self.fill()
        self.ViewGrid.MouseDoubleClick += self._on_open
        self.OpenBtn.Click += self._on_open
        self.CurrentBtn.Click += self._on_current
        self.CancelBtn.Click += lambda s, e: self.window.Close()
        self.CloseBtn.Click += lambda s, e: self.window.Close()
        self.HeaderBar.MouseLeftButtonDown += self._on_drag
        self.drawer = ca_drawer.WindowDrawer(w, self.HeaderBar, self.RootGrid,
                                             self.ShrinkBtn, None,
                                             on_change=self._on_drawer)
        w.PreviewKeyDown += self._on_key
        w.Closed += self._on_closed
        w.Loaded += lambda s, e: self.ViewSearch.Focus()
        own_dialog(w, owner, owner_drawer)
        self.fill()

    def fill(self):
        self.rows = core.plan_choices(self.info['views'], self.ViewSearch.Text,
                                      self.info['level_key'],
                                      bool(self.OnLevelChk.IsChecked))
        out = []
        for i, v in enumerate(self.rows):
            values = [v['name'], v['level'], v['kind']]
            out.append(values + [i, search_text(values)])
        fill_table(self.table, out)
        self.CountText.Text = u'{0} of {1} floor plans'.format(
            len(self.rows), len(self.info['views']))
        self.OpenBtn.IsEnabled = bool(self.rows)
        if self.rows:
            self.ViewGrid.SelectedIndex = 0

    def _on_open(self, sender, args):
        idx = selected_indexes(self.ViewGrid)
        if not idx or idx[0] >= len(self.rows):
            return
        self.result = ('open', self.rows[idx[0]]['id'])
        self.window.Close()

    def _on_current(self, sender, args):
        self.result = ('current', None)
        self.window.Close()

    def _on_drag(self, sender, args):
        if args.ClickCount == 2 and self.drawer.parked:
            self.drawer.reopen()
            return
        drag_header(self.window, args)

    def _on_key(self, sender, args):
        if args.Key == Key.Enter and not self.drawer.parked:
            args.Handled = True
            self._on_open(None, None)
            return
        self.drawer.handle_key(args)

    def _on_drawer(self, parked):
        od = self.owner_drawer
        if od is None:
            return
        if parked and not od.parked:
            od.park()
            self.parked_owner = True
        elif not parked and self.parked_owner and od.parked:
            od.reopen()
            self.parked_owner = False

    def _on_closed(self, sender, args):
        od = self.owner_drawer
        if self.parked_owner and od is not None and od.parked:
            od.reopen()
            self.parked_owner = False

    def show(self):
        self.window.ShowDialog()
        return self.result


# ======================================================================
# ExternalEvent runner
# ======================================================================

class Runner(IExternalEventHandler):
    """Queues work for Revit's API context. A Pending answer from Raise()
    means an earlier request is still waiting, so the job stays queued; only
    a refused job is taken back off - never the whole queue."""

    def __init__(self):
        self.jobs = []
        self.event = None
        self.log = None

    def Execute(self, uiapp):
        batch = list(self.jobs)
        del self.jobs[:]
        for fn, done in batch:
            result = None
            error = None
            try:
                result = fn(uiapp)
            except Exception:
                error = traceback.format_exc()
            try:
                done(result, error)
            except Exception:
                if self.log is not None:
                    self.log.write(u'callback failed: ' + traceback.format_exc())

    def GetName(self):
        return u'RevoBIM Clash Analysis'

    def submit(self, fn, done):
        job = (fn, done)
        self.jobs.append(job)
        try:
            status = self.event.Raise()
        except Exception:
            status = None
        if status == ExternalEventRequest.Accepted or \
                status == ExternalEventRequest.Pending:
            return True
        try:
            self.jobs.remove(job)
        except ValueError:
            pass
        if self.log is not None:
            self.log.write(u'ExternalEvent refused: {0}'.format(status))
        return False


# ======================================================================
# Table helpers - DataTable bound through DefaultView, read only
# ======================================================================

_TYPES = {'s': String, 'i': Int32, 'd': Double, 'blob': Int32}

# Review status blob: the cell is coloured from the palette by the number
# in the column (0 not reviewed, 1 reviewed, 2 OK), so it follows the theme.
BLOB_TEMPLATE = (
    u'<DataTemplate xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" '
    u'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml">'
    u'<Ellipse x:Name="Blob" Width="12" Height="12" HorizontalAlignment="Center" '
    u'VerticalAlignment="Center" Fill="{DynamicResource Red}" ToolTip="Not reviewed"/>'
    u'<DataTemplate.Triggers>'
    u'<DataTrigger Binding="{Binding KEY}" Value="1">'
    u'<Setter TargetName="Blob" Property="Fill" Value="{DynamicResource Orange}"/>'
    u'<Setter TargetName="Blob" Property="ToolTip" Value="Reviewed"/></DataTrigger>'
    u'<DataTrigger Binding="{Binding KEY}" Value="2">'
    u'<Setter TargetName="Blob" Property="Fill" Value="{DynamicResource Green}"/>'
    u'<Setter TargetName="Blob" Property="ToolTip" Value="OK"/></DataTrigger>'
    u'</DataTemplate.Triggers></DataTemplate>')


def make_table(cols):
    """cols: [(key, header, kind, weight, min_width)]"""
    table = DataTable()
    for key, header, kind, weight, minw in cols:
        table.Columns.Add(key, _TYPES[kind])
    table.Columns.Add('idx', Int32)
    table.Columns.Add('search', String)
    return table


def blob_column(key, header):
    col = DataGridTemplateColumn()
    col.Header = header
    col.CellTemplate = XamlReader.Parse(BLOB_TEMPLATE.replace(u'KEY', key))
    col.SortMemberPath = key
    return col


def setup_grid(grid, cols, table):
    grid.Columns.Clear()
    for key, header, kind, weight, minw in cols:
        if kind == 'blob':
            col = blob_column(key, header)
            col.Width = DataGridLength(weight, DataGridLengthUnitType.Star)
            col.MinWidth = minw
            grid.Columns.Add(col)
            continue
        col = DataGridTextColumn()
        col.Header = header
        col.Binding = Binding(key)
        col.SortMemberPath = key
        col.Width = DataGridLength(weight, DataGridLengthUnitType.Star)
        col.MinWidth = minw
        grid.Columns.Add(col)
    grid.ItemsSource = table.DefaultView


def fill_table(table, rows):
    """rows: list of value lists matching the columns, then idx, search."""
    table.BeginLoadData()
    table.Rows.Clear()
    for values in rows:
        table.Rows.Add(Array[Object](values))
    table.EndLoadData()


def search_text(values):
    return u' '.join(core.to_text(v) for v in values).lower()


def selected_indexes(grid):
    out = []
    try:
        for item in grid.SelectedItems:
            out.append(int(item['idx']))
    except Exception:
        pass
    return out


PAIR_COLS = [('a', u'Set A', 's', 1.0, 110), ('b', u'Set B', 's', 1.0, 110),
             ('n', u'Clashes', 'i', 0.35, 64)]
CLASH_COLS = [('no', u'#', 'i', 0.18, 40), ('a', u'Set A', 's', 1.0, 120),
              ('b', u'Set B', 's', 1.0, 120), ('am', u'A model', 's', 0.55, 80),
              ('bm', u'B model', 's', 0.55, 80),
              ('size', u'Overlap (mm)', 's', 0.5, 90),
              ('how', u'Found by', 's', 0.35, 70)]
GROUP_COLS = [('name', u'Group', 's', 1.4, 160), ('lvl', u'Level', 's', 0.3, 50),
              ('test', u'Clash test', 's', 0.8, 90),
              ('date', u'Created', 's', 0.6, 100),
              ('last', u'Last run started', 's', 0.6, 100),
              ('n', u'Clash families', 'i', 0.45, 70),
              ('ws', u'Workset', 's', 0.6, 80)]
SUMMARY_COLS = [('c', u'Comments', 's', 1.0, 200), ('n', u'Quantity', 'i', 0.22, 70)]
DETAIL_COLS = [('st', u'Review', 'blob', 0.2, 56), ('no', u'#', 'i', 0.15, 36), ('id', u'Element ID', 'i', 0.3, 80),
               ('ft', u'Family : Type', 's', 0.8, 120), ('c', u'Comments', 's', 1.2, 160),
               ('lv', u'Level', 's', 0.4, 70), ('ws', u'Workset', 's', 0.45, 70)]


# ======================================================================
# The window
# ======================================================================

class ClashWindow(object):

    def __init__(self, uiapp, runner):
        # ---- state first: nothing below may read an attribute not set here
        self.uiapp = uiapp
        self.uidoc = uiapp.ActiveUIDocument
        self.doc = self.uidoc.Document
        self.runner = runner
        self.settings = load_settings()
        self.log = Log(self.settings['debug'])
        runner.log = self.log
        self.busy = False
        self.busy_label = u''
        self.closed = False
        self.full_saved = None
        self.egg_stamps = []
        self.painting = False
        self.models = []
        self.trees = {'a': core.CatalogTree(), 'b': core.CatalogTree()}
        self.tree_checks = {'a': [], 'b': []}
        self.model_checks = {'a': [], 'b': []}
        self.tests = {}
        self.test_menu = None
        self.menu_items = {}
        self.current_name = None
        self.results = {}
        self.result_order = []
        self.shown_result = None
        self.pair_filter = None
        self.pair_rows = []
        self.shown_clashes = []
        self.markers = []
        self.worksets = []
        self.pending_ws = []
        self.sections = {}
        self.isolated_view = None
        self.reviews = {}
        self.detail_menu = None
        self.views3d = []
        self.ws_prev = {}
        self.groups = []
        self.report_rows = []
        self.report_record = None
        self.pair_table = make_table(PAIR_COLS)
        self.clash_table = make_table(CLASH_COLS)
        self.group_table = make_table(GROUP_COLS)
        self.summary_table = make_table(SUMMARY_COLS)
        self.detail_table = make_table(DETAIL_COLS)
        self.project = core.project_key(self.doc.Title, rv.central_path(self.doc))
        self.tests_dir = os.path.join(TESTS_ROOT, self.project)
        self.reviews_path = os.path.join(self.tests_dir, core.REVIEW_FILE)
        self.resolved_theme = core.resolve_theme(self.settings['theme'],
                                                 canvas_theme())
        self.watchdog = DispatcherTimer()
        self.watchdog.Interval = TimeSpan.FromSeconds(WATCHDOG_SECONDS)

        # ---- the window
        self.window = load_xaml('ClashAnalysis.xaml')
        dress(self.window)
        apply_palette(self.window, self.resolved_theme)
        for name in NAMES:
            setattr(self, name, self.window.FindName(name))
        self.drawer = ca_drawer.WindowDrawer(self.window, self.HeaderBar,
                                             self.RootGrid, self.ShrinkBtn,
                                             self.GripLayer)
        try:
            WindowInteropHelper(self.window).Owner = uiapp.MainWindowHandle
        except Exception:
            pass
        try:
            self.window.Width = max(1000.0, self.settings['win_width'])
            self.window.Height = max(620.0, self.settings['win_height'])
        except Exception:
            pass
        self.VersionText.Text = u'v' + __version__
        self.ToolText.Text = TOOL_NAME
        icon = load_image(os.path.join(HERE, 'icon.png'))
        if icon is not None:
            self.LogoIcon.Source = icon
        self.DebugChk.IsChecked = self.settings['debug']

        # ---- model reads that are safe here (the command is in API context)
        self.models = rv.list_models(self.doc)
        rv.scan_catalog(self.models[0], self.log.write)
        self.markers = rv.marker_symbols(self.doc)
        self.worksets = rv.user_worksets(self.doc)
        self.groups = rv.clash_groups(self.doc)
        self.tests = self.load_tests()

        self.wire()
        self.build_test_menu()
        self.build_detail_menu()
        self.reviews = self.load_reviews()
        self.fill_static()
        self.paint_theme_chip()
        self.fill_test_list()
        first = self.settings['last_test'] if self.settings['last_test'] in \
            self.tests else None
        if first is None and self.tests:
            first = sorted(self.tests.keys(), key=lambda s: s.lower())[0]
        if first is not None:
            self.select_test(first)
        else:
            self.load_form(core.new_test())
        self.fill_groups()
        self.log.write(u'opened v{0}, {1} model(s), {2} saved test(s)'.format(
            __version__, len(self.models), len(self.tests)))

    # ------------------------------------------------------------------
    # wiring
    # ------------------------------------------------------------------
    def wire(self):
        w = self.window
        w.PreviewKeyDown += self.on_key
        w.Closing += self.on_closing
        self.watchdog.Tick += EventHandler(self.on_watchdog)
        self.HeaderBar.MouseLeftButtonDown += self.on_header_down
        self.LogoIcon.PreviewMouseLeftButtonDown += self.on_logo
        self.ThemeBtn.Click += self.on_theme
        self.MaxBtn.Click += self.on_max
        self.CloseBtn.Click += self.on_close
        self.DebugChk.Click += self.on_debug
        for name in ('GripL', 'GripR', 'GripT', 'GripB', 'GripTL', 'GripTR',
                     'GripBL', 'GripBR'):
            grip = getattr(self, name)
            grip.Tag = name[4:]
            grip.DragDelta += self.on_grip
        # tests tab
        self.TestsHeader.MouseLeftButtonUp += lambda s, e: self.toggle_section('tests')
        self.SetsHeader.MouseLeftButtonUp += lambda s, e: self.toggle_section('sets')
        self.SplitA.DragCompleted += lambda s, e: self.on_models_split('a')
        self.SplitB.DragCompleted += lambda s, e: self.on_models_split('b')
        self.TestSearch.TextChanged += lambda s, e: self.fill_test_list()
        self.TestList.SelectionChanged += self.on_test_picked
        self.NewTestBtn.Click += self.on_new_test
        self.DuplicateTestBtn.Click += self.on_duplicate_test
        self.RenameTestBtn.Click += self.on_rename_test
        self.TestList.PreviewMouseRightButtonDown += self.on_test_right_down
        self.TestList.KeyDown += self.on_test_key
        self.DeleteTestBtn.Click += self.on_delete_test
        self.RunAllBtn.Click += self.on_run_all
        self.SaveTestBtn.Click += self.on_save_test
        self.RunTestBtn.Click += self.on_run_test
        self.SearchA.TextChanged += lambda s, e: self.draw_tree('a')
        self.SearchB.TextChanged += lambda s, e: self.draw_tree('b')
        self.ClearA.Click += lambda s, e: self.clear_tree('a')
        self.ClearB.Click += lambda s, e: self.clear_tree('b')
        self.ExpandA.Click += lambda s, e: self.expand_tree('a')
        self.ExpandB.Click += lambda s, e: self.expand_tree('b')
        # results tab
        self.ResultCombo.SelectionChanged += self.on_result_picked
        self.PairGrid.SelectionChanged += self.on_pair_picked
        self.AllPairsBtn.Click += self.on_all_pairs
        self.ClashSearch.TextChanged += self.on_clash_search
        self.ClashGrid.MouseDoubleClick += lambda s, e: self.on_show(None, None)
        self.ClashGrid.SelectionChanged += lambda s, e: self.paint_place_label()
        self.ScopeCombo.SelectionChanged += lambda s, e: self.paint_place_label()
        self.CommentCombo.SelectionChanged += lambda s, e: self.paint_place_label()
        self.ShowBtn.Click += self.on_show
        self.PlaceBtn.Click += self.on_place
        self.WorksetCombo.SelectionChanged += self.on_workset_picked
        self.GroupWorksetCombo.SelectionChanged += self.on_workset_picked
        self.ScheduleBtn.Click += self.on_schedule
        self.MarkerCombo.SelectionChanged += lambda s, e: self.paint_schedule_btn()
        # groups tab
        self.RefreshGroupsBtn.Click += lambda s, e: self.refresh_groups()
        self.GroupSearch.TextChanged += self.on_group_search
        self.GroupGrid.SelectionChanged += self.on_group_picked
        self.CopyReportBtn.Click += self.on_copy_report
        self.SelectGroupBtn.Click += self.on_select_group
        self.ZoomGroupBtn.Click += self.on_zoom_member
        self.DetailGrid.MouseDoubleClick += lambda s, e: self.on_zoom_member(None, None)
        self.AssignWorksetBtn.Click += self.on_assign_workset
        self.DeleteGroupBtn.Click += self.on_delete_group
        self.IsolateBtn.Click += self.on_isolate
        self.View3DBtn.Click += self.on_view_3d
        self.StatusNotBtn.Click += lambda s, e: self.set_review(u'not')
        self.StatusReviewedBtn.Click += lambda s, e: self.set_review(u'reviewed')
        self.StatusOkBtn.Click += lambda s, e: self.set_review(u'ok')
        self.ResetViewBtn.Click += self.on_reset_view

    def fill_static(self):
        setup_grid(self.PairGrid, PAIR_COLS, self.pair_table)
        setup_grid(self.ClashGrid, CLASH_COLS, self.clash_table)
        setup_grid(self.GroupGrid, GROUP_COLS, self.group_table)
        setup_grid(self.SummaryGrid, SUMMARY_COLS, self.summary_table)
        setup_grid(self.DetailGrid, DETAIL_COLS, self.detail_table)
        for key, label in core.DETECT_MODES:
            self.ModeCombo.Items.Add(self.combo_item(label, key))
        for key, label in core.RUN_SCOPES:
            self.RunScopeCombo.Items.Add(self.combo_item(label, key))
        self.RunScopeCombo.SelectedIndex = 0
        for key, label in core.COMMENT_FORMATS:
            self.CommentCombo.Items.Add(self.combo_item(label, key))
        self.select_tag(self.CommentCombo, self.settings['comment_format'])
        for key, label in SCOPES:
            self.ScopeCombo.Items.Add(self.combo_item(label, key))
        self.ScopeCombo.SelectedIndex = 0
        for label, sym in self.markers:
            self.MarkerCombo.Items.Add(self.combo_item(label, label))
        if not self.select_tag(self.MarkerCombo, self.settings['marker_family']):
            if self.markers:
                self.MarkerCombo.SelectedIndex = 0
        self.fill_worksets()
        self.AssignWorksetBtn.IsEnabled = bool(self.worksets)
        self.paint_schedule_btn()
        self.build_sections()
        for side in ('a', 'b'):
            box = self.ModelsA if side == 'a' else self.ModelsB
            box.HorizontalContentAlignment = HorizontalAlignment.Stretch
            box.Items.Clear()
            self.model_checks[side] = []
            for model in self.models:
                cb = CheckBox()
                cb.Content = model.label
                cb.Tag = model.key
                cb.HorizontalAlignment = HorizontalAlignment.Stretch
                cb.Click += self.on_model_tick
                box.Items.Add(cb)
                self.model_checks[side].append(cb)

    # ------------------------------------------------------------------
    # small helpers
    # ------------------------------------------------------------------
    def combo_item(self, label, tag):
        item = ComboBoxItem()
        item.Content = label
        item.Tag = tag
        return item

    def select_tag(self, combo, tag):
        for i in range(combo.Items.Count):
            if combo.Items[i].Tag == tag:
                combo.SelectedIndex = i
                return True
        return False

    def tag_of(self, combo):
        item = combo.SelectedItem
        return item.Tag if item is not None else None

    # ------------------------------------------------------------------
    # worksets: the model's, plus Z_BIM_Clash_Sphere / custom to create
    # ------------------------------------------------------------------
    def ws_item(self, kind, name, tag):
        item = ComboBoxItem()
        item.Tag = tag
        if kind == 'create':
            panel = StackPanel()
            panel.Orientation = Orientation.Horizontal
            for text in (name, u'  Create Workset?'):
                tb = TextBlock()
                tb.Text = text
                tb.FontWeight = FontWeights.Bold
                tb.SetResourceReference(TextBlock.ForegroundProperty, 'Green')
                panel.Children.Add(tb)
            item.Content = panel
            item.ToolTip = (u'Not in this model yet. Created when the command '
                            u'runs, then the clash families go on it.')
        elif kind == 'custom':
            tb = TextBlock()
            tb.Text = name
            tb.FontStyle = FontStyles.Italic
            item.Content = tb
            item.ToolTip = u'Name a new workset - it is created when the command runs'
        else:
            item.Content = name
        return item

    def fill_worksets(self, select=None):
        """Rebuild both workset lists. select: a name to pick in both."""
        names = [n for n, wid in self.worksets]
        entries = core.workset_entries(names, self.pending_ws)
        self.painting = True
        try:
            for combo in (self.WorksetCombo, self.GroupWorksetCombo):
                keep = self.tag_of(combo)
                combo.Items.Clear()
                if not self.worksets:
                    combo.Items.Add(self.combo_item(u'Model is not workshared', u''))
                    combo.SelectedIndex = 0
                    combo.IsEnabled = False
                    continue
                for kind, name, tag in entries:
                    combo.Items.Add(self.ws_item(kind, name, tag))
                want = None
                if select:
                    want = core.default_ws_tag(select, entries)
                elif keep and core.parse_ws_tag(keep)[0] != 'custom':
                    kind, name = core.parse_ws_tag(keep)
                    want = core.default_ws_tag(name, entries)
                if want is None or not self.select_tag(combo, want):
                    self.select_tag(combo, core.default_ws_tag(
                        self.settings['workset'], entries))
                self.ws_prev[combo.Name] = self.tag_of(combo)
        finally:
            self.painting = False

    def on_workset_picked(self, sender, args):
        if self.painting:
            return
        combo = sender
        kind, name = core.parse_ws_tag(self.tag_of(combo))
        if kind != 'custom':
            self.ws_prev[combo.Name] = self.tag_of(combo)
            return
        existing = [n for n, wid in self.worksets]
        typed = u''
        while True:
            key, typed = self.ask_text(
                u'Custom workset',
                u'Name of the workset to create. It is made when the command '
                u'runs, then the clash families are put on it.',
                typed, u'Use')
            if key != 'yes':
                self.painting = True
                try:
                    if not self.select_tag(combo, self.ws_prev.get(combo.Name)):
                        combo.SelectedIndex = 0
                finally:
                    self.painting = False
                return
            clean, problem, found = core.check_workset_name(typed, existing)
            if problem:
                self.tell(u'Workset name', problem)
                continue
            break
        if found is None and clean.lower() not in [p.lower() for p in self.pending_ws]:
            self.pending_ws.append(clean)
        others = [c for c in (self.WorksetCombo, self.GroupWorksetCombo) if c is not combo]
        kept = [(c, self.tag_of(c)) for c in others]
        self.fill_worksets(select=found or clean)
        for c, tag in kept:
            self.painting = True
            try:
                self.select_tag(c, tag)
                self.ws_prev[c.Name] = self.tag_of(c)
            finally:
                self.painting = False
        self.status(u'Workset "{0}" {1}'.format(
            found or clean, u'already in the model - using it' if found
            else u'will be created when the command runs'))

    def chosen_workset(self, combo):
        """(kind, name, WorksetId or None). kind: 'existing', 'create' or None."""
        kind, name = core.parse_ws_tag(self.tag_of(combo))
        if kind == 'existing':
            for n, wid in self.worksets:
                if n == name:
                    return kind, name, wid
            return None, u'', None
        if kind == 'create' and self.worksets:
            return kind, name, None
        return None, u'', None

    def after_workset_job(self, result):
        """Read the worksets again after a command that may have made one."""
        made = result.get('workset_created')
        if not made:
            return
        self.worksets = rv.user_worksets(self.doc)
        self.pending_ws = [p for p in self.pending_ws if p.lower() != made.lower()]
        kept = [(c, core.parse_ws_tag(self.tag_of(c))[1])
                for c in (self.WorksetCombo, self.GroupWorksetCombo)]
        self.fill_worksets()
        for c, name in kept:
            self.painting = True
            try:
                self.select_tag(c, core.default_ws_tag(
                    name, core.workset_entries([n for n, w in self.worksets],
                                               self.pending_ws)))
                self.ws_prev[c.Name] = self.tag_of(c)
            finally:
                self.painting = False

    def status(self, text):
        self.StatusText.Text = core.to_text(text)

    def ask(self, title, message, buttons):
        try:
            return Prompt(self.window, self.drawer, self.resolved_theme, title,
                          message, buttons).show()
        except Exception:
            self.log.write(u'prompt failed: ' + traceback.format_exc())
            return None

    def ask_text(self, title, message, text, ok_label):
        """(button key, typed text) from a prompt with a text box."""
        try:
            prompt = Prompt(self.window, self.drawer, self.resolved_theme, title,
                            message, [(u'Cancel', 'no', 'Btn'),
                                      (ok_label, 'yes', 'GreenBtn')], text=text)
            key = prompt.show()
            return key, prompt.value
        except Exception:
            self.log.write(u'prompt failed: ' + traceback.format_exc())
            return None, u''

    def tell(self, title, message):
        self.ask(title, message, [(u'OK', 'ok', 'Btn')])

    def confirm(self, title, message, yes_label, danger=False):
        style = 'RedBtn' if danger else 'GreenBtn'
        return self.ask(title, message, [(u'Cancel', 'no', 'Btn'),
                                         (yes_label, 'yes', style)]) == 'yes'

    # ------------------------------------------------------------------
    # running work in Revit's API context
    # ------------------------------------------------------------------
    def set_busy(self, flag, label=u''):
        self.busy = flag
        self.busy_label = label
        # the body and other controls go deaf; the shrink button stays live
        self.MainTabs.IsHitTestVisible = not flag
        self.ThemeBtn.IsHitTestVisible = not flag
        self.MaxBtn.IsHitTestVisible = not flag
        self.window.Cursor = Cursors.Wait if flag else None
        if flag:
            self.status(label + u' - Revit is working, please wait...')
            self.watchdog.Start()
        else:
            self.watchdog.Stop()

    def on_watchdog(self, sender, args):
        self.watchdog.Stop()
        if self.busy:
            self.log.write(u'watchdog freed the window: "{0}" never ran'.format(
                self.busy_label))
            self.set_busy(False)
            self.status(u'Revit did not pick up "{0}" - finish what Revit is '
                        u'doing (Escape any command) and try again'.format(
                            self.busy_label))

    def run(self, label, fn, done):
        if self.busy:
            self.log.write(u'click ignored while busy: ' + label)
            self.status(u'Still working on "{0}"'.format(self.busy_label))
            return
        self.set_busy(True, label)

        def finish(result, error):
            # hand back to the window's dispatcher, so Revit's Execute
            # returns before any prompt opens or the next job is raised
            try:
                self.window.Dispatcher.BeginInvoke(
                    Action(lambda: deliver(result, error)))
            except Exception:
                deliver(result, error)

        def deliver(result, error):
            self.set_busy(False)
            if error:
                self.log.write(label + u' failed:\n' + error)
                self.status(label + u' failed - details in the debug log')
                self.tell(label + u' failed', error.strip().splitlines()[-1])
                return
            try:
                done(result)
            except Exception:
                self.log.write(label + u' result: ' + traceback.format_exc())
                self.status(label + u' finished, but showing it failed')

        if not self.runner.submit(fn, finish):
            self.set_busy(False)
            self.status(u'Revit refused the request - try again')

    # ------------------------------------------------------------------
    # chrome
    # ------------------------------------------------------------------
    def on_key(self, sender, args):
        if self.drawer.handle_key(args):
            return
        if args.Key == Key.F11:
            self.toggle_full()
            args.Handled = True

    def on_header_down(self, sender, args):
        if args.ClickCount == 2:
            if self.drawer.parked:
                self.drawer.reopen()
            else:
                self.toggle_full()
            return
        if self.busy and self.drawer.parked:
            return
        if self.full_saved is not None and not self.drawer.parked:
            # dragging counts as leaving full screen
            left, top, width, height = self.full_saved
            self.full_saved = None
            self.window.Width = width
            self.window.Height = height
        drag_header(self.window, args)

    def toggle_full(self):
        if self.drawer.parked:
            self.drawer.reopen()
            return
        w = self.window
        if self.full_saved is not None:
            left, top, width, height = self.full_saved
            self.full_saved = None
            w.Left, w.Top, w.Width, w.Height = left, top, width, height
            return
        self.full_saved = (w.Left, w.Top, w.ActualWidth, w.ActualHeight)
        left, top, width, height = ca_drawer.work_area(w)
        w.Left, w.Top, w.Width, w.Height = left, top, width, height

    def on_max(self, sender, args):
        self.toggle_full()

    def on_grip(self, sender, args):
        w = self.window
        edge = sender.Tag
        dx = args.HorizontalChange
        dy = args.VerticalChange
        self.full_saved = None
        if 'R' in edge:
            w.Width = max(w.MinWidth, w.ActualWidth + dx)
        if 'B' in edge:
            w.Height = max(w.MinHeight, w.ActualHeight + dy)
        if 'L' in edge:
            new_w = w.ActualWidth - dx
            if new_w >= w.MinWidth:
                w.Left = w.Left + dx
                w.Width = new_w
        if 'T' in edge:
            new_h = w.ActualHeight - dy
            if new_h >= w.MinHeight:
                w.Top = w.Top + dy
                w.Height = new_h

    def on_logo(self, sender, args):
        args.Handled = True     # a click on the logo is not a header drag
        self.egg_stamps = (self.egg_stamps + [args.Timestamp])[-6:]
        if core.egg_ready(self.egg_stamps):
            self.egg_stamps = []
            try:
                from revobim.egg import egg_hook
                egg_hook.launch(self.window, self.resolved_theme, 'pacman')
            except Exception:
                self.log.write(u'easter egg unavailable: ' + traceback.format_exc())

    def paint_theme_chip(self):
        self.ThemeText.Text = core.theme_chip_label(self.settings['theme'],
                                                    self.resolved_theme)

    def on_theme(self, sender, args):
        self.settings['theme'] = core.next_theme(self.settings['theme'])
        self.resolved_theme = core.resolve_theme(self.settings['theme'],
                                                 canvas_theme())
        apply_palette(self.window, self.resolved_theme)
        if self.test_menu is not None:
            apply_palette(self.test_menu, self.resolved_theme)
        if self.detail_menu is not None:
            apply_palette(self.detail_menu, self.resolved_theme)
        self.paint_theme_chip()
        save_settings(self.settings)

    def on_debug(self, sender, args):
        self.settings['debug'] = bool(self.DebugChk.IsChecked)
        self.log.enabled = self.settings['debug']
        save_settings(self.settings)

    def on_close(self, sender, args):
        self.window.Close()

    def on_closing(self, sender, args):
        if self.busy:
            args.Cancel = True
            self.status(u'Wait for "{0}" to finish before closing'.format(
                self.busy_label))
            return
        self.closed = True
        try:
            if not self.drawer.parked and self.full_saved is None:
                self.settings['win_width'] = float(self.window.ActualWidth)
                self.settings['win_height'] = float(self.window.ActualHeight)
            self.settings['marker_family'] = self.tag_of(self.MarkerCombo) or u''
            if self.worksets:
                kind, name = core.parse_ws_tag(self.tag_of(self.WorksetCombo))
                if kind in ('create', 'existing'):
                    self.settings['workset'] = name
            self.settings['comment_format'] = self.tag_of(self.CommentCombo) or \
                u'family_type'
            self.settings['last_test'] = self.current_name or u''
        except Exception:
            pass
        save_settings(self.settings)
        forget()
        self.log.write(u'closed')

    def show(self):
        self.window.Show()
        self.window.Activate()

    # ------------------------------------------------------------------
    # saved tests
    # ------------------------------------------------------------------
    def load_tests(self):
        out = {}
        try:
            names = os.listdir(self.tests_dir)
        except Exception:
            names = []
        for fn in names:
            if not fn.lower().endswith('.txt'):
                continue
            test = core.parse_test(read_text(os.path.join(self.tests_dir, fn)))
            out[test['name']] = test
        return out

    def test_path(self, name):
        return os.path.join(self.tests_dir, core.safe_filename(name) + u'.txt')

    def store_test(self, test):
        write_text(self.test_path(test['name']), core.dump_test(test))
        self.tests[test['name']] = test

    def fill_test_list(self):
        term = core.to_text(self.TestSearch.Text).strip().lower()
        self.painting = True
        try:
            self.TestList.Items.Clear()
            for name in sorted(self.tests.keys(), key=lambda s: s.lower()):
                if term and term not in name.lower():
                    continue
                test = self.tests[name]
                item = ListBoxItem()
                item.Tag = name
                panel = StackPanel()
                title = TextBlock()
                title.Text = name
                title.FontWeight = FontWeights.SemiBold
                sub = TextBlock()
                sub.SetResourceReference(TextBlock.ForegroundProperty, 'Muted')
                sub.FontSize = 11
                if test['last_count'] >= 0:
                    sub.Text = u'Last run {0} - {1} clash{2}'.format(
                        test['last_run'], test['last_count'],
                        u'' if test['last_count'] == 1 else u'es')
                else:
                    sub.Text = u'Not run yet'
                if test.get('scope') == u'view':
                    sub.Text += u' - current view'
                panel.Children.Add(title)
                panel.Children.Add(sub)
                item.Content = panel
                self.TestList.Items.Add(item)
                if name == self.current_name:
                    self.TestList.SelectedItem = item
        finally:
            self.painting = False
        self.paint_section_summaries()

    def select_test(self, name):
        self.current_name = name
        self.fill_test_list()
        self.load_form(self.tests[name])

    def on_test_picked(self, sender, args):
        if self.painting:
            return
        item = self.TestList.SelectedItem
        if item is None:
            return
        self.current_name = item.Tag
        self.load_form(self.tests[item.Tag])

    def load_form(self, test):
        self.TestName.Text = test['name']
        self.select_tag(self.ModeCombo, test['mode'])
        self.select_tag(self.RunScopeCombo, test['scope'])
        self.TouchBox.Text = u'{0:g}'.format(test['touch_mm'])
        self.SkipConnected.IsChecked = bool(test['skip_connected'])
        for side in ('a', 'b'):
            chosen = set(test[side + '_models'])
            for cb in self.model_checks[side]:
                cb.IsChecked = cb.Tag in chosen
            self.trees[side] = core.CatalogTree({}, test[side + '_keys'])
        wanted = set(test['a_models']) | set(test['b_models'])
        self.ensure_catalogs(wanted, self.refresh_trees)

    def read_form(self):
        test = core.new_test(core.to_text(self.TestName.Text).strip())
        test['mode'] = self.tag_of(self.ModeCombo) or u'solid'
        test['scope'] = self.tag_of(self.RunScopeCombo) or u'view'
        try:
            test['touch_mm'] = max(0.0, float(self.TouchBox.Text))
        except Exception:
            test['touch_mm'] = core.TEST_DEFAULTS['touch_mm']
        test['skip_connected'] = bool(self.SkipConnected.IsChecked)
        for side in ('a', 'b'):
            test[side + '_models'] = self.ticked_models(side)
            test[side + '_keys'] = self.trees[side].chosen_keys()
        old = self.tests.get(self.current_name) if self.current_name else None
        if old is not None and old['name'] == test['name']:
            test['last_count'] = old['last_count']
            test['last_run'] = old['last_run']
        return test

    def check_test(self, test):
        if not test['name']:
            return u'Give the clash test a name.'
        for side, label in (('a', u'Set A'), ('b', u'Set B')):
            if not test[side + '_models']:
                return u'{0} has no model ticked.'.format(label)
            if not test[side + '_keys']:
                return u'{0} has no category or family ticked.'.format(label)
        return None

    def save_form(self):
        test = self.read_form()
        problem = self.check_test(test)
        if problem:
            self.tell(u'Clash test not saved', problem)
            return None
        old = self.current_name
        if old and old != test['name'] and old in self.tests:
            try:
                os.remove(self.test_path(old))
            except Exception:
                pass
            self.tests.pop(old, None)
        self.store_test(test)
        self.current_name = test['name']
        self.fill_test_list()
        return test

    def on_save_test(self, sender, args):
        if self.save_form() is not None:
            self.status(u'Saved clash test "{0}"'.format(self.current_name))

    def on_new_test(self, sender, args):
        self.current_name = None
        name = core.unique_name(u'New clash test', self.tests.keys())
        self.TestList.SelectedItem = None
        self.load_form(core.new_test(name))

    def on_duplicate_test(self, sender, args):
        if not self.current_name:
            self.status(u'Pick a saved test to duplicate')
            return
        test = self.read_form()
        test['name'] = core.unique_name(test['name'] + u' copy', self.tests.keys())
        test['last_count'] = -1
        test['last_run'] = u''
        self.store_test(test)
        self.select_test(test['name'])

    # ---- right-click menu and rename ----
    def build_test_menu(self):
        menu = ContextMenu()
        dress(menu)
        apply_palette(menu, self.resolved_theme)
        for key, label, gesture, handler in (
                ('rename', u'Rename...', u'F2', self.on_rename_test),
                ('duplicate', u'Duplicate', u'', self.on_duplicate_test),
                ('run', u'Run this test', u'', self.on_run_from_menu),
                ('-', None, None, None),
                ('delete', u'Delete', u'Del', self.on_delete_test)):
            if key == '-':
                sep = Separator()
                sep.SetResourceReference(FrameworkElement.StyleProperty, 'MenuSep')
                menu.Items.Add(sep)
                continue
            item = MenuItem()
            item.Header = label
            item.InputGestureText = gesture
            item.Click += handler
            menu.Items.Add(item)
            self.menu_items[key] = item
        menu.Opened += self.on_test_menu_opened
        self.TestList.ContextMenu = menu
        self.test_menu = menu

    def on_test_menu_opened(self, sender, args):
        picked = bool(self.current_name) and self.current_name in self.tests
        for item in self.menu_items.values():
            item.IsEnabled = picked and not self.busy

    def on_test_right_down(self, sender, args):
        """Right-click selects the test under the pointer first, so the menu
        acts on the test that was clicked, not the one picked before."""
        node = args.OriginalSource
        while node is not None and not isinstance(node, ListBoxItem):
            try:
                node = VisualTreeHelper.GetParent(node)
            except Exception:
                node = None
        if node is not None:
            node.IsSelected = True

    def on_test_key(self, sender, args):
        if args.Key == Key.F2:
            args.Handled = True
            self.on_rename_test(None, None)
        elif args.Key == Key.Delete:
            args.Handled = True
            self.on_delete_test(None, None)

    def on_run_from_menu(self, sender, args):
        self.on_run_test(None, None)

    def on_rename_test(self, sender, args):
        old = self.current_name
        if not old or old not in self.tests:
            self.status(u'Pick a saved test to rename')
            return
        key, typed = self.ask_text(
            u'Rename clash test',
            u'New name for "{0}".\n\nCLASH- groups already placed keep the '
            u'name they were given.'.format(old), old, u'Rename')
        if key != 'yes':
            return
        new, problem = core.check_test_name(typed, old, self.tests.keys())
        if problem:
            self.tell(u'Clash test not renamed', problem)
            return
        if new == old:
            return
        self.rename_test(old, new)

    def rename_test(self, old, new):
        test = dict(self.tests[old])
        test['name'] = new
        old_path = self.test_path(old)
        try:
            # write the new file first, so a failure cannot lose the test
            write_text(self.test_path(new), core.dump_test(test))
        except Exception:
            self.log.write(u'rename failed: ' + traceback.format_exc())
            self.tell(u'Clash test not renamed',
                      u'The new file could not be written - the test is unchanged.')
            return
        if os.path.normcase(old_path) != os.path.normcase(self.test_path(new)):
            try:
                os.remove(old_path)
            except Exception:
                self.log.write(u'old test file left behind: ' + old_path)
        del self.tests[old]
        self.tests[new] = test
        if old in self.results:
            self.results[new] = self.results.pop(old)
            self.result_order = core.rename_in_order(self.result_order, old, new)
            if self.shown_result == old:
                self.shown_result = new
            self.painting = True
            try:
                self.ResultCombo.Items.Clear()
                for n in self.result_order:
                    self.ResultCombo.Items.Add(self.combo_item(n, n))
                if self.shown_result:
                    self.select_tag(self.ResultCombo, self.shown_result)
            finally:
                self.painting = False
        self.current_name = new
        self.TestName.Text = new
        self.settings['last_test'] = new
        save_settings(self.settings)
        self.fill_test_list()
        self.log.write(u'renamed test "{0}" -> "{1}"'.format(old, new))
        self.status(u'Renamed "{0}" to "{1}"'.format(old, new))

    def on_delete_test(self, sender, args):
        name = self.current_name
        if not name:
            self.status(u'Pick a saved test to delete')
            return
        if not self.confirm(u'Delete clash test',
                            u'Delete the saved clash test "{0}"?\n\nGroups it '
                            u'already placed in the model are kept.'.format(name),
                            u'Delete', danger=True):
            return
        try:
            os.remove(self.test_path(name))
        except Exception:
            pass
        self.tests.pop(name, None)
        self.current_name = None
        self.fill_test_list()
        self.load_form(core.new_test(core.unique_name(u'New clash test',
                                                      self.tests.keys())))
        self.status(u'Deleted clash test "{0}"'.format(name))

    # ------------------------------------------------------------------
    # models and the category / family trees
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # collapsible sections and the Models list height
    # ------------------------------------------------------------------
    def build_sections(self):
        try:
            self.sections['tests'] = ca_drawer.SectionDrawer(
                self.TestsBody, self.TestsChevron, None,
                self.settings['tests_open'],
                lambda is_open: self.section_changed('tests', is_open))
            self.sections['sets'] = ca_drawer.SectionDrawer(
                self.SetsBody, self.SetsChevron, self.SetsRow,
                self.settings['sets_open'],
                lambda is_open: self.section_changed('sets', is_open))
        except Exception:
            self.log.write(u'sections: ' + traceback.format_exc())
        h = self.settings['models_height'] or core.models_list_height()
        for row in (self.ModelsRowA, self.ModelsRowB):
            row.Height = GridLength(h)

    def toggle_section(self, key):
        section = self.sections.get(key)
        if section is not None:
            section.toggle()

    def section_changed(self, key, is_open):
        self.settings[key + '_open'] = bool(is_open)

    def on_models_split(self, side):
        """Dragging one Models list sizes both, and is remembered."""
        mine, other = ((self.ModelsRowA, self.ModelsRowB) if side == 'a'
                       else (self.ModelsRowB, self.ModelsRowA))
        h = float(mine.ActualHeight)
        if h > 0:
            other.Height = GridLength(h)
            self.settings['models_height'] = h

    def paint_section_summaries(self):
        n = len(self.tests)
        text = u'{0} saved'.format(n)
        if self.current_name:
            text += u' - "{0}"'.format(self.current_name)
        self.TestsSummary.Text = text
        self.SetsSummary.Text = u'A: {0}   B: {1}'.format(self.CountA.Text,
                                                        self.CountB.Text)

    def ticked_models(self, side):
        return [cb.Tag for cb in self.model_checks[side] if cb.IsChecked]

    def ensure_catalogs(self, keys, then):
        missing = [m for m in self.models if m.key in keys and m.catalog is None]
        if not missing:
            then()
            return

        def job(uiapp):
            for model in missing:
                rv.scan_catalog(model, self.log.write)
            return len(missing)

        self.run(u'Reading linked models', job, lambda result: then())

    def on_model_tick(self, sender, args):
        if self.busy:
            # the categories could not be read now - undo the tick, not leave
            # a ticked model with nothing listed
            sender.IsChecked = not sender.IsChecked
            self.status(u'Still working on "{0}" - tick the model again in a moment'.format(
                self.busy_label))
            return
        self.ensure_catalogs(set(self.ticked_models('a')) |
                             set(self.ticked_models('b')), self.refresh_trees)

    def refresh_trees(self):
        for side in ('a', 'b'):
            keys = set(self.ticked_models(side))
            cats = [m.catalog for m in self.models
                    if m.key in keys and m.catalog is not None]
            tree = self.trees[side]
            tree.set_catalog(core.merge_catalogs(cats), tree.ticked)
            self.draw_tree(side)

    def draw_tree(self, side):
        tree = self.trees[side]
        box = self.TreeA if side == 'a' else self.TreeB
        search = self.SearchA if side == 'a' else self.SearchB
        rows = tree.rows(search.Text)
        self.painting = True
        try:
            box.Items.Clear()
            checks = []
            for row in rows:
                item = ListBoxItem()
                panel = DockPanel()
                count = TextBlock()
                count.Text = u'{0:,}'.format(row['count'])
                count.SetResourceReference(TextBlock.ForegroundProperty, 'Muted')
                count.FontSize = 11
                count.VerticalAlignment = VerticalAlignment.Center
                DockPanel.SetDock(count, Dock.Right)
                panel.Children.Add(count)
                if row['kind'] == 'cat':
                    arrow = Button()
                    arrow.Content = u'▾' if row['open'] else u'▸'
                    arrow.SetResourceReference(FrameworkElement.StyleProperty,
                                               'ChromeBtn')
                    arrow.Width = 20
                    arrow.Height = 20
                    arrow.Tag = row['cat']
                    arrow.Click += self.on_arrow_a if side == 'a' else self.on_arrow_b
                    DockPanel.SetDock(arrow, Dock.Left)
                    panel.Children.Add(arrow)
                else:
                    panel.Margin = Thickness(26, 0, 0, 0)
                cb = CheckBox()
                cb.IsThreeState = row['kind'] == 'cat'
                cb.IsChecked = row['state']
                label = TextBlock()
                label.Text = row['label']
                label.TextTrimming = TextTrimming.CharacterEllipsis
                if row['kind'] == 'cat':
                    label.FontWeight = FontWeights.SemiBold
                cb.Content = label
                cb.Tag = (row['kind'], row['cat'], row['fam'])
                cb.Click += self.on_tree_tick_a if side == 'a' else self.on_tree_tick_b
                panel.Children.Add(cb)
                item.Content = panel
                box.Items.Add(item)
                checks.append(cb)
            self.tree_checks[side] = checks
        finally:
            self.painting = False
        self.paint_counts(side)

    def paint_tree_states(self, side):
        tree = self.trees[side]
        self.painting = True
        try:
            for cb in self.tree_checks[side]:
                kind, cat, fam = cb.Tag
                if kind == 'cat':
                    cb.IsChecked = tree.cat_state(cat)
                else:
                    cb.IsChecked = core.cf_key(cat, fam) in tree.ticked
        finally:
            self.painting = False
        self.paint_counts(side)

    def paint_counts(self, side):
        n, cats = self.trees[side].summary()
        label = self.CountA if side == 'a' else self.CountB
        label.Text = u'{0} famil{1} in {2} categor{3}'.format(
            n, u'y' if n == 1 else u'ies', cats, u'y' if cats == 1 else u'ies')
        self.paint_section_summaries()

    def tree_tick(self, side, cb):
        if self.painting:
            return
        kind, cat, fam = cb.Tag
        if kind == 'cat':
            self.trees[side].toggle_category(cat)
        else:
            self.trees[side].toggle_family(cat, fam)
        self.paint_tree_states(side)

    def on_tree_tick_a(self, sender, args):
        self.tree_tick('a', sender)

    def on_tree_tick_b(self, sender, args):
        self.tree_tick('b', sender)

    def on_arrow_a(self, sender, args):
        self.trees['a'].toggle_collapse(sender.Tag)
        self.draw_tree('a')

    def on_arrow_b(self, sender, args):
        self.trees['b'].toggle_collapse(sender.Tag)
        self.draw_tree('b')

    def clear_tree(self, side):
        self.trees[side].clear()
        self.paint_tree_states(side)

    def expand_tree(self, side):
        tree = self.trees[side]
        tree.set_all_collapsed(len(tree.collapsed) < len(tree.catalog))
        self.draw_tree(side)

    # ------------------------------------------------------------------
    # running tests
    # ------------------------------------------------------------------
    def stamp_now(self):
        return datetime.datetime.now().strftime('%d/%m/%Y %H:%M')

    def on_run_test(self, sender, args):
        test = self.save_form()
        if test is None:
            return
        models = self.models
        log = self.log.write

        def job(uiapp):
            started = self.stamp_now()
            result = rv.run_test(models, test, log, rv.run_scope(uiapp, test))
            result['started'] = started
            return result

        def done(result):
            self.record_result(test, result)
            self.show_result(test['name'])
            self.MainTabs.SelectedItem = self.TabResults

        self.run(u'Running "{0}"'.format(test['name']), job, done)

    def on_run_all(self, sender, args):
        names = sorted(self.tests.keys(), key=lambda s: s.lower())
        if not names:
            self.status(u'No saved clash tests to run')
            return
        tests = [self.tests[n] for n in names]
        models = self.models
        log = self.log.write

        def job(uiapp):
            out = []
            for test in tests:
                try:
                    started = self.stamp_now()
                    result = rv.run_test(models, test, log, rv.run_scope(uiapp, test))
                    result['started'] = started
                    out.append((test, result, None))
                except Exception as ex:
                    out.append((test, None, core.to_text(ex)))
            return out

        def done(results):
            lines = []
            for test, result, error in results:
                if error:
                    lines.append(u'{0}: failed - {1}'.format(test['name'], error))
                    continue
                self.record_result(test, result)
                lines.append(u'{0}: {1} clashes'.format(test['name'],
                                                        len(result['clashes'])))
            if self.result_order:
                self.show_result(self.result_order[-1])
            self.tell(u'All clash tests run', u'\n'.join(lines))

        self.run(u'Running {0} clash tests'.format(len(tests)), job, done)

    def record_result(self, test, result):
        # the time the run started, not when it came back
        result['run_at'] = result.get('started') or self.stamp_now()
        name = test['name']
        self.results[name] = result
        if name in self.result_order:
            self.result_order.remove(name)
        self.result_order.append(name)
        stored = self.tests.get(name, test)
        stored['last_count'] = len(result['clashes'])
        stored['last_run'] = result['run_at']
        try:
            self.store_test(stored)
        except Exception:
            self.log.write(u'could not save last run: ' + traceback.format_exc())
        self.fill_test_list()
        self.painting = True
        try:
            self.ResultCombo.Items.Clear()
            for n in self.result_order:
                self.ResultCombo.Items.Add(self.combo_item(n, n))
        finally:
            self.painting = False
        self.status(u'"{0}": {1} clashes'.format(name, len(result['clashes'])))

    # ------------------------------------------------------------------
    # results
    # ------------------------------------------------------------------
    def on_result_picked(self, sender, args):
        if self.painting:
            return
        name = self.tag_of(self.ResultCombo)
        if name:
            self.show_result(name)

    def show_result(self, name):
        result = self.results.get(name)
        if result is None:
            return
        self.shown_result = name
        self.pair_filter = None
        self.painting = True
        try:
            self.select_tag(self.ResultCombo, name)
        finally:
            self.painting = False
        clashes = result['clashes']
        n = len(clashes)
        self.TotalText.Text = u'{0} clash{1}'.format(n, u'' if n == 1 else u'es')
        info = u'Set A {0:,} elements - Set B {1:,} - {2:,} pairs checked - started {3}'.format(
            result['a_count'], result['b_count'], result['candidates'],
            result['run_at'])
        if result.get('scope'):
            info += u' - view "{0}"'.format(result['scope'])
            if result.get('view_level') is not None:
                info += u' (clash families go on level "{0}")'.format(
                    rv.level_name(self.doc, result['view_level']))
        if result.get('approx'):
            info += u' - {0} found by bounding box (Revit could not intersect the solids)'.format(
                result['approx'])
        self.ResultInfo.Text = info
        rows = []
        for i, (la, lb, count) in enumerate(core.summarise(clashes)):
            rows.append([la, lb, count, i, search_text([la, lb])])
        self.pair_rows = core.summarise(clashes)
        fill_table(self.pair_table, rows)
        self.fill_clashes()

    def fill_clashes(self):
        result = self.results.get(self.shown_result)
        clashes = result['clashes'] if result else []
        self.shown_clashes = []
        rows = []
        for i, c in enumerate(clashes):
            la = core.side_label(c['a'])
            lb = core.side_label(c['b'])
            if self.pair_filter is not None and (la, lb) != self.pair_filter:
                continue
            size = u' x '.join(u'{0:.0f}'.format(core.ft_to_mm(v)) for v in c['size'])
            how = u'Box' if c['approx'] else u'Solid'
            values = [i + 1, la, lb, c['a']['model'], c['b']['model'], size, how]
            rows.append(values + [i, search_text(values)])
            self.shown_clashes.append(i)
        fill_table(self.clash_table, rows)
        self.clash_table.DefaultView.RowFilter = core.row_filter(self.ClashSearch.Text)
        self.paint_place_label()

    def on_pair_picked(self, sender, args):
        if self.painting:
            return
        idx = selected_indexes(self.PairGrid)
        if not idx:
            return
        la, lb, count = self.pair_rows[idx[0]]
        self.pair_filter = (la, lb)
        self.fill_clashes()

    def on_all_pairs(self, sender, args):
        self.pair_filter = None
        self.PairGrid.UnselectAll()
        self.fill_clashes()

    def on_clash_search(self, sender, args):
        self.clash_table.DefaultView.RowFilter = core.row_filter(self.ClashSearch.Text)
        self.paint_place_label()

    def scoped_clashes(self):
        result = self.results.get(self.shown_result)
        if result is None:
            return []
        clashes = result['clashes']
        scope = self.tag_of(self.ScopeCombo) or 'all'
        if scope == 'selected':
            return [clashes[i] for i in selected_indexes(self.ClashGrid)]
        if scope == 'shown':
            out = []
            for row in self.clash_table.DefaultView:
                out.append(clashes[int(row['idx'])])
            return out
        return list(clashes)

    def paint_place_label(self):
        if self.painting:
            return
        clashes = self.scoped_clashes()
        n = len(clashes)
        self.PlaceLabel.Text = u'Place {0} clash famil{1}'.format(
            n, u'y' if n == 1 else u'ies')
        self.PlaceBtn.IsEnabled = n > 0 and bool(self.markers)
        fmt = self.tag_of(self.CommentCombo) or 'family_type'
        if clashes:
            self.CommentPreview.Text = u'Comment e.g. ' + core.comment_text(
                clashes[0]['a'], clashes[0]['b'], fmt)
        else:
            self.CommentPreview.Text = u''

    def on_show(self, sender, args):
        result = self.results.get(self.shown_result)
        idx = selected_indexes(self.ClashGrid)
        if result is None or not idx:
            self.status(u'Pick a clash in the list first')
            return
        clash = result['clashes'][idx[0]]
        ids = [s['eid'] for s in (clash['a'], clash['b']) if s['eid'] is not None]
        boxed = bool(self.SectionBoxChk.IsChecked)
        half = core.mm_to_ft(ZOOM_HALF_MM)
        point = clash['point']

        def job(uiapp):
            return jobs.show_clash(uiapp.ActiveUIDocument, point, half, ids, boxed)

        self.run(u'Zoom to clash', job,
                 lambda r: self.status(u'Clash {0}: {1}'.format(
                     idx[0] + 1, core.comment_text(clash['a'], clash['b']))))

    def on_place(self, sender, args):
        clashes = self.scoped_clashes()
        if not clashes:
            self.status(u'No clashes to place')
            return
        label = self.tag_of(self.MarkerCombo)
        symbol = None
        for l, sym in self.markers:
            if l == label:
                symbol = sym
        if symbol is None:
            self.tell(u'No clash family', u'Pick the family to place at each '
                      u'clash. Any loaded level based or work plane based '
                      u'model family can be used.')
            return
        ws_kind, ws_name, ws_id = self.chosen_workset(self.WorksetCombo)
        create_ws = ws_name if ws_kind == 'create' else None
        fmt = self.tag_of(self.CommentCombo) or 'family_type'
        test_name = self.shown_result
        now = datetime.datetime.now()
        stamp = (now.year, now.month, now.day, now.hour, now.minute)
        group_name = core.clash_group_name(stamp, test_name, u'L02')
        message = (u'Place {0} x {1}\nat the centre of each clash, write '
                   u'"{2}" style comments, and group them one group per floor, '
                   u'named with the level code, e.g.\n\n{3}\n\nClashes that already '
                   u'have this family within {4:.0f} mm are skipped.'.format(
                       len(clashes), label,
                       core.comment_text(clashes[0]['a'], clashes[0]['b'], fmt),
                       group_name, core.DUPLICATE_MM))
        if create_ws:
            message += u'\n\nWorkset "{0}" is created first, then they go on it.'.format(
                ws_name)
        elif ws_id is not None:
            message += u'\n\non workset "{0}".'.format(ws_name)
        result_now = self.results.get(test_name) or {}
        level_id = result_now.get('view_level')
        if level_id is not None:
            message += u'\n\nLevel: "{0}" (the floor plan this test ran in).'.format(
                rv.level_name(self.doc, level_id))
        else:
            message += u'\n\nLevel: the closest level at or below each clash.'
        if not self.confirm(u'Place clash families', message, u'Place'):
            return
        log = self.log.write

        def job(uiapp):
            doc = uiapp.ActiveUIDocument.Document
            wid, made = ws_id, False
            if create_ws:
                wid, made = jobs.ensure_workset(doc, create_ws, log)
            result = jobs.place_markers(doc, clashes, symbol, wid, test_name,
                                        fmt, stamp, log, level_id)
            result['workset_created'] = create_ws if made else u''
            return result

        def done(result):
            self.after_workset_job(result)
            failed = len(result['failed'])
            n_groups = len(result['groups'])
            text = u'Placed {0} clash families in {1} floor group{2}'.format(
                result['placed'], n_groups, u'' if n_groups == 1 else u's')
            if result['skipped']:
                text += u' - {0} skipped (already placed)'.format(result['skipped'])
            if failed:
                text += u' - {0} could not be placed'.format(failed)
            self.status(text)
            notes = []
            if result['skipped'] and not result['placed'] and not failed:
                notes.append(u'Every clash already has a {0} family in place - '
                             u'nothing new was placed.'.format(
                                 rv.family_of(symbol)))
            if failed:
                notes.append(u'{0} could not be placed. First reason: {1}'.format(
                    failed, result['failed'][0][1]))
            if result['comments_ok'] < result['placed']:
                notes.append(u'{0} did not take the comment.'.format(
                    result['placed'] - result['comments_ok']))
            if result['workset_refused']:
                notes.append(u'{0} stayed off the workset.'.format(
                    result['workset_refused']))
            if result['level_refused']:
                notes.append(u'{0} would not take their level.'.format(
                    result['level_refused']))
            if result['placed'] and not result['group_ok']:
                notes.append(u'A group could not be given its full name.')
            if notes:
                self.tell(u'Clash families placed - check these', u'\n'.join(notes))
            self.refresh_groups(select_name=result['group_name'])
            self.MainTabs.SelectedItem = self.TabGroups

        self.run(u'Placing clash families', job, done)

    def chosen_symbol(self):
        label = self.tag_of(self.MarkerCombo)
        for l, sym in self.markers:
            if l == label:
                return sym
        return None

    def paint_schedule_btn(self):
        sym = self.chosen_symbol()
        self.ScheduleBtn.IsEnabled = sym is not None
        if sym is not None:
            self.ScheduleBtn.ToolTip = (
                u'Create or update {0}: Generic Models where Family is "{1}", '
                u'Level and Comments, sorted by Level'.format(
                    core.SCHEDULE_NAME, rv.family_of(sym)))

    def on_schedule(self, sender, args):
        symbol = self.chosen_symbol()
        if symbol is None:
            self.tell(u'No clash family', u'Pick the clash family first - the '
                      u'schedule lists that family only.')
            return
        family = rv.family_of(symbol)
        exists = rv.find_schedule(self.doc, core.SCHEDULE_NAME) is not None
        message = (u'{0} {1}\n\nGeneric Models where Family is "{2}"\n'
                   u'Columns: Level, Comments\nSorted by Level, with a header '
                   u'per level\nComments column sized to the longest comment.'.format(
                       u'Update' if exists else u'Create', core.SCHEDULE_NAME, family))
        if exists:
            message += (u'\n\nThe schedule already exists: its fields, filters and '
                        u'sorting are replaced. Sheets it is placed on keep it.')
        if not self.confirm(u'Clash schedule', message,
                            u'Update' if exists else u'Create'):
            return
        log = self.log.write

        def job(uiapp):
            uidoc = uiapp.ActiveUIDocument
            result = jobs.make_clash_schedule(uidoc.Document, symbol, log)
            result['opened'] = jobs.open_view(uidoc, result['id'])
            return result

        def done(result):
            text = u'{0} {1} - {2} clash famil{3}'.format(
                u'Created' if result['created'] else u'Updated',
                core.SCHEDULE_NAME, result['rows'],
                u'y' if result['rows'] == 1 else u'ies')
            self.status(text)
            if result['notes']:
                self.tell(u'Clash schedule - check these', u'\n'.join(result['notes']))

        self.run(u'Creating the clash schedule', job, done)

    # ------------------------------------------------------------------
    # CLASH- groups in the model
    # ------------------------------------------------------------------
    def fill_groups(self, select_name=None):
        rows = []
        for i, rec in enumerate(self.groups):
            values = [rec['name'], rec['parsed'].get('level', u''),
                      rec['parsed']['clash'], rec['parsed']['display_date'],
                      self.last_run_of(rec['parsed']['clash']),
                      rec['member_count'], rec['workset']]
            rows.append(values + [i, search_text(values)])
        self.painting = True
        try:
            fill_table(self.group_table, rows)
            self.group_table.DefaultView.RowFilter = core.row_filter(self.GroupSearch.Text)
        finally:
            self.painting = False
        target = None
        if select_name:
            for row in self.group_table.DefaultView:
                if row['name'] == select_name:
                    target = row
        if target is not None:
            self.GroupGrid.SelectedItem = target
            self.GroupGrid.ScrollIntoView(target)
        else:
            self.show_report(None, [])

    def last_run_of(self, clash_name):
        """When the saved clash test a group came from last started running.
        Group names carry the test name tidied for Revit, so compare tidied."""
        key = core.to_text(clash_name).lower()
        for name, test in self.tests.items():
            if (core.sanitize_name(name) or u'Clash').lower() == key:
                return test.get('last_run') or u''
        return u''

    def refresh_groups(self, select_name=None):
        def job(uiapp):
            doc = uiapp.ActiveUIDocument.Document
            return rv.clash_groups(doc), rv.views_3d(doc), rv.user_name(doc)

        def done(found):
            groups, views, user = found
            self.fill_views_3d(views, user)
            self.groups = groups
            self.fill_groups(select_name)
            self.status(u'{0} CLASH- group{1} in the model'.format(
                len(groups), u'' if len(groups) == 1 else u's'))

        self.run(u'Reading clash groups', job, done)

    def on_group_search(self, sender, args):
        self.group_table.DefaultView.RowFilter = core.row_filter(self.GroupSearch.Text)

    def picked_group(self):
        idx = selected_indexes(self.GroupGrid)
        if not idx or idx[0] >= len(self.groups):
            return None
        return self.groups[idx[0]]

    def on_group_picked(self, sender, args):
        if self.painting:
            return
        rec = self.picked_group()
        if rec is None:
            return

        def job(uiapp):
            return rv.group_report(uiapp.ActiveUIDocument.Document, rec)

        self.run(u'Reading the group report', job,
                 lambda rows: self.show_report(rec, rows))

    def show_report(self, rec, rows):
        self.report_record = rec
        self.report_rows = rows
        if rec is None:
            self.ReportTitle.Text = u'Pick a group to see its report'
            fill_table(self.summary_table, [])
            fill_table(self.detail_table, [])
            self.ReviewSummary.Text = u''
            return
        self.ReportTitle.Text = u'{0}  -  {1} clash famil{2}'.format(
            rec['name'], len(rows), u'y' if len(rows) == 1 else u'ies')
        summary = core.comment_report([r['comments'] for r in rows])
        fill_table(self.summary_table,
                   [[c, n, i, search_text([c])] for i, (c, n) in enumerate(summary)])
        self.fill_detail()

    def fill_detail(self, keep=None):
        """Detail rows with their review blob. keep: row indexes to
        highlight again afterwards."""
        rows = self.report_rows
        detail = []
        states = []
        for i, r in enumerate(rows):
            state = core.review_state(self.reviews, r.get('uid'))
            states.append(state)
            values = [core.review_number(state), i + 1, r['id'], r['family_type'],
                      r['comments'], r['level'], r['workset']]
            detail.append(values + [i, search_text(values[1:] + [core.review_label(state)])])
        self.painting = True
        try:
            fill_table(self.detail_table, detail)
            if keep:
                for row in self.detail_table.DefaultView:
                    if int(row['idx']) in keep:
                        self.DetailGrid.SelectedItems.Add(row)
        finally:
            self.painting = False
        self.ReviewSummary.Text = core.review_summary(states) if rows else u''

    def on_copy_report(self, sender, args):
        rec = self.report_record
        if rec is None:
            self.status(u'Pick a group first')
            return
        lines = [rec['name'], u'', u'Comments\tQuantity']
        for c, n in core.comment_report([r['comments'] for r in self.report_rows]):
            lines.append(u'{0}\t{1}'.format(c, n))
        lines += [u'', u'Review\tElement ID\tFamily : Type\tComments\tLevel\tWorkset']
        for r in self.report_rows:
            lines.append(u'\t'.join(core.to_text(v) for v in (
                core.review_label(core.review_state(self.reviews, r.get('uid'))),
                r['id'], r['family_type'], r['comments'], r['level'], r['workset'])))
        try:
            Clipboard.SetText(u'\r\n'.join(lines))
            self.status(u'Report copied - paste it into Excel')
        except Exception:
            self.status(u'The clipboard is busy - try again')

    def on_select_group(self, sender, args):
        rec = self.report_record
        if rec is None:
            self.status(u'Pick a group first')
            return
        picked = [self.report_rows[i]['eid'] for i in selected_indexes(self.DetailGrid)]
        ids = picked or list(rec['instances'])

        def job(uiapp):
            jobs.select(uiapp.ActiveUIDocument, ids)
            return len(ids)

        self.run(u'Selecting in Revit', job,
                 lambda n: self.status(u'{0} selected in Revit'.format(n)))

    def on_zoom_member(self, sender, args):
        idx = selected_indexes(self.DetailGrid)
        if not idx:
            self.status(u'Pick a clash family in the lower table first')
            return
        row = self.report_rows[idx[0]]
        half = core.mm_to_ft(ZOOM_HALF_MM)
        boxed = bool(self.SectionBoxChk.IsChecked)

        def job(uiapp):
            uidoc = uiapp.ActiveUIDocument
            el = uidoc.Document.GetElement(row['eid'])
            bb = el.get_BoundingBox(None) if el is not None else None
            if bb is None:
                return False
            centre = core.box_centre((bb.Min.X, bb.Min.Y, bb.Min.Z,
                                      bb.Max.X, bb.Max.Y, bb.Max.Z))
            jobs.show_clash(uidoc, centre, half, [row['eid']], boxed)
            return True

        def done(ok):
            if not ok:
                self.status(u'That clash family has no extent to zoom to')
                return
            self.status(row['comments'])
            state = core.review_state(self.reviews, row.get('uid'))
            if core.after_zoom(state) != state:
                core.set_reviews(self.reviews, [row.get('uid')], core.after_zoom(state))
                self.save_reviews()
                self.fill_detail(keep=set(idx))
            # out of the way so the clash can be seen
            try:
                if not self.drawer.parked:
                    self.drawer.park()
            except Exception:
                self.log.write(u'auto shrink: ' + traceback.format_exc())

        self.run(u'Zoom to clash family', job, done)

    def on_assign_workset(self, sender, args):
        rec = self.picked_group()
        if rec is None:
            self.status(u'Pick a group first')
            return
        ws_kind, ws_name, ws_id = self.chosen_workset(self.GroupWorksetCombo)
        if ws_kind is None:
            self.status(u'Pick a workset first')
            return
        create_ws = ws_name if ws_kind == 'create' else None
        message = u'Put {0} and its {1} clash families on workset "{2}"?'.format(
            rec['name'], rec['member_count'], ws_name)
        if create_ws:
            message += u'\n\n"{0}" is not in the model yet - it is created first.'.format(
                ws_name)
        if not self.confirm(u'Assign workset', message, u'Assign'):
            return
        log = self.log.write

        def job(uiapp):
            doc = uiapp.ActiveUIDocument.Document
            wid, made = ws_id, False
            if create_ws:
                wid, made = jobs.ensure_workset(doc, create_ws, log)
            result = jobs.assign_workset(doc, rec, wid, log)
            result['workset_created'] = create_ws if made else u''
            return result

        def done(result):
            self.after_workset_job(result)
            if result['ok']:
                self.status(u'{0} clash families now on "{1}"'.format(
                    result['changed'], ws_name))
            else:
                self.tell(u'Workset not fully assigned', result['reason'])
            self.refresh_groups(select_name=rec['name'])

        self.run(u'Assigning workset', job, done)

    # ------------------------------------------------------------------
    # Review status
    # ------------------------------------------------------------------
    def load_reviews(self):
        try:
            if os.path.exists(self.reviews_path):
                return core.parse_reviews(read_text(self.reviews_path))
        except Exception:
            self.log.write(u'reviews: ' + traceback.format_exc())
        return {}

    def save_reviews(self):
        try:
            _ensure_dir(self.tests_dir)
            write_text(self.reviews_path, core.dump_reviews(self.reviews))
        except Exception:
            self.log.write(u'could not save review status: ' + traceback.format_exc())
            self.status(u'Review status could not be saved - see the debug log')

    def set_review(self, state):
        idx = selected_indexes(self.DetailGrid)
        if not idx:
            self.status(u'Highlight one or more clash families first '
                        u'(Ctrl / Shift click for several)')
            return
        uids = [self.report_rows[i].get('uid') for i in idx if i < len(self.report_rows)]
        changed = core.set_reviews(self.reviews, uids, state)
        if changed:
            self.save_reviews()
        self.fill_detail(keep=set(idx))
        self.status(u'{0} clash famil{1} set to {2}'.format(
            len(uids), u'y' if len(uids) == 1 else u'ies', core.review_label(state)))

    def build_detail_menu(self):
        menu = ContextMenu()
        dress(menu)
        apply_palette(menu, self.resolved_theme)
        for key, label, brush, n in core.REVIEW_STATES:
            item = MenuItem()
            item.Header = label
            blob = Ellipse()
            blob.Width = 11
            blob.Height = 11
            blob.SetResourceReference(Shape.FillProperty, brush)
            item.Icon = blob
            item.Tag = key
            item.Click += lambda s, e: self.set_review(s.Tag)
            menu.Items.Add(item)
        sep = Separator()
        sep.SetResourceReference(FrameworkElement.StyleProperty, 'MenuSep')
        menu.Items.Add(sep)
        zoom = MenuItem()
        zoom.Header = u'Zoom to family'
        zoom.Click += lambda s, e: self.on_zoom_member(None, None)
        menu.Items.Add(zoom)
        self.DetailGrid.ContextMenu = menu
        self.detail_menu = menu

    # ------------------------------------------------------------------
    # View in 3D
    # ------------------------------------------------------------------
    def fill_views_3d(self, views, user):
        names = [n for n, vid in views]
        keep = self.tag_of(self.View3DCombo)
        self.views3d = views
        self.painting = True
        try:
            self.View3DCombo.Items.Clear()
            for n, vid in views:
                self.View3DCombo.Items.Add(self.combo_item(n, n))
            if not views:
                self.View3DCombo.Items.Add(self.combo_item(
                    u'New: ' + core.NEW_3D_NAME, u''))
            want = keep or core.default_3d(names, user)
            if not (want and self.select_tag(self.View3DCombo, want)):
                self.View3DCombo.SelectedIndex = 0
        finally:
            self.painting = False

    def on_view_3d(self, sender, args):
        rec = self.report_record
        if rec is None:
            self.status(u'Pick a clash group first')
            return
        picked = [self.report_rows[i]['eid'] for i in selected_indexes(self.DetailGrid)]
        name = self.tag_of(self.View3DCombo) or u''
        view_id = None
        for n, vid in self.views3d:
            if n == name:
                view_id = vid
        log = self.log.write

        def job(uiapp):
            uidoc = uiapp.ActiveUIDocument
            members = picked or rv.group_members(uidoc.Document, rec)
            return jobs.view_in_3d(uidoc, view_id, members, log)

        def done(result):
            self.status(u'"{0}": section box round {1} clash sphere{2}'.format(
                result['view'], result['count'], u'' if result['count'] == 1 else u's'))
            if view_id is None:
                self.refresh_views_3d()
            if not result['zoomed']:
                self.run(u'Zooming to the clash spheres',
                         lambda uiapp: jobs.zoom_fit(uiapp.ActiveUIDocument,
                                                     result['view_id']),
                         lambda ok: None)

        self.run(u'Opening the 3D view', job, done)

    def refresh_views_3d(self):
        def job(uiapp):
            doc = uiapp.ActiveUIDocument.Document
            return rv.views_3d(doc), rv.user_name(doc)

        self.run(u'Reading 3D views', job, lambda r: self.fill_views_3d(r[0], r[1]))

    # ------------------------------------------------------------------
    # Isolate Clash Sphere / Reset view
    # ------------------------------------------------------------------
    def on_isolate(self, sender, args):
        rec = self.report_record
        if rec is None:
            self.status(u'Pick a clash group first')
            return
        picked = [self.report_rows[i]['eid'] for i in selected_indexes(self.DetailGrid)]

        def job(uiapp):
            uidoc = uiapp.ActiveUIDocument
            doc = uidoc.Document
            members = picked or rv.group_members(doc, rec)
            return rv.isolate_info(doc, uidoc.ActiveView, members)

        def done(info):
            if not info['members']:
                self.tell(u'Isolate Clash Sphere', u'The group has no clash spheres left '
                          u'in the model.')
                return
            if info['active_ok']:
                self.isolate_in(None, info)
                return
            if not info['views']:
                self.tell(u'Isolate Clash Sphere', u'The model has no floor plans to '
                          u'open. Isolating in the active view instead.')
                self.isolate_in(None, info)
                return
            try:
                picker = ViewPicker(self.window, self.drawer, self.resolved_theme, info)
                choice = picker.show()
            except Exception:
                self.log.write(u'view picker failed: ' + traceback.format_exc())
                self.status(u'The floor plan picker could not open - see the debug log')
                return
            if not choice:
                self.status(u'Isolate cancelled')
                return
            self.isolate_in(choice[1] if choice[0] == 'open' else None, info)

        self.run(u'Finding the clash spheres\' level', job, done)

    def isolate_in(self, view_id, info):
        """view_id None: the active view. Otherwise open that plan first."""
        log = self.log.write
        members = info['members']
        cats = info['cat_ids']

        def job(uiapp):
            uidoc = uiapp.ActiveUIDocument
            doc = uidoc.Document
            view = uidoc.ActiveView if view_id is None else doc.GetElement(view_id)
            if view is None:
                raise RuntimeError(u'that floor plan is no longer in the model')
            active = jobs.activate_view(uidoc, view)
            result = jobs.isolate_in_view(uidoc, view, members, cats, log)
            result['active'] = active
            return result

        def done(result):
            self.isolated_view = result['view_id']
            text = u'{0} clash sphere{1} isolated in "{2}"'.format(
                result['isolated'], u'' if result['isolated'] == 1 else u's',
                result['view'])
            if not result['tvp']:
                text += u' (Temporary View Properties refused - categories left as they are)'
            self.status(text)
            if not result['zoomed']:
                # the plan opens at Revit's next idle: zoom once it has
                self.run(u'Zooming to the clash spheres',
                         lambda uiapp: jobs.zoom_fit(uiapp.ActiveUIDocument,
                                                     result['view_id']),
                         lambda ok: None)

        self.run(u'Isolating the clash spheres', job, done)

    def on_reset_view(self, sender, args):
        last = self.isolated_view
        log = self.log.write

        def job(uiapp):
            uidoc = uiapp.ActiveUIDocument
            doc = uidoc.Document
            views = [uidoc.ActiveView]
            if last is not None and rv.eid_value(last) != rv.eid_value(uidoc.ActiveView.Id):
                v = doc.GetElement(last)
                if v is not None:
                    views.append(v)
            names = []
            for v in views:
                if jobs.reset_view(doc, v, log):
                    names.append(core.to_text(v.Name))
            return names

        def done(names):
            self.isolated_view = None
            if names:
                self.status(u'Reset: {0}'.format(u', '.join(u'"{0}"'.format(n) for n in names)))
            else:
                self.status(u'Nothing to reset - no temporary isolate or view properties on')

        self.run(u'Resetting the view', job, done)

    def on_delete_group(self, sender, args):
        rec = self.picked_group()
        if rec is None:
            self.status(u'Pick a group first')
            return
        if not self.confirm(u'Delete clash group',
                            u'Delete {0}?\n\nThis deletes {1} instance(s) of the '
                            u'group, its {2} clash families and the group type. '
                            u'Undo in Revit brings it back.'.format(
                                rec['name'], len(rec['instances']),
                                rec['member_count']),
                            u'Delete group', danger=True):
            return
        log = self.log.write

        def job(uiapp):
            return jobs.delete_group(uiapp.ActiveUIDocument.Document, rec, log)

        def done(result):
            if result['deleted']:
                self.status(u'Deleted {0}'.format(rec['name']))
            else:
                self.tell(u'Group not deleted', result['reason'])
            self.refresh_groups()

        self.run(u'Deleting clash group', job, done)



# ======================================================================
# Launch - one live window per Revit session
# ======================================================================

def forget():
    try:
        AppDomain.CurrentDomain.SetData(LIVE_KEY, None)
    except Exception:
        pass
    del _KEEP[:]


def bring_back():
    """True when a window from this version is already open - it is brought
    forward (and reopened if it was shrunk) instead of opening a second."""
    try:
        live = AppDomain.CurrentDomain.GetData(LIVE_KEY)
    except Exception:
        live = None
    if live is None:
        return False
    try:
        if not live.IsVisible:
            return False
        for keep in _KEEP:
            if getattr(keep, 'window', None) is live and keep.drawer.parked:
                keep.drawer.reopen()
        live.Activate()
        return True
    except Exception:
        return False


def create(uiapp):
    """Build the window inside the command, where reading the model is
    allowed. The window, its runner and its ExternalEvent are parked at
    module level so the persistent engine does not collect them."""
    runner = Runner()
    runner.event = ExternalEvent.Create(runner)
    win = ClashWindow(uiapp, runner)
    _KEEP[:] = [win, runner, runner.event]
    try:
        AppDomain.CurrentDomain.SetData(LIVE_KEY, win.window)
    except Exception:
        pass
    return win
