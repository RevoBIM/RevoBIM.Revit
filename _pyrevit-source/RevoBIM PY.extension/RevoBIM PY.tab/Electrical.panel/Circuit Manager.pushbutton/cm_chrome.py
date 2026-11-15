# -*- coding: utf-8 -*-
"""Circuit Manager - the window chrome every window in the tool shares.

Header (icon, RevoBIM, tool name, theme chip, version, shrink, full screen,
close), dragging, the eight resize grips, full screen by bounds, the theme
chip and the shrink-to-taskbar drawer. Every window class builds on
ThemedWindow so the gesture and the look are identical across them.
"""
import cm_clr  # noqa: F401
import os
import io
import datetime

from System import Action
from System.IO import File, MemoryStream
from System.Windows import Visibility, WindowStartupLocation, SizeToContent
from System.Windows.Input import Keyboard, ModifierKeys
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Markup import XamlReader
from System.Windows.Media import Geometry
from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption

import cm_logic
import cm_theme
import cm_drawer
from cm_version import __version__, TOOL_KEY

HERE = os.path.dirname(os.path.abspath(__file__))
APPDATA = os.path.join(os.environ.get('APPDATA', HERE), 'RevoBIM')
SETTINGS_PATH = os.path.join(APPDATA, TOOL_KEY + '.txt')
DEBUG_PATH = os.path.join(APPDATA, TOOL_KEY + '_debug.txt')

GLYPHS = {
    # Auto: half moon on a ring - follows Revit's canvas
    'follow': u'M 7,0 A 7,7 0 1 1 7,14 A 7,7 0 1 1 7,0 Z M 7,2 L 7,12 '
              u'A 5,5 0 0 1 7,2 Z',
    # Dark: crescent
    'dark': u'M 9,0 A 7,7 0 1 0 14,9 A 5.5,5.5 0 1 1 9,0 Z',
    # Light: sun
    'light': u'M 7,3.5 A 3.5,3.5 0 1 1 7,10.5 A 3.5,3.5 0 1 1 7,3.5 Z '
             u'M 6.3,0 L 7.7,0 L 7.7,2 L 6.3,2 Z M 6.3,12 L 7.7,12 L 7.7,14 '
             u'L 6.3,14 Z M 0,6.3 L 2,6.3 L 2,7.7 L 0,7.7 Z M 12,6.3 L 14,6.3 '
             u'L 14,7.7 L 12,7.7 Z',
}


# ======================================================================
# Settings and log - shared by every window in the tool
# ======================================================================
class Settings(object):

    def __init__(self):
        self.data = dict(cm_logic.DEFAULTS)
        self.load()

    def load(self):
        try:
            with io.open(SETTINGS_PATH, 'r', encoding='utf-8') as fh:
                text = fh.read()
            self.data = cm_logic.parse_settings(text)
        except Exception:
            self.data = cm_logic.parse_settings(u'')

    def save(self):
        try:
            if not os.path.isdir(APPDATA):
                os.makedirs(APPDATA)
            text = cm_logic.dump_settings(self.data)
            with io.open(SETTINGS_PATH, 'w', encoding='utf-8') as fh:
                fh.write(text)
        except Exception:
            pass

    def get(self, key):
        return self.data.get(key, cm_logic.DEFAULTS.get(key, ''))

    def set(self, key, value, save=True):
        self.data[key] = cm_logic.to_text(value)
        if save:
            self.save()


SETTINGS = Settings()


def log(text):
    if SETTINGS.get('debug') != '1':
        return
    try:
        if not os.path.isdir(APPDATA):
            os.makedirs(APPDATA)
        stamp = datetime.datetime.now().strftime('%H:%M:%S')
        with io.open(DEBUG_PATH, 'a', encoding='utf-8') as fh:
            fh.write(u'{0} v{1} {2}\n'.format(stamp, __version__,
                                             cm_logic.to_text(text)))
    except Exception:
        pass


# ======================================================================
# Theme state shared by every open window
# ======================================================================
OPEN_WINDOWS = []


def resolved_theme():
    return cm_logic.resolve_theme(SETTINGS.get('theme'),
                                  cm_theme.canvas_is_dark())


def repaint_all():
    resolved = resolved_theme()
    for w in list(OPEN_WINDOWS):
        try:
            w.paint(resolved)
        except Exception:
            pass


def load_icon(image):
    try:
        path = os.path.join(HERE, 'icon.png')
        bmp = BitmapImage()
        bmp.BeginInit()
        bmp.StreamSource = MemoryStream(File.ReadAllBytes(path))
        bmp.CacheOption = BitmapCacheOption.OnLoad
        bmp.EndInit()
        image.Source = bmp
    except Exception:
        pass


def mods():
    m = Keyboard.Modifiers
    return ((m & ModifierKeys.Control) == ModifierKeys.Control,
            (m & ModifierKeys.Shift) == ModifierKeys.Shift)


# ======================================================================
# ThemedWindow
# ======================================================================
class ThemedWindow(object):
    """A RevoBIM window: layout + Theme.xaml + palette + chrome + drawer."""

    LAYOUT = None

    def __init__(self, owner=None):
        self.win = XamlReader.Parse(File.ReadAllText(
            os.path.join(HERE, self.LAYOUT)))
        self.owner = owner
        self.win.Resources.MergedDictionaries.Add(cm_theme.load_theme_dict())
        self.resolved = resolved_theme()
        cm_theme.apply_palette(self.win, self.resolved)
        self.fullscreen = False
        self.saved_bounds = None
        self.drawer = cm_drawer.attach(self.win, self.find)
        if owner is not None:
            try:
                self.win.Owner = owner.win
                self.drawer.set_owner(owner.drawer)
                if owner.drawer.parked:
                    # centred on a parked bar most of it would be off screen
                    self.win.WindowStartupLocation = \
                        WindowStartupLocation.CenterScreen
                else:
                    self.win.WindowStartupLocation = \
                        WindowStartupLocation.CenterOwner
            except Exception:
                pass
        self._wire_chrome()
        OPEN_WINDOWS.append(self)
        self.win.Closed += self._on_closed_base

    # ------------------------------------------------------------------
    def find(self, name):
        try:
            return self.win.FindName(name)
        except Exception:
            return None

    def _wire_chrome(self):
        load_icon(self.find('icon_img'))
        self.find('version_text').Text = u'v' + __version__
        self.find('close_btn').Click += lambda s, a: self.win.Close()
        self.find('theme_btn').Click += self._on_theme
        header = self.find('header_bar')
        header.MouseLeftButtonDown += self._on_header_down
        self.win.PreviewKeyDown += self._on_key_base
        self.win.Activated += self._on_activated
        mx = self.find('max_btn')
        if mx is not None:
            mx.Click += lambda s, a: self.toggle_fullscreen()
        self._wire_grips()
        self._show_theme_chip()

    def _show_theme_chip(self):
        setting = SETTINGS.get('theme')
        try:
            self.find('theme_text').Text = cm_logic.theme_chip_text(setting)
            self.find('theme_glyph').Data = Geometry.Parse(
                GLYPHS.get(setting, GLYPHS['follow']))
        except Exception:
            pass

    def paint(self, resolved):
        self.resolved = resolved
        cm_theme.apply_palette(self.win, resolved)
        self._show_theme_chip()
        self.on_repainted()

    def on_repainted(self):
        """Windows with code-built, locally set brushes repaint them here."""
        pass

    def _on_theme(self, sender, args):
        SETTINGS.set('theme', cm_logic.next_theme(SETTINGS.get('theme')))
        log(u'theme -> {0}'.format(SETTINGS.get('theme')))
        repaint_all()

    def _on_activated(self, sender, args):
        if SETTINGS.get('theme') != 'follow':
            return
        try:
            now = resolved_theme()
            if now != self.resolved:
                repaint_all()
        except Exception:
            pass

    # ------------------------------------------------------------------
    def _on_header_down(self, sender, args):
        try:
            if args.ClickCount == 2:
                if not self.drawer.on_header_double_click():
                    if self.find('max_btn') is not None:
                        self.toggle_fullscreen()
                args.Handled = True
                return
            if self.drawer.can_drag():
                if self.fullscreen:
                    self.fullscreen = False      # dragging leaves full screen
                self.win.DragMove()
        except Exception:
            pass

    def _on_key_base(self, sender, args):
        try:
            key = str(args.Key)
            ctrl, shift = mods()
            if self.drawer.on_key(key, ctrl, shift):
                args.Handled = True
                return
            if key == 'F11' and self.find('max_btn') is not None:
                self.toggle_fullscreen()
                args.Handled = True
                return
            self.on_key(args, key, ctrl, shift)
        except Exception:
            log(u'key handler failed')

    def on_key(self, args, key, ctrl, shift):
        pass

    # ------------------------------------------------------------------
    def toggle_fullscreen(self):
        w = self.win
        if self.drawer.parked:
            self.drawer.expand()
            return
        if not self.fullscreen:
            self.saved_bounds = (w.Left, w.Top, w.Width, w.Height)
            env = cm_drawer.real_env()
            top, bottom = env.work_area(w)
            left, right = self._work_lr()
            w.Left, w.Top = left, top
            w.Width, w.Height = right - left, bottom - top
            self.fullscreen = True
        else:
            if self.saved_bounds:
                w.Left, w.Top, w.Width, w.Height = self.saved_bounds
            self.fullscreen = False

    def _work_lr(self):
        try:
            from System.Windows.Forms import Screen
            from System.Windows import PresentationSource
            hwnd = WindowInteropHelper(self.win).Handle
            area = Screen.FromHandle(hwnd).WorkingArea
            scale = 1.0
            src = PresentationSource.FromVisual(self.win)
            if src is not None and src.CompositionTarget is not None:
                scale = src.CompositionTarget.TransformToDevice.M11 or 1.0
            return area.Left / scale, area.Right / scale
        except Exception:
            from System.Windows import SystemParameters
            wa = SystemParameters.WorkArea
            return wa.Left, wa.Right

    # ------------------------------------------------------------------
    def _wire_grips(self):
        names = ('grip_n', 'grip_s', 'grip_w', 'grip_e', 'grip_nw',
                 'grip_ne', 'grip_sw', 'grip_se')
        for name in names:
            thumb = self.find(name)
            if thumb is None:
                continue
            thumb.DragDelta += self._make_grip(name)

    def _make_grip(self, name):
        def handler(sender, args):
            try:
                w = self.win
                if self.drawer.parked or self.drawer.sliding:
                    return
                self.fullscreen = False
                dx, dy = args.HorizontalChange, args.VerticalChange
                if 'e' in name[5:]:
                    w.Width = max(w.MinWidth, w.Width + dx)
                if 's' in name[5:]:
                    w.Height = max(w.MinHeight, w.Height + dy)
                if 'w' in name[5:]:
                    nw = max(w.MinWidth, w.Width - dx)
                    w.Left = w.Left + (w.Width - nw)
                    w.Width = nw
                if 'n' in name[5:]:
                    nh = max(w.MinHeight, w.Height - dy)
                    w.Top = w.Top + (w.Height - nh)
                    w.Height = nh
            except Exception:
                pass
        return handler

    # ------------------------------------------------------------------
    def _on_closed_base(self, sender, args):
        try:
            OPEN_WINDOWS.remove(self)
        except Exception:
            pass
        self.on_closed()

    def on_closed(self):
        pass


def owned_to_revit(window, uiapp):
    """Own a modeless window to Revit or it slips behind Revit."""
    try:
        WindowInteropHelper(window).Owner = uiapp.MainWindowHandle
    except Exception:
        pass


def later(window, fn):
    """Run fn after the current event has finished (dispatcher, background)."""
    from System.Windows.Threading import DispatcherPriority
    try:
        window.Dispatcher.BeginInvoke(DispatcherPriority.Background,
                                      Action(fn))
    except Exception:
        fn()
