# -*- coding: utf-8 -*-
"""ThemedWindow: chrome, theme chip, grips, full screen, drawer and the logo easter egg."""
import pm_clr
import codecs
import os

from System.IO import File, MemoryStream
from System.Windows import (HorizontalAlignment, RoutedEventHandler, VerticalAlignment,
                            WindowStartupLocation)
from System.Windows.Controls import ContextMenu, MenuItem
from System.Windows.Controls.Primitives import Thumb
from System.Windows.Input import Cursors, Key, Keyboard, ModifierKeys
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Markup import XamlReader
from System.Windows.Media.Imaging import BitmapCacheOption, BitmapImage
from System.Windows.Forms import Screen

import pm_core as core
import pm_drawer
import pm_theme
from pm_version import __version__

HERE = os.path.dirname(os.path.abspath(__file__))
HEADER = u'''
<Border x:Name="Header" Grid.Row="0" Background="{DynamicResource TitleBg}" CornerRadius="6,6,0,0" Height="44">
  <DockPanel Margin="10,0,8,0">
    <Image x:Name="Logo" Width="26" Height="26" Margin="0,0,8,0"/>
    <TextBlock Text="RevoBIM" Foreground="{DynamicResource Blue}" FontSize="20" FontWeight="Bold" VerticalAlignment="Center"/>
    <TextBlock Text="@@TITLE@@" Foreground="{DynamicResource Orange}" FontSize="15" Margin="8,3,0,0" VerticalAlignment="Center"/>
    <StackPanel Orientation="Horizontal" DockPanel.Dock="Right" HorizontalAlignment="Right">
      <Button x:Name="ThemeBtn" Style="{DynamicResource ChipBtn}" ToolTip="Theme: Auto follows Revit's canvas"/>
      <TextBlock x:Name="VersionText" Foreground="{DynamicResource Muted}" FontSize="11" Margin="10,0,10,0" VerticalAlignment="Center"/>
      <Button x:Name="ShrinkBtn" Style="{DynamicResource ShrinkBtn}" ToolTip="Shrink to taskbar (Ctrl+Shift+H)"/>
      <Button x:Name="FullBtn" Style="{DynamicResource WinBtn}" ToolTip="Full screen (F11)">
        <Border Width="11" Height="11" BorderThickness="1.4" BorderBrush="{Binding Foreground, RelativeSource={RelativeSource AncestorType=Button}}"/>
      </Button>
      <Button x:Name="CloseBtn" Style="{DynamicResource CloseBtn}" ToolTip="Close">
        <Path Data="M0,0 L10,10 M10,0 L0,10" StrokeThickness="1.5" Stroke="{Binding Foreground, RelativeSource={RelativeSource AncestorType=Button}}"/>
      </Button>
    </StackPanel>
  </DockPanel>
</Border>
'''


def read_text(name):
    with codecs.open(os.path.join(HERE, name), 'r', 'utf-8') as src:
        return src.read()


def load_image(path):
    image = BitmapImage()
    image.BeginInit()
    image.CacheOption = BitmapCacheOption.OnLoad
    image.StreamSource = MemoryStream(File.ReadAllBytes(path))
    image.EndInit()
    image.Freeze()
    return image


class ThemedWindow(object):
    def __init__(self, layout, title, settings, owner=None):
        self.settings = settings
        self.owner = owner
        self.drawer_owner = owner.drawer if owner is not None else None
        text = core.compose_layout(read_text(layout), HEADER, title)
        self.win = XamlReader.Parse(text)
        self.theme_dict = XamlReader.Parse(read_text('Theme.xaml'))
        self.win.Resources.MergedDictionaries.Add(self.theme_dict)
        self.palette = {}
        self.full_saved = None
        self.egg_clicks = []
        self.apply_theme()
        self.e('VersionText').Text = u'v' + __version__
        self.e('CloseBtn').Click += self.on_close_button
        self.e('FullBtn').Click += self.on_full
        self.e('ThemeBtn').Click += self.on_theme
        self.e('ShrinkBtn').Click += self.on_shrink
        header = self.e('Header')
        header.MouseLeftButtonDown += self.on_header_down
        self.win.PreviewKeyDown += self.on_key
        self.win.Activated += self.on_activated
        self.win.Closed += self.on_closed
        self.grips = self.e('Grips')
        self._add_grips()
        self.drawer = pm_drawer.Drawer(self.win, header, self.e('Root'), self.e('ShrinkBtn'),
                                       self.grips, self.work_area, self.drawer_owner)
        try:
            logo = self.e('Logo')
            logo.Source = load_image(os.path.join(HERE, 'icon.png'))
            logo.MouseLeftButtonDown += self.on_logo
        except Exception:
            pass
        if owner is not None:
            self.win.Owner = owner.win
            placement = (WindowStartupLocation.CenterScreen if owner.drawer.parked
                         else WindowStartupLocation.CenterOwner)
            self.win.WindowStartupLocation = placement

    def e(self, name):
        return self.win.FindName(name)

    # ---- theme

    def apply_theme(self):
        setting = self.settings.get('theme', 'follow')
        name = core.resolve_theme(setting, pm_theme.canvas_is_dark())
        self.palette = pm_theme.brushes(name)
        for key in self.palette:
            self.win.Resources[key] = self.palette[key]
        self.e('ThemeBtn').Content = core.theme_label(setting)
        self.theme_name = name

    def on_theme(self, sender, args):
        self.settings['theme'] = core.next_theme(self.settings.get('theme'))
        core.save_settings(core.settings_path(), self.settings)
        self.apply_theme()

    def on_activated(self, sender, args):
        if self.settings.get('theme') == 'follow':
            self.apply_theme()

    # ---- window behaviour

    def work_area(self):
        handle = WindowInteropHelper(self.win).Handle
        area = Screen.FromHandle(handle).WorkingArea
        scale = 1.0
        try:
            from System.Windows import PresentationSource
            scale = PresentationSource.FromVisual(self.win).CompositionTarget.TransformToDevice.M11
        except Exception:
            pass
        return (area.Left / scale, area.Top / scale, area.Right / scale, area.Bottom / scale)

    def _add_grips(self):
        strip = 5
        H = HorizontalAlignment
        V = VerticalAlignment
        spec = (
            ('l', H.Left, V.Stretch, strip, None, Cursors.SizeWE),
            ('r', H.Right, V.Stretch, strip, None, Cursors.SizeWE),
            ('t', H.Stretch, V.Top, None, strip, Cursors.SizeNS),
            ('b', H.Stretch, V.Bottom, None, strip, Cursors.SizeNS),
            ('tl', H.Left, V.Top, 9, 9, Cursors.SizeNWSE),
            ('br', H.Right, V.Bottom, 9, 9, Cursors.SizeNWSE),
            ('tr', H.Right, V.Top, 9, 9, Cursors.SizeNESW),
            ('bl', H.Left, V.Bottom, 9, 9, Cursors.SizeNESW),
        )
        for code, halign, valign, width, height, cursor in spec:
            thumb = Thumb()
            thumb.Opacity = 0.0
            thumb.HorizontalAlignment = halign
            thumb.VerticalAlignment = valign
            thumb.Cursor = cursor
            if width:
                thumb.Width = width
            if height:
                thumb.Height = height
            thumb.DragDelta += self._grip_handler(code)
            self.grips.Children.Add(thumb)

    def _grip_handler(self, code):
        def handler(sender, args):
            self.full_saved = None
            win = self.win
            if 'r' in code:
                win.Width = max(win.MinWidth, win.ActualWidth + args.HorizontalChange)
            if 'b' in code:
                win.Height = max(win.MinHeight, win.ActualHeight + args.VerticalChange)
            if 'l' in code:
                width = max(win.MinWidth, win.ActualWidth - args.HorizontalChange)
                win.Left += win.ActualWidth - width
                win.Width = width
            if 't' in code:
                height = max(win.MinHeight, win.ActualHeight - args.VerticalChange)
                win.Top += win.ActualHeight - height
                win.Height = height
        return handler

    def on_header_down(self, sender, args):
        if args.ClickCount == 2:
            if self.drawer.parked:
                self.drawer.toggle()
            else:
                self.on_full(None, None)
            return
        try:
            self.full_saved = None
            self.win.DragMove()
        except Exception:
            pass

    def on_full(self, sender, args):
        if self.drawer.parked:
            self.drawer.toggle()
            return
        win = self.win
        if self.full_saved is not None:
            win.Left, win.Top, win.Width, win.Height = self.full_saved
            self.full_saved = None
            return
        self.full_saved = (win.Left, win.Top, win.ActualWidth, win.ActualHeight)
        left, top, right, bottom = self.work_area()
        win.Left, win.Top, win.Width, win.Height = left, top, right - left, bottom - top

    def on_shrink(self, sender, args):
        self.drawer.toggle()

    def on_key(self, sender, args):
        ctrl_shift = Keyboard.Modifiers == (ModifierKeys.Control | ModifierKeys.Shift)
        if ctrl_shift and args.Key == Key.H:
            self.drawer.toggle()
            args.Handled = True
        elif self.drawer.parked and args.Key in (Key.Escape, Key.Enter, Key.F11):
            self.drawer.toggle()
            args.Handled = True
        elif args.Key == Key.F11:
            self.on_full(None, None)
            args.Handled = True
        elif args.Key == Key.Escape and self.escape_closes():
            self.win.Close()
            args.Handled = True

    def escape_closes(self):
        return True

    def on_close_button(self, sender, args):
        self.win.Close()

    def on_closed(self, sender, args):
        self.drawer.settle()

    def on_logo(self, sender, args):
        """Three slow clicks: 250ms floor, 2s ceiling."""
        stamp = args.Timestamp
        if self.egg_clicks and stamp == self.egg_clicks[-1]:
            return
        if self.egg_clicks and not (250 <= stamp - self.egg_clicks[-1] <= 2000):
            self.egg_clicks = []
        self.egg_clicks.append(stamp)
        if len(self.egg_clicks) >= 3:
            self.egg_clicks = []
            try:
                from revobim.egg import egg_hook
                egg_hook.launch(self.win, self.theme_name, 'pacman')
            except Exception as error:
                core.log(u'egg: {0}'.format(error), self.settings)

    # ---- menus: a popup has no window above it, so it carries the theme itself

    def new_menu(self):
        menu = ContextMenu()
        menu.Resources.MergedDictionaries.Add(self.theme_dict)
        for key in self.palette:
            menu.Resources[key] = self.palette[key]
        menu.SetResourceReference(ContextMenu.StyleProperty, 'ThemedMenu')
        return menu

    def menu_item(self, menu, text, handler, icon=None, enabled=True):
        item = MenuItem()
        item.Header = text
        item.IsEnabled = enabled
        item.SetResourceReference(MenuItem.StyleProperty, 'ThemedMenuItem')
        if icon is not None:
            item.Icon = icon
        item.Click += RoutedEventHandler(handler)
        menu.Items.Add(item)
        return item
