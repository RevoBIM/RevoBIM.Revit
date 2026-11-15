# -*- coding: utf-8 -*-
"""Space Data Push - the window: rows of space parameter -> element parameter,
the two pick buttons, the activity log, theme, settings and the easter egg.

Every read or write of the model goes out through the Runner (ExternalEvent), and
the window never waits for it: a job is queued, the handler returns, and the
result is marshalled back with UI.on_ui.
"""
import sdp_clr

import os
import time
import traceback

import sdp_logic as L
import sdp_model as M
import sdp_theme as T
import sdp_ui as UI
from sdp_runner import Runner
from sdp_version import __version__, TOOL_NAME, PARK_KEY

from System import AppDomain, TimeSpan
from System.Windows import FontWeights, FrameworkElement, GridLength, GridUnitType
from System.Windows import HorizontalAlignment, TextTrimming, TextWrapping, Thickness
from System.Windows import VerticalAlignment, Window, WindowState
from System.Windows import CornerRadius
from System.Windows.Controls import Border, Button, ColumnDefinition, ComboBox, Grid, TextBlock
from System.Windows.Data import Binding, RelativeSource, RelativeSourceMode
from System.Windows.Media import Geometry
from System.Windows.Shapes import Ellipse, Path
from System.Windows.Threading import DispatcherTimer

WATCHDOG_SECONDS = 20
LOG_LIMIT = 400
DEFAULT_CATEGORY_NAME = u'Detail Items'

LEVEL_BRUSH = {
    u'ok': 'GreenBrush', u'same': 'MutedBrush', u'skip': 'OrangeBrush',
    u'fail': 'RedBrush', u'warn': 'OrangeBrush', u'info': 'MutedBrush',
    u'head': 'TextBrush',
}
PREVIEW_BRUSH = {u'value': 'TextBrush', u'blank': 'OrangeBrush', u'none': 'MutedBrush'}
DOT_BRUSH = {'follow': 'BlueBrush', 'dark': 'MutedBrush', 'light': 'OrangeBrush'}

_LIVE = []


# ------------------------------------------------------------------ first read

class OpenData(object):
    """What the window needs before it can be drawn. Read inside the command, where
    the API is valid, so the first paint never depends on the ExternalEvent."""

    def __init__(self, doc, settings):
        self.cats = M.read_categories(doc)
        self.space_params = M.read_space_params(doc)
        self.category = pick_default_category(self.cats, settings.get('category'))
        self.target_params = []
        if self.category is not None:
            self.target_params = M.read_category_params(doc, self.category)


def pick_default_category(cats, saved):
    """The saved category, else Detail Items, else the first one."""
    wanted = None
    try:
        wanted = int(saved) if saved not in (None, u'') else None
    except Exception:
        wanted = None
    if wanted is not None:
        for c in cats:
            if c.value == wanted:
                return c
    try:
        detail = M.detail_items_value()
    except Exception:
        detail = None
    for c in cats:
        if detail is not None and c.value == detail:
            return c
    for c in cats:
        if c.name == DEFAULT_CATEGORY_NAME:
            return c
    return cats[0] if cats else None


class Row(object):
    """One mapped pair: a space parameter and the element parameter it goes to."""

    def __init__(self, src, dst):
        self.src = src
        self.dst = dst
        self.grid = None
        self.src_box = None
        self.src_filter = None
        self.preview = None
        self.dst_box = None
        self.dst_filter = None
        self.remove_btn = None
        self.keep = []


# ---------------------------------------------------------------------- window

class SdpWindow(object):

    def __init__(self, uiapp, runner, data, settings):
        self.uiapp = uiapp
        self.runner = runner
        self.settings = settings
        self.cats = data.cats
        self.cat_by_name = {}
        self.category = data.category
        self.space_params = list(data.space_params)
        self.target_params = list(data.target_params)
        self.param_cache = {}
        if data.category is not None:
            self.param_cache[data.category.value] = list(data.target_params)
        self.hold = None
        self.rows = []
        self.busy = False
        self.loading = 0
        self.closed = False
        self.proved = False
        self.theme_mode = settings['theme']
        self.theme_name = 'dark'
        self.keep = []
        self.timer = None

        self.window = UI.load_window('SpaceDataPush.xaml')
        self.find = self.window.FindName
        self.grab_controls()
        self.cat_filter = UI.FilterCombo(self.cat_combo, self.on_cat_picked)
        self.chrome = UI.Chrome(self.window, self.find)
        self.chrome.wire()
        self.keep.append(UI.frameless(self.window))
        UI.set_icon(self.icon_image, 'icon.png')
        self.version_text.Text = u'v%s' % __version__
        self.tool_text.Text = TOOL_NAME
        self.apply_theme()
        self.restore_size()
        self.load_options()
        self.fill_categories()
        self.load_rows()
        self.refresh_preview()
        self.show_hold()
        self.wire()
        self.egg_state = UI.attach_egg(self.window, self.logo_host, self.get_theme_name, self.keep)
        L.log_debug(u'window built, egg=%s, theme=%s' % (self.egg_state, self.theme_name))

    # ---------------------------------------------------------------- plumbing

    def grab_controls(self):
        f = self.find
        self.icon_image = f('IconImage')
        self.logo_host = f('LogoHost')
        self.tool_text = f('ToolText')
        self.version_text = f('VersionText')
        self.theme_chip = f('ThemeChip')
        self.theme_dot = f('ThemeDot')
        self.theme_text = f('ThemeText')
        self.cat_combo = f('CatCombo')
        self.rows_panel = f('RowsPanel')
        self.add_btn = f('AddRowBtn')
        self.count_text = f('RowCountText')
        self.space_info = f('SpaceInfo')
        self.overwrite_check = f('OverwriteCheck')
        self.skip_check = f('SkipBlankCheck')
        self.keep_check = f('KeepPickingCheck')
        self.hide_check = f('HideCheck')
        self.log_panel = f('LogPanel')
        self.clear_btn = f('ClearLogBtn')
        self.status_text = f('StatusText')
        self.status_dot = f('StatusDot')
        self.pick_space_btn = f('PickSpaceBtn')
        self.pick_push_btn = f('PickPushBtn')

    def wire(self):
        self.theme_chip.Click += self.on_theme_click
        self.add_btn.Click += self.on_add_row
        self.clear_btn.Click += self.on_clear_log
        self.pick_space_btn.Click += self.on_pick_space
        self.pick_push_btn.Click += self.on_pick_push
        for box in (self.overwrite_check, self.skip_check, self.keep_check, self.hide_check):
            box.Click += self.on_option
        self.window.Closing += self.on_closing
        self.window.Activated += self.on_activated
        self.timer = DispatcherTimer()
        self.timer.Interval = TimeSpan.FromSeconds(1)
        self.timer.Tick += self.on_tick

    def get_theme_name(self):
        return self.theme_name

    def touch(self):
        """The first handler that runs proves the engine is alive: the note written
        just before Show() is removed, and settings are kept up to date."""
        if not self.proved:
            self.proved = True
            clear_alive_note()
        self.save()

    def set_status(self, text, kind=u'info'):
        if self.status_text.Text == text:
            return
        self.status_text.Text = text
        self.status_text.SetResourceReference(TextBlock.ForegroundProperty,
                                              LEVEL_BRUSH.get(kind, 'TextBrush'))
        self.status_dot.SetResourceReference(Ellipse.FillProperty,
                                             LEVEL_BRUSH.get(kind, 'MutedBrush'))

    def set_busy(self, flag, text=None, kind=u'info'):
        self.busy = flag
        self.pick_space_btn.IsEnabled = not flag
        self.pick_push_btn.IsEnabled = not flag
        if text is not None:
            self.set_status(text, kind)

    def log(self, text, kind=u'info'):
        """One line in the activity list, with a colour bar down its left so the
        outcome reads at a glance rather than from the wording."""
        brush = LEVEL_BRUSH.get(kind, 'TextBrush')
        line = Grid()
        line.Margin = Thickness(0, 5 if kind == u'head' else 0, 0, 2)
        self.add_column(line, 3, GridUnitType.Pixel)
        self.add_column(line, 1, GridUnitType.Star)

        bar = Border()
        bar.CornerRadius = CornerRadius(2)
        bar.Margin = Thickness(0, 1, 9, 1)
        bar.SetResourceReference(Border.BackgroundProperty,
                                 brush if kind != u'info' else 'EdgeBrush')
        Grid.SetColumn(bar, 0)

        tb = TextBlock()
        tb.Text = text
        tb.TextWrapping = TextWrapping.Wrap
        tb.SetResourceReference(TextBlock.ForegroundProperty, brush)
        if kind == u'head':
            tb.FontWeight = FontWeights.SemiBold
        Grid.SetColumn(tb, 1)

        line.Children.Add(bar)
        line.Children.Add(tb)
        self.log_panel.Children.Add(line)
        while self.log_panel.Children.Count > LOG_LIMIT:
            self.log_panel.Children.RemoveAt(0)
        try:
            self.log_panel.Parent.ScrollToEnd()
        except Exception:
            pass

    # ------------------------------------------------------------------ theme

    def apply_theme(self):
        revit = T.revit_theme_name()
        self.theme_name = L.resolve_theme(self.theme_mode, revit)
        T.apply(self.window, self.theme_name)
        # Window.Background is a DynamicResource, but a brush written onto
        # window.Resources does not always re-resolve on the window itself, so it is
        # pointed at the key again after every swap.
        try:
            self.window.SetResourceReference(Window.BackgroundProperty, 'WindowBrush')
        except Exception:
            pass
        self.theme_text.Text = L.THEME_LABELS.get(self.theme_mode, u'Auto')
        self.theme_dot.SetResourceReference(Ellipse.FillProperty,
                                            DOT_BRUSH.get(self.theme_mode, 'BlueBrush'))

    def on_theme_click(self, sender, args):
        self.touch()
        self.theme_mode = L.next_theme_mode(self.theme_mode)
        self.apply_theme()
        self.save()

    def on_activated(self, sender, args):
        """Auto follows Revit's canvas theme, so it is re-read whenever the window
        comes to the front: switching Revit between light and dark just works."""
        if self.theme_mode != 'follow':
            return
        try:
            now = L.resolve_theme('follow', T.revit_theme_name())
            if now != self.theme_name:
                self.apply_theme()
        except Exception:
            pass

    # --------------------------------------------------------------- settings

    def restore_size(self):
        """Last size wins, clamped to the window's own minimums so a saved size from
        a smaller screen can never open it unusably small."""
        try:
            w = float(self.settings.get('win_w') or 0)
            h = float(self.settings.get('win_h') or 0)
            if w >= self.window.MinWidth:
                self.window.Width = w
            if h >= self.window.MinHeight:
                self.window.Height = h
        except Exception:
            pass

    def load_options(self):
        s = self.settings
        self.overwrite_check.IsChecked = (s['overwrite'] == '1')
        self.skip_check.IsChecked = (s['skip_blank'] == '1')
        self.keep_check.IsChecked = (s['keep_picking'] == '1')
        self.hide_check.IsChecked = (s['hide_window'] == '1')

    def collect_settings(self):
        s = dict(self.settings)
        s['theme'] = self.theme_mode
        s['category'] = u'%d' % self.category.value if self.category is not None else u''
        pairs = [(r.src, r.dst) for r in self.rows if r.src]
        s['rows'] = L.encode_rows(pairs)
        s['rows_saved'] = '1'
        s['overwrite'] = '1' if UI.checked(self.overwrite_check) else '0'
        s['skip_blank'] = '1' if UI.checked(self.skip_check) else '0'
        s['keep_picking'] = '1' if UI.checked(self.keep_check) else '0'
        s['hide_window'] = '1' if UI.checked(self.hide_check) else '0'
        try:
            if not self.chrome.full:
                s['win_w'] = u'%d' % int(self.window.Width)
                s['win_h'] = u'%d' % int(self.window.Height)
        except Exception:
            pass
        return s

    def save(self):
        try:
            self.settings = L.clean_settings(self.collect_settings())
            L.save_settings(self.settings)
        except Exception as ex:
            L.log_debug(u'save failed: %s' % ex)

    def on_option(self, sender, args):
        self.touch()

    # ------------------------------------------------------------- categories

    def fill_categories(self):
        self.cat_by_name = dict((c.name, c) for c in self.cats)
        current = self.category.name if self.category is not None else u''
        self.cat_filter.set_items([c.name for c in self.cats], current)

    def on_cat_picked(self, name):
        rec = self.cat_by_name.get(name)
        if rec is None:
            return
        if self.category is not None and rec.value == self.category.value:
            return
        self.touch()
        self.category = rec
        self.load_target_params()

    def load_target_params(self):
        rec = self.category
        if rec is None:
            return
        cached = self.param_cache.get(rec.value)
        if cached is not None:
            self.got_params(rec, cached)
            return
        self.set_status(u'Reading the parameters of %s ...' % rec.name, u'info')
        window = self.window

        def job(uiapp):
            names = None
            try:
                names = M.read_category_params(uiapp.ActiveUIDocument.Document, rec)
            except Exception as ex:
                L.log_debug(u'reading category parameters failed: %s' % ex)
            UI.on_ui(window, lambda: self.got_params(rec, names))

        if not self.runner.submit(job):
            self.set_status(u'Revit did not accept the request - choose the category again.', u'fail')

    def got_params(self, rec, names):
        if self.closed:
            return
        if names is None:
            self.set_status(u'Could not read the parameters of %s.' % rec.name, u'fail')
            return
        self.param_cache[rec.value] = list(names)
        if self.category is None or rec.value != self.category.value:
            return
        self.target_params = list(names)
        cleared = 0
        for row in self.rows:
            if row.dst and row.dst not in self.target_params:
                row.dst = u''
                cleared += 1
        self.refill_all()
        text = u'%s: %d writable parameters.' % (rec.name, len(names))
        if cleared:
            text += u'  %d row(s) cleared because that category does not carry the parameter.' % cleared
        self.set_status(text, u'info')
        self.save()

    # ------------------------------------------------------------------- rows

    def load_rows(self):
        pairs = []
        if self.settings.get('rows_saved') == '1':
            pairs = L.decode_rows(self.settings.get('rows'))
        for src, dst in pairs:
            if dst and dst not in self.target_params:
                dst = u''
            self.add_row(src, dst, scroll=False)
        if not self.rows:
            self.add_row(u'', u'', scroll=False)

    def on_add_row(self, sender, args):
        self.touch()
        self.add_row(u'', u'')

    def add_row(self, src, dst, scroll=True):
        row = Row(src, dst)
        self.build_row(row)
        self.rows.append(row)
        self.rows_panel.Children.Add(row.grid)
        self.refill_row(row)
        self.paint_preview(row)
        self.update_count()
        if scroll:
            try:
                row.grid.BringIntoView()
            except Exception:
                pass

    def remove_row(self, row):
        self.touch()
        if row in self.rows:
            self.rows.remove(row)
        self.rows_panel.Children.Remove(row.grid)
        if not self.rows:
            self.add_row(u'', u'', scroll=False)
        self.update_count()

    def update_count(self):
        n = len([r for r in self.rows if r.src and r.dst])
        self.count_text.Text = u'%d of %d row(s) ready to push' % (n, len(self.rows))

    @staticmethod
    def add_column(grid, width, unit, minimum=0):
        cd = ColumnDefinition()
        cd.Width = GridLength(width, unit)
        if minimum:
            cd.MinWidth = minimum
        grid.ColumnDefinitions.Add(cd)

    def build_row(self, row):
        """Columns match HeadGrid in the layout: space parameter, its value, arrow,
        element parameter, remove."""
        g = Grid()
        g.Margin = Thickness(0, 0, 0, 6)
        self.add_column(g, 2.3, GridUnitType.Star, 150)
        self.add_column(g, 1.5, GridUnitType.Star, 110)
        self.add_column(g, 46, GridUnitType.Pixel)
        self.add_column(g, 2.3, GridUnitType.Star, 150)
        self.add_column(g, 34, GridUnitType.Pixel)

        row.src_box = ComboBox()
        row.src_box.Margin = Thickness(0, 0, 10, 0)
        row.src_box.ToolTip = u'The space parameter to read. Type in the box to narrow the list.'
        Grid.SetColumn(row.src_box, 0)

        row.preview = TextBlock()
        row.preview.VerticalAlignment = VerticalAlignment.Center
        row.preview.Margin = Thickness(0, 0, 10, 0)
        row.preview.TextTrimming = TextTrimming.CharacterEllipsis
        Grid.SetColumn(row.preview, 1)

        arrow = Path()
        arrow.Data = Geometry.Parse('M0,5 L22,5 M17,0 L22,5 L17,10')
        arrow.StrokeThickness = 1.6
        arrow.HorizontalAlignment = HorizontalAlignment.Center
        arrow.VerticalAlignment = VerticalAlignment.Center
        arrow.SetResourceReference(Path.StrokeProperty, 'MutedBrush')
        Grid.SetColumn(arrow, 2)

        row.dst_box = ComboBox()
        row.dst_box.ToolTip = u'The parameter on the element to write. Type in the box to narrow the list.'
        Grid.SetColumn(row.dst_box, 3)

        row.remove_btn = Button()
        row.remove_btn.ToolTip = u'Remove this row'
        row.remove_btn.HorizontalAlignment = HorizontalAlignment.Right
        row.remove_btn.SetResourceReference(FrameworkElement.StyleProperty, 'BtnClose')
        cross = Path()
        cross.Data = Geometry.Parse('M0,0 L9,9 M9,0 L0,9')
        cross.StrokeThickness = 1.5
        cross.SetBinding(Path.StrokeProperty, self.foreground_binding())
        row.remove_btn.Content = cross
        Grid.SetColumn(row.remove_btn, 4)

        for child in (row.src_box, row.preview, arrow, row.dst_box, row.remove_btn):
            g.Children.Add(child)
        row.grid = g

        def on_src(value):
            self.touch()
            row.src = value
            self.paint_preview(row)
            self.after_row_change()

        def on_dst(value):
            self.touch()
            row.dst = value
            self.after_row_change()

        def on_remove(sender, args):
            self.remove_row(row)

        row.src_filter = UI.FilterCombo(row.src_box, on_src)
        row.dst_filter = UI.FilterCombo(row.dst_box, on_dst, blank_label=L.NONE_LABEL)
        row.remove_btn.Click += on_remove
        row.keep.extend([on_src, on_dst, on_remove])

    @staticmethod
    def foreground_binding():
        b = Binding('Foreground')
        b.RelativeSource = RelativeSource(RelativeSourceMode.FindAncestor, Button, 1)
        return b

    def after_row_change(self):
        self.update_count()
        dupes = L.find_duplicate_targets([(r.src, r.dst) for r in self.rows])
        if dupes:
            self.set_status(u'More than one row writes to: %s. Only one value can win.'
                            % u', '.join(dupes), u'warn')

    # ------------------------------------------------- filling the row combos

    def refill_row(self, row):
        row.src_filter.set_items(self.space_params, row.src)
        row.dst_filter.set_items(self.target_params, row.dst)

    def refill_all(self):
        for row in self.rows:
            self.refill_row(row)
        self.update_count()

    # ---------------------------------------------------- held space and values

    def paint_preview(self, row):
        snap = None
        if self.hold is not None and row.src:
            snap = self.hold.values.get(row.src)
        text, kind = L.preview_text(snap, self.hold is not None and bool(row.src))
        row.preview.Text = text
        row.preview.SetResourceReference(TextBlock.ForegroundProperty,
                                         PREVIEW_BRUSH.get(kind, 'TextBrush'))

    def refresh_preview(self):
        for row in self.rows:
            self.paint_preview(row)

    def show_hold(self):
        if self.hold is None:
            self.space_info.Text = u'No space held yet - press Pick Space.'
            self.space_info.SetResourceReference(TextBlock.ForegroundProperty, 'MutedBrush')
        else:
            self.space_info.Text = u'Holding space:  %s' % self.hold.caption
            self.space_info.SetResourceReference(TextBlock.ForegroundProperty, 'TextBrush')

    def on_clear_log(self, sender, args):
        self.touch()
        self.log_panel.Children.Clear()

    # ----------------------------------------------------------- pick a space

    def on_pick_space(self, sender, args):
        self.touch()
        if self.busy:
            return
        hide = UI.checked(self.hide_check)
        self.set_busy(True, u'Pick a space in Revit (Esc cancels) ...')
        if not self.runner.submit(self.make_space_job(hide)):
            self.set_busy(False, u'Revit did not accept the request - try again.', u'fail')

    def make_space_job(self, hide):
        window = self.window

        def job(uiapp):
            out = {'hold': None, 'error': u'', 'cancel': False}
            hidden = False
            try:
                uidoc = uiapp.ActiveUIDocument
                if uidoc is None:
                    raise L.UserMessage(u'Open a project first.')
                doc = uidoc.Document
                sp = M.selected_space(uidoc)
                if sp is None:
                    if hide:
                        window.Hide()
                        hidden = True
                    sp = M.pick_one(uidoc, M.CategoryFilter(M.space_category_value()),
                                    u'Pick a space  (Esc to cancel)')
                if sp is None:
                    out['cancel'] = True
                else:
                    out['hold'] = M.hold_space(doc, sp)
            except L.UserMessage as ex:
                out['error'] = L.to_text(ex)
            except Exception as ex:
                out['error'] = u'Could not pick a space: %s' % L.to_text(ex)
                L.log_debug(traceback.format_exc())
            finally:
                if hidden:
                    show_again(window)
            UI.on_ui(window, lambda: self.space_done(out))

        return job

    def space_done(self, out):
        if self.closed:
            return
        if out['error']:
            self.set_busy(False, out['error'], u'fail')
            self.log(out['error'], u'fail')
            return
        if out['cancel'] or out['hold'] is None:
            self.set_busy(False, u'Space pick cancelled.', u'info')
            return
        self.hold = out['hold']
        self.save()
        self.space_params = L.merge_names(self.space_params, list(self.hold.values.keys()))
        self.refill_all()
        self.refresh_preview()
        self.show_hold()
        text = u'Holding %s. Go to the view with your elements, then press Pick Elements and Push.' \
               % self.hold.caption
        self.set_busy(False, text, u'ok')
        self.log(u'Space picked: %s' % self.hold.caption, u'head')

    # ------------------------------------------------------ pick and push

    def mappings(self):
        return [(r.src, r.dst) for r in self.rows if r.src and r.dst]

    def on_pick_push(self, sender, args):
        self.touch()
        if self.busy:
            return
        if self.hold is None:
            self.set_status(u'Pick a space first, then come back to this button.', u'warn')
            return
        if self.category is None:
            self.set_status(u'Choose an element category first.', u'warn')
            return
        maps = self.mappings()
        if not maps:
            self.set_status(u'Set at least one row: a space parameter and the element parameter it goes to.',
                            u'warn')
            return
        dupes = L.find_duplicate_targets(maps)
        if dupes:
            self.set_status(u'More than one row writes to %s - change one of them.'
                            % u', '.join(dupes), u'warn')
            return
        opts = {
            'hide': UI.checked(self.hide_check),
            'overwrite': UI.checked(self.overwrite_check),
            'skip_blank': UI.checked(self.skip_check),
            'keep': UI.checked(self.keep_check),
        }
        self.set_busy(True, u'Click %s elements in Revit (Esc finishes) ...' % self.category.name)
        job = self.make_push_job(self.hold, self.category, maps, opts)
        if not self.runner.submit(job):
            self.set_busy(False, u'Revit did not accept the request - try again.', u'fail')

    def make_push_job(self, hold, cat, maps, opts):
        window = self.window
        runner = self.runner

        def job(uiapp):
            tally = {'picked': 0, 'error': u''}
            hidden = False
            try:
                uidoc = uiapp.ActiveUIDocument
                if uidoc is None:
                    raise L.UserMessage(u'Open a project first.')
                if L.to_text(uidoc.Document.Title) != hold.doc_title:
                    raise L.UserMessage(u'The space was picked in "%s" - pick it again here.'
                                        % hold.doc_title)
                if opts['hide']:
                    window.Hide()
                    hidden = True
                while True:
                    uidoc = uiapp.ActiveUIDocument
                    if uidoc is None or L.to_text(uidoc.Document.Title) != hold.doc_title:
                        raise L.UserMessage(u'The active project changed - stopped.')
                    doc = uidoc.Document
                    el = M.pick_one(uidoc, M.CategoryFilter(cat.value),
                                    u'Click a %s to push the values onto  (Esc to finish)' % cat.name)
                    if el is None:
                        break
                    sp = doc.GetElement(hold.eid)
                    if sp is None:
                        raise L.UserMessage(u'The held space no longer exists.')
                    fresh = M.hold_space(doc, sp)
                    label = M.element_label(el)
                    runner.suppress = True
                    try:
                        results = M.push_to_element(doc, fresh, el, maps,
                                                    opts['overwrite'], opts['skip_blank'])
                    finally:
                        runner.suppress = False
                    tally['picked'] += 1
                    UI.on_ui(window, lambda l=label, r=results: self.log_push(l, r))
                    if not opts['keep']:
                        break
            except L.UserMessage as ex:
                tally['error'] = L.to_text(ex)
            except Exception as ex:
                tally['error'] = u'Stopped: %s' % L.to_text(ex)
                L.log_debug(traceback.format_exc())
            finally:
                runner.suppress = False
                if hidden:
                    show_again(window)
            UI.on_ui(window, lambda: self.push_done(tally))

        return job

    def log_push(self, label, results):
        if self.closed:
            return
        counts = L.result_counts(results)
        level = L.result_level(counts)
        self.log(u'%s  \u00b7  %s  \u00b7  id %s' % (label[0], label[1], label[2]), u'head')
        self.log(L.result_summary(counts), level)
        for r in results:
            self.log(u'   ' + L.result_line(r), r.status)
        self.set_status(u'%s: %s' % (label[1], L.result_summary(counts)), level)

    def push_done(self, tally):
        if self.closed:
            return
        if tally['error']:
            self.set_busy(False, tally['error'], u'fail')
            self.log(tally['error'], u'fail')
            return
        n = tally['picked']
        if n:
            text = u'Finished - %d element(s) pushed. Pick Space for the next one.' % n
        else:
            text = u'No elements picked. Pick Space for another, or push onto more elements.'
        self.set_busy(False, text, u'info')
        self.save()
        self.come_back()

    def come_back(self):
        """Picking is over, so the window is what should be in front, with Pick Space
        under the cursor's next click and under Enter."""
        try:
            self.window.Show()
            if self.window.WindowState == WindowState.Minimized:
                self.window.WindowState = WindowState.Normal
            self.window.Activate()
            self.pick_space_btn.IsDefault = True
            self.pick_space_btn.Focus()
        except Exception:
            pass

    # -------------------------------------------------------- watchdog / close

    def on_tick(self, sender, args):
        """Frees the buttons if the ExternalEvent never started the job."""
        try:
            queued = self.runner.queued_at
            if self.busy and queued is not None and self.runner.job_started is None \
                    and (time.time() - queued) > WATCHDOG_SECONDS:
                self.runner.queued_at = None
                self.set_busy(False, u'Revit did not start the request - try the button again.', u'fail')
                L.log_debug(u'watchdog freed the window after %ds' % WATCHDOG_SECONDS)
        except Exception:
            pass

    def on_closing(self, sender, args):
        self.closed = True
        try:
            self.save()
            if self.timer is not None:
                self.timer.Stop()
        except Exception:
            pass
        clear_alive_note()
        unpark()

    def show(self):
        """Everything is built before this, so the window is complete the moment it
        appears: no rows landing one at a time and no box filling itself on screen."""
        self.set_status(u'Ready. Set the rows, then Pick Space.', u'info')
        write_alive_note()
        self.window.Show()
        try:
            self.window.Activate()
            # Focus lands on a button, not in a dropdown's text box: focus in an
            # editable ComboBox puts a caret in it and makes it look as though the
            # tool is typing into itself as it opens.
            self.pick_space_btn.IsDefault = True
            self.pick_space_btn.Focus()
        except Exception:
            pass
        self.timer.Start()


# ------------------------------------------------------------ module functions

def show_again(window):
    try:
        window.Show()
        window.Activate()
    except Exception:
        pass


def alive_path():
    return os.path.join(L.appdata_dir(), L.ALIVE_FILE)


def write_alive_note():
    try:
        with open(alive_path(), 'w') as fh:
            fh.write(L.alive_note(__version__, time.time()))
    except Exception:
        pass


def clear_alive_note():
    try:
        path = alive_path()
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def read_alive_note():
    try:
        path = alive_path()
        if os.path.exists(path):
            with open(path, 'r') as fh:
                return fh.read()
    except Exception:
        pass
    return u''


def parked_window():
    try:
        return AppDomain.CurrentDomain.GetData(PARK_KEY + u'.window')
    except Exception:
        return None


def park(window, runner):
    try:
        AppDomain.CurrentDomain.SetData(PARK_KEY + u'.window', window)
        AppDomain.CurrentDomain.SetData(PARK_KEY + u'.runner', runner)
    except Exception:
        pass


def unpark():
    try:
        AppDomain.CurrentDomain.SetData(PARK_KEY + u'.window', None)
        AppDomain.CurrentDomain.SetData(PARK_KEY + u'.runner', None)
    except Exception:
        pass
    del _LIVE[:]


def launch(uiapp):
    """Open the window, or bring the open one to the front."""
    settings = L.load_settings()
    L.set_debug(settings.get('debug') == '1')
    uidoc = uiapp.ActiveUIDocument
    if uidoc is None:
        raise L.UserMessage(u'Open a project first.')

    old = parked_window()
    if old is not None:
        stale = L.note_is_stale(read_alive_note(), __version__)
        try:
            if not stale:
                if old.WindowState == WindowState.Minimized:
                    old.WindowState = WindowState.Normal
                old.Show()
                old.Activate()
                return
            L.log_debug(u'previous window never responded - replacing it')
            old.Close()
        except Exception as ex:
            L.log_debug(u'could not reuse the open window: %s' % ex)
        unpark()

    data = OpenData(uidoc.Document, settings)
    if data.category is None:
        raise L.UserMessage(u'This project has no categories that can carry parameters.')
    runner = Runner()
    ctrl = SdpWindow(uiapp, runner, data, settings)
    UI.own_window(ctrl.window, uiapp)
    del _LIVE[:]
    _LIVE.append(ctrl)
    park(ctrl.window, runner)
    ctrl.show()
