# -*- coding: utf-8 -*-
u"""Hanger Automation - the Family Hangers and Family Floor Support tabs and
their Family settings dialog.

One FamTab class runs both tabs.  The floor tab (mode 'floor') has the same
controls with Flr in place of Fam in their names (hfam_core.flr_name), its own
settings (flr_ in place of fam_, fha_core.floor_key) and no drop rods; its jobs
get the settings remapped back to fam_ keys plus _mode = 'floor'.

All Python state lives on FamTab / FamSettingsDialog (plain Python objects);
nothing is attached to WPF controls except real WPF properties.  Revit is only
read through the window's ExternalEvent (start_quiet / start_job), never
directly from a click handler.
"""
import fha_clr  # noqa: F401  (must be first)
import fha_core as core
import hfam_core as fc
import hfam_revit as hr
import hcirc_core as cc
import hcirc_revit as hc
import fha_ui as ui
import fha_revit as frv
import hview_ui
from System.Windows import Visibility, FontWeights
from System.Windows.Controls import TextBlock

FAM_CHECKS = (('ChkFamRodPlace', u'fam_rod_place'), ('ChkFamRodRealign', u'fam_rod_realign'),
              ('ChkFamRodAuto', u'fam_rod_auto'), ('ChkFamDw144', u'fam_dw144'),
              ('ChkFamAccessory', u'fam_accessory'), ('ChkFamSkipExisting', u'fam_skip_existing'),
              ('ChkFamDims', u'fam_dims'), ('ChkFamInsPlace', u'fam_ins_place'),
              ('ChkFamInsRealign', u'fam_ins_realign'), ('ChkFamInsAuto', u'fam_ins_auto'),
              ('ChkFamRodLinked', u'fam_rod_linked'), ('ChkFamLockPlace', u'fam_lock_place'),
              ('ChkFamLockRealign', u'fam_lock_realign'), ('ChkFamLockAuto', u'fam_lock_auto'),
              ('ChkFamSetOnly', u'fam_set_only'))
FAM_BOXES = (('TxtFamSpacing', u'fam_spacing', 3000.0), ('TxtFamStart', u'fam_start_off', 300.0),
             ('TxtFamEnd', u'fam_end_off', 300.0), ('TxtFamFlange', u'fam_flange_clear', 150.0),
             ('TxtFamTakeoff', u'fam_takeoff_clear', 400.0), ('TxtFamDimOffset', u'fam_dim_offset', 800.0))
FAM_BUTTONS = ('BtnFamPlace', 'BtnFamRealign', 'BtnFamAuto', 'BtnFamRods', 'BtnFamSettings', 'BtnFamRefresh',
               'BtnFamRules')
ROD_CONTROLS = ('ChkFamRodPlace', 'ChkFamRodRealign', 'ChkFamRodAuto', 'ChkFamRodLinked', 'BtnFamRods')
DIM_DEFAULT = u'(default dimension type)'
NONE_LABEL = u'(none)'


def num_text(v):
    return u'{0:g}'.format(v)


LIST_H = 92.0                      # the family list's starting height
LIST_MIN, LIST_MAX = 60.0, 700.0   # how far its grip drags


def family_row(text, set_up):
    u"""(TextBlock, set up) for one line of the family list: a family already
    set up in Family settings is bold green."""
    tb = TextBlock()
    tb.Text = text
    if set_up:
        tb.FontWeight = FontWeights.Bold
        tb.SetResourceReference(TextBlock.ForegroundProperty, 'SetTextBrush')
        tb.ToolTip = u'Set up in Family settings'
    return tb, set_up


def list_height(h):
    u"""The family list height, kept between its limits."""
    try:
        h = float(h)
    except Exception:
        h = LIST_H
    if h != h:   # NaN (Height not set)
        h = LIST_H
    return max(LIST_MIN, min(LIST_MAX, h))


class FamTab(object):
    def __init__(self, owner, doc, mode=u'hang', items=None):
        self.o = owner
        self.mode = mode if mode in fc.MODES else u'hang'
        self.floor = self.mode == u'floor'
        self.noun = u'floor support' if self.floor else u'hanger'
        self.checks = [(n, k) for n, k in FAM_CHECKS if not (self.floor and n in ROD_CONTROLS)]
        self.buttons = [n for n in FAM_BUTTONS if not (self.floor and n in ROD_CONTROLS)]
        self.items = []
        self.shown = []
        self.previews = {}
        self.params = {}        # family name -> (parameter names, where they came from)
        self.fams = fc.load_families()
        self.loading = False
        self.want_preview = None
        self.busy = False
        self.view_ok = False
        self.fold = None
        self.ws_values = []
        self.ignored = set()   # families the user said to carry on with, unconfigured, this session
        self.open_doc = doc   # while the window is being built we are in Revit's API context: previews read directly
        if items is not None:
            self.items = list(items)
        else:
            try:
                self.items = hr.list_family_types(doc)   # the command's own API context
            except Exception:
                self.items = []
        dims = []
        try:
            dims = [d[0] for d in frv.linear_dimension_types(doc)]
            self.view_ok = hr.is_floor_plan(owner.uiapp.ActiveUIDocument.ActiveView)
        except Exception:
            pass
        for name in ('CmbFamDimType', 'CmbFamAutoDimType'):   # the Dimension placer and Auto place share them
            cd = self.c(name)
            cd.Items.Add(DIM_DEFAULT)
            for n in dims:
                cd.Items.Add(n)
        self.mirroring = False
        self.list_grow = 0.0
        self.rows = []          # (TextBlock, set up) for each family listed
        cb = self.c('CmbFamCategory')
        for _key, label in fc.CATEGORIES:
            cb.Items.Add(label)
        if self.floor:
            cbase = self.o.c('CmbFlrBase')
            for _key, label in core.BASES:
                cbase.Items.Add(label)

    def c(self, name):
        return self.o.c(fc.flr_name(name) if self.floor else name)

    def k(self, key):
        u"""This tab's settings key for a Family Hangers key."""
        return core.floor_key(key) if self.floor else key

    # ---- settings in and out
    def load(self, s):
        self.loading = True
        for name, key in self.checks:
            self.c(name).IsChecked = core.as_bool(s, self.k(key))
        for name, key, default in FAM_BOXES:
            self.c(name).Text = s.get(self.k(key), num_text(default))
        keys = [k for k, _l in fc.CATEGORIES]
        cat = s.get(self.k(u'fam_category'), u'all')
        self.c('CmbFamCategory').SelectedIndex = keys.index(cat) if cat in keys else 0
        self.c('TxtFamSearch').Text = s.get(self.k(u'fam_search'), u'')
        self.c('LstFamilies').Height = list_height(core.parse_mm(s.get(self.k(u'fam_list_h'), u'92'), LIST_H))
        want = s.get(self.k(u'fam_dim_type'), u'')
        for name in ('CmbFamDimType', 'CmbFamAutoDimType'):
            cd = self.c(name)
            cd.SelectedIndex = 0
            for i in range(int(cd.Items.Count)):
                if want and cd.Items[i] == want:
                    cd.SelectedIndex = i
        self.c('TxtFamAutoDimOffset').Text = self.c('TxtFamDimOffset').Text
        self.ws_values = ui.fill_workset_combo(self.c('CmbFamWorkset'), getattr(self.o, 'worksets', []),
                                               s.get(self.k(u'fam_workset'), u''))
        if self.floor:
            keys = [k for k, _l in core.BASES]
            base = s.get(u'flr_base', u'level')
            self.o.c('CmbFlrBase').SelectedIndex = keys.index(base) if base in keys else 0
            self.o.c('ChkFlrBaseLinked').IsChecked = core.as_bool(s, u'flr_base_linked')
        self.loading = False
        self.set_view_ok(self.view_ok)
        self.refill(s.get(self.k(u'fam_symbol'), u''))

    def gather(self, s):
        for name, key in self.checks:
            s[self.k(key)] = u'1' if self.c(name).IsChecked else u'0'
        for name, key, default in FAM_BOXES:
            s[self.k(key)] = num_text(core.parse_mm(self.c(name).Text, default))
        cd = self.c('CmbFamDimType')
        s[self.k(u'fam_dim_type')] = u'' if int(cd.SelectedIndex) <= 0 else u'{0}'.format(cd.SelectedItem)
        s[self.k(u'fam_category')] = self.category_key()
        if self.ws_values:
            s[self.k(u'fam_workset')] = core.workset_value(self.ws_values, self.c('CmbFamWorkset').SelectedIndex)
        if self.floor:
            i = int(self.o.c('CmbFlrBase').SelectedIndex)
            s[u'flr_base'] = core.BASES[i][0] if 0 <= i < len(core.BASES) else u'level'
            s[u'flr_base_linked'] = u'1' if self.o.c('ChkFlrBaseLinked').IsChecked else u'0'
        s[self.k(u'fam_search')] = u'{0}'.format(self.c('TxtFamSearch').Text or u'')
        s[self.k(u'fam_list_h')] = num_text(list_height(float(self.c('LstFamilies').Height)))
        it = self.current()
        if it is not None:
            s[self.k(u'fam_symbol')] = it['key']
        return s

    def wire(self):
        tools = ('Place', 'Realign', 'Auto', 'Dims') if self.floor else ('Place', 'Realign', 'Auto', 'Rods', 'Dims')
        self.fold = ui.Collapser(self.o.win, tools, on_change=self._fold_changed,
                                 on_resize=self.o.resize_for_fold, prefix=u'Flr' if self.floor else u'Fam')
        self.fold.load(u'')   # every tool starts folded; open the one you need
        self.c('BtnFamToggleAll').Click += self._toggle_all
        # Auto place's dimension distance and type mirror the Dimension placer's (one setting each)
        self.c('TxtFamDimOffset').TextChanged += self._mirror('TxtFamDimOffset', 'TxtFamAutoDimOffset', 'Text')
        self.c('TxtFamAutoDimOffset').TextChanged += self._mirror('TxtFamAutoDimOffset', 'TxtFamDimOffset', 'Text')
        self.c('CmbFamDimType').SelectionChanged += self._mirror('CmbFamDimType', 'CmbFamAutoDimType', 'SelectedIndex')
        self.c('CmbFamAutoDimType').SelectionChanged += self._mirror('CmbFamAutoDimType', 'CmbFamDimType', 'SelectedIndex')
        self.c('CmbFamCategory').SelectionChanged += self._filter_changed
        self.c('TxtFamSearch').TextChanged += self._filter_changed
        self.c('ChkFamSetOnly').Checked += self._filter_changed
        self.c('ChkFamSetOnly').Unchecked += self._filter_changed
        self.c('LstFamilies').SelectionChanged += self._picked
        self.c('ThmFamListSize').DragDelta += self._list_drag
        self.c('ThmFamListSize').DragCompleted += self._list_dropped
        self.c('BtnFamSettings').Click += self._settings_click
        self.c('BtnFamRefresh').Click += self._refresh_click
        self.c('BtnFamPlace').Click += self._place_click
        self.c('BtnFamRealign').Click += self._realign_click
        self.c('BtnFamAuto').Click += self._auto_click
        self.c('BtnFamDims').Click += self._dims_click
        if not self.floor:
            self.c('BtnFamRods').Click += self._rods_click
        self.c('BtnFamRules').Click += self._rules_click

    # ---- the family list: drag its grip to show more or fewer families
    def _list_drag(self, sender, e):
        try:
            lst = self.c('LstFamilies')
            old = float(lst.Height)
            new = list_height(old + float(e.VerticalChange))
            if abs(new - old) > 0.1:
                lst.Height = new
                self.list_grow += new - old
        except Exception:
            pass

    def _list_dropped(self, sender, e):
        grow, self.list_grow = self.list_grow, 0.0
        try:
            if abs(grow) > 0.5:
                self.o.resize_for_fold(grow)   # the window follows, like opening a tool
        except Exception:
            pass

    def _mirror(self, src, dst, prop):
        def changed(sender, e):
            if self.mirroring or self.loading:
                return
            self.mirroring = True
            try:
                setattr(self.c(dst), prop, getattr(self.c(src), prop))
            except Exception:
                pass
            finally:
                self.mirroring = False
        return changed

    # ---- folding tools
    def _toggle_all(self, sender, e):
        try:
            self.fold.set_all(not self.fold.all_open())
        except Exception:
            pass

    def _fold_changed(self):
        try:
            self.c('FamToggleAllTxt').Text = u'Collapse all' if self.fold.all_open() else u'Expand all'
        except Exception:
            pass

    def _rules_click(self, sender, e):
        try:
            dlg = RulesDialog(self.o, self.o.settings)
            if dlg.show():
                self.o.settings.update(dlg.result)
                self.o._save()
                self.o.status(u'Hanger rules saved')
        except Exception as ex:
            self.o.status(u'Hanger rules failed: {0}'.format(ex))

    def set_busy(self, busy):
        self.busy = busy
        for n in self.buttons:
            try:
                self.c(n).IsEnabled = not busy
            except Exception:
                pass
        self.set_view_ok(self.view_ok)

    def set_view_ok(self, ok):
        u"""The dimension placer only lights up in a floor plan."""
        self.view_ok = bool(ok)
        try:
            self.c('BtnFamDims').IsEnabled = self.view_ok and not self.busy
            self.c('FamDimHint').Visibility = Visibility.Collapsed if self.view_ok else Visibility.Visible
        except Exception:
            pass

    def debug_text(self):
        u"""Family settings and the chosen type, for Copy debug."""
        it = self.current()
        lines = [u'[{0}]'.format(u'Family Floor Support' if self.floor else u'Family Hangers'),
                 u'Chosen: {0}'.format(u'{0} ({1})'.format(it['key'], it['cat_label']) if it else u'(none)'),
                 u'Families listed: {0}'.format(len(self.items)),
                 u'Floor plan active: {0}'.format(self.view_ok)]
        if it is not None:
            lines.append(u'Chosen family settings: ' + u' | '.join(
                u'{0}={1}'.format(k, v) for k, v in sorted(self.cfg_for(it).items())))
            names, source = self.params.get(it['family'], ([], u'not read yet'))
            lines.append(u'Parameters ({0}): {1}'.format(source, u', '.join(names)))
        lines.append(fc.dump_families(self.fams))
        return u'\n'.join(lines)

    # ---- the list
    def category_key(self):
        i = int(self.c('CmbFamCategory').SelectedIndex)
        return fc.CATEGORIES[i][0] if 0 <= i < len(fc.CATEGORIES) else u'all'

    def refill(self, keep_key=None):
        if keep_key is None:
            cur = self.current()
            keep_key = cur['key'] if cur is not None else u''
        self.loading = True
        try:
            self.shown = fc.filter_types(self.items, self.category_key(), u'{0}'.format(self.c('TxtFamSearch').Text or u''))
            if self.c('ChkFamSetOnly').IsChecked:
                self.shown = [it for it in self.shown if fc.configured(self.fams, it['family'])]
            lst = self.c('LstFamilies')
            lst.Items.Clear()
            self.rows = []
            pick = -1
            for i, it in enumerate(self.shown):
                row = family_row(u'{0}  :  {1}'.format(it['family'], it['type']), fc.configured(self.fams, it['family']))
                self.rows.append(row)
                lst.Items.Add(row[0])
                if it['key'] == keep_key:
                    pick = i
            if pick < 0 and len(self.shown) == 1:
                pick = 0
            lst.SelectedIndex = pick
            if pick >= 0:
                lst.ScrollIntoView(lst.Items[pick])
        except Exception:
            pass
        finally:
            self.loading = False
        self.paint_rows()
        self._chosen_changed()

    def paint_rows(self):
        u"""Set-up families in bold green - the selected row in the normal text
        colour, so it still reads on the selection highlight."""
        try:
            sel = int(self.c('LstFamilies').SelectedIndex)
        except Exception:
            sel = -1
        for i, (tb, set_up) in enumerate(self.rows):
            if set_up:
                try:
                    tb.SetResourceReference(TextBlock.ForegroundProperty, 'TextBrush' if i == sel else 'SetTextBrush')
                except Exception:
                    pass

    def current(self):
        try:
            i = int(self.c('LstFamilies').SelectedIndex)
        except Exception:
            return None
        return self.shown[i] if 0 <= i < len(self.shown) else None

    def _filter_changed(self, sender, e):
        if not self.loading:
            self.refill()

    def _picked(self, sender, e):
        if not self.loading:
            self.paint_rows()
            self._chosen_changed()

    def cfg_for(self, it):
        names = self.params.get(it['family'], ([], u''))[0]
        return fc.fam_config(self.fams, it['family'], names)

    def _chosen_changed(self):
        it = self.current()
        txt = self.c('FamChosenTxt')
        if it is None:
            txt.Text = u'Choose the {0} family and type'.format(self.noun) if self.items else \
                u'No Generic Model, MEP Ancillary Framing or Duct Accessory families in the project'
            self.show_preview(None)
            return
        cfg = self.cfg_for(it)
        if cfg[u'left'] and cfg[u'right']:
            width = u'width: {0} / {1}'.format(cfg[u'left'], cfg[u'right'])
        else:
            width = u'width parameters not set - open Family settings'
        setup = u'' if fc.configured(self.fams, it['family']) else u'  |  not set up yet'
        if self.floor and cfg.get(u'style') == u'circ':
            txt.Text = u'{0}  |  Circular System Based  |  diameter: {1}  |  height: {2}{3}'.format(
                it['cat_label'], cfg[u'dia'] or u'(none)', cfg[u'circ_height'] or u'(none)', setup)
        elif self.floor:
            txt.Text = u'{0}  |  Rectangular Floor Based  |  {1}  |  first bar: {2}  |  height: {3}{4}'.format(
                it['cat_label'], width, cfg[u'first_bar'] or u'(none)', cfg[u'height'] or u'(none)', setup)
        elif cfg.get(u'style') == u'circ':
            txt.Text = u'{0}  |  Circular System Based  |  diameter: {1}  |  rod: {2}{3}'.format(
                it['cat_label'], cfg[u'dia'] or u'(none)', cfg[u'rod'] or u'(none)', setup)
        else:
            txt.Text = u'{0}  |  {1}  |  rod: {2}{3}'.format(it['cat_label'], width, cfg[u'rod'] or u'(none)', setup)
        if it['key'] in self.previews:
            self.show_preview(self.previews[it['key']])
        else:
            self.show_preview(None, u'Loading...')
            self.request_preview(it)

    # ---- preview (read through the ExternalEvent)
    def request_preview(self, it):
        self.want_preview = it['key']
        key = it['key']
        if self.open_doc is not None:   # opening the tool: read it now, so the chosen family shows at once
            try:
                data = hr.preview_bytes(self.open_doc, it['id'])
            except Exception:
                data = None
            self._got_preview(key, data)
            return
        started = self.o.start_quiet(hr.preview_job_for(it['id']),
                                     lambda res, err: self._got_preview(key, res))
        if not started:   # Revit busy with another read: try again when it finishes (retry_preview)
            self.show_preview(None, u'Loading...')

    def retry_preview(self):
        u"""A read has finished: fetch the chosen type's preview if it is still missing."""
        it = self.current()
        if it is not None and it['key'] not in self.previews and not self.o.busy:
            self.request_preview(it)

    def _got_preview(self, key, data):
        self.previews[key] = data
        it = self.current()
        if it is None:
            return
        if it['key'] == key:
            self.show_preview(data)
        elif it['key'] not in self.previews:
            self.request_preview(it)   # the selection moved on while we were reading

    def show_preview(self, data, hint=u'No preview'):
        img = self.c('FamPreview')
        lab = self.c('FamPreviewHint')
        try:
            if data:
                img.Source = ui.bitmap_from_bytes(data)
                lab.Visibility = Visibility.Collapsed
            else:
                img.Source = None
                lab.Text = hint
                lab.Visibility = Visibility.Visible
        except Exception:
            pass

    # ---- refresh
    def _refresh_click(self, sender, e):
        self.o.start_quiet(hr.list_job, self._got_list, u'Reading families...')

    def _got_list(self, res, err):
        if err or res is None:
            self.o.status(u'Could not read the families - see Copy debug')
            return
        self.items = res
        self.previews = {}
        self.refill()
        self.o.status(u'{0} {1} family types'.format(len(self.items), self.noun))

    # ---- family settings
    def _settings_click(self, sender, e):
        it = self.current()
        if it is None:
            self.o.status(u'Choose a family and type first')
            return
        if it['family'] in self.params:
            self.open_settings(it)
            return
        fam = it['family']

        def got(res, err):
            names, source = res if (res and not err) else ([], u'nothing - see Copy debug')
            self.params[fam] = (list(names), source)
            self.open_settings(it)
        self.o.start_quiet(hr.params_job_for(it['id']), got, u'Reading the family parameters...')

    def open_settings(self, it):
        names, source = self.params.get(it['family'], ([], u''))
        try:
            dlg = FamSettingsDialog(self.o, it, self.cfg_for(it), names, source, self.mode)
            if dlg.show():
                self.fams = fc.load_families()   # the other tab may have saved since
                self.fams[it['family']] = dlg.result
                fc.save_families(self.fams)
                self.o.family_settings_saved(self)
                self.o.status(u'Settings saved for {0}'.format(it['family']))
                self.refill()
        except Exception as ex:
            self.o.status(u'Family settings failed: {0}'.format(ex))

    # ---- the three tools
    def job_extra(self, s):
        u"""What a job needs from this tab.  The floor tab hands its own flr_
        settings over as the fam_ keys the jobs read, no drop rods, and
        _mode = 'floor' so the jobs fit floor supports."""
        if self.floor:
            for key in list(s):
                fk = core.floor_key(key)
                if fk != key and fk in s:
                    s[key] = s[fk]
            for key in core.FLOOR_SKIP:
                if u'_rod_' in key:
                    s[key] = u'0'
        s[u'_mode'] = self.mode
        s[u'_ui'] = getattr(self.o, 'dim_ui', None)   # asks where dimensions go from a 3D view
        it = self.current()
        if it is not None:
            cfg = dict(self.cfg_for(it))
            cfg[u'mode'] = self.mode
            s[u'_fam'] = {'id': it['id'], 'family': it['family'], 'cfg': cfg}
        s[u'_fams'] = dict((f, dict(fc.fam_config(self.fams, f), mode=self.mode)) for f in self.fams)

    def reload_families(self):
        self.fams = fc.load_families()
        self.refill()   # set-up families are shown in bold green

    def _run(self, job, circ_job=None):
        u"""Start a tool.  A floor support family saved as Circular System Based
        runs its own job (hcirc_revit); everything else runs the job given."""
        it = self.current()
        if it is None:
            self.o.status(u'Choose a {0} family and type first'.format(self.noun))
            return
        if not fc.configured(self.fams, it['family']) and it['family'] not in self.ignored:
            ans = self.ask_setup(it)
            if ans == u'setup':
                self._settings_click(None, None)
                return
            if ans != u'ignore':
                return
            self.ignored.add(it['family'])   # not asked again this session
        cfg = self.cfg_for(it)
        if self.circular(cfg):
            if not (cfg[u'dia'] and (cfg[u'circ_height'] or not self.floor)):
                self.o.status(u'Set the diameter{0} parameter{1} in Family settings first'.format(
                    u' and support height' if self.floor else u'', u's' if self.floor else u''))
                return
            self.o.start_job(circ_job, self.job_extra)
            return
        else:
            if not (cfg[u'left'] and cfg[u'right']):
                self.o.status(u'Set the two width parameters in Family settings first')
                return
            if self.floor and not (cfg[u'first_bar'] and cfg[u'height']):
                self.o.status(u'Set the first bar and support height parameters in Family settings first')
                return
        self.o.start_job(job, self.job_extra)

    def ask_setup(self, it):
        u"""A family never set up: 'setup' (open Family settings), 'ignore' or None."""
        style = (u' - Rectangular Floor Based or Circular System Based -' if self.floor else
                 u' - Rectangular Hanger System or Circular System Based -')
        return hview_ui.Prompt(
            self.o, u'Family settings', u'Set up the family first',
            u'"{0}" has not been set up yet. Family settings tells the tool which of its parameters set the '
            u'width, height{1} and the rest{2}. Ignore carries on with the parameters guessed from their names.'.format(
                it['family'], u' and first bar' if self.floor else u' and drop rod', style),
            [(u'ignore', u'Ignore and carry on', False), (u'setup', u'Set up the family', True)]).show()

    def circular(self, cfg):
        u"""The chosen family is saved as Circular System Based (a floor support
        or, from 1.14.0, a hanger): it runs the circular jobs (hcirc_revit)."""
        return cc.is_circ(dict(cfg or {}, mode=self.mode))

    def _place_click(self, sender, e):
        self._run(hr.job_place, hc.job_place)

    def _realign_click(self, sender, e):
        self._run(hr.job_realign, hc.job_realign)

    def _auto_click(self, sender, e):
        self._run(hr.job_auto, hc.job_auto)

    def _rods_click(self, sender, e):
        self.o.start_job(hr.job_rods, self.job_extra)

    def _dims_click(self, sender, e):
        if not self.view_ok:
            self.o.status(u'Open a floor plan first')
            return
        self.o.start_job(hc.job_dims, self.job_extra)   # changes nothing for rectangular families


class RulesDialog(object):
    u"""The rules for hanging several services together."""
    def __init__(self, owner, settings):
        self.o = owner
        self.ok = False
        self.result = None
        self.win = ui.load_xaml_window(u'HangerRules.xaml')
        ui.apply_palette(self.win, owner.mode)
        ui.place_dialog(self.win, owner)
        self.drawer = ui.dialog_drawer(self, owner, self.c('RulesHeader'), self.c('RulesShrinkBtn'),
                                       self.c('RulesShrinkIcon'), self.c('RulesExpandIcon'))
        self.c('RulesVerTxt').Text = u'v{0}'.format(core.__version__)
        self.c('RulesZ').Text = settings.get(u'fam_group_z', u'50')
        self.c('RulesGap').Text = settings.get(u'fam_group_gap', u'500')
        self.c('RulesAngle').Text = settings.get(u'fam_group_angle', u'2')
        keys = [k for k, _l in fc.CENTRES]
        for _k, label in fc.CENTRES:
            self.c('RulesCentre').Items.Add(label)
        cur = settings.get(u'fam_group_centre', u'mean')
        self.c('RulesCentre').SelectedIndex = keys.index(cur) if cur in keys else 0
        self.c('RulesSave').Click += self._save
        self.c('RulesCancel').Click += self._cancel
        self.c('RulesCloseBtn').Click += self._cancel
        self.c('RulesHeader').MouseLeftButtonDown += self._drag

    def c(self, name):
        return self.win.FindName(name)

    def _drag(self, sender, e):
        try:
            self.win.DragMove()
        except Exception:
            pass

    def _save(self, sender, e):
        try:
            i = int(self.c('RulesCentre').SelectedIndex)
            self.result = {
                u'fam_group_z': num_text(core.parse_mm(self.c('RulesZ').Text, 50.0)),
                u'fam_group_gap': num_text(core.parse_mm(self.c('RulesGap').Text, 500.0)),
                u'fam_group_angle': num_text(min(45.0, core.parse_mm(self.c('RulesAngle').Text, 2.0))),
                u'fam_group_centre': fc.CENTRES[i][0] if 0 <= i < len(fc.CENTRES) else u'mean',
            }
            self.ok = True
        except Exception:
            self.ok = False
        self.win.Close()

    def _cancel(self, sender, e):
        self.win.Close()

    def show(self):
        self.win.ShowDialog()
        return self.ok


FLOOR_ROWS = ('DlgFirstBarLbl', 'DlgFirstBar', 'DlgHeightLbl', 'DlgHeight', 'DlgHeightClearLbl', 'DlgHeightClear')
HANG_ROWS = ('DlgRodLbl', 'DlgRod', 'DlgSoffitLbl', 'DlgSoffit')


# rows of the Circular System Based tab that belong to one family tab only
CIRC_FLOOR_ROWS = ('DlgCircHeightLbl', 'DlgCircHeight')               # floor supports: support height
CIRC_HANG_ROWS = ('DlgCircRodLbl', 'DlgCircRod', 'DlgCircSoffitLbl', 'DlgCircSoffit')   # hangers: drop rod
CIRC_HANG_NOTE = (u'The hanger goes on the service\'s level with its reference on the centreline of the pipe, round '
                  u'duct or round FAB duct where it hangs (so it follows a sloping pipe), turned so the service runs '
                  u'along the axis chosen. The diameter parameter takes the service\'s diameter (with its insulation '
                  u'when the hanger goes round it) and the drop rod runs from the centreline up to the level or '
                  u'structure above. Rectangular services are skipped, and each hanger goes round one service.')


class FamSettingsDialog(object):
    u"""Which parameters stretch the hanger, which is the drop rod (hangers) or
    the first bar offset and support height (floor supports), which way the
    width runs and where the rod stops - saved per family."""
    def __init__(self, owner, item, cfg, names, source, mode=u'hang'):
        self.o = owner
        self.item = item
        self.cfg = cfg
        self.floor = mode == u'floor'
        self.ok = False
        self.result = None
        self.win = ui.load_xaml_window(u'HangerFamilySettings.xaml')
        ui.apply_palette(self.win, owner.mode)
        ui.place_dialog(self.win, owner)
        self.drawer = ui.dialog_drawer(self, owner, self.c('DlgHeader'), self.c('DlgShrinkBtn'),
                                       self.c('DlgShrinkIcon'), self.c('DlgExpandIcon'))
        self.c('DlgFamilyTxt').Text = u'{0} : {1}'.format(item['family'], item['type'])
        self.c('DlgSourceTxt').Text = (u'Parameters read from {0}.'.format(source) if names
                                        else u'No parameters could be read ({0}).'.format(source or u'?'))
        self.c('DlgVerTxt').Text = u'v{0}'.format(core.__version__)
        for name, key in (('DlgLeft', u'left'), ('DlgRight', u'right'), ('DlgRod', u'rod'),
                          ('DlgFirstBar', u'first_bar'), ('DlgHeight', u'height'),
                          ('DlgDia', u'dia'), ('DlgCircHeight', u'circ_height')):
            self._fill(self.c(name), names, cfg.get(key, u''))
        self._fill(self.c('DlgCircRod'), names, cfg.get(u'rod', u''))
        self._fill_pairs(self.c('DlgCircAxis'), fc.RUN_AXES, cfg.get(u'circ_axis', u'X'))
        self._fill_pairs(self.c('DlgCircSoffit'), fc.SOFFITS, cfg.get(u'soffit', u'level'))
        self.style = cfg.get(u'style', u'rect')
        self.c('DlgHeightClear').Text = cfg.get(u'height_clear', u'0')
        for n in (HANG_ROWS if self.floor else FLOOR_ROWS):
            self.c(n).Visibility = Visibility.Collapsed
        # both tabs: Rectangular (Floor Based / Hanger System) and Circular System Based
        self.c('DlgStyleTabs').Visibility = Visibility.Visible
        self.c('DlgTabRect').Click += lambda s, e: self.show_style(u'rect')
        self.c('DlgTabCirc').Click += lambda s, e: self.show_style(u'circ')
        for n in (CIRC_FLOOR_ROWS if not self.floor else CIRC_HANG_ROWS):
            self.c(n).Visibility = Visibility.Collapsed
        if not self.floor:
            self.c('DlgTabRectTxt').Text = u'Rectangular Hanger System'
            self.c('DlgTabRect').ToolTip = u'A bearer under the service, stretched to its width, on drop rods'
            self.c('DlgTabCirc').ToolTip = u'A ring round a pipe or round duct, hung on a drop rod'
            self.c('DlgCircNoteTxt').Text = CIRC_HANG_NOTE
        self.show_style(self.style)
        if self.floor:
            self.c('DlgTitleTxt').Text = u'Floor support family settings'
            self.c('DlgNoteTxt').Text = (u'The support stands on the service\'s level. The first bar offset is set to the '
                                         u'service invert above that level and the support height to the service\'s depth '
                                         u'(both with insulation when the support goes round it), plus the clearance above. '
                                         u'Each width parameter is half the service width plus the clearance.')
        self._fill_pairs(self.c('DlgAxis'), fc.AXES, cfg.get(u'axis', u'X'))
        self._fill_pairs(self.c('DlgSoffit'), fc.SOFFITS, cfg.get(u'soffit', u'level'))
        self.c('DlgClear').Text = cfg.get(u'clearance', u'0')
        self.c('DlgSwap').IsChecked = cfg.get(u'swap', u'0') == u'1'
        self.c('DlgSave').Click += self._save
        self.c('DlgCancel').Click += self._cancel
        self.c('DlgCloseBtn').Click += self._cancel
        self.c('DlgHeader').MouseLeftButtonDown += self._drag

    def c(self, name):
        return self.win.FindName(name)

    def show_style(self, style):
        u"""Rectangular Floor Based / Circular System Based: the tab showing is
        the style the family is saved as."""
        self.style = style if style in (u'rect', u'circ') else u'rect'
        circ = self.style == u'circ'
        self.c('DlgRectPanel').Visibility = Visibility.Collapsed if circ else Visibility.Visible
        self.c('DlgCircPanel').Visibility = Visibility.Visible if circ else Visibility.Collapsed
        ui.set_style(self.c('DlgTabRect'), 'Tab' if circ else 'TabActive')
        ui.set_style(self.c('DlgTabCirc'), 'TabActive' if circ else 'Tab')

    @staticmethod
    def _fill(combo, names, value):
        items = [NONE_LABEL] + list(names)
        if value and value not in items:
            items.append(value)
        for n in items:
            combo.Items.Add(n)
        combo.SelectedIndex = items.index(value) if value in items else 0

    @staticmethod
    def _fill_pairs(combo, pairs, value):
        keys = [k for k, _l in pairs]
        for _k, label in pairs:
            combo.Items.Add(label)
        combo.SelectedIndex = keys.index(value) if value in keys else 0

    @staticmethod
    def _value(combo):
        v = u'{0}'.format(combo.SelectedItem or u'')
        return u'' if v == NONE_LABEL else v

    def _drag(self, sender, e):
        try:
            self.win.DragMove()
        except Exception:
            pass

    def _save(self, sender, e):
        # a circular hanger keeps its drop rod rows on its own tab
        circ_hang = self.style == u'circ' and not self.floor
        rod_box = 'DlgCircRod' if circ_hang else 'DlgRod'
        soffit_box = 'DlgCircSoffit' if circ_hang else 'DlgSoffit'
        try:
            self.result = {
                u'left': self._value(self.c('DlgLeft')),
                u'right': self._value(self.c('DlgRight')),
                u'rod': self._value(self.c(rod_box)),
                u'axis': fc.AXES[max(0, self.c('DlgAxis').SelectedIndex)][0],
                u'soffit': fc.SOFFITS[max(0, self.c(soffit_box).SelectedIndex)][0],
                u'clearance': num_text(core.parse_mm(self.c('DlgClear').Text, 0.0)),
                u'swap': u'1' if self.c('DlgSwap').IsChecked else u'0',
                u'first_bar': self._value(self.c('DlgFirstBar')),
                u'height': self._value(self.c('DlgHeight')),
                u'height_clear': num_text(core.parse_mm(self.c('DlgHeightClear').Text, 0.0)),
                u'style': self.style,
                u'dia': self._value(self.c('DlgDia')),
                u'circ_height': self._value(self.c('DlgCircHeight')),
                u'circ_axis': fc.RUN_AXES[max(0, self.c('DlgCircAxis').SelectedIndex)][0],
            }
            self.ok = True
        except Exception:
            self.ok = False
        self.win.Close()

    def _cancel(self, sender, e):
        self.win.Close()

    def show(self):
        self.win.ShowDialog()
        return self.ok
