# -*- coding: utf-8 -*-
"""Schematic Marriage - Parameter Push Templates window.

Modeless child of the main window (a modal dialog would stop the
ExternalEvent from running until it closed). The editor works on a COPY of a
template; nothing reaches the model until Save Template.
"""
import sm_clr  # noqa: F401  (must stay first - references the assemblies)

import os
import traceback

from System.IO import File
from System.Text import Encoding
from System.Windows import GridLength, GridUnitType, Visibility
from System.Windows.Controls import TextBlock, TextBox, Button, DataGridRow
from System.Windows.Controls.Primitives import DataGridColumnHeader, ScrollBar
from System.Windows.Media import VisualTreeHelper
from System.Windows.Input import Keyboard, ModifierKeys, Key
from Microsoft.Win32 import OpenFileDialog, SaveFileDialog

import sm_store as store
import sm_revit as rv
import sm_wpf as ui
from sm_store import to_text

DOT = u'  \u00b7  '
CHROME = 30.0          # body margins (2 x 14) + window border (2 x 1)
SPLIT_W = 9.0
MIN_W_CLOSED = 440.0
MIN_W_OPEN = 380.0 + SPLIT_W + 480.0 + CHROME

TPL_COLUMNS = [
    (u'name', u'Template', 2.0, 150, None),
    (u'src_cat', u'Source', 1.2, 90, u'BlueBrush'),
    (u'tgt_cat', u'Target', 1.2, 90, u'OrangeBrush'),
    (u'params', u'Pushes', 0.55, 62, None),
    (u'used', u'Used', 0.5, 52, None),
]

PUSH_COLUMNS = [
    (u'src', u'Source parameter', 1.4, 140, u'BlueBrush'),
    (u'arrow', u'', 0.22, 28, None),
    (u'tgt', u'Target parameter', 1.4, 140, u'OrangeBrush'),
    (u'kind', u'Converts', 1.0, 130, None),
]


class NewRow(object):
    """The green '+ New template' row that always sits under the last template."""
    id = u''
    used = 0
    tgt_scope = u''

    def value(self, key):
        return u'+   New template' if key == u'name' else u''


NEW_ROW = NewRow()


class TemplatesWindow(ui.ThemedWindow):
    XAML = 'SMTemplates.xaml'

    def __init__(self, state):
        self.cats = []
        self.params = {}
        self.edit = None
        self.is_new = False
        self.dirty = False
        self.editing = False
        self.just_saved = u''
        self.tpl_undo = store.UndoStack()
        self.saved_text = None
        self.expanded = False
        self._tween = None
        self._manual_open = False
        self._opened_once = False          # opens closed, pinned or not
        self.pinned = state.settings.get(u'tpl_pinned') == u'1'
        self._suspend = False
        self._pending_prefill = None
        self.src_ids = []
        self.tgt_ids = []
        self.tsort = None
        self.tdesc = False
        ui.ThemedWindow.__init__(self, state)
        self.grid = self.n('GridTemplates')
        self.pgrid = self.n('GridPushes')
        self.text_conv = ui.FuncConverter(self._cell_text)
        self.brush_conv = ui.FuncConverter(self._cell_brush)
        for key, title, star, minw, brush_key in TPL_COLUMNS:
            header, _box = ui.header_with_filter(title, brush_key, None, filters=False)
            self.grid.Columns.Add(ui.text_column(header, key, self.text_conv, star, minw,
                                                 self.brush_conv, bold=(key == u'name')))
        for key, title, star, minw, brush_key in PUSH_COLUMNS:
            header, _box = ui.header_with_filter(title, brush_key, None, filters=False)
            col = ui.text_column(header, u'p_' + key, self.text_conv, star, minw, self.brush_conv)
            col.CanUserSort = False
            self.pgrid.Columns.Add(col)
        self.search_later = ui.Debounce(220, self.refresh_list, self._error)
        self._wire()
        try:
            self.win.Width = self._list_w() + CHROME      # opens contracted - just the list
            self.win.Height = float(state.settings.get(u'tpl_h') or 800)
        except Exception:
            pass
        self._show_pin()
        self.load_editor(None, False)

    # ---- wiring -----------------------------------------------------------
    def _wire(self):
        self.grid.SelectionChanged += lambda s, a: self._on_tpl_select()
        self.grid.Sorting += self._on_sorting
        self.n('TxtTplSearch').TextChanged += lambda s, a: self.search_later.poke()
        self.n('BtnNew').Click += lambda s, a: self.new_template(self._main_selection())
        self.n('BtnEdit').Click += lambda s, a: self.start_edit()
        self.n('BtnPin').Click += lambda s, a: self.toggle_pin()
        self.n('BtnSlide').Click += lambda s, a: self.toggle_slide()
        self.n('BtnTplUndo').Click += lambda s, a: self.do_undo()
        self.n('BtnTplRedo').Click += lambda s, a: self.do_redo()
        self.n('TxtName').IsUndoEnabled = False       # its typing is on the template's own undo
        self.win.PreviewKeyDown += self._on_preview_key
        self.n('BtnBack').Click += lambda s, a: self.back_to_marriages()
        self.grid.MouseDoubleClick += lambda s, a: self.start_edit()
        self.grid.PreviewMouseLeftButtonDown += self._on_grid_mouse_down
        self.n('BtnDuplicate').Click += lambda s, a: self.duplicate()
        self.n('BtnMerge').Click += lambda s, a: self.merge()
        self.n('BtnDelete').Click += lambda s, a: self.delete()
        self.n('BtnImport').Click += lambda s, a: self.import_library()
        self.n('BtnExport').Click += lambda s, a: self.export_library()
        self.n('TxtName').TextChanged += self._on_name
        self.cat_pick = {
            u'src': ui.SearchPick(self.n('TxtSrcCat'), self.n('PopSrcCat'), self.n('LstSrcCat'),
                                  lambda e: self.on_cat_picked(u'src', e)),
            u'tgt': ui.SearchPick(self.n('TxtTgtCat'), self.n('PopTgtCat'), self.n('LstTgtCat'),
                                  lambda e: self.on_cat_picked(u'tgt', e)),
        }
        self.n('TxtSrcParSearch').TextChanged += lambda s, a: self.fill_params(u'src')
        self.n('TxtTgtParSearch').TextChanged += lambda s, a: self.fill_params(u'tgt')
        self.n('LstSrcPar').SelectionChanged += lambda s, a: self._update_add()
        self.n('LstTgtPar').SelectionChanged += lambda s, a: self._update_add()
        self.n('LstTgtPar').MouseDoubleClick += lambda s, a: self.add_push()
        self.n('BtnAddPush').Click += lambda s, a: self.add_push()
        self.pgrid.SelectionChanged += lambda s, a: self._update_remove_push()
        self.n('BtnRemovePush').Click += lambda s, a: self.remove_pushes()
        self.n('ChkClearEmpty').Click += self._on_clear_empty
        self.n('BtnSave').Click += lambda s, a: self.save()
        self.n('BtnRevert').Click += lambda s, a: self.revert()
        self.win.Closing += self._on_closing
        self.win.Closed += self._on_closed

    def _error(self, text):
        self.state.debug(text)
        self.status(u'Something went wrong - tick Debug in the main window and send the report.', u'bad')

    def status(self, text, kind=u''):
        try:
            t = self.n('TxtStatus')
            t.Text = to_text(text)
            key = {u'bad': 'RedBrush', u'warn': 'OrangeBrush', u'ok': 'GreenBrush'}.get(kind, 'MutedBrush')
            t.SetResourceReference(TextBlock.ForegroundProperty, key)
        except Exception:
            pass

    def progress(self, done, total, label=u''):
        """Band above the footer: label, % and what is left. total 0 hides it.
        Only ever called between reads - never inside a transaction."""
        band = self.n('ProgressBand')
        if total <= 0:
            band.Visibility = Visibility.Collapsed
            return
        band.Visibility = Visibility.Visible
        frac = max(0.0, min(1.0, float(done) / float(total)))
        self.n('ColFill').Width = GridLength(frac, GridUnitType.Star)
        self.n('ColRest').Width = GridLength(1.0 - frac, GridUnitType.Star)
        self.n('TxtProgress').Text = u'{0}  -  {1}%  -  {2} of {3} left'.format(
            label, int(round(frac * 100)), total - done, total)
        ui.do_events()

    def after_theme(self):
        for g in (self.grid, self.pgrid):
            try:
                g.Items.Refresh()
            except Exception:
                pass

    # ---- cells ------------------------------------------------------------
    def _cell_text(self, row, key):
        key = to_text(key)
        if key.startswith(u'p_'):
            return row.value(key[2:])
        return row.value(key)

    def _cell_brush(self, row, key):
        key = to_text(key)
        res = self.win.Resources
        if isinstance(row, NewRow):
            return res['GreenBrush']
        if key == u'name' and self.just_saved and row.id == self.just_saved:
            return res['GreenBrush']
        if key == u'used':
            return res['OrangeBrush'] if row.used else res['MutedBrush']
        if key == u'params':
            return res['MutedBrush']
        if key == u'p_arrow':
            return res['MutedBrush']
        if key == u'p_kind':
            return res['OrangeBrush'] if row.tgt_scope == u'type' else res['MutedBrush']
        return res['TextBrush']   # never Unset: that falls to WPF's default, not the theme

    # ---- template list ----------------------------------------------------
    def refresh_list(self):
        text = to_text(self.n('TxtTplSearch').Text)
        rows = [t for t in self.state.templates
                if store.matches_keywords(t.name + u' ' + t.src_cat_name + u' ' + t.tgt_cat_name, text)]
        if self.tsort:
            key = self.tsort
            if key in (u'params', u'used'):
                rows.sort(key=lambda t: int(t.value(key) or 0), reverse=self.tdesc)
            else:
                rows.sort(key=lambda t: store.natural_key(t.value(key)), reverse=self.tdesc)
        keep = set(t.id for t in self.selected_templates())
        if not keep and self.edit is not None:
            keep.add(self.edit.id)
        self._suspend = True
        try:
            self.grid.ItemsSource = ui.items(rows + [NEW_ROW])
            for t in rows:
                if t.id in keep:
                    self.grid.SelectedItems.Add(t)
                    if t.id == self.just_saved:
                        self.grid.ScrollIntoView(t)
        except Exception:
            pass
        finally:
            self._suspend = False
        n = len(self.state.templates)
        self.n('TxtTplCount').Text = (u'{0} in this model'.format(n) if len(rows) == n
                                      else u'{0} of {1}'.format(len(rows), n))
        self._update_list_buttons()

    def _on_sorting(self, sender, args):
        args.Handled = True
        key = to_text(args.Column.SortMemberPath)
        if self.tsort == key:
            self.tdesc = not self.tdesc
        else:
            self.tsort, self.tdesc = key, False
        for c in self.grid.Columns:
            c.SortDirection = None
        args.Column.SortDirection = ui.sort_direction(self.tdesc)
        self.refresh_list()

    def selected_templates(self):
        try:
            return [t for t in self.grid.SelectedItems if not isinstance(t, NewRow)]
        except Exception:
            return []

    def _update_list_buttons(self):
        sel = self.selected_templates()
        self.n('BtnEdit').IsEnabled = len(sel) == 1
        self.n('BtnDuplicate').IsEnabled = len(sel) == 1
        self.n('BtnMerge').IsEnabled = len(sel) >= 2
        self.n('TxtMerge').Text = u'Merge ({0})'.format(len(sel)) if len(sel) >= 2 else u'Merge'
        self.n('BtnDelete').IsEnabled = len(sel) >= 1
        self.n('TxtDelete').Text = u'Delete ({0})'.format(len(sel)) if len(sel) > 1 else u'Delete'
        self.n('TxtExport').Text = (u'Export {0} selected...'.format(len(sel)) if sel
                                    else u'Export all...')

    def _on_tpl_select(self):
        if self._suspend:
            return
        if any(isinstance(t, NewRow) for t in self.grid.SelectedItems):
            self._suspend = True
            try:
                self.grid.SelectedItems.Clear()
            finally:
                self._suspend = False
            self.new_template(self._main_selection())
            return
        self._update_list_buttons()
        sel = self.selected_templates()
        if len(sel) != 1:
            return
        t = sel[0]
        if self.edit is not None and t.id == self.edit.id:
            return
        if not self.confirm_discard():
            self._suspend = True
            try:
                self.grid.SelectedItems.Clear()
            finally:
                self._suspend = False
            return
        # one click: the editor slides out already in edit mode
        self.load_editor(t.copy(keep_id=True), False, editing=True)
        self.status(u'Editing "{0}" - Save Template when done. Click the empty space under the list to '
                    u'put it away unchanged.'.format(t.name))

    def start_edit(self):
        sel = self.selected_templates()
        if len(sel) != 1:
            return
        t = sel[0]
        if self.edit is None or self.edit.id != t.id:
            if not self.confirm_discard():
                return
            self.load_editor(t.copy(keep_id=True), False, editing=True)
        else:
            self.set_editing(True)
        self.status(u'Editing "{0}" - Save Template when done, Cancel to leave it as it was.'.format(t.name))

    def set_editing(self, on):
        self.editing = bool(on) and self.edit is not None
        card = self.n('EditorCard')
        card.IsEnabled = self.editing
        card.Opacity = 1.0 if self.editing else 0.5
        self.set_dirty(self.dirty)

    # ---- sliding editor --------------------------------------------------
    def _list_w(self):
        try:
            w = self.n('ColList').ActualWidth
            if w and w > 300:
                return float(w)
        except Exception:
            pass
        try:
            return max(380.0, float(self.state.settings.get(u'tpl_list_w') or 600))
        except Exception:
            return 600.0

    def _edit_w(self):
        try:
            return max(480.0, float(self.state.settings.get(u'tpl_edit_w') or 720))
        except Exception:
            return 720.0

    def _remember_edit_w(self):
        try:
            w = self.n('ColEdit').ActualWidth
            if w and w >= 480:
                self.state.settings[u'tpl_edit_w'] = to_text(int(w))
        except Exception:
            pass

    def _sync_expand(self, animate=True):
        want = (self.pinned and self._opened_once) or self.edit is not None or self._manual_open
        if want:
            self._opened_once = True
        self.set_expanded(want, animate)

    def toggle_pin(self):
        self.pinned = not self.pinned
        if self.pinned:
            self._opened_once = True
        self.state.settings[u'tpl_pinned'] = u'1' if self.pinned else u'0'
        self.state.save_settings()
        self._show_pin()
        if not self.pinned and not self.editing and self.edit is not None:
            self.load_editor(None, False)       # previewing only: retract
        else:
            self._sync_expand()
        self.status(u'Editor pinned open - it stays out and greys when not editing.' if self.pinned
                    else u'Editor unpinned - it slides out when you pick or create a template.')

    def _show_pin(self):
        b = self.n('BtnPin')
        b.SetResourceReference(Button.BackgroundProperty, 'BlueSoftBrush' if self.pinned else 'CardBrush')
        b.SetResourceReference(Button.BorderBrushProperty, 'BlueBrush' if self.pinned else 'EdgeBrush')
        self.n('TxtPin').Text = u'Pinned' if self.pinned else u'Pin'

    def toggle_slide(self):
        if self.expanded:
            if self.pinned:
                self.status(u'The editor is pinned - unpin it to slide it away.', u'warn')
                return
            if not self.confirm_discard():
                return
            self._manual_open = False
            self.load_editor(None, False)
        else:
            self._manual_open = True
            self._sync_expand()

    def set_expanded(self, on, animate=True):
        if on == self.expanded and self._tween is None:
            self._layout(on)
            return
        if self._tween is not None:
            self._tween.stop()
            self._tween = None
        self.expanded = on
        if not on:
            self._manual_open = False
        self.n('TxtSlide').Text = u'Editor  \u2039' if on else u'Editor  \u203a'
        w = self.win
        list_w = self._list_w()
        if not on and self._layout_is_open():
            self._remember_edit_w()
        target = list_w + CHROME + ((SPLIT_W + self._edit_w()) if on else 0)
        if self._full is not None or not animate or not w.IsLoaded:
            self._layout(on)
            if self._full is None:
                w.Width = target
            return
        # slide: list held at its pixel width, editor column takes whatever
        # the window gives it while the window grows or shrinks
        col_list, col_edit = self.n('ColList'), self.n('ColEdit')
        col_list.Width = GridLength(list_w)
        col_edit.MinWidth = 0
        col_edit.Width = GridLength(1, GridUnitType.Star)
        self.n('ColSplit').Width = GridLength.Auto
        self.n('EditorCard').Visibility = Visibility.Visible
        self.n('Splitter').Visibility = Visibility.Visible
        w.MinWidth = MIN_W_CLOSED
        start_w, start_left = w.Width, w.Left
        end_left = start_left
        if on:
            left, _top, right, _bottom = self.screen_area()
            if start_left + target > right:
                end_left = max(left, right - target)

        def step(e):
            w.Width = start_w + (target - start_w) * e
            if end_left != start_left:
                w.Left = start_left + (end_left - start_left) * e

        def done():
            self._tween = None
            self._layout(on)
            w.Width = target

        self._tween = ui.Tween(260, step, done)
        self._tween.start()

    def _layout_is_open(self):
        return self.n('EditorCard').Visibility == Visibility.Visible

    def _layout(self, on):
        """Settled layout: both columns star-sized when open (splitter rule)."""
        col_list, col_split, col_edit = self.n('ColList'), self.n('ColSplit'), self.n('ColEdit')
        card, splitter = self.n('EditorCard'), self.n('Splitter')
        if on:
            list_w = self._list_w()
            edit_w = col_edit.ActualWidth if col_edit.ActualWidth >= 480 else self._edit_w()
            col_list.Width = GridLength(list_w, GridUnitType.Star)
            col_split.Width = GridLength.Auto
            col_edit.Width = GridLength(edit_w, GridUnitType.Star)
            col_edit.MinWidth = 480
            card.Visibility = Visibility.Visible
            splitter.Visibility = Visibility.Visible
            self.win.MinWidth = MIN_W_OPEN
        else:
            col_list.Width = GridLength(1, GridUnitType.Star)
            col_split.Width = GridLength(0)
            col_edit.MinWidth = 0
            col_edit.Width = GridLength(0)
            card.Visibility = Visibility.Collapsed
            splitter.Visibility = Visibility.Collapsed
            self.win.MinWidth = MIN_W_CLOSED

    def _on_grid_mouse_down(self, sender, args):
        """A click in the empty space under the templates (no row, heading or
        scroll bar) puts an untouched editor away."""
        dep = args.OriginalSource
        while dep is not None:
            if isinstance(dep, (DataGridRow, DataGridColumnHeader, ScrollBar)):
                return
            try:
                dep = VisualTreeHelper.GetParent(dep)
            except Exception:
                dep = None
        if self.pinned or not self.expanded or self.dirty:
            return
        self._suspend = True
        try:
            self.grid.SelectedItems.Clear()
        finally:
            self._suspend = False
        self._update_list_buttons()
        self.load_editor(None, False)
        self.status(u'Editor put away - nothing was changed.')

    def dock_point(self):
        """Where the window comes from and goes back to: the middle of the
        main window's footer. None when the main window is not on screen."""
        try:
            mw = self.state.main.win
            if not mw.IsVisible or mw.ActualWidth <= 0:
                return None
            return mw.Left + mw.ActualWidth / 2.0, mw.Top + mw.ActualHeight - 26.0
        except Exception:
            return None

    def _on_close_click(self, sender, args):
        """The header X closes the same way as Close back to Marriages."""
        self.back_to_marriages()

    def back_to_marriages(self):
        """Shrink into the bottom of the main window, the way a Mac window
        minimises to the dock, then close."""
        if getattr(self, '_leaving', False):    # a second click while it is already going
            return
        if not self.confirm_discard():
            return
        self._leaving = True
        self.dirty = False                      # already asked - no second prompt on Closing
        main = self.state.main
        point = self.dock_point()
        if point is None or self._full is not None:
            self.close()
            return
        tx, ty = point

        def done():
            self.close()
            try:
                main.win.Activate()
            except Exception:
                pass
        ui.genie(self.win, tx, ty, done, owner=main.win)

    def _main_selection(self):
        try:
            sel = self.state.main.selected_rows()
            return sel[0] if sel else None
        except Exception:
            return None

    # ---- editor -----------------------------------------------------------
    def load_editor(self, template, is_new, editing=None):
        self.edit = template
        self.is_new = is_new
        self.dirty = False
        self.tpl_undo.clear()
        # baseline for "changed?": a new template counts as untouched until edited,
        # so putting an empty new one away never asks to discard it
        self.saved_text = None if template is None else template.to_text()
        if editing is None:
            editing = is_new
        on = template is not None
        for name in ('TxtName', 'TxtSrcCat', 'TxtTgtCat',
                     'TxtSrcParSearch', 'TxtTgtParSearch', 'ChkClearEmpty'):
            self.n(name).IsEnabled = on
        self._suspend = True
        try:
            self.n('TxtName').Text = template.name if on else u''
            self.n('ChkClearEmpty').IsChecked = bool(on and template.clear_empty)
            self.n('TxtSrcParSearch').Text = u''
            self.n('TxtTgtParSearch').Text = u''
        finally:
            self._suspend = False
        self.fill_cat_combo(u'src')
        self.fill_cat_combo(u'tgt')
        self.refresh_pushes()
        if on:
            self.load_params(u'src')
            self.load_params(u'tgt')
        else:
            self.n('LstSrcPar').Items.Clear()
            self.n('LstTgtPar').Items.Clear()
        self.dirty = False
        self.set_editing(editing)
        self._sync_expand()

    def set_dirty(self, on):
        self.dirty = bool(on) and self.edit is not None
        self._update_tpl_undo()
        self.n('BtnSave').IsEnabled = self.dirty and self.editing
        self.n('BtnRevert').IsEnabled = self.editing
        self.n('TxtRevert').Text = u'Discard' if self.is_new else u'Cancel'
        state = self.n('TxtEditState')
        if self.edit is None:
            state.Text = u'Press New (or the green + row) to create one, or Edit a template on the left'
            state.SetResourceReference(TextBlock.ForegroundProperty, 'MutedBrush')
        elif self.is_new:
            state.Text = u'New template - not saved yet'
            state.SetResourceReference(TextBlock.ForegroundProperty, 'OrangeBrush')
        elif self.dirty:
            state.Text = u'"{0}"{1}unsaved changes'.format(self.edit.name, DOT)
            state.SetResourceReference(TextBlock.ForegroundProperty, 'OrangeBrush')
        else:
            used = 0
            for t in self.state.templates:
                if t.id == self.edit.id:
                    used = t.used
            state.Text = u'"{0}"{1}used by {2} marriage(s){3}'.format(
                self.edit.name, DOT, used, u'' if self.editing else DOT + u'press Edit to change it')
            state.SetResourceReference(TextBlock.ForegroundProperty, 'MutedBrush')

    def confirm_discard(self):
        if not self.dirty or not self.editing or self.edit is None:
            return True
        r = ui.prompt(self, u'Unsaved template',
                      u'Discard the unsaved changes to "{0}"?'.format(self.edit.name or u'new template'),
                      ok=u'Discard', cancel=u'Keep editing', danger=True)
        return bool(r.get('ok'))

    def new_template(self, prefill=None):
        if not self.confirm_discard():
            return
        t = store.Template()
        if prefill is not None:
            t.src_cat_id, t.src_cat_name = prefill.src_cat_id, prefill.src_cat_name
            t.tgt_cat_id, t.tgt_cat_name = prefill.tgt_cat_id, prefill.tgt_cat_name
            base = u'{0} to {1}'.format(prefill.src_cat_name, prefill.tgt_cat_name)
        else:
            base = u'New template'
        t.name = store.unique_name(base, [x.name for x in self.state.templates])
        self._suspend = True
        try:
            self.grid.SelectedItems.Clear()
        finally:
            self._suspend = False
        self.load_editor(t, True)
        self.status(u'Choose the categories, then add parameter pushes and Save Template.')
        try:
            self.n('TxtName').Focus()
            self.n('TxtName').SelectAll()
        except Exception:
            pass

    def _on_name(self, sender, args):
        if self._suspend or self.edit is None:
            return
        before = self.edit.to_text()
        self.edit.name = to_text(self.n('TxtName').Text)
        self._record(u'rename', before, merge=True)

    def _on_clear_empty(self, sender, args):
        if self.edit is None:
            return
        before = self.edit.to_text()
        self.edit.clear_empty = bool(self.n('ChkClearEmpty').IsChecked)
        self._record(u'clear-empty option', before)

    def revert(self):
        """Cancel / Discard: leave edit mode with the template as it was saved."""
        if self.edit is None:
            return
        if self.dirty and not self.confirm_discard():
            return
        if self.is_new:
            self.load_editor(None, False)
            self.status(u'New template discarded.')
            return
        for t in self.state.templates:
            if t.id == self.edit.id:
                if self.pinned:
                    self.load_editor(t.copy(keep_id=True), False, editing=False)
                else:
                    self.load_editor(None, False)
                self.status(u'Edit cancelled - "{0}" is as it was.'.format(t.name))
                return

    # ---- categories -------------------------------------------------------
    def load_categories(self, prefill=None):
        self._pending_prefill = prefill
        if self.state.cat_cache is not None:          # read once per session
            self._categories_ready(self.state.cat_cache)
            return
        self.status(u'Reading the categories in the model...')
        self.progress(0, 1, u'Reading categories')

        def work(uiapp):
            return rv.list_categories(self.state.doc,
                                      progress=lambda d, t: self.progress(d, t, u'Reading categories'))

        def done(result, error):
            self.progress(0, 0)
            if error:
                self._error(error)
                return
            self.state.cat_cache = result or []
            self._categories_ready(self.state.cat_cache)

        self.state.runner.submit(u'categories', work, done, quiet=True)

    def _categories_ready(self, cats):
        self.cats = list(cats)
        self.fill_cat_combo(u'src')
        self.fill_cat_combo(u'tgt')
        self.status(u'{0} MEP / schematic categories with elements in the model.'.format(len(self.cats)))
        if self._pending_prefill is not None:
            p = self._pending_prefill
            self._pending_prefill = None
            self.new_template(p)

    def fill_cat_combo(self, side):
        """Hand the one-box category picker its list and the current choice."""
        pick = self.cat_pick[side]
        cur_id, cur_name = self._side_cat(side)
        entries = list(self.cats)
        if cur_id and not any(c[0] == cur_id for c in entries):
            entries.insert(0, (cur_id, cur_name, 0))
        pick.set_entries(entries)
        pick.set_current(cur_id, cur_name)

    def on_cat_picked(self, side, entry):
        """-> False to make the picker put the old category back."""
        if self.edit is None:
            return False
        cid, name = entry[0], entry[1]
        old = self._side_cat(side)[0]
        if cid == old:
            return True
        before = self.edit.to_text()
        if self.edit.mappings:
            r = ui.prompt(self, u'Change category',
                          u'Changing the {0} category clears the {1} parameter push(es) already in this '
                          u'template, because they belong to the old category.'.format(
                              u'source' if side == u'src' else u'target', len(self.edit.mappings)),
                          ok=u'Change it', danger=True)
            if not r.get('ok'):
                return False
            self.edit.mappings = []
        if side == u'src':
            self.edit.src_cat_id, self.edit.src_cat_name = cid, name
        else:
            self.edit.tgt_cat_id, self.edit.tgt_cat_name = cid, name
        self.refresh_pushes()
        self.load_params(side)
        self._record(u'{0} category {1}'.format(u'source' if side == u'src' else u'target', name), before)
        return True

    # ---- parameters -------------------------------------------------------
    def _side_cat(self, side):
        if self.edit is None:
            return u'', u''
        if side == u'src':
            return self.edit.src_cat_id, self.edit.src_cat_name
        return self.edit.tgt_cat_id, self.edit.tgt_cat_name

    def load_params(self, side):
        cid, _name = self._side_cat(side)
        if not cid:
            self.fill_params(side)
            return
        if cid in self.params:
            self.fill_params(side)
            return
        lst = self.n('LstSrcPar' if side == u'src' else 'LstTgtPar')
        lst.Items.Clear()
        lst.Items.Add(ui.list_item(u'Reading parameters...', u'', None, muted=True))
        label = u'Reading {0} parameters'.format(_name)
        self.progress(0, 1, label)

        def work(uiapp):
            return rv.discover_params(self.state.doc, cid,
                                      progress=lambda d, t: self.progress(d, t, label))

        def done(result, error):
            self.progress(0, 0)
            if error:
                self._error(error)
                return
            self.params[cid] = result or []
            self.fill_params(u'src')
            self.fill_params(u'tgt')

        self.state.runner.submit(u'parameters', work, done, quiet=True)

    def fill_params(self, side):
        if self._suspend:
            return
        lst = self.n('LstSrcPar' if side == u'src' else 'LstTgtPar')
        head = self.n('TxtSrcParHead' if side == u'src' else 'TxtTgtParHead')
        box = self.n('TxtSrcParSearch' if side == u'src' else 'TxtTgtParSearch')
        cid, cname = self._side_cat(side)
        lst.Items.Clear()
        base = u'Source parameters' if side == u'src' else u'Target parameters (writable)'
        if not cid:
            head.Text = base
            lst.Items.Add(ui.list_item(u'Choose a category first.', u'', None, muted=True))
            self._update_add()
            return
        if cid not in self.params:
            head.Text = base
            return
        text = to_text(box.Text)
        infos = self.params[cid]
        if side == u'tgt':
            infos = [i for i in infos if i['writable']]
        used = set()
        if side == u'tgt' and self.edit is not None:
            used = set(m.key() for m in self.edit.mappings)
        shown = 0
        for info in infos:
            if not store.matches_keywords(info['name'], text):
                continue
            note = store.storage_label(info['storage']) + DOT + info['scope']
            if info.get('shared'):
                note += DOT + u'shared'
            taken = (info['name'], info['scope']) in used
            if taken:
                note += DOT + u'already pushed'
            lst.Items.Add(ui.list_item(info['name'], note, info, muted=taken))
            shown += 1
        head.Text = u'{0}  -  {1}, {2}'.format(base, cname, shown)
        if not infos:
            lst.Items.Add(ui.list_item(u'No {0}parameters found on {1}.'.format(
                u'writable ' if side == u'tgt' else u'', cname), u'', None, muted=True))
        self._update_add()

    def _picked(self, side):
        item = self.n('LstSrcPar' if side == u'src' else 'LstTgtPar').SelectedItem
        if item is None:
            return None
        return item.Tag

    def _update_add(self):
        self.n('BtnAddPush').IsEnabled = (self.edit is not None and self._picked(u'src') is not None
                                          and self._picked(u'tgt') is not None)

    def add_push(self):
        if self.edit is None:
            return
        s = self._picked(u'src')
        t = self._picked(u'tgt')
        if s is None or t is None:
            self.status(u'Pick a source parameter and a target parameter.', u'warn')
            return
        mapping = store.Mapping(s['name'], t['name'], t['scope'], s['storage'], t['storage'])
        before = self.edit.to_text()
        ok, note = store.add_mapping(self.edit, mapping)
        if not ok:
            self.status(note, u'bad')
            return
        self.refresh_pushes()
        self.fill_params(u'tgt')
        self._record(u'add push {0} > {1}'.format(s['name'], t['name']), before)
        msg = u'"{0}" will push into "{1}".'.format(s['name'], t['name'])
        if t['scope'] == u'type':
            msg += u' It is a TYPE parameter - every element of the target type gets the value.'
        if note:
            msg += u' ' + note
        self.status(msg, u'warn' if (note or t['scope'] == u'type') else u'ok')

    def refresh_pushes(self):
        rows = list(self.edit.mappings) if self.edit is not None else []
        self.pgrid.ItemsSource = ui.items(rows)
        self.n('TxtPushCount').Text = u'{0}'.format(len(rows)) if rows else u'none yet'
        self._update_remove_push()

    def _update_remove_push(self):
        try:
            self.n('BtnRemovePush').IsEnabled = self.pgrid.SelectedItems.Count > 0
        except Exception:
            pass

    def remove_pushes(self):
        if self.edit is None:
            return
        gone = set(id(m) for m in self.pgrid.SelectedItems)
        if not gone:
            return
        before = self.edit.to_text()
        self.edit.mappings = [m for m in self.edit.mappings if id(m) not in gone]
        self.refresh_pushes()
        self.fill_params(u'tgt')
        self._record(u'remove {0} push(es)'.format(len(gone)), before)

    # ---- undo / redo (editing a template) ----------------------------------
    def _record(self, label, before, merge=False):
        if self.edit is None:
            return
        self.tpl_undo.push(label, before, self.edit.to_text(), merge=merge)
        self._sync_dirty()

    def _sync_dirty(self):
        if self.edit is None:
            self.set_dirty(False)
            return
        self.set_dirty(self.edit.to_text() != self.saved_text)

    def _restore(self, text):
        """Put the editor back to a snapshot, keeping the template's identity."""
        t = store.Template.from_text(text)
        t.storage_id = self.edit.storage_id
        self.edit = t
        self._suspend = True
        try:
            self.n('TxtName').Text = t.name
            self.n('ChkClearEmpty').IsChecked = bool(t.clear_empty)
        finally:
            self._suspend = False
        self.fill_cat_combo(u'src')
        self.fill_cat_combo(u'tgt')
        self.refresh_pushes()
        self.load_params(u'src')
        self.load_params(u'tgt')
        self._sync_dirty()

    def do_undo(self):
        if not self.editing or self.edit is None:
            return
        step = self.tpl_undo.undo()
        if step is None:
            self.status(u'Nothing to undo in this template.')
            return
        self._restore(step[1])
        self.status(u'Undone: ' + step[0], u'warn')

    def do_redo(self):
        if not self.editing or self.edit is None:
            return
        step = self.tpl_undo.redo()
        if step is None:
            self.status(u'Nothing to redo in this template.')
            return
        self._restore(step[1])
        self.status(u'Redone: ' + step[0], u'warn')

    def _update_tpl_undo(self):
        u = self.tpl_undo
        on = self.editing
        self.n('BtnTplUndo').IsEnabled = on and u.can_undo()
        self.n('BtnTplRedo').IsEnabled = on and u.can_redo()
        self.n('BtnTplUndo').ToolTip = (u'Undo (Ctrl+Z): ' + u.next_undo_label()) if u.can_undo() else u'Nothing to undo'
        self.n('BtnTplRedo').ToolTip = (u'Redo (Ctrl+Y): ' + u.next_redo_label()) if u.can_redo() else u'Nothing to redo'

    def _on_preview_key(self, sender, args):
        """Ctrl+Z / Ctrl+Y undo template edits. In a search box they stay the box's own.
        Escape slides a previewed (not edited) template away."""
        if self.drawer.collapsed:
            return                      # parked: the drawer owns the keys
        if args.Key == Key.Escape and self.expanded and not self.pinned and not self.editing \
                and not isinstance(Keyboard.FocusedElement, TextBox):
            self.toggle_slide()
            args.Handled = True
            return
        if (Keyboard.Modifiers & ModifierKeys.Control) != ModifierKeys.Control:
            return
        focused = Keyboard.FocusedElement
        if isinstance(focused, TextBox) and not focused.Equals(self.n('TxtName')):
            return
        shift = (Keyboard.Modifiers & ModifierKeys.Shift) == ModifierKeys.Shift
        if args.Key == Key.Z and not shift:
            self.do_undo()
            args.Handled = True
        elif args.Key == Key.Y or (args.Key == Key.Z and shift):
            self.do_redo()
            args.Handled = True
        elif args.Key == Key.S and self.editing and self.dirty:
            self.save()
            args.Handled = True

    # ---- save ---------------------------------------------------------------
    def save(self):
        t = self.edit
        if t is None:
            return
        t.name = to_text(t.name).strip()
        if not t.name:
            self.status(u'Give the template a name.', u'bad')
            return
        others = [x.name.lower() for x in self.state.templates if x.id != t.id]
        if t.name.lower() in others:
            self.status(u'There is already a template called "{0}".'.format(t.name), u'bad')
            return
        if not t.src_cat_id or not t.tgt_cat_id:
            self.status(u'Choose both a source and a target category.', u'bad')
            return
        if not t.mappings:
            self.status(u'Add at least one parameter push.', u'bad')
            return
        t.modified = store.now_text()
        is_new = t.storage_id is None

        def work(uiapp):
            if is_new:
                return rv.save_records(self.state.doc, u'save template', creates=[(store.KIND_TEMPLATE, t)])
            return rv.save_records(self.state.doc, u'save template', updates=[t])

        def done(rep, error):
            if error or t not in rep['done']:
                why = rep['failed'][0][1] if (rep and rep['failed']) else u'see debug'
                self.status(u'Not saved: ' + why, u'bad')
                return
            saved = t.copy(keep_id=True)
            self.state.templates = [x for x in self.state.templates if x.id != t.id] + [saved]
            self.state.templates.sort(key=lambda x: store.natural_key(x.name))
            # saved: grey the editor out again, show the saved one, highlight it in the list
            self.just_saved = t.id
            self.edit = None
            self.state.data_changed()
            self._suspend = True
            try:
                self.grid.SelectedItems.Clear()
            finally:
                self._suspend = False
            if self.pinned:
                self.load_editor(saved.copy(keep_id=True), False, editing=False)
            else:
                self.load_editor(None, False)        # slide the editor away
            self.refresh_list()
            self.status(u'Saved "{0}" with {1} push(es) - highlighted green in the list.'.format(
                t.name, len(t.mappings)), u'ok')

        self.state.runner.submit(u'save template', work, done)

    # ---- duplicate / merge / delete ---------------------------------------
    def duplicate(self):
        sel = self.selected_templates()
        if len(sel) != 1 or not self.confirm_discard():
            return
        dup = store.duplicate_template(sel[0], [x.name for x in self.state.templates])

        def work(uiapp):
            return rv.save_records(self.state.doc, u'duplicate template', creates=[(store.KIND_TEMPLATE, dup)])

        def done(rep, error):
            if error or dup not in rep['done']:
                self.status(u'Duplicate failed.', u'bad')
                return
            self.state.templates.append(dup)
            self.edit, self.dirty = None, False
            self.just_saved = dup.id
            self.state.data_changed()
            self._suspend = True
            try:
                self.grid.SelectedItems.Clear()
            finally:
                self._suspend = False
            self.load_editor(dup.copy(keep_id=True), False, editing=False)
            self.refresh_list()
            self.status(u'Duplicated as "{0}".'.format(dup.name), u'ok')

        self.state.runner.submit(u'duplicate template', work, done)

    def merge(self):
        sel = self.selected_templates()
        if len(sel) < 2:
            return
        pairs = set((t.src_cat_id, t.tgt_cat_id) for t in sel)
        if len(pairs) > 1:
            self.status(u'Only templates for the same source and target categories can be merged.', u'bad')
            return
        if not self.confirm_discard():
            return
        order = sorted(range(len(sel)), key=lambda i: -sel[i].used)
        choices = [u'{0}   (used {1}, {2} pushes)'.format(sel[i].name, sel[i].used, len(sel[i].mappings))
                   for i in range(len(sel))]
        r = ui.prompt(self, u'Merge templates', u'Which template should the others merge into?\n'
                      u'It keeps its name; the pushes of the others are added to it.',
                      ok=u'Next', choices=choices, selected=order[0])
        if not r.get('ok') or r.get('index') is None:
            return
        master = sel[r['index']]
        others = [t for t in sel if t.id != master.id]
        try:
            merged, conflicts = store.merge_templates(master, others)
        except ValueError as ex:
            self.status(to_text(ex), u'bad')
            return
        other_ids = set(t.id for t in others)
        moving = [m for m in self.state.marriages if m.template_id in other_ids]
        msg = (u'Merge {0} template(s) into "{1}"?\n\n"{1}" will have {2} pushes. {3} marriage(s) move to it, '
               u'then {4} deleted.').format(len(others), master.name, len(merged.mappings), len(moving),
                                           u', '.join(u'"' + t.name + u'"' for t in others) + u' are')
        lines = None
        if conflicts:
            msg += u'\n\nThese target parameters are pushed by both - "{0}" wins:'.format(master.name)
            lines = [u'{0}: keeps "{1}", drops "{2}"'.format(c[0], c[1], c[2]) for c in conflicts]
        r2 = ui.prompt(self, u'Merge templates',
                       msg + u'\n\nAre you sure you know what you are doing?', ok=u'Merge', danger=True,
                       choices=lines, selected=None)
        if not r2.get('ok'):
            return
        old = dict((m.id, m.template_id) for m in moving)

        def work(uiapp):
            for m in moving:
                m.template_id = master.id
            rep1 = rv.save_records(self.state.doc, u'merge templates', updates=[merged] + moving)
            failed = set(id(o) for o, _r in rep1['failed'])
            blocked = set()
            for m in moving:
                if id(m) in failed:
                    blocked.add(old[m.id])
                    m.template_id = old[m.id]
            rep2 = {'done': [], 'failed': []}
            if merged in rep1['done']:
                rep2 = rv.save_records(self.state.doc, u'merge templates - delete',
                                       deletes=[t for t in others if t.id not in blocked])
            return rep1, rep2

        def done(result, error):
            if error:
                self._error(error)
                self.state.main.reload_from_model()
                return
            rep1, rep2 = result
            if merged in rep1['done']:
                gone = set(t.id for t in rep2['done'])
                self.state.templates = [merged.copy(keep_id=True) if t.id == master.id else t
                                        for t in self.state.templates if t.id not in gone]
            problems = rep1['failed'] + rep2['failed']
            self.edit, self.dirty = None, False
            self.state.data_changed()
            self.load_editor(None, False)
            if problems:
                self.status(u'Merged with {0} problem(s): {1}'.format(len(problems), problems[0][1]), u'bad')
            else:
                self.status(u'Merged into "{0}".'.format(master.name), u'ok')

        self.state.runner.submit(u'merge templates', work, done)

    def delete(self):
        sel = self.selected_templates()
        if not sel:
            return
        ids = set(t.id for t in sel)
        using = [m for m in self.state.marriages if m.template_id in ids]
        names = u', '.join(u'"' + t.name + u'"' for t in sel)
        if using:
            in_use = [t for t in sel if t.used]
            msg = (u'{0} of these template(s) {1} in use by {2} marriage(s):\n{3}\n\n'
                   u'Deleting leaves those marriages without a template. Values already pushed stay '
                   u'where they are. Delete anyway?').format(
                       len(in_use), u'is' if len(in_use) == 1 else u'are', len(using),
                       u', '.join(u'"{0}" ({1})'.format(t.name, t.used) for t in in_use))
            title = u'Template in use'
        else:
            msg = u'Delete {0}?'.format(names)
            title = u'Delete templates'
        r = ui.prompt(self, title, msg, ok=u'Delete', danger=True)
        if not r.get('ok'):
            return
        old = dict((m.id, m.template_id) for m in using)

        def work(uiapp):
            rep1 = {'done': [], 'failed': []}
            if using:
                for m in using:
                    m.template_id = u''
                rep1 = rv.save_records(self.state.doc, u'unassign templates', updates=using)
            failed = set(id(o) for o, _r in rep1['failed'])
            blocked = set()
            for m in using:
                if id(m) in failed:
                    blocked.add(old[m.id])
                    m.template_id = old[m.id]
            rep2 = rv.save_records(self.state.doc, u'delete templates',
                                   deletes=[t for t in sel if t.id not in blocked])
            return rep1, rep2

        def done(result, error):
            if error:
                self._error(error)
                return
            rep1, rep2 = result
            gone = set(t.id for t in rep2['done'])
            self.state.templates = [t for t in self.state.templates if t.id not in gone]
            if self.edit is not None and self.edit.id in gone:
                self.edit, self.dirty = None, False
                self.load_editor(None, False)
            self.state.data_changed()
            problems = rep1['failed'] + rep2['failed']
            if problems:
                self.status(u'Deleted {0}; {1} problem(s): {2}'.format(len(gone), len(problems), problems[0][1]),
                            u'bad')
            else:
                self.status(u'Deleted {0} template(s).'.format(len(gone)), u'ok')

        self.state.runner.submit(u'delete templates', work, done)

    # ---- library file -------------------------------------------------------
    def _folder(self):
        folder = to_text(self.state.settings.get(u'library_folder'))
        return folder if folder and os.path.isdir(folder) else u''

    def export_library(self):
        sel = self.selected_templates() or list(self.state.templates)
        if not sel:
            self.status(u'No templates to export yet.', u'warn')
            return
        dlg = SaveFileDialog()
        dlg.Title = u'Export Parameter Push Templates'
        dlg.Filter = u'RevoBIM template library (*.txt)|*.txt|All files (*.*)|*.*'
        dlg.FileName = u'RevoBIM Parameter Push Templates.txt'
        if self._folder():
            dlg.InitialDirectory = self._folder()
        if dlg.ShowDialog(self.win) != True:  # noqa: E712  (Nullable bool)
            return
        try:
            File.WriteAllText(dlg.FileName, store.export_templates(sel), Encoding.UTF8)
            self.state.settings[u'library_folder'] = to_text(os.path.dirname(dlg.FileName))
            self.state.save_settings()
            self.status(u'Exported {0} template(s) to {1}'.format(len(sel), dlg.FileName), u'ok')
        except Exception as ex:
            self.status(u'Export failed: ' + to_text(ex), u'bad')

    def import_library(self):
        dlg = OpenFileDialog()
        dlg.Title = u'Import Parameter Push Templates'
        dlg.Filter = u'RevoBIM template library (*.txt)|*.txt|All files (*.*)|*.*'
        if self._folder():
            dlg.InitialDirectory = self._folder()
        if dlg.ShowDialog(self.win) != True:  # noqa: E712
            return
        try:
            text = to_text(File.ReadAllText(dlg.FileName, Encoding.UTF8))
        except Exception as ex:
            self.status(u'Could not read the file: ' + to_text(ex), u'bad')
            return
        self.state.settings[u'library_folder'] = to_text(os.path.dirname(dlg.FileName))
        self.state.save_settings()
        incoming = store.import_templates(text)
        if not incoming:
            self.status(u'No templates found in that file.', u'warn')
            return
        plan = store.plan_import(incoming, self.state.templates)
        known = set(c[0] for c in self.cats)
        lines = []
        for t, action in plan:
            line = u'{0}: {1}   ({2})'.format(action, t.name, t.categories_label())
            if known and (t.src_cat_id not in known or t.tgt_cat_id not in known):
                line += u'   - category not used in this model yet'
            lines.append(line)
        r = ui.prompt(self, u'Import templates',
                      u'{0} template(s) in the file. "update" replaces the copy already in this model; '
                      u'"rename" is a different template with the same name.'.format(len(plan)),
                      ok=u'Import', choices=lines, selected=None)
        if not r.get('ok'):
            return
        by_id = dict((t.id, t) for t in self.state.templates)
        creates, updates = [], []
        for t, action in plan:
            if action == u'update':
                t.storage_id = by_id[t.id].storage_id
                updates.append(t)
            else:
                creates.append((store.KIND_TEMPLATE, t))

        def work(uiapp):
            return rv.save_records(self.state.doc, u'import templates', creates=creates, updates=updates)

        def done(rep, error):
            if error:
                self._error(error)
                return
            done_ids = set(t.id for t in rep['done'])
            keep = [t for t in self.state.templates if t.id not in done_ids]
            self.state.templates = keep + [t for t in rep['done']]
            self.state.templates.sort(key=lambda x: store.natural_key(x.name))
            self.state.data_changed()
            if rep['failed']:
                self.status(u'Imported {0}; {1} failed ({2}).'.format(
                    len(rep['done']), len(rep['failed']), rep['failed'][0][1]), u'bad')
            else:
                self.status(u'Imported {0} template(s).'.format(len(rep['done'])), u'ok')

        self.state.runner.submit(u'import templates', work, done)

    # ---- closing ------------------------------------------------------------
    def _on_closing(self, sender, args):
        try:
            if not self.confirm_discard():
                args.Cancel = True
        except Exception:
            pass

    def _on_closed(self, sender, args):
        try:
            if self._full is None:
                self.state.settings[u'tpl_list_w'] = to_text(int(self._list_w()))
                if self.expanded:
                    self._remember_edit_w()
                self.state.settings[u'tpl_h'] = to_text(int(self.win.Height))
            self.state.save_settings()
        except Exception:
            pass
        self.search_later.stop()
        try:
            self.grid.ItemsSource = None
            self.pgrid.ItemsSource = None
        except Exception:
            pass
        self.state.tpl_win = None


def open_window(state, prefill=None):
    w = TemplatesWindow(state)
    state.tpl_win = w
    try:
        w.win.Owner = state.main.win
    except Exception:
        pass
    w.refresh_list()
    try:
        if state.main is not None and state.main.drawer.collapsed:
            # the main window is parked as a bar - centring on it would open half off screen
            from System.Windows import WindowStartupLocation
            w.win.WindowStartupLocation = getattr(WindowStartupLocation, 'CenterScreen')
    except Exception:
        pass
    point = w.dock_point()
    if point is None:
        w.win.Show()
        w.load_categories(prefill)
        return w
    # pour out of the main window's footer - the reverse of Close back to Marriages
    w.win.Opacity = 0.0
    w.win.Show()
    try:
        w.win.UpdateLayout()
    except Exception:
        pass

    def landed():
        w.win.Opacity = 1.0
        try:
            w.win.Activate()
        except Exception:
            pass
        w.load_categories(prefill)
    ui.genie(w.win, point[0], point[1], landed, owner=state.main.win, reverse=True)
    return w
