# -*- coding: utf-8 -*-
"""The main window: a tab each for pipes, ducts and containment. In each,
every system in the project, one expandable section per service type,
isolate in 3D and change type from the footer. Each tab keeps its own read
of the model, its own sections and its own settings."""
import msm_clr  # noqa: F401  - assemblies first

import io
import os
import sys
import time
import traceback

from System import AppDomain, TimeSpan
from System.Windows.Threading import DispatcherTimer
from System.Windows import (Visibility, Clipboard, Thickness, FontWeights,
                            VerticalAlignment, Point, CornerRadius, TextTrimming)
from System.Windows.Input import Key, Keyboard, ModifierKeys, Cursors
from System.Windows.Controls import (TextBlock, Border, Expander, StackPanel, DockPanel,
                                     Dock, Button)
from System.Windows.Documents import Run, TextElement

import msm_core as core
import msm_theme as theme
import msm_ui as ui
import msm_model as model
import msm_ops as ops
import msm_grid as grid
import msm_settings
import msm_standards
import msm_resize
import msm_service
import msm_typechange
import msm_xlsx

WINDOW_KEY = u"RevoBIM.MepSystemManager.window.{0}".format(core.__version__)

# the window, the runner and its ExternalEvent are parked here so the
# persistent engine cannot collect them out from under the user
_LIVE = {}


class MainWindow(object):
    def __init__(self, uiapp, modal):
        self.uiapp = uiapp
        self.modal = modal
        self.base = core.load_settings()
        active = self.base.get(u"active_tab")
        self.domain = active if active in core.DOMAINS else u"pipe"
        self.tabs = {}
        for domain in core.DOMAINS:
            self.tabs[domain] = {u"snapshot": None, u"sections": [], u"read_from": u"",
                                 u"type_pick": None, u"scroll": None, u"pending": {},
                                 u"outers": []}
        self.syncing = False
        self.debug = core.to_bool(self.settings.get(u"debug"))
        self.debug_rows = []
        self.busy_since = None
        self.busy_what = u""
        self.watchdog = None
        self.busy = False
        self.proved_alive = False
        self.suspend_issues = False
        # False while the window builds itself: filling a dropdown fires its
        # SelectionChanged inside the command, while the engine is certainly
        # alive, and that must not count as proof. launch() arms it once the
        # window is shown.
        self.armed = False
        self.runner = ops.DirectRunner(uiapp) if modal else ops.ModelessRunner()
        self.watch_runner()

        self.window = ui.load_window(u"MepSystemManager.xaml", self.settings.get(u"theme"))
        w = self.window
        find = w.FindName
        self.find = find
        self.body_scroll = find(u"BodyScroll")
        if not modal:
            ui.set_owner(w, uiapp)

        find(u"VersionText").Text = u"v{0}".format(core.__version__)
        ui.load_icon(find(u"Logo"))
        ui.Chrome(w, header=find(u"HeaderBar"), full_button=find(u"BtnFull"),
                  full_glyph_back=find(u"FullGlyphBack"), close_button=find(u"BtnClose"))
        ui.attach_egg(w, find(u"LogoHost"), self.palette)
        self.paint_theme_label()

        self.sync_toolbar()
        find(u"ChkDebug").IsChecked = self.debug
        find(u"BtnCopyDebug").Visibility = Visibility.Visible if self.debug else Visibility.Collapsed

        safe = self.safe
        find(u"ChkDebug").Checked += safe(self.toggle_debug, u"Debug")
        find(u"ChkDebug").Unchecked += safe(self.toggle_debug, u"Debug")
        find(u"BtnCopyDebug").Click += safe(self.copy_debug, u"Copy debug table")
        find(u"BtnResize").Click += safe(self.resize_runs, u"Resize runs")
        find(u"BtnTabPipe").Click += safe(lambda: self.switch_tab(u"pipe"), u"Pipe tab")
        find(u"BtnTabDuct").Click += safe(lambda: self.switch_tab(u"duct"), u"Duct tab")
        find(u"BtnTabCont").Click += safe(lambda: self.switch_tab(u"cont"), u"Containment tab")
        find(u"BtnTabWs").Click += safe(lambda: self.switch_tab(u"ws"), u"Workset tab")
        find(u"BtnService").Click += safe(self.change_service, u"Change Service")
        find(u"BtnStage").Click += safe(self.stage_workset, u"Assign to selected")
        find(u"BtnPick").Click += safe(self.pick_system, u"Pick System")
        find(u"BtnReapply").Click += safe(self.reapply_type, u"Re-apply Type")
        find(u"BtnUnstage").Click += safe(self.unstage_workset, u"Clear selected")
        find(u"BtnClearAll").Click += safe(self.clear_staged, u"Clear all")
        find(u"BtnApplyWs").Click += safe(self.apply_worksets, u"Apply worksets")
        find(u"CmbWorkset").SelectionChanged += safe(self.on_selection_changed, u"Workset")
        find(u"TxtWorksetSearch").TextChanged += safe(self.on_workset_search, u"Workset search")
        find(u"TxtTypeSearch").TextChanged += safe(self.on_type_search, u"Type search")
        find(u"CmbWsGrouping").SelectionChanged += safe(self.on_ws_grouping, u"Group by")
        find(u"ChkMixedOnly").Checked += safe(self.on_mixed_only, u"Mixed only")
        find(u"ChkMultiType").Checked += safe(self.on_multi_type, u"Multi-type only")
        find(u"ChkNest").Checked += safe(self.on_nest, u"Group by System No")
        find(u"ChkNest").Unchecked += safe(self.on_nest, u"Group by System No")
        find(u"ChkMultiType").Unchecked += safe(self.on_multi_type, u"Multi-type only")
        find(u"ChkMixedOnly").Unchecked += safe(self.on_mixed_only, u"Mixed only")
        find(u"BtnSettings").Click += safe(self.open_settings, u"Settings")
        find(u"BtnChecks").Click += safe(self.open_checks, u"Checks")
        find(u"BtnExport").Click += safe(self.export, u"Export")
        find(u"BtnChecksOn").Click += safe(self.toggle_checks, u"Checks on or off")
        find(u"ChkIssuesOnly").Checked += safe(self.on_issues_only, u"Issues only")
        find(u"ChkIssuesOnly").Unchecked += safe(self.on_issues_only, u"Issues only")
        find(u"BtnTheme").Click += safe(self.cycle_theme, u"Theme")
        find(u"BtnRefresh").Click += safe(self.reload, u"Refresh")
        find(u"BtnExpandAll").Click += safe(lambda: self.expand_all(True), u"Expand all")
        find(u"BtnCollapseAll").Click += safe(lambda: self.expand_all(False), u"Collapse all")
        find(u"TxtSearch").TextChanged += safe(self.on_search, u"Search")
        for name in (u"ChkSplitSystem", u"ChkSplitType", u"ChkSplitSize"):
            find(name).Checked += safe(self.on_split, u"Rows split by")
            find(name).Unchecked += safe(self.on_split, u"Rows split by")
        find(u"CmbScope").SelectionChanged += safe(self.on_scope, u"Scope")
        find(u"BtnIsolate").Click += safe(self.isolate, u"Isolate Selected")
        find(u"BtnReset").Click += safe(self.reset_isolate, u"Reset")
        find(u"BtnChangeType").Click += safe(self.change_type, u"Change Type")
        find(u"CmbPipeType").SelectionChanged += safe(self.on_selection_changed, u"Type")
        find(u"CmbView").SelectionChanged += safe(self.on_view_picked, u"3D view")
        w.PreviewKeyDown += self.on_key
        w.ContentRendered += self.on_rendered
        self.sticky_index = None
        self.body_scroll.ScrollChanged += self.on_body_scroll
        find(u"StickyHeader").MouseLeftButtonUp += self.on_sticky_click
        w.Closing += self.on_closing
        w.Closed += self.on_closed

        self.search_timer = None
        self.reload()

    # ---------------- the active tab ----------------

    def _get_settings(self):
        """The active tab's settings over the one settings dict."""
        return core.DomainView(self.base, self.domain)

    def _set_settings(self, value):
        self.base = value.base if isinstance(value, core.DomainView) else value

    settings = property(_get_settings, _set_settings)

    def _tab_get(self, key):
        return self.tabs[self.domain][key]

    def _tab_set(self, key, value):
        self.tabs[self.domain][key] = value

    snapshot = property(lambda self: self._tab_get(u"snapshot"),
                        lambda self, v: self._tab_set(u"snapshot", v))
    sections = property(lambda self: self._tab_get(u"sections"),
                        lambda self, v: self._tab_set(u"sections", v))
    read_from = property(lambda self: self._tab_get(u"read_from"),
                         lambda self, v: self._tab_set(u"read_from", v))
    # the folds that hold sections - disciplines on the Workset Assigner,
    # service types when System No has folds of its own: (title, expander, sections)
    outers = property(lambda self: self._tab_get(u"outers"),
                      lambda self, v: self._tab_set(u"outers", v))

    def info(self):
        return core.domain_info(self.domain)

    def noun(self, count):
        return core.noun(self.domain, count)

    def system_colours(self):
        """{System No: colour index} across the tab, so each System No fold
        keeps its colour through refreshes and filters."""
        snap = self.snapshot
        if snap is None or self.domain == u"ws":
            return {}
        cached = getattr(snap, u"_system_colours", None)
        if cached is None:
            cached = core.type_colours([r.get(u"system") for r in snap.records])
            snap._system_colours = cached
        return cached

    def type_colours(self):
        """{type name: colour index} for the tab in front, from every type of
        that discipline in the model - so a type keeps its colour whichever
        service it is in and however the rows are filtered."""
        snap = self.snapshot
        if snap is None or self.domain == u"ws":
            return {}
        cached = getattr(snap, u"_colours", None)
        if cached is None:
            cached = core.type_colours([n for n, _i in snap.types] +
                                       [r.get(u"ptype") for r in snap.records])
            snap._colours = cached
        return cached

    def field_titles(self):
        if self.domain == u"ws":
            return dict(core.WS_TITLES)
        return core.field_titles(self.domain)

    def sync_toolbar(self):
        """Put the toolbar, tabs and footer wording in step with the active
        tab, without any of their handlers acting on it."""
        find = self.find
        info = self.info()
        self.syncing = True
        try:
            for domain, name in ((u"pipe", u"BtnTabPipe"), (u"duct", u"BtnTabDuct"),
                                 (u"cont", u"BtnTabCont"), (u"ws", u"BtnTabWs")):
                style = self.window.TryFindResource(
                    u"BtnTabActive" if domain == self.domain else u"BtnTab")
                if style is not None:
                    find(name).Style = style
            find(u"ChkSplitSystem").Content = info[u"system_word"]
            find(u"ChkSplitType").Content = info[u"type_word"]
            find(u"ChkSplitSystem").IsChecked = core.to_bool(self.settings.get(u"split_system"))
            find(u"ChkSplitType").IsChecked = core.to_bool(self.settings.get(u"split_type"))
            find(u"ChkSplitSize").IsChecked = core.to_bool(self.settings.get(u"split_size"))
            msm_settings.fill(find(u"CmbScope"), msm_settings.SCOPES, self.settings.get(u"scope"))
            find(u"ChkIssuesOnly").IsChecked = core.to_bool(self.settings.get(u"issues_only"))
            # the button carries an icon; only its label changes per tab
            find(u"ChangeTypeLabel").Text = u"Change {0}".format(info[u"type_word"])
            cont = self.domain == u"cont"
            ws = self.domain == u"ws"
            find(u"BtnResize").Visibility = Visibility.Visible if cont else Visibility.Collapsed
            # routing preferences: pipes and ducts; containment has none to re-apply
            find(u"BtnReapply").Visibility = (Visibility.Visible if self.domain in (u"pipe", u"duct")
                                              else Visibility.Collapsed)
            find(u"BtnService").Visibility = Visibility.Visible if cont else Visibility.Collapsed
            find(u"ChkNest").IsChecked = core.to_bool(self.settings.get(u"nest_systems"))
            find(u"ChkMultiType").Visibility = Visibility.Visible if cont else Visibility.Collapsed
            find(u"ChkMultiType").IsChecked = cont and core.to_bool(
                self.settings.get(u"multi_type_only"))
            # the Workset Assigner has its own footer and none of the discipline tools
            shown, hidden = Visibility.Visible, Visibility.Collapsed
            find(u"DisciplineTools").Visibility = hidden if ws else shown
            find(u"DisciplineTools2").Visibility = hidden if ws else shown
            find(u"WsTools").Visibility = shown if ws else hidden
            find(u"WsTools2").Visibility = shown if ws else hidden
            msm_settings.fill(find(u"CmbWsGrouping"), core.WS_GROUPINGS,
                              self.settings.get(u"ws_grouping", u"type"))
            find(u"ChkMixedOnly").IsChecked = core.to_bool(self.settings.get(u"ws_mixed_only"))
            find(u"FooterMain").Visibility = hidden if ws else shown
            find(u"FooterWs").Visibility = shown if ws else hidden
            find(u"FooterIsolate").Visibility = hidden if ws else shown
            find(u"FooterWs2").Visibility = shown if ws else hidden
            find(u"BtnApplyWs").Visibility = shown if ws else hidden
            for chip in (u"BtnChecks", u"BtnExport", u"BtnSettings"):
                find(chip).Visibility = hidden if ws else shown
            find(u"TxtSearch").Tag = u"Search every system..." if ws else u"Search every service..."
            find(u"CmbPipeType").ToolTip = u"The {0} to change the selected rows to".format(
                info[u"type_word"].lower())
            self.paint_checks_switch()
        finally:
            self.syncing = False

    def switch_tab(self, domain):
        if domain == self.domain or domain not in core.DOMAINS:
            return
        tab = self.tabs[self.domain]
        try:
            tab[u"scroll"] = self.body_scroll.VerticalOffset
        except Exception:
            pass
        tab[u"type_pick"] = self.find(u"CmbPipeType").SelectedItem
        self.domain = domain
        self.base[u"active_tab"] = domain
        core.save_settings(self.base)
        self.sync_toolbar()
        self.show_tab()

    def show_tab(self):
        """Show the active tab's sections as they were left, reading the model
        only the first time or when another model has become active."""
        if self.snapshot is None or self.read_from != self.doc_key():
            self.reload()
            return
        host = self.find(u"GroupsHost")
        host.Children.Clear()
        self.sticky_index = None
        self.find(u"StickyHeader").Visibility = Visibility.Collapsed
        if self.outers:
            # sections that live inside folds (disciplines, or service types
            # holding System No folds): put the folds back, not the sections
            for _title, outer, _made in self.outers:
                host.Children.Add(outer)
            for section in self.sections:
                section.refresh()
        else:
            for section in self.sections:
                host.Children.Add(section.expander)
                section.refresh()
        self.find(u"EmptyText").Visibility = (Visibility.Visible if not self.sections
                                              else Visibility.Collapsed)
        self.syncing = True
        try:
            if self.domain == u"ws":
                self.fill_worksets()
            self.fill_pipe_types()
            pick = self.tabs[self.domain][u"type_pick"]
            if pick is not None and pick in [n for n, _i in self.snapshot.types]:
                self.find(u"CmbPipeType").SelectedItem = pick
        finally:
            self.syncing = False
        self.on_selection_changed()
        offset = self.tabs[self.domain][u"scroll"]
        if offset is not None:
            ui.later(self.window, lambda: self.body_scroll.ScrollToVerticalOffset(offset))
        self.set_status(self.read_summary())

    def read_summary(self):
        if self.domain == u"ws":
            snap = self.snapshot
            if snap is None or not snap.workshared:
                return u"This model is not workshared - there are no worksets to assign."
            systems = len(snap.systems)
            return u"{0} system{1} under {2} system type{3}, {4} worksets. Select systems or " \
                   u"whole system types, pick a workset, Assign, then Apply.".format(
                       systems, u"" if systems == 1 else u"s", len(self.sections),
                       u"" if len(self.sections) == 1 else u"s", len(snap.worksets))
        count = len(self.snapshot.records) if self.snapshot is not None else 0
        groups = len(self.sections)
        scope = u"in the active view" if self.settings.get(u"scope") == u"view" else \
            u"in the project"
        return u"{0} {1} {2}, {3} service type{4}. Select rows, then isolate or change " \
               u"their type.".format(count, self.noun(count), scope, groups,
                                     u"" if groups == 1 else u"s")

    # ---------------- plumbing ----------------

    def safe(self, action, where):
        def handler(sender, args):
            self.prove_alive()
            if self.syncing:
                return
            if self.busy:
                waited = time.time() - (self.busy_since or time.time())
                self.dbg(u"click", u"ignored - busy", u"", u"{0} pressed {1:.0f}s into: {2}".format(
                    where, waited, self.busy_what))
                self.set_status(u"Still waiting for Revit ({0:.0f}s) - {1}".format(
                    waited, self.busy_what or u"working"), True)
                return
            try:
                action()
            except Exception:
                self.report_error(where)
        return handler

    def report_error(self, where):
        text = traceback.format_exc()
        ui.log(u"{0} failed:\n{1}".format(where, text), True)
        self.dbg(u"error", where, u"", text)
        self.set_status(u"{0} failed - details in {1}".format(where, ui.log_path()), True)

    def prove_alive(self):
        """The first handler that runs proves the persistent engine is alive:
        clear the note launch() left, so the next launch does not offer modal."""
        if self.proved_alive or not self.armed:
            return
        self.proved_alive = True
        try:
            path = os.path.join(core.settings_dir(), core.MODELESS_FLAG)
            if os.path.isfile(path):
                os.remove(path)
        except Exception:
            pass

    def on_rendered(self, sender, args):
        self.prove_alive()

    def set_status(self, text, warn=False):
        try:
            status = self.find(u"StatusText")
            status.Text = text
            grid.res(status, TextBlock.ForegroundProperty, u"Orange" if warn else u"Muted")
        except Exception:
            pass

    def palette(self):
        return theme.palette(theme.resolve(self.settings.get(u"theme")))

    def popup_layer(self):
        try:
            return self.window.Content
        except Exception:
            return None

    def global_search(self):
        try:
            return self.find(u"TxtSearch").Text or u""
        except Exception:
            return u""

    def set_busy(self, flag, text=None, watch=True):
        """Busy blocks the window while Revit runs a request. A watchdog
        frees it if Revit has not run the request within core.BUSY_TIMEOUT_S,
        so a request Revit is slow to pick up can never leave the window
        frozen until the tool is restarted."""
        self.busy = flag
        self.busy_since = time.time() if flag else None
        self.busy_what = (text or u"") if flag else u""
        # a pick waits on the user, not on Revit: no watchdog for that
        if flag and watch:
            self.start_watchdog()
        try:
            self.window.IsHitTestVisible = not flag
            fill = self.find(u"ProgressFill")
            fill.Width = self.window.ActualWidth if flag else 0
        except Exception:
            pass
        if text:
            self.set_status(text)

    def watch_runner(self):
        """Every job tells the window when Revit begins it."""
        try:
            self.runner.started = self.revit_started
        except Exception:
            pass

    def revit_started(self):
        """Revit has picked the request up: the watchdog's job is done - a
        long run is not a stuck one."""
        self.busy_since = None
        try:
            if self.watchdog is not None:
                self.watchdog.Stop()
        except Exception:
            pass

    def start_watchdog(self):
        if getattr(self, u"watchdog", None) is None:
            self.watchdog = DispatcherTimer()
            self.watchdog.Interval = TimeSpan.FromSeconds(2)
            self.watchdog.Tick += self.on_watchdog
        self.watchdog.Start()

    def on_watchdog(self, sender, args):
        try:
            if not self.busy:
                self.watchdog.Stop()
                return
            if self.busy_since is None:
                self.watchdog.Stop()            # Revit is running it
                return
            if core.busy_expired(self.busy_since, time.time()):
                waited = time.time() - self.busy_since
                self.watchdog.Stop()
                self.dbg(u"watchdog", u"freed", u"", u"{0} not started by Revit after {1:.0f}s - "
                         u"window freed".format(self.busy_what or u"a request", waited))
                self.set_busy(False)
                self.set_status(u"Revit had not started the last request after {0:.0f}s - it "
                                u"starts when Revit is idle (finish any command or dialog in "
                                u"Revit). The window is free again.".format(waited), True)
        except Exception:
            pass

    # ---------------- theme ----------------

    def paint_theme_label(self):
        self.find(u"ThemeLabel").Text = theme.label(self.settings.get(u"theme"))

    def cycle_theme(self):
        self.settings[u"theme"] = theme.next_mode(self.settings.get(u"theme"))
        theme.apply(self.window, self.settings[u"theme"])
        self.paint_theme_label()
        core.save_settings(self.settings)

    # ---------------- reading ----------------

    def active_view(self):
        try:
            return self.uiapp.ActiveUIDocument.ActiveView
        except Exception:
            return None

    def doc_key(self):
        try:
            doc = self.uiapp.ActiveUIDocument.Document
            return u"{0}|{1}".format(doc.Title, doc.PathName)
        except Exception:
            return u""

    def same_document(self):
        """The ids in the table belong to the document that was read. If
        another model is active now, writing them would hit the wrong one."""
        if self.doc_key() == self.read_from:
            return True
        self.set_status(u"A different model is active now - press Refresh (F5) to read it.", True)
        return False

    def reload(self):
        started = time.time()
        doc = self.uiapp.ActiveUIDocument.Document
        kept = self.capture_view_state()
        self.read_from = self.doc_key()
        view = self.active_view() if self.settings.get(u"scope") == u"view" else None
        self.set_status(u"Reading {0}...".format(self.noun(2)))
        if self.domain == u"ws":
            self.snapshot = model.read_worksets(doc, core.DomainView(self.base, u"cont"))
            self.fill_worksets()
        else:
            self.snapshot = model.read(doc, self.settings, view, self.domain)
        self.fill_views()
        self.syncing = True
        try:
            self.fill_pipe_types()
        finally:
            self.syncing = False
        self.build_sections(kept, announce=False)
        self.set_status(self.read_summary())
        ui.log(u"{0}: read {1} {2}, {3} groups".format(
            self.domain, len(self.snapshot.records), self.noun(2), len(self.sections)),
            self.debug)
        if self.debug and self.domain == u"ws":
            self.dbg(u"read", u"worksets", u"", u"{0} systems, {1} worksets, workshared {2}, "
                     u"{3:.2f}s".format(len(self.snapshot.systems), len(self.snapshot.worksets),
                                        self.snapshot.workshared, time.time() - started))
        elif self.debug:
            records = self.snapshot.records
            flagged = sum([len([r for r in s.rows if r.get(u"flag")]) for s in self.sections])
            self.dbg(u"read", u"done", u"", u"{0} {1}, {2} types, {3} groups, {4} flagged rows, "
                     u"scope {5}, {6:.2f}s".format(
                         len(records), self.noun(len(records)), len(self.snapshot.types),
                         len(self.sections), flagged, self.settings.get(u"scope"),
                         time.time() - started))
            first = not self.tabs[self.domain].get(u"sampled")
            self.tabs[self.domain][u"sampled"] = True
            for record in (records[:40] if first else []):
                self.dbg(u"read", u"sample", record.get(u"id"), u"; ".join(
                    [u"{0}={1}".format(k, record.get(k)) for k in
                     (u"kind", u"system", u"system_type", u"ptype", u"size_text", u"open_ends",
                      u"mismatch", u"size_ok", u"has_system", u"system_id")
                     if k in record]))
        self.announce_kept()

    def fill_views(self):
        combo = self.find(u"CmbView")
        self.view_choices = [(core.DEFAULT_VIEW_LABEL, 0)] + list(self.snapshot.views_3d)
        last = self.settings.get(u"last_view", u"")
        combo.Items.Clear()
        chosen = 0
        for index, (name, _id) in enumerate(self.view_choices):
            combo.Items.Add(name)
            if name == last:
                chosen = index
        combo.SelectedIndex = chosen

    def fill_pipe_types(self):
        """The dropdown holds the types the search box lets through;
        self.type_choices keeps them in step, so a pick is read from the list
        on screen, never by its place in the full one."""
        combo = self.find(u"CmbPipeType")
        previous = combo.SelectedItem
        text = self.find(u"TxtTypeSearch").Text or u""
        shown, matched = core.filter_choices(self.snapshot.types, text)
        self.type_choices = shown
        combo.Items.Clear()
        for name, _id in shown:
            combo.Items.Add(name)
        names = [n for n, _i in shown]
        if previous is not None and previous in names:
            combo.SelectedItem = previous
        elif len(shown) == 1 and text.strip():
            combo.SelectedIndex = 0
        else:
            combo.SelectedIndex = -1
        return matched

    def on_type_search(self):
        if self.snapshot is None or self.domain == u"ws":
            return
        text = (self.find(u"TxtTypeSearch").Text or u"").strip()
        matched = self.fill_pipe_types()
        if not matched:
            self.set_status(u"No type holds '{0}' - showing them all.".format(text), True)
        elif text:
            count = len(self.type_choices)
            self.set_status(u"{0} type{1} match '{2}'.".format(
                count, u"" if count == 1 else u"s", text))
        self.on_selection_changed()

    def build_sections(self, kept=None, announce=True):
        if kept is None:
            kept = self.capture_view_state()
        expanded = set(core.split_list(self.settings.get(u"expanded")))
        host = self.find(u"GroupsHost")
        host.Children.Clear()
        self.sections = []
        self.outers = []
        self.sticky_index = None
        self.find(u"StickyHeader").Visibility = Visibility.Collapsed
        if self.domain == u"ws":
            self.build_workset_sections(kept, expanded, host, announce)
            return
        groups = core.build_groups(
            self.snapshot.records, self.settings.get(u"group_by"),
            core.to_bool(self.settings.get(u"split_system")),
            core.to_bool(self.settings.get(u"split_type")),
            core.to_bool(self.settings.get(u"split_size")),
            core.decode_standards(self.settings.get(u"standards")),
            core.enabled_checks(self.settings, self.domain),
            self.domain)
        # containment: each service type's heading lists the types it uses,
        # and the tick can narrow the page to the services using more than one
        notes = {}
        parts = {}
        multi = set()
        multi_only = False
        if self.domain == u"cont":
            by_group = core.types_by_group(self.snapshot.records, self.settings.get(u"group_by"))
            multi = core.multi_type_groups(by_group)
            multi_only = core.to_bool(self.settings.get(u"multi_type_only"))
            colours = self.type_colours()
            parts = {}
            for group, counts in by_group.items():
                notes[group] = core.type_summary(counts)[0]
                parts[group] = core.summary_parts(counts, colours)
            self.find(u"ChkMultiType").Content = \
                u"Only service types using more than one type ({0})".format(len(multi))
        # System No folds: only when rows are split by System No, or every
        # service would be one fold called "N systems"
        nest = core.to_bool(self.settings.get(u"nest_systems")) and \
            core.to_bool(self.settings.get(u"split_system"))
        for name in core.group_order(list(groups.keys())):
            if multi_only and name not in multi:
                continue
            if nest:
                self.build_nested_service(host, name, groups[name], expanded, notes.get(name, u""),
                                          parts.get(name) if self.domain == u"cont" else None,
                                          name in multi)
                continue
            section = grid.GroupSection(self, name, groups[name], name in expanded,
                                        None, notes.get(name, u""),
                                        core.default_sort(self.domain),
                                        u"Orange" if name in multi else u"Blue",
                                        parts.get(name) if self.domain == u"cont" else None)
            host.Children.Add(section.expander)
            self.sections.append(section)
        self.find(u"EmptyText").Visibility = (Visibility.Visible if not self.sections
                                              else Visibility.Collapsed)
        try:
            self.find(u"EmptyText").Text = (
                u"Every service type uses a single type." if multi_only and groups else
                u"No {0} found.".format(self.noun(2)))
        except Exception:
            pass
        self.restore_view_state(kept)
        self.on_selection_changed()
        if announce:
            self.announce_kept()

    # ---------------- System No folds ----------------

    def build_nested_service(self, host, service, rows, expanded, note, note_parts, multi):
        """A service type as a fold of System No folds, each holding that
        system's rows - the same table, sorts and filters as ever."""
        outer = Expander()
        outer.IsExpanded = service in expanded
        outer.Margin = Thickness(0, 0, 0, 6)
        holder = StackPanel()
        holder.Margin = Thickness(18, 2, 0, 4)
        outer.Content = holder
        made = []
        colours = self.system_colours()
        for system, system_rows in core.nest_by_system(rows):
            key = core.nested_name(service, system)
            colour = colours.get(system)
            section = grid.GroupSection(self, key, system_rows, key in expanded, None, u"",
                                        core.default_sort(self.domain), u"Blue", None,
                                        system or core.UNASSIGNED,
                                        u"Type{0}".format(colour) if colour is not None else None)
            section.outer = outer
            holder.Children.Add(section.expander)
            self.sections.append(section)
            made.append(section)
        outer.Header = self.service_header(service, made, note, note_parts, multi)
        outer.Expanded += lambda s, a: self.on_expand_changed()
        outer.Collapsed += lambda s, a: self.on_expand_changed()
        host.Children.Add(outer)
        self.outers.append((service, outer, made))

    def service_header(self, service, sections, note, note_parts, multi):
        rows = [r for s in sections for r in s.rows]
        elements = sum([int(r.get(u"count") or 0) for r in rows])
        flagged = len([r for r in rows if r.get(u"flag")])
        panel = DockPanel()
        panel.LastChildFill = False
        for text, state in ((u"Close all", False), (u"Open all", True)):
            button = Button()
            button.Content = text
            button.Padding = Thickness(10, 1, 10, 1)
            button.MinHeight = 24
            button.FontSize = 11.5
            button.Margin = Thickness(6, 0, 0, 0)
            button.ToolTip = u"{0} every system number under {1}".format(
                u"Open" if state else u"Close", service)
            button.Click += self.safe(lambda state=state, made=sections:
                                      self.open_sections(made, state), u"Open or close")
            DockPanel.SetDock(button, Dock.Right)
            panel.Children.Add(button)
        if note_parts or note:
            summary = TextBlock()
            summary.FontSize = 11.5
            summary.FontWeight = FontWeights.SemiBold
            summary.VerticalAlignment = VerticalAlignment.Center
            summary.Margin = Thickness(0, 0, 12, 0)
            summary.MaxWidth = 520
            summary.TextTrimming = TextTrimming.CharacterEllipsis
            summary.ToolTip = note
            if note_parts:
                for text, colour in note_parts:
                    run = Run(text)
                    grid.res(run, TextElement.ForegroundProperty,
                             u"Type{0}".format(colour) if colour is not None else u"Muted")
                    summary.Inlines.Add(run)
            else:
                summary.Text = note
                grid.res(summary, TextBlock.ForegroundProperty, u"Orange" if multi else u"Blue")
            DockPanel.SetDock(summary, Dock.Right)
            panel.Children.Add(summary)
        name = TextBlock()
        name.Text = service
        name.FontSize = 14.5
        name.FontWeight = FontWeights.Bold
        grid.res(name, TextBlock.ForegroundProperty, u"Text")
        panel.Children.Add(name)
        count = TextBlock()
        count.Text = u"   {0} system{1} \u00b7 {2} {3}".format(
            len(sections), u"" if len(sections) == 1 else u"s", elements, self.noun(elements))
        count.VerticalAlignment = VerticalAlignment.Center
        grid.res(count, TextBlock.ForegroundProperty, u"Muted")
        panel.Children.Add(count)
        if flagged:
            flag = TextBlock()
            flag.Text = u"   {0} row{1} need{2} a look".format(
                flagged, u"" if flagged == 1 else u"s", u"s" if flagged == 1 else u"")
            flag.FontWeight = FontWeights.SemiBold
            flag.VerticalAlignment = VerticalAlignment.Center
            grid.res(flag, TextBlock.ForegroundProperty, u"Red")
            panel.Children.Add(flag)
        return panel

    def on_nest(self):
        self.settings[u"nest_systems"] = core.from_bool(bool(self.find(u"ChkNest").IsChecked))
        core.save_settings(self.settings)
        self.build_sections()

    # ---------------- the Workset Assigner ----------------

    def workset_names(self):
        return dict((number, name) for name, number in (self.snapshot.worksets or []))

    def fill_worksets(self):
        """The dropdown holds only the worksets the search box lets through;
        self.ws_choices keeps them in step, so a pick is always read from the
        list on screen, not by its place in the full one."""
        combo = self.find(u"CmbWorkset")
        previous = combo.SelectedItem
        text = self.find(u"TxtWorksetSearch").Text or u""
        shown, matched = core.filter_choices(self.snapshot.worksets, text)
        self.ws_choices = shown
        combo.Items.Clear()
        for name, _number in shown:
            combo.Items.Add(name)
        names = [n for n, _i in shown]
        if previous is not None and previous in names:
            combo.SelectedItem = previous
        elif len(shown) == 1 and text.strip():
            combo.SelectedIndex = 0
        return matched

    def on_workset_search(self):
        if self.snapshot is None or self.domain != u"ws":
            return
        text = self.find(u"TxtWorksetSearch").Text or u""
        matched = self.fill_worksets()
        if not matched:
            self.set_status(u"No workset holds '{0}' - showing them all.".format(text.strip()),
                            True)
        elif text.strip():
            count = len(self.ws_choices)
            self.set_status(u"{0} workset{1} match '{2}'.".format(
                count, u"" if count == 1 else u"s", text.strip()))
        self.on_selection_changed()

    def build_workset_sections(self, kept, expanded, host, announce):
        """Two levels: a discipline expander (Containment / Pipework /
        Ductwork) holding a section per system type - or, grouped by
        discipline only, one section with the system type as a column."""
        snap = self.snapshot
        pending = self.tabs[u"ws"][u"pending"]
        grouping = self.settings.get(u"ws_grouping", u"type")
        mixed_only = core.to_bool(self.settings.get(u"ws_mixed_only"))
        tree = core.workset_tree(snap.systems, pending, self.workset_names(), grouping,
                                 mixed_only)
        self.outers = []
        for title, sections in tree:
            outer = Expander()
            outer.IsExpanded = title in expanded
            outer.Margin = Thickness(0, 0, 0, 6)
            holder = StackPanel()
            holder.Margin = Thickness(18, 2, 0, 4)
            outer.Content = holder
            made = []
            for name, rows, note in sections:
                if grouping == u"discipline":
                    # one list per discipline: the discipline expander is the
                    # only fold, so the list inside it is always open
                    section = grid.GroupSection(self, name, rows, True,
                                                core.WS_FIELDS_FLAT, u"",
                                                [(u"system_type", False), (u"system", False)])
                else:
                    section = grid.GroupSection(self, name, rows, name in expanded,
                                                core.WS_FIELDS, u"Type on: " + note)
                section.outer = outer
                holder.Children.Add(section.expander)
                self.sections.append(section)
                made.append(section)
            outer.Header = self.discipline_header(title, made, grouping)
            outer.Expanded += lambda s, a: self.on_expand_changed()
            outer.Collapsed += lambda s, a: self.on_expand_changed()
            host.Children.Add(outer)
            self.outers.append((title, outer, made))
        mixed = core.mixed_count(snap.systems)
        self.find(u"ChkMixedOnly").Content = u"Only systems on more than one workset ({0})".format(
            mixed)
        empty = self.find(u"EmptyText")
        empty.Visibility = Visibility.Visible if not self.sections else Visibility.Collapsed
        try:
            if not snap.workshared:
                empty.Text = u"This model is not workshared - there are no worksets to assign."
            elif mixed_only:
                empty.Text = u"No system is on more than one workset."
            else:
                empty.Text = u"No systems found."
        except Exception:
            pass
        self.restore_view_state(kept)
        self.on_selection_changed()
        if announce:
            self.announce_kept()

    def discipline_header(self, title, sections, grouping):
        rows = [r for s in sections for r in s.rows]
        mixed = len([r for r in rows if r.get(u"mixed")])
        panel = DockPanel()
        panel.LastChildFill = False
        for text, handler in ((u"Close all", False), (u"Open all", True)):
            button = Button()
            button.Content = text
            button.Padding = Thickness(10, 1, 10, 1)
            button.MinHeight = 24
            button.FontSize = 11.5
            button.Margin = Thickness(6, 0, 0, 0)
            button.ToolTip = u"{0} every system type under {1}".format(
                u"Open" if handler else u"Close", title)
            button.Click += self.safe(lambda state=handler, made=sections:
                                      self.open_sections(made, state), u"Open or close")
            DockPanel.SetDock(button, Dock.Right)
            panel.Children.Add(button)
        name = TextBlock()
        name.Text = title
        name.FontSize = 15
        name.FontWeight = FontWeights.Bold
        grid.res(name, TextBlock.ForegroundProperty, u"Blue")
        panel.Children.Add(name)
        count = TextBlock()
        count.Text = u"   {0} system{1}{2}".format(
            len(rows), u"" if len(rows) == 1 else u"s",
            u"" if grouping == u"discipline" else u" \u00b7 {0} system type{1}".format(
                len(sections), u"" if len(sections) == 1 else u"s"))
        count.VerticalAlignment = VerticalAlignment.Center
        grid.res(count, TextBlock.ForegroundProperty, u"Muted")
        panel.Children.Add(count)
        if mixed:
            flag = TextBlock()
            flag.Text = u"   {0} on more than one workset".format(mixed)
            flag.FontWeight = FontWeights.SemiBold
            flag.VerticalAlignment = VerticalAlignment.Center
            grid.res(flag, TextBlock.ForegroundProperty, u"Red")
            panel.Children.Add(flag)
        return panel

    def open_sections(self, sections, state):
        for section in sections:
            section.expander.IsExpanded = state
            if state and section.outer is not None:
                section.outer.IsExpanded = True
        self.on_expand_changed()

    def on_multi_type(self):
        state = bool(self.find(u"ChkMultiType").IsChecked)
        self.settings[u"multi_type_only"] = core.from_bool(state)
        core.save_settings(self.settings)
        self.build_sections()
        if state:
            count = len(self.sections)
            self.set_status(u"{0} service type{1} use more than one type - each heading lists "
                            u"them.".format(count, u"" if count == 1 else u"s") if count else
                            u"Every service type uses a single type.")

    def on_ws_grouping(self):
        grouping = msm_settings.picked(self.find(u"CmbWsGrouping"), core.WS_GROUPINGS)
        if grouping == self.settings.get(u"ws_grouping"):
            return
        self.settings[u"ws_grouping"] = grouping
        core.save_settings(self.settings)
        self.build_sections()

    def on_mixed_only(self):
        state = bool(self.find(u"ChkMixedOnly").IsChecked)
        self.settings[u"ws_mixed_only"] = core.from_bool(state)
        core.save_settings(self.settings)
        self.build_sections()
        if state:
            for _title, outer, made in self.outers:
                outer.IsExpanded = True
                for section in made:
                    section.expander.IsExpanded = True
            count = len([r for s in self.sections for r in s.rows])
            self.set_status(u"{0} system{1} on more than one workset - select them, pick the "
                            u"right workset, Assign, then Apply.".format(
                                count, u"" if count == 1 else u"s") if count else
                            u"No system is on more than one workset.")

    def paint_pending(self):
        pending = self.tabs[u"ws"][u"pending"]
        find = self.find
        count = len(pending)
        find(u"PendingText").Text = (u"Nothing staged" if not count else
                                     u"{0} system{1} staged - not written until Apply".format(
                                         count, u"" if count == 1 else u"s"))
        find(u"BtnClearAll").IsEnabled = bool(count)
        find(u"BtnApplyWs").IsEnabled = bool(count)
        find(u"BtnApplyWs").Content = u"Apply ({0})".format(count) if count else u"Apply"

    def stage_workset(self):
        rows = self.selected_rows()
        index = self.find(u"CmbWorkset").SelectedIndex
        if not rows or index < 0:
            self.set_status(u"Select systems and a workset first.", True)
            return
        choices = getattr(self, u"ws_choices", None) or self.snapshot.worksets
        if index >= len(choices):
            self.set_status(u"Pick the workset again.", True)
            return
        name, number = choices[index]
        tab = self.tabs[u"ws"]
        keys = [r[u"key"] for r in rows]
        tab[u"pending"] = core.stage_worksets(tab[u"pending"], keys, number)
        self.build_sections()
        # let the staged rows show orange: a selected row is drawn in the
        # selection colour, which hid that anything had happened
        for section in self.sections:
            section.clear_selection()
        self.on_selection_changed()
        total = len(tab[u"pending"])
        self.set_status(u"{0} system{1} staged for {2} - shown orange. Nothing is written until "
                        u"you press Apply ({3}) at the bottom right.".format(
                            len(rows), u"" if len(rows) == 1 else u"s", name, total))
        self.dbg(u"worksets", u"staged", u"", u"{0} systems -> {1} ({2}); {3} staged in all: {4}"
                 .format(len(rows), name, number, total, u", ".join(keys[:30])))

    def unstage_workset(self):
        rows = self.selected_rows()
        tab = self.tabs[u"ws"]
        pending = dict(tab[u"pending"])
        for row in rows:
            pending.pop(row[u"key"], None)
        tab[u"pending"] = pending
        self.build_sections()

    def clear_staged(self):
        self.tabs[u"ws"][u"pending"] = {}
        self.build_sections()
        self.set_status(u"Nothing staged.")

    def apply_worksets(self):
        pending = self.tabs[u"ws"][u"pending"]
        self.dbg(u"worksets", u"apply pressed", u"", u"{0} staged".format(len(pending)))
        if not pending:
            self.set_status(u"Nothing staged to apply - select systems, pick a workset and "
                            u"Assign to selected first.", True)
            self.dbg(u"worksets", u"apply stopped", u"", u"nothing staged")
            return
        if not self.same_document():
            self.dbg(u"worksets", u"apply stopped", u"", u"a different model is active")
            return
        names = self.workset_names()
        # from the whole read, so a staged system a filter hides is still applied
        rows = core.staged_rows(self.snapshot.systems, pending, names)
        total, text = core.workset_plan_text(rows, pending, names)
        body = u"Move {0} element{1} to new worksets:\n\n{2}\n\nOnly pipework is moved - " \
               u"pipes, ducts, trays, conduits, their fittings and accessories. Revit's undo " \
               u"takes it all back in one step.".format(total, u"" if total == 1 else u"s", text)
        if not ui.message(self.window, u"Apply worksets", body, u"Apply", u"Cancel",
                          self.settings.get(u"theme")):
            self.set_status(u"Nothing written - the staged worksets are still there.")
            self.dbg(u"worksets", u"apply stopped", u"", u"cancelled at the confirm")
            return
        assignments = [(u"{0} - {1}".format(r[u"group"], r[u"system"]), r[u"ids"],
                        pending[r[u"key"]]) for r in rows]
        missing = [k for k in pending if k not in set([r[u"key"] for r in rows])]
        self.dbg(u"worksets", u"apply sent", u"", u"{0} systems, {1} elements{2}".format(
            len(assignments), total,
            u"; staged but no longer in the model: " + u", ".join(missing) if missing else u""))
        self.set_busy(True, u"Moving {0} elements...".format(total))
        job = ops.workset_job(assignments)
        sent = self.runner.run(job, lambda result: ui.later(self.window,
                                                            lambda: self.worksets_done(result)))
        self.dbg(u"worksets", u"request", u"", u"Revit said {0}".format(sent))

    def worksets_done(self, result):
        self.set_busy(False)
        self.dbg_result(u"worksets", result)
        if result.error:
            ui.log(u"worksets failed:\n" + result.error, True)
            self.set_status(u"Apply failed - nothing was written. Details in the log.", True)
            self.show_results(u"Apply worksets", result.error, True)
            return
        d = result.data
        self.tabs[u"ws"][u"pending"] = {}
        summary = u"{0} of {1} system{2} done - {3} element{4} moved, {5} already on the " \
                  u"right workset.".format(
                      d.get(u"systems_done", 0), d.get(u"systems", 0),
                      u"" if d.get(u"systems") == 1 else u"s", d.get(u"changed", 0),
                      u"" if d.get(u"changed") == 1 else u"s", d.get(u"already", 0))
        needs_look = bool(d.get(u"failed") or d.get(u"locked") or d.get(u"not_taken"))
        self.reload()
        self.set_status(summary + (u" Some need a look." if needs_look else u""), needs_look)
        lines = [summary, u""]
        for key, title in ((u"locked", u"Held by somebody else - skipped"),
                           (u"failed", u"Revit would not move"),
                           (u"not_taken", u"Not every element moved")):
            items = d.get(key) or []
            if items:
                lines.append(u"{0} ({1}):".format(title, len(items)))
                lines.extend([u"   {0}".format(i) for i in items[:30]])
                lines.append(u"")
        self.show_results(u"Apply worksets", u"\n".join(lines), needs_look)

    # ---------------- containment: change service type ----------------

    def change_service(self):
        if self.domain != u"cont":
            return
        rows = self.selected_rows()
        ids = core.selected_ids(rows)
        if not ids:
            self.set_status(u"Select one or more rows first.", True)
            return
        if not self.same_document():
            return
        records = self.snapshot.records
        kinds = dict((r[u"id"], r.get(u"kind")) for r in records)
        group_by = self.settings.get(u"group_by")
        system_from = self.settings.get(u"system_from")
        counts = {}
        for scope, _label in core.SERVICE_SCOPES:
            reach = core.service_scope_ids(records, ids, scope, group_by, system_from)
            counts[scope] = (len([i for i in reach if kinds.get(i) == u"tray"]),
                             len([i for i in reach if kinds.get(i) == u"conduit"]))
        services_now = sorted(set([r[u"group"] for r in rows]), key=core.natural_key)
        every = sorted(set([s.name for s in self.sections if s.name != core.UNASSIGNED]),
                       key=core.natural_key)
        parameter = self.settings.get(u"group_param") if group_by == u"param" \
            else u"Service Type"
        dialog = msm_service.ServiceDialog(self.window, self.settings, services_now, every,
                                           counts, parameter)
        answer = dialog.show()
        if not answer:
            self.set_status(u"Nothing changed.")
            return
        reach = core.service_scope_ids(records, ids, answer[u"scope"], group_by, system_from)
        trays, conduits = counts[answer[u"scope"]]
        body = u"Change the service type of {0} tray{1} and {2} conduit{3} to:  {4}\n\n" \
               u"From: {5}\nFittings on those runs: {6}\nWrites: {7}".format(
                   trays, u"" if trays == 1 else u"s", conduits, u"" if conduits == 1 else u"s",
                   answer[u"value"], u", ".join(services_now),
                   u"yes" if answer[u"fittings"] else u"no", parameter)
        if not ui.message(self.window, u"Change service type", body, u"Change", u"Cancel",
                          self.settings.get(u"theme")):
            self.set_status(u"Nothing changed.")
            return
        self.dbg(u"service", u"asked", u"", u"{0} -> {1}, scope {2}, {3} elements, fittings {4}"
                 .format(u", ".join(services_now), answer[u"value"], answer[u"scope"], len(reach),
                         answer[u"fittings"]))
        self.set_busy(True, u"Changing the service type of {0} {1}...".format(
            len(reach), self.noun(len(reach))))
        job = ops.service_job(reach, answer[u"value"], answer[u"fittings"],
                              self.settings.resolved())
        self.runner.run(job, lambda result: ui.later(
            self.window, lambda: self.service_done(result, answer[u"value"])))

    def service_done(self, result, value):
        self.set_busy(False)
        self.dbg_result(u"service", result)
        if result.error:
            self.set_status(result.error.strip().splitlines()[-1], True)
            self.show_results(u"Change service type", result.error, True)
            return
        d = result.data
        summary = u"{0} element{1} now on {2}{3}.".format(
            d.get(u"changed", 0), u"" if d.get(u"changed") == 1 else u"s", value,
            u" (including {0} fittings)".format(d.get(u"fittings")) if d.get(u"fittings") else u"")
        needs_look = bool(d.get(u"failed") or d.get(u"locked") or d.get(u"not_taken"))
        self.reload()
        self.set_status(summary + (u" Some need a look." if needs_look else u""), needs_look)
        if needs_look:
            lines = [summary, u""]
            for key, title in ((u"locked", u"Held by somebody else - skipped"),
                               (u"failed", u"Could not be set"),
                               (u"not_taken", u"Did not take")):
                items = d.get(key) or []
                if items:
                    lines.append(u"{0} ({1}):".format(title, len(items)))
                    lines.extend([u"   {0}".format(i) for i in items[:30]])
                    lines.append(u"")
            self.show_results(u"Change service type", u"\n".join(lines), True)

    # ---------------- the frozen system type heading ----------------

    STICKY_HEIGHT = 36.0

    def section_extents(self):
        """[(top, bottom, open)] for each section, from the top of the visible
        page - a section folded away inside a closed discipline counts as
        not there."""
        out = []
        for section in self.sections:
            try:
                expander = section.expander
                outer = getattr(section, u"outer", None)
                if not expander.IsVisible or (outer is not None and not outer.IsExpanded):
                    out.append((float(u"inf"), float(u"inf"), False))
                    continue
                top = expander.TranslatePoint(Point(0, 0), self.body_scroll).Y
                out.append((top, top + expander.ActualHeight, bool(expander.IsExpanded)))
            except Exception:
                out.append((float(u"inf"), float(u"inf"), False))
        return out

    def on_body_scroll(self, sender, args):
        try:
            self.update_sticky()
        except Exception:
            pass                            # a heading is a nicety, never a failure

    def sticky_columns(self, section):
        """The pinned system type's column headings, the same width and at the
        same place as its table's, the sorted one boxed in its sort colour.
        Clicking one sorts the table, as its own heading would."""
        host = self.find(u"StickyColumns")
        try:
            grid_x = section.grid.TranslatePoint(Point(0, 0), self.body_scroll).X
        except Exception:
            grid_x = 0.0
        columns = []
        for field, column in zip(section.fields, list(section.grid.Columns)):
            try:
                if column.Visibility != Visibility.Visible:
                    continue
                columns.append((field, column.ActualWidth))
            except Exception:
                pass
        signature = (id(section), round(grid_x), tuple([(f, round(w)) for f, w in columns]),
                     tuple(section.sort_stack))
        if signature == getattr(self, u"sticky_signature", None):
            return
        self.sticky_signature = signature
        host.Children.Clear()
        # the overlay sits 1 in and is padded 14; the table starts at grid_x
        host.Margin = Thickness(max(0.0, grid_x - 15.0), 6, 0, 0)
        for field, width in columns:
            text, colour = section.header_text(field)
            cell = Border()
            cell.Width = max(0.0, width)
            cell.BorderThickness = Thickness(1.5)
            cell.CornerRadius = CornerRadius(3)
            cell.Padding = Thickness(4, 2, 4, 2)
            if colour:
                grid.res(cell, Border.BorderBrushProperty, colour)
            label = TextBlock()
            label.Text = text
            label.FontWeight = FontWeights.SemiBold
            label.FontSize = 12
            label.TextTrimming = TextTrimming.CharacterEllipsis
            grid.res(label, TextBlock.ForegroundProperty, colour or u"Muted")
            cell.Child = label
            cell.Cursor = Cursors.Hand
            cell.ToolTip = u"Sort by {0} - Shift adds a level".format(
                self.field_titles().get(field, field))
            cell.MouseLeftButtonUp += self.sticky_sort_handler(section, field)
            host.Children.Add(cell)

    def sticky_sort_handler(self, section, field):
        def handler(sender, args):
            try:
                args.Handled = True             # a sort, not a jump back up
                shift = (Keyboard.Modifiers & ModifierKeys.Shift) == ModifierKeys.Shift
                section.sort_by(field, shift)
                self.update_sticky(force=True)
            except Exception:
                self.report_error(u"Sorting")
        return handler

    def update_sticky(self, force=False):
        if force:
            self.sticky_signature = None
            self.sticky_index = None
        header = self.find(u"StickyHeader")
        extents = [e for e in self.section_extents()]
        # sections folded away sit at infinity; drop them, keeping the index
        shown = [(i, e) for i, e in enumerate(extents) if e[0] != float(u"inf")]
        height = header.ActualHeight or self.STICKY_HEIGHT
        index, push = core.sticky_pick([e for _i, e in shown], height)
        if index is None:
            header.Visibility = Visibility.Collapsed
            self.sticky_index = None
            return
        section = self.sections[shown[index][0]]
        if self.sticky_index is not section:
            self.sticky_index = section
            find = self.find
            title = section.name
            if u" \u00b7 " in title:
                title = title.replace(u" \u00b7 ", u"  \u203a  ", 1)
            find(u"StickyTitle").Text = title
            find(u"StickyNote").Text = section.note or u""
            try:
                find(u"StickyCount").Text = section.count_text.Text
                find(u"StickyFlag").Text = section.flag_text.Text
            except Exception:
                find(u"StickyCount").Text = u""
                find(u"StickyFlag").Text = u""
        self.sticky_columns(section)
        header.Margin = Thickness(1, push, 14, 0)
        header.Visibility = Visibility.Visible

    def on_sticky_click(self, sender, args):
        """Back up to the pinned system type's own heading."""
        try:
            section = self.sticky_index
            if section is None:
                return
            top = section.expander.TranslatePoint(Point(0, 0), self.body_scroll).Y
            self.body_scroll.ScrollToVerticalOffset(max(0.0, self.body_scroll.VerticalOffset + top))
        except Exception:
            pass

    # ---------------- Re-apply Type ----------------

    def reapply_type(self):
        if self.domain not in (u"pipe", u"duct"):
            return
        rows = self.selected_rows()
        ids = core.selected_ids(rows)
        if not ids:
            self.set_status(u"Select one or more systems first.", True)
            return
        if not self.same_document():
            return
        systems = sorted(set([r.get(u"system") or u"" for r in rows]), key=core.natural_key)
        types = sorted(set([r.get(u"ptype") or u"" for r in rows]), key=core.natural_key)
        retain = core.split_list(self.settings.get(u"retain", u""))
        body = (u"Re-apply the {0} of {1} {2} on {3} system{4}:\n   {5}\n\n"
                u"Types: {6}\n\n"
                u"Every fitting on them is put back to what its type's routing preferences "
                u"call for, as Revit's Reapply Type does. A fitting between a selected {7} and "
                u"one left alone, or between two types, is not touched. Parameters kept: {8}."
                .format(self.info()[u"type_word"].lower(), len(ids), self.noun(len(ids)),
                        len(systems), u"" if len(systems) == 1 else u"s",
                        u", ".join(systems[:12]) + (u" ..." if len(systems) > 12 else u""),
                        u", ".join(types[:6]) + (u" ..." if len(types) > 6 else u""),
                        self.info()[u"noun"][0], u", ".join(retain) or u"none ticked"))
        if not ui.message(self.window, u"Re-apply Type", body, u"Re-apply", u"Cancel",
                          self.settings.get(u"theme")):
            self.set_status(u"Nothing changed.")
            return
        self.dbg(u"reapply", u"asked", u"", u"{0} {1} on {2} systems".format(
            len(ids), self.noun(len(ids)), len(systems)))
        self.set_busy(True, u"Re-applying the type to {0} {1}...".format(len(ids),
                                                                         self.noun(len(ids))))
        status = self.runner.run(ops.reapply_job(ids, self.settings.resolved()),
                                 lambda result: ui.later(self.window,
                                                         lambda: self.reapply_done(result)))
        self.dbg(u"reapply", u"request", u"", u"Revit said {0}".format(status))

    def reapply_done(self, result):
        self.set_busy(False)
        self.dbg_result(u"reapply", result)
        if result.error:
            self.set_status(result.error.strip().splitlines()[-1], True)
            self.show_results(u"Re-apply Type", result.error, True)
            return
        d = result.data
        summary = u"{0} fitting{1} put back to the routing preferences, {2} already right.".format(
            d.get(u"fittings_swapped", 0), u"" if d.get(u"fittings_swapped") == 1 else u"s",
            d.get(u"fittings_already", 0))
        if d.get(u"values_restored"):
            summary += u" {0} retained value{1} written back.".format(
                d.get(u"values_restored"), u"" if d.get(u"values_restored") == 1 else u"s")
        needs_look = bool(d.get(u"fitting_failed") or d.get(u"locked") or d.get(u"not_restored"))
        self.reload()
        self.set_status(summary + (u" Some need a look." if needs_look else u""), needs_look)
        lines = [summary, u""]
        left = d.get(u"not_selected", 0) + d.get(u"mixed_types", 0)
        if left:
            lines.append(u"{0} fitting{1} left alone - joining a selected {2} to one not "
                         u"selected, or joining two types.".format(
                             left, u"" if left == 1 else u"s", self.info()[u"noun"][0]))
            lines.append(u"")
        for key, title in ((u"locked", u"Held by somebody else - skipped"),
                           (u"fitting_failed", u"Could not be re-applied"),
                           (u"not_restored", u"Retained values that did not go back")):
            items = d.get(key) or []
            if items:
                lines.append(u"{0} ({1}):".format(title, len(items)))
                lines.extend([u"   {0}".format(i) for i in items[:30]])
                lines.append(u"")
        self.show_results(u"Re-apply Type", u"\n".join(lines), needs_look)

    # ---------------- Pick System ----------------

    def pick_system(self):
        """Pick an element in Revit; its system is found, on its own tab, and
        selected in the list."""
        self.dbg(u"pick", u"pressed", u"", u"tab {0}".format(self.domain))
        self.set_busy(True, u"Pick a pipe, duct, cable tray or conduit in Revit - Esc to cancel.",
                      watch=False)
        lookup = core.to_bool(self.settings.get(u"lookup_linked"))
        status = self.runner.run(ops.pick_job(lookup), lambda result: ui.later(
            self.window, lambda: self.pick_done(result)))
        self.dbg(u"pick", u"request", u"", u"Revit said {0}".format(status))

    def pick_done(self, result):
        self.set_busy(False)
        self.dbg_result(u"pick", result)
        if result.get(u"cancelled"):
            self.set_status(u"Pick cancelled.")
            return
        if result.get(u"linked_refused"):
            self.set_status(u"That is in a linked model - Pick System only takes this model's "
                            u"elements. (Settings: Look up linked elements.)", True)
            return
        linked = result.get(u"linked")
        if linked:
            self.set_status(u"Linked model {0}: {1} {2} - {3}{4}{5}. Linked elements are read-only "
                            u"and not in the lists.".format(
                                linked.get(u"link"), linked.get(u"category"), linked.get(u"id"),
                                linked.get(u"system") or u"no system",
                                u", " + linked.get(u"type") if linked.get(u"type") else u"",
                                u", " + linked.get(u"size") if linked.get(u"size") else u""))
            return
        if result.error:
            self.set_status(u"Pick failed - {0}".format(result.error.strip().splitlines()[-1]),
                            True)
            return
        picked = result.get(u"id")
        near = result.get(u"near") or [picked]
        domain = result.get(u"domain")
        what = u"{0} {1}".format(result.get(u"category") or u"Element", picked)
        if not domain:
            self.set_status(u"{0} is not on a pipe, duct or containment system.".format(what), True)
            return
        # the workset tab lists all three; any other tab hands over to the right one
        if self.domain != u"ws" and domain != self.domain:
            self.switch_tab(domain)
        elif self.read_from != self.doc_key():
            self.reload()
        if self.domain == u"ws":
            ids = set(near)
        else:
            ids = set(core.picked_system_ids(self.snapshot.records, near,
                                             self.settings.get(u"group_by")))
        if not ids:
            scope = u" The tab is set to the active view only - set Scope to Project." \
                if self.settings.get(u"scope") == u"view" else u""
            self.set_status(u"{0} is not in this tab's list.{1}".format(what, scope), True)
            return
        found = self.select_system(ids)
        page_cleared = False
        if not found and self.clear_page_filters():
            page_cleared = True
            found = self.select_system(ids)
        if not found:
            self.set_status(u"{0} is not in this tab's list.".format(what), True)
            return
        rows = [r for s in self.sections for r in s.selected_rows()]
        head = rows[0]
        text = u"Picked {0} - {1} \u203a {2}".format(what, head.get(u"group", u""),
                                                      head.get(u"system", u""))
        if len(rows) > 1:
            text += u" ({0} rows)".format(len(rows))
        # say what had to be loosened to show it
        note = getattr(self, u"kept_note", u"") or u""
        extra = []
        if page_cleared:
            extra.append(u"the page filter that hid it is off")
        if u"Filters widened" in note:
            extra.append(u"column filters widened")
        if u"Search cleared" in note:
            extra.append(u"search cleared")
        if u"Issues only switched off" in note:
            extra.append(u"Issues only is off")
        if extra:
            text += u" - " + u", ".join(extra)
        self.set_status(text + u".")

    def select_system(self, ids):
        """Select every row holding one of ids - on every section, with the
        filters loosened so they show - open them and scroll to the first."""
        for section in self.sections:
            section.clear_selection()
        state = {u"doc": self.read_from, u"layout": core.layout_signature(self.settings),
                 u"keys": set(), u"ids": set(ids), u"scroll": None,
                 u"sections": dict((s.name, s.state()) for s in self.sections)}
        self.restore_view_state(state)
        self.on_selection_changed()
        chosen = [s for s in self.sections if s.selected_rows()]
        if chosen:
            ui.later(self.window, lambda: self.scroll_to_selection(chosen[0]))
        return bool(chosen)

    def scroll_to_selection(self, section):
        try:
            items = list(section.grid.SelectedItems)
            container = None
            if items:
                section.grid.ScrollIntoView(items[0])
                container = section.grid.ItemContainerGenerator.ContainerFromItem(items[0])
            (container or section.expander).BringIntoView()
        except Exception:
            pass

    def clear_page_filters(self):
        """Tab-wide filters that can hide a whole system type: switch them off
        so a picked system can be shown. True if one was on."""
        changed = False
        if self.domain == u"cont" and core.to_bool(self.settings.get(u"multi_type_only")):
            self.settings[u"multi_type_only"] = u"0"
            changed = True
        if self.domain == u"ws" and core.to_bool(self.settings.get(u"ws_mixed_only")):
            self.settings[u"ws_mixed_only"] = u"0"
            changed = True
        if not changed:
            return False
        core.save_settings(self.settings)
        self.sync_toolbar()
        self.build_sections()
        return True

    # ---------------- keeping the selection through a refresh ----------------

    def capture_view_state(self):
        """What is selected, and each service's sort and filters, before the
        sections are rebuilt. Selection is held by pipe id as well as row key,
        so rows that changed type are found again."""
        sections = getattr(self, u"sections", None) or []
        if not sections:
            return None
        state = {u"doc": getattr(self, u"read_from", u""),
                 u"layout": core.layout_signature(self.settings),
                 u"keys": set(), u"ids": set(), u"sections": {}, u"scroll": None}
        for section in sections:
            rows = section.selected_rows()
            for row in rows:
                state[u"keys"].add(row[u"key"])
            state[u"ids"].update(core.selected_ids(rows))
            state[u"sections"][section.name] = section.state()
        try:
            state[u"scroll"] = self.body_scroll.VerticalOffset
        except Exception:
            pass
        return state

    def restore_view_state(self, state):
        self.kept_note = u""
        if not state or state.get(u"doc") != self.read_from:
            return
        same_layout = state.get(u"layout") == core.layout_signature(self.settings)
        chosen = {}
        loosened = set()
        search_hides = False
        for section in self.sections:
            rows = core.rows_to_reselect(section.rows, state[u"keys"], state[u"ids"])
            saved = state[u"sections"].get(section.name) if same_layout else None
            keywords = saved[u"keywords"] if saved else {}
            ticks = saved[u"ticks"] if saved else {}
            if rows:
                keywords, ticks, fields, hides = core.loosen_for(
                    rows, keywords, ticks, self.global_search())
                loosened.update([u"{0} ({1})".format(self.field_titles().get(f, f),
                                                     section.name) for f in fields])
                search_hides = search_hides or hides
            if saved or rows:
                section.apply_state(saved[u"sort"] if saved else None, keywords, ticks)
            if rows:
                chosen[section] = [r[u"key"] for r in rows]
        issues_hide = False
        if self.issues_only():
            for section in self.sections:
                picked = core.rows_to_reselect(section.rows, state[u"keys"], state[u"ids"])
                if [r for r in picked if not r.get(u"flag")]:
                    issues_hide = True
                    break
        if issues_hide:
            self.set_issues_only(False, refresh=False)
        if search_hides:
            try:
                self.find(u"TxtSearch").Text = u""
            except Exception:
                pass
        if search_hides or issues_hide:
            for section in self.sections:
                section.refresh()
        rows_kept = 0
        for section, keys in chosen.items():
            try:
                section.expander.IsExpanded = True
                if section.outer is not None:
                    section.outer.IsExpanded = True
            except Exception:
                pass
            rows_kept += section.select_keys(keys)
        offset = state.get(u"scroll")
        if offset is not None:
            ui.later(self.window, lambda: self.body_scroll.ScrollToVerticalOffset(offset))
        if not state[u"ids"] and not state[u"keys"]:
            return
        note = u"Selection kept: {0} row{1}.".format(rows_kept, u"" if rows_kept == 1 else u"s")
        found = set()
        for section in self.sections:
            found.update(core.selected_ids(section.selected_rows()))
        gone = len(state[u"ids"] - found)
        if gone:
            note += u" {0} selected {1} no longer here.".format(gone, self.noun(gone))
        if loosened:
            note += u" Filters widened to show it: {0}.".format(u", ".join(sorted(loosened)))
        if search_hides:
            note += u" Search cleared - it hid the selection."
        if issues_hide:
            note += u" Issues only switched off - it hid the selection."
        self.kept_note = note

    def announce_kept(self):
        note = getattr(self, u"kept_note", u"")
        if not note:
            return
        try:
            status = self.find(u"StatusText")
            status.Text = u"{0}  {1}".format(status.Text, note).strip()
        except Exception:
            pass
        ui.log(note, self.debug)

    # ---------------- toolbar ----------------

    def on_search(self):
        if self.search_timer is None:
            from System import TimeSpan
            from System.Windows.Threading import DispatcherTimer
            self.search_timer = DispatcherTimer()
            self.search_timer.Interval = TimeSpan.FromMilliseconds(220)
            self.search_timer.Tick += self.safe(self.run_search, u"Search")
        self.search_timer.Stop()
        self.search_timer.Start()

    def run_search(self):
        self.search_timer.Stop()
        for section in self.sections:
            section.refresh()
        self.on_selection_changed()

    def on_split(self):
        find = self.find
        self.settings[u"split_system"] = core.from_bool(find(u"ChkSplitSystem").IsChecked)
        self.settings[u"split_type"] = core.from_bool(find(u"ChkSplitType").IsChecked)
        self.settings[u"split_size"] = core.from_bool(find(u"ChkSplitSize").IsChecked)
        core.save_settings(self.settings)
        if self.snapshot is not None:
            self.build_sections()

    def on_scope(self):
        scope = msm_settings.picked(self.find(u"CmbScope"), msm_settings.SCOPES)
        if scope == self.settings.get(u"scope"):
            return
        self.settings[u"scope"] = scope
        core.save_settings(self.settings)
        self.reload()

    def expand_all(self, state):
        """On the Workset Assigner, Collapse all folds down to the disciplines
        and Expand all opens everything."""
        for section in self.sections:
            section.expander.IsExpanded = state
        for _title, outer, _made in self.outers:
            outer.IsExpanded = state
        self.on_expand_changed()

    def on_expand_changed(self):
        names = [s.name for s in self.sections if s.expander.IsExpanded]
        names.extend([t for t, outer, _m in self.outers if outer.IsExpanded])
        self.settings[u"expanded"] = core.join_list(names)
        core.save_settings(self.settings)

    def on_view_picked(self):
        combo = self.find(u"CmbView")
        if combo.SelectedItem is not None:
            self.settings[u"last_view"] = u"{0}".format(combo.SelectedItem)
            core.save_settings(self.settings)

    def on_key(self, sender, args):
        try:
            if args.Key == Key.F5 and not self.busy:
                self.reload()
                args.Handled = True
        except Exception:
            self.report_error(u"Refresh")

    def open_settings(self):
        dialog = msm_settings.SettingsDialog(self.window, self.settings,
                                             self.snapshot.param_names,
                                             self.snapshot.all_param_names)
        if dialog.show():
            before = self.settings
            self.settings = core.load_settings()
            theme.apply(self.window, self.settings.get(u"theme"))
            self.paint_theme_label()
            self.sync_toolbar()
            reread = [k for k in (u"group_by", u"group_param", u"system_from", u"scope")
                      if before.get(k) != self.settings.get(k)]
            if reread:
                self.reload()
            else:
                self.build_sections()
            self.set_status(u"Settings saved.")
        else:
            theme.apply(self.window, self.settings.get(u"theme"))

    # ---------------- checks, standards, issues only ----------------

    def checks_on(self):
        return core.checks_on(self.settings)

    def issues_only(self):
        """Issues only means nothing while the checks are off - it would hide
        every row - so it counts only when they are on."""
        if self.domain == u"ws":
            return False
        return core.to_bool(self.settings.get(u"issues_only")) and self.checks_on()

    def paint_checks_switch(self):
        on = self.checks_on()
        find = self.find
        find(u"ChecksOnLabel").Text = u"Checks on" if on else u"Checks off"
        grid.res(find(u"ChecksOnDot"), Border.BackgroundProperty, u"Red" if on else u"Muted")
        find(u"ChkIssuesOnly").IsEnabled = on

    def toggle_checks(self):
        self.settings[u"checks_on"] = core.from_bool(not self.checks_on())
        core.save_settings(self.settings)
        self.paint_checks_switch()
        self.build_sections()
        if self.checks_on():
            flagged = sum([len([r for r in s.rows if r.get(u"flag")]) for s in self.sections])
            self.set_status(u"Checks on - {0} row{1} need{2} a look.".format(
                flagged, u"" if flagged == 1 else u"s", u"s" if flagged == 1 else u""))
        else:
            self.set_status(u"Checks off - no rows flagged. Which checks are ticked is kept "
                            u"for when they go back on.")

    def set_issues_only(self, state, refresh=True):
        self.settings[u"issues_only"] = core.from_bool(state)
        core.save_settings(self.settings)
        box = self.find(u"ChkIssuesOnly")
        if bool(box.IsChecked) != bool(state):
            self.suspend_issues = True
            try:
                box.IsChecked = state
            finally:
                self.suspend_issues = False
        if refresh:
            for section in self.sections:
                section.refresh()
            self.on_selection_changed()

    def on_issues_only(self):
        if getattr(self, u"suspend_issues", False):
            return
        state = bool(self.find(u"ChkIssuesOnly").IsChecked)
        self.set_issues_only(state)
        if state:
            flagged = sum([len([r for r in s.rows if r.get(u"flag")]) for s in self.sections])
            self.set_status(u"{0} row{1} flagged by the checks.".format(
                flagged, u"" if flagged == 1 else u"s") if flagged else
                u"Nothing flagged - every row passes the checks that are switched on.")

    def open_checks(self):
        services = [s.name for s in self.sections]
        dialog = msm_standards.StandardsDialog(self.window, self.settings, services,
                                               [n for n, _i in self.snapshot.types])
        if dialog.show():
            self.settings = core.load_settings()
            self.build_sections()
            flagged = sum([len([r for r in s.rows if r.get(u"flag")]) for s in self.sections])
            if not self.checks_on():
                self.set_status(u"Checks saved. They are switched off in the toolbar, so "
                                u"nothing is flagged until they go back on.")
            else:
                self.set_status(u"Checks saved - {0} row{1} need{2} a look.".format(
                    flagged, u"" if flagged == 1 else u"s", u"s" if flagged == 1 else u""))

    # ---------------- export ----------------

    def export(self):
        groups = [(s.name, list(s.visible_rows)) for s in self.sections if s.visible_rows]
        if not groups:
            self.set_status(u"Nothing shown to export.", True)
            return
        filtered = any([len(s.visible_rows) != len(s.rows) for s in self.sections])
        project = u""
        try:
            project = self.uiapp.ActiveUIDocument.Document.Title
        except Exception:
            pass
        path = ui.ask_save_path(self.window,
                                core.export_filename(project, self.info()[u"export"]),
                                self.settings.get(u"export_dir"))
        if not path:
            return
        parts = msm_xlsx.build_parts(msm_xlsx.system_sheets(groups, self.checks_on(),
                                                            self.domain))
        try:
            ui.write_xlsx(path, parts)
        except Exception as error:
            ui.log(u"export failed:\n{0}".format(traceback.format_exc()), True)
            ui.message(self.window, core.TOOL_NAME,
                       u"The workbook could not be written.\n\n{0}\n\nIf it is open in "
                       u"Excel, close it there and export again.".format(error),
                       mode=self.settings.get(u"theme"))
            return
        self.settings[u"export_dir"] = os.path.dirname(path)
        core.save_settings(self.settings)
        rows = sum([len(r) for _s, r in groups])
        self.set_status(u"Exported {0} row{1} from {2} service{3}{4}.".format(
            rows, u"" if rows == 1 else u"s", len(groups), u"" if len(groups) == 1 else u"s",
            u" - as filtered" if filtered else u""))
        if ui.message(self.window, core.TOOL_NAME,
                      u"Exported to\n{0}".format(path), u"Open folder", u"Close",
                      self.settings.get(u"theme")):
            ui.show_in_folder(path)

    # ---------------- selection ----------------

    def keep_only(self, section):
        """Clear every group's selection but this one (core.groups_to_clear)."""
        counts = []
        for other in self.sections:
            try:
                counts.append(other.grid.SelectedItems.Count)
            except Exception:
                counts.append(0)
        try:
            active = self.sections.index(section)
        except ValueError:
            active = -1
        for index in core.groups_to_clear(counts, active, False):
            self.sections[index].clear_selection()

    def selected_rows(self):
        out = []
        for section in self.sections:
            out.extend(section.selected_rows())
        return out

    def on_selection_changed(self):
        rows = self.selected_rows()
        ids = core.selected_ids(rows)
        find = self.find
        if self.domain == u"ws":
            types = len(set([r[u"group"] for r in rows]))
            find(u"SelectionText").Text = u"Nothing selected" if not rows else \
                u"{0} system{1} \u00b7 {2} element{3} \u00b7 {4} system type{5}".format(
                    len(rows), u"" if len(rows) == 1 else u"s", len(ids),
                    u"" if len(ids) == 1 else u"s", types, u"" if types == 1 else u"s")
            find(u"BtnStage").IsEnabled = bool(rows) and find(u"CmbWorkset").SelectedIndex >= 0
            find(u"BtnUnstage").IsEnabled = bool(
                [r for r in rows if r[u"key"] in self.tabs[u"ws"][u"pending"]])
            self.paint_pending()
            return
        if not rows:
            find(u"SelectionText").Text = u"Nothing selected"
        else:
            services = len(set([r[u"group"] for r in rows]))
            find(u"SelectionText").Text = u"{0} row{1} \u00b7 {2} {3} \u00b7 {4} service{5}".format(
                len(rows), u"" if len(rows) == 1 else u"s",
                len(ids), self.noun(len(ids)),
                services, u"" if services == 1 else u"s")
        combo = find(u"CmbPipeType")
        if rows and combo.SelectedIndex < 0:
            suggestion = core.suggest_type(
                rows, core.decode_standards(self.settings.get(u"standards")),
                [n for n, _i in self.snapshot.types])
            if suggestion is not None:
                combo.SelectedItem = suggestion
        find(u"BtnIsolate").IsEnabled = bool(ids)
        find(u"BtnChangeType").IsEnabled = bool(ids) and combo.SelectedIndex >= 0
        # green once a type to change to is chosen, orange until then
        style = self.window.TryFindResource(u"BtnGreen" if combo.SelectedIndex >= 0
                                            else u"BtnOrange")
        if style is not None and find(u"BtnChangeType").Style is not style:
            find(u"BtnChangeType").Style = style
        find(u"BtnResize").IsEnabled = bool(ids) and self.domain == u"cont"
        find(u"BtnReapply").IsEnabled = bool(ids) and self.domain in (u"pipe", u"duct")
        find(u"BtnService").IsEnabled = bool(ids) and self.domain == u"cont"

    def chosen_view_id(self):
        index = self.find(u"CmbView").SelectedIndex
        if 0 <= index < len(self.view_choices):
            return self.view_choices[index][1]
        return 0

    # ---------------- isolate ----------------

    def isolate(self):
        if self.domain == u"ws":
            return
        ids = core.selected_ids(self.selected_rows())
        self.dbg(u"isolate", u"pressed", u"", u"{0} elements selected, busy {1}".format(
            len(ids), self.busy))
        if self.busy:
            self.set_status(u"Still waiting for Revit - {0}".format(self.busy_what), True)
            return
        if not ids:
            self.set_status(u"Select one or more rows first.", True)
            return
        if not self.same_document():
            self.dbg(u"isolate", u"stopped", u"", u"a different model is active")
            return
        self.set_busy(True, u"Isolating {0} {1}...".format(len(ids), self.noun(len(ids))))
        job = ops.isolate_job(ids, self.chosen_view_id(), self.settings.resolved())
        status = self.runner.run(job, lambda result: ui.later(self.window,
                                                              lambda: self.isolate_done(result)))
        self.dbg(u"isolate", u"request", u"", u"Revit said {0}".format(status))

    def isolate_done(self, result):
        self.set_busy(False)
        self.dbg_result(u"isolate", result)
        self.forget_highlight(result)
        self.remember_isolated_view(result.get(u"view_id"))
        if result.error:
            ui.log(u"isolate failed:\n" + result.error, True)
            self.set_status(u"Isolate failed - {0}".format(result.error.strip().splitlines()[-1]), True)
            self.show_results(u"Isolate", result.error, True)
            return
        text = u"Isolated {0} elements in {1}.".format(result.get(u"count"), result.get(u"view_name"))
        reset = result.get(u"reset_views") or []
        if len(reset) > 1:
            text += u" Reset {0} first.".format(u" and ".join(reset))
        elif result.get(u"was_isolated"):
            text += u" The earlier isolate was reset first."
        left = result.get(u"leftovers") or []
        if left:
            text += (u" {0} element{1} from an earlier isolate still show - use Reset Temporary "
                     u"Hide/Isolate in the view.".format(len(left), u"" if len(left) == 1 else u"s"))
        elif result.get(u"retried"):
            text += u" Something from an earlier isolate still showed, so it was reset and isolated again."
        if result.get(u"made_view"):
            text += u" The view did not exist, so it was made."
            self.reload_views_only()
        if result.get(u"switch_failed"):
            text += u" Open the view to see it - Revit would not switch to it."
        if result.get(u"section_box"):
            text += u" Section box fitted round them."
        if result.get(u"section_box_failed"):
            text += u" The section box could not be set."
        if result.get(u"box_hidden"):
            text += u" The section box element could not be found, so the isolate hides it."
        if result.get(u"dropped_text"):
            ui.log(u"isolate left out (not on the picked systems): " +
                   result.get(u"dropped_text"), self.debug)
        self.set_status(text, bool(result.get(u"switch_failed") or left))
        ui.log(text, self.debug)

    def reload_views_only(self):
        try:
            doc = self.uiapp.ActiveUIDocument.Document
            self.snapshot.views_3d = model.read_views(doc)
            self.fill_views()
        except Exception:
            pass

    def reset_isolate(self):
        if not self.same_document():
            return
        self.set_busy(True, u"Resetting the isolate...")
        job = ops.reset_job(self.chosen_view_id(), self.settings.get(u"highlighted", u""),
                            self.settings.get(u"isolated_view") or 0)
        self.runner.run(job, lambda result: ui.later(self.window,
                                                     lambda: self.reset_done(result)))

    def reset_done(self, result):
        self.set_busy(False)
        self.dbg_result(u"reset", result)
        self.forget_highlight(result)
        if result.get(u"ok"):
            self.remember_isolated_view(None)
        if result.error:
            self.set_status(result.error.strip().splitlines()[-1], True)
            return
        self.set_status(u"Temporary isolate taken off {0}.".format(result.get(u"view_name")))

    # ---------------- change pipe type ----------------

    def change_type(self):
        rows = self.selected_rows()
        ids = core.selected_ids(rows)
        combo = self.find(u"CmbPipeType")
        index = combo.SelectedIndex
        if not ids or index < 0:
            self.set_status(u"Select rows and a {0} first.".format(
                self.info()[u"type_word"].lower()), True)
            return
        if not self.same_document():
            return
        choices = getattr(self, u"type_choices", None) or self.snapshot.types
        if index >= len(choices):
            self.set_status(u"Pick the type again.", True)
            return
        type_name, type_id = choices[index]
        title = u"Change {0}".format(self.info()[u"type_word"])
        if self.domain == u"pipe":
            self.change_pipe_type(rows, ids, type_name, type_id, title)
            return
        systems = sorted(set([r[u"system"] for r in rows]), key=core.natural_key)
        from_types = sorted(set([r[u"ptype"] for r in rows]), key=core.natural_key)
        swap = core.to_bool(self.settings.get(u"swap_fittings"))
        fittings = 0
        if swap:
            try:
                fittings = ops.fitting_count_estimate(self.uiapp.ActiveUIDocument.Document, ids)
            except Exception:
                fittings = 0
        body = core.change_summary(len(ids), systems, from_types, type_name,
                                   core.split_list(self.settings.get(u"retain")),
                                   core.to_bool(self.settings.get(u"keep_size")),
                                   swap, fittings, self.domain)
        body += u"\n\nWhat is retained is set in Settings. Revit's undo takes it all back in one step."
        if self.domain == u"cont":
            body += (u"\n\nA cable tray type only goes onto cable trays and a conduit type "
                     u"onto conduits - anything else selected is skipped and listed.")
        if not ui.message(self.window, title, body, u"Change", u"Cancel",
                          self.settings.get(u"theme")):
            self.set_status(u"Nothing changed.")
            return
        self.set_busy(True, u"Changing {0} {1} to {2}...".format(
            len(ids), self.noun(len(ids)), type_name))
        ui.log(u"change type: {0} {1} -> {2}".format(len(ids), self.noun(len(ids)), type_name),
               self.debug)
        job = ops.change_type_job(ids, type_id, self.settings.resolved())
        self.runner.run(job, lambda result: ui.later(
            self.window, lambda: self.change_done(result, type_name, title)))

    def change_pipe_type(self, rows, ids, type_name, type_id, title):
        """Pipes: the size mapping window - every current type and size, the
        size each goes to on the new type - then the change."""
        wanted = set(ids)
        records = [r for r in self.snapshot.records if r[u"id"] in wanted]
        size_rows = core.size_rows(records)
        try:
            available = model.type_sizes(self.uiapp.ActiveUIDocument.Document, type_id)
        except Exception:
            available = []
        systems = sorted(set([r.get(u"system") or u"" for r in rows]), key=core.natural_key)
        dialog = msm_typechange.TypeChangeDialog(self.window, self.settings, size_rows,
                                                 type_name, available, systems)
        answer = dialog.show()
        if answer is None:
            self.set_status(u"Nothing changed.")
            return
        size_map = core.size_map_from(size_rows, answer)
        for line in core.mapping_summary(size_rows, answer, type_name):
            self.dbg(u"change type", u"mapping", u"", line)
        self.set_busy(True, u"Changing {0} pipes to {1}...".format(len(ids), type_name))
        job = ops.change_type_job(ids, type_id, self.settings.resolved(), size_map)
        status = self.runner.run(job, lambda result: ui.later(
            self.window, lambda: self.change_done(result, type_name, title)))
        self.dbg(u"change type", u"request", u"", u"Revit said {0}".format(status))

    def write_change_log(self, title, d):
        """The change log as a file beside the settings: every success and every
        error with its element id."""
        path = os.path.join(core.settings_dir(), u"mep_system_manager_change_log.txt")
        lines = [u"{0} - {1}".format(title, time.strftime(u"%Y-%m-%d %H:%M:%S")), u"",
                 u"Changed ({0}):".format(len(d.get(u"log_ok") or []))]
        lines.extend([u"   " + l for l in d.get(u"log_ok") or []])
        lines.append(u"")
        lines.append(u"Errors ({0}):".format(len(d.get(u"log_err") or [])))
        lines.extend([u"   " + l for l in d.get(u"log_err") or []])
        try:
            with io.open(path, u"w", encoding=u"utf-8") as handle:
                handle.write(u"\n".join(lines) + u"\n")
            return path
        except Exception:
            return None

    def show_change_log(self, title, d):
        ok = d.get(u"log_ok") or []
        err = d.get(u"log_err") or []
        path = self.write_change_log(title, d)
        lines = [u"{0} changed, {1} error{2}.".format(len(ok), len(err), u"" if len(err) == 1 else u"s")]
        if d.get(u"groups_reclosed"):
            lines.append(u"Groups opened, changed and closed again: {0}".format(
                u", ".join(d.get(u"groups_reclosed"))))
        lines.append(u"")
        lines.append(u"Errors ({0}):".format(len(err)))
        lines.extend([u"   " + l for l in err[:40]] or [u"   none"])
        if len(err) > 40:
            lines.append(u"   ...and {0} more".format(len(err) - 40))
        lines.append(u"")
        lines.append(u"Changed ({0}):".format(len(ok)))
        lines.extend([u"   " + l for l in ok[:40]] or [u"   none"])
        if len(ok) > 40:
            lines.append(u"   ...and {0} more".format(len(ok) - 40))
        if path:
            lines.append(u"")
            lines.append(u"The full log is saved to {0}".format(path))
        ui.message(self.window, title + u" - log", u"\n".join(lines), u"OK", None,
                   self.settings.get(u"theme"))
        if err and d.get(u"_error_ids"):
            if ui.message(self.window, title,
                          u"{0} error{1}. Show them in a 3D view? The converted systems are "
                          u"isolated, what changed is made 60% transparent and the errors are "
                          u"drawn in solid magenta. Reset Isolate takes it off.".format(
                              len(err), u"" if len(err) == 1 else u"s"),
                          u"Show errors in 3D", u"Close", self.settings.get(u"theme")):
                self.set_busy(True, u"Showing the errors in 3D...")
                job = ops.isolate_errors_job(d.get(u"_system_ids") or [],
                                             d.get(u"_success_ids") or [],
                                             d.get(u"_error_ids") or [], self.chosen_view_id(),
                                             self.settings.resolved())
                self.runner.run(job, lambda r: ui.later(self.window,
                                                        lambda: self.errors_shown(r)))

    def errors_shown(self, result):
        self.set_busy(False)
        self.dbg_result(u"errors in 3D", result)
        if result.error:
            self.set_status(result.error.strip().splitlines()[-1], True)
            return
        if result.get(u"highlighted"):
            self.settings[u"highlighted"] = result.get(u"highlighted")
            core.save_settings(self.settings)
        self.remember_isolated_view(result.get(u"view_id"))
        self.set_status(u"Isolated {0} elements in {1}: {2} changed shown 60% transparent, {3} "
                        u"errors in magenta. Reset Isolate takes it off.".format(
                            result.get(u"count"), result.get(u"view_name"),
                            result.get(u"faded"), result.get(u"marked")))

    def change_done(self, result, type_name, title=u"Change Type"):
        self.set_busy(False)
        self.dbg_result(u"change type", result)
        if result.error:
            ui.log(u"change type failed:\n" + result.error, True)
            self.set_status(u"Change failed - nothing was written. Details in the log.", True)
            self.show_results(title, result.error, True)
            return
        d = result.data
        summary = u"{0} of {1} {2} are now {3}.".format(d.get(u"on_type", 0), d.get(u"asked", 0),
                                                       self.noun(2), type_name)
        if d.get(u"fittings_swapped"):
            summary += u" {0} fittings swapped.".format(d.get(u"fittings_swapped"))
        if d.get(u"to_resize"):
            summary += u" {0} of {1} resized in the second pass.".format(
                d.get(u"resized", 0), d.get(u"to_resize"))
        if d.get(u"reapplied"):
            summary += u" Revit's Reapply Type was handed {0} elements; it runs as this " \
                       u"finishes.".format(d.get(u"reapplied"))
        if d.get(u"accessories_resized"):
            summary += u" {0} accessor{1} resized.".format(
                d.get(u"accessories_resized"),
                u"y" if d.get(u"accessories_resized") == 1 else u"ies")
        if d.get(u"values_restored"):
            summary += u" {0} retained values written back.".format(d.get(u"values_restored"))
        needs_look = core.results_need_a_look(d)
        self.set_status(summary + (u" Some need a look." if needs_look else u""), needs_look)
        ui.log(summary, self.debug)
        lines = [summary, u""]
        sections = ((u"wrong_kind", u"Not the kind that type is for - skipped"),
                    (u"locked", u"Held by somebody else - skipped"),
                    (u"failed", u"Revit refused"),
                    (u"size_changed", u"Size not available on the new type"),
                    (u"not_restored", u"Parameter value that would not go back"),
                    (u"fitting_failed", u"Fittings left as they were"),
                    (u"accessories_left", u"Accessories left at their old size"),
                    (u"disconnected", u"Disconnected by Revit - reconnect these"))
        for key, heading in sections:
            items = d.get(key) or []
            if items:
                lines.append(u"{0} ({1}):".format(heading, len(items)))
                for item in items[:40]:
                    lines.append(u"   {0}".format(item))
                if len(items) > 40:
                    lines.append(u"   ...and {0} more (all in the log)".format(len(items) - 40))
                lines.append(u"")
                ui.log(u"{0}: {1}".format(heading, u"; ".join(items)), self.debug)
        if d.get(u"replaced_fittings"):
            lines.append(u"{0} fittings were replaced by Revit during the change; their "
                         u"retained values were carried onto the new ones."
                         .format(d.get(u"replaced_fittings")))
        if d.get(u"already"):
            lines.append(u"{0} {1} already on {2}.".format(
                d.get(u"already"), self.noun(d.get(u"already")), type_name))
        if d.get(u"fittings_left"):
            lines.append(u"{0} fittings join a changed {1} to one that is not changing, "
                         u"so they were left alone.".format(d.get(u"fittings_left"),
                                                             self.info()[u"noun"][0]))
        if d.get(u"dialogs"):
            lines.append(u"Revit dialogs dismissed during the run: {0}".format(
                u", ".join(d.get(u"dialogs"))))
        if d.get(u"group_skipped"):
            lines.append(u"In a group that could not be opened - left as they were:")
            lines.extend([u"   " + l for l in d.get(u"group_skipped")[:30]])
        self.reload()
        if d.get(u"log_ok") is not None and (d.get(u"log_ok") or d.get(u"log_err")):
            # the log of successes and errors, and the offer to show errors in 3D
            self.show_change_log(title, d)
        else:
            self.show_results(title, u"\n".join(lines), needs_look)

    def show_results(self, title, body, needs_look):
        mode = self.settings.get(u"show_results", u"issues")
        if mode == u"never" or (mode == u"issues" and not needs_look):
            return
        ui.message(self.window, title, body, u"OK", None, self.settings.get(u"theme"))

    # ---------------- debug table ----------------

    def toggle_debug(self):
        self.debug = bool(self.find(u"ChkDebug").IsChecked)
        self.settings[u"debug"] = core.from_bool(self.debug)
        core.save_settings(self.settings)
        self.find(u"BtnCopyDebug").Visibility = (Visibility.Visible if self.debug
                                                 else Visibility.Collapsed)
        if self.debug:
            self.dbg(u"debug", u"on", u"", u"recording from here")
            self.set_status(u"Debug on - what each action does is recorded. Copy table puts "
                            u"it on the clipboard to send.")
        else:
            self.set_status(u"Debug off.")

    def dbg(self, action, step, element=u"", detail=u""):
        """One row of the debug table, only while Debug is ticked."""
        if not getattr(self, u"debug", False):
            return
        core.add_debug_row(self.debug_rows, {
            u"time": time.strftime(u"%H:%M:%S"), u"tab": getattr(self, u"domain", u""),
            u"action": action, u"step": step, u"element": element, u"detail": detail})

    def dbg_result(self, action, result):
        """Everything a job reported: every list item as its own row."""
        if not self.debug:
            return
        if result.error:
            for step, text in core.error_rows(result.error):
                self.dbg(action, u"error " + step, u"", text)
        for step, text in core.error_rows(result.data.get(u"_stopped_at")):
            self.dbg(action, u"stopped " + step, u"", text)
        for key in sorted(result.data.keys()):
            if key.startswith(u"_"):
                continue                        # working data, not for the table
            value = result.data[key]
            if isinstance(value, (list, tuple)):
                if not value:
                    continue
                for item in value:
                    if isinstance(item, dict):
                        self.dbg(action, key, item.get(u"run", u""), u"; ".join(
                            [u"{0}={1}".format(k, item[k]) for k in sorted(item)]))
                    else:
                        text = u"{0}".format(item)
                        head = text.split(u" - ", 1)
                        element = head[0] if len(head) == 2 and head[0].isdigit() else u""
                        self.dbg(action, key, element, head[1] if element else text)
            elif isinstance(value, dict):
                self.dbg(action, key, u"", u"; ".join([u"{0}: {1}".format(k, value[k])
                                                        for k in sorted(value)]))
            else:
                self.dbg(action, key, u"", value)

    def environment(self):
        out = [(u"Tool", u"{0} v{1}".format(core.TOOL_NAME, core.__version__))]
        try:
            app = self.uiapp.Application
            out.append((u"Revit", u"{0} ({1})".format(app.VersionName, app.VersionBuild)))
        except Exception:
            pass
        out.append((u"Engine", sys.version.replace(u"\n", u" ")))
        try:
            from pyrevit import versionmgr
            out.append((u"pyRevit", versionmgr.get_pyrevit_version().get_formatted()))
        except Exception:
            pass
        try:
            doc = self.uiapp.ActiveUIDocument.Document
            out.append((u"Model", u"{0}{1}".format(doc.Title, u" (workshared)"
                                                   if doc.IsWorkshared else u"")))
        except Exception:
            pass
        out.append((u"Window", u"modal" if self.modal else u"modeless"))
        out.append((u"Tab", self.info()[u"tab"]))
        for domain in core.DOMAINS:
            snap = self.tabs[domain][u"snapshot"]
            if snap is not None:
                out.append((u"Read " + domain, u"{0} rows of model, {1} types".format(
                    len(snap.records), len(snap.types))))
        resolved = self.settings.resolved()
        out.append((u"Settings (this tab)", u"; ".join(
            [u"{0}={1}".format(k, resolved[k]) for k in sorted(resolved)])))
        return out

    def copy_debug(self):
        text = core.debug_table(self.environment(), self.debug_rows)
        path = os.path.join(core.settings_dir(), u"mep_system_manager_debug_table.md")
        saved = False
        try:
            if not os.path.isdir(core.settings_dir()):
                os.makedirs(core.settings_dir())
            with io.open(path, u"w", encoding=u"utf-8") as handle:
                handle.write(text)
            saved = True
        except Exception:
            pass
        copied = False
        try:
            Clipboard.SetText(text)
            copied = True
        except Exception:
            pass
        rows = len(self.debug_rows)
        if copied:
            self.set_status(u"Debug table copied - {0} row{1}. Paste it into the chat.{2}".format(
                rows, u"" if rows == 1 else u"s",
                u" Also saved to {0}".format(path) if saved else u""))
        elif saved:
            self.set_status(u"The clipboard was busy - the table is saved to {0}".format(path), True)
        else:
            self.set_status(u"The debug table could not be copied or saved.", True)

    # ---------------- containment: resize runs ----------------

    def remember_isolated_view(self, view_id):
        """The next isolate resets this view too, even if it isolates elsewhere."""
        value = u"{0}".format(view_id) if view_id else u""
        if self.settings.get(u"isolated_view") != value:
            self.settings[u"isolated_view"] = value
            core.save_settings(self.settings)

    def forget_highlight(self, result):
        if result.get(u"highlight_cleared") is not None:
            self.settings[u"highlighted"] = u""
            core.save_settings(self.settings)

    def resize_runs(self):
        if self.domain != u"cont":
            return
        rows = self.selected_rows()
        ids = core.selected_ids(rows)
        if not ids:
            self.set_status(u"Select one or more rows first.", True)
            return
        if not self.same_document():
            return
        kinds = {}
        for record in self.snapshot.records:
            kinds[record[u"id"]] = record.get(u"kind")
        trays = len([i for i in ids if kinds.get(i) == u"tray"])
        conduits = len([i for i in ids if kinds.get(i) == u"conduit"])
        members = core.run_members(self.snapshot.records, ids, self.settings.get(u"group_by"),
                                   self.settings.get(u"system_from"))
        whole = None
        runs = len(set([r.get(u"system") for r in self.snapshot.records
                        if r[u"id"] in set(ids)]))
        if members is not None:
            whole = (len([i for i in members if kinds.get(i) == u"tray"]),
                     len([i for i in members if kinds.get(i) == u"conduit"]))
        sizes = []
        for row in rows:
            if row.get(u"size") and row[u"size"] not in sizes:
                sizes.append(row[u"size"])
        dialog = msm_resize.ResizeDialog(self.window, self.settings, trays, conduits,
                                         len(rows), sizes, whole)
        answer = dialog.show()
        self.settings = core.load_settings()
        if not answer:
            self.set_status(u"Nothing resized.")
            return
        if answer[u"whole_run"] and whole is not None:
            count_trays, count_conduits = whole
        else:
            count_trays, count_conduits = trays, conduits
        body = core.resize_summary(runs, count_trays, count_conduits, answer[u"width"],
                                   answer[u"height"], answer[u"diameter"], answer[u"whole_run"])
        body += u"\n\nIf Revit objects: {0}.".format(
            dict(core.RESIZE_MODES).get(answer.get(u"mode"), u"").lower())
        if not ui.message(self.window, u"Resize runs", body, u"Resize", u"Cancel",
                          self.settings.get(u"theme")):
            self.set_status(u"Nothing resized.")
            return
        self.dbg(u"resize", u"asked", u"", u"{0} rows, {1} runs, {2} trays and {3} conduits "
                 u"selected, whole runs would be {4}; width={5}, height={6}, diameter={7}, "
                 u"whole run={8}".format(
                     len(rows), runs, trays, conduits, whole, answer[u"width"],
                     answer[u"height"], answer[u"diameter"], answer[u"whole_run"]))
        self.set_busy(True, u"Resizing {0} run{1}...".format(len(rows), u"" if len(rows) == 1
                                                             else u"s"))
        job = ops.resize_job(ids, answer[u"width"], answer[u"height"], answer[u"diameter"],
                             answer[u"whole_run"], self.settings.resolved(),
                             answer.get(u"mode", u"partial"), answer.get(u"fittings", True))
        self.runner.run(job, lambda result: ui.later(self.window,
                                                     lambda: self.resize_done(result)))

    def resize_done(self, result):
        self.set_busy(False)
        self.dbg_result(u"resize", result)
        if result.error:
            ui.log(u"resize failed:\n" + result.error, True)
            self.set_status(u"Resize failed - nothing was changed. Details in the log.", True)
            self.show_results(u"Resize runs", result.error, True)
            return
        d = result.data
        failed = d.get(u"failed_runs") or []
        summary = u"{0} of {1} run{2} fully resized - {3} tray{4} and conduit{4} " \
                  u"changed.".format(d.get(u"runs_done", 0), d.get(u"runs", 0),
                                     u"" if d.get(u"runs") == 1 else u"s",
                                     d.get(u"resized", 0),
                                     u"" if d.get(u"resized") == 1 else u"s")
        if d.get(u"unchanged"):
            summary += u" {0} already that size.".format(d.get(u"unchanged"))
        if d.get(u"with_fittings"):
            summary += u" {0} fitting{1} at the new size".format(
                d.get(u"fittings_resized", 0), u"" if d.get(u"fittings_resized") == 1 else u"s")
            left = len(d.get(u"fittings_left") or [])
            summary += u", {0} left at the old size.".format(left) if left else u"."
        before, after = d.get(u"before_close"), d.get(u"after_close")
        if before is not None and after is not None and before != after:
            summary += (u" Revit changed {0} back when the resize was closed as one undo step - "
                        u"send the debug table.".format(before - after))
        self.reload()
        self.set_status(summary + (u" {0} run{1} would not resize.".format(
            len(failed), u"" if len(failed) == 1 else u"s") if failed else u""), bool(failed))
        ui.log(summary, self.debug)
        lines = [summary, u""]
        for key, title in ((u"locked", u"Held by somebody else - skipped"),
                           (u"not_taken", u"Revit did not take the new size"),
                           (u"fittings_left", u"Fittings still at the old size"),
                           (u"warnings", u"Warnings Revit raised (dismissed)")):
            items = d.get(key) or []
            if items:
                lines.append(u"{0} ({1}):".format(title, len(items)))
                lines.extend([u"   {0}".format(i) for i in items[:30]])
                lines.append(u"")
        if not failed:
            done = d.get(u"_done_all") or []
            lines.extend([u"   {0}".format(r) for r in (d.get(u"run_sizes") or [])[:12]])
            lines.append(u"")
            lines.append(u"Show what was resized in the 3D view - the resized runs with their "
                         u"fittings, isolated?")
            if done and ui.message(self.window, u"Resize runs", u"\n".join(lines),
                                   u"Show in 3D", u"Close", self.settings.get(u"theme")):
                self.set_busy(True, u"Isolating the resized runs...")
                job = ops.highlight_job(done, [], self.chosen_view_id(),
                                        self.settings.resolved())
                self.runner.run(job, lambda r: ui.later(self.window,
                                                        lambda: self.highlight_done(r)))
            return
        broken = sorted(set([b for run in failed for b in run[u"broken"]]))
        run_ids = sorted(set([i for run in failed for i in run[u"all"]]))
        lines.append(u"Revit objected on {0} run{1}; what it objected to was put back as it "
                     u"was:".format(len(failed), u"" if len(failed) == 1 else u"s"))
        hints = []
        for run in failed[:12]:
            left = len(run.get(u"left") or [])
            done = run.get(u"resized", 0)
            if done:
                state = u"{0} resized, {1} left as {2}".format(
                    done, left, u"it was" if left == 1 else u"they were")
            else:
                state = u"nothing resized - the whole run is as it was"
            lines.append(u"   Run {0}: {1}".format(run[u"run"], state))
            for text in run[u"messages"][:3]:
                lines.append(u"      Revit: {0}".format(text[:220]))
                hint = core.explain_failure(text)
                if hint and hint not in hints:
                    hints.append(hint)
        lines.append(u"")
        for hint in hints:
            lines.append(u"What this usually means: " + hint)
            lines.append(u"")
        lines.append(u"Isolate these runs in the 3D view, with the elements Revit named and "
                     u"the ones left at the old size shown in red and selected? Reset takes the "
                     u"red off again.")
        if ui.message(self.window, u"Resize runs", u"\n".join(lines), u"Isolate and highlight",
                      u"Close", self.settings.get(u"theme")):
            self.set_busy(True, u"Isolating {0} run{1}...".format(
                len(failed), u"" if len(failed) == 1 else u"s"))
            job = ops.highlight_job(run_ids, broken, self.chosen_view_id(),
                                    self.settings.resolved())
            self.runner.run(job, lambda r: ui.later(self.window,
                                                    lambda: self.highlight_done(r)))

    def highlight_done(self, result):
        self.set_busy(False)
        self.dbg_result(u"highlight", result)
        self.remember_isolated_view(result.get(u"view_id"))
        if result.error:
            self.set_status(result.error.strip().splitlines()[-1], True)
            return
        if result.get(u"highlighted"):
            self.settings[u"highlighted"] = result.get(u"highlighted")
            core.save_settings(self.settings)
        if result.get(u"painted"):
            self.set_status(u"Isolated {0} elements in {1}; {2} shown red and selected. "
                            u"Reset takes the red off.".format(result.get(u"count"),
                                                                result.get(u"view_name"),
                                                                result.get(u"painted")))
        else:
            self.set_status(u"Isolated {0} elements in {1}.".format(result.get(u"count"),
                                                                    result.get(u"view_name")))

    # ---------------- closing ----------------

    def on_closing(self, sender, args):
        """Staged worksets are not in the model until Apply; closing would lose
        them without a word, so ask."""
        try:
            pending = self.tabs[u"ws"][u"pending"]
            if not pending or self.busy:
                return
            count = len(pending)
            if not ui.message(self.window, u"Close the window?",
                              u"{0} system{1} staged on the Workset Assigner {2} not been "
                              u"applied. Close anyway and lose {3}?".format(
                                  count, u"" if count == 1 else u"s",
                                  u"has" if count == 1 else u"have",
                                  u"it" if count == 1 else u"them"),
                              u"Close", u"Keep open", self.settings.get(u"theme")):
                args.Cancel = True
        except Exception:
            pass

    def on_closed(self, sender, args):
        try:
            AppDomain.CurrentDomain.SetData(WINDOW_KEY, None)
        except Exception:
            pass
        _LIVE.clear()


# ============================================================
# launch
# ============================================================

def _flag_path():
    return os.path.join(core.settings_dir(), core.MODELESS_FLAG)


def _write_flag():
    try:
        folder = core.settings_dir()
        if not os.path.isdir(folder):
            os.makedirs(folder)
        with io.open(_flag_path(), u"w", encoding=u"utf-8") as handle:
            handle.write(core.flag_text(core.__version__))
    except Exception:
        pass


def _read_flag():
    try:
        if os.path.isfile(_flag_path()):
            with io.open(_flag_path(), u"r", encoding=u"utf-8") as handle:
                return handle.read()
    except Exception:
        pass
    return None


def _clear_flag():
    try:
        if os.path.isfile(_flag_path()):
            os.remove(_flag_path())
    except Exception:
        pass


def launch(uiapp):
    uidoc = uiapp.ActiveUIDocument
    if uidoc is None:
        ui.message(None, core.TOOL_NAME, u"Open a project first.")
        return
    if uidoc.Document.IsFamilyDocument:
        ui.message(None, core.TOOL_NAME, u"This works in a project, not the family editor.")
        return

    existing = None
    try:
        existing = AppDomain.CurrentDomain.GetData(WINDOW_KEY)
    except Exception:
        existing = None
    if existing is not None:
        try:
            if existing.IsVisible:
                existing.Activate()
                return
        except Exception:
            pass

    settings = core.load_settings()
    modal = settings.get(u"window_mode") == u"modal"
    flag = _read_flag()
    if flag is not None and not core.should_offer_modal(flag, core.__version__,
                                                         settings.get(u"window_mode")):
        _clear_flag()          # stale: another version, or modal is set
    if core.should_offer_modal(flag, core.__version__, settings.get(u"window_mode")):
        # the window opened last time and no handler ever ran - the engine
        # was not kept alive. Nothing inside a dead window can say so.
        modal = ui.message(
            None, core.TOOL_NAME,
            u"Last time the window opened but did not respond to anything.\n\n"
            u"Open it modal this time? Revit waits while it is open, but every "
            u"button works.", u"Open modal", u"Try modeless again",
            settings.get(u"theme"))

    controller = MainWindow(uiapp, modal)
    if modal:
        _clear_flag()
        controller.window.ShowDialog()
        return
    _write_flag()
    _LIVE[u"controller"] = controller
    try:
        AppDomain.CurrentDomain.SetData(WINDOW_KEY, controller.window)
    except Exception:
        pass
    # only now can a handler prove the engine outlived the command
    controller.armed = True
    controller.window.Show()
