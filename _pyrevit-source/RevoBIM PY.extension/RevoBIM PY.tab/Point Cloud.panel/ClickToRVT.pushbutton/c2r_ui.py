# -*- coding: utf-8 -*-
"""Click to RVT Element - the window, its chrome, the settings dialog and
the ExternalEvent runner every Revit call goes out through."""
import c2r_clr  # noqa: F401

import os
import io
import time
import traceback

from System import Action, AppDomain
from System.IO import File, MemoryStream, FileStream, FileMode, FileAccess
from System.Windows import (Thickness, HorizontalAlignment, VerticalAlignment, FontWeights, GridLength,
                            GridUnitType, WindowStartupLocation, Point)
from System.Windows.Controls import (StackPanel, Orientation, Grid, ColumnDefinition, RowDefinition, TextBlock,
                                     CheckBox, ComboBox, Button, Border, TextBox, Canvas)
from System.Windows.Input import Key, Keyboard, ModifierKeys
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Markup import XamlReader
from System.Windows.Media import SolidColorBrush, ColorConverter, Geometry, PointCollection, Stretch
from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption
from System.Windows.Shapes import Path, Rectangle, Polygon, Shape
from System.Windows.Threading import DispatcherTimer, DispatcherPriority
from System import TimeSpan, EventHandler
from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent, TaskDialog

import c2r_version
import c2r_core as core
import c2r_jobs as jobs
import c2r_build as build
from c2r_drawer import WindowDrawer, work_area

HERE = os.path.dirname(os.path.abspath(__file__))
VERSION = c2r_version.__version__
APP_DIR = os.path.join(os.environ.get(u'APPDATA') or os.path.expanduser(u'~'), u'RevoBIM')
SETTINGS_PATH = os.path.join(APP_DIR, u'click_to_rvt.txt')
DEBUG_PATH = os.path.join(APP_DIR, u'click_to_rvt_debug.txt')
LIVE_KEY = u'RevoBIM.ClickToRVT.window.' + VERSION
WATCHDOG_S = 25.0
_LIVE = []


# =====================================================================
# files
# =====================================================================

def _ensure_dir():
    try:
        if not os.path.isdir(APP_DIR):
            os.makedirs(APP_DIR)
    except Exception:
        pass


def load_settings():
    try:
        with io.open(SETTINGS_PATH, u'r', encoding=u'utf-8') as f:
            return core.load_settings(f.read())
    except Exception:
        return core.load_settings(u'')


def save_settings(st):
    _ensure_dir()
    try:
        text = core.dump_settings(st)
        with io.open(SETTINGS_PATH, u'w', encoding=u'utf-8') as f:
            f.write(text)
        return True
    except Exception:
        return False


class Log(object):
    def __init__(self, on):
        self.on = on
        self.lines = []

    def write(self, msg):
        line = u'{0}  {1}'.format(time.strftime(u'%H:%M:%S'), msg)
        self.lines.append(line)
        self.lines = self.lines[-200:]
        if not self.on:
            return
        _ensure_dir()
        try:
            with io.open(DEBUG_PATH, u'a', encoding=u'utf-8') as f:
                f.write(line + u'\n')
        except Exception:
            pass


def load_xaml(name):
    fs = FileStream(os.path.join(HERE, name), FileMode.Open, FileAccess.Read)
    try:
        return XamlReader.Load(fs)
    finally:
        fs.Close()


def load_icon(image):
    try:
        path = os.path.join(HERE, u'icon.png')
        bmp = BitmapImage()
        bmp.BeginInit()
        bmp.StreamSource = MemoryStream(File.ReadAllBytes(path))
        bmp.CacheOption = BitmapCacheOption.OnLoad
        bmp.EndInit()
        image.Source = bmp
    except Exception:
        pass


# =====================================================================
# theme
# =====================================================================

def canvas_is_dark():
    """Revit's canvas theme. UIThemeManager exists from 2024; UITheme.Dark
    is 0, so the read is tested against None, never for truth."""
    try:
        import Autodesk.Revit.UI as RUI
        mgr = getattr(RUI, u'UIThemeManager', None)
        if mgr is None:
            return False
        t = mgr.CurrentCanvasTheme
        if t is None:
            return False
        return u'{0}'.format(t) == u'Dark'
    except Exception:
        return False


def brush(hexstr):
    b = SolidColorBrush(ColorConverter.ConvertFromString(hexstr))
    b.Freeze()
    return b


def apply_palette(win, name):
    pal = core.PALETTES[name]
    for k in core.PALETTE_KEYS:
        win.Resources[k] = brush(pal[k])


def merge_theme(win):
    fs = FileStream(os.path.join(HERE, u'Theme.xaml'), FileMode.Open, FileAccess.Read)
    try:
        win.Resources.MergedDictionaries.Add(XamlReader.Load(fs))
    finally:
        fs.Close()


def themed_text(text, key=u'Text', size=None, bold=False):
    tb = TextBlock()
    tb.Text = text
    tb.SetResourceReference(TextBlock.ForegroundProperty, key)
    tb.VerticalAlignment = VerticalAlignment.Center
    if size:
        tb.FontSize = size
    if bold:
        tb.FontWeight = FontWeights.SemiBold
    return tb


# =====================================================================
# chrome shared by every window
# =====================================================================

class Chrome(object):
    """Header drag, full screen by bounds, resize grips, keys and the
    shrink drawer for one borderless window."""

    def __init__(self, win, host, grips, on_error):
        self.win = win
        self.host = host
        self.full = None
        f = win.FindName
        self.header = f(u'Header')
        self.root = f(u'Root')
        self.shrink_btn = f(u'ShrinkBtn')
        self.drawer = WindowDrawer(win, self.header, self.root, self.shrink_btn, f(u'Grips'),
                                   on_error=on_error)
        self.shrink_btn.Click += self._on_shrink
        self.header.MouseLeftButtonDown += self._on_header_down
        win.PreviewKeyDown += self._on_key
        full = f(u'FullBtn')
        if full is not None:
            full.Click += self._on_full
        for name, sides in grips:
            th = f(name)
            if th is not None:
                th.DragDelta += self._grip(sides)

    def _on_shrink(self, sender, args):
        self.drawer.toggle()

    def busy(self):
        return bool(getattr(self.host, u'busy', False))

    def _on_header_down(self, sender, e):
        try:
            if e.ClickCount == 2:
                if self.drawer.parked:
                    self.drawer.expand()
                elif self.win.FindName(u'FullBtn') is not None:
                    self.toggle_full()
                return
            if self.drawer.parked and self.busy():
                return
            if self.full is not None and not self.drawer.parked:
                self.leave_full()
            self.win.DragMove()
        except Exception:
            pass

    def _on_key(self, sender, e):
        try:
            ctrl_shift = (Keyboard.Modifiers & (ModifierKeys.Control | ModifierKeys.Shift)) == \
                (ModifierKeys.Control | ModifierKeys.Shift)
            if ctrl_shift and e.Key == Key.H:
                self.drawer.toggle()
                e.Handled = True
                return
            if self.drawer.parked:
                if e.Key in (Key.Escape, Key.Return, Key.Enter, Key.F11):
                    self.drawer.expand()
                e.Handled = True
                return
            if e.Key == Key.F11 and self.win.FindName(u'FullBtn') is not None:
                self.toggle_full()
                e.Handled = True
            elif e.Key == Key.Escape and self.full is not None:
                self.leave_full()
                e.Handled = True
        except Exception:
            pass

    def _on_full(self, sender, args):
        self.toggle_full()

    def toggle_full(self):
        if self.drawer.parked or self.drawer.sliding:
            return
        if self.full is None:
            w = self.win
            self.full = (w.Left, w.Top, w.Width, w.Height)
            l, t, r, b = work_area(w)
            w.Left = l
            w.Top = t
            w.Width = r - l
            w.Height = b - t
        else:
            self.leave_full()

    def leave_full(self):
        if self.full is None:
            return
        w = self.win
        l, t, wd, h = self.full
        self.full = None
        w.Left = l
        w.Top = t
        w.Width = wd
        w.Height = h

    def _grip(self, sides):
        def handler(sender, e):
            try:
                w = self.win
                self.full = None
                if u'l' in sides:
                    nw = max(w.MinWidth, w.Width - e.HorizontalChange)
                    w.Left = w.Left + (w.Width - nw)
                    w.Width = nw
                if u'r' in sides:
                    w.Width = max(w.MinWidth, w.Width + e.HorizontalChange)
                if u't' in sides:
                    nh = max(w.MinHeight, w.Height - e.VerticalChange)
                    w.Top = w.Top + (w.Height - nh)
                    w.Height = nh
                if u'b' in sides:
                    w.Height = max(w.MinHeight, w.Height + e.VerticalChange)
            except Exception:
                pass
        return handler


MAIN_GRIPS = [(u'GripL', u'l'), (u'GripR', u'r'), (u'GripT', u't'), (u'GripB', u'b'),
              (u'GripTL', u'tl'), (u'GripTR', u'tr'), (u'GripBL', u'bl'), (u'GripBR', u'br')]
DIALOG_GRIPS = [(u'GripR', u'r'), (u'GripB', u'b'), (u'GripBR', u'br')]


def own_dialog(dialog, owner_win, owner_drawer):
    """A dialog never centres on a parked owner - it would land mostly off
    the screen round a 50 px bar."""
    dialog.Owner = owner_win
    if owner_drawer is not None and owner_drawer.parked:
        dialog.WindowStartupLocation = WindowStartupLocation.CenterScreen
    else:
        dialog.WindowStartupLocation = WindowStartupLocation.CenterOwner


# =====================================================================
# ExternalEvent runner
# =====================================================================

class Handler(IExternalEventHandler):
    def __init__(self, runner):
        self.runner = runner

    def Execute(self, uiapp):
        try:
            self.runner.execute(uiapp)
        except Exception:
            pass

    def GetName(self):
        return u'RevoBIM Click to RVT Element'


class Runner(object):
    """Queue behind a Pending raise, never clear it wholesale; a watchdog
    frees the window if Revit has not started a job in 25 s."""

    def __init__(self, log, on_stuck):
        self.log = log
        self.on_stuck = on_stuck
        self.queue = []
        self.running = False
        self.raised_at = None
        self.handler = Handler(self)
        self.event = ExternalEvent.Create(self.handler)

    def submit(self, name, fn, done):
        self.queue.append((name, fn, done))
        return self._raise(name)

    def _raise(self, name):
        try:
            r = u'{0}'.format(self.event.Raise())
        except Exception as ex:
            r = u'error {0}'.format(ex)
        if r in (u'Accepted', u'Pending'):
            if self.raised_at is None:
                self.raised_at = time.time()
            return True
        self.log(u'runner: Raise for {0} answered {1}; job dropped'.format(name, r))
        if self.queue:
            self.queue.pop()
        return False

    def execute(self, uiapp):
        self.raised_at = None
        if not self.queue:
            return
        name, fn, done = self.queue.pop(0)
        self.running = True
        res = None
        err = None
        try:
            res = fn(uiapp)
        except Exception:
            err = traceback.format_exc()
        self.running = False
        try:
            done(res, err)
        except Exception:
            self.log(u'runner: callback for {0} failed\n{1}'.format(name, traceback.format_exc()))
        if self.queue:
            self._raise(self.queue[0][0])

    def watchdog(self):
        if self.raised_at is not None and not self.running and time.time() - self.raised_at > WATCHDOG_S:
            self.log(u'runner: Revit did not start the job in {0:.0f} s - window freed'.format(WATCHDOG_S))
            self.raised_at = None
            self.queue = []
            self.on_stuck()


# =====================================================================
# main window
# =====================================================================

AUTO_TYPE = u'Auto - closest size'
AUTO_LEVEL = u'Auto - level below'


class MainWindow(object):

    def __init__(self, uiapp, st, cat):
        self.uiapp = uiapp
        self.st = st
        self.cat = cat
        self.busy = False
        self.stop = False
        self.last = None
        self.preview = None
        self.kind_checks = {}
        self.kind_combos = {}
        self.log = Log(st[u'debug'] == u'1')
        self.win = load_xaml(u'ClickToRvt.xaml')
        merge_theme(self.win)
        self.f = self.win.FindName
        self.chrome = Chrome(self.win, self, MAIN_GRIPS, self._drawer_error)
        self.drawer = self.chrome.drawer
        self.runner = Runner(self.log.write, self._stuck)
        self.apply_theme()
        load_icon(self.f(u'Logo'))
        self.f(u'VersionText').Text = u'v' + VERSION
        try:
            WindowInteropHelper(self.win).Owner = uiapp.MainWindowHandle
        except Exception:
            pass
        self._build_kinds()
        self._fill_options()
        self._wire()
        self.timer = DispatcherTimer()
        self.timer.Interval = TimeSpan.FromSeconds(1)
        self.timer.Tick += EventHandler(self._tick)
        self.timer.Start()
        self.log.write(u'--- Click to RVT Element {0} opened, {1} point clouds'.format(
            VERSION, len(cat.get(u'clouds') or [])))

    # ------------------------------------------------------------------ setup
    def _wire(self):
        f = self.f
        f(u'CloseBtn').Click += self._on_close
        f(u'GearBtn').Click += self._on_settings
        f(u'ThemeBtn').Click += self._on_theme
        f(u'ClickBtn').Click += self._on_click
        f(u'StopBtn').Click += self._on_stop
        f(u'SelectBtn').Click += self._on_select
        f(u'DeleteBtn').Click += self._on_delete
        f(u'DebugChk').Click += self._on_debug
        f(u'Preview').SizeChanged += self._on_preview_size
        self.win.Activated += self._on_activated
        self.win.Closed += self._on_closed

    def _build_kinds(self):
        rows = self.f(u'KindRows')
        enabled = set(core.param_names(self.st[u'kinds']))
        for group in (u'MEP', u'Architecture', u'Structure'):
            head = StackPanel()
            head.Orientation = Orientation.Horizontal
            head.Margin = Thickness(0, 6, 0, 2)
            tick = Border()
            tick.Width = 3
            tick.Height = 12
            tick.Margin = Thickness(0, 0, 6, 0)
            tick.SetResourceReference(Border.BackgroundProperty, core.GROUP_ACCENT[group])
            head.Children.Add(tick)
            head.Children.Add(themed_text(group, u'Muted', 11))
            rows.Children.Add(head)
            for key, label, grp, glyph in core.KINDS:
                if grp != group:
                    continue
                g = Grid()
                g.Margin = Thickness(0, 1, 0, 1)
                for w in (24.0, 24.0, 84.0):
                    cd = ColumnDefinition()
                    cd.Width = GridLength(w)
                    g.ColumnDefinitions.Add(cd)
                cd = ColumnDefinition()
                cd.Width = GridLength(1.0, GridUnitType.Star)
                g.ColumnDefinitions.Add(cd)
                chk = CheckBox()
                chk.IsChecked = key in enabled
                chk.VerticalAlignment = VerticalAlignment.Center
                chk.ToolTip = u'Recognise ' + label.lower()
                g.Children.Add(chk)
                p = Path()
                p.Data = Geometry.Parse(glyph)
                p.StrokeThickness = 1.4
                p.Width = 16
                p.Height = 16
                p.Stretch = getattr(Stretch, u'None')
                p.SetResourceReference(Shape.StrokeProperty, core.GROUP_ACCENT[grp])
                p.VerticalAlignment = VerticalAlignment.Center
                Grid.SetColumn(p, 1)
                g.Children.Add(p)
                tb = themed_text(label)
                Grid.SetColumn(tb, 2)
                g.Children.Add(tb)
                cb = ComboBox()
                cb.Items.Add(AUTO_TYPE)
                want = self.st.get(u'type_' + key) or u''
                sel = 0
                types = self.cat.get(key) or []
                for t in types:
                    cb.Items.Add(t[u'name'])
                    if t[u'name'] == want:
                        sel = cb.Items.Count - 1
                cb.SelectedIndex = sel
                if not types:
                    cb.IsEnabled = False
                    cb.ToolTip = u'No {0} types in this model'.format(label.lower())
                Grid.SetColumn(cb, 3)
                g.Children.Add(cb)
                rows.Children.Add(g)
                self.kind_checks[key] = chk
                self.kind_combos[key] = cb

    def _fill_combo(self, cb, names, want, first=None):
        cb.Items.Clear()
        if first:
            cb.Items.Add(first)
        sel = 0
        for n in names:
            cb.Items.Add(n)
            if n == want:
                sel = cb.Items.Count - 1
        if cb.Items.Count:
            cb.SelectedIndex = sel

    def _fill_options(self):
        f = self.f
        st = self.st
        self._fill_combo(f(u'PipeSysCombo'), [n for n, _i in self.cat.get(u'pipe_systems') or []], st[u'pipe_system'])
        self._fill_combo(f(u'DuctSysCombo'), [n for n, _i in self.cat.get(u'duct_systems') or []], st[u'duct_system'])
        self._fill_combo(f(u'LevelCombo'), [l[0] for l in self.cat.get(u'levels') or []], st[u'level'], AUTO_LEVEL)
        f(u'TraceRadio').IsChecked = st[u'run_mode'] != u'click'
        f(u'ClickEndRadio').IsChecked = st[u'run_mode'] == u'click'
        f(u'InsulationBox').Text = u'' if st[u'insulation_mm'] in (u'0', u'0.0') else st[u'insulation_mm']
        f(u'AutoPlaceChk').IsChecked = st[u'auto_place'] == u'1'
        f(u'ContinuousChk').IsChecked = st[u'continuous'] == u'1'
        f(u'DebugChk').IsChecked = st[u'debug'] == u'1'

    # ------------------------------------------------------------------ options
    def read_opts(self):
        f = self.f
        st = self.st
        enabled = [k for k in core.KIND_KEYS if self.kind_checks[k].IsChecked]
        types = {}
        for k in core.KIND_KEYS:
            cb = self.kind_combos[k]
            v = u'' if cb.SelectedIndex <= 0 else u'{0}'.format(cb.SelectedItem)
            types[k] = v
            st[u'type_' + k] = v
        st[u'kinds'] = u','.join(enabled)

        def combo(name, auto=False):
            cb = f(name)
            if cb.SelectedIndex < (1 if auto else 0):
                return u''
            return u'{0}'.format(cb.SelectedItem)
        st[u'pipe_system'] = combo(u'PipeSysCombo')
        st[u'duct_system'] = combo(u'DuctSysCombo')
        st[u'level'] = combo(u'LevelCombo', True)
        st[u'run_mode'] = u'click' if f(u'ClickEndRadio').IsChecked else u'trace'
        try:
            ins = float((f(u'InsulationBox').Text or u'0').strip())
            ins = max(0.0, min(200.0, ins))
        except Exception:
            ins = 0.0
        st[u'insulation_mm'] = u'{0:g}'.format(ins)
        st[u'auto_place'] = u'1' if f(u'AutoPlaceChk').IsChecked else u'0'
        st[u'continuous'] = u'1' if f(u'ContinuousChk').IsChecked else u'0'
        save_settings(st)
        return {u'enabled': enabled, u'types': types, u'pipe_system': st[u'pipe_system'],
                u'duct_system': st[u'duct_system'], u'level': st[u'level'], u'run_mode': st[u'run_mode'],
                u'insulation_mm': ins, u'auto_place': st[u'auto_place'] == u'1',
                u'continuous': st[u'continuous'] == u'1'}

    # ------------------------------------------------------------------ state
    def status(self, text, key=u'Muted'):
        try:
            tb = self.f(u'StatusText')
            tb.Text = text
            tb.SetResourceReference(TextBlock.ForegroundProperty, key)
            tb.ToolTip = text
        except Exception:
            pass

    def set_busy(self, on):
        """The body and the header controls go deaf for a run; the shrink
        button never does."""
        self.busy = on
        f = self.f
        for name in (u'Body', u'GearBtn', u'ThemeBtn', u'FullBtn', u'CloseBtn', u'ClickBtn', u'DebugChk'):
            try:
                f(name).IsEnabled = not on
            except Exception:
                pass
        f(u'StopBtn').IsEnabled = on

    def _stuck(self):
        self.set_busy(False)
        self.status(u'Revit did not answer - the window has been freed. Try again.', u'Orange')

    def _tick(self, sender, args):
        try:
            self.runner.watchdog()
        except Exception:
            pass

    def _drawer_error(self, ex):
        self.log.write(u'drawer: {0}'.format(ex))

    def _fail(self, where):
        tb = traceback.format_exc()
        self.log.write(u'{0} failed\n{1}'.format(where, tb))
        self.status(u'{0} failed - see the debug log'.format(where), u'Red')

    # ------------------------------------------------------------------ theme
    def apply_theme(self):
        name = core.resolve_theme(self.st[u'theme'], canvas_is_dark())
        apply_palette(self.win, name)
        try:
            self.f(u'ThemeLabel').Text = core.THEME_LABEL[self.st[u'theme']]
        except Exception:
            pass
        return name

    def _on_theme(self, sender, args):
        try:
            self.st[u'theme'] = core.next_theme(self.st[u'theme'])
            save_settings(self.st)
            self.apply_theme()
        except Exception:
            self._fail(u'Theme')

    def _on_activated(self, sender, args):
        if self.st[u'theme'] == u'follow':
            try:
                self.apply_theme()
            except Exception:
                pass

    # ------------------------------------------------------------------ actions
    def _on_click(self, sender, args):
        self.start_click()

    def start_click(self):
        if self.busy:
            self.log.write(u'click ignored: busy')
            return
        try:
            self.stop = False
            opts = self.read_opts()
            st = dict(self.st)
            log = self.log.write
            self.set_busy(True)
            self.status(u'Click the scanned object in Revit - Escape stops', u'Blue')
            ok = self.runner.submit(u'click', lambda app: jobs.click_job(app, opts, st, log),
                                    lambda res, err: self._click_done(res, err, opts))
            if not ok:
                self.set_busy(False)
                self.status(u'Revit would not take the request - try again', u'Orange')
        except Exception:
            self.set_busy(False)
            self._fail(u'Click in model')

    def _click_done(self, res, err, opts):
        self.set_busy(False)
        if err:
            self.log.write(u'click job failed\n' + err)
            self.status(u'Failed: ' + err.strip().splitlines()[-1], u'Red')
            return
        if res.get(u'cancelled'):
            self.status(u'Stopped', u'Muted')
            return
        again = False
        if u'rec' in res:
            self.last = res
            self.show_result()
        if res.get(u'error'):
            self.status(res[u'error'], u'Orange')
            again = u'click' in res and u'cands' not in res     # a fresh click can fix it
        else:
            self.status(self._summary(), u'Text')
            again = res.get(u'placed') is not None
        if again and opts[u'continuous'] and opts[u'auto_place'] and not self.stop:
            self.win.Dispatcher.BeginInvoke(DispatcherPriority.Background, Action(self.start_click))

    def _summary(self):
        last = self.last
        if not last or last.get(u'placed') is None:
            return u'Recognised - pick how to place it'
        c = last[u'cands'][last[u'placed']]
        rec = last[u'rec']
        extra = u''
        if rec[u'shape'] in (u'round', u'rect'):
            extra = u' - {0:.2f} m'.format(core.v_dist(rec[u'p0'], rec[u'p1']) / 1000.0)
        return u'{0} placed - {1} -> {2}{3} - {4:,} pts - fit {5:.1f} mm'.format(
            core.KIND_LABEL[c[u'kind']], c[u'measure'], c[u'text'], extra, rec.get(u'npts', 0), rec.get(u'rms', 0.0))

    def _on_stop(self, sender, args):
        self.stop = True
        self.status(u'Stopping after this one - press Escape in Revit to cancel the pick', u'Orange')

    def _alt_click(self, index):
        def handler(sender, args):
            if self.busy or not self.last:
                return
            try:
                opts = self.read_opts()
                st = dict(self.st)
                last = self.last
                log = self.log.write
                self.set_busy(True)
                self.status(u'Placing...', u'Blue')
                self.runner.submit(u'place', lambda app: jobs.place_job(app, last, index, opts, st, log),
                                   self._place_done)
            except Exception:
                self.set_busy(False)
                self._fail(u'Place')
        return handler

    def _place_done(self, res, err):
        self.set_busy(False)
        if err:
            self.log.write(u'place failed\n' + err)
            self.status(u'Not placed: ' + err.strip().splitlines()[-1], u'Red')
            return
        self.last[u'ids'] = res[u'ids']
        self.last[u'placed'] = res[u'placed']
        self.last.pop(u'error', None)
        self.show_result()
        self.status(self._summary(), u'Text')

    def _on_select(self, sender, args):
        if self.busy or not self.last or not self.last.get(u'ids'):
            return
        ids = self.last[u'ids']
        self.runner.submit(u'select', lambda app: jobs.select_job(app, ids),
                           lambda res, err: self.status(u'Selected in Revit' if not err else u'Select failed', u'Muted'))

    def _on_delete(self, sender, args):
        if self.busy or not self.last or not self.last.get(u'ids'):
            return
        ids = self.last[u'ids']

        def done(res, err):
            self.set_busy(False)
            if err:
                self.log.write(u'delete failed\n' + err)
                self.status(u'Delete failed', u'Red')
                return
            self.last[u'ids'] = []
            self.last[u'placed'] = None
            self.show_result()
            self.status(u'Deleted - pick another way to place it, or click again', u'Muted')
        self.set_busy(True)
        self.runner.submit(u'delete', lambda app: jobs.delete_job(app, ids), done)

    def _on_debug(self, sender, args):
        self.st[u'debug'] = u'1' if self.f(u'DebugChk').IsChecked else u'0'
        self.log.on = self.st[u'debug'] == u'1'
        save_settings(self.st)

    def _on_settings(self, sender, args):
        try:
            dlg = SettingsDialog(self)
            dlg.show()
        except Exception:
            self._fail(u'Settings')

    def _on_close(self, sender, args):
        try:
            self.read_opts()
        except Exception:
            pass
        self.win.Close()

    def _on_closed(self, sender, args):
        try:
            self.timer.Stop()
        except Exception:
            pass
        try:
            AppDomain.CurrentDomain.SetData(LIVE_KEY, None)
        except Exception:
            pass
        if self in _LIVE:
            _LIVE.remove(self)

    # ------------------------------------------------------------------ result
    def show_result(self):
        f = self.f
        last = self.last
        rec = last[u'rec']
        f(u'ResultTitle').Text = core.describe(rec)
        cands = last[u'cands']
        placed = last.get(u'placed')
        lead = cands[placed] if placed is not None else (cands[0] if cands else None)
        if lead is not None:
            f(u'ResultDetail').Text = u'{0} - {1} confidence - {2:,} points - fit {3:.1f} mm'.format(
                lead[u'measure'], lead[u'conf'], rec.get(u'npts', 0), rec.get(u'rms', 0.0))
        else:
            f(u'ResultDetail').Text = u''
        panel = f(u'AltPanel')
        panel.Children.Clear()
        for k in range(min(6, len(cands))):
            c = cands[k]
            b = Button()
            b.Style = self.win.FindResource(u'AltBtn')
            sp = StackPanel()
            sp.Children.Add(themed_text(c[u'text'], u'Text', bold=(k == placed)))
            sp.Children.Add(themed_text(u'{0} - {1}'.format(c[u'type'][u'name'], c[u'conf']), u'Muted', 10.5))
            b.Content = sp
            b.Tag = u'placed' if k == placed else u''
            b.ToolTip = (u'Placed' if k == placed else
                         (u'Swap to this' if placed is not None else u'Place this'))
            b.Click += self._alt_click(k)
            panel.Children.Add(b)
        has = bool(last.get(u'ids'))
        f(u'SelectBtn').IsEnabled = has
        f(u'DeleteBtn').IsEnabled = has
        self.preview = rec.get(u'preview')
        self.draw_preview()

    def _on_preview_size(self, sender, args):
        self.draw_preview()

    def draw_preview(self):
        cv = self.f(u'Preview')
        try:
            cv.Children.Clear()
            prev = self.preview
            if not prev:
                return
            W = cv.ActualWidth if cv.ActualWidth > 0 else 360.0
            H = cv.ActualHeight if cv.ActualHeight > 0 else 180.0
            pts = prev.get(u'pts') or []
            shapes = prev.get(u'shapes') or []
            xs = [p[0] for p in pts] + [q[0] for s in shapes for q in s]
            ys = [p[1] for p in pts] + [q[1] for s in shapes for q in s]
            if not xs:
                return
            x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
            sx = max(1.0, x1 - x0)
            sy = max(1.0, y1 - y0)
            m = 14.0
            scale = min((W - 2 * m) / sx, (H - 2 * m) / sy)
            ox = (W - sx * scale) / 2.0
            oy = (H - sy * scale) / 2.0

            def tx(x, y):
                return ox + (x - x0) * scale, H - (oy + (y - y0) * scale)
            step = max(1, len(pts) // 900)
            for k in range(0, len(pts), step):
                px, py = tx(pts[k][0], pts[k][1])
                r = Rectangle()
                r.Width = 2.2
                r.Height = 2.2
                r.SetResourceReference(Shape.FillProperty, u'Dot')
                r.Opacity = 0.75
                Canvas.SetLeft(r, px - 1.1)
                Canvas.SetTop(r, py - 1.1)
                cv.Children.Add(r)
            for s in shapes:
                poly = Polygon()
                pc = PointCollection()
                for q in s:
                    px, py = tx(q[0], q[1])
                    pc.Add(Point(px, py))
                poly.Points = pc
                poly.StrokeThickness = 2.0
                poly.SetResourceReference(Shape.StrokeProperty, u'Fit')
                cv.Children.Add(poly)
            self.f(u'CaptionText').Text = u'{0} - view {1:,.0f} x {2:,.0f} mm'.format(
                prev.get(u'caption', u''), sx, sy)
        except Exception:
            self.log.write(u'preview: ' + traceback.format_exc())

    # ------------------------------------------------------------------ show
    def show(self):
        self.win.Show()
        self.win.Activate()

    def bring_back(self):
        if self.drawer.parked:
            self.drawer.expand()
        self.win.Activate()


# =====================================================================
# settings dialog
# =====================================================================

SETTING_FIELDS = [
    (u'Cloud', None, None),
    (u'spacing_mm', u'Point spacing asked of Revit', u'mm'),
    (u'max_points', u'Most points per harvest', u''),
    (u'noise_mm', u'Scan noise', u'mm (Matterport about 6 to 10)'),
    (u'click_box_mm', u'Search round the click', u'mm either side'),
    (u'Runs', None, None),
    (u'trace_step_mm', u'Trace step', u'mm'),
    (u'trace_gap_mm', u'Gap a trace jumps', u'mm'),
    (u'trace_max_m', u'Longest run traced', u'm'),
    (u'section_half_mm', u'Section window', u'mm either side'),
    (u'snap_axis_deg', u'Square runs within', u'degrees of level / plumb'),
    (u'conduit_max_mm', u'Largest conduit', u'mm OD'),
    (u'Walls and slabs', None, None),
    (u'wall_search_m', u'Wall search length', u'm'),
    (u'wall_fallback_mm', u'Wall thickness if far face unscanned', u'mm'),
    (u'wall_height', u'Wall height', None),
    (u'floor_search_m', u'Slab search size', u'm'),
    (u'slab_cell_mm', u'Slab outline grid', u'mm'),
    (u'floor_outline', u'Slab outline', None),
    (u'Structure', None, None),
    (u'column_w_params', u'Column width parameters', u'first found wins'),
    (u'column_d_params', u'Column depth parameters', u''),
    (u'beam_w_params', u'Beam width parameters', u''),
    (u'beam_d_params', u'Beam depth parameters', u''),
]
CHOICE_LABELS = {
    u'wall_height': [(u'cloud', u'From the cloud'), (u'levels', u'Level to level above')],
    u'floor_outline': [(u'traced', u'Traced outline'), (u'rectangle', u'Rectangle')],
}


class SettingsDialog(object):

    def __init__(self, main):
        self.main = main
        self.win = load_xaml(u'Settings.xaml')
        merge_theme(self.win)
        self.f = self.win.FindName
        self.busy = False
        self.chrome = Chrome(self.win, self, DIALOG_GRIPS, main._drawer_error)
        self.drawer = self.chrome.drawer
        self.drawer.linked = main.drawer
        apply_palette(self.win, core.resolve_theme(main.st[u'theme'], canvas_is_dark()))
        load_icon(self.f(u'Logo'))
        self.f(u'VersionText').Text = u'v' + VERSION
        self.boxes = {}
        self._build(main.st)
        self.f(u'CloseBtn').Click += self._on_cancel
        self.f(u'CancelBtn').Click += self._on_cancel
        self.f(u'SaveBtn').Click += self._on_save
        self.f(u'ResetBtn').Click += self._on_reset
        self.win.Closed += self._on_closed

    def _build(self, st):
        g = self.f(u'Fields')
        g.Children.Clear()
        g.RowDefinitions.Clear()
        g.ColumnDefinitions.Clear()
        for w in (GridLength(230.0), GridLength(1.0, GridUnitType.Star), GridLength(150.0)):
            cd = ColumnDefinition()
            cd.Width = w
            g.ColumnDefinitions.Add(cd)
        row = 0
        for key, label, hint in SETTING_FIELDS:
            rd = RowDefinition()
            rd.Height = GridLength(32.0)
            g.RowDefinitions.Add(rd)
            if label is None:
                head = StackPanel()
                head.Orientation = Orientation.Horizontal
                head.VerticalAlignment = VerticalAlignment.Bottom
                tick = Border()
                tick.Width = 4
                tick.Height = 14
                tick.Margin = Thickness(0, 0, 6, 2)
                tick.SetResourceReference(Border.BackgroundProperty, u'Blue' if row == 0 else u'Orange')
                head.Children.Add(tick)
                head.Children.Add(themed_text(key, u'Text', bold=True))
                Grid.SetRow(head, row)
                Grid.SetColumnSpan(head, 3)
                g.Children.Add(head)
                row += 1
                continue
            lab = themed_text(label, u'Muted')
            Grid.SetRow(lab, row)
            g.Children.Add(lab)
            if key in CHOICE_LABELS:
                ctl = ComboBox()
                for val, text in CHOICE_LABELS[key]:
                    ctl.Items.Add(text)
                    if st[key] == val:
                        ctl.SelectedIndex = ctl.Items.Count - 1
            else:
                ctl = TextBox()
                ctl.Text = st[key]
                ctl.Tag = core.DEFAULTS[key]
            ctl.Margin = Thickness(0, 3, 8, 3)
            Grid.SetRow(ctl, row)
            Grid.SetColumn(ctl, 1)
            g.Children.Add(ctl)
            if hint:
                h = themed_text(hint, u'Muted', 11)
                Grid.SetRow(h, row)
                Grid.SetColumn(h, 2)
                g.Children.Add(h)
            self.boxes[key] = ctl
            row += 1

    def _values(self):
        d = dict(self.main.st)
        for key, ctl in self.boxes.items():
            if key in CHOICE_LABELS:
                i = ctl.SelectedIndex
                if i >= 0:
                    d[key] = CHOICE_LABELS[key][i][0]
            else:
                d[key] = (ctl.Text or u'').strip()
        return d

    def _on_save(self, sender, args):
        try:
            d = self._values()
            checked = core.load_settings(core.dump_settings(d))
            bad = [k for k in self.boxes if checked[k] != d[k]]
            if bad:
                labels = [l for k, l, _h in SETTING_FIELDS if k in bad]
                self.f(u'StatusText').Text = u'Out of range: ' + u', '.join(labels)
                self.f(u'StatusText').SetResourceReference(TextBlock.ForegroundProperty, u'Red')
                return
            self.main.st.update(checked)
            save_settings(self.main.st)
            self.win.Close()
        except Exception:
            self.main._fail(u'Save settings')

    def _on_reset(self, sender, args):
        d = dict(self.main.st)
        for key in self.boxes:
            d[key] = core.DEFAULTS[key]
        self.boxes = {}
        self._build(d)
        self.f(u'StatusText').Text = u'Defaults shown - Save to keep them'

    def _on_cancel(self, sender, args):
        self.win.Close()

    def _on_closed(self, sender, args):
        try:
            if self.main.drawer.parked:
                self.main.drawer.expand()
        except Exception:
            pass

    def show(self):
        own_dialog(self.win, self.main.win, self.main.drawer)
        self.win.ShowDialog()


# =====================================================================
# entry
# =====================================================================

def launch(uiapp):
    existing = None
    try:
        existing = AppDomain.CurrentDomain.GetData(LIVE_KEY)
    except Exception:
        existing = None
    if existing is not None:
        try:
            existing.bring_back()
            return existing
        except Exception:
            pass
    st = load_settings()
    doc = uiapp.ActiveUIDocument.Document
    cat = build.read_catalogue(doc, st)
    try:
        import c2r_cloud
        cat[u'clouds'] = c2r_cloud.clouds_in(doc)
    except Exception:
        cat[u'clouds'] = []
    ui = MainWindow(uiapp, st, cat)
    _LIVE.append(ui)
    try:
        AppDomain.CurrentDomain.SetData(LIVE_KEY, ui)
    except Exception:
        pass
    ui.show()
    if not cat[u'clouds']:
        ui.status(u'No point cloud in this model - link one (Insert > Point Cloud) first', u'Orange')
    return ui


def report_error(stage, text):
    _ensure_dir()
    try:
        with io.open(os.path.join(APP_DIR, u'click_to_rvt_error.txt'), u'w', encoding=u'utf-8') as f:
            f.write(u'{0}\n{1}'.format(stage, text))
    except Exception:
        pass
    TaskDialog.Show(u'Click to RVT Element', u'{0} failed:\n\n{1}'.format(stage, text[-1500:]))
