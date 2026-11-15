# -*- coding: utf-8 -*-
"""Unhide in View - the window and the ExternalEvent runner.

Modeless and owned by Revit's main window, so Revit stays usable. Every
read and write goes out through one ExternalEvent; nothing here waits for
it (Revit raises it on this same thread - waiting would deadlock). Results
come back as callbacks marshalled onto the window's dispatcher.
"""
import uiv_clr  # noqa: F401  - assembly references first, always

import os
import time
import traceback

import clr
from System import Action, AppDomain, Boolean, Int32, String, TimeSpan
from System.Data import DataTable, DataRowView
from System.Windows import (
    Visibility, GridLength, GridUnitType, HorizontalAlignment, FrameworkElement,
    DataTemplate, FrameworkElementFactory, Clipboard, RoutedEventHandler,
)
from System.Windows.Controls import (
    DataGridTextColumn, DataGridTemplateColumn, DataGridLength,
    DataGridLengthUnitType, DataGridRow, StackPanel, TextBlock, TextBox,
    CheckBox, Button, Control,
)
from System.Windows.Controls.Primitives import ButtonBase, ToggleButton
from System.Windows.Data import Binding, BindingMode, UpdateSourceTrigger
from System.Windows.Input import Key, Keyboard, ModifierKeys
from System.Windows.Media import VisualTreeHelper, Visual
from System.Windows.Threading import DispatcherTimer
from Autodesk.Revit.UI import (
    IExternalEventHandler, ExternalEvent, TaskDialog, TaskDialogCommonButtons,
)

import uiv_core as core
import uiv_revit as rv
import uiv_ui as ui


# The window, its runner and the ExternalEvent are parked here: a modeless
# window nothing holds on to is collected out from under the user.
_PARKED = {}


# =====================================================================
# ExternalEvent runner
# =====================================================================

class Job(object):
    def __init__(self, name, work, done=None, fail=None, user=True):
        self.name = name
        self.work = work
        self.done = done
        self.fail = fail
        self.user = user


class _Handler(IExternalEventHandler):
    def __init__(self, runner):
        self.runner = runner

    def Execute(self, uiapp):
        try:
            self.runner.execute(uiapp)
        except Exception:
            try:
                self.runner.log.add(u'Runner failed: ' + traceback.format_exc())
            except Exception:
                pass

    def GetName(self):
        return 'RevoBIM Unhide in View'


class Runner(object):
    """Queue, raise, return. A 'Pending' answer means an earlier request is
    still waiting - the new job queues behind it and the queue is never
    cleared. Only a refused job is removed, and it is told so."""

    WATCHDOG_S = 20.0

    def __init__(self, log):
        self.log = log
        self.queue = []
        self.event = None
        self.handler = None
        self.direct_uiapp = None      # modal fallback: run at once
        self.raised_at = None
        self.dispatcher = None

    def create_event(self):
        self.handler = _Handler(self)
        self.event = ExternalEvent.Create(self.handler)

    def submit(self, job):
        self.queue.append(job)
        if self.direct_uiapp is not None:
            self.execute(self.direct_uiapp)
            return True
        if self.raised_at is not None:
            self.log.add(u'Queued behind a pending request: ' + job.name)
            return True
        return self._raise(job)

    def _raise(self, job=None):
        try:
            status = str(self.event.Raise())
        except Exception:
            status = 'Error ' + traceback.format_exc()
        if status in ('Accepted', 'Pending'):
            self.raised_at = time.time()
            return True
        self.log.add(u'ExternalEvent.Raise() answered ' + core.to_text(status))
        if job is not None and job in self.queue:
            self.queue.remove(job)
            self._post(job.fail, u'Revit did not take the request ({0}). Try again.'.format(status))
        return False

    def execute(self, uiapp):
        self.raised_at = None
        jobs = self.queue
        self.queue = []
        for job in jobs:
            try:
                payload = job.work(uiapp)
            except Exception:
                self._post(job.fail, traceback.format_exc())
                continue
            self._post(job.done, payload)
        if self.queue and self.direct_uiapp is None:
            self._raise()

    def watchdog(self):
        if self.raised_at is None or self.direct_uiapp is not None:
            return False
        if time.time() - self.raised_at < self.WATCHDOG_S:
            return False
        self.log.add(u'Revit has not run the request after {0:.0f}s - asking again'.format(
            time.time() - self.raised_at))
        self.raised_at = None
        if self.queue:
            self._raise()
        return True

    def _post(self, fn, arg):
        if fn is None:
            return
        log = self.log

        def call():
            try:
                fn(arg)
            except Exception:
                log.add(u'Callback failed: ' + traceback.format_exc())
        if self.dispatcher is not None:
            self.dispatcher.BeginInvoke(Action(call))
        else:
            call()


# =====================================================================
# Small WPF helpers
# =====================================================================

def _clr(t):
    return clr.GetClrType(t)


def _ancestor(element, kinds):
    """Walk up the visual tree to the first element of one of these types."""
    el = element
    for _ in range(60):
        if el is None:
            return None
        for k in kinds:
            if isinstance(el, k):
                return el
        try:
            if isinstance(el, Visual):
                el = VisualTreeHelper.GetParent(el)
            else:
                el = getattr(el, 'Parent', None)
        except Exception:
            return None
    return None


def _is_within(element, targets):
    el = element
    for _ in range(60):
        if el is None:
            return False
        for t in targets:
            if el is t:
                return True
        try:
            if isinstance(el, Visual):
                el = VisualTreeHelper.GetParent(el)
            else:
                el = getattr(el, 'Parent', None)
        except Exception:
            return False
    return False


def _timer(ms, fn):
    t = DispatcherTimer()
    t.Interval = TimeSpan.FromMilliseconds(ms)

    def tick(sender, e):
        sender.Stop()
        fn()
    t.Tick += tick
    return t


def _restart(timer):
    timer.Stop()
    timer.Start()


# =====================================================================
# The window
# =====================================================================

class UnhideWindow(object):

    NAMES = [
        'RootGrid', 'Frame', 'HeaderBar', 'Logo', 'ToolTitle', 'ThemeChip',
        'ThemeText', 'VersionText', 'ShrinkBtn', 'FullScreenBtn', 'CloseBtn', 'DebugChk',
        'CopyDebugBtn', 'UnhideBtn', 'UnhideText', 'StatusText', 'BodyGrid',
        'LeftCol', 'RightCol', 'ElemRow', 'CatRow', 'FocusViewText',
        'ElemCountText', 'CurrentViewBtn', 'ElemGrid', 'ElemEmptyText',
        'ChangeTemplatesChk', 'CatSearch', 'CatTargetText', 'CatGrid',
        'CatEmptyText', 'RefreshBtn', 'ViewCountText', 'ViewSearch',
        'OnlyHiddenToggle', 'OnlyHiddenText', 'ScanBar', 'ScanText',
        'ViewGrid', 'ViewEmptyText', 'UnhideViewsBtn', 'UnhideViewsText',
        'TickedText', 'ConfirmOverlay', 'ConfirmTitle', 'ConfirmText',
        'ConfirmNoBtn', 'ConfirmYesBtn', 'ConfirmYesText', 'GripLayer',
        'FooterBar',
    ]

    ELEM_FILTER_COLS = ['id_txt', 'category', 'ftype', 'level', 'note']

    def __init__(self, uiapp, runner, settings, log, modal=False):
        # ---- every attribute set before anything is called ----------------
        self.uiapp = uiapp
        self.runner = runner
        self.settings = settings
        self.log = log
        self.modal = modal
        self.version = core.__version__
        self.here = os.path.dirname(os.path.abspath(__file__))
        self.closed = False
        self.close_ok = False
        self.armed = False
        self.proved = False
        self.started = False
        self.loading = False
        self.doc = None
        self.views = []
        self.view_by_key = {}
        self.cats = []
        self.cat_names = {}
        self.cat_ids = {}
        self.scanner = None
        self.scan_in_flight = False
        self.scan_started = 0.0
        self.hidden = {}
        self.cat_state = {}
        self.cat_job_pending = False
        self.cat_job_again = False
        self.focus_key = None
        self.staging = core.Staging()
        self.elem_notes = {}
        self.cat_notes = {}
        self.elem_filters = {}
        self.view_rows = {}
        self.elem_rows = {}
        self.cat_rows = {}
        self.user_jobs = 0
        self.busy_since = 0.0
        self.suspend = False
        self.current_theme = 'dark'
        self.confirm_action = None
        self.elem_all = None
        self.view_all = None
        self.cat_all = None
        self.view_table = None
        self.elem_table = None
        self.cat_table = None

        # ---- the window ---------------------------------------------------------
        self.win = ui.load_window(os.path.join(self.here, 'UnhideInView.xaml'),
                                  os.path.join(self.here, 'Theme.xaml'))
        self.c = ui.find(self.win, self.NAMES)
        self.runner.dispatcher = self.win.Dispatcher
        self.fullscreen = ui.FullScreen(self.win)
        # shrink to taskbar: the header bar stays, the rest slides away
        self.drawer = ui.WindowDrawer(self.win, self.c['HeaderBar'], self.c['RootGrid'],
                                      self.c['ShrinkBtn'], self.c['GripLayer'], log=self.log)

        self.view_timer = _timer(220, self._refilter_views)
        self.elem_timer = _timer(220, self._refilter_elems)
        self.cat_timer = _timer(220, self._refilter_cats)
        self.scan_timer = _timer(25, self._pump_scan)
        self.watch_timer = DispatcherTimer()
        self.watch_timer.Interval = TimeSpan.FromSeconds(2)

        self._build_tables()
        self._apply_settings()
        self._wire()
        self.apply_theme()
        self._chrome()
        self.refresh_buttons()

    # =================================================================
    # Building
    # =================================================================

    def _table(self, cols):
        t = DataTable()
        for name, typ in cols:
            t.Columns.Add(name, _clr(typ))
        t.DefaultView.RowFilter = "vis = '1'"
        return t

    def _build_tables(self):
        common = [('key', String), ('tick', Boolean), ('note', String),
                  ('warn', String), ('bad', String), ('hot', String), ('vis', String)]
        self.view_table = self._table(common + [
            ('name', String), ('nkey', String), ('vtype', String),
            ('cnt', Int32), ('cnt_txt', String)])
        self.elem_table = self._table(common + [
            ('id_txt', String), ('nid', String), ('category', String),
            ('ftype', String), ('level', String)])
        self.cat_table = self._table(common + [
            ('name', String), ('nkey', String), ('hidden_txt', String),
            ('hidden_n', Int32)])

        # ---- views -------------------------------------------------------------
        g = self.c['ViewGrid']
        col, self.view_all = self._tick_col(self._on_view_all)
        g.Columns.Add(col)
        g.Columns.Add(self._text_col(u'View', 'name', 160, 3.0, 'nkey'))
        g.Columns.Add(self._text_col(u'Type', 'vtype', 80, 1.0))
        g.Columns.Add(self._styled_col(u'Hidden', 'cnt_txt', 'RbCountText', 64, 0.7, 'cnt'))
        g.ItemsSource = self.view_table.DefaultView

        # ---- hidden elements -------------------------------------------------
        g = self.c['ElemGrid']
        col, self.elem_all = self._tick_col(self._on_elem_all)
        g.Columns.Add(col)
        g.Columns.Add(self._text_col(self._head(u'Element ID', 'id_txt'), 'id_txt', 86, 0.8, 'nid'))
        g.Columns.Add(self._text_col(self._head(u'Category', 'category'), 'category', 110, 1.3))
        g.Columns.Add(self._text_col(self._head(u'Family : Type', 'ftype'), 'ftype', 150, 2.4))
        g.Columns.Add(self._text_col(self._head(u'Level', 'level'), 'level', 80, 1.0))
        g.Columns.Add(self._styled_col(self._head(u'Note', 'note'), 'note', 'RbNoteText', 110, 1.4))
        g.ItemsSource = self.elem_table.DefaultView

        # ---- hidden categories ------------------------------------------------
        g = self.c['CatGrid']
        col, self.cat_all = self._tick_col(self._on_cat_all)
        g.Columns.Add(col)
        g.Columns.Add(self._text_col(u'Category', 'name', 160, 2.6, 'nkey'))
        g.Columns.Add(self._styled_col(u'Hidden in', 'hidden_txt', 'RbCountText', 70, 0.7, 'hidden_n'))
        g.Columns.Add(self._styled_col(u'Note', 'note', 'RbNoteText', 120, 1.8))
        g.ItemsSource = self.cat_table.DefaultView

    def _width(self, col, min_w, star):
        col.MinWidth = min_w
        col.Width = DataGridLength(star, DataGridLengthUnitType.Star)

    def _text_col(self, header, path, min_w, star, sort_path=None):
        col = DataGridTextColumn()
        col.Header = header
        col.Binding = Binding(path)
        col.IsReadOnly = True
        col.SortMemberPath = sort_path or path
        self._width(col, min_w, star)
        style = self.win.TryFindResource('RbCellText')
        if style is not None:
            col.ElementStyle = style
        return col

    def _styled_col(self, header, path, style_key, min_w, star, sort_path=None):
        f = FrameworkElementFactory(TextBlock)
        f.SetBinding(TextBlock.TextProperty, Binding(path))
        f.SetResourceReference(FrameworkElement.StyleProperty, style_key)
        dt = DataTemplate()
        dt.VisualTree = f
        col = DataGridTemplateColumn()
        col.CellTemplate = dt
        col.Header = header
        col.SortMemberPath = sort_path or path
        col.CanUserSort = True
        self._width(col, min_w, star)
        return col

    def _tick_col(self, on_all):
        f = FrameworkElementFactory(CheckBox)
        b = Binding('tick')
        b.Mode = BindingMode.TwoWay
        b.UpdateSourceTrigger = UpdateSourceTrigger.PropertyChanged
        f.SetBinding(ToggleButton.IsCheckedProperty, b)
        f.SetResourceReference(FrameworkElement.StyleProperty, 'RbCheck')
        f.SetValue(FrameworkElement.HorizontalAlignmentProperty, HorizontalAlignment.Center)
        dt = DataTemplate()
        dt.VisualTree = f
        col = DataGridTemplateColumn()
        col.CellTemplate = dt
        hdr = CheckBox()
        hdr.SetResourceReference(FrameworkElement.StyleProperty, 'RbCheck')
        hdr.ToolTip = u'Tick or untick every row shown'
        hdr.Click += self._h(on_all)
        col.Header = hdr
        col.Width = DataGridLength(36)
        col.CanUserSort = False
        col.CanUserResize = False
        return col, hdr

    def _head(self, title, key):
        """A live heading: the name with a keyword box under it. Typing in
        the box never sorts - the TextBox takes the mouse."""
        sp = StackPanel()
        tb = TextBlock()
        tb.Text = title
        tb.SetResourceReference(FrameworkElement.StyleProperty, 'RbHeadText')
        box = TextBox()
        box.Tag = u'filter'
        box.SetResourceReference(FrameworkElement.StyleProperty, 'RbHeadSearch')
        box.TextChanged += self._h(self._filter_handler(key))
        sp.Children.Add(tb)
        sp.Children.Add(box)
        return sp

    def _filter_handler(self, key):
        def handler(sender, e):
            self.elem_filters[key] = core.to_text(sender.Text)
            _restart(self.elem_timer)
        return handler

    def _apply_settings(self):
        s = self.settings
        w = self.win
        w.Width = core.as_float(s.get('width'), 1320, w.MinWidth, 4000)
        w.Height = core.as_float(s.get('height'), 800, w.MinHeight, 3000)
        split = core.as_float(s.get('split'), 0.56, 0.2, 0.8)
        self.c['LeftCol'].Width = GridLength(split, GridUnitType.Star)
        self.c['RightCol'].Width = GridLength(1.0 - split, GridUnitType.Star)
        cs = core.as_float(s.get('cat_split'), 0.34, 0.12, 0.8)
        self.c['ElemRow'].Height = GridLength(1.0 - cs, GridUnitType.Star)
        self.c['CatRow'].Height = GridLength(cs, GridUnitType.Star)
        self.c['DebugChk'].IsChecked = core.as_bool(s.get('debug'))
        self.c['OnlyHiddenToggle'].IsChecked = core.as_bool(s.get('only_hidden'))
        self.c['ChangeTemplatesChk'].IsChecked = core.as_bool(s.get('change_templates'))
        self.c['VersionText'].Text = u'v' + self.version

    def _wire(self):
        c = self.c
        h = self._h
        c['CloseBtn'].Click += h(lambda s, e: self.request_close())
        c['ShrinkBtn'].Click += h(lambda s, e: self.drawer.toggle())
        c['FullScreenBtn'].Click += h(self._on_full_screen)
        c['ThemeChip'].Click += h(self._on_theme_chip)
        c['HeaderBar'].MouseLeftButtonDown += h(self._on_header_down)
        c['CopyDebugBtn'].Click += h(self._on_copy_debug)
        c['DebugChk'].Click += h(self._on_debug)
        c['UnhideBtn'].Click += h(self._on_unhide)
        c['UnhideViewsBtn'].Click += h(self._on_unhide_views)
        c['CurrentViewBtn'].Click += h(self._on_current_view)
        c['RefreshBtn'].Click += h(lambda s, e: self.load())
        c['ViewSearch'].TextChanged += h(lambda s, e: _restart(self.view_timer))
        c['CatSearch'].TextChanged += h(lambda s, e: _restart(self.cat_timer))
        c['OnlyHiddenToggle'].Click += h(self._on_only_hidden)
        c['ChangeTemplatesChk'].Click += h(self._on_change_templates)
        c['ConfirmNoBtn'].Click += h(lambda s, e: self._hide_confirm())
        c['ConfirmYesBtn'].Click += h(self._on_confirm_yes)

        for name, which in (('ViewGrid', 'view'), ('ElemGrid', 'elem'), ('CatGrid', 'cat')):
            g = c[name]
            g.AddHandler(ButtonBase.ClickEvent, RoutedEventHandler(h(self._tick_handler(which))))
        c['ViewGrid'].SelectionChanged += h(self._on_view_selected)
        c['ElemGrid'].SelectionChanged += h(lambda s, e: self.refresh_buttons())
        c['ViewGrid'].MouseDoubleClick += h(self._on_view_double)
        c['ElemGrid'].MouseDoubleClick += h(self._on_elem_double)

        self.win.PreviewKeyDown += h(self._on_key)
        self.win.Activated += self._on_activated
        self.win.ContentRendered += h(self._on_rendered)
        self.win.Closing += self._on_closing
        self.win.Closed += self._on_closed
        self.watch_timer.Tick += h(self._on_watchdog)

    def _chrome(self):
        try:
            bmp = ui.load_bitmap(os.path.join(self.here, 'icon.png'))
            if bmp is not None:
                self.c['Logo'].Source = bmp
        except Exception:
            pass
        try:
            ui.add_resize_grips(self.win, self.c['GripLayer'], self.fullscreen.forget)
        except Exception:
            pass
        try:
            ui.attach_egg(self.win, self.c['Logo'], lambda: self.current_theme, self.log)
        except Exception:
            pass

    # =================================================================
    # Handlers are guarded: a WPF event swallows exceptions silently
    # =================================================================

    def _h(self, fn):
        def handler(sender, e):
            try:
                self._prove_alive()
                fn(sender, e)
            except Exception:
                self.log.add(u'Handler error: ' + traceback.format_exc())
                self.set_status(u'Something went wrong - tick Debug, Copy debug and send it over.',
                                'bad')
        return handler

    def arm(self):
        """Called by launch() after the open-note is written, right before
        Show(). Nothing earlier may count as proof the engine is alive."""
        self.armed = True

    def _prove_alive(self):
        if not self.armed or self.proved:
            return
        self.proved = True
        try:
            p = core.settings_path(core.OPEN_NOTE_FILE)
            if os.path.exists(p):
                os.remove(p)
        except Exception:
            pass

    # =================================================================
    # Status, theme, chrome
    # =================================================================

    def set_status(self, text, kind='muted'):
        st = self.c['StatusText']
        st.Text = core.to_text(text)
        key = {'bad': 'Red', 'good': 'Green', 'warn': 'Orange'}.get(kind, 'Muted')
        st.SetResourceReference(TextBlock.ForegroundProperty, key)

    def apply_theme(self):
        mode = core.normalise_theme(self.settings.get('theme'))
        canvas = None
        if mode == 'follow':
            canvas = ui.canvas_theme(self.uiapp)
        name = core.resolve_theme(mode, canvas)
        self.current_theme = name
        ui.apply_palette(self.win, name)
        label = core.THEME_LABEL.get(mode, u'Auto')
        if mode == 'follow':
            label = u'Auto'
        self.c['ThemeText'].Text = label
        self.c['ThemeChip'].ToolTip = (
            u'Theme: {0} ({1}). Click for {2}.'.format(
                label, name, core.THEME_LABEL[core.next_theme(mode)]))

    def _on_theme_chip(self, sender, e):
        self.settings['theme'] = core.next_theme(self.settings.get('theme'))
        core.save_settings(self.settings)
        self.apply_theme()
        self.log.add(u'Theme -> ' + self.settings['theme'] + u' (' + self.current_theme + u')')

    def _on_activated(self, sender, e):
        try:
            self._prove_alive()
            if core.normalise_theme(self.settings.get('theme')) == 'follow':
                self.apply_theme()
        except Exception:
            pass

    def _on_full_screen(self, sender, e):
        # while shrunk, full screen means 'give me the window back'
        if not self.drawer.is_open():
            self.drawer.expand()
            return
        self.fullscreen.toggle()

    def _on_header_down(self, sender, e):
        src = e.OriginalSource
        if _is_within(src, [self.c['Logo']]) or _ancestor(src, [Button, ToggleButton]) is not None:
            return
        if self.drawer.on_header_down(e):
            return
        if e.ClickCount == 2:
            self.fullscreen.toggle()
            return
        try:
            self.fullscreen.forget()
            self.win.DragMove()
        except Exception:
            pass

    def _on_copy_debug(self, sender, e):
        text = self.log.text(self._debug_header())
        try:
            Clipboard.SetText(text)
            self.set_status(u'Debug copied to the clipboard ({0} lines).'.format(len(self.log.lines)), 'good')
        except Exception:
            self.set_status(u'Could not reach the clipboard - the log is in ' + self.log.path, 'warn')
        self.log.flush(self._debug_header())

    def _debug_header(self):
        lines = [u'RevoBIM Unhide in View v' + self.version]
        try:
            lines.append(u'Revit ' + core.to_text(self.uiapp.Application.VersionNumber) + u' ' +
                         core.to_text(self.uiapp.Application.VersionBuild))
        except Exception:
            pass
        lines.append(u'Theme: ' + core.to_text(self.settings.get('theme')) + u' -> ' + self.current_theme)
        lines.append(u'Modal fallback: ' + (u'yes' if self.modal else u'no'))
        if self.scanner is not None:
            done, total = self.scanner.progress()
            lines.append(u'Scan: {0}/{1} views, {2} checks, {3} errors'.format(
                done, total, self.scanner.checked, self.scanner.errors))
        lines.append(u'Staged: {0} elements in {1} views, {2} categories'.format(
            self.staging.element_total(), self.staging.element_views(),
            len(self.staging.categories)))
        lines.append(u'Settings: ' + u'; '.join(
            u'{0}={1}'.format(k, self.settings.get(k)) for k in sorted(self.settings.keys())))
        lines.append(u'=' * 60)
        return u'\n'.join(lines)

    def _on_debug(self, sender, e):
        on = bool(self.c['DebugChk'].IsChecked)
        self.log.enabled = on
        self.settings['debug'] = '1' if on else '0'
        core.save_settings(self.settings)

    # =================================================================
    # Loading
    # =================================================================

    def _on_rendered(self, sender, e):
        if self.started:
            return
        self.started = True
        self.watch_timer.Start()
        self.load()

    def _submit(self, name, work, done, user=True):
        """Every Revit call goes through here. A user job marks the window
        busy until its callback lands; the watchdog frees it if Revit never
        answers."""
        if user:
            self.user_jobs += 1
            self.busy_since = time.time()
            self.refresh_buttons()

        def finish(payload):
            if user:
                self.user_jobs = max(0, self.user_jobs - 1)
            try:
                done(payload)
            finally:
                if user:
                    self.refresh_buttons()

        def fail(text):
            if user:
                self.user_jobs = max(0, self.user_jobs - 1)
            self.log.add(u'Job "{0}" failed: {1}'.format(name, core.to_text(text)))
            self.set_status(u'{0} did not finish - tick Debug, Copy debug and send it over.'.format(name), 'bad')
            if name == 'Read the model':
                self.loading = False
            if name == 'Scan':
                self.scan_in_flight = False
            if name == 'Categories':
                self.cat_job_pending = False
            self.refresh_buttons()
        self.log.add(u'Job: ' + name)
        return self.runner.submit(Job(name, work, finish, fail, user))

    def load(self):
        if self.loading:
            return
        self.loading = True
        self.set_status(u'Reading the model...')
        self.c['ScanText'].Text = u'Reading views and elements...'
        log = self.log

        def work(uiapp):
            uidoc = uiapp.ActiveUIDocument
            if uidoc is None:
                raise RuntimeError('No model is open in Revit')
            doc = uidoc.Document
            t0 = time.time()
            views = rv.read_views(doc, log)
            cats = rv.all_categories(doc)
            cat_ids = rv.candidate_category_ids(doc)
            scanner = rv.make_scanner(doc, views, cat_ids, log)
            log.add(u'Model read in {0:.2f}s: {1}'.format(time.time() - t0, core.to_text(doc.Title)))
            return {'doc': doc, 'views': views, 'cats': cats, 'scanner': scanner,
                    'active': rv.active_view_key(uidoc), 'title': core.to_text(doc.Title)}
        self._submit('Read the model', work, self._loaded)

    def _loaded(self, data):
        self.loading = False
        ticked = set(self._ticked_views())
        old_focus = self.focus_key
        self.doc = data['doc']
        self.views = data['views']
        self.view_by_key = dict((v['key'], v) for v in self.views)
        self.cats = data['cats']
        self.cat_names = dict((k, n) for k, _c, n, _t, _p in self.cats)
        self.cat_ids = dict((k, c.Id) for k, c, _n, _t, _p in self.cats)
        self.scanner = data['scanner']
        self.hidden = {}
        self.cat_state = {}
        self.elem_notes = {}
        self.cat_notes = {}
        self.scan_started = time.time()

        focus = data.get('active')
        if focus not in self.view_by_key:
            focus = old_focus if old_focus in self.view_by_key else None
        if focus is None and self.views:
            focus = self.views[0]['key']

        self._fill_views(ticked)
        self.set_status(u'{0} - {1} views. Scanning for hidden elements...'.format(
            data.get('title', u''), len(self.views)))
        self._set_focus(focus, select_row=True)
        self.scanner.bump([focus] + [k for k in ticked if k in self.view_by_key])
        self._pump_scan()

    # =================================================================
    # The scan, a slice at a time
    # =================================================================

    def _pump_scan(self):
        if self.closed or self.scanner is None or self.scan_in_flight:
            return
        if self.scanner.finished():
            self._show_scan_progress()
            return
        if not rv.doc_alive(self.doc):
            return
        self.scan_in_flight = True
        budget = core.as_float(self.settings.get('scan_budget_ms'), 120, 20, 1000) / 1000.0
        scanner = self.scanner

        def work(uiapp):
            return scanner, scanner.step(budget)
        self._submit('Scan', work, self._scanned, user=False)

    def _scanned(self, payload):
        self.scan_in_flight = False
        scanner, finished = payload
        if scanner is not self.scanner:
            return                      # a Refresh replaced it
        for vk in finished:
            ids = scanner.results.get(vk) or []
            self.hidden[vk] = dict((rv.eid_value(i), i) for i in ids)
            self.staging.prune_view(vk, set(self.hidden[vk].keys()))
            self._update_view_count(vk)
            if vk == self.focus_key:
                self._request_elem_rows(vk)
        if finished:
            self.refresh_buttons()
        self._show_scan_progress()
        if not scanner.finished():
            _restart(self.scan_timer)

    def _show_scan_progress(self):
        if self.scanner is None:
            return
        done, total = self.scanner.progress()
        bar = self.c['ScanBar']
        bar.Value = (100.0 * done / total) if total else 100.0
        with_hidden = len([k for k, d in self.hidden.items() if d])
        if self.scanner.finished():
            bar.SetResourceReference(Control.ForegroundProperty, 'Green')
            self.c['ScanText'].Text = u'Scanned {0} - {1} with hidden elements ({2:.1f}s)'.format(
                core.plural(total, u'view'), with_hidden, time.time() - self.scan_started)
        else:
            bar.SetResourceReference(Control.ForegroundProperty, 'Blue')
            self.c['ScanText'].Text = u'Scanning views for hidden elements: {0} / {1} - {2} found so far'.format(
                done, total, with_hidden)

    # =================================================================
    # Views list
    # =================================================================

    def _fill_views(self, ticked):
        t = self.view_table
        self.suspend = True
        try:
            t.Rows.Clear()
            self.view_rows = {}
            for v in self.views:
                r = t.NewRow()
                r['key'] = core.to_text(v['key'])
                r['tick'] = v['key'] in ticked
                r['name'] = v['name']
                r['nkey'] = core.natural_key(v['name'])
                r['vtype'] = v['type']
                r['note'] = v.get('template_name') or u''
                r['warn'] = u'0'
                r['bad'] = u'0'
                r['vis'] = u'1'
                self._set_count_cells(r, None)
                t.Rows.Add(r)
                self.view_rows[v['key']] = r
        finally:
            self.suspend = False
        self._refilter_views()

    def _set_count_cells(self, row, n):
        row['cnt'] = n if n is not None else -1
        row['cnt_txt'] = core.count_text(n)
        row['hot'] = u'1' if n else u'0'

    def _update_view_count(self, vk):
        r = self.view_rows.get(vk)
        if r is None:
            return
        n = len(self.hidden[vk]) if vk in self.hidden else None
        self._set_count_cells(r, n)
        self._view_vis(vk, r)

    def _view_vis(self, vk, r):
        v = self.view_by_key.get(vk)
        if v is None:
            return
        n = len(self.hidden[vk]) if vk in self.hidden else None
        ok = core.view_row_visible(v['name'], v['type'], n,
                                   self.c['ViewSearch'].Text,
                                   bool(self.c['OnlyHiddenToggle'].IsChecked))
        want = u'1' if ok else u'0'
        if r['vis'] != want:
            r['vis'] = want

    def _refilter_views(self):
        for vk, r in self.view_rows.items():
            self._view_vis(vk, r)
        shown = self.view_table.DefaultView.Count
        total = len(self.view_rows)
        self.c['ViewCountText'].Text = (
            core.plural(total, u'view') if shown == total
            else u'{0} of {1} views'.format(shown, total))
        empty = u''
        if total and not shown:
            if bool(self.c['OnlyHiddenToggle'].IsChecked) and self.scanner is not None \
                    and not self.scanner.finished():
                empty = u'No views with hidden elements found yet - still scanning.'
            elif bool(self.c['OnlyHiddenToggle'].IsChecked):
                empty = u'No view has elements hidden in it.'
            else:
                empty = u'No views match the search.'
        self.c['ViewEmptyText'].Text = empty

    def _on_only_hidden(self, sender, e):
        on = bool(self.c['OnlyHiddenToggle'].IsChecked)
        self.settings['only_hidden'] = '1' if on else '0'
        core.save_settings(self.settings)
        self._refilter_views()

    def _ticked_views(self):
        out = []
        for vk, r in self.view_rows.items():
            try:
                if bool(r['tick']):
                    out.append(vk)
            except Exception:
                pass
        return out

    def _on_view_selected(self, sender, e):
        if self.suspend:
            return
        added = e.AddedItems
        if added is None or added.Count == 0:
            return
        drv = added[added.Count - 1]
        if not isinstance(drv, DataRowView):
            return
        vk = int(drv.Row['key'])
        if vk != self.focus_key:
            self._set_focus(vk, select_row=False)

    def _on_view_double(self, sender, e):
        row = _ancestor(e.OriginalSource, [DataGridRow])
        if row is None or not isinstance(row.Item, DataRowView):
            return
        vk = int(row.Item.Row['key'])
        v = self.view_by_key.get(vk)
        if v is None or not self._doc_ok():
            return
        log = self.log
        doc = self.doc

        def work(uiapp):
            uidoc = uiapp.ActiveUIDocument
            if uidoc is None or not rv.same_doc(uidoc.Document, doc):
                return u'Open this model in Revit first - the window is reading another one.'
            ok = rv.activate_view(uidoc, v['view'], log)
            return u'Opened ' + v['name'] if ok else u'Revit would not open ' + v['name']
        self._submit('Open view', work, lambda msg: self.set_status(msg))

    # =================================================================
    # Focus: which view the left table shows
    # =================================================================

    def _set_focus(self, vk, select_row=False):
        self.focus_key = vk
        v = self.view_by_key.get(vk)
        self.c['FocusViewText'].Text = (u'{0}  ({1})'.format(v['name'], v['type']) if v else u'')
        self.elem_table.Rows.Clear()
        self.elem_rows = {}
        self.elem_all.IsChecked = False
        if select_row:
            self._select_view_row(vk)
        if v is None:
            self.c['ElemEmptyText'].Text = u'No view to show.'
        elif vk in self.hidden:
            self._request_elem_rows(vk)
        else:
            self.c['ElemEmptyText'].Text = u'Scanning this view...'
            self.c['ElemCountText'].Text = u''
            if self.scanner is not None:
                self.scanner.bump([vk])
                self._pump_scan()
        self._targets_changed()

    def _select_view_row(self, vk):
        r = self.view_rows.get(vk)
        if r is None:
            return
        g = self.c['ViewGrid']
        self.suspend = True
        try:
            for drv in self.view_table.DefaultView:
                if drv.Row is r or drv.Row['key'] == r['key']:
                    g.SelectedItem = drv
                    g.ScrollIntoView(drv)
                    break
        finally:
            self.suspend = False

    def _on_current_view(self, sender, e):
        doc = self.doc

        def work(uiapp):
            uidoc = uiapp.ActiveUIDocument
            if uidoc is None or not rv.same_doc(uidoc.Document, doc):
                return None
            return rv.active_view_key(uidoc)

        def done(vk):
            if vk is None:
                self.set_status(u'The model open in Revit is not the one this window read - press Refresh.', 'warn')
                return
            if vk not in self.view_by_key:
                self.set_status(u'The open view cannot hide elements (a schedule or browser) - pick one from the list.', 'warn')
                return
            self._set_focus(vk, select_row=True)
        self._submit('Current view', work, done)

    # =================================================================
    # Hidden elements table
    # =================================================================

    def _request_elem_rows(self, vk):
        hidden = self.hidden.get(vk)
        v = self.view_by_key.get(vk)
        if hidden is None or v is None:
            return
        if not hidden:
            self._fill_elems(vk, [])
            return
        self.c['ElemEmptyText'].Text = u'Reading {0}...'.format(core.plural(len(hidden), u'element'))
        doc = self.doc
        items = sorted(hidden.items())

        def work(uiapp):
            cache = {}
            return vk, [rv.element_row(doc, eid, v['view'], cache) for _k, eid in items]
        self._submit('Read hidden elements', work, lambda p: self._fill_elems(p[0], p[1]), user=False)

    def _fill_elems(self, vk, rows):
        if vk != self.focus_key:
            return
        t = self.elem_table
        t.Rows.Clear()
        self.elem_rows = {}
        for d in rows:
            r = t.NewRow()
            k = d['key']
            r['key'] = core.to_text(k)
            r['tick'] = self.staging.element_ticked(vk, k)
            r['id_txt'] = d['id_txt']
            r['nid'] = core.natural_key(d['id_txt'])
            r['category'] = d['category']
            r['ftype'] = d['ftype']
            r['level'] = d['level']
            note = self.elem_notes.get((vk, k))
            if note:
                r['note'] = note
                r['bad'] = u'1'
                r['warn'] = u'0'
            else:
                r['note'] = d['note']
                r['bad'] = d['bad']
                r['warn'] = d['warn']
            r['hot'] = u'0'
            r['vis'] = u'1'
            t.Rows.Add(r)
            self.elem_rows[k] = r
        self._refilter_elems()

    def _refilter_elems(self):
        filters = dict((k, v) for k, v in self.elem_filters.items() if v)
        for k, r in self.elem_rows.items():
            values = dict((c, r[c]) for c in self.ELEM_FILTER_COLS)
            want = u'1' if core.row_matches_columns(values, filters) else u'0'
            if r['vis'] != want:
                r['vis'] = want
        total = len(self.elem_rows)
        shown = self.elem_table.DefaultView.Count
        if self.focus_key in self.hidden:
            txt = core.plural(total, u'hidden element')
            if shown != total:
                txt += u', {0} shown'.format(shown)
            self.c['ElemCountText'].Text = txt
        if not total and self.focus_key in self.hidden:
            self.c['ElemEmptyText'].Text = u'Nothing is hidden in this view by Hide in View > Elements.'
        elif total and not shown:
            self.c['ElemEmptyText'].Text = u'No hidden elements match the filters.'
        else:
            self.c['ElemEmptyText'].Text = u''
        self.refresh_buttons()

    def _on_elem_double(self, sender, e):
        row = _ancestor(e.OriginalSource, [DataGridRow])
        if row is None or not isinstance(row.Item, DataRowView):
            return
        vk = self.focus_key
        ek = int(row.Item.Row['key'])
        eid = (self.hidden.get(vk) or {}).get(ek)
        v = self.view_by_key.get(vk)
        if eid is None or v is None or not self._doc_ok():
            return
        log = self.log
        doc = self.doc

        def work(uiapp):
            uidoc = uiapp.ActiveUIDocument
            if uidoc is None or not rv.same_doc(uidoc.Document, doc):
                return u'Open this model in Revit first - the window is reading another one.'
            rv.activate_view(uidoc, v['view'], log)
            ok = rv.select_ids(uidoc, [eid], log)
            return (u'Selected element {0} - its properties are in the Properties palette.'.format(ek)
                    if ok else u'Revit would not select element {0}.'.format(ek))
        self._submit('Select element', work, lambda msg: self.set_status(msg))

    # =================================================================
    # Categories
    # =================================================================

    def _targets(self):
        return core.target_views(self._ticked_views(), self.focus_key)

    def _targets_changed(self):
        targets = self._targets()
        ticked = self._ticked_views()
        if ticked:
            self.c['CatTargetText'].Text = u'in the {0} ticked'.format(core.plural(len(ticked), u'view'))
        else:
            v = self.view_by_key.get(self.focus_key)
            self.c['CatTargetText'].Text = (u'in ' + v['name']) if v else u''
        if not targets:
            self.cat_table.Rows.Clear()
            self.cat_rows = {}
            self.c['CatEmptyText'].Text = u''
            return
        self._refresh_categories()

    CAT_VIEWS_PER_JOB = 20

    def _refresh_categories(self):
        """Category state is read a few views per ExternalEvent, so ticking
        every view in a big project never holds Revit for long."""
        targets = self._targets()
        missing = [vk for vk in targets if vk not in self.cat_state and vk in self.view_by_key]
        if not missing:
            self._fill_cats()
            return
        if self.cat_job_pending:
            self.cat_job_again = True
            return
        self.cat_job_pending = True
        read = len([vk for vk in targets if vk in self.cat_state])
        self.c['CatEmptyText'].Text = u'Reading categories... {0} / {1} views'.format(read, len(targets))
        doc = self.doc
        cats = self.cats
        views = [(vk, self.view_by_key[vk]['view']) for vk in missing[:self.CAT_VIEWS_PER_JOB]]
        log = self.log

        def work(uiapp):
            out = {}
            for vk, view in views:
                try:
                    out[vk] = rv.read_category_state(doc, view, cats, log)
                except Exception:
                    log.add(u'Categories of view {0} unreadable: {1}'.format(vk, traceback.format_exc()))
                    out[vk] = {}
            return out

        def done(states):
            self.cat_job_pending = False
            self.cat_job_again = False
            self.cat_state.update(states)
            self._refresh_categories()
        self._submit('Categories', work, done, user=False)

    def _fill_cats(self):
        targets = self._targets()
        rows = core.summarise_categories(targets, self.cat_state, self.cat_names)
        self.staging.prune_categories(set(r['key'] for r in rows))
        change_t = bool(self.c['ChangeTemplatesChk'].IsChecked)
        t = self.cat_table
        t.Rows.Clear()
        self.cat_rows = {}
        for d in rows:
            r = t.NewRow()
            k = d['key']
            r['key'] = core.to_text(k)
            r['tick'] = k in self.staging.categories
            r['name'] = d['name']
            r['nkey'] = core.natural_key(d['name'])
            r['hidden_txt'] = d['hidden_text']
            r['hidden_n'] = d['hidden_in']
            refused = self.cat_notes.get(k)
            if refused:
                r['note'] = refused
                r['bad'] = u'1'
                r['warn'] = u'0'
            else:
                note = d['note']
                if note and not change_t:
                    note += u' - tick "Also change view templates" to unhide it there'
                r['note'] = note
                r['bad'] = u'0'
                r['warn'] = u'1' if d['templates'] else u'0'
            r['hot'] = u'1'
            r['vis'] = u'1'
            t.Rows.Add(r)
            self.cat_rows[k] = r
        self._refilter_cats()

    def _refilter_cats(self):
        q = self.c['CatSearch'].Text
        for k, r in self.cat_rows.items():
            want = u'1' if core.keyword_match(r['name'], q) else u'0'
            if r['vis'] != want:
                r['vis'] = want
        total = len(self.cat_rows)
        shown = self.cat_table.DefaultView.Count
        if not total:
            self.c['CatEmptyText'].Text = u'No categories are hidden in these views.'
        elif not shown:
            self.c['CatEmptyText'].Text = u'No hidden categories match the search.'
        else:
            self.c['CatEmptyText'].Text = u''
        self.refresh_buttons()

    def _on_change_templates(self, sender, e):
        on = bool(self.c['ChangeTemplatesChk'].IsChecked)
        self.settings['change_templates'] = '1' if on else '0'
        core.save_settings(self.settings)
        self._fill_cats()

    # =================================================================
    # Ticks
    # =================================================================

    def _tick_handler(self, which):
        def handler(sender, e):
            src = e.OriginalSource
            if not isinstance(src, CheckBox):
                return
            drv = getattr(src, 'DataContext', None)
            if not isinstance(drv, DataRowView):
                return
            try:
                drv.EndEdit()
            except Exception:
                pass
            self._ticked(which, [drv.Row], bool(src.IsChecked))
        return handler

    def _ticked(self, which, rows, on):
        for r in rows:
            if bool(r['tick']) != on:
                r['tick'] = on
            k = int(r['key'])
            if which == 'elem':
                self.staging.set_element(self.focus_key, k, on)
            elif which == 'cat':
                self.staging.set_category(k, on)
        if which == 'view':
            for r in rows:
                vk = int(r['key'])
                if on and self.scanner is not None and vk not in self.hidden:
                    self.scanner.bump([vk])
            self._pump_scan()
            self._targets_changed()
        self.refresh_buttons()

    def _shown_rows(self, table):
        return [drv.Row for drv in table.DefaultView]

    def _on_view_all(self, sender, e):
        self._ticked('view', self._shown_rows(self.view_table), bool(sender.IsChecked))

    def _on_elem_all(self, sender, e):
        self._ticked('elem', self._shown_rows(self.elem_table), bool(sender.IsChecked))

    def _on_cat_all(self, sender, e):
        self._ticked('cat', self._shown_rows(self.cat_table), bool(sender.IsChecked))

    def _toggle_selected(self, grid, which):
        rows = [item.Row for item in grid.SelectedItems if isinstance(item, DataRowView)]
        if not rows:
            return False
        on = not all(bool(r['tick']) for r in rows)
        self._ticked(which, rows, on)
        return True

    # =================================================================
    # Buttons
    # =================================================================

    def _selected_elem_keys(self):
        out = []
        for item in self.c['ElemGrid'].SelectedItems:
            if isinstance(item, DataRowView):
                try:
                    out.append(int(item.Row['key']))
                except Exception:
                    pass
        return out

    def _effective_staging(self):
        """Ticks if there are any; otherwise the rows selected in the left
        table - 'select them and click Unhide' works without ticking."""
        if self.staging.element_total() or self.focus_key is None:
            return self.staging, False
        sel = self._selected_elem_keys()
        if not sel:
            return self.staging, False
        st = core.Staging()
        st.categories = set(self.staging.categories)
        for k in sel:
            st.set_element(self.focus_key, k, True)
        return st, True

    def refresh_buttons(self):
        if self.view_table is None:
            return
        busy = self.user_jobs > 0
        loaded = self.doc is not None
        st, from_sel = self._effective_staging()
        n_el = st.element_total()
        n_cat = len(st.categories)
        label = core.unhide_label(n_el, n_cat)
        if from_sel and n_el:
            label += u' (selected)'
        self.c['UnhideText'].Text = label
        self.c['UnhideBtn'].IsEnabled = bool(loaded and not busy and (n_el or n_cat))

        ticked = self._ticked_views()
        n_hidden = 0
        waiting = 0
        for vk in ticked:
            if vk in self.hidden:
                n_hidden += len(self.hidden[vk])
            else:
                waiting += 1
        if waiting:
            self.c['UnhideViewsText'].Text = u'Unhide all in ticked views (scanning {0})'.format(waiting)
        else:
            self.c['UnhideViewsText'].Text = core.views_button_label(len(ticked), n_hidden)
        self.c['UnhideViewsBtn'].IsEnabled = bool(
            loaded and not busy and ticked and not waiting and n_hidden)
        if ticked:
            extra = u''
            if self.staging.element_total():
                extra = u' - {0} elements ticked in {1}'.format(
                    self.staging.element_total(), core.plural(self.staging.element_views(), u'view'))
            self.c['TickedText'].Text = core.plural(len(ticked), u'view') + u' ticked' + extra
        elif self.staging.element_total():
            self.c['TickedText'].Text = u'{0} elements ticked in {1}'.format(
                self.staging.element_total(), core.plural(self.staging.element_views(), u'view'))
        else:
            self.c['TickedText'].Text = u'Tick views to unhide everything in them'

    # =================================================================
    # Unhide
    # =================================================================

    def _doc_ok(self):
        if rv.doc_alive(self.doc):
            return True
        self.set_status(u'The model this window read has been closed - press Refresh.', 'warn')
        return False

    def _on_unhide(self, sender, e):
        if not self._doc_ok():
            return
        st, _from_sel = self._effective_staging()
        self._start_unhide(st, self._targets())

    def _on_unhide_views(self, sender, e):
        if not self._doc_ok():
            return
        st = core.Staging()
        for vk in self._ticked_views():
            for ek in (self.hidden.get(vk) or {}).keys():
                st.set_element(vk, ek, True)
        if not st.element_total():
            self.set_status(u'Nothing is hidden in the ticked views.')
            return
        n = st.element_total()
        nv = st.element_views()
        self._confirm(u'Unhide everything in the ticked views?',
                      u'{0} hidden in {1} will be shown again. One undo step reverses it.'.format(
                          core.plural(n, u'element'), core.plural(nv, u'view')),
                      u'Unhide {0}'.format(core.plural(n, u'element')),
                      lambda: self._start_unhide(st, []))

    def _start_unhide(self, staging, targets):
        missing = [vk for vk in targets if vk not in self.cat_state]
        if staging.categories and missing:
            self.set_status(u'Still reading the categories of the target views - try again in a moment.', 'warn')
            self._refresh_categories()
            return
        hidden_keys = dict((vk, set(d.keys())) for vk, d in self.hidden.items())
        change_t = bool(self.c['ChangeTemplatesChk'].IsChecked)
        plan = core.build_plan(staging, hidden_keys, targets, self.cat_state, change_t,
                               lambda vk: (self.view_by_key.get(vk) or {}).get('template_key'))
        n_el, n_ev, n_cat, n_own = core.plan_counts(plan)
        self.log.add(u'Plan: {0} elements in {1} views, {2} categories on {3} views/templates, {4} skipped'.format(
            n_el, n_ev, n_cat, n_own, len(plan['skipped'])))
        for s in plan['skipped']:
            self.log.add(u'  skip {0} {1} {2}: {3}'.format(s[0], s[1], s[2], s[3]))
        if not n_el and not n_cat:
            reason = plan['skipped'][0][3] if plan['skipped'] else u'nothing is ticked'
            self.set_status(u'Nothing to unhide - ' + reason + u'.', 'warn')
            return
        templates = [okey for okey, is_t, _c in plan['categories'] if is_t]
        if templates:
            names = []
            users = 0
            for okey in templates:
                for v in self.views:
                    if v.get('template_key') == okey:
                        users += 1
                        if v['template_name'] not in names:
                            names.append(v['template_name'])
            self._confirm(u'Change view templates?',
                          u'This unhides categories on {0} ({1}), which changes every view using '
                          u'them - {2} in this model.'.format(
                              core.plural(len(templates), u'template'), u', '.join(names),
                              core.plural(users, u'view')),
                          u'Change templates and unhide',
                          lambda: self._run_plan(plan))
            return
        self._run_plan(plan)

    def _template_view(self, tkey):
        for v in self.views:
            if v.get('template_key') == tkey and v.get('template_id') is not None:
                return self.doc.GetElement(v['template_id'])
        return None

    def _run_plan(self, plan):
        doc = self.doc
        log = self.log
        hidden = self.hidden
        view_by_key = self.view_by_key
        cat_ids = self.cat_ids

        def view_of(vk):
            v = view_by_key.get(vk)
            return v['view'] if v else None

        def owner_of(key, is_t):
            return self._template_view(key) if is_t else view_of(key)

        def eid_of(vk, ek):
            return (hidden.get(vk) or {}).get(ek)

        def cat_id_of(ck):
            return cat_ids.get(ck)

        def work(uiapp):
            return rv.run_unhide(doc, plan, view_of, owner_of, eid_of, cat_id_of, uiapp, log)

        self.set_status(u'Unhiding...')
        self._submit('Unhide', work, lambda result: self._after_unhide(plan, result))

    def _after_unhide(self, plan, result):
        touched_views = set()
        for vk, ek in result['ok_elements']:
            d = self.hidden.get(vk)
            if d is not None:
                d.pop(ek, None)
            self.staging.set_element(vk, ek, False)
            self.elem_notes.pop((vk, ek), None)
            touched_views.add(vk)
        for kind, owner, key, msg in result['refused']:
            if kind == 'element':
                self.elem_notes[(owner, key)] = msg
                self.staging.set_element(owner, key, False)
                touched_views.add(owner)
            elif kind == 'category':
                self.cat_notes[key] = msg
        for vk in touched_views:
            if self.scanner is not None and vk in self.hidden:
                self.scanner.results[vk] = list((self.hidden.get(vk) or {}).values())
            self._update_view_count(vk)

        # categories: every view whose own settings or template changed reads again
        changed_owners = set()
        for okey, is_t, ck in result['ok_categories']:
            self.staging.set_category(ck, False)
            self.cat_notes.pop(ck, None)
            changed_owners.add((okey, is_t))
        for okey, is_t, _cks in plan['categories']:
            changed_owners.add((okey, is_t))
        for okey, is_t in changed_owners:
            if is_t:
                for v in self.views:
                    if v.get('template_key') == okey:
                        self.cat_state.pop(v['key'], None)
            else:
                self.cat_state.pop(okey, None)

        for s in result.get('skipped') or []:
            self.log.add(u'Skipped {0} {1} {2}: {3}'.format(s[0], s[1], s[2], s[3]))
        if self.focus_key in touched_views or self.focus_key in self.hidden:
            self._request_elem_rows(self.focus_key)
        self._targets_changed()
        self._refilter_views()
        kind = 'bad' if result['refused'] else ('good' if (result['elements_ok'] or result['categories_ok']) else 'warn')
        self.set_status(core.summarise_result(result), kind)
        self.log.flush(self._debug_header())
        try:
            self.uiapp.ActiveUIDocument.RefreshActiveView()
        except Exception:
            pass

    # =================================================================
    # Confirm overlay
    # =================================================================

    def _confirm(self, title, text, yes_label, action):
        # a prompt on a shrunk window would sit over the bar - open it first
        if not self.drawer.is_open():
            self.drawer.restore_now()
        self.confirm_action = action
        self.c['ConfirmTitle'].Text = title
        self.c['ConfirmText'].Text = text
        self.c['ConfirmYesText'].Text = yes_label
        self.c['ConfirmOverlay'].Visibility = Visibility.Visible

    def _hide_confirm(self):
        self.c['ConfirmOverlay'].Visibility = Visibility.Collapsed
        self.confirm_action = None

    def _on_confirm_yes(self, sender, e):
        action = self.confirm_action
        self._hide_confirm()
        if action is not None:
            action()

    # =================================================================
    # Keyboard
    # =================================================================

    def _on_key(self, sender, e):
        mods = Keyboard.Modifiers
        ctrl = (mods & ModifierKeys.Control) == ModifierKeys.Control
        shift = (mods & ModifierKeys.Shift) == ModifierKeys.Shift
        focus = Keyboard.FocusedElement
        in_text = isinstance(focus, TextBox)
        # the most specific combination first - first match wins
        if ctrl and shift and e.Key == Key.H:
            self.drawer.toggle()
            e.Handled = True
            return
        if not self.drawer.is_open():
            # shrunk: Escape, Enter and F11 bring the window back rather than
            # reaching the close prompt or filling the screen with nothing
            if e.Key in (Key.Escape, Key.Enter, Key.Return, Key.F11):
                self.drawer.expand()
                e.Handled = True
            return
        if e.Key == Key.F5:
            self.load()
            e.Handled = True
        elif e.Key == Key.F11:
            self.fullscreen.toggle()
            e.Handled = True
        elif e.Key == Key.Escape:
            if self.c['ConfirmOverlay'].Visibility == Visibility.Visible:
                self._hide_confirm()
            elif self.fullscreen.active():
                self.fullscreen.leave()
            elif in_text and focus.Text:
                focus.Text = u''
            e.Handled = True
        elif ctrl and e.Key == Key.F:
            self.c['ViewSearch'].Focus()
            self.c['ViewSearch'].SelectAll()
            e.Handled = True
        elif e.Key == Key.Space and not in_text:
            for name, which in (('ElemGrid', 'elem'), ('ViewGrid', 'view'), ('CatGrid', 'cat')):
                g = self.c[name]
                if g.IsKeyboardFocusWithin:
                    if self._toggle_selected(g, which):
                        e.Handled = True
                    break

    # =================================================================
    # Watchdog and closing
    # =================================================================

    def _on_watchdog(self, sender, e):
        if self.runner.watchdog():
            self.set_status(u'Revit had not answered for 20s - asked again.', 'warn')
        if self.user_jobs and time.time() - self.busy_since > 25.0:
            self.log.add(u'Window freed after 25s busy ({0} jobs outstanding)'.format(self.user_jobs))
            self.user_jobs = 0
            self.set_status(u'Revit did not answer - the window is free again. Try once more.', 'warn')
            self.refresh_buttons()

    def request_close(self):
        if self.staging.anything():
            n = self.staging.element_total()
            nc = len(self.staging.categories)
            self._confirm(u'Close without unhiding?',
                          u'{0} and {1} are ticked and have not been unhidden.'.format(
                              core.plural(n, u'element'), core.plural(nc, u'category', u'categories')),
                          u'Close anyway', self._really_close)
            return
        self._really_close()

    def _really_close(self):
        self.close_ok = True
        try:
            self.win.Close()
        except Exception:
            pass

    def _on_closing(self, sender, e):
        try:
            if not self.close_ok and self.staging.anything():
                e.Cancel = True
                self.request_close()
        except Exception:
            pass

    def _on_closed(self, sender, e):
        self.closed = True
        for t in (self.view_timer, self.elem_timer, self.cat_timer, self.scan_timer, self.watch_timer):
            try:
                t.Stop()
            except Exception:
                pass
        self.drawer.stop()
        try:
            # the real size - not the parked bar, not the full-screen bounds
            bounds = self.drawer.true_bounds()
            if self.fullscreen.saved is not None:
                bounds = self.fullscreen.saved
            s = self.settings
            s['width'] = u'{0:.0f}'.format(bounds[2])
            s['height'] = u'{0:.0f}'.format(bounds[3])
            lw = self.c['LeftCol'].ActualWidth
            rw = self.c['RightCol'].ActualWidth
            if lw + rw > 0:
                s['split'] = u'{0:.3f}'.format(lw / (lw + rw))
            eh = self.c['ElemRow'].ActualHeight
            ch = self.c['CatRow'].ActualHeight
            if eh + ch > 0:
                s['cat_split'] = u'{0:.3f}'.format(ch / (eh + ch))
            core.save_settings(s)
        except Exception:
            pass
        self.log.add(u'Closed')
        self.log.flush(self._debug_header())
        try:
            if AppDomain.CurrentDomain.GetData(core.APPDOMAIN_KEY) is self:
                AppDomain.CurrentDomain.SetData(core.APPDOMAIN_KEY, None)
        except Exception:
            pass
        _PARKED.clear()

    # ---- used by launch() for a second click on the ribbon button -------------
    def is_open(self):
        return not self.closed and bool(self.win.IsVisible)

    def bring_forward(self):
        try:
            self.win.Activate()
        except Exception:
            pass

    def force_close(self):
        self.close_ok = True
        try:
            self.win.Close()
        except Exception:
            pass


# =====================================================================
# Launch
# =====================================================================

def _note_path():
    return core.settings_path(core.OPEN_NOTE_FILE)


def _engine_looked_dead():
    """A note left by the last modeless window that no handler ever cleared
    means its engine was gone: every button would have been dead."""
    try:
        p = _note_path()
        if not os.path.exists(p):
            return False
        f = open(p, 'r')
        try:
            text = f.read().strip()
        finally:
            f.close()
        return text == core.__version__
    except Exception:
        return False


def _write_note():
    try:
        d = core.settings_dir()
        if not os.path.isdir(d):
            os.makedirs(d)
        f = open(_note_path(), 'w')
        try:
            f.write(core.__version__)
        finally:
            f.close()
    except Exception:
        pass


def _clear_note():
    try:
        p = _note_path()
        if os.path.exists(p):
            os.remove(p)
    except Exception:
        pass


def _ask_modal():
    try:
        td = TaskDialog(u'RevoBIM Unhide in View')
        td.MainInstruction = u'Last time the window did not respond'
        td.MainContent = (u'Open it as a modal window this time? Revit is locked while it is '
                          u'open, but every button works.')
        td.CommonButtons = TaskDialogCommonButtons.Yes | TaskDialogCommonButtons.No
        return str(td.Show()) == 'Yes'
    except Exception:
        return False


def launch(uiapp):
    settings = core.load_settings()
    log = core.DebugLog(core.as_bool(settings.get('debug')))
    log.add(u'RevoBIM Unhide in View v{0} - {1}'.format(
        core.__version__, time.strftime('%Y-%m-%d %H:%M:%S')))
    try:
        log.add(u'Revit {0}, assemblies missing: {1}'.format(
            core.to_text(uiapp.Application.VersionNumber), u', '.join(uiv_clr.MISSING) or u'none'))
    except Exception:
        pass

    old = None
    try:
        old = AppDomain.CurrentDomain.GetData(core.APPDOMAIN_KEY)
    except Exception:
        old = None
    if old is not None:
        try:
            if getattr(old, 'version', None) == core.__version__ and old.is_open():
                old.bring_forward()
                return old
            old.force_close()
        except Exception:
            pass

    modal = False
    if _engine_looked_dead():
        log.add(u'Open-note left by the last session - offering modal')
        modal = _ask_modal()
        _clear_note()

    runner = Runner(log)
    if modal:
        runner.direct_uiapp = uiapp
    else:
        runner.create_event()
    w = UnhideWindow(uiapp, runner, settings, log, modal)
    _PARKED['window'] = w
    _PARKED['runner'] = runner
    try:
        AppDomain.CurrentDomain.SetData(core.APPDOMAIN_KEY, w)
    except Exception:
        pass
    ui.own_to_revit(w.win, uiapp)
    if modal:
        w.win.ShowDialog()
    else:
        _write_note()
        w.arm()
        w.win.Show()
    return w
