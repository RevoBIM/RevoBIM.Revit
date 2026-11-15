# -*- coding: utf-8 -*-
"""The window every RevoBIM tool wears: borderless chrome, theme chip, version,
shrink, full screen, close, resize grips, easter egg. Python state lives on
this object, never on the WPF Window: IronPython refuses new attributes on it."""
import fpp_clr  # noqa: F401  (must stay first)
import os
import sys
import time
import traceback
from System import Action, Array, Double, Object, TimeSpan
from System.Data import DataTable
from System.IO import File, FileAccess, FileMode, FileStream, MemoryStream
from System.Windows import (PresentationSource, SizeToContent,
                            SystemParameters, VerticalAlignment, Visibility,
                            WindowStartupLocation)
from System.Windows.Input import Key, Keyboard, ModifierKeys
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Markup import XamlReader
from System.Windows.Media import ColorConverter, SolidColorBrush
from System.Windows.Media.Imaging import BitmapCacheOption, BitmapImage
from System.Windows.Threading import DispatcherPriority, DispatcherTimer
from System.Windows.Forms import Screen

import fpp_core
import fpp_theme
from fpp_core import to_text
from fpp_drawer import Drawer
from fpp_version import __version__

HERE = os.path.dirname(os.path.abspath(__file__))
GRIPS = ('n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw')


def noop():
    pass


def brush(hex_value):
    color = ColorConverter.ConvertFromString(hex_value)
    solid = SolidColorBrush(color)
    solid.Freeze()
    return solid


def load_xaml(name):
    stream = FileStream(os.path.join(HERE, name), FileMode.Open,
                        FileAccess.Read)
    try:
        return XamlReader.Load(stream)
    finally:
        stream.Close()


def load_bitmap(path):
    image = BitmapImage()
    image.BeginInit()
    image.CacheOption = BitmapCacheOption.OnLoad
    image.StreamSource = MemoryStream(File.ReadAllBytes(path))
    image.EndInit()
    image.Freeze()
    return image


class WpfBits(object):
    """The few WPF values the drawer needs, so it can run on the bench."""
    def visibility(self, name):
        return getattr(Visibility, name)

    def size_manual(self):
        return SizeToContent.Manual

    def align_top(self):
        return VerticalAlignment.Top

    def align_stretch(self):
        return VerticalAlignment.Stretch

    def nan(self):
        return Double.NaN

    def bar_height(self, header, window):
        return header.ActualHeight + 2.0

    def make_timer(self, ms, handler):
        timer = DispatcherTimer(DispatcherPriority.Render)
        timer.Interval = TimeSpan.FromMilliseconds(ms)
        timer.Tick += handler
        return timer


def work_area(window):
    """The screen the window is on, in WPF units. WorkArea is only ever the
    primary monitor."""
    try:
        handle = WindowInteropHelper(window).Handle
        area = Screen.FromHandle(handle).WorkingArea
        source = PresentationSource.FromVisual(window)
        scale = source.CompositionTarget.TransformToDevice.M11 if source else 1.0
        return (area.Left / scale, area.Top / scale, area.Width / scale,
                area.Height / scale)
    except Exception:
        area = SystemParameters.WorkArea
        return (area.Left, area.Top, area.Width, area.Height)


class Table(object):
    """A DataTable bound once. Refilling keeps the selection by key."""
    def __init__(self, grid, names, single=False):
        self.grid = grid
        self.names = names
        self.single = single            # SelectedItems throws in single mode
        self.data = DataTable()
        for name in names:
            self.data.Columns.Add(name)
        grid.ItemsSource = self.data.DefaultView

    def fill(self, rows, keep=None):
        keep = keep if keep is not None else self.keys()
        self.data.BeginLoadData()
        self.data.Clear()
        for row in rows:
            values = [row.get(name, u'') for name in self.names]
            self.data.Rows.Add(Array[Object](values))
        self.data.EndLoadData()
        if keep:
            for item in self.data.DefaultView:
                if to_text(item['key']) in keep:
                    if self.single:
                        self.grid.SelectedItem = item
                        break
                    self.grid.SelectedItems.Add(item)

    def keys(self):
        return [to_text(item['key']) for item in self.grid.SelectedItems]


class ThemedWindow(object):
    def __init__(self, xaml_name, settings, owner=None, resizable=True):
        self.settings = settings
        self.owner = owner
        self.resizable = resizable
        self.full = False
        self.full_saved = None
        self.window = load_xaml(xaml_name)
        self.find = self.window.FindName
        self.window.Resources.MergedDictionaries.Add(load_xaml('Theme.xaml'))
        self.logo = self.find('logo_img')
        self.egg = fpp_core.EggWatcher()
        self.apply_theme()
        self.wire_chrome()

    # ----- errors -----
    def safe(self, handler):
        """Silent handlers hide dead buttons: a failure is logged and shown."""
        def run(sender=None, args=None):
            try:
                self.prove_alive()
                return handler(sender, args)
            except Exception:
                text = traceback.format_exc()
                fpp_core.log(None, text)
                fpp_core.write_text(fpp_core.error_path(), text)
                self.on_error(text)
        return run

    def prove_alive(self):
        pass

    def on_error(self, text):
        pass

    # ----- theme -----
    def theme_name(self):
        return fpp_theme.resolve(self.settings.get('theme', 'auto'),
                                 fpp_theme.revit_canvas())

    def apply_theme(self):
        values = fpp_theme.palette(self.theme_name())
        for key in sorted(values):
            self.window.Resources[key + 'Brush'] = brush(values[key])
        chip = self.find('txt_theme')
        chip.Text = fpp_theme.chip_label(self.settings.get('theme', 'auto'))

    def on_theme(self, sender, args):
        self.settings['theme'] = fpp_theme.next_setting(
            self.settings.get('theme', 'auto'))
        fpp_core.save_settings(self.settings)
        self.apply_theme()

    # ----- wiring -----
    def wire_chrome(self):
        find = self.find
        self.find('txt_version').Text = u'v' + __version__
        try:
            self.logo.Source = load_bitmap(os.path.join(HERE, 'icon.png'))
        except Exception:
            pass
        find('btn_theme').Click += self.safe(self.on_theme)
        find('btn_close').Click += self.safe(self.on_close_button)
        header = find('header_bar')
        header.MouseLeftButtonDown += self.safe(self.on_header_down)
        button = find('shrink_btn')
        button.Click += self.safe(self.on_shrink)
        grips = None
        if self.resizable:
            find('btn_full').Click += self.safe(self.on_full)
            grips = find('grip_layer')
            for name in GRIPS:
                find('grip_' + name).DragDelta += self.grip_handler(name)
        self.window.PreviewKeyDown += self.safe(self.on_chrome_key)
        self.window.Activated += self.safe(self.on_activated)
        self.drawer = Drawer(self.window, header, find('root_grid'), button,
                             find('shrink_glyph'), find('expand_glyph'),
                             WpfBits(), grips, self.drawer_siblings(),
                             work_area)
        self.attach_egg()

    def drawer_siblings(self):
        return [self.find(name) for name in self.sibling_names()]

    def sibling_names(self):
        return []

    def on_activated(self, sender, args):
        if self.settings.get('theme', 'auto') == 'auto':
            self.apply_theme()

    def on_shrink(self, sender, args):
        self.drawer.toggle()

    def on_close_button(self, sender, args):
        self.window.Close()

    def on_header_down(self, sender, args):
        if self.logo.IsMouseOver:
            return
        if args.ClickCount == 2:
            if self.drawer.parked:
                self.drawer.expand()
            elif self.resizable:
                self.toggle_full()
            return
        if self.drawer.parked and self.is_busy():
            return                     # DragMove is a modal message loop
        if self.full:
            self.leave_full()
        try:
            self.window.DragMove()
        except Exception:
            pass

    def is_busy(self):
        return False

    def on_chrome_key(self, sender, args):
        ctrl_shift = ModifierKeys.Control | ModifierKeys.Shift
        if args.Key == Key.H and Keyboard.Modifiers == ctrl_shift:
            self.drawer.toggle()
            args.Handled = True
            return
        if self.drawer.parked:
            if args.Key in (Key.Escape, Key.Enter, Key.F11):
                self.drawer.expand()
            args.Handled = True
            return
        if self.drawer.sliding:
            args.Handled = True
            return
        if args.Key == Key.F11 and self.resizable:
            self.toggle_full()
            args.Handled = True
            return
        self.on_key(args)

    def on_key(self, args):
        pass

    # ----- full screen and grips -----
    def on_full(self, sender, args):
        self.toggle_full()

    def toggle_full(self):
        if self.full:
            self.leave_full()
            return
        win = self.window
        self.full_saved = (win.Left, win.Top, win.Width, win.Height)
        area = work_area(win)
        win.Left, win.Top, win.Width, win.Height = area
        self.full = True

    def leave_full(self):
        if not self.full:
            return
        self.full = False
        win = self.window
        win.Left, win.Top, win.Width, win.Height = self.full_saved

    def grip_handler(self, name):
        def drag(sender, args):
            win = self.window
            self.full = False
            if 'e' in name:
                win.Width = max(win.MinWidth, win.Width + args.HorizontalChange)
            if 's' in name:
                win.Height = max(win.MinHeight,
                                 win.Height + args.VerticalChange)
            if 'w' in name:
                width = max(win.MinWidth, win.Width - args.HorizontalChange)
                win.Left = win.Left + win.Width - width
                win.Width = width
            if 'n' in name:
                height = max(win.MinHeight, win.Height - args.VerticalChange)
                win.Top = win.Top + win.Height - height
                win.Height = height
        return self.safe(drag)

    # ----- easter egg -----
    def attach_egg(self):
        """Tried by name; a game that will not start only writes to the log."""
        try:
            folder = HERE
            for _level in range(8):
                folder = os.path.dirname(folder)
                lib = os.path.join(folder, 'lib')
                if os.path.isdir(os.path.join(lib, 'revobim')):
                    if lib not in sys.path:
                        sys.path.append(lib)
                    break
            from revobim.egg import egg_hook
            self.egg_hook = egg_hook
        except Exception as err:
            self.egg_hook = None
            fpp_core.log(self.settings, u'egg not found: {0}'.format(err))
            return
        try:
            self.egg_hook.attach(self.logo, host_window=self.window,
                                 theme=self.theme_name)
            return
        except Exception as err:
            fpp_core.log(self.settings, u'egg attach: {0}'.format(err))
        self.logo.MouseLeftButtonDown += self.safe(self.on_logo_click)

    def on_logo_click(self, sender, args):
        if self.egg.click(time.time()):
            try:
                self.egg_hook.launch(host_window=self.window,
                                     theme=self.theme_name(),
                                     game_key='pacman')
            except Exception as err:
                fpp_core.log(self.settings, u'egg launch: {0}'.format(err))

    # ----- dialogs -----
    def place_dialog(self, dialog):
        """A dialog opening over a parked owner would centre on a 50px bar."""
        if self.window.IsLoaded:        # Owner refuses an unshown window
            dialog.Owner = self.window
        if self.drawer.parked or not self.window.IsLoaded:
            dialog.WindowStartupLocation = WindowStartupLocation.CenterScreen
        else:
            dialog.WindowStartupLocation = WindowStartupLocation.CenterOwner

    def repaint(self):
        """Render sits above Input, so this repaints without pumping clicks."""
        self.window.Dispatcher.Invoke(DispatcherPriority.Render, Action(noop))
