# -*- coding: utf-8 -*-
u"""Project Browser Pro - the browser itself.

One BrowserControl is the whole browser: header with the theme chip and
version top right, tabs, search, toolbar, the list and the debug footer.
It is hosted three ways and does not care which:
  * the main dockable pane (all tabs)
  * a dockable pane fixed to one tab (tab strip hidden)
  * Window.xaml, floating, when the panes are not registered

The list is a ListBox bound to a DataTable: the tree is flattened into rows
by pbp_tree, and only what is showing is in the table, so expanding a folder
is a rebuild of the visible rows rather than a tree of WPF objects.
"""
import os
import time

import pbp_clr  # noqa: F401
from System import Action
from System.Data import DataTable
from System.Windows import Visibility
from System.Windows.Controls import (ContextMenu, MenuItem, Separator, ListBoxItem,
                                     Button, WrapPanel, TextBlock, Orientation)
from System.Windows import DragDropEffects, DragDropKeyStates
from System.Windows.Input import Keyboard, ModifierKeys, Key, MouseButtonState
from System.Windows.Media import ScaleTransform, Geometry, VisualTreeHelper
from System.Windows.Threading import DispatcherTimer, DispatcherPriority

import pbp_log
import pbp_ui
import pbp_theme
import pbp_tree
import pbp_settings
import pbp_handoff
import pbp_runner
import pbp_store
import pbp_revit
import pbp_icons
import pbp_palette
import pbp_panes
import pbp_disc
import pbp_catgroups
from pbp_ui import find, safe, show
from pbp_compat import to_text, words, clamp, natural_key, eid_value, matches
from pbp_marks import clean_group as pbp_marks_clean
from pbp_version import __version__, TOOL_NAME

TABS = (
    # (tab, radio button, icon path, icon kind, tooltip label) - in tab order
    (u'all', u'TabAll', u'IconAll', u'all', u'Everything'),
    (u'favourites', u'TabFavourites', u'IconFavourites', u'star', u'Favourites'),
    (u'views', u'TabViews', u'IconViews', u'plan', u'Views'),
    (u'legends', u'TabLegends', u'IconLegends', u'legend', u'Legends and drafting views'),
    (u'sheets', u'TabSheets', u'IconSheets', u'sheet', u'Sheets'),
    (u'schedules', u'TabSchedules', u'IconSchedules', u'schedule', u'Schedules'),
    (u'panels', u'TabPanels', u'IconPanels', u'panel', u'Panel schedules'),
    (u'families', u'TabFamilies', u'IconFamilies', u'family', u'Families and types'),
)
COLUMNS = (u'key', u'text', u'count', u'pad', u'chev', u'chevvis', u'icon',
           u'iconvis', u'iconfill', u'fill', u'edge', u'pillvis', u'rowh',
           u'weight', u'dot', u'dotfill', u'dottip', u'fore', u'chevfill', u'size',
           u'iconback', u'iconbackfill')
NUMBER_COLUMNS = (u'pad', u'rowh', u'size')
ROW_HEIGHT = 22.0
PILL_HEIGHT = 25.0           # a coloured favourite
HEAD_HEIGHTS = {1: 28.0, 2: 25.0}
HEAD_SIZES = {1: 13.0, 2: 12.0}
HEAD_WEIGHTS = {1: u'Bold', 2: u'SemiBold'}
TEXT_SIZE = 12.0
# Where each level's headings sit on their colour gradient: main headings
# at the dark end, the level below lighter, each run dark to light.
LADDER = {1: (0.0, 0.3), 2: (0.38, 0.95)}
# The Legends and Drafting Views tab's two fixed groups: larger and bolder
# than any heading, so they read as the tab's own two halves.
MASTER_SIZE = 14.5
MASTER_HEIGHT = 31.0
MASTER_ICONS = {pbp_tree.LEGENDS: u'legend', pbp_tree.DRAFTING: u'drafting'}
LEGEND_ORDER = {1: list(pbp_tree.MASTERS)}
# The Legends tab's sub tabs, left to right: (master, its row icon kind).
SUB_TABS = ((pbp_tree.LEGENDS, u'legend'), (pbp_tree.DRAFTING, u'drafting'))
# The Favourites tab's row of the header tabs: (tab, button, icon, count).
FAV_SUBS = (
    (u'all', u'FavSubAll', u'FavSubIconAll', u'FavSubCountAll'),
    (u'views', u'FavSubViews', u'FavSubIconViews', u'FavSubCountViews'),
    (u'legends', u'FavSubLegends', u'FavSubIconLegends', u'FavSubCountLegends'),
    (u'sheets', u'FavSubSheets', u'FavSubIconSheets', u'FavSubCountSheets'),
    (u'schedules', u'FavSubSchedules', u'FavSubIconSchedules', u'FavSubCountSchedules'),
    (u'panels', u'FavSubPanels', u'FavSubIconPanels', u'FavSubCountPanels'),
    (u'families', u'FavSubFamilies', u'FavSubIconFamilies', u'FavSubCountFamilies'),
)
FAV_TABS = tuple(item[0] for item in FAV_SUBS)
# Tabs whose folder headings get discipline icons (Pipework, Ductwork, ...).
DISCIPLINE_TABS = (u'views', u'legends', u'sheets', u'schedules', u'panels')
FAMILY_ORDER = {1: list(pbp_catgroups.ORDER)}
SLOW_CLICK = 0.55            # seconds: a second click this long after the first renames
SYNC_DELAY = 0.3             # seconds the selection settles before Revit is told
DRAG_START = 10              # pixels the mouse moves before a heading is being dragged
FOLLOW_EVERY = 0.4           # seconds between looks for a new Revit selection
# What can be dragged onto a sheet to be placed on it.
PLACEABLE_TABS = (u'views', u'legends', u'schedules', u'panels')
MAX_SHEET_ITEMS = 6
DRAG_FORMAT = u'RevoBIM.ProjectBrowserPro.Drag'
# The drag in progress, shared by every browser in this engine, so views
# dragged from one browser window can be dropped on a sheet in another.
DRAGGING = [None]
# DragDropEffects.None - None is a keyword in Python, so it is read by name
NO_DROP = getattr(DragDropEffects, u'None')
# Tabs that show their type roots as headings.
ROOTED_TABS = (u'all', u'favourites')
MAX_GROUP_ITEMS = 10
INDENT = 14
NEST_INDENT = 12   # a dependent view sits this far right of its parent
BASE_PAD = 4
ZOOM_MIN = 0.6
ZOOM_MAX = 2.0
ZOOM_STEP = 0.1
CONFIRM_OPEN_OVER = 12
CONFIRM_EXPRESS_OVER = 20
# Seconds the model must be still before a change is read: a burst of
# edits costs one read.
REFRESH_SETTLE = 0.8
# A render slower than this is noted in the log, with its row count.
SLOW_RENDER_MS = 150
# Tabs whose items show under a sheet that is opened to its views.
SHEET_CONTENT = (u'views', u'legends', u'schedules', u'panels')
# A highlighter pen, for the menu's Highlight.
HIGHLIGHT_GLYPH = u'M8.5,0.8 L11.2,3.5 L5,9.7 L2.3,7 Z M2,7.6 L4.4,10 L1,11.2 Z'
# Dock: a window going into a frame's side; Undock: a window lifting out.
GLYPH_DOCK = u'M0.8,1.5 L11.2,1.5 L11.2,10.5 L0.8,10.5 Z M7.5,1.5 L7.5,10.5 M2.5,6 L5.8,6 M4.4,4.4 L5.8,6 L4.4,7.6'
GLYPH_UNDOCK = u'M0.8,4 L8,4 L8,11 L0.8,11 Z M4,1 L11.2,1 L11.2,8 L8,8 M6,6 L10,2 M7.6,2 L10,2 L10,4.4'
GLYPH_COLLAPSE = u'M2,1.5 L10,1.5 M3,5 L6,8 L9,5'
GLYPH_EXPAND = u'M2,10.5 L10,10.5 M3,7 L6,4 L9,7'
BAR_UP = u'M1.5,7 L5,3.5 L8.5,7'
BAR_DOWN = u'M1.5,3.5 L5,7 L8.5,3.5'


class BrowserControl(object):

    # The 1.0 to 1.4 on / off colour flag, kept as a view of the mode:
    # True is Colour, False is Greyscale. Custom reads as False.
    def _colour_flag(self):
        return self.colour_mode == u'colour'

    def _colour_flag_set(self, on):
        self.colour_mode = u'colour' if on else u'grey'

    colour = property(_colour_flag, _colour_flag_set)

    def __init__(self, host, fixed_tab=None, window=None, pin=None):
        self.host = host
        self.window = window
        self.folder = pbp_log.appdata_folder()
        # A pinned copy shows one heading dragged out of a browser: from a
        # pane slot ('pin:3', its heading read from the pins file and
        # re-read whenever a pin is written) or handed in (a floating copy).
        self.pin_slot = None
        self.pin = pin
        if fixed_tab and to_text(fixed_tab).startswith(u'pin:'):
            self.pin_slot = int(to_text(fixed_tab)[4:])
            self.pin = pbp_settings.load_pins(self.folder).get(self.pin_slot)
            fixed_tab = self.pin[0] if self.pin else u'views'
        elif self.pin:
            fixed_tab = self.pin[0]
        self.fixed_tab = fixed_tab
        self.last_pins = pbp_store.pins_count()
        # the dockable pane this browser is the content of, if any: a pane
        # opened from another browser takes its size and place from it
        if self.pin_slot is not None:
            self.pane_guid = pbp_panes.pin_guids()[self.pin_slot - 1]
        elif host == u'pane':
            self.pane_guid = pbp_panes.guid_for(fixed_tab)
        else:
            self.pane_guid = None
        self.settings = pbp_settings.load(self.folder)
        pbp_log.set_enabled(pbp_settings.as_bool(self.settings[u'debug']))
        self.theme_mode = self.settings[u'theme']
        self.theme_name = pbp_theme.resolve(self.theme_mode)
        self.tab = fixed_tab or self.settings[u'last_tab']
        self.colour_mode = pbp_settings.colour_mode(self.settings[u'colour'])
        self.last_settings = pbp_store.settings_count()
        self.zoom = float(clamp(self.settings[u'zoom'], ZOOM_MIN, ZOOM_MAX))
        self.bar_open = pbp_settings.as_bool(self.settings[u'bar'])
        self.sync = pbp_settings.as_bool(self.settings[u'sync'])
        self.follow = pbp_settings.as_bool(self.settings[u'follow'])
        # the Legends tab shows one of its masters at a time
        self.legend_sub = legend_sub(self.settings.get(u'legend_sub'))
        # ...and the Favourites tab all of its types, or one
        self.fav_sub = fav_sub(self.settings.get(u'fav_sub'))
        # folders start closed unless the setting says open
        self.start_open = pbp_settings.as_bool(self.settings.get(u'start_open', u'0'))
        self.following = False
        self.after_read = u''
        self.last_synced = set()
        self.last_selection = pbp_store.selection_count()
        self.plan = {}
        self.drag = None
        self.slow = None
        self.editing = None
        self.store = pbp_store.STORE
        self.runner = pbp_runner.get()
        self.snapshot = None
        self.roots = {}
        self.collapsed = {}   # per tab: the folders closed now
        # per tab: (state, folder keys, closed by default) as last drawn, so
        # what the user opens and closes is told apart and remembered
        self.fold_basis = {}
        self.open_sheets = {}  # per tab: the sheets opened to show their views
        self.rows = []
        self.row_by_key = {}
        self.search_words = []
        self.express = None
        self.progress = None
        self.last_folder = u''
        self.last_dirty = pbp_store.dirty_count()
        self.last_views = pbp_store.views_count()
        self.dirty_since = 0.0
        self.ticks = 0
        self.rendering = False
        # the cells in the list now, row by row - a redraw sets only the
        # cells that differ; and whether a change arrived while hidden
        self.shown = []
        self.last_fill = None
        self.stale = False
        self.menus = []
        self.tab_menus = {}
        self.disc_cache = {}
        # rows highlighted for now (keys); kept until turned off, not saved
        self.highlights = set()

        self.root = pbp_ui.load_xaml(u'Browser.xaml')
        pbp_theme.apply(self.root, self.theme_name)
        self._find_elements()
        self._build_table()
        self.scale = ScaleTransform(self.zoom, self.zoom)
        self.scaled.LayoutTransform = self.scale
        self._decorate()
        self._wire()
        self._paint_theme_chip()
        self._paint_dock()
        self._paint_toggles()
        self._apply_zoom(self.zoom, save=False)
        self._apply_bar()
        self._select_tab_button()
        self._update_toolbar()

        self.store.subscribe(self._on_snapshot)
        self.timer = DispatcherTimer()
        self.timer.Interval = _seconds(1.0)
        self.timer.Tick += safe(self._tick, u'tick')
        self.timer.Start()
        # Polls Pro Sheets four times a second while an express print runs,
        # so the progress strip moves smoothly; stopped the rest of the time.
        self.express_timer = DispatcherTimer()
        self.express_timer.Interval = _seconds(0.25)
        self.express_timer.Tick += safe(self._express_tick, u'express tick')
        # one-shot timers: rename on a slow second click, tell Revit the
        # selection once it settles, zoom views Revit opened late
        self.rename_timer = DispatcherTimer()
        self.rename_timer.Interval = _seconds(SLOW_CLICK)
        self.rename_timer.Tick += safe(self._rename_tick, u'rename tick')
        self.sync_timer = DispatcherTimer()
        self.sync_timer.Interval = _seconds(SYNC_DELAY)
        self.sync_timer.Tick += safe(self._sync_tick, u'sync tick')
        self.zoom_timer = DispatcherTimer()
        self.zoom_timer.Interval = _seconds(0.6)
        self.zoom_timer.Tick += safe(self._zoom_tick, u'zoom tick')
        self.zoom_pending = []
        # finds Revit's selection here: a quick look at a counter the
        # Idling hook bumps, a real look only when it moved
        self.follow_timer = DispatcherTimer()
        self.follow_timer.Interval = _seconds(FOLLOW_EVERY)
        self.follow_timer.Tick += safe(self._follow_tick, u'follow tick')
        self.follow_timer.Start()
        if self.store.snapshot is not None:
            self._on_snapshot(self.store.snapshot, False)
        pbp_log.log(u'browser built: host={0} tab={1} theme={2}/{3}'.format(
            host, fixed_tab or u'(all tabs)', self.theme_mode, self.theme_name))

    # ============================================================
    # building
    # ============================================================
    def _find_elements(self):
        r = self.root
        self.scaled = find(r, u'Scaled')
        self.header = find(r, u'Header')
        self.logo = find(r, u'LogoImage')
        self.title_text = find(r, u'TitleText')
        self.theme_chip = find(r, u'ThemeChip')
        self.dock_button = find(r, u'DockButton')
        self.dock_glyph = find(r, u'DockGlyph')
        self.dock_text = find(r, u'DockText')
        self.theme_glyph = find(r, u'ThemeGlyph')
        self.theme_text = find(r, u'ThemeText')
        self.version_text = find(r, u'VersionText')
        self.window_buttons = find(r, u'WindowButtons')
        self.full_button = find(r, u'FullButton')
        self.close_button = find(r, u'CloseButton')
        self.tab_strip = find(r, u'TabStrip')
        self.edit_layer = find(r, u'EditLayer')
        self.inline_edit = find(r, u'InlineEdit')
        self.search = find(r, u'SearchBox')
        self.clear_search = find(r, u'ClearSearch')
        self.collapse_button = find(r, u'CollapseButton')
        self.collapse_glyph = find(r, u'CollapseGlyph')
        self.colour_button = find(r, u'ColourButton')
        self.colour_dots = [find(r, u'ColourDot{0}'.format(i)) for i in (1, 2, 3)]
        self.settings_button = find(r, u'SettingsButton')
        self.org_button = find(r, u'OrgButton')
        self.refresh_button = find(r, u'RefreshButton')
        self.pop_out_button = find(r, u'PopOutButton')
        self.print_button = find(r, u'PrintButton')
        self.print_bar = find(r, u'PrintBar')
        self.print_bar_text = find(r, u'PrintBarText')
        self.express_button = find(r, u'ExpressButton')
        self.open_folder_button = find(r, u'OpenFolderButton')
        self.org_text = find(r, u'OrgText')
        self.sheet_set_button = find(r, u'SheetSetButton')
        self.sheet_set_text = find(r, u'SheetSetText')
        self.sub_tabs = find(r, u'SubTabs')
        self.sub_buttons = {pbp_tree.LEGENDS: find(r, u'SubLegends'),
                            pbp_tree.DRAFTING: find(r, u'SubDrafting')}
        self.sub_icons = {pbp_tree.LEGENDS: find(r, u'SubLegendsIcon'),
                          pbp_tree.DRAFTING: find(r, u'SubDraftingIcon')}
        self.sub_texts = {pbp_tree.LEGENDS: find(r, u'SubLegendsText'),
                          pbp_tree.DRAFTING: find(r, u'SubDraftingText')}
        self.fav_tabs = find(r, u'FavTabs')
        self.fav_buttons = {}
        self.fav_counts = {}
        for tab, button, icon, count in FAV_SUBS:
            self.fav_buttons[tab] = find(r, button)
            self.fav_counts[tab] = find(r, count)
            try:
                find(r, icon).Data = Geometry.Parse(pbp_icons.tab_glyph(tab))
            except Exception:
                pbp_log.exc(u'favourites tab icon')
        self.list = find(r, u'List')
        self.empty_text = find(r, u'EmptyText')
        self.status = find(r, u'StatusText')
        self.debug_tick = find(r, u'DebugTick')
        self.copy_report = find(r, u'CopyReportButton')
        self.log_button = find(r, u'LogButton')
        self.zoom_text = find(r, u'ZoomText')
        self.tab_buttons = {}
        self.counts = {}
        for tab, button, icon, kind, label in TABS:
            self.tab_buttons[tab] = find(r, button)
            try:
                find(r, icon).Data = Geometry.Parse(pbp_icons.tab_glyph(tab))
            except Exception:
                pbp_log.exc(u'tab icon')
        self.top_bar = find(r, u'TopBar')
        self.tool_bar = find(r, u'ToolBar')
        self.bar_toggle = find(r, u'BarToggle')
        self.footer = find(r, u'Footer')
        self.bar_glyph = find(r, u'BarToggleGlyph')

    def _build_table(self):
        self.table = DataTable(u'rows')
        for name in COLUMNS:
            if name in NUMBER_COLUMNS:
                self.table.Columns.Add(name, clr_type(u'double'))
            else:
                self.table.Columns.Add(name, clr_type(u'string'))
        self.list.ItemsSource = self.table.DefaultView

    def _decorate(self):
        self.version_text.Text = u'v' + __version__
        for master, kind in SUB_TABS:
            try:
                self.sub_icons[master].Data = Geometry.Parse(
                    pbp_icons.framed(pbp_icons.icon_for(kind)))
            except Exception:
                pass
        self._paint_title()
        if self.fixed_tab:
            show(self.tab_strip, False)
        show(self.window_buttons, self.host == u'window')
        logo = pbp_ui.logo_image()
        if logo is not None:
            self.logo.Source = logo
        pbp_ui.attach_egg(self.logo, getattr(self.window, u'window', None))
        self.debug_tick.IsChecked = pbp_settings.as_bool(self.settings[u'debug'])
        self.menu = self._new_menu()
        self.list.ContextMenu = self.menu
        for tab, button, icon, kind, label in TABS:
            menu = self._new_menu()
            self.tab_menus[tab] = menu
            self.tab_buttons[tab].ContextMenu = menu
        # Opened by a left click, under the button; not the button's
        # ContextMenu, so a right click does not show a stale list.
        self.sheet_set_menu = self._new_menu()
        self.org_menu = self._new_menu()

    def _paint_title(self):
        if self.pin:
            self.title_text.Text = u'\u2192 ' + (self.pin[1][-1] if self.pin[1] else TOOL_NAME)
            self.title_text.ToolTip = self._pin_line()
        elif self.fixed_tab:
            self.title_text.Text = u'{0} \u00b7 {1}'.format(
                TOOL_NAME, pbp_tree.TAB_LABELS.get(self.fixed_tab, self.fixed_tab))
        else:
            self.title_text.Text = TOOL_NAME

    def _pin_line(self):
        if not self.pin:
            return u''
        return u' \u203a '.join((pbp_tree.TAB_LABELS.get(self.pin[0], self.pin[0]),)
                                + tuple(self.pin[1]))

    def _new_menu(self):
        menu = ContextMenu()
        pbp_theme.apply(menu, self.theme_name)
        pbp_ui.set_style(menu, u'PbpContextMenu')
        self.menus.append(menu)
        return menu

    def _wire(self):
        self.theme_chip.Click += safe(self._cycle_theme, u'theme chip')
        self.dock_button.Click += safe(self._dock_clicked, u'dock')
        self.bar_toggle.Click += safe(self._bar_clicked, u'bar toggle')
        self.search.TextChanged += safe(self._search_changed, u'search')
        self.clear_search.Click += safe(self._clear_search, u'clear search')
        self.collapse_button.Click += safe(self._collapse_toggle, u'collapse')
        self.colour_button.Click += safe(self._colour_toggle, u'colour')
        self.settings_button.Click += safe(self._settings_clicked, u'settings')
        self.org_button.Click += safe(self._org_clicked, u'organisation')
        self.refresh_button.Click += safe(self._refresh_clicked, u'refresh')
        self.pop_out_button.Click += safe(self._pop_out_clicked, u'pop out')
        self.print_button.Click += safe(self._print_clicked, u'print')
        self.express_button.Click += safe(self._express_clicked, u'express')
        self.open_folder_button.Click += safe(self._open_folder, u'open folder')
        self.sheet_set_button.Click += safe(self._sheet_set_clicked, u'sheet set')
        for master, kind in SUB_TABS:
            self.sub_buttons[master].Checked += safe(self._sub_checker(master), u'sub tab')
        for tab in FAV_TABS:
            self.fav_buttons[tab].Checked += safe(self._fav_checker(tab), u'favourites tab')
        self.debug_tick.Checked += safe(self._debug_changed, u'debug on')
        self.debug_tick.Unchecked += safe(self._debug_changed, u'debug off')
        self.copy_report.Click += safe(self._copy_report, u'copy report')
        self.log_button.Click += safe(self._open_log, u'open log')
        self.list.PreviewMouseLeftButtonDown += safe(self._list_mouse_down, u'list mouse')
        self.list.MouseDoubleClick += safe(self._list_double, u'list double')
        self.list.PreviewMouseRightButtonDown += safe(self._list_right_down, u'list right')
        self.list.KeyDown += safe(self._list_key, u'list key')
        self.list.SelectionChanged += safe(self._selection_changed, u'selection')
        self.list.ContextMenuOpening += safe(self._list_menu_opening, u'list menu')
        self.list.PreviewMouseWheel += safe(self._list_wheel, u'list wheel')
        self.root.PreviewMouseMove += safe(self._drag_move, u'drag move')
        self.root.PreviewMouseLeftButtonUp += safe(self._mouse_up, u'mouse up')
        self.root.AllowDrop = True
        self.root.QueryContinueDrag += safe(self._drag_query, u'drag query')
        self.root.DragOver += safe(self._drag_over, u'drag over')
        self.root.Drop += safe(self._drop, u'drop')
        self.inline_edit.KeyDown += safe(self._edit_key, u'inline edit key')
        self.inline_edit.LostKeyboardFocus += safe(self._edit_lost, u'inline edit lost')
        self.root.PreviewMouseWheel += safe(self._wheel, u'zoom wheel')
        self.root.PreviewKeyDown += safe(self._root_key, u'root key')
        self.root.IsVisibleChanged += safe(self._visible_changed, u'visible')
        self.header.MouseLeftButtonDown += safe(self._header_down, u'header')
        self.full_button.Click += safe(self._full_clicked, u'full screen')
        self.close_button.Click += safe(self._close_clicked, u'close')
        for tab, button, icon, kind, label in TABS:
            self.tab_buttons[tab].Checked += safe(self._tab_checker(tab), u'tab ' + tab)
            self.tab_buttons[tab].ContextMenuOpening += safe(self._tab_menu_opener(tab), u'tab menu')

    # ============================================================
    # data
    # ============================================================
    def _on_snapshot(self, snapshot, views_only):
        u"""The store has news. Each kind costs only what it must:

        views opened or closed (True)   the dots of those rows, nothing else
        some tabs changed (PATCH)       those tabs' trees, redrawn only when
                                        this browser shows one of them
        the user's marks (MARKS)        every tree, nothing read
        a whole read (False)            everything

        A hidden browser (a pane behind another, a closed pin) keeps the
        snapshot and draws once, when it is next shown."""
        if snapshot is None:
            return
        self.snapshot = snapshot
        if views_only is True:
            if self._hidden():
                self.stale = True
            else:
                self._repaint_ids(self.store.changed_ids)
            return
        if views_only == pbp_store.PATCH:
            tabs = set(self.store.changed_tabs)
            self._drop_roots(tabs)
            if self._hidden():
                self.stale = self.stale or self._shows(tabs)
                return
            self._paint_counts()
            if not self._shows(tabs):
                return
        else:
            self.roots = {}
            if self._hidden():
                self.stale = True
                return
            self._paint_counts()
        self.stale = False
        self._render()
        if views_only:
            return
        if snapshot.note:
            self._status(snapshot.note)
        else:
            extra = u''
            if snapshot.errors:
                extra = u'  ({0} read problem(s) - see the debug report)'.format(len(snapshot.errors))
            self._status(u'{0}: {1} items, read in {2} ms.{3}'.format(
                snapshot.title, sum(snapshot.counts().values()), snapshot.ms, extra))
            if self.after_read:
                self._status(self.after_read)
                self.after_read = u''

    def _hidden(self):
        try:
            return not self.root.IsVisible
        except Exception:
            return False

    def _drop_roots(self, tabs):
        u"""Forget the trees of these tabs (and the favourites, which take
        from every tab); the others are kept as built."""
        for key in list(self.roots):
            if key == u'favourites' or key.split(u'|')[0] in tabs:
                del self.roots[key]

    def _shows(self, tabs):
        u"""Whether a change to these tabs changes what this browser draws."""
        tabs = set(tabs)
        if not tabs:
            return False
        if self.pin:
            mine = set([self.pin[0]])
        elif self.tab in (u'all', u'favourites'):
            return True
        else:
            mine = set([self.tab])
        if u'sheets' in mine:
            # a sheet opens to the views on it
            mine |= set(SHEET_CONTENT)
        return bool(mine & tabs)

    def _org(self, tab):
        if self.snapshot is not None and tab in self.snapshot.orgs:
            return self.snapshot.orgs[tab]
        return pbp_settings.normalise_org(pbp_settings.DEFAULT_ORGS.get(tab), tab)

    def _marks(self):
        return self.store.marks()

    def _root_for(self, tab, sheet_set=u''):
        u"""The tree for one tab. The Sheets tab can be cut down to one
        sheet set; that tree is cached under its own key, so the All tab
        (which always shows every sheet) never gets the filtered one."""
        cache_key = tab + (u'|set:' + sheet_set if sheet_set else u'')
        root = self.roots.get(cache_key)
        if root is None:
            org = dict(self._org(tab))
            if org[u'source'] == u'revit' and self.snapshot is not None:
                org[u'desc'] = self.snapshot.revit_desc.get(tab, False)
            leaves = self.snapshot.tabs.get(tab, []) if self.snapshot is not None else []
            prefix = None
            order = None
            if tab == u'panels':
                marks = self._marks()
                prefix = pbp_tree.panel_prefix(marks.group_of, bool(marks.groups))
            elif tab == u'legends':
                prefix = legend_master
                order = LEGEND_ORDER
            elif tab == u'families':
                order = FAMILY_ORDER
            if sheet_set:
                wanted = self.snapshot.sheet_sets.get(sheet_set, set())
                leaves = [leaf for leaf in leaves if leaf.uid in wanted]
            root = pbp_tree.build_tab(tab, leaves, org, prefix=prefix,
                                      key=u'r:sheets|set' if sheet_set else None,
                                      order=order)
            self.roots[cache_key] = root
        return root

    def _favourite_roots(self):
        roots = self.roots.get(u'favourites')
        if roots is None:
            tabs = self.snapshot.tabs if self.snapshot is not None else {}
            orgs = dict((tab, self._org(pbp_settings.fav_org_key(tab)))
                        for tab in pbp_settings.FAV_TYPES)
            roots = pbp_tree.build_favourites(self._marks().fav_leaves(tabs),
                                              self._favourite_groups(), orgs)
            self.roots[u'favourites'] = roots
        return roots

    def _favourite_groups(self):
        u"""{tab: [folder nodes]} for the whole folders made favourites -
        the tab's own nodes, found by their names in its whole tree."""
        groups = {}
        if self.snapshot is None:
            return groups
        for tab, path in self._marks().fav_groups:
            if tab not in pbp_tree.TAB_ORDER:
                continue
            node = pbp_tree.find_node(self._root_for(tab), path)
            if node is not None:
                groups.setdefault(tab, []).append(node)
        return groups

    def _sheet_set(self):
        u"""The sheet set the Sheets tab is filtered to, or u'' for all -
        and u'' too when the saved set has since been deleted in Revit."""
        if self.snapshot is None:
            return u''
        name = self._marks().sheet_set
        return name if name in self.snapshot.sheet_sets else u''

    def _pinned_node(self):
        u"""The heading a pinned copy shows, found by its folder names in
        the tab's whole tree - or None when this model has no such heading."""
        if not self.pin:
            return None
        return pbp_tree.find_node(self._root_for(self.pin[0]), self.pin[1])

    def _roots(self):
        if self.pin:
            node = self._pinned_node()
            return [node] if node is not None else []
        if self.tab == u'all':
            return [self._root_for(t) for t in pbp_tree.TAB_ORDER]
        if self.tab == u'favourites':
            roots = self._favourite_roots()
            if self.fav_sub != u'all':
                # one type: its favourites without the type's own heading
                roots = [root for root in roots if root.tab == self.fav_sub]
            return roots
        if self.tab == u'sheets':
            return [self._root_for(u'sheets', self._sheet_set())]
        if self.tab == u'legends':
            # one master at a time, chosen by the sub tabs; drawn without
            # its own heading, as a pinned copy is
            node = self._legend_master_node(self.legend_sub)
            return [node] if node is not None else []
        return [self._root_for(self.tab)]

    def _legend_master_node(self, master):
        for node in self._root_for(u'legends').children:
            if node.label == master:
                return node
        return None

    def _show_roots(self):
        if self.tab == u'favourites' and self.fav_sub != u'all':
            return False
        return self.tab in ROOTED_TABS and not self.pin

    def _full_roots(self):
        u"""The whole trees the colours are planned over - so a pinned copy
        colours its headings exactly as the browser it came from."""
        if self.pin:
            return [self._root_for(self.pin[0])]
        if self.tab == u'legends':
            # colours are planned over the whole tab, masters and all
            return [self._root_for(u'legends')]
        if self.tab == u'favourites':
            # each type's own grouping is coloured by its own organisation;
            # a favourite group keeps the colours it has on its own tab
            return [root for root in self._favourite_roots() if root.organised] + \
                [self._root_for(tab) for tab in pbp_tree.TAB_ORDER
                    if tab in set(t for t, path in self._marks().fav_groups)]
        return self._roots()

    def _fold_key(self):
        u"""Where opened and closed folders are remembered: per tab, and per
        pinned copy (a pin is a heading of its own)."""
        return u'pin:{0}'.format(self.pin_slot) if self.pin else self.tab

    def _collapsed_for(self, roots):
        u"""The folders closed now. Everything starts closed (as Collapse all
        leaves it); what the user opens or closes is remembered per tab, per
        project, and comes back next time - a folder new to the model
        starts closed.

        Opening and closing elsewhere in the browser change self.collapsed;
        here the change is told apart from the state last drawn and saved
        as the folders opened (closed by default) and closed (open by
        default - the type headings on the All tab)."""
        tab = self.tab
        where = self._fold_key()
        known = pbp_tree.all_group_keys(roots)
        if self.start_open:
            default = set()
        else:
            default = pbp_tree.collapse_all_state(roots, self._show_roots())
            if self._show_roots():
                # the type headings (All, Favourites) start open: closed,
                # a Favourites tab would look empty
                default -= set(root.key for root in roots)
        marks = self._marks()
        opened, shut = marks.folds_of(where)
        state = self.collapsed.get(tab)
        basis = self.fold_basis.get(tab)
        if state is not None and (basis is None or state != basis[0]):
            # the user opened or closed something since the last draw
            was_known, was_default = (basis[1], basis[2]) if basis else (known, default)
            state = set(state) & was_known
            new_opened = (opened - was_known) | (was_default - state)
            new_shut = (shut - was_known) | (state - was_default)
            if (new_opened, new_shut) != (opened, shut):
                opened, shut = new_opened, new_shut
                marks.set_folds(where, opened, shut)
                marks.save()
        state = (default - opened) | (shut & known)
        self.collapsed[tab] = state
        self.fold_basis[tab] = (set(state), known, default)
        return state

    # ============================================================
    # rendering
    # ============================================================
    def _render(self):
        if self.rendering:
            return
        self.rendering = True
        started = time.time()
        try:
            roots = self._roots()
            show_roots = self._show_roots()
            collapsed = self._collapsed_for(roots)
            selected = self._selected_keys()
            offset = self._scroll_offset()
            self._end_edit(False)
            self.plan = self._plan_headings(self._full_roots())
            self.rows = pbp_tree.flatten(roots, collapsed, self.search_words, show_roots,
                                         self.open_sheets.get(self.tab, set()))
            self.row_by_key = dict((row.key, row) for row in self.rows)
            self._fill_table([self._cells(row) for row in self.rows])
            self._reselect(selected)
            self._restore_scroll(offset)
            self._paint_empty()
            self._paint_org_line()
            self._paint_sub_tabs()
            self._paint_fav_tabs()
            self._paint_toggles()
            self._update_toolbar()
        finally:
            self.rendering = False
        ms = int((time.time() - started) * 1000)
        if ms >= SLOW_RENDER_MS:
            pbp_log.log(u'render {0}: {1} rows in {2} ms ({3})'.format(
                self.tab, len(self.rows), ms, self.last_fill))

    def _fill_table(self, all_cells):
        u"""Put these cells in the list. The same rows as before (the usual
        case after a change: a renamed view, a dot moved) have only the
        cells that differ set, so WPF redraws only those; different rows
        are loaded afresh."""
        all_cells = [tuple(cells) for cells in all_cells]
        same_rows = (len(all_cells) == len(self.shown) and
                     all(new[0] == old[0] for new, old in zip(all_cells, self.shown)))
        if same_rows:
            differing = sum(1 for new, old in zip(all_cells, self.shown) if new != old)
            # a theme or colour change touches every row: loading afresh is
            # quicker than setting every cell one by one
            same_rows = differing <= max(40, len(all_cells) // 2)
        if same_rows:
            changed = 0
            for index, cells in enumerate(all_cells):
                if self._set_cells(index, cells):
                    changed += 1
            self.last_fill = u'{0} of {1} rows redrawn'.format(changed, len(all_cells))
            return changed
        self.table.BeginLoadData()
        try:
            self.table.Rows.Clear()
            for cells in all_cells:
                self.table.Rows.Add(*cells)
        finally:
            self.table.EndLoadData()
        self.shown = all_cells
        self.last_fill = u'{0} rows loaded'.format(len(all_cells))
        return len(all_cells)

    def _set_cells(self, index, cells):
        u"""Set the cells of one row that differ from what it shows."""
        cells = tuple(cells)
        old = self.shown[index]
        if cells == old:
            return False
        row = self.table.Rows[index]
        for column, new_value, old_value in zip(COLUMNS, cells, old):
            if new_value != old_value:
                row[column] = new_value
        self.shown[index] = cells
        return True

    def _repaint_ids(self, ids):
        u"""Redraw only the rows of these elements - a view opened, closed
        or made active moves only its dot. The row count, which other row
        is where, the trees: none of it changes."""
        if not ids or self.rendering or len(self.shown) != len(self.rows):
            return 0
        count = 0
        for index, row in enumerate(self.rows):
            leaf = row.leaf
            if leaf is None or eid_value(leaf.eid) not in ids:
                continue
            if self._set_cells(index, self._cells(row)):
                count += 1
        return count

    def _discipline(self, text):
        u"""pbp_disc.match, cached: the same few dozen folder and template
        names come round on every render."""
        if text not in self.disc_cache:
            self.disc_cache[text] = pbp_disc.match(text)
        return self.disc_cache[text]

    def _heading_info(self, node, parent):
        u"""(colour family, discipline, icon) for a main heading.

        Families: the main group decides the gradient and the icon; a
        category below it keeps its group's gradient and shows its own
        discipline's icon where its name has one (Cable Trays, Ducts...).
        Elsewhere a heading's name decides (ELECTRICAL, HEATING, DRAINAGE);
        a second level heading naming nothing takes its main heading's."""
        if node.tab == u'legends' and node.level == 1 and node.label in MASTER_ICONS:
            return (u'other', None, pbp_icons.icon_for(MASTER_ICONS[node.label]))
        if node.tab == u'families':
            if node.level == 1:
                return (pbp_catgroups.ramp(node.label), None, pbp_catgroups.icon(node.label))
            found = self._discipline(node.label)
            icon = pbp_disc.icon(found) if found else (parent[2] if parent else None)
            family = parent[0] if parent else u'other'
            if family != u'other' and found and pbp_disc.family(found) != u'other':
                # inside the MEP groups a category keeps its own trade's
                # colour: Plumbing Fixtures brown under Mechanical & Plumbing
                family = pbp_disc.family(found)
            return (family, found, icon)
        if node.tab not in DISCIPLINE_TABS:
            return (u'other', None, None)
        found = self._discipline(node.label)
        if found is None and parent is not None:
            return parent
        return (pbp_disc.family(found), found, pbp_disc.icon(found) if found else None)

    def _plan_headings(self, roots):
        u"""Each main heading's place on its colour gradient, by node key.

        Per level, the headings of one colour family under the same parent
        run dark to light in browser order: three electrical headings under
        ELECTRICAL are three greens, darkest first. Main headings sit at the
        dark end of the ramp, the level below in its lighter part."""
        plan = {}
        for root in roots:
            organised = getattr(root, u'organised', None)
            if organised is not None:
                # a Favourites type root: only its own folders, by its own
                # organisation (its favourite groups are planned on their tab)
                levels = self._colour_levels(root.org_key)
                if levels:
                    self._plan_level(organised, None, 1, plan, levels)
                continue
            levels = self._colour_levels(root.tab)
            if levels:
                self._plan_level(root.children, None, 1, plan, levels)
        return plan

    def _group_colour(self, node):
        u"""A colour the user set in the tab's Browser Organisation for this
        value of this grouping level (or, as 1.3 stored them, for the name
        on any level) - or u''."""
        if node is None or not pbp_settings.colourable(org_key(node)):
            return u''
        own = self._org(org_key(node)).get(u'group_colours', {})
        return own.get(pbp_settings.group_key(node.level, node.label)) or own.get(node.label, u'')

    def heading_groups(self, tab):
        u"""[(level, name, colour now, on a coloured level)] for every
        folder on a tab, every level, in browser order, each level's names
        once - what Browser Organisation lists to be given colours of their
        own. Colour now is the user's, else the gradient's, else u''."""
        if tab in pbp_settings.FAV_ORGS:
            # that type's favourites, as they are grouped on the Favourites tab
            roots = [root for root in self._favourite_roots()
                     if root.tab == pbp_settings.base_tab(tab)]
            root = pbp_tree.Node(u'', u'', 0, pbp_settings.base_tab(tab), ())
            root.children = list(roots[0].organised) if roots else []
            plan = self._plan_headings(roots)
        else:
            root = self._root_for(tab)
            plan = self._plan_headings([root])
        out = []
        seen = set()

        def visit(node):
            for child in node.children:
                if (child.level, child.label) not in seen:
                    seen.add((child.level, child.label))
                    colour = self._group_colour(child)
                    if not colour and child.key in plan:
                        colour = pbp_palette.shade(plan[child.key][0], plan[child.key][1])
                    out.append((child.level, child.label, colour, child.key in plan))
                visit(child)
        visit(root)
        return out

    def level_offset(self, tab):
        u"""How many fixed folder levels a tab puts above its organisation's
        own (the Legends / Drafting Views masters, panel groups)."""
        if tab == u'legends':
            return 1
        if tab == u'panels' and self.snapshot is not None and self._marks().groups:
            return 1
        return 0

    def _colour_levels(self, tab):
        u"""The folder levels (counted from the top of the tab's tree) drawn
        as coloured main headings: the organisation's ticked levels, moved
        down past a tab's own fixed top level - panel groups (coloured too)
        and the Legends / Drafting Views masters (styled on their own).
        Families colour their main group and category unless the user
        ticked other levels (their grouping itself is fixed)."""
        if tab in pbp_settings.FAV_ORGS:
            # a favourites organisation: no fixed levels above its own
            return set(self._org(tab).get(u'colours', pbp_settings.DEFAULT_COLOURS))
        if tab == u'families':
            # main group and category unless the user ticked others
            return set(self._org(tab).get(u'colours', pbp_settings.DEFAULT_COLOURS))
        if tab not in pbp_settings.ORGANISABLE:
            return set()
        levels = set(self._org(tab).get(u'colours', pbp_settings.DEFAULT_COLOURS))
        if tab == u'legends':
            return set(level + 1 for level in levels)
        if tab == u'panels' and self.snapshot is not None and self._marks().groups:
            return set([1]) | set(level + 1 for level in levels)
        return levels

    def _plan_level(self, nodes, parent, level, plan, levels):
        if not nodes or level > max(levels):
            return
        infos = [(node, self._heading_info(node, parent)) for node in nodes]
        runs = {}
        for node, info in infos:
            runs.setdefault(info[0], []).append(node.key)
        first, last = LADDER[1 if level == min(levels) else 2]
        place = {}
        for family, keys in runs.items():
            for key, t in zip(keys, pbp_palette.ladder(len(keys), first, last)):
                place[key] = t
        rank = 1 if level == min(levels) else 2
        for node, info in infos:
            if level in levels:
                plan[node.key] = (info[0], place[node.key], info[1], info[2], rank)
            # the Legends / Drafting Views masters lend no icon or colour
            below = None if is_master(node) else info
            self._plan_level(node.children, below, level + 1, plan, levels)

    def _cells(self, row):
        u"""One DataTable row's values, in COLUMNS order.

        Colour lives on headings only. With the colour button on, each main
        heading - the first two folder levels (View Group and View Purpose;
        main group and category on Families) - is a solid rounded pill with
        a shadow, shaded along its family's gradient: electrical greens,
        mechanical blues, plumbing browns, everything else violets. Its
        text, icon and chevron take black or white for contrast. Main
        headings are larger and bold either way. Views get no fill; a
        view's icon comes from its view template's name. A favourite given
        a colour sits on a pill of that colour on the Favourites tab.
        """
        theme = self.theme_name
        pal = pbp_palette.palette(theme)
        transparent = pbp_palette.TRANSPARENT
        pad = float(BASE_PAD + row.level * INDENT + (NEST_INDENT if row.nested else 0))
        dotfill = transparent
        dottip = u''
        fill = edge = transparent
        pillvis = u'Collapsed'
        rowh = ROW_HEIGHT
        fore = pal[u'TextBrush']
        chevfill = pal[u'MutedBrush']
        size = TEXT_SIZE
        iconback = pbp_icons.NO_INNER
        iconbackfill = transparent
        if row.heading:
            chev = pbp_icons.CHEV_DOWN if row.expanded else pbp_icons.CHEV_RIGHT
            chevvis = u'Visible'
            node = row.node
            icon = pbp_icons.CHEV_RIGHT
            iconvis = u'Collapsed'
            iconfill = transparent
            weight = u'Normal'
            if row.is_root:
                kind = pbp_icons.TAB_ICON.get(row.tab, u'view')
                icon = pbp_icons.icon_for(kind)
                iconvis = u'Visible'
                iconfill = pbp_palette.kind_colour(pbp_icons.family_for(kind), theme)
                weight = u'SemiBold'
            elif is_master(node):
                weight = u'Bold'
                size = MASTER_SIZE
                rowh = MASTER_HEIGHT
                icon = pbp_icons.framed(pbp_icons.icon_for(MASTER_ICONS[node.label]))
                iconvis = u'Visible'
                iconfill = fore
            elif node is not None and (node.key in self.plan or self._group_colour(node)):
                if node.key in self.plan:
                    family, t, found, glyph, level = self.plan[node.key]
                else:
                    # a value on an uncoloured level the user gave a colour
                    family, t, found, glyph, level = u'other', 0.5, None, None, 2
                own = self._group_colour(node)
                weight = HEAD_WEIGHTS[level]
                size = HEAD_SIZES[level]
                rowh = HEAD_HEIGHTS[level]
                pillvis = u'Visible'
                mode = self.colour_mode
                if own and mode != u'grey':
                    # the colour the user gave this group (Colour and Custom)
                    fill, edge, fore = pbp_palette.own_pill(own)
                    chevfill = iconfill = fore
                elif mode == u'colour':
                    fill, edge, fore = pbp_palette.heading_pill(family, t)
                    chevfill = iconfill = fore
                else:
                    # Greyscale, and Custom where no colour was given: the
                    # bars stay, in grey (barely there on light)
                    fill, edge = pbp_palette.grey_pill(level, theme)
                    iconfill = pal[u'MutedBrush']
                if glyph:
                    icon = glyph
                    iconvis = u'Visible'
            count = u'({0})'.format(row.count) if row.count is not None else u''
            dot = u'Collapsed'
        else:
            leaf = row.leaf
            # a sheet with views on it opens like a folder, as in Revit
            chev = pbp_icons.CHEV_DOWN if row.expanded else pbp_icons.CHEV_RIGHT
            chevvis = u'Visible' if row.opens else u'Hidden'
            icon = pbp_icons.icon_for(leaf.kind)
            iconvis = u'Visible'
            iconfill = pbp_palette.kind_colour(pbp_icons.family_for(leaf.kind), theme)
            if pbp_icons.is_view_kind(leaf.kind):
                # Views are plain framed icons in the text colour, with a
                # small symbol: the discipline its template names, else
                # its view type.
                symbol = icon
                if leaf.template:
                    found = self._discipline(leaf.template)
                    if found is not None:
                        symbol = pbp_disc.icon(found)
                icon = pbp_icons.framed(symbol)
                iconfill = fore
                if leaf.sheets:
                    # placed on a sheet: the inside of the frame in blue
                    iconback = pbp_icons.INNER
                    iconbackfill = pal[u'OnSheetBrush']
            if self.tab == u'favourites':
                colour = pbp_palette.slot_colour(self._marks().colour_of(leaf.uid), theme)
                if colour is not None:
                    fill, edge = pbp_palette.pill(colour, 2, theme)
                    pillvis = u'Visible'
                    rowh = PILL_HEIGHT
            count = u''
            # Bold marks a view with dependents nested under it. It gets no
            # fill or colour of its own; the active view is marked by an
            # orange dot instead of bold, so the two never clash.
            weight = u'Bold' if row.is_parent else u'Normal'
            if leaf.is_active:
                dot, dotfill, dottip = u'Visible', pal[u'OrangeBrush'], u'Active view'
            elif leaf.is_open:
                dot, dotfill, dottip = u'Visible', pal[u'GreenBrush'], u'Open in Revit'
            else:
                dot = u'Collapsed'
        if row.key in self.highlights:
            # highlighted: the settings' fill and text over whatever the row
            # had (marker yellow; white bold text on the dark theme)
            fill, edge, fore, bold = self._highlight_style(theme)
            pillvis = u'Visible'
            chevfill = fore
            if bold:
                weight = u'Bold'
            if row.heading and not row.is_root:
                iconfill = fore
            rowh = max(rowh, PILL_HEIGHT)
        return [row.key, row.text, count, pad, chev, chevvis, icon, iconvis,
                iconfill, fill, edge, pillvis, rowh, weight, dot, dotfill, dottip,
                fore, chevfill, size, iconback, iconbackfill]

    def _paint_counts(self):
        u"""Counts live in each tab's tooltip and in the line under the
        toolbar - the icon tabs have no room for a number."""
        counts = dict(self.snapshot.counts() if self.snapshot is not None else {})
        counts[u'all'] = sum(counts.values())
        if self.snapshot is not None:
            counts[u'favourites'] = sum(root.count for root in self._favourite_roots())
        self.counts = counts
        for tab, button, icon, kind, label in TABS:
            tip = u'{0}: {1}'.format(label, counts.get(tab, 0))
            if tab in pbp_settings.ORGANISABLE:
                tip += u'. Right click for Browser Organisation.'
            elif tab in pbp_settings.FIXED_ORGS:
                tip += u'. Right click for heading colours.'
            elif tab == u'favourites':
                tip += (u'. Right click anything in the browser to add it; right click here '
                        u'to organise a type\'s favourites.')
            self.tab_buttons[tab].ToolTip = tip

    def _paint_empty(self):
        if self.snapshot is None:
            text = u'Reading the model...'
        elif self.snapshot.note:
            text = self.snapshot.note
        elif self.pin and self._pinned_node() is None:
            text = (u'{0} is not in this model - it may have been renamed, or the '
                    u'browser organisation changed.\n\nDrag a heading out of the browser '
                    u'again to pin it here.'.format(self._pin_line()))
        elif not self.rows and self.search_words:
            text = u'Nothing matches the search.'
        elif not self.rows and self.tab == u'legends' and not self.pin:
            text = self._legend_empty_text()
        elif not self.rows and self.tab == u'favourites' and self.fav_sub != u'all':
            text = (u'No {0} in your favourites yet.\n\nRight click one on its own tab and '
                    u'choose Add to favourites.'.format(dict(
                        (tab, label) for tab, b, i, k, label in TABS)[self.fav_sub].lower()))
        elif not self.rows and self.tab == u'favourites':
            text = (u'No favourites yet.\n\nRight click a view, sheet, schedule, panel '
                    u'schedule or family type on any tab and choose Add to favourites.')
        elif not self.rows:
            text = u'Nothing to show on this tab.'
        else:
            text = u''
        self.empty_text.Text = text
        show(self.empty_text, bool(text))

    def _paint_org_line(self):
        self.sheet_set_text.Text = self._sheet_set() or u'All sheets'
        if self.pin:
            node = self._pinned_node()
            count = node.count if node is not None else 0
            self.org_text.Text = u'{0} items \u00b7 pinned copy of {1}'.format(count, self._pin_line())
            return
        if self.tab == u'all':
            line = u'Each tab keeps its own organisation. Right click a tab to change it.'
        elif self.tab == u'favourites' and self.fav_sub != u'all':
            name = self.snapshot.revit_names.get(self.fav_sub, u'') if self.snapshot is not None else u''
            line = pbp_settings.describe_org(self._org(pbp_settings.fav_org_key(self.fav_sub)), name)
        elif self.tab == u'favourites':
            line = u'By type, each grouped its own way: right click the Favourites tab to organise one.'
        elif self.tab in pbp_settings.ORGANISABLE:
            name = self.snapshot.revit_names.get(self.tab, u'') if self.snapshot is not None else u''
            line = pbp_settings.describe_org(self._org(self.tab), name)
        else:
            line = (u'Main group \u203a Category \u203a Family \u203a Type \u00b7 right click a '
                    u'heading to colour it')
        count = self.counts.get(self.tab, 0)
        if self.tab == u'sheets' and self._sheet_set():
            # the sheets in the set that exist - not the set's own count
            count = sum(root.count for root in self._roots())
        if self.snapshot is not None:
            line = u'{0} items \u00b7 {1}'.format(count, line)
        self.org_text.Text = line
        self.sheet_set_text.Text = self._sheet_set() or u'All sheets'

    def _paint_toggles(self):
        self._paint_colour_button()
        roots = self._roots()
        collapsed = pbp_tree.is_collapsed(self.collapsed.get(self.tab, set()), roots,
                                          self._show_roots())
        try:
            self.collapse_glyph.Data = Geometry.Parse(GLYPH_EXPAND if collapsed else GLYPH_COLLAPSE)
        except Exception:
            pass
        self.collapse_button.ToolTip = u'Expand all' if collapsed else u'Collapse all'

    def _paint_theme_chip(self):
        self.theme_text.Text = pbp_theme.LABELS.get(self.theme_mode, u'Auto')
        try:
            self.theme_glyph.Data = Geometry.Parse(pbp_theme.GLYPHS.get(self.theme_mode))
        except Exception:
            pass

    def _update_toolbar(self):
        # Print and Express float under the search box while sheets are
        # selected - one by one or under a selected heading - on any tab.
        show(self.sheet_set_button, self.tab == u'sheets')
        sheets = len(self._selected_sheets())
        show(self.print_bar, sheets > 0)
        show(self.open_folder_button, bool(self.last_folder))
        self.print_bar_text.Text = u'{0} sheet{1}'.format(sheets, u'' if sheets == 1 else u's')
        self.print_button.IsEnabled = sheets > 0
        self.express_button.IsEnabled = sheets > 0 and self.express is None
        self.print_button.ToolTip = (
            u'Open Pro Sheets with {0} sheet(s) ready to print'.format(sheets) if sheets
            else u'Select one or more sheets to print them with Pro Sheets')
        self.org_button.IsEnabled = (pbp_settings.colourable(self.tab) or
                                     self.tab == u'favourites') and not self.pin
        show(self.pop_out_button, self.tab != u'all' and not self.fixed_tab)
        self.clear_search.Visibility = Visibility.Visible if self.search.Text else Visibility.Collapsed

    def _status(self, text):
        self.status.Text = to_text(text)
        pbp_log.log(u'status: ' + to_text(text))

    # ============================================================
    # selection helpers
    # ============================================================
    def _selected_rows(self):
        rows = []
        for item in self.list.SelectedItems:
            try:
                row = self.row_by_key.get(to_text(item[u'key']))
            except Exception:
                row = None
            if row is not None:
                rows.append(row)
        return rows

    def _selected_keys(self):
        return set(row.key for row in self._selected_rows())

    def _selected_leaves(self):
        return pbp_tree.unique_leaves(self._selected_rows())

    def _selected_sheets(self):
        u"""Sheets picked one by one, and every sheet under a selected
        heading - so selecting a sheet folder prints all of it."""
        return sheets_of_rows(self._selected_rows())

    def _reselect(self, keys):
        if not keys:
            return
        try:
            for item in self.table.DefaultView:
                if to_text(item[u'key']) in keys:
                    self.list.SelectedItems.Add(item)
        except Exception:
            pbp_log.exc(u'reselect')

    def _row_at(self, source):
        u"""The row under a mouse event's OriginalSource, and whether the
        click landed on the chevron."""
        element = source
        on_chevron = False
        depth = 0
        while element is not None and depth < 40:
            depth += 1
            try:
                if to_text(getattr(element, u'Tag', u'')) == u'chev':
                    on_chevron = True
            except Exception:
                pass
            if isinstance(element, ListBoxItem):
                try:
                    key = to_text(element.DataContext[u'key'])
                    return self.row_by_key.get(key), on_chevron, element
                except Exception:
                    return None, False, element
            try:
                element = VisualTreeHelper.GetParent(element)
            except Exception:
                element = getattr(element, u'Parent', None)
        return None, False, None

    def _scroll_viewer(self):
        element = self.list
        for depth in range(6):
            try:
                if VisualTreeHelper.GetChildrenCount(element) == 0:
                    return None
                element = VisualTreeHelper.GetChild(element, 0)
            except Exception:
                return None
            if element.GetType().Name == u'ScrollViewer':
                return element
        return None

    def _scroll_offset(self):
        viewer = self._scroll_viewer()
        try:
            return viewer.VerticalOffset if viewer is not None else 0.0
        except Exception:
            return 0.0

    def _restore_scroll(self, offset):
        viewer = self._scroll_viewer()
        if viewer is None or not offset:
            return

        def restore():
            try:
                viewer.ScrollToVerticalOffset(offset)
            except Exception:
                pass
        try:
            self.root.Dispatcher.BeginInvoke(DispatcherPriority.Loaded, Action(restore))
        except Exception:
            restore()

    # ============================================================
    # list events
    # ============================================================
    def _list_mouse_down(self, sender, args):
        row, on_chevron, item = self._row_at(args.OriginalSource)
        self.slow = None
        self.drag = None
        self.rename_timer.Stop()
        if row is not None and on_chevron and (row.heading or row.opens):
            args.Handled = True
            self._toggle(row)
            return
        if row is None:
            return
        plain = no_modifiers()
        if row.heading and plain:
            # a heading pressed may become a heading dragged out
            self.drag = {u'row': row, u'start': args.GetPosition(self.root), u'live': False,
                         u'leaves': None}
        elif plain and row.leaf is not None and row.leaf.tab in PLACEABLE_TABS:
            # views pressed may become views dragged onto a sheet
            picked = self._selected_rows()
            keep = (args.ClickCount == 1 and item is not None and item.IsSelected
                    and len(picked) > 1)
            rows = picked if item is not None and item.IsSelected else [row]
            leaves = [leaf for leaf in pbp_tree.unique_leaves(rows) if leaf.tab in PLACEABLE_TABS]
            self.drag = {u'row': row, u'start': args.GetPosition(self.root), u'live': False,
                         u'leaves': leaves, u'keep': keep}
            if keep:
                # pressed on one of several selected views: keep them all
                # selected for the drag; a plain click selects just it
                args.Handled = True
        if (plain and args.ClickCount == 1 and item is not None and item.IsSelected
                and len(self._selected_rows()) == 1 and self._renamable(row)):
            # pressed again on the one selected row: a rename, unless it
            # turns out to be a double click or a drag
            self.slow = row.key

    def _mouse_up(self, sender, args):
        drag = self.drag
        self.drag = None
        if drag is not None and drag.get(u'keep'):
            # it was a click after all: select just that row
            self.list.SelectedItems.Clear()
            self._reselect(set([drag[u'row'].key]))
        if self.slow is not None:
            self.rename_timer.Stop()
            self.rename_timer.Start()

    def _rename_tick(self, sender, args):
        self.rename_timer.Stop()
        key, self.slow = self.slow, None
        rows = self._selected_rows()
        if key is not None and len(rows) == 1 and rows[0].key == key:
            self._begin_edit(rows[0])

    # ---- dragging: headings out into pinned copies, views onto sheets ----
    # Windows' own drag and drop (DragDrop.DoDragDrop), not a mouse capture
    # of our own: 1.3.0 captured the mouse itself, never heard the button
    # come up once it left the window, and the browser stayed mid-drag -
    # frozen, nothing placed. DoDragDrop runs its own loop and always ends.
    def _drag_move(self, sender, args):
        drag = self.drag
        if drag is None:
            return
        if args.LeftButton != MouseButtonState.Pressed:
            self.drag = None
            return
        point = args.GetPosition(self.root)
        if (abs(point.X - drag[u'start'].X) < DRAG_START
                and abs(point.Y - drag[u'start'].Y) < DRAG_START):
            return
        self.drag = None
        self.slow = None
        self.rename_timer.Stop()
        drag[u'live'] = True
        args.Handled = True
        leaves = drag.get(u'leaves')
        pbp_log.log(u'drag start: {0}'.format(
            u'{0} view(s)'.format(len(leaves)) if leaves is not None else u'heading ' + drag[u'row'].text))
        result = self._do_drag(drag)
        pbp_log.log(u'drag end: {0}'.format(result))
        self._finish_drag(drag, result)

    def _do_drag(self, drag):
        u"""Run the drag. Returns what happened: ('sheet', sheet leaf) when
        dropped on a sheet in a browser, ('outside', (x, y)) when released
        outside this browser (screen pixels), ('inside', None) when released
        in it on nothing, ('cancel', None) for Esc."""
        from System.Windows import DataObject, DragDrop, DragDropEffects
        from System.Windows.Input import Mouse
        DRAGGING[0] = drag
        drag[u'target'] = None
        drag[u'release'] = None
        try:
            try:
                # the list holds the mouse for its own drag-select: let go
                Mouse.Capture(None)
            except Exception:
                pass
            DragDrop.DoDragDrop(self.root, DataObject(DRAG_FORMAT, u'1'), DragDropEffects.Copy)
        except Exception:
            pbp_log.exc(u'drag')
            return (u'cancel', None)
        finally:
            DRAGGING[0] = None
        if drag[u'target'] is not None:
            return (u'sheet', drag[u'target'])
        if drag[u'release'] == u'cancel':
            return (u'cancel', None)
        if drag[u'release'] is not None:
            x, y = drag[u'release']
            return (u'outside', (x, y)) if self._outside_screen(x, y) else (u'inside', None)
        return (u'cancel', None)

    def _finish_drag(self, drag, result):
        kind, value = result
        leaves = drag.get(u'leaves')
        if leaves is None:
            if kind == u'outside':
                self._pin_heading(drag[u'row'])
            return
        if not leaves:
            return
        if kind == u'sheet':
            self._status(u'Placing {0} on {1}...'.format(plural(len(leaves), u'view'), value.text))
            self._job(u'place on sheet', lambda app: pbp_revit.place_on_sheet(app, value.eid, leaves),
                      self._placed)
        elif kind == u'outside':
            # onto Revit's own view: placed on the sheet open there
            x, y = value
            self._job(u'place on open sheet',
                      lambda app: pbp_revit.place_on_active_sheet(app, x, y, leaves), self._placed)
        elif kind == u'inside':
            self._status(u'Drop the views on a sheet - here, or on the sheet open in Revit.')

    def _place_on_open_sheet(self, leaves):
        self._job(u'place on open sheet',
                  lambda app: pbp_revit.place_on_active_sheet(app, None, None, leaves), self._placed)

    def _drag_query(self, sender, args):
        u"""Asked by Windows all through a drag that started here: notes
        where the button came up (screen pixels), and Esc."""
        drag = DRAGGING[0]
        if drag is None:
            return
        if args.EscapePressed:
            drag[u'release'] = u'cancel'
            return
        if not int(args.KeyStates) & int(DragDropKeyStates.LeftMouseButton):
            drag[u'release'] = mouse_screen()

    def _drag_over(self, sender, args):
        u"""A drag over this browser (from it or from another of them): a
        sheet under views is a place to drop; anything else is not."""
        args.Handled = True
        drag = DRAGGING[0]
        target = None
        if drag is not None and drag.get(u'leaves') and args.Data.GetDataPresent(DRAG_FORMAT):
            target = self._sheet_under(args.GetPosition(self.root))
        args.Effects = DragDropEffects.Copy if target is not None else NO_DROP
        if drag is not None and drag.get(u'leaves'):
            count = plural(len(drag[u'leaves']), u'view')
            self.status.Text = (u'Release to place {0} on {1}, centred.'.format(count, target.text)
                                if target is not None else
                                u'Drag {0} onto a sheet - here, or the sheet open in Revit.'.format(count))
        elif drag is not None:
            self.status.Text = u'Drag outside the browser to open {0} in its own window.'.format(
                drag[u'row'].text)

    def _drop(self, sender, args):
        args.Handled = True
        drag = DRAGGING[0]
        if drag is None or not drag.get(u'leaves') or not args.Data.GetDataPresent(DRAG_FORMAT):
            return
        drag[u'target'] = self._sheet_under(args.GetPosition(self.root))

    def _outside_screen(self, x, y):
        u"""True when a screen point (pixels) is not on this browser."""
        try:
            from System.Windows import Point
            top_left = self.root.PointToScreen(Point(0, 0))
            bottom_right = self.root.PointToScreen(Point(self.root.ActualWidth, self.root.ActualHeight))
            return not (top_left.X <= x <= bottom_right.X and top_left.Y <= y <= bottom_right.Y)
        except Exception:
            return True

    # ---- drag views onto a sheet ----
    def _sheet_under(self, point):
        u"""The sheet under a point in the browser: a sheet row, or a row
        of something placed on a sheet (its sheet)."""
        try:
            element = self.list.InputHitTest(self.root.TranslatePoint(point, self.list))
        except Exception:
            return None
        row, on_chevron, item = self._row_at(element)
        if row is None or row.heading:
            return None
        if row.on_sheet is not None:
            return row.on_sheet
        return row.leaf if row.leaf is not None and row.leaf.tab == u'sheets' else None

    def _placed(self, result, error):
        if error or not result:
            self._status(u'Placing failed - see the debug report.')
            return
        if not result.get(u'ok'):
            self._status(result.get(u'why', u'Nothing was placed.'))
            return
        refused = result.get(u'refused') or []
        line = u'Placed {0} on {1}, centred.'.format(plural(result[u'placed'], u'view'),
                                                     result.get(u'sheet', u'the sheet'))
        if refused:
            line += u' Not placed: ' + u'; '.join(u'{0} ({1})'.format(name, why)
                                                  for name, why in refused[:4])
        self._refresh(u'placed on sheet')
        # said now, and again once the refresh it starts has landed
        self.after_read = line
        self._status(line)

    def _pin_heading(self, row):
        u"""Open a copy of this heading in a pane of its own: the first
        pinned pane slot Revit is not showing, or a floating window when
        none is free (or the panes are not registered yet)."""
        if row.is_root:
            # a type heading (All, Favourites): its whole tab
            self._pop_out(row.tab if self.tab == u'all' else self.tab)
            return
        node = row.node
        if node is None:
            return
        pin = (node.tab, tuple(node.path))
        placement = self._placement()
        if not pbp_store.panes_registered():
            self._float_pin(pin, u'Dockable panes are not registered (the startup block), so it '
                                 u'opened as a floating window.', placement)
            return
        folder = self.folder
        offer = self._offer_placement

        def work(app):
            guid = pbp_revit.free_pane(app, pbp_panes.pin_guids())
            if guid is None:
                return {u'ok': False}
            slot = pbp_panes.pin_slot_for(guid)
            pbp_settings.save_pin(folder, slot, pin[0], pin[1])
            pbp_store.bump_pins()
            offer(guid, placement)
            result = pbp_revit.show_pane(app, guid)
            result[u'slot'] = slot
            return result

        def done(result, error):
            if error or not result or not result.get(u'ok'):
                self._float_pin(pin, u'Every pinned pane is in use (close one), or Revit needs a '
                                     u'restart to make them - so it opened as a floating window.',
                                placement)
            else:
                self._status(u'{0} pinned in its own pane (RevoBIM Pinned {1}).'.format(
                    pin[1][-1], result.get(u'slot')))
        self._job(u'pin ' + row.text, work, done)

    def _float_pin(self, pin, why, placement=None):
        import pbp_window
        pbp_window.open_pinned(pin, placement)
        self._status(why)

    def _repin(self):
        u"""A pane slot was given a new heading: show that one."""
        pin = pbp_settings.load_pins(self.folder).get(self.pin_slot)
        if pin is None or pin == self.pin:
            return
        self.pin = pin
        self.fixed_tab = self.tab = pin[0]
        self.collapsed = {}
        self._paint_title()
        self._render()
        pbp_log.log(u'pinned pane {0} now shows {1}'.format(self.pin_slot, self._pin_line()))

    # ---- rename in place ----
    def _renamable(self, row):
        if row.heading:
            return self._is_group_heading(row, self._marks().group_names()) if self.snapshot else False
        return row.leaf is not None and row.leaf.tab != u'families'

    def _container(self, row):
        for item in self.table.DefaultView:
            if to_text(item[u'key']) == row.key:
                try:
                    self.list.ScrollIntoView(item)
                    self.list.UpdateLayout()
                except Exception:
                    pass
                return item, self.list.ItemContainerGenerator.ContainerFromItem(item)
        return None, None

    def _begin_edit(self, row):
        u"""Lay the edit box over the row's text, in place."""
        if not self._renamable(row):
            return False
        item, container = self._container(row)
        if container is None:
            return False
        from System.Windows import Point
        from System.Windows.Controls import Canvas
        cells = dict(zip(COLUMNS, self._cells(row)))
        left = cells[u'pad'] + 3 + 16 + 18
        try:
            origin = container.TranslatePoint(Point(left, 0), self.edit_layer)
        except Exception:
            pbp_log.exc(u'inline edit position')
            return False
        text = row.text
        self.editing = {u'key': row.key, u'row': row, u'original': text}
        box = self.inline_edit
        box.Text = text
        box.FontSize = cells[u'size']
        box.Width = max(60.0, container.ActualWidth - left - 6)
        box.Height = max(18.0, container.ActualHeight)
        Canvas.SetLeft(box, origin.X)
        Canvas.SetTop(box, origin.Y)
        show(box, True)
        box.Focus()
        leaf = row.leaf
        if leaf is not None and leaf.tab == u'sheets' and u' - ' in text:
            # the name part selected, the number still there to change
            start = text.index(u' - ') + 3
            box.Select(start, len(text) - start)
        else:
            box.SelectAll()
        return True

    def _edit_key(self, sender, args):
        if args.Key == Key.Enter:
            args.Handled = True
            self._end_edit(True)
        elif args.Key == Key.Escape:
            args.Handled = True
            self._end_edit(False)

    def _edit_lost(self, sender, args):
        self._end_edit(True)

    def _list_wheel(self, sender, args):
        if self.editing is not None:
            self._end_edit(True)

    def _end_edit(self, keep):
        editing, self.editing = self.editing, None
        if editing is None:
            return
        show(self.inline_edit, False)
        try:
            self.list.Focus()
        except Exception:
            pass
        if keep:
            self._commit_rename(editing[u'row'], to_text(self.inline_edit.Text).strip())

    def _commit_rename(self, row, text):
        if not text or text == row.text:
            return
        if row.heading:
            self._marks().rename_group(row.text, text)
            self.store.save_marks(u'rename group in place')
            self._status(u'Group renamed to {0}.'.format(text))
            return
        leaf = row.leaf
        name, number = rename_parts(leaf, text)
        if name is None and number is None:
            return
        self._job(u'rename', lambda app: pbp_revit.rename_leaf(app, leaf, name, number),
                  self._renamed)

    # ---- double click ----
    def _list_double(self, sender, args):
        self.slow = None
        self.drag = None
        self.rename_timer.Stop()
        row, on_chevron, item = self._row_at(args.OriginalSource)
        if row is None or on_chevron:
            return
        args.Handled = True
        if row.heading:
            self._toggle(row)
        elif row.leaf.tab == u'families':
            self._place(row.leaf)
        else:
            self._open([row.leaf])

    def _list_right_down(self, sender, args):
        row, on_chevron, item = self._row_at(args.OriginalSource)
        if item is not None and not item.IsSelected:
            self.list.SelectedItems.Clear()
            item.IsSelected = True

    def _list_key(self, sender, args):
        key = args.Key
        rows = self._selected_rows()
        if key == Key.Enter:
            args.Handled = True
            leaves = self._selected_leaves()
            if leaves:
                self._open(leaves)
            elif len(rows) == 1 and rows[0].heading:
                self._toggle(rows[0])
        elif key in (Key.Left, Key.Right) and len(rows) == 1 and (rows[0].heading or rows[0].opens):
            args.Handled = True
            want_open = key == Key.Right
            if rows[0].expanded != want_open:
                self._toggle(rows[0])
        elif key == Key.F2:
            args.Handled = True
            if len(rows) != 1 or not self._begin_edit(rows[0]):
                self._rename()

    def _selection_changed(self, sender, args):
        if self.rendering:
            return
        self._update_toolbar()
        leaves = self._selected_leaves()
        if self.sync and leaves and not self.following:
            # Revit's selection follows the browser's, once it settles
            self.sync_timer.Stop()
            self.sync_timer.Start()
        if leaves:
            sheets = len(pbp_tree.sheet_leaves(leaves))
            text = u'{0} selected'.format(len(leaves))
            if sheets and self.tab in (u'sheets', u'favourites'):
                text += u' - Print or Express to send them to Pro Sheets'
            self.status.Text = text

    def _sync_tick(self, sender, args):
        self.sync_timer.Stop()
        leaves = self._selected_leaves()
        if not self.sync or not leaves or not self.runner.ready():
            return
        # remembered, so Revit's selection coming back is not "found" again
        self.last_synced = set(leaf.key for leaf in leaves)
        self.runner.queue(u'sync selection', lambda app: pbp_revit.select_leaves(app, leaves), None)

    def _follow_tick(self, sender, args):
        count = pbp_store.selection_count()
        if count == self.last_selection:
            return
        self.last_selection = count
        if (not self.follow or self.rendering or self.editing is not None or self.drag is not None
                or self.snapshot is None or not self.root.IsVisible):
            return
        targets = pbp_store.read_selection()
        keys = [key for kind, key in targets
                if kind == u'view' or (kind == u'type' and self.tab == u'families')]
        if not keys or set(keys) == self.last_synced:
            return
        self._reveal(keys)

    def _reveal(self, keys):
        u"""Open the folders holding these items, select them here and
        scroll to the first - Revit's selection, found in this browser."""
        if self.tab == u'legends' and not self.pin:
            wanted = set(keys)
            masters = [legend_master(leaf)[0] for leaf in
                       (self.snapshot.tabs.get(u'legends', []) if self.snapshot is not None else [])
                       if leaf.key in wanted]
            if masters and self.legend_sub not in masters:
                # it is on the other sub tab: go there
                self._show_sub(masters[0])
        found = pbp_tree.locate(self._roots(), keys)
        if not found:
            return 0
        closed = set(self.collapsed.get(self.tab, set()))
        for ancestors in found.values():
            closed -= set(ancestors)
        self.collapsed[self.tab] = closed
        self.following = True
        try:
            self._render()
            self.list.SelectedItems.Clear()
            self._reselect(set(found))
            first = [row for row in self.rows if row.key in found][:1]
            if first:
                item, container = self._container(first[0])
        finally:
            self.following = False
        self._status(u'Found {0} from Revit\'s selection.'.format(plural(len(found), u'item')))
        return len(found)

    def _follow_toggle(self):
        self.follow = not self.follow
        self.settings[u'follow'] = u'1' if self.follow else u'0'
        pbp_settings.save(self.folder, self.settings)
        self._status(u'Selecting in Revit finds it here.' if self.follow
                     else u'Selecting in Revit no longer finds it here.')

    def _sync_toggle(self):
        self.sync = not self.sync
        self.settings[u'sync'] = u'1' if self.sync else u'0'
        pbp_settings.save(self.folder, self.settings)
        self._status(u'Selecting here selects in Revit.' if self.sync
                     else u'Selecting here no longer selects in Revit.')

    def _toggle(self, row):
        if not row.heading:
            # a sheet: show or hide the views placed on it
            if row.opens:
                state = self.open_sheets.get(self.tab, set())
                self.open_sheets[self.tab] = pbp_tree.toggle(state, row.leaf.key)
                self._render()
            return
        state = self.collapsed.get(self.tab, set())
        self.collapsed[self.tab] = pbp_tree.toggle(state, row.key)
        self._render()

    def _sheet_opener(self, sheet):
        return lambda: self._open([sheet])

    def _fold_inside(self, heading, close):
        u"""Close (or open) every folder inside a heading; the heading
        itself stays open, so what is inside shows folded."""
        node = heading.node
        if node is None:
            return
        inside = pbp_tree.inside_keys(node)
        state = set(self.collapsed.get(self.tab, set()))
        state.discard(node.key)
        if close:
            state |= inside
        else:
            state -= inside
        self.collapsed[self.tab] = state
        self._render()

    def _sheet_views(self, heading, show_them):
        u"""Open (or shut) every sheet under a heading, so its placed views
        show (or hide) - Revit's +/- on each sheet, for a whole folder."""
        sheets = [leaf for leaf in self._heading_leaves(heading) if leaf.placed]
        state = set(self.open_sheets.get(self.tab, set()))
        keys = set(leaf.key for leaf in sheets)
        state = (state | keys) if show_them else (state - keys)
        self.open_sheets[self.tab] = state
        if show_them and heading.node is not None:
            closed = set(self.collapsed.get(self.tab, set()))
            closed.discard(heading.node.key)
            closed -= pbp_tree.inside_keys(heading.node)
            self.collapsed[self.tab] = closed
        self._render()
        self._status(u'{0} the views on {1} sheet(s).'.format(
            u'Showing' if show_them else u'Hiding', len(sheets)))

    def _heading_leaves(self, heading):
        node = heading.node
        return pbp_tree.leaves_under(node, node.flat) if node is not None else []

    # ============================================================
    # context menus
    # ============================================================
    def _item(self, menu, header, handler, enabled=True, gesture=u'', icon=None):
        item = MenuItem()
        pbp_ui.set_style(item, u'PbpMenuItem')
        item.Header = header
        item.IsEnabled = enabled
        if gesture:
            item.InputGestureText = gesture
        if icon is not None:
            item.Icon = icon
        item.Click += safe(lambda sender, args: handler(), u'menu ' + header)
        menu.Items.Add(item)
        return item

    def _separator(self, menu):
        if menu.Items.Count:
            separator = Separator()
            pbp_ui.set_style(separator, u'MenuSeparator')
            menu.Items.Add(separator)

    def _list_menu_opening(self, sender, args):
        menu = self.menu
        menu.Items.Clear()
        rows = self._selected_rows()
        leaves = pbp_tree.unique_leaves(rows)
        openable = [leaf for leaf in leaves if leaf.tab != u'families']
        sheets = pbp_tree.sheet_leaves(leaves)
        types = [leaf for leaf in leaves if leaf.tab == u'families']
        headings = [row for row in rows if row.heading]
        if openable:
            # Open selected: views, sheets, schedules and panel schedules
            # together, from any tab, in one go.
            label = u'Open' if len(openable) == 1 else u'Open selected ({0})'.format(len(openable))
            self._item(menu, label, lambda: self._open(openable), gesture=u'Enter')
            self._item(menu, u'Select in Revit', lambda: self._select_in_revit(openable))
        placeable = [leaf for leaf in leaves if leaf.tab in PLACEABLE_TABS]
        if placeable:
            self._item(menu, u'Place on the open sheet (centred)',
                       lambda: self._place_on_open_sheet(placeable))
        if len(leaves) == 1 and leaves[0].sheets:
            # the sheet(s) this view, legend or schedule is placed on
            for sheet in leaves[0].sheets[:MAX_SHEET_ITEMS]:
                self._item(menu, u'Open sheet {0}'.format(sheet.text), self._sheet_opener(sheet))
        if len(leaves) == 1 and leaves[0].tab != u'families' and len(rows) == 1:
            self._item(menu, u'Rename', lambda: self._begin_edit(rows[0]) or self._rename(),
                       gesture=u'F2')
        self._favourite_items(menu, leaves)
        self._highlight_items(menu, rows)
        self._panel_group_items(menu, leaves, headings)
        if sheets:
            self._separator(menu)
            self._item(menu, u'Print in ProSheets ({0})'.format(len(sheets)),
                       lambda: self._prosheets(u'print', sheets))
            self._item(menu, u'Express print ({0})'.format(len(sheets)),
                       lambda: self._prosheets(u'express', sheets), enabled=self.express is None)
        if len(types) == 1:
            self._separator(menu)
            self._item(menu, u'Place an instance', lambda: self._place(types[0]))
            self._item(menu, u'Select all instances', lambda: self._select_instances(types[0]))
        if leaves:
            names = u'\r\n'.join(leaf.text for leaf in leaves)
            self._item(menu, u'Copy name' if len(leaves) == 1 else u'Copy names',
                       lambda: self._copy(names))
        if headings and not sheets:
            sheets = sheets_of_rows(rows)
            if sheets:
                # a sheet heading prints everything under it
                self._separator(menu)
                self._item(menu, u'Print all {0} sheets in ProSheets'.format(len(sheets)),
                           lambda: self._prosheets(u'print', sheets))
                self._item(menu, u'Express print all {0} sheets'.format(len(sheets)),
                           lambda: self._prosheets(u'express', sheets), enabled=self.express is None)
        if len(headings) == 1:
            self._separator(menu)
            heading = headings[0]
            self._item(menu, u'Collapse folder' if heading.expanded else u'Expand folder',
                       lambda: self._toggle(heading))
            if heading.node is not None and heading.node.children:
                self._item(menu, u'Collapse all inside', lambda: self._fold_inside(heading, True))
                self._item(menu, u'Expand all inside', lambda: self._fold_inside(heading, False))
            placed = [leaf for leaf in self._heading_leaves(heading) if leaf.placed]
            if placed:
                shown = self.open_sheets.get(self.tab, set())
                if any(leaf.key not in shown for leaf in placed):
                    self._item(menu, u'Show views on sheets', lambda: self._sheet_views(heading, True))
                if any(leaf.key in shown for leaf in placed):
                    self._item(menu, u'Hide views on sheets', lambda: self._sheet_views(heading, False))
            self._item(menu, u'Select everything in it',
                       lambda: self._select_folder(heading))
            self._group_favourite_item(menu, heading)
            self._heading_colour_items(menu, heading)
        self._separator(menu)
        tab = self._menu_tab(rows)
        if tab in pbp_settings.ORGANISABLE:
            self._item(menu, u'Browser Organisation...', lambda: self._organise(tab))
        elif tab in pbp_settings.FIXED_ORGS:
            self._item(menu, u'Heading colours...', lambda: self._organise(tab))
        elif tab == u'favourites':
            # the types of what was clicked on, else the one showing, else all
            types = [t for t in pbp_settings.FAV_TYPES if t in set(row.tab for row in rows)]
            if not types and self.fav_sub != u'all':
                types = [self.fav_sub]
            self._fav_org_items(menu, types or None)
        self._item(menu, u'Expand all', self._expand_all)
        self._item(menu, u'Collapse all', self._collapse_all)
        self._item(menu, u'Select in Revit as I click', self._sync_toggle,
                   icon=self._check_glyph(self.sync))
        self._item(menu, u'Find Revit\'s selection here', self._follow_toggle,
                   icon=self._check_glyph(self.follow))
        if tab != u'all' and not self.fixed_tab:
            self._item(menu, u'Open {0} as its own window'.format(pbp_tree.TAB_LABELS.get(tab)),
                       lambda: self._pop_out(tab))

    # ---- highlights: rows marked for now ----
    def _highlight_items(self, menu, rows):
        u"""Highlight the rows right clicked; they stay highlighted, as more
        are added, until turned off."""
        keys = [row.key for row in rows]
        new = [key for key in keys if key not in self.highlights]
        old = [key for key in keys if key in self.highlights]
        if not new and not old and not self.highlights:
            return
        self._separator(menu)
        if new:
            self._item(menu, u'Highlight' if len(new) == 1 else u'Highlight {0}'.format(len(new)),
                       lambda: self._highlight(new, True), icon=self._glyph(HIGHLIGHT_GLYPH, u'FavBrush'))
        if old:
            self._item(menu, u'Remove highlight', lambda: self._highlight(old, False))
        if self.highlights:
            self._item(menu, u'Turn off highlight ({0})'.format(len(self.highlights)),
                       self._clear_highlights)

    def _highlight(self, keys, on):
        if on:
            self.highlights |= set(keys)
        else:
            self.highlights -= set(keys)
        self._render()

    def _clear_highlights(self):
        self.highlights = set()
        self._render()
        self._status(u'Highlights turned off.')

    # ---- a heading's colour, set from its menu ----
    def _heading_colour_items(self, menu, heading):
        u"""On a coloured heading: its colour, picked right there - the same
        choices as Browser Organisation (yours included), Automatic, or any
        colour (More colours...). Saved with the tab's organisation."""
        node = heading.node
        if node is None or heading.is_root or not pbp_settings.colourable(org_key(node)):
            return
        if node.key not in self.plan and not self._group_colour(node):
            return
        self._separator(menu)
        custom = pbp_settings.custom_colours(self.settings)
        row = WrapPanel()
        row.Orientation = Orientation.Horizontal
        row.MaxWidth = 300
        label = TextBlock()
        label.Text = u'Colour'
        label.Margin = _thickness(0, 0, 10, 4)
        label.VerticalAlignment = _centre()
        row.Children.Add(label)
        for colour in pbp_palette.choice_colours(custom):
            swatch = Button()
            pbp_ui.set_style(swatch, u'SwatchButton')
            swatch.Background = pbp_theme.brush(colour)
            swatch.ToolTip = colour
            swatch.Click += safe(self._heading_swatch(node, colour), u'heading swatch')
            row.Children.Add(swatch)
        item = MenuItem()
        pbp_ui.set_style(item, u'PbpMenuItem')
        item.Header = row
        item.StaysOpenOnClick = True
        menu.Items.Add(item)
        self._item(menu, u'More colours...', lambda: self._heading_more_colours(node))
        if self._group_colour(node):
            self._item(menu, u'Automatic colour', lambda: self.set_heading_colour(node, u''))

    def _heading_swatch(self, node, colour):
        def clicked(sender, args):
            args.Handled = True
            self.menu.IsOpen = False
            self.set_heading_colour(node, colour)
        return clicked

    def _heading_more_colours(self, node):
        import pbp_orgwin
        colour = pbp_orgwin.pick_colour(self._group_colour(node))
        if not colour:
            return
        custom = pbp_settings.custom_colours(self.settings)
        if colour not in custom:
            pbp_settings.set_custom_colours(self.settings, custom + [colour])
            pbp_settings.save(self.folder, self.settings)
        self.set_heading_colour(node, colour)

    def set_heading_colour(self, node, colour):
        u"""Give this heading (this value of this grouping level) its own
        colour, or back to automatic with u''. Every pane redraws."""
        whose = org_key(node)
        org = dict(self._org(whose))
        own = dict(org.get(u'group_colours', {}))
        key = pbp_settings.group_key(node.level, node.label)
        if colour:
            own[key] = colour
        else:
            own.pop(key, None)
            own.pop(node.label, None)
        org[u'group_colours'] = own
        self.store.save_org(whose, org)
        self.store.publish_marks_changed()
        self._status(u'{0}: {1}.'.format(node.label, u'colour ' + colour if colour else u'automatic colour'))

    # ---- favourites ----
    def _group_favourite_item(self, menu, heading):
        u"""A whole folder as a favourite: it shows under its type on the
        Favourites tab, with everything in it, in its own colours."""
        node = heading.node
        if node is None or heading.is_root or not node.path or self.snapshot is None:
            return
        if node.tab not in pbp_tree.TAB_ORDER:
            return
        marks = self._marks()
        if marks.is_fav_group(node.tab, node.path):
            self._item(menu, u'Remove group from favourites',
                       lambda: self._favourite_group(node, False))
        else:
            self._item(menu, u'Add group to favourites', lambda: self._favourite_group(node, True),
                       icon=self._glyph(pbp_icons.ICONS[u'star'], u'FavBrush'))

    def _favourite_group(self, node, add):
        marks = self._marks()
        if add:
            marks.add_fav_group(node.tab, node.path)
        else:
            marks.remove_fav_group(node.tab, node.path)
        self.store.save_marks(u'group favourite')
        self._status(u'{0} {1} favourites.'.format(node.label, u'added to' if add else u'removed from'))

    def _favourite_items(self, menu, leaves):
        if not leaves or self.snapshot is None:
            return
        marks = self._marks()
        new = [leaf for leaf in leaves if not marks.is_fav(leaf.uid)]
        old = [leaf for leaf in leaves if marks.is_fav(leaf.uid)]
        self._separator(menu)
        if new:
            label = u'Add to favourites' if len(new) == 1 else u'Add {0} to favourites'.format(len(new))
            self._item(menu, label, lambda: self._add_favourites(new),
                       icon=self._glyph(pbp_icons.ICONS[u'star'], u'FavBrush'))
        if old:
            label = (u'Remove from favourites' if len(old) == 1
                     else u'Remove {0} from favourites'.format(len(old)))
            self._item(menu, label, lambda: self._remove_favourites(old))
        if old and self.tab == u'favourites':
            self._swatch_row(menu, old)
            if any(marks.colour_of(leaf.uid) for leaf in old):
                self._item(menu, u'Clear colour', lambda: self._set_colour(old, u''))

    def _swatch_row(self, menu, leaves):
        u"""Set colour: one row of ten swatches inside the menu, so a colour
        is one click away rather than a window away."""
        row = WrapPanel()
        row.Orientation = Orientation.Horizontal
        label = TextBlock()
        label.Text = u'Set colour'
        label.Margin = _thickness(0, 0, 10, 0)
        label.VerticalAlignment = _centre()
        row.Children.Add(label)
        for index, name in enumerate(pbp_palette.COLOUR_NAMES):
            slot = u'c{0}'.format(index)
            swatch = Button()
            pbp_ui.set_style(swatch, u'SwatchButton')
            swatch.Background = pbp_theme.brush(pbp_palette.slot_colour(slot, self.theme_name))
            swatch.ToolTip = name
            swatch.Click += safe(self._swatch_clicked(leaves, slot), u'swatch ' + name)
            row.Children.Add(swatch)
        item = MenuItem()
        pbp_ui.set_style(item, u'PbpMenuItem')
        item.Header = row
        item.StaysOpenOnClick = True
        menu.Items.Add(item)

    def _swatch_clicked(self, leaves, slot):
        def clicked(sender, args):
            args.Handled = True
            self.menu.IsOpen = False
            self._set_colour(leaves, slot)
        return clicked

    def _add_favourites(self, leaves):
        added = self._marks().add_favs(leaves)
        self.store.save_marks(u'add')
        self._status(u'Added {0} to favourites.'.format(added))

    def _remove_favourites(self, leaves):
        removed = self._marks().remove_favs(leaves)
        self.store.save_marks(u'remove')
        self._status(u'Removed {0} from favourites.'.format(removed))

    def _set_colour(self, leaves, slot):
        self._marks().set_colour(leaves, slot)
        self.store.save_marks(u'colour')
        self._status(u'Colour cleared.' if not slot else u'Coloured {0} favourite(s) {1}.'.format(
            len(leaves), pbp_palette.COLOUR_NAMES[int(slot[1:])].lower()))

    # ---- panel schedule groups ----
    def _panel_group_items(self, menu, leaves, headings):
        if self.snapshot is None:
            return
        marks = self._marks()
        panels = [leaf for leaf in leaves if leaf.tab == u'panels']
        names = marks.group_names()
        group_heads = [row for row in headings if self._is_group_heading(row, names)]
        if not panels and len(group_heads) != 1:
            return
        self._separator(menu)
        if panels:
            current = set(marks.group_of(leaf.uid) for leaf in panels)
            for name in names[:MAX_GROUP_ITEMS]:
                if current == set([name]):
                    continue
                self._item(menu, u'Move to group: {0}'.format(name),
                           self._group_mover(panels, name))
            self._item(menu, u'New group...', lambda: self._new_group(panels))
            if any(current):
                self._item(menu, u'Remove from group', lambda: self._group_panels(panels, u''))
        if len(group_heads) == 1:
            name = group_heads[0].text
            self._item(menu, u'Rename group...', lambda: self._rename_group(name))
            self._item(menu, u'Ungroup', lambda: self._ungroup(name))

    def _is_group_heading(self, row, names):
        node = row.node
        return (node is not None and node.tab == u'panels' and node.level == 1
                and not row.is_root and row.text in names)

    def _group_mover(self, panels, name):
        return lambda: self._group_panels(panels, name)

    def _new_group(self, panels):
        name = pbp_ui.ask_text(u'New panel group', u'Group name for {0} panel schedule(s):'.format(
            len(panels)), u'', self.theme_name)
        name = pbp_marks_clean(name or u'')
        if name:
            self._group_panels(panels, name)

    def _group_panels(self, panels, name):
        self._marks().set_group(panels, name)
        self.store.save_marks(u'group')
        self._status(u'{0} panel schedule(s) {1}.'.format(
            len(panels), u'moved to ' + name if name else u'taken out of their group'))

    def _rename_group(self, old):
        new = pbp_marks_clean(pbp_ui.ask_text(u'Rename group', u'New name for the group:',
                                              old, self.theme_name) or u'')
        if not new or new == old:
            return
        self._marks().rename_group(old, new)
        self.store.save_marks(u'rename group')
        self._status(u'Group renamed to {0}.'.format(new))

    def _ungroup(self, name):
        count = self._marks().drop_group(name)
        self.store.save_marks(u'ungroup')
        self._status(u'{0} ungrouped ({1} panel schedule(s)).'.format(name, count))

    # ---- sheet sets ----
    def _sheet_set_clicked(self, sender, args):
        menu = self.sheet_set_menu
        menu.Items.Clear()
        current = self._sheet_set()
        self._item(menu, u'All sheets', lambda: self._choose_sheet_set(u''),
                   icon=self._check_glyph(not current))
        names = sorted(self.snapshot.sheet_sets.keys(), key=natural_key) if self.snapshot else []
        if names:
            self._separator(menu)
        for name in names:
            label = u'{0}  ({1})'.format(name, len(self.snapshot.sheet_sets[name]))
            self._item(menu, label, self._sheet_set_chooser(name), icon=self._check_glyph(name == current))
        if not names:
            self._item(menu, u'No sheet sets in this model (Print > Sheet sets)',
                       lambda: None, enabled=False)
        menu.PlacementTarget = self.sheet_set_button
        menu.Placement = _below()
        menu.IsOpen = True

    def _sheet_set_chooser(self, name):
        return lambda: self._choose_sheet_set(name)

    def _choose_sheet_set(self, name):
        marks = self._marks()
        if marks.sheet_set == name:
            return
        marks.sheet_set = name
        self.collapsed.pop(u'sheets', None)
        self.store.save_marks(u'sheet set')
        self._status(u'Showing the sheets in {0}.'.format(name) if name else u'Showing all sheets.')

    def _check_glyph(self, on):
        return self._glyph(u'M1.5,6.5 L4.5,9.5 L10.5,2.5', u'GreenBrush', stroke=True) if on else None

    def _glyph(self, data, brush_key, stroke=False):
        u"""A small Path for a menu item's icon column."""
        try:
            from System.Windows.Shapes import Path
            path = Path()
            path.Data = Geometry.Parse(data)
            path.Width = 12
            path.Height = 12
            colour = pbp_theme.brush(pbp_palette.palette(self.theme_name)[brush_key])
            if stroke:
                path.Stroke = colour
                path.StrokeThickness = 1.6
            else:
                path.Fill = colour
            return path
        except Exception:
            pbp_log.exc(u'menu glyph')
            return None

    def _menu_tab(self, rows):
        if self.tab != u'all':
            return self.tab
        tabs = set(row.tab for row in rows if row.tab)
        return tabs.pop() if len(tabs) == 1 else u'all'

    def _tab_menu_opener(self, tab):
        def opening(sender, args):
            menu = self.tab_menus[tab]
            menu.Items.Clear()
            if tab in pbp_settings.ORGANISABLE:
                self._item(menu, u'Browser Organisation...', lambda: self._organise(tab))
            elif tab == u'favourites':
                self._fav_org_items(menu)
            elif tab in pbp_settings.FIXED_ORGS:
                self._item(menu, u'Heading colours...', lambda: self._organise(tab))
            if tab != u'all' and not self.fixed_tab:
                self._item(menu, u'Open as its own dockable window', lambda: self._pop_out(tab))
            if tab == u'sheets' and self._sheet_set():
                self._item(menu, u'Show all sheets', lambda: self._choose_sheet_set(u''))
            self._item(menu, u'Refresh', self._refresh_clicked_menu)
            if not menu.Items.Count:
                args.Handled = True
        return opening

    # ============================================================
    # tabs, search, toolbar
    # ============================================================
    # ============================================================
    # the Legends tab's sub tabs
    # ============================================================
    def _legend_leaves(self, master):
        leaves = self.snapshot.tabs.get(u'legends', []) if self.snapshot is not None else []
        return [leaf for leaf in leaves if legend_master(leaf)[0] == master]

    def _paint_sub_tabs(self):
        u"""The grey strip under the search box: shown on the Legends tab,
        the chosen master checked, each with its count - or, while
        searching, how many of its items match."""
        on = self.tab == u'legends' and not self.pin
        show(self.sub_tabs, on)
        if not on:
            return
        for master, kind in SUB_TABS:
            leaves = self._legend_leaves(master)
            if self.search_words:
                count = sum(1 for leaf in leaves if matches(leaf.search, self.search_words))
            else:
                count = len(leaves)
            self.sub_texts[master].Text = u'{0}  {1}'.format(master, count)
            button = self.sub_buttons[master]
            if bool(button.IsChecked) != (master == self.legend_sub):
                button.IsChecked = master == self.legend_sub

    def _paint_fav_tabs(self):
        u"""The header tabs again, under the search box on the Favourites
        tab: each type's icon and how many favourites it holds (matches
        while searching); All shows every type under its heading."""
        on = self.tab == u'favourites' and not self.pin
        show(self.fav_tabs, on)
        if not on:
            return
        counts = dict((tab, 0) for tab in FAV_TABS)
        for root in self._favourite_roots():
            leaves = pbp_tree.leaves_under(root, root.flat)
            if self.search_words:
                leaves = [leaf for leaf in leaves if matches(leaf.search, self.search_words)]
            counts[root.tab] = len(set(leaf.key for leaf in leaves))
        counts[u'all'] = sum(counts.values())
        for tab in FAV_TABS:
            self.fav_counts[tab].Text = to_text(counts[tab])
            button = self.fav_buttons[tab]
            if bool(button.IsChecked) != (tab == self.fav_sub):
                button.IsChecked = tab == self.fav_sub

    def _fav_checker(self, tab):
        def checked(sender, args):
            self._show_fav(tab)
        return checked

    def _show_fav(self, tab):
        if tab == self.fav_sub:
            return False
        self.fav_sub = tab
        self.settings[u'fav_sub'] = tab
        pbp_settings.save(self.folder, self.settings)
        self._render()
        return True

    def _legend_empty_text(self):
        other = [m for m, kind in SUB_TABS if m != self.legend_sub][0]
        if self.search_words:
            found = sum(1 for leaf in self._legend_leaves(other)
                        if matches(leaf.search, self.search_words))
            if found:
                return u'Nothing in {0} matches the search - {1} in {2}.'.format(
                    self.legend_sub, found, other)
            return u'Nothing matches the search.'
        return u'No {0} in this model.'.format(self.legend_sub.lower())

    def _sub_checker(self, master):
        def checked(sender, args):
            self._show_sub(master)
        return checked

    def _show_sub(self, master, save=True):
        if master == self.legend_sub:
            return False
        self.legend_sub = master
        if save:
            self.settings[u'legend_sub'] = master
            pbp_settings.save(self.folder, self.settings)
        self._render()
        return True

    def _tab_checker(self, tab):
        def checked(sender, args):
            if self.fixed_tab or self.tab == tab:
                return
            self.tab = tab
            self.settings[u'last_tab'] = tab
            pbp_settings.save(self.folder, self.settings)
            self._render()
        return checked

    def _select_tab_button(self):
        button = self.tab_buttons.get(self.tab)
        if button is not None:
            button.IsChecked = True

    def _search_changed(self, sender, args):
        self.search_words = words(self.search.Text)
        self._render()

    def _clear_search(self, sender, args):
        self.search.Text = u''
        self.search.Focus()

    def _collapse_toggle(self, sender, args):
        roots = self._roots()
        if pbp_tree.is_collapsed(self.collapsed.get(self.tab, set()), roots, self._show_roots()):
            self._expand_all()
        else:
            self._collapse_all()

    def _expand_all(self):
        self.collapsed[self.tab] = set()
        self._render()

    def _collapse_all(self):
        self.collapsed[self.tab] = pbp_tree.collapse_all_state(self._roots(), self._show_roots())
        self._render()

    def _bar_clicked(self, sender, args):
        self.bar_open = not self.bar_open
        self.settings[u'bar'] = u'1' if self.bar_open else u'0'
        pbp_settings.save(self.folder, self.settings)
        self._apply_bar()

    def _apply_bar(self):
        u"""Fold the title line, the tool buttons and the footer (status,
        Debug, Copy report, Log, zoom) away, or bring them back.

        A floating window keeps its title line folded or not: it carries the
        drag handle and the close button, without which the window could be
        neither moved nor closed."""
        show(self.footer, self.bar_open)
        if self.bar_open:
            show(self.top_bar, True)
            show(self.tool_bar, True)
        elif self.host == u'window':
            show(self.top_bar, True)
            show(self.tool_bar, False)
        else:
            show(self.top_bar, False)
        try:
            self.bar_glyph.Data = Geometry.Parse(BAR_UP if self.bar_open else BAR_DOWN)
        except Exception:
            pass
        self.bar_toggle.ToolTip = (u'Hide the title, tool buttons and footer' if self.bar_open
                                   else u'Show the title, tool buttons and footer')

    def _colour_toggle(self, sender, args):
        u"""Colour -> Greyscale -> Custom -> Colour."""
        self.colour_mode = pbp_settings.next_colour_mode(self.colour_mode)
        self.settings[u'colour'] = self.colour_mode
        pbp_settings.save(self.folder, self.settings)
        pbp_store.bump_settings()
        self.last_settings = pbp_store.settings_count()
        self._render()
        self._status(u'Heading colours: {0}.{1}'.format(
            pbp_settings.COLOUR_LABELS[self.colour_mode],
            u' Grey, except headings given a colour of their own (right click a heading, '
            u'or Browser Organisation).' if self.colour_mode == u'custom' else u''))

    def _paint_colour_button(self):
        pal = pbp_palette.palette(self.theme_name)
        mode = self.colour_mode
        if mode == u'colour':
            fills = [pal[u'BlueBrush'], pal[u'OrangeBrush'], pal[u'GreenBrush']]
        elif mode == u'custom':
            fills = [pal[u'MutedBrush'], pal[u'OrangeBrush'], pal[u'MutedBrush']]
        else:
            fills = [pal[u'MutedBrush']] * 3
        for dot, colour in zip(self.colour_dots, fills):
            try:
                dot.Fill = pbp_theme.brush(colour)
            except Exception:
                pass
        pbp_ui.set_style(self.colour_button, u'ToolButtonOn' if mode != u'grey' else u'ToolButton')
        self.colour_button.ToolTip = u'Heading colours: {0} - click for {1}'.format(
            pbp_settings.COLOUR_LABELS[mode], pbp_settings.COLOUR_LABELS[pbp_settings.next_colour_mode(mode)])

    def _highlight_style(self, theme):
        u"""(fill, edge, text, bold) for highlighted rows, from the settings."""
        light = theme == u'light'
        fill = self.settings[u'highlight_light' if light else u'highlight_dark']
        text = self.settings[u'highlight_light_text' if light else u'highlight_dark_text']
        edge = pbp_palette.own_pill(fill)[1]
        return fill, edge, text, pbp_settings.as_bool(self.settings[u'highlight_bold'])

    def _settings_clicked(self, sender, args):
        import pbp_setwin
        result = pbp_setwin.ask(self.settings, self.theme_name)
        if result is None:
            return
        self.settings.update(result)
        pbp_settings.save(self.folder, self.settings)
        pbp_store.bump_settings()
        self._reload_settings()
        self._status(u'Settings saved.')

    def _reload_settings(self):
        u"""Settings changed (here or in another browser): take them up."""
        self.last_settings = pbp_store.settings_count()
        self.settings = pbp_settings.load(self.folder)
        self.colour_mode = pbp_settings.colour_mode(self.settings[u'colour'])
        self._render()

    def _org_clicked(self, sender, args):
        if self.tab == u'favourites':
            if self.fav_sub != u'all':
                self._organise(pbp_settings.fav_org_key(self.fav_sub))
                return
            # all types showing: which one's favourites
            menu = self.org_menu
            menu.Items.Clear()
            self._fav_org_items(menu)
            menu.PlacementTarget = self.org_button
            menu.Placement = _below()
            menu.IsOpen = True
        elif self.tab in pbp_settings.ORGANISABLE or self.tab in pbp_settings.FIXED_ORGS:
            self._organise(self.tab)

    def _refresh_clicked(self, sender, args):
        self._refresh(u'refresh button')

    def _refresh_clicked_menu(self):
        self._refresh(u'refresh menu')

    def _refresh(self, reason):
        if not self.runner.ready():
            self._status(u'Waiting for Revit - try again in a moment.')
            return
        self._status(u'Reading the model...')
        self.store.request_read(self.runner, reason)

    def _pop_out_clicked(self, sender, args):
        if self.tab != u'all':
            self._pop_out(self.tab)

    # ============================================================
    # organisation
    # ============================================================
    def _organise(self, key):
        u"""Browser Organisation for a tab ('views'), or for one type's
        favourites on the Favourites tab ('fav.views') - its own grouping,
        offered the type's parameters, apart from the type's tab."""
        if self.snapshot is None:
            self._status(u'Still reading the model.')
            return
        import pbp_orgwin
        tab = pbp_settings.base_tab(key)
        title = None
        colours_only = key in pbp_settings.FIXED_ORGS
        if key != tab:
            title = u'Favourites \u203a ' + pbp_tree.TAB_LABELS.get(tab, tab)
        elif colours_only:
            title = pbp_tree.TAB_LABELS.get(tab, tab) + u' \u00b7 heading colours'
        result = pbp_orgwin.ask(tab, self._org(key), self.snapshot.catalogues.get(tab, []),
                                self.snapshot.revit_names.get(tab, u''), self.theme_name,
                                self.snapshot.revit_levels.get(tab, []),
                                self.snapshot.revit_sort.get(tab, u''),
                                self.heading_groups(key), self.level_offset(key),
                                org_key=key, title=title, colours_only=colours_only)
        if result is None:
            return
        self.store.save_org(key, result)
        if colours_only:
            # only colours changed: every pane redraws, nothing to read
            self.store.publish_marks_changed()
            self._status(u'{0} heading colours saved.'.format(pbp_tree.TAB_LABELS.get(tab, tab)))
            return
        if key != tab:
            self.roots.pop(u'favourites', None)
            self.collapsed.pop(u'favourites', None)
            # every pane's Favourites tab regroups
            self.store.publish_marks_changed()
        else:
            self.roots.pop(tab, None)
            self.collapsed.pop(tab, None)
            self._render()
        if self.runner.ready():
            # the new grouping's values: this type alone is read again
            self._status(u'Reading {0} again...'.format(pbp_tree.TAB_LABELS.get(tab, tab)))
            self.store.request_sections(self.runner, [tab], u'organisation changed')

    def _fav_org_items(self, menu, tabs=None):
        u"""'Browser Organisation: Views...' for each type of favourite."""
        for tab in (tabs or pbp_settings.FAV_TYPES):
            label = pbp_tree.TAB_LABELS.get(tab, tab)
            self._item(menu, u'Browser Organisation: {0}...'.format(label),
                       self._fav_organiser(tab))

    def _fav_organiser(self, tab):
        return lambda: self._organise(pbp_settings.fav_org_key(tab))

    # ============================================================
    # actions through Revit
    # ============================================================
    def _job(self, name, work, done=None):
        if not self.runner.ready():
            self._status(u'Waiting for Revit - try again in a moment.')
            return False
        if not self.runner.queue(name, work, done):
            self._status(u'Revit would not take the request ({0}) - try again.'.format(name))
            return False
        return True

    def _open(self, leaves):
        ordered = pbp_tree.open_order([leaf for leaf in leaves if leaf.tab != u'families'])
        if not ordered:
            return
        if len(ordered) > CONFIRM_OPEN_OVER and not pbp_ui.confirm(
                u'Open views', u'Open {0} views, sheets and schedules?'.format(len(ordered)),
                self.theme_name, ok_text=u'Open'):
            return
        self._status(u'Opening {0}...'.format(len(ordered)))
        self._job(u'open', lambda app: pbp_revit.open_leaves(app, ordered), self._opened)

    def _opened(self, result, error):
        if error or result is None:
            self._status(u'Opening failed - see the debug report.')
            return
        later = result.get(u'zoom_later') or []
        if later:
            # Revit made these windows after the open returned: zoom them
            # on a second pass, once it has
            self.zoom_pending = list(later)
            self.zoom_timer.Stop()
            self.zoom_timer.Start()
        failed = result[u'failed']
        if failed:
            lines = u'\n'.join(u'{0}: {1}'.format(name, why) for name, why in failed[:12])
            self._status(u'Opened {0}, {1} refused.'.format(result[u'opened'], len(failed)))
            pbp_ui.message(u'Open views', u'Revit refused these:\n\n' + lines, self.theme_name)
        else:
            self._status(u'Opened {0}.'.format(result[u'opened']))

    def _zoom_tick(self, sender, args):
        self.zoom_timer.Stop()
        leaves, self.zoom_pending = self.zoom_pending, []
        if leaves and self.runner.ready():
            self.runner.queue(u'zoom to fit', lambda app: pbp_revit.zoom_leaves(app, leaves), None)

    def _select_in_revit(self, leaves):
        self._job(u'select', lambda app: pbp_revit.select_leaves(app, leaves),
                  lambda result, error: self._status(
                      u'Selected {0} in Revit.'.format(len(leaves)) if not error
                      else u'Select failed - see the debug report.'))

    def _select_folder(self, heading):
        node = heading.node
        if node is None:
            return
        keys = set(leaf.key for leaf in pbp_tree.leaves_under(node, node.flat))
        if not heading.expanded:
            self._toggle(heading)
        self.list.SelectedItems.Clear()
        self._reselect(keys)

    def _rename(self):
        leaves = self._selected_leaves()
        if len(leaves) != 1 or leaves[0].tab == u'families':
            return
        leaf = leaves[0]
        current = leaf.text
        if leaf.tab == u'sheets' and u' - ' in current:
            current = current.split(u' - ', 1)[1]
        new_name = pbp_ui.ask_text(u'Rename', u'New name:', current, self.theme_name)
        if not new_name or new_name == current:
            return
        self._job(u'rename', lambda app: pbp_revit.rename_leaf(app, leaf, new_name, None),
                  self._renamed)

    def _renamed(self, result, error):
        if error or result is None or not result.get(u'ok'):
            why = result.get(u'why') if result else u'see the debug report'
            self._status(u'Rename refused: {0}'.format(why))
            return
        self._status(u'Renamed.')
        self._refresh(u'renamed')

    def _place(self, leaf):
        self._job(u'place', lambda app: pbp_revit.place_type(app, leaf),
                  lambda result, error: self._status(
                      u'Placing {0} - click in the view, Esc to finish.'.format(leaf.text)
                      if result and result.get(u'ok') else
                      u'Revit cannot place {0} from here.'.format(leaf.text)))

    def _select_instances(self, leaf):
        self._job(u'select instances', lambda app: pbp_revit.select_instances(app, leaf),
                  lambda result, error: self._status(
                      u'Selected {0} instance(s) of {1}.'.format(result[u'count'], leaf.text)
                      if result else u'Select failed - see the debug report.'))

    def _copy(self, text):
        if pbp_ui.copy_text(text):
            self._status(u'Copied.')

    # ============================================================
    # Pro Sheets
    # ============================================================
    def _print_clicked(self, sender, args):
        self._prosheets(u'print', self._selected_sheets())

    def _express_clicked(self, sender, args):
        self._prosheets(u'express', self._selected_sheets())

    def _prosheets(self, kind, sheets):
        if not sheets:
            self._status(u'Select one or more sheets first.')
            return
        if kind == u'express':
            if self.express is not None:
                self._status(u'An express print is already running.')
                return
            folder, has_hook, version = pbp_handoff.hook_state(os.path.dirname(os.path.abspath(__file__)))
            if not has_hook:
                # Without the hook Pro Sheets would only open on its first
                # page - say so instead of sending the sheets there.
                pbp_log.log(u'express: Pro Sheets {0} at {1} has no {2}'.format(
                    version or u'?', folder, pbp_handoff.HOOK_FILE))
                self._status(u'Express needs the express hook in Pro Sheets - see the message.')
                pbp_ui.message(
                    u'Express print',
                    u'Pro Sheets Exporter {0} has no express hook ({1}), so Express would only '
                    u'open Pro Sheets on its first page.\n\nGive the Pro Sheets chat the '
                    u'"Pro Sheets express hook" prompt to add it. Print still works: it opens Pro '
                    u'Sheets with the sheets ticked.'.format(version or u'', pbp_handoff.HOOK_FILE),
                    self.theme_name)
                return
            if len(sheets) > CONFIRM_EXPRESS_OVER and not pbp_ui.confirm(
                    u'Express print', u'Express print {0} sheets with the last Pro Sheets '
                    u'settings?'.format(len(sheets)), self.theme_name, ok_text=u'Print'):
                return
        folder = self.folder

        def work(app):
            return pbp_revit.prosheets(app, kind, sheets, folder)

        def done(result, error):
            self._prosheets_posted(kind, len(sheets), result, error)
        self._status(u'Sending {0} sheet(s) to Pro Sheets...'.format(len(sheets)))
        self._job(u'prosheets ' + kind, work, done)

    def _prosheets_posted(self, kind, count, result, error):
        if error or result is None:
            self._status(u'Pro Sheets could not be started - see the debug report.')
            return
        if not result.get(u'ok'):
            self._status(result.get(u'why', u'Pro Sheets could not be started.'))
            return
        if kind == u'print':
            self._status(u'Pro Sheets is opening with {0} sheet(s) ready to print.'.format(count))
            return
        now = time.time()
        self.express = {u'token': result[u'token'], u'started': now, u'count': count,
                        u'acked': False, u'last': None, u'changed': now}
        self.last_folder = u''
        self._update_toolbar()
        self._status(u'Express print: {0} sheet(s) sent to Pro Sheets.'.format(count))
        try:
            import pbp_progress
            self.progress = pbp_progress.ExpressProgress(count, self.theme_name)
            self.progress.show()
        except Exception:
            self.progress = None
            pbp_log.exc(u'express progress window')
        self.express_timer.Start()

    def _express_tick(self, sender, args):
        if self.express is None:
            self.express_timer.Stop()
            return
        self._poll_express()

    def _poll_express(self):
        u"""Read Pro Sheets' latest answer and move the progress strip on.

        Done: the strip reaches 100%, the output folder opens, the strip
        closes - nothing else is shown. Failed, never started, or stalled:
        the strip turns red and says why, and stays until closed."""
        express = self.express
        if express is None:
            return
        now = time.time()
        answer = pbp_handoff.poll(self.folder, express[u'token'])
        if pbp_handoff.waiting_too_long(express[u'started'], now, answer):
            self._express_end(u'Pro Sheets opened but did not run the express export - it needs '
                              u'the express hook (see the tool doc).', ok=False)
            pbp_log.log(u'express: no answer from Pro Sheets after {0:.0f}s'.format(
                float(pbp_handoff.ACK_TIMEOUT)))
            return
        if answer is None:
            return
        key = (answer[u'status'], answer[u'done'], answer[u'current'])
        if key != express[u'last']:
            express[u'last'] = key
            express[u'changed'] = now
            express[u'acked'] = True
            pbp_log.log(u'express: {0}'.format(answer))
        elif answer[u'status'] in pbp_handoff.LIVE and pbp_handoff.stalled(express[u'changed'], now):
            self._express_end(u'Pro Sheets stopped reporting progress - check Revit for a dialog.',
                              ok=False)
            return
        if self.progress is not None:
            import pbp_progress
            self.progress.set(pbp_handoff.percent(answer),
                              pbp_progress.detail_for(answer, express[u'count']))
        status = answer[u'status']
        if status in pbp_handoff.LIVE:
            self.status.Text = u'Express print: {0}%'.format(pbp_handoff.percent(answer))
        elif status == u'done':
            self.last_folder = answer[u'folder']
            line = u'Express print finished: {0} file(s).'.format(answer[u'files'])
            if answer[u'message']:
                # Some files written, some not: the folder still opens, and
                # what did not write is said rather than left to be found.
                line += u' ' + answer[u'message']
            self._express_end(line, ok=True)
        elif status == u'failed':
            self._express_end(u'Express print failed: {0}'.format(answer[u'message'] or u'see Pro Sheets'),
                              ok=False)

    def _express_end(self, message, ok):
        self.express = None
        self.express_timer.Stop()
        self._update_toolbar()
        self._status(message)
        if ok:
            if self.progress is not None:
                self.progress.close()
                self.progress = None
            if self.last_folder and os.path.isdir(self.last_folder):
                pbp_ui.shell_open(self.last_folder)
            elif self.last_folder:
                self._status(message + u' The folder it named is not there: ' + self.last_folder)
        elif self.progress is not None:
            self.progress.fail(message)

    def _open_folder(self, sender, args):
        if self.last_folder and os.path.isdir(self.last_folder):
            pbp_ui.shell_open(self.last_folder)
        else:
            self._status(u'That folder is not there any more.')

    # ============================================================
    # pop out
    # ============================================================
    def _pop_out(self, tab):
        placement = self._placement()
        if pbp_store.panes_registered():
            guid = pbp_panes.guid_for(tab)
            self._offer_placement(guid, placement)

            def done(result, error):
                if error or not result or not result.get(u'ok'):
                    self._float(tab, u'The {0} pane registers at the next Revit start, so it '
                                     u'opened as a floating window.'.format(pbp_tree.TAB_LABELS.get(tab)),
                                placement)
            self._job(u'show pane ' + tab, lambda app: pbp_revit.show_pane(app, guid), done)
            return
        self._float(tab, u'Dockable panes are not registered (the startup block), so {0} opened '
                         u'as a floating window.'.format(pbp_tree.TAB_LABELS.get(tab)), placement)

    # ---- Dock / Undock ----
    def _paint_dock(self):
        docked = self.host == u'pane'
        self.dock_text.Text = u'Undock' if docked else u'Dock'
        try:
            self.dock_glyph.Data = Geometry.Parse(GLYPH_UNDOCK if docked else GLYPH_DOCK)
        except Exception:
            pass
        self.dock_button.ToolTip = (
            u'Take this panel out of Revit\'s dock as a floating window' if docked else
            u'Put this browser in Revit\'s dock (sets docking up first where it never was)')

    def _dock_clicked(self, sender, args):
        if self.host == u'pane':
            self._undock()
        else:
            self._dock()

    def _undock(self):
        u"""A docked panel out as a floating window the same size, beside
        where it was; the panel is hidden (Revit has no call to float a
        docked panel itself)."""
        placement = self._placement()
        guid = self.pane_guid or pbp_panes.MAIN_GUID
        pin, tab = self.pin, self.fixed_tab

        def done(result, error):
            import pbp_window
            if pin:
                pbp_window.open_pinned(pin, placement)
            else:
                pbp_window.open_floating(tab, placement)
        self._job(u'undock', lambda app: pbp_revit.hide_pane(app, guid), done)

    def _dock(self):
        u"""A floating window into Revit's dock - its own panel shown, the
        window closed. Where Revit never took the panels (the startup.py
        block is missing on this machine), say so and offer to add it."""
        if not pbp_store.panes_registered():
            self._set_up_docking()
            return
        if self.pin:
            node = self._pinned_node()
            if node is not None:
                row = pbp_tree.Row(node.key, node.label, 0, True, node=node, tab=node.tab)
                self._pin_heading(row)
                self._close_clicked(None, None)
            return
        guid = pbp_panes.guid_for(self.fixed_tab)

        def done(result, error):
            if error or not result or not result.get(u'ok'):
                pbp_ui.message(u'Dock', u'Revit did not show the docked panel ({0}). Restart Revit - '
                                        u'a panel added in an update only registers when Revit starts.'.format(
                                            (result or {}).get(u'why', u'see the debug report')),
                               self.theme_name)
                return
            self._close_clicked(None, None)
        self._job(u'dock', lambda app: pbp_revit.show_pane(app, guid), done)

    def _set_up_docking(self):
        import pbp_startup
        here = os.path.dirname(os.path.abspath(__file__))
        what, path = pbp_startup.state(here)
        pbp_log.log(u'dock: panes not registered, startup.py is {0} ({1})'.format(what, path))
        if what == u'present':
            pbp_ui.message(
                u'Dock',
                u'The docking block is in startup.py, but Revit did not take the panels when it '
                u'started this time.\n\nRestart Revit. If it still will not dock, turn Debug on, '
                u'restart, and send the debug report - the log shows why.', self.theme_name)
            return
        if what == u'no_extension':
            pbp_ui.message(u'Dock', u'Docking needs the tool inside a .extension folder.', self.theme_name)
            return
        if not pbp_ui.confirm(
                u'Set up docking',
                u'This machine has never had docking set up: Revit only takes a dockable panel '
                u'while it starts, from a block in\n\n{0}\n\nAdd the block now? Everything already in '
                u'startup.py stays as it is, and a backup copy is kept. Then restart Revit.'.format(path),
                self.theme_name, ok_text=u'Add it'):
            return
        ok, line = pbp_startup.install(here)
        pbp_log.log(u'dock: ' + line)
        pbp_ui.message(u'Set up docking',
                       line + (u'\n\nRestart Revit, then click Dock.' if ok else u''), self.theme_name)
        self._status(line)

    def _float(self, tab, why, placement=None):
        import pbp_window
        pbp_window.open_floating(tab, placement)
        self._status(why)

    # ---- where a popped-out window goes ----
    def _placement(self):
        u"""(left, top, width, height) for a window opened from here: this
        browser's size, beside it - to its left when the screen has room,
        else to its right. In WPF units (DPI-independent). None if this
        browser is not on screen."""
        try:
            from System.Windows import Point, PresentationSource, SystemParameters
            source = PresentationSource.FromVisual(self.root)
            if source is None:
                return None
            corner = source.CompositionTarget.TransformFromDevice.Transform(
                self.root.PointToScreen(Point(0, 0)))
            return beside(corner.X, corner.Y, self.root.ActualWidth, self.root.ActualHeight,
                          SystemParameters.VirtualScreenLeft, SystemParameters.VirtualScreenWidth,
                          SystemParameters.VirtualScreenTop, SystemParameters.VirtualScreenHeight)
        except Exception:
            pbp_log.exc(u'placement')
            return None

    def _offer_placement(self, guid, placement):
        if placement:
            pbp_store.domain_set(pbp_store.PLACE_KEY + guid,
                                 u','.join(to_text(round(v, 1)) for v in placement))

    def _take_placement(self):
        u"""A pane just shown: if a browser asked for it to go somewhere,
        size and move the floating window Revit put it in. A docked pane is
        left where Revit docked it."""
        if not self.pane_guid:
            return
        key = pbp_store.PLACE_KEY + self.pane_guid
        text = pbp_store.domain_get(key)
        if not text:
            return
        pbp_store.domain_set(key, None)
        try:
            left, top, width, height = [float(v) for v in to_text(text).split(u',')]
            from System.Windows import Window, SystemParameters
            window = Window.GetWindow(self.root)
            kind = window.GetType().FullName if window is not None else u'none'
            if window is None or window.ActualWidth >= SystemParameters.VirtualScreenWidth * 0.8:
                pbp_log.log(u'placement: pane is docked ({0}) - left where Revit put it'.format(kind))
                return
            window.Left, window.Top = left, top
            window.Width, window.Height = width, height
            pbp_log.log(u'placement: {0} to {1}'.format(kind, text))
        except Exception:
            pbp_log.exc(u'take placement')

    # ============================================================
    # theme, zoom, debug
    # ============================================================
    def _cycle_theme(self, sender, args):
        self.theme_mode = pbp_theme.next_mode(self.theme_mode)
        self.settings[u'theme'] = self.theme_mode
        pbp_settings.save(self.folder, self.settings)
        self._paint_theme_chip()
        self._apply_theme(pbp_theme.resolve(self.theme_mode))

    def _apply_theme(self, name):
        if name == self.theme_name:
            return
        self.theme_name = name
        pbp_theme.apply(self.root, name)
        for menu in self.menus:
            pbp_theme.apply(menu, name)
        if self.window is not None:
            self.window.apply_theme(name)
        self._render()
        pbp_log.log(u'theme now {0} ({1})'.format(name, self.theme_mode))

    def _wheel(self, sender, args):
        if (Keyboard.Modifiers & ModifierKeys.Control) != ModifierKeys.Control:
            return
        args.Handled = True
        step = ZOOM_STEP if args.Delta > 0 else -ZOOM_STEP
        self._apply_zoom(self.zoom + step)

    def _apply_zoom(self, value, save=True):
        self.zoom = round(float(clamp(value, ZOOM_MIN, ZOOM_MAX)), 2)
        self.scale.ScaleX = self.zoom
        self.scale.ScaleY = self.zoom
        self.zoom_text.Text = u'{0}%'.format(int(round(self.zoom * 100)))
        if save:
            self.settings[u'zoom'] = to_text(self.zoom)
            pbp_settings.save(self.folder, self.settings)

    def _root_key(self, sender, args):
        ctrl = (Keyboard.Modifiers & ModifierKeys.Control) == ModifierKeys.Control
        if ctrl and args.Key in (Key.D0, Key.NumPad0):
            args.Handled = True
            self._apply_zoom(1.0)
        elif ctrl and args.Key == Key.F:
            args.Handled = True
            self.search.Focus()
            self.search.SelectAll()
        elif args.Key == Key.F5:
            args.Handled = True
            self._refresh(u'F5')
        elif args.Key == Key.F11 and self.window is not None:
            args.Handled = True
            self._full_clicked(None, None)
        elif args.Key == Key.Escape and self.search.IsKeyboardFocused and self.search.Text:
            args.Handled = True
            self.search.Text = u''

    def _debug_changed(self, sender, args):
        on = bool(self.debug_tick.IsChecked)
        pbp_log.set_enabled(on)
        self.settings[u'debug'] = u'1' if on else u'0'
        pbp_settings.save(self.folder, self.settings)
        pbp_log.log(u'debug log {0}'.format(u'on' if on else u'off'))

    def report_lines(self):
        snap = self.snapshot
        lines = [
            u'tool: {0} v{1}'.format(TOOL_NAME, __version__),
            u'host: {0}, fixed tab: {1}, current tab: {2}'.format(
                self.host, self.fixed_tab or u'-', self.tab),
            u'revit: {0}'.format(snap.revit_version if snap is not None else u'?'),
            u'engine: {0}'.format(_engine()),
            u'assemblies missing: {0}'.format(u', '.join(pbp_clr.MISSING) or u'none'),
            u'panes registered: {0}, hooks: {1}'.format(
                pbp_store.panes_registered(),
                to_text(pbp_store.domain_get(u'RevoBIM.PBP.hooks', u'none'))),
            u'theme: mode={0} showing={1} revit canvas={2}'.format(
                self.theme_mode, self.theme_name, pbp_theme.read_revit_theme()),
            u'runner: ' + self.runner.describe(),
            u'store: reads={0} change reads={1} reading={2} dirty={3}/{4} last fill: {5}'.format(
                self.store.reads, self.store.change_reads, self.store.reading,
                self.store.read_dirty, pbp_store.dirty_count(), self.last_fill),
            u'last read: {0}'.format(pbp_revit.timing_text(snap) if snap is not None else u'-'),
            u'zoom: {0}  colour: {1}  search: {2}'.format(
                self.zoom, self.colour_mode, u' '.join(self.search_words) or u'-'),
            u'rows showing: {0}  selected: {1}'.format(len(self.rows), len(self._selected_rows())),
            u'express: {0}  last folder: {1}'.format(self.express, self.last_folder or u'-'),
            u'pin: slot {0} {1}  sync to Revit: {2}'.format(self.pin_slot, self._pin_line() or u'-',
                                                          self.sync),
        ]
        if snap is not None:
            marks = self._marks()
            lines.append(u'marks: {0} favourite(s), {1} coloured, {2} grouped panel(s) in {3}, '
                         u'sheet set {4!r} of {5}'.format(
                             len(marks.favs), len(marks.colours), len(marks.groups),
                             marks.group_names(), marks.sheet_set, sorted(snap.sheet_sets)))
        if snap is not None:
            lines.append(u'project: {0}  read {1} ms  counts {2}'.format(
                snap.title, snap.ms, snap.counts()))
            for tab in pbp_settings.ORGANISABLE + pbp_settings.FAV_ORGS:
                lines.append(u'organisation {0}: {1}  (revit: {2})'.format(
                    tab, self._org(tab), snap.revit_names.get(tab, u'')))
            lines.append(u'read problems: {0}'.format(len(snap.errors)))
            for text in snap.errors[:3]:
                lines.append(text.strip().splitlines()[-1] if text.strip() else u'')
        return lines

    def _copy_report(self, sender, args):
        if pbp_ui.copy_text(pbp_log.report(self.report_lines())):
            self._status(u'Debug report copied - paste it into the chat with Claude.')

    def _open_log(self, sender, args):
        path = pbp_log.log_path()
        if not os.path.isfile(path):
            pbp_log.log(u'log opened')
        if not pbp_ui.shell_open(path):
            self._status(u'The log is at ' + path)

    # ============================================================
    # window hosting
    # ============================================================
    def _header_down(self, sender, args):
        if self.window is None:
            return
        if args.ClickCount == 2:
            self._full_clicked(None, None)
            return
        self.window.drag()

    def _full_clicked(self, sender, args):
        if self.window is not None:
            self.window.toggle_full()

    def _close_clicked(self, sender, args):
        if self.window is not None:
            self.window.close()

    def dispose(self):
        try:
            self.timer.Stop()
        except Exception:
            pass
        self.store.unsubscribe(self._on_snapshot)

    # ============================================================
    # the clock: refresh, theme follow, express, watchdog
    # ============================================================
    def _visible_changed(self, sender, args):
        if self.root.IsVisible:
            if self.snapshot is not None:
                self._paint_counts()
            if self.stale and self.snapshot is not None:
                # changes came while hidden: draw them once, now
                self.stale = False
                self._render()
            self._tick(None, None)
            if self.pane_guid:
                # once Revit has the pane's window laid out
                try:
                    self.root.Dispatcher.BeginInvoke(DispatcherPriority.Loaded,
                                                     Action(self._take_placement))
                except Exception:
                    self._take_placement()

    def _check_pins(self):
        if self.pin_slot is None:
            return
        pins = pbp_store.pins_count()
        if pins != self.last_pins:
            self.last_pins = pins
            self._repin()

    def _tick(self, sender, args):
        self.ticks += 1
        now = time.time()
        self._check_pins()
        if pbp_store.settings_count() != self.last_settings:
            self._reload_settings()
        if self.runner.stalled(now):
            self.runner.kick()
        if self.theme_mode == u'follow' and self.ticks % 3 == 0:
            self._apply_theme(pbp_theme.resolve(u'follow'))
        if not self.root.IsVisible or not self.runner.ready():
            return
        dirty = pbp_store.dirty_count()
        if dirty != self.last_dirty:
            self.last_dirty = dirty
            self.dirty_since = now
        if self.store.snapshot is None:
            if not self.store.reading:
                self.store.request_read(self.runner, u'first show')
            return
        if self.dirty_since and now - self.dirty_since >= REFRESH_SETTLE:
            self.dirty_since = 0.0
            self.store.refresh(self.runner, u'model changed')
            return
        if self.store.read_dirty != dirty and not self.dirty_since and not self.store.reading:
            self.store.refresh(self.runner, u'catch up')
            return
        views = pbp_store.views_count()
        if views != self.last_views and self.store.request_views(self.runner):
            # kept until the store takes it: a view closed during a read is
            # asked about after it, not lost
            self.last_views = views


# ============================================================
# helpers
# ============================================================

PLACE_GAP = 8


def beside(left, top, width, height, screen_left, screen_width, screen_top, screen_height):
    u"""Where a window the size of this one goes beside it: on its left
    when that fits on the screens, else on its right, else as far over as
    fits. Same top, kept on screen."""
    width = max(300.0, float(width))
    height = max(360.0, float(height))
    x = left - width - PLACE_GAP
    if x < screen_left:
        x = left + width + PLACE_GAP
        if x + width > screen_left + screen_width:
            x = max(screen_left, screen_left + screen_width - width)
    y = min(max(top, screen_top), max(screen_top, screen_top + screen_height - height))
    return (float(x), float(y), width, height)


def sheets_of_rows(rows):
    u"""The sheets in these rows, each once: sheet rows themselves, and
    every sheet under a heading row."""
    seen = set()
    out = []
    for row in rows:
        if row.heading and row.node is not None:
            leaves = pbp_tree.leaves_under(row.node, row.node.flat)
        elif row.leaf is not None and row.on_sheet is None:
            leaves = [row.leaf]
        else:
            leaves = []
        for leaf in leaves:
            if leaf.tab == u'sheets' and leaf.key not in seen:
                seen.add(leaf.key)
                out.append(leaf)
    return out


def legend_master(leaf):
    u"""The Legends and Drafting Views tab's fixed top folder for a leaf."""
    return (pbp_tree.DRAFTING if leaf.kind == u'drafting' else pbp_tree.LEGENDS,)


def org_key(node):
    u"""Whose organisation a folder is grouped by: its tab's, or its type's
    favourites' ('fav.views')."""
    return getattr(node, u'org_key', None) or node.tab


def fav_sub(value):
    u"""The saved Favourites type, or all for anything else."""
    value = to_text(value)
    return value if value in FAV_TABS else u'all'


def legend_sub(value):
    u"""The saved sub tab, or Legends for anything else."""
    value = to_text(value)
    return value if value in pbp_tree.MASTERS else pbp_tree.LEGENDS


def is_master(node):
    return (node is not None and node.tab == u'legends' and node.level == 1
            and node.label in MASTER_ICONS)


def mouse_screen():
    u"""Where the mouse is, in screen pixels - as Revit measures its
    drawing area."""
    try:
        from System.Windows.Forms import Control
        position = Control.MousePosition
        return (float(position.X), float(position.Y))
    except Exception:
        return None


def plural(count, word):
    return u'{0} {1}{2}'.format(count, word, u'' if count == 1 else u's')


def no_modifiers():
    u"""No Ctrl / Shift / Alt held. (ModifierKeys.None cannot be written:
    None is a keyword in Python, so the flags are read as a number.)"""
    try:
        return int(Keyboard.Modifiers) == 0
    except Exception:
        return True


def rename_parts(leaf, text):
    u"""(new name, new number) from what was typed over a row - None for
    a part that did not change. A sheet's row reads 'NUMBER - NAME'; typing
    over either half changes that half, and text with no ' - ' is a name."""
    text = to_text(text).strip()
    if leaf.tab != u'sheets':
        return (text if text and text != leaf.text else None), None
    old_name = leaf.text.split(u' - ', 1)[1] if u' - ' in leaf.text else leaf.text
    if u' - ' in text:
        number, name = [part.strip() for part in text.split(u' - ', 1)]
    else:
        number, name = leaf.number, text
    return ((name if name and name != old_name else None),
            (number if number and number != leaf.number else None))


def _thickness(left, top, right, bottom):
    from System.Windows import Thickness
    return Thickness(left, top, right, bottom)


def _below():
    from System.Windows.Controls.Primitives import PlacementMode
    return PlacementMode.Bottom


def _centre():
    from System.Windows import VerticalAlignment
    return VerticalAlignment.Center


def _seconds(value):
    from System import TimeSpan
    return TimeSpan.FromSeconds(value)


def clr_type(name):
    u"""A System.Type for a DataTable column, whichever way this IronPython
    wants it handed over."""
    import System
    value = System.Double if name == u'double' else System.String
    try:
        import clr
        return clr.GetClrType(value)
    except Exception:
        return value


def _engine():
    try:
        import sys
        return to_text(sys.version).splitlines()[0]
    except Exception:
        return u'?'
