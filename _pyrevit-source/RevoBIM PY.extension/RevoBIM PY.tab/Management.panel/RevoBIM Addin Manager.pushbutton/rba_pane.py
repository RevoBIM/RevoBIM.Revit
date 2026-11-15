# -*- coding: utf-8 -*-
u"""RevoBIM Addin Manager - the panel itself, and what the button does.

One control, two hosts. Docked, it sits in the pane Revit was given at start
up (`rba_dock`), Revit owns the frame, and the window controls in its header
stay collapsed. Floating, it is the whole of a borderless window
(`rba_window`), its header is that window's header, and shrunk to the taskbar
its header is the bar left floating.

Rows are built as WPF elements in code rather than bound to Python objects -
binding to IronPython objects is unreliable across engine versions.
"""

import rba_clr  # noqa: F401

import os

from System import TimeSpan
from System.IO import FileSystemWatcher, NotifyFilters
from System.Windows import Thickness, CornerRadius, FontWeights, GridLength
from System.Windows import TextTrimming, TextWrapping
from System.Windows import HorizontalAlignment, VerticalAlignment, Visibility
from System.Windows.Controls import (Border, Grid, StackPanel, TextBlock, Image,
                                     ColumnDefinition, ToolTip, Orientation)
from System.Windows.Media import FontFamily, Stretch
from System.Windows.Shapes import Path as WpfPath
from System.Windows.Media import Geometry
from System.Windows.Threading import DispatcherTimer
from System.Windows.Input import Cursors, Key

import rba_core
import rba_dock
import rba_favs
import rba_scan
import rba_launch
import rba_menu
import rba_qat
import rba_settings
import rba_theme
import rba_ui
import rba_window

# Every module the panel will ever reach is imported HERE, at the top, never
# inside a handler. The docked panel lives in pyRevit's start up engine, whose
# sys.path is reset once startup.py has run - a module first imported from a
# click handler hours later is not found. Imported now, each sits in
# sys.modules and the reset cannot touch it.

from rba_core import to_text, log, log_exception

SEARCH_DEBOUNCE_MS = 220
THEME_RECHECK_MS = 2500

CHEVRON_CLOSED = u"M 0,0 L 5,4.5 L 0,9 Z"
CHEVRON_OPEN = u"M 0,1 L 9,1 L 4.5,7 Z"

# ----------------------------------------------------------------------
# the pane
# ----------------------------------------------------------------------

class AddinsPane(object):

    def __init__(self, mode=u"window"):
        u"""mode is "pane" when Revit docks it, "window" when floating."""
        self.mode = mode
        self.host_window = None      # the floating Window, when there is one
        self.host_drawer = None      # and its drawer, which dialogs park with
        self.theme_listeners = []    # the host repaints its own frame here
        self.settings = rba_core.load_settings()
        rba_core.set_debug(rba_core.as_bool(self.settings, u"debug"))
        # Write back at once, so a migration done on reading (1.5.1 rebuilds
        # the favourites saved as fragments) is kept even if nothing else is
        # changed this session.
        rba_core.save_settings(self.settings)
        self.items = []
        self.groups = []
        self.collapsed = {}
        for key in rba_core.as_list(self.settings, u"collapsed"):
            self.collapsed[key] = True
        self.theme_name = u"dark"
        self.dirty = False
        self.settings_stamp = rba_core.settings_stamp()
        self.watchers = []
        self.first_read_done = False
        self.control = rba_ui.load_xaml(u"RevoBIMAddins.xaml")
        self._wire()
        self.apply_theme()
        # No scan here.  The pane is built during Revit's start up, at a point
        # where pyRevit has not finished building the ribbon, so matching the
        # folder walk against the live ribbon would mark every addin as not
        # loaded.  The first read happens when the pane is first shown.
        self.set_status(u"Reading the addins folder...")

    # ---------------------------------------------------------------- wiring

    def find(self, name):
        return self.control.FindName(name)

    def _wire(self):
        self.search_box = self.find(u"SearchBox")
        self.list_panel = self.find(u"ListPanel")
        self.status_text = self.find(u"StatusText")
        self.version_text = self.find(u"VersionText")
        self.theme_btn = self.find(u"ThemeBtn")
        self.settings_btn = self.find(u"SettingsBtn")
        self.logo_block = self.find(u"LogoBlock")

        self.version_text.Text = u"v" + rba_core.__version__

        self.search_box.TextChanged += self.on_search_changed
        self.theme_btn.Click += self.on_theme_click
        self.settings_btn.Click += self.on_settings_click
        self.fold_btn = self.find(u"FoldBtn")
        self.fold_btn.Click += self.on_fold
        self.fav_btn = self.find(u"FavBtn")
        self.fav_btn.Click += self.on_fav_view
        self.labels_btn = self.find(u"LabelsBtn")
        self.labels_btn.Click += self.on_labels
        self.search_row = self.find(u"SearchRow")
        self.fav_panel = self.find(u"FavPanel")
        self.favs = rba_favs.FavGrid(self, self.fav_panel)
        self.find(u"SmallerBtn").Click += self.on_smaller
        self.find(u"BiggerBtn").Click += self.on_bigger
        self.find(u"RefreshBtn").Click += self.on_refresh
        self.footer = self.find(u"Footer")
        self.footer_btn = self.find(u"FooterBtn")
        self.footer_btn.Click += self.on_footer_click
        self.apply_footer()
        self.control.KeyDown += self.on_key
        self.control.Loaded += self.on_loaded
        self.control.IsVisibleChanged += self.on_visible_changed

        self.search_timer = DispatcherTimer()
        self.search_timer.Interval = TimeSpan.FromMilliseconds(SEARCH_DEBOUNCE_MS)
        self.search_timer.Tick += self.on_search_tick

        self.watch_timer = DispatcherTimer()
        self.watch_timer.Interval = TimeSpan.FromMilliseconds(
            max(400, rba_core.as_int(self.settings, u"watch_ms", 1500)))
        self.watch_timer.Tick += self.on_watch_tick
        self.watch_timer.Start()

        # Auto follows Revit's canvas theme, which can be changed while the
        # pane is open.  Re-read it on a slow timer rather than hunting for a
        # ThemeChanged event that does not exist on every release in range.
        self.theme_timer = DispatcherTimer()
        self.theme_timer.Interval = TimeSpan.FromMilliseconds(THEME_RECHECK_MS)
        self.theme_timer.Tick += self.on_theme_tick
        self.theme_timer.Start()

        rba_ui.attach_easter_egg(self.logo_block,
                                 lambda: self.control,
                                 lambda: self.theme_name)

    # ---------------------------------------------------------------- pins

    def save_settings(self):
        rba_core.save_settings(self.settings)
        self.settings_stamp = rba_core.settings_stamp()

    def pinned_keys(self):
        return rba_core.as_list(self.settings, u"pinned")

    def toggle_pin(self, item):
        keys = self.pinned_keys()
        if item.key in keys:
            keys = [key for key in keys if key != item.key]
            note = u"{0} unpinned".format(item.title)
        else:
            keys.append(item.key)
            note = u"{0} pinned to the top".format(item.title)
        rba_core.set_list(self.settings, u"pinned", keys)
        self.save_settings()
        self.render()
        self.set_status(note)

    def pinned_items(self):
        u"""In the order they were pinned, not alphabetically.

        A pinned list is a list somebody arranged; re-sorting it every render
        would move things out from under the hand that reaches for them.
        """
        by_key = {}
        for item in self.items:
            by_key[item.key] = item
        out = []
        for key in self.pinned_keys():
            if key in by_key:
                out.append(by_key[key])
        return out

    def stop(self):
        u"""Let go of the timers and watchers.

        Called on a pane that turned out not to be needed - one built for a
        registration Revit then would not honour. Left running, its watch timer
        would rescan the extensions folder every second and a half for the rest
        of the session with nothing on screen to show for it.
        """
        for timer in (getattr(self, u"watch_timer", None),
                      getattr(self, u"theme_timer", None),
                      getattr(self, u"search_timer", None)):
            try:
                timer.Stop()
            except Exception:
                pass
        for watcher in self.watchers:
            try:
                watcher.EnableRaisingEvents = False
                watcher.Dispose()
            except Exception:
                pass
        self.watchers = []

    def on_visible_changed(self, sender, args):
        u"""Re-read whenever the docked pane is shown again.

        The button that shows a docked pane runs in its own engine and cannot
        reach this one to ask for a rescan - so the pane notices for itself.
        A tool folder may have been added since, and a pyRevit reload rebuilds
        the ribbon with new command ids behind the same captions.
        """
        try:
            # Docked only: a floating window has just read the folder as it
            # opened, and an owned window hides and returns every time Revit
            # is minimised and restored.
            if self.mode == u"pane" and self.first_read_done and bool(args.NewValue):
                self.rescan()
        except Exception:
            log_exception(u"on_visible_changed")

    def on_loaded(self, sender, args):
        u"""The first time Revit actually shows the pane, read the folder.

        Loaded is a Direct routed event and fires on the control itself, which
        is exactly what is wanted here: it is the first moment the ribbon is
        certain to exist.
        """
        if self.first_read_done:
            return
        self.first_read_done = True
        self.rescan()

    # ---------------------------------------------------------------- theme

    def res(self, key):
        try:
            found = self.control.TryFindResource(key)
            if found is not None:
                return found
        except Exception:
            pass
        return None

    def apply_theme(self):
        mode = to_text(self.settings.get(u"theme", u"auto"))
        self.theme_name = rba_theme.resolve(mode)
        rba_theme.apply(self.control, self.theme_name)
        # The button is a glyph, not a word: show the one for the live mode.
        try:
            for name, glyph_mode in ((u"ThemeAutoGlyph", u"auto"),
                                     (u"ThemeDarkGlyph", u"dark"),
                                     (u"ThemeLightGlyph", u"light")):
                self.find(name).Visibility = (Visibility.Visible if mode == glyph_mode
                                              else Visibility.Collapsed)
            self.theme_btn.ToolTip = {
                u"auto": u"Theme: Auto - follows Revit's canvas. Click for Dark.",
                u"dark": u"Theme: Dark. Click for Light.",
                u"light": u"Theme: Light. Click for Auto.",
            }.get(mode, u"Theme")
        except Exception:
            log_exception(u"theme glyph")
        # The floating window paints its own frame and grips; a palette
        # written only onto this control would leave them the old colour.
        for listener in list(self.theme_listeners):
            try:
                listener(self.theme_name)
            except Exception:
                log_exception(u"theme listener")

    def on_theme_click(self, sender, args):
        try:
            mode = rba_theme.next_mode(self.settings.get(u"theme", u"auto"))
            self.settings[u"theme"] = mode
            self.save_settings()
            self.apply_theme()
            self.render()
        except Exception:
            log_exception(u"on_theme_click")

    def on_theme_tick(self, sender, args):
        try:
            if to_text(self.settings.get(u"theme", u"auto")).lower() != u"auto":
                return
            wanted = rba_theme.resolve(u"auto")
            if wanted != self.theme_name:
                log(u"theme: Revit moved to {0}".format(wanted))
                self.apply_theme()
                self.render()
        except Exception:
            log_exception(u"on_theme_tick")

    # ---------------------------------------------------------------- scan

    def roots(self):
        return rba_scan.resolve_roots(self.settings.get(u"folders", u""))

    def rescan(self):
        try:
            roots = self.roots()
            self.items = rba_scan.scan(roots, self.settings.get(u"name_filter", u""))
            rba_launch.attach_live(self.items)
            self.apply_qat()
            self.rebuild_watchers(roots)
            self.render()
        except Exception:
            log_exception(u"rescan")
            self.set_status(u"Could not read the addins folder - see the debug log")

    def apply_qat(self):
        u"""Put the pinned toolbar buttons back.

        Revit rebuilds its own Quick Access Toolbar from UIState.dat at start
        up and knows nothing about this list, so it is re-applied every time
        the panel reads the folder.
        """
        keys = rba_core.as_list(self.settings, u"qat")
        if not keys:
            return
        try:
            rba_qat.reapply(self.items, keys)
        except Exception:
            log_exception(u"apply_qat")

    def rebuild_watchers(self, roots):
        for watcher in self.watchers:
            try:
                watcher.EnableRaisingEvents = False
                watcher.Dispose()
            except Exception:
                pass
        self.watchers = []
        if not rba_core.as_bool(self.settings, u"watch"):
            return
        for root in roots:
            try:
                watcher = FileSystemWatcher(root)
                watcher.IncludeSubdirectories = True
                watcher.NotifyFilter = NotifyFilters.DirectoryName | NotifyFilters.FileName
                # The watcher raises on a worker thread, so it only ever sets a
                # flag; the dispatcher timer does the read.  Marshalling a
                # rescan onto the UI thread from here is the same class of bug
                # as reading the document inside DocumentChanged.
                watcher.Created += self.on_folder_changed
                watcher.Deleted += self.on_folder_changed
                watcher.Renamed += self.on_folder_changed
                watcher.EnableRaisingEvents = True
                self.watchers.append(watcher)
            except Exception:
                log_exception(u"rebuild_watchers/{0}".format(root))

    def on_folder_changed(self, sender, args):
        self.dirty = True

    def on_watch_tick(self, sender, args):
        stamp = rba_core.settings_stamp()
        if stamp != self.settings_stamp:
            self.settings_stamp = stamp
            log(u"watch: settings changed on disk, reloading")
            self.reload_settings()
            return
        if not self.dirty:
            return
        self.dirty = False
        log(u"watch: folder changed, re-reading")
        self.rescan()

    def reload_settings(self, from_disk=True):
        if from_disk:
            self.settings = rba_core.load_settings()
        self.apply_footer()
        rba_core.set_debug(rba_core.as_bool(self.settings, u"debug"))
        rba_ui.clear_icon_cache()
        self.watch_timer.Interval = TimeSpan.FromMilliseconds(
            max(400, rba_core.as_int(self.settings, u"watch_ms", 1500)))
        self.apply_theme()
        self.rescan()

    # ---------------------------------------------------------------- search

    def on_search_changed(self, sender, args):
        self.search_timer.Stop()
        self.search_timer.Start()

    def on_search_tick(self, sender, args):
        self.search_timer.Stop()
        self.render()

    # ---------------------------------------------------------------- render

    def icon_size(self):
        size = rba_core.as_int(self.settings, u"icon_size", 32)
        if size not in rba_core.ICON_SIZES:
            size = 32
        return size

    def render(self):
        u"""Name matches first, grouped as usual; what-it-does matches below.

        Two passes over one filtered list rather than one pooled search, so a
        description hit can never sit above an exact name match.
        """
        self.apply_view()
        if self.in_favourites():
            try:
                count = self.favs.render()
                self.set_status(u"{0} favourite{1} - drag to reorder".format(
                    count, u"" if count == 1 else u"s") if count else
                    u"No favourites yet")
            except Exception:
                log_exception(u"render favourites")
            return
        try:
            self.list_panel.Children.Clear()
            search = to_text(self.search_box.Text)
            searching = bool(search.strip())
            primary, secondary = rba_scan.search_split(
                self.items, search,
                hide_unloaded=rba_core.as_bool(self.settings, u"hide_unloaded"))
            self.groups = rba_scan.group_items(
                primary,
                group_by=to_text(self.settings.get(u"group_by", u"panel")))
            shown = 0
            self.drawn_keys = []

            pinned = [] if searching else self.pinned_items()
            if pinned:
                group = rba_scan.Group(u"__pinned__", u"Pinned", u"")
                group.items = pinned
                self.drawn_keys.append(group.key)
                collapsed = self.collapsed.get(group.key, False)
                self.list_panel.Children.Add(
                    self.build_group_header(group, collapsed, accent=True))
                if not collapsed:
                    for item in pinned:
                        self.list_panel.Children.Add(self.build_row(item))
            for group in self.groups:
                self.drawn_keys.append(group.key)
                collapsed = (not searching) and self.collapsed.get(group.key, False)
                self.list_panel.Children.Add(self.build_group_header(group, collapsed))
                if collapsed:
                    continue
                for item in group.items:
                    self.list_panel.Children.Add(self.build_row(item))
                    shown += 1
            if secondary:
                self.list_panel.Children.Add(self.build_section_header(
                    u"Matches what they do", len(secondary)))
                for item in secondary:
                    self.list_panel.Children.Add(self.build_row(item, detail=True))
                    shown += 1
            if not self.groups and not secondary:
                self.list_panel.Children.Add(self.build_empty_note(searching))
            self.report(shown, len(secondary))
            self.update_fold_button()
        except Exception:
            log_exception(u"render")

    def report(self, shown, by_description=0):
        total = len(self.items)
        unloaded = len([item for item in self.items if not item.live])
        parts = [u"{0} addins in {1} groups".format(total, len(self.groups))]
        if shown != total:
            parts = [u"{0} of {1} addins".format(shown, total)]
            if by_description:
                parts.append(u"{0} by description".format(by_description))
        if unloaded:
            parts.append(u"{0} not on the ribbon".format(unloaded))
        self.set_status(u"  -  ".join(parts))

    def build_section_header(self, text, count):
        u"""The divider between the name matches and the description matches."""
        border = Border()
        border.Background = self.res(u"BgWindow")
        border.Padding = Thickness(1, 6, 1, 4)
        border.Margin = Thickness(0, 10, 0, 2)
        border.BorderBrush = self.res(u"BrdEdge")
        border.BorderThickness = Thickness(0, 1, 0, 0)

        stack = StackPanel()
        stack.Orientation = Orientation.Horizontal
        tick = Border()
        tick.Width = 4
        tick.Height = 13
        tick.CornerRadius = CornerRadius(2)
        tick.Background = self.res(u"AccOrange")
        tick.Margin = Thickness(0, 0, 7, 0)
        tick.VerticalAlignment = VerticalAlignment.Center
        stack.Children.Add(tick)

        label = TextBlock()
        label.Text = u"{0}  ({1})".format(text, count)
        label.Foreground = self.res(u"FgMuted")
        label.FontFamily = FontFamily(u"Segoe UI")
        label.FontSize = 11.5
        label.VerticalAlignment = VerticalAlignment.Center
        stack.Children.Add(label)

        border.Child = stack
        return border

    def set_status(self, text):
        try:
            self.status_text.Text = to_text(text)
        except Exception:
            pass

    def build_empty_note(self, searching):
        label = TextBlock()
        if searching:
            label.Text = u"Nothing matches that."
        else:
            label.Text = (u"No addins found. Point the tool at your pyRevit "
                          u"extensions folder in Settings.")
        label.TextWrapping = TextWrapping.Wrap
        label.Foreground = self.res(u"FgMuted")
        label.FontFamily = FontFamily(u"Segoe UI")
        label.FontSize = 12
        label.Margin = Thickness(6, 14, 6, 6)
        return label

    def build_group_header(self, group, collapsed, accent=False):
        border = Border()
        border.Background = self.res(u"BgCard")
        border.CornerRadius = CornerRadius(3)
        border.Padding = Thickness(7, 5, 7, 5)
        border.Margin = Thickness(0, 7, 0, 2)
        border.Cursor = Cursors.Hand

        grid = Grid()
        grid.ColumnDefinitions.Add(ColumnDefinition())
        grid.ColumnDefinitions[0].Width = GridLength(14)
        grid.ColumnDefinitions.Add(ColumnDefinition())
        grid.ColumnDefinitions.Add(ColumnDefinition())
        grid.ColumnDefinitions[2].Width = GridLength.Auto

        chevron = WpfPath()
        chevron.Data = Geometry.Parse(CHEVRON_CLOSED if collapsed else CHEVRON_OPEN)
        chevron.Fill = self.res(u"AccOrange" if collapsed else u"FgMuted")
        chevron.VerticalAlignment = VerticalAlignment.Center
        chevron.HorizontalAlignment = HorizontalAlignment.Left
        Grid.SetColumn(chevron, 0)
        grid.Children.Add(chevron)

        title = TextBlock()
        title.Text = group.title
        title.Foreground = self.res(u"AccOrange" if accent else u"FgText")
        title.FontFamily = FontFamily(u"Segoe UI")
        title.FontSize = 12.5
        title.FontWeight = FontWeights.SemiBold
        title.TextTrimming = TextTrimming.CharacterEllipsis
        title.VerticalAlignment = VerticalAlignment.Center
        Grid.SetColumn(title, 1)
        grid.Children.Add(title)

        count = TextBlock()
        count.Text = to_text(len(group.items))
        count.Foreground = self.res(u"FgMuted")
        count.FontFamily = FontFamily(u"Segoe UI")
        count.FontSize = 11
        count.VerticalAlignment = VerticalAlignment.Center
        count.Margin = Thickness(6, 0, 0, 0)
        Grid.SetColumn(count, 2)
        grid.Children.Add(count)

        border.Child = grid
        if group.subtitle:
            tip = ToolTip()
            tip.Content = group.subtitle
            border.ToolTip = tip

        def on_click(sender, args, key=group.key):
            self.toggle_group(key)

        border.MouseLeftButtonUp += on_click
        return border

    def toggle_group(self, key):
        self.collapsed[key] = not self.collapsed.get(key, False)
        rba_core.set_list(self.settings, u"collapsed",
                          [k for k in self.collapsed if self.collapsed[k]])
        self.save_settings()
        self.render()

    def build_row(self, item, detail=False):
        size = self.icon_size()
        border = Border()
        border.Background = self.res(u"BgWindow")
        border.CornerRadius = CornerRadius(3)
        border.Padding = Thickness(7, 4, 7, 4)
        border.Margin = Thickness(2, 1, 0, 1)
        border.Cursor = Cursors.Hand

        grid = Grid()
        grid.ColumnDefinitions.Add(ColumnDefinition())
        grid.ColumnDefinitions[0].Width = GridLength(size + 8)
        grid.ColumnDefinitions.Add(ColumnDefinition())

        icon_path = item.icon
        if self.theme_name == u"dark" and item.icon_dark:
            icon_path = item.icon_dark
        source = rba_ui.load_image(icon_path, size)
        if source is not None:
            picture = Image()
            picture.Source = source
            picture.Width = size
            picture.Height = size
            picture.Stretch = Stretch.Uniform
            picture.HorizontalAlignment = HorizontalAlignment.Left
            picture.VerticalAlignment = VerticalAlignment.Center
            visual = picture
        else:
            visual = rba_ui.initial_glyph(item.title, size,
                                          self.res(u"BgCard"), self.res(u"FgMuted"))
            visual.HorizontalAlignment = HorizontalAlignment.Left
            visual.VerticalAlignment = VerticalAlignment.Center
        Grid.SetColumn(visual, 0)
        grid.Children.Add(visual)

        stack = StackPanel()
        stack.VerticalAlignment = VerticalAlignment.Center
        Grid.SetColumn(stack, 1)

        label = TextBlock()
        label.Text = item.title
        label.Foreground = self.res(u"FgText" if item.live else u"FgMuted")
        label.FontFamily = FontFamily(u"Segoe UI")
        label.FontSize = 12.5
        label.TextTrimming = TextTrimming.CharacterEllipsis
        stack.Children.Add(label)

        snippet = u""
        if detail:
            snippet = item.description or item.tooltip
            if len(snippet) > 90:
                snippet = snippet[:88] + u".."
        if item.parent or snippet or not item.live:
            sub = TextBlock()
            if not item.live:
                sub.Text = u"not loaded - reload pyRevit"
                sub.Foreground = self.res(u"AccOrange")
            elif snippet:
                sub.Text = snippet
                sub.Foreground = self.res(u"FgMuted")
            else:
                sub.Text = item.parent
                sub.Foreground = self.res(u"FgMuted")
            sub.FontFamily = FontFamily(u"Segoe UI")
            sub.FontSize = 10.5
            sub.TextTrimming = TextTrimming.CharacterEllipsis
            stack.Children.Add(sub)

        grid.Children.Add(stack)
        border.Child = grid

        if rba_core.as_bool(self.settings, u"show_tooltips"):
            lines = []
            if item.tooltip:
                lines.append(item.tooltip)
            lines.append(u"{0} > {1}".format(item.tab, item.panel))
            if rba_core.as_bool(self.settings, u"show_paths"):
                lines.append(item.folder)
            tip = ToolTip()
            tip.Content = u"\n".join(lines)
            border.ToolTip = tip

        hover = self.res(u"BgHover")
        rest = self.res(u"BgWindow")

        def on_enter(sender, args):
            sender.Background = hover

        def on_leave(sender, args):
            sender.Background = rest

        def on_click(sender, args, entry=item):
            self.launch(entry)

        def on_context(sender, args, entry=item):
            try:
                menu = rba_menu.build(self, entry)
                menu.PlacementTarget = sender
                menu.IsOpen = True
                args.Handled = True
            except Exception:
                log_exception(u"row/context")
                self.set_status(u"The menu would not open - see the debug log")

        border.MouseEnter += on_enter
        border.MouseLeave += on_leave
        border.MouseLeftButtonUp += on_click
        border.MouseRightButtonUp += on_context
        return border

    # ---------------------------------------------------------------- actions

    def launch(self, item):
        ok, message = rba_launch.launch(item)
        if ok:
            self.set_status(u"Ran {0}".format(item.title))
        else:
            # Tools finish silently: a refusal goes to the footer and the debug
            # log, never a dialog.
            self.set_status(message)
            log(u"launch refused: {0}".format(message))

    # ---------------------------------------------------------------- views

    def in_favourites(self):
        return to_text(self.settings.get(u"view", u"all")) == u"favourites"

    def apply_view(self):
        u"""Favourites: the grid, no search box, no fold; else the list."""
        favourites = self.in_favourites()
        shown, hidden = Visibility.Visible, Visibility.Collapsed
        try:
            self.search_row.Visibility = hidden if favourites else shown
            self.list_panel.Visibility = hidden if favourites else shown
            self.fav_panel.Visibility = shown if favourites else hidden
            self.fold_btn.Visibility = hidden if favourites else shown
            self.labels_btn.Visibility = shown if favourites else hidden
            self.fav_btn.Tag = u"on" if favourites else None
            self.fav_btn.ToolTip = (u"Back to every addin" if favourites
                                    else u"Favourites")
            labels = self.favs.labels_shown()
            self.labels_btn.Tag = u"on" if labels else None
            self.labels_btn.ToolTip = (u"Hide the names under favourites" if labels
                                       else u"Show the names under favourites")
        except Exception:
            log_exception(u"apply_view")

    def on_fav_view(self, sender, args):
        self.settings[u"view"] = u"all" if self.in_favourites() else u"favourites"
        self.save_settings()
        self.render()

    def on_labels(self, sender, args):
        self.favs.toggle_labels()

    def is_favourite(self, item):
        return self.favs.is_favourite(item)

    def toggle_favourite(self, item):
        self.favs.toggle(item)

    def any_open(self):
        keys = getattr(self, u"drawn_keys", [])
        return any(not self.collapsed.get(key, False) for key in keys)

    def update_fold_button(self):
        u"""One button for both: collapse while anything is open, else expand."""
        try:
            closing = self.any_open()
            self.find(u"FoldCloseGlyph").Visibility = (Visibility.Visible if closing
                                                       else Visibility.Collapsed)
            self.find(u"FoldOpenGlyph").Visibility = (Visibility.Collapsed if closing
                                                      else Visibility.Visible)
            self.fold_btn.ToolTip = (u"Collapse every group" if closing
                                     else u"Expand every group")
        except Exception:
            log_exception(u"fold button")

    def on_fold(self, sender, args):
        if self.any_open():
            for key in getattr(self, u"drawn_keys", []):
                self.collapsed[key] = True
        else:
            self.collapsed = {}
        rba_core.set_list(self.settings, u"collapsed",
                          [k for k in self.collapsed if self.collapsed[k]])
        self.save_settings()
        self.render()

    def step_icon(self, direction):
        sizes = rba_core.ICON_SIZES
        current = self.icon_size()
        index = sizes.index(current) + direction
        index = max(0, min(len(sizes) - 1, index))
        self.settings[u"icon_size"] = to_text(sizes[index])
        self.save_settings()
        self.render()

    def on_smaller(self, sender, args):
        self.step_icon(-1)

    def on_bigger(self, sender, args):
        self.step_icon(1)

    # ---------------------------------------------------------------- footer

    def apply_footer(self):
        shown = rba_core.as_bool(self.settings, u"show_footer")
        try:
            self.footer.Visibility = Visibility.Visible if shown else Visibility.Collapsed
            # Lit while the footer shows, like the dock buttons.
            self.footer_btn.Tag = u"on" if shown else None
            self.footer_btn.ToolTip = (u"Hide the status footer" if shown
                                       else u"Show the status footer")
        except Exception:
            log_exception(u"apply_footer")

    def on_footer_click(self, sender, args):
        # Parked, the drawer is holding the footer's visibility to put back on
        # reopening - changing it underneath would be undone. Open first.
        drawer = self.host_drawer
        if drawer is not None and drawer.shrunk:
            drawer.expand(instant=True)
        shown = rba_core.as_bool(self.settings, u"show_footer")
        self.settings[u"show_footer"] = u"0" if shown else u"1"
        self.save_settings()
        self.apply_footer()

    def on_refresh(self, sender, args):
        self.rescan()

    def on_key(self, sender, args):
        try:
            if args.Key == Key.F5:
                self.rescan()
                args.Handled = True
            elif args.Key == Key.Escape:
                self.search_box.Text = u""
        except Exception:
            pass

    def on_settings_click(self, sender, args):
        try:
            changed = rba_settings.show(self.settings, self.theme_name,
                                        owner=self.host_window,
                                        owner_drawer=self.host_drawer)
            if changed:
                self.settings = changed
                self.save_settings()
                self.reload_settings(from_disk=False)
        except Exception:
            log_exception(u"on_settings_click")
            self.set_status(u"Settings would not open - see the debug log")


# ----------------------------------------------------------------------
# what the ribbon button does
# ----------------------------------------------------------------------

def show(uiapp):
    u"""Show the docked pane if Revit holds one, else the floating window.

    **This never registers anything.** Revit only sets a dockable pane up while
    it is building its user interface, so a registration from here is accepted
    and the pane is never created - after which GetDockablePane throws for the
    rest of the session and even the start up registration can no longer take.
    1.1.0 to 1.3.0 tried it anyway. Registration belongs to start up alone
    (`rba_dock.register`, from the startup block).
    """
    rba_launch.set_uiapp(uiapp)
    if rba_dock.pane_registered():
        _warn_if_stale()
        try:
            pane = uiapp.GetDockablePane(rba_dock.pane_id())
            if pane.IsShown():
                pane.Hide()
            else:
                pane.Show()
            return True, u""
        except Exception:
            log_exception(u"show/GetDockablePane")

    status = rba_dock.docking_status()
    log(u"docking unavailable ({0}): {1}".format(status[0], status[2]))
    return rba_window.show(_build_pane, status)


STALE_KEY = u"RevoBIM.AddinManager.stale_warned"


def _warn_if_stale():
    u"""Say once per session when the docked pane is older than what is installed.

    A docked pane runs the code Revit loaded at start up. Unzipping an update
    or reloading pyRevit does not replace it - only restarting Revit does - so
    without this an update looks as though it did nothing. A pane registered
    by 1.4.0 carries no version at all, which counts as stale.
    """
    running = rba_dock.pane_version()
    if running == rba_core.__version__:
        return
    try:
        from System import AppDomain
        if AppDomain.CurrentDomain.GetData(STALE_KEY):
            return
        AppDomain.CurrentDomain.SetData(STALE_KEY, u"yes")
    except Exception:
        pass
    log(u"docked pane is {0}, installed is {1}".format(running or u"older", rba_core.__version__))
    try:
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show(
            u"RevoBIM Addin Manager",
            u"The docked panel is running {0}, but {1} is installed.\n\n"
            u"Revit keeps the docked panel it loaded at start up - a pyRevit "
            u"reload does not replace it. Restart Revit to load {1}.".format(
                u"v" + running if running else u"an older version",
                u"v" + rba_core.__version__))
    except Exception:
        pass


def _build_pane():
    pane = AddinsPane(mode=u"window")
    pane.first_read_done = True
    pane.rescan()
    return pane


def register(*candidates):
    u"""Kept for startup blocks pasted from 1.2.0 to 1.3.0, which call it here."""
    return rba_dock.register(*candidates)
