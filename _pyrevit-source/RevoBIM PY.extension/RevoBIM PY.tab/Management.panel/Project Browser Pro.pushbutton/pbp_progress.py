# -*- coding: utf-8 -*-
u"""Project Browser Pro - the express print progress strip.

Small, borderless, owned by Revit and placed at the bottom centre of
Revit's window. It never takes focus (ShowActivated off) so Revit keeps the
keyboard while it runs. It is the only thing an express print puts on
screen; on success it closes itself, on a failure it stays and shows why,
with a close button.
"""
import pbp_clr  # noqa: F401
from System.Windows import GridLength, GridUnitType
from System.Windows.Controls import Border, TextBlock

import pbp_log
import pbp_ui
import pbp_theme
from pbp_ui import find, safe, show
from pbp_compat import to_text


def bar_lengths(percent):
    u"""Star weights for the done / left columns of the bar."""
    try:
        value = float(percent)
    except Exception:
        value = 0.0
    value = max(0.0, min(100.0, value))
    return value, 100.0 - value


def detail_for(answer, count):
    u"""The line under the bar, from Pro Sheets' latest answer."""
    if answer is None:
        return u'Starting Pro Sheets with {0} sheet(s)...'.format(count)
    status = answer.get(u'status')
    total = answer.get(u'total') or count
    if status == u'started':
        return u'Pro Sheets is loading its last settings...'
    if status == u'running':
        line = u'{0} of {1} files'.format(answer.get(u'done', 0), total)
        if answer.get(u'current'):
            line += u' · ' + answer[u'current']
        return line
    if status == u'done':
        return u'{0} file(s) written - opening the folder.'.format(answer.get(u'files', 0))
    if status == u'failed':
        return u'Failed: ' + (answer.get(u'message') or u'see Pro Sheets')
    return u''


class ExpressProgress(object):

    def __init__(self, count, theme_name):
        self.count = count
        self.closed = False
        self.window = pbp_ui.load_xaml(u'Progress.xaml')
        pbp_theme.apply(self.window, theme_name)
        w = self.window
        self.percent_text = find(w, u'PercentText')
        self.detail = find(w, u'DetailText')
        self.done_column = find(w, u'DoneColumn')
        self.left_column = find(w, u'LeftColumn')
        self.bar_fill = find(w, u'BarFill')
        self.close_button = find(w, u'CloseButton')
        self.close_button.Click += safe(self._close_clicked, u'progress close')
        w.Closed += safe(self._closed, u'progress closed')
        w.Loaded += safe(self._place, u'progress place')
        self.set(0, detail_for(None, count))

    def show(self):
        pbp_ui.own(self.window)
        self.window.Show()

    def _place(self, sender, args):
        u"""Bottom centre of whichever screen Revit is on."""
        try:
            from System.Windows.Forms import Screen
            from System.Diagnostics import Process
            handle = Process.GetCurrentProcess().MainWindowHandle
            area = Screen.FromHandle(handle).WorkingArea
            scale = 1.0
            from System.Windows import PresentationSource
            source = PresentationSource.FromVisual(self.window)
            if source is not None:
                scale = source.CompositionTarget.TransformToDevice.M11
            left = area.Left / scale
            width = area.Width / scale
            bottom = (area.Top + area.Height) / scale
            self.window.Left = left + (width - self.window.ActualWidth) / 2.0
            self.window.Top = bottom - self.window.ActualHeight - 48
        except Exception:
            pbp_log.exc(u'progress place')

    def set(self, percent, detail):
        done, left = bar_lengths(percent)
        self.done_column.Width = GridLength(done, GridUnitType.Star)
        self.left_column.Width = GridLength(left, GridUnitType.Star)
        self.percent_text.Text = u'{0}%'.format(int(done))
        self.detail.Text = to_text(detail)

    def fail(self, message):
        self.detail.Text = to_text(message)
        self.bar_fill.SetResourceReference(Border.BackgroundProperty, u'RedBrush')
        self.percent_text.SetResourceReference(TextBlock.ForegroundProperty, u'RedBrush')
        show(self.close_button, True)

    def close(self):
        if not self.closed:
            try:
                self.window.Close()
            except Exception:
                pass

    def _close_clicked(self, sender, args):
        self.close()

    def _closed(self, sender, args):
        self.closed = True
