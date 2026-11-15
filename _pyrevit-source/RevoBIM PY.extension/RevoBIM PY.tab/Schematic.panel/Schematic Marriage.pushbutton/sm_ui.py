# -*- coding: utf-8 -*-
"""Schematic Marriage - main window, shared state and the ExternalEvent runner.

Modeless: Revit stays usable while the window is open. Every read and write
of the document goes out through one ExternalEvent and comes back through a
callback - the window never waits on the event it raised (that deadlocks).
"""
import sm_clr  # noqa: F401  (must stay first - references the assemblies)

import io
import os
import traceback

from System import AppDomain, EventHandler
from System.Windows import GridLength, GridUnitType, Visibility
from System.Windows.Controls import DataGridRow, TextBlock, TextBox
from System.Windows.Input import Keyboard, ModifierKeys, Key
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Media import VisualTreeHelper

from Autodesk.Revit.UI import ExternalEvent, IExternalEventHandler
from Autodesk.Revit.DB.Events import DocumentChangedEventArgs

import sm_store as store
import sm_revit as rv
import sm_wpf as ui
from sm_store import to_text
from sm_version import __version__

LIVE_KEY = 'RevoBIM.SchematicMarriage.window.' + __version__
DOT = u'  \u00b7  '


# ==========================================================================
# ExternalEvent runner
# ==========================================================================

class _Handler(IExternalEventHandler):
    def __init__(self, runner):
        self.runner = runner

    def Execute(self, uiapp):
        try:
            self.runner.execute(uiapp)
        except Exception:
            self.runner.state.debug(u'runner crashed:\n' + to_text(traceback.format_exc()))

    def GetName(self):
        return 'RevoBIM Schematic Marriage'


class Runner(object):
    """Queue jobs, raise once, run them all in API context.
    A Pending answer means an earlier request is still waiting: the job is
    kept and runs with it. Only a refused job is dropped."""

    def __init__(self, state):
        self.state = state
        self.queue = []
        self.busy = False
        self.handler = _Handler(self)
        self.event = ExternalEvent.Create(self.handler)
        self.watchdog = ui.Debounce(20000, self._watchdog)

    def submit(self, label, work, done=None, quiet=False):
        job = (label, work, done, quiet)
        self.queue.append(job)
        try:
            answer = to_text(self.event.Raise())
        except Exception as ex:
            answer = u'error: ' + to_text(ex)
        if answer in (u'Accepted', u'Pending'):
            if not quiet:
                self._busy(True)
                self.watchdog.poke()
            return True
        try:
            self.queue.remove(job)
        except ValueError:
            pass
        self.state.status(u'Revit did not accept the request ({0}) - try again.'.format(answer), u'bad')
        return False

    def execute(self, uiapp):
        while self.queue:
            label, work, done, quiet = self.queue.pop(0)
            result, error = None, None
            try:
                result = work(uiapp)
            except rv.PickCancelled:
                error = u'cancelled'
            except Exception:
                error = to_text(traceback.format_exc())
                self.state.debug(u'job "{0}" failed:\n{1}'.format(label, error))
            if done is not None:
                try:
                    done(result, error)
                except Exception:
                    self.state.debug(u'callback for "{0}" failed:\n{1}'.format(
                        label, to_text(traceback.format_exc())))
        self._busy(False)

    def _watchdog(self):
        # Revit has not run the request in 20s (a command or dialog is open in
        # Revit). Free the window rather than leave it looking frozen; the job
        # stays queued and runs when Revit is idle again.
        if self.busy and self.queue:
            self._busy(False)
            self.state.status(u'Revit has not picked up the request yet - finish or Esc out of what Revit '
                              u'is doing and it will run.', u'warn')
            self.state.debug(u'watchdog freed the window with {0} job(s) queued'.format(len(self.queue)))

    def _busy(self, on):
        if not on:
            self.watchdog.stop()
        self.busy = on
        for w in self.state.windows():
            try:
                w.set_busy(on)          # body deaf, shrink-to-taskbar stays live
            except Exception:
                pass


# ==========================================================================
# shared state
# ==========================================================================

class State(object):
    def __init__(self, uiapp):
        self.uiapp = uiapp
        self.doc = uiapp.ActiveUIDocument.Document
        self.settings = store.load_settings()
        self.marriages = []
        self.templates = []
        self.main = None
        self.tpl_win = None
        self.log = []
        self.hl = {}          # magenta highlight registry, see sm_revit.highlight
        self.cat_cache = None  # template editor categories, read once per session
        self.runner = Runner(self)

    def windows(self):
        return [w for w in (self.main, self.tpl_win) if w is not None]

    def templates_by_id(self):
        return dict((t.id, t) for t in self.templates)

    def template_name(self, tid):
        for t in self.templates:
            if t.id == tid:
                return t.name
        return u''

    def recount(self):
        store.apply_usage(self.templates, self.marriages)

    def status(self, text, kind=u''):
        if self.main is not None:
            self.main.status(text, kind)

    def debug(self, text):
        self.log.append(u'[{0}] {1}'.format(store.now_text(), to_text(text)))
        if self.settings.get(u'debug') == u'1':
            self.flush_debug()

    def flush_debug(self):
        try:
            folder = store.settings_dir()
            if not os.path.isdir(folder):
                os.makedirs(folder)
            with io.open(store.debug_path(), 'a', encoding='utf-8') as fh:
                for line in self.log:
                    fh.write(to_text(line) + u'\n')
            self.log = []
        except Exception:
            pass

    def save_settings(self):
        store.save_settings(self.settings)

    def cycle_theme(self):
        self.settings[u'theme'] = store.next_theme(self.settings.get(u'theme', u'follow'))
        self.save_settings()
        self.apply_theme_everywhere()

    def apply_theme_everywhere(self):
        for w in self.windows():
            try:
                w.apply_theme()
            except Exception:
                pass

    def data_changed(self):
        """Marriages or templates changed: recount and repaint both windows."""
        self.recount()
        if self.main is not None:
            self.main.refresh()
        if self.tpl_win is not None:
            self.tpl_win.refresh_list()


# ==========================================================================
# main window
# ==========================================================================

COLUMNS = [
    # key,       header,                 star, min, side
    (u'no',      u'#',                   0.35, 40,  None),
    (u'src_cat', u'Source category',     1.0,  110, u'BlueBrush'),
    (u'src',     u'Source family : type', 1.7, 170, u'BlueBrush'),
    (u'src_id',  u'Source ID',           0.6,  80,  u'BlueBrush'),
    (u'tgt_cat', u'Target category',     1.0,  110, u'OrangeBrush'),
    (u'tgt',     u'Target family : type', 1.7, 170, u'OrangeBrush'),
    (u'tgt_id',  u'Target ID',           0.6,  80,  u'OrangeBrush'),
    (u'template', u'Parameter Push Template', 1.4, 180, None),
    (u'status',  u'Last update',         1.1,  140, None),
]


class MainWindow(ui.ThemedWindow):
    XAML = 'SchematicMarriage.xaml'

    def __init__(self, state):
        self.src = None
        self.tgt = None
        self.view_rows = []
        self.sort_key = None
        self.sort_desc = False
        self.col_filters = {}
        self.filter_boxes = {}
        self.last_tpl_for_pair = {}
        self._suspend = False
        self._watch_ids = set()
        self.undo = store.UndoStack()
        ui.ThemedWindow.__init__(self, state)
        self.grid = self.n('GridMarriages')
        self.text_conv = ui.FuncConverter(self._cell_text)
        self.brush_conv = ui.FuncConverter(self._cell_brush)
        self.bg_conv = ui.FuncConverter(self._template_bg)
        self.tip_conv = ui.FuncConverter(self._cell_tip)
        self.border_conv = ui.FuncConverter(self._template_border)
        self._build_columns()
        self.search_later = ui.Debounce(220, self.refilter, self._error)
        self.reload_later = ui.Debounce(1200, self.reload_from_model, self._error)
        self._wire()
        self._dc = EventHandler[DocumentChangedEventArgs](self._on_doc_changed)
        try:
            state.uiapp.Application.DocumentChanged += self._dc
        except Exception:
            self._dc = None
        try:
            self.win.Width = float(state.settings.get(u'main_w') or 1220)
            self.win.Height = float(state.settings.get(u'main_h') or 780)
        except Exception:
            pass
        self.n('ChkDebug').IsChecked = state.settings.get(u'debug') == u'1'

    # ---- building ---------------------------------------------------------
    def _build_columns(self):
        for key, title, star, minw, brush_key in COLUMNS:
            header, box = ui.header_with_filter(title, brush_key, self._on_filter_changed,
                                                filters=(key != u'no'))
            if box is not None:
                self.filter_boxes[key] = box
            if key == u'template':
                col = ui.button_column(header, key, self.text_conv, self._on_template_cell,
                                       star, minw, self.brush_conv, self.bg_conv, self.border_conv)
            else:
                col = ui.text_column(header, key, self.text_conv, star, minw, self.brush_conv, tip_conv=self.tip_conv,
                                     bold=(key in (u'src', u'tgt')))
            self.grid.Columns.Add(col)

    def _wire(self):
        self.n('BtnPickSrc').Click += lambda s, a: self.pick(u'src')
        self.n('BtnPickTgt').Click += lambda s, a: self.pick(u'tgt')
        self.n('BtnClearSrc').Click += lambda s, a: self.set_pick(u'src', None)
        self.n('BtnClearTgt').Click += lambda s, a: self.set_pick(u'tgt', None)
        self.n('BtnAdd').Click += lambda s, a: self.add_marriage()
        self.n('BtnRemove').Click += lambda s, a: self.remove_selected()
        self.n('BtnSetTpl').Click += lambda s, a: self._set_template_for_selected()
        self.n('BtnUndo').Click += lambda s, a: self.do_undo()
        self.n('BtnRedo').Click += lambda s, a: self.do_redo()
        self.n('BtnApply').Click += lambda s, a: self.apply_changes()
        self.win.PreviewKeyDown += self._on_preview_key
        self.n('BtnHighlight').Click += lambda s, a: self.highlight_selected()
        self.n('BtnClearHl').Click += lambda s, a: self.release_highlight(None)
        self.n('BtnIsolate').Click += lambda s, a: self.isolate_selected()
        self.n('BtnUpdate').Click += lambda s, a: self.update_data()
        self.n('BtnTemplates').Click += lambda s, a: self.open_templates(None)
        self.n('TxtSearch').TextChanged += lambda s, a: self.search_later.poke()
        self.n('ChkDebug').Click += self._on_debug
        self.n('CmbNewTpl').SelectionChanged += self._on_new_tpl
        self.grid.Sorting += self._on_sorting
        self.grid.SelectionChanged += lambda s, a: self._selection_changed()
        self.grid.MouseDoubleClick += self._on_double_click
        self.grid.MouseRightButtonUp += self._on_right_click
        self.win.Closing += self._on_closing
        self.win.Closed += self._on_closed

    def _error(self, text):
        self.state.debug(text)
        self.status(u'Something went wrong - tick Debug and send the report.', u'bad')

    # ---- cells ------------------------------------------------------------
    def _cell_text(self, row, key):
        key = to_text(key)
        if key == u'no':
            return to_text(getattr(row, 'no', u''))
        if key == u'template':
            if not row.template_id:
                return u'+ Assign template' + (u'   \u2022 cleared, not applied' if row.pending() else u'')
            name = self.state.template_name(row.template_id) or u'(template deleted)'
            return name + u'   \u2022 not applied' if row.pending() else name
        if key == u'src' and row.src_view:
            return row.src_label + u'   [' + row.src_view + u']'
        if key == u'tgt' and row.tgt_view:
            return row.tgt_label + u'   [' + row.tgt_view + u']'
        return row.value(key)

    def _cell_tip(self, row, key):
        """The full description shown under a cell that is cut short."""
        key = to_text(key)
        if key.startswith(u'src') or key.startswith(u'tgt'):
            side = u'src' if key.startswith(u'src') else u'tgt'
            cat = row.src_cat_name if side == u'src' else row.tgt_cat_name
            label = row.src_label if side == u'src' else row.tgt_label
            eid = row.src_eid if side == u'src' else row.tgt_eid
            view = row.src_view if side == u'src' else row.tgt_view
            lines = [u'{0}: {1}'.format(u'Source' if side == u'src' else u'Target', label),
                     u'Category: ' + cat]
            if eid:
                lines.append(u'Element ID: ' + eid)
            if view:
                lines.append(u'Drawn in view: ' + view)
            if (row.src_missing if side == u'src' else row.tgt_missing):
                lines.append(u'This element is no longer in the model.')
            return ui.tip_block(u'\n'.join(lines))
        if key == u'status' and row.status:
            return ui.tip_block(u'Last update: ' + row.status)
        return ui.tip_block(self._cell_text(row, key))

    def _template_bg(self, row, key):
        """An assigned template reads as a raised blue button; unassigned stays plain;
        a staged (not applied) change is orange."""
        res = self.win.Resources
        if row.pending():
            return res['OrangeSoftBrush']
        if row.template_id and self.state.template_name(row.template_id):
            return res['BlueSoftBrush']
        return res['FieldBrush']

    def _template_border(self, row, key):
        res = self.win.Resources
        if row.pending():
            return res['OrangeBrush']
        if row.template_id and self.state.template_name(row.template_id):
            return res['BlueBrush']
        if row.template_id:
            return res['RedBrush']
        return res['EdgeBrush']

    def _cell_brush(self, row, key):
        key = to_text(key)
        res = self.win.Resources
        if key.startswith(u'src') and row.src_missing:
            return res['RedBrush']
        if key.startswith(u'tgt') and row.tgt_missing:
            return res['RedBrush']
        if key == u'template':
            if row.pending():
                return res['OrangeBrush']
            if not row.template_id:
                return res['MutedBrush']
            if not self.state.template_name(row.template_id):
                return res['RedBrush']
            return res['BlueBrush']
        if key == u'status':
            kind = row.status_kind
            if kind == u'bad':
                return res['RedBrush']
            if kind == u'warn':
                return res['OrangeBrush']
            if kind == u'ok':
                return res['GreenBrush']
            return res['MutedBrush']
        if key == u'no':
            return res['MutedBrush']
        return res['TextBrush']   # never Unset: that falls to WPF's default, not the theme

    # ---- status -----------------------------------------------------------
    def status(self, text, kind=u''):
        try:
            t = self.n('TxtStatus')
            t.Text = to_text(text)
            key = {u'bad': 'RedBrush', u'warn': 'OrangeBrush', u'ok': 'GreenBrush'}.get(kind, 'MutedBrush')
            t.SetResourceReference(TextBlock.ForegroundProperty, key)
        except Exception:
            pass

    def progress(self, done, total):
        band = self.n('ProgressBand')
        if total <= 0:
            band.Visibility = Visibility.Collapsed
            return
        band.Visibility = Visibility.Visible
        frac = max(0.0, min(1.0, float(done) / float(total)))
        self.n('ColFill').Width = GridLength(frac, GridUnitType.Star)
        self.n('ColRest').Width = GridLength(1.0 - frac, GridUnitType.Star)
        self.n('TxtProgress').Text = u'{0}%  -  {1} of {2} left'.format(
            int(round(frac * 100)), total - done, total)
        ui.do_events()

    # ---- refresh / filter / sort -----------------------------------------
    def refresh(self):
        for i, m in enumerate(self.state.marriages, 1):
            m.no = i
        self._rebuild_watch()
        self.refilter()
        self._update_buttons()
        self._fill_new_template_combo()

    def _row_values(self, m):
        vals = [m.value(k) for k in (u'src_cat', u'src', u'src_id', u'tgt_cat', u'tgt', u'tgt_id', u'status')]
        vals.append(self.state.template_name(m.template_id))
        vals.append(m.src_view)
        vals.append(m.tgt_view)
        return u' '.join(vals)

    def _passes(self, m, search):
        for key, text in self.col_filters.items():
            if not text:
                continue
            value = self.state.template_name(m.template_id) if key == u'template' else self._cell_text(m, key)
            if not store.matches_keywords(value, text):
                return False
        if search and not store.matches_keywords(self._row_values(m), search):
            return False
        return True

    def refilter(self):
        search = to_text(self.n('TxtSearch').Text)
        rows = [m for m in self.state.marriages if self._passes(m, search)]
        if self.sort_key:
            key = self.sort_key
            if key == u'no':
                rows.sort(key=lambda m: m.no, reverse=self.sort_desc)
            elif key == u'template':
                rows.sort(key=lambda m: store.natural_key(self.state.template_name(m.template_id)),
                          reverse=self.sort_desc)
            else:
                rows.sort(key=lambda m: store.natural_key(m.value(key)), reverse=self.sort_desc)
        self.view_rows = rows
        self.grid.ItemsSource = ui.items(rows)
        total = len(self.state.marriages)
        assigned = len([m for m in self.state.marriages if m.template_id])
        text = u'{0} in this model{1}{2} with a template'.format(total, DOT, assigned)
        if len(rows) != total:
            text += DOT + u'showing {0}'.format(len(rows))
        self.n('TxtCount').Text = text
        self._selection_changed()

    def _on_filter_changed(self, sender, args):
        for key, box in self.filter_boxes.items():
            self.col_filters[key] = to_text(box.Text)
        self.search_later.poke()

    def _on_sorting(self, sender, args):
        args.Handled = True
        key = to_text(args.Column.SortMemberPath)
        if self.sort_key == key:
            self.sort_desc = not self.sort_desc
        else:
            self.sort_key = key
            self.sort_desc = False
        for c in self.grid.Columns:
            c.SortDirection = None
        args.Column.SortDirection = ui.sort_direction(self.sort_desc)
        self.refilter()

    def selected_rows(self):
        return [r for r in self.grid.SelectedItems]

    def _selection_changed(self):
        rows = self.selected_rows()
        btn = self.n('BtnRemove')
        btn.IsEnabled = bool(rows)
        self.n('BtnHighlight').IsEnabled = bool(rows)
        self.n('BtnIsolate').IsEnabled = bool(rows)
        self.n('TxtRemove').Text = (u'Remove Selected ({0})'.format(len(rows)) if rows
                                    else u'Remove Selected')
        self.n('BtnSetTpl').IsEnabled = bool(rows)
        self.n('TxtSetTpl').Text = (u'Set Template ({0})'.format(len(rows)) if rows else u'Set Template')
        if len(rows) > 1 and not self.state.runner.busy:
            self.status(u'{0} selected - choosing a template on any selected row sets all {0}.'.format(len(rows)))

    def _update_buttons(self):
        pending = len(store.pending_marriages(self.state.marriages))
        self.n('BtnApply').IsEnabled = pending > 0
        self.n('TxtApply').Text = u'Apply Changes ({0})'.format(pending) if pending else u'Apply Changes'
        self._update_undo_buttons()
        assigned = len([m for m in self.state.marriages if m.template_id])
        btn = self.n('BtnUpdate')
        btn.IsEnabled = assigned > 0
        self.n('TxtUpdate').Text = (u'Update Data ({0})'.format(assigned) if assigned
                                    else u'Update Data')
        self.n('BtnAdd').IsEnabled = self.src is not None and self.tgt is not None

    def after_theme(self):
        try:
            self.grid.Items.Refresh()
        except Exception:
            pass

    # ---- picking ----------------------------------------------------------
    def _doc_ok(self, uiapp):
        try:
            return uiapp.ActiveUIDocument.Document.Equals(self.state.doc)
        except Exception:
            return False

    def pick(self, which):
        label = u'SOURCE element' if which == u'src' else u'TARGET element (or detail item)'
        prompt = u'Schematic Marriage: click the {0}. Esc cancels.'.format(label)
        doc_title = to_text(self.state.doc.Title)

        def work(uiapp):
            if not self._doc_ok(uiapp):
                raise Exception(u'Switch back to {0} to pick.'.format(doc_title))
            uidoc = uiapp.ActiveUIDocument
            e, how = rv.pick_element(uidoc, prompt)
            doc = uidoc.Document
            rv.release(doc, self.state.hl, which)
            painted = rv.highlight(doc, uidoc.ActiveView, [e], self.state.hl, which)
            return rv.describe(doc, e), how, painted, rv.elem_name(uidoc.ActiveView)

        def done(result, error):
            try:
                self.win.Activate()
            except Exception:
                pass
            if error == u'cancelled':
                self.status(u'Pick cancelled.')
                return
            if error:
                self.status(error.strip().splitlines()[-1], u'bad')
                return
            d, how, painted, view_name = result
            d['how'] = how
            self.set_pick(which, d)
            self._update_hl_button()
            text = u'{0} set{1}'.format(u'Source' if which == u'src' else u'Target',
                                        u' from the selection in Revit' if how == u'selection' else u'')
            n, problem = painted
            if n:
                self.status(text + u' - shown magenta in "{0}" until the pick is cleared or added.'.format(
                    view_name), u'ok')
            else:
                self.status(text + u' - could not highlight it in this view ({0}).'.format(
                    problem or u'not drawn here'), u'warn')

        self.status(u'Pick the {0} in Revit (Esc cancels)...'.format(label.lower()), u'warn')
        self.state.runner.submit(u'pick ' + which, work, done)

    def set_pick(self, which, d):
        if which == u'src':
            self.src = d
            prefix, clear = u'TxtSrc', u'BtnClearSrc'
            empty = (u'Nothing picked', u'Pick the element whose values you want to push',
                     u'model element - values are read from here')
        else:
            self.tgt = d
            prefix, clear = u'TxtTgt', u'BtnClearTgt'
            empty = (u'Nothing picked', u'Pick the element that should receive the values',
                     u'model element or detail item - values are written here')
        if d is None:
            self.release_highlight(which)
            self.n(prefix + u'Cat').Text = empty[0]
            self.n(prefix + u'Name').Text = empty[1]
            self.n(prefix + u'Meta').Text = empty[2]
            self.n(clear).IsEnabled = False
        else:
            self.n(prefix + u'Cat').Text = d['cat_name']
            self.n(prefix + u'Name').Text = d['label']
            meta = u'ID ' + d['eid']
            if d.get('view'):
                meta += DOT + u'view: ' + d['view']
            if d.get('how') == u'selection':
                meta += DOT + u'taken from the selection'
            self.n(prefix + u'Meta').Text = meta
            self.n(clear).IsEnabled = True
        self._update_buttons()
        self._fill_new_template_combo()

    def _pair(self):
        if self.src is None or self.tgt is None:
            return None
        return (self.src['cat_id'], self.tgt['cat_id'])

    def _fill_new_template_combo(self):
        cmb = self.n('CmbNewTpl')
        self._suspend = True
        try:
            cmb.Items.Clear()
            pair = self._pair()
            self._new_tpl_ids = [u'']
            cmb.Items.Add(u'(No template yet)')
            if pair is None:
                cmb.SelectedIndex = 0
                cmb.IsEnabled = False
                return
            compat = [t for t in self.state.templates if store.is_compatible(t, pair[0], pair[1])]
            compat.sort(key=lambda t: store.natural_key(t.name))
            for t in compat:
                cmb.Items.Add(t.name)
                self._new_tpl_ids.append(t.id)
            cmb.IsEnabled = True
            want = self.last_tpl_for_pair.get(pair)
            if want is None and len(compat) == 1:
                want = compat[0].id
            cmb.SelectedIndex = self._new_tpl_ids.index(want) if want in self._new_tpl_ids else 0
        finally:
            self._suspend = False

    def _on_new_tpl(self, sender, args):
        if self._suspend:
            return
        pair = self._pair()
        idx = self.n('CmbNewTpl').SelectedIndex
        if pair is not None and 0 <= idx < len(self._new_tpl_ids):
            self.last_tpl_for_pair[pair] = self._new_tpl_ids[idx]

    # ---- marriages --------------------------------------------------------
    def add_marriage(self):
        if self.src is None or self.tgt is None:
            return
        if self.src['uid'] == self.tgt['uid']:
            self.status(u'Source and target are the same element - pick two different ones.', u'bad')
            return
        clash = store.pair_exists(self.state.marriages, self.src['uid'], self.tgt['uid'])
        if clash is not None:
            self.status(u'Already married (row {0}).'.format(getattr(clash, 'no', u'?')), u'warn')
            return
        m = store.Marriage()
        m.src_uid, m.tgt_uid = self.src['uid'], self.tgt['uid']
        m.src_cat_id, m.src_cat_name = self.src['cat_id'], self.src['cat_name']
        m.tgt_cat_id, m.tgt_cat_name = self.tgt['cat_id'], self.tgt['cat_name']
        idx = self.n('CmbNewTpl').SelectedIndex
        if 0 < idx < len(self._new_tpl_ids):
            m.template_id = self._new_tpl_ids[idx]
        others = len([x for x in self.state.marriages if x.tgt_uid == m.tgt_uid])

        def work(uiapp):
            rep = rv.save_records(self.state.doc, u'add marriage', creates=[(store.KIND_MARRIAGE, m)])
            if m in rep['done']:
                rv.resolve(self.state.doc, [m])
            return rep

        def done(rep, error):
            if error:
                self.status(u'Could not add the marriage - see debug.', u'bad')
                return
            if m not in rep['done']:
                reason = rep['failed'][0][1] if rep['failed'] else u'unknown'
                self.status(u'Not added: ' + reason, u'bad')
                return
            self.state.marriages.append(m)
            self.set_pick(u'src', None)
            self.set_pick(u'tgt', None)
            self.state.data_changed()
            try:
                self.grid.SelectedItem = m
                self.grid.ScrollIntoView(m)
            except Exception:
                pass
            note = u''
            if others:
                note = u'  Note: that target already receives values from {0} other source(s).'.format(others)
            self.status(u'Marriage {0} added.{1}'.format(m.no, note), u'warn' if others else u'ok')

        self.state.runner.submit(u'add marriage', work, done)

    def remove_selected(self):
        rows = self.selected_rows()
        if not rows:
            return
        r = ui.prompt(self, u'Remove marriages',
                      u'Remove {0} marriage(s) from this model\'s database?\n\n'
                      u'The elements themselves are not changed, and values already pushed stay where they are.'
                      .format(len(rows)), ok=u'Remove', danger=True)
        if not r.get('ok'):
            return

        def work(uiapp):
            return rv.save_records(self.state.doc, u'remove marriages', deletes=rows)

        def done(rep, error):
            if error:
                self.status(u'Remove failed - see debug.', u'bad')
                return
            gone = set(id(x) for x in rep['done'])
            self.state.marriages = [x for x in self.state.marriages if id(x) not in gone]
            self.state.data_changed()
            if rep['failed']:
                self.status(u'Removed {0}; {1} not removed ({2}).'.format(
                    len(rep['done']), len(rep['failed']), rep['failed'][0][1]), u'bad')
            else:
                self.status(u'Removed {0} marriage(s).'.format(len(rep['done'])), u'ok')

        self.state.runner.submit(u'remove marriages', work, done)

    # ---- template cell ----------------------------------------------------
    def _on_template_cell(self, sender, args):
        try:
            row = sender.DataContext
            mods = Keyboard.Modifiers
            # the cell is a button, so it would swallow Ctrl / Shift clicks -
            # treat them as selection, the way the rest of the row behaves
            if (mods & ModifierKeys.Control) == ModifierKeys.Control:
                if row in self.selected_rows():
                    self.grid.SelectedItems.Remove(row)
                else:
                    self.grid.SelectedItems.Add(row)
                return
            if (mods & ModifierKeys.Shift) == ModifierKeys.Shift:
                sel = self.selected_rows()
                anchor = sel[0] if sel else row
                a = self.view_rows.index(anchor) if anchor in self.view_rows else 0
                b = self.view_rows.index(row)
                for r in self.view_rows[min(a, b):max(a, b) + 1]:
                    if r not in self.grid.SelectedItems:
                        self.grid.SelectedItems.Add(r)
                return
            sel = self.selected_rows()
            rows = sel if (row in sel and len(sel) > 1) else [row]
            if row not in sel:
                self.grid.SelectedItem = row
            self.template_menu(rows, sender)
        except Exception:
            self._error(to_text(traceback.format_exc()))

    def _set_template_for_selected(self):
        rows = self.selected_rows()
        if rows:
            self.template_menu(rows, self.n('BtnSetTpl'))

    def template_menu(self, rows, target):
        menu = self.menu()
        pairs = set((m.src_cat_id, m.tgt_cat_id) for m in rows)
        first = rows[0]
        if len(pairs) > 1:
            self.menu_add(menu, u'The selected marriages are for different categories.', enabled=False,
                          brush_key='OrangeBrush')
            self.menu_add(menu, u'Select rows with the same source and target categories.', enabled=False)
            self.menu_add(menu, u'(No template)  - clear', lambda s, a: self.assign(rows, u''))
        else:
            head = u'{0}  >  {1}'.format(first.src_cat_name, first.tgt_cat_name)
            if len(rows) > 1:
                head += u'   ({0} marriages)'.format(len(rows))
            self.menu_add(menu, head, enabled=False, brush_key='MutedBrush', bold=True)
            compat = store.compatible_templates(self.state.templates, rows)
            if not compat:
                self.menu_add(menu, u'No templates for these categories yet.', enabled=False,
                              brush_key='OrangeBrush')
            for t in compat:
                mark = u'\u2713  ' if all(m.template_id == t.id for m in rows) else u'     '
                label = u'{0}{1}   ({2} pushes, used {3})'.format(mark, t.name, len(t.mappings), t.used)
                self.menu_add(menu, label, self._assign_handler(rows, t.id), brush_key='BlueBrush')
            self.menu_add(menu, u'     (No template)', lambda s, a: self.assign(rows, u''))
            self.menu_add(menu, u'+   New template for {0}...'.format(head.split(u'   (')[0]),
                          lambda s, a: self.open_templates(prefill=first), brush_key='GreenBrush')
        menu.PlacementTarget = target
        menu.IsOpen = True

    def _assign_handler(self, rows, tid):
        return lambda s, a: self.assign(rows, tid)

    def assign(self, rows, tid):
        """Stage the change - nothing reaches the model until Apply Changes."""
        changed = [m for m in rows if m.template_id != tid]
        if not changed:
            return
        before = store.template_snapshot(changed)
        for m in changed:
            m.template_id = tid
        name = self.state.template_name(tid) or u'no template'
        self.undo.push(u'set {0} to "{1}"'.format(
            u'{0} marriages'.format(len(changed)) if len(changed) > 1 else u'marriage {0}'.format(
                getattr(changed[0], 'no', u'')), name),
            before, store.template_snapshot(changed))
        self.state.data_changed()
        self.status(u'{0} marriage(s) set to "{1}" - not applied yet (Apply Changes, Ctrl+Z to undo).'.format(
            len(changed), name), u'warn')

    # ---- undo / redo / apply -------------------------------------------------
    def do_undo(self):
        step = self.undo.undo()
        if step is None:
            self.status(u'Nothing to undo.')
            return
        label, snap = step
        store.restore_templates(self.state.marriages, snap)
        self.state.data_changed()
        self.status(u'Undone: ' + label, u'warn')

    def do_redo(self):
        step = self.undo.redo()
        if step is None:
            self.status(u'Nothing to redo.')
            return
        label, snap = step
        store.restore_templates(self.state.marriages, snap)
        self.state.data_changed()
        self.status(u'Redone: ' + label, u'warn')

    def _update_undo_buttons(self):
        u = self.undo
        self.n('BtnUndo').IsEnabled = u.can_undo()
        self.n('BtnRedo').IsEnabled = u.can_redo()
        self.n('BtnUndo').ToolTip = (u'Undo (Ctrl+Z): ' + u.next_undo_label()) if u.can_undo() else u'Nothing to undo'
        self.n('BtnRedo').ToolTip = (u'Redo (Ctrl+Y): ' + u.next_redo_label()) if u.can_redo() else u'Nothing to redo'

    def _on_preview_key(self, sender, args):
        """Ctrl+Z / Ctrl+Y undo template assignments - unless a text box has
        focus, where they belong to the text box."""
        if (Keyboard.Modifiers & ModifierKeys.Control) != ModifierKeys.Control:
            return
        if isinstance(Keyboard.FocusedElement, TextBox):
            return
        if args.Key == Key.Z and (Keyboard.Modifiers & ModifierKeys.Shift) == ModifierKeys.Shift:
            self.do_redo()
            args.Handled = True
        elif args.Key == Key.Z:
            self.do_undo()
            args.Handled = True
        elif args.Key == Key.Y:
            self.do_redo()
            args.Handled = True
        elif args.Key == Key.S:
            self.apply_changes()
            args.Handled = True

    def apply_changes(self, then=None):
        """Write every staged template change. then(ok) runs afterwards."""
        pending = store.pending_marriages(self.state.marriages)
        if not pending:
            if then is not None:
                then(True)
            return

        def work(uiapp):
            return rv.save_records(self.state.doc, u'apply template changes', updates=pending)

        def done(rep, error):
            failed = [(m, u'error') for m in pending] if error else rep['failed']
            self.state.data_changed()
            if failed:
                self.status(u'{0} applied, {1} not ({2}) - they stay staged.'.format(
                    len(pending) - len(failed), len(failed), failed[0][1]), u'bad')
                if error:
                    self.debug_report(u'Apply Changes FAILED', [error])
            else:
                self.status(u'{0} template change(s) applied to the model.'.format(len(pending)), u'ok')
            if then is not None:
                then(not failed)

        self.status(u'Applying {0} change(s)...'.format(len(pending)), u'warn')
        self.state.runner.submit(u'apply changes', work, done)

    def ask_to_apply(self, action):
        """-> 'apply', 'skip' or 'cancel' when there are staged changes, else 'none'."""
        pending = store.pending_marriages(self.state.marriages)
        if not pending:
            return u'none'
        msg = (u'{0} template change(s) have not been applied to the model yet.\n\n'
               u'Would you like to apply them before {1}?').format(len(pending), action)
        tw = self.state.tpl_win
        if tw is not None and tw.dirty and tw.edit is not None:
            msg += (u'\n\nThe template "{0}" also has unsaved edits - {1} uses its last saved '
                    u'version.').format(tw.edit.name, action)
        r = ui.prompt(self, u'Apply changes?', msg, ok=u'Apply and continue', cancel=u'Cancel',
                      alt=u'Continue without')
        if r.get('ok'):
            return u'apply'
        if r.get('alt'):
            return u'skip'
        return u'cancel'

    # ---- show in Revit ------------------------------------------------------
    def _column_key_at_current(self):
        try:
            col = self.grid.CurrentColumn
            return to_text(col.SortMemberPath) if col is not None else u''
        except Exception:
            return u''

    def _on_double_click(self, sender, args):
        row = self.grid.SelectedItem
        if row is None:
            return
        key = self._column_key_at_current()
        if key == u'template':
            return
        self.show(row, u'tgt' if key.startswith(u'tgt') else u'src')

    def show(self, row, which):
        uid = row.src_uid if which == u'src' else row.tgt_uid

        def work(uiapp):
            if not self._doc_ok(uiapp):
                raise Exception(u'Switch back to the model this window belongs to.')
            return rv.show_element(uiapp.ActiveUIDocument, uid)

        def done(result, error):
            if error:
                self.status(error.strip().splitlines()[-1], u'bad')
            elif result == u'missing':
                self.status(u'That element is no longer in the model.', u'bad')
            elif result == u'view':
                self.status(u'Opening the view the element is drawn in.', u'ok')
            else:
                self.status(u'Selected in Revit.', u'ok')

        self.state.runner.submit(u'show', work, done)

    def _on_right_click(self, sender, args):
        dep = args.OriginalSource
        row_el = None
        while dep is not None:
            if isinstance(dep, DataGridRow):
                row_el = dep
                break
            try:
                dep = VisualTreeHelper.GetParent(dep)
            except Exception:
                dep = None
        if row_el is None:
            return
        row = row_el.Item
        sel = self.selected_rows()
        if row not in sel:
            self.grid.SelectedItem = row
            sel = [row]
        menu = self.menu()
        self.menu_add(menu, u'Show source in Revit', lambda s, a: self.show(row, u'src'), brush_key='BlueBrush')
        self.menu_add(menu, u'Show target in Revit', lambda s, a: self.show(row, u'tgt'), brush_key='OrangeBrush')
        self.menu_add(menu, u'Highlight {0} in current view'.format(
            u'these' if len(sel) > 1 else u'this'), lambda s, a: self.highlight_selected())
        self.menu_add(menu, u'Isolate in Default 3D', lambda s, a: self.isolate_selected())
        self.menu_add(menu, u'Parameter push template...', lambda s, a: self.template_menu(sel, self.grid))
        self.menu_add(menu, u'Remove {0} marriage(s)'.format(len(sel)), lambda s, a: self.remove_selected(),
                      brush_key='RedBrush')
        menu.PlacementTarget = self.grid
        menu.IsOpen = True
        args.Handled = True

    # ---- debug report -------------------------------------------------------
    def debug_on(self):
        return self.state.settings.get(u'debug') == u'1'

    def debug_report(self, title, lines):
        """With Debug ticked: a report after the run with a Copy button to send to Claude."""
        if not self.debug_on():
            return False
        app = self.state.uiapp.Application
        version = u'?'
        try:
            version = to_text(app.VersionNumber) + u' (' + to_text(app.VersionBuild) + u')'
        except Exception:
            pass
        head = [u'RevoBIM Schematic Marriage v{0} - {1}'.format(__version__, title),
                u'Revit {0}  -  model: {1}  -  workshared: {2}  -  {3}'.format(
                    version, to_text(self.state.doc.Title), self.state.doc.IsWorkshared, store.now_text()),
                u'marriages: {0}  -  templates: {1}  -  with a template: {2}  -  highlights held: {3}'.format(
                    len(self.state.marriages), len(self.state.templates),
                    len([m for m in self.state.marriages if m.template_id]), len(self.state.hl)),
                u'']
        text = u'\n'.join(head + [to_text(l) for l in lines])
        self.state.debug(text)
        self.state.flush_debug()
        ui.prompt(self, u'Debug report', u'Press Copy and paste this to Claude. It is also saved to ' +
                  store.debug_path(), ok=u'Close', show_cancel=False, copy_text=text)
        return True

    # ---- highlight / isolate ----------------------------------------------
    def _update_hl_button(self):
        n = len(self.state.hl)
        self.n('BtnClearHl').IsEnabled = n > 0
        self.n('TxtClearHl').Text = u'Clear Highlights ({0})'.format(n) if n else u'Clear Highlights'

    def release_highlight(self, tag, quiet=True):
        """Put back the graphics held by tag ('src', 'tgt', 'view', or None for all)."""
        if not any(tag is None or tag in r['tags'] for r in self.state.hl.values()):
            return

        def work(uiapp):
            return rv.release(self.state.doc, self.state.hl, tag)

        def done(result, error):
            if self.state.main is None:
                return
            self._update_hl_button()
            if tag is None and not error:
                self.status(u'Highlights cleared ({0} element(s) put back).'.format(result or 0), u'ok')

        self.state.runner.submit(u'release highlight', work, done, quiet=quiet)

    def highlight_selected(self):
        rows = self.selected_rows()
        if not rows:
            return

        def work(uiapp):
            if not self._doc_ok(uiapp):
                raise Exception(u'Switch back to {0} first.'.format(to_text(self.state.doc.Title)))
            uidoc = uiapp.ActiveUIDocument
            doc, view = uidoc.Document, uidoc.ActiveView
            rv.release(doc, self.state.hl, u'view')
            wanted = rv.marriage_elements(doc, rows)
            here = rv.visible_in_view(doc, view, wanted)
            n, problem = rv.highlight(doc, view, here, self.state.hl, u'view')
            return n, len(wanted), problem, rv.elem_name(view)

        def done(result, error):
            self._update_hl_button()
            if error:
                self.status(error.strip().splitlines()[-1], u'bad')
                self.debug_report(u'Highlight in View FAILED', [error])
                return
            n, total, problem, view_name = result
            if not n:
                self.status(u'None of the {0} element(s) are in "{1}"{2}.'.format(
                    total, view_name, u' (' + problem + u')' if problem else u''), u'warn')
            elif n < total:
                self.status(u'{0} of {1} element(s) highlighted magenta in "{2}" - the other {3} are not in this view.'
                            .format(n, total, view_name, total - n), u'warn')
            else:
                self.status(u'All {0} element(s) highlighted magenta in "{1}".'.format(n, view_name), u'ok')

        self.status(u'Highlighting in the current view...', u'warn')
        self.state.runner.submit(u'highlight', work, done)

    def isolate_selected(self):
        rows = self.selected_rows()
        if not rows:
            return

        def work(uiapp):
            if not self._doc_ok(uiapp):
                raise Exception(u'Switch back to {0} first.'.format(to_text(self.state.doc.Title)))
            uidoc = uiapp.ActiveUIDocument
            return rv.isolate_in_3d(uidoc, rv.marriage_elements(uidoc.Document, rows))

        def done(result, error):
            if error:
                self.status(u'Isolate failed: ' + error.strip().splitlines()[-1], u'bad')
                self.debug_report(u'Isolate in Default 3D FAILED', [error])
                return
            name, n, skipped = result
            if not n:
                self.status(u'Nothing to isolate - the selected marriages have no model elements in this model.', u'warn')
                return
            note = u' ({0} detail item(s) left out - they only exist in their own view).'.format(skipped) if skipped else u'.'
            self.status(u'{0} element(s) isolated in "{1}"{2}'.format(n, name, note), u'ok')

        self.status(u'Opening the default 3D view...', u'warn')
        self.state.runner.submit(u'isolate in 3D', work, done)

    # ---- update data ------------------------------------------------------
    def update_data(self):
        choice = self.ask_to_apply(u'running Update Data')
        if choice == u'cancel':
            return
        if choice == u'apply':
            self.apply_changes(then=lambda ok: self._run_update(u'none') if ok else None)
            return
        self._run_update(choice)

    def _run_update(self, choice):
        """choice 'skip': run on what the model holds, leaving staged changes staged."""
        swapped = {}
        if choice == u'skip':
            for m in store.pending_marriages(self.state.marriages):
                swapped[m.id] = m.template_id
                m.template_id = m.applied_tid
        todo = [m for m in self.state.marriages if m.template_id]
        if not todo:
            store.restore_templates(self.state.marriages, swapped)
            self.status(u'Nothing applied has a template yet.', u'warn')
            return
        templates = self.state.templates_by_id()
        log = []

        def work(uiapp):
            if not self._doc_ok(uiapp):
                raise Exception(u'Switch back to {0} to update.'.format(to_text(self.state.doc.Title)))
            rep = rv.push(self.state.doc, self.state.marriages, templates, progress=self.progress, log=log)
            rv.resolve(self.state.doc, self.state.marriages)
            return rep

        def done(rep, error):
            self.progress(0, 0)
            store.restore_templates(self.state.marriages, swapped)   # staged ones back as they were
            if error:
                self.status(u'Update failed - see the debug report.' if self.debug_on()
                            else u'Update failed - tick Debug, run again and send the report.', u'bad')
                self.refresh()
                if not self.debug_report(u'Update Data FAILED', [u'--- error ---', error, u'--- log ---'] + log):
                    self.state.debug(error)
                return
            self.refresh()
            problems = rep['failed'] + rep['conflicts'] + rep['refused']
            text = u'{0} written across {1}{2}{3} already up to date'.format(
                store.plural(rep['writes'], u'value'), store.plural(rep['marriages'], u'marriage'),
                DOT, rep['unchanged'])
            if rep['empty']:
                text += DOT + u'{0} left alone (source empty)'.format(len(rep['empty']))
            lines = [u'Marriage {0}: {1}'.format(no, why) for no, why in problems + rep['skipped']]
            if problems or rep['skipped']:
                text += DOT + u'{0} need a look'.format(len(problems) + len(rep['skipped']))
                self.status(text, u'bad' if problems else u'warn')
            else:
                self.status(text + u'.', u'ok')
            empties = [u'Marriage {0}: "{1}" is empty on the source - target left as it was '
                       u'(tick "clear the target" in the template to blank it instead)'.format(no, name)
                       for no, name in rep['empty']]
            report = [text, u'',
                      u'written {0}  already {1}  source-empty {2}  skipped {3}  failed {4}  conflicts {5}  '
                      u'held-by-others {6}'.format(
                          rep['writes'], rep['unchanged'], len(rep['empty']), len(rep['skipped']),
                          len(rep['failed']), len(rep['conflicts']), len(rep['refused'])),
                      u'timing: ' + rep.get('timing', u''),
                      u'', u'--- needs a look ---'] + (lines or [u'(nothing)']) + \
                     [u'', u'--- left alone, by design ---'] + (empties or [u'(nothing)']) + \
                     [u'', u'--- per marriage (source param > target param: was -> now) ---'] + log
            if not self.debug_report(u'Update Data', report) and (problems or rep['skipped']):
                ui.info(self, u'Update Data',
                        text + u'.\n\nRows with a red or orange "Last update" are the ones to look at:',
                        lines[:400])

        self.status(u'Updating {0} marriages...'.format(len(todo)), u'warn')
        self.progress(0, max(1, len(todo)))
        self.state.runner.submit(u'update data', work, done)

    # ---- model watching ---------------------------------------------------
    def _on_doc_changed(self, sender, args):
        try:
            if self._closing or self.state.runner.busy:
                return
            if not args.GetDocument().Equals(self.state.doc):
                return
            if self._relevant(args):
                self.reload_later.poke()
        except Exception:
            pass

    def _relevant(self, args):
        """Only our records or married elements matter - not every edit in the model."""
        watch = self._watch_ids
        for getter in (args.GetDeletedElementIds, args.GetModifiedElementIds):
            ids = getter()
            if ids.Count > 5000:
                return True
            for i in ids:
                if rv.eid_value(i) in watch:
                    return True
        added = args.GetAddedElementIds()
        if added.Count > 5000:
            return True
        for i in added:
            try:
                if type(self.state.doc.GetElement(i)).__name__ == 'DataStorage':
                    return True
            except Exception:
                pass
        return False

    def _rebuild_watch(self):
        watch = set()
        for rec in list(self.state.marriages) + list(self.state.templates):
            if rec.storage_id is not None:
                watch.add(rv.eid_value(rec.storage_id))
        for m in self.state.marriages:
            for text in (m.src_eid, m.tgt_eid):
                try:
                    watch.add(int(text))
                except Exception:
                    pass
        self._watch_ids = watch

    def reload_from_model(self):
        if self._closing or self.state.runner.busy:
            return
        old_status = dict((m.id, (m.status, m.status_kind)) for m in self.state.marriages)

        def work(uiapp):
            if not self.state.doc.IsValidObject:
                return None
            ms, ts = rv.read_all(self.state.doc)
            rv.resolve(self.state.doc, ms)
            return ms, ts

        def done(result, error):
            if error or result is None:
                return
            ms, ts = result
            for m in ms:
                if m.id in old_status:
                    m.status, m.status_kind = old_status[m.id]
            store.keep_staged(ms, self.state.marriages)
            self.state.marriages, self.state.templates = ms, ts
            self.state.data_changed()

        self.state.runner.submit(u'reload', work, done, quiet=True)

    # ---- templates window --------------------------------------------------
    def open_templates(self, prefill=None):
        try:
            import sm_tpl_ui
            # the toolbar button opens the list with nothing in the editor; only
            # "New template for these categories..." passes a prefill
            if self.state.tpl_win is not None:
                self.state.tpl_win.win.Activate()
                if prefill is not None:
                    self.state.tpl_win.new_template(prefill)
                return
            sm_tpl_ui.open_window(self.state, prefill)
        except Exception:
            self._error(to_text(traceback.format_exc()))

    # ---- misc ---------------------------------------------------------------
    def _on_debug(self, sender, args):
        self.state.settings[u'debug'] = u'1' if self.n('ChkDebug').IsChecked else u'0'
        self.state.save_settings()
        if self.state.settings[u'debug'] == u'1':
            self.state.debug(u'debug on - Schematic Marriage v{0}, model {1}'.format(
                __version__, to_text(self.state.doc.Title)))
            self.status(u'Debug on: ' + store.debug_path())

    def _on_closing(self, sender, args):
        if not getattr(self, '_close_ok', False):
            choice = self.ask_to_apply(u'closing')
            if choice == u'cancel':
                args.Cancel = True
                return
            if choice == u'apply':
                args.Cancel = True

                def then(ok):
                    if ok:
                        self._close_ok = True
                        self.close()
                self.apply_changes(then=then)
                return
        tw = self.state.tpl_win
        if tw is not None and tw.dirty:
            if not tw.confirm_discard():
                args.Cancel = True
                return
            tw.dirty = False

    def _on_closed(self, sender, args):
        self._closing = True
        try:
            if self._full is None:
                self.state.settings[u'main_w'] = to_text(int(self.win.Width))
                self.state.settings[u'main_h'] = to_text(int(self.win.Height))
            self.state.save_settings()
        except Exception:
            pass
        self.search_later.stop()
        self.reload_later.stop()
        if self._dc is not None:
            try:
                self.state.uiapp.Application.DocumentChanged -= self._dc
            except Exception:
                pass
        if self.state.tpl_win is not None:
            self.state.tpl_win.close()
        if self.state.hl:
            state = self.state

            def work(uiapp):
                return rv.release(state.doc, state.hl, None)
            state.runner.submit(u'release highlights on close', work, None, quiet=True)
        try:
            self.grid.ItemsSource = None
        except Exception:
            pass
        self.state.flush_debug()
        self.state.main = None
        try:
            AppDomain.CurrentDomain.SetData(LIVE_KEY, None)
        except Exception:
            pass


# ==========================================================================
# launch
# ==========================================================================

def _live_window():
    try:
        return AppDomain.CurrentDomain.GetData(LIVE_KEY)
    except Exception:
        return None


def launch(uiapp):
    """Called from script.py inside the command (API context)."""
    existing = _live_window()
    if existing is not None:
        try:
            if existing.state.doc.Equals(uiapp.ActiveUIDocument.Document):
                existing.win.Activate()
                return existing
            existing.close()
        except Exception:
            pass

    state = State(uiapp)
    state.marriages, state.templates = rv.read_all(state.doc)
    rv.resolve(state.doc, state.marriages)
    state.recount()

    main = MainWindow(state)
    state.main = main
    try:
        WindowInteropHelper(main.win).Owner = uiapp.MainWindowHandle
    except Exception:
        pass
    main.refresh()
    if state.marriages:
        main.status(u'{0} marriages and {1} templates read from {2}.'.format(
            len(state.marriages), len(state.templates), to_text(state.doc.Title)))
    else:
        main.status(u'No marriages in {0} yet - pick a source and a target to start.'.format(
            to_text(state.doc.Title)))
    try:
        AppDomain.CurrentDomain.SetData(LIVE_KEY, main)
    except Exception:
        pass
    main.win.Show()
    return main
