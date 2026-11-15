# -*- coding: utf-8 -*-
"""Find Room - the modeless window.

Left: rooms (or spaces) of the chosen model grouped under their levels in
elevation order, levels collapsible, keyword search. Picking a room lists the
floor plans on its level on the right; clicking a plan opens it in Temporary
View Properties with room references and colour fill on, colours the room and
zooms to it. Every read and write goes through the ExternalEvent runner.
"""
import frm_clr  # noqa: F401 - assemblies first, always

import os
import sys
import time

from System import AppDomain, TimeSpan
from System.Windows import (
    Visibility, Thickness, GridLength, GridUnitType, VerticalAlignment,
    TextTrimming, TextAlignment, FontWeights, Clipboard, SystemParameters,
    FrameworkElement, CornerRadius,
)
from System.Windows.Controls import (
    ListBoxItem, Grid, ColumnDefinition, TextBlock, StackPanel, Orientation,
    ComboBoxItem, Border,
)
from System.Windows.Shapes import Path
from System.Windows.Input import Key
from System.Windows.Threading import DispatcherTimer

import frm_core as core
import frm_revit as rv
import frm_ui as ui
import frm_runner
from frm_version import __version__

WINDOW_KEY = u"RevoBIM.FindRoom.window.{0}".format(__version__)
_LIVE = []

CHEVRON_OPEN = u"M0,1 L9,1 L4.5,6 Z"
CHEVRON_SHUT = u"M1,0 L6,4.5 L1,9 Z"


class WrongDocument(Exception):
    pass


def _tb(text, key=u"Text", size=None, bold=False, trim=True):
    t = TextBlock()
    t.Text = core.to_text(text)
    t.SetResourceReference(TextBlock.ForegroundProperty, key)
    t.VerticalAlignment = VerticalAlignment.Center
    if size:
        t.FontSize = size
    if bold:
        t.FontWeight = FontWeights.SemiBold
    if trim:
        t.TextTrimming = TextTrimming.CharacterEllipsis
    return t


def _col(grid, width=None, star=False, min_width=None):
    c = ColumnDefinition()
    if star:
        c.Width = GridLength(1, GridUnitType.Star)
    elif width is None:
        c.Width = GridLength.Auto
    else:
        c.Width = GridLength(width)
    if min_width:
        c.MinWidth = min_width
    grid.ColumnDefinitions.Add(c)


def _place(grid, element, col):
    Grid.SetColumn(element, col)
    grid.Children.Add(element)


def _badge(text, key):
    b = Border()
    b.CornerRadius = CornerRadius(3)
    b.Padding = Thickness(5, 0, 5, 1)
    b.Margin = Thickness(6, 0, 0, 0)
    b.VerticalAlignment = VerticalAlignment.Center
    b.SetResourceReference(Border.BackgroundProperty, key)
    t = _tb(text, u"OnAccent", size=10, trim=False)
    b.Child = t
    return b


class FindRoomWindow(object):

    def __init__(self, uiapp, settings, preselect=None):
        self.uiapp = uiapp
        doc = uiapp.ActiveUIDocument.Document
        self.doc_title = core.to_text(doc.Title)
        self.doc_key = rv.doc_key(doc)
        self.settings = settings
        self.log = ui.Log(core.get_bool(settings, u"debug"))
        self.log(u"Find Room {0} on Revit {1}, {2}".format(
            __version__, rv.revit_version(uiapp), sys.version.split()[0]))
        if frm_clr.MISSING:
            self.log(u"assemblies not found: {0}".format(u", ".join(frm_clr.MISSING)))

        self.models = []
        self.model = None
        self.rooms = []
        self.collapsed = set()
        self.room = None
        self.views = []
        self.view_meta = (u"", 0.0, [], None)
        self.views_for = None
        self.record = None
        self.last_view = {}
        self.filling = False
        self.go_when_ready = False
        self.zoom_tries = 0
        self.closing = False
        self.preselect = preselect or (None, None)
        self.mode = settings.get(u"mode", u"rooms")
        if self.preselect[0] in (u"rooms", u"spaces"):
            self.mode = self.preselect[0]
        self.theme_mode = settings.get(u"theme", u"follow")
        self.theme = u"dark"
        self.canvas = None

        self.win = ui.load_xaml("FindRoom.xaml")
        ui.merge_theme(self.win)
        f = self.win.FindName
        for name in (u"Root", u"Header", u"Logo", u"ThemeBtn", u"ThemeIcon", u"ThemeText",
                     u"SettingsBtn", u"VersionText", u"FullBtn", u"CloseBtn",
                     u"RoomsRadio", u"SpacesRadio", u"ModelCombo", u"RefreshBtn", u"ModelNote",
                     u"LeftCol", u"RightCol", u"RoomsHeading", u"RoomsCount", u"CollapseBtn",
                     u"ExpandBtn", u"UnplacedCheck", u"SearchBox", u"RoomList", u"RoomsEmpty",
                     u"ViewsHeading", u"ViewsSub", u"ViewSearch", u"ViewList", u"ViewsEmpty",
                     u"GoBtn", u"GoText", u"DebugCheck", u"CopyDebugBtn", u"ClearBtn",
                     u"Status", u"SettingsPanel", u"HlSwatch", u"HlText", u"TransText",
                     u"MarginText", u"TolText", u"RestoreCheck", u"SettingsSave",
                     u"SettingsReset"):
            setattr(self, name, f(name))

        self.refresh_theme()
        self.VersionText.Text = u"v{0}".format(__version__)
        logo = ui.load_image(os.path.join(ui.HERE, "icon.png"))
        if logo is not None:
            self.Logo.Source = logo

        self.fullscreen = ui.FullScreen(self.win)
        self.egg = ui.EggCounter(self.win, lambda: self.theme)
        self.runner = frm_runner.Runner(self.win.Dispatcher, self.log, self._on_busy)
        self.plan_timer = DispatcherTimer()
        self.plan_timer.Interval = TimeSpan.FromMilliseconds(160)
        self.plan_timer.Tick += self._plan_tick
        self.zoom_timer = DispatcherTimer()
        self.zoom_timer.Interval = TimeSpan.FromMilliseconds(350)
        self.zoom_timer.Tick += self._zoom_tick
        self.pending_zoom = None
        self.header_click = -100000
        self.last_go = (None, None, 0.0)

        self._size()
        self._wire()
        self.filling = True
        self.RoomsRadio.IsChecked = self.mode == u"rooms"
        self.SpacesRadio.IsChecked = self.mode == u"spaces"
        self.UnplacedCheck.IsChecked = core.get_bool(settings, u"show_unplaced")
        self.DebugCheck.IsChecked = core.get_bool(settings, u"debug")
        self.filling = False
        self._mode_text()
        self.read_models()

    # =========================================================================
    # Set-up
    # =========================================================================
    def _size(self):
        w = self.win
        w.Width = core.get_float(self.settings, u"width", 780, 4000)
        w.Height = core.get_float(self.settings, u"height", 480, 3000)
        try:
            wa = SystemParameters.WorkArea
            w.Width = min(w.Width, wa.Width)
            w.Height = min(w.Height, wa.Height)
            w.Left = wa.Left + (wa.Width - w.Width) / 2.0
            w.Top = wa.Top + (wa.Height - w.Height) / 2.0
        except Exception:
            pass
        split = core.get_float(self.settings, u"split", 0.25, 0.75)
        self.LeftCol.Width = GridLength(split * 100.0, GridUnitType.Star)
        self.RightCol.Width = GridLength((1.0 - split) * 100.0, GridUnitType.Star)

    def _wire(self):
        w = self.win
        self.Header.MouseLeftButtonDown += self._header_down
        self.Logo.MouseLeftButtonDown += self._logo_down
        w.PreviewMouseLeftButtonDown += self._any_down
        w.PreviewKeyDown += self._key
        w.Activated += self._activated
        w.Closing += self._closing
        w.Closed += self._closed
        self.ThemeBtn.Click += self._theme_click
        self.SettingsBtn.Click += self._settings_open
        self.SettingsSave.Click += self._settings_save
        self.SettingsReset.Click += self._settings_reset
        self.HlText.TextChanged += self._swatch
        self.FullBtn.Click += lambda s, e: self.fullscreen.toggle()
        self.CloseBtn.Click += lambda s, e: self.win.Close()
        self.RoomsRadio.Checked += self._mode_changed
        self.SpacesRadio.Checked += self._mode_changed
        self.ModelCombo.SelectionChanged += self._model_changed
        self.RefreshBtn.Click += lambda s, e: self.refresh()
        self.SearchBox.TextChanged += lambda s, e: self.fill_rooms()
        self.UnplacedCheck.Click += self._unplaced
        self.ExpandBtn.Click += lambda s, e: self._expand_all(True)
        self.CollapseBtn.Click += lambda s, e: self._expand_all(False)
        self.RoomList.SelectionChanged += self._room_selected
        self.RoomList.MouseDoubleClick += self._room_double
        self.RoomList.PreviewKeyDown += self._room_key
        self.ViewSearch.TextChanged += lambda s, e: self.fill_views()
        self.ViewList.SelectionChanged += self._view_selected
        self.ViewList.PreviewKeyDown += self._view_key
        self.GoBtn.Click += lambda s, e: self.go_selected()
        self.ClearBtn.Click += lambda s, e: self.clear()
        self.DebugCheck.Click += self._debug
        self.CopyDebugBtn.Click += self._copy_debug
        ui.attach_grips(w, self.win.FindName, self._grip_moved)

    # =========================================================================
    # Theme
    # =========================================================================
    def refresh_theme(self):
        try:
            self.canvas = rv.canvas_theme(self.uiapp)
        except Exception:
            self.canvas = None
        self.theme = core.resolve_theme(self.theme_mode, self.canvas)
        ui.apply_palette(self.win, self.theme)
        try:
            self.ThemeIcon.Data = ui.geometry(ui.THEME_ICONS.get(self.theme_mode))
            self.ThemeText.Text = core.theme_label(self.theme_mode)
            tip = u"Theme: {0}".format(core.theme_label(self.theme_mode))
            if self.theme_mode == u"follow":
                tip += u" - following Revit's canvas ({0})".format(self.canvas or u"not readable, dark")
            self.ThemeBtn.ToolTip = tip + u". Click for Auto, Dark, Light."
        except Exception:
            pass

    def _theme_click(self, sender, e):
        self.theme_mode = core.next_theme_mode(self.theme_mode)
        self.settings[u"theme"] = self.theme_mode
        core.save_settings(self.settings)
        self.refresh_theme()

    def _activated(self, sender, e):
        if self.theme_mode == u"follow":
            before = self.theme
            self.refresh_theme()
            if before != self.theme:
                self.log(u"canvas theme changed to {0}".format(self.theme))

    # =========================================================================
    # Jobs
    # =========================================================================
    def _job(self, name, fn, done):
        """fn(uiapp, doc) in Revit's API context, refusing to touch any model
        other than the one this window was opened on."""
        def work(uiapp):
            try:
                doc = uiapp.ActiveUIDocument.Document
            except Exception:
                doc = None
            if doc is None or rv.doc_key(doc) != self.doc_key:
                raise WrongDocument(u"Switch back to {0} - this window belongs to it.".format(
                    self.doc_title))
            return fn(uiapp, doc)

        def back(result, error):
            if self.closing and name not in (u"clear",):
                return
            done(result, error)
        return self.runner.submit(name, work, back)

    def _on_busy(self, busy):
        if not busy and self.runner.queue:
            self.log(u"runner freed with {0} job(s) still waiting".format(len(self.runner.queue)))

    def status(self, text, key=u"Muted"):
        self.Status.Text = core.to_text(text)
        self.Status.SetResourceReference(TextBlock.ForegroundProperty, key)

    # =========================================================================
    # Models
    # =========================================================================
    def read_models(self):
        self.status(u"Reading the model...")

        def fn(uiapp, doc):
            return rv.list_models(doc)

        def done(models, error):
            if error:
                self.status(error, u"Red")
                return
            self.models = models or []
            self._fill_models()
        self._job(u"models", fn, done)

    def _fill_models(self):
        self.filling = True
        try:
            self.ModelCombo.Items.Clear()
            want = self.settings.get(u"model", u"")
            pick = None
            for m in self.models:
                item = ComboBoxItem()
                if m.loaded:
                    item.Content = u"{0}   \u00b7  {1} rooms".format(m.label, m.count)
                else:
                    item.Content = m.label
                item.IsEnabled = m.loaded
                item.Tag = m.key
                self.ModelCombo.Items.Add(item)
                if pick is None and m.loaded and want and m.name == want:
                    pick = m
            if self.preselect[1] is not None or pick is None:
                pick = self._default_model()
            if pick is not None:
                self.ModelCombo.SelectedIndex = self.models.index(pick)
            self.model = pick
        finally:
            self.filling = False
        self._mode_text()
        self.read_rooms()

    def _default_model(self):
        host = self.models[0] if self.models else None
        if self.preselect[1] is not None or self.mode == u"spaces":
            return host
        if host is not None and host.count > 0:
            return host
        for m in self.models[1:]:
            if m.loaded and m.count > 0:
                return m
        return host

    def _model_changed(self, sender, e):
        if self.filling:
            return
        i = self.ModelCombo.SelectedIndex
        if i < 0 or i >= len(self.models):
            return
        self.model = self.models[i]
        self.settings[u"model"] = self.model.name
        core.save_settings(self.settings)
        self.read_rooms()

    def _mode_changed(self, sender, e):
        if self.filling:
            return
        self.mode = u"spaces" if self.SpacesRadio.IsChecked else u"rooms"
        self.settings[u"mode"] = self.mode
        core.save_settings(self.settings)
        self._mode_text()
        self.read_rooms()

    def _mode_text(self):
        spaces = self.mode == u"spaces"
        self.ModelCombo.IsEnabled = not spaces
        self.RoomsHeading.Text = u"Spaces by level" if spaces else u"Rooms by level"
        self.SearchBox.Tag = u"Search number, name or level"
        self.UnplacedCheck.ToolTip = u"Also list {0} that are not placed or not enclosed".format(
            u"spaces" if spaces else u"rooms")
        if spaces:
            self.ModelNote.Text = u"Spaces are read from this model - no linked model needed."
        elif self.model is not None and self.model.is_link:
            self.ModelNote.Text = u"Linked rooms are found on this model's plans at the same level."
        else:
            self.ModelNote.Text = u""

    def refresh(self):
        self.read_models()

    # =========================================================================
    # Rooms
    # =========================================================================
    def read_rooms(self):
        self.rooms = []
        self.room = None
        self._clear_views(u"Pick a {0} on the left.".format(self._noun()))
        self.RoomList.Items.Clear()
        self.RoomsEmpty.Text = u"Reading {0}...".format(self._noun(True))
        self.RoomsEmpty.Visibility = Visibility.Visible
        mode, model = self.mode, self.model

        def fn(uiapp, doc):
            return rv.read_rooms(doc, model, mode, self.log)

        def done(result, error):
            if error:
                self.RoomsEmpty.Text = error
                self.status(error, u"Red")
                return
            if mode != self.mode or model is not self.model:
                return
            self.rooms, problems = result
            self.fill_rooms()
            levels = len(core.level_keys([r for r in self.rooms if r.state == u"ok"]))
            placed = len([r for r in self.rooms if r.state == u"ok"])
            msg = u"{0} {1} on {2} level{3}".format(
                placed, self._noun(placed != 1), levels, u"" if levels == 1 else u"s")
            unplaced = len(self.rooms) - placed
            if unplaced:
                msg += u" \u00b7 {0} not placed or not enclosed".format(unplaced)
            if problems:
                msg += u" \u00b7 {0} could not be read (see debug)".format(len(problems))
                for p in problems[:50]:
                    self.log(p)
            self.status(msg)
            self._apply_preselect()
        self._job(u"rooms", fn, done)

    def _noun(self, plural=False):
        base = u"space" if self.mode == u"spaces" else u"room"
        return base + (u"s" if plural else u"")

    def fill_rooms(self):
        rows, shown, levels = core.build_rows(
            self.rooms, self.SearchBox.Text, self.collapsed,
            bool(self.UnplacedCheck.IsChecked))
        keep = self.room.key if self.room is not None else None
        self.filling = True
        try:
            self.RoomList.Items.Clear()
            selected = None
            for row in rows:
                if row.kind == u"level":
                    self.RoomList.Items.Add(self._level_item(row))
                else:
                    item = self._room_item(row)
                    self.RoomList.Items.Add(item)
                    if keep is not None and row.room.key == keep:
                        selected = item
            if selected is not None:
                self.RoomList.SelectedItem = selected
        finally:
            self.filling = False
        self.RoomsCount.Text = u"{0} \u00b7 {1} level{2}".format(
            shown, levels, u"" if levels == 1 else u"s") if self.rooms else u""
        if not self.rooms:
            where = u"this model" if self.mode == u"spaces" or self.model is None \
                or not self.model.is_link else self.model.name
            self.RoomsEmpty.Text = u"No {0} in {1}.".format(self._noun(True), where)
            self.RoomsEmpty.Visibility = Visibility.Visible
        elif not rows:
            self.RoomsEmpty.Text = u"Nothing matches the search."
            self.RoomsEmpty.Visibility = Visibility.Visible
        else:
            self.RoomsEmpty.Visibility = Visibility.Collapsed

    def _level_item(self, row):
        item = ListBoxItem()
        item.SetResourceReference(FrameworkElement.StyleProperty, u"HeaderItem")
        item.Padding = Thickness(8, 5, 10, 5)
        g = Grid()
        _col(g, 18)
        _col(g, star=True)
        _col(g)
        _col(g)
        chev = Path()
        chev.Data = ui.geometry(CHEVRON_OPEN if row.expanded else CHEVRON_SHUT)
        chev.SetResourceReference(Path.FillProperty, u"Orange")
        chev.VerticalAlignment = VerticalAlignment.Center
        _place(g, chev, 0)
        _place(g, _tb(row.level_name, bold=True), 1)
        _place(g, _tb(u"{0} {1}".format(row.count, self._noun(row.count != 1)), u"Muted"), 2)
        elev = _tb(core.format_elev(row.elev), u"Faint", size=11)
        elev.Margin = Thickness(12, 0, 0, 0)
        elev.MinWidth = 70
        elev.TextAlignment = TextAlignment.Right
        _place(g, elev, 3)
        item.Content = g
        item.Tag = u"level"
        key = row.level_key

        def toggle(sender, e):
            e.Handled = True
            self.header_click = e.Timestamp
            if e.ClickCount > 1 or core.words(self.SearchBox.Text):
                return
            if key in self.collapsed:
                self.collapsed.discard(key)
            else:
                self.collapsed.add(key)
            self.fill_rooms()
        item.PreviewMouseLeftButtonDown += toggle
        return item

    def _room_item(self, row):
        room = row.room
        item = ListBoxItem()
        item.Padding = Thickness(26, 4, 10, 4)
        g = Grid()
        _col(g, min_width=64)
        _col(g, star=True)
        _col(g)
        _col(g)
        num = _tb(room.number or u"-", u"Blue", bold=True)
        num.Margin = Thickness(0, 0, 12, 0)
        _place(g, num, 0)
        _place(g, _tb(room.name or u"(no name)"), 1)
        area = _tb(core.format_area(room.area_m2), u"Muted", size=11)
        area.Margin = Thickness(10, 0, 0, 0)
        _place(g, area, 2)
        if room.state != u"ok":
            st = _tb(room.state_text, u"Orange", size=11)
            st.Margin = Thickness(10, 0, 0, 0)
            _place(g, st, 3)
            item.Opacity = 0.6
            item.ToolTip = u"{0} - it cannot be shown on a plan.".format(room.state_text)
        item.Content = g
        item.Tag = room.key
        return item

    def _room_for(self, item):
        if item is None:
            return None
        key = item.Tag
        if key == u"level":
            return None
        for r in self.rooms:
            if r.key == key:
                return r
        return None

    def _room_selected(self, sender, e):
        if self.filling:
            return
        room = self._room_for(self.RoomList.SelectedItem)
        if room is None:
            return
        if self.room is not None and room.key == self.room.key and self.views_for == room.key:
            return
        self.room = room
        self.go_when_ready = False
        self.plan_timer.Stop()
        self.plan_timer.Start()

    def _room_double(self, sender, e):
        # a double-click on a level heading must not go to the room selected
        # before it (MouseDoubleClick fires even when the preview was handled)
        if abs(e.Timestamp - self.header_click) < 800:
            return
        room = self._room_for(self.RoomList.SelectedItem)
        if room is not None:
            self.go_first()

    def _room_key(self, sender, e):
        if e.Key == Key.Enter:
            e.Handled = True
            self.go_first()

    def _unplaced(self, sender, e):
        self.settings[u"show_unplaced"] = u"1" if self.UnplacedCheck.IsChecked else u"0"
        core.save_settings(self.settings)
        self.fill_rooms()

    def _expand_all(self, expand):
        if expand:
            self.collapsed = set()
        else:
            self.collapsed = set(core.level_keys(self.rooms))
        self.fill_rooms()

    def _apply_preselect(self):
        key = self.preselect[1]
        if key is None:
            return
        self.preselect = (None, None)
        for item in self.RoomList.Items:
            if item.Tag == key:
                self.RoomList.SelectedItem = item
                try:
                    self.RoomList.ScrollIntoView(item)
                except Exception:
                    pass
                return

    # =========================================================================
    # Plans
    # =========================================================================
    def _clear_views(self, message):
        self.views = []
        self.views_for = None
        self.ViewList.Items.Clear()
        self.ViewsHeading.Text = u"Floor plans"
        self.ViewsSub.Text = message
        self.ViewsEmpty.Text = u""
        self.GoBtn.IsEnabled = False

    def _plan_tick(self, sender, e):
        self.plan_timer.Stop()
        self.read_plans()

    def read_plans(self):
        room = self.room
        if room is None:
            return
        self._clear_views(room.label)
        self.ViewsHeading.Text = u"Floor plans on {0}".format(room.level_name)
        if not room.findable:
            self.ViewsSub.Text = u"{0} - {1}, so it cannot be shown on a plan.".format(
                room.label, room.state_text.lower() or u"no position")
            self.go_when_ready = False
            return
        self.ViewsEmpty.Text = u"Finding plans..."
        tol = core.mm_to_ft(core.get_float(self.settings, u"level_tol_mm", 1, 5000))

        def fn(uiapp, doc):
            views, how, offset, names = rv.plans_for_room(doc, room, tol)
            active = None
            try:
                active = rv.eid_value(uiapp.ActiveUIDocument.ActiveView.Id)
            except Exception:
                pass
            return views, how, offset, names, active

        def done(result, error):
            if self.room is None or self.room.key != room.key:
                return
            if error:
                self.ViewsEmpty.Text = error
                self.status(error, u"Red")
                return
            views, how, offset, names, active = result
            self.views = views
            self.views_for = room.key
            self.view_meta = (how, offset, names, active)
            self._views_text(room)
            self.fill_views()
            if self.go_when_ready:
                self.go_when_ready = False
                self.go_first()
        self._job(u"plans", fn, done)

    def _views_text(self, room):
        how, offset, names, active = self.view_meta
        level = u", ".join(names) if names else room.level_name
        self.ViewsHeading.Text = u"Floor plans on {0}".format(level)
        sub = room.label
        if room.ref.get(u"link") is not None:
            if how == u"elevation":
                sub += u"  \u00b7  linked level {0} matched by height".format(room.level_name)
            elif how == u"name":
                sub += u"  \u00b7  matched by level name ({0:.0f} mm apart)".format(core.ft_to_mm(offset))
            elif how == u"nearest":
                sub += u"  \u00b7  no level at the same height - nearest is {0} ({1:.0f} mm off)".format(
                    level, core.ft_to_mm(offset))
        self.ViewsSub.Text = sub

    def fill_views(self):
        room = self.room
        if room is None or self.views_for != (room.key if room else None):
            return
        how, offset, names, active = self.view_meta
        preferred = self.last_view.get(room.level_key)
        ordered = core.filter_views(core.sort_views(self.views, active, preferred),
                                    self.ViewSearch.Text)
        self.ViewList.Items.Clear()
        for v in ordered:
            self.ViewList.Items.Add(self._view_item(v, v.key == active, v.key == preferred))
        if ordered:
            self.ViewList.SelectedIndex = 0
            self.ViewsEmpty.Text = u""
        elif self.views:
            self.ViewsEmpty.Text = u"Nothing matches the search."
        else:
            self.ViewsEmpty.Text = u"No floor plans on this level{0}.".format(
                u" in this model" if room.ref.get(u"link") is not None else u"")
        self.GoBtn.IsEnabled = bool(ordered)

    def _view_item(self, v, is_active, is_last):
        item = ListBoxItem()
        item.Padding = Thickness(10, 5, 10, 6)
        stack = StackPanel()
        top = StackPanel()
        top.Orientation = Orientation.Horizontal
        name = _tb(v.name, bold=True)
        top.Children.Add(name)
        if is_last:
            top.Children.Add(_badge(u"Last used", u"Blue"))
        if is_active:
            top.Children.Add(_badge(u"Open now", u"Green"))
        stack.Children.Add(top)
        bits = [b for b in (v.type_name, v.scale_text,
                            u"Sheet {0}".format(v.sheet) if v.sheet else u"",
                            u"Template: {0}".format(v.template) if v.template else u"") if b]
        if bits:
            line = _tb(u"  \u00b7  ".join(bits), u"Muted", size=11)
            line.Margin = Thickness(0, 2, 0, 0)
            stack.Children.Add(line)
        if v.note:
            note = _tb(v.note, u"Red" if not v.in_crop else u"Orange", size=11)
            note.Margin = Thickness(0, 2, 0, 0)
            stack.Children.Add(note)
        if not v.in_crop:
            item.ToolTip = u"The room sits outside this view's crop region - it opens, but the room will be cropped out."
        item.Content = stack
        item.Tag = v.key
        key = v.key

        def click(sender, e):
            self.go(self._view_by_key(key))
        item.MouseLeftButtonUp += click
        return item

    def _view_by_key(self, key):
        for v in self.views:
            if v.key == key:
                return v
        return None

    def _view_selected(self, sender, e):
        self.GoBtn.IsEnabled = self.ViewList.SelectedItem is not None

    def _view_key(self, sender, e):
        if e.Key == Key.Enter:
            e.Handled = True
            self.go_selected()

    # =========================================================================
    # Go / clear
    # =========================================================================
    def go_selected(self):
        item = self.ViewList.SelectedItem
        if item is not None:
            self.go(self._view_by_key(item.Tag))

    def go_first(self):
        room = self.room
        if room is None or not room.findable:
            return
        if self.views_for != room.key:
            self.go_when_ready = True
            self.plan_timer.Stop()
            self.read_plans()
            return
        if self.ViewList.Items.Count:
            self.go(self._view_by_key(self.ViewList.Items[0].Tag))
        else:
            self.status(u"No floor plans on {0} to show it in.".format(room.level_name), u"Orange")

    def go(self, view):
        room = self.room
        if view is None or room is None or not room.findable:
            return
        now = time.time()
        if self.last_go[0] == room.key and self.last_go[1] == view.key and \
                now - self.last_go[2] < 0.8:
            return
        self.last_go = (room.key, view.key, now)
        self.status(u"Opening {0}...".format(view.name))
        previous = self.record
        settings = dict(self.settings)

        def fn(uiapp, doc):
            return rv.go_to_room(uiapp, room, view.ref, settings, previous, self.log)

        def done(result, error):
            if error:
                self.status(error, u"Red")
                return
            if result.get(u"record") is not None:
                self.record = result[u"record"]
            elif result.get(u"cleared"):
                self.record = None
            self.ClearBtn.IsEnabled = self.record is not None
            self.last_view[room.level_key] = view.key
            msgs = result.get(u"msgs") or []
            text = u"Showing {0} on {1}".format(room.label, view.name)
            if result.get(u"opened") == u"requested" and not result.get(u"zoomed"):
                self.pending_zoom = (view.ref, room.box)
                self.zoom_tries = 0
                self.zoom_timer.Start()
            elif result.get(u"opened") == u"" and not msgs:
                msgs.append(u"Revit would not open the view")
            if msgs:
                self.status(text + u" - " + u"; ".join(msgs), u"Orange")
            else:
                self.status(text, u"Green")
            self.fill_views()
        self._job(u"go", fn, done)

    def _zoom_tick(self, sender, e):
        self.zoom_timer.Stop()
        if self.pending_zoom is None:
            return
        view_id, box = self.pending_zoom
        margin = core.mm_to_ft(core.get_float(self.settings, u"zoom_margin_mm", 0, 50000))

        def fn(uiapp, doc):
            return rv.zoom_to(uiapp.ActiveUIDocument, view_id, box, margin)

        def done(ok, error):
            self.zoom_tries += 1
            if ok or self.zoom_tries >= 6:
                self.pending_zoom = None
                if not ok:
                    self.log(u"zoom gave up after {0} tries".format(self.zoom_tries))
                return
            self.zoom_timer.Start()
        self._job(u"zoom", fn, done)

    def clear(self, closing=False):
        record = self.record
        if record is None:
            return

        def fn(uiapp, doc):
            return rv.clear(uiapp, record, self.log)

        def done(ok, error):
            if error:
                self.log(u"clear: {0}".format(error))
            if ok:
                self.record = None
            if not closing:
                self.ClearBtn.IsEnabled = self.record is not None
                self.status(u"Highlight cleared." if ok else
                            u"Could not clear the highlight - see debug.", u"Muted" if ok else u"Orange")
            else:
                self.runner.dispose()
        self._job(u"clear", fn, done)

    # =========================================================================
    # Settings panel
    # =========================================================================
    def _settings_open(self, sender, e):
        if self.SettingsPanel.Visibility == Visibility.Visible:
            self.SettingsPanel.Visibility = Visibility.Collapsed
            return
        s = self.settings
        self.HlText.Text = core.to_hex(core.parse_hex(s.get(u"highlight")))
        self.TransText.Text = core.to_text(core.get_int(s, u"transparency", 0, 90))
        self.MarginText.Text = core.to_text(core.get_int(s, u"zoom_margin_mm", 0, 50000))
        self.TolText.Text = core.to_text(core.get_int(s, u"level_tol_mm", 1, 5000))
        self.RestoreCheck.IsChecked = core.get_bool(s, u"restore_on_close")
        self.SettingsPanel.Visibility = Visibility.Visible

    def _swatch(self, sender, e):
        try:
            self.HlSwatch.Background = ui.brush(core.to_hex(core.parse_hex(self.HlText.Text)))
        except Exception:
            pass

    def _settings_save(self, sender, e):
        s = self.settings
        s[u"highlight"] = core.to_hex(core.parse_hex(self.HlText.Text, core.parse_hex(s.get(u"highlight"))))
        for box, key, lo, hi in ((self.TransText, u"transparency", 0, 90),
                                 (self.MarginText, u"zoom_margin_mm", 0, 50000),
                                 (self.TolText, u"level_tol_mm", 1, 5000)):
            probe = {key: box.Text}
            try:
                float(box.Text)
                s[key] = core.to_text(core.get_int(probe, key, lo, hi))
            except Exception:
                pass
        s[u"restore_on_close"] = u"1" if self.RestoreCheck.IsChecked else u"0"
        core.save_settings(s)
        self.SettingsPanel.Visibility = Visibility.Collapsed
        self.status(u"Settings saved - they apply to the next room you go to.")

    def _settings_reset(self, sender, e):
        d = core.DEFAULTS
        self.HlText.Text = d[u"highlight"]
        self.TransText.Text = d[u"transparency"]
        self.MarginText.Text = d[u"zoom_margin_mm"]
        self.TolText.Text = d[u"level_tol_mm"]
        self.RestoreCheck.IsChecked = d[u"restore_on_close"] == u"1"

    # =========================================================================
    # Debug
    # =========================================================================
    def _debug(self, sender, e):
        on = bool(self.DebugCheck.IsChecked)
        self.log.enabled = on
        self.settings[u"debug"] = u"1" if on else u"0"
        core.save_settings(self.settings)
        if on:
            self.log(u"debug on")

    def report(self):
        lines = [
            u"RevoBIM Find Room v{0}".format(__version__),
            u"Revit {0} | Python {1}".format(rv.revit_version(self.uiapp), sys.version.split()[0]),
            u"Missing assemblies: {0}".format(u", ".join(frm_clr.MISSING) or u"none"),
            u"Theme mode {0} | canvas {1} | showing {2}".format(self.theme_mode, self.canvas, self.theme),
            u"Model {0} | mode {1} | models {2}".format(
                self.model.label if self.model else u"-", self.mode, len(self.models)),
            u"Rooms read {0} | selected {1} | plans {2}".format(
                len(self.rooms), self.room.label if self.room else u"-", len(self.views)),
            u"Highlight active: {0}".format(
                u"no" if not self.record else u"view {0}, tvp_by_us {1}, filter {2}, cats {3}".format(
                    rv.eid_value(self.record.get(u"view_id")), self.record.get(u"tvp_by_us"),
                    self.record.get(u"filter_id") is not None, len(self.record.get(u"cats", [])))),
            u"Runner busy {0}, queued {1}".format(self.runner.busy, len(self.runner.queue)),
            u"Settings: " + u"; ".join(u"{0}={1}".format(k, self.settings[k]) for k in sorted(self.settings)),
            u"",
            self.log.text(),
        ]
        return u"\n".join(lines)

    def _copy_debug(self, sender, e):
        try:
            Clipboard.SetText(self.report())
            self.status(u"Debug report copied - paste it to Claude.")
        except Exception as exc:
            self.status(u"Could not copy: {0}".format(exc), u"Red")

    # =========================================================================
    # Chrome
    # =========================================================================
    def _header_down(self, sender, e):
        if e.ClickCount == 2:
            self.fullscreen.toggle()
            return
        try:
            if self.fullscreen.on:
                self.fullscreen.saved = None
            self.win.DragMove()
        except Exception:
            pass

    def _logo_down(self, sender, e):
        e.Handled = True
        self.egg.click(e.Timestamp)

    def _any_down(self, sender, e):
        try:
            if not self.Logo.Equals(e.OriginalSource):
                self.egg.reset()
        except Exception:
            pass

    def _grip_moved(self):
        if self.fullscreen.on:
            self.fullscreen.saved = None

    def _key(self, sender, e):
        if e.Key == Key.F11:
            e.Handled = True
            self.fullscreen.toggle()
        elif e.Key == Key.F5:
            e.Handled = True
            self.refresh()
        elif e.Key == Key.Escape:
            if self.SettingsPanel.Visibility == Visibility.Visible:
                e.Handled = True
                self.SettingsPanel.Visibility = Visibility.Collapsed
            elif self.fullscreen.on:
                e.Handled = True
                self.fullscreen.leave()

    def _closing(self, sender, e):
        self.closing = True
        try:
            if self.fullscreen.on:
                self.fullscreen.leave()
            self.settings[u"width"] = core.to_text(int(self.win.ActualWidth))
            self.settings[u"height"] = core.to_text(int(self.win.ActualHeight))
            lw = self.LeftCol.ActualWidth
            rw = self.RightCol.ActualWidth
            if lw + rw > 0:
                self.settings[u"split"] = u"{0:.3f}".format(lw / (lw + rw))
            core.save_settings(self.settings)
        except Exception:
            pass
        if self.record is not None and core.get_bool(self.settings, u"restore_on_close"):
            self.clear(closing=True)
        else:
            self.runner.dispose()

    def _closed(self, sender, e):
        try:
            if AppDomain.CurrentDomain.GetData(WINDOW_KEY) is self:
                AppDomain.CurrentDomain.SetData(WINDOW_KEY, None)
        except Exception:
            pass
        try:
            _LIVE.remove(self)
        except ValueError:
            pass


# =============================================================================
# Launch
# =============================================================================
def launch(uiapp):
    """Bring the open window forward if it belongs to this model; otherwise
    close it and open one for this model. Parked in the AppDomain under a
    version-stamped key, and in _LIVE so the engine keeps it."""
    doc = uiapp.ActiveUIDocument.Document
    domain = AppDomain.CurrentDomain
    existing = None
    try:
        existing = domain.GetData(WINDOW_KEY)
    except Exception:
        existing = None
    if existing is not None:
        try:
            if existing.doc_key == rv.doc_key(doc) and existing.win.IsLoaded:
                existing.win.Activate()
                return existing
            existing.win.Close()
        except Exception:
            pass
    settings = core.load_settings()
    pre = rv.preselected_room(uiapp.ActiveUIDocument)
    window = FindRoomWindow(uiapp, settings, pre)
    try:
        ui.set_owner(window.win, uiapp.MainWindowHandle)
    except Exception:
        pass
    domain.SetData(WINDOW_KEY, window)
    _LIVE.append(window)
    window.win.Show()
    return window
