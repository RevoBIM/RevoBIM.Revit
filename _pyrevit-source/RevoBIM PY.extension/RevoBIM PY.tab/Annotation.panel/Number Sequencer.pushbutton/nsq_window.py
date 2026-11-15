# -*- coding: utf-8 -*-
"""Number Sequencer - the modeless window and its ExternalEvent runner.

Revit stays usable behind the window. Every read and write of the model
goes out through one ExternalEvent; the window never waits for it.
"""

import nsq_clr  # noqa: F401  (must stay the first import)

import traceback

from System import Action, AppDomain, TimeSpan
from System.Windows import (Thickness, CornerRadius, FontWeights, Clipboard, GridLength,
                            GridUnitType, VerticalAlignment, HorizontalAlignment,
                            TextWrapping, TextTrimming, FrameworkElement)
from System.Windows.Controls import (Grid, Border, TextBlock, DockPanel, Dock,
                                     ColumnDefinition, ComboBoxItem)
from System.Windows.Input import Cursors, Key
from System.Windows.Threading import DispatcherTimer
from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent

import nsq_core as core
import nsq_revit as rv
import nsq_ui as ui
import nsq_tree
import nsq_selector
import nsq_views

APPDOMAIN_KEY = u"RevoBIM.NumberSequencer.window." + core.__version__
WATCHDOG_SECONDS = 20
PARAM_LIST_MAX = 400

# sections that fold away: key, chevron button, body, star row (or None)
SECTIONS = [
    (u"seq_sys", u"SeqSysToggle", u"SeqSysBody", None),
    (u"seq_fam", u"SeqFamToggle", u"SeqFamBody", u"SeqFamRow"),
    (u"sel_fam", u"SelFamToggle", u"SelFamBody", None),
    (u"sel_sys", u"SelSysToggle", u"SelSysBody", u"SelSysRow"),
    (u"start", u"StartToggle", u"StartBody", None),
    (u"param", u"ParamToggle", u"ParamBody", None),
    (u"sequence", u"SequenceToggle", u"SequenceBody", None),
]
FAMILY_SHARE = 0.5     # the selector's families grow to their full height, up to this share
SYSTEMS_RESERVE = 260  # what the systems card needs below them


# ============================================================
# ExternalEvent runner
# ============================================================

class _Handler(IExternalEventHandler):
    def __init__(self, log):
        self.log = log
        self.jobs = []

    def Execute(self, uiapp):
        jobs = self.jobs
        self.jobs = []
        for name, fn, cb in jobs:
            res = None
            err = None
            try:
                res = fn(uiapp)
            except Exception:
                err = traceback.format_exc()
                self.log.add(u"job {0} failed: {1}".format(name, err))
            try:
                cb(res, err)
            except Exception:
                self.log.add(u"callback {0} failed: {1}".format(name, traceback.format_exc()))

    def GetName(self):
        return u"RevoBIM Number Sequencer"


class Runner(object):
    def __init__(self, log):
        self.log = log
        self.handler = _Handler(log)
        self.event = ExternalEvent.Create(self.handler)

    def queue(self, name, fn, cb):
        """Queue behind anything Pending; drop only this job if refused."""
        job = (name, fn, cb)
        self.handler.jobs.append(job)
        status = self.event.Raise()
        text = u"{0}".format(status)
        self.log.add(u"raise {0}: {1}".format(name, text))
        if text in (u"Accepted", u"Pending"):
            return True
        try:
            self.handler.jobs.remove(job)
        except ValueError:
            pass
        try:
            cb(None, u"Revit refused the request ({0})".format(text))
        except Exception:
            pass
        return False


# ============================================================
# The window
# ============================================================

class SequencerWindow(object):

    def __init__(self, uiapp):
        self.uiapp = uiapp
        self.settings = core.load_settings()
        self.log = core.DebugLog(self.settings.get(u"debug") != u"off")
        self.log.add(u"Number Sequencer {0}".format(core.__version__))
        self.log.add(u"assemblies: " + u", ".join(nsq_clr.LOADED))
        try:
            self.log.add(u"Revit {0}".format(uiapp.Application.VersionNumber))
        except Exception:
            pass
        self.runner = Runner(self.log)
        self.busy = False
        self.data = None
        self.params = []
        self.tags = []
        self.type_of = {}
        self.order = []
        self.spans = []
        self.systems = []
        self.sel_sys = -1
        self.sys_seq = 0
        self.sys_rows = []
        self.param_name = None
        self.param_hits = []
        self.param_items = []
        self.param_hi = -1
        self.param_typing = False
        self.skipped = core.skip_keys_from(self.settings.get(u"skip"))
        self.tab = u"seq"
        self.tag_view = []
        self.fold_batch = None  # height gathered while Collapse / Expand all runs
        self.tagwin = None      # the Tag Views or Sheets window while it is open
        self.tagchrome = None
        self.tag_closing = False
        self.want_select = None
        self.select_queued = False
        self.last_errors = []
        self.mode = u"dark"
        self.loading = True

        self.win = ui.load_xaml(u"NumberSequencer.xaml")
        ui.merge_theme(self.win)
        self.ctl = self.win.FindName
        try:
            ui.iconize(self.win)
        except Exception:
            pass
        self.ctl(u"VersionText").Text = u"v" + core.__version__
        icon = ui.load_icon()
        if icon is not None:
            self.ctl(u"HeaderIcon").Source = icon
        self._apply_theme()
        self.chrome = ui.Chrome(self.win, self.ctl(u"HeaderBar"), self.ctl(u"FullBtn"),
                                self.ctl(u"CloseBtn"), self.ctl(u"RevoText"), min_btn=self.ctl(u"MinBtn"))
        ui.wire_egg(self.win, self.ctl(u"RevoText"), lambda: self.mode, self.log)
        ui.own_to_revit(self.win, uiapp)
        # the size it was closed at (folded sections shrank it), then the screen's limits
        for key, prop in ((u"win_w", u"Width"), (u"win_h", u"Height")):
            v = core.to_int(self.settings.get(key), 0)
            if v > 200:
                setattr(self.win, prop, float(v))
        ui.fit_to_screen(self.win)

        self.watchdog = DispatcherTimer()
        self.watchdog.Interval = TimeSpan.FromSeconds(WATCHDOG_SECONDS)
        self.watchdog.Tick += self._on_watchdog

        self.tree = nsq_tree.FamilyTree(self.ctl(u"TreeHost"), self.ctl(u"CountText"), self.ctl(u"SearchBox"),
                                        self._guard, lambda: self.mode, self.skipped,
                                        self._on_tree_changed, self._on_tree_select)
        self.sel = nsq_selector.SelectorTab(self)
        self.views = nsq_views.TagViewsPanel(self)
        self._restore_controls()
        self._wire()
        self._build_sections()
        self.loading = False

    # ---------------------------------------------------- wiring
    def _wire(self):
        c = self.ctl
        c(u"ThemeBtn").Click += self._guard(self._on_theme)
        c(u"TabSeq").Checked += self._guard(self._on_tab)
        c(u"TabSel").Checked += self._guard(self._on_tab)
        c(u"AddSelBtn").Click += self._guard(self._on_add_selection)
        c(u"PickSysBtn").Click += self._guard(self._on_pick_systems)
        c(u"SysUpBtn").Click += self._guard(self._on_sys_up)
        c(u"SysDownBtn").Click += self._guard(self._on_sys_down)
        c(u"SysRemoveBtn").Click += self._guard(self._on_sys_remove)
        c(u"SysClearBtn").Click += self._guard(self._on_sys_clear)
        c(u"PickStartBtn").Click += self._guard(self._on_pick_start)
        c(u"AutoStartBtn").Click += self._guard(self._on_auto_start)
        c(u"ShowStartBtn").Click += self._guard(self._on_show_start)
        c(u"ExpandAllBtn").Click += self._guard(self._on_expand_all)
        c(u"CollapseAllBtn").Click += self._guard(self._on_collapse_all)
        c(u"TickAllBtn").Click += self._guard(self._on_tick_all)
        c(u"UntickAllBtn").Click += self._guard(self._on_untick_all)
        c(u"SearchBox").TextChanged += self._guard(self._on_search)
        c(u"ParamBox").TextChanged += self._guard(self._on_param_typed)
        c(u"ParamBox").PreviewKeyDown += self._guard(self._on_param_keys)
        c(u"ParamBox").PreviewMouseLeftButtonDown += self._guard(self._on_param_mouse)
        c(u"ParamBox").GotKeyboardFocus += self._guard(self._on_param_focus)
        c(u"ParamBox").LostKeyboardFocus += self._guard(self._on_param_left)
        c(u"ParamDrop").Click += self._guard(self._on_param_drop)
        for n in (u"Fmt3", u"Fmt2", u"Fmt1", u"DirUp", u"DirDown"):
            c(n).Checked += self._guard(self._on_sequence_changed)
        c(u"StartBox").TextChanged += self._guard(self._on_sequence_changed)
        c(u"TagCheck").Click += self._guard(self._on_tag_changed)
        c(u"TagCombo").SelectionChanged += self._guard(self._on_tag_changed)
        c(u"TagUntaggedCheck").Click += self._guard(self._on_tag_changed)
        c(u"DebugCheck").Click += self._guard(self._on_debug)
        c(u"CopyDebugBtn").Click += self._guard(self._on_copy_debug)
        c(u"ApplyBtn").Click += self._guard(self._on_apply)
        self.win.Activated += self._guard(self._on_activated)
        self.win.Closed += self._guard(self._on_closed)

    # ---------------------------------------------------- folding sections, the tag drawer
    def _build_sections(self):
        c = self.ctl
        shut = set([k for k in (self.settings.get(u"collapsed") or u"").split(core.SKIP_SEP) if k])
        self.sections = {}
        for key, btn, body, row in SECTIONS:
            self.sections[key] = ui.Section(key, c(btn), c(body), c(row) if row else None,
                                            self._section_changed, key in shut, self._section_resize)
        c(u"SelPane").SizeChanged += self._guard(self._on_main_size)
        c(u"FoldAllBtn").Click += self._guard(self._on_fold_all)
        self._refresh_fold_all()
        ui.set_icon_data(c(u"TagOpenIcon"), u"tag")
        c(u"TagOpenBtn").Click += self._guard(self._on_tag_open)
        self._refresh_tag_open()

    def _tab_sections(self):
        """The sections on the open tab, top to bottom."""
        own = [u"sel_fam", u"sel_sys"] if self.tab == u"sel" else [u"seq_sys", u"seq_fam"]
        return [self.sections[k] for k in own + [u"start", u"param", u"sequence"] if k in self.sections]

    def _refresh_fold_all(self):
        btn = self.ctl(u"FoldAllBtn")
        if any([sec.open for sec in self._tab_sections()]):
            ui.set_button(btn, u"collapse", u"Collapse all")
        else:
            ui.set_button(btn, u"expand", u"Expand all")

    def _on_fold_all(self, sender, e):
        """Fold every section on the tab (any open) or open them all. The
        window moves once, by the total, rather than once per section."""
        secs = self._tab_sections()
        open_ = not any([sec.open for sec in secs])
        self.fold_batch = 0.0
        try:
            for sec in secs:
                sec.set(open_)
        finally:
            total = self.fold_batch
            self.fold_batch = None
        self._section_resize(total)
        self._refresh_fold_all()

    def _section_resize(self, delta):
        """A section folded or opened: the window shrinks or grows by what it
        gave up or takes back (bottom edge moves; never past the screen, never
        below the minimum). Full screen and the shrunk bar keep their size."""
        if self.fold_batch is not None:
            self.fold_batch += delta   # Collapse / Expand all: one move for the lot
            return
        if self.loading or self.chrome.full or self.chrome.shrunk:
            return
        w = self.win
        h0 = w.ActualHeight
        area = ui.work_area(w)
        most = (area[3] - w.Top) if area is not None else h0 + delta
        to = max(w.MinHeight, min(most, h0 + delta))
        if abs(to - h0) < 1.0:
            return
        self.chrome.tall = None
        ui.animate(w, FrameworkElement.HeightProperty, to, frm=h0)

    def _section_changed(self, key, open_):
        if self.loading:
            return
        if self.fold_batch is None:
            self._refresh_fold_all()
        shut = sorted([k for k, sec in self.sections.items() if not sec.open])
        self.settings[u"collapsed"] = core.SKIP_SEP.join(shut)
        self._save()


    def _on_main_size(self, sender, e):
        """The selector's families show in full, up to a share of its pane -
        never so tall the systems table (heading, tools and 120 px of rows)
        loses its room. The pane resizes when the window or a section below
        it folds, so the cap follows."""
        h = self.ctl(u"SelPane").ActualHeight
        self.ctl(u"SelTreeScroll").MaxHeight = max(80.0, min(h * FAMILY_SHARE, h - SYSTEMS_RESERVE) - 70.0)

    def _tag_summary(self):
        n = self.views.ticked_count() if getattr(self, u"views", None) is not None else 0
        if not self.ctl(u"TagCheck").IsChecked:
            return u"tags off" + (u" - {0} view(s) ticked".format(n) if n else u"")
        return u"tags on - " + (u"{0} view(s) ticked".format(n) if n else u"the active view")

    def _refresh_tag_open(self):
        """The Tag Views or Sheets button (and its window) say what will be tagged."""
        text = self._tag_summary()
        self.ctl(u"TagOpenNote").Text = text
        tw = getattr(self, u"tagwin", None)
        if tw is not None:
            try:
                tw.FindName(u"TStatus").Text = u"{0}. Apply to go back, then Run Sequence.".format(text[0].upper() + text[1:])
            except Exception:
                pass

    # ---------------------------------------------------- the Tag Views or Sheets window
    def _on_tag_open(self, sender, e):
        """A bigger window for the tag, the sheets and the views. Their
        controls live in the main window (hidden) and move into it while it is
        open, so nothing is built twice and the ticks are the same ones."""
        tw = getattr(self, u"tagwin", None)
        if tw is not None:
            tw.Activate()
            return
        tw = ui.load_xaml(u"NumberSequencerTags.xaml")
        ui.merge_theme(tw)
        ui.apply_palette(tw, self.mode)
        try:
            ui.iconize(tw)
        except Exception:
            pass
        tw.Owner = self.win
        f = tw.FindName
        f(u"TVersion").Text = u"v" + core.__version__
        f(u"TThemeText").Text = core.theme_label(self.settings.get(u"theme"))
        icon = ui.load_icon()
        if icon is not None:
            f(u"TIcon").Source = icon
        content = self.ctl(u"TagContent")
        self.ctl(u"TagStore").Child = None
        f(u"THost").Child = content
        self.tagwin = tw
        self.tag_closing = False
        self.tagchrome = ui.Chrome(tw, f(u"THeader"), f(u"TFullBtn"), f(u"TCloseX"),
                                   min_btn=f(u"TMinBtn"), on_close=self._close_tagwin)

        def apply(s, e2):
            self._close_tagwin()

        def theme(s, e2):
            self._on_theme(None, None)
            f(u"TThemeText").Text = core.theme_label(self.settings.get(u"theme"))

        def closed(s, e2):
            # the controls go home before anything else can touch them
            f(u"THost").Child = None
            self.ctl(u"TagStore").Child = content
            self.tagwin = None
            self._refresh_preview()
            self._status(u"{0} - press Run Sequence".format(self._tag_summary().capitalize()))
            try:
                self.ctl(u"ApplyBtn").Focus()
            except Exception:
                pass

        f(u"TApplyBtn").Click += self._guard(apply)
        f(u"TThemeBtn").Click += self._guard(theme)
        tw.Closed += self._guard(closed)
        if not self.ctl(u"TagCheck").IsChecked:
            # opening Tag Views or Sheets means tagging: switch it on
            self.ctl(u"TagCheck").IsChecked = True
            self._on_tag_changed(None, None)
        self._refresh_tag_open()
        # pours out of the button, as the other RevoBIM windows open
        tw.Opacity = 0.0
        tw.Show()
        tw.UpdateLayout()
        ui.genie(tw, ui.screen_point(self.ctl(u"TagOpenBtn"), self.win), None, reverse=True)

    def _close_tagwin(self):
        """Apply / close: the window pours back into its button, then closes."""
        tw = getattr(self, u"tagwin", None)
        if tw is None or self.tag_closing:
            return
        self.tag_closing = True
        if self.tagchrome is not None and self.tagchrome.shrunk:
            tw.Close()
            return

        def gone():
            try:
                tw.Close()
            except Exception:
                pass
        ui.genie(tw, ui.screen_point(self.ctl(u"TagOpenBtn"), self.win), gone)

    def _offer_open(self, tag):
        """After a run that tagged in ticked views: offer to open them (a sheet
        whose views are all ticked opens as the sheet)."""
        if not tag or not tag.get(u"views"):
            return
        sheets, view_ids = core.open_list(self.views.sheets, self.views.ticked_ids_here())
        by_id = dict((r[u"id"], r[u"eid"]) for r in self.views.rows)
        ids = [sh[u"eid"] for sh in sheets] + [by_id[v] for v in view_ids if v in by_id]
        if not ids:
            return
        what = []
        if sheets:
            what.append(u"{0} sheet{1}".format(len(sheets), u"" if len(sheets) == 1 else u"s"))
        if view_ids:
            what.append(u"{0} view{1}".format(len(view_ids), u"" if len(view_ids) == 1 else u"s"))
        msg = u"The sequence is applied and tagged. Open the {0} you ticked?".format(u" and ".join(what))
        if len(ids) > 15:
            msg += u" ({0} tabs will open.)".format(len(ids))
        if not ui.ask_yes_no(self.win, self.mode, u"Open the tagged views", msg, u"Open them", u"Not now"):
            return

        def job(uiapp):
            return rv.open_views(uiapp.ActiveUIDocument, ids, self.log)

        def done(n, err):
            self._status(u"Could not open them all - see debug" if err else
                         u"Opened {0} view(s) / sheet(s)".format(n or 0))

        self.runner.queue(u"open tagged views", job, done)

    def _guard(self, fn):
        def handler(sender, e):
            try:
                fn(sender, e)
            except Exception:
                self.log.add(u"handler {0} failed: {1}".format(
                    getattr(fn, u"__name__", u"?"), traceback.format_exc()))
                self._status(u"Something went wrong - tick Debug and Copy debug")
        return handler

    def _restore_controls(self):
        s = self.settings
        pad = core.to_int(s.get(u"pad"), 3)
        self.ctl({3: u"Fmt3", 2: u"Fmt2"}.get(pad, u"Fmt1")).IsChecked = True
        self.ctl(u"DirDown" if s.get(u"direction") == u"down" else u"DirUp").IsChecked = True
        self.ctl(u"StartBox").Text = s.get(u"start") or u"1"
        self.ctl(u"TagCheck").IsChecked = s.get(u"tag") == u"on"
        self.ctl(u"TagUntaggedCheck").IsChecked = s.get(u"tag_untagged") != u"off"
        self.ctl(u"DebugCheck").IsChecked = self.log.enabled
        self.ctl(u"ThemeText").Text = core.theme_label(s.get(u"theme"))
        self.ctl(u"TabSel" if s.get(u"tab") == u"sel" else u"TabSeq").IsChecked = True

    # ---------------------------------------------------- theme
    def _apply_theme(self):
        dark = ui.canvas_is_dark(self.uiapp)
        mode = core.resolve_theme(self.settings.get(u"theme"), dark)
        changed = mode != self.mode
        self.mode = mode
        ui.apply_palette(self.win, mode)
        tw = getattr(self, u"tagwin", None)
        if tw is not None:
            ui.apply_palette(tw, mode)
        return changed

    def _on_theme(self, sender, e):
        self.settings[u"theme"] = core.next_theme(self.settings.get(u"theme"))
        self.ctl(u"ThemeText").Text = core.theme_label(self.settings[u"theme"])
        self._apply_theme()
        self._build_tree()
        self.sel.rebuild()
        self._refresh_preview()
        self._save()

    def _on_activated(self, sender, e):
        if self.tab == u"sel":
            self.sel._check_view()
        if self.settings.get(u"theme") == u"auto" and self._apply_theme():
            self._build_tree()
            self.sel.rebuild()
            self._refresh_preview()

    # ---------------------------------------------------- tabs
    def _on_tab(self, sender, e):
        if self.loading:
            return
        self._show_tab(u"sel" if self.ctl(u"TabSel").IsChecked else u"seq")

    def _show_tab(self, tab):
        self.tab = tab
        self.settings[u"tab"] = tab
        ui.show(self.ctl(u"SeqPane"), tab == u"seq")
        ui.show(self.ctl(u"SelPane"), tab == u"sel")
        # the selector has its own Pick start / Auto Re-order under Duct / Pipe
        ui.show(self.ctl(u"PickStartBtn"), tab == u"seq")
        ui.show(self.ctl(u"AutoStartBtn"), tab == u"seq")
        self.ctl(u"StartHead").Text = u"Start point" if tab == u"seq" else u"Start point of the sequence"
        if tab == u"sel":
            self.sel.activate()
        self._refresh_shared()
        self._refresh_fold_all()
        self._save()

    def _refresh_shared(self):
        self._refresh_params()
        self._fill_tags()
        self._refresh_start()
        self._refresh_preview()

    def _sel_changed(self, params=True):
        """The System Selector changed what is numbered."""
        if self.tab != u"sel":
            return
        if params:
            self._refresh_params()
        self._fill_tags()
        self._refresh_start()
        self._refresh_preview()

    def _find_keys(self):
        """Elements of the selected system(s), for Find views with this system:
        on the System Selector the selected rows, on the Sequencer the chosen system."""
        if self.tab == u"sel":
            keys, label = self.sel.picked_keys()
            idmap = (self.sel.st()[u"data"] or {}).get(u"idmap", {})
        elif 0 <= self.sel_sys < len(self.systems):
            sysd = self.systems[self.sel_sys]
            keys, label = list(sysd[u"keys"]), sysd[u"name"]
            idmap = (self.data or {}).get(u"idmap", {})
        else:
            return [], u""
        return [idmap[k] for k in keys if k in idmap], label

    def _src(self):
        """What the shared options act on: the active tab's sequence."""
        if self.tab == u"sel":
            return self.sel.source()
        d = self.data or {}
        keys = list(d.get(u"nodes", {}))
        return {u"order": self.order, u"include": self._include, u"idmap": d.get(u"idmap", {}),
                u"labels": d.get(u"labels", {}), u"hostcat": d.get(u"hostcat", {}),
                u"storages": d.get(u"storages", {}), u"per_elem": d.get(u"per_elem", {}),
                u"keys": keys, u"total": len(keys), u"has": bool(self.systems),
                u"systems": len(self.systems), u"kind": u"duct", u"plans_only": False,
                u"view_type": u"", u"verb": u"Apply", u"after": None,
                u"empty_hint": u"Add a system to list its parameters"}

    # ---------------------------------------------------- status / busy
    def _status(self, text):
        try:
            self.ctl(u"StatusText").Text = text
        except Exception:
            pass

    def _set_busy(self, busy):
        self.busy = busy
        if busy:
            self.watchdog.Start()
        else:
            self.watchdog.Stop()
        self._refresh_apply()

    def _on_watchdog(self, sender, e):
        self.watchdog.Stop()
        if self.busy:
            self.log.add(u"watchdog freed a busy window")
            self.busy = False
            self._status(u"Revit did not answer - try again")
            self._refresh_apply()

    def _queue(self, name, fn, cb, status):
        if self.busy:
            self.log.add(u"click ignored while busy: " + name)
            self._status(u"Busy - waiting for Revit")
            return
        self._set_busy(True)
        self._status(status)

        def done(res, err):
            self._set_busy(False)
            cb(res, err)

        self.runner.queue(name, fn, done)

    # ---------------------------------------------------- reading
    def read_now(self, uiapp):
        """At launch we are inside the command, so read directly."""
        res = self._job_add_selection(uiapp)
        self._added(res, None)
        self.views.load_now(uiapp)
        if self.settings.get(u"tab") == u"sel":
            self.sel.read_now(uiapp)
            self._show_tab(u"sel")

    def _known(self):
        return set(self.data[u"nodes"]) if self.data else set()

    def _read(self, doc, elems):
        data = rv.read_network(doc, elems, self.log)
        storages, per_elem = rv.param_map(elems)
        data[u"storages"] = storages
        data[u"per_elem"] = per_elem
        return data

    def _job_add_selection(self, uiapp):
        uidoc = uiapp.ActiveUIDocument
        doc = uidoc.Document
        ids = list(uidoc.Selection.GetElementIds())
        known = self._known()
        elems = [e for e in rv.expand_selection(doc, ids) if rv.eid_value(e.Id) not in known]
        self.log.add(u"add selection: {0} ids -> {1} new duct elements".format(len(ids), len(elems)))
        return {u"reads": [self._read(doc, elems)] if elems else [], u"starts": {},
                u"tags": rv.tag_choices(doc)}

    def _job_pick_systems(self, uiapp):
        """Pick the first element of each system in turn until Escape. Each
        pick reads that element's connected system and starts it there."""
        uidoc = uiapp.ActiveUIDocument
        doc = uidoc.Document
        known = self._known()
        reads = []
        starts = {}
        while True:
            n = len(self.systems) + len(reads) + 1
            el = rv.pick_duct_element(uidoc, u"RevoBIM Number Sequencer: click the first element "
                                             u"of system {0} - Esc when done".format(n))
            if el is None:
                break
            k = rv.eid_value(el.Id)
            starts[k] = True
            if k in known:
                continue  # already listed: it just becomes that system's start
            elems = [e for e in rv.collect_network(doc, el) if rv.eid_value(e.Id) not in known]
            for e in elems:
                known.add(rv.eid_value(e.Id))
            self.log.add(u"picked {0}: {1} new elements".format(k, len(elems)))
            if elems:
                reads.append(self._read(doc, elems))
        if not reads and not starts:
            return None
        return {u"reads": reads, u"starts": starts, u"tags": rv.tag_choices(doc)}

    def _job_pick_start(self, uiapp):
        uidoc = uiapp.ActiveUIDocument
        doc = uidoc.Document
        el = rv.pick_duct_element(uidoc, u"RevoBIM Number Sequencer: click the element to start numbering from")
        if el is None:
            return None
        k = rv.eid_value(el.Id)
        if k in self._known():
            return {u"reads": [], u"starts": {k: True}, u"tags": None}
        known = self._known()
        elems = [e for e in rv.collect_network(doc, el) if rv.eid_value(e.Id) not in known]
        return {u"reads": [self._read(doc, elems)] if elems else [], u"starts": {k: True}, u"tags": None}

    def _on_add_selection(self, sender, e):
        self._queue(u"add selection", self._job_add_selection, self._added,
                    u"Reading the Revit selection")

    def _on_pick_systems(self, sender, e):
        self._queue(u"pick systems", self._job_pick_systems, self._added,
                    u"Click the first element of each system, in order - Esc when done")

    def _on_pick_start(self, sender, e):
        if self.tab == u"sel":
            self.sel.pick_start()
            return
        self._queue(u"pick start", self._job_pick_start, self._added,
                    u"Click the element to start numbering from (Esc cancels)")

    def _added(self, res, err):
        if err:
            self._status(u"Could not read - see debug")
            return
        if res is None:
            self._status(u"Cancelled")
            return
        if res.get(u"tags") is not None:
            self.tags = res[u"tags"]
            self._fill_tags()
        starts = res.get(u"starts") or {}
        moved = 0
        for i, sysd in enumerate(self.systems):
            for k in starts:
                if k in sysd[u"keys_set"]:
                    sysd[u"start"] = k
                    self.sel_sys = i
                    moved += 1
        added = 0
        for data in res.get(u"reads") or []:
            new_keys = self._merge(data)
            if not new_keys:
                continue
            comps = core.components(self.data[u"nodes"], new_keys)
            for comp, st in core.order_systems(self.data[u"nodes"], comps, starts, self._exit_point()):
                self._append_system(comp, st)
                added += 1
        self._refresh_all()
        if added:
            self._status(u"Added {0} system(s) - {1} in the sequence".format(added, len(self.systems)))
        elif moved:
            self._status(u"Start moved")
        elif not self.systems:
            self._status(u"Nothing with duct connectors selected - tab-select duct systems, or Pick systems")
        else:
            self._status(u"Nothing new - those elements are already in the sequence")

    # ---------------------------------------------------- the model held
    def _merge(self, data):
        if self.data is None:
            self.data = {u"nodes": {}, u"rows": [], u"idmap": {}, u"hostcat": {}, u"labels": {},
                         u"sysname": {}, u"storages": {}, u"per_elem": {}}
        d = self.data
        new = [k for k in data[u"nodes"] if k not in d[u"nodes"]]
        for k in new:
            d[u"nodes"][k] = data[u"nodes"][k]
            for name in (u"idmap", u"hostcat", u"labels", u"sysname", u"per_elem"):
                if k in data.get(name, {}):
                    d[name][k] = data[name][k]
        new_set = set(new)
        for row in data[u"rows"]:
            if row[0] in new_set:
                d[u"rows"].append(row)
                self.type_of[row[0]] = core.type_key(row[1], row[2], row[3])
        for name, st in data.get(u"storages", {}).items():
            d[u"storages"].setdefault(name, st)
        return new

    def _drop_keys(self, keys):
        d = self.data
        if not d:
            return
        gone = set(keys)
        for k in gone:
            for name in (u"nodes", u"idmap", u"hostcat", u"labels", u"sysname", u"per_elem"):
                d[name].pop(k, None)
            self.type_of.pop(k, None)
        d[u"rows"] = [r for r in d[u"rows"] if r[0] not in gone]

    def _append_system(self, comp, start):
        self.sys_seq += 1
        name = core.system_name(comp, self.data[u"sysname"], u"System {0}".format(self.sys_seq))
        self.systems.append({u"keys": list(comp), u"keys_set": set(comp), u"start": start, u"name": name})
        self.sel_sys = len(self.systems) - 1
        self.log.add(u"system {0}: {1}, {2} elements, start {3}".format(
            len(self.systems), name, len(comp), start))

    def _exit_point(self):
        """Where the last listed system finishes - the next one starts nearest it."""
        if not self.systems or not self.data:
            return None
        last = self.systems[-1]
        order = core.system_order(self.data[u"nodes"], last[u"keys"], last[u"start"])
        if not order:
            return None
        return core.node_point(self.data[u"nodes"][order[-1]])

    def _refresh_all(self):
        self._refresh_params()
        self._recompute_order()
        self._build_tree()

    def _refresh_params(self):
        src = self._src()
        self.params = core.param_list(src[u"storages"], src[u"per_elem"], src[u"keys"]) if src[u"keys"] else []
        self._fill_params()

    # ---------------------------------------------------- systems list
    def _recompute_order(self):
        if not self.systems or not self.data:
            self.order, self.spans = [], []
        else:
            self.order, self.spans = core.full_order(self.data[u"nodes"], self.systems)
            self.log.add(u"walk: {0} elements over {1} system(s)".format(len(self.order), len(self.systems)))
        if self.systems:
            self.sel_sys = max(0, min(self.sel_sys, len(self.systems) - 1))
        else:
            self.sel_sys = -1
        self._build_systems()
        self._refresh_start()
        self._refresh_preview()

    def _build_systems(self):
        host = self.ctl(u"SystemHost")
        host.Children.Clear()
        self.sys_rows = []
        for i, sysd in enumerate(self.systems):
            row = Border()
            row.CornerRadius = CornerRadius(3)
            row.Margin = Thickness(0, 1, 0, 1)
            row.Padding = Thickness(4, 3, 8, 3)
            row.Cursor = Cursors.Hand
            if i == self.sel_sys:
                row.SetResourceReference(Border.BackgroundProperty, u"Sel")
            grid = Grid()
            for w in (26, None, None, None):
                cd = ColumnDefinition()
                cd.Width = GridLength(w) if w else GridLength.Auto
                grid.ColumnDefinitions.Add(cd)
            grid.ColumnDefinitions[1].Width = GridLength(1, getattr(GridUnitType, u"Star"))
            badge = Border()
            badge.Width = 20
            badge.Height = 20
            badge.CornerRadius = CornerRadius(10)
            badge.SetResourceReference(Border.BackgroundProperty, u"Orange")
            num = TextBlock()
            num.Text = u"{0}".format(i + 1)
            num.FontSize = 11
            num.FontWeight = FontWeights.SemiBold
            num.HorizontalAlignment = getattr(HorizontalAlignment, u"Center")
            num.VerticalAlignment = getattr(VerticalAlignment, u"Center")
            num.SetResourceReference(TextBlock.ForegroundProperty, u"OnAccent")
            badge.Child = num
            Grid.SetColumn(badge, 0)
            grid.Children.Add(badge)
            name = TextBlock()
            name.Text = sysd[u"name"] + (u"   (picked start)" if sysd[u"start"] is not None else u"")
            name.Margin = Thickness(4, 0, 6, 0)
            name.VerticalAlignment = getattr(VerticalAlignment, u"Center")
            name.TextTrimming = getattr(TextTrimming, u"CharacterEllipsis")
            name.SetResourceReference(TextBlock.ForegroundProperty, u"Text")
            Grid.SetColumn(name, 1)
            grid.Children.Add(name)
            rng = TextBlock()
            rng.Margin = Thickness(0, 0, 10, 0)
            rng.VerticalAlignment = getattr(VerticalAlignment, u"Center")
            rng.SetResourceReference(TextBlock.ForegroundProperty, u"Blue")
            Grid.SetColumn(rng, 2)
            grid.Children.Add(rng)
            cnt = TextBlock()
            cnt.Text = u"{0} el.".format(len(sysd[u"keys"]))
            cnt.VerticalAlignment = getattr(VerticalAlignment, u"Center")
            cnt.SetResourceReference(TextBlock.ForegroundProperty, u"Muted")
            Grid.SetColumn(cnt, 3)
            grid.Children.Add(cnt)
            row.Child = grid
            row.ToolTip = u"Click to choose, double-click to select this system in Revit"
            row.MouseLeftButtonDown += self._guard(self._sys_click(i))
            host.Children.Add(row)
            self.sys_rows.append(rng)
        n = len(self.systems)
        self.ctl(u"SysCountText").Text = u"{0} system{1}".format(n, u"" if n == 1 else u"s") if n else u""
        has = 0 <= self.sel_sys < n
        self.ctl(u"SysUpBtn").IsEnabled = has and self.sel_sys > 0
        self.ctl(u"SysDownBtn").IsEnabled = has and self.sel_sys < n - 1
        self.ctl(u"SysRemoveBtn").IsEnabled = has
        self.ctl(u"SysClearBtn").IsEnabled = n > 0

    def _sys_click(self, index):
        def handler(sender, e):
            if e.ClickCount == 2:
                ids = [self.data[u"idmap"][k] for k in self.systems[index][u"keys"]
                       if k in self.data[u"idmap"]]
                self._select_ids(ids)
                e.Handled = True
                return
            self.sel_sys = index
            self._build_systems()
            self._refresh_system_ranges(self._plan()[0])
            self._refresh_start()
            e.Handled = True
        return handler

    def _refresh_system_ranges(self, plan):
        if not self.sys_rows:
            return
        ranges = core.system_ranges(plan or [], [self.order[a:b] for a, b in self.spans])
        for tb, r in zip(self.sys_rows, ranges):
            tb.Text = (r[0] if r[0] == r[1] else u"{0} - {1}".format(r[0], r[1])) if r else u"none"

    def _on_sys_up(self, sender, e):
        i = self.sel_sys
        if 0 < i < len(self.systems):
            self.systems[i - 1], self.systems[i] = self.systems[i], self.systems[i - 1]
            self.sel_sys = i - 1
            self._recompute_order()

    def _on_sys_down(self, sender, e):
        i = self.sel_sys
        if 0 <= i < len(self.systems) - 1:
            self.systems[i + 1], self.systems[i] = self.systems[i], self.systems[i + 1]
            self.sel_sys = i + 1
            self._recompute_order()

    def _on_sys_remove(self, sender, e):
        i = self.sel_sys
        if 0 <= i < len(self.systems):
            gone = self.systems.pop(i)
            self._drop_keys(gone[u"keys"])
            self._refresh_all()

    def _on_sys_clear(self, sender, e):
        self.systems = []
        self.data = None
        self.type_of = {}
        self.sys_seq = 0
        self._refresh_all()

    # ---------------------------------------------------- start point
    def _on_auto_start(self, sender, e):
        if self.tab == u"sel":
            self.sel.auto_reorder(step=self.sel._shift())
            return
        if 0 <= self.sel_sys < len(self.systems):
            self.systems[self.sel_sys][u"start"] = None
            self._recompute_order()

    def _sel_start_key(self):
        if not (0 <= self.sel_sys < len(self.spans)):
            return None
        a, b = self.spans[self.sel_sys]
        return self.order[a] if b > a else None

    def _on_show_start(self, sender, e):
        if self.tab == u"sel":
            self.sel.show_start()
            return
        k = self._sel_start_key()
        if k is not None:
            self._select_ids([self.data[u"idmap"].get(k)])

    def _select_ids(self, ids, zoom=True):
        """Select in Revit. Clicks in quick succession only send the last one,
        and selecting never blocks the window."""
        self.want_select = (list(ids), zoom)
        if self.select_queued:
            return
        self.select_queued = True

        def job(uiapp):
            self.select_queued = False
            want = self.want_select
            self.want_select = None
            if want is None:
                return False
            rv.select_and_show(uiapp.ActiveUIDocument, want[0], want[1])
            return True

        def done(r, err):
            self.select_queued = False
            if err:
                self._status(u"Could not select - see debug")

        self.runner.queue(u"select", job, done)

    def _refresh_start(self):
        if self.tab == u"sel":
            self.sel.refresh_start()
            return
        auto = self.ctl(u"AutoStartBtn")
        ui.set_button(auto, u"auto", u"Auto")
        auto.SetResourceReference(FrameworkElement.StyleProperty, u"ToolButton")
        auto.ToolTip = u"Put the chosen system back on the automatic start"
        t = self.ctl(u"StartText")
        k = self._sel_start_key()
        if k is None:
            t.Text = u"No systems yet - Add selection or Pick systems"
            return
        sysd = self.systems[self.sel_sys]
        how = u"picked" if sysd[u"start"] is not None else u"auto"
        t.Text = u"System {0}, {1}: starts ({2}) at {3}  [{4}]".format(
            self.sel_sys + 1, sysd[u"name"], how, self.data[u"labels"].get(k, u""), k)

    # ---------------------------------------------------- the family tree (Sequencer tab)
    def _build_tree(self):
        d = self.data or {}
        self.tree.set_rows(d.get(u"rows", []), len(d.get(u"nodes", {})))
        self.tree.build()

    def _on_tree_changed(self):
        self._refresh_preview()
        self._save()

    def _on_tree_select(self, keys):
        idmap = (self.data or {}).get(u"idmap", {})
        self._select_ids([idmap[k] for k in keys if k in idmap])

    def _on_expand_all(self, sender, e):
        self.tree.expand_all()

    def _on_collapse_all(self, sender, e):
        self.tree.collapse_all()

    def _on_tick_all(self, sender, e):
        if self.data:
            self.tree.tick_all()

    def _on_untick_all(self, sender, e):
        if self.data:
            self.tree.untick_all()

    def _on_search(self, sender, e):
        self.tree.build()

    # ---------------------------------------------------- parameter: type-to-filter dropdown
    def _fill_params(self):
        names = [p[0] for p in self.params]
        if self.param_name not in names:
            self.param_name = core.default_parameter(names, self.settings.get(u"parameter")) or None
        self._param_text(self.param_name or u"")
        self._refresh_param_note()

    def _param_text(self, text):
        self.param_typing = True
        try:
            self.ctl(u"ParamBox").Text = text
        finally:
            self.param_typing = False

    def _chosen_param(self):
        for p in self.params:
            if p[0] == self.param_name:
                return p
        return None

    def _show_param_list(self, typed):
        """Rebuild the dropdown with the names containing what was typed."""
        self.param_hits = core.filter_params(self.params, typed)
        host = self.ctl(u"ParamListHost")
        host.Children.Clear()
        self.param_items = []
        src = self._src()
        total = src[u"total"]
        if not self.param_hits:
            tb = TextBlock()
            tb.Margin = Thickness(8, 6, 8, 6)
            tb.Text = u"No parameter contains \"{0}\"".format(typed.strip()) if self.params \
                else src[u"empty_hint"]
            tb.SetResourceReference(TextBlock.ForegroundProperty, u"Muted")
            host.Children.Add(tb)
        for i, p in enumerate(self.param_hits[:PARAM_LIST_MAX]):
            row = Border()
            row.Padding = Thickness(8, 4, 8, 4)
            row.CornerRadius = CornerRadius(3)
            row.Cursor = Cursors.Hand
            dock = DockPanel()
            info = TextBlock()
            info.Text = u"{0}  {1}/{2}".format(u"text" if p[1] == u"text" else u"integer", p[2], total)
            info.FontSize = 11
            info.Margin = Thickness(12, 0, 0, 0)
            info.SetResourceReference(TextBlock.ForegroundProperty, u"Muted")
            DockPanel.SetDock(info, getattr(Dock, u"Right"))
            dock.Children.Add(info)
            name = TextBlock()
            name.Text = p[0]
            if p[0] == self.param_name:
                name.FontWeight = FontWeights.SemiBold
                name.SetResourceReference(TextBlock.ForegroundProperty, u"Blue")
            else:
                name.SetResourceReference(TextBlock.ForegroundProperty, u"Text")
            dock.Children.Add(name)
            row.Child = dock
            row.MouseLeftButtonDown += self._guard(self._param_click(p[0]))
            row.MouseEnter += self._guard(self._param_hover(i))
            host.Children.Add(row)
            self.param_items.append(row)
        names = [p[0] for p in self.param_hits]
        if typed.strip():
            self.param_hi = 0 if names else -1
        else:
            self.param_hi = names.index(self.param_name) if self.param_name in names else -1
        self._paint_param_hi()
        self.ctl(u"ParamPopup").IsOpen = True

    def _paint_param_hi(self):
        for i, row in enumerate(self.param_items):
            if i == self.param_hi:
                row.SetResourceReference(Border.BackgroundProperty, u"Hover")
                try:
                    row.BringIntoView()
                except Exception:
                    pass
            else:
                row.ClearValue(Border.BackgroundProperty)

    def _list_text(self):
        """What to filter by: the box text, unless it still shows the chosen name."""
        text = self.ctl(u"ParamBox").Text or u""
        return u"" if text == (self.param_name or u"") else text

    def _on_param_typed(self, sender, e):
        if self.param_typing:
            return
        self._show_param_list(self.ctl(u"ParamBox").Text or u"")

    def _on_param_drop(self, sender, e):
        self._show_param_list(u"")
        self.ctl(u"ParamBox").Focus()

    def _on_param_mouse(self, sender, e):
        box = self.ctl(u"ParamBox")
        if not box.IsKeyboardFocusWithin:
            box.Focus()
            self._show_param_list(u"")
            e.Handled = True

    def _on_param_focus(self, sender, e):
        self.ctl(u"ParamBox").SelectAll()

    def _on_param_left(self, sender, e):
        """Leaving the box: an exact name typed counts as chosen, anything
        else goes back to the chosen parameter. Typing never changes it."""
        exact = core.exact_param(self.params, self.ctl(u"ParamBox").Text)
        if exact and exact != self.param_name:
            self._choose_param(exact)
            return
        self._param_text(self.param_name or u"")

    def _on_param_keys(self, sender, e):
        popup = self.ctl(u"ParamPopup")
        key = e.Key
        if key == getattr(Key, u"Down") or key == getattr(Key, u"Up"):
            if not popup.IsOpen:
                self._show_param_list(self._list_text())
            n = len(self.param_items)
            if n:
                step = 1 if key == getattr(Key, u"Down") else -1
                self.param_hi = max(0, min(n - 1, self.param_hi + step))
                self._paint_param_hi()
            e.Handled = True
        elif key == getattr(Key, u"Enter"):
            if popup.IsOpen and self.param_items:
                i = self.param_hi if 0 <= self.param_hi < len(self.param_items) else 0
                self._choose_param(self.param_hits[i][0])
            e.Handled = True
        elif key == getattr(Key, u"Escape") and popup.IsOpen:
            popup.IsOpen = False
            self._param_text(self.param_name or u"")
            e.Handled = True

    def _param_click(self, name):
        def handler(sender, e):
            self._choose_param(name)
            e.Handled = True
        return handler

    def _param_hover(self, index):
        def handler(sender, e):
            self.param_hi = index
            self._paint_param_hi()
        return handler

    def _choose_param(self, name):
        self.param_name = name
        self.ctl(u"ParamPopup").IsOpen = False
        self._param_text(name)
        self.settings[u"parameter"] = name
        self._save()
        self._refresh_param_note()
        self._refresh_preview()

    def _refresh_param_note(self):
        p = self._chosen_param()
        note = self.ctl(u"ParamNote")
        src = self._src()
        if not src[u"has"]:
            note.Text = u""
        elif p is None:
            note.Text = u"No writable text or integer parameter found on these elements"
        else:
            total = src[u"total"]
            kind = u"Text" if p[1] == u"text" else u"Integer"
            note.Text = u"{0} parameter on {1} of {2} elements".format(kind, p[2], total)
            if p[2] < total:
                note.Text += u" - the rest are reported after {0}".format(src[u"verb"])

    # ---------------------------------------------------- sequence
    def _pad(self):
        if self.ctl(u"Fmt3").IsChecked:
            return 3
        if self.ctl(u"Fmt2").IsChecked:
            return 2
        return 0

    def _direction(self):
        return u"down" if self.ctl(u"DirDown").IsChecked else u"up"

    def _on_sequence_changed(self, sender, e):
        if self.loading:
            return
        self.settings[u"pad"] = u"{0}".format(self._pad())
        self.settings[u"direction"] = self._direction()
        self.settings[u"start"] = (self.ctl(u"StartBox").Text or u"").strip()
        self._save()
        self._refresh_preview()

    def _include(self, key):
        return self.type_of.get(key) not in self.skipped

    def _plan(self, src=None):
        src = src or self._src()
        start = core.parse_start(self.ctl(u"StartBox").Text)
        if not src[u"order"] or start is None:
            return None, [], start
        plan, errors = core.plan_numbers(src[u"order"], src[u"include"], start,
                                         self._direction(), self._pad())
        return plan, errors, start

    def _refresh_preview(self):
        prev = self.ctl(u"PreviewText")
        src = self._src()
        plan, errors, start = self._plan(src)
        if self.tab == u"sel":
            self.sel.refresh_ranges(plan)
        else:
            self._refresh_system_ranges(plan)
        if not src[u"has"]:
            prev.Text = u""
        elif start is None:
            prev.Text = u"Type a whole number to start from, e.g. 045"
        else:
            skipped = len([k for k in src[u"order"] if not src[u"include"](k)])
            prev.Text = core.preview_text(plan, errors, skipped, self._pad())
            if src[u"systems"] > 1:
                prev.Text += u"  |  {0} systems".format(src[u"systems"])
        self._refresh_tag_note(plan, src)
        self._refresh_apply(plan, src)

    def _refresh_apply(self, plan=None, src=None):
        src = src or self._src()
        if plan is None:
            plan = self._plan(src)[0]
        n = len(plan or [])
        ok = bool(n) and self._chosen_param() is not None and not self.busy
        waiting = bool(src.get(u"needs_start")) and not src.get(u"started")
        # the System Selector runs only once a start is picked (step 2.2)
        self.ctl(u"ApplyBtn").IsEnabled = ok and not waiting
        self.ctl(u"ApplyBtn").ToolTip = (u"Pick a start first (2.3 Pick start)" if waiting else
                                         u"Number the sequence (and tag it, when Tags is on)")
        ui.set_icon_data(self.ctl(u"ApplyIcon"), u"run")
        self.ctl(u"ApplyText").Text = u"Run Sequence ({0})".format(n) if n else u"Run Sequence"

    # ---------------------------------------------------- tags
    def _fill_tags(self):
        combo = self.ctl(u"TagCombo")
        saved = self.settings.get(u"tag_type")
        self.tag_view = core.tags_for_kind(self.tags, self._src()[u"kind"])
        was = self.loading
        self.loading = True
        try:
            combo.Items.Clear()
            pick = None
            fallback = None
            for i, t in enumerate(self.tag_view):
                item = ComboBoxItem()
                item.Content = t[u"label"]
                item.Tag = i
                combo.Items.Add(item)
                if t[u"label"] == saved:
                    pick = item
                if fallback is None and t[u"tag_cat"] == u"OST_MultiCategoryTags":
                    fallback = item
            pick = pick or fallback
            if pick is None and combo.Items.Count:
                pick = combo.Items[0]
            if pick is not None:
                combo.SelectedItem = pick
        finally:
            self.loading = was
        self._sync_tag_enabled()

    def _chosen_tag(self):
        item = self.ctl(u"TagCombo").SelectedItem
        if item is None:
            return None
        try:
            return self.tag_view[int(item.Tag)]
        except Exception:
            return None

    def _sync_tag_enabled(self):
        on = bool(self.ctl(u"TagCheck").IsChecked)
        self.ctl(u"TagCombo").IsEnabled = on
        self.ctl(u"TagUntaggedCheck").IsEnabled = on

    def _tag_plan(self, plan, src):
        """(by_host, host categories in plan order) for the chosen tag: where it
        cannot go, the tag made for that category (else a multi-category tag)."""
        hosts = [src[u"hostcat"].get(k) for k, n, s in (plan or [])]
        return core.tag_for_hosts(self.tags, self._chosen_tag(), hosts), hosts

    def _on_tag_changed(self, sender, e):
        if self.loading:
            return
        self._sync_tag_enabled()
        self.settings[u"tag"] = u"on" if self.ctl(u"TagCheck").IsChecked else u"off"
        self.settings[u"tag_untagged"] = u"on" if self.ctl(u"TagUntaggedCheck").IsChecked else u"off"
        t = self._chosen_tag()
        if t is not None:
            self.settings[u"tag_type"] = t[u"label"]
        self._save()
        self._refresh_tag_note(self._plan()[0])

    def _refresh_tag_note(self, plan, src=None):
        self._refresh_tag_open()
        src = src or self._src()
        note = self.ctl(u"TagNote")
        if not self.ctl(u"TagCheck").IsChecked:
            note.Text = u"Plan views only on this tab" if src[u"plans_only"] else u""
            return
        t = self._chosen_tag()
        if t is None:
            note.Text = u"No {0}, fitting, accessory, fabrication or multi-category tags are loaded".format(
                src[u"kind"])
            return
        if not plan:
            note.Text = u""
            return
        by_host, hosts = self._tag_plan(plan, src)
        yes, no, others = core.tag_plan_note(by_host, t, hosts)
        if not no:
            text = u"Tags all {0} numbered elements".format(yes)
        else:
            text = u"Tags {0} of {1} - no loaded tag can take the other {2}; " \
                   u"load one for their category or a multi-category tag".format(yes, yes + no, no)
        if others:
            text += u". This tag cannot take every category, so " + u"; ".join(
                [u"{0} get {1}".format(n, label) for label, n in others])
        if self.ctl(u"TagUntaggedCheck").IsChecked:
            text += u". Anything already tagged in a view is left alone"
        n = self.views.ticked_count()
        if n:
            text = u"Tags go in the {0} ticked view(s), wherever the numbered elements show " \
                   u"(3D views must be locked). ".format(n) + text
        elif src[u"plans_only"]:
            ok, why = core.tag_view_ok(src[u"view_type"], plans_only=True)
            text = u"Active view - plan views only. " + text if ok else u"No tags will be placed: " + why
        note.Text = text

    # ---------------------------------------------------- apply / run
    def _on_apply(self, sender, e):
        src = self._src()
        if src.get(u"needs_start") and not src.get(u"started"):
            self._status(u"Pick a start first (2.3 Pick start)")
            return
        plan, pre_errors, start = self._plan(src)
        p = self._chosen_param()
        if not plan or p is None:
            return
        name, storage = p[0], p[1]
        idmap = src[u"idmap"]
        labels = src[u"labels"]
        after = src[u"after"]
        tag = None
        if self.ctl(u"TagCheck").IsChecked:
            t = self._chosen_tag()
            if t is not None:
                by_host, hosts = self._tag_plan(plan, src)
                tag = {u"on": True, u"id": t[u"id"], u"tag_cat": t[u"tag_cat"],
                       u"plans_only": bool(src[u"plans_only"]), u"views": self.views.ticked_ids(),
                       u"views_doc": self.views.doc_key,
                       u"by_host": dict((h, (None if v is None else {u"id": v[u"id"], u"tag_cat": v[u"tag_cat"],
                                                                     u"label": v[u"label"]}))
                                        for h, v in by_host.items() if h is not None),
                       u"untagged_only": bool(self.ctl(u"TagUntaggedCheck").IsChecked)}
        self.log.add(u"{0}: {1} planned, param {2} ({3}), pad {4}, start {5} {6}, tag {7}".format(
            src[u"verb"].lower(), len(plan), name, storage, self._pad(), start, self._direction(),
            tag[u"tag_cat"] if tag else u"off"))
        for k, n, text in plan:
            self.log.add(u"  {0} -> {1}  {2}".format(k, text, labels.get(k, u"")))

        def job(uiapp):
            doc = uiapp.ActiveUIDocument.Document
            writes, same, errors = core.prepare_writes(
                plan, lambda k: rv.read_param_info(doc.GetElement(idmap[k]), name))
            res = rv.apply_job(uiapp, {u"param": name, u"storage": storage, u"writes": writes,
                                       u"same": same, u"idmap": idmap, u"tag": tag}, self.log)
            res[u"errors"] = list(pre_errors) + errors + res[u"errors"]
            res[u"cleared"] = 0
            if after is not None:
                try:
                    res[u"cleared"] = after(uiapp)
                except Exception:
                    self.log.add(u"after run failed: " + traceback.format_exc())
                    res[u"errors"].append((None, u"The view colours could not be cleared - use Clear colours"))
            return res

        self._queue(src[u"verb"].lower(), job, lambda r, err: self._applied(r, err, src, tag),
                    u"Numbering")

    def _applied(self, res, err, src=None, tag=None):
        src = src or self._src()
        if err or res is None:
            self._status(u"{0} failed - see debug".format(src[u"verb"]))
            self._show_results([(None, err or u"{0} failed".format(src[u"verb"]))], src)
            return
        msg = u"Numbered {0}".format(res[u"written"])
        if res[u"same"]:
            msg += u" ({0} already right)".format(res[u"same"])
        if res[u"tagged"] or res[u"tag_skipped"]:
            msg += u"  |  tagged {0}".format(res[u"tagged"])
            if res.get(u"tag_views"):
                msg += u" in {0} view(s)".format(res[u"tag_views"])
            if res.get(u"tag_already"):
                msg += u", {0} already tagged".format(res[u"tag_already"])
            if res.get(u"tag_no_tag"):
                msg += u", {0} with no tag for their category".format(res[u"tag_no_tag"])
        if res.get(u"cleared"):
            msg += u"  |  view colours cleared"
        if res[u"errors"]:
            msg += u"  |  {0} to check".format(len(res[u"errors"]))
        self._status(msg)
        self.sel.after_run_ui()
        self.log.write()
        if res[u"errors"]:
            errs = res[u"errors"]
            # show after Execute has returned so Revit is not held
            self.win.Dispatcher.BeginInvoke(Action(lambda: self._show_results(errs, src)))
        if tag and tag.get(u"views") and res.get(u"tagged"):
            self.win.Dispatcher.BeginInvoke(Action(lambda: self._offer_open(tag)))

    # ---------------------------------------------------- results window
    def _show_results(self, errors, src=None):
        src = src or self._src()
        self.last_errors = errors
        try:
            rw = ui.load_xaml(u"NumberSequencerResults.xaml")
            ui.merge_theme(rw)
            ui.apply_palette(rw, self.mode)
            try:
                ui.iconize(rw)
            except Exception:
                pass
            rw.Owner = self.win
            f = rw.FindName
            f(u"RVersion").Text = u"v" + core.__version__
            icon = ui.load_icon()
            if icon is not None:
                f(u"RIcon").Source = icon
            f(u"RSummary").Text = u"{0} item(s) were not numbered or tagged. " \
                                  u"Everything else in the sequence went through.".format(len(errors))
            lst = f(u"RList")
            idmap = src[u"idmap"]
            labels = src[u"labels"]
            for k, msg in errors:
                tb = TextBlock()
                tb.TextWrapping = getattr(TextWrapping, u"Wrap")
                tb.Margin = Thickness(4, 2, 4, 2)
                tb.SetResourceReference(TextBlock.ForegroundProperty, u"Text")
                if k is None:
                    tb.Text = msg
                else:
                    tb.Text = u"{0}  {1}  -  {2}".format(k, labels.get(k, u""), msg)
                    tb.Cursor = Cursors.Hand
                    tb.MouseLeftButtonDown += self._guard(self._result_click(idmap.get(k)))
                lst.Children.Add(tb)
            text = u"\n".join([u"{0}\t{1}\t{2}".format(k or u"", labels.get(k, u""), m) for k, m in errors])

            def close(s, e):
                rw.Close()

            def copy(s, e):
                try:
                    Clipboard.SetText(text)
                except Exception:
                    pass

            def select(s, e):
                ids = [idmap[k] for k, m in errors if k in idmap]
                if ids:
                    self._select_ids(ids)

            def drag(s, e):
                try:
                    rw.DragMove()
                except Exception:
                    pass

            f(u"RCloseX").Click += close
            f(u"RCloseBtn").Click += close
            f(u"RCopyBtn").Click += copy
            f(u"RSelectBtn").Click += select
            f(u"RHeader").MouseLeftButtonDown += drag
            rw.Show()
        except Exception:
            self.log.add(u"results window failed: " + traceback.format_exc())

    def _result_click(self, eid):
        def handler(sender, e):
            if e.ClickCount == 2 and eid is not None:
                self._select_ids([eid])
        return handler

    # ---------------------------------------------------- debug, save, close
    def _on_debug(self, sender, e):
        self.log.enabled = bool(self.ctl(u"DebugCheck").IsChecked)
        self.settings[u"debug"] = u"on" if self.log.enabled else u"off"
        self._save()

    def _on_copy_debug(self, sender, e):
        text = core.format_settings(self.settings) + u"\n" + self.log.text()
        try:
            Clipboard.SetText(text)
            self._status(u"Debug copied to the clipboard")
        except Exception:
            self._status(u"Could not reach the clipboard")
        self.log.write()

    def _save(self):
        if self.loading:
            return
        self.settings[u"skip"] = core.skip_text_from(self.skipped)
        self.settings[u"sel_skip"] = core.skip_text_from(self.sel.skipped)
        core.save_settings(self.settings)

    def _remember_size(self):
        w = self.win
        if self.chrome.full:
            return
        height = self.chrome.before[1] if self.chrome.shrunk and self.chrome.before else w.ActualHeight
        self.settings[u"win_w"] = u"{0}".format(int(round(w.ActualWidth)))
        self.settings[u"win_h"] = u"{0}".format(int(round(height)))

    def _on_closed(self, sender, e):
        try:
            self._remember_size()
        except Exception:
            pass
        tw = getattr(self, u"tagwin", None)
        if tw is not None:
            try:
                tw.Close()
            except Exception:
                pass
        self.sel.on_closed()
        self._save()
        self.log.write()
        try:
            AppDomain.CurrentDomain.SetData(APPDOMAIN_KEY, None)
        except Exception:
            pass

    def show(self):
        AppDomain.CurrentDomain.SetData(APPDOMAIN_KEY, self)
        self.win.Show()
        self.win.Activate()


def existing_window():
    try:
        w = AppDomain.CurrentDomain.GetData(APPDOMAIN_KEY)
        if w is not None and w.win.IsVisible:
            return w
    except Exception:
        pass
    return None


def launch(uiapp):
    w = existing_window()
    if w is not None:
        try:
            w.win.Activate()
            if w.tab == u"sel":
                w.sel.refresh()
            else:
                w._on_add_selection(None, None)
        except Exception:
            pass
        return w
    w = SequencerWindow(uiapp)
    w.read_now(uiapp)
    w.show()
    return w
