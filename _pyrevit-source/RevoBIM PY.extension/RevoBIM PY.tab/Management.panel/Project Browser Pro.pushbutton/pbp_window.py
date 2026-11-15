# -*- coding: utf-8 -*-
u"""Project Browser Pro - the floating window.

Used when the dockable panes are not registered (the startup.py block has
not been pasted, or Revit has not been restarted since), and for a tab
popped out without them. Same browser, wrapped in the house chrome: drag by
the header, eight resize grips, full screen by bounds, close.

A borderless AllowsTransparency window cannot be resized by WPF and
maximising it covers the task bar on the wrong monitor, which is why both
are done by hand here.
"""
import pbp_clr  # noqa: F401
from System import AppDomain
from System.Windows import PresentationSource
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Forms import Screen

import pbp_log
import pbp_ui
import pbp_theme
from pbp_ui import find, safe
from pbp_tree import TAB_LABELS
from pbp_version import __version__

GRIPS = {
    u'GripN': u'n', u'GripS': u's', u'GripE': u'e', u'GripW': u'w',
    u'GripNE': u'ne', u'GripNW': u'nw', u'GripSE': u'se', u'GripSW': u'sw',
}


def _key(tab):
    # Version-stamped, so a window left by an older copy of the tool is never
    # handed to a newer one after an upgrade.
    return u'RevoBIM.PBP.window.{0}.{1}'.format(__version__, tab or u'main')


class FloatingWindow(object):

    def __init__(self, fixed_tab=None, pin=None):
        import pbp_browser
        self.fixed_tab = fixed_tab
        self.pin = pin
        self.full = False
        self.saved = None
        self.window = pbp_ui.load_xaml(u'Window.xaml')
        self.browser = pbp_browser.BrowserControl(u'window', fixed_tab, window=self, pin=pin)
        pbp_theme.apply(self.window, self.browser.theme_name)
        find(self.window, u'Host').Child = self.browser.root
        if pin:
            self.window.Title = u'RevoBIM - ' + u' \u203a '.join(pin[1])
        elif fixed_tab:
            self.window.Title = u'RevoBIM Project Browser Pro - ' + TAB_LABELS.get(fixed_tab, fixed_tab)
        for name, edges in GRIPS.items():
            find(self.window, name).DragDelta += safe(self._resizer(edges), u'grip ' + name)
        self.window.Closed += safe(self._closed, u'window closed')

    def apply_theme(self, name):
        pbp_theme.apply(self.window, name)

    def show(self):
        pbp_ui.own(self.window)
        self.window.Show()
        self.window.Activate()

    def drag(self):
        if self.full:
            self.toggle_full()
        try:
            self.window.DragMove()
        except Exception:
            pass

    def close(self):
        self.window.Close()

    def _closed(self, sender, args):
        self.browser.dispose()
        if self.pin is None:
            try:
                AppDomain.CurrentDomain.SetData(_key(self.fixed_tab), None)
            except Exception:
                pass
        pbp_log.log(u'floating window closed: {0}'.format(self.fixed_tab or u'main'))

    def _resizer(self, edges):
        def resize(sender, args):
            w = self.window
            if self.full:
                self.full = False
            dx = args.HorizontalChange
            dy = args.VerticalChange
            if u'e' in edges:
                w.Width = max(w.MinWidth, w.Width + dx)
            if u's' in edges:
                w.Height = max(w.MinHeight, w.Height + dy)
            if u'w' in edges:
                width = max(w.MinWidth, w.Width - dx)
                w.Left = w.Left + (w.Width - width)
                w.Width = width
            if u'n' in edges:
                height = max(w.MinHeight, w.Height - dy)
                w.Top = w.Top + (w.Height - height)
                w.Height = height
        return resize

    def toggle_full(self):
        w = self.window
        if self.full:
            if self.saved is not None:
                w.Left, w.Top, w.Width, w.Height = self.saved
            self.full = False
            return
        try:
            area = Screen.FromHandle(WindowInteropHelper(w).Handle).WorkingArea
            scale_x, scale_y = 1.0, 1.0
            source = PresentationSource.FromVisual(w)
            if source is not None:
                matrix = source.CompositionTarget.TransformToDevice
                scale_x, scale_y = matrix.M11, matrix.M22
            self.saved = (w.Left, w.Top, w.Width, w.Height)
            w.Left = area.Left / scale_x
            w.Top = area.Top / scale_y
            w.Width = area.Width / scale_x
            w.Height = area.Height / scale_y
            self.full = True
        except Exception:
            pbp_log.exc(u'full screen')


def place(window, placement):
    u"""Put a window at (left, top, width, height) - the size of the
    browser it came from, beside it."""
    if not placement:
        return
    try:
        from System.Windows import WindowStartupLocation
        window.WindowStartupLocation = WindowStartupLocation.Manual
        left, top, width, height = placement
        window.Left, window.Top = left, top
        window.Width = max(window.MinWidth, width)
        window.Height = max(window.MinHeight, height)
    except Exception:
        pbp_log.exc(u'place floating window')


def open_floating(tab=None, placement=None):
    u"""Show the floating browser for a tab (None: all tabs), reusing one
    that is already open."""
    try:
        existing = AppDomain.CurrentDomain.GetData(_key(tab))
    except Exception:
        existing = None
    if existing is not None:
        try:
            if existing.window.IsLoaded:
                existing.window.Activate()
                return existing
        except Exception:
            pass
    floating = FloatingWindow(tab)
    try:
        AppDomain.CurrentDomain.SetData(_key(tab), floating)
    except Exception:
        pass
    place(floating.window, placement)
    floating.show()
    return floating


def open_pinned(pin, placement=None):
    u"""A floating copy of one heading (tab, folder labels) - used when no
    pinned pane slot is free, or the panes are not registered. Each drag
    makes its own window."""
    floating = FloatingWindow(None, pin=pin)
    place(floating.window, placement)
    floating.show()
    return floating
