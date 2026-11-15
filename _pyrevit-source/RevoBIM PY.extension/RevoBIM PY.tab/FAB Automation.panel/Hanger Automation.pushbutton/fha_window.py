# -*- coding: utf-8 -*-
u"""The modeless Hanger Automation window and its ExternalEvent runner.

Three tabs: FAB Hangers (fha_revit), Family Hangers and Family Floor Support
(both hfam_ui.FamTab / hfam_revit, the floor one in mode 'floor').  All share
one ExternalEvent.  start_job runs a tool and reports in the results
box; start_quiet runs a read (family list, preview, parameter names) and hands
the answer to a callback without touching the results or the debug file.

All Python-side state lives on FhaWindow / FhaHandler / ui.Chrome (Python
objects).  Nothing is ever assigned onto the WPF Window or a control except
real WPF properties (PascalCase).
"""
import fha_clr  # noqa: F401  (must be first)
import traceback
import fha_core as core
import fha_ui as ui
import fha_revit as rv
import hfam_ui
import hview_ui
import hfam_revit
from System.Windows import Visibility
from System import Action, TimeSpan
from System.Windows import Clipboard

# tab key -> (tab button, panel)
TABS = {u'fab': ('TabFab', 'FabPanel'), u'fam': ('TabFam', 'FamPanel'), u'floor': ('TabFloor', 'FloorPanel')}
from System.Windows.Threading import DispatcherTimer
from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent

WATCHDOG_SECONDS = 20
JOB_BUTTONS = ('BtnRehost', 'BtnExtend', 'BtnPlace')
CHECKS = (('ChkReplace', u'rehost_replace'), ('ChkExtendAfter', u'extend_after'),
          ('ChkFloors', u'ext_floors'), ('ChkFraming', u'ext_framing'),
          ('ChkRoofs', u'ext_roofs'), ('ChkDims', u'dims'),
          ('ChkSkipExisting', u'skip_existing'), ('ChkExtendPlace', u'extend_place'),
          ('ChkDebug', u'debug'))
_STATE = {'win': None, 'evt': None, 'handler': None, 'view_hooked': False}


def _view_activated(sender, args):
    u"""Revit's ViewActivated (hooked once per engine): light the dimension
    placer only in a floor plan."""
    try:
        w = _STATE.get('win')
        if w is not None:
            ok = hfam_revit.is_floor_plan(args.CurrentActiveView)
            for t in w.fam_tabs():
                t.set_view_ok(ok)
    except Exception:
        pass


def hook_views(uiapp):
    if _STATE.get('view_hooked'):
        return
    try:
        uiapp.ViewActivated += _view_activated
        _STATE['view_hooked'] = True
    except Exception:
        pass


# ================================================================ runner
class FhaHandler(IExternalEventHandler):
    u"""Runs one queued job inside Revit's API context, then hands the result
    back to the window on its dispatcher.  DialogBoxShowing is hooked once and
    switched with a flag (unhooking a bound method is unreliable)."""
    def __init__(self):
        self.job = None
        self.owner = None
        self.settings = {}
        self.log = None
        self.started = False
        self.suppress = False
        self.hooked = False
        self.quiet = False

    def GetName(self):
        return u'Hanger Automation'

    def _dialog(self, sender, args):
        if not self.suppress:
            return
        try:
            if self.log is not None:
                self.log.add(u'dialog suppressed: {0}'.format(args.DialogId))
            args.OverrideResult(1)
        except Exception:
            pass

    def Execute(self, uiapp):
        self.started = True
        job, owner, quiet = self.job, self.owner, self.quiet
        self.job = None
        res, err = None, None
        log = core.DebugLog(core.as_bool(self.settings, u'debug'))
        if not quiet:
            self.log = log
        try:
            if not self.hooked:
                try:
                    uiapp.DialogBoxShowing += self._dialog
                    self.hooked = True
                except Exception:
                    pass
            self.suppress = True
            log.add(u'Hanger Automation {0}, Revit {1}, egg: {2}'.format(
                core.__version__, getattr(uiapp.Application, 'VersionNumber', u'?'),
                getattr(owner, 'egg_route', u'?')))
            if job is None:
                err = u'No job was queued.'
            else:
                if not quiet:
                    rv.CURRENT_LOG[0] = log
                res = job(uiapp.ActiveUIDocument, self.settings, log)
        except Exception:
            err = traceback.format_exc()
            log.add(err)
        finally:
            self.suppress = False
            if not quiet:
                rv.CURRENT_LOG[0] = None
        if not quiet:
            log.write()
        if owner is not None:
            try:
                owner.win.Dispatcher.BeginInvoke(Action(lambda: owner.finished(res, err)))
            except Exception:
                owner.finished(res, err)


# ================================================================ window
class FhaWindow(object):
    def __init__(self, uiapp):
        self.uiapp = uiapp
        self.win = ui.load_window()
        self.chrome = ui.Chrome(self.win)
        self.drawer = None
        self.settings = core.load_settings()
        self.mode = self.settings.get(u'theme', u'auto')
        if self.mode not in core.THEME_MODES:
            self.mode = u'auto'
        self.busy = False
        self.last_debug = u''
        self.timer = None
        self.theme_name = u'dark'
        self.egg_route = u''
        self.quiet_cb = None
        self.pending = None
        self.fold_content = None
        self.tab = u'fab'
        doc = None
        try:
            doc = uiapp.ActiveUIDocument.Document
        except Exception:
            pass
        self.worksets = [n for n, _i in rv.user_worksets(doc)] if doc is not None else []
        self.ws_values = []
        self.dim_ui = hview_ui.DimViewsUI(self)   # prompts and the Dimension views picker, for the jobs
        self.fam = hfam_ui.FamTab(self, doc)
        self.flr = hfam_ui.FamTab(self, doc, u'floor', self.fam.items)
        self._fill_lists()
        self._load_controls()
        for t in self.fam_tabs():
            t.load(self.settings)
        self.drawer = ui.Drawer(self.win, self.chrome, self.c('HeaderBar'), self.c('ShrinkBtn'), self.c('ShrinkIcon'),
                                self.c('ExpandIcon'), body=self._body_parts, show_body=self._show_body,
                                grips=self.c('GripLayer'))
        self._wire()
        for tab in self.fam_tabs():
            tab.wire()
            tab.open_doc = None   # from here on previews go through the ExternalEvent
        self._show_tab(self.settings.get(u'active_tab', u'fab'))
        ui.set_icon(self.win)
        self.chrome.add_grips(self.c('GripLayer'))
        ui.own_window(self.win, uiapp)
        self.egg_route = ui.attach_egg(self.win, self.c('Logo'), theme=self._theme_name)
        self.c('VerTxt').Text = u'v{0}'.format(core.__version__)
        self._theme()

    def c(self, name):
        return self.win.FindName(name)

    # ---- population
    def _fill_lists(self):
        labels, dims = [], []
        try:
            doc = self.uiapp.ActiveUIDocument.Document
            labels = [b[0] for b in rv.hanger_buttons(doc)]
            dims = [d[0] for d in rv.linear_dimension_types(doc)]
        except Exception:
            pass
        cb = self.c('CmbButton')
        cb.Items.Add(u'(automatic - matches the duct size)')
        for n in labels:
            cb.Items.Add(n)
        cd = self.c('CmbDimType')
        cd.Items.Add(u'(default dimension type)')
        for n in dims:
            cd.Items.Add(n)
        cs = self.c('CmbScope')
        cs.Items.Add(u'Selected run only')
        cs.Items.Add(u'Whole connected system')
        self.n_buttons = len(labels)

    def _load_controls(self):
        s = self.settings
        for name, key in CHECKS:
            self.c(name).IsChecked = core.as_bool(s, key)
        self.c('TxtRadius').Text = s.get(u'search_radius', u'1500')
        self.c('TxtSpacing').Text = s.get(u'spacing', u'2000')
        self._select(self.c('CmbButton'), s.get(u'button', u''))
        self._select(self.c('CmbDimType'), s.get(u'dim_type', u''))
        self.c('CmbScope').SelectedIndex = 1 if s.get(u'scope', u'run') == u'system' else 0
        self.ws_values = ui.fill_workset_combo(self.c('CmbWorkset'), self.worksets, s.get(u'workset', u''))
        if self.n_buttons == 0:
            self.c('StatusTxt').Text = u'No hanger buttons found in the loaded fabrication services'

    @staticmethod
    def _select(combo, value):
        for i in range(combo.Items.Count):
            if value and combo.Items[i] == value:
                combo.SelectedIndex = i
                return
        combo.SelectedIndex = 0

    def _gather(self):
        s = dict(self.settings)
        for name, key in CHECKS:
            s[key] = u'1' if self.c(name).IsChecked else u'0'
        s[u'search_radius'] = num_text(core.parse_mm(self.c('TxtRadius').Text, 1500.0))
        s[u'spacing'] = num_text(max(100.0, core.parse_mm(self.c('TxtSpacing').Text, 2000.0)))
        cb = self.c('CmbButton')
        s[u'button'] = u'' if cb.SelectedIndex <= 0 else u'{0}'.format(cb.SelectedItem)
        cd = self.c('CmbDimType')
        s[u'dim_type'] = u'' if cd.SelectedIndex <= 0 else u'{0}'.format(cd.SelectedItem)
        s[u'scope'] = u'system' if self.c('CmbScope').SelectedIndex == 1 else u'run'
        if self.ws_values:
            s[u'workset'] = core.workset_value(self.ws_values, self.c('CmbWorkset').SelectedIndex)
        s[u'theme'] = self.mode
        s[u'active_tab'] = self.tab
        for t in self.fam_tabs():
            t.gather(s)
        return s

    def fam_tabs(self):
        u"""The family tabs (Family Hangers, Family Floor Support)."""
        return [t for t in (getattr(self, 'fam', None), getattr(self, 'flr', None)) if t is not None]

    def family_settings_saved(self, by):
        u"""One tab saved a family's settings: the other re-reads the file."""
        for t in self.fam_tabs():
            if t is not by:
                t.reload_families()

    def _save(self):
        try:
            self.settings = self._gather()
            core.save_settings(self.settings)
        except Exception:
            pass

    # ---- theme
    def _theme_name(self):
        return self.theme_name

    def _theme(self):
        name = ui.apply_palette(self.win, self.mode)
        self.theme_name = name
        label = {u'auto': u'Auto ({0})'.format(name), u'dark': u'Dark', u'light': u'Light'}[self.mode]
        self.c('ThemeBtn').Content = label

    def _cycle_theme(self, sender, e):
        try:
            self.mode = core.next_mode(self.mode)
            self._theme()
            self._save()
        except Exception:
            pass

    # ---- wiring (every handler guards itself: WPF swallows exceptions)
    def _wire(self):
        self.c('HeaderBar').MouseLeftButtonDown += self._header_down
        self.c('ThemeBtn').Click += self._cycle_theme
        self.c('FullBtn').Click += self._full_click
        self.c('ShrinkBtn').Click += self._shrink_click
        self.c('CloseBtn').Click += self._close_click
        self.c('BtnClose').Click += self._close_click
        self.c('BtnCopyDebug').Click += self._copy_debug
        self.c('BtnRehost').Click += self._rehost_click
        self.c('BtnExtend').Click += self._extend_click
        self.c('BtnPlace').Click += self._place_click
        self.c('TabFab').Click += self._tab_fab_click
        self.c('TabFam').Click += self._tab_fam_click
        self.c('TabFloor').Click += self._tab_floor_click
        self.win.KeyDown += self._key
        self.win.ContentRendered += self.fit
        self.win.Closed += self._closed

    # ---- tabs
    def _show_tab(self, name):
        self.tab = name if name in TABS else u'fab'
        self._apply_tab()
        self.fit()

    def _apply_tab(self):
        for key, (tab, panel) in TABS.items():
            on = key == self.tab
            self.c(panel).Visibility = Visibility.Visible if on else Visibility.Collapsed
            ui.set_style(self.c(tab), 'TabActive' if on else 'Tab')

    # ---- shrink to the taskbar (drawer)
    def _body_parts(self):
        u"""Everything below the title bar, collapsed while shrunk."""
        names = ['TabsBar', 'LogBox', 'FooterBar'] + [p for _t, p in TABS.values()]
        return [self.c(n) for n in names]

    def _show_body(self):
        for n in ('TabsBar', 'LogBox', 'FooterBar'):
            self.c(n).Visibility = Visibility.Visible
        self._apply_tab()

    def _shrink_click(self, sender, e):
        self.drawer.toggle()

    def resize_for_fold(self, delta):
        u"""A tool is opening or folding by `delta`: slide the window with it so its
        bottom stays at the lowest tool - never taller than the screen allows
        (the tab scrolls then), never shorter than the minimum."""
        try:
            win = self.win
            sc = self.c(TABS.get(self.tab, TABS[u'fam'])[1])
            if self.chrome.full or float(win.ActualHeight) <= 0 or self.drawer.shrunk or self.drawer.moving:
                return
            now = self.fold_content if self.fold_content is not None else float(sc.Content.ActualHeight)
            self.fold_content = now + delta
            have = float(sc.ViewportHeight) or float(sc.ActualHeight)
            _l, wa_top, _w, wa_h = self.chrome.work_area()
            h, top = core.fit_height(float(win.ActualHeight), have, self.fold_content, float(win.MinHeight),
                                     float(win.Top), float(wa_top), float(wa_h) * ui.MAX_SCREEN)
            if abs(top - float(win.Top)) > 0.5:
                win.Top = top
            ui.animate_height(win, h, self._fold_resized)
        except Exception:
            self.fold_content = None

    def _fold_resized(self):
        self.fold_content = None

    def fit(self, sender=None, e=None, grow_only=False):
        u"""Grow or shrink the window to show every tool on the open tab."""
        if self.drawer is not None and (self.drawer.shrunk or self.drawer.moving):
            return
        self.chrome.fit_to(self.c(TABS.get(self.tab, TABS[u'fab'])[1]), grow_only)

    def _tab_fab_click(self, sender, e):
        self._show_tab(u'fab')

    def _tab_fam_click(self, sender, e):
        self._show_tab(u'fam')

    def _tab_floor_click(self, sender, e):
        self._show_tab(u'floor')

    def status(self, text):
        try:
            self.c('StatusTxt').Text = text
        except Exception:
            pass

    def _header_down(self, sender, e):
        if self.drawer.shrunk:
            try:
                if e.ClickCount == 2:
                    self.drawer.expand()   # double-click the floating bar opens it again
                    return
            except Exception:
                pass
            if self.busy:
                return   # no DragMove (a modal loop) while a job holds Revit's API context
        self.chrome.header_down(e, self.c('Logo'))

    def _full_click(self, sender, e):
        if self.drawer.shrunk:
            self.drawer.expand()
            return
        self.chrome.toggle_full()

    def _close_click(self, sender, e):
        self.close()

    def _rehost_click(self, sender, e):
        self.start('rehost')

    def _extend_click(self, sender, e):
        self.start('extend')

    def _place_click(self, sender, e):
        self.start('place')

    def _key(self, sender, e):
        try:
            if self.drawer.key(e):   # Ctrl+Shift+H; Esc / Enter / F11 open a parked window
                e.Handled = True
                return
            k = str(e.Key)
            if k == 'F11':
                self.chrome.toggle_full()
            # Escape never closes the tool: it is pressed to leave Revit picks
        except Exception:
            pass

    def close(self):
        self._save()
        try:
            self.win.Close()
        except Exception:
            pass

    def _closed(self, sender, e):
        _STATE['win'] = None
        self._stop_timer()

    def _copy_debug(self, sender, e):
        try:
            text = u'Hanger Automation {0}\n\n{1}\n\nSettings:\n{2}\n\nFamily tabs:\n{3}'.format(
                core.__version__, self.last_debug or u'(nothing run yet)',
                u'\n'.join(u'{0}={1}'.format(k, v) for k, v in sorted(self._gather().items())),
                u'\n\n'.join(t.debug_text() for t in self.fam_tabs()))
            Clipboard.SetText(text)
            self.c('StatusTxt').Text = u'Debug copied to the clipboard'
        except Exception:
            pass

    # ---- running a job
    def _set_busy(self, busy, status):
        self.busy = busy
        for n in JOB_BUTTONS:
            self.c(n).IsEnabled = not busy
        for t in self.fam_tabs():
            t.set_busy(busy)
        self.c('StatusTxt').Text = status

    def start(self, kind):
        jobs = {'rehost': rv.job_rehost, 'extend': rv.job_extend, 'place': rv.job_place}
        self.start_job(jobs[kind], self.job_extra)

    def job_extra(self, s):
        s[u'_ui'] = self.dim_ui

    def _queue(self, job, settings, quiet, status):
        h = _STATE['handler']
        h.owner = self
        h.settings = settings
        h.job = job
        h.quiet = quiet
        h.started = False
        self._set_busy(True, status)
        answer = str(_STATE['evt'].Raise())
        if answer in ('Accepted', 'Pending'):
            self._start_timer()
            return True
        h.job = None
        self.quiet_cb = None
        self._set_busy(False, u'Revit refused the request ({0}) - try again'.format(answer))
        return False

    def start_job(self, job, extra=None):
        u"""A tool: picks, writes, results box, debug file."""
        try:
            if self.busy:
                if self.quiet_cb is not None:
                    self.pending = (job, extra)   # a quick read is in flight: run straight after it
                    self.status(u'Starting as soon as Revit has finished reading...')
                    return True
                self.status(u'Still working on the last request...')
                return False
            self._save()
            settings = dict(self.settings)
            if extra is not None:
                extra(settings)
            self.quiet_cb = None
            return self._queue(job, settings, False, u'Working... pick in the model if asked (Esc cancels the pick)')
        except Exception:
            self._set_busy(False, u'Could not start - see Copy debug')
            self.last_debug = traceback.format_exc()
            return False

    def start_quiet(self, job, callback, status=u'Reading...'):
        u"""A read: the answer goes to callback(result, error).  False if busy."""
        try:
            if self.busy:
                return False
            self.quiet_cb = callback
            return self._queue(job, dict(self.settings), True, status)
        except Exception:
            self.quiet_cb = None
            self._set_busy(False, u'Ready')
            return False

    def _start_timer(self):
        self._stop_timer()
        try:
            self.timer = DispatcherTimer()
            self.timer.Interval = TimeSpan.FromSeconds(WATCHDOG_SECONDS)
            self.timer.Tick += self._watchdog
            self.timer.Start()
        except Exception:
            self.timer = None

    def _stop_timer(self):
        try:
            if self.timer is not None:
                self.timer.Stop()
        except Exception:
            pass
        self.timer = None

    def _watchdog(self, sender, e):
        u"""Frees the window if Revit never started the job (it was busy)."""
        self._stop_timer()
        h = _STATE['handler']
        if self.busy and h is not None and not h.started:
            h.job = None
            self.quiet_cb = None
            self.pending = None
            self._set_busy(False, u'Revit was busy and did not run it - click again')

    def finished(self, res, err):
        self._stop_timer()
        if self.quiet_cb is not None:
            cb, self.quiet_cb = self.quiet_cb, None
            self._set_busy(False, u'Ready')
            try:
                cb(res, err)
            except Exception:
                self.last_debug = traceback.format_exc()
            if self.pending is not None and not self.busy:
                job, extra = self.pending
                self.pending = None
                self.start_job(job, extra)
            for t in self.fam_tabs():   # a tab whose preview read could not start gets its turn now
                if not self.busy:
                    t.retry_preview()
            return
        h = _STATE['handler']
        if h is not None and h.log is not None:
            self.last_debug = h.log.text()
        lines = []
        if err:
            lines.append(u'Something went wrong - press Copy debug and send it over.')
            lines.append(u'{0}'.format(err))
            status = u'Failed - see the results box'
        elif res is not None:
            lines.append(u'{0}: {1} done, {2} skipped, {3} failed'.format(
                res['title'], res['done'], res['skipped'], res['failed']))
            lines.extend(res['lines'])
            status = u'{0}: {1} done'.format(res['title'], res['done'])
        else:
            status = u'Ready'
        try:
            self.c('LogBox').Text = u'\n'.join(lines)
            self._set_busy(False, status)
            self.win.Activate()
        except Exception:
            pass


def num_text(v):
    return u'{0:g}'.format(v)


# ================================================================= entry
def show(uiapp):
    u"""Open the window, or bring the open one forward."""
    w = ui.parked()
    if w is not None:
        try:
            w.Activate()
            return None
        except Exception:
            pass
    if _STATE['handler'] is None:
        _STATE['handler'] = FhaHandler()
        _STATE['evt'] = ExternalEvent.Create(_STATE['handler'])
    fw = FhaWindow(uiapp)
    _STATE['win'] = fw
    hook_views(uiapp)
    ui.park(fw.win)
    fw.win.Show()
    return fw
