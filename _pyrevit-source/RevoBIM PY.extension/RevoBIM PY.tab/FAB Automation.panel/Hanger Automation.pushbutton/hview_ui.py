# -*- coding: utf-8 -*-
u"""Hanger Automation - prompts and the Dimension views picker.

Used by the Auto place tools when Dimension each run is ticked but the active
view cannot take dimensions (a 3D view): ask to skip or choose views, a picker
with Sheets and Views tabs (house search, ticks, highlight-and-tick), then
after the run an offer to open the views or sheets that got dimensions.

The jobs reach this through settings['_ui'] (a DimViewsUI), so hfam_revit /
fha_revit never import WPF.  Every window here carries a shrink drawer.
"""
import fha_clr  # noqa: F401  (must be first)
import fha_core as core
import fha_ui as ui
from System.Windows import Visibility
from System.Windows.Controls import Button, CheckBox


# ===================================================================== prompt
class Prompt(object):
    u"""A themed question with buttons; show() returns the key of the one pressed
    (None when closed with the X)."""
    def __init__(self, owner, title, heading, text, buttons):
        self.o = owner
        self.answer = None
        self.win = ui.load_xaml_window(u'HangerPrompt.xaml')
        ui.apply_palette(self.win, getattr(owner, 'mode', u'auto'))
        ui.place_dialog(self.win, owner)
        self.drawer = ui.dialog_drawer(self, owner, self.c('PromptHeader'), self.c('PromptShrinkBtn'),
                                       self.c('PromptShrinkIcon'), self.c('PromptExpandIcon'))
        self.c('PromptVerTxt').Text = u'v{0}'.format(core.__version__)
        self.c('PromptTitleTxt').Text = title
        self.c('PromptHeading').Text = heading
        self.c('PromptText').Text = text
        self.buttons = []
        for key, label, primary in buttons:
            b = Button()
            b.Content = label
            b.Margin = ui.thickness(8, 0, 0, 0)
            if primary:
                ui.set_style(b, 'Primary')
            b.Click += self._clicker(key)
            self.c('PromptButtons').Children.Add(b)
            self.buttons.append((key, b))
        self.c('PromptCloseBtn').Click += self._close
        self.c('PromptHeader').MouseLeftButtonDown += self._drag

    def c(self, name):
        return self.win.FindName(name)

    def _clicker(self, key):
        def click(sender, e):
            self.answer = key
            self.win.Close()
        return click

    def _close(self, sender, e):
        self.answer = None
        self.win.Close()

    def _drag(self, sender, e):
        try:
            self.win.DragMove()
        except Exception:
            pass

    def show(self):
        self.win.ShowDialog()
        return self.answer


# ============================================================== view picker
class DimViewsDialog(object):
    u"""Sheets and Views tabs.  rows: [{'key', 'name', 'type', 'scale'}];
    sheets: [{'key', 'number', 'name', 'views': [view keys]}].  show() returns
    {'views': [keys], 'sheets': [keys]} on Apply, None on Skip / close."""
    def __init__(self, owner, rows, sheets, intro=None):
        self.o = owner
        self.rows, self.sheets = list(rows), list(sheets)
        self.result = None
        self.suspend = False
        self.tab = u'views'      # Views first, filtered to floor plans
        self.win = ui.load_xaml_window(u'HangerDimViews.xaml')
        ui.apply_palette(self.win, getattr(owner, 'mode', u'auto'))
        ui.place_dialog(self.win, owner)
        self.drawer = ui.dialog_drawer(self, owner, self.c('DvHeader'), self.c('DvShrinkBtn'),
                                       self.c('DvShrinkIcon'), self.c('DvExpandIcon'))
        self.c('DvVerTxt').Text = u'v{0}'.format(core.__version__)
        if intro:
            self.c('DvIntroTxt').Text = intro
        # one CheckBox per row, kept for the life of the dialog so ticks survive searches
        self.view_boxes = [(r, self._box(core.view_row_text(r))) for r in
                           sorted(self.rows, key=lambda r: (r['type'] not in core.PLAN_VIEW_TYPES, core.natural_key(r['name'])))]
        self.sheet_boxes = [(r, self._box(core.sheet_row_text(r))) for r in
                            sorted(self.sheets, key=lambda r: core.natural_key(r['number']))]
        self.c('TxtSheetsSearch').Text = u''
        self.c('TxtViewsSearch').Text = u''
        kinds = self.c('CmbViewsKind')
        for _k, label in core.VIEW_KINDS:
            kinds.Items.Add(label)
        kinds.SelectedIndex = 0   # Floor plans
        self.c('TabDvSheetsTxt').Text = u'Sheets ({0})'.format(len(self.sheets))
        self.c('TabDvViewsTxt').Text = u'Views ({0})'.format(len(self.rows))
        self._wire()
        self.refill()
        self.show_tab(self.tab)

    def c(self, name):
        return self.win.FindName(name)

    def _box(self, text):
        b = CheckBox()
        b.Content = text
        b.IsChecked = False      # set before the handlers (a start value is not a tick)
        b.Checked += self._ticked
        b.Unchecked += self._ticked
        return b

    def _wire(self):
        self.c('TabDvSheets').Click += lambda s, e: self.show_tab(u'sheets')
        self.c('TabDvViews').Click += lambda s, e: self.show_tab(u'views')
        self.c('TxtSheetsSearch').TextChanged += lambda s, e: self.refill()
        self.c('TxtViewsSearch').TextChanged += lambda s, e: self.refill()
        self.c('CmbViewsKind').SelectionChanged += lambda s, e: self.refill()
        self.c('BtnSheetsTickShown').Click += lambda s, e: self.tick_shown(u'Sheets', True)
        self.c('BtnSheetsUntickShown').Click += lambda s, e: self.tick_shown(u'Sheets', False)
        self.c('BtnViewsTickShown').Click += lambda s, e: self.tick_shown(u'Views', True)
        self.c('BtnViewsUntickShown').Click += lambda s, e: self.tick_shown(u'Views', False)
        self.c('DvApply').Click += self._apply
        self.c('DvSkip').Click += self._skip
        self.c('DvCloseBtn').Click += self._skip
        self.c('DvHeader').MouseLeftButtonDown += self._drag

    # ---- tabs and lists
    def show_tab(self, name):
        self.tab = name if name in (u'sheets', u'views') else u'sheets'
        sheets = self.tab == u'sheets'
        self.c('SheetsPanel').Visibility = Visibility.Visible if sheets else Visibility.Collapsed
        self.c('ViewsPanel').Visibility = Visibility.Collapsed if sheets else Visibility.Visible
        ui.set_style(self.c('TabDvSheets'), 'TabActive' if sheets else 'Tab')
        ui.set_style(self.c('TabDvViews'), 'Tab' if sheets else 'TabActive')

    def shown(self, which):
        u"""The (row, box) pairs the search (and kind filter) leave showing."""
        if which == u'Sheets':
            keep = set(id(r) for r in core.filter_sheet_rows(self.sheets, self.c('TxtSheetsSearch').Text or u''))
            return [(r, b) for r, b in self.sheet_boxes if id(r) in keep]
        i = int(self.c('CmbViewsKind').SelectedIndex)
        kind = core.VIEW_KINDS[i][0] if 0 <= i < len(core.VIEW_KINDS) else u'floor'
        keep = set(id(r) for r in core.filter_view_rows(self.rows, self.c('TxtViewsSearch').Text or u'', kind))
        return [(r, b) for r, b in self.view_boxes if id(r) in keep]

    def refill(self):
        for which in (u'Sheets', u'Views'):
            lst = self.c('Lst' + which)
            lst.Items.Clear()
            for _r, b in self.shown(which):
                lst.Items.Add(b)
        self.count()

    def tick_shown(self, which, on):
        self.suspend = True
        try:
            for _r, b in self.shown(which):
                b.IsChecked = on
        finally:
            self.suspend = False
        self.count()

    def _ticked(self, sender, e):
        u"""Ticking a highlighted row ticks every highlighted row (house rule)."""
        if self.suspend:
            return
        self.suspend = True
        try:
            for which in (u'Sheets', u'Views'):
                lst = self.c('Lst' + which)
                sel = [x for x in lst.SelectedItems] if lst.SelectedItems is not None else []
                if any(x is sender for x in sel):
                    for x in sel:
                        x.IsChecked = sender.IsChecked
        except Exception:
            pass
        finally:
            self.suspend = False
        self.count()

    def picked(self):
        views = [r['key'] for r, b in self.view_boxes if b.IsChecked]
        sheets = [r['key'] for r, b in self.sheet_boxes if b.IsChecked]
        return views, sheets

    def count(self):
        views, sheets = self.picked()
        total = core.chosen_views(views, sheets, self.sheets)
        try:
            self.c('SheetsCountTxt').Text = u'{0} of {1} ticked'.format(len(sheets), len(self.sheets))
            self.c('ViewsCountTxt').Text = u'{0} of {1} ticked'.format(len(views), len(self.rows))
            if total:
                self.c('DvStatusTxt').Text = u'{0} sheet{1} and {2} view{3} ticked - dimensions go in {4} view{5}'.format(
                    len(sheets), u'' if len(sheets) == 1 else u's', len(views), u'' if len(views) == 1 else u's',
                    len(total), u'' if len(total) == 1 else u's')
            else:
                self.c('DvStatusTxt').Text = u'Nothing ticked - tick sheets or views, or Skip dimensions'
            self.c('DvApply').IsEnabled = bool(total)
        except Exception:
            pass

    # ---- close
    def _apply(self, sender, e):
        views, sheets = self.picked()
        if not core.chosen_views(views, sheets, self.sheets):
            return
        self.result = {'views': views, 'sheets': sheets}
        self.win.Close()

    def _skip(self, sender, e):
        self.result = None
        self.win.Close()

    def _drag(self, sender, e):
        try:
            self.win.DragMove()
        except Exception:
            pass

    def show(self):
        self.win.ShowDialog()
        return self.result


# ================================================================ for jobs
class DimViewsUI(object):
    u"""Handed to the jobs as settings['_ui'] by the window: every question a job
    asks mid-run (dimension views, the floor support base, opening views)."""
    def __init__(self, owner):
        self.o = owner

    def choose_dim_views(self, view_name, rows, sheets):
        u"""None to skip, else {'views': [keys], 'sheets': [keys]}."""
        if not rows:
            Prompt(self.o, u'Dimension views', u'No plan or section views to dimension in',
                   u'Dimension each run is ticked, but this model has no floor plans or sections. '
                   u'The hangers will be placed without dimensions.', [(u'ok', u'OK', True)]).show()
            return None
        ans = Prompt(self.o, u'Dimension views', u'Where should the run dimensions go?',
                     u'Dimension each run is ticked, but "{0}" is a 3D view - dimensions go in floor plans and '
                     u'sections. Choose the sheets or views to put them in, or carry on without them.'.format(view_name),
                     [(u'skip', u'No - skip dimension placement', False), (u'choose', u'Choose views...', True)]).show()
        if ans != u'choose':
            return None
        return DimViewsDialog(self.o, rows, sheets).show()

    def ask_base_pick(self, linked):
        u"""Floor supports standing on a picked element: say what to click next.
        'pick' or 'level' (the X stands them on the level too)."""
        where = u'in the linked model ' if linked else u''
        return Prompt(self.o, u'Floor support base', u'Now click the floor, roof or equipment the supports stand on',
                      u'After you press Pick it, click it in Revit {0}- the status bar at the bottom left says what to '
                      u'click. {1}Each support is lifted onto its top surface and stays hosted on its level. '
                      u'Esc in Revit stands them on the level instead.'.format(
                          where, u'Click the link first, then the element inside it. ' if not linked else u''),
                      [(u'level', u'Stand on the level', False), (u'pick', u'Pick it in Revit', True)]).show()

    def ask_open(self, n_runs, views, sheets):
        u"""After the run: 'sheets', 'views' or None.  views / sheets: names."""
        buttons = [(None, u'No thanks', False)]
        if views:
            buttons.append((u'views', u'Open the {0} view{1}'.format(len(views), u'' if len(views) == 1 else u's'),
                            not sheets))
        if sheets:
            buttons.append((u'sheets', u'Open the {0} sheet{1}'.format(len(sheets), u'' if len(sheets) == 1 else u's'), True))
        names = (sheets or views)[:6]
        more = len(sheets or views) - len(names)
        return Prompt(self.o, u'Dimension views', u'Done - {0} run{1} dimensioned'.format(n_runs, u'' if n_runs == 1 else u's'),
                      u'Would you like to open the {0} with the dimensions?\n{1}{2}'.format(
                          u'sheets' if sheets else u'views', u'\n'.join(names),
                          u'\n... and {0} more'.format(more) if more > 0 else u''), buttons).show()
