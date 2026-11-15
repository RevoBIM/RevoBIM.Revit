# -*- coding: utf-8 -*-
"""ThemedWindow: the house chrome every Bulk Rename window is built on."""
import os
import sys

import brn_clr  # noqa: F401  must stay first
import brn_core as core
import brn_theme
from brn_drawer import Drawer
from brn_version import __version__

from System import Double, TimeSpan
from System.IO import File, MemoryStream, StringReader
from System.Windows import (
    PresentationSource, SizeToContent, SystemParameters, VerticalAlignment,
    Visibility,
)
from System.Windows.Forms import Screen
from System.Windows.Input import Key, Keyboard, ModifierKeys
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Markup import XamlReader
from System.Windows.Media import ColorConverter, SolidColorBrush
from System.Windows.Media.Imaging import BitmapCacheOption, BitmapImage
from System.Windows.Threading import DispatcherTimer
from System.Xml import XmlReader

HERE = os.path.dirname(os.path.abspath(__file__))
GRIPS = {'GripL': 'L', 'GripR': 'R', 'GripT': 'T', 'GripB': 'B',
         'GripTL': 'TL', 'GripTR': 'TR', 'GripBL': 'BL', 'GripBR': 'BR'}


def load_xaml(name):
    with open(os.path.join(HERE, name), 'r') as handle:
        text = handle.read()
    return XamlReader.Load(XmlReader.Create(StringReader(text)))


def canvas_theme(uiapp):
    """Revit's canvas. UITheme.Dark is 0, so reads are tested with is not None,
    and UIThemeManager only exists from 2024, so it is reached by getattr."""
    try:
        import Autodesk.Revit.UI as ui
        manager = getattr(ui, 'UIThemeManager', None)
        if manager is not None:
            value = manager.CurrentCanvasTheme
            if value is not None:
                return 'dark' if str(value) == 'Dark' else 'light'
    except Exception:
        pass
    try:
        colour = uiapp.Application.BackgroundColor
        return core.canvas_from_rgb(colour.Red, colour.Green, colour.Blue)
    except Exception:
        return 'dark'


class WpfDrawer(Drawer):
    def manual(self):
        return SizeToContent.Manual

    def top_align(self):
        return VerticalAlignment.Top

    def stretch(self):
        return VerticalAlignment.Stretch

    def nan(self):
        return Double.NaN


class ThemedWindow(object):
    LAYOUT = None

    def __init__(self, uiapp, settings, log, owner=None):
        self.uiapp = uiapp
        self.settings = settings
        self.log = log
        self.owner = owner
        self.window = load_xaml(self.LAYOUT)
        self.full_bounds = None
        self.theme_name = None
        self.theme_mode = None
        self.clicks = core.SlowClicks()
        self.window.Resources.MergedDictionaries.Add(load_xaml('Theme.xaml'))
        find = self.window.FindName
        self.root = find('Root')
        self.header = find('Header')
        self.logo = find('Logo')
        self.theme_chip = find('ThemeChip')
        self.theme_label = find('ThemeLabel')
        self.grips = find('Grips')
        self.shrink_btn = find('ShrinkBtn')
        self.full_btn = find('FullBtn')
        self.close_btn = find('CloseBtn')
        find('VersionText').Text = u'v' + __version__
        self.drawer = WpfDrawer(
            self.window, self.header, self.root, find('ShrinkGlyph'),
            find('ExpandGlyph'), self.grips, self.work_area, self._make_timer,
            (Visibility.Visible, Visibility.Collapsed))
        if owner is not None:
            self.drawer.owner = owner.drawer
        self._wire()
        self.apply_theme()
        self._load_logo()

    # ---------- plumbing ----------
    def safe(self, handler):
        def run(sender, args):
            try:
                handler(sender, args)
            except Exception as error:
                self.log(u'{0}: {1}'.format(getattr(handler, '__name__', 'handler'), error))
        return run

    def _make_timer(self, tick):
        timer = DispatcherTimer()
        timer.Interval = TimeSpan.FromMilliseconds(core.TICK_MS)
        timer.Tick += tick
        return timer

    def _wire(self):
        window = self.window
        safe = self.safe
        self.header.MouseLeftButtonDown += safe(self.on_header_down)
        self.theme_chip.Click += safe(self.on_theme_chip)
        self.shrink_btn.Click += safe(lambda s, a: self.drawer.toggle())
        self.full_btn.Click += safe(lambda s, a: self.toggle_full())
        self.close_btn.Click += safe(lambda s, a: self.request_close())
        self.logo.MouseLeftButtonDown += safe(self.on_logo)
        window.PreviewKeyDown += safe(self.on_key)
        window.Activated += safe(lambda s, a: self.apply_theme())
        window.Closed += safe(lambda s, a: self.on_closed())
        for name, edge in GRIPS.items():
            window.FindName(name).DragDelta += safe(self._grip(edge))

    def _grip(self, edge):
        def drag(sender, args):
            window = self.window
            rect = core.resize(
                (window.Left, window.Top, window.ActualWidth, window.ActualHeight),
                edge, args.HorizontalChange, args.VerticalChange,
                window.MinWidth, window.MinHeight)
            window.SizeToContent = SizeToContent.Manual
            window.Left, window.Top, window.Width, window.Height = rect
            self.full_bounds = None
        return drag

    def _load_logo(self):
        try:
            data = File.ReadAllBytes(os.path.join(HERE, 'icon.png'))
            image = BitmapImage()
            image.BeginInit()
            image.StreamSource = MemoryStream(data)
            image.CacheOption = BitmapCacheOption.OnLoad
            image.EndInit()
            image.Freeze()
            self.logo.Source = image
        except Exception as error:
            self.log(u'logo: {0}'.format(error))

    # ---------- theme ----------
    def apply_theme(self):
        mode = self.settings.get('theme', 'auto')
        name = core.resolve_theme(mode, canvas_theme(self.uiapp))
        if name == self.theme_name and mode == self.theme_mode:
            return
        self.theme_name = name
        self.theme_mode = mode
        resources = self.window.Resources
        for key, value in brn_theme.palette(name).items():
            resources[key] = SolidColorBrush(ColorConverter.ConvertFromString(value))
        self.theme_label.Text = {'auto': u'Auto', 'dark': u'Dark',
                                 'light': u'Light'}[mode]

    def on_theme_chip(self, sender, args):
        self.settings['theme'] = core.next_theme(self.settings.get('theme', 'auto'))
        core.save_settings(self.settings)
        self.apply_theme()

    # ---------- header, keys ----------
    def on_header_down(self, sender, args):
        if args.ClickCount == 2:
            if self.drawer.parked:
                self.drawer.expand()
            else:
                self.toggle_full()
            return
        before = (self.window.Left, self.window.Top)
        try:
            self.window.DragMove()
        except Exception:
            pass
        if before != (self.window.Left, self.window.Top):
            self.full_bounds = None

    def on_logo(self, sender, args):
        args.Handled = True
        if self.clicks.click(args.Timestamp):
            self._play()

    def _play(self):
        folder = HERE
        for _ in range(8):
            lib = os.path.join(folder, 'lib')
            if os.path.isdir(os.path.join(lib, 'revobim')):
                if lib not in sys.path:
                    sys.path.append(lib)
                break
            folder = os.path.dirname(folder)
        from revobim.egg import egg_hook
        egg_hook.launch(host_window=self.window, theme=self.theme_name,
                        game_key='pacman')

    def on_key(self, sender, args):
        key = args.Key
        both = ModifierKeys.Control | ModifierKeys.Shift
        if key == Key.H and Keyboard.Modifiers == both:
            self.drawer.toggle()
            args.Handled = True
        elif self.drawer.parked:
            if key in (Key.Escape, Key.Enter, Key.F11):
                self.drawer.expand()
            args.Handled = True
        elif key == Key.F11:
            self.toggle_full()
            args.Handled = True
        elif key == Key.Escape:
            self.request_close()
            args.Handled = True

    # ---------- size ----------
    def dpi_scale(self):
        try:
            source = PresentationSource.FromVisual(self.window)
            return source.CompositionTarget.TransformToDevice.M11
        except Exception:
            return 1.0

    def work_area(self):
        try:
            handle = WindowInteropHelper(self.window).Handle
            area = Screen.FromHandle(handle).WorkingArea
            scale = self.dpi_scale()
            return (area.Left / scale, area.Top / scale,
                    area.Width / scale, area.Height / scale)
        except Exception:
            area = SystemParameters.WorkArea
            return (area.Left, area.Top, area.Width, area.Height)

    def toggle_full(self):
        window = self.window
        if self.drawer.parked:
            self.drawer.expand()
            return
        window.SizeToContent = SizeToContent.Manual
        if self.full_bounds is not None:
            bounds = self.full_bounds
            self.full_bounds = None
        else:
            self.full_bounds = (window.Left, window.Top, window.ActualWidth,
                                window.ActualHeight)
            bounds = self.work_area()
        window.Left, window.Top, window.Width, window.Height = bounds

    # ---------- lifetime ----------
    def own_to_revit(self):
        try:
            WindowInteropHelper(self.window).Owner = self.uiapp.MainWindowHandle
        except Exception as error:
            self.log(u'owner: {0}'.format(error))

    def request_close(self):
        self.window.Close()

    def on_closed(self):
        self.drawer.settle()
