# -*- coding: utf-8 -*-
"""Selected in View - the modeless window, the selection filter and the
ExternalEvent runner.

While the window is open, every selection Revit makes is checked as it
lands: elements whose category (or tag type) is unticked, linked models
when Linked models is red, and pinned elements when Pinned is red are taken
straight back out. Closing the window unhooks it and selection is normal.
"""
import os
import sys
import time

import siv_clr  # noqa: F401  (assemblies first)

from System import AppDomain, EventHandler
from System.Windows import (
    Thickness, CornerRadius, GridLength, GridUnitType, HorizontalAlignment,
    VerticalAlignment, Visibility, TextTrimming, FontWeights, Clipboard,
    SystemParameters, PresentationSource,
)
from System.Windows.Controls import (
    StackPanel, Grid, ColumnDefinition, TextBlock, CheckBox, Border, Button,
    Orientation,
)
from System.Windows.Shapes import Path
from System.Windows.Media import Brushes
from System.Windows.Input import Key
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Forms import Screen
from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent, ExternalEventRequest
from Autodesk.Revit.UI.Events import SelectionChangedEventArgs, ViewActivatedEventArgs

import siv_core as core
import siv_revit as rv
import siv_ui as ui

HOOK_KEY = 'RevoBIM.SelectedInView.hooks'
WIN_KEY = 'RevoBIM.SelectedInView.window'

ARROW_RIGHT = 'M2,1 L7,5 L2,9 Z'
ARROW_DOWN = 'M0,2 L9,2 L4.5,7 Z'

_KEEP_ALIVE = []


# =====================================================================
# AppDomain bookkeeping - one window, one set of event hooks
# =====================================================================
def _domain_get(key):
    try:
        return AppDomain.CurrentDomain.GetData(key)
    except Exception:
        return None


def _domain_set(key, value):
    try:
        AppDomain.CurrentDomain.SetData(key, value)
    except Exception:
        pass


def _unhook_saved():
    """Remove hooks left by an earlier run (or an engine that died)."""
    saved = _domain_get(HOOK_KEY)
    if saved is None:
        return
    try:
        app = saved[0]
        try:
            app.SelectionChanged -= saved[1]
        except Exception:
            pass
        try:
            app.ViewActivated -= saved[2]
        except Exception:
            pass
    except Exception:
        pass
    _domain_set(HOOK_KEY, None)


# =====================================================================
# ExternalEvent runner - for work started from the window
# =====================================================================
class _Handler(IExternalEventHandler):
    def __init__(self, log):
        self.log = log
        self.jobs = []

    def Execute(self, uiapp):
        jobs = self.jobs
        self.jobs = []
        for name, fn in jobs:
            try:
                fn(uiapp)
            except Exception as ex:
                self.log.add(u'job {0} failed: {1}'.format(name, ex))

    def GetName(self):
        return 'RevoBIM Selected in View'


class Runner(object):
    def __init__(self, log):
        self.log = log
        self.handler = _Handler(log)
        self.event = ExternalEvent.Create(self.handler)

    def run(self, name, fn):
        job = (name, fn)
        self.handler.jobs.append(job)
        status = self.event.Raise()
        if status == ExternalEventRequest.Accepted or status == ExternalEventRequest.Pending:
            return True
        # refused: remove only this job, never the queue
        try:
            self.handler.jobs.remove(job)
        except ValueError:
            pass
        self.log.add(u'Raise() refused for {0}: {1}'.format(name, status))
        return False

    def dispose(self):
        try:
            self.event.Dispose()
        except Exception:
            pass


# =====================================================================
# The window
# =====================================================================
class Controller(object):

    def __init__(self, uiapp, folder):
        self.uiapp = uiapp
        self.folder = folder
        self.settings = core.load_settings()
        self.log = core.DebugLog(core.debug_path(), self.settings.get('debug') == '1')
        self.state = core.FilterState()
        self.rows = []
        self.ui_rows = {}
        self.ui_sections = {}
        self.expanded = set()
        self.closed = False
        self.busy_sel = False
        self.stale = False
        self.full = None
        self.mode = 'dark'
        self.egg_shared = False
        self.clicks = core.SlowClicks()
        self.hooks = None
        self.view_label = u''
        self.stats = {}
        self.runner = Runner(self.log)
        self.win = ui.load_window(folder)
        self.ctl = self.win.FindName
        self._log_environment()
        self._wire()
        self.apply_theme()
        self._restore_bounds()

    # ---------------------------------------------------------------
    def _log_environment(self):
        self.log.add(u'===== Selected in View {0} - {1} ====='.format(
            core.__version__, time.strftime('%Y-%m-%d %H:%M:%S')))
        try:
            self.log.add(u'Revit {0} | {1}'.format(
                self.uiapp.Application.VersionNumber, sys.version.split()[0]))
        except Exception:
            pass
        if siv_clr.SKIPPED:
            self.log.add(u'assemblies skipped: {0}'.format(u', '.join(siv_clr.SKIPPED)))

    def _safe(self, fn):
        def handler(sender, args):
            try:
                fn(sender, args)
            except Exception as ex:
                self.log.add(u'UI error in {0}: {1}'.format(getattr(fn, '__name__', '?'), ex))
                self.set_status(u'Something went wrong - tick Debug and Copy debug.')
        return handler

    def _wire(self):
        c = self.ctl
        c('VersionText').Text = u'v' + core.__version__
        img = ui.load_image(os.path.join(self.folder, 'icon.png'))
        if img is not None:
            c('LogoIcon').Source = img
        c('DebugCheck').IsChecked = self.log.enabled

        c('Header').MouseLeftButtonDown += self._safe(self.on_header_down)
        c('LogoIcon').MouseLeftButtonDown += self._safe(self.on_logo_down)
        c('BrandText').MouseLeftButtonDown += self._safe(self.on_logo_down)
        c('ThemeBtn').Click += self._safe(self.on_theme)
        c('FullBtn').Click += self._safe(self.on_full)
        c('CloseBtn').Click += self._safe(self.on_close)
        c('LinksBtn').Click += self._safe(self.on_links)
        c('PinnedBtn').Click += self._safe(self.on_pinned)
        c('AllBtn').Click += self._safe(self.on_all)
        c('NoneBtn').Click += self._safe(self.on_none)
        c('RefreshBtn').Click += self._safe(self.on_refresh)
        c('SearchBox').TextChanged += self._safe(self.on_search)
        c('DebugCheck').Click += self._safe(self.on_debug)
        c('CopyBtn').Click += self._safe(self.on_copy)
        self.win.PreviewKeyDown += self._safe(self.on_key)
        self.win.Activated += self._safe(self.on_activated)
        self.win.Closed += self._safe(self.on_closed)

        grips = {
            'GripL': (True, False, False, False), 'GripR': (False, False, True, False),
            'GripT': (False, True, False, False), 'GripB': (False, False, False, True),
            'GripTL': (True, True, False, False), 'GripTR': (False, True, True, False),
            'GripBL': (True, False, False, True), 'GripBR': (False, False, True, True),
        }
        for name, sides in grips.items():
            c(name).DragDelta += self._safe(self._grip_handler(sides))

        ui.set_owner(self.win, self.uiapp)
        self.egg_shared = ui.attach_egg(self.win)
        self.update_state_buttons()

    # ---------------------------------------------------------------
    # Event hooks
    # ---------------------------------------------------------------
    def hook(self):
        _unhook_saved()
        sd = EventHandler[SelectionChangedEventArgs](self.on_selection_changed)
        vd = EventHandler[ViewActivatedEventArgs](self.on_view_activated)
        self.uiapp.SelectionChanged += sd
        self.uiapp.ViewActivated += vd
        self.hooks = (sd, vd)
        _domain_set(HOOK_KEY, (self.uiapp, sd, vd))
        self.log.add(u'hooked SelectionChanged and ViewActivated')

    def unhook(self):
        if self.hooks is None:
            return
        sd, vd = self.hooks
        try:
            self.uiapp.SelectionChanged -= sd
        except Exception:
            pass
        try:
            self.uiapp.ViewActivated -= vd
        except Exception:
            pass
        self.hooks = None
        saved = _domain_get(HOOK_KEY)
        try:
            if saved is not None and saved[1] is sd:
                _domain_set(HOOK_KEY, None)
        except Exception:
            _domain_set(HOOK_KEY, None)
        self.log.add(u'unhooked')

    def on_selection_changed(self, sender, args):
        if self.closed or self.busy_sel or not self.state.restricting():
            return
        try:
            self._filter_selection(args)
        except Exception as ex:
            self.log.add(u'selection filter error: {0}'.format(ex))

    def _filter_selection(self, args):
        doc = None
        ids = []
        try:
            doc = args.GetDocument()
            ids = list(args.GetSelectedElements())
        except Exception:
            uidoc = self.uiapp.ActiveUIDocument
            if uidoc is None:
                return
            doc = uidoc.Document
            ids = list(uidoc.Selection.GetElementIds())
        if doc is None or not ids:
            return
        keep, dropped, unknown = rv.plan_selection(doc, ids, self.state)
        if unknown:
            self.mark_stale(True)
        if not dropped:
            return
        summary = core.drop_summary(len(keep), dropped)
        done = False
        self.busy_sel = True
        try:
            rv.set_selection(self.uiapp.ActiveUIDocument, keep)
            done = True
        except Exception as ex:
            self.log.add(u'direct reselect refused ({0}); queuing'.format(ex))
        finally:
            self.busy_sel = False
        if not done:
            kept = list(keep)
            self.runner.run('reselect', lambda app: rv.set_selection(app.ActiveUIDocument, kept))
        self.log.add(u'pick of {0}: {1}'.format(len(ids), summary))
        self.set_status(summary)

    def on_view_activated(self, sender, args):
        if self.closed:
            return
        try:
            view = args.CurrentActiveView
            doc = args.Document
            if view is not None:
                self.load_view(doc, view)
        except Exception as ex:
            self.log.add(u'view refresh error: {0}'.format(ex))

    # ---------------------------------------------------------------
    # Reading the view and building the list
    # ---------------------------------------------------------------
    def load_view(self, doc, view):
        records, stats = rv.read_view(doc, view)
        self.stats = stats
        self.rows = core.build_list(records)
        self.state.learn(self.rows)
        try:
            self.view_label = u'{0}  -  {1}'.format(view.Name, doc.Title)
        except Exception:
            self.view_label = u''
        self.ctl('ViewText').Text = u'View: ' + self.view_label
        self.ctl('ViewText').ToolTip = self.view_label
        self.rebuild_list()
        self.apply_search()
        self.mark_stale(False)
        self.update_state_buttons()
        self.log.add(u'read view "{0}": {1} elements, {2} categories, {3} links, {4} pinned, {5} skipped'.format(
            self.view_label, stats.get('elements'), len(self.rows), stats.get('links'),
            stats.get('pinned'), stats.get('skipped')))
        if stats.get('error'):
            self.set_status(stats['error'])
        else:
            self.set_status(u'Ticked categories are the only ones your next selection keeps.')

    def rebuild_list(self):
        panel = self.ctl('ListPanel')
        panel.Children.Clear()
        self.ui_rows = {}
        self.ui_sections = {}
        for section, title in core.SECTIONS:
            rows = core.rows_in(self.rows, section)
            if not rows:
                continue
            panel.Children.Add(self._section_header(section, title, rows))
            for row in rows:
                self._add_row(panel, row)
        if not self.rows:
            tb = TextBlock()
            tb.Text = u'Nothing selectable in this view.'
            tb.Margin = Thickness(10, 10, 10, 10)
            tb.SetResourceReference(TextBlock.ForegroundProperty, 'Muted')
            panel.Children.Add(tb)
        self.sync_checks()

    def _grid(self, widths):
        g = Grid()
        for w in widths:
            cd = ColumnDefinition()
            if w == '*':
                cd.Width = GridLength(1, GridUnitType.Star)
            elif w == 'auto':
                cd.Width = GridLength.Auto
            else:
                cd.Width = GridLength(w)
            g.ColumnDefinitions.Add(cd)
        return g

    def _text(self, text, key, size=12.0, bold=False):
        tb = TextBlock()
        tb.Text = text
        tb.FontSize = size
        tb.VerticalAlignment = VerticalAlignment.Center
        tb.TextTrimming = TextTrimming.CharacterEllipsis
        tb.SetResourceReference(TextBlock.ForegroundProperty, key)
        if bold:
            tb.FontWeight = FontWeights.SemiBold
        return tb

    def _section_header(self, section, title, rows):
        g = self._grid([4, 'auto', '*', 'auto'])
        g.Margin = Thickness(6, 7, 8, 2)
        tick = Border()
        tick.Width = 4
        tick.Height = 13
        tick.CornerRadius = CornerRadius(1)
        tick.SetResourceReference(Border.BackgroundProperty, core.SECTION_TICK.get(section, 'Blue'))
        Grid.SetColumn(tick, 0)
        g.Children.Add(tick)
        cb = CheckBox()
        cb.Margin = Thickness(6, 0, 0, 0)
        if section == 'tags':
            cb.ToolTip = u'Tick or untick every tag family'
        else:
            cb.ToolTip = u'Tick or untick every {0} category'.format(title.lower())
        cb.Click += self._safe(self._section_click(section, cb))
        Grid.SetColumn(cb, 1)
        g.Children.Add(cb)
        label = self._text(title.upper(), 'Muted', 11.0, True)
        label.Margin = Thickness(6, 0, 0, 0)
        Grid.SetColumn(label, 2)
        g.Children.Add(label)
        count = self._text(u'', 'Muted', 11.0)
        Grid.SetColumn(count, 3)
        g.Children.Add(count)
        self.ui_sections[section] = {'check': cb, 'header': g, 'count': count, 'rows': rows}
        return g

    def _row_frame(self, indent):
        bd = Border()
        bd.Padding = Thickness(2 + indent, 1, 8, 1)
        bd.Margin = Thickness(3, 0, 3, 0)
        bd.CornerRadius = CornerRadius(3)
        bd.Background = Brushes.Transparent
        bd.MinHeight = 21

        def enter(s, a):
            s.SetResourceReference(Border.BackgroundProperty, 'RowHover')

        def leave(s, a):
            s.Background = Brushes.Transparent
        bd.MouseEnter += self._safe(enter)
        bd.MouseLeave += self._safe(leave)
        return bd

    def _swatch(self, colour, outline=False):
        sw = Border()
        sw.Width = 10
        sw.Height = 10
        sw.CornerRadius = CornerRadius(2)
        sw.VerticalAlignment = VerticalAlignment.Center
        sw.HorizontalAlignment = HorizontalAlignment.Center
        if outline:
            sw.BorderThickness = Thickness(1.5)
            sw.SetResourceReference(Border.BorderBrushProperty, colour)
        else:
            sw.SetResourceReference(Border.BackgroundProperty, colour)
        return sw

    def _add_row(self, panel, row):
        is_tags = row['section'] == 'tags'
        bd = self._row_frame(0)
        g = self._grid([16, 'auto', 16, '*', 'auto'])
        arrow = None
        if is_tags and row['types']:
            btn = Button()
            btn.SetResourceReference(Button.StyleProperty, 'ArrowButton')
            arrow = Path()
            arrow.Data = ui.geometry(ARROW_DOWN if row['key'] in self.expanded else ARROW_RIGHT)
            arrow.SetResourceReference(Path.FillProperty, 'Muted')
            btn.Content = arrow
            btn.ToolTip = u'Show the types in this tag family'
            btn.Click += self._safe(self._arrow_click(row['key']))
            Grid.SetColumn(btn, 0)
            g.Children.Add(btn)
        cb = CheckBox()
        row_click = self._row_click(row, cb)
        cb.Click += self._safe(row_click)
        Grid.SetColumn(cb, 1)
        g.Children.Add(cb)
        sw = self._swatch(row['colour'])
        Grid.SetColumn(sw, 2)
        g.Children.Add(sw)
        name = self._text(row['name'], row['colour'], 12.0, True)
        name.Margin = Thickness(4, 0, 6, 0)
        name.ToolTip = row['name']
        if is_tags and row.get('categories'):
            name.ToolTip = u'{0}\nTag family - {1}'.format(row['name'], u', '.join(row['categories']))
        Grid.SetColumn(name, 3)
        g.Children.Add(name)
        count = self._text(str(row['count']), 'Muted', 11.0)
        Grid.SetColumn(count, 4)
        g.Children.Add(count)
        bd.Child = g
        bd.MouseLeftButtonUp += self._safe(self._frame_click(cb, row_click))
        panel.Children.Add(bd)

        kids_panel = None
        kid_ui = {}
        if is_tags and row['types']:
            kids_panel = StackPanel()
            kids_panel.Orientation = Orientation.Vertical
            open_ = row['key'] in self.expanded
            kids_panel.Visibility = Visibility.Visible if open_ else Visibility.Collapsed
            for child in row['types']:
                kid_ui[child['key']] = self._add_child(kids_panel, row, child)
            panel.Children.Add(kids_panel)
        self.ui_rows[row['key']] = {'row': row, 'border': bd, 'check': cb,
                                    'arrow': arrow, 'kids': kids_panel, 'kid_ui': kid_ui}

    def _add_child(self, panel, row, child):
        bd = self._row_frame(16)
        g = self._grid([16, 'auto', 16, '*', 'auto'])
        cb = CheckBox()
        child_click = self._child_click(row, child['key'], cb)
        cb.Click += self._safe(child_click)
        Grid.SetColumn(cb, 1)
        g.Children.Add(cb)
        sw = self._swatch(row['colour'], outline=True)
        Grid.SetColumn(sw, 2)
        g.Children.Add(sw)
        name = self._text(child['name'], 'Text', 11.5)
        name.Margin = Thickness(4, 0, 6, 0)
        name.ToolTip = child['name']
        Grid.SetColumn(name, 3)
        g.Children.Add(name)
        count = self._text(str(child['count']), 'Muted', 11.0)
        Grid.SetColumn(count, 4)
        g.Children.Add(count)
        bd.Child = g
        bd.MouseLeftButtonUp += self._safe(self._frame_click(cb, child_click))
        panel.Children.Add(bd)
        return {'border': bd, 'check': cb, 'child': child}

    # click factories (closures bound per row) ----------------------
    def _frame_click(self, cb, on_click):
        """A click anywhere on the row toggles its tick."""
        def handler(sender, args):
            cb.IsChecked = not (cb.IsChecked == True)  # noqa: E712
            on_click(cb, args)
        return handler

    def _row_click(self, row, cb):
        def handler(sender, args):
            self.state.set_row(row, cb.IsChecked == True)  # noqa: E712
            self.after_change()
        return handler

    def _child_click(self, row, key, cb):
        def handler(sender, args):
            self.state.set_child(row, key, cb.IsChecked == True)  # noqa: E712
            self.after_change()
        return handler

    def _section_click(self, section, cb):
        def handler(sender, args):
            self.state.set_all(core.rows_in(self.rows, section), cb.IsChecked == True)  # noqa: E712
            self.after_change()
        return handler

    def _arrow_click(self, key):
        def handler(sender, args):
            if key in self.expanded:
                self.expanded.discard(key)
            else:
                self.expanded.add(key)
            self.show_kids(key, key in self.expanded)
        return handler

    def show_kids(self, key, open_):
        u = self.ui_rows.get(key)
        if u is None or u['kids'] is None:
            return
        u['kids'].Visibility = Visibility.Visible if open_ else Visibility.Collapsed
        if u['arrow'] is not None:
            u['arrow'].Data = ui.geometry(ARROW_DOWN if open_ else ARROW_RIGHT)

    # ---------------------------------------------------------------
    def after_change(self):
        self.sync_checks()
        on, total = core.picking_summary(self.rows, self.state)
        if self.state.restricting():
            self.set_status(u'Next selection keeps {0} of {1} categories.'.format(on, total))
        else:
            self.set_status(u'Everything is pickable.')

    def sync_checks(self):
        for u in self.ui_rows.values():
            u['check'].IsChecked = self.state.row_on(u['row'])
            for k in u['kid_ui'].values():
                k['check'].IsChecked = k['child']['key'] not in self.state.off_tags
        for s in self.ui_sections.values():
            s['check'].IsChecked = core.section_state(s['rows'], self.state)
            on, total = core.picking_summary(s['rows'], self.state)
            s['count'].Text = u'{0}/{1}'.format(on, total)
        on, total = core.picking_summary(self.rows, self.state)
        self.ctl('CountText').Text = u'Picking {0} of {1} categories'.format(on, total)

    def apply_search(self):
        query = self.ctl('SearchBox').Text or u''
        searching = bool(query.strip())
        for key, u in self.ui_rows.items():
            row = u['row']
            row_hit = core.matches(query, row['name'])
            any_kid = False
            for k in u['kid_ui'].values():
                hit = row_hit or core.matches(query, k['child']['name'])
                k['border'].Visibility = Visibility.Visible if hit else Visibility.Collapsed
                if hit and not row_hit:
                    any_kid = True
            show = row_hit or any_kid
            u['border'].Visibility = Visibility.Visible if show else Visibility.Collapsed
            if u['kids'] is not None:
                open_ = (key in self.expanded) or (searching and any_kid)
                u['kids'].Visibility = Visibility.Visible if (show and open_) else Visibility.Collapsed
                if u['arrow'] is not None:
                    u['arrow'].Data = ui.geometry(ARROW_DOWN if open_ else ARROW_RIGHT)
        for s in self.ui_sections.values():
            vis = False
            for r in s['rows']:
                u = self.ui_rows.get(r['key'])
                if u is not None and u['border'].Visibility == Visibility.Visible:
                    vis = True
                    break
            s['header'].Visibility = Visibility.Visible if vis else Visibility.Collapsed

    def update_state_buttons(self):
        links = self.stats.get('links', 0) if self.stats else 0
        pinned = self.stats.get('pinned', 0) if self.stats else 0
        lb = self.ctl('LinksBtn')
        pb = self.ctl('PinnedBtn')
        lb.SetResourceReference(Button.BackgroundProperty, 'Green' if self.state.links_on else 'Red')
        pb.SetResourceReference(Button.BackgroundProperty, 'Green' if self.state.pinned_on else 'Red')
        lb.ToolTip = (u'Linked models ({0} in view): {1}. Click to switch.\n'
                      u'Revit and CAD links and point clouds. Revit\'s own Select links '
                      u'toggle (status bar) must also be on for links to be pickable.').format(
            links, u'pickable' if self.state.links_on else u'filtered out')
        pb.ToolTip = (u'Pinned elements ({0} in view): {1}. Click to switch.\n'
                      u'Revit\'s own Select pinned elements toggle (status bar) must also '
                      u'be on for pinned elements to be pickable.').format(
            pinned, u'pickable' if self.state.pinned_on else u'filtered out')

    def mark_stale(self, stale):
        self.stale = stale
        glyph = self.ctl('RefreshGlyph')
        glyph.SetResourceReference(Path.StrokeProperty, 'Orange' if stale else 'Text')
        self.ctl('RefreshBtn').ToolTip = (
            u'New categories have appeared since this list was read - click to refresh.'
            if stale else u'Re-read the categories in the active view')

    def set_status(self, text):
        try:
            self.ctl('StatusText').Text = text
        except Exception:
            pass

    # ---------------------------------------------------------------
    # Toolbar and footer
    # ---------------------------------------------------------------
    def on_links(self, sender, args):
        self.state.links_on = not self.state.links_on
        self.update_state_buttons()
        self.after_change()

    def on_pinned(self, sender, args):
        self.state.pinned_on = not self.state.pinned_on
        self.update_state_buttons()
        self.after_change()

    def on_all(self, sender, args):
        self.state.set_all(self.rows, True)
        self.after_change()

    def on_none(self, sender, args):
        self.state.set_all(self.rows, False)
        self.after_change()

    def on_search(self, sender, args):
        self.apply_search()

    def on_refresh(self, sender, args):
        def job(app):
            uidoc = app.ActiveUIDocument
            if uidoc is None:
                self.set_status(u'No model open.')
                return
            self.load_view(uidoc.Document, uidoc.ActiveView)
        if self.runner.run('refresh', job):
            self.set_status(u'Reading the view...')
        else:
            self.set_status(u'Revit is busy - finish the current command and refresh again.')

    def on_debug(self, sender, args):
        self.log.enabled = self.ctl('DebugCheck').IsChecked == True  # noqa: E712
        self.settings['debug'] = '1' if self.log.enabled else '0'
        core.save_settings(self.settings)

    def on_copy(self, sender, args):
        lines = [u'Selected in View {0}'.format(core.__version__),
                 u'settings: ' + core.format_settings(self.settings).replace(u'\n', u' | '),
                 u'state: off_cats={0} off_tags={1} links_on={2} pinned_on={3}'.format(
                     len(self.state.off_cats), len(self.state.off_tags),
                     self.state.links_on, self.state.pinned_on),
                 self.log.text()]
        Clipboard.SetText(u'\n'.join(lines))
        self.set_status(u'Debug copied to the clipboard.')

    # ---------------------------------------------------------------
    # Theme
    # ---------------------------------------------------------------
    def apply_theme(self):
        setting = self.settings.get('theme', 'auto')
        canvas = rv.canvas_theme(self.uiapp) if setting == 'auto' else None
        mode = core.resolve_theme(setting, canvas)
        if mode != self.mode or not self.win.Resources.Contains('WindowBg'):
            ui.apply_palette(self.win, mode)
        self.mode = mode
        self.ctl('ThemeText').Text = core.THEME_LABELS.get(setting, u'Auto')
        self.ctl('ThemeBtn').ToolTip = core.theme_tooltip(setting, mode)

    def on_theme(self, sender, args):
        self.settings['theme'] = core.next_theme(self.settings.get('theme', 'auto'))
        core.save_settings(self.settings)
        self.apply_theme()

    def on_activated(self, sender, args):
        if self.settings.get('theme', 'auto') == 'auto':
            self.apply_theme()

    # ---------------------------------------------------------------
    # Chrome: drag, logo, full screen, grips, keys, close
    # ---------------------------------------------------------------
    def on_header_down(self, sender, args):
        if args.ClickCount == 2:
            self.toggle_full()
            return
        if self.full is not None:
            self.toggle_full()
        try:
            self.win.DragMove()
        except Exception:
            pass

    def on_logo_down(self, sender, args):
        args.Handled = True
        if self.egg_shared:
            return
        if self.clicks.click(args.Timestamp):
            ui.launch_egg(self.win, self.mode)

    def on_full(self, sender, args):
        self.toggle_full()

    def toggle_full(self):
        w = self.win
        if self.full is not None:
            left, top, width, height = self.full
            self.full = None
            w.Left, w.Top, w.Width, w.Height = left, top, width, height
            return
        self.full = (w.Left, w.Top, w.Width, w.Height)
        try:
            wa = Screen.FromHandle(WindowInteropHelper(w).Handle).WorkingArea
            m = PresentationSource.FromVisual(w).CompositionTarget.TransformToDevice
            sx, sy = m.M11, m.M22
            w.Left, w.Top = wa.Left / sx, wa.Top / sy
            w.Width, w.Height = wa.Width / sx, wa.Height / sy
        except Exception:
            area = SystemParameters.WorkArea
            w.Left, w.Top, w.Width, w.Height = area.Left, area.Top, area.Width, area.Height

    def _grip_handler(self, sides):
        left, top, right, bottom = sides

        def handler(sender, args):
            w = self.win
            self.full = None
            hc = args.HorizontalChange
            vc = args.VerticalChange
            if right:
                w.Width = max(w.MinWidth, w.Width + hc)
            if bottom:
                w.Height = max(w.MinHeight, w.Height + vc)
            if left:
                new_w = max(w.MinWidth, w.Width - hc)
                w.Left = w.Left + (w.Width - new_w)
                w.Width = new_w
            if top:
                new_h = max(w.MinHeight, w.Height - vc)
                w.Top = w.Top + (w.Height - new_h)
                w.Height = new_h
        return handler

    def on_key(self, sender, args):
        if args.Key == Key.F11:
            self.toggle_full()
            args.Handled = True
        elif args.Key == Key.Escape:
            if self.full is not None:
                self.toggle_full()
            else:
                self.ctl('SearchBox').Text = u''
            args.Handled = True

    def _restore_bounds(self):
        s = self.settings
        left = core.to_float(s.get('left'))
        top = core.to_float(s.get('top'))
        width = core.to_float(s.get('width'))
        height = core.to_float(s.get('height'))
        if width and width >= self.win.MinWidth:
            self.win.Width = width
        if height and height >= self.win.MinHeight:
            self.win.Height = height
        if left is None or top is None:
            # first run: top right of the working area, clear of the ribbon
            area = SystemParameters.WorkArea
            self.win.Left = area.Right - self.win.Width - 40
            self.win.Top = area.Top + 150
            return
        vl = SystemParameters.VirtualScreenLeft
        vt = SystemParameters.VirtualScreenTop
        vr = vl + SystemParameters.VirtualScreenWidth
        vb = vt + SystemParameters.VirtualScreenHeight
        if vl <= left <= vr - 80 and vt <= top <= vb - 60:
            self.win.Left = left
            self.win.Top = top

    def on_close(self, sender, args):
        self.win.Close()

    def on_closed(self, sender, args):
        self.shutdown()

    def shutdown(self):
        if self.closed:
            return
        self.closed = True
        self.unhook()
        if self.full is not None:
            self.toggle_full()
        try:
            self.settings['left'] = str(int(self.win.Left))
            self.settings['top'] = str(int(self.win.Top))
            self.settings['width'] = str(int(self.win.Width))
            self.settings['height'] = str(int(self.win.Height))
        except Exception:
            pass
        core.save_settings(self.settings)
        self.runner.dispose()
        saved = _domain_get(WIN_KEY)
        try:
            if saved is not None and saved[1] is self.win:
                _domain_set(WIN_KEY, None)
        except Exception:
            _domain_set(WIN_KEY, None)
        if self in _KEEP_ALIVE:
            _KEEP_ALIVE.remove(self)
        self.log.add(u'closed - selection back to normal')

    # ---------------------------------------------------------------
    def show(self):
        uidoc = self.uiapp.ActiveUIDocument
        if uidoc is not None:
            self.load_view(uidoc.Document, uidoc.ActiveView)
        self.hook()
        _domain_set(WIN_KEY, (core.__version__, self.win))
        _KEEP_ALIVE.append(self)
        self.win.Show()
        self.win.Activate()


def launch(uiapp, folder):
    """Bring an open window forward, or open a new one."""
    existing = _domain_get(WIN_KEY)
    if existing is not None:
        try:
            if existing[0] == core.__version__ and existing[1].IsVisible:
                existing[1].Activate()
                return None
            existing[1].Close()
        except Exception:
            pass
        _domain_set(WIN_KEY, None)
    ctl = Controller(uiapp, folder)
    ctl.show()
    return ctl
