# -*- coding: utf-8 -*-
"""Clash Analysis - shrink to taskbar.

WindowDrawer is the WPF glue round ca_core.DrawerMachine, which holds every
decision and is proven on the logic bench. One drawer per window, main
window and prompts alike, so the gesture is identical everywhere.
"""
import ca_clr  # noqa: F401  (assembly references first)

from System import Double, EventHandler, TimeSpan
from System.Windows import (
    GridLength, GridUnitType, PresentationSource, SizeToContent,
    VerticalAlignment, Visibility, Window,
)
from System.Windows.Media import RotateTransform
from System.Windows.Forms import Screen
from System.Windows.Input import Key, Keyboard, ModifierKeys
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Threading import DispatcherTimer

import ca_core as core


def dpi_scale(window):
    try:
        src = PresentationSource.FromVisual(window)
        m = src.CompositionTarget.TransformToDevice
        return (m.M11 or 1.0, m.M22 or 1.0)
    except Exception:
        return (1.0, 1.0)


def work_area(window):
    """(left, top, width, height) in WPF units of the screen the window is
    on - not SystemParameters.WorkArea, which is always the primary."""
    try:
        handle = WindowInteropHelper(window).Handle
        wa = Screen.FromHandle(handle).WorkingArea
        sx, sy = dpi_scale(window)
        return (wa.Left / sx, wa.Top / sy, wa.Width / sx, wa.Height / sy)
    except Exception:
        return (0.0, 0.0, 1920.0, 1040.0)


def _timer(interval_ms, on_tick):
    t = DispatcherTimer()
    t.Interval = TimeSpan.FromMilliseconds(interval_ms)
    t.Tick += EventHandler(lambda s, e: on_tick())
    return t


class _Host(object):
    """The adapter DrawerMachine drives."""

    def __init__(self, drawer):
        self.d = drawer

    def bounds(self):
        w = self.d.window
        return (w.Left, w.Top, w.ActualWidth, w.ActualHeight)

    def work_area(self):
        return work_area(self.d.window)

    def header_height(self):
        try:
            return float(self.d.header.ActualHeight) + 2.0
        except Exception:
            return 44.0

    def set_bounds(self, top, height):
        w = self.d.window
        w.Top = top
        w.Height = max(1.0, height)

    def prepare(self, parking):
        d = self.d
        w = d.window
        if parking:
            d.saved_min = w.MinHeight
            w.MinHeight = 0
            w.SizeToContent = SizeToContent.Manual
            # pin the body so the grid is not re-measured every frame
            d.root.Height = d.root.ActualHeight
            d.root.VerticalAlignment = VerticalAlignment.Top
            if d.grips is not None:
                d.grips.Visibility = Visibility.Collapsed

    def release(self):
        w = self.d.window
        try:
            w.BeginAnimation(Window.TopProperty, None)
        except Exception:
            pass
        try:
            w.BeginAnimation(Window.HeightProperty, None)
        except Exception:
            pass

    def finished(self, parked):
        d = self.d
        w = d.window
        if parked:
            d.button.Tag = u'shrunk'
        else:
            d.button.Tag = None
            d.root.Height = Double.NaN
            d.root.VerticalAlignment = VerticalAlignment.Stretch
            w.MinHeight = d.saved_min
            if d.grips is not None:
                d.grips.Visibility = Visibility.Visible
        if d.on_change is not None:
            d.on_change(parked)


class WindowDrawer(object):

    def __init__(self, window, header, root, button, grips=None,
                 on_change=None):
        self.window = window
        self.header = header
        self.root = root
        self.button = button
        self.grips = grips
        self.on_change = on_change
        self.saved_min = window.MinHeight
        self.machine = core.DrawerMachine(_Host(self), _timer)
        button.Click += self._on_click

    @property
    def parked(self):
        return self.machine.parked

    def _on_click(self, sender, args):
        self.toggle()

    def toggle(self):
        return self.machine.toggle()

    def park(self):
        self.machine.park()

    def reopen(self):
        self.machine.reopen()

    def handle_key(self, args):
        """Ctrl+Shift+H toggles; while parked Escape, Enter and F11 reopen
        instead of doing what they do on an open window."""
        mods = Keyboard.Modifiers
        if args.Key == Key.H and mods == (ModifierKeys.Control | ModifierKeys.Shift):
            self.toggle()
            args.Handled = True
            return True
        if self.machine.parked and args.Key in (Key.Escape, Key.Enter, Key.F11):
            self.reopen()
            args.Handled = True
            return True
        return False


class SectionDrawer(object):
    """Collapsible section with the same drawer slide as the window:
    core.SectionMachine decides, this moves the body's height and turns the
    chevron. row: the Grid row the section sits in when it should give its
    space away while shut (a star row); None for an Auto row."""

    def __init__(self, body, chevron, row=None, is_open=True, on_change=None):
        self.body = body
        self.row = row
        self.on_change = on_change
        self.turn = RotateTransform()
        try:
            chevron.RenderTransform = self.turn
        except Exception:
            pass
        self.machine = core.SectionMachine(self, _timer, is_open=is_open)
        self.land(is_open, quiet=True)

    @property
    def is_open(self):
        return self.machine.is_open

    def toggle(self):
        return self.machine.toggle()

    def _row(self, star):
        if self.row is None:
            return
        self.row.Height = GridLength(1.0, GridUnitType.Star) if star else GridLength.Auto

    # ---- SectionMachine host
    def current(self):
        if self.body.Visibility != Visibility.Visible:
            return 0.0
        return float(self.body.ActualHeight)

    def open_target(self):
        """Lay the section out fully open, read its height, and let the
        slide start from wherever it is now."""
        self._row(True)
        self.body.Visibility = Visibility.Visible
        self.body.Height = Double.NaN
        self.body.UpdateLayout()
        return float(self.body.ActualHeight)

    def begin(self):
        self._row(False)
        self.body.Visibility = Visibility.Visible

    def apply(self, height, angle):
        self.body.Height = height
        self.turn.Angle = angle

    def land(self, is_open, quiet=False):
        self.body.Height = Double.NaN
        if is_open:
            self.body.Visibility = Visibility.Visible
            self._row(True)
            self.turn.Angle = core.CHEVRON_OPEN
        else:
            self.body.Visibility = Visibility.Collapsed
            self._row(False)
            self.turn.Angle = core.CHEVRON_SHUT
        if self.on_change is not None and not quiet:
            try:
                self.on_change(is_open)
            except Exception:
                pass
